import React, { useState, useEffect, useRef } from 'react';
import { Sparkles, BookOpen, ThumbsUp, ThumbsDown, Copy, SlidersHorizontal, Check, Clock3, ChevronDown, ChevronUp, ListChecks, Loader2, CheckCircle2, AlertCircle, ExternalLink, AlertTriangle, Terminal, RotateCcw, Pencil, Play } from 'lucide-react';
import {
  AIConversationMessage,
  AIExecutionMode,
  AITokenSource,
  AssistantProcessStep,
  AssistantRetrievalTrace,
  CopilotContract,
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
  submitCopilotFeedback,
  checkCopilotAttachment,
  createCopilotCase,
  handoffCopilotCase,
  createDiagnosticPlan,
  runDiagnosticPlan,
} from '../../../api/ai';
import { MarkdownRenderer } from '../../../components/MarkdownRenderer';
import { copyTextWithFallback } from '../../../utils/clipboard';
import { cloneSelectionWithin, hasTextSelection, restoreSelection } from './selectionUtils';
import { CopilotSidebar, ChatSession } from './CopilotSidebar';
import { CopilotHeader } from './CopilotHeader';
import { CopilotEmptyState } from './CopilotEmptyState';
import { CopilotComposer, CopilotModelOption } from './CopilotComposer';
import { CopilotInspectorDrawer } from './CopilotInspectorDrawer';
import { formatCopilotDuration, upsertCopilotProcessStep } from './progress';
import { ActionButton, ActionIconButton, ActionIconGroup } from '../../../components/ui/ActionIconButton';

interface CopilotSelectionSnapshot {
  range: Range;
  messageRoot: Element;
}

interface CitationSource {
  citation_id?: string;
  document: string;
  document_id?: string;
  section?: string;
  vendor?: string;
  product?: string;
  os_family?: string;
  software_version?: string;
  document_version?: string;
  url?: string;
  chunk_id?: string;
  source_type?: string;
  status?: string;
  trust?: string;
  validation?: string;
  updated_at?: string;
  claim_ids?: string[];
  warnings?: string[];
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
  input_tokens?: number;
  output_tokens?: number;
  route_model?: string;
  provider_id?: string;
  route_reason?: string;
  execution_mode?: AIExecutionMode;
  external_egress?: boolean | null;
  token_source?: AITokenSource | null;
  processing_steps?: AssistantProcessStep[];
  copilot?: CopilotContract;
  feedback?: 'positive' | 'negative';
  stream_status?: 'streaming' | 'completed' | 'aborted' | 'error';
}

