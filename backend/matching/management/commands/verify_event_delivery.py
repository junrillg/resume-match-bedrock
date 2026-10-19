"""Live local two-gateway verification; fixture credentials never leave memory."""
import json
import time
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.test import Client

from matching.events import record_change
from matching.models import StreamEvent, StreamState


class Command(BaseCommand):
    help = "Verify real local SSE fan-out, global caps, replay/reset and session revocation using isolated disposable accounts."

    def handle(self, *args, **options):
        if not settings.DEBUG or not 1 <= settings.STREAM_MAX_OWNER_CONNECTIONS <= 20:
            raise CommandError("This bounded verification is restricted to the local development deployment.")
        owner = get_user_model().objects.create_user("delivery-verify-" + uuid.uuid4().hex)
        other = None
        client = Client()
        session_keys = []
        opened = []

        def login():
            client.force_login(owner)
            key = client.cookies[settings.SESSION_COOKIE_NAME].value
            session_keys.append(key)
            return key

        session_key = login()

        def stream(host, cursor=None, origin=None):
            # These names are the two Compose services; no arbitrary outbound URL.
            url = f"http://{host}:8001/api/events/" + ("" if cursor is None else "?cursor=" + str(cursor))
            headers = {"Host": "localhost", "Cookie": settings.SESSION_COOKIE_NAME + "=" + session_key}
            if origin:
                headers["Origin"] = origin
            response = urlopen(Request(url, headers=headers), timeout=6)
            opened.append(response)
            return response

        def event(response, wanted):
            current = {}
            for _ in range(100):
                line = response.readline().decode().strip()
                if not line:
                    if current.get("event") == wanted:
                        return json.loads(current["data"])
                    current = {}
                elif ": " in line:
                    key, value = line.split(": ", 1)
                    current[key] = value
            raise AssertionError("Expected delivery event was absent.")

        try:
            for index in range(settings.STREAM_MAX_OWNER_CONNECTIONS):
                response = stream("events-a" if index % 2 == 0 else "events-b")
                assert event(response, "ready")["revision"] == 0
            try:
                stream("events-b")
                raise AssertionError("Global owner limit was not enforced.")
            except HTTPError as error:
                assert error.code == 429
            revision = record_change(owner.pk, "workspace.changed")
            for response in opened:
                assert event(response, "change")["revision"] == revision
            try:
                stream("events-a", origin="https://invalid.example")
                raise AssertionError("Cross-origin stream was admitted.")
            except HTTPError as error:
                assert error.code == 403
            assert client.post("/api/logout/", HTTP_HOST="localhost").status_code == 200
            for response in opened:
                assert event(response, "session-ended") == {}
                response.close()
            opened.clear()
            session_key = login()
            response = stream("events-b", 0)
            assert event(response, "change")["revision"] == 1
            assert event(response, "ready")["revision"] == 2
            response.close()
            opened.clear()
            StreamState.objects.filter(owner=owner).update(floor_revision=2)
            StreamEvent.objects.filter(owner=owner).delete()
            response = stream("events-a", 0)
            assert event(response, "reset")["revision"] == 2
            assert event(response, "ready")["revision"] == 2
            owner.set_password(uuid.uuid4().hex)
            owner.save()
            assert event(response, "session-ended") == {}
            response.close()
            opened.clear()
            session_key = login()
            response = stream("events-b")
            event(response, "ready")
            owner.is_active = False
            owner.save()
            assert event(response, "session-ended") == {}
            response.close()
            opened.clear()
            owner.is_active = True
            owner.save()
            session_key = login()
            response = stream("events-a")
            event(response, "ready")
            password = uuid.uuid4().hex
            other = get_user_model().objects.create_user("delivery-switch-" + uuid.uuid4().hex, password=password)
            switched = client.post("/api/login/", data=json.dumps({"username":other.username,"password":password}), content_type="application/json", HTTP_HOST="localhost")
            assert switched.status_code == 200
            session_keys.append(client.cookies[settings.SESSION_COOKIE_NAME].value)
            assert event(response, "session-ended") == {}
            self.stdout.write(json.dumps({
                "global_owner_cap_across_two_gateways": settings.STREAM_MAX_OWNER_CONNECTIONS,
                "wake_reaches_both_gateways": True, "logout_ends_all_streams": True,
                "cross_origin_denied": True, "ordered_replay": True, "expired_cursor_reset": True,
                "password_change_ends_stream": True, "account_deactivation_ends_stream": True, "account_switch_ends_previous_owner_stream":True,
            }, sort_keys=True))
        except Exception:
            raise CommandError("Live delivery verification failed. Check local gateway/relay health; no credentials were printed.") from None
        finally:
            for response in opened:
                response.close()
            Session.objects.filter(session_key__in=session_keys).delete()
            owner.delete()
            if other is not None:
                other.delete()
