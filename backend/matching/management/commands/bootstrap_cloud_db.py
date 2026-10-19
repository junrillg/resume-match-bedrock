"""Direct, one-off privileged bootstrap. Ordinary tasks never receive master credentials."""
import os
from contextlib import contextmanager
from copy import deepcopy
from io import StringIO

import psycopg
from psycopg import ClientCursor, sql
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

STREAM_TABLES = ("auth_user", "django_session", "matching_streamstate", "matching_streamevent")


def ensure_role(cursor, name, password, connection_limit, *, readonly=False):
    cursor.execute("SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname = %s", (name,))
    existing = cursor.fetchone()
    if existing is not None and any(existing):
        raise ValueError("Unexpected elevated database role")
    cursor.execute("SELECT 1 FROM pg_auth_members WHERE member = (SELECT oid FROM pg_roles WHERE rolname = %s)", (name,))
    if cursor.fetchone() is not None:
        raise ValueError("Unexpected database role membership")
    role = sql.Identifier(name)
    if existing is None:
        cursor.execute(sql.SQL("CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %s").format(role), (password,))
    else:
        # Never silently rotate an adopted credential on repeat bootstrap.
        cursor.execute(sql.SQL("ALTER ROLE {} LOGIN NOINHERIT").format(role))
    cursor.execute(sql.SQL("ALTER ROLE {} CONNECTION LIMIT {}").format(role, sql.Literal(connection_limit)))
    for setting, value in (("timezone", "UTC"), ("statement_timeout", "3000" if readonly else "10000"),
                           ("lock_timeout", "1000"), ("default_transaction_read_only", "on" if readonly else "off")):
        cursor.execute(sql.SQL("ALTER ROLE {} SET {} TO {}").format(role, sql.Identifier(setting), sql.Literal(value)))
    return existing is not None


def ensure_stream_permissions(cursor, database, *, owner=None):
    role = sql.Identifier("resume_stream")
    # Reject unexpected pre-existing access rather than masking a dangerous role.
    cursor.execute("""SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%%'
        AND ((c.relowner=(SELECT oid FROM pg_roles WHERE rolname='resume_stream'))
          OR (c.relkind IN ('r','p','v','m','f') AND (
            (NOT (n.nspname='public' AND c.relname=ANY(%s)) AND has_table_privilege('resume_stream',c.oid,'SELECT'))
            OR has_table_privilege('resume_stream',c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')))
          OR (c.relkind='S' AND has_sequence_privilege('resume_stream',c.oid,'USAGE,SELECT,UPDATE'))) LIMIT 1""", (list(STREAM_TABLES),))
    if cursor.fetchone() is not None:
        raise ValueError("Unexpected stream object privileges")
    cursor.execute("""SELECT 1 FROM pg_namespace WHERE nspname NOT LIKE 'pg_%'
        AND (nspowner=(SELECT oid FROM pg_roles WHERE rolname='resume_stream')
          OR has_schema_privilege('resume_stream',oid,'CREATE')) LIMIT 1""")
    if cursor.fetchone() is not None:
        raise ValueError("Unexpected stream schema privileges")
    cursor.execute("""SELECT 1 FROM pg_default_acl d, LATERAL aclexplode(d.defaclacl) a
        WHERE a.grantee IN (0,(SELECT oid FROM pg_roles WHERE rolname='resume_stream')) LIMIT 1""")
    if cursor.fetchone() is not None:
        raise ValueError("Unexpected future stream privileges")
    cursor.execute("SELECT 1 WHERE has_database_privilege('resume_stream',%s,'CREATE,TEMPORARY')", (database,))
    if cursor.fetchone() is not None:
        raise ValueError("Unexpected stream database privileges")
    cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database), role))
    if owner:
        cursor.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(owner)))
    try:
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
        cursor.execute(sql.SQL("GRANT SELECT ON {} TO {}").format(
            sql.SQL(", ").join(sql.Identifier("public", table) for table in STREAM_TABLES), role))
    finally:
        if owner:
            cursor.execute("RESET ROLE")


