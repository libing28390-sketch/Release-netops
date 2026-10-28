import { describe, expect, it } from 'vitest';
import type { ChangeOrder } from './types';
import type { SessionUser } from '../../types';
import { EMPTY_FORM } from './constants';
import {
  clampChangeOrderPage,
  canRecordEmergencyPostReview,
  canCurrentUserImplement,
  canUploadControlSheetAttachment,
  describeCurrentResponsibility,
  describeNextWorkflowAction,
  getChangeOrderExecutionAuthRole,
  hasOrderExecutionRequestBeenSent,
  isEligibleChangeOrderExecutor,
  isEligibleImplementer,
  getAssignedImplementer,
  getBusinessConfirmer,
  getImplementerConflictRole,
  buildChangeOrderRollbackFields,
  getFinalApproverCandidates,
  getInitialReviewerCandidates,
  getMissingChangeOrderControlSheetFields,
  parseRollbackCommands,
  resolveChangeOrderRollbackPlan,
  serializeRollbackCommands,
  getVerificationReadiness,
  hasActiveApprovalSnapshot,
  getNextWorkflowAction,
  getChangeOrderWindowState,
  getResultReviewActions,
  formatChangeOrderApiMessage,
  buildWorkflowPresentation,
  isBusinessVerifier,
  isChangeOrderFinalApprover,
  isChangeOrderInitialReviewer,
} from './helpers';

const createOrder = (overrides: Partial<ChangeOrder> = {}): ChangeOrder => ({
  id: 'order-1',
  order_number: 'CO-1',
  title: 'Core switch change',
  description: '',
  order_type: 'config_change',
  priority: 'medium',
  status: 'draft',
  requester_id: 'requester-id',
  requester_username: 'requester',
  assigned_initial_reviewer_id: '',
  assigned_initial_reviewer_username: '',
  assigned_final_approver_id: '',
  assigned_final_approver_username: '',
  initial_reviewer_id: '',
  initial_reviewer_username: '',
  final_approver_id: '',
  final_approver_username: '',
  approver_id: '',
  approver_username: '',
  target_devices: [],
  commands: [],
  rollback_plan: '',
  risk_level: 'low',
  scheduled_start: '',
  scheduled_end: '',
  actual_start: '',
  actual_end: '',
  result_summary: '',
  result_detail: {},
  rejected_reason: '',
  created_at: '',
  updated_at: '',
  ...overrides,
});

describe('change order API error messages', () => {
  const scopeDenied = {
    code: 'RESOURCE_SCOPE_DENIED',
    message: 'Insufficient permission for this resource scope',
    resource_type: 'command',
    action: 'execute',
  };

  it('localizes structured device command scope denial', () => {
    expect(formatChangeOrderApiMessage(scopeDenied, 'zh', '操作失败'))
      .toBe('当前账号无权对目标设备执行命令，请联系管理员检查授权。');
    expect(formatChangeOrderApiMessage(scopeDenied, 'en', 'Operation failed'))
      .toBe('You are not authorized to execute commands on these devices. Ask an administrator to review access.');
  });

  it('returns bounded text for string and message details, and a localized fallback for other values', () => {
    expect(formatChangeOrderApiMessage('  Not allowed  ', 'en', 'Fallback')).toBe('Not allowed');
    expect(formatChangeOrderApiMessage(`  ${'x'.repeat(300)}  `, 'en', 'Fallback')).toHaveLength(240);
    expect(formatChangeOrderApiMessage({ code: 'OTHER', message: ' Server rejected the request ' }, 'en', 'Fallback'))
      .toBe('Server rejected the request');
    expect(formatChangeOrderApiMessage({ code: 'OTHER', message: { reason: 'hidden' } }, 'zh', '操作失败'))
      .toBe('操作失败');
    expect(formatChangeOrderApiMessage(['unexpected'], 'en', 'Fallback')).toBe('Fallback');
    expect(formatChangeOrderApiMessage(null, 'zh', '请求失败')).toBe('请求失败');
  });
});

