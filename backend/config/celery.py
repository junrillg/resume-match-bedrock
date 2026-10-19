import os
import time
import uuid
from pathlib import Path

from celery import Celery
from celery.signals import heartbeat_sent, worker_ready, worker_shutdown
from kombu import Exchange, Queue

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
app = Celery("resume_match")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.conf.task_queues = (Queue("resume.match.quorum", Exchange("resume.match.quorum", type="direct", durable=True), routing_key="resume.match.quorum", durable=True, queue_arguments={"x-queue-type": "quorum"}),)
app.autodiscover_tasks()


_supply_id = uuid.uuid4()
_last_supply = 0.0
_ready = False


@heartbeat_sent.connect
def mark_supply(**kwargs):
    global _last_supply
    if not _ready or time.monotonic() - _last_supply < 10:
        return
    from django.db import connections
    from django.utils import timezone
    from matching.models import WorkerSupply
    try:
        WorkerSupply.objects.update_or_create(pk=_supply_id, defaults={"last_seen": timezone.now()})
        _last_supply = time.monotonic()
    except Exception:
        # Missing liveness fails admission closed; never serialize raw DB errors.
        pass
    finally:
        connections.close_all()


@worker_ready.connect
def mark_worker_ready(**kwargs):
    global _ready
    _ready = True
    Path("/tmp/resume-match-worker-ready").write_text(str(os.getpid()))
    mark_supply()


@worker_shutdown.connect
def clear_worker_ready(**kwargs):
    global _ready
    _ready = False
    Path("/tmp/resume-match-worker-ready").unlink(missing_ok=True)
    from django.db import connections
    from matching.models import WorkerSupply
    try:
        WorkerSupply.objects.filter(pk=_supply_id).delete()
    except Exception:
        pass
    finally:
        connections.close_all()
