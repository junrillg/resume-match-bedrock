import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import App, { MatchResult } from './App';
import type { CompletionNotification, DocumentRecord, Job, Match, Session } from './api';

const report: Match = {
  id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', job_title: 'Full stack engineer', score: 60, provider: 'demo',
  created_at: '2026-01-01T12:00:00Z', request_id: 'request-123',
  requirements: [
    { skill: 'Python', weight: 3, matched: true, evidence: 'Built Python services.' },
    { skill: 'PostgreSQL', weight: 2, matched: false, evidence: null },
  ],
};
const queued: Job = { id: '11111111-1111-4111-8111-111111111111', job_title: report.job_title, status: 'queued', attempts: 0, created_at: report.created_at, request_id: report.request_id, error_code: null, match: null, document: null };
const signedIn: Session = { authenticated: true, username: 'reviewer', csrfToken: 'rotated-token', provider: 'demo', document_retention_days: 90 };
const anonymous: Session = { authenticated: false, csrfToken: 'anonymous-token', provider: 'demo', document_retention_days: 90 };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

function server(session = signedIn, jobs: Job[] = []) {
  const state = {
    session, jobs, matches: [] as Match[], documents: [] as DocumentRecord[], notifications: [] as CompletionNotification[],
    deletedDocuments: new Set<string>(),
    deleteDocument: async (id: string): Promise<Response> => { const related = state.jobs.filter((job) => job.document?.id === id).map((job) => job.id); state.deletedDocuments.add(id); state.documents = state.documents.filter((item) => item.id !== id); state.jobs = state.jobs.filter((job) => !related.includes(job.id)); state.matches = []; state.notifications = state.notifications.filter((notice) => !related.includes(notice.job_id)); return json({ deleted: true, status: 'deleting' }, 202); },
    deleteJob: async (id: string): Promise<Response> => { state.jobs = state.jobs.filter((job) => job.id !== id); state.matches = []; state.notifications = state.notifications.filter((notice) => notice.job_id !== id); return json({ deleted: true }); },
    readDetail: async (id: string): Promise<Response> => { const job = state.jobs.find((item) => item.id === id); return job ? json(job) : json({ error: 'Not found.' }, 404); },
    readNotifications: async (offset: number): Promise<Response> => json({ notifications: state.notifications.slice(offset, offset + 100), unread_count: state.notifications.filter((item) => !item.read_at).length, next_offset: state.notifications.length > offset + 100 ? offset + 100 : null }),
    post: async (_options: RequestInit) => json(queued, 202),
    readJobs: async (): Promise<Response> => json({ jobs: state.jobs }),
    readDocuments: async (): Promise<Response> => json({ documents: state.documents }),
    download: async (): Promise<Response> => new Response('synthetic original', { headers: { 'Content-Type': 'application/octet-stream' } }),
  };
  const fetcher = vi.fn(async (url: string, options: RequestInit) => {
    if (url === '/api/session/') return json(state.session);
    if (url === '/api/login/') { state.session = signedIn; return json(signedIn); }
    if (url === '/api/logout/') { state.session = anonymous; return json(anonymous); }
    if (url === '/api/jobs/' && options.method === 'POST') { const response = await state.post(options); if (response.ok) { const job = await response.clone().json() as Job; if (!job.document || !state.deletedDocuments.has(job.document.id)) state.jobs = [job, ...state.jobs.filter((item) => item.id !== job.id)]; } return response; }
    if (url.startsWith('/api/notifications/?')) return state.readNotifications(Number(url.split('offset=')[1]));
    if (url.startsWith('/api/notifications/') && options.method === 'POST') { const id = url.split('/')[3]; const notice = state.notifications.find((item) => item.id === id); if (!notice) return json({ error: 'Not found.' }, 404); notice.read_at = '2026-10-19T00:00:00Z'; return json(notice); }
    if (/^\/api\/jobs\/[^/]+\/$/.test(url) && !options.method) return state.readDetail(url.split('/')[3]);
    if (url === '/api/jobs/') return state.readJobs();
    if (url === '/api/documents/') return state.readDocuments();
    if (url.endsWith('/download/')) return state.download();
    if (url.startsWith('/api/documents/') && options.method === 'DELETE') return state.deleteDocument(url.split('/')[3]);
    if (url === '/api/matches/') return json({ matches: state.matches });
    if (url.startsWith('/api/jobs/') && options.method === 'DELETE') return state.deleteJob(url.split('/')[3]);
    if (options.method === 'DELETE') { state.jobs = []; state.matches = []; return json({ deleted: true }); }
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal('fetch', fetcher);
  return { state, fetcher };
}
async function mount() { await act(async () => { render(<App />); }); }
async function click(name: string | RegExp) { await act(async () => { fireEvent.click(screen.queryByRole('button', { name }) ?? screen.getByRole('link', { name })); }); }
async function tick(milliseconds = 1000) { await act(async () => { await vi.advanceTimersByTimeAsync(milliseconds); }); }
async function login() {
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'reviewer' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'synthetic-only' } });
  await click('Sign in');
}
beforeEach(() => {
  window.history.replaceState(null, '', '/');
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible'); vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true);
  vi.useFakeTimers(); vi.stubGlobal('requestAnimationFrame', () => 0);
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it('shows server-owned coverage, excerpts, and honest document gaps', () => {
  render(<MatchResult match={report} busy={false} onDelete={() => {}} />);
  expect(screen.getByRole('meter').getAttribute('aria-valuenow')).toBe('60');
  expect(screen.getByText('Built Python services.')).toBeTruthy();
  expect(screen.getByText(/not proof of a missing ability/)).toBeTruthy();
  expect(screen.getByText('Demo · local deterministic')).toBeTruthy();
});

it('uses rotated CSRF, polls queued/running to success, stops, and confirms deletion', async () => {
  const { state, fetcher } = server(anonymous);
  state.post = async () => { state.jobs = [queued]; return json(queued, 202); };
  await mount(); await login(); await click(/Use synthetic sample/); await click(/Analyze evidence/);
  expect(screen.getByText(/Accepted and waiting for a worker/)).toBeTruthy();
  const post = fetcher.mock.calls.find(([url, options]) => url === '/api/jobs/' && options.method === 'POST')![1];
  expect(new Headers(post.headers).get('X-CSRFToken')).toBe('rotated-token');
  expect(new Headers(post.headers).get('Idempotency-Key')).toMatch(/^[a-f0-9-]{36}$/);
  expect((post.body as FormData).get('resume_text')).toContain('SYNTHETIC SAMPLE');
  expect((post.body as FormData).has('resume')).toBe(false);
  state.jobs = [{ ...queued, status: 'running', attempts: 1 }]; await tick();
  expect(screen.getByText(/A worker is extracting/)).toBeTruthy();
  state.jobs = [{ ...queued, status: 'succeeded', attempts: 1, match: report }]; await tick();
  expect(screen.getByRole('meter')).toBeTruthy(); expect(screen.getByText('11111111-1111-4111-8111-111111111111')).toBeTruthy();
  const count = fetcher.mock.calls.length; await tick(5000); expect(fetcher.mock.calls).toHaveLength(count);
  await click('Delete this report'); expect(fetcher.mock.calls).toHaveLength(count);
  await click('Delete comparison'); expect(screen.queryByRole('meter')).toBeNull();
  expect(fetcher.mock.calls.some(([url, options]) => url === '/api/jobs/11111111-1111-4111-8111-111111111111/' && options.method === 'DELETE')).toBe(true);
});

it('reuses the key after ambiguous transport failure and rotates for changed inputs', async () => {
  const { state, fetcher } = server();
  state.post = async () => { throw new TypeError('network lost'); };
  await mount(); await click(/Use synthetic sample/); await click(/Analyze evidence/); await tick(5000);
  expect(fetcher.mock.calls.filter(([, options]) => options.method === 'POST')).toHaveLength(1);
  await click('Retry same comparison');
  fireEvent.change(screen.getByLabelText('Role title'), { target: { value: 'Another role' } });
  state.post = async () => json({ ...queued, job_title: 'Another role', status: 'failed', error_code: 'invalid_evidence' }, 202);
  await click(/Analyze evidence/);
  const posts = fetcher.mock.calls.filter(([, options]) => options.method === 'POST').map(([, options]) => options);
  const keys = posts.map((options) => new Headers(options.headers).get('Idempotency-Key'));
  expect(keys[0]).toBe(keys[1]); expect(keys[2]).not.toBe(keys[0]);
  expect((posts[0].body as FormData).get('resume_text')).toBe((posts[1].body as FormData).get('resume_text'));
  expect(screen.getByText(/The extracted evidence could not be verified/)).toBeTruthy();
  expect(screen.queryByRole('meter')).toBeNull();
});

it('restores pending work and backs off/resumes monitoring without falsely failing the job', async () => {
  const { state, fetcher } = server(signedIn, [queued]);
  await mount(); await click(/Full stack engineer.*queued/); expect(screen.getByText('11111111-1111-4111-8111-111111111111')).toBeTruthy();
  state.readJobs = async () => { throw new TypeError('offline'); }; await tick();
  expect(screen.getByText('Status updates paused.')).toBeTruthy();
  expect(screen.getByText(/Your job has not been marked failed/)).toBeTruthy();
  const count = fetcher.mock.calls.length; await tick(5000); expect(fetcher.mock.calls.length).toBeGreaterThan(count);
  state.readJobs = async () => json({ jobs: [{ ...queued, status: 'succeeded', match: report }] });
  await click('Resume status updates'); await tick(); expect(screen.getByRole('meter')).toBeTruthy();
});

it('ties upload retries to document contents instead of filename and submits only the file', async () => {
  const { state, fetcher } = server();
  state.post = async () => { throw new TypeError('offline'); };
  vi.stubGlobal('crypto', {
    randomUUID: crypto.randomUUID.bind(crypto),
    subtle: { digest: async (_algorithm: string, contents: ArrayBuffer) => contents },
  });
  const upload = (content: string, filename = 'same-name.txt') => {
    const file = new File([content], filename, { type: 'text/plain' });
    Object.defineProperty(file, 'arrayBuffer', { value: async () => new TextEncoder().encode(content).buffer });
    fireEvent.change(screen.getByLabelText('Choose a résumé document'), { target: { files: [file] } });
  };
  await mount(); fireEvent.click(screen.getByLabelText('Upload document'));
  const submit = async () => { await act(async () => { fireEvent.submit(screen.getByLabelText('Role title').closest('form')!); }); };
  upload('Python'); await submit();
  upload('Python'); await submit();
  upload('Django'); await submit();
  upload('Django', 'same-name.pdf'); await submit();
  const posts = fetcher.mock.calls.filter(([, options]) => options.method === 'POST').map(([, options]) => options);
  const keys = posts.map((options) => new Headers(options.headers).get('Idempotency-Key'));
  expect(keys[0]).toBe(keys[1]); expect(keys[2]).not.toBe(keys[0]); expect(keys[3]).not.toBe(keys[2]);
  expect((posts[0].body as FormData).get('resume')).toBeInstanceOf(File);
  expect((posts[0].body as FormData).has('resume_text')).toBe(false);
});

it('aborts a hung status request after ten seconds and pauses updates', async () => {
  const { state, fetcher } = server(signedIn, [queued]);
  await mount(); await click(/Full stack engineer.*queued/);
  state.readJobs = () => new Promise((_resolve, reject) => {
    const signal = fetcher.mock.calls.filter(([url]) => url === '/api/jobs/').at(-1)![1].signal!;
    signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
  });
  await tick(); await tick(10000);
  expect(screen.getByText('Status updates paused.')).toBeTruthy();
  expect(screen.getByText(/Accepted and waiting for a worker/)).toBeTruthy();
});

it('does not restore a deleted pending job from an older in-flight poll', async () => {
  const other = { ...queued, id: '22222222-2222-4222-8222-222222222222', job_title: 'Another pending role' };
  const { state } = server(signedIn, [queued, other]);
  await mount(); await click(/Full stack engineer.*queued/); let complete!: (response: Response) => void;
  state.readJobs = () => new Promise((resolve) => { complete = resolve; }); await tick();
  await click('Delete this comparison'); await click('Delete comparison');
  await act(async () => { complete(json({ jobs: [queued, other] })); });
  expect(screen.queryByText('11111111-1111-4111-8111-111111111111')).toBeNull();
  expect(screen.getByRole('link', { name: /Another pending role/ })).toBeTruthy();
  expect(screen.queryByRole('link', { name: /Full stack engineer.*queued/ })).toBeNull();
});

it('clears private drafts/keys on auth loss and ignores an old submission response', async () => {
  const { state, fetcher } = server(signedIn, [queued]);
  let finishPost!: (response: Response) => void;
  state.post = () => new Promise((resolve) => { finishPost = resolve; });
  await mount(); await click(/Use synthetic sample/); await click(/Analyze evidence/);
  state.session = anonymous; state.readJobs = async () => json({ error: 'Sign in again.' }, 401); await tick();
  expect(screen.getByRole('heading', { name: 'Sign in to review a résumé' })).toBeTruthy();
  await act(async () => { finishPost(json({ ...queued, id: 'private-old-job' }, 202)); });
  state.jobs = []; state.readJobs = async () => json({ jobs: [] }); await login();
  expect((screen.getByLabelText('Résumé text') as HTMLTextAreaElement).value).toBe('');
  expect(screen.queryByText('private-old-job')).toBeNull();
  state.post = async () => json({ ...queued, status: 'failed', error_code: 'retry_exhausted' }, 202);
  await click(/Use synthetic sample/); await click(/Analyze evidence/);
  const posts = fetcher.mock.calls.filter(([, options]) => options.method === 'POST' && options.body instanceof FormData);
  expect(new Headers(posts[0][1].headers).get('Idempotency-Key')).not.toBe(new Headers(posts[1][1].headers).get('Idempotency-Key'));
});

it('keeps legacy reports accessible and deletes them through the report endpoint', async () => {
  const { state, fetcher } = server(); state.matches = [report];
  await mount(); await click(/Full stack engineer.*60%/); expect(screen.getByRole('meter')).toBeTruthy();
  await click('Delete this report'); await click('Delete comparison');
  expect(fetcher.mock.calls.some(([url, options]) => url === '/api/matches/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/' && options.method === 'DELETE')).toBe(true);
});

it('cancels polling on unmount and ignores a response that finishes afterward', async () => {
  const { state, fetcher } = server(signedIn, [queued]);
  await mount(); let finish!: (response: Response) => void;
  state.readJobs = () => new Promise((resolve) => { finish = resolve; }); await tick();
  const pending = fetcher.mock.calls.filter(([url]) => url === '/api/jobs/').at(-1)![1]; cleanup(); expect(pending.signal?.aborted).toBe(true);
  await act(async () => { finish(json({ jobs: [queued] })); });
  const count = fetcher.mock.calls.length; await tick(5000); expect(fetcher.mock.calls).toHaveLength(count);
});

it('makes a hung admission request retryable with the same idempotency key', async () => {
  const { state, fetcher } = server();
  state.post = (options) => new Promise((_resolve, reject) => {
    options.signal!.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
  });
  await mount(); await click(/Use synthetic sample/); await click(/Analyze evidence/);
  await tick(10000);
  expect(screen.getByText(/The request timed out or was cancelled/)).toBeTruthy();
  state.post = async () => json(queued, 202);
  await click('Retry same comparison');
  const posts = fetcher.mock.calls.filter(([, options]) => options.method === 'POST');
  expect(posts).toHaveLength(2);
  expect(new Headers(posts[0][1].headers).get('Idempotency-Key')).toBe(new Headers(posts[1][1].headers).get('Idempotency-Key'));
  expect(screen.getByText(/Accepted and waiting for a worker/)).toBeTruthy();
});

it('preserves an ambiguous submission key when an unrelated report is deleted', async () => {
  const { state, fetcher } = server(); state.matches = [report];
  state.post = async () => { throw new TypeError('response lost'); };
  await mount(); await click(/Use synthetic sample/); await click(/Analyze evidence/);
  await click(/Full stack engineer.*60%/); await click('Delete this report'); await click('Delete comparison');
  state.post = async () => json({ ...queued, status: 'failed', error_code: 'provider_rejected' }, 202);
  await click('Retry same comparison');
  const posts = fetcher.mock.calls.filter(([, options]) => options.method === 'POST');
  expect(posts).toHaveLength(2);
  expect(new Headers(posts[0][1].headers).get('Idempotency-Key')).toBe(new Headers(posts[1][1].headers).get('Idempotency-Key'));
});


it.each([
  ['demo', 'Demo · local deterministic', 'The worker extracts literal skill mentions'],
  ['bedrock-local', 'Local contract provider', 'a separate local provider service'],
  ['bedrock', 'AWS Bedrock', 'AWS Bedrock in the configured region'],
] as const)('names the %s provider and discloses its actual processing boundary', async (provider, label, disclosure) => {
  server({ ...signedIn, provider });
  await mount();
  expect(screen.getByText(label)).toBeTruthy();
  expect(screen.getByText(new RegExp(disclosure))).toBeTruthy();
});

it('shows the configured log viewer and omits the link when unavailable', async () => {
  const { state } = server({ ...signedIn, log_viewer_url: 'http://127.0.0.1:5080' }, [queued]);
  await mount(); await click(/Full stack engineer.*queued/); fireEvent.click(screen.getByText('Source and processing reference'));
  expect(screen.getByRole('link', { name: /OpenObserve log viewer/ }).getAttribute('href')).toBe('http://127.0.0.1:5080');
  cleanup();
  state.session = signedIn;
  await mount();
  expect(screen.queryByRole('link', { name: /OpenObserve log viewer/ })).toBeNull();
});

const stored: DocumentRecord = {
  id: 'doc-1', filename: 'saved-original.txt', content_type: 'text/plain', size_bytes: 24,
  status: 'ready', created_at: '2026-10-18T00:00:00Z', expires_at: '2027-01-16T00:00:00Z',
};

it('submits a saved source without new bytes and rotates the key for explicit reprocessing', async () => {
  const { state, fetcher } = server(); state.documents = [stored];
  state.post = async () => json({ ...queued, document: stored }, 202);
  await mount(); await click('Use source'); await click('Analyze evidence');
  const first = fetcher.mock.calls.find(([url, options]) => url === '/api/jobs/' && options.method === 'POST')![1];
  expect((first.body as FormData).get('document_id')).toBe('doc-1');
  expect((first.body as FormData).get('reprocess')).toBe('false');
  expect((first.body as FormData).has('resume')).toBe(false);
  expect((first.body as FormData).has('resume_text')).toBe(false);
  await click('New comparison');
  fireEvent.click(screen.getByLabelText('Re-extract the original instead of using saved text'));
  await click('Analyze evidence');
  const second = fetcher.mock.calls.filter(([url, options]) => url === '/api/jobs/' && options.method === 'POST')[1][1];
  expect((second.body as FormData).get('reprocess')).toBe('true');
  expect(new Headers(second.headers).get('Idempotency-Key')).not.toBe(new Headers(first.headers).get('Idempotency-Key'));
});

it('preserves exact pasted whitespace in the body and idempotency identity', async () => {
  const { state, fetcher } = server(); state.post = async () => { throw new TypeError('offline'); };
  await mount();
  fireEvent.change(screen.getByLabelText('Résumé text'), { target: { value: '  Python APIs.\n' } });
  await click('Analyze evidence');
  fireEvent.change(screen.getByLabelText('Résumé text'), { target: { value: 'Python APIs.' } });
  await click('Analyze evidence');
  const posts = fetcher.mock.calls.filter(([url, options]) => url === '/api/jobs/' && options.method === 'POST').map(([, options]) => options);
  expect((posts[0].body as FormData).get('resume_text')).toBe('  Python APIs.\n');
  expect(new Headers(posts[0].headers).get('Idempotency-Key')).not.toBe(new Headers(posts[1].headers).get('Idempotency-Key'));
});

it('makes pending originals reusable, hides their downloads and shows configured retention', async () => {
  const { state } = server({ ...signedIn, document_retention_days: 45 });
  state.documents = [{ ...stored, status: 'pending' }];
  await mount();
  expect(screen.getByText(/expire after 45 days/)).toBeTruthy();
  expect(screen.getByText(/Waiting for safety checks/)).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Download original' })).toBeNull();
  await click('Use source');
  expect((screen.getByLabelText('Choose a saved source') as HTMLSelectElement).value).toBe('doc-1');
  expect(screen.getByText(/Expires Jan 16, 2027/)).toBeTruthy();
});

it('confirms source deletion separately and rejects a stale poll restoring its reports or original', async () => {
  const linked = { ...queued, document: stored };
  const { state, fetcher } = server(signedIn, [linked]); state.documents = [stored]; state.matches = [report];
  await mount();
  let complete!: (response: Response) => void;
  state.readJobs = () => new Promise((resolve) => { complete = resolve; }); await tick();
  state.readJobs = async () => json({ jobs: state.jobs });
  const before = fetcher.mock.calls.filter(([, options]) => options.method === 'DELETE').length;
  await click('Delete original');
  expect(screen.getByText(/and all its comparisons and reports/)).toBeTruthy();
  expect(fetcher.mock.calls.filter(([, options]) => options.method === 'DELETE')).toHaveLength(before);
  await click('Delete original and reports');
  await act(async () => { complete(json({ jobs: [linked] })); });
  expect(screen.queryByText('saved-original.txt')).toBeNull();
  expect(screen.queryByText('11111111-1111-4111-8111-111111111111')).toBeNull();
  expect(screen.queryByRole('meter')).toBeNull();
  expect(fetcher.mock.calls.some(([url, options]) => url === '/api/documents/doc-1/' && options.method === 'DELETE')).toBe(true);
});

it('does not release a late download after sign out', async () => {
  const { state } = server(); state.documents = [stored];
  let complete!: (response: Response) => void;
  state.download = () => new Promise((resolve) => { complete = resolve; });
  const create = vi.fn();
  vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: vi.fn() });
  await mount(); await click('Download original'); await click('Sign out');
  await act(async () => { complete(new Response('synthetic', { headers: { 'Content-Type': 'application/octet-stream' } })); });
  expect(create).not.toHaveBeenCalled();
  expect(screen.getByRole('heading', { name: 'Sign in to review a résumé' })).toBeTruthy();
  await login();
  expect(screen.queryByText(/Original upload is incomplete/)).toBeNull();
});

