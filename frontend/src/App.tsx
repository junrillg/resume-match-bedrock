import { useEffect, useRef, useState, type FormEvent, type MouseEvent } from 'react';
import { api, ApiError, downloadDocument, type CompletionNotification, type NotificationPage, type DocumentRecord, type Job, type Match, type Requirement, type Session } from './api';

import { readRoute, jobPath, resultPath, reportPath, type Route } from './navigation';

const defaults: Requirement[] = [
  { skill: 'Python', weight: 3 }, { skill: 'Django', weight: 3 },
  { skill: 'React', weight: 2 }, { skill: 'PostgreSQL', weight: 2 },
];
const sample = 'SYNTHETIC SAMPLE — not a real candidate\n\nBackend engineer\nBuilt Python services and Django APIs for an internal inventory application.\nCreated React interfaces for searching products and reviewing stock.\nWrote integration tests and reviewed changes with the engineering team.';
const activeJob = (job: Job) => job.status === 'uploading' || job.status === 'queued' || job.status === 'running';
const reusableDocument = (document: DocumentRecord) => document.status === 'pending' || document.status === 'ready';
const documentLabel = (document: DocumentRecord) => document.filename || (document.status === 'deleting' ? 'Document being deleted' : 'Unavailable original');
const documentStatuses: Record<DocumentRecord['status'], string> = {
  uploading: 'Upload incomplete', pending: 'Waiting for safety checks', ready: 'Ready',
  rejected: 'Rejected by safety checks', deleting: 'Deletion pending', deleted: 'Deleted',
};
const jobMessages: Record<string, string> = {
  document_rejected: 'The original did not pass safety or document checks. Use another source.',
  document_integrity: 'The stored original failed its integrity check. Use another source.',
  document_unavailable: 'The original or its safety checks are unavailable. Try processing the saved source again later.',

  invalid_evidence: 'The extracted evidence could not be verified against the résumé.',
  provider_rejected: 'The extraction provider rejected this request.',
  processing_failed: 'The résumé could not be processed.',
  retry_exhausted: 'Processing stopped after the allowed retry attempts.',
  deadline_exceeded: 'The job exceeded its processing deadline.',
};
const providerLabels: Record<Session['provider'], string> = {
  demo: 'Demo · local deterministic',
  'bedrock-local': 'Local contract provider',
  bedrock: 'AWS Bedrock',
};
const providerLabel = (provider: Session['provider']) => providerLabels[provider];
const providerDisclosure: Record<Session['provider'], string> = {
  demo: 'The worker extracts literal skill mentions within this application.',
  'bedrock-local': 'Résumé text goes to a separate local provider service for evidence extraction. Use documents you are authorized to process.',
  bedrock: 'Résumé text goes to AWS Bedrock in the configured region for evidence extraction. Use documents you are authorized to process.',
};
const errorText = (error: unknown) => error instanceof ApiError
  ? `${error.message}${error.requestId ? ` Reference: ${error.requestId}` : ''}`
  : 'Something went wrong. Please try again.';

export function MatchResult({ match, onDelete, busy }: { match: Match; onDelete: () => void; busy: boolean }) {
  const matched = match.requirements.filter((item) => item.matched).length;
  return <section className="panel result" aria-labelledby="result-heading" aria-live="polite">
    <div className="section-heading"><div><p className="eyebrow">Evidence report</p><h2 id="result-heading">{match.job_title}</h2></div><span className="tag">{providerLabel(match.provider)}</span></div>
    <div className="score-row">
      <div className="score"><strong>{match.score}<span>%</span></strong><span>weighted coverage</span></div>
      <div><h3>{matched} of {match.requirements.length} skills evidenced</h3><p>Only evidence found in the résumé contributes to this score. Review every excerpt before drawing a conclusion.</p></div>
    </div>
    <div className="coverage-track" role="meter" aria-label="Weighted skill evidence coverage" aria-valuemin={0} aria-valuemax={100} aria-valuenow={match.score}><span style={{ width: `${match.score}%` }} /></div>
    <div className="evidence-list">{match.requirements.map((item) => <article className="evidence" key={item.skill}>
      <div className="evidence-heading"><h3><span className={`evidence-symbol ${item.matched ? 'found' : ''}`} aria-hidden="true">{item.matched ? '✓' : '−'}</span>{item.skill}</h3><span className="weight-label">Weight {item.weight} · {item.matched ? 'Evidenced' : 'Not evidenced'}</span></div>
      {item.matched && item.evidence ? <blockquote>{item.evidence}</blockquote> : <p className="gap">No supporting excerpt found. This is a gap in the document, not proof of a missing ability.</p>}
    </article>)}</div>
    <div className="report-footer"><span>Reference {match.request_id}</span><button className="text-button danger" type="button" disabled={busy} onClick={onDelete}>Delete this report</button></div>
  </section>;
}

