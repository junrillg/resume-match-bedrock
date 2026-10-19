import time
from pathlib import Path
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from matching.events import prune_events, redis_options, relay_events, ShardedPublisher, delivery_stats
from matching.telemetry import emit


class Command(BaseCommand):
    help = "Publish bounded durable delivery intents and prune retained published events."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        client = ShardedPublisher()
        last_prune = 0
        last_metrics = 0
        published = 0
        while True:
            close_old_connections()
            try:
                sent = relay_events(client)
                published += sent
                if time.monotonic() - last_metrics > 30:
                    emit("delivery.snapshot", stage="event-relay", published_count=published, **delivery_stats())
                    last_metrics = time.monotonic()
                if time.monotonic() - last_prune > 60:
                    prune_events()
                    last_prune = time.monotonic()
                Path("/tmp/resume-match-event-relay-heartbeat").touch()
            except Exception:
                # No exception rendering: SDK errors can contain connection credentials.
                sent = 0
            if options["once"]:
                return
            time.sleep(0.05 if sent else 0.5)
