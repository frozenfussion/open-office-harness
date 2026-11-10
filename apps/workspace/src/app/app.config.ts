// SPDX-License-Identifier: AGPL-3.0-only
import { ApplicationConfig } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { provideRouter } from '@angular/router';
import { provideAuth, LogLevel } from 'angular-auth-oidc-client';
import { CONFIG, Config } from './config';

export function appConfig(config: Config): ApplicationConfig {
  return { providers: [
    provideHttpClient(),
    provideRouter([]),
    { provide: CONFIG, useValue: config },
    provideAuth({ config: {
      authority: config.issuer,
      clientId: config.clientId,
      redirectUrl: window.location.origin + '/',
      postLogoutRedirectUri: window.location.origin + '/',
      responseType: 'code',
      scope: 'openid profile offline_access',
      silentRenew: true,
      useRefreshToken: true,
      logLevel: LogLevel.None,
    } }),
  ] };
}
