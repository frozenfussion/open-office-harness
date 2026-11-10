// SPDX-License-Identifier: AGPL-3.0-only
import { TestBed } from '@angular/core/testing';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Api, ApiError, Me } from './api';
import { ChatModels } from './chat-models';

describe('Chat models', () => {
  afterEach(() => { vi.restoreAllMocks(); TestBed.resetTestingModule(); localStorage.clear(); });
  const me: Me = {access: 'approved', user_id: 'test-user', name: 'Test user', chat_tiers: [1, 3],
    chat_tier_titles: {'1': 'Test main'}, chat_tier_thinking_switch: {'1': true, '3': true}, skills: [],
    requestable_tiers: [
      {tier: 2, title: '<b>Another model</b>', requested: null},
      {tier: 4, title: 'Test pending', requested: 'pending'},
      {tier: 5, title: 'Test rejected', requested: 'rejected'},
      {tier: 99, title: 'Excluded check', requested: null},
      {tier: 1, title: 'Already allowed', requested: null},
    ]};
  async function fixture(request = vi.fn().mockResolvedValue({id: 'test-request', status: 'pending'})) {
    TestBed.configureTestingModule({imports: [ChatModels], providers: [{provide: Api, useValue: {requestTier: request}}]});
    const view = TestBed.createComponent(ChatModels);
    view.componentRef.setInput('me', me);
    view.componentRef.setInput('tier', 1);
    view.detectChanges(); await view.whenStable(); view.detectChanges();
    return {view, controls: view.componentInstance, request};
  }
  it('shows thinking only for a supported selected tier and remembers each tier across reloads', async () => {
    const {view, controls} = await fixture();
    const toggle = view.nativeElement.querySelector('[role="switch"]') as HTMLButtonElement;
    expect(toggle.getAttribute('aria-label')).toBe('Thinking');
    expect(toggle.getAttribute('aria-checked')).toBe('true');
    toggle.click(); view.detectChanges();
    expect(controls.thinking()).toBe(false);
    expect(localStorage.getItem('ooh.thinking.1')).toBe('false');
    view.componentRef.setInput('tier', 3); view.detectChanges();
    expect(controls.thinking()).toBe(true);
    view.componentRef.setInput('tier', 1); view.detectChanges();
    expect(controls.thinking()).toBe(false);
    view.destroy();
    TestBed.resetTestingModule();
    const reloaded = await fixture();
    expect(reloaded.controls.thinking()).toBe(false);
    reloaded.view.componentRef.setInput('me', {...me, chat_tier_thinking_switch: {}});
    reloaded.view.detectChanges();
    expect(reloaded.view.nativeElement.querySelector('[role="switch"]')).toBeNull();
    expect(reloaded.controls.thinking()).toBe(true);
  });
  it('keeps chat usable when browser preference storage is unavailable', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {throw new Error('Unavailable');});
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {throw new Error('Unavailable');});
    const {controls} = await fixture();
    expect(controls.thinking()).toBe(true);
    controls.toggleThinking();
    expect(controls.thinking()).toBe(false);
  });
  it('opens the request panel from the last picker option without changing the chat tier', async () => {
    const {view, controls} = await fixture();
    const emit = vi.spyOn(controls.tierChange, 'emit');
    const select = view.nativeElement.querySelector('select') as HTMLSelectElement;
    select.selectedIndex = select.options.length - 1;
    select.dispatchEvent(new Event('change')); view.detectChanges();
    expect(controls.panel()).toBe(true);
    expect(controls.tier()).toBe(1);
    expect(emit).not.toHaveBeenCalled();
    expect(select.selectedIndex).toBe(0);
    expect(view.nativeElement.querySelector('[aria-label="Request another model"]')).not.toBeNull();
    const choices = view.nativeElement.querySelector('[aria-label="Model to request"]');
    expect(choices.textContent).toContain('<b>Another model</b> - Tier 2');
    expect(choices.querySelector('b')).toBeNull();
    expect(choices.textContent).not.toContain('Tier 99');
    expect(choices.textContent).not.toContain('Already allowed');
    expect(choices.textContent).toContain('Requested');
    expect(choices.textContent).toContain('Not approved');
  });
  it('sends one request with a trimmed optional reason and changes its button to Requested', async () => {
    let finish!: () => void;
    const request = vi.fn(() => new Promise<{id: string; status: 'pending'}>(resolve => {
      finish = () => resolve({id: 'test-request', status: 'pending'});
    }));
    const {view, controls} = await fixture(request);
    controls.panel.set(true); controls.requestTier.set(2); controls.reason = '  Test reason  ';
    const sending = controls.sendRequest();
    await controls.sendRequest();
    expect(request).toHaveBeenCalledExactlyOnceWith(2, 'Test reason');
    expect(controls.requesting()).toBe(true);
    finish(); await sending; view.detectChanges();
    expect(controls.selected()?.requested).toBe('pending');
    const button = (Array.from(view.nativeElement.querySelectorAll('button')) as HTMLButtonElement[]).find(button => button.textContent === 'Requested') as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    await controls.sendRequest();
    expect(request).toHaveBeenCalledOnce();
  });
  it('refuses pending, unknown, unapproved and overlong requests locally', async () => {
    const {view, controls, request} = await fixture();
    for (const tier of [null, 4, 99, 1]) { controls.requestTier.set(tier); await controls.sendRequest(); }
    controls.requestTier.set(2); controls.reason = 'x'.repeat(301); await controls.sendRequest();
    controls.reason = ''; view.componentRef.setInput('me', {...me, access: 'pending'}); await controls.sendRequest();
    expect(request).not.toHaveBeenCalled();
  });
  it('allows 300-character reasons and an empty reason', async () => {
    const {controls, request} = await fixture();
    controls.requestTier.set(2); controls.reason = 'x'.repeat(300); await controls.sendRequest();
    expect(request).toHaveBeenLastCalledWith(2, 'x'.repeat(300));
    controls.requestTier.set(5); controls.reason = ''; await controls.sendRequest();
    expect(request).toHaveBeenLastCalledWith(5, '');
  });
  it.each([
    [409, 'too_soon', 'Backend refusal', 'You can ask for this model again 7 days after the last answer.'],
    [409, 'already_requested', 'Already requested.', 'Already requested.'],
    [429, 'too_many_requests', 'Too many requests.', 'Too many requests.'],
    [403, 'not_approved', '<b>Not approved.</b>', '<b>Not approved.</b>'],
    [400, 'tier_not_requestable', 'Tier not requestable.', 'Tier not requestable.'],
  ])('shows refusal %s %s as a plain message', async (status, code, message, expected) => {
    const {view, controls, request} = await fixture(vi.fn().mockRejectedValue(new ApiError(status, message, code)));
    controls.panel.set(true); controls.requestTier.set(5);
    await controls.sendRequest(); view.detectChanges();
    expect(request).toHaveBeenCalledOnce();
    expect(view.nativeElement.querySelector('[role="alert"]').textContent).toBe(expected);
    expect(view.nativeElement.querySelector('[role="alert"] b')).toBeNull();
    expect(controls.selected()?.requested).toBe('rejected');
    expect(controls.requesting()).toBe(false);
  });
  it('shows an empty panel when no other models are available', async () => {
    const {view, controls} = await fixture();
    view.componentRef.setInput('me', {...me, requestable_tiers: []}); controls.panel.set(true); view.detectChanges();
    expect(view.nativeElement.textContent).toContain('There are no other models to request.');
    expect(view.nativeElement.querySelector('[aria-label="Model to request"]')).toBeNull();
  });
});
