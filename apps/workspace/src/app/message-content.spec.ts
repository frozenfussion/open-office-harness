// SPDX-License-Identifier: AGPL-3.0-only
import { TestBed } from '@angular/core/testing';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MessageContent, formatMessageTime } from './message-content';

describe('message content', () => {
  const clipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
  afterEach(() => {
    TestBed.resetTestingModule(); vi.useRealTimers(); vi.restoreAllMocks();
    if (clipboard) Object.defineProperty(navigator, 'clipboard', clipboard);
    else Reflect.deleteProperty(navigator, 'clipboard');
  });
  async function fixture(role: 'user' | 'assistant', content: string, streaming = false) {
    TestBed.configureTestingModule({imports: [MessageContent]});
    const view = TestBed.createComponent(MessageContent);
    view.componentRef.setInput('role', role);
    view.componentRef.setInput('content', content);
    view.componentRef.setInput('createdAt', '2026-11-10T08:39:00Z');
    view.componentRef.setInput('streaming', streaming);
    view.detectChanges(); await view.whenStable(); view.detectChanges();
    return view;
  }
  it.each(['user', 'assistant'] as const)('shows browser-local date and time on %s messages', async role => {
    const view = await fixture(role, 'Text');
    const time = view.nativeElement.querySelector('time');
    const expected = new Intl.DateTimeFormat('en-GB', {day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'}).format(new Date('2026-11-10T08:39:00Z'));
    expect(time.getAttribute('datetime')).toBe('2026-11-10T08:39:00Z');
    expect(time.textContent).toBe(expected);
    expect(formatMessageTime('invalid')).toBe('Time unavailable');
  });
  it('shows stored thinking collapsed above the answer as plain text, with independent copying', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {writeText}});
    const view = await fixture('assistant', '**Answer only**');
    const text = '<script>alert(1)</script> **Thought** $x$\nNext line';
    view.componentRef.setInput('thinking', text); view.detectChanges();
    const details = view.nativeElement.querySelector('details') as HTMLDetailsElement;
    expect(details.open).toBe(false);
    expect(details.querySelector('summary')?.textContent).toContain('Thinking');
    expect(details.querySelector('pre')?.textContent).toBe(text);
    expect(details.querySelector('script,strong,.katex')).toBeNull();
    expect(details.compareDocumentPosition(view.nativeElement.querySelector('.ooh-msg__body')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    details.open = true;
    vi.useFakeTimers();
    (details.querySelector('button') as HTMLButtonElement).click(); await Promise.resolve(); view.detectChanges();
    expect(writeText).toHaveBeenLastCalledWith(text);
    expect(details.querySelector('button')?.textContent).toBe('Copied');
    vi.advanceTimersByTime(2000); view.detectChanges();
    expect(details.querySelector('button')?.textContent).toBe('Copy thinking');
    view.nativeElement.querySelector('.message-actions button').click(); await Promise.resolve();
    expect(writeText).toHaveBeenLastCalledWith('**Answer only**');
  });
  it('fills thinking live without reopening or resetting the disclosure', async () => {
    const view = await fixture('assistant', '', true);
    expect(view.nativeElement.querySelector('details')).toBeNull();
    view.componentRef.setInput('thinking', 'First thought'); view.detectChanges();
    const details = view.nativeElement.querySelector('details') as HTMLDetailsElement;
    expect(details.open).toBe(false);
    expect(details.querySelector('summary')?.textContent).toContain('Thinking…');
    details.open = true;
    view.componentRef.setInput('thinking', 'First thought, next thought'); view.detectChanges();
    expect(details.open).toBe(true);
    expect(details.querySelector('pre')?.textContent).toBe('First thought, next thought');
    view.componentRef.setInput('streaming', false); view.detectChanges();
    expect(details.querySelector('summary')?.textContent?.trim()).toBe('›Thinking');
  });
  it('omits answer controls and the empty answer body when there is thinking only', async () => {
    const view = await fixture('assistant', '');
    view.componentRef.setInput('thinking', 'Thought only'); view.detectChanges();
    expect(view.nativeElement.querySelector('details pre').textContent).toBe('Thought only');
    expect(view.nativeElement.querySelector('.ooh-msg__body,.message-actions,time')).toBeNull();
    expect(view.nativeElement.querySelectorAll('button')).toHaveLength(1);
    expect(view.nativeElement.querySelector('button').textContent).toBe('Copy thinking');
  });
  it('never shows thinking for user messages or empty assistant thinking', async () => {
    const view = await fixture('user', 'Question');
    view.componentRef.setInput('thinking', 'Ignored'); view.detectChanges();
    expect(view.nativeElement.querySelector('details')).toBeNull();
    view.componentRef.setInput('role', 'assistant'); view.componentRef.setInput('thinking', ''); view.detectChanges();
    expect(view.nativeElement.querySelector('details')).toBeNull();
  });
  it('keeps user Markdown and HTML as original plain text', async () => {
    const content = '# Heading\n<script>alert(1)</script> $x^2$';
    const view = await fixture('user', content);
    expect(view.nativeElement.querySelector('.plain-message').textContent).toBe(content);
    expect(view.nativeElement.querySelector('h1,script,.katex')).toBeNull();
  });
  it.each(['user', 'assistant'] as const)('copies original %s text and shows Copied for two seconds', async role => {
    const content = '**Original** $x^2$';
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {writeText}});
    const view = await fixture(role, content);
    vi.useFakeTimers();
    const button = view.nativeElement.querySelector('.message-actions button');
    button.click(); await Promise.resolve(); view.detectChanges();
    expect(writeText).toHaveBeenCalledExactlyOnceWith(content);
    expect(button.textContent).toBe('Copied');
    vi.advanceTimersByTime(1999); view.detectChanges(); expect(button.textContent).toBe('Copied');
    vi.advanceTimersByTime(1); view.detectChanges(); expect(button.textContent).toBe('Copy');
  });
  it('copies code without Markdown fences', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {writeText}});
    const view = await fixture('assistant', '```js\nconst n = 1;\n```');
    const button = view.nativeElement.querySelector('pre button');
    expect(button.textContent).toBe('Copy code');
    button.click(); await Promise.resolve();
    expect(writeText).toHaveBeenCalledExactlyOnceWith('const n = 1;');
    expect(button.textContent).toBe('Copied');
  });
  it('throttles streamed rendering to one pass per 100 ms and flushes completion', async () => {
    const view = await fixture('assistant', 'Start', true);
    vi.useFakeTimers({toFake: ['setTimeout', 'clearTimeout']});
    const time = vi.spyOn(performance, 'now');
    time.mockReturnValue(1_000_000);
    view.componentRef.setInput('content', 'First'); view.detectChanges();
    const host = view.nativeElement.querySelector('.ooh-markdown');
    const changes = new MutationObserver(() => undefined);
    changes.observe(host, {childList: true});
    for (let count = 1; count <= 9; count++) {
      time.mockReturnValue(1_000_000 + count * 10);
      view.componentRef.setInput('content', `Chunk ${count}`); view.detectChanges();
    }
    expect(host.textContent).toContain('First');
    expect(changes.takeRecords()).toHaveLength(0);
    time.mockReturnValue(1_000_100); vi.advanceTimersByTime(100);
    expect(changes.takeRecords()).toHaveLength(1);
    expect(view.nativeElement.querySelector('.ooh-markdown').textContent).toContain('Chunk 9');
    view.componentRef.setInput('content', '**Done**');
    view.componentRef.setInput('streaming', false); view.detectChanges();
    expect(view.nativeElement.querySelector('strong').textContent).toBe('Done');
    changes.disconnect();
  });
});
