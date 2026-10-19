"""Actual PostgreSQL permission/initialization checks, scoped to the disposable test DB."""
import secrets
from unittest import skipUnless

import psycopg
from psycopg import ClientCursor, sql
from django.db import connection
from django.test import TransactionTestCase

from .management.commands.bootstrap_cloud_db import STREAM_TABLES, ensure_role, ensure_stream_permissions


class StreamRoleTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql": self.skipTest("PostgreSQL privilege semantics")
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname='resume_stream'")
            if cursor.fetchone(): self.skipTest("Preserve pre-existing adopted stream role")
        self.password=secrets.token_urlsafe(32)
        params=connection.get_connection_params().copy()
        params.pop("cursor_factory",None)
        params.pop("context",None)
        self.admin=psycopg.connect(**params,autocommit=True,cursor_factory=ClientCursor)
        self.addCleanup(self.cleanup_role)
        with self.admin.cursor() as cursor:
            cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            cursor.execute(sql.SQL("REVOKE TEMPORARY ON DATABASE {} FROM PUBLIC").format(sql.Identifier(connection.settings_dict["NAME"])))
            ensure_role(cursor,"resume_stream",self.password,64,readonly=True)
            ensure_stream_permissions(cursor,connection.settings_dict["NAME"])
        self.params={**params,"user":"resume_stream","password":self.password}

    def cleanup_role(self):
        with self.admin.cursor() as cursor:
            cursor.execute("DROP OWNED BY resume_stream")
            cursor.execute("DROP ROLE resume_stream")
        self.admin.close()
        self.password=None

    def test_four_selects_only_and_role_defaults_require_no_initialization_set(self):
        from django.db.backends.postgresql.base import DatabaseWrapper
        with psycopg.connect(**self.params,autocommit=True) as stream:
            with stream.cursor() as cursor:
                for table in STREAM_TABLES:
                    cursor.execute(sql.SQL("SELECT 1 FROM {} LIMIT 0").format(sql.Identifier(table)))
                for setting,value in [("TimeZone","UTC"),("statement_timeout","3s"),("lock_timeout","1s"),("default_transaction_read_only","on")]:
                    cursor.execute(sql.SQL("SHOW {}").format(sql.Identifier(setting)))
                    self.assertEqual(cursor.fetchone()[0],value)
                # Effective grants stay narrow even if a client clears read-only mode.
                cursor.execute("SET default_transaction_read_only=off")
                for query in ["SELECT 1 FROM matching_document LIMIT 0", "SELECT 1 FROM matching_match LIMIT 0",
                              "UPDATE auth_user SET is_active=false WHERE false", "CREATE TABLE public.forbidden(id int)",
                              "SELECT last_value FROM auth_user_id_seq"]:
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege): cursor.execute(query)
            wrapper=DatabaseWrapper({**connection.settings_dict,"TIME_ZONE":None,"OPTIONS":{}})
            # Django 5.2 returns False when neither SET timezone nor assume_role is needed.
            self.assertFalse(wrapper._configure_connection(stream))
        with self.admin.cursor() as cursor:
            cursor.execute("SELECT rolconnlimit FROM pg_roles WHERE rolname='resume_stream'")
            self.assertEqual(cursor.fetchone()[0],64)

    def test_repeat_preserves_password_and_rejects_unexpected_source_grant(self):
        with self.admin.cursor() as cursor:
            ensure_role(cursor,"resume_stream",secrets.token_urlsafe(32),64,readonly=True)
            ensure_stream_permissions(cursor,connection.settings_dict["NAME"])
        # The adopted old secret still authenticates; no secret is returned or formatted.
        with psycopg.connect(**self.params) as stream:
            stream.execute("SELECT 1")
        with self.admin.cursor() as cursor:
            cursor.execute("GRANT SELECT ON matching_document TO resume_stream")
            with self.assertRaisesMessage(ValueError,"Unexpected stream object privileges"):
                ensure_stream_permissions(cursor,connection.settings_dict["NAME"])

    def test_elevated_existing_role_and_membership_are_rejected(self):
        with self.admin.cursor() as cursor:
            cursor.execute("ALTER ROLE resume_stream CREATEDB")
            with self.assertRaisesMessage(ValueError,"Unexpected elevated"):
                ensure_role(cursor,"resume_stream",self.password,64,readonly=True)
            cursor.execute("ALTER ROLE resume_stream NOCREATEDB")
            cursor.execute(sql.SQL("GRANT {} TO resume_stream").format(sql.Identifier(connection.settings_dict["USER"])))
            with self.assertRaisesMessage(ValueError,"Unexpected database role membership"):
                ensure_role(cursor,"resume_stream",self.password,64,readonly=True)
            cursor.execute(sql.SQL("REVOKE {} FROM resume_stream").format(sql.Identifier(connection.settings_dict["USER"])))


