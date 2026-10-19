# Upload to score: execution views

The seven business steps share one durable flow: **1 Submit · 2 Accept · 3 Relay · 4 Queue · 5 Process · 6 Save · 7 Read**. Separate delivery detail uses **7a Persist · 7b Publish wake · 7c Deliver change · 7d Read affected state**. A receipt accepts work; the event stream announces changes; authorized REST returns the report.

[Architecture overview](architecture.md) · [Operating contract](implementation-guide.md) · [AWS service journey](aws-service-journey.md)

For the step-by-step API admission lesson, open [_admit_jobs(): four branch-by-branch diagrams](admit-jobs-walkthrough.md). It covers request validation, transaction A, original upload and transaction B.

## End-to-end execution

![End-to-end execution.](assets/upload-to-score-overview.svg)

Original bytes stay private; UUID work messages and minimal owner-change signals have separate responsibilities.

<details>
<summary>Editable Mermaid source</summary>

```mermaid
flowchart TB
  accTitle: User action to saved score and visible completion
  accDescr: Seven business steps connect original storage, reliable processing and durable event delivery. SSE changes trigger authorized reads, not an embedded result payload.
  UI[1 React analyze handler + API client] --> API[2 Django owner / CSRF / retry / supply checks]
  API --> S[Private original PUT; release DB for I/O]
  S --> DB[Atomic queued job + outbox + revision]
  API -->|Saved document reuse| DB
  DB --> R[3 Productive confirmed relay]
  R --> Q[4 RabbitMQ UUID]
  Q --> W[5 Leased worker: original / safety / parser / Converse]
  W --> SAVE[6 Owner-stream / document / job fence; report + notice + event]
  SAVE --> ER[7a–b Durable event relay → ordered Valkey shard]
  ER --> G[7c Raw ASGI gateway → SSE identifiers]
  G --> GET[7d React targeted authorized REST reads]
  GET --> RESULT[Same processing route → result; other routes → inbox]
```

[Source file](assets/upload-to-score-overview.mmd)

</details>

## 1–2 · Admission and retry identity

![1–2 · Admission and retry identity.](assets/upload-to-score-admission.svg)

Unchanged-key recovery precedes new-work limits. Only stored, finalized source admits queued processing; an uploading reservation can require unchanged-input retry.

<details>
<summary>Editable Mermaid source</summary>

```mermaid
flowchart TB
  accTitle: Logical admission, source reservation and atomic queueing
  accDescr: Idempotency recovery precedes new-work limits. Original bytes are stored before queued dispatch intent is committed; object storage and PostgreSQL are independent boundaries.
  FORM[1 App.analyze → api POST /api/jobs/] --> CHECK[2 Session / CSRF / input / owner checks]
  CHECK --> LOCK[Lock owner stream; inspect retry identity]
  LOCK --> EXIST{Existing unchanged key?}
  EXIST -->|Recover; no new charge| RECEIPT[Return logical job state]
  EXIST -->|No| SUPPLY{Owner fairness + fresh supply + finite budgets}
  SUPPLY -->|Denied| ERR[429 / 503 + Retry-After]
  SUPPLY -->|Allowed| RES[Reserve job + document + upload lease]
  RES --> IO[Release DB; PUT private original]
  IO --> FINAL[Lock owner stream → document → job]
  FINAL --> COMMIT[Commit pending document + queued job + outbox + change]
  COMMIT --> RECEIPT
  CHECK -->|Owned saved source| REUSE[Same guards; skip upload]
  REUSE --> COMMIT
  IO -->|Interrupted| REC[Same-input retry or abandoned-upload cleanup]
```

[Source file](assets/upload-to-score-admission.mmd)

</details>

## 3–4 · Confirmed dispatch

![3–4 · Confirmed dispatch.](assets/upload-to-score-dispatch.svg)

The reused producer drains productive batches. Duplicate delivery is expected; PostgreSQL owns claim and completion authority.

<details>
<summary>Editable Mermaid source</summary>

