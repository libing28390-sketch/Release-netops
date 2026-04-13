import React, { useEffect, useState, useCallback, useMemo } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  CalendarClock, Clock, Plus, X, Trash2, Activity, RotateCcw,
  Play, Shield, CheckCircle2, CalendarRange, AlertTriangle,
} from 'lucide-react';
import Pagination from '../components/Pagination';

/* ═══════════════════════════════════════════════════════ */
/*  Types                                                  */
/* ═══════════════════════════════════════════════════════ */

interface InspectionSchedule {
  id: string; name: string; cron_expr: string; scope_type: string; scope_filter: string;
  enabled: number; last_run_at?: string; created_by: string; created_at: string;
  scheduled_at?: string; expires_at?: string;
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

const ExecutionScheduleTab: React.FC<ExecutionScheduleTabProps> = ({ language, showToast, initialTab }) => {
  const zh = language === 'zh';

  /* ═══ STATE ═══ */
  const [inspSchedules, setInspSchedules] = useState<InspectionSchedule[]>([]);
  const [inspSchedulesLoading, setInspSchedulesLoading] = useState(false);
  const [inspSchedulePage, setInspSchedulePage] = useState(1);
  const [inspSchedulePageSize] = useState(10);
  const [showAddInspSchedule, setShowAddInspSchedule] = useState(false);
  const [inspForm, setInspForm] = useState({ name: '', scheduled_at: '', expires_at: '', scope_type: 'all', scope_filter: '' });

  const [inspRuns, setInspRuns] = useState<InspectionRun[]>([]);
  const [inspRunsLoading, setInspRunsLoading] = useState(false);
  const [inspRunPage, setInspRunPage] = useState(1);
  const [inspRunPageSize] = useState(10);
  const [inspRunTotal, setInspRunTotal] = useState(0);
  type InspSubTab = 'schedules' | 'history';
  const [inspSubTab, setInspSubTab] = useState<InspSubTab>(initialTab || 'schedules');

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
  }, []);

  /* ═══ Paginated schedule slice ═══ */
  const paginatedSchedules = useMemo(() => {
    const start = (inspSchedulePage - 1) * inspSchedulePageSize;
    return inspSchedules.slice(start, start + inspSchedulePageSize);
  }, [inspSchedules, inspSchedulePage, inspSchedulePageSize]);

  /* ═══ FETCHERS ═══ */
  const fetchInspSchedules = useCallback(async () => {
    setInspSchedulesLoading(true);
    try {
      const r = await fetch('/api/inspections/schedules', { headers: authHeaders });
      if (r.ok) { const j = await r.json(); setInspSchedules(j.data || []); }
    } finally { setInspSchedulesLoading(false); }
  }, [authHeaders]);

  const fetchInspRuns = useCallback(async () => {
    setInspRunsLoading(true);
    try {
      const offset = (inspRunPage - 1) * inspRunPageSize;
      const r = await fetch(`/api/inspections?limit=${inspRunPageSize}&offset=${offset}`, { headers: authHeaders });
      if (r.ok) {
        const j = await r.json(); const d = j.data;
        if (d && typeof d === 'object' && !Array.isArray(d)) {
          setInspRuns(Array.isArray(d.items) ? d.items : []);
          setInspRunTotal(typeof d.total === 'number' ? d.total : 0);
        } else {
          setInspRuns(Array.isArray(d) ? d : []);
          setInspRunTotal(Array.isArray(d) ? d.length : 0);
        }
      }
    } finally { setInspRunsLoading(false); }
  }, [authHeaders, inspRunPage, inspRunPageSize]);

  useEffect(() => {
    fetchInspSchedules();
    if (inspSubTab === 'history') fetchInspRuns();
  }, [inspSubTab, fetchInspSchedules, fetchInspRuns]);

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
    if (!inspForm.name.trim() || !inspForm.scheduled_at) {
      showToast(zh ? '请填写计划名称和执行时间' : 'Name and scheduled time are required', 'error');
      return;
    }
    if (inspForm.expires_at && inspForm.expires_at <= inspForm.scheduled_at) {
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
          approval_token: approvalToken,
          approval_code: approvalCode,
        }),
      });
      if (r.ok) {
        setShowAddInspSchedule(false);
        setInspForm({ name: '', scheduled_at: '', expires_at: '', scope_type: 'all', scope_filter: '' });
        resetApproval();
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
    <div className="space-y-3">
      {/* Page Header */}
      <div className="rounded-2xl border border-black/5 bg-white shadow-sm">
        <div className="flex items-center justify-between px-5 py-3">
          <div>
            <h2 className="text-lg font-semibold text-[#164e63]">{zh ? '执行计划' : 'Execution Schedules'}</h2>
            <p className="text-[11px] text-black/40">{zh ? '创建指定时间范围内执行的一次性巡检计划' : 'Create one-time inspection plans within a specified time window'}</p>
          </div>
        </div>
      </div>

      {/* Sub-tabs + Add button */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-1 bg-black/[0.03] rounded-lg p-0.5">
          {(['schedules', 'history'] as InspSubTab[]).map(tab => (
            <button
              key={tab}
              onClick={() => setInspSubTab(tab)}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                inspSubTab === tab ? 'bg-white text-[#164e63] shadow-sm' : 'text-black/40 hover:text-black/60'
              }`}
            >
              {tab === 'schedules' ? (zh ? '执行计划' : 'Schedules') : (zh ? '执行历史' : 'History')}
            </button>
          ))}
        </div>
        {inspSubTab === 'schedules' && (
          <button
            onClick={() => setShowAddInspSchedule(v => !v)}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-gradient-to-r from-cyan-500 to-cyan-600 text-white text-xs font-bold shadow-sm hover:from-cyan-400 hover:to-cyan-500 transition-all active:scale-[0.97]"
          >
            <Plus className="w-3.5 h-3.5" />
            {zh ? '新建计划' : 'Add Schedule'}
          </button>
        )}
      </div>

      {/* ── Schedules sub-tab ── */}
      {inspSubTab === 'schedules' && (
        <div className="space-y-3">
          {/* ── Add schedule form ── */}
          <AnimatePresence>
            {showAddInspSchedule && (
              <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
                <div className="rounded-2xl border border-cyan-200/60 bg-gradient-to-br from-cyan-50/50 to-white p-5 space-y-4 shadow-sm">
                  <div className="flex items-center justify-between">
                    <h4 className="text-sm font-bold text-[#164e63] flex items-center gap-2">
                      <Plus className="w-4 h-4 text-cyan-500" />
                      {zh ? '新建执行计划' : 'New Execution Schedule'}
                    </h4>
                    <button onClick={() => setShowAddInspSchedule(false)} className="p-1 rounded-lg text-black/30 hover:bg-black/5 transition-all">
                      <X className="w-4 h-4" />
                    </button>
                  </div>

                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    {/* Left: Name + Scope */}
                    <div className="space-y-4">
                      <div>
                        <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '计划名称' : 'Name'}</label>
                        <input
                          type="text" value={inspForm.name}
                          onChange={e => setInspForm(f => ({ ...f, name: e.target.value }))}
                          className="w-full px-3.5 py-2.5 rounded-xl border border-black/[0.08] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all"
                          placeholder={zh ? '例：核心交换机月度巡检' : 'e.g. Core Switch Monthly Check'}
                        />
                      </div>
                      <div>
                        <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '执行范围' : 'Scope'}</label>
                        <select
                          value={inspForm.scope_type}
                          onChange={e => setInspForm(f => ({ ...f, scope_type: e.target.value }))}
                          className="w-full px-3.5 py-2.5 rounded-xl border border-black/[0.08] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all"
                        >
                          <option value="all">{zh ? '全部设备' : 'All devices'}</option>
                          <option value="site">{zh ? '按站点' : 'By site'}</option>
                          <option value="role">{zh ? '按角色' : 'By role'}</option>
                        </select>
                      </div>
                      {inspForm.scope_type !== 'all' && (
                        <div>
                          <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '过滤条件' : 'Filter'}</label>
                          <input
                            type="text" value={inspForm.scope_filter}
                            onChange={e => setInspForm(f => ({ ...f, scope_filter: e.target.value }))}
                            className="w-full px-3.5 py-2.5 rounded-xl border border-black/[0.08] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all"
                            placeholder={zh ? '站点名 / 角色名' : 'Site or role name'}
                          />
                        </div>
                      )}
                    </div>

                    {/* Right: Time Range Picker */}
                    <div className="space-y-4">
                      <div>
                        <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">
                          <span className="text-red-400 mr-0.5">*</span>
                          {zh ? '执行开始时间' : 'Start Time'}
                        </label>
                        <input
                          type="datetime-local"
                          value={inspForm.scheduled_at}
                          onChange={e => setInspForm(f => ({ ...f, scheduled_at: e.target.value }))}
                          className="w-full px-3.5 py-2.5 rounded-xl border border-black/[0.08] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all"
                        />
                      </div>
                      <div>
                        <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">
                          {zh ? '执行结束时间（可选）' : 'End Time (optional)'}
                        </label>
                        <input
                          type="datetime-local"
                          value={inspForm.expires_at}
                          onChange={e => setInspForm(f => ({ ...f, expires_at: e.target.value }))}
                          min={inspForm.scheduled_at || undefined}
                          className="w-full px-3.5 py-2.5 rounded-xl border border-black/[0.08] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all"
                        />
                      </div>
                      {inspForm.scheduled_at && (
                        <div className="flex items-center gap-3 rounded-xl bg-cyan-500/[0.04] px-3.5 py-2.5">
                          <CalendarRange size={14} className="text-cyan-500 shrink-0" />
                          <div className="text-[11px] text-black/50">
                            <span className="font-semibold text-[#164e63]">{fmtDateTime(inspForm.scheduled_at, zh)}</span>
                            {inspForm.expires_at && (
                              <>
                                <span className="mx-1.5 text-black/20">→</span>
                                <span className="font-semibold text-[#164e63]">{fmtDateTime(inspForm.expires_at, zh)}</span>
                              </>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Approval Section */}
                  <div className="rounded-xl border border-amber-200/60 bg-gradient-to-br from-amber-50/50 to-white p-4 space-y-3">
                    <div className="flex items-center gap-2">
                      <Shield size={14} className="text-amber-600" />
                      <h5 className="text-xs font-bold text-amber-900 uppercase tracking-wider">{zh ? '审核授权' : 'Approval Authorization'}</h5>
                    </div>
                    {approvalStatus === 'idle' && (
                      <div className="space-y-3">
                        <div>
                          <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '审批人' : 'Approver'}</label>
                          <select
                            value={approverUsername}
                            onChange={(e) => setApproverUsername(e.target.value)}
                            className="w-full px-3.5 py-2.5 rounded-xl border border-black/[0.08] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-amber-500/20 focus:border-amber-400 transition-all"
                          >
                            <option value="">{zh ? '选择审批人...' : 'Select approver...'}</option>
                            {approvers.map(a => (
                              <option key={a.id} value={a.username}>{a.username} ({a.role})</option>
                            ))}
                          </select>
                        </div>
                        <button
                          onClick={requestApproval}
                          disabled={!approverUsername}
                          className="w-full px-4 py-2 rounded-xl bg-amber-600 text-white text-xs font-bold hover:bg-amber-700 disabled:opacity-40 transition-all"
                        >
                          {zh ? '发送验证码' : 'Send Code'}
                        </button>
                      </div>
                    )}
                    {(approvalStatus === 'sending' || approvalStatus === 'sent') && (
                      <div className="space-y-3">
                        <div className="text-xs text-amber-700">
                          {zh ? '验证码已发送至审批人，请输入收到的验证码' : 'Code sent to approver, enter the code you received'}
                        </div>
                        <input
                          type="text"
                          value={approvalCode}
                          onChange={(e) => { setApprovalCode(e.target.value.trim()); setApprovalError(''); }}
                          placeholder={zh ? '6 位验证码' : '6-digit code'}
                          className="w-full px-3.5 py-2.5 rounded-xl border border-black/[0.08] text-sm bg-white text-center font-mono font-bold focus:outline-none focus:ring-2 focus:ring-amber-500/20 focus:border-amber-400 transition-all"
                          maxLength={6}
                        />
                        {approvalError && <p className="text-[10px] text-red-600">{approvalError}</p>}
                        <button
                          onClick={verifyApproval}
                          disabled={approvalCode.length !== 6}
                          className="w-full px-4 py-2 rounded-xl bg-amber-600 text-white text-xs font-bold hover:bg-amber-700 disabled:opacity-40 transition-all"
                        >
                          {zh ? '验证' : 'Verify'}
                        </button>
                      </div>
                    )}
                    {approvalStatus === 'verified' && (
                      <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-green-50/60 border border-green-200/80">
                        <CheckCircle2 size={14} className="text-green-600" />
                        <span className="text-xs text-green-700 font-medium">{zh ? '已验证' : 'Verified'}</span>
                      </div>
                    )}
                  </div>

                  <div className="flex items-center gap-2 pt-1">
                    <button
                      onClick={addInspSchedule}
                      disabled={!inspForm.name.trim() || !inspForm.scheduled_at || approvalStatus !== 'verified'}
                      className="px-5 py-2 rounded-xl bg-cyan-600 text-white text-xs font-bold hover:bg-cyan-700 disabled:opacity-40 transition-all shadow-sm"
                    >
                      {zh ? '保存计划' : 'Save'}
                    </button>
                    <button
                      onClick={() => { setShowAddInspSchedule(false); resetApproval(); }}
                      className="px-5 py-2 rounded-xl border border-black/[0.08] text-xs font-semibold text-black/50 hover:bg-black/[0.02] transition-all"
                    >
                      {zh ? '取消' : 'Cancel'}
                    </button>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* ── Section header ── */}
          <div className="flex items-center gap-2 pt-1">
            <h3 className="text-xs font-bold text-black/40 uppercase tracking-wider">{zh ? '执行计划列表' : 'Schedule List'}</h3>
            <div className="flex-1 h-px bg-black/[0.06]" />
            <span className="text-[10px] text-black/25 tabular-nums">{inspSchedules.length} {zh ? '个' : ''}</span>
          </div>

          {/* ── Schedule cards ── */}
          {inspSchedulesLoading ? (
            <div className="flex items-center justify-center py-12 text-black/30">
              <RotateCcw size={14} className="animate-spin mr-2" />
              <span className="text-xs">{zh ? '加载中...' : 'Loading...'}</span>
            </div>
          ) : inspSchedules.length > 0 ? (
            <>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {paginatedSchedules.map(sch => {
                  const st = getScheduleStatus(sch, zh);
                  return (
                    <div key={sch.id} className="rounded-2xl border border-black/[0.06] bg-white shadow-sm p-4 hover:shadow-md transition-shadow">
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-center gap-3 min-w-0">
                          <div className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${sch.enabled ? 'bg-cyan-50' : 'bg-slate-50'}`}>
                            <CalendarClock className={`w-4 h-4 ${sch.enabled ? 'text-cyan-600' : 'text-slate-400'}`} />
                          </div>
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <p className="text-sm font-bold text-[#164e63] truncate">{sch.name}</p>
                              <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full whitespace-nowrap ${st.cls}`}>{st.label}</span>
                            </div>
                            <div className="flex items-center gap-1.5 mt-1">
                              <Clock size={11} className="text-black/25 shrink-0" />
                              <span className="text-[11px] text-black/50 font-mono">{fmtDateTime(sch.scheduled_at, zh)}</span>
                              {sch.expires_at && (
                                <>
                                  <span className="text-black/15 text-[10px]">→</span>
                                  <span className="text-[11px] text-black/50 font-mono">{fmtDateTime(sch.expires_at, zh)}</span>
                                </>
                              )}
                            </div>
                          </div>
                        </div>
                        <div className="flex items-center gap-1.5 shrink-0">
                          <button
                            onClick={() => toggleInspScheduleEnabled(sch)}
                            className={`relative w-9 h-5 rounded-full transition-colors ${sch.enabled ? 'bg-cyan-500' : 'bg-slate-200'}`}
                          >
                            <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow-sm transition-transform ${sch.enabled ? 'left-[18px]' : 'left-0.5'}`} />
                          </button>
                          <button
                            onClick={() => deleteInspSchedule(sch.id)}
                            className="p-1.5 rounded-lg text-black/20 hover:bg-red-50 hover:text-red-500 transition-all"
                            title={zh ? '删除' : 'Delete'}
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                      <div className="flex items-center gap-3 mt-3 pt-3 border-t border-black/[0.04] text-[11px] text-black/35">
                        <span>{zh ? '范围' : 'Scope'}: <strong className="text-black/60">{sch.scope_type === 'all' ? (zh ? '全部设备' : 'All') : `${sch.scope_type}${sch.scope_filter ? `: ${sch.scope_filter}` : ''}`}</strong></span>
                        <span className="text-black/10">|</span>
                        <span>{zh ? '上次运行' : 'Last'}: <strong className="text-black/60">{sch.last_run_at ? fmtDateTime(sch.last_run_at, zh) : '—'}</strong></span>
                        <span className="text-black/10">|</span>
                        <span>{zh ? '创建者' : 'By'}: <strong className="text-black/60">{sch.created_by || '—'}</strong></span>
                      </div>
                    </div>
                  );
                })}
              </div>
              {inspSchedules.length > inspSchedulePageSize && (
                <Pagination currentPage={inspSchedulePage} totalItems={inspSchedules.length} itemsPerPage={inspSchedulePageSize} onPageChange={setInspSchedulePage} language={language} />
              )}
            </>
          ) : (
            <div className="rounded-2xl border-2 border-dashed border-black/[0.06] p-12 text-center">
              <CalendarClock className="w-8 h-8 text-black/15 mx-auto mb-3" />
              <p className="text-sm text-black/35 font-medium">{zh ? '暂无执行计划' : 'No execution schedules'}</p>
              <p className="text-[11px] text-black/25 mt-1">{zh ? '点击「新建计划」创建一次性执行任务' : 'Click "Add Schedule" to create a one-time task'}</p>
            </div>
          )}
        </div>
      )}

      {/* ── History sub-tab ── */}
      {inspSubTab === 'history' && (
        <div className="space-y-3">
          <div className="rounded-2xl border border-black/[0.06] bg-white shadow-sm overflow-hidden">
            <div className="flex items-center justify-between px-5 py-3 border-b border-black/5">
              <h3 className="text-sm font-bold text-[#164e63] flex items-center gap-2">
                <Activity size={14} className="text-cyan-500" />
                {zh ? '历史执行记录' : 'Execution History'}
              </h3>
              <button
                onClick={fetchInspRuns}
                disabled={inspRunsLoading}
                className="inline-flex h-7 items-center gap-1 rounded-lg border border-black/8 bg-[#f8fafc] px-2.5 text-[11px] font-medium text-[#0e7490] transition-all hover:bg-white hover:border-cyan-400/30"
              >
                <RotateCcw size={11} className={inspRunsLoading ? 'animate-spin' : ''} />
                {zh ? '刷新' : 'Refresh'}
              </button>
            </div>

            {inspRunsLoading ? (
              <div className="flex items-center justify-center py-12 text-black/30">
                <RotateCcw size={14} className="animate-spin mr-2" />
                <span className="text-xs">{zh ? '加载中...' : 'Loading...'}</span>
              </div>
            ) : inspRuns.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-black/5 bg-black/[0.015]">
                      <th className="px-4 py-2.5 text-[10px] font-bold uppercase tracking-wider text-black/35">{zh ? '执行时间' : 'Time'}</th>
                      <th className="px-4 py-2.5 text-[10px] font-bold uppercase tracking-wider text-black/35">{zh ? '触发方式' : 'Trigger'}</th>
                      <th className="px-4 py-2.5 text-[10px] font-bold uppercase tracking-wider text-black/35">{zh ? '状态' : 'Status'}</th>
                      <th className="px-4 py-2.5 text-[10px] font-bold uppercase tracking-wider text-black/35">{zh ? '设备总数' : 'Devices'}</th>
                      <th className="px-4 py-2.5 text-[10px] font-bold uppercase tracking-wider text-black/35">{zh ? '健康/警告/严重' : 'H / W / C'}</th>
                      <th className="px-4 py-2.5 text-[10px] font-bold uppercase tracking-wider text-black/35">{zh ? '平均分数' : 'Avg Score'}</th>
                      <th className="px-4 py-2.5 text-[10px] font-bold uppercase tracking-wider text-black/35">{zh ? '执行者' : 'By'}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {inspRuns.map(run => {
                      const statusMap: Record<string, { label: string; cls: string }> = {
                        completed: { label: zh ? '完成' : 'Done', cls: 'bg-emerald-50 text-emerald-700' },
                        running: { label: zh ? '运行中' : 'Running', cls: 'bg-cyan-50 text-cyan-700' },
                        failed: { label: zh ? '失败' : 'Failed', cls: 'bg-red-50 text-red-700' },
                      };
                      const st = statusMap[run.status] || { label: run.status, cls: 'bg-slate-50 text-slate-600' };
                      const triggerLabel = run.trigger_type === 'manual' ? (zh ? '手动' : 'Manual') : (zh ? '定时' : 'Scheduled');
                      return (
                        <tr key={run.id} className="border-b border-black/[0.03] hover:bg-black/[0.01] transition-colors">
                          <td className="px-4 py-2.5 text-xs text-black/60 font-mono">
                            {new Date(run.started_at).toLocaleString(zh ? 'zh-CN' : 'en-US', { hour12: false })}
                          </td>
                          <td className="px-4 py-2.5">
                            <span className={`inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full ${
                              run.trigger_type === 'manual' ? 'bg-violet-50 text-violet-600' : 'bg-cyan-50 text-cyan-600'
                            }`}>
                              {run.trigger_type === 'manual' ? <Play className="w-2.5 h-2.5" /> : <CalendarClock className="w-2.5 h-2.5" />}
                              {triggerLabel}
                            </span>
                          </td>
                          <td className="px-4 py-2.5">
                            <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${st.cls}`}>{st.label}</span>
                          </td>
                          <td className="px-4 py-2.5 text-xs text-black/60">{run.total_devices}</td>
                          <td className="px-4 py-2.5">
                            <div className="flex items-center gap-1.5 text-[10px]">
                              <span className="font-bold text-emerald-600">{run.healthy_count}</span>
                              <span className="text-black/15">/</span>
                              <span className="font-bold text-amber-600">{run.warning_count}</span>
                              <span className="text-black/15">/</span>
                              <span className="font-bold text-red-600">{run.critical_count}</span>
                            </div>
                          </td>
                          <td className="px-4 py-2.5">
                            <span className={`text-xs font-bold tabular-nums ${
                              run.avg_health_score >= 80 ? 'text-emerald-600' : run.avg_health_score >= 60 ? 'text-amber-600' : 'text-red-600'
                            }`}>
                              {run.avg_health_score?.toFixed(1) ?? '—'}
                            </span>
                          </td>
                          <td className="px-4 py-2.5 text-xs text-black/40">{run.created_by || '—'}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="flex flex-col items-center py-12 text-black/25">
                <Activity size={24} strokeWidth={1} />
                <p className="mt-2 text-xs font-medium">{zh ? '暂无执行历史' : 'No execution history'}</p>
              </div>
            )}

            {inspRunTotal > 0 && (
              <div className="px-4 py-3 border-t border-black/5">
                <Pagination
                  currentPage={inspRunPage}
                  totalItems={inspRunTotal}
                  onPageChange={setInspRunPage}
                  itemsPerPage={inspRunPageSize}
                  language={language}
                />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default ExecutionScheduleTab;
