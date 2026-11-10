// SPDX-License-Identifier: AGPL-3.0-only
import { InjectionToken } from '@angular/core';
export interface Config { issuer: string; clientId: string; apiBase: string }
export const CONFIG = new InjectionToken<Config>('Workspace configuration');
export function readConfig(value: unknown): Config {
  const config = value as Partial<Config> | null;
  if (!config || typeof config.issuer !== 'string' ||
      new URL(config.issuer).protocol !== 'https:' || config.clientId !== 'ooh-workspace' ||
      config.apiBase !== '/api') {
    throw new Error('Invalid Workspace settings');
  }
  return config as Config;
}
