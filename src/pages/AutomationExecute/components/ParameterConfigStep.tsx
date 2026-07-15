import React from 'react';
import { motion } from 'motion/react';
import { ChevronLeft, CheckCircle2, Ticket, RotateCcw, XCircle, AlertTriangle, Shield, Terminal, Maximize2, Play } from 'lucide-react';
import type { AutomationScenario, QuickPlaybookPreview, StepId } from '../types';

interface ParameterConfigStepProps {
  isZh: boolean;
  quickPlaybookScenario: AutomationScenario;
  groupedVariables: Record<string, any[]>;
  VAR_GROUP_ORDER: string[];
  varGroupLabel: (group: string) => string;
  quickPlaybookVars: Record<string, string>;
  onQuickPlaybookVarChange: (key: string, value: string) => void;
  quickPlaybookPlatform: string;
  quickPlaybookConcurrency: number;
  onQuickPlaybookConcurrencyChange: (value: number) => void;
  changeTicket: string;
  setChangeTicket: (val: string) => void;
  ticketValidation: {
    loading: boolean;
    found?: boolean;
    valid?: boolean;
    reason?: string;
    message?: string;
    title?: string;
    status?: string;
    scheduled_start?: string;
    scheduled_end?: string;
  };
  blockingIssues: Array<{ message: string; severity: 'critical' | 'high' | 'medium' }>;
  quickRiskConfirmed: boolean;
  onQuickRiskConfirmedChange: (value: boolean) => void;
  previewLineCount: number;
  quickPlaybookPreview: QuickPlaybookPreview | null;
  onOpenCommandPreview: () => void;
  canExecute: boolean;
  setConfirmAction: (action: 'validate' | 'apply') => void;
  setConfirmModalOpen: (val: boolean) => void;
  onRunValidation: (changeTicket?: string) => void;
  setCurrentStep: (val: StepId) => void;
  targetCount: number;
  getPlatformLabel: (platform: string) => string;
}

