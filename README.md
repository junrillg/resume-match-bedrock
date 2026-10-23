# Résumé Match · Evidence workbench

Reviewers upload or reuse a résumé, set weighted requirements and receive a coverage score with supporting source quotes. Private object storage retains the original; PostgreSQL owns document identity, processing state and results. After acceptance, reviewers can leave the processing page and continue working; a saved in-app notification links to the completed report.

![Seven business steps: submit, reserve/store/admit, relay, queue, fetch and process, save, then read the report.](docs/assets/architecture-completion.svg)

## One comparison, end to end

1. **Submit:** React sends a PDF/TXT, pasted text or saved document ID with requirements and a retry key.
2. **Accept:** Django checks owner fairness and fresh processing supply, reserves new document/job identity, stores the original, then atomically queues the job and its outbox. Reuse skips the new upload; unchanged-key retries recover the existing job.
3. **Relay:** a separate process drains committed UUIDs through a reused producer and waits for broker confirmation.
4. **Queue:** RabbitMQ retains that UUID; document content stays out of messages.
5. **Process:** a leased worker fetches and verifies the original, passes the malware gate, parses or reuses versioned extraction, and validates proposed evidence.
6. **Save:** application code checks the current document/lease, calculates coverage and atomically commits one report, its completion notification and a durable change event.
7. **Read:** the event relay wakes the owner's Valkey shard; an asynchronous SSE gateway signals the browser to fetch only changed, authorized state. The active processing page advances on success; notifications elsewhere leave the current page intact.

A queued receipt confirms stored source and dispatch intent. A concurrent replay may instead return an **uploading** reservation: storage is not yet confirmed and interrupted uploads require unchanged-input retry. Neither receipt promises a completed report. Notifications persist across refresh and sign-out; they appear when the user returns to the app. [Admission and recovery →](docs/architecture.md)

The same serving path starts small and scales through independent gateway/worker replicas and bounded shared services. **One million connected users and 100 comparisons/second are planning inputs.** A local 1,000-stream failure/recovery run and a real queued comparison passed; the full targets remain unmeasured. [Measured envelope and transport →](docs/decisions/0009-event-driven-completion.md) · [Deployment and admission bounds →](docs/decisions/0010-bounded-deployment.md)

## Original files and application records

![Upload, storage, scan, processing, reuse and deletion boundaries.](docs/assets/document-lifecycle.svg)

The local flow uses persistent SeaweedFS S3-compatible storage, ClamAV, PostgreSQL and RabbitMQ. Originals, extracted text and associated results follow the configurable **90-day** project policy. Owners can download clean originals, compare them again, reprocess them or request deletion. [Document lifecycle →](docs/document-lifecycle.md)

The separate AWS Terraform design uses private S3, GuardDuty Malware Protection for S3, ECS/Fargate, RDS with RDS Proxy, Amazon MQ, private encrypted Valkey shards and Bedrock. Official-icon diagrams show their responsibilities. Local execution and mocked configuration checks do not establish AWS deployment or managed-service behavior. [AWS journey →](docs/aws-service-journey.md)

## Run with Make and Docker

Requires GNU Make 3.81+ (including macOS Make), a POSIX shell, Docker Compose with
`--wait`, Python 3.12+ and `openssl`.

```sh
make help
make up
make sample
```

Allow at least 8 GiB for Docker; ClamAV reserves 4 GiB and uses AMD64 emulation on ARM64. Initial signature updates require internet access. Open <http://127.0.0.1:8088>; run `make credentials` in your private terminal for generated logins. The same startup connects the service viewers below.

`make sample` runs a separate disposable synthetic comparison through HTTP, the queue,
worker and SSE; it reports a 100% score and job/request IDs, then removes its own
original and fixture records. The UI’s built-in sample remains 80%.

`make down` and `make restart` preserve volumes. Keep their ignored `.env`; replacing
passwords does not update initialized services. `make logs` follows container output;
OpenObserve below provides searchable logs. `make help` lists every command.

After startup, `make test` runs the existing automated suites; `make verify` also builds
images, checks Django configuration/migration drift and validates the credential-free
Terraform mock plans (Terraform 1.15.8 required). CI invokes `make check`, which also
reports the missing formatter/linter, backend type and security-scan gates and exits
nonzero until those are configured. A passing `make verify` is limited to the existing
checks. [Command details →](docs/implementation-guide.md#verification-commands)

## Inspect the running flow

| Surface | Local address | View |
| --- | --- | --- |
| Application | <http://127.0.0.1:8088> | Owned documents, processing/results pages and saved notifications |
| RabbitMQ Management | <http://127.0.0.1:15672/#/queues> | Queue backlog, consumers and delivery activity |
| Flower | <http://127.0.0.1:5555/tasks> | Celery task events and worker heartbeat |
| pgAdmin | <http://127.0.0.1:5050> | Read-only document/job/outbox/result/notification and stream revision/event records |
| Fan-out viewer | <http://127.0.0.1:8089> | Read-only connections to both independent Valkey shards |
| SeaweedFS admin | <http://127.0.0.1:23646/files?path=/buckets/resume-originals> | Privileged, read-only storage inventory |
| OpenObserve | <http://127.0.0.1:5080> | Correlated application/process events |
| ClamAV | `docker compose exec scanner clamdtop` | Live terminal scan queue and signature state |

All web listeners bind loopback and use generated private logins. Storage administration
can read raw/quarantined originals across accounts; it is a synthetic-only operator
surface. Flower task completion does not establish comparison success. [Access,
permissions and observed behavior →](docs/implementation-guide.md#service-inspection)

## Engineering references

- [Architecture](docs/architecture.md): request, storage, dispatch, processing and visible outcome.
- [Upload-to-score Mermaid diagrams](docs/upload-to-score-mermaid.md): end-to-end flow, function links, retries and document lifecycle.
- [Design and decisions](docs/design.md): requirements, alternatives and actual delivery boundaries.
- [Implementation reference](docs/implementation-guide.md): source/API map, log search and verification.
- [AWS deployment](infra/terraform/README.md): prerequisites, mocked checks, bootstrap and preservation.

**Limits:** local HTTP/debug and single-node services are restricted to synthetic data. Coverage measures source evidence, not candidate quality. OCR and DOCX are unsupported. Cloud deployment, failover, capacity, federation and model evaluation require separate acceptance evidence.
