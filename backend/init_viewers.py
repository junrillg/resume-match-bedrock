"""Provision dedicated local inspection accounts without resetting existing passwords."""
import base64
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import psycopg
from psycopg import sql
from kombu import Connection
from urllib.parse import quote

EVENT_READ = r"^(celeryev|flower\..*|.*\.reply\.flower\.pidbox)$"
EVENT_WRITE = r"^(flower\..*|.*\.reply\.flower\.pidbox)$"
TABLES = ("matching_job", "matching_match", "matching_document", "matching_outboxevent")


def rabbit_request(path, *, method="GET", body=None, username="lab", password=None):
    password = os.environ["RABBITMQ_PASSWORD"] if password is None else password
    token = base64.b64encode((username + ":" + password).encode()).decode()
    request = Request("http://broker:15672/api/" + path, method=method,
                      data=None if body is None else json.dumps(body).encode(),
                      headers={"Authorization": "Basic " + token, "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=5) as response:
            content = response.read()
            return json.loads(content) if content else None
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise RuntimeError("RabbitMQ viewer account operation was refused.") from None


def provision_rabbit():
    for attempt in range(60):
        try:
            rabbit_request("overview")
            break
        except URLError:
            if attempt == 59:
                raise RuntimeError("RabbitMQ management did not become ready.") from None
            time.sleep(1)
    accounts = [
        ("lab_monitor", "RABBITMQ_VIEWER_PASSWORD", ["monitoring"], {"configure": "^$", "read": "^$", "write": "^$"}),
        ("flower", "FLOWER_BROKER_PASSWORD", [], {"configure": EVENT_READ, "read": EVENT_READ, "write": EVENT_WRITE}),
    ]
    for username, key, tags, permissions in accounts:
        existing = rabbit_request("users/" + username)
        if existing is None:
            rabbit_request("users/" + username, method="PUT", body={"password": os.environ[key], "tags": tags})
        elif sorted(existing["tags"]) != sorted(tags):
            raise RuntimeError("Existing viewer account has unexpected privileges; preserve and inspect it.")
        current = rabbit_request("permissions/%2F/" + username)
        if current is not None and any(current[k] != v for k, v in permissions.items()):
            raise RuntimeError("Existing viewer permissions differ; preserve and inspect them.")
        if current is None:
            rabbit_request("permissions/%2F/" + username, method="PUT", body=permissions)
        # Authenticate with the saved password, without putting a credential in argv or output.
        with Connection("amqp://{}:{}@broker:5672//".format(username, quote(os.environ[key], safe="")), connect_timeout=5) as connection:
            connection.connect()


def provision_postgres():
    connect = {"host": "db", "dbname": os.environ["POSTGRES_DB"], "connect_timeout": 5}
    with psycopg.connect(**connect, user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"], autocommit=True) as admin:
        role = admin.execute("SELECT rolsuper, rolinherit, rolcreaterole, rolcreatedb, rolcanlogin, rolreplication, rolbypassrls FROM pg_roles WHERE rolname='lab_viewer'").fetchone()
        if role is None:
            verifier = admin.pgconn.encrypt_password(os.environ["POSTGRES_VIEWER_PASSWORD"].encode(), b"lab_viewer", b"scram-sha-256").decode()
            admin.execute(sql.SQL("CREATE ROLE lab_viewer LOGIN NOINHERIT PASSWORD {}").format(sql.Literal(verifier)))
        elif role != (False, False, False, False, True, False, False):
            raise RuntimeError("Existing database viewer has unexpected privileges; preserve and inspect it.")
        if admin.execute("SELECT EXISTS(SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname='lab_viewer'))").fetchone()[0]:
            raise RuntimeError("Database viewer must not inherit any role membership.")
        unsafe = admin.execute("""
            SELECT EXISTS(
              SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
              WHERE n.nspname NOT LIKE 'pg_%%' AND n.nspname<>'information_schema'
              AND (c.relowner=(SELECT oid FROM pg_roles WHERE rolname='lab_viewer')
                OR (c.relkind IN ('r','p','v','m','f') AND (
                  has_table_privilege('lab_viewer',c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN,SELECT WITH GRANT OPTION')
                  OR (has_table_privilege('lab_viewer',c.oid,'SELECT')
                    AND (n.nspname<>'public' OR c.relname<>ALL(%s)))))))
              OR EXISTS(SELECT 1 FROM pg_namespace WHERE nspname NOT LIKE 'pg_%%'
                AND nspname<>'information_schema' AND has_schema_privilege('lab_viewer',oid,'CREATE'))
              OR has_database_privilege('lab_viewer',current_database(),'CREATE')
            """, (list(TABLES),)).fetchone()[0]
        if unsafe:
            raise RuntimeError("Database viewer has privileges outside its table allowlist; preserve and inspect it.")
        admin.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO lab_viewer").format(sql.Identifier(connect["dbname"])))
        admin.execute("GRANT USAGE ON SCHEMA public TO lab_viewer")
        admin.execute(sql.SQL("GRANT SELECT ON {} TO lab_viewer").format(sql.SQL(", ").join(sql.Identifier("public", table) for table in TABLES)))
        admin.execute("ALTER ROLE lab_viewer SET default_transaction_read_only=on")
    with psycopg.connect(**connect, user="lab_viewer", password=os.environ["POSTGRES_VIEWER_PASSWORD"]) as viewer:
        for table in TABLES:
            viewer.execute(sql.SQL("SELECT 1 FROM {} LIMIT 1").format(sql.Identifier("public", table)))


if __name__ == "__main__":
    try:
        provision_postgres()
        provision_rabbit()
    except Exception:
        raise SystemExit("Viewer initialization failed; check local service health and viewer account configuration.") from None
    print("Dedicated read-only viewer accounts ready.")
