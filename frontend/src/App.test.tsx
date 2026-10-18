import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import App, { MatchResult } from './App';
import type { DocumentRecord, Job, Match, Session } from './api';

const report: Match = {
  id: 'report-1', job_title: 'Full stack engineer', score: 60, provider: 'demo',
  created_at: '2026-01-01T12:00:00Z', request_id: 'request-123',
  requirements: [
    { skill: 'Python', weight: 3, matched: true, evidence: 'Built Python services.' },
    { skill: 'PostgreSQL', weight: 2, matched: false, evidence: null },
  ],
};
const queued: Job = { id: 'job-1', job_title: report.job_title, status: 'queued', attempts: 0, created_at: report.created_at, request_id: report.request_id, error_code: null, match: null, document: null };
const signedIn: Session = { authenticated: true, username: 'reviewer', csrfToken: 'rotated-token', provider: 'demo', document_retention_days: 90 };
const anonymous: Session = { authenticated: false, csrfToken: 'anonymous-token', provider: 'demo', document_retention_days: 90 };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

function server(session = signedIn, jobs: Job[] = []) {
  const state = {
    session, jobs, matches: [] as Match[], documents: [] as DocumentRecord[],
    post: async (_options: RequestInit) => json(queued, 202),
    readJobs: async (): Promise<Response> => json({ jobs: state.jobs }),
    readDocuments: async (): Promise<Response> => json({ documents: state.documents }),
    download: async (): Promise<Response> => new Response('synthetic original', { headers: { 'Content-Type': 'application/octet-stream' } }),
  };
  const fetcher = vi.fn(async (url: string, options: RequestInit) => {
    if (url === '/api/session/') return json(state.session);
    if (url === '/api/login/') { state.session = signedIn; return json(signedIn); }
    if (url === '/api/logout/') { state.session = anonymous; return json(anonymous); }
    if (url === '/api/jobs/' && options.method === 'POST') return state.post(options);
    if (url === '/api/jobs/') return state.readJobs();
    if (url === '/api/documents/') return state.readDocuments();
    if (url.endsWith('/download/')) return state.download();
    if (url.startsWith('/api/documents/') && options.method === 'DELETE') { state.documents = []; state.jobs = []; state.matches = []; return json({ deleted: true, status: 'deleting' }, 202); }
    if (url === '/api/matches/') return json({ matches: state.matches });
    if (options.method === 'DELETE') { state.jobs = []; state.matches = []; return json({ deleted: true }); }
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal('fetch', fetcher);
  return { state, fetcher };
}
async function mount() { await act(async () => { render(<App />); }); }
async function click(name: string | RegExp) { await act(async () => { fireEvent.click(screen.getByRole('button', { name })); }); }
async function tick(milliseconds = 1000) { await act(async () => { await vi.advanceTimersByTimeAsync(milliseconds); }); }
async function login() {
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'reviewer' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'synthetic-only' } });
  await click('Sign in');
}
beforeEach(() => {
  vi.useFakeTimers(); vi.stubGlobal('requestAnimationFrame', () => 0);
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

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
  expect(screen.getByRole('meter')).toBeTruthy(); expect(screen.getByText('job-1')).toBeTruthy();
  const count = fetcher.mock.calls.length; await tick(5000); expect(fetcher.mock.calls).toHaveLength(count);
  await click('Delete this report'); expect(fetcher.mock.calls).toHaveLength(count);
  await click('Delete comparison'); expect(screen.queryByRole('meter')).toBeNull();
  expect(fetcher.mock.calls.at(-1)![0]).toBe('/api/jobs/job-1/');
  expect(fetcher.mock.calls.at(-1)![1].method).toBe('DELETE');
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

it('restores pending work and pauses/resumes monitoring without falsely failing the job', async () => {
  const { state, fetcher } = server(signedIn, [queued]);
  await mount(); expect(screen.getByText('job-1')).toBeTruthy();
  state.readJobs = async () => { throw new TypeError('offline'); }; await tick();
  expect(screen.getByText('Status updates paused.')).toBeTruthy();
  expect(screen.getByText(/Your job has not been marked failed/)).toBeTruthy();
  const count = fetcher.mock.calls.length; await tick(5000); expect(fetcher.mock.calls).toHaveLength(count);
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
  await mount();
  state.readJobs = () => new Promise((_resolve, reject) => {
    const signal = fetcher.mock.calls.filter(([url]) => url === '/api/jobs/').at(-1)![1].signal!;
    signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
  });
  await tick(); await tick(10000);
  expect(screen.getByText('Status updates paused.')).toBeTruthy();
  expect(screen.getByText(/Accepted and waiting for a worker/)).toBeTruthy();
});

it('does not restore a deleted pending job from an older in-flight poll', async () => {
  const other = { ...queued, id: 'job-2', job_title: 'Another pending role' };
  const { state } = server(signedIn, [queued, other]);
  await mount(); let complete!: (response: Response) => void;
  state.readJobs = () => new Promise((resolve) => { complete = resolve; }); await tick();
  await click('Delete this comparison'); await click('Delete comparison');
  await act(async () => { complete(json({ jobs: [queued, other] })); });
  expect(screen.queryByText('job-1')).toBeNull();
  expect(screen.getByRole('button', { name: /Another pending role/ })).toBeTruthy();
  expect(screen.queryByRole('button', { name: /Full stack engineer.*queued/ })).toBeNull();
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
  expect(fetcher.mock.calls.at(-1)![0]).toBe('/api/matches/report-1/');
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
  await mount(); await click(/Full stack engineer.*60%/);
  await click(/Use synthetic sample/); await click(/Analyze evidence/);
  await click('Delete this report'); await click('Delete comparison');
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
  await mount();
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
  expect(screen.queryByText('job-1')).toBeNull();
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
  await mount();
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
