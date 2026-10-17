# One comparison across AWS

A reviewer submits a résumé and receives a durable receipt. Background work produces
checked evidence; the browser reads the saved report. The service choices preserve
those responsibilities while separating public entry, private processing and operations.

![AWS request path: Route 53 resolves the endpoint, an ALB reaches the ECS/Fargate application, RDS commits admission, a relay publishes to Amazon MQ, a worker invokes Bedrock, then fences the RDS result for browser reads.](assets/enterprise-context.svg)

The **1–7** numbers match the [local execution](architecture.md). Solid arrows carry
requests or work; dashed arrows identify lookup or supporting relationships. Status
reads begin after acceptance and can overlap relay and worker execution.
**Local execution verified; AWS deployment defined in Terraform, not deployed.**

## 1–2 · Reach the application and accept work

**Route 53** answers the browser's DNS lookup with the load balancer address; it does
not proxy the résumé. **ACM** supplies the certificate used by the **Application Load
Balancer**, which terminates HTTPS and forwards healthy traffic to the application.

**ECS** maintains application tasks on **Fargate**, which provides container compute.
nginx serves React and proxies `/api/jobs/` to Gunicorn/Django over task-local localhost.
Django checks session, CSRF, bounded input and retry identity. **RDS PostgreSQL** commits
the job and outbox together before `202 Accepted` returns through the same HTTP path.
The receipt means durable admission, not successful model processing.

## 3–4 · Dispatch committed work

A separate **ECS/Fargate relay** reads committed RDS outbox entries and publishes only
the job UUID to **Amazon MQ for RabbitMQ** using TLS. The relay marks dispatch sent
after confirmation; the worker may already receive delivery before that update commits.

Amazon MQ supplies managed RabbitMQ with the same AMQP responsibility as the local
broker. The application declares `resume.match.quorum`; the AWS cluster spans three
availability zones. Confirmation concerns broker acceptance, not report completion.
RDS and reconciliation remain authoritative when publication or delivery repeats.

## 5–6 · Extract, check and save

The **ECS/Fargate worker** obtains a short RDS lease and calls **Amazon Bedrock Converse**
through a **PrivateLink interface endpoint**. The bounded request carries document data,
requested skills and safe correlation UUIDs. Bedrock returns proposed evidence to the
worker; it does not write to RDS or decide the score.

Application code verifies source quotes. A second RDS transaction checks the current
lease, calculates weighted coverage, saves one report and clears temporary source text.
Transient failure has a finite retry/deadline budget; invalid evidence produces a safe
failed state. Provider calls may repeat, even though committed reports remain unique.

## 7 · Read the outcome

React sends owner-scoped `GET /api/jobs/` through the same HTTPS entry. Django reads
RDS state and returns status plus any completed report. React renders the score and
quotes, or a safe failure category. It polls one request at a time while work is active;
no model response is pushed directly to the browser.

## What supports the path

![Supporting AWS responsibilities grouped by launch, private connectivity, access protection and operations. These are dependencies rather than consecutive résumé-processing hops.](assets/aws-support.svg)

| Responsibility | Service → next receiver | Why it is here |
| --- | --- | --- |
| Launch trusted images | **ECR** supplies application images to Fargate. The **S3 gateway endpoint** permits ECR's layer downloads. | Private tasks can start without a general internet egress route; there is no résumé S3 bucket. |
| Connect privately | **VPC** subnets, routes and security groups restrict application, database and broker traffic. The internet gateway serves public ALB subnets; tasks remain private. **PrivateLink** endpoints reach ECR, secrets, logs and Bedrock. | Each connection has an explicit network destination and port. Endpoints do not replace IAM or TLS. |
| Authorize actions | **IAM** separates task execution, worker invocation and one-off database bootstrap roles. | Image/secret/log permissions differ from the worker's model permission; the browser receives neither. |
| Supply secrets | **Secrets Manager** provides configured values to task startup; bootstrap retrieves the RDS-managed master secret. | Normal application processes use a restricted database role; secret changes require the documented rollout. |
| Protect storage | **KMS** keys protect the configured data, image repositories, secrets and logs. | Encryption access is granted to the service or role that needs it, not modeled as a new call for every form action. |
| Diagnose and alert | **CloudWatch** receives container logs and the configured metric alarms. | Safe request/job IDs connect processing boundaries; persisted RDS state remains the business ledger. |

