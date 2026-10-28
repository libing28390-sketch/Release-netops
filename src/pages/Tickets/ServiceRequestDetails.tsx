import React, { useState } from 'react';
import { AlertTriangle, ArrowUpRight, CheckCircle2, Link2, LoaderCircle, Play, Send, UserPlus, Users, XCircle, type LucideIcon } from 'lucide-react';
import { ActionButton } from '../../components/ui/ActionIconButton';
import { SelectField, TextField } from '../../components/ui/FormField';
import { TicketDialog, TicketEmptyState, TicketFacts, ticketInputClass, ticketSurfaceClass } from '../../components/tickets/TicketUI';
import type { LinkedChangeOrder, ServiceRequestAction, ServiceRequestDetail, TicketAssignmentGroup, TicketActionPayload } from './types';
import TicketSlaSummary from './TicketSlaSummary';

interface ServiceRequestDetailsProps {
  detail: ServiceRequestDetail | null;
  loading: boolean;
  error: string;
  groups: TicketAssignmentGroup[];
  actionLoading: boolean;
  actionError: string;
  onClose: () => void;
  onRetry: () => void;
  onAction: (action: ServiceRequestAction, payload: TicketActionPayload) => Promise<void>;
  onLinkChangeOrder: (changeOrderNumber: string) => Promise<void>;
  language: string;
}

const statusText = (status: string, zh: boolean): string => ({
  submitted: zh ? '已提交' : 'Submitted',
  pending_approval: zh ? '待审批' : 'Pending approval',
  accepted: zh ? '已受理' : 'Accepted',
  in_progress: zh ? '处理中' : 'In progress',
  waiting_external: zh ? '等待外部资源' : 'Waiting for external work',
  pending_confirmation: zh ? '待确认' : 'Pending confirmation',
  completed: zh ? '已完成' : 'Completed',
  rejected: zh ? '已拒绝' : 'Rejected',
  cancelled: zh ? '已取消' : 'Cancelled',
}[status] || status.replaceAll('_', ' '));

const actionText = (action: ServiceRequestAction, zh: boolean): string => ({
  approve: zh ? '审批通过' : 'Approve',
  reject: zh ? '拒绝申请' : 'Reject',
  assign: zh ? '指派责任组' : 'Assign group',
  claim: zh ? '认领申请' : 'Claim',
  acknowledge: zh ? '确认受理' : 'Acknowledge',
  start: zh ? '开始处理' : 'Start work',
  wait_external: zh ? '等待外部资源' : 'Wait for external work',
  resume: zh ? '恢复处理' : 'Resume work',
  deliver: zh ? '提交交付结果' : 'Submit delivery',
  confirm_complete: zh ? '确认完成' : 'Confirm completion',
  return: zh ? '退回修改' : 'Return for changes',
  cancel: zh ? '取消申请' : 'Cancel request',
})[action];

const actionIcon = (action: ServiceRequestAction): LucideIcon => action === 'approve' || action === 'confirm_complete'
  ? CheckCircle2
  : action === 'reject' || action === 'cancel' || action === 'return'
    ? XCircle
    : action === 'start' || action === 'resume'
      ? Play
      : action === 'assign'
        ? Users
        : action === 'claim'
          ? UserPlus
          : Send;

const actionVariant = (action: ServiceRequestAction): 'default' | 'danger' | 'success' | 'primary' => {
  if (action === 'reject' || action === 'cancel' || action === 'return') return 'danger';
  if (action === 'approve' || action === 'confirm_complete') return 'success';
  if (action === 'start' || action === 'resume' || action === 'deliver') return 'primary';
  return 'default';
};

const valueText = (value: unknown): string => {
  if (typeof value === 'string') return value;
  if (value == null) return '';
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
};

