import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, AlertTriangle, ArrowRight, CheckCircle2, ChevronRight, ClipboardCheck, Clock, Cpu, Download, Eye, FileText, Loader2, Play, RefreshCw, Search, Server, Shield, Wifi, WifiOff, X, XCircle, Zap, BarChart3, CalendarClock, ExternalLink, HardDrive, Layers } from 'lucide-react';
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { Device, DeviceHealthHistoryResponse, DeviceHealthOverview } from '../types';
import { authHeaders as apiAuthHeaders } from '../api/http';
import { useChartTheme } from '../hooks/useChartTheme';
import { ActionButton, ActionIconButton, ActionIconGroup } from '../components/ui/ActionIconButton';
import { useSystem } from '../hooks/useSystem';
import Pagination from '../components/Pagination';
import PageHero from '../components/PageHero';
import {
  alertPanelClass,
  alertSecondaryButtonClass,
} from './alertManagementShared';

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
  fan_status: boolean | 0 | 1 | string | null;
  psu_status: boolean | 0 | 1 | string | null;
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
  metrics_json: string;
  analysis_json: string;
  raw_outputs_json: string;
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
const Th: React.FC<{ children?: React.ReactNode; className?: string }> = ({ children, className = '' }) => (
  <th className={`px-4 py-3 text-[10px] font-bold uppercase tracking-[0.12em] text-black/35 whitespace-nowrap ${className}`}>{children}</th>
);

/* ────────────────────────────────────────── */
/* Component                                  */
/* ────────────────────────────────────────── */

