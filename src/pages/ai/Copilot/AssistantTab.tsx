import React, { useState, useEffect, useRef } from 'react';
import { Sparkles, BookOpen, ThumbsUp, ThumbsDown, Copy, SlidersHorizontal, Check, Clock3, ChevronDown, ChevronUp, ListChecks, Loader2, CheckCircle2, AlertCircle } from 'lucide-react';
import {
  AIConversationMessage,
  AssistantProcessStep,
  AssistantRetrievalTrace,
  chatAssistantStream,
  clearAIConversation,
  createAIConversation,
  deleteAIConversation,
  getAIConversation,
  getAIModels,
  getAIProviders,
  importAIConversationMessages,
  listAIConversations,
  renameAIConversation,
  archiveAIConversation,
} from '../../../api/ai';
import { MarkdownRenderer } from '../../../components/MarkdownRenderer';
import { copyTextWithFallback } from '../../../utils/clipboard';
import { CopilotSidebar, ChatSession } from './CopilotSidebar';
import { CopilotHeader } from './CopilotHeader';
import { CopilotEmptyState } from './CopilotEmptyState';
import { CopilotComposer, CopilotModelOption } from './CopilotComposer';
import { CopilotInspectorDrawer } from './CopilotInspectorDrawer';
import { formatCopilotDuration, upsertCopilotProcessStep } from './progress';

interface CitationSource {
  document: string;
  section: string;
}

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  intent?: string;
  sources?: CitationSource[];
  retrieval?: AssistantRetrievalTrace;
  created_at: string;
  latency_ms?: number;
  processing_steps?: AssistantProcessStep[];
}

const LEGACY_STORAGE_KEY = 'nexora_copilot_sessions_v4';
const SIDEBAR_COLLAPSED_KEY = 'nexora_copilot_sidebar_collapsed_v1';
const ARCHIVED_VIEW_KEY = 'nexora_copilot_archived_view_v1';

const formatSessionTime = (value: string | undefined): string => {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};

const mapConversationMessage = (message: AIConversationMessage): ChatMessage => ({
  id: message.id,
  role: message.role === 'user' ? 'user' : 'assistant',
  content: message.content || '',
  created_at: message.created_at,
  sources: Array.isArray(message.citations)
    ? message.citations.map((item: any) => ({
      document: String(item?.document || item?.document_name || 'Nexora'),
      section: String(item?.section || ''),
    }))
    : undefined,
});

const readLegacySessions = (): ChatSession[] => {
  try {
    const saved = localStorage.getItem(LEGACY_STORAGE_KEY);
    const parsed = saved ? JSON.parse(saved) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    console.error('Failed to load legacy Copilot sessions:', error);
    return [];
  }
};

