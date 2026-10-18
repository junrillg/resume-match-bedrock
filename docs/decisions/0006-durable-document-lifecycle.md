# ADR 0006: durable originals and document lifecycle

Status: accepted design; implementation and runtime verification pending. Supersedes the source-discard decision in ADR 0002 and the application-storage exclusion in ADR 0005.

## Decision

Keep exact PDF/TXT originals and UTF-8 snapshots of pasted input in private object storage. PostgreSQL owns document identity, owner, opaque object key, checksum, size/type, lifecycle, extraction version, expiry and comparison records. A comparison references a document; deleting a comparison keeps its reusable original. Existing source-cleared jobs remain readable with source unavailable; migration cannot recover discarded bytes.

The API accepts bounded originals through the existing multipart endpoint. Reserve upload/document/job identity before object PUT; finalize queued work and its outbox only after storage confirmation. Replayed requests use the same reservation and exact-byte fingerprint. Interrupted uploads expire into durable cleanup intent. A successful S3 call is not a PostgreSQL transaction.

The worker fetches and checks the stored bytes, passes a fail-closed malware gate, then parses and caches validated extraction before evidence processing. Reuse may use a matching parser-version cache; explicit reprocessing reads and verifies the source again. Download is owner-authorized, clean-only, attachment-only and no-store. No document body, filename, storage key or signed URL belongs in queue messages or logs.

Document deletion first tombstones access and fences related work, then retries physical object deletion while preserving cleanup identity. Expiry follows the same path. Upload completion racing deletion must leave no resurrected original or result. Recovery reconciles reserved uploads and deletion intents; exception-handler compensation alone is insufficient.

## Lifecycle policy

The project defaults to 90 days for originals, extracted text and associated comparisons/results, with owner deletion available earlier. This duration is configurable project policy, not a universal enterprise or legal standard. Abandoned upload reservations expire after one hour. Rejected files are inaccessible and scheduled for deletion. Operational logs retain their existing three-day policy; cloud database backups retain the configured seven-day window and require restore-time deletion/expiry reconciliation. Tombstones retain only cleanup identifiers until deletion is confirmed; do not retain source indefinitely as an audit artifact.

Use an unversioned originals bucket with immutable generated object keys. This avoids delete markers hiding retained historical versions; production backup/versioning changes must preserve erasure and recovery semantics. AWS lifecycle provides an expiry backstop; application expiry denies access and cleans relational derived data too. Infrastructure deletion never silently destroys retained documents.

## Local and AWS boundaries

Compose adds persistent SeaweedFS S3-compatible storage and a private ClamAV daemon. Existing PostgreSQL, transactional outbox, RabbitMQ and leased worker remain. There is no local S3-notification claim. Terraform separately wires the private S3 bucket, encryption, task permissions, endpoint policy and GuardDuty Malware Protection for S3. GuardDuty scans the protected prefix and writes scan-result tags; cloud processing requires NO_THREATS_FOUND, and application roles cannot forge that tag. EventBridge is a scan integration dependency, not an invented extra comparison queue. This avoids running a signature-update system in private application subnets. The existing S3 endpoint for ECR layers does not by itself grant document access.

Local scanner engine/definition readiness and supported machine architecture must be checked. Malware scanning reduces risk; it does not prove a file harmless. Exact-byte retrieval, bounded parsing and attachment delivery remain required controls. No live AWS deployment or managed-service guarantee is inferred from Compose or mocked Terraform plans.

## Acceptance

- Exact original survives normal restart and downloads byte-for-byte; owner isolation holds.
- Upload once, compare against another requirement set, and explicitly reprocess the stored source.
- Same-key replay does not create another logical job; different original bytes conflict.
- Object-write/DB-finalization failures, missing/corrupt objects and abandoned uploads reconcile without ready-but-missing sources or untracked orphans.
- Scanner unavailable/infected input cannot reach parsing/provider/download; safe terminal state is visible.
- Deletion/expiry denies access immediately, fences late work, retries storage deletion and removes derived content.
- Correlated, payload-free events are searchable; Terraform checks private access, role separation, encryption, expiry and application wiring.

## Alternatives

Temporary database text loses original fidelity and prevents library reuse. Database blobs combine unrelated storage responsibilities and complicate large-file growth. Browser presigned upload is valid at larger limits, but adds finalization and URL controls without a benefit at 1 MiB. LocalStack is useful for broader AWS API emulation when its current access requirements fit; SeaweedFS is sufficient for this S3 client boundary. Neither emulator proves AWS IAM or managed durability.

Sources and checked dates are in [research](../research.md#durable-document-storage-review--2026-10-18).
