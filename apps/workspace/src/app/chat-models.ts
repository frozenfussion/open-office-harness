// SPDX-License-Identifier: AGPL-3.0-only
import { Component, computed, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api, ApiError, Me } from './api';

@Component({
  selector: 'app-chat-models', imports: [FormsModule], templateUrl: './chat-models.html', styleUrl: './chat-models.css',
})
export class ChatModels {
  private readonly api = inject(Api);
  readonly me = input.required<Me>();
  readonly tier = input<number | null>(null);
  readonly busy = input(false);
  readonly tierChange = output<number>();
  readonly panel = signal(false);
  readonly skillsPanel = signal(false);
  readonly skillPanel = signal(false);
  readonly requestSkill = signal<string | null>(null);
  private readonly pendingSkills = signal<string[]>([]);
  skillReason = '';
  readonly skillChoices = computed(() => (this.me().requestable_skills ?? []).map(row => ({...row, requested: this.pendingSkills().includes(row.name) ? 'pending' as const : row.requested})));
  readonly selectedSkill = computed(() => this.skillChoices().find(row => row.name === this.requestSkill()));
  readonly requesting = signal(false);
  readonly notice = signal('');
  private readonly pending = signal<number[]>([]);
  private readonly preferences = signal<Record<string, boolean>>({});
  readonly switchAvailable = computed(() => this.tier() !== null && this.me().chat_tier_thinking_switch?.[String(this.tier())] === true);
  readonly thinking = computed(() => {
    if (!this.switchAvailable()) return true;
    const tier = String(this.tier());
    if (this.preferences()[tier] !== undefined) return this.preferences()[tier];
    try { return localStorage.getItem('ooh.thinking.' + tier) !== 'false'; }
    catch { return true; }
  });
  readonly choices = computed(() => (this.me().requestable_tiers ?? []).filter(row => row.tier !== 99 && !this.me().chat_tiers.includes(row.tier))
    .map(row => ({...row, requested: this.pending().includes(row.tier) ? 'pending' as const : row.requested})));
  readonly selected = computed(() => this.choices().find(row => row.tier === this.requestTier()));
  readonly requestTier = signal<number | null>(null);
  reason = '';
  label(tier: number): string {
    const title = this.me().chat_tier_titles?.[String(tier)];
    return title ? `${title} - Tier ${tier}` : `Tier ${tier}`;
  }
  choose(value: number | 'request' | 'skills', select: HTMLSelectElement): void {
    if (this.busy()) return;
    if (value === 'request' || value === 'skills') {
      if (value === 'skills') this.skillsPanel.set(true); else
      this.panel.set(true); this.notice.set('');
      select.selectedIndex = this.tier() === null ? 0 : this.me().chat_tiers.indexOf(this.tier()!);
    } else if (this.me().chat_tiers.includes(value)) this.tierChange.emit(value);
  }
  toggleThinking(): void {
    if (this.busy() || !this.switchAvailable()) return;
    const tier = String(this.tier());
    const value = !this.thinking();
    this.preferences.update(old => ({...old, [tier]: value}));
    try { localStorage.setItem('ooh.thinking.' + tier, String(value)); }
    catch { /* Keep the choice for this page when browser storage is unavailable. */ }
  }
  async sendSkillRequest(): Promise<void> {
    const selected = this.selectedSkill();
    if (this.me().access !== 'approved' || !selected || selected.requested === 'pending' || this.requesting() || this.skillReason.length > 300) return;
    this.requesting.set(true); this.notice.set('');
    try {
      await this.api.requestSkill(selected.name, this.skillReason.trim());
      this.pendingSkills.update(old => [...old, selected.name]); this.skillReason = '';
    } catch (error) { this.notice.set(error instanceof ApiError ? error.message : 'The request failed. Try again.'); }
    finally { this.requesting.set(false); }
  }
  async sendRequest(): Promise<void> {
    const selected = this.selected();
    if (this.me().access !== 'approved' || !selected || selected.requested === 'pending' || this.requesting() || this.reason.length > 300) return;
    this.requesting.set(true); this.notice.set('');
    try {
      await this.api.requestTier(selected.tier, this.reason.trim());
      this.pending.update(old => [...old, selected.tier]);
      this.reason = '';
    } catch (error) {
      this.notice.set(error instanceof ApiError && error.status === 409 && error.code === 'too_soon'
        ? 'You can ask for this model again 7 days after the last answer.'
        : error instanceof ApiError ? error.message : 'The request failed. Try again.');
    } finally { this.requesting.set(false); }
  }
}
