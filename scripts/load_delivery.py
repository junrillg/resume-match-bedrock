#!/usr/bin/env python3
"""Exercise real authenticated SSE connections through the local Compose proxy.

Uses disposable owners and sessions. Credentials stay in memory and never enter the
report. This is a bounded local delivery benchmark, not a million-user certification.
"""
import argparse
import asyncio
from collections import Counter
import json
import hashlib
import os
from pathlib import Path
import resource
import re
import random
import ssl
import statistics
import subprocess
import time
import uuid
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent


def shell(code):
    result = subprocess.run(["docker", "compose", "exec", "-T", "api", "python", "manage.py", "shell"],
                            input=code, cwd=ROOT, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError("Synthetic fixture operation failed; inspect the local application logs privately.")
    lines = [line[12:] for line in result.stdout.splitlines() if line.startswith("LOAD_RESULT:")]
    return json.loads(lines[-1]) if lines else None


async def stream_reader(reader, chunked):
    if not chunked:
        while data := await reader.read(65536):
            yield data
        return
    while True:
        line = await reader.readline()
        if not line:
            return
        size = int(line.split(b";", 1)[0].strip(), 16)
        if size == 0:
            return
        data = await reader.readexactly(size)
        await reader.readexactly(2)
        yield data


class AdmissionRejected(Exception):
    def __init__(self, status, retry_after):
        self.status, self.retry_after = status, retry_after
        super().__init__("Stream admission rejected")


class StreamClosed(Exception):
    pass


async def connect(target, session, cursor=0):
    reader, writer = await asyncio.wait_for(asyncio.open_connection(target.hostname, target.port or 443,
        ssl=ssl.create_default_context() if target.scheme == "https" else None), 15)
    request = (f"GET /api/events/?cursor={cursor} HTTP/1.1\r\nHost: {target.netloc}\r\n"
               f"Origin: {target.scheme}://{target.netloc}\r\nAccept: text/event-stream\r\n"
               f"Cookie: sessionid={session}\r\nConnection: keep-alive\r\n\r\n")
    try:
        writer.write(request.encode("ascii")); await writer.drain()
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 30)
        status = int(head.split(b"\r\n", 1)[0].split()[1])
        if status != 200:
            retry_after = 5
            for line in head.lower().split(b"\r\n"):
                if line.startswith(b"retry-after:"):
                    try: retry_after = min(120, max(1, int(line.split(b":", 1)[1].strip())))
                    except ValueError: pass
            raise AdmissionRejected(status, retry_after)
        return reader, writer, b"transfer-encoding: chunked" in head.lower()
    except BaseException:
        writer.close()
        try: await writer.wait_closed()
        except (OSError, asyncio.CancelledError): pass
        raise


class Client:
    def __init__(self, target, session):
        self.target, self.session = target, session
        self.ready, self.changed = asyncio.Event(), asyncio.Event()
        self.revision, self.changes, self.heartbeats = 0, 0, 0
        self.writer = None
        self.error = None
        self.admission_statuses = Counter()
        self.connected = False
        self.reconnects = 0

    async def run(self):
        self.error = None
        for attempt in range(6):
            try:
                return await self.once()
            except AdmissionRejected as exc:
                self.admission_statuses[str(exc.status)] += 1
                if exc.status not in {429, 503} or attempt == 5:
                    self.error = f"Admission{exc.status}"; break
                # Match the production reconnect policy and retain throttle evidence.
                delay = max(exc.retry_after, random.uniform(15, 30) * min(4, 2 ** attempt))
                await asyncio.sleep(delay)
            except StreamClosed:
                self.reconnects += 1
                if attempt == 5:
                    self.error = "StreamClosed"; break
                await asyncio.sleep(random.uniform(15, 30) * min(4, 2 ** attempt))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.error = type(exc).__name__; break
        self.ready.set(); self.changed.set()

    async def once(self):
        try:
            reader, self.writer, chunked = await connect(self.target, self.session, self.revision)
            buffer = b""
            async for data in stream_reader(reader, chunked):
                buffer += data
                if len(buffer) > 262144:
                    raise RuntimeError("Unbounded event frame")
                while b"\n\n" in buffer:
                    frame, buffer = buffer.split(b"\n\n", 1)
                    if frame.startswith(b":"):
                        self.heartbeats += 1
                        continue
                    event, payload = "message", {}
                    for line in frame.decode().splitlines():
                        if line.startswith("event:"): event = line[6:].strip()
                        if line.startswith("data:"): payload = json.loads(line[5:].strip())
                    self.revision = max(self.revision, payload.get("revision", 0))
                    if event == "ready": self.connected = True; self.ready.set()
                    if event == "change":
                        self.changes += 1; self.changed.set()
                    if event == "session-ended": raise RuntimeError("Unexpected expired synthetic session")
            raise StreamClosed()
        finally:
            self.connected = False
            if self.writer:
                self.writer.close()
                await self.writer.wait_closed()