describe('control sheet attachment upload eligibility', () => {
  const requester: SessionUser = { id: 'requester-id', username: 'requester', role: 'Operator' };

  it('allows the requester or an administrator to upload before execution begins', () => {
    expect(canUploadControlSheetAttachment(createOrder({ status: 'draft' }), requester)).toBe(true);
    expect(canUploadControlSheetAttachment(createOrder({ status: 'initial_review' }), requester)).toBe(true);
    expect(canUploadControlSheetAttachment(createOrder({ status: 'final_review' }), requester)).toBe(true);
    expect(canUploadControlSheetAttachment(createOrder({ status: 'approved' }), requester)).toBe(true);
    expect(canUploadControlSheetAttachment(createOrder({ status: 'approved' }), {
      id: 'requester-id', username: 'requester', role: 'Viewer', role_profile: 'Change Requester',
    })).toBe(true);
    expect(canUploadControlSheetAttachment(createOrder({ status: 'approved' }), { id: 'admin', username: 'admin', role: 'Administrator' })).toBe(true);
  });

  it('blocks other users, execution-started orders, and terminal workflow states', () => {
    expect(canUploadControlSheetAttachment(createOrder({ status: 'approved' }), { id: 'other', username: 'other', role: 'Operator' })).toBe(false);
    expect(canUploadControlSheetAttachment(createOrder({ status: 'approved' }), {
      id: 'operator-admin', username: 'operator-admin', role: 'Administrator', role_profile: 'Automation Operator',
    })).toBe(false);
    expect(canUploadControlSheetAttachment(createOrder({ status: 'implementing', result_detail: { execution_started_at: '2026-10-26T10:00:00Z' } }), requester)).toBe(false);
    expect(canUploadControlSheetAttachment(createOrder({ status: 'completed' }), requester)).toBe(false);
  });
});

describe('change order pagination', () => {
  it('clamps an out-of-range page after the result count shrinks', () => {
    expect(clampChangeOrderPage(5, 21, 10)).toBe(3);
    expect(clampChangeOrderPage(3, 20, 10)).toBe(2);
  });

  it('keeps the first page available for empty results and normalizes invalid values', () => {
    expect(clampChangeOrderPage(4, 0, 10)).toBe(1);
    expect(clampChangeOrderPage(0, 30, 10)).toBe(1);
    expect(clampChangeOrderPage(2, 30, 0)).toBe(2);
  });
});

describe('approved order next action and window', () => {
  const order = createOrder({
    status: 'approved', scheduled_start: '2026-10-25 09:00:00', scheduled_end: '2026-10-25 10:00:00',
    control_sheet: { implementer: { id: 'engineer-id', username: 'engineer' } },
  });
  const start = Date.parse('2026-10-25T09:00:00+08:00');
  const end = Date.parse('2026-10-25T10:00:00+08:00');
  it('matches Shanghai legacy timestamps, explicit offsets and the exclusive end boundary', () => {
    expect(getChangeOrderWindowState(order, start - 1)).toBe('before');
    expect(getChangeOrderWindowState(order, start)).toBe('open');
    expect(getChangeOrderWindowState(order, end - 1)).toBe('open');
    expect(getChangeOrderWindowState(order, end)).toBe('ended');
    expect(getChangeOrderWindowState({ ...order, scheduled_start: '2026-10-25T01:00:00Z', scheduled_end: '2026-10-25T02:00:00Z' }, start)).toBe('open');
    expect(getChangeOrderWindowState({ ...order, scheduled_end: order.scheduled_start }, start)).toBe('invalid');
  });
  it('describes time restrictions before an available implementation action', () => {
    const actions = [{ status: 'implementing', label: '进入实施' }];
    expect(getNextWorkflowAction(order, actions, 'zh', start - 1)).toContain('未开始');
    expect(getNextWorkflowAction(order, actions, 'zh', start)).toBe('窗口内，待 engineer 进入实施');
    expect(getNextWorkflowAction(order, actions, 'zh', end)).toContain('已结束');
    expect(getNextWorkflowAction({ ...order, scheduled_start: '' }, actions, 'zh', start)).toContain('无效');
  });
  it('explains assignment conflicts and role restrictions instead of waiting for the same person', () => {
    expect(getNextWorkflowAction({ ...order, requester_id: 'engineer-id' }, [], 'zh', start, { id: 'engineer-id', username: 'engineer', role: 'Operator' })).toBe('窗口内，可进入实施');
    expect(getNextWorkflowAction({ ...order, assigned_final_approver_id: 'engineer-id' }, [], 'zh', start)).toContain('请调整实施人');
    expect(getNextWorkflowAction(order, [], 'zh', start, { id: 'engineer-id', username: 'engineer', role: 'Administrator' })).toContain('不符合实施角色要求');
    expect(getNextWorkflowAction({ ...order, control_sheet: {} }, [], 'en', start)).toBe('Assign an implementer');
  });
  it('explains why a disabled next action cannot be used', () => {
    expect(getNextWorkflowAction({ ...order, status: 'implementing' }, [{ status: 'execute_commands', label: '已请求执行', disabled: true, disabledReason: '授权已使用' }], 'zh', start)).toBe('授权已使用');
  });
});

