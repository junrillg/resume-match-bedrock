# ADR 0008: resumable processing and durable completion notifications

Status: processing/inbox behavior implemented; polling transport superseded by [ADR 0009](0009-event-driven-completion.md) · 2026-10-19

## Context

Comparisons already run independently in a worker. The browser polls without holding its submit lock, but presents status and results beneath the form. A shared request lock disables unrelated controls, and completion has no persisted inbox.

## Decision

After finalized admission, navigate to `/jobs/<id>` immediately. Users can start another comparison, inspect history or sign out while the worker continues. A reserved `uploading` receipt is incomplete: retain the source and same-key recovery rather than promise processing.

Persist one completion notification per job in the same PostgreSQL transaction as its terminal outcome. Success and terminal failure notify; intermediate retries do not. The notification references the job, carries no source/evidence payload, and cascades with deletion and source expiry. Existing terminal jobs remain accessible in history; migration does not fabricate unread historical notifications.

Expose owner-scoped notification listing and a CSRF-protected idempotent read acknowledgement. The inbox survives navigation, refresh and sign-out. Bounded background reads discover completion; focus/reconnect catches up. A closed browser receives its saved notification when it returns. This implementation supplies in-app delivery; external email/push needs a separately configured delivery channel.

Processing and result routes resolve the authoritative owner-scoped job endpoint, including older jobs outside the recent list. Only the same visible processing route can automatically transition to `/results/<job-id>`. Completion elsewhere adds an inbox entry without replacing a draft or stealing focus. Notification activation opens its result/status destination. Mark as read is a separate persisted action; acknowledgement failure does not prevent result access.

Pending state belongs to the action/entity, never to the duration of the worker job. Navigation and sign-out stay available. Async responses are fenced against session changes, navigation and deletion; errors show recoverable states without declaring background work failed. No invented percent complete or estimated finish time.

## Alternatives and consequences

- Keeping inline results alone leaves the return path and unread state ambiguous.
- WebSockets/SSE provide faster connected delivery but require new connection infrastructure and still need durable state/catch-up. Bounded polling fits this workload and current WSGI deployment.
- A browser-only toast is lost on refresh and cannot represent completion while away.
- `on_commit()` is suitable for best-effort telemetry, but a process crash can lose a notification callback. Its database row belongs inside the outcome transaction.

No new managed service is required. AWS uses the same application/PostgreSQL contract; this decision does not claim cloud deployment or exactly-once external delivery.

## Verification and delivery plan

| Milestone | Scope | Observable check |
| --- | --- | --- |
| Design | Source review, this ADR, research | Polling and request lock distinguished; delivery limits explicit |
| Durable inbox | Model/migration, terminal writes, owner/read APIs | Atomic rollback, duplicate/stale delivery, success/failure, CSRF/isolation/deletion |
| Nonblocking UI | Processing/results routes, inbox, scoped pending and background refresh | Leave during queued work, submit another, reload/deep link/Back, completion while elsewhere, session fences |
| Communication | Professional diagrams/source map and operating reference | User-to-worker-to-notification-to-result journey matches actual code and runtime |

## Sources

Accessed 2026-10-19. [Async request-reply](https://learn.microsoft.com/en-us/azure/architecture/patterns/asynchronous-request-reply) supports accepted receipts, status resources and bounded polling. [Django transactions](https://docs.djangoproject.com/en/5.2/topics/db/transactions/) defines atomic writes and post-commit callback limits. [React effect cleanup](https://react.dev/reference/react/useEffect) supports cancellation against stale responses. [History API](https://developer.mozilla.org/en-US/docs/Web/API/History_API/Working_with_the_History_API) defines same-document navigation and Back/Forward handling. Route names, in-app delivery and notification lifetime are this design's choices.

## Observed local evidence

The backend passed 112 tests and migration drift checks; the frontend passed 46 tests and the production build. Real Compose HTTP checks verified two queued jobs, one notification each, a fresh login, idempotent read and cross-owner denial. Chrome checks verified navigation/new work while queued, off-route draft preservation, result links/reload/Back, read persistence, same-job automatic transition and completion while the app tab was closed. Desktop and 390×844 mobile inbox views passed; no horizontal overflow was observed. This establishes the stated local behavior, not live cloud or external notification delivery.
