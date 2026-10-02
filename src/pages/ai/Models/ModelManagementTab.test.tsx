import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ModelManagementTab } from './ModelManagementTab';
import {
  createAIModel,
  checkAIModelHealth,
  deleteAIModel,
  getAIModelDeletePreview,
  getAIModelRoutes,
  getAIModels,
  getAIProviders,
  setAIUserDefaultModel,
  updateAIModel,
  upsertAIModelRoute,
} from '../../../api/ai';

vi.mock('../../../contexts/AppDomainContext', () => ({
  useCoreApp: vi.fn(),
}));

vi.mock('../../../api/ai', () => ({
  checkAIModelHealth: vi.fn(),
  createAIModel: vi.fn(),
  deleteAIModel: vi.fn(),
  getAIModelDeletePreview: vi.fn(),
  getAIModelRoutes: vi.fn(),
  getAIModels: vi.fn(),
  getAIProviders: vi.fn(),
  setAIUserDefaultModel: vi.fn(),
  updateAIModel: vi.fn(),
  upsertAIModelRoute: vi.fn(),
}));

const provider = { id: 'prov-1', name: 'DeepSeek 主供应商', provider_type: 'deepseek' };
const model = {
  id: 'model-1',
  provider_id: provider.id,
  name: 'DeepSeek V4 Flash',
  model_code: 'deepseek-v4-flash',
  model_type: 'chat',
  thinking_supported: true,
  tool_call_supported: true,
  json_supported: true,
  context_length: 128000,
  max_output_tokens: 8192,
  default_temperature: 0.2,
  default_max_tokens: 4096,
  enabled: true,
  is_default: true,
  priority: 1,
  created_at: '2026-08-17T00:00:00Z',
  updated_at: '2026-08-17T00:00:00Z',
  stream_supported: true,
  health_status: 'healthy',
  last_latency_ms: 42,
};

const getModels = vi.mocked(getAIModels);
const getRoutes = vi.mocked(getAIModelRoutes);
const getProviders = vi.mocked(getAIProviders);
const createModel = vi.mocked(createAIModel);
const healthCheck = vi.mocked(checkAIModelHealth);
const deleteModel = vi.mocked(deleteAIModel);
const getDeletePreview = vi.mocked(getAIModelDeletePreview);
const updateModel = vi.mocked(updateAIModel);
const setDefault = vi.mocked(setAIUserDefaultModel);
const upsertRoute = vi.mocked(upsertAIModelRoute);
const showToast = vi.fn();