it('handles download safety failures inline and clears private sources on a download 401', async () => {
  const { state } = server(); state.documents = [stored];
  state.download = async () => json({ error: 'Safety checks are unavailable.', request_id: 'download-trace' }, 503);
  await mount(); await click('Download original');
  expect(screen.getByText(/Safety checks are unavailable.*download-trace/)).toBeTruthy();
  state.session = anonymous; state.download = async () => json({ error: 'Sign in again.' }, 401);
  await click('Download original');
  expect(screen.getByRole('heading', { name: 'Sign in to review a résumé' })).toBeTruthy();
  expect(screen.queryByText('saved-original.txt')).toBeNull();
});

it('restores uploading receipts as active work and explains source replay instead of claiming completion', async () => {
  const { state } = server(signedIn, [{ ...queued, status: 'uploading', document: { ...stored, status: 'uploading' } }]);
  state.documents = [{ ...stored, status: 'uploading' }];
  await mount(); await click(/Full stack engineer.*uploading/);
  expect(screen.getByText(/The original upload is incomplete/)).toBeTruthy();
  state.jobs = [{ ...queued, status: 'succeeded', document: stored, match: report }]; state.documents = [stored];
  await tick();
  expect(screen.getByRole('button', { name: 'Download original' })).toBeTruthy();
  expect(screen.getByRole('meter')).toBeTruthy();
});

