import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { workspaceEvents, type WorkspaceUpdates } from './workspaceEvents';
import { TestEventSource } from './testEventSource';

const id = '11111111-1111-4111-8111-111111111111';
let delivery: ReturnType<typeof workspaceEvents>;
function start(apply = vi.fn(async (_updates: WorkspaceUpdates, _signal: AbortSignal) => {})) {
  const callbacks = { apply, error: vi.fn(), connectionError: vi.fn(), sessionEnded: vi.fn(), connection: vi.fn() };
  delivery = workspaceEvents(callbacks); return callbacks;
}
const advance = (milliseconds = 101) => vi.advanceTimersByTimeAsync(milliseconds);
beforeEach(() => {
  vi.useFakeTimers(); vi.spyOn(Math, 'random').mockReturnValue(0); TestEventSource.reset(); vi.stubGlobal('EventSource', TestEventSource);
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true);
});
afterEach(() => { delivery?.stop(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it('waits for subscription ready before snapshot, then makes no healthy idle reads', async () => {
  TestEventSource.autoReady = false;
  const callbacks = start(); await advance(1000);
  expect(callbacks.apply).not.toHaveBeenCalled();
  TestEventSource.active()!.emit('ready', { revision: 4 }); await advance(0);
  expect(callbacks.apply).toHaveBeenCalledTimes(1);
  expect(callbacks.apply.mock.calls[0][0].full).toBe(true);
  await advance(300000);
  expect(callbacks.apply).toHaveBeenCalledTimes(1);
  expect(TestEventSource.instances.filter((item) => !item.closed)).toHaveLength(1);
});

it('coalesces repeated revisions and affected IDs into one targeted batch', async () => {
  const callbacks = start(); await advance(0); callbacks.apply.mockClear();
  for (let n = 0; n < 100; n++) TestEventSource.change('job.changed', { job_id: id });
  TestEventSource.change('document.changed', { document_id: id });
  TestEventSource.change('inbox.changed');
  TestEventSource.active()!.emit('change', { revision: 102, kind: 'job.changed', job_id: id });
  await advance();
  expect(callbacks.apply).toHaveBeenCalledTimes(1);
  expect(callbacks.apply.mock.calls[0][0]).toEqual({ full: false, jobs: [id], documents: [id], inbox: true });
});

it('keeps changes received during snapshot and does not overlap REST batches', async () => {
  let complete!: () => void;
  const apply = vi.fn(async (_updates: WorkspaceUpdates, _signal: AbortSignal) => {});
  apply.mockImplementationOnce(() => new Promise((resolve) => { complete = resolve; }));
  start(apply); await advance(0);
  TestEventSource.change('job.changed', { job_id: id }); await advance(5000);
  expect(apply).toHaveBeenCalledTimes(1);
  complete(); await advance();
  expect(apply).toHaveBeenCalledTimes(2);
  expect(apply.mock.calls[1][0].jobs).toEqual([id]);
});

it('reconnects from its numeric owner-local cursor and reconciles expired replay', async () => {
  const callbacks = start(); await advance(0);
  TestEventSource.change('job.changed', { job_id: id }); await advance();
  TestEventSource.autoReady = false;
  TestEventSource.active()!.dispatchEvent(new Event('error')); await advance(15000);
  expect(TestEventSource.active()!.url).toBe('/api/events/?cursor=1');
  TestEventSource.active()!.emit('reset', { revision: 40 });
  TestEventSource.active()!.emit('ready', { revision: 40 }); await advance(0);
  expect(callbacks.apply.mock.calls.at(-1)![0].full).toBe(true);
  const count = callbacks.apply.mock.calls.length;
  TestEventSource.active()!.emit('change', { revision: 39, kind: 'inbox.changed' }); await advance();
  expect(callbacks.apply).toHaveBeenCalledTimes(count);
});

it('bounds a large distinct completion burst by falling back to one snapshot', async () => {
  const callbacks = start(); await advance(0); callbacks.apply.mockClear();
  for (let n = 0; n < 300; n++) TestEventSource.change('job.changed', { job_id: `00000000-0000-4000-8000-${String(n).padStart(12, '0')}` });
  await advance();
  expect(callbacks.apply).toHaveBeenCalledTimes(1);
  expect(callbacks.apply.mock.calls[0][0].full).toBe(true);
  expect(callbacks.apply.mock.calls[0][0].jobs.length).toBeLessThanOrEqual(256);
});

it('closes while hidden/offline and catches up once after becoming visible online', async () => {
  const visibility = vi.spyOn(document, 'visibilityState', 'get');
  const online = vi.spyOn(navigator, 'onLine', 'get');
  const callbacks = start(); await advance(0);
  visibility.mockReturnValue('hidden'); document.dispatchEvent(new Event('visibilitychange'));
  expect(TestEventSource.active()).toBeUndefined();
  await advance(300000); expect(callbacks.apply).toHaveBeenCalledTimes(1);
  visibility.mockReturnValue('visible'); online.mockReturnValue(false); document.dispatchEvent(new Event('visibilitychange'));
  expect(TestEventSource.active()).toBeUndefined();
  online.mockReturnValue(true); window.dispatchEvent(new Event('online')); await advance(0);
  expect(TestEventSource.instances).toHaveLength(2);
  expect(callbacks.apply).toHaveBeenCalledTimes(2);
});

it('stops on session-ended and ignores callbacks from the old stream', async () => {
  const callbacks = start(); await advance(0); const original = TestEventSource.active()!;
  original.emit('session-ended', {});
  expect(original.closed).toBe(true); expect(callbacks.sessionEnded).toHaveBeenCalledTimes(1);
  original.emit('change', { revision: 50, kind: 'workspace.changed' });
  window.dispatchEvent(new Event('focus')); await advance(60000);
  expect(callbacks.apply).toHaveBeenCalledTimes(1); expect(TestEventSource.instances).toHaveLength(1);
});

it('reconnects without any automatic REST polling during a prolonged stream outage', async () => {
  const callbacks = start(); await advance(0); TestEventSource.autoReady = false;
  TestEventSource.active()!.dispatchEvent(new Event('error'));
  await advance(300000);
  expect(callbacks.apply).toHaveBeenCalledTimes(1);
  expect(callbacks.connectionError.mock.calls.length).toBeGreaterThan(2);
  expect(TestEventSource.instances.filter((item) => !item.closed).length).toBeLessThanOrEqual(1);
});

it('reports unsupported streaming without repeatedly connecting or polling', async () => {
  vi.stubGlobal('EventSource', undefined); const callbacks = start();
  await advance(300000);
  expect(callbacks.connectionError).toHaveBeenCalledTimes(1);
  expect(callbacks.apply).not.toHaveBeenCalled();
  delivery.reconcile(); await advance(0);
  expect(callbacks.apply).toHaveBeenCalledTimes(1);
  expect(callbacks.connectionError.mock.calls.at(-1)?.[0]).toMatch(/cannot receive live updates/);
});

it('backs off failed state reads, then allows deliberate immediate retry', async () => {
  const callbacks = start(); await advance(0);
  callbacks.apply.mockRejectedValueOnce(new Error('temporarily unavailable'));
  TestEventSource.change('job.changed', { job_id: id }); await advance();
  expect(callbacks.error).toHaveBeenCalledTimes(1);
  TestEventSource.change('inbox.changed'); await advance(10000);
  expect(callbacks.apply).toHaveBeenCalledTimes(2);
  delivery.reconcile(); await advance(0);
  expect(callbacks.apply).toHaveBeenCalledTimes(3);
  expect(callbacks.apply.mock.calls.at(-1)![0].full).toBe(true);
});

it('aborts in-flight reads and disposes timers/listeners on unmount', async () => {
  const callbacks = start(vi.fn(() => new Promise<void>(() => {}))); await advance(0);
  const signal = callbacks.apply.mock.calls[0][1]; delivery.stop();
  expect(signal.aborted).toBe(true);
  window.dispatchEvent(new Event('focus')); await advance(120000);
  expect(callbacks.apply).toHaveBeenCalledTimes(1);
  expect(TestEventSource.active()).toBeUndefined();
});


it('stops failed resource retries after three attempts without broadening into list polling', async () => {
  const callbacks = start(); await advance(0);
  callbacks.apply.mockRejectedValue(new Error('state reads unavailable'));
  TestEventSource.change('job.changed', { job_id: id }); await advance();
  await advance(30000); await advance(60000);
  expect(callbacks.apply).toHaveBeenCalledTimes(4);
  expect(callbacks.apply.mock.calls.slice(1).every(([batch]) => !batch.full && batch.jobs.length === 1)).toBe(true);
  TestEventSource.change('inbox.changed'); await advance(300000);
  expect(callbacks.apply).toHaveBeenCalledTimes(4);
});
