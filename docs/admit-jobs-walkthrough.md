# _admit_jobs(): step-by-step Mermaid walkthrough

Read these four diagrams alongside [the exact function at revision 5b74706](https://github.com/junrillg/resume-match-bedrock/blob/5b74706828b6aaa35f61bfce563aa0f6dc6e7065/backend/matching/views.py#L283). Source snapshot: `5b74706828b6aaa35f61bfce563aa0f6dc6e7065`, inspected 19 October 2026.

[End-to-end diagrams](upload-to-score-mermaid.md) · [Notion notebook](https://app.notion.com/p/3fd71e91a0f6816585fdf556f98829ab)

These diagrams cover every explicit branch in the selected function, lines 283–396. Helper internals, unexpected exceptions and deployment behavior are outside this function-level map. HTTP 202 returns the current job; it can still be uploading, processing, completed or failed. Creating this reference does not answer the pending learner checkpoint.

## 1. Request routing and validation

[Code: lines 283–308](https://github.com/junrillg/resume-match-bedrock/blob/5b74706828b6aaa35f61bfce563aa0f6dc6e7065/backend/matching/views.py#L283)

```mermaid
flowchart TD
    START["Request enters _admit_jobs()"] --> AUTH{"Signed in?"}
    AUTH -->|No| E401["Return 401"]
    AUTH -->|Yes| GET{"GET request?"}
    GET -->|Yes| BAD{"summary provided<br>with value other than true?"}
    BAD -->|Yes| E400["Return 400"]
    BAD -->|No| LIST["Find this owner's jobs<br>Keep jobs without documents or with unexpired documents<br>Exclude deleting/deleted documents"]
    LIST --> LOAD["Load related match and document<br>Defer resume_text, requirements and document extracted_text"]
    LOAD --> SUMMARY{"summary=true?"}
    SUMMARY -->|Yes| DEFER["Also defer match requirements"]
    SUMMARY -->|No| JSON
    DEFER --> JSON["Serialize first 100 jobs<br>Return JSON"]
    GET -->|No| POST{"POST request?"}
    POST -->|No| E405["Return 405"]
    POST -->|Yes| KEY{"Idempotency-Key<br>is a valid UUID?"}
    KEY -->|No| KEY400["Return 400"]
    KEY -->|Yes| FORM{"read_match_form() succeeds?"}
    FORM -->|Invalid input or upload limits| FORM400["Return 400<br>Validation message or upload-limit message"]
    FORM -->|Yes| SOURCE{"Saved document ID?"}
    SOURCE -->|Yes| SAVED["Identity = document ID + reprocess"]
    SOURCE -->|No| NEW["Identity = SHA-256 of original bytes + content type"]
    SAVED --> HASH
    NEW --> HASH
    HASH["Fingerprint = SHA-256 of sorted JSON<br>title + requirements + source identity<br>Capture now before identity; initialize lease=None"]
    HASH --> NEXT["Continue to diagram 2"]
```

## 2. Transaction A: reuse or reserve

[Code: lines 309–357](https://github.com/junrillg/resume-match-bedrock/blob/5b74706828b6aaa35f61bfce563aa0f6dc6e7065/backend/matching/views.py#L309)

The owner lock remains held throughout this transaction. The saved-document check precedes the idempotency lookup. Matching retries avoid new admission and quota charges.

```mermaid
flowchart TD
    START["BEGIN transaction A<br>lock_stream(owner)<br>document=None"] --> SAVED{"Saved document ID?"}
    SAVED -->|Yes| DOC["Lock saved document<br>Require same owner, PENDING/READY and unexpired"]
    DOC --> FOUND{"Document found?"}
    FOUND -->|No| E404["Return 404"]
    FOUND -->|Yes| LOOKUP
    SAVED -->|No| LOOKUP["Find Job by owner + idempotency key<br>Load related match and document"]
    LOOKUP --> EXISTS{"Existing job?"}
    EXISTS -->|Yes| HASH{"Stored fingerprint<br>equals incoming fingerprint?"}
    HASH -->|No| CONFLICT["Return 409<br>Key belongs to different contents"]
    HASH -->|Yes| USE["Reuse existing job and its document"]
    USE --> UP{"Job still UPLOADING?"}
    UP -->|No| RETURN["Return accepted_job(): HTTP 202"]
    UP -->|Yes| LOCK["Lock and reread document<br>Lock and reread job"]
    LOCK --> AGAIN{"Job still UPLOADING?"}
    AGAIN -->|No| RETURN
    AGAIN -->|Yes| VALID{"Document UPLOADING<br>and upload deadline in future?"}
    VALID -->|No| EXPIRED["Return 409<br>Reservation unavailable"]
    VALID -->|Yes| ACTIVE{"Upload lease exists<br>and is still active?"}
    ACTIVE -->|Yes| RETURN
    ACTIVE -->|No| HASBYTES
    EXISTS -->|No| ADMIT{"reserve_admission() allows work?"}
    ADMIT -->|No| DENIED["Raise AdmissionDenied<br>Outer wrapper handles response"]
    ADMIT -->|Yes| QUOTA{"Daily quota available?"}
    QUOTA -->|No| LIMIT["Raise AdmissionDenied<br>429: daily limit reached"]
    QUOTA -->|Yes| NEWDOC{"New original bytes?"}
    NEWDOC -->|Yes| CREATE["Create UPLOADING Document<br>UUID, object key, filename, type, size, checksum<br>Retention expiry + upload deadline"]
    NEWDOC -->|No| JOB
    CREATE --> JOB["Create Job referencing document<br>Save key, fingerprint, inputs, provider and request ID<br>Reserve admission; set scheduling times<br>UPLOADING for new bytes; otherwise QUEUED"]
    JOB --> OUTBOX{"Saved source: no new bytes?"}
    OUTBOX -->|Yes| EVENT["Create OutboxEvent"]
    OUTBOX -->|No| HASBYTES
    EVENT --> HASBYTES{"New original bytes present?"}
    HASBYTES -->|Yes| LEASE["Generate new lease UUID<br>Save lease and its expiry on document"]
    HASBYTES -->|No| COMMIT
    LEASE --> COMMIT["COMMIT transaction A<br>Release transaction locks"]
    COMMIT --> NEXT["Continue to diagram 3"]
```

A normal return inside `atomic()` exits normally and commits; raising `AdmissionDenied` rolls back this transaction. The surrounding `admit_jobs()` wrapper translates that exception into an HTTP response. Neither a normal error response nor a 202 automatically implies rollback.

## 3. Upload outside the transaction

[Code: lines 358–365](https://github.com/junrillg/resume-match-bedrock/blob/5b74706828b6aaa35f61bfce563aa0f6dc6e7065/backend/matching/views.py#L358)

Saved-document submissions skip the PUT. New originals go from Django to the configured S3-compatible store. Local SeaweedFS and AWS S3 are configuration choices; this map does not establish a deployed AWS upload.

```mermaid
flowchart TD
    START["Transaction A committed"] --> SOURCE{"New original bytes?"}
    SOURCE -->|No: saved document| DONE["Continue to final response<br>shown at bottom of diagram 4"]
    SOURCE -->|Yes| RELEASE["release_database()<br>Release database connections outside transaction"]
    RELEASE --> PUT["put_original(document, source bytes)<br>S3-compatible storage request"]
    PUT --> RESULT{"PUT succeeds?"}
    RESULT -->|DocumentUnavailable| EXPIRE["Expire lease only where<br>document ID AND lease UUID still match"]
    EXPIRE --> ERROR["Return 503<br>Retry unchanged inputs<br>Committed reservation remains"]
    RESULT -->|Yes| NEXT["Continue to transaction B<br>diagram 4"]
```

The storage request is outside the SQL transaction. Failure can leave the object outcome uncertain; expiring this attempt's lease does not delete the committed reservation or expire a newer attempt's lease.

## 4. Transaction B: finalize only the current attempt

[Code: lines 366–396](https://github.com/junrillg/resume-match-bedrock/blob/5b74706828b6aaa35f61bfce563aa0f6dc6e7065/backend/matching/views.py#L366)

```mermaid
flowchart TD
    START["BEGIN transaction B<br>lock_stream(owner)<br>Lock and reread document<br>Lock job if it still exists"] --> DEAD{"Document DELETING, DELETED or REJECTED<br>OR job missing while document UPLOADING?"}
    DEAD -->|Yes| REJECTED{"Document REJECTED?"}
    REJECTED -->|Yes| CLEAN
    REJECTED -->|No| DELETE["Set document DELETING"]
    DELETE --> CLEAN["Set delete_after=now<br>Expire upload lease; save document"]
    CLEAN --> E409["Return 409<br>Deleted or rejected during upload"]
    DEAD -->|No| MISSING{"Job missing?"}
    MISSING -->|Yes| JOB409["Return 409<br>Comparison deleted during upload"]
    MISSING -->|No| OWN{"Document still UPLOADING<br>AND stored lease equals this attempt's lease?"}
    OWN -->|No| CURRENT["Attach current document to in-memory job<br>Return existing job: HTTP 202<br>Do not finalize this attempt"]
    OWN -->|Yes| DOC["Document becomes PENDING<br>Clear upload lease UUID and expiry<br>Save document"]
    DOC --> JOB["Job becomes QUEUED<br>Refresh available_at, wake_at and deadline_at<br>Save job"]
    JOB --> EVENT["Create OutboxEvent available now<br>Attach current document to in-memory job"]
    EVENT --> COMMIT["COMMIT transaction B<br>Document + job + outbox commit together"]
    COMMIT --> LOG
    SAVED["Saved-source path from diagram 3<br>Already queued in transaction A"] --> LOG["emit(job.accepted)<br>Telemetry only"]
    LOG --> RESPONSE["Return accepted_job(job)<br>HTTP 202"]
```

The finalizer checks the lease UUID, not lease expiry. Expiry allows a later request to take over; a replacement UUID prevents the older attempt from finalizing. An expired lease does not cancel an in-flight PUT. Deletion/rejection guards precede this lease check so a late successful PUT restores cleanup intent instead of reviving deleted data.

`PENDING` means awaiting worker processing, not already scanned or parsed. The outbox persists dispatch intent for the relay; it does not call Celery here. `emit()` records telemetry. `accepted_job()` serializes current job state with HTTP 202, a Location header and Retry-After.

## Reference and verification

Main path: validate → reserve in PostgreSQL → upload original → verify current lease → atomically commit PENDING document + QUEUED job + OutboxEvent → return 202.

The function uses owner/document/job locks and durable records to handle retries and concurrent attempts. Helper internals can produce further exceptions; database and object storage do not share an atomic commit. Runtime behavior and hosted rendering are separate from source and Mermaid-syntax verification.

Pending learner checkpoint, preserved: “Attempt A finishes its PUT after attempt B has replaced its lease. Should A queue the job and create an outbox event, or return the current job without finalizing?”