class RuntimeOwnershipTests(TransactionTestCase):
    def test_non_superuser_bootstrap_migrates_as_nonlogin_owner_runtime_has_dml_without_ddl(self):
        from copy import deepcopy
        from io import StringIO
        import uuid
        from django.core.management import call_command
        from .management.commands.bootstrap_cloud_db import ensure_runtime_owner, migration_connection
        if connection.vendor != "postgresql": self.skipTest("PostgreSQL ownership semantics")
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname IN ('resume_app','resume_owner','resume_stream')")
            if cursor.fetchone(): self.skipTest("Preserve adopted role identities")
        params=connection.get_connection_params().copy()
        params.pop("context",None)
        params.pop("cursor_factory",None)
        dbname="owner_check_"+uuid.uuid4().hex[:12]
        bootstrap="bootstrap_check_"+uuid.uuid4().hex[:12]
        bootstrap_password=secrets.token_urlsafe(32)
        app_password=secrets.token_urlsafe(32)
        admin=psycopg.connect(**params,autocommit=True,cursor_factory=ClientCursor)
        created=False
        try:
            with admin.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE ROLE {} LOGIN CREATEDB CREATEROLE NOINHERIT PASSWORD %s").format(sql.Identifier(bootstrap)),(bootstrap_password,))
                cursor.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(dbname),sql.Identifier(bootstrap)))
                created=True
            master_params={**params,"dbname":dbname,"user":bootstrap,"password":bootstrap_password}
            with psycopg.connect(**master_params,autocommit=True,cursor_factory=ClientCursor) as master:
                with master.cursor() as cursor:
                    ensure_role(cursor,"resume_app",app_password,128)
                    cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
                    cursor.execute(sql.SQL("REVOKE TEMPORARY ON DATABASE {} FROM PUBLIC").format(sql.Identifier(dbname)))
                    # Model ownership from the previous bootstrap without a privileged login.
                    cursor.execute(sql.SQL("GRANT resume_app TO {} WITH INHERIT FALSE, SET TRUE").format(sql.Identifier(bootstrap)))
                    cursor.execute("GRANT CREATE, USAGE ON SCHEMA public TO resume_app")
                    cursor.execute("SET ROLE resume_app")
                    cursor.execute("CREATE TABLE public.legacy_owned(id serial PRIMARY KEY, value text)")
                    cursor.execute("RESET ROLE")
                    ensure_runtime_owner(cursor,dbname,bootstrap)
            direct=deepcopy(connection.settings_dict)
            direct.update(NAME=dbname,USER="resume_app",PASSWORD=app_password)
            original=connection.settings_dict
            with migration_connection(direct,bootstrap,bootstrap_password):
                call_command("migrate",interactive=False,verbosity=0,stdout=StringIO(),stderr=StringIO())
                self.assertEqual(connection.settings_dict["USER"],bootstrap)
                self.assertEqual(connection.settings_dict["OPTIONS"]["assume_role"],"resume_owner")
            self.assertIs(connection.settings_dict,original)
            self.assertNotIn("assume_role",connection.settings_dict["OPTIONS"])
            with psycopg.connect(**master_params,autocommit=True,cursor_factory=ClientCursor) as master:
                with master.cursor() as cursor:
                    ensure_role(cursor,"resume_app",secrets.token_urlsafe(32),128)
                    ensure_runtime_owner(cursor,dbname,bootstrap)
                    cursor.execute("SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname='public'")
                    self.assertEqual(cursor.fetchall(),[("resume_owner",)])
                    cursor.execute("SELECT rolcanlogin FROM pg_roles WHERE rolname='resume_owner'")
                    self.assertFalse(cursor.fetchone()[0])
                    ensure_role(cursor,"resume_stream",secrets.token_urlsafe(32),64,readonly=True)
                    ensure_stream_permissions(cursor,dbname,owner="resume_owner")
            app_params={**params,"dbname":dbname,"user":"resume_app","password":app_password}
            with psycopg.connect(**app_params,autocommit=True) as ordinary:
                with ordinary.cursor() as cursor:
                    cursor.execute("INSERT INTO legacy_owned(value) VALUES ('synthetic') RETURNING id")
                    key=cursor.fetchone()[0]
                    cursor.execute("SELECT value FROM legacy_owned WHERE id=%s",(key,))
                    self.assertEqual(cursor.fetchone()[0],"synthetic")
                    cursor.execute("UPDATE legacy_owned SET value='updated' WHERE id=%s",(key,))
                    cursor.execute("DELETE FROM legacy_owned WHERE id=%s",(key,))
                    cursor.execute("SELECT count(*) FROM django_migrations")
                    self.assertGreater(cursor.fetchone()[0],0)
                    for query in ["CREATE TABLE public.forbidden(id int)","ALTER TABLE legacy_owned ADD COLUMN forbidden int",
                                  "DROP TABLE legacy_owned","TRUNCATE legacy_owned","SET ROLE resume_owner","CREATE TEMP TABLE forbidden(id int)","CREATE SCHEMA forbidden"]:
                        with self.assertRaises(psycopg.errors.InsufficientPrivilege): cursor.execute(query)
        finally:
            connection.close()
            with admin.cursor() as cursor:
                if created:
                    cursor.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(dbname)))
                    cursor.execute("DROP ROLE IF EXISTS resume_stream")
                    cursor.execute("DROP ROLE IF EXISTS resume_app")
                    cursor.execute("DROP ROLE IF EXISTS resume_owner")
                cursor.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(bootstrap)))
            admin.close()
