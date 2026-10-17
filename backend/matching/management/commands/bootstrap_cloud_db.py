"""One-off cloud bootstrap; the normal application never receives the master secret."""
import os
from io import StringIO

import psycopg
from psycopg import ClientCursor, sql
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections


class Command(BaseCommand):
    help = "Create the restricted cloud database role, migrate and provision the first reviewer."
    requires_system_checks = []

    def handle(self, *args, **options):
        database = settings.DATABASES["default"]
        master_user = os.getenv("RDS_MASTER_USERNAME", "")
        master_password = os.getenv("RDS_MASTER_PASSWORD", "")
        username = os.getenv("CLOUD_REVIEWER_USERNAME", "")
        password = os.getenv("CLOUD_REVIEWER_PASSWORD", "")
        if (settings.DEBUG or database["ENGINE"] != "django.db.backends.postgresql"
                or database.get("USER") != "resume_app"
                or database.get("OPTIONS", {}).get("sslmode") != "verify-full"
                or not database.get("OPTIONS", {}).get("sslrootcert")
                or not master_user or not master_password or master_user == database["USER"]
                or not username or len(username) > 150 or len(password) < 24
                or len(database.get("PASSWORD", "")) < 24):
            raise CommandError("Cloud bootstrap requires production settings, verified database TLS and bootstrap-only credentials.")
        try:
            with psycopg.connect(host=database["HOST"], port=database.get("PORT", "5432"),
                                  dbname=database["NAME"], user=master_user, password=master_password,
                                  sslmode="verify-full", sslrootcert=database["OPTIONS"]["sslrootcert"],
                                  connect_timeout=10, cursor_factory=ClientCursor) as admin:
                with admin.cursor() as cursor:
                    cursor.execute("SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname = %s", (database["USER"],))
                    existing = cursor.fetchone()
                    if existing is not None and any(existing):
                        raise ValueError("Unexpected elevated application role")
                    cursor.execute("SELECT 1 FROM pg_auth_members WHERE member = (SELECT oid FROM pg_roles WHERE rolname = %s)", (database["USER"],))
                    if cursor.fetchone() is not None:
                        raise ValueError("Unexpected application role membership")
                    action = "ALTER" if existing is not None else "CREATE"
                    # RDS administrators cannot ALTER the SUPERUSER flag, even to false.
                    attributes = "LOGIN NOINHERIT" if existing is not None else "LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                    cursor.execute(sql.SQL(action + " ROLE {} " + attributes + " PASSWORD %s").format(sql.Identifier(database["USER"])), (database["PASSWORD"],))
                    cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database["NAME"]), sql.Identifier(database["USER"])))
                    cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
                    cursor.execute(sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(sql.Identifier(database["USER"])))
            # Migrations and account creation use only the application's ordinary connection.
            connections.close_all()
            call_command("migrate", interactive=False, verbosity=0, stdout=StringIO(), stderr=StringIO())
            users = get_user_model().objects
            if not users.filter(username=username).exists():
                users.create_user(username=username, password=password, is_staff=False, is_superuser=False)
        except Exception:
            # Database and validation exceptions may contain passwords or connection strings.
            raise CommandError("Cloud bootstrap failed; inspect database availability and configured permissions privately.") from None
        self.stdout.write("Cloud database and initial reviewer ready.")
