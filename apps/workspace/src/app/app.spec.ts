// SPDX-License-Identifier: AGPL-3.0-only
import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { OidcSecurityService } from 'angular-auth-oidc-client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App, metaLine } from './app';
import { Api, ApiError } from './api';
import { readStream, SseParser } from './sse';
import { CONFIG, readConfig } from './config';
import { appConfig } from './app.config';

describe('Workspace', () => {
  afterEach(() => { vi.restoreAllMocks(); TestBed.resetTestingModule(); window.history.replaceState(null, '', '/'); });
  it('parses SSE across byte and line boundaries, CRLF and final chunks', async () => {
    const events: unknown[] = [];
    const bytes = new TextEncoder().encode('data: {"type":"delta","text":"你"}\r\n\r\ndata: {"type":"failed","error":{"code":"unavailable","message":"Try again"}}\n\n');
    await readStream(new ReadableStream({start(controller) {
      for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
      controller.close();
    }}), event => events.push(event));
    expect(events).toEqual([{type: 'delta', text: '你'}, {type: 'failed', error: {code: 'unavailable', message: 'Try again'}}]);
    const parser = new SseParser(event => events.push(event));
    parser.push(': keepalive\ndata: {"type":"delta",\n');
    parser.push('data: "text":"end"}', true);
    expect(events.at(-1)).toEqual({type: 'delta', text: 'end'});
  });
  it('formats the meta line and budget note', () => {
    expect(metaLine({role: 'assistant', content: '', tier: 2, model_title: 'Test entry', input_tokens: 12, output_tokens: 24}))
      .toBe('tier 2 · Test entry · 12 in / 24 out tokens');
    expect(metaLine({role: 'assistant', content: '', tier: 1, model_title: 'Test entry', note: 'tier 2 is over its daily budget; answered with tier 1'}))
      .toContain(' · tier 2 is over its daily budget; answered with tier 1');
  });
  async function fixture(send = vi.fn().mockRejectedValue(new ApiError(403, "You don't have tier 3. An admin can grant it."))) {
    TestBed.configureTestingModule({imports: [App], providers: [
      {provide: OidcSecurityService, useValue: {checkAuth: () => of({isAuthenticated: false}), isAuthenticated$: of({isAuthenticated: false})}},
      {provide: Api, useValue: {create: async () => ({id: 'test-conversation'}), list: async () => [], send}},
    ]});
    const view = TestBed.createComponent(App);
    view.detectChanges();
    view.componentInstance.signedIn.set(true);
    view.componentInstance.me.set({access: 'approved', user_id: 'test-user', name: 'Test user', chat_tiers: [1, 3], chat_tier_titles: {}, skills: []});
    view.componentInstance.tier = 1;
    view.detectChanges();
    await view.whenStable();
    return view;
  }
  it('offers only allowed tiers', async () => {
    const view = await fixture();
    const options = [...view.nativeElement.querySelectorAll('select option')] as HTMLOptionElement[];
    expect(options.map(option => option.textContent?.trim())).toEqual(['Tier 1', 'Tier 3']);
  });
  it('labels allowed chat models with their titles and falls back to the tier', async () => {
    const view = await fixture();
    view.componentInstance.me.update(me => me ? {
      ...me, chat_tier_titles: {'1': 'Test main entry', '2': 'Hidden entry'},
    } : null);
    view.detectChanges();
    const select = view.nativeElement.querySelector('select[aria-label="Chat model"]');
    expect(select).not.toBeNull();
    const options = [...select.querySelectorAll('option')] as HTMLOptionElement[];
    expect(options.map(option => option.textContent?.trim())).toEqual(['Test main entry - Tier 1', 'Tier 3']);
    expect(view.nativeElement.querySelector('.ooh-label').textContent).toBe('Chat model');
    expect(select.textContent).not.toContain('Hidden entry');
  });
  it('shows a 403 message in an amber notice', async () => {
    const view = await fixture();
    view.componentInstance.draft = 'A question';
    await view.componentInstance.send();
    view.detectChanges();
    const notice = view.nativeElement.querySelector('[role="alert"]');
    expect(notice.textContent).toBe("You don't have tier 3. An admin can grant it.");
    expect(notice.classList.contains('forbidden')).toBe(true);
  });
  it('streams plain text, disables sending, and renders final metadata', async () => {
    let finish!: () => void;
    const send = vi.fn(async (_id, _content, _tier, _signal, receive) => {
      receive({type: 'delta', text: '<img src=x onerror=alert(1)>\nAnswer'});
      await new Promise<void>(resolve => {finish = resolve;});
      receive({type: 'completed', message_id: 'message', tier: 1, model_title: 'Test entry', usage: {input_tokens: 2, output_tokens: 4}, note: null});
    });
    const view = await fixture(send);
    view.componentInstance.draft = 'Question';
    const sending = view.componentInstance.send();
    await vi.waitFor(() => expect(send).toHaveBeenCalled());
    view.detectChanges();
    expect(view.nativeElement.querySelector('button[type="submit"]').disabled).toBe(true);
    expect(view.nativeElement.querySelector('.ooh-cursor')).not.toBeNull();
    expect(view.nativeElement.querySelector('.messages img')).toBeNull();
    expect(view.nativeElement.querySelector('.messages').textContent).toContain('<img src=x');
    finish(); await sending; view.detectChanges();
    expect(view.nativeElement.querySelector('.ooh-cursor')).toBeNull();
    expect(view.nativeElement.querySelector('.ooh-msg__meta').textContent).toContain('tier 1 · Test entry · 2 in / 4 out tokens');
  });
  async function accessFixture(access: 'approved' | 'pending' | 'rejected' | 'closed' | 'unavailable') {
    const api = {
      me: access === 'unavailable'
        ? vi.fn().mockRejectedValue(new ApiError(503, 'Your access could not be checked. Try again.'))
        : vi.fn().mockResolvedValue({access, user_id: 'test-user', name: 'Given Family', chat_tiers: [1], chat_tier_titles: {}, skills: []}),
      list: vi.fn().mockResolvedValue([]),
      conversation: vi.fn(), create: vi.fn(), send: vi.fn(),
    };
    const logoff = vi.fn(() => of(undefined));
    TestBed.configureTestingModule({imports: [App], providers: [
      {provide: OidcSecurityService, useValue: {
        checkAuth: () => of({isAuthenticated: true, userData: {given_name: 'Given'}}),
        isAuthenticated$: of({isAuthenticated: true}), logoff,
      }},
      {provide: Api, useValue: api},
    ]});
    if (access !== 'approved') window.history.replaceState(null, '', '/?conversation=should-not-load');
    const view = TestBed.createComponent(App);
    view.detectChanges();
    await view.whenStable();
    view.detectChanges();
    return {view, api, logoff};
  }
  it.each([
    ['pending', 'Thanks, Given. Your request is waiting for approval.'],
    ['rejected', 'Your request was not approved. Please contact your administrator.'],
    ['closed', 'Requests are closed for now. Please contact your administrator.'],
  ] as const)('shows only the %s message and sign out', async (access, message) => {
    const {view, api, logoff} = await accessFixture(access);
    expect(view.nativeElement.querySelector('[role="status"]').textContent).toBe(message);
    expect(view.nativeElement.querySelector('nav')).toBeNull();
    expect(view.nativeElement.querySelector('form')).toBeNull();
    const buttons = view.nativeElement.querySelectorAll('button');
    expect(buttons.length).toBe(1);
    expect(buttons[0].textContent).toBe('Sign out');
    expect(api.me).toHaveBeenCalledOnce();
    expect(api.list).not.toHaveBeenCalled();
    expect(api.conversation).not.toHaveBeenCalled();
    expect(api.create).not.toHaveBeenCalled();
    expect(api.send).not.toHaveBeenCalled();
    buttons[0].click();
    expect(logoff).toHaveBeenCalledOnce();
  });
  it('opens chat and loads conversations for approved access', async () => {
    const {view, api} = await accessFixture('approved');
    expect(view.nativeElement.querySelector('nav')).not.toBeNull();
    expect(view.nativeElement.querySelector('form')).not.toBeNull();
    expect(api.list).toHaveBeenCalledOnce();
  });
  it('shows a red notice when access cannot be checked', async () => {
    const {view, api} = await accessFixture('unavailable');
    const notice = view.nativeElement.querySelector('[role="alert"]');
    expect(notice.classList.contains('notice')).toBe(true);
    expect(notice.classList.contains('forbidden')).toBe(false);
    expect(notice.textContent).toBe('Your access could not be checked. Try again.');
    expect(view.nativeElement.textContent).not.toContain('waiting for approval');
    expect(view.nativeElement.querySelector('form')).toBeNull();
    expect(api.list).not.toHaveBeenCalled();
  });
  it('creates a conversation with the required empty JSON body', async () => {
    const fetchRequest = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({id: 'test-conversation'}), {
      status: 201, headers: {'Content-Type': 'application/json'},
    }));
    TestBed.configureTestingModule({providers: [
      {provide: CONFIG, useValue: {apiBase: '/api'}},
      {provide: OidcSecurityService, useValue: {getAccessToken: () => of('test-token')}},
    ]});
    expect(await TestBed.inject(Api).create()).toEqual({id: 'test-conversation'});
    expect(fetchRequest).toHaveBeenCalledExactlyOnceWith('/api/conversations', {
      method: 'POST', body: '{}', cache: 'no-store',
      headers: {Authorization: 'Bearer test-token', 'Content-Type': 'application/json'},
    });
  });
  it('constructs the real OIDC client with the application providers', () => {
    TestBed.configureTestingModule(appConfig({issuer: 'https://identity.invalid/realms/test', clientId: 'ooh-workspace', apiBase: '/api'}));
    expect(TestBed.inject(OidcSecurityService)).toBeDefined();
  });
  it('rejects settings that send API tokens away from this host', () => {
    expect(() => readConfig({issuer: 'https://identity.invalid', clientId: 'ooh-workspace', apiBase: 'https://other.invalid'})).toThrow();
  });
});
