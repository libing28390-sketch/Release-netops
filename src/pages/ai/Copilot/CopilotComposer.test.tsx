import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CopilotComposer, type CopilotModelOption } from './CopilotComposer';

const models: CopilotModelOption[] = [
  { id: 'model-a', name: 'Model Alpha', model_code: 'alpha', provider_name: 'Provider A', model_type: 'chat', health_status: 'healthy' },
  { id: 'model-b', name: 'Model Beta', model_code: 'beta', provider_name: 'Provider A', model_type: 'reasoning', health_status: 'healthy' },
];

describe('CopilotComposer selection controls', () => {
  afterEach(() => cleanup());

  it('exposes the selected model and reasoning option while allowing the choice to change', async () => {
    const onSelectModel = vi.fn();
    const { rerender } = render(
      <CopilotComposer onSend={vi.fn()} models={models} selectedModel="model-a" onSelectModel={onSelectModel} />,
    );

    fireEvent.click(screen.getByTitle('点击展开模型与推理控制面板'));
    fireEvent.click(screen.getByText('模型'));
    const alphaOption = screen.getByText('Model Alpha').closest('button');
    const betaOption = screen.getByText('Model Beta').closest('button');
    expect(alphaOption?.getAttribute('aria-pressed')).toBe('true');
    expect(betaOption?.getAttribute('aria-pressed')).toBe('false');

    fireEvent.click(screen.getByText('Model Beta'));
    expect(onSelectModel).toHaveBeenCalledWith('model-b');
    await waitFor(() => expect(document.activeElement?.textContent).toContain('模型'));
    rerender(<CopilotComposer onSend={vi.fn()} models={models} selectedModel="model-b" onSelectModel={onSelectModel} />);
    fireEvent.click(screen.getByText('模型'));
    expect(screen.getByText('Model Beta').closest('button')?.getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByText('推理强度'));
    expect(screen.getByRole('button', { name: '最高 (深度思考 R1)' }).getAttribute('aria-pressed')).toBe('true');
    const normalReasoning = screen.getByRole('button', { name: '常规' });
    expect(normalReasoning.getAttribute('aria-pressed')).toBe('false');

    fireEvent.click(normalReasoning);
    fireEvent.click(screen.getByText('推理强度'));
    expect(screen.getByRole('button', { name: '常规' }).getAttribute('aria-pressed')).toBe('true');
  });

  it('closes non-modal popovers with Escape and restores focus to each trigger', async () => {
    render(<CopilotComposer onSend={vi.fn()} models={models} selectedModel="model-a" onSelectModel={vi.fn()} />);

    const modelTrigger = screen.getByTitle('点击展开模型与推理控制面板');
    fireEvent.click(modelTrigger);
    expect(screen.getByText('推理强度')).toBeTruthy();
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(document.activeElement).toBe(modelTrigger));
    expect(screen.queryByText('推理强度')).toBeNull();

    const quickMenuTrigger = screen.getByTitle('打开快捷指令');
    fireEvent.click(quickMenuTrigger);
    expect(screen.getByText('快捷指令')).toBeTruthy();
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(document.activeElement).toBe(quickMenuTrigger));
    expect(screen.queryByText('快捷指令')).toBeNull();
  });
});
