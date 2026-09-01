import React from 'react';
import { AlertTriangle, ArrowRight, CheckCircle2, Clock3, ListFilter, ShieldAlert, X } from 'lucide-react';
import { AssistantClarification, AssistantClarificationOption } from '../../../api/ai';

interface ClarificationCardProps {
  clarification: AssistantClarification;
  disabled?: boolean;
  onSelect: (option: AssistantClarificationOption) => void;
  onCancel: () => void;
}

const fieldLabels: Record<string, string> = {
  device_id: '目标设备',
  device_identifier: '目标设备',
  device_or_scope: '设备范围',
  device_or_time_range: '设备或时间范围',
  interface: '接口',
  protocol: '协议',
  metric: '指标',
  time_range: '时间范围',
  action: '动作',
  confirmation: '确认授权',
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
  const expiresAt = clarification.expires_at ? Date.parse(clarification.expires_at) : NaN;
  const expired = Number.isFinite(expiresAt) && expiresAt <= Date.now();
  const isHighRisk = clarification.requires_confirmation || clarification.risk_level === 'R3' || clarification.risk_level === 'R4' || clarification.risk === 'high' || clarification.risk === 'critical';
  const title = expired
    ? '补充信息已过期'
    : isHighRisk
      ? '执行前安全确认'
      : clarification.request_kind === 'intent_classification'
        ? '需要补充信息'
        : '先确认配置范围';
  const ariaLabel = expired ? '补充信息已过期' : isHighRisk ? '执行前安全确认' : '补充信息';
  const recognizedFields = Object.entries(clarification.recognized_fields || {})
    .filter(([, value]) => String(value || '').trim())
    .slice(0, 8);
  const options = Array.isArray(clarification.options)
    ? clarification.options.filter((option) => option && (option.label || option.value)).slice(0, 12)
    : [];
  const missingFields = (clarification.missing_fields || [])
    .map((field) => fieldLabels[field] || field)
    .slice(0, 4);

  return (
    <section
      className="rounded-2xl border border-indigo-200/80 bg-indigo-50/70 p-4 shadow-xs dark:border-indigo-800/70 dark:bg-indigo-950/25"
      aria-label={ariaLabel}
      data-testid="clarification-card"
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-white shadow-sm">
          <ListFilter className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-indigo-900 dark:text-indigo-100">{title}</h3>
            {clarification.risk && !expired && (
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${isHighRisk ? 'bg-rose-100 text-rose-700 dark:bg-rose-950/50 dark:text-rose-300' : 'bg-white/80 text-indigo-700 dark:bg-gray-900/60 dark:text-indigo-300'}`}>
                {isHighRisk ? '高风险 · 需确认' : clarification.risk === 'medium' ? '配置参考' : '只读查询'}
              </span>
            )}
            {clarification.risk_level && !expired && <span className="rounded-full bg-white/80 px-2 py-0.5 text-[10px] font-mono text-indigo-700 dark:bg-gray-900/60 dark:text-indigo-300">{clarification.risk_level}</span>}
          </div>
          <p className={`mt-1.5 text-xs leading-relaxed ${expired ? 'text-amber-800 dark:text-amber-300' : 'text-indigo-900/80 dark:text-indigo-100/80'}`}>
            {expired ? '这张澄清卡片已超过有效期，请重新描述当前问题，避免沿用旧设备、接口或时间范围。' : clarification.question || '请补充需要查询的功能和设备平台。'}
          </p>
          {expired && (
            <div className="mt-2 inline-flex items-center gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-2 py-1 text-[11px] text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-300">
              <Clock3 className="h-3.5 w-3.5" /> 已过期，不会继续提交旧条件
            </div>
          )}
          {recognizedFields.length > 0 && !expired && (
            <div className="mt-3 rounded-xl border border-indigo-200/70 bg-white/60 p-2.5 dark:border-indigo-800/70 dark:bg-gray-900/40">
              <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold text-indigo-800 dark:text-indigo-200">
                <CheckCircle2 className="h-3.5 w-3.5" /> 当前已识别
              </div>
              <div className="flex flex-wrap gap-1.5">
                {recognizedFields.map(([field, value]) => (
                  <span key={field} className="rounded-lg border border-indigo-100 bg-white px-2 py-1 text-[11px] text-indigo-900 dark:border-indigo-900/70 dark:bg-gray-900 dark:text-indigo-100">
                    <span className="text-indigo-500 dark:text-indigo-300">{fieldLabels[field] || field}</span>：{String(value)}
                  </span>
                ))}
              </div>
            </div>
          )}
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
              disabled={disabled || expired}
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
        <span className="inline-flex items-center gap-1.5">{isHighRisk && !expired ? <ShieldAlert className="h-3.5 w-3.5" /> : <AlertTriangle className="h-3.5 w-3.5" />}{expired ? '请重新发送当前问题开始新的澄清' : isHighRisk ? '普通聊天文本不会直接执行变更，需完成独立确认。' : '也可以直接在输入框补充设备、接口、协议或时间范围。'}</span>
        <button
          type="button"
          disabled={disabled}
          onClick={onCancel}
          className="inline-flex items-center gap-1 rounded-lg px-2 py-1 font-medium text-indigo-700 hover:bg-white/70 disabled:cursor-not-allowed disabled:opacity-50 dark:text-indigo-300 dark:hover:bg-gray-900/60"
        >
          <X className="h-3.5 w-3.5" />
          {expired ? '重新开始' : '取消引导'}
        </button>
      </div>
    </section>
  );
};

export default ClarificationCard;
