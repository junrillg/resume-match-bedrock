"""Durable owner revisions; fan-out is a disposable wake, never the source of truth."""
import json
from datetime import timedelta
from functools import partial

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import StreamEvent, StreamState
from .telemetry import emit

KINDS = {"job.changed", "document.changed", "inbox.changed", "workspace.changed"}


def lock_stream(owner_id):
    """First lock in every owner mutation transaction, before document/job rows."""
    if owner_id is None:
        return None
    StreamState.objects.get_or_create(owner_id=owner_id)
    return StreamState.objects.select_for_update().get(owner_id=owner_id)


def record_change(owner_id, kind, *, job_id=None, document_id=None):
    if kind not in KINDS:
        raise ValueError("Unsupported stream change")
    with transaction.atomic():
        state = lock_stream(owner_id)
        state.revision += 1
        state.save(update_fields=["revision"])
        StreamEvent.objects.create(owner_id=owner_id, revision=state.revision, kind=kind,
                                   job_id=job_id, document_id=document_id, available_at=timezone.now())
        transaction.on_commit(partial(emit, "delivery.persisted", revision=state.revision,
                                     job_id=job_id, document_id=document_id))
    return state.revision


def event_payload(event):
    result = {"revision": event.revision, "kind": event.kind}
    for field in ("job_id", "document_id"):
        if getattr(event, field):
            result[field] = str(getattr(event, field))
    return result


def replay(owner_id, cursor):
    state = StreamState.objects.filter(owner_id=owner_id).first()
    revision, floor = (state.revision, state.floor_revision) if state else (0, 0)
    if cursor is None or cursor < floor or cursor > revision:
        return {"reset": cursor is not None, "revision": revision, "events": []}
    expected = revision - cursor
    if expected > settings.STREAM_REPLAY_LIMIT:
        return {"reset": True, "revision": revision, "events": []}
    events = list(StreamEvent.objects.filter(owner_id=owner_id, revision__gt=cursor, revision__lte=revision).order_by("revision")[:settings.STREAM_REPLAY_LIMIT + 1])
    # Pruning may commit between READ COMMITTED queries. Contiguous revisions
    # prove coverage; a gap must reset, never advance past unseen changes.
    if len(events) != expected:
        return {"reset": True, "revision": revision, "events": []}
    return {"reset": False, "revision": revision, "events": [event_payload(item) for item in events],
            "delivery_lag_ms": max(0, int((timezone.now() - events[0].created_at).total_seconds() * 1000)) if events else 0}


def redis_options(shard=0):
    return {"host": settings.STREAM_REDIS_HOSTS[shard], "port": settings.STREAM_REDIS_PORT,
            "username": settings.STREAM_REDIS_USERNAME, "password": settings.STREAM_REDIS_PASSWORD or None,
            "ssl": settings.STREAM_REDIS_TLS, "socket_connect_timeout": 2, "socket_timeout": 3,
            "decode_responses": True, **({"ssl_cert_reqs": "required"} if settings.STREAM_REDIS_TLS else {})}


def relay_events(client, limit=100):
    """Skip locked intents allow multiple relays; failed publishes back off durably."""
    sent = 0
    for _ in range(limit):
        with transaction.atomic():
            event = StreamEvent.objects.select_for_update(skip_locked=True).filter(
                published_at__isnull=True, available_at__lte=timezone.now()).order_by("available_at", "id").first()
            if event is None:
                break
            try:
                client.publish(f"owner:{event.owner_id}", str(event.revision))
            except Exception:
                event.attempts = min(16, event.attempts + 1)
                event.available_at = timezone.now() + timedelta(seconds=min(30, 2 ** event.attempts))
                event.save(update_fields=["attempts", "available_at"])
                transaction.on_commit(partial(emit, "delivery.publish_failed", stage="event-relay", job_id=event.job_id, document_id=event.document_id, revision=event.revision))
                break
            event.published_at = timezone.now()
            event.save(update_fields=["published_at"])
            sent += 1
            transaction.on_commit(partial(emit, "delivery.published", stage="event-relay", job_id=event.job_id, document_id=event.document_id, revision=event.revision))
    return sent


def prune_events(limit=100):
    """Bound cleanup by owners and rows; floor + removal commit atomically.

    Unpublished intents are never pruned. Per-owner revisions remain monotonic.
    """
    cutoff = timezone.now() - timedelta(seconds=settings.STREAM_RETENTION_SECONDS)
    owners = list(StreamEvent.objects.filter(created_at__lt=cutoff, published_at__isnull=False)
                  .order_by("created_at").values_list("owner_id", flat=True)[:limit])
    for owner_id in set(owners):
        with transaction.atomic():
            state = StreamState.objects.select_for_update(skip_locked=True).filter(owner_id=owner_id).first()
            if state is None:
                continue
            old = list(StreamEvent.objects.filter(owner_id=owner_id, revision__gt=state.floor_revision,
                       created_at__lt=cutoff, published_at__isnull=False).order_by("revision")[:limit])
            if not old:
                continue
            # Never advance past an unpublished/young earlier revision.
            boundary = old[-1].revision
            gap = StreamEvent.objects.filter(owner_id=owner_id, revision__lte=boundary).filter(
                published_at__isnull=True).order_by("revision").first()
            if gap:
                boundary = gap.revision - 1
            state.floor_revision = max(state.floor_revision, boundary)
            state.save(update_fields=["floor_revision"])
            StreamEvent.objects.filter(owner_id=owner_id, revision__lte=boundary).delete()


class ShardedPublisher:
    """Independent shards, not Redis Cluster; the ordered map is deployment state."""
    def __init__(self):
        import redis
        self.clients = [redis.Redis(**redis_options(i), max_connections=4) for i in range(len(settings.STREAM_REDIS_HOSTS))]

    def publish(self, channel, revision):
        owner_id = int(channel.split(":", 1)[1])
        return self.clients[owner_id % len(self.clients)].publish(channel, revision)


def delivery_stats():
    pending = StreamEvent.objects.filter(published_at__isnull=True)
    count = pending[:10001].count()
    first = pending.order_by("created_at", "id").values_list("created_at", flat=True).first()
    return {"pending_events": min(count, 10000), "pending_capped": int(count > 10000),
            "oldest_pending_ms": max(0, int((timezone.now() - first).total_seconds() * 1000)) if first else 0}
