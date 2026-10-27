import type { ChangeOrder, ScenarioVariable, ScenarioPhasePreview, WorkflowVisualState, CommandTemplateSnapshot, AssignmentEvent, ChangeOrderPersonRef, VerificationRecord, ResultReviewAction } from './types';
import type { SessionUser, User as UserOption } from '../../types';
import {
  STATUS_META,
  PRIORITY_META,
  ORDER_TYPE_META,
  RISK_META,
  TIMELINE_EVENT_META,
  PRIMARY_WORKFLOW,
  PRIMARY_WORKFLOW_INDEX,
  OPTIONAL_VAR_KEYWORDS,
  ADDRESS_FAMILY_OPTIONS,
} from './constants';

export const fmtTime = (iso: string) => {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  } catch { return iso; }
};

export const fmtDate = (iso: string) => {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  } catch { return iso; }
};

export const statusLabel = (status: string, lang: string) =>
  STATUS_META[status]?.label?.[lang === 'zh' ? 'zh' : 'en'] ?? status;

const MAX_API_MESSAGE_LENGTH = 240;

const safeApiMessageText = (value: unknown): string => typeof value === 'string'
  ? value.replace(/[\u0000-\u001F\u007F]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, MAX_API_MESSAGE_LENGTH)
  : '';

/** Convert API error details into a bounded text value that is safe for UI text nodes. */
export const formatChangeOrderApiMessage = (detail: unknown, lang: string, fallback: string): string => {
  const zh = lang === 'zh';
  const fallbackText = safeApiMessageText(fallback) || (zh ? '操作失败，请稍后重试。' : 'Request failed. Please try again.');
  if (detail instanceof Error) return safeApiMessageText(detail.message) || fallbackText;
  if (typeof detail === 'string') return safeApiMessageText(detail) || fallbackText;
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return fallbackText;

  const record = detail as Record<string, unknown>;
  const code = safeApiMessageText(record.code).toUpperCase();
  if (code === 'RESOURCE_SCOPE_DENIED') {
    const resource = safeApiMessageText(record.resource_type).toLowerCase();
    const action = safeApiMessageText(record.action).toLowerCase();
    if (resource === 'command' && action === 'execute') {
      return zh
        ? '当前账号无权对目标设备执行命令，请联系管理员检查授权。'
        : 'You are not authorized to execute commands on these devices. Ask an administrator to review access.';
    }
    return zh
      ? '当前账号无此资源范围的访问权限，请联系管理员。'
      : 'You are not authorized for this resource scope. Ask an administrator to review access.';
  }

  return safeApiMessageText(record.message) || fallbackText;
};

/** Emergency post-review is recorded only after the change has reached an end state. */
export const canRecordEmergencyPostReview = (
  order: Pick<ChangeOrder, 'order_type' | 'status' | 'actual_end' | 'emergency_review_status' | 'emergency_review_owner_id'>,
  currentUserId: string,
): boolean => Boolean(
  order.order_type === 'emergency'
  && ['completed', 'rolled_back'].includes(order.status)
  && order.actual_end
  && order.emergency_review_status === 'pending'
  && currentUserId
  && order.emergency_review_owner_id === currentUserId,
);

export interface CurrentResponsibility {
  stage: string;
  owner: string;
}

/** Describe the active workflow role from the existing status and assignment fields. */
export const describeCurrentResponsibility = (order: ChangeOrder, lang: string): CurrentResponsibility => {
  const zh = lang === 'zh';
  const requester = order.requester_username || (zh ? '申请人' : 'Requester');
  const controlSheet = (order.control_sheet || {}) as Record<string, unknown>;
  const implementer = controlSheet.implementer && typeof controlSheet.implementer === 'object'
    ? controlSheet.implementer as Record<string, unknown>
    : {};
  const implementerName = String(
    implementer.username || implementer.id || controlSheet.implementer_username || controlSheet.implementer_id || '',
  ).trim();

  switch (order.status) {
    case 'draft':
    case 'rejected':
      return { stage: statusLabel(order.status, lang), owner: requester };
    case 'initial_review':
      return {
        stage: statusLabel(order.status, lang),
        owner: order.assigned_initial_reviewer_username || (zh ? '初审组' : 'Initial review group'),
      };
    case 'final_review':
      return {
        stage: statusLabel(order.status, lang),
        owner: order.assigned_final_approver_username || (zh ? '待指定终审人' : 'Final approver not assigned'),
      };
    case 'approved':
      return {
        stage: statusLabel(order.status, lang),
        owner: implementerName || (zh ? '待指派实施人' : 'Awaiting implementer assignment'),
      };
    case 'implementing':
      return {
        stage: statusLabel(order.status, lang),
        owner: implementerName || (zh ? '未指定实施人' : 'Implementer not assigned'),
      };
    case 'failed':
    case 'rollback_in_progress':
      return { stage: statusLabel(order.status, lang), owner: implementerName || requester };
    case 'implementation_review':
      return { stage: statusLabel(order.status, lang), owner: getResultReviewer(order).username || (zh ? '指定复核人' : 'Assigned reviewer') };
    case 'implementation_result_review':
      return { stage: statusLabel(order.status, lang), owner: order.initial_reviewer_username || order.assigned_initial_reviewer_username || (zh ? '原初审人' : 'Initial reviewer') };
    case 'completed':
    case 'rolled_back':
    case 'cancelled':
      return { stage: statusLabel(order.status, lang), owner: '—' };
    case 'pending':
      return { stage: statusLabel(order.status, lang), owner: order.approver_username || (zh ? '审批组待处理' : 'Approval group') };
    case 'executing':
      return { stage: statusLabel(order.status, lang), owner: requester };
    default:
      return { stage: statusLabel(order.status, lang), owner: '—' };
  }
};

