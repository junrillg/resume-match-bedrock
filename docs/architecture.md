# Résumé comparison execution

A reviewer uploads or reuses a résumé, requests weighted evidence analysis and receives a report. Object storage preserves the original; PostgreSQL owns identity, lifecycle, dispatch intent and results. Processing runs independently. Durable change signals tell the browser which authorized records to read.

![Local seven-step request, dispatch, worker and result flow.](assets/architecture-completion.svg)

The canonical steps are **1 Submit · 2 Accept · 3 Relay · 4 Queue · 5 Process · 6 Save · 7 Read**. Solid arrows carry work; dashed arrows show concurrent reads or diagnostic metadata. [Requirements and decisions](design.md) establish the scope.

For the complete function-level trace, open the [upload-to-score Mermaid diagrams](upload-to-score-mermaid.md): overview, admission, RabbitMQ/Celery dispatch, retrieval/scoring and recovery/lifecycle. Each diagram has an editable source.

## 1–2 · Submit, store and admit

React sends multipart input and a UUID retry key through nginx. Django checks the session, CSRF, limits, ownership and payload identity before changing durable state. Unchanged-key recovery precedes new-work admission. New logical jobs must fit owner, rate and active-work budgets with fresh broker/worker supply and acceptable queue age; rejection returns `429` or `503` with retry guidance.

![Admission sequence: PostgreSQL reserves source identity, the object store confirms PUT, then queued job and outbox commit.](assets/admission-sequence.svg)

[Diagram source](assets/admission-sequence.mmd)

Object PUT and database finalization are separate operations. The outbox exists only after confirmed source storage and finalization. A concurrent same-key request may receive an `uploading` reservation; it does not prove storage or queueing. An interrupted upload requires retrying the original unchanged input/key, or reservation expiry and cleanup. Saved-document comparison skips PUT and commits a new queued job/outbox against the owned, unexpired source.

## 3–6 · Dispatch, verify source and save

![Dispatch and processing: UUID delivery, source retrieval and integrity checks, safety gate, parsing, proposed evidence and fenced result.](assets/processing-sequence.svg)

[Diagram source](assets/processing-sequence.mmd)

The local worker fetches and checksum-checks bytes, then calls ClamAV; AWS checks the GuardDuty clean tag before GET, with a bucket policy enforcing the same gate. The diagram groups that boundary rather than implying identical scanner order. Every comparison verifies the source; matching extraction can avoid parsing again. Explicit reprocessing parses it again.

Object, scanner and provider I/O release database connections. Completion locks owner stream state, then document, then job and rejects deleted/expired source or a stale lease. The terminal transaction commits the outcome, one owner-visible completion notice and durable owner revisions, then releases the admission reservation atomically. Intermediate retries create no notice. Delivery/provider calls may repeat; one job/result relationship prevents duplicate committed reports. Worker execution can precede the relay's sent-marker commit. There is no total order across independent processes.

## 7 · Continue work and return to the outcome

![Durable acceptance leads to a processing route with free navigation. Worker outcome and notification commit together; only the same processing page auto-opens its result.](assets/completion-sequence.svg)

[Diagram source](assets/completion-sequence.mmd) · [Delivery decision](decisions/0009-event-driven-completion.md)

After a finalized receipt, React opens `/jobs/<id>` with navigation available. The reviewer can start another comparison or leave. PostgreSQL saves a completion/failure notification with the terminal outcome. `/notifications` links to `/results/<job-id>` on success or the job's safe failure page. **Mark as read** is a separate, idempotent action; report access never waits for it.

Only the same active processing page advances automatically. Completion elsewhere preserves the current route, draft and focus. One SSE stream per visible authenticated tab receives minimal change identifiers. Hidden/offline tabs close it; reconnect performs authorized reconciliation. A closed browser finds saved notices on the next visit. This is in-app delivery.

![Durable event publication, owner fan-out, SSE delivery and targeted reads.](assets/event-delivery.svg)

