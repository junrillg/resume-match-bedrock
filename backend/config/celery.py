import os
from pathlib import Path

from celery import Celery
from celery.signals import worker_ready, worker_shutdown
from kombu import Exchange, Queue

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
app = Celery("resume_match")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.conf.task_queues = (Queue("resume.match.quorum", Exchange("resume.match.quorum", type="direct", durable=True), routing_key="resume.match.quorum", durable=True, queue_arguments={"x-queue-type": "quorum"}),)
app.autodiscover_tasks()


@worker_ready.connect
def mark_worker_ready(**kwargs):
    Path("/tmp/resume-match-worker-ready").write_text(str(os.getpid()))


@worker_shutdown.connect
def clear_worker_ready(**kwargs):
    Path("/tmp/resume-match-worker-ready").unlink(missing_ok=True)