it('explains unavailable originals for legacy jobs and renders long source filenames as text', async () => {
  const { state } = server(signedIn, [{ ...queued, status: 'succeeded', match: report }]);
  const filename = '長いrésumé-'.repeat(20) + '.pdf'; state.documents = [{ ...stored, filename }];
  await mount();
  await click(/Full stack engineer.*60%/);
  expect(screen.getByText('Original unavailable for this earlier comparison.')).toBeTruthy();
  expect(screen.getByRole('heading', { name: filename })).toBeTruthy();
});

const completedNotice: CompletionNotification = {
  id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', job_id: queued.id, job_title: queued.job_title,
  status: 'succeeded', created_at: '2026-10-19T00:00:00Z', read_at: null, href: `/results/${queued.id}`,
};
async function openInbox() { await click(/^Notifications \d+ unread$/); }
async function popTo(path: string) {
  await act(async () => { window.history.pushState(null, '', path); window.dispatchEvent(new PopStateEvent('popstate')); });
}

it('leaves accepted work to complete off-route without interrupting another draft, then opens its notification', async () => {
  const { state } = server();
  await mount(); await click(/Use synthetic sample/); await click('Analyze evidence');
  expect(window.location.pathname).toBe(`/jobs/${queued.id}`);
  expect((screen.getByRole('button', { name: 'Sign out' }) as HTMLButtonElement).disabled).toBe(false);
  await click('New comparison');
  fireEvent.change(screen.getByLabelText('Role title'), { target: { value: 'Draft for another role' } });
  state.jobs = [{ ...queued, status: 'succeeded', match: report }]; state.notifications = [completedNotice];
  await tick();
  expect(window.location.pathname).toBe('/');
  expect((screen.getByLabelText('Role title') as HTMLInputElement).value).toBe('Draft for another role');
  expect(screen.queryByRole('meter')).toBeNull();
  expect(screen.getByText('1 comparison has an update.')).toBeTruthy();
  await openInbox(); await click(/Full stack engineerReport ready/);
  expect(window.location.pathname).toBe(`/results/${queued.id}`);
  expect(screen.getByRole('meter')).toBeTruthy();
});