export const getChangeOrderWindowState = (order: Pick<ChangeOrder, 'scheduled_start' | 'scheduled_end'>, now = Date.now()): 'invalid' | 'before' | 'open' | 'ended' => {
  const parse = (value: string) => {
    const raw = (value || '').trim().replace(' ', 'T');
    if (!raw) return Number.NaN;
    // Match the API: offset-free legacy values use Asia/Shanghai wall time.
    return Date.parse(/[zZ]$|[+-]\d{2}:?\d{2}$/.test(raw) ? raw : `${raw}+08:00`);
  };
  const start = parse(order.scheduled_start);
  const end = parse(order.scheduled_end);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start >= end) return 'invalid';
  return now < start ? 'before' : now >= end ? 'ended' : 'open';
};

export const describeNextWorkflowAction = (order: ChangeOrder, lang: string, now = Date.now(), currentUser?: SessionUser): string => {
  const zh = lang === 'zh';
  const implementer = getAssignedImplementer(order);
  const implementerName = implementer.username || (zh ? '指定实施人' : 'assigned implementer');
  switch (normalizeWorkflowStatus(order.status)) {
    case 'draft': return zh ? '等待申请人提交审核' : 'Waiting for requester to submit for review';
    case 'initial_review': return zh
      ? (order.assigned_initial_reviewer_username ? `等待初审人 ${order.assigned_initial_reviewer_username} 审核` : '等待初审人审核')
      : `Waiting for ${order.assigned_initial_reviewer_username || 'initial reviewer'}`;
    case 'final_review': return zh
      ? (order.assigned_final_approver_username ? `等待终审人 ${order.assigned_final_approver_username} 审批` : '等待终审人审批')
      : `Waiting for ${order.assigned_final_approver_username || 'final approver'}`;
    case 'approved': {
      const windowState = getChangeOrderWindowState(order, now);
      if (windowState === 'invalid') return zh ? '实施窗口无效，请调整计划并重新审批' : 'Invalid window. Reschedule and request approval again.';
      if (windowState === 'ended') return zh ? '实施窗口已结束，请调整计划并重新审批' : 'Window ended. Reschedule and request approval again.';
      if (!implementer.id && !implementer.username) return zh ? '请指派实施人' : 'Assign an implementer';
      const assignedUser = { id: implementer.id, username: implementer.username };
      if (currentUserMatches(assignedUser, {
        id: order.assigned_final_approver_id || order.final_approver_id || order.approver_id,
        username: order.assigned_final_approver_username || order.final_approver_username || order.approver_username,
      })) return zh ? '实施人与终审人相同，请调整实施人' : 'Implementer is also the final approver. Reassign the implementer.';
      if (currentUser && isChangeOrderImplementer(order, currentUser) && !isEligibleChangeOrderExecutor(currentUser)) {
        return zh ? '当前账号不符合实施角色要求，请调整实施人' : 'Your account does not meet implementation role requirements. Reassign the implementer.';
      }
      if (windowState === 'before') return zh ? '实施窗口未开始，请到计划开始时间后实施' : 'Window not started. Begin at the scheduled start time.';
      if (currentUser && canCurrentUserImplement(order, currentUser)) return zh ? '窗口内，可进入实施' : 'Window open. Start implementation.';
      return zh ? `窗口内，待 ${implementerName} 进入实施` : `Window open. ${implementerName} to start implementation.`;
    }
    case 'implementing': return zh ? '等待实施与验证结果' : 'Waiting for implementation and verification results';
    case 'implementation_review': return zh ? '待指定复核人审核实施结果' : 'Assigned reviewer to check implementation results';
    case 'implementation_result_review': return zh ? '复核异常，待原初审人确认实施结果' : 'Abnormal results await the original initial reviewer';
    case 'failed': return zh ? '等待责任人处理失败并决定是否回退' : 'Waiting for the owner to handle the failure or roll back';
    case 'rollback_in_progress': return zh ? '等待责任人记录回退结果' : 'Waiting for the owner to record rollback results';
    case 'rejected': return zh ? '等待申请人修改后重新提交' : 'Waiting for requester to revise and resubmit';
    case 'completed':
    case 'rolled_back':
    case 'cancelled': return zh ? '流程已结束' : 'Workflow finished';
    default: return zh ? '等待当前处理人' : 'Waiting for the current owner';
  }
};

