# Implementation reference

This reference maps the [design](design.md) and [architecture decisions](decisions/0001-durable-background-work.md)
to the implemented components, their guarantees and operating checks. The repository
runs one authenticated résumé comparison flow with synthetic data; the local provider
exercises the complete infrastructure path without AWS credentials.

## Runtime and entry point

[`compose.yaml`](../compose.yaml) starts PostgreSQL, RabbitMQ, Django/Gunicorn, a relay,
a Celery worker, OpenObserve and the React/nginx entry point. A migration service runs
before the application starts. Dockerfiles pin the runtime versions; nginx provides
the same-origin browser/API boundary.

| Source | Responsibility |
| --- | --- |
| [`scripts/lab`](../scripts/lab) | Startup, readiness, local credentials, status and verification commands |
| [`backend/Dockerfile`](../backend/Dockerfile) | Python application image |
| [`frontend/Dockerfile`](../frontend/Dockerfile) | React production build and nginx runtime |
| [`frontend/nginx.conf`](../frontend/nginx.conf) | Static assets and API proxy with Docker DNS resolution |

Run `./scripts/lab up`, then `./scripts/lab status`. The application listens on
`http://127.0.0.1:8088`; OpenObserve listens on `http://127.0.0.1:5080`. Database and
broker ports remain inside Compose. `./scripts/lab credentials` displays generated
local logins in the operator's terminal. Credentials live in ignored, owner-only `.env`.
Ordinary startup preserves existing credentials and volumes; `./scripts/lab down`
stops the stack without removing its data.

## Document and evidence boundary

[`backend/matching/services.py`](../backend/matching/services.py) bounds document
normalization, validates explicit skill/weight requirements, obtains proposed evidence,
checks source membership and skill boundaries, then calculates weighted literal coverage.
[`backend/matching/tests.py`](../backend/matching/tests.py) covers input, scoring and
mocked provider contracts. Forged quotes and SQL extracted only from MySQL are rejected.
The synthetic Python/Django/React sample scores 80% against the default four requirements.

The model does not own the score. A valid quote does not prove competence, positive
experience or document truth. Bedrock remains disabled in Compose; its adapter is
verified with mocked SDK responses. See [ADR 0002](decisions/0002-evidence-and-data-boundaries.md)
for data retention and external-provider boundaries.

## Durable admission

[`models.py`](../backend/matching/models.py) defines jobs, outbox events and the unique
job/result relationship. [`views.py`](../backend/matching/views.py) authenticates the
caller, enforces CSRF and owner access, normalizes input, checks quotas and commits the
job plus dispatch intent in one PostgreSQL transaction. HTTP 202 indicates acceptance.

An owner-scoped UUID idempotency key and payload fingerprint make repeated identical
admission return the same logical job. A conflicting payload returns 409. Rollback
leaves neither a job nor an outbox entry. Another account cannot read or delete the job.
Admission remains possible during a broker outage because PostgreSQL owns accepted work.
[`test_jobs.py`](../backend/matching/test_jobs.py) verifies admission and concurrency
against PostgreSQL. See [ADR 0001](decisions/0001-durable-background-work.md).

## Delivery, processing and recovery

[`jobs.py`](../backend/matching/jobs.py) publishes UUID-only persistent messages to a
declared durable queue and marks the outbox sent after publisher confirmation. The
[`relay command`](../backend/matching/management/commands/relay_jobs.py) drives dispatch
and reconciliation. [`tasks.py`](../backend/matching/tasks.py) and
[`Celery configuration`](../backend/config/celery.py) connect worker delivery to the
business job lifecycle.

A worker claims under a short locked transaction, extracts outside the transaction and
finishes only with a current lease token. Recovery handles expired leases and stale
queued wakeups within finite attempts and deadlines. Duplicate or stale completion
cannot create a second committed result. This guarantee does not prevent repeated
external provider calls or charges. PostgreSQL concurrency tests cover these boundaries;
SQLite alone cannot demonstrate row-lock behavior.

