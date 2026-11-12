// SPDX-License-Identifier: AGPL-3.0-only
import { TestBed } from '@angular/core/testing';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { Operations, Request, DecisionRow, TrailRow } from './operations';
import { connectionSummary } from './models';
afterEach(() => vi.restoreAllMocks());
async function create(screen: string, request: Request = vi.fn().mockResolvedValue([])) {
  await TestBed.configureTestingModule({ imports: [Operations] }).compileComponents();
  const fixture = TestBed.createComponent(Operations);
  fixture.componentRef.setInput('request', request); fixture.componentRef.setInput('screen', screen);
  fixture.detectChanges(); await fixture.whenStable(); return { fixture, app: fixture.componentInstance };
}
const row: DecisionRow = { id: 'synthetic-request', kind: 'approval', action: 'safety.flag', requester_user_id: 'synthetic-user', status: 'pending', details: { excerpt: '<script>synthetic excerpt</script>', scores: { personal_data: 0.9 } } };
describe('Stage 3 admin screens', () => {
  it('shows overview numbers and unavailable figures as dashes', async () => {
    const request = vi.fn().mockResolvedValue({ people_active_today: null, people_approved: 7, skill_jobs_today: 3, model_calls_today: 4, cost_today_usd: null, needs_attention: [], health: [{ name: 'synthetic-service', status: 'down', checked_at: null }] });
    const { fixture } = await create('overview', request); const text = fixture.nativeElement.textContent;
    expect(text).toContain('of 7 approved'); expect(text).toContain('3'); expect(text).toContain('4'); expect(text.match(/—/g)).toHaveLength(3); expect(text).toContain('Down'); expect(request).toHaveBeenCalledWith('/admin/overview');
  });
  it('links attention items to their screen', async () => {
    const request = vi.fn().mockResolvedValue({ people_active_today: 0, people_approved: 0, skill_jobs_today: 0, model_calls_today: 0, cost_today_usd: 0, needs_attention: [{ kind: 'model_down', title: 'Model down', detail: 'Synthetic', at: '2026-11-11', link: '#models' }], health: [] });
    const { fixture, app } = await create('overview', request); const navigate = vi.spyOn(app.navigate, 'emit'); fixture.nativeElement.querySelector('a').click(); expect(navigate).toHaveBeenCalledWith('models');
  });
  it('combines all decision kinds and excludes the reserved tier', async () => {
    const request = vi.fn().mockImplementation(async (path: string) => path.startsWith('/admin/rights') ? [{ key: 'chat.tier.1' }, { key: 'chat.tier.99' }] : [{ ...row, action: undefined, created_at: '2026-11-11T00:00:00Z' }]);
    const { fixture, app } = await create('approvals', request); expect(app.decisions().map(x => x.kind).sort()).toEqual(['access', 'approval', 'skill', 'tier']); expect(app.tiers()).toEqual([1]);
    for (const label of ['Sign-up', 'Skill request', 'Model request']) expect(fixture.nativeElement.textContent).toContain(label);
  });
  it('renders safety excerpts safely and sends Clear false and Confirm problem true', async () => {
    const request = vi.fn().mockResolvedValue([]); const { fixture, app } = await create('approvals', request); app.select(row); fixture.detectChanges();
    for (const label of ['Clear', 'Confirm problem', '<script>synthetic excerpt</script>']) expect(fixture.nativeElement.textContent).toContain(label); expect(fixture.nativeElement.querySelector('script')).toBeNull();
    app.note = 'Synthetic note'; await app.decide(false); expect(request).toHaveBeenCalledWith('/admin/approvals/synthetic-request/decision', 'POST', { approved: false, note: 'Synthetic note' });
    app.select(row); await app.decide(true); expect(request).toHaveBeenCalledWith('/admin/approvals/synthetic-request/decision', 'POST', { approved: true, note: '' });
  });
  it('uses job Deny, requires a tier for sign-ups and routes skill and model decisions', async () => {
    const request = vi.fn().mockResolvedValue([]); const { fixture, app } = await create('approvals', request);
    app.select({ ...row, action: 'skill.synthetic' }); fixture.detectChanges(); expect(fixture.nativeElement.textContent).toContain('Deny');
    app.select({ ...row, kind: 'access', action: undefined }); const count = request.mock.calls.length; await app.decide(true); expect(request.mock.calls).toHaveLength(count);
    app.tier = 2; await app.decide(true); expect(request).toHaveBeenCalledWith('/admin/access-requests/synthetic-request/approve', 'POST', { tier: 2 });
    for (const kind of ['tier', 'skill']) { app.select({ ...row, kind, action: undefined }); await app.decide(false); expect(request).toHaveBeenCalledWith('/admin/' + kind + '-requests/synthetic-request/reject', 'POST', {}); }
  });
  it('retains a failed decision for retry', async () => {
    const request = vi.fn().mockResolvedValue([]); const { app } = await create('approvals', request); app.select(row); request.mockRejectedValueOnce(new Error('Synthetic error')); await app.decide(false); expect(app.selected()).toEqual(row); expect(app.error()).toBe('Synthetic error');
  });
  it('loads the matrix and changes grants only after Save', async () => {
    const request = vi.fn().mockImplementation(async (path: string, method?: string) => method === 'POST' ? { id: 'created', right_key: 'skill.synthetic', subject_type: 'user', subject_id: 'synthetic-user' } : path.startsWith('/admin/people') ? [{ user_id: 'synthetic-user', name: 'Synthetic User' }] : path.startsWith('/admin/rights') ? [{ key: 'chat.tier.1' }] : path.startsWith('/admin/skills') ? [{ right: 'skill.synthetic', title: 'Synthetic skill' }] : [{ id: 'everyone', right_key: 'chat.tier.1', subject_type: 'everyone' }]);
    const { fixture, app } = await create('rights', request); expect(fixture.nativeElement.textContent).toContain('Everyone'); expect(app.columns()).toHaveLength(2);
    app.toggle('synthetic-user', 'skill.synthetic', true); app.toggle('', 'chat.tier.1', false); expect(request.mock.calls.filter(x => x[1])).toHaveLength(0); await app.saveRights();
    expect(request).toHaveBeenCalledWith('/admin/grants', 'POST', { right_key: 'skill.synthetic', subject_type: 'user', subject_id: 'synthetic-user' }); expect(request).toHaveBeenCalledWith('/admin/grants/everyone', 'DELETE'); expect(app.changeCount()).toBe(0);
  });
  it('retains only unsaved grant changes after a partial failure', async () => {
    const request = vi.fn().mockResolvedValue([]); const { app } = await create('rights', request); app.toggle('', 'skill.one', true); app.toggle('', 'skill.two', true);
    request.mockResolvedValueOnce({ id: 'one', right_key: 'skill.one', subject_type: 'everyone' }).mockRejectedValueOnce(new Error('Synthetic conflict')); await app.saveRights(); expect(app.changeCount()).toBe(1); expect(app.checked('', 'skill.one')).toBe(true);
  });
  it('sends full request ID, person and action filters', async () => {
    const request = vi.fn().mockResolvedValue([]); const { app } = await create('audit', request); app.requestId = '00000000-0000-4000-8000-000000000001'; app.person = 'synthetic-user'; app.action = 'skill.requested'; await app.filter();
    expect(request).toHaveBeenLastCalledWith('/admin/trail?limit=200&correlation_id=00000000-0000-4000-8000-000000000001&user_id=synthetic-user&action=skill.requested');
  });
  it('opens all request trail pages in time order', async () => {
    const request = vi.fn().mockResolvedValue([]); const { app } = await create('audit', request);
    const rows = Array.from({ length: 200 }, (_, n) => ({ id: n + 2, occurred_at: '2026-11-11T02:00:00Z', correlation_id: 'synthetic-request' } as TrailRow));
    request.mockResolvedValueOnce(rows).mockResolvedValueOnce([{ id: 1, occurred_at: '2026-11-11T01:00:00Z', correlation_id: 'synthetic-request' }]); await app.trace('synthetic-request'); expect(app.trail()).toHaveLength(201); expect(app.trail()[0].id).toBe(1); expect(request).toHaveBeenLastCalledWith('/admin/trail?limit=200&correlation_id=synthetic-request&before_id=2');
  });
  it('formats a classification score', () => { expect(connectionSummary({ ok: true, model_title: 'Synthetic', reply: '', duration_ms: 1234, score: 0.9, usage: { input_tokens: 1, output_tokens: 1 }, cost_usd: 0 })).toBe('Works · 1.2 s · score 0.9'); });
  it('shows the local greeting and readable Overview times without refetching on display input changes', async () => {
    vi.useFakeTimers({ toFake: ['Date'] }); vi.setSystemTime(new Date('2026-11-11T13:55:46Z'));
    try {
      const request = vi.fn().mockResolvedValue({ people_active_today: 1, people_approved: 2, skill_jobs_today: 0, model_calls_today: 0, cost_today_usd: 0, needs_attention: [{ kind: 'dead_letter', title: 'Failed messages', detail: 'Synthetic error', at: '2026-11-11T13:09:06Z', link: '#overview' }], health: [{ name: 'synthetic-service', status: 'ok', checked_at: '2026-11-11T13:55:46Z' }] });
      const { fixture } = await create('overview', request); fixture.componentRef.setInput('givenName', 'Synthetic'); fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('h1').textContent).toBe('Good evening, Synthetic.');
      expect(fixture.nativeElement.textContent).toContain('11 Nov 21:09:06'); expect(fixture.nativeElement.textContent).toContain('11 Nov 21:55:46');
      expect(fixture.nativeElement.textContent).not.toContain('2026-11-11T');
      fixture.componentRef.setInput('timeZone', 'UTC'); fixture.detectChanges(); expect(fixture.nativeElement.querySelector('h1').textContent).toBe('Good afternoon, Synthetic.');
      expect(request).toHaveBeenCalledTimes(1);
    } finally { vi.useRealTimers(); }
  });
  it('formats approval and audit timestamps and shows the known person with an id tooltip', async () => {
    const request = vi.fn().mockResolvedValue([]); const { fixture, app } = await create('approvals', request);
    app.decisions.set([{ ...row, created_at: '2026-11-11T13:55:46Z' }]); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('11 Nov 21:55:46'); expect(fixture.nativeElement.textContent).not.toContain('(UTC)');
    fixture.componentRef.setInput('screen', 'audit'); fixture.detectChanges(); await fixture.whenStable();
    app.trail.set([{ id: 1, occurred_at: '2026-11-11T13:55:46.453Z', user_id: 'synthetic-id', person: 'Synthetic Person', producer: 'synthetic', correlation_id: 'synthetic-request', actor: 'synthetic', action: 'synthetic', target: 'synthetic', outcome: 'ok' }]); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('11 Nov 21:55:46.453'); expect(fixture.nativeElement.textContent).not.toContain('(UTC)');
    expect(fixture.nativeElement.querySelector('td[title="synthetic-id"]').textContent).toBe('Synthetic Person');
  });

});

