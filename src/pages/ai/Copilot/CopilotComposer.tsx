import React, { useState, useRef, useEffect, useMemo } from 'react';
import { ArrowUp, Plus, MapPin, Sliders, AlertTriangle, BookOpen, ChevronDown, ChevronRight, Check, RotateCcw, Globe, Cpu, Zap, Square, Paperclip, FileText, X, Network, Bell } from 'lucide-react';
import type { CopilotToolDefinition, ParsedCopilotAttachment } from '../../../api/ai';

export interface CopilotModelOption {
  id: string;
  name: string;
  model_code: string;
  provider_name: string;
  model_type?: string;
  context_length?: number;
  health_status?: string;
  stream_supported?: boolean;
}

const getModelHealthLabel = (status?: string) => {
  switch (String(status || 'unknown').toLowerCase()) {
    case 'healthy': return '健康';
    case 'unhealthy': return '异常';
    case 'disabled': return '未启用';
    case 'not_supported': return '不适用';
    default: return '未检查';
  }
};

interface CopilotComposerProps {
  onSend: (message: string) => void;
  selectedModel?: string;
  onSelectModel?: (model: string) => void;
  models?: CopilotModelOption[];
  disabled?: boolean;
  context?: Record<string, unknown>;
  onContextChange?: (context: Record<string, unknown>) => void;
  attachmentNotice?: string | null;
  onAttachmentText?: (text: string) => void;
  editDraft?: string | null;
  onEditDraftConsumed?: () => void;
  onStop?: () => void;
  isStreaming?: boolean;
  tools?: CopilotToolDefinition[];
  onUploadFile?: (file: File) => Promise<ParsedCopilotAttachment>;
}

