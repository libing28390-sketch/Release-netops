import React, { useState, useEffect, useRef } from 'react';
import { Sparkles, BookOpen, ThumbsUp, ThumbsDown, Copy, RotateCcw, SlidersHorizontal, Check, User } from 'lucide-react';
import { chatAssistantStream, getAIModels, getAIProviders } from '../../../api/ai';
import { MarkdownRenderer } from '../../../components/MarkdownRenderer';
import { CopilotSidebar, ChatSession } from './CopilotSidebar';
import { CopilotHeader } from './CopilotHeader';
import { CopilotEmptyState } from './CopilotEmptyState';
import { CopilotComposer, CopilotModelOption } from './CopilotComposer';
import { CopilotInspectorDrawer } from './CopilotInspectorDrawer';

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
  created_at: string;
  latency_ms?: number;
}

const STORAGE_KEY = 'nexora_copilot_sessions_v4';

export const AssistantTab: React.FC = () => {
  const [sessions, setSessions] = useState<ChatSession[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) return JSON.parse(saved);
    } catch (e) {
      console.error('Failed to load sessions:', e);
    }
    const initId = 'sess_' + Date.now();
    return [{
      id: initId,
      title: '新对话',
      updatedAt: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      messages: []
    }];
  });

  const [activeSessionId, setActiveSessionId] = useState<string>(() => {
    return sessions[0]?.id || 'sess_' + Date.now();
  });

  const [selectedModel, setSelectedModel] = useState('deepseek-v4-flash');
  const [availableModels, setAvailableModels] = useState<CopilotModelOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [isInspectorOpen, setIsInspectorOpen] = useState(false);
  const [activeInspectorMsg, setActiveInspectorMsg] = useState<ChatMessage | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [expandedSourcesId, setExpandedSourcesId] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const activeSession = sessions.find((s) => s.id === activeSessionId) || sessions[0];
  const messages = activeSession ? activeSession.messages : [];

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
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
    } catch (e) {
      console.error('Failed to save sessions:', e);
    }
  }, [sessions]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const handleNewSession = () => {
    const newId = 'sess_' + Date.now();
    const newSess: ChatSession = {
      id: newId,
      title: '新对话',
      updatedAt: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      messages: []
    };
    setSessions((prev) => [newSess, ...prev]);
    setActiveSessionId(newId);
  };

  const handleDeleteSession = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (sessions.length <= 1) {
      handleClearMessages();
      return;
    }
    const updated = sessions.filter((s) => s.id !== id);
    setSessions(updated);
    if (activeSessionId === id) {
      setActiveSessionId(updated[0].id);
    }
  };

  const handleClearMessages = () => {
    setSessions((prev) =>
      prev.map((s) => (s.id === activeSessionId ? { ...s, messages: [] } : s))
    );
  };

  const handleSend = async (userMsg: string) => {
    if (!userMsg.trim() || loading) return;

    const nowTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const isFirstMsg = messages.length === 0;
    const newTitle = isFirstMsg ? (userMsg.length > 16 ? userMsg.slice(0, 16) + '...' : userMsg) : activeSession.title;

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

    try {
      const historyPayload = messages.map((m) => ({ role: m.role, content: m.content }));

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
                    };
                  }
                  return m;
                });
                return { ...s, messages: msgs };
              }
              return s;
            })
          );
        }
      );

      const elapsed = Date.now() - startTime;
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
      setSessions((prev) =>
        prev.map((s) => {
          if (s.id === activeSessionId) {
            const msgs = s.messages.map((m) => {
              if (m.id === assistantMsgId) {
                return { ...m, content: `[网络或大模型响应失败] ${err.message || '请求超时'}` };
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
    }
  };

  const handleCopyMessage = async (id: string, text: string) => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        const textArea = document.createElement('textarea');
        textArea.value = text;
        textArea.style.position = 'fixed';
        textArea.style.opacity = '0';
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
      }
      setCopiedId(id);
      setTimeout(() => setCopiedId(null), 2000);
    } catch (e) {
      console.error('Copy failed:', e);
    }
  };

  return (
    <div className="flex h-[calc(100vh-140px)] min-h-[660px] bg-white dark:bg-gray-900 rounded-2xl border border-gray-200/80 dark:border-gray-800 overflow-hidden shadow-xs font-sans">
      {/* ── Left Sidebar (260px) ── */}
      <CopilotSidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelectSession={setActiveSessionId}
        onNewSession={handleNewSession}
        onDeleteSession={handleDeleteSession}
      />

      {/* ── Main Chat Workspace Column ── */}
      <div className="flex-1 flex flex-col h-full bg-white dark:bg-gray-900 relative min-w-0">
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

        {/* Center Scrollable Chat List (Max-width 820px) */}
        <div className="flex-1 overflow-y-auto">
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
                      const uniqueSources = Array.from(new Map(m.sources.map(s => [s.document + s.section, s])).values());
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
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* Bottom ChatGPT Composer (Fixed at bottom) */}
        <CopilotComposer
          onSend={handleSend}
          selectedModel={selectedModel}
          onSelectModel={setSelectedModel}
          models={availableModels}
          disabled={loading}
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
