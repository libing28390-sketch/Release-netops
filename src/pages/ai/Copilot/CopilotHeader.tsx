import React, { useEffect, useRef, useState } from 'react';
import { Download, FileCode2, FileText, RotateCcw, Sparkles } from 'lucide-react';

interface CopilotModelOption {
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

const getModelHealthClass = (status?: string) => {
  switch (String(status || 'unknown').toLowerCase()) {
    case 'healthy': return 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-400';
    case 'unhealthy': return 'bg-red-50 text-red-700 dark:bg-red-950/60 dark:text-red-400';
    default: return 'bg-gray-200/70 text-gray-600 dark:bg-gray-700 dark:text-gray-300';
  }
};

interface CopilotHeaderProps {
  sessionTitle: string;
  selectedModel: string;
  models?: CopilotModelOption[];
  onClearChat: () => void;
  onExportMarkdown?: () => void;
  onExportJson?: () => void;
  canExport?: boolean;
}

/**
 * Page header.  The model is chosen only in the composer; the header shows
 * the current model read-only (name + health badge).  The fallback to the
 * first configured model mirrors the composer, so both always agree.
 */
export const CopilotHeader: React.FC<CopilotHeaderProps> = ({
  sessionTitle,
  selectedModel,
  models = [],
  onClearChat,
  onExportMarkdown,
  onExportJson,
  canExport = false,
}) => {
  const [exportOpen, setExportOpen] = useState(false);
  const exportMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!exportOpen) return;
    const onPointerDown = (event: MouseEvent) => {
      if (exportMenuRef.current && !exportMenuRef.current.contains(event.target as Node)) {
        setExportOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setExportOpen(false);
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [exportOpen]);

  const currentModel = models.find((m) => m.id === selectedModel) || models[0];
  const modelName = currentModel ? (currentModel.name || currentModel.model_code || '默认模型') : '默认模型';
  const healthLabel = currentModel ? getModelHealthLabel(currentModel.health_status) : '';

  return (
    <header className="h-13 min-w-0 shrink-0 border-b border-gray-100 dark:border-gray-800/70 bg-white/90 dark:bg-gray-900/90 backdrop-blur-xs px-4 flex items-center justify-between gap-2 select-none">
      {/* Minimal Gemini-style Header: Title + Subtle Model Badge */}
      <div className="flex min-w-0 items-center gap-2.5">
        <div className="flex min-w-0 items-center gap-2">
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gradient-to-tr from-blue-500 via-indigo-500 to-purple-500 text-white shadow-2xs">
            <Sparkles className="w-3.5 h-3.5" />
          </span>
          <h2 className="font-semibold text-gray-900 dark:text-white text-sm truncate max-w-[260px]">
            {sessionTitle || '新对话'}
          </h2>
        </div>

        <div
          aria-label="当前模型"
          title={currentModel ? `${currentModel.provider_name || 'AI 供应商'} · ${currentModel.model_code || modelName}（在输入框中切换模型）` : '未配置可选模型，使用服务端默认模型'}
          className="flex min-w-0 items-center gap-1.5 bg-gray-100/80 dark:bg-gray-800/80 text-gray-600 dark:text-gray-300 text-[11px] font-medium px-2.5 py-0.5 rounded-full"
        >
          <span data-testid="copilot-header-model-name" className="truncate max-w-[180px]">{modelName}</span>
          {currentModel && (
            <span
              data-testid="copilot-header-model-health"
              className={`shrink-0 rounded-full px-1.5 py-px text-[10px] ${getModelHealthClass(currentModel.health_status)}`}
            >
              {healthLabel}
            </span>
          )}
        </div>
      </div>

      {/* Minimal Actions: Export + Clear Chat */}
      <div className="flex shrink-0 items-center gap-1">
        {(onExportMarkdown || onExportJson) && (
          <div ref={exportMenuRef} className="relative">
            <button
              type="button"
              disabled={!canExport}
              aria-expanded={exportOpen}
              aria-haspopup="menu"
              onClick={() => setExportOpen((prev) => !prev)}
              className="inline-flex items-center gap-1 rounded-full px-2.5 py-1.5 text-xs font-medium text-gray-500 transition hover:bg-gray-100 hover:text-gray-800 disabled:cursor-not-allowed disabled:opacity-40 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200"
              title={canExport ? '导出当前会话' : '当前会话暂无消息可导出'}
            >
              <Download className="w-3.5 h-3.5" />
              <span>导出</span>
            </button>
            {exportOpen && canExport && (
              <div
                role="menu"
                className="absolute right-0 top-full z-30 mt-1.5 w-48 rounded-xl border border-gray-200/90 bg-white p-1.5 text-xs shadow-lg dark:border-gray-700 dark:bg-gray-800"
              >
                {onExportMarkdown && (
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setExportOpen(false);
                      onExportMarkdown();
                    }}
                    className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-gray-700 transition hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-gray-700"
                  >
                    <FileText className="w-3.5 h-3.5 text-indigo-500 shrink-0" />
                    <span>导出为 Markdown (.md)</span>
                  </button>
                )}
                {onExportJson && (
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setExportOpen(false);
                      onExportJson();
                    }}
                    className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-gray-700 transition hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-gray-700"
                  >
                    <FileCode2 className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
                    <span>导出为 JSON (.json)</span>
                  </button>
                )}
              </div>
            )}
          </div>
        )}
        <button
          type="button"
          onClick={onClearChat}
          className="p-2 hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-400 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 rounded-full transition"
          title="清空当前对话"
        >
          <RotateCcw className="w-4 h-4" />
        </button>
      </div>
    </header>
  );
};
