# One comparison across AWS

The AWS design preserves the same seven business steps as local execution: a reviewer submits or reuses an original, background work validates evidence, and the browser reads a durable report. Original objects and application records have separate owners; neither a queue nor the model owns the result.

![AWS request path and concurrent report reads using official service icons.](assets/enterprise-context.svg?v=durable-originals-20261018)

**Local execution verified; AWS deployment defined and mock-plan checked, not deployed.** The [local architecture](architecture.md) and this view share **1 Submit · 2 Accept · 3 Relay · 4 Queue · 5 Process · 6 Save · 7 Read**.

## 1–2 · Reach the application, store the original and admit

Route 53 resolves the endpoint; it does not proxy documents. ACM supplies the ALB certificate. The HTTPS load balancer reaches a private ECS/Fargate task containing nginx and Django, which validates session, CSRF, ownership, limits and retry identity.

RDS PostgreSQL first records a new source reservation and upload lease. The application PUTs exact bytes into private S3, then commits pending document + queued job + outbox in RDS. Object storage and RDS are separate consistency boundaries. A concurrent `202 uploading` means reservation only; the finalized queued receipt confirms storage/admission. Reusing an owned source skips a new PUT.

![S3, EventBridge, GuardDuty, application roles and RDS document-safety boundary.](assets/aws-document-gate.svg?v=durable-originals-20261018)

S3 retains originals under generated `originals/` keys with SSE-KMS. S3 notifications reach EventBridge; GuardDuty Malware Protection for S3 manages its scan rule, reads new objects through its service role, and writes the scan-result tag. This is scanner integration, not an additional comparison queue. Application roles cannot forge the tag. A bucket policy denies original reads until `NO_THREATS_FOUND`, except the scanning role itself.

## 3–4 · Dispatch committed work

The Fargate relay reads the RDS outbox and publishes only the job UUID over TLS to Amazon MQ for RabbitMQ. Confirmation permits its sent marker; worker delivery may begin before that marker commits. The application declares the quorum queue; the managed broker spans three availability zones. RDS owns business state when confirmation or delivery repeats.

## 5–6 · Verify source, extract evidence and save

The Fargate worker obtains an RDS lease, checks the GuardDuty result, fetches S3 bytes and verifies size/SHA-256. Pending scan tags defer processing within the ten-minute job deadline without consuming provider-attempt budget. Failed, unsupported or inaccessible scans fail closed. A parser-version cache avoids repeated parsing; explicit reprocessing reads/parses the retained source again.

Only the worker invokes Bedrock Converse through PrivateLink. Bedrock returns proposed quotes; application code checks source/skill evidence, computes coverage and saves one report after verifying the current document and lease in RDS. Delivery and model calls may repeat, but a stale attempt cannot overwrite the committed result.

## 7 · Return the outcome and manage the source

React polls the owner-scoped jobs collection through the same HTTPS path. Django returns durable state and any saved report; React renders evidence or a safe failure category. Owners can retrieve a ready original through an authorized attachment response, reuse it, reprocess it, or request document deletion. Expiry and deletion fence access/work before the relay retries S3 cleanup. [Lifecycle policy →](document-lifecycle.md)

## Supporting responsibilities

![AWS supporting relationships: launch, network, access, encryption and diagnostics.](assets/aws-support.svg?v=durable-originals-20261018)

| Role | Service and boundary |
| --- | --- |
| Launch | ECR supplies immutable application images. The shared S3 gateway endpoint preserves ECR layer access alongside narrowly scoped document operations. |
| Private networking | VPC routes/security groups restrict peers and ports; PrivateLink reaches ECR, secrets, logs and Bedrock. No NAT or general internet egress is needed by the selected cloud scan design. |
| Authorization | IAM separates execution, bootstrap, API upload/download, worker read/model, relay delete and scanner integration permissions. |
| Configuration | Secrets Manager injects startup secrets. Bootstrap alone retrieves the RDS-managed master secret. |
| Encryption | KMS protects configured objects, database, messaging, images, secrets and logs. S3-mediated permissions are constrained by service and object encryption context. |
| Operations | CloudWatch receives safe container events and configured metric alarms. Optional existing SNS destinations deliver notifications. |

DNS/certificate validation, image publication, secret provisioning, scan-plan readiness and database bootstrap precede normal admission. They are [deployment dependencies](../infra/terraform/README.md), not invented sequential request hops.

## Local counterpart and limits

