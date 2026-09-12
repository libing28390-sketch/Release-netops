import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PromptCenterTab } from './PromptCenterTab';
import { getAIPromptAudit, getAIPromptVersions, getAIPromptsPage, updateAIPrompt } from '../../../api/ai';

vi.mock('../../../contexts/AppDomainContext', () => ({
  useCoreApp: vi.fn(),
}));

vi.mock('../../../api/ai', () => ({
  createAIPrompt: vi.fn(),
  copyAIPrompt: vi.fn(),
  compareAIPromptVersions: vi.fn(),
  getAIPromptAudit: vi.fn(),
  getAIPromptVersions: vi.fn(),
  getAIPromptsPage: vi.fn(),
  restoreAIPromptVersion: vi.fn(),
  updateAIPrompt: vi.fn(),
}));

const prompt = {
  id: 'prompt-change-plan',
  code: 'CHANGE_PLAN',
  name: '网络变更实施计划',
  scene: 'change_plan',
  vendor: 'all',
  platform: 'all',
  system_prompt: '只引用事实并输出可回滚计划。',
  user_prompt_template: '目标：{{objective}}\n约束：{{constraints}}',
  output_schema: '{"summary":"string","steps":[]}',
  temperature: 0.1,
  max_tokens: 3072,
  version: 1,
  enabled: true,
  created_by: 'system',
  created_at: '2026-08-17T00:00:00Z',
  updated_at: '2026-08-17T00:00:00Z',
};

const getPrompts = vi.mocked(getAIPromptsPage);
const getVersions = vi.mocked(getAIPromptVersions);
const getAudit = vi.mocked(getAIPromptAudit);
const updatePrompt = vi.mocked(updateAIPrompt);

describe('PromptCenterTab browser key paths', () => {
  beforeEach(async () => {
    const { useCoreApp } = await import('../../../contexts/AppDomainContext');
    vi.mocked(useCoreApp).mockReturnValue({ language: 'zh', showToast: vi.fn() } as never);
    getPrompts.mockResolvedValue({ items: [prompt as any], total: 1, page: 1, page_size: 20, total_pages: 1 });
    getVersions.mockResolvedValue([
      {
        id: 'prompt-version-1',
        prompt_id: prompt.id,
        version: 1,
        system_prompt: prompt.system_prompt,
        user_prompt_template: prompt.user_prompt_template,
        output_schema: prompt.output_schema,
        temperature: prompt.temperature,
        max_tokens: prompt.max_tokens,
        created_by: 'system',
        created_at: prompt.created_at,
      } as any,
    ]);
    getAudit.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20, total_pages: 1 });
    updatePrompt.mockImplementation(async (_id, data) => ({ ...prompt, ...data, version: data.system_prompt ? 2 : prompt.version } as any));
  });

  afterEach(() => cleanup());

  it('renders scene coverage, previews sanitized variables, loads versions, and edits a new version', async () => {
    const user = userEvent.setup();
    render(<PromptCenterTab />);

    expect(await screen.findByText('网络变更实施计划')).toBeTruthy();
    expect((await screen.findAllByText('网络变更计划')).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('2 个输入变量')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: '查看' }));
    expect(await screen.findByRole('dialog', { name: '网络变更实施计划' })).toBeTruthy();
    expect(getVersions).toHaveBeenCalledWith(prompt.id);
    await user.click(screen.getByRole('button', { name: '渲染样例' }));
    expect(screen.getByText(/在审批后启用一条备用上联/)).toBeTruthy();
    expect((await screen.findAllByText('v1')).length).toBeGreaterThanOrEqual(1);

    await user.click(screen.getByRole('button', { name: '编辑 Prompt' }));
    screen.getByRole('dialog', { name: '编辑 Prompt 提示词模板' });
    await user.clear(screen.getByLabelText(/System Prompt/));
    await user.type(screen.getByLabelText(/System Prompt/), '只输出可验证的回滚计划。');
    await user.type(screen.getByLabelText(/修改原因/), '补充回滚验证要求');
    await user.click(screen.getByRole('button', { name: '保存并生成新版本' }));

    await waitFor(() => expect(updatePrompt).toHaveBeenCalledWith(prompt.id, expect.objectContaining({
      system_prompt: '只输出可验证的回滚计划。',
      output_schema: prompt.output_schema,
    })));
    expect(screen.queryByRole('dialog', { name: '编辑 Prompt 提示词模板' })).toBeNull();
  }, 15000);

  it('blocks an invalid output contract before sending a create request', async () => {
    const user = userEvent.setup();
    render(<PromptCenterTab />);
    await screen.findByText('网络变更实施计划');

    await user.click(screen.getByRole('button', { name: '添加 Prompt' }));
    await user.clear(screen.getByLabelText(/Output Schema/));
    await user.type(screen.getByLabelText(/Output Schema/), 'not-json');

    expect(screen.getByText('Output Schema 不是有效 JSON')).toBeTruthy();
    expect((screen.getByRole('button', { name: '确认添加' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('toggles availability without exposing raw business requests', async () => {
    const user = userEvent.setup();
    updatePrompt.mockResolvedValueOnce({ ...prompt, enabled: false } as any);
    render(<PromptCenterTab />);
    await screen.findByText('网络变更实施计划');

    await user.click(screen.getByRole('button', { name: '停用 网络变更实施计划' }));
    await waitFor(() => expect(updatePrompt).toHaveBeenCalledWith(prompt.id, expect.objectContaining({ enabled: false, expected_version: prompt.version })));
    expect(screen.queryByText('sk-live-secret')).toBeNull();
    expect(screen.queryByText('真实业务请求')).toBeNull();
  });
});
