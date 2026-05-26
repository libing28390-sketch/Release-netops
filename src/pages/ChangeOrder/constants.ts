import React from 'react';
import { ArrowUp, ArrowUpRight, ArrowDown, Minus } from 'lucide-react';
import type { ScenarioPhasePreview } from './types';

export const STATUS_META: Record<string, { label: { zh: string; en: string }; dot: string; bg: string; ring: string }> = {
  draft:               { label: { zh: '草稿', en: 'Draft' },                   dot: 'bg-slate-400',   bg: 'bg-slate-50',    ring: 'ring-slate-200' },
  initial_review:      { label: { zh: '初审中', en: 'Initial Review' },        dot: 'bg-amber-400',   bg: 'bg-amber-50',    ring: 'ring-amber-200' },
  final_review:        { label: { zh: '终审中', en: 'Final Review' },           dot: 'bg-sky-500',     bg: 'bg-sky-50',      ring: 'ring-sky-200' },
  approved:            { label: { zh: '审批完成', en: 'Approved' },             dot: 'bg-blue-400',    bg: 'bg-blue-50',     ring: 'ring-blue-200' },
  implementing:        { label: { zh: '实施中', en: 'Implementing' },           dot: 'bg-cyan-400',    bg: 'bg-cyan-50',     ring: 'ring-cyan-200' },
  completed:           { label: { zh: '变更完成', en: 'Completed' },            dot: 'bg-emerald-500', bg: 'bg-emerald-50',  ring: 'ring-emerald-200' },
  rollback_in_progress:{ label: { zh: '回溯中', en: 'Rollback In Progress' },   dot: 'bg-violet-500',  bg: 'bg-violet-50',   ring: 'ring-violet-200' },
  rolled_back:         { label: { zh: '已回溯', en: 'Rolled Back' },            dot: 'bg-indigo-500',  bg: 'bg-indigo-50',   ring: 'ring-indigo-200' },
  rejected:            { label: { zh: '已驳回', en: 'Rejected' },               dot: 'bg-red-400',     bg: 'bg-red-50',      ring: 'ring-red-200' },
  failed:              { label: { zh: '失败', en: 'Failed' },                   dot: 'bg-rose-500',    bg: 'bg-rose-50',     ring: 'ring-rose-200' },
  cancelled:           { label: { zh: '已取消', en: 'Cancelled' },              dot: 'bg-gray-400',    bg: 'bg-gray-50',     ring: 'ring-gray-200' },
  pending:             { label: { zh: '待审批(旧)', en: 'Pending (Legacy)' },   dot: 'bg-amber-400',   bg: 'bg-amber-50',    ring: 'ring-amber-200' },
  executing:           { label: { zh: '执行中(旧)', en: 'Executing (Legacy)' }, dot: 'bg-cyan-400',    bg: 'bg-cyan-50',     ring: 'ring-cyan-200' },
};

export const PRIORITY_META: Record<string, { label: { zh: string; en: string }; icon: React.ElementType; color: string; bg: string }> = {
  critical: { label: { zh: '紧急', en: 'Critical' }, icon: ArrowUp,       color: 'text-rose-600',   bg: 'bg-rose-50' },
  high:     { label: { zh: '高', en: 'High' },       icon: ArrowUpRight,  color: 'text-orange-600', bg: 'bg-orange-50' },
  medium:   { label: { zh: '中', en: 'Medium' },     icon: Minus,         color: 'text-amber-600',  bg: 'bg-amber-50' },
  low:      { label: { zh: '低', en: 'Low' },        icon: ArrowDown,     color: 'text-slate-500',  bg: 'bg-slate-50' },
};

export const ORDER_TYPE_META: Record<string, { label: { zh: string; en: string } }> = {
  config_change:    { label: { zh: '配置变更', en: 'Config Change' } },
  firmware_upgrade: { label: { zh: '固件升级', en: 'Firmware Upgrade' } },
  maintenance:      { label: { zh: '维护操作', en: 'Maintenance' } },
  emergency:        { label: { zh: '紧急变更', en: 'Emergency' } },
  other:            { label: { zh: '其他', en: 'Other' } },
};

export const RISK_META: Record<string, { label: { zh: string; en: string }; color: string }> = {
  low:    { label: { zh: '低风险', en: 'Low Risk' },      color: 'text-emerald-600' },
  medium: { label: { zh: '中风险', en: 'Medium Risk' },   color: 'text-amber-600' },
  high:   { label: { zh: '高风险', en: 'High Risk' },     color: 'text-rose-600' },
};

export const EMPTY_CONTROL_SHEET = {
  change_time_start: '',
  change_time_end: '',
  implementer_id: '',
  implementer_username: '',
  co_reviewer_id: '',
  co_reviewer_username: '',
  device_ips: '',
  pre_check: '',
  execution: '',
  post_verify: '',
  business_verify: '',
  rollback_plan: '',
};