export const getNextWorkflowAction = (
  order: ChangeOrder,
  actions: Array<{ status: string; label: string; disabled?: boolean; disabledReason?: string }>,
  lang: string,
  now = Date.now(),
  currentUser?: SessionUser,
): string => {
  const fallback = describeNextWorkflowAction(order, lang, now, currentUser);
  // Window and assignment restrictions take precedence over a visible action label.
  if (normalizeWorkflowStatus(order.status) === 'approved') return fallback;
  const action = actions.find(action => action.status.startsWith('result_review_')) || actions.find(action => action.status !== 'cancelled');
  return (action?.disabled ? action.disabledReason : action?.label) || fallback;
};

const nonEmptyString = (value: unknown): string => typeof value === 'string' ? value.trim() : '';

export type ImplementerConflictRole = 'co_reviewer' | 'business_confirmer' | 'initial_reviewer' | 'final_approver';

/** Return the first review/confirmation role that conflicts with the implementer. */
export const getImplementerConflictRole = (
  implementerId: unknown,
  assignments: Partial<Record<ImplementerConflictRole, unknown>>,
): ImplementerConflictRole | null => {
  const normalizedImplementerId = nonEmptyString(implementerId);
  if (!normalizedImplementerId) return null;
  const roles: ImplementerConflictRole[] = ['co_reviewer', 'business_confirmer', 'initial_reviewer', 'final_approver'];
  return roles.find((role) => nonEmptyString(assignments[role]) === normalizedImplementerId) || null;
};

/** Prefer a template's explicit rollback commands; otherwise keep the operator's written plan. */
export const resolveChangeOrderRollbackPlan = (
  manualPlan: unknown,
  generatedRollbackCommands: unknown,
): string => {
  const generated = Array.isArray(generatedRollbackCommands)
    ? generatedRollbackCommands.map((command) => String(command ?? '').trim()).filter(Boolean).join('\n')
    : '';
  return generated || nonEmptyString(manualPlan);
};

export const parseRollbackCommands = (value: unknown): string[] =>
  String(value ?? '')
    .split(/\r?\n/)
    .map((command) => command.trim())
    .filter(Boolean);

export const serializeRollbackCommands = (commands: unknown): string =>
  Array.isArray(commands)
    ? commands.map((command) => String(command ?? '').trim()).filter(Boolean).join('\n')
    : '';

export const getMissingChangeOrderControlSheetFields = (controlSheet: unknown): string[] => {
  const values = controlSheet && typeof controlSheet === 'object'
    ? controlSheet as Record<string, unknown>
    : {};
  const requiredFields = [
    'implementer_id',
    'pre_check',
    'execution',
    'post_verify',
    'business_verify',
  ];
  return requiredFields.filter((field) => !String(values[field] ?? '').trim());
};

/** Serialize the same approved rollback plan to the order and its control sheet. */
export const buildChangeOrderRollbackFields = (
  manualPlan: unknown,
  localRollbackCommands: unknown,
  validatedRollbackCommands: unknown,
  controlSheet: Record<string, unknown> = {},
): { rollback_plan: string; control_sheet: Record<string, unknown> } => {
  const rollbackCommands = validatedRollbackCommands !== undefined
    ? (Array.isArray(validatedRollbackCommands) ? validatedRollbackCommands : [])
    : localRollbackCommands;
  const rollbackPlan = resolveChangeOrderRollbackPlan(manualPlan, rollbackCommands);
  return {
    rollback_plan: rollbackPlan,
    control_sheet: { ...controlSheet, rollback_plan: rollbackPlan },
  };
};

const controlSheetRecord = (order: ChangeOrder): Record<string, unknown> =>
  order.control_sheet && typeof order.control_sheet === 'object'
    ? order.control_sheet as Record<string, unknown>
    : {};

const nestedPerson = (value: unknown): ChangeOrderPersonRef => {
  if (!value || typeof value !== 'object') return {};
  const record = value as Record<string, unknown>;
  return {
    id: nonEmptyString(record.id) || undefined,
    username: nonEmptyString(record.username) || undefined,
  };
};

const resolvePerson = (
  order: ChangeOrder,
  nestedKeys: string[],
  flatKeys: { id: string[]; username: string[] },
): ChangeOrderPersonRef => {
  const sheet = controlSheetRecord(order);
  for (const key of nestedKeys) {
    const person = nestedPerson(sheet[key]);
    if (person.id || person.username) return person;
  }
  const id = flatKeys.id.map(key => nonEmptyString(sheet[key])).find(Boolean);
  const username = flatKeys.username.map(key => nonEmptyString(sheet[key])).find(Boolean);
  return { id, username };
};

