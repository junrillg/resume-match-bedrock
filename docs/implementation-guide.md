# Rebuild the flow independently

Start with [the scenario and vocabulary](design.md), then [the decisions](decisions/0001-durable-background-work.md).
Use a separate scratch repository. The running reference is a comparison point, not a
requirement to copy every file. Work through one stage at a time and keep its checks
with its code. The topic lessons in the private tutorial add hints and learning videos.

## 1. Make the system runnable

Create a Django API, PostgreSQL and a same-origin React/nginx entry point under Compose.
Add migrations, readiness checks and private local credentials. Inspect `compose.yaml`,
`backend/Dockerfile`, `frontend/Dockerfile`, `frontend/nginx.conf` and `scripts/lab`.

Check: one command starts healthy services; a browser session can sign in, and a mutation
without CSRF fails. Run `./scripts/lab up`, then `./scripts/lab status`. Stop with
`./scripts/lab down`; ordinary startup must not delete volumes or regenerate passwords.

## 2. Define an inspectable evidence boundary

Implement bounded document normalization and explicit skill/weight validation. Let a
local provider propose quotes, then validate source membership and skill boundaries.
Calculate the weighted coverage in application code. Inspect `backend/matching/services.py`
and the input/scoring/provider cases in `backend/matching/tests.py`.

Check: the fictional Python/Django/React sample scores 80% against the default four
requirements; forged quotes and SQL extracted only from MySQL are rejected. A quote is
not proof of competence. Keep real AWS calls disabled while rebuilding this contract.

## 3. Admit work durably

Define Job and OutboxEvent records in PostgreSQL. Require an owner-scoped idempotency
key and fingerprint; commit job and dispatch intent in one transaction, then return202.
Inspect `backend/matching/models.py`, the jobs API in `backend/matching/views.py`, and
`backend/matching/test_jobs.py`.

Check: identical owner/key/body yields one job; a conflicting body yields409; rollback
leaves neither job nor dispatch. Another account cannot read/delete the job. Admission
must still work when RabbitMQ is unavailable because the database owns accepted work.

## 4. Deliver, process and recover

Declare a durable queue. Relay UUID-only persistent messages with publisher confirms.
A separate worker claims under a short transaction, extracts outside the transaction,
and finishes only with a current lease token. Reconcile expired/stale jobs with bounded
attempts and deadlines. Inspect `backend/matching/jobs.py`, `tasks.py`, `config/celery.py`
and `management/commands/relay_jobs.py`.

Check: run `./scripts/lab test` against PostgreSQL. Stop the worker, submit a synthetic
job through the API and observe queued state. Restart the worker and expect one result.
Repeat with a broker interruption and retained volumes. Concurrency tests should reject
a duplicate/stale completion; do not assume an empty SQLite test proves row locking.

## 5. Make asynchronous state understandable

Planned next: React will submit to the jobs API, retain a key across ambiguous network
retries, poll owner-scoped status and show queued/running/succeeded/failed states. The
current UI still uses the compatibility route until this milestone is verified.

Check: admission is visibly distinct from completion; a failed job never looks like a
zero score; authentication loss clears private drafts and job state. Existing saved
reports remain available. The final guide will link the verified UI milestone.

## 6. Follow the job through safe logs

Planned next: instrument safe events and bring up the OSS log viewer in Compose. Use
request/job IDs to correlate API admission, relay publication and worker completion.
Inspect [ADR0004](decisions/0004-searchable-observability.md) before choosing fields.

Check: search actual emitted events for one synthetic job; no document, quote, prompt
or credential fields appear. Stop the viewer and verify jobs still complete. Bounded
best-effort telemetry may lose events; the database remains the business ledger.

## Checkpoints before expanding

Explain where accepted work survives a broker outage, what a confirmation proves,
which token fences a stale worker, and where the score is owned. Then change one
requirement or failure at a time. Add a second domain only after you can reconstruct
this flow and its failure behavior without relying on the reference implementation.
