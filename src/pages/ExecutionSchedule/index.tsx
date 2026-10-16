import React, { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { CalendarClock, Plus, X, RotateCcw } from 'lucide-react';
import * as XLSX from 'xlsx';
import PageHero from '../../components/PageHero';
import { ActionButton } from '../../components/ui/ActionIconButton';
import { useSystem } from '../../hooks/useSystem';
import type { ExecutionScheduleTabProps, ScheduledJob, FormState, ValidatedDevice, EligibleApprover, UnifiedExecutionLog, InspSubTab, InspDetailTab, PlaybookExecutionApproval, ConfigBackupRunDetail, ConfigBackupRunDevice, BackupDetailStatus } from './types';
import { INITIAL_FORM } from './constants';
import { serializeTagFilter, EMPTY_TAG_FILTER } from '../../components/TagConditionPicker';
import { fmtDateTime } from './helpers';

// Components
import ScheduleEditor from './components/ScheduleEditor';
import ScheduleList from './components/ScheduleList';
import ScheduleDetail from './components/ScheduleDetail';
import HistoryList from './components/HistoryList';
import ExecutionDetail from './components/ExecutionDetail';
import CandidateModal from './components/CandidateModal';

type ExecutionScheduleOperation = 'CREATE' | 'ENABLE' | 'DISABLE' | 'DELETE';

interface ExecutionScheduleOperationManifest {
  operation: ExecutionScheduleOperation;
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

interface PendingScheduleOperation {
  operation: 'ENABLE' | 'DISABLE' | 'DELETE';
  job: ScheduledJob;
}

const normalizeCheckItems = (items: unknown): string[] => {
  const values = Array.isArray(items) ? items : String(items || '').split(/[,\n]+/);
  return values.map(item => String(item).trim()).filter(Boolean);
};

const normalizeExecutionHistoryItem = (item: any, zh: boolean): UnifiedExecutionLog => {
  const source: UnifiedExecutionLog['source'] = item?.source === 'config_backup'
    ? 'config_backup'
    : item?.source === 'playbook' ? 'playbook' : 'inspection';
  const triggerType: UnifiedExecutionLog['trigger_type'] = ['manual', 'plan', 'job'].includes(item?.trigger_type)
    ? item.trigger_type
    : 'manual';
  const id = String(item?.id || item?.backup_run_id || '');
  const endedAt = item?.ended_at || item?.completed_at || null;
  const durationMs = item?.duration_ms == null || item.duration_ms === '' ? null : Number(item.duration_ms);
  return {
    id,
    source,
    ...(source === 'config_backup' ? { backup_run_id: String(item?.backup_run_id || id) } : {}),
    started_at: String(item?.started_at || item?.created_at || ''),
    ended_at: endedAt == null ? null : String(endedAt),
    duration_ms: durationMs != null && Number.isFinite(durationMs) ? durationMs : null,
    trigger_type: triggerType,
    status: String(item?.status || 'unknown'),
    total_devices: Number(item?.total_devices || 0),
    success_count: Number(item?.success_count || 0),
    failed_count: Number(item?.failed_count || 0),
    partial_count: Number(item?.partial_count || 0),
    skipped_count: Number(item?.skipped_count || 0),
    created_by: String(item?.created_by || (source === 'inspection' ? 'system' : 'admin')),
    name: String(item?.name || item?.scenario_name || item?.schedule_name || (source === 'config_backup'
      ? (zh ? '配置备份批次' : 'Configuration backup batch')
      : source === 'playbook'
        ? (zh ? '快捷命令执行' : 'Quick Playbook')
        : (zh ? '网络巡检' : 'Network Inspection'))),
  };
};

const escapeHtml = (value: unknown): string => String(value ?? '')
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#39;');

const downloadBlob = (blob: Blob, filename: string) => {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
};

const sanitizeFilenameSegment = (value: unknown, fallback: string, maxLength = 72) => {
  const sanitized = String(value ?? '')
    .normalize('NFKC')
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_')
    .replace(/\s+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^[._]+|[._]+$/g, '')
    .slice(0, maxLength);
  return sanitized || fallback;
};

const formatFilenameTimestamp = (value?: string | null) => {
  const parsed = value ? new Date(value) : new Date();
  const date = Number.isNaN(parsed.getTime()) ? new Date() : parsed;
  const twoDigits = (part: number) => String(part).padStart(2, '0');
  return `${date.getFullYear()}${twoDigits(date.getMonth() + 1)}${twoDigits(date.getDate())}_${twoDigits(date.getHours())}${twoDigits(date.getMinutes())}${twoDigits(date.getSeconds())}`;
};

const buildExecutionReportFilename = ({
  systemName,
  source,
  taskName,
  startedAt,
  runId,
  extension,
  zh,
}: {
  systemName?: string;
  source: string;
  taskName?: string;
  startedAt?: string | null;
  runId: string;
  extension: string;
  zh: boolean;
}) => {
  const reportType = source === 'config_backup'
    ? (zh ? '配置备份' : 'ConfigBackup')
    : source === 'playbook'
      ? (zh ? '自动化作业' : 'AutomationJob')
      : (zh ? '网络巡检' : 'NetworkInspection');
  const shortId = sanitizeFilenameSegment(String(runId || '').replace(/-/g, '').slice(0, 8), 'record', 8);
  return [
    sanitizeFilenameSegment(systemName, 'Nexora', 40),
    reportType,
    sanitizeFilenameSegment(taskName, zh ? '未命名作业' : 'UntitledJob'),
    formatFilenameTimestamp(startedAt),
    shortId,
  ].join('_') + `.${sanitizeFilenameSegment(extension, 'xlsx', 8).toLowerCase()}`;
};

const ExecutionScheduleCoordinator: React.FC<ExecutionScheduleTabProps> = ({
  language,
  showToast,
  initialTab,
  devices,
  onRerun,
}) => {
  const { systemInfo } = useSystem();
  const navigate = useNavigate();
  const zh = language === 'zh';

  /* ═══ STATE ═══ */
  const [inspSchedules, setInspSchedules] = useState<ScheduledJob[]>([]);
  const [inspSchedulesLoading, setInspSchedulesLoading] = useState(false);
  const [inspSchedulesError, setInspSchedulesError] = useState('');
  const [inspSchedulePage, setInspSchedulePage] = useState(1);
  const [inspSchedulePageSize, setInspSchedulePageSize] = useState(10);
  const [inspScheduleTotal, setInspScheduleTotal] = useState(0);
  const [showAddInspSchedule, setShowAddInspSchedule] = useState(false);
  const [form, setForm] = useState<FormState>({ ...INITIAL_FORM });

  // IP validation state
  const [ipDevices, setIpDevices] = useState<ValidatedDevice[]>([]);
  const [ipInput, setIpInput] = useState('');
  const [ipValidating, setIpValidating] = useState(false);
  const [ipError, setIpError] = useState('');
  const [tagFilter, setTagFilter] = useState<any>({ ...EMPTY_TAG_FILTER });

  // Candidate IP / Device Selection modal
  const [candidateModalOpen, setCandidateModalOpen] = useState(false);
  const [candidateList, setCandidateList] = useState<Array<{ ip: string; hostname: string; tags: any[]; selected: boolean }>>([]);
  const [candidateSearching, setCandidateSearching] = useState(false);

  // Script selection
  const [availableScripts, setAvailableScripts] = useState<{ id: string; name: string; status: string; category: string }[]>([]);
  const [scriptSearch, setScriptSearch] = useState('');
  const [showScriptDropdown, setShowScriptDropdown] = useState(false);

  const [inspectionItems, setInspectionItems] = useState<any[]>([]);
  const [inspectionItemsLoading, setInspectionItemsLoading] = useState(false);

  const [selectedSchedule, setSelectedSchedule] = useState<ScheduledJob | null>(null);
  const [showScheduleDetail, setShowScheduleDetail] = useState(false);

  const [inspRunsLoading, setInspRunsLoading] = useState(false);
  const [inspRunsError, setInspRunsError] = useState('');
  const [inspRunPage, setInspRunPage] = useState(1);
  const [inspRunPageSize, setInspRunPageSize] = useState(10);
  const [inspRunTotal, setInspRunTotal] = useState(0);
  const [inspSubTab, setInspSubTab] = useState<InspSubTab>(initialTab || 'schedules');

  // Future projections filter states
  const [timeRange, setTimeRange] = useState<'1h' | '4h' | '12h' | '1d' | '3d' | 'custom'>('1d');
  const [nameFilterInput, setNameFilterInput] = useState('');
  const [searchName, setSearchName] = useState('');
  const [customStart, setCustomStart] = useState('');
  const [customEnd, setCustomEnd] = useState('');
  const futureSchedulesControllerRef = useRef<AbortController | null>(null);
  const executionHistoryControllerRef = useRef<AbortController | null>(null);
  const backupDetailRequestRef = useRef<AbortController | null>(null);
  const selectedLogRequestIdRef = useRef(0);

  // Unified execution history states
  const [unifiedLogs, setUnifiedLogs] = useState<UnifiedExecutionLog[]>([]);
  const [executionTypeFilter, setExecutionTypeFilter] = useState<'all' | 'manual' | 'plan' | 'job'>('all');
  const [executionHistorySearch, setExecutionHistorySearch] = useState('');

  const [selectedLog, setSelectedLog] = useState<UnifiedExecutionLog | null>(null);
  const [isDetailModalOpen, setIsDetailModalOpen] = useState(false);
  const [logDetailLoading, setLogDetailLoading] = useState(false);
  const [backupRunDetail, setBackupRunDetail] = useState<ConfigBackupRunDetail | null>(null);
  const [backupRunError, setBackupRunError] = useState('');
  const [backupDevicePage, setBackupDevicePage] = useState(1);
  const [backupDeviceStatusFilter, setBackupDeviceStatusFilter] = useState<BackupDetailStatus>('all');
  const [selectedInspDeviceId, setSelectedInspDeviceId] = useState<string | null>(null);
  const [collapsedCmds, setCollapsedCmds] = useState<Record<string, boolean>>({});
  
  // TextFSM parse state for inspection command blocks
  const [inspParseResults, setInspParseResults] = useState<Record<string, { loading: boolean; data: any; error: string }>>({});
  const [inspCopiedKey, setInspCopiedKey] = useState<string | null>(null);
  const [inspDetailTab, setInspDetailTab] = useState<InspDetailTab>('analysis');
  const [inspParseViewMode, setInspParseViewMode] = useState<Record<string, 'raw' | 'parsed'>>({});
  
  // Trend chart state for analysis tab
  const [trendData, setTrendData] = useState<{ deviceId: string; metric: string; series: any[]; firstInspection?: boolean } | null>(null);
  const [trendLoading, setTrendLoading] = useState(false);
  
  const [inspectionDetail, setInspectionDetail] = useState<any>(null);
  const [pbDetail, setPbDetail] = useState<any>(null);
  const [pbDevices, setPbDevices] = useState<any[]>([]);
  const [selectedPbDevice, setSelectedPbDevice] = useState<any>(null);
  const [pbDeviceDetail, setPbDeviceDetail] = useState<any>(null);
  const [pbApprovals, setPbApprovals] = useState<PlaybookExecutionApproval[]>([]);
  const [pbApprovalsLoading, setPbApprovalsLoading] = useState(false);
  const [pbApprovalActionId, setPbApprovalActionId] = useState('');
  const [pbApprovalError, setPbApprovalError] = useState('');

  // Approval states
  const [approvers, setApprovers] = useState<EligibleApprover[]>([]);
  const [approverUsername, setApproverUsername] = useState('');
  const [approvalToken, setApprovalToken] = useState('');
  const [approvalCode, setApprovalCode] = useState('');
  const [approvalStatus, setApprovalStatus] = useState<'idle' | 'sending' | 'sent' | 'verified'>('idle');
  const [approvalError, setApprovalError] = useState('');
  const [approvalManifest, setApprovalManifest] = useState<ExecutionScheduleOperationManifest | null>(null);
  const [pendingScheduleOperation, setPendingScheduleOperation] = useState<PendingScheduleOperation | null>(null);
  const [operationApprovalReason, setOperationApprovalReason] = useState('');
  const [operationLoading, setOperationLoading] = useState(false);

  const authHeaders = useMemo(() => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' };
  }, []);

  /* ═══ FETCHERS ═══ */
  const fetchInspectionItems = useCallback(async () => {
    setInspectionItemsLoading(true);
    try {
      const r = await fetch('/api/inspections/items/all', { headers: authHeaders });
      if (r.ok) {
        const j = await r.json();
        setInspectionItems(j.items || []);
        if (form.check_items.length === 0 && j.items?.length > 0) {
          setForm(f => ({ ...f, check_items: j.items.map((i: any) => i.name) }));
        }
      }
    } catch { /* ignore */ }
    finally { setInspectionItemsLoading(false); }
  }, [authHeaders, form.check_items.length]);

  const fetchInspSchedules = useCallback(async () => {
    futureSchedulesControllerRef.current?.abort();
    const controller = new AbortController();
    futureSchedulesControllerRef.current = controller;
    setInspSchedulesLoading(true);
    setInspSchedulesError('');
    try {
      const params = new URLSearchParams();
      params.append('time_range', timeRange);
      params.append('page', String(inspSchedulePage));
      params.append('page_size', String(inspSchedulePageSize));
      if (searchName.trim()) {
        params.append('query', searchName.trim());
      }
      if (timeRange === 'custom') {
        if (customStart) {
          params.append('start_time', new Date(customStart).toISOString());
        }
        if (customEnd) {
          params.append('end_time', new Date(customEnd).toISOString());
        }
      }
      const r = await fetch(`/api/scheduled-jobs/future?${params.toString()}`, {
        headers: authHeaders,
        signal: controller.signal,
      });
      if (r.status === 401) {
        window.dispatchEvent(new Event('netops:auth-expired'));
        throw new Error(zh ? '登录状态已过期，请重新登录' : 'Your session has expired. Sign in again.');
      }
      if (r.status === 403) throw new Error(zh ? '没有查看执行计划的权限' : 'You do not have permission to view schedules.');
      if (!r.ok) throw new Error(zh ? `执行计划请求失败 (${r.status})` : `Schedule request failed (${r.status})`);
      const j = await r.json();
      const data = j.data || {};
      const items = Array.isArray(data.items) ? data.items : [];
      const total = Number(data.total || 0);
      if (!controller.signal.aborted) {
        setInspSchedules(items);
        setInspScheduleTotal(total);
        const lastPage = Math.max(1, Math.ceil(total / inspSchedulePageSize));
        if (inspSchedulePage > lastPage) setInspSchedulePage(lastPage);
      }
    } catch (cause) {
      if (!controller.signal.aborted) {
        setInspSchedules([]);
        setInspScheduleTotal(0);
        setInspSchedulesError(cause instanceof Error
          ? cause.message
          : (zh ? '加载执行计划失败，请重试' : 'Failed to load schedules. Try again.'));
      }
    }
    finally {
      if (!controller.signal.aborted) setInspSchedulesLoading(false);
    }
  }, [authHeaders, zh, timeRange, searchName, customStart, customEnd, inspSchedulePage, inspSchedulePageSize]);

  const fetchScripts = useCallback(async () => {
    if (!authHeaders) return;
    try {
      const r = await fetch('/api/scripts', { headers: authHeaders });
      if (r.ok) {
        const data = await r.json();
        const arr = Array.isArray(data) ? data : (data.items || data.data || []);
        setAvailableScripts(arr.map((s: any) => ({
          id: s.id, name: s.name, status: s.status, category: s.category || 'automation'
        })));
      }
    } catch { /* ignore */ }
  }, [authHeaders]);

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
        // 1) Search devices table
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
                  selected: true,
                };
              }
            }
          }
        }

        // 2) Fallback: search physical_assets table
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
                    candidatesMap[ip] = candidatesMap[ip] || { ip, hostname: a.hostname || '', tags: [], selected: true };
                  }
                }
              }
            }
          } catch { /* ignore */ }
        }

        // 3) If neither found
        if (!found && !ipDevices.some(existing => existing.ip === query)) {
          candidatesMap[query] = candidatesMap[query] || { ip: query, hostname: '', tags: [], selected: true };
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
          next.push({ ip: c.ip, hostname: c.hostname, tags: c.tags });
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

  const resolveFilter = (): string => {
    if (form.device_scope === 'tag') return serializeTagFilter(tagFilter);
    if (form.device_scope === 'ip') return ipDevices.map(d => d.ip).join(',');
    return form.device_filter;
  };

  const buildFormOperationManifest = (): ExecutionScheduleOperationManifest => {
    const action = form.action_type.trim();
    const checkItems = action === 'inspection' ? normalizeCheckItems(form.check_items) : [];
    const commands = action === 'inspection' && checkItems.length > 0
      ? checkItems.join(',')
      : form.commands;
    return {
      operation: 'CREATE',
      job_id: '',
      job_type: 'once',
      name: form.name.trim(),
      action,
      scope: { type: form.device_scope.trim(), filter: resolveFilter().trim() },
      cron_expr: '',
      scheduled_at: form.scheduled_at.trim(),
      check_items: checkItems,
      commands,
      script_id: form.script_id.trim(),
      is_config: form.is_config ? 1 : 0,
      use_admin_creds: form.use_admin_creds ? 1 : 0,
      enabled: true,
      config_reason: form.config_reason.trim(),
    };
  };

  const buildJobOperationManifest = (
    operation: ExecutionScheduleOperation,
    job: ScheduledJob,
  ): ExecutionScheduleOperationManifest => {
    const action = String(job.action_type || '').trim();
    const checkItems = action === 'inspection' ? normalizeCheckItems(job.check_items) : [];
    const commands = action === 'inspection' && checkItems.length > 0
      ? checkItems.join(',')
      : String(job.commands || '');
    return {
      operation,
      job_id: String(job.id),
      job_type: job.job_type === 'cron' ? 'cron' : 'once',
      name: String(job.name || '').trim(),
      action,
      scope: {
        type: String(job.device_scope || '').trim(),
        filter: String(job.device_filter || '').trim(),
      },
      cron_expr: String(job.cron_expr || '').trim(),
      scheduled_at: String(job.scheduled_at || '').trim(),
      check_items: checkItems,
      commands,
      script_id: String(job.script_id || '').trim(),
      is_config: Number(job.is_config) === 1 ? 1 : 0,
      use_admin_creds: Number(job.use_admin_creds) === 1 ? 1 : 0,
      enabled: operation === 'ENABLE' ? true : operation === 'DISABLE' ? false : Number(job.enabled) === 1,
      config_reason: String(job.config_reason || '').trim(),
    };
  };

  const sameManifest = (left: ExecutionScheduleOperationManifest | null, right: ExecutionScheduleOperationManifest) =>
    left !== null && JSON.stringify(left) === JSON.stringify(right);

  const fetchInspRuns = useCallback(async () => {
    executionHistoryControllerRef.current?.abort();
    const controller = new AbortController();
    executionHistoryControllerRef.current = controller;
    setInspRunsLoading(true);
    setInspRunsError('');
    try {
      const params = new URLSearchParams({
        page: String(inspRunPage),
        page_size: String(inspRunPageSize),
        trigger_type: executionTypeFilter,
      });
      if (executionHistorySearch.trim()) params.set('query', executionHistorySearch.trim());
      const response = await fetch(`/api/inspections/execution-history?${params.toString()}`, {
        headers: authHeaders,
        signal: controller.signal,
      });
      if (response.status === 401) {
        window.dispatchEvent(new Event('netops:auth-expired'));
        throw new Error(zh ? '登录状态已过期，请重新登录' : 'Your session has expired. Sign in again.');
      }
      if (response.status === 403) throw new Error(zh ? '没有查看执行历史的权限' : 'You do not have permission to view execution history.');
      if (!response.ok) throw new Error(zh ? `执行历史请求失败 (${response.status})` : `Execution history request failed (${response.status})`);
      const payload = await response.json();
      const data = payload.data || payload;
      const items = Array.isArray(data.items) ? data.items : [];
      if (controller.signal.aborted) return;

      const logs: UnifiedExecutionLog[] = items.map((item: any) => normalizeExecutionHistoryItem(item, zh));
      const total = Number(data.total || 0);
      setUnifiedLogs(logs);
      setInspRunTotal(total);
      const lastPage = Math.max(1, Math.ceil(total / inspRunPageSize));
      if (inspRunPage > lastPage) setInspRunPage(lastPage);
    } catch (cause) {
      if (!controller.signal.aborted) {
        setUnifiedLogs([]);
        setInspRunTotal(0);
        setInspRunsError(cause instanceof Error
          ? cause.message
          : (zh ? '加载执行历史失败，请重试' : 'Failed to load execution history. Try again.'));
      }
    } finally {
      if (!controller.signal.aborted) setInspRunsLoading(false);
    }
  }, [authHeaders, zh, inspRunPage, inspRunPageSize, executionTypeFilter, executionHistorySearch]);

  const loadAllExecutionLogs = useCallback(async (): Promise<UnifiedExecutionLog[]> => {
    const allLogs: UnifiedExecutionLog[] = [];
    const pageSize = 100;
    let page = 1;
    let total = Number.POSITIVE_INFINITY;
    while (allLogs.length < total) {
      const params = new URLSearchParams({ page: String(page), page_size: String(pageSize), trigger_type: 'all' });
      const response = await fetch(`/api/inspections/execution-history?${params.toString()}`, { headers: authHeaders });
      if (response.status === 401) {
        window.dispatchEvent(new Event('netops:auth-expired'));
        throw new Error(zh ? '登录状态已过期，请重新登录' : 'Your session has expired. Sign in again.');
      }
      if (!response.ok) throw new Error(zh ? `执行历史导出失败 (${response.status})` : `Failed to load history for export (${response.status})`);
      const payload = await response.json();
      const data = payload.data || payload;
      const items = Array.isArray(data.items) ? data.items : [];
      allLogs.push(...items.map((item: any) => normalizeExecutionHistoryItem(item, zh)));
      const reportedTotal = data.total == null ? Number.NaN : Number(data.total);
      total = Number.isFinite(reportedTotal) ? reportedTotal : allLogs.length + (items.length === pageSize ? 1 : 0);
      if (items.length === 0 || allLogs.length >= total) break;
      page += 1;
    }
    return allLogs;
  }, [authHeaders, zh]);

  const handleExecutionTypeFilterChange = useCallback((filter: 'all' | 'manual' | 'plan' | 'job') => {
    setExecutionTypeFilter(filter);
    setInspRunPage(1);
  }, []);

  const handleExecutionHistorySearchChange = useCallback((query: string) => {
    setExecutionHistorySearch(query);
    setInspRunPage(1);
  }, []);

  const handleExecutionHistoryPageSizeChange = useCallback((pageSize: number) => {
    setInspRunPageSize(pageSize);
    setInspRunPage(1);
  }, []);

  const loadBackupRunDetails = useCallback(async (
    log: UnifiedExecutionLog,
    page = 1,
    status: BackupDetailStatus = 'all',
  ) => {
    const runId = log.backup_run_id || log.id;
    if (!runId || log.source !== 'config_backup') return;
    backupDetailRequestRef.current?.abort();
    const controller = new AbortController();
    backupDetailRequestRef.current = controller;
    setLogDetailLoading(true);
    setBackupRunError('');

    try {
      const params = new URLSearchParams({ page: String(page), page_size: '100', status });
      const response = await fetch(`/api/configs/backup-runs/${encodeURIComponent(runId)}?${params.toString()}`, {
        headers: authHeaders,
        signal: controller.signal,
      });
      if (response.status === 401) {
        window.dispatchEvent(new Event('netops:auth-expired'));
        throw new Error(zh ? '登录状态已过期，请重新登录' : 'Your session has expired. Sign in again.');
      }
      if (response.status === 403) {
        throw new Error(zh ? '没有查看此配置备份批次的权限' : 'You do not have permission to view this backup batch.');
      }
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = payload?.detail?.message || payload?.detail || payload?.message;
        throw new Error(typeof detail === 'string' ? detail : (zh ? `备份批次详情加载失败 (${response.status})` : `Failed to load backup batch details (${response.status})`));
      }
      if (controller.signal.aborted) return;
      const devices = Array.isArray(payload?.devices) ? payload.devices : [];
      setBackupRunDetail({
        run: payload?.run && typeof payload.run === 'object' ? payload.run : {},
        devices,
        total: Number(payload?.total ?? devices.length),
        page: Number(payload?.page ?? page),
        page_size: Number(payload?.page_size ?? 100),
      });
      setBackupDevicePage(Number(payload?.page ?? page));
      setBackupDeviceStatusFilter(status);
    } catch (cause) {
      if (controller.signal.aborted) return;
      setBackupRunDetail(null);
      setBackupRunError(cause instanceof Error
        ? cause.message
        : (zh ? '备份批次详情加载失败，请重试' : 'Failed to load backup batch details. Try again.'));
    } finally {
      if (backupDetailRequestRef.current === controller) setLogDetailLoading(false);
    }
  }, [authHeaders, zh]);

  // ESC to close the execution detail modal and the schedule detail modal
  useEffect(() => {
    if (!isDetailModalOpen && !showScheduleDetail) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        if (isDetailModalOpen) setIsDetailModalOpen(false);
        if (showScheduleDetail) setShowScheduleDetail(false);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [isDetailModalOpen, showScheduleDetail]);

  const handleSelectLog = async (log: UnifiedExecutionLog) => {
    const requestId = ++selectedLogRequestIdRef.current;
    backupDetailRequestRef.current?.abort();
    backupDetailRequestRef.current = null;
    setSelectedLog(log);
    setIsDetailModalOpen(true);
    setLogDetailLoading(true);
    setBackupRunDetail(null);
    setBackupRunError('');
    setBackupDevicePage(1);
    setBackupDeviceStatusFilter('all');
    setInspectionDetail(null);
    setPbDetail(null);
    setPbDevices([]);
    setSelectedPbDevice(null);
    setPbDeviceDetail(null);
    setPbApprovals([]);
    setPbApprovalError('');

    try {
      if (log.source === 'config_backup') {
        await loadBackupRunDetails(log, 1, 'all');
      } else if (log.source === 'inspection') {
        const resp = await fetch(`/api/inspections/${log.id}`, { headers: authHeaders });
        if (resp.ok && requestId === selectedLogRequestIdRef.current) {
          const j = await resp.json();
          setInspectionDetail(j.data);
          if (j.data?.results?.length > 0) {
            setSelectedInspDeviceId(j.data.results[0].device_id);
          }
        }
      } else {
        const pbResp = await fetch(`/api/playbooks/${log.id}`, { headers: authHeaders });
        if (pbResp.ok && requestId === selectedLogRequestIdRef.current) {
          const j = await pbResp.json();
          setPbDetail(j);
        }
        if (requestId !== selectedLogRequestIdRef.current) return;
        if (log.status === 'awaiting_approval') {
          setPbApprovalsLoading(true);
          try {
            const approvalResp = await fetch(`/api/playbooks/${log.id}/approvals`, { headers: authHeaders });
            if (approvalResp.ok) {
              const approvalPayload = await approvalResp.json();
              setPbApprovals(approvalPayload.data || []);
            } else {
              setPbApprovalError(zh ? '审批记录加载失败' : 'Failed to load approval gates');
            }
          } catch {
            setPbApprovalError(zh ? '审批记录加载失败' : 'Failed to load approval gates');
          } finally {
            setPbApprovalsLoading(false);
          }
        }
        const devResp = await fetch(`/api/playbooks/${log.id}/devices?page=1&page_size=100`, { headers: authHeaders });
        if (devResp.ok && requestId === selectedLogRequestIdRef.current) {
          const j = await devResp.json();
          const devs = Array.isArray(j) ? j : (j.items || []);
          setPbDevices(devs);
          if (devs.length > 0) {
            setSelectedPbDevice(devs[0].device_id);
            const detailResp = await fetch(`/api/playbooks/${log.id}/devices/${devs[0].device_id}`, { headers: authHeaders });
            if (detailResp.ok) {
              const dj = await detailResp.json();
              setPbDeviceDetail(dj);
            }
          }
        }
      }
    } catch (e) {
      console.error(e);
    } finally {
      if (requestId === selectedLogRequestIdRef.current) setLogDetailLoading(false);
    }
  };

  const handleBackupDeviceStatusFilterChange = (status: BackupDetailStatus) => {
    if (!selectedLog || selectedLog.source !== 'config_backup') return;
    setBackupDeviceStatusFilter(status);
    setBackupDevicePage(1);
    void loadBackupRunDetails(selectedLog, 1, status);
  };

  const handleBackupDevicePageChange = (page: number) => {
    if (!selectedLog || selectedLog.source !== 'config_backup') return;
    setBackupDevicePage(page);
    void loadBackupRunDetails(selectedLog, page, backupDeviceStatusFilter);
  };

  const closeExecutionDetail = () => {
    backupDetailRequestRef.current?.abort();
    backupDetailRequestRef.current = null;
    selectedLogRequestIdRef.current += 1;
    setIsDetailModalOpen(false);
  };

  useEffect(() => {
    if (!isDetailModalOpen) {
      backupDetailRequestRef.current?.abort();
      backupDetailRequestRef.current = null;
    }
  }, [isDetailModalOpen]);

  const handlePlaybookApproval = async (approval: PlaybookExecutionApproval, decision: 'approve' | 'reject') => {
    if (!selectedLog || selectedLog.source !== 'playbook' || approval.status !== 'PENDING') return;
    const reason = decision === 'reject' ? window.prompt(zh ? '请输入拒绝原因' : 'Reason for rejection') : '';
    if (decision === 'reject' && reason === null) return;
    setPbApprovalActionId(approval.id);
    setPbApprovalError('');
    try {
      const response = await fetch(`/api/playbooks/${encodeURIComponent(selectedLog.id)}/approvals/${encodeURIComponent(approval.id)}/${decision}`, {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({ reason: reason || '' }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload?.detail?.message || payload?.detail || (zh ? '审批操作失败' : 'Approval decision failed'));
      setPbApprovals((current) => current.map((item) => item.id === approval.id ? (payload.data?.approval || { ...item, status: decision === 'approve' ? 'APPROVED' : 'REJECTED' }) : item));
      const nextStatus = payload.data?.execution_status;
      if (nextStatus) setSelectedLog((current) => current ? { ...current, status: nextStatus } : current);
      await fetchInspRuns();
      showToast(zh ? (decision === 'approve' ? '审批已通过，执行已恢复' : '审批已拒绝') : (decision === 'approve' ? 'Approval granted; execution resumed' : 'Approval rejected'), decision === 'approve' ? 'success' : 'info');
    } catch (cause) {
      setPbApprovalError(cause instanceof Error ? cause.message : (zh ? '审批操作失败' : 'Approval decision failed'));
    } finally {
      setPbApprovalActionId('');
      setPbApprovalsLoading(false);
    }
  };

  const toggleCmdCollapse = (cmd: string) => {
    setCollapsedCmds(prev => ({ ...prev, [cmd]: !prev[cmd] }));
  };

  const expandAllCmds = (cmds: string[]) => {
    const next: Record<string, boolean> = {};
    cmds.forEach(c => next[c] = false);
    setCollapsedCmds(next);
  };

  const collapseAllCmds = (cmds: string[]) => {
    const next: Record<string, boolean> = {};
    cmds.forEach(c => next[c] = true);
    setCollapsedCmds(next);
  };

  /** Parse a single inspection command output via TextFSM */
  const handleParseInspCmd = useCallback(async (
    blockKey: string,
    platform: string,
    command: string,
    rawOutput: string,
  ) => {
    setInspParseResults(prev => ({ ...prev, [blockKey]: { loading: true, data: null, error: '' } }));
    setInspParseViewMode(prev => ({ ...prev, [blockKey]: 'parsed' }));
    try {
      const res = await fetch('/api/inspections/parse-output', {
        method: 'POST',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform, command, output: rawOutput }),
      });
      const json = await res.json();
      if (json.success && json.data?.count > 0) {
        setInspParseResults(prev => ({ ...prev, [blockKey]: { loading: false, data: json.data, error: '' } }));
      } else if (json.has_template === false) {
        setInspParseResults(prev => ({ ...prev, [blockKey]: { loading: false, data: null, error: zh ? `未找到 ${platform} / ${command} 的解析模板` : `No template for ${platform} / ${command}` } }));
      } else {
        setInspParseResults(prev => ({ ...prev, [blockKey]: { loading: false, data: null, error: json.message || (zh ? '解析无结果' : 'No parse results') } }));
      }
    } catch {
      setInspParseResults(prev => ({ ...prev, [blockKey]: { loading: false, data: null, error: zh ? '解析请求失败' : 'Parse request failed' } }));
    }
  }, [authHeaders, zh]);

  /** R5.6: Fetch metric trend for a device */
  const fetchTrend = useCallback(async (deviceId: string, metric: string) => {
    setTrendLoading(true);
    try {
      const resp = await fetch(`/api/inspections/device/${deviceId}/trend?metric=${encodeURIComponent(metric)}&days=30`, { headers: authHeaders });
      if (resp.ok) {
        const j = await resp.json();
        setTrendData({
          deviceId,
          metric,
          series: j.series || [],
          firstInspection: j.first_inspection,
        });
      } else {
        setTrendData({ deviceId, metric, series: [] });
      }
    } catch {
      setTrendData({ deviceId, metric, series: [] });
    } finally {
      setTrendLoading(false);
    }
  }, [authHeaders]);

  const handleSelectPbDevice = async (device_id: string) => {
    setSelectedPbDevice(device_id);
    setPbDeviceDetail(null);
    try {
      const resp = await fetch(`/api/playbooks/${selectedLog?.id}/devices/${device_id}`, { headers: authHeaders });
      if (resp.ok) {
        const j = await resp.json();
        setPbDeviceDetail(j);
      }
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    if (initialTab) setInspSubTab(initialTab);
    setInspRunPage(1);
    setInspSchedulePage(1);
  }, [initialTab]);

  useEffect(() => {
    if (inspSubTab !== 'schedules') return;
    fetchInspSchedules();
    return () => futureSchedulesControllerRef.current?.abort();
  }, [inspSubTab, fetchInspSchedules]);

  useEffect(() => {
    if (inspSubTab !== 'history') return;
    fetchInspRuns();
    return () => executionHistoryControllerRef.current?.abort();
  }, [inspSubTab, fetchInspRuns]);

  useEffect(() => {
    fetchInspectionItems();
  }, [fetchInspectionItems]);

  const fetchApprovers = useCallback(async () => {
    try {
      const r = await fetch('/api/config-approval/approvers', { headers: authHeaders });
      if (r.ok) {
        const j = await r.json();
        const users = Array.isArray(j) ? j : (Array.isArray(j.data) ? j.data : []);
        setApprovers(users);
      }
    } catch { /* ignore */ }
  }, [authHeaders]);

  useEffect(() => {
    if (showAddInspSchedule || pendingScheduleOperation) fetchApprovers();
  }, [showAddInspSchedule, pendingScheduleOperation, fetchApprovers]);

  /* ═══ APPROVAL ═══ */
  const resetApproval = () => {
    setApprovalStatus('idle');
    setApproverUsername('');
    setApprovalToken('');
    setApprovalCode('');
    setApprovalError('');
    setApprovalManifest(null);
  };

  const requestApproval = async () => {
    if (!approverUsername) return;
    const operationManifest = pendingScheduleOperation
      ? buildJobOperationManifest(pendingScheduleOperation.operation, pendingScheduleOperation.job)
      : buildFormOperationManifest();
    const defaultReason = pendingScheduleOperation
      ? `${pendingScheduleOperation.operation === 'ENABLE'
        ? (zh ? '启用执行计划' : 'Enable execution schedule')
        : pendingScheduleOperation.operation === 'DISABLE'
          ? (zh ? '停用执行计划' : 'Disable execution schedule')
          : (zh ? '删除执行计划' : 'Delete execution schedule')}: ${operationManifest.name}`
      : `${zh ? '创建执行计划' : 'Create execution schedule'}: ${operationManifest.name}`;
    const configReason = pendingScheduleOperation
      ? operationApprovalReason.trim() || defaultReason
      : operationManifest.config_reason || defaultReason;
    setApprovalStatus('sending');
    setApprovalError('');
    try {
      const r = await fetch('/api/config-approval/request', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({
          approver_username: approverUsername,
          config_reason: configReason,
          device_hostname: operationManifest.scope.type === 'all'
            ? (zh ? '全部设备' : 'All devices')
            : (operationManifest.scope.filter || operationManifest.scope.type),
          command_preview: operationManifest.commands || operationManifest.check_items.join(','),
          approval_type: 'execution_plan',
          operation_manifest: operationManifest,
          extra_fields: {
            action_type: operationManifest.action,
            schedule_desc: operationManifest.scheduled_at ? fmtDateTime(operationManifest.scheduled_at, zh) : (zh ? '未设定' : 'Not set'),
            operation: operationManifest.operation,
          },
        }),
      });
      const j = await r.json();
      if (r.ok && j.success) {
        setApprovalToken(j.approval_token);
        setApprovalManifest(operationManifest);
        setApprovalStatus('sent');
        showToast(zh ? '验证码已发送至审批人' : 'Code sent to approver', 'success');
      } else {
        setApprovalStatus('idle');
        setApprovalError(j.detail || j.message || 'Failed');
      }
    } catch {
      setApprovalStatus('idle');
      setApprovalError(zh ? '发送验证码失败' : 'Failed to send code');
    }
  };

  const verifyApproval = async () => {
    if (!approvalToken || !approvalCode || !approvalManifest) return;
    try {
      const r = await fetch('/api/config-approval/verify', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({ approval_token: approvalToken, code: approvalCode, approval_type: 'execution_plan', operation_manifest: approvalManifest }),
      });
      const j = await r.json();
      if (r.ok && j.success) {
        setApprovalStatus('verified');
        showToast(zh ? '审批验证通过' : 'Approval verified', 'success');
      } else {
        setApprovalError(j.detail || j.message || 'Invalid code');
      }
    } catch {
      setApprovalError(zh ? '验证失败' : 'Verification failed');
    }
  };

  /* ═══ ACTIONS ═══ */
  const addInspSchedule = async () => {
    if (!form.name.trim() || !form.scheduled_at) {
      showToast(zh ? '请填写计划名称和执行时间' : 'Name and execution time are required', 'error');
      return;
    }
    if (form.action_type === 'script_run' && !form.script_id) {
      showToast(zh ? '请选择一个要执行的脚本' : 'Please select a script to execute', 'error');
      return;
    }
    if (approvalStatus !== 'verified') {
      showToast(zh ? '请先发送验证码并完成审批验证' : 'Please complete approval verification first', 'error');
      return;
    }
    try {
      const operationManifest = buildFormOperationManifest();
      if (!sameManifest(approvalManifest, operationManifest)) {
        resetApproval();
        showToast(zh ? '计划配置已变化，请重新申请审批' : 'The schedule configuration changed. Request approval again.', 'error');
        return;
      }
      const payload = {
        name: operationManifest.name,
        action_type: operationManifest.action,
        job_type: operationManifest.job_type,
        scheduled_at: operationManifest.scheduled_at,
        cron_expr: operationManifest.cron_expr,
        device_scope: operationManifest.scope.type,
        device_filter: operationManifest.scope.filter,
        script_id: operationManifest.script_id,
        commands: operationManifest.commands,
        is_config: operationManifest.is_config,
        config_reason: operationManifest.config_reason,
        use_admin_creds: operationManifest.use_admin_creds,
        enabled: operationManifest.enabled,
        approval_token: approvalToken,
        approval_code: approvalCode,
        description: form.description.trim(),
        check_items: operationManifest.check_items,
        operation_manifest: operationManifest,
      };

      const r = await fetch('/api/scheduled-jobs', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify(payload),
      });
      if (r.ok) {
        setShowAddInspSchedule(false);
        setForm({ ...INITIAL_FORM });
        setIpDevices([]);
        setTagFilter({ ...EMPTY_TAG_FILTER });
        resetApproval();
        setOperationApprovalReason('');
        setInspSchedulePage(1);
        fetchInspSchedules();
        showToast(zh ? '执行计划已创建' : 'Execution schedule created', 'success');
      } else {
        const j = await r.json();
        showToast(j.detail || j.message || 'Failed', 'error');
      }
    } catch {
      showToast(zh ? '创建失败' : 'Create failed', 'error');
    }
  };

  const deleteInspSchedule = async (id: string) => {
    await startScheduleOperation('DELETE', id);
  };

  const fetchScheduleForOperation = async (id: string): Promise<ScheduledJob | null> => {
    setOperationLoading(true);
    try {
      const response = await fetch(`/api/scheduled-jobs/${encodeURIComponent(id)}`, { headers: authHeaders });
      const payload = await response.json().catch(() => null) as { success?: boolean; data?: ScheduledJob; detail?: string; message?: string } | null;
      if (!response.ok || !payload?.data) {
        throw new Error(payload?.detail || payload?.message || (zh ? '无法读取当前计划配置。' : 'Unable to load the current schedule details.'));
      }
      return payload.data;
    } catch (cause) {
      showToast(cause instanceof Error ? cause.message : (zh ? '无法读取当前计划配置。' : 'Unable to load the current schedule details.'), 'error');
      return null;
    } finally {
      setOperationLoading(false);
    }
  };

  const startScheduleOperation = async (operation: 'ENABLE' | 'DISABLE' | 'DELETE', id: string) => {
    const job = await fetchScheduleForOperation(id);
    if (!job) return;
    const currentOperation = operation === 'DELETE' ? 'DELETE' : Number(job.enabled) ? 'DISABLE' : 'ENABLE';
    resetApproval();
    setOperationApprovalReason(`${currentOperation === 'ENABLE'
      ? (zh ? '启用执行计划' : 'Enable execution schedule')
      : currentOperation === 'DISABLE'
        ? (zh ? '停用执行计划' : 'Disable execution schedule')
        : (zh ? '删除执行计划' : 'Delete execution schedule')}: ${job.name}`);
    setPendingScheduleOperation({ operation: currentOperation, job });
    setShowScheduleDetail(false);
  };

  const executePendingScheduleOperation = async () => {
    if (!pendingScheduleOperation || approvalStatus !== 'verified') return;
    const { operation, job } = pendingScheduleOperation;
    const operationManifest = buildJobOperationManifest(operation, job);
    if (!sameManifest(approvalManifest, operationManifest)) {
      resetApproval();
      setApprovalError(zh ? '计划信息已变化，请重新申请审批。' : 'The schedule details changed. Request approval again.');
      return;
    }
    setOperationLoading(true);
    setApprovalError('');
    try {
      const url = operation === 'DELETE'
        ? `/api/scheduled-jobs/${encodeURIComponent(job.id)}?approval_token=${encodeURIComponent(approvalToken)}&approval_code=${encodeURIComponent(approvalCode)}`
        : `/api/scheduled-jobs/${encodeURIComponent(job.id)}/toggle`;
      const response = await fetch(url, {
        method: operation === 'DELETE' ? 'DELETE' : 'PUT',
        headers: authHeaders,
        body: JSON.stringify(operation === 'DELETE'
          ? { operation_manifest: operationManifest }
          : { enabled: operation === 'ENABLE', approval_token: approvalToken, approval_code: approvalCode, operation_manifest: operationManifest }),
      });
      const payload = await response.json().catch(() => null) as { success?: boolean; detail?: string; message?: string } | null;
      if (!response.ok || payload?.success === false) {
        throw new Error(payload?.detail || payload?.message || (zh ? '操作失败。' : 'Operation failed.'));
      }
      setPendingScheduleOperation(null);
      setShowScheduleDetail(false);
      resetApproval();
      setOperationApprovalReason('');
      fetchInspSchedules();
      showToast(operation === 'DELETE'
        ? (zh ? '计划已删除' : 'Schedule deleted')
        : operation === 'ENABLE'
          ? (zh ? '计划已启用' : 'Schedule enabled')
          : (zh ? '计划已停用' : 'Schedule disabled'), 'success');
    } catch (cause) {
      setApprovalError(cause instanceof Error ? cause.message : (zh ? '操作失败。' : 'Operation failed.'));
    } finally {
      setOperationLoading(false);
    }
  };

  const toggleInspScheduleEnabled = async (sch: ScheduledJob) => {
    await startScheduleOperation(Number(sch.enabled) ? 'DISABLE' : 'ENABLE', sch.job_id || sch.id);
  };

  const fetchAllBackupRunDeviceResults = async (runId: string): Promise<{ run: ConfigBackupRunDetail['run']; devices: ConfigBackupRunDevice[] }> => {
    const pageSize = 100;
    const devices: ConfigBackupRunDevice[] = [];
    let run: ConfigBackupRunDetail['run'] = {};
    let total = Number.POSITIVE_INFINITY;
    let page = 1;
    while (devices.length < total) {
      const params = new URLSearchParams({ page: String(page), page_size: String(pageSize), status: 'all' });
      const response = await fetch(`/api/configs/backup-runs/${encodeURIComponent(runId)}?${params.toString()}`, { headers: authHeaders });
      if (response.status === 401) {
        window.dispatchEvent(new Event('netops:auth-expired'));
        throw new Error(zh ? '登录状态已过期，请重新登录' : 'Your session has expired. Sign in again.');
      }
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = payload?.detail?.message || payload?.detail || payload?.message;
        throw new Error(typeof detail === 'string'
          ? detail
          : response.status === 403
            ? (zh ? '没有导出此配置备份批次的权限' : 'You do not have permission to export this backup batch.')
            : (zh ? `备份批次导出失败 (${response.status})` : `Failed to export backup batch (${response.status})`));
      }
      const data = payload?.data && Array.isArray(payload.data.devices) ? payload.data : payload;
      const pageItems = Array.isArray(data?.devices) ? data.devices as ConfigBackupRunDevice[] : [];
      if (data?.run && typeof data.run === 'object') run = data.run;
      devices.push(...pageItems);
      const reportedTotal = data?.total == null ? Number.NaN : Number(data.total);
      total = Number.isFinite(reportedTotal) ? reportedTotal : devices.length + (pageItems.length === pageSize ? 1 : 0);
      if (pageItems.length === 0 || devices.length >= total) break;
      page += 1;
    }
    return { run, devices };
  };

  const handleExportBackupRunReport = async (logId: string, format: string) => {
    const printWindow = format === 'pdf' ? window.open('', '_blank') : null;
    if (format === 'pdf' && !printWindow) {
      showToast(zh ? '浏览器拦截了打印窗口，请允许弹出窗口后重试' : 'The browser blocked the print window. Allow pop-ups and try again.', 'error');
      return;
    }
    try {
      const log = unifiedLogs.find((item) => item.source === 'config_backup' && (item.id === logId || item.backup_run_id === logId));
      const runId = log?.backup_run_id || log?.id || logId;
      const { run, devices: deviceResults } = await fetchAllBackupRunDeviceResults(runId);
      const backupLog = log || normalizeExecutionHistoryItem({ ...run, id: runId, source: 'config_backup' }, zh);
      const dateLabel = backupLog.started_at ? new Date(backupLog.started_at).toLocaleString(zh ? 'zh-CN' : 'en-US') : '--';
      const summary = zh
        ? {
          '批次 ID': runId,
          '批次名称': backupLog.name,
          '执行时间': dateLabel,
          '状态': backupLog.status,
          '总设备数': backupLog.total_devices,
          '成功设备数': backupLog.success_count,
          '失败设备数': backupLog.failed_count,
          '部分完成设备数': backupLog.partial_count || 0,
          '跳过设备数': backupLog.skipped_count || 0,
          '执行人': backupLog.created_by,
        }
        : {
          'Batch ID': runId,
          'Batch Name': backupLog.name,
          'Started At': dateLabel,
          'Status': backupLog.status,
          'Total Devices': backupLog.total_devices,
          'Successful Devices': backupLog.success_count,
          'Failed Devices': backupLog.failed_count,
          'Partial Devices': backupLog.partial_count || 0,
          'Skipped Devices': backupLog.skipped_count || 0,
          'Operator': backupLog.created_by,
        };
      const deviceRows = deviceResults.map((device) => {
        const isFailure = ['failed', 'unknown', 'unreachable', 'error'].includes(String(device.status || '').toLowerCase());
        const isSkipped = String(device.status || '').toLowerCase() === 'skipped';
        return zh
          ? {
            '设备名称': device.hostname || '--',
            '设备 ID': device.device_id || '--',
            'IP 地址': device.ip_address || '--',
            '状态': device.status || 'unknown',
            '原因': isFailure || isSkipped ? device.reason || '' : '',
            '详细说明': isFailure ? device.detail || '' : '',
            '耗时(ms)': device.duration_ms ?? '',
          }
          : {
            'Device': device.hostname || '--',
            'Device ID': device.device_id || '--',
            'IP Address': device.ip_address || '--',
            'Status': device.status || 'unknown',
            'Reason': isFailure || isSkipped ? device.reason || '' : '',
            'Detail': isFailure ? device.detail || '' : '',
            'Duration (ms)': device.duration_ms ?? '',
          };
      });
      const deviceHeaders = zh
        ? ['设备名称', '设备 ID', 'IP 地址', '状态', '原因', '详细说明', '耗时(ms)']
        : ['Device', 'Device ID', 'IP Address', 'Status', 'Reason', 'Detail', 'Duration (ms)'];
      const reportHtml = `<!doctype html><html><head><meta charset="utf-8"><title>${escapeHtml(backupLog.name)}</title><style>body{font:13px Arial,sans-serif;color:#172033;margin:28px}h1{font-size:20px}h2{font-size:15px;margin-top:28px}table{width:100%;border-collapse:collapse;margin-top:10px}th,td{border:1px solid #d8dee9;padding:7px;text-align:left;vertical-align:top;word-break:break-word}th{background:#f1f5f9} @media print{body{margin:12mm}tr{break-inside:avoid}}</style></head><body><h1>${escapeHtml(backupLog.name)}</h1><h2>${zh ? '批次汇总' : 'Batch summary'}</h2><table><thead><tr>${Object.keys(summary).map((key) => `<th>${escapeHtml(key)}</th>`).join('')}</tr></thead><tbody><tr>${Object.values(summary).map((value) => `<td>${escapeHtml(value)}</td>`).join('')}</tr></tbody></table><h2>${zh ? '设备结果' : 'Device results'} (${deviceRows.length})</h2><table><thead><tr>${deviceHeaders.map((key) => `<th>${escapeHtml(key)}</th>`).join('')}</tr></thead><tbody>${deviceRows.map((row) => `<tr>${Object.values(row).map((value) => `<td>${escapeHtml(value)}</td>`).join('')}</tr>`).join('')}</tbody></table></body></html>`;
      const reportFilename = buildExecutionReportFilename({
        systemName: systemInfo?.system_name,
        source: 'config_backup',
        taskName: backupLog.name,
        startedAt: backupLog.started_at,
        runId,
        extension: format,
        zh,
      });
      const prefix = reportFilename.slice(0, reportFilename.lastIndexOf('.'));

      if (format === 'xlsx') {
        const workbook = XLSX.utils.book_new();
        XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet([summary]), zh ? '批次汇总' : 'Batch Summary');
        XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(deviceRows, { header: deviceHeaders }), zh ? '设备结果' : 'Device Results');
        XLSX.writeFile(workbook, `${prefix}.xlsx`);
      } else if (format === 'json') {
        downloadBlob(new Blob([JSON.stringify({ batch: summary, devices: deviceRows }, null, 2)], { type: 'application/json;charset=utf-8' }), `${prefix}.json`);
      } else if (format === 'html') {
        downloadBlob(new Blob([reportHtml], { type: 'text/html;charset=utf-8' }), `${prefix}.html`);
      } else if (format === 'pdf' && printWindow) {
        printWindow.document.open();
        printWindow.document.write(reportHtml);
        printWindow.document.close();
        window.setTimeout(() => { printWindow.focus(); printWindow.print(); }, 300);
      }
    } catch (cause) {
      printWindow?.close();
      console.error('Config backup batch export failed:', cause);
      showToast(cause instanceof Error ? cause.message : (zh ? `${format.toUpperCase()} 导出失败` : `${format.toUpperCase()} export failed`), 'error');
    }
  };

  const handleExportReport = async (
    logId: string,
    format: string,
    source: string = 'inspection',
    taskName = '',
    startedAt?: string,
  ) => {
    if (source === 'config_backup') {
      await handleExportBackupRunReport(logId, format);
      return;
    }
    try {
      const sourceParam = source === 'playbook' ? '&source=playbook' : '';
      const resp = await fetch(`/api/inspections/${logId}/export?format=${format}${sourceParam}`, { headers: authHeaders });
      if (resp.ok) {
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const ext = format === 'xlsx' ? 'xlsx' : format === 'html' ? 'html' : format === 'pdf' ? 'pdf' : 'json';
        a.download = buildExecutionReportFilename({
          systemName: systemInfo?.system_name,
          source,
          taskName,
          startedAt,
          runId: logId,
          extension: ext,
          zh,
        });
        a.click();
        URL.revokeObjectURL(url);
      } else {
        showToast(zh ? `${format.toUpperCase()} 导出失败 (${resp.status})` : `${format.toUpperCase()} export failed (${resp.status})`, 'error');
      }
    } catch (err) {
      console.error(`Export ${format} failed:`, err);
      showToast(zh ? `${format.toUpperCase()} 导出异常` : `${format.toUpperCase()} export error`, 'error');
    }
  };

  const copyInspText = (text: string, key: string) => {
    navigator.clipboard.writeText(text).catch(() => {
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    });
    setInspCopiedKey(key);
    setTimeout(() => setInspCopiedKey(null), 2000);
  };

  /* ═══ RENDER ═══ */
  return (
    <div className="nx-page-shell flex h-full flex-col overflow-hidden">
      <PageHero
        icon={CalendarClock}
        title={inspSubTab === 'history'
          ? (zh ? '执行历史' : 'Execution History')
          : (zh ? '执行计划' : 'Execution Schedules')}
        subtitle={inspSubTab === 'history'
          ? (zh ? '查看和追溯自动化执行历史' : 'View and trace automation execution history')
          : (zh ? '创建指定时间范围内执行的一次性巡检计划' : 'Create one-time inspection plans within a specified time window')}
        actions={
          <>
            {inspSubTab === 'schedules' && (
              <ActionButton
                onClick={() => setShowAddInspSchedule(!showAddInspSchedule)}
                icon={showAddInspSchedule ? X : Plus}
                variant={showAddInspSchedule ? 'default' : 'primary'}
                size="md"
              >
                {showAddInspSchedule ? (zh ? '取消新建' : 'Cancel') : (zh ? '新建计划' : 'Add Schedule')}
              </ActionButton>
            )}
            {inspSubTab === 'history' && (
              <ActionButton
                onClick={fetchInspRuns}
                disabled={inspRunsLoading}
                icon={RotateCcw}
                iconClassName={inspRunsLoading ? 'animate-spin' : undefined}
                variant="accent"
                size="md"
              >
                {zh ? '刷新记录' : 'Refresh'}
              </ActionButton>
            )}
          </>
        }
      />

      <div className={`flex-1 min-h-0 overflow-auto px-6 py-5 space-y-4 ${inspSubTab === 'history' ? 'flex flex-col' : ''}`}>
        {/* Schedules sub-tab */}
        {inspSubTab === 'schedules' && (
          <div className="space-y-4">
            {showAddInspSchedule ? (
              <ScheduleEditor
                zh={zh}
                language={language}
                form={form}
                setForm={setForm}
                ipInput={ipInput}
                setIpInput={setIpInput}
                ipDevices={ipDevices}
                ipValidating={ipValidating}
                ipError={ipError}
                setIpError={setIpError}
                onValidateIps={validateAndAddIps}
                onRemoveIpDevice={removeIpDevice}
                tagFilter={tagFilter}
                setTagFilter={setTagFilter}
                availableScripts={availableScripts}
                scriptSearch={scriptSearch}
                setScriptSearch={setScriptSearch}
                showScriptDropdown={showScriptDropdown}
                setShowScriptDropdown={setShowScriptDropdown}
                onFetchScripts={fetchScripts}
                inspectionItems={inspectionItems}
                inspectionItemsLoading={inspectionItemsLoading}
                approvers={approvers}
                approverUsername={approverUsername}
                setApproverUsername={setApproverUsername}
                approvalStatus={approvalStatus}
                approvalError={approvalError}
                approvalCode={approvalCode}
                setApprovalCode={setApprovalCode}
                setApprovalError={setApprovalError}
                onRequestApproval={requestApproval}
                onVerifyApproval={verifyApproval}
                onResetApproval={resetApproval}
                onSubmit={addInspSchedule}
                onCancel={() => setShowAddInspSchedule(false)}
              />
            ) : (
              <>
                {/* Future Run projections filter bar */}
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-4 rounded-2xl border border-black/5 bg-white shadow-sm">
                  <div className="flex flex-wrap items-center gap-3">
                    {/* Name search */}
                    <div className="relative">
                      <input
                        type="search"
                        placeholder={zh ? '搜索计划名称...' : 'Search by name...'}
                        value={nameFilterInput}
                        onChange={(e) => setNameFilterInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            setInspSchedulePage(1);
                            setSearchName(nameFilterInput);
                          }
                        }}
                        className="px-3 py-1.5 w-44 text-xs rounded-xl border border-slate-200 focus:outline-none focus:border-cyan-500 transition-all font-medium placeholder-slate-400 text-[#1e293b]"
                      />
                    </div>

                    {/* Time range buttons */}
                    <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-xl">
                      {(['1h', '4h', '12h', '1d', '3d', 'custom'] as const).map((r) => (
                        <button
                          key={r}
                          type="button"
                          onClick={() => {
                            setInspSchedulePage(1);
                            setTimeRange(r);
                            if (r !== 'custom') {
                              setCustomStart('');
                              setCustomEnd('');
                            }
                          }}
                          className={`px-3 py-1 rounded-lg text-xs font-bold transition-all ${
                            timeRange === r
                              ? 'bg-white text-cyan-600 shadow-sm'
                              : 'text-slate-500 hover:text-slate-700'
                          }`}
                        >
                          {r === '1h' ? (zh ? '1小时' : '1 Hour') :
                           r === '4h' ? (zh ? '4小时' : '4 Hours') :
                           r === '12h' ? (zh ? '12小时' : '12 Hours') :
                           r === '1d' ? (zh ? '1天' : '1 Day') :
                           r === '3d' ? (zh ? '3天' : '3 Days') :
                           (zh ? '自定义' : 'Custom')}
                        </button>
                      ))}
                    </div>

                    {/* Custom time picker */}
                    {timeRange === 'custom' && (
                      <div className="flex items-center gap-2 animate-fadeIn">
                        <input
                          type="datetime-local"
                          value={customStart}
                          onChange={(e) => {
                            setInspSchedulePage(1);
                            setCustomStart(e.target.value);
                          }}
                          className="px-2 py-1 text-xs rounded-xl border border-slate-200 focus:outline-none focus:border-cyan-500 font-mono text-[#1e293b]"
                        />
                        <span className="text-slate-400 text-xs">—</span>
                        <input
                          type="datetime-local"
                          value={customEnd}
                          onChange={(e) => {
                            setInspSchedulePage(1);
                            setCustomEnd(e.target.value);
                          }}
                          className="px-2 py-1 text-xs rounded-xl border border-slate-200 focus:outline-none focus:border-cyan-500 font-mono text-[#1e293b]"
                        />
                      </div>
                    )}
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => {
                        setInspSchedulePage(1);
                        setSearchName(nameFilterInput);
                      }}
                      className="px-4 py-1.5 rounded-xl text-xs font-bold text-white bg-cyan-600 hover:bg-cyan-500 transition-all active:scale-[0.97]"
                    >
                      {zh ? '查询' : 'Query'}
                    </button>
                    <button
                      onClick={() => {
                        setInspSchedulePage(1);
                        setNameFilterInput('');
                        setSearchName('');
                        setTimeRange('1d');
                        setCustomStart('');
                        setCustomEnd('');
                      }}
                      className="px-3 py-1.5 rounded-xl text-xs font-bold border border-slate-200 text-slate-500 hover:bg-slate-50 transition-all active:scale-[0.97]"
                    >
                      {zh ? '重置' : 'Reset'}
                    </button>
                  </div>
                </div>

                <ScheduleList
                  zh={zh}
                  language={language}
                  schedules={inspSchedules}
                  loading={inspSchedulesLoading}
                  total={inspScheduleTotal}
                  page={inspSchedulePage}
                  pageSize={inspSchedulePageSize}
                  error={inspSchedulesError}
                  onPageChange={setInspSchedulePage}
                  onPageSizeChange={(size) => {
                    setInspSchedulePageSize(size);
                    setInspSchedulePage(1);
                  }}
                  onSelect={async (sch) => {
                    try {
                      const idToFetch = sch.job_id || sch.id;
                      const r = await fetch(`/api/scheduled-jobs/${idToFetch}`, { headers: authHeaders });
                      if (r.ok) {
                        const json = await r.json();
                        if (json.success) {
                          setSelectedSchedule(json.data);
                          setShowScheduleDetail(true);
                        }
                      }
                    } catch (e) {
                      console.error(e);
                    }
                  }}
                  onToggleEnabled={toggleInspScheduleEnabled}
                  onEdit={(sch) => navigate(`/automation/scheduled-jobs?edit_id=${encodeURIComponent(sch.job_id || sch.id)}`)}
                  onDelete={deleteInspSchedule}
                  onRetry={fetchInspSchedules}
                />
              </>
            )}
          </div>
        )}

        {/* History sub-tab */}
        {inspSubTab === 'history' && (
          <HistoryList
            zh={zh}
            language={language}
            loading={inspRunsLoading}
            errorMessage={inspRunsError}
            logs={unifiedLogs}
            total={inspRunTotal}
            page={inspRunPage}
            pageSize={inspRunPageSize}
            onPageChange={setInspRunPage}
            onPageSizeChange={handleExecutionHistoryPageSizeChange}
            searchQuery={executionHistorySearch}
            onSearchChange={handleExecutionHistorySearchChange}
            executionTypeFilter={executionTypeFilter}
            onFilterChange={handleExecutionTypeFilterChange}
            onSelectLog={handleSelectLog}
            onExport={handleExportReport}
            loadAllLogs={loadAllExecutionLogs}
          />
        )}
      </div>

      {pendingScheduleOperation && (
        <div className="fixed inset-0 z-[120] flex items-center justify-center p-4" role="dialog" aria-modal="true">
          <button
            type="button"
            aria-label={zh ? '关闭审批窗口' : 'Close approval dialog'}
            className="absolute inset-0 bg-slate-950/50 backdrop-blur-sm"
            onClick={() => {
              if (approvalStatus === 'sending' || operationLoading) return;
              setPendingScheduleOperation(null);
              resetApproval();
              setOperationApprovalReason('');
            }}
          />
          <div className="relative w-full max-w-lg rounded-2xl border border-slate-200 bg-white shadow-2xl">
            <div className={`flex items-center justify-between rounded-t-2xl border-b px-6 py-4 ${pendingScheduleOperation.operation === 'DELETE' ? 'border-rose-100 bg-rose-50' : 'border-cyan-100 bg-cyan-50'}`}>
              <div>
                <h3 className={`text-sm font-bold ${pendingScheduleOperation.operation === 'DELETE' ? 'text-rose-800' : 'text-cyan-900'}`}>
                  {pendingScheduleOperation.operation === 'DELETE'
                    ? (zh ? '删除执行计划审批' : 'Delete Schedule Approval')
                    : pendingScheduleOperation.operation === 'ENABLE'
                      ? (zh ? '启用执行计划审批' : 'Enable Schedule Approval')
                      : (zh ? '停用执行计划审批' : 'Disable Schedule Approval')}
                </h3>
                <p className="mt-1 text-xs text-slate-600">{pendingScheduleOperation.job.name}</p>
              </div>
              <button
                type="button"
                className="rounded-lg px-2 py-1 text-slate-400 hover:bg-white/70 hover:text-slate-700 disabled:opacity-40"
                disabled={approvalStatus === 'sending' || operationLoading}
                onClick={() => {
                  setPendingScheduleOperation(null);
                  resetApproval();
                  setOperationApprovalReason('');
                }}
              >
                ×
              </button>
            </div>
            <div className="space-y-4 px-6 py-5 text-xs text-slate-700">
              <div className="rounded-xl border border-slate-100 bg-slate-50 p-3 font-mono text-[11px] text-slate-600">
                <div>ID: {pendingScheduleOperation.job.id}</div>
                <div>{pendingScheduleOperation.job.action_type} · {pendingScheduleOperation.job.device_scope}</div>
                <div>{pendingScheduleOperation.job.scheduled_at || pendingScheduleOperation.job.cron_expr}</div>
              </div>
              {approvalStatus !== 'verified' && (
                <>
                  <label className="block space-y-1.5">
                    <span className="font-semibold">{zh ? '操作原因' : 'Reason'}</span>
                    <input
                      value={operationApprovalReason}
                      onChange={event => setOperationApprovalReason(event.target.value)}
                      disabled={approvalStatus !== 'idle'}
                      className="w-full rounded-xl border border-slate-200 px-3 py-2 outline-none focus:border-cyan-500 disabled:bg-slate-50"
                    />
                  </label>
                  <label className="block space-y-1.5">
                    <span className="font-semibold">{zh ? '选择审批人' : 'Approver'}</span>
                    <select
                      value={approverUsername}
                      onChange={event => setApproverUsername(event.target.value)}
                      disabled={approvalStatus !== 'idle'}
                      className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 outline-none focus:border-cyan-500 disabled:bg-slate-50"
                    >
                      <option value="">{zh ? '选择审批人...' : 'Select approver...'}</option>
                      {approvers.map(approver => (
                        <option key={approver.id} value={approver.username}>{approver.username}</option>
                      ))}
                    </select>
                    {approvers.length === 0 && <span className="block text-amber-700">{zh ? '当前没有可用审批人。' : 'No eligible approvers are available.'}</span>}
                  </label>
                  <button
                    type="button"
                    onClick={requestApproval}
                    disabled={!approverUsername || !operationApprovalReason.trim() || approvalStatus !== 'idle' || operationLoading}
                    className="w-full rounded-xl bg-cyan-800 px-4 py-2.5 font-bold text-white transition hover:bg-cyan-900 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {approvalStatus === 'sending' ? (zh ? '正在发送...' : 'Sending...') : (zh ? '发送审批验证码' : 'Request approval code')}
                  </button>
                </>
              )}
              {approvalStatus === 'sent' && (
                <div className="space-y-2 rounded-xl border border-slate-100 bg-slate-50 p-3">
                  <label className="block font-semibold" htmlFor="execution-schedule-approval-code">
                    {zh ? '输入 6 位审批验证码' : 'Enter the 6-digit approval code'}
                  </label>
                  <div className="flex gap-2">
                    <input
                      id="execution-schedule-approval-code"
                      value={approvalCode}
                      onChange={event => { setApprovalCode(event.target.value.replace(/\D/g, '').slice(0, 6)); setApprovalError(''); }}
                      inputMode="numeric"
                      maxLength={6}
                      className="w-36 rounded-xl border border-slate-200 px-3 py-2 text-center font-mono tracking-[0.25em] outline-none focus:border-emerald-500"
                    />
                    <button
                      type="button"
                      onClick={verifyApproval}
                      disabled={approvalCode.length !== 6}
                      className="rounded-xl bg-emerald-600 px-4 py-2 font-bold text-white hover:bg-emerald-700 disabled:opacity-40"
                    >
                      {zh ? '验证' : 'Verify'}
                    </button>
                  </div>
                </div>
              )}
              {approvalStatus === 'verified' && (
                <div className="rounded-xl border border-emerald-100 bg-emerald-50 px-3 py-2 font-semibold text-emerald-800">
                  {zh ? '审批验证通过。' : 'Approval verified.'}
                </div>
              )}
              {approvalError && <div role="alert" className="rounded-xl bg-rose-50 px-3 py-2 text-rose-700">{approvalError}</div>}
            </div>
            <div className="flex justify-end gap-2 border-t border-slate-100 px-6 py-4">
              <button
                type="button"
                onClick={() => {
                  setPendingScheduleOperation(null);
                  resetApproval();
                  setOperationApprovalReason('');
                }}
                disabled={approvalStatus === 'sending' || operationLoading}
                className="rounded-xl border border-slate-200 px-4 py-2 font-semibold text-slate-600 hover:bg-slate-50 disabled:opacity-40"
              >
                {zh ? '取消' : 'Cancel'}
              </button>
              <button
                type="button"
                onClick={executePendingScheduleOperation}
                disabled={approvalStatus !== 'verified' || operationLoading}
                className={`rounded-xl px-4 py-2 font-bold text-white disabled:cursor-not-allowed disabled:opacity-40 ${pendingScheduleOperation.operation === 'DELETE' ? 'bg-rose-600 hover:bg-rose-700' : pendingScheduleOperation.operation === 'ENABLE' ? 'bg-emerald-600 hover:bg-emerald-700' : 'bg-amber-600 hover:bg-amber-700'}`}
              >
                {operationLoading
                  ? (zh ? '正在处理...' : 'Working...')
                  : pendingScheduleOperation.operation === 'DELETE'
                    ? (zh ? '确认删除' : 'Confirm delete')
                    : pendingScheduleOperation.operation === 'ENABLE'
                      ? (zh ? '确认启用' : 'Confirm enable')
                      : (zh ? '确认停用' : 'Confirm disable')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal/Slide-over details */}
      <ScheduleDetail
        zh={zh}
        open={showScheduleDetail}
        schedule={selectedSchedule}
        onClose={() => { setSelectedSchedule(null); setShowScheduleDetail(false); }}
        onToggleEnabled={(sch) => {
          toggleInspScheduleEnabled(sch);
          setSelectedSchedule(prev => prev ? { ...prev, enabled: prev.enabled ? 0 : 1 } : null);
        }}
        onDelete={(id) => {
          deleteInspSchedule(id);
          setShowScheduleDetail(false);
        }}
        onScheduleUpdate={setSelectedSchedule}
      />

      <ExecutionDetail
        zh={zh}
        open={isDetailModalOpen}
        selectedLog={selectedLog}
        logDetailLoading={logDetailLoading}
        onClose={closeExecutionDetail}
        inspectionDetail={inspectionDetail}
        selectedInspDeviceId={selectedInspDeviceId}
        setSelectedInspDeviceId={setSelectedInspDeviceId}
        collapsedCmds={collapsedCmds}
        toggleCmdCollapse={toggleCmdCollapse}
        expandAllCmds={expandAllCmds}
        collapseAllCmds={collapseAllCmds}
        inspParseResults={inspParseResults}
        inspCopiedKey={inspCopiedKey}
        inspDetailTab={inspDetailTab}
        setInspDetailTab={setInspDetailTab}
        inspParseViewMode={inspParseViewMode}
        setInspParseViewMode={setInspParseViewMode}
        trendData={trendData}
        trendLoading={trendLoading}
        setTrendData={setTrendData}
        onParseCmd={handleParseInspCmd}
        onCopyText={copyInspText}
        onFetchTrend={fetchTrend}
        setCollapsedCmds={setCollapsedCmds}
        setInspParseResults={setInspParseResults}
        pbDetail={pbDetail}
        pbDevices={pbDevices}
        pbApprovals={pbApprovals}
        pbApprovalsLoading={pbApprovalsLoading}
        pbApprovalActionId={pbApprovalActionId}
        pbApprovalError={pbApprovalError}
        onPlaybookApproval={handlePlaybookApproval}
        selectedPbDevice={selectedPbDevice}
        pbDeviceDetail={pbDeviceDetail}
        onSelectPbDevice={handleSelectPbDevice}
        backupRunDetail={backupRunDetail}
        backupRunError={backupRunError}
        backupDevicePage={backupDevicePage}
        backupDeviceStatusFilter={backupDeviceStatusFilter}
        onBackupDevicePageChange={handleBackupDevicePageChange}
        onBackupDeviceStatusFilterChange={handleBackupDeviceStatusFilterChange}
        onRetryBackupRunDetails={() => {
          if (selectedLog?.source === 'config_backup') void loadBackupRunDetails(selectedLog, backupDevicePage, backupDeviceStatusFilter);
        }}
        devices={devices}
      />

      <CandidateModal
        zh={zh}
        open={candidateModalOpen}
        candidates={candidateList}
        onClose={() => {
          setCandidateModalOpen(false);
          setCandidateList([]);
        }}
        onToggle={toggleCandidateSelected}
        onToggleAll={toggleAllCandidates}
        onConfirm={confirmAddCandidates}
      />
    </div>
  );
};

export default ExecutionScheduleCoordinator;
