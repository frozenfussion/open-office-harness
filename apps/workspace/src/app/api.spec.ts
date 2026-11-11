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
  it('posts Auto unchanged with bearer authentication', async () => {
    const fetchRequest = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('', {headers: {'Content-Type': 'text/event-stream'}}));
    await api().send('conversation', 'Question', 'auto', new AbortController().signal, () => {});
    expect(JSON.parse(fetchRequest.mock.calls[0][1]?.body as string)).toEqual({content: 'Question', tier: 'auto', thinking: true});
    expect(fetchRequest.mock.calls[0][1]?.headers).toEqual({Authorization: 'Bearer test-token', 'Content-Type': 'application/json'});
  });
  it('posts model requests as authenticated JSON without a user ID', async () => {
    const fetchRequest = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{"id":"test-request","status":"pending"}', {status: 201}));
    expect(await api().requestTier(2, 'Test reason')).toEqual({id: 'test-request', status: 'pending'});
    expect(fetchRequest).toHaveBeenCalledExactlyOnceWith('/api/tier-requests', {
      method: 'POST', body: '{"tier":2,"reason":"Test reason"}', cache: 'no-store',
      headers: {Authorization: 'Bearer test-token', 'Content-Type': 'application/json'},
    });
  });
  it('reads nullable stored thinking separately from answer content', async () => {
    const history = {id: 'test-conversation', title: 'Test title', messages: [
      {id: 'user-message', role: 'user', content: 'Question', thinking: null, created_at: '2026-11-10T08:00:00Z'},
      {id: 'assistant-message', role: 'assistant', content: 'Answer only', thinking: 'Stored thought', created_at: '2026-11-10T08:00:01Z'},
    ]};
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(history)));
    expect(await api().conversation('test-conversation')).toEqual(history);
  });
  it('preserves refusal codes for the seven-day notice', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{"code":"too_soon","message":"Test refusal"}', {status: 409}));
    await expect(api().requestTier(5, '')).rejects.toMatchObject(new ApiError(409, 'Test refusal', 'too_soon'));
  });
});

describe('Jobs API', () => {
  afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); TestBed.resetTestingModule(); });
  function api(): Api {
    TestBed.configureTestingModule({providers:[{provide:CONFIG,useValue:{apiBase:'/api'}},{provide:OidcSecurityService,useValue:{getAccessToken:()=>of('test-token')}}]});
    return TestBed.inject(Api);
  }
  it('downloads a bearer-authenticated blob by job, uses the filename, and revokes its URL', async () => {
    vi.useFakeTimers();
    const create=vi.fn().mockReturnValue('blob:test'); const revoke=vi.fn();
    Object.defineProperty(URL,'createObjectURL',{configurable:true,value:create});
    Object.defineProperty(URL,'revokeObjectURL',{configurable:true,value:revoke});
    const click=vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{});
    const fetchRequest=vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response('pptx bytes',{headers:{'Content-Disposition':'attachment; filename="water-cycle.pptx"'}}));
    await api().download({job_id:'test-job',title:'Slides',label:'Water',skill:'slides',status:'completed'});
    expect(fetchRequest.mock.calls[0][0]).toBe('/api/jobs/test-job/file');
    expect(fetchRequest.mock.calls[0][1]?.headers).toEqual({Authorization:'Bearer test-token','Content-Type':'application/json'});
    expect(create.mock.calls[0][0]).toBeInstanceOf(Blob);expect(click).toHaveBeenCalledOnce();
    expect((click.mock.instances[0] as HTMLAnchorElement).download).toBe('water-cycle.pptx');
    await vi.advanceTimersByTimeAsync(1000);expect(revoke).toHaveBeenCalledWith('blob:test');
  });
  it('reloads jobs when the SSE connection opens before handling events', async () => {
    vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response('data: {"type":"job.queued","correlation_id":"job","skill":"slides","output":null,"error":null}\n\n',{headers:{'Content-Type':'text/event-stream'}}));
    const order:string[]=[];
    await api().events(new AbortController().signal,async()=>{order.push('reload');},()=>order.push('event'));
    expect(order).toEqual(['reload','event']);
  });
  it('submits a skill request without a user ID and preserves server conflicts', async () => {
    const fetchRequest=vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response('{"code":"too_soon","message":"Wait seven days."}',{status:409}));
    await expect(api().requestSkill('slides','A reason')).rejects.toMatchObject({status:409,code:'too_soon',message:'Wait seven days.'});
    expect(fetchRequest.mock.calls[0][1]?.body).toBe('{"skill":"slides","reason":"A reason"}');
  });
});