For a local synthetic worker interruption, run `docker compose stop worker`, submit
the synthetic sample and observe queued state, then run `docker compose start worker`.
Restore it within the job deadline and verify one completed result. For a broker
interruption, run `docker compose stop broker`, submit a new sample, then run
`docker compose start broker`. Admission should return 202 while the relay retains
unsent dispatch intent. Verify final state and attempt count after recovery.
These commands affect this repository's Compose project; keep its volumes and avoid
unrelated containers. The [failure sequence](architecture.md#failure-and-recovery)
explains the persisted state at each boundary.

## Browser state and isolation

[`App.tsx`](../frontend/src/App.tsx) and [`api.ts`](../frontend/src/api.ts) submit durable
jobs, track active work and display evidence reports. An unchanged normalized payload
retains its idempotency key across an ambiguous admission response; its identity includes
file bytes and parser extension. Changed inputs receive a new key.

Polling uses one request at a time, with a per-request deadline. It pauses on errors
with an explicit resume action, stops at terminal state and cancels on unmount or
authentication loss. Pending jobs reload from the server. Admission is visibly distinct
from completion, and a failed job does not appear as a zero score. Authentication loss
clears private drafts and job state; stale asynchronous responses cannot restore them.
Existing saved reports remain available.

[`App.test.tsx`](../frontend/src/App.test.tsx) covers polling, idempotency and isolation
regressions. Run `npm test` and `npm run build` in `frontend/` for unit and production
build checks; these complement the complete Compose runtime check.

## Correlated operational logs

[`telemetry.py`](../backend/matching/telemetry.py) emits fixed, allowlisted events through
bounded batched OTLP export to OpenObserve OSS. API admission, relay publication and
worker completion share request/job IDs. Document text, quotes, prompts, usernames,
filenames, credentials and raw exceptions are excluded. Arbitrary root logs are not
forwarded, and business paths never wait for a telemetry flush.

[`test_telemetry.py`](../backend/matching/test_telemetry.py) covers privacy and exporter
failure behavior. The [README search instructions](../README.md#search-one-job-across-services)
provide the exact local login and query procedure. Verify records for one synthetic job;
stop OpenObserve and verify jobs still complete. Bounded best-effort telemetry may lose
events; PostgreSQL remains the business ledger. See
[ADR 0004](decisions/0004-searchable-observability.md) for resource limits and retention.

## Verification commands

```sh
./scripts/lab test
docker compose exec -T api python manage.py check
docker compose exec -T api python manage.py makemigrations --check --dry-run
```

The [README](../README.md#verify) records observed test, runtime and failure-check results.
These establish the documented local behavior, not live Bedrock access, production
capacity or high availability. The [broader deployment discussion](architecture.md#what-a-broader-deployment-would-add)
identifies the additional operational design required for production.

## Actual build history

These commits record the actual implementation sequence. The initial synchronous
baseline remains in Git. The researched design was recorded after the queue work and
before the remaining UI/logging implementation; it has not been backdated.

| Outcome | Actual commit |
| --- | --- |
| Initial evidence boundary | [8036951](https://github.com/junrillg/resume-match-bedrock/commit/8036951d9c4254c63efa24658f41d6ed2c58a48c) |
| Docker + PostgreSQL foundation | [6dbaf57](https://github.com/junrillg/resume-match-bedrock/commit/6dbaf577e0e2a9188fe40c66f0e3f2e529a4e037) |
| Durable queue, outbox and recovery | [4456c32](https://github.com/junrillg/resume-match-bedrock/commit/4456c3214871f46ee47e84f6add9f98dcf54f2d5) |
| Researched design package | [f5bd64e](https://github.com/junrillg/resume-match-bedrock/commit/f5bd64ee55e4d49c743437e3ffd4346c0c5141b5) |
| Job-aware React review | [44b0d1e](https://github.com/junrillg/resume-match-bedrock/commit/44b0d1e) |
| Safe searchable observability and restart checks | [a79e75e](https://github.com/junrillg/resume-match-bedrock/commit/a79e75e702431878b684b5b2f7aa719a5eacab2c) |
