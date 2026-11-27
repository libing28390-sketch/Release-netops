import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AgentManagementTab } from './AgentManagementTab';
import { getRegisteredAgents, getRegisteredTools, runAgent } from '../../../api/ai';

vi.mock('../../../contexts/AppDomainContext', () => ({
  useCoreApp: vi.fn(),
}));

vi.mock('../../../api/ai', () => ({
  getRegisteredAgents: vi.fn(),
  getRegisteredTools: vi.fn(),
  runAgent: vi.fn(),
}));

const showToast = vi.fn();

describe('AgentManagementTab', () => {
  beforeEach(async () => {
    const { useCoreApp } = await import('../../../contexts/AppDomainContext');
    vi.mocked(useCoreApp).mockReturnValue({ language: 'zh', showToast } as never);
    showToast.mockClear();
    vi.mocked(runAgent).mockReset();
  });

  afterEach(() => cleanup());

  it('shows the header and registry summary', async () => {
    vi.mocked(getRegisteredTools).mockResolvedValue([
      { name: 'ip_search', display_name: 'IP 搜索', description: '查询 IPAM', risk_level: 'R0' },
      { name: 'arp_lookup', display_name: 'ARP 查询', description: '查询 ARP 表', risk_level: 'R0' },
    ] as never);
    vi.mocked(getRegisteredAgents).mockResolvedValue([
      { id: 'a1', code: 'troubleshooting_agent', name: '排障 Agent', enabled: true, max_steps: 20, timeout: 900, allowed_tools: [] },
      { id: 'a2', code: 'audit_agent', name: '审计 Agent', enabled: false, max_steps: 5, timeout: 60, allowed_tools: ['ip_search'] },
    ] as never);

    render(<AgentManagementTab />);

    expect(screen.getByRole('heading', { name: /Agent 注册表/ })).toBeTruthy();
    const summary = await screen.findByLabelText('Agent 注册表概况');
    await waitFor(() => expect(summary.textContent).toContain('2个 Agent'));
    expect(summary.textContent).toContain('1已启用');
    expect(summary.textContent).toContain('2R0 只读');
    expect(screen.getByText('IP 搜索')).toBeTruthy();
    expect(screen.getByRole('button', { name: /^排障 Agent/ }).getAttribute('aria-pressed')).toBe('true');
  });

  it('shows empty states when the registry is empty', async () => {
    vi.mocked(getRegisteredTools).mockResolvedValue([] as never);
    vi.mocked(getRegisteredAgents).mockResolvedValue([] as never);

    render(<AgentManagementTab />);

    expect(await screen.findByText('暂无已注册 Agent')).toBeTruthy();
    expect(screen.getByText('暂无已注册工具')).toBeTruthy();
  });

  it('runs the selected agent and renders the trajectory', async () => {
    vi.mocked(getRegisteredTools).mockResolvedValue([] as never);
    vi.mocked(getRegisteredAgents).mockResolvedValue([] as never);
    vi.mocked(runAgent).mockResolvedValue({
      run_id: 'run-1',
      question: '为什么掉包',
      status: 'finished',
      steps: [{ step_no: 1, step_type: 'tool_call', tool_name: 'ip_search', status: 'ok' }],
      final_result: '链路 CRC 错误',
    } as never);

    render(<AgentManagementTab />);
    await screen.findByText('暂无已注册 Agent');
    await userEvent.click(screen.getByRole('button', { name: '运行排障 Agent' }));

    expect(await screen.findByText('链路 CRC 错误')).toBeTruthy();
    expect(screen.getByText('Tool Call: ip_search')).toBeTruthy();
    expect(vi.mocked(runAgent)).toHaveBeenCalledWith('为什么测试设备访问核心交换机掉包？', 'troubleshooting_agent');
  });
});
