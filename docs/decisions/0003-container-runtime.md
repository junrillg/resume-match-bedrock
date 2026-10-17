# ADR 0003: one-command local runtime

Status: accepted. Scope: reproducible single-node teaching environment.

## Context and alternatives

Starting frontend, API, database, broker and worker manually obscures the architecture
and creates setup drift. Replacing PostgreSQL/RabbitMQ with test fakes would hide the
very transaction and delivery semantics the lab teaches.

## Decision

Use Docker Compose with pinned images, real PostgreSQL and RabbitMQ, startup health
checks, a one-shot migration service, non-root application containers, private broker/DB
ports and a loopback web entry point. Generate ignored owner-only local credentials
once. Normal stop/restart preserves named volumes and existing credentials.

## Consequences and verification

Docker is required, and a local machine has finite resources. The setup demonstrates
one-node persistence and process separation, not multi-node availability or a cloud
deployment. SQLite remains only an optional fast unit-test path; lock/concurrency
acceptance runs on PostgreSQL. Verify clean startup, migration, API/CSRF through nginx,
restart persistence, and the documented helper without exposing secret values.
[Compose readiness](https://docs.docker.com/compose/how-tos/startup-order/),
[Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/).
