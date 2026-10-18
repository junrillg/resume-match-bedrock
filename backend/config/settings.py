import os
import ssl
from pathlib import Path
from urllib.parse import quote, urlsplit

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.getenv("DJANGO_DEBUG", "true").lower() == "true"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "local-development-only-do-not-deploy")
if not DEBUG and SECRET_KEY == "local-development-only-do-not-deploy":
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY for non-development execution.")
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",")
INSTALLED_APPS = ["django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions", "matching"]
MIDDLEWARE = [
    "matching.middleware.RequestMetadataMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "matching.middleware.ReadinessMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
if os.getenv("POSTGRES_HOST"):
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": os.environ["POSTGRES_HOST"],
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ["POSTGRES_USER"],
        "PASSWORD": os.environ["POSTGRES_PASSWORD"],
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {"connect_timeout": 3},
    }}
    if os.getenv("POSTGRES_SSLMODE"):
        if os.environ["POSTGRES_SSLMODE"] != "verify-full" or not os.getenv("POSTGRES_SSLROOTCERT"):
            raise ImproperlyConfigured("Database TLS requires verify-full and POSTGRES_SSLROOTCERT.")
        DATABASES["default"]["OPTIONS"].update(sslmode="verify-full", sslrootcert=os.environ["POSTGRES_SSLROOTCERT"])
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3", "OPTIONS": {"timeout": 10}}}
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
USE_TZ = True
TIME_ZONE = "UTC"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DATA_UPLOAD_MAX_MEMORY_SIZE = 1_100_000
FILE_UPLOAD_MAX_MEMORY_SIZE = DATA_UPLOAD_MAX_MEMORY_SIZE
FILE_UPLOAD_HANDLERS = ["django.core.files.uploadhandler.MemoryFileUploadHandler"]
DATA_UPLOAD_MAX_NUMBER_FILES = 1
DATA_UPLOAD_MAX_NUMBER_FIELDS = 5
CSRF_FAILURE_VIEW = "matching.views.csrf_failure"
CSRF_TRUSTED_ORIGINS = [value for value in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if value]
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 3600
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_SSL_REDIRECT = not DEBUG
SECURE_REDIRECT_EXEMPT = [r"^api/health/$"]
# Enable only behind the isolated, co-located proxy that overwrites this header.
if os.getenv("DJANGO_TRUST_PROXY", "false").lower() == "true":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 0 if DEBUG else 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
X_FRAME_OPTIONS = "DENY"
MATCH_PROVIDER = os.getenv("MATCH_PROVIDER", "demo")
BEDROCK_REGION = os.getenv("AWS_REGION", "")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "")
BEDROCK_LOCAL_ENDPOINT = os.getenv("BEDROCK_LOCAL_ENDPOINT", "")
BEDROCK_READ_TIMEOUT_SECONDS = 30
if MATCH_PROVIDER not in {"demo", "bedrock-local", "bedrock"}:
    raise ImproperlyConfigured("MATCH_PROVIDER must be demo, bedrock-local or bedrock.")
if MATCH_PROVIDER == "bedrock" and not (BEDROCK_REGION and BEDROCK_MODEL_ID):
    raise ImproperlyConfigured("Bedrock requires AWS_REGION and BEDROCK_MODEL_ID.")
if BEDROCK_LOCAL_ENDPOINT:
    endpoint = urlsplit(BEDROCK_LOCAL_ENDPOINT)
    if endpoint.scheme != "http" or endpoint.hostname not in {"provider", "localhost", "127.0.0.1", "::1"} or endpoint.username or endpoint.password or endpoint.path or endpoint.query or endpoint.fragment:
        raise ImproperlyConfigured("BEDROCK_LOCAL_ENDPOINT must name the local HTTP contract service.")
    if MATCH_PROVIDER != "bedrock-local":
        raise ImproperlyConfigured("A local endpoint is valid only for bedrock-local.")
if MATCH_PROVIDER == "bedrock-local" and (not DEBUG or not BEDROCK_LOCAL_ENDPOINT or BEDROCK_MODEL_ID != "local-evidence-v1" or not BEDROCK_REGION):
    raise ImproperlyConfigured("bedrock-local requires development mode, local endpoint, region and local-evidence-v1 model.")
LOG_VIEWER_URL = os.getenv("LOG_VIEWER_URL", "")
if LOG_VIEWER_URL:
    viewer = urlsplit(LOG_VIEWER_URL)
    if viewer.scheme not in {"http", "https"} or not viewer.hostname or viewer.username or viewer.password:
        raise ImproperlyConfigured("LOG_VIEWER_URL must be an HTTP(S) URL without credentials.")
