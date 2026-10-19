import threading
from unittest.mock import MagicMock, patch

from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from .jobs import publish_job, relay_once, run_job
from .models import OutboxEvent
from .test_jobs import make_job


class RelaySupplyTests(TestCase):
    def setUp(self): self.owner=get_user_model().objects.create_user("relay-supply")

    def test_batch_reuses_caller_producer_and_preserves_confirm_contract(self):
        jobs=[make_job(self.owner) for _ in range(3)]
        producer=MagicMock()
        with patch("matching.jobs.app.send_task") as send:
            self.assertEqual(relay_once(3,producer=producer,maintenance=False),3)
        self.assertEqual(send.call_count,3)
        for call in send.call_args_list:
            self.assertIs(call.kwargs["producer"],producer)
            self.assertEqual(call.kwargs["confirm_timeout"],3)
            self.assertTrue(call.kwargs["mandatory"])
            self.assertFalse(call.kwargs["retry"])

    def test_failed_reused_producer_escapes_for_reconnect_without_marking_sent(self):
        make_job(self.owner)
        with patch("matching.jobs.publish_job",side_effect=ConnectionError("synthetic")):
            with self.assertRaises(ConnectionError): relay_once(producer=MagicMock(),maintenance=False)
        self.assertFalse(OutboxEvent.objects.filter(sent_at__isnull=False).exists())
        with patch("matching.jobs.publish_job"):
            self.assertEqual(relay_once(producer=MagicMock(),maintenance=False),1)

    @override_settings(RELAY_MAINTENANCE_INTERVAL_SECONDS=.1,RELAY_BATCH_SIZE=2)
    def test_command_keeps_producer_across_productive_batches_and_cleanup_is_separate(self):
        from .management.commands.relay_jobs import Command
        from django.core.management import call_command
        producer=MagicMock()
        stop=RuntimeError("stop scoped command test")
        with patch("matching.management.commands.relay_jobs.app.producer_pool.acquire") as acquire, \
             patch("matching.management.commands.relay_jobs.threading.Thread") as thread, \
             patch("matching.management.commands.relay_jobs.sample_supply"), \
             patch("matching.management.commands.relay_jobs.connections.close_all"), \
             patch("matching.management.commands.relay_jobs.Path"), \
             patch("matching.management.commands.relay_jobs.relay_once",side_effect=[2,2,KeyboardInterrupt]) as relay:
            acquire.return_value.__enter__.return_value=producer
            with self.assertRaises(KeyboardInterrupt): Command().handle(once=False)
        self.assertEqual(acquire.call_count,1)
        self.assertEqual(relay.call_count,3)
        thread.assert_called_once()
        self.assertTrue(thread.call_args.kwargs["daemon"])
        for call in relay.call_args_list:
            self.assertIs(call.kwargs["producer"],producer)
            self.assertFalse(call.kwargs["maintenance"])

    @override_settings(RELAY_MAINTENANCE_INTERVAL_SECONDS=.1,RELAY_IDLE_DELAY_SECONDS=.05)
    def test_command_discards_failed_producer_and_reacquires_for_confirmed_replay(self):
        from .management.commands.relay_jobs import Command
        first,second=MagicMock(),MagicMock()
        contexts=[MagicMock(),MagicMock()]
        contexts[0].__enter__.return_value=first
        contexts[1].__enter__.return_value=second
        with patch("matching.management.commands.relay_jobs.app.producer_pool.acquire",side_effect=contexts) as acquire, \
             patch("matching.management.commands.relay_jobs.threading.Thread"), \
             patch("matching.management.commands.relay_jobs.sample_supply") as sample, \
             patch("matching.management.commands.relay_jobs.connections.close_all"), \
             patch("matching.management.commands.relay_jobs.Path"), \
             patch("matching.management.commands.relay_jobs.relay_once",side_effect=[ConnectionError("synthetic"),1,KeyboardInterrupt]):
            with self.assertRaises(KeyboardInterrupt): Command().handle(once=False)
        self.assertEqual(acquire.call_count,2)
        first.connection.close.assert_called_once()
        second.connection.ensure_connection.assert_called_once_with(max_retries=0)
        self.assertIn(False,[call.args[0] for call in sample.call_args_list])


