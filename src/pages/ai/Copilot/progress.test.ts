import { describe, expect, it } from 'vitest';
import { formatCopilotDuration, upsertCopilotProcessStep } from './progress';

describe('Copilot progress helpers', () => {
  it('formats elapsed time in the compact Chinese format used by the chat', () => {
    expect(formatCopilotDuration(0)).toBe('已处理 0秒');
    expect(formatCopilotDuration(6 * 60 * 1000 + 52 * 1000)).toBe('已处理 6分钟 52秒');
    expect(formatCopilotDuration((60 * 60 + 2 * 60 + 3) * 1000)).toBe('已处理 1小时 2分钟 3秒');
  });

  it('updates a running step without reordering the process list', () => {
    const running = {
      id: 'knowledge',
      label: '检索知识库',
      status: 'running' as const,
    };
    const completed = { ...running, status: 'completed' as const, detail: '命中 2 个知识片段' };

    expect(upsertCopilotProcessStep([], running)).toEqual([running]);
    expect(upsertCopilotProcessStep([running], completed)).toEqual([completed]);
  });
});
