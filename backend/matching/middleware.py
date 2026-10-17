import logging
import time
import uuid
from django.core.exceptions import RequestDataTooBig, TooManyFieldsSent, TooManyFilesSent
from django.http import JsonResponse

audit = logging.getLogger("matching.audit")


class ReadinessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # ALB health probes use the target IP Host, not the public DNS name.
        if request.path_info == "/api/health/":
            from .views import health
            return health(request)
        return self.get_response(request)


class RequestMetadataMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = uuid.uuid4()
        start = time.monotonic()
        try:
            if int(request.META.get("CONTENT_LENGTH") or 0) > 1_100_000:
                response = JsonResponse({"error": "Request body is too large.", "request_id": str(request.request_id)}, status=413)
            else:
                response = self.get_response(request)
        except (RequestDataTooBig, TooManyFieldsSent, TooManyFilesSent, ValueError):
            response = JsonResponse({"error": "Invalid request body.", "request_id": str(request.request_id)}, status=400)
        response["X-Request-ID"] = str(request.request_id)
        response["Cache-Control"] = "no-store"
        response["X-Frame-Options"] = "DENY"
        # Never log request bodies, filenames, usernames, provider output or exception text.
        audit.info("request_id=%s method=%s status=%s duration_ms=%d", request.request_id, request.method, response.status_code, (time.monotonic() - start) * 1000)
        return response
