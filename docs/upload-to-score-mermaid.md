# Résumé Match: original upload to scored report (Mermaid)

This page contains actual Mermaid source in fenced `mermaid` blocks. GitHub renders these blocks as diagrams. In Notion, use a code block with its language set to Mermaid and enable its diagram view. Each diagram also has an editable `.mmd` source beside this page under `assets/`.

**Source snapshot:** [`b0b8e58f1776b89a1bf3a7eede0a83266daf63f1`](https://github.com/junrillg/resume-match-bedrock/tree/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1), inspected on 18 October 2026. Later documentation/viewer-only changes do not change the application flow described here. This is source evidence, not proof of an active AWS deployment or a passing runtime/test run.

## How to read it

1. Follow the overview, then the numbered sequence diagrams.
2. `alt` means mutually exclusive branches; `opt` means optional behavior; `loop` repeats work; `par` means independent activities can overlap.
3. SQL transaction boundaries are explicit. Object-storage and provider network calls are outside their surrounding SQL critical sections.
4. `emit()` and `job_event()` record telemetry. `OutboxEvent` plus `publish_job()` dispatch work.

Local Compose uses PostgreSQL, RabbitMQ, Celery, an S3-compatible SeaweedFS service and ClamAV. The AWS configuration defines S3 and GuardDuty scanning. The `demo`, `bedrock-local` and `bedrock` evidence providers are separate choices. Using an S3 API locally does not establish that originals were sent to AWS.

## Coverage boundary

The diagrams cover the application flows for submitting, storing, dispatching, retrieving, safety-checking, parsing, scoring, polling, retrying, recovering, reusing, downloading and deleting an original. They include both newly uploaded and saved-source branches and the material failure/concurrency boundaries. The function registry below links the named application helpers and supporting callbacks.

This is complete within that stated application-flow boundary. Library/SDK/network implementation internals, full infrastructure provisioning bodies, database migration bodies, tests and unrelated account administration are outside scope. Real documents, credentials and environment values are excluded. Creating this map does not complete the learner checkpoint.

## 1. End-to-end overview

Start here. Solid arrows show the application path; dotted arrows explain publisher confirmation and telemetry boundaries.

[Editable Mermaid source](assets/upload-to-score-overview.mmd)

```mermaid
flowchart TB
    B["1. React App.analyze(): validate input, FormData, fingerprint and UUID"]
    H["2. api(): POST /api/jobs/ with CSRF, session cookie and Idempotency-Key"]
    N["3. nginx /api/ proxy -> Gunicorn config.wsgi -> Django middleware and URL routing"]
    V["4. jobs() -> admit_jobs() -> read_match_form() -> read_requirements() / read_source()"]
    A["5. Transaction A: owner lock, deduplication, quota and reservation"]
    NEW{"New original bytes?"}
    PUT["6. put_original() -> client().put_object(): original PDF, TXT or pasted UTF-8"]
    STORE[("Object storage: local SeaweedFS or AWS S3")]
    FINAL["7. Transaction B: document lock then job lock; PENDING document + QUEUED job + OutboxEvent"]
    SAVED["Saved source: ownership/status/expiry check; QUEUED job + OutboxEvent in Transaction A"]
    DB[("PostgreSQL: Document, Job, OutboxEvent, Match, RateBucket")]
    RESP["emit(job.accepted) logs only; serialize_job() -> HTTP 202"]
    RELAY["8. relay_jobs.Command.handle() -> relay_once(): reconcile_documents(), recover_jobs(), due unsent outbox"]
    PUB["9. publish_job(): send_task(matching.process_job), application args = Job UUID"]
    MQ[("RabbitMQ durable direct exchange and quorum queue resume.match.quorum")]
    C["10. Celery process_job() -> run_job() -> claim_job(): DB lease"]
    DT["11. document_text() -> get_original(): retrieve, verify bytes and safety-check"]
    SCAN["GuardDuty tags before GET, or local ClamAV after GET"]
    PARSE["12. Valid parser cache or read_resume(): strict TXT/PDF parsing; mark document READY"]
    EV["13. extract_evidence(): demo literal_evidence() / literal_match(), or Bedrock Converse"]
    PROVIDER["bedrock_request() + correlation_ids() -> boto3.converse(); local ConverseHandler or AWS Bedrock"]
    VAL["14. validate_evidence(): original skills/weights, exact quotes and skill boundaries"]
    FIN["15. finish_job(): document/job locks, lease/deadline/lifecycle guards; calculate_score(); Match + SUCCEEDED"]
    POLL["16. React poll() -> api(): jobs/, matches/, documents/ -> serializers -> MatchResult"]
    REC["Failure/recovery: enqueue_again(), fail_job(), recover_jobs(); stale deliveries cannot commit"]
    LIFE["Reuse, download and deletion: document_download(), tombstone(), reconcile_documents()"]
    B --> H --> N --> V --> A --> NEW
    A <--> DB
    NEW -->|Yes| PUT
    PUT --> STORE
    PUT --> FINAL
    FINAL <--> DB
    NEW -->|No: document_id| SAVED
    SAVED <--> DB
    FINAL --> RESP
    SAVED --> RESP
    DB --> RELAY --> PUB --> MQ --> C
    MQ -. publisher confirmation, not completion .-> PUB
    PUB -. mark sent_at after confirmation .-> DB
    C <--> DB
    C --> DT
    STORE --> DT
    SCAN --> DT
    DT --> PARSE --> EV
    EV --> PROVIDER --> VAL
    EV -->|Demo branch| VAL
    VAL --> FIN
    FIN <--> DB
    RESP --> POLL
    POLL <--> DB
    C --> REC
    REC --> DB
    DB --> LIFE
    LIFE --> STORE
```

## 2. Browser, validation, upload and acceptance

New bytes use two SQL transactions with object PUT between them. Saved-source reuse queues inside the first transaction and skips PUT.

[Editable Mermaid source](assets/upload-to-score-admission.mmd)

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant React as React App.tsx
    participant API as api.ts
    participant Transport as nginx / Gunicorn / Django
    participant View as views.jobs / admit_jobs
    participant Source as read_match_form / read_source
    participant DB as PostgreSQL
    participant Store as SeaweedFS or S3
    User->>React: Submit title, weighted requirements and source
    React->>React: analyze(): preventDefault, validate size/type and duplicate skills
    React->>React: Build FormData, hash file bytes or exact pasted text, or saved ID + reprocess
    React->>React: Same browser fingerprint reuses UUID, changed payload gets new UUID
    React->>API: api(jobs/, POST, FormData, Idempotency-Key)
    API->>Transport: POST /api/jobs/, same-origin cookie and CSRF header
    Note over Transport: nginx body limit -> WSGI -> metadata/security/readiness/session/common/CSRF/auth middleware, URL resolution, CSRF process_view
    Transport->>View: jobs(request) -> admit_jobs(request)
    Note over View: jobs() maps DatabaseError to 503, auth 401, unsupported method 405, invalid UUID/input 400
    View->>Source: read_match_form(request)
    Source->>Source: Allowed and single fields, title, read_requirements(): skills/weights/uniqueness
    alt Saved document selected
        Source->>Source: Parse document UUID and reprocess true/false, reject mixed new input
        Source-->>View: title, requirements, document_id, reprocess, None
    else New file or pasted text
        Source->>Source: read_source(): exactly one input, <=1 MiB, printable name, PDF prefix or UTF-8 TXT
        Note over Source: TXT/paste call read_resume() for early validation, full PDF parsing waits for worker
        Source-->>View: title, requirements, None, False, (original bytes, filename, content_type)
    end
    View->>View: Server SHA-256 of sorted JSON: title, requirements and source identity
    Note over View: New identity = original-byte SHA-256 + content type, saved identity = document ID + reprocess
    View->>DB: BEGIN Transaction A, lock owner row select_for_update()
    opt Saved source
        View->>DB: Lock document, require owner, PENDING/READY and unexpired
        Note over View,DB: Unavailable saved source returns 404
    end
    View->>DB: Find Job by owner + idempotency_key
    alt Existing key with different fingerprint
        View-->>API: 409 conflict, no second admission
    else Existing matching job not UPLOADING, or upload lease still active
        View-->>API: 202 serialize_job(existing), no new quota charge
    else New job or retryable matching UPLOADING reservation
        opt New job
            View->>DB: consume_bucket(): daily quota, 429 if exhausted
            alt New original
                View->>DB: Create UPLOADING Document, object_key originals/UUID and metadata
                View->>DB: Create UPLOADING Job, resume_text is empty
            else Saved original
                View->>DB: Create QUEUED Job referencing document, create OutboxEvent
            end
        end
        opt New original or resumable upload
            View->>DB: Validate reservation deadline, acquire bounded upload lease UUID
        end
        View->>DB: COMMIT Transaction A
        alt New original bytes
            View->>Store: put_original() -> client().put_object(), bytes + type + ContentMD5
            Note over View,Store: Network I/O occurs outside the SQL transaction
            alt PUT unavailable
                break Stop request after unavailable PUT
                    View->>DB: Expire only matching upload lease
                    View-->>API: 503, retry unchanged payload with same key
                end
            else PUT succeeds
                View->>DB: BEGIN Transaction B, lock Document then Job
                alt Deleted/rejected/missing comparison or lease no longer current
                    break Stop this upload finalizer
                        Note over View,DB: Preserve deletion intent for late PUT, commit transaction exit
                        View-->>API: 409, or current 202 for a superseded lease, do not revive old state
                    end
                else Current valid upload lease
                    View->>DB: Document PENDING, clear upload lease, Job QUEUED, reset scheduling times
                    View->>DB: Create OutboxEvent, COMMIT Transaction B
                end
            end
        else Saved original
            Note over View,Store: No new object PUT, relay polls the committed outbox
        end
        View->>View: emit(job.accepted): telemetry only
        View-->>API: HTTP 202 serialize_job(job)
        API-->>React: Update job state and start/continue poll()
    end
    Note over React,DB: After outbox commit, relay/worker may run before browser receives 202, a lost response is safe to retry with the same key
```

## 3. Durable dispatch, RabbitMQ and Celery

RabbitMQ carries wakeups. PostgreSQL remains authoritative for whether a job may run and commit.

[Editable Mermaid source](assets/upload-to-score-dispatch.mmd)

```mermaid
sequenceDiagram
    autonumber
    participant RelayLoop as relay_jobs.Command.handle
    participant Relay as relay_once / publish_job
    participant DB as PostgreSQL
    participant MQ as RabbitMQ
    participant Celery as Celery worker / tasks.process_job
    participant Job as jobs.run_job / claim_job
    loop Continuous relay loop, or one pass with --once
        RelayLoop->>RelayLoop: close_old_connections()
        RelayLoop->>Relay: relay_once(limit=100)
        Relay->>Relay: reconcile_documents(limit), then recover_jobs(limit)
        loop Up to limit due events
            Relay->>DB: BEGIN, select_for_update(skip_locked=True)
            Note over Relay,DB: Earliest created unsent OutboxEvent with available_at <= now, none ends loop
            Relay->>Relay: publish_job(event.job_id)
            Relay->>MQ: app.send_task(matching.process_job, args=[Job UUID])
            Note over Relay,MQ: Durable direct exchange + quorum queue resume.match.quorum, JSON, delivery_mode=2, mandatory=True, retry=False, confirm_timeout=3
            alt Publish/confirm failure
                Relay->>DB: Keep sent_at NULL, commit and stop this batch
                Relay->>Relay: on_commit emit(job.publish_failed)
            else Broker confirms acceptance
                MQ-->>Relay: Publisher confirmation
                Relay->>DB: Set OutboxEvent.sent_at, COMMIT
                Relay->>Relay: on_commit emit(job.published)
                Note over Relay,MQ: Crash after broker confirmation but before SQL commit can publish again, confirmation does not mean scoring completed
            end
        end
        Relay-->>RelayLoop: Number sent
        RelayLoop->>RelayLoop: Touch heartbeat file, return for --once, otherwise sleep 2 seconds
    end
    Note over MQ,Celery: Delivery is concurrent with relay, it can occur before sent_at SQL commit, despite being drawn below the loop
    MQ->>Celery: Deliver matching.process_job, application args contain only Job UUID
    Note over Celery: Celery autodiscover_tasks registers shared_task, ignore_result=True, late acknowledgements configured
    Celery->>Job: process_job(job_id) -> run_job(job_id)
    Job->>Job: Validate UUID, claim_job(job_id)
    Job->>DB: BEGIN, lock Job
    alt Missing, not QUEUED, not due, deadline exceeded or attempts exhausted
        Job->>DB: No claim, fail_job() for deadline/exhaustion when applicable
        Job-->>Celery: Return without processing
    else Claim accepted
        Job->>DB: RUNNING, attempts + 1, new lease ID + 90-second lease, COMMIT
        Job->>Job: emit(job.started), document_text() then extract_evidence() then finish_job()
        Note over Job: Detailed retrieval, validation, score and failures are in the worker diagram
        Job-->>Celery: Return after success or handled retry/failure
    end
    Celery-->>MQ: Normal task return permits late ACK
    Note over Celery,MQ: Handled retries use database outbox, not self.retry(), unexpected outer exception emits job.interrupted. Lost worker deliveries and DB lease recovery may repeat wakeups
    Note over RelayLoop,Celery: Heartbeat freshness proves the relay loop progressed, not that a particular publish or job succeeded
```

## 4. Retrieval, safety, parsing, evidence and scoring

Successful scanning and integrity checks precede parser-cache reuse. Every rejection/error branch stops that successful path.

[Editable Mermaid source](assets/upload-to-score-worker.mmd)

```mermaid
sequenceDiagram
    autonumber
    participant Job as run_job / finish_job
    participant Docs as document_text / get_original
    participant DB as PostgreSQL
    participant Store as SeaweedFS or AWS S3
    participant Safety as ClamAV or GuardDuty
    participant Parse as services.read_resume
    participant Evidence as services.extract_evidence
    participant Provider as Local ConverseHandler or AWS Bedrock
    Job->>Docs: document_text(claim)
    Docs->>DB: Find owner document, PENDING/READY and unexpired
    alt No accessible document
        Docs-->>Job: DocumentError, terminal failure path
    else Accessible document
        Docs->>Docs: get_original(document) -> client()
        opt DOCUMENT_SCAN_MODE is guardduty
            Docs->>Store: cloud_scan(): get_object_tagging()
            Store-->>Docs: GuardDutyMalwareScanStatus
            alt NO_THREATS_FOUND
                Note over Docs,Safety: Continue to object GET
            else Scan not yet ready
                break Defer scan-pending job
                    Docs-->>Job: ScanPending, no object GET
                    Job->>DB: Matching lease: decrement attempts, enqueue_again(now + 8 seconds)
                end
            else Threat, unsupported, access denied or failed
                break Reject unsafe original
                    Docs->>DB: Lock Document, REJECTED, clear cache, schedule byte deletion
                    Docs-->>Job: DocumentError, no object GET
                    Job->>Job: finish_job(error_code), do not extract or score
                end
            end
        end
        opt Safety gate allows retrieval
            Docs->>Store: get_object(object_key), bounded read <= 1 MiB + 1, close body
            Store-->>Docs: Original bytes
            Docs->>Docs: Verify exact size and SHA-256 against Document metadata
            opt DOCUMENT_SCAN_MODE is clamav
                Docs->>Safety: scan_bytes(): fresh database check via _clam_command(), INSTREAM chunks
                Safety-->>Docs: stream: OK, threat, or unavailable
            end
        end
        alt Terminal integrity, malware, text or parser rejection
            Docs->>DB: Lock Document, REJECTED, clear cache, schedule byte deletion
            Docs->>Docs: emit(document.rejected)
            Docs-->>Job: DocumentError, skip READY/evidence/scoring
        else Storage or scanner unavailable
            Docs-->>Job: DocumentUnavailable, transient retry path
        else Scan pending
            Docs-->>Job: ScanPending, delayed retry path
        else Original passes safety and integrity
            alt Current parser_version, cached text and reprocess is false
                Docs->>Docs: Reuse extracted_text only after retrieving and safety-checking original
            else Cache absent/stale or reprocess requested
                Docs->>Parse: TXT: decode UTF-8-sig, PDF: SimpleUploadedFile, read_resume()
                Note over Parse: Nonempty text <= 30,000 characters, no NUL, PDF strictness, unencrypted, <=10 pages and bounded decompression/work, no OCR
                alt read_resume succeeds
                    Parse-->>Docs: Validated extracted text
                else InvalidInput or decoding error
                    break Reject parsing failure
                        Docs->>DB: Lock Document, REJECTED, clear cache, schedule byte deletion
                        Docs-->>Job: DocumentError
                        Job->>Job: finish_job(error_code), no READY/evidence/scoring
                    end
                end
            end
            Docs->>DB: Lock Document, recheck lifecycle/expiry, READY, extracted_text, PARSER_VERSION, scan_checked_at
            Docs->>Docs: emit(document.ready)
            Docs-->>Job: Text
            Job->>Evidence: extract_evidence(text, requirements, provider, correlation)
            alt provider is demo
                Evidence->>Evidence: literal_evidence() -> literal_match()
            else provider is bedrock-local or bedrock
                Evidence->>Evidence: bedrock_request() -> correlation_ids()
                Evidence->>Provider: boto3 bedrock-runtime client.converse(request)
                Note over Provider: bedrock-local: ConverseHandler.do_POST() -> reply(), bedrock: AWS endpoint
                alt Provider call and response envelope succeed
                    Provider-->>Evidence: One bounded JSON text block, stopReason must be end_turn
                else Provider rejects, times out, fails or returns malformed response
                    break Stop evidence extraction on provider failure
                        Evidence-->>Job: TransientProviderError or ProviderError
                        Job->>Job: finish_job(error_code, transient when appropriate), no score
                    end
                end
            end
            Evidence->>Evidence: validate_evidence(): exact ordered skills, exact source quotes <=240 chars, literal skill boundaries, original weights
            alt Evidence passes validation
                Evidence-->>Job: Validated evidence
            else Evidence fails validation
                break Stop invalid evidence
                    Evidence-->>Job: ProviderError
                    Job->>Job: finish_job(error_code), no score
                end
            end
            Job->>DB: finish_job(): BEGIN, lock Document then Job
            Note over Job,DB: Recheck document lifecycle/expiry, RUNNING status, matching current lease, unexpired lease and overall deadline before committing a result
            alt Stale lease, deleted/missing job or unavailable document
                Job->>Job: Return false, no Match creation
            else Current claim but document is not READY
                Job->>DB: fail_job(document_rejected), COMMIT, no score
            else Current claim but overall deadline exceeded
                Job->>DB: fail_job(deadline_exceeded), COMMIT, no score
            else Current claim with validated evidence and READY document
                Job->>Job: calculate_score(): matched weights / total weights * 100
                Note over Job: Decimal with ROUND_HALF_UP to two places, 8 matched weight / 10 total = 80.00
                Job->>DB: Match.objects.create(), Job SUCCEEDED, clear legacy resume_text and lease, COMMIT
                Job->>Job: job_event() -> on_commit emit(job.succeeded)
            end
        end
    end
    Note over Job,Provider: Bedrock supplies evidence, not the final score. Original bytes stay in object storage, cache/metadata stay in Document, report stays in Match
```

## 5. Polling, retries, recovery and original lifecycle

These activities can overlap; they do not wait for a single linear browser-to-worker response.

[Editable Mermaid source](assets/upload-to-score-recovery-lifecycle.mmd)

```mermaid
sequenceDiagram
    autonumber
    participant React as React poll / saved-source controls
    participant View as Django views
    participant DB as PostgreSQL
    participant Worker as run_job / finish_job
    participant Relay as relay_once / recovery helpers
    participant Store as SeaweedFS or S3
    par Browser polls independently of worker
        loop While active jobs exist
            React->>View: poll() -> api(): GET jobs/, matches/, documents/
            View->>DB: Owner-scoped, lifecycle-filtered, bounded reads
            DB-->>View: Job, Match, Document records
            View-->>React: serialize_job(), serialize(), serialize_document()
            React->>React: Render status or MatchResult, pollError stops polling until recovery action
        end
    and Worker handles a failure
        alt ScanPending
            Worker->>DB: Lock matching RUNNING lease, decrement attempt
            Worker->>DB: enqueue_again(now + 8 seconds): queued + outbox, with normal base backoff added
            Note over Worker,DB: With normal base 2 seconds and first-attempt scan wait, next availability is approximately 10 seconds later
        else DocumentUnavailable, TransientProviderError or SoftTimeLimitExceeded
            Worker->>DB: finish_job(transient=True), enqueue_again() if attempts remain
            Note over Worker,DB: Default transient backoff 2 then 4 seconds, max attempts 3, overall deadline 600 seconds
        else Terminal provider/document or unexpected processing error
            Worker->>DB: finish_job() -> fail_job(): stable error code, FAILED, clear legacy text and lease
        end
    and Relay continuously reconciles durable state
        Relay->>Relay: reconcile_documents() before recover_jobs()
        Relay->>DB: recover_jobs(): lock due QUEUED/RUNNING candidates with skip_locked
        alt Deadline exceeded or max attempts exhausted
            Relay->>DB: fail_job(), persist failure
        else RUNNING lease expired
            Relay->>DB: enqueue_again(): QUEUED + new due OutboxEvent
        else QUEUED wake_at reached
            Relay->>DB: Ensure unsent outbox exists, advance wake_at
        end
        Note over Relay,DB: Wake interval default 30 seconds, queue/database are authoritative, repeat deliveries are permitted
    end
    opt User reuses an original
        React->>View: analyze(): POST jobs/ with document_id and reprocess
        View->>DB: Lock/check owner, PENDING/READY, expiry, create new job and outbox, no PUT
        Note over Worker,Store: Worker still retrieves and safety-checks original. reprocess bypasses parser cache only
    end
    opt User downloads an original
        React->>View: downloadOriginal() -> downloadDocument() -> document_download()
        View->>DB: Require owner, READY and unexpired
        View->>Store: get_original(): scan/integrity checks again
        Store-->>View: Bytes, or mapped safety/storage error
        View->>DB: Recheck READY and expiry after network I/O
        View-->>React: FileResponse attachment, private no-store, nosniff
    end
    opt User deletes original, or retention/upload deadline expires
        React->>View: deleteOriginal() -> api(DELETE documents/UUID/)
        View->>DB: document_detail(): lock document, tombstone()
        Note over View,DB: DELETING, clear private metadata/cache, delete associated jobs/reports, delete_after respects upload lease, HTTP 202
        Relay->>DB: reconcile_documents(): also tombstone expired sources and stale UPLOADING reservations
        Relay->>Store: delete_object() after delete_after
        alt Delete unavailable
            Relay->>Relay: emit(document.delete_pending), retry in later relay pass
        else Delete accepted
            Relay->>DB: Recheck status and lease, clear metadata, DELETED tombstone or retain REJECTED status
            Note over Relay,DB: Rejected comparisons remain visible until policy expiry, late upload finalizers restore deletion intent instead of reviving source
        end
        Note over Relay,Store: Default source retention 90 days, upload TTL 1 hour, DELETED tombstone cleanup after 7 days, AWS bucket lifecycle is an additional policy
    end
    opt User deletes only a comparison
        React->>View: deleteSelection() -> job_detail() or match_detail()
        View->>DB: Delete selected history, original remains reusable unless separately deleted/expired
    end
```

## State and failure reference

| Boundary | Success | Failure/retry behavior |
|---|---|---|
| Browser request | React keeps latest payload fingerprint and UUID in memory | Unchanged retry reuses key; reload loses that in-memory key; changed payload gets a new key |
| Server admission | Owner-scoped key/fingerprint deduplication and quota under owner lock | Same key/different content: 409; new quota exhaustion: 429; invalid/auth/method/body checks reject before admission |
| New original PUT | UPLOADING reservation -> PUT -> PENDING document + QUEUED job + outbox | Storage 503 expires matching lease; unchanged retry resumes reservation; late PUT cannot revive deletion |
| Saved source | Existing owned, eligible, unexpired original -> new job + outbox | No object PUT; missing/ineligible source rejected; worker must still retrieve and safety-check bytes |
| Relay | Broker confirmation -> commit sent_at | Failure leaves unsent; confirm/SQL crash gap may duplicate delivery |
| Worker claim | QUEUED/due -> RUNNING + lease | Duplicate/not-due work ignored; deadline/attempt limits fail eligible jobs; stale worker cannot commit |
| Safety/cache | Original GET and safety/integrity -> cache or parse -> READY | Threat/integrity/parser errors reject; unavailable dependencies retry; pending GuardDuty scan defers without consuming an attempt |
| Evidence/score | Valid evidence -> guarded finish -> weighted score + Match | Invalid/untrusted evidence never supplies its own score or changes requirement weights |
| Polling | Parallel owner-scoped jobs/matches/documents reads, approximately one-second interval while active | Session loss clears private state; other errors persist and stop polling pending recovery; old/cancelled responses are ignored |
| Source deletion | Immediate inaccessible tombstone, deferred object DELETE and metadata cleanup | Upload leases and post-I/O rechecks prevent stale finalizers/downloads from reviving or delivering deleted originals |

Defaults shown in the diagrams are snapshot configuration defaults, not deployment-wide guarantees: source retention 90 days, upload reservation TTL one hour, lease 90 seconds, attempts three, job deadline 600 seconds, wake interval 30 seconds, retry base two seconds. Scanner-pending work adds eight seconds before normal backoff. DELETED metadata tombstones have a seven-day cleanup grace. Cloud object lifecycle adds a storage policy; it is not a substitute for the application's ownership and status checks.

## Function and source registry

Pinned links below resolve to the inspected application snapshot. The diagrams group related helpers to keep the visual path readable; this index names the supporting helpers and callbacks without adding unrelated flows to the diagram bodies.

| Function | Source |
|---|---|
| `mark_worker_ready` | [backend/config/celery.py:16](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/config/celery.py#L16) |
| `clear_worker_ready` | [backend/config/celery.py:21](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/config/celery.py#L21) |
| `ConverseHandler.setup` | [backend/local_converse.py:21](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/local_converse.py#L21) |
| `ConverseHandler.log_message` | [backend/local_converse.py:25](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/local_converse.py#L25) |
| `ConverseHandler.reply` | [backend/local_converse.py:28](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/local_converse.py#L28) |
| `ConverseHandler.do_GET` | [backend/local_converse.py:40](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/local_converse.py#L40) |
| `ConverseHandler.do_POST` | [backend/local_converse.py:43](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/local_converse.py#L43) |
| `client` | [backend/matching/documents.py:41](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/documents.py#L41) |
| `read_source` | [backend/matching/documents.py:54](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/documents.py#L54) |
| `put_original` | [backend/matching/documents.py:80](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/documents.py#L80) |
| `_clam_command` | [backend/matching/documents.py:91](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/documents.py#L91) |
| `scan_bytes` | [backend/matching/documents.py:104](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/documents.py#L104) |
| `cloud_scan` | [backend/matching/documents.py:132](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/documents.py#L132) |
| `get_original` | [backend/matching/documents.py:146](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/documents.py#L146) |
| `document_text` | [backend/matching/documents.py:166](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/documents.py#L166) |
| `tombstone` | [backend/matching/documents.py:206](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/documents.py#L206) |
| `reconcile_documents` | [backend/matching/documents.py:222](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/documents.py#L222) |
| `job_event` | [backend/matching/jobs.py:20](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/jobs.py#L20) |
| `fail_job` | [backend/matching/jobs.py:26](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/jobs.py#L26) |
| `enqueue_again` | [backend/matching/jobs.py:36](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/jobs.py#L36) |
| `claim_job` | [backend/matching/jobs.py:46](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/jobs.py#L46) |
| `finish_job` | [backend/matching/jobs.py:66](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/jobs.py#L66) |
| `run_job` | [backend/matching/jobs.py:95](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/jobs.py#L95) |
| `recover_jobs` | [backend/matching/jobs.py:133](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/jobs.py#L133) |
| `publish_job` | [backend/matching/jobs.py:163](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/jobs.py#L163) |
| `relay_once` | [backend/matching/jobs.py:175](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/jobs.py#L175) |
| `Command.add_arguments` | [backend/matching/management/commands/relay_jobs.py:13](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/management/commands/relay_jobs.py#L13) |
| `Command.handle` | [backend/matching/management/commands/relay_jobs.py:16](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/management/commands/relay_jobs.py#L16) |
| `ReadinessMiddleware.__init__` | [backend/matching/middleware.py:11](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/middleware.py#L11) |
| `ReadinessMiddleware.__call__` | [backend/matching/middleware.py:14](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/middleware.py#L14) |
| `RequestMetadataMiddleware.__init__` | [backend/matching/middleware.py:23](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/middleware.py#L23) |
| `RequestMetadataMiddleware.__call__` | [backend/matching/middleware.py:26](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/middleware.py#L26) |
| `read_resume` | [backend/matching/services.py:36](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/services.py#L36) |
| `read_requirements` | [backend/matching/services.py:94](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/services.py#L94) |
| `literal_match` | [backend/matching/services.py:117](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/services.py#L117) |
| `correlation_ids` | [backend/matching/services.py:131](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/services.py#L131) |
| `bedrock_request` | [backend/matching/services.py:141](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/services.py#L141) |
| `literal_evidence` | [backend/matching/services.py:153](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/services.py#L153) |
| `extract_evidence` | [backend/matching/services.py:163](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/services.py#L163) |
| `validate_evidence` | [backend/matching/services.py:200](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/services.py#L200) |
| `calculate_score` | [backend/matching/services.py:220](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/services.py#L220) |
| `process_job` | [backend/matching/tasks.py:7](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/tasks.py#L7) |
| `_reset_after_fork` | [backend/matching/telemetry.py:34](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/telemetry.py#L34) |
| `_get_logger` | [backend/matching/telemetry.py:45](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/telemetry.py#L45) |
| `emit` | [backend/matching/telemetry.py:66](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/telemetry.py#L66) |
| `error` | [backend/matching/views.py:24](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/views.py#L24) |
| `csrf_failure` | [backend/matching/views.py:28](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/views.py#L28) |
| `not_found` | [backend/matching/views.py:32](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/views.py#L32) |
| `server_error` | [backend/matching/views.py:36](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/views.py#L36) |
| `session_payload` | [backend/matching/views.py:40](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/views.py#L40) |
| `health` | [backend/matching/views.py:47](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/views.py#L47) |
| `session` | [backend/matching/views.py:58](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/views.py#L58) |
| `consume_bucket` | [backend/matching/views.py:64](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/views.py#L64) |
| `login` | [backend/matching/views.py:70](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/views.py#L70) |
| `logout` | [backend/matching/views.py:95](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/views.py#L95) |
| `serialize` | [backend/matching/views.py:102](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/views.py#L102) |
| `read_match_form` | [backend/matching/views.py:106](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/views.py#L106) |
| `matches` | [backend/matching/views.py:133](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/views.py#L133) |
| `match_detail` | [backend/matching/views.py:141](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/views.py#L141) |
| `serialize_document` | [backend/matching/views.py:160](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/views.py#L160) |
| `serialize_job` | [backend/matching/views.py:166](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/views.py#L166) |
| `jobs` | [backend/matching/views.py:178](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/views.py#L178) |
| `admit_jobs` | [backend/matching/views.py:185](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/views.py#L185) |
| `documents` | [backend/matching/views.py:289](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/views.py#L289) |
| `document_detail` | [backend/matching/views.py:298](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/views.py#L298) |
| `document_download` | [backend/matching/views.py:312](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/views.py#L312) |
| `job_detail` | [backend/matching/views.py:335](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/backend/matching/views.py#L335) |
| `activeJob` | [frontend/src/App.tsx:9](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/frontend/src/App.tsx#L9) |
| `reusableDocument` | [frontend/src/App.tsx:10](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/frontend/src/App.tsx#L10) |
| `documentLabel` | [frontend/src/App.tsx:11](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/frontend/src/App.tsx#L11) |
| `providerLabel` | [frontend/src/App.tsx:32](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/frontend/src/App.tsx#L32) |
| `errorText` | [frontend/src/App.tsx:38](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/frontend/src/App.tsx#L38) |
| `MatchResult` | [frontend/src/App.tsx:42](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/frontend/src/App.tsx#L42) |
| `App` | [frontend/src/App.tsx:59](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/frontend/src/App.tsx#L59) |
| `clearPrivateState` | [frontend/src/App.tsx:96](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/frontend/src/App.tsx#L96) |
| `refreshSession` | [frontend/src/App.tsx:106](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/frontend/src/App.tsx#L106) |
| `loseSession` | [frontend/src/App.tsx:112](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/frontend/src/App.tsx#L112) |
| `loadWorkspace` | [frontend/src/App.tsx:118](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/frontend/src/App.tsx#L118) |
| `load` | [frontend/src/App.tsx:127](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/frontend/src/App.tsx#L127) |
| `useEffect polling / poll` | [frontend/src/App.tsx:145](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/frontend/src/App.tsx#L145) |
| `poll` | [frontend/src/App.tsx:151](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/frontend/src/App.tsx#L151) |
| `perform` | [frontend/src/App.tsx:175](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/frontend/src/App.tsx#L175) |
| `login` | [frontend/src/App.tsx:189](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/frontend/src/App.tsx#L189) |
| `logout` | [frontend/src/App.tsx:201](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/frontend/src/App.tsx#L201) |
| `analyze` | [frontend/src/App.tsx:211](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/frontend/src/App.tsx#L211) |
| `deleteSelection` | [frontend/src/App.tsx:259](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/frontend/src/App.tsx#L259) |
| `downloadOriginal` | [frontend/src/App.tsx:273](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/frontend/src/App.tsx#L273) |
| `deleteOriginal` | [frontend/src/App.tsx:292](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/frontend/src/App.tsx#L292) |
| `api` | [frontend/src/api.ts:42](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/frontend/src/api.ts#L42) |
| `cancel` | [frontend/src/api.ts:49](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/frontend/src/api.ts#L49) |
| `downloadDocument` | [frontend/src/api.ts:71](https://github.com/junrillg/resume-match-bedrock/blob/b0b8e58f1776b89a1bf3a7eede0a83266daf63f1/frontend/src/api.ts#L71) |


## Configuration and transport sources

- [nginx request routing](../frontend/nginx.conf)
- [Django WSGI entrypoint](../backend/config/wsgi.py), [middleware order and limits](../backend/config/settings.py), [URL routes](../backend/config/urls.py)
- [Celery queue setup and worker readiness callbacks](../backend/config/celery.py), [task wrapper](../backend/matching/tasks.py)
- [Document, Job, Match and OutboxEvent models](../backend/matching/models.py)
- [Local service topology and health checks](../compose.yaml)
- [AWS document bucket/scanning configuration](../infra/terraform/documents.tf)

## Protocol interpretation

[Celery task acknowledgements](https://docs.celeryq.dev/en/v5.6.0/userguide/tasks.html) and [RabbitMQ publisher confirmations versus consumer acknowledgements](https://www.rabbitmq.com/docs/confirms) explain why broker acceptance, worker acknowledgement and application completion are different events. JSON application args contain the Job UUID; the Celery envelope also includes framework metadata. `ignore_result=True` disables a Celery result-backend record, not the application's `Match` report.

## Verification

Application-flow facts were checked against the pinned source and the preceding source-indexed architecture atlas. All five diagrams passed Mermaid 12.2.0 syntax parsing; each Markdown fence exactly matches its editable `.mmd` source. All 91 pinned function links were checked, and their linked application files match the source snapshot. Hosted GitHub/Notion visual rendering was not inspected. Application tests, live broker/storage behavior, AWS configuration and deployment were not run for this documentation-only conversion.
