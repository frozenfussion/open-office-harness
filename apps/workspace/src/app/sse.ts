// SPDX-License-Identifier: AGPL-3.0-only
export interface Usage { input_tokens: number; output_tokens: number }
export type ChatEvent =
  | { type: 'delta'; text: string }
  | { type: 'completed'; message_id: string; tier: number; model_title: string; usage: Usage; note: string | null }
  | { type: 'failed'; error: { code: string; message: string } };

export class SseParser {
  private pending = '';
  private data: string[] = [];
  constructor(private readonly receive: (event: ChatEvent) => void) {}
  push(chunk: string, final = false): void {
    this.pending += chunk;
    let end: number;
    while ((end = this.pending.indexOf('\n')) !== -1) {
      const line = this.pending.slice(0, end).replace(/\r$/, '');
      this.pending = this.pending.slice(end + 1);
      this.line(line);
    }
    if (final) {
      if (this.pending) this.line(this.pending.replace(/\r$/, ''));
      this.pending = '';
      this.line('');
    }
  }
  private line(line: string): void {
    if (line === '') {
      if (this.data.length) {
        const value = JSON.parse(this.data.join('\n')) as ChatEvent;
        this.data = [];
        if (value.type !== 'delta' && value.type !== 'completed' && value.type !== 'failed') {
          throw new Error('Unexpected stream event');
        }
        this.receive(value);
      }
    } else if (line.startsWith('data:')) {
      this.data.push(line.slice(5).replace(/^ /, ''));
    }
  }
}

export async function readStream(body: ReadableStream<Uint8Array>, receive: (event: ChatEvent) => void): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser(receive);
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      parser.push(decoder.decode(value, { stream: true }));
    }
    parser.push(decoder.decode(), true);
  } finally {
    reader.releaseLock();
  }
}
