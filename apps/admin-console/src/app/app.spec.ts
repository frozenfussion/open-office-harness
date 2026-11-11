// SPDX-License-Identifier: AGPL-3.0-only
import { TestBed } from '@angular/core/testing';
import { OidcSecurityService } from 'angular-auth-oidc-client';
import { of } from 'rxjs';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { App } from './app';
import { ConnectionResult, ModelEntry, modelPayload, settingsObject, tierRows } from './models';
const model: ModelEntry = { model_entry_id: 'synthetic', title: 'Synthetic', purpose: 'chat', tier: 1, role: 'main', location: 'cloud', api_type: 'openai_responses', endpoint_url: 'https://synthetic.invalid', model_id: 'synthetic', has_key: true, priority: 100, rate_limit_per_minute: 10, daily_budget: 0, input_price_per_million: 0, output_price_per_million: 0, timeout_seconds: 120, request_settings: {} };
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); sessionStorage.removeItem('ooh-admin-signin-screen'); window.history.replaceState(null, '', window.location.pathname + window.location.search); });
describe('Model settings and rights', () => {
  it('rejects arrays, null and scalar request settings', () => {
    for (const value of ['[]', 'null', 'true', '1', '"text"', '{']) expect(() => settingsObject(value)).toThrow();
    expect(settingsObject('{"temperature":null}')).toEqual({ temperature: null });
  });
  it('never sends fetched metadata or a saved key back to the API', () => {
    const payload = modelPayload({ ...model, health: 'unknown', secret_ref: '', created_at: 'synthetic' } as ModelEntry, '', false, '{}');
    for (const key of ['model_entry_id', 'has_key', 'health', 'created_at', 'api_key', 'secret_ref']) expect(payload).not.toHaveProperty(key);
    expect(modelPayload(model, 'replacement', false, '{}')['api_key']).toBe('replacement');
    expect(modelPayload(model, '', true, '{}')['api_key']).toBe('');
    expect(modelPayload({ ...model, purpose: 'classification' }, '', false, '{}')).not.toHaveProperty('tier');
  });
  it('accepts a blank thinking-off setting or an object, rejecting other JSON', () => {
    expect(modelPayload(model, '', false, '{}', '  ')['request_settings_thinking_off']).toBeNull();
    expect(modelPayload(model, '', false, '{}', '{}')['request_settings_thinking_off']).toEqual({});
    expect(modelPayload(model, '', false, '{}', '{"reasoning":{"effort":"low"}}')['request_settings_thinking_off']).toEqual({ reasoning: { effort: 'low' } });
    for (const value of ['[]', 'null', 'true', '1', '"text"', '{']) expect(() => modelPayload(model, '', false, '{}', value)).toThrow();
  });
  it('keeps grant-only tiers visible and hides tier 99', () => {
    expect(tierRows([model, { ...model, tier: 99 }], [{ id: 'grant', right_key: 'chat.tier.4', subject_type: 'everyone' }, { id: 'check', right_key: 'chat.tier.99', subject_type: 'user' }])).toEqual([1, 4]);
  });
});
describe('Admin console', () => {
  async function create(admin: boolean, authenticated = true, userData: object = {}, issuer = 'https://issuer.invalid') {
    const auth = { checkAuth: () => of({ isAuthenticated: authenticated, userData }), authorize: vi.fn(), logoff: () => of({}), getAccessToken: () => of('synthetic-token'), getPayloadFromAccessToken: vi.fn(() => of({ realm_access: { roles: admin ? ['ooh-admin'] : ['ooh-user'] } })) };
    window.oohConfig = { apiBase: '/api', issuer, clientId: 'ooh-admin-console' };
    vi.spyOn(App.prototype, 'load').mockResolvedValue();
    await TestBed.configureTestingModule({ imports: [App], providers: [{ provide: OidcSecurityService, useValue: auth }] }).compileComponents();
    const fixture = TestBed.createComponent(App); fixture.componentInstance.screen.set('models'); fixture.detectChanges(); return { fixture, auth };
  }
  it('opens the console for an access-token administrator without userinfo roles', async () => {
    const { fixture, auth } = await create(true);
    expect(auth.getPayloadFromAccessToken).toHaveBeenCalled();
    expect(fixture.componentInstance.admin()).toBe(true);
    expect(fixture.nativeElement.textContent).toContain('Add model');
    expect(fixture.nativeElement.textContent).not.toContain('This console is for administrators.');
    expect(App.prototype.load).toHaveBeenCalled();
  });
  it('ignores administrator roles in userinfo when the access token has none', async () => {
    const { fixture } = await create(false, true, { realm_access: { roles: ['ooh-admin'] } });
    expect(fixture.componentInstance.admin()).toBe(false);
    expect(App.prototype.load).not.toHaveBeenCalled();
  });
  it('shows the administrator refusal and sign-out', async () => {
    const { fixture } = await create(false);
    expect(fixture.nativeElement.textContent).toContain('This console is for administrators.');
    expect(fixture.nativeElement.textContent).toContain('Sign out');
    expect(fixture.nativeElement.textContent).not.toContain('Add model');
  });
  it('starts company sign-in without password fields', async () => {
    const { fixture, auth } = await create(false, false);
    fixture.nativeElement.querySelector('button').click(); expect(auth.authorize).toHaveBeenCalled();
    expect(fixture.nativeElement.querySelector('input[type=password]')).toBeNull();
  });
  it('opens an empty key field for an existing entry and shows grant-only tiers', async () => {
    const { fixture } = await create(true); const app = fixture.componentInstance;
    app.models.set([model]); app.grants.set([{ id: 'g', right_key: 'chat.tier.4', subject_type: 'everyone' }]);
    app.edit(model); fixture.detectChanges();
    const input = fixture.nativeElement.querySelector('input[name=key]') as HTMLInputElement;
    expect(input.value).toBe(''); expect(input.placeholder).toBe('Saved · type to replace');
    expect(fixture.nativeElement.textContent).toContain('No model yet');
  });
  it('reads every model page and sorts the display', async () => {
    const { fixture } = await create(true); const app = fixture.componentInstance;
    vi.mocked(App.prototype.load).mockRestore();
    const first = Array.from({ length: 200 }, (_, i) => ({ ...model, model_entry_id: 'synthetic-' + i, purpose: 'z-purpose' }));
    const request = vi.spyOn(app, 'request').mockResolvedValueOnce(first)
      .mockResolvedValueOnce([{ ...model, purpose: 'a-purpose' }]).mockResolvedValueOnce([]).mockResolvedValueOnce({ count: 0 }).mockResolvedValueOnce({ count: 0 }).mockResolvedValueOnce({ count: 0 }).mockResolvedValueOnce([]);
    await app.load();
    expect(request).toHaveBeenNthCalledWith(2, '/admin/models?limit=200&after=synthetic-199');
    expect(app.models()).toHaveLength(201); expect(app.models()[0].purpose).toBe('a-purpose');
  });

  it('disables connection tests without a saved key', async () => {
    const { fixture } = await create(true); const app = fixture.componentInstance;
    app.models.set([{ ...model, has_key: false }]); fixture.detectChanges();
    const button = fixture.nativeElement.querySelector('button[title="Save a key first"]') as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.nextElementSibling?.classList.contains('ooh-help')).toBe(true);
    expect(button.nextElementSibling?.textContent).toBe('Save a key first');
    const request = vi.spyOn(app, 'request'); await app.testConnection({ ...model, has_key: false }); expect(request).not.toHaveBeenCalled();
  });
  it('shows Testing then formats the successful result beneath the row', async () => {
    const { fixture } = await create(true); const app = fixture.componentInstance;
    app.models.set([model]);
    let finish!: (result: ConnectionResult) => void;
    const pending = new Promise<ConnectionResult>(resolve => { finish = resolve; });
    const request = vi.spyOn(app, 'request').mockReturnValueOnce(pending).mockResolvedValueOnce([{ ...model, health: 'ok' }]);
    const test = app.testConnection(model); fixture.detectChanges();
    const button = fixture.nativeElement.querySelector('button[title="One short paid call to this model only"]') as HTMLButtonElement;
    expect(button.disabled).toBe(true); expect(button.textContent).toContain('Testing…');
    finish({ ok: true, model_title: 'Synthetic', reply: 'a'.repeat(90), duration_ms: 1234, usage: { input_tokens: 2, output_tokens: 1 }, cost_usd: 0.000123 });
    await test; fixture.detectChanges();
    expect(request).toHaveBeenCalledWith('/admin/models/synthetic/test', 'POST', {}, expect.any(AbortSignal));
    expect(button.disabled).toBe(false);
    expect(fixture.nativeElement.querySelector('[role=status]').textContent).toBe('Works · 1.2 s · reply: "' + 'a'.repeat(80) + '" · 2/1 tokens · $0.000123');
  });
  it('shows the failure and provider detail as plain text', async () => {
    const { fixture } = await create(true); const app = fixture.componentInstance;
    app.models.set([model]);
    vi.spyOn(app, 'request').mockResolvedValueOnce({ ok: false, reason: 'key refused', provider_status: 401, provider_message: '<img src=x onerror=alert(1)>' }).mockResolvedValueOnce([{ ...model, health: 'down' }]);
    await app.testConnection(model); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role=status]').textContent).toBe('Failed · key refused (provider answered 401) · <img src=x onerror=alert(1)>');
    expect(fixture.nativeElement.querySelector('img')).toBeNull();
  });
  it('aborts the browser wait at the entry timeout plus fifteen seconds', async () => {
    const { fixture } = await create(true); const app = fixture.componentInstance;
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn((url: string, init: RequestInit) => url.includes('/test') ? new Promise((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    }) : Promise.resolve({ ok: true, json: async () => [{ ...model, health: 'down' }] })));
    const test = app.testConnection({ ...model, timeout_seconds: 10 });
    await vi.advanceTimersByTimeAsync(24999); expect(app.testing().has(model.model_entry_id)).toBe(true);
    await vi.advanceTimersByTimeAsync(1); await test;
    expect(app.testResults()[model.model_entry_id]).toEqual({ ok: false, reason: 'took longer than its time limit', provider_status: null, provider_message: null });
    expect(app.testing().size).toBe(0);
  });

  it.each([true, false])('refreshes the row health after a connection test (works: %s) and preserves its result', async ok => {
    const { fixture } = await create(true); const app = fixture.componentInstance;
    const entry: ModelEntry = { ...model, purpose: 'classification', tier: undefined, health: 'unknown' };
    app.models.set([entry]); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.ooh-chip').textContent).toBe('Unknown');
    const result: ConnectionResult = ok
      ? { ok: true, model_title: 'Synthetic', reply: '', duration_ms: 400, usage: { input_tokens: 0, output_tokens: 0 }, cost_usd: 0, score: 1 }
      : { ok: false, reason: 'unavailable', provider_status: 503, provider_message: null };
    const request = vi.spyOn(app, 'request').mockResolvedValueOnce(result).mockResolvedValueOnce([{ ...entry, health: ok ? 'ok' : 'down' }]);
    await app.testConnection(entry); fixture.detectChanges();
    expect(request).toHaveBeenNthCalledWith(2, '/admin/models?limit=200');
    expect(request).toHaveBeenCalledTimes(2);
    expect(fixture.nativeElement.querySelector('.ooh-chip').textContent).toBe(ok ? 'OK' : 'Down');
    expect(fixture.nativeElement.querySelector('[role=status]').textContent).toContain(ok ? 'Works · 0.4 s · score 1' : 'Failed · unavailable');
  });
  it.each(['ok', 'unknown'] as const)('retries unchanged health once after two seconds, ending at %s without polling', async health => {
    const { fixture } = await create(true); const app = fixture.componentInstance;
    vi.useFakeTimers();
    const entry: ModelEntry = { ...model, health: 'unknown' }; app.models.set([entry]);
    const result: ConnectionResult = { ok: true, model_title: 'Synthetic', reply: 'yes', duration_ms: 400, usage: { input_tokens: 1, output_tokens: 1 }, cost_usd: 0 };
    const request = vi.spyOn(app, 'request').mockResolvedValueOnce(result).mockResolvedValueOnce([entry]).mockResolvedValueOnce([{ ...entry, health }]);
    const test = app.testConnection(entry);
    await vi.advanceTimersByTimeAsync(0); fixture.detectChanges();
    expect(request).toHaveBeenCalledTimes(2);
    expect(fixture.nativeElement.querySelector('[role=status]').textContent).toContain('Works');
    await vi.advanceTimersByTimeAsync(1999); expect(request).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1); await test; fixture.detectChanges();
    expect(request).toHaveBeenNthCalledWith(3, '/admin/models?limit=200');
    expect(fixture.nativeElement.querySelector('.ooh-chip').textContent).toBe(health === 'ok' ? 'OK' : 'Unknown');
    expect(fixture.nativeElement.querySelector('[role=status]').textContent).toContain('Works');
    await vi.advanceTimersByTimeAsync(10000); expect(request).toHaveBeenCalledTimes(3);
  });

  const accessRow = { id: 'request-synthetic', user_id: 'user-synthetic', name: '<img src=x>', email: 'synthetic@example.invalid', organisation: 'Synthetic team', reason: '<script>test</script>', status: 'pending' as const, requested_at: '2026-11-10T00:00:00Z' };
  it('links non-admins to the configured Workspace', async () => {
    const { fixture } = await create(false, true, {}, 'https://auth.synthetic.invalid/realms/ooh');
    expect(fixture.nativeElement.querySelector('a').href).toBe('https://harness.synthetic.invalid/');
  });



  it('restores thinking-off JSON for editing and clears it for a new model', async () => {
    const { fixture } = await create(true); const app = fixture.componentInstance;
    app.edit({ ...model, request_settings_thinking_off: { reasoning: { effort: 'low' } } }); fixture.detectChanges();
    expect(JSON.parse(app.thinkingOff)).toEqual({ reasoning: { effort: 'low' } });
    expect(fixture.nativeElement.querySelector('textarea[name=thinkingOff]')).not.toBeNull();
    app.edit({ ...model, request_settings_thinking_off: {} }); expect(app.thinkingOff).toBe('{}');
    app.edit(); expect(app.thinkingOff).toBe('');
    app.edit({ ...model, request_settings_thinking_off: null }); expect(app.thinkingOff).toBe('');
  });



  it('starts on Overview and offers Jev only for classification, with model health', async () => {
    const { fixture } = await create(true); const app = fixture.componentInstance;
    expect(TestBed.createComponent(App).componentInstance.screen()).toBe('overview');
    expect(app.availableTypes('chat').some(x => x.value === 'jev_systemone')).toBe(false);
    expect(app.availableTypes('classification').some(x => x.value === 'jev_systemone')).toBe(true);
    app.models.set([{ ...model, health: 'down', health_reason: 'http_503', health_changed_at: '2026-11-11T00:00:00Z' }]);
    app.edit({ ...model, purpose: 'classification', tier: undefined, api_type: 'jev_systemone' }); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('input[name=tier]')).toBeNull();
    expect(fixture.nativeElement.textContent).toContain('Jev System One'); expect(fixture.nativeElement.textContent).toContain('http_503');
  });

  it('counts approvals in the badge using only the normal pending list', async () => {
    const { fixture } = await create(true); const app = fixture.componentInstance;
    const request = vi.spyOn(app, 'request').mockResolvedValueOnce({ count: 0 }).mockResolvedValueOnce({ count: 0 }).mockResolvedValueOnce({ count: 0 })
      .mockResolvedValueOnce([{ id: 'synthetic-visible-approval', created_at: '2026-11-11T00:00:00Z' }]);
    await app.loadAccessCount(); fixture.detectChanges();
    expect(app.pendingCount()).toBe(1);
    expect(request).toHaveBeenCalledWith('/admin/approvals?status=pending&limit=200');
    expect(fixture.nativeElement.querySelector('.ooh-nav__count').textContent).toBe('1');
  });

  it.each([
    [0, 0, 'Good morning.'], [11, 59, 'Good morning.'],
    [12, 0, 'Good afternoon.'], [17, 59, 'Good afternoon.'],
    [18, 0, 'Good evening.'], [21, 46, 'Good evening.']
  ])('greets signed-out users at browser-local %i:%i', async (hour, minute, expected) => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date(2026, 10, 11, hour, minute));
    const { fixture } = await create(false, false);
    expect(fixture.nativeElement.querySelector('.signin h1').textContent).toBe(expected);
  });

  it('renders stored health for classification without a tier after loading the admin list', async () => {
    const { fixture } = await create(true); const app = fixture.componentInstance;
    vi.mocked(App.prototype.load).mockRestore();
    const classifier = { ...model, model_entry_id: 'synthetic-classifier', title: 'Synthetic classifier', purpose: 'classification', tier: undefined, health: 'ok', health_changed_at: '2026-11-11T12:00:00Z' };
    vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(
      url.startsWith('/api/admin/models?') ? [{ ...model, health: 'ok' }, classifier] : url.includes('/count?') ? { count: 0 } : []
    ), { status: 200, headers: { 'Content-Type': 'application/json' } })));
    await app.load(); fixture.detectChanges();
    const rows = Array.from(fixture.nativeElement.querySelectorAll('.ooh-table tbody tr')) as HTMLTableRowElement[];
    const classification = rows.find(row => row.cells[0]?.textContent === 'classification');
    expect(classification).toBeDefined();
    expect(classification!.cells[6].textContent).toBe('OK');
    expect(classification!.querySelector('.ooh-chip--done')).not.toBeNull();
  });

  it('opens a direct hash link and keeps navigation, hash changes and history in agreement', async () => {
    window.history.replaceState(null, '', '#approvals');
    await create(true);
    const fixture = TestBed.createComponent(App); const app = fixture.componentInstance;
    vi.spyOn(app, 'request').mockResolvedValue([]); fixture.detectChanges(); await fixture.whenStable();
    expect(app.screen()).toBe('approvals'); expect(fixture.nativeElement.textContent).toContain('Human decisions');
    fixture.nativeElement.querySelector('a[href="#audit"]').click();
    expect(app.screen()).toBe('audit'); expect(window.location.hash).toBe('#audit');
    window.history.replaceState(null, '', '#rights'); window.dispatchEvent(new HashChangeEvent('hashchange'));
    expect(app.screen()).toBe('rights');
    window.history.replaceState(null, '', '#models'); window.dispatchEvent(new PopStateEvent('popstate'));
    expect(app.screen()).toBe('models');
    window.history.replaceState(null, '', '#unrecognised'); window.dispatchEvent(new HashChangeEvent('hashchange'));
    expect(app.screen()).toBe('overview'); expect(window.location.hash).toBe('#overview');
  });
  it('uses the given name for Overview and accepts the Control Centre display-zone setting', async () => {
    const { fixture } = await create(true, true, { given_name: 'Synthetic' }); const app = fixture.componentInstance;
    expect(app.givenName()).toBe('Synthetic');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('[]', { headers: { 'Content-Type': 'application/json', 'X-Display-Time-Zone': 'UTC' } })));
    await app.request('/admin/models?limit=200'); expect(app.displayTimeZone()).toBe('UTC');
    expect(app.formatTime('2026-11-11T13:55:46Z')).toBe('11 Nov 13:55:46');
  });

  it('restores the intended screen after sign-in removes the callback hash', async () => {
    window.history.replaceState(null, '', '#approvals');
    const { fixture, auth } = await create(false, false); fixture.componentInstance.screen.set('approvals'); fixture.componentInstance.signIn();
    expect(sessionStorage.getItem('ooh-admin-signin-screen')).toBe('approvals');
    vi.spyOn(auth, 'checkAuth').mockImplementation(() => {
      window.history.replaceState(null, '', window.location.pathname);
      return of({ isAuthenticated: true, userData: {} });
    });
    auth.getPayloadFromAccessToken.mockReturnValue(of({ realm_access: { roles: ['ooh-admin'] } }));
    const returned = TestBed.createComponent(App).componentInstance;
    expect(returned.screen()).toBe('approvals'); expect(window.location.hash).toBe('#approvals');
    expect(sessionStorage.getItem('ooh-admin-signin-screen')).toBeNull();
  });

});
