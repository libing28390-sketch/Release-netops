import React, { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { AnimatePresence, motion } from 'motion/react';
import {
  CalendarClock, Plus, X, Trash2, RotateCcw, Zap, Pencil,
  ChevronDown, Info, Shield, CheckCircle2, AlertTriangle,
  Database, Activity, Power, PowerOff, RefreshCw,
  Search, Eye, Target, FileText, Lock, ChevronUp, Filter, ShieldAlert, User, Layers, Settings2, Terminal
} from 'lucide-react';
import { ActionIconButton } from '../../components/ui/ActionIconButton';
import { TableActionCell, TableActionHeader } from '../../components/ui/TableActionColumn';
import { useEscapeClose } from '../../hooks/useEscapeClose';

import Pagination from '../../components/Pagination';
import { DataTable } from '../../components/DataTable';
import PageHero from '../../components/PageHero';
import { hasTagFilterConditions, parseTagFilter, type TagFilterConfig, EMPTY_TAG_FILTER, serializeTagFilter } from '../../components/TagConditionPicker';
import { ColumnSettingsButton, ListSearchInput, ListToolbar, TableHeaderMultiSelectFilter } from '../../components/ui/TableListControls';
import { loadVisibleColumnKeys, saveVisibleColumnKeys, type ColumnPreferenceDefinition } from '../../components/ui/columnPreferences';

import { ScheduledJob, EligibleApprover, SystemScheduledJob, FormState, ValidatedDevice, ScheduledJobsTabProps, type ApprovalVerificationMethod, type CollectionPlanFilters, type NsotCollectionPreview } from './types';
import { INITIAL_FORM, ACTION_TYPES, MAJOR_CATEGORIES } from './constants';
import { describeCron, describeScope } from './helpers';

import { CandidateModal } from './components/CandidateModal';
import CountdownText from './components/CountdownText';
import { DeleteApprovalModal } from './components/DeleteApprovalModal';
import { JobDetailModal } from './components/JobDetailModal';
import { JobModal } from './components/JobModal';
import { BulkCollectionPlanModal } from './components/BulkCollectionPlanModal';

type ScheduledJobOperation = 'CREATE' | 'UPDATE' | 'ENABLE' | 'DISABLE' | 'DELETE';

interface ScheduledJobOperationManifest {
  operation: ScheduledJobOperation;
  job_id: string;
  job_type: 'cron' | 'once';
  name: string;
  action: string;
  scope: { type: string; filter: string };
  cron_expr: string;
  scheduled_at: string;
  check_items: string[];
  commands: string;
  script_id: string;
  is_config: 0 | 1;
  use_admin_creds: 0 | 1;
  enabled: boolean;
  config_reason: string;
}

const SCHEDULED_JOB_COLUMN_STORAGE_KEY = 'netops:scheduled-jobs:columns:v1';
const SCHEDULED_JOB_COLUMN_DEFS: readonly ColumnPreferenceDefinition<'name' | 'target' | 'schedule' | 'status' | 'updatedBy' | 'updatedAt' | 'actions'>[] = [
  { key: 'name', defaultVisible: true },
  { key: 'target', defaultVisible: true },
  { key: 'schedule', defaultVisible: true },
  { key: 'status', defaultVisible: true },
  { key: 'updatedBy', defaultVisible: false },
  { key: 'updatedAt', defaultVisible: true },
  { key: 'actions', defaultVisible: true, required: true, isAction: true },
];

const formatJobDateTime = (value?: string | null): string => {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  const pad = (part: number) => String(part).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
};

const ScheduledJobsTab: React.FC<ScheduledJobsTabProps> = ({ language, showToast }) => {
  const zh = language === 'zh';
  const navigate = useNavigate();
  const location = useLocation();

  /* === STATE === */
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const jobsRequestSequence = useRef(0);
  const [systemJobs, setSystemJobs] = useState<SystemScheduledJob[]>([]);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [total, setTotal] = useState(0);
  const [jobActionCounts, setJobActionCounts] = useState<Record<string, number>>({});
  const [visibleJobColumnKeys, setVisibleJobColumnKeys] = useState(() => loadVisibleColumnKeys(SCHEDULED_JOB_COLUMN_STORAGE_KEY, SCHEDULED_JOB_COLUMN_DEFS));
  const [jobStatusFilters, setJobStatusFilters] = useState<string[]>([]);
  const visibleJobColumnSet = useMemo(() => new Set<string>(visibleJobColumnKeys), [visibleJobColumnKeys]);

  // Modal
  const [showAddJob, setShowAddJob] = useState(false);
  const [bulkCollectionPlanOpen, setBulkCollectionPlanOpen] = useState(false);
  const [detailJob, setDetailJob] = useState<ScheduledJob | null>(null);
  const [editingJob, setEditingJob] = useState<ScheduledJob | null>(null);
  const [presetOpen, setPresetOpen] = useState(false);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  useEscapeClose(Boolean(deleteConfirmId), () => setDeleteConfirmId(null));

  // Form
  const [form, setForm] = useState<FormState>({ ...INITIAL_FORM });
  const [tagFilter, setTagFilter] = useState<TagFilterConfig>({ ...EMPTY_TAG_FILTER });

  // IP validation state
  const [ipDevices, setIpDevices] = useState<ValidatedDevice[]>([]);
  const [ipInput, setIpInput] = useState('');
  const [ipValidating, setIpValidating] = useState(false);
  const [ipError, setIpError] = useState('');

  // Candidate IP / Device Selection modal
  const [candidateModalOpen, setCandidateModalOpen] = useState(false);
  const [candidateList, setCandidateList] = useState<Array<{ ip: string; hostname: string; tags: any[]; selected: boolean }>>([]);
  const [candidateSearching, setCandidateSearching] = useState(false);

  // Approval (create & update)
  const [approvers, setApprovers] = useState<EligibleApprover[]>([]);
  const [approverLoadStatus, setApproverLoadStatus] = useState<'idle' | 'loading' | 'loaded' | 'error'>('idle');
  const [approverUsername, setApproverUsername] = useState('');
  const [approvalMethod, setApprovalMethod] = useState<ApprovalVerificationMethod>('mfa');
  const [approvalToken, setApprovalToken] = useState('');
  const [approvalCode, setApprovalCode] = useState('');
  const [approvalStatus, setApprovalStatus] = useState<'idle' | 'sending' | 'sent' | 'verifying' | 'verified'>('idle');
  const [approvalCountdown, setApprovalCountdown] = useState(0);
  const [approvalDeadline, setApprovalDeadline] = useState(0);
  const [approvalError, setApprovalError] = useState('');
  const [approvalManifest, setApprovalManifest] = useState<ScheduledJobOperationManifest | null>(null);
  const [disableTarget, setDisableTarget] = useState<ScheduledJob | null>(null);
  const [disableOperation, setDisableOperation] = useState<'ENABLE' | 'DISABLE'>('DISABLE');
  const [disableReason, setDisableReason] = useState('');
  const [disableSubmitting, setDisableSubmitting] = useState(false);

  // Delete approval state
  const [deleteApprovalOpen, setDeleteApprovalOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<ScheduledJob | null>(null);
  const [deleteReason, setDeleteReason] = useState('');
  const [deleteApprover, setDeleteApprover] = useState('');
  const [deleteApprovalMethod, setDeleteApprovalMethod] = useState<ApprovalVerificationMethod>('mfa');
  const [deleteToken, setDeleteToken] = useState('');
  const [deleteCode, setDeleteCode] = useState('');
  const [deleteStatus, setDeleteStatus] = useState<'idle' | 'sending' | 'sent' | 'verifying' | 'verified'>('idle');
  const [deleteCountdown, setDeleteCountdown] = useState(0);
  const [deleteDeadline, setDeleteDeadline] = useState(0);
  const [deleteError, setDeleteError] = useState('');
  const [deleteApprovalManifest, setDeleteApprovalManifest] = useState<ScheduledJobOperationManifest | null>(null);
  const approvalVerifyInFlightRef = useRef(false);
  const deleteVerifyInFlightRef = useRef(false);
  const routedEditJobIdRef = useRef('');
  const openEditModalRef = useRef<(job: ScheduledJob) => void>(() => {});
  const showToastRef = useRef(showToast);
  const zhRef = useRef(zh);

  const expireApprovalCountdown = useCallback(() => {
    setApprovalCountdown(0);
    setApprovalDeadline(0);
  }, []);
  const expireDeleteCountdown = useCallback(() => {
    setDeleteCountdown(0);
    setDeleteDeadline(0);
  }, []);

  // Enabling job tracker
  const [enablingJobId, setEnablingJobId] = useState<string | null>(null);

  // Script selection
  const [availableScripts, setAvailableScripts] = useState<{ id: string; name: string; status: string; category: string; platform?: string }[]>([]);
  const [scriptSearch, setScriptSearch] = useState('');
  const [showScriptDropdown, setShowScriptDropdown] = useState(false);

  const isEditMode = editingJob !== null;

  // Category & Filter state
  const [activeCategory, setActiveCategory] = useState<'all' | 'system' | 'backup' | 'nsot' | 'inspection' | 'command' | 'script_run'>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [appliedSearch, setAppliedSearch] = useState('');
  // Keep platform schedules out of the way of user-created jobs by default.
  // Selecting the dedicated system category expands the small curated list.
  const [systemCollapsed, setSystemCollapsed] = useState(true);

  const filteredJobs = jobs;

  const filteredSystemJobs = useMemo(() => {
    return systemJobs.filter(sj => {
      const q = searchQuery.trim().toLowerCase();
      const name = (zh ? sj.name_zh : sj.name_en).toLowerCase();
      const desc = (zh ? sj.description_zh : sj.description_en).toLowerCase();
      return !q || name.includes(q) || desc.includes(q);
    });
  }, [systemJobs, searchQuery, zh]);

  const exportSystemJobs = () => {
    return {
      headers: [
        zh ? '任务名称' : 'Job Name',
        zh ? '任务说明' : 'Description',
        zh ? '触发发条 (CRON)' : 'Trigger',
        zh ? '预计下次执行' : 'Next Run',
      ],
      rows: filteredSystemJobs.map((job) => [
        zh ? job.name_zh : job.name_en,
        zh ? job.description_zh : job.description_en,
        job.trigger || 'CRON Daemon',
        job.next_run_at
          ? new Date(job.next_run_at).toLocaleString(zh ? 'zh-CN' : 'en-US', {
              hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
            })
          : '',
      ]),
    };
  };

  const stats = useMemo(() => {
    const countFor = (actionType: string) => jobActionCounts[actionType] ?? jobs.filter(j => j.action_type === actionType).length;
    const backupCnt = countFor('backup');
    const nsotCnt = countFor('nsot');
    const inspCnt = countFor('inspection');
    const commandCnt = countFor('command');
    const scriptCnt = countFor('script_run');
    const activeCnt = jobs.filter(j => j.enabled === 1).length;
    return { backupCnt, nsotCnt, inspCnt, commandCnt, scriptCnt, activeCnt };
  }, [jobs, jobActionCounts]);

  const authHeaders = useMemo(() => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' };
  }, []);

  useEffect(() => {
    saveVisibleColumnKeys(SCHEDULED_JOB_COLUMN_STORAGE_KEY, SCHEDULED_JOB_COLUMN_DEFS, visibleJobColumnKeys);
  }, [visibleJobColumnKeys]);

  /* === FETCHERS === */
  const fetchJobs = useCallback(async () => {
    const requestSequence = ++jobsRequestSequence.current;
    setLoading(true);
    try {
      const params = new URLSearchParams({ job_type: 'cron', page: String(page), page_size: String(pageSize) });
      const keyword = appliedSearch.trim();
      if (keyword) params.set('keyword', keyword);
      if (activeCategory !== 'all' && activeCategory !== 'system') params.set('action_type', activeCategory);
      if (jobStatusFilters.length === 1) params.set('enabled', jobStatusFilters[0] === 'enabled' ? '1' : '0');
      const r = await fetch(`/api/scheduled-jobs?${params.toString()}`, { headers: authHeaders });
      if (r.ok && requestSequence === jobsRequestSequence.current) {
        const j = await r.json();
        const d = j.data || {};
        setJobs(d.items || []);
        setTotal(d.total || 0);
        setJobActionCounts(d.action_counts && typeof d.action_counts === 'object' ? d.action_counts : {});
      }
    } finally {
      if (requestSequence === jobsRequestSequence.current) setLoading(false);
    }
  }, [authHeaders, page, pageSize, appliedSearch, activeCategory, jobStatusFilters]);

  const fetchNsotCollectionPreview = useCallback(async (jobId: string, signal: AbortSignal): Promise<NsotCollectionPreview> => {
    const response = await fetch(`/api/scheduled-jobs/${encodeURIComponent(jobId)}/nsot-preview`, {
      headers: authHeaders,
      signal,
    });
    const payload = await response.json().catch(() => null) as {
      data?: NsotCollectionPreview;
      detail?: string;
      message?: string;
    } | null;
    if (!response.ok) {
      throw new Error(payload?.detail || payload?.message || (zh ? '无法加载 NSOT 采集预览。' : 'Unable to load the NSOT collection preview.'));
    }
    if (!payload?.data || !Array.isArray(payload.data.groups)) {
      throw new Error(zh ? '服务器返回的 NSOT 预览格式无法识别。' : 'The server returned an invalid NSOT preview.');
    }
    return payload.data;
  }, [authHeaders, zh]);

  const fetchSystemJobs = useCallback(async () => {
    try {
      const r = await fetch('/api/scheduled-jobs/system', { headers: authHeaders });
      if (r.ok) {
        const j = await r.json();
        const items = Array.isArray(j) ? j : (j?.data?.items || (Array.isArray(j?.data) ? j.data : []));
        setSystemJobs(items);
      }
    } catch {
      // Silently skip
    }
  }, [authHeaders]);

  const fetchApprovers = useCallback(async () => {
    setApproverLoadStatus('loading');
    try {
      const r = await fetch('/api/config-approval/approvers', { headers: authHeaders });
      if (!r.ok) throw new Error('Approver request failed');
      const j = await r.json();
      const users = Array.isArray(j) ? j : j?.data;
      if (!Array.isArray(users)) throw new Error('Approver response is invalid');
      setApprovers(users);
      setApproverLoadStatus('loaded');
    } catch {
      setApproverLoadStatus('error');
    }
  }, [authHeaders]);

  const fetchCronPreview = useCallback(async (cronExpr: string, signal: AbortSignal): Promise<string[]> => {
    const response = await fetch('/api/scheduled-jobs/cron-preview', {
      method: 'POST',
      headers: authHeaders,
      signal,
      body: JSON.stringify({ cron_expr: cronExpr }),
    });
    const payload = await response.json().catch(() => null) as {
      success?: boolean;
      data?: { occurrences?: unknown };
      detail?: string;
      message?: string;
    } | null;
    if (!response.ok || !payload || payload.success !== true) {
      const message = response.status === 401
        ? (zh ? '登录状态已失效，请重新登录后查看执行时间。' : 'Your session has expired. Sign in again to preview execution times.')
        : response.status === 403
          ? (zh ? '当前账号没有预览定时作业的权限。' : 'You do not have permission to preview this schedule.')
          : payload?.detail || payload?.message || (zh ? '无法预览执行时间。' : 'Unable to preview execution times.');
      throw Object.assign(new Error(message), { status: response.status });
    }
    const occurrences = payload.data?.occurrences;
    if (!Array.isArray(occurrences) || occurrences.some(value => typeof value !== 'string')) {
      throw new Error(zh ? '服务器返回的执行时间格式无效。' : 'The server returned invalid execution times.');
    }
    return occurrences.slice(0, 10);
  }, [authHeaders, zh]);

  const [devices, setDevices] = useState<any[]>([]);
  const [deviceLoadStatus, setDeviceLoadStatus] = useState<'idle' | 'loading' | 'loaded' | 'error'>('idle');

  const fetchDevices = useCallback(async () => {
    const pageSize = 500;
    const allDevices: any[] = [];
    let page = 1;
    let total: number | null = null;
    setDeviceLoadStatus('loading');
    try {
      while (true) {
        const r = await fetch(`/api/devices?mode=light&page=${page}&page_size=${pageSize}`, { headers: authHeaders });
        if (!r.ok) throw new Error('Device request failed');
        const j = await r.json();
        const payload = Array.isArray(j) ? j : (j?.data ?? j);
        const items = Array.isArray(payload) ? payload : payload?.items;
        if (!Array.isArray(items)) throw new Error('Device response is invalid');
        allDevices.push(...items);

        const responseTotal = Number(payload?.total);
        if (Number.isFinite(responseTotal) && responseTotal >= 0) total = responseTotal;
        if (items.length === 0 || (total !== null && allDevices.length >= total) || (total === null && items.length < pageSize)) {
          break;
        }
        page += 1;
      }
      setDevices(allDevices);
      setDeviceLoadStatus('loaded');
    } catch {
      setDeviceLoadStatus('error');
    }
  }, [authHeaders]);

  const fetchScripts = useCallback(async () => {
    try {
      const r = await fetch('/api/scripts', { headers: authHeaders });
      if (r.ok) {
        const j = await r.json();
        const data = j.data?.items || j.data || j;
        const list = Array.isArray(data) ? data : [];
        setAvailableScripts(list.filter((s: any) => s.status === 'released'));
      }
    } catch { /* ignore */ }
  }, [authHeaders]);

  useEffect(() => { fetchJobs(); }, [fetchJobs]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setPage(1);
      setAppliedSearch(searchQuery.trim());
    }, 250);
    return () => window.clearTimeout(timer);
  }, [searchQuery]);
  useEffect(() => { fetchSystemJobs(); }, [fetchSystemJobs]);
  useEffect(() => {
    if (showAddJob || editingJob) fetchDevices();
  }, [showAddJob, editingJob, fetchDevices]);
  useEffect(() => {
    if (showAddJob || disableTarget?.id) fetchApprovers();
  }, [showAddJob, disableTarget?.id, fetchApprovers]);
  useEffect(() => {
    const needsScripts = editingJob?.action_type === 'script_run'
      || editingJob?.action_type === 'inspection'
      || detailJob?.action_type === 'script_run'
      || detailJob?.action_type === 'inspection';
    if ((showAddJob || detailJob?.id) && needsScripts) fetchScripts();
  }, [showAddJob, editingJob?.id, editingJob?.action_type, detailJob?.id, detailJob?.action_type, fetchScripts]);

  /* === MODAL HELPERS === */
  const resetApprovalFlow = () => {
    setApprovalToken('');
    setApprovalCode('');
    setApprovalStatus('idle');
    setApprovalCountdown(0);
    setApprovalDeadline(0);
    setApprovalError('');
    setApprovalManifest(null);
  };

  const resetDeleteApprovalFlow = () => {
    setDeleteToken('');
    setDeleteCode('');
    setDeleteStatus('idle');
    setDeleteCountdown(0);
    setDeleteDeadline(0);
    setDeleteError('');
    setDeleteApprovalManifest(null);
  };

  const selectApprover = (username: string) => {
    setApproverUsername(username);
    const methods = approvers.find(item => item.username === username)?.verification_methods || [];
    setApprovalMethod(methods.includes(approvalMethod) ? approvalMethod : (methods[0] || 'mfa'));
    resetApprovalFlow();
  };

  const selectDeleteApprover = (username: string) => {
    setDeleteApprover(username);
    const methods = approvers.find(item => item.username === username)?.verification_methods || [];
    setDeleteApprovalMethod(methods.includes(deleteApprovalMethod) ? deleteApprovalMethod : (methods[0] || 'mfa'));
    resetDeleteApprovalFlow();
  };

  const changeApprovalMethod = (method: ApprovalVerificationMethod) => {
    setApprovalMethod(method);
    resetApprovalFlow();
  };

  const changeDeleteApprovalMethod = (method: ApprovalVerificationMethod) => {
    setDeleteApprovalMethod(method);
    resetDeleteApprovalFlow();
  };

  const resetFormState = () => {
    setForm({ ...INITIAL_FORM });
    setTagFilter({ ...EMPTY_TAG_FILTER });
    setIpDevices([]);
    setIpInput('');
    setScriptSearch('');
    setShowScriptDropdown(false);
    setApproverUsername('');
    setApprovalMethod('mfa');
    resetApprovalFlow();
  };

  const toggleAddJob = () => {
    if (showAddJob) {
      if (approvalStatus === 'sending' || approvalStatus === 'verifying') return;
      setShowAddJob(false);
      setEditingJob(null);
      setEnablingJobId(null);
    } else {
      resetFormState();
      setEditingJob(null);
      setShowAddJob(true);
    }
  };

  const openScheduledJobForCollectionScope = (filters: CollectionPlanFilters) => {
    const serializedFilters = JSON.stringify(filters);
    resetFormState();
    setForm({
      ...INITIAL_FORM,
      name: zh ? 'NSOT 范围周期采集' : 'NSOT scoped collection',
      action_type: 'nsot',
      device_scope: 'composite',
      device_filter: serializedFilters,
      major_type: 'collection',
    });
    setEditingJob(null);
    setEnablingJobId(null);
    setPresetOpen(false);
    setBulkCollectionPlanOpen(false);
    setShowAddJob(true);
  };

  const openEditModal = (job: ScheduledJob) => {
    if (job.authorization_mode === 'system') {
      showToast(zh ? '系统内置作业由平台托管，此处仅可查看。' : 'This built-in job is platform-managed and can only be viewed here.', 'info');
      return;
    }
    setEditingJob(job);
    setForm({
      name: job.name,
      action_type: job.action_type,
      cron_expr: job.cron_expr,
      device_scope: job.device_scope,
      device_filter: job.device_filter,
      commands: job.commands || '',
      script_id: job.script_id || '',
      is_config: !!job.is_config,
      config_reason: job.config_reason || '',
      use_admin_creds: !!job.use_admin_creds,
      major_type: (job.action_type === 'backup' || job.action_type === 'nsot' || job.action_type === 'inspection') ? 'collection' : 'change',
    });
    if (job.device_scope === 'tag') {
      setTagFilter(parseTagFilter(job.device_filter));
    } else {
      setTagFilter({ ...EMPTY_TAG_FILTER });
    }
    // Populate validated IP chips
    if (job.device_scope === 'ip' && job.device_filter) {
      const ips = job.device_filter.split(/[,\n;]+/).map(s => s.trim()).filter(Boolean);
      setIpDevices(ips.map(ip => ({ ip, hostname: '', tags: [] })));
      ips.forEach(ipAddr => {
        fetch(`/api/devices?search=${encodeURIComponent(ipAddr)}&mode=light&page_size=10`, { headers: authHeaders })
          .then(r => r.ok ? r.json() : null)
          .then(j => {
            if (!j) return;
            const items = j.data?.items || j.data || [];
            const device = items.find((d: { ip_address: string }) => d.ip_address === ipAddr);
            if (device) {
              setIpDevices(prev => prev.map(d => d.ip === ipAddr ? {
                ...d,
                hostname: device.hostname || '',
                tags: (device.tags || []).map((t: { id: string; label: string; label_zh: string; color: string }) => ({
                  id: t.id, label: t.label, label_zh: t.label_zh, color: t.color || '#94a3b8',
                })),
              } : d));
            }
          })
          .catch(() => {});
      });
    } else {
      setIpDevices([]);
    }
    setIpInput('');
    setApproverUsername('');
    setApprovalMethod('mfa');
    resetApprovalFlow();
    setShowAddJob(true);
  };

  useEffect(() => {
    openEditModalRef.current = openEditModal;
    showToastRef.current = showToast;
    zhRef.current = zh;
  });

  useEffect(() => {
    const jobId = new URLSearchParams(location.search).get('edit_id') || '';
    if (!jobId || routedEditJobIdRef.current === jobId) return;
    routedEditJobIdRef.current = jobId;
    let active = true;

    const openRoutedEdit = async () => {
      try {
        const response = await fetch(`/api/scheduled-jobs/${encodeURIComponent(jobId)}`, { headers: authHeaders });
        const payload = await response.json().catch(() => null) as { data?: ScheduledJob; detail?: string; message?: string } | null;
        if (!response.ok || !payload?.data) {
          throw new Error(payload?.detail || payload?.message || (zhRef.current ? '无法读取该定时作业。' : 'Unable to load this scheduled job.'));
        }
        if (active) openEditModalRef.current(payload.data);
      } catch (cause) {
        if (active) {
          showToastRef.current(cause instanceof Error ? cause.message : (zhRef.current ? '打开编辑窗口失败' : 'Unable to open the editor'), 'error');
        }
      } finally {
        if (active) {
          const params = new URLSearchParams(location.search);
          params.delete('edit_id');
          navigate({ pathname: location.pathname, search: params.toString() ? `?${params.toString()}` : '' }, { replace: true });
        }
        routedEditJobIdRef.current = '';
      }
    };

    void openRoutedEdit();
    return () => { active = false; };
  }, [authHeaders, location.pathname, location.search, navigate]);

  const closeModal = () => {
    setShowAddJob(false);
    setEditingJob(null);
    setEnablingJobId(null);
    setPresetOpen(false);
  };

  /* === APPROVAL (create & update) === */
  const requestApproval = async () => {
    if (!disableTarget && editingJob?.authorization_mode === 'system') {
      showToast(zh ? '系统内置作业由平台托管，此处仅可查看。' : 'This built-in job is platform-managed and can only be viewed here.', 'info');
      return;
    }
    if (!approverUsername || approvalStatus === 'sending' || approvalStatus === 'verifying' || approvalStatus === 'verified') return;
    if (approvalStatus === 'sent' && approvalCountdown > 0) return;
    // 在发送验证码前先校验必填项,避免半填状态下的无效审批流
    if (!disableTarget) {
      const err = validateForm();
      if (err) { showToast(err, 'error'); return; }
    }
    const operation = disableTarget ? disableOperation : (isEditMode ? 'UPDATE' : 'CREATE');
    const operationManifest = disableTarget
      ? buildJobOperationManifest(operation, disableTarget)
      : buildFormOperationManifest(isEditMode ? 'UPDATE' : 'CREATE');
    const approvalType = disableTarget?.job_type === 'once' || (!disableTarget && isEditMode && editingJob?.job_type === 'once')
      ? 'execution_plan'
      : 'scheduled_job';
    setApprovalStatus('sending');
    setApprovalCode('');
    setApprovalError('');
    try {
      const actionLabel = ACTION_TYPES.find(a => a.value === operationManifest.action);
      const r = await fetch('/api/config-approval/request', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({
          approver_username: approverUsername,
          config_reason: disableTarget
            ? (disableReason.trim() || `${zh ? (operation === 'ENABLE' ? '启用定时作业' : '停用定时作业') : (operation === 'ENABLE' ? 'Enable scheduled job' : 'Disable scheduled job')}: ${operationManifest.name}`)
            : (operationManifest.config_reason || `${zh ? (isEditMode ? '修改定时作业' : '创建定时作业') : (isEditMode ? 'Update job' : 'Create job')}: ${operationManifest.name}`),
          device_hostname: operationManifest.scope.type === 'all' ? (zh ? '全部设备' : 'All devices') : operationManifest.scope.filter,
          command_preview: '',
          approval_type: approvalType,
          verification_method: approvalMethod,
          operation_manifest: operationManifest,
          extra_fields: {
            action_type: zh ? (actionLabel?.labelZh || operationManifest.action) : (actionLabel?.labelEn || operationManifest.action),
            schedule_desc: describeCron(operationManifest.cron_expr, zh),
            operation,
          },
        }),
      });
      const j = await r.json();
      if (r.ok && j.success) {
        setApprovalToken(j.approval_token);
        setApprovalManifest(operationManifest);
        setApprovalStatus('sent');
        setApprovalCountdown(300);
        setApprovalDeadline(Date.now() + 300_000);
        const message = approvalMethod === 'mfa'
          ? (zh ? '请输入审批人 MFA 验证器中的动态码' : 'Enter the approver’s authenticator code')
          : approvalMethod === 'email'
          ? (zh ? '邮箱验证码已发送至审批人' : 'Email code sent to approver')
          : (zh ? '飞书验证码已发送至审批人' : 'Feishu code sent to approver');
        showToast(message, 'success');
      } else {
        setApprovalStatus('idle');
        setApprovalError(j.detail || j.message || 'Failed');
      }
    } catch {
      setApprovalStatus('idle');
      setApprovalError(zh ? '发送验证码失败' : 'Failed to send code');
    }
  };

  const verifyApproval = async (code = approvalCode) => {
    if (approvalVerifyInFlightRef.current || approvalStatus !== 'sent' || !approvalToken || code.length !== 6 || !approvalManifest) return;
    approvalVerifyInFlightRef.current = true;
    const approvalType = disableTarget?.job_type === 'once' || (!disableTarget && isEditMode && editingJob?.job_type === 'once')
      ? 'execution_plan'
      : 'scheduled_job';
    setApprovalStatus('verifying');
    setApprovalError('');
    try {
      const r = await fetch('/api/config-approval/verify', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({ approval_token: approvalToken, code, approval_type: approvalType, operation_manifest: approvalManifest }),
      });
      const j = await r.json();
      if (r.ok && j.success) {
        setApprovalStatus('verified');
        setApprovalCountdown(0);
        setApprovalDeadline(0);
        showToast(zh ? '审批验证通过' : 'Approval verified', 'success');
      } else {
        setApprovalStatus('sent');
        setApprovalError(j.detail || j.message || 'Invalid code');
      }
    } catch {
      setApprovalStatus('sent');
      setApprovalError(zh ? '验证失败' : 'Verification failed');
    } finally {
      approvalVerifyInFlightRef.current = false;
    }
  };

  /* === APPROVAL (delete) === */
  const requestDeleteApproval = async () => {
    if (!deleteApprover || !deleteTarget || deleteStatus === 'sending' || deleteStatus === 'verifying' || deleteStatus === 'verified') return;
    if (deleteStatus === 'sent' && deleteCountdown > 0) return;
    const deleteApprovalType = deleteTarget.job_type === 'once' ? 'execution_plan' : 'scheduled_job_delete';
    const operationManifest = buildJobOperationManifest('DELETE', deleteTarget);
    setDeleteStatus('sending');
    setDeleteCode('');
    setDeleteError('');
    try {
      const r = await fetch('/api/config-approval/request', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({
          approver_username: deleteApprover,
          config_reason: deleteReason || `${zh ? '删除定时作业' : 'Delete scheduled job'}: ${deleteTarget.name}`,
          device_hostname: deleteTarget.device_scope === 'all' ? (zh ? '全部设备' : 'All devices') : deleteTarget.device_filter,
          command_preview: '',
          approval_type: deleteApprovalType,
          verification_method: deleteApprovalMethod,
          operation_manifest: operationManifest,
          extra_fields: { action_type: 'DELETE', job_name: deleteTarget.name },
        }),
      });
      const j = await r.json();
      if (r.ok && j.success) {
        setDeleteToken(j.approval_token);
        setDeleteApprovalManifest(operationManifest);
        setDeleteStatus('sent');
        setDeleteCountdown(300);
        setDeleteDeadline(Date.now() + 300_000);
        const message = deleteApprovalMethod === 'mfa'
          ? (zh ? '请输入审批人 MFA 验证器中的动态码' : 'Enter the approver’s authenticator code')
          : deleteApprovalMethod === 'email'
          ? (zh ? '删除审批邮箱验证码已发送' : 'Delete approval email sent')
          : (zh ? '删除审批飞书验证码已发送' : 'Delete approval code sent to Feishu');
        showToast(message, 'success');
      } else {
        setDeleteStatus('idle');
        setDeleteError(j.detail || j.message || 'Failed');
      }
    } catch {
      setDeleteStatus('idle');
      setDeleteError(zh ? '发送验证码失败' : 'Failed to send code');
    }
  };

  const verifyDeleteApproval = async (code = deleteCode) => {
    if (deleteVerifyInFlightRef.current || deleteStatus !== 'sent' || !deleteToken || code.length !== 6 || !deleteTarget || !deleteApprovalManifest) return;
    deleteVerifyInFlightRef.current = true;
    const deleteApprovalType = deleteTarget.job_type === 'once' ? 'execution_plan' : 'scheduled_job_delete';
    setDeleteStatus('verifying');
    setDeleteError('');
    try {
      const r = await fetch('/api/config-approval/verify', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({ approval_token: deleteToken, code, approval_type: deleteApprovalType, operation_manifest: deleteApprovalManifest }),
      });
      const j = await r.json();
      if (r.ok && j.success) {
        setDeleteStatus('verified');
        setDeleteCountdown(0);
        setDeleteDeadline(0);
        showToast(zh ? '删除审批验证通过' : 'Delete approval verified', 'success');
      } else {
        setDeleteStatus('sent');
        setDeleteError(j.detail || j.message || 'Invalid code');
      }
    } catch {
      setDeleteStatus('sent');
      setDeleteError(zh ? '验证失败' : 'Verification failed');
    } finally {
      deleteVerifyInFlightRef.current = false;
    }
  };

  const executeDeleteJob = async () => {
    if (!deleteTarget || deleteStatus !== 'verified') return;
    const operationManifest = buildJobOperationManifest('DELETE', deleteTarget);
    if (!sameManifest(deleteApprovalManifest, operationManifest)) {
      resetDeleteApprovalFlow();
      setDeleteError(zh ? '作业信息已变化，请重新申请删除审批。' : 'The job details changed. Request delete approval again.');
      return;
    }
    try {
      const url = `/api/scheduled-jobs/${deleteTarget.id}?approval_token=${encodeURIComponent(deleteToken)}&approval_code=${encodeURIComponent(deleteCode)}`;
      const r = await fetch(url, {
        method: 'DELETE',
        headers: authHeaders,
        body: JSON.stringify({ operation_manifest: operationManifest }),
      });
      const j = await r.json();
      if (r.ok && j.success) {
        setDeleteApprovalOpen(false);
        setDeleteTarget(null);
        fetchJobs();
        showToast(zh ? '定时作业已删除' : 'Job successfully deleted', 'success');
      } else {
        setDeleteError(j.detail || j.message || 'Deletion failed');
      }
    } catch {
      setDeleteError(zh ? '删除请求操作失败' : 'Deletion failed');
    }
  };

  /* === Candidate IP search === */
  const validateAndAddIps = async (raw: string) => {
    const queries = raw.split(/[,;\s]+/).map(s => s.trim()).filter(Boolean);
    if (queries.length === 0) return;
    setIpError('');
    setIpValidating(true);
    setCandidateSearching(true);

    const candidatesMap: Record<string, { ip: string; hostname: string; tags: any[]; selected: boolean }> = {};

    try {
      for (const query of queries) {
        let found = false;
        const r = await fetch(`/api/devices?search=${encodeURIComponent(query)}&mode=light&page_size=50`, { headers: authHeaders });
        if (r.ok) {
          const j = await r.json();
          const items = Array.isArray(j) ? j : (j.items || j.data?.items || j.data || []);
          if (items.length > 0) {
            found = true;
            for (const dev of items) {
              const ip = dev.ip_address;
              if (ip && !ipDevices.some(existing => existing.ip === ip)) {
                candidatesMap[ip] = {
                  ip,
                  hostname: dev.hostname || '',
                  tags: (dev.tags || []).map((t: any) => ({
                    id: t.id, label: t.label, label_zh: t.label_zh, color: t.color || '#94a3b8',
                  })),
                  selected: false,
                };
              }
            }
          }
        }

        if (!found) {
          try {
            const ar = await fetch(`/api/assets?q=${encodeURIComponent(query)}&page_size=50`, { headers: authHeaders });
            if (ar.ok) {
              const aj = await ar.json();
              const assets = Array.isArray(aj) ? aj : (aj.items || aj.data?.items || aj.data || []);
              if (assets.length > 0) {
                found = true;
                for (const a of assets) {
                  const ip = a.management_ip || a.business_ip || query;
                  if (ip && !ipDevices.some(existing => existing.ip === ip)) {
                    candidatesMap[ip] = candidatesMap[ip] || {
                      ip,
                      hostname: a.hostname || '',
                      tags: [],
                      selected: false,
                    };
                  }
                }
              }
            }
          } catch { /* ignore */ }
        }

        if (!found && !ipDevices.some(existing => existing.ip === query)) {
          candidatesMap[query] = candidatesMap[query] || {
            ip: query,
            hostname: '',
            tags: [],
            selected: false,
          };
        }
      }

      const candidateArray = Object.values(candidatesMap);
      if (candidateArray.length > 0) {
        setCandidateList(candidateArray);
        setCandidateModalOpen(true);
      } else {
        setIpError(zh ? '输入的 IP 或查询目标已全部添加或无匹配结果' : 'All queried IPs are already added or no results');
      }
    } catch {
      setIpError(zh ? '查询设备失败' : 'Device lookup failed');
    } finally {
      setIpValidating(false);
      setCandidateSearching(false);
    }
  };

  const confirmAddCandidates = () => {
    const selectedCandidates = candidateList.filter(c => c.selected);
    if (selectedCandidates.length === 0) return;

    setIpDevices(prev => {
      const next = [...prev];
      for (const c of selectedCandidates) {
        if (!next.some(existing => existing.ip === c.ip)) {
          next.push({
            ip: c.ip,
            hostname: c.hostname,
            tags: c.tags,
          });
        }
      }
      return next;
    });
    setIpInput('');
    setCandidateModalOpen(false);
    setCandidateList([]);
  };

  const toggleCandidateSelected = (idx: number) => {
    setCandidateList(prev => prev.map((c, i) => i === idx ? { ...c, selected: !c.selected } : c));
  };

  const toggleAllCandidates = () => {
    const allSel = candidateList.length > 0 && candidateList.every(c => c.selected);
    setCandidateList(prev => prev.map(c => ({ ...c, selected: !allSel })));
  };

  const removeIpDevice = (ip: string) => {
    setIpDevices(prev => prev.filter(d => d.ip !== ip));
  };

  /* === CRUD === */
  const resolveFilter = (): string => {
    if (form.device_scope === 'tag') return serializeTagFilter(tagFilter);
    if (form.device_scope === 'ip') return ipDevices.map(d => d.ip).join(',');
    return form.device_filter;
  };

  const buildFormOperationManifest = (operation: 'CREATE' | 'UPDATE'): ScheduledJobOperationManifest => {
    const action = form.action_type.trim();
    const isNsot = action === 'nsot';
    const jobType: 'cron' | 'once' = operation === 'CREATE' ? 'cron' : editingJob?.job_type === 'once' ? 'once' : 'cron';
    const checkItems: string[] = [];
    const commands = isNsot ? '' : form.commands;
    return {
      operation,
      job_id: editingJob?.id || '',
      job_type: jobType,
      name: form.name.trim(),
      action,
      scope: { type: form.device_scope.trim(), filter: resolveFilter().trim() },
      cron_expr: jobType === 'once' ? String(editingJob?.cron_expr || '').trim() : form.cron_expr.trim(),
      scheduled_at: jobType === 'once' ? String(editingJob?.scheduled_at || '').trim() : '',
      check_items: checkItems,
      commands,
      script_id: isNsot ? '' : form.script_id.trim(),
      is_config: !isNsot && form.is_config ? 1 : 0,
      use_admin_creds: !isNsot && form.use_admin_creds ? 1 : 0,
      enabled: !editingJob || Number(editingJob.enabled) === 1,
      config_reason: form.config_reason.trim(),
    };
  };

  const buildJobOperationManifest = (
    operation: ScheduledJobOperation,
    job: ScheduledJob,
  ): ScheduledJobOperationManifest => {
    const action = String(job.action_type || '');
    const currentItems = (job as ScheduledJob & { check_items?: string[] }).check_items;
    const checkItems = action === 'inspection'
      ? (Array.isArray(currentItems) ? currentItems.map(item => String(item).trim()).filter(Boolean) : [])
      : [];
    const commands = action === 'inspection' && checkItems.length > 0
      ? checkItems.join(',')
      : String(job.commands || '');
    return {
      operation,
      job_id: String(job.id),
      job_type: job.job_type === 'once' ? 'once' : 'cron',
      name: String(job.name || ''),
      action,
      scope: {
        type: String(job.device_scope || ''),
        filter: String(job.device_filter || ''),
      },
      cron_expr: String(job.cron_expr || ''),
      scheduled_at: String(job.scheduled_at || ''),
      check_items: checkItems,
      commands,
      script_id: String(job.script_id || ''),
      is_config: Number(job.is_config) === 1 ? 1 : 0,
      use_admin_creds: Number(job.use_admin_creds) === 1 ? 1 : 0,
      enabled: operation === 'ENABLE' ? true : operation === 'DISABLE' ? false : Number(job.enabled) === 1,
      config_reason: String(job.config_reason || ''),
    };
  };

  const sameManifest = (left: ScheduledJobOperationManifest | null, right: ScheduledJobOperationManifest) =>
    left !== null && JSON.stringify(left) === JSON.stringify(right);

  const fetchCurrentScheduledJob = async (id: string): Promise<ScheduledJob | null> => {
    try {
      const response = await fetch(`/api/scheduled-jobs/${encodeURIComponent(id)}`, { headers: authHeaders });
      const payload = await response.json().catch(() => null) as { success?: boolean; data?: ScheduledJob; detail?: string; message?: string } | null;
      if (!response.ok || !payload?.data) {
        throw new Error(payload?.detail || payload?.message || (zh ? '无法读取当前作业配置。' : 'Unable to load the current job details.'));
      }
      return payload.data;
    } catch (cause) {
      showToast(cause instanceof Error ? cause.message : (zh ? '无法读取当前作业配置。' : 'Unable to load the current job details.'), 'error');
      return null;
    }
  };

  const openDeleteApproval = async (job: ScheduledJob) => {
    if (job.authorization_mode === 'system') {
      showToast(zh ? '系统内置作业由平台托管，此处仅可查看。' : 'This built-in job is platform-managed and can only be viewed here.', 'info');
      return;
    }
    const currentJob = await fetchCurrentScheduledJob(job.id);
    if (!currentJob) return;
    setDeleteConfirmId(null);
    setDeleteTarget(currentJob);
    setDeleteReason(`${zh ? '申请删除作业' : 'Delete job'}: ${currentJob.name}`);
    setDeleteApprover('');
    setDeleteApprovalMethod('mfa');
    resetDeleteApprovalFlow();
    fetchApprovers();
    setDeleteApprovalOpen(true);
  };

  /**
   * 统一的表单必填校验。命令(commands)在大部分场景下可选；其余字段都是必填。
   * 仅当返回值为 null 时通过校验，否则返回的字符串就是要展示给用户的中/英文提示。
   */
  const validateForm = (): string | null => {
    if (!form.name.trim()) return zh ? '请填写作业名称' : 'Please enter job name';
    if (!form.action_type) return zh ? '请选择作业类型' : 'Please select a job type';
    if (form.action_type === 'command' && !form.commands.trim()) {
      return zh ? '请输入要执行的命令' : 'Enter the commands to run';
    }
    if (form.action_type === 'script_run' && !form.script_id.trim()) {
      return zh ? '请选择一个已发布的自动化脚本' : 'Select a released automation script';
    }
    if (form.script_id.trim() && form.action_type !== 'command' && form.action_type !== 'script_run') {
      return zh ? '当前作业类型不能关联自动化脚本' : 'This job type cannot use an automation script';
    }
    if (form.is_config && form.action_type !== 'command' && form.action_type !== 'script_run') {
      return zh ? '配置变更模式只能用于命令或脚本作业' : 'Configuration-change mode is only available for command or script jobs';
    }
    if (form.is_config && !form.config_reason.trim()) {
      return zh ? '请填写配置变更原因' : 'Enter the configuration change reason';
    }
    if (!form.cron_expr.trim()) return zh ? '请配置调度时间(Cron)' : 'Please configure schedule (Cron)';

    // Cron 表达式必须是 5 段且每段非空
    const parts = form.cron_expr.trim().split(/\s+/);
    if (parts.length !== 5 || parts.some(p => !p)) {
      return zh ? 'Cron 表达式格式不完整(需 5 段)' : 'Cron expression must have 5 fields';
    }

    // 设备范围必填
    if (!form.device_scope) return zh ? '请选择设备范围' : 'Please select device scope';
    if (form.device_scope === 'ip' && ipDevices.length === 0) {
      return zh ? '请至少添加一个目标 IP / 设备' : 'Please add at least one target IP / device';
    }
    if (form.device_scope === 'tag') {
      if (!hasTagFilterConditions(tagFilter)) return zh ? '请配置至少一个标签条件' : 'Please configure at least one tag condition';
    }
    if ((form.device_scope === 'site' || form.device_scope === 'role') && !form.device_filter.trim()) {
      return zh ? '请填写过滤条件' : 'Please enter filter condition';
    }

    // 按作业类型继续校验
    // 智能巡检三种来源:
    //  - default: script_id 与 commands 都为空 → 通过 (后端启用全量默认指标)
    //  - script:  script_id 必填
    //  - custom:  commands  必填
    // 因 inspSource 状态在 JobModal 内,这里仅做"任一分支可推导出有效配置"的校验,
    // 不阻拦三种合法组合(空/有 script_id/有 commands)。

    return null;
  };

  const createJob = async () => {
    const err = validateForm();
    if (err) { showToast(err, 'error'); return; }
    if (approvalStatus !== 'verified') {
      showToast(zh ? '请先发送验证码并完成审批验证' : 'Please complete approval verification first', 'error');
      return;
    }
    const operationManifest = buildFormOperationManifest('CREATE');
    if (!sameManifest(approvalManifest, operationManifest)) {
      resetApprovalFlow();
      showToast(zh ? '作业配置已变化，请重新申请审批' : 'The job configuration changed. Request approval again.', 'error');
      return;
    }
    try {
      const r = await fetch('/api/scheduled-jobs', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({
          ...form,
          name: operationManifest.name,
          action_type: operationManifest.action,
          cron_expr: operationManifest.cron_expr,
          scheduled_at: operationManifest.scheduled_at,
          device_scope: operationManifest.scope.type,
          device_filter: operationManifest.scope.filter,
          commands: operationManifest.commands,
          check_items: operationManifest.check_items,
          script_id: operationManifest.script_id,
          is_config: operationManifest.is_config,
          config_reason: operationManifest.config_reason,
          use_admin_creds: operationManifest.use_admin_creds,
          enabled: operationManifest.enabled,
          job_type: operationManifest.job_type,
          approval_token: approvalToken,
          approval_code: approvalCode,
          operation_manifest: operationManifest,
        }),
      });
      const j = await r.json();
      if (r.ok && j.success) {
        closeModal();
        fetchJobs();
        showToast(zh ? '定时作业已创建' : 'Scheduled job created', 'success');
      } else {
        showToast(j.detail || j.message || 'Failed', 'error');
      }
    } catch {
      showToast(zh ? '创建失败' : 'Create failed', 'error');
    }
  };

  const updateJob = async () => {
    if (!editingJob) return;
    if (editingJob.authorization_mode === 'system') {
      showToast(zh ? '系统内置作业由平台托管，此处仅可查看。' : 'This built-in job is platform-managed and can only be viewed here.', 'info');
      return;
    }
    const err = validateForm();
    if (err) { showToast(err, 'error'); return; }
    if (approvalStatus !== 'verified') {
      showToast(zh ? '请先发送验证码并完成审批验证' : 'Please complete approval verification first', 'error');
      return;
    }
    const operationManifest = buildFormOperationManifest('UPDATE');
    if (!sameManifest(approvalManifest, operationManifest)) {
      resetApprovalFlow();
      showToast(zh ? '作业配置已变化，请重新申请审批' : 'The job configuration changed. Request approval again.', 'error');
      return;
    }
    try {
      const r = await fetch(`/api/scheduled-jobs/${editingJob.id}`, {
        method: 'PUT',
        headers: authHeaders,
        body: JSON.stringify({
          name: operationManifest.name,
          action_type: operationManifest.action,
          cron_expr: operationManifest.cron_expr,
          scheduled_at: operationManifest.scheduled_at,
          job_type: operationManifest.job_type,
          device_scope: operationManifest.scope.type,
          device_filter: operationManifest.scope.filter,
          script_id: operationManifest.script_id,
          commands: operationManifest.commands,
          check_items: operationManifest.check_items,
          is_config: operationManifest.is_config,
          config_reason: operationManifest.config_reason,
          use_admin_creds: operationManifest.use_admin_creds,
          approval_token: approvalToken,
          approval_code: approvalCode,
          operation_manifest: operationManifest,
        }),
      });
      const j = await r.json();
      if (r.ok && j.success) {
        closeModal();
        fetchJobs();
        showToast(zh ? '作业已更新' : 'Job updated', 'success');
      } else {
        showToast(j.detail || j.message || 'Failed', 'error');
      }
    } catch {
      showToast(zh ? '操作失败' : 'Operation failed', 'error');
    }
  };

  const executeDisableJob = async () => {
    if (!disableTarget || approvalStatus !== 'verified') return;
    const operationManifest = buildJobOperationManifest(disableOperation, disableTarget);
    if (!sameManifest(approvalManifest, operationManifest)) {
      resetApprovalFlow();
      setApprovalError(zh ? '作业信息已变化，请重新申请停用审批。' : 'The job details changed. Request disable approval again.');
      return;
    }
    setDisableSubmitting(true);
    setApprovalError('');
    try {
      const response = await fetch(`/api/scheduled-jobs/${encodeURIComponent(disableTarget.id)}/toggle`, {
        method: 'PUT',
        headers: authHeaders,
        body: JSON.stringify({
          enabled: disableOperation === 'ENABLE',
          approval_token: approvalToken,
          approval_code: approvalCode,
          operation_manifest: operationManifest,
        }),
      });
      const payload = await response.json().catch(() => null) as { success?: boolean; detail?: string; message?: string } | null;
      if (!response.ok || payload?.success === false) {
        throw new Error(payload?.detail || payload?.message || (zh
          ? (disableOperation === 'ENABLE' ? '无法启用作业。' : '无法停用作业。')
          : (disableOperation === 'ENABLE' ? 'Unable to enable job.' : 'Unable to disable job.')));
      }
      setDisableTarget(null);
      setDisableReason('');
      resetApprovalFlow();
      fetchJobs();
      showToast(disableOperation === 'ENABLE'
        ? (zh ? '作业已启用' : 'Job enabled')
        : (zh ? '作业已停用' : 'Job disabled'), 'success');
    } catch (cause) {
      setApprovalError(cause instanceof Error ? cause.message : (zh
        ? (disableOperation === 'ENABLE' ? '无法启用作业。' : '无法停用作业。')
        : (disableOperation === 'ENABLE' ? 'Unable to enable job.' : 'Unable to disable job.')));
    } finally {
      setDisableSubmitting(false);
    }
  };

  const toggleJobEnabled = async (job: ScheduledJob) => {
    if (job.authorization_mode === 'system') {
      showToast(zh ? '系统内置作业由平台托管，此处仅可查看。' : 'This built-in job is platform-managed and can only be viewed here.', 'info');
      return;
    }
    const currentJob = await fetchCurrentScheduledJob(job.id);
    if (!currentJob) return;
    const operation = Number(currentJob.enabled) ? 'DISABLE' : 'ENABLE';
    resetApprovalFlow();
    setApproverUsername('');
    setApprovalMethod('mfa');
    setDisableOperation(operation);
    setDisableReason(`${zh ? (operation === 'ENABLE' ? '启用定时作业' : '停用定时作业') : (operation === 'ENABLE' ? 'Enable scheduled job' : 'Disable scheduled job')}: ${currentJob.name}`);
    setDisableTarget(currentJob);
  };

  const submitForm = () => {
    const err = validateForm();
    if (err) { showToast(err, 'error'); return; }
    if (isEditMode) updateJob();
    else createJob();
  };

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <PageHero
        icon={CalendarClock}
        title={zh ? '定时作业' : 'Scheduled Jobs'}
        subtitle={zh ? '创建和管理周期性执行的自动化作业，需审批人验证码授权' : 'Create and manage periodic automation jobs with approver verification'}
        actions={
          <>
            <button
              onClick={() => { fetchJobs(); fetchSystemJobs(); }}
              disabled={loading}
              className="inline-flex h-8 items-center gap-1 rounded-xl border border-black/8 bg-white px-3 text-[11px] font-medium text-blue-700 transition-all hover:bg-blue-50 hover:border-blue-200"
            >
              <RotateCcw size={12} className={loading ? 'animate-spin' : ''} />
              {zh ? '刷新' : 'Refresh'}
            </button>
            {!showAddJob && (
              <button
                type="button"
                onClick={() => setBulkCollectionPlanOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-xl border border-blue-200 bg-white px-3.5 py-2.5 text-xs font-bold text-blue-700 shadow-sm transition hover:border-blue-300 hover:bg-blue-50"
              >
                <Layers size={15} />
                {zh ? '批量采集模板' : 'Bulk Collection Templates'}
              </button>
            )}
          </>
        }
      />

      <div className="relative min-h-0 flex-1 overflow-auto px-2 py-3 sm:px-3 lg:px-4">
            <motion.div
              key="list-view"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className={`space-y-4 transition-opacity duration-150 ${showAddJob ? 'pointer-events-none' : ''}`}
              aria-hidden={showAddJob}
              inert={showAddJob}
            >
              {/* ═══ 顶层多维分类导航与搜索栏 ═══ */}
              <ListToolbar
                className="flex-col md:flex-row md:items-center justify-between bg-slate-100/90 p-1.5 rounded-2xl border border-slate-200/80 shadow-inner"
                leadingAction={!showAddJob ? (
                  <button
                    type="button"
                    onClick={toggleAddJob}
                    className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-xs font-bold text-white shadow-sm transition hover:bg-blue-700 active:scale-[0.98]"
                  >
                    <Plus size={15} />
                    {zh ? '新建' : 'New'}
                  </button>
                ) : undefined}
              >
                <div className="flex items-center gap-1 overflow-x-auto custom-scrollbar py-0.5">
                  <button
                    onClick={() => { setPage(1); setActiveCategory('all'); }}
                    className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-bold transition-all whitespace-nowrap shrink-0 ${
                      activeCategory === 'all'
                        ? 'bg-white text-blue-700 shadow-sm border border-blue-100'
                        : 'text-slate-600 hover:text-slate-900 hover:bg-white/60'
                    }`}
                  >
                    <span>{zh ? '用户作业' : 'User Jobs'}</span>
                    <span className={`px-2 py-0.5 rounded-full text-[10px] ${activeCategory === 'all' ? 'bg-blue-100 text-blue-800 font-mono' : 'bg-slate-200/80 text-slate-600'}`}>
                      {total}
                    </span>
                  </button>

                  <button
                    onClick={() => {
                      setPage(1);
                      setActiveCategory('system');
                      setSystemCollapsed(false);
                    }}
                    className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-bold transition-all whitespace-nowrap shrink-0 ${
                      activeCategory === 'system'
                        ? 'bg-white text-blue-700 shadow-sm border border-blue-100'
                        : 'text-slate-600 hover:text-slate-900 hover:bg-white/60'
                    }`}
                  >
                    <span>{zh ? '系统计划' : 'System Schedules'}</span>
                    <span className={`px-2 py-0.5 rounded-full text-[10px] ${activeCategory === 'system' ? 'bg-blue-100 text-blue-800 font-mono' : 'bg-slate-200/80 text-slate-600'}`}>
                      {systemJobs.length}
                    </span>
                  </button>

                  <div className="w-px h-5 bg-slate-300/60 mx-1" />

                  <button
                    onClick={() => { setPage(1); setActiveCategory('backup'); }}
                    className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-bold transition-all whitespace-nowrap shrink-0 ${
                      activeCategory === 'backup'
                        ? 'bg-white text-blue-700 border border-blue-100 shadow-sm'
                        : 'text-slate-600 hover:text-slate-900 hover:bg-white/60'
                    }`}
                  >
                    <Database size={13} className={activeCategory === 'backup' ? 'text-blue-600' : 'text-slate-400'} />
                    <span>{zh ? '配置采集' : 'Backup'}</span>
                    <span className="text-[10px] opacity-60 font-mono">{stats.backupCnt}</span>
                  </button>

                  <button
                    onClick={() => { setPage(1); setActiveCategory('nsot'); }}
                    className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-bold transition-all whitespace-nowrap shrink-0 ${
                      activeCategory === 'nsot'
                        ? 'bg-white text-blue-700 border border-blue-100 shadow-sm'
                        : 'text-slate-600 hover:text-slate-900 hover:bg-white/60'
                    }`}
                  >
                    <RefreshCw size={13} className={activeCategory === 'nsot' ? 'text-blue-600' : 'text-slate-400'} />
                    <span>NSOT</span>
                    <span className="text-[10px] opacity-60 font-mono">{stats.nsotCnt}</span>
                  </button>

                  <button
                    onClick={() => { setPage(1); setActiveCategory('inspection'); }}
                    className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-bold transition-all whitespace-nowrap shrink-0 ${
                      activeCategory === 'inspection'
                        ? 'bg-white text-blue-700 border border-blue-100 shadow-sm'
                        : 'text-slate-600 hover:text-slate-900 hover:bg-white/60'
                    }`}
                  >
                    <Activity size={13} className={activeCategory === 'inspection' ? 'text-blue-600' : 'text-slate-400'} />
                    <span>{zh ? '智能巡检' : 'Inspection'}</span>
                    <span className="text-[10px] opacity-60 font-mono">{stats.inspCnt}</span>
                  </button>

                  <button
                    onClick={() => { setPage(1); setActiveCategory('command'); }}
                    className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-bold transition-all whitespace-nowrap shrink-0 ${
                      activeCategory === 'command'
                        ? 'bg-white text-blue-700 border border-blue-100 shadow-sm'
                        : 'text-slate-600 hover:text-slate-900 hover:bg-white/60'
                    }`}
                  >
                    <Terminal size={13} className={activeCategory === 'command' ? 'text-blue-600' : 'text-slate-400'} />
                    <span>{zh ? '命令执行' : 'Commands'}</span>
                    <span className="text-[10px] opacity-60 font-mono">{stats.commandCnt}</span>
                  </button>

                  <button
                    onClick={() => { setPage(1); setActiveCategory('script_run'); }}
                    className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-bold transition-all whitespace-nowrap shrink-0 ${
                      activeCategory === 'script_run'
                        ? 'bg-white text-blue-700 border border-blue-100 shadow-sm'
                        : 'text-slate-600 hover:text-slate-900 hover:bg-white/60'
                    }`}
                  >
                    <Zap size={13} className={activeCategory === 'script_run' ? 'text-blue-600' : 'text-slate-400'} />
                    <span>{zh ? '自动化脚本' : 'Scripts'}</span>
                    <span className="text-[10px] opacity-60 font-mono">{stats.scriptCnt}</span>
                  </button>
                </div>

                <ListSearchInput
                    language={language}
                    className="md:max-w-xs"
                    value={searchQuery}
                    onChange={e => setSearchQuery(e.target.value)}
                    placeholder={zh ? '按名称、脚本ID或命令搜索...' : 'Search by name, command...'}
                    onClear={() => setSearchQuery('')}
                  />
                <ColumnSettingsButton
                  columns={[
                    { key: 'name', label: zh ? '作业名称' : 'Job name' },
                    { key: 'target', label: zh ? '任务对象' : 'Target' },
                    { key: 'schedule', label: zh ? '执行周期' : 'Schedule' },
                    { key: 'status', label: zh ? '状态' : 'Status' },
                    { key: 'updatedBy', label: zh ? '修改人' : 'Modified by' },
                    { key: 'updatedAt', label: zh ? '修改时间' : 'Modified at' },
                    { key: 'actions', label: zh ? '操作' : 'Actions', required: true, isAction: true },
                  ]}
                  visibleKeys={visibleJobColumnKeys}
                  defaultVisibleKeys={SCHEDULED_JOB_COLUMN_DEFS.filter(column => column.defaultVisible).map(column => column.key)}
                  onApply={keys => setVisibleJobColumnKeys(keys as typeof visibleJobColumnKeys)}
                  language={language}
                  label={zh ? '列设置' : 'Columns'}
                />
              </ListToolbar>

              {/* ═══ 内置系统作业分栏呈现 ═══ */}
              {activeCategory === 'system' && (
                <div className="rounded-2xl border border-slate-200/80 bg-white shadow-sm overflow-hidden">
                  <div
                    onClick={() => setSystemCollapsed(!systemCollapsed)}
                    className="px-5 py-3.5 bg-slate-50/50 hover:bg-slate-50 transition-colors border-b border-slate-100 flex items-center justify-between cursor-pointer select-none"
                  >
                    <div className="flex items-center gap-2.5">
                      <div className="w-7 h-7 rounded-lg bg-slate-200/50 flex items-center justify-center text-slate-600 shrink-0">
                        <Lock size={14} />
                      </div>
                      <div>
                        <h4 className="text-xs font-bold text-slate-700 flex items-center gap-2">
                          <span>{zh ? '系统业务计划' : 'System Business Schedules'}</span>
                          <span className="px-2 py-0.5 rounded-full bg-slate-200/70 text-slate-700 text-[10px] font-mono">
                            {filteredSystemJobs.length} {zh ? '项' : 'items'}
                          </span>
                        </h4>
                        <p className="text-[10px] text-slate-400 mt-0.5">
                          {zh
                            ? '仅展示需要业务关注的计划；采集与同步守护任务由平台托管'
                            : 'Operator-facing schedules only; collectors and sync daemons are platform-managed'}
                        </p>
                      </div>
                    </div>
                    <button className="text-slate-400 hover:text-slate-600 transition-colors p-1">
                      <ChevronUp size={16} className={`transition-transform duration-200 ${systemCollapsed ? 'rotate-180' : ''}`} />
                    </button>
                  </div>

                  {!systemCollapsed && (
                    <div className="overflow-x-auto">
                      <DataTable className="text-left" exportConfig={{ filename: 'scheduled-jobs-system', language: zh ? 'zh' : 'en', disabled: filteredSystemJobs.length === 0, exportData: exportSystemJobs }}>
                        <thead>
                          <tr className="border-b border-slate-100 text-[11px] font-bold text-slate-400 bg-slate-50/40 uppercase tracking-wider">
                            <th className="py-2.5 px-4">{zh ? '任务名称' : 'Job Name'}</th>
                            <th className="py-2.5 px-4">{zh ? '任务说明' : 'Description'}</th>
                            <th className="py-2.5 px-4">{zh ? '触发发条 (CRON)' : 'Trigger'}</th>
                            <th className="py-2.5 px-4">{zh ? '预计下次执行' : 'Next Run'}</th>
                            <TableActionHeader className="py-2.5 px-4">{zh ? '规则配置管理' : 'Management'}</TableActionHeader>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100 text-xs">
                          {filteredSystemJobs.map(sj => {
                            const isInsp = sj.action_type === 'inspection';
                            const isBackup = sj.action_type === 'backup';
                            const isSec = sj.action_type === 'password_rotation';
                            const icon = isBackup ? Database : isInsp ? Activity : isSec ? Shield : CalendarClock;
                            const Icon = icon;
                            const nextAt = sj.next_run_at
                              ? new Date(sj.next_run_at).toLocaleString(zh ? 'zh-CN' : 'en-US', {
                                  hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
                                })
                              : '-';

                            return (
                              <tr
                                key={sj.id}
                                className="hover:bg-slate-50/80 transition-colors group/row"
                              >
                                <td className="py-3 px-4 font-bold text-slate-800 min-w-[180px]">
                                  <div className="flex items-center gap-2">
                                    <div className={`w-6 h-6 rounded flex items-center justify-center shrink-0 ${
                                      isInsp ? 'bg-emerald-50 text-emerald-600 border border-emerald-100' :
                                      isBackup ? 'bg-indigo-50 text-indigo-600 border border-indigo-100' :
                                      isSec ? 'bg-amber-50 text-amber-600 border border-amber-100' :
                                      'bg-cyan-50 text-cyan-600 border border-cyan-100'
                                    }`}>
                                      <Icon size={13} />
                                    </div>
                                    <div>
                                      <div className="font-bold text-xs text-slate-800">{zh ? sj.name_zh : sj.name_en}</div>
                                    </div>
                                  </div>
                                </td>
                                <td className="py-3 px-4 text-slate-600 max-w-[280px] truncate" title={zh ? sj.description_zh : sj.description_en}>
                                  {zh ? sj.description_zh : sj.description_en}
                                </td>
                                <td className="py-3 px-4 font-mono text-[11px] text-cyan-700 font-medium">
                                  <span className="bg-cyan-50 px-2 py-0.5 rounded border border-cyan-100">{sj.trigger || 'CRON Daemon'}</span>
                                </td>
                                <td className="py-3 px-4 font-mono text-[11px] text-slate-500">
                                  {nextAt !== '-' && (
                                    <span className="inline-flex items-center gap-1.5 font-mono">
                                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse shrink-0" />
                                      {nextAt}
                                    </span>
                                  )}
                                </td>
                                <TableActionCell className="py-3 px-4">
                                  {sj.deep_link ? (
                                    <ActionIconButton
                                      icon={Settings2}
                                      label={zh ? '配置规则' : 'Configure rule'}
                                      variant="accent"
                                      onClick={() => navigate(sj.deep_link!)}
                                    />
                                  ) : (
                                    <span className="text-[11px] text-slate-400 italic">{zh ? '内核保护' : 'Kernel Protected'}</span>
                                  )}
                                </TableActionCell>
                              </tr>
                            );
                          })}
                        </tbody>
                      </DataTable>
                    </div>
                  )}
                </div>
              )}

              {/* ═══ 用户自定义作业分栏标题 ═══ */}
              {activeCategory !== 'system' && (
                <div className="flex items-center gap-3 px-1 pt-2">
                  <h3 className="text-xs font-bold uppercase tracking-widest text-slate-500 flex items-center gap-2">
                    <span>
                      {activeCategory === 'all' && (zh ? '用户自定义作业' : 'User-defined Jobs')}
                      {activeCategory === 'backup' && (zh ? '配置自动备份作业' : 'Config Backup Jobs')}
                      {activeCategory === 'nsot' && (zh ? 'NSOT 网络事实库采集作业' : 'NSOT Facts Collection Jobs')}
                      {activeCategory === 'inspection' && (zh ? '智能巡检作业' : 'Smart Inspection Jobs')}
                      {activeCategory === 'command' && (zh ? '命令执行作业' : 'Command Jobs')}
                      {activeCategory === 'script_run' && (zh ? '自动化脚本作业' : 'Automated Script Jobs')}
                    </span>
                    <span className="px-2 py-0.5 rounded-full bg-slate-200/70 text-slate-700 text-[10px] font-mono">
                      {filteredJobs.length} {zh ? '项' : 'items'}
                    </span>
                  </h3>
                  <div className="flex-1 h-px bg-slate-200" />
                  {searchQuery && (
                    <span className="text-xs text-cyan-600 font-semibold bg-cyan-50 px-2.5 py-0.5 rounded-full border border-cyan-100">
                      {zh ? `过滤出 ${filteredJobs.length} 项` : `Filtered ${filteredJobs.length}`}
                    </span>
                  )}
                </div>
              )}

              {/* ═══ 作业列表呈现 ═══ */}
              {activeCategory === 'system' ? null : loading ? (
                <div className="flex items-center justify-center py-16 text-slate-400">
                  <RotateCcw size={16} className="animate-spin mr-2 text-cyan-600" />
                  <span className="text-xs">{zh ? '数据加载中...' : 'Loading jobs...'}</span>
                </div>
              ) : filteredJobs.length > 0 ? (
                <div className="flex-1 overflow-auto max-h-[calc(100vh-320px)] rounded-2xl border border-slate-200 bg-white shadow-sm custom-scrollbar">
                  <DataTable
                    className="w-full min-w-[1060px] text-left"
                    exportConfig={{ filename: 'scheduled-jobs', language: zh ? 'zh' : 'en', disabled: filteredJobs.length === 0 }}
                  >
                    <thead className="sticky top-0 z-10 bg-slate-50 text-[11px] font-bold text-slate-500 shadow-[0_1px_0_rgba(15,23,42,0.08)]">
                      <tr>
                        {visibleJobColumnSet.has('name') && <th className="px-4 py-3">{zh ? '作业名称' : 'Job Name'}</th>}
                        {visibleJobColumnSet.has('target') && <th className="px-4 py-3">{zh ? '任务对象' : 'Target'}</th>}
                        {visibleJobColumnSet.has('schedule') && <th className="px-4 py-3">{zh ? '执行周期（Crontab）' : 'Schedule (Crontab)'}</th>}
                        {visibleJobColumnSet.has('status') && <th className="px-4 py-3"><span className="inline-flex items-center">{zh ? '状态' : 'Status'}<TableHeaderMultiSelectFilter label={zh ? '状态' : 'Status'} language={language} options={[{ value: 'enabled', label: zh ? '已启用' : 'Enabled' }, { value: 'disabled', label: zh ? '已停用' : 'Disabled' }]} selectedValues={jobStatusFilters} onApply={(values) => { setPage(1); setJobStatusFilters(values); }} /></span></th>}
                        {visibleJobColumnSet.has('updatedBy') && <th className="px-4 py-3">{zh ? '修改人' : 'Modified By'}</th>}
                        {visibleJobColumnSet.has('updatedAt') && <th className="px-4 py-3">{zh ? '修改时间' : 'Modified At'}</th>}
                        <TableActionHeader className="whitespace-nowrap px-4 py-3">{zh ? '操作' : 'Actions'}</TableActionHeader>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 text-xs">
                      {filteredJobs.map(job => {
                        const isEnabled = !!job.enabled;
                        const isSystemManaged = job.authorization_mode === 'system';
                        let scopeDesc = describeScope(job.device_scope, job.device_filter, zh);
                        if (job.device_scope === 'composite') {
                          try {
                            const scopeFilters: unknown = JSON.parse(job.device_filter || '{}');
                            if (scopeFilters && typeof scopeFilters === 'object' && !Array.isArray(scopeFilters)) {
                              const platform = (scopeFilters as CollectionPlanFilters).platform;
                              if (platform) scopeDesc = `${scopeDesc} · ${platform}`;
                            }
                          } catch { /* Keep the legacy scope label for malformed filters. */ }
                        }
                        return (
                          <tr
                            key={job.id}
                            onClick={() => setDetailJob(job)}
                            onKeyDown={(event) => {
                              if (event.key === 'Enter' || event.key === ' ') {
                                event.preventDefault();
                                setDetailJob(job);
                              }
                            }}
                            tabIndex={0}
                            data-selected={detailJob?.id === job.id || undefined}
                            aria-selected={detailJob?.id === job.id}
                            className="cursor-pointer transition-colors hover:bg-blue-50/40 focus:outline-none focus-visible:bg-blue-50/50"
                          >
                            {visibleJobColumnSet.has('name') && <td className="max-w-[220px] px-4 py-3.5 font-semibold text-slate-800">
                              <span className="block truncate" title={job.name}>{job.name || '—'}</span>
                            </td>}
                            {visibleJobColumnSet.has('target') && <td className="max-w-[230px] px-4 py-3.5 text-slate-600">
                              <span className="block truncate" title={scopeDesc}>{scopeDesc}</span>
                            </td>}
                            {visibleJobColumnSet.has('schedule') && <td className="px-4 py-3.5">
                              <code className="whitespace-nowrap rounded-md border border-cyan-100 bg-cyan-50 px-2 py-1 font-mono text-[11px] font-semibold text-cyan-800" title={describeCron(job.cron_expr, zh)}>
                                {job.cron_expr || '—'}
                              </code>
                            </td>}
                            {visibleJobColumnSet.has('status') && <td className="px-4 py-3.5">
                              <span className={`inline-flex whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-bold ${
                                isEnabled ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-600'
                              }`}>
                                {isEnabled ? (zh ? '已启用' : 'Enabled') : (zh ? '已停用' : 'Disabled')}
                              </span>
                            </td>}
                            {visibleJobColumnSet.has('updatedBy') && <td className="px-4 py-3.5 font-medium text-slate-600">
                              {job.updated_by || job.created_by || '—'}
                            </td>}
                            {visibleJobColumnSet.has('updatedAt') && <td className="whitespace-nowrap px-4 py-3.5 font-mono text-[11px] text-slate-600">
                              {formatJobDateTime(job.updated_at || job.created_at)}
                            </td>}
                            <TableActionCell
                              className="whitespace-nowrap px-4 py-3.5"
                              label={zh ? `定时作业操作：${job.name}` : `Scheduled job actions: ${job.name}`}
                              onClick={(event) => event.stopPropagation()}
                            >
                              <ActionIconButton
                                icon={Eye}
                                label={zh ? '查看详情' : 'View details'}
                                onClick={() => setDetailJob(job)}
                              />
                              {!isSystemManaged && (
                                <>
                                  <ActionIconButton
                                    icon={Pencil}
                                    label={zh ? '编辑作业' : 'Edit job'}
                                    onClick={() => openEditModal(job)}
                                  />
                                  <ActionIconButton
                                    icon={isEnabled ? PowerOff : Power}
                                    label={isEnabled ? (zh ? '停用作业' : 'Disable job') : (zh ? '启用作业' : 'Enable job')}
                                    variant={isEnabled ? 'default' : 'success'}
                                    onClick={() => toggleJobEnabled(job)}
                                  />
                                  {deleteConfirmId === job.id ? (
                                    <div className="flex items-center gap-1.5 ml-1">
                                      <button
                                        onClick={() => { void openDeleteApproval(job); }}
                                        className="px-2.5 py-1.5 rounded-xl bg-rose-600 text-white text-xs font-bold hover:bg-rose-700 transition-all shadow-sm"
                                      >
                                        {zh ? '确认删除' : 'Confirm'}
                                      </button>
                                      <button
                                        onClick={() => setDeleteConfirmId(null)}
                                        className="px-2.5 py-1.5 rounded-xl border border-slate-200 text-xs font-semibold text-slate-600 hover:bg-slate-100 transition-all"
                                      >
                                        {zh ? '取消' : 'Cancel'}
                                      </button>
                                    </div>
                                  ) : (
                                    <ActionIconButton
                                      icon={Trash2}
                                      label={zh ? '删除作业' : 'Delete job'}
                                      variant="danger"
                                      onClick={() => setDeleteConfirmId(job.id)}
                                    />
                                  )}
                                </>
                              )}
                            </TableActionCell>
                          </tr>
                        );
                      })}
                    </tbody>
                  </DataTable>
                </div>
              ) : (
                <div className="rounded-3xl border-2 border-dashed border-slate-200/80 p-16 text-center bg-white/50">
                  <div className="w-16 h-16 rounded-2xl bg-cyan-50 text-cyan-600 flex items-center justify-center mx-auto mb-4 border border-cyan-100 shadow-sm">
                    <CalendarClock size={32} />
                  </div>
                  <p className="text-base text-slate-800 font-bold">{zh ? '未找到符合条件的定时作业' : 'No matching scheduled jobs'}</p>
                  <p className="text-xs text-slate-500 mt-1 mb-6 max-w-md mx-auto leading-relaxed">
                    {zh
                      ? '当前分类或搜索条件下暂无匹配的周期性自动化作业。您可以点击上方重置筛选，或立即创建每日备份与智能巡检任务。'
                      : 'No scheduled jobs found matching current filters. Create a new recurring job anytime.'}
                  </p>
                  <button
                    onClick={toggleAddJob}
                    className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-blue-600 text-white text-xs font-bold hover:bg-blue-700 transition-all shadow shadow-blue-600/20 active:scale-[0.98]"
                  >
                    <Plus size={16} />
                    {zh ? '新建' : 'New'}
                  </button>
                </div>
              )}

              {total > 0 && (
                <div className="mt-auto pt-4 border-t border-black/5 bg-white">
                  <Pagination currentPage={page} totalItems={total} itemsPerPage={pageSize} onPageChange={setPage} onItemsPerPageChange={setPageSize} language={language} />
                </div>
              )}
            </motion.div>
      </div>

      {showAddJob && (
        <JobModal
          isOpen={showAddJob}
          onClose={closeModal}
          isEditMode={isEditMode}
          enablingJobId={enablingJobId}
          editingJob={editingJob}
          form={form}
          setForm={setForm}
          tagFilter={tagFilter}
          setTagFilter={setTagFilter}
          ipInput={ipInput}
          setIpInput={setIpInput}
          ipValidating={ipValidating}
          ipError={ipError}
          setIpError={setIpError}
          ipDevices={ipDevices}
          removeIpDevice={removeIpDevice}
          validateAndAddIps={validateAndAddIps}
          presetOpen={presetOpen}
          setPresetOpen={setPresetOpen}
          scriptSearch={scriptSearch}
          setScriptSearch={setScriptSearch}
          showScriptDropdown={showScriptDropdown}
          setShowScriptDropdown={setShowScriptDropdown}
          availableScripts={availableScripts}
          fetchScripts={fetchScripts}
          approverUsername={approverUsername}
          setApproverUsername={selectApprover}
          approvers={approvers}
          approverLoadStatus={approverLoadStatus}
          refreshApprovers={fetchApprovers}
          approvalMethod={approvalMethod}
          setApprovalMethod={changeApprovalMethod}
          approvalStatus={approvalStatus}
          approvalCountdown={approvalCountdown}
          approvalDeadline={approvalDeadline}
          onApprovalCountdownExpire={expireApprovalCountdown}
          approvalCode={approvalCode}
          setApprovalCode={setApprovalCode}
          approvalError={approvalError}
          setApprovalError={setApprovalError}
          requestApproval={requestApproval}
          verifyApproval={verifyApproval}
          fetchCronPreview={fetchCronPreview}
          submitForm={submitForm}
          language={language}
          devices={devices}
          deviceLoadStatus={deviceLoadStatus}
          refreshDevices={fetchDevices}
        />
      )}

      {/* --- Detail Modal --- */}
      <JobDetailModal
        isOpen={!!detailJob}
        onClose={() => setDetailJob(null)}
        detailJob={detailJob}
        openScriptManagement={(scriptId) => {
          setDetailJob(null);
          navigate({ pathname: '/automation/scripts', search: `?q=${encodeURIComponent(scriptId)}` });
        }}
        availableScripts={availableScripts}
        openEditModal={openEditModal}
        fetchNsotCollectionPreview={fetchNsotCollectionPreview}
        language={language}
      />

      {disableTarget && (
        <div className="fixed inset-0 z-[90] flex items-center justify-center p-4" role="dialog" aria-modal="true">
          <button
            type="button"
            aria-label={zh ? '关闭作业审批' : 'Close job approval'}
            className="absolute inset-0 bg-slate-950/50"
            disabled={approvalStatus === 'sending' || approvalStatus === 'verifying' || disableSubmitting}
            onClick={() => {
              setDisableTarget(null);
              setDisableReason('');
              resetApprovalFlow();
            }}
          />
          <div className="relative w-full max-w-sm overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl">
            <div className={`flex items-center justify-between border-b px-4 py-3 ${disableOperation === 'ENABLE' ? 'border-cyan-100 bg-cyan-50' : 'border-amber-100 bg-amber-50'}`}>
              <div>
                <h3 className={`text-sm font-bold ${disableOperation === 'ENABLE' ? 'text-cyan-900' : 'text-amber-900'}`}>
                  {disableOperation === 'ENABLE'
                    ? (zh ? '启用作业审批' : 'Enable Job Approval')
                    : (zh ? '停用作业审批' : 'Disable Job Approval')}
                </h3>
                <p className="mt-1 text-xs text-slate-600">{disableTarget.name}</p>
              </div>
              <button
                type="button"
                disabled={approvalStatus === 'sending' || approvalStatus === 'verifying' || disableSubmitting}
                onClick={() => {
                  setDisableTarget(null);
                  setDisableReason('');
                  resetApprovalFlow();
                }}
                className="rounded-lg px-2 py-1 text-slate-400 hover:bg-white/70 hover:text-slate-700 disabled:opacity-40"
              >×</button>
            </div>
            <div className="space-y-3 px-4 py-4 text-xs text-slate-700">
              <div className="rounded-xl border border-slate-100 bg-slate-50 px-3 py-2 text-[11px] text-slate-600">
                <div className="truncate font-semibold text-slate-800">{disableTarget.action_type} · {disableTarget.device_scope}</div>
                <div className="mt-0.5 font-mono">{disableTarget.cron_expr}</div>
              </div>
              <label className="block space-y-1.5">
                <span className="font-semibold">{zh ? '操作原因' : 'Reason'}</span>
                <input
                  value={disableReason}
                  onChange={event => setDisableReason(event.target.value)}
                  disabled={approvalStatus !== 'idle'}
                  className={`w-full rounded-xl border border-slate-200 px-3 py-2 outline-none disabled:bg-slate-50 ${disableOperation === 'ENABLE' ? 'focus:border-cyan-500' : 'focus:border-amber-500'}`}
                />
              </label>
              {approvalStatus === 'idle' && (
                <>
                  <label className="block space-y-1.5">
                    <span className="font-semibold">{zh ? '选择审批人' : 'Approver'}</span>
                    <select
                      value={approverUsername}
                      onChange={event => selectApprover(event.target.value)}
                      className={`w-full rounded-xl border border-slate-200 bg-white px-3 py-2 outline-none ${disableOperation === 'ENABLE' ? 'focus:border-cyan-500' : 'focus:border-amber-500'}`}
                    >
                      <option value="">{zh ? '选择审批人...' : 'Select approver...'}</option>
                      {approvers.map(approver => (
                        <option key={approver.id} value={approver.username}>{approver.username}</option>
                      ))}
                    </select>
                    {approverLoadStatus === 'loading' && <span className="block text-slate-500">{zh ? '正在加载审批人…' : 'Loading approvers…'}</span>}
                    {approverLoadStatus === 'error' && (
                      <span className="flex items-center justify-between gap-2 text-rose-700">
                        {zh ? '审批人加载失败，可能是登录或权限问题。' : 'Approver loading failed. Check your session or permissions.'}
                        <button type="button" onClick={fetchApprovers} className="shrink-0 font-semibold underline">{zh ? '重试' : 'Retry'}</button>
                      </span>
                    )}
                    {approverLoadStatus === 'loaded' && approvers.length === 0 && <span className="block text-amber-700">{zh ? '当前没有可用审批人。' : 'No eligible approvers are available.'}</span>}
                  </label>
                  {approvalMethod && (approvers.find(item => item.username === approverUsername)?.verification_methods.length || 0) > 0 && (
                    <label className="block space-y-1.5">
                      <span className="font-semibold">{zh ? '验证方式' : 'Verification method'}</span>
                      <select
                        value={approvalMethod}
                        onChange={event => changeApprovalMethod(event.target.value as ApprovalVerificationMethod)}
                        className={`w-full rounded-xl border border-slate-200 bg-white px-3 py-2 outline-none ${disableOperation === 'ENABLE' ? 'focus:border-cyan-500' : 'focus:border-amber-500'}`}
                      >
                        {approvers.find(item => item.username === approverUsername)?.verification_methods.map(method => (
                          <option key={method} value={method}>{method === 'mfa' ? 'MFA' : method === 'email' ? (zh ? '邮箱' : 'Email') : 'Feishu'}</option>
                        ))}
                      </select>
                    </label>
                  )}
                  <button
                    type="button"
                    onClick={requestApproval}
                    disabled={!approverUsername || !disableReason.trim() || approvalStatus !== 'idle'}
                    className={`w-full rounded-xl px-4 py-2.5 font-bold text-white disabled:cursor-not-allowed disabled:opacity-40 ${disableOperation === 'ENABLE' ? 'bg-cyan-600 hover:bg-cyan-700' : 'bg-amber-600 hover:bg-amber-700'}`}
                  >
                    {zh ? '发送审批验证码' : 'Request approval code'}
                  </button>
                </>
              )}
              {approvalStatus === 'sending' && <div className="rounded-xl bg-slate-50 px-3 py-2 text-slate-600">{zh ? '正在发送验证码...' : 'Sending approval code...'}</div>}
              {(approvalStatus === 'sent' || approvalStatus === 'verifying') && (
                <div className="space-y-2 rounded-xl border border-slate-100 bg-slate-50 p-3">
                  <label className="block font-semibold" htmlFor="scheduled-job-disable-code">
                    {approvalMethod === 'mfa' ? (zh ? '输入审批人的 6 位 MFA 动态码' : 'Enter approver’s 6-digit MFA code') : (zh ? '输入 6 位工单验证码' : 'Enter the 6-digit approval code')}
                  </label>
                  <div className="flex gap-2">
                    <input
                      id="scheduled-job-disable-code"
                      value={approvalCode}
                      disabled={approvalStatus === 'verifying'}
                      onChange={event => {
                        const code = event.target.value.replace(/\D/g, '').slice(0, 6);
                        setApprovalCode(code);
                        setApprovalError('');
                        if (code.length === 6) verifyApproval(code);
                      }}
                      inputMode="numeric"
                      maxLength={6}
                      className="w-36 rounded-xl border border-slate-200 px-3 py-1.5 text-center font-mono tracking-[0.25em] outline-none focus:border-emerald-500 disabled:bg-slate-100"
                    />
                    {approvalStatus === 'verifying' && <span className="text-[11px] text-cyan-700">{zh ? '正在验证…' : 'Verifying…'}</span>}
                  </div>
                  <p className="text-[10px] text-slate-400">{zh ? '输入满 6 位后自动验证；失败后修改验证码即可重试。' : 'Verification starts after 6 digits; edit the code to retry if it fails.'}</p>
                  {approvalCountdown > 0 && (
                    <CountdownText deadline={approvalDeadline} onExpire={expireApprovalCountdown}>
                      {secondsRemaining => (
                        <p className="text-slate-500">{zh ? '验证码有效期' : 'Code expires in'} {Math.floor(secondsRemaining / 60)}:{String(secondsRemaining % 60).padStart(2, '0')}</p>
                      )}
                    </CountdownText>
                  )}
                </div>
              )}
              {approvalStatus === 'verified' && <div className="rounded-xl border border-emerald-100 bg-emerald-50 px-3 py-2 font-semibold text-emerald-800">{zh ? '审批验证通过。' : 'Approval verified.'}</div>}
              {approvalError && <div role="alert" className="rounded-xl bg-rose-50 px-3 py-2 text-rose-700">{approvalError}</div>}
            </div>
            <div className="flex justify-end gap-2 border-t border-slate-100 px-4 py-3">
              <button
                type="button"
                disabled={approvalStatus === 'sending' || approvalStatus === 'verifying' || disableSubmitting}
                onClick={() => {
                  setDisableTarget(null);
                  setDisableReason('');
                  resetApprovalFlow();
                }}
                className="rounded-xl border border-slate-200 px-4 py-2 font-semibold text-slate-600 hover:bg-slate-50 disabled:opacity-40"
              >{zh ? '取消' : 'Cancel'}</button>
              <button
                type="button"
                onClick={executeDisableJob}
                disabled={approvalStatus !== 'verified' || disableSubmitting}
                className={`rounded-xl px-4 py-2 font-bold text-white disabled:cursor-not-allowed disabled:opacity-40 ${disableOperation === 'ENABLE' ? 'bg-cyan-600 hover:bg-cyan-700' : 'bg-amber-600 hover:bg-amber-700'}`}
              >{disableSubmitting
                ? (disableOperation === 'ENABLE' ? (zh ? '正在启用...' : 'Enabling...') : (zh ? '正在停用...' : 'Disabling...'))
                : (disableOperation === 'ENABLE' ? (zh ? '确认启用作业' : 'Confirm enable') : (zh ? '确认停用作业' : 'Confirm disable'))}</button>
            </div>
          </div>
        </div>
      )}

      {/* --- Delete Approval Modal --- */}
      <DeleteApprovalModal
        isOpen={deleteApprovalOpen}
        onClose={() => setDeleteApprovalOpen(false)}
        deleteTarget={deleteTarget}
        deleteReason={deleteReason}
        setDeleteReason={setDeleteReason}
        deleteApprover={deleteApprover}
        setDeleteApprover={selectDeleteApprover}
        deleteApprovalMethod={deleteApprovalMethod}
        setDeleteApprovalMethod={changeDeleteApprovalMethod}
        deleteStatus={deleteStatus}
        deleteCountdown={deleteCountdown}
        deleteDeadline={deleteDeadline}
        onDeleteCountdownExpire={expireDeleteCountdown}
        deleteCode={deleteCode}
        setDeleteCode={setDeleteCode}
        deleteError={deleteError}
        setDeleteError={setDeleteError}
        approvers={approvers}
        approverLoadStatus={approverLoadStatus}
        refreshApprovers={fetchApprovers}
        requestDeleteApproval={requestDeleteApproval}
        verifyDeleteApproval={verifyDeleteApproval}
        executeDeleteJob={executeDeleteJob}
        language={language}
      />

      {/* --- Candidate IP / Device Selection Modal --- */}
      <CandidateModal
        isOpen={candidateModalOpen}
        onClose={() => setCandidateModalOpen(false)}
        candidateList={candidateList}
        toggleCandidateSelected={toggleCandidateSelected}
        toggleAllCandidates={toggleAllCandidates}
        confirmAddCandidates={confirmAddCandidates}
        language={language}
      />

      {bulkCollectionPlanOpen && (
        <BulkCollectionPlanModal
          language={language}
          onClose={() => setBulkCollectionPlanOpen(false)}
          onCreateScheduledJob={openScheduledJobForCollectionScope}
        />
      )}

    </div>
  );
};

export default ScheduledJobsTab;
