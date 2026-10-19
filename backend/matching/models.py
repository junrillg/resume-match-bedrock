import uuid
from django.conf import settings
from django.db import models, transaction
from django.db.models.signals import post_delete, pre_delete
from django.dispatch import receiver


class TrackedMutation(models.Model):
    """Persist the visible mutation and its delivery intent in the same transaction.

    Bulk updates are reserved for invisible leases/housekeeping. Visible state must
    use save/delete so clients cannot miss committed changes.
    """
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        with transaction.atomic():
            from .events import lock_stream
            lock_stream(self.job.owner_id if isinstance(self, CompletionNotification) else self.owner_id)
            if isinstance(self, CompletionNotification):
                self.owner_id = self.job.owner_id
            super().save(*args, **kwargs)
            from .events import record_change
            visible = ({"status", "attempts", "error_code", "job_title", "document", "document_id"} if isinstance(self, Job)
                       else {"status", "filename", "content_type", "size_bytes", "expires_at"} if isinstance(self, Document)
                       else {"status", "read_at"})
            if kwargs.get("update_fields") is not None and not visible.intersection(kwargs["update_fields"]):
                return
            if isinstance(self, CompletionNotification):
                record_change(self.job.owner_id, "inbox.changed", job_id=self.job_id)
            elif isinstance(self, Job):
                record_change(self.owner_id, "job.changed", job_id=self.id, document_id=self.document_id)
            elif isinstance(self, Document):
                record_change(self.owner_id, "document.changed", document_id=self.id)


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


class Job(TrackedMutation):
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
    admission_reserved = models.BooleanField(default=False)
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
        indexes = [models.Index(fields=["owner", "-created_at", "-id"]), models.Index(fields=["status", "wake_at"]),
                   models.Index(fields=["status", "created_at"], name="job_queue_age"),
                   models.Index(fields=["owner", "status"], name="job_owner_active"),
                   models.Index(fields=["status", "created_at"], condition=models.Q(admission_reserved=True), name="job_reserved_repair")]


class OutboxEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="dispatches")
    available_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["sent_at", "available_at"])]


class CompletionNotification(TrackedMutation):
    """Durable inbox receipt, committed with the terminal job outcome."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    job = models.OneToOneField(Job, on_delete=models.CASCADE, related_name="completion_notification")
    status = models.CharField(max_length=12, choices=[(Job.Status.SUCCEEDED, "Succeeded"), (Job.Status.FAILED, "Failed")])
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["owner", "-created_at", "-id"], name="notice_owner_page"),
                   models.Index(fields=["owner", "read_at"], name="notice_owner_unread")]
        constraints = [models.CheckConstraint(condition=models.Q(status__in=["succeeded", "failed"]), name="notification_terminal_status")]


class Document(TrackedMutation):
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


class StreamState(models.Model):
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, primary_key=True, on_delete=models.CASCADE)
    revision = models.PositiveBigIntegerField(default=0)
    floor_revision = models.PositiveBigIntegerField(default=0)


class StreamEvent(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    revision = models.PositiveBigIntegerField()
    kind = models.CharField(max_length=24)
    job_id = models.UUIDField(null=True)
    document_id = models.UUIDField(null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    available_at = models.DateTimeField()
    published_at = models.DateTimeField(null=True)
    attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "revision"], name="stream_owner_revision")]
        indexes = [models.Index(fields=["available_at", "id"], condition=models.Q(published_at__isnull=True), name="stream_pending_delivery"),
                   models.Index(fields=["created_at", "id"], condition=models.Q(published_at__isnull=True), name="stream_pending_age")]


@receiver(post_delete, sender=Job)
@receiver(post_delete, sender=Document)
@receiver(post_delete, sender=Match)
def deleted_resource(sender, instance, **kwargs):
    from django.contrib.auth import get_user_model
    from .events import record_change
    # User deletion cascades must not recreate a stream for the removed account.
    origin = kwargs.get("origin")
    if isinstance(origin, get_user_model()) or getattr(origin, "model", None) is get_user_model():
        return
    if get_user_model().objects.filter(pk=instance.owner_id).exists():
        record_change(instance.owner_id, "workspace.changed")


# Password/account revocation wakes all owner streams. Each stream checks its own
# session hash; no session key/token is published. Direct SQL administration is
# bounded by the gateway's maximum connection lifetime.
from django.contrib.auth import get_user_model
from django.db.models.signals import pre_save, post_save


@receiver(pre_save, sender=get_user_model())
def account_before_save(sender, instance, **kwargs):
    previous = sender.objects.filter(pk=instance.pk).values("password", "is_active").first() if instance.pk else None
    instance._stream_auth_changed = previous is not None and (
        previous["password"] != instance.password or previous["is_active"] != instance.is_active)


@receiver(post_save, sender=get_user_model())
def account_after_save(sender, instance, **kwargs):
    if getattr(instance, "_stream_auth_changed", False):
        from .events import record_change
        record_change(instance.pk, "workspace.changed")


class AdmissionHealth(models.Model):
    """One short admission mutex; no work or network I/O is done under this lock."""
    key = models.CharField(primary_key=True, max_length=16, default="jobs")
    active = models.PositiveIntegerField(default=0)
    rate_second = models.BigIntegerField(default=0)
    rate_count = models.PositiveIntegerField(default=0)
    sampled_at = models.DateTimeField(null=True)
    oldest_queued_at = models.DateTimeField(null=True)
    queued_sample = models.PositiveIntegerField(default=0)
    broker_ready = models.BooleanField(default=False)
    worker_ready = models.BooleanField(default=False)


class WorkerSupply(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    last_seen = models.DateTimeField(db_index=True)


@receiver(pre_delete, sender=Job)
def release_deleted_admission(sender, instance, **kwargs):
    from .admission import release_admission
    release_admission(instance)
