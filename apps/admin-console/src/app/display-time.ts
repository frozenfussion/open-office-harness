// SPDX-License-Identifier: AGPL-3.0-only
export const defaultTimeZone = 'Asia/Kuala_Lumpur';
export function validTimeZone(zone: string): boolean {
  try { new Intl.DateTimeFormat('en-GB', { timeZone: zone }); return true; } catch { return false; }
}
export function displayTime(value: string | null | undefined, timeZone = defaultTimeZone, milliseconds = false): string {
  if (!value) return '—';
  const date = new Date(value); if (Number.isNaN(date.getTime())) return '—';
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone, day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
    ...(milliseconds ? { fractionalSecondDigits: 3 as const } : {})
  }).formatToParts(date);
  const part = (name: Intl.DateTimeFormatPartTypes): string => parts.find(p => p.type === name)?.value ?? '';
  return `${part('day')} ${part('month')} ${part('hour')}:${part('minute')}:${part('second')}` + (milliseconds ? '.' + part('fractionalSecond') : '');
}
export function overviewGreeting(name: string, timeZone = defaultTimeZone, date = new Date()): string {
  const hour = Number(new Intl.DateTimeFormat('en-GB', { timeZone, hour: '2-digit', hourCycle: 'h23' }).format(date));
  const phrase = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
  return phrase + (name.trim() ? ', ' + name.trim() : '') + '.';
}