Alarm notifications use optional existing SNS destinations; without them alarms remain
visible in CloudWatch without sending notifications. DNS validation, certificate issuance,
image publication, secret provisioning and database
bootstrap happen before normal traffic. They are [deployment steps](../infra/terraform/README.md),
not hidden request handlers. The [resource map](#implementation-and-terraform) identifies exact wiring.

## Local counterpart and limits

| Business role | Local execution | AWS deployment | What local evidence does not prove |
| --- | --- | --- | --- |
| 1–2 Entry/compute | Browser → loopback nginx → Django containers | Route 53 + ACM + ALB → ECS/Fargate task | Public DNS, certificate issuance, cloud ingress, scaling or federation |
| 2/6/7 Durable ledger | Real PostgreSQL | RDS PostgreSQL | Managed backups/restoration, failover or cloud TLS connectivity |
| 3–4 Dispatch | Relay + single-node RabbitMQ quorum queue | Relay task + three-zone Amazon MQ RabbitMQ cluster | Multi-node replication or zone failure recovery |
| 5 Evidence API | boto3 → separate HTTP Converse contract service | Worker role → private Bedrock runtime | IAM, model quality, quotas, billing or managed inference |
| Diagnostics | Safe OTLP events → searchable OpenObserve OSS | Container stdout → CloudWatch logs/alarms | Cloud log delivery, alert response or equivalent dashboards |
| Supporting controls | Compose networking, ignored owner-only secrets, local images | VPC/endpoints, IAM, Secrets Manager, KMS and ECR | Managed access/encryption or deployment behavior |

The local provider accepts the actual SDK's Converse request and returns deterministic
literal evidence. It is neither a general AWS emulator nor an implementation of an LLM.
UUID metadata correlates the provider's `provider.completed` event with API, relay and worker.
## Implementation and Terraform

<details>
<summary>Exact resource and application map</summary>

Application links pin the verified runtime; infrastructure links pin the deployment
configuration. A Bedrock model and delegated DNS zone are account-owned prerequisites;
Terraform does not create a model or take over the parent zone.

| Step / responsibility | Terraform definition | Application or wiring |
| --- | --- | --- |
| 1 DNS/TLS/entry | [DNS record](https://github.com/junrillg/resume-match-bedrock/blob/e2bfaa2d3302e7ea54beda759ba44d22cd05f03f/infra/terraform/ingress.tf#L57) · [ACM validation](https://github.com/junrillg/resume-match-bedrock/blob/e2bfaa2d3302e7ea54beda759ba44d22cd05f03f/infra/terraform/ingress.tf#L1) · [ALB/listener/target](https://github.com/junrillg/resume-match-bedrock/blob/e2bfaa2d3302e7ea54beda759ba44d22cd05f03f/infra/terraform/ingress.tf#L20) | [nginx proxy](https://github.com/junrillg/resume-match-bedrock/blob/4e9432e597d4d4d68cf8257110d4ca3f50cad0e4/frontend/nginx.conf#L40) |
| 1–2/3/5 Compute | [aws_ecs_cluster.main](https://github.com/junrillg/resume-match-bedrock/blob/e2bfaa2d3302e7ea54beda759ba44d22cd05f03f/infra/terraform/compute.tf#L68) · [aws_ecs_task_definition.service / aws_ecs_service.main](https://github.com/junrillg/resume-match-bedrock/blob/e2bfaa2d3302e7ea54beda759ba44d22cd05f03f/infra/terraform/compute.tf#L75) | [images, commands and task-local proxy](https://github.com/junrillg/resume-match-bedrock/blob/e2bfaa2d3302e7ea54beda759ba44d22cd05f03f/infra/terraform/compute.tf#L1) |
| 2/6/7 Durable ledger | [aws_db_instance.main + TLS parameter/subnet groups](https://github.com/junrillg/resume-match-bedrock/blob/e2bfaa2d3302e7ea54beda759ba44d22cd05f03f/infra/terraform/data.tf#L46) | [admission](https://github.com/junrillg/resume-match-bedrock/blob/4e9432e597d4d4d68cf8257110d4ca3f50cad0e4/backend/matching/views.py#L153) · [fenced completion](https://github.com/junrillg/resume-match-bedrock/blob/4e9432e597d4d4d68cf8257110d4ca3f50cad0e4/backend/matching/jobs.py#L65) |
| 3–4 Messaging | [aws_mq_broker.main](https://github.com/junrillg/resume-match-bedrock/blob/e2bfaa2d3302e7ea54beda759ba44d22cd05f03f/infra/terraform/data.tf#L88) | [queue declaration](https://github.com/junrillg/resume-match-bedrock/blob/4e9432e597d4d4d68cf8257110d4ca3f50cad0e4/backend/config/celery.py#L11) · [publish/confirm](https://github.com/junrillg/resume-match-bedrock/blob/4e9432e597d4d4d68cf8257110d4ca3f50cad0e4/backend/matching/jobs.py#L147) |
| 5 Model access | [aws_vpc_endpoint.bedrock](https://github.com/junrillg/resume-match-bedrock/blob/e2bfaa2d3302e7ea54beda759ba44d22cd05f03f/infra/terraform/network.tf#L172) · [aws_iam_role_policy.bedrock](https://github.com/junrillg/resume-match-bedrock/blob/e2bfaa2d3302e7ea54beda759ba44d22cd05f03f/infra/terraform/identity.tf#L37) | [Converse request/client](https://github.com/junrillg/resume-match-bedrock/blob/4e9432e597d4d4d68cf8257110d4ca3f50cad0e4/backend/matching/services.py#L141) · [local HTTP operation](https://github.com/junrillg/resume-match-bedrock/blob/4e9432e597d4d4d68cf8257110d4ca3f50cad0e4/backend/local_converse.py#L43) |
| Network | [VPC, gateway, subnets, routes and security groups](https://github.com/junrillg/resume-match-bedrock/blob/e2bfaa2d3302e7ea54beda759ba44d22cd05f03f/infra/terraform/network.tf#L5) · [service/S3 endpoints](https://github.com/junrillg/resume-match-bedrock/blob/e2bfaa2d3302e7ea54beda759ba44d22cd05f03f/infra/terraform/network.tf#L163) | [private task wiring](https://github.com/junrillg/resume-match-bedrock/blob/e2bfaa2d3302e7ea54beda759ba44d22cd05f03f/infra/terraform/compute.tf#L97) |
| Images | [aws_ecr_repository.image](https://github.com/junrillg/resume-match-bedrock/blob/e2bfaa2d3302e7ea54beda759ba44d22cd05f03f/infra/terraform/data.tf#L112) | [immutable digest references](https://github.com/junrillg/resume-match-bedrock/blob/e2bfaa2d3302e7ea54beda759ba44d22cd05f03f/infra/terraform/compute.tf#L1) |
| Identity and secrets | [execution / task roles](https://github.com/junrillg/resume-match-bedrock/blob/e2bfaa2d3302e7ea54beda759ba44d22cd05f03f/infra/terraform/identity.tf#L13) · [aws_secretsmanager_secret.app](https://github.com/junrillg/resume-match-bedrock/blob/e2bfaa2d3302e7ea54beda759ba44d22cd05f03f/infra/terraform/data.tf#L22) | [bootstrap_cloud_db.Command.handle](https://github.com/junrillg/resume-match-bedrock/blob/e2bfaa2d3302e7ea54beda759ba44d22cd05f03f/backend/matching/management/commands/bootstrap_cloud_db.py#L18) |
| Encryption | [aws_kms_key.main](https://github.com/junrillg/resume-match-bedrock/blob/e2bfaa2d3302e7ea54beda759ba44d22cd05f03f/infra/terraform/data.tf#L1) | [encrypted RDS, MQ, repositories and logs](https://github.com/junrillg/resume-match-bedrock/blob/e2bfaa2d3302e7ea54beda759ba44d22cd05f03f/infra/terraform/data.tf#L33) |
| Logs/alarms | [service/database log groups](https://github.com/junrillg/resume-match-bedrock/blob/e2bfaa2d3302e7ea54beda759ba44d22cd05f03f/infra/terraform/data.tf#L33) · [metric filters, alarms and saved query](https://github.com/junrillg/resume-match-bedrock/blob/e2bfaa2d3302e7ea54beda759ba44d22cd05f03f/infra/terraform/monitoring.tf#L1) | [safe emit](https://github.com/junrillg/resume-match-bedrock/blob/4e9432e597d4d4d68cf8257110d4ca3f50cad0e4/backend/matching/telemetry.py#L66) |

</details>

The [deployment runbook](../infra/terraform/README.md) covers account-owned prerequisites,
image and secret preparation, bootstrap, protected remote state, plan/apply review and
endpoint smoke checks. Format/schema and mocked-plan checks validate configuration,
not a successful AWS deployment. Cloud deployment and model behavior remain unmeasured.

## Deliberate omissions

No CloudFront or API Gateway is required by this single same-origin ALB entry. nginx
and Django share an ECS task, so Cloud Map adds no needed discovery. Temporary bounded
source text already belongs to the job transaction; no document bucket is needed.
Redis adds no demonstrated cache role; Kafka has no retained-stream/replay consumer;
Step Functions would duplicate the existing persisted job lifecycle.

See [the decision](decisions/0005-aws-service-journey.md), [research](research.md) and
[recovery sequence](architecture.md#failure-and-recovery) for the guarantees and tradeoffs.