const LEGACY_STORAGE_KEY = 'nexora_copilot_sessions_v4';
const SIDEBAR_COLLAPSED_KEY = 'nexora_copilot_sidebar_collapsed_v1';
const ARCHIVED_VIEW_KEY = 'nexora_copilot_archived_view_v1';
const FEEDBACK_REASONS: Array<{ code: string; label: string }> = [
  { code: 'model_wrong', label: '型号错' },
  { code: 'version_wrong', label: '版本错' },
  { code: 'command_wrong', label: '命令错' },
  { code: 'insufficient_evidence', label: '证据不足' },
  { code: 'stale', label: '内容过时' },
  { code: 'irrelevant', label: '内容无关' },
];

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
  // requested_model_id is only the user's selection, not evidence that the
  // provider was called. Only display the durable actual route here.
  route_model: message.actual_model_id,
  provider_id: message.provider_id,
  route_reason: message.route_reason,
  execution_mode: message.execution_mode,
  external_egress: message.external_egress,
  input_tokens: typeof message.input_tokens === 'number' ? message.input_tokens : undefined,
  output_tokens: typeof message.output_tokens === 'number' ? message.output_tokens : undefined,
  latency_ms: typeof message.latency_ms === 'number' ? message.latency_ms : undefined,
  token_source: message.token_source,
  sources: Array.isArray(message.citations)
    ? message.citations.map((item: any) => ({
      citation_id: String(item?.citation_id || ''),
      document: String(item?.document || item?.document_name || 'Nexora'),
      document_id: item?.document_id ? String(item.document_id) : undefined,
      section: item?.section ? String(item.section) : undefined,
      vendor: item?.vendor ? String(item.vendor) : undefined,
      product: item?.product ? String(item.product) : undefined,
      os_family: item?.os_family ? String(item.os_family) : undefined,
      software_version: item?.software_version ? String(item.software_version) : undefined,
      document_version: item?.document_version ? String(item.document_version) : undefined,
      url: item?.url ? String(item.url) : undefined,
      chunk_id: item?.chunk_id ? String(item.chunk_id) : undefined,
      source_type: item?.source_type ? String(item.source_type) : undefined,
      status: item?.status ? String(item.status) : undefined,
      trust: item?.trust ? String(item.trust) : undefined,
      validation: item?.validation ? String(item.validation) : undefined,
      updated_at: item?.updated_at ? String(item.updated_at) : undefined,
      claim_ids: Array.isArray(item?.claim_ids) ? item.claim_ids.map(String) : undefined,
      warnings: Array.isArray(item?.warnings) ? item.warnings.map(String) : undefined,
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
    : `耗时 ${formatCopilotDuration(latencyMs || 0).replace('已处理 ', '')}`;

  return (
    <div className="pt-1 space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="inline-flex items-center gap-1.5 text-gray-500 dark:text-gray-400">
          <Clock3 className="w-3.5 h-3.5" />
          {durationLabel}
        </span>
        {steps.length > 0 && (
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={expanded}
            aria-label={`${expanded ? '收起' : '展开'}处理过程，共 ${steps.length} 步`}
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
        <div className="max-w-2xl rounded-xl border border-gray-200/80 dark:border-gray-700 bg-gray-50/80 dark:bg-gray-800/50 p-2.5 space-y-1.5 select-text">
          {steps.map((step) => (
            <div key={step.id} className="rounded-lg border border-gray-200/80 dark:border-gray-700/80 bg-white/80 dark:bg-gray-900/60 px-3 py-2.5 text-xs">
              <div className="flex items-start gap-2.5">
                <div className="mt-0.5 shrink-0">
                {step.status === 'running' ? (
                  <Loader2 className="w-3.5 h-3.5 text-indigo-500 animate-spin" />
                ) : step.status === 'error' ? (
                  <AlertCircle className="w-3.5 h-3.5 text-rose-500" />
                ) : step.command ? (
                  <Terminal className="w-3.5 h-3.5 text-slate-500 dark:text-slate-400" />
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
                  {step.detail && <div className="mt-1 text-gray-500 dark:text-gray-400">{step.detail}</div>}
                  {step.operation && (
                    <div className="mt-1.5 flex min-w-0 items-start gap-2">
                      <span className="shrink-0 text-[10px] text-gray-400 dark:text-gray-500">调用</span>
                      <code className="min-w-0 break-all rounded bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 text-[10px] text-gray-500 dark:text-gray-400 select-text">
                        {step.operation}
                      </code>
                    </div>
                  )}
                  {step.command && (
                    <div className="mt-1.5 flex min-w-0 items-start gap-2">
                      <span className="shrink-0 text-[10px] text-gray-400 dark:text-gray-500">命令</span>
                      <pre className="min-w-0 flex-1 overflow-x-auto whitespace-pre-wrap break-words rounded bg-gray-900 px-2 py-1.5 text-[10px] leading-relaxed text-gray-200 select-text">
                        {step.command}
                      </pre>
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}
          <div className="border-t border-gray-200/80 dark:border-gray-700 px-1 pt-2 text-[11px] text-gray-400 dark:text-gray-500 select-text">
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
  const [selectedModel, setSelectedModel] = useState('');
  const [availableModels, setAvailableModels] = useState<CopilotModelOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [sessionLoadingId, setSessionLoadingId] = useState<string | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === 'true');
  const [showArchived, setShowArchived] = useState(() => localStorage.getItem(ARCHIVED_VIEW_KEY) === 'true');
  const [isInspectorOpen, setIsInspectorOpen] = useState(false);
  const [activeInspectorMsg, setActiveInspectorMsg] = useState<ChatMessage | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [copyFailedId, setCopyFailedId] = useState<string | null>(null);
  const [selectedText, setSelectedText] = useState<{ messageId: string; text: string } | null>(null);
  const [expandedSourcesId, setExpandedSourcesId] = useState<string | null>(null);
  const [expandedProcessId, setExpandedProcessId] = useState<string | null>(null);
  const [streamingMessageId, setStreamingMessageId] = useState<string | null>(null);
  const [liveElapsedMs, setLiveElapsedMs] = useState(0);
  const [copilotContext, setCopilotContext] = useState<Record<string, unknown>>({});
  const [feedbackMessageId, setFeedbackMessageId] = useState<string | null>(null);
  const [feedbackReasonMessageId, setFeedbackReasonMessageId] = useState<string | null>(null);
  const [feedbackNotice, setFeedbackNotice] = useState<string | null>(null);
  const [attachmentNotice, setAttachmentNotice] = useState<string | null>(null);
  const [caseNotice, setCaseNotice] = useState<string | null>(null);
  const [diagnosticPlan, setDiagnosticPlan] = useState<any | null>(null);
  const [authorizedDiagnosticSteps, setAuthorizedDiagnosticSteps] = useState<number[]>([]);
  const [diagnosticNotice, setDiagnosticNotice] = useState<string | null>(null);
  const [caseId, setCaseId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<string | null>(null);

  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const requestStartedAtRef = useRef<number | null>(null);
  const loadedSessionIdsRef = useRef<Set<string>>(new Set());
  const abortControllerRef = useRef<AbortController | null>(null);
  const selectionBeforeContextMenuRef = useRef<CopilotSelectionSnapshot | null>(null);
  const selectedTextRef = useRef<{ messageId: string; text: string } | null>(null);
  const isSelectingTextRef = useRef(false);
  const shouldStickToBottomRef = useRef(true);
  const restoringSelectionRef = useRef(false);

  const activeSession = sessions.find((s) => s.id === activeSessionId);
  const messages = (activeSession?.messages || []) as ChatMessage[];
  // Keep the Copilot session rail under the user's control. Auto-collapsing it
  // at 900px made the conversation list look like an empty white strip in an
  // embedded browser and hid rename/archive actions.
  const compactSidebar = sidebarCollapsed;

  useEffect(() => {
    const rememberSelection = () => {
      if (restoringSelectionRef.current) return;
      const selection = window.getSelection();
      if (!selection || !hasTextSelection(selection)) {
        setSelectedText(null);
        return;
      }

      const anchorElement = selection.anchorNode instanceof Element
        ? selection.anchorNode
        : selection.anchorNode?.parentElement;
      const messageContent = anchorElement?.closest('[data-copilot-message-content]');
      const messageRoot = messageContent?.closest('[data-copilot-message-id]');
      if (!messageContent || !messageRoot || !messageContent.contains(selection.focusNode)) {
        setSelectedText(null);
        return;
      }

      const range = cloneSelectionWithin(selection, messageContent);
      if (range) {
        const text = selection.toString();
        if (!text.trim()) {
          setSelectedText(null);
          return;
        }
        const nextSelectedText = { messageId: messageRoot.getAttribute('data-copilot-message-id') || '', text };
        selectedTextRef.current = nextSelectedText;
        setSelectedText(nextSelectedText);
        selectionBeforeContextMenuRef.current = { range, messageRoot: messageContent };
      }
    };

    const finishTextSelection = () => {
      isSelectingTextRef.current = false;
    };

    const restoreSelectionForContextMenu = (event: MouseEvent) => {
      const target = event.target instanceof Element ? event.target : null;
      const messageRoot = target?.closest('[data-copilot-message-content]');
      const snapshot = selectionBeforeContextMenuRef.current;
      if (!snapshot || !messageRoot || snapshot.messageRoot !== messageRoot) return;

      selectionBeforeContextMenuRef.current = null;
      restoringSelectionRef.current = true;
      const restoredRange = snapshot.range.cloneRange();
      restoreSelection(restoredRange);
      window.setTimeout(() => {
        restoreSelection(restoredRange);
        restoringSelectionRef.current = false;
        selectionBeforeContextMenuRef.current = null;
      }, 0);
    };

    document.addEventListener('selectionchange', rememberSelection);
    document.addEventListener('contextmenu', restoreSelectionForContextMenu, true);
    window.addEventListener('mouseup', finishTextSelection);
    window.addEventListener('blur', finishTextSelection);
    return () => {
      document.removeEventListener('selectionchange', rememberSelection);
      document.removeEventListener('contextmenu', restoreSelectionForContextMenu, true);
      window.removeEventListener('mouseup', finishTextSelection);
      window.removeEventListener('blur', finishTextSelection);
    };
  }, []);

  const loadSessionMessages = async (sessionId: string) => {
    if (!sessionId.startsWith('conv_') || loadedSessionIdsRef.current.has(sessionId)) return;
    loadedSessionIdsRef.current.add(sessionId);
    setSessionLoadingId(sessionId);
    try {
      const context = await getAIConversation(sessionId);
      if (context.conversation.selected_model_id) {
        setSelectedModel(context.conversation.selected_model_id);
      }
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
            model_type: m.model_type,
            context_length: m.context_length,
            health_status: m.health_status,
            stream_supported: m.stream_supported,
          }));

        if (validModels.length > 0) {
          setAvailableModels(validModels);
          if (!validModels.some((m) => m.id === selectedModel)) {
            setSelectedModel(validModels[0].id);
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
    if (isSelectingTextRef.current || hasTextSelection(window.getSelection())) return;
    if (!shouldStickToBottomRef.current) return;

    // Scroll the message list itself. Calling scrollIntoView here can select
    // the outer Copilot shell as the scroll container and move the sidebar
    // and header out of view in nested flex layouts.
    container.scrollTo({ top: container.scrollHeight, behavior: 'auto' });
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

  const handleStopGeneration = () => {
    abortControllerRef.current?.abort();
  };

  const handleMessageMouseDown = (event: React.MouseEvent<HTMLElement>) => {
    if (event.button === 0) {
      isSelectingTextRef.current = true;
      selectionBeforeContextMenuRef.current = null;
      return;
    }
    if (event.button !== 2) return;

    const messageRoot = event.currentTarget.closest('[data-copilot-message-content]');
    const range = cloneSelectionWithin(window.getSelection(), event.currentTarget);
    if (messageRoot && range) {
      selectionBeforeContextMenuRef.current = { range, messageRoot };
    } else if (!messageRoot || selectionBeforeContextMenuRef.current?.messageRoot !== messageRoot) {
      selectionBeforeContextMenuRef.current = null;
    }
  };

  const handleMessagesScroll = () => {
    const container = messagesContainerRef.current;
    if (!container) return;
    const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    shouldStickToBottomRef.current = distanceFromBottom <= 120;
  };

  const handleEditMessage = (message: ChatMessage) => {
    setEditDraft(message.content);
  };

  const handleResendMessage = (message: ChatMessage) => {
    if (loading) return;
    void handleSend(message.content);
  };

  const handleRetryMessage = (message: ChatMessage) => {
    const index = messages.findIndex((item) => item.id === message.id);
    const previousUser = index >= 0
      ? [...messages.slice(0, index)].reverse().find((item) => item.role === 'user')
      : undefined;
    if (previousUser) handleResendMessage(previousUser);
  };

  const handleContinueMessage = (message: ChatMessage) => {
    const continuation = `请基于上一条回答继续排查：只推进下一项有信息增益的检查，不重复已完成检查；保持只读并说明依据。\n上一条回答：${message.content.slice(0, 6000)}`;
    void handleSend(continuation);
  };

  const handleSend = async (userMsg: string) => {
    if (!userMsg.trim() || loading || !activeSession) return;

    shouldStickToBottomRef.current = true;

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
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    // Stream tokens arrive faster than the display refreshes. Committing one
    // setState per token re-rendered the whole conversation and made text
    // selection and copy feel laggy, so tokens are batched per frame.
    let pendingStreamText = '';
    let streamFlushHandle: number | null = null;
    let streamFlushIsTimeout = false;
    const appendStreamText = (chunk: string) => {
      if (!chunk) return;
      setSessions((prev) =>
        prev.map((s) => {
          if (s.id !== activeSessionId) return s;
          const msgs = s.messages.map((m) => {
            if (m.id === assistantMsgId) {
              return { ...m, content: m.content + chunk, stream_status: 'streaming' as const };
            }
            return m;
          });
          return { ...s, messages: msgs };
        })
      );
    };
    const flushStreamText = () => {
      streamFlushHandle = null;
      const chunk = pendingStreamText;
      pendingStreamText = '';
      appendStreamText(chunk);
    };
    const scheduleStreamFlush = () => {
      if (streamFlushHandle !== null) return;
      if (document.hidden) {
        streamFlushIsTimeout = true;
        streamFlushHandle = window.setTimeout(flushStreamText, 100);
      } else {
        streamFlushIsTimeout = false;
        streamFlushHandle = window.requestAnimationFrame(flushStreamText);
      }
    };
    const finalizeStreamText = (flushRemaining: boolean) => {
      if (streamFlushHandle !== null) {
        if (streamFlushIsTimeout) window.clearTimeout(streamFlushHandle);
        else window.cancelAnimationFrame(streamFlushHandle);
        streamFlushHandle = null;
      }
      const chunk = pendingStreamText;
      pendingStreamText = '';
      if (flushRemaining) appendStreamText(chunk);
    };

    try {
      const historyPayload = conversationId ? undefined : messages.map((m) => ({ role: m.role, content: m.content }));

      await chatAssistantStream(
        userMsg,
        historyPayload,
        (token) => {
          pendingStreamText += token;
          scheduleStreamFlush();
        },
        (meta) => {
          setSessions((prev) =>
            prev.map((s) => {
              if (s.id === activeSessionId) {
                const msgs = s.messages.map((m) => {
                  if (m.id === assistantMsgId) {
                    return {
                      ...m,
                      stream_status: 'streaming',
                      intent: meta.intent || m.intent,
                      sources: meta.citations || m.sources,
                      retrieval: meta.retrieval || m.retrieval,
                      copilot: meta.copilot || m.copilot,
                      route_model: meta.model_id || meta.requested_model_id || meta.copilot?.runtime?.model_id || m.route_model,
                      provider_id: meta.provider_id || meta.copilot?.runtime?.provider_id || m.provider_id,
                      route_reason: meta.route_reason || m.route_reason,
                      execution_mode: meta.execution_mode || meta.copilot?.runtime?.execution_mode || m.execution_mode,
                      external_egress: meta.external_egress ?? meta.copilot?.runtime?.external_egress ?? m.external_egress,
                      token_source: meta.token_source ?? m.token_source,
                      input_tokens: meta.input_tokens ?? m.input_tokens,
                      output_tokens: meta.output_tokens ?? m.output_tokens,
                      latency_ms: meta.latency_ms ?? m.latency_ms,
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
          setSessions((prev) =>
            prev.map((s) => {
              if (s.id !== activeSessionId) return s;
              return {
                ...s,
                messages: s.messages.map((m) => {
                  if (m.id !== assistantMsgId) return m;
                  return {
                    ...m,
                    latency_ms: typeof done.duration_ms === 'number' ? done.duration_ms : m.latency_ms,
                    input_tokens: typeof done.input_tokens === 'number' ? done.input_tokens : m.input_tokens,
                    output_tokens: typeof done.output_tokens === 'number' ? done.output_tokens : m.output_tokens,
                    route_model: done.model_id || m.route_model,
                    provider_id: done.provider_id || m.provider_id,
                    route_reason: done.route_reason || m.route_reason,
                    execution_mode: done.execution_mode || m.execution_mode,
                    external_egress: done.external_egress ?? m.external_egress,
                    token_source: done.token_source ?? m.token_source,
                  };
                }),
              };
            })
          );
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
                  m.id === assistantMsgId ? { ...m, content: message, stream_status: 'error' } : m
                ),
              };
            })
          );
        },
        conversationId,
        selectedModel,
        copilotContext,
        abortController.signal,
        (citationEvent) => {
          const raw = citationEvent.citation as Record<string, unknown>;
          const citation = {
            ...raw,
            document: String(raw.document || raw.document_name || 'Nexora'),
          } as CitationSource;
          setSessions((prev) =>
            prev.map((s) => {
              if (s.id !== activeSessionId) return s;
              return {
                ...s,
                messages: s.messages.map((m) => {
                  if (m.id !== assistantMsgId) return m;
                  const existing = m.sources || [];
                  if (citation.citation_id && existing.some((item) => item.citation_id === citation.citation_id)) return m;
                  return { ...m, sources: [...existing, citation] };
                }),
              };
            }),
          );
        },
      );

      finalizeStreamText(true);
      const elapsed = streamDurationMs ?? Date.now() - startTime;
      setSessions((prev) =>
        prev.map((s) => {
          if (s.id === activeSessionId) {
            const msgs = s.messages.map((m) => {
              if (m.id === assistantMsgId) {
                const updatedMsg = {
                  ...m,
                  latency_ms: m.latency_ms ?? elapsed,
                  stream_status: 'completed' as const,
                };
                setActiveInspectorMsg((current) => current?.id === updatedMsg.id ? updatedMsg : current);
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
      finalizeStreamText(false);
      const elapsed = streamDurationMs ?? Date.now() - startTime;
      const aborted = err?.name === 'AbortError' || abortController.signal.aborted;
      setSessions((prev) =>
        prev.map((s) => {
          if (s.id === activeSessionId) {
            const msgs = s.messages.map((m) => {
              if (m.id === assistantMsgId) {
                return {
                  ...m,
                  content: aborted ? '[已停止生成，可重试、修改问题或继续排查]' : `[网络或大模型响应失败] ${err.message || '请求超时'}`,
                  latency_ms: elapsed,
                  stream_status: aborted ? 'aborted' : 'error',
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
      abortControllerRef.current = null;
      setLoading(false);
      setStreamingMessageId(null);
      requestStartedAtRef.current = null;
      setLiveElapsedMs(0);
    }
  };

  const handleCopyMessage = async (id: string, text: string) => {
    try {
      const copiedSuccessfully = await copyTextWithFallback(text);
      if (!copiedSuccessfully) {
        setCopyFailedId(id);
        window.setTimeout(() => setCopyFailedId((current) => current === id ? null : current), 2500);
        return;
      }
      setCopyFailedId(null);
      setCopiedId(id);
      window.setTimeout(() => setCopiedId(null), 2000);
    } catch (e) {
      console.error('Copy failed:', e);
    }
  };

  const handleFeedback = async (message: ChatMessage, rating: 'positive' | 'negative', reason?: string) => {
    if (!activeSessionId || !activeSessionId.startsWith('conv_')) {
      setFeedbackNotice('请在已保存会话中提交反馈');
      return;
    }
    setFeedbackMessageId(message.id);
    try {
      const reasons = rating === 'negative' ? [reason || 'insufficient_evidence'] : [];
      await submitCopilotFeedback({ conversation_id: activeSessionId, message_id: message.id, rating, reasons });
      setSessions((previous) => previous.map((session) => session.id === activeSessionId
        ? { ...session, messages: session.messages.map((item: any) => item.id === message.id ? { ...item, feedback: rating } : item) }
        : session));
      setFeedbackNotice(rating === 'positive' ? '已记录为有帮助' : '已记录改进原因');
      setFeedbackReasonMessageId(null);
    } catch (error: any) {
      setFeedbackNotice(error?.message || '反馈提交失败');
    } finally {
      setFeedbackMessageId(null);
      window.setTimeout(() => setFeedbackNotice(null), 2500);
    }
  };

  const handleNegativeFeedback = (message: ChatMessage) => {
    setFeedbackReasonMessageId(message.id);
  };

  const handleAttachmentText = async (text: string) => {
    try {
      const result = await checkCopilotAttachment(text);
      setAttachmentNotice(result.decision === 'ALLOW' ? '附件已通过预检' : `附件${result.decision === 'BLOCK' ? '已阻止' : '需脱敏'}：${result.user_message}`);
    } catch (error: any) {
      setAttachmentNotice(error?.message || '附件预检失败，已阻止上传');
    }
  };

  const handleCreateCase = async (message: ChatMessage) => {
    if (!activeSessionId || !activeSessionId.startsWith('conv_')) {
      setCaseNotice('请在已保存会话中生成案例');
      return;
    }
    try {
      const created = await createCopilotCase({
        title: message.content.slice(0, 80) || 'Copilot 故障案例',
        symptom: message.content.slice(0, 2000),
        conversation_id: activeSessionId,
        context: copilotContext,
        plan: message.copilot?.next_checks?.map((purpose) => ({ purpose, status: 'planned', read_only: true })) || [],
      });
      setCaseId(String(created.id));
      setCaseNotice(`故障案例已创建：${created.id}`);
      window.setTimeout(() => setCaseNotice(null), 3000);
    } catch (error: any) {
      setCaseNotice(error?.message || '故障案例创建失败');
    }
  };

  const handleHandoffCase = async (message: ChatMessage) => {
    if (!caseId) return;
    try {
      await handoffCopilotCase(caseId, {
        summary: message.content.slice(0, 2000),
        ticket_draft: `【Nexora Copilot】${message.content.slice(0, 1200)}`,
      });
      setCaseNotice(`案例 ${caseId} 已生成交接草稿`);
    } catch (error: any) {
      setCaseNotice(error?.message || '案例交接失败');
    }
  };

  const handleBuildDiagnosticPlan = async (symptom: string) => {
    const lower = symptom.toLowerCase();
    const playbook = lower.includes('ospf') ? 'ospf' : lower.includes('bgp') ? 'bgp' : lower.includes('cpu') ? 'cpu' : lower.includes('memory') ? 'memory' : lower.includes('丢包') || lower.includes('loss') ? 'packet_loss' : lower.includes('接口') || lower.includes('interface') ? 'interface_down' : 'unreachable';
    try {
      const plan = await createDiagnosticPlan({ symptom, playbook, vendor: String(copilotContext.vendor || ''), platform: String(copilotContext.platform || ''), target: String(copilotContext.device_id || copilotContext.site_id || '未指定目标'), device_id: String(copilotContext.device_id || '') || undefined });
      setDiagnosticPlan(plan);
      setAuthorizedDiagnosticSteps([]);
      setDiagnosticNotice(null);
    } catch (error: any) {
      setDiagnosticNotice(error?.message || '只读检查计划生成失败');
    }
  };

  const handleRunDiagnosticPlan = async () => {
    if (!diagnosticPlan || authorizedDiagnosticSteps.length === 0) {
      setDiagnosticNotice('请先逐步授权至少一项只读检查');
      return;
    }
    try {
      const result = await runDiagnosticPlan({ plan: diagnosticPlan, authorized_steps: authorizedDiagnosticSteps, context: { ...copilotContext, case_id: activeSessionId } });
      setDiagnosticPlan({ ...diagnosticPlan, ...result });
      setDiagnosticNotice('只读诊断已完成，结果已记录');
    } catch (error: any) {
      setDiagnosticNotice(error?.message || '只读诊断执行失败');
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
        />

        {sessionError && (
          <div className="mx-4 mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700 flex items-center justify-between gap-3">
            <span>{sessionError}</span>
            <button type="button" onClick={() => setSessionError(null)} className="text-amber-600 hover:text-amber-900">关闭</button>
          </div>
        )}

        {/* Center Scrollable Chat List (Max-width 820px) */}
        <div ref={messagesContainerRef} onScroll={handleMessagesScroll} className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          {messages.length === 0 ? (
            <CopilotEmptyState onSelectPrompt={handleSend} />
          ) : (
            <div className="max-w-[820px] mx-auto w-full px-4 py-8 space-y-8">
              {messages.map((m) => {
                if (m.role === 'user') {
                  return (
                    <div key={m.id} data-copilot-message-id={m.id} className="flex flex-col items-end gap-1 select-text">
                      <div
                        className="max-w-[78%] cursor-text rounded-[20px] rounded-tr-none bg-[#f4f4f5] px-4 py-3 font-sans text-sm leading-relaxed text-gray-900 selection:bg-indigo-200 selection:text-gray-900 dark:bg-gray-800 dark:text-gray-100 dark:selection:bg-indigo-700/70 dark:selection:text-white"
                        data-copilot-message-content="true"
                        style={{ userSelect: 'text', WebkitUserSelect: 'text' }}
                        onMouseDownCapture={handleMessageMouseDown}
                      >
                        <p className="whitespace-pre-wrap">{m.content}</p>
                      </div>
                      <ActionIconGroup className="text-gray-400 select-none" label="用户消息操作">
                        <ActionIconButton
                          icon={copiedId === m.id ? Check : Copy}
                          label="复制问题"
                          size="xs"
                          variant={copiedId === m.id ? 'success' : 'accent'}
                          onClick={() => void handleCopyMessage(m.id, m.content)}
                          className="dark:text-gray-400 dark:hover:text-white"
                        />
                        <ActionIconButton
                          icon={Pencil}
                          label="编辑并发送问题"
                          size="xs"
                          variant="default"
                          onClick={() => handleEditMessage(m)}
                          disabled={loading}
                          className="dark:text-gray-400 dark:hover:text-white"
                        />
                        <ActionIconButton
                          icon={RotateCcw}
                          label="重新发送问题"
                          size="xs"
                          variant="default"
                          onClick={() => handleResendMessage(m)}
                          disabled={loading}
                          className="dark:text-gray-400 dark:hover:text-white"
                        />
                      </ActionIconGroup>
                    </div>
                  );
                }

                // Assistant Message (No Card Box, Pure Document-like Experience)
                const isMessageStreaming = streamingMessageId === m.id;
                const copilotIntent = String(m.copilot?.intent || '');
                // Consultation/CMDB answers are complete read-only results,
                // not diagnostic plans.  Keep the developer Trace available,
                // but do not surface a generic evidence checklist in the
                // conversation body.
                const showCopilotSummary = Boolean(
                  m.copilot
                  && copilotIntent
                  // Knowledge retrieval is a read-only lookup, not a
                  // diagnostic/change plan.  Its answer already carries the
                  // local-evidence or cloud-reference disclaimer, while the
                  // generic vendor/model/version checklist is noisy here.
                  && !['consultation', 'general_qa', 'chitchat', 'knowledge_retrieval'].includes(copilotIntent),
                );
                const actualModel = m.route_model
                  ? availableModels.find((model) => model.id === m.route_model)
                  : undefined;
                const providerName = actualModel?.provider_name;
                const displayProviderName = providerName?.toLowerCase() === 'deepseek' ? 'DeepSeek' : providerName;
                const actualModelLabel = actualModel
                  ? `${displayProviderName || actualModel.provider_name} · ${actualModel.model_code}`
                  : (m.route_model || undefined);
                const executionLabel = m.execution_mode === 'local_knowledge'
                  ? '本地知识直出'
                  : m.execution_mode === 'local_operation'
                    ? '本地数据计算'
                    : m.execution_mode === 'provider_generated'
                      ? `${displayProviderName || '外部模型'} 生成`
                      : m.execution_mode === 'local_fallback'
                        ? '本地回退回答'
                        : isMessageStreaming
                          ? '执行路径确认中'
                          : '历史消息 · 路由未知';
                const executionBadgeClass = m.execution_mode === 'local_knowledge' || m.execution_mode === 'local_operation'
                  ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300'
                  : m.execution_mode === 'provider_generated'
                    ? 'border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-800 dark:bg-indigo-950/40 dark:text-indigo-300'
                    : m.execution_mode === 'local_fallback'
                      ? 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300'
                      : 'border-gray-200 bg-gray-50 text-gray-600 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300';
                return (
                  <div key={m.id} data-copilot-message-id={m.id} className="space-y-3 select-text">
                    {/* Assistant Title Header */}
                    <div className="flex flex-wrap items-start justify-between gap-2 select-none">
                      <div className="space-y-1.5">
                        <div className="flex flex-wrap items-center gap-2">
                          <div className="w-6 h-6 rounded-full bg-indigo-600 flex items-center justify-center text-white shadow-xs">
                            <Sparkles className="w-3.5 h-3.5" />
                          </div>
                          <span className="font-bold text-gray-900 dark:text-white text-sm tracking-tight">
                            Nexora AI
                          </span>
                          <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${executionBadgeClass}`}>
                            {executionLabel}
                          </span>
                        </div>
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 pl-8 text-[11px] text-gray-500 dark:text-gray-400">
                          <span>{m.external_egress === true ? '已通过安全网关调用外部模型' : m.external_egress === false ? '未发生外部调用' : isMessageStreaming ? '外部调用状态确认中' : '外部调用状态未记录'}</span>
                          {m.execution_mode === 'provider_generated' && actualModelLabel && <span>实际模型：{actualModelLabel}</span>}
                          <span>
                            {typeof m.input_tokens === 'number' && typeof m.output_tokens === 'number'
                              ? m.token_source === 'provider_reported'
                                ? `实际 Token：输入 ${m.input_tokens} / 输出 ${m.output_tokens}`
                                : m.token_source === 'estimated'
                                  ? `Token 估算：输入 ${m.input_tokens} / 输出 ${m.output_tokens}`
                                  : `模型 Token：输入 ${m.input_tokens} / 输出 ${m.output_tokens}`
                              : '模型 Token 未记录'}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Content Rendered via MarkdownRenderer */}
                    <div
                      className="cursor-text pl-1 text-gray-800 select-text selection:bg-indigo-200 selection:text-gray-900 dark:text-gray-100 dark:selection:bg-indigo-700/70 dark:selection:text-white"
                      data-copilot-message-content="true"
                      style={{ userSelect: 'text', WebkitUserSelect: 'text' }}
                    >
                      {isMessageStreaming ? (
                        <div className="whitespace-pre-wrap break-words leading-relaxed select-text">
                          {m.content || '...'}
                        </div>
                      ) : (
                        <MarkdownRenderer content={m.content || (loading ? '...' : '')} />
                      )}
                    </div>

                    {m.copilot && showCopilotSummary && (
                      (m.copilot.required_evidence && m.copilot.required_evidence.length > 0) ||
                      (m.copilot.confirmed_facts && m.copilot.confirmed_facts.length > 0) ||
                      (m.copilot.next_checks && m.copilot.next_checks.length > 0) ||
                      (m.copilot.intent && !['consultation', 'general_qa', 'chitchat', 'knowledge_retrieval'].includes(m.copilot.intent))
                    ) && (
                      <div className="rounded-xl border border-indigo-100 dark:border-indigo-900/60 bg-indigo-50/60 dark:bg-indigo-950/20 p-3 text-xs space-y-2">
                        <div className="flex flex-wrap items-center gap-2 font-semibold text-indigo-700 dark:text-indigo-300">
                          <span>诊断摘要</span>
                          <span className="rounded-full bg-white/80 dark:bg-gray-900/70 px-2 py-0.5">{m.copilot.intent || 'consultation'}</span>
                          <span className="rounded-full bg-white/80 dark:bg-gray-900/70 px-2 py-0.5">风险 {m.copilot.risk || 'low'}</span>
                          <span className="rounded-full bg-white/80 dark:bg-gray-900/70 px-2 py-0.5">置信度 {Math.round((m.copilot.confidence || 0) * 100)}%</span>
                        </div>
                        {m.copilot.confirmed_facts && m.copilot.confirmed_facts.length > 0 && (
                          <div><span className="font-medium text-gray-600 dark:text-gray-300">已确认：</span>{m.copilot.confirmed_facts.join('；')}</div>
                        )}
                        {m.copilot.required_evidence && m.copilot.required_evidence.length > 0 && (
                          <div className="text-amber-700 dark:text-amber-300"><span className="font-medium">待补证据：</span>{m.copilot.required_evidence.join('；')}</div>
                        )}
                        <div className="flex flex-wrap gap-1.5 text-[11px] text-gray-500 dark:text-gray-400">
                          {(m.copilot.source_labels || []).map((label) => <span key={label} className="rounded border border-gray-200 dark:border-gray-700 px-1.5 py-0.5">{label === 'official' ? '官方知识' : label === 'enterprise' ? '企业知识' : label === 'realtime_device' ? '实时设备' : '模型推断'}</span>)}
                          <span className="rounded border border-gray-200 dark:border-gray-700 px-1.5 py-0.5">{m.copilot.runtime?.external_egress ? '已通过安全网关外发' : '未外发'}</span>
                          <span className="rounded border border-gray-200 dark:border-gray-700 px-1.5 py-0.5">{m.copilot.runtime?.cli_executed ? '已执行 CLI' : '未执行 CLI'}</span>
                        </div>
                        {m.copilot.context_budget && (
                          <div className="text-[11px] text-gray-500 dark:text-gray-400">
                            上下文预算 {m.copilot.context_budget.used_chars || 0}/{m.copilot.context_budget.limit_chars || 0} 字符 · {m.copilot.context_budget.truncated ? '已截断并保留结构化摘要' : '未截断'}
                          </div>
                        )}
                        {m.copilot.next_checks && m.copilot.next_checks.length > 0 && (
                          <div><span className="font-medium text-gray-600 dark:text-gray-300">下一步：</span>{m.copilot.next_checks.slice(0, 3).join('；')}</div>
                        )}
                      </div>
                    )}

                    {/* Source References Pill & Popover (Tier 2) */}
                    {m.sources && m.sources.length > 0 && (() => {
                      const sourceList = m.sources as CitationSource[];
                      const uniqueSources = Array.from(new Map(sourceList.map((s) => [s.citation_id || s.document + (s.section || ''), s])).values());
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
                                <div key={src.citation_id || sIdx} className="rounded-lg p-2 hover:bg-gray-100 dark:hover:bg-gray-700/50 text-gray-700 dark:text-gray-300 space-y-1.5">
                                  <div className="flex items-center justify-between gap-2">
                                    {src.url ? (
                                      <a href={src.url} target="_blank" rel="noreferrer" className="font-medium truncate text-indigo-700 dark:text-indigo-300 hover:underline inline-flex items-center gap-1">
                                        <span className="truncate">{src.document}</span><ExternalLink className="w-3 h-3 shrink-0" />
                                      </a>
                                    ) : <span className="font-medium truncate">{src.document}</span>}
                                    <span className="text-[11px] text-gray-400 font-mono flex-shrink-0 ml-2">{src.section || '未标注章节'}</span>
                                  </div>
                                  <div className="flex flex-wrap gap-1 text-[10px] text-gray-500">
                                    {src.source_type && <span className="rounded bg-white dark:bg-gray-900 px-1.5 py-0.5">{src.source_type}</span>}
                                    {src.product && <span className="rounded bg-white dark:bg-gray-900 px-1.5 py-0.5">{src.product}</span>}
                                    {src.os_family && <span className="rounded bg-white dark:bg-gray-900 px-1.5 py-0.5">{src.os_family}</span>}
                                    {src.software_version && <span className="rounded bg-white dark:bg-gray-900 px-1.5 py-0.5">{src.software_version}</span>}
                                    {src.updated_at && <span className="rounded bg-white dark:bg-gray-900 px-1.5 py-0.5">更新 {src.updated_at}</span>}
                                  </div>
                                  {src.warnings && src.warnings.length > 0 && (
                                    <div className="flex items-start gap-1 text-[10px] text-amber-600 dark:text-amber-300"><AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" />{src.warnings.join('、')}</div>
                                  )}
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
                      {selectedText?.messageId === m.id && (
                        <ActionButton
                          type="button"
                          icon={copiedId === `${m.id}:selection` ? Check : Copy}
                          variant={copiedId === `${m.id}:selection` ? 'success' : copyFailedId === `${m.id}:selection` ? 'danger' : 'default'}
                          size="sm"
                          onPointerDown={(event) => event.preventDefault()}
                          onClick={() => {
                            const liveSelection = window.getSelection()?.toString() || '';
                            const savedSelection = selectionBeforeContextMenuRef.current?.range.toString() || '';
                            const cachedSelection = selectedTextRef.current?.messageId === m.id ? selectedTextRef.current.text : '';
                            const textToCopy = liveSelection.trim() ? liveSelection : cachedSelection.trim() ? cachedSelection : savedSelection.trim() ? savedSelection : selectedText.text;
                            void handleCopyMessage(`${m.id}:selection`, textToCopy);
                          }}
                          className="!h-7 !px-2 !text-[11px]"
                        >
                          {copyFailedId === `${m.id}:selection` ? '复制失败' : copiedId === `${m.id}:selection` ? '已复制' : '复制选中'}
                        </ActionButton>
                      )}
                      <ActionButton
                        type="button"
                        icon={copiedId === m.id ? Check : Copy}
                        variant={copiedId === m.id ? 'success' : copyFailedId === m.id ? 'danger' : 'default'}
                        size="sm"
                        onPointerDown={(event) => event.preventDefault()}
                        onClick={() => handleCopyMessage(m.id, m.content)}
                        className="!h-7 !px-2 !text-[11px]"
                      >
                        {copyFailedId === m.id ? '复制失败' : copiedId === m.id ? '已复制' : '复制全文'}
                      </ActionButton>

                      <ActionIconButton icon={RotateCcw} label="重试本次问题" onClick={() => handleRetryMessage(m)} disabled={loading} />
                      <ActionIconButton icon={Pencil} label="编辑并发送上一条问题" onClick={() => {
                        const previousUser = messages.slice(0, messages.findIndex((item) => item.id === m.id)).reverse().find((item) => item.role === 'user');
                        if (previousUser) handleEditMessage(previousUser);
                      }} disabled={loading} />
                      <ActionIconButton icon={Play} label="继续排查" onClick={() => handleContinueMessage(m)} disabled={loading} />

                      <button
                        onClick={() => void handleFeedback(m, 'positive')}
                        disabled={feedbackMessageId === m.id}
                        className={`hover:text-emerald-600 p-1 transition ${m.feedback === 'positive' ? 'text-emerald-600' : ''}`}
                        title="好评（记录到反馈）"
                      >
                        <ThumbsUp className="w-3.5 h-3.5" />
                      </button>

                      <button type="button" onClick={() => void handleCreateCase(m)} className="hover:text-indigo-500 p-1 transition" title="生成故障案例">
                        案例
                      </button>
                      {m.copilot?.intent === 'diagnosis' && (
                        <button type="button" onClick={() => void handleBuildDiagnosticPlan(m.content)} className="hover:text-amber-600 p-1 transition" title="生成只读诊断计划">
                          诊断计划
                        </button>
                      )}

                      <button
                        onClick={() => handleNegativeFeedback(m)}
                        disabled={feedbackMessageId === m.id}
                        className={`hover:text-red-500 p-1 transition ${m.feedback === 'negative' ? 'text-red-500' : ''}`}
                        title="差评（记录改进原因）"
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
                    {feedbackReasonMessageId === m.id && (
                      <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-rose-100 bg-rose-50/70 px-2 py-1.5 text-[11px] text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/20 dark:text-rose-300">
                        <span>请选择差评原因：</span>
                        {FEEDBACK_REASONS.map((reason) => (
                          <button key={reason.code} type="button" onClick={() => void handleFeedback(m, 'negative', reason.code)} className="rounded border border-rose-200 bg-white/80 px-1.5 py-0.5 hover:bg-rose-100 dark:border-rose-900/60 dark:bg-gray-900/50">{reason.label}</button>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}

              {loading && (
                <div className="flex gap-2 items-center text-xs text-indigo-500 font-medium p-2 select-none">
                  <div className="w-4 h-4 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
                  AI 正在思考中...
                </div>
              )}
              {feedbackNotice && <div className="text-center text-xs text-gray-500 dark:text-gray-400">{feedbackNotice}</div>}
              {caseNotice && <div className="flex items-center justify-center gap-2 text-center text-xs text-indigo-500 dark:text-indigo-300"><span>{caseNotice}</span>{caseId && <button type="button" onClick={() => { const lastAssistant = [...messages].reverse().find((item) => item.role === 'assistant'); if (lastAssistant) void handleHandoffCase(lastAssistant); }} className="rounded border border-indigo-200 px-2 py-0.5 hover:bg-indigo-50 dark:border-indigo-800 dark:hover:bg-indigo-950/40">交接草稿</button>}</div>}
            </div>
          )}
        </div>

        {/* Bottom ChatGPT Composer (Fixed at bottom) */}
        {diagnosticPlan && (
          <div className="mx-auto mb-2 w-full max-w-[820px] rounded-xl border border-amber-200 bg-amber-50/70 px-3 py-2 text-xs dark:border-amber-900/60 dark:bg-amber-950/20">
            <div className="flex flex-wrap items-center justify-between gap-2"><span className="font-semibold text-amber-800 dark:text-amber-300">只读诊断计划 · {diagnosticPlan.playbook || 'network'}</span><span className="text-amber-700 dark:text-amber-400">默认不连接设备、不执行写操作</span></div>
            <div className="mt-2 flex flex-wrap gap-2">{(diagnosticPlan.steps || []).map((step: any) => <label key={`${step.step_no}-${step.purpose}`} className="inline-flex items-center gap-1.5 rounded border border-amber-200 bg-white/70 px-2 py-1 dark:border-amber-900/60 dark:bg-gray-900/40"><input type="checkbox" checked={authorizedDiagnosticSteps.includes(step.step_no)} onChange={(event) => setAuthorizedDiagnosticSteps((current) => event.target.checked ? [...new Set([...current, step.step_no])] : current.filter((item) => item !== step.step_no))} />{step.purpose}{step.command ? ` · ${step.command}` : ''}</label>)}</div>
            <div className="mt-2 flex flex-wrap items-center gap-2"><button type="button" onClick={() => void handleRunDiagnosticPlan()} className="rounded-lg bg-amber-600 px-2.5 py-1.5 font-semibold text-white hover:bg-amber-700">执行已授权只读检查</button><button type="button" onClick={() => setDiagnosticPlan(null)} className="rounded-lg border border-amber-200 px-2.5 py-1.5 text-amber-800 dark:border-amber-900/60 dark:text-amber-300">关闭计划</button>{diagnosticNotice && <span className="text-amber-700 dark:text-amber-300">{diagnosticNotice}</span>}</div>
            {diagnosticPlan.conclusion && <div className="mt-2 text-amber-800 dark:text-amber-300">结论：{diagnosticPlan.conclusion}</div>}
          </div>
        )}
        <CopilotComposer
          onSend={handleSend}
          selectedModel={selectedModel}
          onSelectModel={setSelectedModel}
          models={availableModels}
          context={copilotContext}
          onContextChange={setCopilotContext}
          attachmentNotice={attachmentNotice}
          onAttachmentText={handleAttachmentText}
          editDraft={editDraft}
          onEditDraftConsumed={() => setEditDraft(null)}
          onStop={handleStopGeneration}
          isStreaming={loading}
          disabled={loading || sessionLoadingId === activeSessionId || !activeSession}
        />
      </div>

      {/* ── Center Inspector Modal ── */}
      <CopilotInspectorDrawer
        isOpen={isInspectorOpen}
        onClose={() => setIsInspectorOpen(false)}
        activeMessage={activeInspectorMsg}
      />
    </div>
  );
};

export default AssistantTab;
