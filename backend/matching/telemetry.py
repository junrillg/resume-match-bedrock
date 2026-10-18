"""Allowlisted lifecycle events only; exporting is bounded, asynchronous and optional."""
import base64
import json
import logging
import os
import threading
import time
import uuid

from django.conf import settings
from opentelemetry._logs import SeverityNumber
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource

EVENTS = {"job.accepted", "job.published", "job.started", "job.retry", "job.succeeded",
          "job.failed", "job.recovered", "job.publish_failed", "job.interrupted", "provider.requested", "provider.responded", "provider.completed", "document.ready", "document.rejected", "document.delete_requested", "document.delete_pending", "document.deleted"}
STAGES = {"api", "relay", "worker", "recovery", "provider"}
STATUSES = {"queued", "running", "succeeded", "failed", "confirmed", "unpublished", "interrupted", "ready", "rejected", "deleting", "deleted"}
ERRORS = {"invalid_evidence", "provider_rejected", "processing_failed", "retry_exhausted",
          "deadline_exceeded", "provider_unavailable", "publish_unavailable", "document_rejected", "document_integrity", "document_unavailable"}
audit = logging.getLogger("matching.audit")

# SDK export errors can contain HTTP response bodies or raw exceptions. Never bridge them.
sdk_log = logging.getLogger("opentelemetry")
sdk_log.handlers = [logging.NullHandler()]
sdk_log.propagate = False
_lock = threading.Lock()
_pid = None
_logger = None


def _reset_after_fork():
    global _lock, _pid, _logger
    _lock = threading.Lock()
    _pid = None
    _logger = None


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_after_fork)


def _get_logger():
    global _pid, _logger
    if not settings.OTEL_LOGS_ENDPOINT or not settings.OPENOBSERVE_PASSWORD:
        return None
    pid = os.getpid()
    with _lock:
        if _pid != pid or _logger is None:
            credentials = base64.b64encode(("lab@example.invalid:" + settings.OPENOBSERVE_PASSWORD).encode()).decode()
            exporter = OTLPLogExporter(endpoint=settings.OTEL_LOGS_ENDPOINT, timeout=0.5,
                                       headers={"Authorization": "Basic " + credentials, "stream-name": "resume_match"},
                                       max_request_size=262_144)
            service = settings.LAB_SERVICE_NAME if settings.LAB_SERVICE_NAME in {"api", "relay", "worker", "provider"} else "unknown"
            provider = LoggerProvider(resource=Resource({"service.name": service}), shutdown_on_exit=False)
            provider.add_log_record_processor(BatchLogRecordProcessor(
                exporter, max_queue_size=256, max_export_batch_size=32, schedule_delay_millis=1000,
            ))
            _logger = provider.get_logger("resume_match.lifecycle")
            _pid = pid
        return _logger


def emit(event, **attributes):
    if event not in EVENTS:
        return
    safe = {}
    for key in ("request_id", "job_id", "document_id"):
        try:
            safe[key] = str(uuid.UUID(str(attributes[key])))
        except (KeyError, ValueError, TypeError, AttributeError):
            pass
    for key, allowed in (("stage", STAGES), ("status", STATUSES), ("error_code", ERRORS)):
        value = attributes.get(key)
        if isinstance(value, str) and value in allowed:
            safe[key] = value
    for key, maximum in (("attempt", 3), ("duration_ms", 600_000)):
        value = attributes.get(key)
        if type(value) is int and 0 <= value <= maximum:
            safe[key] = value
    safe["service_name"] = settings.LAB_SERVICE_NAME if settings.LAB_SERVICE_NAME in {"api", "relay", "worker", "provider"} else "unknown"
    failed = event in {"job.failed", "job.interrupted", "job.publish_failed"}
    audit.log(logging.ERROR if failed else logging.INFO, "%s", json.dumps({"event": event, **safe}, sort_keys=True))
    try:
        logger = _get_logger()
        if logger is not None:
            logger.emit(body=event, timestamp=time.time_ns(), attributes=safe,
                        severity_number=SeverityNumber.ERROR if failed else SeverityNumber.INFO)
    except Exception:
        # Telemetry must not change admission, transactions, scoring or worker acknowledgement.
        pass
