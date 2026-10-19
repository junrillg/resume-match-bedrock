# ADR 0010: small initial capacity on the enterprise serving path

Status: implemented locally; Terraform mock-plan verified, not deployed · 2026-10-19

## Decision

Start with small configurable service counts while retaining ADR 0009's asynchronous
gateway, shared fan-out and durable recovery. One million simultaneous users and
100 comparisons/second inform architecture and capacity planning. They are not the
initial deployment size or a claim of tested throughput. Capacity grows through the
same implementation, configuration and replicas.

| Boundary | Implementation work |
| --- | --- |
| Stream ingress | Exact ALB `/api/events/` route to independent ASGI tasks; ordinary API traffic remains separate |
| Wake distribution | Ordered independent, private, encrypted Valkey shards; distinct gateway and publication credentials |
| Database | RDS Proxy with separate application and SELECT-only stream credentials; direct bootstrap; release connections before external work |
| Processing supply | Reused confirmed publisher, productive outbox draining and bounded maintenance cadence |
| Admission | Owner fairness, finite queue/rate budgets and fresh supply/queue-health checks; unchanged-key retries retain recovery semantics |
| Scaling | Small configurable minima/maxima, gateway connection/CPU/memory policies, finite database/network budgets and saturation signals |

The proxy protects connection supply; it does not add database execution capacity.
Its ACM certificate needs an appropriate Amazon Trust Services trust chain, distinct
from the direct RDS instance CA bundle. Database role defaults and connection options
must avoid unnecessary session pinning. Stream credentials may read only identity,
session, stream-state and event tables, never source documents or results.
The runtime application receives data access without schema ownership. Only the
direct, privileged bootstrap can assume the nonlogin migration owner; adopted
application credentials are preserved through the guarded ownership transition.

An overloaded deployment rejects new logical work with bounded retry guidance.
Accepted jobs retain durable execution and cleanup. A connection failure or queue
delay must not restore fleet-wide HTTP polling or discard a saved outcome.

## Deployment and capacity evidence

Terraform defines the same roles and permissions as local execution, with small
defaults, independent service scale controls and credential-free mock-plan checks.
Future larger profiles must fit actual subnet, target, database and provider budgets.
For illustration, a configured 2,000 sockets/process at 70% utilization needs 1,074
balanced replicas to retain one million configured sockets after one of three AZs is
lost. This is arithmetic, not a measured per-process capacity or a provisioning default.

The application starts small. Full-scale load testing, actual AWS provisioning,
account-specific quotas and managed-service failover are separate acceptance evidence.
Local tests must still prove the implemented isolation, bounded resources, failure and
recovery mechanisms. No cloud resources are created by this decision.

## Verification

1. Focused PostgreSQL checks cover role privileges, admission replay/rollback/limits,
   queue-health freshness and connection release; relay checks cover producer reuse
   and productive draining without losing recovery.
2. Terraform format/schema checks and mocked plans assert exact ingress, stable shard
   order, TLS/ACL/secret boundaries, proxy roles, scale controls and finite budgets.
3. Verify the local and cloud nginx startup branches without changing browser behavior.
   Preserve the existing 1,000-stream and queued-comparison evidence where source is
   unchanged; exercise changed processing mechanisms separately.

The PostgreSQL regression run passed 155 tests. Subsequent focused checks passed
20 admission/publishing cases and eight ownership/bootstrap cases after that helper
changed. Fifteen credential-free Terraform mock plans and four nginx checks passed.
The updated live comparison again reached its saved result and notification through
SSE, and its original was physically removed during isolated fixture cleanup.

A bounded local sample confirmed 200 dispatches in 0.538 seconds through one reused
producer and two productive batches. A separate 200-operation, eight-thread SQL
reservation/create/release test measured 174.73 operations/second, p95 72.93 ms.
These are mechanism measurements; they do not measure provider or complete comparison
throughput. The serialized admission budget is evaluated against logical job arrivals,
not connected browser count, and remains bounded by its configured rate and active cap.

The reservation migration uses a coordinated admission/old-worker cutover. Bounded
terminal-reservation repair supplements that procedure; it does not claim arbitrary
mixed-version deletion compatibility. A sampled queue-age gate protects new admission,
while accepted jobs retain recovery and their finite deadline.

## Sources

Accessed 2026-10-19. [RDS Proxy TLS and pooling](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy.howitworks.html),
[proxy credentials](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy-secrets-arns.html),
[connection pinning](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy-best-practices.configuration.html),
[Valkey access control](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/Clusters.RBAC.html),
[ALB quotas](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-limits.html)
and [ECS scale quotas](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/operating-at-scale-service-quotas.html)
support the configuration boundaries. Service offerings and account quotas still need
verification in the selected environment before deployment.
The ownership transition follows [PostgreSQL 17 role attributes](https://www.postgresql.org/docs/17/role-attributes.html),
[REASSIGN OWNED](https://www.postgresql.org/docs/17/sql-reassign-owned.html) and
[RDS administrator capabilities](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Appendix.PostgreSQL.CommonDBATasks.Roles.rds_superuser.html).
