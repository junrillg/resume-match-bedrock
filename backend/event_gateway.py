"""Raw ASGI streaming tier. Django's HTTP handler is intentionally never entered.

All ORM work runs in one bounded shared executor and closes its DB connection.
One pub/sub connection per process multiplexes owner channels. Idle sockets use
only asyncio tasks/heartbeats; no dedicated threads, DB connections or DB polls.
"""
import asyncio
import contextlib
import json
import os
import random
import time
import uuid
import threading
import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlsplit

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY, get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db import connections
from django.utils import timezone
from django.utils.crypto import constant_time_compare
import redis.asyncio as redis

from matching.events import redis_options, replay
from matching.telemetry import emit


@dataclass(frozen=True)
class Identity:
    owner_id: int
    session_key: str
    expires_at: float


def authenticate(session_key):
    session = Session.objects.filter(session_key=session_key, expire_date__gt=timezone.now()).first()
    if session is None:
        return None
    data = session.get_decoded()
    if data.get(BACKEND_SESSION_KEY) not in settings.AUTHENTICATION_BACKENDS:
        return None
    user = get_user_model().objects.filter(pk=data.get(SESSION_KEY), is_active=True).first()
    if user is None or not constant_time_compare(data.get(HASH_SESSION_KEY, ""), user.get_session_auth_hash()):
        return None
    return Identity(user.pk, session_key, session.expire_date.timestamp())


class Busy(Exception):
    pass


class DatabaseWork:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=settings.STREAM_DB_WORKERS, thread_name_prefix="stream-db")
        self.slots = asyncio.Semaphore(settings.STREAM_DB_QUEUE)
        self.active = 0
        self.pending = 0
        self.waiting = 0

    async def run(self, function, *args, wait_timeout=0.05):
        self.waiting += 1
        try:
            try:
                await asyncio.wait_for(self.slots.acquire(), timeout=wait_timeout)
            except TimeoutError:
                raise Busy() from None
        finally:
            self.waiting -= 1
        self.pending += 1
        def execute():
            self.active += 1
            try:
                return function(*args)
            finally:
                connections.close_all()
                self.active -= 1
        future = asyncio.get_running_loop().run_in_executor(self.executor, execute)
        def completed(result):
            self.slots.release()
            self.pending -= 1
            if not result.cancelled():
                result.exception()  # retrieve failures even if the caller disconnected
        future.add_done_callback(completed)
        return await asyncio.shield(future)


class OwnerSubscription:
    def __init__(self):
        self.ready = asyncio.Event()
        self.generation = 0
        self.listeners = set()


class Fanout:
    """Coalesced wake queues; subscribe ACK is a replay precondition."""
    def __init__(self, shard=0):
        self.owners = {}
        self.commands = asyncio.Queue(maxsize=settings.STREAM_MAX_CONNECTIONS * 2)
        self.task = None
        self.client = redis.Redis(**redis_options(shard), max_connections=16)
        self.connected = False
        self.generation = 0

    async def add(self, owner_id):
        owner = self.owners.get(owner_id)
        if owner is None:
            owner = self.owners[owner_id] = OwnerSubscription()
            await self.commands.put(("subscribe", owner_id))
        queue = asyncio.Queue(maxsize=1)
        owner.listeners.add(queue)
        try:
            await asyncio.wait_for(owner.ready.wait(), timeout=5)
        except BaseException:
            self.remove(owner_id, queue)
            raise
        return queue

    def remove(self, owner_id, queue):
        owner = self.owners.get(owner_id)
        if owner:
            owner.listeners.discard(queue)
            if not owner.listeners:
                self.owners.pop(owner_id, None)
                with contextlib.suppress(asyncio.QueueFull):
                    self.commands.put_nowait(("unsubscribe", owner_id))

    @staticmethod
    def wake(owner, reason="change"):
        for queue in tuple(owner.listeners):
            # A reconnect resync must survive coalescing with ordinary changes.
            previous = queue.get_nowait() if not queue.empty() else None
            queue.put_nowait("resync" if "resync" in (reason, previous) else "change")

    async def run(self):
        client = self.client
        try:
            while True:
                try:
                    await client.ping()
                    async with client.pubsub() as pubsub:
                        self.generation += 1
                        # Always subscribe before reconciliation, including Redis reconnect.
                        for owner_id in list(self.owners):
                            await pubsub.subscribe(f"owner:{owner_id}")
                        self.connected = True
                        while True:
                            while not self.commands.empty():
                                command, owner_id = self.commands.get_nowait()
                                if command == "subscribe" and owner_id in self.owners:
                                    await pubsub.subscribe(f"owner:{owner_id}")
                                elif command == "unsubscribe" and owner_id not in self.owners:
                                    await pubsub.unsubscribe(f"owner:{owner_id}")
                            if not pubsub.subscribed:
                                await asyncio.sleep(0.05)
                                continue
                            message = await pubsub.get_message(ignore_subscribe_messages=False, timeout=0.1)
                            if message and str(message["channel"]).startswith("owner:"):
                                owner_id = int(str(message["channel"]).split(":", 1)[1])
                                owner = self.owners.get(owner_id)
                                if owner:
                                    if message["type"] == "subscribe":
                                        owner.generation = self.generation
                                        owner.ready.set()
                                        self.wake(owner, "resync")  # durable reconciliation closes outage gaps
                                    elif message["type"] == "message":
                                        self.wake(owner)
                            await asyncio.sleep(0)
                except (redis.RedisError, OSError, ValueError):
                    self.connected = False
                    for owner in list(self.owners.values()):
                        owner.ready.clear()
                    await asyncio.sleep(random.uniform(0.5, 1.5))
        finally:
            await client.aclose()


