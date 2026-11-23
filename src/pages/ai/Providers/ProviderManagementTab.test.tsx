import React from 'react';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ProviderManagementTab, getAllowlistCeilingError, invalidEndpointPatternLines, parseEndpointPatterns } from './ProviderManagementTab';
import { getProviderPageCopy } from './ProviderManagementTab.copy';
import { createAIProvider, deleteAIProvider, getAIProviderDeletePreview, getAIProviderKeyHistory, getAIProvidersPage, invalidateAIProviderKey, testAIProvider, updateAIProvider } from '../../../api/ai';

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
  getAIProviderKeyHistory: vi.fn(),
  invalidateAIProviderKey: vi.fn(),
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
const getKeyHistory = vi.mocked(getAIProviderKeyHistory);
const invalidateKey = vi.mocked(invalidateAIProviderKey);
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
    updateProvider.mockClear();
    invalidateKey.mockReset();
    getKeyHistory.mockReset();
    invalidateKey.mockResolvedValue({ ...provider, api_key_masked: undefined, health_status: 'disabled' } as any);
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
    expect(screen.getByText('健康:')).toBeTruthy();
    expect(screen.getAllByText('健康').length).toBeGreaterThan(0);
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
  }, 20_000);

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

  it('renders the persisted connectivity result after the page is reopened', async () => {
    const testedProvider = {
      ...provider,
      health_status: 'healthy',
      last_error_code: null,
      last_health_check_at: '2026-09-10T00:00:00Z',
      last_success_at: '2026-09-10T00:00:00Z',
    };
    getProviders.mockResolvedValueOnce({
      items: [testedProvider as any],
      total: 1,
      page: 1,
      page_size: 20,
      total_pages: 1,
      facets: { data_regions: ['unknown'], health_statuses: ['healthy'], provider_types: ['deepseek'], tags: [] },
    });

    render(<ProviderManagementTab />);

    expect(await screen.findByText('连接测试通过')).toBeTruthy();
    expect(screen.queryByText('尚未进行连通性测试')).toBeNull();
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

  it('traps focus in the provider editor and restores the opener after Escape', async () => {
    const user = userEvent.setup();
    render(<ProviderManagementTab />);
    await screen.findAllByText('DeepSeek 主供应商');

    const openEditor = screen.getByRole('button', { name: '添加 Provider' });
    await user.click(openEditor);
    const nameInput = screen.getByLabelText('Provider 名称');
    await waitFor(() => expect(document.activeElement).toBe(nameInput));

    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(openEditor));
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

  // ── L6-c: clearing fields and one-request key replacement ──────────────

  const compliantProvider = {
    ...provider,
    proxy_url: 'http://proxy.internal:8080',
    tags: ['prod'],
    allowed_data_classification: 'INTERNAL',
    no_training_confirmed: true,
    retention_days: 30,
    data_processing_agreement_ref: 'DPA-2026-001',
    approved_endpoint_patterns: ['https://api.deepseek.com'],
  };

  const mockSingleProvider = (item: Record<string, unknown>) => {
    getProviders.mockResolvedValue({
      items: [item as any],
      total: 1,
      page: 1,
      page_size: 20,
      total_pages: 1,
      facets: { data_regions: ['unknown'], health_statuses: ['unhealthy'], provider_types: ['deepseek'], tags: ['prod'] },
    });
  };

  it('sends emptied proxy, tags and DPA so the server clears them', async () => {
    mockSingleProvider(compliantProvider);
    const user = userEvent.setup();
    render(<ProviderManagementTab />);
    await screen.findAllByText('DeepSeek 主供应商');
    await user.click(screen.getAllByRole('button', { name: '编辑 DeepSeek 主供应商' })[0]);

    await user.clear(screen.getByLabelText('代理地址 (可选)'));
    await user.clear(screen.getByLabelText('标签 (逗号分隔)'));
    await user.clear(screen.getByLabelText('DPA 协议编号/链接'));
    await user.click(screen.getByLabelText(/Zero-Training/));
    await user.click(screen.getByRole('button', { name: '保存修改' }));

    await waitFor(() => expect(updateProvider).toHaveBeenCalledTimes(1));
    const payload = updateProvider.mock.calls[0][1] as Record<string, unknown>;
    expect(payload.proxy_url).toBe('');
    expect(payload.tags).toEqual([]);
    expect(payload.data_processing_agreement_ref).toBe('');
    expect(payload.no_training_confirmed).toBe(false);
    expect(payload.retention_days).toBe(30);
    expect(payload.api_key).toBeUndefined();
    // The allowlist was not touched, so it is not sent.
    expect(payload).not.toHaveProperty('approved_endpoint_patterns');
  });

  it('replaces the key in the same update request instead of a second rotate call', async () => {
    const user = userEvent.setup();
    render(<ProviderManagementTab />);
    await screen.findAllByText('DeepSeek 主供应商');
    await user.click(screen.getAllByRole('button', { name: '编辑 DeepSeek 主供应商' })[0]);
    await user.type(screen.getByLabelText('API Key'), '  sk-new-key  ');
    await user.click(screen.getByRole('button', { name: '保存修改' }));

    await waitFor(() => expect(updateProvider).toHaveBeenCalledTimes(1));
    expect(updateProvider).toHaveBeenCalledWith(provider.id, expect.objectContaining({ api_key: 'sk-new-key' }));
  });

  // ── L6-d: egress allowlist, key invalidation, key history ──────────────

  it('shows the egress allowlist and sends it only when it was edited', async () => {
    mockSingleProvider(compliantProvider);
    const user = userEvent.setup();
    render(<ProviderManagementTab />);
    await screen.findAllByText('DeepSeek 主供应商');
    expect(within(screen.getByRole('list', { name: '已批准的外发地址' })).getByText('https://api.deepseek.com')).toBeTruthy();

    await user.click(screen.getAllByRole('button', { name: '编辑 DeepSeek 主供应商' })[0]);
    const allowlist = screen.getByLabelText('外发白名单');
    await user.type(allowlist, '{enter}http://insecure.example.com');
    await user.click(screen.getByRole('button', { name: '保存修改' }));
    expect(showToast).toHaveBeenCalledWith('白名单第 2 行不是 HTTPS 地址', 'error');
    expect(updateProvider).not.toHaveBeenCalled();

    await user.clear(allowlist);
    await user.type(allowlist, 'https://api.deepseek.com/*');
    await user.click(screen.getByRole('button', { name: '保存修改' }));
    await waitFor(() => expect(updateProvider).toHaveBeenCalledWith(provider.id, expect.objectContaining({
      approved_endpoint_patterns: ['https://api.deepseek.com/*'],
    })));
  });

  it('explains an allowlist that goes beyond the deployment allowlist', async () => {
    mockSingleProvider(compliantProvider);
    const expected = '外发白名单超出了服务器配置的部署级白名单范围：https://*。这里只能在部署级白名单范围内收窄；如需放行新的地址，请先由服务器管理员在服务器配置 AI_PROVIDER_ENDPOINT_ALLOWLIST 中添加。';
    updateProvider.mockRejectedValueOnce(Object.assign(new Error('raw server text'), {
      status: 400,
      code: 'AI_PROVIDER_ALLOWLIST_EXCEEDS_DEPLOYMENT',
      detail: {
        code: 'AI_PROVIDER_ALLOWLIST_EXCEEDS_DEPLOYMENT',
        message: 'raw server text',
        details: { rejected_patterns: ['https://*'], deployment_allowlist_configured: true },
      },
    }));
    const user = userEvent.setup();
    render(<ProviderManagementTab />);
    await screen.findAllByText('DeepSeek 主供应商');
    await user.click(screen.getAllByRole('button', { name: '编辑 DeepSeek 主供应商' })[0]);

    const allowlist = screen.getByLabelText('外发白名单');
    expect(screen.getByText(/只能在服务器配置的部署级白名单范围内收窄/)).toBeTruthy();
    await user.clear(allowlist);
    await user.type(allowlist, 'https://*');
    await user.click(screen.getByRole('button', { name: '保存修改' }));

    await waitFor(() => expect(showToast).toHaveBeenCalledWith(expected, 'error'));
    expect(screen.getByText(expected)).toBeTruthy();
    expect(allowlist.getAttribute('aria-invalid')).toBe('true');
    expect(showToast).not.toHaveBeenCalledWith('raw server text', 'error');
  });

  it('explains the exact-Base-URL rule when no deployment allowlist is configured', () => {
    const message = getAllowlistCeilingError({
      code: 'AI_PROVIDER_ALLOWLIST_EXCEEDS_DEPLOYMENT',
      detail: { details: { rejected_patterns: ['https://api.example.com/*'], deployment_allowlist_configured: false } },
    }, getProviderPageCopy('zh'));
    expect(message).toContain('服务器未配置部署级白名单');
    expect(message).toContain('https://api.example.com/*');
    expect(getAllowlistCeilingError(new Error('other'), getProviderPageCopy('zh'))).toBeNull();
    expect(getAllowlistCeilingError({ detail: { code: 'AI_PROVIDER_ALLOWLIST_EXCEEDS_DEPLOYMENT' } }, getProviderPageCopy('zh'))).toContain('部署级白名单范围');
  });

  it('invalidates the key only after an explicit acknowledgement', async () => {
    const user = userEvent.setup();
    render(<ProviderManagementTab />);
    await screen.findAllByText('DeepSeek 主供应商');
    await user.click(screen.getByRole('button', { name: '作废 DeepSeek 主供应商 的密钥' }));

    const dialog = screen.getByRole('alertdialog');
    const confirm = within(dialog).getByRole('button', { name: '确认作废' });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    await user.type(within(dialog).getByLabelText('作废原因'), '密钥疑似泄露');
    await user.click(within(dialog).getByLabelText('我了解作废后该 Provider 会立即停止调用'));
    expect((confirm as HTMLButtonElement).disabled).toBe(false);
    await user.click(confirm);

    await waitFor(() => expect(invalidateKey).toHaveBeenCalledWith(provider.id, '密钥疑似泄露'));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(showToast).toHaveBeenCalledWith('已作废“DeepSeek 主供应商”的密钥', 'success');
  });

  it('lists key versions and activity without any key material', async () => {
    getKeyHistory.mockResolvedValue({
      provider_id: provider.id,
      retention_days: 30,
      versions: [
        { key_version: 2, status: 'active', created_by: 'admin', created_at: '2026-11-20T08:00:00Z', ciphertext_retained: true },
        { key_version: 1, status: 'retired', created_by: 'admin', created_at: '2026-10-01T08:00:00Z', retired_at: '2026-11-20T08:00:00Z', ciphertext_retained: false },
      ],
      audit: [{ key_version: 2, action: 'rotate', actor: 'admin', reason_code: 'manual_rotation', created_at: '2026-11-20T08:00:00Z' }],
    });
    const user = userEvent.setup();
    render(<ProviderManagementTab />);
    await screen.findAllByText('DeepSeek 主供应商');
    await user.click(screen.getByRole('button', { name: '查看 DeepSeek 主供应商 的密钥历史' }));

    const drawer = await screen.findByRole('dialog', { name: 'DeepSeek 主供应商 · 密钥历史' });
    expect((await within(drawer).findAllByText('v2')).length).toBe(2);
    expect(within(drawer).getByText('使用中')).toBeTruthy();
    expect(within(drawer).getByText('已替换')).toBeTruthy();
    expect(within(drawer).getByText('手动轮换')).toBeTruthy();
    expect(drawer.textContent).not.toContain('sk-');
    expect(getKeyHistory).toHaveBeenCalledWith(provider.id);

    await user.click(within(drawer).getByRole('button', { name: '关闭' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });
});

describe('egress allowlist parsing', () => {
  it('normalizes, de-duplicates and validates lines', () => {
    expect(parseEndpointPatterns(' https://a.example.com/ \n\nhttps://a.example.com\nhttps://b.example.com/*')).toEqual([
      'https://a.example.com', 'https://b.example.com/*',
    ]);
    expect(invalidEndpointPatternLines('https://ok.example.com\nhttp://bad.example.com\n\nnot a url\nhttps://*.example.com/v1')).toEqual([2, 4]);
  });
});