/** Read the current implementer, preferring the canonical nested control sheet shape. */
export const getAssignedImplementer = (order: ChangeOrder): ChangeOrderPersonRef =>
  resolvePerson(order, ['implementer'], {
    id: ['implementer_id'],
    username: ['implementer_username'],
  });

/** Read the designated business confirmer and tolerate older verifier field names. */
export const getBusinessConfirmer = (order: ChangeOrder): ChangeOrderPersonRef =>
  resolvePerson(order, ['business_confirmer', 'business_verifier'], {
    id: ['business_confirmer_id', 'business_verifier_id'],
    username: ['business_confirmer_username', 'business_verifier_username'],
  });

export const getAssignmentEvents = (order: ChangeOrder): AssignmentEvent[] => {
  const events = order.result_detail?.assignment_events;
  return Array.isArray(events) ? events.filter((event): event is AssignmentEvent => Boolean(event && typeof event === 'object')) : [];
};

export const getVerificationRecords = (order: ChangeOrder): VerificationRecord[] => {
  const records = order.result_detail?.verification_records;
  return Array.isArray(records)
    ? records.filter((record): record is VerificationRecord => Boolean(record && typeof record === 'object' && (record as VerificationRecord).kind && (record as VerificationRecord).result))
    : [];
};

export const getCurrentVerificationRecords = (order: ChangeOrder): VerificationRecord[] => {
  const details = order.result_detail || {};
  const snapshotHash = nonEmptyString(details.approval_snapshot_hash);
  if (!snapshotHash || Number(details.approval_snapshot_version) <= 0) return [];
  return getVerificationRecords(order).filter(record => record.approval_snapshot_hash === snapshotHash);
};

export const hasActiveApprovalSnapshot = (order: ChangeOrder): boolean => {
  const details = order.result_detail || {};
  return Boolean(nonEmptyString(details.approval_snapshot_hash) && Number(details.approval_snapshot_version) > 0);
};

export const getLatestVerification = (order: ChangeOrder, kind: VerificationRecord['kind']): VerificationRecord | undefined =>
  getCurrentVerificationRecords(order).filter(record => record.kind === kind).at(-1);

const currentUserMatches = (user: SessionUser, person: ChangeOrderPersonRef): boolean => {
  const userId = nonEmptyString(user.id);
  const personId = nonEmptyString(person.id);
  if (userId && personId) return userId === personId;
  const username = nonEmptyString(user.username).toLowerCase();
  return Boolean(username && nonEmptyString(person.username).toLowerCase() === username);
};

export const isChangeOrderRequester = (order: ChangeOrder, user: SessionUser): boolean =>
  currentUserMatches(user, { id: order.requester_id, username: order.requester_username });

/** Match the control-sheet upload actor and status rules enforced by the API. */
export const canUploadControlSheetAttachment = (order: ChangeOrder, user: SessionUser): boolean => {
  const uploadableStatus = ['draft', 'initial_review', 'final_review', 'approved', 'implementing'].includes(order.status);
  const executionStarted = nonEmptyString(order.result_detail?.execution_started_at);
  const profile = nonEmptyString(user.role_profile);
  const canUpdateChangeOrder = profile === 'Change Requester' || profile === 'System Administrator'
    || (!profile && user.role !== 'Viewer');
  const uploadActor = user.role === 'Administrator' || isChangeOrderRequester(order, user);
  return uploadableStatus && !executionStarted && canUpdateChangeOrder && uploadActor;
};

export const isChangeOrderInitialReviewer = (order: ChangeOrder, user: SessionUser): boolean =>
  user.role === 'Administrator' && currentUserMatches(user, {
    id: order.assigned_initial_reviewer_id,
    username: order.assigned_initial_reviewer_username,
  });

export const isChangeOrderFinalApprover = (order: ChangeOrder, user: SessionUser): boolean =>
  user.role === 'Administrator' && currentUserMatches(user, {
    id: order.assigned_final_approver_id || order.final_approver_id || order.approver_id,
    username: order.assigned_final_approver_username || order.final_approver_username || order.approver_username,
  });

export const isChangeOrderImplementer = (order: ChangeOrder, user: SessionUser): boolean =>
  currentUserMatches(user, getAssignedImplementer(order));

export const getResultReviewer = (order: ChangeOrder): ChangeOrderPersonRef => {
  const sheet = controlSheetRecord(order);
  const person = nestedPerson(sheet.co_reviewer);
  return { id: person.id || nonEmptyString(sheet.co_reviewer_id), username: person.username || nonEmptyString(sheet.co_reviewer_username) };
};

