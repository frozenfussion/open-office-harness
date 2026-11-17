// SPDX-License-Identifier: AGPL-3.0-only
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { OidcSecurityService } from 'angular-auth-oidc-client';
import { of } from 'rxjs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from './app';
import { Api, ApiError, Picture } from './api';
import { Jobs } from './jobs';
import { ChatPicture } from './chat-picture';
import { CONFIG } from './config';

const picture: Picture = {upload_id: 'test-upload', file_name: 'picture.png', mime: 'image/png', size_bytes: 8};
const completed = {type: 'completed', message_id: 'answer', tier: 1, model_title: 'Test entry', usage: {input_tokens: 1, output_tokens: 1}};
afterEach(() => { TestBed.resetTestingModule(); vi.restoreAllMocks(); vi.useRealTimers(); window.history.replaceState(null, '', '/'); });
function urls() {
  Object.defineProperty(URL, 'createObjectURL', {configurable: true, value: vi.fn().mockReturnValue('blob:picture')});
  Object.defineProperty(URL, 'revokeObjectURL', {configurable: true, value: vi.fn()});
}
async function fixture(overrides: Partial<Api> = {}) {
  urls();
  const api = {upload: vi.fn().mockResolvedValue(picture), picture: vi.fn().mockResolvedValue(new Blob(['picture'])),
    create: vi.fn().mockResolvedValue({id: 'test-chat'}), list: vi.fn().mockResolvedValue([]),
    send: vi.fn(async (_id, _content, _tier, _signal, receive) => receive(completed)), export: vi.fn().mockResolvedValue('test-chat.docx'), ...overrides};
  TestBed.configureTestingModule({imports: [App], providers: [
    {provide: Api, useValue: api},
    {provide: Jobs, useValue: {start: vi.fn(), stop: vi.fn(), rows: signal([]), notice: signal(''), more: signal(false)}},
    {provide: OidcSecurityService, useValue: {checkAuth: () => of({isAuthenticated: false}), isAuthenticated$: of({isAuthenticated: false})}},
  ]});
  const view = TestBed.createComponent(App); view.detectChanges();
  const app = view.componentInstance;
  app.signedIn.set(true); app.me.set({access: 'approved', user_id: 'test-user', name: '', chat_tiers: [1], chat_tier_titles: {}, chat_tier_thinking_switch: {}, skills: [], requestable_tiers: [], upload_max_bytes: 1048576});
  app.tier = 1; view.detectChanges();
  return {view, app, api};
}
async function choose(app: App, file = new File(['picture'], 'picture.png', {type: 'image/png'})) {
  const input = {files: [file], value: 'picture.png'};
  await app.choosePicture({target: input} as unknown as Event);
  expect(input.value).toBe('');
}
describe('Attach picture', () => {
  it.each(['image/png', 'image/jpeg'])('uploads %s and shows name, type, size and preview', async type => {
    const {app, api, view} = await fixture();
    const file = new File(['picture'], 'picture.png', {type}); await choose(app, file); view.detectChanges();
    expect(api.upload).toHaveBeenCalledWith(file);
    expect(view.nativeElement.querySelector('.picture-preview img').src).toBe('blob:picture');
    expect(view.nativeElement.querySelector('.picture-preview').textContent).toContain('picture.png · image/png · 8 bytes');
    expect(view.nativeElement.textContent).toContain('up to 1 MB');
    expect(view.nativeElement.querySelector('input[type=file]').accept).toBe('image/png,image/jpeg');
  });
  it.each([
    [new File(['x'], 'bad.gif', {type: 'image/gif'}), 'Only PNG and JPEG pictures can be attached.'],
    [new File([new Uint8Array(1048577)], 'big.png', {type: 'image/png'}), 'This picture is larger than the limit of 1 MB.'],
  ])('refuses %s before upload', async (file, notice) => {
    const {app, api} = await fixture(); await choose(app, file);
    expect(api.upload).not.toHaveBeenCalled(); expect(app.notice()).toBe(notice);
  });
  it('replaces and removes the preview, releasing local URLs without a delete request', async () => {
    const {app, api} = await fixture(); await choose(app); await choose(app);
    expect(api.upload).toHaveBeenCalledTimes(2); expect(URL.revokeObjectURL).toHaveBeenCalledOnce();
    app.removePicture(); expect(app.attachment()).toBeNull(); expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2);
  });
  it('disables Send during upload and shows the API upload error', async () => {
    let reject!: (error: unknown) => void;
    const {app, view} = await fixture({upload: vi.fn(() => new Promise<Picture>((_resolve, fail) => { reject = fail; }))});
    app.draft = 'Question'; const pending = choose(app); view.detectChanges();
    expect(view.nativeElement.querySelector('button[type=submit]').disabled).toBe(true);
    reject(new ApiError(429, "You have reached today's limit for pictures.", 'upload_limit')); await pending;
    expect(app.notice()).toBe("You have reached today's limit for pictures."); expect(app.attachment()).toBeNull();
  });
  it('ignores an upload that finishes after switching chats', async () => {
    let resolve!: (picture: Picture) => void;
    const {app} = await fixture({upload: vi.fn(() => new Promise<Picture>(done => {resolve = done;}))});
    const pending = choose(app); app.newChat(); resolve(picture); await pending;
    expect(app.attachment()).toBeNull(); expect(URL.createObjectURL).not.toHaveBeenCalled();
  });
  it('clears the preview as soon as the answer stream opens, before any output', async () => {
    let finish!: () => void;
    const send = vi.fn(async (_id, _text, _tier, _signal, receive, _thinking, _upload, connected) => {
      connected(); await new Promise<void>(done => {finish = done;}); receive(completed);
    });
    const {app} = await fixture({send}); await choose(app); app.draft = 'Question';
    const pending = app.send(); await vi.waitFor(() => expect(send).toHaveBeenCalled());
    expect(app.attachment()).toBeNull(); expect(app.messages()[0].picture).toEqual(picture);
    finish(); await pending;
  });
  it('sends upload_id and immediately shows the local picture without fetching it', async () => {
    let finish!: () => void;
    const send = vi.fn(async (_id, _text, _tier, _signal, receive, _thinking, upload) => {
      expect(upload).toBe('test-upload'); receive({type: 'delta', text: 'Answer'});
      await new Promise<void>(done => {finish = done;}); receive(completed);
    });
    const {app, api, view} = await fixture({send}); await choose(app); app.draft = 'Question';
    const pending = app.send(); await vi.waitFor(() => expect(send).toHaveBeenCalled()); view.detectChanges();
    expect(view.nativeElement.querySelector('.messages img').alt).toBe('picture.png');
    expect(api.picture).not.toHaveBeenCalled(); expect(app.attachment()).toBeNull();
    finish(); await pending; app.newChat(); expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:picture');
  });
  it.each(['invalid_input', 'not_found', 'upload_not_found', 'not_allowed', 'no_tier', 'tier_not_allowed', 'rights_unavailable', 'unauthorized'])('restores text and preview when %s means nothing was stored', async code => {
    const {app} = await fixture({send: vi.fn().mockRejectedValue(new ApiError(400, 'Refused', code))});
    await choose(app); app.draft = 'Question'; await app.send();
    expect(app.messages()).toEqual([]); expect(app.draft).toBe('Question'); expect(app.attachment()?.picture).toEqual(picture);
  });
  it('clears an already used picture and restores the question with the prescribed notice', async () => {
    const {app} = await fixture({send: vi.fn().mockRejectedValue(new ApiError(409, 'Used', 'upload_used'))});
    await choose(app); app.draft = 'Question'; await app.send();
    expect(app.messages()).toEqual([]); expect(app.draft).toBe('Question'); expect(app.attachment()).toBeNull();
    expect(app.notice()).toBe('This picture was already sent. Attach it again to send it once more.');
  });
  it.each(['image_refused', 'rate_limited', 'budget_exceeded', 'no_model', 'unavailable'])('keeps the question and clears the preview after %s', async code => {
    const {app} = await fixture({send: vi.fn().mockRejectedValue(new ApiError(502, 'Try again', code))});
    await choose(app); app.draft = 'Question'; await app.send();
    expect(app.messages()[0].picture).toEqual(picture); expect(app.draft).toBe(''); expect(app.attachment()).toBeNull();
    expect(app.notice()).toBe('Try again');
  });
});
describe('Saved picture', () => {
  it('fetches the owned blob and releases its URL when the message leaves the screen', async () => {
    urls(); const api = {picture: vi.fn().mockResolvedValue(new Blob(['picture']))};
    TestBed.configureTestingModule({imports: [ChatPicture], providers: [{provide: Api, useValue: api}]});
    const view = TestBed.createComponent(ChatPicture); view.componentRef.setInput('picture', picture);
    view.detectChanges(); await view.whenStable(); view.detectChanges();
    expect(api.picture).toHaveBeenCalledWith('test-upload'); expect(view.nativeElement.querySelector('img').alt).toBe('picture.png');
    expect(view.nativeElement.querySelector('figcaption').textContent).toBe('picture.png');
    view.destroy(); expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:picture');
  });
});
describe('Export to Word', () => {
  it('enables only for a saved conversation with messages while no answer is streaming', async () => {
    const {app, view, api} = await fixture(); const button = () => view.nativeElement.querySelector('.export-word') as HTMLButtonElement;
    expect(button().disabled).toBe(true);
    app.currentId.set('test-chat'); view.detectChanges(); expect(button().disabled).toBe(true);
    app.messages.set([{role: 'user', content: 'Question', created_at: ''}]); view.detectChanges(); expect(button().disabled).toBe(false);
    app.streaming.set(true); view.detectChanges(); expect(button().disabled).toBe(true);
    app.streaming.set(false); await app.exportWord(); view.detectChanges();
    expect(api.export).toHaveBeenCalledWith('test-chat'); expect(view.nativeElement.textContent).toContain('Saved: test-chat.docx');
  });
  it.each(['attachment; filename="my-chat.docx"', ''])('downloads an authenticated Word blob with filename header %s', async disposition => {
    urls(); vi.useFakeTimers();
    TestBed.configureTestingModule({providers: [{provide: CONFIG, useValue: {apiBase: '/api'}}, {provide: OidcSecurityService, useValue: {getAccessToken: () => of('test-token')}}]});
    const request = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('PK docx', {headers: {'Content-Disposition': disposition}}));
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const filename = await TestBed.inject(Api).export('test-chat');
    expect(filename).toBe(disposition ? 'my-chat.docx' : 'chat.docx');
    expect(request.mock.calls[0][0]).toBe('/api/conversations/test-chat/export');
    expect(request.mock.calls[0][1]?.headers).toMatchObject({Authorization: 'Bearer test-token'});
    expect((click.mock.instances[0] as HTMLAnchorElement).download).toBe(filename);
    expect(URL.createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    await vi.advanceTimersByTimeAsync(1000); expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:picture');
  });
  it('uploads raw bytes with MIME and encoded name, fetches pictures with bearer auth, and sends upload_id', async () => {
    TestBed.configureTestingModule({providers: [{provide: CONFIG, useValue: {apiBase: '/api'}}, {provide: OidcSecurityService, useValue: {getAccessToken: () => of('test-token')}}]});
    const request = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify(picture)))
      .mockResolvedValueOnce(new Response('picture')).mockResolvedValueOnce(new Response('', {headers: {'Content-Type': 'text/event-stream'}}));
    const api = TestBed.inject(Api); const file = new File(['picture'], 'two words.png', {type: 'image/png'});
    await api.upload(file); await api.picture('test-upload'); await api.send('chat', 'Question', 1, new AbortController().signal, () => {}, true, 'test-upload');
    expect(request.mock.calls[0][1]).toMatchObject({method: 'POST', body: file, headers: {'Content-Type': 'image/png', 'X-File-Name': 'two%20words.png', Authorization: 'Bearer test-token'}});
    expect(request.mock.calls[1][0]).toBe('/api/uploads/test-upload');
    expect(request.mock.calls[1][1]?.headers).toMatchObject({Authorization: 'Bearer test-token'});
    expect(JSON.parse(request.mock.calls[2][1]?.body as string).upload_id).toBe('test-upload');
  });
});