def ensure_runtime_owner(cursor, database, master_user):
    """Dedicated nonlogin owner; runtime identities can never SET ROLE to it."""
    cursor.execute("SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolcanlogin FROM pg_roles WHERE rolname='resume_owner'")
    existing = cursor.fetchone()
    if existing is not None and any(existing):
        raise ValueError("Unexpected privileged or login migration owner")
    cursor.execute("SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname='resume_owner')")
    if cursor.fetchone() is not None:
        raise ValueError("Unexpected migration owner membership")
    if existing is None:
        cursor.execute("CREATE ROLE resume_owner NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS")
    # PG17 non-superuser CREATEROLE creators have ADMIN, but SET defaults false.
    # Only the privileged bootstrap administrator receives explicit SET membership.
    cursor.execute(sql.SQL("GRANT resume_app, resume_owner TO {} WITH INHERIT FALSE, SET TRUE").format(sql.Identifier(master_user)))
    cursor.execute("""SELECT 1 FROM pg_database WHERE datdba=(SELECT oid FROM pg_roles WHERE rolname='resume_app')
        UNION ALL SELECT 1 FROM pg_namespace WHERE nspname <> 'public' AND nspowner=(SELECT oid FROM pg_roles WHERE rolname='resume_app')
        UNION ALL SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname NOT IN ('public','pg_toast') AND c.relowner=(SELECT oid FROM pg_roles WHERE rolname='resume_app') LIMIT 1""")
    if cursor.fetchone() is not None:
        raise ValueError("Unexpected application ownership outside its schema")
    cursor.execute(sql.SQL("REVOKE CREATE, TEMPORARY ON DATABASE {} FROM resume_app").format(sql.Identifier(database)))
    cursor.execute(sql.SQL("GRANT CREATE ON DATABASE {} TO resume_owner").format(sql.Identifier(database)))
    # REASSIGN checks inherited privileges, not SET membership alone. Enable
    # those rights only for the privileged administrator during the transition.
    cursor.execute(sql.SQL("GRANT resume_app, resume_owner TO {} WITH INHERIT TRUE, SET TRUE").format(sql.Identifier(master_user)))
    try:
        cursor.execute("REASSIGN OWNED BY resume_app TO resume_owner")
        cursor.execute("ALTER SCHEMA public OWNER TO resume_owner")
    finally:
        cursor.execute(sql.SQL("GRANT resume_app, resume_owner TO {} WITH INHERIT FALSE, SET TRUE").format(sql.Identifier(master_user)))
    cursor.execute("SET ROLE resume_owner")
    try:
        cursor.execute("REVOKE ALL ON SCHEMA public FROM resume_app")
        cursor.execute("GRANT USAGE ON SCHEMA public TO resume_app")
        cursor.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM resume_app")
        cursor.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO resume_app")
        cursor.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM resume_app")
        cursor.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO resume_app")
        cursor.execute("ALTER DEFAULT PRIVILEGES FOR ROLE resume_owner IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO resume_app")
        cursor.execute("ALTER DEFAULT PRIVILEGES FOR ROLE resume_owner IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO resume_app")
    finally:
        cursor.execute("RESET ROLE")
    cursor.execute("""SELECT 1 FROM pg_class WHERE relowner=(SELECT oid FROM pg_roles WHERE rolname='resume_app')
        UNION ALL SELECT 1 FROM pg_namespace WHERE nspowner=(SELECT oid FROM pg_roles WHERE rolname='resume_app') LIMIT 1""")
    if cursor.fetchone() is not None:
        raise ValueError("Unresolved runtime ownership")
    cursor.execute("SELECT 1 WHERE has_database_privilege('resume_app',%s,'CREATE,TEMPORARY')", (database,))
    if cursor.fetchone() is not None:
        raise ValueError("Unexpected runtime database creation privilege")
    cursor.execute("SELECT 1 FROM pg_namespace WHERE nspname NOT LIKE 'pg_%' AND has_schema_privilege('resume_app',oid,'CREATE') LIMIT 1")
    if cursor.fetchone() is not None:
        raise ValueError("Unexpected runtime schema creation privilege")