const InspectionTab: React.FC<InspectionTabProps> = ({ language, devices, overview, onShowDetails, initialView }) => {
  const { systemInfo } = useSystem();
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
  const [recordPageSize, setRecordPageSize] = useState(10);
  const [recordTotal, setRecordTotal] = useState(0);
  const [exportingReportId, setExportingReportId] = useState<string | null>(null);

  /* ─── token helper ─── */
  const authHeaders = useMemo(() => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' };
  }, []);

  /* ─── data fetchers ─── */

  const fetchHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const resp = await fetch(`/api/device-health/history?range_hours=${rangeHours}`, { headers: apiAuthHeaders() });
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
        const items = Array.isArray(d) ? d : Array.isArray(d?.items) ? d.items : [];
        setRuns(items);
        setRecordTotal(typeof d?.total === 'number' ? d.total : items.length);
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

  /* ─── Export records ─── */

  const handleExportRecords = async () => {
    try {
      const allRecords: InspectionRun[] = [];
      let offset = 0;
      const limit = 100;
      
      while (true) {
        const resp = await fetch(`/api/inspections?limit=${limit}&offset=${offset}`, { headers: authHeaders });
        if (!resp.ok) break;
        const json = await resp.json();
        const items = Array.isArray(json.data?.items) ? json.data.items : Array.isArray(json.data) ? json.data : [];
        if (!items.length) break;
        allRecords.push(...items);
        if (items.length < limit) break;
        offset += limit;
      }

      if (!allRecords.length) {
        alert(isZh ? '暂无巡检记录可导出' : 'No inspection records to export');
        return;
      }

      const headers = isZh 
        ? ['执行批次ID', '触发方式', '范围类型', '范围过滤', '状态', '开始时间', '完成时间', '设备总数', '成功数', '失败数', '不可达数', '健康数', '告警数', '严重数', '平均得分', '创建人']
        : ['Run ID', 'Trigger Type', 'Scope Type', 'Scope Filter', 'Status', 'Started At', 'Completed At', 'Total Devices', 'Success', 'Failed', 'Unreachable', 'Healthy', 'Warning', 'Critical', 'Avg Score', 'Created By'];

      const rows = allRecords.map(r => [
        r.id,
        r.trigger_type,
        r.scope_type,
        r.scope_filter || '-',
        r.status,
        r.started_at,
        r.completed_at || '-',
        r.total_devices,
        r.success_count,
        r.failed_count,
        r.unreachable_count,
        r.healthy_count,
        r.warning_count,
        r.critical_count,
        r.avg_health_score ?? '-',
        r.created_by
      ]);

      const csvContent = '\uFEFF' + [
        headers.join(','),
        ...rows.map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(','))
      ].join('\n');

      const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.setAttribute('href', url);
      link.setAttribute('download', `inspection_runs_${new Date().toISOString().slice(0, 10)}.csv`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    } catch (e) {
      console.error('Export failed:', e);
      alert(isZh ? '导出失败' : 'Export failed');
    }
  };

  const downloadReport = async (runId: string, format: 'excel' | 'pdf' | 'html' | 'json') => {
    setExportingReportId(runId);
    try {
      const resp = await fetch(`/api/inspections/${runId}/report/${format}`, { headers: authHeaders });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      const ext = format === 'excel' ? 'xlsx' : format;
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `inspection_report_${runId.slice(0, 8)}_${new Date().toISOString().slice(0, 10)}.${ext}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Download failed:', err);
      alert(isZh ? '报表下载失败' : 'Report download failed');
    } finally {
      setExportingReportId(null);
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

  /* ─────────────────────────────────────── */
  /* Render                                   */
  /* ─────────────────────────────────────── */

  return (
    <div className="flex-1 flex flex-col overflow-hidden min-h-0">
      {/* ── Page Hero Header ── */}
      <PageHero
        icon={subTab === 'overview' ? ClipboardCheck : FileText}
        title={
          subTab === 'overview'
            ? (isZh ? '巡检健康概览' : 'Inspection Overview')
            : (isZh ? '巡检记录与报告' : 'Inspection Records & Reports')
        }
        subtitle={
          subTab === 'overview'
            ? (isZh ? '全网设备健康评分、异常隐患雷达与运行健康走势分析' : 'Fleet health score, risk radar, and health score trends over time')
            : (isZh ? '审计历史巡检执行批次、单设备检查明细及一键下载巡检报告' : 'Audit historical inspection runs, per-device check details, and export reports')
        }
        actions={
          <div className="flex items-center gap-2">
            {subTab === 'records' && (
              <button
                onClick={handleExportRecords}
                className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold bg-[#06b6d4] hover:bg-[#0891b2] text-white transition-all shadow-md shadow-cyan-500/20"
              >
                <Download size={13} />
                {isZh ? '导出巡检台账' : 'Export CSV'}
              </button>
            )}
            <a
              href="/automation/scheduled-jobs"
              className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-bold bg-[#00172d] text-white hover:bg-[#00284f] transition-all shadow-md"
            >
              <CalendarClock size={13} className="text-cyan-400" />
              {isZh ? '配置定时巡检' : 'Scheduled Jobs'}
            </a>
            <button
              onClick={() => { fetchHistory(); fetchRecentRuns(); if (subTab === 'records') fetchRuns(); }}
              className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium border border-black/10 dark:border-white/10 hover:bg-black/5 dark:hover:bg-white/5 transition-all text-slate-700 dark:text-slate-300 bg-white dark:bg-slate-900"
            >
              <RefreshCw size={13} className={historyLoading || runsLoading ? 'animate-spin' : ''} />
              {isZh ? '刷新' : 'Refresh'}
            </button>
          </div>
        }
      />

      <div className="flex-1 flex flex-col overflow-hidden px-6 py-5 space-y-4 min-h-0">
        
        {/* ═══════ Hero gauge strip (ONLY on Overview mode) ═══════ */}
        {subTab === 'overview' && (
          <div className="relative rounded-2xl overflow-hidden bg-gradient-to-r from-[#0c1e35] via-[#0e2942] to-[#0a3455] p-5 shadow-lg shrink-0">
            <div className="absolute inset-0 opacity-[0.04]" style={{ backgroundImage: 'radial-gradient(circle, white 1px, transparent 1px)', backgroundSize: '18px 18px' }} />
            <div className="relative flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
              <div className="flex items-center gap-5">
                <ScoreGauge score={typeof avgScore === 'number' ? Math.round(avgScore) : null} size={76} />
                <div>
                  <h2 className="text-white/90 text-lg font-bold tracking-tight">{isZh ? '网络运行健康总览' : 'Network Health Overview'}</h2>
                  <div className="flex items-center gap-3 mt-2">
                    {([
                      { label: isZh ? '受管设备' : 'Devices', value: overview?.total_devices ?? devices.length, cls: 'bg-white/10 text-white/80' },
                      { label: isZh ? '正常' : 'Healthy', value: overview?.healthy ?? 0, cls: 'bg-emerald-500/20 text-emerald-300' },
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

              <div className="flex items-center gap-2">
                <button
                  onClick={() => setSubTab('records')}
                  className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl text-xs font-bold bg-white/10 hover:bg-white/20 text-white transition-all backdrop-blur-sm border border-white/10"
                >
                  <Clock size={14} className="text-cyan-400" />
                  {isZh ? '查看全部巡检流水' : 'View All Records'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ═══════ Main Content Area ═══════ */}
        <div className={`${alertPanelClass} flex-1 min-h-0 flex flex-col overflow-hidden`}>
          {/* Navigation Tabs (Only when NOT driven by sidebar navigation) */}
          {!initialView && (
            <div className="flex items-center gap-1.5 border-b border-black/5 px-5 py-3 shrink-0 bg-slate-50/50 dark:bg-slate-900/30">
              {[
                { key: 'overview', label: isZh ? '健康总览' : 'Overview', icon: <BarChart3 className="w-3.5 h-3.5" /> },
                { key: 'records', label: isZh ? '巡检流水与报告' : 'Records & Reports', icon: <Clock className="w-3.5 h-3.5" /> },
              ].map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => { setSubTab(tab.key as SubTab); setSelectedRunDetail(null); }}
                  className={`flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-bold transition-all ${
                    subTab === tab.key
                      ? 'bg-[#00172d] text-white shadow-md'
                      : 'text-slate-500 hover:bg-black/5 hover:text-slate-800'
                  }`}
                >
                  {tab.icon}
                  {tab.label}
                </button>
              ))}
            </div>
          )}

          {/* ═══════ SUB-TAB: Overview ═══════ */}
          {subTab === 'overview' && (
            <div className="flex-1 overflow-y-auto p-5 space-y-5">
              {/* Chart + Risky Devices grid */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
                {/* Health history chart (2 cols) */}
                <div className="lg:col-span-2 rounded-2xl border border-black/5 dark:border-white/5 bg-white dark:bg-[#111827] p-5 shadow-sm space-y-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-sm font-bold text-[#0b2340] dark:text-white flex items-center gap-2">
                        <Activity className="w-4 h-4 text-cyan-500" />
                        {isZh ? '健康度趋势走势' : 'Health Score Trend'}
                      </h3>
                      <p className="text-[11px] text-slate-400 mt-0.5">{isZh ? '统计时间窗口内的全网健康评分与正常设备数量变化' : 'Average score and healthy device counts over time'}</p>
                    </div>
                    <div className="flex items-center gap-1 bg-slate-100 dark:bg-slate-800 p-1 rounded-xl">
                      {[
                        { hours: 12, label: '12h' },
                        { hours: 24, label: '24h' },
                        { hours: 72, label: '3d' },
                        { hours: 168, label: '7d' },
                      ].map((btn) => (
                        <button
                          key={btn.hours}
                          onClick={() => setRangeHours(btn.hours)}
                          className={`rounded-lg px-2.5 py-1 text-[11px] font-semibold transition-all ${
                            rangeHours === btn.hours
                              ? 'bg-white dark:bg-slate-700 text-[#0b2340] dark:text-white shadow-sm font-bold'
                              : 'text-slate-400 hover:text-slate-700'
                          }`}
                        >
                          {btn.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="h-64 w-full">
                    {historyLoading ? (
                      <div className="h-full flex items-center justify-center text-xs text-slate-400">
                        <Loader2 className="w-5 h-5 animate-spin mr-2 text-cyan-500" />
                        {isZh ? '加载趋势数据中...' : 'Loading trend data...'}
                      </div>
                    ) : historySeries.length === 0 ? (
                      <div className="h-full flex items-center justify-center text-xs text-slate-400">
                        {isZh ? '暂无历史趋势数据' : 'No history data available'}
                      </div>
                    ) : (
                      <ResponsiveContainer width="100%" height="100%">
                        <ComposedChart data={historySeries} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} vertical={false} />
                          <XAxis dataKey="timestamp" stroke={ct.axis} tick={{ fill: ct.textMuted, fontSize: 10 }} tickFormatter={(ts) => ts.slice(11, 16)} />
                          <YAxis yAxisId="score" domain={[0, 100]} stroke={ct.axis} tick={{ fill: ct.textMuted, fontSize: 10 }} />
                          <YAxis yAxisId="count" orientation="right" stroke={ct.axis} tick={{ fill: ct.textMuted, fontSize: 10 }} />
                          <Tooltip
                            contentStyle={{ background: ct.tooltipBg, border: `1px solid ${ct.tooltipBorder}`, borderRadius: '12px', fontSize: '11px' }}
                            formatter={(value: any, name: string) => [
                              value,
                              name === 'average_score' ? (isZh ? '平均得分' : 'Avg Score') : (isZh ? '健康设备数' : 'Healthy Devices'),
                            ]}
                            labelFormatter={(label) => `${isZh ? '时间' : 'Time'}: ${label}`}
                          />
                          <Bar yAxisId="count" dataKey="healthy_count" fill="#10b981" opacity={0.3} radius={[4, 4, 0, 0]} maxBarSize={20} />
                          <Line yAxisId="score" type="monotone" dataKey="average_score" stroke="#06b6d4" strokeWidth={2.5} dot={false} activeDot={{ r: 4 }} />
                        </ComposedChart>
                      </ResponsiveContainer>
                    )}
                  </div>
                </div>

                {/* Top Risky Devices (1 col) */}
                <div className="rounded-2xl border border-black/5 dark:border-white/5 bg-white dark:bg-[#111827] p-5 shadow-sm space-y-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-sm font-bold text-[#0b2340] dark:text-white flex items-center gap-2">
                        <AlertTriangle className="w-4 h-4 text-amber-500" />
                        {isZh ? '重点隐患设备' : 'Top Risky Devices'}
                      </h3>
                      <p className="text-[11px] text-slate-400 mt-0.5">{isZh ? '当前处于严重或告警状态的设备' : 'Devices in warning or critical state'}</p>
                    </div>
                  </div>

                  <div className="space-y-2 max-h-72 overflow-y-auto">
                    {riskyDevices.length === 0 ? (
                      <div className="py-12 text-center text-xs text-slate-400">
                        <CheckCircle2 className="w-8 h-8 text-emerald-500 mx-auto mb-2 opacity-80" />
                        {isZh ? '太棒了，全网暂无高风险设备！' : 'All devices healthy!'}
                      </div>
                    ) : (
                      riskyDevices.map((dev) => {
                        const tone = statusToneMap[dev.health_status] || statusToneMap.unknown;
                        return (
                          <div
                            key={dev.id}
                            onClick={() => onShowDetails(dev)}
                            className="p-3 rounded-xl border border-black/5 dark:border-white/5 hover:border-cyan-200 dark:hover:border-cyan-800 transition-all cursor-pointer bg-slate-50/50 dark:bg-slate-900/50 flex items-center justify-between group"
                          >
                            <div className="min-w-0 pr-2">
                              <div className="text-xs font-bold text-slate-800 dark:text-slate-200 truncate group-hover:text-cyan-600 transition-colors">
                                {dev.hostname || dev.ip_address}
                              </div>
                              <div className="text-[10px] text-slate-400 font-mono truncate mt-0.5">
                                {dev.ip_address} · {dev.platform || 'generic'}
                              </div>
                            </div>
                            <div className="flex items-center gap-2 shrink-0">
                              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${tone}`}>
                                {dev.health_status}
                              </span>
                              <span className="text-xs font-bold font-mono text-slate-700 dark:text-slate-300">
                                {dev.health_score ?? '—'}
                              </span>
                            </div>
                          </div>
                        );
                      })
                    )}
                  </div>
                </div>
              </div>

              {/* Recent Inspection Runs Summary */}
              <div className="rounded-2xl border border-black/5 dark:border-white/5 bg-white dark:bg-[#111827] p-5 shadow-sm space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-bold text-[#0b2340] dark:text-white flex items-center gap-2">
                      <Clock className="w-4 h-4 text-cyan-500" />
                      {isZh ? '最近巡检批次概况' : 'Recent Inspection Runs'}
                    </h3>
                    <p className="text-[11px] text-slate-400 mt-0.5">{isZh ? '最近完成的巡检批次与健康汇总' : 'Latest completed inspection executions'}</p>
                  </div>
                  <button
                    onClick={() => setSubTab('records')}
                    className="text-xs font-bold text-cyan-600 hover:text-cyan-700 flex items-center gap-1"
                  >
                    {isZh ? '查看完整流水记录' : 'View Full History'}
                    <ChevronRight size={13} />
                  </button>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-left">
                    <thead>
                      <tr className="border-b border-black/5 dark:border-white/5">
                        <Th>{isZh ? '批次 ID' : 'Run ID'}</Th>
                        <Th>{isZh ? '触发类型' : 'Trigger'}</Th>
                        <Th>{isZh ? '范围' : 'Scope'}</Th>
                        <Th>{isZh ? '设备总数' : 'Devices'}</Th>
                        <Th>{isZh ? '健康分布' : 'Healthy / Warn / Crit'}</Th>
                        <Th>{isZh ? '平均得分' : 'Avg Score'}</Th>
                        <Th>{isZh ? '执行时间' : 'Time'}</Th>
                        <Th className="text-right">{isZh ? '操作' : 'Actions'}</Th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-black/[0.03] dark:divide-white/[0.03] text-xs">
                      {recentRuns.length === 0 ? (
                        <tr>
                          <td colSpan={8} className="py-8 text-center text-slate-400 text-xs">
                            {isZh ? '暂无巡检记录' : 'No inspection runs found'}
                          </td>
                        </tr>
                      ) : (
                        recentRuns.map((run) => (
                          <tr key={run.id} className="hover:bg-black/[0.01] dark:hover:bg-white/[0.01] transition-colors">
                            <td className="px-4 py-3 font-mono text-[11px] font-bold text-slate-700 dark:text-slate-300">
                              {run.id.slice(0, 8)}...
                            </td>
                            <td className="px-4 py-3">
                              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">
                                {run.trigger_type}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-slate-600 dark:text-slate-400 text-[11px]">
                              {run.scope_type}: {run.scope_filter || (isZh ? '全部' : 'all')}
                            </td>
                            <td className="px-4 py-3 font-bold font-mono text-slate-800 dark:text-slate-200">
                              {run.total_devices}
                            </td>
                            <td className="px-4 py-3 font-mono text-[11px]">
                              <span className="text-emerald-600 font-semibold">{run.healthy_count}</span> /{' '}
                              <span className="text-amber-600 font-semibold">{run.warning_count}</span> /{' '}
                              <span className="text-red-600 font-semibold">{run.critical_count}</span>
                            </td>
                            <td className="px-4 py-3 font-mono font-bold text-slate-800 dark:text-slate-200">
                              {run.avg_health_score ?? '—'}
                            </td>
                            <td className="px-4 py-3 text-slate-400 text-[11px] whitespace-nowrap">
                              {run.started_at?.replace('T', ' ').slice(0, 19) || '-'}
                            </td>
                            <td className="px-4 py-3 text-right">
                              <button
                                onClick={() => {
                                  setSubTab('records');
                                  fetchRunDetail(run.id);
                                }}
                                className="text-xs font-semibold text-cyan-600 hover:text-cyan-700 px-2 py-1 rounded-lg hover:bg-cyan-50 dark:hover:bg-cyan-950 transition-colors"
                              >
                                {isZh ? '明细与报告' : 'Detail & Report'}
                              </button>
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* ═══════ SUB-TAB: Records ═══════ */}
          {subTab === 'records' && (
            <div className="flex-1 flex flex-col min-h-0 overflow-hidden p-5 space-y-4">
              {/* Toolbar */}
              <div className="flex flex-wrap items-center justify-between gap-3 shrink-0">
                <div className="relative w-72">
                  <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input
                    type="text"
                    value={recordSearch}
                    onChange={(e) => setRecordSearch(e.target.value)}
                    placeholder={isZh ? '搜索批次 ID、触发类型、范围...' : 'Search runs by ID, trigger, scope...'}
                    className="w-full pl-9 pr-3 py-2 rounded-xl border border-black/10 dark:border-white/10 text-xs bg-white dark:bg-slate-900 focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-500"
                  />
                </div>

                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-400 font-mono">
                    {isZh ? `共 ${recordTotal} 条批次记录` : `Total ${recordTotal} runs`}
                  </span>
                </div>
              </div>

              {/* Table */}
              <div className="flex-1 overflow-auto rounded-2xl border border-black/5 dark:border-white/5 bg-white dark:bg-[#111827]">
                <table className="w-full text-left">
                  <thead className="sticky top-0 bg-slate-50/90 dark:bg-slate-900/90 backdrop-blur-sm z-10">
                    <tr className="border-b border-black/5 dark:border-white/5">
                      <Th>{isZh ? '批次 ID' : 'Run ID'}</Th>
                      <Th>{isZh ? '触发方式' : 'Trigger'}</Th>
                      <Th>{isZh ? '设备范围' : 'Scope'}</Th>
                      <Th>{isZh ? '创建人 / 来源' : 'Created By'}</Th>
                      <Th>{isZh ? '设备总数' : 'Total'}</Th>
                      <Th>{isZh ? '健康分布 (正常/告警/严重)' : 'Healthy / Warn / Crit'}</Th>
                      <Th>{isZh ? '平均得分' : 'Avg Score'}</Th>
                      <Th>{isZh ? '开始时间' : 'Started At'}</Th>
                      <Th className="text-right">{isZh ? '操作与报告导出' : 'Actions & Export'}</Th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-black/[0.03] dark:divide-white/[0.03] text-xs">
                    {runsLoading ? (
                      <tr>
                        <td colSpan={9} className="py-16 text-center text-slate-400">
                          <Loader2 className="w-6 h-6 animate-spin mx-auto mb-2 text-cyan-500" />
                          {isZh ? '加载巡检记录中...' : 'Loading inspection runs...'}
                        </td>
                      </tr>
                    ) : filteredRuns.length === 0 ? (
                      <tr>
                        <td colSpan={9} className="py-16 text-center text-slate-400">
                          {isZh ? '未找到符合条件的巡检记录' : 'No inspection records found'}
                        </td>
                      </tr>
                    ) : (
                      filteredRuns.map((run) => (
                        <tr key={run.id} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors">
                          <td className="px-4 py-3 font-mono text-[11px] font-bold text-slate-700 dark:text-slate-300">
                            {run.id.slice(0, 8)}...
                          </td>
                          <td className="px-4 py-3">
                            <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">
                              {run.trigger_type}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-slate-600 dark:text-slate-400 text-[11px]">
                            {run.scope_type}: {run.scope_filter || (isZh ? '全部' : 'all')}
                          </td>
                          <td className="px-4 py-3 text-slate-600 dark:text-slate-400 text-[11px]">
                            {run.created_by || 'system'}
                          </td>
                          <td className="px-4 py-3 font-bold font-mono text-slate-800 dark:text-slate-200">
                            {run.total_devices}
                          </td>
                          <td className="px-4 py-3 font-mono text-[11px]">
                            <span className="text-emerald-600 font-semibold">{run.healthy_count}</span> /{' '}
                            <span className="text-amber-600 font-semibold">{run.warning_count}</span> /{' '}
                            <span className="text-red-600 font-semibold">{run.critical_count}</span>
                          </td>
                          <td className="px-4 py-3 font-mono font-bold text-slate-800 dark:text-slate-200">
                            {run.avg_health_score ?? '—'}
                          </td>
                          <td className="px-4 py-3 text-slate-400 text-[11px] whitespace-nowrap">
                            {run.started_at?.replace('T', ' ').slice(0, 19) || '-'}
                          </td>
                          <td className="px-4 py-3 text-right">
                            <div className="inline-flex items-center gap-1.5">
                              <button
                                onClick={() => fetchRunDetail(run.id)}
                                className="px-2.5 py-1 text-xs font-semibold rounded-lg bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 transition-colors"
                              >
                                {isZh ? '查看详情' : 'Details'}
                              </button>
                              <button
                                onClick={() => downloadReport(run.id, 'excel')}
                                disabled={exportingReportId === run.id}
                                className="p-1.5 text-xs rounded-lg text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-950 transition-colors"
                                title={isZh ? '下载 Excel 巡检报表' : 'Download Excel Report'}
                              >
                                <Download size={13} />
                              </button>
                              <button
                                onClick={() => downloadReport(run.id, 'pdf')}
                                disabled={exportingReportId === run.id}
                                className="p-1.5 text-xs rounded-lg text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950 transition-colors"
                                title={isZh ? '下载 PDF 巡检报表' : 'Download PDF Report'}
                              >
                                <FileText size={13} />
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              <div className="shrink-0">
                <Pagination
                  currentPage={recordPage}
                  totalItems={recordTotal}
                  itemsPerPage={recordPageSize}
                  onPageChange={setRecordPage}
                  onItemsPerPageChange={(v) => { setRecordPage(1); setRecordPageSize(v); }}
                  language={language}
                />
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ═══════ Drawer: Run Detail Modal ═══════ */}
      {selectedRunDetail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-150">
          <div className="bg-white dark:bg-[#0f172a] rounded-2xl border border-black/10 dark:border-white/10 shadow-2xl w-full max-w-5xl max-h-[90vh] flex flex-col overflow-hidden animate-in zoom-in-95 duration-200">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-black/5 dark:border-white/10 bg-slate-50/50 dark:bg-slate-900/50">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-cyan-500 to-cyan-700 flex items-center justify-center text-white shadow-md shadow-cyan-500/20">
                  <ClipboardCheck size={18} />
                </div>
                <div>
                  <h3 className="text-base font-bold text-slate-900 dark:text-white">
                    {isZh ? '巡检批次执行详情' : 'Inspection Run Details'}
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-slate-400 font-mono mt-0.5">
                    ID: {selectedRunDetail.id} · {selectedRunDetail.started_at?.replace('T', ' ').slice(0, 19)}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => downloadReport(selectedRunDetail.id, 'excel')}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-bold bg-emerald-50 text-emerald-700 hover:bg-emerald-100 transition-colors"
                >
                  <Download size={12} />
                  Excel
                </button>
                <button
                  onClick={() => downloadReport(selectedRunDetail.id, 'pdf')}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-bold bg-rose-50 text-rose-700 hover:bg-rose-100 transition-colors"
                >
                  <Download size={12} />
                  PDF
                </button>
                <button
                  onClick={() => setSelectedRunDetail(null)}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                >
                  <X size={18} />
                </button>
              </div>
            </div>

            {/* Content Table */}
            <div className="flex-1 overflow-y-auto p-6 space-y-4">
              <div className="grid grid-cols-4 gap-3">
                <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-900/50 border border-black/5 dark:border-white/5">
                  <div className="text-[10px] text-slate-400 uppercase font-bold">{isZh ? '设备总数' : 'Total'}</div>
                  <div className="text-xl font-bold text-slate-900 dark:text-white font-mono mt-0.5">{selectedRunDetail.total_devices}</div>
                </div>
                <div className="p-3 rounded-xl bg-emerald-50/50 dark:bg-emerald-950/20 border border-emerald-200/50">
                  <div className="text-[10px] text-emerald-600 uppercase font-bold">{isZh ? '正常设备' : 'Healthy'}</div>
                  <div className="text-xl font-bold text-emerald-700 dark:text-emerald-300 font-mono mt-0.5">{selectedRunDetail.healthy_count}</div>
                </div>
                <div className="p-3 rounded-xl bg-amber-50/50 dark:bg-amber-950/20 border border-amber-200/50">
                  <div className="text-[10px] text-amber-600 uppercase font-bold">{isZh ? '告警设备' : 'Warning'}</div>
                  <div className="text-xl font-bold text-amber-700 dark:text-amber-300 font-mono mt-0.5">{selectedRunDetail.warning_count}</div>
                </div>
                <div className="p-3 rounded-xl bg-rose-50/50 dark:bg-rose-950/20 border border-rose-200/50">
                  <div className="text-[10px] text-rose-600 uppercase font-bold">{isZh ? '严重设备' : 'Critical'}</div>
                  <div className="text-xl font-bold text-rose-700 dark:text-rose-300 font-mono mt-0.5">{selectedRunDetail.critical_count}</div>
                </div>
              </div>

              <div className="overflow-x-auto rounded-xl border border-black/5 dark:border-white/5">
                <table className="w-full text-left">
                  <thead className="bg-slate-50 dark:bg-slate-900/80">
                    <tr className="border-b border-black/5 dark:border-white/5">
                      <Th>{isZh ? '设备主机名 / IP' : 'Device'}</Th>
                      <Th>{isZh ? '厂商平台' : 'Platform'}</Th>
                      <Th>{isZh ? '健康状态' : 'Status'}</Th>
                      <Th>{isZh ? '得分' : 'Score'}</Th>
                      <Th>{isZh ? 'CPU / 内存' : 'CPU / Mem'}</Th>
                      <Th>{isZh ? '环境/电源' : 'Env / PSU'}</Th>
                      <Th>{isZh ? '接口总/Down' : 'Ports / Down'}</Th>
                      <Th>{isZh ? 'Ping / SSH' : 'Connectivity'}</Th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-black/[0.03] dark:divide-white/[0.03] text-xs">
                    {detailLoading ? (
                      <tr>
                        <td colSpan={8} className="py-12 text-center text-slate-400">
                          <Loader2 className="w-5 h-5 animate-spin mx-auto mb-2 text-cyan-500" />
                          {isZh ? '加载明细数据中...' : 'Loading results...'}
                        </td>
                      </tr>
                    ) : (selectedRunDetail.results || []).length === 0 ? (
                      <tr>
                        <td colSpan={8} className="py-12 text-center text-slate-400">
                          {isZh ? '无单设备执行结果' : 'No result rows'}
                        </td>
                      </tr>
                    ) : (
                      selectedRunDetail.results.map((res) => {
                        const tone = statusToneMap[res.health_status] || statusToneMap.unknown;
                        return (
                          <tr key={res.id} className="hover:bg-black/[0.01] dark:hover:bg-white/[0.01]">
                            <td className="px-4 py-3">
                              <div className="font-bold text-slate-800 dark:text-slate-200">{res.hostname || res.ip_address}</div>
                              <div className="text-[10px] text-slate-400 font-mono">{res.ip_address}</div>
                            </td>
                            <td className="px-4 py-3 text-slate-600 dark:text-slate-400 font-mono text-[11px]">
                              {res.platform || '-'}
                            </td>
                            <td className="px-4 py-3">
                              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${tone}`}>
                                {res.health_status}
                              </span>
                            </td>
                            <td className="px-4 py-3 font-mono font-bold text-slate-800 dark:text-slate-200">
                              {res.health_score ?? '—'}
                            </td>
                            <td className="px-4 py-3 font-mono text-[11px] text-slate-700 dark:text-slate-300">
                              {res.cpu_usage != null ? `${res.cpu_usage}%` : '—'} / {res.memory_usage != null ? `${res.memory_usage}%` : '—'}
                            </td>
                            <td className="px-4 py-3 text-[11px] text-slate-600 dark:text-slate-400 font-mono">
                              {res.temperature != null ? `${res.temperature}°C` : '—'} · {res.fan_status ? 'Fan✓' : 'Fan—'}
                            </td>
                            <td className="px-4 py-3 text-[11px] font-mono text-slate-700 dark:text-slate-300">
                              {res.interface_total} / <span className={res.interface_down > 0 ? 'text-rose-500 font-bold' : ''}>{res.interface_down}</span>
                            </td>
                            <td className="px-4 py-3 text-[11px]">
                              <span className={res.ping_ok ? 'text-emerald-600 font-semibold' : 'text-rose-500 font-semibold'}>
                                {res.ping_ok ? 'Ping✓' : 'Ping✗'}
                              </span> ·{' '}
                              <span className={res.ssh_ok ? 'text-emerald-600 font-semibold' : 'text-rose-500 font-semibold'}>
                                {res.ssh_ok ? 'SSH✓' : 'SSH✗'}
                              </span>
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Footer */}
            <div className="flex items-center justify-end px-6 py-3.5 border-t border-black/5 dark:border-white/10 bg-slate-50/50 dark:bg-slate-900/50">
              <button
                onClick={() => setSelectedRunDetail(null)}
                className="px-5 py-2 rounded-xl text-xs font-bold bg-[#06b6d4] hover:bg-[#0891b2] text-white shadow-md shadow-cyan-500/20 transition-all active:scale-95"
              >
                {isZh ? '关闭' : 'Close'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default InspectionTab;
