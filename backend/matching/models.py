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
        UPLOADING = "uploading"
        QUEUED = "queued"
        RUNNING = "running"
        SUCCEEDED = "succeeded"
        FAILED = "failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    document = models.ForeignKey("Document", null=True, blank=True, on_delete=models.PROTECT, related_name="jobs")
    reprocess = models.BooleanField(default=False)
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


class CompletionNotification(models.Model):
    """Durable inbox receipt, committed with the terminal job outcome."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField(Job, on_delete=models.CASCADE, related_name="completion_notification")
    status = models.CharField(max_length=12, choices=[(Job.Status.SUCCEEDED, "Succeeded"), (Job.Status.FAILED, "Failed")])
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [models.CheckConstraint(condition=models.Q(status__in=["succeeded", "failed"]), name="notification_terminal_status")]


class Document(models.Model):
    class Status(models.TextChoices):
        UPLOADING = "uploading"
        PENDING = "pending"
        READY = "ready"
        REJECTED = "rejected"
        DELETING = "deleting"
        DELETED = "deleted"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    object_key = models.CharField(max_length=160, unique=True)
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=80)
    size_bytes = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.UPLOADING)
    extracted_text = models.TextField(blank=True, default="")
    parser_version = models.CharField(max_length=40, blank=True, default="")
    scan_checked_at = models.DateTimeField(null=True, blank=True)
    upload_lease = models.UUIDField(null=True, blank=True)
    upload_lease_until = models.DateTimeField(null=True, blank=True)
    upload_deadline = models.DateTimeField()
    deleted_at = models.DateTimeField(null=True, blank=True)
    delete_after = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "delete_after"]), models.Index(fields=["owner", "-created_at"])]
