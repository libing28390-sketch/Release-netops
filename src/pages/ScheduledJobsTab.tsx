import React, { useEffect, useState, useCallback, useMemo } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  CalendarClock, Plus, X, Trash2, RotateCcw, Zap, Pencil,
  ChevronDown, Info, Shield, CheckCircle2, AlertTriangle,
  Database, Activity, Power, PowerOff,
} from 'lucide-react';
import Pagination from '../components/Pagination';
import TagConditionPicker, { type TagFilterConfig, EMPTY_TAG_FILTER, serializeTagFilter, parseTagFilter } from '../components/TagConditionPicker';

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
  { value: 'backup', labelZh: '配置备份', labelEn: 'Config Backup', icon: Database },
  { value: 'inspection', labelZh: '设备巡检', labelEn: 'Device Inspection', icon: Activity },
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
  created_by: string;
  created_at: string;
}

interface EligibleApprover {
  id: string;
  username: string;
  role: string;
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
  is_config: boolean;
  config_reason: string;
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
  is_config: false,
  config_reason: '',
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

  /* === STATE === */
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [total, setTotal] = useState(0);

  // Modal
  const [modalOpen, setModalOpen] = useState(false);
  const [editingJob, setEditingJob] = useState<ScheduledJob | null>(null);
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

  // Approval (create only)
  const [approvers, setApprovers] = useState<EligibleApprover[]>([]);
  const [approverUsername, setApproverUsername] = useState('');
  const [approvalToken, setApprovalToken] = useState('');
  const [approvalCode, setApprovalCode] = useState('');
  const [approvalStatus, setApprovalStatus] = useState<'idle' | 'sending' | 'sent' | 'verified'>('idle');
  const [approvalCountdown, setApprovalCountdown] = useState(0);
  const [approvalError, setApprovalError] = useState('');

  const isEditMode = editingJob !== null;

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

  useEffect(() => { fetchJobs(); }, [fetchJobs]);
  useEffect(() => { if (modalOpen && !isEditMode) fetchApprovers(); }, [modalOpen, isEditMode, fetchApprovers]);

  useEffect(() => {
    if (approvalCountdown <= 0) return;
    const t = setTimeout(() => setApprovalCountdown(c => c - 1), 1000);
    return () => clearTimeout(t);
  }, [approvalCountdown]);

  /* === MODAL HELPERS === */
  const resetFormState = () => {
    setForm({ ...INITIAL_FORM });
    setTagFilter({ ...EMPTY_TAG_FILTER });
    setIpDevices([]);
    setIpInput('');
    setApproverUsername('');
    setApprovalToken('');
    setApprovalCode('');
    setApprovalStatus('idle');
    setApprovalCountdown(0);
    setApprovalError('');
  };

  const openCreateModal = () => {
    resetFormState();
    setEditingJob(null);
    setModalOpen(true);
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
      is_config: !!job.is_config,
      config_reason: job.config_reason || '',
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
    setModalOpen(true);
  };

  const closeModal = () => {
    setModalOpen(false);
    setEditingJob(null);
    setPresetOpen(false);
  };