describe('implementation result review workflow', () => {
  const order = createOrder({ status: 'implementing',
    initial_reviewer_id: 'initial', initial_reviewer_username: 'first-reviewer',
    control_sheet: { implementer: { id: 'requester-id', username: 'requester' }, co_reviewer: { id: 'checker', username: 'checker' } },
  });
  const implementer: SessionUser = { id: 'requester-id', username: 'requester', role: 'Operator' };
  const checker: SessionUser = { id: 'checker', username: 'checker', role: 'Viewer' };
  it('lets the applicant implement and submit only after the existing verification gate', () => {
    expect(getResultReviewActions(order, implementer, 'zh')[0]).toMatchObject({ action: 'submit', disabled: true });
    const verified = { ...order, result_detail: { approval_snapshot_hash: 'hash', approval_snapshot_version: 1, verification_records: [{ kind: 'technical', result: 'passed', approval_snapshot_hash: 'hash' }] } };
    expect(getResultReviewActions(verified, implementer, 'zh')[0]).toMatchObject({ action: 'submit', disabled: false });
    expect(getResultReviewActions({ ...verified, control_sheet: { implementer: order.control_sheet?.implementer } }, implementer, 'zh')).toEqual([]);
  });
  it('allows the designated reviewer without an executor role, never the implementer', () => {
    const pending = { ...order, status: 'implementation_review' };
    expect(getResultReviewActions(pending, checker, 'zh').map(action => action.action)).toEqual(['pass', 'fail']);
    expect(getResultReviewActions(pending, implementer, 'zh')).toEqual([]);
    expect(getResultReviewActions(pending, { id: 'other', username: 'other', role: 'Administrator' }, 'zh')).toEqual([]);
    expect(describeCurrentResponsibility(pending, 'zh').owner).toBe('checker');
  });
  it('routes abnormal results to the actual original initial reviewer', () => {
    const pending = { ...order, status: 'implementation_result_review', assigned_initial_reviewer_id: 'other-initial' };
    expect(getResultReviewActions(pending, { id: 'initial', username: 'first-reviewer', role: 'Administrator' }, 'zh').map(action => action.action)).toEqual(['accept', 'reject']);
    expect(getResultReviewActions(pending, { id: 'other-initial', username: 'other', role: 'Administrator' }, 'zh')).toEqual([]);
    expect(describeCurrentResponsibility(pending, 'zh').owner).toBe('first-reviewer');
  });
  it('shows the result review phase after implementation instead of returning to pre-approval', () => {
    const presentation = buildWorkflowPresentation({ ...order, status: 'implementation_result_review' }, 'zh');
    expect(presentation.steps.find(step => step.key === 'initial_review')?.state).toBe('done');
    expect(presentation.steps.find(step => step.key === 'implementation_review')?.state).toBe('error');
    expect(presentation.exception?.detail).toContain('不重新授权');
  });
});

describe('emergency post-review timing', () => {
  const pendingEmergency = {
    order_type: 'emergency',
    status: 'implementing',
    actual_end: '',
    emergency_review_status: 'pending' as const,
    emergency_review_owner_id: 'reviewer-1',
  };

  it('waits for a completed or rolled-back change with an actual end time', () => {
    expect(canRecordEmergencyPostReview(pendingEmergency, 'reviewer-1')).toBe(false);
    expect(canRecordEmergencyPostReview({ ...pendingEmergency, status: 'completed', actual_end: '' }, 'reviewer-1')).toBe(false);
    expect(canRecordEmergencyPostReview({ ...pendingEmergency, status: 'completed', actual_end: '2026-10-24T10:00:00Z' }, 'reviewer-1')).toBe(true);
    expect(canRecordEmergencyPostReview({ ...pendingEmergency, status: 'rolled_back', actual_end: '2026-10-24T10:00:00Z' }, 'reviewer-1')).toBe(true);
  });

  it('only allows the designated reviewer while review is pending', () => {
    const completed = { ...pendingEmergency, status: 'completed', actual_end: '2026-10-24T10:00:00Z' };
    expect(canRecordEmergencyPostReview(completed, 'other-user')).toBe(false);
    expect(canRecordEmergencyPostReview({ ...completed, emergency_review_status: 'accepted' }, 'reviewer-1')).toBe(false);
  });
});

