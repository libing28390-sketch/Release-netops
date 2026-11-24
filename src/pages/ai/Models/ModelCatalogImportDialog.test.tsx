import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AIProvider, AIProviderCatalogModel } from '../../../api/ai';
import { getAIProviderModelCatalog, importAIProviderModels } from '../../../api/ai';
import { ModelCatalogImportDialog } from './ModelCatalogImportDialog';

vi.mock('../../../api/ai', () => ({
  getAIProviderModelCatalog: vi.fn(),
  importAIProviderModels: vi.fn(),
}));

const provider: AIProvider = {
  id: 'provider-1',
  name: 'Gemini',
  provider_type: 'google',
  timeout: 30,
  max_retries: 2,
  enabled: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const model = (model_code: string, model_type: AIProviderCatalogModel['model_type'], already_registered = false): AIProviderCatalogModel => ({
  model_code,
  name: model_code,
  model_type,
  already_registered,
});

const fetchCatalog = vi.mocked(getAIProviderModelCatalog);
const importModels = vi.mocked(importAIProviderModels);
const onClose = vi.fn();
const onImported = vi.fn();

const renderDialog = () => render(
  <ModelCatalogImportDialog providers={[provider]} language="zh" onClose={onClose} onImported={onImported} />,
);

describe('ModelCatalogImportDialog', () => {
  beforeEach(() => {
    fetchCatalog.mockReset();
    importModels.mockReset();
    onClose.mockReset();
    onImported.mockReset();
    importModels.mockResolvedValue({ created: 2, skipped: 0 });
  });

  afterEach(() => cleanup());

  it('fetches on demand, defaults only account chat models, and imports selected typed items', async () => {
    const user = userEvent.setup();
    fetchCatalog.mockResolvedValue({
      source: 'account',
      items: [model('chat-model', 'chat'), model('embedding-model', 'embedding'), model('unknown-model', 'unknown'), model('rerank-model', 'rerank'), model('registered-model', 'chat', true)],
    });
    renderDialog();

    expect(fetchCatalog).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: '读取模型列表' }));
    await screen.findByText('找到 5 个模型');
    expect(fetchCatalog).toHaveBeenCalledWith(provider.id);

    const chat = screen.getByRole('checkbox', { name: '选择 chat-model (chat-model)' }) as HTMLInputElement;
    const embedding = screen.getByRole('checkbox', { name: '选择 embedding-model (embedding-model)' }) as HTMLInputElement;
    const unknown = screen.getByRole('checkbox', { name: '选择 unknown-model (unknown-model)' }) as HTMLInputElement;
    const rerank = screen.getByRole('checkbox', { name: '选择 rerank-model (rerank-model)' }) as HTMLInputElement;
    const registered = screen.getByRole('checkbox', { name: '选择 registered-model (registered-model)' }) as HTMLInputElement;
    expect(chat.checked).toBe(true);
    expect(embedding.checked).toBe(false);
    expect(unknown.checked).toBe(false);
    expect(rerank.checked).toBe(false);
    expect(registered.disabled).toBe(true);

    await user.click(unknown);
    await user.selectOptions(screen.getByRole('combobox', { name: '为 unknown-model 指定类型' }), 'rerank');
    await user.click(rerank);
    await user.click(screen.getByRole('button', { name: '导入所选 (3)' }));

    await waitFor(() => expect(importModels).toHaveBeenCalledWith(provider.id, [
      { model_code: 'chat-model', name: 'chat-model', model_type: 'chat' },
      { model_code: 'unknown-model', name: 'unknown-model', model_type: 'rerank' },
      { model_code: 'rerank-model', name: 'rerank-model', model_type: 'rerank' },
    ]));
    expect(onImported).toHaveBeenCalledWith({ created: 2, skipped: 0 });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('does not preselect public catalog entries and offers a bulk selection of eligible rows', async () => {
    const user = userEvent.setup();
    fetchCatalog.mockResolvedValue({
      source: 'public',
      items: [model('public-chat', 'chat'), model('public-embedding', 'embedding'), model('public-unknown', 'unknown')],
    });
    renderDialog();

    await user.click(screen.getByRole('button', { name: '读取模型列表' }));
    expect(await screen.findByText(/官方公开目录/)).toBeTruthy();
    expect((screen.getByRole('checkbox', { name: '选择 public-chat (public-chat)' }) as HTMLInputElement).checked).toBe(false);
    await user.click(screen.getByRole('button', { name: '全选当前可导入项 (2)' }));
    expect((screen.getByRole('checkbox', { name: '选择 public-chat (public-chat)' }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole('checkbox', { name: '选择 public-embedding (public-embedding)' }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole('checkbox', { name: '选择 public-unknown (public-unknown)' }) as HTMLInputElement).checked).toBe(false);
  });

  it('assigns a type to selected unknown catalog models in bulk', async () => {
    const user = userEvent.setup();
    fetchCatalog.mockResolvedValue({ source: 'account', items: [model('unknown-model', 'unknown')] });
    renderDialog();

    await user.click(screen.getByRole('button', { name: '读取模型列表' }));
    await screen.findByText('找到 1 个模型');
    await user.click(screen.getByRole('checkbox', { name: '选择 unknown-model (unknown-model)' }));
    await user.selectOptions(screen.getByRole('combobox', { name: '为已选未知类型项指定类型 (1)' }), 'reasoning');
    await user.click(screen.getByRole('button', { name: '应用' }));
    await user.click(screen.getByRole('button', { name: '导入所选 (1)' }));

    await waitFor(() => expect(importModels).toHaveBeenCalledWith(provider.id, [
      { model_code: 'unknown-model', name: 'unknown-model', model_type: 'reasoning' },
    ]));
  });

  it('shows a permission state when catalog access is denied', async () => {
    const user = userEvent.setup();
    fetchCatalog.mockRejectedValue(Object.assign(new Error('forbidden'), { status: 403 }));
    renderDialog();

    await user.click(screen.getByRole('button', { name: '读取模型列表' }));
    expect((await screen.findByRole('alert')).textContent).toContain('当前账号没有读取此 Provider 模型目录的权限。');
    expect((screen.getByRole('button', { name: '读取模型列表' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('announces catalog loading while the request is pending', async () => {
    const user = userEvent.setup();
    let resolveCatalog: ((value: { source: 'account'; items: AIProviderCatalogModel[] }) => void) | undefined;
    fetchCatalog.mockReturnValue(new Promise((resolve) => { resolveCatalog = resolve; }));
    renderDialog();

    await user.click(screen.getByRole('button', { name: '读取模型列表' }));
    expect(screen.getByRole('status').textContent).toContain('正在读取 Gemini 的模型列表');
    resolveCatalog?.({ source: 'account', items: [] });
    await waitFor(() => expect(screen.getByText('找到 0 个模型')).toBeTruthy());
  });

  it('uses the first provider when provider data arrives after the dialog opens', async () => {
    const user = userEvent.setup();
    fetchCatalog.mockResolvedValue({ source: 'account', items: [] });
    const view = render(<ModelCatalogImportDialog providers={[]} language="zh" onClose={onClose} onImported={onImported} />);
    expect((screen.getByRole('button', { name: '读取模型列表' }) as HTMLButtonElement).disabled).toBe(true);

    view.rerender(<ModelCatalogImportDialog providers={[provider]} language="zh" onClose={onClose} onImported={onImported} />);
    await user.click(screen.getByRole('button', { name: '读取模型列表' }));
    await screen.findByText('找到 0 个模型');
    expect(fetchCatalog).toHaveBeenCalledWith(provider.id);
  });

  it('submits deduplicated pasted IDs without fetching the catalog', async () => {
    const user = userEvent.setup();
    importModels.mockResolvedValue({ created: 2, skipped: 0 });
    renderDialog();

    await user.click(screen.getByRole('tab', { name: '批量粘贴模型 ID' }));
    expect((screen.getByRole('textbox', { name: '批量粘贴模型 ID' }) as HTMLTextAreaElement).placeholder).toContain('model-id-1');
    await user.type(screen.getByRole('textbox', { name: '批量粘贴模型 ID' }), ' model-a \nmodel-b\nmodel-a\n   ');
    await user.selectOptions(screen.getByRole('combobox', { name: '整批模型类型' }), 'rerank');
    expect(screen.getByRole('status').textContent).toContain('识别到 2 个唯一 ID，已去除 1 个重复项');
    await user.click(screen.getByRole('button', { name: '导入输入 ID (2)' }));

    await waitFor(() => expect(importModels).toHaveBeenCalledWith(provider.id, [
      { model_code: 'model-a', name: 'model-a', model_type: 'rerank' },
      { model_code: 'model-b', name: 'model-b', model_type: 'rerank' },
    ]));
    expect(fetchCatalog).not.toHaveBeenCalled();
    expect(onImported).toHaveBeenCalledWith({ created: 2, skipped: 0 });
  });

  it('prevents batches larger than 500 and tells the user to split them', async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(screen.getByRole('tab', { name: '批量粘贴模型 ID' }));
    const ids = Array.from({ length: 501 }, (_, index) => `model-${index + 1}`).join('\n');
    fireEvent.change(screen.getByRole('textbox', { name: '批量粘贴模型 ID' }), { target: { value: ids } });

    expect(screen.getByRole('status').textContent).toContain('每次最多导入 500 个，请拆成多批后提交');
    expect((screen.getByRole('button', { name: '导入输入 ID (501)' }) as HTMLButtonElement).disabled).toBe(true);
    expect(importModels).not.toHaveBeenCalled();
  });

  it('allows retrying the same import after a retryable server error', async () => {
    const user = userEvent.setup();
    fetchCatalog.mockResolvedValue({ source: 'account', items: [model('chat-model', 'chat')] });
    importModels.mockRejectedValueOnce(Object.assign(new Error('temporary server error'), { status: 500 }));
    importModels.mockResolvedValueOnce({ created: 1, skipped: 0 });
    renderDialog();

    await user.click(screen.getByRole('button', { name: '读取模型列表' }));
    await screen.findByText('找到 1 个模型');
    await user.click(screen.getByRole('button', { name: '导入所选 (1)' }));
    expect((await screen.findByRole('alert')).textContent).toContain('temporary server error');
    expect((screen.getByRole('button', { name: '导入所选 (1)' }) as HTMLButtonElement).disabled).toBe(false);
    await user.click(screen.getByRole('button', { name: '导入所选 (1)' }));
    await waitFor(() => expect(importModels).toHaveBeenCalledTimes(2));
    expect(onImported).toHaveBeenCalledWith({ created: 1, skipped: 0 });
  });
});
