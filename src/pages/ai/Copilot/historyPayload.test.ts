import { describe, expect, it } from 'vitest';
import { buildLocalHistoryPayload } from './historyPayload';

describe('buildLocalHistoryPayload', () => {
  it('keeps real turns and drops error bubbles, empty placeholders and other roles', () => {
    const payload = buildLocalHistoryPayload([
      { role: 'user', content: '10.10.20.15 接在哪台交换机' },
      { role: 'assistant', content: 'SW-CORE-01 GE1/0/12', stream_status: 'completed' },
      { role: 'user', content: '再查一次' },
      { role: 'assistant', content: '模型服务暂时不可用', stream_status: 'error' },
      { role: 'assistant', content: '   ', stream_status: 'streaming' },
      { role: 'system', content: 'internal' },
      { role: 'assistant', content: '已中断的部分回答', stream_status: 'aborted' },
    ]);
    expect(payload).toEqual([
      { role: 'user', content: '10.10.20.15 接在哪台交换机' },
      { role: 'assistant', content: 'SW-CORE-01 GE1/0/12' },
      { role: 'user', content: '再查一次' },
      { role: 'assistant', content: '已中断的部分回答' },
    ]);
  });

  it('returns an empty list for a new session', () => {
    expect(buildLocalHistoryPayload([])).toEqual([]);
  });
});
