"""Database state is authoritative; RabbitMQ deliveries are repeatable wakeups."""
import logging
import uuid
from datetime import timedelta

from billiard.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from config.celery import app
from .models import Job, Match, OutboxEvent
from .services import ProviderError, TransientProviderError, calculate_score, extract_evidence

audit = logging.getLogger("matching.audit")


def fail_job(job, code):
    job.status = Job.Status.FAILED
    job.error_code = code
    job.resume_text = ""
    job.lease_id = None
    job.lease_expires_at = None
    job.save()


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


def finish_job(claim, evidence=None, error_code=None, transient=False):
    with transaction.atomic():
        job = Job.objects.select_for_update().filter(pk=claim.pk).first()
        now = timezone.now()
        if job is None or job.status != Job.Status.RUNNING or job.lease_id != claim.lease_id or job.lease_expires_at <= now:
            return False
        if job.deadline_at <= now:
            fail_job(job, "deadline_exceeded")
        elif transient and job.attempts < settings.JOB_MAX_ATTEMPTS:
            enqueue_again(job, now)
        elif error_code:
            fail_job(job, "retry_exhausted" if transient else error_code)
        else:
            Match.objects.create(job=job, owner_id=job.owner_id, job_title=job.job_title, score=calculate_score(evidence), provider=job.provider, requirements=evidence, request_id=job.request_id)
            job.status = Job.Status.SUCCEEDED
            job.resume_text = ""
            job.lease_id = None
            job.lease_expires_at = None
            job.save()
        audit.info("request_id=%s job_id=%s stage=worker status=%s attempt=%s", job.request_id, job.id, job.status, job.attempts)
        return True


def run_job(job_id):
    try:
        job_id = uuid.UUID(str(job_id))
    except ValueError:
        return
    claim = claim_job(job_id)
    if claim is None:
        return
    audit.info("request_id=%s job_id=%s stage=worker status=running attempt=%s", claim.request_id, claim.id, claim.attempts)
    try:
        evidence = extract_evidence(claim.resume_text, claim.requirements, provider=claim.provider)
    except (TransientProviderError, SoftTimeLimitExceeded):
        finish_job(claim, error_code="provider_unavailable", transient=True)
    except ProviderError as exc:
        finish_job(claim, error_code=exc.code)
    except Exception:
        # Persist only a stable code: unexpected exception text may contain source or credentials.
        finish_job(claim, error_code="processing_failed")
    else:
        finish_job(claim, evidence=evidence)


def recover_jobs(limit=100):
    now = timezone.now()
    recovered = 0
    candidates = Job.objects.filter(status__in=[Job.Status.QUEUED, Job.Status.RUNNING]).filter(
        Q(deadline_at__lte=now) | Q(status=Job.Status.RUNNING, lease_expires_at__lte=now) | Q(status=Job.Status.QUEUED, wake_at__lte=now)
    ).order_by("wake_at").values_list("id", flat=True)[:limit]
    for job_id in list(candidates):
        with transaction.atomic():
            job = Job.objects.select_for_update(skip_locked=True).filter(pk=job_id).first()
            if job is None or job.status not in {Job.Status.QUEUED, Job.Status.RUNNING}:
                continue
            if job.deadline_at <= now:
                fail_job(job, "deadline_exceeded")
            elif job.status == Job.Status.RUNNING and job.lease_expires_at <= now:
                if job.attempts >= settings.JOB_MAX_ATTEMPTS:
                    fail_job(job, "retry_exhausted")
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
            audit.info("request_id=%s job_id=%s stage=recovery status=%s attempt=%s", job.request_id, job.id, job.status, job.attempts)
    return recovered


def publish_job(job_id):
    queue = app.amqp.queues["resume.match"]
    with app.connection_for_write() as connection:
        connection.ensure_connection(max_retries=0)
        with app.amqp.Producer(connection) as producer:
            app.send_task("matching.process_job", args=[str(job_id)], producer=producer,
                          queue=queue, routing_key="resume.match", exchange=queue.exchange,
                          declare=[queue], serializer="json", delivery_mode=2,
                          retry=False, mandatory=True, confirm_timeout=3,
                          ignore_result=True)


def relay_once(limit=100):
    recover_jobs(limit)
    sent = 0
    for _ in range(limit):
        with transaction.atomic():
            event = OutboxEvent.objects.select_for_update(skip_locked=True).filter(sent_at__isnull=True, available_at__lte=timezone.now()).order_by("created_at").first()
            if event is None:
                break
            try:
                publish_job(event.job_id)
            except Exception:
                audit.warning("job_id=%s stage=relay status=unpublished", event.job_id)
                break
            event.sent_at = timezone.now()
            event.save(update_fields=["sent_at"])
            sent += 1
            audit.info("job_id=%s stage=relay status=confirmed", event.job_id)
    return sent
