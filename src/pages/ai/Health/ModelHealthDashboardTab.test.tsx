import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { ModelHealthDashboardTab } from './ModelHealthDashboardTab';
import { checkAIModelHealth, getAIModelHealthSummary } from '../../../api/ai';

vi.mock('../../../contexts/AppDomainContext', () => ({
  useCoreApp: vi.fn(),
}));

vi.mock('../../../api/ai', () => ({
  checkAIModelHealth: vi.fn(),
  getAIModelHealthSummary: vi.fn(),
}));

const getSummary = vi.mocked(getAIModelHealthSummary);
const checkModel = vi.mocked(checkAIModelHealth);
const showToast = vi.fn();

const timeline = (status: string, availability: number | null) => Array.from({ length: 90 }, (_, index) => ({
  bucket_date: `2026-06-${String(index + 1).padStart(2, '0')}`,
  status,
  check_count: availability == null ? 0 : 1,
  success_count: availability === 100 ? 1 : 0,
  failure_count: availability === 100 ? 0 : availability == null ? 0 : 1,
  availability_percent: availability,
  avg_latency_ms: availability == null ? null : 240,
}));

describe('ModelHealthDashboardTab', () => {
  beforeEach(async () => {
    const { useCoreApp } = await import('../../../contexts/AppDomainContext');
    showToast.mockClear();
    checkModel.mockReset();
    vi.mocked(useCoreApp).mockReturnValue({ language: 'zh', showToast } as never);
    getSummary.mockResolvedValue({
      window_days: 90,
      window_start: '2026-06-13T00:00:00Z',
      generated_at: '2026-09-10T08:00:00Z',
      overall_status: 'unhealthy',
      service_count: 2,
      monitored_service_count: 2,
      checked_service_count: 2,
      total_check_count: 10,
      total_success_count: 9,
      total_failure_count: 1,
      availability_percent: 90,
      avg_latency_ms: 320,
      services: [
        {
          model_id: 'model-healthy',
          provider_id: 'provider-1',
          provider_name: 'DeepSeek',
          model_name: 'DeepSeek Chat',
          model_code: 'deepseek-chat',
          model_type: 'chat',
          enabled: true,
          health_status: 'healthy',
          last_health_check_at: '2026-09-10T08:00:00Z',
          window_check_count: 5,
          window_success_count: 5,
          window_failure_count: 0,
          window_availability_percent: 100,
          window_avg_latency_ms: 240,
          timeline: timeline('healthy', 100),
        },
        {
          model_id: 'model-unhealthy',
          provider_id: 'provider-1',
          provider_name: 'DeepSeek',
          model_name: 'DeepSeek Reasoner',
          model_code: 'deepseek-reasoner',
          model_type: 'reasoning',
          enabled: true,
          health_status: 'unhealthy',
          last_health_check_at: '2026-09-10T07:50:00Z',
          window_check_count: 5,
          window_success_count: 4,
          window_failure_count: 1,
          window_availability_percent: 80,
          window_avg_latency_ms: 400,
          timeline: timeline('unhealthy', 80),
        },
      ],
    });
  });

  afterEach(() => cleanup());

  it('renders an OpenAI-style status banner and historical service bars', async () => {
    render(<MemoryRouter><ModelHealthDashboardTab /></MemoryRouter>);

    expect(await screen.findByText('当前状态：Nexora AI 模型服务')).toBeTruthy();
    expect(screen.getByText('部分模型需要关注')).toBeTruthy();
    expect(screen.getByText('系统状态')).toBeTruthy();
    expect(screen.getByText('DeepSeek Chat')).toBeTruthy();
    expect(screen.getByText('DeepSeek Reasoner')).toBeTruthy();
    expect(screen.getAllByRole('button', { name: '立即检查' }).length).toBe(2);
    expect(screen.getAllByText('90 天前').length).toBeGreaterThan(0);
  });

  it('reloads the status history when the time window changes', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><ModelHealthDashboardTab /></MemoryRouter>);
    await screen.findByText('系统状态');

    await user.click(screen.getByRole('button', { name: '30天' }));
    await waitFor(() => expect(getSummary).toHaveBeenLastCalledWith(30));
  });
});
