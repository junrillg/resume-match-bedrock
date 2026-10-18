import hashlib
import json
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib import auth
from django.contrib.auth import get_user_model
from django.core.exceptions import RequestDataTooBig, TooManyFieldsSent, TooManyFilesSent
from django.db.models import F
from django.db import connection, transaction, DatabaseError
from django.http import JsonResponse, FileResponse
from django.middleware.csrf import get_token
from django.utils import timezone

from .models import Document, Job, Match, OutboxEvent, RateBucket
from .services import InvalidInput, read_requirements, read_resume
from .telemetry import emit
from .documents import read_source, put_original, get_original, tombstone, DocumentError, DocumentUnavailable
import io
from django.db.models import Q


def error(request, message, status):
    return JsonResponse({"error": message, "request_id": str(request.request_id)}, status=status)


def csrf_failure(request, reason=""):
    return error(request, "CSRF verification failed. Refresh and try again.", 403)


def not_found(request, exception=None):
    return error(request, "Not found.", 404)


def server_error(request):
    return error(request, "Unexpected server error.", 500)


def session_payload(request):
    payload = {"authenticated": request.user.is_authenticated, "csrfToken": get_token(request), "provider": settings.MATCH_PROVIDER, "log_viewer_url": settings.LOG_VIEWER_URL, "document_retention_days": settings.DOCUMENT_RETENTION_DAYS}
    if request.user.is_authenticated:
        payload["username"] = request.user.get_username()
    return payload


def health(request):
    if request.method != "GET":
        return JsonResponse({"status": "unavailable"}, status=405)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ready"})


def session(request):
    if request.method != "GET":
        return error(request, "Method not allowed.", 405)
    return JsonResponse(session_payload(request))


def consume_bucket(key, limit, expires_at):
    RateBucket.objects.filter(expires_at__lt=timezone.now()).delete()
    RateBucket.objects.get_or_create(key=key, defaults={"expires_at": expires_at})
    return bool(RateBucket.objects.filter(key=key, count__lt=limit).update(count=F("count") + 1))


def login(request):
    if request.method != "POST":
        return error(request, "Method not allowed.", 405)
    now = timezone.now()
    window = int(now.timestamp()) // 300
    # REMOTE_ADDR comes from the server; never trust caller-supplied forwarded headers.
    identity = hashlib.sha256(request.META.get("REMOTE_ADDR", "unknown").encode()).hexdigest()
    if not consume_bucket(f"login:{identity}:{window}", 10, now + timedelta(minutes=5)):
        return error(request, "Too many login attempts. Try again in five minutes.", 429)
    try:
        body = json.loads(request.body)
        if not isinstance(body, dict) or set(body) != {"username", "password"}:
            raise ValueError()
        username, password = body["username"], body["password"]
        if not isinstance(username, str) or not isinstance(password, str) or not 1 <= len(username) <= 150 or not 1 <= len(password) <= 1024:
            raise ValueError()
    except (ValueError, TypeError, RequestDataTooBig):
        return error(request, "Provide username and password as JSON.", 400)
    user = auth.authenticate(request, username=username, password=password)
    if user is None:
        return error(request, "Invalid username or password.", 401)
    auth.login(request, user)
    return JsonResponse(session_payload(request))


def logout(request):
    if request.method != "POST":
        return error(request, "Method not allowed.", 405)
    auth.logout(request)
    return JsonResponse(session_payload(request))


def serialize(record):
    return {"id": str(record.id), "job_title": record.job_title, "score": float(record.score), "provider": record.provider, "created_at": record.created_at.isoformat(), "requirements": record.requirements, "request_id": str(record.request_id)}


