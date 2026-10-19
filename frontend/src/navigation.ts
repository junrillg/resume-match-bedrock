export type Route =
  | { kind: 'home' | 'notifications' | 'not-found'; path: string }
  | { kind: 'job' | 'result' | 'legacy'; path: string; id: string };

// Keep application navigation local and match the UUID identifiers accepted by Django.
const uuid = '[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}';
const detail = new RegExp(`^/(jobs|results|reports)/(${uuid})/?$`, 'i');
export function readRoute(path = window.location.pathname): Route {
  if (path === '/') return { kind: 'home', path };
  if (path === '/notifications' || path === '/notifications/') return { kind: 'notifications', path };
  const match = detail.exec(path);
  if (match) {
    const segment = match[1].toLowerCase();
    return { kind: segment === 'jobs' ? 'job' : segment === 'results' ? 'result' : 'legacy', id: match[2].toLowerCase(), path };
  }
  return { kind: 'not-found', path };
}
export const jobPath = (id: string) => `/jobs/${encodeURIComponent(id)}`;
export const resultPath = (id: string) => `/results/${encodeURIComponent(id)}`;
export const reportPath = (id: string) => `/reports/${encodeURIComponent(id)}`;
