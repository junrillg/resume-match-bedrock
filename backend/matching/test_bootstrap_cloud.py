import os
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from .management.commands.bootstrap_cloud_db import Command


DATABASE = {"default": {"ENGINE": "django.db.backends.postgresql", "HOST": "db.example.invalid", "PORT": "5432", "NAME": "resume_match", "USER": "resume_app", "PASSWORD": "app-secret-" * 4, "OPTIONS": {"sslmode": "verify-full", "sslrootcert": "/app/certs/rds-global-bundle.pem"}}}
ENVIRONMENT = {"RDS_MASTER_USERNAME": "admin", "RDS_MASTER_PASSWORD": "master-secret-" * 3, "CLOUD_REVIEWER_USERNAME": "reviewer", "CLOUD_REVIEWER_PASSWORD": "reviewer-secret-" * 3}


@override_settings(DEBUG=False, DATABASES=DATABASE)
@patch.dict(os.environ, ENVIRONMENT)
class CloudBootstrapTests(SimpleTestCase):
    def run_bootstrap(self, *, existing_role=None, membership=None, existing_user=False, failure=None):
        output = StringIO()
        with patch("matching.management.commands.bootstrap_cloud_db.psycopg.connect") as connect, patch("matching.management.commands.bootstrap_cloud_db.call_command") as migrate, patch("matching.management.commands.bootstrap_cloud_db.connections.close_all"), patch("matching.management.commands.bootstrap_cloud_db.get_user_model") as model:
            cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
            cursor.fetchone.side_effect = [existing_role, membership]
            if failure:
                connect.side_effect = failure
            model.return_value.objects.filter.return_value.exists.return_value = existing_user
            command = Command(stdout=output)
            command.handle()
            return connect, cursor, migrate, model, output.getvalue()

    def test_creates_restricted_role_then_migrates_as_application(self):
        connect, cursor, migrate, model, output = self.run_bootstrap()
        self.assertEqual(connect.call_args.kwargs["sslmode"], "verify-full")
        self.assertEqual(connect.call_args.kwargs["user"], "admin")
        self.assertEqual(cursor.execute.call_args_list[2].args[1], (DATABASE["default"]["PASSWORD"],))
        statement = str(cursor.execute.call_args_list[2].args[0])
        self.assertIn("NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS", statement)
        self.assertNotIn(DATABASE["default"]["PASSWORD"], statement)
        migrate.assert_called_once()
        model.return_value.objects.create_user.assert_called_once_with(username="reviewer", password=ENVIRONMENT["CLOUD_REVIEWER_PASSWORD"], is_staff=False, is_superuser=False)
        self.assertEqual(output, "Cloud database and initial reviewer ready.\n")

    def test_existing_reviewer_password_is_not_reset(self):
        _, cursor, _, model, _ = self.run_bootstrap(existing_role=(False,) * 5, existing_user=True)
        self.assertIn("ALTER ROLE", str(cursor.execute.call_args_list[2].args[0]))
        self.assertNotIn("NOSUPERUSER", str(cursor.execute.call_args_list[2].args[0]))
        model.return_value.objects.create_user.assert_not_called()

    def test_rejects_existing_elevated_role_or_membership(self):
        for kwargs in [{"existing_role": (True, False, False, False, False)}, {"existing_role": (False,) * 5, "membership": (1,)}]:
            with self.subTest(kwargs=kwargs), self.assertRaisesMessage(CommandError, "Cloud bootstrap failed"):
                self.run_bootstrap(**kwargs)

    def test_exception_never_exposes_secret(self):
        with self.assertRaises(CommandError) as error:
            self.run_bootstrap(failure=RuntimeError(ENVIRONMENT["RDS_MASTER_PASSWORD"]))
        self.assertNotIn("master-secret", str(error.exception))
        self.assertTrue(error.exception.__suppress_context__)

    @override_settings(DEBUG=True)
    def test_rejects_local_execution_before_connection(self):
        with patch("matching.management.commands.bootstrap_cloud_db.psycopg.connect") as connect, self.assertRaisesMessage(CommandError, "requires production settings"):
            Command().handle()
        connect.assert_not_called()
