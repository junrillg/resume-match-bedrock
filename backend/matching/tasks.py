import logging

from celery import shared_task
from .jobs import run_job

audit = logging.getLogger("matching.audit")


@shared_task(name="matching.process_job", ignore_result=True)
def process_job(job_id):
    try:
        run_job(job_id)
    except Exception:
        # The relay recovers queued/leased work; Celery must never format raw failures.
        audit.error("stage=worker status=interrupted")
