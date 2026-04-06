import React, { useEffect, useState, useCallback, useMemo } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  CalendarClock, Clock, Plus, X, Trash2, Activity, RotateCcw, Zap,
  ChevronDown, Play, Info, Database, Server, ExternalLink,
} from 'lucide-react';
import Pagination from '../components/Pagination';

/* ═══════════════════════════════════════════════════════ */
/*  Constants                                              */
/* ═══════════════════════════════════════════════════════ */

const INSPECTION_CRON_PRESETS = [
  { label: '每天 06:00 和 18:00', labelEn: 'Daily at 06:00 & 18:00', cron: '0 6,18 * * *' },
  { label: '每天 08:00', labelEn: 'Daily at 08:00', cron: '0 8 * * *' },
  { label: '每天 00:00', labelEn: 'Daily at midnight', cron: '0 0 * * *' },
  { label: '每4小时', labelEn: 'Every 4 hours', cron: '0 */4 * * *' },
  { label: '每2小时', labelEn: 'Every 2 hours', cron: '0 */2 * * *' },
  { label: '每30分钟', labelEn: 'Every 30 minutes', cron: '*/30 * * * *' },
  { label: '工作日 09:00', labelEn: 'Weekdays at 09:00', cron: '0 9 * * 1-5' },
  { label: '每周一 06:00', labelEn: 'Mon at 06:00', cron: '0 6 * * 1' },
  { label: '每月1日 06:00', labelEn: '1st of month at 06:00', cron: '0 6 1 * *' },
];

const CRON_FIELD_LABELS_ZH = ['分钟', '小时', '日', '月', '星期'];
const CRON_FIELD_LABELS_EN = ['Minute', 'Hour', 'Day', 'Month', 'Weekday'];
const CRON_FIELD_HINTS_ZH = ['0-59, */5, 0,30', '0-23, */2, 0-6', '1-31, */2', '1-12, */3', '0-6, 1-5'];
const CRON_FIELD_HINTS_EN = ['0-59, */5, 0,30', '0-23, */2, 0-6', '1-31, */2', '1-12, */3', '0-6 (Sun=0), 1-5'];

/* ═══════════════════════════════════════════════════════ */
/*  Types                                                  */
/* ═══════════════════════════════════════════════════════ */

interface InspectionSchedule {
  id: string; name: string; cron_expr: string; scope_type: string; scope_filter: string;
  enabled: number; last_run_at?: string; created_by: string; created_at: string;
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
}

interface BackupSchedulePreview {
  enabled: boolean;
  cron: string;
  upcoming: string[];
  devices: { id: string; hostname: string; ip_address: string; platform: string; status: string }[];
  device_count: number;
}

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

/* ═══════════════════════════════════════════════════════ */
/*  Component                                              */
/* ═══════════════════════════════════════════════════════ */

