# ADR 0007: connected service inspection

Status: accepted and implemented in `17ba0eb`. Runtime access, permissions and
synthetic processing are verified. Authenticated populated RabbitMQ, Flower and
SeaweedFS views passed; pgAdmin final connection/record review remains pending.

The current delivery extension adds a read-only Valkey viewer and stream tables under [ADR 0009](0009-event-driven-completion.md). The original inventory below records the earlier inspection milestone.

## Context

OpenObserve connects safe lifecycle logs, but does not expose RabbitMQ backlog,
Celery transport activity, relational state or object-storage inventory. Every
service selected for this lab needs a usable inspection surface and an explanation
of what its observations mean. A separate GUI for every process is unnecessary
when an existing viewer and a supported health/CLI interface cover its boundary.

## Decision

Start RabbitMQ Management, Flower, pgAdmin and an authenticated read-only
SeaweedFS `weed admin` operator console with the normal Compose startup. Keep OpenObserve and
the existing application. The complete inventory is in [the design](../design.md#service-inspection).
Use the registry-verified Flower 2.2.0 and pgAdmin 9.17 images, the matching
RabbitMQ 4.3.6 alpine base with its management plugin enabled offline, and existing SeaweedFS
4.48. Record exact pins in [research](../research.md). SeaweedFS authentication and
read-only behavior are confirmed against the pinned source; verify actual runtime
capabilities rather than infer them from a newer release.

Bind each exposed viewer to `127.0.0.1`. Generate separate viewer credentials through the
existing owner-only `.env` upgrade path, preserve initialized secrets/volumes, and
publish no credential values or credential-bearing URLs. Give database inspection
a dedicated read-only role rather than PostgreSQL bootstrap credentials. Treat
storage administration as a privileged synthetic-only operator surface. Its
cluster-wide filer access may expose raw/quarantined originals; read-only prevents
mutation, not owner or malware-gate bypass. Verify and document its actual file
read/download behavior. It is separate from the owner-scoped clean-only application
API and uses a separate read-only login. Keep native database, S3, scanner,
filer/master, gRPC and AMQP sockets off the host; the admin process must not expose
an unauthenticated gRPC listener to the Compose network.

Endpoints are RabbitMQ `:15672/#/queues`, Flower `:5555/tasks`, pgAdmin
`:5050` and SeaweedFS `:23646/files?path=/buckets/resume-originals`, all on loopback.
Enable RabbitMQ Management on the same 4.3.6 alpine release and retain its broker
volume and identity.

Flower consumes explicit Celery task events; no result backend is required. Keep
remote-control disabled and restrict administrative viewer actions. Celery task IDs
and application job UUIDs describe different boundaries. The task carries only the
job UUID. A Flower `SUCCESS` means the Celery function returned: application-owned
retry, rejection and failure remain in PostgreSQL and correlated logs. Never weaken
the existing exception-privacy wrapper to make Flower display business failures.

Relay and the local provider use their supported process/health interfaces and
the existing correlated logs. ClamAV provides the official `clamdtop` terminal
dashboard at the verified image path `/usr/bin/clamdtop`; open it using
`docker compose exec scanner clamdtop` and verify its interactive output. Document missing standalone web GUIs with primary evidence. No Redis or new
queue/database service is added only to supply a dashboard. Existing application screens and browser Network inspection
cover the frontend/API boundary. One-shot initialization and migrations remain
visible as Compose completion states.

## Acceptance

- Normal startup connects all selected viewers; new listeners are loopback-only,
  authenticated and limited to their intended observation role.
- Existing credentials and persisted sources/jobs survive upgrade and ordinary
  restart. Database inspection cannot mutate business rows. Storage operator access is
  explicitly distinguished from the application document-safety boundary.
- A synthetic comparison visibly connects queued backlog, worker activity,
  persisted document/job/outbox/result and object inventory. Resume processing and
  verify the expected 80% report. Record actual queue/task/job identity mapping.
- Inspect a controlled safe failure and explain the difference between transport
  task completion and durable business outcome. Restore stopped services afterward.
- Verify live interfaces against meaningful activity, and record any unavailable
  screen or capability as a blocker rather than claiming empty startup as coverage.
- Keep public architecture/operating docs and diagrams aligned with actual runtime
  and observed evidence. No live AWS or paid calls.

## Consequences

Ten focused checks and real service/API observations passed, including an 80%
default comparison while pgAdmin was stopped, an EICAR document rejection and the
interactive scanner dashboard. RabbitMQ, Flower and SeaweedFS authenticated browser views passed; pgAdmin
registration was corrected and awaits final connection/record review. [Recorded evidence](../implementation-guide.md#inspection-evidence--2026-10-18)
distinguishes those checks.

The stack gains local operating visibility and additional container/resource cost.
Viewer event histories are diagnostic and may be incomplete across outages or
restarts; PostgreSQL remains authoritative for business state. Loopback binding
is a local-development boundary, not a production access architecture. Real data,
remote exposure and managed-service administration require separate authorization
and controls. A working dashboard does not establish enterprise readiness.
