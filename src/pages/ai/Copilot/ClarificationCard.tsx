import React from 'react';
import { ArrowRight, ListFilter, X } from 'lucide-react';
import { AssistantClarification, AssistantClarificationOption } from '../../../api/ai';

interface ClarificationCardProps {
  clarification: AssistantClarification;
  disabled?: boolean;
  onSelect: (option: AssistantClarificationOption) => void;
  onCancel: () => void;
}

const fieldLabels: Record<string, string> = {
  feature: '功能',
  cli_platform: '平台',
  target_device: '目标设备',
  product_model: '型号',
  software_version: '版本',
};

export const ClarificationCard: React.FC<ClarificationCardProps> = ({
  clarification,
  disabled = false,
  onSelect,
  onCancel,
}) => {
  const options = Array.isArray(clarification.options)
    ? clarification.options.filter((option) => option && (option.label || option.value)).slice(0, 12)
    : [];
  const missingFields = (clarification.missing_fields || [])
    .map((field) => fieldLabels[field] || field)
    .slice(0, 4);

  return (
    <section
      className="rounded-2xl border border-indigo-200/80 bg-indigo-50/70 p-4 shadow-xs dark:border-indigo-800/70 dark:bg-indigo-950/25"
      aria-label="配置范围确认"
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-white shadow-sm">
          <ListFilter className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-indigo-900 dark:text-indigo-100">先确认配置范围</h3>
            {clarification.risk && (
              <span className="rounded-full bg-white/80 px-2 py-0.5 text-[10px] font-medium text-indigo-700 dark:bg-gray-900/60 dark:text-indigo-300">
                {clarification.risk === 'high' ? '涉及变更' : '配置参考'}
              </span>
            )}
          </div>
          <p className="mt-1.5 text-xs leading-relaxed text-indigo-900/80 dark:text-indigo-100/80">
            {clarification.question || '请补充需要查询的功能和设备平台。'}
          </p>
          {missingFields.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-indigo-700 dark:text-indigo-300">
              <span className="font-medium">待补充：</span>
              {missingFields.map((field) => (
                <span key={field} className="rounded border border-indigo-200 bg-white/70 px-1.5 py-0.5 dark:border-indigo-800 dark:bg-gray-900/50">
                  {field}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {options.length > 0 && (
        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {options.map((option, index) => (
            <button
              type="button"
              key={`${option.field || 'option'}-${option.value}-${index}`}
              disabled={disabled}
              onClick={() => onSelect(option)}
              className="group flex min-w-0 items-center justify-between gap-2 rounded-xl border border-indigo-200/80 bg-white/85 px-3 py-2.5 text-left text-xs text-indigo-900 transition hover:border-indigo-400 hover:bg-white disabled:cursor-not-allowed disabled:opacity-50 dark:border-indigo-800/80 dark:bg-gray-900/60 dark:text-indigo-100 dark:hover:border-indigo-500 dark:hover:bg-gray-900"
            >
              <span className="min-w-0 truncate font-medium">{option.label || option.value}</span>
              <span className="flex shrink-0 items-center gap-1 text-[10px] text-indigo-500 opacity-70 transition group-hover:translate-x-0.5 group-hover:opacity-100 dark:text-indigo-300">
                {option.field ? fieldLabels[option.field] || option.field : '选择'}
                <ArrowRight className="h-3 w-3" />
              </span>
            </button>
          ))}
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-indigo-200/70 pt-3 text-[11px] text-indigo-700/80 dark:border-indigo-800/70 dark:text-indigo-300/80">
        <span>也可以直接在输入框补充型号、版本或 display version 回显。</span>
        <button
          type="button"
          disabled={disabled}
          onClick={onCancel}
          className="inline-flex items-center gap-1 rounded-lg px-2 py-1 font-medium text-indigo-700 hover:bg-white/70 disabled:cursor-not-allowed disabled:opacity-50 dark:text-indigo-300 dark:hover:bg-gray-900/60"
        >
          <X className="h-3.5 w-3.5" />
          取消引导
        </button>
      </div>
    </section>
  );
};

export default ClarificationCard;
