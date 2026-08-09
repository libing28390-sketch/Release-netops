import React from 'react';
import { RotateCcw, SlidersHorizontal, ChevronDown, Sparkles, Bot, ShieldCheck } from 'lucide-react';

interface CopilotHeaderProps {
  sessionTitle: string;
  selectedModel: string;
  onSelectModel: (model: string) => void;
  models?: Array<{ id: string; name: string; model_code: string; provider_name: string }>;
  onClearChat: () => void;
  onToggleInspector: () => void;
  isInspectorOpen: boolean;
}

export const CopilotHeader: React.FC<CopilotHeaderProps> = ({
  sessionTitle,
  selectedModel,
  onSelectModel,
  models = [],
  onClearChat,
  onToggleInspector,
  isInspectorOpen,
}) => {
  const defaultModels = [
    { id: 'm0', name: 'DeepSeek V4 Flash (默认极速)', model_code: 'deepseek-v4-flash', provider_name: 'DeepSeek' },
    { id: 'm0pro', name: 'DeepSeek V4 Pro (专业旗舰)', model_code: 'deepseek-v4-pro', provider_name: 'DeepSeek' },
  ];

  const effectiveModels = models.length > 0 ? models : defaultModels;

  const groupedModels = effectiveModels.reduce((acc, m) => {
    const pName = m.provider_name || 'AI 供应商';
    if (!acc[pName]) acc[pName] = [];
    acc[pName].push(m);
    return acc;
  }, {} as Record<string, typeof effectiveModels>);

  return (
    <header className="h-14 min-w-0 shrink-0 border-b border-gray-200/70 dark:border-gray-800 bg-white/80 dark:bg-gray-900/80 backdrop-blur-xs px-3 sm:px-4 flex items-center justify-between gap-2 select-none">
      {/* Title & Model Selector */}
      <div className="flex min-w-0 items-center gap-2 sm:gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <Bot className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
          <h2 className="font-bold text-gray-900 dark:text-white text-sm truncate max-w-[240px]">
            {sessionTitle || '新对话'}
          </h2>
        </div>

        {/* Model Select Pill */}
        <div className="relative group">
          <select
            value={selectedModel}
            onChange={(e) => onSelectModel(e.target.value)}
            className="appearance-none bg-gray-100 dark:bg-gray-800 hover:bg-gray-200/70 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-200 text-xs font-medium pl-3 pr-7 py-1 rounded-full border border-gray-200/80 dark:border-gray-700 cursor-pointer focus:outline-none transition"
          >
            {Object.entries(groupedModels).map(([providerName, modelList]) => (
              <optgroup key={providerName} label={providerName}>
                {modelList.map((m) => (
                  <option key={m.model_code} value={m.model_code}>
                    {m.name || m.model_code}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          <ChevronDown className="w-3.5 h-3.5 absolute right-2.5 top-2 text-gray-400 pointer-events-none" />
        </div>
      </div>

      {/* Actions: Clear Chat & Inspector Drawer Toggle */}
      <div className="flex shrink-0 items-center gap-1 sm:gap-2">
        <span className="hidden sm:flex items-center gap-1 text-[11px] text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/60 px-2 py-0.5 rounded-full font-medium">
          <ShieldCheck className="w-3 h-3" /> 内网事实优先
        </span>

        <button
          onClick={onClearChat}
          className="p-1.5 hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 hover:text-red-600 dark:text-gray-400 dark:hover:text-red-400 rounded-lg transition"
          title="清空当前对话"
        >
          <RotateCcw className="w-4 h-4" />
        </button>

        <button
          onClick={onToggleInspector}
          className={`p-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition border ${
            isInspectorOpen
              ? 'bg-indigo-50 dark:bg-indigo-950/70 border-indigo-200 dark:border-indigo-800 text-indigo-600 dark:text-indigo-400'
              : 'border-transparent text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800 dark:text-gray-400'
          }`}
          title="开启/关闭开发者调试抽屉"
        >
          <SlidersHorizontal className="w-4 h-4" />
          <span className="hidden md:inline">调试 Trace</span>
        </button>
      </div>
    </header>
  );
};
