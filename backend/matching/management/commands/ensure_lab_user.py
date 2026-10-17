import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create the local synthetic lab account once; never print or reset its password."

    def handle(self, *args, **options):
        if not settings.DEBUG or settings.MATCH_PROVIDER not in {"demo", "bedrock-local"}:
            raise CommandError("The synthetic account is restricted to the local demo.")
        password = os.getenv("LAB_DEMO_PASSWORD", "")
        if len(password) < 24:
            raise CommandError("LAB_DEMO_PASSWORD must contain at least 24 characters.")
        users = get_user_model().objects
        if not users.filter(username="lab").exists():
            users.create_user(username="lab", password=password)
        self.stdout.write("Local demo account ready.")