def read_match_form(request):
    if set(request.POST) - {"resume_text", "requirements", "job_title", "document_id", "reprocess"} or set(request.FILES) - {"resume"}:
        raise InvalidInput("Unexpected form fields.")
    if any(len(request.POST.getlist(key)) != 1 for key in request.POST) or len(request.FILES.getlist("resume")) > 1:
        raise InvalidInput("Repeated form fields are unsupported.")
    title = request.POST.get("job_title", "").strip()
    if not 1 <= len(title) <= 120 or any(ord(c) < 32 for c in title):
        raise InvalidInput("Job title must contain 1–120 printable characters.")
    requirements = read_requirements(request.POST.get("requirements"))
    reprocess = request.POST.get("reprocess", "false")
    if reprocess not in {"true", "false"}:
        raise InvalidInput("reprocess must be true or false.")
    document_id = request.POST.get("document_id")
    if document_id:
        if request.POST.get("resume_text", "").strip() or request.FILES.get("resume"):
            raise InvalidInput("Use a saved document OR a new source.")
        try:
            document_id = uuid.UUID(document_id)
        except (ValueError, TypeError):
            raise InvalidInput("Provide a document UUID.") from None
        return title, requirements, document_id, reprocess == "true", None
    if reprocess == "true":
        raise InvalidInput("Reprocessing requires a saved document.")
    source = read_source(request.POST.get("resume_text", ""), request.FILES.get("resume"))
    return title, requirements, None, False, source


def matches(request):
    if not request.user.is_authenticated:
        return error(request, "Sign in to continue.", 401)
    if request.method == "GET":
        return JsonResponse({"matches": [serialize(record) for record in Match.objects.filter(owner=request.user, created_at__gt=timezone.now() - timedelta(days=settings.DOCUMENT_RETENTION_DAYS)).filter(Q(job__document__isnull=True) | Q(job__document__expires_at__gt=timezone.now())).exclude(job__document__status__in=["deleting", "deleted"])[:100]]})
    return error(request, "Method not allowed. Submit new comparisons through /api/jobs/.", 405)


def match_detail(request, match_id):
    if not request.user.is_authenticated:
        return error(request, "Sign in to continue.", 401)
    if request.method != "DELETE":
        return error(request, "Method not allowed.", 405)
    record = Match.objects.filter(owner=request.user, pk=match_id).first()
    if record is None:
        return error(request, "Not found.", 404)
    if record.job_id:
        with transaction.atomic():
            job = Job.objects.select_for_update().filter(owner=request.user, pk=record.job_id).first()
            if job is None:
                return error(request, "Not found.", 404)
            job.delete()
    else:
        record.delete()
    return JsonResponse({"deleted": str(match_id), "request_id": str(request.request_id)})


def serialize_document(document):
    return {"id": str(document.id), "filename": document.filename, "content_type": document.content_type,
            "size_bytes": document.size_bytes, "status": document.status,
            "created_at": document.created_at.isoformat(), "expires_at": document.expires_at.isoformat()}


def serialize_job(job):
    try:
        match = serialize(job.match)
    except Match.DoesNotExist:
        match = None
    document = job.document if job.document_id else None
    return {"id": str(job.id), "job_title": job.job_title, "status": job.status,
            "attempts": job.attempts, "created_at": job.created_at.isoformat(),
            "request_id": str(job.request_id), "error_code": job.error_code or None, "match": match,
            "document": serialize_document(document) if document and document.status != Document.Status.DELETED else None}


def jobs(request):
    try:
        return admit_jobs(request)
    except DatabaseError:
        return error(request, "Document admission is unavailable. Retry unchanged inputs.", 503)


