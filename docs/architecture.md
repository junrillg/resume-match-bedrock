# Trace one résumé comparison

Read [the scenario and vocabulary](design.md) first. This reference implements one
enterprise reliability pattern: durable admission of slow work, repeatable delivery,
and one committed result. We designed it as a résumé review aid and verify it using synthetic documents.

![Numbered local flow: React and Django admit a job and outbox in PostgreSQL; a relay publishes a UUID to RabbitMQ, a worker processes under a fenced lease, and React reads the result. Dotted telemetry goes to OpenObserve. Bedrock remains disabled.](assets/architecture.svg)

Solid numbered arrows carry business work. Dotted arrows carry diagnostic metadata
or the explicitly disabled external-provider option. All local services start together
with `./scripts/lab up`; database and broker ports remain private to Compose.

## Walk the successful input

The synthetic sample mentions Python, Django and React. Requirements assign weights
3, 3, 2 and 2 to those skills and PostgreSQL. Application code counts 8 matched weight
out of 10: 80%. This measures literal evidence coverage, not candidate quality,
competence or a hiring recommendation.

| Step | What happens and why | Source / check |
| --- | --- | --- |
| 1 | React sends session cookies, CSRF and a UUID idempotency key. Ambiguous retries retain the key for the same payload. | [App](../frontend/src/App.tsx), [API helper](../frontend/src/api.ts), [UI regressions](../frontend/src/App.test.tsx) |
| 2 | Django authenticates, bounds input, normalizes selectable PDF/TXT text, then commits Job + Outbox together. `202` means accepted. | [jobs view](../backend/matching/views.py), [models](../backend/matching/models.py), [admission tests](../backend/matching/test_jobs.py) |
| 3–4 | The relay publishes a persistent UUID-only message to the declared durable queue. It marks sent after publisher confirmation. | [relay_once / publish_job](../backend/matching/jobs.py), [relay command](../backend/matching/management/commands/relay_jobs.py) |
| 5 | A worker locks briefly to claim a 90-second lease. Extraction occurs outside that transaction; the token fences completion. | [claim_job / run_job](../backend/matching/jobs.py), [task configuration](../backend/config/celery.py) |
| 6 | The validator rejects invented evidence and partial-word tricks. The server computes the score. Current-token completion saves one result and clears temporary source text atomically. | [services](../backend/matching/services.py), [finish_job](../backend/matching/jobs.py), [boundary tests](../backend/matching/tests.py) |
| 7 | Owner-scoped GET shows queued/running/succeeded/failed and the report. Polling is non-overlapping, bounded per request, paused on errors and stopped at terminal state. | [job API](../backend/matching/views.py), [React lifecycle tests](../frontend/src/App.test.tsx) |

PostgreSQL is the business ledger. RabbitMQ delivers repeatable wakeups. A publisher
confirmation proves broker acceptance under its configured durability semantics; it
does not prove worker completion. The job/result rows establish completion.

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

The default provider is a local literal extractor. The Bedrock adapter has mocked SDK
tests; no AWS credentials are mounted and no calls are authorized. System instructions
are separated from document data, but that alone is not an injection guarantee. Quotes
must appear in the source and contain a bounded skill mention; negation, truth and
positive experience still require human judgment.

Sessions identify reviewers; owner-scoped queries protect jobs/results. CSRF protects
browser mutations including login. This is account isolation, not organization tenancy.
The UI clears drafts, files and private state on logout/authentication loss and rejects
stale responses. See [ADR 0002](decisions/0002-evidence-and-data-boundaries.md).

## Follow the operational path

API, relay and worker export fixed lifecycle metadata to OpenObserve through bounded
OpenTelemetry background batches. Correlate using the request/job IDs shown in the UI.
See [ADR 0004](decisions/0004-searchable-observability.md) and the README's exact search
and verification evidence. Lifecycle logs exclude document text, quotes, prompts, provider payloads,
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

![OpenObserve search returns eight safe lifecycle events for a synthetic success and controlled failure across API, relay and worker.](assets/log-search.png)

## What a broader deployment would add

![Proposed deployment only: protected ingress, organization identity, managed database and broker, isolated workers, approved Bedrock and central operations. None are provisioned here.](assets/enterprise-context.svg)

This separate diagram is a design discussion. Production work includes SSO/RBAC and
tenant policy; TLS/network protections; malware scanning; capacity and availability
targets; backups and restore drills; retention/deletion across backups; alerts; provider
spend limits; model/fairness evaluation and legal review for the intended use. No
throughput, SLA or production readiness is certified.

Kafka is omitted because there are no independent replay consumers or retained stream
requirements. Redis is omitted because no cache bottleneck or separate result backend
is needed. More boxes would not strengthen this flow's stated guarantees.

![Nonliteral analogy: documents pass through a sieve, then selected evidence is weighed.](assets/evidence-concept.png)

The illustration explains validation before scoring; it is not infrastructure. Continue
with [the implementation reference](implementation-guide.md), [ADRs](decisions/0001-durable-background-work.md)
and [research](research.md).
