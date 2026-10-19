"""In-app delivery is a durable database write, not a best-effort callback."""
from datetime import timedelta
from functools import partial

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import CompletionNotification, Job
from .telemetry import emit


def persist_completion(job, stage):
    # Call only while holding the job lock inside its outcome transaction.
    if job.status not in {Job.Status.SUCCEEDED, Job.Status.FAILED}:
        return
    notification, created = CompletionNotification.objects.get_or_create(job=job, defaults={"status": job.status})
    if created:
        transaction.on_commit(partial(emit, "notification.persisted", notification_id=notification.id,
                                     job_id=job.id, request_id=job.request_id, stage=stage, status=job.status))


def visible_notifications(owner):
    now = timezone.now()
    return CompletionNotification.objects.filter(job__owner=owner).filter(
        Q(job__document__expires_at__gt=now) |
        Q(job__document__isnull=True, job__created_at__gt=now - timedelta(days=settings.DOCUMENT_RETENTION_DAYS))
    ).exclude(job__document__status__in=["deleting", "deleted"]).select_related("job")


def serialize_notification(notification):
    destination = "results" if notification.status == Job.Status.SUCCEEDED else "jobs"
    return {"id": str(notification.id), "job_id": str(notification.job_id),
            "job_title": notification.job.job_title, "status": notification.status,
            "created_at": notification.created_at.isoformat(),
            "read_at": notification.read_at.isoformat() if notification.read_at else None,
            "href": f"/{destination}/{notification.job_id}"}