describe('describeCurrentResponsibility', () => {
  it('shows the assigned initial reviewer', () => {
    expect(describeCurrentResponsibility(createOrder({
      status: 'initial_review',
      assigned_initial_reviewer_username: 'reviewer-1',
    }), 'zh')).toEqual({ stage: '初审中', owner: 'reviewer-1' });
  });

  it('identifies an unassigned final approver instead of showing a blank owner', () => {
    expect(describeCurrentResponsibility(createOrder({ status: 'final_review' }), 'zh').owner)
      .toBe('待指定终审人');
  });

  it('uses the control-sheet implementer name during implementation', () => {
    expect(describeCurrentResponsibility(createOrder({
      status: 'implementing',
      control_sheet: { implementer: { id: 'implementer-id', username: 'engineer-1' } },
    }), 'zh').owner).toBe('engineer-1');
  });

  it('shows the selected implementer as current owner once approval is complete', () => {
    expect(describeCurrentResponsibility(createOrder({
      status: 'approved',
      control_sheet: { implementer: { id: 'implementer-id', username: 'engineer-1' } },
    }), 'zh').owner).toBe('engineer-1');
    expect(describeCurrentResponsibility(createOrder({ status: 'approved' }), 'zh').owner)
      .toBe('待指派实施人');
  });

  it('keeps failed and rollback transitions with the implementer when known', () => {
    expect(describeCurrentResponsibility(createOrder({ status: 'failed' }), 'zh').owner)
      .toBe('requester');
    expect(describeCurrentResponsibility(createOrder({ status: 'rollback_in_progress' }), 'zh').owner)
      .toBe('requester');
    expect(describeCurrentResponsibility(createOrder({
      status: 'rollback_in_progress',
      control_sheet: { implementer: { id: 'implementer-id', username: 'engineer-1' } },
    }), 'zh').owner).toBe('engineer-1');
  });

  it('does not assign an active owner after a terminal state', () => {
    expect(describeCurrentResponsibility(createOrder({ status: 'completed' }), 'zh'))
      .toEqual({ stage: '变更完成', owner: '—' });
  });
});

