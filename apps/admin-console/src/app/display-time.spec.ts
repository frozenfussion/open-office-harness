// SPDX-License-Identifier: AGPL-3.0-only
import { describe, it, expect } from 'vitest';
import { displayTime, overviewGreeting, validTimeZone } from './display-time';
describe('Display time zone', () => {
  it('formats UTC instants in the configured zone with optional milliseconds', () => {
    expect(displayTime('2026-11-11T13:55:46.4538646+00:00')).toBe('11 Nov 21:55:46');
    expect(displayTime('2026-11-11T13:55:46.4538646+00:00', 'Asia/Kuala_Lumpur', true)).toBe('11 Nov 21:55:46.453');
    expect(displayTime('2026-11-11T13:55:46Z', 'UTC')).toBe('11 Nov 13:55:46');
  });
  it('handles local midnight, missing timestamps and invalid settings', () => {
    expect(displayTime('2026-11-11T16:00:00Z')).toBe('12 Nov 00:00:00');
    expect(displayTime(null)).toBe('—'); expect(displayTime('invalid')).toBe('—');
    expect(validTimeZone('Asia/Kuala_Lumpur')).toBe(true); expect(validTimeZone('invalid-zone')).toBe(false);
  });
  it('greets the known person in the configured zone without hard-coded names', () => {
    const date = new Date('2026-11-11T13:55:46Z');
    expect(overviewGreeting('Synthetic', 'Asia/Kuala_Lumpur', date)).toBe('Good evening, Synthetic.');
    expect(overviewGreeting('Synthetic', 'UTC', date)).toBe('Good afternoon, Synthetic.');
    expect(overviewGreeting('', 'UTC', date)).toBe('Good afternoon.');
  });
});
