import React, { useEffect, useState, useCallback, useMemo } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  CalendarClock, Clock, Plus, X, Trash2, Activity, RotateCcw,
  Play, Shield, CheckCircle2, CalendarRange, AlertTriangle,
  Eye, Download, Search, FileText, ChevronRight,
  FileSpreadsheet, FileJson, Loader2, Table2, Copy, Check,
  Database, Zap, Target, FileCode, ShieldAlert, User, Pencil, Info
} from 'lucide-react';
import * as XLSX from 'xlsx';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as RTooltip, ResponsiveContainer } from 'recharts';
import Pagination from '../components/Pagination';
import OutputActions from '../components/OutputActions';
import DateTimePicker from '../components/DateTimePicker';
import TagConditionPicker, { type TagFilterConfig, EMPTY_TAG_FILTER, serializeTagFilter, parseTagFilter } from '../components/TagConditionPicker';
import PageHero from '../components/PageHero';
import type { Device } from '../types';

/* ═══════════════════════════════════════════════════════ */
/*  Types                                                  */
/* ═══════════════════════════════════════════════════════ */

const ACTION_TYPES = [
  { value: 'backup', labelZh: '核心配置备份', labelEn: 'Config Backup', icon: Database, category: 'collection' },
  { value: 'inspection', labelZh: '智能巡检', labelEn: 'Smart Inspection', icon: Activity, category: 'collection' },
  { value: 'script_run', labelZh: '自动化脚本', labelEn: 'Automated Script', icon: Zap, category: 'change' },
];

const MAJOR_CATEGORIES = [
  { value: 'collection', labelZh: '采集与巡检', labelEn: 'Collection & Inspection', icon: Database },
  { value: 'change', labelZh: '自动化变更', labelEn: 'Automation Change', icon: Zap },
];

const SCOPE_OPTIONS = [
  { value: 'all', labelZh: '全部在线设备', labelEn: 'All online devices' },
  { value: 'ip', labelZh: '按 IP 地址', labelEn: 'By IP address' },
  { value: 'tag', labelZh: '按标签', labelEn: 'By tag' },
  { value: 'site', labelZh: '按站点', labelEn: 'By site' },
  { value: 'role', labelZh: '按角色', labelEn: 'By role' },
];

interface ScheduledJob {
  id: string;
  name: string;
  job_type: string;
  action_type: string;
  cron_expr: string;
  scheduled_at: string;
  device_scope: string;
  device_filter: string;
  commands: string;
  script_id: string;
  is_config: number;
  config_reason: string;
  enabled: number;
  status: string;
  approved_by: string;
  approved_at: string;
  last_run_at: string;
  last_run_status: string;
  run_count: number;
  use_admin_creds?: number;
  created_by: string;
  created_at: string;
  major_type?: string;
  check_items?: string[];
  description?: string;
}
interface InspectionRun {
  id: string; schedule_id?: string; trigger_type: string; scope_type: string; scope_filter: string;
  status: string; started_at: string; completed_at?: string; total_devices: number;
  success_count: number; failed_count: number; unreachable_count: number;
  healthy_count: number; warning_count: number; critical_count: number;
  avg_health_score: number; created_by: string;
}

interface ExecutionScheduleTabProps {
  t: (key: string) => string;
  language: string;
  showToast: (msg: string, type?: 'success' | 'error' | 'info') => void;
  initialTab?: 'schedules' | 'history';
  devices: Device[];
  onRerun?: (log: any) => void;
}

interface FormState {
  name: string;
  action_type: string;
  scheduled_at: string;
  device_scope: string;
  device_filter: string;
  commands: string;
  script_id: string;
  is_config: boolean;
  config_reason: string;
  use_admin_creds: boolean;
  major_type: string;
  check_items: string[];
  description: string;
}

interface ValidatedDevice {
  ip: string;
  hostname: string;
  tags: { id: string; label: string; label_zh: string; color: string }[];
}

interface EligibleApprover {
  id: string;
  username: string;
  role: string;
}

const INITIAL_FORM: FormState = {
  name: '',
  action_type: 'backup',
  scheduled_at: '',
  device_scope: 'all',
  device_filter: '',
  commands: '',
  script_id: '',
  is_config: false,
  config_reason: '',
  use_admin_creds: false,
  major_type: 'collection',
  check_items: [],
  description: '',
};

/* ═══════════════════════════════════════════════════════ */
/*  Helpers                                                */
/* ═══════════════════════════════════════════════════════ */

const fmtDateTime = (iso: string | undefined, zh: boolean): string => {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(zh ? 'zh-CN' : 'en-US', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  });
};

const getScheduleStatus = (sch: ScheduledJob, zh: boolean) => {
  if (!sch.enabled) return { label: zh ? '已停用' : 'Disabled', cls: 'bg-slate-100 text-slate-500', icon: 'disabled' as const };
  if (sch.last_run_at) return { label: zh ? '已执行' : 'Executed', cls: 'bg-emerald-50 text-emerald-600', icon: 'done' as const };
  const now = new Date();
  if (sch.scheduled_at && new Date(sch.scheduled_at) > now) return { label: zh ? '等待中' : 'Pending', cls: 'bg-cyan-50 text-cyan-600', icon: 'pending' as const };
  return { label: zh ? '就绪' : 'Ready', cls: 'bg-amber-50 text-amber-600', icon: 'ready' as const };
};

const describeScope = (scope: string, filter: string, zh: boolean): string => {
  if (scope === 'all') return zh ? '全部设备' : 'All devices';
  if (scope === 'ip') {
    const ips = filter.split(/[,\n;]+/).map(s => s.trim()).filter(Boolean);
    if (ips.length === 0) return zh ? 'IP 地址' : 'IP addresses';
    if (ips.length <= 2) return ips.join(', ');
    return `${ips[0]}, ${ips[1]} +${ips.length - 2}`;
  }
  if (scope === 'tag' || scope === 'tags') {
    try {
      const cfg = JSON.parse(filter);
      // New format: groups[]
      if (Array.isArray(cfg.groups)) {
        const n = cfg.groups.reduce((s: number, g: { tag_ids?: string[] }) => s + (g.tag_ids?.length || 0), 0) + (cfg.exclude_tag_ids?.length || 0);
        return zh ? `${n} 个标签条件` : `${n} tag conditions`;
      }
      // Old format compat
      const n = (cfg.tag_ids?.length || 0) + (cfg.exclude_tag_ids?.length || 0);
      return zh ? `${n} 个标签条件` : `${n} tag conditions`;
    } catch { /* ignore */ }
    return filter || (zh ? '标签' : 'Tags');
  }
  return filter || scope;
};

/* ═══════════════════════════════════════════════════════ */
/*  Component                                              */
/* ═══════════════════════════════════════════════════════ */