```mermaid
flowchart LR
  accTitle: Durable intent to bounded worker claim
  accDescr: A long-lived confirmed producer drains committed outbox batches. Publisher ambiguity and redelivery are expected; the PostgreSQL lease determines which claim may commit.
  O[Committed OutboxEvent] --> R[3 relay_jobs productive loop]
  R --> P[Reused producer; persistent UUID publication]
  P --> Q[4 RabbitMQ quorum queue]
  Q -->|Confirm| SENT[Mark sent in PostgreSQL]
  Q --> W[Celery run_match wrapper]
  W --> C[5 claim_job: queued status + lease + deadline]
  C --> RUN[run_job]
  Q -. Redelivery / confirmation ambiguity .-> C
  R -. Independent bounded maintenance .-> M[Recover leases / source cleanup / sample supply]
```

[Source file](assets/upload-to-score-dispatch.mmd)

</details>

## 5–6 · Source, evidence and outcome

![5–6 · Source, evidence and outcome.](assets/upload-to-score-worker.svg)

External I/O releases database connections. Integrity/safety gates and quote validation precede the atomic, lease-fenced outcome.

<details>
<summary>Editable Mermaid source</summary>

```mermaid
flowchart TB
  accTitle: Source retrieval to fenced score
  accDescr: External work uses no held database connection. Source integrity, malware checks and evidence validation precede atomic result commitment.
  C[5 claim_job] --> RELEASE[Release DB connection before external I/O]
  RELEASE --> G[document_text: retrieve exact original + size / SHA-256]
  G --> SAFETY[Local ClamAV; AWS GuardDuty tag before GET]
  SAFETY --> CACHE{Matching parser version?}
  CACHE -->|Yes, not explicit reprocess| TEXT[Bounded extracted text]
  CACHE -->|No| PARSE[Parse selectable PDF / UTF-8 text]
  PARSE --> TEXT
  TEXT --> PROVIDER[extract_evidence → Converse request]
  PROVIDER --> VALID[Validate schema, source quotes and skill mentions]
  VALID --> SCORE[Application-owned weighted coverage]
  SCORE --> LOCK[6 Lock owner stream → document → job]
  LOCK --> FENCE{Live source and current lease?}
  FENCE -->|Yes| SAVE[Atomic Match + job + notice + revisions; release admission]
  FENCE -->|No| DISCARD[Reject stale completion]
```

[Source file](assets/upload-to-score-worker.mmd)

</details>

## Recovery and source lifecycle

![Recovery and source lifecycle.](assets/upload-to-score-recovery-lifecycle.svg)

Finite retries recover accepted intent. Deletion first fences access/work and then retries physical cleanup; the configurable source policy remains 90 days.

<details>
<summary>Editable Mermaid source</summary>

```mermaid
flowchart TB
  accTitle: Bounded recovery and retained-source lifecycle
  accDescr: Retry identity, outbox and leases recover accepted work while source deletion fences access and results before physical cleanup. No recurring browser polling is used.
  U[Interrupted PUT] --> ID[Same input + key recovers upload reservation]
  ID --> FINAL[Confirmed PUT → queued job + outbox]
  FINAL --> BROKER[Broker outage / ambiguous confirm → retain outbox]
  BROKER --> CLAIM[Worker claim or bounded lease recovery]
  CLAIM --> END[Three provider claims; 90s lease; ten-minute deadline]
  END --> TERMINAL[Terminal outcome + one notice + event]
  TERMINAL --> SIGNAL[Event relay / SSE reconnect / durable replay]
  SIGNAL --> GET[Authorized targeted read or reset snapshot]
  D[Owner deletion / 90-day policy expiry] --> F[Owner-stream then document lock; tombstone and fence]
  F --> CLEAN[Retry physical object DELETE; clear derived source state]
  CLEAN --> PURGE[Remove cleanup tombstone after seven days]
  F -. No late result resurrection .-> END
```

[Source file](assets/upload-to-score-recovery-lifecycle.mmd)

</details>

## 7 · Connected delivery and route-safe reads

![7 · Connected delivery and route-safe reads.](assets/upload-to-score-completion.svg)

Durable revisions bridge at-most-once wake transport. A change signal triggers bounded affected reads; off-route completion preserves current work.

<details>
<summary>Editable Mermaid source</summary>

