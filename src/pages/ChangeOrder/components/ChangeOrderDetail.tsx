import React, { useEffect, useState } from 'react';
import {
  ChevronRight, Copy, Star, Bookmark, Save, Download, FileText,
  CheckCircle2, AlertTriangle, User,
  Calendar, Shield, Clock, Paperclip, Info, RefreshCw
} from 'lucide-react';
import { motion } from 'motion/react';
import type { ChangeOrder, TimelineEvent, PlatformMeta, ResultReviewAction } from '../types';
import type { SessionUser, User as UserOption } from '../../../types';
import { STATUS_META, EMPTY_TEMPLATE_PREVIEW } from '../constants';
import {
  fmtDate, fmtTime, statusLabel, priorityLabel, riskLabel, typeLabel,
  isCommandTemplateSnapshot, timelineEventLabel, translateSummary, fmtFileSize,
  buildWorkflowPresentation, describeCurrentResponsibility, getNextWorkflowAction, getChangeOrderWindowState,
  canRecordEmergencyPostReview,
} from '../helpers';
import { ControlSheetPanel } from './ControlSheetPanel';
import type { ControlSheetUploadResult } from './ControlSheetPanel';
import { ChangeOrderWorkflowPanels, type AssignmentRequest, type ChangeOrderMutationResult, type VerificationRequest } from './ChangeOrderWorkflowPanels';
import { ActionButton } from '../../../components/ui/ActionIconButton';
import { TicketFacts, ticketSurfaceClass } from '../../../components/tickets/TicketUI';


interface Props {
  language: string;
  selectedOrder: ChangeOrder;
  onCloseDetail: () => void;
  detailLoading: boolean;
  detailError: 'permission' | 'load' | null;
  retryDetail: () => void;
  currentUser: SessionUser;
  users: UserOption[];
  timeline: TimelineEvent[];
  timelineLoading: boolean;
  setTimeline: (t: TimelineEvent[]) => void;
  bookmarkedIds: Set<string>;
  handleToggleBookmark: (id: string) => void;
  handleCopyOrder: (order: ChangeOrder) => void;
  handleSaveAsTemplate: (order: ChangeOrder) => void;
  handleExportOrder: (order: ChangeOrder) => void;
  openEdit: (order: ChangeOrder) => void;
  getTransitionActions: (order: ChangeOrder) => { label: string; status: string; variant: string; icon: React.ComponentType<any>; disabled?: boolean; disabledReason?: string }[];
  handleTransition: (orderId: string, status: string, payload?: any) => void;
  handleAssignment: (orderId: string, request: AssignmentRequest) => Promise<ChangeOrderMutationResult>;
  handleVerification: (orderId: string, request: VerificationRequest) => Promise<ChangeOrderMutationResult>;
  handleResultReview: (orderId: string, action: ResultReviewAction, summary: string) => Promise<void>;
  handleEmergencyReview: (orderId: string, outcome: 'accepted' | 'follow_up_required', note: string) => Promise<ChangeOrderMutationResult>;
  handleControlSheetUpload: (orderId: string, file: File) => Promise<ControlSheetUploadResult>;
  handleControlSheetDownload: (orderId: string, attachmentId: string, filename: string) => void;
  setExecuteModal: (m: any) => void;
  setActionPrompt: (p: any) => void;
  setFinalApproverPrompt: (p: any) => void;
  FEATURE_CONTROL_SHEET: boolean;
  platforms: Record<string, PlatformMeta>;
}

