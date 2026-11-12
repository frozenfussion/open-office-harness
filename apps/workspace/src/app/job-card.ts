// SPDX-License-Identifier: AGPL-3.0-only
import { Component, inject, input, signal } from '@angular/core';
import { Api, ApiError, Job } from './api';
import { jobLabel } from './jobs';
@Component({selector: 'app-job-card', template: `
  <article class="ooh-card" aria-label="Skill job">
    <h3>{{ job().title }}</h3><p>{{ job().label }}</p>
    <span class="ooh-chip" role="status">{{ label(job().status) }}</span>
    @if (job().error; as error) { <p role="alert">{{ error.message }}</p> }
    <p class="ooh-help">Request ID {{ job().job_id.slice(0, 8) }}
      <button class="ooh-btn ooh-btn--ghost ooh-btn--sm" (click)="copy()">{{ copied() ? 'Copied' : 'Copy' }}</button>
    </p>
    @if (job().status === 'completed') {
      <button class="ooh-btn ooh-btn--secondary" [disabled]="downloading()" (click)="download()">{{ downloading() ? 'Downloading…' : 'Download' }}</button>
    }
    @if (notice()) { <p role="alert">{{ notice() }}</p> }
  </article>`, styles: `:host{display:block;margin-block:var(--space-3)}article{padding:var(--space-4);border:1px solid var(--line);background:var(--surface)}h3{margin:0;color:var(--ink)}p{overflow-wrap:anywhere}button{margin-inline:var(--space-2)}`})
export class JobCard {
  private readonly api = inject(Api);
  readonly job = input.required<Job>();
  readonly notice = signal(''); readonly copied = signal(false); readonly downloading = signal(false);
  label = jobLabel;
  async copy(): Promise<void> {
    try { await navigator.clipboard.writeText(this.job().job_id); this.copied.set(true); }
    catch { this.notice.set('Copy failed. Request ID ' + this.job().job_id); }
  }
  async download(): Promise<void> {
    if (this.downloading()) return;
    this.downloading.set(true); this.notice.set('');
    try { await this.api.download(this.job()); }
    catch (error) { this.notice.set(error instanceof ApiError ? error.message : 'Download failed. Try again.'); }
    finally { this.downloading.set(false); }
  }
}