// A failed sibling must settle before another monitoring cycle can start.
async function settledBatch<T extends readonly unknown[]>(...requests: { [K in keyof T]: Promise<T[K]> }): Promise<T> {
  const responses = await Promise.allSettled(requests);
  const failure = responses.find((response) => response.status === 'rejected');
  if (failure?.status === 'rejected') throw failure.reason;
  return responses.map((response) => (response as PromiseFulfilledResult<unknown>).value) as unknown as T;
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [signingIn, setSigningIn] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [deletingSelection, setDeletingSelection] = useState(false);
  const [deletingDocumentId, setDeletingDocumentId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [jobTitle, setJobTitle] = useState('Full stack engineer');
  const [requirements, setRequirements] = useState(defaults);
  const [source, setSource] = useState<'paste' | 'file' | 'saved'>('paste');
  const [resume, setResume] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [savedDocumentId, setSavedDocumentId] = useState('');
  const [reprocess, setReprocess] = useState(false);
  const [downloadingDocumentId, setDownloadingDocumentId] = useState<string | null>(null);
  const [deleteDocumentId, setDeleteDocumentId] = useState<string | null>(null);
  const [matches, setMatches] = useState<Match[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [deleteRequested, setDeleteRequested] = useState(false);
  const [pollError, setPollError] = useState('');
  const [retryPending, setRetryPending] = useState(false);
  const [route, setRoute] = useState<Route>(() => readRoute());
  const [routeJob, setRouteJob] = useState<Job | null>(null);
  const [routeError, setRouteError] = useState('');
  const [routeLoading, setRouteLoading] = useState(false);
  const [routeRefresh, setRouteRefresh] = useState(0);
  const [notifications, setNotifications] = useState<CompletionNotification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [loadingNotifications, setLoadingNotifications] = useState(false);
  const [readingIds, setReadingIds] = useState<string[]>([]);
  const [notificationError, setNotificationError] = useState('');
  const [offline, setOffline] = useState(!navigator.onLine);
  const privateEpoch = useRef(0);
  const workspaceRevision = useRef(0);
  const routeRevision = useRef(0);
  const deletedDocumentIds = useRef(new Set<string>());
  const deletedJobIds = useRef(new Set<string>());
  const latestJobs = useRef(jobs); latestJobs.current = jobs;
  const routeCurrent = useRef(route);
  const hasMorePages = useRef(false);
  const resetInboxOnRefresh = useRef(false);
  const draftSource = useRef({ source, savedDocumentId }); draftSource.current = { source, savedDocumentId };
  const latestRouteJob = useRef(routeJob); latestRouteJob.current = routeJob;
  const submission = useRef<{ fingerprint: string; key: string } | null>(null);
  const monitorWake = useRef<(() => void) | null>(null);
  const routeHeading = useRef<HTMLHeadingElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const selectedJob = route.kind === 'job' || route.kind === 'result'
    ? jobs.find((job) => job.id === route.id) ?? (routeJob?.id === route.id ? routeJob : null) : null;
  const selectedLegacy = route.kind === 'legacy' ? matches.find((match) => match.id === route.id) ?? null : null;
  const displayedMatch = selectedJob?.match ?? selectedLegacy;
  const legacyMatches = matches.filter((match) => !jobs.some((job) => job.match?.id === match.id));
  const hasActiveJobs = jobs.some(activeJob) || !!(routeJob && activeJob(routeJob)) || documents.some((document) => document.status === 'deleting');
  const activeState = useRef(hasActiveJobs);
  activeState.current = hasActiveJobs;
  const usableDocuments = documents.filter(reusableDocument);
  const savedDocument = usableDocuments.find((document) => document.id === savedDocumentId);
  const documentToDelete = documents.find((document) => document.id === deleteDocumentId);

  function navigate(path: string, replace = false) {
    const destination = readRoute(path);
    if (destination.kind === 'not-found') return;
    routeRevision.current += 1;
    routeCurrent.current = destination;
    if (replace) window.history.replaceState(null, '', path);
    else window.history.pushState(null, '', path);
    setRoute(destination); setRouteError(''); setRouteJob(null); setDeleteRequested(false);
  }
  function follow(event: MouseEvent<HTMLAnchorElement>) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.currentTarget.target) return;
    const destination = new URL(event.currentTarget.href);
    if (destination.origin !== window.location.origin || readRoute(destination.pathname).kind === 'not-found') return;
    event.preventDefault(); navigate(destination.pathname);
  }
  useEffect(() => {
    const pop = () => {
      routeRevision.current += 1;
      routeCurrent.current = readRoute();
      setRoute(routeCurrent.current); setRouteError(''); setRouteJob(null); setDeleteRequested(false);
    };
    window.addEventListener('popstate', pop);
    return () => window.removeEventListener('popstate', pop);
  }, []);
  useEffect(() => {
    document.title = `${route.kind === 'notifications' ? 'Notifications' : route.kind === 'result' || route.kind === 'legacy' ? 'Evidence report' : route.kind === 'job' ? 'Comparison status' : 'Evidence workspace'} · Resume Match`;
    if (route.kind !== 'home') requestAnimationFrame(() => routeHeading.current?.focus());
  }, [route.path, loading, session?.authenticated]);

  function clearPrivateState() {
    privateEpoch.current += 1; workspaceRevision.current += 1; routeRevision.current += 1;
    setSubmitting(false); setSigningIn(false); setDeletingSelection(false); setLoading(false);
    setMatches([]); setResume(''); setFile(null); setPassword(''); setUsername('');
    setJobs([]); setRouteJob(null); setRouteError(''); setPollError(''); setRetryPending(false);
    setSource('paste'); submission.current = null; deletedDocumentIds.current.clear(); deletedJobIds.current.clear();
    setDocuments([]); setSavedDocumentId(''); setReprocess(false); setDeleteDocumentId(null); setDownloadingDocumentId(null); setDeletingDocumentId(null);
    setNotifications([]); setUnreadCount(0); setNextOffset(null); setReadingIds([]); setNotificationError(''); setLoadingNotifications(false); hasMorePages.current = false;
    setJobTitle('Full stack engineer'); setRequirements(defaults); setDeleteRequested(false);
    if (fileRef.current) fileRef.current.value = '';
  }
  async function refreshSession() {
    const epoch = privateEpoch.current;
    const current = await api<Session>('session/');
    if (epoch === privateEpoch.current) setSession(current);
    return current;
  }
  async function loseSession() {
    clearPrivateState(); setSession(null);
    try { await refreshSession(); } catch { /* The sign-in panel offers connection recovery. */ }
  }
  function updateInbox(page: NotificationPage, reset = false) {
    reset = reset || resetInboxOnRefresh.current;
    if (reset) { hasMorePages.current = false; resetInboxOnRefresh.current = false; }
    setUnreadCount(page.unread_count);
    setNotifications((previous) => reset || !hasMorePages.current ? page.notifications : [
      ...page.notifications, ...previous.filter((notice) => !page.notifications.some((item) => item.id === notice.id)),
    ]);
    if (reset || !hasMorePages.current) setNextOffset(page.next_offset);
  }
  async function loadWorkspace() {
    const epoch = privateEpoch.current;
    const revision = workspaceRevision.current;
    const [jobList, reportList, documentList, inbox] = await Promise.all([
      api<{ jobs: Job[] }>('jobs/'), api<{ matches: Match[] }>('matches/'),
      api<{ documents: DocumentRecord[] }>('documents/'), api<NotificationPage>('notifications/?offset=0'),
    ]);
    if (epoch !== privateEpoch.current || revision !== workspaceRevision.current) return;
    setJobs(jobList.jobs); setMatches(reportList.matches); setDocuments(documentList.documents); updateInbox(inbox);
  }
  async function load() {
    const epoch = privateEpoch.current; setLoading(true); setError('');
    try {
      const current = await refreshSession();
      if (epoch !== privateEpoch.current) return;
      if (current.authenticated) await loadWorkspace(); else clearPrivateState();
    } catch (error) {
      if (epoch !== privateEpoch.current) return;
      setError(errorText(error));
      if (error instanceof ApiError && error.status === 401) await loseSession();
    } finally { if (epoch === privateEpoch.current) setLoading(false); }
  }
  useEffect(() => { void load(); return () => { privateEpoch.current += 1; }; }, []);

  // A detail URL is independently authorized; recent-history pagination is not a 404 test.
  useEffect(() => {
    if (!session?.authenticated || (route.kind !== 'job' && route.kind !== 'result')) return;
    const epoch = privateEpoch.current; const revision = workspaceRevision.current;
    const controller = new AbortController(); let cancelled = false;
    setRouteLoading(true); setRouteError('');
    api<Job>(`jobs/${route.id}/`, { signal: controller.signal }).then((job) => {
      if (cancelled || epoch !== privateEpoch.current || revision !== workspaceRevision.current) return;
      setRouteJob(job); setJobs((previous) => previous.map((item) => item.id === job.id ? job : item));
    }).catch(async (error) => {
      if (cancelled || epoch !== privateEpoch.current || revision !== workspaceRevision.current) return;
      if (error instanceof ApiError && error.status === 401) await loseSession();
      else setRouteError(error instanceof ApiError && error.status === 404 ? 'This comparison is unavailable. It may have expired or been deleted, or belong to another account.' : errorText(error));
    }).finally(() => { if (!cancelled && epoch === privateEpoch.current) setRouteLoading(false); });
    return () => { cancelled = true; controller.abort(); };
  }, [route.path, routeRefresh, session?.authenticated]);

  // Only the same job's active processing page may advance automatically.
  useEffect(() => {
    if (session?.authenticated && route.kind === 'job' && routeCurrent.current.kind === 'job' && routeCurrent.current.id === route.id && selectedJob?.status === 'succeeded' && selectedJob.match && !routeError) {
      navigate(resultPath(selectedJob.id), true);
    }
  }, [route.kind, route.path, selectedJob?.id, selectedJob?.status, selectedJob?.match?.id, routeError, session?.authenticated]);

  // Idle inbox catch-up is required even when no active job is known in this tab.
  useEffect(() => {
    if (!session?.authenticated) return;
    const epoch = privateEpoch.current;
    let cancelled = false; let inFlight = false; let catchUp = false; let failures = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    const visible = () => document.visibilityState !== 'hidden' && navigator.onLine;
    const schedule = (delay: number) => { clearTimeout(timer); if (!cancelled && visible()) timer = setTimeout(poll, delay); };
    async function poll() {
      if (cancelled || !visible()) return;
      if (inFlight) { catchUp = true; return; }
      inFlight = true; controller = new AbortController();
      const revision = workspaceRevision.current;
      const current = routeCurrent.current;
      const detailId = current.kind === 'job' || current.kind === 'result' ? current.id : null;
      try {
        const [jobList, reportList, documentList, inbox, detail] = await settledBatch(
          api<{ jobs: Job[] }>('jobs/', { signal: controller.signal }),
          api<{ matches: Match[] }>('matches/', { signal: controller.signal }),
          api<{ documents: DocumentRecord[] }>('documents/', { signal: controller.signal }),
          api<NotificationPage>('notifications/?offset=0', { signal: controller.signal }),
          detailId ? api<Job>(`jobs/${detailId}/`, { signal: controller.signal }).catch((error) => {
            if (error instanceof ApiError && error.status === 404) return null;
            throw error;
          }) : Promise.resolve(null),
        );
        if (cancelled || epoch !== privateEpoch.current || revision !== workspaceRevision.current) return;
        activeState.current = jobList.jobs.some(activeJob) || !!(detail && activeJob(detail)) || documentList.documents.some((item) => item.status === 'deleting');
        setJobs(jobList.jobs); setMatches(reportList.matches); setDocuments(documentList.documents); updateInbox(inbox);
        if (detailId && 'id' in routeCurrent.current && routeCurrent.current.id === detailId) {
          setRouteJob(detail);
          if (!detail) setRouteError('This comparison is unavailable. It may have expired or been deleted, or belong to another account.');
        }
        failures = 0; setPollError('');
      } catch (error) {
        if (cancelled || epoch !== privateEpoch.current || !visible()) return;
        if (error instanceof ApiError && error.status === 401) await loseSession();
        else { failures += 1; setPollError(errorText(error)); }
      } finally {
        inFlight = false;
        if (!cancelled && epoch === privateEpoch.current) {
          const delay = catchUp ? 0 : failures ? Math.min(30000, 1000 * 2 ** Math.min(failures, 5)) : activeState.current ? 1000 : 15000;
          catchUp = false; schedule(delay);
        }
      }
    }
    const wake = () => { clearTimeout(timer); if (visible()) { if (inFlight) catchUp = true; else void poll(); } };
    const returnToApp = () => { resetInboxOnRefresh.current = true; wake(); };
    const connection = () => { setOffline(!navigator.onLine); if (visible()) returnToApp(); else { clearTimeout(timer); controller?.abort(); } };
    monitorWake.current = wake;
    window.addEventListener('online', connection); window.addEventListener('offline', connection); window.addEventListener('focus', returnToApp); document.addEventListener('visibilitychange', connection);
    schedule(activeState.current ? 1000 : 15000);
    return () => { cancelled = true; clearTimeout(timer); controller?.abort(); monitorWake.current = null;
      window.removeEventListener('online', connection); window.removeEventListener('offline', connection); window.removeEventListener('focus', returnToApp); document.removeEventListener('visibilitychange', connection); };
  }, [session?.authenticated]);

  async function perform(action: (epoch: number) => Promise<void>, pending: (value: boolean) => void) {
    const epoch = privateEpoch.current; pending(true); setError('');
    try { await action(epoch); }
    catch (error) {
      if (epoch !== privateEpoch.current) return;
      setError(errorText(error)); if (error instanceof ApiError && error.status === 401) await loseSession();
    } finally { if (epoch === privateEpoch.current) pending(false); }
  }
  async function login(event: FormEvent) {
    event.preventDefault(); if (signingIn) return;
    await perform(async (epoch) => {
      await api<Session>('login/', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }) }, session?.csrfToken);
      if (epoch !== privateEpoch.current) return;
      setPassword(''); await refreshSession();
      if (epoch === privateEpoch.current) await loadWorkspace();
    }, setSigningIn);
  }
  async function logout() {
    if (signingOut) return;
    const csrf = session?.csrfToken;
    clearPrivateState(); setSession(null); setSigningOut(true); setError('');
    const epoch = privateEpoch.current;
    try {
      const anonymous = await api<Session>('logout/', { method: 'POST' }, csrf);
      if (epoch === privateEpoch.current) setSession(anonymous);
    } catch (error) { if (epoch === privateEpoch.current) setError(errorText(error)); }
    finally { if (epoch === privateEpoch.current) setSigningOut(false); }
  }

  async function analyze(event: FormEvent) {
    event.preventDefault(); if (submitting) return; setError('');
    if (source === 'file' && (!file || file.size > 1024 * 1024 || !/\.(pdf|txt)$/i.test(file.name))) {
      setError('Choose a PDF or UTF-8 TXT file no larger than 1 MiB.'); return;
    }
    if (source === 'saved' && !savedDocument) { setError('Choose a saved source that is ready or waiting for processing.'); return; }
    const cleaned = requirements.map((item) => ({ skill: item.skill.trim(), weight: item.weight }));
    if (new Set(cleaned.map((item) => item.skill.toLowerCase())).size !== cleaned.length) {
      setError('Each skill must be unique. Combine duplicate skills before running the match.'); return;
    }
    const navigation = routeRevision.current;
    await perform(async (epoch) => {
      const body = new FormData(); body.set('job_title', jobTitle.trim()); body.set('requirements', JSON.stringify(cleaned));
      if (source === 'file' && file) body.set('resume', file);
      else if (source === 'saved' && savedDocument) { body.set('document_id', savedDocument.id); body.set('reprocess', String(reprocess)); }
      else body.set('resume_text', resume);
      const document = source === 'file' && file ? Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', await file.arrayBuffer()))) : source === 'saved' ? savedDocumentId : resume;
      const parser = source === 'file' ? file?.name.split('.').at(-1)?.toLowerCase() : null;
      const fingerprint = JSON.stringify({ title: jobTitle.trim(), requirements: cleaned, source, parser, document, reprocess: source === 'saved' && reprocess });
      if (epoch !== privateEpoch.current) return;
      if (submission.current?.fingerprint !== fingerprint) submission.current = { fingerprint, key: crypto.randomUUID() };
      const key = submission.current.key; setRetryPending(false);
      let job: Job;
      try { job = await api<Job>('jobs/', { method: 'POST', body, headers: { 'Idempotency-Key': key } }, session?.csrfToken); }
      catch (error) {
        if (epoch === privateEpoch.current && error instanceof ApiError && (error.status === 0 || error.status >= 500 || (error.status >= 200 && error.status < 300))) setRetryPending(true);
        throw error;
      }
      if (epoch !== privateEpoch.current) return;
      if (deletedJobIds.current.has(job.id) || (job.document && deletedDocumentIds.current.has(job.document.id))) {
        setError('The source for this comparison was deleted while admission was in progress. Choose another source.'); return;
      }
      workspaceRevision.current += 1;
      setJobs((previous) => [job, ...previous.filter((item) => item.id !== job.id)]);
      if (job.match) setMatches((previous) => [job.match!, ...previous.filter((item) => item.id !== job.match!.id)]);
      if (job.document) setDocuments((previous) => [job.document!, ...previous.filter((item) => item.id !== job.document!.id)]);
      activeState.current = activeJob(job) || activeState.current;
      setDeleteRequested(false); setPollError(''); if (job.status === 'uploading') setRetryPending(true);
      if (navigation === routeRevision.current && routeCurrent.current.kind === 'home') navigate(job.status === 'succeeded' && job.match ? resultPath(job.id) : jobPath(job.id));
      monitorWake.current?.();
    }, setSubmitting);
  }
  async function deleteSelection() {
    if ((!selectedJob && !selectedLegacy) || deletingSelection) return;
    const jobId = selectedJob?.id; const matchId = displayedMatch?.id;
    const navigation = routeRevision.current;
    await perform(async (epoch) => {
      await api(jobId ? `jobs/${jobId}/` : `matches/${matchId}/`, { method: 'DELETE' }, session?.csrfToken);
      if (epoch !== privateEpoch.current) return;
      workspaceRevision.current += 1;
      if (jobId) deletedJobIds.current.add(jobId);
      setJobs((previous) => previous.filter((job) => jobId ? job.id !== jobId : job.match?.id !== matchId));
      setMatches((previous) => previous.filter((match) => match.id !== matchId));
      hasMorePages.current = false; setNextOffset(null); setNotifications([]); setRouteJob((previous) => previous?.id === jobId || previous?.match?.id === matchId ? null : previous); setDeleteRequested(false);
      if (navigation === routeRevision.current) navigate('/');
      monitorWake.current?.();
    }, setDeletingSelection);
  }
  async function downloadOriginal(document: DocumentRecord) {
    const epoch = privateEpoch.current;
    setDownloadingDocumentId(document.id); setError('');
    try {
      const blob = await downloadDocument(document.id);
      if (epoch !== privateEpoch.current || deletedDocumentIds.current.has(document.id)) return;
      const url = URL.createObjectURL(blob); const link = window.document.createElement('a');
      link.href = url; link.download = document.filename; window.document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      if (epoch !== privateEpoch.current) return;
      setError(errorText(error)); if (error instanceof ApiError && error.status === 401) await loseSession();
    } finally { if (epoch === privateEpoch.current) setDownloadingDocumentId(null); }
  }
  async function deleteOriginal() {
    if (!documentToDelete || deletingDocumentId) return;
    const documentId = documentToDelete.id;
    await perform(async (epoch) => {
      await api(`documents/${documentId}/`, { method: 'DELETE' }, session?.csrfToken);
      if (epoch !== privateEpoch.current) return;
      workspaceRevision.current += 1;
      deletedDocumentIds.current.add(documentId);
      const removedJobs = latestJobs.current.filter((job) => job.document?.id === documentId).map((job) => job.id);
      if (latestRouteJob.current?.document?.id === documentId) removedJobs.push(latestRouteJob.current.id);
      removedJobs.forEach((id) => deletedJobIds.current.add(id));
      setDocuments((previous) => previous.filter((item) => item.id !== documentId));
      setJobs((previous) => previous.filter((job) => job.document?.id !== documentId));
      setMatches([]); hasMorePages.current = false; setNextOffset(null); setNotifications([]); setDeleteRequested(false); setDeleteDocumentId(null);
      setRouteJob((previous) => previous?.document?.id === documentId ? null : previous);
      const current = routeCurrent.current;
      if ((current.kind === 'job' || current.kind === 'result') && removedJobs.includes(current.id)) navigate('/');
      if (draftSource.current.source === 'saved' && draftSource.current.savedDocumentId === documentId) { setSavedDocumentId(''); setReprocess(false); setSource('paste'); }
      await loadWorkspace(); monitorWake.current?.();
    }, (pending) => setDeletingDocumentId(pending ? documentId : null));
  }
  async function markRead(notice: CompletionNotification) {
    if (notice.read_at || readingIds.includes(notice.id)) return;
    const epoch = privateEpoch.current; setReadingIds((previous) => [...previous, notice.id]); setNotificationError('');
    try {
      const updated = await api<CompletionNotification>(`notifications/${notice.id}/read/`, { method: 'POST' }, session?.csrfToken);
      if (epoch !== privateEpoch.current) return;
      workspaceRevision.current += 1;
      setNotifications((previous) => previous.map((item) => item.id === updated.id ? updated : item));
      setUnreadCount((previous) => Math.max(0, previous - 1)); monitorWake.current?.();
    } catch (error) {
      if (epoch !== privateEpoch.current) return;
      if (error instanceof ApiError && error.status === 401) await loseSession();
      else setNotificationError(errorText(error));
    } finally { if (epoch === privateEpoch.current) setReadingIds((previous) => previous.filter((id) => id !== notice.id)); }
  }
  async function loadMoreNotifications() {
    if (nextOffset === null || loadingNotifications) return;
    const epoch = privateEpoch.current; const revision = workspaceRevision.current;
    setLoadingNotifications(true); setNotificationError('');
    try {
      const page = await api<NotificationPage>(`notifications/?offset=${nextOffset}`);
      if (epoch !== privateEpoch.current || revision !== workspaceRevision.current) return;
      hasMorePages.current = true; setUnreadCount(page.unread_count); setNextOffset(page.next_offset);
      setNotifications((previous) => [...previous, ...page.notifications.filter((notice) => !previous.some((item) => item.id === notice.id))]);
    } catch (error) {
      if (epoch !== privateEpoch.current) return;
      if (error instanceof ApiError && error.status === 401) await loseSession(); else setNotificationError(errorText(error));
    } finally { if (epoch === privateEpoch.current) setLoadingNotifications(false); }
  }
  function noticeList(items: CompletionNotification[]) {
    return <ul className="notification-list">{items.map((notice) => <li key={notice.id} className={notice.read_at ? '' : 'unread'}>
      <div><a href={notice.status === 'succeeded' ? resultPath(notice.job_id) : jobPath(notice.job_id)} onClick={follow}>{notice.job_title}<span>{notice.status === 'succeeded' ? 'Report ready' : 'Processing stopped'}</span></a><p>{new Date(notice.created_at).toLocaleString()}{!notice.read_at && ' · Unread'}</p></div>
      {!notice.read_at && <button className="text-button" type="button" disabled={readingIds.includes(notice.id)} onClick={() => markRead(notice)}>{readingIds.includes(notice.id) ? 'Marking read…' : 'Mark as read'}</button>}
    </li>)}</ul>;
  }
  const heading = route.kind === 'notifications' ? 'Notifications' : route.kind === 'result' || route.kind === 'legacy' ? 'Evidence report' : selectedJob?.status === 'failed' ? 'Comparison stopped' : 'Comparison in progress';
  return <>
    <a className="skip-link" href="#workspace">Skip to workspace</a>
    <header className="topbar"><a className="brand" href="/" onClick={follow} aria-label="Resume Match home"><span className="brand-mark" aria-hidden="true">r<span>m</span></span><span>Resume Match<small>Evidence workspace</small></span></a>
      <div className="account">{session && <span className="provider"><i aria-hidden="true" />{providerLabel(session.provider)}</span>}{session?.authenticated && <><span className="username">{session.username}</span><button className="header-button" type="button" onClick={logout} disabled={signingOut}>Sign out</button></>}</div>
    </header>
    <main id="workspace">
      {(route.kind === 'home' || !session?.authenticated) && <div className="intro"><div><p className="eyebrow">Résumé intelligence / human review</p><h1>Make the evidence<br /><em>easy to see.</em></h1><p>Compare a résumé with the skills that matter for a role.<br className="desktop-break" /> Explicit weights. Source excerpts. A score you can inspect.</p></div><div className="intro-note"><span className="note-icon" aria-hidden="true">↗</span><p>A review aid, never a hiring recommendation. A person makes the decision.</p></div></div>}
      {error && <div className="error" role="alert"><strong>We couldn’t complete that.</strong><p>{error}</p>{!session && <button type="button" onClick={load} disabled={loading}>Retry connection</button>}</div>}
      {loading ? <div className="panel loading" role="status">Connecting to your workspace…</div> : !session?.authenticated ? <section className="panel login-panel" aria-labelledby="login-heading"><div><p className="eyebrow">Your private workspace</p><h2 id="login-heading">Sign in to review a résumé</h2><p>Originals and reports belong to your account. Sources are stored privately and scanned before use. They remain until their configured expiry or earlier owner deletion.</p><p className="help">Use the account provided for this workspace. There is no shared default password.</p></div><form onSubmit={login}><label htmlFor="username">Username</label><input id="username" autoComplete="username" required value={username} maxLength={150} onChange={(event) => setUsername(event.target.value)} /><label htmlFor="password">Password</label><input id="password" type="password" autoComplete="current-password" maxLength={1024} required value={password} onChange={(event) => setPassword(event.target.value)} /><button className="primary" disabled={signingIn || signingOut || !session} type="submit">{signingOut ? 'Signing out…' : signingIn ? 'Signing in…' : 'Sign in'}<span aria-hidden="true">→</span></button></form></section> : <>
        <nav className="workspace-nav" aria-label="Workspace"><a href="/" onClick={follow} aria-current={route.kind === 'home' ? 'page' : undefined}>New comparison</a><a href="/notifications" onClick={follow} aria-current={route.kind === 'notifications' ? 'page' : undefined}>Notifications <span>{unreadCount} unread</span></a></nav>
        {route.kind !== 'home' && <div className="route-intro"><h1 ref={routeHeading} tabIndex={-1}>{route.kind === 'not-found' ? 'Page unavailable' : heading}</h1>{route.kind === 'job' && activeJob(selectedJob ?? { status: 'queued' } as Job) && <p>You can keep working. A notification will be saved here when this comparison finishes, including if you close the browser and return later.</p>}</div>}
        {unreadCount > 0 && route.kind !== 'notifications' && <div className="completion-summary" role="status"><span>{unreadCount} {unreadCount === 1 ? 'comparison has an update' : 'comparisons have updates'}.</span> <a href="/notifications" onClick={follow}>View notifications</a></div>}
        {offline && <div className="monitor-note" role="status">You’re offline. Accepted comparisons continue on the server. Updates will resume when you reconnect.</div>}
        {pollError && <div className="error monitor-note" role="alert"><strong>Status updates paused.</strong><p>{pollError} Your job has not been marked failed. We’ll retry automatically with a bounded delay.</p><button type="button" className="text-button" onClick={() => monitorWake.current?.()}>Resume status updates</button></div>}
        <div className="workspace-grid"><div>
          <div hidden={route.kind !== 'home'}>
            {/* The draft stays mounted across routes, including the selected File. */}
            <form className="panel match-form" onSubmit={analyze} onChange={() => setRetryPending(false)} aria-labelledby="new-match-heading"><div className="section-heading"><div><p className="eyebrow">New comparison</p><h2 id="new-match-heading">Define the match</h2></div><button className="text-button" type="button" disabled={submitting} onClick={() => { setResume(sample); setSource('paste'); setJobTitle('Full stack engineer'); setRequirements(defaults.map((item) => ({ ...item }))); setFile(null); if (fileRef.current) fileRef.current.value = ''; }}>Use synthetic sample <span aria-hidden="true">↗</span></button></div>
          <fieldset disabled={submitting}><legend className="step-title"><span>01</span> The role</legend><label htmlFor="job-title">Role title</label><input id="job-title" required maxLength={120} value={jobTitle} onChange={(event) => setJobTitle(event.target.value)} />
          <div className="requirement-title"><span className="field-label">Required skills</span><span>Weight 1–10</span></div><p className="help">Higher weights give a skill more influence. Use specific, job-relevant skills.</p>
          {requirements.map((item, index) => <div className="requirement-row" key={index}><input aria-label={`Skill ${index + 1}`} placeholder="e.g. Django" required maxLength={80} value={item.skill} onChange={(event) => setRequirements((previous) => previous.map((value, i) => i === index ? { ...value, skill: event.target.value } : value))} /><input aria-label={`Weight for skill ${index + 1}`} type="number" min={1} max={10} step={1} required value={Number.isNaN(item.weight) ? '' : item.weight} onChange={(event) => setRequirements((previous) => previous.map((value, i) => i === index ? { ...value, weight: event.target.valueAsNumber } : value))} /><button className="remove-button" type="button" disabled={requirements.length === 1} aria-label={`Remove skill ${index + 1}`} onClick={() => setRequirements((previous) => previous.filter((_, i) => i !== index))}>×</button></div>)}
          <button className="text-button add-skill" type="button" disabled={requirements.length >= 20} onClick={() => setRequirements((previous) => [...previous, { skill: '', weight: 1 }])}>+ Add skill <span className="muted">{requirements.length}/20</span></button></fieldset>
          <fieldset disabled={submitting}><legend className="step-title"><span>02</span> The résumé</legend><div className="source-options"><label><input type="radio" name="source" checked={source === 'paste'} onChange={() => setSource('paste')} /> Paste text</label><label><input type="radio" name="source" checked={source === 'file'} onChange={() => setSource('file')} /> Upload document</label><label><input type="radio" name="source" checked={source === 'saved'} onChange={() => { setSource('saved'); setSavedDocumentId(savedDocumentId || usableDocuments[0]?.id || ''); }} /> Saved source</label></div>
          {source === 'paste' ? <><label className="sr-only" htmlFor="resume-text">Résumé text</label><textarea id="resume-text" required maxLength={30000} rows={8} placeholder="Paste the résumé here. Start with the synthetic sample to explore safely." value={resume} onChange={(event) => setResume(event.target.value)} /><div className="input-meta"><span>Only the selected source is submitted.</span><span>{resume.length.toLocaleString()}/30,000</span></div></> : source === 'file' ? <div className="file-area"><label htmlFor="resume-file">Choose a résumé document</label><input id="resume-file" ref={fileRef} type="file" accept=".pdf,.txt" required onChange={(event) => setFile(event.target.files?.[0] || null)} /><p className="help">PDF or UTF-8 TXT · max 1 MiB · up to 10 PDF pages. Scanned PDFs need text extraction first.</p></div> : <div className="saved-source">
            <label htmlFor="saved-source">Choose a saved source</label><select id="saved-source" required value={savedDocumentId} onChange={(event) => { setSavedDocumentId(event.target.value); setReprocess(false); }}><option value="">Select an original</option>{usableDocuments.map((document) => <option key={document.id} value={document.id}>{documentLabel(document)} · {documentStatuses[document.status]}</option>)}</select>
            {usableDocuments.length ? <><p className="help">Reuse an original without uploading it again. Safety checks run before processing.</p><label className="reprocess-option"><input type="checkbox" checked={reprocess} onChange={(event) => setReprocess(event.target.checked)} /> Re-extract the original instead of using saved text</label></> : <p className="help">Upload or paste a source first. Rejected and deleted originals cannot be reused.</p>}
          </div>}
          <p className="privacy-note">{providerDisclosure[session.provider]}</p></fieldset>
          {retryPending && <p className="retry-note" role="status">The server may already have accepted this comparison. Retry unchanged inputs to recover the same job without creating a duplicate.</p>}
          <p className="help">Originals, extracted text and associated reports expire after {session.document_retention_days} days from the original upload. Deleting a comparison keeps its saved source; deleting the document removes its related comparisons.</p>
          <button className="primary analyze" type="submit" disabled={submitting}>{submitting ? 'Submitting comparison…' : retryPending ? 'Retry same comparison' : 'Analyze evidence'}<span aria-hidden="true">→</span></button><p className="form-footnote">20 new comparisons per account per day. Status checks and delivery retries don’t use another comparison. Scores measure weighted evidence coverage, not candidate quality.</p>
        </form>
          </div>
          {(route.kind === 'job' || route.kind === 'result') && <div className="job-route">
            {routeError ? <section className="panel route-message" role="alert"><h2>Comparison unavailable</h2><p>{routeError}</p><button className="text-button" type="button" onClick={() => setRouteRefresh((previous) => previous + 1)}>Retry this page</button><a href="/" onClick={follow}>Start another comparison</a></section> : !selectedJob ? <section className="panel route-message" role="status">{routeLoading ? 'Loading this comparison…' : 'This comparison is not available yet.'}</section> : <>
              <section className={`panel job-panel ${selectedJob.status === 'failed' ? 'job-failed' : ''}`} aria-labelledby="job-heading">
                <div className="section-heading"><h2 id="job-heading">{selectedJob.job_title}</h2><span className={`tag status-${selectedJob.status}`}>{selectedJob.status}</span></div>
                <p className="job-message" role="status">{selectedJob.status === 'uploading' ? 'The original upload is incomplete. Return to your comparison draft and retry unchanged text or the same file. After refreshing, choose the original file or paste the text to submit again.' : selectedJob.status === 'queued' ? 'Accepted and waiting for a worker. You can leave this page and continue working.' : selectedJob.status === 'running' ? 'A worker is extracting and checking the résumé evidence.' : selectedJob.status === 'succeeded' ? 'The evidence report is ready for your review.' : jobMessages[selectedJob.error_code ?? ''] || 'Processing stopped without a report. Review the reference below when investigating.'}</p>
                {route.kind === 'result' && selectedJob.status !== 'succeeded' && <p className="help">There is no completed report yet. <a href={jobPath(selectedJob.id)} onClick={follow}>Open processing status</a>.</p>}
                <div className="route-actions"><a className="primary action-link" href="/" onClick={follow}>Continue with another comparison <span aria-hidden="true">→</span></a>{selectedJob.status === 'uploading' && <a href="/" onClick={follow}>Return to comparison draft</a>}</div>
                {selectedJob.status === 'failed' && <p className="help">The failed comparison remains in your history. Review the source or requirements, then submit from your draft when you are ready.</p>}
                <details className="processing-details"><summary>Source and processing reference</summary>
                  <p className="help">Processing attempts: {selectedJob.attempts}{selectedJob.error_code && <> · Error code: <code>{selectedJob.error_code}</code></>}</p>
                  {selectedJob.document ? <p className="help">Source: {documentLabel(selectedJob.document)} · {documentStatuses[selectedJob.document.status]}</p> : <p className="help">Original unavailable for this earlier comparison.</p>}
                  <dl className="trace-ids"><div><dt>Job ID</dt><dd>{selectedJob.id}</dd></div><div><dt>Request ID</dt><dd>{selectedJob.request_id}</dd></div></dl>
                  {session.log_viewer_url && <p className="help">Search either ID in the <a href={session.log_viewer_url} target="_blank" rel="noopener noreferrer">OpenObserve log viewer (opens a new tab)</a> to follow this comparison across services.</p>}
                </details>
                {!displayedMatch && <button className="text-button danger" type="button" disabled={deletingSelection} onClick={() => setDeleteRequested(true)}>Delete this comparison</button>}
              </section>
              {route.kind === 'result' && displayedMatch && <MatchResult match={displayedMatch} busy={deletingSelection} onDelete={() => setDeleteRequested(true)} />}
            </>}
          </div>}
          {route.kind === 'legacy' && (displayedMatch ? <MatchResult match={displayedMatch} busy={deletingSelection} onDelete={() => setDeleteRequested(true)} /> : <section className="panel route-message"><h2>Report unavailable</h2><p>This earlier report is not in your available recent history. It may have expired or been deleted.</p><a href="/" onClick={follow}>Return to your workspace</a></section>)}
          {route.kind === 'notifications' && <section className="panel inbox" aria-labelledby="inbox-heading"><div className="section-heading"><h2 id="inbox-heading">Your comparison updates</h2><span>{unreadCount} unread</span></div><p>Reports and processing failures are saved here. Open an update when you’re ready; it won’t interrupt another comparison.</p><p className="inbox-refresh-note">Returning to this tab refreshes the list. Load older updates again after returning or deleting a source.</p>{notificationError && <p className="error" role="alert">{notificationError}</p>}{notifications.length ? noticeList(notifications) : <div className="inbox-empty"><h3>No updates yet</h3><p>Accepted comparisons continue in the background. Their completion or failure will appear here.</p><a href="/" onClick={follow}>Start a comparison</a></div>}{nextOffset !== null && <button className="text-button" type="button" disabled={loadingNotifications} onClick={loadMoreNotifications}>{loadingNotifications ? 'Loading older updates…' : 'Load older updates'}</button>}</section>}
          {route.kind === 'not-found' && <section className="panel route-message"><h2>We couldn’t find that page</h2><p>Use your workspace or a comparison link from your notifications.</p><a href="/" onClick={follow}>Open your workspace</a></section>}
          {deleteRequested && (selectedJob || selectedLegacy) && <div className="delete-confirm" role="alert"><p>Delete this comparison and its evidence? Its saved document remains available. This cannot be undone.</p><button className="danger-button" type="button" disabled={deletingSelection} onClick={deleteSelection}>Delete comparison</button><button className="text-button" type="button" disabled={deletingSelection} onClick={() => setDeleteRequested(false)}>Keep comparison</button></div>}
        </div>
        <aside><section className="document-library" aria-labelledby="documents-heading"><h2 id="documents-heading">Saved originals <span>{documents.length}</span></h2><p className="help">Private sources for your next comparison.</p>
          {documents.length ? <ul className="document-list">{documents.map((document) => <li key={document.id}>
            <h3>{documentLabel(document)}</h3><p className="help">{documentStatuses[document.status]}<br />Expires {new Date(document.expires_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}</p>
            <div className="document-actions">{reusableDocument(document) && <button className="text-button" type="button" disabled={deletingDocumentId === document.id} onClick={() => { setSource('saved'); setSavedDocumentId(document.id); setReprocess(false); setRetryPending(false); navigate('/'); }}>Use source</button>}{document.status === 'ready' && <button className="text-button" type="button" disabled={downloadingDocumentId === document.id} onClick={() => downloadOriginal(document)}>{downloadingDocumentId === document.id ? 'Downloading…' : 'Download original'}</button>}{document.status !== 'deleting' && <button className="text-button danger" type="button" disabled={deletingDocumentId === document.id} onClick={() => setDeleteDocumentId(document.id)}>Delete original</button>}</div>
          </li>)}</ul> : <p className="help">Your uploaded files and pasted snapshots will appear here.</p>}
          {documentToDelete && <div className="delete-confirm" role="alert"><p>Delete {documentLabel(documentToDelete)} and all its comparisons and reports? Access ends immediately; stored bytes are removed in the background. This cannot be undone.</p><button className="danger-button" type="button" disabled={!!deletingDocumentId} onClick={deleteOriginal}>Delete original and reports</button><button className="text-button" type="button" disabled={!!deletingDocumentId} onClick={() => setDeleteDocumentId(null)}>Keep original</button></div>}
        </section><section aria-labelledby="history-heading"><div className="history-heading"><p className="eyebrow">Your workspace</p><h2 id="history-heading">Recent comparisons <span>{jobs.length + legacyMatches.length}</span></h2></div>{jobs.length || legacyMatches.length ? <div className="history-list">
          {jobs.map((job) => <a key={job.id} className={`history-item ${selectedJob?.id === job.id ? 'selected' : ''}`} aria-current={selectedJob?.id === job.id ? 'page' : undefined} href={job.status === 'succeeded' && job.match ? resultPath(job.id) : jobPath(job.id)} onClick={follow}><span className="history-title">{job.job_title}</span><span className="history-meta">{new Date(job.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}<span>{job.match ? `${job.match.score}%` : job.status}</span></span></a>)}
          {legacyMatches.map((match) => <a key={match.id} className={`history-item ${selectedLegacy?.id === match.id ? 'selected' : ''}`} aria-current={selectedLegacy?.id === match.id ? 'page' : undefined} href={reportPath(match.id)} onClick={follow}><span className="history-title">{match.job_title}</span><span className="history-meta">{new Date(match.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}<span>{match.score}%</span></span></a>)}
        </div> : <div className="empty-history"><span aria-hidden="true">≡</span><h3>A clear paper trail.</h3><p>Your comparisons will appear here. Start with the synthetic sample to see how the evidence report works.</p></div>}<div className="method-note"><h3>How the score works</h3><p>Matched skill weights ÷ all skill weights × 100.</p><p>Evidence is checked against the source text. An absent excerpt contributes zero weight. Skill wording and extraction errors can affect coverage.</p><span>Review excerpts, then verify with a person.</span></div></section></aside>
        </div>
      </>}
      <footer className="site-footer"><span>Resume Match <span aria-hidden="true">/</span> Evidence workspace</span><span>Source excerpts · Weighted coverage · Human review</span></footer>
    </main>
  </>;
}
