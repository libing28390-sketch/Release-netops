import React from 'react';
import {
  ChevronRight, Copy, Star, Bookmark, Save, Download, FileText,
  XCircle, Zap, CheckCircle2, AlertTriangle, User, UserCheck,
  Calendar, Shield, Hash, Clock, Paperclip, Info, RefreshCw
} from 'lucide-react';
import { motion } from 'motion/react';
import type { ChangeOrder, TimelineEvent, PlatformMeta } from '../types';
import type { SessionUser } from '../../../types';
import { STATUS_META, PRIORITY_META, RISK_META, EMPTY_TEMPLATE_PREVIEW } from '../constants';
import {
  fmtDate, fmtTime, statusLabel, priorityLabel, riskLabel, typeLabel,
  isCommandTemplateSnapshot, timelineEventLabel, translateSummary, fmtFileSize,
  buildWorkflowPresentation
} from '../helpers';
import { ControlSheetPanel } from './ControlSheetPanel';
import { ActionButton } from '../../../components/ui/ActionIconButton';


interface Props {
  language: string;
  selectedOrder: ChangeOrder;
  setSelectedOrder: (o: ChangeOrder | null) => void;
  currentUser: SessionUser;
  timeline: TimelineEvent[];
  timelineLoading: boolean;
  setTimeline: (t: TimelineEvent[]) => void;
  bookmarkedIds: Set<string>;
  handleToggleBookmark: (id: string) => void;
  handleCopyOrder: (order: ChangeOrder) => void;
  handleSaveAsTemplate: (order: ChangeOrder) => void;
  handleExportOrder: (order: ChangeOrder) => void;
  openEdit: (order: ChangeOrder) => void;
  getTransitionActions: (order: ChangeOrder) => { label: string; status: string; variant: string; icon: React.ComponentType<any> }[];
  handleTransition: (orderId: string, status: string, payload?: any) => void;
  setExecuteModal: (m: any) => void;
  setActionPrompt: (p: any) => void;
  setFinalApproverPrompt: (p: any) => void;
  FEATURE_CONTROL_SHEET: boolean;
  platforms: Record<string, PlatformMeta>;
}

