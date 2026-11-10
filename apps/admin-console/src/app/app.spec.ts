// SPDX-License-Identifier: AGPL-3.0-only
import { TestBed } from '@angular/core/testing';
import { OidcSecurityService } from 'angular-auth-oidc-client';
import { of } from 'rxjs';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { App } from './app';
import { ModelEntry, modelPayload, settingsObject, tierRows } from './models';
const model: ModelEntry = { model_entry_id: 'synthetic', title: 'Synthetic', purpose: 'chat', tier: 1, role: 'main', location: 'cloud', api_type: 'openai_responses', endpoint_url: 'https://synthetic.invalid', model_id: 'synthetic', has_key: true, priority: 100, rate_limit_per_minute: 10, daily_budget: 0, input_price_per_million: 0, output_price_per_million: 0, timeout_seconds: 120, request_settings: {} };
afterEach(() => vi.restoreAllMocks());
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
  it('keeps grant-only tiers visible and hides tier 99', () => {
    expect(tierRows([model, { ...model, tier: 99 }], [{ id: 'grant', right_key: 'chat.tier.4', subject_type: 'everyone' }, { id: 'check', right_key: 'chat.tier.99', subject_type: 'user' }])).toEqual([1, 4]);
  });
});
describe('Admin console', () => {
  async function create(admin: boolean, authenticated = true, userData: object = {}) {
    const auth = { checkAuth: () => of({ isAuthenticated: authenticated, userData }), authorize: vi.fn(), logoff: () => of({}), getAccessToken: () => of('synthetic-token'), getPayloadFromAccessToken: vi.fn(() => of({ realm_access: { roles: admin ? ['ooh-admin'] : ['ooh-user'] } })) };
    window.oohConfig = { apiBase: '/api', issuer: 'https://issuer.invalid', clientId: 'ooh-admin-console' };
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
    expect(fixture.nativeElement.textContent).not.toContain('Test connection');
  });
  it('reads every model page and sorts the display', async () => {
    const { fixture } = await create(true); const app = fixture.componentInstance;
    vi.mocked(App.prototype.load).mockRestore();
    const first = Array.from({ length: 200 }, (_, i) => ({ ...model, model_entry_id: 'synthetic-' + i, purpose: 'z-purpose' }));
    const request = vi.spyOn(app, 'request').mockResolvedValueOnce(first)
      .mockResolvedValueOnce([{ ...model, purpose: 'a-purpose' }]).mockResolvedValueOnce([]);
    await app.load();
    expect(request).toHaveBeenNthCalledWith(2, '/admin/models?limit=200&after=synthetic-199');
    expect(app.models()).toHaveLength(201); expect(app.models()[0].purpose).toBe('a-purpose');
  });

});
