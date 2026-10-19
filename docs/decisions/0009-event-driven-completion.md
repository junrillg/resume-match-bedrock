# ADR 0009: durable events and asynchronous browser delivery

Status: local delivery verified; deployment defined and mock-plan verified, not deployed · 2026-10-19

## Context

The design target is **1,000,000 simultaneously connected users**, with browser tabs,
job arrivals and completion throughput budgeted separately. The prior client made
four or five list/detail requests per refresh, then waited one second while work is
active. Five hundred visible tabs could therefore approach 2,000–2,500 requests/second.
No load evidence justifies that strategy for the target. This decision supersedes
ADR 0008's transport choice; its durable inbox and nonblocking navigation remain.

## Decision

Use a dedicated asynchronous SSE gateway for connected delivery, a PostgreSQL event
ledger for recovery, and Redis-compatible owner-channel fan-out for wakeups.

```text
Submit → API → job + dispatch outbox → RabbitMQ → worker
                                                  ↓
                           PostgreSQL outcome + inbox + delivery event
                                                  ↓
                          event relay → owner wake → ASGI gateway
                                                  ↓
                                SSE → browser → authorized targeted read
```

Events carry identifiers and change kinds, never source content. Per-owner revisions
are allocated under an owner stream-state lock inside the mutation transaction.
An indexed, independently scalable relay marks delivery intents published only after
successful fan-out publication. Repeated wakes are harmless; Redis does not own results.
Subscribe before replay; reconnect and fan-out reconnection reconcile durable state.
Expired cursors request a fresh authorized snapshot rather than silently skipping work.

Partition fan-out across a fixed, ordered set of independent Valkey-compatible shards,
with the same owner mapping for publication, connection leases and subscription. Each
gateway multiplexes one subscription connection per shard. This avoids a browser-sized
Redis connection count and regular Redis Cluster Pub/Sub's all-node broadcast behavior.
Changing the shard map is a coordinated drain/restart with the publication relay paused;
the durable ledger retains changes during that operation.

Keep streaming outside Django's regular request handler. In the pinned Django/asgiref
implementation, thread-sensitive work can retain a thread for a streamed response's
lifetime. The gateway uses bounded authentication/replay work, bounded subscriber queues,
connection limits, heartbeats without per-client database polling, session expiry and
revocation handling, and explicit origin/Host/security checks. Ordinary Django API calls
remain short-lived. Proxy buffering is disabled only on the stream route.

One visible authenticated tab opens one stream. Initial/reconnect reads reconcile the
workspace; events refresh affected resources rather than all lists every second.
Hidden/offline tabs disconnect. Streaming outage does not trigger fleet-wide automatic
HTTP polling: clients reconnect with jitter and expose deliberate refresh/recovery.
Completion preserves drafts and unrelated routes; only the same processing page may
transition automatically. The durable inbox still recovers closed-browser completion.

## Scale and failure contract

The million-connection target is an architectural requirement, not a measured result.
Implement horizontal gateway/relay scaling, bounded database work and admission,
replay retention, overload behavior, observable connection/event lag and deployment
configuration now. Parameter changes and additional replicas must expand the same
delivery path; periodic full-workspace polling is not the production architecture.
Initial deployments start small using this same path. The target informs design;
it does not require provisioning a million connections or claiming unmeasured capacity.

Capacity validation records measured per-replica sockets, memory, threads, database
connections/queries, event latency, reconnect rate and ordinary API responsiveness.
First exercise 500–1,000 real local connections and two gateway processes. Extrapolations
remain planning arithmetic until a distributed run proves the full target. Cloud quotas,
regional failure budgets, provider throughput and job-arrival requirements must be
resolved before claiming deployment capacity; simultaneous users alone supplies none
of those rates. Local execution must not fabricate million-user test evidence.

Verify atomic rollback, concurrent revision ordering, duplicate/out-of-order wakes,
cross-owner denial, replay races, Redis/gateway outage, session revocation/expiry,
source deletion, bounded slow consumers and reconnect bursts. Preserve existing data.

## Local verification

On 2026-10-19, the six-CPU, approximately 12-GiB ARM64 Docker VM ran two gateways
and two independent wake shards alongside the processing stack:

| Experiment | Observation |
| --- | --- |
| 1,000 authenticated connections, 30-second idle interval | 500 connections per gateway; ordinary API latency p95 25.6 ms across 30 probes |
| Five-second full-population idle sample | Zero gateway database requests; 12 threads and approximately 85 MiB per gateway |
| Both wake shards restarted | Recovery in 2.363 seconds; subsequent change reached every owner |
| One durable change per owner | All 1,000 observed within 3.108 seconds, including transaction generation |
| All sockets reconnect together | Full population stable in 32.338 seconds; 686 temporary 503 responses retried; no exhausted clients |
| Real comparison through the running services | HTTP 202 → confirmed broker dispatch → worker/provider → saved score/inbox/event → SSE → authorized result GET; source physically deleted during cleanup |

Reproduce delivery load with `python3 scripts/load_delivery.py --connections 1000
--seconds 30 --restart-fanout`; the command restarts only the local wake shards.
`python3 backend/verify_business_delivery.py --run` verifies one isolated comparison.
Both commands remove their synthetic fixtures. The backend suite passed 133 tests;
the subsequent deletion lock-order correction passed its focused PostgreSQL test.
The frontend passed 66 tests and its production build.

These observations establish a bounded local delivery envelope. They do not establish
100 comparisons/second processing throughput, managed failover, or million-user capacity.

## Milestones

1. Publish researched transport/capacity design and upgrade the reusable skill.
2. Implement and verify the complete event ledger, relay, gateway, Compose/viewers and
   event-driven browser path together; commit this runnable behavior.
3. Wire the same path into Terraform with private encrypted fan-out, independent scale
   controls, connection/pool budgets and alarms; run credential-free mock plan checks.
4. Publish professional execution/scale diagrams, operational references and exact
   implementation evidence for the running delivery path.

## Sources

Accessed 2026-10-19. [Django async](https://docs.djangoproject.com/en/5.2/topics/async/),
[ASGI handler](https://github.com/django/django/blob/stable/5.2.x/django/core/handlers/asgi.py)
and [asgiref context](https://github.com/django/asgiref/blob/main/asgiref/sync.py) support
the separation and thread-budget checks. [Redis Pub/Sub](https://redis.io/docs/latest/develop/pubsub/)
documents at-most-once fan-out; durable recovery is our database responsibility.
[SSE framing](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events)
defines IDs, reconnects and heartbeats. [nginx proxy buffering](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_buffering)
and [ALB connection attributes](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/edit-load-balancer-attributes.html)
inform the proxy and heartbeat configuration. These sources do not establish this
application's capacity; measurements and deployment prerequisites do.

The [Centrifugo million-connection experiment](https://centrifugal.dev/blog/2020/02/10/million-connections-with-centrifugo)
is a published example of gateway replicas and independent Redis shards. It used a
different WebSocket implementation and hardware; its performance numbers do not apply
to this application. Its [fan-out scaling discussion](https://centrifugal.dev/docs/pro/scalability)
also explains why ordinary cluster-wide Pub/Sub is not interchangeable with partitioned
delivery. These sources inform topology, not a capacity guarantee or a dependency on
that product. [AWS ALB quotas](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-limits.html)
and [ECS quotas](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service-quotas.html)
must be checked for the eventual deployment account, without assuming their increases.
