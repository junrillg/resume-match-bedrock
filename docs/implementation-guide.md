# Implementation reference

Use this reference for a specific implementation or operating question. For the full
flow, read [the architecture](architecture.md); for requirements and rationale, see
[the design](design.md), [decisions](decisions/0001-durable-background-work.md) and
[primary research](research.md). All runtime examples use synthetic documents.

- **Run or inspect:** [startup](#runtime-and-entry-point), [log search](#search-one-job-across-services).
- **Trace implementation:** [source handoffs](#source-handoffs).
- **Review contracts:** [documents](#document-and-evidence-boundary), [API](#asynchronous-jobs-api), [delivery](#delivery-processing-and-recovery), [browser](#browser-state-and-isolation).
- **Check evidence:** [commands](#verification-commands), [observed behavior](#verified-local-behavior), [build history](#actual-build-history).

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
stops the stack without removing its data. Keep `.env` with those volumes: replacing
its passwords does not update credentials already initialized in them. An existing
SQLite development database is separate and untouched. This is a local HTTP stack
with Django debug enabled; it must not be exposed as an internet deployment.

Startup waits for dependencies, applies migrations and creates the synthetic `lab`
account once. nginx refreshes the API address through Docker DNS after container
recreation, preventing stale upstream 502s. The pinned nginx supports the
[OSS upstream resolver](https://nginx.org/en/docs/http/ngx_http_upstream_module.html).


## Source handoffs

The [three request diagrams](architecture.md#one-request-in-three-phases) show the runtime
sequence. The lookup below pins the corresponding implementation; source links identify
functions rather than implying every file must be read in full.

<details>
<summary>Exact source map: browser input → durable work → rendered report</summary>

| Boundary | Source | Data passed / responsibility |
| --- | --- | --- |
| Initialize/authenticate | [App.load / login](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/frontend/src/App.tsx#L97); [session / login](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/backend/matching/views.py#L37) | GET session supplies CSRF and provider state; login establishes the session; jobs and existing reports reload. |
| Capture and submit | [form events](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/frontend/src/App.tsx#L243); [analyze](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/frontend/src/App.tsx#L179) | State → selected text/file + weighted requirements; file bytes and extension participate in retry identity. |
| Send HTTP | [api](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/frontend/src/api.ts#L34); [nginx /api/](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/frontend/nginx.conf#L35) | CSRF header, same-origin cookie and UUID key → proxy to api:8000; ten-second browser deadline. |
| Identify and route | [middleware order](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/backend/config/settings.py#L14); [RequestMetadataMiddleware](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/backend/matching/middleware.py#L14); [URL patterns](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/backend/config/urls.py#L4) | Server request UUID, body cap, session/CSRF/auth middleware → /api/jobs/ view; response is no-store. |
| Normalize input | [read_match_form](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/backend/matching/views.py#L92); [read_resume](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/backend/matching/services.py#L34); [read_requirements](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/backend/matching/services.py#L92) | Multipart text or bounded selectable PDF/TXT → normalized source and explicit unique skill/weight pairs. |
| Admit once | [jobs](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/backend/matching/views.py#L142); [Job / OutboxEvent](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/backend/matching/models.py#L28) | Owner lock + key/fingerprint + quota → atomic job/outbox commit → 202 receipt. |
| Relay UUID | [relay command](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/backend/matching/management/commands/relay_jobs.py#L16); [relay_once / publish_job](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/backend/matching/jobs.py#L142); [queue declaration](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/backend/config/celery.py#L11) | Unsent outbox → confirmed persistent message on resume.match → sent marker. |
| Claim work | [process_job](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/backend/matching/tasks.py#L7); [run_job](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/backend/matching/jobs.py#L89); [claim_job](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/backend/matching/jobs.py#L45) | UUID → stored job; short row lock establishes running state, attempt and expiring lease token. |
| Extract and verify | [extract_evidence](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/backend/matching/services.py#L138); [validate_evidence](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/backend/matching/services.py#L172) | Untrusted proposed quotes → checked source excerpts and literal skill mentions. |
| Commit result | [finish_job](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/backend/matching/jobs.py#L65) | Current unexpired lease → weighted score, unique Match + succeeded Job + cleared source, in one transaction. |
| Read durable state | [jobs GET](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/backend/matching/views.py#L145); [serialize_job](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/backend/matching/views.py#L132) | Owner-scoped collection query → statuses and nested completed matches; detail GET is also available. |
| Render | [poll effect](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/frontend/src/App.tsx#L115); [selected result](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/frontend/src/App.tsx#L61); [MatchResult](https://github.com/junrillg/resume-match-bedrock/blob/d845dcad742087943295c3f37d556b1be53945b8/frontend/src/App.tsx#L22) | GET collection → React job state → selected nested match → score and quotations. |

The initial `Idempotency-Key`, server `request_id`, and durable `job_id` have different
roles: deduplicate admission, correlate the accepted request, and identify business work.
Each later HTTP status check has its own header request ID; the job payload retains its
original request ID. Queue messages contain the job ID, never document content.

</details>

## Document and evidence boundary

[`backend/matching/services.py`](../backend/matching/services.py) bounds document
normalization, validates explicit skill/weight requirements, obtains proposed evidence,
checks source membership and skill boundaries, then calculates weighted literal coverage.
[`backend/matching/tests.py`](../backend/matching/tests.py) covers input, scoring and
mocked provider contracts. Forged quotes and SQL extracted only from MySQL are rejected.
The synthetic Python/Django/React sample scores 80% against the default four requirements.

Selectable-text PDF and UTF-8 TXT uploads are limited to 1 MiB; pasted/extracted text
to 30,000 characters. OCR and DOCX are unsupported. Requirements are 1–20 unique skills
with integer weights from 1–10. Scores do not infer aliases, competence, experience
duration, negation or document truth; each quote still needs human review.

Source text is temporarily stored while queued/running and cleared on success/failure
or removed on deletion. Evidence excerpts remain until result deletion. Clearing live
rows does not erase historical backups. See [ADR 0002](decisions/0002-evidence-and-data-boundaries.md).

<details>
<summary>Bedrock activation boundary — disabled locally</summary>

Compose uses the local literal extractor and mounts no AWS credentials. The Bedrock
adapter is verified with mocked SDK responses; live account access and model behavior
remain unverified. Application code owns evidence validation and the score.

A later authorized integration needs an approved account, region, Converse model and
spend limit, server-side worker credentials, matching API/worker provider configuration,
and resource-scoped `bedrock:InvokeModel` permission. Review model support, cross-region
inference and invocation logging first. Credentials never belong in browser code,
Git or command arguments. Timeouts, attempts and tokens are bounded; provider failures
never fall back to a demo score.

</details>

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

## Asynchronous jobs API

Session cookies, CSRF and owner-scoped access apply throughout. New comparisons use
jobs; the matches API retains read/delete access to existing reports and rejects POST.

| Endpoint | Contract |
| --- | --- |
| `POST /api/jobs/` | Multipart résumé/requirements form plus UUID `Idempotency-Key`; returns 202 and the durable job. |
| `GET /api/jobs/` | The current owner's latest 100 jobs. |
| `GET /api/jobs/<id>/` | State, attempts, safe error code and completed match when available. |
| `DELETE /api/jobs/<id>/` | Removes the owned job and result. |

Identical owner/key/normalized payload returns the same job without another quota
charge. Reusing a key with different input returns 409. Admission allows 20 new logical
jobs per owner per UTC day. States are queued, running, succeeded and failed; acceptance
is not completion. Saved-report history is limited to the latest 100 results.

<details>
<summary>Rejected input and uncertain responses</summary>

- `400`: malformed form, key or bounded document/requirements validation failure.
- `401` / `403`: missing session or failed CSRF; the UI clears account state on 401.
- `409`: an existing idempotency key was reused with different normalized input.
- `413`: nginx or middleware rejects a body beyond its total request limit.
- `429`: the daily admission quota is exhausted.
- Browser timeout, network failure or ambiguous server response: manual retry of unchanged
  input retains its key. A failed GET pauses status updates without failing the job;
  the explicit resume action restarts polling.

</details>

## Delivery, processing and recovery

[`jobs.py`](../backend/matching/jobs.py) publishes UUID-only persistent messages to a
declared durable queue and marks the outbox sent after publisher confirmation. The
[`relay command`](../backend/matching/management/commands/relay_jobs.py) drives dispatch
and reconciliation. [`tasks.py`](../backend/matching/tasks.py) and
[`Celery configuration`](../backend/config/celery.py) connect worker delivery to the
business job lifecycle.

A worker claims under a short locked transaction, extracts outside the transaction and
finishes only with a current lease token. Recovery handles expired leases and stale
queued wakeups within three claims, 2/4-second retry backoff and a ten-minute total
deadline. Leases last 90 seconds. Duplicate or stale completion cannot create a second
committed result. This guarantee does not prevent repeated external provider calls or charges. PostgreSQL concurrency tests cover these boundaries;
SQLite alone cannot demonstrate row-lock behavior. No Redis, result backend, Beat or
Celery retry state is required; PostgreSQL owns the lifecycle.

<details>
<summary>Reproduce broker and worker interruption</summary>

For a local synthetic worker interruption, run `docker compose stop worker`, submit
the synthetic sample and observe queued state, then run `docker compose start worker`.
Restore it within the job deadline and verify one completed result. For a broker
interruption, run `docker compose stop broker`, submit a new sample, then run
`docker compose start broker`. Admission should return 202 while the relay retains
unsent dispatch intent. Verify final state and attempt count after recovery.
These commands affect this repository's Compose project; keep its volumes and avoid
unrelated containers. The [failure sequence](architecture.md#failure-and-recovery)
explains the persisted state at each boundary.

</details>

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
failure behavior. PostgreSQL remains the business ledger; logs are best-effort diagnostics,
not a distributed trace or durable audit ledger.

### Search one job across services

Open <http://127.0.0.1:5080> with the viewer login shown by `./scripts/lab credentials`
in your private terminal. Select organization `default`, stream `resume_match` and a
time range covering the submission. Enable SQL mode and paste the request ID from the UI:

```sql
SELECT * FROM "resume_match"
WHERE request_id = 'PASTE_REQUEST_UUID'
ORDER BY _timestamp ASC
```

Alternatively, use `WHERE job_id = 'PASTE_JOB_UUID'` with the job ID shown in the UI.
The accepted job's original request ID connects API, relay and worker events; a poll
request's HTTP `X-Request-ID` identifies that separate GET. Cross-process arrival order
can differ, and best-effort export can omit events.

<details>
<summary>Lifecycle events and safe failure categories</summary>

| Event | Emitting boundary |
| --- | --- |
| `job.accepted` | API, after the admission transaction commits |
| `job.published` / `job.publish_failed` | Relay, confirmed send or publication failure |
| `job.started` | Worker, after acquiring a claim |
| `job.succeeded` / `job.retry` / `job.failed` | Worker completion transaction, emitted on commit |
| `job.recovered` | Relay recovery transaction, emitted on commit |
| `job.interrupted` | Task wrapper, unexpected interruption |

Allowed attributes are UUID `request_id`/`job_id`, enum `stage`/`status`/`error_code`,
integer `attempt` (0–3), `duration_ms` (0–600000), and `service_name` (api/relay/worker, otherwise unknown).
An event may omit attributes. The HTTP request summary is separate stdout metadata;
arbitrary access/application logs are not forwarded to OpenObserve.

Stable error categories are `invalid_evidence`, `provider_rejected`, `processing_failed`,
`retry_exhausted`, `deadline_exceeded`, `provider_unavailable` and `publish_unavailable`.
Transient provider failures can return the job to queued; invalid evidence fails without
a demo fallback. See [run_job / finish_job](../backend/matching/jobs.py),
[recovery](../backend/matching/jobs.py) and [telemetry allowlists](../backend/matching/telemetry.py).

</details>

[Search screenshot](assets/log-search.png).

<details>
<summary>Export limits, retention and viewer outage</summary>

The exporter uses a 256-record queue, batches of 32, a one-second schedule and a
0.5-second HTTP timeout. It never flushes or waits in the business path. Events can be
lost on buffer overflow, viewer outage or process exit; stdout remains a fallback.
For a synthetic outage check, stop the viewer with `docker compose stop openobserve`,
submit a comparison and verify completion, then restore it with `docker compose start openobserve`.

OpenObserve OSS v1.1.1 is pinned by digest and runs nonroot with a static HTTP health
probe, 1 GiB container limit, 64/16 MiB memtable/in-memory file limits, 256 MiB query pool
and disabled caches. Three-day retention is checked hourly with a 120-minute file-delete
delay; a 1024 MiB free-space circuit breaker protects disk. This is not a hard byte quota
on its named volume. Startup adds a missing viewer password atomically while preserving
existing secrets and owner-only `.env` permissions. [ADR 0004](decisions/0004-searchable-observability.md)
records the image digest, implementation rationale and trade-offs.

</details>

## Verification commands

```sh
./scripts/lab test
docker compose exec -T api python manage.py check
docker compose exec -T api python manage.py makemigrations --check --dry-run
```

Frontend unit/build checks require local Node.js 22.12+ and npm. They complement the
complete Compose runtime check:

```sh
cd frontend
npm ci
npm test
npm run build
```

## Verified local behavior

The recorded verification covers 62 backend tests on Compose PostgreSQL, 15 frontend
tests, the TypeScript/Vite production build and three startup-helper checks. Backend
coverage includes input/scoring boundaries, owner isolation, CSRF, provider contracts,
concurrent idempotent admission, duplicate workers and deletion/completion fencing.

<details>
<summary>Runtime, recovery and observability evidence</summary>

- All seven services passed health checks. The nginx/session smoke check covered CSRF
  rejection, login, the synthetic 80% match, saved history and deletion.
- Real-broker checks covered queued work with the worker paused, HTTP 202 during broker
  outage, durable messages surviving broker restart and completion after worker restart.
  Completed jobs held one result and cleared temporary source text.
- OpenObserve returned eight complete lifecycle records across API, relay and worker,
  without document or credential fields. With the viewer stopped, admission took
  0.057 seconds and the worker completed an 80% comparison in 1.643 seconds.
- An isolated Compose project with fresh volumes started through `lab up`, processed its
  first 80% job and exported four searchable events. Only its temporary volumes were
  removed; the original stack and history were restored.
- Chrome checks confirmed the 80% sample on desktop and a mobile viewport.
  [Evidence report screenshot](assets/workbench.png).

These are observations from local checks, not throughput benchmarks or production SLAs.

</details>

Live Bedrock access and model accuracy remain unverified. The single-node deployment
does not establish capacity or high availability. The [broader deployment discussion](architecture.md#what-a-broader-deployment-would-add)
covers SSO/RBAC, organization isolation, TLS/network protections, retention and backups,
abuse controls, alerts and model evaluation still needed for production.

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