class ShardedFanout:
    def __init__(self):
        self.shards = [Fanout(i) for i in range(len(settings.STREAM_REDIS_HOSTS))]
        self.task = None

    def shard(self, owner_id):
        return self.shards[owner_id % len(self.shards)]

    def client_for_owner(self, owner_id):
        return self.shard(owner_id).client

    @property
    def owners(self):
        return {owner_id: owner for shard in self.shards for owner_id, owner in shard.owners.items()}

    @property
    def connected(self):
        return all(shard.connected for shard in self.shards)

    async def add(self, owner_id):
        return await self.shard(owner_id).add(owner_id)

    def remove(self, owner_id, queue):
        self.shard(owner_id).remove(owner_id, queue)

    async def run(self):
        await asyncio.gather(*(shard.run() for shard in self.shards))

    async def aclose(self):
        for shard in self.shards:
            await shard.client.aclose()


def frame(event, data, revision=None):
    prefix = f"id: {revision}\n" if revision is not None else ""
    return (prefix + f"event: {event}\ndata: " + json.dumps(data, separators=(",", ":")) + "\n\n").encode()


class Gateway:
    def __init__(self):
        self.db = DatabaseWork()
        self.fanout = ShardedFanout()
        self.count = 0
        self.owners = Counter()
        self.metrics = Counter()
        self.started = False

    async def start(self):
        if not self.started:
            self.fanout.task = asyncio.create_task(self.fanout.run())
            self.metrics_task = asyncio.create_task(self.metric_loop())
            self.started = True

    def snapshot(self):
        from django.db.backends.postgresql.base import DatabaseWrapper
        pool = DatabaseWrapper._connection_pools.get("default")
        return {"connections": self.count, "owners": len(self.owners), "db_active": self.db.active,
                "db_pending": self.db.pending, "db_waiting": self.db.waiting, "threads": threading.active_count(),
                "subscribed_owners": len(self.fanout.owners), "fanout_connected": self.fanout.connected,
                "fanout_shards": len(self.fanout.shards), "fanout_shard_connected": [shard.connected for shard in self.fanout.shards], "db_pool": pool.get_stats() if pool else {}, **self.metrics}

    async def metric_loop(self):
        while True:
            await asyncio.sleep(30)
            snapshot = self.snapshot()
            emit("stream.snapshot", stage="gateway", active_connections=self.count,
                 subscribed_owners=len(self.fanout.owners), db_active=self.db.active, db_pending=self.db.pending, db_waiting=self.db.waiting,
                 threads=snapshot["threads"], errors=self.metrics["stream_errors"], overload=self.metrics["overload"],
                 delivery_lag_ms=self.metrics["delivery_lag_ms"])
            if os.getenv("DELIVERY_CLOUD_METRICS", "false").lower() == "true":
                service = os.getenv("ECS_SERVICE_NAME", "event-gateway")[:255]
                logging.getLogger("matching.audit").info("%s", json.dumps({
                    "_aws": {"Timestamp": int(time.time()*1000), "CloudWatchMetrics": [{
                        "Namespace": "ResumeMatch/Delivery", "Dimensions": [["ServiceName"]],
                        "Metrics": [{"Name": "ConnectedStreams", "Unit": "Count"}]}]},
                    "ServiceName": service, "ConnectedStreams": self.count}))

    async def response(self, send, status, body=b"", extra=()):
        if status >= 400:
            self.metrics[f"http_{status}"] += 1
        headers = [(b"content-type", b"application/json"), *self.security_headers(), (b"cache-control", b"no-store"),
                   (b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"same-origin"),
                   (b"x-frame-options", b"DENY"), *extra]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    def security_headers():
        if not settings.DEBUG and settings.SECURE_HSTS_SECONDS:
            value = f"max-age={settings.SECURE_HSTS_SECONDS}"
            if settings.SECURE_HSTS_INCLUDE_SUBDOMAINS:
                value += "; includeSubDomains"
            if settings.SECURE_HSTS_PRELOAD:
                value += "; preload"
            return [(b"strict-transport-security", value.encode())]
        return []

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await self.start()
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    self.fanout.task.cancel()
                    self.metrics_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self.fanout.task
                    self.db.executor.shutdown(wait=False, cancel_futures=True)
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        if scope["type"] != "http":
            return
        await self.start()
        if scope["path"] == "/health/":
            return await self.response(send, 200 if any(shard.connected for shard in self.fanout.shards) else 503, b'{"status":"ready"}')
        if scope["path"] == "/metrics/":
            body = json.dumps(self.snapshot()).encode()
            return await self.response(send, 200, body)
        headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope["headers"]}
        if scope["path"] != "/api/events/" or scope["method"] != "GET":
            return await self.response(send, 404)
        # Trust forwarding only from the isolated nginx/ALB path, just like Django.
        scheme = scope.get("scheme", "http")
        if settings.SECURE_PROXY_SSL_HEADER and headers.get("x-forwarded-proto") == "https":
            scheme = "https"
        host = headers.get("host", "")
        from django.http.request import validate_host, split_domain_port
        domain, _ = split_domain_port(host)
        if not validate_host(domain, settings.ALLOWED_HOSTS) or (not settings.DEBUG and scheme != "https"):
            return await self.response(send, 403)
        try:
            if int(headers.get("content-length", "0")) != 0 or "transfer-encoding" in headers:
                return await self.response(send, 400)
        except ValueError:
            return await self.response(send, 400)
        origin = headers.get("origin")
        if origin and origin != f"{scheme}://{host}":
            return await self.response(send, 403)
        if headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
            return await self.response(send, 403)
        if self.count >= settings.STREAM_MAX_CONNECTIONS:
            self.metrics["overload"] += 1
            return await self.response(send, 503, extra=[(b"retry-after", b"5")])
        try:
            query = parse_qs(scope.get("query_string", b"").decode("ascii"), keep_blank_values=True, max_num_fields=2)
            if set(query) - {"cursor"} or any(len(values) != 1 for values in query.values()):
                raise ValueError()
            raw_cursor = headers.get("last-event-id") or query.get("cursor", [None])[0]
            if raw_cursor is not None and (not raw_cursor.isascii() or not raw_cursor.isdecimal() or len(raw_cursor) > 16):
                raise ValueError()
            cursor = int(raw_cursor) if raw_cursor is not None else None
            cookies = SimpleCookie()
            cookies.load(headers.get("cookie", ""))
            if settings.SESSION_COOKIE_NAME not in cookies:
                return await self.response(send, 401)
            session_key = cookies[settings.SESSION_COOKIE_NAME].value
            if len(session_key) > 64:
                raise ValueError()
        except (ValueError, UnicodeError, KeyError):
            return await self.response(send, 400)
        try:
            identity = await self.db.run(authenticate, session_key)
        except Busy:
            self.metrics["rejected_auth_budget"] += 1
            return await self.response(send, 503, extra=[(b"retry-after", b"5")])
        except Exception:
            self.metrics["rejected_auth_unavailable"] += 1
            return await self.response(send, 503, extra=[(b"retry-after", b"5")])
        if identity is None:
            return await self.response(send, 401)
        if self.owners[identity.owner_id] >= settings.STREAM_MAX_OWNER_CONNECTIONS or self.count >= settings.STREAM_MAX_CONNECTIONS:
            return await self.response(send, 429, extra=[(b"retry-after", b"10")])
        self.count += 1
        self.owners[identity.owner_id] += 1
        queue = None
        lease_token = uuid.uuid4().hex
        deadline = min(identity.expires_at, time.time() + random.uniform(0.8, 1.0) * settings.STREAM_MAX_LIFETIME_SECONDS)
        lease_key = f"owner-cap:{identity.owner_id}"
        leased = False
        disconnect = None
        started = False
        phase = "lease"
        async def write(body):
            # ASGI flow control plus deadline bounds slow consumers.
            await asyncio.wait_for(send({"type": "http.response.body", "body": body, "more_body": True}), timeout=5)
        try:
            # Subscribe ACK is the fan-out barrier. Acquire the fixed lease after
            # it, then discard only wakes preceding the initial DB snapshot.
            phase = "subscribe"
            queue = await self.fanout.add(identity.owner_id)
            phase = "lease"
            async def acquire_lease():
                return bool(await self.fanout.client_for_owner(identity.owner_id).eval("""
                    redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
                    if redis.call('ZSCORE', KEYS[1], ARGV[4]) then return 1 end
                    if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then return 0 end
                    redis.call('ZADD', KEYS[1], ARGV[3], ARGV[4])
                    redis.call('EXPIRE', KEYS[1], ARGV[5])
                    return 1
                """, 1, lease_key, time.time(), settings.STREAM_MAX_OWNER_CONNECTIONS,
                     deadline, lease_token, settings.STREAM_MAX_LIFETIME_SECONDS + 60))
            async def lease_barrier():
                nonlocal leased
                owner_subscription = self.fanout.shard(identity.owner_id).owners[identity.owner_id]
                while True:
                    await asyncio.wait_for(owner_subscription.ready.wait(), timeout=5)
                    generation = owner_subscription.generation
                    admitted = await acquire_lease()
                    leased = leased or admitted
                    if owner_subscription.ready.is_set() and owner_subscription.generation == generation:
                        return admitted
            admitted = await asyncio.wait_for(lease_barrier(), timeout=5)
            if not admitted:
                await self.response(send, 429, extra=[(b"retry-after", b"10")])
                return
            while not queue.empty():
                queue.get_nowait()
            phase = "initial_replay"
            initial = await self.db.run(replay, identity.owner_id, cursor)
            if time.time() >= identity.expires_at:
                return await self.response(send, 401)
            await send({"type": "http.response.start", "status": 200, "headers": [
                (b"content-type", b"text/event-stream"), *self.security_headers(), (b"cache-control", b"private, no-store"),
                (b"x-accel-buffering", b"no"), (b"x-content-type-options", b"nosniff"),
                (b"x-frame-options", b"DENY"), (b"referrer-policy", b"same-origin")]})
            started = True
            phase = "write"
            await write(b"retry: 3000\n\n")
            async def deliver(batch):
                nonlocal cursor
                if batch["reset"]:
                    self.metrics["resets"] += 1
                    await write(frame("reset", {"revision": batch["revision"]}, batch["revision"]))
                else:
                    for event in batch["events"]:
                        await write(frame("change", event, event["revision"]))
                        self.metrics["events"] += 1
                self.metrics["delivery_lag_ms"] = batch.get("delivery_lag_ms", 0)
                cursor = batch["revision"]
            await deliver(initial)
            await write(frame("ready", {"revision": cursor}, cursor))
            self.metrics["accepted"] += 1
            # Stagger rollover so fleet-wide deployments do not synchronize reconnects.
            async def disconnected():
                while (await receive())["type"] != "http.disconnect":
                    pass
            disconnect = asyncio.create_task(disconnected())
            while time.time() < deadline:
                wake = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait([wake, disconnect], timeout=min(settings.STREAM_HEARTBEAT_SECONDS, max(0, deadline-time.time())), return_when=asyncio.FIRST_COMPLETED)
                if disconnect in done:
                    wake.cancel()
                    break
                if wake in done:
                    if wake.result() == "resync":
                        # Volatile Redis leases can disappear on restart. Rejoin
                        # under the same global cap before delivering any events.
                        phase = "lease_resync"
                        if not await asyncio.wait_for(lease_barrier(), timeout=5):
                            self.metrics["closed_owner_limit"] += 1
                            break
                    phase = "live_replay"
                    batch = await self.db.run(replay, identity.owner_id, cursor, wait_timeout=5)
                    if batch["reset"] or any(event["kind"] == "workspace.changed" for event in batch["events"]):
                        current = await self.db.run(authenticate, session_key, wait_timeout=5)
                        if current is None:
                            await write(frame("session-ended", {}))
                            break
                    phase = "write"
                    if time.time() >= identity.expires_at:
                        await write(frame("session-ended", {}))
                        break
                    if time.time() >= deadline:
                        break
                    await deliver(batch)
                else:
                    wake.cancel()
                    await write(b": heartbeat\n\n")
            else:
                if identity.expires_at <= time.time():
                    await write(frame("session-ended", {}))
        except (Busy, TimeoutError, OSError):
            self.metrics["disconnected_overload"] += 1
            self.metrics[("closed_" if started else "rejected_") + phase] += 1
            if not started:
                await self.response(send, 503, extra=[(b"retry-after", b"5")])
        except asyncio.CancelledError:
            raise
        except Exception:
            self.metrics["stream_errors"] += 1
            if not started:
                await self.response(send, 503)
        finally:
            if leased:
                with contextlib.suppress(Exception):
                    await self.fanout.client_for_owner(identity.owner_id).zrem(lease_key, lease_token)
            if disconnect:
                disconnect.cancel()
            if queue:
                self.fanout.remove(identity.owner_id, queue)
            self.count -= 1
            self.owners[identity.owner_id] -= 1
            if not self.owners[identity.owner_id]:
                del self.owners[identity.owner_id]
            if started:
                with contextlib.suppress(Exception):
                    await send({"type": "http.response.body", "body": b"", "more_body": False})


application = Gateway()
