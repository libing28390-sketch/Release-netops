import React, { useEffect, useState, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { AnimatePresence, motion } from 'motion/react';
import {
  CalendarClock, Plus, X, Trash2, RotateCcw, Zap, Pencil,
  ChevronDown, Info, Shield, CheckCircle2, AlertTriangle,
  Database, Activity, Power, PowerOff,
  Search, FileCode, Eye, Target, FileText, Lock, ArrowUpRight, ChevronUp, Filter, ShieldAlert, User,
} from 'lucide-react';
import Pagination from '../components/Pagination';
import TagConditionPicker, { type TagFilterConfig, EMPTY_TAG_FILTER, serializeTagFilter, parseTagFilter } from '../components/TagConditionPicker';
import PageHero from '../components/PageHero';

/* ═══════════════════════════════════════════════════════ */
/*  Constants                                              */
/* ═══════════════════════════════════════════════════════ */

const CRON_PRESETS = [
  { label: '每天 02:00', labelEn: 'Daily at 02:00', cron: '0 2 * * *' },
  { label: '每天 06:00', labelEn: 'Daily at 06:00', cron: '0 6 * * *' },
  { label: '每天 22:00', labelEn: 'Daily at 22:00', cron: '0 22 * * *' },
  { label: '每12小时', labelEn: 'Every 12 hours', cron: '0 */12 * * *' },
  { label: '每6小时', labelEn: 'Every 6 hours', cron: '0 */6 * * *' },
  { label: '每小时', labelEn: 'Every hour', cron: '0 * * * *' },
  { label: '工作日 08:00', labelEn: 'Weekdays at 08:00', cron: '0 8 * * 1-5' },
  { label: '每周一 03:00', labelEn: 'Mon at 03:00', cron: '0 3 * * 1' },
  { label: '每月1日 02:00', labelEn: '1st of month at 02:00', cron: '0 2 1 * *' },
];

const CRON_FIELD_LABELS_ZH = ['分钟', '小时', '日', '月', '星期'];
const CRON_FIELD_LABELS_EN = ['Minute', 'Hour', 'Day', 'Month', 'Weekday'];
const CRON_FIELD_HINTS_ZH = ['0-59, */5, 0,30', '0-23, */2, 0-6', '1-31, */2', '1-12, */3', '0-6, 1-5'];
const CRON_FIELD_HINTS_EN = ['0-59, */5, 0,30', '0-23, */2, 0-6', '1-31, */2', '1-12, */3', '0-6 (Sun=0), 1-5'];

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

/* ═══════════════════════════════════════════════════════ */
/*  Types                                                  */
/* ═══════════════════════════════════════════════════════ */

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
}

interface EligibleApprover {
  id: string;
  username: string;
  role: string;
}

interface SystemScheduledJob {
  id: string;
  name_zh: string;
  name_en: string;
  description_zh: string;
  description_en: string;
  category?: string;
  action_type?: string;
  deep_link?: string | null;
  trigger?: string;
  next_run_at?: string | null;
}

interface ScheduledJobsTabProps {
  t: (key: string) => string;
  language: string;
  showToast: (msg: string, type?: 'success' | 'error' | 'info') => void;
}

interface FormState {
  name: string;
  action_type: string;
  cron_expr: string;
  device_scope: string;
  device_filter: string;
  commands: string;
  script_id: string;
  is_config: boolean;
  config_reason: string;
  use_admin_creds: boolean;
  major_type: string;
}

interface ValidatedDevice {
  ip: string;
  hostname: string;
  tags: { id: string; label: string; label_zh: string; color: string }[];
}

const INITIAL_FORM: FormState = {
  name: '',
  action_type: 'backup',
  cron_expr: '0 2 * * *',
  device_scope: 'all',
  device_filter: '',
  commands: '',
  script_id: '',
  is_config: false,
  config_reason: '',
  use_admin_creds: false,
  major_type: 'collection', // UI helper state
};

/* ═══════════════════════════════════════════════════════ */
/*  Helpers                                                */
/* ═══════════════════════════════════════════════════════ */

const describeCron = (cron: string, zh: boolean): string => {
  const parts = cron.trim().split(/\s+/);
  if (parts.length < 5) return cron;
  const [min, hour, day, month, dow] = parts;
  const weekDaysZh = ['日', '一', '二', '三', '四', '五', '六'];
  const weekDaysEn = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const fmtTime = (h: string, m: string) => `${h.padStart(2, '0')}:${m.padStart(2, '0')}`;
  if (min.startsWith('*/') && hour === '*') return zh ? `每 ${min.slice(2)} 分钟` : `Every ${min.slice(2)} minutes`;
  if (hour === '*' && !min.includes('/') && day === '*' && month === '*') return zh ? `每小时第 ${min} 分钟` : `Hourly at :${min.padStart(2, '0')}`;
  if (hour.startsWith('*/') && day === '*' && month === '*' && dow === '*') return zh ? `每 ${hour.slice(2)} 小时的第 ${min} 分钟` : `Every ${hour.slice(2)}h at :${min.padStart(2, '0')}`;
  const timeList = (hour.includes(',') ? hour.split(',') : [hour]).map(h => fmtTime(h, min));
  const timeStr = timeList.join(zh ? '、' : ', ');
  if (day === '*' && month === '*' && dow !== '*') {
    if (dow === '1-5') return zh ? `工作日 ${timeStr}` : `Weekdays at ${timeStr}`;
    const days = dow.split(',').map(d => { const n = parseInt(d, 10); return isNaN(n) ? d : (zh ? `周${weekDaysZh[n % 7]}` : weekDaysEn[n % 7]); });
    return zh ? `${days.join('、')} ${timeStr}` : `${days.join(', ')} at ${timeStr}`;
  }
  if (day === '*' && month === '*' && dow === '*') return zh ? `每天 ${timeStr}` : `Daily at ${timeStr}`;
  if (day !== '*' && month === '*') return zh ? `每月 ${day} 日 ${timeStr}` : `Monthly on ${day} at ${timeStr}`;
  return cron;
};

