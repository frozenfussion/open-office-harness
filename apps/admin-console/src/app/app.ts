// SPDX-License-Identifier: AGPL-3.0-only
import { Component, DestroyRef, ElementRef, afterNextRender, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { OidcSecurityService } from 'angular-auth-oidc-client';
import { firstValueFrom, of, switchMap } from 'rxjs';
import { AccessRequest, AccessStatus, ConnectionResult, connectionSummary, Grant, ModelEntry, modelPayload, tierRows } from './models';

export interface AppConfig { issuer: string; clientId: string; apiBase: string; }
declare global { interface Window { oohConfig: AppConfig; OpenOfficeHarness?: { WordRain: { mount(el: HTMLCanvasElement): { stop(): void } } }; } }
@Component({ selector: 'app-root', imports: [FormsModule], templateUrl: './app.html', styleUrl: './app.css' })
export class App {
  private auth = inject(OidcSecurityService);
  private element = inject(ElementRef<HTMLElement>);
  private destroy = inject(DestroyRef);
  signedIn = signal(false); admin = signal(false); ready = signal(false);
  models = signal<ModelEntry[]>([]); grants = signal<Grant[]>([]);
  screen = signal<'models' | 'access'>('models');
  accessFilter = signal<AccessStatus>('pending');
  accessRequests = signal<AccessRequest[]>([]);
  pendingCount = signal(0); accessBusy = signal(false);
  selectedTiers: Record<string, number | undefined> = {};
  error = signal(''); busy = signal(false); editing = signal<ModelEntry | null>(null);
  testing = signal<Set<string>>(new Set());
  testResults = signal<Record<string, ConnectionResult>>({});
  connectionSummary = connectionSummary;
  key = ''; removeKey = false; settings = '{}'; people: Record<number, string> = {};
  types = [
    { value: 'openai_chat_completions', title: 'OpenAI-compatible', help: 'Chat completions: https://api.deepseek.com or http://<host>:8000/v1' },
    { value: 'openai_responses', title: 'OpenAI Responses', help: 'Responses API: https://api.openai.com/v1' },
    { value: 'anthropic_messages', title: 'Anthropic Messages', help: 'Messages API: https://api.anthropic.com or https://api.deepseek.com/anthropic' }
  ];
  constructor() {
    afterNextRender(() => {
      const canvas = this.element.nativeElement.querySelector('canvas');
      if (canvas) { const rain = window.OpenOfficeHarness?.WordRain.mount(canvas); this.destroy.onDestroy(() => rain?.stop()); }
    });
    this.auth.checkAuth().pipe(switchMap(result => {
      this.signedIn.set(result.isAuthenticated);
      return result.isAuthenticated ? this.auth.getPayloadFromAccessToken() : of(null);
    })).subscribe({ next: payload => {
      const roles: unknown = payload?.realm_access?.roles;
      this.admin.set(Array.isArray(roles) && roles.includes('ooh-admin'));
      this.ready.set(true);
      if (this.admin()) void this.load();
    }, error: () => { this.ready.set(true); this.error.set('Sign-in could not finish. Try signing in again.'); } });
  }
  signIn(): void { this.auth.authorize(); }
  signOut(): void { this.auth.logoff().subscribe({ error: () => this.error.set('Sign-out failed. Try again.') }); }
  tiers(): number[] { return tierRows(this.models(), this.grants()); }
  groups(): string[] { return [...new Set(this.models().map(m => this.label(m)))]; }
  label(m: ModelEntry): string { return m.purpose + (m.purpose === 'chat' ? ` · tier ${m.tier}` : ''); }
  groupModels(label: string): ModelEntry[] { return this.models().filter(m => this.label(m) === label); }
  tierModels(tier: number): ModelEntry[] { return this.models().filter(m => m.purpose === 'chat' && m.tier === tier); }
  tierGrants(tier: number): Grant[] { return this.grants().filter(g => g.right_key === `chat.tier.${tier}`); }
  everyone(tier: number): boolean { return this.tierGrants(tier).some(g => g.subject_type === 'everyone'); }
  async request<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
    const token = await firstValueFrom(this.auth.getAccessToken());
    const response = await fetch(window.oohConfig.apiBase + path, { method, signal, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.message || 'The request failed. Try again.');
    return result as T;
  }
  async load(): Promise<void> {
    try {
      // The registry is intentionally private; the console uses the admin list.
      const models: ModelEntry[] = [];
      let modelAfter = '';
      do {
        const page = await this.request<ModelEntry[]>('/admin/models?limit=200' + (modelAfter ? '&after=' + encodeURIComponent(modelAfter) : ''));
        models.push(...page); modelAfter = page.length === 200 ? page[page.length - 1].model_entry_id : '';
      } while (modelAfter);
      models.sort((a, b) => a.purpose.localeCompare(b.purpose) || (a.tier ?? 0) - (b.tier ?? 0)
        || (a.role === b.role ? 0 : a.role === 'main' ? -1 : 1) || a.priority - b.priority);
      const grants: Grant[] = [];
      let after = '';
      do {
        const page = await this.request<Grant[]>('/admin/grants?limit=200' + (after ? '&after=' + encodeURIComponent(after) : ''));
        grants.push(...page); after = page.length === 200 ? page[page.length - 1].id : '';
      } while (after);
      this.models.set(models); this.grants.set(grants);
      await this.loadAccessCount();
    } catch (e) { this.failure(e); }
  }
  workspaceUrl(): string { return 'https://harness.' + new URL(window.oohConfig.issuer).hostname.replace(/^auth\./, ''); }
  async loadAccessCount(): Promise<void> {
    try { this.pendingCount.set((await this.request<{ count: number }>('/admin/access-requests/count?status=pending')).count); }
    catch (error) { this.failure(error); }
  }
  async openAccessRequests(): Promise<void> { this.screen.set('access'); await this.loadAccessRequests(); }
  async loadAccessRequests(): Promise<void> {
    this.error.set(''); this.selectedTiers = {}; this.accessRequests.set([]);
    const filter = this.accessFilter();
    try {
      const rows: AccessRequest[] = []; let after = '';
      do {
        const page = await this.request<AccessRequest[]>('/admin/access-requests?status=' + filter + '&limit=200' + (after ? '&after=' + encodeURIComponent(after) : ''));
        rows.push(...page); after = page.length === 200 ? page[page.length - 1].id : '';
      } while (after);
      if (filter === this.accessFilter()) this.accessRequests.set(rows);
      await this.loadAccessCount();
    } catch (error) { this.failure(error); }
  }
  async decideAccess(row: AccessRequest, action: 'approve' | 'reject' | 'revoke'): Promise<void> {
    const tier = this.selectedTiers[row.id];
    if (this.accessBusy() || action === 'approve' && !tier) return;
    this.accessBusy.set(true); this.error.set('');
    try {
      const updated = await this.request<AccessRequest>('/admin/access-requests/' + encodeURIComponent(row.id) + '/' + action, 'POST', action === 'approve' ? { tier } : {});
      this.accessRequests.update(rows => rows.flatMap(item => item.id !== row.id ? [item] : updated.status === this.accessFilter() ? [updated] : []));
      await this.load(); await this.loadAccessRequests();
    } catch (error) { this.failure(error); } finally { this.accessBusy.set(false); }
  }
  edit(model?: ModelEntry): void {
    this.error.set(''); this.key = ''; this.removeKey = false;
    const entry: ModelEntry = model ? structuredClone(model) : { model_entry_id: '', title: '', purpose: 'chat', tier: 1, role: 'main', location: 'cloud', api_type: 'openai_chat_completions', endpoint_url: '', model_id: '', has_key: false, priority: 100, rate_limit_per_minute: 60, daily_budget: 0, input_price_per_million: 0, output_price_per_million: 0, timeout_seconds: 120, request_settings: {} };
    this.settings = JSON.stringify(entry.request_settings, null, 2); this.editing.set(entry);
  }
  async save(): Promise<void> {
    const m = this.editing(); if (!m || this.busy()) return;
    this.busy.set(true); this.error.set('');
    try {
      const payload = modelPayload(m, this.key, this.removeKey, this.settings);
      await this.request('/admin/models' + (m.model_entry_id ? '/' + m.model_entry_id : ''), m.model_entry_id ? 'PUT' : 'POST', payload);
      this.key = ''; this.editing.set(null); await this.load();
    } catch (e) { this.failure(e); } finally { this.busy.set(false); }
  }
  async testConnection(model: ModelEntry): Promise<void> {
    const id = model.model_entry_id;
    if (!model.has_key || this.testing().has(id)) return;
    this.testing.update(ids => new Set([...ids, id]));
    this.testResults.update(results => { const next = { ...results }; delete next[id]; return next; });
    const abort = new AbortController();
    const timer = setTimeout(() => abort.abort(), (model.timeout_seconds + 15) * 1000);
    try {
      const result = await this.request<ConnectionResult>('/admin/models/' + encodeURIComponent(id) + '/test', 'POST', {}, abort.signal);
      this.testResults.update(results => ({ ...results, [id]: result }));
    } catch (error) {
      const reason = abort.signal.aborted ? 'took longer than its time limit' : error instanceof Error ? error.message : 'unexpected answer';
      this.testResults.update(results => ({ ...results, [id]: { ok: false, reason, provider_status: null, provider_message: null } }));
    } finally {
      clearTimeout(timer);
      this.testing.update(ids => { const next = new Set(ids); next.delete(id); return next; });
    }
  }
  async switchOff(m: ModelEntry): Promise<void> {
    if (!confirm(`Switch off ${m.title || m.model_id}?`)) return;
    await this.change(() => this.request('/admin/models/' + m.model_entry_id, 'DELETE'));
  }
  async toggleEveryone(tier: number): Promise<void> {
    const grant = this.tierGrants(tier).find(g => g.subject_type === 'everyone');
    await this.change(() => grant ? this.request('/admin/grants/' + grant.id, 'DELETE') : this.request('/admin/grants', 'POST', { right_key: `chat.tier.${tier}`, subject_type: 'everyone' }));
  }
  async addPerson(tier: number): Promise<void> {
    const id = this.people[tier]?.trim(); if (!id) return;
    await this.change(() => this.request('/admin/grants', 'POST', { right_key: `chat.tier.${tier}`, subject_type: 'user', subject_id: id }));
    this.people[tier] = '';
  }
  async removeGrant(grant: Grant): Promise<void> { await this.change(() => this.request('/admin/grants/' + grant.id, 'DELETE')); }
  private async change(action: () => Promise<unknown>): Promise<void> {
    if (this.busy()) return; this.busy.set(true); this.error.set('');
    try { await action(); await this.load(); } catch (e) { this.failure(e); } finally { this.busy.set(false); }
  }
  private failure(e: unknown): void { this.error.set(e instanceof Error ? e.message : 'The request failed. Try again.'); }
}