export const EMPTY_FORM = {
  title: '',
  description: '',
  order_type: 'config_change',
  priority: 'medium',
  risk_level: 'low',
  rollback_plan: '',
  scheduled_start: '',
  scheduled_end: '',
  assigned_initial_reviewer_id: '',
  assigned_initial_reviewer_username: '',
  assigned_final_approver_id: '',
  assigned_final_approver_username: '',
  target_devices: [] as { hostname: string; ip_address: string; username?: string; platform?: string }[],
  commands: [] as string[],
  control_sheet: { ...EMPTY_CONTROL_SHEET },
};

export const DEFAULT_PAGE_SIZE = 10;
export const EMPTY_TEMPLATE_PREVIEW: ScenarioPhasePreview = {
  pre_check: [],
  execute: [],
  post_check: [],
  rollback: [],
};

export const CONFIG_TEMPLATE_SCENARIO_PREFIX = 'cfgtpl:';
export const toConfigTemplateScenarioId = (templateId: string) => `${CONFIG_TEMPLATE_SCENARIO_PREFIX}${templateId}`;
export const isConfigTemplateScenarioId = (scenarioId: string) => scenarioId.startsWith(CONFIG_TEMPLATE_SCENARIO_PREFIX);
export const fromConfigTemplateScenarioId = (scenarioId: string) => scenarioId.replace(CONFIG_TEMPLATE_SCENARIO_PREFIX, '');

export const TIMELINE_EVENT_META: Record<string, { zh: string; en: string }> = {
  'change_order.created': { zh: '创建工单', en: 'Order Created' },
  'change_order.updated': { zh: '更新工单', en: 'Order Updated' },
  'change_order.initial_review': { zh: '提交初审', en: 'Submitted for Initial Review' },
  'change_order.final_review': { zh: '初审通过，进入终审', en: 'Passed Initial Review' },
  'change_order.approved': { zh: '终审通过', en: 'Final Approval Granted' },
  'change_order.implementing': { zh: '进入实施', en: 'Implementation Started' },
  'change_order.completed': { zh: '变更完成', en: 'Change Completed' },
  'change_order.rejected': { zh: '工单驳回', en: 'Order Rejected' },
  'change_order.failed': { zh: '实施失败', en: 'Implementation Failed' },
  'change_order.rollback_in_progress': { zh: '启动回溯', en: 'Rollback Started' },
  'change_order.rolled_back': { zh: '回溯完成', en: 'Rollback Completed' },
  'change_order.cancelled': { zh: '工单取消', en: 'Order Cancelled' },
  'change_order.deleted': { zh: '工单删除', en: 'Order Deleted' },
  'change_order.control_sheet_uploaded': { zh: '上传变更控制表附件', en: 'Control Sheet Attachment Uploaded' },
};

export const PRIMARY_WORKFLOW = [
  {
    key: 'draft',
    label: { zh: '工单创建', en: 'Created' },
    hint: { zh: '提交变更目标、命令与回退方案', en: 'Submit scope, commands and rollback plan' },
  },
  {
    key: 'initial_review',
    label: { zh: '初审', en: 'Initial Review' },
    hint: { zh: '由审核人确认变更必要性与风险', en: 'Reviewer checks necessity and risk' },
  },
  {
    key: 'final_review',
    label: { zh: '终审', en: 'Final Review' },
    hint: { zh: '由管理员确认窗口与实施许可', en: 'Administrator grants the final approval' },
  },
  {
    key: 'approved',
    label: { zh: '审批完成', en: 'Approved' },
    hint: { zh: '已具备进入实施阶段的许可', en: 'Ready to enter the implementation window' },
  },
  {
    key: 'implementing',
    label: { zh: '实施', en: 'Implementing' },
    hint: { zh: '执行变更并观测现场状态', en: 'Execute the change and observe results' },
  },
  {
    key: 'completed',
    label: { zh: '完成', en: 'Completed' },
    hint: { zh: '变更收敛并归档结果', en: 'Change completed and archived' },
  },
] as const;

export const PRIMARY_WORKFLOW_INDEX = PRIMARY_WORKFLOW.reduce<Record<string, number>>((acc, step, index) => {
  acc[step.key] = index;
  return acc;
}, {});

export const OPTIONAL_VAR_KEYWORDS = ['group_name', 'family', 'description'];
export const ADDRESS_FAMILY_OPTIONS = [
  'ipv4 unicast',
  'ipv4 multicast',
  'ipv6 unicast',
  'ipv6 multicast',
  'vpnv4 unicast',
  'vpnv6 unicast',
  'l2vpn evpn',
  'ipv4-family unicast',
  'ipv4-family vpnv4',
  'ipv6-family unicast',
  'inet unicast',
  'inet6 unicast',
];
