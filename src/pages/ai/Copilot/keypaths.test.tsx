import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import CopilotComposer from './CopilotComposer';
import { CopilotHeader } from './CopilotHeader';

const models = [
  { id: 'm-deepseek', name: 'DeepSeek V4 Flash', model_code: 'deepseek-v4-flash', provider_name: 'DeepSeek', model_type: 'chat', context_length: 128000, health_status: 'healthy' },
  { id: 'm-openai', name: 'OpenAI GPT-4o', model_code: 'gpt-4o', provider_name: 'OpenAI', model_type: 'chat', context_length: 128000, health_status: 'healthy' },
];

describe('Copilot browser key paths', () => {
  afterEach(() => cleanup());

  it('sends a question, switches models, and captures diagnostic context', async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    const onSelectModel = vi.fn();
    const onContextChange = vi.fn();
    render(
      <CopilotComposer
        onSend={onSend}
        selectedModel="m-deepseek"
        onSelectModel={onSelectModel}
        models={models}
        onContextChange={onContextChange}
      />,
    );

    const input = screen.getByPlaceholderText('询问 Nexora AI，或输入 / 使用快捷指令...');
    await user.type(input, '查询 OSPF 邻居状态');
    await user.click(screen.getByRole('button', { name: '发送' }));
    expect(onSend).toHaveBeenCalledWith('查询 OSPF 邻居状态');

    await user.click(screen.getByTitle('点击展开模型与推理控制面板'));
    await user.click(screen.getByRole('button', { name: /模型/ }));
    await user.click(screen.getByRole('button', { name: /OpenAI GPT-4o/ }));
    expect(onSelectModel).toHaveBeenCalledWith('m-openai');

    await user.click(screen.getByRole('button', { name: '选择诊断范围' }));
    fireEvent.change(screen.getByRole('textbox', { name: '厂商' }), { target: { value: 'Cisco' } });
    expect(onContextChange.mock.calls.at(-1)?.[0]).toEqual({ vendor: 'Cisco' });
  });

  it('loads an existing question for editing and sends the revised text', async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    const onEditDraftConsumed = vi.fn();
    render(
      <CopilotComposer
        onSend={onSend}
        editDraft="查询原始问题"
        onEditDraftConsumed={onEditDraftConsumed}
      />,
    );

    const input = screen.getByPlaceholderText('询问 Nexora AI，或输入 / 使用快捷指令...');
    await waitFor(() => expect((input as HTMLTextAreaElement).value).toBe('查询原始问题'));
    expect(screen.getByText('正在编辑问题，修改后点击发送即可提交新问题')).toBeTruthy();

    await user.clear(input);
    await user.type(input, '查询修改后的问题');
    await user.click(screen.getByRole('button', { name: '发送' }));

    expect(onSend).toHaveBeenCalledWith('查询修改后的问题');
    expect(screen.queryByText('正在编辑问题，修改后点击发送即可提交新问题')).toBeNull();
  });

  it('keeps header model selection and inspector actions keyboard accessible', async () => {
    const user = userEvent.setup();
    const onSelectModel = vi.fn();
    const onClearChat = vi.fn();
    render(
      <CopilotHeader
        sessionTitle="OSPF 排障"
        selectedModel="m-deepseek"
        onSelectModel={onSelectModel}
        models={models}
        onClearChat={onClearChat}
      />,
    );
    await user.selectOptions(screen.getByRole('combobox'), 'm-openai');
    expect(onSelectModel).toHaveBeenCalledWith('m-openai');
    await user.click(screen.getByTitle('清空当前对话'));
    expect(onClearChat).toHaveBeenCalledTimes(1);
  });
});
