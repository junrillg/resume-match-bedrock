import time
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from matching.jobs import relay_once


class Command(BaseCommand):
    help = "Publish committed outbox dispatches and recover expired work; never expose payloads."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run one bounded relay cycle and exit.")

    def handle(self, *args, **options):
        while True:
            close_old_connections()
            relay_once()
            Path("/tmp/resume-match-relay-heartbeat").touch()
            if options["once"]:
                return
            time.sleep(2)
