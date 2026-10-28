import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Activity, AlertTriangle, ArrowUpRight, CheckCircle2, ClipboardList, Clock3, FilePlus2, GitMerge, LoaderCircle, Pencil, Play, Plus, RefreshCw, Search, Send, Trash2, UserPlus, Users, X, XCircle } from 'lucide-react';
import type { SessionUser, User } from '../../types';
import PageHero from '../../components/PageHero';
import Pagination from '../../components/Pagination';
import { TicketDialog, TicketEmptyState, ticketInputClass } from '../../components/tickets/TicketUI';
import { ActionButton, ActionIconButton } from '../../components/ui/ActionIconButton';
import { ListSearchInput } from '../../components/ui/TableListControls';
import { DataTable } from '../../components/DataTable';
import { addTicketAssignmentGroupMember, buildIncidentTicketPath, createServiceRequest, createTicketAssignmentGroup, deleteTicketAssignmentGroup, getIncidentTicketDetail, getServiceCatalog, getServiceRequestDetail, getTicketAssignmentGroupMembers, getTicketAssignmentGroups, linkServiceRequestChangeOrder, listUnifiedTickets, postIncidentTicketAction, postServiceRequestAction, removeTicketAssignmentGroupMember, TicketApiError, updateTicketAssignmentGroup } from './api';
import type { IncidentTicket, IncidentTicketAction, IncidentTicketDetail, ServiceCatalogItem, ServiceRequestAction, ServiceRequestDetail, TicketActionPayload, TicketAssignmentGroup, TicketAssignmentMember, TicketSourceType, UnifiedTicket } from './types';
import ServiceRequestComposer from './ServiceRequestComposer';
import ServiceRequestDetails from './ServiceRequestDetails';
import TicketSlaSummary from './TicketSlaSummary';
import TicketSummaryPanel from './TicketSummaryPanel';
import TicketSlaSettingsPanel from './TicketSlaSettingsPanel';
import ServiceCatalogManager from './ServiceCatalogManager';

const DEFAULT_TICKET_PAGE_SIZE = 10;

interface TicketsPageProps {
  language: string;
  currentUser: SessionUser;
  users?: User[];
  showToast?: (message: string, type?: string) => void;
}

type ActionFormState = {
  assignmentGroupId: string;
  assigneeId: string;
  reason: string;
  summary: string;
  evidence: string;
  targetTicketId: string;
};

const EMPTY_ACTION_FORM: ActionFormState = {
  assignmentGroupId: '',
  assigneeId: '',
  reason: '',
  summary: '',
  evidence: '',
  targetTicketId: '',
};

const statusLabel = (status: string, zh: boolean): string => {
  const labels: Record<string, { zh: string; en: string }> = {
    open: { zh: '待处理', en: 'Open' },
    submitted: { zh: '已提交', en: 'Submitted' },
    pending_approval: { zh: '待审批', en: 'Pending approval' },
    accepted: { zh: '已受理', en: 'Accepted' },
    in_progress: { zh: '处理中', en: 'In progress' },
    waiting_external: { zh: '等待外部资源', en: 'Waiting for external work' },
    pending_confirmation: { zh: '待确认', en: 'Pending confirmation' },
    completed: { zh: '已完成', en: 'Completed' },
    rejected: { zh: '已拒绝', en: 'Rejected' },
    cancelled: { zh: '已取消', en: 'Cancelled' },
    closed: { zh: '已关闭', en: 'Closed' },
    merged: { zh: '已合并', en: 'Merged' },
  };
  return labels[status]?.[zh ? 'zh' : 'en'] || status.replaceAll('_', ' ');
};

const priorityLabel = (priority: string, zh: boolean): string => {
  const labels: Record<string, { zh: string; en: string }> = {
    critical: { zh: '紧急', en: 'Critical' },
    p1: { zh: '紧急', en: 'P1' },
    high: { zh: '高', en: 'High' },
    p2: { zh: '高', en: 'P2' },
    medium: { zh: '中', en: 'Medium' },
    p3: { zh: '中', en: 'P3' },
    low: { zh: '低', en: 'Low' },
    p4: { zh: '低', en: 'P4' },
  };
  return labels[priority.toLowerCase()]?.[zh ? 'zh' : 'en'] || priority;
};

const typeLabel = (ticket: IncidentTicket | UnifiedTicket, zh: boolean): string => {
  const type = String(('source_type' in ticket && ticket.source_type) || ticket.ticket_type || ticket.type || 'incident');
  const labels: Record<string, { zh: string; en: string }> = {
    incident: { zh: '故障', en: 'Incident' },
    service_request: { zh: '服务申请', en: 'Service request' },
    availability: { zh: '可用性故障', en: 'Availability' },
    performance: { zh: '性能故障', en: 'Performance' },
    network: { zh: '网络故障', en: 'Network' },
  };
  return labels[type.toLowerCase()]?.[zh ? 'zh' : 'en'] || type.replaceAll('_', ' ');
};

export const getIncidentTicketNextStep = (ticket: IncidentTicket | UnifiedTicket, zh = true): string => {
  if (zh && 'next_step' in ticket && typeof ticket.next_step === 'string' && ticket.next_step) return ticket.next_step;
  if ('source_type' in ticket && ticket.source_type === 'service_request') {
    const serviceSteps: Record<string, { zh: string; en: string }> = {
      submitted: { zh: '等待受理', en: 'Awaiting triage' },
      pending_approval: { zh: '等待审批', en: 'Awaiting approval' },
      accepted: { zh: '指派或开始受理', en: 'Assign or start fulfillment' },
      in_progress: { zh: '完成交付', en: 'Complete fulfillment' },
      waiting_external: { zh: '等待外部资源', en: 'Waiting for external work' },
      pending_confirmation: { zh: '等待申请人确认', en: 'Awaiting requester confirmation' },
      completed: { zh: '已完成', en: 'Completed' },
      rejected: { zh: '已拒绝', en: 'Rejected' },
      cancelled: { zh: '已取消', en: 'Cancelled' },
    };
    return serviceSteps[ticket.status]?.[zh ? 'zh' : 'en'] || (zh ? '查看申请状态' : 'Review request status');
  }
  if (ticket.status === 'open') {
    if (ticket.assignee_id || ticket.assignee_username) return zh ? '开始处理' : 'Start work';
    return zh ? '指派或认领' : 'Assign or claim';
  }
  if (ticket.status === 'in_progress') return zh ? '恢复后提交确认' : 'Request confirmation after recovery';
  if (ticket.status === 'pending_confirmation') return zh ? '等待确认关闭' : 'Await closure confirmation';
  if (ticket.status === 'closed') return zh ? '已关闭' : 'Closed';
  if (ticket.status === 'cancelled') return zh ? '已取消' : 'Cancelled';
  if (ticket.status === 'merged') return zh ? '已合并' : 'Merged';
  return zh ? '查看工单状态' : 'Review ticket status';
};

const displayTime = (value?: string): string => {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
};

const evidenceText = (value: unknown): string => {
  if (typeof value === 'string') return value;
  if (value == null) return '';
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
};

const ticketMemberId = (member: TicketAssignmentMember): string => member.user_id || member.id || '';

const getTicketPersonAssignee = (ticket: IncidentTicket | UnifiedTicket): string =>
  ticket.assignee_username || (('assignee_id' in ticket && ticket.assignee_id) ? ticket.current_owner_username || '' : '');

const getTicketOwnerDisplay = (ticket: IncidentTicket | UnifiedTicket, unassignedLabel: string): string => {
  const person = getTicketPersonAssignee(ticket);
  if (person) return ticket.assignment_group_name ? `${person} · ${ticket.assignment_group_name}` : person;
  return ticket.assignment_group_name || unassignedLabel;
};

const unifiedTicketSourceId = (ticket: UnifiedTicket): string => {
  const sourceId = typeof ticket.source_id === 'string' ? ticket.source_id.trim() : '';
  if (sourceId) return sourceId;
  return ticket.source_type === 'service_request' && typeof ticket.request_id === 'string' ? ticket.request_id.trim() : '';
};

