// SPDX-License-Identifier: AGPL-3.0-only
import { TestBed } from '@angular/core/testing';
import { OidcSecurityService } from 'angular-auth-oidc-client';
import { of } from 'rxjs';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { App } from './app';
import { ConnectionResult, ModelEntry, modelPayload, settingsObject, tierRows } from './models';
const model: ModelEntry = { model_entry_id: 'synthetic', title: 'Synthetic', purpose: 'chat', tier: 1, role: 'main', location: 'cloud', api_type: 'openai_responses', endpoint_url: 'https://synthetic.invalid', model_id: 'synthetic', has_key: true, priority: 100, rate_limit_per_minute: 10, daily_budget: 0, input_price_per_million: 0, output_price_per_million: 0, timeout_seconds: 120, request_settings: {} };
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });
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
    const fixture = TestBed.createComponent(App); fixture.detectChanges(); return { fixture, auth };
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
      .mockResolvedValueOnce([{ ...model, purpose: 'a-purpose' }]).mockResolvedValueOnce([]).mockResolvedValueOnce({ count: 0 }).mockResolvedValueOnce({ count: 0 });
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
    const request = vi.spyOn(app, 'request').mockReturnValueOnce(pending);
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
    vi.spyOn(app, 'request').mockResolvedValueOnce({ ok: false, reason: 'key refused', provider_status: 401, provider_message: '<img src=x onerror=alert(1)>' });
    await app.testConnection(model); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role=status]').textContent).toBe('Failed · key refused (provider answered 401) · <img src=x onerror=alert(1)>');
    expect(fixture.nativeElement.querySelector('img')).toBeNull();
  });
  it('aborts the browser wait at the entry timeout plus fifteen seconds', async () => {
    const { fixture } = await create(true); const app = fixture.componentInstance;
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    })));
    const test = app.testConnection({ ...model, timeout_seconds: 10 });
    await vi.advanceTimersByTimeAsync(24999); expect(app.testing().has(model.model_entry_id)).toBe(true);
    await vi.advanceTimersByTimeAsync(1); await test;
    expect(app.testResults()[model.model_entry_id]).toEqual({ ok: false, reason: 'took longer than its time limit', provider_status: null, provider_message: null });
    expect(app.testing().size).toBe(0);
  });

  const accessRow = { id: 'request-synthetic', user_id: 'user-synthetic', name: '<img src=x>', email: 'synthetic@example.invalid', organisation: 'Synthetic team', reason: '<script>test</script>', status: 'pending' as const, requested_at: '2026-11-10T00:00:00Z' };
  it('links non-admins to the configured Workspace', async () => {
    const { fixture } = await create(false, true, {}, 'https://auth.synthetic.invalid/realms/ooh');
    expect(fixture.nativeElement.querySelector('a').href).toBe('https://harness.synthetic.invalid/');
  });
  it('loads each access filter and hides the zero count badge', async () => {
    const { fixture } = await create(true); const app = fixture.componentInstance;
    const request = vi.spyOn(app, 'request');
    for (const status of ['pending', 'approved', 'rejected'] as const) {
      app.accessFilter.set(status); request.mockResolvedValueOnce([{ ...accessRow, status }]).mockResolvedValueOnce([]).mockResolvedValueOnce({ count: 0 }).mockResolvedValueOnce({ count: 0 });
      await app.openAccessRequests(); fixture.detectChanges();
      expect(request).toHaveBeenCalledWith('/admin/access-requests?status=' + status + '&limit=200');
      expect(fixture.nativeElement.querySelector('.ooh-nav__count')).toBeNull();
      expect(fixture.nativeElement.textContent).toContain('not verified');
      expect(fixture.nativeElement.textContent).toContain('<img src=x>');
      expect(fixture.nativeElement.querySelector('img')).toBeNull();
    }
    app.pendingCount.set(3); fixture.detectChanges(); expect(fixture.nativeElement.querySelector('.ooh-nav__count').textContent).toBe('3');
  });
  it('requires a tier and sends approve, reject and revoke actions', async () => {
    const { fixture } = await create(true); const app = fixture.componentInstance;
    app.screen.set('access'); app.models.set([model, { ...model, tier: 99 }]); app.grants.set([{ id: 'grant', right_key: 'chat.tier.4', subject_type: 'everyone' }]); app.accessRequests.set([accessRow]); fixture.detectChanges();
    const approve = [...fixture.nativeElement.querySelectorAll('button')].find((b: unknown) => (b as HTMLButtonElement).textContent?.trim() === 'Approve') as HTMLButtonElement;
    expect(approve.disabled).toBe(true);
    const options = fixture.nativeElement.querySelectorAll('select[aria-label="Chat tier"] option');
    expect([...options].map((o: unknown) => (o as HTMLOptionElement).textContent)).toEqual(['Choose a tier', 'Tier 1', 'Tier 4']);
    vi.spyOn(app, 'loadAccessRequests').mockResolvedValue();
    const request = vi.spyOn(app, 'request');
    for (const action of ['approve', 'reject', 'revoke'] as const) {
      app.accessRequests.set([accessRow]); app.selectedTiers[accessRow.id] = 4;
      request.mockResolvedValueOnce({ ...accessRow, status: action === 'approve' ? 'approved' : 'rejected' });
      await app.decideAccess(accessRow, action);
      expect(request).toHaveBeenLastCalledWith('/admin/access-requests/' + accessRow.id + '/' + action, 'POST', action === 'approve' ? { tier: 4 } : {});
      expect(app.accessRequests()).toEqual([]);
    }
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
  it('reads all model request pages and adds both pending counts', async () => {
    const { fixture } = await create(true); const app = fixture.componentInstance;
    const row = { ...accessRow, tier: 4, title: '<script>Synthetic model</script>' };
    const first = Array.from({ length: 200 }, (_, i) => ({ ...row, id: 'tier-' + i }));
    const request = vi.spyOn(app, 'request').mockResolvedValueOnce([]).mockResolvedValueOnce(first).mockResolvedValueOnce([{ ...row, id: 'last' }]).mockResolvedValueOnce({ count: 2 }).mockResolvedValueOnce({ count: 3 });
    await app.openAccessRequests(); fixture.detectChanges();
    expect(request).toHaveBeenNthCalledWith(3, '/admin/tier-requests?status=pending&limit=200&after=tier-199');
    expect(app.tierRequests()).toHaveLength(201); expect(app.pendingCount()).toBe(5);
    expect(fixture.nativeElement.textContent).toContain('Model requests');
    expect(fixture.nativeElement.textContent).toContain('<script>Synthetic model</script> - Tier 4');
    expect(fixture.nativeElement.textContent).toContain('<script>test</script>');
    expect(fixture.nativeElement.querySelector('script, img')).toBeNull();
  });
  it('decides model requests and keeps a failed decision visible', async () => {
    const { fixture } = await create(true); const app = fixture.componentInstance;
    const row = { ...accessRow, tier: 4, title: 'Synthetic model' };
    vi.spyOn(app, 'loadAccessRequests').mockResolvedValue(); const request = vi.spyOn(app, 'request');
    for (const action of ['approve', 'reject'] as const) {
      app.tierRequests.set([row]); request.mockResolvedValueOnce({ ...row, status: action === 'approve' ? 'approved' : 'rejected' });
      await app.decideTier(row, action);
      expect(request).toHaveBeenLastCalledWith('/admin/tier-requests/' + row.id + '/' + action, 'POST', {});
      expect(app.tierRequests()).toEqual([]); expect(app.accessBusy()).toBe(false);
    }
    app.tierRequests.set([row]); request.mockRejectedValueOnce(new Error("This person's access is no longer approved"));
    await app.decideTier(row, 'approve'); expect(app.tierRequests()).toEqual([row]); expect(app.error()).toContain('no longer approved');
  });

});