describe('Stage 4 recovery and tracing', () => {
  const letter = { id: 'synthetic-letter', topic: 'dlq.skill.requests.slides', error_code: 'worker_gave_up', error_message: 'Synthetic failure', received_at: '2026-11-12T00:00:00Z', correlation_id: 'synthetic-request', original_message: '{"text":"<script>marker</script>"}', replay_count: 0, replayable: true, replay_history: [] };
  it('filters and pages failed messages, safely shows details and asks before replay', async () => {
    const request = vi.fn().mockResolvedValue([letter]); const { fixture, app } = await create('failed-messages', request);
    app.selectDeadLetter(letter); fixture.detectChanges(); expect(fixture.nativeElement.querySelector('script')).toBeNull(); expect(fixture.nativeElement.textContent).toContain('<script>marker</script>');
    await app.replay(); expect(request.mock.calls.filter(x => x[1] === 'POST')).toHaveLength(0);
    const button = Array.from(fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>).find(x => x.textContent === 'Replay')!; button.click(); fixture.detectChanges(); expect(fixture.nativeElement.textContent).toContain('Send this original message again?');
    request.mockResolvedValueOnce({ outcome: 'sent' }).mockResolvedValueOnce([{ ...letter, replay_count: 1, replay_history: [{ id: 'replay', replayed_at: '2026-11-12T00:00:00Z', replayed_by: 'synthetic-admin', target_topic: 'skill.requests.slides', outcome: 'sent' }] }]);
    await app.replay(); fixture.detectChanges(); expect(request).toHaveBeenCalledWith('/admin/dead-letters/synthetic-letter/replay', 'POST', {}); expect(fixture.nativeElement.textContent).toContain('Replay sent'); expect(fixture.nativeElement.textContent).toContain('synthetic-admin');
    app.topic = letter.topic; await app.loadDeadLetters(); expect(request).toHaveBeenLastCalledWith('/admin/dead-letters?limit=200&topic=dlq.skill.requests.slides');
    await app.loadDeadLetters(true); expect(request.mock.calls.at(-1)![0]).toContain('before=2026-11-12T00%3A00%3A00Z%2Csynthetic-letter');
  });
  it('refreshes replay history for a selected message beyond the first page', async () => {
    const request = vi.fn().mockResolvedValue([]); const { app } = await create('failed-messages', request);
    app.selectDeadLetter(letter); app.confirmReplay.set(true);
    const newer = Array.from({ length: 200 }, (_, i) => ({ ...letter, id: 'newer-' + i }));
    request.mockResolvedValueOnce({ outcome: 'sent' }).mockResolvedValueOnce(newer).mockResolvedValueOnce([{ ...letter, replay_count: 1, replay_history: [{ id: 'replay', outcome: 'sent' }] }]);
    await app.replay(); expect(app.deadLetter()?.replay_count).toBe(1); expect(app.deadLetter()?.replay_history).toHaveLength(1); expect(request.mock.calls.at(-1)![0]).toContain('before=');
  });
  it('disables replay with a reason and retains a failed replay result', async () => {
    const request = vi.fn().mockResolvedValue([letter]); const { fixture, app } = await create('failed-messages', request);
    app.selectDeadLetter({ ...letter, topic: 'dlq.chat.messages', replayable: false }); fixture.detectChanges();
    const button = Array.from(fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>).find(x => x.textContent === 'Replay')!; expect(button.disabled).toBe(true); expect(fixture.nativeElement.textContent).toContain('IDs only');
    app.selectDeadLetter(letter); app.confirmReplay.set(true); request.mockRejectedValueOnce(new Error('Kafka is unavailable')).mockResolvedValueOnce([letter]); await app.replay(); fixture.detectChanges(); expect(fixture.nativeElement.textContent).toContain('Kafka is unavailable'); expect(app.busy()).toBe(false);
  });
  it('draws parent indentation and duration bars and exposes attributes on click', async () => {
    const request = vi.fn().mockResolvedValue([]); const { fixture, app } = await create('audit', request);
    const parent = { span_id: 'parent', service: 'harness-api', name: 'POST /chat', kind: 'SPAN_KIND_SERVER', start: '2026-11-12T00:00:00Z', duration_ms: 20, status: 'ok', attributes: {} };
    const child = { ...parent, span_id: 'child', parent_span_id: 'parent', service: 'control-centre', start: '2026-11-12T00:00:00.005Z', duration_ms: 5, status: 'error', attributes: { 'ooh.tier': 1 } };
    request.mockResolvedValueOnce({ trace_id: 'trace', spans: [child, parent] }); await app.openTrace('trace'); fixture.detectChanges();
    expect(app.traceSpans().map(x => x.depth)).toEqual([0, 1]); expect(app.traceSpans()[1].offset).toBe(25); expect(app.traceSpans()[1].width).toBe(25); expect(fixture.nativeElement.querySelectorAll('.timeline-bar')).toHaveLength(2);
    const childButton = Array.from(fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>).find(x => x.textContent?.includes('control-centre'))!; childButton.click(); fixture.detectChanges(); expect(fixture.nativeElement.textContent).toContain('ooh.tier'); expect(fixture.nativeElement.textContent).toContain('Error');
  });
  it('keeps the audit rows when traces expire or tracing is unavailable', async () => {
    const request = vi.fn().mockResolvedValue([]); const { fixture, app } = await create('audit', request);
    app.trail.set([{ id: 1, occurred_at: '', producer: 'synthetic', correlation_id: 'synthetic', user_id: 'synthetic', actor: 'synthetic', action: 'synthetic', target: '', outcome: 'ok', trace_id: 'trace' }]);
    request.mockRejectedValueOnce(new Error('This trace has expired')); await app.openTrace('trace'); fixture.detectChanges(); expect(fixture.nativeElement.textContent).toContain('This trace has expired'); expect(app.trail()).toHaveLength(1);
    request.mockRejectedValueOnce(new Error('Unavailable')); await app.openTrace('trace'); expect(app.traceMessage()).toBe('Tracing is unavailable'); expect(app.trail()).toHaveLength(1);
  });
  it('links dead-letter attention to Failed messages', async () => {
    const request = vi.fn().mockResolvedValue({ people_active_today: 0, people_approved: 0, needs_attention: [{ kind: 'dead_letter', title: 'Failed messages', at: '', detail: '1', link: '#failed-messages' }], health: [] });
    const { fixture, app } = await create('overview', request); const navigate = vi.spyOn(app.navigate, 'emit'); fixture.nativeElement.querySelector('a').click(); expect(navigate).toHaveBeenCalledWith('failed-messages');
  });
});
