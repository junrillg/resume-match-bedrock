import hashlib
import io
import json
import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch

from botocore.exceptions import EndpointConnectionError
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, SimpleTestCase, override_settings
from django.utils import timezone

from .documents import (DocumentError, DocumentIntegrityError, DocumentUnavailable, ScanPending,
                        cloud_scan, get_original, reconcile_documents, scan_bytes)
from .jobs import run_job
from .models import Document, Job, Match, OutboxEvent
from .test_storage_support import StorageBoundaryMixin


@override_settings(MATCH_PROVIDER="demo", DOCUMENT_SCAN_MODE="clamav", OTEL_LOGS_ENDPOINT="")
class DocumentFlowTests(StorageBoundaryMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.owner = get_user_model().objects.create_user("document-owner")
        self.other = get_user_model().objects.create_user("other-document-owner")
        self.client.force_login(self.owner)
        self.raw = b"\xef\xbb\xbfSynthetic Python APIs.\r\n"

    def post(self, key=None, **values):
        form = {"job_title": "Synthetic role", "requirements": json.dumps([{"skill":"Python", "weight":1}]), **values}
        if not ("document_id" in values or "resume_text" in values or "resume" in values):
            form["resume"] = SimpleUploadedFile("original.txt", self.raw)
        return self.client.post("/api/jobs/", form, HTTP_IDEMPOTENCY_KEY=str(key or uuid.uuid4()))

    @override_settings(DOCUMENT_RETENTION_DAYS=45)
    def test_session_reports_configured_retention_and_document_uses_policy(self):
        self.assertEqual(self.client.get("/api/session/").json()["document_retention_days"], 45)
        self.post()
        self.assertAlmostEqual((Document.objects.get().expires_at-timezone.now()).total_seconds(), 45*86400, delta=5)

    def test_original_roundtrip_reuse_reprocess_and_separate_comparison_delete(self):
        response = self.post()
        self.assertEqual(response.status_code, 202)
        job = Job.objects.get()
        document = job.document
        self.assertEqual(document.sha256, hashlib.sha256(self.raw).hexdigest())
        self.assertEqual(job.resume_text, "")
        self.assertEqual(self.client.get(f"/api/documents/{document.id}/download/").status_code, 404)
        run_job(job.id)
        document.refresh_from_db()
        self.assertEqual((document.status, document.extracted_text), ("ready", "Synthetic Python APIs."))
        download = self.client.get(f"/api/documents/{document.id}/download/")
        self.assertEqual(b"".join(download.streaming_content), self.raw)
        self.assertIn("no-store", download["Cache-Control"])
        self.assertIn("attachment", download["Content-Disposition"])
        other = self.post(document_id=str(document.id))
        self.assertEqual(other.status_code, 202)
        with patch("matching.documents.read_resume", side_effect=AssertionError("cache must be reused")):
            run_job(other.json()["id"])
        repeated = self.post(document_id=str(document.id), reprocess="true")
        run_job(repeated.json()["id"])
        self.assertEqual(Match.objects.count(), 3)
        self.client.delete(f"/api/jobs/{job.id}/")
        self.assertEqual(Document.objects.get(pk=document.id).status, "ready")
        self.assertIn(document.object_key, self.storage.objects)

    def test_raw_identity_not_normalized_text_and_upload_failure_replay(self):
        key = uuid.uuid4()
        first = self.post(key)
        self.assertEqual(self.post(key).json()["id"], first.json()["id"])
        self.assertEqual(self.post(key, resume=SimpleUploadedFile("original.txt", self.raw.replace(b"\r\n", b"\n"))).status_code, 409)
        key = uuid.uuid4()
        with patch("matching.views.put_original", side_effect=DocumentUnavailable):
            self.assertEqual(self.post(key).status_code, 503)
        pending = Job.objects.get(idempotency_key=key)
        self.assertEqual((pending.status, pending.dispatches.count()), ("uploading", 0))
        Job.objects.filter(pk=pending.pk).update(deadline_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.post(key).json()["id"], str(pending.id))
        pending.refresh_from_db()
        self.assertEqual(pending.status, "queued")
        self.assertGreater(pending.deadline_at, timezone.now()+timedelta(minutes=9))

    def test_owner_csrf_and_expiry_deny_access_before_cleanup(self):
        job_id = self.post().json()["id"]
        run_job(job_id)
        document = Job.objects.get(pk=job_id).document
        self.client.force_login(self.other)
        self.assertEqual(self.client.get("/api/documents/").json(), {"documents": []})
        self.assertEqual(self.client.get(f"/api/documents/{document.id}/download/").status_code, 404)
        self.assertEqual(self.post(document_id=str(document.id)).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/documents/{document.id}/").status_code, 404)
        self.client.force_login(self.owner)
        guarded = Client(enforce_csrf_checks=True)
        guarded.force_login(self.owner)
        self.assertEqual(guarded.delete(f"/api/documents/{document.id}/").status_code, 403)
        Document.objects.filter(pk=document.id).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.client.get(f"/api/documents/{document.id}/download/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}/").status_code, 404)
        self.assertEqual(self.client.get("/api/matches/").json(), {"matches": []})
        reconcile_documents()
        self.assertFalse(Job.objects.filter(pk=job_id).exists())
        self.assertNotIn(document.object_key, self.storage.objects)

    def test_delete_retry_denies_access_and_fences_late_completion(self):
        job_id = self.post().json()["id"]
        document = Job.objects.get(pk=job_id).document
        response = self.client.delete(f"/api/documents/{document.id}/")
        self.assertEqual(response.status_code, 202)
        document.refresh_from_db()
        self.assertEqual((document.filename, document.extracted_text, document.sha256), ("", "", ""))
        self.assertEqual(self.client.get(f"/api/documents/{document.id}/download/").status_code, 404)
        run_job(job_id)
        self.assertFalse(Match.objects.exists())
        with patch.object(self.storage, "delete_object", side_effect=EndpointConnectionError(endpoint_url="http://synthetic.invalid")):
            reconcile_documents()
        document.refresh_from_db()
        self.assertEqual(document.status, "deleting")
        self.assertIn(document.object_key, self.storage.objects)
        reconcile_documents()
        document.refresh_from_db()
        self.assertEqual((document.status, document.extracted_text, document.filename), ("deleted", "", ""))
        self.assertNotIn(document.object_key, self.storage.objects)

    def test_stale_upload_completion_does_not_delete_newer_ready_admission(self):
        from .documents import put_original
        key = uuid.uuid4()
        calls = 0
        def delayed_put(document, data):
            nonlocal calls
            calls += 1
            if calls == 1:
                Document.objects.filter(pk=document.pk).update(upload_lease_until=timezone.now()-timedelta(seconds=1))
                newer = self.post(key)
                self.assertEqual(newer.status_code, 202)
                run_job(newer.json()["id"])
            put_original(document, data)
        with patch("matching.views.put_original", side_effect=delayed_put):
            response = self.post(key)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "succeeded")
        document = Document.objects.get()
        self.assertEqual(document.status, "ready")
        self.assertEqual((Job.objects.count(), Match.objects.count(), OutboxEvent.objects.count()), (1, 1, 1))
        self.assertIn(document.object_key, self.storage.objects)

    def test_upload_completion_racing_delete_restores_cleanup_intent(self):
        from .documents import put_original
        def racing_put(document, data):
            self.client.delete(f"/api/documents/{document.id}/")
            put_original(document, data)
        with patch("matching.views.put_original", side_effect=racing_put):
            self.assertEqual(self.post().status_code, 409)
        document = Document.objects.get()
        self.assertEqual(document.status, "deleting")
        reconcile_documents()
        self.assertNotIn(document.object_key, self.storage.objects)
        self.assertFalse(Job.objects.exists())

    def test_integrity_infection_and_unavailable_scanner_fail_closed(self):
        job_id = self.post().json()["id"]
        document = Job.objects.get(pk=job_id).document
        self.storage.objects[document.object_key] = b"changed"
        with patch("matching.jobs.extract_evidence") as provider:
            run_job(job_id)
            provider.assert_not_called()
        self.assertEqual(Job.objects.get(pk=job_id).error_code, "document_integrity")
        self.assertEqual(Document.objects.get(pk=document.id).status, "rejected")
        other_id = self.post().json()["id"]
        with patch("matching.documents.scan_bytes", side_effect=DocumentError), patch("matching.jobs.extract_evidence") as provider:
            run_job(other_id)
            provider.assert_not_called()
        self.assertEqual(Job.objects.get(pk=other_id).error_code, "document_rejected")
        next_id = self.post().json()["id"]
        with patch("matching.documents.scan_bytes", side_effect=DocumentUnavailable), patch("matching.jobs.extract_evidence") as provider:
            run_job(next_id)
            provider.assert_not_called()
        self.assertEqual(Job.objects.get(pk=next_id).status, "queued")

    def test_cloud_scan_pending_waits_without_spending_provider_attempt_budget(self):
        job_id = self.post().json()["id"]
        with patch("matching.documents.get_original", side_effect=ScanPending):
            run_job(job_id)
        job = Job.objects.get(pk=job_id)
        self.assertEqual((job.status, job.attempts, job.match if hasattr(job, "match") else None), ("queued", 0, None))
        self.assertGreater(job.available_at, timezone.now()+timedelta(seconds=5))

    def test_pending_document_can_be_retried_after_scanner_outage(self):
        job_id = self.post().json()["id"]
        document_id = str(Job.objects.get(pk=job_id).document_id)
        with patch("matching.documents.scan_bytes", side_effect=DocumentUnavailable):
            run_job(job_id)
        response = self.post(document_id=document_id, reprocess="true")
        self.assertEqual(response.status_code, 202)
        run_job(response.json()["id"])
        self.assertEqual(Job.objects.get(pk=response.json()["id"]).status, "succeeded")

    def test_confirmed_deletion_tombstone_has_finite_seven_day_grace(self):
        job_id = self.post().json()["id"]
        document = Job.objects.get(pk=job_id).document
        self.client.delete(f"/api/documents/{document.id}/")
        reconcile_documents()
        self.assertTrue(Document.objects.filter(pk=document.pk).exists())
        Document.objects.filter(pk=document.pk).update(deleted_at=timezone.now()-timedelta(days=8))
        reconcile_documents()
        self.assertFalse(Document.objects.filter(pk=document.pk).exists())

    def test_abandoned_reservation_is_reconciled(self):
        with patch("matching.views.put_original", side_effect=DocumentUnavailable):
            self.post()
        document = Document.objects.get()
        Document.objects.filter(pk=document.pk).update(upload_deadline=timezone.now()-timedelta(seconds=1))
        reconcile_documents()
        self.assertFalse(Job.objects.exists())
        self.assertEqual(Document.objects.get().status, "deleted")