const AssistantProcessPanel: React.FC<{
  steps: AssistantProcessStep[];
  expanded: boolean;
  onToggle: () => void;
  isStreaming: boolean;
  elapsedMs: number;
  latencyMs?: number;
}> = ({ steps, expanded, onToggle, isStreaming, elapsedMs, latencyMs }) => {
  const durationLabel = isStreaming
    ? `处理中 ${formatCopilotDuration(elapsedMs).replace('已处理 ', '')}`
    : formatCopilotDuration(latencyMs || 0);

  return (
    <div className="pt-1 space-y-2 select-none">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="inline-flex items-center gap-1.5 text-gray-500 dark:text-gray-400">
          <Clock3 className="w-3.5 h-3.5" />
          {durationLabel}
        </span>
        {steps.length > 0 && (
          <button
            type="button"
            onClick={onToggle}
            className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/70 px-2.5 py-1 text-gray-600 dark:text-gray-300 hover:border-indigo-300 hover:text-indigo-600 dark:hover:text-indigo-300 transition"
          >
            <ListChecks className="w-3.5 h-3.5" />
            <span>处理过程</span>
            <span className="text-[10px] text-gray-400">{steps.length} 步</span>
            {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>
        )}
      </div>

      {expanded && steps.length > 0 && (
        <div className="max-w-xl rounded-xl border border-gray-200/80 dark:border-gray-700 bg-gray-50/80 dark:bg-gray-800/50 px-3 py-2.5 space-y-2">
          {steps.map((step) => (
            <div key={step.id} className="flex items-start gap-2.5 text-xs">
              <div className="mt-0.5 shrink-0">
                {step.status === 'running' ? (
                  <Loader2 className="w-3.5 h-3.5 text-indigo-500 animate-spin" />
                ) : step.status === 'error' ? (
                  <AlertCircle className="w-3.5 h-3.5 text-rose-500" />
                ) : (
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
                )}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                  <span className="font-medium text-gray-700 dark:text-gray-200">{step.label}</span>
                  {step.status === 'running' && <span className="text-indigo-500">进行中</span>}
                  {step.status === 'error' && <span className="text-rose-500">失败</span>}
                </div>
                {step.detail && <div className="mt-0.5 text-gray-500 dark:text-gray-400">{step.detail}</div>}
                {step.operation && (
                  <code className="mt-1 inline-block max-w-full truncate rounded bg-white dark:bg-gray-900 px-1.5 py-0.5 text-[10px] text-gray-500 dark:text-gray-400">
                    {step.operation}
                  </code>
                )}
                {step.command && (
                  <code className="mt-1 block max-w-full overflow-x-auto rounded bg-gray-900 px-1.5 py-0.5 text-[10px] text-gray-200">
                    {step.command}
                  </code>
                )}
              </div>
            </div>
          ))}
          <div className="border-t border-gray-200/80 dark:border-gray-700 pt-2 text-[11px] text-gray-400 dark:text-gray-500">
            本次 Copilot 对话仅执行只读查询、知识检索和模型生成，未执行设备 CLI 命令。
          </div>
        </div>
      )}
    </div>
  );
};

export const AssistantTab: React.FC = () => {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState('');
  const [selectedModel, setSelectedModel] = useState('deepseek-v4-flash');
  const [availableModels, setAvailableModels] = useState<CopilotModelOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [sessionLoadingId, setSessionLoadingId] = useState<string | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === 'true');
  const [showArchived, setShowArchived] = useState(() => localStorage.getItem(ARCHIVED_VIEW_KEY) === 'true');
  const [isInspectorOpen, setIsInspectorOpen] = useState(false);
  const [activeInspectorMsg, setActiveInspectorMsg] = useState<ChatMessage | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [expandedSourcesId, setExpandedSourcesId] = useState<string | null>(null);
  const [expandedProcessId, setExpandedProcessId] = useState<string | null>(null);
  const [streamingMessageId, setStreamingMessageId] = useState<string | null>(null);
  const [liveElapsedMs, setLiveElapsedMs] = useState(0);

  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const requestStartedAtRef = useRef<number | null>(null);
  const loadedSessionIdsRef = useRef<Set<string>>(new Set());

  const activeSession = sessions.find((s) => s.id === activeSessionId);
  const messages = (activeSession?.messages || []) as ChatMessage[];
  // Keep the Copilot session rail under the user's control. Auto-collapsing it
  // at 900px made the conversation list look like an empty white strip in an
  // embedded browser and hid rename/archive actions.
  const compactSidebar = sidebarCollapsed;

  const loadSessionMessages = async (sessionId: string) => {
    if (!sessionId.startsWith('conv_') || loadedSessionIdsRef.current.has(sessionId)) return;
    loadedSessionIdsRef.current.add(sessionId);
    setSessionLoadingId(sessionId);
    try {
      const context = await getAIConversation(sessionId);
      const remoteMessages = context.messages
        .filter((message) => message.role === 'user' || message.role === 'assistant')
        .map(mapConversationMessage);
      setSessions((previous) => previous.map((session) => (
        session.id === sessionId
          ? {
            ...session,
            title: context.conversation.title || session.title || '新对话',
            status: context.conversation.status,
            updatedAt: formatSessionTime(context.conversation.updated_at),
            messages: remoteMessages,
          }
          : session
      )));
    } catch (error: any) {
      loadedSessionIdsRef.current.delete(sessionId);
      setSessionError(error?.message || '会话内容加载失败');
    } finally {
      setSessionLoadingId((current) => current === sessionId ? null : current);
    }
  };

  useEffect(() => {
    const fetchModelsAndProviders = async () => {
      try {
        const [providers, models] = await Promise.all([getAIProviders(), getAIModels()]);
        const enabledProviderMap = new Map(providers.filter((p) => p.enabled).map((p) => [p.id, p.name]));

        const validModels = models
          .filter((m) => m.enabled && enabledProviderMap.has(m.provider_id))
          .map((m) => ({
            id: m.id,
            name: m.name,
            model_code: m.model_code,
            provider_name: enabledProviderMap.get(m.provider_id) || 'AI 供应商',
          }));

        if (validModels.length > 0) {
          setAvailableModels(validModels);
          if (!validModels.some((m) => m.model_code === selectedModel)) {
            setSelectedModel(validModels[0].model_code);
          }
        }
      } catch (err) {
        console.error('Failed to load dynamic AI providers/models:', err);
      }
    };
    fetchModelsAndProviders();
  }, []);

  useEffect(() => {
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(sidebarCollapsed));
  }, [sidebarCollapsed]);

  useEffect(() => {
    localStorage.setItem(ARCHIVED_VIEW_KEY, String(showArchived));
  }, [showArchived]);

  useEffect(() => {
    let cancelled = false;
    const loadConversations = async () => {
      const legacySessions = readLegacySessions();
      try {
        const result = await listAIConversations(true);
        let remoteSessions: ChatSession[] = result.items.map((conversation) => ({
          id: conversation.id,
          title: conversation.title || '新对话',
          updatedAt: formatSessionTime(conversation.updated_at),
          messages: [],
          status: conversation.status,
          created_at: conversation.created_at,
          updated_at: conversation.updated_at,
        }));
        if (remoteSessions.length === 0 && legacySessions.length > 0) {
          const migratedSessions: ChatSession[] = [];
          for (const legacy of legacySessions.slice(0, 50)) {
            const created = await createAIConversation(legacy.title || '新对话');
            const legacyMessages = Array.isArray(legacy.messages)
              ? legacy.messages
                .filter((message: any) => message?.role === 'user' || message?.role === 'assistant')
                .map((message: any) => ({ role: message.role, content: String(message.content || '') }))
                .slice(0, 200)
              : [];
            if (legacyMessages.length > 0) {
              await importAIConversationMessages(created.id, legacyMessages);
            }
            migratedSessions.push({
              id: created.id,
              title: created.title || legacy.title || '新对话',
              updatedAt: formatSessionTime(created.updated_at),
              messages: [],
              status: created.status,
              created_at: created.created_at,
              updated_at: created.updated_at,
            });
          }
          remoteSessions = migratedSessions;
        }
        if (remoteSessions.length === 0) {
          const created = await createAIConversation();
          remoteSessions = [{
            id: created.id,
            title: created.title || '新对话',
            updatedAt: formatSessionTime(created.updated_at),
            messages: [],
            status: created.status,
            created_at: created.created_at,
            updated_at: created.updated_at,
          }];
        }
        if (cancelled) return;
        setSessions(remoteSessions);
        const first = remoteSessions.find((session) => session.status !== 'archived') || remoteSessions[0];
        setActiveSessionId(first.id);
        await loadSessionMessages(first.id);
      } catch (error: any) {
        if (cancelled) return;
        const fallback = legacySessions.length > 0 ? legacySessions : [{
          id: `local_${Date.now()}`,
          title: '新对话',
          updatedAt: formatSessionTime(new Date().toISOString()),
          messages: [],
        }];
        setSessions(fallback);
        setActiveSessionId(fallback[0].id);
        setSessionError(error?.message || '会话服务暂时不可用，当前显示本地缓存');
      }
    };
    void loadConversations();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!activeSessionId) return;
    void loadSessionMessages(activeSessionId);
  }, [activeSessionId]);

  useEffect(() => {
    const container = messagesContainerRef.current;
    if (!container) return;

    // Scroll the message list itself. Calling scrollIntoView here can select
    // the outer Copilot shell as the scroll container and move the sidebar
    // and header out of view in nested flex layouts.
    container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
  }, [messages, loading]);

  useEffect(() => {
    if (!loading || requestStartedAtRef.current === null) return;

    const updateElapsed = () => {
      if (requestStartedAtRef.current !== null) {
        setLiveElapsedMs(Date.now() - requestStartedAtRef.current);
      }
    };

    updateElapsed();
    const timer = window.setInterval(updateElapsed, 1000);
    return () => window.clearInterval(timer);
  }, [loading]);

  const createAndSelectSession = async (): Promise<string | null> => {
    try {
      const created = await createAIConversation();
      const newSession: ChatSession = {
        id: created.id,
        title: created.title || '新对话',
        updatedAt: formatSessionTime(created.updated_at),
        messages: [],
        status: created.status,
        created_at: created.created_at,
        updated_at: created.updated_at,
      };
      setSessions((previous) => [newSession, ...previous]);
      setActiveSessionId(newSession.id);
      setSessionError(null);
      return newSession.id;
    } catch (error: any) {
      setSessionError(error?.message || '新建会话失败');
      return null;
    }
  };

  const handleNewSession = () => {
    void createAndSelectSession();
  };

  const handleSelectSession = (id: string) => {
    setSessionError(null);
    setActiveSessionId(id);
    void loadSessionMessages(id);
  };

  const handleRenameSession = async (id: string, title: string) => {
    try {
      const updated = id.startsWith('conv_')
        ? await renameAIConversation(id, title)
        : { title, updated_at: new Date().toISOString() };
      setSessions((previous) => previous.map((session) => (
        session.id === id
          ? { ...session, title: updated.title || title, updatedAt: formatSessionTime(updated.updated_at) }
          : session
      )));
    } catch (error: any) {
      setSessionError(error?.message || '重命名会话失败');
    }
  };

  const handleArchiveSession = async (id: string, archived: boolean) => {
    try {
      const updated = id.startsWith('conv_')
        ? await archiveAIConversation(id, archived)
        : { status: archived ? 'archived' as const : 'active' as const, updated_at: new Date().toISOString() };
      setSessions((previous) => previous.map((session) => (
        session.id === id
          ? { ...session, status: updated.status, updatedAt: formatSessionTime(updated.updated_at) }
          : session
      )));
      if (archived && activeSessionId === id) {
        const replacement = sessions.find((session) => session.id !== id && session.status !== 'archived');
        if (replacement) setActiveSessionId(replacement.id);
        else await createAndSelectSession();
      }
    } catch (error: any) {
      setSessionError(error?.message || '归档会话失败');
    }
  };

  const handleDeleteSession = async (id: string) => {
    try {
      if (id.startsWith('conv_')) await deleteAIConversation(id);
      loadedSessionIdsRef.current.delete(id);
      const updated = sessions.filter((session) => session.id !== id);
      setSessions(updated);
      if (activeSessionId === id) {
        const replacement = updated.find((session) => session.status !== 'archived');
        if (replacement) setActiveSessionId(replacement.id);
        else await createAndSelectSession();
      }
    } catch (error: any) {
      setSessionError(error?.message || '删除会话失败');
    }
  };

  const handleClearMessages = async () => {
    if (!activeSessionId) return;
    try {
      if (activeSessionId.startsWith('conv_')) await clearAIConversation(activeSessionId);
      setSessions((previous) => previous.map((session) => (
        session.id === activeSessionId ? { ...session, messages: [], updatedAt: formatSessionTime(new Date().toISOString()) } : session
      )));
    } catch (error: any) {
      setSessionError(error?.message || '清空会话失败');
    }
  };

  const handleSend = async (userMsg: string) => {
    if (!userMsg.trim() || loading || !activeSession) return;

    const conversationId = activeSession.id.startsWith('conv_') ? activeSession.id : undefined;
    if (conversationId && activeSession.status === 'archived') {
      try {
        await archiveAIConversation(conversationId, false);
        setSessions((previous) => previous.map((session) => (
          session.id === conversationId ? { ...session, status: 'active' } : session
        )));
      } catch (error: any) {
        setSessionError(error?.message || '归档会话恢复失败');
        return;
      }
    }

    const nowTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const isFirstMsg = messages.length === 0;
    const newTitle = isFirstMsg ? (userMsg.length > 16 ? userMsg.slice(0, 16) + '...' : userMsg) : activeSession.title;

    if (conversationId && isFirstMsg) {
      void renameAIConversation(conversationId, newTitle).catch((error) => {
        console.warn('Failed to update conversation title:', error);
      });
    }

    const userMessageObj: ChatMessage = {
      id: 'msg_' + Date.now(),
      role: 'user',
      content: userMsg,
      created_at: nowTime,
    };

    const assistantMsgId = 'msg_ast_' + (Date.now() + 1);
    const assistantMessageObj: ChatMessage = {
      id: assistantMsgId,
      role: 'assistant',
      content: '',
      created_at: nowTime,
      processing_steps: [],
    };

    const updatedMessages = [...messages, userMessageObj, assistantMessageObj];

    setSessions((prev) =>
      prev.map((s) => {
        if (s.id === activeSessionId) {
          return {
            ...s,
            title: newTitle,
            updatedAt: nowTime,
            messages: updatedMessages,
          };
        }
        return s;
      })
    );

    setLoading(true);
    const startTime = Date.now();
    requestStartedAtRef.current = startTime;
    setStreamingMessageId(assistantMsgId);
    setLiveElapsedMs(0);
    let streamDurationMs: number | undefined;

    try {
      const historyPayload = conversationId ? undefined : messages.map((m) => ({ role: m.role, content: m.content }));

      await chatAssistantStream(
        userMsg,
        historyPayload,
        (token) => {
          setSessions((prev) =>
            prev.map((s) => {
              if (s.id === activeSessionId) {
                const msgs = s.messages.map((m) => {
                  if (m.id === assistantMsgId) {
                    return { ...m, content: m.content + token };
                  }
                  return m;
                });
                return { ...s, messages: msgs };
              }
              return s;
            })
          );
        },
        (meta) => {
          setSessions((prev) =>
            prev.map((s) => {
              if (s.id === activeSessionId) {
                const msgs = s.messages.map((m) => {
                  if (m.id === assistantMsgId) {
                    return {
                      ...m,
                      intent: meta.intent,
                      sources: meta.citations,
                      retrieval: meta.retrieval,
                    };
                  }
                  return m;
                });
                return { ...s, messages: msgs };
              }
              return s;
            })
          );
        },
        (step) => {
          setSessions((prev) =>
            prev.map((s) => {
              if (s.id !== activeSessionId) return s;
              const msgs = s.messages.map((m) => {
                if (m.id !== assistantMsgId) return m;
                return {
                  ...m,
                  processing_steps: upsertCopilotProcessStep(m.processing_steps || [], step),
                };
              });
              return { ...s, messages: msgs };
            })
          );
        },
        (done) => {
          if (typeof done.duration_ms === 'number') {
            streamDurationMs = done.duration_ms;
          }
        },
        (streamError) => {
          const message = streamError.code === 'AI_SECURITY_BLOCKED'
            ? 'AI_SECURITY_BLOCKED：请求被安全策略拦截，请减少敏感内容后重试。'
            : `[Copilot 处理失败] ${streamError.message || streamError.code || '服务返回错误'}`;
          setSessions((prev) =>
            prev.map((s) => {
              if (s.id !== activeSessionId) return s;
              return {
                ...s,
                messages: s.messages.map((m) =>
                  m.id === assistantMsgId ? { ...m, content: message } : m
                ),
              };
            })
          );
        },
        conversationId
      );

      const elapsed = streamDurationMs ?? Date.now() - startTime;
      setSessions((prev) =>
        prev.map((s) => {
          if (s.id === activeSessionId) {
            const msgs = s.messages.map((m) => {
              if (m.id === assistantMsgId) {
                const updatedMsg = { ...m, latency_ms: elapsed };
                setActiveInspectorMsg(updatedMsg);
                return updatedMsg;
              }
              return m;
            });
            return { ...s, messages: msgs };
          }
          return s;
        })
      );
    } catch (err: any) {
      const elapsed = streamDurationMs ?? Date.now() - startTime;
      setSessions((prev) =>
        prev.map((s) => {
          if (s.id === activeSessionId) {
            const msgs = s.messages.map((m) => {
              if (m.id === assistantMsgId) {
                return {
                  ...m,
                  content: `[网络或大模型响应失败] ${err.message || '请求超时'}`,
                  latency_ms: elapsed,
                };
              }
              return m;
            });
            return { ...s, messages: msgs };
          }
          return s;
        })
      );
    } finally {
      setLoading(false);
      setStreamingMessageId(null);
      requestStartedAtRef.current = null;
      setLiveElapsedMs(0);
    }
  };

  const handleCopyMessage = async (id: string, text: string) => {
    try {
      const copiedSuccessfully = await copyTextWithFallback(text);
      if (!copiedSuccessfully) return;
      setCopiedId(id);
      window.setTimeout(() => setCopiedId(null), 2000);
    } catch (e) {
      console.error('Copy failed:', e);
    }
  };

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-1 bg-white dark:bg-gray-900 rounded-2xl border border-gray-200/80 dark:border-gray-800 overflow-hidden shadow-xs font-sans">
      {/* ── Left Sidebar (260px) ── */}
      <CopilotSidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        collapsed={compactSidebar}
        showArchived={showArchived}
        onToggleCollapsed={() => setSidebarCollapsed((value) => !value)}
        onToggleArchived={() => setShowArchived((value) => !value)}
        onSelectSession={handleSelectSession}
        onNewSession={handleNewSession}
        onRenameSession={handleRenameSession}
        onArchiveSession={handleArchiveSession}
        onDeleteSession={handleDeleteSession}
      />

      {/* ── Main Chat Workspace Column ── */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-white dark:bg-gray-900 relative">
        {/* Top Header (56px) */}
        <CopilotHeader
          sessionTitle={activeSession?.title || '新对话'}
          selectedModel={selectedModel}
          onSelectModel={setSelectedModel}
          models={availableModels}
          onClearChat={handleClearMessages}
          onToggleInspector={() => setIsInspectorOpen(!isInspectorOpen)}
          isInspectorOpen={isInspectorOpen}
        />

        {sessionError && (
          <div className="mx-4 mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700 flex items-center justify-between gap-3">
            <span>{sessionError}</span>
            <button type="button" onClick={() => setSessionError(null)} className="text-amber-600 hover:text-amber-900">关闭</button>
          </div>
        )}

        {/* Center Scrollable Chat List (Max-width 820px) */}
        <div ref={messagesContainerRef} className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          {messages.length === 0 ? (
            <CopilotEmptyState onSelectPrompt={handleSend} />
          ) : (
            <div className="max-w-[820px] mx-auto w-full px-4 py-8 space-y-8">
              {messages.map((m) => {
                if (m.role === 'user') {
                  return (
                    <div key={m.id} className="flex justify-end select-text">
                      <div className="max-w-[78%] bg-[#f4f4f5] dark:bg-gray-800 text-gray-900 dark:text-gray-100 rounded-[20px] rounded-tr-none px-4 py-3 shadow-xs font-sans text-sm leading-relaxed">
                        <p className="whitespace-pre-wrap">{m.content}</p>
                      </div>
                    </div>
                  );
                }

                // Assistant Message (No Card Box, Pure Document-like Experience)
                return (
                  <div key={m.id} className="space-y-3 select-text">
                    {/* Assistant Title Header */}
                    <div className="flex items-center justify-between select-none">
                      <div className="flex items-center gap-2">
                        <div className="w-6 h-6 rounded-full bg-indigo-600 flex items-center justify-center text-white shadow-xs">
                          <Sparkles className="w-3.5 h-3.5" />
                        </div>
                        <span className="font-bold text-gray-900 dark:text-white text-sm tracking-tight">
                          Nexora AI
                        </span>
                      </div>
                    </div>

                    {/* Content Rendered via MarkdownRenderer */}
                    <div className="text-gray-800 dark:text-gray-100 pl-1">
                      <MarkdownRenderer content={m.content || (loading ? '...' : '')} />
                    </div>

                    {/* Source References Pill & Popover (Tier 2) */}
                    {m.sources && m.sources.length > 0 && (() => {
                      const sourceList = m.sources as CitationSource[];
                      const uniqueSources = Array.from(new Map(sourceList.map((s) => [s.document + s.section, s])).values());
                      const isExpanded = expandedSourcesId === m.id;
                      return (
                        <div className="pt-1 select-none">
                          <button
                            onClick={() => setExpandedSourcesId(isExpanded ? null : m.id)}
                            className="inline-flex items-center gap-1.5 px-3 py-1 bg-indigo-50/70 dark:bg-indigo-950/40 hover:bg-indigo-100 dark:hover:bg-indigo-900/60 text-indigo-700 dark:text-indigo-300 rounded-full text-xs font-medium border border-indigo-200/60 dark:border-indigo-800/60 transition cursor-pointer"
                          >
                            <BookOpen className="w-3.5 h-3.5" />
                            <span>已参考 {uniqueSources.length} 个 Nexora 知识库来源</span>
                            <span className="text-[10px] opacity-70 ml-0.5">{isExpanded ? '▲ 收起' : '▼ 展开'}</span>
                          </button>

                          {isExpanded && (
                            <div className="mt-2 p-3 bg-gray-50 dark:bg-gray-800/60 rounded-xl border border-gray-200/70 dark:border-gray-700 text-xs space-y-1.5 max-w-md shadow-xs transition-all">
                              <div className="font-semibold text-gray-800 dark:text-gray-200 mb-1 flex items-center justify-between">
                                <span>参考文档清单</span>
                                <span className="text-[10px] text-gray-400 font-normal">点击任意条目可查全篇</span>
                              </div>
                              {uniqueSources.map((src, sIdx) => (
                                <div key={sIdx} className="flex items-center justify-between p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700/50 text-gray-700 dark:text-gray-300">
                                  <span className="font-medium truncate">{src.document}</span>
                                  <span className="text-[11px] text-gray-400 font-mono flex-shrink-0 ml-2">{src.section}</span>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      );
                    })()}

                    {(() => {
                      const processSteps = (m.processing_steps || []) as AssistantProcessStep[];
                      const isStreaming = streamingMessageId === m.id;
                      if (!isStreaming && m.latency_ms === undefined && processSteps.length === 0) return null;
                      return (
                        <AssistantProcessPanel
                          steps={processSteps}
                          expanded={expandedProcessId === m.id}
                          onToggle={() => setExpandedProcessId(expandedProcessId === m.id ? null : m.id)}
                          isStreaming={isStreaming}
                          elapsedMs={liveElapsedMs}
                          latencyMs={m.latency_ms}
                        />
                      );
                    })()}

                    {/* Assistant Action Bar (Copy, Like, Regenerate, Inspector Toggle) */}
                    <div className="flex items-center gap-3 pt-1 text-gray-400 select-none text-xs">
                      <button
                        onClick={() => handleCopyMessage(m.id, m.content)}
                        className="hover:text-gray-700 dark:hover:text-gray-200 flex items-center gap-1 p-1 transition"
                        title="复制全文"
                      >
                        {copiedId === m.id ? (
                          <Check className="w-3.5 h-3.5 text-emerald-500" />
                        ) : (
                          <Copy className="w-3.5 h-3.5" />
                        )}
                      </button>

                      <button
                        onClick={() => alert('感谢您的反馈！')}
                        className="hover:text-emerald-600 p-1 transition"
                        title="好评"
                      >
                        <ThumbsUp className="w-3.5 h-3.5" />
                      </button>

                      <button
                        onClick={() => alert('感谢您的意见，已提交优化记录。')}
                        className="hover:text-red-500 p-1 transition"
                        title="差评"
                      >
                        <ThumbsDown className="w-3.5 h-3.5" />
                      </button>

                      <button
                        onClick={() => {
                          setActiveInspectorMsg(m);
                          setIsInspectorOpen(true);
                        }}
                        className="hover:text-indigo-500 flex items-center gap-1 p-1 transition ml-auto"
                        title="查看技术调试 Trace"
                      >
                        <SlidersHorizontal className="w-3.5 h-3.5" />
                        <span className="text-[11px]">调试 Trace</span>
                      </button>
                    </div>
                  </div>
                );
              })}

              {loading && (
                <div className="flex gap-2 items-center text-xs text-indigo-500 font-medium p-2 select-none">
                  <div className="w-4 h-4 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
                  AI 正在思考中...
                </div>
              )}
            </div>
          )}
        </div>

        {/* Bottom ChatGPT Composer (Fixed at bottom) */}
        <CopilotComposer
          onSend={handleSend}
          selectedModel={selectedModel}
          onSelectModel={setSelectedModel}
          models={availableModels}
          disabled={loading || sessionLoadingId === activeSessionId || !activeSession}
        />
      </div>

      {/* ── Right Inspector Drawer (360px) ── */}
      <CopilotInspectorDrawer
        isOpen={isInspectorOpen}
        onClose={() => setIsInspectorOpen(false)}
        activeMessage={activeInspectorMsg}
      />
    </div>
  );
};

export default AssistantTab;
