import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { UsageDashboardTab } from './UsageDashboardTab';
import { getAIAuditLogs, getAIPlatformMetrics, getAIUsageSummary } from '../../../api/ai';

vi.mock('../../../contexts/AppDomainContext', () => ({
  useCoreApp: vi.fn(),
}));

vi.mock('../../../api/ai', () => ({
  getAIUsageSummary: vi.fn(),
  getAIAuditLogs: vi.fn(),
  getAIPlatformMetrics: vi.fn(),
}));

// The export-capable table is covered by its own tests; render a plain table here.
vi.mock('../../../components/DataTable', () => ({
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  DataTable: ({ unstyled, exportConfig, ...props }: Record<string, unknown>) => <table {...(props as React.TableHTMLAttributes<HTMLTableElement>)} />,
}));

const showToast = vi.fn();

const summary = {
  total_requests: 12,
  total_input_tokens: 3400,
  total_output_tokens: 1200,
  total_tokens: 4600,
  avg_latency_ms: 1500,
  scene_breakdown: { chat: 12 },
  estimated_cost_usd: 0.5,
  daily_estimated_cost_usd: 0.25,
  budget_usd: 10,
  budget_percent: 2.5,
  budget_alert: false,
  provider_breakdown: {
    'prov_deepseek:model_flash': { requests: 9, input_tokens: 3000, output_tokens: 1000, estimated_cost_usd: 0.4, avg_latency_ms: 1400 },
    'prov_deepseek:model_pro': { requests: 3, input_tokens: 400, output_tokens: 200, estimated_cost_usd: 0.1, avg_latency_ms: 1800 },
  },
};

const metrics = {
  requests: { success: 10, blocked: 1, error: 1 },
  tools: { cmdb_lookup: 4 },
  agents: { diagnose: 2 },
};

describe('UsageDashboardTab', () => {
  beforeEach(async () => {
    const { useCoreApp } = await import('../../../contexts/AppDomainContext');
    showToast.mockClear();
    vi.mocked(useCoreApp).mockReturnValue({ language: 'zh', showToast } as never);
    vi.mocked(getAIUsageSummary).mockResolvedValue(summary as never);
    vi.mocked(getAIPlatformMetrics).mockResolvedValue(metrics as never);
    vi.mocked(getAIAuditLogs).mockResolvedValue([
      {
        id: 'log-00000001',
        request_id: 'req_1234567890abcdef',
        user_id: 'nxa_user_abcdef1234567890',
        scene: 'chat',
        provider_id: 'prov_deepseek',
        model_id: 'model_flash',
        input_tokens: 300,
        output_tokens: 120,
        latency_ms: 900,
        status: 'blocked',
        error_code: 'AI_SECURITY_BLOCKED',
        created_at: '2026-11-22T08:00:00Z',
      },
    ] as never);
  });

  afterEach(() => cleanup());

  it('renders the page header, request summary and usage panel', async () => {
    render(<UsageDashboardTab />);

    expect(screen.getByRole('heading', { level: 2, name: /Token 使用统计与 AI 审计/ })).toBeTruthy();
    const overview = await screen.findByLabelText('请求概览');
    expect(overview.textContent).toContain('总请求');
    expect(overview.textContent).toContain('阻断');
    expect(screen.getByText('用量与成本')).toBeTruthy();
    expect(screen.getByText('$0.2500')).toBeTruthy();
    expect(screen.getByRole('progressbar', { name: '日预算使用率' }).getAttribute('aria-valuenow')).toBe('3');
  });

  it('shows the provider breakdown returned as a keyed object, busiest model first', async () => {
    render(<UsageDashboardTab />);

    expect(await screen.findByText('按 Provider / Model 分布')).toBeTruthy();
    const rows = screen.getByLabelText('按 Provider / Model 分布').querySelectorAll('tbody tr');
    expect(rows.length).toBe(2);
    expect(rows[0].textContent).toContain('model_flash');
    expect(rows[1].textContent).toContain('model_pro');
  });

  it('lists audit records with status badges and shows an empty state without records', async () => {
    const { unmount } = render(<UsageDashboardTab />);
    expect(await screen.findByText('已阻断')).toBeTruthy();
    expect(screen.getByText('会话用户')).toBeTruthy();
    expect(screen.getByText('AI_SECURITY_BLOCKED')).toBeTruthy();
    unmount();

    vi.mocked(getAIAuditLogs).mockResolvedValueOnce([] as never);
    render(<UsageDashboardTab />);
    expect(await screen.findByText('当前没有审计记录')).toBeTruthy();
  });
});
