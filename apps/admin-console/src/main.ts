// SPDX-License-Identifier: AGPL-3.0-only
import { bootstrapApplication } from '@angular/platform-browser';
import { provideHttpClient } from '@angular/common/http';
import { provideAuth } from 'angular-auth-oidc-client';
import { App } from './app/app';
async function start(): Promise<void> {
  const response = await fetch('/config.json', { cache: 'no-store' });
  if (!response.ok) throw new Error('App settings unavailable');
  window.oohConfig = await response.json();
  const config = window.oohConfig;
  await bootstrapApplication(App, { providers: [provideHttpClient(), provideAuth({ config: {
    authority: config.issuer, clientId: config.clientId, redirectUrl: window.location.origin,
    postLogoutRedirectUri: window.location.origin, responseType: 'code', scope: 'openid profile email',
    silentRenew: true, useRefreshToken: true, renewTimeBeforeTokenExpiresInSeconds: 30
  } })] });
}
void start().catch(() => { document.body.textContent = 'The console could not start. Reload the page to try again.'; });