export const ChangeOrderDetail: React.FC<Props> = ({
  language,
  selectedOrder,
  onCloseDetail,
  detailLoading,
  detailError,
  retryDetail,
  currentUser,
  users,
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
  handleAssignment,
  handleVerification,
  handleEmergencyReview,
  handleControlSheetUpload,
  handleControlSheetDownload,
  handleResultReview,
  setExecuteModal,
  setActionPrompt,
  setFinalApproverPrompt,
  FEATURE_CONTROL_SHEET,
  platforms,
}) => {
  const zh = language === 'zh';
  const [emergencyOutcome, setEmergencyOutcome] = useState<'accepted' | 'follow_up_required'>('accepted');
  const [emergencyReviewNote, setEmergencyReviewNote] = useState('');
  const [emergencyReviewError, setEmergencyReviewError] = useState('');
  const [emergencyReviewBusy, setEmergencyReviewBusy] = useState(false);
  const [currentTime, setCurrentTime] = useState(() => Date.now());
  const responsibility = describeCurrentResponsibility(selectedOrder, language);
  const windowState = getChangeOrderWindowState(selectedOrder, currentTime);
  const windowBlockReason = windowState === 'before'
    ? (zh ? '实施窗口未开始' : 'Window not started')
    : windowState === 'ended'
      ? (zh ? '实施窗口已结束，请调整计划并重新审批' : 'Window ended. Reschedule and request approval again.')
      : (zh ? '实施窗口无效，请调整计划并重新审批' : 'Invalid window. Reschedule and request approval again.');
  const hasControlSheetAttachment = Boolean(selectedOrder.control_sheet_attachments?.length);
  const transitionActions = detailLoading || detailError ? [] : getTransitionActions(selectedOrder).map(action => {
    if (action.status === 'implementing' && !hasControlSheetAttachment) {
      return {
        ...action,
        disabled: true,
        disabledReason: zh
          ? '实施前请先上传至少一份控制表附件。'
          : 'Upload at least one control sheet attachment before implementation.',
      };
    }
    return selectedOrder.status === 'approved' && action.status === 'implementing' && windowState !== 'open'
      ? { ...action, disabled: true, disabledReason: windowBlockReason }
      : action;
  });
  const nextStep = getNextWorkflowAction(selectedOrder, transitionActions, language, currentTime, currentUser);
  useEffect(() => {
    setCurrentTime(Date.now());
    const timer = window.setInterval(() => setCurrentTime(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, [selectedOrder.id]);

  const scheduledWindowState = windowState === 'invalid'
    ? (zh ? '时间待确认' : 'Window incomplete')
    : windowState === 'before'
      ? (zh ? '未开始' : 'Not started')
      : windowState === 'open'
        ? (zh ? '窗口内' : 'In window')
        : (zh ? '已结束' : 'Ended');

  const variantBtnClass = (variant: string) => {
    switch (variant) {
      case 'primary': return 'bg-[var(--ui-accent)] text-white hover:bg-[var(--ui-accent-hover)]';
      case 'success': return 'bg-[var(--ui-success)] text-white hover:brightness-95';
      case 'danger': return 'bg-[var(--ui-danger)] text-white hover:brightness-95';
      default: return 'border border-[var(--ui-border)] bg-[var(--ui-surface)] text-[var(--ui-fg-muted)] hover:bg-[var(--ui-surface-muted)]';
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

  const canRecordEmergencyReview = !detailLoading && !detailError && canRecordEmergencyPostReview(selectedOrder, currentUser.id);
  const submitEmergencyReview = async () => {
    if (!emergencyReviewNote.trim() || emergencyReviewBusy) return;
    setEmergencyReviewBusy(true);
    setEmergencyReviewError('');
    const result = await handleEmergencyReview(selectedOrder.id, emergencyOutcome, emergencyReviewNote.trim());
    if (result.success === true) {
      setEmergencyReviewNote('');
    } else {
      setEmergencyReviewError(result.message);
    }
    setEmergencyReviewBusy(false);
  };

  return (
    <motion.div
      key={selectedOrder.id}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: 'spring', stiffness: 360, damping: 32 }}
    >
      {detailLoading && (
        <div role="status" aria-live="polite" className="mb-4 flex items-center gap-2 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface-muted)] px-4 py-3 text-[13px] text-[var(--ui-fg-muted)]">
          <RefreshCw size={14} className="animate-spin" />
          {zh ? '正在加载工单详情…' : 'Loading order details…'}
        </div>
      )}
      {detailError && (
        <div role="alert" className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-[var(--ui-danger)]/30 bg-[var(--ui-danger-subtle)] px-4 py-3 text-[13px] text-[var(--ui-danger)]">
          <span className="min-w-0 flex-1">
            {detailError === 'permission'
              ? (zh ? '无权读取工单完整详情，或登录状态已失效。当前显示的列表摘要可能不完整。' : 'You are not authorized to load the full order details, or your session has expired. The visible list summary may be incomplete.')
              : (zh ? '工单详情加载失败，当前显示的是列表摘要。' : 'Could not load order details. The visible content is only the list summary.')}
          </span>
          <button type="button" onClick={retryDetail} disabled={detailLoading} className="min-h-9 shrink-0 rounded-lg border border-[var(--ui-danger)]/40 px-3 text-[13px] font-semibold hover:bg-[var(--ui-danger-subtle)] disabled:cursor-not-allowed disabled:opacity-50">
            {zh ? '重试' : 'Retry'}
          </button>
        </div>
      )}
      {/* Back button + quick actions bar */}
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <button
          type="button"
          onClick={onCloseDetail}
          className="inline-flex min-h-9 items-center gap-2 self-start rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 text-[13px] font-medium text-[var(--ui-fg-muted)] transition-colors hover:bg-[var(--ui-surface-muted)] hover:text-[var(--ui-fg)]"
        >
          <ChevronRight size={15} className="rotate-180" />
          {zh ? '返回工单列表' : 'Back to List'}
        </button>
        <div className="flex flex-wrap items-center gap-2 sm:justify-end">
          {/* ── Utility buttons: Copy / Bookmark / Save as Template / Export ── */}
          <ActionButton icon={Copy} variant="accent" size="sm" onClick={() => handleCopyOrder(selectedOrder)} title={zh ? '复制工单' : 'Copy as new order'}>
            {zh ? '复制' : 'Copy'}
          </ActionButton>
          <button
            onClick={() => handleToggleBookmark(selectedOrder.id)}
            title={zh ? (bookmarkedIds.has(selectedOrder.id) ? '取消收藏' : '收藏') : (bookmarkedIds.has(selectedOrder.id) ? 'Remove bookmark' : 'Bookmark')}
            className={`inline-flex min-h-9 items-center gap-1.5 rounded-lg border px-3 text-[13px] font-medium transition-colors ${
              bookmarkedIds.has(selectedOrder.id)
                ? 'border-[var(--ui-warning)]/30 bg-[var(--ui-warning-subtle)] text-[var(--ui-warning)]'
                : 'border-[var(--ui-border)] bg-[var(--ui-surface)] text-[var(--ui-fg-muted)] hover:bg-[var(--ui-surface-muted)]'
            }`}
          >
            {bookmarkedIds.has(selectedOrder.id) ? <Star size={13} className="fill-amber-400 text-amber-500" /> : <Bookmark size={13} />}
            {zh ? (bookmarkedIds.has(selectedOrder.id) ? '已收藏' : '收藏') : (bookmarkedIds.has(selectedOrder.id) ? 'Saved' : 'Save')}
          </button>
          {selectedOrder.requester_username === currentUser.username && (
            <button
              onClick={() => handleSaveAsTemplate(selectedOrder)}
              title={zh ? '保存为模板' : 'Save as template'}
              className="inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 text-[13px] font-medium text-[var(--ui-fg-muted)] transition-colors hover:bg-[var(--ui-surface-muted)]"
            >
              <Save size={13} />
              {zh ? '存为模板' : 'Template'}
            </button>
          )}
          <ActionButton icon={Download} variant="accent" size="sm" onClick={() => handleExportOrder(selectedOrder)} title={zh ? '导出工单（CSV）' : 'Export order (CSV)'}>
            {zh ? '导出' : 'Export'}
          </ActionButton>
          {/* ── Workflow buttons ── */}
          {transitionActions.filter(action => action.status === 'cancelled').map(action => (
            <ActionButton key={action.status} variant="danger" size="sm" onClick={() => setActionPrompt({
              title: zh ? '确定要废除/取消此工单吗？' : 'Discard this order?',
              placeholder: zh ? '可选填，说明废除工单的原因...' : 'Optional cancellation reason...',
              value: '', required: false,
              onConfirm: (value: string) => handleTransition(selectedOrder.id, action.status, { cancellation_reason: value }),
            })}><action.icon size={13} />{action.label}</ActionButton>
          ))}
          {!detailLoading && !detailError && ['draft', 'rejected'].includes(selectedOrder.status) && selectedOrder.requester_username === currentUser.username && (
            <button
              onClick={() => openEdit(selectedOrder)}
              className="inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 text-[13px] font-medium text-[var(--ui-fg)] transition-colors hover:bg-[var(--ui-surface-muted)]"
            >
              <FileText size={13} />
              {zh ? '编辑' : 'Edit'}
            </button>
          )}

        </div>
      </div>

      <section className={`${ticketSurfaceClass} overflow-hidden`} aria-label={zh ? '变更工单摘要' : 'Change order summary'}>
        <header className="border-b border-[var(--ui-border)] p-4 sm:px-5 sm:py-4">
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1.5">
            <p className="font-mono text-[13px] font-semibold text-[var(--ui-fg-muted)]">{selectedOrder.order_number}</p>
            {(() => {
              const sm = STATUS_META[selectedOrder.status] || STATUS_META.draft;
              return (
                <span className={`inline-flex min-h-6 items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ${sm.bg} ${sm.ring}`}>
                  <span className={`h-1.5 w-1.5 rounded-full ${sm.dot}`} />
                  {statusLabel(selectedOrder.status, language)}
                </span>
              );
            })()}
            <span className="rounded-full border border-[var(--ui-border)] px-2.5 py-1 text-[11px] text-[var(--ui-fg-muted)]">{priorityLabel(selectedOrder.priority, language)}</span>
            <span className="inline-flex items-center gap-1 rounded-full border border-[var(--ui-border)] px-2.5 py-1 text-[11px] text-[var(--ui-fg-muted)]">
              <Shield size={12} aria-hidden="true" />{riskLabel(selectedOrder.risk_level, language)}
            </span>
          </div>
          <h2 className="mt-2 text-[17px] font-semibold leading-6 text-[var(--ui-fg)]">{selectedOrder.title}</h2>
          <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <TicketFacts items={[{ label: zh ? '当前处理人' : 'Current owner', value: responsibility.owner }]} />
            <section aria-label={zh ? '下一步' : 'Next step'} className="min-w-0 sm:max-w-[60%] sm:text-right">
              <p className="text-xs text-[var(--ui-fg-muted)]">{zh ? '下一步' : 'Next step'}</p>
              <p className="mt-1 text-[13px] font-medium leading-5 text-[var(--ui-fg)]">{nextStep}</p>
              {transitionActions.some(action => action.status !== 'cancelled') && <div className="mt-2 flex flex-wrap items-start gap-2 sm:justify-end">
          {transitionActions.filter(action => action.status !== 'cancelled').map(action => (
            <div key={action.status} className="flex flex-col items-start gap-0.5">
              <button
                type="button"
                disabled={action.disabled}
                title={action.disabledReason}
                aria-describedby={action.disabledReason ? `change-order-action-hint-${action.status}` : undefined}
                onClick={() => {
                if (action.status.startsWith('result_review_')) {
                  const reviewAction = action.status.slice('result_review_'.length) as ResultReviewAction;
                  setActionPrompt({ title: action.label, placeholder: zh ? '填写实施结果或复核意见' : 'Enter implementation results or review comments', value: '', required: true,
                    onConfirm: (summary: string) => handleResultReview(selectedOrder.id, reviewAction, summary),
                  });
                } else if (action.status === 'execute_commands') {
                  setExecuteModal({
                    order: selectedOrder,
                    phase: 'confirm',
                    output: '',
                    error: '',
                    success: false,
                    requestSent: false,
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
                    title: zh ? '请输入回退原因' : 'Rollback reason',
                    placeholder: zh ? '必填项，说明触发回退的原因' : 'Required. Reason for rollback',
                    value: '',
                    required: true,
                    onConfirm: (val: string) => handleTransition(selectedOrder.id, action.status, { rollback_reason: val })
                  });
                } else if (action.status === 'rolled_back') {
                  setActionPrompt({
                    title: zh ? '请输入回退结果说明' : 'Rollback summary',
                    placeholder: zh ? '可选填，回退结果的补充说明' : 'Optional rollback summary',
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
                className={`inline-flex min-h-9 items-center gap-1.5 rounded-lg px-3 text-[13px] font-medium transition-colors ${variantBtnClass(action.variant)} disabled:cursor-not-allowed disabled:opacity-45`}
              >
                <action.icon size={13} />
                {action.label}
              </button>
              {action.disabledReason && <span id={`change-order-action-hint-${action.status}`} className="max-w-[180px] text-[11px] leading-4 text-[var(--ui-warning)]">{action.disabledReason}</span>}
            </div>
          ))}
              </div>}
            </section>
          </div>
        </header>

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
              <div className="rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface-muted)] px-4 py-3">
                <div className="flex items-center gap-0 overflow-x-auto">
                  {workflow.steps.map((step, index) => {
                    const isLast = index === workflow.steps.length - 1;
                    const dotClass = step.state === 'done'
                      ? 'bg-emerald-500 ring-emerald-200'
                      : step.state === 'current'
                        ? 'bg-sky-500 ring-sky-200 animate-pulse'
                        : step.state === 'error'
                          ? 'bg-rose-500 ring-rose-200'
                          : 'bg-[var(--ui-fg-subtle)] ring-[var(--ui-border)]';
                    const lineClass = step.state === 'done' ? 'bg-emerald-300' : step.state === 'error' ? 'bg-rose-300' : 'bg-[var(--ui-border)]';
                    const labelClass = step.state === 'done'
                      ? 'text-emerald-700'
                      : step.state === 'current'
                        ? 'text-sky-700 font-bold'
                        : step.state === 'error'
                          ? 'text-rose-600'
                          : 'text-[var(--ui-fg-muted)]';
                    return (
                      <React.Fragment key={step.key}>
                        <div className="flex flex-col items-center min-w-[60px] flex-shrink-0">
                          <span className={`w-5 h-5 rounded-full ring-2 flex items-center justify-center ${dotClass}`}>
                            {step.state === 'done' ? <CheckCircle2 size={11} className="text-white" /> :
                             step.state === 'current' ? <Clock size={11} className="text-white" /> :
                             step.state === 'error' ? <AlertTriangle size={10} className="text-white" /> :
                             <span className="text-[11px] font-bold text-white">{index + 1}</span>}
                          </span>
                          <span className={`mt-1 whitespace-nowrap text-center text-[11px] leading-tight ${labelClass}`}>{step.label[zh ? 'zh' : 'en']}</span>
                          {step.caption && <span className="mt-0.5 max-w-[100px] truncate text-center text-[11px] leading-tight text-[var(--ui-fg-muted)]">{step.caption}</span>}
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
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {/* ── Left Column: Meta + Description ── */}
            <div className="space-y-3">
              {/* Description */}
              {selectedOrder.description && (
                <div className="rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface-muted)] p-4">
                  <p className="text-xs font-semibold text-[var(--ui-fg-muted)] mb-1.5">{zh ? '描述' : 'Description'}</p>
                  <p className="text-[13px] text-[var(--ui-fg)] leading-relaxed whitespace-pre-wrap">{selectedOrder.description}</p>
                </div>
              )}

              <section className={`${ticketSurfaceClass} p-4`} aria-label={zh ? '工单信息' : 'Order information'}>
                <h3 className="mb-3 text-[13px] font-semibold text-[var(--ui-fg)]">{zh ? '工单信息' : 'Order information'}</h3>
                <TicketFacts
                  className="gap-y-2 sm:grid-cols-2 xl:grid-cols-2"
                  items={[
                    { label: zh ? '变更类型' : 'Change type', value: typeLabel(selectedOrder.order_type, language) },
                    { label: zh ? '创建时间' : 'Created', value: fmtDate(selectedOrder.created_at) },
                  ]}
                />
              </section>

              {/* Schedule */}
              {(selectedOrder.scheduled_start || selectedOrder.scheduled_end) && (
                <section className={`${ticketSurfaceClass} p-4`} aria-label={zh ? '计划时间窗口' : 'Scheduled window'}>
                  <p className="text-xs font-semibold text-[var(--ui-fg-muted)] flex items-center gap-1.5 mb-1.5">
                    <Calendar size={14} /> {zh ? '计划时间窗口' : 'Scheduled window'}
                  </p>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <p className="text-[13px] font-medium text-[var(--ui-fg)] tabular-nums">
                      {fmtDate(selectedOrder.scheduled_start)} — {fmtDate(selectedOrder.scheduled_end)}
                    </p>
                    <span className="rounded-full border border-[var(--ui-border)] bg-[var(--ui-surface-muted)] px-2.5 py-1 text-[11px] font-medium text-[var(--ui-fg-muted)]">{scheduledWindowState}</span>
                  </div>
                </section>
              )}

              {/* Result Summary */}
              {selectedOrder.result_summary && (
                <div className={`${ticketSurfaceClass} p-4`}>
                  <p className="mb-1.5 text-[13px] font-semibold text-[var(--ui-fg-muted)]">{zh ? '执行结果' : 'Result'}</p>
                  <p className="whitespace-pre-wrap text-[13px] leading-5 text-[var(--ui-fg)]">{selectedOrder.result_summary}</p>
                </div>
              )}

              {selectedOrder.order_type === 'emergency' && (
                <section className="rounded-2xl border border-amber-200 bg-amber-50/60 p-4" aria-label={zh ? '紧急变更事后复核' : 'Emergency post-review'}>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-xs font-semibold text-amber-900">{zh ? '紧急变更事后复核' : 'Emergency post-review'}</p>
                      <p className="mt-1 text-[11px] leading-relaxed text-amber-800">{selectedOrder.emergency_reason || (zh ? '未填写紧急原因' : 'No emergency reason recorded')}</p>
                    </div>
                    <span className={`rounded-full px-2.5 py-1 text-[10px] font-semibold ${selectedOrder.emergency_review_status === 'accepted' ? 'bg-emerald-100 text-emerald-800' : selectedOrder.emergency_review_status === 'follow_up_required' ? 'bg-rose-100 text-rose-800' : 'bg-amber-100 text-amber-900'}`}>
                      {selectedOrder.emergency_review_status === 'accepted'
                        ? (zh ? '复核通过' : 'Reviewed')
                        : selectedOrder.emergency_review_status === 'follow_up_required'
                          ? (zh ? '需要跟进' : 'Follow-up required')
                          : (zh ? '待复核' : 'Review pending')}
                    </span>
                  </div>
                  <div className="mt-3 grid gap-2 text-[11px] text-amber-950 sm:grid-cols-2">
                    <p>{zh ? '复核人：' : 'Reviewer: '}{users.find((person) => person.id === selectedOrder.emergency_review_owner_id)?.username || selectedOrder.emergency_review_owner_id || '—'}</p>
                    <p>{zh ? '复核期限：' : 'Due: '}{fmtTime(selectedOrder.emergency_review_due_at || '')}</p>
                    {selectedOrder.emergency_reviewed_by && <p>{zh ? '登记人：' : 'Recorded by: '}{selectedOrder.emergency_reviewed_by}</p>}
                    {selectedOrder.emergency_reviewed_at && <p>{zh ? '复核时间：' : 'Reviewed at: '}{fmtTime(selectedOrder.emergency_reviewed_at)}</p>}
                  </div>
                  {selectedOrder.emergency_review_note && <p className="mt-2 whitespace-pre-wrap text-xs text-amber-950">{selectedOrder.emergency_review_note}</p>}
                  {selectedOrder.emergency_review_status === 'pending' && !canRecordEmergencyReview && (
                    <p className="mt-3 rounded-lg bg-white/70 px-3 py-2 text-[11px] text-amber-800">
                      {selectedOrder.emergency_review_owner_id !== currentUser.id
                        ? (zh ? '仅指定复核人可以登记结果。' : 'Only the assigned reviewer can record the outcome.')
                        : (zh ? '执行结束并完成归档后，可以登记复核结果。' : 'The review outcome can be recorded after execution ends and the change is closed.')}
                    </p>
                  )}
                  {canRecordEmergencyReview && (
                    <div className="mt-3 space-y-2 border-t border-amber-200 pt-3">
                      <div className="flex flex-wrap gap-2">
                        <button type="button" aria-pressed={emergencyOutcome === 'accepted'} onClick={() => setEmergencyOutcome('accepted')} className={`min-h-8 rounded-lg px-3 text-[11px] font-semibold ${emergencyOutcome === 'accepted' ? 'bg-emerald-600 text-white' : 'border border-amber-200 bg-white text-amber-900'}`}>{zh ? '复核通过' : 'Accept'}</button>
                        <button type="button" aria-pressed={emergencyOutcome === 'follow_up_required'} onClick={() => setEmergencyOutcome('follow_up_required')} className={`min-h-8 rounded-lg px-3 text-[11px] font-semibold ${emergencyOutcome === 'follow_up_required' ? 'bg-rose-600 text-white' : 'border border-amber-200 bg-white text-amber-900'}`}>{zh ? '需要跟进' : 'Follow-up required'}</button>
                      </div>
                      <textarea value={emergencyReviewNote} onChange={(event) => setEmergencyReviewNote(event.target.value)} maxLength={4000} rows={2} placeholder={zh ? '填写复核结论和后续事项' : 'Record the review result and any follow-up'} className="w-full rounded-lg border border-amber-200 bg-white px-3 py-2 text-xs text-slate-800 outline-none focus:border-amber-400" />
                      {emergencyReviewError && <p role="alert" className="text-[11px] text-rose-700">{emergencyReviewError}</p>}
                      <button type="button" disabled={!emergencyReviewNote.trim() || emergencyReviewBusy} onClick={() => void submitEmergencyReview()} className="min-h-9 rounded-lg bg-amber-700 px-3.5 text-xs font-semibold text-white hover:bg-amber-800 disabled:cursor-not-allowed disabled:opacity-50">{emergencyReviewBusy ? (zh ? '正在保存…' : 'Saving…') : (zh ? '提交复核' : 'Submit review')}</button>
                    </div>
                  )}
                </section>
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
                    <AlertTriangle size={12} /> {zh ? '回退原因' : 'Rollback Reason'}
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
                  <details className={`group ${ticketSurfaceClass} overflow-hidden`}>
                    <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-3 px-4 py-3 hover:bg-[var(--ui-surface-muted)]">
                      <span className="min-w-0">
                        <span className="block text-xs font-semibold text-[var(--ui-fg-muted)]">{zh ? '命令模板快照' : 'Command template snapshot'}</span>
                        <span className="mt-1 block truncate text-[13px] font-medium text-[var(--ui-fg)]">
                          {zh ? (templateSnapshot.scenario_name_zh || templateSnapshot.scenario_name || templateSnapshot.scenario_id) : (templateSnapshot.scenario_name || templateSnapshot.scenario_id)}
                        </span>
                      </span>
                      <span className="flex items-center gap-2 text-[11px] text-[var(--ui-fg-muted)]">
                        {platformLabel(templateSnapshot.platform)}<ChevronRight size={14} className="transition-transform group-open:rotate-90" aria-hidden="true" />
                      </span>
                    </summary>
                    <div className="border-t border-[var(--ui-border)] p-4">
                      {Object.keys(templateSnapshot.variables || {}).length > 0 && (
                        <div className="mb-3 flex flex-wrap gap-1.5">
                          {Object.entries(templateSnapshot.variables || {}).map(([key, value]) => (
                            <span key={key} className="inline-flex items-center gap-1 rounded-md border border-[var(--ui-border)] bg-[var(--ui-surface-muted)] px-2 py-1 text-[12px] text-[var(--ui-fg)]">
                              <span className="font-semibold text-[var(--ui-fg-muted)]">{key}</span>
                              <span>{value || '—'}</span>
                            </span>
                          ))}
                        </div>
                      )}
                    <div className="mt-3 grid grid-cols-1 gap-3">
                      {/* Pre-check Commands */}
                      {preview.pre_check.length > 0 ? (
                        <div>
                          <p className="text-xs font-semibold text-[var(--ui-fg-muted)] mb-1.5">{zh ? '预检命令' : 'Pre-check Commands'}</p>
                          <div className="rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface-muted)] p-3 font-mono text-[12px] text-[var(--ui-fg)] whitespace-pre-wrap break-all leading-5">
                            {preview.pre_check.map((cmd, index) => <div key={`pre-${cmd}-${index}`}>{index + 1}. {cmd}</div>)}
                          </div>
                        </div>
                      ) : (
                        <div>
                          <p className="text-xs font-semibold text-[var(--ui-fg-muted)] mb-1.5">{zh ? '预检命令' : 'Pre-check Commands'}</p>
                          <p className="text-[12px] text-[var(--ui-fg-muted)]">{zh ? '无' : 'None'}</p>
                        </div>
                      )}
                      {/* Execute Commands */}
                      {preview.execute.length > 0 ? (
                        <div>
                          <p className="text-xs font-semibold text-[var(--ui-fg-muted)] mb-1.5">{zh ? '执行命令' : 'Execute Commands'}</p>
                          <div className="rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface-muted)] p-3 font-mono text-[12px] text-[var(--ui-fg)] whitespace-pre-wrap break-all leading-5">
                            {preview.execute.map((cmd, index) => <div key={`exec-${cmd}-${index}`}>{index + 1}. {cmd}</div>)}
                          </div>
                        </div>
                      ) : (
                        <div>
                          <p className="text-xs font-semibold text-[var(--ui-fg-muted)] mb-1.5">{zh ? '执行命令' : 'Execute Commands'}</p>
                          <p className="text-[12px] text-[var(--ui-fg-muted)]">{zh ? '无' : 'None'}</p>
                        </div>
                      )}
                      {/* Post-check Commands */}
                      {preview.post_check.length > 0 ? (
                        <div>
                          <p className="text-xs font-semibold text-[var(--ui-fg-muted)] mb-1.5">{zh ? '后检命令' : 'Post-check Commands'}</p>
                          <div className="rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface-muted)] p-3 font-mono text-[12px] text-[var(--ui-fg)] whitespace-pre-wrap break-all leading-5">
                            {preview.post_check.map((cmd, index) => <div key={`post-${cmd}-${index}`}>{index + 1}. {cmd}</div>)}
                          </div>
                        </div>
                      ) : (
                        <div>
                          <p className="text-xs font-semibold text-[var(--ui-fg-muted)] mb-1.5">{zh ? '后检命令' : 'Post-check Commands'}</p>
                          <p className="text-[12px] text-[var(--ui-fg-muted)]">{zh ? '无' : 'None'}</p>
                        </div>
                      )}
                      {/* Rollback Commands */}
                      {preview.rollback.length > 0 ? (
                        <div>
                          <p className="text-xs font-semibold text-[var(--ui-fg-muted)] mb-1.5">{zh ? '回退命令' : 'Rollback Commands'}</p>
                          <div className="rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface-muted)] p-3 font-mono text-[12px] text-[var(--ui-fg)] whitespace-pre-wrap break-all leading-5">
                            {preview.rollback.map((cmd, index) => <div key={`rollback-${cmd}-${index}`}>{index + 1}. {cmd}</div>)}
                          </div>
                        </div>
                      ) : (
                        <div>
                          <p className="text-xs font-semibold text-[var(--ui-fg-muted)] mb-1.5">{zh ? '回退命令' : 'Rollback Commands'}</p>
                          <p className="text-[12px] text-[var(--ui-fg-muted)]">{zh ? '无' : 'None'}</p>
                        </div>
                      )}
                    </div>
                    </div>
                  </details>
                );
              })()}

              {/* Target Devices */}
              <section className={`${ticketSurfaceClass} p-4`} aria-label={zh ? '目标设备' : 'Target devices'}>
                <h3 className="mb-3 text-[13px] font-semibold text-[var(--ui-fg)]">
                  {zh ? '目标设备' : 'Target devices'} <span className="font-normal text-[var(--ui-fg-muted)]">({selectedOrder.target_devices?.length || 0})</span>
                </h3>
                {selectedOrder.target_devices?.length ? (
                  <ul className="divide-y divide-[var(--ui-border)]">
                    {selectedOrder.target_devices.map((device, index) => (
                      <li key={`${device.ip_address || device.hostname || 'target'}-${index}`} className="flex min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2 first:pt-0 last:pb-0 text-[13px]">
                        <span className="min-w-0 font-medium text-[var(--ui-fg)]">{device.hostname || (zh ? '未命名设备' : 'Unnamed device')}</span>
                        <span className="font-mono text-[12px] text-[var(--ui-fg-muted)]">{device.ip_address || '—'}</span>
                      </li>
                    ))}
                  </ul>
                ) : <p className="text-[13px] text-[var(--ui-fg-muted)]">{zh ? '未配置目标设备。' : 'No target devices are listed.'}</p>}
              </section>

              {/* Commands */}
              <section className={`${ticketSurfaceClass} p-4`} aria-label={zh ? '机器执行命令' : 'Machine execution commands'}>
                <h3 className="mb-3 text-[13px] font-semibold text-[var(--ui-fg)]">{zh ? '机器执行命令' : 'Machine execution commands'}</h3>
                {selectedOrder.commands?.length ? (
                  <div className="overflow-x-auto rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface-muted)] p-3 font-mono text-[12px] leading-5 text-[var(--ui-fg)]">
                    {selectedOrder.commands.map((cmd, i) => (
                      <div key={i} className="flex">
                        <span className="mr-3 w-5 shrink-0 select-none text-right text-[var(--ui-fg-subtle)]">{i + 1}</span>
                        {cmd}
                      </div>
                    ))}
                  </div>
                ) : <p className="text-[13px] text-[var(--ui-fg-muted)]">{zh ? '未记录机器执行命令。' : 'No machine commands are recorded.'}</p>}
              </section>

              {/* Rollback Plan */}
              <section className={`${ticketSurfaceClass} p-4`} aria-label={zh ? '回退方案' : 'Rollback plan'}>
                <h3 className="mb-2 text-[13px] font-semibold text-[var(--ui-fg)]">{zh ? '回退方案' : 'Rollback plan'}</h3>
                <p className="whitespace-pre-wrap text-[13px] leading-5 text-[var(--ui-fg)]">{selectedOrder.rollback_plan || (zh ? '未记录回退方案。' : 'No rollback plan is recorded.')}</p>
              </section>
            </div>
          </div>

          {typeof selectedOrder.result_detail?.result_review_summary === 'string' && selectedOrder.result_detail.result_review_summary && (
            <section className={`${ticketSurfaceClass} p-4`} aria-label={zh ? '实施复核说明' : 'Implementation review summary'}>
              <h3 className="text-[13px] font-semibold text-[var(--ui-fg)]">{zh ? '实施复核说明' : 'Implementation review summary'}</h3>
              <p className="mt-2 whitespace-pre-wrap text-[13px] leading-5 text-[var(--ui-fg)]">{selectedOrder.result_detail.result_review_summary}</p>
            </section>
          )}

          <ChangeOrderWorkflowPanels
            language={language}
            order={selectedOrder}
            currentUser={currentUser}
            users={users}
            readOnly={detailLoading || Boolean(detailError)}
            onAssignment={handleAssignment}
            onVerification={handleVerification}
          />

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
            <ControlSheetPanel
              language={language}
              selectedOrder={selectedOrder}
              currentUser={currentUser}
              onUpload={handleControlSheetUpload}
              onDownload={handleControlSheetDownload}
            />
          )}

          <details className={`${ticketSurfaceClass} overflow-hidden`}>
            <summary className="flex cursor-pointer flex-wrap items-center justify-between gap-2 px-4 py-3.5 hover:bg-[var(--ui-surface-muted)] sm:px-5">
              <span className="inline-flex items-center gap-2 text-[13px] font-semibold text-[var(--ui-fg)]">
                <Clock size={15} className="text-[var(--ui-fg-muted)]" aria-hidden="true" />
                {zh ? '工单活动记录' : 'Order activity'}
              </span>
              <span className="text-[11px] text-[var(--ui-fg-muted)]">
                {timelineLoading ? (zh ? '正在加载…' : 'Loading…') : (zh ? `${timeline.length} 条记录` : `${timeline.length} events`)}
              </span>
            </summary>
            <div className="border-t border-[var(--ui-border)] p-4 sm:p-5">

            {timelineLoading ? (
              <div role="status" className="flex items-center justify-center gap-2 py-8 text-[13px] text-[var(--ui-fg-muted)]">
                <RefreshCw size={16} className="animate-spin" /> {zh ? '加载时间线中…' : 'Loading activity…'}
              </div>
            ) : timeline.length === 0 ? (
              <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[var(--ui-border)] py-8 text-center text-[var(--ui-fg-muted)]">
                <Clock size={22} className="mb-2 text-[var(--ui-fg-subtle)]" aria-hidden="true" />
                <p className="text-[13px]">{zh ? '暂无流程记录' : 'No activity recorded'}</p>
              </div>
            ) : (
              <div className="relative space-y-5 pl-8 before:absolute before:bottom-1 before:left-[11px] before:top-1 before:w-px before:bg-[var(--ui-border)]">
                {[...timeline].reverse().map((evt, idx) => {
                  const isNewest = idx === 0;
                  const isControlSheetUpload = evt.event_type === 'change_order.control_sheet_uploaded';
                  return (
                    <div key={evt.id} className="relative">
                      {/* Dot on the line */}
                      <div className={`absolute -left-[35px] top-1.5 w-6 h-6 rounded-full border-4 border-[var(--ui-surface)] shadow-sm flex items-center justify-center z-10 ${
                        isNewest ? 'bg-[var(--ui-accent)]' : 'bg-[var(--ui-surface-emphasis)]'
                      }`}>
                        {isControlSheetUpload
                          ? <Paperclip size={10} className={isNewest ? 'text-white' : 'text-[var(--ui-fg-muted)]'} />
                          : <div className={`h-1.5 w-1.5 rounded-full ${isNewest ? 'bg-white' : 'bg-[var(--ui-fg-subtle)]'}`} />}
                      </div>

                      <div className={`group transition-all duration-300 ${isNewest ? 'translate-x-1' : ''}`}>
                        <div className="flex flex-wrap items-center gap-3 mb-1.5">
                          <span className={`text-[13px] font-semibold ${isNewest ? 'text-[var(--ui-fg)]' : 'text-[var(--ui-fg-muted)]'}`}>
                            {timelineEventLabel(evt.event_type, language)}
                          </span>
                          <time className="rounded-md bg-[var(--ui-surface-muted)] px-2 py-0.5 font-mono text-[11px] text-[var(--ui-fg-muted)] tabular-nums">
                            {fmtDate(evt.created_at)}
                          </time>
                          <div className="flex items-center gap-1.5 rounded-md border border-[var(--ui-border)] px-2 py-0.5 text-[11px] text-[var(--ui-fg-muted)]">
                            <User size={10} />
                            {evt.actor_username || (zh ? '系统自动化' : 'System')}
                          </div>
                          {isControlSheetUpload && (
                            <span className="inline-flex items-center gap-1 rounded-full border border-[var(--ui-border)] px-2 py-0.5 text-[11px] text-[var(--ui-fg-muted)]">
                              <Paperclip size={9} />
                              {zh ? '附件' : 'Attachment'}
                            </span>
                          )}
                        </div>
                        <div className="rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] p-3">
                          <p className="whitespace-pre-wrap text-[13px] leading-5 text-[var(--ui-fg)]">
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
          </details>
        </div>
      </section>
    </motion.div>
  );
};