describe('change order responsibilities and verification', () => {
  it('uses normal device credentials by default and admin credentials only for a System Administrator profile', () => {
    expect(getChangeOrderExecutionAuthRole({ id: 'operator-1', username: 'operator', role: 'Operator' })).toBe('normal');
    expect(getChangeOrderExecutionAuthRole({ id: 'admin-1', username: 'admin', role: 'Administrator' })).toBe('normal');
    expect(getChangeOrderExecutionAuthRole({ id: 'admin-2', username: 'admin-2', role: 'Administrator', role_profile: 'Network Operator' })).toBe('normal');
    expect(getChangeOrderExecutionAuthRole({ id: 'sysadmin-1', username: 'sysadmin', role: 'Administrator', role_profile: 'System Administrator' })).toBe('admin');
  });

  it('detects a consumed or started single-use execution request', () => {
    expect(hasOrderExecutionRequestBeenSent(createOrder({ result_detail: {} }))).toBe(false);
    expect(hasOrderExecutionRequestBeenSent(createOrder({ result_detail: { execution_token_consumed_at: '2026-10-24T09:00:00Z' } }))).toBe(false);
    expect(hasOrderExecutionRequestBeenSent(createOrder({ result_detail: { execution_started_at: '2026-10-24T09:00:00Z' } }))).toBe(true);
    expect(hasOrderExecutionRequestBeenSent(createOrder({ result_detail: { execution_request_hash: 'fingerprint' } }))).toBe(true);
    expect(hasOrderExecutionRequestBeenSent(createOrder({ result_detail: { execution_results: [{ status: 'partial_failure' }] } }))).toBe(true);
    expect(hasOrderExecutionRequestBeenSent(createOrder({ result_detail: { playbook_execution_events: [{ status: 'running' }] } }))).toBe(true);
  });

  it('derives the next main workflow action from status when the viewer can only cancel', () => {
    expect(describeNextWorkflowAction(createOrder({
      status: 'initial_review',
      assigned_initial_reviewer_username: 'reviewer-1',
    }), 'zh')).toBe('等待初审人 reviewer-1 审核');
  });

  it('does not present cancel as the next step when the viewer is not the assigned reviewer', () => {
    expect(getNextWorkflowAction(createOrder({
      status: 'initial_review',
      assigned_initial_reviewer_username: 'reviewer-1',
    }), [{ label: 'Cancel', status: 'cancelled' }], 'zh')).toBe('等待初审人 reviewer-1 审核');
  });

  it('uses the canonical nested implementer and business confirmer while reading legacy aliases', () => {
    const order = createOrder({ control_sheet: {
      implementer: { id: 'implementer-1', username: 'engineer-1' },
      business_verifier: { id: 'confirmer-1', username: 'business-1' },
      business_verifier_id: 'legacy-id',
      business_verifier_username: 'legacy-user',
    } });
    expect(getAssignedImplementer(order)).toEqual({ id: 'implementer-1', username: 'engineer-1' });
    expect(getBusinessConfirmer(order)).toEqual({ id: 'confirmer-1', username: 'business-1' });
    expect(isBusinessVerifier(order, { id: 'confirmer-1', username: 'business-1' })).toBe(true);
  });

  it('hides implementation actions from a final approver and from an administrator without assignment', () => {
    const order = createOrder({
      status: 'implementing',
      assigned_final_approver_id: 'approver-1',
      control_sheet: { implementer: { id: 'implementer-1', username: 'engineer-1' } },
    });
    expect(canCurrentUserImplement(order, { id: 'implementer-1', username: 'engineer-1', role: 'Operator' })).toBe(true);
    expect(canCurrentUserImplement(order, { id: 'approver-1', username: 'approver', role: 'Administrator' })).toBe(false);
    expect(canCurrentUserImplement(order, { id: 'admin-1', username: 'admin', role: 'Administrator' })).toBe(false);
    expect(canCurrentUserImplement(order, { id: 'implementer-1', username: 'engineer-1', role: 'Administrator' })).toBe(false);
    expect(canCurrentUserImplement(order, { id: 'implementer-1', username: 'engineer-1', role: 'Administrator', role_profile: 'Network Operator' })).toBe(false);
    expect(canCurrentUserImplement(order, { id: 'implementer-1', username: 'engineer-1', role: 'Administrator', role_profile: 'System Administrator' })).toBe(true);
    expect(canCurrentUserImplement(order, { id: 'implementer-1', username: 'engineer-1', role: 'Operator', role_profile: 'Automation Operator' })).toBe(true);
  });

  it('allows only the supported execution profiles and legacy profileless Operators', () => {
    expect(isEligibleChangeOrderExecutor({ role: 'Operator' })).toBe(true);
    expect(isEligibleChangeOrderExecutor({ role: 'Operator', role_profile: 'Automation Operator' })).toBe(true);
    expect(isEligibleChangeOrderExecutor({ role: 'Administrator', role_profile: 'System Administrator' })).toBe(true);
    expect(isEligibleChangeOrderExecutor({ role: 'Operator', role_profile: 'Change Requester' })).toBe(false);
    expect(isEligibleChangeOrderExecutor({ role: 'Operator', role_profile: 'Platform Viewer' })).toBe(false);
    expect(isEligibleChangeOrderExecutor({ role: 'Administrator', role_profile: 'Network Operator' })).toBe(false);
    expect(isEligibleChangeOrderExecutor({ role: 'Viewer', role_profile: 'Automation Operator' })).toBe(false);
    expect(isEligibleChangeOrderExecutor({ role: 'Administrator' })).toBe(false);
  });

  it('allows the requester to implement while keeping the final approver separate', () => {
    const order = createOrder({
      requester_id: 'requester-id',
      requester_username: 'requester',
      assigned_final_approver_id: 'approver-id',
      assigned_final_approver_username: 'approver',
    });
    expect(isEligibleImplementer({ id: 'executor-id', username: 'executor', role: 'Operator' }, order)).toBe(true);
    expect(isEligibleImplementer({ id: 'requester-id', username: 'requester', role: 'Operator' }, order)).toBe(true);
    expect(canCurrentUserImplement({ ...order, control_sheet: { implementer: { id: 'requester-id', username: 'requester' } } }, { id: 'requester-id', username: 'requester', role: 'Operator' })).toBe(true);
    expect(isEligibleImplementer({ id: 'approver-id', username: 'approver', role: 'Administrator', role_profile: 'System Administrator' }, order)).toBe(false);
  });

  it('requires technical pass and requires business pass only when business verification applies', () => {
    const noBusinessRequirement = createOrder({
      result_detail: {
        approval_snapshot_hash: 'snapshot-1',
        approval_snapshot_version: 1,
        verification_records: [{ kind: 'technical', result: 'passed', summary: 'CLI checks passed', approval_snapshot_hash: 'snapshot-1' }],
      },
    });
    expect(getVerificationReadiness(noBusinessRequirement)).toMatchObject({
      technicalPassed: true,
      businessApplicable: false,
      canComplete: true,
    });

    const businessRequired = createOrder({
      control_sheet: { business_verify: 'Service owner confirms checkout works' },
      result_detail: {
        approval_snapshot_hash: 'snapshot-1',
        approval_snapshot_version: 1,
        verification_records: [
          { kind: 'technical', result: 'passed', summary: 'CLI checks passed', approval_snapshot_hash: 'snapshot-1' },
          { kind: 'business', result: 'failed', summary: 'Checkout still errors', approval_snapshot_hash: 'snapshot-1' },
        ],
      },
    });
    expect(getVerificationReadiness(businessRequired)).toMatchObject({
      technicalPassed: true,
      businessApplicable: true,
      businessPassed: false,
      canComplete: false,
      missingKinds: ['business'],
    });
  });

  it('does not reuse verification from an invalidated approval snapshot', () => {
    const order = createOrder({
      result_detail: {
        approval_snapshot_version: 1,
        verification_records: [{ kind: 'technical', result: 'passed', summary: 'Previously passed', approval_snapshot_hash: 'old-snapshot' }],
      },
    });
    expect(hasActiveApprovalSnapshot(order)).toBe(false);
    expect(getVerificationReadiness(order).canComplete).toBe(false);
    expect(getVerificationReadiness(order).missingKinds).toEqual(['technical']);
  });

  it('defaults legacy device-login authorization exemption to false for every role', () => {
    expect(EMPTY_FORM.authorization_exempt).toBe(false);
  });

  it.each([
    ['co_reviewer', 'co_reviewer'],
    ['business_confirmer', 'business_confirmer'],
    ['initial_reviewer', 'initial_reviewer'],
    ['final_approver', 'final_approver'],
  ] as const)('detects an implementer assigned as %s', (_label, role) => {
    expect(getImplementerConflictRole('admin-1', { [role]: 'admin-1' })).toBe(role);
  });

  it('allows a distinct implementer and review/confirmation assignments', () => {
    expect(getImplementerConflictRole('engineer-1', {
      co_reviewer: 'reviewer-1',
      business_confirmer: 'owner-1',
      initial_reviewer: 'reviewer-2',
      final_approver: 'approver-1',
    })).toBeNull();
    expect(getImplementerConflictRole('', { co_reviewer: 'reviewer-1' })).toBeNull();
  });

  it('uses generated template rollback commands when present and falls back to the written plan', () => {
    expect(resolveChangeOrderRollbackPlan('Manual fallback', [' undo command ', '', 'restore state']))
      .toBe('undo command\nrestore state');
    expect(resolveChangeOrderRollbackPlan('  Manual fallback  ', []))
      .toBe('Manual fallback');
    expect(resolveChangeOrderRollbackPlan('', [])).toBe('');
  });

  it('serializes the latest template precheck rollback plan into both submitted fields', () => {
    const submitted = buildChangeOrderRollbackFields(
      'Manual fallback',
      ['Local preview command'],
      ['Server validated command', 'Restore previous route'],
      { implementer: { id: 'engineer-1' }, rollback_plan: 'Stale mirrored content' },
    );

    expect(submitted.rollback_plan).toBe('Server validated command\nRestore previous route');
    expect(submitted.control_sheet).toEqual({
      implementer: { id: 'engineer-1' },
      rollback_plan: submitted.rollback_plan,
    });
  });

  it('uses the operator plan when the validated template has no rollback commands', () => {
    expect(buildChangeOrderRollbackFields('Operator plan', ['Local preview'], [], {}).rollback_plan)
      .toBe('Operator plan');
    expect(buildChangeOrderRollbackFields('', ['Local preview'], [], {}).rollback_plan).toBe('');
  });

  it('parses and serializes rollback commands without blank lines', () => {
    const commands = parseRollbackCommands('  undo interface 1/0/1\r\n\nrestore vlan 20  ');
    expect(commands).toEqual(['undo interface 1/0/1', 'restore vlan 20']);
    expect(serializeRollbackCommands(commands)).toBe('undo interface 1/0/1\nrestore vlan 20');
  });

  it('reports required control-sheet fields for final submission', () => {
    expect(getMissingChangeOrderControlSheetFields({
      implementer_id: 'engineer-1',
      pre_check: 'show interface brief',
      execution: 'Apply the approved commands',
      post_verify: 'Confirm interface and route state',
      business_verify: 'Service owner confirms connectivity',
    })).toEqual([]);
    expect(getMissingChangeOrderControlSheetFields({ implementer_id: 'engineer-1' })).toEqual([
      'pre_check', 'execution', 'post_verify', 'business_verify',
    ]);
  });

  it('only offers administrators assigned to the final-approver group', () => {
    const users = [
      { id: 'alice', username: 'alice', role: 'Administrator', change_groups: ['final_approver'] },
      { id: 'admin', username: 'admin', role: 'Administrator', change_groups: [] },
      { id: 'reviewer', username: 'reviewer', role: 'Operator', change_groups: ['final_approver'] },
      { id: 'requester', username: 'requester', role: 'Administrator', change_groups: ['final_approver'] },
    ] as any;

    expect(getFinalApproverCandidates(users, 'current-user', 'requester', 'implementer').map((user) => user.id))
      .toEqual(['alice']);
    expect(getFinalApproverCandidates(users, 'current-user', 'requester', 'alice')).toEqual([]);
  });

  it('only offers administrators assigned to the initial-review group', () => {
    const users = [
      { id: 'admin-reviewer', username: 'reviewer', role: 'Administrator', change_groups: ['initial_reviewer'] },
      { id: 'operator-reviewer', username: 'operator', role: 'Operator', change_groups: ['initial_reviewer'] },
      { id: 'admin-without-group', username: 'admin', role: 'Administrator', change_groups: [] },
      { id: 'requester', username: 'requester', role: 'Administrator', change_groups: ['initial_reviewer'] },
    ] as any;

    expect(getInitialReviewerCandidates(users, 'requester', 'implementer').map((user) => user.id))
      .toEqual(['admin-reviewer']);
    expect(getInitialReviewerCandidates(users, 'requester', 'admin-reviewer')).toEqual([]);
  });

  it('only treats administrators as assigned initial reviewers and final approvers', () => {
    const order = createOrder({
      assigned_initial_reviewer_id: 'reviewer-1',
      assigned_initial_reviewer_username: 'reviewer',
      assigned_final_approver_id: 'approver-1',
      assigned_final_approver_username: 'approver',
    });
    const administrator = { id: 'reviewer-1', username: 'reviewer', role: 'Administrator' } as SessionUser;
    const ordinaryUser = { id: 'reviewer-1', username: 'reviewer', role: 'Operator' } as SessionUser;

    expect(isChangeOrderInitialReviewer(order, administrator)).toBe(true);
    expect(isChangeOrderInitialReviewer(order, ordinaryUser)).toBe(false);
    expect(isChangeOrderFinalApprover(order, { id: 'approver-1', username: 'approver', role: 'Administrator' } as SessionUser)).toBe(true);
    expect(isChangeOrderFinalApprover(order, { id: 'approver-1', username: 'approver', role: 'Operator' } as SessionUser)).toBe(false);
  });
});
