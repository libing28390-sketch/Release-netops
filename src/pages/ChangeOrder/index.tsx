import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { ClipboardList, CheckCircle2, AlertTriangle, X, Zap, XCircle, Trash2 } from 'lucide-react';
import { AnimatePresence } from 'motion/react';
import PageHero from '../../components/PageHero';
import type { User as UserOption, SessionUser, ConfigTemplate } from '../../types';
import type { ChangeOrder as IChangeOrder, ScenarioTemplate, Summary, PlatformMeta, ResultReviewAction } from './types';

// Sub-components
import { ChangeOrderList } from './components/ChangeOrderList';
import { ChangeOrderDetail } from './components/ChangeOrderDetail';
import type { ControlSheetUploadResult } from './components/ControlSheetPanel';
import { ChangeOrderEditor } from './components/ChangeOrderEditor';
import { TerminalExecution } from './components/TerminalExecution';
import { useEscapeClose } from '../../hooks/useEscapeClose';
import { TicketDialog, ticketInputClass } from '../../components/tickets/TicketUI';
import { TicketReviewerDialog } from '../../components/tickets/TicketReviewerDialog';
import { ActionButton } from '../../components/ui/ActionIconButton';
import ToastNotification from '../../components/ToastNotification';
import { PasswordInputField } from '../../components/ui/PasswordInputField';

// Constants & Helpers
import {
  STATUS_META,
  PRIORITY_META,
  RISK_META,
  ORDER_TYPE_META,
  EMPTY_FORM,
  DEFAULT_PAGE_SIZE,
  toConfigTemplateScenarioId,
  fromConfigTemplateScenarioId,
  isConfigTemplateScenarioId
} from './constants';
import {
  clampChangeOrderPage,
  getFinalApproverCandidates,
  getInitialReviewerCandidates,
  formatChangeOrderApiMessage,
  getMissingChangeOrderControlSheetFields,
  isCommandTemplateSnapshot,
  fmtDate,
  inferVariableMeta,
  canCurrentUserImplement,
  getAssignedImplementer,
  getResultReviewer,
  getResultReviewActions,
  getVerificationReadiness,
  getBusinessConfirmer,
  buildChangeOrderRollbackFields,
  getImplementerConflictRole,
  resolveChangeOrderRollbackPlan,
  getChangeOrderExecutionAuthRole,
  hasOrderExecutionRequestBeenSent,
  isChangeOrderRequester,
  isChangeOrderInitialReviewer,
  isChangeOrderFinalApprover
} from './helpers';
import { synchronizeControlSheetMirrors } from './controlSheetSync';
import type { AssignmentRequest, ChangeOrderMutationResult, VerificationRequest } from './components/ChangeOrderWorkflowPanels';

const FEATURE_CONTROL_SHEET = true;
type ChangeOrderRequestError = 'permission' | 'load';

const executionRequestKey = (order: IChangeOrder): string => {
  const details = order.result_detail || {};
  const approvalIdentity = String(details.execution_token_id || details.approval_snapshot_hash || '');
  const approvalVersion = String(details.approval_snapshot_version || '');
  return `${order.id}:${approvalIdentity}:${approvalVersion}`;
};

interface Props {
  language: string;
  t: (key: string) => string;
  users: UserOption[];
  scenarios: ScenarioTemplate[];
  configTemplates: ConfigTemplate[];
  platforms: Record<string, PlatformMeta>;
  currentUser: SessionUser;
  initialView?: 'all' | 'group_todo' | 'my_todo' | 'my_participated' | 'my_focus' | 'my_drafts' | 'create';
  findMatchingPlatform: (devicePlatform: string, platforms: string[] | Record<string, any>) => string | undefined;
}

