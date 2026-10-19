export type WorkspaceChange = {
  revision: number;
  kind: 'job.changed' | 'document.changed' | 'inbox.changed' | 'workspace.changed';
  job_id?: string;
  document_id?: string;
};
export type WorkspaceUpdates = { full: boolean; jobs: string[]; documents: string[]; inbox: boolean };
type Callbacks = {
  apply: (updates: WorkspaceUpdates, signal: AbortSignal) => Promise<void>;
  error: (error: unknown) => void;
  connectionError: (message?: string) => void;
  sessionEnded: () => void;
  connection: (offline: boolean) => void;
};
const validRevision = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) >= 0;
const validId = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9-]{36}$/i.test(value);
const jitter = (delay: number) => Math.round(delay * (1 + Math.random() * .25));

// One stream per visible authenticated tab. The database snapshot is taken after
// server subscription acknowledgement; changes arriving during it stay buffered.
export function workspaceEvents(callbacks: Callbacks) {
  let stopped = false; let stream: EventSource | undefined;
  let generation = 0; let cursor: number | undefined; let ready = false;
  let failures = 0; let readFailures = 0; let readPaused = false;
  let reading = false; let full = false; let inbox = false;
  let jobs = new Set<string>(); let documents = new Set<string>();
  let controller: AbortController | undefined;
  let flushTimer: ReturnType<typeof setTimeout> | undefined;
  let retryTimer: ReturnType<typeof setTimeout> | undefined;
  let readyTimer: ReturnType<typeof setTimeout> | undefined;
  const visible = () => !stopped && document.visibilityState !== 'hidden' && navigator.onLine;
  const pending = () => full || inbox || jobs.size > 0 || documents.size > 0;
  function scheduleFlush(delay = 100) {
    if (!visible() || !ready || readPaused || reading || flushTimer) return;
    if (delay === 0) { queueMicrotask(() => { void flush(); }); return; }
    flushTimer = setTimeout(() => { flushTimer = undefined; void flush(); }, delay);
  }
  async function flush() {
    if (!visible() || reading || !pending()) return;
    reading = true; controller = new AbortController();
    const batch = { full, inbox, jobs: [...jobs], documents: [...documents] };
    full = false; inbox = false; jobs.clear(); documents.clear();
    try {
      await callbacks.apply(batch, controller.signal); readFailures = 0;
      if (typeof EventSource === 'undefined' && !stopped) callbacks.connectionError('This browser cannot receive live updates. Refresh saved updates when needed.');
    }
    catch (error) {
      if (!stopped && !controller.signal.aborted) {
        callbacks.error(error);
        full ||= batch.full; inbox ||= batch.inbox;
        batch.jobs.forEach((id) => jobs.add(id)); batch.documents.forEach((id) => documents.add(id));
        if (jobs.size + documents.size > 256) { full = true; jobs.clear(); documents.clear(); }
        readFailures += 1; readPaused = readFailures >= 3;
        // Retry this failed resource batch at most twice. A live-stream outage
        // never starts HTTP polling; recovery after exhaustion is explicit or on
        // a successful new subscription, which reauthorizes a fresh snapshot.
        if (!readPaused) flushTimer = setTimeout(() => {
          flushTimer = undefined; if (visible()) void flush();
        }, jitter(30000 * 2 ** (readFailures - 1)));
      }
    } finally { reading = false; if (pending()) scheduleFlush(); }
  }
  function reconcile() {
    clearTimeout(flushTimer); flushTimer = undefined;
    readPaused = false; readFailures = 0; full = true; scheduleFlush(0);
  }
  function close() {
    generation += 1; ready = false; stream?.close(); stream = undefined;
    clearTimeout(readyTimer); clearTimeout(retryTimer);
  }
  function failed(instance: number) {
    if (!visible() || instance !== generation) return;
    close(); failures += 1; callbacks.connectionError();
    // Spread fleet-wide reconnects: 15–30s, 30–60s, then 60–120s.
    // There is no automatic REST fallback during a streaming outage.
    const cap = Math.min(120000, 30000 * 2 ** Math.min(failures - 1, 2));
    retryTimer = setTimeout(connect, Math.round(cap / 2 + Math.random() * cap / 2));
  }
  function message(event: Event): unknown {
    try { return JSON.parse((event as MessageEvent<string>).data); } catch { return null; }
  }
  function connect() {
    if (!visible()) return;
    close(); const instance = generation;
    if (typeof EventSource === 'undefined') { callbacks.connectionError('This browser cannot receive live updates. Refresh saved updates when needed.'); return; }
    try { stream = new EventSource(`/api/events/${cursor === undefined ? '' : `?cursor=${cursor}`}`); }
    catch { failed(instance); return; }
    const alive = () => !stopped && instance === generation;
    stream.addEventListener('ready', (event) => {
      if (!alive()) return;
      const value = message(event) as { revision?: unknown } | null;
      if (!value || !validRevision(value.revision)) { failed(instance); return; }
      cursor = Math.max(cursor ?? 0, value.revision); ready = true; failures = 0;
      clearTimeout(readyTimer);
      // Includes first load, replay completion and reconnection. Buffered changes
      // are consumed after this snapshot, closing subscribe/catch-up races.
      reconcile();
    });
    stream.addEventListener('reset', (event) => {
      if (!alive()) return;
      const value = message(event) as { revision?: unknown } | null;
      if (!value || !validRevision(value.revision)) { failed(instance); return; }
      cursor = value.revision; full = true;
      // Reset may be followed by ready; do not discard already-buffered changes.
      if (ready) scheduleFlush(0);
    });
    stream.addEventListener('change', (event) => {
      if (!alive()) return;
      const value = message(event) as Partial<WorkspaceChange> | null;
      if (!value || !validRevision(value.revision) || !['job.changed', 'document.changed', 'inbox.changed', 'workspace.changed'].includes(value.kind ?? '')) {
        failed(instance); return;
      }
      if (cursor !== undefined && value.revision <= cursor) return;
      cursor = value.revision;
      if (value.kind === 'workspace.changed') full = true;
      else if (value.kind === 'inbox.changed') inbox = true;
      else if (value.kind === 'job.changed' && validId(value.job_id)) jobs.add(value.job_id);
      else if (value.kind === 'document.changed' && validId(value.document_id)) documents.add(value.document_id);
      else full = true;
      if (value.kind === 'job.changed' && validId(value.document_id)) documents.add(value.document_id);
      if (jobs.size + documents.size > 256) { full = true; jobs.clear(); documents.clear(); }
      scheduleFlush();
    });
    stream.addEventListener('session-ended', () => { if (alive()) { stop(); callbacks.sessionEnded(); } });
    stream.addEventListener('error', () => failed(instance));
    readyTimer = setTimeout(() => failed(instance), 15000);
  }
  function wake() {
    if (!visible()) return;
    if (!stream) connect(); else reconcile();
  }
  function connection() {
    callbacks.connection(!navigator.onLine);
    if (visible()) wake();
    else {
      close(); clearTimeout(flushTimer); flushTimer = undefined;
      // Already completed responses remain valid; cancellation stops unnecessary work.
      controller?.abort();
    }
  }
  function stop() {
    stopped = true; close(); clearTimeout(flushTimer); controller?.abort();
    window.removeEventListener('online', connection); window.removeEventListener('offline', connection);
    window.removeEventListener('focus', wake); document.removeEventListener('visibilitychange', connection);
  }
  window.addEventListener('online', connection); window.addEventListener('offline', connection);
  window.addEventListener('focus', wake); document.addEventListener('visibilitychange', connection);
  connect();
  return { stop, reconcile: () => {
    if (!visible()) return;
    clearTimeout(flushTimer); flushTimer = undefined;
    readPaused = false; readFailures = 0; full = true;
    // Explicit refresh remains available when streaming is unsupported/unavailable.
    // It is a user/mutation action, never a background polling timer.
    void flush();
    if (!stream && typeof EventSource !== 'undefined') connect();
  } };
}
