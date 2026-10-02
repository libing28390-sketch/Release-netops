import type { ChangeOrder, ScenarioVariable, ScenarioPhasePreview, WorkflowVisualState, CommandTemplateSnapshot } from './types';
import type { User as UserOption } from '../../types';
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

export const priorityLabel = (priority: string, lang: string) =>
  PRIORITY_META[priority]?.label?.[lang === 'zh' ? 'zh' : 'en'] ?? priority;

export const typeLabel = (type: string, lang: string) =>
  ORDER_TYPE_META[type]?.label?.[lang === 'zh' ? 'zh' : 'en'] ?? type;

export const riskLabel = (risk: string, lang: string) =>
  RISK_META[risk]?.label?.[lang === 'zh' ? 'zh' : 'en'] ?? risk;

export const hasChangeGroup = (user: UserOption, groupKey: string) =>
  Array.isArray(user.change_groups) && user.change_groups.includes(groupKey);

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
    'rollback_in_progress': '回溯中',
    'rolled_back': '已回溯',
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
  const completedIndex = PRIMARY_WORKFLOW_INDEX.completed;
  const states = PRIMARY_WORKFLOW.map<WorkflowVisualState>(() => 'pending');

  const setDoneBefore = (index: number) => {
    for (let i = 0; i < index; i += 1) states[i] = 'done';
  };

  const formatActorCaption = (label: string, actor: string) => actor ? `${label}${actor}` : '';

  let exception: { tone: 'rose' | 'violet' | 'slate'; label: string; detail: string } | null = null;

  if (normalizedStatus === 'completed') {
    for (let i = 0; i <= completedIndex; i += 1) states[i] = 'done';
  } else if (normalizedStatus === 'rejected') {
    const rejectedStage = typeof details.rejected_stage === 'string'
      ? normalizeWorkflowStatus(details.rejected_stage)
      : 'initial_review';
    const rejectedIndex = PRIMARY_WORKFLOW_INDEX[rejectedStage] ?? PRIMARY_WORKFLOW_INDEX.initial_review;
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
      label: zh ? '异常回溯中' : 'Rollback in Progress',
      detail: typeof details.rollback_reason === 'string' && details.rollback_reason
        ? details.rollback_reason
        : (zh ? '实施阶段发现异常，正在执行回溯。' : 'An issue was found during implementation and rollback is running.'),
    };
  } else if (normalizedStatus === 'rolled_back') {
    setDoneBefore(implementingIndex);
    states[implementingIndex] = 'error';
    exception = {
      tone: 'violet',
      label: zh ? '回溯完成' : 'Rollback Completed',
      detail: order.result_summary || (zh ? '异常已处理，变更已成功回溯。' : 'Rollback finished and the change was reverted.'),
    };
  } else if (normalizedStatus === 'failed') {
    setDoneBefore(implementingIndex);
    states[implementingIndex] = 'error';
    exception = {
      tone: 'rose',
      label: typeof details.rollback_started_at === 'string' && details.rollback_started_at
        ? (zh ? '回溯失败' : 'Rollback Failed')
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
    const cancelIndex = PRIMARY_WORKFLOW_INDEX[cancelStage] ?? 0;
    setDoneBefore(cancelIndex);
    states[cancelIndex] = 'error';
    exception = {
      tone: 'slate',
      label: zh ? '工单取消' : 'Order Cancelled',
      detail: zh ? '该工单已被人工取消，不再继续执行。' : 'This order was cancelled and will not continue.',
    };
  } else {
    const currentIndex = PRIMARY_WORKFLOW_INDEX[normalizedStatus] ?? 0;
    setDoneBefore(currentIndex);
    states[currentIndex] = 'current';
  }

  const steps = PRIMARY_WORKFLOW.map((step, index) => {
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
