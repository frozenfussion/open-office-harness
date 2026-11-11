// SPDX-License-Identifier: AGPL-3.0-only
export interface Usage { input_tokens: number; output_tokens: number }
import type { Job, Routing } from './api';
export interface JobEvent { type: 'job.queued' | 'job.awaiting_approval' | 'job.completed' | 'job.failed'; correlation_id: string; skill: string; output: Job['output']; error: Job['error'] }
export type ChatEvent =
  | ({type: 'job'} & Job)
  | { type: 'thinking'; text: string }
  | { type: 'delta'; text: string }
  | { type: 'completed'; routing?: Routing; message_id: string; tier: number; model_title: string; usage: Usage; note: string | null; thinking_applied: boolean }
  | { type: 'title'; conversation_id: string; title: string }
  | { type: 'failed'; error: { code: string; message: string } };

export class SseParser {
  private pending = '';
  private data: string[] = [];
  constructor(private readonly receive: (event: ChatEvent | JobEvent) => void) {}
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
        const value = JSON.parse(this.data.join('\n')) as ChatEvent | JobEvent;
        this.data = [];
        if (value.type !== 'delta' && value.type !== 'completed' && value.type !== 'failed' && value.type !== 'title' && value.type !== 'thinking' && value.type !== 'job' && !['job.queued', 'job.awaiting_approval', 'job.completed', 'job.failed'].includes(value.type)) {
          return;
        }
        this.receive(value);
      }
    } else if (line.startsWith('data:')) {
      this.data.push(line.slice(5).replace(/^ /, ''));
    }
  }
}

export async function readStream(body: ReadableStream<Uint8Array>, receive: (event: ChatEvent | JobEvent) => void): Promise<void> {
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
