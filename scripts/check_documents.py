"""Exercise durable originals through the running local HTTP application (synthetic data only)."""
import http.cookiejar
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8088/api/"
state = dict(line.split("=", 1) for line in (ROOT / ".env").read_text().splitlines() if line and not line.startswith("#"))
http = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
csrf = ""
created = []
evidence = {}

def compose(*arguments):
    subprocess.run(["docker", "compose", *arguments], cwd=ROOT, check=True, capture_output=True)

def scanner_ready():
    for attempt in range(120):
        check = subprocess.run(["docker", "compose", "ps", "scanner", "--format", "{{.Health}}"], cwd=ROOT, check=True, capture_output=True, text=True)
        if check.stdout.strip() == "healthy":
            return
        time.sleep(2)
    raise AssertionError("Scanner did not regain readiness.")


def request(path, *, method="GET", body=None, headers=None):
    extra = dict(headers or {})
    if method != "GET":
        extra["X-CSRFToken"] = csrf
    try:
        response = http.open(urllib.request.Request(BASE + path, data=body, method=method, headers=extra), timeout=15)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        data = response.read()
        return response.status, json.loads(data) if "application/json" in response.headers.get("Content-Type", "") else data


def submit(*, document_id=None, raw=None, key=None, reprocess=False):
    boundary = "storage-check-" + uuid.uuid4().hex
    fields = {"job_title": "Synthetic durable storage check", "requirements": '[{"skill":"Python","weight":1}]'}
    if document_id:
        fields.update(document_id=document_id, reprocess=str(reprocess).lower())
    body = b""
    for name, value in fields.items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
    if raw is not None:
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="resume"; filename="synthetic-original.txt"\r\nContent-Type: text/plain\r\n\r\n'.encode() + raw + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return request("jobs/", method="POST", body=body, headers={"Content-Type": "multipart/form-data; boundary=" + boundary, "Idempotency-Key": key or str(uuid.uuid4())})


def wait(job_id):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        status, job = request(f"jobs/{job_id}/")
        assert status == 200, f"Status read failed: {status}"
        if job["status"] in {"succeeded", "failed"}:
            return job
        time.sleep(1)
    raise AssertionError("Synthetic job did not reach a terminal state within 90 seconds.")


status, session = request("session/")
assert status == 200
csrf = session["csrfToken"]
status, session = request("login/", method="POST", body=json.dumps({"username": "lab", "password": state["LAB_DEMO_PASSWORD"]}).encode(), headers={"Content-Type": "application/json"})
assert status == 200, "Synthetic account login failed."
csrf = session["csrfToken"]
original = b"\xef\xbb\xbfSynthetic Python APIs.\r\nByte-for-byte original.\r\n"
try:
    key = str(uuid.uuid4())
    status, first = submit(raw=original, key=key)
    assert status == 202, f"Upload rejected: {status}"
    document_id = first["document"]["id"]
    created.append(document_id)
    status, replay = submit(raw=original, key=key)
    assert status == 202 and replay["id"] == first["id"]
    result = wait(first["id"])
    assert result["status"] == "succeeded", "Clean original did not complete: " + str(result["error_code"])
    assert request(f"documents/{document_id}/download/") == (200, original)
    subprocess.run(["docker", "compose", "restart", "objectstore"], cwd=ROOT, check=True, capture_output=True)
    for attempt in range(30):
        status, data = request(f"documents/{document_id}/download/")
        if status == 200:
            assert data == original
            break
        time.sleep(1)
    else:
        raise AssertionError("Original did not survive object-store restart.")
    for reprocess in [False, True]:
        status, job = submit(document_id=document_id, reprocess=reprocess)
        assert status == 202
        assert wait(job["id"])["status"] == "succeeded"
    assert request(f"jobs/{first['id']}/", method="DELETE")[0] == 200
    assert request(f"documents/{document_id}/download/") == (200, original)
    # These bounded outages affect only this lab; always restore both services below.
    compose("stop", "objectstore")
    outage_key = str(uuid.uuid4())
    status, _ = submit(raw=original, key=outage_key)
    assert status == 503, f"Unavailable storage must deny admission: {status}"
    assert request(f"documents/{document_id}/", method="DELETE")[0] == 202
    assert request(f"documents/{document_id}/download/")[0] == 404
    assert submit(document_id=document_id)[0] == 404
    evidence["object_storage_outage"] = {"upload_status": 503, "tombstoned_download_status": 404, "reuse_status": 404}
    compose("start", "objectstore")
    for attempt in range(30):
        status, recovered = submit(raw=original, key=outage_key)
        if status == 202:
            break
        assert status == 503
        time.sleep(1)
    else:
        raise AssertionError("Storage did not recover.")
    recovered_id = recovered["document"]["id"]
    created.append(recovered_id)
    assert wait(recovered["id"])["status"] == "succeeded"
    status, replay = submit(raw=original, key=outage_key)
    assert status == 202 and replay["id"] == recovered["id"]
    evidence["object_storage_outage"].update(recovered_job_id=recovered["id"], replay_same_job=True)
    for attempt in range(30):
        # The generated immutable key belongs only to this check's synthetic document.
        check = subprocess.run(["docker", "compose", "exec", "-T", "api", "python", "manage.py", "shell", "-c",
            "from matching.documents import client; from botocore.exceptions import ClientError; "
            + "exec(" + repr("try:\n client().get_object(Bucket='resume-originals',Key='originals/" + document_id + "')\n print('PRESENT')\nexcept ClientError as exc:\n print('ABSENT' if exc.response['Error']['Code'] in {'NoSuchKey','404'} else 'ERROR')".replace("\n", "\n")) + ")"],
            cwd=ROOT, check=True, capture_output=True, text=True)
        if "ABSENT" in check.stdout:
            break
        time.sleep(1)
    else:
        raise AssertionError("Tombstoned original was not physically removed after recovery.")
    evidence["object_storage_outage"]["physical_delete_after_restore"] = True
    compose("stop", "scanner")
    assert request(f"documents/{recovered_id}/download/")[0] == 503
    status, scanner_job = submit(raw=original)
    assert status == 202
    pending_id = scanner_job["document"]["id"]
    created.append(pending_id)
    failed = wait(scanner_job["id"])
    assert failed["status"] == "failed" and failed["match"] is None
    assert request(f"documents/{pending_id}/download/")[0] == 404
    evidence["scanner_outage"] = {"ready_download_status": 503, "pending_download_status": 404, "job_status": failed["status"], "error_code": failed["error_code"], "job_id": failed["id"], "no_report": failed["match"] is None}
    compose("start", "scanner")
    scanner_ready()
    status, retry = submit(document_id=pending_id, reprocess=True)
    assert status == 202
    assert wait(retry["id"])["status"] == "succeeded"
    evidence["scanner_outage"]["recovered_without_reupload"] = True
    eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    status, infected = submit(raw=eicar)
    assert status == 202
    created.append(infected["document"]["id"])
    rejected = wait(infected["id"])
    assert rejected["status"] == "failed" and rejected["error_code"] == "document_rejected"
    assert request(f"documents/{created[-1]}/download/")[0] == 404
    print("PASS: exact original, replay, restart durability, reuse, reprocess, comparison separation and EICAR quarantine.")
    print("Correlation IDs:", first["request_id"], first["id"], first["document"]["id"])
    print(json.dumps(evidence, sort_keys=True))
finally:
    compose("start", "objectstore", "scanner")
    scanner_ready()
    for document_id in created:
        status, _ = request(f"documents/{document_id}/", method="DELETE")
        assert status in {202, 404}, "Synthetic cleanup request failed."
    request("logout/", method="POST")
