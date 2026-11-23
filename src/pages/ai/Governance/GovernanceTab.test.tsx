import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { GovernanceTab } from './GovernanceTab';
import { createChangeDraft, generateAIConfig } from '../../../api/ai';
import { apiRequest } from '../../../api/http';

vi.mock('../../../contexts/AppDomainContext', () => ({
  useCoreApp: vi.fn(),
}));

vi.mock('../../../api/ai', () => ({
  generateAIConfig: vi.fn(),
  createChangeDraft: vi.fn(),
}));

vi.mock('../../../api/http', () => ({
  apiRequest: vi.fn(),
}));

const showToast = vi.fn();
const generate = vi.mocked(generateAIConfig);
const createDraft = vi.mocked(createChangeDraft);
const request = vi.mocked(apiRequest);

describe('GovernanceTab', () => {
  beforeEach(async () => {
    const { useCoreApp } = await import('../../../contexts/AppDomainContext');
    vi.mocked(useCoreApp).mockReturnValue({ language: 'zh', showToast } as never);
    showToast.mockClear();
    generate.mockReset();
    createDraft.mockReset();
    request.mockReset();
    request.mockResolvedValue({
      items: [{ id: 'dev-1', hostname: 'core-sw-01', ip_address: '10.0.0.1', vendor: 'Huawei', platform: 'huawei_vrp' }],
    } as never);
  });

  afterEach(() => cleanup());

  it('shows the page header, summary and an empty state before a plan exists', async () => {
    render(<GovernanceTab />);

    expect(screen.getByRole('heading', { name: 'AI 变更治理' })).toBeTruthy();
    expect(screen.getByText('Generate ≠ Execute')).toBeTruthy();
    expect(screen.getByLabelText('变更治理概况')).toBeTruthy();
    expect(screen.getByText('还没有变更方案')).toBeTruthy();
    await waitFor(() => expect(screen.getByRole('option', { name: /core-sw-01/ })).toBeTruthy());
  });

  it('requires risk acknowledgement before a plan with high-risk commands can be submitted', async () => {
    generate.mockResolvedValue({
      summary: '为 VLAN 200 配置 OSPF',
      commands: ['ospf 1', 'undo silent-interface Vlanif200'],
      verification_commands: ['display ospf peer'],
      rollback_commands: ['silent-interface Vlanif200'],
      safety_warnings: [{ reason: '修改路由协议', command: 'ospf 1' }],
      plan_token: 'plan-token-1',
    } as never);
    createDraft.mockResolvedValue({ order_number: 'CHG-001', change_id: 'chg-1' } as never);
    const user = userEvent.setup();

    render(<GovernanceTab />);
    await user.click(screen.getByRole('button', { name: /生成配置命令/ }));

    await waitFor(() => expect(screen.getByTestId('governance-plan')).toBeTruthy());
    expect(screen.queryByText('还没有变更方案')).toBeNull();
    expect(screen.getByTestId('governance-commands').textContent).toContain('undo silent-interface Vlanif200');
    expect(screen.getByRole('alert').textContent).toContain('修改路由协议');

    const submit = screen.getByRole('button', { name: /提交变更工单/ }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    await user.click(screen.getByRole('checkbox'));
    expect(submit.disabled).toBe(false);
    await user.click(submit);

    await waitFor(() => expect(createDraft).toHaveBeenCalledTimes(1));
    expect(createDraft.mock.calls[0][0]).toMatchObject({
      device_id: 'dev-1',
      plan_token: 'plan-token-1',
      risk_acknowledged: true,
    });
    await waitFor(() => expect(screen.getByText(/工单号：CHG-001/)).toBeTruthy());
  });
});