export const getResultReviewActions = (order: ChangeOrder, user: SessionUser, lang: string): Array<{ action: ResultReviewAction; label: string; disabled?: boolean; disabledReason?: string }> => {
  const zh = lang === 'zh';
  const reviewer = getResultReviewer(order);
  if (!reviewer.id && !reviewer.username) return [];
  if (['implementing', 'failed'].includes(order.status) && canCurrentUserImplement(order, user)) {
    const readiness = getVerificationReadiness(order);
    return [{ action: 'submit', label: zh ? '提交实施复核' : 'Submit results for review', disabled: !readiness.canComplete,
      disabledReason: readiness.canComplete ? undefined : (zh ? '请先完成技术与业务验证' : 'Complete technical and business verification first') }];
  }
  if (isChangeOrderImplementer(order, user)) return [];
  if (order.status === 'implementation_review' && currentUserMatches(user, reviewer)) return [
    { action: 'pass', label: zh ? '复核正常，关单' : 'Accept results and close' },
    { action: 'fail', label: zh ? '复核异常，转初审人' : 'Escalate to initial reviewer' },
  ];
  if (order.status === 'implementation_result_review' && currentUserMatches(user, {
    id: order.initial_reviewer_id || order.assigned_initial_reviewer_id,
    username: order.initial_reviewer_username || order.assigned_initial_reviewer_username,
  })) return [
    { action: 'accept', label: zh ? '确认结果，关单' : 'Confirm results and close' },
    { action: 'reject', label: zh ? '退回实施人处理' : 'Return to implementer' },
  ];
  return [];
};

/** UI gate only; the API remains the authority for execution permission. */
export const isEligibleChangeOrderExecutor = (user: Pick<SessionUser, 'role' | 'role_profile'>): boolean => {
  if (user.role === 'Viewer') return false;
  const roleProfile = nonEmptyString(user.role_profile);
  if (!roleProfile) return user.role === 'Operator';
  return roleProfile === 'Automation Operator' || roleProfile === 'System Administrator';
};

export const canCurrentUserImplement = (order: ChangeOrder, user: SessionUser): boolean =>
  isEligibleChangeOrderExecutor(user)
  && isChangeOrderImplementer(order, user)
  && !isChangeOrderFinalApprover(order, user);

export const getChangeOrderExecutionAuthRole = (user: SessionUser): 'normal' | 'admin' =>
  user.role === 'Administrator' && user.role_profile === 'System Administrator' ? 'admin' : 'normal';

export const hasOrderExecutionRequestBeenSent = (order: ChangeOrder): boolean => {
  const details = order.result_detail || {};
  if (['execution_started_at', 'execution_request_hash'].some(key => Boolean(nonEmptyString(details[key])))) return true;
  return ['execution_results', 'playbook_execution_events'].some(key =>
    Array.isArray(details[key]) && details[key].length > 0,
  );
};

export const clampChangeOrderPage = (page: number, totalItems: number, pageSize: number): number => {
  const safePageSize = Number.isFinite(pageSize) ? Math.max(1, Math.floor(pageSize)) : 1;
  const safePage = Number.isFinite(page) ? Math.max(1, Math.floor(page)) : 1;
  const safeTotalItems = Number.isFinite(totalItems) ? Math.max(0, Math.floor(totalItems)) : 0;
  const totalPages = Math.max(1, Math.ceil(safeTotalItems / safePageSize));
  return Math.min(safePage, totalPages);
};

export const isBusinessVerifier = (order: ChangeOrder, user: SessionUser): boolean =>
  isChangeOrderRequester(order, user) || currentUserMatches(user, getBusinessConfirmer(order));

export interface VerificationReadiness {
  technicalPassed: boolean;
  businessApplicable: boolean;
  businessPassed: boolean;
  canComplete: boolean;
  missingKinds: VerificationRecord['kind'][];
}

export const getVerificationReadiness = (order: ChangeOrder): VerificationReadiness => {
  const technicalPassed = getLatestVerification(order, 'technical')?.result === 'passed';
  const businessConfirmer = getBusinessConfirmer(order);
  const businessInstructions = nonEmptyString(controlSheetRecord(order).business_verify);
  const businessApplicable = Boolean(businessInstructions || businessConfirmer.id || businessConfirmer.username);
  const businessPassed = getLatestVerification(order, 'business')?.result === 'passed';
  const missingKinds: VerificationRecord['kind'][] = [];
  if (!technicalPassed) missingKinds.push('technical');
  if (businessApplicable && !businessPassed) missingKinds.push('business');
  return {
    technicalPassed,
    businessApplicable,
    businessPassed,
    canComplete: missingKinds.length === 0,
    missingKinds,
  };
};

export const isEligibleImplementer = (user: UserOption, order: ChangeOrder): boolean => {
  if (!isEligibleChangeOrderExecutor(user)) return false;
  return !currentUserMatches({ id: user.id, username: user.username }, {
    id: order.assigned_final_approver_id || order.final_approver_id || order.approver_id,
    username: order.assigned_final_approver_username || order.final_approver_username || order.approver_username,
  });
};

export const priorityLabel = (priority: string, lang: string) =>
  PRIORITY_META[priority]?.label?.[lang === 'zh' ? 'zh' : 'en'] ?? priority;

