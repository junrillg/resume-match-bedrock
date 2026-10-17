# Résumé comparison execution

A reviewer fills in a résumé and weighted requirements, then clicks **Analyze evidence**.
The browser receives a job receipt while processing continues in the background. It reads
the saved state until it can show a score and the source quotes supporting it.

We designed each handoff to preserve accepted work and prevent duplicate results.
[The scenario and vocabulary](design.md) describe the requirements and terms.

![Numbered local flow: React and Django admit a job and outbox in PostgreSQL; a relay publishes a UUID to RabbitMQ, a worker processes under a fenced lease, and React reads the result. A separate local HTTP provider exchanges Converse requests with the worker; safe telemetry reaches OpenObserve.](assets/architecture.svg)

The overview maps responsibilities: browser reads begin after acceptance and can
overlap relay and worker processing.

Solid numbered arrows carry business work. Dashed arrows identify concurrent reads
or diagnostic metadata. All local services start together
with `./scripts/lab up`; database and broker ports remain private to Compose.

## One request in three phases

The synthetic sample mentions Python, Django and React. Their weights are 3, 3 and 2;
PostgreSQL adds an unmatched weight of 2. Validated coverage is `(3 + 3 + 2) / 10 = 80%`.
The score describes document evidence, not candidate quality.

The overview’s **1–7** steps remain the reference throughout: **1 Submit · 2 Accept ·
3 Relay · 4 Queue · 5 Process · 6 Save · 7 Read**. Labels such as `2.1` expand step 2.
The phases group responsibilities: after acceptance, browser reads can overlap dispatch
and processing; they do not wait for a worker push.

### 1. Admit the request

Form events update React state; submit sends only the selected text or file. The API
helper sends CSRF and same-origin credentials; the submit handler supplies the retry key. nginx forwards
`/api/` to Django. Middleware establishes request identity before the view validates input.

```mermaid
sequenceDiagram
  participant UI as React browser
  participant API as Django API
  participant DB as PostgreSQL
  UI->>API: 1.1 POST /api/jobs/ through nginx
  API->>API: 2.1 Session + CSRF + input checks
  API->>DB: 2.2 One transaction: Job + OutboxEvent
  DB-->>API: Commit succeeds
  API-->>UI: 2.3 202: durable job receipt
```

The transaction also checks owner-scoped idempotency and charges the daily quota once.
`202` confirms a durable receipt; it does not promise a score or require a working broker.
A repeated unchanged submission can recover that same receipt.

### 2. Dispatch and process

The relay publishes a wakeup after the database commit. A broker confirmation and a
worker result are separate facts; PostgreSQL remains the business ledger.

```mermaid
sequenceDiagram
  participant Relay
  participant DB as PostgreSQL
  participant MQ as RabbitMQ
  participant Worker as Celery worker
  participant Provider as HTTP Converse service
  Relay->>DB: 3.1 Lock an unsent outbox event
  Relay->>MQ: 3.2 Publish persistent job UUID
  MQ-->>Relay: Publisher confirmation
  Relay->>DB: 3.3 Mark outbox sent
  MQ->>Worker: 4.1 matching.process_job(job_id)
  Worker->>DB: 5.1 Lock job, claim timed lease
  DB-->>Worker: Stored text + requirements + lease
  Worker->>Provider: 5.2 boto3 Converse: source + requested skills + UUID metadata
  Provider-->>Worker: Deterministic proposed evidence
  Note over Worker: Validate source quotes before completion
  Worker->>DB: 6.1 Fence lease, score, commit result
```

Extraction runs outside the claim transaction. Completion locks the job again and checks
its current, unexpired lease token before saving one result and clearing temporary text.
Delivery and provider calls may repeat; the result relationship is unique per job.
Worker delivery can begin before the relay handles confirmation or commits its sent marker;
the sequence shows responsibilities, not a cross-process ordering guarantee.

### 3. Read and render the result

The browser polls the **owner's job collection**, not the detail endpoint. Each response
embeds any completed report; the UI derives its selected result from that server state.

```mermaid
sequenceDiagram
  participant UI as React browser
  participant API as Django API
  participant DB as PostgreSQL
  loop While queued/running, one request at a time
    UI->>API: 7.1 GET /api/jobs/
    API->>DB: 7.2 Current owner's jobs + related Match
    DB-->>API: Durable status, attempts, optional report
    API-->>UI: 7.3 JSON jobs with nested match
  end
  Note over UI,API: 7.4 MatchResult renders<br/>score and source quotes
```

Polling starts after a one-second delay, with a ten-second deadline per request. It stops
at terminal state and pauses on network errors. A fast local job can finish between polls,
so `running` need not appear on screen. Failed jobs display an error category without a score.