it('advances only the currently viewed processing job and supports real Back navigation', async () => {
  const { state } = server(signedIn, [queued]);
  await mount(); await click(/Full stack engineer.*queued/);
  state.jobs = [{ ...queued, status: 'succeeded', match: report }]; await tick();
  expect(window.location.pathname).toBe(`/results/${queued.id}`);
  await click('New comparison');
  await act(async () => { window.history.back(); await vi.advanceTimersByTimeAsync(1); });
  expect(window.location.pathname).toBe(`/results/${queued.id}`);
  expect(screen.getByRole('meter')).toBeTruthy();
});

it('keeps navigation and signout available during deferred admission and never redirects a user who left', async () => {
  const { state } = server(); let finish!: (response: Response) => void;
  state.post = () => new Promise((resolve) => { finish = resolve; });
  await mount(); await click(/Use synthetic sample/); await click('Analyze evidence');
  expect((screen.getByRole('button', { name: 'Sign out' }) as HTMLButtonElement).disabled).toBe(false);
  await openInbox();
  await act(async () => { finish(json(queued, 202)); });
  expect(window.location.pathname).toBe('/notifications');
  expect(screen.queryByRole('heading', { name: 'Comparison in progress' })).toBeNull();
  expect(screen.getByRole('link', { name: /Full stack engineer.*queued/ })).toBeTruthy();
  await click('New comparison');
  expect((screen.getByLabelText('Résumé text') as HTMLTextAreaElement).value).toContain('SYNTHETIC SAMPLE');
});

