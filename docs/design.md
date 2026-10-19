# Résumé review design

The system preserves an uploaded original, processes comparisons independently of the browser and returns checked evidence with an application-owned score. Its core boundaries are durable source storage, recoverable dispatch, fenced results and owner-controlled retrieval/deletion.

![Seven-step local execution and concurrent result reads.](assets/architecture-completion.svg)

## Requirements and data ownership

| Input or record | Contract / owner |
| --- | --- |
| Original | PDF/TXT up to 1 MiB; pasted UTF-8 snapshot; private object storage retains exact bytes |
| Document record | PostgreSQL owns account, generated key, checksum, media type, lifecycle and expiry |
| Extraction | Up to 10 PDF pages / 30,000 characters; PostgreSQL cache records parser version |
| Comparison | 1–20 unique weighted requirements; PostgreSQL job/outbox/result records |
| Completion | One terminal notification per job; owner inbox/read state shares source/job retention |
| Access | Authenticated owner, CSRF on browser mutations, clean-only attachment download |
| Retention | Configurable 90-day policy for documents/derived results; earlier owner deletion |

These are project requirements, not industry capacity targets. Admission permits 20 logical jobs per owner per UTC day. Account isolation is implemented; organization tenancy and federated identity are separate deployment requirements. No automated hiring decision is made.

## Scale inputs

The architecture target is **1,000,000 simultaneously connected users** and a peak
**100 comparisons/second**. Browser tabs, upload reuse, service time and provider token
quotas affect the resulting infrastructure budget. Initial execution starts small with
the same event-driven code path; increasing capacity must not require replacing polling
or an in-memory durability substitute. [Delivery design and measured local envelope →](decisions/0009-event-driven-completion.md)

The local run verifies 1,000 connected owners and one real queued comparison. It does
not measure the target processing rate or million-user capacity. Deployment sizes and
capacity evidence remain distinct from the implemented mechanisms.

## Flow and consistency

Steps **1 Submit · 2 Accept · 3 Relay · 4 Queue · 5 Process · 6 Save · 7 Read** are shared across the [architecture](architecture.md), [document lifecycle](document-lifecycle.md) and [AWS journey](aws-service-journey.md).

New-source admission has three boundaries: reserve document/job identity in PostgreSQL; PUT the original; then commit pending document + queued job + outbox together. The object service and database do not share a transaction. Reserved-upload identity, leases, deadlines and reconciliation close partial-write/deletion failures. A concurrent replay can return `202 uploading`; only a finalized queued receipt confirms stored source. Saved-source reuse queues another comparison without uploading again.

After commit, the relay publishes only a UUID. The worker fetches verified source, passes the malware gate, parses or reuses matching extraction, calls the evidence provider, validates quotes, and saves a fenced score/result and terminal notification atomically. Browser reads overlap those processes. At-least-once delivery and provider calls can repeat; the database permits one committed report per job.

## Service choices

| Responsibility | Local service | Decision |
| --- | --- | --- |
| Entry and owner access | React/nginx + Django | [Runtime](decisions/0003-container-runtime.md) |
| Originals and integrity | SeaweedFS S3-compatible storage | [Durable lifecycle](decisions/0006-durable-document-lifecycle.md) |
| Metadata, state and results | PostgreSQL | [Background work](decisions/0001-durable-background-work.md) |
| Delivery and reconciliation | Relay + RabbitMQ + Celery worker | [Background work](decisions/0001-durable-background-work.md) |
| Connected browser delivery | PostgreSQL event ledger + event relay + two independent Valkey shards + two raw ASGI gateway processes | [Durable events](decisions/0009-event-driven-completion.md) |
| Untrusted-file gate | ClamAV locally; GuardDuty in AWS design | [Durable lifecycle](decisions/0006-durable-document-lifecycle.md) |
| Proposed evidence | Separate HTTP Converse service / Bedrock | [Evidence boundary](decisions/0002-evidence-and-data-boundaries.md) |
| Correlated diagnostics | OpenObserve + bounded OTLP export | [Observability](decisions/0004-searchable-observability.md) |

Valkey supplies owner-channel wakeups and bounded connection leases, not a cache or the source of business truth. PostgreSQL owns replay and saved outcomes. Kafka has no retained-stream consumer here. Business scope stays small while storage/recovery/access mechanisms remain complete for the stated flow.

## Service inspection

The local runtime includes a connected inspection surface for every selected service.
Viewer coverage is part of the operating contract, including startup, private access,
meaningful sample activity and documented interpretation. It does not change the seven
business steps or authorize AWS access. [ADR 0007](decisions/0007-service-inspection.md)
records the service inventory and least-privilege boundaries.