export const typeLabel = (type: string, lang: string) =>
  ORDER_TYPE_META[type]?.label?.[lang === 'zh' ? 'zh' : 'en'] ?? type;

export const riskLabel = (risk: string, lang: string) =>
  RISK_META[risk]?.label?.[lang === 'zh' ? 'zh' : 'en'] ?? risk;

export const hasChangeGroup = (user: UserOption, groupKey: string) =>
  Array.isArray(user.change_groups) && user.change_groups.includes(groupKey);

export const getFinalApproverCandidates = (
  users: UserOption[],
  currentUserId: string,
  requesterId: string,
  implementerId: string,
): UserOption[] => {
  const excludedIds = new Set([currentUserId, requesterId, implementerId].filter(Boolean).map(String));
  return users.filter((user) =>
    user.role === 'Administrator'
    && hasChangeGroup(user, 'final_approver')
    && !excludedIds.has(String(user.id)),
  );
};

export const getInitialReviewerCandidates = (
  users: UserOption[],
  currentUserId: string,
  implementerId: string,
): UserOption[] => {
  const excludedIds = new Set([currentUserId, implementerId].filter(Boolean).map(String));
  return users.filter((user) =>
    user.role === 'Administrator'
    && hasChangeGroup(user, 'initial_reviewer')
    && !excludedIds.has(String(user.id)),
  );
};

export const buildUserOptionLabel = (user: UserOption) =>
  [user.display_name || user.username, user.group_name].filter(Boolean).join(' · ');

export const isCommandTemplateSnapshot = (value: unknown): value is CommandTemplateSnapshot => {
  if (!value || typeof value !== 'object') return false;
  const record = value as Record<string, unknown>;
  return typeof record.scenario_id === 'string' && typeof record.platform === 'string';
};

export const variableLabel = (variable: ScenarioVariable, lang: string) => {
  if (lang === 'zh') return variable.label_zh || variable.label || variable.key;
  return variable.label || variable.key;
};

export const timelineEventLabel = (eventType: string, lang: string) =>
  TIMELINE_EVENT_META[eventType]?.[lang === 'zh' ? 'zh' : 'en'] ?? eventType;

export const translateSummary = (summaryText: string, lang: string) => {
  if (lang !== 'zh' || !summaryText) return summaryText;
  let text = summaryText;
  const statusMap: Record<string, string> = {
    'draft': '草稿',
    'initial_review': '初审中',
    'final_review': '终审中',
    'approved': '审批完成',
    'implementing': '实施中',
    'completed': '完成',
    'rollback_in_progress': '回退中',
    'rolled_back': '已回退',
    'rejected': '已驳回',
    'failed': '执行失败',
    'cancelled': '已取消',
  };
  Object.entries(statusMap).forEach(([k, v]) => {
    text = text.replace(new RegExp(`\\b${k}\\b`, 'g'), v);
  });
  return text;
};

export const fmtFileSize = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

export const normalizeWorkflowStatus = (status: string) => {
  if (status === 'pending') return 'initial_review';
  if (status === 'executing') return 'implementing';
  return status;
};

