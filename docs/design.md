# Start here: one résumé review, end to end

A reviewer submits a résumé and weighted skill requirements. Extracting evidence may
involve a slow or unavailable model. The application should accept durable work quickly,
show progress, survive delivery failures and commit one result for a logical submission.
It should also make that journey visible without logging document contents.

This is a **fictional design scenario**, not an employer's internal system. The scope
is one authenticated review flow. It is an enterprise pattern implemented locally;
single-node Docker Compose does not provide a production cluster or HA.

## Vocabulary before services

- **Job:** a durable record of one requested comparison and its current state.
- **Queue:** a broker's delivery mechanism for work; it does not own the business result.
- **Outbox:** a database record saying committed work still needs to be published.
- **Relay:** the process that publishes outbox entries and reconciles interrupted jobs.
- **Lease:** a temporary right for one attempt to finish a job; a token rejects stale attempts.
- **Idempotency:** repeating delivery/admission does not create another committed result.
- **Telemetry:** diagnostic events about work, with safe IDs instead of document content.

## Design inputs and boundaries

One bounded PDF/TXT or pasted résumé, up to 1 MiB / 10 PDF pages / 30,000 characters,
is compared against 1–20 explicit weighted requirements. These are actual application
limits, not measured industry capacity targets. The account quota is 20 logical jobs
per UTC day. Work has a finite deadline and attempt budget. The caller owns its jobs
and reports. This is user isolation, not a complete organization/tenant authorization model.

The default external-provider substitute is deterministic and local; it lets the real
queue/worker/database flow run without AWS credentials. Real Bedrock calls remain opt-in
and were not authorized for this run. No automatic hiring decision is made.

## Intended flow

1. React sends a CSRF-protected submission with an idempotency key through nginx to Django.
2. Django authenticates, validates bounded input and normalizes selectable document text.
3. One PostgreSQL transaction records the job and an outbox entry. HTTP `202` means
   accepted, not completed. A repeated key/body returns the same logical job.
4. The relay publishes only the job ID to a declared durable RabbitMQ queue and records
   broker confirmation. The résumé text stays in the database, never in the queue message.
5. A separate Celery worker claims the job under a short row lock, then calls the
   extraction provider outside that transaction. A lease token fences result writes.
6. Application code validates quoted evidence against the original source and computes
   the weighted coverage score. Result and terminal job state commit together.
7. React polls the owner-scoped job endpoint; the result appears when processing finishes.
8. Safe structured lifecycle events let the reviewer find the request/job in OpenObserve.

The observability step is planned until its own implementation milestone is verified.
The definitive shipped flow and evidence are maintained in [architecture.md](architecture.md).

## Where failure changes the flow

Broker unavailable: the API can still commit a job/outbox; the relay retries delivery.
Duplicate messages: only one valid claim/result is allowed. A crashed or stale worker:
lease/deadline reconciliation can schedule another bounded attempt, and the old token
cannot overwrite it. Exhaustion or deadline: a visible terminal failure replaces endless
retries. Telemetry unavailable: business processing continues with bounded diagnostic loss.

Résumé text is retained temporarily while queued/running and cleared at terminal state
or deletion. Persisted quotes can still contain personal data. Production backup/log
retention, SSO, organization tenancy, ingress/TLS, malware scanning and HA require their
own operational design. See the [data and AI decision](decisions/0002-evidence-and-data-boundaries.md).

## Service responsibilities and decisions

| Component | One responsibility | Decision |
| --- | --- | --- |
| nginx + React | Same-origin entry point and progress/evidence UI | [Local runtime](decisions/0003-container-runtime.md) |
| Django API | Authorized, validated, idempotent work admission | [Background work](decisions/0001-durable-background-work.md) |
| PostgreSQL | Source of truth for jobs, outbox and results | [Background work](decisions/0001-durable-background-work.md) |
| Relay + RabbitMQ + worker | Reliable delivery and independent processing | [Background work](decisions/0001-durable-background-work.md) |
| Bedrock adapter / local substitute | Propose evidence; never own the score | [Evidence boundary](decisions/0002-evidence-and-data-boundaries.md) |
| OpenObserve + OTLP exporter | Search safe lifecycle events across processes | [Observability](decisions/0004-searchable-observability.md) |

## Ordered build and verification plan

The initial synchronous baseline already exists; its history is preserved. The Docker
foundation is verified in commit `6dbaf577e0e2a9188fe40c66f0e3f2e529a4e037`.
The queue milestone is verified in commit `4456c3214871f46ee47e84f6add9f98dcf54f2d5`.
This design package records the researched
choices before the remaining UI and observability implementation, without backdating it.

| Milestone | Components | Observable check |
| --- | --- | --- |
| Docker foundation | Dockerfiles, Compose, startup helper, database | One command starts healthy services; login/sample works on PostgreSQL. |
| Durable job processing | Job/outbox API, relay, worker, recovery | Broker outage retains work; restart completes one result; concurrency tests fence duplicates. |
| Job-aware UI | React submission, polling, queued/terminal states | Real HTTP admission and state progression; source/drafts stay isolated on auth loss. |
| Searchable observability | Structured events, OTLP export, OSS viewer | Query one job across services; sensitive fields absent; viewer outage does not stop work. |
| Learning documentation | Numbered diagrams, code map, rebuild guide, topic lessons | A newcomer can trace one input, explain the decisions and begin reimplementation. |

Each implementation milestone includes its boundary checks before its real commit/push.
See [research sources](research.md), [the architecture](architecture.md), then the
[implementation guide](implementation-guide.md) as that final guide is completed.
