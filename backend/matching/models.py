import uuid
from django.conf import settings
from django.db import models


class Match(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    job_title = models.CharField(max_length=120)
    score = models.DecimalField(max_digits=5, decimal_places=2)
    provider = models.CharField(max_length=16)
    requirements = models.JSONField()
    request_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)
    job = models.OneToOneField("Job", null=True, blank=True, on_delete=models.CASCADE, related_name="match")

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["owner", "-created_at"])]


class RateBucket(models.Model):
    key = models.CharField(primary_key=True, max_length=100)
    count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)


class Job(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued"
        RUNNING = "running"
        SUCCEEDED = "succeeded"
        FAILED = "failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    idempotency_key = models.UUIDField()
    payload_hash = models.CharField(max_length=64)
    job_title = models.CharField(max_length=120)
    requirements = models.JSONField()
    resume_text = models.TextField()
    provider = models.CharField(max_length=16)
    request_id = models.UUIDField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.QUEUED)
    attempts = models.PositiveSmallIntegerField(default=0)
    error_code = models.CharField(max_length=32, blank=True, default="")
    lease_id = models.UUIDField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    available_at = models.DateTimeField()
    wake_at = models.DateTimeField()
    deadline_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "idempotency_key"], name="job_owner_idempotency"),
            models.CheckConstraint(condition=models.Q(attempts__lte=3), name="job_attempt_cap"),
        ]
        indexes = [models.Index(fields=["owner", "-created_at"]), models.Index(fields=["status", "wake_at"])]


class OutboxEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="dispatches")
    available_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["sent_at", "available_at"])]