async def probe(target, session):
    start = time.perf_counter()
    reader, writer = await asyncio.open_connection(target.hostname, target.port or 443,
        ssl=ssl.create_default_context() if target.scheme == "https" else None)
    writer.write((f"GET /api/jobs/ HTTP/1.1\r\nHost: {target.netloc}\r\nCookie: sessionid={session}\r\nConnection: close\r\n\r\n").encode())
    await writer.drain()
    response = await asyncio.wait_for(reader.read(), 10)
    writer.close(); await writer.wait_closed()
    if response.split(b"\r\n", 1)[0].split()[1] != b"200": raise RuntimeError("Ordinary API probe failed")
    return (time.perf_counter() - start) * 1000


def percentile(samples, fraction):
    return sorted(samples)[min(len(samples) - 1, int(len(samples) * fraction))]


async def stable_connections(clients, timeout=120):
    """Ready once is insufficient: require every socket to remain live for2seconds."""
    end = time.monotonic() + timeout
    stable_since = None
    while time.monotonic() < end:
        if any(client.error for client in clients):
            raise RuntimeError("A stream exhausted recovery attempts")
        if all(client.connected for client in clients):
            stable_since = stable_since or time.monotonic()
            if time.monotonic() - stable_since >= 2: return
        else:
            stable_since = None
        await asyncio.sleep(.1)
    raise TimeoutError("The full connection population did not stabilize")


