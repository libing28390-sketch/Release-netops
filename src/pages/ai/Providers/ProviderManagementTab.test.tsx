import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ProviderManagementTab } from './ProviderManagementTab';
import { createAIProvider, getAIProviders, testAIProvider } from '../../../api/ai';

vi.mock('../../../contexts/AppDomainContext', () => ({
  useCoreApp: vi.fn(),
}));

vi.mock('../../../api/ai', () => ({
  getAIProviders: vi.fn(),
  createAIProvider: vi.fn(),
  updateAIProvider: vi.fn(),
  deleteAIProvider: vi.fn(),
  getAIProviderDeletePreview: vi.fn(),
  testAIProvider: vi.fn(),
}));

const provider = {
  id: 'prov_deepseek_001',
  name: 'DeepSeek 主供应商',
  provider_type: 'deepseek',
  base_url: 'https://api.deepseek.com',
  api_key_masked: 'sk-****181f',
  timeout: 30,
  max_retries: 2,
  enabled: true,
  allowed_data_classification: 'PUBLIC',
  health_status: 'healthy',
  created_at: '2026-08-17T00:00:00Z',
  updated_at: '2026-08-17T00:00:00Z',
};

const getProviders = vi.mocked(getAIProviders);
const createProvider = vi.mocked(createAIProvider);
const testProvider = vi.mocked(testAIProvider);

describe('ProviderManagementTab browser key paths', () => {
  beforeEach(async () => {
    const { useCoreApp } = await import('../../../contexts/AppDomainContext');
    vi.mocked(useCoreApp).mockReturnValue({ language: 'zh', showToast: vi.fn() } as never);
    getProviders.mockResolvedValue([provider as any]);
    createProvider.mockResolvedValue(provider as any);
    testProvider.mockResolvedValue({ success: true, message: 'ok', model_tested: 'deepseek-chat', sample_response: 'ok', latency_ms: 12 } as any);
  });

  afterEach(() => cleanup());

  it('loads a masked provider, tests through the gateway, and opens the add flow', async () => {
    const user = userEvent.setup();
    render(<ProviderManagementTab />);

    expect(await screen.findByText('DeepSeek 主供应商')).toBeTruthy();
    expect(screen.getByText('sk-****181f')).toBeTruthy();
    expect(screen.queryByText('sk-live-secret')).toBeNull();

    await user.click(screen.getByRole('button', { name: '测试连通性' }));
    expect(await screen.findByText('连接测试通过')).toBeTruthy();
    expect(testProvider).toHaveBeenCalledWith(provider.id);

    await user.click(screen.getByRole('button', { name: '添加 Provider' }));
    expect(screen.getByRole('dialog')).toBeTruthy();
    await user.type(screen.getByLabelText('Provider 名称'), '备用 OpenAI');
    await user.type(screen.getByLabelText('API Key'), 'sk-test-only');
    await user.selectOptions(screen.getByLabelText('允许数据分类'), 'INTERNAL');
    await user.click(screen.getByRole('button', { name: '确认添加' }));
    await waitFor(() => expect(createProvider).toHaveBeenCalledWith(expect.objectContaining({ name: '备用 OpenAI', api_key: 'sk-test-only', allowed_data_classification: 'INTERNAL' })));
  });

  it('shows the empty state and a recoverable request error', async () => {
    getProviders.mockResolvedValueOnce([]);
    const user = userEvent.setup();
    render(<ProviderManagementTab />);
    expect(await screen.findByText('还没有 Provider')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '添加第一个 Provider' }));
    expect(screen.getByRole('dialog')).toBeTruthy();

    cleanup();
    getProviders.mockRejectedValueOnce(new Error('Provider 服务暂不可用'));
    render(<ProviderManagementTab />);
    expect(await screen.findByText('Provider 服务暂不可用')).toBeTruthy();
    expect(screen.getByRole('button', { name: '重试' })).toBeTruthy();
  });

  it('explains a Provider classification boundary error', async () => {
    testProvider.mockResolvedValueOnce({
      success: false,
      message: 'provider connection test blocked or failed',
      error_code: 'AI_SECURITY_CLASSIFICATION_DENIED',
      latency_ms: 8,
    } as any);
    const user = userEvent.setup();
    render(<ProviderManagementTab />);

    await screen.findByText('DeepSeek 主供应商');
    await user.click(screen.getByRole('button', { name: '测试连通性' }));
    expect(await screen.findByText(/允许的数据分类级别不足/)).toBeTruthy();
  });
});