MATCH_DAILY_LIMIT = 20
OTEL_LOGS_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "")
OPENOBSERVE_PASSWORD = os.getenv("OPENOBSERVE_PASSWORD", "")
LAB_SERVICE_NAME = os.getenv("LAB_SERVICE_NAME", "api")
JOB_MAX_ATTEMPTS = 3
JOB_DEADLINE_SECONDS = 600
JOB_LEASE_SECONDS = 90
JOB_WAKE_SECONDS = 30
JOB_RETRY_SECONDS = 2
RABBITMQ_TLS = os.getenv("RABBITMQ_TLS", "false").lower() == "true"
CELERY_BROKER_URL = "{}://{}:{}@{}:{}//".format(
    "amqps" if RABBITMQ_TLS else "amqp",
    quote(os.getenv("RABBITMQ_USER", "lab"), safe=""),
    quote(os.getenv("RABBITMQ_PASSWORD", ""), safe=""),
    os.getenv("RABBITMQ_HOST", "127.0.0.1"),
    5671 if RABBITMQ_TLS else 5672,
)
if RABBITMQ_TLS:
    # py-amqp enables SSLContext.check_hostname when server_hostname is present.
    CELERY_BROKER_USE_SSL = {"cert_reqs": ssl.CERT_REQUIRED, "server_hostname": os.getenv("RABBITMQ_HOST", "127.0.0.1")}
CELERY_BROKER_CONNECTION_TIMEOUT = 3
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_HEARTBEAT = 10
CELERY_BROKER_TRANSPORT_OPTIONS = {"confirm_publish": True, "read_timeout": 3, "write_timeout": 3}
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_STORE_ERRORS_EVEN_IF_IGNORED = False
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_WORKER_ENABLE_REMOTE_CONTROL = False
CELERY_WORKER_SEND_TASK_EVENTS = True
CELERY_TASK_SEND_SENT_EVENT = True
CELERY_WORKER_CANCEL_LONG_RUNNING_TASKS_ON_CONNECTION_LOSS = True
CELERY_TASK_SOFT_TIME_LIMIT = 50
CELERY_TASK_TIME_LIMIT = 60
CELERY_TASK_CREATE_MISSING_QUEUES = False
CELERY_TASK_DEFAULT_QUEUE = "resume.match.quorum"
CELERY_TASK_DEFAULT_QUEUE_TYPE = "quorum"
CELERY_TASK_DEFAULT_EXCHANGE = "resume.match.quorum"
CELERY_TASK_DEFAULT_ROUTING_KEY = "resume.match.quorum"
CELERY_TASK_DEFAULT_DELIVERY_MODE = "persistent"
CELERY_TASK_PUBLISH_RETRY = False
LOGGING = {"version": 1, "disable_existing_loggers": False, "handlers": {"console": {"class": "logging.StreamHandler"}}, "loggers": {"matching.audit": {"handlers": ["console"], "level": "INFO", "propagate": False}}}

# Originals use immutable generated keys. Local endpoints never discover cloud credentials.
DOCUMENT_BUCKET = os.getenv("DOCUMENT_BUCKET", "resume-originals")
DOCUMENT_ENDPOINT = os.getenv("DOCUMENT_ENDPOINT", "")
DOCUMENT_REGION = os.getenv("DOCUMENT_REGION", "us-east-1")
DOCUMENT_ACCESS_KEY = os.getenv("DOCUMENT_ACCESS_KEY", "")
DOCUMENT_SECRET_KEY = os.getenv("DOCUMENT_SECRET_KEY", "")
DOCUMENT_SCAN_MODE = os.getenv("DOCUMENT_SCAN_MODE", "guardduty")
DOCUMENT_RETENTION_DAYS = int(os.getenv("DOCUMENT_RETENTION_DAYS", "90"))
DOCUMENT_UPLOAD_TTL_SECONDS = 3600
DOCUMENT_UPLOAD_LEASE_SECONDS = 90
DOCUMENT_SCANNER_HOST = os.getenv("DOCUMENT_SCANNER_HOST", "scanner")
DOCUMENT_SCANNER_PORT = int(os.getenv("DOCUMENT_SCANNER_PORT", "3310"))
DOCUMENT_SIGNATURE_MAX_AGE_DAYS = 14
if not 1 <= DOCUMENT_RETENTION_DAYS <= 3650:
    raise ImproperlyConfigured("DOCUMENT_RETENTION_DAYS must be 1–3650.")
if DOCUMENT_SCAN_MODE not in {"clamav", "guardduty"}:
    raise ImproperlyConfigured("DOCUMENT_SCAN_MODE must be clamav or guardduty.")
if DOCUMENT_ENDPOINT:
    endpoint = urlsplit(DOCUMENT_ENDPOINT)
    if not DEBUG or endpoint.scheme != "http" or endpoint.hostname not in {"objectstore", "localhost", "127.0.0.1"} or endpoint.username or endpoint.password or endpoint.path or endpoint.query or endpoint.fragment:
        raise ImproperlyConfigured("DOCUMENT_ENDPOINT is restricted to local development object storage.")
    if not DOCUMENT_ACCESS_KEY or not DOCUMENT_SECRET_KEY or DOCUMENT_SCAN_MODE != "clamav":
        raise ImproperlyConfigured("Local object storage requires explicit local credentials and ClamAV.")