def admit_jobs(request):
    if not request.user.is_authenticated:
        return error(request, "Sign in to continue.", 401)
    if request.method == "GET":
        records = Job.objects.filter(owner=request.user).filter(Q(document__isnull=True) | Q(document__expires_at__gt=timezone.now())).exclude(document__status__in=["deleting", "deleted"]).select_related("match", "document")[:100]
        return JsonResponse({"jobs": [serialize_job(job) for job in records]})
    if request.method != "POST":
        return error(request, "Method not allowed.", 405)
    try:
        key = uuid.UUID(request.headers.get("Idempotency-Key", ""))
    except (ValueError, AttributeError):
        return error(request, "Provide a UUID Idempotency-Key header.", 400)
    try:
        title, requirements, document_id, reprocess, source = read_match_form(request)
    except (InvalidInput, RequestDataTooBig, TooManyFieldsSent, TooManyFilesSent) as exc:
        return error(request, str(exc) if isinstance(exc, InvalidInput) else "Request body exceeds upload limits.", 400)
    now = timezone.now()
    identity = {"document_id": str(document_id), "reprocess": reprocess} if document_id else {
        "sha256": hashlib.sha256(source[0]).hexdigest(), "content_type": source[2]}
    fingerprint = hashlib.sha256(json.dumps({"job_title": title, "requirements": requirements, "source": identity}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    lease = None
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=request.user.pk)
        document = None
        if document_id:
            document = Document.objects.select_for_update().filter(pk=document_id, owner=request.user, status__in=[Document.Status.PENDING, Document.Status.READY], expires_at__gt=now).first()
            if document is None:
                return error(request, "Saved document is not available.", 404)
        existing = Job.objects.filter(owner=request.user, idempotency_key=key).select_related("match", "document").first()
        if existing:
            if existing.payload_hash != fingerprint:
                return error(request, "Idempotency key already belongs to a different request.", 409)
            job = existing
            document = job.document
            if job.status != Job.Status.UPLOADING:
                return JsonResponse(serialize_job(job), status=202)
            document = Document.objects.select_for_update().get(pk=document.pk)
            job = Job.objects.select_for_update(of=("self",)).select_related("match", "document").get(pk=job.pk)
            if job.status != Job.Status.UPLOADING:
                return JsonResponse(serialize_job(job), status=202)
            if document.status != Document.Status.UPLOADING or document.upload_deadline <= now:
                return error(request, "Upload reservation is no longer available.", 409)
            if document.upload_lease_until and document.upload_lease_until > now:
                return JsonResponse(serialize_job(job), status=202)
        else:
            if not consume_bucket(f"match:{request.user.pk}:{now.date()}", settings.MATCH_DAILY_LIMIT, now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)):
                return error(request, "Daily matching limit reached. Try again tomorrow (UTC).", 429)
            if source:
                document_id = uuid.uuid4()
                document = Document.objects.create(id=document_id, owner=request.user, object_key=f"originals/{document_id}",
                    filename=source[1], content_type=source[2], size_bytes=len(source[0]), sha256=identity["sha256"],
                    expires_at=now + timedelta(days=settings.DOCUMENT_RETENTION_DAYS),
                    upload_deadline=now + timedelta(seconds=settings.DOCUMENT_UPLOAD_TTL_SECONDS))
            job = Job.objects.create(owner=request.user, document=document, reprocess=reprocess,
                idempotency_key=key, payload_hash=fingerprint, job_title=title, requirements=requirements, resume_text="",
                provider=settings.MATCH_PROVIDER, request_id=request.request_id,
                status=Job.Status.UPLOADING if source else Job.Status.QUEUED,
                available_at=now, wake_at=now + timedelta(seconds=settings.JOB_WAKE_SECONDS),
                deadline_at=now + timedelta(seconds=settings.JOB_DEADLINE_SECONDS))
            if not source:
                OutboxEvent.objects.create(job=job, available_at=now)
        if source:
            lease = uuid.uuid4()
            document.upload_lease = lease
            document.upload_lease_until = now + timedelta(seconds=settings.DOCUMENT_UPLOAD_LEASE_SECONDS)
            document.save(update_fields=["upload_lease", "upload_lease_until"])
    if source:
        try:
            put_original(document, source[0])
        except DocumentUnavailable:
            Document.objects.filter(pk=document.pk, upload_lease=lease).update(upload_lease_until=timezone.now())
            return error(request, "Document storage is unavailable. Retry unchanged inputs.", 503)
        with transaction.atomic():
            current = Document.objects.select_for_update().get(pk=document.pk)
            job = Job.objects.select_for_update().filter(pk=job.pk).first()
            if current.status in {Document.Status.DELETING, Document.Status.DELETED, Document.Status.REJECTED} or (job is None and current.status == Document.Status.UPLOADING):
                # A late successful PUT restores deletion intent, never another upload's state.
                if current.status != Document.Status.REJECTED:
                    current.status = Document.Status.DELETING
                current.delete_after = timezone.now()
                current.upload_lease_until = timezone.now()
                current.save()
                return error(request, "Document was deleted or rejected during upload.", 409)
            if job is None:
                return error(request, "Comparison was deleted during upload.", 409)
            if current.status != Document.Status.UPLOADING or current.upload_lease != lease:
                job.document = current
                return JsonResponse(serialize_job(job), status=202)
            current.status = Document.Status.PENDING
            current.upload_lease = None
            current.upload_lease_until = None
            current.save()
            now = timezone.now()
            job.status = Job.Status.QUEUED
            job.available_at = now
            job.wake_at = now + timedelta(seconds=settings.JOB_WAKE_SECONDS)
            job.deadline_at = now + timedelta(seconds=settings.JOB_DEADLINE_SECONDS)
            job.save()
            OutboxEvent.objects.create(job=job, available_at=now)
            job.document = current
    emit("job.accepted", request_id=job.request_id, job_id=job.id, document_id=job.document_id, stage="api", status="queued", attempt=0)
    return JsonResponse(serialize_job(job), status=202)