it('drops a late accepted job after explicit signout', async () => {
  const { state } = server(); let finish!: (response: Response) => void;
  state.post = () => new Promise((resolve) => { finish = resolve; });
  await mount(); await click(/Use synthetic sample/); await click('Analyze evidence'); await click('Sign out');
  await act(async () => { finish(json(queued, 202)); });
  expect(screen.getByRole('heading', { name: 'Sign in to review a résumé' })).toBeTruthy();
  expect(screen.queryByText(queued.id)).toBeNull(); expect(window.location.pathname).toBe('/');
});

it('loads a direct processing or result URL through detail authorization even outside recent history', async () => {
  const { state, fetcher } = server();
  const deep = { ...queued, id: 'abcdef12-abcd-4abc-8def-abcdef123456' };
  window.history.replaceState(null, '', `/JOBS/${deep.id.toUpperCase()}`);
  state.readDetail = async () => json({ ...deep, status: 'succeeded', match: report });
  await mount();
  expect(window.location.pathname).toBe(`/results/${deep.id}`);
  expect(screen.getByRole('meter')).toBeTruthy();
  expect(fetcher.mock.calls.some(([url]) => url === `/api/jobs/${deep.id}/`)).toBe(true);
});

it('keeps an unavailable deep link private and rejects non-UUID paths without a detail request', async () => {
  const { fetcher } = server(); window.history.replaceState(null, '', `/results/${queued.id}`);
  await mount(); expect(screen.getByRole('heading', { name: 'Comparison unavailable' })).toBeTruthy();
  expect(screen.queryByRole('meter')).toBeNull(); cleanup();
  window.history.replaceState(null, '', '/jobs/not-a-valid-id'); const count = fetcher.mock.calls.filter(([url]) => url.startsWith('/api/jobs/')).length;
  await mount(); expect(screen.getByRole('heading', { name: 'We couldn’t find that page' })).toBeTruthy();
  expect(fetcher.mock.calls.filter(([url]) => url.startsWith('/api/jobs/'))).toHaveLength(count + 1);
});

