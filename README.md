# Résumé Match · Evidence workbench

Reviewers upload or reuse a résumé, set weighted requirements and receive a coverage score with supporting source quotes. Private object storage retains the original; PostgreSQL owns document identity, processing state and results. Background processing stays independent of the browser request.

![Seven business steps: submit, reserve/store/admit, relay, queue, fetch and process, save, then read the report.](https://raw.githubusercontent.com/junrillg/resume-match-bedrock/4dec8c528107a7c22d4364167a9d9a252a280e5e/docs/assets/architecture.svg)

## One comparison, end to end

1. **Submit:** React sends a PDF/TXT, pasted text or saved document ID with requirements and a retry key.
2. **Accept:** Django reserves new document/job identity in PostgreSQL, stores the original, then atomically queues the job and its outbox. Reuse skips the new upload.
3. **Relay:** a separate process publishes the committed job UUID and waits for broker confirmation.
4. **Queue:** RabbitMQ retains that UUID; document content stays out of messages.
5. **Process:** a leased worker fetches and verifies the original, passes the malware gate, parses or reuses versioned extraction, and validates proposed evidence.
6. **Save:** application code checks the current document/lease, calculates coverage and commits one report.
7. **Read:** React polls owner-scoped status and renders the result or a safe failure.

A queued receipt confirms stored source and dispatch intent. A concurrent replay may instead return an **uploading** reservation: storage is not yet confirmed and interrupted uploads require unchanged-input retry. Neither receipt promises a completed report. [Admission and recovery →](docs/architecture.md)

## Original files and application records

![Upload, storage, scan, processing, reuse and deletion boundaries.](https://raw.githubusercontent.com/junrillg/resume-match-bedrock/8aaace9d884240208ecd9d07bdfd8ace2b1c1271/docs/assets/document-lifecycle.svg)

The local flow uses persistent SeaweedFS S3-compatible storage, ClamAV, PostgreSQL and RabbitMQ. Originals, extracted text and associated results follow the configurable **90-day** project policy. Owners can download clean originals, compare them again, reprocess them or request deletion. [Document lifecycle →](docs/document-lifecycle.md)

The separate AWS Terraform design uses private S3, GuardDuty Malware Protection for S3, ECS/Fargate, RDS, Amazon MQ and Bedrock. Official-icon diagrams show their responsibilities. Local execution and mocked configuration checks do not establish AWS deployment or managed-service behavior. [AWS journey →](docs/aws-service-journey.md)

## Run with Docker

```sh
./scripts/lab up
```

Allow at least 8 GiB for Docker; ClamAV reserves 4 GiB and uses AMD64 emulation on ARM64. Initial signature updates require internet access. Open <http://127.0.0.1:8088>; run `./scripts/lab credentials` in your private terminal for generated logins. The synthetic sample returns **80%**. Search correlated events in OpenObserve at <http://127.0.0.1:5080>.

`./scripts/lab down` preserves volumes. Keep their ignored `.env`; replacing passwords does not update initialized services. `./scripts/lab help` lists commands.

## Engineering references

- [Architecture](docs/architecture.md): request, storage, dispatch, processing and visible outcome.
- [Design and decisions](docs/design.md): requirements, alternatives and actual delivery boundaries.
- [Implementation reference](docs/implementation-guide.md): source/API map, log search and verification.
- [AWS deployment](infra/terraform/README.md): prerequisites, mocked checks, bootstrap and preservation.

**Limits:** local HTTP/debug and single-node services are restricted to synthetic data. Coverage measures source evidence, not candidate quality. OCR and DOCX are unsupported. Cloud deployment, failover, capacity, federation and model evaluation require separate acceptance evidence.
