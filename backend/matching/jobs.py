"""Database state is authoritative; RabbitMQ deliveries are repeatable wakeups."""
import time
import uuid
from datetime import timedelta
from functools import partial

from billiard.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from config.celery import app
from .models import Document, Job, Match, OutboxEvent
from .services import ProviderError, TransientProviderError, calculate_score, extract_evidence
from .telemetry import emit
from .documents import document_text, reconcile_documents, DocumentUnavailable, ScanPending
from .notifications import persist_completion
from .events import lock_stream


def job_event(event, job, stage, **extra):
    attributes = {"request_id": job.request_id, "job_id": job.id, "document_id": job.document_id, "stage": stage,
                  "status": job.status, "attempt": job.attempts, "error_code": job.error_code, **extra}
    transaction.on_commit(partial(emit, event, **attributes))


def fail_job(job, code, stage="worker", duration_ms=0):
    job.status = Job.Status.FAILED
    job.error_code = code
    job.resume_text = ""
    job.lease_id = None
    job.lease_expires_at = None
    job.save()
    persist_completion(job, stage)
    job_event("job.failed", job, stage, duration_ms=duration_ms)


def enqueue_again(job, now):
    job.status = Job.Status.QUEUED
    job.lease_id = None
    job.lease_expires_at = None
    job.available_at = now + timedelta(seconds=settings.JOB_RETRY_SECONDS * (2 ** max(0, job.attempts - 1)))
    job.wake_at = job.available_at + timedelta(seconds=settings.JOB_WAKE_SECONDS)
    job.save()
    OutboxEvent.objects.create(job=job, available_at=job.available_at)


def claim_job(job_id):
    with transaction.atomic():
        lock_stream(Job.objects.filter(pk=job_id).values_list("owner_id", flat=True).first())
        job = Job.objects.select_for_update().filter(pk=job_id).first()
        now = timezone.now()
        if job is None or job.status != Job.Status.QUEUED or job.available_at > now:
            return None
        if job.deadline_at <= now:
            fail_job(job, "deadline_exceeded")
            return None
        if job.attempts >= settings.JOB_MAX_ATTEMPTS:
            fail_job(job, "retry_exhausted")
            return None
        job.status = Job.Status.RUNNING
        job.attempts += 1
        job.lease_id = uuid.uuid4()
        job.lease_expires_at = now + timedelta(seconds=settings.JOB_LEASE_SECONDS)
        job.save()
        return job


def finish_job(claim, evidence=None, error_code=None, transient=False, duration_ms=0):
    with transaction.atomic():
        lock_stream(claim.owner_id)
        document = Document.objects.select_for_update().filter(pk=claim.document_id).first() if claim.document_id else None
        if claim.document_id and (document is None or document.status in {Document.Status.DELETING, Document.Status.DELETED} or document.expires_at <= timezone.now()):
            return False
        job = Job.objects.select_for_update().filter(pk=claim.pk).first()
        now = timezone.now()
        if job is None or job.status != Job.Status.RUNNING or job.lease_id != claim.lease_id or job.lease_expires_at <= now:
            return False
        if document is not None and not error_code and document.status != Document.Status.READY:
            fail_job(job, "document_rejected", duration_ms=duration_ms)
        elif job.deadline_at <= now:
            fail_job(job, "deadline_exceeded", duration_ms=duration_ms)
        elif transient and job.attempts < settings.JOB_MAX_ATTEMPTS:
            enqueue_again(job, now)
        elif error_code:
            fail_job(job, "retry_exhausted" if transient else error_code, duration_ms=duration_ms)
        else:
            Match.objects.create(job=job, owner_id=job.owner_id, job_title=job.job_title, score=calculate_score(evidence), provider=job.provider, requirements=evidence, request_id=job.request_id)
            job.status = Job.Status.SUCCEEDED
            job.resume_text = ""
            job.lease_id = None
            job.lease_expires_at = None
            job.save()
            persist_completion(job, "worker")
        if job.status != Job.Status.FAILED:
            job_event("job.retry" if job.status == Job.Status.QUEUED else "job.succeeded", job, "worker", duration_ms=duration_ms, error_code=error_code)
        return True