it('renders terminal failure without a report and links its saved notification to that job', async () => {
  const { state } = server(signedIn, [{ ...queued, status: 'failed', error_code: 'retry_exhausted' }]);
  state.notifications = [{ ...completedNotice, status: 'failed', href: `/jobs/${queued.id}` }];
  await mount(); await openInbox(); await click(/Full stack engineerProcessing stopped/);
  expect(window.location.pathname).toBe(`/jobs/${queued.id}`);
  expect(screen.getByText('Processing stopped after the allowed retry attempts.')).toBeTruthy();
  expect(screen.queryByRole('meter')).toBeNull();
});

it('reconciles a completion when returning online even with no previously known active jobs', async () => {
  const { state, fetcher } = server();
  const online = vi.spyOn(navigator, 'onLine', 'get'); const visibility = vi.spyOn(document, 'visibilityState', 'get');
  await mount(); const count = fetcher.mock.calls.length;
  visibility.mockReturnValue('hidden'); await act(async () => { document.dispatchEvent(new Event('visibilitychange')); });
  state.jobs = [{ ...queued, status: 'succeeded', match: report }]; state.notifications = [completedNotice];
  await tick(30000); expect(fetcher.mock.calls).toHaveLength(count);
  online.mockReturnValue(false); visibility.mockReturnValue('visible'); await act(async () => { document.dispatchEvent(new Event('visibilitychange')); });
  await tick(30000); expect(fetcher.mock.calls).toHaveLength(count);
  online.mockReturnValue(true); await act(async () => { window.dispatchEvent(new Event('online')); });
  expect(screen.getByText('1 comparison has an update.')).toBeTruthy();
  expect(window.location.pathname).toBe('/');
});