describe('ModelManagementTab browser key paths', () => {
  beforeEach(async () => {
    const { useCoreApp } = await import('../../../contexts/AppDomainContext');
    showToast.mockClear();
    deleteModel.mockClear();
    getDeletePreview.mockReset();
    getDeletePreview.mockResolvedValue({ route_count: 0, message_count: 0, can_delete: true } as any);
    vi.mocked(useCoreApp).mockReturnValue({ language: 'zh', currentUser: { role: 'Administrator' }, showToast } as never);
    getModels.mockResolvedValue([model as any]);
    getRoutes.mockResolvedValue([]);
    getProviders.mockResolvedValue([provider as any]);
    createModel.mockResolvedValue(model as any);
    healthCheck.mockResolvedValue({
      model_id: model.id,
      model_name: model.name,
      model_code: model.model_code,
      success: true,
      health_status: 'healthy',
      latency_ms: 42,
      last_health_check_at: '2026-09-10T00:00:00Z',
      message: 'ok',
      sla_window_hours: 24,
      sla_check_count: 1,
      sla_success_count: 1,
      sla_failure_count: 0,
      sla_availability_percent: 100,
      sla_avg_latency_ms: 42,
    });
    updateModel.mockResolvedValue(model as any);
    setDefault.mockResolvedValue(undefined as any);
    upsertRoute.mockResolvedValue({ id: 'route-1', scene: 'chat', model_id: model.id, enabled: true } as any);
  });

  afterEach(() => cleanup());

  it('renders model/provider mapping and switches the default and scene route', async () => {
    const user = userEvent.setup();
    render(<ModelManagementTab />);
    expect((await screen.findAllByText('DeepSeek V4 Flash')).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('DeepSeek 主供应商').some((element) => element.tagName === 'DIV')).toBe(true);
    await user.click(screen.getByTitle('设为当前用户默认'));
    expect(updateModel).toHaveBeenCalledWith(model.id, { is_default: true });
    expect(setDefault).toHaveBeenCalledWith(model.id);

    await user.selectOptions(screen.getByRole('combobox', { name: '命令解释模型路由' }), model.id);
    await waitFor(() => expect(upsertRoute).toHaveBeenCalledWith({ scene: 'command_explain', model_id: model.id, enabled: true }));
  });

  it('batch assigns a primary model to all selected scenes', async () => {
    const user = userEvent.setup();
    render(<ModelManagementTab />);

    await screen.findAllByText('DeepSeek V4 Flash');
    await user.click(screen.getByRole('checkbox', { name: '全选场景' }));
    await user.selectOptions(screen.getByRole('combobox', { name: '批量设置主模型' }), model.id);
    await user.click(screen.getByRole('button', { name: '应用到选中场景' }));

    await waitFor(() => expect(upsertRoute).toHaveBeenCalledTimes(12));
    expect(upsertRoute).toHaveBeenCalledWith(expect.objectContaining({
      scene: 'command_explain',
      model_id: model.id,
      enabled: true,
      priority: 10,
      data_classification: 'PUBLIC',
    }));
    expect(showToast).toHaveBeenCalledWith('已将 DeepSeek V4 Flash 设置到 12 个场景', 'success');
  });

  it('runs an explicit model health check and reports the result', async () => {
    const user = userEvent.setup();
    render(<ModelManagementTab />);

    await screen.findAllByText('DeepSeek V4 Flash');
    await user.click(screen.getByRole('button', { name: '立即检查模型健康' }));

    await waitFor(() => expect(healthCheck).toHaveBeenCalledWith(model.id));
    expect(showToast).toHaveBeenCalledWith('“DeepSeek V4 Flash”健康检查通过（42 ms）', 'success');
  });

  it('batch assigns data classification without requiring a primary model change', async () => {
    const user = userEvent.setup();
    render(<ModelManagementTab />);

    await screen.findAllByText('DeepSeek V4 Flash');
    await user.click(screen.getByRole('checkbox', { name: '全选场景' }));
    await user.selectOptions(screen.getByRole('combobox', { name: '批量设置数据分类' }), 'INTERNAL');
    await user.click(screen.getByRole('button', { name: '应用到选中场景' }));

    await waitFor(() => expect(upsertRoute).toHaveBeenCalledTimes(12));
    expect(upsertRoute).toHaveBeenCalledWith(expect.objectContaining({
      scene: 'command_explain',
      model_id: model.id,
      enabled: true,
      priority: 10,
      data_classification: 'INTERNAL',
    }));
    expect(showToast).toHaveBeenCalledWith('已将数据分类 INTERNAL 设置到 12 个场景', 'success');
  });

  it('opens the model creation path and keeps an empty model list usable', async () => {
    const user = userEvent.setup();
    getModels.mockResolvedValueOnce([]);
    render(<ModelManagementTab />);
    expect(await screen.findByText('AI Model 模型管理')).toBeTruthy();
    expect(screen.queryByText('DeepSeek V4 Flash')).toBeNull();
    await user.click(screen.getByRole('button', { name: '添加 Model' }));
    await user.type(screen.getByPlaceholderText('例如：DeepSeek V4 Flash'), '备用模型');
    await user.type(screen.getByPlaceholderText('deepseek-v4-flash'), 'backup-model');
    await user.click(screen.getByRole('button', { name: '确认添加' }));
    await waitFor(() => expect(createModel).toHaveBeenCalledWith(expect.objectContaining({ name: '备用模型', model_code: 'backup-model', provider_id: provider.id })));
  });

  it('explains historical provenance before sending an impossible model delete request', async () => {
    getDeletePreview.mockResolvedValueOnce({ route_count: 0, message_count: 23, can_delete: false } as any);
    const user = userEvent.setup();
    render(<ModelManagementTab />);

    await screen.findAllByText('DeepSeek V4 Flash');
    await user.click(screen.getByRole('button', { name: '删除' }));

    await waitFor(() => expect(showToast).toHaveBeenCalledWith(
      '暂时不能删除“DeepSeek V4 Flash”：已有 23 条历史对话保留了它的模型溯源。历史溯源不能物理删除；如果只是暂时不用，请直接禁用模型。',
      'error',
    ));
    expect(deleteModel).not.toHaveBeenCalled();
  });

  it('cancels deletion safely when the usage preview is unavailable', async () => {
    getDeletePreview.mockRejectedValueOnce(new Error('preview unavailable'));
    const user = userEvent.setup();
    render(<ModelManagementTab />);

    await screen.findAllByText('DeepSeek V4 Flash');
    await user.click(screen.getByRole('button', { name: '删除' }));

    await waitFor(() => expect(showToast).toHaveBeenCalledWith(
      '暂时无法确认模型是否仍在使用，已取消删除以保护历史记录。请刷新页面后重试。',
      'error',
    ));
    expect(deleteModel).not.toHaveBeenCalled();
  });
});
