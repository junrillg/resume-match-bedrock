export type Session = {
  authenticated: boolean;
  username?: string;
  csrfToken: string;
  log_viewer_url?: string;
  document_retention_days: number;
  provider: 'demo' | 'bedrock-local' | 'bedrock';
};
export type DocumentRecord = {
  id: string; filename: string; content_type: string; size_bytes: number;
  status: 'uploading' | 'pending' | 'ready' | 'rejected' | 'deleting' | 'deleted';
  created_at: string; expires_at: string;
};
export type Requirement = { skill: string; weight: number };
export type Match = {
  id: string;
  job_title: string;
  score: number;
  provider: Session['provider'];
  created_at: string;
  requirements: (Requirement & { matched: boolean; evidence: string | null })[];
  request_id: string;
};
export type Job = {
  id: string;
  job_title: string;
  status: 'uploading' | 'queued' | 'running' | 'succeeded' | 'failed';
  attempts: number;
  created_at: string;
  request_id: string;
  error_code: string | null;
  match: Match | null;
  document: DocumentRecord | null;
  processing_url?: string;
  result_url?: string | null;
};
// History snapshots carry scores, never full evidence reports.
export type HistoryJob = Omit<Job, 'match'> & { match: Pick<Match, 'id' | 'score'> | null };
export type CompletionNotification = {
  id: string; job_id: string; job_title: string; status: 'succeeded' | 'failed';
  created_at: string; read_at: string | null; href: string;
};
export type NotificationPage = {
  notifications: CompletionNotification[]; unread_count: number; next_cursor: string | null; next_offset?: number | null;
};

export class ApiError extends Error {
  constructor(message: string, public status: number, public requestId?: string) {
    super(message);
  }
}

export async function api<T>(path: string, options: RequestInit = {}, csrfToken?: string): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.method && options.method !== 'GET') {
    if (!csrfToken) throw new ApiError('Your session needs refreshing. Reload the page and try again.', 403);
    headers.set('X-CSRFToken', csrfToken);
  }
  const controller = new AbortController();
  const cancel = () => controller.abort();
  if (options.signal?.aborted) cancel();
  else options.signal?.addEventListener('abort', cancel, { once: true });
  const timeout = setTimeout(cancel, 10000);
  try {
    const response = await fetch(`/api/${path}`, { ...options, signal: controller.signal, headers, credentials: 'same-origin' });
    if (response.status === 204) return undefined as T;
    const body = await response.json().catch(() => null);
    if (!response.ok) throw new ApiError(body?.error || 'The request could not be completed. Please try again.', response.status, body?.request_id);
    if (body === null) throw new ApiError('The server returned an unreadable response. Please try again.', response.status);
    return body as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(controller.signal.aborted
      ? 'The request timed out or was cancelled. Check the server, then try again.'
      : 'Cannot reach the server. Check that the backend is running, then try again.', 0);
  } finally {
    clearTimeout(timeout);
    options.signal?.removeEventListener('abort', cancel);
  }
}

export async function downloadDocument(id: string): Promise<Blob> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch(`/api/documents/${encodeURIComponent(id)}/download/`, {
      credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new ApiError(body?.error || 'The original could not be downloaded. Try again later.', response.status, body?.request_id);
    }
    if (!response.headers.get('Content-Type')?.includes('application/octet-stream')) {
      throw new ApiError('The server returned an unreadable download. Try again later.', response.status);
    }
    return await response.blob();
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(controller.signal.aborted
      ? 'The download timed out. Please try again.'
      : 'Cannot download the original. Check your connection and try again.', 0);
  } finally { clearTimeout(timeout); }
}