it('does not overlap monitoring requests while a previous refresh is still pending', async () => {
  const { state, fetcher } = server(signedIn, [queued]); let finish!: (response: Response) => void;
  await mount(); state.readJobs = () => new Promise((resolve) => { finish = resolve; }); await tick();
  const count = fetcher.mock.calls.filter(([url]) => url === '/api/jobs/').length;
  await act(async () => { window.dispatchEvent(new Event('focus')); window.dispatchEvent(new Event('online')); });
  await tick(3000); expect(fetcher.mock.calls.filter(([url]) => url === '/api/jobs/')).toHaveLength(count);
  state.readJobs = async () => json({ jobs: state.jobs });
  await act(async () => { finish(json({ jobs: state.jobs })); }); await tick(1);
  expect(fetcher.mock.calls.filter(([url]) => url === '/api/jobs/')).toHaveLength(count + 1);
});

it('persists read acknowledgement with CSRF and restores it after remount', async () => {
  const { state, fetcher } = server(); state.notifications = [{ ...completedNotice }];
  await mount(); await openInbox(); await click('Mark as read');
  expect(screen.getByText('0 unread', { selector: '.inbox .section-heading > span' })).toBeTruthy();
  const acknowledgement = fetcher.mock.calls.find(([url, options]) => url === `/api/notifications/${completedNotice.id}/read/` && options.method === 'POST')!;
  expect(new Headers(acknowledgement[1].headers).get('X-CSRFToken')).toBe('rotated-token');
  cleanup(); await mount(); expect(screen.queryByRole('button', { name: 'Mark as read' })).toBeNull();
  expect(screen.getByRole('link', { name: /Full stack engineerReport ready/ }).getAttribute('href')).toBe(`/results/${queued.id}`);
});

it('merges older inbox pages without duplicates, then refreshes their window when returning', async () => {
  const { state } = server();
  state.notifications = Array.from({ length: 101 }, (_, index) => ({ ...completedNotice, id: `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`, job_title: `Finished role ${index}` }));
  await mount(); await openInbox(); await click('Load older updates');
  expect(screen.getByRole('link', { name: 'Finished role 100Report ready' })).toBeTruthy();
  await tick(15000); expect(screen.getAllByRole('link', { name: /Finished role/ })).toHaveLength(101);
  await act(async () => { window.dispatchEvent(new Event('focus')); });
  expect(screen.queryByRole('link', { name: 'Finished role 100Report ready' })).toBeNull();
  expect(screen.getByRole('button', { name: 'Load older updates' })).toBeTruthy();
});

