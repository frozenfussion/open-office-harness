// SPDX-License-Identifier: AGPL-3.0-only
import { inject, Injectable } from '@angular/core';
import { OidcSecurityService } from 'angular-auth-oidc-client';
import { firstValueFrom } from 'rxjs';
import { CONFIG } from './config';
import { ChatEvent, JobEvent, readStream } from './sse';
export type Access = 'approved' | 'pending' | 'rejected' | 'closed';
export interface RequestableTier { tier: number; title: string; requested: 'pending' | 'rejected' | null }
export interface RequestableSkill { name: string; title: string; description: string; requested: 'pending' | 'rejected' | null }
export type JobStatus = 'awaiting_approval' | 'queued' | 'completed' | 'failed' | 'rejected';
export interface Job { job_id: string; skill: string; title: string; label: string; status: JobStatus; created_at?: string; updated_at?: string; output?: {file_key: string; mime: string; summary: string} | null; error?: {code: string; message: string} | null }
export interface Me { requestable_skills?: RequestableSkill[]; access: Access; user_id: string; name: string; chat_tiers: number[]; chat_tier_titles: Record<string, string>; chat_tier_thinking_switch: Record<string, boolean>; requestable_tiers: RequestableTier[]; skills: {name: string; title: string}[] }
export interface Conversation { id: string; title: string; updated_at: string }
export interface Message {
  jobs?: Job[]; id?: string; role: 'user' | 'assistant'; content: string; created_at: string;
  tier?: number | null; model_title?: string | null;
  input_tokens?: number | null; output_tokens?: number | null; note?: string | null;
  outcome?: string; thinking?: string | null; thinkingRequested?: boolean; thinking_applied?: boolean;
}
export class ApiError extends Error {
  constructor(readonly status: number, message: string, readonly code?: string) { super(message); }
}
@Injectable({ providedIn: 'root' })
export class Api {
  private readonly auth = inject(OidcSecurityService);
  private readonly config = inject(CONFIG);
  private async request(path: string, init?: RequestInit): Promise<Response> {
    const token = await firstValueFrom(this.auth.getAccessToken());
    const response = await fetch(this.config.apiBase + path, {
      ...init, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      cache: 'no-store',
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({})) as {message?: string; code?: string};
      throw new ApiError(response.status, error.message || 'The request failed. Try again.', error.code);
    }
    return response;
  }
  async me(): Promise<Me> { return (await this.request('/me')).json(); }
  async list(before?: string): Promise<Conversation[]> {
    return (await this.request('/conversations?limit=50' + (before ? '&before=' + encodeURIComponent(before) : ''))).json();
  }
  async create(): Promise<{ id: string }> {
    return (await this.request('/conversations', { method: 'POST', body: '{}' })).json();
  }
  async conversation(id: string): Promise<{id: string; title: string; messages: Message[]}> {
    return (await this.request('/conversations/' + encodeURIComponent(id))).json();
  }
  async requestTier(tier: number, reason: string): Promise<{id: string; status: 'pending'}> {
    return (await this.request('/tier-requests', {method: 'POST', body: JSON.stringify({tier, reason})})).json();
  }
  async jobs(before?: string): Promise<Job[]> {
    return (await this.request('/jobs?limit=50' + (before ? '&before=' + encodeURIComponent(before) : ''))).json();
  }
  async requestSkill(skill: string, reason: string): Promise<{id: string; status: 'pending'}> {
    return (await this.request('/skill-requests', {method: 'POST', body: JSON.stringify({skill, reason})})).json();
  }
  async events(signal: AbortSignal, connected: () => Promise<void>, receive: (event: JobEvent) => void): Promise<void> {
    const response = await this.request('/events', {signal});
    if (!response.body || !response.headers.get('Content-Type')?.startsWith('text/event-stream')) throw new Error('Jobs stream unavailable');
    await connected();
    await readStream(response.body, event => { if (event.type.startsWith('job.')) receive(event as JobEvent); });
  }
  async download(job: Job): Promise<void> {
    const response = await this.request('/jobs/' + encodeURIComponent(job.job_id) + '/file');
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    const filename = response.headers.get('Content-Disposition')?.match(/filename="([^"\r\n]+)"/i)?.[1];
    anchor.download = filename?.replace(/[\\/]/g, '_') || 'presentation.pptx';
    document.body.append(anchor);
    try { anchor.click(); } finally { anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
  }
  async send(id: string, content: string, tier: number, signal: AbortSignal, receive: (event: ChatEvent) => void, thinking = true): Promise<void> {
    const response = await this.request('/conversations/' + encodeURIComponent(id) + '/messages', {
      method: 'POST', body: JSON.stringify({content, tier, thinking}), signal,
    });
    if (!response.body || !response.headers.get('Content-Type')?.startsWith('text/event-stream')) {
      throw new Error('The answer stream did not start. Try again.');
    }
    await readStream(response.body, event => { if (!event.type.startsWith('job.')) receive(event as ChatEvent); });
  }
}
