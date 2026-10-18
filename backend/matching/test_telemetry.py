from .test_storage_support import StorageBoundaryMixin
import logging
import threading
import time
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import SimpleTestCase, TestCase, override_settings
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, LogRecordExporter, LogRecordExportResult

from . import telemetry
from .jobs import job_event, run_job
from .models import Job, OutboxEvent


@override_settings(LAB_SERVICE_NAME="api", OTEL_LOGS_ENDPOINT="http://viewer.invalid/api/default/v1/logs", OPENOBSERVE_PASSWORD="synthetic-telemetry-test-password")
class TelemetryTests(SimpleTestCase):
    def tearDown(self):
        telemetry._reset_after_fork()

    def test_only_allowlisted_metadata_reaches_stdout_and_export(self):
        request_id, job_id = uuid.uuid4(), uuid.uuid4()
        with patch("matching.telemetry._get_logger") as logger, self.assertLogs("matching.audit", level="INFO") as captured:
            telemetry.emit("job.accepted", request_id=request_id, job_id=job_id, stage="api", status="queued",
                           attempt=0, duration_ms=15, title="PRIVATE-TITLE", resume="PRIVATE-SOURCE",
                           evidence="PRIVATE-QUOTE", filename="PRIVATE-FILE", credentials="PRIVATE-SECRET")
        payload = logger.return_value.emit.call_args.kwargs
        self.assertEqual(payload["body"], "job.accepted")
        self.assertEqual(payload["attributes"], {"request_id": str(request_id), "job_id": str(job_id), "stage": "api", "status": "queued", "attempt": 0, "duration_ms": 15, "service_name": "api"})
        self.assertNotIn("PRIVATE", repr(payload) + "\n".join(captured.output))

    def test_invalid_known_values_and_unknown_event_bodies_are_dropped(self):
        with patch("matching.telemetry._get_logger") as logger, self.assertLogs("matching.audit", level="INFO") as captured:
            telemetry.emit("job.accepted", request_id="PRIVATE", job_id=["PRIVATE"], stage="PRIVATE", status="PRIVATE",
                           attempt=True, duration_ms="PRIVATE", error_code="PRIVATE")
            telemetry.emit("PRIVATE-ARBITRARY-BODY", request_id=uuid.uuid4())
        logger.assert_called_once()
        self.assertEqual(logger.return_value.emit.call_args.kwargs["attributes"], {"service_name": "api"})
        self.assertNotIn("PRIVATE", "\n".join(captured.output))

    def test_exporter_configuration_is_bounded_lazy_and_recreated_after_pid_change(self):
        telemetry._reset_after_fork()
        with patch("matching.telemetry.OTLPLogExporter") as exporter, patch("matching.telemetry.LoggerProvider") as provider, patch("matching.telemetry.BatchLogRecordProcessor") as batch, patch("matching.telemetry.os.getpid", return_value=123) as pid:
            telemetry._get_logger()
            telemetry._get_logger()
            self.assertEqual(provider.call_count, 1)
            self.assertFalse(provider.call_args.kwargs["shutdown_on_exit"])
            self.assertEqual(exporter.call_args.kwargs["timeout"], 0.5)
            self.assertEqual(exporter.call_args.kwargs["max_request_size"], 262_144)
            self.assertEqual(exporter.call_args.kwargs["headers"]["stream-name"], "resume_match")
            self.assertEqual(batch.call_args.kwargs, {"max_queue_size": 256, "max_export_batch_size": 32, "schedule_delay_millis": 1000})
            pid.return_value = 456
            telemetry._get_logger()
            self.assertEqual(provider.call_count, 2)
            provider.return_value.shutdown.assert_not_called()

    def test_child_reset_replaces_inherited_locked_mutex(self):
        inherited = telemetry._lock
        inherited.acquire()
        try:
            telemetry._reset_after_fork()
            self.assertTrue(telemetry._lock.acquire(blocking=False))
            telemetry._lock.release()
        finally:
            inherited.release()

    def test_export_initialization_failure_never_escapes_or_logs_exception_text(self):
        with patch("matching.telemetry._get_logger", side_effect=RuntimeError("PRIVATE-EXPORT-ERROR")), self.assertLogs("matching.audit", level="INFO") as captured:
            self.assertIsNone(telemetry.emit("job.accepted", request_id=uuid.uuid4(), stage="api", status="queued"))
        self.assertNotIn("PRIVATE", "\n".join(captured.output))

    def test_sdk_response_and_exception_logs_never_reach_root_logging(self):
        with self.assertNoLogs(logging.getLogger(), level="DEBUG"):
            logging.getLogger("opentelemetry.exporter.otlp.proto.http._log_exporter").error("PRIVATE-RESPONSE", exc_info=RuntimeError("PRIVATE-EXCEPTION"))

    def test_slow_exporter_cannot_block_emission_and_queue_stays_bounded(self):
        entered, release = threading.Event(), threading.Event()
        class SlowExporter(LogRecordExporter):
            def export(self, batch):
                entered.set()
                release.wait(timeout=2)
                return LogRecordExportResult.FAILURE

            def shutdown(self):
                pass

            def force_flush(self, timeout_millis=10_000):
                return True
        provider = LoggerProvider(shutdown_on_exit=False)
        processor = BatchLogRecordProcessor(SlowExporter(), max_queue_size=256, max_export_batch_size=32, schedule_delay_millis=1000)
        provider.add_log_record_processor(processor)
        logger = provider.get_logger("bounded-test")
        try:
            with patch("matching.telemetry._get_logger", return_value=logger), patch("matching.telemetry.audit"):
                for _ in range(32):
                    telemetry.emit("job.started", job_id=uuid.uuid4(), stage="worker", status="running", attempt=1)
                self.assertTrue(entered.wait(timeout=1))
                start = time.monotonic()
                for _ in range(512):
                    telemetry.emit("job.started", job_id=uuid.uuid4(), stage="worker", status="running", attempt=1)
                self.assertLess(time.monotonic() - start, 0.5)
                self.assertLessEqual(len(processor._batch_processor._queue), 256)
        finally:
            release.set()
            # Tests may drain their fake exporter; application paths never flush or wait for it.
            provider.shutdown()