| Responsibility | Local | AWS | Unproven by local execution |
| --- | --- | --- | --- |
| Entry/compute | Loopback nginx + Django | Route 53/ACM/ALB + ECS/Fargate | Public TLS, scaling and federation |
| Originals | Persistent SeaweedFS S3 API | Private S3 + SSE-KMS | Managed durability, IAM and lifecycle execution |
| Malware gate | ClamAV daemon + definition checks | GuardDuty + EventBridge + clean tag | Same engine, tag timing or AWS enforcement |
| Records/results | PostgreSQL | Multi-AZ RDS PostgreSQL | Restore, failover and real cloud TLS |
| Delivery | Relay + single-node RabbitMQ quorum queue | Relay + three-zone Amazon MQ | Multi-node/zone recovery |
| Evidence API | SDK → deterministic HTTP Converse service | Worker role → private Bedrock | Model quality, quotas, billing or managed inference |
| Diagnostics | OTLP → OpenObserve | Stdout → CloudWatch/alarms | Equivalent dashboards or cloud ingestion |

## Implementation and Terraform

<details>
<summary>Exact source and resource map</summary>

| Boundary | Application | Terraform |
| --- | --- | --- |
| Entry/admission | [admit_jobs / document_download](https://github.com/junrillg/resume-match-bedrock/blob/4c8e18a5c544e142a604336c1c47cf415e90818e/backend/matching/views.py) · route declarations in `backend/config/urls.py` | [ingress.tf](https://github.com/junrillg/resume-match-bedrock/blob/3c05f3fc26d3c838b246eea17c02f0027b91e98f/infra/terraform/ingress.tf) · [compute.tf](https://github.com/junrillg/resume-match-bedrock/blob/3c05f3fc26d3c838b246eea17c02f0027b91e98f/infra/terraform/compute.tf) |
| Object/scanner access | [source and scanner adapter](https://github.com/junrillg/resume-match-bedrock/blob/4c8e18a5c544e142a604336c1c47cf415e90818e/backend/matching/documents.py) | [documents.tf](https://github.com/junrillg/resume-match-bedrock/blob/3c05f3fc26d3c838b246eea17c02f0027b91e98f/infra/terraform/documents.tf): originals bucket, policies, scan role/plan and notifications |
| Metadata/leases/results | [Document / Job / Match](https://github.com/junrillg/resume-match-bedrock/blob/4c8e18a5c544e142a604336c1c47cf415e90818e/backend/matching/models.py) · [relay_once / run_job / finish_job](https://github.com/junrillg/resume-match-bedrock/blob/4c8e18a5c544e142a604336c1c47cf415e90818e/backend/matching/jobs.py) | [data.tf](https://github.com/junrillg/resume-match-bedrock/blob/3c05f3fc26d3c838b246eea17c02f0027b91e98f/infra/terraform/data.tf): RDS and MQ |
| Queue declaration | `backend/config/celery.py` | [data.tf](https://github.com/junrillg/resume-match-bedrock/blob/3c05f3fc26d3c838b246eea17c02f0027b91e98f/infra/terraform/data.tf): three-zone MQ |
| Model boundary | [Converse / evidence validation](https://github.com/junrillg/resume-match-bedrock/blob/4c8e18a5c544e142a604336c1c47cf415e90818e/backend/matching/services.py) | `identity.tf` worker model grant and `network.tf` Bedrock endpoint |
| Network/identity | `backend/config/settings.py` cloud TLS/config | [network.tf](https://github.com/junrillg/resume-match-bedrock/blob/3c05f3fc26d3c838b246eea17c02f0027b91e98f/infra/terraform/network.tf) · [identity.tf](https://github.com/junrillg/resume-match-bedrock/blob/3c05f3fc26d3c838b246eea17c02f0027b91e98f/infra/terraform/identity.tf) |
| Logs | [allowlisted emit](https://github.com/junrillg/resume-match-bedrock/blob/4c8e18a5c544e142a604336c1c47cf415e90818e/backend/matching/telemetry.py) | `monitoring.tf` and `data.tf` log groups |

</details>

The [deployment runbook](../infra/terraform/README.md) covers real-account prerequisites, protected state, images, bootstrap, ACTIVE scanner checks, enablement and preservation. Mocked plans verify configuration invariants, not actual IAM enforcement or scan operation. Capacity, managed failover, restore-time deletion reconciliation, alert ownership and model evaluation remain deployment acceptance work.

Redis, Kafka and Step Functions have no additional required responsibility in this flow. CloudFront, API Gateway and Cloud Map are also omitted deliberately. S3 originals are an implemented design addition under [ADR 0006](decisions/0006-durable-document-lifecycle.md), superseding the earlier storage exclusion in [ADR 0005](decisions/0005-aws-service-journey.md).
