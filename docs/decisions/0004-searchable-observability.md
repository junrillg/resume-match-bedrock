# ADR 0004: searchable, privacy-limited observability

Status: accepted for implementation; runtime evidence is required before marking verified.

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

## Consequences and verification

Bound the export queue and network wait; do not flush in the business path. Telemetry
is best effort, not a durable audit ledger. A full buffer or crashed process can lose
logs. Retention and free-disk protection are not a hard named-volume byte quota.
Verify real ingestion/search across API/relay/worker, absence of document/credential
fields, and successful job processing while the viewer is down. Do not promise OSS
SSO/RBAC features belonging to the commercial edition.
[OSS license](https://github.com/openobserve/openobserve/blob/v1.1.1/LICENSE),
[OTLP ingestion](https://openobserve.ai/docs/reference/api/ingestion/logs/otlp/),
[Python exporters](https://opentelemetry.io/docs/languages/python/exporters/).
