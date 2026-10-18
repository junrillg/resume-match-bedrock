"""Viewer provisioning preserves accounts when privilege/configuration drift is detected."""
import unittest
from unittest.mock import MagicMock, patch

from init_viewers import provision_postgres, provision_rabbit


class ViewerAccountBoundaryTests(unittest.TestCase):
    @patch("init_viewers.rabbit_request")
    def test_existing_privileged_rabbit_user_is_preserved_and_refused(self, request):
        request.side_effect = [{"status": "ready"}, {"tags": ["administrator"]}]
        with self.assertRaisesRegex(RuntimeError, "unexpected privileges"):
            provision_rabbit()
        self.assertTrue(all(call.kwargs.get("method", "GET") == "GET" for call in request.call_args_list))

    @patch("init_viewers.rabbit_request")
    def test_existing_rabbit_write_permissions_are_preserved_and_refused(self, request):
        request.side_effect = [{"status": "ready"}, {"tags": ["monitoring"]},
                               {"configure": "^$", "read": "^$", "write": ".*"}]
        with self.assertRaisesRegex(RuntimeError, "permissions differ"):
            provision_rabbit()
        self.assertTrue(all(call.kwargs.get("method", "GET") == "GET" for call in request.call_args_list))

    @patch.dict("os.environ", {"POSTGRES_DB": "synthetic", "POSTGRES_USER": "synthetic",
                              "POSTGRES_PASSWORD": "synthetic"})
    @patch("init_viewers.psycopg.connect")
    def test_existing_privileged_database_role_is_preserved_and_refused(self, connect):
        admin = MagicMock()
        connect.return_value.__enter__.return_value = admin
        admin.execute.return_value.fetchone.return_value = (True, False, False, False, True, False, False)
        with self.assertRaisesRegex(RuntimeError, "unexpected privileges"):
            provision_postgres()
        self.assertEqual(admin.execute.call_count, 1)

    @patch.dict("os.environ", {"POSTGRES_DB": "synthetic", "POSTGRES_USER": "synthetic",
                              "POSTGRES_PASSWORD": "synthetic"})
    @patch("init_viewers.psycopg.connect")
    def test_database_role_membership_is_preserved_and_refused(self, connect):
        admin = MagicMock()
        connect.return_value.__enter__.return_value = admin
        admin.execute.return_value.fetchone.side_effect = [(False, False, False, False, True, False, False), (True,)]
        with self.assertRaisesRegex(RuntimeError, "role membership"):
            provision_postgres()
        self.assertEqual(admin.execute.call_count, 2)

    @patch.dict("os.environ", {"POSTGRES_DB": "synthetic", "POSTGRES_USER": "synthetic",
                              "POSTGRES_PASSWORD": "synthetic"})
    @patch("init_viewers.psycopg.connect")
    def test_database_privileges_outside_allowlist_are_preserved_and_refused(self, connect):
        admin = MagicMock()
        connect.return_value.__enter__.return_value = admin
        admin.execute.return_value.fetchone.side_effect = [(False, False, False, False, True, False, False), (False,), (True,)]
        with self.assertRaisesRegex(RuntimeError, "table allowlist"):
            provision_postgres()
        self.assertEqual(admin.execute.call_count, 3)
