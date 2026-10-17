import hashlib
import json
from datetime import timedelta

from django.conf import settings
from django.contrib import auth
from django.core.exceptions import RequestDataTooBig, TooManyFieldsSent, TooManyFilesSent
from django.db.models import F
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone

from .models import Match, RateBucket
from .services import InvalidInput, ProviderError, calculate_score, extract_evidence, read_requirements, read_resume


def error(request, message, status):
    return JsonResponse({"error": message, "request_id": str(request.request_id)}, status=status)


def csrf_failure(request, reason=""):
    return error(request, "CSRF verification failed. Refresh and try again.", 403)


def not_found(request, exception=None):
    return error(request, "Not found.", 404)


def server_error(request):
    return error(request, "Unexpected server error.", 500)


def session_payload(request):
    payload = {"authenticated": request.user.is_authenticated, "csrfToken": get_token(request), "provider": settings.MATCH_PROVIDER}
    if request.user.is_authenticated:
        payload["username"] = request.user.get_username()
    return payload


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


def matches(request):
    if not request.user.is_authenticated:
        return error(request, "Sign in to continue.", 401)
    if request.method == "GET":
        return JsonResponse({"matches": [serialize(record) for record in Match.objects.filter(owner=request.user)[:100]]})
    if request.method != "POST":
        return error(request, "Method not allowed.", 405)
    try:
        if set(request.POST) - {"resume_text", "requirements", "job_title"} or set(request.FILES) - {"resume"}:
            raise InvalidInput("Unexpected form fields.")
        if any(len(request.POST.getlist(key)) != 1 for key in request.POST) or len(request.FILES.getlist("resume")) > 1:
            raise InvalidInput("Repeated form fields are unsupported.")
        title = request.POST.get("job_title", "").strip()
        if not 1 <= len(title) <= 120 or any(ord(c) < 32 for c in title):
            raise InvalidInput("Job title must contain 1–120 printable characters.")
        requirements = read_requirements(request.POST.get("requirements"))
        text = read_resume(request.POST.get("resume_text", ""), request.FILES.get("resume"))
    except (InvalidInput, RequestDataTooBig, TooManyFieldsSent, TooManyFilesSent) as exc:
        message = str(exc) if isinstance(exc, InvalidInput) else "Request body exceeds upload limits."
        return error(request, message, 400)
    now = timezone.now()
    if not consume_bucket(f"match:{request.user.pk}:{now.date()}", settings.MATCH_DAILY_LIMIT, now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)):
        return error(request, "Daily matching limit reached. Try again tomorrow (UTC).", 429)
    try:
        evidence = extract_evidence(text, requirements)
    except ProviderError:
        return error(request, "Evidence provider unavailable or returned invalid evidence. No result was saved.", 502)
    record = Match.objects.create(owner=request.user, job_title=title, score=calculate_score(evidence), provider=settings.MATCH_PROVIDER, requirements=evidence, request_id=request.request_id)
    return JsonResponse(serialize(record), status=201)


def match_detail(request, match_id):
    if not request.user.is_authenticated:
        return error(request, "Sign in to continue.", 401)
    if request.method != "DELETE":
        return error(request, "Method not allowed.", 405)
    deleted, _ = Match.objects.filter(owner=request.user, pk=match_id).delete()
    if not deleted:
        return error(request, "Not found.", 404)
    return JsonResponse({"deleted": str(match_id), "request_id": str(request.request_id)})
