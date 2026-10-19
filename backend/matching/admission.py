"""Finite admission supply; durable reservation follows the logical job, not a delivery."""
from datetime import timedelta

from django.conf import settings
from django.db import connection, connections, transaction
from django.db.models import F
from django.utils import timezone

from .models import AdmissionHealth, Job, RateBucket, WorkerSupply
from .telemetry import emit


class AdmissionDenied(Exception):
    def __init__(self, message, status=503, retry_after=2):
        self.message, self.status, self.retry_after = message, status, retry_after


def release_database():
    # Django TestCase wraps the entire test in a transaction. Real call sites
    # cross this boundary only after their business transaction has completed.
    if not connection.in_atomic_block:
        connections.close_all()


def reserve_admission(owner_id, now):
    """Caller holds owner StreamState lock and the job-creation transaction."""
    active = Job.objects.filter(owner_id=owner_id, status__in=["uploading", "queued", "running"]).order_by()
    if len(list(active.values_list("pk", flat=True)[:settings.OWNER_ACTIVE_JOB_LIMIT])) >= settings.OWNER_ACTIVE_JOB_LIMIT:
        raise AdmissionDenied("Active comparison limit reached. Wait for a comparison to finish.", 429)
    health = AdmissionHealth.objects.select_for_update().filter(pk="jobs").first()
    now = timezone.now()
    if health is None or health.sampled_at is None or health.sampled_at < now - timedelta(seconds=settings.ADMISSION_HEALTH_MAX_AGE_SECONDS):
        raise AdmissionDenied("Processing supply is being checked. Retry shortly.")
    if not health.broker_ready or not health.worker_ready:
        raise AdmissionDenied("Processing supply is unavailable. Retry shortly.")
    if health.oldest_queued_at and (now - health.oldest_queued_at).total_seconds() >= settings.QUEUE_AGE_LIMIT_SECONDS:
        raise AdmissionDenied("Processing queue is at its wait budget. Retry shortly.")
    if health.active >= settings.GLOBAL_ADMISSION_MAX_ACTIVE or health.queued_sample >= settings.GLOBAL_ADMISSION_MAX_ACTIVE:
        raise AdmissionDenied("Processing capacity is full. Retry shortly.")
    second = int(now.timestamp())
    if health.rate_second != second:
        health.rate_second, health.rate_count = second, 0
    if health.rate_count >= settings.GLOBAL_ADMISSION_PER_SECOND:
        raise AdmissionDenied("Comparison admission rate reached. Retry shortly.", 429, 1)
    health.active += 1
    health.rate_count += 1
    health.save(update_fields=["active", "rate_second", "rate_count"])


def release_admission(job):
    """CAS makes terminal retry/delete/cascade release once, within the outcome transaction."""
    if Job.objects.filter(pk=job.pk, admission_reserved=True).update(admission_reserved=False):
        AdmissionHealth.objects.filter(pk="jobs", active__gt=0).update(active=F("active") - 1)
    job.admission_reserved = False


def sample_supply(broker_ready):
    now = timezone.now()
    # Indexed bounded samples; never count the jobs table on admission or maintenance.
    queued = list(Job.objects.filter(status=Job.Status.QUEUED).order_by("created_at").values_list("created_at", flat=True)[:settings.GLOBAL_ADMISSION_MAX_ACTIVE + 1])
    worker_ready = WorkerSupply.objects.filter(last_seen__gte=now - timedelta(seconds=45)).exists()
    AdmissionHealth.objects.update_or_create(pk="jobs", defaults={"sampled_at": now,
        "oldest_queued_at": queued[0] if queued else None, "queued_sample": len(queued),
        "broker_ready": broker_ready, "worker_ready": worker_ready})
    health = AdmissionHealth.objects.only("active").get(pk="jobs")
    emit("admission.snapshot", stage="relay", active_jobs=health.active, queued_jobs=len(queued),
         oldest_queue_age_ms=max(0, int((now - queued[0]).total_seconds() * 1000)) if queued else 0,
         broker_ready=int(broker_ready), worker_ready=int(worker_ready))


def repair_terminal_reservations(limit):
    # Bounded bridge for a pre-upgrade worker finishing a previously admitted job.
    candidates = list(Job.objects.filter(admission_reserved=True, status__in=["succeeded", "failed"]).order_by().values_list("pk", "owner_id")[:limit])
    from .events import lock_stream
    for pk, owner_id in candidates:
        with transaction.atomic():
            lock_stream(owner_id)
            job = Job.objects.select_for_update(skip_locked=True).filter(pk=pk, admission_reserved=True, status__in=["succeeded", "failed"]).first()
            if job is not None:
                release_admission(job)


def maintenance_once(limit):
    from .documents import reconcile_documents
    from .jobs import recover_jobs
    try:
        repair_terminal_reservations(limit)
        recover_jobs(limit)
        reconcile_documents(limit)
        now = timezone.now()
        expired = list(RateBucket.objects.filter(expires_at__lt=now).values_list("pk", flat=True)[:limit])
        RateBucket.objects.filter(pk__in=expired).delete()
        stale = list(WorkerSupply.objects.filter(last_seen__lt=now - timedelta(minutes=5)).values_list("pk", flat=True)[:limit])
        WorkerSupply.objects.filter(pk__in=stale).delete()
    finally:
        release_database()