| Service boundary | Inspection surface | What it establishes |
| --- | --- | --- |
| React/nginx + Django API | Existing application plus browser Network panel | Request/status/response and owner-visible report |
| Celery worker | Flower at `127.0.0.1:5555/tasks` | Worker heartbeat and transport task lifecycle; comparison outcome remains in PostgreSQL |
| RabbitMQ | Management at `127.0.0.1:15672/#/queues` | Quorum queue, consumers, ready/unacknowledged messages and delivery activity |
| PostgreSQL | pgAdmin at `127.0.0.1:5050`, dedicated read-only database role | Document/job/outbox/result relationships and durable business state |
| SeaweedFS | Authenticated read-only `weed admin` at `127.0.0.1:23646/files?path=/buckets/resume-originals` | Cluster/bucket/object inventory; privileged raw-object visibility is separate from the owner-scoped application |
| API/relay/worker/provider diagnostics | Existing OpenObserve | Correlated, payload-free lifecycle events |
| Relay | OpenObserve plus supported process/heartbeat inspection | Dispatch intent and publication/recovery without inventing a separate relay GUI |
| ClamAV | Official `clamdtop` terminal dashboard, plus health and OpenObserve safety events | Scan queue, memory/signature readiness and rejection; daemon port stays private |
| Local Converse provider | OpenObserve and existing health endpoint | Separate HTTP hop and safe success/rejection state; no live Bedrock console claim |
| Initialization/migrations | Compose completion state and bounded operational output | Successful prerequisite completion; no extra permanent dashboard |

All new host listeners bind loopback. Separate viewer passwords are generated into the existing
owner-only ignored environment and shown only by the explicit private credentials
command. Existing credentials and named volumes remain intact. Monitoring must not
require enabling Celery remote-control commands or exposing raw database, S3, scanner,
filer/master, gRPC or AMQP ports. SeaweedFS administration is a privileged synthetic-only
operator surface: read-only is cluster-wide and does not imply owner-scoped or
clean-only reads. Its separate login must not be presented as an application user
account. Research must resolve any viewer capability or privilege uncertainty before
wiring that viewer; an unavailable GUI must be reported with its supported inspection
alternative, never silently skipped.

## Inspection delivery record

| Requirement | Status | Evidence | Next action |
| --- | --- | --- | --- |
| Complete service/viewer inventory and access design | Verified | ADR 0007, checked release sources and pinned images | Retain the complete inventory when services change |
| Connected default startup and private, least-privilege access | Verified | 13 healthy services; auth/permission checks and 10 focused tests | Preserve existing secrets/volumes |
| Meaningful task/queue/database/storage activity | Runtime and three new GUIs verified; pgAdmin reconnect pending | Queue backlog/drain, Flower task/job mapping, retained object inventory, success/rejection and log/scanner views | Verify pgAdmin connection and populated records |
| Public operating reference and matching diagrams | Verified | [Access/evidence reference](implementation-guide.md#service-inspection); published inspection diagram checked | Finish the remaining pgAdmin connection/record review |

The design commit preceded **runtime viewers and focused tests** (`17ba0eb`);
**operating docs, diagrams and final evidence** follow that runtime milestone.
RabbitMQ, Flower and SeaweedFS populated browser review passed. pgAdmin registration
was corrected after the browser exposed its password-file configuration gap; final
connection/record review remains pending. Successful direct SQL does not close that gate.
The stack remains running for review.

## Failure boundaries

Object outage leaves recoverable upload identity, not a processable missing source. Broker outage leaves durable outbox intent. Pending cloud scans defer provider work within the job deadline; failed/unavailable scanning fails closed. Token checks prevent stale completion. Document deletion/expiry denies access and fences related work before retried object cleanup. Diagnostics can fail without failing business processing.

The [lifecycle reference](document-lifecycle.md) defines source and derived-data cleanup, the seven-day cloud backup window, and restore-time reconciliation. Local logs retain three days; configured CloudWatch logs retain 30 days. Malware scanning reduces risk, and retained evidence can still be personal data.

## Delivery record

Existing history is preserved. Research and ADR 0006 were committed before the durable-storage changes; subsequent verified milestones are recorded with their actual commits in the [implementation reference](implementation-guide.md#actual-build-history). The source-retention portions of ADRs 0002/0005 are superseded; their earlier decisions remain traceable.

| Durable-document milestone | Acceptance |
| --- | --- |
| Research/design | Primary sources, data inventory and lifecycle/recovery decision |
| Local processing | Real object/scanner flow, PostgreSQL isolation/concurrency, outage and cleanup checks |
| AWS configuration | Private S3/scanner/IAM/endpoint/KMS wiring and mocked plan assertions |
| Document UI | Source selection, authorized download/reprocess/deletion and verified status/error states |
| Architecture communication | Matching diagrams, source links, operating contracts and evidence |

The [research](research.md) supports these choices. Passing local checks and mocked Terraform plans does not certify cloud operation, high availability or universal production readiness.

## Processing and completion journey

The event-delivery milestone is governed by [ADR 0009](decisions/0009-event-driven-completion.md):
**one million simultaneous users**, dedicated asynchronous SSE delivery, durable event
recovery and bounded event-driven reads. Its deployment target and measured local
capacity are separate. The local implementation replaces recurring browser polling
with SSE signals and targeted authorized reads. Stream heartbeats do not query the
database; fan-out recovery reconciles the durable revision ledger. Terraform wiring
and the detailed public topology update remain separate delivery milestones.

[ADR 0008](decisions/0008-nonblocking-completion.md) defines the shipped processing, inbox and result routes. Action pending state is separate from worker progress; saved completion notices survive leaving the page. A paused-worker browser run verified a second submission, an unchanged off-route draft, explicit notification access, result refresh, read persistence and completion while the app tab was closed. The design, durable inbox and UI were verified and published as separate milestones.
