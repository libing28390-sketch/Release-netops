import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ClipboardList, Plus, Search, X, RefreshCw, ChevronRight,
  Clock, CheckCircle2, XCircle, AlertTriangle, Send,
  FileText, Calendar, Shield, Zap, Eye,
  ArrowUpRight, ArrowDown, ArrowUp, Minus,
  User, Hash, Filter, Trash2,
  Copy, Bookmark, BookmarkCheck, Save, ChevronDown, SlidersHorizontal, Star,
  Users, UserCheck, Heart,
} from 'lucide-react';
import DateTimePicker from '../components/DateTimePicker';
import { AnimatePresence, motion } from 'motion/react';
import { sectionHeaderRowClass } from '../components/shared';
import Pagination from '../components/Pagination';
import type { User as UserOption, SessionUser, ConfigTemplate } from '../types';

/* ═══════════════════════════════════════════════════════════════════
   Types
   ═══════════════════════════════════════════════════════════════════ */

interface ChangeOrder {
  id: string;
  order_number: string;
  title: string;
  description: string;
  order_type: string;
  priority: string;
  status: string;
  requester_id: string;
  requester_username: string;
  assigned_initial_reviewer_id: string;
  assigned_initial_reviewer_username: string;
  assigned_final_approver_id: string;
  assigned_final_approver_username: string;
  initial_reviewer_id: string;
  initial_reviewer_username: string;
  final_approver_id: string;
  final_approver_username: string;
  approver_id: string;
  approver_username: string;
  target_devices: { hostname: string; ip_address: string; username?: string; platform?: string }[];
  commands: string[];
  command_template?: unknown;
  rollback_plan: string;
  risk_level: string;
  scheduled_start: string;
  scheduled_end: string;
  actual_start: string;
  actual_end: string;
  result_summary: string;
  result_detail: Record<string, unknown>;
  authorization_exempt?: boolean;
  rejected_reason: string;
  created_at: string;
  updated_at: string;
}

interface TimelineEvent {
  id: string;
  event_type: string;
  summary: string;
  actor_username: string;
  created_at: string;
}

interface Summary {
  total: number;
  by_status: Record<string, number>;
  by_priority: Record<string, number>;
  by_type: Record<string, number>;
}

interface DeviceOption {
  id: string;
  hostname: string;
  ip_address: string;
  platform?: string;
  asset_tag?: string;
}

interface ScenarioPhasePreview {
  pre_check: string[];
  execute: string[];
  post_check: string[];
  rollback: string[];
}

interface ScenarioVariable {
  key: string;
  label: string;
  label_zh?: string;
  type: string;
  required: boolean;
  placeholder?: string;
  options?: string[];
  platform_hints?: Record<string, string>;
}

interface ScenarioTemplate {
  id: string;
  name: string;
  name_zh?: string;
  description?: string;
  description_zh?: string;
  category?: string;
  icon?: string;
  risk?: string;
  supported_platforms?: string[];
  default_platform?: string;
  variables?: ScenarioVariable[];
  platform_phases?: Record<string, Partial<ScenarioPhasePreview>>;
}

interface PlatformMeta {
  name?: string;
  vendor?: string;
  icon?: string;
}

interface CommandTemplateSnapshot {
  mode?: 'template';
  scenario_id: string;
  scenario_name?: string;
  scenario_name_zh?: string;
  platform: string;
  variables: Record<string, string>;
  preview: ScenarioPhasePreview;
  generated_at?: string;
}

interface Props {
  language: string;
  t: (key: string) => string;
  users: UserOption[];
  scenarios: ScenarioTemplate[];
  configTemplates: ConfigTemplate[];
  platforms: Record<string, PlatformMeta>;
  currentUser: SessionUser;
  initialView?: 'all' | 'group_todo' | 'my_todo' | 'my_participated' | 'my_focus' | 'my_drafts' | 'create';
}

/* ═══════════════════════════════════════════════════════════════════
   Constants & Design Tokens
   ═══════════════════════════════════════════════════════════════════ */

const STATUS_META: Record<string, { label: { zh: string; en: string }; dot: string; bg: string; ring: string }> = {
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
  // Legacy statuses for compatibility with existing data
  pending:             { label: { zh: '待审批(旧)', en: 'Pending (Legacy)' },   dot: 'bg-amber-400',   bg: 'bg-amber-50',    ring: 'ring-amber-200' },
  executing:           { label: { zh: '执行中(旧)', en: 'Executing (Legacy)' }, dot: 'bg-cyan-400',    bg: 'bg-cyan-50',     ring: 'ring-cyan-200' },
};

const PRIORITY_META: Record<string, { label: { zh: string; en: string }; icon: React.ElementType; color: string; bg: string }> = {
  critical: { label: { zh: '紧急', en: 'Critical' }, icon: ArrowUp,       color: 'text-rose-600',   bg: 'bg-rose-50' },
  high:     { label: { zh: '高', en: 'High' },       icon: ArrowUpRight,  color: 'text-orange-600', bg: 'bg-orange-50' },
  medium:   { label: { zh: '中', en: 'Medium' },     icon: Minus,         color: 'text-amber-600',  bg: 'bg-amber-50' },
  low:      { label: { zh: '低', en: 'Low' },        icon: ArrowDown,     color: 'text-slate-500',  bg: 'bg-slate-50' },
};

const ORDER_TYPE_META: Record<string, { label: { zh: string; en: string } }> = {
  config_change:    { label: { zh: '配置变更', en: 'Config Change' } },
  firmware_upgrade: { label: { zh: '固件升级', en: 'Firmware Upgrade' } },
  maintenance:      { label: { zh: '维护操作', en: 'Maintenance' } },
  emergency:        { label: { zh: '紧急变更', en: 'Emergency' } },
  other:            { label: { zh: '其他', en: 'Other' } },
};

const RISK_META: Record<string, { label: { zh: string; en: string }; color: string }> = {
  low:    { label: { zh: '低风险', en: 'Low Risk' },      color: 'text-emerald-600' },
  medium: { label: { zh: '中风险', en: 'Medium Risk' },   color: 'text-amber-600' },
  high:   { label: { zh: '高风险', en: 'High Risk' },     color: 'text-rose-600' },
};

const EMPTY_FORM = {
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
};

const DEFAULT_PAGE_SIZE = 20;
const EMPTY_TEMPLATE_PREVIEW: ScenarioPhasePreview = {
  pre_check: [],
  execute: [],
  post_check: [],
  rollback: [],
};

/* ═══════════════════════════════════════════════════════════════════
   Helpers
   ═══════════════════════════════════════════════════════════════════ */

const fmtTime = (iso: string) => {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  } catch { return iso; }
};

const fmtDate = (iso: string) => {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  } catch { return iso; }
};

const statusLabel = (status: string, lang: string) =>
  STATUS_META[status]?.label?.[lang === 'zh' ? 'zh' : 'en'] ?? status;

const priorityLabel = (priority: string, lang: string) =>
  PRIORITY_META[priority]?.label?.[lang === 'zh' ? 'zh' : 'en'] ?? priority;

const typeLabel = (type: string, lang: string) =>
  ORDER_TYPE_META[type]?.label?.[lang === 'zh' ? 'zh' : 'en'] ?? type;

const riskLabel = (risk: string, lang: string) =>
  RISK_META[risk]?.label?.[lang === 'zh' ? 'zh' : 'en'] ?? risk;

const hasChangeGroup = (user: UserOption, groupKey: string) =>
  Array.isArray(user.change_groups) && user.change_groups.includes(groupKey);

const buildUserOptionLabel = (user: UserOption) =>
  [user.username, user.group_name].filter(Boolean).join(' · ');

const isCommandTemplateSnapshot = (value: unknown): value is CommandTemplateSnapshot => {
  if (!value || typeof value !== 'object') return false;
  const record = value as Record<string, unknown>;
  return typeof record.scenario_id === 'string' && typeof record.platform === 'string';
};

const TIMELINE_EVENT_META: Record<string, { zh: string; en: string }> = {
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
};

const timelineEventLabel = (eventType: string, lang: string) =>
  TIMELINE_EVENT_META[eventType]?.[lang === 'zh' ? 'zh' : 'en'] ?? eventType;

type WorkflowVisualState = 'done' | 'current' | 'pending' | 'error';

