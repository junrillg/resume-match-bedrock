#!/usr/bin/env python3
"""Verify the real local accept-to-result path: python backend/verify_business_delivery.py --run.

Uses HTTP login/admission, the running relay/broker/worker/provider, SSE and the
saved result. Only a disposable synthetic owner is created. Its original is
removed through the document deletion lifecycle before fixture records are removed.
Cookie/password/source bodies never enter output. No AWS endpoint is permitted.
"""
import argparse
from datetime import datetime, timezone
from http.cookiejar import CookieJar
import json
import secrets
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import build_opener, HTTPCookieProcessor, Request
import uuid

from verify_event_faults import django, docker

BASE = "http://127.0.0.1:8088"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Run one synthetic local business journey and clean its source through the normal lifecycle.")
    args = parser.parse_args()
    if not args.run:
        parser.print_help()
        return 0
    prefix = "business-delivery-" + uuid.uuid4().hex
    password = secrets.token_hex(32)
    fixture = None
    stream = None
    cookies = CookieJar()
    opener = build_opener(HTTPCookieProcessor(cookies))
    csrf = None
    session_keys = set()
    phase = "local_preflight"
    report = {"ok": False}

    def request(path, *, method="GET", values=None, encoding="json", headers=None, expected=200):
        nonlocal csrf
        outgoing = dict(headers or {})
        data = None
        if values is not None:
            if encoding == "form":
                data = urlencode(values).encode()
                outgoing["Content-Type"] = "application/x-www-form-urlencoded"
            else:
                data = json.dumps(values).encode()
                outgoing["Content-Type"] = "application/json"
        if method != "GET":
            outgoing.update({"Origin": BASE, "X-CSRFToken": csrf or ""})
        response = opener.open(Request(BASE + path, data=data, method=method, headers=outgoing), timeout=20)
        assert response.status == expected
        body = json.load(response)
        session_keys.update(cookie.value for cookie in cookies if cookie.name == "sessionid")
        if "csrfToken" in body:
            csrf = body["csrfToken"]
        return body, dict(response.headers)

    def sse_event():
        fields = {}
        while True:
            line = stream.readline().decode().strip()
            if not line:
                if "event" in fields:
                    return fields["event"], json.loads(fields.get("data", "{}"))
                fields = {}
            elif ": " in line:
                key, value = line.split(": ", 1)
                fields[key] = value

    try:
        local = json.loads(django("from django.conf import settings;from urllib.parse import urlsplit;"
            "print(json.dumps({'local':settings.DEBUG and settings.MATCH_PROVIDER=='bedrock-local' and "
            "urlsplit(settings.BEDROCK_LOCAL_ENDPOINT).hostname=='provider' and "
            "urlsplit(settings.DOCUMENT_ENDPOINT).hostname=='objectstore'}))"))
        if local.get("local") is not True:
            raise RuntimeError("Business verification requires the local provider and object storage.")
        fixture = json.loads(django("from django.contrib.auth import get_user_model;data=json.load(sys.stdin);"
            "user=get_user_model().objects.create_user(data['username'],password=data['password']);"
            "print(json.dumps({'owner_id':user.pk}))", {"username": prefix, "password": password}))
        phase = "http_login"
        request("/api/session/")
        login, _ = request("/api/login/", method="POST", values={"username": prefix, "password": password})
        assert login["authenticated"] is True and login["provider"] == "bedrock-local"
        password = None
        phase = "subscribe_before_submit"
        stream = opener.open(Request(BASE + "/api/events/"), timeout=20)
        event_name, event_data = sse_event()
        assert event_name == "ready"
        revision = event_data["revision"]
        started = datetime.now(timezone.utc).isoformat()
        phase = "http_accept"
        accepted, headers = request("/api/jobs/", method="POST", encoding="form", expected=202,
            headers={"Idempotency-Key": str(uuid.uuid4())}, values={
                "job_title": "Synthetic end-to-end verification",
                "resume_text": "Synthetic candidate built Python and Django services.",
                "requirements": json.dumps([{"skill": "Python", "weight": 3}, {"skill": "Django", "weight": 2}]),
            })
        job_id = accepted["id"]
        assert headers["Location"] == "/api/jobs/" + job_id + "/"
        assert accepted["status"] in {"queued", "running", "succeeded"}
        phase = "sse_terminal_delivery"
        seen = []
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            event_name, event_data = sse_event()
            assert event_name != "session-ended"
            if event_name == "change":
                assert event_data["revision"] > revision
                revision = event_data["revision"]
                seen.append(event_data["kind"])
                if event_data["kind"] == "inbox.changed" and event_data.get("job_id") == job_id:
                    break
        else:
            raise AssertionError("Terminal SSE event was absent")
        phase = "authorized_result_and_inbox"
        result, _ = request("/api/jobs/" + job_id + "/")
        assert result["status"] == "succeeded"
        assert result["match"]["score"] == 100
        assert result["match"]["provider"] == "bedrock-local"
        assert len(result["match"]["requirements"]) == 2
        inbox, _ = request("/api/notifications/?cursor=")
        assert len(inbox["notifications"]) == 1
        assert inbox["notifications"][0]["job_id"] == job_id
        assert inbox["notifications"][0]["href"] == "/results/" + job_id
        phase = "database_and_service_evidence"
        evidence = json.loads(django(
            "from matching.models import Job,OutboxEvent,CompletionNotification,StreamEvent;"
            "data=json.load(sys.stdin);job=Job.objects.get(pk=data['job_id'],owner_id=data['owner_id']);"
            "print(json.dumps({'request_id':str(job.request_id),'attempts':job.attempts,"
            "'dispatch_confirmed':OutboxEvent.objects.filter(job=job,sent_at__isnull=False).exists(),"
            "'notice_count':CompletionNotification.objects.filter(job=job,status='succeeded').count(),"
            "'durable_kinds':list(StreamEvent.objects.filter(owner_id=job.owner_id).values_list('kind',flat=True).distinct()),"
            "'saved_score':float(job.match.score)}))", {"owner_id": fixture["owner_id"], "job_id": job_id}))
        assert evidence["attempts"] >= 1 and evidence["dispatch_confirmed"] is True
        assert evidence["notice_count"] == 1 and evidence["saved_score"] == 100
        assert {"job.changed", "document.changed", "inbox.changed"} <= set(evidence["durable_kinds"])
        log_checks = {}
        for service, expected_event in {"relay": "job.published", "worker": "job.started",
                                        "provider": "provider.completed", "event-relay": "delivery.published"}.items():
            lines = docker("logs", "--no-color", "--since", started, service)
            found = False
            for line in lines.splitlines():
                offset = line.find("{")
                if offset < 0:
                    continue
                try:
                    entry = json.loads(line[offset:])
                except ValueError:
                    continue
                if entry.get("event") == expected_event and entry.get("job_id") == job_id:
                    found = True
                    break
            log_checks[expected_event] = found
        assert all(log_checks.values())
        report = {"ok": True, "accepted_status": 202, "score": 100, "sse_change_count": len(seen),
                  "verified_steps": ["HTTP admission", "confirmed broker dispatch", "worker claim", "local Converse provider",
                                     "saved result and notification", "durable delivery ledger", "SSE completion", "authorized result read"],
                  "correlated_service_logs": log_checks}
    except Exception as error:
        report = {"ok": False, "phase": phase, "error_type": type(error).__name__}
    finally:
        if stream:
            stream.close()
        if fixture:
            try:
                # Find only this fixture's documents, including ambiguous accepted requests.
                documents = json.loads(django("from matching.models import Document;data=json.load(sys.stdin);"
                    "print(json.dumps([str(pk) for pk in Document.objects.filter(owner_id=data['owner_id']).values_list('pk',flat=True)]))", fixture))
                for document_id in documents:
                    try:
                        request("/api/documents/" + document_id + "/", method="DELETE", expected=202)
                    except HTTPError as error:
                        if error.code != 404:
                            raise
                cleanup_deadline = time.monotonic() + 45
                while True:
                    deleted = json.loads(django(
                        "from matching.models import Document;from matching.documents import client;from botocore.exceptions import ClientError;"
                        "data=json.load(sys.stdin);docs=list(Document.objects.filter(owner_id=data['owner_id']));"
                        "removed=all(doc.status=='deleted' for doc in docs);"
                        "\nif removed:\n for doc in docs:\n  try:\n   client().head_object(Bucket=__import__('django.conf',fromlist=['settings']).settings.DOCUMENT_BUCKET,Key=doc.object_key);removed=False\n  except ClientError as error:\n   if error.response['Error']['Code'] not in {'404','NoSuchKey','NotFound'}:raise\n"
                        "print(json.dumps({'removed':removed}))", fixture))
                    if deleted["removed"]:
                        break
                    if time.monotonic() >= cleanup_deadline:
                        raise TimeoutError("Original cleanup did not complete")
                    time.sleep(.5)
                try:
                    request("/api/logout/", method="POST")
                except HTTPError:
                    pass
                django("from django.contrib.auth import get_user_model;from django.contrib.sessions.models import Session;"
                       "from matching.models import Document,RateBucket;from django.db import transaction;from matching.events import lock_stream;"
                       "data=json.load(sys.stdin);user=get_user_model().objects.get(pk=data['owner_id'],username=data['username']);"
                       "\nwith transaction.atomic():\n lock_stream(user.pk)\n Document.objects.filter(owner=user,status='deleted').delete()\n"
                       " RateBucket.objects.filter(key__startswith='match:'+str(user.pk)+':').delete()\n"
                       " Session.objects.filter(session_key__in=data['session_keys']).delete()\n user.delete()\n",
                       {**fixture, "username": prefix, "session_keys": list(session_keys)})
                report["cleanup"] = {"originals_physically_removed": True, "fixture_records_removed": True}
            except Exception as error:
                report["ok"] = False
                report["cleanup_pending"] = True
                report["fixture_owner_id"] = fixture["owner_id"]
                report["cleanup_error_type"] = type(error).__name__
        print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
