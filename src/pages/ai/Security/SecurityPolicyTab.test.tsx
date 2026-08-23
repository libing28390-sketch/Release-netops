import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SecurityPolicyTab from './SecurityPolicyTab';
import {
  getAISecurityEventsPage,
  getAISecurityIncidentsPage,
  getAISecurityPolicy,
  setAIDevPassthrough,
  testAISecurityPayload,
  updateAISecurityPolicy,
} from '../../../api/ai';

vi.mock('../../../api/ai', () => ({
  getAISecurityEventsPage: vi.fn(),
  getAISecurityIncidentsPage: vi.fn(),
  getAISecurityPolicy: vi.fn(),
  resolveAISecurityIncident: vi.fn(),
  exportAISecurityEvents: vi.fn(),
  setAIKillSwitch: vi.fn(),
  setAIDevPassthrough: vi.fn(),
  setAITenantKillSwitch: vi.fn(),
  testAISecurityPayload: vi.fn(),
  updateAISecurityPolicy: vi.fn(),
}));

const policy = {
  external_ai_enabled: false,
  kill_switch: false,
  max_payload_bytes: 256000,
  identifiers_must_be_tokenized: true,
  allow_sensitive_minimization: true,
  allowed_provider_types: ['deepseek', 'openai_compatible'],
  allowed_classifications: ['PUBLIC', 'INTERNAL'],
  allowed_data_regions: ['unknown', 'global'],
  tenant_kill_switches: {},
  dev_passthrough: {
    supported: false,
    configured: false,
    enabled: false,
    expires_at: null,
    remaining_seconds: 0,
    max_minutes: 15,
    environment: 'production',
  },
};

const getPolicy = vi.mocked(getAISecurityPolicy);
const getEvents = vi.mocked(getAISecurityEventsPage);
const getIncidents = vi.mocked(getAISecurityIncidentsPage);
const updatePolicy = vi.mocked(updateAISecurityPolicy);
const setDevPassthrough = vi.mocked(setAIDevPassthrough);
const testPayload = vi.mocked(testAISecurityPayload);

describe('SecurityPolicyTab browser key paths', () => {
  beforeEach(() => {
    getPolicy.mockResolvedValue(policy as any);
    getEvents.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20, total_pages: 1 });
    getIncidents.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20, total_pages: 1 });
    updatePolicy.mockResolvedValue({ ...policy, external_ai_enabled: true } as any);
    testPayload.mockResolvedValue({ decision: 'MINIMIZE', max_data_level: 'INTERNAL', finding_categories: ['identifier'], payload_bytes: 42, reason: 'tokenized', external_call_made: false } as any);
    vi.stubGlobal('confirm', vi.fn(() => true));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('loads fail-closed posture, enables the outlet, and runs a no-external-call dry run', async () => {
    const user = userEvent.setup();
    render(<SecurityPolicyTab />);
    expect(await screen.findByText('默认拒绝外部 AI')).toBeTruthy();
    expect(screen.getByRole('switch', { name: '切换外部 AI 出口' }).getAttribute('aria-checked')).toBe('false');

    await user.click(screen.getByRole('switch', { name: '切换外部 AI 出口' }));
    await waitFor(() => expect(updatePolicy).toHaveBeenCalledWith(expect.objectContaining({ external_ai_enabled: true })));
    expect(updatePolicy.mock.calls[0]?.[0]).not.toHaveProperty('dev_passthrough');
    expect(await screen.findByText('安全网关已就绪')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: '运行策略检查' }));
    expect((await screen.findByRole('status', { name: '策略检查结果' })).textContent).toContain('MINIMIZE / INTERNAL');
    expect(testPayload).toHaveBeenCalledWith([{ role: 'user', content: expect.stringContaining('show interface') }]);
  });

  it('renders a safe error state when the policy endpoint is unavailable', async () => {
    getPolicy.mockRejectedValueOnce(new Error('安全策略服务不可用'));
    render(<SecurityPolicyTab />);
    expect((await screen.findByRole('alert')).textContent).toContain('安全策略服务不可用');
  });

  it('enables the administrator-controlled temporary AI test mode for a bounded window', async () => {
    const user = userEvent.setup();
    getPolicy.mockResolvedValueOnce({
      ...policy,
      external_ai_enabled: true,
      dev_passthrough: {
        supported: true,
        configured: true,
        enabled: false,
        expires_at: null,
        remaining_seconds: 0,
        max_minutes: 15,
        environment: 'production',
      },
    } as any);
    setDevPassthrough.mockResolvedValueOnce({
      supported: true,
      configured: true,
      enabled: true,
      expires_at: '2026-08-21T16:15:00+00:00',
      remaining_seconds: 900,
      max_minutes: 15,
      environment: 'production',
    });

    render(<SecurityPolicyTab />);
    const switchButton = await screen.findByRole('switch', { name: '切换 AI 临时测试模式' });
    await user.click(switchButton);

    await waitFor(() => expect(setDevPassthrough).toHaveBeenCalledWith(true, 15));
    expect(await screen.findByText('AI 临时测试模式已开启')).toBeTruthy();
  });
});
