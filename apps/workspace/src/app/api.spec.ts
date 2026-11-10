// SPDX-License-Identifier: AGPL-3.0-only
import { TestBed } from '@angular/core/testing';
import { OidcSecurityService } from 'angular-auth-oidc-client';
import { of } from 'rxjs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Api, ApiError } from './api';
import { CONFIG } from './config';

describe('Workspace API model controls', () => {
  afterEach(() => { vi.restoreAllMocks(); TestBed.resetTestingModule(); });
  function api(): Api {
    TestBed.configureTestingModule({providers: [
      {provide: CONFIG, useValue: {apiBase: '/api'}},
      {provide: OidcSecurityService, useValue: {getAccessToken: () => of('test-token')}},
    ]});
    return TestBed.inject(Api);
  }
  it.each([true, false])('sends the captured thinking=%s with the numeric tier', async thinking => {
    const fetchRequest = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('', {headers: {'Content-Type': 'text/event-stream'}}));
    const signal = new AbortController().signal;
    await api().send('test-conversation', 'Test question', 3, signal, vi.fn(), thinking);
    expect(fetchRequest).toHaveBeenCalledExactlyOnceWith('/api/conversations/test-conversation/messages', {
      method: 'POST', body: JSON.stringify({content: 'Test question', tier: 3, thinking}), signal, cache: 'no-store',
      headers: {Authorization: 'Bearer test-token', 'Content-Type': 'application/json'},
    });
  });
  it('defaults thinking to true when no choice is supplied', async () => {
    const fetchRequest = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('', {headers: {'Content-Type': 'text/event-stream'}}));
    await api().send('test-conversation', 'Test question', 1, new AbortController().signal, vi.fn());
    expect(JSON.parse(fetchRequest.mock.calls[0][1]?.body as string).thinking).toBe(true);
  });
  it('posts model requests as authenticated JSON without a user ID', async () => {
    const fetchRequest = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{"id":"test-request","status":"pending"}', {status: 201}));
    expect(await api().requestTier(2, 'Test reason')).toEqual({id: 'test-request', status: 'pending'});
    expect(fetchRequest).toHaveBeenCalledExactlyOnceWith('/api/tier-requests', {
      method: 'POST', body: '{"tier":2,"reason":"Test reason"}', cache: 'no-store',
      headers: {Authorization: 'Bearer test-token', 'Content-Type': 'application/json'},
    });
  });
  it('preserves refusal codes for the seven-day notice', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{"code":"too_soon","message":"Test refusal"}', {status: 409}));
    await expect(api().requestTier(5, '')).rejects.toMatchObject(new ApiError(409, 'Test refusal', 'too_soon'));
  });
});
