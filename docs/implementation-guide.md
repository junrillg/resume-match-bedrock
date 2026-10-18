# Implementation reference

Use this reference for source, API and operating contracts. The [architecture](architecture.md) carries the numbered end-to-end flow; the [document lifecycle](document-lifecycle.md) explains original/record boundaries and recovery. All runtime examples use synthetic documents.

## Runtime and entry point

`./scripts/lab up` builds and starts React/nginx, Django, PostgreSQL, persistent SeaweedFS S3 storage, ClamAV, the relay, RabbitMQ, Celery worker, HTTP Converse provider, OpenObserve, Flower, pgAdmin and SeaweedFS admin. Initialization creates private local storage identities/bucket and applies migrations before admission. `./scripts/lab down` stops the project while retaining its database, object, scanner-definition, broker and viewer volumes.

| Artifact | Responsibility |
| --- | --- |
| [`compose.yaml`](../compose.yaml) and [`scripts/lab`](../scripts/lab) | Startup, resource/health checks, local secrets, sample runtime and test commands |
| [`storage/start.sh`](../storage/start.sh) / [`backend/init_storage.py`](../backend/init_storage.py) | Private S3-compatible identities, storage startup and bucket initialization |
| [`backend/init_viewers.py`](../backend/init_viewers.py) / [`viewing/`](../viewing/) | Dedicated inspection roles, private connection files and read-only viewer configuration |
| [`backend/Dockerfile`](../backend/Dockerfile) / [`frontend/Dockerfile`](../frontend/Dockerfile) | Pinned application build/runtime |
| [`frontend/nginx.conf`](../frontend/nginx.conf) | Same-origin API proxy; Docker DNS locally, task-local upstream on ECS |
| [`infra/terraform/`](../infra/terraform/README.md) | Separate AWS resources and reviewed release/bootstrap process |

The app is <http://127.0.0.1:8088>; OpenObserve is <http://127.0.0.1:5080>. Run `./scripts/lab credentials` in a private terminal. Ignored owner-only `.env` stores generated local credentials; preserve it with initialized volumes. Local HTTP/debug and single-node services must remain restricted to synthetic data. Native object, database, scanner and AMQP ports stay inside Compose; authenticated HTTP viewers are separate loopback endpoints. Allow at least 8 GiB for Docker; the private scanner reserves 4 GiB, needs initial definition downloads and uses AMD64 emulation on ARM64.

## Service inspection

`./scripts/lab up` starts every viewer with the business services. Run
`./scripts/lab credentials` only in a private terminal for the generated passwords.
The ignored owner-only `.env` preserves each separate login; do not replace it while
retaining initialized volumes. No password belongs in a URL or published screenshot.

| Surface | Entry and login | Interpretation / boundary |
| --- | --- | --- |
| Application/API | <http://127.0.0.1:8088>, user `lab`; browser Network panel for API calls | Owner-visible document, comparison and report state |
| RabbitMQ Management | <http://127.0.0.1:15672/#/queues>, user `lab_monitor` | Queue `resume.match.quorum`; ready versus unacknowledged messages, consumers and rates. Monitoring role has no queue/exchange configure, read or write permission. |
| Flower | <http://127.0.0.1:5555/tasks>, user `viewer` | Event-based task lifecycle and worker heartbeat. Read-only UI and event-scoped broker account; no business-queue read/control permission. |
| pgAdmin | <http://127.0.0.1:5050>, email `lab@example.invalid` | Preconfigured **Resume Match (read only)** connection as `lab_viewer`; SELECT only on `matching_document`, `matching_job`, `matching_outboxevent`, `matching_match`. It can read all owners' rows in those tables, including synthetic source/results; it is an operator account, not application tenancy. |
| SeaweedFS admin | <http://127.0.0.1:23646/files?path=/buckets/resume-originals>, user `viewer` | Read-only cluster/filer access. Raw/quarantined files can be read or downloaded outside the application's clean-only owner checks; synthetic-only privileged operator boundary. |
| OpenObserve | <http://127.0.0.1:5080>, email `lab@example.invalid` | Search `resume_match` by request/job/document UUID; service `api`, `relay`, `worker`, `provider` and lifecycle body explain the application outcome. |
| ClamAV | `docker compose exec scanner clamdtop` | Supported terminal dashboard for daemon queue/memory/signature state; `q` quits. The unauthenticated daemon socket is not published. |
| Relay / local provider | OpenObserve; `./scripts/lab status` for heartbeat/health | Custom processes have no independent vendor GUI. Inspect dispatch/provider events beside the durable job; provider health is not a real Bedrock invocation. |
| Initialization | `./scripts/lab status` | Completed migrations/storage/viewer initialization are prerequisites, not permanent dashboards. |

