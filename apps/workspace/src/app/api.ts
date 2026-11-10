// SPDX-License-Identifier: AGPL-3.0-only
import { inject, Injectable } from '@angular/core';
import { OidcSecurityService } from 'angular-auth-oidc-client';
import { firstValueFrom } from 'rxjs';
import { CONFIG } from './config';
import { ChatEvent, readStream } from './sse';
export type Access = 'approved' | 'pending' | 'rejected' | 'closed';
export interface Me { access: Access; user_id: string; name: string; chat_tiers: number[]; chat_tier_titles: Record<string, string>; skills: {name: string; title: string}[] }
export interface Conversation { id: string; title: string; updated_at: string }
export interface Message {
  id?: string; role: 'user' | 'assistant'; content: string;
  tier?: number | null; model_title?: string | null;
  input_tokens?: number | null; output_tokens?: number | null; note?: string | null;
  outcome?: string;
}
export class ApiError extends Error {
  constructor(readonly status: number, message: string) { super(message); }
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
      const error = await response.json().catch(() => ({})) as {message?: string};
      throw new ApiError(response.status, error.message || 'The request failed. Try again.');
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
  async send(id: string, content: string, tier: number, signal: AbortSignal, receive: (event: ChatEvent) => void): Promise<void> {
    const response = await this.request('/conversations/' + encodeURIComponent(id) + '/messages', {
      method: 'POST', body: JSON.stringify({content, tier}), signal,
    });
    if (!response.body || !response.headers.get('Content-Type')?.startsWith('text/event-stream')) {
      throw new Error('The answer stream did not start. Try again.');
    }
    await readStream(response.body, receive);
  }
}