const PRIMARY_WORKFLOW = [
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

const PRIMARY_WORKFLOW_INDEX = PRIMARY_WORKFLOW.reduce<Record<string, number>>((acc, step, index) => {
  acc[step.key] = index;
  return acc;
}, {});

const normalizeWorkflowStatus = (status: string) => {
  if (status === 'pending') return 'initial_review';
  if (status === 'executing') return 'implementing';
  return status;
};

const buildWorkflowPresentation = (order: ChangeOrder, lang: string) => {
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

/* ═══════════════════════════════════════════════════════════════════
   Component
   ═══════════════════════════════════════════════════════════════════ */

const ChangeOrderTab: React.FC<Props> = ({ language, t, users, scenarios, configTemplates, platforms, currentUser, initialView }) => {
  const zh = language === 'zh';
  const isCreateView = initialView === 'create';
  const navigate = useNavigate();

  // ── Data state ──
  const [orders, setOrders] = useState<ChangeOrder[]>([]);
  const [total, setTotal] = useState(0);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);

  // ── Filters ──
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [priorityFilter, setPriorityFilter] = useState('');
  const [requesterFilter, setRequesterFilter] = useState('');
  const [assigneeFilter, setAssigneeFilter] = useState('');
  const [bookmarkFilter, setBookmarkFilter] = useState(false);
  const [showAdvancedSearch, setShowAdvancedSearch] = useState(false);
  const [orderTypeFilter, setOrderTypeFilter] = useState('');
  const [createdFrom, setCreatedFrom] = useState('');
  const [createdTo, setCreatedTo] = useState('');
  const [completedFrom, setCompletedFrom] = useState('');
  const [completedTo, setCompletedTo] = useState('');
  const [scheduledFrom, setScheduledFrom] = useState('');
  const [scheduledTo, setScheduledTo] = useState('');
  const [viewTab, setViewTab] = useState<'all' | 'group_todo' | 'my_todo' | 'my_focus' | 'my_participated' | 'my_drafts'>(initialView && initialView !== 'create' ? initialView : 'all');

  // Sync viewTab when sidebar navigation changes
  useEffect(() => {
    if (initialView && initialView !== 'create') setViewTab(initialView);
  }, [initialView]);

  // ── Bookmarks ──
  const [bookmarkedIds, setBookmarkedIds] = useState<Set<string>>(new Set());
  // ── Detail panel ──
  const [selectedOrder, setSelectedOrder] = useState<ChangeOrder | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [timelineLoading, setTimelineLoading] = useState(false);

  // ── Create/Edit modal ──
  const [showCreateModal, setShowCreateModal] = useState(initialView === 'create');
  const [editingOrder, setEditingOrder] = useState<ChangeOrder | null>(null);

  useEffect(() => {
    if (initialView !== 'create') {
      setShowCreateModal(false);
    }
  }, [initialView]);
  const [form, setForm] = useState(() => ({ ...EMPTY_FORM, authorization_exempt: currentUser.role === 'Administrator' }));
  const [saving, setSaving] = useState(false);
  const [commandInput, setCommandInput] = useState('');
  const [deviceInput, setDeviceInput] = useState({ hostname: '', ip_address: '' });
  const [deviceKeyword, setDeviceKeyword] = useState('');
  const [deviceOptions, setDeviceOptions] = useState<DeviceOption[]>([]);
  const [deviceLoading, setDeviceLoading] = useState(false);
  const [commandMode, setCommandMode] = useState<'manual' | 'template'>('manual');
  const [selectedScenarioId, setSelectedScenarioId] = useState('');
  const [selectedScenarioPlatform, setSelectedScenarioPlatform] = useState('');
  const [templateVariables, setTemplateVariables] = useState<Record<string, string>>({});
  const [templatePreview, setTemplatePreview] = useState<ScenarioPhasePreview | null>(null);
  const [templatePreviewLoading, setTemplatePreviewLoading] = useState(false);
  const [templatePreviewError, setTemplatePreviewError] = useState('');
  const [showDevicePicker, setShowDevicePicker] = useState(false);
  const [selectedInventoryDevice, setSelectedInventoryDevice] = useState<DeviceOption | null>(null);

  const isPrivilegedDefault = currentUser.role === 'Administrator';

  // ── Toast ──
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null);

  const showToast = useCallback((msg: string, type: 'success' | 'error' = 'success') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3000);
  }, []);

  const authHeaders = useCallback((withJson = false) => {
    const token = localStorage.getItem('netops_token');
    return {
      ...(withJson ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    };
  }, []);

  const resetTemplateComposer = useCallback(() => {
    setCommandMode('manual');
    setSelectedScenarioId('');
    setSelectedScenarioPlatform('');
    setTemplateVariables({});
    setTemplatePreview(null);
    setTemplatePreviewError('');
    setTemplatePreviewLoading(false);
  }, []);

  const resetEditorState = useCallback(() => {
    setEditingOrder(null);
    setForm({ ...EMPTY_FORM, authorization_exempt: isPrivilegedDefault });
    setCommandInput('');
    setDeviceInput({ hostname: '', ip_address: '' });
    setDeviceKeyword('');
    setDeviceOptions([]);
    setShowDevicePicker(false);
    setSelectedInventoryDevice(null);
    resetTemplateComposer();
  }, [isPrivilegedDefault, resetTemplateComposer]);

  const closeEditor = useCallback(() => {
    resetEditorState();
    setShowCreateModal(false);
    if (isCreateView) {
      navigate('/change-orders/all');
      return;
    }
  }, [isCreateView, navigate, resetEditorState]);

  const getDefaultPrePostCheck = (platformKey: string): { pre_check: string[]; post_check: string[] } => {
    const prePostMap: Record<string, { pre_check: string[]; post_check: string[] }> = {
      'cisco_ios': { 
        pre_check: ['show version', 'show running-config | include interface'], 
        post_check: ['show running-config | include interface', 'show interfaces status'] 
      },
      'cisco_nxos': { 
        pre_check: ['show version', 'show running-config | include interface'], 
        post_check: ['show running-config | include interface', 'show interface status'] 
      },
      'cisco_iosxr': { 
        pre_check: ['show version', 'show running-config | include interface'], 
        post_check: ['show running-config | include interface', 'show interfaces'] 
      },
      'huawei_vrp': { 
        pre_check: ['display version', 'display current-configuration | include interface'], 
        post_check: ['display current-configuration | include interface', 'display interface'] 
      },
      'h3c_comware': { 
        pre_check: ['display version', 'display current-configuration | include interface'], 
        post_check: ['display current-configuration | include interface', 'display interface'] 
      },
      'arista_eos': { 
        pre_check: ['show version', 'show running-config | include interface'], 
        post_check: ['show running-config | include interface', 'show interfaces status'] 
      },
      'juniper_junos': { 
        pre_check: ['show version', 'show configuration | display set | grep interface'], 
        post_check: ['show configuration | display set | grep interface', 'show interfaces'] 
      },
    };
    return prePostMap[platformKey] || { pre_check: [], post_check: [] };
  };

  const scenarioOptions = useMemo(() => {
    if (configTemplates && configTemplates.length > 0) {
      return configTemplates
        .filter((item) => item && item.id && item.name)
        .map((template) => {
          const matchedPlatforms = Object.entries(platforms)
            .filter(([, meta]) => !template.vendor || meta.vendor === template.vendor)
            .map(([key]) => key);
          const supportedPlatforms = matchedPlatforms.length > 0 ? matchedPlatforms : Object.keys(platforms);
          const phases: Record<string, Partial<ScenarioPhasePreview>> = {};
          supportedPlatforms.forEach((platformKey) => {
            const { pre_check, post_check } = getDefaultPrePostCheck(platformKey);
            phases[platformKey] = {
              pre_check,
              execute: template.content ? [template.content] : [],
              post_check,
              rollback: [],
            };
          });
          return {
            id: template.id,
            name: template.name,
            name_zh: template.name,
            description: template.category || '',
            description_zh: template.category || '',
            category: template.category,
            icon: '📄',
            risk: 'medium',
            supported_platforms: supportedPlatforms,
            default_platform: supportedPlatforms[0] || '',
            variables: [],
            platform_phases: phases,
          } as ScenarioTemplate;
        });
    }
    return scenarios.filter((item) => item && item.id && item.platform_phases && Object.keys(item.platform_phases).length > 0);
  }, [configTemplates, platforms, scenarios]);

  const selectedScenario = useMemo(
    () => scenarioOptions.find((item) => item.id === selectedScenarioId) || null,
    [scenarioOptions, selectedScenarioId],
  );

  const selectedScenarioVariables = useMemo(
    () => (selectedScenario?.variables || []).filter((item) => item?.key),
    [selectedScenario],
  );

  const selectedScenarioPlatforms = useMemo(() => {
    if (!selectedScenario) return [] as string[];
    if (selectedScenario.supported_platforms?.length) return selectedScenario.supported_platforms;
    return Object.keys(selectedScenario.platform_phases || {});
  }, [selectedScenario]);

  const platformLabel = useCallback((platformKey: string) => {
    if (!platformKey) return zh ? '未指定平台' : 'Unknown platform';
    const meta = platforms[platformKey] || {};
    const baseLabel = meta.name || platformKey;
    if (meta.icon && meta.vendor) return `${meta.icon} ${meta.vendor} · ${baseLabel}`;
    if (meta.icon) return `${meta.icon} ${baseLabel}`;
    if (meta.vendor) return `${meta.vendor} · ${baseLabel}`;
    return baseLabel;
  }, [platforms, zh]);

  const variableLabel = useCallback((variable: ScenarioVariable) => {
    if (zh) return variable.label_zh || variable.label || variable.key;
    return variable.label || variable.key;
  }, [zh]);

  const templateMissingRequired = useMemo(() => selectedScenarioVariables
    .filter((item) => item.required && !String(templateVariables[item.key] ?? '').trim())
    .map((item) => variableLabel(item)), [selectedScenarioVariables, templateVariables, variableLabel]);

  const assignTemplateVariable = useCallback((key: string, value: string) => {
    setTemplateVariables((current) => ({ ...current, [key]: value }));
  }, []);

  const initialReviewerOptions = useMemo(() => {
    const grouped = users.filter((item) => item.role !== 'Viewer' && hasChangeGroup(item, 'initial_reviewer') && String(item.id) !== String(currentUser.id));
    const fallback = users.filter((item) => item.role !== 'Viewer' && String(item.id) !== String(currentUser.id));
    return grouped.length > 0 ? grouped : fallback;
  }, [users, currentUser.id]);

  const finalApproverOptions = useMemo(() => {
    const grouped = users.filter((item) => item.role === 'Administrator' && hasChangeGroup(item, 'final_approver') && String(item.id) !== String(currentUser.id));
    const fallback = users.filter((item) => item.role === 'Administrator' && String(item.id) !== String(currentUser.id));
    return grouped.length > 0 ? grouped : fallback;
  }, [users, currentUser.id]);

  const assignReviewer = useCallback((stage: 'initial' | 'final', reviewerId: string) => {
    const source = stage === 'initial' ? initialReviewerOptions : finalApproverOptions;
    const reviewer = source.find((item) => String(item.id) === reviewerId);
    if (stage === 'initial') {
      setForm((current) => {
        if (current.assigned_final_approver_id && current.assigned_final_approver_id === reviewerId) {
          showToast(zh ? '初审人不能与终审人相同' : 'Initial reviewer cannot be the same as final approver', 'error');
          return current;
        }
        return {
          ...current,
          assigned_initial_reviewer_id: reviewerId,
          assigned_initial_reviewer_username: reviewer?.username || '',
        };
      });
      return;
    }
    setForm((current) => {
      if (current.assigned_initial_reviewer_id && current.assigned_initial_reviewer_id === reviewerId) {
        showToast(zh ? '终审人不能与初审人相同' : 'Final approver cannot be the same as initial reviewer', 'error');
        return current;
      }
      return {
        ...current,
        assigned_final_approver_id: reviewerId,
        assigned_final_approver_username: reviewer?.username || '',
      };
    });
  }, [finalApproverOptions, initialReviewerOptions, zh, showToast]);

  useEffect(() => {
    if (commandMode !== 'template') return;
    if (!selectedScenario) {
      setTemplatePreview(null);
      setTemplatePreviewError('');
      return;
    }
    setSelectedScenarioPlatform((current) => {
      if (current && selectedScenarioPlatforms.includes(current)) return current;
      return selectedScenario.default_platform || selectedScenarioPlatforms[0] || '';
    });
    setTemplateVariables((current) => {
      const next: Record<string, string> = {};
      selectedScenarioVariables.forEach((item) => {
        next[item.key] = String(current[item.key] ?? '');
      });
      return next;
    });
  }, [commandMode, selectedScenario, selectedScenarioPlatforms, selectedScenarioVariables]);

  useEffect(() => {
    if (commandMode !== 'template' || !selectedScenario) return;
    const defaultPlatform = selectedScenario.default_platform || selectedScenario.supported_platforms?.[0];
    if (defaultPlatform && !selectedScenarioPlatform) {
      setSelectedScenarioPlatform(defaultPlatform);
    }
  }, [selectedScenarioId, commandMode, selectedScenario, selectedScenarioPlatform]);

  // ── Auto-detect scenario from device platform ──
  useEffect(() => {
    if (commandMode !== 'template' || selectedScenarioId) return;
    const deviceWithPlatform = form.target_devices.find((dev) => dev.platform);
    
    console.log('[AutoDetect] Mode:', commandMode, 'Has scenario:', !!selectedScenarioId, 'Device platform:', deviceWithPlatform?.platform);
    console.log('[AutoDetect] Available scenarios:', scenarioOptions.length, scenarioOptions.map(s => ({ id: s.id, name: s.name, platforms: s.supported_platforms?.slice(0, 3) })));
    
    if (!deviceWithPlatform?.platform) {
      console.log('[AutoDetect] No device platform found');
      return;
    }

    const matchedScenario = scenarioOptions.find((scenario) => {
      const supportedPlatforms = scenario.supported_platforms?.length
        ? scenario.supported_platforms
        : Object.keys(scenario.platform_phases || {});
      const isMatch = supportedPlatforms.some((p) => findMatchingPlatform(deviceWithPlatform.platform || '', [p]));
      console.log('[AutoDetect] Scenario', scenario.name, 'supports', supportedPlatforms.slice(0, 3), '... match?', isMatch);
      return isMatch;
    });

    if (matchedScenario) {
      console.log('[AutoDetect] Matched scenario:', matchedScenario.id, matchedScenario.name);
      setSelectedScenarioId(matchedScenario.id);
      const platformsList = matchedScenario.supported_platforms?.length
        ? matchedScenario.supported_platforms
        : Object.keys(matchedScenario.platform_phases || {});
      const matchedPlatform = findMatchingPlatform(deviceWithPlatform.platform || '', platformsList);
      console.log('[AutoDetect] Matched platform:', matchedPlatform);
      if (matchedPlatform) {
        setSelectedScenarioPlatform(matchedPlatform);
      }
    } else {
      console.log('[AutoDetect] No matching scenario found for platform:', deviceWithPlatform.platform);
    }
  }, [commandMode, selectedScenarioId, form.target_devices, scenarioOptions]);


  const normalizePlatformKey = (value: string) => String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
  const findMatchingPlatform = (input: string, candidates: string[]) => {
    const normalized = normalizePlatformKey(input);
    if (!normalized) return '';
    const exact = candidates.find((candidate) => normalizePlatformKey(candidate) === normalized);
    if (exact) return exact;
    return candidates.find((candidate) => normalizePlatformKey(candidate).includes(normalized) || normalized.includes(normalizePlatformKey(candidate))) || '';
  };

  const renderTemplateText = (templateText: string, vars: Record<string, string>) => {
    let text = templateText;
    Object.entries(vars).forEach(([key, value]) => {
      text = text.replace(new RegExp(`{{\\s*${key}\\s*}}`, 'g'), String(value));
    });
    text = text.replace(/\{\%.*?\%\}/g, '');
    text = text.replace(/\{\{.*?\}\}/g, '');
    return text.trim();
  };

  const renderPhaseCommands = (phaseTemplates: string[] = [], vars: Record<string, string>) => {
    const commands: string[] = [];
    phaseTemplates.forEach((tmpl) => {
      const rendered = renderTemplateText(tmpl, vars);
      rendered.split('\n').forEach((line) => {
        const trimmed = line.trimEnd();
        if (trimmed) {
          commands.push(trimmed);
        }
      });
    });
    return commands;
  };

  const getLocalTemplatePreview = () => {
    if (!selectedScenario || !selectedScenarioPlatform) return null;
    const phases = selectedScenario.platform_phases?.[selectedScenarioPlatform] || {};
    return {
      pre_check: renderPhaseCommands(phases.pre_check || [], templateVariables),
      execute: renderPhaseCommands(phases.execute || [], templateVariables),
      post_check: renderPhaseCommands(phases.post_check || [], templateVariables),
      rollback: renderPhaseCommands(phases.rollback || [], templateVariables),
    };
  };

  useEffect(() => {
    if (commandMode !== 'template' || !selectedScenario || selectedScenarioPlatform) return;
    const deviceWithPlatform = form.target_devices.find((dev) => dev.platform);
    if (!deviceWithPlatform?.platform) return;
    const platformsList = selectedScenario.supported_platforms?.length
      ? selectedScenario.supported_platforms
      : Object.keys(selectedScenario.platform_phases || {});
    const matchedPlatform = findMatchingPlatform(deviceWithPlatform.platform, platformsList);
    if (matchedPlatform) {
      setSelectedScenarioPlatform(matchedPlatform);
    }
  }, [commandMode, selectedScenario, selectedScenarioPlatform, form.target_devices]);

  const fetchTemplatePreview = useCallback(async () => {
    const effectiveScenarioPlatform = selectedScenarioPlatform || (selectedScenarioPlatforms.length === 1 ? selectedScenarioPlatforms[0] : '');
    if (commandMode !== 'template' || !selectedScenarioId || !effectiveScenarioPlatform) {
      setTemplatePreview(null);
      return;
    }
    setTemplatePreviewLoading(true);
    setTemplatePreviewError('');
    try {
      const resp = await fetch('/api/playbooks/preview', {
        method: 'POST',
        headers: authHeaders(true),
        body: JSON.stringify({
          scenario_id: selectedScenarioId,
          platform: effectiveScenarioPlatform,
          variables: templateVariables,
        }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        throw new Error(String(data.detail || resp.statusText || 'Preview failed'));
      }
      const preview = {
        pre_check: Array.isArray(data.pre_check) ? data.pre_check : [],
        execute: Array.isArray(data.execute) ? data.execute : [],
        post_check: Array.isArray(data.post_check) ? data.post_check : [],
        rollback: Array.isArray(data.rollback) ? data.rollback : [],
      };
      if (preview.execute.length === 0 && selectedScenario?.platform_phases) {
        const fallback = getLocalTemplatePreview();
        if (fallback) {
          setTemplatePreview(fallback);
          return;
        }
      }
      setTemplatePreview(preview);
    } catch (error) {
      const fallback = getLocalTemplatePreview();
      if (fallback) {
        setTemplatePreview(fallback);
        setTemplatePreviewError('');
      } else {
        setTemplatePreview(null);
        setTemplatePreviewError(error instanceof Error ? error.message : (zh ? '模板预览失败' : 'Template preview failed'));
      }
    } finally {
      setTemplatePreviewLoading(false);
    }
  }, [authHeaders, commandMode, selectedScenarioId, selectedScenarioPlatform, selectedScenarioPlatforms, selectedScenario, templateVariables, zh]);

  const editorVisible = isCreateView || showCreateModal;
  const hideDraftListWhenEditing = showCreateModal && viewTab === 'my_drafts' && editingOrder !== null;

  useEffect(() => {
    if (!editorVisible || commandMode !== 'template' || !selectedScenarioId) return;
    const timer = setTimeout(() => { fetchTemplatePreview(); }, 220);
    return () => clearTimeout(timer);
  }, [editorVisible, commandMode, selectedScenarioId, selectedScenarioPlatform, templateVariables, fetchTemplatePreview]);

  // ── Fetch ──
  const fetchOrders = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
      if (search) params.set('search', search);
      if (statusFilter) params.set('status', statusFilter);
      if (priorityFilter) params.set('priority', priorityFilter);
      if (requesterFilter) params.set('requester', requesterFilter);
      if (assigneeFilter) params.set('assignee', assigneeFilter);
      if (bookmarkFilter && currentUser.id) params.set('bookmarked', String(currentUser.id));
      if (orderTypeFilter) params.set('order_type', orderTypeFilter);
      if (createdFrom) params.set('created_from', createdFrom);
      if (createdTo) params.set('created_to', createdTo);
      if (completedFrom) params.set('completed_from', completedFrom);
      if (completedTo) params.set('completed_to', completedTo);
      if (scheduledFrom) params.set('scheduled_from', scheduledFrom);
      if (scheduledTo) params.set('scheduled_to', scheduledTo);
      // View tab specific filters
      if (viewTab === 'my_todo' && currentUser.username) {
        params.set('my_todo', currentUser.username);
      } else if (viewTab === 'group_todo' && Array.isArray(currentUser.change_groups) && currentUser.change_groups.length > 0) {
        params.set('group_todo', currentUser.change_groups.join(','));
      } else if (viewTab === 'my_focus' && currentUser.id) {
        params.set('bookmarked', String(currentUser.id));
      } else if (viewTab === 'my_participated' && currentUser.username) {
        params.set('my_participated', currentUser.username);
      } else if (viewTab === 'my_drafts' && currentUser.username) {
        params.set('my_drafts', currentUser.username);
      }
      const resp = await fetch(`/api/change-orders?${params}`, { headers: authHeaders() });
      const data = await resp.json();
      if (data.success) {
        setOrders(data.data);
        setTotal(data.total);
      }
    } catch (e: unknown) {
      showToast(zh ? '加载失败' : 'Load failed', 'error');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, search, statusFilter, priorityFilter, requesterFilter, assigneeFilter, bookmarkFilter, orderTypeFilter, createdFrom, createdTo, completedFrom, completedTo, scheduledFrom, scheduledTo, viewTab, currentUser.id, currentUser.username, currentUser.change_groups, zh, showToast, authHeaders]);

  const fetchBookmarks = useCallback(async () => {
    try {
      const resp = await fetch('/api/change-orders-bookmarks', { headers: authHeaders() });
      const data = await resp.json();
      if (data.success) setBookmarkedIds(new Set(data.data));
    } catch { /* ignore */ }
  }, [authHeaders]);

  const fetchSummary = useCallback(async () => {
    try {
      const resp = await fetch('/api/change-orders/summary', { headers: authHeaders() });
      const data = await resp.json();
      if (data.success) setSummary(data.data);
    } catch { /* ignore */ }
  }, [authHeaders]);

  const fetchTimeline = useCallback(async (orderId: string) => {
    setTimelineLoading(true);
    try {
      const resp = await fetch(`/api/change-orders/${orderId}/timeline`, { headers: authHeaders() });
      const data = await resp.json();
      if (data.success) setTimeline(Array.isArray(data.data) ? data.data : []);
      else setTimeline([]);
    } catch {
      setTimeline([]);
    } finally {
      setTimelineLoading(false);
    }
  }, [authHeaders]);

  useEffect(() => { fetchOrders(); }, [fetchOrders]);
  useEffect(() => { fetchSummary(); }, [fetchSummary]);
  useEffect(() => { fetchBookmarks(); }, [fetchBookmarks]);

  // ── Create / Update ──
  const saveOrder = async (closeAfterSave = true, asDraft = false) => {
    const effectiveScenarioPlatform = selectedScenarioPlatform || (selectedScenarioPlatforms.length === 1 ? selectedScenarioPlatforms[0] : '');
    // When no scenario selected, use local preview if available
    const localPreview = selectedScenarioId && selectedScenarioPlatform ? getLocalTemplatePreview() : null;
    const effectivePreview = templatePreview || localPreview;
    
    if (!form.title.trim()) {
      showToast(zh ? '请输入工单标题' : 'Title is required', 'error');
      return;
    }

    if (!asDraft) {
      if (!form.assigned_initial_reviewer_id) {
        showToast(zh ? '请指定初审人' : 'Assign an initial reviewer', 'error');
        return;
      }
      if (commandMode === 'manual' && form.commands.length === 0) {
        showToast(zh ? '请至少添加一条执行命令' : 'Add at least one command', 'error');
        return;
      }
      if (commandMode === 'template') {
        // Auto-match platform from device if not explicitly selected
        const devicePlatform = form.target_devices.find(d => d.platform)?.platform;
        const platformToUse = effectiveScenarioPlatform || devicePlatform || '';
        
        if (!selectedScenarioId && !platformToUse) {
          showToast(zh ? '请选择变更模板场景或添加有平台信息的目标设备' : 'Select a scenario or add a device with platform info', 'error');
          return;
        }
        if (selectedScenarioId && !effectiveScenarioPlatform && !platformToUse) {
          showToast(zh ? '无法确定目标平台' : 'Cannot determine target platform', 'error');
          return;
        }
        // Only validate template preview if scenario is selected
        if (selectedScenarioId) {
          if (templateMissingRequired.length > 0) {
            showToast(zh ? `请先填写必填变量：${templateMissingRequired.join('、')}` : `Fill required variables: ${templateMissingRequired.join(', ')}`, 'error');
            return;
          }
          if (!effectivePreview || effectivePreview.execute.length === 0) {
            showToast(zh ? '模板尚未生成可执行命令，请检查变量或模板配置' : 'No executable commands were generated, check variables or template config', 'error');
            return;
          }
        }
      }
    }

    setSaving(true);
    try {
      const payload: any = {
        ...form,
        status: asDraft ? 'draft' : 'initial_review',
        command_template: {},
        commands: form.commands,
        rollback_plan: form.rollback_plan,
      };

      if (commandMode === 'template' && selectedScenarioId && effectiveScenarioPlatform) {
        if (!selectedScenarioPlatform && selectedScenarioPlatforms.length === 1) {
          setSelectedScenarioPlatform(effectiveScenarioPlatform);
        }
        payload.command_template = {
          scenario_id: selectedScenarioId,
          platform: effectiveScenarioPlatform,
          variables: templateVariables,
        };
        if (effectivePreview?.execute?.length) {
          payload.commands = effectivePreview.execute;
        }
        payload.rollback_plan = (effectivePreview?.rollback || []).join('\n') || form.rollback_plan;
      } else if (commandMode === 'template') {
        // Template mode but no scenario selected; use device platform
        const devicePlatform = form.target_devices.find(d => d.platform)?.platform || '';
        if (devicePlatform) {
          payload.command_template = {
            scenario_id: '',
            platform: devicePlatform,
            variables: {},
          };
        }
      }

      const url = editingOrder ? `/api/change-orders/${editingOrder.id}` : '/api/change-orders';
      const method = editingOrder ? 'PUT' : 'POST';
      const resp = await fetch(url, {
        method,
        headers: authHeaders(true),
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (data.success) {
        if (asDraft) {
          showToast(zh ? '草稿已保存' : 'Draft saved');
        } else if (editingOrder) {
          showToast(data.message || (zh ? '工单已提交' : 'Order submitted'));
        } else {
          showToast(data.message || (zh ? '工单已创建' : 'Order created'));
        }
        if (editingOrder === null && !asDraft && data.data) {
          setEditingOrder(data.data);
        }
        if (editingOrder === null && asDraft && data.data) {
          setEditingOrder(data.data);
        }
        if (closeAfterSave && !asDraft) {
          closeEditor();
        }
        fetchOrders();
        fetchSummary();
        if (asDraft) {
          if (!isCreateView) {
            closeEditor();
          } else {
            setShowCreateModal(false);
            resetEditorState();
          }
          navigate('/change-orders/drafts');
        }
      } else {
        showToast(data.detail || data.message || 'Error', 'error');
      }
    } catch {
      showToast(zh ? '保存失败' : 'Save failed', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleSave = () => saveOrder(true, false);
  const handleSaveDraft = () => saveOrder(true, true);

  // ── Status Transition ──
  const handleTransition = async (orderId: string, status: string, extra?: Record<string, unknown>) => {
    try {
      const resp = await fetch(`/api/change-orders/${orderId}/transition`, {
        method: 'POST',
        headers: authHeaders(true),
        body: JSON.stringify({ status, ...extra }),
      });
      const data = await resp.json();
      if (data.success) {
        showToast(data.message || (zh ? '状态已更新' : 'Status updated'));
        if (selectedOrder?.id === orderId) {
          setSelectedOrder(data.data);
          fetchTimeline(orderId);
        }
        fetchOrders();
        fetchSummary();
      } else {
        showToast(data.detail || 'Error', 'error');
      }
    } catch { showToast(zh ? '操作失败' : 'Failed', 'error'); }
  };

  // ── Delete ──
  const handleDelete = async (orderId: string) => {
    if (!confirm(zh ? '确定删除此工单？' : 'Delete this change order?')) return;
    try {
      const resp = await fetch(`/api/change-orders/${orderId}`, { method: 'DELETE', headers: authHeaders() });
      const data = await resp.json();
      if (data.success) {
        showToast(data.message || (zh ? '已删除' : 'Deleted'));
        if (selectedOrder?.id === orderId) {
          setSelectedOrder(null);
          setTimeline([]);
        }
        fetchOrders();
        fetchSummary();
      } else {
        showToast(data.detail || 'Error', 'error');
      }
    } catch { showToast(zh ? '删除失败' : 'Delete failed', 'error'); }
  };

  // ── Bookmark ──
  const handleToggleBookmark = async (orderId: string) => {
    try {
      const resp = await fetch(`/api/change-orders/${orderId}/bookmark`, { method: 'POST', headers: authHeaders() });
      const data = await resp.json();
      if (data.success) {
        setBookmarkedIds(prev => {
          const next = new Set(prev);
          if (data.data.bookmarked) { next.add(orderId); } else { next.delete(orderId); }
          return next;
        });
        showToast(data.data.bookmarked ? (zh ? '已收藏' : 'Bookmarked') : (zh ? '已取消收藏' : 'Unbookmarked'));
      }
    } catch { showToast(zh ? '操作失败' : 'Failed', 'error'); }
  };

  // ── Copy order → open create modal pre-filled ──
  const handleCopyOrder = (order: ChangeOrder) => {
    setEditingOrder(null);
    setForm({
      title: `${order.title} (${zh ? '副本' : 'Copy'})`,
      description: order.description,
      order_type: order.order_type,
      priority: order.priority,
      target_devices: order.target_devices || [],
      commands: order.commands || [],
      rollback_plan: order.rollback_plan,
      risk_level: order.risk_level,
      scheduled_start: order.scheduled_start,
      scheduled_end: order.scheduled_end,
      assigned_initial_reviewer_id: '',
      assigned_initial_reviewer_username: '',
      assigned_final_approver_id: '',
      assigned_final_approver_username: '',
    });
    setCommandInput('');
    setShowCreateModal(true);
    showToast(zh ? '工单内容已复制，请修改后提交' : 'Order copied, edit and submit');
  };

  // ── Save as template ──
  const handleSaveAsTemplate = async (order: ChangeOrder) => {
    const name = prompt(zh ? '请输入模板名称' : 'Template name:', order.title);
    if (!name) return;
    const description = prompt(zh ? '模板描述（可选）' : 'Description (optional):', '') || '';
    try {
      const resp = await fetch('/api/change-order-templates', {
        method: 'POST',
        headers: authHeaders(true),
        body: JSON.stringify({ order_id: order.id, name, description }),
      });
      const data = await resp.json();
      if (data.success) {
        showToast(data.message || (zh ? '模板已保存' : 'Template saved'));
      } else {
        showToast(data.detail || 'Error', 'error');
      }
    } catch { showToast(zh ? '保存失败' : 'Save failed', 'error'); }
  };

  // ── Advanced search active count ──
  const advancedFilterCount = [requesterFilter, assigneeFilter, bookmarkFilter, orderTypeFilter, createdFrom, createdTo, completedFrom, completedTo, scheduledFrom, scheduledTo].filter(Boolean).length;

  // ── Detail ──
  const openDetail = async (order: ChangeOrder) => {
    setDetailLoading(true);
    setSelectedOrder(order);
    setTimeline([]);
    try {
      const resp = await fetch(`/api/change-orders/${order.id}`, { headers: authHeaders() });
      const data = await resp.json();
      if (data.success) setSelectedOrder(data.data);
    } catch { /* keep summary data */ }
    finally {
      setDetailLoading(false);
      fetchTimeline(order.id);
    }
  };

  // ── Edit ──
  const openEdit = (order: ChangeOrder) => {
    const templateSnapshot = isCommandTemplateSnapshot(order.command_template) ? order.command_template : null;
    setSelectedOrder(null);
    setEditingOrder(order);
    setForm({
      title: order.title,
      description: order.description,
      order_type: order.order_type,
      priority: order.priority,
      risk_level: order.risk_level,
      rollback_plan: order.rollback_plan,
      scheduled_start: order.scheduled_start,
      scheduled_end: order.scheduled_end,
      assigned_initial_reviewer_id: order.assigned_initial_reviewer_id || '',
      assigned_initial_reviewer_username: order.assigned_initial_reviewer_username || '',
      assigned_final_approver_id: order.assigned_final_approver_id || '',
      assigned_final_approver_username: order.assigned_final_approver_username || '',
      authorization_exempt: order.authorization_exempt ?? false,
      target_devices: order.target_devices || [],
      commands: order.commands || [],
    });
    if (templateSnapshot) {
      setCommandMode('template');
      setSelectedScenarioId(String(templateSnapshot.scenario_id || ''));
      setSelectedScenarioPlatform(String(templateSnapshot.platform || ''));
      setTemplateVariables(Object.fromEntries(
        Object.entries(templateSnapshot.variables || {}).map(([key, value]) => [key, String(value ?? '')]),
      ));
      setTemplatePreview(templateSnapshot.preview || EMPTY_TEMPLATE_PREVIEW);
      setTemplatePreviewError('');
    } else {
      resetTemplateComposer();
    }
    setShowCreateModal(true);
  };

  // ── Inventory device search for selectable target IP/device ──
  const fetchDeviceOptions = useCallback(async (keyword: string) => {
    if (!showDevicePicker) return;
    setDeviceLoading(true);
    try {
      const params = new URLSearchParams({ mode: 'light' });
      if (keyword.trim()) params.set('search', keyword.trim());
      const resp = await fetch(`/api/devices?${params.toString()}`, { headers: authHeaders() });
      const data = await resp.json();
      const rows = Array.isArray(data) ? data : (data?.data || []);
      const normalized: DeviceOption[] = (rows || [])
        .map((d: Record<string, unknown>) => ({
          id: String(d.id || ''),
          hostname: String(d.hostname || ''),
          ip_address: String(d.ip_address || ''),
          platform: String(d.platform || ''),
          asset_tag: String(d.asset_tag || ''),
        }))
        .filter((d: DeviceOption) => d.hostname || d.ip_address)
        .slice(0, 12);
      setDeviceOptions(normalized);
    } catch {
      setDeviceOptions([]);
    } finally {
      setDeviceLoading(false);
    }
  }, [showDevicePicker, authHeaders]);

  useEffect(() => {
    if (!editorVisible || !showDevicePicker) return;
    const timer = setTimeout(() => { fetchDeviceOptions(deviceKeyword); }, 250);
    return () => clearTimeout(timer);
  }, [deviceKeyword, editorVisible, showDevicePicker, fetchDeviceOptions]);

  const addDeviceFromInventory = (dev: DeviceOption) => {
    const next = { hostname: dev.hostname || '', ip_address: dev.ip_address || '', platform: dev.platform || '' };
    setForm((f) => {
      const exists = f.target_devices.some(
        (x) => (x.ip_address && next.ip_address && x.ip_address === next.ip_address)
          || (x.hostname && next.hostname && x.hostname === next.hostname)
      );
      if (exists) return f;
      return { ...f, target_devices: [...f.target_devices, next] };
    });
  };

  const confirmSelectedDevice = () => {
    if (!selectedInventoryDevice) return;
    addDeviceFromInventory(selectedInventoryDevice);
    
    if (commandMode === 'template' && selectedScenario && selectedInventoryDevice.platform) {
      const platformsList = selectedScenario.supported_platforms?.length 
        ? selectedScenario.supported_platforms 
        : Object.keys(selectedScenario.platform_phases || {});
      const matchedPlatform = findMatchingPlatform(selectedInventoryDevice.platform, platformsList);
      if (matchedPlatform) {
        setSelectedScenarioPlatform(matchedPlatform);
      }
    }
    
    setSelectedInventoryDevice(null);
    setShowDevicePicker(false);
    setDeviceKeyword('');
    setDeviceOptions([]);
  };

  // ── Add command ──
  const addCommand = () => {
    if (!commandInput.trim()) return;
    setForm(f => ({ ...f, commands: [...f.commands, commandInput.trim()] }));
    setCommandInput('');
  };

  // ── Add device ──
  const addDevice = () => {
    if (!deviceInput.hostname.trim() && !deviceInput.ip_address.trim()) return;
    setForm(f => ({
      ...f,
      target_devices: [
        ...f.target_devices.filter(
          d => !(d.hostname === deviceInput.hostname.trim() && d.ip_address === deviceInput.ip_address.trim())
        ),
        { hostname: deviceInput.hostname.trim(), ip_address: deviceInput.ip_address.trim() },
      ],
    }));
    setDeviceInput({ hostname: '', ip_address: '' });
  };

  // ── Summary cards ──
  const summaryCards = useMemo(() => {
    if (!summary) return [];
    const s = summary.by_status;
    return [
      { key: 'total',     value: summary.total,                             label: zh ? '全部工单' : 'Total',       icon: ClipboardList, color: 'text-slate-700',   iconBg: 'bg-slate-100' },
      { key: 'reviewing', value: (s.initial_review || 0) + (s.final_review || 0) + (s.pending || 0), label: zh ? '审核中' : 'Reviewing', icon: Clock, color: 'text-amber-600', iconBg: 'bg-amber-50' },
      { key: 'implementing',   value: (s.implementing || 0) + (s.executing || 0),                 label: zh ? '实施中' : 'Implementing',   icon: Zap,          color: 'text-cyan-600',    iconBg: 'bg-cyan-50' },
      { key: 'completed',      value: (s.completed || 0),                                          label: zh ? '变更完成' : 'Completed',    icon: CheckCircle2, color: 'text-emerald-600', iconBg: 'bg-emerald-50' },
      { key: 'rollback',       value: (s.rollback_in_progress || 0) + (s.rolled_back || 0),       label: zh ? '回溯' : 'Rollback',         icon: AlertTriangle,color: 'text-violet-600',  iconBg: 'bg-violet-50' },
    ];
  }, [summary, zh]);

  // ── Status transition buttons for detail panel ──
  const getTransitionActions = (order: ChangeOrder) => {
    const actions: { label: string; status: string; variant: string; icon: React.ElementType }[] = [];
    switch (order.status) {
      case 'draft':
        actions.push({ label: zh ? '提交初审' : 'Submit Review', status: 'initial_review', variant: 'primary', icon: Send });
        break;
      case 'initial_review':
        actions.push({ label: zh ? '初审通过' : 'Pass Initial Review', status: 'final_review', variant: 'success', icon: CheckCircle2 });
        actions.push({ label: zh ? '驳回' : 'Reject', status: 'rejected', variant: 'danger', icon: XCircle });
        break;
      case 'final_review':
        actions.push({ label: zh ? '审批通过' : 'Approve', status: 'approved', variant: 'success', icon: CheckCircle2 });
        actions.push({ label: zh ? '驳回' : 'Reject', status: 'rejected', variant: 'danger', icon: XCircle });
        break;
      case 'pending':
        actions.push({ label: zh ? '审批通过(旧)' : 'Approve (Legacy)', status: 'approved', variant: 'success', icon: CheckCircle2 });
        actions.push({ label: zh ? '驳回' : 'Reject', status: 'rejected', variant: 'danger', icon: XCircle });
        break;
      case 'approved':
        actions.push({ label: zh ? '进入实施' : 'Start Implementing', status: 'implementing', variant: 'primary', icon: Zap });
        break;
      case 'implementing':
      case 'executing':
        actions.push({ label: zh ? '标记完成' : 'Complete', status: 'completed', variant: 'success', icon: CheckCircle2 });
        actions.push({ label: zh ? '标记失败' : 'Failed', status: 'failed', variant: 'danger', icon: XCircle });
        actions.push({ label: zh ? '触发回溯' : 'Start Rollback', status: 'rollback_in_progress', variant: 'muted', icon: AlertTriangle });
        break;
      case 'failed':
        actions.push({ label: zh ? '发起回溯' : 'Rollback', status: 'rollback_in_progress', variant: 'muted', icon: AlertTriangle });
        break;
      case 'rollback_in_progress':
        actions.push({ label: zh ? '回溯完成' : 'Rollback Completed', status: 'rolled_back', variant: 'success', icon: CheckCircle2 });
        actions.push({ label: zh ? '回溯失败' : 'Rollback Failed', status: 'failed', variant: 'danger', icon: XCircle });
        break;
    }
    if (!['completed', 'cancelled', 'rolled_back'].includes(order.status)) {
      actions.push({ label: zh ? '取消' : 'Cancel', status: 'cancelled', variant: 'muted', icon: X });
    }
    return actions;
  };

  const variantBtnClass = (variant: string) => {
    switch (variant) {
      case 'primary': return 'bg-[#00bceb] text-white hover:bg-[#0096bd] shadow-lg shadow-[#00bceb]/16';
      case 'success': return 'bg-emerald-500 text-white hover:bg-emerald-600 shadow-lg shadow-emerald-500/16';
      case 'danger':  return 'bg-rose-500 text-white hover:bg-rose-600 shadow-lg shadow-rose-500/16';
      default:        return 'bg-white text-black/60 border border-black/10 hover:bg-black/5';
    }
  };

  /* ═════════════════════════════════════════════════════════════════
     Render
     ═════════════════════════════════════════════════════════════════ */

  return (
    <div className="flex flex-col gap-6">
      {/* ── Toast ── */}
      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            className={`fixed top-6 right-6 z-[9999] px-5 py-3 rounded-xl shadow-2xl text-sm font-medium ${
              toast.type === 'success'
                ? 'bg-emerald-500 text-white'
                : 'bg-rose-500 text-white'
            }`}
          >
            {toast.msg}
          </motion.div>
        )}
      </AnimatePresence>

      {!selectedOrder ? (
      <>
      {!isCreateView && !hideDraftListWhenEditing && (
        <>
          {/* ── Summary Cards ── */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            {summaryCards.map((card, idx) => (
              <motion.div
            key={card.key}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: idx * 0.05 }}
            className="bg-white rounded-2xl border border-black/5 p-4 shadow-sm hover:shadow-md transition-shadow cursor-default"
          >
            <div className="flex items-center justify-between">
              <div className={`p-2 rounded-xl ${card.iconBg}`}>
                <card.icon size={16} className={card.color} />
              </div>
              <span className={`text-2xl font-bold tabular-nums ${card.color}`}>{card.value}</span>
            </div>
            <p className="mt-2 text-xs text-black/45 font-medium">{card.label}</p>
          </motion.div>
        ))}
          </div>

          {/* ── Filters bar ── */}
          <div className="bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden">
        <div className="flex flex-wrap gap-3 items-center p-4">
          <div className="relative flex-1 min-w-[200px]">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-black/30" />
            <input
              value={search}
              onChange={e => { setSearch(e.target.value); setPage(1); }}
              placeholder={zh ? '搜索工单号 / 标题...' : 'Search order # / title...'}
              className="w-full pl-9 pr-8 py-2 text-sm bg-black/[0.02] border border-black/8 rounded-xl outline-none focus:border-[#00bceb]/40 focus:ring-2 focus:ring-[#00bceb]/10 transition-all"
            />
            {search && (
              <button title={zh ? '清空搜索' : 'Clear search'} onClick={() => { setSearch(''); setPage(1); }} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-black/30 hover:text-black/60">
                <X size={13} />
              </button>
            )}
          </div>
          <div className="flex items-center gap-1.5 text-black/40">
            <Filter size={13} />
          </div>
          <select
            title={zh ? '按状态筛选' : 'Filter by status'}
            value={statusFilter}
            onChange={e => { setStatusFilter(e.target.value); setPage(1); }}
            className="bg-white border border-black/10 rounded-xl px-3 py-2 text-xs outline-none focus:border-[#00bceb]/40"
          >
            <option value="">{zh ? '全部状态' : 'All Status'}</option>
            {Object.entries(STATUS_META).map(([k, v]) => (
              <option key={k} value={k}>{v.label[zh ? 'zh' : 'en']}</option>
            ))}
          </select>
          <select
            title={zh ? '按优先级筛选' : 'Filter by priority'}
            value={priorityFilter}
            onChange={e => { setPriorityFilter(e.target.value); setPage(1); }}
            className="bg-white border border-black/10 rounded-xl px-3 py-2 text-xs outline-none focus:border-[#00bceb]/40"
          >
            <option value="">{zh ? '全部优先级' : 'All Priority'}</option>
            {Object.entries(PRIORITY_META).map(([k, v]) => (
              <option key={k} value={k}>{v.label[zh ? 'zh' : 'en']}</option>
            ))}
          </select>
          <button
            onClick={() => setShowAdvancedSearch(v => !v)}
            className={`inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium border transition-all ${
              showAdvancedSearch || advancedFilterCount > 0
                ? 'bg-[#00bceb]/8 text-[#00bceb] border-[#00bceb]/20'
                : 'bg-white text-black/50 border-black/10 hover:border-[#00bceb]/30 hover:text-[#00bceb]'
            }`}
          >
            <SlidersHorizontal size={12} />
            {zh ? '高级筛选' : 'Advanced'}
            {advancedFilterCount > 0 && (
              <span className="ml-0.5 px-1.5 py-0.5 rounded-full text-[10px] font-bold bg-[#00bceb] text-white leading-none">{advancedFilterCount}</span>
            )}
            <ChevronDown size={11} className={`transition-transform ${showAdvancedSearch ? 'rotate-180' : ''}`} />
          </button>
          {/* Bookmark quick-filter */}
          <button
            onClick={() => { setBookmarkFilter(v => !v); setPage(1); }}
            title={zh ? '只看收藏' : 'Show bookmarked'}
            className={`p-2 rounded-xl border transition-all ${
              bookmarkFilter
                ? 'bg-amber-50 text-amber-500 border-amber-200'
                : 'bg-white text-black/35 border-black/10 hover:text-amber-500 hover:border-amber-200'
            }`}
          >
            {bookmarkFilter ? <BookmarkCheck size={14} /> : <Bookmark size={14} />}
          </button>
          {/* Refresh */}
          <button
            onClick={() => { fetchOrders(); fetchSummary(); fetchBookmarks(); }}
            className="p-2 rounded-xl border border-black/10 bg-white text-black/40 hover:text-[#00bceb] hover:border-[#00bceb]/30 transition-all"
            title={zh ? '刷新' : 'Refresh'}
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
        {/* ── Advanced search panel ── */}
        <AnimatePresence>
          {showAdvancedSearch && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden"
            >
              <div className="px-4 pb-4 pt-3 border-t border-black/5 space-y-3">
                {/* Row 1: Creator / Assignee / Order Type */}
                <div className="flex flex-wrap gap-3 items-end">
                  <div className="min-w-[170px]">
                    <label className="block text-[11px] font-semibold text-black/40 mb-1">{zh ? '创建人' : 'Creator'}</label>
                    <select
                      value={requesterFilter}
                      onChange={e => { setRequesterFilter(e.target.value); setPage(1); }}
                      title={zh ? '按创建人筛选' : 'Filter by creator'}
                      className="w-full bg-white border border-black/10 rounded-xl px-3 py-2 text-xs outline-none focus:border-[#00bceb]/40"
                    >
                      <option value="">{zh ? '全部创建人' : 'All Creators'}</option>
                      {users.map(u => (
                        <option key={u.id} value={u.username}>{u.username}{u.group_name ? ` · ${u.group_name}` : ''}</option>
                      ))}
                    </select>
                  </div>
                  <div className="min-w-[170px]">
                    <label className="block text-[11px] font-semibold text-black/40 mb-1">{zh ? '处理人' : 'Assignee'}</label>
                    <select
                      value={assigneeFilter}
                      onChange={e => { setAssigneeFilter(e.target.value); setPage(1); }}
                      title={zh ? '按处理人筛选' : 'Filter by assignee'}
                      className="w-full bg-white border border-black/10 rounded-xl px-3 py-2 text-xs outline-none focus:border-[#00bceb]/40"
                    >
                      <option value="">{zh ? '全部处理人' : 'All Assignees'}</option>
                      {users.filter(u => u.role !== 'Viewer').map(u => (
                        <option key={u.id} value={u.username}>{u.username}{u.group_name ? ` · ${u.group_name}` : ''}</option>
                      ))}
                    </select>
                  </div>
                  <div className="min-w-[170px]">
                    <label className="block text-[11px] font-semibold text-black/40 mb-1">{zh ? '工单类型' : 'Order Type'}</label>
                    <select
                      value={orderTypeFilter}
                      onChange={e => { setOrderTypeFilter(e.target.value); setPage(1); }}
                      title={zh ? '按类型筛选' : 'Filter by type'}
                      className="w-full bg-white border border-black/10 rounded-xl px-3 py-2 text-xs outline-none focus:border-[#00bceb]/40"
                    >
                      <option value="">{zh ? '全部类型' : 'All Types'}</option>
                      {Object.entries(ORDER_TYPE_META).map(([k, v]) => (
                        <option key={k} value={k}>{v.label[zh ? 'zh' : 'en']}</option>
                      ))}
                    </select>
                  </div>
                </div>
                {/* Row 2: Date range filters */}
                <div className="flex flex-wrap gap-3 items-end">
                  <div className="min-w-[170px]">
                    <label className="block text-[11px] font-semibold text-black/40 mb-1">{zh ? '创建时间（从）' : 'Created From'}</label>
                    <input
                      type="datetime-local"
                      value={createdFrom}
                      onChange={e => { setCreatedFrom(e.target.value); setPage(1); }}
                      title={zh ? '创建时间（从）' : 'Created From'}
                      className="w-full bg-white border border-black/10 rounded-xl px-3 py-2 text-xs outline-none focus:border-[#00bceb]/40"
                    />
                  </div>
                  <div className="min-w-[170px]">
                    <label className="block text-[11px] font-semibold text-black/40 mb-1">{zh ? '创建时间（至）' : 'Created To'}</label>
                    <input
                      type="datetime-local"
                      value={createdTo}
                      onChange={e => { setCreatedTo(e.target.value); setPage(1); }}
                      title={zh ? '创建时间（至）' : 'Created To'}
                      className="w-full bg-white border border-black/10 rounded-xl px-3 py-2 text-xs outline-none focus:border-[#00bceb]/40"
                    />
                  </div>
                  <div className="min-w-[170px]">
                    <label className="block text-[11px] font-semibold text-black/40 mb-1">{zh ? '完成时间（从）' : 'Completed From'}</label>
                    <input
                      type="datetime-local"
                      value={completedFrom}
                      onChange={e => { setCompletedFrom(e.target.value); setPage(1); }}
                      title={zh ? '完成时间（从）' : 'Completed From'}
                      className="w-full bg-white border border-black/10 rounded-xl px-3 py-2 text-xs outline-none focus:border-[#00bceb]/40"
                    />
                  </div>
                  <div className="min-w-[170px]">
                    <label className="block text-[11px] font-semibold text-black/40 mb-1">{zh ? '完成时间（至）' : 'Completed To'}</label>
                    <input
                      type="datetime-local"
                      value={completedTo}
                      onChange={e => { setCompletedTo(e.target.value); setPage(1); }}
                      title={zh ? '完成时间（至）' : 'Completed To'}
                      className="w-full bg-white border border-black/10 rounded-xl px-3 py-2 text-xs outline-none focus:border-[#00bceb]/40"
                    />
                  </div>
                </div>
                {/* Row 3: Scheduled range + Quick presets + Clear */}
                <div className="flex flex-wrap gap-3 items-end">
                  <div className="min-w-[170px]">
                    <label className="block text-[11px] font-semibold text-black/40 mb-1">{zh ? '计划开始（从）' : 'Scheduled From'}</label>
                    <input
                      type="datetime-local"
                      value={scheduledFrom}
                      onChange={e => { setScheduledFrom(e.target.value); setPage(1); }}
                      title={zh ? '计划开始（从）' : 'Scheduled From'}
                      className="w-full bg-white border border-black/10 rounded-xl px-3 py-2 text-xs outline-none focus:border-[#00bceb]/40"
                    />
                  </div>
                  <div className="min-w-[170px]">
                    <label className="block text-[11px] font-semibold text-black/40 mb-1">{zh ? '计划结束（至）' : 'Scheduled To'}</label>
                    <input
                      type="datetime-local"
                      value={scheduledTo}
                      onChange={e => { setScheduledTo(e.target.value); setPage(1); }}
                      title={zh ? '计划结束（至）' : 'Scheduled To'}
                      className="w-full bg-white border border-black/10 rounded-xl px-3 py-2 text-xs outline-none focus:border-[#00bceb]/40"
                    />
                  </div>
                  {/* Quick date presets */}
                  <div>
                    <label className="block text-[11px] font-semibold text-black/40 mb-1">{zh ? '快捷选择' : 'Quick Range'}</label>
                    <div className="flex gap-1.5">
                      {([
                        { label: zh ? '今天' : 'Today', days: 0 },
                        { label: zh ? '近7天' : '7d', days: 7 },
                        { label: zh ? '近30天' : '30d', days: 30 },
                        { label: zh ? '近90天' : '90d', days: 90 },
                      ] as const).map(preset => (
                        <button
                          key={preset.days}
                          onClick={() => {
                            const now = new Date();
                            const to = now.toISOString().slice(0, 16);
                            const from = preset.days === 0
                              ? new Date(now.getFullYear(), now.getMonth(), now.getDate()).toISOString().slice(0, 16)
                              : new Date(now.getTime() - preset.days * 86400000).toISOString().slice(0, 16);
                            setCreatedFrom(from);
                            setCreatedTo(to);
                            setPage(1);
                          }}
                          className="px-2.5 py-1.5 rounded-lg text-[11px] font-medium border border-black/8 bg-white text-black/50 hover:text-[#00bceb] hover:border-[#00bceb]/30 transition-all"
                        >
                          {preset.label}
                        </button>
                      ))}
                    </div>
                  </div>
                  {/* Clear all advanced filters */}
                  {advancedFilterCount > 0 && (
                    <button
                      onClick={() => {
                        setRequesterFilter(''); setAssigneeFilter(''); setBookmarkFilter(false);
                        setOrderTypeFilter('');
                        setCreatedFrom(''); setCreatedTo('');
                        setCompletedFrom(''); setCompletedTo('');
                        setScheduledFrom(''); setScheduledTo('');
                        setPage(1);
                      }}
                      className="px-3 py-2 rounded-xl text-xs font-medium text-rose-500 bg-rose-50 border border-rose-200 hover:bg-rose-100 transition-all"
                    >
                      {zh ? '清空高级筛选' : 'Clear advanced'}
                    </button>
                  )}
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
        </>
      )}

      {/* ── Table ── */}
      {!isCreateView && !hideDraftListWhenEditing && (
        <div className="min-w-0">
          <div className="bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden">
            {loading && orders.length === 0 ? (
              <div className="flex items-center justify-center py-24 text-black/30">
                <RefreshCw size={18} className="animate-spin mr-2" /> {zh ? '加载中...' : 'Loading...'}
              </div>
            ) : orders.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-24 text-black/30">
                <ClipboardList size={40} className="mb-3 opacity-30" />
                <p className="text-sm">{zh ? '暂无变更工单' : 'No change orders'}</p>
              </div>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-black/[0.02] border-b border-black/5 text-black/50 text-xs">
                        <th className="text-left px-4 py-3 font-semibold">{zh ? '工单号' : 'Order #'}</th>
                        <th className="text-left px-4 py-3 font-semibold">{zh ? '标题' : 'Title'}</th>
                        <th className="text-left px-4 py-3 font-semibold">{zh ? '类型' : 'Type'}</th>
                        <th className="text-center px-4 py-3 font-semibold">{zh ? '优先级' : 'Priority'}</th>
                        <th className="text-center px-4 py-3 font-semibold">{zh ? '状态' : 'Status'}</th>
                        <th className="text-left px-4 py-3 font-semibold">{zh ? '申请人' : 'Requester'}</th>
                        <th className="text-left px-4 py-3 font-semibold">{zh ? '创建时间' : 'Created'}</th>
                        <th className="text-center px-4 py-3 font-semibold">{zh ? '操作' : 'Actions'}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-black/[0.04]">
                      {orders.map((order) => {
                        const sm = STATUS_META[order.status] || STATUS_META.draft;
                        const pm = PRIORITY_META[order.priority] || PRIORITY_META.medium;
                        const PriorityIcon = pm.icon;
                        const isSelected = selectedOrder?.id === order.id;
                        return (
                          <tr
                            key={order.id}
                            onClick={() => openDetail(order)}
                            className={`cursor-pointer transition-colors ${
                              isSelected
                                ? 'bg-[#00bceb]/[0.04] ring-1 ring-inset ring-[#00bceb]/12'
                                : 'hover:bg-black/[0.015]'
                            }`}
                          >
                            <td className="px-4 py-3">
                              <span className="font-mono text-xs font-bold tracking-wide text-[#0e7490] inline-flex items-center gap-1">
                                {bookmarkedIds.has(order.id) && <Star size={10} className="text-amber-400 fill-amber-400 flex-shrink-0" />}
                                {order.order_number}
                              </span>
                            </td>
                            <td className="px-4 py-3 max-w-[200px]">
                              <span className="font-medium text-black/80 truncate block">{order.title}</span>
                            </td>
                            <td className="px-4 py-3">
                              <span className="text-xs text-black/50">{typeLabel(order.order_type, language)}</span>
                            </td>
                            <td className="px-4 py-3 text-center">
                              <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-xs font-medium ${pm.bg} ${pm.color}`}>
                                <PriorityIcon size={11} />
                                {priorityLabel(order.priority, language)}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-center">
                              <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ring-1 ${sm.bg} ${sm.ring}`}>
                                <span className={`w-1.5 h-1.5 rounded-full ${sm.dot}`} />
                                {statusLabel(order.status, language)}
                              </span>
                            </td>
                            <td className="px-4 py-3">
                              <span className="text-xs text-black/55">{order.requester_username || '—'}</span>
                            </td>
                            <td className="px-4 py-3">
                              <span className="text-xs text-black/40 tabular-nums">{fmtTime(order.created_at)}</span>
                            </td>
                            <td className="px-4 py-3 text-center">
                              <div className="flex items-center justify-center gap-1">
                                <button
                                  onClick={(e) => { e.stopPropagation(); openDetail(order); }}
                                  className="p-1.5 rounded-lg text-black/30 hover:text-[#00bceb] hover:bg-[#00bceb]/8 transition-all"
                                  title={zh ? '查看' : 'View'}
                                >
                                  <Eye size={14} />
                                </button>
                                {['draft', 'rejected'].includes(order.status) && (
                                  <button
                                    onClick={(e) => { e.stopPropagation(); openEdit(order); }}
                                    className="p-1.5 rounded-lg text-black/30 hover:text-amber-600 hover:bg-amber-50 transition-all"
                                    title={zh ? '编辑' : 'Edit'}
                                  >
                                    <FileText size={14} />
                                  </button>
                                )}
                                {['draft', 'cancelled'].includes(order.status) && (
                                  <button
                                    onClick={(e) => { e.stopPropagation(); handleDelete(order.id); }}
                                    className="p-1.5 rounded-lg text-black/30 hover:text-rose-600 hover:bg-rose-50 transition-all"
                                    title={zh ? '删除' : 'Delete'}
                                  >
                                    <Trash2 size={14} />
                                  </button>
                                )}
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <div className="border-t border-black/5 px-4 py-3">
                  <Pagination
                    currentPage={page}
                    itemsPerPage={pageSize}
                    totalItems={total}
                    onPageChange={setPage}
                    onItemsPerPageChange={(v) => { setPageSize(v); setPage(1); }}
                    language={language}
                  />
                </div>
              </>
            )}
          </div>
        </div>
      )}
      </>
      ) : (
      /* ═══════════════════════════════════════════════════════════════════
         Full-page Detail View
         ═══════════════════════════════════════════════════════════════════ */
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
            {/* ── Utility buttons: Copy / Bookmark / Save as Template ── */}
            <button
              onClick={() => handleCopyOrder(selectedOrder)}
              title={zh ? '复制工单' : 'Copy as new order'}
              className="px-3 py-2 rounded-xl text-xs font-medium flex items-center gap-1.5 bg-white text-black/50 border border-black/10 hover:bg-black/5 hover:text-[#00bceb] transition-all"
            >
              <Copy size={13} />
              {zh ? '复制' : 'Copy'}
            </button>
            <button
              onClick={() => handleToggleBookmark(selectedOrder.id)}
              title={zh ? (bookmarkedIds.has(selectedOrder.id) ? '取消收藏' : '收藏') : (bookmarkedIds.has(selectedOrder.id) ? 'Remove bookmark' : 'Bookmark')}
              className={`px-3 py-2 rounded-xl text-xs font-medium flex items-center gap-1.5 border transition-all ${
                bookmarkedIds.has(selectedOrder.id)
                  ? 'bg-amber-50 text-amber-600 border-amber-200 hover:bg-amber-100'
                  : 'bg-white text-black/50 border-black/10 hover:bg-amber-50 hover:text-amber-500 hover:border-amber-200'
              }`}
            >
              {bookmarkedIds.has(selectedOrder.id) ? <Star size={13} className="fill-amber-400" /> : <Bookmark size={13} />}
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
            <div className="w-px h-5 bg-black/8 mx-0.5" />
            {/* ── Workflow buttons ── */}
            {['draft', 'rejected'].includes(selectedOrder.status) && (
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
                  if (action.status === 'rejected') {
                    const reason = prompt(zh ? '请输入驳回原因' : 'Rejection reason:');
                    if (reason === null) return;
                    handleTransition(selectedOrder.id, action.status, { rejected_reason: reason });
                  } else if (action.status === 'completed') {
                    const summaryText = prompt(zh ? '请输入实施结果说明' : 'Result summary:') || '';
                    handleTransition(selectedOrder.id, action.status, { result_summary: summaryText });
                  } else if (action.status === 'failed') {
                    const failedReason = prompt(zh ? '请输入失败原因' : 'Failure reason:') || '';
                    handleTransition(selectedOrder.id, action.status, { result_summary: failedReason });
                  } else if (action.status === 'rollback_in_progress') {
                    const rollbackReason = prompt(zh ? '请输入回溯原因' : 'Rollback reason:') || '';
                    handleTransition(selectedOrder.id, action.status, { rollback_reason: rollbackReason });
                  } else if (action.status === 'rolled_back') {
                    const rollbackSummary = prompt(zh ? '请输入回溯结果说明' : 'Rollback summary:') || '';
                    handleTransition(selectedOrder.id, action.status, { result_summary: rollbackSummary });
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
                          const PIcon = pm.icon;
                          return (
                            <span className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-lg text-[10px] font-medium ${pm.bg} ${pm.color}`}>
                              <PIcon size={10} />
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

                  {/* ── Two-Column Content ── */}
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                    {/* ── Left Column: Meta + Description ── */}
                    <div className="space-y-3">
                      {/* Description */}
                      {selectedOrder.description && (
                        <div className="bg-black/[0.015] rounded-xl p-3">
                          <p className="text-[10px] font-semibold text-black/35 uppercase tracking-wider mb-1">{zh ? '描述' : 'Description'}</p>
                          <p className="text-xs text-black/65 leading-relaxed whitespace-pre-wrap">{selectedOrder.description}</p>
                        </div>
                      )}

                      {/* Meta info — compact 2-col grid */}
                      <div className="grid grid-cols-2 gap-2">
                        <div className="bg-black/[0.015] rounded-lg px-3 py-2">
                          <p className="text-[9px] font-semibold text-black/30 uppercase tracking-wider">{zh ? '类型' : 'Type'}</p>
                          <p className="mt-0.5 text-xs font-medium text-black/70">{typeLabel(selectedOrder.order_type, language)}</p>
                        </div>
                        <div className="bg-black/[0.015] rounded-lg px-3 py-2">
                          <p className="text-[9px] font-semibold text-black/30 uppercase tracking-wider">{zh ? '申请人' : 'Requester'}</p>
                          <p className="mt-0.5 text-xs font-medium text-black/70 flex items-center gap-1">
                            <User size={10} className="text-black/25" />
                            {selectedOrder.requester_username || '—'}
                          </p>
                        </div>
                        {selectedOrder.assigned_initial_reviewer_username && (
                          <div className="bg-black/[0.015] rounded-lg px-3 py-2">
                            <p className="text-[9px] font-semibold text-black/30 uppercase tracking-wider">{zh ? '指定初审人' : 'Assigned Reviewer'}</p>
                            <p className="mt-0.5 text-xs font-medium text-black/70 flex items-center gap-1">
                              <User size={10} className="text-black/25" />
                              {selectedOrder.assigned_initial_reviewer_username}
                            </p>
                          </div>
                        )}
                        {selectedOrder.initial_reviewer_username && (
                          <div className="bg-black/[0.015] rounded-lg px-3 py-2">
                            <p className="text-[9px] font-semibold text-black/30 uppercase tracking-wider">{zh ? '实际初审人' : 'Actual Reviewer'}</p>
                            <p className="mt-0.5 text-xs font-medium text-black/70 flex items-center gap-1">
                              <User size={10} className="text-black/25" />
                              {selectedOrder.initial_reviewer_username}
                            </p>
                          </div>
                        )}
                        {selectedOrder.assigned_final_approver_username && (
                          <div className="bg-black/[0.015] rounded-lg px-3 py-2">
                            <p className="text-[9px] font-semibold text-black/30 uppercase tracking-wider">{zh ? '指定终审人' : 'Assigned Approver'}</p>
                            <p className="mt-0.5 text-xs font-medium text-black/70 flex items-center gap-1">
                              <User size={10} className="text-black/25" />
                              {selectedOrder.assigned_final_approver_username}
                            </p>
                          </div>
                        )}
                        {(selectedOrder.final_approver_username || selectedOrder.approver_username) && (
                          <div className="bg-black/[0.015] rounded-lg px-3 py-2">
                            <p className="text-[9px] font-semibold text-black/30 uppercase tracking-wider">{zh ? '实际终审人' : 'Actual Approver'}</p>
                            <p className="mt-0.5 text-xs font-medium text-black/70 flex items-center gap-1">
                              <User size={10} className="text-black/25" />
                              {selectedOrder.final_approver_username || selectedOrder.approver_username}
                            </p>
                          </div>
                        )}
                        <div className="bg-black/[0.015] rounded-lg px-3 py-2">
                          <p className="text-[9px] font-semibold text-black/30 uppercase tracking-wider">{zh ? '创建时间' : 'Created'}</p>
                          <p className="mt-0.5 text-[11px] font-medium text-black/55 tabular-nums">{fmtDate(selectedOrder.created_at)}</p>
                        </div>
                      </div>

                      {/* Schedule */}
                      {(selectedOrder.scheduled_start || selectedOrder.scheduled_end) && (
                        <div className="bg-blue-50/60 rounded-lg px-3 py-2 ring-1 ring-blue-100">
                          <p className="text-[9px] font-semibold text-blue-500 uppercase tracking-wider flex items-center gap-1">
                            <Calendar size={9} /> {zh ? '计划时间窗口' : 'Scheduled Window'}
                          </p>
                          <p className="mt-0.5 text-xs text-blue-700 tabular-nums">
                            {fmtDate(selectedOrder.scheduled_start)} — {fmtDate(selectedOrder.scheduled_end)}
                          </p>
                        </div>
                      )}

                      {/* Result Summary */}
                      {selectedOrder.result_summary && (
                        <div className="bg-emerald-50/60 rounded-lg px-3 py-2 ring-1 ring-emerald-100">
                          <p className="text-[9px] font-semibold text-emerald-600 uppercase tracking-wider mb-0.5">{zh ? '执行结果' : 'Result'}</p>
                          <p className="text-xs text-black/60 leading-relaxed whitespace-pre-wrap">{selectedOrder.result_summary}</p>
                        </div>
                      )}

                      {/* Rejected Reason */}
                      {selectedOrder.rejected_reason && (
                        <div className="bg-rose-50 rounded-lg px-3 py-2 ring-1 ring-rose-200">
                          <p className="text-[9px] font-semibold text-rose-500 uppercase tracking-wider flex items-center gap-1">
                            <AlertTriangle size={9} /> {zh ? '驳回原因' : 'Rejection Reason'}
                          </p>
                          <p className="mt-0.5 text-xs text-rose-700">{selectedOrder.rejected_reason}</p>
                        </div>
                      )}

                      {/* Rollback Reason */}
                      {typeof selectedOrder.result_detail?.rollback_reason === 'string' && selectedOrder.result_detail.rollback_reason && (
                        <div className="bg-violet-50 rounded-lg px-3 py-2 ring-1 ring-violet-200">
                          <p className="text-[9px] font-semibold text-violet-600 uppercase tracking-wider flex items-center gap-1">
                            <AlertTriangle size={9} /> {zh ? '回溯原因' : 'Rollback Reason'}
                          </p>
                          <p className="mt-0.5 text-xs text-violet-700">{selectedOrder.result_detail.rollback_reason}</p>
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
                          <div className="rounded-xl border border-[#00bceb]/15 bg-gradient-to-br from-[#00bceb]/[0.04] to-white p-3">
                            <div className="flex items-start justify-between gap-2">
                              <div>
                                <p className="text-[9px] font-semibold uppercase tracking-wider text-[#0e7490]">{zh ? '命令模板快照' : 'Template Snapshot'}</p>
                                <h4 className="mt-0.5 text-xs font-semibold text-black/80">
                                  {zh ? (templateSnapshot.scenario_name_zh || templateSnapshot.scenario_name || templateSnapshot.scenario_id) : (templateSnapshot.scenario_name || templateSnapshot.scenario_id)}
                                </h4>
                              </div>
                              <span className="rounded-full bg-white px-2 py-0.5 text-[9px] font-semibold text-[#0e7490] ring-1 ring-[#00bceb]/20">
                                {platformLabel(templateSnapshot.platform)}
                              </span>
                            </div>
                            {Object.keys(templateSnapshot.variables || {}).length > 0 && (
                              <div className="mt-2 flex flex-wrap gap-1">
                                {Object.entries(templateSnapshot.variables || {}).map(([key, value]) => (
                                  <span key={key} className="inline-flex items-center gap-0.5 rounded-full bg-white px-1.5 py-0.5 text-[9px] text-black/60 ring-1 ring-black/8">
                                    <span className="font-semibold text-black/45">{key}</span>
                                    <span>{value || '—'}</span>
                                  </span>
                                ))}
                              </div>
                            )}
                            <div className="mt-2 grid grid-cols-1 gap-2">
                              {preview.pre_check.length > 0 && (
                                <div>
                                  <p className="text-[9px] font-semibold uppercase tracking-wider text-black/30 mb-1">{zh ? '实施前检查' : 'Pre-check'}</p>
                                  <div className="rounded-lg bg-slate-900 p-2 font-mono text-[11px] text-cyan-300 whitespace-pre-wrap break-all leading-relaxed">
                                    {preview.pre_check.map((cmd, index) => <div key={`${cmd}-${index}`}>{index + 1}. {cmd}</div>)}
                                  </div>
                                </div>
                              )}
                              {preview.post_check.length > 0 && (
                                <div>
                                  <p className="text-[9px] font-semibold uppercase tracking-wider text-black/30 mb-1">{zh ? '实施后检查' : 'Post-check'}</p>
                                  <div className="rounded-lg bg-slate-900 p-2 font-mono text-[11px] text-amber-300 whitespace-pre-wrap break-all leading-relaxed">
                                    {preview.post_check.map((cmd, index) => <div key={`${cmd}-${index}`}>{index + 1}. {cmd}</div>)}
                                  </div>
                                </div>
                              )}
                              {preview.rollback.length > 0 && (
                                <div>
                                  <p className="text-[9px] font-semibold uppercase tracking-wider text-black/30 mb-1">{zh ? '模板回退命令' : 'Template Rollback'}</p>
                                  <div className="rounded-lg bg-slate-900 p-2 font-mono text-[11px] text-rose-300 whitespace-pre-wrap break-all leading-relaxed">
                                    {preview.rollback.map((cmd, index) => <div key={`${cmd}-${index}`}>{index + 1}. {cmd}</div>)}
                                  </div>
                                </div>
                              )}
                            </div>
                          </div>
                        );
                      })()}

                      {/* Target Devices */}
                      {selectedOrder.target_devices?.length > 0 && (
                        <div>
                          <p className="text-[9px] font-semibold text-black/30 uppercase tracking-wider mb-1.5">{zh ? '目标设备' : 'Target Devices'}</p>
                          <div className="flex flex-wrap gap-1.5">
                            {selectedOrder.target_devices.map((dev, i) => (
                              <span key={i} className="inline-flex items-center gap-1 rounded-lg bg-cyan-50/80 px-2.5 py-1.5 text-[11px] font-medium text-cyan-800 ring-1 ring-cyan-200/70">
                                {dev.hostname || (zh ? '未命名' : 'Unnamed')}
                                {dev.ip_address && <span className="font-mono text-[10px] text-cyan-600/80">{dev.ip_address}</span>}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Commands */}
                      {selectedOrder.commands?.length > 0 && (
                        <div>
                          <p className="text-[9px] font-semibold text-black/30 uppercase tracking-wider mb-1.5">{zh ? '执行命令' : 'Commands'}</p>
                          <div className="bg-slate-900 rounded-lg p-2.5 font-mono text-[11px] text-emerald-400 leading-relaxed whitespace-pre-wrap break-all">
                            {selectedOrder.commands.map((cmd, i) => (
                              <div key={i} className="flex">
                                <span className="text-slate-500 select-none mr-2 w-4 text-right">{i + 1}</span>
                                {cmd}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Rollback Plan */}
                      {selectedOrder.rollback_plan && (
                        <div>
                          <p className="text-[9px] font-semibold text-black/30 uppercase tracking-wider mb-1">{zh ? '回退方案' : 'Rollback Plan'}</p>
                          <p className="text-xs text-black/60 leading-relaxed whitespace-pre-wrap bg-amber-50/50 rounded-lg p-2.5 ring-1 ring-amber-100">
                            {selectedOrder.rollback_plan}
                          </p>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* ── Timeline (full width) ── */}
                  <div>
                    <p className="text-[9px] font-semibold text-black/30 uppercase tracking-wider mb-1.5">{zh ? '流程时间线' : 'Timeline'}</p>
                    {timelineLoading ? (
                      <div className="text-xs text-black/40 py-2">{zh ? '加载时间线中...' : 'Loading timeline...'}</div>
                    ) : timeline.length === 0 ? (
                      <div className="text-xs text-black/35 py-2">{zh ? '暂无流程记录' : 'No timeline events'}</div>
                    ) : (
                      <div className="flex flex-wrap gap-2">
                        {timeline.map((evt) => (
                          <div key={evt.id} className="rounded-lg border border-black/6 bg-black/[0.015] px-2.5 py-1.5 min-w-[200px] flex-1">
                            <div className="flex items-center justify-between gap-2">
                              <span className="text-[11px] font-medium text-black/65">{timelineEventLabel(evt.event_type, language)}</span>
                              <span className="text-[10px] text-black/30 tabular-nums">{fmtTime(evt.created_at)}</span>
                            </div>
                            <div className="mt-0.5 text-[10px] text-black/40 whitespace-pre-wrap break-words">
                              {evt.summary || timelineEventLabel(evt.event_type, language)}
                              {' · '}{evt.actor_username || (zh ? '系统' : 'System')}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

              </div>
      </motion.div>
      )}

      {/* ════════════════════════════════════════════════════════════
         Create / Edit Modal
         ════════════════════════════════════════════════════════════ */}
      <AnimatePresence>
        {editorVisible && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 10 }}
            className="order-first w-full"
          >
            <motion.div
              initial={{ scale: 0.98, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.98, opacity: 0 }}
              transition={{ type: 'spring', stiffness: 380, damping: 30 }}
              className="bg-white rounded-3xl border border-black/5 shadow-sm overflow-hidden flex flex-col"
            >
              {/* Modal header */}
              <div className="px-6 py-5 border-b border-black/5 bg-gradient-to-r from-[#00bceb]/[0.04] to-transparent flex items-center justify-between">
                <h3 className="text-lg font-semibold flex items-center gap-2.5">
                  <span className="p-2 rounded-xl bg-[#00bceb]/10 ring-1 ring-[#00bceb]/15">
                    <ClipboardList size={16} className="text-[#00bceb]" />
                  </span>
                  {editingOrder ? (zh ? '编辑工单' : 'Edit Order') : (zh ? '新建变更工单' : 'New Change Order')}
                </h3>
                <button title={zh ? '关闭编辑器' : 'Close editor'} onClick={closeEditor} className="p-2 rounded-lg text-black/30 hover:text-black/60 hover:bg-black/5 transition-all">
                  <X size={18} />
                </button>
              </div>

              {/* Modal body */}
              <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
                {/* Title */}
                <div>
                  <label className="block text-xs font-semibold text-black/50 mb-1.5">{zh ? '工单标题' : 'Title'} <span className="text-rose-500">*</span></label>
                  <input
                    value={form.title}
                    onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
                    placeholder={zh ? '例如: 核心交换机VLAN调整' : 'e.g.: Core switch VLAN adjustment'}
                    className="w-full px-4 py-2.5 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40 focus:ring-2 focus:ring-[#00bceb]/10 transition-all"
                  />
                </div>

                {/* Description */}
                <div>
                  <label className="block text-xs font-semibold text-black/50 mb-1.5">{zh ? '描述' : 'Description'}</label>
                  <textarea
                    value={form.description}
                    onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                    placeholder={zh ? '详细描述变更内容、影响范围...' : 'Describe the change, impact scope...'}
                    rows={3}
                    className="w-full px-4 py-2.5 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40 focus:ring-2 focus:ring-[#00bceb]/10 transition-all resize-none"
                  />
                </div>

                {/* Type + Priority + Risk — 3 columns */}
                <div className="grid grid-cols-3 gap-4">
                  <div>
                    <label className="block text-xs font-semibold text-black/50 mb-1.5">{zh ? '变更类型' : 'Type'}</label>
                    <select
                      title={zh ? '变更类型' : 'Change order type'}
                      value={form.order_type}
                      onChange={e => setForm(f => ({ ...f, order_type: e.target.value }))}
                      className="w-full px-3 py-2.5 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40"
                    >
                      {Object.entries(ORDER_TYPE_META).map(([k, v]) => (
                        <option key={k} value={k}>{v.label[zh ? 'zh' : 'en']}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-black/50 mb-1.5">{zh ? '优先级' : 'Priority'}</label>
                    <select
                      title={zh ? '优先级' : 'Priority'}
                      value={form.priority}
                      onChange={e => setForm(f => ({ ...f, priority: e.target.value }))}
                      className="w-full px-3 py-2.5 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40"
                    >
                      {Object.entries(PRIORITY_META).map(([k, v]) => (
                        <option key={k} value={k}>{v.label[zh ? 'zh' : 'en']}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-black/50 mb-1.5">{zh ? '风险等级' : 'Risk Level'}</label>
                    <select
                      title={zh ? '风险等级' : 'Risk level'}
                      value={form.risk_level}
                      onChange={e => setForm(f => ({ ...f, risk_level: e.target.value }))}
                      className="w-full px-3 py-2.5 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40"
                    >
                      {Object.entries(RISK_META).map(([k, v]) => (
                        <option key={k} value={k}>{v.label[zh ? 'zh' : 'en']}</option>
                      ))}
                    </select>
                  </div>
                </div>

                {/* Schedule */}
                <div className="grid grid-cols-2 gap-4">
                  <DateTimePicker
                    label={zh ? '计划开始时间' : 'Scheduled Start'}
                    value={form.scheduled_start}
                    onChange={v => setForm(f => ({ ...f, scheduled_start: v }))}
                    language={language}
                  />
                  <DateTimePicker
                    label={zh ? '计划结束时间' : 'Scheduled End'}
                    value={form.scheduled_end}
                    onChange={v => setForm(f => ({ ...f, scheduled_end: v }))}
                    language={language}
                  />
                </div>

                <div className="grid grid-cols-1 gap-4">
                  <div>
                    <label className="block text-xs font-semibold text-black/50 mb-1.5">{zh ? '指定初审人' : 'Assigned Reviewer'}</label>
                    <select
                      title={zh ? '指定初审人' : 'Assigned reviewer'}
                      value={form.assigned_initial_reviewer_id}
                      onChange={(e) => assignReviewer('initial', e.target.value)}
                      className="w-full px-3 py-2.5 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40 bg-white"
                    >
                      <option value="" disabled>{zh ? '请选择初审人' : 'Select initial reviewer'}</option>
                      {initialReviewerOptions.map((item) => (
                        <option key={item.id} value={String(item.id)}>{buildUserOptionLabel(item)}</option>
                      ))}
                    </select>
                  </div>
                </div>
                <p className="-mt-2 text-[11px] text-black/40">
                  {zh ? '只需指定初审人，终审阶段由终审组成员处理。' : 'Only assign an initial reviewer now; final approval will be handled by the approver group later.'}
                </p>

                <div className="mt-4 rounded-2xl border border-black/8 bg-black/[0.015] p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="text-xs font-semibold text-black/70">{zh ? '设备登录免授权' : 'Device Login Auth Exempt'}</p>
                      <p className="text-[11px] text-black/40 mt-1">
                        {zh ? '开启后变更执行时可跳过设备登录时的额外授权检查，与工单审批流程无关。' : 'Enable to exempt device login authorization during execution; this does not skip the change order approval workflow.'}
                      </p>
                    </div>
                    <label className="inline-flex items-center gap-2 rounded-full border border-black/10 bg-white px-3 py-2 text-sm cursor-pointer select-none">
                      <input
                        type="checkbox"
                        checked={form.authorization_exempt}
                        onChange={(e) => setForm(f => ({
                          ...f,
                          authorization_exempt: e.target.checked,
                        }))}
                        className="h-4 w-4 rounded border border-black/10 text-[#06b6d4] focus:ring-[#06b6d4]"
                      />
                      <span>{form.authorization_exempt ? (zh ? '已启用' : 'Enabled') : (zh ? '未启用' : 'Disabled')}</span>
                    </label>
                  </div>
                </div>

                {/* Target Devices */}
                <div className="mt-4">
                  <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
                    <label className="block text-xs font-semibold text-black/50">{zh ? '目标设备' : 'Target Devices'}</label>
                    <button
                      type="button"
                      onClick={() => setShowDevicePicker(true)}
                      className="rounded-xl bg-[#06b6d4] px-3 py-2 text-xs font-semibold text-white hover:bg-[#0891b2] transition-all"
                    >
                      {zh ? '从设备库选择' : 'Pick from inventory'}
                    </button>
                  </div>
                  <div className="flex gap-2 mb-2">
                    <input
                      title={zh ? '目标设备主机名' : 'Target device hostname'}
                      value={deviceInput.hostname}
                      onChange={e => setDeviceInput(d => ({ ...d, hostname: e.target.value }))}
                      placeholder={zh ? '主机名' : 'Hostname'}
                      className="flex-1 px-3 py-2 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40"
                    />
                    <input
                      title={zh ? '目标设备IP地址' : 'Target device IP address'}
                      value={deviceInput.ip_address}
                      onChange={e => setDeviceInput(d => ({ ...d, ip_address: e.target.value }))}
                      placeholder={zh ? 'IP 地址' : 'IP Address'}
                      className="flex-1 px-3 py-2 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40"
                    />
                    <button title={zh ? '添加目标设备' : 'Add target device'} onClick={addDevice} className="px-3 py-2 rounded-xl bg-[#00bceb]/10 text-[#00bceb] text-sm font-medium hover:bg-[#00bceb]/18 transition-all">
                      <Plus size={15} />
                    </button>
                  </div>
                  {form.target_devices.length > 0 && (
                    <div className="mt-2 overflow-x-auto rounded-3xl border border-black/10 bg-slate-50">
                      <table className="min-w-full text-sm text-left">
                        <thead>
                          <tr className="text-xs text-black/50 uppercase tracking-[0.04em]">
                            <th className="px-3 py-3">{zh ? 'IP地址' : 'IP Address'}</th>
                            <th className="px-3 py-3">{zh ? '设备名称' : 'Device Name'}</th>
                            <th className="px-3 py-3">{zh ? '用户名' : 'Username'}</th>
                            <th className="px-3 py-3">{zh ? '开始/结束' : 'Start / End'}</th>
                            <th className="px-3 py-3">{zh ? '执行人' : 'Executor'}</th>
                            <th className="px-3 py-3">{zh ? '操作' : 'Actions'}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {form.target_devices.map((dev, i) => (
                            <tr key={i} className="border-t border-black/10">
                              <td className="px-3 py-3 text-black/80">{dev.ip_address || '—'}</td>
                              <td className="px-3 py-3 text-black/80">{dev.hostname || '—'}</td>
                              <td className="px-3 py-3 text-black/80">{dev.username || currentUser.username || '—'}</td>
                              <td className="px-3 py-3 text-black/80">{fmtTime(form.scheduled_start)} / {fmtTime(form.scheduled_end)}</td>
                              <td className="px-3 py-3 text-black/80">{currentUser.username || '—'}</td>
                              <td className="px-3 py-3">
                                <button
                                  title={zh ? '移除目标设备' : 'Remove target device'}
                                  onClick={() => setForm(f => ({ ...f, target_devices: f.target_devices.filter((_, j) => j !== i) }))}
                                  className="text-cyan-400 hover:text-cyan-700"
                                >
                                  <X size={14} />
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>

                {showDevicePicker && (
                  <div className="mt-4 rounded-3xl border border-black/10 bg-white p-5 shadow-sm">
                    <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
                      <div>
                        <p className="text-sm font-semibold text-black/75">{zh ? '选择目标设备' : 'Select target devices'}</p>
                        <p className="text-[11px] text-black/40 mt-1">
                          {zh ? '搜索设备库（支持主机名/IP/管理IP/资产标签），选择设备后点击确认添加。' : 'Search inventory by hostname, IP, management IP or asset tag. Select a device and confirm to add.'}
                        </p>
                      </div>
                      <button type="button" title={zh ? '关闭设备选择器' : 'Close device picker'} onClick={() => { setShowDevicePicker(false); setDeviceKeyword(''); setSelectedInventoryDevice(null); }} className="text-black/50 hover:text-black">
                        <X size={18} />
                      </button>
                    </div>
                    <input
                      title={zh ? '搜索设备清单' : 'Search inventory devices'}
                      value={deviceKeyword}
                      onChange={e => setDeviceKeyword(e.target.value)}
                      placeholder={zh ? '搜索主机名 / IP / 管理IP / 资产标签' : 'Search hostname / IP / management IP / asset tag'}
                      className="w-full px-3 py-2 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40"
                    />
                    <div className="mt-3 grid gap-4 xl:grid-cols-[1fr_250px]">
                      <div className="max-h-72 overflow-y-auto border border-black/10 rounded-3xl bg-slate-50">
                        {deviceLoading ? (
                          <div className="px-3 py-3 text-sm text-black/50">{zh ? '搜索中...' : 'Searching...'}</div>
                        ) : deviceOptions.length === 0 ? (
                          <div className="px-3 py-3 text-sm text-black/40">{zh ? '未找到匹配设备，请修改关键词或直接输入目标设备。' : 'No devices found, change search term or add manually.'}</div>
                        ) : (
                          deviceOptions.map((dev) => (
                            <button
                              type="button"
                              key={`${dev.id}-${dev.ip_address}`}
                              onClick={() => setSelectedInventoryDevice(dev)}
                              className={`w-full px-4 py-3 text-left text-sm text-black/80 hover:bg-[#00bceb]/8 border-b last:border-b-0 border-black/10 transition-all ${selectedInventoryDevice?.id === dev.id ? 'bg-[#00bceb]/15' : ''}`}
                            >
                              <div className="font-medium">{dev.hostname || (zh ? '未命名设备' : 'Unnamed')}</div>
                              <div className="text-[11px] text-black/45">
                                {dev.asset_tag ? `${dev.asset_tag} · ` : ''}{dev.ip_address || '—'}
                              </div>
                            </button>
                          ))
                        )}
                      </div>
                      <div className="rounded-3xl border border-black/10 bg-slate-50 p-4">
                        <p className="text-xs font-semibold text-black/50 mb-2">{zh ? '已选设备' : 'Selected device'}</p>
                        {selectedInventoryDevice ? (
                          <div className="space-y-3">
                            <div className="rounded-2xl border border-black/10 bg-white p-3">
                              <div className="font-medium text-black/80">{selectedInventoryDevice.hostname || (zh ? '未命名设备' : 'Unnamed device')}</div>
                              <div className="text-[11px] text-black/45">
                                {selectedInventoryDevice.asset_tag ? `${selectedInventoryDevice.asset_tag} · ` : ''}{selectedInventoryDevice.ip_address || '—'}
                              </div>
                              {selectedInventoryDevice.platform && (
                                <div className="text-[11px] text-black/40">{platformLabel(selectedInventoryDevice.platform)}</div>
                              )}
                            </div>
                            <button
                              type="button"
                              onClick={confirmSelectedDevice}
                              className="w-full rounded-xl bg-[#06b6d4] px-3 py-2 text-sm font-semibold text-white hover:bg-[#0891b2] transition-all"
                            >
                              {zh ? '确认添加设备' : 'Confirm add device'}
                            </button>
                          </div>
                        ) : (
                          <div className="rounded-2xl border border-dashed border-black/10 bg-white/70 p-4 text-[11px] text-black/45">
                            {zh ? '请选择一个设备以确认添加到工单。' : 'Select a device to confirm adding it to the order.'}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}

                <div className="rounded-2xl border border-black/8 bg-black/[0.015] p-4">
                  <div className="flex items-center justify-between gap-3 mb-3">
                    <div>
                      <label className="block text-xs font-semibold text-black/50">{zh ? '命令来源' : 'Command Source'}</label>
                      <p className="mt-1 text-[11px] text-black/40">{zh ? '可继续使用手工输入，也可以切换为可参数化的变更模板。' : 'Keep manual commands or switch to a parameterized scenario template.'}</p>
                    </div>
                    <div className="inline-flex rounded-xl bg-white p-1 ring-1 ring-black/8">
                      <button
                        type="button"
                        onClick={() => setCommandMode('manual')}
                        className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${commandMode === 'manual' ? 'bg-[#00bceb] text-white shadow-sm' : 'text-black/55 hover:bg-black/[0.04]'}`}
                      >
                        {zh ? '手工命令' : 'Manual'}
                      </button>
                      <button
                        type="button"
                        onClick={() => setCommandMode('template')}
                        className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${commandMode === 'template' ? 'bg-[#00bceb] text-white shadow-sm' : 'text-black/55 hover:bg-black/[0.04]'}`}
                      >
                        {zh ? '模板场景' : 'Template'}
                      </button>
                    </div>
                  </div>

                  {commandMode === 'template' ? (
                    <div className="space-y-4">
                      <div className="grid grid-cols-1 gap-4">
                        <div>
                          <label className="block text-xs font-semibold text-black/50 mb-1.5">{zh ? '变更模板场景' : 'Scenario Template'}</label>
                          <select
                            title={zh ? '变更模板场景' : 'Scenario template'}
                            value={selectedScenarioId}
                            onChange={(e) => setSelectedScenarioId(e.target.value)}
                            className="w-full px-3 py-2.5 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40 bg-white"
                          >
                            <option value="">{zh ? '请选择一个配置模板' : 'Select a config template'}</option>
                            {scenarioOptions.map((scenario) => (
                              <option key={scenario.id} value={scenario.id}>
                                {scenario.icon ? `${scenario.icon} ` : ''}{zh ? (scenario.name_zh || scenario.name) : scenario.name}
                              </option>
                            ))}
                          </select>
                        </div>
                        {selectedScenario && selectedScenarioPlatforms.length > 0 && (
                          <div className="rounded-2xl border border-black/10 bg-slate-50 px-4 py-3 text-sm text-black/70">
                            <label className="block text-xs font-semibold text-black/50 mb-1.5">{zh ? '目标平台' : 'Target platform'}</label>
                            <select
                              title={zh ? '选择目标平台' : 'Select target platform'}
                              value={selectedScenarioPlatform}
                              onChange={(e) => setSelectedScenarioPlatform(e.target.value)}
                              className="w-full px-3 py-2.5 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40 bg-white"
                            >
                              <option value="">{zh ? '自动匹配目标设备平台' : 'Auto detect target device platform'}</option>
                              {selectedScenarioPlatforms.map((platform) => (
                                <option key={platform} value={platform}>{platformLabel(platform)}</option>
                              ))}
                            </select>
                            <p className="mt-2 text-[11px] text-black/40">
                              {zh ? '如果目标设备已包含平台信息，系统会自动匹配；也可手动指定。' : 'If target devices include platform info, the system will auto-detect; you can also choose manually.'}
                            </p>
                          </div>
                        )}
                      </div>

                      {selectedScenario && (
                        <div className="rounded-2xl border border-[#00bceb]/15 bg-[#00bceb]/[0.04] px-4 py-4">
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <p className="text-sm font-semibold text-black/80">{zh ? (selectedScenario.name_zh || selectedScenario.name) : selectedScenario.name}</p>
                              <p className="mt-1 text-xs text-black/45">{zh ? (selectedScenario.description_zh || selectedScenario.description || '') : (selectedScenario.description || '')}</p>
                            </div>
                            <span className={`shrink-0 rounded-full px-2.5 py-1 text-[10px] font-semibold ${RISK_META[selectedScenario.risk || form.risk_level]?.color || 'text-slate-600'} bg-white ring-1 ring-black/8`}>
                              {riskLabel(selectedScenario.risk || form.risk_level, language)}
                            </span>
                          </div>
                        </div>
                      )}

                      {selectedScenarioVariables.length > 0 && (
                        <div className="grid grid-cols-2 gap-3">
                          {selectedScenarioVariables.map((variable) => {
                            const hint = variable.platform_hints?.[selectedScenarioPlatform] || variable.placeholder || '';
                            const commonClass = 'w-full px-3 py-2.5 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40';
                            return (
                              <div key={variable.key} className={variable.type === 'textarea' ? 'col-span-2' : ''}>
                                <label className="block text-xs font-semibold text-black/50 mb-1.5">
                                  {variableLabel(variable)}
                                  {variable.required && <span className="text-rose-500 ml-1">*</span>}
                                </label>
                                {variable.type === 'textarea' ? (
                                  <textarea
                                    title={variableLabel(variable)}
                                    value={templateVariables[variable.key] || ''}
                                    onChange={(e) => assignTemplateVariable(variable.key, e.target.value)}
                                    placeholder={hint}
                                    rows={3}
                                    className={`${commonClass} resize-none font-mono text-xs`}
                                  />
                                ) : variable.type === 'select' ? (
                                  <select
                                    title={variableLabel(variable)}
                                    value={templateVariables[variable.key] || ''}
                                    onChange={(e) => assignTemplateVariable(variable.key, e.target.value)}
                                    className={`${commonClass} bg-white`}
                                  >
                                    <option value="">{zh ? '请选择' : 'Select'}</option>
                                    {(variable.options || []).map((option) => (
                                      <option key={option} value={option}>{option}</option>
                                    ))}
                                  </select>
                                ) : (
                                  <input
                                    type={variable.type === 'number' ? 'number' : 'text'}
                                    title={variableLabel(variable)}
                                    value={templateVariables[variable.key] || ''}
                                    onChange={(e) => assignTemplateVariable(variable.key, e.target.value)}
                                    placeholder={hint}
                                    className={commonClass}
                                  />
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}

                      {templateMissingRequired.length > 0 && (
                        <div className="rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-700 ring-1 ring-amber-200">
                          {zh ? `仍有必填变量未填写：${templateMissingRequired.join('、')}` : `Required variables are missing: ${templateMissingRequired.join(', ')}`}
                        </div>
                      )}

                      {templatePreviewError && (
                        <div className="rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-700 ring-1 ring-rose-200">
                          {templatePreviewError}
                        </div>
                      )}

                      <div className="grid grid-cols-2 gap-3">
                        {([
                          { key: 'pre_check', title: zh ? '实施前检查' : 'Pre-check', tone: 'text-cyan-300' },
                          { key: 'execute', title: zh ? '执行命令' : 'Execute', tone: 'text-emerald-300' },
                          { key: 'post_check', title: zh ? '实施后检查' : 'Post-check', tone: 'text-amber-300' },
                          { key: 'rollback', title: zh ? '回退命令' : 'Rollback', tone: 'text-rose-300' },
                        ] as Array<{ key: keyof ScenarioPhasePreview; title: string; tone: string }>).map((section) => {
                          const commands = templatePreview?.[section.key] || [];
                          return (
                            <div key={section.key} className="rounded-2xl border border-black/8 bg-white p-3">
                              <div className="flex items-center justify-between gap-2 mb-2">
                                <p className="text-[10px] font-semibold uppercase tracking-wider text-black/35">{section.title}</p>
                                {templatePreviewLoading && section.key === 'execute' && <RefreshCw size={12} className="animate-spin text-black/30" />}
                              </div>
                              <div className={`rounded-xl bg-slate-900 p-3 font-mono text-xs whitespace-pre-wrap break-all ${section.tone}`}>
                                {commands.length > 0 ? commands.map((cmd, index) => <div key={`${section.key}-${index}`}>{index + 1}. {cmd}</div>) : <div className="text-slate-500">{zh ? '暂无内容' : 'No commands'}</div>}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-4">
                      <div>
                        <label className="block text-xs font-semibold text-black/50 mb-1.5">{zh ? '执行命令' : 'Commands'}</label>
                        <div className="flex gap-2">
                          <input
                            value={commandInput}
                            onChange={e => setCommandInput(e.target.value)}
                            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addCommand(); } }}
                            placeholder={zh ? '输入命令后按 Enter 添加' : 'Type command and press Enter'}
                            className="flex-1 px-3 py-2 text-sm font-mono border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40"
                          />
                          <button title={zh ? '添加命令' : 'Add command'} onClick={addCommand} className="px-3 py-2 rounded-xl bg-[#00bceb]/10 text-[#00bceb] text-sm font-medium hover:bg-[#00bceb]/18 transition-all">
                            <Plus size={15} />
                          </button>
                        </div>
                        {form.commands.length > 0 && (
                          <div className="mt-2 bg-slate-900 rounded-xl p-3 font-mono text-xs text-emerald-400 leading-relaxed max-h-28 overflow-y-auto">
                            {form.commands.map((cmd, i) => (
                              <div key={i} className="flex items-center group">
                                <span className="text-slate-500 select-none mr-2 w-4 text-right">{i + 1}</span>
                                <span className="flex-1">{cmd}</span>
                                <button
                                  title={zh ? '移除命令' : 'Remove command'}
                                  onClick={() => setForm(f => ({ ...f, commands: f.commands.filter((_, j) => j !== i) }))}
                                  className="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-rose-400 ml-2 transition-opacity"
                                >
                                  <X size={11} />
                                </button>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>

                      <div>
                        <label className="block text-xs font-semibold text-black/50 mb-1.5">{zh ? '回退方案' : 'Rollback Plan'}</label>
                        <textarea
                          value={form.rollback_plan}
                          onChange={e => setForm(f => ({ ...f, rollback_plan: e.target.value }))}
                          placeholder={zh ? '描述失败时的回退步骤...' : 'Describe rollback steps in case of failure...'}
                          rows={2}
                          className="w-full px-4 py-2.5 text-sm border border-black/10 rounded-xl outline-none focus:border-[#00bceb]/40 focus:ring-2 focus:ring-[#00bceb]/10 transition-all resize-none"
                        />
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Modal footer */}
              <div className="px-6 py-4 border-t border-black/5 bg-black/[0.01] flex flex-wrap items-center justify-end gap-3">
                <button onClick={closeEditor} className="px-4 py-2.5 rounded-xl text-sm font-medium text-black/50 hover:bg-black/5 transition-all">
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button
                  onClick={handleSaveDraft}
                  disabled={saving || !form.title.trim()}
                  className="px-4 py-2.5 rounded-xl bg-white text-black/70 border border-black/10 text-sm font-medium hover:bg-black/5 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <Save size={14} />
                  {zh ? '保存草稿' : 'Save Draft'}
                </button>
                <button
                  onClick={handleSave}
                  disabled={saving || !form.title.trim()}
                  className="px-5 py-2.5 bg-[#00bceb] text-white rounded-xl text-sm font-medium flex items-center gap-2 hover:bg-[#0096bd] transition-all shadow-lg shadow-[#00bceb]/20 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {saving ? <RefreshCw size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
                  {editingOrder ? (zh ? '提交' : 'Submit') : (zh ? '创建工单' : 'Create Order')}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default ChangeOrderTab;
