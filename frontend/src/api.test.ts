import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from './api';

afterEach(() => vi.unstubAllGlobals());

describe('same-origin API boundary', () => {
  it('sends the current CSRF token for mutations without overriding multipart content type', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 'report' }), { status: 201 }));
    vi.stubGlobal('fetch', fetcher);
    const body = new FormData();
    body.set('resume_text', 'Fictional Python experience.');
    await api('jobs/', { method: 'POST', body }, 'rotated-token');
    const [url, options] = fetcher.mock.calls[0];
    expect(url).toBe('/api/jobs/');
    expect(options.credentials).toBe('same-origin');
    expect(options.headers.get('X-CSRFToken')).toBe('rotated-token');
    expect(options.headers.has('Content-Type')).toBe(false);
    expect(options.body).toBe(body);
  });

  it('blocks mutations without CSRF and preserves server error references', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: 'Daily limit reached.', request_id: 'trace-123' }), { status: 429 }));
    vi.stubGlobal('fetch', fetcher);
    await expect(api('logout/', { method: 'POST' })).rejects.toBeInstanceOf(ApiError);
    expect(fetcher).not.toHaveBeenCalled();
    await expect(api('jobs/', { method: 'POST' }, 'csrf')).rejects.toMatchObject({ message: 'Daily limit reached.', status: 429, requestId: 'trace-123' });
  });

  it('handles successful deletion and unreachable or non-JSON backends', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockRejectedValueOnce(new TypeError('Network failed'))
      .mockResolvedValueOnce(new Response('<html>Bad gateway</html>', { status: 502 }));
    vi.stubGlobal('fetch', fetcher);
    await expect(api('jobs/id/', { method: 'DELETE' }, 'csrf')).resolves.toBeUndefined();
    await expect(api('session/')).rejects.toMatchObject({ status: 0 });
    await expect(api('session/')).rejects.toMatchObject({ status: 502 });
  });
});