const describeScope = (scope: string, filter: string, zh: boolean): string => {
  if (scope === 'all') return zh ? '全部设备' : 'All devices';
  if (scope === 'ip') {
    const ips = filter.split(/[,\n;]+/).map(s => s.trim()).filter(Boolean);
    if (ips.length === 0) return zh ? 'IP 地址' : 'IP addresses';
    if (ips.length <= 2) return ips.join(', ');
    return `${ips[0]}, ${ips[1]} +${ips.length - 2}`;
  }
  if (scope === 'tag') {
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

const ScheduledJobsTab: React.FC<ScheduledJobsTabProps> = ({ language, showToast }) => {
  const zh = language === 'zh';
  const navigate = useNavigate();

  /* === STATE === */
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const [systemJobs, setSystemJobs] = useState<SystemScheduledJob[]>([]);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [total, setTotal] = useState(0);

  // Modal
  const [showAddJob, setShowAddJob] = useState(false);
  const [detailJob, setDetailJob] = useState<ScheduledJob | null>(null);
  const [editingJob, setEditingJob] = useState<ScheduledJob | null>(null);
  const [viewingScript, setViewingScript] = useState<any>(null); // New state for script content view
  const [presetOpen, setPresetOpen] = useState(false);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);

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
  const [approverUsername, setApproverUsername] = useState('');
  const [approvalToken, setApprovalToken] = useState('');
  const [approvalCode, setApprovalCode] = useState('');
  const [approvalStatus, setApprovalStatus] = useState<'idle' | 'sending' | 'sent' | 'verified'>('idle');
  const [approvalCountdown, setApprovalCountdown] = useState(0);
  const [approvalError, setApprovalError] = useState('');

  // Delete approval state
  const [deleteApprovalOpen, setDeleteApprovalOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<ScheduledJob | null>(null);
  const [deleteReason, setDeleteReason] = useState('');
  const [deleteApprover, setDeleteApprover] = useState('');
  const [deleteToken, setDeleteToken] = useState('');
  const [deleteCode, setDeleteCode] = useState('');
  const [deleteStatus, setDeleteStatus] = useState<'idle' | 'sending' | 'sent' | 'verified'>('idle');
  const [deleteCountdown, setDeleteCountdown] = useState(0);
  const [deleteError, setDeleteError] = useState('');

  // Enabling job tracker
  const [enablingJobId, setEnablingJobId] = useState<string | null>(null);

  // Script selection
  const [availableScripts, setAvailableScripts] = useState<{ id: string; name: string; status: string; category: string }[]>([]);
  const [scriptSearch, setScriptSearch] = useState('');
  const [showScriptDropdown, setShowScriptDropdown] = useState(false);

  const isEditMode = editingJob !== null;

  // Category & Filter state
  const [activeCategory, setActiveCategory] = useState<'all' | 'system' | 'backup' | 'inspection' | 'script_run'>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [systemCollapsed, setSystemCollapsed] = useState(false);

  const filteredJobs = useMemo(() => {
    return jobs.filter(j => {
      const q = searchQuery.trim().toLowerCase();
      const matchQ = !q || j.name.toLowerCase().includes(q) || (j.commands || '').toLowerCase().includes(q) || (j.device_filter || '').toLowerCase().includes(q);
      if (!matchQ) return false;
      if (activeCategory === 'all') return true;
      if (activeCategory === 'system') return false;
      return j.action_type === activeCategory;
    });
  }, [jobs, searchQuery, activeCategory]);

  const filteredSystemJobs = useMemo(() => {
    return systemJobs.filter(sj => {
      const q = searchQuery.trim().toLowerCase();
      const name = (zh ? sj.name_zh : sj.name_en).toLowerCase();
      const desc = (zh ? sj.description_zh : sj.description_en).toLowerCase();
      return !q || name.includes(q) || desc.includes(q);
    });
  }, [systemJobs, searchQuery, zh]);

  const stats = useMemo(() => {
    const backupCnt = jobs.filter(j => j.action_type === 'backup').length;
    const inspCnt = jobs.filter(j => j.action_type === 'inspection').length;
    const scriptCnt = jobs.filter(j => j.action_type === 'script_run').length;
    const activeCnt = jobs.filter(j => j.enabled === 1).length;
    return { backupCnt, inspCnt, scriptCnt, activeCnt };
  }, [jobs]);

  const authHeaders = useMemo(() => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' };
  }, []);

  /* === FETCHERS === */
  const fetchJobs = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`/api/scheduled-jobs?job_type=cron&page=${page}&page_size=${pageSize}`, { headers: authHeaders });
      if (r.ok) {
        const j = await r.json();
        const d = j.data || {};
        setJobs(d.items || []);
        setTotal(d.total || 0);
      }
    } finally {
      setLoading(false);
    }
  }, [authHeaders, page, pageSize]);

  const fetchSystemJobs = useCallback(async () => {
    try {
      const r = await fetch('/api/scheduled-jobs/system', { headers: authHeaders });
      if (r.ok) {
        const j = await r.json();
        setSystemJobs(j?.data?.items || []);
      }
    } catch {
      // Silently skip — system jobs view is optional enrichment, not blocking.
    }
  }, [authHeaders]);

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
  useEffect(() => { fetchSystemJobs(); }, [fetchSystemJobs]);
  useEffect(() => { 
    if (showAddJob) fetchApprovers(); 
    if ((showAddJob || detailJob) && (form.action_type === 'script_run' || detailJob?.action_type === 'script_run')) fetchScripts();
  }, [showAddJob, detailJob, isEditMode, fetchApprovers, fetchScripts, form.action_type]);

  // Auto-load script content when detail modal opens for a script_run job
  useEffect(() => {
    if (detailJob && detailJob.action_type === 'script_run' && detailJob.script_id) {
      void fetchAndShowScriptDetail(detailJob.script_id);
    } else if (!detailJob) {
      setViewingScript(null);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detailJob?.id, detailJob?.script_id]);

  useEffect(() => {
    if (approvalCountdown <= 0) return;
    const t = setTimeout(() => setApprovalCountdown(c => c - 1), 1000);
    return () => clearTimeout(t);
  }, [approvalCountdown]);

  useEffect(() => {
    if (deleteCountdown <= 0) return;
    const t = setTimeout(() => setDeleteCountdown(c => c - 1), 1000);
    return () => clearTimeout(t);
  }, [deleteCountdown]);

  /* === MODAL HELPERS === */
  const resetFormState = () => {
    setForm({ ...INITIAL_FORM });
    setTagFilter({ ...EMPTY_TAG_FILTER });
    setIpDevices([]);
    setIpInput('');
    setScriptSearch('');
    setShowScriptDropdown(false);
    setApproverUsername('');
    setApprovalToken('');
    setApprovalCode('');
    setApprovalStatus('idle');
    setApprovalCountdown(0);
    setApprovalError('');
  };

  const toggleAddJob = () => {
    if (showAddJob) {
      setShowAddJob(false);
      setEditingJob(null);
      setEnablingJobId(null);
    } else {
      resetFormState();
      setEditingJob(null);
      setShowAddJob(true);
    }
  };

  const openEditModal = (job: ScheduledJob) => {
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
      major_type: job.action_type === 'backup' ? 'collection' : 'change', // Simple inference
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
    setApprovalToken('');
    setApprovalCode('');
    setApprovalStatus('idle');
    setApprovalCountdown(0);
    setApprovalError('');
    setShowAddJob(true);
  };

  const fetchAndShowScriptDetail = async (scriptId: string) => {
    if (!scriptId) return;
    try {
      const r = await fetch('/api/scripts', { headers: authHeaders });
      if (r.ok) {
        const j = await r.json();
        const data = j.data?.items || j.data || j;
        const list = Array.isArray(data) ? data : [];
        const script = list.find((s: any) => s.id === scriptId);
        if (script) {
          setViewingScript(script);
        } else {
          showToast(zh ? '找不到脚本详情' : 'Script detail not found', 'error');
        }
      }
    } catch {
      showToast(zh ? '获取脚本失败' : 'Failed to fetch script', 'error');
    }
  };

  const closeModal = () => {
    setShowAddJob(false);
    setEditingJob(null);
    setEnablingJobId(null);
    setPresetOpen(false);
  };

  /* === APPROVAL (create & update) === */
  const requestApproval = async () => {
    if (!approverUsername) return;
    setApprovalStatus('sending');
    setApprovalError('');
    try {
      const actionLabel = ACTION_TYPES.find(a => a.value === form.action_type);
      const r = await fetch('/api/config-approval/request', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({
          approver_username: approverUsername,
          config_reason: form.config_reason || `${zh ? (isEditMode ? '修改定时作业' : '创建定时作业') : (isEditMode ? 'Update job' : 'Create job')}: ${form.name}`,
          device_hostname: form.device_scope === 'all' ? (zh ? '全部设备' : 'All devices') : form.device_filter,
          command_preview: '',
          approval_type: 'scheduled_job',
          extra_fields: {
            action_type: zh ? (actionLabel?.labelZh || form.action_type) : (actionLabel?.labelEn || form.action_type),
            schedule_desc: describeCron(form.cron_expr, zh),
            operation: isEditMode ? 'UPDATE' : 'CREATE',
          },
        }),
      });
      const j = await r.json();
      if (r.ok && j.success) {
        setApprovalToken(j.approval_token);
        setApprovalStatus('sent');
        setApprovalCountdown(300);
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

  /* === APPROVAL (delete) === */
  const requestDeleteApproval = async () => {
    if (!deleteApprover || !deleteTarget) return;
    setDeleteStatus('sending');
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
          approval_type: 'scheduled_job_delete',
          extra_fields: { action_type: 'DELETE', job_name: deleteTarget.name },
        }),
      });
      const j = await r.json();
      if (r.ok && j.success) {
        setDeleteToken(j.approval_token);
        setDeleteStatus('sent');
        setDeleteCountdown(300);
        showToast(zh ? '删除验证码已发至审批人' : 'Delete code sent to approver', 'success');
      } else {
        setDeleteStatus('idle');
        setDeleteError(j.detail || j.message || 'Failed');
      }
    } catch {
      setDeleteStatus('idle');
      setDeleteError(zh ? '发送验证码失败' : 'Failed to send code');
    }
  };

  const verifyDeleteApproval = async () => {
    if (!deleteToken || !deleteCode) return;
    try {
      const r = await fetch('/api/config-approval/verify', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({ approval_token: deleteToken, code: deleteCode }),
      });
      const j = await r.json();
      if (r.ok && j.success) {
        setDeleteStatus('verified');
        showToast(zh ? '删除审批验证通过' : 'Delete approval verified', 'success');
      } else {
        setDeleteError(j.detail || j.message || 'Invalid code');
      }
    } catch {
      setDeleteError(zh ? '验证失败' : 'Verification failed');
    }
  };

  const executeDeleteJob = async () => {
    if (!deleteTarget || deleteStatus !== 'verified') return;
    try {
      const url = `/api/scheduled-jobs/${deleteTarget.id}?approval_token=${encodeURIComponent(deleteToken)}&approval_code=${encodeURIComponent(deleteCode)}`;
      const r = await fetch(url, { method: 'DELETE', headers: authHeaders });
      const j = await r.json();
      if (r.ok && j.success) {
        setDeleteApprovalOpen(false);
        setDeleteTarget(null);
        fetchJobs();
        showToast(zh ? '定时作业已永久安全删除' : 'Job successfully deleted', 'success');
      } else {
        setDeleteError(j.detail || j.message || 'Deletion failed');
      }
    } catch {
      setDeleteError(zh ? '删除请求操作失败' : 'Deletion failed');
    }
  };

  /* === Candidate IP search (Modal for checking/selection before adding) === */
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
        // 1) Search devices table (add ALL fuzzy matches to candidates)
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
                  selected: true, // Default checked
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
                    candidatesMap[ip] = candidatesMap[ip] || {
                      ip,
                      hostname: a.hostname || '',
                      tags: [],
                      selected: true,
                    };
                  }
                }
              }
            }
          } catch { /* ignore */ }
        }

        // 3) If neither found, treat as manual IP input
        if (!found && !ipDevices.some(existing => existing.ip === query)) {
          candidatesMap[query] = candidatesMap[query] || {
            ip: query,
            hostname: '',
            tags: [],
            selected: true,
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

  const createJob = async () => {
    if (!form.name.trim()) return;
    if (approvalStatus !== 'verified') {
      showToast(zh ? '请先发送验证码并完成审批验证' : 'Please complete approval verification first', 'error');
      return;
    }
    try {
      const r = await fetch('/api/scheduled-jobs', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({
          ...form,
          use_admin_creds: form.use_admin_creds ? 1 : 0,
          device_filter: resolveFilter(),
          job_type: 'cron',
          approval_token: approvalToken,
          approval_code: approvalCode,
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
    if (!editingJob || !form.name.trim()) return;
    if (approvalStatus !== 'verified') {
      showToast(zh ? '请先发送验证码并完成审批验证' : 'Please complete approval verification first', 'error');
      return;
    }
    try {
      const r = await fetch(`/api/scheduled-jobs/${editingJob.id}`, {
        method: 'PUT',
        headers: authHeaders,
        body: JSON.stringify({
          name: form.name,
          action_type: form.action_type,
          cron_expr: form.cron_expr,
          device_scope: form.device_scope,
          device_filter: resolveFilter(),
          script_id: form.script_id,
          commands: form.commands,
          config_reason: form.config_reason,
          use_admin_creds: form.use_admin_creds ? 1 : 0,
          approval_token: approvalToken,
          approval_code: approvalCode,
          ...(enablingJobId === editingJob.id ? { enabled: true } : {}),
        }),
      });
      const j = await r.json();
      if (r.ok && j.success) {
        closeModal();
        fetchJobs();
        showToast(enablingJobId === editingJob.id ? (zh ? '作业已成功启用' : 'Job enabled') : (zh ? '作业已更新' : 'Job updated'), 'success');
      } else {
        showToast(j.detail || j.message || 'Failed', 'error');
      }
    } catch {
      showToast(zh ? '操作失败' : 'Operation failed', 'error');
    }
  };

  const deleteJob = async (id: string) => {
    try {
      const r = await fetch(`/api/scheduled-jobs/${id}`, { method: 'DELETE', headers: authHeaders });
      if (r.ok) {
        fetchJobs();
        showToast(zh ? '已删除' : 'Deleted', 'success');
      }
    } catch { /* ignore */ }
    setDeleteConfirmId(null);
  };

  const toggleJobEnabled = async (job: ScheduledJob) => {
    const nextEnabled = !job.enabled;
    if (!nextEnabled) {
      // 停用作业不需要审核，直接停用
      try {
        const r = await fetch(`/api/scheduled-jobs/${job.id}/toggle`, {
          method: 'PUT',
          headers: authHeaders,
          body: JSON.stringify({ enabled: false }),
        });
        if (r.ok) {
          fetchJobs();
          showToast(zh ? '作业已安全停用' : 'Job disabled', 'success');
        }
      } catch { /* ignore */ }
      return;
    }
    // 启用作业需要审核
    setEnablingJobId(job.id);
    openEditModal(job);
    showToast(zh ? '恢复启用定时作业需完成审批授权' : 'Enabling job requires approval verification', 'info');
  };

  const submitForm = () => {
    if (form.action_type === 'script_run' && !form.script_id) {
      showToast(zh ? '请选择一个要执行的脚本' : 'Please select a script to execute', 'error');
      return;
    }
    if (isEditMode) updateJob();
    else createJob();
  };

  /* === CRON === */
  const cronParts = form.cron_expr.split(/\s+/);
  const cronFields = [cronParts[0] ?? '0', cronParts[1] ?? '*', cronParts[2] ?? '*', cronParts[3] ?? '*', cronParts[4] ?? '*'];
  const updateCronField = (index: number, value: string) => {
    const p = [...cronFields]; p[index] = value || '*';
    setForm(f => ({ ...f, cron_expr: p.join(' ') }));
  };

  /* ════════════════════════════════════════════════════ */
  /*  RENDER                                              */
  /* ════════════════════════════════════════════════════ */
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
              className="inline-flex h-8 items-center gap-1 rounded-xl border border-black/8 bg-white px-3 text-[11px] font-medium text-[#0e7490] transition-all hover:bg-cyan-50 hover:border-cyan-400/30"
            >
              <RotateCcw size={12} className={loading ? 'animate-spin' : ''} />
              {zh ? '刷新' : 'Refresh'}
            </button>
            <button
              onClick={toggleAddJob}
              className={`flex items-center gap-1.5 px-4 py-2.5 rounded-xl text-sm font-bold shadow-sm transition-all active:scale-[0.97] ${
                showAddJob
                  ? 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                  : 'bg-gradient-to-r from-cyan-500 to-cyan-600 text-white hover:from-cyan-400 hover:to-cyan-500'
              }`}
            >
              {showAddJob ? <X size={16} /> : <Plus size={16} />}
              {showAddJob ? (zh ? '取消新建' : 'Cancel') : (zh ? '新建定时作业' : 'New Scheduled Job')}
            </button>
          </>
        }
      />

      <div className="flex-1 overflow-auto px-6 py-5 space-y-4">

      <AnimatePresence mode="wait">
        {showAddJob ? (
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
                  {enablingJobId === editingJob?.id ? (zh ? '安全启用授权验证' : 'Enable Scheduled Job (Auth Required)') : isEditMode ? (zh ? '编辑定时作业' : 'Edit Scheduled Job') : (zh ? '配置新的定时作业' : 'Configure New Scheduled Job')}
                </h3>
                
              </div>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
                  {/* Left column */}
                  <div className="space-y-4">
                    <div>
                      <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '作业名称' : 'Name'}</label>
                      <input
                        type="text" value={form.name}
                        onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                        className="w-full px-3.5 py-2.5 rounded-xl border border-black/[0.08] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all"
                        placeholder={zh ? '每日配置备份' : 'Daily config backup'}
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
                                  className="absolute z-[60] left-0 right-0 mt-2 bg-[#0f172a]/95 backdrop-blur-xl border border-white/10 rounded-2xl shadow-2xl max-h-48 overflow-y-auto no-scrollbar"
                                >
                                   {(() => {
                                      const filtered = (availableScripts || []).filter(s => {
                                         const searchVal = scriptSearch.toLowerCase();
                                         return s.name.toLowerCase().includes(searchVal);
                                      });
                                      
                                      if (filtered.length === 0) {
                                         return <div className="p-8 text-center text-slate-400 text-[11px] italic">{zh ? '未找到匹配的脚本' : 'No matching scripts found'}</div>;
                                      }

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
                                                     {isWrongCategory && (
                                                        <span className="text-[8px] text-amber-500/60 italic font-normal">
                                                           {zh ? '(非当前分类)' : '(Not current category)'}
                                                        </span>
                                                     )}
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

                    {/* IP input — inline, right below Device Scope */}
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

                        {ipError && (
                          <p className={`text-[10px] mt-1 ${ipError.includes('已添加') || ipError.includes('added') ? 'text-amber-500' : 'text-red-500'}`}>{ipError}</p>
                        )}

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
                                {dev.tags.length > 0 && (
                                  <div className="flex items-center gap-1 flex-1 min-w-0 overflow-hidden">
                                    {dev.tags.slice(0, 3).map(tag => (
                                      <span
                                        key={tag.id}
                                        className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-medium bg-white border border-black/[0.06] shrink-0"
                                      >
                                        <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: tag.color }} />
                                        <span className="truncate">{zh ? (tag.label_zh || tag.label) : tag.label}</span>
                                      </span>
                                    ))}
                                    {dev.tags.length > 3 && (
                                      <span className="text-[9px] text-black/30 shrink-0">+{dev.tags.length - 3}</span>
                                    )}
                                  </div>
                                )}
                                <button
                                  type="button"
                                  onClick={() => removeIpDevice(dev.ip)}
                                  className="p-1 rounded-lg text-black/25 hover:text-red-500 hover:bg-red-50 transition-all shrink-0 ml-auto"
                                  title={zh ? '移除' : 'Remove'}
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

                    {/* Tag picker — inline, right below Device Scope */}
                    {form.device_scope === 'tag' && (
                      <div>
                        <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '标签条件' : 'Tag Conditions'}</label>
                        <TagConditionPicker value={tagFilter} onChange={setTagFilter} language={language} />
                      </div>
                    )}

                    {/* Site / Role filter */}
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

                  {/* Right column */}
                  <div className="space-y-4">
                    {/* Cron */}
                    <div className="space-y-3">
                      <div className="relative">
                        <button
                          type="button"
                          onClick={() => setPresetOpen(!presetOpen)}
                          className="inline-flex h-10 w-full items-center justify-between gap-2 rounded-xl border border-black/8 bg-[#f8fafc] px-3.5 text-sm text-[#164e63] transition-all hover:border-cyan-400/30 hover:bg-white"
                        >
                          <div className="flex items-center gap-2">
                            <Zap size={13} className="text-cyan-500" />
                            <span>{zh ? '快速预设' : 'Quick Presets'}</span>
                          </div>
                          <ChevronDown size={14} className={`text-black/30 transition-transform ${presetOpen ? 'rotate-180' : ''}`} />
                        </button>
                        <AnimatePresence>
                          {presetOpen && (
                            <motion.div
                              initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
                              className="absolute z-20 mt-1.5 w-full rounded-xl border border-black/8 bg-white shadow-lg overflow-hidden max-h-56 overflow-y-auto"
                            >
                              {CRON_PRESETS.map(p => (
                                <button
                                  type="button" key={p.cron}
                                  onClick={() => { setForm(f => ({ ...f, cron_expr: p.cron })); setPresetOpen(false); }}
                                  className={`flex w-full items-center justify-between px-3.5 py-2.5 text-sm transition-colors hover:bg-[#ecfeff] ${form.cron_expr === p.cron ? 'bg-[#ecfeff] text-[#0891b2] font-medium' : 'text-black/60'}`}
                                >
                                  <span>{zh ? p.label : p.labelEn}</span>
                                  <code className="text-[10px] font-mono text-black/30">{p.cron}</code>
                                </button>
                              ))}
                            </motion.div>
                          )}
                        </AnimatePresence>
                      </div>

                      <div className="space-y-2">
                        <div className="flex items-center gap-1.5">
                          <Info size={11} className="text-black/25" />
                          <p className="text-[10px] text-black/30">{zh ? '标准 5 段 Cron：分 时 日 月 周' : '5-field Cron: min hour day month weekday'}</p>
                        </div>
                        <div className="grid grid-cols-5 gap-1.5">
                          {cronFields.map((val, i) => (
                            <div key={i}>
                              <label className="block text-[9px] font-bold uppercase tracking-wider text-black/30 mb-0.5">
                                {zh ? CRON_FIELD_LABELS_ZH[i] : CRON_FIELD_LABELS_EN[i]}
                              </label>
                              <input
                                value={val}
                                onChange={e => updateCronField(i, e.target.value)}
                                placeholder="*"
                                className="w-full rounded-lg border border-black/8 bg-[#f8fafc] px-2 py-1.5 text-center font-mono text-sm text-[#164e63] outline-none placeholder:text-black/20 focus:border-cyan-400/40 focus:bg-white focus:ring-2 focus:ring-cyan-500/10 transition-all"
                              />
                              <p className="mt-0.5 text-[8px] text-black/20 text-center truncate">
                                {zh ? CRON_FIELD_HINTS_ZH[i] : CRON_FIELD_HINTS_EN[i]}
                              </p>
                            </div>
                          ))}
                        </div>
                        <div className="flex items-center gap-3 rounded-lg bg-cyan-500/[0.04] px-3 py-2">
                          <code className="flex-1 font-mono text-sm text-[#164e63] font-semibold">{form.cron_expr}</code>
                          <span className="text-[11px] text-black/40">{describeCron(form.cron_expr, zh)}</span>
                        </div>
                      </div>
                    </div>

                      {form.action_type !== 'backup' && (
                        <div className="space-y-2">
                          <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block">
                            {form.action_type === 'inspection' ? (zh ? '巡检指标项' : 'Inspection Items') : (zh ? '执行命令 (可选)' : 'Commands (Optional)')}
                          </label>
                          <textarea
                            value={form.commands}
                            onChange={e => setForm(f => ({ ...f, commands: e.target.value }))}
                            rows={3}
                            className="w-full px-3 py-2 rounded-xl border border-black/[0.08] text-xs font-mono bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all resize-none"
                            placeholder={form.action_type === 'inspection' 
                              ? (zh ? '输入指标名称，每行一个\nnet_cisco_cpu\nnet_cisco_mem' : 'Enter metric names, one per line\nnet_cisco_cpu\nnet_cisco_mem')
                              : (zh ? '输入设备命令，每行一个' : 'Enter commands, one per line')
                            }
                          />
                        </div>
                      )}

                      {/* Execution User / Role Level */}
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
                              <div className="text-xs font-bold flex items-center gap-1.5">
                                <User className="w-3.5 h-3.5 text-cyan-600 shrink-0" />
                                <span className="truncate">{zh ? '普通运维操作员' : 'Normal Operator'}</span>
                              </div>
                              <div className="text-[10px] text-black/40 font-normal mt-0.5 leading-snug">{zh ? '日常例行巡检与常规低危命令，使用标准受限凭据连接' : 'Routine inspection & standard commands using normal creds'}</div>
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
                              <div className="text-xs font-bold flex items-center gap-1.5 text-amber-800">
                                <ShieldAlert className="w-3.5 h-3.5 text-amber-600 shrink-0" />
                                <span className="truncate">{zh ? '特权借用 (Enable/Admin)' : 'Privileged Borrowing'}</span>
                              </div>
                              <div className="text-[10px] text-amber-700/70 font-normal mt-0.5 leading-snug">{zh ? '高危或管理作业自动申请使用硬件保险箱中的提权密码' : 'Auto borrow enable/admin credentials from hardware vault'}</div>
                            </div>
                          </button>
                        </div>
                      </div>

                      {/* Approval (create & edit) */}
                      <div className="rounded-xl border border-black/8 overflow-hidden">
                        <div className={`px-4 py-2.5 flex items-center gap-2.5 ${
                          approvalStatus === 'verified'
                            ? 'bg-gradient-to-r from-emerald-500 to-emerald-600'
                            : 'bg-gradient-to-r from-[#005b75] to-[#00465a]'
                        }`}>
                          <Shield className="w-3.5 h-3.5 text-white/90" />
                          <span className="text-[12px] font-semibold text-white/95">
                            {approvalStatus === 'verified'
                              ? (zh ? '审批已通过' : 'Approval Granted')
                              : (zh ? '审批验证' : 'Approval Required')}
                          </span>
                          {approvalStatus === 'verified' && (
                            <span className="ml-auto text-[11px] text-white/70 font-medium flex items-center gap-1">
                              <CheckCircle2 className="w-3 h-3" />
                              {zh ? '可以创建' : 'Ready'}
                            </span>
                          )}
                        </div>

                        {approvalStatus !== 'verified' && (
                          <div className="px-4 py-3.5 bg-[#f7fbfc] space-y-3">
                            <div className="space-y-3">
                              <div>
                                <label className="text-[11px] font-semibold text-black/50 mb-1 block">{zh ? '变更原因' : 'Reason'}</label>
                                <input
                                  value={form.config_reason}
                                  onChange={e => setForm(f => ({ ...f, config_reason: e.target.value }))}
                                  placeholder={zh ? '创建定时备份作业' : 'Create scheduled backup job'}
                                  className="w-full rounded-xl border border-black/10 bg-white px-3 py-2 text-xs outline-none focus:border-[#00bceb] focus:ring-1 focus:ring-[#00bceb]/20 placeholder:text-black/25 transition-all"
                                  maxLength={200}
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
                                      <option key={u.id} value={u.username}>
                                        {u.username} ({u.role})
                                      </option>
                                    ))}
                                  </select>
                                  <button
                                    type="button"
                                    onClick={requestApproval}
                                    disabled={!approverUsername || !form.config_reason.trim() || approvalStatus === 'sending' || (approvalStatus === 'sent' && approvalCountdown > 0)}
                                    className={`px-3 py-2 rounded-xl text-[11px] font-semibold transition-all whitespace-nowrap flex items-center gap-1.5 ${
                                      approverUsername && form.config_reason.trim() && !(approvalStatus === 'sent' && approvalCountdown > 0)
                                        ? 'bg-[#005b75] text-white hover:bg-[#00465a] shadow-sm'
                                        : 'bg-black/8 text-black/30 cursor-not-allowed'
                                    }`}
                                  >
                                    {approvalStatus === 'sending' ? (
                                      <RotateCcw className="w-3 h-3 animate-spin" />
                                    ) : approvalStatus === 'sent' && approvalCountdown > 0 ? (
                                      `${Math.floor(approvalCountdown / 60)}:${String(approvalCountdown % 60).padStart(2, '0')}`
                                    ) : (
                                      zh ? '发送验证码' : 'Send Code'
                                    )}
                                  </button>
                                </div>
                              </div>
                            </div>

                            {approvalStatus === 'sent' && (
                              <div className="space-y-2">
                                <label className="text-[11px] text-black/40 block">
                                  {zh ? '输入审批人收到的 6 位验证码' : 'Enter the 6-digit code sent to approver'}
                                </label>
                                <div className="flex items-center gap-2">
                                  <input
                                    value={approvalCode}
                                    onChange={e => { setApprovalCode(e.target.value.replace(/\D/g, '').slice(0, 6)); setApprovalError(''); }}
                                    placeholder="000000"
                                    maxLength={6}
                                    className="w-36 tracking-[0.3em] text-center rounded-xl border border-black/10 bg-white px-3 py-2 text-sm font-mono outline-none focus:border-[#00bceb] focus:ring-1 focus:ring-[#00bceb]/20 transition-all"
                                  />
                                  <button
                                    type="button"
                                    onClick={verifyApproval}
                                    disabled={approvalCode.length !== 6}
                                    className={`px-4 py-2 rounded-xl text-xs font-bold transition-all ${
                                      approvalCode.length === 6
                                        ? 'bg-emerald-600 text-white hover:bg-emerald-700'
                                        : 'bg-black/8 text-black/30 cursor-not-allowed'
                                    }`}
                                  >
                                    {zh ? '验证' : 'Verify'}
                                  </button>
                                </div>
                              </div>
                            )}

                            {approvalError && (
                              <div className="flex items-center gap-1.5 text-red-600 text-[11px]">
                                <AlertTriangle className="w-3 h-3" />
                                {approvalError}
                              </div>
                            )}

                            <p className="text-[10px] text-black/25">
                              {zh ? '验证码将通过飞书发送给审批人，有效期 5 分钟。' : 'A verification code will be sent to the approver via Feishu. Valid for 5 minutes.'}
                            </p>
                          </div>
                        )}
                      </div>
                  </div>
                </div>

                {/* End grid */}
              <div className="lg:col-span-2 pt-4 border-t border-black/5 flex items-center justify-end gap-3">
                <button
                  type="button"
                  onClick={closeModal}
                  className="px-6 py-2.5 rounded-xl border border-slate-200 text-sm font-bold text-slate-600 hover:bg-slate-50 transition-all"
                >
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button
                  type="button"
                  onClick={submitForm}
                  disabled={!form.name.trim() || (!isEditMode && approvalStatus !== 'verified')}
                  className="px-8 py-2.5 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 text-white text-sm font-bold shadow-md hover:from-cyan-400 hover:to-blue-500 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isEditMode ? (zh ? '保存修改' : 'Save Changes') : (zh ? '确认创建' : 'Confirm Create')}
                </button>
              </div>
            </div>
          </motion.div>
          ) : (
            <motion.div
              key="list-view"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              className="space-y-4"
            >
{/* ═══ 顶层多维分类导航与搜索栏 ═══ */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 bg-slate-100/90 p-1.5 rounded-2xl border border-slate-200/80 shadow-inner">
        <div className="flex items-center gap-1 overflow-x-auto custom-scrollbar py-0.5">
          <button
            onClick={() => setActiveCategory('all')}
            className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-bold transition-all whitespace-nowrap shrink-0 ${
              activeCategory === 'all'
                ? 'bg-white text-cyan-700 shadow-sm border border-cyan-100'
                : 'text-slate-600 hover:text-slate-900 hover:bg-white/60'
            }`}
          >
            <span>{zh ? '全部作业' : 'All Jobs'}</span>
            <span className={`px-2 py-0.5 rounded-full text-[10px] ${activeCategory === 'all' ? 'bg-cyan-100 text-cyan-800 font-mono' : 'bg-slate-200/80 text-slate-600'}`}>
              {jobs.length + systemJobs.length}
            </span>
          </button>

          <button
            onClick={() => setActiveCategory('system')}
            className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-bold transition-all whitespace-nowrap shrink-0 ${
              activeCategory === 'system'
                ? 'bg-white text-slate-900 shadow-sm border border-slate-200'
                : 'text-slate-600 hover:text-slate-900 hover:bg-white/60'
            }`}
          >
            <Lock size={14} className={activeCategory === 'system' ? 'text-slate-800' : 'text-slate-400'} />
            <span>{zh ? '系统内置' : 'System Managed'}</span>
            <span className={`px-2 py-0.5 rounded-full text-[10px] ${activeCategory === 'system' ? 'bg-slate-200 text-slate-800 font-mono' : 'bg-slate-200/80 text-slate-600'}`}>
              {systemJobs.length}
            </span>
          </button>

          <button
            onClick={() => setActiveCategory('backup')}
            className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-bold transition-all whitespace-nowrap shrink-0 ${
              activeCategory === 'backup'
                ? 'bg-white text-indigo-700 shadow-sm border border-indigo-100'
                : 'text-slate-600 hover:text-slate-900 hover:bg-white/60'
            }`}
          >
            <Database size={14} className={activeCategory === 'backup' ? 'text-indigo-600' : 'text-slate-400'} />
            <span>{zh ? '配置自动备份' : 'Config Backup'}</span>
            <span className={`px-2 py-0.5 rounded-full text-[10px] ${activeCategory === 'backup' ? 'bg-indigo-100 text-indigo-800 font-mono' : 'bg-slate-200/80 text-slate-600'}`}>
              {stats.backupCnt}
            </span>
          </button>

          <button
            onClick={() => setActiveCategory('inspection')}
            className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-bold transition-all whitespace-nowrap shrink-0 ${
              activeCategory === 'inspection'
                ? 'bg-white text-emerald-700 shadow-sm border border-emerald-100'
                : 'text-slate-600 hover:text-slate-900 hover:bg-white/60'
            }`}
          >
            <Activity size={14} className={activeCategory === 'inspection' ? 'text-emerald-600' : 'text-slate-400'} />
            <span>{zh ? '智能巡检' : 'Smart Inspection'}</span>
            <span className={`px-2 py-0.5 rounded-full text-[10px] ${activeCategory === 'inspection' ? 'bg-emerald-100 text-emerald-800 font-mono' : 'bg-slate-200/80 text-slate-600'}`}>
              {stats.inspCnt}
            </span>
          </button>

          <button
            onClick={() => setActiveCategory('script_run')}
            className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-bold transition-all whitespace-nowrap shrink-0 ${
              activeCategory === 'script_run'
                ? 'bg-white text-amber-700 shadow-sm border border-amber-100'
                : 'text-slate-600 hover:text-slate-900 hover:bg-white/60'
            }`}
          >
            <Zap size={14} className={activeCategory === 'script_run' ? 'text-amber-600' : 'text-slate-400'} />
            <span>{zh ? '自动化脚本' : 'Automated Script'}</span>
            <span className={`px-2 py-0.5 rounded-full text-[10px] ${activeCategory === 'script_run' ? 'bg-amber-100 text-amber-800 font-mono' : 'bg-slate-200/80 text-slate-600'}`}>
              {stats.scriptCnt}
            </span>
          </button>
        </div>

        <div className="relative min-w-[260px] shrink-0">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder={zh ? '检索作业名称、命令或 IP 范围...' : 'Search jobs, commands, IP scope...'}
            className="w-full h-9 pl-9 pr-8 bg-white/90 border border-slate-200/80 rounded-xl text-xs text-slate-800 placeholder:text-slate-400 focus:outline-none focus:border-cyan-500 focus:bg-white shadow-sm transition-all"
          />
          {searchQuery && (
            <button onClick={() => setSearchQuery('')} className="absolute right-2.5 top-1/2 -translate-y-1/2 p-1 text-slate-400 hover:text-slate-600">
              <X size={14} />
            </button>
          )}
        </div>
      </div>

      {/* ═══ 系统内置作业守护进程 (表格形式，与系统明亮底色完美统一) ═══ */}
      {(activeCategory === 'all' || activeCategory === 'system') && filteredSystemJobs.length > 0 && (
        <div className="rounded-2xl border border-slate-200/80 bg-white shadow-sm overflow-hidden mb-6 transition-all">
          <div className="px-5 py-3.5 border-b border-slate-100 bg-slate-50/70 flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-lg bg-cyan-100 text-cyan-700 flex items-center justify-center font-bold">
                <Lock size={14} />
              </div>
              <h3 className="text-xs font-bold text-slate-800 flex items-center gap-2">
                {zh ? '平台内置常驻系统守护进程' : 'Platform Managed System Daemons'}
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-cyan-50 text-cyan-700 border border-cyan-100 font-normal tracking-normal">
                  {zh ? '内核自动调度，无需人工审批' : 'Kernel Managed'}
                </span>
              </h3>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-xs font-mono font-bold text-slate-600 bg-white px-2.5 py-1 rounded-lg border border-slate-200/80 shadow-2xs">
                {filteredSystemJobs.length} {zh ? '个常驻任务' : 'Daemons'}
              </span>
              {activeCategory === 'all' && (
                <button
                  onClick={() => setSystemCollapsed(c => !c)}
                  className="p-1 rounded-lg bg-slate-200/60 text-slate-600 hover:bg-slate-200 hover:text-slate-900 transition-all flex items-center gap-1 text-xs px-2.5 py-1"
                >
                  <span>{systemCollapsed ? (zh ? '展开列表' : 'Expand') : (zh ? '收起面板' : 'Collapse')}</span>
                  {systemCollapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
                </button>
              )}
            </div>
          </div>

          {(!systemCollapsed || activeCategory === 'system') && (
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-slate-100 text-[11px] font-bold text-slate-400 bg-slate-50/40 uppercase tracking-wider">
                    <th className="py-2.5 px-4">{zh ? '任务名称 / 标识' : 'Job Name / ID'}</th>
                    <th className="py-2.5 px-4">{zh ? '任务说明' : 'Description'}</th>
                    <th className="py-2.5 px-4">{zh ? '触发发条 (CRON)' : 'Trigger'}</th>
                    <th className="py-2.5 px-4">{zh ? '预计下次执行' : 'Next Run'}</th>
                    <th className="py-2.5 px-4 text-right">{zh ? '规则配置管理' : 'Management'}</th>
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
                              <code className="text-[10px] text-slate-400 font-mono">{sj.id}</code>
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
                        <td className="py-3 px-4 text-right">
                          {sj.deep_link ? (
                            <button
                              onClick={() => navigate(sj.deep_link!)}
                              className={`inline-flex items-center gap-1 text-[11px] font-bold px-2.5 py-1 rounded-lg border transition-all ${
                                isInsp ? 'bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100' :
                                isBackup ? 'bg-indigo-50 text-indigo-700 border-indigo-200 hover:bg-indigo-100' :
                                'bg-cyan-50 text-cyan-700 border-cyan-200 hover:bg-cyan-100'
                              }`}
                            >
                              <span>{zh ? '配置规则' : 'Configure'}</span>
                              <ArrowUpRight size={12} />
                            </button>
                          ) : (
                            <span className="text-[11px] text-slate-400 italic">{zh ? '内核保护' : 'Kernel Protected'}</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
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
              {activeCategory === 'inspection' && (zh ? '智能巡检作业' : 'Smart Inspection Jobs')}
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
        <div className="flex-1 overflow-y-auto max-h-[calc(100vh-320px)] custom-scrollbar">
          <div className="space-y-2.5">
            {filteredJobs.map(job => {
              const atInfo = ACTION_TYPES.find(a => a.value === job.action_type);
              const AtIcon = atInfo?.icon || Database;
              const isEnabled = !!job.enabled;
              const scopeDesc = describeScope(job.device_scope, job.device_filter, zh);
              const isInsp = job.action_type === 'inspection';
              const isBackup = job.action_type === 'backup';
              const isScript = job.action_type === 'script_run';
              return (
                <motion.div
                  key={job.id}
                  layout
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  onClick={() => setDetailJob(job)}
                  className={`rounded-2xl border transition-all hover:shadow-md cursor-pointer group overflow-hidden ${
                    isEnabled ? 'bg-white border-slate-200/90 shadow-sm' : 'bg-slate-50 border-slate-200/50 opacity-60'
                  }`}
                >
                  <div className="flex items-center gap-4 px-5 py-4">
                    {/* 分类定制色彩底座 Icon */}
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
                          {job.name}
                        </p>
                        <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
                          isEnabled ? 'bg-emerald-100/80 text-emerald-700 border border-emerald-200' : 'bg-slate-100 text-slate-500 border border-slate-200'
                        }`}>
                          {isEnabled ? (zh ? '运行中' : 'Active') : (zh ? '已停用' : 'Disabled')}
                        </span>
                        {job.last_run_status && (
                          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
                            job.last_run_status === 'success'
                              ? 'bg-emerald-50 text-emerald-600 border border-emerald-100'
                              : 'bg-rose-50 text-rose-600 border border-rose-100'
                          }`}>
                            <div className={`w-1.5 h-1.5 rounded-full ${job.last_run_status === 'success' ? 'bg-emerald-500' : 'bg-rose-500'}`} />
                            {job.last_run_status === 'success' ? (zh ? '执行成功' : 'Success') : (zh ? '执行失败' : 'Failed')}
                          </span>
                        )}
                        {job.use_admin_creds ? (
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
                          {describeCron(job.cron_expr, zh)}
                        </span>
                        <span className="text-slate-300">·</span>
                        <span className={`font-semibold ${isInsp ? 'text-emerald-700' : isBackup ? 'select-none text-indigo-700' : isScript ? 'text-amber-700' : 'text-slate-700'}`}>
                          {zh ? (atInfo?.labelZh || job.action_type) : (atInfo?.labelEn || job.action_type)}
                        </span>
                        <span className="text-slate-300">·</span>
                        <span className="flex items-center gap-1 text-slate-600 font-medium">
                          <Target size={12} className="text-slate-400" />
                          {scopeDesc}
                        </span>

                        {job.action_type === 'script_run' && job.script_id && (
                          <>
                            <span className="text-slate-300">·</span>
                            <span className="flex items-center gap-1 text-[#00a9ce] font-bold bg-cyan-50 px-2 py-0.5 rounded border border-cyan-100">
                              <FileCode size={12} />
                              {(availableScripts || []).find(s => s.id === job.script_id)?.name || job.script_id}
                            </span>
                          </>
                        )}
                        {job.run_count > 0 && (
                          <>
                            <span className="text-slate-300">·</span>
                            <span className="font-mono text-slate-600">{zh ? `累计触发 ${job.run_count} 次` : `${job.run_count} runs`}</span>
                          </>
                        )}
                        {job.last_run_at && (
                          <>
                            <span className="text-slate-300">·</span>
                            <span>{zh ? '最近运行' : 'Last run'}: <span className="font-mono">{new Date(job.last_run_at).toLocaleString(zh ? 'zh-CN' : 'en-US', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}</span></span>
                          </>
                        )}
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-1 shrink-0" onClick={e => e.stopPropagation()}>
                      <button
                        onClick={() => setDetailJob(job)}
                        className="p-2 rounded-xl text-slate-400 hover:bg-cyan-50 hover:text-cyan-600 transition-all opacity-0 group-hover:opacity-100"
                        title={zh ? '查看运行详情' : 'View Detail'}
                      >
                        <Eye size={16} />
                      </button>
                      <button
                        onClick={() => openEditModal(job)}
                        className="p-2 rounded-xl text-slate-400 hover:bg-cyan-50 hover:text-cyan-600 transition-all"
                        title={zh ? '编辑配置' : 'Edit'}
                      >
                        <Pencil size={16} />
                      </button>
                      <button
                        onClick={() => toggleJobEnabled(job)}
                        className={`p-2 rounded-xl transition-all ${isEnabled ? 'text-slate-400 hover:bg-amber-50 hover:text-amber-600' : 'text-slate-400 hover:bg-emerald-50 hover:text-emerald-600'}`}
                        title={isEnabled ? (zh ? '暂停执行' : 'Disable') : (zh ? '恢复启动' : 'Enable')}
                      >
                        {isEnabled ? <PowerOff size={16} /> : <Power size={16} />}
                      </button>
                      {deleteConfirmId === job.id ? (
                        <div className="flex items-center gap-1.5 ml-1">
                          <button
                            onClick={() => {
                              setDeleteConfirmId(null);
                              setDeleteTarget(job);
                              setDeleteReason(`${zh ? '申请删除作业' : 'Delete job'}: ${job.name}`);
                              setDeleteApprover('');
                              setDeleteToken('');
                              setDeleteCode('');
                              setDeleteStatus('idle');
                              setDeleteCountdown(0);
                              setDeleteError('');
                              fetchApprovers();
                              setDeleteApprovalOpen(true);
                            }}
                            className="px-2.5 py-1.5 rounded-xl bg-rose-600 text-white text-xs font-bold hover:bg-rose-700 transition-all shadow-sm"
                          >
                            {zh ? '确认删除' : 'Yes'}
                          </button>
                          <button
                            onClick={() => setDeleteConfirmId(null)}
                            className="px-2.5 py-1.5 rounded-xl border border-slate-200 text-xs font-semibold text-slate-600 hover:bg-slate-100 transition-all"
                          >
                            {zh ? '取消' : 'No'}
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => setDeleteConfirmId(job.id)}
                          className="p-2 rounded-xl text-slate-400 hover:bg-rose-50 hover:text-rose-600 transition-all"
                          title={zh ? '删除作业' : 'Delete'}
                        >
                          <Trash2 size={16} />
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Bottom meta */}
                  <div className="px-5 py-2.5 bg-slate-50/80 border-t border-slate-100 flex items-center gap-4 text-[11px] text-slate-500">
                    <span className="font-mono text-slate-600 font-semibold">{job.cron_expr}</span>
                    <span className="text-slate-300">|</span>
                    <span>{zh ? '审批授权人' : 'Approver'}: <span className="font-bold text-slate-700">{job.approved_by || '\u2014'}</span></span>
                    <span className="text-slate-300">|</span>
                    <span>{zh ? '创建者' : 'Creator'}: <span className="font-medium text-slate-700">{job.created_by}</span> · <span className="font-mono">{new Date(job.created_at).toLocaleDateString(zh ? 'zh-CN' : 'en-US')}</span></span>
                  </div>
                </motion.div>
              );
            })}
          </div>
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
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-cyan-500 to-cyan-600 text-white text-xs font-bold hover:from-cyan-400 hover:to-cyan-500 transition-all shadow shadow-cyan-500/20 active:scale-[0.98]"
          >
            <Plus size={16} />
            {zh ? '新建定时作业' : 'New Scheduled Job'}
          </button>
        </div>
      )}

      {total > 0 && (
        <div className="mt-auto pt-4 border-t border-black/5 bg-white">
          <Pagination currentPage={page} totalItems={total} itemsPerPage={pageSize} onPageChange={setPage} onItemsPerPageChange={setPageSize} language={language} />
        </div>
      )}

      {/* --- Detail Modal --- */}
      <AnimatePresence>
        {detailJob && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-[60] flex items-center justify-center p-4"
          >
            <div className="fixed inset-0 bg-black/40 backdrop-blur-md" onClick={() => setDetailJob(null)} />
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
              className="relative w-full max-w-2xl max-h-[85vh] bg-white rounded-3xl shadow-2xl flex flex-col overflow-hidden border border-black/5"
            >
              {/* Header */}
              <div className="px-6 py-5 border-b border-black/[0.03] flex items-center justify-between bg-gradient-to-r from-slate-50/50 to-white">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-2xl bg-cyan-500/10 flex items-center justify-center">
                    <Info className="w-5 h-5 text-cyan-600" />
                  </div>
                  <div>
                    <h3 className="text-base font-bold text-[#164e63]">{detailJob.name}</h3>
                    <div className="flex items-center gap-2 text-[10px] text-black/40 mt-0.5">
                      <span className="bg-slate-100 px-1.5 py-0.5 rounded font-mono">{detailJob.id}</span>
                      <span>·</span>
                      <span>{zh ? '定时作业详情' : 'Scheduled Job Detail'}</span>
                    </div>
                  </div>
                </div>
                <button
                  onClick={() => setDetailJob(null)}
                  className="p-2 rounded-xl text-black/20 hover:bg-black/5 hover:text-black/40 transition-all"
                >
                  <X size={20} />
                </button>
              </div>

              {/* Content */}
              <div className="flex-1 overflow-y-auto p-6 space-y-6 custom-scrollbar">
                {/* 1. Schedule & Scope Grid */}
                <div className="grid grid-cols-2 gap-4">
                  <div className="p-4 rounded-2xl bg-slate-50/50 border border-black/[0.02]">
                    <div className="flex items-center gap-2 text-[11px] font-bold text-black/40 mb-2 uppercase tracking-wider">
                      <CalendarClock size={12} />
                      {zh ? '执行周期' : 'Schedule'}
                    </div>
                    <p className="text-sm font-semibold text-[#0e7490]">
                      {describeCron(detailJob.cron_expr, zh)}
                    </p>
                    <p className="text-[10px] font-mono text-black/30 mt-1">{detailJob.cron_expr}</p>
                  </div>
                  <div className="p-4 rounded-2xl bg-slate-50/50 border border-black/[0.02]">
                    <div className="flex items-center gap-2 text-[11px] font-bold text-black/40 mb-2 uppercase tracking-wider">
                      <Target size={12} />
                      {zh ? '执行范围' : 'Target Scope'}
                    </div>
                    <p className="text-sm font-semibold text-slate-700">
                      {detailJob.device_scope === 'all' ? (zh ? '全部在线设备' : 'All Online Devices') :
                       detailJob.device_scope === 'ip' ? (zh ? '按 IP 指定' : 'By IP Address') :
                       detailJob.device_scope === 'tag' ? (zh ? '按标签筛选' : 'By Tags') : (zh ? '自定义范围' : 'Custom')}
                    </p>
                    <p className="text-[10px] text-black/40 mt-1 truncate">
                      {detailJob.device_filter || (zh ? '无额外过滤条件' : 'No filter')}
                    </p>
                  </div>
                </div>

                {/* 2. Device List (IP List) */}
                {(detailJob.device_scope === 'ip' || detailJob.device_scope === 'all') && (
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <h4 className="text-[11px] font-bold text-black/50 uppercase tracking-wider">{zh ? '执行 IP 列表' : 'Target IPs'}</h4>
                      <span className="text-[10px] text-black/30">
                        {detailJob.device_scope === 'all' ? (zh ? '动态获取' : 'Dynamic') : `${(detailJob.device_filter || '').split(',').length} 个目标`}
                      </span>
                    </div>
                    <div className="p-3 rounded-2xl border border-black/[0.04] bg-slate-50/30">
                      <div className="flex flex-wrap gap-1.5">
                        {detailJob.device_scope === 'all' ? (
                          <div className="text-[11px] text-black/40 italic px-2 py-1">{zh ? '作业运行时将自动扫描所有在线设备' : 'Automatically targets all online devices at runtime'}</div>
                        ) : (
                          (detailJob.device_filter || '').split(',').map((ip, idx) => (
                            <span key={idx} className="inline-flex items-center px-2 py-0.5 rounded-md bg-white border border-black/[0.06] text-[11px] font-mono text-slate-600 shadow-sm">
                              {ip.trim()}
                            </span>
                          ))
                        )}
                      </div>
                    </div>
                  </div>
                )}

                {/* 3. Execution Content (Script/Commands) */}
                <div>
                  <h4 className="text-[11px] font-bold text-black/50 uppercase tracking-wider mb-2">{zh ? '执行脚本/内容' : 'Execution Content'}</h4>
                  <div className="rounded-2xl border border-black/[0.06] overflow-hidden bg-[#1e293b]">
                    <div className="px-4 py-2 bg-white/5 border-b border-white/[0.05] flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <FileText size={12} className="text-cyan-400" />
                        <span className="text-[11px] font-bold text-white/70">
                          {detailJob.action_type === 'backup' ? (zh ? '采集与巡检：核心配置备份' : 'Collection & Inspection: Config Backup') :
                           (availableScripts.find(s => s.id === detailJob.script_id)?.name || detailJob.script_id || (zh ? '操作内容' : 'Operation Content'))}
                        </span>
                        {detailJob.script_id && (
                          <button 
                            onClick={() => fetchAndShowScriptDetail(detailJob.script_id!)}
                            className="text-[9px] bg-cyan-500/10 text-cyan-400 px-1.5 py-0.5 rounded border border-cyan-500/20 hover:bg-cyan-500/20 transition-all ml-1"
                          >
                            {zh ? '查看脚本详情' : 'View Script'}
                          </button>
                        )}
                      </div>
                      <div className="text-[9px] font-bold text-cyan-400/60 uppercase tracking-widest">
                        {detailJob.action_type === 'backup' ? (zh ? '采集' : 'BACKUP') : 
                         detailJob.major_type === 'collection' ? (zh ? '巡检' : 'INSPECTION') : (zh ? '变更' : 'CHANGE')}
                      </div>
                    </div>
                    <div className="p-4 overflow-x-auto">
                      <pre className="font-mono text-[11px] leading-relaxed text-cyan-50/90 whitespace-pre-wrap">
                        {detailJob.action_type === 'backup'
                          ? (zh ? '# 该作业为内置配置备份任务\n# 将自动采集设备 running-config 并进行版本比对' : '# This is a built-in config backup job.\n# It will collect running-config and track drifts.')
                          : detailJob.action_type === 'inspection'
                            ? (zh ? '# 该作业为内置综合巡检\n# 将采集 interfaces / neighbors / arp / mac_table / routing_table / bgp / ospf' : '# Built-in comprehensive inspection job.\n# Collects interfaces / neighbors / arp / mac_table / routing_table / bgp / ospf')
                            : detailJob.script_id && viewingScript?.id === detailJob.script_id && viewingScript?.content
                              ? viewingScript.content
                              : detailJob.commands
                                ? detailJob.commands
                                : detailJob.script_id
                                  ? (zh ? `# 此作业绑定脚本: ${availableScripts.find(s => s.id === detailJob.script_id)?.name || detailJob.script_id}\n# 点击上方"查看脚本详情"查看完整内容` : `# Bound script: ${availableScripts.find(s => s.id === detailJob.script_id)?.name || detailJob.script_id}\n# Click "View Script" above to see full content`)
                                  : (zh ? '-- 未设置具体执行内容 --' : '-- No commands defined --')}
                      </pre>
                    </div>
                  </div>
                </div>

                {/* 4. Meta Info */}
                <div className="pt-4 border-t border-black/[0.03] grid grid-cols-2 gap-y-4 text-[10px]">
                  <div>
                    <p className="text-black/30 mb-1">{zh ? '状态' : 'Status'}</p>
                    <span className={`px-2 py-0.5 rounded-full font-bold ${detailJob.enabled ? 'bg-emerald-50 text-emerald-600' : 'bg-slate-100 text-slate-500'}`}>
                      {detailJob.enabled ? (zh ? '已启用' : 'Active') : (zh ? '已停用' : 'Disabled')}
                    </span>
                  </div>
                  <div>
                    <p className="text-black/30 mb-1">{zh ? '配置原因' : 'Reason'}</p>
                    <p className="text-slate-600 font-medium italic truncate">{detailJob.config_reason || '\u2014'}</p>
                  </div>
                  <div>
                    <p className="text-black/30 mb-1">{zh ? '审批人' : 'Approver'}</p>
                    <p className="text-slate-600 font-bold">{detailJob.approved_by || (zh ? '系统自核' : 'Auto')}</p>
                  </div>
                  <div>
                    <p className="text-black/30 mb-1">{zh ? '创建者' : 'Creator'}</p>
                    <p className="text-slate-600 font-bold">{detailJob.created_by} · {new Date(detailJob.created_at).toLocaleDateString()}</p>
                  </div>
                </div>
              </div>

              {/* Footer */}
              <div className="px-6 py-4 bg-slate-50/80 border-t border-black/[0.03] flex items-center justify-end gap-3">
                <button
                  onClick={() => setDetailJob(null)}
                  className="px-6 py-2 rounded-xl border border-black/10 text-xs font-bold text-black/50 hover:bg-black/5 transition-all"
                >
                  {zh ? '关闭' : 'Close'}
                </button>
                <button
                  onClick={() => {
                    const job = detailJob;
                    setDetailJob(null);
                    openEditModal(job);
                  }}
                  className="px-6 py-2 rounded-xl bg-[#164e63] text-white text-xs font-bold shadow-lg shadow-cyan-900/10 hover:bg-[#0891b2] transition-all"
                >
                  {zh ? '编辑该作业' : 'Edit Job'}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* --- Delete Approval Modal --- */}
      <AnimatePresence>
        {deleteApprovalOpen && deleteTarget && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
          >
            <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setDeleteApprovalOpen(false)} />
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 10 }}
              className="relative w-full max-w-md rounded-2xl bg-white border border-slate-100 shadow-2xl overflow-hidden z-10"
              onClick={e => e.stopPropagation()}
            >
              <div className="bg-rose-50 border-b border-rose-100 px-6 py-4 flex items-center justify-between">
                <div className="flex items-center gap-2.5 text-rose-700">
                  <Shield className="w-5 h-5 text-rose-600" />
                  <h3 className="font-bold text-sm">{zh ? '删除安全校验与工单授权' : 'Delete Security Verification'}</h3>
                </div>
                <button onClick={() => setDeleteApprovalOpen(false)} className="text-rose-400 hover:text-rose-600 p-1">
                  <X size={16} />
                </button>
              </div>

              <div className="p-6 space-y-4 text-xs text-slate-600">
                <div className="bg-slate-50 p-3 rounded-xl border border-slate-100 space-y-1">
                  <span className="text-[10px] text-slate-400 font-semibold">{zh ? '即将永久删除作业' : 'Target Job to Delete'}</span>
                  <div className="font-bold text-slate-800 text-sm truncate">{deleteTarget.name}</div>
                  <div className="font-mono text-[10px] text-slate-500">{deleteTarget.cron_expr} · {deleteTarget.action_type}</div>
                </div>

                <div className="space-y-1.5">
                  <label className="font-bold text-slate-700 block">{zh ? '删除原因说明' : 'Deletion Reason'}</label>
                  <input
                    type="text" value={deleteReason} onChange={e => setDeleteReason(e.target.value)}
                    placeholder={zh ? '输入删除原因...' : 'Enter reason...'}
                    className="w-full px-3 py-2 rounded-xl border border-slate-200 bg-white outline-none focus:border-rose-500 transition-all"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="font-bold text-slate-700 block">{zh ? '选择授权审批人' : 'Select Approver'}</label>
                  <div className="flex items-center gap-2">
                    <select
                      value={deleteApprover} onChange={e => setDeleteApprover(e.target.value)}
                      disabled={deleteStatus === 'sending' || deleteStatus === 'sent'}
                      className="flex-1 px-3 py-2 rounded-xl border border-slate-200 bg-white outline-none focus:border-rose-500 transition-all"
                    >
                      <option value="">{zh ? '选择审批人...' : 'Select approver...'}</option>
                      {approvers.map(u => (
                        <option key={u.id} value={u.username}>{u.username} ({u.role})</option>
                      ))}
                    </select>
                    <button
                      type="button" onClick={requestDeleteApproval}
                      disabled={!deleteApprover || !deleteReason.trim() || deleteStatus === 'sending' || (deleteStatus === 'sent' && deleteCountdown > 0)}
                      className={`px-3 py-2 rounded-xl font-bold whitespace-nowrap transition-all flex items-center gap-1 ${
                        deleteApprover && deleteReason.trim() && !(deleteStatus === 'sent' && deleteCountdown > 0)
                          ? 'bg-rose-600 text-white hover:bg-rose-700 shadow-sm'
                          : 'bg-slate-100 text-slate-400 cursor-not-allowed'
                      }`}
                    >
                      {deleteStatus === 'sending' ? <RotateCcw className="w-3 h-3 animate-spin" />
                        : deleteStatus === 'sent' && deleteCountdown > 0 ? `${Math.floor(deleteCountdown / 60)}:${String(deleteCountdown % 60).padStart(2, '0')}`
                        : (zh ? '发验证码' : 'Send Code')}
                    </button>
                  </div>
                </div>

                {deleteStatus === 'sent' && (
                  <div className="space-y-1.5 pt-2 border-t border-slate-100">
                    <label className="text-[11px] text-slate-500 block">{zh ? '输入 6 位工单验证码' : 'Enter 6-digit verification code'}</label>
                    <div className="flex items-center gap-2">
                      <input
                        value={deleteCode} onChange={e => { setDeleteCode(e.target.value.replace(/\D/g, '').slice(0, 6)); setDeleteError(''); }}
                        placeholder="000000" maxLength={6}
                        className="w-32 tracking-[0.3em] text-center font-mono rounded-xl border border-slate-200 py-2 text-sm outline-none focus:border-rose-500 transition-all"
                      />
                      <button
                        type="button" onClick={verifyDeleteApproval} disabled={deleteCode.length !== 6}
                        className={`px-4 py-2 rounded-xl font-bold transition-all ${deleteCode.length === 6 ? 'bg-emerald-600 text-white hover:bg-emerald-700' : 'bg-slate-100 text-slate-400 cursor-not-allowed'}`}
                      >
                        {zh ? '验证' : 'Verify'}
                      </button>
                    </div>
                  </div>
                )}

                {deleteError && (
                  <div className="flex items-center gap-1.5 text-rose-600 text-xs pt-1">
                    <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                    <span>{deleteError}</span>
                  </div>
                )}
              </div>

              <div className="px-6 py-4 bg-slate-50/80 border-t border-slate-100 flex items-center justify-end gap-2">
                <button
                  type="button" onClick={() => setDeleteApprovalOpen(false)}
                  className="px-4 py-2 rounded-xl border border-slate-200 font-semibold text-slate-600 hover:bg-slate-100 transition-all"
                >
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button
                  type="button" onClick={executeDeleteJob} disabled={deleteStatus !== 'verified'}
                  className="px-4 py-2 rounded-xl bg-rose-600 text-white font-bold hover:bg-rose-700 disabled:opacity-40 disabled:cursor-not-allowed transition-all shadow-md shadow-rose-600/10"
                >
                  {zh ? '确认安全删除' : 'Secure Delete'}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

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

      {/* --- Script Preview Modal --- */}
      <AnimatePresence>
        {viewingScript && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-[70] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.9, y: 30 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.9, y: 30 }}
              className="relative w-full max-w-4xl max-h-[85vh] bg-[#0f172a] rounded-3xl shadow-2xl flex flex-col overflow-hidden border border-white/10"
            >
              <div className="px-6 py-4 border-b border-white/5 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-lg bg-cyan-500/20 flex items-center justify-center">
                    <FileCode className="w-4 h-4 text-cyan-400" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-white/90">{viewingScript.name}</h3>
                    <p className="text-[10px] text-white/40">{viewingScript.id} · {viewingScript.category === 'inspection' ? (zh ? '巡检脚本' : 'Inspection') : (zh ? '变更脚本' : 'Change')}</p>
                  </div>
                </div>
                <button
                  onClick={() => setViewingScript(null)}
                  className="p-2 rounded-lg text-white/20 hover:bg-white/5 hover:text-white/40 transition-all"
                >
                  <X size={18} />
                </button>
              </div>
              <div className="flex-1 overflow-y-auto p-6 space-y-4 custom-scrollbar">
                 {viewingScript.description && (
                   <div className="p-4 rounded-xl bg-white/5 border border-white/5">
                     <p className="text-[11px] text-white/60 leading-relaxed italic">
                       {viewingScript.description}
                     </p>
                   </div>
                 )}
                 <div className="relative group">
                   <pre className="p-5 rounded-2xl bg-black/50 border border-white/10 font-mono text-[11px] leading-relaxed text-cyan-50/80 overflow-x-auto">
                     {viewingScript.content}
                   </pre>
                 </div>
              </div>
              <div className="px-6 py-4 bg-white/[0.02] border-t border-white/5 flex items-center justify-end">
                <button
                  onClick={() => setViewingScript(null)}
                  className="px-6 py-2 rounded-xl bg-white/5 text-white/60 text-xs font-bold hover:bg-white/10 transition-all"
                >
                  {zh ? '返回详情' : 'Back'}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
          </motion.div>
        )}
      </AnimatePresence>
      </div>
    </div>
  );
};

export default ScheduledJobsTab;
