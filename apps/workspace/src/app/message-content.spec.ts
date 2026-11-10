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