The [source handoffs](implementation-guide.md#source-handoffs) map these three phases to
exact functions, proxy configuration and route declarations.

## Failure and recovery

![Sequence: Django commits a job and outbox while RabbitMQ is unavailable; the relay later publishes it, a worker commits a result, and React reads completion.](assets/recovery.svg)

- **Broker down:** admission remains possible while PostgreSQL is available. Unsent
  outbox intent survives. If confirmation or its database update is uncertain,
  publication can repeat.
- **Duplicate or interrupted worker:** a short locked claim and token-fenced completion
  protect effects. The relay reconciles expired leases and stale queued wakeups.
- **Transient extraction failure:** at most three claims, 2/4-second retry backoff and a
  ten-minute job deadline. Permanent invalid evidence fails safely. No demo fallback.
- **Stale completion or deletion:** an old lease cannot overwrite a newer attempt;
  deletion and completion lock the same job. A unique job/result relationship prevents
  duplicate committed reports. Provider calls can still repeat or incur repeated charges.
- **Browser/network error:** same-payload manual retry retains its key. Changed inputs
  use a new key. The server rejects a conflicting payload under an existing key.
- **Log viewer down:** bounded background telemetry can lose events; business state
  remains in PostgreSQL. Stdout is a fallback, not a durable audit ledger.

```mermaid
stateDiagram-v2
  [*] --> queued: job + outbox commit
  queued --> running: locked lease claim
  running --> succeeded: validated evidence + fenced commit
  running --> queued: retryable failure / expired lease
  queued --> failed: deadline / exhausted budget
  running --> failed: invalid evidence / deadline / exhausted budget
  succeeded --> [*]
  failed --> [*]
```

Real broker/worker pause and restart experiments verified durable delivery and eventual
single-result completion. PostgreSQL concurrency tests cover duplicate claims, fenced
completion and deletion races. Expired leases and exhaustion are tested; a mid-provider
process kill has not been measured as a live cloud experiment.

## Data, AI and authorization boundaries

Only bounded, selectable text is parsed; no OCR or DOCX. PDF normalization remains in
the API; evidence extraction is the worker responsibility. Queue messages contain only
the job UUID. Temporary source text stays in PostgreSQL until terminal state or deletion;
evidence excerpts remain until report deletion. Backups may retain old rows.

The default Compose provider is a separate HTTP Converse contract service. The worker
uses boto3 against its explicit local endpoint, with unsigned requests and no credential
discovery. It returns deterministic literal evidence; AWS uses the Bedrock runtime
through the Terraform-defined private endpoint. Local contract and mocked SDK tests
do not prove model quality or cloud connectivity. System instructions
are separated from document data, but that alone is not an injection guarantee. Quotes
must appear in the source and contain a bounded skill mention; negation, truth and
positive experience still require human judgment.

Sessions identify reviewers; owner-scoped queries protect jobs/results. CSRF protects
browser mutations including login. This is account isolation, not organization tenancy.
The UI clears drafts, files and private state on logout/authentication loss and rejects
stale responses. See [ADR 0002](decisions/0002-evidence-and-data-boundaries.md).

## Follow the operational path

API, relay, worker and local HTTP provider export fixed lifecycle metadata to OpenObserve through bounded
OpenTelemetry background batches. Correlate using the request/job IDs shown in the UI.
See [ADR 0004](decisions/0004-searchable-observability.md), the [exact log search](implementation-guide.md#search-one-job-across-services)
and [verification evidence](implementation-guide.md#verified-local-behavior). Lifecycle logs exclude document text, quotes, prompts, provider payloads,
filenames, usernames, credentials, cookies, headers and raw exceptions.

| Safe field | Operational question |
| --- | --- |
| timestamp | When was this event observed? Cross-process arrival order can differ. |
| service_name / event | Which process reached which lifecycle boundary? |
| request_id / job_id | Which submission connects these events and database state? |
| status | Is work queued, running, terminal or awaiting publication? |
| attempt | Is this the first claim or a bounded retry? |
| duration_ms | How long did the measured processing boundary take? |
| error_code | Which safe failure category should be investigated? |

Not every event has every field. These are logs, not a distributed trace or a metrics
dashboard. Job IDs are useful search fields; they are unsuitable as one metric label
per job. Best-effort diagnostics do not replace the persisted attempt/deadline ledger.

![Earlier OpenObserve capture shows safe lifecycle events across API, relay and worker; current verification also includes the local HTTP provider.](assets/log-search.png)

## AWS deployment and remaining production work

![Terraform-defined AWS request path using official service icons: endpoint ingress, ECS tasks, RDS, Amazon MQ, private Bedrock access and report reads.](assets/enterprise-context.svg)

[The AWS service journey](aws-service-journey.md) follows each selected service and its
local counterpart. [Terraform](../infra/terraform/README.md) defines networking, HTTPS,
private application tasks, managed persistence/messaging, model access, identities,
secrets, encryption and operations. It has not been deployed.

Production acceptance still needs account/region/model checks; restore/failover and
capacity drills; organization identity/RBAC and tenant policy if required; malware
scanning and retention across backups; alert ownership; and model/fairness evaluation
for the intended use. No throughput, SLA or universal production readiness is certified.

Kafka has no independent replay consumer here. Redis has no demonstrated caching role;
the database already owns status/results. More services would not strengthen those guarantees.

Continue with [the implementation reference](implementation-guide.md),
[ADRs](decisions/0001-durable-background-work.md) and [research](research.md).
