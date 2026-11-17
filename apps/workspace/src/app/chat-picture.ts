// SPDX-License-Identifier: AGPL-3.0-only
import { Component, effect, inject, input, signal } from '@angular/core';
import { Api, Picture } from './api';

@Component({selector: 'app-chat-picture', template: `
  <figure>
    @if (url()) { <img [src]="url()" [alt]="picture().file_name" /> }
    @else { <span role="status">{{ failed() ? 'Picture could not be loaded.' : 'Loading picture…' }}</span> }
    <figcaption>{{ picture().file_name }}</figcaption>
  </figure>`, styles: `
  figure { margin: 0 0 var(--space-3); }
  img { display: block; max-width: 100%; max-height: 280px; border-radius: var(--radius-md); }
  figcaption { color: var(--ink-muted); font-size: 13px; overflow-wrap: anywhere; }
`})
export class ChatPicture {
  readonly picture = input.required<Picture>();
  readonly localUrl = input<string>();
  readonly url = signal('');
  readonly failed = signal(false);
  private readonly api = inject(Api);
  constructor() {
    effect(onCleanup => {
      const picture = this.picture(); const local = this.localUrl();
      let active = true; let owned: string | undefined;
      this.url.set(local ?? ''); this.failed.set(false);
      onCleanup(() => { active = false; if (owned) URL.revokeObjectURL(owned); });
      if (!local) void this.api.picture(picture.upload_id).then(blob => {
        if (active) { owned = URL.createObjectURL(blob); this.url.set(owned); }
      }).catch(() => { if (active) this.failed.set(true); });
    });
  }
}