The event relay marks pending publication only after the owner-shard wake succeeds. Valkey distributes wakeups and connection leases; PostgreSQL owns replay and results. A separate raw ASGI gateway multiplexes subscriptions, authenticates sessions and bounds database work. Subscribe acknowledgement precedes replay. Heartbeats perform no SQL. Stale cursors request a fresh snapshot; stream outages use jittered reconnect.

Owner-authorized detail reads support direct result links. Session, navigation and deletion fences reject stale responses. [Timing, routes and operating contract →](implementation-guide.md#browser-state-and-isolation)


## Stored originals and lifecycle

![Original-object and database lifecycle from upload through retrieval, reuse and deletion.](assets/document-lifecycle.svg)

Owners can download a ready original through an authorized, attachment-only, no-store response, create further comparisons or reprocess. Document deletion/expiry first blocks access and fences related jobs, then the relay retries physical deletion. Deleting an established comparison preserves its original. Cancelling the initial unfinished upload instead schedules that unready source for cleanup. [Lifecycle and cross-store recovery →](document-lifecycle.md)

## Failure and recovery

| Boundary | Durable response |
| --- | --- |
| PUT or finalization interrupted | Reservation/key survive; same-input retry or deadline cleanup; no unready outbox |
| Broker/worker supply unavailable | New logical admission returns `503`; already accepted outbox intent remains recoverable, and confirmation ambiguity can repeat publication |
| Source missing/corrupt or scanner unavailable | No parse/provider/download bypass; visible bounded failure |
| GuardDuty scan pending | Requeue without using provider-attempt budget, within ten-minute job deadline |
| Worker interrupted | Lease/deadline reconciliation; stale completion cannot overwrite another claim |
| Source deleted/expired | Access denied and work fenced; failed object DELETE remains retryable |
| Fan-out/gateway unavailable | Durable events/outcomes remain; publication retries and jittered reconnect/replay recover state, without automatic REST polling |
| Viewer unavailable | Bounded best-effort diagnostic loss; business processing continues |

The provider budget is three claims with 2/4-second retry backoff and a ten-minute job deadline; leases last 90 seconds. Cloud scan pending uses its separate deferral within that deadline. [Exact operating/source reference →](implementation-guide.md)

## Inspect service boundaries

![RabbitMQ, Celery, PostgreSQL and object storage connect to separate local inspection surfaces; business UUID delivery remains distinct from read-only inspection.](assets/service-inspection.svg)

[Diagram source](assets/service-inspection.mmd)

RabbitMQ Management exposes backlog and consumers; Flower consumes task events;
pgAdmin reads seven application/stream record tables; the read-only fan-out viewer inspects both Valkey shards; SeaweedFS admin inspects storage.
OpenObserve correlates API/relay/worker/provider events and exposes event-relay/gateway delivery health, while `clamdtop`
shows the scanner's queue and signature state. These surfaces accompany the existing
seven business steps and do not become part of request completion.

Task completion is a transport observation: the application can reject a document
while Flower shows `SUCCESS`. PostgreSQL owns the comparison outcome. Database and
storage viewers are privileged synthetic-only operator surfaces; read-only storage
access includes raw/quarantined files and is separate from application owner/safety
checks. [Access, permissions and current verification →](implementation-guide.md#service-inspection)

## Evidence and deployment limits

The synthetic weights Python 3, Django 3, React 2 and unmatched PostgreSQL 2 produce **80%**. Application code validates literal quotes and skill mentions, then scores matched weight / total weight. This measures document evidence, not competence, truth or fairness.

Real Compose checks exercised originals, ClamAV, PostgreSQL, queued processing, storage/scanner outages and cleanup. Searchable metadata connects API, relay, worker and the HTTP provider; no document, filename, object key, signed URL or credential is logged. [Log search and evidence →](implementation-guide.md#search-one-job-across-services)

The [AWS service journey](aws-service-journey.md) uses separate Terraform and official-icon diagrams. It is source/mock-plan verified, not deployed. Local single-node services do not establish managed failover, capacity, organization identity, backup restoration or model quality. Those checks remain deployment acceptance work.
