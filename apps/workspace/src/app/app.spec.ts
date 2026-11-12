// SPDX-License-Identifier: AGPL-3.0-only
import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { OidcSecurityService } from 'angular-auth-oidc-client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Jobs } from './jobs';
import { signal } from '@angular/core';
import { App, greeting, metaLine } from './app';
import { Message, Api, ApiError } from './api';
import { ChatEvent, JobEvent, readStream, SseParser } from './sse';
import { CONFIG, readConfig } from './config';
import { appConfig } from './app.config';

describe('Auto routing metadata', () => {
  it('shows routing and a declined skill note for streamed and reloaded answers', () => {
    const note = 'The model chose not to use Slides.';
    const message: Message = {role: 'assistant', content: 'Answer', created_at: '', tier: 1, model_title: 'Example',
      routing: {tier: 1, scores: {needs_tier2: 0.1}, skill: 'slides', note}};
    expect(metaLine(message)).toContain('auto → tier 1');
    expect(metaLine(message)).toContain(note);
    expect(metaLine(JSON.parse(JSON.stringify(message)))).toBe(metaLine(message));
  });
});

describe('Workspace', () => {
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); TestBed.resetTestingModule(); window.history.replaceState(null, '', '/'); localStorage.clear(); sessionStorage.clear(); });
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
  it('parses a late title after completed across split SSE chunks', async () => {
    const events: (ChatEvent | JobEvent)[] = [];
    const wire = 'data: {"type":"completed","message_id":"m","tier":1,"model_title":"Test entry","usage":{"input_tokens":2,"output_tokens":4},"note":null,"thinking_applied":true}\n\n' +
      'data: {"type":"title","conversation_id":"test-conversation","title":"A short conversation title"}\n\n';
    const bytes = new TextEncoder().encode(wire);
    await readStream(new ReadableStream({start(controller) {
      for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
      controller.close();
    }}), event => events.push(event));
    expect(events.map(event => event.type)).toEqual(['completed', 'title']);
    expect(events[1]).toEqual({type: 'title', conversation_id: 'test-conversation', title: 'A short conversation title'});
  });
  it.each([
    [0, 0, 'Good morning.'], [11, 59, 'Good morning.'],
    [12, 0, 'Good afternoon.'], [17, 59, 'Good afternoon.'],
    [18, 0, 'Good evening.'], [23, 59, 'Good evening.'],
  ])('greets using browser local time at %s:%s', (hour, minute, expected) => {
    expect(greeting(new Date(2026, 10, 10, hour, minute))).toBe(expected);
  });
  it.each([
    [11, 59, 'Good morning.'], [12, 0, 'Good afternoon.'],
    [17, 59, 'Good afternoon.'], [18, 0, 'Good evening.'],
  ])('captures the greeting when sign-in is shown at %s:%s without live updates', (hour, minute, expected) => {
    vi.useFakeTimers({toFake: ['Date']}); vi.setSystemTime(new Date(2026, 10, 10, hour, minute));
    TestBed.configureTestingModule({imports: [App], providers: [{provide: Jobs, useValue: {start: vi.fn(), stop: vi.fn(), rows: signal([]), notice: signal(''), more: signal(false)}},
      {provide: OidcSecurityService, useValue: {checkAuth: () => of({isAuthenticated: false}), isAuthenticated$: of({isAuthenticated: false})}},
      {provide: Api, useValue: {}},
    ]});
    const view = TestBed.createComponent(App); view.detectChanges();
    expect(view.nativeElement.querySelector('h1').textContent).toBe(expected);
    vi.setSystemTime(new Date(2026, 10, 11, 0, 0));
    view.componentInstance.notice.set('Another render'); view.detectChanges();
    expect(view.nativeElement.querySelector('h1').textContent).toBe(expected);
  });
  it('ignores unknown SSE event types between known events', () => {
    const events: (ChatEvent | JobEvent)[] = [];
    const parser = new SseParser(event => events.push(event));
    parser.push('data: {"type":"future","text":"Ignore"}\n\ndata: {"type":"thinking","text":"Thought"}\n\n');
    parser.push('data: {"type":"future_final"}\n\ndata: {"type":"delta","text":"Answer"}\n\n', true);
    expect(events).toEqual([{type: 'thinking', text: 'Thought'}, {type: 'delta', text: 'Answer'}]);
  });
  it('starts direct Workspace registration with prompt=create and preserves ordinary sign-in', async () => {
    const authorize = vi.fn();
    TestBed.configureTestingModule({imports: [App], providers: [{provide: Jobs, useValue: {start: vi.fn(), stop: vi.fn(), rows: signal([]), notice: signal(''), more: signal(false)}},
      {provide: OidcSecurityService, useValue: {authorize, checkAuth: () => of({isAuthenticated: false}), isAuthenticated$: of({isAuthenticated: false})}},
      {provide: Api, useValue: {}},
    ]});
    const view = TestBed.createComponent(App); view.detectChanges();
    const buttons = view.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>;
    expect(buttons[0].textContent).toBe('Sign in with company account');
    expect(buttons[1].textContent).toBe('Request access');
    buttons[1].click();
    expect(authorize).toHaveBeenLastCalledWith(undefined, {customParams: {prompt: 'create'}});
    buttons[0].click(); expect(authorize).toHaveBeenLastCalledWith();
    expect(view.nativeElement.querySelector('h1').textContent).toBe(greeting());
  });
  it.each(['signIn', 'requestAccess'] as const)('restores a saved chat once after %s redirects', async action => {
    const id = '12345678-1234-1234-1234-123456789012';
    const authorize = vi.fn();
    const conversation = vi.fn().mockResolvedValue({id, title: 'Saved chat', messages: []});
    let authenticated = false;
    TestBed.configureTestingModule({imports: [App], providers: [
      {provide: Jobs, useValue: {start: vi.fn(), stop: vi.fn(), rows: signal([]), notice: signal(''), more: signal(false)}},
      {provide: OidcSecurityService, useValue: {authorize, checkAuth: () => of({isAuthenticated: authenticated}), isAuthenticated$: of({isAuthenticated: false})}},
      {provide: Api, useValue: {me: async () => ({access: 'approved', user_id: 'test-user', name: 'Test user', chat_tiers: [1], skills: [], requestable_tiers: [], chat_tier_titles: {}, chat_tier_thinking_switch: {}}), list: async () => [], conversation}},
    ]});
    window.history.replaceState(null, '', '/?conversation=' + id);
    const before = TestBed.createComponent(App); before.detectChanges();
    before.componentInstance[action](); before.destroy();
    window.history.replaceState(null, '', '/?code=test'); authenticated = true;
    const after = TestBed.createComponent(App); after.detectChanges(); await vi.waitFor(() => expect(after.componentInstance.loading()).toBe(false)); await after.whenStable();
    expect(conversation).toHaveBeenCalledExactlyOnceWith(id);
    expect(after.componentInstance.currentId()).toBe(id);
    expect(sessionStorage.getItem('ooh.pending-conversation')).toBeNull();
    after.destroy(); window.history.replaceState(null, '', '/');
    const again = TestBed.createComponent(App); again.detectChanges(); await again.whenStable();
    expect(conversation).toHaveBeenCalledOnce();
  });
  it('opens the current address instead of an abandoned saved link', async () => {
    const saved = '12345678-1234-1234-1234-123456789012';
    const current = '12345678-1234-1234-1234-123456789013';
    const conversation = vi.fn().mockResolvedValue({id: current, title: 'Current chat', messages: []});
    TestBed.configureTestingModule({imports: [App], providers: [
      {provide: Jobs, useValue: {start: vi.fn(), stop: vi.fn(), rows: signal([]), notice: signal(''), more: signal(false)}},
      {provide: OidcSecurityService, useValue: {checkAuth: () => of({isAuthenticated: true}), isAuthenticated$: of({isAuthenticated: true})}},
      {provide: Api, useValue: {me: async () => ({access: 'approved', user_id: 'test-user', name: 'Test user', chat_tiers: [1], skills: [], requestable_tiers: [], chat_tier_titles: {}, chat_tier_thinking_switch: {}}), list: async () => [], conversation}},
    ]});
    sessionStorage.setItem('ooh.pending-conversation', saved);
    window.history.replaceState(null, '', '/?conversation=' + current);
    const view = TestBed.createComponent(App); view.detectChanges();
    await vi.waitFor(() => expect(view.componentInstance.loading()).toBe(false)); await view.whenStable();
    expect(conversation).toHaveBeenCalledExactlyOnceWith(current);
    expect(view.componentInstance.currentId()).toBe(current);
    expect(sessionStorage.getItem('ooh.pending-conversation')).toBeNull();
  });
  it('ignores non-UUID saved links before and after sign-in', async () => {
    const conversation = vi.fn();
    TestBed.configureTestingModule({imports: [App], providers: [
      {provide: Jobs, useValue: {start: vi.fn(), stop: vi.fn(), rows: signal([]), notice: signal(''), more: signal(false)}},
      {provide: OidcSecurityService, useValue: {authorize: vi.fn(), checkAuth: () => of({isAuthenticated: true}), isAuthenticated$: of({isAuthenticated: true})}},
      {provide: Api, useValue: {me: async () => ({access: 'approved', user_id: 'test-user', name: 'Test user', chat_tiers: [1], skills: [], requestable_tiers: [], chat_tier_titles: {}, chat_tier_thinking_switch: {}}), list: async () => [], conversation}},
    ]});
    window.history.replaceState(null, '', '/?conversation=not-a-uuid');
    const view = TestBed.createComponent(App); view.componentInstance.signIn();
    expect(sessionStorage.getItem('ooh.pending-conversation')).toBeNull();
    sessionStorage.setItem('ooh.pending-conversation', 'not-a-uuid');
    view.detectChanges(); await vi.waitFor(() => expect(view.componentInstance.loading()).toBe(false)); await view.whenStable();
    expect(conversation).not.toHaveBeenCalled();
    expect(sessionStorage.getItem('ooh.pending-conversation')).toBeNull();
  });
  it('formats the meta line and budget note', () => {
    expect(metaLine({role: 'assistant', content: '', created_at: '2026-11-10T08:00:00Z', tier: 2, model_title: 'Test entry', input_tokens: 12, output_tokens: 24}))
      .toBe('tier 2 · Test entry · 12 in / 24 out tokens');
    expect(metaLine({role: 'assistant', content: '', created_at: '2026-11-10T08:00:00Z', tier: 1, model_title: 'Test entry', note: 'tier 2 is over its daily budget; answered with tier 1'}))
      .toContain(' · tier 2 is over its daily budget; answered with tier 1');
  });
  async function fixture(send = vi.fn().mockRejectedValue(new ApiError(403, "You don't have tier 3. An admin can grant it."))) {
    TestBed.configureTestingModule({imports: [App], providers: [{provide: Jobs, useValue: {start: vi.fn(), stop: vi.fn(), rows: signal([]), notice: signal(''), more: signal(false)}},
      {provide: OidcSecurityService, useValue: {checkAuth: () => of({isAuthenticated: false}), isAuthenticated$: of({isAuthenticated: false})}},
      {provide: Api, useValue: {create: async () => ({id: 'test-conversation'}), list: async () => [], send}},
    ]});
    const view = TestBed.createComponent(App);
    view.detectChanges();
    view.componentInstance.signedIn.set(true);
    view.componentInstance.me.set({access: 'approved', user_id: 'test-user', name: 'Test user', chat_tiers: [1, 3], chat_tier_titles: {}, chat_tier_thinking_switch: {}, requestable_tiers: [], skills: []});
    view.componentInstance.tier = 1;
    view.detectChanges();
    await view.whenStable();
    return view;
  }
  it('offers only allowed tiers', async () => {
    const view = await fixture();
    const options = [...view.nativeElement.querySelectorAll('select option')] as HTMLOptionElement[];
    expect(options.map(option => option.textContent?.trim())).toEqual(['Auto', 'Tier 1', 'Tier 3', 'Skills', 'Request another model…']);
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
    expect(options.map(option => option.textContent?.trim())).toEqual(['Auto', 'Test main entry - Tier 1', 'Tier 3', 'Skills', 'Request another model…']);
    expect(view.nativeElement.querySelector('.ooh-label').textContent).toBe('Chat model');
    expect(select.textContent).not.toContain('Hidden entry');
  });
  it('sends Auto and shows routing from the completed stream', async () => {
    const note = 'This question may need tier 2. An admin can give you tier 2.';
    const send = vi.fn(async (_id, _text, tier, _signal, receive) => {
      expect(tier).toBe('auto');
      receive({type: 'delta', text: 'Answer'});
      receive({type: 'completed', message_id: 'message', tier: 1, model_title: 'Example',
        usage: {input_tokens: 2, output_tokens: 4}, note, thinking_applied: true,
        routing: {tier: 1, scores: {needs_tier2: 0.9}, note}});
    });
    const view = await fixture(send);
    view.componentInstance.tier = 'auto';
    view.componentInstance.draft = 'Question';
    await view.componentInstance.send(); view.detectChanges();
    expect(view.nativeElement.querySelector('.messages').textContent).toContain('auto → tier 1');
    expect(view.nativeElement.querySelector('.messages').textContent).toContain(note);
    expect(view.componentInstance.messages().at(-1)?.routing?.scores).toEqual({needs_tier2: 0.9});
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
  it('streams safe assistant text, disables sending, and renders final metadata', async () => {
    let finish!: () => void;
    const send = vi.fn(async (_id, _content, _tier, _signal, receive) => {
      receive({type: 'delta', text: '<img src=x onerror=alert(1)>\nAnswer'});
      await new Promise<void>(resolve => {finish = resolve;});
      receive({type: 'completed', message_id: 'message', tier: 1, model_title: 'Test entry', usage: {input_tokens: 2, output_tokens: 4}, note: null, thinking_applied: true});
    });
    const view = await fixture(send);
    view.componentInstance.draft = 'Question';
    const sending = view.componentInstance.send();
    await vi.waitFor(() => expect(send).toHaveBeenCalled());
    view.detectChanges();
    expect(view.nativeElement.querySelector('button[type="submit"]').disabled).toBe(true);
    expect(view.nativeElement.querySelector('.ooh-cursor')).not.toBeNull();
    expect(view.nativeElement.querySelector('.messages img')).toBeNull();
    await view.whenStable();
    expect(view.nativeElement.querySelector('.messages').textContent).toContain('Answer');
    finish(); await sending; view.detectChanges();
    expect(view.nativeElement.querySelector('.ooh-cursor')).toBeNull();
    expect(view.nativeElement.querySelector('.messages').textContent).toContain('tier 1 · Test entry · 2 in / 4 out tokens');
    expect(view.nativeElement.querySelectorAll('time').length).toBe(2);
    expect(view.componentInstance.messages().every(message => !Number.isNaN(Date.parse(message.created_at)))).toBe(true);
  });
  it.each([true, false])('captures thinking off and the actual model support=%s in final metadata', async applied => {
    const send = vi.fn(async (_id, _content, _tier, _signal, receive, thinking) => {
      expect(thinking).toBe(false);
      receive({type: 'delta', text: 'Answer'});
      receive({type: 'completed', message_id: 'message', tier: 3, model_title: 'Test backup',
        usage: {input_tokens: 2, output_tokens: 4}, note: null, thinking_applied: applied});
    });
    const view = await fixture(send);
    const app = view.componentInstance;
    app.me.update(me => me ? {...me, chat_tier_thinking_switch: {'1': true}} : null);
    view.detectChanges(); await view.whenStable();
    (view.nativeElement.querySelector('[role="switch"]') as HTMLButtonElement).click();
    app.draft = 'Question';
    await app.send(); view.detectChanges();
    expect(send).toHaveBeenCalledOnce();
    const meta = view.nativeElement.querySelector('.ooh-msg--assistant > .ooh-msg__meta').textContent;
    expect(meta).toContain('tier 3 · Test backup');
    expect(meta.includes('thinking off not supported by this model')).toBe(!applied);
  });
  const completion = {type: 'completed', message_id: 'message', tier: 1, model_title: 'Test entry',
    usage: {input_tokens: 2, output_tokens: 4}, note: null, thinking_applied: true} as const;
  it('enables the composer at completed and applies a later title immediately without reordering', async () => {
    let receive!: (event: ChatEvent) => void;
    let finish!: () => void;
    const send = vi.fn(async (_id, _content, _tier, _signal, callback) => {
      receive = callback;
      callback({type: 'delta', text: 'Answer'});
      await new Promise<void>(resolve => {finish = resolve;});
    });
    const view = await fixture(send);
    const app = view.componentInstance;
    let resolveList!: (rows: {id: string; title: string; updated_at: string}[]) => void;
    vi.spyOn(TestBed.inject(Api), 'list').mockImplementation(() => new Promise(resolve => {resolveList = resolve;}));
    app.draft = 'Question';
    const sending = app.send();
    await vi.waitFor(() => expect(send).toHaveBeenCalledOnce());
    receive(completion);
    // The list response can finish after the title event.
    receive({type: 'title', conversation_id: 'test-conversation', title: '<b>Short title</b>'});
    expect(app.title()).toBe('<b>Short title</b>');
    resolveList([
      {id: 'other', title: 'Other', updated_at: '2026-11-10T09:00:00Z'},
      {id: 'test-conversation', title: 'Question', updated_at: '2026-11-10T08:00:00Z'},
    ]);
    await vi.waitFor(() => expect(app.conversations()[1]?.title).toBe('<b>Short title</b>'));
    view.detectChanges();
    await view.whenStable();
    const composer = view.nativeElement.querySelector('textarea') as HTMLTextAreaElement;
    expect(composer.disabled).toBe(false);
    composer.value = 'Next question';
    composer.dispatchEvent(new Event('input'));
    view.detectChanges();
    expect(view.nativeElement.querySelector('button[type="submit"]').disabled).toBe(false);
    expect(view.nativeElement.querySelector('.ooh-cursor')).toBeNull();
    expect(view.nativeElement.querySelector('h1').textContent).toBe('<b>Short title</b>');
    expect(view.nativeElement.querySelector('h1 b')).toBeNull();
    expect(app.conversations()).toEqual([
      {id: 'other', title: 'Other', updated_at: '2026-11-10T09:00:00Z'},
      {id: 'test-conversation', title: '<b>Short title</b>', updated_at: '2026-11-10T08:00:00Z'},
    ]);
    finish(); await sending;
    expect(app.messages().at(-1)?.outcome).toBe('completed');
    expect(app.notice()).toBe('');
  });
  it('keeps an old stream title with its conversation and does not unlock a newer answer', async () => {
    const callbacks: ((event: ChatEvent) => void)[] = [];
    const finishes: (() => void)[] = [];
    const send = vi.fn(async (_id, _content, _tier, _signal, receive) => {
      callbacks.push(receive);
      await new Promise<void>(resolve => {finishes.push(resolve);});
    });
    const view = await fixture(send);
    const app = view.componentInstance;
    vi.spyOn(TestBed.inject(Api), 'create').mockResolvedValueOnce({id: 'test-conversation'}).mockResolvedValueOnce({id: 'second-conversation'});
    app.draft = 'First';
    const first = app.send();
    await vi.waitFor(() => expect(send).toHaveBeenCalledTimes(1));
    callbacks[0](completion);
    await Promise.resolve();
    app.newChat();
    app.conversations.set([{id: 'test-conversation', title: 'First', updated_at: 'unchanged'}]);
    callbacks[0]({type: 'title', conversation_id: 'test-conversation', title: 'First conversation title'});
    expect(app.title()).toBe('New chat');
    expect(app.conversations()[0].title).toBe('First conversation title');
    app.draft = 'Second';
    const second = app.send();
    await vi.waitFor(() => expect(send).toHaveBeenCalledTimes(2));
    finishes[0](); await first;
    expect(app.streaming()).toBe(true);
    callbacks[1](completion);
    finishes[1](); await second;
    expect(app.streaming()).toBe(false);
  });
  it('cancels every pending title stream on destruction', async () => {
    const callbacks: ((event: ChatEvent) => void)[] = [];
    const signals: AbortSignal[] = [];
    const finishes: (() => void)[] = [];
    const send = vi.fn(async (_id, _content, _tier, signal, receive) => {
      signals.push(signal);
      callbacks.push(receive);
      await new Promise<void>(resolve => {finishes.push(resolve);});
    });
    const view = await fixture(send);
    const app = view.componentInstance;
    app.draft = 'First';
    const first = app.send();
    await vi.waitFor(() => expect(send).toHaveBeenCalledTimes(1));
    callbacks[0](completion);
    app.draft = 'Second';
    const second = app.send();
    await vi.waitFor(() => expect(send).toHaveBeenCalledTimes(2));
    callbacks[1](completion);
    view.destroy();
    expect(signals.every(signal => signal.aborted)).toBe(true);
    callbacks[0]({type: 'title', conversation_id: 'test-conversation', title: 'Late title'});
    expect(app.title()).toBe('First');
    finishes.forEach(finish => finish());
    await Promise.all([first, second]);
  });
  it('keeps the job card when the model follow-up fails after starting the job', async () => {
    const job = {job_id:'12345678-1234-1234-1234-123456789012',skill:'slides',title:'Presentation (.pptx)',label:'Water cycle',status:'queued' as const};
    const view = await fixture(vi.fn(async (_id, _content, _tier, _signal, receive) => {
      receive({type:'job',...job});
      receive({type:'failed',error:{code:'unavailable',message:'The job has started, but the model could not finish its answer.'}});
    }));
    const jobs = TestBed.inject(Jobs);
    Object.assign(jobs, {add: vi.fn()});
    view.componentInstance.draft='Make slides';await view.componentInstance.send();view.detectChanges();
    expect(jobs.add).toHaveBeenCalledWith({type:'job',...job});
    expect(view.nativeElement.querySelector('.messages app-job-card').textContent).toContain('Water cycle');
    expect(view.nativeElement.querySelector('[role="alert"]').textContent).toBe('The job has started, but the model could not finish its answer.');
  });
  it('keeps a completed answer when the optional title stream breaks', async () => {
    const view = await fixture(vi.fn(async (_id, _content, _tier, _signal, receive) => {
      receive({type: 'delta', text: 'Answer'});
      receive(completion);
      throw new Error('Title transport broke');
    }));
    view.componentInstance.draft = 'Default title';
    await view.componentInstance.send();
    expect(view.componentInstance.messages().at(-1)?.outcome).toBe('completed');
    expect(view.componentInstance.title()).toBe('Default title');
    expect(view.componentInstance.notice()).toBe('');
  });
  it('retains the default title when no title event arrives', async () => {
    const view = await fixture(vi.fn(async (_id, _content, _tier, _signal, receive) => {
      receive({type: 'delta', text: 'Answer'});
      receive(completion);
    }));
    view.componentInstance.draft = 'Default title';
    await view.componentInstance.send();
    expect(view.componentInstance.title()).toBe('Default title');
    expect(view.componentInstance.notice()).toBe('');
  });
  it('parses and fills thinking events before and between answer deltas', async () => {
    const wire = [
      {type: 'thinking', text: '<b>First thought</b> '}, {type: 'delta', text: 'First answer '},
      {type: 'thinking', text: 'next thought'}, {type: 'delta', text: 'next answer'}, completion,
    ].map(event => 'data: ' + JSON.stringify(event) + '\n\n').join('');
    const send = vi.fn(async (_id, _content, _tier, _signal, receive) => {
      const bytes = new TextEncoder().encode(wire);
      await readStream(new ReadableStream({start(controller) {
        for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
        controller.close();
      }}), receive);
    });
    const view = await fixture(send); view.componentInstance.draft = 'Question';
    await view.componentInstance.send(); view.detectChanges(); await view.whenStable(); view.detectChanges();
    const answer = view.componentInstance.messages().at(-1)!;
    expect(answer.thinking).toBe('<b>First thought</b> next thought');
    expect(answer.content).toBe('First answer next answer');
    expect(answer.outcome).toBe('completed');
    expect(view.nativeElement.querySelector('details pre').textContent).toBe(answer.thinking);
    expect(view.nativeElement.querySelector('details b')).toBeNull();
    expect(view.nativeElement.querySelector('details').open).toBe(false);
  });
  it('keeps failed thinking with an empty answer and displays only thinking and the outcome', async () => {
    const view = await fixture(vi.fn(async (_id, _content, _tier, _signal, receive) => {
      receive({type: 'thinking', text: 'Partial thought'});
      receive({type: 'failed', error: {code: 'unavailable', message: 'The model did not answer. Try again.'}});
    }));
    view.componentInstance.draft = 'Question'; await view.componentInstance.send();
    view.detectChanges(); await view.whenStable(); view.detectChanges();
    const answer = view.componentInstance.messages().at(-1)!;
    expect(answer.content).toBe(''); expect(answer.thinking).toBe('Partial thought'); expect(answer.outcome).toBe('failed');
    const article = view.nativeElement.querySelector('.ooh-msg--assistant');
    expect(article.querySelector('details pre').textContent).toBe('Partial thought');
    expect(article.querySelector('.ooh-msg__body,.message-actions,time')).toBeNull();
    expect(article.querySelector('.ooh-msg__meta').textContent).toContain('Answer interrupted');
  });
  async function accessFixture(access: 'approved' | 'pending' | 'rejected' | 'closed' | 'unavailable') {
    const api = {
      me: access === 'unavailable'
        ? vi.fn().mockRejectedValue(new ApiError(503, 'Your access could not be checked. Try again.'))
        : vi.fn().mockResolvedValue({access, user_id: 'test-user', name: 'Given Family', chat_tiers: [1], chat_tier_titles: {}, chat_tier_thinking_switch: {}, requestable_tiers: [], skills: []}),
      list: vi.fn().mockResolvedValue([]),
      conversation: vi.fn(), create: vi.fn(), send: vi.fn(),
    };
    const logoff = vi.fn(() => of(undefined));
    TestBed.configureTestingModule({imports: [App], providers: [{provide: Jobs, useValue: {start: vi.fn(), stop: vi.fn(), rows: signal([]), notice: signal(''), more: signal(false)}},
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
    TestBed.configureTestingModule({providers: [{provide: Jobs, useValue: {start: vi.fn(), stop: vi.fn(), rows: signal([]), notice: signal(''), more: signal(false)}},
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
