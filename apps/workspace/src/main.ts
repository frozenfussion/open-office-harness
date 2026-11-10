// SPDX-License-Identifier: AGPL-3.0-only
import { bootstrapApplication } from '@angular/platform-browser';
import { App } from './app/app';
import { readConfig } from './app/config';
import { appConfig } from './app/app.config';

async function start(): Promise<void> {
  const config = readConfig(await (await fetch('/config.json', { cache: 'no-store' })).json());
  await bootstrapApplication(App, appConfig(config));
}
void start().catch(() => {
  document.body.textContent = 'Workspace could not start. Reload the page or ask an admin to check its settings.';
});