const ExecutionScheduleTab: React.FC<ExecutionScheduleTabProps> = ({ language, showToast, initialTab, devices, onRerun }) => {
  const zh = language === 'zh';

  /* ═══ STATE ═══ */
  const [inspSchedules, setInspSchedules] = useState<ScheduledJob[]>([]);
  const [inspSchedulesLoading, setInspSchedulesLoading] = useState(false);
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
  const [tagFilter, setTagFilter] = useState<TagFilterConfig>({ ...EMPTY_TAG_FILTER });

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

  const [inspRuns, setInspRuns] = useState<InspectionRun[]>([]);
  const [inspRunsLoading, setInspRunsLoading] = useState(false);
  const [inspRunPage, setInspRunPage] = useState(1);
  const [inspRunPageSize, setInspRunPageSize] = useState(10);
  const [inspRunTotal, setInspRunTotal] = useState(0);
  type InspSubTab = 'schedules' | 'history';
  const [inspSubTab, setInspSubTab] = useState<InspSubTab>(initialTab || 'schedules');

  // Unified execution history states
  interface UnifiedExecutionLog {
    id: string;
    source: 'inspection' | 'playbook';
    started_at: string;
    trigger_type: 'manual' | 'plan' | 'job';
    status: string;
    total_devices: number;
    success_count: number;
    failed_count: number;
    partial_count?: number;
    avg_health_score?: number;
    created_by: string;
    name: string;
  }
  const [unifiedLogs, setUnifiedLogs] = useState<UnifiedExecutionLog[]>([]);
  const [executionTypeFilter, setExecutionTypeFilter] = useState<'all' | 'manual' | 'plan' | 'job'>('all');

  const [selectedLog, setSelectedLog] = useState<UnifiedExecutionLog | null>(null);
  const [isDetailModalOpen, setIsDetailModalOpen] = useState(false);
  const [logDetailLoading, setLogDetailLoading] = useState(false);
  const [selectedInspDeviceId, setSelectedInspDeviceId] = useState<string | null>(null);
  const [collapsedCmds, setCollapsedCmds] = useState<Record<string, boolean>>({});
  // TextFSM parse state for inspection command blocks
  const [inspParseResults, setInspParseResults] = useState<Record<string, { loading: boolean; data: any; error: string }>>({});
  const [inspCopiedKey, setInspCopiedKey] = useState<string | null>(null);
  // Inspection device detail tab (R3.1: 原始输出 / 指标快照 / 指标分析 / 合规检查)
  type InspDetailTab = 'raw' | 'snapshot' | 'analysis' | 'compliance';
  const [inspDetailTab, setInspDetailTab] = useState<InspDetailTab>('analysis');
  const [inspParseViewMode, setInspParseViewMode] = useState<Record<string, 'raw' | 'parsed'>>({});
  // Trend chart state for analysis tab (R5.5–R5.7)
  const [trendData, setTrendData] = useState<{ deviceId: string; metric: string; series: any[]; firstInspection?: boolean } | null>(null);
  const [trendLoading, setTrendLoading] = useState(false);
  
  const [inspectionDetail, setInspectionDetail] = useState<any>(null);
  const [pbDetail, setPbDetail] = useState<any>(null);
  const [pbDevices, setPbDevices] = useState<any[]>([]);
  const [selectedPbDevice, setSelectedPbDevice] = useState<any>(null);
  const [pbDeviceDetail, setPbDeviceDetail] = useState<any>(null);

  useEffect(() => { if (initialTab) setInspSubTab(initialTab); }, [initialTab]);

  // Approval states
  interface EligibleApprover { id: string; username: string; role: string }
  const [approvers, setApprovers] = useState<EligibleApprover[]>([]);
  const [approverUsername, setApproverUsername] = useState('');
  const [approvalToken, setApprovalToken] = useState('');
  const [approvalCode, setApprovalCode] = useState('');
  const [approvalStatus, setApprovalStatus] = useState<'idle' | 'sending' | 'sent' | 'verified'>('idle');
  const [approvalError, setApprovalError] = useState('');

  const authHeaders = useMemo(() => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' };
  }, [localStorage.getItem('netops_token')]); // Re-evaluate if token changes

  /* ═══ FETCHERS ═══ */
  const fetchInspectionItems = useCallback(async () => {
    setInspectionItemsLoading(true);
    try {
      const r = await fetch('/api/inspections/items/all', { headers: authHeaders });
      if (r.ok) {
        const j = await r.json();
        setInspectionItems(j.items || []);
        // Set default check items if form is empty
        if (form.check_items.length === 0 && j.items?.length > 0) {
          setForm(f => ({ ...f, check_items: j.items.map((i: any) => i.name) }));
        }
      }
    } catch { /* ignore */ }
    finally { setInspectionItemsLoading(false); }
  }, [authHeaders, form.check_items.length]);

  const fetchInspSchedules = useCallback(async () => {
    setInspSchedulesLoading(true);
    try {
      const offset = (inspSchedulePage - 1) * inspSchedulePageSize;
      const r = await fetch(`/api/scheduled-jobs?job_type=once&limit=${inspSchedulePageSize}&offset=${offset}`, { headers: authHeaders });
      if (r.ok) {
        const j = await r.json();
        const d = j.data || {};
        setInspSchedules(d.items || []);
        setInspScheduleTotal(d.total || 0);
      }
    } catch { /* ignore */ }
    finally { setInspSchedulesLoading(false); }
  }, [authHeaders, inspSchedulePage, inspSchedulePageSize]);

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

  const fetchInspRuns = useCallback(async () => {
    console.log('[ExecutionScheduleTab] fetchInspRuns called');
    setInspRunsLoading(true);
    try {
      // 1. Fetch inspections (limit 500)
      const inspResp = await fetch(`/api/inspections?limit=500`, { headers: authHeaders });
      let inspections: any[] = [];
      if (inspResp.ok) {
        const j = await inspResp.json();
        const d = j.data;
        inspections = Array.isArray(d) ? d : (d?.items || []);
      }

      // 2. Fetch playbooks (limit 500)
      const pbResp = await fetch(`/api/playbooks?page=1&page_size=500`, { headers: authHeaders });
      let playbooks: any[] = [];
      if (pbResp.ok) {
        const j = await pbResp.json();
        playbooks = Array.isArray(j) ? j : (j?.items || []);
        console.log(`[ExecutionScheduleTab] Fetched ${playbooks.length} playbooks`);
      } else {
        console.warn(`[ExecutionScheduleTab] Playbooks API failed: ${pbResp.status} ${pbResp.statusText}`);
        if (pbResp.status === 403) {
          showToast(zh ? '获取执行历史被拒绝 (403)' : 'Access denied to execution history (403)', 'error');
        }
      }

      // 3. Normalize & Merge
      const normalizedInsp: UnifiedExecutionLog[] = inspections.map(run => ({
        id: run.id,
        source: 'inspection',
        started_at: run.started_at,
        trigger_type: run.trigger_type === 'manual' ? 'manual' : 'plan',
        status: run.status,
        total_devices: run.total_devices || 0,
        success_count: run.success_count || 0,
        failed_count: run.failed_count || 0,
        avg_health_score: run.avg_health_score,
        created_by: run.created_by || 'system',
        name: run.schedule_name || run.name || (zh ? '网络巡检' : 'Network Inspection')
      }));

      const normalizedPlaybooks: UnifiedExecutionLog[] = playbooks.map(pb => {
        const isScheduled = pb.author === 'scheduler' || pb.author === 'system'
                            || (pb.scenario_id && String(pb.scenario_id).startsWith('scheduled:'));
        return {
          id: pb.id,
          source: 'playbook',
          started_at: pb.created_at,
          trigger_type: isScheduled ? 'job' : 'manual',
          status: pb.status,
          total_devices: pb.total_devices || 0,
          success_count: pb.success_count || 0,
          failed_count: pb.failed_count || 0,
          partial_count: pb.partial_count || 0,
          created_by: pb.author || 'admin',
          name: pb.scenario_name || pb.task_name || (zh ? '快捷命令执行' : 'Quick Playbook')
        };
      });

      const combined = [...normalizedInsp, ...normalizedPlaybooks].sort((a, b) => {
        const timeA = a.started_at ? new Date(a.started_at).getTime() : 0;
        const timeB = b.started_at ? new Date(b.started_at).getTime() : 0;
        return (isNaN(timeB) ? 0 : timeB) - (isNaN(timeA) ? 0 : timeA);
      });

      console.log(`[ExecutionScheduleTab] Combined logs count: ${combined.length}`);
      setUnifiedLogs(combined);
    } catch (e) {
      console.error(e);
    } finally {
      setInspRunsLoading(false);
    }
  }, [authHeaders, zh]);

  const filteredLogs = useMemo(() => {
    return unifiedLogs.filter(log => {
      if (executionTypeFilter === 'all') return true;
      return log.trigger_type === executionTypeFilter;
    });
  }, [unifiedLogs, executionTypeFilter]);

  // Reset log page when filter changes
  useEffect(() => {
    setInspRunPage(1);
  }, [executionTypeFilter, unifiedLogs.length]);

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

  const paginatedLogs = useMemo(() => {
    const start = (inspRunPage - 1) * inspRunPageSize;
    return filteredLogs.slice(start, start + inspRunPageSize);
  }, [filteredLogs, inspRunPage, inspRunPageSize]);

  const handleSelectLog = async (log: UnifiedExecutionLog) => {
    setSelectedLog(log);
    setIsDetailModalOpen(true);
    setLogDetailLoading(true);
    setInspectionDetail(null);
    setPbDetail(null);
    setPbDevices([]);
    setSelectedPbDevice(null);
    setPbDeviceDetail(null);

    try {
      if (log.source === 'inspection') {
        const resp = await fetch(`/api/inspections/${log.id}`, { headers: authHeaders });
        if (resp.ok) {
          const j = await resp.json();
          setInspectionDetail(j.data);
          if (j.data?.results?.length > 0) {
            setSelectedInspDeviceId(j.data.results[0].device_id);
          }
        }
      } else {
        const pbResp = await fetch(`/api/playbooks/${log.id}`, { headers: authHeaders });
        if (pbResp.ok) {
          const j = await pbResp.json();
          setPbDetail(j);
        }
        const devResp = await fetch(`/api/playbooks/${log.id}/devices?page=1&page_size=100`, { headers: authHeaders });
        if (devResp.ok) {
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
      setLogDetailLoading(false);
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

  /** Export parsed records to .xlsx */
  const downloadInspExcel = useCallback((records: Record<string, any>[], fields: string[], filename: string) => {
    if (!records?.length) return;
    const data = records.map(r => {
      const row: Record<string, any> = {};
      for (const f of fields) row[f] = r[f] ?? '';
      return row;
    });
    const ws = XLSX.utils.json_to_sheet(data, { header: fields });
    ws['!cols'] = fields.map(f => {
      const maxLen = Math.max(f.length, ...data.map(r => String(r[f] ?? '').length));
      return { wch: Math.min(Math.max(maxLen + 2, 10), 60) };
    });
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, 'Parsed');
    XLSX.writeFile(wb, filename.endsWith('.xlsx') ? filename : `${filename}.xlsx`);
  }, []);

  /** Export parsed records as JSON */
  const downloadInspJSON = useCallback((records: Record<string, any>[], filename: string) => {
    if (!records?.length) return;
    const blob = new Blob([JSON.stringify(records, null, 2)], { type: 'application/json;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename.endsWith('.json') ? filename : `${filename}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, []);

  /** Split raw output string by command markers (# show ...) or intelligent signature alignment */
  const splitOutputByCommand = useCallback((output: string, commands: string[]): Array<{ command: string; output: string }> => {
    if (!output && (!commands || commands.length === 0)) return [];
    const safeOutput = output || '';
    const safeCommands = commands || [];

    // 1. Try standard marker split: lines starting with "# <cmd>"
    const markerRe = /^#[ \t]+(?:[^:\n]+:[ \t]+)?(.+)$/m;
    if (markerRe.test(safeOutput)) {
      const blocks: Array<{ command: string; output: string }> = [];
      const lines = safeOutput.split('\n');
      let currentCmd = '';
      let currentLines: string[] = [];

      for (const line of lines) {
        const m = line.match(/^#[ \t]+(?:[^:\n]+:[ \t]+)?(.+)$/);
        if (m) {
          if (currentCmd || currentLines.some(l => l.trim())) {
            blocks.push({ command: currentCmd, output: currentLines.join('\n').trim() });
          }
          currentCmd = m[1].trim();
          currentLines = [];
        } else {
          currentLines.push(line);
        }
      }
      if (currentCmd || currentLines.some(l => l.trim())) {
        blocks.push({ command: currentCmd, output: currentLines.join('\n').trim() });
      }
      const valid = blocks.filter(b => b.command || b.output);
      if (valid.length > 0) return valid;
    }

    // 2. If we only have 0 or 1 command, return full blob directly
    if (safeCommands.length === 0) {
      return safeOutput.trim() ? [{ command: '', output: safeOutput.trim() }] : [];
    }
    if (safeCommands.length === 1) {
      return [{ command: safeCommands[0], output: safeOutput.trim() }];
    }

    // 3. Multi-command split strategy (Resonance & Signature matching inspired by Excel export)
    const lines = safeOutput.split('\n');
    
    // 3a. Search for command prompts in lines (e.g. "SW1# show version" or "show version")
    const cleanPromptRe = /^.*?[\#\>\$]\s*/;
    const foundHeaders: Array<{ lineIdx: number; cmd: string }> = [];
    
    for (let i = 0; i < lines.length; i++) {
      const sLine = lines[i].replace(cleanPromptRe, '').trim().toLowerCase();
      for (const cmd of safeCommands) {
        const cLower = cmd.trim().toLowerCase();
        if (sLine === cLower || sLine.startsWith(cLower + ' ')) {
          foundHeaders.push({ lineIdx: i, cmd });
          break;
        }
      }
    }

    // If we found command headers matching our expected commands
    if (foundHeaders.length > 0) {
      const extractedMap: Record<string, string> = {};
      for (let i = 0; i < foundHeaders.length; i++) {
        const startIdx = foundHeaders[i].lineIdx;
        const cmdName = foundHeaders[i].cmd;
        const endIdx = i + 1 < foundHeaders.length ? foundHeaders[i + 1].lineIdx : lines.length;
        const contentLines = lines.slice(startIdx + 1, endIdx);
        extractedMap[cmdName] = contentLines.join('\n').trim();
      }

      return safeCommands.map(cmd => ({
        command: cmd,
        output: (extractedMap[cmd] !== undefined && extractedMap[cmd].trim() !== '') 
          ? extractedMap[cmd] 
          : 'ℹ️ 无返回内容或未采集。'
      }));
    }

    // 3b. If no prompt headers found, use Signature & Sequential Boundary Analysis
    const sigMap: Record<string, string[]> = {
      'show version': ['cisco ios software', 'linux software', 'cisco internetwork operating system', 'software (i86bi', 'rom: bootstrap'],
      'show processes cpu': ['cpu utilization for five seconds', 'pid runtime', 'cpu utilization'],
      'show processes memory': ['processor pool total', 'pid tty allocated', 'holding getbufs', 'memory pool'],
      'show environment temperature': ['temperature', 'temperature status', 'inlet temperature', 'fan status', 'temp'],
      'show environment power': ['power supply', 'power status', 'watts', 'power consumption', 'psu'],
      'show environment': ['environmental status', 'temperature', 'power', 'fan'],
      'show interfaces status': ['port name status', 'duplex speed', 'port status', 'port vlan duplex speed'],
      'show interfaces': ['line protocol is', 'hardware is', '5 minute input rate', 'full-duplex'],
      'show ip bgp summary': ['bgp router identifier', 'neighbor v as', 'bgp table version'],
      'show ip bgp': ['bgp routing table', 'bgp router identifier'],
      'show ip ospf neighbor': ['neighbor id pri state', 'ospf process'],
      'show ip ospf': ['routing process "ospf', 'ospf router with id'],
      'show ip route summary': ['ip routing table', 'route source', 'subnets'],
      'show ip route': ['codes: l - local', 'gateway of last resort', 'routing table'],
      'show running-config': ['building configuration', 'current configuration', 'version 15.'],
      'show ip int': ['interface ip-address ok?'],
      'show inventory': ['name:', 'descr:', 'chassis'],
      'show clock': ['utc', 'cst', 'pst', 'est'],
    };

    const getSigs = (c: string): string[] => {
      const cLower = c.trim().toLowerCase();
      for (const [key, sigs] of Object.entries(sigMap)) {
        if (cLower.includes(key)) return sigs;
      }
      return [];
    };

    const resultBlocks: Array<{ command: string; output: string }> = [];
    let currIdx = 0;
    const totalLines = lines.length;
    let cmdI = 0;
    const totalCmds = safeCommands.length;
    const errRe = /^\s*(?:%|invalid|unknown|syntax error|bad command|unrecognized)/i;

    while (cmdI < totalCmds) {
      const cmd = safeCommands[cmdI];
      if (currIdx >= totalLines) {
        resultBlocks.push({ command: cmd, output: 'ℹ️ 无返回内容或未采集。' });
        cmdI++;
        continue;
      }

      const currentIsError = errRe.test(lines[currIdx]);

      if (!currentIsError) {
        let endIdx = totalLines;
        for (let offset = 0; offset < totalLines - currIdx; offset++) {
          const absIdx = currIdx + offset;
          const l = lines[absIdx];
          const lLower = l.trim().toLowerCase();

          if (offset > 1 && errRe.test(l)) {
            endIdx = absIdx;
            break;
          }

          let matchedNext = false;
          for (let nextCIdx = cmdI + 1; nextCIdx < totalCmds; nextCIdx++) {
            const nextCmd = safeCommands[nextCIdx];
            if (lLower.includes(nextCmd.toLowerCase()) && lLower.length < nextCmd.length + 15) {
              endIdx = absIdx;
              matchedNext = true;
              break;
            }
            const sigs = getSigs(nextCmd);
            if (sigs.length > 0 && sigs.some(sig => lLower.includes(sig))) {
              endIdx = absIdx;
              matchedNext = true;
              break;
            }
          }
          if (matchedNext) break;
        }

        const cmdContent = lines.slice(currIdx, endIdx).join('\n').trim();
        resultBlocks.push({ command: cmd, output: cmdContent || 'ℹ️ 执行成功，但无回显' });
        currIdx = endIdx;
        cmdI++;
      } else {
        // Error block resonance alignment
        let nextSuccessCmdIdx = -1;
        let foundSuccessLineIdx = totalLines;

        for (let nextCIdx = cmdI + 1; nextCIdx < totalCmds; nextCIdx++) {
          const nextCmd = safeCommands[nextCIdx];
          const sigs = getSigs(nextCmd);

          for (let offset = 0; offset < totalLines - currIdx; offset++) {
            const absIdx = currIdx + offset;
            const l = lines[absIdx];
            const lLower = l.trim().toLowerCase();
            if (!errRe.test(l)) {
              if (lLower.includes(nextCmd.toLowerCase()) && lLower.length < nextCmd.length + 15) {
                nextSuccessCmdIdx = nextCIdx;
                foundSuccessLineIdx = absIdx;
                break;
              }
              if (sigs.length > 0 && sigs.some(sig => lLower.includes(sig))) {
                nextSuccessCmdIdx = nextCIdx;
                foundSuccessLineIdx = absIdx;
                break;
              }
            }
          }
          if (nextSuccessCmdIdx !== -1) break;
        }

        const chunkLines = lines.slice(currIdx, foundSuccessLineIdx);
        const countToAssign = (nextSuccessCmdIdx !== -1 ? nextSuccessCmdIdx : totalCmds) - cmdI;

        if (countToAssign === 1) {
          resultBlocks.push({ command: cmd, output: chunkLines.join('\n').trim() });
        } else {
          const errChunks: string[] = [];
          let currErrChunk: string[] = [];
          for (const cl of chunkLines) {
            const clStr = cl.trim();
            const isCaretOnly = clStr.length > 0 && clStr.split('').every(ch => ch === '^' || ch === ' ');
            const isErrStart = errRe.test(cl) || isCaretOnly;
            const hasRealText = currErrChunk.some(x => /[a-zA-Z0-9%]/.test(x));

            if (isErrStart && hasRealText) {
              errChunks.push(currErrChunk.join('\n').trim());
              currErrChunk = [cl];
            } else {
              currErrChunk.push(cl);
            }
          }
          if (currErrChunk.length > 0) {
            errChunks.push(currErrChunk.join('\n').trim());
          }
          const validErrChunks = errChunks.filter(ch => ch.trim() !== '');

          const cmdsToAssign = safeCommands.slice(cmdI, cmdI + countToAssign);
          const assignedOut: Record<string, string> = {};
          const remainingErrs = [...validErrChunks];
          const remainingCmds = [...cmdsToAssign];

          for (const errTxt of [...remainingErrs]) {
            const errLower = errTxt.toLowerCase();
            let matchedCmd: string | undefined = undefined;
            if (errLower.includes('bgp')) {
              matchedCmd = remainingCmds.find(c => c.toLowerCase().includes('bgp'));
            } else if (errLower.includes('ospf')) {
              matchedCmd = remainingCmds.find(c => c.toLowerCase().includes('ospf'));
            } else if (errLower.includes('interface') || errLower.includes('drop') || errLower.includes('line protocol')) {
              matchedCmd = remainingCmds.find(c => c.toLowerCase().includes('interface') || c.toLowerCase().includes('int'));
            }

            if (matchedCmd) {
              assignedOut[matchedCmd] = errTxt;
              remainingErrs.splice(remainingErrs.indexOf(errTxt), 1);
              remainingCmds.splice(remainingCmds.indexOf(matchedCmd), 1);
            }
          }

          for (const errTxt of remainingErrs) {
            if (remainingCmds.length > 0) {
              const cmdTarget = remainingCmds.shift()!;
              assignedOut[cmdTarget] = errTxt;
            }
          }

          for (const cName of cmdsToAssign) {
            resultBlocks.push({ command: cName, output: assignedOut[cName] || 'ℹ️ 执行成功，但无回显' });
          }
        }

        currIdx = foundSuccessLineIdx;
        cmdI = nextSuccessCmdIdx !== -1 ? nextSuccessCmdIdx : totalCmds;
      }
    }

    return resultBlocks;
  }, []);


  /** Centralized export handler for all report formats */
  const handleExportReport = useCallback(async (logId: string, format: string, source: string = 'inspection') => {
    try {
      const sourceParam = source === 'playbook' ? '&source=playbook' : '';
      const resp = await fetch(`/api/inspections/${logId}/export?format=${format}${sourceParam}`, { headers: authHeaders });
      if (resp.ok) {
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const today = new Date().toISOString().slice(0, 10).replace(/-/g, '');
        const prefix = source === 'playbook' ? 'Playbook' : 'Inspection';
        const ext = format === 'xlsx' ? 'xlsx' : format === 'html' ? 'html' : format === 'pdf' ? 'pdf' : 'json';
        a.download = `Nexora_${prefix}_Report_${logId}_${today}.${ext}`;
        a.click();
        URL.revokeObjectURL(url);
      } else {
        showToast(zh ? `${format.toUpperCase()} 导出失败 (${resp.status})` : `${format.toUpperCase()} export failed (${resp.status})`, 'error');
      }
    } catch (err) {
      console.error(`Export ${format} failed:`, err);
      showToast(zh ? `${format.toUpperCase()} 导出异常` : `${format.toUpperCase()} export error`, 'error');
    }
  }, [authHeaders, zh, showToast]);

  /** Copy text to clipboard with brief feedback */
  const copyInspText = useCallback((text: string, key: string) => {
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
  }, []);

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
    fetchInspSchedules();
    if (inspSubTab === 'history') {
      console.log('[ExecutionScheduleTab] Triggering fetchInspRuns due to subTab change');
      fetchInspRuns();
    }
    fetchInspectionItems();
  }, [inspSubTab, fetchInspSchedules, fetchInspRuns, fetchInspectionItems]);

  const fetchApprovers = useCallback(async () => {
    try {
      const r = await fetch('/api/users', { headers: authHeaders });
      if (r.ok) {
        const j = await r.json();
        const users = Array.isArray(j) ? j : (j.data || []);
        setApprovers(users.filter((u: EligibleApprover) => u.role === 'Administrator' || u.role === 'Operator'));
      }
    } catch { /* ignore */ }
  }, [authHeaders]);

  useEffect(() => {
    if (showAddInspSchedule) fetchApprovers();
  }, [showAddInspSchedule, fetchApprovers]);

  /* ═══ APPROVAL ═══ */
  const resetApproval = () => {
    setApprovalStatus('idle');
    setApproverUsername('');
    setApprovalToken('');
    setApprovalCode('');
    setApprovalError('');
  };

  const requestApproval = async () => {
    if (!approverUsername) return;
    setApprovalStatus('sending');
    setApprovalError('');
    try {
      const r = await fetch('/api/config-approval/request', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({
          approver_username: approverUsername,
          config_reason: form.config_reason || `${zh ? '创建执行计划' : 'Create execution schedule'}: ${form.name}`,
          device_hostname: resolveFilter() || (zh ? '全部设备' : 'All devices'),
          command_preview: form.commands || '',
          approval_type: 'execution_plan',
          extra_fields: {
            action_type: form.action_type,
            schedule_desc: form.scheduled_at ? fmtDateTime(form.scheduled_at, zh) : (zh ? '未设定' : 'Not set'),
          },
        }),
      });
      const j = await r.json();
      if (r.ok && j.success) {
        setApprovalToken(j.approval_token);
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
    if (!approvalToken || !approvalCode) return;
    try {
      const r = await fetch('/api/config-approval/verify', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({ approval_token: approvalToken, code: approvalCode }),
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
      const payload = {
        name: form.name,
        action_type: form.action_type,
        job_type: 'once',
        scheduled_at: form.scheduled_at,
        cron_expr: '',
        device_scope: form.device_scope,
        device_filter: resolveFilter(),
        script_id: form.script_id,
        commands: form.commands,
        config_reason: form.config_reason,
        use_admin_creds: form.use_admin_creds ? 1 : 0,
        approval_token: approvalToken,
        approval_code: approvalCode,
        description: form.description,
        check_items: form.check_items,
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
    try {
      await fetch(`/api/scheduled-jobs/${id}`, { method: 'DELETE', headers: authHeaders });
      fetchInspSchedules();
      showToast(zh ? '计划已删除' : 'Schedule deleted', 'success');
    } catch { /* ignore */ }
  };

  const toggleInspScheduleEnabled = async (sch: ScheduledJob) => {
    try {
      await fetch(`/api/scheduled-jobs/${sch.id}/toggle`, {
        method: 'PUT', headers: authHeaders,
        body: JSON.stringify({ enabled: !sch.enabled }),
      });
      fetchInspSchedules();
    } catch { /* ignore */ }
  };

  /* ═══ RENDER ═══ */
  return (
    <div className="flex flex-col h-full overflow-hidden">
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
              <button
                onClick={() => setShowAddInspSchedule(!showAddInspSchedule)}
                className={`flex items-center gap-1.5 px-4 py-2.5 rounded-xl text-sm font-bold shadow-sm transition-all active:scale-[0.97] ${
                  showAddInspSchedule
                    ? 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                    : 'bg-gradient-to-r from-cyan-500 to-cyan-600 text-white hover:from-cyan-400 hover:to-cyan-500'
                }`}
              >
                {showAddInspSchedule ? <X size={16} /> : <Plus size={16} />}
                {showAddInspSchedule ? (zh ? '取消新建' : 'Cancel') : (zh ? '新建计划' : 'Add Schedule')}
              </button>
            )}
            {inspSubTab === 'history' && (
              <button
                onClick={fetchInspRuns}
                disabled={inspRunsLoading}
                className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl border border-cyan-100 bg-cyan-50/50 text-[#0e7490] text-sm font-bold shadow-sm hover:bg-cyan-50 transition-all active:scale-[0.97]"
              >
                <RotateCcw size={16} className={inspRunsLoading ? 'animate-spin' : ''} />
                {zh ? '刷新记录' : 'Refresh'}
              </button>
            )}
          </>
        }
      />

      <div className="flex-1 overflow-auto px-6 py-5 space-y-4">

      {/* ── Schedules sub-tab ── */}
      {inspSubTab === 'schedules' && (
        <div className="space-y-4">
          <AnimatePresence mode="wait">
            {showAddInspSchedule ? (
              /* ── ADD FORM VIEW ── */
              <motion.div
                key="add-form"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                className="rounded-2xl border border-cyan-200/60 bg-white p-6 space-y-6 shadow-xl relative overflow-hidden"
              >
                <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-cyan-400 to-blue-500" />
                
                <div className="flex items-center justify-between border-b border-black/5 pb-4">
                  <h3 className="text-lg font-bold text-[#164e63] flex items-center gap-2">
                    <CalendarClock className="text-cyan-500" size={20} />
                    {zh ? '配置新的执行计划' : 'Configure New Execution Schedule'}
                  </h3>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                  {/* Left Column: Basic Info & Scope */}
                  <div className="space-y-5">
                    <div>
                      <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '计划名称' : 'Name'}</label>
                      <input
                        type="text" value={form.name}
                        onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                        className="w-full px-3.5 py-2.5 rounded-xl border border-black/[0.08] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all"
                        placeholder={zh ? '例：核心交换机月度变更' : 'e.g. Core Switch Monthly Check'}
                      />
                    </div>

                    <div>
                      <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '作业类型' : 'Action Type'}</label>
                      <div className="grid grid-cols-2 gap-2">
                        {MAJOR_CATEGORIES.map(mc => (
                          <button
                            key={mc.value} type="button"
                            onClick={() => {
                               setForm(f => ({ ...f, major_type: mc.value as any }));
                               if (mc.value === 'change') {
                                 setForm(f => ({ ...f, action_type: 'script_run' }));
                               } else if (mc.value === 'collection' && form.action_type !== 'script_run') {
                                 setForm(f => ({ ...f, action_type: 'backup' }));
                               }
                               fetchScripts();
                            }}
                            className={`flex items-center gap-2 px-3 py-2.5 rounded-xl border text-xs font-semibold transition-all ${
                              form.major_type === mc.value
                                ? 'border-cyan-400 bg-cyan-50 text-[#0891b2]'
                                : 'border-black/[0.06] bg-white text-black/50 hover:border-black/15'
                            }`}
                          >
                            <mc.icon className="w-3.5 h-3.5" />
                            {zh ? mc.labelZh : mc.labelEn}
                          </button>
                        ))}
                      </div>
                    </div>

                    {form.major_type === 'collection' && (
                      <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="p-1 bg-slate-50 rounded-xl border border-black/5 flex gap-1">
                        <button
                          type="button"
                          onClick={() => setForm(f => ({ ...f, action_type: 'backup', script_id: '' }))}
                          className={`flex-1 py-1.5 rounded-lg text-[10px] font-bold transition-all ${form.action_type === 'backup' ? 'bg-white shadow-sm text-cyan-600' : 'text-black/40 hover:text-black/60'}`}
                        >
                          {zh ? '核心配置采集' : 'Config Backup'}
                        </button>
                        <button
                          type="button"
                          onClick={() => setForm(f => ({ ...f, action_type: 'inspection' }))}
                          className={`flex-1 py-1.5 rounded-lg text-[10px] font-bold transition-all ${form.action_type === 'inspection' ? 'bg-white shadow-sm text-cyan-600' : 'text-black/40 hover:text-black/60'}`}
                        >
                          {zh ? '智能巡检' : 'Inspection'}
                        </button>
                        <button
                          type="button"
                          onClick={() => setForm(f => ({ ...f, action_type: 'script_run' }))}
                          className={`flex-1 py-1.5 rounded-lg text-[10px] font-bold transition-all ${form.action_type === 'script_run' ? 'bg-white shadow-sm text-cyan-600' : 'text-black/40 hover:text-black/60'}`}
                        >
                          {zh ? '脚本运行' : 'Script'}
                        </button>
                      </motion.div>
                    )}

                    {form.action_type === 'script_run' && (
                       <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="relative">
                          <label className="text-[10px] font-bold uppercase tracking-widest text-[#00a9ce] block mb-1.5">{zh ? '关联已发布脚本' : 'ASSOCIATED SCRIPT'}</label>
                          <div className="relative">
                             <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" size={14} />
                             <input 
                               type="text" 
                               placeholder={zh ? "输入名称搜索所有脚本..." : "Type to search all scripts..."}
                               value={scriptSearch}
                               onFocus={() => {
                                 setShowScriptDropdown(true);
                                 if (!scriptSearch) {
                                   const current = (availableScripts || []).find(s => s.id === form.script_id);
                                   if (current) setScriptSearch(current.name);
                                 }
                               }}
                               onChange={(e) => { setScriptSearch(e.target.value); setShowScriptDropdown(true); }}
                               className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-cyan-500/20 bg-cyan-500/5 text-sm focus:ring-2 focus:ring-cyan-500/20 outline-none transition-all placeholder:text-black/20"
                             />
                          </div>
                          
                          <AnimatePresence>
                             {showScriptDropdown && (
                                <motion.div 
                                  initial={{ opacity: 0, y: -5 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -5 }}
                                  className="absolute z-[60] left-0 right-0 mt-2 bg-[#0f172a]/95 backdrop-blur-xl border border-white/10 rounded-2xl shadow-2xl max-h-48 overflow-y-auto custom-scrollbar"
                                >
                                   {(() => {
                                      const filtered = (availableScripts || []).filter(s => {
                                         const searchVal = scriptSearch.toLowerCase();
                                         return s.name.toLowerCase().includes(searchVal);
                                      });
                                      if (filtered.length === 0) return <div className="p-8 text-center text-slate-400 text-[11px] italic">{zh ? '未找到匹配的脚本' : 'No matching scripts found'}</div>;
                                      return filtered.map(s => {
                                         const isSelected = form.script_id === s.id;
                                         const expectedCategory = form.major_type === 'collection' ? 'inspection' : 'change';
                                         const isWrongCategory = s.category && s.category !== expectedCategory;
                                         return (
                                            <div 
                                              key={s.id} 
                                              onClick={() => { 
                                                setForm(f => ({ ...f, script_id: s.id })); 
                                                setScriptSearch(s.name); 
                                                setShowScriptDropdown(false); 
                                              }}
                                              className={`px-5 py-3 text-[12px] cursor-pointer hover:bg-white/5 transition-all flex items-center justify-between border-b border-white/5 last:border-0 ${isSelected ? 'bg-cyan-500/20 text-[#00a9ce] font-bold' : 'text-slate-300'}`}
                                            >
                                               <div className="flex flex-col gap-0.5">
                                                  <span className="flex items-center gap-2">
                                                     <FileCode size={12} className={isWrongCategory ? 'text-amber-500' : 'text-cyan-500'} /> 
                                                     {s.name}
                                                  </span>
                                                  <div className="flex items-center gap-2 mt-1">
                                                     <span className={`text-[8px] px-1.5 py-0.5 rounded uppercase tracking-wider ${s.category === 'inspection' ? 'bg-emerald-500/10 text-emerald-500' : s.category === 'change' ? 'bg-amber-500/10 text-amber-500' : 'bg-slate-500/10 text-slate-500'}`}>
                                                        {s.category === 'inspection' ? (zh ? '巡检/采集' : 'INSPECTION') : 
                                                         s.category === 'change' ? (zh ? '自动化变更' : 'CHANGE') : (zh ? '未分类' : 'UNCATEGORIZED')}
                                                     </span>
                                                     {isWrongCategory && <span className="text-[8px] text-amber-500/60 italic font-normal">{zh ? '(非当前分类)' : '(Not current category)'}</span>}
                                                  </div>
                                               </div>
                                               {isSelected && <CheckCircle2 size={14} className="text-cyan-400" />}
                                            </div>
                                         );
                                      });
                                   })()}
                                </motion.div>
                             )}
                          </AnimatePresence>
                       </motion.div>
                    )}

                    <div>
                      <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '设备范围' : 'Device Scope'}</label>
                      <select
                        value={form.device_scope}
                        onChange={e => { setForm(f => ({ ...f, device_scope: e.target.value, device_filter: '' })); setIpDevices([]); setIpInput(''); }}
                        className="w-full px-3.5 py-2.5 rounded-xl border border-black/[0.08] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all"
                      >
                        {SCOPE_OPTIONS.map(o => (
                          <option key={o.value} value={o.value}>{zh ? o.labelZh : o.labelEn}</option>
                        ))}
                      </select>
                    </div>

                    {form.device_scope === 'ip' && (
                      <div>
                        <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">
                          {zh ? 'IP 地址' : 'IP Addresses'}
                        </label>
                        <div className="relative">
                          <input
                            type="text"
                            value={ipInput}
                            onChange={e => { setIpInput(e.target.value); setIpError(''); }}
                            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); validateAndAddIps(ipInput); } }}
                            disabled={ipValidating}
                            className="w-full pl-3.5 pr-12 py-2.5 rounded-xl border border-black/[0.08] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all font-mono"
                            placeholder={zh ? '输入 IP/关键词 后回车查询，弹窗勾选添加' : 'Enter IP/query and press Enter to select'}
                          />
                          <button
                            type="button"
                            onClick={() => validateAndAddIps(ipInput)}
                            disabled={!ipInput.trim() || ipValidating}
                            className="absolute right-2.5 top-1/2 -translate-y-1/2 p-1.5 rounded-lg text-cyan-600 hover:bg-cyan-50 transition-all disabled:opacity-30"
                          >
                            {ipValidating ? <RotateCcw size={14} className="animate-spin" /> : <Search size={14} />}
                          </button>
                        </div>
                        {ipError && <p className={`text-[10px] mt-1 ${ipError.includes('已添加') || ipError.includes('added') ? 'text-amber-500' : 'text-red-500'}`}>{ipError}</p>}
                        {ipDevices.length > 0 && (
                          <div className="mt-2 space-y-1 max-h-40 overflow-y-auto pr-1">
                            {ipDevices.map(dev => (
                              <div
                                key={dev.ip}
                                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border group hover:border-cyan-200/60 transition-all ${
                                  dev.hostname ? 'border-black/[0.06] bg-[#f8fafc]' : 'border-amber-200/60 bg-amber-50/30'
                                }`}
                              >
                                <span className="text-xs font-mono font-bold text-[#164e63] shrink-0">{dev.ip}</span>
                                {dev.hostname ? (
                                  <>
                                    <span className="text-black/15 text-[10px]">·</span>
                                    <span className="text-[11px] text-black/40 truncate">{dev.hostname}</span>
                                  </>
                                ) : (
                                  <span className="text-[10px] text-amber-500 italic">{zh ? '手动IP' : 'manual'}</span>
                                )}
                                <button
                                  type="button"
                                  onClick={() => removeIpDevice(dev.ip)}
                                  className="p-1 rounded-lg text-black/25 hover:text-red-500 hover:bg-red-50 transition-all shrink-0 ml-auto"
                                >
                                  <Trash2 size={12} />
                                </button>
                              </div>
                            ))}
                          </div>
                        )}
                        <p className="text-[10px] text-black/25 mt-1.5">
                          {ipDevices.length > 0
                            ? (zh ? `已添加 ${ipDevices.length} 个设备` : `${ipDevices.length} device(s) added`)
                            : (zh ? '输入 IP 后回车,系统自动验证并显示设备标签' : 'Enter IP and press Enter to validate')}
                        </p>
                      </div>
                    )}

                    {form.device_scope === 'tag' && (
                      <div>
                        <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '标签条件' : 'Tag Conditions'}</label>
                        <TagConditionPicker value={tagFilter} onChange={setTagFilter} language={language} />
                      </div>
                    )}

                    {(form.device_scope === 'site' || form.device_scope === 'role') && (
                      <div>
                        <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '过滤条件' : 'Filter'}</label>
                        <input
                          type="text" value={form.device_filter}
                          onChange={e => setForm(f => ({ ...f, device_filter: e.target.value }))}
                          className="w-full px-3.5 py-2.5 rounded-xl border border-black/[0.08] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all"
                          placeholder={zh ? (form.device_scope === 'site' ? '站点名称' : '角色名称') : (form.device_scope === 'site' ? 'Site name' : 'Role name')}
                        />
                      </div>
                    )}
                  </div>

                  {/* Right Column: Time, Commands, Security */}
                  <div className="space-y-5">
                    <div>
                      <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">
                        {zh ? '执行时间' : 'Execution Time'}
                      </label>
                      <DateTimePicker
                        value={form.scheduled_at}
                        onChange={v => setForm(f => ({ ...f, scheduled_at: v }))}
                        language={language}
                        className="w-full"
                      />
                    </div>

                    {form.action_type !== 'backup' && (
                      <div className="space-y-2">
                        <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block">
                          {form.action_type === 'inspection' ? (zh ? '巡检指标项' : 'Inspection Items') : (zh ? '执行命令 (可选)' : 'Commands (Optional)')}
                        </label>
                        {form.action_type === 'inspection' ? (
                          <div className="rounded-xl border border-black/[0.08] p-3 max-h-48 overflow-y-auto custom-scrollbar bg-[#f8fafc]">
                            {inspectionItemsLoading ? (
                              <div className="py-4 text-center text-black/20 text-[11px] italic">{zh ? '加载中...' : 'Loading...'}</div>
                            ) : inspectionItems.length > 0 ? (
                              <div className="grid grid-cols-2 gap-2">
                                {inspectionItems.map(item => {
                                  const isChecked = form.check_items.includes(item.name);
                                  return (
                                    <label key={item.id} className="flex items-center gap-2 cursor-pointer group">
                                      <input
                                        type="checkbox"
                                        checked={isChecked}
                                        onChange={() => {
                                          setForm(f => ({
                                            ...f,
                                            check_items: isChecked ? f.check_items.filter(x => x !== item.name) : [...f.check_items, item.name]
                                          }));
                                        }}
                                        className="w-3.5 h-3.5 rounded border-black/20 text-cyan-500 focus:ring-cyan-500/20"
                                      />
                                      <span className="text-[11px] text-black/60 font-medium group-hover:text-cyan-600 truncate">{item.name}</span>
                                    </label>
                                  );
                                })}
                              </div>
                            ) : (
                              <div className="py-4 text-center text-black/20 text-[11px] italic">{zh ? '暂无可用指标项' : 'No items available'}</div>
                            )}
                          </div>
                        ) : (
                          <textarea
                            value={form.commands}
                            onChange={e => setForm(f => ({ ...f, commands: e.target.value }))}
                            rows={3}
                            className="w-full px-3 py-2 rounded-xl border border-black/[0.08] text-xs font-mono bg-[#f8fafc] focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all resize-none"
                            placeholder={zh ? '输入设备命令，每行一个' : 'Enter commands, one per line'}
                          />
                        )}
                      </div>
                    )}

                    <div className="space-y-2 pt-1">
                      <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">
                        {zh ? '执行凭证与特权借用等级' : 'Execution Credentials & Privilege Level'}
                      </label>
                      <div className="grid grid-cols-2 gap-3">
                        <button
                          type="button"
                          onClick={() => setForm(f => ({ ...f, use_admin_creds: false }))}
                          className={`flex items-start gap-2.5 p-3 rounded-xl border text-left transition-all ${
                            !form.use_admin_creds
                              ? 'border-cyan-500 bg-cyan-50/50 text-[#164e63] shadow-sm font-semibold'
                              : 'border-slate-200 bg-white text-slate-500 hover:bg-slate-50'
                          }`}
                        >
                          <div className={`w-3.5 h-3.5 rounded-full flex items-center justify-center border mt-0.5 shrink-0 ${!form.use_admin_creds ? 'border-cyan-600 bg-cyan-600 text-white' : 'border-slate-300'}`}>
                            {!form.use_admin_creds && <div className="w-1.5 h-1.5 rounded-full bg-white" />}
                          </div>
                          <div className="min-w-0">
                            <div className="text-[11px] font-bold flex items-center gap-1.5">
                              <User className="w-3.5 h-3.5 text-cyan-600 shrink-0" />
                              <span className="truncate">{zh ? '普通运维操作员' : 'Normal Operator'}</span>
                            </div>
                          </div>
                        </button>
                        <button
                          type="button"
                          onClick={() => setForm(f => ({ ...f, use_admin_creds: true }))}
                          className={`flex items-start gap-2.5 p-3 rounded-xl border text-left transition-all ${
                            form.use_admin_creds
                              ? 'border-amber-500 bg-amber-50/50 text-amber-900 shadow-sm font-semibold'
                              : 'border-slate-200 bg-white text-slate-500 hover:bg-slate-50'
                          }`}
                        >
                          <div className={`w-3.5 h-3.5 rounded-full flex items-center justify-center border mt-0.5 shrink-0 ${form.use_admin_creds ? 'border-amber-600 bg-amber-600 text-white' : 'border-slate-300'}`}>
                            {form.use_admin_creds && <div className="w-1.5 h-1.5 rounded-full bg-white" />}
                          </div>
                          <div className="min-w-0">
                            <div className="text-[11px] font-bold flex items-center gap-1.5 text-amber-800">
                              <ShieldAlert className="w-3.5 h-3.5 text-amber-600 shrink-0" />
                              <span className="truncate">{zh ? '特权借用 (Enable)' : 'Privileged Borrowing'}</span>
                            </div>
                          </div>
                        </button>
                      </div>
                    </div>

                    <div className="rounded-xl border border-black/8 overflow-hidden">
                      <div className={`px-4 py-2.5 flex items-center gap-2.5 ${
                        approvalStatus === 'verified'
                          ? 'bg-gradient-to-r from-emerald-500 to-emerald-600'
                          : 'bg-gradient-to-r from-[#005b75] to-[#00465a]'
                      }`}>
                        <Shield className="w-3.5 h-3.5 text-white/90" />
                        <span className="text-[12px] font-semibold text-white/95">
                          {approvalStatus === 'verified' ? (zh ? '审批已通过' : 'Approval Granted') : (zh ? '审批验证' : 'Approval Required')}
                        </span>
                      </div>

                      {approvalStatus !== 'verified' && (
                        <div className="px-4 py-3.5 bg-[#f7fbfc] space-y-3">
                          <div className="space-y-3">
                            <div>
                              <label className="text-[11px] font-semibold text-black/50 mb-1 block">{zh ? '变更原因' : 'Reason'}</label>
                              <input
                                value={form.config_reason}
                                onChange={e => setForm(f => ({ ...f, config_reason: e.target.value }))}
                                placeholder={zh ? '创建执行计划' : 'Create execution plan'}
                                className="w-full rounded-xl border border-black/10 bg-white px-3 py-2 text-xs outline-none focus:border-[#00bceb] focus:ring-1 focus:ring-[#00bceb]/20 placeholder:text-black/25 transition-all"
                              />
                            </div>
                            <div>
                              <label className="text-[11px] font-semibold text-black/50 mb-1 block">{zh ? '审批人' : 'Approver'}</label>
                              <div className="flex items-center gap-2">
                                <select
                                  value={approverUsername}
                                  onChange={e => setApproverUsername(e.target.value)}
                                  className="flex-1 rounded-xl border border-black/10 bg-white px-3 py-2 text-xs outline-none focus:border-[#00bceb] focus:ring-1 focus:ring-[#00bceb]/20 transition-all"
                                  disabled={approvalStatus === 'sent' || approvalStatus === 'sending'}
                                >
                                  <option value="">{zh ? '选择审批人...' : 'Select approver...'}</option>
                                  {approvers.map(u => (
                                    <option key={u.id} value={u.username}>{u.username} ({u.role})</option>
                                  ))}
                                </select>
                                <button
                                  type="button"
                                  onClick={requestApproval}
                                  disabled={!approverUsername || !form.config_reason.trim() || approvalStatus === 'sending' || approvalStatus === 'sent'}
                                  className={`px-3 py-2 rounded-xl text-[11px] font-semibold transition-all flex items-center gap-1.5 ${
                                    approverUsername && form.config_reason.trim() && approvalStatus !== 'sent'
                                      ? 'bg-[#005b75] text-white hover:bg-[#00465a] shadow-sm'
                                      : 'bg-black/8 text-black/30 cursor-not-allowed'
                                  }`}
                                >
                                  {approvalStatus === 'sending' ? <RotateCcw className="w-3 h-3 animate-spin" /> : (zh ? '发验证码' : 'Send Code')}
                                </button>
                              </div>
                            </div>
                          </div>

                          {approvalStatus === 'sent' && (
                            <div className="space-y-1.5 pt-2 border-t border-black/5">
                              <label className="text-[11px] text-black/50 block">{zh ? '输入 6 位工单验证码' : 'Enter 6-digit verification code'}</label>
                              <div className="flex items-center gap-2">
                                <input
                                  value={approvalCode} onChange={e => { setApprovalCode(e.target.value.replace(/\D/g, '').slice(0, 6)); setApprovalError(''); }}
                                  placeholder="000000" maxLength={6}
                                  className="w-32 tracking-[0.3em] text-center font-mono rounded-xl border border-black/10 py-2 text-sm outline-none focus:border-emerald-500 transition-all"
                                />
                                <button
                                  type="button" onClick={verifyApproval} disabled={approvalCode.length !== 6}
                                  className={`px-4 py-2 rounded-xl font-bold transition-all ${approvalCode.length === 6 ? 'bg-emerald-600 text-white hover:bg-emerald-700' : 'bg-black/8 text-black/30 cursor-not-allowed'}`}
                                >
                                  {zh ? '验证' : 'Verify'}
                                </button>
                                <button onClick={resetApproval} className="p-2 text-black/30 hover:text-black/50 ml-1" title={zh ? '重置审批状态' : 'Reset'}>
                                  <RotateCcw size={14} />
                                </button>
                              </div>
                            </div>
                          )}

                          {approvalError && (
                            <div className="flex items-center gap-1.5 text-rose-600 text-[11px] pt-1">
                              <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                              <span>{approvalError}</span>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                {/* Bottom Submit */}
                <div className="border-t border-black/5 pt-5 flex items-center justify-end gap-3">
                  <button
                    onClick={() => { setShowAddInspSchedule(false); resetApproval(); }}
                    className="px-6 py-2.5 rounded-xl border border-black/10 text-sm font-semibold text-black/50 hover:bg-black/5 transition-all"
                  >
                    {zh ? '取消' : 'Cancel'}
                  </button>
                  <button
                    onClick={addInspSchedule}
                    disabled={!form.name.trim() || !form.scheduled_at || approvalStatus !== 'verified'}
                    className="px-8 py-2.5 rounded-xl bg-[#164e63] text-white text-sm font-bold shadow-lg shadow-cyan-900/10 hover:bg-[#0891b2] transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {zh ? '发布执行计划' : 'Publish Schedule'}
                  </button>
                </div>
              </motion.div>
            ) : (
              /* ── LIST VIEW ── */
              <motion.div
                key="list-view"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="space-y-4"
              >
                <div className="rounded-2xl border border-black/5 bg-white shadow-sm overflow-hidden min-h-[500px] flex flex-col">
                  {/* Table Header / Toolbar */}
                  <div className="px-6 py-4 border-b border-black/5 bg-black/[0.01] flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-lg bg-cyan-50 flex items-center justify-center">
                        <CalendarClock size={16} className="text-cyan-600" />
                      </div>
                      <h3 className="text-sm font-bold text-[#164e63]">{zh ? '当前计划列表' : 'Active Schedules'}</h3>
                    </div>
                    <div className="text-[11px] font-bold text-black/25 uppercase tracking-widest tabular-nums">
                      {inspScheduleTotal} {zh ? '个项目' : 'Items'}
                    </div>
                  </div>

                  {/* List Body */}
                  <div className="flex-1 overflow-y-auto max-h-[calc(100vh-420px)] custom-scrollbar">
                    {inspSchedulesLoading ? (
                      <div className="h-full flex flex-col items-center justify-center py-24 text-black/20 gap-3">
                        <RotateCcw size={32} className="animate-spin opacity-20" />
                        <span className="text-sm font-medium">{zh ? '正在加载数据...' : 'Loading schedules...'}</span>
                      </div>
                    ) : inspSchedules.length > 0 ? (
                      <div className="space-y-2.5 p-4">
                        {inspSchedules.map(sch => {
                          const atInfo = ACTION_TYPES.find(a => a.value === sch.action_type);
                          const AtIcon = atInfo?.icon || Database;
                          const isEnabled = !!sch.enabled;
                          const scopeDesc = describeScope(sch.device_scope, sch.device_filter, zh);
                          const isInsp = sch.action_type === 'inspection';
                          const isBackup = sch.action_type === 'backup';
                          const isScript = sch.action_type === 'script_run';
                          const st = getScheduleStatus(sch, zh);
                          
                          return (
                            <motion.div
                              key={sch.id}
                              layout
                              initial={{ opacity: 0, y: 8 }}
                              animate={{ opacity: 1, y: 0 }}
                              onClick={() => { setSelectedSchedule(sch); setShowScheduleDetail(true); }}
                              className={`rounded-2xl border transition-all hover:shadow-md cursor-pointer group overflow-hidden ${
                                isEnabled ? 'bg-white border-slate-200/90 shadow-sm' : 'bg-slate-50 border-slate-200/50 opacity-60'
                              }`}
                            >
                              <div className="flex items-center gap-4 px-5 py-4">
                                {/* Category Icon */}
                                <div className={`w-11 h-11 rounded-xl flex items-center justify-center shrink-0 border ${
                                  isEnabled
                                    ? isInsp ? 'bg-emerald-50 text-emerald-600 border-emerald-100'
                                      : isBackup ? 'bg-indigo-50 text-indigo-600 border-indigo-100'
                                      : isScript ? 'bg-amber-50 text-amber-600 border-amber-100'
                                      : 'bg-cyan-50 text-cyan-600 border-cyan-100'
                                    : 'bg-slate-100 text-slate-400 border-slate-200'
                                }`}>
                                  <AtIcon size={20} />
                                </div>

                                {/* Main info */}
                                <div className="flex-1 min-w-0">
                                  <div className="flex items-center gap-2.5">
                                    <p className="text-sm font-bold text-[#0f172a] truncate group-hover:text-cyan-700 transition-colors">
                                      {sch.name}
                                    </p>
                                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
                                      st.icon === 'ready' || st.icon === 'pending' ? 'bg-cyan-100/80 text-cyan-700 border border-cyan-200' :
                                      st.icon === 'done' ? 'bg-emerald-100 text-emerald-700 border border-emerald-200' :
                                      'bg-slate-100 text-slate-500 border border-slate-200'
                                    }`}>
                                      {st.label}
                                    </span>
                                    {sch.last_run_status && (
                                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
                                        sch.last_run_status === 'success'
                                          ? 'bg-emerald-50 text-emerald-600 border border-emerald-100'
                                          : 'bg-rose-50 text-rose-600 border border-rose-100'
                                      }`}>
                                        <div className={`w-1.5 h-1.5 rounded-full ${sch.last_run_status === 'success' ? 'bg-emerald-500' : 'bg-rose-500'}`} />
                                        {sch.last_run_status === 'success' ? (zh ? '执行成功' : 'Success') : (zh ? '执行失败' : 'Failed')}
                                      </span>
                                    )}
                                    {sch.use_admin_creds ? (
                                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-amber-50 text-amber-700 border border-amber-200 shadow-sm">
                                        <ShieldAlert size={12} className="text-amber-600" />
                                        {zh ? '特权执行 (Admin)' : 'Privileged'}
                                      </span>
                                    ) : (
                                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-slate-100 text-slate-600 border border-slate-200 shadow-sm">
                                        <User size={12} className="text-slate-500" />
                                        {zh ? '普通执行 (User)' : 'Normal'}
                                      </span>
                                    )}
                                  </div>

                                  <div className="flex items-center gap-3 mt-1.5 text-xs text-slate-500 flex-wrap">
                                    <span className="flex items-center gap-1 font-mono font-semibold text-slate-700 bg-slate-100 px-2 py-0.5 rounded">
                                      <CalendarClock size={12} className="text-cyan-600" />
                                      {fmtDateTime(sch.scheduled_at, zh)}
                                    </span>
                                    <span className="text-slate-300">·</span>
                                    <span className={`font-semibold ${isInsp ? 'text-emerald-700' : isBackup ? 'select-none text-indigo-700' : isScript ? 'text-amber-700' : 'text-slate-700'}`}>
                                      {zh ? (atInfo?.labelZh || sch.action_type) : (atInfo?.labelEn || sch.action_type)}
                                    </span>
                                    <span className="text-slate-300">·</span>
                                    <span className="flex items-center gap-1 text-slate-600 font-medium">
                                      <Target size={12} className="text-slate-400" />
                                      {scopeDesc}
                                    </span>

                                    {sch.action_type === 'script_run' && sch.script_id && (
                                      <>
                                        <span className="text-slate-300">·</span>
                                        <span className="flex items-center gap-1 text-[#00a9ce] font-bold bg-cyan-50 px-2 py-0.5 rounded border border-cyan-100">
                                          <FileCode size={12} />
                                          {(availableScripts || []).find(s => s.id === sch.script_id)?.name || sch.script_id}
                                        </span>
                                      </>
                                    )}
                                    {sch.last_run_at && (
                                      <>
                                        <span className="text-slate-300">·</span>
                                        <span>{zh ? '最近运行' : 'Last run'}: <span className="font-mono">{new Date(sch.last_run_at).toLocaleString(zh ? 'zh-CN' : 'en-US', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}</span></span>
                                      </>
                                    )}
                                  </div>
                                </div>

                                {/* Actions */}
                                <div className="flex items-center gap-1 shrink-0" onClick={e => e.stopPropagation()}>
                                  <button
                                    onClick={() => toggleInspScheduleEnabled(sch)}
                                    className={`p-2 rounded-xl transition-all ${isEnabled ? 'text-slate-400 hover:bg-amber-50 hover:text-amber-600' : 'text-slate-400 hover:bg-emerald-50 hover:text-emerald-600'}`}
                                    title={isEnabled ? (zh ? '停用' : 'Disable') : (zh ? '启用' : 'Enable')}
                                  >
                                    <Activity size={16} />
                                  </button>
                                  <button
                                    onClick={() => deleteInspSchedule(sch.id)}
                                    className="p-2 rounded-xl text-slate-400 hover:bg-rose-50 hover:text-rose-600 transition-all"
                                    title={zh ? '删除' : 'Delete'}
                                  >
                                    <Trash2 size={16} />
                                  </button>
                                </div>
                              </div>

                              {/* Bottom meta */}
                              <div className="px-5 py-2.5 bg-slate-50/80 border-t border-slate-100 flex items-center gap-4 text-[11px] text-slate-500">
                                {sch.description && (
                                  <>
                                    <span className="text-slate-600 italic truncate max-w-[200px]">{sch.description}</span>
                                    <span className="text-slate-300">|</span>
                                  </>
                                )}
                                <span>{zh ? '审批授权人' : 'Approver'}: <span className="font-bold text-slate-700">{sch.approved_by || '\u2014'}</span></span>
                                <span className="text-slate-300">|</span>
                                <span>{zh ? '创建者' : 'Creator'}: <span className="font-medium text-slate-700">{sch.created_by}</span> · <span className="font-mono">{new Date(sch.created_at).toLocaleDateString(zh ? 'zh-CN' : 'en-US')}</span></span>
                              </div>
                            </motion.div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="h-full flex flex-col items-center justify-center py-32 text-black/20 gap-3">
                        <CalendarClock size={48} strokeWidth={1} className="opacity-10" />
                        <div className="text-center">
                          <p className="text-sm font-bold text-black/30">{zh ? '暂无任何执行计划' : 'No schedules found'}</p>
                          <p className="text-[11px] mt-1">{zh ? '点击右上角「新建计划」开始自动化巡检' : 'Click "Add Schedule" to start automation'}</p>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Pagination Section */}
                  {inspScheduleTotal > 0 && (
                    <div className="mt-auto">
                      <Pagination
                        currentPage={inspSchedulePage}
                        totalItems={inspScheduleTotal}
                        itemsPerPage={inspSchedulePageSize}
                        onPageChange={setInspSchedulePage}
                        onItemsPerPageChange={setInspSchedulePageSize}
                        language={language}
                      />
                    </div>
                  )}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}

      {/* ── History sub-tab ── */}
      {inspSubTab === 'history' && (
        <div className="space-y-4">
          <div className="rounded-2xl border border-black/5 bg-white shadow-sm overflow-hidden min-h-[500px] flex flex-col">
            <div className="px-6 py-4 border-b border-black/5 bg-black/[0.01] flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-indigo-50 flex items-center justify-center">
                  <Activity size={16} className="text-indigo-600" />
                </div>
                <h3 className="text-sm font-bold text-[#164e63]">{zh ? '执行流水历史' : 'Execution Logs'}</h3>
              </div>
              
              <div className="flex items-center gap-4">
                {/* Type Filter Buttons */}
                <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-xl">
                  {(['all', 'manual', 'plan', 'job'] as const).map(type => {
                    const labels = {
                      all: zh ? '全部' : 'All',
                      manual: zh ? '手动执行' : 'Manual',
                      plan: zh ? '执行计划' : 'Plan',
                      job: zh ? '定时作业' : 'Job',
                    };
                    return (
                      <button
                        key={type}
                        onClick={() => { setExecutionTypeFilter(type); setInspRunPage(1); }}
                        className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-all ${
                          executionTypeFilter === type 
                            ? 'bg-white text-[#164e63] shadow-sm' 
                            : 'text-black/50 hover:text-black/70'
                        }`}
                      >
                        {labels[type]}
                      </button>
                    );
                  })}
                </div>

                <div className="text-[11px] font-bold text-black/25 uppercase tracking-widest tabular-nums">
                  {filteredLogs.length} {zh ? '条记录' : 'Logs'}
                </div>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto max-h-[calc(100vh-380px)] custom-scrollbar">
              {inspRunsLoading ? (
                <div className="h-full flex flex-col items-center justify-center py-24 text-black/20 gap-3">
                  <RotateCcw size={32} className="animate-spin opacity-20" />
                  <span className="text-sm font-medium">{zh ? '获取流水中...' : 'Loading history...'}</span>
                </div>
              ) : paginatedLogs.length > 0 ? (
                <table className="w-full text-left border-collapse min-w-[1000px]">
                  <thead className="sticky top-0 bg-slate-50 border-b border-black/5 z-10">
                    <tr className="bg-black/[0.01]">
                      <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{zh ? '触发时间' : 'Triggered At'}</th>
                      <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{zh ? '任务名称' : 'Task Name'}</th>
                      <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{zh ? '执行方式' : 'Type'}</th>
                      <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{zh ? '状态' : 'Status'}</th>
                      <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{zh ? '执行概况' : 'Execution Summary'}</th>
                      <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{zh ? '执行人' : 'Operator'}</th>
                      <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider text-right">{zh ? '操作' : 'Actions'}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-black/[0.03]">
                    {paginatedLogs.map(log => {
                      const statusMap: Record<string, { label: string; cls: string; dot: string }> = {
                        completed: { label: zh ? '已完成' : 'Completed', cls: 'bg-emerald-50 text-emerald-700', dot: 'bg-emerald-500' },
                        success: { label: zh ? '已完成' : 'Completed', cls: 'bg-emerald-50 text-emerald-700', dot: 'bg-emerald-500' },
                        running: { label: zh ? '执行中' : 'Running', cls: 'bg-cyan-50 text-cyan-700', dot: 'bg-cyan-500' },
                        failed: { label: zh ? '已失败' : 'Failed', cls: 'bg-red-50 text-red-700', dot: 'bg-red-500' },
                      };
                      const st = statusMap[log.status] || { label: log.status, cls: 'bg-slate-50 text-slate-600', dot: 'bg-slate-400' };
                      
                      const typeLabels = {
                        manual: { label: zh ? '手动执行' : 'Manual', cls: 'bg-violet-50 text-violet-600 border-violet-100' },
                        plan: { label: zh ? '执行计划' : 'Execution Plan', cls: 'bg-blue-50 text-blue-600 border-blue-100' },
                        job: { label: zh ? '定时作业' : 'Scheduled Job', cls: 'bg-amber-50 text-amber-600 border-amber-100' },
                      };
                      const tl = typeLabels[log.trigger_type] || { label: log.trigger_type, cls: 'bg-slate-50 text-slate-600 border-slate-100' };

                      return (
                        <tr key={`${log.source}-${log.id}`} className="hover:bg-indigo-50/20 transition-colors">
                          <td className="px-6 py-4 text-[13px] text-[#164e63] font-mono whitespace-nowrap">
                            {new Date(log.started_at).toLocaleString(zh ? 'zh-CN' : 'en-US', { hour12: false })}
                          </td>
                          <td className="px-6 py-4 text-xs font-bold text-black/80">
                            {log.name}
                          </td>
                          <td className="px-6 py-4">
                            <span className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wide border ${tl.cls}`}>
                              {log.trigger_type === 'manual' ? <Play size={10} /> : log.trigger_type === 'plan' ? <CalendarClock size={10} /> : <Clock size={10} />}
                              {tl.label}
                            </span>
                          </td>
                          <td className="px-6 py-4">
                            <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-bold ${st.cls}`}>
                              <div className={`w-1.5 h-1.5 rounded-full ${log.status === 'running' ? 'animate-pulse' : ''} ${st.dot}`} />
                              {st.label}
                            </span>
                          </td>
                          <td className="px-6 py-4">
                            <div className="flex flex-col">
                              <span className="text-xs font-bold text-black/60">{log.total_devices} {zh ? '台设备' : 'Devices'}</span>
                              <div className="flex items-center gap-1.5 mt-1">
                                {log.source === 'inspection' ? (
                                  <>
                                    <span className="text-[10px] text-black/40">{zh ? '平均分' : 'Avg Score'}:</span>
                                    <span className={`text-[11px] font-black tabular-nums ${
                                    (log.avg_health_score || 0) >= 80 ? 'text-emerald-600' : (log.avg_health_score || 0) >= 60 ? 'text-amber-600' : 'text-red-600'
                                    }`}>
                                      {log.avg_health_score?.toFixed(1) ?? '—'}
                                    </span>
                                  </>
                                ) : (
                                  <>
                                    <div className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                                    <span className="text-[10px] text-emerald-600 font-bold">{log.success_count}</span>
                                    <div className="w-1.5 h-1.5 rounded-full bg-red-400 ml-1" />
                                    <span className="text-[10px] text-red-600 font-bold">{log.failed_count}</span>
                                  </>
                                )}
                              </div>
                            </div>
                          </td>
                          <td className="px-6 py-4">
                            <span className="text-xs font-bold text-black/40">{log.created_by}</span>
                          </td>
                          <td className="px-6 py-4 text-right">
                            <div className="flex items-center justify-end gap-2">
                              <button
                                onClick={() => handleSelectLog(log)}
                                className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-bold text-cyan-600 border border-cyan-100 bg-cyan-50/20 hover:bg-cyan-50 transition-all active:scale-95"
                              >
                                <Eye size={12} />
                                {zh ? '查看' : 'View'}
                              </button>
                              
                              {/* ── R7.1: 标准化导出按钮组 ── */}
                              <div className="flex items-center gap-1 ml-2 pl-2 border-l border-black/5">
                                <button
                                  onClick={() => handleExportReport(log.id, 'html', log.source)}
                                  className="p-1.5 rounded-lg text-indigo-600 hover:bg-indigo-50 transition-all active:scale-90"
                                  title={zh ? '导出 HTML' : 'Export HTML'}
                                >
                                  <FileText size={14} />
                                </button>
                                <button
                                  onClick={() => handleExportReport(log.id, 'pdf', log.source)}
                                  className="p-1.5 rounded-lg text-rose-600 hover:bg-rose-50 transition-all active:scale-90"
                                  title={zh ? '导出 PDF' : 'Export PDF'}
                                >
                                  <FileText size={14} />
                                </button>
                                <button
                                  onClick={() => handleExportReport(log.id, 'xlsx', log.source)}
                                  className="p-1.5 rounded-lg text-emerald-600 hover:bg-emerald-50 transition-all active:scale-90"
                                  title={zh ? '导出 Excel' : 'Export Excel'}
                                >
                                  <FileSpreadsheet size={14} />
                                </button>
                                <button
                                  onClick={() => handleExportReport(log.id, 'json', log.source)}
                                  className="p-1.5 rounded-lg text-slate-600 hover:bg-slate-50 transition-all active:scale-90"
                                  title={zh ? '导出 JSON' : 'Export JSON'}
                                >
                                  <FileJson size={14} />
                                </button>
                              </div>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              ) : (
                <div className="h-full flex flex-col items-center justify-center py-32 text-black/20 gap-3">
                  <Activity size={48} strokeWidth={1} className="opacity-10" />
                  <p className="text-sm font-bold text-black/30">{zh ? '暂无历史执行记录' : 'No history found'}</p>
                </div>
              )}
            </div>

            {filteredLogs.length > 0 && (
              <div className="mt-auto">
                <Pagination
                  currentPage={inspRunPage}
                  totalItems={filteredLogs.length}
                  onPageChange={setInspRunPage}
                  itemsPerPage={inspRunPageSize}
                  onItemsPerPageChange={setInspRunPageSize}
                  language={language}
                />
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Detail Modal ── */}
      <AnimatePresence>
    {isDetailModalOpen && selectedLog && (
      <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 sm:p-6 lg:p-8">
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={() => setIsDetailModalOpen(false)}
          className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        />
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 20 }}
          className="relative bg-white rounded-[2rem] shadow-2xl w-full max-w-6xl h-[90vh] overflow-hidden flex flex-col z-10 border border-black/10"
        >
          <div className="px-6 py-4 border-b border-black/5 flex items-center justify-between bg-black/[0.015] flex-shrink-0">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-indigo-50 flex items-center justify-center text-indigo-600 border border-indigo-100">
                <Activity size={18} />
              </div>
              <div>
                <h3 className="text-base font-bold text-[#164e63]">
                  {selectedLog.name}
                </h3>
                <p className="text-[10px] text-black/30 font-mono mt-0.5">ID: {selectedLog.id}</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {/* ── R7.1: 详情弹窗标准化导出按钮组 ── */}
              <div className="flex items-center gap-1 bg-black/5 p-1 rounded-xl mr-2">
                <button
                  onClick={() => handleExportReport(selectedLog.id, 'html', selectedLog.source)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold text-indigo-700 hover:bg-white transition-all shadow-sm"
                >
                  <FileText size={14} />
                  HTML
                </button>
                <button
                  onClick={() => handleExportReport(selectedLog.id, 'pdf', selectedLog.source)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold text-rose-700 hover:bg-white transition-all shadow-sm"
                >
                  <FileText size={14} />
                  PDF
                </button>
                <button
                  onClick={() => handleExportReport(selectedLog.id, 'xlsx', selectedLog.source)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold text-emerald-700 hover:bg-white transition-all shadow-sm"
                >
                  <FileSpreadsheet size={14} />
                  Excel
                </button>
                <button
                  onClick={() => handleExportReport(selectedLog.id, 'json', selectedLog.source)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold text-slate-700 hover:bg-white transition-all shadow-sm"
                >
                  <FileJson size={14} />
                  JSON
                </button>
              </div>
              <button
                onClick={() => setIsDetailModalOpen(false)}
                className="p-2 rounded-xl text-black/20 hover:bg-black/5 hover:text-black/40 transition-all"
              >
                <X size={20} />
              </button>
            </div>
          </div>

          {/* Modal Content */}
          <div className="flex-1 overflow-hidden relative">
            {logDetailLoading ? (
              <div className="h-full flex flex-col items-center justify-center text-black/20 gap-3">
                <RotateCcw size={32} className="animate-spin opacity-20" />
                <span className="text-xs font-bold">{zh ? '加载详情中...' : 'Loading details...'}</span>
              </div>
            ) : (selectedLog && selectedLog.source === 'inspection') ? (
              /* Inspection Details View - Upgraded to Split-Pane Layout */
              <div className="flex flex-col md:flex-row h-full">
                {/* Device List (Left) */}
                <div className="w-full md:w-4/12 border-r border-black/5 flex flex-col h-full bg-slate-50/50">
                  <div className="p-4 border-b border-black/5 bg-white flex items-center justify-between">
                    <span className="text-xs font-bold text-black/50">{zh ? '设备巡检结果' : 'Inspection Results'}</span>
                    <span className="text-[10px] font-bold text-black/20 uppercase tracking-widest tabular-nums">
                      {inspectionDetail?.results?.length || 0} {zh ? '台设备' : 'Devices'}
                    </span>
                  </div>
                  <div className="flex-1 overflow-auto p-2 space-y-1 custom-scrollbar">
                    {(inspectionDetail?.results || []).map((res: any) => {
                      const isSelected = selectedInspDeviceId === res.device_id;
                      return (
                        <div
                          key={res.id}
                          onClick={() => {
                            setSelectedInspDeviceId(res.device_id);
                            setCollapsedCmds({});
                            setInspParseResults({});
                          }}
                          className={`flex items-center justify-between p-3 rounded-xl border cursor-pointer transition-all ${
                            isSelected 
                              ? 'bg-[#164e63] text-white border-transparent shadow-md' 
                              : 'bg-white border-black/5 hover:border-black/10 hover:shadow-sm'
                          }`}
                        >
                          <div className="min-w-0">
                            <p className={`text-xs font-bold truncate ${isSelected ? 'text-white' : 'text-[#164e63]'}`}>{res.hostname}</p>
                            <div className="flex items-center gap-2 mt-0.5">
                              <p className={`text-[9px] font-mono ${isSelected ? 'text-white/60' : 'text-black/30'}`}>{res.ip_address}</p>
                              <span className={`text-[9px] font-bold ${isSelected ? 'text-cyan-300' : 'text-cyan-600'}`}>Score: {res.health_score ?? '—'}</span>
                            </div>
                          </div>
                          <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${
                            res.health_status === 'healthy' 
                              ? (isSelected ? 'bg-emerald-400/20 text-emerald-300' : 'bg-emerald-50 text-emerald-600')
                              : res.health_status === 'warning'
                                ? (isSelected ? 'bg-amber-400/20 text-amber-300' : 'bg-amber-50 text-amber-600')
                                : (isSelected ? 'bg-red-400/20 text-red-300' : 'bg-red-50 text-red-600')
                          }`}>
                            {res.health_status === 'healthy' ? (zh ? '健康' : 'OK') : res.health_status === 'warning' ? (zh ? '警告' : 'WARN') : (zh ? '故障' : 'CRIT')}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Detail Content (Right) */}
                <div className="flex-1 flex flex-col bg-[#1E1E1E] overflow-hidden">
                  {selectedInspDeviceId ? (() => {
                    const res = inspectionDetail.results.find((r: any) => r.device_id === selectedInspDeviceId);
                    if (!res) return null;
                    
                    let rawOutputs: Record<string, string> = {};
                    try { rawOutputs = typeof res.raw_outputs_json === 'string' ? JSON.parse(res.raw_outputs_json) : (res.raw_outputs_json || {}); } catch(e) {}
                    
                    let analysis: any[] = [];
                    try { analysis = typeof res.analysis_json === 'string' ? JSON.parse(res.analysis_json) : (res.analysis_json || []); } catch(e) {}

                    let findings: any[] = [];
                    try { findings = typeof res.findings_json === 'string' ? JSON.parse(res.findings_json) : (res.findings_json || []); } catch(e) {}

                    // R3: parse metrics_json and correlated_risks_json
                    let metricsObj: Record<string, any> = {};
                    try { metricsObj = typeof res.metrics_json === 'string' ? JSON.parse(res.metrics_json) : (res.metrics_json || {}); } catch(e) {}

                    let correlatedRisks: any[] = [];
                    try { correlatedRisks = typeof res.correlated_risks_json === 'string' ? JSON.parse(res.correlated_risks_json) : (res.correlated_risks_json || []); } catch(e) {}

                    // R3.8: 合规项（来自 analysis 中 category=compliance）
                    const complianceItems = analysis.filter((a: any) => (a.category === 'compliance') || (a.key && String(a.key).includes('compliance')));

                    return (
                      <>
                        <div className="p-4 border-b border-white/10 bg-black/20 flex items-center justify-between">
                          <div className="flex flex-col gap-1">
                            <span className="text-xs text-white/80 font-bold block">{res.hostname} ({res.ip_address})</span>
                            <div className="flex items-center gap-2">
                              <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded bg-white/5 ${
                                res.ping_ok ? 'text-emerald-400' : 'text-red-400'
                              }`}>Ping: {res.ping_ok ? 'OK' : 'FAIL'}</span>
                              <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded bg-white/5 ${
                                res.ssh_ok ? 'text-emerald-400' : 'text-red-400'
                              }`}>SSH: {res.ssh_ok ? 'OK' : 'FAIL'}</span>
                              {res.ssh_error && <span className="text-[10px] text-red-400/70 truncate max-w-[200px]" title={res.ssh_error}>{res.ssh_error}</span>}
                            </div>
                          </div>
                          <div className="flex flex-col items-end gap-1">
                            <div className="text-[10px] text-white/30 font-mono uppercase tracking-widest">{zh ? '健康得分' : 'Health Score'}</div>
                            <div className={`text-xl font-black ${
                              (res.health_score || 0) >= 90 ? 'text-emerald-400' : (res.health_score || 0) >= 60 ? 'text-amber-400' : 'text-red-400'
                            }`}>{res.health_score ?? '—'}</div>
                          </div>
                        </div>

                        <div className="flex-1 overflow-auto custom-scrollbar-dark p-6 space-y-8 select-text">
                          {/* R3.1: Tab bar */}
                          <div className="flex items-center gap-1 border-b border-white/10 -mt-2 -mx-2 px-2">
                            {([
                              { key: 'analysis', label: zh ? '指标分析' : 'Analysis' },
                              { key: 'snapshot', label: zh ? '指标快照' : 'Snapshot' },
                              { key: 'compliance', label: zh ? '合规检查' : 'Compliance' },
                              { key: 'raw', label: zh ? '原始输出' : 'Raw Output' },
                            ] as { key: InspDetailTab; label: string }[]).map(t => (
                              <button
                                key={t.key}
                                onClick={() => { setInspDetailTab(t.key); setTrendData(null); }}
                                className={`px-3 py-1.5 text-[11px] font-bold uppercase tracking-wider transition-colors ${
                                  inspDetailTab === t.key ? 'text-cyan-400 border-b-2 border-cyan-400' : 'text-white/40 hover:text-white/70'
                                }`}
                              >
                                {t.label}
                              </button>
                            ))}
                          </div>

                          {/* TAB: 指标分析 (R3.2-R3.4, R3.9) */}
                          {inspDetailTab === 'analysis' && (
                            <div className="space-y-4">
                              {/* R3.9: Correlated risks card at top */}
                              {correlatedRisks.length > 0 && (
                                <div className="space-y-2">
                                  <h4 className="text-[11px] font-bold text-red-400 uppercase tracking-widest flex items-center gap-2">
                                    <AlertTriangle size={12} />
                                    {zh ? '关联风险预警' : 'Correlated Risk Alerts'}
                                  </h4>
                                  {correlatedRisks.map((risk, i) => (
                                    <div key={i} className={`p-3 rounded-lg border ${
                                      risk.severity === 'critical' ? 'bg-red-500/10 border-red-500/30' : 'bg-amber-500/10 border-amber-500/30'
                                    }`}>
                                      <div className="flex items-start justify-between gap-2">
                                        <div className="flex-1">
                                          <div className="text-xs font-bold text-white/90 mb-1">⚠️ {risk.rule_name}</div>
                                          <div className="text-[11px] text-white/60 leading-relaxed">{risk.description}</div>
                                          {risk.suggestion && <div className="text-[11px] text-cyan-400/70 mt-1.5">💡 {risk.suggestion}</div>}
                                        </div>
                                        <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded shrink-0 ${
                                          risk.severity === 'critical' ? 'bg-red-500/30 text-red-300' : 'bg-amber-500/30 text-amber-300'
                                        }`}>{risk.severity?.toUpperCase()}</span>
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              )}

                              {/* Trend chart (R5.6) */}
                              {trendData && (
                                <div className="rounded-lg border border-cyan-500/20 bg-black/30 p-4">
                                  <div className="flex items-center justify-between mb-3">
                                    <span className="text-[11px] font-bold text-cyan-400">
                                      {zh ? '趋势：' : 'Trend: '}{trendData.metric}
                                    </span>
                                    <button
                                      onClick={() => setTrendData(null)}
                                      className="text-[10px] text-white/30 hover:text-white/60"
                                    >✕</button>
                                  </div>
                                  {trendLoading ? (
                                    <div className="text-center py-6 text-white/30 text-xs">{zh ? '加载中...' : 'Loading...'}</div>
                                  ) : trendData.series.length > 0 ? (
                                    <ResponsiveContainer width="100%" height={200}>
                                      <LineChart data={trendData.series}>
                                        <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
                                        <XAxis dataKey="ts" stroke="#64748b" fontSize={10} tickFormatter={(v) => String(v).slice(5, 16)} />
                                        <YAxis stroke="#64748b" fontSize={10} />
                                        <RTooltip contentStyle={{ background: '#1e293b', border: '1px solid #334155', fontSize: 11 }} />
                                        <Line type="monotone" dataKey="value" stroke="#00bceb" strokeWidth={2} dot={false} />
                                      </LineChart>
                                    </ResponsiveContainer>
                                  ) : (
                                    <div className="text-center py-6 text-white/30 text-xs italic">
                                      {zh ? '暂无历史数据，首次巡检后将自动记录' : 'No history yet — data appears after future runs'}
                                    </div>
                                  )}
                                </div>
                              )}

                              {/* R3.2: Analysis table */}
                              {analysis.length > 0 ? (
                                <table className="w-full text-[11px]">
                                  <thead>
                                    <tr className="text-white/50 border-b border-white/10">
                                      <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '指标' : 'Metric'}</th>
                                      <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '当前值' : 'Value'}</th>
                                      <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '状态' : 'Status'}</th>
                                      <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '诊断结论' : 'Conclusion'}</th>
                                      <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '建议' : 'Suggestion'}</th>
                                      <th className="text-right py-2 px-2 font-bold uppercase tracking-wider">{zh ? '操作' : 'Actions'}</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {analysis.map((a, i) => {
                                      const rowBg = a.status === 'critical' ? 'bg-red-500/10' : a.status === 'warning' ? 'bg-amber-500/10' : '';
                                      const isNumeric = typeof a.value === 'number';
                                      return (
                                        <tr key={i} className={`${rowBg} border-b border-white/5`}>
                                          <td className="py-2 px-2 text-white/90 font-bold">{a.metric}</td>
                                          <td className="py-2 px-2 text-white/70 font-mono">{String(a.value ?? '—')}</td>
                                          <td className="py-2 px-2">
                                            <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${
                                              a.status === 'critical' ? 'bg-red-500/30 text-red-300' : a.status === 'warning' ? 'bg-amber-500/30 text-amber-300' : 'bg-emerald-500/30 text-emerald-300'
                                            }`}>{a.status?.toUpperCase()}</span>
                                          </td>
                                          <td className="py-2 px-2 text-white/50">{a.conclusion}</td>
                                          <td className="py-2 px-2 text-white/50">{a.suggestion}</td>
                                          <td className="py-2 px-2 text-right">
                                            {isNumeric && a.key && (
                                              <button
                                                onClick={() => fetchTrend(res.device_id, a.key)}
                                                className="text-[9px] font-bold text-cyan-400 hover:text-cyan-300 px-2 py-1 rounded border border-cyan-500/30 hover:bg-cyan-500/10"
                                              >
                                                {zh ? '趋势' : 'Trend'}
                                              </button>
                                            )}
                                          </td>
                                        </tr>
                                      );
                                    })}
                                  </tbody>
                                </table>
                              ) : (
                                <div className="text-white/30 text-center py-6 text-xs italic">{zh ? '暂无分析结果' : 'No analysis available'}</div>
                              )}
                            </div>
                          )}

                          {/* TAB: 指标快照 (R3.5-R3.7) */}
                          {inspDetailTab === 'snapshot' && (
                            <div className="space-y-2">
                              {Object.keys(metricsObj).length === 0 ? (
                                <div className="text-white/30 text-center py-6 text-xs italic">{zh ? '暂无指标数据' : 'No metrics'}</div>
                              ) : (
                                <table className="w-full text-[11px]">
                                  <thead>
                                    <tr className="text-white/50 border-b border-white/10">
                                      <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '指标键' : 'Metric Key'}</th>
                                      <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '值 / 错误' : 'Value / Error'}</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {Object.entries(metricsObj).map(([key, val]) => {
                                      const isError = val && typeof val === 'object' && 'error' in (val as any);
                                      return (
                                        <tr key={key} className="border-b border-white/5">
                                          <td className={`py-2 px-2 font-mono ${isError ? 'text-red-400' : 'text-white/80'}`}>{key}</td>
                                          <td className="py-2 px-2">
                                            {isError ? (
                                              <span className="text-red-400 text-[10px]">⚠ {(val as any).error}</span>
                                            ) : (
                                              <span className="text-white/70 font-mono">{String(val)}</span>
                                            )}
                                          </td>
                                        </tr>
                                      );
                                    })}
                                  </tbody>
                                </table>
                              )}
                            </div>
                          )}

                          {/* TAB: 合规检查 (R3.8) */}
                          {inspDetailTab === 'compliance' && (
                            <div className="space-y-2">
                              {complianceItems.length === 0 ? (
                                <div className="text-white/30 text-center py-6 text-xs italic">
                                  {zh ? '暂无合规检查项' : 'No compliance checks defined'}
                                </div>
                              ) : (
                                <table className="w-full text-[11px]">
                                  <thead>
                                    <tr className="text-white/50 border-b border-white/10">
                                      <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '合规项' : 'Item'}</th>
                                      <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '当前值' : 'Value'}</th>
                                      <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '状态' : 'Status'}</th>
                                      <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '说明' : 'Description'}</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {complianceItems.map((c, i) => {
                                      const passing = c.status === 'healthy';
                                      return (
                                        <tr key={i} className="border-b border-white/5">
                                          <td className="py-2 px-2 text-white/90 font-bold">{c.metric}</td>
                                          <td className="py-2 px-2 text-white/70 font-mono">{String(c.value ?? '—')}</td>
                                          <td className="py-2 px-2">
                                            {passing ? (
                                              <span className="inline-flex items-center gap-1 text-emerald-400 text-[10px] font-bold">✓ {zh ? '通过' : 'Pass'}</span>
                                            ) : (
                                              <span className="inline-flex items-center gap-1 text-red-400 text-[10px] font-bold">✗ {zh ? '失败' : 'Fail'}</span>
                                            )}
                                          </td>
                                          <td className="py-2 px-2 text-white/50">{c.conclusion}</td>
                                        </tr>
                                      );
                                    })}
                                  </tbody>
                                </table>
                              )}
                            </div>
                          )}

                          {/* TAB: 原始输出 (existing) */}
                          {inspDetailTab === 'raw' && (
                          <>
                          {/* 1. Findings Section */}
                          {findings.length > 0 && (
                            <div className="space-y-3">
                              <h4 className="text-[11px] font-bold text-white/40 uppercase tracking-widest flex items-center gap-2">
                                <AlertTriangle size={12} className="text-amber-500" />
                                {zh ? '异常发现' : 'Diagnostic Findings'}
                              </h4>
                              <div className="space-y-2">
                                {findings.map((f, i) => (
                                  <div key={i} className={`p-3 rounded-lg border flex items-start gap-3 ${
                                    f.severity === 'critical' ? 'bg-red-500/10 border-red-500/20 text-red-400' : 'bg-amber-500/10 border-amber-500/20 text-amber-400'
                                  }`}>
                                    <div className="mt-1 w-1.5 h-1.5 rounded-full bg-current" />
                                    <span className="text-xs font-medium leading-relaxed">{f.message}</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}

                          {/* 2. Analysis Blocks */}
                          {analysis.length > 0 && (
                            <div className="space-y-3">
                              <h4 className="text-[11px] font-bold text-white/40 uppercase tracking-widest flex items-center gap-2">
                                <Activity size={12} className="text-cyan-500" />
                                {zh ? '智能分析' : 'Smart Analysis'}
                              </h4>
                              <div className="grid grid-cols-1 gap-3">
                                {analysis.map((a, i) => (
                                  <div key={i} className="p-3 rounded-lg bg-white/5 border border-white/10 hover:bg-white/[0.08] transition-colors">
                                    <div className="flex items-center justify-between mb-2">
                                      <span className="text-[11px] font-bold text-white/80">{a.metric}</span>
                                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                                        a.status === 'healthy' ? 'text-emerald-400 bg-emerald-400/10' : a.status === 'warning' ? 'text-amber-400 bg-amber-400/10' : 'text-red-400 bg-red-400/10'
                                      }`}>{a.status?.toUpperCase()}</span>
                                    </div>
                                    <div className="text-xs text-white/50 leading-relaxed">{a.conclusion}</div>
                                    {a.value !== undefined && (
                                      <div className="mt-2 text-[10px] font-mono text-white/30 italic">Value: {String(a.value)}</div>
                                    )}
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}

                          {/* 3. Raw Output Blocks */}
                          <div className="space-y-3">
                            <div className="flex items-center justify-between">
                              <h4 className="text-[11px] font-bold text-white/40 uppercase tracking-widest flex items-center gap-2">
                                <FileText size={12} className="text-indigo-400" />
                                {zh ? '命令执行记录' : 'Command Execution Blocks'}
                              </h4>
                              {Object.keys(rawOutputs).length > 1 && (
                                <div className="flex items-center gap-3">
                                  <button 
                                    onClick={() => expandAllCmds(Object.keys(rawOutputs))}
                                    className="text-[10px] font-bold text-cyan-400/50 hover:text-cyan-400 transition-colors"
                                  >
                                    {zh ? '全部展开' : 'Expand All'}
                                  </button>
                                  <div className="w-px h-2 bg-white/10" />
                                  <button 
                                    onClick={() => collapseAllCmds(Object.keys(rawOutputs))}
                                    className="text-[10px] font-bold text-white/20 hover:text-white/40 transition-colors"
                                  >
                                    {zh ? '全部折叠' : 'Collapse All'}
                                  </button>
                                </div>
                              )}
                            </div>
                            <div className="space-y-3">
                              {Object.keys(rawOutputs).length > 0 ? (
                                Object.entries(rawOutputs).map(([cmd, output], i) => {
                                  const outputStr = String(output);
                                  const isError = outputStr.startsWith('__ERROR__') || outputStr.includes('% Invalid input') || outputStr.includes('error');
                                  const isCollapsed = collapsedCmds[cmd] ?? (!isError && Object.keys(rawOutputs).length > 3);
                                  const blockKey = `${res.device_id}::${cmd}`;
                                  const parseState = inspParseResults[blockKey];
                                  const isCopied = inspCopiedKey === blockKey;

                                  return (
                                    <div key={i} className={`rounded-lg overflow-hidden border transition-all ${
                                      isError ? 'border-red-500/30 bg-red-500/5' : 'border-white/5 bg-black/20'
                                    }`}>
                                      <div
                                        onClick={() => toggleCmdCollapse(cmd)}
                                        className="px-4 py-2 bg-white/5 flex items-center justify-between cursor-pointer hover:bg-white/[0.08]"
                                      >
                                        <div className="flex items-center gap-2 min-w-0">
                                          <ChevronRight size={14} className={`text-white/20 transition-transform shrink-0 ${isCollapsed ? '' : 'rotate-90'}`} />
                                          <span className={`text-[11px] font-mono font-bold truncate ${isError ? 'text-red-400' : 'text-cyan-400/80'}`}>&gt; {cmd}</span>
                                        </div>
                                        {/* Action toolbar — shown when expanded */}
                                        {!isCollapsed && (
                                          <div className="flex items-center gap-1 shrink-0 ml-3" onClick={e => e.stopPropagation()}>
                                            {/* Raw / Parsed toggle */}
                                            <div className="flex items-center gap-0.5 p-0.5 rounded-md bg-white/5 border border-white/10 mr-1">
                                              <button
                                                onClick={() => setInspParseViewMode(prev => ({ ...prev, [blockKey]: 'raw' }))}
                                                className={`flex items-center gap-1 px-2 py-0.5 rounded text-[9px] font-bold transition-all ${(!inspParseViewMode[blockKey] || inspParseViewMode[blockKey] === 'raw') ? 'bg-white/10 text-white' : 'text-white/30 hover:text-white/60'}`}
                                              >
                                                Raw
                                              </button>
                                              <button
                                                onClick={() => {
                                                  if (!parseState || (!parseState.data && !parseState.loading)) {
                                                    void handleParseInspCmd(blockKey, res.platform || 'cisco_ios', cmd, outputStr);
                                                  } else {
                                                    setInspParseViewMode(prev => ({ ...prev, [blockKey]: 'parsed' }));
                                                  }
                                                }}
                                                className={`flex items-center gap-1 px-2 py-0.5 rounded text-[9px] font-bold transition-all ${(inspParseViewMode[blockKey] === 'parsed') ? 'bg-white/10 text-cyan-400' : 'text-white/30 hover:text-white/60'}`}
                                              >
                                                {parseState?.loading ? <Loader2 size={9} className="animate-spin" /> : 'Parsed'}
                                              </button>
                                            </div>
                                            {/* Copy */}
                                            <button
                                              onClick={() => copyInspText(outputStr, blockKey)}
                                              className={`flex items-center gap-1 p-1 rounded border transition-all text-[9px] font-mono ${isCopied ? 'bg-emerald-900/40 border-emerald-500/40 text-emerald-400' : 'bg-white/5 border-white/10 text-white/30 hover:text-white/60 hover:border-white/20'}`}
                                              title={zh ? '复制' : 'Copy'}
                                            >
                                              {isCopied ? <Check size={11} /> : <Copy size={11} />}
                                            </button>
                                            {/* Download TXT */}
                                            <button
                                              onClick={() => {
                                                const safeCmd = cmd.replace(/[^a-z0-9_]/gi, '_').slice(0, 40);
                                                const blob = new Blob([outputStr], { type: 'text/plain' });
                                                const url = URL.createObjectURL(blob);
                                                const a = document.createElement('a');
                                                a.href = url; a.download = `${res.hostname}_${safeCmd}.txt`; a.click();
                                                URL.revokeObjectURL(url);
                                              }}
                                              className="flex items-center gap-1 p-1 rounded border bg-white/5 border-white/10 text-white/30 hover:text-cyan-400 hover:border-cyan-500/40 transition-all"
                                              title={zh ? '下载原始文本 (.txt)' : 'Download raw .txt'}
                                            >
                                              <Download size={11} />
                                              <span className="text-[9px] font-mono">txt</span>
                                            </button>
                                            {/* Parse / Parsed toggle */}
                                            <button
                                              onClick={() => {
                                                if (!parseState || (!parseState.data && !parseState.loading)) {
                                                  void handleParseInspCmd(blockKey, res.platform || 'cisco_ios', cmd, outputStr);
                                                }
                                              }}
                                              disabled={parseState?.loading}
                                              className={`flex items-center gap-1 px-2 py-1 rounded border text-[9px] font-mono transition-all ${
                                                parseState?.data
                                                  ? 'bg-cyan-900/40 border-cyan-500/40 text-cyan-300'
                                                  : parseState?.error
                                                  ? 'bg-amber-900/20 border-amber-500/30 text-amber-400/60'
                                                  : 'bg-white/5 border-white/10 text-white/30 hover:text-cyan-400 hover:border-cyan-500/40'
                                              }`}
                                              title={parseState?.error || (zh ? '用 TextFSM 解析' : 'Parse with TextFSM')}
                                            >
                                              {parseState?.loading
                                                ? <Loader2 size={11} className="animate-spin" />
                                                : <Table2 size={11} />}
                                              <span>{parseState?.data ? (zh ? '已解析' : 'Parsed') : (zh ? '解析' : 'Parse')}</span>
                                            </button>
                                            {/* Download Excel — only when parsed */}
                                            {parseState?.data?.count > 0 && (
                                              <button
                                                onClick={() => {
                                                  const safeCmd = cmd.replace(/[^a-z0-9_]/gi, '_').slice(0, 40);
                                                  downloadInspExcel(parseState.data.records, parseState.data.fields, `${res.hostname}_${safeCmd}_parsed`);
                                                }}
                                                className="flex items-center gap-1 p-1 rounded border bg-emerald-900/30 border-emerald-500/40 text-emerald-400 hover:bg-emerald-900/50 transition-all"
                                                title={zh ? '下载解析结果 (Excel)' : 'Download parsed as Excel'}
                                              >
                                                <FileSpreadsheet size={11} />
                                                <span className="text-[9px] font-mono">xlsx</span>
                                              </button>
                                            )}
                                            {/* Download JSON — only when parsed */}
                                            {parseState?.data?.count > 0 && (
                                              <button
                                                onClick={() => {
                                                  const safeCmd = cmd.replace(/[^a-z0-9_]/gi, '_').slice(0, 40);
                                                  downloadInspJSON(parseState.data.records, `${res.hostname}_${safeCmd}_parsed`);
                                                }}
                                                className="flex items-center gap-1 p-1 rounded border bg-indigo-900/30 border-indigo-500/40 text-indigo-400 hover:bg-indigo-900/50 transition-all"
                                                title={zh ? '下载解析结果 (JSON)' : 'Download parsed as JSON'}
                                              >
                                                <FileJson size={11} />
                                                <span className="text-[9px] font-mono">json</span>
                                              </button>
                                            )}
                                          </div>
                                        )}
                                        {isCollapsed && (
                                          <span className="text-[10px] text-white/20 font-mono italic truncate max-w-[300px]">
                                            {outputStr.substring(0, 60).replace(/\n/g, ' ')}...
                                          </span>
                                        )}
                                      </div>
                                      {!isCollapsed && (
                                        <div className={`p-4 font-mono text-[11px] ${inspParseViewMode[blockKey] === 'parsed' ? '' : 'whitespace-pre-wrap'} leading-relaxed ${isError ? 'text-red-300/80' : 'text-white/60'}`}>
                                          {inspParseViewMode[blockKey] === 'parsed' ? (
                                            <>
                                              {parseState?.loading ? (
                                                <div className="flex items-center gap-2 py-4 text-cyan-400/50">
                                                  <Loader2 size={16} className="animate-spin" />
                                                  <span>{zh ? '正在解析中...' : 'Parsing...'}</span>
                                                </div>
                                              ) : parseState?.error ? (
                                                <div className="py-4 text-amber-500/80 italic">
                                                  ⚠ {parseState.error}
                                                </div>
                                              ) : parseState?.data?.records ? (
                                                <div className="overflow-x-auto custom-scrollbar-dark pb-2">
                                                  <table className="w-full text-left border-collapse border border-white/10">
                                                    <thead>
                                                      <tr className="bg-white/5 border-b border-white/10">
                                                        {parseState.data.fields.map((f: string) => (
                                                          <th key={f} className="px-3 py-2 text-[10px] font-bold text-cyan-400/80 uppercase tracking-wider border-r border-white/10 last:border-r-0">{f}</th>
                                                        ))}
                                                      </tr>
                                                    </thead>
                                                    <tbody className="divide-y divide-white/5">
                                                      {parseState.data.records.map((rec: any, idx: number) => (
                                                        <tr key={idx} className="hover:bg-white/[0.03]">
                                                          {parseState.data.fields.map((f: string) => (
                                                            <td key={f} className="px-3 py-2 text-[10px] text-white/60 whitespace-nowrap border-r border-white/5 last:border-r-0">{String(rec[f] ?? '—')}</td>
                                                          ))}
                                                        </tr>
                                                      ))}
                                                    </tbody>
                                                  </table>
                                                </div>
                                              ) : (
                                                <div className="py-4 text-white/20 italic">{zh ? '未解析或解析无结果' : 'Not parsed or no results'}</div>
                                              )}
                                            </>
                                          ) : (
                                            outputStr
                                          )}
                                        </div>
                                      )}
                                    </div>
                                  );
                                })
                              ) : (
                                <div className="text-white/20 text-center py-10 italic text-[11px]">
                                  {res.ssh_ok ? (zh ? '无命令回显' : 'No output returned') : (zh ? '连接未建立' : 'Connection failed')}
                                </div>
                              )}
                            </div>
                          </div>
                          </>
                          )}
                        </div>
                      </>
                    );
                  })() : (
                    <div className="flex-1 flex flex-col items-center justify-center text-white/20 gap-3">
                      <Search size={48} strokeWidth={1} className="opacity-10" />
                      <span className="text-sm">{zh ? '请选择左侧设备查看详情' : 'Select a device to see details'}</span>
                    </div>
                  )}
                </div>
              </div>
            ) : (
              /* Playbook Details View */
              <div className="flex flex-col md:flex-row h-full">
                {/* Device List (Left) */}
                <div className="w-full md:w-4/12 border-r border-black/5 flex flex-col h-full bg-slate-50/50">
                  <div className="p-4 border-b border-black/5 bg-white">
                    <span className="text-xs font-bold text-black/50">{zh ? '执行设备情况' : 'Device Execution'}</span>
                  </div>
                  <div className="flex-1 overflow-auto p-2 space-y-1">
                    {pbDevices.map((dev) => {
                      const stMap: Record<string, { cls: string; label: string }> = {
                        success: { cls: 'bg-emerald-500', label: zh ? '成功' : 'Pass' },
                        completed: { cls: 'bg-emerald-500', label: zh ? '成功' : 'Pass' },
                        failed: { cls: 'bg-red-500', label: zh ? '失败' : 'Fail' },
                        error: { cls: 'bg-red-500', label: zh ? '失败' : 'Fail' },
                        partial: { cls: 'bg-amber-500', label: zh ? '部分成功' : 'Partial' },
                        partial_failure: { cls: 'bg-amber-500', label: zh ? '部分成功' : 'Partial' },
                        running: { cls: 'bg-cyan-500 animate-pulse', label: zh ? '运行中' : 'Live' },
                      };
                      const dst = stMap[dev.status || ''] || { cls: 'bg-slate-400', label: dev.status || (zh ? '未知' : 'Unknown') };
                      const isSelected = selectedPbDevice === dev.device_id;

                      return (
                        <div
                          key={dev.device_id}
                          onClick={() => handleSelectPbDevice(dev.device_id)}
                          className={`flex items-center justify-between p-3 rounded-xl border cursor-pointer transition-all ${
                            isSelected 
                              ? 'bg-[#164e63] text-white border-transparent shadow-md' 
                              : 'bg-white border-black/5 hover:border-black/10 hover:shadow-sm'
                          }`}
                        >
                          <div className="min-w-0">
                            <p className={`text-xs font-bold truncate ${isSelected ? 'text-white' : 'text-[#164e63]'}`}>{dev.hostname}</p>
                            <p className={`text-[10px] font-mono mt-0.5 ${isSelected ? 'text-white/60' : 'text-black/30'}`}>{dev.ip_address}</p>
                          </div>
                          <span className={`text-[9px] font-bold text-white px-2 py-0.5 rounded-md ${dst.cls}`}>{dst.label}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Command Output (Right) */}
                <div className="flex-1 flex flex-col bg-[#1E1E1E] overflow-hidden">
                  <div className="p-4 border-b border-white/10 bg-black/20 flex items-center justify-between">
                    <div>
                      <span className="text-xs text-white/80 font-bold block">
                        {selectedPbDevice 
                          ? (pbDevices.find((d: any) => d.device_id === selectedPbDevice)?.hostname || '') 
                          : (zh ? '请选择设备查看命令输出' : 'Select a device to view command outputs')}
                      </span>
                      {selectedPbDevice && (() => {
                        const dev = devices.find(d => d.id === selectedPbDevice);
                        if (!dev) return null;
                        return (
                          <div className="flex items-center gap-3 mt-1.5">
                            <span className="text-[10px] text-white/40 font-mono bg-white/5 px-1.5 py-0.5 rounded uppercase tracking-tighter">PLAT: {dev.platform || '-'}</span>
                            <span className="text-[10px] text-white/40 font-mono bg-white/5 px-1.5 py-0.5 rounded uppercase tracking-tighter">ROLE: {dev.role || '-'}</span>
                            <span className="text-[10px] text-white/40 font-mono bg-white/5 px-1.5 py-0.5 rounded uppercase tracking-tighter">SITE: {dev.site || '-'}</span>
                            <span className="text-[10px] text-white/40 font-mono bg-white/5 px-1.5 py-0.5 rounded uppercase tracking-tighter">MOD: {dev.model || '-'}</span>
                          </div>
                        );
                      })()}
                    </div>
                    {selectedPbDevice && pbDeviceDetail?.phases && (
                      <div className="flex items-center gap-3">
                        <button 
                          onClick={() => {
                            const next = { ...collapsedCmds };
                            Object.entries(pbDeviceDetail.phases).forEach(([ph, pdata]: any) => {
                              const cmds = (pdata || {}).commands || [];
                              const outStr = typeof (pdata || {}).output === 'string' ? pdata.output : JSON.stringify((pdata || {}).output || '');
                              const blocks = splitOutputByCommand(outStr, cmds);
                              blocks.forEach((_, bi) => next[`pb_${selectedPbDevice}_${ph}_${bi}`] = false);
                            });
                            setCollapsedCmds(next);
                          }}
                          className="text-[10px] font-bold text-cyan-400/60 hover:text-cyan-400 transition-colors cursor-pointer"
                        >
                          {zh ? '全部展开' : 'Expand All'}
                        </button>
                        <div className="w-px h-2.5 bg-white/10" />
                        <button 
                          onClick={() => {
                            const next = { ...collapsedCmds };
                            Object.entries(pbDeviceDetail.phases).forEach(([ph, pdata]: any) => {
                              const cmds = (pdata || {}).commands || [];
                              const outStr = typeof (pdata || {}).output === 'string' ? pdata.output : JSON.stringify((pdata || {}).output || '');
                              const blocks = splitOutputByCommand(outStr, cmds);
                              blocks.forEach((_, bi) => next[`pb_${selectedPbDevice}_${ph}_${bi}`] = true);
                            });
                            setCollapsedCmds(next);
                          }}
                          className="text-[10px] font-bold text-white/30 hover:text-white/60 transition-colors cursor-pointer"
                        >
                          {zh ? '全部折叠' : 'Collapse All'}
                        </button>
                      </div>
                    )}
                  </div>
                  <div className="flex-1 p-6 font-mono text-xs text-[#d4d4d4] overflow-auto whitespace-pre-wrap select-text relative">
                    {pbDeviceDetail?.phases ? (
                      Object.entries(pbDeviceDetail.phases).map(([phase, pdata]: any) => {
                        const pd = pdata || {};
                        const cmds = pd.commands || [];
                        const outputStr = typeof pd.output === 'string' ? pd.output : JSON.stringify(pd.output || '');
                        const blocks = splitOutputByCommand(outputStr, cmds);
                        const dev = devices.find(d => d.id === selectedPbDevice);

                        return (
                          <div key={phase} className="mb-6 group/phase">
                            <div className="flex items-center gap-2 mb-3">
                              <div className="h-px flex-1 bg-white/5" />
                              <span className="text-[#a170e8] text-[10px] font-black uppercase tracking-[0.2em]"># PHASE: {phase.toUpperCase()}</span>
                              <div className="h-px flex-1 bg-white/5" />
                            </div>
                            
                            <div className="space-y-3">
                              {blocks.map((blk, bi) => {
                                const bOutput = blk.output || '';
                                const bIsError = bOutput.includes('__ERROR__') || bOutput.includes('% Invalid input') || bOutput.includes('error');
                                const bKey = `pb_${selectedPbDevice}_${phase}_${bi}`;
                                const isCollapsed = collapsedCmds[bKey] ?? false;
                                
                                return (
                                  <div key={bi} className={`rounded-lg overflow-hidden border transition-all ${
                                    bIsError ? 'border-red-500/30 bg-red-500/5' : 'border-white/5 bg-black/20'
                                  }`}>
                                    <div 
                                      onClick={() => toggleCmdCollapse(bKey)}
                                      className="px-4 py-2 bg-white/5 flex items-center justify-between cursor-pointer hover:bg-white/[0.08] select-none"
                                    >
                                      <div className="flex items-center gap-2 min-w-0">
                                        <ChevronRight size={14} className={`text-white/20 shrink-0 transition-transform duration-200 ${isCollapsed ? '' : 'rotate-90'}`} />
                                        <span className={`text-[11px] font-mono font-bold truncate ${bIsError ? 'text-red-400' : 'text-cyan-400/80'}`}>&gt; {blk.command || 'system'}</span>
                                      </div>
                                      <div className="flex items-center gap-2 shrink-0 ml-3" onClick={e => e.stopPropagation()}>
                                        {isCollapsed && (
                                          <span className="text-[10px] text-white/30 font-mono italic truncate max-w-[250px] hidden sm:inline">
                                            {bOutput.substring(0, 60).replace(/\n/g, ' ')}...
                                          </span>
                                        )}
                                        <OutputActions
                                          text={blk.output}
                                          filename={`${dev?.hostname || 'device'}_${phase}_cmd${bi}`}
                                          theme="dark"
                                          zh={zh}
                                          iconOnly={true}
                                        />
                                      </div>
                                    </div>
                                    {!isCollapsed && (
                                      <div className={`p-4 font-mono text-[11px] whitespace-pre-wrap leading-relaxed ${bIsError ? 'text-red-300/80' : 'text-[#d4d4d4]'}`}>
                                        {blk.output || (pd.status === 'success' ? (zh ? '命令执行成功，但无回显' : 'Success, no output') : '—')}
                                      </div>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        );
                      })
                    ) : (
                      <div className="text-white/20 text-center py-24 select-none">{zh ? '无命令输出' : 'No command output'}</div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        </motion.div>
      </div>
    )}
  </AnimatePresence>

  <AnimatePresence>
        {showScheduleDetail && selectedSchedule && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 sm:p-6 lg:p-8">
            <motion.div
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              onClick={() => setShowScheduleDetail(false)}
              className="absolute inset-0 bg-[#00172D]/60 backdrop-blur-md"
            />
            <motion.div
              initial={{ opacity: 0, scale: 0.9, y: 30 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.9, y: 30 }}
              className="relative w-full max-w-3xl bg-white rounded-[2.5rem] shadow-2xl shadow-black/40 overflow-hidden flex flex-col max-h-[90vh]"
            >
              {/* Modal Header */}
              <div className="px-8 py-6 border-b border-black/5 flex items-center justify-between bg-[linear-gradient(to_bottom,#fcfdfd_0%,#ffffff_100%)]">
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 rounded-2xl bg-cyan-50 flex items-center justify-center text-cyan-600 shadow-sm border border-cyan-100">
                    <CalendarClock size={24} />
                  </div>
                  <div>
                    <h3 className="text-xl font-bold text-[#164e63]">{selectedSchedule.name}</h3>
                    <p className="text-xs text-black/30 font-medium tracking-tight mt-0.5">ID: {selectedSchedule.id}</p>
                  </div>
                </div>
                <button
                  onClick={() => setShowScheduleDetail(false)}
                  className="p-3 rounded-2xl text-black/20 hover:bg-black/5 hover:text-black/40 transition-all active:scale-90"
                >
                  <X size={20} />
                </button>
              </div>

              {/* Modal Content */}
              <div className="flex-1 overflow-y-auto px-8 py-8 custom-scrollbar">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-10">
                  {/* Info Blocks */}
                  <div className="space-y-8">
                    <section>
                      <label className="text-[10px] font-black text-black/20 uppercase tracking-[0.2em] block mb-3">{zh ? '基本信息' : 'Basic Info'}</label>
                      <div className="space-y-5">
                        <div>
                          <p className="text-[11px] font-bold text-black/30 mb-1">{zh ? '描述' : 'Description'}</p>
                          <p className="text-sm text-[#164e63] font-medium leading-relaxed">
                            {selectedSchedule.description || (zh ? '未填写描述' : 'No description provided')}
                          </p>
                        </div>
                        <div className="grid grid-cols-2 gap-4">
                          <div>
                            <p className="text-[11px] font-bold text-black/30 mb-1">{zh ? '创建者' : 'Author'}</p>
                            <p className="text-sm text-[#164e63] font-black">{selectedSchedule.created_by || '—'}</p>
                          </div>
                          <div>
                            <p className="text-[11px] font-bold text-black/30 mb-1">{zh ? '创建时间' : 'Created At'}</p>
                            <p className="text-sm text-[#164e63] font-black font-mono">{new Date(selectedSchedule.created_at).toLocaleDateString()}</p>
                          </div>
                        </div>
                      </div>
                    </section>

                    <section>
                      <label className="text-[10px] font-black text-black/20 uppercase tracking-[0.2em] block mb-3">{zh ? '执行配置' : 'Execution Config'}</label>
                      <div className="rounded-3xl bg-slate-50 border border-black/5 p-6 space-y-5 shadow-inner">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-bold text-black/40">{zh ? '范围类型' : 'Scope Type'}</span>
                          <span className="text-xs font-black text-[#164e63] uppercase tracking-wide bg-white px-3 py-1 rounded-full shadow-sm">{selectedSchedule.device_scope}</span>
                        </div>
                        {selectedSchedule.device_filter && (
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-bold text-black/40">{zh ? '过滤条件' : 'Filter'}</span>
                            <span className="text-xs font-black text-[#164e63] max-w-[150px] truncate">{selectedSchedule.device_filter}</span>
                          </div>
                        )}
                        <div className="pt-2 border-t border-black/5">
                          <span className="text-[11px] font-bold text-black/30 block mb-2">{zh ? '执行时间' : 'Execution Time'}</span>
                          <div className="flex items-center gap-3">
                            <div className="flex-1 text-[11px] font-mono text-cyan-600 bg-cyan-50 px-3 py-2 rounded-xl border border-cyan-100 text-center">
                              {fmtDateTime(selectedSchedule.scheduled_at, zh)}
                            </div>
                          </div>
                        </div>
                      </div>
                    </section>
                  </div>

                  {/* Metrics Block */}
                  <div className="space-y-8">
                    <section>
                      <label className="text-[10px] font-black text-black/20 uppercase tracking-[0.2em] block mb-3">{zh ? '关联指标项' : 'Linked Metrics'}</label>
                      <div className="flex flex-wrap gap-2">
                        {Array.isArray(selectedSchedule.check_items) && selectedSchedule.check_items.length > 0 ? (
                          selectedSchedule.check_items.map(item => (
                            <div key={item} className="flex items-center gap-2 px-4 py-2.5 rounded-2xl bg-cyan-500/[0.06] border border-cyan-500/10 transition-all hover:bg-cyan-500/10 cursor-default">
                              <CheckCircle2 size={12} className="text-cyan-500" />
                              <span className="text-xs font-bold text-cyan-800">{item}</span>
                            </div>
                          ))
                        ) : (
                          <span className="text-xs text-black/20 italic">{zh ? '未关联任何指标' : 'No metrics linked'}</span>
                        )}
                      </div>
                    </section>

                    <section>
                      <label className="text-[10px] font-black text-black/20 uppercase tracking-[0.2em] block mb-3">{zh ? '状态与记录' : 'Status & Stats'}</label>
                      <div className="grid grid-cols-1 gap-4">
                        <div className="flex items-center justify-between p-5 rounded-[2rem] bg-gradient-to-br from-white to-slate-50 border border-black/5 shadow-sm group">
                          <div className="flex items-center gap-3">
                            <div className={`w-10 h-10 rounded-2xl flex items-center justify-center transition-all group-hover:scale-110 ${selectedSchedule.enabled ? 'bg-emerald-50 text-emerald-600' : 'bg-slate-50 text-slate-400'}`}>
                              <Activity size={20} />
                            </div>
                            <div>
                              <p className="text-[11px] font-bold text-black/30 uppercase tracking-widest">{zh ? '当前状态' : 'Current Status'}</p>
                              <p className={`text-sm font-black ${selectedSchedule.enabled ? 'text-emerald-600' : 'text-slate-400'}`}>
                                {selectedSchedule.enabled ? (zh ? '运行中' : 'Active') : (zh ? '已停用' : 'Disabled')}
                              </p>
                            </div>
                          </div>
                          <button
                            onClick={() => { toggleInspScheduleEnabled(selectedSchedule); setSelectedSchedule({ ...selectedSchedule, enabled: selectedSchedule.enabled ? 0 : 1 } as ScheduledJob); }}
                            className={`px-4 py-1.5 rounded-full text-[10px] font-black uppercase transition-all shadow-sm ${selectedSchedule.enabled ? 'bg-white text-emerald-600 hover:bg-emerald-50 border border-emerald-100' : 'bg-emerald-600 text-white hover:bg-emerald-700'}`}
                          >
                            {selectedSchedule.enabled ? (zh ? '停用' : 'Disable') : (zh ? '启动' : 'Enable')}
                          </button>
                        </div>

                        <div className="p-5 rounded-[2rem] bg-slate-50 border border-black/5 shadow-inner">
                          <div className="flex items-center gap-3 mb-2">
                            <RotateCcw size={14} className="text-black/20" />
                            <span className="text-[11px] font-bold text-black/30 uppercase tracking-widest">{zh ? '最近一次执行' : 'Last Execution'}</span>
                          </div>
                          <p className="text-sm font-black text-[#164e63] font-mono">
                            {selectedSchedule.last_run_at ? fmtDateTime(selectedSchedule.last_run_at, zh) : (zh ? '暂无执行记录' : 'Never executed')}
                          </p>
                        </div>
                      </div>
                    </section>
                  </div>
                </div>
              </div>

              {/* Modal Footer */}
              <div className="px-8 py-6 border-t border-black/5 bg-slate-50/30 flex items-center justify-between">
                <button
                  onClick={() => {
                    if (confirm(zh ? '确定删除该执行计划？' : 'Are you sure you want to delete this schedule?')) {
                      deleteInspSchedule(selectedSchedule.id);
                      setShowScheduleDetail(false);
                    }
                  }}
                  className="flex items-center gap-2 px-6 py-2.5 rounded-2xl text-red-500 hover:bg-red-50 text-xs font-black transition-all"
                >
                  <Trash2 size={16} />
                  {zh ? '删除计划' : 'Delete Plan'}
                </button>
                <button
                  onClick={() => setShowScheduleDetail(false)}
                  className="px-8 py-2.5 rounded-2xl bg-[#164e63] text-white text-xs font-black hover:bg-[#155e75] transition-all shadow-lg shadow-cyan-900/20 active:scale-95"
                >
                  {zh ? '完成并关闭' : 'Done & Close'}
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
      </div>
      {/* --- Candidate IP / Device Selection Modal --- */}
      <AnimatePresence>
        {candidateModalOpen && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-[70] flex items-center justify-center p-4"
          >
            <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setCandidateModalOpen(false)} />
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 15 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 15 }}
              className="relative w-full max-w-xl bg-white rounded-2xl shadow-2xl overflow-hidden border border-slate-100 flex flex-col z-10 max-h-[80vh]"
              onClick={e => e.stopPropagation()}
            >
              <div className="px-6 py-4 bg-gradient-to-r from-slate-900 to-[#0f172a] text-white flex items-center justify-between border-b border-white/10">
                <div className="flex items-center gap-2.5">
                  <div className="w-8 h-8 rounded-xl bg-cyan-500/20 flex items-center justify-center border border-cyan-400/20 text-cyan-400">
                    <Target size={16} />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold">{zh ? '选择匹配的目标设备' : 'Select Matched Target Devices'}</h3>
                    <p className="text-[10px] text-slate-400">{zh ? `共检索到 ${candidateList.length} 台候选目标` : `Found ${candidateList.length} candidate device(s)`}</p>
                  </div>
                </div>
                <button type="button" onClick={() => setCandidateModalOpen(false)} className="text-slate-400 hover:text-white transition-colors p-1">
                  <X size={16} />
                </button>
              </div>

              <div className="px-6 py-3 bg-slate-50 border-b border-slate-200/80 flex items-center justify-between text-xs text-slate-600">
                <label className="flex items-center gap-2 font-bold cursor-pointer hover:text-slate-900 select-none">
                  <input
                    type="checkbox"
                    checked={candidateList.length > 0 && candidateList.every(c => c.selected)}
                    onChange={toggleAllCandidates}
                    className="w-4 h-4 rounded border-slate-300 text-cyan-600 focus:ring-cyan-500"
                  />
                  <span>{zh ? '全选 / 全不选' : 'Select All'}</span>
                </label>
                <span className="font-mono text-[11px] bg-white px-2 py-0.5 rounded border border-slate-200 font-bold text-slate-700 shadow-2xs">
                  {zh ? `已勾选 ${candidateList.filter(c => c.selected).length} / ${candidateList.length} 台` : `${candidateList.filter(c => c.selected).length} / ${candidateList.length} selected`}
                </span>
              </div>

              <div className="flex-1 overflow-y-auto p-6 space-y-2 custom-scrollbar max-h-[50vh]">
                {candidateList.map((cand, idx) => (
                  <div
                    key={cand.ip}
                    onClick={() => toggleCandidateSelected(idx)}
                    className={`flex items-center gap-3 px-4 py-3 rounded-xl border transition-all cursor-pointer ${
                      cand.selected
                        ? 'border-cyan-400 bg-cyan-50/60 shadow-2xs text-slate-900 font-bold'
                        : 'border-slate-200/80 bg-white text-slate-500 hover:border-slate-300 opacity-70'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={cand.selected}
                      onChange={() => {}} // parent div onClick handles toggle
                      className="w-4 h-4 rounded border-slate-300 text-cyan-600 focus:ring-cyan-500 pointer-events-none shrink-0"
                    />
                    <span className="font-mono text-xs text-[#0f172a] shrink-0 w-32">{cand.ip}</span>
                    {cand.hostname ? (
                      <span className="text-xs text-slate-600 truncate flex-1">{cand.hostname}</span>
                    ) : (
                      <span className="text-xs text-amber-600/80 italic flex-1 font-normal">{zh ? '手动输入目标 (非资产表)' : 'Manual Target'}</span>
                    )}
                    {cand.tags.length > 0 && (
                      <div className="flex items-center gap-1 shrink-0 max-w-[150px] overflow-hidden">
                        {cand.tags.slice(0, 2).map(t => (
                          <span key={t.id} className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-medium bg-white border border-black/5">
                            <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: t.color || '#94a3b8' }} />
                            <span className="truncate">{zh ? (t.label_zh || t.label) : t.label}</span>
                          </span>
                        ))}
                        {cand.tags.length > 2 && <span className="text-[9px] text-slate-400">+{cand.tags.length - 2}</span>}
                      </div>
                    )}
                  </div>
                ))}
              </div>

              <div className="px-6 py-4 bg-slate-50/80 border-t border-slate-100 flex items-center justify-end gap-2.5">
                <button
                  type="button"
                  onClick={() => setCandidateModalOpen(false)}
                  className="px-4 py-2 rounded-xl border border-slate-200 font-semibold text-xs text-slate-600 hover:bg-slate-100 transition-all"
                >
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button
                  type="button"
                  onClick={confirmAddCandidates}
                  disabled={candidateList.filter(c => c.selected).length === 0}
                  className="px-5 py-2 rounded-xl bg-[#164e63] text-white font-bold text-xs hover:bg-[#0891b2] transition-all disabled:opacity-40 disabled:cursor-not-allowed shadow-md shadow-cyan-950/10"
                >
                  {zh ? `确认添加 (${candidateList.filter(c => c.selected).length}台)` : `Add Selected (${candidateList.filter(c => c.selected).length})`}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default ExecutionScheduleTab;
