# Research behind this design

Checked **2026-10-17**. Our architecture addresses the bounded résumé-review
workload in [the design](design.md). The choices follow the requirements and source-backed
tradeoffs documented here.
Sources describe contracts; the repository's tests and container experiments establish
which contracts the local implementation actually demonstrates.

| Question | Primary source and applicable version | Decision supported |
| --- | --- | --- |
| What happens if a database commit succeeds but queue publication fails? | [AWS transactional outbox guidance](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html) | Save the job and dispatch intent in one transaction; a separate relay publishes committed intent. |
| Does a broker confirmation mean a worker finished? | [RabbitMQ acknowledgements and confirms](https://www.rabbitmq.com/docs/confirms), RabbitMQ 4.3.6 | No. Confirm publication before marking the dispatch sent; keep application completion in PostgreSQL. |
| Can message delivery repeat? | [RabbitMQ reliability guide](https://www.rabbitmq.com/docs/reliability) | Expect duplicates after uncertain publication/connection failure; make committed effects idempotent. |
| What does a killed Celery worker acknowledge? | [Celery tasks](https://docs.celeryq.dev/en/stable/userguide/tasks.html), pinned 5.6 line | Late acknowledgement alone is insufficient; worker-loss rejection plus database recovery and a persisted attempt budget are needed. |
| How are routing, persistence and acknowledgement configured? | [Celery configuration](https://docs.celeryq.dev/en/stable/userguide/configuration.html) and [Kombu producer API](https://docs.celeryq.dev/projects/kombu/en/stable/reference/kombu.html) | Declare the exact durable queue, persistent JSON messages and bounded confirmation/transport waits. No Celery result backend is needed. |
| How do concurrent workers claim one job? | [Django row locking](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update), Django 5.2.18 and PostgreSQL | Short transactions lock the job, claim a lease and fence completion. Test these semantics on PostgreSQL, not SQLite. |
| How should a browser session mutate data safely? | [Django CSRF](https://docs.djangoproject.com/en/5.2/howto/csrf/) | Same-origin cookies and explicit CSRF tokens protect login and mutations; owner filters protect each user's jobs/results. |
| How do containers wait for readiness? | [Compose startup order](https://docs.docker.com/compose/how-tos/startup-order/) | Health checks and a successful migration service precede API/web startup. A started process alone is not readiness. |
| What can a PDF parser safely assume? | [pypdf text extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html), pypdf 6.21.0 | Bound file/page/text/decompression work. Selectable text only; no claim that scanned images receive OCR. |
| How is Bedrock called? | [Boto3 Converse](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-runtime/client/converse.html), boto3 1.43.114 | Separate system instructions from document data, bound tokens, check stop reason and strictly validate extraction. |
| How are provider waits bounded? | [Botocore Config](https://docs.aws.amazon.com/botocore/latest/reference/config.html) and [retry semantics](https://docs.aws.amazon.com/boto3/latest/guide/retries.html) | Explicit connection/read timeouts and one total SDK attempt; database jobs own the retry budget. |
| Could provider logs retain document data? | [Bedrock model invocation logging](https://docs.aws.amazon.com/bedrock/latest/userguide/model-invocation-logging.html) | Review account/region logging and retention before real data; do not infer privacy from the application alone. |
| Is the chosen viewer actually open source? | [OpenObserve v1.1.1 license](https://github.com/openobserve/openobserve/blob/v1.1.1/LICENSE) and [repository](https://github.com/openobserve/openobserve) | Use the AGPL OSS image explicitly; the vendor's Enterprise examples do not establish OSS feature availability. |
| Does log ingestion need another collector? | [OpenObserve OTLP API](https://openobserve.ai/docs/reference/api/ingestion/logs/otlp/) | Direct OTLP HTTP log export can keep this local teaching stack small. |
| Can telemetry block the application? | [OpenTelemetry Python exporters](https://opentelemetry.io/docs/languages/python/exporters/) and [tagged batch processor](https://github.com/open-telemetry/opentelemetry-python/blob/v1.45.1/opentelemetry-sdk/src/opentelemetry/sdk/_shared_internal/__init__.py) | Bounded background batching, exporter-level timeout, no request-path flush; logs are best effort rather than an audit ledger. |

Additional pinned-version operational contracts:

- [OpenObserve v1.1.1 configuration](https://github.com/openobserve/openobserve/blob/v1.1.1/src/config/src/config.rs): three-day retention is the minimum positive setting; its scheduled deletion is not immediate. The free-disk circuit breaker is not a volume byte quota. Memory and cache limits are explicit in Compose.
- [nginx upstream resolve](https://nginx.org/en/docs/http/ngx_http_upstream_module.html#resolve): dynamic upstream resolution is available in the pinned OSS version. A shared zone and Docker DNS resolver let the existing web container follow a recreated API's changed address; this was exercised locally.

## AWS deployment contracts

The [AWS decision](decisions/0005-aws-service-journey.md) was recorded before runtime
and Terraform implementation. These primary sources support the selected service wiring:

- [Fargate networking](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-task-networking.html) and [ECR private endpoints](https://docs.aws.amazon.com/AmazonECR/latest/userguide/vpc-endpoints.html): shared-task localhost; private image pulls also need the S3 layer route.
- [Amazon MQ cluster deployment](https://docs.aws.amazon.com/amazon-mq/latest/developer-guide/rabbitmq-broker-architecture.html), [4.3 behavior](https://docs.aws.amazon.com/amazon-mq/latest/developer-guide/rabbitmq-43.html) and [data protection](https://docs.aws.amazon.com/amazon-mq/latest/developer-guide/data-protection.html): three-zone RabbitMQ, quorum queues and supported encryption; aggregate broker alarms rather than removed queue dimensions.
- [RDS PostgreSQL TLS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.SSL.html) and [ECS secret injection](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/secrets-envvar-secrets-manager.html): verified database transport and task-start secret configuration.
- [Bedrock interface endpoints](https://docs.aws.amazon.com/bedrock/latest/userguide/vpc-interface-endpoints.html): private worker-to-runtime connectivity alongside IAM authorization.
- [Terraform validation](https://developer.hashicorp.com/terraform/cli/commands/validate) and [provider mocking](https://developer.hashicorp.com/terraform/language/tests/mocking): credential-free schema and plan assertions, separate from deployment evidence.
- [LocalStack authentication](https://docs.localstack.cloud/aws/getting-started/auth-token/): a separate deterministic HTTP contract service avoids a licensed/authenticated emulator prerequisite.

## Alternatives considered

A synchronous request is simpler, but ties model latency/retry to an HTTP worker.
Directly enqueueing after a transaction leaves a process-death gap; enqueueing before
commit can expose uncommitted or rolled-back work. PostgreSQL/outbox/RabbitMQ introduces
an extra relay and eventual consistency in exchange for recoverable admission.

Kafka's retained log and independent replay consumers are useful for a different
workload. This lab needs a work queue and one processing responsibility, so RabbitMQ
fits. Redis caching would add invalidation without a demonstrated read bottleneck;
the database already holds job status, so a Redis result backend is unnecessary.
OpenObserve keeps log search in one OSS service; Graylog or Grafana/Loki could fit a
broader operational stack but add dependencies this one-flow lab does not teach.

## What the evidence does not establish

No production throughput/SLA, fairness/accuracy of hiring decisions, live AWS invocation,
managed-service availability, multi-node HA or organization-level tenancy has been
measured. These are explicit limits, not facts inferred from a successful local demo.
The selection and tradeoffs are recorded in [the ADRs](decisions/0001-durable-background-work.md).
