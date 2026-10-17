import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import Client, TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.utils import timezone

from config.celery import app
from .jobs import claim_job, finish_job, recover_jobs, relay_once, run_job
from .models import Job, Match, OutboxEvent, RateBucket
from .services import ProviderError, TransientProviderError, extract_evidence
from .tasks import process_job

REQUIREMENTS = [{"skill": "Python", "weight": 3}, {"skill": "Django", "weight": 2}]
SOURCE = "Fictional candidate built Python APIs."


def make_job(owner, **changes):
    now = timezone.now()
    values = {"owner": owner, "idempotency_key": uuid.uuid4(), "payload_hash": "a" * 64,
              "job_title": "Synthetic async role", "requirements": REQUIREMENTS,
              "resume_text": SOURCE, "provider": "demo", "request_id": uuid.uuid4(),
              "available_at": now, "wake_at": now + timedelta(seconds=30),
              "deadline_at": now + timedelta(minutes=10)}
    values.update(changes)
    job = Job.objects.create(**values)
    OutboxEvent.objects.create(job=job, available_at=values["available_at"])
    return job


@override_settings(MATCH_PROVIDER="demo")
class JobAPITests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("async-alice")
        self.other = get_user_model().objects.create_user("async-bob")
        self.client.force_login(self.owner)

    def form(self, **changes):
        return {"job_title": "Synthetic async role", "requirements": json.dumps(REQUIREMENTS), "resume_text": SOURCE, **changes}

    def post(self, key=None, **changes):
        return self.client.post("/api/jobs/", self.form(**changes), HTTP_IDEMPOTENCY_KEY=str(key or uuid.uuid4()))

    def test_accepts_without_running_provider_and_replays_without_charging_quota(self):
        key = uuid.uuid4()
        with patch("matching.jobs.extract_evidence") as provider:
            first = self.post(key)
            second = self.post(key)
        self.assertEqual((first.status_code, second.status_code), (202, 202))
        self.assertEqual(first.json(), second.json())
        self.assertEqual(first.json()["status"], "queued")
        self.assertEqual(first.json()["attempts"], 0)
        self.assertIsNone(first.json()["match"])
        self.assertIsNone(first.json()["error_code"])
        self.assertEqual(Job.objects.get().resume_text, SOURCE)
        self.assertEqual(OutboxEvent.objects.count(), 1)
        self.assertEqual(RateBucket.objects.get(key__startswith="match:").count, 1)
        provider.assert_not_called()
        self.assertNotIn(SOURCE, first.content.decode())

    def test_same_key_conflicting_payload_is_409(self):
        key = uuid.uuid4()
        self.post(key)
        self.assertEqual(self.post(key, resume_text="A different fictional Python résumé").status_code, 409)
        self.assertEqual(Job.objects.count(), 1)
        self.assertEqual(RateBucket.objects.get(key__startswith="match:").count, 1)

    def test_key_auth_scope_and_csrf(self):
        self.assertEqual(self.client.post("/api/jobs/", self.form()).status_code, 400)
        self.assertEqual(self.client.post("/api/jobs/", self.form(), HTTP_IDEMPOTENCY_KEY="invalid").status_code, 400)
        key = uuid.uuid4()
        job_id = self.post(key).json()["id"]
        self.client.force_login(self.other)
        self.assertEqual(self.client.get("/api/jobs/").json(), {"jobs": []})
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}/").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/jobs/{job_id}/").status_code, 404)
        self.assertEqual(self.post(key).status_code, 202)
        self.assertEqual(Job.objects.count(), 2)
        guarded = Client(enforce_csrf_checks=True)
        guarded.force_login(self.owner)
        self.assertEqual(guarded.post("/api/jobs/", self.form(), HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4())).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get("/api/jobs/").status_code, 401)
        self.assertEqual(self.post().status_code, 401)

    def test_job_outbox_and_quota_roll_back_together(self):
        with patch("matching.views.OutboxEvent.objects.create", side_effect=RuntimeError("simulated crash")), self.assertRaises(RuntimeError):
            self.post()
        self.assertEqual(Job.objects.count(), 0)
        self.assertEqual(OutboxEvent.objects.count(), 0)
        self.assertEqual(RateBucket.objects.filter(key__startswith="match:").count(), 0)

    @override_settings(MATCH_DAILY_LIMIT=1)
    def test_quota_applies_only_to_new_logical_jobs(self):
        key = uuid.uuid4()
        self.assertEqual(self.post(key).status_code, 202)
        self.assertEqual(self.post(key).status_code, 202)
        self.assertEqual(self.post().status_code, 429)

    def test_delete_queued_job_erases_source_and_dispatch(self):
        job_id = self.post().json()["id"]
        self.assertEqual(self.client.delete(f"/api/jobs/{job_id}/").status_code, 200)
        run_job(job_id)
        self.assertEqual((Job.objects.count(), OutboxEvent.objects.count(), Match.objects.count()), (0, 0, 0))

    def test_deleting_either_match_or_job_erases_completed_job_and_result(self):
        job_id = self.post().json()["id"]
        run_job(job_id)
        match = Match.objects.get(job_id=job_id)
        self.assertEqual(self.client.delete(f"/api/matches/{match.id}/").status_code, 200)
        self.assertEqual((Job.objects.count(), Match.objects.count(), OutboxEvent.objects.count()), (0, 0, 0))
        job_id = self.post().json()["id"]
        run_job(job_id)
        result = self.client.get(f"/api/jobs/{job_id}/").json()
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["match"]["score"], 60)
        self.assertEqual(Job.objects.get(pk=job_id).resume_text, "")
        self.assertEqual(self.client.delete(f"/api/jobs/{job_id}/").status_code, 200)
        self.assertEqual((Job.objects.count(), OutboxEvent.objects.count(), Match.objects.count()), (0, 0, 0))