def run_job(job_id):
    try:
        job_id = uuid.UUID(str(job_id))
    except ValueError:
        return
    claim = claim_job(job_id)
    if claim is None:
        return
    emit("job.started", request_id=claim.request_id, job_id=claim.id, document_id=claim.document_id, stage="worker", status="running", attempt=claim.attempts)
    started = time.monotonic()
    try:
        text = document_text(claim) if claim.document_id else claim.resume_text
        if claim.provider != "demo":
            emit("provider.requested", request_id=claim.request_id, job_id=claim.id, stage="worker", status="running", attempt=claim.attempts)
        evidence = extract_evidence(text, claim.requirements, provider=claim.provider,
                                    correlation={"request_id": claim.request_id, "job_id": claim.id})
        if claim.provider != "demo":
            emit("provider.responded", request_id=claim.request_id, job_id=claim.id, stage="worker", status="running", attempt=claim.attempts, duration_ms=int((time.monotonic() - started) * 1000))
    except ScanPending:
        with transaction.atomic():
            lock_stream(claim.owner_id)
            job = Job.objects.select_for_update().filter(pk=claim.pk, status=Job.Status.RUNNING, lease_id=claim.lease_id).first()
            if job is not None:
                job.attempts = max(0, job.attempts - 1)
                enqueue_again(job, timezone.now() + timedelta(seconds=8))
                job_event("job.retry", job, "worker", error_code="document_unavailable")
    except DocumentUnavailable:
        finish_job(claim, error_code="document_unavailable", transient=True, duration_ms=int((time.monotonic() - started) * 1000))
    except (TransientProviderError, SoftTimeLimitExceeded):
        finish_job(claim, error_code="provider_unavailable", transient=True, duration_ms=int((time.monotonic() - started) * 1000))
    except ProviderError as exc:
        finish_job(claim, error_code=exc.code, duration_ms=int((time.monotonic() - started) * 1000))
    except Exception:
        # Persist only a stable code: unexpected exception text may contain source or credentials.
        finish_job(claim, error_code="processing_failed", duration_ms=int((time.monotonic() - started) * 1000))
    else:
        finish_job(claim, evidence=evidence, duration_ms=int((time.monotonic() - started) * 1000))


def recover_jobs(limit=100):
    now = timezone.now()
    recovered = 0
    candidates = Job.objects.filter(status__in=[Job.Status.QUEUED, Job.Status.RUNNING]).filter(
        Q(deadline_at__lte=now) | Q(status=Job.Status.RUNNING, lease_expires_at__lte=now) | Q(status=Job.Status.QUEUED, wake_at__lte=now)
    ).order_by("wake_at").values_list("id", flat=True)[:limit]
    for job_id in list(candidates):
        with transaction.atomic():
            lock_stream(Job.objects.filter(pk=job_id).values_list("owner_id", flat=True).first())
            job = Job.objects.select_for_update(skip_locked=True).filter(pk=job_id).first()
            if job is None or job.status not in {Job.Status.QUEUED, Job.Status.RUNNING}:
                continue
            if job.deadline_at <= now:
                fail_job(job, "deadline_exceeded", stage="recovery")
            elif job.status == Job.Status.RUNNING and job.lease_expires_at <= now:
                if job.attempts >= settings.JOB_MAX_ATTEMPTS:
                    fail_job(job, "retry_exhausted", stage="recovery")
                else:
                    enqueue_again(job, now)
            elif job.status == Job.Status.QUEUED and job.wake_at <= now:
                if not job.dispatches.filter(sent_at__isnull=True).exists():
                    OutboxEvent.objects.create(job=job, available_at=max(now, job.available_at))
                job.wake_at = max(now, job.available_at) + timedelta(seconds=settings.JOB_WAKE_SECONDS)
                job.save(update_fields=["wake_at"])
            else:
                continue
            recovered += 1
            job_event("job.recovered", job, "recovery")
    return recovered


def publish_job(job_id):
    queue = app.amqp.queues["resume.match.quorum"]
    with app.connection_for_write() as connection:
        connection.ensure_connection(max_retries=0)
        with app.amqp.Producer(connection) as producer:
            app.send_task("matching.process_job", args=[str(job_id)], producer=producer,
                          queue=queue, routing_key="resume.match.quorum", exchange=queue.exchange,
                          declare=[queue], serializer="json", delivery_mode=2,
                          retry=False, mandatory=True, confirm_timeout=3,
                          ignore_result=True)


def relay_once(limit=100):
    reconcile_documents(limit)
    recover_jobs(limit)
    sent = 0
    for _ in range(limit):
        with transaction.atomic():
            event = OutboxEvent.objects.select_for_update(skip_locked=True).filter(sent_at__isnull=True, available_at__lte=timezone.now()).order_by("created_at").first()
            if event is None:
                break
            metadata = Job.objects.filter(pk=event.job_id).values("request_id", "attempts").first() or {}
            try:
                publish_job(event.job_id)
            except Exception:
                transaction.on_commit(partial(emit, "job.publish_failed", job_id=event.job_id,
                                             request_id=metadata.get("request_id"), stage="relay", status="unpublished",
                                             attempt=metadata.get("attempts"), error_code="publish_unavailable"))
                break
            event.sent_at = timezone.now()
            event.save(update_fields=["sent_at"])
            sent += 1
            transaction.on_commit(partial(emit, "job.published", job_id=event.job_id,
                                         request_id=metadata.get("request_id"), stage="relay", status="confirmed", attempt=metadata.get("attempts")))
    return sent