export const ChangeOrderDetail: React.FC<Props> = ({
  language,
  selectedOrder,
  setSelectedOrder,
  currentUser,
  timeline,
  timelineLoading,
  setTimeline,
  bookmarkedIds,
  handleToggleBookmark,
  handleCopyOrder,
  handleSaveAsTemplate,
  handleExportOrder,
  openEdit,
  getTransitionActions,
  handleTransition,
  setExecuteModal,
  setActionPrompt,
  setFinalApproverPrompt,
  FEATURE_CONTROL_SHEET,
  platforms,
}) => {
  const zh = language === 'zh';

  const variantBtnClass = (variant: string) => {
    switch (variant) {
      case 'primary': return 'bg-[#00bceb] text-white hover:bg-[#0096bd] shadow-lg shadow-[#00bceb]/16';
      case 'success': return 'bg-emerald-500 text-white hover:bg-emerald-600 shadow-lg shadow-emerald-500/16';
      case 'danger':  return 'bg-rose-500 text-white hover:bg-rose-600 shadow-lg shadow-rose-500/16';
      default:        return 'bg-white text-black/60 border border-black/10 hover:bg-black/5';
    }
  };

  const platformLabel = (platformKey: string) => {
    if (!platformKey) return zh ? '未指定平台' : 'Unknown platform';
    const meta = platforms[platformKey] || {};
    const baseLabel = meta.name || platformKey;
    if (meta.icon && meta.vendor) return `${meta.icon} ${meta.vendor} · ${baseLabel}`;
    if (meta.icon) return `${meta.icon} ${baseLabel}`;
    if (meta.vendor) return `${meta.vendor} · ${baseLabel}`;
    return baseLabel;
  };

  return (
    <motion.div
      key={selectedOrder.id}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: 'spring', stiffness: 360, damping: 32 }}
    >
      {/* Back button + quick actions bar */}
      <div className="flex items-center justify-between mb-5">
        <button
          onClick={() => { setSelectedOrder(null); setTimeline([]); }}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-black/60 bg-white border border-black/8 hover:border-[#00bceb]/30 hover:text-[#00bceb] transition-all shadow-sm"
        >
          <ChevronRight size={15} className="rotate-180" />
          {zh ? '返回工单列表' : 'Back to List'}
        </button>
        <div className="flex items-center gap-2">
          {/* ── Utility buttons: Copy / Bookmark / Save as Template / Export ── */}
          <ActionButton icon={Copy} variant="accent" size="sm" onClick={() => handleCopyOrder(selectedOrder)} title={zh ? '复制工单' : 'Copy as new order'}>
            {zh ? '复制' : 'Copy'}
          </ActionButton>
          <button
            onClick={() => handleToggleBookmark(selectedOrder.id)}
            title={zh ? (bookmarkedIds.has(selectedOrder.id) ? '取消收藏' : '收藏') : (bookmarkedIds.has(selectedOrder.id) ? 'Remove bookmark' : 'Bookmark')}
            className={`px-3 py-2 rounded-xl text-xs font-medium flex items-center gap-1.5 border transition-all ${
              bookmarkedIds.has(selectedOrder.id)
                ? 'bg-amber-50 text-amber-600 border-amber-200 hover:bg-amber-100'
                : 'bg-white text-black/50 border-black/10 hover:bg-amber-50 hover:text-amber-500 hover:border-amber-200'
            }`}
          >
            {bookmarkedIds.has(selectedOrder.id) ? <Star size={13} className="fill-amber-400 text-amber-500" /> : <Bookmark size={13} />}
            {zh ? (bookmarkedIds.has(selectedOrder.id) ? '已收藏' : '收藏') : (bookmarkedIds.has(selectedOrder.id) ? 'Saved' : 'Save')}
          </button>
          {selectedOrder.requester_username === currentUser.username && (
            <button
              onClick={() => handleSaveAsTemplate(selectedOrder)}
              title={zh ? '保存为模板' : 'Save as template'}
              className="px-3 py-2 rounded-xl text-xs font-medium flex items-center gap-1.5 bg-white text-black/50 border border-black/10 hover:bg-emerald-50 hover:text-emerald-600 hover:border-emerald-200 transition-all"
            >
              <Save size={13} />
              {zh ? '存为模板' : 'Template'}
            </button>
          )}
          <ActionButton icon={Download} variant="accent" size="sm" onClick={() => handleExportOrder(selectedOrder)} title={zh ? '导出工单（CSV）' : 'Export order (CSV)'}>
            {zh ? '导出' : 'Export'}
          </ActionButton>
          <div className="w-px h-5 bg-black/8 mx-0.5" />
          {/* ── Workflow buttons ── */}
          {['draft', 'rejected'].includes(selectedOrder.status) && selectedOrder.requester_username === currentUser.username && (
            <button
              onClick={() => openEdit(selectedOrder)}
              className="px-3.5 py-2 rounded-xl text-xs font-medium flex items-center gap-1.5 bg-white text-black/60 border border-black/10 hover:bg-black/5 transition-all"
            >
              <FileText size={13} />
              {zh ? '编辑' : 'Edit'}
            </button>
          )}
          {getTransitionActions(selectedOrder).map(action => (
            <button
              key={action.status}
              onClick={() => {
                if (action.status === 'execute_commands') {
                  setExecuteModal({
                    order: selectedOrder,
                    phase: 'confirm',
                    output: '',
                    error: '',
                    success: false,
                  });
                } else if (['rejected', 'initial_review'].includes(action.status)) {
                  setActionPrompt({
                    title: action.status === 'initial_review' ? (zh ? '请输入退回原因' : 'Return reason') : (zh ? '请输入驳回原因' : 'Rejection reason'),
                    placeholder: zh ? '必填项，说明具体的意见 and 原因...' : 'Required. Specific reason/comments',
                    value: '',
                    required: true,
                    onConfirm: (val: string) => handleTransition(selectedOrder.id, action.status, { rejected_reason: val })
                  });
                } else if (action.status === 'approved') {
                  setActionPrompt({
                    title: zh ? '请输入审批意见' : 'Approval comments',
                    placeholder: zh ? '可选填，请输入审批通过意见...' : 'Optional comments...',
                    value: '',
                    required: false,
                    onConfirm: (val: string) => handleTransition(selectedOrder.id, action.status, { approval_comment: val })
                  });
                } else if (action.status === 'final_review') {
                  const proceed = (extraData?: any) => {
                    setActionPrompt({
                      title: zh ? '请输入初审意见' : 'Review comments',
                      placeholder: zh ? '可选填，请输入初审通过意见...' : 'Optional comments...',
                      value: '',
                      required: false,
                      onConfirm: (val: string) => handleTransition(selectedOrder.id, action.status, { ...extraData, review_comment: val })
                    });
                  };
                  if (selectedOrder.assigned_final_approver_id) {
                    proceed();
                  } else {
                    setFinalApproverPrompt({
                      onConfirm: (id: string) => proceed({ assigned_final_approver_id: id })
                    });
                  }
                } else if (action.status === 'implementing') {
                  setActionPrompt({
                    title: zh ? '实施前 MFA 再认证' : 'MFA re-authentication',
                    placeholder: zh ? '输入身份验证器中的动态验证码' : 'Enter the code from your authenticator',
                    value: '',
                    required: true,
                    sensitive: true,
                    onConfirm: (val: string) => handleTransition(selectedOrder.id, action.status, { mfa_code: val })
                  });
                } else if (action.status === 'completed') {
                  setActionPrompt({
                    title: zh ? '请输入实施结果说明' : 'Result summary',
                    placeholder: zh ? '可选填，实施结果的补充说明' : 'Optional result summary',
                    value: '',
                    required: false,
                    onConfirm: (val: string) => handleTransition(selectedOrder.id, action.status, { result_summary: val })
                  });
                } else if (action.status === 'failed') {
                  setActionPrompt({
                    title: zh ? '请输入失败原因' : 'Failure reason',
                    placeholder: zh ? '必填项，说明失败的具体原因' : 'Required. Reason for failure',
                    value: '',
                    required: true,
                    onConfirm: (val: string) => handleTransition(selectedOrder.id, action.status, { result_summary: val })
                  });
                } else if (action.status === 'rollback_in_progress') {
                  setActionPrompt({
                    title: zh ? '请输入回溯原因' : 'Rollback reason',
                    placeholder: zh ? '必填项，说明触发回溯的原因' : 'Required. Reason for rollback',
                    value: '',
                    required: true,
                    onConfirm: (val: string) => handleTransition(selectedOrder.id, action.status, { rollback_reason: val })
                  });
                } else if (action.status === 'rolled_back') {
                  setActionPrompt({
                    title: zh ? '请输入回溯结果说明' : 'Rollback summary',
                    placeholder: zh ? '可选填，回溯结果的补充说明' : 'Optional rollback summary',
                    value: '',
                    required: false,
                    onConfirm: (val: string) => handleTransition(selectedOrder.id, action.status, { result_summary: val })
                  });
                } else if (action.status === 'cancelled') {
                  setActionPrompt({
                    title: zh ? '确定要废除/取消此工单吗？' : 'Discard this order?',
                    placeholder: zh ? '可选填，说明废除工单的原因...' : 'Optional cancellation reason...',
                    value: '',
                    required: false,
                    onConfirm: (val: string) => handleTransition(selectedOrder.id, action.status, { cancellation_reason: val })
                  });
                } else {
                  handleTransition(selectedOrder.id, action.status);
                }
              }}
              className={`px-3.5 py-2 rounded-xl text-xs font-medium flex items-center gap-1.5 transition-all ${variantBtnClass(action.variant)}`}
            >
              <action.icon size={13} />
              {action.label}
            </button>
          ))}
        </div>
      </div>

      {/* Detail Header Card */}
      <div className="bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden">
        <div className="px-5 pt-4 pb-3 border-b border-black/5 bg-gradient-to-br from-[#00bceb]/[0.03] to-transparent">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-gradient-to-br from-[#00bceb]/12 to-[#0096bd]/6 ring-1 ring-[#00bceb]/12">
              <Hash size={14} className="text-[#00bceb]" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <p className="font-mono text-xs font-bold text-[#0e7490] tracking-wide">{selectedOrder.order_number}</p>
                {(() => {
                  const sm = STATUS_META[selectedOrder.status] || STATUS_META.draft;
                  return (
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold ring-1 ${sm.bg} ${sm.ring}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${sm.dot}`} />
                      {statusLabel(selectedOrder.status, language)}
                    </span>
                  );
                })()}
                {(() => {
                  const pm = PRIORITY_META[selectedOrder.priority] || PRIORITY_META.medium;
                  return (
                    <span className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-lg text-[10px] font-medium ${pm.bg} ${pm.color}`}>
                      {priorityLabel(selectedOrder.priority, language)}
                    </span>
                  );
                })()}
                <span className={`text-[10px] font-medium ${RISK_META[selectedOrder.risk_level]?.color || 'text-slate-500'}`}>
                  <Shield size={10} className="inline -mt-0.5 mr-0.5" />
                  {riskLabel(selectedOrder.risk_level, language)}
                </span>
              </div>
              <h3 className="mt-0.5 text-base font-semibold text-black/85 leading-snug">{selectedOrder.title}</h3>
            </div>
          </div>
        </div>

        {/* Detail Body — Compact Layout */}
        <div className="px-5 py-4 space-y-3">
          {/* ── Horizontal Workflow Stepper ── */}
          {(() => {
            const workflow = buildWorkflowPresentation(selectedOrder, language);
            const toneClass = workflow.exception?.tone === 'rose'
              ? 'bg-rose-50 ring-rose-200 text-rose-700'
              : workflow.exception?.tone === 'violet'
                ? 'bg-violet-50 ring-violet-200 text-violet-700'
                : 'bg-slate-50 ring-slate-200 text-slate-700';
            return (
              <div className="rounded-xl border border-black/6 bg-gradient-to-r from-[#00bceb]/[0.03] to-transparent px-4 py-3">
                <div className="flex items-center gap-0 overflow-x-auto">
                  {workflow.steps.map((step, index) => {
                    const isLast = index === workflow.steps.length - 1;
                    const dotClass = step.state === 'done'
                      ? 'bg-emerald-500 ring-emerald-200'
                      : step.state === 'current'
                        ? 'bg-sky-500 ring-sky-200 animate-pulse'
                        : step.state === 'error'
                          ? 'bg-rose-500 ring-rose-200'
                          : 'bg-black/15 ring-black/8';
                    const lineClass = step.state === 'done' ? 'bg-emerald-300' : step.state === 'error' ? 'bg-rose-300' : 'bg-black/10';
                    const labelClass = step.state === 'done'
                      ? 'text-emerald-700'
                      : step.state === 'current'
                        ? 'text-sky-700 font-bold'
                        : step.state === 'error'
                          ? 'text-rose-600'
                          : 'text-black/40';
                    return (
                      <React.Fragment key={step.key}>
                        <div className="flex flex-col items-center min-w-[60px] flex-shrink-0">
                          <span className={`w-5 h-5 rounded-full ring-2 flex items-center justify-center ${dotClass}`}>
                            {step.state === 'done' ? <CheckCircle2 size={11} className="text-white" /> :
                             step.state === 'current' ? <Clock size={11} className="text-white" /> :
                             step.state === 'error' ? <AlertTriangle size={10} className="text-white" /> :
                             <span className="text-[8px] font-bold text-white">{index + 1}</span>}
                          </span>
                          <span className={`mt-1 text-[10px] leading-tight text-center whitespace-nowrap ${labelClass}`}>{step.label[zh ? 'zh' : 'en']}</span>
                          {step.caption && <span className="text-[9px] text-black/30 text-center leading-tight mt-0.5 max-w-[80px] truncate">{step.caption}</span>}
                        </div>
                        {!isLast && <div className={`h-[2px] flex-1 min-w-[20px] mt-[-14px] ${lineClass}`} />}
                      </React.Fragment>
                    );
                  })}
                </div>
                {workflow.exception && (
                  <div className={`mt-2 rounded-lg p-2 ring-1 text-xs ${toneClass}`}>
                    <span className="font-semibold"><AlertTriangle size={10} className="inline -mt-0.5 mr-1" />{workflow.exception.label}</span>
                    <span className="ml-1.5">{workflow.exception.detail}</span>
                  </div>
                )}
              </div>
            );
          })()}

          {/* ── Content — consistent with creation form ── */}
          <div className="space-y-4">
            {/* ── Left Column: Meta + Description ── */}
            <div className="space-y-3">
              {/* Description */}
              {selectedOrder.description && (
                <div className="rounded-2xl border border-black/8 bg-black/[0.015] p-4">
                  <p className="text-xs font-semibold text-black/50 mb-1.5">{zh ? '描述' : 'Description'}</p>
                  <p className="text-sm text-black/65 leading-relaxed whitespace-pre-wrap">{selectedOrder.description}</p>
                </div>
              )}

              {/* Meta info — compact 2-col grid */}
              <div className="rounded-2xl border border-black/8 bg-black/[0.015] p-4">
                <p className="text-xs font-semibold text-black/50 mb-3">{zh ? '工单信息' : 'Order Info'}</p>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                  <div className="bg-white rounded-xl px-3 py-2.5 ring-1 ring-black/5">
                    <p className="text-[10px] font-semibold text-black/35 uppercase tracking-wider">{zh ? '类型' : 'Type'}</p>
                    <p className="mt-1 text-sm font-medium text-black/70">{typeLabel(selectedOrder.order_type, language)}</p>
                  </div>
                  <div className="bg-white rounded-xl px-3 py-2.5 ring-1 ring-black/5">
                    <p className="text-[10px] font-semibold text-black/35 uppercase tracking-wider">{zh ? '申请人' : 'Requester'}</p>
                    <p className="mt-1 text-sm font-medium text-black/70 flex items-center gap-1.5">
                      <User size={12} className="text-black/25" />
                      {selectedOrder.requester_username || '—'}
                    </p>
                  </div>
                  {selectedOrder.assigned_initial_reviewer_username && (
                    <div className="bg-white rounded-xl px-3 py-2.5 ring-1 ring-black/5">
                      <p className="text-[10px] font-semibold text-black/35 uppercase tracking-wider">{zh ? '指定初审人' : 'Assigned Reviewer'}</p>
                      <p className="mt-1 text-sm font-medium text-black/70 flex items-center gap-1.5">
                        <User size={12} className="text-black/25" />
                        {selectedOrder.assigned_initial_reviewer_username}
                      </p>
                    </div>
                  )}
                  {selectedOrder.initial_reviewer_username && (
                    <div className="bg-white rounded-xl px-3 py-2.5 ring-1 ring-black/5">
                      <p className="text-[10px] font-semibold text-black/35 uppercase tracking-wider">{zh ? '实际初审人' : 'Actual Reviewer'}</p>
                      <p className="mt-1 text-sm font-medium text-black/70 flex items-center gap-1.5">
                        <User size={12} className="text-black/25" />
                        {selectedOrder.initial_reviewer_username}
                      </p>
                    </div>
                  )}
                  {selectedOrder.assigned_final_approver_username && (
                    <div className="bg-white rounded-xl px-3 py-2.5 ring-1 ring-black/5">
                      <p className="text-[10px] font-semibold text-black/35 uppercase tracking-wider">{zh ? '指定终审人' : 'Assigned Approver'}</p>
                      <p className="mt-1 text-sm font-medium text-black/70 flex items-center gap-1.5">
                        <User size={12} className="text-black/25" />
                        {selectedOrder.assigned_final_approver_username}
                      </p>
                    </div>
                  )}
                  {(selectedOrder.final_approver_username || selectedOrder.approver_username) && (
                    <div className="bg-white rounded-xl px-3 py-2.5 ring-1 ring-black/5">
                      <p className="text-[10px] font-semibold text-black/35 uppercase tracking-wider">{zh ? '实际终审人' : 'Actual Approver'}</p>
                      <p className="mt-1 text-sm font-medium text-black/70 flex items-center gap-1.5">
                        <User size={12} className="text-black/25" />
                        {selectedOrder.final_approver_username || selectedOrder.approver_username}
                      </p>
                    </div>
                  )}
                  <div className="bg-white rounded-xl px-3 py-2.5 ring-1 ring-black/5">
                    <p className="text-[10px] font-semibold text-black/35 uppercase tracking-wider">{zh ? '创建时间' : 'Created'}</p>
                    <p className="mt-1 text-sm font-medium text-black/55 tabular-nums">{fmtDate(selectedOrder.created_at)}</p>
                  </div>
                </div>
              </div>

              {/* Schedule */}
              {(selectedOrder.scheduled_start || selectedOrder.scheduled_end) && (
                <div className="rounded-2xl border border-blue-100 bg-blue-50/60 p-4">
                  <p className="text-xs font-semibold text-blue-600 flex items-center gap-1.5 mb-1">
                    <Calendar size={12} /> {zh ? '计划时间窗口' : 'Scheduled Window'}
                  </p>
                  <p className="text-sm text-blue-700 tabular-nums">
                    {fmtDate(selectedOrder.scheduled_start)} — {fmtDate(selectedOrder.scheduled_end)}
                  </p>
                </div>
              )}

              {/* Result Summary */}
              {selectedOrder.result_summary && (
                <div className="rounded-2xl border border-emerald-100 bg-emerald-50/60 p-4">
                  <p className="text-xs font-semibold text-emerald-600 mb-1.5">{zh ? '执行结果' : 'Result'}</p>
                  <p className="text-sm text-black/60 leading-relaxed whitespace-pre-wrap">{selectedOrder.result_summary}</p>
                </div>
              )}

              {/* Rejected Reason */}
              {selectedOrder.rejected_reason && (
                <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4">
                  <p className="text-xs font-semibold text-rose-500 flex items-center gap-1.5 mb-1">
                    <AlertTriangle size={12} /> {zh ? '驳回原因' : 'Rejection Reason'}
                  </p>
                  <p className="text-sm text-rose-700">{selectedOrder.rejected_reason}</p>
                </div>
              )}

              {/* Rollback Reason */}
              {typeof selectedOrder.result_detail?.rollback_reason === 'string' && selectedOrder.result_detail.rollback_reason && (
                <div className="rounded-2xl border border-violet-200 bg-violet-50 p-4">
                  <p className="text-xs font-semibold text-violet-600 flex items-center gap-1.5 mb-1">
                    <AlertTriangle size={12} /> {zh ? '回溯原因' : 'Rollback Reason'}
                  </p>
                  <p className="text-sm text-violet-700">{selectedOrder.result_detail.rollback_reason}</p>
                </div>
              )}
            </div>

            {/* ── Right Column: Commands + Devices + Rollback ── */}
            <div className="space-y-3">
              {/* Template Snapshot */}
              {(() => {
                const templateSnapshot = isCommandTemplateSnapshot(selectedOrder.command_template) ? selectedOrder.command_template : null;
                if (!templateSnapshot) return null;
                const preview = templateSnapshot.preview || EMPTY_TEMPLATE_PREVIEW;
                return (
                  <div className="rounded-2xl border border-[#00bceb]/15 bg-gradient-to-br from-[#00bceb]/[0.04] to-white p-4">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <p className="text-xs font-semibold text-[#0e7490]">{zh ? '命令模板快照' : 'Template Snapshot'}</p>
                        <h4 className="mt-1 text-sm font-semibold text-black/80">
                          {zh ? (templateSnapshot.scenario_name_zh || templateSnapshot.scenario_name || templateSnapshot.scenario_id) : (templateSnapshot.scenario_name || templateSnapshot.scenario_id)}
                        </h4>
                      </div>
                      <span className="rounded-full bg-white px-2.5 py-1 text-[10px] font-semibold text-[#0e7490] ring-1 ring-[#00bceb]/20">
                        {platformLabel(templateSnapshot.platform)}
                      </span>
                    </div>
                    {Object.keys(templateSnapshot.variables || {}).length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-1.5">
                        {Object.entries(templateSnapshot.variables || {}).map(([key, value]) => (
                          <span key={key} className="inline-flex items-center gap-1 rounded-lg bg-white px-2 py-1 text-xs text-black/60 ring-1 ring-black/8">
                            <span className="font-semibold text-black/45">{key}</span>
                            <span>{value || '—'}</span>
                          </span>
                        ))}
                      </div>
                    )}
                    <div className="mt-3 grid grid-cols-1 gap-3">
                      {/* Pre-check Commands */}
                      {preview.pre_check.length > 0 ? (
                        <div>
                          <p className="text-xs font-semibold text-black/40 mb-1.5">{zh ? '预检命令' : 'Pre-check Commands'}</p>
                          <div className="rounded-xl bg-slate-900 p-3 font-mono text-xs text-cyan-300 whitespace-pre-wrap break-all leading-relaxed">
                            {preview.pre_check.map((cmd, index) => <div key={`pre-${cmd}-${index}`}>{index + 1}. {cmd}</div>)}
                          </div>
                        </div>
                      ) : (
                        <div>
                          <p className="text-xs font-semibold text-black/40 mb-1.5">{zh ? '预检命令' : 'Pre-check Commands'}</p>
                          <p className="text-xs text-black/30 italic">{zh ? '无' : 'None'}</p>
                        </div>
                      )}
                      {/* Execute Commands */}
                      {preview.execute.length > 0 ? (
                        <div>
                          <p className="text-xs font-semibold text-black/40 mb-1.5">{zh ? '执行命令' : 'Execute Commands'}</p>
                          <div className="rounded-xl bg-slate-900 p-3 font-mono text-xs text-emerald-300 whitespace-pre-wrap break-all leading-relaxed">
                            {preview.execute.map((cmd, index) => <div key={`exec-${cmd}-${index}`}>{index + 1}. {cmd}</div>)}
                          </div>
                        </div>
                      ) : (
                        <div>
                          <p className="text-xs font-semibold text-black/40 mb-1.5">{zh ? '执行命令' : 'Execute Commands'}</p>
                          <p className="text-xs text-black/30 italic">{zh ? '无' : 'None'}</p>
                        </div>
                      )}
                      {/* Post-check Commands */}
                      {preview.post_check.length > 0 ? (
                        <div>
                          <p className="text-xs font-semibold text-black/40 mb-1.5">{zh ? '后检命令' : 'Post-check Commands'}</p>
                          <div className="rounded-xl bg-slate-900 p-3 font-mono text-xs text-amber-300 whitespace-pre-wrap break-all leading-relaxed">
                            {preview.post_check.map((cmd, index) => <div key={`post-${cmd}-${index}`}>{index + 1}. {cmd}</div>)}
                          </div>
                        </div>
                      ) : (
                        <div>
                          <p className="text-xs font-semibold text-black/40 mb-1.5">{zh ? '后检命令' : 'Post-check Commands'}</p>
                          <p className="text-xs text-black/30 italic">{zh ? '无' : 'None'}</p>
                        </div>
                      )}
                      {/* Rollback Commands */}
                      {preview.rollback.length > 0 ? (
                        <div>
                          <p className="text-xs font-semibold text-black/40 mb-1.5">{zh ? '回滚命令' : 'Rollback Commands'}</p>
                          <div className="rounded-xl bg-slate-900 p-3 font-mono text-xs text-rose-300 whitespace-pre-wrap break-all leading-relaxed">
                            {preview.rollback.map((cmd, index) => <div key={`rollback-${cmd}-${index}`}>{index + 1}. {cmd}</div>)}
                          </div>
                        </div>
                      ) : (
                        <div>
                          <p className="text-xs font-semibold text-black/40 mb-1.5">{zh ? '回滚命令' : 'Rollback Commands'}</p>
                          <p className="text-xs text-black/30 italic">{zh ? '无' : 'None'}</p>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })()}

              {/* Target Devices */}
              {selectedOrder.target_devices?.length > 0 && (
                <div className="rounded-2xl border border-black/8 bg-black/[0.015] p-4">
                  <p className="text-xs font-semibold text-black/50 mb-2">{zh ? '目标设备' : 'Target Devices'}</p>
                  <div className="flex flex-wrap gap-2">
                    {selectedOrder.target_devices.map((dev, i) => (
                      <span key={i} className="inline-flex items-center gap-1.5 rounded-xl bg-cyan-50/80 px-3 py-2 text-xs font-medium text-cyan-800 ring-1 ring-cyan-200/70">
                        {dev.hostname || (zh ? '未命名' : 'Unnamed')}
                        {dev.ip_address && <span className="font-mono text-[11px] text-cyan-600/80">{dev.ip_address}</span>}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Commands */}
              {selectedOrder.commands?.length > 0 && (
                <div className="rounded-2xl border border-black/8 bg-black/[0.015] p-4">
                  <p className="text-xs font-semibold text-black/50 mb-2">{zh ? '执行命令' : 'Commands'}</p>
                  <div className="bg-slate-900 rounded-xl p-3 font-mono text-xs text-emerald-400 leading-relaxed whitespace-pre-wrap break-all">
                    {selectedOrder.commands.map((cmd, i) => (
                      <div key={i} className="flex">
                        <span className="text-slate-500 select-none mr-2 w-5 text-right">{i + 1}</span>
                        {cmd}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Rollback Plan */}
              {selectedOrder.rollback_plan && (
                <div className="rounded-2xl border border-amber-100 bg-amber-50/50 p-4">
                  <p className="text-xs font-semibold text-black/50 mb-1.5">{zh ? '回退方案' : 'Rollback Plan'}</p>
                  <p className="text-sm text-black/60 leading-relaxed whitespace-pre-wrap">
                    {selectedOrder.rollback_plan}
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* ── Control Sheet Missing Banner (historical orders) ── */}
          {FEATURE_CONTROL_SHEET && selectedOrder.control_sheet_missing && (
            <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 flex items-start gap-3">
              <Info size={16} className="text-amber-500 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-semibold text-amber-700">
                  {zh ? '变更控制表数据缺失' : 'Control Sheet Data Missing'}
                </p>
                <p className="text-xs text-amber-600 mt-0.5">
                  {zh
                    ? '此工单为历史工单，创建时尚未启用变更控制表功能，相关结构化字段与附件不可用。'
                    : 'This is a historical order created before the control sheet feature was enabled. Structured fields and attachments are unavailable.'}
                </p>
              </div>
            </div>
          )}

          {/* ── Control Sheet Section & Attachments ── */}
          {FEATURE_CONTROL_SHEET && !selectedOrder.control_sheet_missing && (
            <ControlSheetPanel language={language} selectedOrder={selectedOrder} />
          )}

          {/* ── Timeline (Professional Vertical Layout) ── */}
          <div className="rounded-2xl border border-black/8 bg-white p-6">
            <div className="flex items-center justify-between mb-6">
              <p className="text-sm font-bold text-black/80 flex items-center gap-2">
                <Clock size={16} className="text-[#00bceb]" />
                {zh ? '工单全生命周期记录' : 'Order Lifecycle Timeline'}
              </p>
              <span className="text-[10px] font-medium text-black/40 px-2 py-0.5 bg-black/[0.03] rounded-full">
                {zh ? `共 ${timeline.length} 条记录` : `${timeline.length} events`}
              </span>
            </div>

            {timelineLoading ? (
              <div className="flex items-center justify-center py-8 text-black/30">
                <RefreshCw size={18} className="animate-spin mr-2" /> {zh ? '加载时间线中...' : 'Loading timeline...'}
              </div>
            ) : timeline.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 text-black/30 border border-dashed border-black/10 rounded-xl">
                <Clock size={24} className="mb-2 opacity-20" />
                <p className="text-xs">{zh ? '暂无流程记录' : 'No timeline events'}</p>
              </div>
            ) : (
              <div className="relative pl-8 space-y-8 before:absolute before:left-[11px] before:top-2 before:bottom-2 before:w-0.5 before:bg-gradient-to-b before:from-[#00bceb]/60 before:via-[#00bceb]/20 before:to-transparent">
                {[...timeline].reverse().map((evt, idx) => {
                  const isNewest = idx === 0;
                  const isControlSheetUpload = evt.event_type === 'change_order.control_sheet_uploaded';
                  return (
                    <div key={evt.id} className="relative">
                      {/* Dot on the line */}
                      <div className={`absolute -left-[35px] top-1.5 w-6 h-6 rounded-full border-4 border-white shadow-sm flex items-center justify-center z-10 ${
                        isControlSheetUpload
                          ? 'bg-teal-500 scale-105'
                          : isNewest ? 'bg-[#00bceb] scale-110' : 'bg-slate-200'
                      }`}>
                        {isControlSheetUpload
                          ? <Paperclip size={10} className="text-white" />
                          : <div className={`w-1.5 h-1.5 rounded-full ${isNewest ? 'bg-white' : 'bg-black/20'}`} />
                        }
                      </div>

                      <div className={`group transition-all duration-300 ${isNewest ? 'translate-x-1' : ''}`}>
                        <div className="flex flex-wrap items-center gap-3 mb-1.5">
                          <span className={`text-sm font-bold ${
                            isControlSheetUpload ? 'text-teal-700' : isNewest ? 'text-black/90' : 'text-black/60'
                          }`}>
                            {timelineEventLabel(evt.event_type, language)}
                          </span>
                          <span className="text-[11px] font-mono text-black/40 bg-black/[0.03] px-2 py-0.5 rounded-md tabular-nums">
                            {fmtDate(evt.created_at)}
                          </span>
                          <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[10px] font-bold ring-1 ${
                            isControlSheetUpload
                              ? 'bg-teal-50 text-teal-700 ring-teal-200/50'
                              : 'bg-sky-50 text-[#0e7490] ring-sky-200/50'
                          }`}>
                            <User size={10} />
                            {evt.actor_username || (zh ? '系统自动化' : 'System')}
                          </div>
                          {isControlSheetUpload && (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-teal-100 text-teal-700 ring-1 ring-teal-200">
                              <Paperclip size={9} />
                              {zh ? '附件' : 'Attachment'}
                            </span>
                          )}
                        </div>
                        <div className={`p-3.5 rounded-2xl border transition-all ${
                          isControlSheetUpload
                            ? 'border-teal-100 bg-teal-50/40 group-hover:bg-teal-50 group-hover:border-teal-200'
                            : 'border-black/5 bg-black/[0.01] group-hover:bg-black/[0.03] group-hover:border-[#00bceb]/20'
                        }`}>
                          <p className="text-xs text-black/60 leading-relaxed">
                            {translateSummary(evt.summary || timelineEventLabel(evt.event_type, language), language)}
                          </p>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </motion.div>
  );
};