const ExecutionScheduleTab: React.FC<ExecutionScheduleTabProps> = ({ language, showToast }) => {
  const zh = language === 'zh';

  /* ═══ STATE ═══ */
  const [inspSchedules, setInspSchedules] = useState<InspectionSchedule[]>([]);
  const [inspSchedulesLoading, setInspSchedulesLoading] = useState(false);
  const [showAddInspSchedule, setShowAddInspSchedule] = useState(false);
  const [inspForm, setInspForm] = useState({ name: '', cron_expr: '0 6,18 * * *', scope_type: 'all', scope_filter: '' });
  const [inspPresetOpen, setInspPresetOpen] = useState(false);

  const [inspRuns, setInspRuns] = useState<InspectionRun[]>([]);
  const [inspRunsLoading, setInspRunsLoading] = useState(false);
  const [inspRunPage, setInspRunPage] = useState(1);
  const [inspRunPageSize] = useState(10);
  const [inspRunTotal, setInspRunTotal] = useState(0);
  type InspSubTab = 'schedules' | 'history';
  const [inspSubTab, setInspSubTab] = useState<InspSubTab>('schedules');

  const [backupPreview, setBackupPreview] = useState<BackupSchedulePreview | null>(null);

  const authHeaders = useMemo(() => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' };
  }, []);

  /* ═══ FETCHERS ═══ */
  const fetchInspSchedules = useCallback(async () => {
    setInspSchedulesLoading(true);
    try { const r = await fetch('/api/inspections/schedules', { headers: authHeaders }); if (r.ok) { const j = await r.json(); setInspSchedules(j.data || []); } }
    finally { setInspSchedulesLoading(false); }
  }, [authHeaders]);

  const fetchInspRuns = useCallback(async () => {
    setInspRunsLoading(true);
    try {
      const offset = (inspRunPage - 1) * inspRunPageSize;
      const r = await fetch(`/api/inspections?limit=${inspRunPageSize}&offset=${offset}`, { headers: authHeaders });
      if (r.ok) {
        const j = await r.json(); const d = j.data;
        if (d && typeof d === 'object' && !Array.isArray(d)) { setInspRuns(Array.isArray(d.items) ? d.items : []); setInspRunTotal(typeof d.total === 'number' ? d.total : 0); }
        else { setInspRuns(Array.isArray(d) ? d : []); setInspRunTotal(Array.isArray(d) ? d.length : 0); }
      }
    } finally { setInspRunsLoading(false); }
  }, [authHeaders, inspRunPage, inspRunPageSize]);

  useEffect(() => {
    fetchInspSchedules();
    fetchBackupPreview();
    if (inspSubTab === 'history') fetchInspRuns();
  }, [inspSubTab, fetchInspSchedules, fetchInspRuns]);

  const fetchBackupPreview = useCallback(async () => {
    try {
      const r = await fetch('/api/configs/schedule/preview?n=3', { headers: authHeaders });
      if (r.ok) setBackupPreview(await r.json());
    } catch { /* ignore */ }
  }, [authHeaders]);

  /* ═══ ACTIONS ═══ */
  const addInspSchedule = async () => {
    if (!inspForm.name.trim()) return;
    try {
      const r = await fetch('/api/inspections/schedules', { method: 'POST', headers: authHeaders, body: JSON.stringify(inspForm) });
      if (r.ok) { setShowAddInspSchedule(false); setInspForm({ name: '', cron_expr: '0 6,18 * * *', scope_type: 'all', scope_filter: '' }); fetchInspSchedules(); showToast(zh ? '执行计划已创建' : 'Execution schedule created', 'success'); }
    } catch { /* ignore */ }
  };
  const deleteInspSchedule = async (id: string) => {
    try { await fetch(`/api/inspections/schedules/${id}`, { method: 'DELETE', headers: authHeaders }); fetchInspSchedules(); showToast(zh ? '计划已删除' : 'Schedule deleted', 'success'); } catch { /* ignore */ }
  };
  const toggleInspScheduleEnabled = async (sch: InspectionSchedule) => {
    try { await fetch(`/api/inspections/schedules/${sch.id}`, { method: 'PUT', headers: authHeaders, body: JSON.stringify({ enabled: !sch.enabled }) }); fetchInspSchedules(); } catch { /* ignore */ }
  };

  const inspCronParts = inspForm.cron_expr.split(/\s+/);
  const inspCronFields = [inspCronParts[0] ?? '0', inspCronParts[1] ?? '*', inspCronParts[2] ?? '*', inspCronParts[3] ?? '*', inspCronParts[4] ?? '*'];
  const updateInspCronField = (index: number, value: string) => {
    const p = [...inspCronFields]; p[index] = value || '*';
    setInspForm(f => ({ ...f, cron_expr: p.join(' ') }));
  };

  /* ═══ RENDER ═══ */
  return (
    <div className="space-y-3">
      {/* Page Header */}
      <div className="rounded-2xl border border-black/5 bg-white shadow-sm">
        <div className="flex items-center justify-between px-5 py-3">
          <div>
            <h2 className="text-lg font-semibold text-[#164e63]">{zh ? '执行计划' : 'Execution Schedules'}</h2>
            <p className="text-[11px] text-black/40">{zh ? '统一查看与管理所有定时执行计划' : 'Unified view of all scheduled execution plans'}</p>
          </div>
        </div>
      </div>

      {/* Sub-tabs + Add button */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-1 rounded-xl bg-black/[0.03] p-1">
          <button
            onClick={() => setInspSubTab('schedules')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              inspSubTab === 'schedules' ? 'bg-white text-[#164e63] shadow-sm' : 'text-black/40 hover:text-black/60'
            }`}
          >
            <CalendarClock className="w-3.5 h-3.5" />
            {zh ? '执行计划' : 'Schedules'}
          </button>
          <button
            onClick={() => setInspSubTab('history')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              inspSubTab === 'history' ? 'bg-white text-[#164e63] shadow-sm' : 'text-black/40 hover:text-black/60'
            }`}
          >
            <Clock className="w-3.5 h-3.5" />
            {zh ? '历史任务' : 'History'}
          </button>
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
          {/* Add schedule form */}
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
                          placeholder={zh ? '每日巡检' : 'Daily inspection'}
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

                    {/* Right: Cron Editor */}
                    <div className="space-y-3">
                      <div className="relative">
                        <button
                          onClick={() => setInspPresetOpen(!inspPresetOpen)}
                          className="inline-flex h-10 w-full items-center justify-between gap-2 rounded-xl border border-black/8 bg-[#f8fafc] px-3.5 text-sm text-[#164e63] transition-all hover:border-cyan-400/30 hover:bg-white"
                        >
                          <div className="flex items-center gap-2">
                            <Zap size={13} className="text-cyan-500" />
                            <span>{zh ? '快速预设' : 'Quick Presets'}</span>
                          </div>
                          <ChevronDown size={14} className={`text-black/30 transition-transform ${inspPresetOpen ? 'rotate-180' : ''}`} />
                        </button>
                        <AnimatePresence>
                          {inspPresetOpen && (
                            <motion.div
                              initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
                              className="absolute z-20 mt-1.5 w-full rounded-xl border border-black/8 bg-white shadow-lg overflow-hidden max-h-56 overflow-y-auto"
                            >
                              {INSPECTION_CRON_PRESETS.map(p => (
                                <button
                                  key={p.cron}
                                  onClick={() => { setInspForm(f => ({ ...f, cron_expr: p.cron })); setInspPresetOpen(false); }}
                                  className={`flex w-full items-center justify-between px-3.5 py-2.5 text-sm transition-colors hover:bg-[#ecfeff] ${inspForm.cron_expr === p.cron ? 'bg-[#ecfeff] text-[#0891b2] font-medium' : 'text-black/60'}`}
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
                          {inspCronFields.map((val, i) => (
                            <div key={i}>
                              <label className="block text-[9px] font-bold uppercase tracking-wider text-black/30 mb-0.5">
                                {zh ? CRON_FIELD_LABELS_ZH[i] : CRON_FIELD_LABELS_EN[i]}
                              </label>
                              <input
                                value={val}
                                onChange={e => updateInspCronField(i, e.target.value)}
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
                          <code className="flex-1 font-mono text-sm text-[#164e63] font-semibold">{inspForm.cron_expr}</code>
                          <span className="text-[11px] text-black/40">{describeCron(inspForm.cron_expr, zh)}</span>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 pt-1">
                    <button
                      onClick={addInspSchedule}
                      disabled={!inspForm.name.trim()}
                      className="px-5 py-2 rounded-xl bg-cyan-600 text-white text-xs font-bold hover:bg-cyan-700 disabled:opacity-40 transition-all shadow-sm"
                    >
                      {zh ? '保存计划' : 'Save'}
                    </button>
                    <button
                      onClick={() => setShowAddInspSchedule(false)}
                      className="px-5 py-2 rounded-xl border border-black/[0.08] text-xs font-semibold text-black/50 hover:bg-black/[0.02] transition-all"
                    >
                      {zh ? '取消' : 'Cancel'}
                    </button>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* ── Backup Schedule Overview ── */}
          {backupPreview && (
            <div className="rounded-2xl border border-black/[0.06] bg-gradient-to-r from-[#0f172a] to-[#1e293b] p-4 shadow-lg">
              <div className="flex items-center justify-between flex-wrap gap-3">
                <div className="flex items-center gap-3">
                  <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${backupPreview.enabled ? 'bg-emerald-500/15' : 'bg-white/5'}`}>
                    <Database className={`w-4 h-4 ${backupPreview.enabled ? 'text-emerald-400' : 'text-white/30'}`} />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-bold text-white">{zh ? '配置备份' : 'Config Backup'}</p>
                      <span className={`text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded ${backupPreview.enabled ? 'bg-emerald-500/20 text-emerald-400' : 'bg-white/5 text-white/30'}`}>
                        {backupPreview.enabled ? (zh ? '运行中' : 'ACTIVE') : (zh ? '已停用' : 'IDLE')}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 mt-0.5">
                      <code className="text-[11px] text-cyan-400/80 font-mono">{backupPreview.cron}</code>
                      <span className="text-[10px] text-white/30">{describeCron(backupPreview.cron, zh)}</span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-4">
                  {backupPreview.enabled && backupPreview.upcoming?.[0] && (
                    <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/5">
                      <Clock size={12} className="text-cyan-400/60" />
                      <span className="text-[10px] text-white/30">{zh ? '下次执行' : 'Next'}</span>
                      <span className="text-[11px] text-cyan-400 font-mono font-medium">
                        {new Date(backupPreview.upcoming[0]).toLocaleString(zh ? 'zh-CN' : 'en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })}
                      </span>
                    </div>
                  )}
                  <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/5">
                    <Server size={12} className="text-white/30" />
                    <span className="text-[11px] text-white/50">{backupPreview.device_count} {zh ? '台设备' : 'devices'}</span>
                  </div>
                  <button
                    onClick={() => { window.history.pushState({}, '', '/config/schedule'); window.dispatchEvent(new PopStateEvent('popstate')); }}
                    className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 text-[11px] font-medium text-white/60 hover:bg-white/10 hover:text-white transition-all"
                  >
                    {zh ? '管理备份计划' : 'Manage'}
                    <ExternalLink size={11} />
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* ── Inspection section header ── */}
          <div className="flex items-center gap-2 pt-1">
            <h3 className="text-xs font-bold text-black/40 uppercase tracking-wider">{zh ? '巡检计划' : 'Inspection Schedules'}</h3>
            <div className="flex-1 h-px bg-black/[0.06]" />
            <span className="text-[10px] text-black/25 tabular-nums">{inspSchedules.length} {zh ? '个' : ''}</span>
          </div>

          {/* Schedule cards */}
          {inspSchedulesLoading ? (
            <div className="flex items-center justify-center py-12 text-black/30">
              <RotateCcw size={14} className="animate-spin mr-2" />
              <span className="text-xs">{zh ? '加载中...' : 'Loading...'}</span>
            </div>
          ) : inspSchedules.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {inspSchedules.map(sch => (
                <div key={sch.id} className="rounded-2xl border border-black/[0.06] bg-white shadow-sm p-4 hover:shadow-md transition-shadow">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-3 min-w-0">
                      <div className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${sch.enabled ? 'bg-cyan-50' : 'bg-slate-50'}`}>
                        <CalendarClock className={`w-4 h-4 ${sch.enabled ? 'text-cyan-600' : 'text-slate-400'}`} />
                      </div>
                      <div className="min-w-0">
                        <p className="text-sm font-bold text-[#164e63] truncate">{sch.name}</p>
                        <p className="text-[11px] text-black/50 mt-0.5">{describeCron(sch.cron_expr, zh)}</p>
                        <p className="text-[10px] text-black/25 font-mono mt-0.5">{sch.cron_expr}</p>
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
                    <span>{zh ? '上次运行' : 'Last'}: <strong className="text-black/60">{sch.last_run_at ? new Date(sch.last_run_at).toLocaleString(zh ? 'zh-CN' : 'en-US', { hour12: false }) : '—'}</strong></span>
                    <span className="text-black/10">|</span>
                    <span>{zh ? '创建者' : 'By'}: <strong className="text-black/60">{sch.created_by || '—'}</strong></span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-2xl border-2 border-dashed border-black/[0.06] p-12 text-center">
              <CalendarClock className="w-8 h-8 text-black/15 mx-auto mb-3" />
              <p className="text-sm text-black/35 font-medium">{zh ? '暂无执行计划' : 'No execution schedules'}</p>
              <p className="text-[11px] text-black/25 mt-1">{zh ? '点击「新建计划」创建定时执行任务' : 'Click "Add Schedule" to create one'}</p>
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
