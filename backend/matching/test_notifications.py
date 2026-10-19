"""Durability, isolation and privacy at the completion-to-inbox boundary."""
from datetime import timedelta
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from .documents import tombstone
from .jobs import claim_job, finish_job, recover_jobs, run_job
from .models import CompletionNotification, Document, Job, Match
from .notifications import persist_completion
from .services import ProviderError, TransientProviderError, extract_evidence
from .test_jobs import make_job, REQUIREMENTS, SOURCE
from .test_storage_support import StorageBoundaryMixin


@override_settings(MATCH_PROVIDER="demo", OTEL_LOGS_ENDPOINT="")
class NotificationTests(StorageBoundaryMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.owner = get_user_model().objects.create_user("notification-owner")
        self.other = get_user_model().objects.create_user("notification-other")
        self.client.force_login(self.owner)

    def complete(self, owner=None, **changes):
        job = make_job(owner or self.owner, **changes)
        run_job(job.id)
        job.refresh_from_db()
        return job, job.completion_notification

    def test_success_is_durable_once_across_deliveries_and_stale_completion(self):
        job = make_job(self.owner)
        claim = claim_job(job.id)
        self.assertTrue(finish_job(claim, evidence=extract_evidence(SOURCE, REQUIREMENTS)))
        run_job(job.id)
        self.assertFalse(finish_job(claim, evidence=extract_evidence(SOURCE, REQUIREMENTS)))
        self.assertEqual(CompletionNotification.objects.filter(job=job).count(), 1)
        notice = CompletionNotification.objects.get()
        self.assertEqual(notice.status, "succeeded")
        self.assertIsNone(notice.read_at)

    def test_notice_failure_rolls_back_outcome_and_match_and_emits_nothing(self):
        job = make_job(self.owner)
        claim = claim_job(job.id)
        with patch("matching.notifications.CompletionNotification.objects.get_or_create", side_effect=IntegrityError("synthetic failure")), patch("matching.notifications.emit") as emitted, self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(IntegrityError):
                finish_job(claim, evidence=extract_evidence(SOURCE, REQUIREMENTS))
        job.refresh_from_db()
        self.assertEqual(job.status, "running")
        self.assertEqual(Match.objects.count(), 0)
        self.assertEqual(CompletionNotification.objects.count(), 0)
        emitted.assert_not_called()

    def test_outer_rollback_removes_outcome_and_notice(self):
        job = make_job(self.owner)
        claim = claim_job(job.id)
        with patch("matching.notifications.emit") as emitted, self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    finish_job(claim, evidence=extract_evidence(SOURCE, REQUIREMENTS))
                    raise RuntimeError("synthetic rollback")
        job.refresh_from_db()
        self.assertEqual(job.status, "running")
        self.assertEqual((Match.objects.count(), CompletionNotification.objects.count()), (0, 0))
        emitted.assert_not_called()

    def test_notification_failure_also_rolls_back_terminal_deadline_failure(self):
        job = make_job(self.owner, deadline_at=timezone.now() - timedelta(seconds=1))
        with patch("matching.notifications.CompletionNotification.objects.get_or_create", side_effect=IntegrityError("synthetic failure")):
            with self.assertRaises(IntegrityError):
                claim_job(job.id)
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_code), ("queued", ""))
        self.assertFalse(CompletionNotification.objects.exists())

    @override_settings(JOB_RETRY_SECONDS=0)
    def test_retries_do_not_notify_but_terminal_exhaustion_does(self):
        job = make_job(self.owner)
        with patch("matching.jobs.extract_evidence", side_effect=TransientProviderError()):
            run_job(job.id)
            self.assertEqual(CompletionNotification.objects.count(), 0)
            run_job(job.id)
            self.assertEqual(CompletionNotification.objects.count(), 0)
            run_job(job.id)
        self.assertEqual(CompletionNotification.objects.get().status, "failed")

    def test_provider_failure_and_recovery_deadlines_notify_once(self):
        failed = make_job(self.owner)
        with patch("matching.jobs.extract_evidence", side_effect=ProviderError()):
            run_job(failed.id)
        queued = make_job(self.owner, deadline_at=timezone.now() - timedelta(seconds=1))
        running = make_job(self.owner)
        claim_job(running.id)
        Job.objects.filter(pk=running.pk).update(deadline_at=timezone.now() - timedelta(seconds=1))
        recover_jobs()
        recover_jobs()
        self.assertEqual(set(CompletionNotification.objects.values_list("job_id", "status")), {(failed.id, "failed"), (queued.id, "failed"), (running.id, "failed")})

    def test_claim_rejection_and_expired_final_lease_create_failure_notifications(self):
        expired = make_job(self.owner, deadline_at=timezone.now() - timedelta(seconds=1))
        self.assertIsNone(claim_job(expired.id))
        capped = make_job(self.owner, attempts=3)
        self.assertIsNone(claim_job(capped.id))
        running = make_job(self.owner, attempts=2)
        claim_job(running.id)
        Job.objects.filter(pk=running.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        recover_jobs()
        self.assertEqual(CompletionNotification.objects.count(), 3)
        self.assertFalse(CompletionNotification.objects.exclude(status="failed").exists())

    @override_settings(JOB_RETRY_SECONDS=0)
    def test_stale_lease_cannot_create_a_notice_before_current_worker_completes(self):
        job = make_job(self.owner)
        old = claim_job(job.id)
        Job.objects.filter(pk=job.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        recover_jobs()
        new = claim_job(job.id)
        self.assertFalse(finish_job(old, evidence=extract_evidence(SOURCE, REQUIREMENTS)))
        self.assertFalse(CompletionNotification.objects.exists())
        self.assertTrue(finish_job(new, evidence=extract_evidence(SOURCE, REQUIREMENTS)))
        self.assertEqual(CompletionNotification.objects.count(), 1)

    def test_owner_scoped_list_and_idempotent_read_survive_new_session(self):
        job, notice = self.complete()
        self.complete(self.other)
        response = self.client.get("/api/notifications/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        body = response.json()
        self.assertEqual(body["unread_count"], 1)
        self.assertIsNone(body["next_offset"])
        row = body["notifications"][0]
        self.assertEqual(set(row), {"id", "job_id", "job_title", "status", "created_at", "read_at", "href"})
        self.assertEqual((row["job_id"], row["href"]), (str(job.id), f"/results/{job.id}"))
        self.assertNotIn(SOURCE, response.content.decode())
        url = f"/api/notifications/{notice.id}/read/"
        first = self.client.post(url).json()
        self.assertIsNotNone(first["read_at"])
        self.assertEqual(first, self.client.post(url).json())
        self.client.logout()
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get("/api/notifications/").json()["unread_count"], 0)
        self.assertEqual(self.client.get("/api/notifications/").json()["notifications"][0]["read_at"], first["read_at"])
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url).status_code, 404)

    def test_auth_methods_and_csrf(self):
        job, notice = self.complete()
        url = f"/api/notifications/{notice.id}/read/"
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post("/api/notifications/").status_code, 405)
        guarded = Client(enforce_csrf_checks=True)
        guarded.force_login(self.owner)
        self.assertEqual(guarded.post(url).status_code, 403)
        token = guarded.get("/api/session/").json()["csrfToken"]
        self.assertEqual(guarded.post(url, HTTP_X_CSRFTOKEN=token).status_code, 200)
        self.client.logout()
        self.assertEqual(self.client.get("/api/notifications/").status_code, 401)
        self.assertEqual(self.client.post(url).status_code, 401)

    def test_fixed_bounded_page_unread_count_and_validation(self):
        jobs = [make_job(self.owner, status=Job.Status.SUCCEEDED) for _ in range(101)]
        CompletionNotification.objects.bulk_create([CompletionNotification(job=job, status=Job.Status.SUCCEEDED) for job in jobs])
        first = self.client.get("/api/notifications/").json()
        second = self.client.get("/api/notifications/?offset=100").json()
        self.assertEqual((len(first["notifications"]), first["unread_count"], first["next_offset"]), (100, 101, 100))
        self.assertEqual((len(second["notifications"]), second["unread_count"], second["next_offset"]), (1, 101, None))
        self.assertNotIn(second["notifications"][0]["id"], {row["id"] for row in first["notifications"]})
        for offset in ["-1", "x", "100001", "1.5", "١"]:
            self.assertEqual(self.client.get("/api/notifications/", {"offset": offset}).status_code, 400)

    def test_failure_link_and_nonterminal_jobs_never_notify(self):
        job = make_job(self.owner)
        with transaction.atomic():
            persist_completion(job, "worker")
        self.assertFalse(CompletionNotification.objects.exists())
        with patch("matching.jobs.extract_evidence", side_effect=ProviderError()):
            run_job(job.id)
        row = self.client.get("/api/notifications/").json()["notifications"][0]
        self.assertEqual((row["status"], row["href"]), ("failed", f"/jobs/{job.id}"))

    def test_legacy_terminal_jobs_are_not_backfilled(self):
        make_job(self.owner, status=Job.Status.SUCCEEDED)
        self.assertEqual(self.client.get("/api/notifications/").json()["notifications"], [])

    def test_delete_job_and_expiry_remove_notifications_and_hide_reads(self):
        job, notice = self.complete()
        self.client.delete(f"/api/jobs/{job.id}/")
        self.assertFalse(CompletionNotification.objects.exists())
        job, notice = self.complete()
        Job.objects.filter(pk=job.id).update(created_at=timezone.now() - timedelta(days=91))
        self.assertEqual(self.client.get("/api/notifications/").json()["unread_count"], 0)
        self.assertEqual(self.client.post(f"/api/notifications/{notice.id}/read/").status_code, 404)
        from .documents import reconcile_documents
        reconcile_documents()
        self.assertFalse(CompletionNotification.objects.exists())

    def test_original_tombstone_and_expiry_hide_or_cascade_and_fence_completion(self):
        now = timezone.now()
        document = Document.objects.create(owner=self.owner, object_key=f"synthetic/{uuid.uuid4()}", filename="synthetic.txt", content_type="text/plain", size_bytes=1, sha256="a" * 64, status=Document.Status.READY, upload_deadline=now + timedelta(hours=1), expires_at=now + timedelta(days=90))
        job = make_job(self.owner, document=document)
        claim = claim_job(job.id)
        with transaction.atomic():
            tombstone(document)
        self.assertFalse(finish_job(claim, evidence=extract_evidence(SOURCE, REQUIREMENTS)))
        self.assertFalse(CompletionNotification.objects.exists())
        document.status = Document.Status.READY
        document.save()
        job = make_job(self.owner, document=document)
        claim = claim_job(job.id)
        self.assertTrue(finish_job(claim, evidence=extract_evidence(SOURCE, REQUIREMENTS)))
        notice = CompletionNotification.objects.get()
        Document.objects.filter(pk=document.id).update(expires_at=now - timedelta(seconds=1))
        self.assertEqual(self.client.get("/api/notifications/").json()["notifications"], [])
        self.assertEqual(self.client.post(f"/api/notifications/{notice.id}/read/").status_code, 404)
        document.refresh_from_db()
        with transaction.atomic():
            tombstone(document)
        self.assertFalse(CompletionNotification.objects.exists())

    def test_accepted_receipts_expose_status_location_without_waiting(self):
        key = str(uuid.uuid4())
        form = {"job_title": "Synthetic role", "resume_text": SOURCE, "requirements": '[{"skill":"Python","weight":1}]'}
        for _ in range(2):
            response = self.client.post("/api/jobs/", form, HTTP_IDEMPOTENCY_KEY=key)
            job_id = response.json()["id"]
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response["Location"], f"/api/jobs/{job_id}/")
            self.assertEqual(response["Retry-After"], "2")
            self.assertEqual(response.json()["processing_url"], f"/jobs/{job_id}")
            self.assertIsNone(response.json()["result_url"])
        run_job(job_id)
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}/").json()["result_url"], f"/results/{job_id}")

    def test_notifications_emit_only_safe_correlated_metadata(self):
        with patch("matching.telemetry._get_logger") as logger, self.assertLogs("matching.audit", level="INFO") as captured, self.captureOnCommitCallbacks(execute=True):
            job, notice = self.complete(job_title="PRIVATE-TITLE", resume_text="PRIVATE-SOURCE Python")
            self.client.post(f"/api/notifications/{notice.id}/read/")
        output = "\n".join(captured.output)
        self.assertIn("notification.persisted", output)
        self.assertIn("notification.read", output)
        self.assertIn(str(notice.id), output)
        self.assertNotIn("PRIVATE", output + repr(logger.return_value.emit.call_args_list))
