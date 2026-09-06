import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ProviderManagementTab } from './ProviderManagementTab';
import { createAIProvider, deleteAIProvider, getAIProviderDeletePreview, getAIProvidersPage, testAIProvider, updateAIProvider } from '../../../api/ai';

vi.mock('../../../contexts/AppDomainContext', () => ({
  useCoreApp: vi.fn(),
}));

vi.mock('../../../api/ai', () => ({
  getAIProvidersPage: vi.fn(),
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
  data_region: 'unknown',
  allowed_data_classification: 'PUBLIC',
  health_status: 'unhealthy',
  last_error_code: 'AI_SECURITY_BLOCKED',
  created_at: '2026-08-17T00:00:00Z',
  updated_at: '2026-08-17T00:00:00Z',
};

const getProviders = vi.mocked(getAIProvidersPage);
const createProvider = vi.mocked(createAIProvider);
const updateProvider = vi.mocked(updateAIProvider);
const deleteProvider = vi.mocked(deleteAIProvider);
const getDeletePreview = vi.mocked(getAIProviderDeletePreview);
const testProvider = vi.mocked(testAIProvider);
const showToast = vi.fn();

describe('ProviderManagementTab browser key paths', () => {
  beforeEach(async () => {
    const { useCoreApp } = await import('../../../contexts/AppDomainContext');
    showToast.mockClear();
    deleteProvider.mockClear();
    getDeletePreview.mockReset();
    getDeletePreview.mockResolvedValue({ model_count: 0, route_count: 0, can_delete: true } as any);
    vi.mocked(useCoreApp).mockReturnValue({ language: 'zh', showToast } as never);
    getProviders.mockResolvedValue({
      items: [provider as any],
      total: 1,
      page: 1,
      page_size: 20,
      total_pages: 1,
      facets: { data_regions: ['unknown'], health_statuses: ['unhealthy'], provider_types: ['deepseek'], tags: [] },
    });
    createProvider.mockResolvedValue(provider as any);
    updateProvider.mockResolvedValue(provider as any);
    testProvider.mockResolvedValue({ success: true, message: 'ok', model_tested: 'deepseek-chat', sample_response: 'ok', latency_ms: 12 } as any);
  });

  afterEach(() => cleanup());

  it('loads a masked provider, tests through the gateway, and opens the add flow', async () => {
    const user = userEvent.setup();
    render(<ProviderManagementTab />);

    expect((await screen.findAllByText('DeepSeek 主供应商')).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('sk-****181f')).toBeTruthy();
    expect(screen.queryByText('sk-live-secret')).toBeNull();
    const manualLink = screen.getByRole('link', { name: '下载 AI 使用手册' });
    expect(manualLink.getAttribute('href')).toBe('/downloads/nexora-ai-provider-debug-manual.md');
    expect(manualLink.getAttribute('download')).toBe('Nexora-AI-使用手册.md');

    await user.click(screen.getByRole('button', { name: '测试连通性' }));
    expect(await screen.findByText('连接测试通过')).toBeTruthy();
    expect(screen.getByText('健康: healthy')).toBeTruthy();
    expect(screen.queryByText('AI_SECURITY_BLOCKED')).toBeNull();
    expect(testProvider).toHaveBeenCalledWith(provider.id);

    await user.click(screen.getByRole('button', { name: '添加 Provider' }));
    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(screen.queryByText('云端供应商证明（内部数据必填）')).toBeNull();
    expect(screen.queryByText('供应商无训练条款已核验')).toBeNull();
    expect(screen.queryByText('协议 / DPA 编号')).toBeNull();
    expect(screen.queryByText(/批准端点模式/)).toBeNull();
    await user.type(screen.getByLabelText('Provider 名称'), '备用 OpenAI');
    await user.type(screen.getByLabelText('API Key'), 'sk-test-only');
    expect(screen.getByLabelText('API Key').getAttribute('type')).toBe('password');
    await user.click(screen.getByRole('button', { name: '显示 API Key' }));
    expect(screen.getByLabelText('API Key').getAttribute('type')).toBe('text');
    await user.click(screen.getByRole('button', { name: '隐藏 API Key' }));
    expect(screen.getByLabelText('API Key').getAttribute('type')).toBe('password');
    await user.selectOptions(screen.getByLabelText('数据区域'), 'global');
    await user.selectOptions(screen.getByLabelText('允许数据分类'), 'INTERNAL');
    await user.click(screen.getByRole('button', { name: '确认添加' }));
    await waitFor(() => expect(createProvider).toHaveBeenCalledWith(expect.objectContaining({ name: '备用 OpenAI', api_key: 'sk-test-only', data_region: 'global', allowed_data_classification: 'INTERNAL' })));
    expect(createProvider.mock.calls[0][0]).not.toHaveProperty('no_training_confirmed');
    expect(createProvider.mock.calls[0][0]).not.toHaveProperty('retention_days');
    expect(createProvider.mock.calls[0][0]).not.toHaveProperty('data_processing_agreement_ref');
    expect(createProvider.mock.calls[0][0]).not.toHaveProperty('approved_endpoint_patterns');
  }, 10_000);

  it('keeps the existing API key when editing a provider without re-entering it', async () => {
    const user = userEvent.setup();
    render(<ProviderManagementTab />);

    await screen.findAllByText('DeepSeek 主供应商');
    await user.click(screen.getAllByRole('button', { name: '编辑 DeepSeek 主供应商' })[0]);

    const apiKeyInput = screen.getByLabelText('API Key');
    expect(apiKeyInput.hasAttribute('required')).toBe(false);
    expect(apiKeyInput.getAttribute('placeholder')).toBe('留空以保留现有密钥');

    await user.selectOptions(screen.getByLabelText('允许数据分类'), 'INTERNAL');
    await user.click(screen.getByRole('button', { name: '保存修改' }));
    await waitFor(() => expect(updateProvider).toHaveBeenCalledWith(provider.id, expect.objectContaining({
      allowed_data_classification: 'INTERNAL',
      api_key: undefined,
    })));
  });

  it('shows the empty state and a recoverable request error', async () => {
    getProviders.mockResolvedValueOnce({ items: [], total: 0, page: 1, page_size: 20, total_pages: 1, facets: {} });
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

    await screen.findAllByText('DeepSeek 主供应商');
    await user.click(screen.getByRole('button', { name: '测试连通性' }));
    expect(await screen.findByText(/允许的数据分类级别不足/)).toBeTruthy();
  });

  it('explains an invalid API key instead of showing a generic gateway failure', async () => {
    testProvider.mockResolvedValueOnce({
      success: false,
      message: 'provider connection test blocked or failed',
      error_code: 'AI_AUTH_FAILED',
      latency_ms: 120,
    } as any);
    const user = userEvent.setup();
    render(<ProviderManagementTab />);

    await screen.findAllByText('DeepSeek 主供应商');
    await user.click(screen.getByRole('button', { name: '测试连通性' }));
    expect(await screen.findByText(/Provider 已拒绝 API Key/)).toBeTruthy();
    expect(screen.getByText('错误标识：AI_AUTH_FAILED')).toBeTruthy();
  });

  it('explains the health backoff after a recent failed probe', async () => {
    testProvider.mockResolvedValueOnce({
      success: false,
      message: 'health probe backoff is active',
      error_code: 'AI_HEALTH_BACKOFF',
      latency_ms: 0,
    } as any);
    const user = userEvent.setup();
    render(<ProviderManagementTab />);

    await screen.findAllByText('DeepSeek 主供应商');
    await user.click(screen.getByRole('button', { name: '测试连通性' }));
    expect(await screen.findByText(/短暂冷却/)).toBeTruthy();
  });

  it('explains an unsupported provider or endpoint instead of showing a generic failure', async () => {
    testProvider.mockResolvedValueOnce({
      success: false,
      message: 'provider endpoint is not approved',
      error_code: 'AI_PROVIDER_UNSUPPORTED',
      latency_ms: 21,
    } as any);
    const user = userEvent.setup();
    render(<ProviderManagementTab />);

    await screen.findAllByText('DeepSeek 主供应商');
    await user.click(screen.getByRole('button', { name: '测试连通性' }));
    expect(await screen.findByText(/安全网关未批准该 Provider 类型或端点/)).toBeTruthy();
    expect(screen.getByText('错误标识：AI_PROVIDER_UNSUPPORTED')).toBeTruthy();
  });

  it('explains Provider dependencies before sending an impossible delete request', async () => {
    getDeletePreview.mockResolvedValueOnce({ model_count: 1, route_count: 2, can_delete: false } as any);
    const user = userEvent.setup();
    render(<ProviderManagementTab />);

    await screen.findAllByText('DeepSeek 主供应商');
    await user.click(screen.getAllByRole('button', { name: '删除 DeepSeek 主供应商' })[0]);

    await waitFor(() => expect(showToast).toHaveBeenCalledWith(
      '暂时不能删除“DeepSeek 主供应商”：仍关联 1 个模型、2 条业务路由。请先在模型管理中处理这些关联；如果只是暂时不用，可以直接停用 Provider。',
      'error',
    ));
    expect(deleteProvider).not.toHaveBeenCalled();
  });
});