const ChangeOrderComponent: React.FC<Props> = ({
  language,
  t,
  scenarios,
  configTemplates,
  platforms,
  currentUser,
  initialView,
  findMatchingPlatform,
}) => {
  const zh = language === 'zh';
  const isCreateView = initialView === 'create';
  const navigate = useNavigate();
  const location = useLocation();
  const incidentIdFromQuery = useMemo(
    () => new URLSearchParams(location.search).get('incident_id') || '',
    [location.search],
  );
  const incidentTicketIdFromQuery = useMemo(
    () => new URLSearchParams(location.search).get('incident_ticket_id') || '',
    [location.search],
  );
  const orderIdFromQuery = useMemo(
    () => new URLSearchParams(location.search).get('order_id') || '',
    [location.search],
  );

  // ── Data state ──
  const [orders, setOrders] = useState<IChangeOrder[]>([]);
  const [assignmentUsers, setAssignmentUsers] = useState<UserOption[]>([]);
  const [total, setTotal] = useState(0);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState<ChangeOrderRequestError | null>(null);
  const orderListRequestSequence = useRef(0);
  const orderListRequestController = useRef<AbortController | null>(null);
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
  const [viewTab, setViewTab] = useState<'all' | 'group_todo' | 'my_todo' | 'my_focus' | 'my_participated' | 'my_drafts'>(
    initialView && initialView !== 'create' ? initialView : 'all'
  );
  const [myTodoSubTab, setMyTodoSubTab] = useState<'review' | 'implement' | 'modify'>('review');

  // ── Bookmarks ──
  const [bookmarkedIds, setBookmarkedIds] = useState<Set<string>>(new Set());
  // ── Detail panel ──
  const [selectedOrder, setSelectedOrder] = useState<IChangeOrder | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<ChangeOrderRequestError | null>(null);
  const detailRequestSequence = useRef(0);
  const [timeline, setTimeline] = useState<any[]>([]);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const timelineRequestSequence = useRef(0);
  const closeDetail = useCallback(() => {
    detailRequestSequence.current += 1;
    timelineRequestSequence.current += 1;
    setDetailLoading(false);
    setDetailError(null);
    setTimelineLoading(false);
    setSelectedOrder(null);
    setTimeline([]);
  }, []);
  const [actionPrompt, setActionPrompt] = useState<{
    title: string;
    placeholder: string;
    value: string;
    required: boolean;
    sensitive?: boolean;
    onConfirm: (val: string) => void;
  } | null>(null);

  // ── Execute-commands modal state ──
  const [executeModal, setExecuteModal] = useState<{
    order: IChangeOrder;
    phase: 'confirm' | 'running' | 'done';
    output: string;
    error: string;
    success: boolean;
    requestSent?: boolean;
  } | null>(null);
  const [sentExecutionRequestKeys, setSentExecutionRequestKeys] = useState<Set<string>>(() => new Set());

  const [finalApproverPrompt, setFinalApproverPrompt] = useState<{
    onConfirm: (id: string) => void;
  } | null>(null);
  const [finalApproverSearch, setFinalApproverSearch] = useState('');
  const [tempSelectedFinalApprover, setTempSelectedFinalApprover] = useState<string>('');

  const [initialApproverPrompt, setInitialApproverPrompt] = useState<{
    onConfirm: (id: string) => void;
  } | null>(null);
  const [initialApproverSearch, setInitialApproverSearch] = useState('');
  const [tempSelectedInitialApprover, setTempSelectedInitialApprover] = useState<string>('');
  const [selectedGroupForInitial, setSelectedGroupForInitial] = useState<string>('');

  // ── Create/Edit modal ──
  const [showCreateModal, setShowCreateModal] = useState(initialView === 'create');
  const [editingOrder, setEditingOrder] = useState<IChangeOrder | null>(null);

  const [form, setForm] = useState(() => ({ ...EMPTY_FORM }));
  const [saving, setSaving] = useState(false);
  const [selectedGroupForFinal, setSelectedGroupForFinal] = useState<string>('');

  // Sync the selected queue when sidebar navigation changes.
  useEffect(() => {
    if (initialView && initialView !== 'create') {
      setViewTab(initialView);
    }
    if (initialView !== 'create') {
      setShowCreateModal(false);
      if (initialView) closeDetail();
    }
  }, [closeDetail, initialView]);

  // Template Mode States
  const [commandMode, setCommandMode] = useState<'manual' | 'template'>('manual');
  const [selectedScenarioId, setSelectedScenarioId] = useState('');
  const [selectedScenarioPlatform, setSelectedScenarioPlatform] = useState('');
  const [templateVariables, setTemplateVariables] = useState<Record<string, string>>({});

  // ── Toast ──
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null);

  const showToast = useCallback((msg: unknown, type: 'success' | 'error' = 'success') => {
    const translationMap: Record<string, string> = {
      'Requester cannot review/approve own change order': '申请人不能审核或审批自己的变更工单',
      'Only Administrator can finalize approval for change orders': '只有管理员角色的用户才能执行最终审批',
      'Only Administrator can reject in final review stage': '只有管理员角色的用户才能在终审阶段驳回工单',
      'Only the assigned initial reviewer can process this change order': '只有被指定的初审人才能处理此工单的初审',
      'Only users in the initial review group can process this change order': '只有初审组成员或管理员才能处理此工单的初审',
      'Initial reviewer must be an Administrator': '初审人必须是管理员',
      'Selected user is not in the initial review group': '所选初审人不在初审组，请检查用户的工单职责组配置',
      'Only the assigned final approver can process this change order': '只有被指定的终审人才能处理此工单的终审',
      'Only users in the final approval group can process this change order': '只有终审组成员或管理员才能处理此工单的终审',
      'Selected user is not in the final approval group': '所选终审人不在终审组，请检查用户的工单职责组配置',
      'Change order not found': '未找到变更工单',
      'Forbidden': '拒绝访问',
    };

    const safeMessage = formatChangeOrderApiMessage(msg, language, zh ? '操作失败，请稍后重试。' : 'Request failed. Please try again.');
    const finalMsg = zh ? (translationMap[safeMessage] || safeMessage) : safeMessage;
    setToast({ msg: finalMsg, type });
    setTimeout(() => setToast(null), type === 'error' ? 5000 : 3000);
  }, [language, zh]);

  const authHeaders = useCallback((withJson = false) => {
    const token = localStorage.getItem('netops_token');
    return {
      ...(withJson ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    };
  }, []);

  useEffect(() => {
    let active = true;
    setAssignmentUsers([]);
    const loadAssignmentUsers = async () => {
      try {
        const response = await fetch('/api/change-orders/assignment-options', {
          headers: authHeaders(),
        });
        if (!response.ok) return;
        const payload = await response.json();
        if (active && Array.isArray(payload?.data)) {
          setAssignmentUsers(payload.data);
        }
      } catch {
        if (active) setAssignmentUsers([]);
      }
    };
    void loadAssignmentUsers();
    return () => { active = false; };
  }, [authHeaders, currentUser.id]);

  const resetTemplateComposer = useCallback(() => {
    setCommandMode('manual');
    setSelectedScenarioId('');
    setSelectedScenarioPlatform('');
    setTemplateVariables({});
  }, []);

  const editorVisible = isCreateView || showCreateModal;

  const isDirty = useMemo(() => {
    if (!editorVisible) return false;
    if (editingOrder) {
      const existingBusinessConfirmer = getBusinessConfirmer(editingOrder);
      return (
        form.title !== editingOrder.title ||
        form.description !== (editingOrder.description || '') ||
        form.priority !== editingOrder.priority ||
        form.order_type !== editingOrder.order_type ||
        form.risk_level !== editingOrder.risk_level ||
        form.target_devices.length !== (editingOrder.target_devices?.length || 0) ||
        form.commands.length !== (editingOrder.commands?.length || 0) ||
        form.rollback_plan !== (editingOrder.rollback_plan || '') ||
        form.control_sheet.business_confirmer_id !== (existingBusinessConfirmer.id || '') ||
        form.control_sheet.business_confirmer_username !== (existingBusinessConfirmer.username || '')
      );
    }
    return (
      form.title.trim() !== '' ||
      form.description.trim() !== '' ||
      Boolean(form.control_sheet.business_confirmer_id) ||
      form.target_devices.length > 0 ||
      form.commands.length > 0
    );
  }, [editorVisible, form, editingOrder]);

  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (isDirty) {
        e.preventDefault();
        e.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [isDirty]);

  const resetEditorState = useCallback(() => {
    setEditingOrder(null);
    setForm({ ...EMPTY_FORM });
    resetTemplateComposer();
  }, [resetTemplateComposer]);

  const closeEditor = useCallback((forceClose = false) => {
    if (!forceClose && isDirty && !window.confirm(zh ? '确认不保存吗？' : 'Confirm not to save?')) {
      return;
    }
    resetEditorState();
    setShowCreateModal(false);
    if (isCreateView) {
      navigate('/change-orders/all');
    }
  }, [isCreateView, isDirty, navigate, resetEditorState, zh]);
  const closeFinalApproverPrompt = useCallback(() => {
    setFinalApproverPrompt(null);
    setFinalApproverSearch('');
    setTempSelectedFinalApprover('');
    setSelectedGroupForFinal('');
  }, []);
  const closeInitialApproverPrompt = useCallback(() => {
    setInitialApproverPrompt(null);
    setInitialApproverSearch('');
    setTempSelectedInitialApprover('');
    setSelectedGroupForInitial('');
  }, []);
  useEscapeClose(
    editorVisible && !saving && !actionPrompt && !finalApproverPrompt && !initialApproverPrompt && !executeModal,
    () => closeEditor(),
  );


  // Handle scenarioId from location state
  useEffect(() => {
    if (location.state && (location.state as any).scenarioId) {
      const stateObj = location.state as any;
      setSelectedScenarioId(stateObj.scenarioId);
      setCommandMode('template');
      if (stateObj.platform) {
        setSelectedScenarioPlatform(stateObj.platform);
      }
      if (stateObj.variables) {
        setTemplateVariables(stateObj.variables);
      }
      if (stateObj.targetDevices) {
        setForm((f) => ({
          ...f,
          target_devices: stateObj.targetDevices,
        }));
      }
      setShowCreateModal(true);
      window.history.replaceState({}, document.title);
    }
  }, [location.state]);

  useEffect(() => {
    if (!isCreateView || !incidentIdFromQuery || editingOrder) return;
    let cancelled = false;
    const loadIncidentContext = async () => {
      try {
        const token = localStorage.getItem('netops_token');
        const headers = token ? { Authorization: `Bearer ${token}` } : {};
        const [detailResponse, impactResponse] = await Promise.all([
          fetch(`/api/monitoring/incidents/${encodeURIComponent(incidentIdFromQuery)}`, { headers }),
          fetch(`/api/monitoring/incidents/${encodeURIComponent(incidentIdFromQuery)}/impact`, { headers }),
        ]);
        if (cancelled || !detailResponse.ok) return;
        const detail = await detailResponse.json();
        const impact = impactResponse.ok ? await impactResponse.json() : null;
        const affectedNodes = Array.isArray(impact?.nodes)
          ? impact.nodes.filter((node: any) => node?.impact_scope === 'affected')
          : [];
        const targetDevices = affectedNodes.map((node: any) => ({
          hostname: node.hostname || node.id || '',
          ip_address: node.ip_address || '',
        })).filter((device: any) => device.hostname || device.ip_address);
        setForm((current) => ({
          ...current,
          incident_id: incidentIdFromQuery,
          title: current.title || `[${detail.incident_key || incidentIdFromQuery}] ${detail.title || 'Monitoring incident'}`,
          description: current.description || detail.summary || '',
          target_devices: current.target_devices.length > 0
            ? current.target_devices
            : targetDevices.length > 0
              ? targetDevices
              : detail.ip_address || detail.hostname
                ? [{ hostname: detail.hostname || '', ip_address: detail.ip_address || '' }]
                : current.target_devices,
        }));
      } catch {
        // The incident link is still preserved even when context enrichment is unavailable.
        setForm((current) => ({ ...current, incident_id: incidentIdFromQuery }));
      }
    };
    loadIncidentContext();
    return () => { cancelled = true; };
  }, [editingOrder, incidentIdFromQuery, isCreateView]);

  const getDefaultPrePostCheck = (platformKey: string, category?: string, name?: string): { pre_check: string[]; post_check: string[] } => {
    const plat = (platformKey || '').toLowerCase();
    const cat = (category || '').toLowerCase();
    const nm = (name || '').toLowerCase();

    if (plat.includes('cisco')) {
      if (cat === 'routing' || nm.includes('bgp') || nm.includes('ospf') || nm.includes('route')) {
        if (nm.includes('bgp')) {
          return { pre_check: ['show ip bgp summary', 'show ip route'], post_check: ['show ip bgp summary', 'show ip route'] };
        } else if (nm.includes('ospf')) {
          return { pre_check: ['show ip ospf neighbor', 'show ip route'], post_check: ['show ip ospf neighbor', 'show ip route'] };
        } else {
          return { pre_check: ['show ip route'], post_check: ['show ip route'] };
        }
      } else if (cat === 'security' || nm.includes('acl') || nm.includes('ssh') || nm.includes('aaa') || nm.includes('tacacs')) {
        if (nm.includes('acl')) {
          return { pre_check: ['show ip access-lists'], post_check: ['show ip access-lists'] };
        } else if (nm.includes('ssh') || nm.includes('aaa') || nm.includes('tacacs')) {
          return { pre_check: ['show run | include ssh', 'show run | include aaa'], post_check: ['show ssh', 'show run | include ssh'] };
        } else {
          return { pre_check: ['show running-config'], post_check: ['show running-config'] };
        }
      } else if (cat === 'switching' || nm.includes('vlan')) {
        return { pre_check: ['show vlan brief', 'show interfaces status'], post_check: ['show vlan brief', 'show interfaces status'] };
      } else if (cat === 'management' || nm.includes('snmp') || nm.includes('ntp')) {
        if (nm.includes('snmp')) {
          return { pre_check: ['show snmp'], post_check: ['show snmp'] };
        } else {
          return { pre_check: ['show ntp status'], post_check: ['show ntp status'] };
        }
      }
      return { pre_check: ['show version', 'show running-config | include interface'], post_check: ['show running-config | include interface', 'show interfaces status'] };
    }

    if (plat.includes('huawei') || plat.includes('h3c')) {
      if (cat === 'routing' || nm.includes('bgp') || nm.includes('ospf') || nm.includes('route')) {
        if (nm.includes('bgp')) {
          return { pre_check: ['display bgp peer', 'display ip routing-table'], post_check: ['display bgp peer', 'display ip routing-table'] };
        } else if (nm.includes('ospf')) {
          return { pre_check: ['display ospf peer brief', 'display ip routing-table'], post_check: ['display ospf peer brief', 'display ip routing-table'] };
        } else {
          return { pre_check: ['display ip routing-table'], post_check: ['display ip routing-table'] };
        }
      } else if (cat === 'security' || nm.includes('acl') || nm.includes('ssh') || nm.includes('aaa') || nm.includes('tacacs')) {
        if (nm.includes('acl')) {
          return { pre_check: ['display acl all'], post_check: ['display acl all'] };
        } else if (nm.includes('ssh') || nm.includes('aaa') || nm.includes('tacacs')) {
          return { pre_check: ['display local-user'], post_check: ['display local-user'] };
        } else {
          return { pre_check: ['display current-configuration'], post_check: ['display current-configuration'] };
        }
      } else if (cat === 'switching' || nm.includes('vlan')) {
        return { pre_check: ['display vlan'], post_check: ['display vlan'] };
      } else if (cat === 'management' || nm.includes('snmp') || nm.includes('ntp')) {
        if (nm.includes('snmp')) {
          return { pre_check: ['display snmp-agent sys-info'], post_check: ['display snmp-agent sys-info'] };
        } else {
          return { pre_check: ['display ntp-service status'], post_check: ['display ntp-service status'] };
        }
      }
      return { pre_check: ['display version', 'display current-configuration | include interface'], post_check: ['display current-configuration | include interface', 'display interface'] };
    }

    if (plat.includes('juniper')) {
      if (cat === 'routing' || nm.includes('bgp') || nm.includes('ospf') || nm.includes('route')) {
        if (nm.includes('bgp')) {
          return { pre_check: ['show bgp summary', 'show route'], post_check: ['show bgp summary', 'show route'] };
        } else if (nm.includes('ospf')) {
          return { pre_check: ['show ospf neighbor', 'show route'], post_check: ['show ospf neighbor', 'show route'] };
        } else {
          return { pre_check: ['show route'], post_check: ['show route'] };
        }
      } else if (cat === 'security' || nm.includes('acl') || nm.includes('ssh') || nm.includes('aaa')) {
        if (nm.includes('acl') || nm.includes('filter')) {
          return { pre_check: ['show firewall'], post_check: ['show firewall'] };
        } else {
          return { pre_check: ['show system services'], post_check: ['show system services'] };
        }
      } else if (cat === 'switching' || nm.includes('vlan')) {
        return { pre_check: ['show vlans'], post_check: ['show vlans'] };
      } else if (cat === 'management' || nm.includes('snmp') || nm.includes('ntp')) {
        if (nm.includes('snmp')) {
          return { pre_check: ['show snmp mib'], post_check: ['show snmp mib'] };
        } else {
          return { pre_check: ['show ntp status'], post_check: ['show ntp status'] };
        }
      }
      return { pre_check: ['show version', 'show configuration | display set | grep interface'], post_check: ['show configuration | display set | grep interface', 'show interfaces'] };
    }

    if (plat.includes('arista')) {
      if (cat === 'routing' || nm.includes('bgp') || nm.includes('ospf') || nm.includes('route')) {
        if (nm.includes('bgp')) {
          return { pre_check: ['show ip bgp summary', 'show ip route'], post_check: ['show ip bgp summary', 'show ip route'] };
        } else if (nm.includes('ospf')) {
          return { pre_check: ['show ip ospf neighbor', 'show ip route'], post_check: ['show ip ospf neighbor', 'show ip route'] };
        } else {
          return { pre_check: ['show ip route'], post_check: ['show ip route'] };
        }
      } else if (cat === 'security' || nm.includes('acl') || nm.includes('ssh')) {
        return { pre_check: ['show ip access-lists'], post_check: ['show ip access-lists'] };
      } else if (cat === 'switching' || nm.includes('vlan')) {
        return { pre_check: ['show vlan'], post_check: ['show vlan'] };
      } else if (cat === 'management' || nm.includes('snmp') || nm.includes('ntp')) {
        if (nm.includes('snmp')) {
          return { pre_check: ['show snmp'], post_check: ['show snmp'] };
        } else {
          return { pre_check: ['show ntp status'], post_check: ['show ntp status'] };
        }
      }
      return { pre_check: ['show version', 'show running-config | include interface'], post_check: ['show running-config | include interface', 'show interfaces status'] };
    }

    return { pre_check: [], post_check: [] };
  };

  const scenarioOptions = useMemo(() => {
    const groups: Record<string, ConfigTemplate[]> = {};
    (configTemplates || []).forEach((template) => {
      if (template && template.id && template.name) {
        const nameKey = template.name.trim();
        if (!groups[nameKey]) {
          groups[nameKey] = [];
        }
        groups[nameKey].push(template);
      }
    });

    const configTemplateItems = Object.entries(groups).map(([name, templates]) => {
      const allPlatforms: string[] = [];
      const phases: Record<string, Partial<any>> = {};
      const variablesMap = new Map<string, any>();

      templates.forEach((template) => {
        const matchedPlatforms = Object.entries(platforms)
          .filter(([, meta]) => !template.vendor || (meta as PlatformMeta)?.vendor === template.vendor)
          .map(([key]) => key);
        const fallbackPlatforms = ['cisco_ios', 'huawei_vrp', 'h3c_comware', 'linux'];
        const supportedPlatforms = matchedPlatforms.length > 0 
          ? matchedPlatforms 
          : (Object.keys(platforms).length > 0 ? Object.keys(platforms) : fallbackPlatforms);

        supportedPlatforms.forEach((platformKey) => {
          if (!allPlatforms.includes(platformKey)) {
            allPlatforms.push(platformKey);
          }
          const { pre_check, post_check } = getDefaultPrePostCheck(platformKey, template.category, template.name);
          phases[platformKey] = {
            pre_check,
            execute: template.content ? [template.content] : [],
            post_check,
            rollback: template.rollback ? [template.rollback] : [],
          };
        });

        const varMatches = [...(template.content || '').matchAll(/\{\{\s*([\w.-]+)(?:\s*\|\s*[^}]+)?\s*\}\}/g)];
        const uniqueVars = [...new Set(varMatches.map(m => m[1]))];
        uniqueVars.forEach(key => {
          if (!variablesMap.has(key)) {
            const meta = inferVariableMeta(key);
            variablesMap.set(key, {
              key,
              label: key,
              label_zh: key,
              ...meta,
            });
          }
        });
      });

      const firstTemplate = templates[0];
      return {
        id: toConfigTemplateScenarioId(firstTemplate.id),
        source_kind: 'config_template' as const,
        source_template_id: firstTemplate.id,
        name: name,
        name_zh: name,
        description: firstTemplate.category || '',
        description_zh: firstTemplate.category || '',
        category: firstTemplate.category,
        icon: '📄',
        risk: 'medium',
        supported_platforms: allPlatforms,
        default_platform: allPlatforms[0] || '',
        variables: Array.from(variablesMap.values()),
        platform_phases: phases,
        templates: templates,
      } as ScenarioTemplate;
    });

    const combined = [...(scenarios || []), ...configTemplateItems];
    return combined.sort((a, b) => {
      const nameA = zh ? (a.name_zh || a.name) : a.name;
      const nameB = zh ? (b.name_zh || b.name) : b.name;
      return nameA.localeCompare(nameB);
    });
  }, [configTemplates, scenarios, platforms, zh]);

  const selectedScenario = useMemo(
    () => scenarioOptions.find((item) => item.id === selectedScenarioId) || null,
    [scenarioOptions, selectedScenarioId],
  );

  const selectedScenarioPlatforms = useMemo(() => {
    if (!selectedScenario) return [] as string[];
    const allPlatforms = selectedScenario.supported_platforms?.length
      ? selectedScenario.supported_platforms
      : Object.keys(selectedScenario.platform_phases || {});
    
    const devicePlatforms = [...new Set(form.target_devices.map((d: any) => d.platform).filter(Boolean))];
    if (devicePlatforms.length > 0) {
      const filtered = allPlatforms.filter(p => 
        devicePlatforms.some(dp => findMatchingPlatform(dp || '', [p]))
      );
      if (filtered.length > 0) return filtered;
    }
    
    return allPlatforms;
  }, [selectedScenario, form.target_devices, findMatchingPlatform]);

  const selectedScenarioVariables = useMemo(() => {
    if (!selectedScenario) return [];
    
    if (selectedScenario.source_kind !== 'config_template') {
      return (selectedScenario.variables || []).filter((item) => item?.key);
    }
    
    const targetVendor = platforms[selectedScenarioPlatform]?.vendor;
    const matchedTemplate = (selectedScenario.templates || []).find(tpl => tpl.vendor === targetVendor) || 
                            (selectedScenario.templates || []).find(tpl => tpl.vendor?.toLowerCase() === targetVendor?.toLowerCase()) ||
                            (selectedScenario.templates || [])[0];
                            
    if (!matchedTemplate) return [];
    
    const content = matchedTemplate.content || '';
    const varMatches = [...content.matchAll(/\{\{\s*([\w.-]+)(?:\s*\|\s*[^}]+)?\s*\}\}/g)];
    const uniqueKeys = [...new Set(varMatches.map(m => m[1]))];
    
    return uniqueKeys.map(key => {
      const existing = (selectedScenario.variables || []).find(v => v.key === key);
      if (existing) return existing;
      const meta = inferVariableMeta(key);
      return {
        key,
        label: key,
        label_zh: key,
        ...meta,
      };
    });
  }, [selectedScenario, selectedScenarioPlatform, platforms]);

  const resolvedTemplateId = useMemo(() => {
    if (!selectedScenarioId) return '';
    if (!isConfigTemplateScenarioId(selectedScenarioId)) {
      return selectedScenarioId;
    }
    const baseId = fromConfigTemplateScenarioId(selectedScenarioId);
    if (!selectedScenario || !selectedScenario.templates || selectedScenario.templates.length === 0) {
      return baseId;
    }
    const targetVendor = platforms[selectedScenarioPlatform]?.vendor;
    if (targetVendor) {
      const matched = selectedScenario.templates.find(tpl => tpl.vendor === targetVendor);
      if (matched) return matched.id;
    }
    const matchedCaseInsensitive = selectedScenario.templates.find(tpl => 
      tpl.vendor?.toLowerCase() === targetVendor?.toLowerCase()
    );
    if (matchedCaseInsensitive) return matchedCaseInsensitive.id;
    return selectedScenario.templates[0].id;
  }, [selectedScenarioId, selectedScenario, selectedScenarioPlatform, platforms]);

  const templateMissingRequired = useMemo(() => selectedScenarioVariables
    .filter((item) => item.required && !String(templateVariables[item.key] ?? '').trim())
    .map((item) => zh ? item.label_zh || item.label || item.key : item.label || item.key), [selectedScenarioVariables, templateVariables, zh]);

  const assignTemplateVariable = useCallback((key: string, value: string) => {
    setTemplateVariables((current) => ({ ...current, [key]: value }));
  }, []);

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

  const getLocalTemplatePreview = (platformOverride?: string) => {
    const platformToUse = platformOverride || selectedScenarioPlatform;
    if (!selectedScenario || !platformToUse) return null;
    const phases = selectedScenario.platform_phases?.[platformToUse] || {};
    return {
      pre_check: renderPhaseCommands(phases.pre_check || [], templateVariables),
      execute: renderPhaseCommands(phases.execute || [], templateVariables),
      post_check: renderPhaseCommands(phases.post_check || [], templateVariables),
      rollback: renderPhaseCommands(phases.rollback || [], templateVariables),
    };
  };

  const effectivePreview = useMemo(() => {
    const platformToUse = selectedScenarioPlatform || selectedScenarioPlatforms[0] || '';
    return getLocalTemplatePreview(platformToUse);
  }, [selectedScenarioPlatform, selectedScenarioPlatforms, selectedScenario, templateVariables]);

  // ── Fetch functions ──
  const fetchOrders = useCallback(async () => {
    orderListRequestController.current?.abort();
    const controller = new AbortController();
    orderListRequestController.current = controller;
    const requestSequence = ++orderListRequestSequence.current;
    let requestError: ChangeOrderRequestError = 'load';
    setLoading(true);
    setListError(null);
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
      const resp = await fetch(`/api/change-orders?${params}`, { headers: authHeaders(), signal: controller.signal });
      if (!resp.ok) {
        if (resp.status === 401 || resp.status === 403) requestError = 'permission';
        throw new Error('Failed to load change orders');
      }
      const data = await resp.json();
      if (data.success) {
        if (requestSequence !== orderListRequestSequence.current) return;
        setOrders(data.data);
        setTotal(data.total);
      } else if (requestSequence === orderListRequestSequence.current) {
        setListError(requestError);
      }
    } catch {
      if (controller.signal.aborted || requestSequence !== orderListRequestSequence.current) return;
      setListError(requestError);
      if (requestError === 'permission') {
        setOrders([]);
        setTotal(0);
        setBookmarkedIds(new Set());
      }
      showToast(zh ? '加载失败' : 'Load failed', 'error');
    } finally {
      if (requestSequence === orderListRequestSequence.current) {
        orderListRequestController.current = null;
        setLoading(false);
      }
    }
  }, [page, pageSize, search, statusFilter, priorityFilter, requesterFilter, assigneeFilter, bookmarkFilter, orderTypeFilter, createdFrom, createdTo, completedFrom, completedTo, scheduledFrom, scheduledTo, viewTab, currentUser.id, currentUser.username, currentUser.change_groups, zh, showToast, authHeaders]);

  useEffect(() => {
    const safePage = clampChangeOrderPage(page, total, pageSize);
    if (safePage !== page) setPage(safePage);
  }, [page, pageSize, total]);

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
    const requestSequence = ++timelineRequestSequence.current;
    setTimelineLoading(true);
    try {
      const resp = await fetch(`/api/change-orders/${orderId}/timeline`, { headers: authHeaders() });
      if (!resp.ok) throw new Error('Failed to load change order timeline');
      const data = await resp.json();
      if (requestSequence !== timelineRequestSequence.current) return;
      if (data.success) setTimeline(Array.isArray(data.data) ? data.data : []);
      else setTimeline([]);
    } catch {
      if (requestSequence === timelineRequestSequence.current) setTimeline([]);
    } finally {
      if (requestSequence === timelineRequestSequence.current) setTimelineLoading(false);
    }
  }, [authHeaders]);

  useEffect(() => () => {
    detailRequestSequence.current += 1;
    timelineRequestSequence.current += 1;
  }, []);

  useEffect(() => {
    void fetchOrders();
    return () => {
      orderListRequestSequence.current += 1;
      orderListRequestController.current?.abort();
    };
  }, [fetchOrders]);
  useEffect(() => { fetchSummary(); }, [fetchSummary]);
  useEffect(() => { fetchBookmarks(); }, [fetchBookmarks]);

  // ── Save Order logic ──
  const saveOrder = async (closeAfterSave = true, asDraft = false, explicitInitialReviewerId?: string) => {
    const effectiveScenarioPlatform = selectedScenarioPlatform || selectedScenarioPlatforms[0] || '';
    const reviewerIdToUse = explicitInitialReviewerId || form.assigned_initial_reviewer_id;
    let validatedRollbackCommands: unknown;
    let resolvedRollbackPlan = commandMode === 'template'
      ? resolveChangeOrderRollbackPlan(form.rollback_plan, effectivePreview?.rollback)
      : String(form.rollback_plan || '').trim();
    
    if (!form.title.trim()) {
      showToast(zh ? '请输入工单标题' : 'Title is required', 'error');
      return;
    }

    if (!asDraft) {
      const implementerConflict = getImplementerConflictRole(form.control_sheet?.implementer_id, {
        co_reviewer: form.control_sheet?.co_reviewer_id,
        business_confirmer: form.control_sheet?.business_confirmer_id,
        initial_reviewer: reviewerIdToUse,
        final_approver: form.assigned_final_approver_id,
      });
      if (implementerConflict) {
        const roleLabels = {
          co_reviewer: zh ? '复核人' : 'reviewer',
          business_confirmer: zh ? '业务确认人' : 'business confirmer',
          initial_reviewer: zh ? '初审人' : 'initial reviewer',
          final_approver: zh ? '终审人' : 'final approver',
        };
        showToast(zh
          ? `实施人不能与${roleLabels[implementerConflict]}相同，请重新选择。`
          : `The implementer must differ from the ${roleLabels[implementerConflict]}.`, 'error');
        return;
      }
      if (form.order_type === 'emergency') {
        if (!String(form.emergency_reason || '').trim()) {
          showToast(zh ? '请填写紧急原因' : 'Emergency reason is required', 'error');
          return;
        }
        if (!String(form.emergency_review_owner_id || '').trim()) {
          showToast(zh ? '请选择事后复核人' : 'Select a post-review owner', 'error');
          return;
        }
        if (form.emergency_review_owner_id === currentUser.id || form.emergency_review_owner_id === form.control_sheet?.implementer_id) {
          showToast(zh ? '事后复核人必须与申请人、实施人分离' : 'The post-review owner must differ from the requester and implementer', 'error');
          return;
        }
        const reviewDue = new Date(String(form.emergency_review_due_at || '').replace(' ', 'T'));
        if (!form.emergency_review_due_at || Number.isNaN(reviewDue.getTime()) || reviewDue.getTime() <= Date.now()) {
          showToast(zh ? '事后复核期限必须晚于当前时间' : 'Post-review due time must be in the future', 'error');
          return;
        }
      }
      if (!form.scheduled_start) {
        showToast(zh ? '请选择计划开始时间' : 'Scheduled start time is required', 'error');
        return;
      }
      if (!form.scheduled_end) {
        showToast(zh ? '请选择计划结束时间' : 'Scheduled end time is required', 'error');
        return;
      }
      if (form.scheduled_start && form.scheduled_end) {
        if (form.scheduled_start >= form.scheduled_end) {
          showToast(zh ? '计划结束时间必须晚于开始时间' : 'End time must be after start time', 'error');
          return;
        }
        const startMs = new Date(form.scheduled_start.replace(' ', 'T')).getTime();
        const endMs = new Date(form.scheduled_end.replace(' ', 'T')).getTime();
        if (endMs - startMs > 14 * 24 * 60 * 60 * 1000) {
          showToast(zh ? '计划周期不能超过 2 周' : 'Duration cannot exceed 2 weeks', 'error');
          return;
        }
      }
      if (!form.target_devices || form.target_devices.length === 0) {
        showToast(zh ? '请选择目标设备' : 'Add at least one target device', 'error');
        return;
      }
      
      if (commandMode === 'manual' && form.commands.length === 0) {
        showToast(zh ? '请至少添加一条执行命令' : 'Add at least one command', 'error');
        return;
      }
      if (commandMode === 'template') {
        if (!selectedScenarioId) {
          showToast(zh ? '请先选择场景并填写必填变量' : 'Please select a scenario and fill in all required variables', 'error');
          return;
        }
        if (!effectiveScenarioPlatform) {
          showToast(zh ? '无法确定目标平台' : 'Cannot determine target platform', 'error');
          return;
        }
        if (templateMissingRequired.length > 0) {
          showToast(zh ? `请先填写必填变量：${templateMissingRequired.join('、')}` : `Fill required variables: ${templateMissingRequired.join(', ')}`, 'error');
          return;
        }

        setSaving(true);
        try {
          const checkPayload = {
            scenario_id: resolvedTemplateId,
            source_kind: selectedScenario?.source_kind || 'scenario',
            platform: effectiveScenarioPlatform,
            variables: templateVariables,
            target_devices: form.target_devices,
          };
          const checkResp = await fetch('/api/change-orders/validate', {
            method: 'POST',
            headers: authHeaders(true),
            body: JSON.stringify(checkPayload),
          });
          const checkData = await checkResp.json();
          if (!checkData.success || !checkData.valid) {
            showToast(zh ? '参数校验失败，请检查并核对参数输入' : 'Validation failed, please check your parameters', 'error');
            setSaving(false);
            return;
          }
          if (Array.isArray(checkData.preview?.rollback)) {
            validatedRollbackCommands = checkData.preview.rollback;
          }
          resolvedRollbackPlan = buildChangeOrderRollbackFields(
            form.rollback_plan,
            effectivePreview?.rollback,
            validatedRollbackCommands,
          ).rollback_plan;
          setSaving(false);
        } catch {
          showToast(zh ? '预检查失败' : 'Precheck failed', 'error');
          setSaving(false);
          return;
        }
      }

      if (!resolvedRollbackPlan) {
        showToast(zh ? '请输入回退方案，或在模板中配置回退命令。' : 'Enter a rollback plan or configure rollback commands in the template.', 'error');
        return;
      }

      const missingControlSheetFields = getMissingChangeOrderControlSheetFields(form.control_sheet);
      if (missingControlSheetFields.length > 0) {
        const fieldLabels: Record<string, string> = {
          implementer_id: zh ? '实施人' : 'Implementer',
          co_reviewer_id: zh ? '复核人' : 'Reviewer',
          pre_check: zh ? '变更前检查' : 'Pre-check',
          execution: zh ? '人工实施步骤' : 'Manual implementation steps',
          post_verify: zh ? '变更后验证' : 'Post-change verification',
          business_verify: zh ? '业务验证' : 'Business verification',
        };
        showToast(
          zh
            ? `请完善变更控制表：${missingControlSheetFields.map((field) => fieldLabels[field]).join('、')}`
            : `Complete the change control sheet: ${missingControlSheetFields.map((field) => fieldLabels[field]).join(', ')}`,
          'error',
        );
        return;
      }

      if (!reviewerIdToUse) {
        setInitialApproverPrompt({
          onConfirm: (id: string) => {
            saveOrder(closeAfterSave, asDraft, id);
          }
        });
        return;
      }
    }

    setSaving(true);
    try {
      const payload: any = {
        ...form,
        authorization_exempt: form.authorization_exempt ?? false,
        assigned_initial_reviewer_id: reviewerIdToUse || '',
        status: asDraft ? 'draft' : 'initial_review',
        command_template: {},
        commands: form.commands,
        rollback_plan: resolvedRollbackPlan,
      };
      if (!editingOrder && incidentTicketIdFromQuery) {
        payload.incident_ticket_id = incidentTicketIdFromQuery;
      }

      if (FEATURE_CONTROL_SHEET) {
        const cs = form.control_sheet;
        payload.control_sheet = {
          change_time: {
            start: cs.change_time_start || '',
            end: cs.change_time_end || '',
          },
          implementer: {
            id: cs.implementer_id || '',
            username: cs.implementer_username || '',
          },
          co_reviewer: {
            id: cs.co_reviewer_id || '',
            username: cs.co_reviewer_username || '',
          },
          business_confirmer: {
            id: cs.business_confirmer_id || '',
            username: cs.business_confirmer_username || '',
          },
          device_ips: cs.device_ips
            ? cs.device_ips.split(/[\n,]+/).map((s: string) => s.trim()).filter(Boolean)
            : [],
          pre_check: cs.pre_check || '',
          execution: cs.execution || '',
          post_verify: cs.post_verify || '',
          business_verify: cs.business_verify || '',
          rollback_plan: resolvedRollbackPlan,
        };
      }

      if (commandMode === 'template' && selectedScenarioId && effectiveScenarioPlatform) {
        payload.command_template = {
          scenario_id: resolvedTemplateId,
          source_kind: selectedScenario?.source_kind || 'scenario',
          platform: effectiveScenarioPlatform,
          variables: templateVariables,
        };
        if (effectivePreview?.execute?.length) {
          payload.commands = effectivePreview.execute;
        }
      }

      if (FEATURE_CONTROL_SHEET) {
        const synchronizedSheet = synchronizeControlSheetMirrors(form.control_sheet, {
          scheduledStart: payload.scheduled_start || '',
          scheduledEnd: payload.scheduled_end || '',
          targetIps: (payload.target_devices || []).map((device: { ip_address?: string }) => device.ip_address || ''),
          rollbackPlan: payload.rollback_plan || '',
        });
        payload.control_sheet = {
          ...payload.control_sheet,
          change_time: {
            start: synchronizedSheet.change_time_start || '',
            end: synchronizedSheet.change_time_end || '',
          },
          device_ips: synchronizedSheet.device_ips
            ? synchronizedSheet.device_ips.split(/[\n,]+/).map((value: string) => value.trim()).filter(Boolean)
            : [],
          rollback_plan: synchronizedSheet.rollback_plan || '',
        };
      }

      const rollbackFields = buildChangeOrderRollbackFields(
        form.rollback_plan,
        effectivePreview?.rollback,
        validatedRollbackCommands,
        payload.control_sheet || {},
      );
      payload.rollback_plan = rollbackFields.rollback_plan;
      if (FEATURE_CONTROL_SHEET) payload.control_sheet = rollbackFields.control_sheet;

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
        if (editingOrder === null && data.data) {
          setEditingOrder(data.data);
        }
        if (closeAfterSave && !asDraft) {
          closeEditor(true);
        }
        window.dispatchEvent(new CustomEvent('refresh-todo-badge'));
        fetchOrders();
        fetchSummary();
        if (asDraft) {
          if (!isCreateView) {
            closeEditor(true);
          } else {
            setShowCreateModal(false);
            resetEditorState();
          }
          navigate('/change-orders/drafts');
        }
      } else {
        showToast(formatChangeOrderApiMessage(data.detail ?? data.message, language, zh ? '保存失败' : 'Save failed'), 'error');
      }
    } catch {
      showToast(zh ? '保存失败' : 'Save failed', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleSave = () => saveOrder(true, false);
  const handleSaveDraft = () => saveOrder(true, true);

  // ── Transition Action ──
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
        window.dispatchEvent(new CustomEvent('refresh-todo-badge'));
        fetchOrders();
        fetchSummary();
      } else {
        showToast(formatChangeOrderApiMessage(data.detail ?? data.message, language, zh ? '操作失败' : 'Action failed'), 'error');
      }
    } catch { showToast(zh ? '操作失败' : 'Failed', 'error'); }
  };

  const handleAssignment = async (orderId: string, request: AssignmentRequest): Promise<ChangeOrderMutationResult> => {
    try {
      const resp = await fetch(`/api/change-orders/${orderId}/assignment`, {
        method: 'POST',
        headers: authHeaders(true),
        body: JSON.stringify(request),
      });
      const data = await resp.json();
      if (!resp.ok || !data.success || !data.data) {
        const detail = data.detail ?? data.message;
        return { success: false, message: formatChangeOrderApiMessage(detail, language, zh ? '责任分配失败' : 'Assignment failed') };
      }
      setSelectedOrder(data.data);
      fetchTimeline(orderId);
      window.dispatchEvent(new CustomEvent('refresh-todo-badge'));
      fetchOrders();
      fetchSummary();
      return { success: true, order: data.data };
    } catch (error) {
      return { success: false, message: formatChangeOrderApiMessage(error, language, zh ? '责任分配请求失败' : 'Assignment request failed') };
    }
  };

  const handleVerification = async (orderId: string, request: VerificationRequest): Promise<ChangeOrderMutationResult> => {
    try {
      const resp = await fetch(`/api/change-orders/${orderId}/verification`, {
        method: 'POST',
        headers: authHeaders(true),
        body: JSON.stringify(request),
      });
      const data = await resp.json();
      if (!resp.ok || !data.success || !data.data) {
        const detail = data.detail ?? data.message;
        return { success: false, message: formatChangeOrderApiMessage(detail, language, zh ? '验证结果提交失败' : 'Verification submission failed') };
      }
      setSelectedOrder(data.data);
      fetchTimeline(orderId);
      window.dispatchEvent(new CustomEvent('refresh-todo-badge'));
      fetchOrders();
      fetchSummary();
      return { success: true, order: data.data };
    } catch (error) {
      return { success: false, message: formatChangeOrderApiMessage(error, language, zh ? '验证结果请求失败' : 'Verification request failed') };
    }
  };

  const handleResultReview = async (orderId: string, action: ResultReviewAction, summary: string) => {
    try {
      const response = await fetch(`/api/change-orders/${encodeURIComponent(orderId)}/result-review`, {
        method: 'POST', headers: authHeaders(true), body: JSON.stringify({ action, summary }),
      });
      const data = await response.json();
      if (!response.ok || !data.success || !data.data) {
        showToast(formatChangeOrderApiMessage(data.detail ?? data.message, language, zh ? '实施复核提交失败' : 'Result review failed'), 'error');
        return;
      }
      setSelectedOrder(data.data);
      fetchTimeline(orderId); fetchOrders(); fetchSummary();
      window.dispatchEvent(new CustomEvent('refresh-todo-badge'));
      showToast(zh ? '实施复核结果已提交' : 'Result review submitted', 'success');
    } catch { showToast(zh ? '实施复核请求失败' : 'Result review request failed', 'error'); }
  };

  const handleEmergencyReview = async (
    orderId: string,
    outcome: 'accepted' | 'follow_up_required',
    note: string,
  ): Promise<ChangeOrderMutationResult> => {
    try {
      const response = await fetch(`/api/change-orders/${encodeURIComponent(orderId)}/emergency-review`, {
        method: 'POST',
        headers: authHeaders(true),
        body: JSON.stringify({ outcome, note }),
      });
      const payload = await response.json();
      const order = payload?.order as IChangeOrder | undefined;
      if (!response.ok || !payload?.success || !order) {
        const detail = payload?.detail || payload?.message;
        return { success: false, message: formatChangeOrderApiMessage(detail, language, zh ? '事后复核未能保存' : 'Post-review could not be saved') };
      }
      setSelectedOrder(order);
      fetchTimeline(orderId);
      fetchOrders();
      fetchSummary();
      return { success: true, order };
    } catch (error) {
      return { success: false, message: formatChangeOrderApiMessage(error, language, zh ? '事后复核请求失败' : 'Post-review request failed') };
    }
  };

  // ── Run Order Commands ──
  const runOrderCommands = async () => {
    if (!executeModal) return;
    const order = executeModal.order;
    const commands = (order.commands || []).join('\n').trim();
    const targetDevices = order.target_devices || [];

    if (!commands) {
      setExecuteModal({ ...executeModal, phase: 'done', success: false, error: zh ? '工单中没有可下发的命令' : 'No commands to execute' });
      return;
    }
    if (targetDevices.length === 0) {
      setExecuteModal({ ...executeModal, phase: 'done', success: false, error: zh ? '工单未关联目标设备' : 'No target devices linked to this order' });
      return;
    }

    setExecuteModal({ ...executeModal, phase: 'running', output: '', error: '', success: false, requestSent: false });

    try {
      const invResp = await fetch('/api/devices?mode=light', { headers: authHeaders() });
      if (!invResp.ok) {
        setExecuteModal((prev) => prev && ({
          ...prev,
          phase: 'done',
          success: false,
          error: zh ? '无法获取设备清单以解析目标设备' : 'Failed to load device inventory to resolve target devices',
        }));
        return;
      }
      const invData = await invResp.json();
      const inventory: Array<{ id: string; hostname?: string; ip_address?: string }> =
        Array.isArray(invData) ? invData : (invData?.data || []);
      const resolved: Array<{ id: string; hostname: string; ip_address: string }> = [];
      const unresolved: string[] = [];
      targetDevices.forEach((td: any) => {
        const match = inventory.find(d =>
          (td.ip_address && d.ip_address === td.ip_address) ||
          (td.hostname && d.hostname === td.hostname)
        );
        if (match && match.id) {
          resolved.push({ id: match.id, hostname: td.hostname || match.hostname || '', ip_address: td.ip_address || match.ip_address || '' });
        } else {
          unresolved.push(td.hostname || td.ip_address || 'unknown');
        }
      });

      if (resolved.length === 0) {
        setExecuteModal((prev) => prev && ({
          ...prev,
          phase: 'done',
          success: false,
          error: zh
            ? `工单中的目标设备未在资产库中找到匹配项：${unresolved.join(', ')}。请确认这些设备已添加到设备清单。`
            : `Target devices not found in inventory: ${unresolved.join(', ')}. Please add them first.`,
        }));
        return;
      }

      setSentExecutionRequestKeys(previous => new Set(previous).add(executionRequestKey(order)));
      setExecuteModal((prev) => prev && ({ ...prev, requestSent: true }));
      const resp = await fetch('/api/execute', {
        method: 'POST',
        headers: authHeaders(true),
        body: JSON.stringify({
          device_ids: resolved.map(r => r.id),
          command: commands,
          isConfig: true,
          change_ticket: order.order_number,
          task_name: `ChangeOrder ${order.order_number}: ${order.title}`,
          auth_role: getChangeOrderExecutionAuthRole(currentUser),
        }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        setExecuteModal((prev) => prev && ({
          ...prev,
          phase: 'done',
          success: false,
          error: formatChangeOrderApiMessage(data.detail ?? data.message, language, zh ? '执行失败' : 'Execution failed'),
        }));
        return;
      }
      
      let combined = '';
      if (data.results) {
        Object.entries(data.results as Record<string, any>).forEach(([devId, res]: [string, any]) => {
          const dev = resolved.find(r => r.id === devId);
          const label = dev ? `${dev.hostname || devId} (${dev.ip_address || ''})` : devId;
          combined += `\n────── ${label} ──────\n${res.output || ''}\n`;
        });
      } else if (data.output) {
        combined = String(data.output);
      }
      if (unresolved.length) {
        combined += `\n\n[${zh ? '已跳过资产库中不存在的设备' : 'Skipped devices not found in inventory'}]: ${unresolved.join(', ')}`;
      }
      const resultEntries = Object.entries((data.results || {}) as Record<string, any>);
      const hasFailedDevice = resultEntries.some(([, result]) =>
        String(result?.status || '').toLowerCase() !== 'success'
      );
      const hasError = /Error:/i.test(combined)
        || data.status !== 'completed'
        || resultEntries.length === 0
        || hasFailedDevice;
      setExecuteModal((prev) => prev && ({
        ...prev,
        phase: 'done',
        success: !hasError,
        output: combined.trim(),
        error: hasError ? (zh ? '部分命令执行返回错误，请检查输出' : 'Some commands returned errors, please review the output') : '',
      }));
    } catch (err: unknown) {
      setExecuteModal((prev) => prev && ({
        ...prev,
        phase: 'done',
        success: false,
        error: formatChangeOrderApiMessage(err, language, zh ? '请求失败' : 'Request failed'),
      }));
    }
  };

  // ── Delete Order ──
  const handleDelete = async (orderId: string) => {
    if (!confirm(zh ? '确定删除此工单？' : 'Delete this change order?')) return;
    try {
      const resp = await fetch(`/api/change-orders/${orderId}`, { method: 'DELETE', headers: authHeaders() });
      const data = await resp.json();
      if (data.success) {
        showToast(data.message || (zh ? '已删除' : 'Deleted'));
        if (selectedOrder?.id === orderId) {
          closeDetail();
        }
        fetchOrders();
        fetchSummary();
      } else {
        showToast(formatChangeOrderApiMessage(data.detail ?? data.message, language, zh ? '删除失败' : 'Delete failed'), 'error');
      }
    } catch { showToast(zh ? '删除失败' : 'Delete failed', 'error'); }
  };

  // ── Bookmark Toggle ──
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

  // ── Copy Order → Open composer ──
  const handleCopyOrder = (order: IChangeOrder) => {
    setEditingOrder(null);
    closeDetail();
    const existingCs = order.control_sheet || {};
    setForm({
      title: `${order.title} (${zh ? '副本' : 'Copy'})`,
      incident_id: order.incident_id || '',
      description: order.description,
      order_type: order.order_type,
      emergency_reason: '',
      emergency_review_owner_id: '',
      emergency_review_due_at: '',
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
      authorization_exempt: order.authorization_exempt ?? false,
      control_sheet: {
        change_time_start: existingCs.change_time?.start || '',
        change_time_end: existingCs.change_time?.end || '',
        implementer_id: existingCs.implementer?.id || '',
        implementer_username: existingCs.implementer?.username || '',
        co_reviewer_id: existingCs.co_reviewer?.id || '',
        co_reviewer_username: existingCs.co_reviewer?.username || '',
        business_confirmer_id: existingCs.business_confirmer?.id || existingCs.business_verifier?.id || existingCs.business_confirmer_id || existingCs.business_verifier_id || '',
        business_confirmer_username: existingCs.business_confirmer?.username || existingCs.business_verifier?.username || existingCs.business_confirmer_username || existingCs.business_verifier_username || '',
        device_ips: Array.isArray(existingCs.device_ips) ? existingCs.device_ips.join('\n') : (existingCs.device_ips || ''),
        pre_check: existingCs.pre_check || '',
        execution: existingCs.execution || '',
        post_verify: existingCs.post_verify || '',
        business_verify: existingCs.business_verify || '',
        rollback_plan: existingCs.rollback_plan || '',
      },
    });
    setCommandMode('manual');
    setShowCreateModal(true);
    showToast(zh ? '工单内容已复制，请修改后提交' : 'Order copied, edit and submit');
  };

  // ── Save as Template ──
  const handleSaveAsTemplate = async (order: IChangeOrder) => {
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
        showToast(formatChangeOrderApiMessage(data.detail ?? data.message, language, zh ? '保存失败' : 'Save failed'), 'error');
      }
    } catch { showToast(zh ? '保存失败' : 'Save failed', 'error'); }
  };

  // ── Export CSV ──
  const handleExportOrder = (order: IChangeOrder) => {
    const cs = order.control_sheet || {};
    const attachments = order.control_sheet_attachments || [];
    const rows: (string[] | string)[] = [];

    rows.push([zh ? '字段' : 'Field', zh ? '值' : 'Value']);
    rows.push([zh ? '工单号' : 'Order Number', order.order_number]);
    rows.push([zh ? '标题' : 'Title', order.title]);
    rows.push([zh ? '描述' : 'Description', order.description || '']);
    rows.push([zh ? '类型' : 'Type', zh ? ORDER_TYPE_META[order.order_type]?.label?.zh : ORDER_TYPE_META[order.order_type]?.label?.en]);
    rows.push([zh ? '优先级' : 'Priority', zh ? PRIORITY_META[order.priority]?.label?.zh : PRIORITY_META[order.priority]?.label?.en]);
    rows.push([zh ? '风险等级' : 'Risk Level', zh ? RISK_META[order.risk_level]?.label?.zh : RISK_META[order.risk_level]?.label?.en]);
    rows.push([zh ? '状态' : 'Status', zh ? STATUS_META[order.status]?.label?.zh : STATUS_META[order.status]?.label?.en]);
    rows.push([zh ? '申请人' : 'Requester', order.requester_username || '']);
    rows.push([zh ? '初审人' : 'Initial Reviewer', order.initial_reviewer_username || '']);
    rows.push([zh ? '终审人' : 'Final Approver', order.final_approver_username || order.approver_username || '']);
    rows.push([zh ? '创建时间' : 'Created At', fmtDate(order.created_at)]);
    rows.push([zh ? '计划开始' : 'Scheduled Start', order.scheduled_start ? fmtDate(order.scheduled_start) : '']);
    rows.push([zh ? '计划结束' : 'Scheduled End', order.scheduled_end ? fmtDate(order.scheduled_end) : '']);
    rows.push([zh ? '实际开始' : 'Actual Start', order.actual_start ? fmtDate(order.actual_start) : '']);
    rows.push([zh ? '实际结束' : 'Actual End', order.actual_end ? fmtDate(order.actual_end) : '']);
    rows.push([zh ? '执行结果' : 'Result Summary', order.result_summary || '']);
    rows.push([zh ? '驳回原因' : 'Rejection Reason', order.rejected_reason || '']);

    if (FEATURE_CONTROL_SHEET) {
      rows.push(['', '']);
      rows.push([zh ? '=== 变更控制表 ===' : '=== Control Sheet ===', '']);
      const changeTimeStart = cs.change_time?.start || '';
      const changeTimeEnd = cs.change_time?.end || '';
      rows.push([zh ? '变更时间窗口（开始）' : 'Change Time Start', changeTimeStart ? fmtDate(changeTimeStart) : '']);
      rows.push([zh ? '变更时间窗口（结束）' : 'Change Time End', changeTimeEnd ? fmtDate(changeTimeEnd) : '']);
      rows.push([zh ? '实施人' : 'Implementer', cs.implementer?.username || '']);
      rows.push([zh ? '复核人' : 'Reviewer', cs.co_reviewer?.username || '']);
      const deviceIps = Array.isArray(cs.device_ips) ? cs.device_ips.join(', ') : (cs.device_ips || '');
      rows.push([zh ? '目标设备IP' : 'Target Device IPs', deviceIps]);
      rows.push([zh ? '实施前检查' : 'Pre-Check', cs.pre_check || '']);
      rows.push([zh ? '执行步骤' : 'Execution Steps', cs.execution || '']);
      rows.push([zh ? '实施后验证' : 'Post-Verify', cs.post_verify || '']);
      rows.push([zh ? '业务验证' : 'Business Verify', cs.business_verify || '']);
      rows.push([zh ? '回退方案' : 'Rollback Plan', cs.rollback_plan || '']);

      if (attachments.length > 0) {
        rows.push(['', '']);
        rows.push([zh ? '=== 控制表附件 ===' : '=== Control Sheet Attachments ===', '']);
        rows.push([
          zh ? '文件名' : 'Filename',
          zh ? '大小' : 'Size',
          zh ? '上传人' : 'Uploaded By',
          zh ? '上传时间' : 'Uploaded At',
        ].join('\t'));
        attachments.forEach(att => {
          rows.push([
            att.filename,
            att.size_bytes + ' B',
            att.uploaded_by_username,
            fmtDate(att.uploaded_at),
          ].join('\t'));
        });
      }
    }

    const csvContent = '\ufeff' + rows.map(r =>
      Array.isArray(r) ? r.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(',') : r
    ).join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `${order.order_number}_${new Date().toISOString().slice(0, 10)}.csv`;
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    showToast(zh ? '导出成功' : 'Exported successfully');
  };

  // ── Open Detail panel ──
  const openDetail = async (order: IChangeOrder) => {
    const requestSequence = ++detailRequestSequence.current;
    timelineRequestSequence.current += 1;
    setDetailLoading(true);
    setDetailError(null);
    setTimelineLoading(false);
    setSelectedOrder(order);
    setTimeline([]);
    let requestError: ChangeOrderRequestError = 'load';
    let detailLoaded = false;
    try {
      const resp = await fetch(`/api/change-orders/${order.id}`, { headers: authHeaders() });
      if (!resp.ok) {
        if (resp.status === 401 || resp.status === 403) requestError = 'permission';
        throw new Error('Failed to load change order details');
      }
      const data = await resp.json();
      if (requestSequence !== detailRequestSequence.current) return;
      if (data.success) {
        setSelectedOrder(data.data);
        detailLoaded = true;
      } else {
        setDetailError(requestError);
      }
    } catch {
      if (requestSequence === detailRequestSequence.current) setDetailError(requestError);
    } finally {
      if (requestSequence === detailRequestSequence.current) {
        setDetailLoading(false);
        if (detailLoaded) void fetchTimeline(order.id);
      }
    }
  };

  const handleControlSheetUpload = async (orderId: string, file: File): Promise<ControlSheetUploadResult> => {
    const requiresReview = selectedOrder?.id === orderId && ['final_review', 'approved', 'implementing'].includes(selectedOrder.status);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const response = await fetch(`/api/change-orders/${encodeURIComponent(orderId)}/control-sheet`, {
        method: 'POST',
        headers: authHeaders(),
        body: formData,
      });
      const payload = await response.json();
      if (!response.ok || !payload?.success) {
        return {
          success: false,
          message: formatChangeOrderApiMessage(payload?.detail ?? payload?.message, language, zh ? '附件上传失败' : 'Attachment upload failed'),
        };
      }

      const orderForRefresh = selectedOrder?.id === orderId ? selectedOrder : orders.find(order => order.id === orderId);
      const detailRefresh = orderForRefresh ? openDetail(orderForRefresh) : Promise.resolve();
      await Promise.all([detailRefresh, fetchOrders(), fetchSummary()]);
      return { success: true, requiresReview };
    } catch (error) {
      return {
        success: false,
        message: formatChangeOrderApiMessage(error, language, zh ? '附件上传请求失败' : 'Attachment upload request failed'),
      };
    }
  };

  const handleControlSheetDownload = async (orderId: string, attachmentId: string, filename: string) => {
    try {
      const response = await fetch(
        `/api/change-orders/${encodeURIComponent(orderId)}/attachments/${encodeURIComponent(attachmentId)}`,
        { headers: authHeaders() },
      );
      if (!response.ok) {
        let payload: unknown = {};
        try { payload = await response.json(); } catch { /* use a localized fallback */ }
        const errorPayload = payload && typeof payload === 'object' && !Array.isArray(payload)
          ? payload as Record<string, unknown>
          : {};
        showToast(formatChangeOrderApiMessage(errorPayload.detail ?? errorPayload.message, language, zh ? '附件下载失败' : 'Attachment download failed'), 'error');
        return;
      }
      const objectUrl = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = filename;
      link.style.display = 'none';
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (error) {
      showToast(formatChangeOrderApiMessage(error, language, zh ? '附件下载请求失败' : 'Attachment download request failed'), 'error');
    }
  };

  useEffect(() => {
    if (!orderIdFromQuery || isCreateView) return;
    let cancelled = false;
    const loadLinkedOrder = async () => {
      try {
        const resp = await fetch(`/api/change-orders/${encodeURIComponent(orderIdFromQuery)}`, { headers: authHeaders() });
        const data = await resp.json();
        if (!cancelled && data.success && data.data) {
          setSelectedOrder(data.data);
          fetchTimeline(data.data.id);
        }
      } catch {
        // The list remains usable even if a linked order was removed or unavailable.
      }
    };
    loadLinkedOrder();
    return () => { cancelled = true; };
  }, [authHeaders, fetchTimeline, isCreateView, orderIdFromQuery]);

  // ── Open Edit modal ──
  const openEdit = (order: IChangeOrder) => {
    const templateSnapshot = isCommandTemplateSnapshot(order.command_template) ? order.command_template : null;
    closeDetail();
    setEditingOrder(order);
    const existingCs = order.control_sheet || {};
    const populatedControlSheet = {
      change_time_start: existingCs.change_time?.start || '',
      change_time_end: existingCs.change_time?.end || '',
      implementer_id: existingCs.implementer?.id || '',
      implementer_username: existingCs.implementer?.username || '',
      co_reviewer_id: existingCs.co_reviewer?.id || '',
      co_reviewer_username: existingCs.co_reviewer?.username || '',
      business_confirmer_id: existingCs.business_confirmer?.id || existingCs.business_verifier?.id || existingCs.business_confirmer_id || existingCs.business_verifier_id || '',
      business_confirmer_username: existingCs.business_confirmer?.username || existingCs.business_verifier?.username || existingCs.business_confirmer_username || existingCs.business_verifier_username || '',
      device_ips: Array.isArray(existingCs.device_ips) ? existingCs.device_ips.join('\n') : (existingCs.device_ips || ''),
      pre_check: existingCs.pre_check || '',
      execution: existingCs.execution || '',
      post_verify: existingCs.post_verify || '',
      business_verify: existingCs.business_verify || '',
      rollback_plan: existingCs.rollback_plan || '',
    };
    setForm({
      title: order.title,
      incident_id: order.incident_id || '',
      description: order.description,
      order_type: order.order_type,
      emergency_reason: order.emergency_reason || '',
      emergency_review_owner_id: order.emergency_review_owner_id || '',
      emergency_review_due_at: order.emergency_review_due_at || '',
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
      control_sheet: populatedControlSheet,
    });
    if (templateSnapshot) {
      setCommandMode('template');
      const snapshotScenarioId = String(templateSnapshot.scenario_id || '');
      const asConfigTemplateScenarioId = toConfigTemplateScenarioId(snapshotScenarioId);
      const existsAsScenario = scenarioOptions.some((item) => item.id === snapshotScenarioId);
      const existsAsConfigTemplate = scenarioOptions.some((item) => 
        item.id === asConfigTemplateScenarioId || 
        item.templates?.some(tpl => toConfigTemplateScenarioId(tpl.id) === asConfigTemplateScenarioId)
      );
      const preferredId = existsAsScenario
        ? snapshotScenarioId
        : existsAsConfigTemplate
          ? (scenarioOptions.find((item) => item.id === asConfigTemplateScenarioId || item.templates?.some(tpl => toConfigTemplateScenarioId(tpl.id) === asConfigTemplateScenarioId))?.id || '')
          : scenarioOptions.find((item) => (templateSnapshot.scenario_name && item.name === templateSnapshot.scenario_name) || (templateSnapshot.scenario_name_zh && item.name_zh === templateSnapshot.scenario_name_zh))?.id || '';
      setSelectedScenarioId(preferredId);
      setSelectedScenarioPlatform(String(templateSnapshot.platform || ''));
      setTemplateVariables(Object.fromEntries(
        Object.entries(templateSnapshot.variables || {}).map(([key, value]) => [key, String(value ?? '')]),
      ));
    } else {
      resetTemplateComposer();
    }
    setShowCreateModal(true);
  };

  const initialReviewerOptions = useMemo(() => {
    const implementerId = String(form.control_sheet?.implementer_id || '');
    return getInitialReviewerCandidates(assignmentUsers, String(currentUser.id || ''), implementerId);
  }, [assignmentUsers, currentUser.id, form.control_sheet?.implementer_id]);

  const groupedInitialReviewers = useMemo(() => {
    const map: Record<string, UserOption[]> = {};
    initialReviewerOptions.forEach(u => {
      const q = initialApproverSearch.toLowerCase();
      const matchSearch = !q ||
        u.username.toLowerCase().includes(q) ||
        (u.display_name && u.display_name.toLowerCase().includes(q)) ||
        (u.phone && u.phone.includes(initialApproverSearch)) ||
        (u.role && u.role.toLowerCase().includes(q));
      if (matchSearch) {
        const g = u.group_name || (zh ? '无组别' : 'No Group');
        if (!map[g]) map[g] = [];
        map[g].push(u);
      }
    });
    return map;
  }, [initialReviewerOptions, initialApproverSearch, zh]);

  const finalApproverOptions = useMemo(() => {
    const reqId = selectedOrder?.requester_id;
    const implementerId = selectedOrder ? String(getAssignedImplementer(selectedOrder).id || '') : '';
    return getFinalApproverCandidates(assignmentUsers, String(currentUser.id || ''), String(reqId || ''), implementerId);
  }, [assignmentUsers, currentUser.id, selectedOrder?.requester_id, selectedOrder?.control_sheet]);

  const groupedFinalApprovers = useMemo(() => {
    const map: Record<string, UserOption[]> = {};
    finalApproverOptions.forEach(u => {
      const q = finalApproverSearch.toLowerCase();
      const matchSearch = !q ||
        u.username.toLowerCase().includes(q) ||
        (u.display_name && u.display_name.toLowerCase().includes(q)) ||
        (u.phone && u.phone.includes(finalApproverSearch)) ||
        (u.role && u.role.toLowerCase().includes(q));
      if (matchSearch) {
        const g = u.group_name || (zh ? '无组别' : 'No Group');
        if (!map[g]) map[g] = [];
        map[g].push(u);
      }
    });
    return map;
  }, [finalApproverOptions, finalApproverSearch, zh]);

  const viewMeta: Record<typeof viewTab, { zh: string; en: string; desc_zh: string; desc_en: string }> = {
    all: { zh: '全部变更单', en: 'All change orders', desc_zh: '查看所有变更工单的生命周期', desc_en: 'Browse the full change order lifecycle' },
    my_todo: { zh: '个人待办', en: 'My Todo', desc_zh: '需要你处理的变更工单', desc_en: 'Change orders awaiting your action' },
    group_todo: { zh: '组内待办', en: 'Group Todo', desc_zh: '你所在职责组的待办事项', desc_en: 'Pending items for your duty groups' },
    my_participated: { zh: '我参与的', en: 'My Participated', desc_zh: '曾参与审批或执行的工单', desc_en: 'Orders you have reviewed or executed' },
    my_focus: { zh: '我的关注', en: 'My Focus', desc_zh: '你标记关注的重要工单', desc_en: 'Orders you have bookmarked' },
    my_drafts: { zh: '草稿箱', en: 'Drafts', desc_zh: '尚未提交的工单草稿', desc_en: 'Pending change order drafts' },
  };

  const heroTitle = editorVisible ? (zh ? (editingOrder ? '编辑变更工单' : '新建变更工单') : (editingOrder ? 'Edit change order' : 'New change order')) : (zh ? viewMeta[viewTab].zh : viewMeta[viewTab].en);
  const heroSubtitle = editorVisible ? (zh ? '填写变更范围、机器命令和验证要求，提交后进入审核。' : 'Define the scope, commands and verification requirements before review.') : (zh ? viewMeta[viewTab].desc_zh : viewMeta[viewTab].desc_en);

  const advancedFilterCount = [requesterFilter, assigneeFilter, bookmarkFilter, orderTypeFilter, createdFrom, createdTo, completedFrom, completedTo, scheduledFrom, scheduledTo].filter(Boolean).length;

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <PageHero
        icon={ClipboardList}
        title={heroTitle}
        subtitle={heroSubtitle}
      />
      
      <div className="flex flex-col gap-4 flex-1 min-h-0 overflow-y-auto custom-scrollbar px-4 py-4 sm:px-6 sm:py-5">
        <AnimatePresence>
          {toast && <ToastNotification toast={{ message: toast.msg, type: toast.type }} onClose={() => setToast(null)} />}
        </AnimatePresence>

        {editorVisible ? (
          <ChangeOrderEditor
            language={language}
            currentUser={currentUser}
            users={assignmentUsers}
            platforms={platforms}
            editingOrder={editingOrder}
            form={form}
            setForm={setForm}
            saving={saving}
            handleSave={handleSave}
            handleSaveDraft={handleSaveDraft}
            closeEditor={closeEditor}
            commandMode={commandMode}
            setCommandMode={setCommandMode}
            selectedScenarioId={selectedScenarioId}
            setSelectedScenarioId={setSelectedScenarioId}
            selectedScenarioPlatform={selectedScenarioPlatform}
            setSelectedScenarioPlatform={setSelectedScenarioPlatform}
            templateVariables={templateVariables}
            setTemplateVariables={setTemplateVariables}
            scenarioOptions={scenarioOptions}
            findMatchingPlatform={findMatchingPlatform}
            toConfigTemplateScenarioId={toConfigTemplateScenarioId}
            fromConfigTemplateScenarioId={fromConfigTemplateScenarioId}
            isConfigTemplateScenarioId={isConfigTemplateScenarioId}
            showToast={showToast}
            authHeaders={authHeaders}
          />
        ) : selectedOrder ? (
          <ChangeOrderDetail
            language={language}
            selectedOrder={selectedOrder}
            onCloseDetail={closeDetail}
            detailLoading={detailLoading}
            detailError={detailError}
            retryDetail={() => { if (selectedOrder) void openDetail(selectedOrder); }}
            currentUser={currentUser}
            users={assignmentUsers}
            timeline={timeline}
            timelineLoading={timelineLoading}
            setTimeline={setTimeline}
            bookmarkedIds={bookmarkedIds}
            handleToggleBookmark={handleToggleBookmark}
            handleCopyOrder={handleCopyOrder}
            handleSaveAsTemplate={handleSaveAsTemplate}
            handleExportOrder={handleExportOrder}
            openEdit={openEdit}
            getTransitionActions={(order) => {
              const actions: { label: string; status: string; variant: string; icon: React.ComponentType<any>; disabled?: boolean; disabledReason?: string }[] = [];
              const isRequester = isChangeOrderRequester(order, currentUser);
              const isInitialReviewer = isChangeOrderInitialReviewer(order, currentUser);
              const isFinalApprover = isChangeOrderFinalApprover(order, currentUser);
              const isAdministrator = currentUser.role === 'Administrator';
              const canImplement = canCurrentUserImplement(order, currentUser);
              const executionRequestAlreadySent = sentExecutionRequestKeys.has(executionRequestKey(order)) || hasOrderExecutionRequestBeenSent(order);

              switch (order.status) {
                case 'draft':
                  if (isRequester) {
                    actions.push({ label: zh ? '提交初审' : 'Submit Review', status: 'initial_review', variant: 'primary', icon: Zap });
                  }
                  break;
                case 'initial_review':
                  if (!isRequester && (isInitialReviewer || (isAdministrator && !order.assigned_initial_reviewer_id))) {
                    actions.push({ label: zh ? '初审通过' : 'Pass Initial Review', status: 'final_review', variant: 'success', icon: CheckCircle2 });
                    actions.push({ label: zh ? '驳回' : 'Reject', status: 'rejected', variant: 'danger', icon: XCircle });
                  }
                  break;
                case 'final_review':
                  if (!isRequester && (isFinalApprover || (isAdministrator && !order.assigned_final_approver_id))) {
                    actions.push({ label: zh ? '审批通过' : 'Approve', status: 'approved', variant: 'success', icon: CheckCircle2 });
                    actions.push({ label: zh ? '驳回到初审' : 'Reject to Initial', status: 'initial_review', variant: 'danger', icon: XCircle });
                    actions.push({ label: zh ? '彻底驳回' : 'Reject Completely', status: 'rejected', variant: 'danger', icon: XCircle });
                  }
                  break;
                case 'approved':
                  if (canImplement) {
                    actions.push({ label: zh ? '进入实施' : 'Start Implementing', status: 'implementing', variant: 'primary', icon: Zap });
                  }
                  break;
                case 'implementing':
                case 'executing':
                  if (canImplement) {
                    const readiness = getVerificationReadiness(order);
                    const blockedReason = readiness.missingKinds.length > 0
                      ? (zh
                        ? `完成前需${readiness.missingKinds.map(kind => kind === 'technical' ? '技术验证' : '业务验证').join('、')}通过`
                        : `Complete after ${readiness.missingKinds.join(' and ')} verification passes`)
                      : undefined;
                    actions.push(executionRequestAlreadySent
                      ? {
                        label: zh ? '已请求执行' : 'Request sent',
                        status: 'execute_commands',
                        variant: 'muted',
                        icon: CheckCircle2,
                        disabled: true,
                        disabledReason: zh
                          ? '授权已使用；先核实设备实际状态，需再次执行时重新申请审批'
                          : 'Authorization used. Verify the actual device state first; request a new approval before executing again.',
                      }
                      : { label: zh ? '下发命令' : 'Push Commands', status: 'execute_commands', variant: 'primary', icon: Zap });
                    if (!getResultReviewer(order).id && !getResultReviewer(order).username) actions.push({ label: zh ? '标记完成' : 'Complete', status: 'completed', variant: 'success', icon: CheckCircle2, disabled: !readiness.canComplete, disabledReason: blockedReason });
                    actions.push({ label: zh ? '标记失败' : 'Failed', status: 'failed', variant: 'danger', icon: XCircle });
                    actions.push({ label: zh ? '发起回退' : 'Start Rollback', status: 'rollback_in_progress', variant: 'muted', icon: AlertTriangle });
                  }
                  break;
                case 'failed':
                  if (canImplement) {
                    actions.push({ label: zh ? '发起回退' : 'Rollback', status: 'rollback_in_progress', variant: 'muted', icon: AlertTriangle });
                  }
                  break;
                case 'rollback_in_progress':
                  if (canImplement) {
                    actions.push({ label: zh ? '回退完成' : 'Rollback Completed', status: 'rolled_back', variant: 'success', icon: CheckCircle2 });
                    actions.push({ label: zh ? '回退失败' : 'Rollback Failed', status: 'failed', variant: 'danger', icon: XCircle });
                  }
                  break;
              }
              
              getResultReviewActions(order, currentUser, language).forEach(action => actions.push({
                label: action.label, status: `result_review_${action.action}`, variant: ['fail', 'reject'].includes(action.action) ? 'danger' : 'primary',
                icon: CheckCircle2, disabled: action.disabled, disabledReason: action.disabledReason,
              }));

              if (!['completed', 'cancelled', 'rolled_back', 'implementation_review', 'implementation_result_review'].includes(order.status)) {
                if (isRequester) {
                  actions.push({ label: zh ? '废除' : 'Discard', status: 'cancelled', variant: 'danger', icon: Trash2 });
                } else if (isAdministrator) {
                  actions.push({ label: zh ? '取消' : 'Cancel', status: 'cancelled', variant: 'muted', icon: X });
                }
              }
              return actions;
            }}
            handleTransition={handleTransition}
            handleAssignment={handleAssignment}
            handleVerification={handleVerification}
            handleResultReview={handleResultReview}
            handleEmergencyReview={handleEmergencyReview}
            handleControlSheetUpload={handleControlSheetUpload}
            handleControlSheetDownload={handleControlSheetDownload}
            setExecuteModal={setExecuteModal}
            setActionPrompt={setActionPrompt}
            setFinalApproverPrompt={setFinalApproverPrompt}
            FEATURE_CONTROL_SHEET={FEATURE_CONTROL_SHEET}
            platforms={platforms}
          />
        ) : (
          <ChangeOrderList
            language={language}
            orders={orders}
            total={total}
            summary={summary}
            loading={loading}
            loadError={listError}
            page={page}
            pageSize={pageSize}
            setPage={setPage}
            setPageSize={setPageSize}
            search={search}
            setSearch={setSearch}
            statusFilter={statusFilter}
            setStatusFilter={setStatusFilter}
            priorityFilter={priorityFilter}
            setPriorityFilter={setPriorityFilter}
            requesterFilter={requesterFilter}
            setRequesterFilter={setRequesterFilter}
            assigneeFilter={assigneeFilter}
            setAssigneeFilter={setAssigneeFilter}
            bookmarkFilter={bookmarkFilter}
            setBookmarkFilter={setBookmarkFilter}
            showAdvancedSearch={showAdvancedSearch}
            setShowAdvancedSearch={setShowAdvancedSearch}
            orderTypeFilter={orderTypeFilter}
            setOrderTypeFilter={setOrderTypeFilter}
            createdFrom={createdFrom}
            setCreatedFrom={setCreatedFrom}
            createdTo={createdTo}
            setCreatedTo={setCreatedTo}
            completedFrom={completedFrom}
            setCompletedFrom={setCompletedFrom}
            completedTo={completedTo}
            setCompletedTo={setCompletedTo}
            scheduledFrom={scheduledFrom}
            setScheduledFrom={setScheduledFrom}
            scheduledTo={scheduledTo}
            setScheduledTo={setScheduledTo}
            viewTab={viewTab}
            myTodoSubTab={myTodoSubTab}
            FEATURE_TODO_SUBTABS={false}
            DEFAULT_PAGE_SIZE={DEFAULT_PAGE_SIZE}
            setMyTodoSubTab={setMyTodoSubTab}
            bookmarkedIds={bookmarkedIds}
            openDetail={openDetail}
            openEdit={openEdit}
            handleDelete={handleDelete}
            fetchOrders={fetchOrders}
            fetchSummary={fetchSummary}
            fetchBookmarks={fetchBookmarks}
            users={assignmentUsers}
            currentUser={currentUser}
            advancedFilterCount={advancedFilterCount}
          />
        )}
      </div>

      {/* Execute Modal */}
      {executeModal && (
        <TerminalExecution
          language={language}
          executeModal={executeModal}
          setExecuteModal={setExecuteModal}
          runOrderCommands={runOrderCommands}
        />
      )}

      {actionPrompt && (
        <TicketDialog title={actionPrompt.title} language={language} onClose={() => setActionPrompt(null)} widthClassName="max-w-md" initialFocusSelector={actionPrompt.sensitive ? '#change-order-sensitive-response' : 'textarea'} actions={<>
          <ActionButton onClick={() => setActionPrompt(null)}>{zh ? '取消' : 'Cancel'}</ActionButton>
          <ActionButton variant="primary" disabled={actionPrompt.required && !actionPrompt.value.trim()} onClick={() => { actionPrompt.onConfirm(actionPrompt.value.trim()); setActionPrompt(null); }}>{zh ? '确认提交' : 'Confirm'}</ActionButton>
        </>}>
          {actionPrompt.sensitive ? (
            <PasswordInputField id="change-order-sensitive-response" inputMode="numeric" autoComplete="one-time-code" showPasswordLabel={zh ? '显示验证码' : 'Show verification code'} hidePasswordLabel={zh ? '隐藏验证码' : 'Hide verification code'} aria-label={actionPrompt.placeholder || (zh ? '敏感验证码' : 'Sensitive verification code')} value={actionPrompt.value} onChange={(event) => setActionPrompt({ ...actionPrompt, value: event.target.value.replace(/\D/g, '').slice(0, 8) })} placeholder={actionPrompt.placeholder} maxLength={8} className="tracking-[0.25em]" />
          ) : <textarea rows={4} aria-label={actionPrompt.title} value={actionPrompt.value} onChange={(event) => setActionPrompt({ ...actionPrompt, value: event.target.value })} placeholder={actionPrompt.placeholder} className={`${ticketInputClass} resize-y`} />}
        </TicketDialog>
      )}
      {finalApproverPrompt && <TicketReviewerDialog title={zh ? '请指定终审人' : 'Select Final Approver'} language={language} search={finalApproverSearch} onSearchChange={setFinalApproverSearch} groups={groupedFinalApprovers} selectedId={tempSelectedFinalApprover} onSelect={setTempSelectedFinalApprover} onClose={closeFinalApproverPrompt} emptyMessage={zh ? '没有可选终审人，请在用户管理中将管理员加入“终审组”。' : 'No eligible final approvers. Add an administrator to the final-approver group in User Management.'} onConfirm={() => {
        if (!finalApproverOptions.some((user) => String(user.id) === tempSelectedFinalApprover)) {
          showToast(zh ? '所选终审人已不在终审组，请重新选择。' : 'The selected user is no longer in the final-approver group. Select another user.', 'error');
          setTempSelectedFinalApprover('');
          return;
        }
        finalApproverPrompt.onConfirm(tempSelectedFinalApprover);
        closeFinalApproverPrompt();
      }} />}
      {initialApproverPrompt && <TicketReviewerDialog title={zh ? '请指定初审人' : 'Select Initial Reviewer'} language={language} search={initialApproverSearch} onSearchChange={setInitialApproverSearch} groups={groupedInitialReviewers} selectedId={tempSelectedInitialApprover} onSelect={setTempSelectedInitialApprover} onClose={closeInitialApproverPrompt} emptyMessage={zh ? '没有可选初审人，请在用户管理中将管理员加入“初审组”。' : 'No eligible initial reviewers. Add an administrator to the initial-review group in User Management.'} onConfirm={() => {
        initialApproverPrompt.onConfirm(tempSelectedInitialApprover);
        closeInitialApproverPrompt();
      }} />}

    </div>
  );
};

export default ChangeOrderComponent;
