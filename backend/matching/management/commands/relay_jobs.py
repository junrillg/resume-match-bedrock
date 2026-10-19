"""Productive confirmed drain; slow source cleanup has its own bounded worker."""
import threading
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connections

from config.celery import app
from matching.admission import maintenance_once, sample_supply
from matching.jobs import relay_once
from matching.telemetry import emit


class Command(BaseCommand):
    help = "Drain committed dispatches with a reused confirmed producer and bounded maintenance."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run one bounded relay cycle and exit.")

    def handle(self, *args, **options):
        stopped = threading.Event()

        def maintain():
            while not stopped.is_set():
                try:
                    maintenance_once(settings.RELAY_MAINTENANCE_BATCH_SIZE)
                except Exception:
                    emit("job.interrupted", stage="recovery", status="interrupted", error_code="processing_failed")
                finally:
                    connections.close_all()
                stopped.wait(settings.RELAY_MAINTENANCE_INTERVAL_SECONDS)

        if not options["once"]:
            threading.Thread(target=maintain, name="bounded-maintenance", daemon=True).start()
        else:
            maintenance_once(settings.RELAY_MAINTENANCE_BATCH_SIZE)
        sampled = 0.0
        try:
            while not stopped.is_set():
                try:
                    with app.producer_pool.acquire(block=True, timeout=3) as producer:
                        try:
                            producer.connection.ensure_connection(max_retries=0)
                            while not stopped.is_set():
                                producer.connection.heartbeat_check()
                                if time.monotonic() - sampled >= settings.RELAY_MAINTENANCE_INTERVAL_SECONDS:
                                    sample_supply(True)
                                    sampled = time.monotonic()
                                sent = relay_once(settings.RELAY_BATCH_SIZE, producer=producer, maintenance=False)
                                Path("/tmp/resume-match-relay-heartbeat").touch()
                                connections.close_all()
                                if options["once"]:
                                    return
                                stopped.wait(settings.RELAY_PRODUCTIVE_DELAY_SECONDS if sent else settings.RELAY_IDLE_DELAY_SECONDS)
                        except Exception:
                            # Discard the failed session; confirmed rows remain durable,
                            # unconfirmed rows are replayable with idempotent worker effects.
                            producer.connection.close()
                            raise
                except Exception:
                    emit("job.publish_failed", stage="relay", status="unpublished", error_code="publish_unavailable")
                    try:
                        sample_supply(False)
                    finally:
                        connections.close_all()
                    if options["once"]:
                        return
                    stopped.wait(settings.RELAY_IDLE_DELAY_SECONDS)
        finally:
            stopped.set()
            connections.close_all()
