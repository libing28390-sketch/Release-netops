import React, { useEffect, useState, useCallback, useMemo } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  CalendarClock, Clock, Plus, X, Trash2, Activity, RotateCcw,
  Play, Shield, CheckCircle2, CalendarRange, AlertTriangle,
} from 'lucide-react';
import Pagination from '../components/Pagination';
import DateTimePicker from '../components/DateTimePicker';

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
    <div className="space-y-4">
      {/* Page Header */}
      <div className="rounded-2xl border border-black/5 bg-[linear-gradient(to_right,#f4fbfc_0%,#ffffff_100%)] shadow-sm">
        <div className="flex items-center justify-between px-6 py-4">
          <div>
            <h2 className="text-xl font-bold text-[#164e63]">
              {inspSubTab === 'history' 
                ? (zh ? '执行历史' : 'Execution History') 
                : (zh ? '执行计划' : 'Execution Schedules')}
            </h2>
            <p className="text-xs text-black/40 mt-1">
              {inspSubTab === 'history'
                ? (zh ? '查看和追溯自动化执行历史' : 'View and trace automation execution history')
                : (zh ? '创建指定时间范围内执行的一次性巡检计划' : 'Create one-time inspection plans within a specified time window')}
            </p>
          </div>
          <div className="flex items-center gap-3">
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
          </div>
        </div>
      </div>

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
                  <div className="flex-1 overflow-x-auto">
                    {inspSchedulesLoading ? (
                      <div className="h-full flex flex-col items-center justify-center py-24 text-black/20 gap-3">
                        <RotateCcw size={32} className="animate-spin opacity-20" />
                        <span className="text-sm font-medium">{zh ? '正在加载数据...' : 'Loading schedules...'}</span>
                      </div>
                    ) : inspSchedules.length > 0 ? (
                      <table className="w-full text-left border-collapse min-w-[900px]">
                        <thead>
                          <tr className="bg-black/[0.01] border-b border-black/5">
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
              <div className="text-[11px] font-bold text-black/25 uppercase tracking-widest tabular-nums">
                {inspRunTotal} {zh ? '条记录' : 'Logs'}
              </div>
            </div>

            <div className="flex-1 overflow-x-auto">
              {inspRunsLoading ? (
                <div className="h-full flex flex-col items-center justify-center py-24 text-black/20 gap-3">
                  <RotateCcw size={32} className="animate-spin opacity-20" />
                  <span className="text-sm font-medium">{zh ? '获取流水中...' : 'Loading history...'}</span>
                </div>
              ) : inspRuns.length > 0 ? (
                <table className="w-full text-left border-collapse min-w-[1000px]">
                  <thead>
                    <tr className="bg-black/[0.01] border-b border-black/5">
                      <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{zh ? '触发时间' : 'Triggered At'}</th>
                      <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{zh ? '类型' : 'Type'}</th>
                      <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{zh ? '状态' : 'Status'}</th>
                      <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{zh ? '设备概况' : 'Devices Info'}</th>
                      <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{zh ? '健康指数' : 'Health Score'}</th>
                      <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider text-right">{zh ? '执行人' : 'Operator'}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-black/[0.03]">
                    {inspRuns.map(run => {
                      const statusMap: Record<string, { label: string; cls: string; dot: string }> = {
                        completed: { label: zh ? '已完成' : 'Completed', cls: 'bg-emerald-50 text-emerald-700', dot: 'bg-emerald-500' },
                        running: { label: zh ? '执行中' : 'Running', cls: 'bg-cyan-50 text-cyan-700', dot: 'bg-cyan-500' },
                        failed: { label: zh ? '已失败' : 'Failed', cls: 'bg-red-50 text-red-700', dot: 'bg-red-500' },
                      };
                      const st = statusMap[run.status] || { label: run.status, cls: 'bg-slate-50 text-slate-600', dot: 'bg-slate-400' };
                      return (
                        <tr key={run.id} className="hover:bg-indigo-50/20 transition-colors">
                          <td className="px-6 py-4 text-[13px] text-[#164e63] font-mono whitespace-nowrap">
                            {new Date(run.started_at).toLocaleString(zh ? 'zh-CN' : 'en-US', { hour12: false })}
                          </td>
                          <td className="px-6 py-4">
                            <span className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wide border ${
                              run.trigger_type === 'manual' 
                                ? 'bg-violet-50 text-violet-600 border-violet-100' 
                                : 'bg-blue-50 text-blue-600 border-blue-100'
                            }`}>
                              {run.trigger_type === 'manual' ? <Play size={10} /> : <Clock size={10} />}
                              {run.trigger_type === 'manual' ? (zh ? '手动' : 'Manual') : (zh ? '计划' : 'Plan')}
                            </span>
                          </td>
                          <td className="px-6 py-4">
                            <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-bold ${st.cls}`}>
                              <div className={`w-1.5 h-1.5 rounded-full ${run.status === 'running' ? 'animate-pulse' : ''} ${st.dot}`} />
                              {st.label}
                            </span>
                          </td>
                          <td className="px-6 py-4">
                            <div className="flex items-center gap-3">
                              <div className="flex flex-col">
                                <span className="text-xs font-bold text-black/60">{run.total_devices} {zh ? '台设备' : 'Devices'}</span>
                                <div className="flex items-center gap-1.5 mt-1">
                                  <div className="w-1.5 h-1.5 rounded-full bg-emerald-400" title={zh ? '健康' : 'Healthy'} />
                                  <span className="text-[10px] text-emerald-600 font-bold">{run.healthy_count}</span>
                                  <div className="w-1.5 h-1.5 rounded-full bg-amber-400 ml-1" title={zh ? '警告' : 'Warning'} />
                                  <span className="text-[10px] text-amber-600 font-bold">{run.warning_count}</span>
                                  <div className="w-1.5 h-1.5 rounded-full bg-red-400 ml-1" title={zh ? '故障' : 'Critical'} />
                                  <span className="text-[10px] text-red-600 font-bold">{run.critical_count}</span>
                                </div>
                              </div>
                            </div>
                          </td>
                          <td className="px-6 py-4">
                            <div className="flex flex-col gap-1.5">
                              <span className={`text-sm font-black tabular-nums ${
                                run.avg_health_score >= 80 ? 'text-emerald-600' : run.avg_health_score >= 60 ? 'text-amber-600' : 'text-red-600'
                              }`}>
                                {run.avg_health_score?.toFixed(1) ?? '—'}
                              </span>
                              <div className="w-20 h-1 bg-black/5 rounded-full overflow-hidden">
                                <div 
                                  className={`h-full rounded-full transition-all duration-1000 ${
                                    run.avg_health_score >= 80 ? 'bg-emerald-500' : run.avg_health_score >= 60 ? 'bg-amber-500' : 'bg-red-500'
                                  }`}
                                  style={{ width: `${run.avg_health_score ?? 0}%` }}
                                />
                              </div>
                            </div>
                          </td>
                          <td className="px-6 py-4 text-right">
                            <span className="text-xs font-bold text-black/30 group-hover:text-black/50 transition-colors">{run.created_by || 'system'}</span>
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

            {inspRunTotal > 0 && (
              <div className="mt-auto">
                <Pagination
                  currentPage={inspRunPage}
                  totalItems={inspRunTotal}
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
  );
};

export default ExecutionScheduleTab;