it('does not resurrect an original or navigate from a delayed admission after that source is deleted', async () => {
  const { state } = server(); state.documents = [stored]; let finish!: (response: Response) => void;
  state.post = () => new Promise((resolve) => { finish = resolve; });
  await mount(); await click('Use source'); await click('Analyze evidence'); await click('Delete original'); await click('Delete original and reports');
  await act(async () => { finish(json({ ...queued, document: stored }, 202)); });
  expect(screen.queryByText('saved-original.txt')).toBeNull();
  expect(screen.queryByRole('link', { name: /Full stack engineer.*queued/ })).toBeNull();
  expect(window.location.pathname).toBe('/'); expect(screen.getByText(/source for this comparison was deleted/)).toBeTruthy();
});

it('preserves a newly selected source while an unrelated original deletion is pending', async () => {
  const other = { ...stored, id: 'doc-2', filename: 'other-source.txt' };
  const { state } = server(); state.documents = [stored, other];
  let finish!: () => void; const remove = state.deleteDocument;
  state.deleteDocument = async (id) => { await new Promise<void>((resolve) => { finish = resolve; }); return remove(id); };
  await mount(); const sourceA = screen.getByRole('heading', { name: stored.filename }).closest('li')!;
  const sourceB = screen.getByRole('heading', { name: other.filename }).closest('li')!;
  await act(async () => { fireEvent.click(within(sourceA).getByRole('button', { name: 'Use source' })); fireEvent.click(within(sourceA).getByRole('button', { name: 'Delete original' })); });
  await click('Delete original and reports');
  await act(async () => { fireEvent.click(within(sourceB).getByRole('button', { name: 'Use source' })); finish(); });
  expect((screen.getByLabelText('Choose a saved source') as HTMLSelectElement).value).toBe('doc-2');
  expect(screen.queryByRole('heading', { name: stored.filename })).toBeNull();
});

it('keeps a newer deep-linked comparison visible after an older deletion completes', async () => {
  const other = { ...queued, id: '22222222-2222-4222-8222-222222222222', job_title: 'Independent deep-linked job' };
  const { state } = server(signedIn, [queued]); let finish!: () => void; const remove = state.deleteJob;
  state.readDetail = async (id) => json(id === other.id ? other : queued);
  state.deleteJob = async (id) => { await new Promise<void>((resolve) => { finish = resolve; }); return remove(id); };
  await mount(); await click(/Full stack engineer.*queued/); await click('Delete this comparison'); await click('Delete comparison');
  await popTo(`/jobs/${other.id}`); expect(screen.getByRole('heading', { name: other.job_title })).toBeTruthy();
  await act(async () => { finish(); });
  expect(window.location.pathname).toBe(`/jobs/${other.id}`); expect(screen.getByRole('heading', { name: other.job_title })).toBeTruthy();
});

it('releases a pending original download after an unrelated notification acknowledgement', async () => {
  const { state } = server(); state.documents = [stored]; state.notifications = [{ ...completedNotice }];
  let finish!: (response: Response) => void; state.download = () => new Promise((resolve) => { finish = resolve; });
  const create = vi.fn(() => 'blob:synthetic-only');
  class BrowserURL extends URL { static createObjectURL = create; static revokeObjectURL = vi.fn(); }
  vi.stubGlobal('URL', BrowserURL); vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  await mount(); await click('Download original'); await openInbox(); await click('Mark as read');
  await act(async () => { finish(new Response('synthetic original', { headers: { 'Content-Type': 'application/octet-stream' } })); });
  expect(create).toHaveBeenCalledOnce(); expect(window.location.pathname).toBe('/notifications');
});

it('does not release a pending original download after deleting that original', async () => {
  const { state } = server(); state.documents = [stored]; let finish!: (response: Response) => void;
  state.download = () => new Promise((resolve) => { finish = resolve; }); const create = vi.fn(() => 'blob:synthetic-only');
  class BrowserURL extends URL { static createObjectURL = create; static revokeObjectURL = vi.fn(); }
  vi.stubGlobal('URL', BrowserURL);
  await mount(); await click('Download original'); await click('Delete original'); await click('Delete original and reports');
  await act(async () => { finish(new Response('synthetic original', { headers: { 'Content-Type': 'application/octet-stream' } })); });
  expect(create).not.toHaveBeenCalled();
});

it('resets older inbox pages after deleting a source whose jobs are outside recent history', async () => {
  const { state } = server(); state.documents = [stored];
  state.jobs = Array.from({ length: 101 }, (_, index) => ({ ...queued, document: stored, id: `00000000-0000-4000-8000-${String(index).padStart(12, '0')}` }));
  state.notifications = state.jobs.map((job, index) => ({ ...completedNotice, id: job.id, job_id: job.id, job_title: `Old comparison ${index}` }));
  state.readJobs = async () => json({ jobs: [] });
  await mount(); await openInbox(); await click('Load older updates');
  expect(screen.getByRole('link', { name: 'Old comparison 100Report ready' })).toBeTruthy();
  await click('Delete original'); await click('Delete original and reports');
  expect(screen.getByRole('heading', { name: 'No updates yet' })).toBeTruthy();
  expect(screen.queryByRole('link', { name: /Old comparison/ })).toBeNull();
});
