import { describe, expect, it } from 'vitest';
import {
  buildExportFilename,
  formatConversationAsJson,
  formatConversationAsMarkdown,
} from './exportUtils';

describe('Copilot exportUtils', () => {
  const sampleDate = new Date(2026, 10, 23, 9, 55, 0);

  it('sanitizes unsafe characters in export filename', () => {
    const name = buildExportFilename('OSPF/BGP:排障*记录?', 'md', sampleDate);
    expect(name).toBe('Nexora_OSPF_BGP_排障_记录__20261123_0955.md');
  });

  it('formats conversation as Markdown with tokens and sources', () => {
    const md = formatConversationAsMarkdown({
      id: 'conv_123',
      title: '武汉天气查询',
      modelName: 'deepseek',
      exportedAt: sampleDate,
      messages: [
        { id: 'u1', role: 'user', content: '查查武汉天气', created_at: '2026-11-23 09:50' },
        {
          id: 'a1',
          role: 'assistant',
          content: '今日武汉多云，12~18℃。',
          created_at: '2026-11-23 09:51',
          input_tokens: 1200,
          output_tokens: 180,
          cached_tokens: 640,
          sources: [{ title: '中国天气网', url: 'https://www.weather.com.cn' }],
        },
      ],
    });

    expect(md).toContain('# 武汉天气查询');
    expect(md).toContain('## 1. 用户');
    expect(md).toContain('## 2. Nexora AI');
    expect(md).toContain('输入 1200 · 输出 180 · 缓存 640');
    expect(md).toContain('[中国天气网](https://www.weather.com.cn)');
  });

  it('formats conversation as structured JSON', () => {
    const raw = formatConversationAsJson({
      id: 'conv_123',
      title: 'OSPF 排查',
      modelName: 'deepseek',
      exportedAt: sampleDate,
      messages: [
        {
          id: 'a1',
          role: 'assistant',
          content: '检查 MTU 与区域号。',
          input_tokens: 500,
          output_tokens: 90,
          cached_tokens: 200,
        },
      ],
    });
    const parsed = JSON.parse(raw);
    expect(parsed.schema_version).toBe('1.0');
    expect(parsed.conversation.id).toBe('conv_123');
    expect(parsed.conversation.message_count).toBe(1);
    expect(parsed.messages[0].tokens).toEqual({ input: 500, output: 90, cached: 200 });
  });
});