```mermaid
flowchart TB
  accTitle: Durable completion to route-safe browser state
  accDescr: The durable event ledger bridges database results and at-most-once owner wakeups. A dedicated ASGI gateway signals affected resources; React preserves unrelated work.
  TX[6 Atomic report + terminal notice] --> LEDGER[7a StreamState revision + StreamEvent]
  LEDGER --> RELAY[7b event_relay: publish pending owner wake]
  RELAY --> V[Stable owner modulo ordered Valkey shards]
  V --> G[7c Shared subscription → bounded raw ASGI gateway]
  LEDGER -. Authorized replay after subscribe ACK .-> G
  G --> SSE[EventSource change: IDs + revision]
  SSE --> READ[7d Coalesce / deduplicate; four concurrent REST reads]
  READ --> API[Owner-scoped job / documents / inbox GET]
  API --> ROUTE{Same processing route succeeded?}
  ROUTE -->|Yes| RESULT[Replace with saved result route]
  ROUTE -->|No| INBOX[Update saved inbox; preserve route / draft / focus]
  SSE -. Hidden / offline / outage .-> REC[Close; jitter reconnect; fresh snapshot]
  REC --> READ
```

[Source file](assets/upload-to-score-completion.mmd)

</details>

## Exact implementation boundaries

These links pin the verified runtime/deployment commit; diagrams describe that source rather than an alternative target. Named handlers connect the user action through every selected service.

| Step | Caller → receiver | Responsibility |
| --- | --- | --- |
| 1 Submit | [analyze → API client](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/frontend/src/App.tsx#L361) | Original/saved ID, requirements and unchanged retry identity |
| 1 HTTP | [api](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/frontend/src/api.ts) | Same-origin session/CSRF and bounded timeout |
| 2 Admission | [admit_jobs](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/backend/matching/views.py#L273) | Owner-stream lock, unchanged-key recovery, reserve/PUT/finalize |
| 2 Supply | [reserve_admission](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/backend/matching/admission.py#L25) | Fair owner/global rate/active budgets, fresh queue/supply gate |
| 2 Source | [put_original](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/backend/matching/documents.py#L81) | Exact bounded bytes; database released before object I/O |
| 3–4 Dispatch | [publish_job / relay_once](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/backend/matching/jobs.py#L175) | Reused confirmed producer; UUID-only persistent delivery |
| 3 Productive loop | [relay_jobs](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/backend/matching/management/commands/relay_jobs.py) | Productive drain and separate bounded maintenance/supply sample |
| 5 Source/process | [run_job](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/backend/matching/jobs.py#L104) | Lease, source verification/safety, parser cache and external-I/O connection release |
| 5 Provider | [extract_evidence](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/backend/matching/services.py#L163) | Converse → schema/source/skill validation → weighted score |
| 6 Commit | [finish_job](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/backend/matching/jobs.py#L72) | Owner-stream → document → job fence; report, notice, revision and admission release |
| 7a–b Event publication | [record_change / relay_events](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/backend/matching/events.py#L25) | Durable owner revision then publish to stable ordered shard |
| 7c Delivery | [Gateway.__call__](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/backend/event_gateway.py#L284) | Session/origin checks; subscribe ACK then bounded replay and SSE |
| 7d Reads/routes | [apply](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/frontend/src/App.tsx#L247) | Authorized affected reads; preserve unrelated route/draft |
| 7d Stream lifecycle | [workspaceEvents](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/frontend/src/workspaceEvents.ts#L21) | One visible-tab EventSource, coalescing, bounded reads and jitter reconnect |
| Inbox | [notifications / notification_read](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/backend/matching/views.py#L209) | Signed keyset cursor and independent idempotent read receipt |
| Source lifecycle | [tombstone / reconcile_documents](https://github.com/junrillg/resume-match-bedrock/blob/4e69a31653b4dd78de6ac35ff59bace3b798ac6e/backend/matching/documents.py#L211) | Immediate access fence, durable change and retried physical cleanup |

## Interpreting the result

- A `202 queued` means original storage and dispatch intent committed; it is not a finished score. `202 uploading` means reservation only.
- New-work `429`/`503` is distinct from accepted-job recovery. No connection failure erases a saved outcome.
- SSE carries identifiers and revisions, never résumé text or the report. Initial/reconnect snapshots and targeted REST remain owner-authorized.
- One saved report and one terminal notice do not imply exactly-once broker/model execution.
- Local 1,000-stream evidence and small AWS defaults are separate from the one-million connection / 100-comparison-per-second planning inputs. [Measured bounds](decisions/0009-event-driven-completion.md#local-verification) · [Deployment bounds](decisions/0010-bounded-deployment.md)