class ExternalIOConnectionTests(TransactionTestCase):
    @override_settings(MATCH_PROVIDER="demo",OTEL_LOGS_ENDPOINT="")
    def test_provider_runs_after_database_connection_is_released(self):
        if connection.vendor != "postgresql": self.skipTest("SQLite memory connections deliberately ignore close")
        owner=get_user_model().objects.create_user("connection-release")
        job=make_job(owner)
        from .services import extract_evidence
        observed=[]
        def inspect(*args,**kwargs):
            observed.append((connection.in_atomic_block,connection.connection is None))
            return extract_evidence(*args,**kwargs)
        with patch("matching.jobs.extract_evidence",side_effect=inspect): run_job(job.id)
        self.assertEqual(observed,[(False,True)])
        job.refresh_from_db()
        self.assertEqual(job.status,"succeeded")


from .test_storage_support import StorageBoundaryMixin


class StorageIOConnectionTests(StorageBoundaryMixin, TransactionTestCase):
    @override_settings(MATCH_PROVIDER="demo", OTEL_LOGS_ENDPOINT="")
    def test_upload_worker_download_and_delete_release_database_before_external_io(self):
        import json
        import uuid
        if connection.vendor != "postgresql": self.skipTest("PostgreSQL connection lifecycle")
        owner=get_user_model().objects.create_user("storage-connection-release")
        self.client.force_login(owner)
        observed=[]
        def checked(name,wrapped):
            def invoke(*args,**kwargs):
                observed.append(name)
                self.assertFalse(connection.in_atomic_block)
                self.assertIsNone(connection.connection)
                return wrapped(*args,**kwargs)
            return invoke
        for name in ["put_object","get_object","delete_object"]:
            original=getattr(self.storage,name)
            setattr(self.storage,name,checked(name,original))
        with patch("matching.documents.scan_bytes",side_effect=checked("scan",lambda data:None)):
            accepted=self.client.post("/api/jobs/",{"job_title":"Synthetic role", "resume_text":"Synthetic Python developer", "requirements":json.dumps([{"skill":"Python","weight":1}])},HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
            self.assertEqual(accepted.status_code,202)
            run_job(accepted.json()["id"])
            from .models import Document
            document=Document.objects.get(owner=owner)
            response=self.client.get(f"/api/documents/{document.pk}/download/")
            self.assertEqual(response.status_code,200)
            response.close()
            self.assertEqual(self.client.delete(f"/api/documents/{document.pk}/").status_code,202)
            from .documents import reconcile_documents
            reconcile_documents(1)
        self.assertTrue({"put_object","get_object","scan","delete_object"}.issubset(observed))
        self.assertFalse(self.storage.objects)


class ConfirmedRelayMeasurement(TransactionTestCase):
    def test_local_confirmed_drain_measurement(self):
        import os
        import time
        from urllib.parse import urlsplit
        from django.conf import settings
        from config.celery import app
        if os.getenv("VERIFY_LIVE_BROKER") != "true": self.skipTest("Explicit local-broker integration opt-in")
        self.assertEqual(os.getenv("DJANGO_DEBUG"),"true")
        self.assertEqual(urlsplit(settings.CELERY_BROKER_URL).hostname,"broker")
        self.assertTrue(connection.settings_dict["NAME"].startswith("test_"))
        owner=get_user_model().objects.create_user("scoped-relay-measurement")
        for _ in range(200): make_job(owner)
        with app.producer_pool.acquire(block=True,timeout=3) as producer:
            producer.connection.ensure_connection(max_retries=0)
            started=time.monotonic()
            first=relay_once(100,producer=producer,maintenance=False)
            second=relay_once(100,producer=producer,maintenance=False)
            elapsed=time.monotonic()-started
        self.assertEqual(first+second,200)
        self.assertEqual(OutboxEvent.objects.filter(sent_at__isnull=False).count(),200)
        print("Confirmed local RabbitMQ drain: dispatches=200 reused_producer=1 batches=2 elapsed_seconds=%.3f throughput_per_second=%.2f; worker/provider throughput not measured" % (elapsed,200/elapsed))
        # Real workers see absent test-database IDs and acknowledge harmlessly;
        # this measures dispatch/confirm/SQL marking, not provider completion.
