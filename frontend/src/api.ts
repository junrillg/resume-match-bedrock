export type Session = {
  authenticated: boolean;
  username?: string;
  csrfToken: string;
  provider: 'demo' | 'bedrock';
};
export type Requirement = { skill: string; weight: number };
export type Match = {
  id: string;
  job_title: string;
  score: number;
  provider: 'demo' | 'bedrock';
  created_at: string;
  requirements: (Requirement & { matched: boolean; evidence: string | null })[];
  request_id: string;
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
  let response: Response;
  try {
    response = await fetch(`/api/${path}`, { ...options, headers, credentials: 'same-origin' });
  } catch {
    throw new ApiError('Cannot reach the server. Check that the backend is running, then try again.', 0);
  }
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(body?.error || 'The request could not be completed. Please try again.', response.status, body?.request_id);
  if (body === null) throw new ApiError('The server returned an unreadable response. Please try again.', response.status);
  return body as T;
}
