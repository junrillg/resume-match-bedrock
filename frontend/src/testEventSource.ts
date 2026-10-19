// Controllable transport double: timers never fabricate a server-side change.
export class TestEventSource extends EventTarget {
  static instances: TestEventSource[] = [];
  static autoReady = true;
  static revision = 0;
  closed = false;
  constructor(public url: string) {
    super(); TestEventSource.instances.push(this);
    if (TestEventSource.autoReady) queueMicrotask(() => { if (!this.closed) this.emit('ready', { revision: TestEventSource.revision }); });
  }
  emit(name: string, data: unknown) { this.dispatchEvent(new MessageEvent(name, { data: JSON.stringify(data) })); }
  close() { this.closed = true; }
  static active() { return this.instances.filter((instance) => !instance.closed).at(-1); }
  static change(kind: string, ids: { job_id?: string; document_id?: string } = {}) {
    this.active()?.emit('change', { revision: ++this.revision, kind, ...ids });
  }
  static reset() { this.instances = []; this.autoReady = true; this.revision = 0; }
}
