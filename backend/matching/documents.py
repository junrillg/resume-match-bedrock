"""Private immutable originals; PostgreSQL retains admission and cleanup identity."""
import base64
import hashlib
import io
import socket
import struct
import uuid
from datetime import datetime, timedelta, timezone as datetime_timezone

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Document, Job
from .services import InvalidInput, MAX_FILE_BYTES, ProviderError, TransientProviderError, read_resume
from .telemetry import emit
from .events import lock_stream

PARSER_VERSION = "pypdf-6.21-text-v1"


class DocumentError(ProviderError):
    code = "document_rejected"


class DocumentUnavailable(TransientProviderError):
    code = "document_unavailable"


class ScanPending(DocumentUnavailable):
    pass


class DocumentIntegrityError(DocumentError):
    code = "document_integrity"


def client():
    if settings.DEBUG and not settings.DOCUMENT_ENDPOINT:
        raise DocumentUnavailable()
    options = {}
    if settings.DOCUMENT_ENDPOINT:
        options = {"endpoint_url": settings.DOCUMENT_ENDPOINT,
                   "aws_access_key_id": settings.DOCUMENT_ACCESS_KEY,
                   "aws_secret_access_key": settings.DOCUMENT_SECRET_KEY}
    return boto3.client("s3", region_name=settings.DOCUMENT_REGION, config=Config(
        connect_timeout=2, read_timeout=5, retries={"total_max_attempts": 1},
        s3={"addressing_style": "path"}, **({"proxies": {}} if options else {})), **options)


def read_source(text, upload):
    if bool(text.strip()) == bool(upload):
        raise InvalidInput("Provide pasted resume text OR one PDF/TXT file.")
    if upload:
        data = upload.read(MAX_FILE_BYTES + 1)
        filename = upload.name
        if upload.size > MAX_FILE_BYTES or len(data) > MAX_FILE_BYTES:
            raise InvalidInput("Resume file must be at most 1 MiB.")
        if not filename or len(filename) > 255 or any(ord(char) < 32 for char in filename):
            raise InvalidInput("Provide a printable filename of at most 255 characters.")
        if filename.lower().endswith(".pdf") and data.startswith(b"%PDF-"):
            content_type = "application/pdf"
        elif filename.lower().endswith(".txt"):
            content_type = "text/plain"
            try:
                read_resume(data.decode("utf-8-sig"), None)
            except UnicodeDecodeError:
                raise InvalidInput("TXT files must use UTF-8 encoding.") from None
        else:
            raise InvalidInput("Upload a valid PDF or UTF-8 TXT file.")
    else:
        read_resume(text, None)
        data, filename, content_type = text.encode("utf-8"), "pasted-resume.txt", "text/plain"
    return data, filename, content_type


def put_original(document, data):
    try:
        storage = client()
        response = storage.put_object(Bucket=settings.DOCUMENT_BUCKET, Key=document.object_key, Body=data,
                           ContentType=document.content_type, ContentMD5=base64.b64encode(hashlib.md5(data, usedforsecurity=False).digest()).decode())
        if response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 200:
            raise DocumentUnavailable()
    except (BotoCoreError, ClientError):
        raise DocumentUnavailable() from None


def _clam_command(command):
    with socket.create_connection((settings.DOCUMENT_SCANNER_HOST, settings.DOCUMENT_SCANNER_PORT), timeout=3) as stream:
        stream.settimeout(5)
        stream.sendall(command)
        result = b""
        while b"\0" not in result and len(result) < 512:
            chunk = stream.recv(min(512 - len(result), 512))
            if not chunk:
                break
            result += chunk
        return result.rstrip(b"\0\n")


