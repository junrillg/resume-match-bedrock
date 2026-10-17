import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import App, { MatchResult } from './App';
import type { Match } from './api';

const report: Match = {
  id: 'report-1', job_title: 'Full stack engineer', score: 60, provider: 'demo',
  created_at: '2026-01-01T12:00:00Z', request_id: 'request-123',
  requirements: [
    { skill: 'Python', weight: 3, matched: true, evidence: 'Built Python services.' },
    { skill: 'PostgreSQL', weight: 2, matched: false, evidence: null },
  ],
};

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('shows server-owned weighted coverage, actual excerpts, and honest document gaps', () => {
  render(<MatchResult match={report} busy={false} onDelete={() => {}} />);
  expect(screen.getByRole('meter').getAttribute('aria-valuenow')).toBe('60');
  expect(screen.getByText('Built Python services.')).toBeTruthy();
  expect(screen.getByText(/not proof of a missing ability/)).toBeTruthy();
  expect(screen.getByText('Demo · local deterministic')).toBeTruthy();
  expect(screen.getByText('1 of 2 skills evidenced')).toBeTruthy();
});

it('rotates CSRF after login, submits only the selected source, and confirms deletion', async () => {
  const anonymous = { authenticated: false, csrfToken: 'before-login', provider: 'demo' };
  const signedIn = { authenticated: true, username: 'reviewer', csrfToken: 'after-login', provider: 'demo' };
  const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(anonymous)))
    .mockResolvedValueOnce(new Response(JSON.stringify(signedIn)))
    .mockResolvedValueOnce(new Response(JSON.stringify(signedIn)))
    .mockResolvedValueOnce(new Response(JSON.stringify({ matches: [] })))
    .mockResolvedValueOnce(new Response(JSON.stringify(report), { status: 201 }))
    .mockResolvedValueOnce(new Response(null, { status: 204 }));
  vi.stubGlobal('fetch', fetcher);
  vi.stubGlobal('requestAnimationFrame', () => 0);
  render(<App />);
  await screen.findByRole('heading', { name: 'Sign in to review a résumé' });
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'reviewer' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'example-not-a-real-password' } });
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
  await screen.findByRole('heading', { name: 'Define the match' });
  fireEvent.click(screen.getByRole('button', { name: /Use fictional sample/ }));
  fireEvent.click(screen.getByRole('button', { name: /Analyze evidence/ }));
  await screen.findByRole('heading', { name: '1 of 2 skills evidenced' });
  const [, post] = fetcher.mock.calls[4];
  expect(post.headers.get('X-CSRFToken')).toBe('after-login');
  expect(post.body.get('resume_text')).toContain('FICTIONAL SAMPLE');
  expect(post.body.has('resume')).toBe(false);
  expect(JSON.parse(post.body.get('requirements'))).toHaveLength(4);
  fireEvent.click(screen.getByRole('button', { name: 'Delete this report' }));
  expect(fetcher).toHaveBeenCalledTimes(5);
  fireEvent.click(screen.getByRole('button', { name: 'Delete report' }));
  await waitFor(() => expect(screen.queryByRole('meter')).toBeNull());
  expect(fetcher.mock.calls[5][1].method).toBe('DELETE');
});

it('clears the previous account’s private draft after session expiry', async () => {
  const firstUser = { authenticated: true, username: 'first-reviewer', csrfToken: 'first', provider: 'demo' };
  const anonymous = { authenticated: false, csrfToken: 'anonymous', provider: 'demo' };
  const nextUser = { authenticated: true, username: 'next-reviewer', csrfToken: 'next', provider: 'demo' };
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(firstUser)))
    .mockResolvedValueOnce(new Response(JSON.stringify({ matches: [] })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ error: 'Sign in again.', request_id: 'expired' }), { status: 401 }))
    .mockResolvedValueOnce(new Response(JSON.stringify(anonymous)))
    .mockResolvedValueOnce(new Response(JSON.stringify(nextUser)))
    .mockResolvedValueOnce(new Response(JSON.stringify(nextUser)))
    .mockResolvedValueOnce(new Response(JSON.stringify({ matches: [] }))));
  render(<App />);
  fireEvent.click(await screen.findByRole('button', { name: /Use fictional sample/ }));
  fireEvent.change(screen.getByLabelText('Role title'), { target: { value: 'Private role' } });
  fireEvent.click(screen.getByRole('button', { name: /Analyze evidence/ }));
  await screen.findByRole('heading', { name: 'Sign in to review a résumé' });
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'next-reviewer' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'fictional-only' } });
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
  await screen.findByRole('heading', { name: 'Define the match' });
  expect((screen.getByLabelText('Résumé text') as HTMLTextAreaElement).value).toBe('');
  expect((screen.getByLabelText('Role title') as HTMLInputElement).value).toBe('Full stack engineer');
});
