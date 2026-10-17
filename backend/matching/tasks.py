from celery import shared_task
from .jobs import run_job
from .telemetry import emit


@shared_task(name="matching.process_job", ignore_result=True)
def process_job(job_id):
    try:
        run_job(job_id)
    except Exception:
        # The relay recovers queued/leased work; Celery must never format raw failures.
        emit("job.interrupted", job_id=job_id, stage="worker", status="interrupted", error_code="processing_failed")