@override_settings(MATCH_PROVIDER="demo", LAB_SERVICE_NAME="api", OTEL_LOGS_ENDPOINT="")
class TelemetryTransactionTests(StorageBoundaryMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.owner = get_user_model().objects.create_user("telemetry-fixture")
        self.client.force_login(self.owner)

    def test_real_admission_and_completion_emit_only_metadata_even_when_exporter_fails(self):
        form = {"job_title": "PRIVATE-JOB-TITLE", "resume_text": "PRIVATE-SOURCE Python", "requirements": '[{"skill":"Python","weight":1}]'}
        with patch("matching.telemetry._get_logger", side_effect=RuntimeError("PRIVATE-EXPORT-ERROR")), self.assertLogs("matching.audit", level="INFO") as captured, self.captureOnCommitCallbacks(execute=True):
            response = self.client.post("/api/jobs/", form, HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
            self.assertEqual(response.status_code, 202)
            run_job(response.json()["id"])
        job = Job.objects.get()
        self.assertEqual(job.status, "succeeded")
        self.assertEqual(job.resume_text, "")
        self.assertEqual(OutboxEvent.objects.count(), 1)
        text = "\n".join(captured.output)
        self.assertIn("job.accepted", text)
        self.assertIn("job.started", text)
        self.assertIn("job.succeeded", text)
        self.assertNotIn("PRIVATE", text)

    def test_rolled_back_state_change_never_emits_success(self):
        from .test_jobs import make_job
        job = make_job(self.owner)
        with patch("matching.jobs.emit") as emitted, self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    job_event("job.succeeded", job, "worker")
                    raise RuntimeError("simulate rollback")
            except RuntimeError:
                pass
        emitted.assert_not_called()