export const buildWorkflowPresentation = (order: ChangeOrder, lang: string) => {
  const zh = lang === 'zh';
  const details = (order.result_detail || {}) as Record<string, unknown>;
  const normalizedStatus = normalizeWorkflowStatus(order.status);
  const implementingIndex = PRIMARY_WORKFLOW_INDEX.implementing;
  const reviewer = getResultReviewer(order);
  const hasResultReview = Boolean(reviewer.id || reviewer.username);
  const workflow: Array<{key: string; label: {zh: string; en: string}; hint: {zh: string; en: string}}> = [...PRIMARY_WORKFLOW];
  if (hasResultReview) workflow.splice(workflow.length - 1, 0, { key: 'implementation_review', label: { zh: '实施复核', en: 'Result review' }, hint: { zh: '由复核人确认最终实施结果', en: 'Reviewer confirms implementation results' } });
  const indexes = Object.fromEntries(workflow.map((step, index) => [step.key, index]));
  const completedIndex = indexes.completed;
  const states = workflow.map<WorkflowVisualState>(() => 'pending');

  const setDoneBefore = (index: number) => {
    for (let i = 0; i < index; i += 1) states[i] = 'done';
  };

  const formatActorCaption = (label: string, actor: string) => actor ? `${label}${actor}` : '';

  let exception: { tone: 'rose' | 'violet' | 'slate'; label: string; detail: string } | null = null;

  if (normalizedStatus === 'completed') {
    for (let i = 0; i <= completedIndex; i += 1) states[i] = 'done';
  } else if (['implementation_review', 'implementation_result_review'].includes(normalizedStatus)) {
    const index = indexes.implementation_review;
    setDoneBefore(index);
    states[index] = normalizedStatus === 'implementation_result_review' ? 'error' : 'current';
    if (normalizedStatus === 'implementation_result_review') exception = { tone: 'rose', label: zh ? '复核异常' : 'Abnormal result', detail: zh ? '待原初审人审核实施结果，不重新授权命令执行。' : 'The original initial reviewer will decide on results; execution is not reauthorized.' };
  } else if (normalizedStatus === 'rejected') {
    const rejectedStage = typeof details.rejected_stage === 'string'
      ? normalizeWorkflowStatus(details.rejected_stage)
      : 'initial_review';
    const rejectedIndex = indexes[rejectedStage] ?? PRIMARY_WORKFLOW_INDEX.initial_review;
    setDoneBefore(rejectedIndex);
    states[rejectedIndex] = 'error';
    exception = {
      tone: 'rose',
      label: zh ? '审核驳回' : 'Rejected in Review',
      detail: order.rejected_reason || (zh ? '当前工单已在审核阶段被驳回。' : 'This order was rejected during review.'),
    };
  } else if (normalizedStatus === 'rollback_in_progress') {
    setDoneBefore(implementingIndex);
    states[implementingIndex] = 'error';
    exception = {
      tone: 'violet',
      label: zh ? '异常回退中' : 'Rollback in Progress',
      detail: typeof details.rollback_reason === 'string' && details.rollback_reason
        ? details.rollback_reason
        : (zh ? '实施阶段发现异常，正在执行回退。' : 'An issue was found during implementation and rollback is running.'),
    };
  } else if (normalizedStatus === 'rolled_back') {
    setDoneBefore(implementingIndex);
    states[implementingIndex] = 'error';
    exception = {
      tone: 'violet',
      label: zh ? '回退完成' : 'Rollback Completed',
      detail: order.result_summary || (zh ? '异常已处理，变更已成功回退。' : 'Rollback finished and the change was reverted.'),
    };
  } else if (normalizedStatus === 'failed') {
    setDoneBefore(implementingIndex);
    states[implementingIndex] = 'error';
    exception = {
      tone: 'rose',
      label: typeof details.rollback_started_at === 'string' && details.rollback_started_at
        ? (zh ? '回退失败' : 'Rollback Failed')
        : (zh ? '实施失败' : 'Implementation Failed'),
      detail: order.result_summary || (zh ? '变更执行失败，需要人工介入处理。' : 'The change failed and requires manual intervention.'),
    };
  } else if (normalizedStatus === 'cancelled') {
    const cancelStage = order.actual_start
      ? 'implementing'
      : (order.final_approver_username || order.approver_username)
        ? 'approved'
        : order.initial_reviewer_username
          ? 'final_review'
          : 'draft';
    const cancelIndex = indexes[cancelStage] ?? 0;
    setDoneBefore(cancelIndex);
    states[cancelIndex] = 'error';
    exception = {
      tone: 'slate',
      label: zh ? '工单取消' : 'Order Cancelled',
      detail: zh ? '该工单已被人工取消，不再继续执行。' : 'This order was cancelled and will not continue.',
    };
  } else {
    const currentIndex = indexes[normalizedStatus] ?? 0;
    setDoneBefore(currentIndex);
    states[currentIndex] = 'current';
  }

  const steps = workflow.map((step, index) => {
    let caption: string = step.hint[zh ? 'zh' : 'en'];
    if (step.key === 'draft' && order.created_at) {
      caption = zh ? `创建于 ${fmtTime(order.created_at)}` : `Created ${fmtTime(order.created_at)}`;
    }
    if (step.key === 'initial_review' && order.initial_reviewer_username) {
      caption = zh
        ? formatActorCaption('初审人：', order.initial_reviewer_username)
        : formatActorCaption('Initial reviewer: ', order.initial_reviewer_username);
    } else if (step.key === 'initial_review' && order.assigned_initial_reviewer_username) {
      caption = zh
        ? formatActorCaption('指定初审：', order.assigned_initial_reviewer_username)
        : formatActorCaption('Assigned reviewer: ', order.assigned_initial_reviewer_username);
    }
    if (step.key === 'final_review' && (order.final_approver_username || order.approver_username)) {
      const actor = order.final_approver_username || order.approver_username;
      caption = zh
        ? formatActorCaption('终审人：', actor)
        : formatActorCaption('Final approver: ', actor);
    } else if (step.key === 'final_review' && order.assigned_final_approver_username) {
      caption = zh
        ? formatActorCaption('指定终审：', order.assigned_final_approver_username)
        : formatActorCaption('Assigned approver: ', order.assigned_final_approver_username);
    }
    if (step.key === 'approved' && (order.final_approver_username || order.approver_username)) {
      const actor = order.final_approver_username || order.approver_username;
      caption = zh ? `已由 ${actor} 授权实施` : `Authorized by ${actor}`;
    }
    if (step.key === 'implementing' && order.actual_start) {
      caption = zh ? `开始于 ${fmtTime(order.actual_start)}` : `Started ${fmtTime(order.actual_start)}`;
    }
    if (step.key === 'completed' && order.actual_end) {
      caption = zh ? `完成于 ${fmtTime(order.actual_end)}` : `Completed ${fmtTime(order.actual_end)}`;
    }
    return {
      ...step,
      state: states[index],
      caption,
    };
  });

  return { steps, exception };
};

