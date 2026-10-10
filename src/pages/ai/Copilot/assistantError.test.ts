import { describe, expect, it } from 'vitest';
import { formatAssistantStreamError } from './assistantError';

describe('formatAssistantStreamError', () => {
  it('distinguishes provider failures from security blocks', () => {
    expect(formatAssistantStreamError({ code: 'AI_PROVIDER_UNSUPPORTED' })).toContain('Provider/模型配置');
    expect(formatAssistantStreamError({ code: 'AI_SECURITY_BLOCKED' })).toContain('安全策略拦截');
    expect(formatAssistantStreamError({ code: 'AI_PERMISSION_DENIED' })).toContain('没有执行此操作的权限');
  });

  it('guides the operator for clarification, confirmation, and retrieval misses', () => {
    expect(formatAssistantStreamError({ code: 'AI_CLARIFICATION_REQUIRED' })).toContain('澄清卡片');
    expect(formatAssistantStreamError({ code: 'AI_TOOL_CONFIRMATION_REQUIRED' })).toContain('安全确认');
    expect(formatAssistantStreamError({ code: 'RETRIEVAL_NO_MATCH' })).toContain('补充厂商');
  });

  it('keeps unknown diagnostic codes without echoing raw backend details', () => {
    expect(formatAssistantStreamError({ code: 'SOME_NEW_CODE', message: 'backend detail' })).toBe('[Copilot 处理失败] SOME_NEW_CODE');
  });
});
