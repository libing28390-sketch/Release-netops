import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ModelManagementTab } from './ModelManagementTab';
import {
  createAIModel,
  getAIModelRoutes,
  getAIModels,
  getAIProviders,
  setAIUserDefaultModel,
  updateAIModel,
  upsertAIModelRoute,
} from '../../../api/ai';

vi.mock('../../../api/ai', () => ({
  createAIModel: vi.fn(),
  deleteAIModel: vi.fn(),
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
const updateModel = vi.mocked(updateAIModel);
const setDefault = vi.mocked(setAIUserDefaultModel);
const upsertRoute = vi.mocked(upsertAIModelRoute);

describe('ModelManagementTab browser key paths', () => {
  beforeEach(() => {
    getModels.mockResolvedValue([model as any]);
    getRoutes.mockResolvedValue([]);
    getProviders.mockResolvedValue([provider as any]);
    createModel.mockResolvedValue(model as any);
    updateModel.mockResolvedValue(model as any);
    setDefault.mockResolvedValue(undefined as any);
    upsertRoute.mockResolvedValue({ id: 'route-1', scene: 'chat', model_id: model.id, enabled: true } as any);
  });

  afterEach(() => cleanup());

  it('renders model/provider mapping and switches the default and scene route', async () => {
    const user = userEvent.setup();
    render(<ModelManagementTab />);
    expect(await screen.findByText('DeepSeek V4 Flash')).toBeTruthy();
    expect(screen.getAllByText('DeepSeek 主供应商').some((element) => element.tagName === 'DIV')).toBe(true);
    await user.click(screen.getByTitle('设为当前用户默认'));
    expect(updateModel).toHaveBeenCalledWith(model.id, { is_default: true });
    expect(setDefault).toHaveBeenCalledWith(model.id);

    await user.selectOptions(screen.getByRole('combobox', { name: '命令解释模型路由' }), model.id);
    await waitFor(() => expect(upsertRoute).toHaveBeenCalledWith({ scene: 'command_explain', model_id: model.id, enabled: true }));
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
});
