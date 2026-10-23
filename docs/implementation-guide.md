# Implementation reference

Use this reference for source, API and operating contracts. The [architecture](architecture.md) carries the numbered end-to-end flow; the [document lifecycle](document-lifecycle.md) explains original/record boundaries and recovery. All runtime examples use synthetic documents.

## Runtime and entry point

`./scripts/lab up` builds and starts React/nginx, Django, PostgreSQL, persistent SeaweedFS S3 storage, ClamAV, the job relay, event relay, two Valkey shards, two raw ASGI gateways, RabbitMQ, Celery worker, HTTP Converse provider, OpenObserve, Flower, pgAdmin and SeaweedFS admin. Initialization creates private local storage identities/bucket and applies migrations before admission. `./scripts/lab down` stops the project while retaining its database, object, scanner-definition, broker and viewer volumes.

| Artifact | Responsibility |
| --- | --- |
| [`Makefile`](../Makefile), [`compose.yaml`](../compose.yaml) and [`scripts/lab`](../scripts/lab) | Startup, resource/health checks, local secrets, sample runtime and test commands |
| [`storage/start.sh`](../storage/start.sh) / [`backend/init_storage.py`](../backend/init_storage.py) | Private S3-compatible identities, storage startup and bucket initialization |
| [`backend/init_viewers.py`](../backend/init_viewers.py) / [`viewing/`](../viewing/) | Dedicated inspection roles, private connection files and read-only viewer configuration |
| [`backend/Dockerfile`](../backend/Dockerfile) / [`frontend/Dockerfile`](../frontend/Dockerfile) | Pinned application build/runtime |
| [`frontend/nginx.conf`](../frontend/nginx.conf) | Same-origin API and unbuffered stream proxy locally; exact ALB stream routing on ECS |
| [`infra/terraform/`](../infra/terraform/README.md) | Separate AWS resources and reviewed release/bootstrap process |

The app is <http://127.0.0.1:8088>; OpenObserve is <http://127.0.0.1:5080>. Run `make credentials` in a private terminal. Ignored owner-only `.env` stores generated local credentials; preserve it with initialized volumes. Local HTTP/debug and single-node services must remain restricted to synthetic data. Native object, database, scanner and AMQP ports stay inside Compose; authenticated HTTP viewers are separate loopback endpoints. Allow at least 8 GiB for Docker; the private scanner reserves 4 GiB, needs initial definition downloads and uses AMD64 emulation on ARM64.

## Service inspection

`./scripts/lab up` starts every viewer with the business services. Run
`make credentials` only in a private terminal for the generated passwords.
The ignored owner-only `.env` preserves each separate login; do not replace it while
retaining initialized volumes. No password belongs in a URL or published screenshot.

| Surface | Entry and login | Interpretation / boundary |
| --- | --- | --- |
| Application/API | <http://127.0.0.1:8088>, user `lab`; browser Network panel for API calls | Owner-visible documents, processing/results routes and persisted completion inbox |
| RabbitMQ Management | <http://127.0.0.1:15672/#/queues>, user `lab_monitor` | Queue `resume.match.quorum`; ready versus unacknowledged messages, consumers and rates. Monitoring role has no queue/exchange configure, read or write permission. |
| Flower | <http://127.0.0.1:5555/tasks>, user `viewer` | Event-based task lifecycle and worker heartbeat. Read-only UI and event-scoped broker account; no business-queue read/control permission. |
| pgAdmin | <http://127.0.0.1:5050>, email `lab@example.invalid` | Preconfigured **Resume Match (read only)** connection as `lab_viewer`; SELECT only on `matching_document`, `matching_job`, `matching_outboxevent`, `matching_match`, `matching_completionnotification`, `matching_streamstate`, `matching_streamevent`. It can read all owners' rows in those tables, including synthetic source/results; it is an operator account, not application tenancy. |
| Fan-out viewer | <http://127.0.0.1:8089>, generated separate GUI login | Read-only connections to both independent Valkey shards; owner wakes/leases, not documents or saved results. |
| SeaweedFS admin | <http://127.0.0.1:23646/files?path=/buckets/resume-originals>, user `viewer` | Read-only cluster/filer access. Raw/quarantined files can be read or downloaded outside the application's clean-only owner checks; synthetic-only privileged operator boundary. |
| OpenObserve | <http://127.0.0.1:5080>, email `lab@example.invalid` | Search `resume_match` by request/job/document UUID; services `api`, `relay`, `worker`, `provider`, `event-relay`, `gateway` and lifecycle body explain the application outcome. |
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
PostgreSQL SELECT restricted to the then-current four matching tables with auth/session reads,
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