Flower 2.2.0 and the worker both use Celery 5.6.3. Explicit worker/send events feed
Flower; no result backend was added. Celery remote control stays disabled, so detailed
worker inspectors and administrative controls are unavailable. Task history is bounded
to 1,000 in-memory records and is lost when Flower restarts.

Each delivery has a **Celery task UUID**, while its single argument contains the
**application job UUID**. A relay retry can create another task UUID for the same job.
The wrapper returns safely after application-owned rejection or retry handling;
Flower can therefore show `SUCCESS` for a failed comparison. PostgreSQL job state and
OpenObserve lifecycle events establish the business outcome. Neither queue confirmation
nor a green transport task proves that a report exists.

Only HTTP viewer ports are published on loopback. SeaweedFS admin's otherwise
unauthenticated gRPC listener stays on container loopback `127.0.0.1:33646`.
Additional viewers used about **337 MiB** after the checked workload; the running
stack used about **2.38 GiB** at that point. These are local snapshots, not capacity
requirements or guarantees; retain the stated Docker minimum and scanner allowance.

### Inspection evidence — 2026-10-18

Runtime configuration and focused checks passed: 13 long-running services healthy;
authenticated/unauthenticated access boundaries; RabbitMQ topology mutations denied;
PostgreSQL SELECT restricted to four matching tables with auth/session reads,
business UPDATE and schema CREATE denied even after disabling the session read-only
default; SeaweedFS authenticated access, delete rejection and private gRPC binding.
Ten focused checks cover startup/secret preservation, viewer drift and task-exception
privacy. They do not replace populated browser-interface observations.

Real queued work completed with separate task/job identities. A one-requirement
synthetic comparison succeeded at 100%; an EICAR source was rejected by the document
gate while its Celery task still showed `SUCCESS`. OpenObserve browser search found
eight success events across four services and five events for the rejection. The
application's default synthetic comparison returned **80%** with pgAdmin stopped;
pgAdmin was restored and all 13 services returned healthy. This checks one viewer
outage, not every possible viewer failure mode.

The live `clamdtop` terminal connected to `/tmp/clamd.sock`, displayed engine 1.5.4,
signature database revision 28156 dated 2026-10-17 and an empty scan queue, then exited cleanly.
Authenticated browser review verified Flower's task/job identity mapping for the
80% sample and rejected source, and SeaweedFS inventory for retained originals with
matching document IDs and byte sizes. The rejected source had already been removed;
quarantined-file visibility is a source-established privilege, not an observed file.
RabbitMQ showed three ready deliveries, zero unacknowledged and zero consumers with
the worker held; after restoration it showed zero ready/unacknowledged/total and
one consumer, and the comparison completed at 80%. Ready delivery counts can include
relay duplicates and do not count unique application jobs.

Populated GUI review exposed two configuration gaps beyond health/API checks:
RabbitMQ's base image disabled the management metrics collector; explicit local
configuration now enables it. pgAdmin 9.17 ignored the old top-level `PassFile`;
registration now uses supported `ConnectionParameters.passfile`, with a targeted
repair of its generated saved connection. Passwords and unrelated registrations
were preserved. One focused regression check passed for the pgAdmin import and
private password-file contract; direct password-file authentication also passed.
**Pending:** pgAdmin's final authenticated connection and populated record view.
Direct database checks do not close the browser gate.

## Source handoffs

<details>
<summary>Commit-pinned implementation map</summary>