  /* === APPROVAL (create only) === */
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
          config_reason: form.config_reason || `${zh ? '创建定时作业' : 'Create scheduled job'}: ${form.name}`,
          device_hostname: form.device_scope === 'all' ? (zh ? '全部设备' : 'All devices') : form.device_filter,
          command_preview: '',
          approval_type: 'scheduled_job',
          extra_fields: {
            action_type: zh ? (actionLabel?.labelZh || form.action_type) : (actionLabel?.labelEn || form.action_type),
            schedule_desc: describeCron(form.cron_expr, zh),
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

  /* === IP validation (supports multiple IPs, allows non-inventory) === */
  const validateAndAddIps = async (raw: string) => {
    const ips = raw.split(/[,;\s]+/).map(s => s.trim()).filter(Boolean);
    if (ips.length === 0) return;
    setIpError('');
    setIpValidating(true);
    const notFound: string[] = [];
    const duplicates: string[] = [];
    try {
      for (const ip of ips) {
        if (ipDevices.some(d => d.ip === ip)) { duplicates.push(ip); continue; }
        try {
          let found = false;
          // 1) Search devices table
          const r = await fetch(`/api/devices?search=${encodeURIComponent(ip)}&mode=light&page_size=50`, { headers: authHeaders });
          if (r.ok) {
            const j = await r.json();
            const items = j.data?.items || j.data || [];
            const device = items.find((d: { ip_address: string }) => d.ip_address === ip);
            if (device) {
              found = true;
              setIpDevices(prev => {
                if (prev.some(d => d.ip === device.ip_address)) return prev;
                return [...prev, {
                  ip: device.ip_address,
                  hostname: device.hostname || '',
                  tags: (device.tags || []).map((t: { id: string; label: string; label_zh: string; color: string }) => ({
                    id: t.id, label: t.label, label_zh: t.label_zh, color: t.color || '#94a3b8',
                  })),
                }];
              });
            }
          }
          // 2) Fallback: search physical_assets table
          if (!found) {
            try {
              const ar = await fetch(`/api/assets?q=${encodeURIComponent(ip)}&page_size=50`, { headers: authHeaders });
              if (ar.ok) {
                const aj = await ar.json();
                const assets = aj.data?.items || aj.data || [];
                const asset = assets.find((a: { management_ip?: string; business_ip?: string }) =>
                  a.management_ip === ip || a.business_ip === ip
                );
                if (asset) {
                  found = true;
                  setIpDevices(prev => {
                    if (prev.some(d => d.ip === ip)) return prev;
                    return [...prev, { ip, hostname: asset.hostname || '', tags: [] }];
                  });
                }
              }
            } catch { /* ignore asset fallback errors */ }
          }
          if (!found) {
            notFound.push(ip);
            setIpDevices(prev => {
              if (prev.some(d => d.ip === ip)) return prev;
              return [...prev, { ip, hostname: '', tags: [] }];
            });
          }
        } catch {
          notFound.push(ip);
          setIpDevices(prev => {
            if (prev.some(d => d.ip === ip)) return prev;
            return [...prev, { ip, hostname: '', tags: [] }];
          });
        }
      }
      setIpInput('');
      if (notFound.length > 0) {
        setIpError(zh ? `以下 IP 不存在于设备列表：${notFound.join(', ')}（已添加，执行时将尝试连接）` : `IP not in inventory: ${notFound.join(', ')} (added, will attempt connection at runtime)`);
      }
    } catch {
      setIpError(zh ? '查询设备失败' : 'Device lookup failed');
    } finally {
      setIpValidating(false);
    }
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
      showToast(zh ? '请先完成审批验证' : 'Please complete approval verification first', 'error');
      return;
    }
    try {
      const r = await fetch('/api/scheduled-jobs', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({
          ...form,
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
          config_reason: form.config_reason,
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
      showToast(zh ? '更新失败' : 'Update failed', 'error');
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
      try {
        const r = await fetch(`/api/scheduled-jobs/${job.id}/toggle`, {
          method: 'PUT',
          headers: authHeaders,
          body: JSON.stringify({ enabled: false }),
        });
        if (r.ok) {
          fetchJobs();
          showToast(zh ? '作业已停用' : 'Job disabled', 'success');
        }
      } catch { /* ignore */ }
      return;
    }
    showToast(zh ? '启用作业需要重新创建并通过审批' : 'Enabling a job requires re-creation with approval', 'info');
  };

  const submitForm = () => {
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
    <div className="h-full flex flex-col overflow-hidden space-y-4">
      {/* Page Header */}
      <div className="rounded-2xl border border-black/5 bg-white shadow-sm">
        <div className="flex items-center justify-between px-5 py-3">
          <div>
            <h2 className="text-lg font-semibold text-[#164e63]">{zh ? '定时作业' : 'Scheduled Jobs'}</h2>
            <p className="text-[11px] text-black/40">{zh ? '创建和管理周期性执行的自动化作业，需审批人验证码授权' : 'Create and manage periodic automation jobs with approver verification'}</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={fetchJobs}
              disabled={loading}
              className="inline-flex h-8 items-center gap-1 rounded-xl border border-black/8 bg-[#f8fafc] px-3 text-[11px] font-medium text-[#0e7490] transition-all hover:bg-white hover:border-cyan-400/30"
            >
              <RotateCcw size={12} className={loading ? 'animate-spin' : ''} />
              {zh ? '刷新' : 'Refresh'}
            </button>
            <button
              onClick={openCreateModal}
              className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-gradient-to-r from-cyan-500 to-cyan-600 text-white text-xs font-bold shadow-sm hover:from-cyan-400 hover:to-cyan-500 transition-all active:scale-[0.97]"
            >
              <Plus className="w-3.5 h-3.5" />
              {zh ? '新建定时作业' : 'New Scheduled Job'}
            </button>
          </div>
        </div>
      </div>

      {/* Job List */}
      {loading ? (
        <div className="flex items-center justify-center py-16 text-black/30">
          <RotateCcw size={14} className="animate-spin mr-2" />
          <span className="text-xs">{zh ? '加载中...' : 'Loading...'}</span>
        </div>
      ) : jobs.length > 0 ? (
        <div className="flex-1 overflow-y-auto max-h-[calc(100vh-320px)] custom-scrollbar">
          <div className="space-y-2">
            {jobs.map(job => {
              const atInfo = ACTION_TYPES.find(a => a.value === job.action_type);
              const AtIcon = atInfo?.icon || Database;
              const isEnabled = !!job.enabled;
              const scopeDesc = describeScope(job.device_scope, job.device_filter, zh);
              return (
                <motion.div
                  key={job.id}
                  layout
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  className={`rounded-2xl border bg-white shadow-sm transition-all hover:shadow-md ${isEnabled ? 'border-black/[0.06]' : 'border-black/[0.04] opacity-60'}`}
                >
                  <div className="flex items-center gap-4 px-5 py-3.5">
                    {/* Icon */}
                    <div className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0 ${isEnabled ? 'bg-gradient-to-br from-cyan-50 to-cyan-100/60' : 'bg-slate-50'}`}>
                      <AtIcon className={`w-[18px] h-[18px] ${isEnabled ? 'text-cyan-600' : 'text-slate-400'}`} />
                    </div>

                    {/* Main info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-bold text-[#164e63] truncate">{job.name}</p>
                        <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider ${isEnabled ? 'bg-emerald-50 text-emerald-600' : 'bg-slate-100 text-slate-400'}`}>
                          {isEnabled ? (zh ? '运行中' : 'Active') : (zh ? '已停用' : 'Disabled')}
                        </span>
                      </div>
                      <div className="flex items-center gap-3 mt-1 text-[11px] text-black/40 flex-wrap">
                        <span className="flex items-center gap-1">
                          <CalendarClock size={10} />
                          {describeCron(job.cron_expr, zh)}
                        </span>
                        <span className="text-black/10">·</span>
                        <span>{zh ? (atInfo?.labelZh || job.action_type) : (atInfo?.labelEn || job.action_type)}</span>
                        <span className="text-black/10">·</span>
                        <span>{scopeDesc}</span>
                        {job.run_count > 0 && (
                          <>
                            <span className="text-black/10">·</span>
                            <span>{zh ? `已执行 ${job.run_count} 次` : `${job.run_count} runs`}</span>
                          </>
                        )}
                        {job.last_run_at && (
                          <>
                            <span className="text-black/10">·</span>
                            <span>{zh ? '最近' : 'Last'}: {new Date(job.last_run_at).toLocaleString(zh ? 'zh-CN' : 'en-US', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>
                          </>
                        )}
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        onClick={() => openEditModal(job)}
                        className="p-2 rounded-lg text-black/25 hover:bg-cyan-50 hover:text-cyan-600 transition-all"
                        title={zh ? '编辑' : 'Edit'}
                      >
                        <Pencil size={14} />
                      </button>
                      <button
                        onClick={() => toggleJobEnabled(job)}
                        className={`p-2 rounded-lg transition-all ${isEnabled ? 'text-black/25 hover:bg-amber-50 hover:text-amber-600' : 'text-black/25 hover:bg-emerald-50 hover:text-emerald-600'}`}
                        title={isEnabled ? (zh ? '停用' : 'Disable') : (zh ? '启用' : 'Enable')}
                      >
                        {isEnabled ? <PowerOff size={14} /> : <Power size={14} />}
                      </button>
                      {deleteConfirmId === job.id ? (
                        <div className="flex items-center gap-1 ml-1">
                          <button
                            onClick={() => deleteJob(job.id)}
                            className="px-2 py-1 rounded-lg bg-red-500 text-white text-[10px] font-bold hover:bg-red-600 transition-all"
                          >
                            {zh ? '确认' : 'Yes'}
                          </button>
                          <button
                            onClick={() => setDeleteConfirmId(null)}
                            className="px-2 py-1 rounded-lg border border-black/10 text-[10px] font-semibold text-black/40 hover:bg-black/5 transition-all"
                          >
                            {zh ? '取消' : 'No'}
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => setDeleteConfirmId(job.id)}
                          className="p-2 rounded-lg text-black/20 hover:bg-red-50 hover:text-red-500 transition-all"
                          title={zh ? '删除' : 'Delete'}
                        >
                          <Trash2 size={14} />
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Bottom meta */}
                  <div className="px-5 py-2 border-t border-black/[0.03] flex items-center gap-4 text-[10px] text-black/25">
                    <span className="font-mono">{job.cron_expr}</span>
                    <span className="text-black/8">|</span>
                    <span>{zh ? '审批' : 'Approved'}: {job.approved_by || '\u2014'}</span>
                    <span className="text-black/8">|</span>
                    <span>{zh ? '创建' : 'Created'}: {job.created_by} · {new Date(job.created_at).toLocaleDateString(zh ? 'zh-CN' : 'en-US')}</span>
                  </div>
                </motion.div>
              );
            })}
          </div>
        </div>
      ) : (
        <div className="rounded-2xl border-2 border-dashed border-black/[0.06] p-16 text-center">
          <CalendarClock className="w-10 h-10 text-black/10 mx-auto mb-3" />
          <p className="text-sm text-black/35 font-medium">{zh ? '暂无定时作业' : 'No scheduled jobs'}</p>
          <p className="text-[11px] text-black/25 mt-1 mb-4">{zh ? '创建周期性自动化任务，如每日配置备份、定时巡检' : 'Create periodic tasks like daily config backup or scheduled inspection'}</p>
          <button
            onClick={openCreateModal}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-cyan-600 text-white text-xs font-bold hover:bg-cyan-700 transition-all shadow-sm"
          >
            <Plus size={13} />
            {zh ? '新建定时作业' : 'New Scheduled Job'}
          </button>
        </div>
      )}

      {total > 0 && (
        <div className="mt-auto pt-4 border-t border-black/5 bg-white">
          <Pagination currentPage={page} totalItems={total} itemsPerPage={pageSize} onPageChange={setPage} language={language} />
        </div>
      )}
      <AnimatePresence>
        {modalOpen && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-start justify-center pt-[6vh] px-4 overflow-y-auto"
          >
            {/* Backdrop */}
            <div className="fixed inset-0 bg-black/30 backdrop-blur-sm" onClick={closeModal} />

            {/* Panel */}
            <motion.div
              initial={{ opacity: 0, y: 24, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 16, scale: 0.98 }}
              transition={{ type: 'spring', damping: 28, stiffness: 350 }}
              className={`relative w-full rounded-2xl border border-black/8 bg-white shadow-2xl mb-8 ${form.device_scope === 'ip' || form.device_scope === 'tag' ? 'max-w-5xl' : 'max-w-3xl'}`}
              onClick={e => e.stopPropagation()}
            >
              {/* Header */}
              <div className="flex items-center justify-between px-6 py-4 border-b border-black/[0.06]">
                <h3 className="text-base font-bold text-[#164e63] flex items-center gap-2">
                  {isEditMode ? <Pencil size={16} className="text-cyan-500" /> : <Plus size={16} className="text-cyan-500" />}
                  {isEditMode ? (zh ? '编辑定时作业' : 'Edit Scheduled Job') : (zh ? '新建定时作业' : 'New Scheduled Job')}
                </h3>
                <button onClick={closeModal} className="p-1.5 rounded-lg text-black/30 hover:bg-black/5 transition-all">
                  <X size={16} />
                </button>
              </div>

              {/* Body */}
              <div className="px-6 py-5 space-y-5 max-h-[70vh] overflow-y-auto">
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
                        {ACTION_TYPES.map(at => (
                          <button
                            key={at.value} type="button"
                            onClick={() => setForm(f => ({ ...f, action_type: at.value }))}
                            className={`flex items-center gap-2 px-3 py-2.5 rounded-xl border text-xs font-semibold transition-all ${
                              form.action_type === at.value
                                ? 'border-cyan-400 bg-cyan-50 text-[#0891b2]'
                                : 'border-black/[0.06] bg-white text-black/50 hover:border-black/15'
                            }`}
                          >
                            <at.icon className="w-3.5 h-3.5" />
                            {zh ? at.labelZh : at.labelEn}
                          </button>
                        ))}
                      </div>
                    </div>

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

                    {/* IP input with validation — rendered outside grid below for full width */}

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

                    {/* Tag picker — rendered outside grid below for full width */}
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

                    {/* Approval (create only) */}
                    {!isEditMode && (
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
                    )}
                  </div>
                </div>

                {/* IP input — full width below grid */}
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
                        className="w-full px-3.5 py-2.5 rounded-xl border border-black/[0.08] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all font-mono pr-10"
                        placeholder={zh ? '输入 IP 地址后按回车验证，支持逗号/空格/分号分隔多个 IP' : 'Enter IPs separated by comma/space/semicolon, press Enter to validate'}
                      />
                      {ipValidating && (
                        <RotateCcw size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-cyan-500 animate-spin" />
                      )}
                    </div>

                    {ipError && (
                      <p className={`text-[10px] mt-1 ${ipError.includes('已添加') || ipError.includes('added') ? 'text-amber-500' : 'text-red-500'}`}>{ipError}</p>
                    )}

                    {ipDevices.length > 0 && (
                      <div className="mt-2 space-y-1">
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
                                {dev.tags.slice(0, 4).map(tag => (
                                  <span
                                    key={tag.id}
                                    className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-medium bg-white border border-black/[0.06] shrink-0"
                                  >
                                    <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: tag.color }} />
                                    <span className="truncate">{zh ? (tag.label_zh || tag.label) : tag.label}</span>
                                  </span>
                                ))}
                                {dev.tags.length > 4 && (
                                  <span className="text-[9px] text-black/30 shrink-0">+{dev.tags.length - 4}</span>
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
                        : (zh ? '输入设备 IP 后按回车，系统将自动验证并显示设备标签' : 'Enter a device IP and press Enter to validate and show device tags')}
                    </p>
                  </div>
                )}

                {/* Tag picker — full width below grid */}
                {form.device_scope === 'tag' && (
                  <div>
                    <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '标签条件' : 'Tag Conditions'}</label>
                    <TagConditionPicker value={tagFilter} onChange={setTagFilter} language={language} />
                  </div>
                )}
              </div>

              {/* Footer */}
              <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-black/[0.06]">
                <button
                  type="button" onClick={closeModal}
                  className="px-5 py-2 rounded-xl border border-black/[0.08] text-xs font-semibold text-black/50 hover:bg-black/[0.02] transition-all"
                >
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button
                  type="button" onClick={submitForm}
                  disabled={!form.name.trim() || (!isEditMode && approvalStatus !== 'verified')}
                  className="px-5 py-2 rounded-xl bg-cyan-600 text-white text-xs font-bold hover:bg-cyan-700 disabled:opacity-40 disabled:cursor-not-allowed transition-all shadow-sm"
                >
                  {isEditMode ? (zh ? '保存修改' : 'Save Changes') : (zh ? '创建定时作业' : 'Create Scheduled Job')}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default ScheduledJobsTab;
