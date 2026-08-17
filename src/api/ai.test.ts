import { describe, expect, it, vi } from 'vitest';

import { chatAssistantStream } from './ai';


describe('versioned assistant SSE contract', () => {
  it('dispatches meta, progress, token, citation, done and error payloads without losing versions', async () => {
    const streamText = [
      'event: meta\n',
      'data: {"event_version":"nxa.sse.v1","intent":"knowledge"}\n\n',
      'event: progress\n',
      'data: {"event_version":"nxa.sse.v1","id":"retrieval","label":"检索","status":"running"}\n\n',
      'event: token\n',
      'data: {"event_version":"nxa.sse.v1","content":"hello"}\n\n',
      'event: citation\n',
      'data: {"event_version":"nxa.sse.v1","index":0,"citation":{"citation_id":"c1"}}\n\n',
      'event: done\n',
      'data: {"event_version":"nxa.sse.v1","status":"completed","duration_ms":4}\n\n',
    ].join('');
    const bytes = new TextEncoder().encode(streamText);
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes);
        controller.close();
      },
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, body }));

    const tokens: string[] = [];
    const metas: string[] = [];
    const progress: string[] = [];
    const citations: string[] = [];
    const done: string[] = [];
    await chatAssistantStream(
      'question',
      undefined,
      (token) => tokens.push(token),
      (meta) => metas.push(meta.event_version || ''),
      (step) => progress.push(step.event_version || ''),
      (payload) => done.push(`${payload.event_version}:${payload.status}`),
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      (citation) => citations.push(`${citation.event_version}:${citation.citation.citation_id}`),
    );

    expect(tokens).toEqual(['hello']);
    expect(metas).toEqual(['nxa.sse.v1']);
    expect(progress).toEqual(['nxa.sse.v1']);
    expect(citations).toEqual(['nxa.sse.v1:c1']);
    expect(done).toEqual(['nxa.sse.v1:completed']);
  });
});

