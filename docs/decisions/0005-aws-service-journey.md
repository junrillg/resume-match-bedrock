# AWS deployment with an executable local counterpart

## Context

A reviewer needs the same submission, durable handoff and visible report across local
and AWS deployments. The AWS architecture must account for ingress, compute, data,
messaging, model access, identity and operations. A direct browser-to-model diagram
would omit those responsibilities. This decision records the next implementation;
the deployment is not an observed AWS environment.

## Decision

Use Route 53 DNS and ACM certificates with an HTTPS Application Load Balancer. An
ECS Fargate application task contains nginx and Django on a shared localhost network.
Separate Fargate relay/worker services use private RDS PostgreSQL and Amazon MQ for
RabbitMQ. Only the worker invokes the selected Bedrock model through a private runtime
endpoint. The database continues to own job state, fencing and the committed report.

Keep supporting services beside this request path: ECR supplies images; Secrets Manager
supplies startup configuration; IAM separates execution and worker permissions; KMS
protects configured storage/secrets/logs; CloudWatch receives process logs. Private VPC
endpoints support ECR, Secrets Manager, logs and Bedrock. ECR layers also require an S3
gateway endpoint; this is not a document bucket. Three availability zones accommodate
the managed RabbitMQ cluster. Cloud failover remains unmeasured until deployment.

Compose retains real PostgreSQL, RabbitMQ and OpenObserve. A separate local HTTP
Converse contract service exercises boto3 request/response handling. It supplies
deterministic evidence, not model intelligence or AWS IAM/network emulation. Local
and AWS flows share business step numbers and an explicit parity crosswalk.

## Alternatives and consequences

Amazon MQ preserves the existing AMQP publisher-confirm/acknowledgement contract.
SQS is a valid different design, but changing transport would require new visibility,
delivery and recovery semantics. A new named quorum queue avoids changing the type
of an existing classic queue in place. Existing volumes and published history remain.

CloudFront, application S3 storage, API Gateway, Cloud Map, Redis, Kafka and Step
Functions add no required responsibility here. The document already has bounded
temporary database retention; nginx and Django share an ECS task. Current LocalStack
requires licensed authentication, so it is not the no-account local runtime.

Terraform defines resources and application wiring separately under `infra/terraform/`.
RDS manages its master password. A one-off bootstrap uses that identity to create a
restricted application database role and migrate before normal services start.
Broker credentials can appear in Terraform state; protected encrypted remote state
and restricted access are deployment prerequisites. Sensitive values never become
committed example inputs or outputs. Destructive cleanup is separate from startup.

## Verification

Local acceptance follows a real submission through proxy, API, database, outbox,
broker, worker, HTTP provider and status reads; it includes provider/queue failure
and correlated logs. Terraform format, validation and mocked plan assertions check
wiring without provisioning. They do not prove AWS quotas, model availability,
multi-AZ recovery or a successful deployment. The deployment runbook separates those
future checks. Frontend changes follow the incumbent design using Impeccable.

## Sources checked 2026-10-17

- [Fargate networking](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-task-networking.html): same-task localhost and private image-pull networking.
- [Amazon MQ 4.3](https://docs.aws.amazon.com/amazon-mq/latest/developer-guide/rabbitmq-43.html), [broker practices](https://docs.aws.amazon.com/amazon-mq/latest/developer-guide/best-practices-broker-setup.html) and [cluster deployment](https://docs.aws.amazon.com/amazon-mq/latest/developer-guide/rabbitmq-broker-architecture.html).
- [RDS PostgreSQL TLS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.SSL.html), [ECS secret injection](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/secrets-envvar-secrets-manager.html) and [Bedrock private endpoints](https://docs.aws.amazon.com/bedrock/latest/userguide/vpc-interface-endpoints.html).
- [MQ Terraform resource](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/mq_broker.html): credential state and user-change limitations.
- [Terraform provider mocking](https://developer.hashicorp.com/terraform/language/tests/mocking): configuration evidence without provisioning.
- [LocalStack authentication](https://docs.localstack.cloud/aws/getting-started/auth-token/): local counterpart selection.
