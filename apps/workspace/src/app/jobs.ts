// SPDX-License-Identifier: AGPL-3.0-only
import { inject, Injectable, signal } from '@angular/core';
import { Api, ApiError, Job } from './api';
import { JobEvent } from './sse';

export function reconnectDelay(attempt: number): number { return [1000, 2000, 5000, 10000][Math.min(attempt, 3)]; }
export function jobLabel(status: Job['status']): string {
  return {awaiting_approval: 'Waiting for approval', queued: 'Queued', completed: 'Ready', failed: 'Failed', rejected: 'Not approved'}[status];
}
@Injectable({providedIn: 'root'})
export class Jobs {
  private readonly api = inject(Api);
  private controller?: AbortController;
  private generation = 0;
  readonly rows = signal<Job[]>([]);
  readonly notice = signal('');
  readonly more = signal(false);
  private revision = 0;
  start(): void {
    this.stop();
    const controller = new AbortController(); this.controller = controller;
    void this.listen(controller, this.generation);
  }
  stop(): void { this.generation++; this.controller?.abort(); this.controller = undefined; this.rows.set([]); this.notice.set(''); }
  async reload(generation = this.generation): Promise<void> {
    const revision = this.revision;
    const rows = await this.api.jobs();
    if (generation !== this.generation) return;
    // An event received during the fetch must win over the older snapshot.
    this.rows.update(old => revision === this.revision ? rows : [...old, ...rows.filter(row => !old.some(item => item.job_id === row.job_id))]);
    this.more.set(rows.length === 50);
  }
  async loadMore(): Promise<void> {
    const last = this.rows().at(-1); if (!last) return;
    const generation = this.generation;
    try {
      const rows = await this.api.jobs(last.job_id);
      if (generation !== this.generation) return;
      this.rows.update(old => [...old, ...rows.filter(row => !old.some(item => item.job_id === row.job_id))]);
      this.more.set(rows.length === 50);
    } catch { this.notice.set('More jobs could not be loaded. Try again.'); }
  }
  add(job: Job): void {
    this.revision++;
    this.rows.update(rows => {
      const existing = rows.find(row => row.job_id === job.job_id);
      const terminal = existing && ['completed', 'failed', 'rejected'].includes(existing.status);
      return [terminal ? {...job, ...existing} : job, ...rows.filter(row => row.job_id !== job.job_id)];
    });
  }
  receive(event: JobEvent): void {
    this.revision++;
    this.rows.update(rows => rows.map(row => row.job_id !== event.correlation_id ? row : {
      ...row, status: event.type === 'job.failed' ? (event.error?.code === 'approval_rejected' ? 'rejected' : 'failed') : event.type.slice(4) as Job['status'],
      output: event.output, error: event.error,
    }));
    if (!this.rows().some(row => row.job_id === event.correlation_id)) void this.reload().catch(() => this.notice.set('Jobs could not be refreshed.'));
  }
  private async listen(controller: AbortController, generation: number): Promise<void> {
    let attempt = 0;
    while (!controller.signal.aborted) {
      try {
        await this.api.events(controller.signal, async () => { await this.reload(generation); this.notice.set(''); }, event => { if (!controller.signal.aborted && generation === this.generation) this.receive(event); });
      } catch (error) {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && [401, 403].includes(error.status)) { this.notice.set(error.message); return; }
      }
      if (controller.signal.aborted) return;
      this.notice.set('Reconnecting to jobs…');
      await new Promise<void>(resolve => {
        const done = (): void => { clearTimeout(timer); controller.signal.removeEventListener('abort', done); resolve(); };
        const timer = setTimeout(done, reconnectDelay(attempt++));
        controller.signal.addEventListener('abort', done, {once: true});
      });
    }
  }
}
