// SPDX-License-Identifier: AGPL-3.0-only
import { afterRenderEffect, Component, ElementRef, inject, OnDestroy, OnInit, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { OidcSecurityService } from 'angular-auth-oidc-client';
import { Subscription } from 'rxjs';
import { Api, ApiError, Conversation, Me, Message } from './api';
import { Rain } from './rain';
import { MessageContent } from './message-content';

export function metaLine(message: Message): string {
  if (!message.model_title || message.tier == null) return '';
  return `tier ${message.tier} · ${message.model_title} · ${message.input_tokens ?? 0} in / ${message.output_tokens ?? 0} out tokens` +
    (message.note ? ` · ${message.note}` : '');
}
@Component({ selector: 'app-root', imports: [FormsModule, Rain, MessageContent], templateUrl: './app.html', styleUrl: './app.css' })
export class App implements OnInit, OnDestroy {
  private readonly auth = inject(OidcSecurityService);
  private readonly api = inject(Api);
  private readonly subscription = new Subscription();
  readonly history = viewChild<ElementRef<HTMLElement>>('history');
  private abort?: AbortController;
  private readonly streams = new Set<AbortController>();
  readonly ready = signal(false);
  readonly signedIn = signal(false);
  readonly me = signal<Me | null>(null);
  readonly givenName = signal('');
  readonly conversations = signal<Conversation[]>([]);
  readonly messages = signal<Message[]>([]);
  readonly currentId = signal<string | null>(null);
  readonly title = signal('New chat');
  readonly streaming = signal(false);
  readonly loading = signal(false);
  readonly more = signal(false);
  readonly notice = signal('');
  readonly forbidden = signal(false);
  readonly copied = signal(false);
  tier: number | null = null;
  draft = '';
  metaLine = metaLine;
  constructor() {
    afterRenderEffect(() => {
      this.messages();
      this.scrollMessages();
    });
  }
  scrollMessages(): void {
    const history = this.history()?.nativeElement;
    if (history) history.scrollTop = history.scrollHeight;
  }
  ngOnInit(): void {
    this.subscription.add(this.auth.isAuthenticated$.subscribe(({isAuthenticated}) => {
      this.signedIn.set(isAuthenticated);
      if (!isAuthenticated) { this.streams.forEach(stream => stream.abort()); this.messages.set([]); this.me.set(null); }
    }));
    this.subscription.add(this.auth.checkAuth().subscribe({
      next: (result) => {
        this.signedIn.set(result.isAuthenticated);
        const givenName: unknown = result.userData?.given_name;
        this.givenName.set(typeof givenName === 'string' ? givenName.trim().slice(0, 200) : '');
        this.ready.set(true);
        if (result.isAuthenticated) void this.load();
      },
      error: () => { this.ready.set(true); this.notice.set('Sign-in could not finish. Try signing in again.'); },
    }));
  }
  ngOnDestroy(): void { this.subscription.unsubscribe(); this.streams.forEach(stream => stream.abort()); }
  signIn(): void { this.auth.authorize(); }
  signOut(): void { this.streams.forEach(stream => stream.abort()); this.auth.logoff().subscribe(); }
  async copyId(): Promise<void> {
    try { await navigator.clipboard.writeText(this.me()?.user_id || ''); this.copied.set(true); }
    catch { this.notice.set('Copy did not work. Select and copy your user ID.'); }
  }
  tierLabel(tier: number): string {
    const title = this.me()?.chat_tier_titles?.[String(tier)];
    return title ? `${title} - Tier ${tier}` : `Tier ${tier}`;
  }
  accessMessage(): string {
    switch (this.me()?.access) {
      case 'pending': {
        const firstName = this.givenName() || this.me()?.name?.trim().split(/\s+/u)[0];
        return `Thanks${firstName ? ', ' + firstName : ''}. Your request is waiting for approval.`;
      }
      case 'rejected': return 'Your request was not approved. Please contact your administrator.';
      case 'closed': return 'Requests are closed for now. Please contact your administrator.';
      default: return '';
    }
  }
  private failure(error: unknown): void {
    this.forbidden.set(error instanceof ApiError && error.status === 403);
    this.notice.set(error instanceof ApiError ? error.message : 'The request failed. Try again.');
  }
  private async load(): Promise<void> {
    this.loading.set(true);
    try {
      const me = await this.api.me();
      if (!['approved', 'pending', 'rejected', 'closed'].includes(me.access)) {
        throw new ApiError(503, 'Your access could not be checked. Try again.');
      }
      this.me.set(me);
      if (me.access !== 'approved') return;
      me.chat_tiers.sort((a, b) => a - b);
      this.me.set(me);
      this.tier = me.chat_tiers[0] ?? null;
      await this.refreshList();
      const id = new URL(window.location.href).searchParams.get('conversation');
      if (id) await this.open(id);
    } catch (error) { this.failure(error); }
    finally { this.loading.set(false); }
  }
  async refreshList(): Promise<void> {
    if (this.me()?.access !== 'approved') return;
    const rows = await this.api.list();
    this.conversations.set(rows);
    this.more.set(rows.length === 50);
  }
  async loadMore(): Promise<void> {
    if (this.me()?.access !== 'approved') return;
    this.loading.set(true);
    try {
      const last = this.conversations().at(-1);
      if (!last) return;
      const rows = await this.api.list(last.id);
      this.conversations.update(old => [...old, ...rows]);
      this.more.set(rows.length === 50);
    } catch (error) { this.failure(error); }
    finally { this.loading.set(false); }
  }
  private setCurrent(id: string | null): void {
    this.currentId.set(id);
    const url = new URL(window.location.href);
    if (id) url.searchParams.set('conversation', id); else url.searchParams.delete('conversation');
    window.history.replaceState(null, '', url);
  }
  newChat(): void {
    if (this.me()?.access !== 'approved' || this.streaming() || this.loading()) return;
    this.setCurrent(null); this.title.set('New chat'); this.messages.set([]); this.notice.set(''); this.draft = '';
  }
  async open(id: string): Promise<void> {
    if (this.me()?.access !== 'approved' || this.streaming()) return;
    this.loading.set(true); this.notice.set('');
    try {
      const conversation = await this.api.conversation(id);
      this.setCurrent(conversation.id); this.title.set(conversation.title); this.messages.set(conversation.messages);
    } catch (error) { this.failure(error); }
    finally { this.loading.set(false); }
  }
  keydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault(); void this.send();
    }
  }
  async send(): Promise<void> {
    if (this.me()?.access !== 'approved' || !this.draft.trim() || this.tier == null || this.streaming() || this.loading()) return;
    const content = this.draft;
    const sentAt = new Date().toISOString();
    const tier = this.tier;
    this.streaming.set(true); this.notice.set(''); this.forbidden.set(false);
    const controller = new AbortController();
    this.abort = controller;
    this.streams.add(controller);
    let assistant: Message | undefined;
    let ended = false;
    let completed = false;
    let listRefresh: Promise<void> | undefined;
    let generatedTitle: string | undefined;
    let id = this.currentId();
    const applyTitle = (): void => {
      if (generatedTitle === undefined || controller.signal.aborted) return;
      this.conversations.update(rows => rows.map(row => row.id === id ? {...row, title: generatedTitle!} : row));
      if (this.currentId() === id) this.title.set(generatedTitle);
    };
    try {
      if (!id) { id = (await this.api.create()).id; this.setCurrent(id); this.title.set(content.slice(0, 60)); }
      assistant = { role: 'assistant', content: '', created_at: sentAt };
      this.messages.update(old => [...old, {role: 'user', content, created_at: sentAt}, assistant!]);
      this.draft = '';
      await this.api.send(id, content, tier, controller.signal, event => {
        if (controller.signal.aborted) return;
        if (event.type === 'title') {
          if (!completed || event.conversation_id !== id) throw new Error('Unexpected conversation title');
          generatedTitle = event.title;
          applyTitle();
          return;
        }
        if (ended) throw new Error('Stream continued after completion');
        if (event.type === 'delta') assistant!.content += event.text;
        else if (event.type === 'completed') {
          Object.assign(assistant!, {created_at: new Date().toISOString(), id: event.message_id, tier: event.tier, model_title: event.model_title,
            input_tokens: event.usage.input_tokens, output_tokens: event.usage.output_tokens, note: event.note, outcome: 'completed'});
          ended = true;
          completed = true;
          this.streaming.set(false);
          listRefresh = this.refreshList().then(applyTitle).catch(error => {
            if (!this.notice()) this.failure(error);
          });
        } else {
          ended = true;
          assistant!.outcome = 'failed';
          assistant!.created_at = new Date().toISOString();
          this.failure(new ApiError(event.error.code === 'tier_not_allowed' || event.error.code === 'no_tier' ? 403 : 503, event.error.message));
        }
        this.messages.update(old => [...old]);
      });
      if (!ended) throw new Error('Stream ended early');
    } catch (error) {
      if (completed || controller.signal.aborted) return;
      if (assistant) {
        assistant.outcome = 'failed';
        assistant.created_at = new Date().toISOString();
        this.messages.update(old => assistant!.content ? [...old] : old.filter(message => message !== assistant));
      }
      this.failure(error);
    } finally {
      this.streams.delete(controller);
      if (this.abort === controller) {
        this.streaming.set(false); this.abort = undefined;
      }
      if (listRefresh) await listRefresh;
      else {
        try { await this.refreshList(); } catch (error) { if (!this.notice()) this.failure(error); }
      }
    }
  }
}
