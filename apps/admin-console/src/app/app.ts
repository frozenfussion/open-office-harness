// SPDX-License-Identifier: AGPL-3.0-only
import { Component, DestroyRef, ElementRef, afterNextRender, computed, inject, signal } from '@angular/core';
import { Operations, Request } from './operations';
import { defaultTimeZone, displayTime, validTimeZone } from './display-time';
import { FormsModule } from '@angular/forms';
import { OidcSecurityService } from 'angular-auth-oidc-client';
import { firstValueFrom, of, switchMap } from 'rxjs';
import { ConnectionResult, connectionSummary, Grant, ModelEntry, modelPayload, tierRows } from './models';

export function greeting(date = new Date()): string {
  const hour = date.getHours();
  return hour < 12 ? 'Good morning.' : hour < 18 ? 'Good afternoon.' : 'Good evening.';
}

export interface AppConfig { issuer: string; clientId: string; apiBase: string; }
declare global { interface Window { oohConfig: AppConfig; OpenOfficeHarness?: { WordRain: { mount(el: HTMLCanvasElement): { stop(): void } } }; } }
@Component({ selector: 'app-root', imports: [FormsModule, Operations], templateUrl: './app.html', styleUrl: './app.css' })
export class App {
  private auth = inject(OidcSecurityService);
  private element = inject(ElementRef<HTMLElement>);
  private destroy = inject(DestroyRef);
  signedIn = signal(false); admin = signal(false); ready = signal(false);
  models = signal<ModelEntry[]>([]); grants = signal<Grant[]>([]);
  readonly greeting = computed(() => {
    this.ready(); this.signedIn();
    return greeting();
  });
  givenName = signal(''); displayTimeZone = signal(defaultTimeZone);
  private screens = ['overview', 'approvals', 'rights', 'models', 'audit', 'failed-messages'];
  private screenFromHash(): string { const value = window.location.hash.slice(1); return this.screens.includes(value) ? value : 'overview'; }
  screen = signal(this.screenFromHash());
  operationRequest: Request = <T>(path: string, method?: string, body?: unknown) => this.request<T>(path, method, body);
  navigate(screen: string, replace = false): void {
    if (!this.screens.includes(screen)) return;
    this.screen.set(screen);
    if (this.ready() && window.location.hash !== '#' + screen) {
      const url = window.location.pathname + window.location.search + '#' + screen;
      if (replace) window.history.replaceState(null, '', url);
      else window.history.pushState(null, '', url);
    }
  }
  formatTime(value: string | null | undefined): string { return displayTime(value, this.displayTimeZone()); }
  pendingCount = signal(0);
  error = signal(''); busy = signal(false); editing = signal<ModelEntry | null>(null);
  testing = signal<Set<string>>(new Set());
  testResults = signal<Record<string, ConnectionResult>>({});
  connectionSummary = connectionSummary;
  key = ''; removeKey = false; settings = '{}'; thinkingOff = ''; people: Record<number, string> = {};
  types = [
    { value: 'openai_chat_completions', title: 'OpenAI-compatible', help: 'Enter the chat completions endpoint.' },
    { value: 'openai_responses', title: 'OpenAI Responses', help: 'Enter the Responses endpoint.' },
    { value: 'anthropic_messages', title: 'Anthropic Messages', help: 'Enter the Messages endpoint.' }
  ];
  availableTypes(purpose: string): typeof this.types { return purpose === 'classification' ? [...this.types, { value: 'jev_systemone', title: 'Jev System One', help: 'Enter the Jev service endpoint.' }] : this.types; }
  constructor() {
    const syncHash = (): void => {
      const screen = this.screenFromHash(); this.screen.set(screen);
      if (this.ready() && window.location.hash !== '#' + screen) window.history.replaceState(null, '', window.location.pathname + window.location.search + '#' + screen);
    };
    window.addEventListener('hashchange', syncHash); window.addEventListener('popstate', syncHash);
    this.destroy.onDestroy(() => { window.removeEventListener('hashchange', syncHash); window.removeEventListener('popstate', syncHash); });
    afterNextRender(() => {
      const canvas = this.element.nativeElement.querySelector('canvas');
      if (canvas) { const rain = window.OpenOfficeHarness?.WordRain.mount(canvas); this.destroy.onDestroy(() => rain?.stop()); }
    });
    this.auth.checkAuth().pipe(switchMap(result => {
      this.signedIn.set(result.isAuthenticated);
      const givenName: unknown = result.userData?.given_name;
      this.givenName.set(typeof givenName === 'string' ? givenName.trim() : '');
      return result.isAuthenticated ? this.auth.getPayloadFromAccessToken() : of(null);
    })).subscribe({ next: payload => {
      const roles: unknown = payload?.realm_access?.roles;
      if (!this.givenName() && typeof payload?.given_name === 'string') this.givenName.set(payload.given_name.trim());
      this.admin.set(Array.isArray(roles) && roles.includes('ooh-admin'));
      this.ready.set(true);
      const intended = this.signedIn() ? sessionStorage.getItem('ooh-admin-signin-screen') : null;
      if (this.signedIn()) sessionStorage.removeItem('ooh-admin-signin-screen');
      this.navigate(intended && this.screens.includes(intended) ? intended : this.screen(), true);
      if (this.admin()) void this.load();
    }, error: () => { this.ready.set(true); this.error.set('Sign-in could not finish. Try signing in again.'); } });
  }
  signIn(): void { sessionStorage.setItem('ooh-admin-signin-screen', this.screen()); this.auth.authorize(); }
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
    const zone = response.headers?.get('X-Display-Time-Zone');
    if (zone && validTimeZone(zone)) this.displayTimeZone.set(zone);
    const result = await response.json();
    if (!response.ok) throw new Error(result.message || 'The request failed. Try again.');
    return result as T;
  }
  async load(): Promise<void> {
    try {
      await this.loadModels();
      const grants: Grant[] = [];
      let after = '';
      do {
        const page = await this.request<Grant[]>('/admin/grants?limit=200' + (after ? '&after=' + encodeURIComponent(after) : ''));
        grants.push(...page); after = page.length === 200 ? page[page.length - 1].id : '';
      } while (after);
      this.grants.set(grants);
      await this.loadAccessCount();
    } catch (e) { this.failure(e); }
  }
  private async loadModels(): Promise<void> {
    // The registry is intentionally private; the console uses the admin list.
    const models: ModelEntry[] = [];
    let modelAfter = '';
    do {
      const page = await this.request<ModelEntry[]>('/admin/models?limit=200' + (modelAfter ? '&after=' + encodeURIComponent(modelAfter) : ''));
      models.push(...page); modelAfter = page.length === 200 ? page[page.length - 1].model_entry_id : '';
    } while (modelAfter);
    models.sort((a, b) => a.purpose.localeCompare(b.purpose) || (a.tier ?? 0) - (b.tier ?? 0)
      || (a.role === b.role ? 0 : a.role === 'main' ? -1 : 1) || a.priority - b.priority);
    this.models.set(models);
  }
  workspaceUrl(): string { return 'https://harness.' + new URL(window.oohConfig.issuer).hostname.replace(/^auth\./, ''); }
  async pendingApprovals(): Promise<number> {
    let before = ''; let count = 0;
    do {
      const page = await this.request<{ id: string; created_at: string }[]>('/admin/approvals?status=pending&limit=200' + (before ? '&before=' + encodeURIComponent(before) : ''));
      count += page.length; before = page.length === 200 ? page[199].created_at + ',' + page[199].id : '';
    } while (before);
    return count;
  }
  async loadAccessCount(): Promise<void> {
    try {
      const [access, models, skills, approvals] = await Promise.all([this.request<{ count: number }>('/admin/access-requests/count?status=pending'), this.request<{ count: number }>('/admin/tier-requests/count?status=pending'), this.request<{ count: number }>('/admin/skill-requests/count?status=pending'), this.pendingApprovals()]);
      this.pendingCount.set(access.count + models.count + skills.count + approvals);
    }
    catch (error) { this.failure(error); }
  }
  edit(model?: ModelEntry): void {
    this.error.set(''); this.key = ''; this.removeKey = false;
    const entry: ModelEntry = model ? structuredClone(model) : { model_entry_id: '', title: '', purpose: 'chat', tier: 1, role: 'main', location: 'cloud', api_type: 'openai_chat_completions', endpoint_url: '', model_id: '', has_key: false, priority: 100, rate_limit_per_minute: 60, daily_budget: 0, input_price_per_million: 0, output_price_per_million: 0, timeout_seconds: 120, request_settings: {} };
    this.thinkingOff = entry.request_settings_thinking_off == null ? '' : JSON.stringify(entry.request_settings_thinking_off, null, 2);
    this.settings = JSON.stringify(entry.request_settings, null, 2); this.editing.set(entry);
  }
  async save(): Promise<void> {
    const m = this.editing(); if (!m || this.busy()) return;
    this.busy.set(true); this.error.set('');
    try {
      const payload = modelPayload(m, this.key, this.removeKey, this.settings, this.thinkingOff);
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
    try {
      if (this.destroy.destroyed) return;
      await this.loadModels();
      const refreshed = this.models().find(entry => entry.model_entry_id === id);
      if (refreshed && refreshed.health === model.health) {
        await new Promise<void>(resolve => setTimeout(resolve, 2000));
        if (!this.destroy.destroyed) await this.loadModels();
      }
    } catch (error) { this.failure(error); }
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
