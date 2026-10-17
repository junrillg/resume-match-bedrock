# Start here: one résumé review, end to end

A reviewer submits a résumé and weighted skill requirements. Extracting evidence may
involve a slow or unavailable model. The application should accept durable work quickly,
show progress, survive delivery failures and commit one result for a logical submission.
It should also make that journey visible without logging document contents.

We designed this system around one authenticated résumé review flow, with durable
background processing and inspectable evidence. Docker Compose runs the complete
architecture locally; the single-node deployment has no production cluster or HA.

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

The separate local HTTP Converse contract service supplies deterministic evidence.
The AWS Terraform deployment preserves the same business boundaries with managed
ingress, private compute/data/messaging and Bedrock access. Local execution and AWS deployment evidence are reported separately.
No automatic hiring decision is made.

## Intended flow

1. **Submit:** React sends the selected document, requirements and retry key through nginx.
2. **Accept:** Django validates the session/input; PostgreSQL commits job and outbox together before the receipt.
3. **Relay:** read committed intent, publish only the job UUID and mark sent after broker confirmation.
4. **Queue:** RabbitMQ retains the persistent wakeup on the declared quorum queue.
5. **Process:** a leased worker calls the HTTP evidence provider outside the claim transaction, then validates its proposals.
6. **Save:** check the current lease, compute weighted coverage, commit one report and clear temporary source.
7. **Read:** React polls owner-scoped status and renders the report or a safe error.

Safe structured events connect the processes in OpenObserve. Reads overlap background
work; delivery and extraction calls can repeat. The [architecture](architecture.md)
shows execution, recovery and evidence; the [AWS journey](aws-service-journey.md) maps
the same responsibilities to the selected managed services.

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
| HTTP Converse service / Bedrock adapter | Propose evidence; never own the score | [Evidence boundary](decisions/0002-evidence-and-data-boundaries.md) |
| OpenObserve + OTLP exporter | Search safe lifecycle events across processes | [Observability](decisions/0004-searchable-observability.md) |

## Ordered build and verification plan

The initial synchronous baseline already exists; its history is preserved. The Docker
foundation is verified in commit `6dbaf577e0e2a9188fe40c66f0e3f2e529a4e037`.
The queue milestone is verified in commit `4456c3214871f46ee47e84f6add9f98dcf54f2d5`.
The job-aware UI is verified in commit `44b0d1e` (15 frontend tests and real queued-to-result UI check).
Searchable logs and runtime recovery are verified in commit `a79e75e702431878b684b5b2f7aa719a5eacab2c`.
This design package records the researched
choices before the remaining UI and observability implementation at that point in history, without backdating it.

| Milestone | Components | Observable check |
| --- | --- | --- |
| Docker foundation | Dockerfiles, Compose, startup helper, database | One command starts healthy services; login/sample works on PostgreSQL. |
| Durable job processing | Job/outbox API, relay, worker, recovery | Broker outage retains work; restart completes one result; concurrency tests fence duplicates. |
| Job-aware UI | React submission, polling, queued/terminal states | Real HTTP admission and state progression; source/drafts stay isolated on auth loss. |
| Searchable observability | Structured events, OTLP export, OSS viewer | Query one job across services; sensitive fields absent; viewer outage does not stop work. |
| Architecture documentation | Numbered diagrams, code map, implementation reference and ADRs | Service boundaries, failure guarantees and operating checks can be traced to source. |

Each implementation milestone includes its boundary checks before its real commit/push.
See [research sources](research.md), [the architecture](architecture.md), then the
[implementation reference](implementation-guide.md).

## AWS delivery sequence

The [AWS service decision](decisions/0005-aws-service-journey.md) records the researched
topology, alternatives, local counterpart and deployment limits before implementation.

| Milestone | Scope | Observable acceptance |
| --- | --- | --- |
| Design | AWS service responsibilities, local parity and ordered delivery | Reviewed decision and plan committed first. |
| Local/provider and transport | Separate HTTP Converse service, SDK endpoint, quorum queue, cloud TLS/proxy configuration, Impeccable UI clarification | Real Compose request returns a report through the HTTP provider; relevant boundary tests and UI/build checks pass. |
| Deployment | Terraform network, ingress, ECS roles/tasks, RDS, MQ, model access, secrets and logs; bootstrap/runbook | Format/init/schema and credential-free mocked plan assertions pass; no real AWS deployment claimed. |
| Architecture communication | Official-icon service views, parity crosswalk, operating evidence and service-by-service overview | Endpoint → durable work → provider → report can be followed without opening implementation files. |

Each implementation milestone is verified and committed before the next. Existing
runtime evidence is reused only where source/configuration and the guarantee remain
unchanged. The model contract service, managed-service TLS and deployment wiring need
new evidence. Three-zone AWS resilience is a deployment requirement, not a local result.