def documents(request):
    if not request.user.is_authenticated:
        return error(request, "Sign in to continue.", 401)
    if request.method != "GET":
        return error(request, "Method not allowed.", 405)
    records = Document.objects.filter(owner=request.user, expires_at__gt=timezone.now()).exclude(status=Document.Status.DELETED)[:100]
    return JsonResponse({"documents": [serialize_document(document) for document in records]})


def document_detail(request, document_id):
    if not request.user.is_authenticated:
        return error(request, "Sign in to continue.", 401)
    if request.method != "DELETE":
        return error(request, "Method not allowed.", 405)
    with transaction.atomic():
        document = Document.objects.select_for_update().filter(owner=request.user, pk=document_id).exclude(status=Document.Status.DELETED).first()
        if document is None:
            return error(request, "Not found.", 404)
        tombstone(document)
    emit("document.delete_requested", document_id=document.id, request_id=request.request_id, stage="api", status="deleting")
    return JsonResponse({"deleted": str(document.id), "status": "deleting", "request_id": str(request.request_id)}, status=202)


def document_download(request, document_id):
    if not request.user.is_authenticated:
        return error(request, "Sign in to continue.", 401)
    if request.method != "GET":
        return error(request, "Method not allowed.", 405)
    document = Document.objects.filter(owner=request.user, pk=document_id, status=Document.Status.READY, expires_at__gt=timezone.now()).first()
    if document is None:
        return error(request, "Document is not available for download.", 404)
    try:
        data = get_original(document)
    except DocumentUnavailable:
        return error(request, "Document safety verification is unavailable. Try again later.", 503)
    except DocumentError:
        return error(request, "Document safety verification failed.", 409)
    # Check again after object/scanner I/O so concurrent tombstones deny delivery.
    if not Document.objects.filter(pk=document.pk, status=Document.Status.READY, expires_at__gt=timezone.now()).exists():
        return error(request, "Document is no longer available.", 404)
    response = FileResponse(io.BytesIO(data), as_attachment=True, filename=document.filename, content_type="application/octet-stream")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def job_detail(request, job_id):
    if not request.user.is_authenticated:
        return error(request, "Sign in to continue.", 401)
    if request.method == "GET":
        job = Job.objects.filter(owner=request.user, pk=job_id).filter(Q(document__isnull=True) | Q(document__expires_at__gt=timezone.now())).exclude(document__status__in=["deleting", "deleted"]).select_related("match", "document").first()
        if job is None:
            return error(request, "Not found.", 404)
        return JsonResponse(serialize_job(job))
    if request.method == "DELETE":
        with transaction.atomic():
            job = Job.objects.select_for_update().filter(owner=request.user, pk=job_id).first()
            if job is None:
                return error(request, "Not found.", 404)
            job.delete()
        return JsonResponse({"deleted": str(job_id), "request_id": str(request.request_id)})
    return error(request, "Method not allowed.", 405)
