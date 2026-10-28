import React, { useEffect, useMemo, useState } from 'react';
import { ArrowRightLeft, CheckCircle2, ClipboardCheck } from 'lucide-react';
import type { SessionUser, User as UserOption } from '../../../types';
import type { AssignmentAction, AssignmentEvent, ChangeOrder, VerificationRecord } from '../types';
import { TicketFacts, ticketInputClass, ticketSurfaceClass } from '../../../components/tickets/TicketUI';
import {
  fmtDate,
  getAssignedImplementer,
  getAssignmentEvents,
  getBusinessConfirmer,
  getCurrentVerificationRecords,
  getVerificationReadiness,
  getLatestVerification,
  hasActiveApprovalSnapshot,
  getVerificationRecords,
  isBusinessVerifier,
  isChangeOrderFinalApprover,
  isChangeOrderImplementer,
  isChangeOrderRequester,
  isEligibleChangeOrderExecutor,
  isEligibleImplementer,
} from '../helpers';

export type AssignmentRequest = {
  action: AssignmentAction;
  implementer_id?: string;
  reason?: string;
};

export type VerificationRequest = {
  kind: VerificationRecord['kind'];
  result: VerificationRecord['result'];
  summary: string;
  evidence?: string;
};

export type ChangeOrderMutationResult =
  | { success: true; order: ChangeOrder }
  | { success: false; message: string };

interface Props {
  language: string;
  order: ChangeOrder;
  currentUser: SessionUser;
  users: UserOption[];
  readOnly?: boolean;
  onAssignment: (orderId: string, request: AssignmentRequest) => Promise<ChangeOrderMutationResult>;
  onVerification: (orderId: string, request: VerificationRequest) => Promise<ChangeOrderMutationResult>;
}

const editableAssignmentStatuses = new Set(['initial_review', 'final_review', 'approved', 'implementing', 'executing']);
const verificationStatuses = new Set(['implementing', 'executing', 'failed', 'rollback_in_progress', 'rolled_back']);

const personText = (username?: string, id?: string, fallback = '—') => username || id || fallback;

const latestHandoff = (events: AssignmentEvent[]): AssignmentEvent | undefined =>
  [...events].reverse().find(event => Boolean(event.reason || event.action === 'transfer'));

const errorMessage = (message: string, zh: boolean) =>
  message || (zh ? '请求失败，请稍后重试。' : 'Request failed. Please try again.');

