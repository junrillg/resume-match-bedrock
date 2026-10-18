"""Generate private in-container connection files before the official entrypoint."""
import json
import os
from pathlib import Path

os.umask(0o077)
database = os.environ["POSTGRES_DB"]
password = os.environ["POSTGRES_VIEWER_PASSWORD"]
def pgpass_escape(value):
    return value.replace("\\", "\\\\").replace(":", "\\:")

Path("/tmp/pgpass").write_text(":".join(map(pgpass_escape, ["db", "5432", database, "lab_viewer", password])) + "\n")
Path("/tmp/servers.json").write_text(json.dumps({"Servers": {"1": {
    "Name": "Resume Match (read only)", "Group": "Local lab", "Host": "db", "Port": 5432,
    "MaintenanceDB": database, "Username": "lab_viewer", "SSLMode": "prefer",
    "PassFile": "/var/lib/pgadmin/storage/lab_example.invalid/.pgpass",
}}}))
os.execv("/entrypoint.sh", ["/entrypoint.sh"])
