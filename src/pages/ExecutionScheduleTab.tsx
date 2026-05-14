import React, { useEffect, useState, useCallback, useMemo } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  CalendarClock, Clock, Plus, X, Trash2, Activity, RotateCcw,
  Play, Shield, CheckCircle2, CalendarRange, AlertTriangle,
  Eye, Download, Search, FileText, ChevronRight,
  FileSpreadsheet, FileJson, Loader2, Table2, Copy, Check
} from 'lucide-react';
import * as XLSX from 'xlsx';
import Pagination from '../components/Pagination';
import OutputActions from '../components/OutputActions';
import DateTimePicker from '../components/DateTimePicker';
import PageHero from '../components/PageHero';
import type { Device } from '../types';

/* ═══════════════════════════════════════════════════════ */
/*  Types                                                  */
/* ═══════════════════════════════════════════════════════ */

interface InspectionSchedule {
  id: string; name: string; cron_expr: string; scope_type: string; scope_filter: string;
  enabled: number; last_run_at?: string; created_by: string; created_at: string;
  scheduled_at?: string; expires_at?: string; description?: string; check_items?: string[];
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

const getScheduleStatus = (sch: InspectionSchedule, zh: boolean) => {
  if (!sch.enabled) return { label: zh ? '已停用' : 'Disabled', cls: 'bg-slate-100 text-slate-500', icon: 'disabled' as const };
  if (sch.last_run_at) return { label: zh ? '已执行' : 'Executed', cls: 'bg-emerald-50 text-emerald-600', icon: 'done' as const };
  const now = new Date();
  if (sch.expires_at && new Date(sch.expires_at) < now) return { label: zh ? '已过期' : 'Expired', cls: 'bg-slate-50 text-slate-400', icon: 'expired' as const };
  if (sch.scheduled_at && new Date(sch.scheduled_at) > now) return { label: zh ? '等待中' : 'Pending', cls: 'bg-cyan-50 text-cyan-600', icon: 'pending' as const };
  return { label: zh ? '就绪' : 'Ready', cls: 'bg-amber-50 text-amber-600', icon: 'ready' as const };
};

/* ═══════════════════════════════════════════════════════ */
/*  Component                                              */
/* ═══════════════════════════════════════════════════════ */

const ExecutionScheduleTab: React.FC<ExecutionScheduleTabProps> = ({ language, showToast, initialTab, devices, onRerun }) => {
  const zh = language === 'zh';

  /* ═══ STATE ═══ */
  const [inspSchedules, setInspSchedules] = useState<InspectionSchedule[]>([]);
  const [inspSchedulesLoading, setInspSchedulesLoading] = useState(false);
  const [inspSchedulePage, setInspSchedulePage] = useState(1);
  const [inspSchedulePageSize, setInspSchedulePageSize] = useState(10);
  const [inspScheduleTotal, setInspScheduleTotal] = useState(0);
  const [showAddInspSchedule, setShowAddInspSchedule] = useState(false);
  const [inspForm, setInspForm] = useState({
    name: '', scheduled_at: '', expires_at: '', scope_type: 'all', scope_filter: '', description: '',
    check_items: [] as string[]
  });

  const [inspectionItems, setInspectionItems] = useState<any[]>([]);
  const [inspectionItemsLoading, setInspectionItemsLoading] = useState(false);

  const [selectedSchedule, setSelectedSchedule] = useState<InspectionSchedule | null>(null);
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
        if (inspForm.check_items.length === 0 && j.items?.length > 0) {
          setInspForm(f => ({ ...f, check_items: j.items.map((i: any) => i.name) }));
        }
      }
    } catch { /* ignore */ }
    finally { setInspectionItemsLoading(false); }
  }, [authHeaders, inspForm.check_items.length]);

  const fetchInspSchedules = useCallback(async () => {
    setInspSchedulesLoading(true);
    try {
      const offset = (inspSchedulePage - 1) * inspSchedulePageSize;
      const r = await fetch(`/api/inspections/schedules?limit=${inspSchedulePageSize}&offset=${offset}`, { headers: authHeaders });
      if (r.ok) {
        const j = await r.json();
        const d = j.data;
        if (d && typeof d === 'object' && !Array.isArray(d)) {
          setInspSchedules(d.items || []);
          setInspScheduleTotal(d.total || 0);
        } else {
          setInspSchedules(j.data || []);
          setInspScheduleTotal(j.data?.length || 0);
        }
      }
    } finally { setInspSchedulesLoading(false); }
  }, [authHeaders, inspSchedulePage, inspSchedulePageSize]);

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
          config_reason: `${zh ? '创建执行计划' : 'Create execution schedule'}: ${inspForm.name}`,
          device_hostname: inspForm.scope_type === 'all' ? (zh ? '全部设备' : 'All devices') : inspForm.scope_filter,
          command_preview: '',
          approval_type: 'execution_plan',
          extra_fields: {
            action_type: zh ? '设备巡检' : 'Device Inspection',
            schedule_desc: `${fmtDateTime(inspForm.scheduled_at, zh)}${inspForm.expires_at ? ` → ${fmtDateTime(inspForm.expires_at, zh)}` : ''}`,
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
    if (!inspForm.name.trim() || !inspForm.scheduled_at || !inspForm.expires_at) {
      showToast(zh ? '请填写计划名称、开始时间和结束时间' : 'Name, start and end times are required', 'error');
      return;
    }
    if (inspForm.expires_at <= inspForm.scheduled_at) {
      showToast(zh ? '结束时间必须晚于开始时间' : 'End time must be after start time', 'error');
      return;
    }
    if (approvalStatus !== 'verified') {
      showToast(zh ? '请先完成审批验证' : 'Please complete approval verification first', 'error');
      return;
    }
    try {
      const r = await fetch('/api/inspections/schedules', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({
          name: inspForm.name,
          scheduled_at: inspForm.scheduled_at,
          expires_at: inspForm.expires_at,
          cron_expr: '',
          scope_type: inspForm.scope_type,
          scope_filter: inspForm.scope_filter,
          description: inspForm.description,
          check_items: inspForm.check_items,
          approval_token: approvalToken,
          approval_code: approvalCode,
        }),
      });
      if (r.ok) {
        setShowAddInspSchedule(false);
        setInspForm({
          name: '', scheduled_at: '', expires_at: '', scope_type: 'all', scope_filter: '', description: '',
          check_items: inspectionItems.map(i => i.name)
        });
        resetApproval();
        setInspSchedulePage(1); // Back to first page to see the new one
        fetchInspSchedules();
        showToast(zh ? '执行计划已创建' : 'Execution schedule created', 'success');
      } else {
        const j = await r.json();
        showToast(j.detail || j.message || 'Failed', 'error');
      }
    } catch { /* ignore */ }
  };

  const deleteInspSchedule = async (id: string) => {
    try {
      await fetch(`/api/inspections/schedules/${id}`, { method: 'DELETE', headers: authHeaders });
      fetchInspSchedules();
      showToast(zh ? '计划已删除' : 'Schedule deleted', 'success');
    } catch { /* ignore */ }
  };

  const toggleInspScheduleEnabled = async (sch: InspectionSchedule) => {
    try {
      await fetch(`/api/inspections/schedules/${sch.id}`, {
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
                  {/* Left Column: Basic Info */}
                  <div className="space-y-5">
                    <div className="space-y-4">
                      <div>
                        <label className="text-xs font-bold text-[#164e63] uppercase tracking-wider block mb-2">
                          {zh ? '1. 计划基本信息' : '1. Basic Information'}
                        </label>
                        <div className="space-y-4 rounded-xl bg-slate-50/50 p-4 border border-black/5">
                          <div>
                            <label className="text-[11px] font-semibold text-black/40 block mb-1.5 uppercase tracking-wide">
                              {zh ? '计划名称' : 'Plan Name'} <span className="text-red-500 ml-0.5">*</span>
                            </label>
                            <input
                              type="text" value={inspForm.name}
                              onChange={e => setInspForm(f => ({ ...f, name: e.target.value }))}
                              className="w-full px-4 py-2.5 rounded-xl border border-black/[0.08] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all shadow-sm"
                              placeholder={zh ? '例：核心交换机月度巡检' : 'e.g. Core Switch Monthly Check'}
                            />
                          </div>
                          <div>
                            <label className="text-[11px] font-semibold text-black/40 block mb-1.5 uppercase tracking-wide">
                              {zh ? '计划描述 (可选)' : 'Description (Optional)'}
                            </label>
                            <textarea
                              rows={2}
                              value={inspForm.description}
                              onChange={e => setInspForm(f => ({ ...f, description: e.target.value }))}
                              className="w-full px-4 py-2.5 rounded-xl border border-black/[0.08] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all shadow-sm resize-none"
                              placeholder={zh ? '简要说明此计划的执行目的...' : 'Briefly describe the purpose...'}
                            />
                          </div>
                        </div>
                      </div>

                      <div>
                        <label className="text-xs font-bold text-[#164e63] uppercase tracking-wider block mb-2">
                          {zh ? '2. 执行时间窗口' : '2. Execution Window'}
                        </label>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 rounded-xl bg-slate-50/50 p-4 border border-black/5">
                          <div>
                            <label className="text-[11px] font-semibold text-black/40 block mb-1.5 uppercase tracking-wide">
                              {zh ? '开始时间' : 'Start Time'} <span className="text-red-500 ml-0.5">*</span>
                            </label>
                            <DateTimePicker
                              value={inspForm.scheduled_at}
                              onChange={v => setInspForm(f => ({ ...f, scheduled_at: v }))}
                              language={language}
                              className="w-full"
                            />
                          </div>
                          <div>
                            <label className="text-[11px] font-semibold text-black/40 block mb-1.5 uppercase tracking-wide">
                              {zh ? '结束时间' : 'End Time'} <span className="text-red-500 ml-0.5">*</span>
                            </label>
                            <DateTimePicker
                              value={inspForm.expires_at}
                              onChange={v => setInspForm(f => ({ ...f, expires_at: v }))}
                              language={language}
                              className="w-full"
                            />
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Right Column: Scope & Metrics */}
                  <div className="space-y-5">
                    <div>
                      <label className="text-xs font-bold text-[#164e63] uppercase tracking-wider block mb-2">
                        {zh ? '3. 执行范围设定' : '3. Execution Scope'}
                      </label>
                      <div className="space-y-4 rounded-xl bg-slate-50/50 p-4 border border-black/5">
                        <div>
                          <label className="text-[11px] font-semibold text-black/40 block mb-1.5 uppercase tracking-wide">
                            {zh ? '范围类型' : 'Scope Type'}
                          </label>
                          <select
                            value={inspForm.scope_type}
                            onChange={e => setInspForm(f => ({ ...f, scope_type: e.target.value }))}
                            className="w-full px-4 py-2.5 rounded-xl border border-black/[0.08] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all shadow-sm cursor-pointer"
                          >
                            <option value="all">{zh ? '全部设备 (All Devices)' : 'All Devices'}</option>
                            <option value="site">{zh ? '按站点 (By Site)' : 'By Site'}</option>
                            <option value="role">{zh ? '按角色 (By Role)' : 'By Role'}</option>
                            <option value="ip">{zh ? '按 IP 列表 (By IP List)' : 'By IP List'}</option>
                            <option value="tags">{zh ? '按标签 (By Tags)' : 'By Tags'}</option>
                          </select>
                        </div>
                        {inspForm.scope_type !== 'all' && (
                          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}>
                            <label className="text-[11px] font-semibold text-black/40 block mb-1.5 uppercase tracking-wide">
                              {zh ? '过滤值 / 逗号分隔' : 'Filter Values / Comma Separated'}
                            </label>
                            <input
                              type="text" value={inspForm.scope_filter}
                              onChange={e => setInspForm(f => ({ ...f, scope_filter: e.target.value }))}
                              className="w-full px-4 py-2.5 rounded-xl border border-black/[0.08] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all shadow-sm"
                              placeholder={
                                inspForm.scope_type === 'ip' ? '192.168.1.1, 10.0.0.1' :
                                inspForm.scope_type === 'tags' ? 'core, prod' :
                                (zh ? '站点名或角色名' : 'Site or role name')
                              }
                            />
                          </motion.div>
                        )}
                      </div>
                    </div>

                    <div>
                      <label className="text-xs font-bold text-[#164e63] uppercase tracking-wider block mb-2">
                        {zh ? '4. 关联巡检指标' : '4. Inspection Metrics'}
                      </label>
                      <div className="rounded-xl bg-slate-50/50 p-4 border border-black/5 max-h-[220px] overflow-y-auto custom-scrollbar">
                        {inspectionItemsLoading ? (
                          <div className="py-8 text-center text-black/20 text-xs italic">{zh ? '获取指标中...' : 'Loading items...'}</div>
                        ) : inspectionItems.length > 0 ? (
                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2">
                            {inspectionItems.map(item => {
                              const isChecked = inspForm.check_items.includes(item.name);
                              return (
                                <label key={item.id} className="flex items-center gap-3 py-1.5 cursor-pointer group hover:bg-black/5 rounded-lg px-2 transition-colors">
                                  <div className={`w-4 h-4 rounded border flex items-center justify-center transition-all ${isChecked ? 'bg-cyan-500 border-cyan-500' : 'bg-white border-black/10 group-hover:border-black/20'}`}>
                                    {isChecked && <CheckCircle2 size={12} className="text-white" />}
                                    <input
                                      type="checkbox" className="hidden"
                                      checked={isChecked}
                                      onChange={() => {
                                        setInspForm(f => ({
                                          ...f,
                                          check_items: isChecked
                                            ? f.check_items.filter(x => x !== item.name)
                                            : [...f.check_items, item.name]
                                        }));
                                      }}
                                    />
                                  </div>
                                  <div className="min-w-0">
                                    <p className={`text-xs font-bold truncate transition-colors ${isChecked ? 'text-cyan-700' : 'text-black/60 group-hover:text-black/80'}`}>{item.name}</p>
                                    <p className="text-[10px] text-black/30 truncate">{item.category}</p>
                                  </div>
                                </label>
                              );
                            })}
                          </div>
                        ) : (
                          <div className="py-8 text-center text-black/20 text-xs italic">{zh ? '暂无可用指标项' : 'No metrics available'}</div>
                        )}
                      </div>
                      <p className="mt-2 text-[10px] text-black/30 italic px-1">
                        {zh ? '提示：指标项支持在「自动化 > 巡检指标」中单独管理。' : 'Tip: Manage metrics in "Automation > Metrics".'}
                      </p>
                    </div>
                  </div>
                </div>

                {/* Bottom: Approval & Submit */}
                <div className="border-t border-black/5 pt-6 flex flex-col sm:flex-row items-center justify-between gap-6">
                  {/* Approval Module */}
                  <div className="w-full sm:max-w-md bg-amber-50/50 rounded-2xl border border-amber-200/50 p-4">
                    <div className="flex items-center gap-2 mb-3">
                      <Shield size={16} className="text-amber-600" />
                      <span className="text-[11px] font-bold text-amber-900 uppercase tracking-widest">{zh ? '安全审计与授权' : 'Approval & Security'}</span>
                    </div>
                    
                    {approvalStatus === 'idle' && (
                      <div className="flex items-center gap-2">
                        <select
                          value={approverUsername}
                          onChange={(e) => setApproverUsername(e.target.value)}
                          className="flex-1 px-3 py-2 rounded-xl border border-amber-200/50 text-xs bg-white focus:outline-none focus:ring-2 focus:ring-amber-500/10"
                        >
                          <option value="">{zh ? '选择审批人...' : 'Approver...'}</option>
                          {approvers.map(a => (
                            <option key={a.id} value={a.username}>{a.username} ({a.role})</option>
                          ))}
                        </select>
                        <button
                          onClick={requestApproval}
                          disabled={!approverUsername}
                          className="px-3 py-1.5 rounded-lg bg-amber-500 text-white text-[10px] font-black uppercase tracking-wider hover:bg-amber-600 disabled:opacity-30 transition-all shrink-0 shadow-sm active:scale-95"
                        >
                          {zh ? '发送码' : 'Send'}
                        </button>
                      </div>
                    )}

                    {(approvalStatus === 'sending' || approvalStatus === 'sent') && (
                      <div className="flex items-center gap-2">
                        <input
                          type="text"
                          value={approvalCode}
                          onChange={(e) => { setApprovalCode(e.target.value.trim()); setApprovalError(''); }}
                          placeholder={zh ? '6 位验证码' : 'Code'}
                          className="flex-1 px-3 py-2 rounded-xl border border-amber-200/50 text-xs bg-white text-center font-mono font-bold focus:outline-none focus:ring-2 focus:ring-amber-500/10"
                          maxLength={6}
                        />
                        <button
                          onClick={verifyApproval}
                          disabled={approvalCode.length !== 6}
                          className="px-3 py-1.5 rounded-lg bg-amber-500 text-white text-[10px] font-black uppercase tracking-wider hover:bg-amber-600 disabled:opacity-30 transition-all shrink-0 shadow-sm active:scale-95"
                        >
                          {zh ? '验证' : 'Verify'}
                        </button>
                        <button onClick={resetApproval} className="p-2 text-amber-900/30 hover:text-amber-900/50 transition-colors">
                          <RotateCcw size={14} />
                        </button>
                      </div>
                    )}

                    {approvalStatus === 'verified' && (
                      <div className="flex items-center justify-between gap-2 px-3 py-2 rounded-xl bg-emerald-50 border border-emerald-200 shadow-sm">
                        <div className="flex items-center gap-2 text-emerald-700">
                          <CheckCircle2 size={16} />
                          <span className="text-xs font-bold">{zh ? '审批已通过' : 'Approved'}</span>
                        </div>
                        <button onClick={resetApproval} className="text-[10px] font-bold text-emerald-900/40 hover:text-emerald-900/60 uppercase">
                          {zh ? '重置' : 'Reset'}
                        </button>
                      </div>
                    )}
                    {approvalError && <p className="mt-2 text-[10px] text-red-500 font-medium px-1">{approvalError}</p>}
                  </div>

                  {/* Submit Actions */}
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => { setShowAddInspSchedule(false); resetApproval(); }}
                      className="px-6 py-3 rounded-xl border border-black/10 text-sm font-bold text-black/40 hover:bg-black/5 hover:text-black/60 transition-all"
                    >
                      {zh ? '取消' : 'Cancel'}
                    </button>
                    <button
                      onClick={addInspSchedule}
                      disabled={!inspForm.name.trim() || !inspForm.scheduled_at || !inspForm.expires_at || approvalStatus !== 'verified'}
                      className="px-8 py-3 rounded-xl bg-gradient-to-r from-cyan-600 to-blue-600 text-white text-sm font-bold shadow-lg shadow-cyan-600/20 hover:scale-[1.02] disabled:opacity-40 disabled:scale-100 transition-all"
                    >
                      {zh ? '发布执行计划' : 'Publish Schedule'}
                    </button>
                  </div>
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

                  {/* Table Body */}
                  <div className="flex-1 overflow-y-auto max-h-[calc(100vh-420px)] custom-scrollbar">
                    {inspSchedulesLoading ? (
                      <div className="h-full flex flex-col items-center justify-center py-24 text-black/20 gap-3">
                        <RotateCcw size={32} className="animate-spin opacity-20" />
                        <span className="text-sm font-medium">{zh ? '正在加载数据...' : 'Loading schedules...'}</span>
                      </div>
                    ) : inspSchedules.length > 0 ? (
                      <table className="w-full text-left border-collapse min-w-[900px]">
                        <thead className="sticky top-0 bg-slate-50 border-b border-black/5 z-10">
                          <tr className="bg-black/[0.01]">
                            <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{zh ? '计划名称' : 'Plan Name'}</th>
                            <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{zh ? '执行窗口' : 'Execution window'}</th>
                            <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{zh ? '范围 / 指标' : 'Scope / Metrics'}</th>
                            <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{zh ? '状态' : 'Status'}</th>
                            <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider text-right">{zh ? '操作' : 'Actions'}</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-black/[0.03]">
                          {inspSchedules.map(sch => {
                            const st = getScheduleStatus(sch, zh);
                            const checkList = Array.isArray(sch.check_items) ? sch.check_items : [];
                            return (
                              <tr key={sch.id} className="group hover:bg-cyan-50/30 transition-colors">
                                <td className="px-6 py-4">
                                  <div className="flex flex-col min-w-0">
                                    <span className="text-sm font-bold text-[#164e63] truncate group-hover:text-cyan-700 transition-colors">{sch.name}</span>
                                    {sch.description && <span className="text-[10px] text-black/30 truncate mt-0.5 italic">{sch.description}</span>}
                                  </div>
                                </td>
                                <td className="px-6 py-4">
                                  <div className="flex flex-col gap-1">
                                    <div className="flex items-center gap-1.5 text-[11px] font-mono text-black/60">
                                      <Play size={10} className="text-emerald-500" />
                                      <span>{fmtDateTime(sch.scheduled_at, zh)}</span>
                                    </div>
                                    <div className="flex items-center gap-1.5 text-[11px] font-mono text-black/40">
                                      <X size={10} className="text-slate-400" />
                                      <span>{fmtDateTime(sch.expires_at, zh)}</span>
                                    </div>
                                  </div>
                                </td>
                                <td className="px-6 py-4">
                                  <div className="flex flex-col gap-2">
                                    <span className="text-[11px] font-bold text-black/50 bg-black/5 self-start px-2 py-0.5 rounded-full">
                                      {sch.scope_type === 'all' ? (zh ? '全量' : 'All') : `${sch.scope_type}:${sch.scope_filter || '*'}`}
                                    </span>
                                    <div className="flex flex-wrap gap-1">
                                      {checkList.slice(0, 3).map(item => (
                                        <span key={item} className="px-1.5 py-0.5 rounded-md bg-cyan-50 border border-cyan-100 text-[9px] font-bold text-cyan-600 uppercase tracking-tighter">
                                          {item}
                                        </span>
                                      ))}
                                      {checkList.length > 3 && (
                                        <span className="px-1.5 py-0.5 rounded-md bg-black/5 text-[9px] font-bold text-black/30">+{checkList.length - 3}</span>
                                      )}
                                    </div>
                                  </div>
                                </td>
                                <td className="px-6 py-4">
                                  <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-bold ${st.cls}`}>
                                    <div className={`w-1.5 h-1.5 rounded-full ${sch.enabled ? 'animate-pulse bg-current' : 'bg-current opacity-40'}`} />
                                    {st.label}
                                  </span>
                                </td>
                                <td className="px-6 py-4 text-right">
                                  <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                    <button
                                      onClick={() => { setSelectedSchedule(sch); setShowScheduleDetail(true); }}
                                      className="p-2 rounded-xl text-black/40 hover:bg-black/5 hover:text-black/60 transition-all"
                                      title={zh ? '详情' : 'Detail'}
                                    >
                                      <Play size={14} />
                                    </button>
                                    <button
                                      onClick={() => toggleInspScheduleEnabled(sch)}
                                      className={`p-2 rounded-xl transition-all ${sch.enabled ? 'text-amber-600 hover:bg-amber-50' : 'text-emerald-600 hover:bg-emerald-50'}`}
                                      title={sch.enabled ? (zh ? '停用' : 'Disable') : (zh ? '启用' : 'Enable')}
                                    >
                                      <Activity size={14} />
                                    </button>
                                    <button
                                      onClick={() => deleteInspSchedule(sch.id)}
                                      className="p-2 rounded-xl text-black/40 hover:bg-red-50 hover:text-red-500 transition-all"
                                      title={zh ? '删除' : 'Delete'}
                                    >
                                      <Trash2 size={14} />
                                    </button>
                                  </div>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
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
                            {log.source === 'inspection' ? (
                              <div className="flex items-center gap-3">
                                <div className="flex flex-col">
                                  <span className="text-xs font-bold text-black/60">{log.total_devices} {zh ? '台设备' : 'Devices'}</span>
                                  <div className="flex items-center gap-1.5 mt-1">
                                    <span className="text-[10px] text-black/40">{zh ? '平均分' : 'Avg Score'}:</span>
                                    <span className={`text-[11px] font-black tabular-nums ${
                                    (log.avg_health_score || 0) >= 80 ? 'text-emerald-600' : (log.avg_health_score || 0) >= 60 ? 'text-amber-600' : 'text-red-600'
                                    }`}>
                                      {log.avg_health_score?.toFixed(1) ?? '—'}
                                    </span>
                                  </div>
                                  </div>
                                </div>
                              ) : (
                                <div className="flex items-center gap-3">
                                  <div className="flex flex-col">
                                    <span className="text-xs font-bold text-black/60">{log.total_devices} {zh ? '台设备' : 'Devices'}</span>
                                    <div className="flex items-center gap-1.5 mt-1">
                                      <div className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                                      <span className="text-[10px] text-emerald-600 font-bold">{log.success_count}</span>
                                      <div className="w-1.5 h-1.5 rounded-full bg-red-400 ml-1" />
                                      <span className="text-[10px] text-red-600 font-bold">{log.failed_count}</span>
                                      {log.partial_count ? (
                                        <>
                                          <div className="w-1.5 h-1.5 rounded-full bg-amber-400 ml-1" />
                                          <span className="text-[10px] text-amber-600 font-bold">{log.partial_count}</span>
                                        </>
                                      ) : null}
                                    </div>
                                  </div>
                                </div>
                              )}
                            </td>
                            <td className="px-6 py-4">
                              <span className="text-xs font-bold text-black/40">{log.created_by}</span>
                            </td>
                            <td className="px-6 py-4 text-right">
                              <div className="flex items-center justify-end gap-2">
                                {onRerun && (
                                  <button
                                    onClick={() => onRerun(log)}
                                    className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-bold text-amber-600 border border-amber-100 bg-amber-50 hover:bg-amber-100 transition-all active:scale-95"
                                    title={zh ? '重新执行' : 'Rerun'}
                                  >
                                    <RotateCcw size={12} />
                                    {zh ? '重试' : 'Retry'}
                                  </button>
                                )}
                                <button
                                  onClick={() => handleSelectLog(log)}
                                  className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-bold text-cyan-600 border border-cyan-100 bg-cyan-50/20 hover:bg-cyan-50 transition-all active:scale-95"
                                >
                                  <Eye size={12} />
                                  {zh ? '查看' : 'View'}
                                </button>
                                <button
                                  onClick={async () => {
                                    if (log.source === 'inspection') {
                                      // Smart Excel Report Export
                                      try {
                                        const resp = await fetch(`/api/inspections/${log.id}/export`, { headers: authHeaders });
                                        if (resp.ok) {
                                          const blob = await resp.blob();
                                          const url = URL.createObjectURL(blob);
                                          const a = document.createElement('a');
                                          a.href = url;
                                          a.download = `Smart_Inspection_Report_${log.id}.xlsx`;
                                          a.click();
                                          URL.revokeObjectURL(url);
                                          return;
                                        }
                                      } catch (err) {
                                        console.error('Failed to export Excel:', err);
                                      }
                                    }

                                    // Fallback to JSON download (original behavior)
                                    let dlData = null;
                                    let fn = `execution_${log.id}.json`;
                                    try {
                                      if (log.source === 'inspection') {
                                        const r = await fetch(`/api/inspections/${log.id}`, { headers: authHeaders });
                                        if (r.ok) {
                                          const j = await r.json();
                                          dlData = j.data;
                                          fn = `inspection_report_${log.id}.json`;
                                        }
                                      } else {
                                        const r1 = await fetch(`/api/playbooks/${log.id}`, { headers: authHeaders });
                                        const r2 = await fetch(`/api/playbooks/${log.id}/devices?page=1&page_size=100`, { headers: authHeaders });
                                        if (r1.ok && r2.ok) {
                                          const j1 = await r1.json();
                                          const j2 = await r2.json();
                                          dlData = { summary: j1, devices: Array.isArray(j2) ? j2 : (j2.items || []) };
                                          fn = `playbook_execution_${log.id}.json`;
                                        }
                                      }
                                      if (dlData) {
                                        const blob = new Blob([JSON.stringify(dlData, null, 2)], { type: 'application/json' });
                                        const url = URL.createObjectURL(blob);
                                        const a = document.createElement('a');
                                        a.href = url;
                                        a.download = fn;
                                        a.click();
                                        URL.revokeObjectURL(url);
                                      }
                                    } catch (err) { console.error(err); }
                                  }}
                                  className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-bold text-slate-600 border border-slate-200 bg-slate-50 hover:bg-slate-100 transition-all active:scale-95"
                                >
                                  {log.source === 'inspection' ? <FileText size={12} /> : <Download size={12} />}
                                  {log.source === 'inspection' ? (zh ? '导出报表' : 'Export Report') : (zh ? '下载' : 'Download')}
                                </button>
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
          {/* Modal Header */}
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
              {selectedLog.source === 'inspection' && (
                <button
                  onClick={async () => {
                    try {
                      const resp = await fetch(`/api/inspections/${selectedLog.id}/export`, { headers: authHeaders });
                      if (resp.ok) {
                        const blob = await resp.blob();
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url;
                        a.download = `Smart_Inspection_Report_${selectedLog.id}.xlsx`;
                        a.click();
                        URL.revokeObjectURL(url);
                      }
                    } catch (err) { console.error(err); }
                  }}
                  title={zh ? '导出 Smart Excel 报表' : 'Export Smart Excel Report'}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold text-cyan-700 border border-cyan-100 bg-cyan-50/50 hover:bg-cyan-50 transition-all active:scale-95"
                >
                  <FileText size={14} />
                  {zh ? '智能报表' : 'Smart Report'}
                </button>
              )}
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
                                        <div className={`p-4 font-mono text-[11px] whitespace-pre-wrap leading-relaxed ${isError ? 'text-red-300/80' : 'text-white/60'}`}>
                                          {outputStr}
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
                  </div>
                  <div className="flex-1 p-6 font-mono text-xs text-[#d4d4d4] overflow-auto whitespace-pre-wrap select-text relative">
                    {pbDeviceDetail?.phases ? (
                      Object.entries(pbDeviceDetail.phases).map(([phase, output]: any) => {
                        const cmds = (output?.commands || []).map((c: string) => `> ${c}`).join('\n');
                        const body = output?.output
                          || ((output?.commands && output.commands.length > 0) ? output.commands.join('\n') : '');
                        const phaseText = `${cmds ? cmds + '\n' : ''}${body || '—'}`;
                        const dev = devices.find(d => d.id === selectedPbDevice);
                        const phaseFilename = `${dev?.hostname || selectedPbDevice || 'device'}_${phase}`;
                        return (
                          <div key={phase} className="mb-4 group/phase">
                            <div className="flex items-center justify-between mb-1">
                              <span className="text-[#a170e8] font-bold"># PHASE: {phase.toUpperCase()}</span>
                              <OutputActions
                                text={phaseText}
                                filename={phaseFilename}
                                theme="dark"
                                zh={zh}
                              />
                            </div>
                            <div className="pl-4 border-l border-[#a170e8]/20 text-[#e0e0e0]">
                              {output.commands && output.commands.length > 0 && (
                                <div className="text-cyan-400/50 mb-2 font-bold italic">
                                  {output.commands.map((cmd: string, i: number) => (
                                    <div key={i}>&gt; {cmd}</div>
                                  ))}
                                </div>
                              )}
                              {/* output field = actual device response text
                                  fallback: if no output field, treat commands array as raw output lines */}
                              {output.output
                                ? output.output
                                : output.status === 'success' && output.commands && output.commands.length > 0
                                  ? <span className="text-yellow-400/70 italic">{zh ? '命令执行成功，但设备未返回数据（如 ARP 表为空）' : 'Command succeeded but device returned no data'}</span>
                                  : (output.commands && output.commands.length > 0
                                      ? output.commands.join('\n')
                                      : '—')}
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
                          <span className="text-xs font-black text-[#164e63] uppercase tracking-wide bg-white px-3 py-1 rounded-full shadow-sm">{selectedSchedule.scope_type}</span>
                        </div>
                        {selectedSchedule.scope_filter && (
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-bold text-black/40">{zh ? '过滤条件' : 'Filter'}</span>
                            <span className="text-xs font-black text-[#164e63] max-w-[150px] truncate">{selectedSchedule.scope_filter}</span>
                          </div>
                        )}
                        <div className="pt-2 border-t border-black/5">
                          <span className="text-[11px] font-bold text-black/30 block mb-2">{zh ? '时间窗口' : 'Time Window'}</span>
                          <div className="flex items-center gap-3">
                            <div className="flex-1 text-[11px] font-mono text-emerald-600 bg-emerald-50 px-3 py-2 rounded-xl border border-emerald-100 text-center">
                              {fmtDateTime(selectedSchedule.scheduled_at, zh)}
                            </div>
                            <div className="text-black/10">→</div>
                            <div className="flex-1 text-[11px] font-mono text-amber-600 bg-amber-50 px-3 py-2 rounded-xl border border-amber-100 text-center">
                              {fmtDateTime(selectedSchedule.expires_at, zh)}
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
                            onClick={() => { toggleInspScheduleEnabled(selectedSchedule); setSelectedSchedule({ ...selectedSchedule, enabled: selectedSchedule.enabled ? 0 : 1 } as InspectionSchedule); }}
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
    </div>
  );
};

export default ExecutionScheduleTab;
