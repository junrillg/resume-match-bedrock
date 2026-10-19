#!/usr/bin/env python3
"""Local two-shard outage proof: python backend/verify_event_faults.py --restart-fanout.

Restarts one disposable fan-out service, preserves database/originals/broker volumes,
and removes only its own synthetic accounts and sessions. Credentials stay in memory.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent


def docker(*arguments, input=None):
    result = subprocess.run(["docker", "compose", *arguments], cwd=ROOT, input=input,
                            text=True, capture_output=True, timeout=45, check=True)
    return result.stdout


def django(script, data=None):
    prelude = "import os,json,sys;os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings');import django;django.setup();"
    return docker("exec", "-T", "api", "python", "-c", prelude + script,
                  input=None if data is None else json.dumps(data))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restart-fanout", action="store_true", help="Run the local fault check, restarting one disposable Valkey shard.")
    args = parser.parse_args()
    if not args.restart_fanout:
        parser.print_help()
        return 0
    fixtures = None
    opened = []
    stopped = None
    phase = "seed"
    try:
        prefix = "fanout-fault-" + uuid.uuid4().hex
        fixtures = json.loads(django(
            "from django.contrib.auth import get_user_model;from django.test import Client;"
            f"users=[get_user_model().objects.create_user({prefix!r}+str(i)) for i in range(2)];"
            "clients=[Client(),Client()];[c.force_login(u) for c,u in zip(clients,users)];"
            "print(json.dumps({'owners':[u.pk for u in users],'sessions':[c.session.session_key for c in clients]}))"))
        def stream(index):
            response = urlopen(Request("http://127.0.0.1:8088/api/events/", headers={
                "Cookie": "sessionid=" + fixtures["sessions"][index]}), timeout=10)
            opened.append(response)
            return response
        def event(response, wanted):
            fields = {}
            for _ in range(100):
                line = response.readline().decode().strip()
                if not line:
                    if fields.get("event") == wanted:
                        return json.loads(fields["data"])
                    fields = {}
                elif ": " in line:
                    key, value = line.split(": ", 1)
                    fields[key] = value
            raise AssertionError("Expected event absent")
        phase = "connect"
        primary = [stream(0) for _ in range(5)]
        for response in primary:
            assert event(response, "ready")["revision"] == 0
        secondary = stream(1)
        assert event(secondary, "ready")["revision"] == 0
        shard = "fanout" if fixtures["owners"][0] % 2 == 0 else "fanout-b"
        phase = "stop_one_shard"
        docker("stop", shard)
        stopped = shard
        django("from matching.events import record_change;[record_change(owner,'workspace.changed') for owner in json.load(sys.stdin)]", fixtures["owners"])
        phase = "unaffected_shard_stays_live"
        assert event(secondary, "change")["revision"] == 1
        phase = "restore_shard"
        docker("start", shard)
        stopped = None
        phase = "durable_recovery"
        for response in primary:
            assert event(response, "change")["revision"] == 1
        phase = "global_limit_after_cache_loss"
        try:
            stream(0)
            raise AssertionError("Sixth owner stream was admitted after cache restart")
        except HTTPError as error:
            assert error.code == 429
        count = docker("exec", "-T", shard, "sh", "-c",
                       'export REDISCLI_AUTH="$STREAM_VIEWER_PASSWORD"; valkey-cli --user viewer ZCARD "owner-cap:$1"',
                       "sh", str(fixtures["owners"][0])).strip()
        assert count == "5"
        print(json.dumps({"ok": True, "connected_owner_streams_after_restart": 5,
                          "global_cap_rebuilt_before_delivery": True,
                          "unaffected_shard_continued_delivery": True,
                          "missed_wake_recovered_from_database": True}, sort_keys=True))
        return 0
    except Exception as error:
        print(json.dumps({"ok": False, "phase": phase, "error_type": type(error).__name__}, sort_keys=True))
        return 1
    finally:
        if stopped:
            docker("start", stopped)
        for response in opened:
            response.close()
        if fixtures:
            django("from django.contrib.auth import get_user_model;from django.contrib.sessions.models import Session;"
                   "data=json.load(sys.stdin);Session.objects.filter(session_key__in=data['sessions']).delete();"
                   "get_user_model().objects.filter(pk__in=data['owners']).delete()", fixtures)


if __name__ == "__main__":
    raise SystemExit(main())
