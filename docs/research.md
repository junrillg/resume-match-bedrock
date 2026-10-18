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

## Durable document storage review — 2026-10-18

The earlier scope cleared source text after comparison. It did not establish an original-document lifecycle before excluding object storage. The revised design retains exact originals for reuse, retrieval and reprocessing; application records remain in PostgreSQL.

| Primary source, checked 2026-10-18 | Supported behavior | Adopted decision |
| --- | --- | --- |
| [AWS document processing](https://aws.amazon.com/blogs/architecture/optimizing-data-with-automated-intelligent-document-processing-solutions/) | Original documents use S3; metadata and processing outputs have separate persistence roles. | Separate original objects from relational ownership/status/results. Its Lambda/DynamoDB topology is not a universal requirement. |
| [GitLab uploads](https://docs.gitlab.com/development/uploads/) | Object storage supports shared application/worker access; small controller uploads and large direct uploads have different tradeoffs. | Keep bounded 1 MiB API uploads; workers fetch stored originals. Presigned browser uploads are unnecessary for this limit. |
| [OWASP file uploads](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html) | Authorization, allowlists, generated storage names, limits, isolated storage and malware controls. | Private quarantine, fail-closed scan, integrity verification and owner-checked attachment download. |
| [SeaweedFS 4.48](https://github.com/seaweedfs/seaweedfs/tree/4.48), [S3 API matrix](https://github.com/seaweedfs/seaweedfs/wiki/Amazon-S3-API) | Maintained Apache-2.0 S3-compatible object service; bucket notifications are not implemented. | Persistent local object service; test exact SDK operations, retain the application outbox rather than claim S3-event parity. |
| [LocalStack authentication](https://docs.localstack.cloud/aws/getting-started/auth-token/), [single-image transition](https://blog.localstack.cloud/localstack-single-image-next-steps/) | Current AWS image requires authentication; old community assumptions are stale. | Choose an account-free local S3-compatible service, not an unsupported tokenless image. |
| [ClamAV Docker](https://docs.clamav.net/manual/Installing/Docker.html), [clamd](https://docs.clamav.net/manual/Usage/Scanning.html) | Official scanner container, streaming daemon integration and definition maintenance requirements. | Scan before parsing/release; scanner failure never means clean. Verify actual container and EICAR rejection locally. |
| [S3 security](https://docs.aws.amazon.com/AmazonS3/latest/userguide/security-best-practices.html) | Private access, encryption and constrained permissions are separate controls. | Terraform bucket public-access block, ownership enforcement, KMS encryption, TLS and scoped task/endpoint policies. |
| [Storage limitation](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/data-protection-principles/a-guide-to-the-data-protection-principles/storage-limitation/) | There is no universal retention duration; purpose and policy govern it. | Configurable 90-day project policy plus owner deletion; no claim of jurisdiction-specific legal compliance. |

Registry verification selected `chrislusf/seaweedfs:4.48@sha256:4e61d15fd35994cb1e43e1e553dff106794841fd9a99ade2fc8c8bfce4d7872d`. Its S3 API is a local counterpart; AWS IAM, KMS and managed durability remain separate cloud properties. Scanner pin, platform and runtime evidence are recorded with implementation. Object PUT and database commit are not atomic; [ADR 0006](decisions/0006-durable-document-lifecycle.md) defines recovery beyond the existing outbox.

Cloud scanning uses [GuardDuty Malware Protection for S3](https://docs.aws.amazon.com/guardduty/latest/ug/how-malware-protection-for-s3-gdu-works.html) and its [tag-based access gate](https://docs.aws.amazon.com/guardduty/latest/ug/tag-based-access-s3-malware-protection.html), checked 2026-10-18. Only a clean scan result releases access; app roles cannot write scan tags. Local ClamAV is an executable role counterpart, not GuardDuty API parity. The verified local scanner image is `clamav/clamav:1.5.4@sha256:638d90201ee7ee6a82d249a2fc23b132e578673b5f1f2766852b127676ca1ef6` (GPL-2.0 engine; official image is AMD64, requiring emulation on the current ARM64 runtime). Real signature readiness, clean/infected scans and failure behavior require runtime evidence.

## Connected service inspection review — 2026-10-18

The [inspection decision](decisions/0007-service-inspection.md) adds operating
visibility to the existing services. These source and registry findings informed the runtime milestone. Container
startup, authentication and permissions are now checked; populated browser review
of the four new GUIs remains pending. [Runtime evidence](implementation-guide.md#inspection-evidence--2026-10-18)
is distinct from image availability.

| Boundary and selected release | Primary source | Decision supported |
| --- | --- | --- |
| RabbitMQ 4.3.6 | [Management plugin](https://www.rabbitmq.com/docs/management) and [monitoring](https://www.rabbitmq.com/docs/monitoring) | Enable the management plugin offline on the existing pinned alpine release; inspect queue ready/unacknowledged counts, consumers and delivery rates. Authenticate and keep the host HTTP listener on loopback. A confirm does not mean completed work. |
| Flower 2.2.0 | [Configuration](https://flower.readthedocs.io/en/latest/config.html), [Celery monitoring](https://docs.celeryq.dev/en/stable/userguide/monitoring.html) and [events](https://docs.celeryq.dev/en/stable/userguide/monitoring.html#events) | Enable worker/send events explicitly, use authenticated read-only Flower and avoid event-enabling broadcasts by setting `enable_events=false`. Preserve disabled Celery remote control; no new result backend. |
| pgAdmin 9.17 / PostgreSQL 17 | [Container deployment](https://www.pgadmin.org/docs/pgadmin4/latest/container_deployment.html), [server registration](https://www.pgadmin.org/docs/pgadmin4/latest/server_dialog.html) and [PostgreSQL grants](https://www.postgresql.org/docs/17/sql-grant.html) | Pre-register the existing database and connect using a dedicated read-only role; keep credentials outside public JSON/docs and use supported password-file handling. Viewer login does not itself restrict database privileges. |
| SeaweedFS 4.48 | [Pinned admin command](https://github.com/seaweedfs/seaweedfs/blob/4.48/weed/command/admin.go) and [read-only middleware](https://github.com/seaweedfs/seaweedfs/blob/4.48/weed/admin/handlers/admin_handlers.go#L254) and [file reads](https://github.com/seaweedfs/seaweedfs/blob/4.48/weed/admin/handlers/file_browser_handlers.go#L379) | Existing image includes authenticated `weed admin` and read-only request enforcement. Its filer access is cluster-wide, not the application's S3 identity. Treat it as a privileged synthetic-only operator console; verify and disclose raw/quarantined file read/download access. Authentication and read-only writes do not imply the application's owner or malware gate. |
| ClamAV 1.5.4 | [Daemon usage](https://docs.clamav.net/manual/Usage/Scanning.html) and [official Docker deployment](https://docs.clamav.net/manual/Installing/Docker.html) | Use the official `clamdtop` terminal dashboard for scan queue/memory/signature information, the pinned image contains `/usr/bin/clamdtop`; supplement with health/version checks and application scan events. Do not publish the unauthenticated daemon port or introduce an unrelated scanning portal. |
| Local relay and Converse provider | [Existing relay implementation](../backend/matching/management/commands/relay_jobs.py), [provider health implementation](../backend/local_converse.py) and [privacy-limited diagnostics](decisions/0004-searchable-observability.md) | Inspect the heartbeat/health contract and correlated service events in OpenObserve. These project-specific processes do not have separate vendor dashboards; the provider remains a deterministic local HTTP contract. |

Registry-confirmed images selected for runtime verification:

- `rabbitmq:4.3.6-alpine@sha256:6931816af1a943f471c038b278835d36692d55dec769232739296bb91b7de0f5` (same base release; enable management offline without changing broker identity/volumes).
- `mher/flower:2.2.0@sha256:b4d3a7b1ed1bba28a32d9ad3c039571c74fe35c2d0ddb9ef7a8d42a3ca38b1bb`.
- `dpage/pgadmin4:9.17@sha256:c332c5f6dfba995d9ebc4af261d93506d6876085d712eaaa3defc8dd1a3f26de`.

RabbitMQ Management is active on the pinned base. SeaweedFS read-only HTTP
access and delete denial were checked; pinned source establishes the privileged
file-read/download boundary. The running scanner image contains `/usr/bin/clamdtop`;
`docker compose exec scanner clamdtop` connected to the daemon and displayed
signature/queue state. Flower stores transport task
state, while this application's wrapper deliberately catches unexpected exceptions
to prevent raw private failures reaching Celery formatting. A green Flower task
therefore cannot establish a successful comparison or application retry semantics;
inspect the durable job record and correlated lifecycle events too.