const incidentEventSummary = (event: IncidentTicketDetail['events'][number], zh: boolean): string => {
  const detailsSummary = event.details?.summary;
  if (typeof detailsSummary === 'string' && detailsSummary.trim()) return detailsSummary;
  if (event.summary?.trim()) return event.summary;
  if (event.message?.trim()) return event.message;
  const eventKey = String(event.action || event.event_type || '').toLowerCase();
  const labels: Record<string, { zh: string; en: string }> = {
    created: { zh: '故障工单已创建', en: 'Incident ticket created' },
    ticket_created: { zh: '故障工单已创建', en: 'Incident ticket created' },
    assigned: { zh: '责任人或责任组已更新', en: 'Ownership updated' },
    claim: { zh: '处理人已认领工单', en: 'Ticket claimed' },
    claimed: { zh: '处理人已认领工单', en: 'Ticket claimed' },
    start: { zh: '开始处理故障', en: 'Response started' },
    started: { zh: '开始处理故障', en: 'Response started' },
    request_confirmation: { zh: '已提交恢复情况，等待确认', en: 'Recovery submitted for confirmation' },
    confirm_close: { zh: '确认关闭故障工单', en: 'Ticket closure confirmed' },
    cancel: { zh: '故障工单已取消', en: 'Ticket cancelled' },
    merge: { zh: '故障工单已合并', en: 'Ticket merged' },
    recurrence: { zh: '故障复发，工单已返回处理中', en: 'Recurrence returned the ticket to active work' },
    reopened: { zh: '故障复发，工单已返回处理中', en: 'Recurrence returned the ticket to active work' },
    monitoring_recovered: { zh: '监控检测到恢复', en: 'Monitoring detected recovery' },
    status_changed: { zh: '工单状态已更新', en: 'Ticket status updated' },
  };
  return labels[eventKey]?.[zh ? 'zh' : 'en'] || (zh ? '工单状态更新' : 'Ticket status updated');
};

const incidentEventEvidence = (event: IncidentTicketDetail['events'][number]): unknown =>
  event.details?.evidence ?? event.evidence ?? event.payload?.evidence;

const isTicketOperator = (user: SessionUser): boolean => ['Administrator', 'Operator'].includes(user.role || '');

const canAct = (ticket: IncidentTicket, action: IncidentTicketAction, user: SessionUser): boolean => {
  if (Array.isArray(ticket.allowed_actions)) return ticket.allowed_actions.includes(action);
  const operator = isTicketOperator(user);
  const usernameMatches = (left?: string, right?: string) => Boolean(left && right && left.toLocaleLowerCase() === right.toLocaleLowerCase());
  const assigned = Boolean((user.id && ticket.assignee_id === user.id) || usernameMatches(ticket.assignee_username || ticket.current_owner_username, user.username));
  const requester = Boolean((user.id && ticket.requester_id === user.id) || usernameMatches(ticket.requester_username, user.username));
  if (action === 'confirm_close') return operator || requester;
  if (action === 'claim' || action === 'assign' || action === 'merge' || action === 'cancel') return operator;
  if (action === 'start' || action === 'request_confirmation') return operator || assigned;
  return false;
};

const actionTitle = (action: IncidentTicketAction, zh: boolean): string => ({
  assign: zh ? '指派处理人' : 'Assign',
  claim: zh ? '认领工单' : 'Claim',
  start: zh ? '开始处理' : 'Start work',
  request_confirmation: zh ? '提交恢复待确认' : 'Request confirmation',
  confirm_close: zh ? '确认关闭' : 'Confirm closure',
  cancel: zh ? '取消工单' : 'Cancel',
  merge: zh ? '合并工单' : 'Merge',
})[action];