export const ChangeOrderWorkflowPanels: React.FC<Props> = ({
  language,
  order,
  currentUser,
  users,
  readOnly = false,
  onAssignment,
  onVerification,
}) => {
  const zh = language === 'zh';
  const implementer = getAssignedImplementer(order);
  const confirmer = getBusinessConfirmer(order);
  const coReviewer = {
    id: String(order.control_sheet?.co_reviewer?.id || order.control_sheet?.co_reviewer_id || ''),
    username: String(order.control_sheet?.co_reviewer?.username || order.control_sheet?.co_reviewer_username || ''),
  };
  const assignmentEvents = getAssignmentEvents(order);
  const lastHandoff = latestHandoff(assignmentEvents);
  const verificationRecords = getVerificationRecords(order);
  const readiness = getVerificationReadiness(order);
  const hasApprovalSnapshot = hasActiveApprovalSnapshot(order);
  const hasImplementer = Boolean(implementer.id || implementer.username);
  const isRequester = isChangeOrderRequester(order, currentUser);
  const isFinalApprover = isChangeOrderFinalApprover(order, currentUser);
  const isAssignedImplementer = isChangeOrderImplementer(order, currentUser);
  const isAdministrator = currentUser.role === 'Administrator';
  const executionAlreadyStarted = order.status === 'implementing' && Boolean(order.result_detail?.execution_started_at);
  const canManageAssignment = !readOnly && editableAssignmentStatuses.has(order.status)
    && !executionAlreadyStarted
    && !isFinalApprover
    && (isRequester || isAdministrator || isAssignedImplementer);
  const canClaim = !readOnly && editableAssignmentStatuses.has(order.status)
    && !executionAlreadyStarted
    && !hasImplementer
    && !isFinalApprover
    && isEligibleChangeOrderExecutor(currentUser);

  const eligibleCandidates = useMemo(() => {
    return users
      .filter(user => isEligibleImplementer(user, order))
      .filter(user => String(user.id) !== String(implementer.id || ''));
  }, [users, order, implementer.id]);

  const [targetId, setTargetId] = useState(implementer.id || '');
  const [assignmentReason, setAssignmentReason] = useState('');
  const [assignmentBusy, setAssignmentBusy] = useState(false);
  const [assignmentError, setAssignmentError] = useState('');
  const [assignmentMessage, setAssignmentMessage] = useState('');
  const [verificationError, setVerificationError] = useState('');
  const [verificationBusy, setVerificationBusy] = useState<VerificationRecord['kind'] | null>(null);
  const [forms, setForms] = useState<Record<VerificationRecord['kind'], { result: VerificationRecord['result']; summary: string; evidence: string }>>({
    technical: { result: 'passed', summary: '', evidence: '' },
    business: { result: 'passed', summary: '', evidence: '' },
  });

  useEffect(() => {
    setTargetId(implementer.id || '');
    setAssignmentReason('');
    setAssignmentError('');
    setAssignmentMessage('');
    setVerificationError('');
    setForms({
      technical: { result: 'passed', summary: '', evidence: '' },
      business: { result: 'passed', summary: '', evidence: '' },
    });
  }, [order.id, implementer.id]);

  const updateForm = (kind: VerificationRecord['kind'], field: 'result' | 'summary' | 'evidence', value: string) => {
    setForms(current => {
      if (field === 'result') return { ...current, [kind]: { ...current[kind], result: value as VerificationRecord['result'] } };
      if (field === 'summary') return { ...current, [kind]: { ...current[kind], summary: value } };
      return { ...current, [kind]: { ...current[kind], evidence: value } };
    });
  };

  const submitAssignment = async (action: AssignmentAction) => {
    if (action !== 'claim' && !targetId) return;
    if (action === 'transfer' && !assignmentReason.trim()) return;
    setAssignmentBusy(true);
    setAssignmentError('');
    setAssignmentMessage('');
    try {
      const result = await onAssignment(order.id, {
        action,
        ...(action === 'claim' ? {} : { implementer_id: targetId }),
        ...(assignmentReason.trim() ? { reason: assignmentReason.trim() } : {}),
      });
      if (result.success === false) {
        setAssignmentError(errorMessage(result.message, zh));
        return;
      }
      setAssignmentMessage(zh ? '责任分工已更新。' : 'Assignment updated.');
      setAssignmentReason('');
      setTargetId(getAssignedImplementer(result.order).id || '');
    } catch (error) {
      setAssignmentError(error instanceof Error ? error.message : errorMessage('', zh));
    } finally {
      setAssignmentBusy(false);
    }
  };

  const submitVerification = async (kind: VerificationRecord['kind']) => {
    const form = forms[kind];
    if (!form.summary.trim()) return;
    setVerificationBusy(kind);
    setVerificationError('');
    try {
      const result = await onVerification(order.id, {
        kind,
        result: form.result,
        summary: form.summary.trim(),
        ...(form.evidence.trim() ? { evidence: form.evidence.trim() } : {}),
      });
      if (result.success === false) {
        setVerificationError(errorMessage(result.message, zh));
        return;
      }
      setForms(current => ({ ...current, [kind]: { ...current[kind], summary: '', evidence: '' } }));
    } catch (error) {
      setVerificationError(error instanceof Error ? error.message : errorMessage('', zh));
    } finally {
      setVerificationBusy(null);
    }
  };

  const renderVerificationCard = (kind: VerificationRecord['kind']) => {
    const isTechnical = kind === 'technical';
    const applicable = isTechnical || readiness.businessApplicable;
    const records = verificationRecords.filter(record => record.kind === kind);
    const currentRecordIds = new Set(getCurrentVerificationRecords(order).filter(record => record.kind === kind));
    const latest = getLatestVerification(order, kind);
    const canSubmit = !readOnly && hasApprovalSnapshot && (isTechnical
      ? !isAssignedImplementer && verificationStatuses.has(order.status)
      : isBusinessVerifier(order, currentUser) && verificationStatuses.has(order.status));
    const form = forms[kind];
    const label = isTechnical ? (zh ? '技术验证' : 'Technical verification') : (zh ? '业务验证' : 'Business verification');
    const verifierHint = isTechnical
      ? (zh ? '由非实施人提交' : 'Submitted by someone other than the implementer')
      : (zh ? '由申请人或指定确认人提交' : 'Submitted by the requester or designated confirmer');
    const previousRecords = records.filter((record) => record !== latest);
    const stateClass = !applicable
      ? 'border-[var(--ui-border)] bg-[var(--ui-surface-muted)] text-[var(--ui-fg-muted)]'
      : latest?.result === 'passed'
        ? 'border-[var(--ui-success)]/30 bg-[var(--ui-success-subtle)] text-[var(--ui-success)]'
        : latest?.result === 'failed'
          ? 'border-[var(--ui-danger)]/30 bg-[var(--ui-danger-subtle)] text-[var(--ui-danger)]'
          : 'border-[var(--ui-warning)]/30 bg-[var(--ui-warning-subtle)] text-[var(--ui-warning)]';

    return (
      <section key={kind} aria-label={label} className={`${ticketSurfaceClass} min-w-0 p-3.5`}>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h4 className="text-[13px] font-semibold text-[var(--ui-fg)]">{label}</h4>
            <p className="mt-0.5 text-[11px] leading-4 text-[var(--ui-fg-muted)]">{applicable ? verifierHint : (zh ? '未配置业务验证要求' : 'No business verification requirement configured')}</p>
          </div>
          <span className={`inline-flex min-h-6 items-center rounded-full border px-2.5 py-1 text-[11px] font-semibold ${stateClass}`}>
            {!applicable ? (zh ? '不适用' : 'Not applicable') : latest?.result === 'passed' ? (zh ? '已通过' : 'Passed') : latest?.result === 'failed' ? (zh ? '未通过' : 'Failed') : (zh ? '待验证' : 'Pending')}
          </span>
        </div>

        {latest && (
          <div className="mt-3 rounded-lg bg-[var(--ui-surface-muted)] p-3">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-[var(--ui-fg-muted)]">
              <span className="font-medium text-[var(--ui-fg)]">{latest.verifier_username || latest.actor_username || (zh ? '未知验证人' : 'Unknown verifier')}</span>
              {latest.created_at && <time className="tabular-nums">{fmtDate(latest.created_at)}</time>}
            </div>
            <p className="mt-1.5 whitespace-pre-wrap text-[13px] leading-5 text-[var(--ui-fg)]">{latest.summary}</p>
            {latest.evidence && <p className="mt-1.5 whitespace-pre-wrap text-[11px] leading-4 text-[var(--ui-fg-muted)]">{zh ? '证据：' : 'Evidence: '}{latest.evidence}</p>}
          </div>
        )}

        {previousRecords.length > 0 && (
          <details className="mt-3 border-t border-[var(--ui-border)] pt-2">
            <summary className="cursor-pointer text-[11px] font-medium text-[var(--ui-fg-muted)] hover:text-[var(--ui-fg)]">
              {zh ? `历史验证记录（${previousRecords.length}）` : `Previous verification records (${previousRecords.length})`}
            </summary>
            <ol className="mt-2 space-y-2">
              {previousRecords.map((record, index) => (
                <li key={record.id || `${kind}-${record.created_at || index}`} className="rounded-lg border border-[var(--ui-border)] px-3 py-2.5">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-[var(--ui-fg-muted)]">
                    <span className={currentRecordIds.has(record) ? 'font-semibold text-[var(--ui-fg)]' : 'font-semibold text-[var(--ui-warning)]'}>
                      {record.result === 'passed' ? (zh ? '通过' : 'Passed') : (zh ? '未通过' : 'Failed')}
                    </span>
                    {!currentRecordIds.has(record) && <span>{zh ? '历史审批版本' : 'Previous approval version'}</span>}
                    <span>{record.verifier_username || record.actor_username || (zh ? '未知验证人' : 'Unknown verifier')}</span>
                    {record.created_at && <time>{fmtDate(record.created_at)}</time>}
                  </div>
                  <p className="mt-1 whitespace-pre-wrap text-[13px] leading-5 text-[var(--ui-fg)]">{record.summary}</p>
                  {record.evidence && <p className="mt-1 whitespace-pre-wrap text-[11px] leading-4 text-[var(--ui-fg-muted)]">{zh ? '证据：' : 'Evidence: '}{record.evidence}</p>}
                </li>
              ))}
            </ol>
          </details>
        )}

        {applicable && canSubmit && (
          <details className="mt-3 border-t border-[var(--ui-border)] pt-2">
            <summary className="cursor-pointer text-[11px] font-semibold text-[var(--ui-accent)] hover:text-[var(--ui-accent-hover)]">
              {zh ? '登记验证结果' : 'Record verification result'}
            </summary>
            <div className="mt-3 grid gap-3">
              <fieldset className="flex flex-wrap gap-3" aria-label={`${label} result`}>
                {(['passed', 'failed'] as const).map(result => (
                  <label key={result} className="inline-flex min-h-8 items-center gap-2 text-[13px] text-[var(--ui-fg)]">
                    <input type="radio" name={`verification-${order.id}-${kind}`} value={result} checked={form.result === result} onChange={() => updateForm(kind, 'result', result)} />
                    {result === 'passed' ? (zh ? '通过' : 'Passed') : (zh ? '未通过' : 'Failed')}
                  </label>
                ))}
              </fieldset>
              <label className="block text-[12px] font-medium text-[var(--ui-fg-muted)]" htmlFor={`${kind}-verification-summary-${order.id}`}>
                {zh ? '验证摘要' : 'Verification summary'} <span className="text-[var(--ui-danger)]">*</span>
                <textarea
                  id={`${kind}-verification-summary-${order.id}`}
                  aria-label={`${label} summary`}
                  rows={2}
                  value={form.summary}
                  onChange={event => updateForm(kind, 'summary', event.target.value)}
                  placeholder={zh ? '填写验证结果和观察到的情况' : 'Describe the result and what you observed'}
                  className={`${ticketInputClass} mt-1.5 resize-y`}
                />
              </label>
              <label className="block text-[12px] font-medium text-[var(--ui-fg-muted)]" htmlFor={`${kind}-verification-evidence-${order.id}`}>
                {zh ? '证据或关联记录' : 'Evidence or reference'}
                <textarea
                  id={`${kind}-verification-evidence-${order.id}`}
                  aria-label={`${label} evidence`}
                  rows={2}
                  value={form.evidence}
                  onChange={event => updateForm(kind, 'evidence', event.target.value)}
                  placeholder={zh ? '可填写命令输出、监测结果或相关工单号' : 'Command output, monitoring result, or related ticket'}
                  className={`${ticketInputClass} mt-1.5 resize-y`}
                />
              </label>
              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={() => void submitVerification(kind)}
                  disabled={!form.summary.trim() || verificationBusy !== null}
                  className="inline-flex min-h-9 items-center gap-1.5 rounded-lg bg-[var(--ui-accent)] px-3.5 text-[13px] font-semibold text-white hover:bg-[var(--ui-accent-hover)] disabled:cursor-not-allowed disabled:opacity-45"
                >
                  <CheckCircle2 size={14} />
                  {verificationBusy === kind ? (zh ? '提交中…' : 'Saving…') : (zh ? '提交验证结果' : 'Submit result')}
                </button>
              </div>
            </div>
          </details>
        )}

        {applicable && !canSubmit && verificationStatuses.has(order.status) && (
          <p className="mt-2 border-t border-[var(--ui-border)] pt-2 text-[11px] leading-4 text-[var(--ui-fg-muted)]">{!hasApprovalSnapshot
            ? (zh ? '工单缺少有效审批快照，暂不能记录验证。' : 'No active approval snapshot is available for verification.')
            : isTechnical
              ? (zh ? '当前实施人不能提交技术验证。' : 'The implementer cannot submit technical verification.')
              : (zh ? '仅申请人或指定业务确认人可提交。' : 'Only the requester or designated business confirmer can submit.')}</p>
        )}
      </section>
    );
  };

  const handoffText = lastHandoff && [lastHandoff.from_username, lastHandoff.to_username, lastHandoff.implementer_username].some(Boolean)
    ? `${lastHandoff.from_username || lastHandoff.actor_username || '—'} → ${lastHandoff.to_username || lastHandoff.implementer_username || '—'}`
    : lastHandoff?.actor_username || '';

  return (
    <section className={`${ticketSurfaceClass} p-4 sm:p-5`} aria-label={zh ? '责任分工和验证' : 'Assignment and verification'}>
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-[var(--ui-border)] pb-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <span className="mt-0.5 rounded-lg bg-[var(--ui-surface-muted)] p-2 text-[var(--ui-fg-muted)]"><ClipboardCheck size={15} aria-hidden="true" /></span>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-[var(--ui-fg)]">{zh ? '责任分工与结果验证' : 'Responsibility and verification'}</h3>
            <p className="mt-1 text-[11px] leading-4 text-[var(--ui-fg-muted)]">
              {zh ? '审批、实施与业务确认角色及当前验证结果。' : 'Review, implementation, and confirmation roles with the latest verification results.'}
            </p>
          </div>
        </div>
        {canClaim && (
          <button type="button" onClick={() => void submitAssignment('claim')} disabled={assignmentBusy} className="inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 text-[13px] font-semibold text-[var(--ui-fg)] hover:bg-[var(--ui-surface-muted)] disabled:cursor-not-allowed disabled:opacity-50">
            {assignmentBusy ? (zh ? '接手中…' : 'Claiming…') : (zh ? '接手工单' : 'Claim order')}
          </button>
        )}
      </header>

      <TicketFacts
        className="mt-4 gap-y-3"
        items={[
          { label: zh ? '申请人' : 'Requester', value: personText(order.requester_username, order.requester_id) },
          { label: zh ? '实施人' : 'Implementer', value: personText(implementer.username, implementer.id, zh ? '未指定' : 'Unassigned') },
          { label: zh ? '初审人' : 'Initial reviewer', value: personText(order.initial_reviewer_username || order.assigned_initial_reviewer_username, order.initial_reviewer_id || order.assigned_initial_reviewer_id) },
          { label: zh ? '终审人' : 'Final approver', value: personText(order.final_approver_username || order.approver_username || order.assigned_final_approver_username, order.final_approver_id || order.approver_id || order.assigned_final_approver_id) },
          { label: zh ? '复核人' : 'Reviewer', value: personText(coReviewer.username, coReviewer.id) },
          { label: zh ? '业务确认人' : 'Business confirmer', value: personText(confirmer.username, confirmer.id, zh ? '申请人' : 'Requester') },
        ]}
      />

      {lastHandoff && (
        <details className="mt-3 border-t border-[var(--ui-border)] pt-2">
          <summary className="cursor-pointer text-[11px] font-medium text-[var(--ui-fg-muted)] hover:text-[var(--ui-fg)]">{zh ? '查看最近一次交接记录' : 'View most recent handoff'}</summary>
          <p className="mt-2 text-[13px] leading-5 text-[var(--ui-fg)]">
            {handoffText}{lastHandoff.reason ? ` · ${lastHandoff.reason}` : ''}
            {lastHandoff.created_at ? <span className="ml-2 text-[11px] text-[var(--ui-fg-muted)]">{fmtDate(lastHandoff.created_at)}</span> : null}
          </p>
        </details>
      )}

      {(canManageAssignment || executionAlreadyStarted || canClaim) && (
        <div className="mt-3 border-t border-[var(--ui-border)] pt-3">
          {executionAlreadyStarted && <p className="mb-2 text-[11px] leading-4 text-[var(--ui-warning)]">{zh ? '设备操作已开始，当前不能再转派实施人。' : 'Device operations have started; the implementer can no longer be transferred.'}</p>}
          {canManageAssignment && (
            <details>
              <summary className="cursor-pointer text-[12px] font-semibold text-[var(--ui-accent)] hover:text-[var(--ui-accent-hover)]">
                {hasImplementer ? (zh ? '调整实施人' : 'Change implementer') : (zh ? '指定实施人' : 'Assign implementer')}
              </summary>
              <div className="mt-3 grid gap-3 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface-muted)] p-3 sm:grid-cols-2 sm:items-end">
                <label htmlFor={`change-order-implementer-${order.id}`} className="block text-[12px] font-medium text-[var(--ui-fg-muted)]">
                  {zh ? '实施人' : 'Implementer'}
                  <select id={`change-order-implementer-${order.id}`} value={targetId} onChange={event => setTargetId(event.target.value)} className={`${ticketInputClass} mt-1.5`}>
                    <option value="">{zh ? '选择实施人' : 'Select implementer'}</option>
                    {eligibleCandidates.map(user => <option key={user.id} value={String(user.id)}>{user.display_name ? `${user.display_name} (${user.username})` : user.username}</option>)}
                  </select>
                </label>
                <label htmlFor={`change-order-assignment-reason-${order.id}`} className="block text-[12px] font-medium text-[var(--ui-fg-muted)]">
                  {zh ? '交接原因' : 'Handoff reason'}{hasImplementer && <span className="text-[var(--ui-danger)]"> *</span>}
                  <input id={`change-order-assignment-reason-${order.id}`} aria-label={zh ? '交接原因' : 'Handoff reason'} value={assignmentReason} onChange={event => setAssignmentReason(event.target.value)} placeholder={zh ? '转派时必填' : 'Required for transfer'} className={`${ticketInputClass} mt-1.5`} />
                </label>
                <div className="flex flex-wrap items-center gap-2 sm:col-span-2 sm:justify-between">
                  {eligibleCandidates.length === 0 && <p className="text-[11px] text-[var(--ui-warning)]">{zh ? '当前没有可选实施人。' : 'No eligible implementer is available.'}</p>}
                  {isAdministrator && <p className="text-[11px] leading-4 text-[var(--ui-fg-muted)]">{zh ? '管理权限仅用于责任分配，不代表执行授权。' : 'Administrative access manages assignment; it does not grant execution authorization.'}</p>}
                  <button
                    type="button"
                    onClick={() => void submitAssignment(hasImplementer ? 'transfer' : 'assign')}
                    disabled={assignmentBusy || !targetId || (hasImplementer && targetId === implementer.id) || (hasImplementer && !assignmentReason.trim())}
                    className="ml-auto inline-flex min-h-9 items-center gap-1.5 rounded-lg bg-[var(--ui-accent)] px-3.5 text-[13px] font-semibold text-white hover:bg-[var(--ui-accent-hover)] disabled:cursor-not-allowed disabled:opacity-45"
                  >
                    <ArrowRightLeft size={14} />
                    {assignmentBusy ? (zh ? '提交中…' : 'Saving…') : hasImplementer ? (zh ? '转派' : 'Transfer') : (zh ? '指派' : 'Assign')}
                  </button>
                </div>
              </div>
            </details>
          )}
          {canClaim && <p className="mt-2 text-[11px] text-[var(--ui-fg-muted)]">{zh ? '接手后仍需满足审批、实施人与窗口授权要求。' : 'Claiming does not bypass approval, implementer, or execution-window checks.'}</p>}
        </div>
      )}

      {assignmentError && <p role="alert" className="mt-3 rounded-lg border border-[var(--ui-danger)]/30 bg-[var(--ui-danger-subtle)] px-3 py-2 text-[13px] text-[var(--ui-danger)]">{assignmentError}</p>}
      {assignmentMessage && <p role="status" className="mt-3 rounded-lg border border-[var(--ui-success)]/30 bg-[var(--ui-success-subtle)] px-3 py-2 text-[13px] text-[var(--ui-success)]">{assignmentMessage}</p>}

      <div className="mt-4 border-t border-[var(--ui-border)] pt-3">
        <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div>
            <h4 className="text-[13px] font-semibold text-[var(--ui-fg)]">{zh ? '技术与业务验证' : 'Technical and business verification'}</h4>
            <p className="mt-1 text-[11px] leading-4 text-[var(--ui-fg-muted)]">{zh ? '完成前需技术验证通过；已配置业务验证时也需业务确认通过。' : 'Technical verification must pass before completion; configured business verification must also pass.'}</p>
          </div>
          {!readiness.canComplete && (
            <span className="text-[11px] font-medium text-[var(--ui-warning)]">
              {zh ? `完成前还需${readiness.missingKinds.map(kind => kind === 'technical' ? '技术验证' : '业务验证').join('、')}通过。` : `Completion is waiting for ${readiness.missingKinds.join(' and ')} verification.`}
            </span>
          )}
        </div>
        {verificationError && <p role="alert" className="mb-3 rounded-lg border border-[var(--ui-danger)]/30 bg-[var(--ui-danger-subtle)] px-3 py-2 text-[13px] text-[var(--ui-danger)]">{verificationError}</p>}
        <div className="grid gap-3 lg:grid-cols-2">
          {renderVerificationCard('technical')}
          {renderVerificationCard('business')}
        </div>
      </div>
    </section>
  );
};
