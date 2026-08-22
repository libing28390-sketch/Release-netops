import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';

const apiMocks = vi.hoisted(() => ({
  chatAssistantStream: vi.fn(),
  listAIConversations: vi.fn(),
  createAIConversation: vi.fn(),
  getAIConversation: vi.fn(),
  getAIProviders: vi.fn(),
  getAIModels: vi.fn(),
  clearAIConversation: vi.fn(),
  deleteAIConversation: vi.fn(),
  importAIConversationMessages: vi.fn(),
  renameAIConversation: vi.fn(),
  archiveAIConversation: vi.fn(),
  submitCopilotFeedback: vi.fn(),
  checkCopilotAttachment: vi.fn(),
  createCopilotCase: vi.fn(),
  handoffCopilotCase: vi.fn(),
  createDiagnosticPlan: vi.fn(),
  runDiagnosticPlan: vi.fn(),
}));

vi.mock('../../../api/ai', () => apiMocks);

import { AssistantTab } from './AssistantTab';

const isoNow = new Date().toISOString();

const primeBackendMocks = () => {
  vi.mocked(apiMocks.renameAIConversation).mockResolvedValue({ title: '新对话', updated_at: isoNow });
  apiMocks.listAIConversations.mockResolvedValue({ items: [] });
  apiMocks.createAIConversation.mockResolvedValue({
    id: 'conv_test1',
    title: '新对话',
    status: 'active',
    created_at: isoNow,
    updated_at: isoNow,
  });
  apiMocks.getAIConversation.mockResolvedValue({
    conversation: { title: '新对话', status: 'active', updated_at: isoNow },
    messages: [],
  });
  apiMocks.getAIProviders.mockResolvedValue([]);
  apiMocks.getAIModels.mockResolvedValue([]);
};

describe('AssistantTab streaming render', () => {
  beforeAll(() => {
    // jsdom does not implement element scrolling; the auto-scroll effect only needs a no-op.
    if (typeof Element.prototype.scrollTo !== 'function') {
      Element.prototype.scrollTo = () => {};
    }
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('renders the complete answer after frame-batched stream tokens flush', async () => {
    primeBackendMocks();
    const tokens = ['OSPF 邻居表为空', '通常意味着', 'Hello 报文', '未能交换', '，请检查区域号一致性。'];
    apiMocks.chatAssistantStream.mockImplementation(
      async (_message: string, _history: unknown, onToken: (t: string) => void) => {
        for (const piece of tokens) {
          onToken(piece);
        }
      },
    );

    const user = userEvent.setup();
    render(<AssistantTab />);

    const input = screen.getByPlaceholderText('询问 Nexora AI，或输入 / 使用快捷指令...');
    await user.type(input, 'OSPF 邻居为空怎么排查');
    await user.click(screen.getByRole('button', { name: '发送' }));

    const expected = tokens.join('');
    await waitFor(() => {
      expect(screen.getByText(expected)).toBeTruthy();
    });
    // Token batching must coalesce into the exact answer, without loss or duplication.
    expect(apiMocks.chatAssistantStream).toHaveBeenCalledTimes(1);
  });

  it('keeps the tail token that arrives in the same frame as stream completion', async () => {
    primeBackendMocks();
    apiMocks.chatAssistantStream.mockImplementation(
      async (_message: string, _history: unknown, onToken: (t: string) => void) => {
        onToken('接口 ');
        onToken('GigabitEthernet0/0/1 ');
        onToken('处于 down 状态');
      },
    );

    const user = userEvent.setup();
    render(<AssistantTab />);

    const input = screen.getByPlaceholderText('询问 Nexora AI，或输入 / 使用快捷指令...');
    await user.type(input, '接口 down 了');
    await user.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(screen.getByText('接口 GigabitEthernet0/0/1 处于 down 状态')).toBeTruthy();
    });
  });
});