@override_settings(MATCH_PROVIDER="demo")
class JobStateTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("state-owner")

    def test_duplicate_deliveries_create_one_result_and_clear_source(self):
        job = make_job(self.owner)
        run_job(job.id)
        run_job(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, "succeeded")
        self.assertEqual(job.attempts, 1)
        self.assertEqual(job.resume_text, "")
        self.assertEqual(Match.objects.filter(job=job).count(), 1)

    def test_bad_evidence_is_terminal_and_source_is_cleared(self):
        job = make_job(self.owner)
        with patch("matching.jobs.extract_evidence", side_effect=ProviderError("DO-NOT-STORE")):
            run_job(job.id)
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_code, job.resume_text), ("failed", "invalid_evidence", ""))
        self.assertEqual(Match.objects.count(), 0)

    @override_settings(JOB_RETRY_SECONDS=0)
    def test_transient_retries_use_new_events_and_exhaust_after_three_claims(self):
        job = make_job(self.owner)
        first_event = job.dispatches.get().id
        with patch("matching.jobs.extract_evidence", side_effect=TransientProviderError("DO-NOT-STORE")) as provider:
            run_job(job.id)
            job.refresh_from_db()
            self.assertEqual((job.status, job.attempts, job.resume_text), ("queued", 1, SOURCE))
            self.assertEqual(job.dispatches.count(), 2)
            self.assertTrue(job.dispatches.filter(pk=first_event).exists())
            run_job(job.id)
            run_job(job.id)
            run_job(job.id)
        job.refresh_from_db()
        self.assertEqual((job.status, job.attempts, job.error_code, job.resume_text), ("failed", 3, "retry_exhausted", ""))
        self.assertEqual(job.dispatches.count(), 3)
        self.assertEqual(provider.call_count, 3)

    def test_backoff_prevents_early_delivery_from_claiming(self):
        job = make_job(self.owner)
        with patch("matching.jobs.extract_evidence", side_effect=TransientProviderError()):
            run_job(job.id)
        self.assertIsNone(claim_job(job.id))
        job.refresh_from_db()
        self.assertEqual(job.attempts, 1)

    @override_settings(JOB_RETRY_SECONDS=0)
    def test_expired_lease_is_recovered_and_stale_completion_is_fenced(self):
        job = make_job(self.owner)
        stale = claim_job(job.id)
        Job.objects.filter(pk=job.id).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(recover_jobs(), 1)
        current = claim_job(job.id)
        evidence = extract_evidence(SOURCE, REQUIREMENTS)
        self.assertFalse(finish_job(stale, evidence=evidence))
        self.assertTrue(finish_job(current, evidence=evidence))
        job.refresh_from_db()
        self.assertEqual((job.attempts, job.status), (2, "succeeded"))
        self.assertEqual(Match.objects.filter(job=job).count(), 1)

    def test_completion_after_lease_expiry_without_recovery_cannot_commit(self):
        job = make_job(self.owner)
        claim = claim_job(job.id)
        Job.objects.filter(pk=job.id).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        self.assertFalse(finish_job(claim, evidence=extract_evidence(SOURCE, REQUIREMENTS)))
        self.assertEqual(Match.objects.count(), 0)

    def test_total_deadline_clears_source_for_queued_and_running(self):
        queued = make_job(self.owner, deadline_at=timezone.now() - timedelta(seconds=1))
        running = make_job(self.owner)
        claim_job(running.id)
        Job.objects.filter(pk=running.id).update(deadline_at=timezone.now() - timedelta(seconds=1))
        recover_jobs()
        for job in [queued, running]:
            job.refresh_from_db()
            self.assertEqual((job.status, job.error_code, job.resume_text), ("failed", "deadline_exceeded", ""))

    def test_stale_queued_confirmation_gets_new_dispatch_without_resetting_old(self):
        job = make_job(self.owner, wake_at=timezone.now() - timedelta(seconds=1))
        old = job.dispatches.get()
        old.sent_at = timezone.now()
        old.save()
        recover_jobs()
        old.refresh_from_db()
        self.assertIsNotNone(old.sent_at)
        self.assertEqual(job.dispatches.count(), 2)
        self.assertEqual(job.dispatches.filter(sent_at__isnull=True).count(), 1)
        recover_jobs()
        self.assertEqual(job.dispatches.count(), 2)

    def test_stale_queued_unsent_event_does_not_multiply(self):
        job = make_job(self.owner, wake_at=timezone.now() - timedelta(seconds=1))
        recover_jobs()
        self.assertEqual(job.dispatches.count(), 1)

    def test_publisher_outage_keeps_event_unsent(self):
        job = make_job(self.owner)
        with patch("matching.jobs.publish_job", side_effect=ConnectionError("DO-NOT-LOG")):
            self.assertEqual(relay_once(), 0)
        self.assertIsNone(job.dispatches.get().sent_at)
        with patch("matching.jobs.publish_job") as publish:
            self.assertEqual(relay_once(), 1)
        publish.assert_called_once_with(job.id)
        self.assertIsNotNone(job.dispatches.get().sent_at)

    def test_crash_after_confirm_replays_same_event_without_duplicate_result(self):
        job = make_job(self.owner)
        with patch("matching.jobs.publish_job") as publish, patch.object(OutboxEvent, "save", side_effect=RuntimeError("crash after broker confirmation")):
            with self.assertRaises(RuntimeError):
                relay_once()
            publish.assert_called_once_with(job.id)
        self.assertIsNone(job.dispatches.get().sent_at)
        with patch("matching.jobs.publish_job") as publish:
            relay_once()
            publish.assert_called_once_with(job.id)
        run_job(job.id)
        run_job(job.id)
        self.assertEqual(Match.objects.filter(job=job).count(), 1)

    def test_legacy_results_survive_new_job_completion(self):
        old = Match.objects.create(owner=self.owner, job_title="Legacy synthetic role", score=50, provider="demo", requirements=[], request_id=uuid.uuid4())
        run_job(make_job(self.owner).id)
        self.assertTrue(Match.objects.filter(pk=old.pk, job__isnull=True).exists())

    def test_transport_and_task_safety_configuration(self):
        self.assertTrue(app.conf.task_acks_late)
        self.assertTrue(app.conf.task_reject_on_worker_lost)
        self.assertEqual(app.conf.worker_prefetch_multiplier, 1)
        self.assertFalse(app.conf.worker_enable_remote_control)
        self.assertEqual(app.conf.accept_content, ["json"])
        self.assertTrue(app.conf.task_ignore_result)
        self.assertIsNone(app.conf.result_backend)
        self.assertFalse(app.conf.task_always_eager)
        self.assertTrue(app.conf.broker_transport_options["confirm_publish"])
        queue = app.amqp.queues["resume.match"]
        self.assertTrue(queue.durable and queue.exchange.durable)
        self.assertEqual(queue.routing_key, "resume.match")
        self.assertLess(app.conf.task_time_limit, settings.JOB_LEASE_SECONDS)

    def test_unexpected_task_failure_never_reaches_celery_exception_formatter(self):
        with patch("matching.tasks.run_job", side_effect=RuntimeError("PRIVATE-SOURCE-DO-NOT-LOG")), self.assertLogs("matching.audit", level="ERROR") as captured:
            self.assertIsNone(process_job.run(str(uuid.uuid4())))
        self.assertNotIn("PRIVATE-SOURCE", "\n".join(captured.output))


