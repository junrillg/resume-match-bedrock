# ADR 0001: durable background work

Status: accepted. Scope: one bounded, retryable résumé-evidence job.

## Context and alternatives

Model extraction can be slow or unavailable. A synchronous HTTP request is simpler
but occupies the web worker and makes retry ambiguous. Publishing directly before/after
a database commit creates a broker/database dual-write gap. Kafka adds retained-stream
and replay-consumer capabilities this single work-queue scenario does not require.

## Decision

Use PostgreSQL as the job/result source of truth, a transactional outbox and relay,
RabbitMQ persistent confirmed delivery, and a separate Celery worker. Carry only the
job UUID in messages. Claim under a short row lock; perform provider work outside the
transaction; fence completion with a lease token and enforce a unique job/result link.
Persist attempt/deadline limits; reconcile expired leases and stale queued wakeups.

## Consequences and verification

Admission is eventually processed rather than immediately scored. The relay and
reconciliation logic add complexity, but a failed publish leaves recoverable intent.
Delivery and provider execution can repeat; the guarantee is one committed result,
not exactly-once model invocation or free retries after an uncertain cloud call.

Verify rollback/outbox atomicity, idempotent admission, PostgreSQL concurrent claims,
stale-completion rejection, deletion races, bounded exhaustion, and real broker/worker
pause/restart. [Outbox guidance](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html),
[RabbitMQ confirms](https://www.rabbitmq.com/docs/confirms),
[Celery tasks](https://docs.celeryq.dev/en/stable/userguide/tasks.html).
