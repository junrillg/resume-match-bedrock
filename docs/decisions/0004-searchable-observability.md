# ADR 0004: searchable, privacy-limited observability

Status: implemented and verified with real search, viewer outage and isolated clean startup.

## Context and alternatives

An HTTP response does not show how a queued job crossed services or recovered. Console
logs alone are awkward for tracing one job. Graylog or Grafana/Loki can serve broader
operational requirements, but add dependencies this focused flow does not need.

## Decision

Use the explicitly OSS OpenObserve v1.1.1 image and standard OpenTelemetry batched HTTP
log export. The viewer runs in the same Compose stack with private local credentials
and a loopback port. Log fixed lifecycle events plus safe request/job IDs, service,
state, attempt, elapsed time and error category. Never attach a root log handler that
could export arbitrary request/provider exceptions or document text.

The base image is pinned to `sha256:dae91bc1f9d4c11db54e924d8d25bac7f6c50e080a8f06fc90d9468eaab81b67`.
It contains no shell/curl/wget; a pinned static BusyBox probe checks `/healthz` in the
nonroot derivative image. The viewer has a 1 GiB container limit, 64 MiB memtable,
16 MiB in-memory file and 256 MiB query-pool limits, with caches disabled. Retention is
three days, checked hourly, with a 120-minute file-delete delay and a 1024 MiB free-space floor.

Python SDK/exporter 1.45.1 initializes lazily per process, with a fresh lock after fork.
Each process owns a 256-record buffer, batches of 32, a one-second schedule, and a
0.5-second exporter HTTP deadline. `shutdown_on_exit=False` avoids draining business
processes on exit. SDK-internal error logging is suppressed because response/error text
may be sensitive; only the dedicated allowlisted lifecycle events are exported.

## Consequences and verification

Bound the export queue and network wait; do not flush in the business path. Telemetry
is best effort, not a durable audit ledger. A full buffer or crashed process can lose
logs. Retention and free-disk protection are not a hard named-volume byte quota.
Verify real ingestion/search across API/relay/worker, absence of document/credential
fields, and successful job processing while the viewer is down. Do not promise OSS
SSO/RBAC features belonging to the commercial edition.

Actual search returned eight non-partial hits across API, relay and worker for a
successful 80% comparison and a controlled deadline failure. Source markers were absent.
The current PostgreSQL suite has 62 passing tests, including privacy, export-outage,
fork/reset, bounded slow-export queue and post-commit/rollback behavior. The startup
helper has three passing checks for help, fresh setup, secret preservation and safe upgrades.
With the viewer stopped, HTTP admission took 0.057 seconds and the real worker completed
an 80% comparison in 1.643 seconds. After restart, all eight original lifecycle records
remained searchable with `is_partial=false`; full records contained no source markers,
titles, forbidden document fields or credential values.

A unique Compose project with new database/broker/log volumes passed one-command startup,
seven health checks, its first 80% job and four real searchable lifecycle events. Only
those temporary volumes were removed, then the original stack/history was restored.
The existing private `.env` remained byte-for-byte unchanged during this clean-data test.
[OSS license](https://github.com/openobserve/openobserve/blob/v1.1.1/LICENSE),
[OTLP ingestion](https://openobserve.ai/docs/reference/api/ingestion/logs/otlp/),
[Python exporters](https://opentelemetry.io/docs/languages/python/exporters/).
