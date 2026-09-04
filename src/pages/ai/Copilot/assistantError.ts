export interface AssistantErrorLike {
  code?: string;
  message?: string;
}

const normalizeCode = (value: unknown): string => String(value || '').trim().toUpperCase();

const hasCode = (code: string, ...values: string[]): boolean => values.some((value) => code === value || code.startsWith(`${value}_`));

/** Keep backend error codes useful for diagnostics while giving operators an actionable UI message. */
export const formatAssistantStreamError = ({ code: rawCode, message: rawMessage }: AssistantErrorLike): string => {
  const code = normalizeCode(rawCode);
  const detail = String(rawMessage || '').trim();

  if (hasCode(code, 'AI_PROVIDER_UNSUPPORTED', 'AI_PROVIDER_ERROR', 'AI_PROVIDER_TIMEOUT', 'AI_PROVIDER_RATE_LIMIT')) {
    return '模型服务暂时不可用，未执行任何设备操作。请检查 AI 中心的 Provider/模型配置后重试。';
  }
  if (hasCode(code, 'AI_SECURITY_BLOCKED', 'AI_SECURITY')) {
    return '请求被安全策略拦截，未执行任何设备操作。请减少敏感内容后重试。';
  }
  if (hasCode(code, 'AI_PERMISSION_DENIED', 'AI_TOOL_PERMISSION_DENIED', 'PERMISSION_DENIED')) {
    return '当前账号没有执行此操作的权限，未执行任何设备操作。';
  }
  if (hasCode(code, 'AI_INTENT_CLARIFICATION_REQUIRED', 'AI_CLARIFICATION_REQUIRED', 'CLARIFICATION_REQUIRED')) {
    return '参数还不完整，请按上方澄清卡片补充设备、接口、协议或时间范围。';
  }
  if (hasCode(code, 'AI_TOOL_CONFIRMATION_REQUIRED', 'TOOL_CONFIRMATION_REQUIRED', 'AI_CONFIRMATION_REQUIRED')) {
    return '该操作可能改变设备状态，需要完成安全确认后才会执行。';
  }
  if (hasCode(code, 'AI_RETRIEVAL_NO_MATCH', 'RETRIEVAL_NO_MATCH', 'KNOWLEDGE_NO_MATCH')) {
    return '知识库没有找到匹配资料，建议补充厂商、型号、版本或目录范围后重试。';
  }
  if (hasCode(code, 'AI_INTERNAL_ERROR', 'AI_REQUEST_REJECTED', 'AI_HTTP_ERROR')) {
    return 'AI 对话服务暂时不可用，未执行任何设备操作，请稍后重试。';
  }

  return `[Copilot 处理失败] ${code || '服务返回错误'}`;
};
