// SPDX-License-Identifier: AGPL-3.0-only
import { cpSync } from 'node:fs';
cpSync(new URL('../design-system/', import.meta.url), new URL('public/ds/', import.meta.url), { recursive: true });