@override_settings(MATCH_PROVIDER="demo")
class PostgreSQLConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("concurrent-owner")

    def in_thread(self, callback):
        close_old_connections()
        try:
            return callback()
        finally:
            connection.close()

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_same_key_admission_creates_one_job_and_one_charge(self):
        clients = [Client(), Client()]
        for client in clients:
            client.force_login(self.owner)
        barrier = threading.Barrier(2)
        key = str(uuid.uuid4())
        form = {"job_title": "Concurrent synthetic role", "resume_text": SOURCE, "requirements": json.dumps(REQUIREMENTS)}
        def submit(client):
            barrier.wait(timeout=5)
            response = client.post("/api/jobs/", form, HTTP_IDEMPOTENCY_KEY=key)
            return response.status_code, response.json()["id"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.in_thread, lambda client=client: submit(client)) for client in clients]
            results = [future.result(timeout=10) for future in futures]
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0][0], 202)
        self.assertEqual(Job.objects.count(), 1)
        self.assertEqual(OutboxEvent.objects.count(), 1)
        self.assertEqual(RateBucket.objects.get(key__startswith="match:").count, 1)

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_duplicate_worker_runs_provider_once_outside_transaction(self):
        job = make_job(self.owner)
        entered, release = threading.Event(), threading.Event()
        def provider(*args, **kwargs):
            self.assertFalse(connection.in_atomic_block)
            entered.set()
            if not release.wait(timeout=5):
                raise AssertionError("test release timed out")
            return extract_evidence(SOURCE, REQUIREMENTS)
        with patch("matching.jobs.extract_evidence", side_effect=provider) as mocked, ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.in_thread, lambda: run_job(job.id))
            try:
                self.assertTrue(entered.wait(timeout=5))
                pool.submit(self.in_thread, lambda: run_job(job.id)).result(timeout=3)
            finally:
                release.set()
            first.result(timeout=5)
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(Match.objects.filter(job=job).count(), 1)

    @skipUnlessDBFeature("has_select_for_update")
    def test_delete_locks_out_completion_until_cascade_finishes(self):
        job = make_job(self.owner)
        claim = claim_job(job.id)
        client = Client()
        client.force_login(self.owner)
        entered, release = threading.Event(), threading.Event()
        original_delete = Job.delete
        def paused_delete(instance, *args, **kwargs):
            entered.set()
            if not release.wait(timeout=5):
                raise AssertionError("test release timed out")
            return original_delete(instance, *args, **kwargs)
        with patch.object(Job, "delete", paused_delete), ThreadPoolExecutor(max_workers=2) as pool:
            deletion = pool.submit(self.in_thread, lambda: client.delete(f"/api/jobs/{job.id}/").status_code)
            try:
                self.assertTrue(entered.wait(timeout=5))
                completion = pool.submit(self.in_thread, lambda: finish_job(claim, evidence=extract_evidence(SOURCE, REQUIREMENTS)))
                self.assertFalse(threading.Event().wait(0.1) or completion.done())
            finally:
                release.set()
            self.assertEqual(deletion.result(timeout=5), 200)
            self.assertFalse(completion.result(timeout=5))
        self.assertEqual((Job.objects.count(), Match.objects.count(), OutboxEvent.objects.count()), (0, 0, 0))
