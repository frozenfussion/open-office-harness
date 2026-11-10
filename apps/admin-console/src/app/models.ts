// SPDX-License-Identifier: AGPL-3.0-only
export interface ModelEntry {
  model_entry_id: string; title: string; purpose: string; tier?: number;
  role: string; location: string; api_type: string; endpoint_url: string; model_id: string;
  has_key: boolean; priority: number; rate_limit_per_minute: number; daily_budget: number;
  input_price_per_million: number; output_price_per_million: number; timeout_seconds: number;
  request_settings: Record<string, unknown>;
}
export interface Grant { id: string; right_key: string; subject_type: string; subject_id?: string; }
export function tierRows(models: ModelEntry[], grants: Grant[]): number[] {
  return [...new Set([...models.filter(m => m.purpose === 'chat').map(m => m.tier!),
    ...grants.filter(g => /^chat\.tier\.[1-9]\d*$/.test(g.right_key)).map(g => Number(g.right_key.slice(10)))])]
    .filter(n => n !== 99).sort((a, b) => a - b);
}
export function settingsObject(text: string): Record<string, unknown> {
  const value: unknown = JSON.parse(text);
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error('Extra request settings must be a JSON object.');
  return value as Record<string, unknown>;
}
export function modelPayload(model: ModelEntry, key: string, removeKey: boolean, settings: string): Record<string, unknown> {
  const body = { title: model.title, purpose: model.purpose, tier: model.tier, role: model.role,
    location: model.location, api_type: model.api_type, endpoint_url: model.endpoint_url, model_id: model.model_id,
    priority: model.priority, rate_limit_per_minute: model.rate_limit_per_minute, daily_budget: model.daily_budget,
    input_price_per_million: model.input_price_per_million, output_price_per_million: model.output_price_per_million,
    timeout_seconds: model.timeout_seconds };
  const payload: Record<string, unknown> = { ...body, request_settings: settingsObject(settings) };
  if (body.purpose !== 'chat') delete payload['tier'];
  if (removeKey || key.length) payload['api_key'] = removeKey ? '' : key;
  return payload;
}
