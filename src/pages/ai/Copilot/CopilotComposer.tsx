import React, { useState, useRef, useEffect } from 'react';
import { ArrowUp, Plus, MapPin, Sliders, AlertTriangle, BookOpen, ChevronDown, ChevronRight, Check, RotateCcw, Sparkles, Cpu, Zap } from 'lucide-react';

export interface CopilotModelOption {
  id: string;
  name: string;
  model_code: string;
  provider_name: string;
}

interface CopilotComposerProps {
  onSend: (message: string) => void;
  selectedModel?: string;
  onSelectModel?: (model: string) => void;
  models?: CopilotModelOption[];
  disabled?: boolean;
}

export const CopilotComposer: React.FC<CopilotComposerProps> = ({
  onSend,
  selectedModel = 'deepseek-v4-flash',
  onSelectModel,
  models = [],
  disabled,
}) => {
  const [input, setInput] = useState('');
  const [showQuickMenu, setShowQuickMenu] = useState(false);
  const [showModelPopover, setShowModelPopover] = useState(false);
  const [activeSubPanel, setActiveSubPanel] = useState<'main' | 'models' | 'reasoning' | 'speed'>('main');
  const [reasoningLevel, setReasoningLevel] = useState<'normal' | 'high'>('high');
  const [speedLevel, setSpeedLevel] = useState<'fast' | 'precise' | 'creative'>('fast');

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  // Auto resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`;
    }
  }, [input]);

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

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!input.trim() || disabled) return;
    onSend(input.trim());
    setInput('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
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
  const currentModelObj = effectiveModels.find((m) => m.model_code === selectedModel) || effectiveModels[0];

  // Group models by provider
  const groupedModels = effectiveModels.reduce((acc, m) => {
    const pName = m.provider_name || 'AI 供应商';
    if (!acc[pName]) acc[pName] = [];
    acc[pName].push(m);
    return acc;
  }, {} as Record<string, CopilotModelOption[]>);

  const resetDefaults = () => {
    if (effectiveModels.length > 0 && onSelectModel) {
      onSelectModel(effectiveModels[0].model_code);
    }
    setReasoningLevel('high');
    setSpeedLevel('fast');
    setActiveSubPanel('main');
  };

  return (
    <div className="relative max-w-[820px] mx-auto w-full shrink-0 px-3 sm:px-4 pb-3 sm:pb-4 pt-1 font-sans">
      {/* Quick Menu Popover */}
      {showQuickMenu && (
        <div className="absolute bottom-full mb-2 left-4 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl p-2 shadow-xl z-20 w-64 space-y-1 text-xs">
          <div className="px-2 py-1 text-[10px] font-semibold text-gray-400 uppercase">快捷指令</div>
          {quickCommands.map((cmd, idx) => (
            <button
              key={idx}
              onClick={() => {
                setInput(cmd.prompt);
                setShowQuickMenu(false);
              }}
              className="w-full px-2.5 py-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-xl flex items-center gap-2 text-gray-700 dark:text-gray-200 text-left transition"
            >
              {cmd.icon}
              <span className="truncate">{cmd.label}</span>
            </button>
          ))}
        </div>
      )}

      {/* Model & Inference Setting Popover (Matching Image 1 Exact Style) */}
      {showModelPopover && (
        <div ref={popoverRef} className="absolute bottom-full mb-3 right-14 z-30 flex items-end gap-2 animate-fadeIn">
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
                      const isSelected = m.model_code === selectedModel;
                      return (
                        <button
                          key={m.model_code}
                          onClick={() => {
                            if (onSelectModel) onSelectModel(m.model_code);
                            setActiveSubPanel('main');
                          }}
                          className={`w-full px-3 py-2 rounded-xl text-left flex items-center justify-between transition cursor-pointer ${
                            isSelected
                              ? 'bg-indigo-50 dark:bg-indigo-950/60 font-semibold text-indigo-700 dark:text-indigo-300'
                              : 'text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700/60'
                          }`}
                        >
                          <span className="truncate">{m.name}</span>
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
                onClick={() => { setReasoningLevel('high'); setActiveSubPanel('main'); }}
                className={`w-full px-3 py-2 rounded-xl text-left flex items-center justify-between transition ${
                  reasoningLevel === 'high' ? 'bg-indigo-50 dark:bg-indigo-950/60 text-indigo-700 dark:text-indigo-300 font-semibold' : 'text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700'
                }`}
              >
                <span>最高 (深度思考 R1)</span>
                {reasoningLevel === 'high' && <Check className="w-3.5 h-3.5" />}
              </button>
              <button
                onClick={() => { setReasoningLevel('normal'); setActiveSubPanel('main'); }}
                className={`w-full px-3 py-2 rounded-xl text-left flex items-center justify-between transition ${
                  reasoningLevel === 'normal' ? 'bg-indigo-50 dark:bg-indigo-950/60 text-indigo-700 dark:text-indigo-300 font-semibold' : 'text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700'
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
                onClick={() => { setSpeedLevel('fast'); setActiveSubPanel('main'); }}
                className={`w-full px-3 py-2 rounded-xl text-left flex items-center justify-between transition ${
                  speedLevel === 'fast' ? 'bg-indigo-50 dark:bg-indigo-950/60 text-indigo-700 dark:text-indigo-300 font-semibold' : 'text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700'
                }`}
              >
                <span>快速 (平衡 0.7)</span>
                {speedLevel === 'fast' && <Check className="w-3.5 h-3.5" />}
              </button>
              <button
                onClick={() => { setSpeedLevel('precise'); setActiveSubPanel('main'); }}
                className={`w-full px-3 py-2 rounded-xl text-left flex items-center justify-between transition ${
                  speedLevel === 'precise' ? 'bg-indigo-50 dark:bg-indigo-950/60 text-indigo-700 dark:text-indigo-300 font-semibold' : 'text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700'
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
              onClick={() => setActiveSubPanel(activeSubPanel === 'models' ? 'main' : 'models')}
              className={`w-full px-3 py-2.5 rounded-xl flex items-center justify-between transition cursor-pointer ${
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
              onClick={() => setActiveSubPanel(activeSubPanel === 'reasoning' ? 'main' : 'reasoning')}
              className={`w-full px-3 py-2.5 rounded-xl flex items-center justify-between transition cursor-pointer ${
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
              onClick={() => setActiveSubPanel(activeSubPanel === 'speed' ? 'main' : 'speed')}
              className={`w-full px-3 py-2.5 rounded-xl flex items-center justify-between transition cursor-pointer ${
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
              className="w-full px-3 py-2 rounded-xl text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center justify-between transition cursor-pointer"
            >
              <span>重置为默认设置</span>
              <RotateCcw className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* Input Box Container (ChatGPT Style 24px Pill/Rounded Container) */}
      <form
        onSubmit={handleSubmit}
        className="bg-[#f4f4f5] dark:bg-gray-800/90 border border-gray-300/60 dark:border-gray-700 rounded-[24px] px-3.5 py-2.5 shadow-xs focus-within:border-indigo-500 focus-within:ring-1 focus-within:ring-indigo-500/20 transition flex items-end gap-2"
      >
        {/* Quick Menu Toggle Button */}
        <button
          type="button"
          onClick={() => setShowQuickMenu(!showQuickMenu)}
          className="p-2 rounded-full text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-white hover:bg-gray-200/60 dark:hover:bg-gray-700 transition flex-shrink-0 mb-0.5"
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
          className="flex-1 bg-transparent border-none focus:outline-none text-gray-900 dark:text-gray-100 text-sm placeholder-gray-400 resize-none py-1.5 min-h-[28px] max-h-[180px] leading-relaxed font-sans"
        />

        {/* Model & Inference Selector Pill (Matching Image 1 Trigger Style) */}
        <div className="mb-0.5 min-w-0 flex-shrink">
          <button
            type="button"
            onClick={() => {
              setShowModelPopover(!showModelPopover);
              setActiveSubPanel('main');
            }}
            className="inline-flex items-center gap-1.5 px-3 py-1 bg-white/90 dark:bg-gray-700/90 hover:bg-white dark:hover:bg-gray-700 text-gray-700 dark:text-gray-200 text-[11px] font-semibold rounded-full border border-gray-300/80 dark:border-gray-600 transition shadow-2xs cursor-pointer select-none"
            title="点击展开模型与推理控制面板"
          >
            <Zap className="w-3 h-3 text-amber-500 fill-amber-500" />
            <span className="max-w-[7rem] truncate sm:max-w-[12rem]">{currentModelObj?.name?.split(' ')[0] || 'DeepSeek V4'} {reasoningLevel === 'high' ? '最高' : ''}</span>
            <ChevronDown className="w-3 h-3 text-gray-400 ml-0.5" />
          </button>
        </div>

        {/* Circular Send Button */}
        <button
          type="submit"
          disabled={disabled || !input.trim()}
          className="w-8 h-8 rounded-full bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-300 dark:disabled:bg-gray-700 text-white flex items-center justify-center transition flex-shrink-0 mb-0.5 shadow-xs cursor-pointer"
          title="发送"
        >
          <ArrowUp className="w-4 h-4" />
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