export const inferVariableMeta = (key: string): Pick<ScenarioVariable, 'type' | 'required' | 'options'> => {
  const k = key.toLowerCase();
  const required = !OPTIONAL_VAR_KEYWORDS.some(x => k.includes(x));
  if (k === 'family' || k.includes('address_family') || k.includes('bgp_family') || k.includes('addr_family')) {
    return { type: 'select', required, options: ADDRESS_FAMILY_OPTIONS };
  }
  return { type: 'text', required };
};

export const getVariableHelpText = (key: string, platform: string, zh: boolean) => {
  const k = key.toLowerCase();
  const plat = (platform || '').toLowerCase();
  
  const isAclNum = k.includes('acl') && !k.includes('name');
  if (isAclNum) {
    if (plat.includes('cisco')) {
      return zh 
        ? '提示：思科标准 ACL (1-99, 1300-1999)；扩展 ACL (100-199, 2000-2699)' 
        : 'Tip: Cisco Standard ACL (1-99, 1300-1999); Extended ACL (100-199, 2000-2699)';
    }
    if (plat.includes('huawei') || plat.includes('h3c')) {
      return zh 
        ? '提示：华为/H3C 基本 ACL (2000-2999)；高级 ACL (3000-3999)；其它 (4000-6999)' 
        : 'Tip: Huawei/H3C Basic ACL (2000-2999); Advanced ACL (3000-3999); Others (4000-6999)';
    }
    if (plat.includes('arista')) {
      return zh 
        ? '提示：Arista ACL 范围 (1-199)' 
        : 'Tip: Arista ACL range (1-199)';
    }
    return zh ? '提示：请输入正整数 ACL 编号' : 'Tip: Please enter a positive integer ACL number';
  }

  const isIp = ['ip', 'host', 'server', 'neighbor', 'gateway', 'network', 'src', 'dst', 'router'].some(ind => k.includes(ind)) && !k.includes('mask') && !k.includes('wildcard');
  if (isIp) {
    if (k.includes('router_id')) {
      return zh 
        ? '提示：请输入合法的 Router ID (IPv4格式，如 10.0.0.1)' 
        : 'Tip: Enter a valid Router ID in IPv4 format (e.g. 10.0.0.1)';
    }
    const isTraditional = ['cisco', 'huawei', 'h3c'].some(p => plat.includes(p));
    if (isTraditional) {
      return zh 
        ? '提示：请输入纯 IPv4 地址（如 192.168.1.1），请勿包含 /24 等掩码位数' 
        : 'Tip: Enter a pure IPv4 address (e.g. 192.168.1.1), do not include /24 suffix';
    }
    return zh 
      ? '提示：支持纯 IPv4 地址或 CIDR 网段（如 192.168.1.0/24 或 192.168.1.1）' 
      : 'Tip: Supports pure IPv4 address or CIDR format (e.g., 192.168.1.0/24 or 192.168.1.1)';
  }

  if (k.includes('wildcard') || k.includes('inverse_mask')) {
    return zh 
      ? '提示：请输入反掩码点分十进制格式（如 0.0.0.255）' 
      : 'Tip: Please enter a wildcard mask (e.g., 0.0.0.255)';
  }

  if (k.includes('mask')) {
    if (plat.includes('cisco')) {
      return zh 
        ? '提示：思科不支持 CIDR 掩码位数（如 32），必须是点分十进制格式的子网掩码（如 255.255.255.255 或 255.255.255.0）' 
        : 'Tip: Cisco does not support CIDR mask digits (e.g. 32). It must be a dotted-decimal subnet mask (e.g. 255.255.255.255 or 255.255.255.0)';
    }
    return zh 
      ? '提示：请输入子网掩码（如 255.255.255.0）或 CIDR 位数（0-32）' 
      : 'Tip: Enter a subnet mask (e.g. 255.255.255.0) or CIDR (0-32)';
  }

  if (k.includes('process')) {
    return zh
      ? '提示：OSPF 进程 ID 必须在 1 到 65535 之间'
      : 'Tip: OSPF Process ID must be between 1 and 65535';
  }

  if (k.includes('area')) {
    return zh
      ? '提示：请输入 OSPF 区域 ID（正整数，或点分十进制如 0.0.0.0）'
      : 'Tip: Enter OSPF Area ID (positive integer, or dotted decimal like 0.0.0.0)';
  }

  const words = k.split(/[^a-z0-9]/);
  if (words.includes('as')) {
    return zh
      ? '提示：AS 号必须在 1 到 4294967295 之间'
      : 'Tip: AS number must be between 1 and 4294967295';
  }

  return '';
};