const ServiceRequestDetails: React.FC<ServiceRequestDetailsProps> = ({ detail, loading, error, groups, actionLoading, actionError, onClose, onRetry, onAction, onLinkChangeOrder, language }) => {
  const zh = language === 'zh';
  const [activeAction, setActiveAction] = useState<ServiceRequestAction | null>(null);
  const [groupId, setGroupId] = useState('');
  const [reason, setReason] = useState('');
  const [summary, setSummary] = useState('');
  const [evidence, setEvidence] = useState('');
  const [changeOrderNumber, setChangeOrderNumber] = useState('');
  const [linkLoading, setLinkLoading] = useState(false);
  const [linkError, setLinkError] = useState('');
  const request = detail?.request;
  const allowedActions = request?.allowed_actions || [];
  const workflowActions = allowedActions.filter((action) => action !== 'link_change_order');
  const linkedChangeOrders: LinkedChangeOrder[] = detail?.linked_change_orders || [];

  const submitAction = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!activeAction || actionLoading) return;
    const payload: TicketActionPayload = {};
    if (activeAction === 'assign') {
      if (!groupId) return;
      payload.assignment_group_id = groupId;
    }
    if (['reject', 'return', 'cancel'].includes(activeAction)) {
      if (!reason.trim()) return;
      payload.reason = reason.trim();
    }
    if (activeAction === 'deliver' || activeAction === 'confirm_complete') {
      if (activeAction === 'deliver' && !summary.trim()) return;
      if (summary.trim()) payload.summary = summary.trim();
      if (evidence.trim()) payload.evidence = evidence.trim();
    }
    await onAction(activeAction, payload);
    setActiveAction(null);
    setGroupId('');
    setReason('');
    setSummary('');
    setEvidence('');
  };

  const submitChangeOrderLink = async (event: React.FormEvent) => {
    event.preventDefault();
    const number = changeOrderNumber.trim();
    if (!number || linkLoading) return;
    setLinkLoading(true);
    setLinkError('');
    try {
      await onLinkChangeOrder(number);
      setChangeOrderNumber('');
    } catch (cause) {
      setLinkError(cause instanceof Error ? cause.message : (zh ? '关联变更单失败' : 'Unable to link change order'));
    } finally {
      setLinkLoading(false);
    }
  };

  const title = request?.title || (loading ? (zh ? '正在加载申请…' : 'Loading request…') : (zh ? '服务申请详情' : 'Service request details'));
  const description = request?.request_number || request?.ticket_key || '';
  const activeGroups = groups.filter((group) => group.active !== false);
  const factItems = request ? [
    { label: zh ? '状态' : 'Status', value: <span className="inline-flex rounded-full bg-[var(--ui-surface-muted)] px-2 py-0.5 text-[var(--ui-text-caption)] font-semibold text-[var(--ui-fg)]">{statusText(request.status, zh)}</span> },
    { label: zh ? '优先级' : 'Priority', value: request.priority || '—' },
    { label: zh ? '申请人' : 'Requester', value: request.requester_username || '—' },
    { label: zh ? '当前处理人' : 'Current owner', value: request.current_owner_username || request.assignment_group_name || (zh ? '未分配' : 'Unassigned') },
    { label: zh ? '创建时间' : 'Created', value: request.created_at ? new Date(request.created_at).toLocaleString(zh ? 'zh-CN' : 'en-US') : '—' },
  ] : [];

  return (
    <TicketDialog
      title={title}
      description={description}
      onClose={onClose}
      closeDisabled={actionLoading || linkLoading}
      language={language}
      widthClassName="max-w-5xl"
      className="!max-h-[94vh]"
      actions={null}
      bodyClassName="space-y-4"
    >
      {loading && !detail && <p role="status" className="flex items-center justify-center gap-2 py-8 text-[var(--ui-text-body)] text-[var(--ui-fg-muted)]"><LoaderCircle size={15} className="animate-spin" />{zh ? '正在加载服务申请详情…' : 'Loading service request details…'}</p>}
      {error && <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[var(--ui-danger)] bg-[var(--ui-danger-subtle)] px-3 py-2 text-[var(--ui-text-body)] text-[var(--ui-danger)]"><span>{error}</span><ActionButton onClick={onRetry}>{zh ? '重试' : 'Retry'}</ActionButton></div>}
      {!loading && !detail && !error && <TicketEmptyState compact title={zh ? '没有可显示的申请详情' : 'Request details are unavailable'} />}

      {request && detail && <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1.45fr)_minmax(260px,.8fr)]">
        <div className="min-w-0 space-y-4">
          <section className={`${ticketSurfaceClass} p-3.5`}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0"><p className="text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">{request.catalog_snapshot?.name || (zh ? '服务申请' : 'Service request')} · {request.priority || '—'}</p><p className="mt-1 break-words text-[var(--ui-text-body)] leading-5 text-[var(--ui-fg)]">{request.catalog_snapshot?.description || (zh ? '暂无服务说明。' : 'No service description.')}</p></div>
            </div>
            <TicketFacts items={factItems} className="mt-3 border-t border-[var(--ui-border)] pt-3" />
            {Object.entries(request.details || {}).length > 0 && <dl className="mt-3 grid gap-x-4 gap-y-2 border-t border-[var(--ui-border)] pt-3 text-[var(--ui-text-body)] sm:grid-cols-[minmax(120px,.45fr)_minmax(0,1fr)]">{Object.entries(request.details || {}).map(([key, value]) => <React.Fragment key={key}><dt className="break-words text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">{request.catalog_snapshot?.request_schema?.fields?.find((field) => field.key === key)?.label || key}</dt><dd className="whitespace-pre-wrap break-words text-[var(--ui-fg)]">{valueText(value) || '—'}</dd></React.Fragment>)}</dl>}
          </section>

          <TicketSlaSummary sla={detail.sla} language={language} />

          <section className={`${ticketSurfaceClass} p-3.5`}>
            <div className="mb-2 flex items-center gap-2"><Link2 size={14} className="text-[var(--ui-fg-muted)]" aria-hidden="true" /><h3 className="text-[var(--ui-text-label)] font-semibold text-[var(--ui-fg)]">{zh ? '关联变更单' : 'Linked change orders'}</h3></div>
            {linkedChangeOrders.length ? <ul className="divide-y divide-[var(--ui-border)]">{linkedChangeOrders.map((order) => <li key={order.id} className="flex min-w-0 items-center justify-between gap-3 py-2 first:pt-0 text-[var(--ui-text-body)]"><span className="min-w-0 break-words font-semibold text-[var(--ui-fg)]">{order.order_number || order.id}{order.title ? ` · ${order.title}` : ''}</span><span className="shrink-0 text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">{order.status || '—'}</span></li>)}</ul> : <p className="text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">{zh ? '暂无关联变更单。' : 'No linked change orders.'}</p>}
            {allowedActions.includes('link_change_order') && <form onSubmit={submitChangeOrderLink} className="mt-3 border-t border-[var(--ui-border)] pt-3">
              <div className="flex flex-wrap items-end gap-2">
                <label className="min-w-[220px] flex-1 text-[var(--ui-text-label)] font-medium text-[var(--ui-fg-muted)]">{zh ? '关联已创建的变更单编号' : 'Link an existing change order'}<input value={changeOrderNumber} onChange={(event) => setChangeOrderNumber(event.target.value)} maxLength={120} placeholder={zh ? '例如：CO-2026-001' : 'e.g. CO-2026-001'} disabled={linkLoading} className={ticketInputClass} /></label>
                <ActionButton type="submit" disabled={!changeOrderNumber.trim() || linkLoading} icon={linkLoading ? LoaderCircle : Link2} iconClassName={linkLoading ? 'animate-spin' : undefined}>{zh ? '关联' : 'Link'}</ActionButton>
              </div>
              <p className="mt-2 flex items-start gap-1.5 text-[var(--ui-text-caption)] leading-4 text-[var(--ui-fg-muted)]"><ArrowUpRight size={12} className="mt-0.5 shrink-0" aria-hidden="true" />{zh ? '配置修改仍需在变更管理中创建并完成审批。这里仅关联已有变更单。' : 'Configuration changes must use the existing change approval flow. This only links an existing change order.'}</p>
              {linkError && <p role="alert" className="mt-2 text-[var(--ui-text-body)] text-[var(--ui-danger)]">{linkError}</p>}
            </form>}
          </section>

          <section className={`${ticketSurfaceClass} p-3.5`}>
            <h3 className="mb-3 text-[var(--ui-text-label)] font-semibold text-[var(--ui-fg)]">{zh ? '处理记录' : 'Activity'}</h3>
            {detail.events.length ? <ol className="space-y-0">{detail.events.map((event) => <li key={event.id} className="relative border-l border-[var(--ui-border)] pb-3 pl-3 last:border-l-transparent last:pb-0"><span className="absolute -left-[4px] top-1 h-2 w-2 rounded-full bg-[var(--ui-accent)]" aria-hidden="true" /><p className="break-words text-[var(--ui-text-body)] font-medium text-[var(--ui-fg)]">{event.summary || event.event_type.replaceAll('_', ' ')}</p><p className="mt-0.5 text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">{event.actor_username || (zh ? '系统' : 'System')} · {event.created_at ? new Date(event.created_at).toLocaleString(zh ? 'zh-CN' : 'en-US') : '—'}</p>{event.evidence && <pre className="mt-1 whitespace-pre-wrap break-words text-[var(--ui-text-caption)] leading-4 text-[var(--ui-fg-muted)]">{valueText(event.evidence)}</pre>}</li>)}</ol> : <p className="text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">{zh ? '暂无处理记录。' : 'No activity yet.'}</p>}
          </section>
        </div>

        <aside className="min-w-0 space-y-4">
          <section className={`${ticketSurfaceClass} p-3.5`}>
            <div className="mb-3 flex items-center gap-2"><Users size={14} className="text-[var(--ui-fg-muted)]" aria-hidden="true" /><h3 className="text-[var(--ui-text-label)] font-semibold text-[var(--ui-fg)]">{zh ? '下一步操作' : 'Next action'}</h3></div>
            {workflowActions.length ? <div className="flex flex-wrap gap-2">{workflowActions.map((action) => <ActionButton key={action} type="button" size="sm" variant={actionVariant(action as ServiceRequestAction)} icon={actionIcon(action as ServiceRequestAction)} onClick={() => { setActiveAction(action as ServiceRequestAction); setGroupId(request.assignment_group_id || ''); setReason(''); setSummary(''); setEvidence(''); }}>{actionText(action as ServiceRequestAction, zh)}</ActionButton>)}</div> : allowedActions.includes('link_change_order') ? <p className="text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">{zh ? '可在详情中的关联变更单区域关联已有单据。' : 'Use the linked change order section to associate an existing order.'}</p> : <p className="text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">{zh ? '当前账号没有可执行操作。' : 'No actions are available to this account.'}</p>}

            {activeAction && <form onSubmit={submitAction} className="mt-3 space-y-3 border-t border-[var(--ui-border)] pt-3">
              <h4 className="text-[var(--ui-text-body)] font-semibold text-[var(--ui-fg)]">{actionText(activeAction, zh)}</h4>
              {activeAction === 'assign' && <SelectField label={zh ? '责任组' : 'Assignment group'} value={groupId} onChange={setGroupId} options={activeGroups.map((group) => ({ value: group.id, label: group.name }))} language={zh ? 'zh' : 'en'} placeholder={zh ? '选择责任组' : 'Select a group'} disabled={actionLoading} helperText={activeGroups.length === 0 ? (zh ? '当前没有可指派的责任组。' : 'No active assignment groups are available.') : undefined} helperTone="warning" />}
              {['reject', 'return', 'cancel'].includes(activeAction) && <label className="block text-[var(--ui-text-label)] font-medium text-[var(--ui-fg-muted)]">{zh ? '原因' : 'Reason'}<textarea required value={reason} onChange={(event) => setReason(event.target.value)} rows={2} disabled={actionLoading} className={`${ticketInputClass} py-2`} /></label>}
              {(activeAction === 'deliver' || activeAction === 'confirm_complete') && <><TextField label={zh ? '处理摘要' : 'Summary'} value={summary} onChange={setSummary} multiline rows={3} disabled={actionLoading} helperText={activeAction === 'deliver' ? (zh ? '提交交付时必填。' : 'Required when submitting delivery.') : undefined} /><TextField label={zh ? '交付证据' : 'Delivery evidence'} value={evidence} onChange={setEvidence} multiline rows={2} disabled={actionLoading} /></>}
              {actionError && <p role="alert" className="text-[var(--ui-text-body)] text-[var(--ui-danger)]">{actionError}</p>}
              <div className="flex justify-end gap-2"><ActionButton onClick={() => setActiveAction(null)} disabled={actionLoading}>{zh ? '返回' : 'Back'}</ActionButton><ActionButton type="submit" variant="primary" disabled={actionLoading || (activeAction === 'assign' && !groupId) || (activeAction === 'deliver' && !summary.trim())} icon={actionLoading ? LoaderCircle : Send} iconClassName={actionLoading ? 'animate-spin' : undefined}>{zh ? '提交' : 'Submit'}</ActionButton></div>
            </form>}
            {!activeAction && actionError && <p role="alert" className="mt-3 rounded-lg border border-[var(--ui-danger)] bg-[var(--ui-danger-subtle)] px-3 py-2 text-[var(--ui-text-body)] text-[var(--ui-danger)]">{actionError}</p>}
            {request.status === 'pending_confirmation' && <p className="mt-3 flex items-start gap-2 rounded-lg bg-[var(--ui-warning-subtle)] px-2.5 py-2 text-[var(--ui-text-caption)] leading-4 text-[var(--ui-warning)]"><AlertTriangle size={13} className="mt-0.5 shrink-0" aria-hidden="true" />{zh ? '交付后需由申请人确认，确认前申请不会关闭。' : 'The requester must confirm delivery before the request is closed.'}</p>}
          </section>
        </aside>
      </div>}
    </TicketDialog>
  );
};

export default ServiceRequestDetails;
