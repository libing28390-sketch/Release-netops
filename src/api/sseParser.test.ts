import { describe, expect, it } from 'vitest';
import { SSEParser, readSSEStream, type SSEEvent } from './sseParser';

/* Review item L6-b: the stream parser follows the WHATWG event-stream rules. */

const collect = (chunks: string[], options?: { dispatchIncomplete?: boolean }) => {
  const events: SSEEvent[] = [];
  const parser = new SSEParser((event) => events.push(event));
  chunks.forEach((chunk) => parser.push(chunk));
  parser.flush(options);
  return { events, parser };
};

describe('SSEParser', () => {
  it('resets the event type after a blank line', () => {
    const { events } = collect(['event: meta\ndata: {"a":1}\n\ndata: {"b":2}\n\n']);
    expect(events.map((event) => event.type)).toEqual(['meta', 'message']);
    expect(events[1].data).toBe('{"b":2}');
  });

  it('joins multi-line data with a newline', () => {
    const { events } = collect(['data: first\ndata: second\ndata:third\n\n']);
    expect(events).toHaveLength(1);
    expect(events[0].data).toBe('first\nsecond\nthird');
  });

  it('removes only one leading space after the colon', () => {
    const { events } = collect(['data:  two spaces\n\n']);
    expect(events[0].data).toBe(' two spaces');
  });

  it('ignores comment / heartbeat lines', () => {
    const { events } = collect([': heartbeat\n\n', ':ping\nevent: token\n: still alive\ndata: x\n\n']);
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({ type: 'token', data: 'x' });
  });

  it('handles a CRLF split across two chunks', () => {
    const { events } = collect(['event: token\r', '\ndata: a\r\n\r', '\ndata: b\r\n\r\n']);
    expect(events.map((event) => [event.type, event.data])).toEqual([['token', 'a'], ['message', 'b']]);
  });

  it('accepts bare CR line endings', () => {
    const { events } = collect(['data: a\r\rdata: b\r\r']);
    expect(events.map((event) => event.data)).toEqual(['a', 'b']);
  });

  it('handles a line split across chunks', () => {
    const { events } = collect(['da', 'ta: hel', 'lo\n', '\n']);
    expect(events.map((event) => event.data)).toEqual(['hello']);
  });

  it('skips a UTF-8 BOM only at the very start of the stream', () => {
    const { events } = collect(['\uFEFFdata: a\n\n', '\uFEFFdata: b\n\n']);
    expect(events[0].data).toBe('a');
    // A BOM later in the stream is part of the field name, so that line is an
    // unknown field and is ignored.
    expect(events).toHaveLength(1);
  });

  it('does not dispatch an event without data, but keeps its id', () => {
    const { events, parser } = collect(['event: meta\nid: s1:4\n\n', 'data: x\n\n']);
    expect(events).toHaveLength(1);
    expect(events[0].type).toBe('message');
    expect(events[0].id).toBeNull();
    expect(events[0].lastEventId).toBe('s1:4');
    expect(parser.lastEventId).toBe('s1:4');
  });

  it('tracks ids per event and ignores ids containing NUL', () => {
    const { events } = collect(['id: 1\ndata: a\n\nid: bad\u0000id\ndata: b\n\n']);
    expect(events[0]).toMatchObject({ id: '1', lastEventId: '1' });
    expect(events[1]).toMatchObject({ id: null, lastEventId: '1' });
  });

  it('accepts only ASCII-digit retry values', () => {
    const { events } = collect(['retry: 3000\ndata: a\n\nretry: 3s\ndata: b\n\nretry: -1\ndata: c\n\n']);
    expect(events.map((event) => event.retry)).toEqual([3000, null, null]);
  });

  it('treats a line without a colon as a field with an empty value', () => {
    const { events } = collect(['data\ndata\n\n']);
    expect(events).toHaveLength(1);
    expect(events[0].data).toBe('\n');
  });

  it('flush dispatches an unterminated last event by default', () => {
    const { events } = collect(['event: done\ndata: {"ok":true}']);
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({ type: 'done', data: '{"ok":true}' });
  });

  it('flush can drop an unterminated event in strict mode', () => {
    const { events } = collect(['data: a\n\ndata: partial'], { dispatchIncomplete: false });
    expect(events.map((event) => event.data)).toEqual(['a']);
  });
});

describe('readSSEStream', () => {
  it('decodes UTF-8 split across byte chunks and dispatches every event', async () => {
    const bytes = new TextEncoder().encode('event: token\ndata: {"content":"你好"}\n\nevent: done\ndata: {}\n\n');
    // Split inside the multi-byte character "你".
    const split = bytes.indexOf(0xe4) + 1;
    const chunks = [bytes.slice(0, split), bytes.slice(split)];
    let index = 0;
    const reader = {
      read: async () => (index < chunks.length ? { done: false, value: chunks[index++] } : { done: true, value: undefined }),
    } as unknown as ReadableStreamDefaultReader<Uint8Array>;

    const events: SSEEvent[] = [];
    await readSSEStream(reader, (event) => events.push(event));
    expect(events.map((event) => event.type)).toEqual(['token', 'done']);
    expect(JSON.parse(events[0].data).content).toBe('你好');
  });
});