export const ParameterConfigStep: React.FC<ParameterConfigStepProps> = ({
  isZh,
  quickPlaybookScenario,
  groupedVariables,
  VAR_GROUP_ORDER,
  varGroupLabel,
  quickPlaybookVars,
  onQuickPlaybookVarChange,
  quickPlaybookPlatform,
  quickPlaybookConcurrency,
  onQuickPlaybookConcurrencyChange,
  changeTicket,
  setChangeTicket,
  ticketValidation,
  blockingIssues,
  quickRiskConfirmed,
  onQuickRiskConfirmedChange,
  previewLineCount,
  quickPlaybookPreview,
  onOpenCommandPreview,
  canExecute,
  setConfirmAction,
  setConfirmModalOpen,
  onRunValidation,
  setCurrentStep,
  targetCount,
  getPlatformLabel,
}) => {
  return (
    <motion.div
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 20 }}
      transition={{ duration: 0.2 }}
      className="h-full flex flex-col gap-3"
    >
      <div className="flex-1 min-h-0 flex gap-4 overflow-hidden">
        {/* Left Form: Parameter Inputs */}
        <div className="flex-1 min-w-0 overflow-auto pr-2 space-y-5 custom-scrollbar">
          {VAR_GROUP_ORDER.filter((group) => (groupedVariables[group] || []).length > 0).map((group) => (
            <div key={group} className="space-y-3">
              <h4 className="text-xs font-bold text-gray-500 border-b pb-1.5">{varGroupLabel(group)}</h4>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                {(groupedVariables[group] || []).map((v) => {
                  const val = quickPlaybookVars[v.key] || '';
                  const hasHint = v.platform_hints && v.platform_hints[quickPlaybookPlatform];
                  return (
                    <div key={v.key} className="flex flex-col gap-1.5">
                      <label className="text-xs font-semibold text-gray-700 flex items-center gap-1">
                        {isZh ? v.label_zh || v.label || v.key : v.label || v.key}
                        {v.required && <span className="text-red-500 font-bold">*</span>}
                      </label>
                      <input
                        type={v.type === 'number' ? 'number' : 'text'}
                        value={val}
                        onChange={(e) => onQuickPlaybookVarChange(v.key, e.target.value)}
                        placeholder={
                          hasHint
                            ? `${isZh ? '例如：' : 'e.g. '}${v.platform_hints[quickPlaybookPlatform]}`
                            : isZh
                            ? v.placeholder || '请输入...'
                            : v.placeholder || 'Enter value...'
                        }
                        className={`px-3 py-2 border border-gray-200 rounded-lg text-xs outline-none focus:border-cyan-400 focus:bg-white bg-gray-50/50 transition-all ${
                          v.required && !val ? 'border-amber-200 focus:border-amber-400' : ''
                        }`}
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          ))}

          {(quickPlaybookScenario.variables || []).length === 0 && (
            <div className="py-12 text-center text-emerald-600 bg-emerald-50/40 rounded-2xl border border-emerald-100 flex flex-col items-center justify-center gap-2">
              <CheckCircle2 size={16} />
              <span>{isZh ? '该场景无需配置参数，可直接执行。' : 'No parameters required. Ready to run.'}</span>
            </div>
          )}

          {/* Options: Concurrency + Change Ticket */}
          <div className="space-y-3 pt-2 border-t border-gray-100">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-500">{isZh ? '并发数' : 'Concurrency'}</span>
                <select
                  value={quickPlaybookConcurrency}
                  onChange={(e) => onQuickPlaybookConcurrencyChange(Number(e.target.value))}
                  className="px-2.5 py-1.5 border border-gray-200 rounded-lg text-xs bg-white outline-none"
                >
                  {[1, 2, 3, 5, 10].map((n) => (
                    <option key={n} value={n}>
                      ×{n}
                    </option>
                  ))}
                </select>
              </div>
              {quickPlaybookConcurrency > 1 && (
                <span className="text-[10px] text-amber-600 bg-amber-50 px-2 py-0.5 rounded-full">
                  {isZh ? '⚠ 建议先小批量验证' : '⚠ Validate with small batch first'}
                </span>
              )}
            </div>

            {quickPlaybookScenario.risk !== 'low' && (
              <div className="flex flex-col gap-2 rounded-xl border border-amber-100 bg-amber-50/50 p-3.5">
                <div className="flex items-center gap-2">
                  <Ticket size={14} className="text-amber-600" />
                  <label className="text-xs font-semibold text-amber-800">
                    {isZh ? '变更工单号' : 'Change Ticket Number'}
                    <span className="text-amber-700/70 ml-1">({isZh ? '可选' : 'Optional'})</span>
                  </label>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={changeTicket}
                    onChange={(e) => setChangeTicket(e.target.value)}
                    placeholder={isZh ? '可选：指定工单号；留空时自动匹配' : 'Optional: specify ticket; leave empty to auto-match'}
                    className={`w-full max-w-[360px] px-3 py-2 border rounded-lg text-xs outline-none bg-white transition-colors ${
                      ticketValidation.found === true && ticketValidation.valid
                        ? 'border-emerald-400 focus:border-emerald-500'
                        : ticketValidation.found === true && !ticketValidation.valid
                        ? 'border-red-400 focus:border-red-500'
                        : 'border-gray-200 focus:border-cyan-400'
                    }`}
                  />
                  {ticketValidation.loading && <RotateCcw size={14} className="animate-spin text-black/30 flex-shrink-0" />}
                  {!ticketValidation.loading && ticketValidation.found === true && ticketValidation.valid && (
                    <CheckCircle2 size={14} className="text-emerald-500 flex-shrink-0" />
                  )}
                  {!ticketValidation.loading && ticketValidation.found === true && !ticketValidation.valid && (
                    <XCircle size={14} className="text-red-500 flex-shrink-0" />
                  )}
                  {!ticketValidation.loading && ticketValidation.found === false && changeTicket.trim().length >= 4 && (
                    <XCircle size={14} className="text-black/25 flex-shrink-0" />
                  )}
                </div>

                {!ticketValidation.loading && changeTicket.trim().length >= 4 && (
                  <div
                    className={`rounded-lg px-3 py-2 text-[11px] ${
                      ticketValidation.found === true && ticketValidation.valid
                        ? 'bg-emerald-50 border border-emerald-200 text-emerald-700'
                        : ticketValidation.found === true && !ticketValidation.valid
                        ? 'bg-red-50 border border-red-200 text-red-700'
                        : ticketValidation.found === false
                        ? 'bg-gray-50 border border-gray-200 text-gray-500'
                        : ''
                    }`}
                  >
                    {ticketValidation.found === true && ticketValidation.valid && (
                      <div className="space-y-0.5">
                        <p className="font-semibold">{ticketValidation.title}</p>
                        <p className="text-[10px] text-emerald-600/70">
                          {isZh ? '工单已审批，当前在变更窗口内' : 'Order approved, within change window'}
                          {ticketValidation.scheduled_start && ticketValidation.scheduled_end && (
                            <span className="ml-1 font-mono">
                              ({ticketValidation.scheduled_start.replace('T', ' ').slice(0, 16)} ~{' '}
                              {ticketValidation.scheduled_end.replace('T', ' ').slice(0, 16)})
                            </span>
                          )}
                        </p>
                      </div>
                    )}
                    {ticketValidation.found === true && !ticketValidation.valid && (
                      <div className="space-y-0.5">
                        <p className="font-semibold flex items-center gap-1">
                          <AlertTriangle size={11} />
                          {ticketValidation.reason === 'expired'
                            ? isZh
                              ? '变更窗口已超时'
                              : 'Change window expired'
                            : ticketValidation.reason === 'not_started'
                            ? isZh
                              ? '变更窗口尚未开始'
                              : 'Change window not started'
                            : ticketValidation.reason === 'invalid_status'
                            ? isZh
                              ? '工单状态不允许执行'
                              : 'Order status does not allow execution'
                            : isZh
                            ? '工单不可用'
                            : 'Order unavailable'}
                        </p>
                        <p className="text-[10px] text-red-600/70">{ticketValidation.message}</p>
                      </div>
                    )}
                    {ticketValidation.found === false && <p>{isZh ? '未找到该工单号，请检查输入' : 'Order number not found, please check input'}</p>}
                  </div>
                )}

                <p className="text-[10px] text-amber-600">
                  {isZh
                    ? '系统会自动匹配该任务对应的有效变更单并校验时间窗；超时将禁止执行。'
                    : 'System auto-matches a valid change order for this scenario and enforces its time window.'}
                </p>
              </div>
            )}
          </div>

          {/* Blocking issues */}
          {blockingIssues.length > 0 && (
            <div className="space-y-2">
              <p className="text-[10px] font-bold uppercase tracking-widest text-red-500 flex items-center gap-1.5">
                <AlertTriangle size={12} />
                {isZh ? '阻塞项' : 'Blocking Issues'}
              </p>
              {blockingIssues.map((issue, i) => (
                <div
                  key={i}
                  className={`flex items-start gap-2 rounded-xl px-3.5 py-2.5 text-xs border ${
                    issue.severity === 'critical'
                      ? 'border-red-200 bg-red-50 text-red-700'
                      : issue.severity === 'high'
                      ? 'border-orange-200 bg-orange-50 text-orange-700'
                      : 'border-amber-200 bg-amber-50 text-amber-700'
                  }`}
                >
                  <span className="flex-shrink-0 mt-0.5 font-bold">
                    {issue.severity === 'critical' ? '✕' : issue.severity === 'high' ? '!' : '▲'}
                  </span>
                  <span>{issue.message}</span>
                </div>
              ))}
            </div>
          )}

          {/* High risk confirmation */}
          {quickPlaybookScenario.risk === 'high' && (
            <label className="flex items-start gap-2.5 rounded-xl border-2 border-red-200 bg-red-50 px-4 py-3 text-xs text-red-700 cursor-pointer">
              <input
                type="checkbox"
                checked={quickRiskConfirmed}
                onChange={(e) => onQuickRiskConfirmedChange(e.target.checked)}
                className="mt-0.5 flex-shrink-0 accent-red-600"
              />
              <span className="leading-relaxed font-sans">
                <Shield size={12} className="inline mr-1 -mt-0.5" />
                {isZh
                  ? '我已了解该场景为高风险操作，确认继续执行。执行后可能影响网络连通性。'
                  : 'I understand this is a high-risk operation and want to proceed. Network connectivity may be affected.'}
              </span>
            </label>
          )}
        </div>

        {/* Right Preview Panel */}
        <div className="w-[380px] flex-shrink-0 flex flex-col bg-[#0d1117] rounded-2xl border border-white/5 shadow-lg overflow-hidden">
          <div className="flex-shrink-0 flex items-center justify-between px-4 py-2.5 bg-[#161b22] border-b border-white/5">
            <div className="flex items-center gap-2">
              <div className="flex gap-[5px]">
                <span className="w-[9px] h-[9px] rounded-full bg-[#ff5f57]/80" />
                <span className="w-[9px] h-[9px] rounded-full bg-[#febc2e]/80" />
                <span className="w-[9px] h-[9px] rounded-full bg-[#28c840]/80" />
              </div>
              <span className="text-[10px] font-bold text-white/50 uppercase tracking-wider">{isZh ? 'CLI 预览' : 'CLI Preview'}</span>
              {previewLineCount > 0 && (
                <span className="text-[10px] text-white/25 font-mono">
                  {previewLineCount} {isZh ? '行' : 'lines'}
                </span>
              )}
            </div>
            {quickPlaybookPreview && (
              <button
                onClick={onOpenCommandPreview}
                className="text-[10px] text-white/30 hover:text-white/60 px-2 py-1 rounded-lg hover:bg-white/5 transition-all"
              >
                <Maximize2 size={12} />
              </button>
            )}
          </div>
          <div className="flex-1 min-h-0 overflow-auto p-4">
            {quickPlaybookPreview ? (
              <div className="space-y-4">
                {(['pre_check', 'execute', 'post_check', 'rollback'] as const)
                  .filter((phase) => (quickPlaybookPreview[phase] || []).length > 0)
                  .map((phase) => (
                    <div key={phase}>
                      <div className="flex items-center gap-2 mb-2">
                        <span
                          className={`w-1 h-3 rounded-full ${
                            phase === 'execute' ? 'bg-cyan-400' : phase === 'rollback' ? 'bg-red-400' : 'bg-white/20'
                          }`}
                        />
                        <span className="text-[9px] font-bold uppercase tracking-widest text-white/30">{phase.replace('_', ' ')}</span>
                      </div>
                      {(quickPlaybookPreview[phase] || []).map((cmd, idx) => (
                        <div key={idx} className="flex items-start gap-2 mb-1">
                          <span className="text-cyan-400/40 text-[11px] select-none mt-0.5">❯</span>
                          <code className="text-[11px] font-mono text-[#e6edf3] leading-relaxed whitespace-pre-wrap">{cmd}</code>
                        </div>
                      ))}
                    </div>
                  ))}
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center h-full gap-3 text-white/20">
                <Terminal size={24} strokeWidth={1} />
                <p className="text-xs">{isZh ? '填写参数后自动生成命令预览' : 'CLI preview auto-generates after filling variables'}</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Bottom Bar */}
      <div className="flex-shrink-0 flex items-center justify-between bg-white rounded-2xl border border-gray-100 shadow-sm px-5 py-3">
        <button
          onClick={() => setCurrentStep(2)}
          className="flex items-center gap-1.5 text-xs font-semibold text-gray-500 hover:text-gray-700 transition-colors"
        >
          <ChevronLeft size={14} />
          {isZh ? '返回场景选择' : 'Back to Scenarios'}
        </button>
        <div className="flex items-center gap-3">
          <p className="text-[10px] text-gray-400">{isZh ? '推荐：先运行校验确认无误，再应用变更' : 'Recommended: validate first, then apply'}</p>
          <button
            onClick={() => {
              if (quickPlaybookScenario.risk === 'high') {
                setConfirmAction('validate');
                setConfirmModalOpen(true);
              } else {
                onRunValidation(changeTicket.trim());
              }
            }}
            disabled={!canExecute}
            className={`px-5 py-2.5 rounded-xl text-xs font-bold transition-all border ${
              canExecute
                ? 'bg-white text-cyan-700 border-cyan-300 hover:bg-cyan-50 shadow-sm'
                : 'bg-gray-50 text-gray-300 border-gray-100 cursor-not-allowed'
            }`}
          >
            {isZh ? '🔍 运行校验' : '🔍 Validate'}
          </button>
          <button
            onClick={() => {
              setConfirmAction('apply');
              setConfirmModalOpen(true);
            }}
            disabled={!canExecute}
            className={`px-6 py-2.5 rounded-xl text-xs font-bold text-white transition-all flex items-center gap-2 ${
              canExecute
                ? 'bg-gradient-to-r from-cyan-500 to-teal-500 shadow-lg shadow-cyan-500/25 hover:shadow-cyan-500/40 hover:-translate-y-0.5'
                : 'bg-gray-200 text-gray-400 cursor-not-allowed'
            }`}
          >
            <Play size={13} />
            {isZh ? `应用变更 (${targetCount})` : `Apply (${targetCount})`}
          </button>
        </div>
      </div>
    </motion.div>
  );
};