def scan_bytes(data):
    try:
        version = _clam_command(b"zVERSION\0").decode("ascii")
        signature_date = datetime.strptime(version.rsplit("/", 1)[1], "%a %b %d %H:%M:%S %Y").replace(tzinfo=datetime_timezone.utc)
        age = timezone.now() - signature_date
        if age < timedelta(days=-1) or age > timedelta(days=settings.DOCUMENT_SIGNATURE_MAX_AGE_DAYS):
            raise DocumentUnavailable()
        with socket.create_connection((settings.DOCUMENT_SCANNER_HOST, settings.DOCUMENT_SCANNER_PORT), timeout=3) as stream:
            stream.settimeout(5)
            stream.sendall(b"zINSTREAM\0")
            for offset in range(0, len(data), 65536):
                chunk = data[offset:offset + 65536]
                stream.sendall(struct.pack(">I", len(chunk)) + chunk)
            stream.sendall(struct.pack(">I", 0))
            result = b""
            while b"\0" not in result and len(result) < 512:
                chunk = stream.recv(512 - len(result))
                if not chunk:
                    break
                result += chunk
        if result.rstrip(b"\0\n") != b"stream: OK":
            if result.rstrip(b"\0\n").endswith(b" FOUND"):
                raise DocumentError()
            raise DocumentUnavailable()
    except (OSError, UnicodeError, ValueError, IndexError):
        raise DocumentUnavailable() from None


def cloud_scan(storage, document):
    try:
        response = storage.get_object_tagging(Bucket=settings.DOCUMENT_BUCKET, Key=document.object_key)
        tags = {tag["Key"]: tag["Value"] for tag in response.get("TagSet", [])}
    except (BotoCoreError, ClientError, KeyError, TypeError):
        raise DocumentUnavailable() from None
    status = tags.get("GuardDutyMalwareScanStatus")
    if status == "NO_THREATS_FOUND":
        return
    if status in {"THREATS_FOUND", "UNSUPPORTED", "ACCESS_DENIED", "FAILED"}:
        raise DocumentError()
    raise ScanPending()


def get_original(document, *, scan=True):
    try:
        storage = client()
        if scan and settings.DOCUMENT_SCAN_MODE == "guardduty":
            cloud_scan(storage, document)
        response = storage.get_object(Bucket=settings.DOCUMENT_BUCKET, Key=document.object_key)
        body = response["Body"]
        try:
            data = body.read(MAX_FILE_BYTES + 1)
        finally:
            body.close()
    except (BotoCoreError, ClientError, OSError, KeyError):
        raise DocumentUnavailable() from None
    if len(data) != document.size_bytes or len(data) > MAX_FILE_BYTES or hashlib.sha256(data).hexdigest() != document.sha256:
        raise DocumentIntegrityError()
    if scan and settings.DOCUMENT_SCAN_MODE == "clamav":
        scan_bytes(data)
    return data


def document_text(claim):
    document = Document.objects.filter(pk=claim.document_id, owner_id=claim.owner_id,
                                       status__in=[Document.Status.PENDING, Document.Status.READY], expires_at__gt=timezone.now()).first()
    if document is None:
        raise DocumentError()
    try:
        from .admission import release_database
        release_database()
        data = get_original(document)
        if document.parser_version == PARSER_VERSION and document.extracted_text and not claim.reprocess:
            text = document.extracted_text
        else:
            if document.content_type == "text/plain":
                text = read_resume(data.decode("utf-8-sig"), None)
            else:
                from django.core.files.uploadedfile import SimpleUploadedFile
                text = read_resume("", SimpleUploadedFile(document.filename, data))
    except (DocumentError, InvalidInput, UnicodeError) as exc:
        # Keep rejected files inaccessible while the relay removes their bytes.
        with transaction.atomic():
            lock_stream(document.owner_id)
            current = Document.objects.select_for_update().get(pk=document.pk)
            if current.status not in {Document.Status.DELETING, Document.Status.DELETED}:
                current.status = Document.Status.REJECTED
                current.extracted_text = ""
                current.parser_version = ""
                current.delete_after = timezone.now()
                current.save()
        emit("document.rejected", document_id=document.id, job_id=claim.id, request_id=claim.request_id, stage="worker", status="rejected")
        raise exc if isinstance(exc, DocumentError) else DocumentError() from None
    with transaction.atomic():
        lock_stream(document.owner_id)
        current = Document.objects.select_for_update().get(pk=document.pk)
        if current.status not in {Document.Status.PENDING, Document.Status.READY} or current.expires_at <= timezone.now():
            raise DocumentError()
        current.status = Document.Status.READY
        current.extracted_text = text
        current.parser_version = PARSER_VERSION
        current.scan_checked_at = timezone.now()
        current.save()
    emit("document.ready", document_id=document.id, job_id=claim.id, request_id=claim.request_id, stage="worker", status="ready")
    return text


