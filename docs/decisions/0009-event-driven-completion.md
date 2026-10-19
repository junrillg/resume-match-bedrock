# ADR 0009: durable events and asynchronous browser delivery

Status: accepted design; implementation in progress · 2026-10-19

## Context

The design target is **1,000,000 simultaneously connected users**, with browser tabs,
job arrivals and completion throughput budgeted separately. The existing client makes
four or five list/detail requests per refresh, then waits one second while work is
active. Five hundred visible tabs can therefore approach 2,000–2,500 requests/second.
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

Keep streaming outside Django's regular request handler. In the pinned Django/asgiref
implementation, thread-sensitive work can retain a thread for a streamed response's
lifetime. The gateway uses bounded authentication/replay work, bounded subscriber queues,
connection limits, heartbeats without per-client database polling, session expiry and
revocation handling, and explicit origin/Host/security checks. Ordinary Django API calls
remain short-lived. Proxy buffering is disabled only on the stream route.

One visible authenticated tab opens one stream. Initial/reconnect reads reconcile the
workspace; events refresh affected resources rather than all lists every second.
Hidden/offline tabs disconnect. A slow fallback is reserved for unavailable streaming.
Completion preserves drafts and unrelated routes; only the same processing page may
transition automatically. The durable inbox still recovers closed-browser completion.

## Scale and failure contract

The million-connection target is an architectural requirement, not a measured result.
Implement horizontal gateway/relay scaling, bounded database work and admission,
replay retention, overload behavior, observable connection/event lag and deployment
configuration now. Parameter changes and additional replicas must expand the same
delivery path; periodic full-workspace polling is not the production architecture.

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

## Milestones

1. Publish researched transport/capacity design and upgrade the reusable skill.
2. Implement and verify the complete event ledger, relay, gateway, Compose/viewers and
   event-driven browser path together; commit this runnable behavior.
3. Wire the same path into Terraform with private encrypted fan-out, independent scale
   controls, connection/pool budgets and alarms; run credential-free mock plan checks.
4. Publish professional execution/scale diagrams and exact implementation evidence;
   update private learning traces and the shared technology reference library.

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