export const CopilotComposer: React.FC<CopilotComposerProps> = ({
  onSend,
  selectedModel = 'deepseek-v4-flash',
  onSelectModel,
  models = [],
  disabled,
  context = {},
  onContextChange,
  attachmentNotice,
  onAttachmentText,
  editDraft,
  onEditDraftConsumed,
  onStop,
  isStreaming = false,
  tools = [],
  onUploadFile,
}) => {
  const [input, setInput] = useState('');
  const [showQuickMenu, setShowQuickMenu] = useState(false);
  const [activeQuickIndex, setActiveQuickIndex] = useState(0);
  const [showModelPopover, setShowModelPopover] = useState(false);
  const [activeSubPanel, setActiveSubPanel] = useState<'main' | 'models' | 'reasoning' | 'speed'>('main');
  const [reasoningLevel, setReasoningLevel] = useState<'normal' | 'high'>('high');
  const [speedLevel, setSpeedLevel] = useState<'fast' | 'precise' | 'creative'>('fast');
  const [isEditing, setIsEditing] = useState(false);
  const [attachedFiles, setAttachedFiles] = useState<ParsedCopilotAttachment[]>([]);
  const [uploadingFile, setUploadingFile] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const webSearchEnabled = Boolean(context?.web_search);
  const toggleWebSearch = () => {
    onContextChange?.({ ...context, web_search: !webSearchEnabled });
  };

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const quickMenuRef = useRef<HTMLDivElement>(null);
  const quickMenuTriggerRef = useRef<HTMLButtonElement>(null);
  const modelPopoverTriggerRef = useRef<HTMLButtonElement>(null);
  const modelSectionTriggerRef = useRef<HTMLButtonElement>(null);
  const reasoningSectionTriggerRef = useRef<HTMLButtonElement>(null);
  const speedSectionTriggerRef = useRef<HTMLButtonElement>(null);

  // Auto resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`;
    }
  }, [input]);

  useEffect(() => {
    if (editDraft === null || editDraft === undefined) return;
    setInput(editDraft);
    setIsEditing(true);
    onEditDraftConsumed?.();
    textareaRef.current?.focus();
  }, [editDraft, onEditDraftConsumed]);

  // Click outside to close popovers
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        popoverRef.current &&
        !popoverRef.current.contains(target) &&
        !modelPopoverTriggerRef.current?.contains(target)
      ) {
        setShowModelPopover(false);
        setActiveSubPanel('main');
      }
      if (
        quickMenuRef.current &&
        !quickMenuRef.current.contains(target) &&
        !quickMenuTriggerRef.current?.contains(target)
      ) {
        setShowQuickMenu(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (showModelPopover) {
        event.preventDefault();
        setShowModelPopover(false);
        setActiveSubPanel('main');
        window.requestAnimationFrame(() => modelPopoverTriggerRef.current?.focus());
      } else if (showQuickMenu) {
        event.preventDefault();
        setShowQuickMenu(false);
        window.requestAnimationFrame(() => quickMenuTriggerRef.current?.focus());
      }
    };
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [showModelPopover, showQuickMenu]);

  const getToolIcon = (cmd: string, category?: string) => {
    if (cmd === '/ip') return <MapPin className="w-3.5 h-3.5 text-emerald-500 shrink-0" />;
    if (cmd === '/mac') return <Cpu className="w-3.5 h-3.5 text-cyan-500 shrink-0" />;
    if (cmd === '/neighbors' || category === 'topology') return <Network className="w-3.5 h-3.5 text-violet-500 shrink-0" />;
    if (cmd === '/alarms' || category === 'monitoring') return <Bell className="w-3.5 h-3.5 text-rose-500 shrink-0" />;
    if (cmd === '/config') return <Sliders className="w-3.5 h-3.5 text-indigo-500 shrink-0" />;
    if (cmd === '/troubleshoot') return <AlertTriangle className="w-3.5 h-3.5 text-amber-500 shrink-0" />;
    if (cmd === '/sop' || category === 'knowledge') return <BookOpen className="w-3.5 h-3.5 text-blue-500 shrink-0" />;
    if (cmd === '/web' || category === 'web') return <Globe className="w-3.5 h-3.5 text-sky-500 shrink-0" />;
    return <Zap className="w-3.5 h-3.5 text-indigo-500 shrink-0" />;
  };

  const quickCommands = useMemo(() => {
    if (tools.length > 0) {
      return tools.map((t) => ({
        cmd: t.cmd,
        label: t.label,
        hint: t.hint,
        enableWeb: Boolean(t.enable_web),
        icon: getToolIcon(t.cmd, t.category),
        expand: (args: string) => {
          const cleanArgs = args.trim();
          if (t.prompt_template && t.prompt_template.includes('{args}')) {
            return cleanArgs
              ? t.prompt_template.replace('{args}', cleanArgs)
              : t.prompt_template.replace('{args}', '').replace(/[:：]\s*$/, '').trim() || t.title;
          }
          return cleanArgs ? `${t.title}：${cleanArgs}` : t.title;
        },
      }));
    }
    return [
      {
        cmd: '/ip',
        label: '/ip 定位目标 IP',
        hint: '/ip 10.0.0.1',
        icon: <MapPin className="w-3.5 h-3.5 text-emerald-500 shrink-0" />,
        expand: (args: string) => (args ? `${args} 在哪台交换机哪个端口？` : '192.168.10.20 在哪台交换机哪个端口？'),
      },
      {
        cmd: '/mac',
        label: '/mac 定位 MAC 地址',
        hint: '/mac aa:bb:cc:dd:ee:ff',
        icon: <Cpu className="w-3.5 h-3.5 text-cyan-500 shrink-0" />,
        expand: (args: string) => (args ? `查询 MAC 地址 ${args} 所在交换机和端口` : '查询 MAC 地址所在交换机和端口'),
      },
      {
        cmd: '/config',
        label: '/config 生成设备配置',
        hint: '/config 华为 S6800 OSPF',
        icon: <Sliders className="w-3.5 h-3.5 text-indigo-500 shrink-0" />,
        expand: (args: string) => (args ? `请生成配置：${args}` : '生成一份华为 S6800 OSPF 配置'),
      },
      {
        cmd: '/troubleshoot',
        label: '/troubleshoot 故障排查',
        hint: '/troubleshoot OSPF ExStart',
        icon: <AlertTriangle className="w-3.5 h-3.5 text-amber-500 shrink-0" />,
        expand: (args: string) => (args ? `排查网络故障：${args}` : 'OSPF 邻居状态 ExStart 如何排查？'),
      },
      {
        cmd: '/sop',
        label: '/sop 检索本地 SOP',
        hint: '/sop 变更规范',
        icon: <BookOpen className="w-3.5 h-3.5 text-blue-500 shrink-0" />,
        expand: (args: string) => (args ? `检索本地知识库 SOP：${args}` : '查询本地 SOP 手册'),
      },
      {
        cmd: '/web',
        label: '/web 联网实时查询',
        hint: '/web 今天武汉天气',
        icon: <Globe className="w-3.5 h-3.5 text-sky-500 shrink-0" />,
        enableWeb: true,
        expand: (args: string) => (args || '查查今天武汉的天气'),
      },
    ];
  }, [tools]);

  const isSlashTyping = input.startsWith('/') && !input.includes(' ');
  const slashQuery = isSlashTyping ? input.trim().toLowerCase() : '';
  const filteredQuickCommands = useMemo(() => {
    if (!slashQuery) return quickCommands;
    return quickCommands.filter((item) => item.cmd.startsWith(slashQuery) || item.label.toLowerCase().includes(slashQuery));
  }, [quickCommands, slashQuery]);

  const isQuickMenuOpen = showQuickMenu || (isSlashTyping && filteredQuickCommands.length > 0);

  useEffect(() => {
    setActiveQuickIndex(0);
  }, [slashQuery, showQuickMenu]);

  const selectQuickCommand = (item: (typeof quickCommands)[number]) => {
    if (item.enableWeb && !webSearchEnabled) {
      onContextChange?.({ ...context, web_search: true });
    }
    setInput(`${item.cmd} `);
    setShowQuickMenu(false);
    textareaRef.current?.focus();
  };

  const expandSlashInput = (raw: string): string => {
    const trimmed = raw.trim();
    if (!trimmed.startsWith('/')) return trimmed;
    const match = /^(\/[a-zA-Z]+)(?:\s+([\s\S]*))?$/.exec(trimmed);
    if (!match) return trimmed;
    const cmdKey = match[1].toLowerCase();
    const args = (match[2] || '').trim();
    const found = quickCommands.find((item) => item.cmd === cmdKey);
    if (!found) return trimmed;
    if (found.enableWeb && !webSearchEnabled) {
      onContextChange?.({ ...context, web_search: true });
    }
    return found.expand(args);
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file || !onUploadFile) return;
    setUploadError(null);
    setUploadingFile(true);
    try {
      const parsed = await onUploadFile(file);
      setAttachedFiles((prev) => [...prev.filter((item) => item.filename !== parsed.filename), parsed]);
    } catch (err: any) {
      setUploadError(err?.message || '文件解析失败，请确认格式为 Word / Excel / PDF / 文本');
    } finally {
      setUploadingFile(false);
    }
  };

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if ((!input.trim() && attachedFiles.length === 0) || disabled || uploadingFile) return;
    const expanded = input.trim() ? expandSlashInput(input) : '请分析以上上传的文档内容并给出核心要点。';
    const attachmentBlock = attachedFiles.length > 0
      ? attachedFiles
          .map((item) => `【附件：${item.filename}】\n${item.text}`)
          .join('\n\n') + '\n\n'
      : '';
    onSend(`${attachmentBlock}${expanded}`);
    setInput('');
    setAttachedFiles([]);
    setUploadError(null);
    setShowQuickMenu(false);
    setIsEditing(false);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleCancelEdit = () => {
    setInput('');
    setIsEditing(false);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.focus();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (isQuickMenuOpen && filteredQuickCommands.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setActiveQuickIndex((prev) => (prev + 1) % filteredQuickCommands.length);
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setActiveQuickIndex((prev) => (prev - 1 + filteredQuickCommands.length) % filteredQuickCommands.length);
        return;
      }
      if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey && isSlashTyping)) {
        e.preventDefault();
        const chosen = filteredQuickCommands[activeQuickIndex] || filteredQuickCommands[0];
        if (chosen) selectQuickCommand(chosen);
        return;
      }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  // Only models that really exist.  The former hard-coded DeepSeek fallback
  // showed options (id "m0") that the server does not know, so picking one
  // sent an unknown model id; with no configured model the server default is
  // used and the picker says so.
  const effectiveModels = models;
  const currentModelObj = effectiveModels.find((m) => m.id === selectedModel) || effectiveModels[0];

  // Group models by provider
  const groupedModels = effectiveModels.reduce((acc, m) => {
    const pName = m.provider_name || 'AI 供应商';
    if (!acc[pName]) acc[pName] = [];
    acc[pName].push(m);
    return acc;
  }, {} as Record<string, CopilotModelOption[]>);

  const resetDefaults = () => {
    if (effectiveModels.length > 0 && onSelectModel) {
      onSelectModel(effectiveModels[0].id);
    }
    setReasoningLevel('high');
    setSpeedLevel('fast');
    setActiveSubPanel('main');
  };

  const updateContext = (key: string, value: string) => {
    onContextChange?.({ ...context, [key]: value || undefined });
  };

  return (
    <div className="relative max-w-3xl mx-auto w-full shrink-0 px-3 sm:px-4 pb-4 pt-1 font-sans">
      {(attachmentNotice || uploadError || attachedFiles.length > 0) && (
        <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] text-gray-500 dark:text-gray-400">
          {attachedFiles.map((file) => (
            <span
              key={file.filename}
              className="inline-flex items-center gap-1.5 rounded-full border border-indigo-200 bg-indigo-50/80 px-2.5 py-1 text-indigo-700 dark:border-indigo-800 dark:bg-indigo-950/40 dark:text-indigo-300"
            >
              <FileText className="w-3 h-3 shrink-0" />
              <span className="max-w-[180px] truncate font-medium">{file.filename}</span>
              <span className="text-[10px] opacity-75">{file.char_count} 字</span>
              <button
                type="button"
                onClick={() => setAttachedFiles((prev) => prev.filter((item) => item.filename !== file.filename))}
                className="ml-0.5 rounded-full p-0.5 hover:bg-indigo-200/60 dark:hover:bg-indigo-900/60"
                title="移除附件"
                aria-label={`移除附件 ${file.filename}`}
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
          {uploadError && (
            <span className="rounded-full bg-rose-50 dark:bg-rose-950/30 px-2.5 py-1 text-rose-700 dark:text-rose-300">{uploadError}</span>
          )}
          {attachmentNotice && (
            <span className="rounded-full bg-amber-50 dark:bg-amber-950/30 px-2.5 py-1 text-amber-700 dark:text-amber-300">{attachmentNotice}</span>
          )}
        </div>
      )}
      {/* Quick Menu & Inline Slash-Command Popover */}
      {isQuickMenuOpen && (
        <div
          ref={quickMenuRef}
          role="listbox"
          aria-label="快捷指令列表"
          className="absolute bottom-full left-3 z-20 mb-2 w-80 max-w-[calc(100vw-1rem)] space-y-1 rounded-2xl border border-gray-200/80 bg-white p-2 text-xs shadow-xl dark:border-gray-700 dark:bg-gray-800 sm:left-4 sm:w-96"
        >
          <div className="flex items-center justify-between px-2 py-1 text-[10px] font-semibold text-gray-400">
            <span>快捷指令</span>
            <span className="font-normal">↑↓ 选择 · Tab/Enter 填入</span>
          </div>
          {filteredQuickCommands.map((cmd, idx) => {
            const isActive = idx === activeQuickIndex;
            return (
              <button
                key={cmd.cmd}
                type="button"
                role="option"
                aria-selected={isActive}
                onMouseEnter={() => setActiveQuickIndex(idx)}
                onClick={() => selectQuickCommand(cmd)}
                className={`flex min-h-9 w-full items-center justify-between gap-2 rounded-xl px-2.5 py-1.5 text-left text-xs transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                  isActive
                    ? 'bg-indigo-50 text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-200'
                    : 'text-gray-700 hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-gray-700'
                }`}
              >
                <span className="flex min-w-0 items-center gap-2">
                  {cmd.icon}
                  <span className="truncate font-medium">{cmd.label}</span>
                </span>
                <span className="shrink-0 text-[10px] text-gray-400 dark:text-gray-500">{cmd.hint}</span>
              </button>
            );
          })}
        </div>
      )}

      {/* Model & Inference Setting Popover (Matching Image 1 Exact Style) */}
      {showModelPopover && (
        <div ref={popoverRef} className="absolute bottom-full right-2 z-30 mb-3 flex max-w-[calc(100vw-1rem)] flex-col-reverse items-end gap-2 animate-fadeIn sm:right-14 sm:flex-row">
          {/* Sub-Panel 2: Model Picker Panel */}
          {activeSubPanel === 'models' && (
            <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl p-2 shadow-2xl w-64 space-y-1 text-xs select-none">
              <div className="px-3 py-1.5 text-[11px] font-bold text-gray-500 dark:text-gray-400 border-b border-gray-100 dark:border-gray-700/60 flex items-center justify-between">
                <span>选择 AI 模型</span>
                <span className="text-[10px] text-indigo-500">已用 {effectiveModels.length} 个模型</span>
              </div>

              <div className="max-h-60 overflow-y-auto space-y-2 pt-1">
                {Object.entries(groupedModels).map(([pName, mList]) => (
                  <div key={pName} className="space-y-1">
                    <div className="px-2.5 text-[10px] font-bold text-indigo-600 dark:text-indigo-400 uppercase">
                      {pName} 供应商
                    </div>
                    {mList.map((m) => {
                      const isSelected = m.id === selectedModel;
                      return (
                        <button
                          key={m.id}
                          onClick={() => {
                            if (onSelectModel) onSelectModel(m.id);
                            setActiveSubPanel('main');
                            window.requestAnimationFrame(() => modelSectionTriggerRef.current?.focus());
                          }}
                          type="button"
                          aria-pressed={isSelected}
                          className={`flex min-h-10 w-full items-center justify-between rounded-xl border px-3 py-2 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                            isSelected
                              ? 'border-indigo-200 bg-indigo-50 font-semibold text-indigo-700 dark:border-indigo-800 dark:bg-indigo-950/60 dark:text-indigo-300'
                              : 'border-transparent text-gray-700 hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-gray-700/60'
                          }`}
                        >
                          <span className="min-w-0 truncate"><span>{m.name}</span><span className="ml-1 text-[10px] text-gray-400">{m.model_type || 'chat'} · {m.context_length ? `${Math.round(m.context_length / 1000)}k` : 'ctx'} · {getModelHealthLabel(m.health_status)}</span></span>
                          {isSelected && <Check className="w-3.5 h-3.5 text-indigo-600 dark:text-indigo-400 flex-shrink-0" />}
                        </button>
                      );
                    })}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Sub-Panel 3: Reasoning Panel */}
          {activeSubPanel === 'reasoning' && (
            <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl p-2 shadow-2xl w-48 space-y-1 text-xs select-none">
              <div className="px-3 py-1.5 text-[11px] font-bold text-gray-500 border-b border-gray-100 dark:border-gray-700/60">
                推理强度
              </div>
              <button
                onClick={() => { setReasoningLevel('high'); setActiveSubPanel('main'); window.requestAnimationFrame(() => reasoningSectionTriggerRef.current?.focus()); }}
                type="button"
                aria-pressed={reasoningLevel === 'high'}
                className={`flex min-h-10 w-full items-center justify-between rounded-xl border px-3 py-2 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                  reasoningLevel === 'high' ? 'border-indigo-200 bg-indigo-50 font-semibold text-indigo-700 dark:border-indigo-800 dark:bg-indigo-950/60 dark:text-indigo-300' : 'border-transparent text-gray-700 hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-gray-700'
                }`}
              >
                <span>最高 (深度思考 R1)</span>
                {reasoningLevel === 'high' && <Check className="w-3.5 h-3.5" />}
              </button>
              <button
                onClick={() => { setReasoningLevel('normal'); setActiveSubPanel('main'); window.requestAnimationFrame(() => reasoningSectionTriggerRef.current?.focus()); }}
                type="button"
                aria-pressed={reasoningLevel === 'normal'}
                className={`flex min-h-10 w-full items-center justify-between rounded-xl border px-3 py-2 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                  reasoningLevel === 'normal' ? 'border-indigo-200 bg-indigo-50 font-semibold text-indigo-700 dark:border-indigo-800 dark:bg-indigo-950/60 dark:text-indigo-300' : 'border-transparent text-gray-700 hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-gray-700'
                }`}
              >
                <span>常规</span>
                {reasoningLevel === 'normal' && <Check className="w-3.5 h-3.5" />}
              </button>
            </div>
          )}

          {/* Sub-Panel 4: Speed Panel */}
          {activeSubPanel === 'speed' && (
            <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl p-2 shadow-2xl w-48 space-y-1 text-xs select-none">
              <div className="px-3 py-1.5 text-[11px] font-bold text-gray-500 border-b border-gray-100 dark:border-gray-700/60">
                响应速度 / 风格
              </div>
              <button
                onClick={() => { setSpeedLevel('fast'); setActiveSubPanel('main'); window.requestAnimationFrame(() => speedSectionTriggerRef.current?.focus()); }}
                type="button"
                aria-pressed={speedLevel === 'fast'}
                className={`flex min-h-10 w-full items-center justify-between rounded-xl border px-3 py-2 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                  speedLevel === 'fast' ? 'border-indigo-200 bg-indigo-50 font-semibold text-indigo-700 dark:border-indigo-800 dark:bg-indigo-950/60 dark:text-indigo-300' : 'border-transparent text-gray-700 hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-gray-700'
                }`}
              >
                <span>快速 (平衡 0.7)</span>
                {speedLevel === 'fast' && <Check className="w-3.5 h-3.5" />}
              </button>
              <button
                onClick={() => { setSpeedLevel('precise'); setActiveSubPanel('main'); window.requestAnimationFrame(() => speedSectionTriggerRef.current?.focus()); }}
                type="button"
                aria-pressed={speedLevel === 'precise'}
                className={`flex min-h-10 w-full items-center justify-between rounded-xl border px-3 py-2 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                  speedLevel === 'precise' ? 'border-indigo-200 bg-indigo-50 font-semibold text-indigo-700 dark:border-indigo-800 dark:bg-indigo-950/60 dark:text-indigo-300' : 'border-transparent text-gray-700 hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-gray-700'
                }`}
              >
                <span>精确 (严谨 0.2)</span>
                {speedLevel === 'precise' && <Check className="w-3.5 h-3.5" />}
              </button>
            </div>
          )}

          {/* Sub-Panel 1: Main Control Panel (Exact Match of Image 1 Right Panel) */}
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl p-2 shadow-2xl w-56 space-y-1 text-xs select-none">
            {/* Item 1: Model Selector Entry */}
            <button
              ref={modelSectionTriggerRef}
              onClick={() => setActiveSubPanel(activeSubPanel === 'models' ? 'main' : 'models')}
              type="button"
              aria-expanded={activeSubPanel === 'models'}
              className={`flex min-h-10 w-full items-center justify-between rounded-xl px-3 py-2.5 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                activeSubPanel === 'models'
                  ? 'bg-gray-100 dark:bg-gray-700 font-semibold text-gray-900 dark:text-white'
                  : 'text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700/70'
              }`}
            >
              <span className="font-medium text-gray-700 dark:text-gray-300">模型</span>
              <div className="flex items-center gap-1 text-gray-500">
                <span className="truncate max-w-[90px] text-right font-medium">{currentModelObj?.name?.split(' ')[0] || selectedModel}</span>
                <ChevronRight className="w-3.5 h-3.5 text-gray-400" />
              </div>
            </button>

            {/* Item 2: Reasoning Effort Entry */}
            <button
              ref={reasoningSectionTriggerRef}
              onClick={() => setActiveSubPanel(activeSubPanel === 'reasoning' ? 'main' : 'reasoning')}
              type="button"
              aria-expanded={activeSubPanel === 'reasoning'}
              className={`flex min-h-10 w-full items-center justify-between rounded-xl px-3 py-2.5 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                activeSubPanel === 'reasoning'
                  ? 'bg-gray-100 dark:bg-gray-700 font-semibold text-gray-900 dark:text-white'
                  : 'text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700/70'
              }`}
            >
              <span className="font-medium text-gray-700 dark:text-gray-300">推理强度</span>
              <div className="flex items-center gap-1 text-gray-500">
                <span>{reasoningLevel === 'high' ? '最高' : '常规'}</span>
                <ChevronRight className="w-3.5 h-3.5 text-gray-400" />
              </div>
            </button>

            {/* Item 3: Speed Entry */}
            <button
              ref={speedSectionTriggerRef}
              onClick={() => setActiveSubPanel(activeSubPanel === 'speed' ? 'main' : 'speed')}
              type="button"
              aria-expanded={activeSubPanel === 'speed'}
              className={`flex min-h-10 w-full items-center justify-between rounded-xl px-3 py-2.5 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                activeSubPanel === 'speed'
                  ? 'bg-gray-100 dark:bg-gray-700 font-semibold text-gray-900 dark:text-white'
                  : 'text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700/70'
              }`}
            >
              <span className="font-medium text-gray-700 dark:text-gray-300">速度</span>
              <div className="flex items-center gap-1 text-gray-500">
                <span>{speedLevel === 'fast' ? '快速' : speedLevel === 'precise' ? '精确' : '创意'}</span>
                <ChevronRight className="w-3.5 h-3.5 text-gray-400" />
              </div>
            </button>

            <div className="border-t border-gray-100 dark:border-gray-700 my-1 pt-1" />

            {/* Item 4: Reset Defaults */}
            <button
              onClick={resetDefaults}
              type="button"
              className="flex min-h-10 w-full items-center justify-between rounded-xl px-3 py-2 text-gray-500 transition hover:bg-gray-100 hover:text-gray-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 dark:text-gray-400 dark:hover:bg-gray-700 dark:hover:text-gray-200"
            >
              <span>重置为默认设置</span>
              <RotateCcw className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}

      {isEditing && (
        <div className="mb-2 flex items-center justify-between gap-3 rounded-xl border border-indigo-200 bg-indigo-50/80 px-3 py-2 text-xs text-indigo-700 dark:border-indigo-900/60 dark:bg-indigo-950/30 dark:text-indigo-300">
          <span>正在编辑问题，修改后点击发送即可提交新问题</span>
          <button type="button" onClick={handleCancelEdit} className="shrink-0 rounded-md px-2 py-1 text-[11px] font-medium hover:bg-indigo-100 dark:hover:bg-indigo-900/50">
            取消编辑
          </button>
        </div>
      )}

      {/* Input Box Container (Gemini Style Two-Row Rounded Card) */}
      <form
        onSubmit={handleSubmit}
        className="flex flex-col rounded-3xl border border-gray-200/90 bg-white px-4 pt-3 pb-2.5 shadow-[0_2px_12px_rgba(15,23,42,0.06)] transition-all focus-within:border-gray-300 focus-within:shadow-[0_4px_20px_rgba(15,23,42,0.09)] dark:border-gray-700/80 dark:bg-gray-800/95 dark:focus-within:border-gray-600"
      >
        {/* Top Row: Full-Width Text Area */}
        <textarea
          ref={textareaRef}
          rows={1}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="询问 Nexora AI，或输入 / 使用快捷指令..."
          className="min-h-[36px] w-full resize-none border-none bg-transparent px-1 py-1 font-sans text-[15px] leading-relaxed text-gray-900 placeholder-gray-400 focus:outline-none dark:text-gray-100 dark:placeholder-gray-500"
        />

        {/* Bottom Row: Left Tools + Right Model & Send */}
        <div className="mt-1.5 flex items-center justify-between gap-2">
          <div className="flex items-center gap-1">
            {/* Quick Menu Toggle Button */}
            <button
              ref={quickMenuTriggerRef}
              type="button"
              onClick={() => setShowQuickMenu(!showQuickMenu)}
              aria-expanded={showQuickMenu}
              className="inline-flex h-8 w-8 items-center justify-center rounded-full text-gray-500 transition hover:bg-gray-100 hover:text-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 dark:text-gray-400 dark:hover:bg-gray-700 dark:hover:text-white"
              title="打开快捷指令"
            >
              <Plus className="w-4 h-4" />
            </button>

            {/* Local Document Upload Button (Word / Excel / PDF / Text) */}
            {onUploadFile && (
              <>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".docx,.xlsx,.pdf,.txt,.md,.csv,.log,.json"
                  onChange={(e) => void handleFileChange(e)}
                  className="hidden"
                />
                <button
                  type="button"
                  disabled={uploadingFile || disabled}
                  onClick={() => fileInputRef.current?.click()}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-full text-gray-500 transition hover:bg-gray-100 hover:text-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:opacity-50 dark:text-gray-400 dark:hover:bg-gray-700 dark:hover:text-white"
                  title="上传本地文档（支持 Word / Excel / PDF / 文本）"
                  aria-label="上传本地文档"
                >
                  <Paperclip className={`w-4 h-4 ${uploadingFile ? 'animate-pulse text-indigo-500' : ''}`} />
                </button>
              </>
            )}

            {/* Web Search Toggle Pill */}
            <button
              type="button"
              onClick={toggleWebSearch}
              aria-pressed={webSearchEnabled}
              className={`inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                webSearchEnabled
                  ? 'bg-blue-50 text-blue-600 hover:bg-blue-100/80 dark:bg-blue-950/60 dark:text-blue-300'
                  : 'text-gray-500 hover:bg-gray-100 hover:text-gray-800 dark:text-gray-400 dark:hover:bg-gray-700 dark:hover:text-gray-200'
              }`}
              title={webSearchEnabled ? '已开启联网查询（点击关闭）' : '开启联网查询公开实时信息'}
            >
              <Globe className="w-3.5 h-3.5" />
              <span>联网</span>
            </button>
          </div>

          <div className="flex items-center gap-2">
            {/* Model & Inference Selector Ghost Pill */}
            <button
              ref={modelPopoverTriggerRef}
              type="button"
              onClick={() => {
                setShowModelPopover(!showModelPopover);
                setActiveSubPanel('main');
              }}
              aria-expanded={showModelPopover}
              className="inline-flex h-8 max-w-[11rem] items-center gap-1.5 rounded-full px-2.5 text-xs font-medium text-gray-600 transition hover:bg-gray-100 hover:text-gray-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 dark:text-gray-300 dark:hover:bg-gray-700 dark:hover:text-white sm:max-w-[14rem]"
              title="点击展开模型与推理控制面板"
            >
              <Zap className="w-3.5 h-3.5 shrink-0 text-amber-500 fill-amber-500" />
              <span className="truncate">{currentModelObj?.name?.split(' ')[0] || '默认模型'}{reasoningLevel === 'high' ? ' · 深度' : ''}</span>
              <ChevronDown className="w-3.5 h-3.5 shrink-0 text-gray-400" />
            </button>

            {/* Circular Send Button */}
            <button
              type={isStreaming ? 'button' : 'submit'}
              onClick={isStreaming ? onStop : undefined}
              disabled={isStreaming ? !onStop : disabled || !input.trim()}
              className="inline-flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-gray-900 text-white transition hover:bg-gray-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-gray-200 disabled:text-gray-400 dark:bg-white dark:text-gray-900 dark:hover:bg-gray-200 dark:disabled:bg-gray-700 dark:disabled:text-gray-500"
              title={isStreaming ? '停止生成' : '发送'}
              aria-label={isStreaming ? '停止生成' : '发送'}
            >
              {isStreaming ? <Square className="w-3 h-3 fill-current" /> : <ArrowUp className="w-4 h-4" />}
            </button>
          </div>
        </div>
      </form>

      {/* Disclaimer Subtitle */}
      <div className="text-[11px] text-center text-gray-400 dark:text-gray-500 mt-2 select-none">
        AI 生成内容可能存在错误，请在生产环境验证配置命令。
      </div>
    </div>
  );
};

export default CopilotComposer;
