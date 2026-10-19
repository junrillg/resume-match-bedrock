# Document admission, processing and report delivery


The execution maps trace original upload and saved-source reuse through admission, durable dispatch, evidence validation, completion notification and report access. Processing runs independently of browser navigation.

**Source snapshot:** [`880f9b8c820203353593c3eb5905cc13228f950d`](https://github.com/junrillg/resume-match-bedrock/tree/880f9b8c820203353593c3eb5905cc13228f950d), inspected on 19 October 2026. This identifies the implementation; it does not establish an active AWS deployment.

## Execution boundaries

- HTTP 202 is an admission receipt. The processing route can be left immediately; status reads do not hold the UI pending state.
- PostgreSQL controls admission, leases, outcomes and unread notifications. RabbitMQ carries repeatable wakeups; publisher confirmation is separate from job completion.
- Object PUT/GET, safety checks and provider calls occur outside their surrounding SQL critical sections. The diagrams show the relevant commit boundaries.
- Local Compose uses PostgreSQL, RabbitMQ, Celery, SeaweedFS and ClamAV. The AWS configuration selects S3 and GuardDuty. Provider choices are `demo`, `bedrock-local` and `bedrock`; local S3 compatibility does not imply an AWS transfer.

The numbered diagrams cover the application path and its failure, recovery, reuse, download and deletion boundaries. SDK/network internals, provisioning bodies and unrelated account administration are outside this execution view.

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
    DB[("PostgreSQL: Document, Job, OutboxEvent, Match, CompletionNotification, RateBucket")]
    RESP["accepted_job() -> HTTP 202, Location and Retry-After; job.accepted is telemetry"]
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
    FIN["15. finish_job(): document/job locks, lease/deadline/lifecycle guards; calculate_score(); Match + SUCCEEDED + unique completion notification atomically"]
    ROUTE["Processing page /jobs/UUID; user can navigate, submit another comparison or sign out"]
    POLL["16. Background status and inbox reads; bounded retries, visibility pause and reconnect catch-up"]
    NOTICE["17. Persistent inbox: explicit result or failure link; separate Mark as read"]
    RESULT["Result page /results/UUID -> owner-scoped job detail -> MatchResult"]
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
    RESP --> ROUTE --> POLL
    POLL <--> DB
    POLL --> NOTICE
    POLL -->|Same visible processing job succeeds| RESULT
    NOTICE -->|User opens ready report| RESULT
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
    React->>React: analyze(): preventDefault, submit-only pending state, validate size/type and duplicate skills
    React->>React: Build FormData, hash file bytes or exact pasted text, or saved ID + reprocess
    React->>React: Same browser fingerprint reuses UUID, changed payload gets new UUID
    React->>API: api(jobs/, POST, FormData, Idempotency-Key)
    Note over User,React: Navigation, history and sign out remain available during admission and processing
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
        View-->>API: 202 accepted_job(existing), no new quota charge
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
        View-->>API: accepted_job(): HTTP 202 job JSON, Location status endpoint, Retry-After 2
    end
    API-->>React: Receipt with processing_url and result_url when already succeeded
    React->>React: Check session, deleted entity and navigation fences, merge current receipt
    alt QUEUED or RUNNING, and user is still on the submitting form
        React->>React: navigate(/jobs/UUID), release submission pending state
    else Already SUCCEEDED, and still on submitting form
        React->>React: navigate(/results/UUID)
    else UPLOADING reservation
        React->>React: Explain incomplete upload, retain draft/source and same-key retry
    else User navigated while admission was in flight
        React->>React: Preserve current route and draft, receipt remains in history
    end
    React->>React: Wake background monitoring without awaiting the worker
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
        Job->>DB: No claim, deadline/exhaustion uses atomic fail_job() plus one completion notification
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
                Job->>Job: Return false, no Match or completion notification
            else Current claim but document is not READY
                Job->>DB: fail_job(document_rejected) plus unique failure notification, COMMIT, no score
            else Current claim but overall deadline exceeded
                Job->>DB: fail_job(deadline_exceeded) plus unique failure notification, COMMIT, no score
            else Current claim with validated evidence and READY document
                Job->>Job: calculate_score(): matched weights / total weights * 100
                Note over Job: Decimal with ROUND_HALF_UP to two places, 8 matched weight / 10 total = 80.00
                Job->>DB: Match.objects.create(), Job SUCCEEDED, clear legacy resume_text and lease
                Job->>DB: persist_completion(): get_or_create unique CompletionNotification for Job
                Note over Job,DB: Match, terminal Job and notification commit together, any write failure rolls them all back
                Job->>DB: COMMIT
                Job->>Job: on_commit emit(notification.persisted), job_event() emits job.succeeded
            end
        end
    end
    Note over Job,Provider: Bedrock supplies evidence, not the final score. Original bytes stay in object storage, cache/metadata stay in Document, report stays in Match, terminal outcomes and unread state stay in PostgreSQL
```

## 5. Background reads, retries, recovery and original lifecycle

These activities can overlap; they do not wait for a single linear browser-to-worker response.

[Editable Mermaid source](assets/upload-to-score-recovery-lifecycle.mmd)

```mermaid
sequenceDiagram
    autonumber
    participant React as Background refresh / source controls
    participant View as Django views
    participant DB as PostgreSQL
    participant Worker as run_job / finish_job
    participant Relay as relay_once / recovery helpers
    participant Store as SeaweedFS or S3
    par Browser refreshes independently of worker
        loop Authenticated, visible and online, 1 second active or 15 seconds idle
            React->>View: GET jobs/, matches/, documents/, notifications/, optional selected job detail
            View->>DB: Owner-scoped, lifecycle-filtered, bounded reads
            DB-->>View: Job, Match, Document and visible completion notification records
            View-->>React: Owner-scoped status/results and inbox with total unread_count
            React->>React: Update status/inbox without locking navigation, only current processing job may auto-open result
            Note over React,View: Error backoff caps at 30 seconds, hidden/offline pauses, focus/reconnect catches up, no browser error marks a job failed
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
            Worker->>DB: finish_job() -> fail_job(): FAILED + unique completion notification atomically, clear legacy text and lease
        end
    and Relay continuously reconciles durable state
        Relay->>Relay: reconcile_documents() before recover_jobs()
        Relay->>DB: recover_jobs(): lock due QUEUED/RUNNING candidates with skip_locked
        alt Deadline exceeded or max attempts exhausted
            Relay->>DB: fail_job(): persist FAILED and unique completion notification atomically
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
        Note over View,DB: DELETING, clear private metadata/cache, delete associated jobs/reports/notifications, delete_after respects upload lease, HTTP 202
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
        View->>DB: Delete selected job/report and its notification, original remains reusable unless separately deleted/expired
    end
```

## 6. Completion inbox and result navigation

A completion record is part of the terminal transaction. Delivery is in-app: a connected browser discovers it in the background, and a returning user receives the same saved unread state. Opening a result and marking an update read are separate actions.

[Editable Mermaid source](assets/upload-to-score-completion.mmd)

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant React as React App and navigation helpers
    participant View as Django job and notification views
    participant Worker as Worker or recovery outcome writer
    participant DB as PostgreSQL
    View-->>React: Finalized admission: HTTP 202 with Job UUID
    React->>React: navigate(/jobs/UUID), submission no longer pending
    opt User chooses to leave processing
        User->>React: Continue elsewhere, prepare another draft or sign out
    end
    Note over User,React: Draft remains mounted across routes, worker progress never locks the workspace
    par Terminal outcome commits independently
        Worker->>DB: BEGIN, current lease, deadline and document lifecycle guards
        alt Success
            Worker->>DB: Match plus Job SUCCEEDED
        else Terminal failure or recovery exhaustion
            Worker->>DB: Job FAILED with safe error code, no Match
        end
        Worker->>DB: persist_completion(): unique notification per Job
        Worker->>DB: COMMIT outcome and notification together
        Worker->>Worker: on_commit telemetry only, UUID correlation
    and Connected browser discovers saved state
        loop Visible and online, active 1s or idle 15s
            React->>View: GET notifications/?offset=0 and workspace status, selected job detail when applicable
            View->>DB: visible_notifications(owner), lifecycle filter, newest 100, total unread_count
            DB-->>View: Persisted inbox and status
            View-->>React: Notification IDs, outcome, timestamps, local destination, no source/evidence
            alt Same visible processing Job is now succeeded with a Match
                React->>React: Replace /jobs/UUID with /results/UUID
            else User is elsewhere
                React->>React: Show unread summary, retain current route, focus and draft
            end
        end
    end
    Note over React,DB: Closed or signed-out browser gets persisted notices after returning and authenticating, no email or push channel is implied
    User->>React: Open notification result or failure-status link
    React->>React: navigate() using local UUID-derived resultPath() or jobPath()
    React->>View: GET /api/jobs/UUID/ independently of recent history
    View->>DB: Owner and document lifecycle check
    View-->>React: Authoritative Job and Match, or unavailable response
    React->>React: Render MatchResult on result route, or processing/failure status
    opt User separately chooses Mark as read
        React->>View: POST /api/notifications/UUID/read/ with CSRF
        View->>DB: Lock visible owned notification, set read_at only if NULL
        DB-->>View: Same persisted timestamp on repeat acknowledgement
        View-->>React: Updated notification, on_commit emits notification.read
        React->>React: Update unread count and refresh, acknowledgement failure cannot block report access
    end
    Note over React,View: Background failures retry with bounded backoff, focus/reconnect catches up. Authentication loss clears private client state
    Note over View,DB: Job/source deletion cascades notices, expiry hides notices before cleanup. Existing historical terminal jobs are not backfilled as unread
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
| Evidence/score | Valid evidence -> guarded finish -> Match + SUCCEEDED + unique completion notification in one transaction | Invalid/untrusted evidence never supplies its own score or changes weights; terminal failure also persists one notification, intermediate retries do not |
| Background reads | Status, inbox and optional detail reads; 1 second active, 15 seconds idle, one settled batch at a time | Hidden/offline pauses; failures retry with backoff capped at 30 seconds; focus/reconnect catches up; session loss clears private state |
| Navigation | Acceptance opens processing; only that same visible processing route auto-opens its successful result | Completion elsewhere leaves the current draft/route intact; result URLs resolve through independently authorized job detail |
| Inbox/read | Durable per-job outcome, fixed 100-item pages, total unread count; separate idempotent read acknowledgement | Owner/lifecycle filters apply to listing and CSRF-protected read; acknowledgement errors do not block result access; no historical unread backfill |
| Source deletion | Immediate inaccessible tombstone; associated jobs, reports and notifications cascade; deferred object DELETE | Upload leases, post-I/O checks and client entity/session fences reject late finalizers, admission responses and downloads |

Defaults shown in the diagrams are snapshot configuration defaults, not deployment-wide guarantees: source retention 90 days, upload reservation TTL one hour, lease 90 seconds, attempts three, job deadline 600 seconds, wake interval 30 seconds, retry base two seconds. Scanner-pending work adds eight seconds before normal backoff. DELETED metadata tombstones have a seven-day cleanup grace. Cloud object lifecycle adds a storage policy; it is not a substitute for the application's ownership and status checks.

## Execution and source registry

Pinned links below resolve to the inspected application snapshot. The diagrams group related helpers to keep the visual path readable; this index names the supporting helpers and callbacks without adding unrelated flows to the diagram bodies.

<details>
<summary>Source index: request handlers, worker helpers, navigation and delivery</summary>

| Symbol | Source |
|---|---|
| `mark_worker_ready` | [backend/config/celery.py:16](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/config/celery.py#L16) |
| `clear_worker_ready` | [backend/config/celery.py:21](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/config/celery.py#L21) |
| `ConverseHandler.setup` | [backend/local_converse.py:21](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/local_converse.py#L21) |
| `ConverseHandler.log_message` | [backend/local_converse.py:25](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/local_converse.py#L25) |
| `ConverseHandler.reply` | [backend/local_converse.py:28](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/local_converse.py#L28) |
| `ConverseHandler.do_GET` | [backend/local_converse.py:40](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/local_converse.py#L40) |
| `ConverseHandler.do_POST` | [backend/local_converse.py:43](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/local_converse.py#L43) |
| `client` | [backend/matching/documents.py:41](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/documents.py#L41) |
| `read_source` | [backend/matching/documents.py:54](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/documents.py#L54) |
| `put_original` | [backend/matching/documents.py:80](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/documents.py#L80) |
| `_clam_command` | [backend/matching/documents.py:91](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/documents.py#L91) |
| `scan_bytes` | [backend/matching/documents.py:104](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/documents.py#L104) |
| `cloud_scan` | [backend/matching/documents.py:132](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/documents.py#L132) |
| `get_original` | [backend/matching/documents.py:146](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/documents.py#L146) |
| `document_text` | [backend/matching/documents.py:166](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/documents.py#L166) |
| `tombstone` | [backend/matching/documents.py:206](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/documents.py#L206) |
| `reconcile_documents` | [backend/matching/documents.py:222](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/documents.py#L222) |
| `job_event` | [backend/matching/jobs.py:21](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/jobs.py#L21) |
| `fail_job` | [backend/matching/jobs.py:27](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/jobs.py#L27) |
| `enqueue_again` | [backend/matching/jobs.py:38](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/jobs.py#L38) |
| `claim_job` | [backend/matching/jobs.py:48](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/jobs.py#L48) |
| `finish_job` | [backend/matching/jobs.py:68](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/jobs.py#L68) |
| `run_job` | [backend/matching/jobs.py:98](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/jobs.py#L98) |
| `recover_jobs` | [backend/matching/jobs.py:136](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/jobs.py#L136) |
| `publish_job` | [backend/matching/jobs.py:166](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/jobs.py#L166) |
| `relay_once` | [backend/matching/jobs.py:178](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/jobs.py#L178) |
| `Command.add_arguments` | [backend/matching/management/commands/relay_jobs.py:13](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/management/commands/relay_jobs.py#L13) |
| `Command.handle` | [backend/matching/management/commands/relay_jobs.py:16](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/management/commands/relay_jobs.py#L16) |
| `ReadinessMiddleware.__init__` | [backend/matching/middleware.py:11](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/middleware.py#L11) |
| `ReadinessMiddleware.__call__` | [backend/matching/middleware.py:14](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/middleware.py#L14) |
| `RequestMetadataMiddleware.__init__` | [backend/matching/middleware.py:23](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/middleware.py#L23) |
| `RequestMetadataMiddleware.__call__` | [backend/matching/middleware.py:26](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/middleware.py#L26) |
| `read_resume` | [backend/matching/services.py:36](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/services.py#L36) |
| `read_requirements` | [backend/matching/services.py:94](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/services.py#L94) |
| `literal_match` | [backend/matching/services.py:117](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/services.py#L117) |
| `correlation_ids` | [backend/matching/services.py:131](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/services.py#L131) |
| `bedrock_request` | [backend/matching/services.py:141](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/services.py#L141) |
| `literal_evidence` | [backend/matching/services.py:153](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/services.py#L153) |
| `extract_evidence` | [backend/matching/services.py:163](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/services.py#L163) |
| `validate_evidence` | [backend/matching/services.py:200](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/services.py#L200) |
| `calculate_score` | [backend/matching/services.py:220](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/services.py#L220) |
| `process_job` | [backend/matching/tasks.py:7](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/tasks.py#L7) |
| `_reset_after_fork` | [backend/matching/telemetry.py:34](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/telemetry.py#L34) |
| `_get_logger` | [backend/matching/telemetry.py:45](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/telemetry.py#L45) |
| `emit` | [backend/matching/telemetry.py:66](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/telemetry.py#L66) |
| `error` | [backend/matching/views.py:25](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/views.py#L25) |
| `csrf_failure` | [backend/matching/views.py:29](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/views.py#L29) |
| `not_found` | [backend/matching/views.py:33](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/views.py#L33) |
| `server_error` | [backend/matching/views.py:37](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/views.py#L37) |
| `session_payload` | [backend/matching/views.py:41](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/views.py#L41) |
| `health` | [backend/matching/views.py:48](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/views.py#L48) |
| `session` | [backend/matching/views.py:59](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/views.py#L59) |
| `consume_bucket` | [backend/matching/views.py:65](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/views.py#L65) |
| `login` | [backend/matching/views.py:71](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/views.py#L71) |
| `logout` | [backend/matching/views.py:96](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/views.py#L96) |
| `serialize` | [backend/matching/views.py:103](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/views.py#L103) |
| `read_match_form` | [backend/matching/views.py:107](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/views.py#L107) |
| `matches` | [backend/matching/views.py:134](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/views.py#L134) |
| `match_detail` | [backend/matching/views.py:142](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/views.py#L142) |
| `serialize_document` | [backend/matching/views.py:161](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/views.py#L161) |
| `serialize_job` | [backend/matching/views.py:167](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/views.py#L167) |
| `jobs` | [backend/matching/views.py:222](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/views.py#L222) |
| `admit_jobs` | [backend/matching/views.py:229](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/views.py#L229) |
| `documents` | [backend/matching/views.py:333](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/views.py#L333) |
| `document_detail` | [backend/matching/views.py:342](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/views.py#L342) |
| `document_download` | [backend/matching/views.py:356](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/views.py#L356) |
| `job_detail` | [backend/matching/views.py:379](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/views.py#L379) |
| `activeJob` | [frontend/src/App.tsx:11](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L11) |
| `reusableDocument` | [frontend/src/App.tsx:12](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L12) |
| `documentLabel` | [frontend/src/App.tsx:13](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L13) |
| `providerLabel` | [frontend/src/App.tsx:34](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L34) |
| `errorText` | [frontend/src/App.tsx:40](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L40) |
| `MatchResult` | [frontend/src/App.tsx:44](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L44) |
| `App` | [frontend/src/App.tsx:69](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L69) |
| `clearPrivateState` | [frontend/src/App.tsx:163](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L163) |
| `refreshSession` | [frontend/src/App.tsx:174](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L174) |
| `loseSession` | [frontend/src/App.tsx:180](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L180) |
| `loadWorkspace` | [frontend/src/App.tsx:193](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L193) |
| `load` | [frontend/src/App.tsx:203](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L203) |
| `useEffect polling / poll` | [frontend/src/App.tsx:242](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L242) |
| `poll` | [frontend/src/App.tsx:250](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L250) |
| `perform` | [frontend/src/App.tsx:298](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L298) |
| `login` | [frontend/src/App.tsx:306](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L306) |
| `logout` | [frontend/src/App.tsx:315](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L315) |
| `analyze` | [frontend/src/App.tsx:327](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L327) |
| `deleteSelection` | [frontend/src/App.tsx:369](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L369) |
| `downloadOriginal` | [frontend/src/App.tsx:385](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L385) |
| `deleteOriginal` | [frontend/src/App.tsx:399](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L399) |
| `api` | [frontend/src/api.ts:51](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/api.ts#L51) |
| `cancel` | [frontend/src/api.ts:58](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/api.ts#L58) |
| `downloadDocument` | [frontend/src/api.ts:80](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/api.ts#L80) |

| `persist_completion` | [backend/matching/notifications.py:14](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/notifications.py#L14) |
| `visible_notifications` | [backend/matching/notifications.py:24](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/notifications.py#L24) |
| `serialize_notification` | [backend/matching/notifications.py:32](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/notifications.py#L32) |
| `accepted_job` | [backend/matching/views.py:181](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/views.py#L181) |
| `notifications` | [backend/matching/views.py:188](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/views.py#L188) |
| `notification_read` | [backend/matching/views.py:204](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/views.py#L204) |
| `CompletionNotification` | [backend/matching/models.py:77](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/models.py#L77) |
| `Document` | [backend/matching/models.py:90](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/models.py#L90) |
| `Job` | [backend/matching/models.py:28](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/models.py#L28) |
| `Match` | [backend/matching/models.py:6](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/models.py#L6) |
| `OutboxEvent` | [backend/matching/models.py:66](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/backend/matching/models.py#L66) |
| `navigate` | [frontend/src/App.tsx:134](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L134) |
| `follow` | [frontend/src/App.tsx:143](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L143) |
| `updateInbox` | [frontend/src/App.tsx:184](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L184) |
| `markRead` | [frontend/src/App.tsx:420](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L420) |
| `loadMoreNotifications` | [frontend/src/App.tsx:435](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L435) |
| `noticeList` | [frontend/src/App.tsx:449](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L449) |
| `settledBatch` | [frontend/src/App.tsx:62](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L62) |
| `readRoute` | [frontend/src/navigation.ts:8](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/navigation.ts#L8) |
| `jobPath` | [frontend/src/navigation.ts:18](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/navigation.ts#L18) |
| `resultPath` | [frontend/src/navigation.ts:19](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/navigation.ts#L19) |
| `reportPath` | [frontend/src/navigation.ts:20](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/navigation.ts#L20) |
| `pop` | [frontend/src/App.tsx:150](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L150) |
| `visible` | [frontend/src/App.tsx:248](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L248) |
| `schedule` | [frontend/src/App.tsx:249](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L249) |
| `wake` | [frontend/src/App.tsx:288](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L288) |
| `returnToApp` | [frontend/src/App.tsx:289](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L289) |
| `connection` | [frontend/src/App.tsx:290](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L290) |
| `Owner-authorized detail effect` | [frontend/src/App.tsx:218](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L218) |
| `Processing result transition effect` | [frontend/src/App.tsx:235](https://github.com/junrillg/resume-match-bedrock/blob/880f9b8c820203353593c3eb5905cc13228f950d/frontend/src/App.tsx#L235) |

</details>

## Configuration and transport sources

- [nginx request routing](../frontend/nginx.conf)
- [Django WSGI entrypoint](../backend/config/wsgi.py), [middleware order and limits](../backend/config/settings.py), [URL routes](../backend/config/urls.py)
- [Celery queue setup and worker readiness callbacks](../backend/config/celery.py), [task wrapper](../backend/matching/tasks.py)
- [Document, Job, Match, OutboxEvent and CompletionNotification models](../backend/matching/models.py)
- [Notification persistence and owner visibility](../backend/matching/notifications.py), [client route handling](../frontend/src/navigation.ts)
- [Local service topology and health checks](../compose.yaml)
- [AWS document bucket/scanning configuration](../infra/terraform/documents.tf)

## Protocol interpretation

[Celery task acknowledgements](https://docs.celeryq.dev/en/v5.6.0/userguide/tasks.html) and [RabbitMQ publisher confirmations versus consumer acknowledgements](https://www.rabbitmq.com/docs/confirms) explain why broker acceptance, worker acknowledgement and application completion are different events. JSON application args contain the Job UUID; the Celery envelope also includes framework metadata. `ignore_result=True` disables a Celery result-backend record, not the application's `Match` report.

## Verification

The execution maps and source anchors were refreshed against the pinned implementation. All six maps passed Mermaid 12.2.0 syntax parsing; each fenced map matches its adjacent editable `.mmd` source. These documentation checks do not establish live AWS behavior or hosted diagram rendering; release verification records those observations separately.
