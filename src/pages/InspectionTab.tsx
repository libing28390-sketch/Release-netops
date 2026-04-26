import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, AlertTriangle, ArrowRight, CheckCircle2, ChevronRight, Clock, Cpu, Loader2, Play, RefreshCw, Search, Server, Shield, X, XCircle, Wifi, WifiOff, Zap, BarChart3, Eye } from 'lucide-react';
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { Device, DeviceHealthHistoryResponse, DeviceHealthOverview } from '../types';
import { useChartTheme } from '../hooks/useChartTheme';
import Pagination from '../components/Pagination';

/* ────────────────────────────────────────── */
/* Types                                      */
/* ────────────────────────────────────────── */

interface InspectionRun {
  id: string;
  schedule_id?: string;
  trigger_type: string;
  scope_type: string;
  scope_filter: string;
  status: string;
  started_at: string;
  completed_at?: string;
  total_devices: number;
  success_count: number;
  failed_count: number;
  unreachable_count: number;
  healthy_count: number;
  warning_count: number;
  critical_count: number;
  avg_health_score: number;
  created_by: string;
}

interface InspectionResult {
  id: string;
  device_id: string;
  hostname: string;
  ip_address: string;
  platform: string;
  role: string;
  site: string;
  ping_ok: number;
  ping_latency_ms: number | null;
  ssh_ok: number;
  ssh_error: string;
  health_score: number | null;
  health_status: string;
  cpu_usage: number | null;
  memory_usage: number | null;
  temperature: number | null;
  fan_status: string;
  psu_status: string;
  interface_total: number;
  interface_up: number;
  interface_down: number;
  interface_flapping: number;
  interface_high_util: number;
  interface_errors: number;
  open_alerts: number;
  critical_alerts: number;
  compliance_status: string;
  findings_json: string;
  checked_at: string;
}

interface InspectionRunDetail extends InspectionRun {
  results: InspectionResult[];
}



/* ────────────────────────────────────────── */
/* Props                                      */
/* ────────────────────────────────────────── */

interface InspectionTabProps {
  t: (key: string) => string;
  language: string;
  devices: Device[];
  overview: DeviceHealthOverview | null;
  onShowDetails: (device: Device) => void;
  initialView?: 'overview' | 'records';
}

const statusToneMap: Record<string, string> = {
  healthy: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200/60',
  warning: 'bg-amber-50 text-amber-700 ring-1 ring-amber-200/60',
  critical: 'bg-red-50 text-red-700 ring-1 ring-red-200/60',
  unknown: 'bg-slate-50 text-slate-600 ring-1 ring-slate-200/60',
};

/* ── Circular score gauge ── */
const ScoreGauge: React.FC<{ score: number | null; size?: number }> = ({ score, size = 80 }) => {
  const value = score ?? 0;
  const r = (size - 8) / 2;
  const circumference = 2 * Math.PI * r;
  const pct = Math.min(100, Math.max(0, value));
  const offset = circumference - (pct / 100) * circumference;
  const color = pct >= 80 ? '#10b981' : pct >= 60 ? '#f59e0b' : '#ef4444';
  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="currentColor" className="text-black/[0.04]" strokeWidth={5} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={5} strokeLinecap="round" strokeDasharray={circumference} strokeDashoffset={offset} style={{ transition: 'stroke-dashoffset 0.8s ease' }} />
      </svg>
      <span className="absolute text-base font-bold tabular-nums" style={{ color }}>{score ?? '—'}</span>
    </div>
  );
};

/* ── Th helper ── */
const Th: React.FC<{ children: React.ReactNode; className?: string }> = ({ children, className = '' }) => (
  <th className={`px-4 py-3 text-[10px] font-bold uppercase tracking-[0.12em] text-black/35 whitespace-nowrap ${className}`}>{children}</th>
);

/* ── Cron expression to human-readable description ── */
const cronToText = (expr: string, isZh: boolean): string => {
  const parts = expr.trim().split(/\s+/);
  if (parts.length < 5) return expr;
  const [min, hour, dom, mon, dow] = parts;
  const weekDaysZh = ['日', '一', '二', '三', '四', '五', '六'];
  const weekDaysEn = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const fmtTime = (h: string, m: string) => `${h.padStart(2, '0')}:${m.padStart(2, '0')}`;

  // 每 N 分钟
  if (min.startsWith('*/') && hour === '*') {
    const n = min.slice(2);
    return isZh ? `每 ${n} 分钟` : `Every ${n} minutes`;
  }
  // 每小时
  if (hour === '*' && !min.includes('/') && dom === '*' && mon === '*') {
    return isZh ? `每小时第 ${min} 分钟` : `Hourly at :${min.padStart(2, '0')}`;
  }

  const timeList = (hour.includes(',') ? hour.split(',') : [hour]).map(h => fmtTime(h, min));
  const timeStr = timeList.join(isZh ? '、' : ', ');

  // 特定星期几
  if (dom === '*' && mon === '*' && dow !== '*') {
    const days = dow.split(',').map(d => {
      const n = parseInt(d, 10);
      return isNaN(n) ? d : (isZh ? `周${weekDaysZh[n % 7]}` : weekDaysEn[n % 7]);
    });
    return isZh ? `${days.join('、')} ${timeStr}` : `${days.join(', ')} at ${timeStr}`;
  }
  // 每天
  if (dom === '*' && mon === '*' && dow === '*') {
    return isZh ? `每天 ${timeStr}` : `Daily at ${timeStr}`;
  }
  // 每月特定日期
  if (dom !== '*' && mon === '*') {
    return isZh ? `每月 ${dom} 日 ${timeStr}` : `Monthly on ${dom} at ${timeStr}`;
  }
  return expr;
};

