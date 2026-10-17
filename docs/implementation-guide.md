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
attempts and deadlines. Inspect `backend/matching/jobs.py`, `backend/matching/tasks.py`, `backend/config/celery.py`
and `backend/matching/management/commands/relay_jobs.py`.

Check: run `./scripts/lab test` against PostgreSQL. Stop the worker, submit a synthetic
job through the API and observe queued state. Restart the worker and expect one result.
Repeat with a broker interruption and retained volumes. Concurrency tests should reject
a duplicate/stale completion; do not assume an empty SQLite test proves row locking.

For the local synthetic drill, run `docker compose stop worker`, submit the fictional
sample in the UI, then run `docker compose start worker`. Restore it promptly, within
the job deadline. For the broker drill, use `docker compose stop broker`, submit a new
sample, then `docker compose start broker`. Compare the job's final result and attempt
count. These commands affect only this repository's Compose project; never stop an
unrelated container or remove volumes. Expected queued/recovery behavior is explained
in [the failure sequence](architecture.md#failure-and-recovery).

## 5. Make asynchronous state understandable

Build the submission form against the jobs API. Retain one idempotency key for an
unchanged normalized payload across ambiguous network errors; include file bytes and
parser extension in its identity. Use a new key for changed input. Poll only active
jobs, one request at a time, with a deadline per request. Pause on errors with a manual
resume action; cancel timers/requests on unmount or authentication loss. Inspect
`frontend/src/App.tsx`, `frontend/src/api.ts` and their neighboring regression tests.

Check: run `npm test` and `npm run build` in `frontend/` when rebuilding this stage.
Simulate a lost admission response, retry unchanged input and expect one logical job.
Change a file extension and expect a fresh key. Delete an unrelated older report and
confirm that an ambiguous submission retains its key. Reload to recover pending jobs.

Check: admission is visibly distinct from completion; a failed job never looks like a
zero score; authentication loss clears private drafts and job state. Existing saved
reports remain available. The actual UI milestone is linked below.

## 6. Follow the job through safe logs

Instrument a dedicated allowlisted event path and add the explicitly OSS viewer to
Compose. Use standard batched OTLP export with bounded buffers and network wait; never
flush on the request/job path or forward arbitrary root logs. Correlate API admission,
relay publication and worker completion using request/job IDs. Inspect
[ADR 0004](decisions/0004-searchable-observability.md) and the README's runtime commands
before choosing fields. Preserve existing generated credentials during an upgrade.

Check: search actual emitted events for one synthetic job; no document, quote, prompt
or credential fields appear. Stop the viewer and verify jobs still complete. Bounded
best-effort telemetry may lose events; the database remains the business ledger.

## Checkpoints before expanding

Explain where accepted work survives a broker outage, what a confirmation proves,
which token fences a stale worker, and where the score is owned. Then change one
requirement or failure at a time. Add a second domain only after you can reconstruct
this flow and its failure behavior without relying on the reference implementation.

## Actual build history

These are real checkpoints, not a reconstructed sequence. The initial synchronous
baseline remains in Git. The researched design was recorded after the queue work and
before the remaining UI/logging implementation; it has not been backdated.

| Outcome | Actual commit |
| --- | --- |
| Initial evidence boundary | [8036951](https://github.com/junrillg/resume-match-bedrock/commit/8036951d9c4254c63efa24658f41d6ed2c58a48c) |
| Docker + PostgreSQL foundation | [6dbaf57](https://github.com/junrillg/resume-match-bedrock/commit/6dbaf577e0e2a9188fe40c66f0e3f2e529a4e037) |
| Durable queue, outbox and recovery | [4456c32](https://github.com/junrillg/resume-match-bedrock/commit/4456c3214871f46ee47e84f6add9f98dcf54f2d5) |
| Researched design and rebuild plan | [f5bd64e](https://github.com/junrillg/resume-match-bedrock/commit/f5bd64ee55e4d49c743437e3ffd4346c0c5141b5) |
| Job-aware React review | [44b0d1e](https://github.com/junrillg/resume-match-bedrock/commit/44b0d1e) |
| Safe searchable observability and restart checks | [a79e75e](https://github.com/junrillg/resume-match-bedrock/commit/a79e75e702431878b684b5b2f7aa719a5eacab2c) |

Supplementary [learning resources](learning-resources.md) are grouped by topic. They
are optional; the repository contains the essential run/build/check instructions.
