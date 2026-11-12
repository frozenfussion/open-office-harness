// SPDX-License-Identifier: AGPL-3.0-only
import { Component, OnChanges, SimpleChanges, PendingTasks, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Grant } from './models';
import { defaultTimeZone, displayTime, overviewGreeting } from './display-time';
export type Request = <T>(path: string, method?: string, body?: unknown) => Promise<T>;
export interface Health { name: string; status: string; checked_at: string | null; }
export interface Overview {
  people_active_today: number | null; people_approved: number; skill_jobs_today: number | null;
  model_calls_today: number | null; cost_today_usd: number | null;
  needs_attention: { kind: string; title: string; detail: string; at: string; link: string }[]; health: Health[];
}
export interface DecisionRow {
  id: string; kind: string; user_id?: string; requester_user_id?: string; name?: string; email?: string;
  title?: string; tier?: number; skill?: string; action?: string; risk?: string; details?: unknown;
  reason?: string; status: string; requested_at?: string; created_at?: string;
}
export interface Person { user_id: string; name?: string; email?: string; }
export interface Column { key: string; title: string; }
export interface TrailRow {
  id: number; occurred_at: string; producer: string; correlation_id: string; user_id: string;
  actor: string; action: string; target: string; outcome: string; scores?: Record<string, number>;
  trace_id?: string | null; person?: string; model?: string; tokens?: number; cost_usd?: number;
}
export interface Replay { id: string; replayed_at: string; replayed_by: string; target_topic: string; outcome: string; error_code?: string; }
export interface DeadLetter { id: string; topic: string; error_code: string; error_message: string; received_at: string; correlation_id?: string; original_message: string; replay_count: number; last_replayed_at?: string; replayable: boolean; replay_history: Replay[]; }
export interface Span { span_id: string; parent_span_id?: string; service: string; name: string; kind: string | number; start: string; duration_ms: number; status: string; attributes: Record<string, unknown>; }
export interface SpanRow { span: Span; depth: number; offset: number; width: number; }
@Component({ selector: 'admin-operations', imports: [FormsModule], templateUrl: './operations.html', styleUrl: './operations.css' })
export class Operations implements OnChanges {
  private tasks = inject(PendingTasks);
  screen = input.required<string>(); request = input.required<Request>();
  timeZone = input(defaultTimeZone); givenName = input('');
  navigate = output<string>(); pending = output<number>();
  overview = signal<Overview | null>(null); decisions = signal<DecisionRow[]>([]); selected = signal<DecisionRow | null>(null);
  persons = signal<Person[]>([]); columns = signal<Column[]>([]); grants = signal<Grant[]>([]);
  changes = signal<Record<string, { user: string; right: string; checked: boolean }>>({});
  trail = signal<TrailRow[]>([]); error = signal(''); busy = signal(false);
  deadLetters = signal<DeadLetter[]>([]); deadLetter = signal<DeadLetter | null>(null); topic = ''; deadMore = signal(false);
  confirmReplay = signal(false); replayResult = signal('');
  traceSpans = signal<SpanRow[]>([]); traceMessage = signal(''); traceLoading = signal(false); selectedSpan = signal<Span | null>(null);
  private traceSequence = 0;
  note = ''; tier: number | undefined; tiers = signal<number[]>([]);
  requestId = ''; person = ''; action = ''; inTrace = signal(false); more = signal(false);
  ngOnChanges(changes: SimpleChanges): void { if (changes['screen'] || changes['request']) this.tasks.run(() => this.load()); }
  formatTime(value: string | null | undefined, milliseconds = false): string { return displayTime(value, this.timeZone(), milliseconds); }
  overviewGreeting(): string { return overviewGreeting(this.givenName(), this.timeZone()); }
  async load(): Promise<void> {
    this.error.set('');
    try {
      switch (this.screen()) {
        case 'overview': this.overview.set(await this.request()<Overview>('/admin/overview')); break;
        case 'approvals': await this.loadDecisions(); break;
        case 'rights': await this.loadRights(); break;
        case 'audit': await this.filter(); break;
        case 'failed-messages': await this.loadDeadLetters(); break;
      }
    } catch (e) { this.failure(e); }
  }
  async pages<T>(path: string, cursor: (row: T) => string, separator = '&after='): Promise<T[]> {
    const rows: T[] = []; let after = '';
    do {
      const page = await this.request()<T[]>(path + (after ? separator + encodeURIComponent(after) : ''));
      rows.push(...page); after = page.length === 200 ? cursor(page[199]) : '';
    } while (after);
    return rows;
  }
  async loadDecisions(): Promise<void> {
    const lists = await Promise.all(['access', 'tier', 'skill'].map(async kind =>
      (await this.pages<DecisionRow>('/admin/' + kind + '-requests?status=pending&limit=200', row => row.id)).map(row => ({ ...row, kind }))));
    const approvals = (await this.pages<DecisionRow>('/admin/approvals?status=pending&limit=200', row => row.created_at + ',' + row.id, '&before='))
      .map(row => ({ ...row, kind: 'approval' }));
    const all = [...lists.flat(), ...approvals].sort((a, b) => (a.requested_at ?? a.created_at ?? '').localeCompare(b.requested_at ?? b.created_at ?? ''));
    this.decisions.set(all); this.pending.emit(all.length); this.selected.set(null); this.note = ''; this.tier = undefined;
    const rights = await this.pages<{ key: string }>('/admin/rights?limit=200', row => row.key);
    this.tiers.set(rights.map(x => /^chat\.tier\.([1-9]\d*)$/.exec(x.key)).filter(x => x !== null && x[1] !== '99').map(x => Number(x![1])).sort((a, b) => a - b));
  }
  title(row: DecisionRow): string {
    return row.kind === 'access' ? 'Sign-up' : row.kind === 'tier' ? `Model request · ${row.title || 'Tier ' + row.tier}` : row.kind === 'skill' ? `Skill request · ${row.title || row.skill}` : row.action === 'safety.flag' ? 'Safety flag' : row.action || 'Job approval';
  }
  select(row: DecisionRow): void { this.selected.set(row); this.note = ''; this.tier = undefined; }
  async decide(approved: boolean): Promise<void> {
    const row = this.selected(); if (!row || this.busy() || approved && row.kind === 'access' && !this.tier) return;
    this.busy.set(true); this.error.set('');
    try {
      if (row.kind === 'approval') await this.request()('/admin/approvals/' + encodeURIComponent(row.id) + '/decision', 'POST', { approved, note: this.note });
      else await this.request()('/admin/' + row.kind + '-requests/' + encodeURIComponent(row.id) + (approved ? '/approve' : '/reject'), 'POST', row.kind === 'access' && approved ? { tier: this.tier } : {});
      await this.loadDecisions();
    } catch (e) { this.failure(e); } finally { this.busy.set(false); }
  }
  async loadRights(): Promise<void> {
    const [persons, rights, skills, grants] = await Promise.all([
      this.pages<Person>('/admin/people?limit=200', row => row.user_id), this.pages<{ key: string }>('/admin/rights?limit=200', row => row.key),
      this.request()<{ name: string; title: string; right: string }[]>('/admin/skills?limit=200'), this.pages<Grant>('/admin/grants?limit=200', row => row.id)
    ]);
    this.persons.set(persons); this.grants.set(grants); this.changes.set({});
    this.columns.set([...rights.filter(x => /^chat\.tier\.[1-9]\d*$/.test(x.key) && x.key !== 'chat.tier.99').sort((a, b) => Number(a.key.slice(10)) - Number(b.key.slice(10))).map(x => ({ key: x.key, title: 'Tier ' + x.key.slice(10) })), ...skills.map(x => ({ key: x.right, title: x.title }))]);
  }
  grant(user: string, right: string): Grant | undefined { return this.grants().find(x => x.right_key === right && (user ? x.subject_type === 'user' && x.subject_id === user : x.subject_type === 'everyone')); }
  cell(user: string, right: string): string { return JSON.stringify([user, right]); }
  checked(user: string, right: string): boolean { return this.changes()[this.cell(user, right)]?.checked ?? !!this.grant(user, right); }
  toggle(user: string, right: string, checked: boolean): void {
    this.changes.update(current => { const next = { ...current }; const key = this.cell(user, right); if (checked === !!this.grant(user, right)) delete next[key]; else next[key] = { user, right, checked }; return next; });
  }
  changeCount(): number { return Object.keys(this.changes()).length; }
  async saveRights(): Promise<void> {
    if (this.busy()) return; this.busy.set(true); this.error.set('');
    try {
      for (const [key, change] of Object.entries(this.changes())) {
        const grant = this.grant(change.user, change.right);
        if (change.checked) {
          const created = await this.request()<Grant>('/admin/grants', 'POST', { right_key: change.right, subject_type: change.user ? 'user' : 'everyone', ...(change.user ? { subject_id: change.user } : {}) });
          this.grants.update(rows => [...rows, created]);
        } else if (grant) { await this.request()('/admin/grants/' + encodeURIComponent(grant.id), 'DELETE'); this.grants.update(rows => rows.filter(x => x.id !== grant.id)); }
        this.changes.update(current => { const next = { ...current }; delete next[key]; return next; });
      }
    } catch (e) { this.failure(e); } finally { this.busy.set(false); }
  }
  async filter(append = false): Promise<void> {
    this.error.set('');
    try {
      const query = new URLSearchParams({ limit: '200' });
      if (this.requestId.trim()) query.set('correlation_id', this.requestId.trim());
      if (this.person.trim()) query.set('user_id', this.person.trim());
      if (this.action.trim()) query.set('action', this.action.trim());
      if (append && this.trail().length) query.set('before_id', String(Math.min(...this.trail().map(x => x.id))));
      const rows = await this.request()<TrailRow[]>('/admin/trail?' + query.toString());
      this.more.set(rows.length === 200); this.trail.set(append ? [...this.trail(), ...rows] : rows);
    } catch (e) { this.failure(e); }
  }
  async trace(id: string): Promise<void> {
    this.requestId = id; this.person = ''; this.action = ''; this.inTrace.set(true); await this.filter();
    while (this.more() && !this.error()) await this.filter(true);
    this.trail.update(rows => [...rows].sort((a, b) => a.occurred_at.localeCompare(b.occurred_at) || a.id - b.id));
  }
  async loadDeadLetters(append = false): Promise<void> {
    this.error.set('');
    try {
      const query = new URLSearchParams({ limit: '200' });
      if (this.topic) query.set('topic', this.topic);
      const last = this.deadLetters().at(-1);
      if (append && last) query.set('before', last.received_at + ',' + last.id);
      const rows = await this.request()<DeadLetter[]>('/admin/dead-letters?' + query.toString());
      this.deadMore.set(rows.length === 200); this.deadLetters.set(append ? [...this.deadLetters(), ...rows] : rows);
    } catch (e) { this.failure(e); }
  }
  selectDeadLetter(row: DeadLetter): void { this.deadLetter.set(row); this.confirmReplay.set(false); this.replayResult.set(''); }
  replayReason(row: DeadLetter): string { return row.topic === 'dlq.chat.messages' ? 'Chat dead letters contain IDs only.' : 'The original message needs valid JSON and a request ID.'; }
  original(row: DeadLetter): string { try { return this.json(JSON.parse(row.original_message)); } catch { return row.original_message; } }
  async copyRequest(id: string): Promise<void> { try { await navigator.clipboard.writeText(id); } catch { this.error.set('Could not copy. Select and copy the request ID.'); } }
  async replay(): Promise<void> {
    const row = this.deadLetter(); if (!row?.replayable || !this.confirmReplay() || this.busy()) return;
    this.busy.set(true); this.replayResult.set(''); this.confirmReplay.set(false);
    try {
      const result = await this.request()<{ outcome: string }>('/admin/dead-letters/' + encodeURIComponent(row.id) + '/replay', 'POST', {});
      this.replayResult.set(result.outcome === 'sent' ? 'Replay sent. The job will update when processing finishes.' : 'Replay failed.');
    } catch (e) { this.replayResult.set(e instanceof Error ? e.message : 'Replay failed.'); }
    finally {
      await this.loadDeadLetters();
      while (this.deadMore() && !this.error() && !this.deadLetters().some(x => x.id === row.id)) await this.loadDeadLetters(true);
      this.deadLetter.set(this.deadLetters().find(x => x.id === row.id) ?? row); this.busy.set(false);
    }
  }
  async openTrace(id: string): Promise<void> {
    const sequence = ++this.traceSequence;
    this.traceMessage.set(''); this.traceSpans.set([]); this.selectedSpan.set(null); this.traceLoading.set(true);
    try {
      const result = await this.request()<{ trace_id: string; spans: Span[] }>('/admin/traces/' + encodeURIComponent(id));
      if (sequence !== this.traceSequence) return;
      const spans = [...result.spans].sort((a, b) => Date.parse(a.start) - Date.parse(b.start));
      const begin = Math.min(...spans.map(x => Date.parse(x.start))); const end = Math.max(...spans.map(x => Date.parse(x.start) + x.duration_ms));
      const total = Math.max(end - begin, 0.001); const byId = new Map(spans.map(x => [x.span_id, x]));
      this.traceSpans.set(spans.map(span => {
        let parent = span.parent_span_id; let depth = 0; const seen = new Set([span.span_id]);
        while (parent && byId.has(parent) && !seen.has(parent)) { seen.add(parent); depth++; parent = byId.get(parent)!.parent_span_id; }
        return { span, depth, offset: (Date.parse(span.start) - begin) / total * 100, width: Math.max(span.duration_ms / total * 100, 0.2) };
      }));
      if (!spans.length) this.traceMessage.set('This trace has expired');
    } catch (e) {
      if (sequence === this.traceSequence) this.traceMessage.set(e instanceof Error && /trace_not_found|expired/i.test(e.message) ? 'This trace has expired' : 'Tracing is unavailable');
    } finally { if (sequence === this.traceSequence) this.traceLoading.set(false); }
  }
  json(value: unknown): string { return JSON.stringify(value, null, 2); }
  figure(n: number | null | undefined): string { return n == null ? '—' : n.toLocaleString('en-US', { maximumFractionDigits: 6 }); }
  private failure(e: unknown): void { this.error.set(e instanceof Error ? e.message : 'The request failed. Try again.'); }
}