/* ── Device role category helper ── */
const NETWORK_ROLES = new Set(['router', 'switch', 'firewall', 'ap', 'wlc', 'load-balancer', 'core', 'distribution', 'access']);
const isNetworkDevice = (role: string, platform: string): boolean => {
  if (!role && !platform) return true; // default to network device
  if (NETWORK_ROLES.has(role.toLowerCase())) return true;
  if (['server', 'host', 'vm', 'virtual-machine', 'hypervisor', 'storage'].includes(role.toLowerCase())) return false;
  // Infer from platform — common network vendor prefixes
  const p = platform.toLowerCase();
  if (['cisco', 'juniper', 'huawei', 'arista', 'h3c', 'fortinet'].some(v => p.includes(v))) return true;
  if (['linux', 'windows', 'vmware', 'esxi'].some(v => p.includes(v))) return false;
  return true; // default network
};

/* ────────────────────────────────────────── */
/* Component                                  */
/* ────────────────────────────────────────── */

const InspectionTab: React.FC<InspectionTabProps> = ({ t, language, devices, overview, onShowDetails, initialView }) => {
  const ct = useChartTheme();
  const isZh = language === 'zh';

  // ── sub-tab ──
  type SubTab = 'overview' | 'records';
  const [subTab, setSubTab] = useState<SubTab>(initialView || 'overview');

  // Sync sub-tab when sidebar navigation changes
  useEffect(() => {
    if (initialView) setSubTab(initialView);
  }, [initialView]);

  // ── overview state ──
  const [rangeHours, setRangeHours] = useState(24);
  const [history, setHistory] = useState<DeviceHealthHistoryResponse | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [recentRuns, setRecentRuns] = useState<InspectionRun[]>([]);

  // ── records state ──
  const [runs, setRuns] = useState<InspectionRun[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [selectedRunDetail, setSelectedRunDetail] = useState<InspectionRunDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [recordSearch, setRecordSearch] = useState('');
  const [recordPage, setRecordPage] = useState(1);
  const [recordPageSize, setRecordPageSize] = useState(15);
  const [recordTotal, setRecordTotal] = useState(0);

  // ── internal pagination for run details ──
  const [detailPage, setDetailPage] = useState(1);
  const [detailPageSize, setDetailPageSize] = useState(20);

  // ── run inspection ──
  const [isRunning, setIsRunning] = useState(false);
  const [runResult, setRunResult] = useState<Record<string, unknown> | null>(null);

  /* ─── token helper ─── */
  const authHeaders = useMemo(() => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' };
  }, []);

  /* ─── data fetchers ─── */

  const fetchHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const resp = await fetch(`/api/device-health/history?range_hours=${rangeHours}`);
      if (resp.ok) {
        const data = await resp.json();
        setHistory(data);
      }
    } finally {
      setHistoryLoading(false);
    }
  }, [rangeHours]);

  const fetchRecentRuns = useCallback(async () => {
    try {
      const resp = await fetch('/api/inspections?limit=5&offset=0', { headers: authHeaders });
      if (resp.ok) {
        const json = await resp.json();
        const d = json.data;
        setRecentRuns(Array.isArray(d) ? d : Array.isArray(d?.items) ? d.items : []);
      }
    } catch { /* ignore */ }
  }, [authHeaders]);

  const fetchRuns = useCallback(async () => {
    setRunsLoading(true);
    try {
      const offset = (recordPage - 1) * recordPageSize;
      const resp = await fetch(`/api/inspections?limit=${recordPageSize}&offset=${offset}`, { headers: authHeaders });
      if (resp.ok) {
        const json = await resp.json();
        const d = json.data;
        if (d && typeof d === 'object' && !Array.isArray(d)) {
          setRuns(Array.isArray(d.items) ? d.items : []);
          setRecordTotal(typeof d.total === 'number' ? d.total : 0);
        } else {
          setRuns(Array.isArray(d) ? d : []);
          setRecordTotal(Array.isArray(d) ? d.length : 0);
        }
      }
    } finally {
      setRunsLoading(false);
    }
  }, [authHeaders, recordPage, recordPageSize]);

  const fetchRunDetail = useCallback(async (runId: string) => {
    setDetailLoading(true);
    try {
      const resp = await fetch(`/api/inspections/${runId}`, { headers: authHeaders });
      if (resp.ok) {
        const json = await resp.json();
        setSelectedRunDetail(json.data || null);
      }
    } finally {
      setDetailLoading(false);
      setDetailPage(1); // Reset page when opening detail
    }
  }, [authHeaders]);



  /* ─── Effects ─── */

  useEffect(() => { fetchHistory(); }, [fetchHistory]);
  useEffect(() => { fetchRecentRuns(); }, [fetchRecentRuns]);
  useEffect(() => {
    if (subTab === 'records') fetchRuns();
  }, [subTab, fetchRuns]);

  // Reset page when search changes
  useEffect(() => { setRecordPage(1); }, [recordSearch]);

  /* ─── actions ─── */

  const triggerInspection = async (scopeType = 'all', scopeFilter = '') => {
    setIsRunning(true);
    setRunResult(null);
    try {
      const resp = await fetch('/api/inspections/run', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({ scope_type: scopeType, scope_filter: scopeFilter }),
      });
      const json = await resp.json();
      setRunResult(json.data || json);
      fetchRecentRuns();
      if (subTab === 'records') fetchRuns();
    } finally {
      setIsRunning(false);
    }
  };



  /* ─── derived data ─── */

  const historySeries = useMemo(() => history?.series || [], [history]);

  const filteredRuns = useMemo(() => {
    if (!recordSearch.trim()) return runs;
    const q = recordSearch.toLowerCase();
    return runs.filter((r) =>
      r.id.toLowerCase().includes(q) ||
      r.created_by.toLowerCase().includes(q) ||
      r.trigger_type.toLowerCase().includes(q) ||
      r.scope_type.toLowerCase().includes(q)
    );
  }, [runs, recordSearch]);

  const riskyDevices = useMemo(() => {
    return [...devices]
      .filter((d) => d.health_status === 'critical' || d.health_status === 'warning')
      .sort((a, b) => (a.health_score ?? 100) - (b.health_score ?? 100))
      .slice(0, 8);
  }, [devices]);

  const avgScore = overview?.average_score ?? null;

  /* ─── Tab config ─── */
  const subTabs: { key: SubTab; label: string; icon: React.ReactNode }[] = [
    { key: 'overview', label: isZh ? '巡检概览' : 'Overview', icon: <BarChart3 className="w-3.5 h-3.5" /> },
    { key: 'records', label: isZh ? '巡检记录' : 'Records', icon: <Clock className="w-3.5 h-3.5" /> },
  ];

  /* ─────────────────────────────────────── */
  /* Render                                   */
  /* ─────────────────────────────────────── */

  return (
    <div className="space-y-5">
      {/* ═══════ Hero header strip ═══════ */}
      <div className="relative rounded-2xl overflow-hidden bg-gradient-to-r from-[#0c1e35] via-[#0e2942] to-[#0a3455] p-5 shadow-lg">
        {/* decorative dots */}
        <div className="absolute inset-0 opacity-[0.04]" style={{ backgroundImage: 'radial-gradient(circle, white 1px, transparent 1px)', backgroundSize: '18px 18px' }} />
        <div className="relative flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
          {/* Left: gauge + KPI pills */}
          <div className="flex items-center gap-5">
            <ScoreGauge score={typeof avgScore === 'number' ? Math.round(avgScore) : null} size={76} />
            <div>
              <h2 className="text-white/90 text-lg font-bold tracking-tight">{isZh ? '网络健康总览' : 'Network Health Overview'}</h2>
              <div className="flex items-center gap-3 mt-2">
                {([
                  { label: isZh ? '设备' : 'Devices', value: overview?.total_devices ?? devices.length, cls: 'bg-white/10 text-white/80' },
                  { label: isZh ? '健康' : 'Healthy', value: overview?.healthy ?? 0, cls: 'bg-emerald-500/20 text-emerald-300' },
                  { label: isZh ? '告警' : 'Warning', value: overview?.warning ?? 0, cls: 'bg-amber-500/20 text-amber-300' },
                  { label: isZh ? '严重' : 'Critical', value: overview?.critical ?? 0, cls: 'bg-red-500/20 text-red-300' },
                ] as const).map((p) => (
                  <span key={p.label} className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold tabular-nums ${p.cls}`}>
                    {p.label} <strong className="text-[13px]">{p.value}</strong>
                  </span>
                ))}
              </div>
            </div>
          </div>

          {/* Right: action button */}
          <button
            onClick={() => triggerInspection('all')}
            disabled={isRunning}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-bold shadow-lg transition-all
              bg-gradient-to-r from-cyan-500 to-cyan-600 text-white hover:from-cyan-400 hover:to-cyan-500
              disabled:opacity-50 disabled:cursor-not-allowed active:scale-[0.97]"
          >
            {isRunning ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
            {isRunning ? (isZh ? '巡检执行中…' : 'Running...') : (isZh ? '立即巡检' : 'Run Inspection')}
          </button>
        </div>
      </div>

      {/* ═══════ Result toast ═══════ */}
      {runResult && (
        <div className="rounded-xl border border-cyan-200 bg-gradient-to-r from-cyan-50 to-white p-3.5 flex items-center justify-between gap-3 shadow-sm animate-in fade-in duration-300">
          <div className="flex items-center gap-3 text-sm">
            <div className="w-7 h-7 rounded-full bg-cyan-100 flex items-center justify-center shrink-0"><CheckCircle2 className="w-4 h-4 text-cyan-600" /></div>
            <span className="text-[#0b2340]">
              {isZh ? '巡检完成' : 'Inspection complete'}
              {' — '}
              {isZh ? '设备' : 'Devices'}: {String(runResult.total_devices || 0)},
              {' '}
              <span className="text-emerald-600 font-semibold">{isZh ? '健康' : 'healthy'} {String(runResult.healthy_count || 0)}</span>
              {', '}
              <span className="text-amber-600 font-semibold">{isZh ? '告警' : 'warning'} {String(runResult.warning_count || 0)}</span>
              {', '}
              <span className="text-red-600 font-semibold">{isZh ? '严重' : 'critical'} {String(runResult.critical_count || 0)}</span>
            </span>
          </div>
          <button onClick={() => setRunResult(null)} className="p-1 rounded-md text-black/30 hover:text-black/60 hover:bg-black/5 transition-colors"><X className="w-4 h-4" /></button>
        </div>
      )}

      {/* ═══════ SUB-TAB: OVERVIEW ═══════ */}
      {subTab === 'overview' && (
        <div className="space-y-5">
          {/* Health Trend Chart */}
          <div className="rounded-2xl border border-black/[0.06] bg-white shadow-sm p-5">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 mb-4">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center">
                  <Activity className="w-4 h-4 text-blue-600" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-[#0b2340]">{isZh ? '设备健康趋势' : 'Device Health Trend'}</h3>
                  <p className="text-[11px] text-black/35">{historyLoading ? (isZh ? '加载中...' : 'Loading...') : (isZh ? '柱状图为异常设备数量，折线为平均健康评分' : 'Bars = abnormal devices, Line = avg health score')}</p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-4 text-[11px] text-black/40">
                  <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-blue-500 inline-block" />{isZh ? '健康评分' : 'Score'}</span>
                  <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-red-400 inline-block" />{isZh ? '严重' : 'Critical'}</span>
                  <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-amber-400 inline-block" />{isZh ? '告警' : 'Warning'}</span>
                </div>
                <div className="flex items-center gap-0.5 rounded-lg bg-black/[0.03] p-0.5">
                  {([{ h: 1, l: isZh ? '1H' : '1H' }, { h: 24, l: isZh ? '24H' : '24H' }, { h: 168, l: isZh ? '7D' : '7D' }] as const).map(({ h, l }) => (
                    <button
                      key={h}
                      type="button"
                      onClick={() => setRangeHours(h)}
                      className={`px-2.5 py-1 rounded-md text-[10px] font-bold tracking-wide transition-all ${rangeHours === h ? 'bg-white text-[#0b2340] shadow-sm ring-1 ring-black/5' : 'text-black/40 hover:text-black/60'}`}
                    >
                      {l}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="h-[240px]">
              {historySeries.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={historySeries} margin={{ top: 8, right: 12, left: -4, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 6" vertical={false} stroke={ct.gridAlt} />
                    <XAxis dataKey="ts" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: ct.axisAlt }} tickFormatter={(v) => new Date(String(v)).toLocaleString(isZh ? 'zh-CN' : 'en-US', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })} minTickGap={36} />
                    <YAxis yAxisId="count" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: ct.axisAlt }} width={28} allowDecimals={false} />
                    <YAxis yAxisId="score" orientation="right" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: ct.axisAlt }} domain={[0, 100]} width={32} tickFormatter={(v: number) => `${v}`} />
                    <Tooltip
                      contentStyle={{ borderRadius: 12, border: 'none', boxShadow: '0 8px 32px rgba(0,0,0,0.12)', padding: '12px 16px', background: ct.tooltipBg, color: ct.tooltipText, fontSize: 12 }}
                      labelFormatter={(v) => new Date(String(v)).toLocaleString(isZh ? 'zh-CN' : 'en-US', { hour12: false })}
                      cursor={{ fill: 'rgba(0,0,0,0.03)' }}
                    />
                    <Bar yAxisId="count" dataKey="critical" name={isZh ? '严重设备' : 'Critical'} stackId="devices" fill="#f87171" radius={[0, 0, 2, 2]} barSize={16} />
                    <Bar yAxisId="count" dataKey="warning" name={isZh ? '告警设备' : 'Warning'} stackId="devices" fill="#fbbf24" radius={[2, 2, 0, 0]} barSize={16} />
                    <Line yAxisId="score" type="monotone" dataKey="average_score" name={isZh ? '平均健康分' : 'Avg Score'} stroke="#3b82f6" strokeWidth={2.5} dot={false} activeDot={{ r: 4, fill: '#3b82f6', stroke: '#fff', strokeWidth: 2 }} />
                  </ComposedChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-full flex flex-col items-center justify-center gap-2 text-black/25">
                  <BarChart3 className="w-8 h-8" />
                  <p className="text-sm">{isZh ? '暂无趋势数据' : 'No trend data yet'}</p>
                </div>
              )}
            </div>
          </div>

          {/* Bottom: recent runs + risk devices */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
            {/* Recent runs */}
            <div className="rounded-2xl border border-black/[0.06] bg-white shadow-sm overflow-hidden">
              <div className="px-5 pt-4 pb-3 flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <div className="w-7 h-7 rounded-lg bg-cyan-50 flex items-center justify-center"><Clock className="w-3.5 h-3.5 text-cyan-600" /></div>
                  <h3 className="text-sm font-bold text-[#0b2340]">{isZh ? '最近巡检' : 'Recent Inspections'}</h3>
                </div>
                <button onClick={() => setSubTab('records')} className="text-[11px] text-cyan-600 hover:text-cyan-800 font-medium flex items-center gap-1 transition-colors">
                  {isZh ? '查看全部' : 'View All'}<ArrowRight className="w-3 h-3" />
                </button>
              </div>
              <div className="px-4 pb-4 space-y-2">
                {recentRuns.length > 0 ? recentRuns.map((run) => (
                  <button
                    key={run.id}
                    type="button"
                    onClick={() => { setSubTab('records'); fetchRunDetail(run.id); }}
                    className="w-full group rounded-xl border border-black/[0.06] bg-white px-4 py-3 text-left transition-all hover:border-cyan-300/60 hover:shadow-sm"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-bold uppercase ${run.status === 'completed' ? 'bg-emerald-50 text-emerald-600' : run.status === 'running' ? 'bg-cyan-50 text-cyan-600' : 'bg-red-50 text-red-600'}`}>
                            {run.status === 'completed' ? <CheckCircle2 className="w-2.5 h-2.5" /> : run.status === 'running' ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <XCircle className="w-2.5 h-2.5" />}
                            {run.status}
                          </span>
                          <span className="text-[10px] text-black/30">{run.trigger_type === 'manual' ? (isZh ? '手动触发' : 'manual') : (isZh ? '定时任务' : 'scheduled')}</span>
                        </div>
                        <p className="text-[11px] text-black/35 mt-1">{run.started_at ? new Date(run.started_at).toLocaleString(isZh ? 'zh-CN' : 'en-US', { hour12: false }) : '-'}</p>
                      </div>
                      <div className="shrink-0 flex items-center gap-3">
                        <div className="flex items-center gap-1 text-[10px] font-bold">
                          <span className="w-5 text-center text-emerald-600">{run.healthy_count}</span>
                          <span className="text-black/15">/</span>
                          <span className="w-5 text-center text-amber-500">{run.warning_count}</span>
                          <span className="text-black/15">/</span>
                          <span className="w-5 text-center text-red-500">{run.critical_count}</span>
                        </div>
                        <div className="w-10 h-10 rounded-lg bg-slate-50 flex items-center justify-center group-hover:bg-cyan-50 transition-colors">
                          <span className="text-sm font-bold tabular-nums text-[#0b2340]">{run.avg_health_score ?? '—'}</span>
                        </div>
                      </div>
                    </div>
                  </button>
                )) : (
                  <div className="rounded-xl border-2 border-dashed border-black/[0.06] p-8 text-center">
                    <Zap className="w-6 h-6 text-black/15 mx-auto mb-2" />
                    <p className="text-sm text-black/35">{isZh ? '暂无巡检记录' : 'No runs yet'}</p>
                    <p className="text-[11px] text-black/25 mt-0.5">{isZh ? '点击「立即巡检」启动首次检查' : 'Click "Run Inspection" to start'}</p>
                  </div>
                )}
              </div>
            </div>

            {/* High-Risk Devices */}
            <div className="rounded-2xl border border-black/[0.06] bg-white shadow-sm overflow-hidden">
              <div className="px-5 pt-4 pb-3 flex items-center gap-2.5">
                <div className="w-7 h-7 rounded-lg bg-red-50 flex items-center justify-center"><AlertTriangle className="w-3.5 h-3.5 text-red-500" /></div>
                <h3 className="text-sm font-bold text-[#0b2340]">{isZh ? '高风险设备' : 'High-Risk Devices'}</h3>
                {riskyDevices.length > 0 && <span className="ml-auto text-[10px] font-bold rounded-full bg-red-50 text-red-600 px-2 py-0.5">{riskyDevices.length}</span>}
              </div>
              <div className="px-4 pb-4 space-y-2">
                {riskyDevices.length > 0 ? riskyDevices.map((device) => (
                  <button
                    key={device.id}
                    type="button"
                    onClick={() => onShowDetails(device)}
                    className="w-full group rounded-xl border border-black/[0.06] px-4 py-3 text-left transition-all hover:border-red-200/80 hover:shadow-sm"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-semibold text-[#0b2340] truncate">{device.hostname || device.ip_address}</p>
                        <p className="text-[11px] text-black/35 truncate mt-0.5">{[device.site, device.role, device.platform].filter(Boolean).join(' · ')}</p>
                      </div>
                      <div className="shrink-0 flex items-center gap-2.5">
                        <span className={`inline-flex rounded-md px-2 py-0.5 text-[10px] font-bold uppercase ${statusToneMap[device.health_status || 'unknown'] || statusToneMap.unknown}`}>
                          {device.health_status === 'critical' ? (isZh ? '严重' : 'CRIT') : device.health_status === 'warning' ? (isZh ? '告警' : 'WARN') : device.health_status || 'N/A'}
                        </span>
                        <div className="w-9 h-9 rounded-lg bg-slate-50 flex items-center justify-center group-hover:bg-red-50 transition-colors">
                          <span className="text-sm font-bold tabular-nums text-[#0b2340]">{Number(device.health_score || 0)}</span>
                        </div>
                      </div>
                    </div>
                  </button>
                )) : (
                  <div className="rounded-xl border-2 border-dashed border-black/[0.06] p-8 text-center">
                    <Shield className="w-6 h-6 text-emerald-300 mx-auto mb-2" />
                    <p className="text-sm text-black/35">{isZh ? '所有设备状态正常' : 'All devices healthy'}</p>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ═══════ SUB-TAB: RECORDS ═══════ */}
      {subTab === 'records' && !selectedRunDetail && (
        <div className="space-y-4">
          {/* Toolbar */}
          <div className="flex items-center gap-3">
            <div className="relative flex-1 max-w-sm">
              <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-black/25" />
              <input
                type="text"
                placeholder={isZh ? '搜索巡检记录…' : 'Search runs...'}
                value={recordSearch}
                onChange={(e) => setRecordSearch(e.target.value)}
                className="w-full pl-10 pr-3 py-2.5 rounded-xl border border-black/[0.08] text-sm bg-white placeholder:text-black/30 focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all"
              />
            </div>
            <button onClick={fetchRuns} className="p-2.5 rounded-xl border border-black/[0.08] hover:bg-black/[0.02] transition-all" title="Refresh">
              <RefreshCw className={`w-4 h-4 text-black/35 ${runsLoading ? 'animate-spin' : ''}`} />
            </button>
          </div>

          {/* Table */}
          <div className="rounded-2xl border border-black/[0.06] bg-white shadow-sm overflow-hidden min-h-[500px] flex flex-col">
            <div className="overflow-y-auto max-h-[calc(100vh-380px)] custom-scrollbar">
              <table className="w-full text-left text-sm">
                <thead className="sticky top-0 bg-slate-50 border-b border-black/[0.05] z-10">
                  <tr>
                    <Th>{isZh ? '时间' : 'Time'}</Th>
                    <Th>{isZh ? '类型' : 'Type'}</Th>
                    <Th>{isZh ? '范围' : 'Scope'}</Th>
                    <Th>{isZh ? '状态' : 'Status'}</Th>
                    <Th>{isZh ? '设备' : 'Devices'}</Th>
                    <Th>{isZh ? '健康/告警/严重' : 'H / W / C'}</Th>
                    <Th>{isZh ? '平均分' : 'Avg'}</Th>
                    <Th>{isZh ? '操作人' : 'By'}</Th>
                    <Th className="w-10"></Th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-black/[0.04]">
                  {filteredRuns.map((run) => (
                    <tr
                      key={run.id}
                      className="group hover:bg-cyan-50/30 cursor-pointer transition-colors"
                      onClick={() => fetchRunDetail(run.id)}
                    >
                      <td className="px-4 py-3 text-[12px] text-black/55 whitespace-nowrap">{run.started_at ? new Date(run.started_at).toLocaleString(isZh ? 'zh-CN' : 'en-US', { hour12: false }) : '-'}</td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex rounded-md px-2 py-0.5 text-[10px] font-bold uppercase ${run.trigger_type === 'manual' ? 'bg-blue-50 text-blue-600' : 'bg-violet-50 text-violet-600'}`}>
                          {run.trigger_type === 'manual' ? (isZh ? '手动' : 'Manual') : (isZh ? '定时' : 'Sched')}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-[12px] text-black/45">{run.scope_type}{run.scope_filter ? `: ${run.scope_filter}` : ''}</td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-bold uppercase ${run.status === 'completed' ? 'bg-emerald-50 text-emerald-600' : run.status === 'running' ? 'bg-cyan-50 text-cyan-600' : 'bg-red-50 text-red-600'}`}>
                          {run.status === 'completed' && <CheckCircle2 className="w-2.5 h-2.5" />}
                          {run.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-semibold tabular-nums text-[13px]">{run.total_devices}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5 text-[11px] font-bold tabular-nums">
                          <span className="text-emerald-600">{run.healthy_count}</span>
                          <span className="text-black/15">/</span>
                          <span className="text-amber-500">{run.warning_count}</span>
                          <span className="text-black/15">/</span>
                          <span className="text-red-500">{run.critical_count}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3 font-bold tabular-nums text-[13px] text-[#0b2340]">{run.avg_health_score ?? '—'}</td>
                      <td className="px-4 py-3 text-[12px] text-black/40">{run.created_by}</td>
                      <td className="px-4 py-3">
                        <Eye className="w-3.5 h-3.5 text-black/20 group-hover:text-cyan-500 transition-colors" />
                      </td>
                    </tr>
                  ))}
                  {filteredRuns.length === 0 && (
                    <tr>
                      <td colSpan={9} className="px-4 py-12 text-center">
                        <Clock className="w-6 h-6 text-black/15 mx-auto mb-2" />
                        <p className="text-sm text-black/35">{runsLoading ? (isZh ? '加载中...' : 'Loading...') : (isZh ? '暂无巡检记录' : 'No inspection runs found')}</p>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            {/* Pagination */}
            <div className="mt-auto px-4 py-3 border-t border-black/[0.04]">
              <Pagination
                currentPage={recordPage}
                totalItems={recordTotal}
                itemsPerPage={recordPageSize}
                onPageChange={setRecordPage}
                onItemsPerPageChange={(size) => { setRecordPageSize(size); setRecordPage(1); }}
                language={language}
              />
            </div>
          </div>
        </div>
      )}

      {/* ═══════ RECORDS: Run Detail ═══════ */}
      {subTab === 'records' && selectedRunDetail && (
        <div className="space-y-5">
          <button
            onClick={() => setSelectedRunDetail(null)}
            className="flex items-center gap-1.5 text-sm text-cyan-600 hover:text-cyan-800 font-medium transition-colors"
          >
            <ChevronRight className="w-3.5 h-3.5 rotate-180" />
            {isZh ? '返回列表' : 'Back to list'}
          </button>

          {detailLoading ? (
            <div className="flex items-center justify-center h-40 text-black/35"><Loader2 className="w-5 h-5 animate-spin mr-2" />{isZh ? '加载中...' : 'Loading...'}</div>
          ) : (
            <>
              {/* Run Summary Banner */}
              <div className="rounded-2xl border border-black/[0.06] bg-white shadow-sm p-5">
                <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-4">
                  <div className="flex items-center gap-4">
                    <ScoreGauge score={selectedRunDetail.avg_health_score} size={64} />
                    <div>
                      <h3 className="text-base font-bold text-[#0b2340]">{isZh ? '巡检详情' : 'Inspection Detail'}</h3>
                      <p className="text-[11px] text-black/35 mt-0.5">{selectedRunDetail.started_at ? new Date(selectedRunDetail.started_at).toLocaleString(isZh ? 'zh-CN' : 'en-US', { hour12: false }) : ''}</p>
                    </div>
                  </div>
                  <span className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-bold uppercase ${selectedRunDetail.status === 'completed' ? 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200' : 'bg-red-50 text-red-700 ring-1 ring-red-200'}`}>
                    {selectedRunDetail.status === 'completed' && <CheckCircle2 className="w-3.5 h-3.5" />}
                    {selectedRunDetail.status}
                  </span>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {([
                    { label: isZh ? '总设备' : 'Total', value: selectedRunDetail.total_devices, bg: 'bg-slate-50', text: 'text-slate-700' },
                    { label: isZh ? '健康' : 'Healthy', value: selectedRunDetail.healthy_count, bg: 'bg-emerald-50', text: 'text-emerald-700' },
                    { label: isZh ? '告警' : 'Warning', value: selectedRunDetail.warning_count, bg: 'bg-amber-50', text: 'text-amber-700' },
                    { label: isZh ? '严重' : 'Critical', value: selectedRunDetail.critical_count, bg: 'bg-red-50', text: 'text-red-700' },
                  ] as const).map((s) => (
                    <div key={s.label} className={`${s.bg} rounded-xl p-3 text-center`}>
                      <p className={`text-[10px] font-bold uppercase tracking-wider ${s.text} opacity-60`}>{s.label}</p>
                      <p className={`text-xl font-bold tabular-nums mt-1 ${s.text}`}>{s.value}</p>
                    </div>
                  ))}
                </div>
              </div>

              {/* Device Results — grouped by category */}
              {(() => {
                const allResults = selectedRunDetail.results || [];
                const networkResults = allResults.filter(r => isNetworkDevice(r.role, r.platform));
                const serverResults = allResults.filter(r => !isNetworkDevice(r.role, r.platform));
                const groups = [
                  { key: 'network', label: isZh ? '网络设备' : 'Network Devices', icon: <Wifi className="w-3.5 h-3.5 text-cyan-600" />, items: networkResults, bg: 'bg-cyan-50', iconBg: 'bg-cyan-50' },
                  { key: 'server', label: isZh ? '服务器 / 主机' : 'Servers / Hosts', icon: <Cpu className="w-3.5 h-3.5 text-violet-600" />, items: serverResults, bg: 'bg-violet-50', iconBg: 'bg-violet-50' },
                ].filter(g => g.items.length > 0);

                const renderResultTable = (results: InspectionResult[]) => (
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-sm">
                      <thead className="sticky top-0 bg-slate-50/95 backdrop-blur border-b border-black/[0.05] z-10">
                        <tr>
                          <Th>{isZh ? '设备' : 'Device'}</Th>
                          <Th>Ping</Th>
                          <Th>SSH</Th>
                          <Th>{isZh ? '状态' : 'Health'}</Th>
                          <Th>{isZh ? '评分' : 'Score'}</Th>
                          <Th>CPU</Th>
                          <Th>{isZh ? '内存' : 'Mem'}</Th>
                          <Th>{isZh ? '接口' : 'IF'}</Th>
                          <Th>{isZh ? '发现' : 'Findings'}</Th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-black/[0.04]">
                        {results.map((r) => {
                          let findings: { severity: string; message: string }[] = [];
                          try { findings = JSON.parse(r.findings_json || '[]'); } catch { /* ignore */ }
                          return (
                            <tr key={r.id} className="hover:bg-slate-50/50 transition-colors">
                              <td className="px-4 py-3">
                                <div className="font-semibold text-[#0b2340] text-[13px]">{r.hostname || '-'}</div>
                                <div className="text-[11px] font-mono text-black/30">{r.ip_address}</div>
                              </td>
                              <td className="px-4 py-3">
                                {r.ping_ok ? (
                                  <span className="inline-flex items-center gap-1 text-emerald-600 text-xs font-semibold"><Wifi className="w-3 h-3" />{r.ping_latency_ms != null ? `${r.ping_latency_ms}ms` : 'OK'}</span>
                                ) : (
                                  <span className="inline-flex items-center gap-1 text-red-500 text-xs font-semibold"><WifiOff className="w-3 h-3" />{isZh ? '不可达' : 'Down'}</span>
                                )}
                              </td>
                              <td className="px-4 py-3">
                                {r.ssh_ok ? (
                                  <span className="inline-flex items-center gap-1 text-emerald-600 text-xs font-semibold"><CheckCircle2 className="w-3 h-3" />OK</span>
                                ) : (
                                  <span className="inline-flex items-center gap-1 text-red-500 text-xs font-semibold" title={r.ssh_error}><XCircle className="w-3 h-3" />{isZh ? '失败' : 'Fail'}</span>
                                )}
                              </td>
                              <td className="px-4 py-3">
                                <span className={`inline-flex rounded-md px-2 py-0.5 text-[10px] font-bold uppercase ${statusToneMap[r.health_status] || statusToneMap.unknown}`}>{r.health_status}</span>
                              </td>
                              <td className="px-4 py-3 font-bold tabular-nums text-[13px]">{r.health_score ?? '—'}</td>
                              <td className="px-4 py-3 tabular-nums text-[12px] text-black/55">{r.cpu_usage != null ? `${r.cpu_usage.toFixed(0)}%` : '-'}</td>
                              <td className="px-4 py-3 tabular-nums text-[12px] text-black/55">{r.memory_usage != null ? `${r.memory_usage.toFixed(0)}%` : '-'}</td>
                              <td className="px-4 py-3 text-[11px]">
                                <span className="text-emerald-600 font-semibold">{r.interface_up}↑</span>
                                {r.interface_down > 0 && <span className="text-black/30 font-semibold ml-1.5">{r.interface_down}↓</span>}
                              </td>
                              <td className="px-4 py-3 max-w-[320px]">
                                {findings.length > 0 ? (
                                  <div className="flex flex-wrap gap-1">
                                    {findings.slice(0, 4).map((f, i) => (
                                      <span key={i} className={`inline-flex rounded-md px-1.5 py-0.5 text-[9px] font-semibold ${f.severity === 'critical' ? 'bg-red-50 text-red-700' : f.severity === 'warning' ? 'bg-amber-50 text-amber-700' : 'bg-slate-50 text-slate-600'}`}>
                                        {f.message}
                                      </span>
                                    ))}
                                    {findings.length > 4 && <span className="text-[10px] text-black/25">+{findings.length - 4}</span>}
                                  </div>
                                ) : (
                                  <span className="inline-flex items-center gap-1 text-[11px] text-emerald-500"><CheckCircle2 className="w-3 h-3" />{isZh ? '正常' : 'OK'}</span>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                );

                return (
                  <div className="space-y-4">
                    {groups.map(g => (
                      <div key={g.key} className="rounded-2xl border border-black/[0.06] bg-white shadow-sm overflow-hidden">
                        <div className="px-5 py-3 border-b border-black/[0.04] flex items-center gap-2.5">
                          <div className={`w-7 h-7 rounded-lg ${g.iconBg} flex items-center justify-center`}>{g.icon}</div>
                          <h4 className="text-sm font-bold text-[#0b2340]">{g.label}</h4>
                          <span className="text-[11px] text-black/30 font-semibold tabular-nums">{g.items.length} {isZh ? '台' : ''}</span>
                        </div>
                        <div className="max-h-[500px] overflow-y-auto custom-scrollbar">
                          {renderResultTable(g.items.slice((detailPage - 1) * detailPageSize, detailPage * detailPageSize))}
                        </div>
                        {g.items.length > detailPageSize && (
                          <div className="px-4 py-3 border-t border-black/[0.04]">
                            <Pagination
                              currentPage={detailPage}
                              totalItems={g.items.length}
                              itemsPerPage={detailPageSize}
                              onPageChange={setDetailPage}
                              onItemsPerPageChange={setDetailPageSize}
                              language={language}
                            />
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                );
              })()}
            </>
          )}
        </div>
      )}

    </div>
  );
};

export default InspectionTab;