| Step | Source / receiver | Contract |
| --- | --- | --- |
| 1 UI input and submit | [App.tsx: analyze / source controls](https://github.com/junrillg/resume-match-bedrock/blob/d290381664ebe3e62532d6756d5989af472972ca/frontend/src/App.tsx) | Selected original or saved ID, requirements and retry identity |
| 1 HTTP boundary | [api.ts: api / downloadDocument](https://github.com/junrillg/resume-match-bedrock/blob/d290381664ebe3e62532d6756d5989af472972ca/frontend/src/api.ts) · `frontend/nginx.conf` | Same-origin session/CSRF, UUID Idempotency-Key and bounded request timeout |
| 2 Routing/access | `backend/config/urls.py` · `matching/middleware.py` · `config/settings.py` | Request metadata/body cap, session and CSRF before owner-scoped handlers |
| 2 Input/reservation | [views.py: read_match_form / admit_jobs](https://github.com/junrillg/resume-match-bedrock/blob/4c8e18a5c544e142a604336c1c47cf415e90818e/backend/matching/views.py) | Owner lock, exact-byte/type fingerprint, quota, upload reservation and finalization |
| 2 Original PUT | [documents.py: read_source / put_original](https://github.com/junrillg/resume-match-bedrock/blob/4c8e18a5c544e142a604336c1c47cf415e90818e/backend/matching/documents.py#L54) | Generated key, bounded bytes, Content-MD5, successful PUT acknowledgment; no unclean HEAD bypass |
| 3–4 Dispatch | [jobs.py: relay_once / publish_job](https://github.com/junrillg/resume-match-bedrock/blob/4c8e18a5c544e142a604336c1c47cf415e90818e/backend/matching/jobs.py) · `config/celery.py` | Committed outbox → persistent UUID → publisher confirmation |
| 5 Claim/source | [jobs.py: claim_job / run_job](https://github.com/junrillg/resume-match-bedrock/blob/4c8e18a5c544e142a604336c1c47cf415e90818e/backend/matching/jobs.py) · [documents.py: document_text / get_original / cloud_scan / scan_bytes](https://github.com/junrillg/resume-match-bedrock/blob/4c8e18a5c544e142a604336c1c47cf415e90818e/backend/matching/documents.py#L146) | Lease → owned/unexpired source → checksum/safety gate → parse or matching cache |
| 5 Evidence | [services.py: extract_evidence / bedrock_request](https://github.com/junrillg/resume-match-bedrock/blob/4c8e18a5c544e142a604336c1c47cf415e90818e/backend/matching/services.py) · `backend/local_converse.py` | Source/skills to Converse, proposed evidence back; schema/quote validation remains application-owned |
| 6 Result | [jobs.py: finish_job](https://github.com/junrillg/resume-match-bedrock/blob/4c8e18a5c544e142a604336c1c47cf415e90818e/backend/matching/jobs.py) · `models.py: Match` | Document then job locks, live lease, deterministic score and one report |
| 7 Poll/render | [App.tsx: polling / MatchResult](https://github.com/junrillg/resume-match-bedrock/blob/d290381664ebe3e62532d6756d5989af472972ca/frontend/src/App.tsx) · `views.py: jobs / serialize_job` | Owner collection with nested report; terminal/error handling |
| Source operations | `views.py: documents / document_download / document_detail` · `documents.py: tombstone / reconcile_documents` | List, clean attachment retrieval, immediate access fencing and retried cleanup |
| Diagnostics | [telemetry.py: emit](https://github.com/junrillg/resume-match-bedrock/blob/4c8e18a5c544e142a604336c1c47cf415e90818e/backend/matching/telemetry.py) | Fixed event body and allowlisted safe attributes |

</details>

## Document and evidence boundary

PDF/TXT uploads are capped at 1 MiB; PDFs at ten pages and extracted text at 30,000 characters. TXT uses UTF-8. Pasted input becomes a retained UTF-8 source snapshot. No OCR/DOCX support is implied. Media checks precede storage; selectable-text parsing follows the malware gate in the worker. Extraction cache is keyed by the parser version; each comparison still retrieves and verifies stored source.

The local object client refuses an absent explicit endpoint in debug mode, preventing accidental cloud discovery when local storage configuration is incomplete.

The provider proposes source quotes for explicit weighted skills. Application code validates structured output, quote occurrence and bounded skill mentions before calculating matched weight / total weight. Literal provenance does not prove competence, positive experience, truth or fairness. Document text is untrusted data; separating system instructions alone does not guarantee injection resistance.

Compose selects `MATCH_PROVIDER=bedrock-local`, an explicit local endpoint and deterministic model contract. The actual boto3 Converse operation reaches a separate HTTP service; this checks request/response handling, not an LLM or AWS IAM. AWS uses the selected Bedrock model and worker role through PrivateLink. Provider errors never fall back to an invented score.

## Admission and API

New uploads reserve document/job identity before PUT, then finalize the document and queued job/outbox under locks. That final PostgreSQL transaction is atomic; the object PUT is not part of it. Same owner/key/input recovers the logical job and charges quota once. Fingerprints include source bytes/type, requirements and title, or saved document ID/reprocess intent. Conflicting input returns 409.

| Endpoint | Contract |
| --- | --- |
| `POST /api/jobs/` | Multipart original or saved `document_id`, requirements, UUID key; saved IDs may use `reprocess=true`; 202 with job/document state |
| `GET /api/jobs/` | Owner's latest 100 jobs, document identity and optional saved report |
| `GET /api/jobs/<id>/` | Owned state/attempts/safe error/report |
| `DELETE /api/jobs/<id>/` | Delete comparison/result; established reusable source remains |
| `GET /api/documents/` | Owner's latest 100 unexpired documents and lifecycle metadata |
| `GET /api/documents/<id>/download/` | Ready, owned, unexpired and safety-verified bytes as no-store attachment |
| `DELETE /api/documents/<id>/` | 202 tombstone; remove access/results immediately, retry object cleanup |

A `202 uploading` concurrent replay confirms only a reservation: no outbox exists and storage may be incomplete. Retry the same original/key after interruption; a poll alone cannot resupply missing bytes. A new upload's finalized `202 queued` confirms successful PUT and committed dispatch intent. States include uploading, queued, running, succeeded and failed; 202 never promises a completed result. Cancelling an unfinished initial upload leads to cleanup rather than retaining an unready orphan.

Authentication, CSRF, owner and body/type limits apply throughout. Safe rejection statuses include 400 validation, 401 authentication, 403 CSRF, 404 unavailable/other-owner resource, 409 conflicting input or safety rejection, 413 body cap, 429 quota and 503 unavailable admission/storage/safety verification. Failed GET/polling pauses UI updates without failing the job.

## Delivery, processing and recovery

PostgreSQL owns jobs, outbox, leases and results. The relay publishes UUID-only persistent wakeups to `resume.match.quorum` and marks dispatch sent after broker confirmation. Redelivery is expected. Three provider claims, a ten-minute job deadline, 90-second leases and bounded retry backoff prevent endless work; lease-fenced completion permits one committed result. The pending cloud scan path requeues without consuming provider attempts, still bounded by the job deadline.

`reconcile_documents` expires abandoned one-hour uploads, tombstones policy-expired sources, retries object deletion and clears derived state. Late upload completion restores deletion intent; document-first completion locks prevent deleted/expired work from recreating results. Cleanup tombstones remain seven days before removal. Legacy source-cleared records remain readable with source unavailable and receive finite cleanup policy.

<details>
<summary>Focused local interruption checks</summary>

Stop only this Compose project's `worker` or `broker`, submit synthetic work, restore the service within its deadline and check one saved result. Stop `objectstore` or `scanner` to observe source-unavailable/scan failure without provider bypass, then restore it. Use new synthetic work after terminal exhaustion; retained admission identity does not restart a terminal job. Ordinary `down`/`up` retains originals and database state. Preserve existing volumes and credentials; never use destructive volume removal as a restart command.

</details>

## Browser state and isolation

The UI sends only the selected source, polls one request at a time and clears private state on logout/authentication loss. Unchanged input retains its retry key after ambiguity; changed input gets a new key. Owner source selection, authorized download, reprocess and document-delete actions share the backend lifecycle contract. Download is an attachment; it does not expose public objects or signed URLs. Deleting a document removes related comparisons; deleting an established comparison keeps its source.

The document-aware UI passed 29 focused frontend tests and the production build. Checks cover saved-source/reprocess request identity, uploading-state recovery, source deletion, download safety/authentication failures, polling and stale-response isolation.

## Correlated operational logs

`telemetry.emit` uses an event name as the OTLP **body**, with UUID request/job/document IDs and allowlisted service, stage, status, attempt, duration and safe error category. OpenObserve stores that name in `body`; stdout JSON uses `event`. Application logs exclude résumé content, quotes, prompts, filenames, object keys, signed URLs, usernames, credentials and raw exceptions. Telemetry export is bounded/background and cannot decide business success.

### Search one job across services

Open <http://127.0.0.1:5080> using the viewer login from `./scripts/lab credentials` in your private terminal. Select organization `default`, stream `resume_match`, the submission time range and SQL mode:

```sql
SELECT * FROM "resume_match"
WHERE request_id = 'PASTE_REQUEST_UUID'
ORDER BY _timestamp ASC
```

Alternatively filter by `job_id = 'PASTE_JOB_UUID'`. The admission request ID connects API, relay, worker and provider; a poll's X-Request-ID belongs to that separate GET. Look at the `body` column for lifecycle names. Verified records included `job.accepted`, `job.published`, `job.started`, `document.ready`, `provider.requested`, `provider.completed`, `provider.responded` and `job.succeeded` across four services. Arrival order can differ and export can lose events. PostgreSQL remains the business ledger.

<details>
<summary>Document events and telemetry limits</summary>

`document.ready` marks validated extraction/safety; `document.rejected` records a source rejection. `document.delete_requested`, `document.delete_pending` and `document.deleted` expose access fencing and cleanup progress. Some events lack request/job IDs; document UUID remains available where emitted. These events contain no source data.

The OTLP exporter buffers 256 records in batches of 32, schedules every second and uses a 0.5-second HTTP timeout. Viewer outage, overflow or process exit can lose logs; stdout is a fallback, not a durable audit ledger. Stop/restore `openobserve` with synthetic work to inspect business-path independence. Local retention is three days with hourly cleanup and delayed file removal; this is not a hard volume-byte quota. Configured CloudWatch log retention is 30 days. A per-job ID is a search field, not a metric label.

</details>

## Verification commands

```sh
./scripts/lab test
docker compose exec -T api python manage.py check
docker compose exec -T api python manage.py makemigrations --check --dry-run
```

Frontend checks require Node.js 22.12+ and run one at a time:

```sh
cd frontend
npm ci
npm test
npm run build
```

## Verified local behavior

The durable-document backend plus endpoint-safety fix passed **89 tests against Compose PostgreSQL**; three startup-helper tests also passed. Separate real S3-client/ClamAV and HTTP experiments exercised exact-byte upload/download, source reuse/reprocessing, infected/unavailable scanner rejection, storage outage/recovery and deletion/expiry fencing. Eight safe lifecycle events were searched across API, relay, worker and provider. These experiments complement unit mocks; they do not transform a mocked boundary test into a real service check.

The Terraform milestone passed format, backend-free initialization, validation and **eight plan-only mocked-provider runs**, including private/encrypted originals, role/tag-gate isolation, endpoint/ECR preservation, retention and ACTIVE scanner enablement. No real AWS API, provisioned service or managed failover was verified.

Desktop and 390 × 844 mobile browser checks verified an 80% report, saved-source reuse with explicit reparse, comparison deletion retaining its source, and document deletion removing related reports before eventual source cleanup. No horizontal overflow was observed. Exact-byte download is verified at the HTTP boundary; browser file persistence was not measured.

Local observations are not throughput benchmarks or SLAs. Cloud deployment, IAM enforcement, managed scan latency, restoration/failover, model quality and organization identity still require their own acceptance evidence. The seven-day RDS backup window requires restore-time deletion/expiry reconciliation before admission reopens.

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
| AWS journey design before implementation | [7104a22](https://github.com/junrillg/resume-match-bedrock/commit/7104a22) |
| Local HTTP Converse, cloud configuration and provider-aware UI | [4e9432e](https://github.com/junrillg/resume-match-bedrock/commit/4e9432e597d4d4d68cf8257110d4ca3f50cad0e4) |
| AWS Terraform and cloud bootstrap | [e2bfaa2](https://github.com/junrillg/resume-match-bedrock/commit/e2bfaa2d3302e7ea54beda759ba44d22cd05f03f) |
| Durable-original research and lifecycle decision | [f57f5fb](https://github.com/junrillg/resume-match-bedrock/commit/f57f5fb) |
| Durable originals, safety gate and recovery | [3d8066f](https://github.com/junrillg/resume-match-bedrock/commit/3d8066f2d1632e1f3415a3a983c833e89f82cf01) |
| Private S3, GuardDuty and cloud lifecycle wiring | [3c05f3f](https://github.com/junrillg/resume-match-bedrock/commit/3c05f3fc26d3c838b246eea17c02f0027b91e98f) |
| Explicit local object endpoint required | [4c8e18a](https://github.com/junrillg/resume-match-bedrock/commit/4c8e18a5c544e142a604336c1c47cf415e90818e) |
| Document-aware UI | [d290381](https://github.com/junrillg/resume-match-bedrock/commit/d290381664ebe3e62532d6756d5989af472972ca) |
| Connected inspection design | [f60d186](https://github.com/junrillg/resume-match-bedrock/commit/f60d186) |
| Connected read-only service viewers | [17ba0eb](https://github.com/junrillg/resume-match-bedrock/commit/17ba0ebb14af3852a2c2682f48d0c2e993a42bba) |