@contextmanager
def migration_connection(database, master_user, master_password):
    """Single-process direct bootstrap override. Secrets exist only in memory."""
    wrapper = connections["default"]
    original = wrapper.settings_dict
    temporary = deepcopy(original)
    temporary.update(deepcopy(database))
    temporary.update(USER=master_user, PASSWORD=master_password, CONN_MAX_AGE=0)
    temporary["OPTIONS"]["assume_role"] = "resume_owner"
    wrapper.close()
    connections.databases["default"] = temporary
    wrapper.settings_dict = temporary
    try:
        yield
    finally:
        try:
            wrapper.close()
        finally:
            wrapper.settings_dict = original
            connections.databases["default"] = original


class Command(BaseCommand):
    help = "Create ordinary and read-only cloud roles, migrate and provision the initial reviewer."
    requires_system_checks = []

    def handle(self, *args, **options):
        database = settings.DATABASES["default"]
        master_user, master_password = os.getenv("RDS_MASTER_USERNAME", ""), os.getenv("RDS_MASTER_PASSWORD", "")
        username, password = os.getenv("CLOUD_REVIEWER_USERNAME", ""), os.getenv("CLOUD_REVIEWER_PASSWORD", "")
        stream_password = os.getenv("STREAM_DB_PASSWORD", "")
        try:
            app_limit = int(os.getenv("APP_DB_CONNECTION_LIMIT", "128"))
            stream_limit = int(os.getenv("STREAM_DB_CONNECTION_LIMIT", "64"))
        except ValueError:
            raise CommandError("Cloud database connection limits must be positive integers.") from None
        if (settings.DEBUG or getattr(settings, "POSTGRES_PROXY_MODE", False)
                or database["ENGINE"] != "django.db.backends.postgresql"
                or database.get("USER") != "resume_app" or min(app_limit, stream_limit) < 1
                or database.get("OPTIONS", {}).get("sslmode") != "verify-full"
                or not database.get("OPTIONS", {}).get("sslrootcert")
                or not master_user or not master_password or master_user in {"resume_app", "resume_stream"}
                or not username or len(username) > 150 or len(password) < 24
                or len(stream_password) < 24 or len(database.get("PASSWORD", "")) < 24):
            raise CommandError("Cloud bootstrap requires production settings, direct verified database TLS and bootstrap-only credentials.")
        parameters = dict(host=database["HOST"], port=database.get("PORT", "5432"), dbname=database["NAME"],
                          sslmode="verify-full", sslrootcert=database["OPTIONS"]["sslrootcert"], connect_timeout=10)
        try:
            with psycopg.connect(**parameters, user=master_user, password=master_password, cursor_factory=ClientCursor) as admin:
                with admin.cursor() as cursor:
                    ensure_role(cursor, "resume_app", database["PASSWORD"], app_limit)
                    cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO resume_app").format(sql.Identifier(database["NAME"])))
                    cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
                    cursor.execute(sql.SQL("REVOKE TEMPORARY ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database["NAME"])))
                    ensure_runtime_owner(cursor, database["NAME"], master_user)
            connections.close_all()
            with migration_connection(database, master_user, master_password):
                call_command("migrate", interactive=False, verbosity=0, stdout=StringIO(), stderr=StringIO())
            with psycopg.connect(**parameters, user=master_user, password=master_password, cursor_factory=ClientCursor) as admin:
                with admin.cursor() as cursor:
                    ensure_role(cursor, "resume_stream", stream_password, stream_limit, readonly=True)
                    ensure_stream_permissions(cursor, database["NAME"], owner="resume_owner")
            # Repeat runs must prove supplied secrets match preserved credentials.
            with psycopg.connect(**parameters, user="resume_stream", password=stream_password) as stream:
                with stream.cursor() as cursor:
                    for table in STREAM_TABLES:
                        cursor.execute(sql.SQL("SELECT 1 FROM {} LIMIT 0").format(sql.Identifier("public", table)))
            users = get_user_model().objects
            if not users.filter(username=username).exists():
                users.create_user(username=username, password=password, is_staff=False, is_superuser=False)
        except Exception:
            raise CommandError("Cloud bootstrap failed; inspect database availability and configured permissions privately.") from None
        self.stdout.write("Cloud database and initial reviewer ready.")
