import React, { useState, useRef, useEffect } from 'react';
import { ArrowUp, Plus, MapPin, Sliders, AlertTriangle, BookOpen, ChevronDown, ChevronRight, Check, RotateCcw, Sparkles, Cpu, Zap, Square } from 'lucide-react';

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
}) => {
  const [input, setInput] = useState('');
  const [showQuickMenu, setShowQuickMenu] = useState(false);
  const [showModelPopover, setShowModelPopover] = useState(false);
  const [activeSubPanel, setActiveSubPanel] = useState<'main' | 'models' | 'reasoning' | 'speed'>('main');
  const [reasoningLevel, setReasoningLevel] = useState<'normal' | 'high'>('high');
  const [speedLevel, setSpeedLevel] = useState<'fast' | 'precise' | 'creative'>('fast');
  const [showContext, setShowContext] = useState(false);
  const [isEditing, setIsEditing] = useState(false);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
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
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setShowModelPopover(false);
        setActiveSubPanel('main');
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

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!input.trim() || disabled) return;
    onSend(input.trim());
    setInput('');
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
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const quickCommands = [
    { label: '/ip 定位目标 IP', icon: <MapPin className="w-3.5 h-3.5 text-emerald-500" />, prompt: '192.168.10.20 在哪台交换机？' },
    { label: '/config 生成配置', icon: <Sliders className="w-3.5 h-3.5 text-indigo-500" />, prompt: '生成一份华为 S6800 OSPF 配置' },
    { label: '/troubleshoot 故障排查', icon: <AlertTriangle className="w-3.5 h-3.5 text-amber-500" />, prompt: 'OSPF 邻居状态 ExStart 如何排查？' },
    { label: '/knowledge 检索 SOP', icon: <BookOpen className="w-3.5 h-3.5 text-blue-500" />, prompt: '查询本地 SOP 手册' },
  ];

  // Fallback default DeepSeek models if DB list is empty
  const defaultModels: CopilotModelOption[] = [
    { id: 'm0', name: 'DeepSeek V4 Flash (默认极速)', model_code: 'deepseek-v4-flash', provider_name: 'DeepSeek' },
    { id: 'm0pro', name: 'DeepSeek V4 Pro (专业旗舰)', model_code: 'deepseek-v4-pro', provider_name: 'DeepSeek' },
  ];

  const effectiveModels = models.length > 0 ? models : defaultModels;
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
    <div className="relative max-w-[820px] mx-auto w-full shrink-0 px-3 sm:px-4 pb-3 sm:pb-4 pt-1 font-sans">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] text-gray-500 dark:text-gray-400">
        <button type="button" onClick={() => setShowContext((value) => !value)} className="rounded-full border border-gray-200 dark:border-gray-700 px-2.5 py-1 hover:border-indigo-300 hover:text-indigo-600" aria-expanded={showContext}>
          {showContext ? '收起诊断范围' : '选择诊断范围'}
        </button>
        {context.device_id && <span className="rounded-full bg-indigo-50 dark:bg-indigo-950/40 px-2 py-1">设备 {String(context.device_id)}</span>}
        {context.interface && <span className="rounded-full bg-indigo-50 dark:bg-indigo-950/40 px-2 py-1">接口 {String(context.interface)}</span>}
        {attachmentNotice && <span className="rounded-full bg-amber-50 dark:bg-amber-950/30 px-2 py-1 text-amber-700 dark:text-amber-300">{attachmentNotice}</span>}
      </div>
      {showContext && (
        <div className="mb-2 grid grid-cols-1 gap-2 rounded-xl border border-gray-200 bg-white/90 p-2 text-xs dark:border-gray-700 dark:bg-gray-900/90 sm:grid-cols-2">
          {([
            ['device_id', '设备 ID'], ['interface', '接口'], ['site_id', 'Site'], ['time_range', '时间范围'], ['vendor', '厂商'], ['platform', '平台'],
          ] as Array<[string, string]>).map(([key, label]) => (
            <label key={key} className="flex items-center gap-1.5 text-gray-500 dark:text-gray-400">
              <span className="w-14 shrink-0">{label}</span>
              <input value={String(context[key] || '')} onChange={(event) => updateContext(key, event.target.value)} className="min-w-0 flex-1 rounded border border-gray-200 dark:border-gray-700 bg-transparent px-2 py-1 text-gray-800 dark:text-gray-200" aria-label={label} />
            </label>
          ))}
          <label className="flex items-center gap-2 text-gray-500 dark:text-gray-400 sm:col-span-2">
            <span>附件预检</span>
            <input type="file" accept=".txt,.md,.log,.html" onChange={(event) => {
              const file = event.target.files?.[0];
              if (!file || !onAttachmentText) return;
              const reader = new FileReader();
              reader.onload = () => onAttachmentText(String(reader.result || ''));
              reader.readAsText(file);
            }} className="min-w-0 text-[11px]" aria-label="选择附件进行安全预检" />
          </label>
        </div>
      )}
      {/* Quick Menu Popover */}
      {showQuickMenu && (
        <div className="absolute bottom-full left-2 z-20 mb-2 w-64 max-w-[calc(100vw-1rem)] space-y-1 rounded-2xl border border-gray-200 bg-white p-2 text-xs shadow-xl dark:border-gray-700 dark:bg-gray-800 sm:left-4">
          <div className="px-2 py-1 text-[10px] font-semibold text-gray-400 uppercase">快捷指令</div>
          {quickCommands.map((cmd, idx) => (
            <button
              key={idx}
              type="button"
              onClick={() => {
                setInput(cmd.prompt);
                setShowQuickMenu(false);
                textareaRef.current?.focus();
              }}
              className="flex min-h-10 w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-xs text-gray-700 transition hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 dark:text-gray-200 dark:hover:bg-gray-700"
            >
              {cmd.icon}
              <span className="truncate">{cmd.label}</span>
            </button>
          ))}
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

      {/* Input Box Container (ChatGPT Style 24px Pill/Rounded Container) */}
      <form
        onSubmit={handleSubmit}
        className="flex flex-wrap items-end gap-2 rounded-2xl border border-gray-300/60 bg-[#f4f4f5] px-3.5 py-2.5 shadow-xs transition focus-within:border-indigo-500 focus-within:ring-1 focus-within:ring-indigo-500/20 dark:border-gray-700 dark:bg-gray-800/90 sm:flex-nowrap sm:rounded-[24px]"
      >
        {/* Quick Menu Toggle Button */}
        <button
          ref={quickMenuTriggerRef}
          type="button"
          onClick={() => setShowQuickMenu(!showQuickMenu)}
          aria-expanded={showQuickMenu}
          className="order-2 mb-0.5 inline-flex min-h-10 min-w-10 flex-shrink-0 items-center justify-center rounded-full p-2 text-gray-500 transition hover:bg-gray-200/60 hover:text-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 dark:text-gray-400 dark:hover:bg-gray-700 dark:hover:text-white sm:order-none"
          title="打开快捷指令"
        >
          <Plus className="w-4 h-4" />
        </button>

        {/* Text Area Input */}
        <textarea
          ref={textareaRef}
          rows={1}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="询问 Nexora AI，或输入 / 使用快捷指令..."
          className="order-1 min-h-10 min-w-0 basis-full resize-none border-none bg-transparent py-1.5 font-sans text-sm leading-relaxed text-gray-900 placeholder-gray-400 focus:outline-none dark:text-gray-100 sm:order-none sm:min-h-[28px] sm:basis-auto sm:flex-1"
        />

        {/* Model & Inference Selector Pill (Matching Image 1 Trigger Style) */}
        <div className="order-3 mb-0.5 min-w-0 flex-shrink sm:order-none">
          <button
            ref={modelPopoverTriggerRef}
            type="button"
            onClick={() => {
              setShowModelPopover(!showModelPopover);
              setActiveSubPanel('main');
            }}
            aria-expanded={showModelPopover}
            className="inline-flex min-h-10 max-w-full items-center gap-1.5 rounded-xl border border-gray-300/80 bg-white/90 px-3 text-xs font-semibold text-gray-700 shadow-2xs transition hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700/90 dark:text-gray-200 dark:hover:bg-gray-700"
            title="点击展开模型与推理控制面板"
          >
            <Zap className="w-3 h-3 text-amber-500 fill-amber-500" />
            <span className="max-w-[7rem] truncate sm:max-w-[12rem]">{currentModelObj?.name?.split(' ')[0] || 'DeepSeek V4'} {reasoningLevel === 'high' ? '最高' : ''}</span>
            <ChevronDown className="w-3 h-3 text-gray-400 ml-0.5" />
          </button>
        </div>

        {/* Circular Send Button */}
        <button
          type={isStreaming ? 'button' : 'submit'}
          onClick={isStreaming ? onStop : undefined}
          disabled={isStreaming ? !onStop : disabled || !input.trim()}
          className="order-4 mb-0.5 inline-flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-indigo-600 text-white shadow-xs transition hover:bg-indigo-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-gray-300 dark:disabled:bg-gray-700 sm:order-none"
          title={isStreaming ? '停止生成' : '发送'}
          aria-label={isStreaming ? '停止生成' : '发送'}
        >
          {isStreaming ? <Square className="w-3.5 h-3.5 fill-current" /> : <ArrowUp className="w-4 h-4" />}
        </button>
      </form>

      {/* Disclaimer Subtitle */}
      <div className="text-[11px] text-center text-gray-400 dark:text-gray-500 mt-2 select-none">
        AI 生成内容可能存在错误，请在生产环境验证配置命令。
      </div>
    </div>
  );
};

export default CopilotComposer;