const TicketsPage: React.FC<TicketsPageProps> = ({ language, currentUser, users = [], showToast }) => {
  const zh = language === 'zh';
  const location = useLocation();
  const navigate = useNavigate();
  const [tickets, setTickets] = useState<UnifiedTicket[]>([]);
  const [ticketType, setTicketType] = useState<'all' | TicketSourceType>('all');
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_TICKET_PAGE_SIZE);
  const [searchDraft, setSearchDraft] = useState('');
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('all');
  const [myTodo, setMyTodo] = useState(false);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState('');
  const [permissionDenied, setPermissionDenied] = useState(false);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [detail, setDetail] = useState<IncidentTicketDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const [serviceRequestDetail, setServiceRequestDetail] = useState<ServiceRequestDetail | null>(null);
  const [serviceRequestLoading, setServiceRequestLoading] = useState(false);
  const [serviceRequestError, setServiceRequestError] = useState('');
  const [serviceActionLoading, setServiceActionLoading] = useState(false);
  const [serviceActionError, setServiceActionError] = useState('');
  const [serviceCatalog, setServiceCatalog] = useState<ServiceCatalogItem[]>([]);
  const [serviceCatalogLoading, setServiceCatalogLoading] = useState(false);
  const [serviceCatalogError, setServiceCatalogError] = useState('');
  const [serviceComposerOpen, setServiceComposerOpen] = useState(false);
  const [serviceCatalogManagerOpen, setServiceCatalogManagerOpen] = useState(false);
  const [ticketSlaSettingsOpen, setTicketSlaSettingsOpen] = useState(false);
  const [groups, setGroups] = useState<TicketAssignmentGroup[]>([]);
  const [groupsLoading, setGroupsLoading] = useState(false);
  const [activeAction, setActiveAction] = useState<IncidentTicketAction | null>(null);
  const [actionForm, setActionForm] = useState<ActionFormState>(EMPTY_ACTION_FORM);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState('');
  const [assignableMembers, setAssignableMembers] = useState<TicketAssignmentMember[]>([]);
  const [assignmentMembersLoading, setAssignmentMembersLoading] = useState(false);
  const [groupManagerOpen, setGroupManagerOpen] = useState(false);
  const [managerGroupId, setManagerGroupId] = useState('');
  const [managerGroupName, setManagerGroupName] = useState('');
  const [managerGroupDescription, setManagerGroupDescription] = useState('');
  const [managerMembers, setManagerMembers] = useState<TicketAssignmentMember[]>([]);
  const [managerMembersLoading, setManagerMembersLoading] = useState(false);
  const [managerMemberUserId, setManagerMemberUserId] = useState('');
  const [managerBusy, setManagerBusy] = useState(false);
  const [managerError, setManagerError] = useState('');
  const [groupError, setGroupError] = useState('');
  const groupMemberRequestSequence = useRef(0);
  const ticketIdFromQuery = useMemo(() => {
    const params = new URLSearchParams(location.search);
    return params.get('ticket_id') || params.get('request_id') || '';
  }, [location.search]);
  const ticketSourceTypeFromQuery = useMemo(() => {
    const params = new URLSearchParams(location.search);
    return params.get('source_type') || (params.has('request_id') ? 'service_request' : 'incident');
  }, [location.search]);
  const isOperator = isTicketOperator(currentUser);
  const isAdministrator = currentUser.role === 'Administrator';

  const loadList = useCallback(async (signal: AbortSignal) => {
    setLoading(true);
    setListError('');
    setPermissionDenied(false);
    try {
      const response = await listUnifiedTickets({ page, pageSize, status: status === 'all' ? '' : status, search, myTodo, type: ticketType, signal });
      if (!signal.aborted) {
        setTickets(response.items);
        setTotal(response.total);
      }
    } catch (error) {
      if (signal.aborted) return;
      const message = error instanceof Error ? error.message : (zh ? '工单加载失败' : 'Unable to load tickets');
      setListError(message);
      setPermissionDenied(error instanceof TicketApiError && error.status === 403);
      setTickets([]);
      setTotal(0);
    } finally {
      if (!signal.aborted) setLoading(false);
    }
  }, [myTodo, page, pageSize, search, status, ticketType, zh]);

  useEffect(() => {
    const controller = new AbortController();
    void loadList(controller.signal);
    return () => controller.abort();
  }, [loadList, refreshVersion]);

  useEffect(() => {
    const lastPage = Math.max(1, Math.ceil(total / pageSize));
    if (page > lastPage) setPage(lastPage);
  }, [page, pageSize, total]);

  const refreshGroups = useCallback(async () => {
    setGroupsLoading(true);
    try {
      const result = await getTicketAssignmentGroups();
      setGroups(result);
      setGroupError('');
      return result;
    } catch (error) {
      setGroupError(error instanceof Error ? error.message : (zh ? '责任组加载失败' : 'Unable to load assignment groups'));
      return [];
    } finally {
      setGroupsLoading(false);
    }
  }, [zh]);

  useEffect(() => {
    if (!isOperator) return;
    void refreshGroups();
  }, [isOperator, refreshGroups]);

  useEffect(() => {
    if (!groupManagerOpen || !managerGroupId) {
      setManagerMembers([]);
      setManagerMembersLoading(false);
      return;
    }
    let active = true;
    setManagerMembers([]);
    setManagerMembersLoading(true);
    setManagerError('');
    void getTicketAssignmentGroupMembers(managerGroupId).then((result) => {
      if (active) setManagerMembers(result);
    }).catch((error: unknown) => {
      if (active) {
        setManagerMembers([]);
        setManagerError(error instanceof Error ? error.message : (zh ? '组成员加载失败' : 'Unable to load group members'));
      }
    }).finally(() => {
      if (active) setManagerMembersLoading(false);
    });
    return () => { active = false; };
  }, [groupManagerOpen, managerGroupId, zh]);

  useEffect(() => {
    const groupId = activeAction === 'assign' ? actionForm.assignmentGroupId : '';
    const ticketId = activeAction === 'assign' ? detail?.ticket.id || '' : '';
    const requestSequence = ++groupMemberRequestSequence.current;
    setAssignableMembers([]);
    setGroupError('');
    if (!groupId || !ticketId) {
      setAssignmentMembersLoading(false);
      return;
    }

    setAssignmentMembersLoading(true);
    void getTicketAssignmentGroupMembers(groupId, ticketId).then((members) => {
      if (requestSequence === groupMemberRequestSequence.current) setAssignableMembers(members);
    }).catch((error: unknown) => {
      if (requestSequence === groupMemberRequestSequence.current) {
        setGroupError(error instanceof Error ? error.message : (zh ? '责任组成员加载失败' : 'Unable to load group members'));
      }
    }).finally(() => {
      if (requestSequence === groupMemberRequestSequence.current) setAssignmentMembersLoading(false);
    });

    return () => {
      if (requestSequence === groupMemberRequestSequence.current) groupMemberRequestSequence.current += 1;
    };
  }, [actionForm.assignmentGroupId, activeAction, detail?.ticket.id, zh]);

  const openGroupManager = () => {
    const firstGroup = groups[0];
    setManagerGroupId(firstGroup?.id || '');
    setManagerGroupName(firstGroup?.name || '');
    setManagerGroupDescription(firstGroup?.description || '');
    setManagerMemberUserId('');
    setManagerError('');
    setGroupManagerOpen(true);
  };

  const selectManagerGroup = (groupId: string) => {
    const selectedGroup = groups.find((group) => group.id === groupId);
    setManagerGroupId(groupId);
    setManagerGroupName(selectedGroup?.name || '');
    setManagerGroupDescription(selectedGroup?.description || '');
    setManagerError('');
  };

  const startNewGroup = () => {
    setManagerGroupId('');
    setManagerGroupName('');
    setManagerGroupDescription('');
    setManagerMembers([]);
    setManagerMemberUserId('');
    setManagerError('');
  };

  const saveManagerGroup = async (event: React.FormEvent) => {
    event.preventDefault();
    const name = managerGroupName.trim();
    if (!name || managerBusy) {
      if (!name) setManagerError(zh ? '请输入责任组名称。' : 'Enter a group name.');
      return;
    }
    setManagerBusy(true);
    setManagerError('');
    try {
      if (managerGroupId) {
        await updateTicketAssignmentGroup(managerGroupId, { name, description: managerGroupDescription.trim() });
      } else {
        const created = await createTicketAssignmentGroup({ name, description: managerGroupDescription.trim() });
        setManagerGroupId(created.id);
      }
      await refreshGroups();
      showToast?.(zh ? '责任组已保存' : 'Assignment group saved', 'success');
      setGroupManagerOpen(false);
    } catch (error) {
      const message = error instanceof Error ? error.message : (zh ? '责任组保存失败' : 'Unable to save assignment group');
      setManagerError(message);
    } finally {
      setManagerBusy(false);
    }
  };

  const deleteManagerGroup = async () => {
    if (!managerGroupId || managerBusy) return;
    if (!window.confirm(zh ? '删除此责任组？现有工单历史会保留。' : 'Delete this assignment group? Ticket history will remain.')) return;
    setManagerBusy(true);
    setManagerError('');
    try {
      await deleteTicketAssignmentGroup(managerGroupId);
      const nextGroups = await refreshGroups();
      const nextGroup = nextGroups[0];
      setManagerGroupId(nextGroup?.id || '');
      setManagerGroupName(nextGroup?.name || '');
      setManagerGroupDescription(nextGroup?.description || '');
      showToast?.(zh ? '责任组已删除' : 'Assignment group deleted', 'success');
    } catch (error) {
      setManagerError(error instanceof Error ? error.message : (zh ? '责任组删除失败' : 'Unable to delete assignment group'));
    } finally {
      setManagerBusy(false);
    }
  };

  const addManagerMember = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!managerGroupId || !managerMemberUserId || managerBusy) return;
    setManagerBusy(true);
    setManagerError('');
    try {
      await addTicketAssignmentGroupMember(managerGroupId, managerMemberUserId);
      setManagerMemberUserId('');
      const [members] = await Promise.all([
        getTicketAssignmentGroupMembers(managerGroupId),
        refreshGroups(),
      ]);
      setManagerMembers(members);
      showToast?.(zh ? '成员已添加' : 'Member added', 'success');
    } catch (error) {
      setManagerError(error instanceof Error ? error.message : (zh ? '成员添加失败' : 'Unable to add member'));
    } finally {
      setManagerBusy(false);
    }
  };

  const removeManagerMember = async (userId: string) => {
    if (!managerGroupId || managerBusy) return;
    setManagerBusy(true);
    setManagerError('');
    try {
      await removeTicketAssignmentGroupMember(managerGroupId, userId);
      const [members] = await Promise.all([
        getTicketAssignmentGroupMembers(managerGroupId),
        refreshGroups(),
      ]);
      setManagerMembers(members);
      showToast?.(zh ? '成员已移除' : 'Member removed', 'success');
    } catch (error) {
      setManagerError(error instanceof Error ? error.message : (zh ? '成员移除失败' : 'Unable to remove member'));
    } finally {
      setManagerBusy(false);
    }
  };

  const loadDetail = useCallback(async (ticketId: string, signal?: AbortSignal) => {
    setDetailLoading(true);
    setDetailError('');
    setActionError('');
    try {
      const result = await getIncidentTicketDetail(ticketId, signal);
      if (!signal?.aborted) setDetail(result);
    } catch (error) {
      if (!signal?.aborted) {
        setDetail(null);
        setDetailError(error instanceof Error ? error.message : (zh ? '故障工单详情加载失败' : 'Unable to load ticket details'));
      }
    } finally {
      if (!signal?.aborted) setDetailLoading(false);
    }
  }, [zh]);

  const loadServiceRequest = useCallback(async (requestId: string, signal?: AbortSignal) => {
    setServiceRequestLoading(true);
    setServiceRequestError('');
    setServiceActionError('');
    try {
      const result = await getServiceRequestDetail(requestId, signal);
      if (!signal?.aborted) setServiceRequestDetail(result);
    } catch (error) {
      if (!signal?.aborted) {
        setServiceRequestDetail(null);
        setServiceRequestError(error instanceof Error ? error.message : (zh ? '服务申请详情加载失败' : 'Unable to load service request details'));
      }
    } finally {
      if (!signal?.aborted) setServiceRequestLoading(false);
    }
  }, [zh]);

  useEffect(() => {
    if (!ticketIdFromQuery) {
      setDetail(null);
      setServiceRequestDetail(null);
      setDetailError('');
      setServiceRequestError('');
      setActiveAction(null);
      return;
    }
    const controller = new AbortController();
    if (ticketSourceTypeFromQuery === 'service_request') {
      setDetail(null);
      void loadServiceRequest(ticketIdFromQuery, controller.signal);
    } else {
      setServiceRequestDetail(null);
      void loadDetail(ticketIdFromQuery, controller.signal);
    }
    return () => controller.abort();
  }, [loadDetail, loadServiceRequest, ticketIdFromQuery, ticketSourceTypeFromQuery]);

  const openTicket = (sourceType: TicketSourceType, ticketId: string) => navigate(
    !ticketId ? '/tickets' : sourceType === 'incident'
      ? buildIncidentTicketPath(ticketId)
      : `/tickets?source_type=${encodeURIComponent(sourceType)}&request_id=${encodeURIComponent(ticketId)}`,
  );
  const closeDetail = () => navigate('/tickets');

  const loadServiceCatalog = async () => {
    setServiceCatalogLoading(true);
    setServiceCatalogError('');
    setServiceCatalog([]);
    try {
      const items = await getServiceCatalog();
      setServiceCatalog(items.filter((item) => item.active !== false));
    } catch (error) {
      setServiceCatalogError(error instanceof Error ? error.message : (zh ? '服务目录加载失败' : 'Unable to load service catalog'));
    } finally {
      setServiceCatalogLoading(false);
    }
  };

  const openServiceComposer = async () => {
    setServiceComposerOpen(true);
    await loadServiceCatalog();
  };

  const submitServiceRequest = async (draft: { catalog_item_id: string; version: number; title: string; details: Record<string, unknown> }) => {
    try {
      const request = await createServiceRequest(draft);
      setServiceComposerOpen(false);
      setPage(1);
      setTicketType('all');
      setStatus('all');
      setSearch('');
      setSearchDraft('');
      setMyTodo(false);
      setRefreshVersion((value) => value + 1);
      navigate(`/tickets?source_type=service_request&request_id=${encodeURIComponent(request.id)}`);
      showToast?.(zh ? '服务申请已提交' : 'Service request submitted', 'success');
    } catch (error) {
      const message = error instanceof Error ? error.message : (zh ? '提交服务申请失败' : 'Unable to submit service request');
      setServiceCatalogError(message);
    }
  };

  const submitServiceAction = async (action: ServiceRequestAction, payload: TicketActionPayload) => {
    if (!serviceRequestDetail) return;
    setServiceActionLoading(true);
    setServiceActionError('');
    try {
      await postServiceRequestAction(serviceRequestDetail.request.id, action, payload);
      setRefreshVersion((value) => value + 1);
      await loadServiceRequest(serviceRequestDetail.request.id);
      showToast?.(zh ? '服务申请已更新' : 'Service request updated', 'success');
    } catch (error) {
      const message = error instanceof Error ? error.message : (zh ? '服务申请操作失败' : 'Service request action failed');
      setServiceActionError(message);
      showToast?.(message, 'error');
    } finally {
      setServiceActionLoading(false);
    }
  };

  const linkServiceRequestToChangeOrder = async (changeOrderNumber: string) => {
    if (!serviceRequestDetail) return;
    const requestId = serviceRequestDetail.request.id;
    try {
      await linkServiceRequestChangeOrder(requestId, changeOrderNumber);
      await loadServiceRequest(requestId);
      showToast?.(zh ? '变更单已关联' : 'Change order linked', 'success');
    } catch (error) {
      showToast?.(error instanceof Error ? error.message : (zh ? '关联变更单失败' : 'Unable to link change order'), 'error');
      throw error;
    }
  };

  const beginAction = (action: IncidentTicketAction) => {
    setActiveAction(action);
    setActionForm({
      ...EMPTY_ACTION_FORM,
      assignmentGroupId: detail?.ticket.assignment_group_id || '',
      assigneeId: detail?.ticket.assignee_id || '',
    });
    setActionError('');
  };

  const handleAssignmentGroupChange = (groupId: string) => {
    setActionForm((current) => ({ ...current, assignmentGroupId: groupId, assigneeId: '' }));
  };

  const buildActionPayload = (action: IncidentTicketAction): TicketActionPayload | null => {
    const reason = actionForm.reason.trim();
    const summary = actionForm.summary.trim();
    if (action === 'assign') {
      if (!actionForm.assignmentGroupId && !actionForm.assigneeId) return null;
      return {
        ...(actionForm.assignmentGroupId ? { assignment_group_id: actionForm.assignmentGroupId } : {}),
        ...(actionForm.assigneeId ? { assignee_id: actionForm.assigneeId } : {}),
        ...(reason ? { reason } : {}),
      };
    }
    if (action === 'request_confirmation') {
      if (!summary) return null;
      return { summary, ...(actionForm.evidence.trim() ? { evidence: actionForm.evidence.trim() } : {}) };
    }
    if (action === 'confirm_close') return summary ? { summary } : {};
    if (action === 'cancel') return reason ? { reason } : null;
    if (action === 'merge') {
      if (!reason || !actionForm.targetTicketId.trim()) return null;
      return { target_ticket_id: actionForm.targetTicketId.trim(), reason };
    }
    return {};
  };

  const submitAction = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!detail || !activeAction || actionLoading) return;
    const payload = buildActionPayload(activeAction);
    if (!payload) {
      setActionError(zh ? '请补齐该操作所需信息。' : 'Complete the required fields for this action.');
      return;
    }
    if ((activeAction === 'cancel' || activeAction === 'merge') && !window.confirm(zh ? `确认${actionTitle(activeAction, true)}？` : `Confirm ${actionTitle(activeAction, false)}?`)) return;
    setActionLoading(true);
    setActionError('');
    try {
      await postIncidentTicketAction(detail.ticket.id, activeAction, payload);
      setActiveAction(null);
      setActionForm(EMPTY_ACTION_FORM);
      setRefreshVersion((value) => value + 1);
      await loadDetail(detail.ticket.id);
      showToast?.(zh ? `${actionTitle(activeAction, true)}已完成` : `${actionTitle(activeAction, false)} completed`, 'success');
    } catch (error) {
      const message = error instanceof Error ? error.message : (zh ? '故障工单操作失败' : 'Ticket action failed');
      setActionError(message);
      showToast?.(message, 'error');
    } finally {
      setActionLoading(false);
    }
  };

  const recoveryEvidence = evidenceText(detail?.ticket.recovery_evidence ?? detail?.ticket.evidence);
  const ticket = detail?.ticket;
  const currentAssigneeName = ticket
    ? getTicketPersonAssignee(ticket) || ticket.assignment_group_name || (zh ? '未分配' : 'Unassigned')
    : (zh ? '未分配' : 'Unassigned');
  const managerCandidateUsers = users.filter((user) => (!user.status || user.status.toLowerCase() === 'active') && !managerMembers.some((member) => ticketMemberId(member) === user.id));
  const typeFilterOptions = [
    { value: 'all', zh: '全部状态', en: 'All statuses' },
    { value: 'open', zh: '待处理', en: 'Open' },
    { value: 'in_progress', zh: '处理中', en: 'In progress' },
    { value: 'pending_confirmation', zh: '待确认', en: 'Pending confirmation' },
    { value: 'pending_approval', zh: '待审批', en: 'Pending approval' },
    { value: 'accepted', zh: '已受理', en: 'Accepted' },
    { value: 'waiting_external', zh: '等待外部资源', en: 'Waiting for external work' },
    { value: 'completed', zh: '已完成', en: 'Completed' },
    { value: 'rejected', zh: '已拒绝', en: 'Rejected' },
    { value: 'cancelled', zh: '已取消', en: 'Cancelled' },
    { value: 'closed', zh: '已关闭', en: 'Closed' },
  ];

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <PageHero
        icon={ClipboardList}
        title={zh ? '故障与服务工单' : 'Incidents & service requests'}
        subtitle={zh ? '统一跟进故障处置与服务申请。' : 'Track incidents and service requests in one place.'}
        actions={<>
          <ActionButton icon={FilePlus2} variant="primary" onClick={() => void openServiceComposer()}>{zh ? '申请服务' : 'Request service'}</ActionButton>
          {isAdministrator && <ActionButton icon={Pencil} onClick={() => setServiceCatalogManagerOpen(true)}>{zh ? '服务目录' : 'Service catalog'}</ActionButton>}
          {isAdministrator && <ActionButton icon={Clock3} onClick={() => setTicketSlaSettingsOpen(true)}>{zh ? '时限设置' : 'SLA settings'}</ActionButton>}
          {isAdministrator && <ActionButton icon={Users} disabled={groupsLoading} onClick={openGroupManager}>{zh ? '责任组' : 'Groups'}</ActionButton>}
          <ActionIconButton icon={RefreshCw} label={zh ? '刷新' : 'Refresh'} disabled={loading} iconClassName={loading ? 'animate-spin' : ''} onClick={() => setRefreshVersion((value) => value + 1)} />
        </>}
      />

      <div data-testid="tickets-main-scroll" className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto px-4 py-4 sm:px-6 sm:py-5">
        <TicketSummaryPanel language={language} refreshKey={refreshVersion} />
        <section className="shrink-0 overflow-hidden rounded-xl border border-[var(--ui-border)] bg-[var(--ui-surface)] shadow-sm">
          <div className="flex flex-wrap items-center gap-2 border-b border-[var(--ui-border)] px-3 py-2.5 sm:px-4">
            {[{ value: 'all', label: zh ? '全部工单' : 'All tickets' }, { value: 'incident', label: zh ? '故障工单' : 'Incidents' }, { value: 'service_request', label: zh ? '服务申请' : 'Service requests' }].map((option) => <button key={option.value} type="button" aria-pressed={ticketType === option.value} onClick={() => { setPage(1); setTicketType(option.value as 'all' | TicketSourceType); }} className={`min-h-8 rounded-lg px-3 text-xs font-semibold ${ticketType === option.value ? 'bg-[var(--ui-accent)] text-white' : 'text-[var(--ui-fg-muted)] hover:bg-[var(--ui-surface-muted)] hover:text-[var(--ui-fg)]'}`}>{option.label}</button>)}
          </div>
          <form
            className="flex flex-col gap-3 border-b border-[var(--ui-border)] bg-[var(--ui-surface-muted)] p-3 sm:flex-row sm:items-center sm:p-4"
            onSubmit={(event) => { event.preventDefault(); setPage(1); setSearch(searchDraft.trim()); }}
          >
            <ListSearchInput language={language} aria-label={zh ? '搜索工单' : 'Search tickets'} value={searchDraft} onChange={(event) => setSearchDraft(event.target.value)} onClear={() => { setSearchDraft(''); setSearch(''); setPage(1); }} placeholder={zh ? '搜索标题、编号或申请人' : 'Search title, number, or requester'} className="min-w-0 flex-1" />
            <select aria-label={zh ? '按状态筛选工单' : 'Filter tickets by status'} value={status} onChange={(event) => { setPage(1); setStatus(event.target.value); }} className="min-h-9 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 text-xs text-[var(--ui-fg)] outline-none focus-visible:ring-2 focus-visible:ring-[var(--ui-accent)]">
              {typeFilterOptions.map((option) => <option key={option.value} value={option.value}>{zh ? option.zh : option.en}</option>)}
            </select>
            <button type="button" aria-pressed={myTodo} onClick={() => { setPage(1); setMyTodo((value) => !value); }} className={`min-h-9 rounded-lg border px-3 text-xs font-semibold ${myTodo ? 'border-[var(--ui-accent)] bg-[var(--ui-accent)] text-white' : 'border-[var(--ui-border)] bg-[var(--ui-surface)] text-[var(--ui-fg)] hover:bg-[var(--ui-surface-muted)]'}`}>
              {zh ? '我的待办' : 'My to-do'}
            </button>
            <ActionButton type="submit" icon={Search} variant="primary">{zh ? '搜索' : 'Search'}</ActionButton>
            {(search || status !== 'all' || myTodo || ticketType !== 'all') && <ActionButton onClick={() => { setSearchDraft(''); setSearch(''); setStatus('all'); setMyTodo(false); setTicketType('all'); setPage(1); }}>{zh ? '重置' : 'Reset'}</ActionButton>}
          </form>

          {listError && (
            <div role="alert" className={`flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3 text-xs ${permissionDenied ? 'border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100' : 'border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-100'}`}>
              <span className="inline-flex items-center gap-2"><AlertTriangle size={14} />{permissionDenied ? (zh ? '当前账号无权查看这些工单。' : 'This account cannot view these tickets.') : listError}</span>
              <button type="button" onClick={() => setRefreshVersion((value) => value + 1)} className="font-semibold underline underline-offset-2">{zh ? '重试' : 'Retry'}</button>
            </div>
          )}

          <div className="overflow-x-auto">
            <DataTable unstyled className="nx-data-table w-full min-w-[760px] text-left text-[13px]">
              <thead><tr className="border-b border-[var(--ui-border)] bg-[var(--ui-surface-muted)] text-[var(--ui-fg-muted)]">
                <th className="px-4 py-3 font-semibold">{zh ? '标题 / 编号' : 'Title / Number'}</th>
                <th className="px-4 py-3 font-semibold">{zh ? '类型 · 优先级' : 'Type · Priority'}</th>
                <th className="px-4 py-3 font-semibold">{zh ? '状态' : 'Status'}</th>
                <th className="px-4 py-3 font-semibold">{zh ? '当前处理人' : 'Current owner'}</th>
                <th className="px-4 py-3 font-semibold">{zh ? '下一步' : 'Next step'}</th>
                <th className="px-4 py-3 text-right font-semibold">{zh ? '操作' : 'Action'}</th>
              </tr></thead>
              <tbody>
                {loading && tickets.length === 0 && <tr><td colSpan={6} className="px-4 py-12 text-center text-[var(--ui-fg-muted)]"><span role="status" className="inline-flex items-center gap-2"><LoaderCircle size={15} className="animate-spin" />{zh ? '正在加载工单…' : 'Loading tickets…'}</span></td></tr>}
                {!loading && !listError && tickets.length === 0 && <tr><td colSpan={6} ><TicketEmptyState title={zh ? '当前筛选条件下没有工单。' : 'No tickets match these filters.'} description={zh ? '可调整类型、状态或搜索条件，查看其他工单。' : 'Try another ticket type, status, or search term.'} /></td></tr>}
                {tickets.map((item) => (
                  <tr key={`${item.source_type}:${unifiedTicketSourceId(item) || item.ticket_key}`} className="border-b border-[var(--ui-border)] last:border-0 hover:bg-[var(--ui-surface-muted)]">
                    <td className="max-w-[360px] px-4 py-3">
                      <button type="button" onClick={() => openTicket(item.source_type, unifiedTicketSourceId(item))} title={item.title} className="block max-w-full truncate text-left font-semibold text-[var(--ui-fg)] hover:text-[var(--ui-accent)]">{item.title || (zh ? '未命名工单' : 'Untitled ticket')}</button>
                      <span className="mt-0.5 block truncate font-mono text-[11px] text-[var(--ui-fg-muted)]">{item.ticket_key || unifiedTicketSourceId(item) || '—'}</span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-[var(--ui-fg-muted)]">{typeLabel(item, zh)} · {item.priority ? priorityLabel(item.priority, zh) : '—'}</td>
                    <td className="whitespace-nowrap px-4 py-3"><span className={`inline-flex rounded-full px-2 py-1 text-[11px] font-semibold ${['closed', 'completed'].includes(item.status) ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-200' : ['pending_confirmation', 'pending_approval'].includes(item.status) ? 'bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-200' : ['rejected', 'cancelled'].includes(item.status) ? 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200' : 'bg-sky-100 text-sky-800 dark:bg-sky-950/50 dark:text-sky-200'}`}>{statusLabel(item.status, zh)}</span></td>
                    <td className="whitespace-nowrap px-4 py-3 text-[var(--ui-fg)]">{getTicketOwnerDisplay(item, zh ? '未分配' : 'Unassigned')}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-[var(--ui-fg-muted)]">{getIncidentTicketNextStep(item, zh)}</td>
                    <td className="px-4 py-3 text-right"><button type="button" disabled={!unifiedTicketSourceId(item)} onClick={() => openTicket(item.source_type, unifiedTicketSourceId(item))} className="rounded-lg border border-[var(--ui-border)] px-2.5 py-1.5 font-semibold text-[var(--ui-fg)] hover:border-[var(--ui-accent)] hover:text-[var(--ui-accent)] disabled:opacity-50">{zh ? '查看' : 'Open'}</button></td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          </div>
          <Pagination currentPage={page} totalItems={total} onPageChange={setPage} itemsPerPage={pageSize} onItemsPerPageChange={(size) => { setPage(1); setPageSize(size); }} language={language} alwaysVisible itemLabel={zh ? '条工单' : 'tickets'} />
        </section>
      </div>

      {ticketIdFromQuery && ticketSourceTypeFromQuery !== 'service_request' && (
        <TicketDialog title={ticket?.title || (detailLoading ? (zh ? '正在加载工单…' : 'Loading ticket…') : (zh ? '故障工单详情' : 'Incident ticket details'))} description={ticket?.ticket_number || ticket?.ticket_key || ticketIdFromQuery} onClose={closeDetail} closeDisabled={actionLoading} language={language} widthClassName="max-w-5xl" actions={null}>
            <div className="space-y-4">
              {detailLoading && !detail && <p role="status" className="flex items-center justify-center gap-2 py-12 text-sm text-[var(--ui-fg-muted)]"><LoaderCircle size={16} className="animate-spin" />{zh ? '正在加载故障工单详情…' : 'Loading incident ticket details…'}</p>}
              {detailError && <div role="alert" className="mb-4 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-100"><div className="flex items-center justify-between gap-3"><span>{detailError}</span><button type="button" onClick={() => void loadDetail(ticketIdFromQuery)} className="font-semibold underline">{zh ? '重试' : 'Retry'}</button></div></div>}
              {ticket && (
                <div className="grid gap-4 lg:grid-cols-[minmax(0,1.45fr)_minmax(280px,.8fr)]">
                  <div className="space-y-4">
                    <section className="rounded-xl border border-[var(--ui-border)] p-3.5">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="text-xs text-[var(--ui-fg-muted)]">{typeLabel(ticket, zh)} · {ticket.priority ? priorityLabel(ticket.priority, zh) : '—'}</p>
                          <p className="mt-1 text-sm leading-6 text-[var(--ui-fg)]">{ticket.description || (zh ? '暂无故障描述。' : 'No incident description.')}</p>
                        </div>
                        <span className="shrink-0 rounded-full bg-sky-100 px-2.5 py-1 text-[11px] font-semibold text-sky-800 dark:bg-sky-950/50 dark:text-sky-200">{statusLabel(ticket.status, zh)}</span>
                      </div>
                      <div className="mt-3 grid gap-2 border-t border-[var(--ui-border)] pt-3 text-xs sm:grid-cols-2">
                        <div><span className="text-[var(--ui-fg-muted)]">{zh ? '责任组' : 'Assignment group'}</span><p className="mt-0.5 font-semibold text-[var(--ui-fg)]">{ticket.assignment_group_name || (zh ? '未分配' : 'Unassigned')}</p></div>
                        <div><span className="text-[var(--ui-fg-muted)]">{zh ? '当前处理人' : 'Current owner'}</span><p className="mt-0.5 font-semibold text-[var(--ui-fg)]">{currentAssigneeName}</p></div>
                        <div><span className="text-[var(--ui-fg-muted)]">{zh ? '申请人' : 'Requester'}</span><p className="mt-0.5 font-semibold text-[var(--ui-fg)]">{ticket.requester_username || '—'}</p></div>
                        <div><span className="text-[var(--ui-fg-muted)]">{zh ? '最近更新' : 'Updated'}</span><p className="mt-0.5 font-semibold text-[var(--ui-fg)]">{displayTime(ticket.updated_at || ticket.created_at)}</p></div>
                      </div>
                    </section>

                    <TicketSlaSummary sla={ticket.sla} language={language} />

                    <section className="rounded-xl border border-[var(--ui-border)] p-3.5">
                      <h3 className="mb-3 flex items-center gap-2 text-xs font-semibold text-[var(--ui-fg)]"><Activity size={14} className="text-[var(--ui-accent)]" />{zh ? '处置时间线' : 'Response timeline'}</h3>
                      {detail.events.length ? <ol className="space-y-3">{detail.events.map((event, index) => {
                        const evidence = incidentEventEvidence(event);
                        return <li key={event.id || `${event.created_at}-${index}`} className="relative border-l border-[var(--ui-border)] pl-3.5 last:border-transparent">
                          <span className="absolute -left-[4px] top-1 h-1.5 w-1.5 rounded-full bg-[var(--ui-accent)]" />
                          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1"><p className="text-xs font-semibold text-[var(--ui-fg)]">{incidentEventSummary(event, zh)}</p><time className="text-[11px] text-[var(--ui-fg-muted)]">{displayTime(event.created_at)}</time></div>
                          <p className="mt-0.5 text-[11px] text-[var(--ui-fg-muted)]">{event.actor_username || (zh ? '系统' : 'System')}</p>
                          {evidence != null && <pre className="mt-1.5 whitespace-pre-wrap break-words rounded-lg bg-[var(--ui-surface-muted)] p-2 text-[11px] text-[var(--ui-fg-muted)]">{evidenceText(evidence)}</pre>}
                        </li>;
                      })}</ol> : <p className="text-xs text-[var(--ui-fg-muted)]">{zh ? '暂无处置事件。' : 'No response events yet.'}</p>}
                    </section>

                    <section className="rounded-xl border border-[var(--ui-border)] p-3.5">
                      <h3 className="mb-2 text-xs font-semibold text-[var(--ui-fg)]">{zh ? '恢复证据' : 'Recovery evidence'}</h3>
                      {recoveryEvidence ? <pre className="whitespace-pre-wrap break-words rounded-lg bg-[var(--ui-surface-muted)] p-2.5 text-xs text-[var(--ui-fg-muted)]">{recoveryEvidence}</pre> : <p className="text-xs text-[var(--ui-fg-muted)]">{zh ? '尚未提交恢复证据。' : 'No recovery evidence has been submitted.'}</p>}
                    </section>

                    <section className="rounded-xl border border-[var(--ui-border)] p-3.5">
                      <h3 className="mb-2 text-xs font-semibold text-[var(--ui-fg)]">{zh ? '关联变更工单' : 'Linked change orders'}</h3>
                      {detail.linked_change_orders.length ? <div className="space-y-1.5">{detail.linked_change_orders.map((order) => <button key={order.id} type="button" onClick={() => navigate(`/change-orders/all?order_id=${encodeURIComponent(order.id)}`)} className="flex w-full items-center justify-between gap-3 rounded-lg bg-[var(--ui-surface-muted)] px-3 py-2 text-left text-xs hover:bg-[var(--ui-accent-subtle)]"><span className="min-w-0 truncate font-semibold text-[var(--ui-fg)]">{order.order_number || order.id} · {order.title || (zh ? '变更工单' : 'Change order')}</span><span className="shrink-0 text-[11px] text-[var(--ui-fg-muted)]">{order.status || ''}</span></button>)}</div> : <p className="text-xs text-[var(--ui-fg-muted)]">{zh ? '暂无关联变更工单。' : 'No linked change orders.'}</p>}
                      <button type="button" onClick={() => navigate(`/change-orders/new?incident_ticket_id=${encodeURIComponent(ticket.id)}${ticket.incident_id ? `&incident_id=${encodeURIComponent(ticket.incident_id)}` : ''}`)} className="mt-3 inline-flex min-h-8 items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-2.5 text-[11px] font-semibold text-indigo-700 hover:bg-indigo-100 dark:border-indigo-800 dark:bg-indigo-950/30 dark:text-indigo-200"><ArrowUpRight size={13} />{zh ? '从故障工单发起变更' : 'Create a change order'}</button>
                    </section>
                  </div>

                  <aside className="space-y-4">
                    <section className="rounded-xl border border-[var(--ui-border)] p-3.5">
                      <div className="mb-3 flex items-center gap-2"><Users size={14} className="text-[var(--ui-accent)]" /><h3 className="text-xs font-semibold text-[var(--ui-fg)]">{zh ? '处理动作' : 'Actions'}</h3></div>
                      {!isOperator && !canAct(ticket, 'confirm_close', currentUser) && <p className="mb-3 rounded-lg bg-amber-50 px-2.5 py-2 text-[11px] text-amber-800 dark:bg-amber-950/30 dark:text-amber-100">{zh ? '当前账号仅可查看此工单。' : 'This account can view this ticket but cannot change it.'}</p>}
                      <div className="flex flex-wrap gap-2">
                        {ticket.status === 'open' && canAct(ticket, 'claim', currentUser) && <button type="button" onClick={() => beginAction('claim')} className="inline-flex min-h-8 items-center gap-1.5 rounded-lg border border-sky-200 bg-sky-50 px-2.5 text-[11px] font-semibold text-sky-700 hover:bg-sky-100"><UserPlus size={13} />{zh ? '认领' : 'Claim'}</button>}
                        {ticket.status !== 'closed' && ticket.status !== 'cancelled' && ticket.status !== 'merged' && canAct(ticket, 'assign', currentUser) && <button type="button" onClick={() => beginAction('assign')} className="inline-flex min-h-8 items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-2.5 text-[11px] font-semibold text-indigo-700 hover:bg-indigo-100"><Users size={13} />{zh ? '指派' : 'Assign'}</button>}
                        {ticket.status === 'open' && canAct(ticket, 'start', currentUser) && <button type="button" onClick={() => beginAction('start')} className="inline-flex min-h-8 items-center gap-1.5 rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 text-[11px] font-semibold text-emerald-700 hover:bg-emerald-100"><Play size={13} />{zh ? '开始处理' : 'Start work'}</button>}
                        {ticket.status === 'in_progress' && canAct(ticket, 'request_confirmation', currentUser) && <button type="button" onClick={() => beginAction('request_confirmation')} className="inline-flex min-h-8 items-center gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-2.5 text-[11px] font-semibold text-amber-800 hover:bg-amber-100"><Send size={13} />{zh ? '提交恢复待确认' : 'Request confirmation'}</button>}
                        {ticket.status === 'pending_confirmation' && canAct(ticket, 'confirm_close', currentUser) && <button type="button" onClick={() => beginAction('confirm_close')} className="inline-flex min-h-8 items-center gap-1.5 rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 text-[11px] font-semibold text-emerald-700 hover:bg-emerald-100"><CheckCircle2 size={13} />{zh ? '确认关闭' : 'Confirm close'}</button>}
                        {!['closed', 'cancelled', 'merged'].includes(ticket.status) && canAct(ticket, 'cancel', currentUser) && <button type="button" onClick={() => beginAction('cancel')} className="inline-flex min-h-8 items-center gap-1.5 rounded-lg border border-rose-200 bg-rose-50 px-2.5 text-[11px] font-semibold text-rose-700 hover:bg-rose-100"><XCircle size={13} />{zh ? '取消' : 'Cancel'}</button>}
                        {!['closed', 'cancelled', 'merged'].includes(ticket.status) && canAct(ticket, 'merge', currentUser) && <button type="button" onClick={() => beginAction('merge')} className="inline-flex min-h-8 items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-2.5 text-[11px] font-semibold text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"><GitMerge size={13} />{zh ? '合并' : 'Merge'}</button>}
                      </div>

                      {activeAction && (
                        <form onSubmit={submitAction} className="mt-3 space-y-2.5 border-t border-[var(--ui-border)] pt-3">
                          <p className="text-xs font-semibold text-[var(--ui-fg)]">{actionTitle(activeAction, zh)}</p>
                          {activeAction === 'assign' && <>
                            <label className="block text-[11px] text-[var(--ui-fg-muted)]">{zh ? '责任组' : 'Assignment group'}<select aria-label={zh ? '责任组' : 'Assignment group'} value={actionForm.assignmentGroupId} onChange={(event) => handleAssignmentGroupChange(event.target.value)} className="mt-1 min-h-9 w-full rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2.5 text-xs text-[var(--ui-fg)]"><option value="">{zh ? '先选择责任组' : 'Select a group first'}</option>{groups.filter((group) => group.active !== false).map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}</select></label>
                            <label className="block text-[11px] text-[var(--ui-fg-muted)]">{zh ? '组内处理人' : 'Group member'}<select aria-label={zh ? '组内处理人' : 'Group member'} disabled={!actionForm.assignmentGroupId || assignmentMembersLoading} value={actionForm.assigneeId} onChange={(event) => setActionForm((current) => ({ ...current, assigneeId: event.target.value }))} className="mt-1 min-h-9 w-full rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2.5 text-xs text-[var(--ui-fg)] disabled:opacity-60"><option value="">{assignmentMembersLoading ? (zh ? '正在加载组成员…' : 'Loading group members…') : (zh ? '选择该组成员' : 'Select a group member')}</option>{assignableMembers.map((member) => { const memberId = ticketMemberId(member); return memberId ? <option key={memberId} value={memberId}>{member.display_name || member.username}</option> : null; })}</select></label>
                            {groupError && <p className="text-[11px] text-amber-700">{groupError}</p>}
                            {!assignmentMembersLoading && actionForm.assignmentGroupId && assignableMembers.length === 0 && !groupError && <p className="text-[11px] text-[var(--ui-fg-muted)]">{zh ? '该责任组暂无可指派成员。' : 'No assignable members in this group.'}</p>}
                          </>}
                          {(activeAction === 'assign' || activeAction === 'cancel' || activeAction === 'merge') && <label className="block text-[11px] text-[var(--ui-fg-muted)]">{zh ? '原因' : 'Reason'}<textarea value={actionForm.reason} onChange={(event) => setActionForm((current) => ({ ...current, reason: event.target.value }))} rows={2} className="mt-1 w-full rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2.5 py-2 text-xs text-[var(--ui-fg)] outline-none focus-visible:ring-2 focus-visible:ring-[var(--ui-accent)]" /></label>}
                          {(activeAction === 'request_confirmation' || activeAction === 'confirm_close') && <label className="block text-[11px] text-[var(--ui-fg-muted)]">{zh ? '处理摘要' : 'Summary'}<textarea required={activeAction === 'request_confirmation'} value={actionForm.summary} onChange={(event) => setActionForm((current) => ({ ...current, summary: event.target.value }))} rows={3} className="mt-1 w-full rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2.5 py-2 text-xs text-[var(--ui-fg)] outline-none focus-visible:ring-2 focus-visible:ring-[var(--ui-accent)]" /></label>}
                          {activeAction === 'request_confirmation' && <label className="block text-[11px] text-[var(--ui-fg-muted)]">{zh ? '恢复证据' : 'Recovery evidence'}<textarea value={actionForm.evidence} onChange={(event) => setActionForm((current) => ({ ...current, evidence: event.target.value }))} rows={3} className="mt-1 w-full rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2.5 py-2 text-xs text-[var(--ui-fg)] outline-none focus-visible:ring-2 focus-visible:ring-[var(--ui-accent)]" /></label>}
                          {activeAction === 'merge' && <label className="block text-[11px] text-[var(--ui-fg-muted)]">{zh ? '目标故障单 ID' : 'Target ticket ID'}<input value={actionForm.targetTicketId} onChange={(event) => setActionForm((current) => ({ ...current, targetTicketId: event.target.value }))} className="mt-1 min-h-9 w-full rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2.5 text-xs text-[var(--ui-fg)] outline-none focus-visible:ring-2 focus-visible:ring-[var(--ui-accent)]" /></label>}
                          {actionError && <p role="alert" className="text-xs text-rose-700 dark:text-rose-300">{actionError}</p>}
                          <div className="flex justify-end gap-2"><button type="button" onClick={() => { setActiveAction(null); setActionError(''); }} className="min-h-8 rounded-lg border border-[var(--ui-border)] px-2.5 text-[11px] font-semibold text-[var(--ui-fg-muted)]">{zh ? '返回' : 'Back'}</button><button type="submit" disabled={actionLoading} className="inline-flex min-h-8 items-center gap-1.5 rounded-lg bg-[var(--ui-accent)] px-3 text-[11px] font-semibold text-white disabled:opacity-50">{actionLoading && <LoaderCircle size={12} className="animate-spin" />}{zh ? '提交' : 'Submit'}</button></div>
                        </form>
                      )}
                    </section>
                    {ticket.status === 'pending_confirmation' && <p className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-[11px] text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100"><AlertTriangle size={14} className="mt-0.5 shrink-0" />{zh ? '监控恢复只作为证据；需要确认后才会关闭工单。若故障复发，工单会回到处理中。' : 'Monitoring recovery is evidence only. Close after confirmation; recurrence returns the ticket to active work.'}</p>}
                  </aside>
                </div>
              )}
            </div>
        </TicketDialog>
      )}

      {ticketIdFromQuery && ticketSourceTypeFromQuery === 'service_request' && <ServiceRequestDetails
        detail={serviceRequestDetail}
        loading={serviceRequestLoading}
        error={serviceRequestError}
        groups={groups}
        actionLoading={serviceActionLoading}
        actionError={serviceActionError}
        onClose={closeDetail}
        onRetry={() => void loadServiceRequest(ticketIdFromQuery)}
        onAction={submitServiceAction}
        onLinkChangeOrder={linkServiceRequestToChangeOrder}
        language={language}
      />}

      <ServiceRequestComposer
        open={serviceComposerOpen}
        catalogs={serviceCatalog}
        loading={serviceCatalogLoading}
        error={serviceCatalogError}
        onClose={() => { setServiceComposerOpen(false); setServiceCatalogError(''); }}
        onSubmit={submitServiceRequest}
        language={language}
      />

      <ServiceCatalogManager
        open={serviceCatalogManagerOpen && isAdministrator}
        groups={groups}
        onClose={() => setServiceCatalogManagerOpen(false)}
        onSaved={() => { void loadServiceCatalog(); }}
        language={language}
      />

      <TicketSlaSettingsPanel
        open={ticketSlaSettingsOpen && isAdministrator}
        onClose={() => setTicketSlaSettingsOpen(false)}
        language={language}
      />

      {groupManagerOpen && isAdministrator && (
        <TicketDialog title={zh ? '责任组管理' : 'Assignment groups'} description={zh ? '维护责任组信息及组内成员。' : 'Maintain assignment groups and their members.'} onClose={() => setGroupManagerOpen(false)} closeDisabled={managerBusy} language={language} widthClassName="max-w-3xl" actions={<>
          <ActionButton icon={Trash2} variant="danger" className="mr-auto" disabled={!managerGroupId || managerBusy} onClick={() => void deleteManagerGroup()}>{zh ? '删除组' : 'Delete group'}</ActionButton>
          <ActionButton disabled={managerBusy} onClick={() => setGroupManagerOpen(false)}>{zh ? '关闭' : 'Close'}</ActionButton>
          <ActionButton type="submit" form="ticket-assignment-group-form" variant="primary" disabled={managerBusy} icon={managerBusy ? LoaderCircle : Pencil} iconClassName={managerBusy ? 'animate-spin' : ''}>{managerGroupId ? (zh ? '保存修改' : 'Save changes') : (zh ? '创建责任组' : 'Create group')}</ActionButton>
        </>}>
          <div className="grid gap-6 md:grid-cols-2">
            <div className="space-y-4">
              <div className="flex items-end gap-2">
                <label className="min-w-0 flex-1 text-xs font-medium text-[var(--ui-fg-muted)]">{zh ? '选择责任组' : 'Select a group'}<select aria-label={zh ? '选择责任组' : 'Select a group'} value={managerGroupId} onChange={(event) => selectManagerGroup(event.target.value)} className={`${ticketInputClass} mt-1.5`}><option value="">{zh ? '新建责任组' : 'New assignment group'}</option>{groups.map((group) => <option key={group.id} value={group.id}>{group.name}{group.active === false ? (zh ? '（停用）' : ' (inactive)') : ''}</option>)}</select></label>
                <ActionButton icon={Plus} onClick={startNewGroup}>{zh ? '新建' : 'New'}</ActionButton>
              </div>
              <form id="ticket-assignment-group-form" onSubmit={saveManagerGroup} className="space-y-4">
                <label className="block text-xs font-medium text-[var(--ui-fg-muted)]">{zh ? '组名' : 'Group name'}<input required value={managerGroupName} onChange={(event) => setManagerGroupName(event.target.value)} className={`${ticketInputClass} mt-1.5`} /></label>
                <label className="block text-xs font-medium text-[var(--ui-fg-muted)]">{zh ? '说明' : 'Description'}<textarea value={managerGroupDescription} onChange={(event) => setManagerGroupDescription(event.target.value)} rows={4} className={`${ticketInputClass} mt-1.5 resize-y`} /></label>
              </form>
            </div>
            <section className="min-w-0 border-t border-[var(--ui-border)] pt-4 md:border-l md:border-t-0 md:pl-6 md:pt-0">
              <div className="mb-3 flex items-center justify-between gap-3"><h3 className="text-sm font-semibold text-[var(--ui-fg)]">{zh ? '组成员' : 'Group members'}</h3>{managerGroupId && <span className="rounded-md bg-[var(--ui-surface-muted)] px-2 py-1 text-xs text-[var(--ui-fg-muted)]">{managerMembers.length}</span>}</div>
              {!managerGroupId ? <p className="rounded-lg bg-[var(--ui-surface-muted)] px-3 py-6 text-center text-xs leading-5 text-[var(--ui-fg-muted)]">{zh ? '先创建或选择责任组，再添加成员。' : 'Create or select a group before adding members.'}</p> : <>
                <form onSubmit={addManagerMember} className="mb-3 flex gap-2">
                  <label className="sr-only" htmlFor="ticket-group-add-member">{zh ? '添加成员' : 'Add member'}</label>
                  <select id="ticket-group-add-member" aria-label={zh ? '添加成员' : 'Add member'} value={managerMemberUserId} onChange={(event) => setManagerMemberUserId(event.target.value)} className={`${ticketInputClass} min-w-0 flex-1`}><option value="">{zh ? '选择用户' : 'Select user'}</option>{managerCandidateUsers.map((user) => <option key={user.id} value={user.id}>{user.display_name || user.username}</option>)}</select>
                  <ActionButton type="submit" icon={Plus} disabled={!managerMemberUserId || managerBusy}>{zh ? '添加' : 'Add'}</ActionButton>
                </form>
                {managerMembersLoading ? <p role="status" className="py-5 text-center text-xs text-[var(--ui-fg-muted)]">{zh ? '正在加载组成员…' : 'Loading group members…'}</p> : managerMembers.length ? <ul className="max-h-64 divide-y divide-[var(--ui-border)] overflow-y-auto">{managerMembers.map((member, index) => { const userId = ticketMemberId(member); return <li key={userId || member.username || index} className="flex items-center justify-between gap-3 py-2.5"><span className="min-w-0 truncate text-[13px] font-medium text-[var(--ui-fg)]">{member.display_name || member.username}{member.display_name && member.display_name !== member.username && <span className="ml-2 text-xs font-normal text-[var(--ui-fg-muted)]">{member.username}</span>}</span><ActionIconButton icon={X} variant="danger" disabled={!userId || managerBusy} label={`${zh ? '移除成员' : 'Remove member'} ${member.username}`} onClick={() => void removeManagerMember(userId)} /></li>; })}</ul> : <p className="py-5 text-center text-xs text-[var(--ui-fg-muted)]">{zh ? '此责任组尚无成员。' : 'This group has no members yet.'}</p>}
              </>}
              {managerError && <p role="alert" className="mt-3 rounded-lg bg-[var(--ui-danger-subtle)] px-3 py-2 text-xs text-[var(--ui-danger)]">{managerError}</p>}
            </section>
          </div>
        </TicketDialog>
      )}
    </div>
  );
};

export default TicketsPage;