## AWS database identities

The deployment separates application, streaming and bootstrap authority. Compose development processes share the configured runtime PostgreSQL login; its separate seven-table inspection account remains read-only.

| Identity | Path and authority |
| --- | --- |
| Application | API, worker and relays use the read/write application login through RDS Proxy; no schema ownership or DDL |
| Stream gateway | Separate proxy login; SELECT only on `auth_user`, `django_session`, `matching_streamstate`, `matching_streamevent`; no source/report reads |
| Bootstrap | Direct privileged RDS connection; guarded transition to a nonlogin migration owner, preserving adopted application credentials |
| Local inspection counterpart | Separate seven-table read-only viewer, with cross-owner synthetic operator access; never an application account |

Role defaults provide UTC and finite SQL/lock timeouts. Proxy TLS uses the Amazon Trust Services chain; direct bootstrap uses the RDS CA bundle. Avoiding unnecessary session settings supports pooling, but real cloud pinning/borrow latency still needs measurement. [Deployment contract](../infra/terraform/README.md)

## Source handoffs

<details>
<summary>Commit-pinned implementation map</summary>

| Step | Exact source at verified runtime commit | Contract |
| --- | --- | --- |
| 1 Submit | [analyze → API client](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/frontend/src/App.tsx#L361) | Original/saved ID, requirements and unchanged retry identity |
| 1 HTTP | [api](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/frontend/src/api.ts) | Same-origin session/CSRF and bounded timeout |
| 2 Admission | [admit_jobs](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/backend/matching/views.py#L273) | Owner-stream lock, unchanged-key recovery, reserve/PUT/finalize |
| 2 Supply | [reserve_admission](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/backend/matching/admission.py#L25) | Fair owner/global rate/active budgets, fresh queue/supply gate |
| 2 Source | [put_original](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/backend/matching/documents.py#L81) | Exact bounded bytes; database released before object I/O |
| 3–4 Dispatch | [publish_job / relay_once](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/backend/matching/jobs.py#L175) | Reused confirmed producer; UUID-only persistent delivery |
| 3 Productive loop | [relay_jobs](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/backend/matching/management/commands/relay_jobs.py) | Productive drain and separate bounded maintenance/supply sample |
| 5 Source/process | [run_job](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/backend/matching/jobs.py#L104) | Lease, source verification/safety, parser cache and external-I/O connection release |
| 5 Provider | [extract_evidence](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/backend/matching/services.py#L163) | Converse → schema/source/skill validation → weighted score |
| 6 Commit | [finish_job](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/backend/matching/jobs.py#L72) | Owner-stream → document → job fence; report, notice, revision and admission release |
| 7a–b Event publication | [record_change / relay_events](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/backend/matching/events.py#L25) | Durable owner revision then publish to stable ordered shard |
| 7c Delivery | [Gateway.__call__](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/backend/event_gateway.py#L284) | Session/origin checks; subscribe ACK then bounded replay and SSE |
| 7d Reads/routes | [apply](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/frontend/src/App.tsx#L247) | Authorized affected reads; preserve unrelated route/draft |
| 7d Stream lifecycle | [workspaceEvents](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/frontend/src/workspaceEvents.ts#L21) | One visible-tab EventSource, coalescing, bounded reads and jitter reconnect |
| Inbox | [notifications / notification_read](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/backend/matching/views.py#L209) | Signed keyset cursor and independent idempotent read receipt |
| Source lifecycle | [tombstone / reconcile_documents](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/backend/matching/documents.py#L211) | Immediate access fence, durable change and retried physical cleanup |

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
| `GET /api/jobs/?summary=true` | Latest 100 owned jobs without repeated full evidence; detail GET supplies the saved report |
| `GET /api/notifications/?cursor=` | Owner-scoped signed keyset pages of 100 notices, unread count and next cursor; legacy offset API remains compatible |
| `POST /api/notifications/<id>/read/` | Owner-scoped CSRF-protected idempotent read receipt; opening a report is separate |
| `GET /api/events/` | Authenticated owner SSE identifiers/revisions; exact separate gateway route |
| `GET /api/documents/<id>/` | Owned current document metadata |
| `GET /api/jobs/<id>/` | Owned state/attempts/safe error/report |
| `DELETE /api/jobs/<id>/` | Delete comparison/result; established reusable source remains |
| `GET /api/documents/` | Owner's latest 100 unexpired documents and lifecycle metadata |
| `GET /api/documents/<id>/download/` | Ready, owned, unexpired and safety-verified bytes as no-store attachment |
| `DELETE /api/documents/<id>/` | 202 tombstone; remove access/results immediately, retry object cleanup |

A `202 uploading` concurrent replay confirms only a reservation: no outbox exists and storage may be incomplete. Retry the same original/key after interruption; a status read cannot resupply missing bytes. A new upload's finalized `202 queued` confirms successful PUT and committed dispatch intent. States include uploading, queued, running, succeeded and failed; 202 never promises a completed result. Accepted responses include `Location: /api/jobs/<id>/` and `Retry-After: 2`; JSON supplies local processing/result destinations. Cancelling an unfinished initial upload leads to cleanup rather than retaining an unready orphan.

Authentication, CSRF, owner and body/type limits apply throughout. Safe rejection statuses include 400 validation, 401 authentication, 403 CSRF, 404 unavailable/other-owner resource, 409 conflicting input or safety rejection, 413 body cap, 429 owner/rate/day budget and 503 unavailable admission/storage/safety verification. Failed status reads do not fail durable work; resource batches retry at most twice, then expose deliberate recovery. A new stream subscription reconciles saved state.

## Delivery, processing and recovery

PostgreSQL owns jobs, outbox, leases, results and completion notifications. The relay publishes UUID-only persistent wakeups to `resume.match.quorum` and marks dispatch sent after broker confirmation. Redelivery is expected. Three provider claims, a ten-minute job deadline, 90-second leases and bounded retry backoff prevent endless work; lease-fenced completion permits one committed result. The pending cloud scan path requeues without consuming provider attempts, still bounded by the job deadline.

`reconcile_documents` expires abandoned one-hour uploads, tombstones policy-expired sources, retries object deletion and clears derived state. Late upload completion restores deletion intent; owner-stream → document → job completion locks prevent deleted/expired work from recreating results. Cleanup tombstones remain seven days before removal. Legacy source-cleared records remain readable with source unavailable and receive finite cleanup policy.

<details>
<summary>Focused local interruption checks</summary>

Stop only this Compose project's `worker` or `broker`, submit synthetic work, restore the service within its deadline and check one saved result. Stop `objectstore` or `scanner` to observe source-unavailable/scan failure without provider bypass, then restore it. Use new synthetic work after terminal exhaustion; retained admission identity does not restart a terminal job. Ordinary `down`/`up` retains originals and database state. Preserve existing volumes and credentials; never use destructive volume removal as a restart command.

</details>

## Browser state and isolation

| Route | Responsibility |
| --- | --- |
| `/` | New comparison; the draft/file stays mounted across in-app navigation |
| `/jobs/<job-id>` | Independently authorized processing or safe terminal failure |
| `/results/<job-id>` | Saved report; reload resolves job detail outside recent history |
| `/notifications` | Durable completion inbox, separate Mark as read and older pages |
| `/reports/<match-id>` | Earlier reports resolved from available recent history; legacy detail GET is unsupported |

Native History API navigation uses validated UUID paths and normal links/Back. A returned admission cannot redirect after navigation. Only the same still-active processing route advances on success; unrelated drafts survive background completion. Action-specific pending state leaves navigation and sign-out available. Form drafts are memory-only and are cleared on reload or authentication loss.

One visible authenticated tab holds one EventSource. Subscription acknowledgement precedes the initial/reconnect snapshot: session, lean jobs, legacy-only reports, documents and first inbox page, plus current job detail when relevant. Steady-state change IDs trigger affected reads, coalesced for 100 ms with at most four targeted requests in flight. More than 256 distinct pending IDs requests a fresh snapshot; there is no recurring workspace polling timer.

Stream failure reconnects with jitter (15–30, 30–60, then 60–120 seconds), without automatic REST fallback. A failed resource batch retries twice with 30/60-second jittered delays before explicit recovery. Hidden/offline tabs close streams and abort reads; returning reconnects and reconciles. Requests time out after ten seconds. Session/navigation/deletion fences reject stale responses. Inbox pages use signed keyset cursors; returning/deletion resets older pages.

The gateway caps configured sockets (2,000/process), owner leases (five globally), shared database work (four active and 64 queued) and replay (100 events; 24-hour retention). Subscribe ACK/generation barriers close replay races. Heartbeats every 15 seconds do no SQL. Stream lifetime is jittered 720–900 seconds, so fleet rollover still creates reconciliation load. These are configured bounds, not measured per-process capacity.

Notifications share the original/job lifetime and cascade on deletion; a OneToOne job relation prevents duplicate terminal notices. No historical unread notices are backfilled. Server owner checks and CSRF protect reads/mutations. Session epochs, route revisions and explicit deletion fences prevent late responses restoring removed data or changing another route/source. An unrelated read acknowledgement cannot cancel a valid original download.

The event-driven UI passed **66 frontend tests** and the production build. An earlier paused-worker browser run verified continuing work, another submission, off-route completion without draft replacement, same-job result transition, result refresh/Back, read persistence and completion while the app tab was closed. Desktop/mobile 390×844 views passed without horizontal overflow. The completion inbox is in-app; external email/push is not implemented.

## Correlated operational logs

`telemetry.emit` uses an event name as the OTLP **body**, with UUID request/job/document/notification IDs and allowlisted service, stage, status, attempt, duration and safe error category. OpenObserve stores that name in `body`; stdout JSON uses `event`. Application logs exclude résumé content, quotes, prompts, filenames, object keys, signed URLs, usernames, credentials and raw exceptions. Telemetry export is bounded/background and cannot decide business success.

### Search one job across services

Open <http://127.0.0.1:5080> using the viewer login from `make credentials` in your private terminal. Select organization `default`, stream `resume_match`, the submission time range and SQL mode:

```sql
SELECT * FROM "resume_match"
WHERE request_id = 'PASTE_REQUEST_UUID'
ORDER BY _timestamp ASC
```

Alternatively filter `job_id = 'PASTE_JOB_UUID'`. The admission request ID joins API acceptance, job relay, worker/provider and terminal notice. REST reads and notification acknowledgement have independent request IDs. Delivery events carry job/document IDs where relevant and a durable owner revision; gateway aggregate snapshots do not provide a per-request trace. Search `body` for lifecycle names; arrival order can differ and exports can lose records. PostgreSQL remains the ledger.

| Signal | Interpretation |
| --- | --- |
| `admission.snapshot` · relay | Active/queued sample, oldest queue age and broker/worker readiness explain new-work admission pressure |
| `job.accepted / published / started / succeeded / failed` | Processing journey; `notification.persisted` joins the terminal inbox via job ID |
| `delivery.persisted / published / publish_failed` · API/worker/event-relay | Durable revision intent and wake publication; publication alone does not prove browser receipt |
| `delivery.snapshot` · event-relay | Bounded pending-event count and oldest unpublished age |
| `stream.snapshot` · gateway | Active streams, database work/queue, threads, overload/errors and event lag; heartbeat SQL remains absent |
| `notification.read` · API | Independent acknowledgement joined by job/notification IDs |

An authenticated OpenObserve API search on 2026-10-19 verified searchable ingestion over a 30-minute window: 118 gateway `stream.snapshot`, 60 event-relay `delivery.snapshot` and 572 relay `admission.snapshot` records, plus persisted/published events. These counts span separate scoped checks; they do not prove one-request correlation or a browser-layout review.

For delivery health use SQL such as `SELECT * FROM "resume_match" WHERE body IN ('delivery.snapshot', 'stream.snapshot', 'admission.snapshot') ORDER BY _timestamp DESC LIMIT 100`. Valkey inspection establishes live transport state, not application outcomes. CloudWatch's saved journey query includes API, job relay, worker, gateway and event relay log groups.

<details>
<summary>Document events and telemetry limits</summary>

`document.ready` marks validated extraction/safety; `document.rejected` records a source rejection. `document.delete_requested`, `document.delete_pending` and `document.deleted` expose access fencing and cleanup progress. Some events lack request/job IDs; document UUID remains available where emitted. These events contain no source data.

The OTLP exporter buffers 256 records in batches of 32, schedules every second and uses a 0.5-second HTTP timeout. Viewer outage, overflow or process exit can lose logs; stdout is a fallback, not a durable audit ledger. Stop/restore `openobserve` with synthetic work to inspect business-path independence. Local retention is three days with hourly cleanup and delayed file removal; this is not a hard volume-byte quota. Configured CloudWatch log retention is 30 days. A per-job ID is a search field, not a metric label.

</details>

## Verification commands

Run from the repository root after `make up`:

```sh
make test
make check-config
make check-terraform
# Or run the existing checks together, including image builds:
make verify
# Full gate: fails explicitly while required quality/security profiles are absent:
make check
```

Make delegates runtime operations to `scripts/lab` and the native Compose, Django,
Node and Terraform commands. `make help` needs no Docker daemon, `.env` or network.
Run `make credentials` only in a private terminal; never in CI or shared output.

`make test` runs the CLI boundary tests, Django suite, Vitest and isolated nginx proxy
checks sequentially. Django runs in a disposable container using the current built
image and creates a separate PostgreSQL test database; frontend
checks use the locked Node build stage in `frontend/Dockerfile`, with no host npm
installation. Proxy tests create and remove only their temporary containers/network.
The focused targets are `test-cli`, `test-backend`, `test-frontend` and `test-proxy`.
Run `make build` before focused backend/config checks after source edits;
`make verify` includes that build. Re-run `make up` to update the running application.

`make verify` sequences image builds, tests, Compose/Django configuration and migration
drift, then Terraform format/init/validate and plan-only mocked tests. Terraform 1.15.8
and registry access are required; no normal plan, apply or AWS calls are included.
`make check` additionally fails on the unconfigured formatter/linter profiles, backend
type checking and dependency/secret/source/configuration/container security scans.
These gates need a separate tooling change; existing checks cannot establish their pass.
The CI workflow runs the same `make check` after startup and preserves volumes on stop.

`make sample` exercises one disposable synthetic owner's HTTP admission, queue, worker,
local provider, saved result/inbox and SSE completion. It prints result and correlation
IDs, then deletes only its fixture originals/records. The expected score is 100%; the
UI sample is a different input with 80% coverage. Interrupting the sample can leave its
synthetic fixture pending cleanup. Fault/load scripts remain explicit operator tools;
ordinary check targets never stop storage/scanning services or run capacity loads.

`make down` removes this project's containers/network while preserving named volumes;
`make restart` restarts services and waits for readiness without volume deletion.
Preserve `.env` with those volumes. There is no destructive cleanup or cloud deployment
target. Compose environment selection is inherited; sample HTTP uses the documented
local address, so do not point it at a different project or port.

## Verified local behavior

[ADR 0009](decisions/0009-event-driven-completion.md#local-verification) records the local 1,000-owner/two-gateway delivery run, both-shard restart, durable change delivery, reconnect burst and one actual comparison through SSE to authorized result retrieval. API probe p95 was 25.6 ms; the five-second idle sample made zero gateway database requests. This does not establish million-user or 100-comparison/second capacity.

[ADR 0010](decisions/0010-bounded-deployment.md#verification) records 155 PostgreSQL regression tests, subsequent 20 admission/publishing and eight ownership/bootstrap checks, fifteen credential-free Terraform mock plans and four nginx checks. A reused producer dispatched 200 UUIDs in 0.538 seconds; an eight-thread 200-operation SQL reservation test measured 174.73 operations/second. These isolate mechanisms rather than complete model-processing throughput. The updated real comparison reached saved result/inbox through SSE and removed its original during fixture cleanup.

Earlier durable-source checks exercised exact-byte retrieval, reuse/reprocessing, infected/unavailable scanning, storage interruption, expiry/deletion fences and restart persistence. Earlier desktop/mobile checks verified route/draft preservation and original deletion, with no horizontal overflow at 390 × 844. Current public diagram/source checks do not replace a fresh hosted browser review. AWS deployment, managed failover, model quality, federation and full-scale capacity remain unmeasured. Restore-time deletion/expiry reconciliation must precede admission after the seven-day RDS backup window.

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
| Event ledger, sharded fan-out and asynchronous SSE runtime | [4cc9cee](https://github.com/junrillg/resume-match-bedrock/commit/4cc9cee) |
| Bounded admission, productive dispatch and small AWS serving path | [4e69a31](https://github.com/junrillg/resume-match-bedrock/commit/4e69a31653b4dd78de6ac35ff59bace3b798ac6e) |

## Earlier completion delivery milestone · 2026-10-19

The following records predate the event-delivery and bounded-deployment checks above; they establish the original durable inbox/route behavior.

Backend: **112 PostgreSQL tests**, migration applied/no drift, and the new notification table admitted to the existing read-only viewer role. Real HTTP verification observed two queued jobs completing with one persisted notice each, fresh-login recovery, idempotent acknowledgement, cross-owner 404s and correlated API/relay/worker/notice events. All probe data used separate synthetic owners and was cleaned up. Existing local services and volumes were preserved.

| Completion milestone | Actual commit |
| --- | --- |
| Researched resumable processing decision | [f32a054](https://github.com/junrillg/resume-match-bedrock/commit/f32a054) |
| Durable inbox and owner APIs | [362a909](https://github.com/junrillg/resume-match-bedrock/commit/362a909) |
| Nonblocking processing, inbox and result routes | [880f9b8](https://github.com/junrillg/resume-match-bedrock/commit/880f9b8) |