async def exercise(args, fixture):
    target = urlsplit(args.url)
    clients = [Client(target, item["session"]) for item in fixture]
    tasks = []
    opened = time.perf_counter()
    for index in range(0, len(clients), args.ramp_batch):
        tasks.extend(asyncio.create_task(client.run()) for client in clients[index:index + args.ramp_batch])
        await asyncio.sleep(args.ramp_delay)
    try:
        await asyncio.wait_for(asyncio.gather(*(client.ready.wait() for client in clients)), 90)
        failures = sum(client.error is not None for client in clients)
        if failures: raise RuntimeError(f"{failures} stream admissions failed")
        await stable_connections(clients)
        connect_seconds = time.perf_counter() - opened
        # Each awaited pause is an actual benchmark interval, not a retry delay.
        samples = []
        for _ in range(args.seconds):
            samples.append(await probe(target, fixture[0]["session"]))
            await asyncio.sleep(1)
        fanout_restart = None
        if args.restart_fanout:
            restart_start = time.perf_counter()
            result = await asyncio.to_thread(subprocess.run,
                ["docker", "compose", "restart", "fanout", "fanout-b"], cwd=ROOT,
                capture_output=True, text=True, timeout=60)
            if result.returncode: raise RuntimeError("Local fan-out restart failed")
            await stable_connections(clients)
            fanout_restart = {"recovered": True, "seconds": round(time.perf_counter() - restart_start, 3)}
        burst_seconds = None
        if not args.skip_burst:
            burst_start = time.perf_counter()
            await asyncio.to_thread(shell, "from matching.events import record_change\n" +
                f"for owner in {repr([item['owner'] for item in fixture])}: record_change(owner, 'workspace.changed')\nprint('LOAD_RESULT:'+__import__('json').dumps(True))")
            await asyncio.wait_for(asyncio.gather(*(client.changed.wait() for client in clients)), args.delivery_timeout)
            burst_seconds = time.perf_counter() - burst_start
        before = [client.changes for client in clients]
        if not args.skip_burst and (any(client.error for client in clients) or not all(count >= 1 for count in before)):
            raise RuntimeError("The completion burst did not reach every owner")
        # Re-open all sockets with the last cursor, proving reconnect admission as a burst.
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        tasks.clear()
        reconnect_start = time.perf_counter()
        for client in clients: client.ready.clear()
        tasks.extend(asyncio.create_task(client.run()) for client in clients)
        await asyncio.wait_for(asyncio.gather(*(client.ready.wait() for client in clients)), 90)
        failures = sum(client.error is not None for client in clients)
        if failures: raise RuntimeError(f"{failures} reconnects failed")
        await stable_connections(clients)
        reconnect_seconds = time.perf_counter() - reconnect_start
        errors = [client.error for client in clients if client.error]
        admissions = Counter()
        for client in clients: admissions.update(client.admission_statuses)
        api_p95 = percentile(samples, .95)
        passed = not errors and api_p95 <= args.api_p95_ms and (burst_seconds is None or burst_seconds <= args.delivery_timeout)
        return {"passed": passed, "connections": len(clients), "idle_seconds": args.seconds,
                "connect_seconds": round(connect_seconds, 3), "reconnect_seconds": round(reconnect_seconds, 3),
                "api_ms": {"p50": round(statistics.median(samples), 2), "p95": round(api_p95, 2), "max": round(max(samples), 2)},
                "burst": {"owners": len(clients), "executed": not args.skip_burst,
                          "observed_by_all": all(count >= 1 for count in before) if not args.skip_burst else None,
                          "seconds_including_transaction_generation": round(burst_seconds, 3) if burst_seconds is not None else None},
                "errors": errors, "heartbeats": sum(client.heartbeats for client in clients),
                "admission_throttles_and_retries": dict(admissions),
                "unexpected_stream_closes_recovered": sum(client.reconnects for client in clients),
                "connection_population_stability_seconds": 2,
                "fanout_restart": fanout_restart,
                "thresholds": {"api_p95_ms": args.api_p95_ms, "all_owner_burst_seconds": args.delivery_timeout},
                "scope": "authenticated SSE/proxy/fan-out/reconnect; excludes document processing and any unexecuted target-scale claim"}
    finally:
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connections", type=int, default=500)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--url", default="http://127.0.0.1:8088")
    parser.add_argument("--ramp-batch", type=int, default=25)
    parser.add_argument("--ramp-delay", type=float, default=.1)
    parser.add_argument("--delivery-timeout", type=float, default=60)
    parser.add_argument("--api-p95-ms", type=float, default=1000)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--fixture-file", type=Path, help="Owner-only JSON: schemaVersion=1, origin, sessions[]. Used unchanged; never logged.")
    parser.add_argument("--allow-remote", action="store_true", help="Explicitly opt into an authorized HTTPS staging origin; requires fixtures and --skip-burst. No cloud provisioning.")
    parser.add_argument("--skip-burst", action="store_true", help="Do not create local database events; remote generators observe operator-generated events.")
    parser.add_argument("--restart-fanout", action="store_true", help="Restart both local disposable wake shards during the run; requires local seeded mode. Preserves database/source volumes.")
    args = parser.parse_args()
    target = urlsplit(args.url)
    local = target.hostname in {"localhost", "127.0.0.1"} and target.scheme == "http" and bool(target.port)
    if target.username or target.password or target.query or target.fragment or target.path not in {"", "/"}:
        parser.error("Use an origin only, without credentials, paths, query or fragment.")
    if not local and not (args.allow_remote and target.scheme == "https" and target.hostname and args.fixture_file and args.skip_burst):
        parser.error("Remote execution requires an authorized HTTPS origin, --allow-remote, --fixture-file and --skip-burst.")
    if args.restart_fanout and (not local or args.fixture_file):
        parser.error("Fan-out restart is restricted to local seeded fixtures.")
    maximum = 20000 if args.fixture_file else 2000
    if not 1 <= args.connections <= maximum or not 1 <= args.seconds <= 300 or not 1 <= args.ramp_batch <= 100:
        parser.error("Use 1–2000 local seeded connections (up to20,000 with fixtures), 1–300 seconds and 1–100 ramp batch.")
    if args.ramp_delay < .01 or args.delivery_timeout <= 0 or args.api_p95_ms <= 0:
        parser.error("Use positive time/latency limits and at least10ms ramp delay.")
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    desired = max(soft, args.connections * 2 + 256)
    resource.setrlimit(resource.RLIMIT_NOFILE, (desired if hard == resource.RLIM_INFINITY else min(hard, desired), hard))
    prefix = "sse-load-" + uuid.uuid4().hex[:12]
    fixture = None
    try:
        if args.fixture_file:
            file = args.fixture_file
            if file.is_symlink() or not file.is_file() or file.stat().st_mode & 0o077 or file.stat().st_uid != os.getuid():
                parser.error("Fixtures must be a regular owner-only file owned by this process's user.")
            data = json.loads(file.read_text())
            if data.get("schemaVersion") != 1 or data.get("origin") != f"{target.scheme}://{target.netloc}":
                parser.error("Fixture schema and exact authorized origin must match.")
            fixture = data.get("sessions", [])[:args.connections]
            if len(fixture) != args.connections or any(not isinstance(row, dict) or not re.fullmatch(r"[a-z0-9]{32}", str(row.get("session", ""))) for row in fixture):
                parser.error("Need one valid Django session per connection; credentials are not shown.")
            if not args.skip_burst:
                parser.error("External fixture mode requires --skip-burst; it never mutates fixture owners.")
        else:
            fixture = shell("from django.contrib.auth import get_user_model, HASH_SESSION_KEY, BACKEND_SESSION_KEY, SESSION_KEY\n"
            "from django.contrib.sessions.backends.db import SessionStore\nimport json\nrows=[]\n" +
            f"for i in range({args.connections}):\n u=get_user_model().objects.create_user(username='{prefix}-'+str(i))\n s=SessionStore()\n s[SESSION_KEY]=str(u.pk)\n s[BACKEND_SESSION_KEY]='django.contrib.auth.backends.ModelBackend'\n s[HASH_SESSION_KEY]=u.get_session_auth_hash()\n s.save()\n rows.append({{'owner':u.pk,'session':s.session_key}})\n" +
            "print('LOAD_RESULT:'+json.dumps(rows))")
        try:
            report = asyncio.run(exercise(args, fixture))
        except Exception as exc:
            report = {"passed": False, "connections_requested": args.connections,
                      "error_type": type(exc).__name__,
                      "scope": "Interrupted or failed delivery experiment; not capacity evidence"}
        report["source_revision"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        report["working_tree_modified"] = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
        report["source_sha256"] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in ("backend/event_gateway.py", "backend/matching/events.py",
                         "backend/matching/views.py", "compose.yaml", "frontend/nginx.conf",
                         "scripts/load_delivery.py")}
        report["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2) + "\n")
            args.report.chmod(0o600)
        print(json.dumps(report, indent=2))
        return 0 if report["passed"] else 1
    finally:
        # Scope cleanup strictly to owners created by this invocation.
        sessions = [item["session"] for item in fixture] if fixture else []
        if not args.fixture_file:
            shell("from django.contrib.auth import get_user_model\nfrom django.contrib.sessions.models import Session\n" +
              f"Session.objects.filter(session_key__in={repr(sessions)}).delete()\n" +
              f"get_user_model().objects.filter(username__startswith='{prefix}-').delete()\nprint('LOAD_RESULT:true')")


if __name__ == "__main__":
    raise SystemExit(main())
