"""In-memory S3 boundary for unit tests; Compose checks exercise the real service."""
import io
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings


class StorageClientSafetyTests(SimpleTestCase):
    @override_settings(DEBUG=True, DOCUMENT_ENDPOINT="")
    def test_local_mode_requires_explicit_endpoint_before_constructing_sdk_client(self):
        from .documents import client, DocumentUnavailable

        with patch("matching.documents.boto3.client") as sdk_client:
            with self.assertRaises(DocumentUnavailable):
                client()
        sdk_client.assert_not_called()


class MemoryStorage:
    def __init__(self):
        self.objects = {}

    def put_object(self, *, Key, Body, **kwargs):
        self.objects[Key] = Body
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def get_object(self, *, Key, **kwargs):
        return {"Body": io.BytesIO(self.objects[Key])}

    def delete_object(self, *, Key, **kwargs):
        self.objects.pop(Key, None)
        return {}

    def get_object_tagging(self, **kwargs):
        return {"TagSet": [{"Key": "GuardDutyMalwareScanStatus", "Value": "NO_THREATS_FOUND"}]}


class StorageBoundaryMixin:
    def setUp(self):
        super().setUp()
        self.storage = MemoryStorage()
        storage_patch = patch("matching.documents.client", return_value=self.storage)
        scanner_patch = patch("matching.documents.scan_bytes")
        storage_patch.start()
        scanner_patch.start()
        self.addCleanup(storage_patch.stop)
        self.addCleanup(scanner_patch.stop)
