/**
 * Incremental Server-Sent Events parser (WHATWG HTML "event stream" format).
 *
 * Replaces the hand-written line loop in chatAssistantStream (review item
 * L6-b), which kept the previous `event:` type across blank lines and parsed
 * each `data:` line on its own.  Behaviour follows the specification:
 *
 * - lines end with LF, CR or CRLF; a CRLF split across two chunks is handled;
 * - a line starting with ":" is a comment (servers use it as a heartbeat);
 * - `field: value` -- one leading space after the colon is removed;
 *   a line without a colon is a field name with an empty value;
 * - `data` lines of one event are joined with "\n";
 * - `event` sets the type of the current event only;
 * - `id` sets the last event id (ignored when it contains U+0000);
 * - `retry` is accepted only when it consists of ASCII digits;
 * - a blank line dispatches the event and resets the event type and data;
 *   an event with no data lines is not dispatched;
 * - a UTF-8 BOM at the very start of the stream is skipped.
 *
 * One deliberate difference: {@link SSEParser.flush} can dispatch an event
 * that was not terminated by a blank line when the stream ends, because a
 * proxy may drop the final separator.  Pass `dispatchIncomplete: false` for
 * strict behaviour.
 */

export interface SSEEvent {
  /** `event` field of this event, or "message" when none was given. */
  type: string;
  /** Data lines joined with "\n". */
  data: string;
  /** `id` field set inside this event block, or null when it had none. */
  id: string | null;
  /** Last event id of the stream after this event (persists across events). */
  lastEventId: string;
  /** `retry` value (milliseconds) set inside this event block, if any. */
  retry: number | null;
}

export type SSEEventHandler = (event: SSEEvent) => void;

export class SSEParser {
  private buffer = '';
  private dataLines: string[] = [];
  private eventType = '';
  private blockId: string | null = null;
  private blockRetry: number | null = null;
  private lastEventIdValue = '';
  private started = false;
  private pendingCR = false;
  private hasFields = false;

  constructor(private readonly onEvent: SSEEventHandler) {}

  /** Last event id seen so far (for reconnection). */
  get lastEventId(): string {
    return this.lastEventIdValue;
  }

  /** Feed decoded text; complete lines are processed immediately. */
  push(chunk: string): void {
    if (!chunk) return;
    let text = chunk;
    if (!this.started) {
      this.started = true;
      if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
    }
    // A CR that ended the previous chunk may be the first half of CRLF.
    if (this.pendingCR) {
      this.pendingCR = false;
      if (text.startsWith('\n')) text = text.slice(1);
    }
    this.buffer += text;

    let start = 0;
    for (let index = 0; index < this.buffer.length; index += 1) {
      const char = this.buffer[index];
      if (char !== '\n' && char !== '\r') continue;
      const line = this.buffer.slice(start, index);
      if (char === '\r') {
        if (index + 1 < this.buffer.length) {
          if (this.buffer[index + 1] === '\n') index += 1;
        } else {
          this.pendingCR = true;
        }
      }
      start = index + 1;
      this.processLine(line);
    }
    this.buffer = this.buffer.slice(start);
  }

  /**
   * End of stream.  Processes an unterminated last line and, unless
   * `dispatchIncomplete` is false, dispatches a pending event.
   */
  flush({ dispatchIncomplete = true }: { dispatchIncomplete?: boolean } = {}): void {
    if (this.buffer) {
      const line = this.buffer;
      this.buffer = '';
      this.processLine(line);
    }
    if (dispatchIncomplete) {
      this.dispatch();
    } else {
      this.resetEvent();
    }
  }

  private processLine(line: string): void {
    if (line === '') {
      this.dispatch();
      return;
    }
    if (line.startsWith(':')) return;
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    this.hasFields = true;
    switch (field) {
      case 'event':
        this.eventType = value;
        break;
      case 'data':
        this.dataLines.push(value);
        break;
      case 'id':
        if (!value.includes('\u0000')) {
          this.lastEventIdValue = value;
          this.blockId = value;
        }
        break;
      case 'retry':
        if (/^\d+$/.test(value)) this.blockRetry = Number(value);
        break;
      default:
        // Unknown fields are ignored by the specification.
        break;
    }
  }

  private dispatch(): void {
    if (!this.hasFields) return;
    if (this.dataLines.length === 0) {
      // "If the data buffer is an empty string ... return": no event, but
      // id/retry already took effect.
      this.resetEvent();
      return;
    }
    const event: SSEEvent = {
      type: this.eventType || 'message',
      data: this.dataLines.join('\n'),
      id: this.blockId,
      lastEventId: this.lastEventIdValue,
      retry: this.blockRetry,
    };
    this.resetEvent();
    this.onEvent(event);
  }

  private resetEvent(): void {
    this.dataLines = [];
    this.eventType = '';
    this.blockId = null;
    this.blockRetry = null;
    this.hasFields = false;
  }
}

/** Read a byte stream to the end, dispatching every SSE event. */
export async function readSSEStream(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  onEvent: SSEEventHandler,
): Promise<void> {
  const decoder = new TextDecoder();
  const parser = new SSEParser(onEvent);
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    parser.push(decoder.decode(value, { stream: true }));
  }
  parser.push(decoder.decode());
  parser.flush();
}
