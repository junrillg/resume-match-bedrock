import asyncio
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.db import connection, connections, transaction
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.utils import timezone

from .events import event_payload, prune_events, record_change, relay_events, replay
from .jobs import claim_job, finish_job
from .models import CompletionNotification, Job, StreamEvent, StreamState
from .services import extract_evidence
from .test_jobs import make_job, REQUIREMENTS, SOURCE


@override_settings(OTEL_LOGS_ENDPOINT="")
class EventLedgerTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("ledger-owner")
        self.other = get_user_model().objects.create_user("ledger-other")

    def test_mutation_and_revision_roll_back_together(self):
        with self.assertRaises(RuntimeError), transaction.atomic():
            make_job(self.owner)
            raise RuntimeError("rollback")
        self.assertFalse(Job.objects.exists())
        self.assertFalse(StreamState.objects.exists())
        self.assertFalse(StreamEvent.objects.exists())

    def test_terminal_result_notice_and_events_are_one_transaction(self):
        job = make_job(self.owner)
        claim = claim_job(job.id)
        before = StreamState.objects.get(owner=self.owner).revision
        with patch("matching.notifications.CompletionNotification.objects.get_or_create", side_effect=RuntimeError("rollback")):
            with self.assertRaises(RuntimeError):
                finish_job(claim, evidence=extract_evidence(SOURCE, REQUIREMENTS))
        job.refresh_from_db()
        self.assertEqual(job.status, "running")
        self.assertFalse(CompletionNotification.objects.exists())
        self.assertEqual(StreamState.objects.get(owner=self.owner).revision, before)
        self.assertTrue(finish_job(claim, evidence=extract_evidence(SOURCE, REQUIREMENTS)))
        events = replay(self.owner.pk, before)["events"]
        self.assertEqual([e["kind"] for e in events], ["job.changed", "inbox.changed"])
        self.assertTrue(all(e["job_id"] == str(job.id) for e in events))
        self.assertNotIn("requirements", repr(events))

    def test_replay_is_owner_scoped_ordered_and_bounded(self):
        for i in range(3):
            record_change(self.owner.pk, "workspace.changed")
        record_change(self.other.pk, "workspace.changed")
        self.assertEqual([e["revision"] for e in replay(self.owner.pk, 1)["events"]], [2, 3])
        self.assertEqual(replay(self.other.pk, 0)["revision"], 1)
        self.assertTrue(replay(self.owner.pk, 999)["reset"])
        self.assertEqual(replay(self.owner.pk, None)["events"], [])
        with override_settings(STREAM_REPLAY_LIMIT=1):
            self.assertTrue(replay(self.owner.pk, 0)["reset"])

    def test_prune_between_state_and_event_reads_forces_reset(self):
        for _ in range(3):
            record_change(self.owner.pk, "workspace.changed")
        original_filter = StreamEvent.objects.filter
        def prune_then_read(*args, **kwargs):
            if "revision__gt" in kwargs:
                StreamState.objects.filter(owner=self.owner).update(floor_revision=3)
                original_filter(owner=self.owner).delete()
            return original_filter(*args, **kwargs)
        with patch("matching.events.StreamEvent.objects.filter", side_effect=prune_then_read):
            result = replay(self.owner.pk, 0)
        self.assertTrue(result["reset"])
        self.assertEqual(result["revision"], 3)
        self.assertEqual(result["events"], [])

    def test_publish_failure_remains_durable_and_duplicate_publish_is_safe(self):
        record_change(self.owner.pk, "workspace.changed")
        client = Mock()
        client.publish.side_effect = ConnectionError("never render private connection details")
        self.assertEqual(relay_events(client), 0)
        event = StreamEvent.objects.get()
        self.assertIsNone(event.published_at)
        self.assertEqual(event.attempts, 1)
        self.assertGreater(event.available_at, timezone.now())
        StreamEvent.objects.update(available_at=timezone.now())
        client.publish.side_effect = None
        self.assertEqual(relay_events(client), 1)
        self.assertEqual(relay_events(client), 0)
        self.assertEqual(replay(self.owner.pk, 0)["events"][0]["revision"], 1)

    def test_retention_reset_never_discards_unpublished_gap(self):
        for _ in range(3):
            record_change(self.owner.pk, "workspace.changed")
        StreamEvent.objects.update(created_at=timezone.now() - timedelta(days=2))
        StreamEvent.objects.exclude(revision=2).update(published_at=timezone.now())
        prune_events()
        self.assertEqual(StreamState.objects.get().floor_revision, 1)
        self.assertEqual(list(StreamEvent.objects.order_by("revision").values_list("revision", flat=True)), [2, 3])
        self.assertTrue(replay(self.owner.pk, 0)["reset"])
        self.assertFalse(replay(self.owner.pk, 1)["reset"])

    def test_deleted_job_emits_workspace_reconciliation_and_user_cascade_does_not_recreate_ledger(self):
        job = make_job(self.owner)
        cursor = StreamState.objects.get(owner=self.owner).revision
        job.delete()
        self.assertEqual(replay(self.owner.pk, cursor)["events"][0]["kind"], "workspace.changed")
        self.owner.delete()
        self.assertFalse(StreamState.objects.exists())
        self.assertFalse(StreamEvent.objects.exists())

    def test_logout_and_account_auth_changes_emit_revocation_wake(self):
        self.client.force_login(self.owner)
        self.client.post("/api/logout/")
        self.assertEqual(StreamEvent.objects.get().kind, "workspace.changed")
        self.owner.set_password("Different-synthetic-password")
        self.owner.save()
        self.assertEqual(StreamState.objects.get().revision, 2)
        self.owner.is_active = False
        self.owner.save()
        self.assertEqual(StreamState.objects.get().revision, 3)

    def test_account_switch_revokes_old_stream_session_and_wakes_previous_owner(self):
        from event_gateway import authenticate
        self.other.set_password("Different-synthetic-login-pass")
        self.other.save()
        self.client.force_login(self.owner)
        old_session = self.client.session.session_key
        response = self.client.post("/api/login/", data=json.dumps({"username":self.other.username,"password":"Different-synthetic-login-pass"}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(authenticate(old_session))
        self.assertEqual(authenticate(self.client.session.session_key).owner_id, self.other.pk)
        self.assertEqual(StreamEvent.objects.get(owner=self.owner).kind, "workspace.changed")

    def test_keyset_inbox_handles_new_insert_without_duplicate_page(self):
        notices = []
        for _ in range(101):
            job = make_job(self.owner, status=Job.Status.SUCCEEDED)
            notices.append(CompletionNotification.objects.create(owner=self.owner, job=job, status=job.status))
        self.client.force_login(self.owner)
        first = self.client.get("/api/notifications/?cursor=").json()
        self.assertEqual(len(first["notifications"]), 100)
        newer = make_job(self.owner, status=Job.Status.SUCCEEDED)
        CompletionNotification.objects.create(owner=self.owner, job=newer, status=newer.status)
        second = self.client.get("/api/notifications/", {"cursor": first["next_cursor"]}).json()
        self.assertEqual(len(second["notifications"]), 1)
        self.assertFalse(set(n["id"] for n in first["notifications"]) & set(n["id"] for n in second["notifications"]))
        self.assertIsNone(second["next_cursor"])
        self.assertEqual(self.client.get("/api/notifications/?cursor=forged").status_code, 400)


class RevisionConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_owner_revisions_are_unique_commit_ordered(self):
        owner = get_user_model().objects.create_user("revision-concurrency")
        StreamState.objects.create(owner=owner)
        barrier = threading.Barrier(4)
        def mutation():
            try:
                barrier.wait(5)
                return record_change(owner.pk, "workspace.changed")
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=4) as pool:
            revisions = [f.result(timeout=10) for f in [pool.submit(mutation) for _ in range(4)]]
        self.assertEqual(sorted(revisions), [1, 2, 3, 4])
        self.assertEqual([item["revision"] for item in replay(owner.pk, 0)["events"]], [1, 2, 3, 4])


class GatewayProtocolTests(SimpleTestCase):
    async def test_rejects_unauthorized_host_origin_and_cursor_before_stream(self):
        from event_gateway import Gateway
        gateway = Gateway()
        async def start():
            pass
        gateway.start = start
        async def status(headers, query=b""):
            sent = []
            async def send(event):
                sent.append(event)
            async def receive():
                return {"type": "http.disconnect"}
            await gateway({"type": "http", "path": "/api/events/", "method": "GET", "scheme": "http", "headers": headers, "query_string": query}, receive, send)
            return sent[0]["status"]
        with override_settings(ALLOWED_HOSTS=["localhost"], DEBUG=True):
            self.assertEqual(await status([(b"host", b"attacker.example")]), 403)
            self.assertEqual(await status([(b"host", b"localhost"), (b"origin", b"https://attacker.example")]), 403)
            self.assertEqual(await status([(b"host", b"localhost")]), 401)
            self.assertEqual(await status([(b"host", b"localhost")], b"cursor=bad"), 400)
        gateway.db.executor.shutdown(wait=False)
        await gateway.fanout.aclose()

    async def test_owner_wakes_coalesce_in_bounded_queue(self):
        from event_gateway import Fanout, OwnerSubscription
        owner = OwnerSubscription()
        queue = asyncio.Queue(maxsize=1)
        owner.listeners.add(queue)
        for _ in range(10000):
            Fanout.wake(owner)
        self.assertEqual(queue.qsize(), 1)

    def test_wire_frames_have_numeric_ids_and_no_source_payload(self):
        from event_gateway import frame
        self.assertEqual(frame("ready", {"revision": 7}, 7), b'id: 7\nevent: ready\ndata: {"revision":7}\n\n')


class ShardRoutingTests(SimpleTestCase):
    @override_settings(STREAM_REDIS_HOSTS=["shard-zero", "shard-one"])
    @patch("redis.Redis")
    def test_owner_routing_is_shared_by_publish_and_connection_admission(self, redis_client):
        from .events import ShardedPublisher
        publisher = ShardedPublisher()
        publisher.clients = [Mock(), Mock()]
        publisher.publish("owner:42", "1")
        publisher.clients[0].publish.assert_called_once_with("owner:42", "1")
        publisher.clients[1].publish.assert_not_called()
        publisher.publish("owner:43", "2")
        publisher.clients[1].publish.assert_called_once_with("owner:43", "2")
        from event_gateway import ShardedFanout
        fanout = ShardedFanout()
        self.assertIs(fanout.shard(42), fanout.shards[0])
        self.assertIs(fanout.shard(43), fanout.shards[1])
        self.assertIs(fanout.client_for_owner(42), fanout.shards[0].client)


class ExecutorBudgetTests(SimpleTestCase):
    @override_settings(STREAM_DB_WORKERS=1, STREAM_DB_QUEUE=1)
    async def test_cancelled_caller_keeps_slot_until_worker_actually_finishes(self):
        from event_gateway import DatabaseWork, Busy
        work = DatabaseWork()
        entered, release = threading.Event(), threading.Event()
        def blocked():
            entered.set()
            release.wait(3)
        first = asyncio.create_task(work.run(blocked))
        try:
            for _ in range(100):
                if entered.is_set():
                    break
                await asyncio.sleep(0.01)
            self.assertTrue(entered.is_set())
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first
            with self.assertRaises(Busy):
                await work.run(lambda: None)
            self.assertEqual(work.pending, 1)
        finally:
            release.set()
            for _ in range(100):
                if work.pending == 0:
                    break
                await asyncio.sleep(0.01)
            work.executor.shutdown(wait=False)
        self.assertEqual(work.pending, 0)

    @override_settings(STREAM_HEARTBEAT_SECONDS=0.01, STREAM_MAX_LIFETIME_SECONDS=1)
    async def test_idle_stream_heartbeats_do_not_query_database(self):
        from event_gateway import Gateway, Identity
        from unittest.mock import AsyncMock
        import time
        gateway = Gateway()
        gateway.start = AsyncMock()
        gateway.db.run = AsyncMock(side_effect=[Identity(7, "not-a-real-token", time.time()+60), {"reset":False,"revision":0,"events":[]}])
        subscription=__import__("event_gateway").OwnerSubscription()
        subscription.ready.set()
        gateway.fanout.shard = Mock(return_value=Mock(owners={7:subscription}))
        gateway.fanout.add = AsyncMock(return_value=asyncio.Queue(maxsize=1))
        gateway.fanout.remove = Mock()
        redis_client = Mock(eval=AsyncMock(return_value=1), zrem=AsyncMock())
        gateway.fanout.client_for_owner = Mock(return_value=redis_client)
        received = asyncio.Queue()
        sent = []
        beats = 0
        async def send(message):
            nonlocal beats
            sent.append(message)
            if message.get("body") == b": heartbeat\n\n":
                beats += 1
                if beats == 2:
                    await received.put({"type":"http.disconnect"})
        scope={"type":"http","path":"/api/events/","method":"GET","scheme":"http","query_string":b"",
               "headers":[(b"host",b"localhost"),(b"cookie",b"sessionid=not-a-real-token")]}
        with override_settings(DEBUG=True, ALLOWED_HOSTS=["localhost"]):
            await asyncio.wait_for(gateway(scope,received.get,send),2)
        self.assertEqual(beats,2)
        self.assertEqual(gateway.db.run.await_count,2)  # authentication and initial replay only
        gateway.db.executor.shutdown(wait=False)
        await gateway.fanout.aclose()


class OwnerLockOrderTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_document_delete_waits_for_claim_without_lock_inversion(self):
        from django.test import Client
        from .models import Document
        owner=get_user_model().objects.create_user("lock-order-owner")
        now=timezone.now()
        document=Document.objects.create(owner=owner,object_key="originals/"+uuid.uuid4().hex,filename="source.txt",
            content_type="text/plain",size_bytes=10,sha256="a"*64,status="pending",upload_deadline=now+timedelta(hours=1),expires_at=now+timedelta(days=90))
        job=make_job(owner,document=document)
        client=Client();client.force_login(owner)
        entered,release=threading.Event(),threading.Event()
        original=Job.save
        def paused(instance,*args,**kwargs):
            if instance.pk==job.pk and instance.status==Job.Status.RUNNING:
                entered.set()
                if not release.wait(5):
                    raise AssertionError("release timed out")
            return original(instance,*args,**kwargs)
        def thread(callback):
            try:return callback()
            finally:connections.close_all()
        with patch.object(Job,"save",paused),ThreadPoolExecutor(max_workers=2) as pool:
            claim=pool.submit(thread,lambda:claim_job(job.pk))
            try:
                self.assertTrue(entered.wait(5))
                deletion=pool.submit(thread,lambda:client.delete(f"/api/documents/{document.pk}/").status_code)
                self.assertFalse(threading.Event().wait(0.1) or deletion.done())
            finally:release.set()
            self.assertIsNotNone(claim.result(5))
            self.assertEqual(deletion.result(5),202)
        self.assertFalse(Job.objects.filter(pk=job.pk).exists())
        revisions=list(StreamEvent.objects.filter(owner=owner).order_by("revision").values_list("revision",flat=True))
        self.assertEqual(revisions,list(range(1,len(revisions)+1)))


class LiveBackpressureTests(SimpleTestCase):
    @override_settings(STREAM_DB_WORKERS=1, STREAM_DB_QUEUE=1)
    async def test_live_work_waits_without_enlarging_executor_queue(self):
        from event_gateway import DatabaseWork
        work=DatabaseWork()
        entered,release=threading.Event(),threading.Event()
        def blocked():
            entered.set()
            release.wait(3)
        first=asyncio.create_task(work.run(blocked))
        live=None
        try:
            for _ in range(100):
                if entered.is_set():break
                await asyncio.sleep(.01)
            self.assertTrue(entered.is_set())
            live=asyncio.create_task(work.run(lambda:"delivered",wait_timeout=1))
            await asyncio.sleep(.1)
            self.assertFalse(live.done())
            self.assertEqual(work.pending,1)
            self.assertEqual(work.waiting,1)
            release.set()
            await first
            self.assertEqual(await live,"delivered")
        finally:
            release.set()
            work.executor.shutdown(wait=False)

    async def test_resync_priority_survives_coalesced_change_wakes(self):
        from event_gateway import Fanout,OwnerSubscription
        owner=OwnerSubscription()
        queue=asyncio.Queue(maxsize=1);owner.listeners.add(queue)
        Fanout.wake(owner,"resync")
        Fanout.wake(owner,"change")
        self.assertEqual(queue.qsize(),1)
        self.assertEqual(queue.get_nowait(),"resync")


class SummaryReadTests(TestCase):
    def test_metadata_history_omits_evidence_and_keeps_authorized_result_detail(self):
        owner=get_user_model().objects.create_user("summary-owner")
        self.client.force_login(owner)
        job=make_job(owner)
        claim=claim_job(job.pk)
        self.assertTrue(finish_job(claim,evidence=extract_evidence(SOURCE,REQUIREMENTS)))
        summary=self.client.get("/api/jobs/?summary=true").json()["jobs"][0]
        self.assertEqual(set(summary["match"]),{"id","score"})
        self.assertNotIn("requirements",json.dumps(summary))
        self.assertNotIn(SOURCE,json.dumps(summary))
        detail=self.client.get(f"/api/jobs/{job.pk}/").json()
        self.assertEqual(len(detail["match"]["requirements"]),2)
        self.assertEqual(self.client.get("/api/matches/?legacy=true").json(),{"matches":[]})
        self.assertEqual(self.client.get("/api/jobs/?summary=false").status_code,400)
        self.assertEqual(self.client.get("/api/matches/?legacy=false").status_code,400)
