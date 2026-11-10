// SPDX-License-Identifier: AGPL-3.0-only
import { afterRenderEffect, Component, computed, ElementRef, inject, input, OnDestroy, output, PendingTasks, signal, viewChild } from '@angular/core';

export function formatMessageTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Time unavailable' : new Intl.DateTimeFormat('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).format(date);
}
@Component({
  selector: 'app-message-content',
  template: `
    <div class="ooh-msg__body">
      @if (role() === 'assistant') {
        <div #rich class="ooh-markdown" (click)="copyCode($event)"></div>
        @if (streaming()) { <span class="ooh-cursor" aria-label="Streaming"></span> }
      } @else { <span class="plain-message">{{ content() }}</span> }
    </div>
    <div class="message-actions ooh-msg__meta">
      <time [attr.datetime]="createdAt()">{{ timestamp() }}</time>
      <button class="ooh-btn ooh-btn--ghost ooh-btn--sm" (click)="copyMessage()">{{ copied() ? 'Copied' : 'Copy' }}</button>
      @if (copyFailed()) { <span role="status">Copy failed. Try again.</span> }
    </div>`,
  styles: `:host{display:block;max-width:100%}.plain-message{white-space:pre-wrap}.message-actions{display:flex;align-items:center;flex-wrap:wrap;gap:var(--space-2)}`,
})
export class MessageContent implements OnDestroy {
  readonly content = input('');
  readonly role = input<'user' | 'assistant'>('assistant');
  readonly createdAt = input('');
  readonly streaming = input(false);
  readonly rendered = output<void>();
  readonly timestamp = computed(() => formatMessageTime(this.createdAt()));
  readonly copied = signal(false);
  readonly copyFailed = signal(false);
  private readonly pendingTasks = inject(PendingTasks);
  private renderer?: typeof import('./rich-text');
  private rendererLoading = false;
  private rendererFailed = false;
  private destroyed = false;
  private readonly rich = viewChild<ElementRef<HTMLElement>>('rich');
  private renderTimer?: ReturnType<typeof setTimeout>;
  private copyTimer?: ReturnType<typeof setTimeout>;
  private readonly codeTimers = new Map<number, ReturnType<typeof setTimeout>>();
  private codeBlocks: string[] = [];
  private lastRender = -Infinity;
  constructor() {
    afterRenderEffect(() => {
      this.content(); this.role(); this.streaming();
      this.requestRender();
    });
  }
  private requestRender(): void {
    if (this.destroyed || !this.rich()) return;
    if (!this.renderer && !this.rendererFailed) {
      if (!this.rendererLoading) {
        this.rendererLoading = true;
        const done = this.pendingTasks.add();
        void import('./rich-text').then(renderer => {
          this.renderer = renderer; this.requestRender();
        }).catch(() => {
          this.rendererFailed = true; this.requestRender();
        }).finally(done);
      }
      return;
    }
    const remaining = 100 - (performance.now() - this.lastRender);
    if (!this.streaming() || remaining <= 0) {
      clearTimeout(this.renderTimer); this.renderTimer = undefined; this.paint();
    } else if (this.renderTimer === undefined) {
      this.renderTimer = setTimeout(() => { this.renderTimer = undefined; this.paint(); }, remaining);
    }
  }
  private paint(): void {
    const host = this.rich()?.nativeElement;
    if (!host) return;
    try {
      if (!this.renderer) throw new Error('Renderer unavailable');
      const rendered = this.renderer.renderRichText(this.content());
      this.codeBlocks = rendered.codeBlocks;
      for (const code of rendered.fragment.querySelectorAll('pre > code[data-ooh-code]')) {
        const index = Number(code.getAttribute('data-ooh-code'));
        const button = document.createElement('button');
        button.type = 'button'; button.className = 'ooh-btn ooh-btn--ghost ooh-btn--sm';
        button.dataset['codeCopy'] = String(index);
        button.textContent = this.codeTimers.has(index) ? 'Copied' : 'Copy code';
        code.parentElement!.prepend(button);
      }
      host.replaceChildren(rendered.fragment);
    } catch {
      this.codeBlocks = [];
      host.replaceChildren(document.createTextNode(this.content()));
    }
    this.lastRender = performance.now();
    this.rendered.emit();
  }
  async copyMessage(): Promise<void> {
    try {
      await navigator.clipboard.writeText(this.content());
      if (this.destroyed) return;
      this.copyFailed.set(false); this.copied.set(true);
      clearTimeout(this.copyTimer);
      this.copyTimer = setTimeout(() => this.copied.set(false), 2000);
    } catch { this.copyFailed.set(true); }
  }
  async copyCode(event: Event): Promise<void> {
    const button = event.target instanceof Element ? event.target.closest<HTMLButtonElement>('button[data-code-copy]') : null;
    if (!button || !this.rich()?.nativeElement.contains(button)) return;
    const index = Number(button.dataset['codeCopy']);
    const text = this.codeBlocks[index];
    if (text === undefined) return;
    try {
      await navigator.clipboard.writeText(text);
      if (this.destroyed) return;
      this.copyFailed.set(false); button.textContent = 'Copied';
      clearTimeout(this.codeTimers.get(index));
      this.codeTimers.set(index, setTimeout(() => {
        this.codeTimers.delete(index);
        const current = this.rich()?.nativeElement.querySelector<HTMLButtonElement>(`button[data-code-copy="${index}"]`);
        if (current) current.textContent = 'Copy code';
      }, 2000));
    } catch { this.copyFailed.set(true); }
  }
  ngOnDestroy(): void {
    this.destroyed = true;
    clearTimeout(this.renderTimer); clearTimeout(this.copyTimer);
    for (const timer of this.codeTimers.values()) clearTimeout(timer);
  }
}
