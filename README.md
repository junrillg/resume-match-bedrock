# Résumé Match · Evidence workbench

A reviewer pastes résumé text or selects a PDF/TXT file, sets skill weights and clicks
**Analyze evidence**. The page receives a job receipt, tracks progress and returns a
weighted coverage score with supporting source quotes.

![The local seven-step comparison: submit, accept, relay, queue, process through an HTTP Converse service, save, and read the report.](docs/assets/architecture.svg)

## One comparison, end to end

1. **Submit:** React sends the document, requirements and a key identifying retries.
2. **Accept:** Django commits the job and dispatch intent together in PostgreSQL, then returns a receipt.
3. **Relay:** a separate process publishes the committed job ID and waits for broker confirmation.
4. **Queue:** RabbitMQ retains that ID for delivery, keeping document content out of messages.
5. **Process:** a worker claims a bounded lease, calls the HTTP evidence provider and validates source quotes.
6. **Save:** application code checks the lease, calculates coverage and commits one report.
7. **Read:** React polls durable status until the score or a safe error appears.

Reads overlap background work. PostgreSQL owns the outcome when delivery repeats;
provider calls may repeat, but at most one result is committed per job.

## The AWS service journey

The same flow has a separate Terraform deployment: Route 53 and an HTTPS load balancer
reach ECS Fargate; RDS owns work/results; Amazon MQ connects relay and worker; the worker
calls Bedrock privately. Identity, secrets, encryption and operations support that path.

[Follow each AWS service →](docs/aws-service-journey.md)

Local execution is verified. Terraform defines the AWS deployment; it has not been deployed.
The local HTTP Converse service returns deterministic evidence and exercises the SDK
boundary, rather than model intelligence or managed AWS behavior.

## Run with Docker

```sh
./scripts/lab up
```

Allow at least 8 GiB for Docker: the private ClamAV scanner reserves 4 GiB.
Its pinned image uses AMD64 emulation on ARM64; signature updates require internet access.

Open <http://127.0.0.1:8088>. Run `./scripts/lab credentials` **in your private terminal**
for the generated login. Load the synthetic sample: its expected score is **80%**.
Search correlated process events in OpenObserve at <http://127.0.0.1:5080>.

`./scripts/lab down` retains volumes. Keep the ignored `.env` with those volumes;
it holds their existing passwords. `./scripts/lab help` lists commands.

## Review the design

- [Execution and recovery](docs/architecture.md): admission, concurrent processing and result rendering.
- [AWS services and local counterparts](docs/aws-service-journey.md): responsibilities, connections and parity limits.
- [Decisions](docs/decisions/0005-aws-service-journey.md): alternatives and consequences.
- [Implementation reference](docs/implementation-guide.md): API, source map, log search and verification evidence.
- [AWS deployment](infra/terraform/README.md): inputs, bootstrap, review/apply order and preservation.

**Limits:** local HTTP, debug mode and single-node services are for synthetic data.
Coverage measures document evidence, not candidate quality. OCR and DOCX are unsupported.
Cloud deployment, failover, capacity, identity federation and model evaluation require their own acceptance evidence.
