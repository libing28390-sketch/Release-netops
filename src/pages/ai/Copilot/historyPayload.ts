/**
 * History sent with a request from a local (not yet saved) Copilot session.
 *
 * Saved conversations (`conv_*`) load their history on the server, so this is
 * only used when there is no conversation id.  Only real user/assistant turns
 * are sent: error bubbles, empty streaming placeholders and other UI-only
 * entries would otherwise take up the server's history budget and push the
 * turns a follow-up refers to out of the window.
 */
export interface LocalHistoryMessage {
  role: string;
  content: string;
  stream_status?: string;
}

export interface HistoryPayloadItem {
  role: 'user' | 'assistant';
  content: string;
}

export function buildLocalHistoryPayload(messages: readonly LocalHistoryMessage[]): HistoryPayloadItem[] {
  const payload: HistoryPayloadItem[] = [];
  for (const message of messages) {
    if (message.role !== 'user' && message.role !== 'assistant') continue;
    if (message.stream_status === 'error') continue;
    const content = String(message.content ?? '');
    if (!content.trim()) continue;
    payload.push({ role: message.role, content });
  }
  return payload;
}