class ScannerProtocolTests(SimpleTestCase):
    def test_clamd_fresh_clean_infected_unknown_and_stale(self):
        version = "ClamAV 1.5.4/12345/" + timezone.now().strftime("%a %b %d %H:%M:%S %Y")
        for response, expected in [(b"stream: OK\0", None), (b"stream: Eicar-Signature FOUND\0", DocumentError), (b"stream: unknown ERROR\0", DocumentUnavailable)]:
            stream = MagicMock()
            stream.__enter__.return_value = stream
            stream.recv.return_value = response
            with patch("matching.documents._clam_command", return_value=version.encode()), patch("matching.documents.socket.create_connection", return_value=stream):
                if expected:
                    with self.assertRaises(expected): scan_bytes(b"synthetic")
                else:
                    scan_bytes(b"synthetic")
                    self.assertEqual(stream.sendall.call_args_list[0].args[0], b"zINSTREAM\0")
                    self.assertEqual(stream.sendall.call_args_list[-1].args[0], b"\0\0\0\0")
        with patch("matching.documents._clam_command", return_value=b"ClamAV 1.5.4/1/Mon Jan 01 00:00:00 2024"):
            with self.assertRaises(DocumentUnavailable): scan_bytes(b"synthetic")

    def test_cloud_gate_never_treats_missing_unknown_or_failed_as_clean(self):
        document = MagicMock(object_key="originals/synthetic")
        storage = MagicMock()
        for status, error in [(None, ScanPending), ("THREATS_FOUND", DocumentError), ("FAILED", DocumentError), ("UNKNOWN", ScanPending)]:
            storage.get_object_tagging.return_value = {"TagSet": [] if status is None else [{"Key":"GuardDutyMalwareScanStatus", "Value":status}]}
            with self.assertRaises(error): cloud_scan(storage, document)
        storage.get_object_tagging.return_value = {"TagSet":[{"Key":"GuardDutyMalwareScanStatus", "Value":"NO_THREATS_FOUND"}]}
        cloud_scan(storage, document)
