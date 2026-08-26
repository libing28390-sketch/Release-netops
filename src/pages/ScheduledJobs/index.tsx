import React, { useEffect, useState, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { AnimatePresence, motion } from 'motion/react';
import {
  CalendarClock, Plus, X, Trash2, RotateCcw, Zap, Pencil,
  ChevronDown, Info, Shield, CheckCircle2, AlertTriangle,
  Database, Activity, Power, PowerOff, RefreshCw,
  Search, FileCode, Eye, Target, FileText, Lock, ArrowUpRight, ChevronUp, Filter, ShieldAlert, User
} from 'lucide-react';
import { ActionIconButton, ActionIconGroup } from '../../components/ui/ActionIconButton';

import Pagination from '../../components/Pagination';
import { DataTable } from '../../components/DataTable';
import PageHero from '../../components/PageHero';
import { hasTagFilterConditions, parseTagFilter, type TagFilterConfig, EMPTY_TAG_FILTER, serializeTagFilter } from '../../components/TagConditionPicker';

import { ScheduledJob, EligibleApprover, SystemScheduledJob, FormState, ValidatedDevice, ScheduledJobsTabProps } from './types';
import { INITIAL_FORM, ACTION_TYPES, MAJOR_CATEGORIES } from './constants';
import { describeCron, describeScope } from './helpers';

import { CandidateModal } from './components/CandidateModal';
import { DeleteApprovalModal } from './components/DeleteApprovalModal';
import { JobDetailModal } from './components/JobDetailModal';
import { JobModal } from './components/JobModal';

const ScheduledJobsTab: React.FC<ScheduledJobsTabProps> = ({ language, showToast }) => {
  const zh = language === 'zh';
  const navigate = useNavigate();

  /* === STATE === */
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const [systemJobs, setSystemJobs] = useState<SystemScheduledJob[]>([]);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);

  // Modal
  const [showAddJob, setShowAddJob] = useState(false);
  const [detailJob, setDetailJob] = useState<ScheduledJob | null>(null);
  const [editingJob, setEditingJob] = useState<ScheduledJob | null>(null);
  const [viewingScript, setViewingScript] = useState<any>(null);
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
  const [availableScripts, setAvailableScripts] = useState<{ id: string; name: string; status: string; category: string; platform?: string }[]>([]);
  const [scriptSearch, setScriptSearch] = useState('');
  const [showScriptDropdown, setShowScriptDropdown] = useState(false);

  const isEditMode = editingJob !== null;

  // Category & Filter state
  const [activeCategory, setActiveCategory] = useState<'all' | 'system' | 'backup' | 'nsot' | 'inspection' | 'script_run'>('all');
  const [searchQuery, setSearchQuery] = useState('');
  // Keep platform schedules out of the way of user-created jobs by default.
  // Selecting the dedicated system category expands the small curated list.
  const [systemCollapsed, setSystemCollapsed] = useState(true);

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
    const nsotCnt = jobs.filter(j => j.action_type === 'nsot').length;
    const inspCnt = jobs.filter(j => j.action_type === 'inspection').length;
    const scriptCnt = jobs.filter(j => j.action_type === 'script_run').length;
    const activeCnt = jobs.filter(j => j.enabled === 1).length;
    return { backupCnt, nsotCnt, inspCnt, scriptCnt, activeCnt };
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
      // Silently skip
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
    if ((showAddJob || detailJob) && (form.action_type === 'script_run' || form.action_type === 'inspection' || detailJob?.action_type === 'script_run' || detailJob?.action_type === 'inspection')) fetchScripts();
  }, [showAddJob, detailJob, isEditMode, fetchApprovers, fetchScripts, form.action_type]);

  // Auto-load script content when detail modal opens for a script_run or inspection job
  useEffect(() => {
    if (detailJob && (detailJob.action_type === 'script_run' || detailJob.action_type === 'inspection') && detailJob.script_id) {
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
    // 在发送验证码前先校验必填项,避免半填状态下的无效审批流
    const err = validateForm();
    if (err) { showToast(err, 'error'); return; }
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
                  selected: true,
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
                      selected: true,
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

  /**
   * 统一的表单必填校验。命令(commands)在大部分场景下可选；其余字段都是必填。
   * 仅当返回值为 null 时通过校验，否则返回的字符串就是要展示给用户的中/英文提示。
   */
  const validateForm = (): string | null => {
    if (!form.name.trim()) return zh ? '请填写作业名称' : 'Please enter job name';
    if (!form.action_type) return zh ? '请选择作业类型' : 'Please select a job type';
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
    if (form.action_type === 'script_run' && !form.script_id) {
      return zh ? '请选择一个要执行的脚本' : 'Please select a script to execute';
    }
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
    if (!editingJob) return;
    const err = validateForm();
    if (err) { showToast(err, 'error'); return; }
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
          showToast(zh ? '作业已安全停用' : 'Job disabled', 'success');
        }
      } catch { /* ignore */ }
      return;
    }
    setEnablingJobId(job.id);
    openEditModal(job);
    showToast(zh ? '恢复启用定时作业需完成审批授权' : 'Enabling job requires approval verification', 'info');
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
              setApproverUsername={setApproverUsername}
              approvers={approvers}
              approvalStatus={approvalStatus}
              approvalCountdown={approvalCountdown}
              approvalCode={approvalCode}
              setApprovalCode={setApprovalCode}
              approvalError={approvalError}
              setApprovalError={setApprovalError}
              requestApproval={requestApproval}
              verifyApproval={verifyApproval}
              submitForm={submitForm}
              language={language}
            />
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
                    <span>{zh ? '用户作业' : 'User Jobs'}</span>
                    <span className={`px-2 py-0.5 rounded-full text-[10px] ${activeCategory === 'all' ? 'bg-cyan-100 text-cyan-800 font-mono' : 'bg-slate-200/80 text-slate-600'}`}>
                      {jobs.length}
                    </span>
                  </button>

                  <button
                    onClick={() => {
                      setActiveCategory('system');
                      setSystemCollapsed(false);
                    }}
                    className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-bold transition-all whitespace-nowrap shrink-0 ${
                      activeCategory === 'system'
                        ? 'bg-white text-cyan-700 shadow-sm border border-cyan-100'
                        : 'text-slate-600 hover:text-slate-900 hover:bg-white/60'
                    }`}
                  >
                    <span>{zh ? '系统计划' : 'System Schedules'}</span>
                    <span className={`px-2 py-0.5 rounded-full text-[10px] ${activeCategory === 'system' ? 'bg-cyan-100 text-cyan-800 font-mono' : 'bg-slate-200/80 text-slate-600'}`}>
                      {systemJobs.length}
                    </span>
                  </button>

                  <div className="w-px h-5 bg-slate-300/60 mx-1" />

                  <button
                    onClick={() => setActiveCategory('backup')}
                    className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-bold transition-all whitespace-nowrap shrink-0 ${
                      activeCategory === 'backup'
                        ? 'bg-white text-indigo-700 border border-indigo-100 shadow-sm'
                        : 'text-slate-600 hover:text-slate-900 hover:bg-white/60'
                    }`}
                  >
                    <Database size={13} className={activeCategory === 'backup' ? 'text-indigo-600' : 'text-slate-400'} />
                    <span>{zh ? '配置采集' : 'Backup'}</span>
                    <span className="text-[10px] opacity-60 font-mono">{stats.backupCnt}</span>
                  </button>

                  <button
                    onClick={() => setActiveCategory('nsot')}
                    className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-bold transition-all whitespace-nowrap shrink-0 ${
                      activeCategory === 'nsot'
                        ? 'bg-white text-cyan-700 border border-cyan-100 shadow-sm'
                        : 'text-slate-600 hover:text-slate-900 hover:bg-white/60'
                    }`}
                  >
                    <RefreshCw size={13} className={activeCategory === 'nsot' ? 'text-cyan-600' : 'text-slate-400'} />
                    <span>NSOT</span>
                    <span className="text-[10px] opacity-60 font-mono">{stats.nsotCnt}</span>
                  </button>

                  <button
                    onClick={() => setActiveCategory('inspection')}
                    className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-bold transition-all whitespace-nowrap shrink-0 ${
                      activeCategory === 'inspection'
                        ? 'bg-white text-emerald-700 border border-emerald-100 shadow-sm'
                        : 'text-slate-600 hover:text-slate-900 hover:bg-white/60'
                    }`}
                  >
                    <Activity size={13} className={activeCategory === 'inspection' ? 'text-emerald-600' : 'text-slate-400'} />
                    <span>{zh ? '智能巡检' : 'Inspection'}</span>
                    <span className="text-[10px] opacity-60 font-mono">{stats.inspCnt}</span>
                  </button>

                  <button
                    onClick={() => setActiveCategory('script_run')}
                    className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-bold transition-all whitespace-nowrap shrink-0 ${
                      activeCategory === 'script_run'
                        ? 'bg-white text-amber-700 border border-amber-100 shadow-sm'
                        : 'text-slate-600 hover:text-slate-900 hover:bg-white/60'
                    }`}
                  >
                    <Zap size={13} className={activeCategory === 'script_run' ? 'text-amber-600' : 'text-slate-400'} />
                    <span>{zh ? '自动化脚本' : 'Scripts'}</span>
                    <span className="text-[10px] opacity-60 font-mono">{stats.scriptCnt}</span>
                  </button>
                </div>

                <div className="relative flex-1 md:max-w-xs">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={14} />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={e => setSearchQuery(e.target.value)}
                    placeholder={zh ? '按名称、脚本ID或命令搜索...' : 'Search by name, command...'}
                    className="w-full pl-9 pr-4 py-2 rounded-xl border border-slate-200 bg-white text-xs outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all placeholder:text-slate-400"
                  />
                  {searchQuery && (
                    <button
                      onClick={() => setSearchQuery('')}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                    >
                      <X size={12} />
                    </button>
                  )}
                </div>
              </div>

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
                      <DataTable className="text-left">
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
                      const isNsot = job.action_type === 'nsot';
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
                            <div className={`w-11 h-11 rounded-xl flex items-center justify-center shrink-0 border ${
                              isEnabled
                                ? isNsot ? 'bg-cyan-50 text-cyan-600 border-cyan-100'
                                  : isInsp ? 'bg-emerald-50 text-emerald-600 border-emerald-100'
                                  : isBackup ? 'bg-indigo-50 text-indigo-600 border-indigo-100'
                                  : isScript ? 'bg-amber-50 text-amber-600 border-amber-100'
                                  : 'bg-cyan-50 text-cyan-600 border-cyan-100'
                                : 'bg-slate-100 text-slate-400 border-slate-200'
                            }`}>
                              <AtIcon size={20} />
                            </div>

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
                                    {isNsot ? <RefreshCw size={12} className="text-cyan-600" /> : <User size={12} className="text-slate-500" />}
                                    {isNsot ? (zh ? '平台采集' : 'Platform collection') : (zh ? '普通执行 (User)' : 'Normal')}
                                  </span>
                                )}
                              </div>

                              <div className="flex items-center gap-3 mt-1.5 text-xs text-slate-500 flex-wrap">
                                <span className="flex items-center gap-1 font-mono font-semibold text-slate-700 bg-slate-100 px-2 py-0.5 rounded">
                                  <CalendarClock size={12} className="text-cyan-600" />
                                  {describeCron(job.cron_expr, zh)}
                                </span>
                                <span className="text-slate-300">·</span>
                                <span className={`font-semibold ${isNsot ? 'text-cyan-700' : isInsp ? 'text-emerald-700' : isBackup ? 'select-none text-indigo-700' : isScript ? 'text-amber-700' : 'text-slate-700'}`}>
                                  {zh ? (atInfo?.labelZh || job.action_type) : (atInfo?.labelEn || job.action_type)}
                                </span>
                                <span className="text-slate-300">·</span>
                                <span className="flex items-center gap-1 text-slate-600 font-medium">
                                  <Target size={12} className="text-slate-400" />
                                  {scopeDesc}
                                </span>

                                {(job.action_type === 'script_run' || job.action_type === 'inspection') && job.script_id && (
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

                            <ActionIconGroup label={zh ? '计划任务操作' : 'Scheduled job actions'} className="shrink-0" onClick={e => e.stopPropagation()}>
                              <ActionIconButton
                                icon={Eye}
                                label={zh ? '查看运行详情' : 'View Detail'}
                                onClick={() => setDetailJob(job)}
                              />
                              <ActionIconButton
                                icon={Pencil}
                                label={zh ? '编辑配置' : 'Edit'}
                                onClick={() => openEditModal(job)}
                              />
                              <ActionIconButton
                                icon={isEnabled ? PowerOff : Power}
                                label={isEnabled ? (zh ? '暂停执行' : 'Disable') : (zh ? '恢复启动' : 'Enable')}
                                variant={isEnabled ? 'default' : 'success'}
                                onClick={() => toggleJobEnabled(job)}
                              />
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
                                <ActionIconButton
                                  icon={Trash2}
                                  label={zh ? '删除作业' : 'Delete'}
                                  variant="danger"
                                  onClick={() => setDeleteConfirmId(job.id)}
                                />
                              )}
                            </ActionIconGroup>
                          </div>

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
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* --- Detail Modal --- */}
      <JobDetailModal
        isOpen={!!detailJob}
        onClose={() => setDetailJob(null)}
        detailJob={detailJob}
        viewingScript={viewingScript}
        fetchAndShowScriptDetail={fetchAndShowScriptDetail}
        availableScripts={availableScripts}
        openEditModal={openEditModal}
        language={language}
      />

      {/* --- Delete Approval Modal --- */}
      <DeleteApprovalModal
        isOpen={deleteApprovalOpen}
        onClose={() => setDeleteApprovalOpen(false)}
        deleteTarget={deleteTarget}
        deleteReason={deleteReason}
        setDeleteReason={setDeleteReason}
        deleteApprover={deleteApprover}
        setDeleteApprover={setDeleteApprover}
        deleteStatus={deleteStatus}
        deleteCountdown={deleteCountdown}
        deleteCode={deleteCode}
        setDeleteCode={setDeleteCode}
        deleteError={deleteError}
        setDeleteError={setDeleteError}
        approvers={approvers}
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
    </div>
  );
};

export default ScheduledJobsTab;
