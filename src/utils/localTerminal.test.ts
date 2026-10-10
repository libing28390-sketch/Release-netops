import { describe, expect, it } from 'vitest';

import { formatTerminalAgentError } from './localTerminal';

describe('formatTerminalAgentError', () => {
  it('directs failed fetch errors to the local Terminal Agent check', () => {
    const message = formatTerminalAgentError(new TypeError('Failed to fetch'), true);

    expect(message).toContain('Terminal Agent');
    expect(message).toContain('127.0.0.1:17890');
  });

  it('distinguishes an origin allowlist failure from an offline Agent', () => {
    const message = formatTerminalAgentError(new Error('backend origin is not allowed by NEXORA_AGENT_ALLOWED_ORIGINS'), true);

    expect(message).toContain('未允许当前 Nexora 页面来源');
    expect(message).toContain('NEXORA_AGENT_ALLOWED_ORIGINS');
  });
});
