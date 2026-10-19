import json
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from .admission import AdmissionDenied, reserve_admission, release_admission, sample_supply
from .events import lock_stream
from .jobs import run_job
from .models import AdmissionHealth, Job, RateBucket, WorkerSupply
from .test_jobs import make_job
from .test_storage_support import StorageBoundaryMixin


class AdmissionTests(StorageBoundaryMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.owner = get_user_model().objects.create_user("admission-owner")
        self.client.force_login(self.owner)
        policy = override_settings(GLOBAL_ADMISSION_PER_SECOND=100, GLOBAL_ADMISSION_MAX_ACTIVE=3, OWNER_ACTIVE_JOB_LIMIT=2, MATCH_PROVIDER="demo", OTEL_LOGS_ENDPOINT="")
        policy.enable()
        self.addCleanup(policy.disable)

    def post(self, key=None):
        return self.client.post("/api/jobs/", {"job_title": "Synthetic role", "requirements": json.dumps([{"skill":"Python","weight":1}]), "resume_text": "Synthetic Python developer"}, HTTP_IDEMPOTENCY_KEY=str(key or uuid.uuid4()))

    def test_duplicate_recovers_before_stale_health_and_does_not_reserve_twice(self):
        key = uuid.uuid4()
        first = self.post(key)
        AdmissionHealth.objects.update(sampled_at=None)
        self.assertEqual(self.post(key).json()["id"], first.json()["id"])
        self.assertEqual(AdmissionHealth.objects.get().active, 1)
        rejected = self.post()
        self.assertEqual((rejected.status_code, rejected["Retry-After"]), (503, "2"))
        self.assertEqual(Job.objects.count(), 1)

    def test_fairness_and_supply_failures_leave_no_rows_or_daily_charge(self):
        for fields in [{"broker_ready":False}, {"worker_ready":False}, {"sampled_at":timezone.now()-timedelta(seconds=20)}, {"oldest_queued_at":timezone.now()-timedelta(seconds=61)}, {"active":3}, {"queued_sample":3}]:
            AdmissionHealth.objects.update(active=0, queued_sample=0, sampled_at=timezone.now(), oldest_queued_at=None, broker_ready=True, worker_ready=True)
            AdmissionHealth.objects.update(**fields)
            self.assertEqual(self.post().status_code, 503)
            self.assertEqual((Job.objects.count(), RateBucket.objects.filter(key__startswith="match:").count()), (0,0))
        AdmissionHealth.objects.update(active=0, queued_sample=0, oldest_queued_at=None, sampled_at=timezone.now(), broker_ready=True, worker_ready=True)
        self.assertEqual(self.post().status_code,202)
        self.assertEqual(self.post().status_code,202)
        self.assertEqual(self.post().status_code,429)
        self.assertEqual(AdmissionHealth.objects.get().active,2)

    @override_settings(GLOBAL_ADMISSION_PER_SECOND=1)
    def test_rate_limit_has_retry_after_without_consuming_quota(self):
        with patch("matching.admission.timezone.now", return_value=timezone.now()):
            self.assertEqual(self.post().status_code,202)
            response=self.post()
        self.assertEqual((response.status_code,response["Retry-After"]),(429,"1"))
        self.assertEqual(AdmissionHealth.objects.get().active,1)
        self.assertEqual(RateBucket.objects.get(key__startswith="match:").count,1)

    @override_settings(MATCH_DAILY_LIMIT=1)
    def test_daily_limit_rolls_back_deployment_reservation(self):
        self.post()
        self.assertEqual(self.post().status_code,429)
        self.assertEqual(AdmissionHealth.objects.get().active,1)
        self.assertEqual(AdmissionHealth.objects.get().rate_count,1)

    def test_terminal_and_delete_release_exactly_once(self):
        first=self.post().json()["id"]
        run_job(first)
        run_job(first)
        self.assertEqual(AdmissionHealth.objects.get().active,0)
        self.client.delete(f"/api/jobs/{first}/")
        self.assertEqual(AdmissionHealth.objects.get().active,0)
        second=self.post().json()["id"]
        self.assertEqual(AdmissionHealth.objects.get().active,1)
        self.client.delete(f"/api/jobs/{second}/")
        self.assertEqual(AdmissionHealth.objects.get().active,0)

    @override_settings(JOB_RETRY_SECONDS=0)
    def test_retry_keeps_reservation_until_terminal_outcome(self):
        from .services import TransientProviderError
        pk=self.post().json()["id"]
        with patch("matching.jobs.extract_evidence",side_effect=TransientProviderError()):
            run_job(pk)
            self.assertEqual(AdmissionHealth.objects.get().active,1)
            run_job(pk)
            run_job(pk)
        self.assertEqual((Job.objects.get(pk=pk).status, AdmissionHealth.objects.get().active),("failed",0))

    def test_failed_creation_rolls_back_supply_and_no_global_expiry_delete(self):
        expired=RateBucket.objects.create(key="expired",expires_at=timezone.now()-timedelta(days=1))
        with patch("matching.views.Document.objects.create",side_effect=RuntimeError("synthetic failure")):
            with self.assertRaises(RuntimeError): self.post()
        self.assertEqual(AdmissionHealth.objects.get().active,0)
        self.assertTrue(RateBucket.objects.filter(pk=expired.pk).exists())

    def test_health_uses_live_worker_and_bounded_indexed_queue_sample(self):
        WorkerSupply.objects.create(last_seen=timezone.now())
        for _ in range(5): make_job(self.owner)
        sample_supply(True)
        row=AdmissionHealth.objects.get()
        self.assertTrue(row.worker_ready)
        self.assertEqual(row.queued_sample,4)
        self.assertIsNotNone(row.oldest_queued_at)
        WorkerSupply.objects.update(last_seen=timezone.now()-timedelta(minutes=2))
        sample_supply(False)
        row.refresh_from_db()
        self.assertFalse(row.broker_ready or row.worker_ready)


    def test_terminal_repair_is_bounded_and_once_only(self):
        from .admission import repair_terminal_reservations
        first=self.post().json()["id"]
        second=self.post().json()["id"]
        Job.objects.update(status="succeeded")  # Emulate old worker outcome, no new release signal.
        repair_terminal_reservations(1)
        self.assertEqual(AdmissionHealth.objects.get().active,1)
        repair_terminal_reservations(1)
        repair_terminal_reservations(1)
        self.assertEqual(AdmissionHealth.objects.get().active,0)


@override_settings(GLOBAL_ADMISSION_PER_SECOND=100000, GLOBAL_ADMISSION_MAX_ACTIVE=3, OWNER_ACTIVE_JOB_LIMIT=2,OTEL_LOGS_ENDPOINT="")
class AdmissionConcurrencyTests(TransactionTestCase):
    def setUp(self):
        from django.db import connection
        if connection.vendor != "postgresql": self.skipTest("PostgreSQL row locking")
        self.owners=[get_user_model().objects.create_user("admission-concurrent-"+str(i)) for i in range(8)]
        AdmissionHealth.objects.update_or_create(pk="jobs",defaults={"active":0,"sampled_at":timezone.now(),"broker_ready":True,"worker_ready":True})

    def test_global_limit_is_atomic_across_owners(self):
        from concurrent.futures import ThreadPoolExecutor
        from django.db import connections
        import threading
        barrier=threading.Barrier(8)
        def reserve(owner):
            try:
                barrier.wait(timeout=10)
                with transaction.atomic():
                    lock_stream(owner.pk)
                    reserve_admission(owner.pk,timezone.now())
                    make_job(owner,admission_reserved=True)
                return True
            except AdmissionDenied: return False
            finally: connections.close_all()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(reserve,self.owners))
        self.assertEqual(sum(results),3)
        self.assertEqual(AdmissionHealth.objects.get().active,3)
        self.assertEqual(Job.objects.filter(admission_reserved=True).count(),3)

    @override_settings(GLOBAL_ADMISSION_MAX_ACTIVE=32)
    def test_short_global_row_contention_at_100_per_second_planning_input(self):
        from concurrent.futures import ThreadPoolExecutor
        from django.db import connections
        import time
        durations=[]
        def cycle(index):
            owner=self.owners[index % len(self.owners)]
            try:
                started=time.monotonic()
                with transaction.atomic():
                    lock_stream(owner.pk)
                    reserve_admission(owner.pk,timezone.now())
                    job=make_job(owner,admission_reserved=True)
                    Job.objects.filter(pk=job.pk).update(status="succeeded")
                    release_admission(job)
                return time.monotonic()-started
            finally: connections.close_all()
        started=time.monotonic()
        with ThreadPoolExecutor(max_workers=8) as pool:
            durations=list(pool.map(cycle,range(200)))
        elapsed=time.monotonic()-started
        throughput=200/elapsed
        p95=sorted(durations)[189]*1000
        print("Admission mutex measurement: operations=200 workers=8 throughput_per_second=%.2f p95_ms=%.2f" % (throughput,p95))
        self.assertEqual(AdmissionHealth.objects.get().active,0)
        self.assertGreaterEqual(throughput,100,"Local contention measurement did not meet planning input; no capacity claim permitted")