def tombstone(document):
    now = timezone.now()
    document.status = Document.Status.DELETING
    document.extracted_text = ""
    document.parser_version = ""
    document.filename = ""
    document.content_type = ""
    document.sha256 = ""
    document.size_bytes = 0
    document.delete_after = max(now, document.upload_lease_until or now)
    document.save()
    # Caller locks owner stream -> document -> job, shared with all mutations.
    for job in list(Job.objects.select_for_update().filter(document=document)):
        job.delete()


def reconcile_documents(limit=100):
    now = timezone.now()
    expired = Document.objects.exclude(status__in=[Document.Status.DELETING, Document.Status.DELETED]).filter(
        Q(expires_at__lte=now) | Q(status=Document.Status.UPLOADING, upload_deadline__lte=now)).values_list("pk", flat=True)[:limit]
    for document_id in list(expired):
        with transaction.atomic():
            lock_stream(Document.objects.filter(pk=document_id).values_list("owner_id", flat=True).first())
            document = Document.objects.select_for_update().filter(pk=document_id).first()
            if document and document.status not in {Document.Status.DELETING, Document.Status.DELETED}:
                tombstone(document)
    # Legacy source-cleared records still follow the same visible-history policy.
    for job in list(Job.objects.filter(document__isnull=True, created_at__lte=now - timedelta(days=settings.DOCUMENT_RETENTION_DAYS))[:limit]):
        with transaction.atomic():
            lock_stream(job.owner_id)
            Job.objects.filter(pk=job.pk).delete()
    from .models import Match
    for match in list(Match.objects.filter(job__isnull=True, created_at__lte=now - timedelta(days=settings.DOCUMENT_RETENTION_DAYS))[:limit]):
        with transaction.atomic():
            lock_stream(match.owner_id)
            Match.objects.filter(pk=match.pk).delete()
    now = timezone.now()
    candidates = Document.objects.filter(status__in=[Document.Status.DELETING, Document.Status.REJECTED], delete_after__lte=now).values_list("pk", flat=True)[:limit]
    for document_id in list(candidates):
        document = Document.objects.get(pk=document_id)
        try:
            from .admission import release_database
            release_database()
            client().delete_object(Bucket=settings.DOCUMENT_BUCKET, Key=document.object_key)
        except (BotoCoreError, ClientError):
            emit("document.delete_pending", document_id=document.id, stage="recovery", status="deleting")
            continue
        with transaction.atomic():
            lock_stream(Document.objects.filter(pk=document_id).values_list("owner_id", flat=True).first())
            current = Document.objects.select_for_update().get(pk=document_id)
            if current.status in {Document.Status.DELETING, Document.Status.REJECTED} and (not current.upload_lease_until or current.upload_lease_until <= timezone.now()):
                rejected = current.status == Document.Status.REJECTED
                current.status = Document.Status.REJECTED if rejected else Document.Status.DELETED
                current.deleted_at = timezone.now()
                current.delete_after = None
                current.filename = ""
                current.content_type = ""
                current.extracted_text = ""
                current.parser_version = ""
                current.sha256 = ""
                current.size_bytes = 0
                current.upload_lease = None
                current.upload_lease_until = None
                current.save()
                # Failed comparisons remain visible for rejected input until policy expiry.
                if not rejected:
                    Job.objects.filter(document=current).delete()
        emit("document.deleted", document_id=document.id, stage="recovery", status="deleted")

    # Seven days is a finite safety grace for late bounded upload finalizers, not source retention.
    stale = Document.objects.filter(status=Document.Status.DELETED, deleted_at__lte=timezone.now() - timedelta(days=7))
    for document_id in list(stale.values_list("pk", flat=True)[:limit]):
        with transaction.atomic():
            lock_stream(Document.objects.filter(pk=document_id).values_list("owner_id", flat=True).first())
            document = Document.objects.select_for_update().get(pk=document_id)
            if not document.upload_lease_until or document.upload_lease_until <= timezone.now():
                Job.objects.filter(document=document).delete()
                document.delete()
