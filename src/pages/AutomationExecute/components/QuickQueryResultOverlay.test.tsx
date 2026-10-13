import { describe, expect, it } from 'vitest';
import { formatParserLabel } from './QuickQueryResultOverlay';

describe('formatParserLabel', () => {
  it('shows the concrete versioned TextFSM template when the backend reports it', () => {
    expect(formatParserLabel(
      'textfsm:h3c_comware_v7_display_interface_brief.textfsm',
      true,
    )).toBe('TextFSM 自动匹配 · h3c_comware_v7_display_interface_brief.textfsm');
  });

  it('does not present the legacy NTC catalog wording', () => {
    expect(formatParserLabel('ntc-templates', true)).toBe('TextFSM 解析（模板未回传）');
  });
});
