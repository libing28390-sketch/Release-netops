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

  it('shows timestamps for both sides and omits prompt-backed assistant actions', async () => {
    primeBackendMocks();
    apiMocks.chatAssistantStream.mockImplementation(
      async (_message: string, _history: unknown, onToken: (t: string) => void) => {
        onToken('带时间的回答');
      },
    );

    const user = userEvent.setup();
    render(<AssistantTab />);
    await user.type(screen.getByPlaceholderText('询问 Nexora AI，或输入 / 使用快捷指令...'), '请回答并显示时间');
    await user.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => expect(screen.getByText('带时间的回答')).toBeTruthy());
    expect(document.querySelectorAll('[data-copilot-message-time="true"]')).toHaveLength(2);
    expect(screen.queryByRole('button', { name: '重试本次问题' })).toBeNull();
    expect(screen.queryByRole('button', { name: '编辑并发送上一条问题' })).toBeNull();
    expect(screen.queryByRole('button', { name: '继续排查' })).toBeNull();
    expect(screen.getByRole('button', { name: '复制全文' })).toBeTruthy();
  });

  it('labels a grounded answer as local with zero model tokens', async () => {
    primeBackendMocks();
    apiMocks.chatAssistantStream.mockImplementation(
      async (
        _message: string,
        _history: unknown,
        onToken: (t: string) => void,
        onMeta: (meta: Record<string, unknown>) => void,
        _onProgress: unknown,
        onDone: (meta: Record<string, unknown>) => void,
      ) => {
        onMeta({ execution_mode: 'local_knowledge', external_egress: false, input_tokens: 0, output_tokens: 0 });
        onToken('本地知识答案');
        onDone({ execution_mode: 'local_knowledge', external_egress: false, input_tokens: 0, output_tokens: 0, duration_ms: 12 });
      },
    );

    const user = userEvent.setup();
    render(<AssistantTab />);
    await user.type(screen.getByPlaceholderText('询问 Nexora AI，或输入 / 使用快捷指令...'), 'S5700 OSPF 配置');
    await user.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => expect(screen.getByText('本地知识直出')).toBeTruthy());
    expect(screen.getByText('未发生外部调用')).toBeTruthy();
    expect(screen.getByText('模型 Token：输入 0 / 输出 0')).toBeTruthy();
  });

  it('labels a real provider answer with its actual DeepSeek route and usage', async () => {
    primeBackendMocks();
    apiMocks.getAIProviders.mockResolvedValue([{ id: 'provider-deepseek', name: 'DeepSeek', enabled: true }]);
    apiMocks.getAIModels.mockResolvedValue([{
      id: 'model-deepseek-chat',
      provider_id: 'provider-deepseek',
      name: 'DeepSeek Chat',
      model_code: 'deepseek-chat',
      model_type: 'chat',
      enabled: true,
    }]);
    apiMocks.chatAssistantStream.mockImplementation(
      async (
        _message: string,
        _history: unknown,
        onToken: (t: string) => void,
        onMeta: (meta: Record<string, unknown>) => void,
        _onProgress: unknown,
        onDone: (meta: Record<string, unknown>) => void,
      ) => {
        onToken('云端回答');
        onMeta({
          execution_mode: 'provider_generated',
          external_egress: true,
          model_id: 'model-deepseek-chat',
          provider_id: 'provider-deepseek',
          input_tokens: 18,
          output_tokens: 7,
          token_source: 'provider_reported',
        });
        onDone({
          execution_mode: 'provider_generated',
          external_egress: true,
          model_id: 'model-deepseek-chat',
          provider_id: 'provider-deepseek',
          input_tokens: 18,
          output_tokens: 7,
          token_source: 'provider_reported',
          duration_ms: 42,
        });
      },
    );

    const user = userEvent.setup();
    render(<AssistantTab />);
    await user.type(screen.getByPlaceholderText('询问 Nexora AI，或输入 / 使用快捷指令...'), '你是谁');
    await user.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => expect(screen.getByText('DeepSeek 生成')).toBeTruthy());
    expect(screen.getByText('已通过安全网关调用外部模型')).toBeTruthy();
    expect(screen.getByText('实际模型：DeepSeek · deepseek-chat')).toBeTruthy();
    expect(screen.getByText('实际 Token：输入 18 / 输出 7')).toBeTruthy();
  });

  it('shows an actionable message when the selected provider is unavailable', async () => {
    primeBackendMocks();
    apiMocks.chatAssistantStream.mockImplementation(async (...args: any[]) => {
      const onError = args[6] as (error: { code: string }) => void;
      onError({ code: 'AI_PROVIDER_UNSUPPORTED' });
    });

    const user = userEvent.setup();
    render(<AssistantTab />);
    await user.type(screen.getByPlaceholderText('询问 Nexora AI，或输入 / 使用快捷指令...'), '请检查设备状态');
    await user.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => expect(screen.getByText(/模型服务暂时不可用，未执行任何设备操作/)).toBeTruthy());
    expect(screen.getByText(/Provider\/模型配置/)).toBeTruthy();
  });

  it('renders a clarification card and submits its bounded state on selection', async () => {
    primeBackendMocks();
    const clarification = {
      required: true,
      state_id: 'clar_ui',
      revision: 1,
      request_kind: 'configuration_reference',
      risk: 'medium',
      missing_fields: ['feature', 'platform_or_model'],
      question: '请补充配置功能和设备平台。',
      options: [
        { field: 'feature', value: 'vlan', label: 'VLAN / Access / Trunk' },
        { field: 'cli_platform', value: 'huawei_yunshan_v600', label: 'Huawei YunShan V600' },
      ],
      allow_free_text: true,
      retrieval_allowed: false,
    };
    apiMocks.chatAssistantStream.mockImplementation(
      async (...args: any[]) => {
        const message = args[0] as string;
        const onToken = args[2] as (token: string) => void;
        const onMeta = args[3] as (meta: Record<string, unknown>) => void;
        const onDone = args[5] as (meta: Record<string, unknown>) => void;
        if (message === '请给我华为交换机配置') {
          onMeta({
            intent: 'knowledge',
            clarification,
            execution_mode: 'local_clarification',
            external_egress: false,
          });
          onToken('请补充范围');
          onDone({ execution_mode: 'local_clarification', external_egress: false, duration_ms: 5 });
          return;
        }

        expect(args[15]).toMatchObject({
          state_id: 'clar_ui',
          revision: 1,
          values: { feature: 'vlan' },
          action: 'submit',
        });
        onMeta({ intent: 'knowledge', execution_mode: 'local_knowledge', external_egress: false });
        onToken('已按范围返回');
        onDone({ execution_mode: 'local_knowledge', external_egress: false, duration_ms: 8 });
      },
    );

    const user = userEvent.setup();
    render(<AssistantTab />);
    const input = screen.getByPlaceholderText('询问 Nexora AI，或输入 / 使用快捷指令...');
    await user.type(input, '请给我华为交换机配置');
    await user.click(screen.getByRole('button', { name: '发送' }));

    const option = await screen.findByRole('button', { name: /VLAN \/ Access \/ Trunk/ });
    await user.click(option);
    await waitFor(() => expect(screen.getByText('已按范围返回')).toBeTruthy());
    expect(apiMocks.chatAssistantStream).toHaveBeenCalledTimes(2);
  });
});
