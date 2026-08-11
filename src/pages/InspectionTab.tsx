import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, AlertTriangle, ArrowRight, CheckCircle2, ChevronRight, ClipboardCheck, Clock, Cpu, Loader2, Play, RefreshCw, Search, Server, Shield, X, XCircle, Wifi, WifiOff, Zap, BarChart3, Eye, Download } from 'lucide-react';
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { Device, DeviceHealthHistoryResponse, DeviceHealthOverview } from '../types';
import { useChartTheme } from '../hooks/useChartTheme';
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

  // ── run inspection ──
  const [isRunning, setIsRunning] = useState(false);
  const [runResult, setRunResult] = useState<Record<string, unknown> | null>(null);
  const [collectionPlans, setCollectionPlans] = useState<any[]>([]);
  const [selectedPlanDeviceId, setSelectedPlanDeviceId] = useState('');
  const [collectionPlansLoading, setCollectionPlansLoading] = useState(false);
  const [collectionPlanMessage, setCollectionPlanMessage] = useState('');

  /* ─── token helper ─── */
  const authHeaders = useMemo(() => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' };
  }, []);

  const fetchCollectionPlans = useCallback(async () => {
    setCollectionPlansLoading(true);
    try {
      const resp = await fetch('/api/collection-plans/devices', { headers: authHeaders });
      if (!resp.ok) return;
      const json = await resp.json();
      const rows = Array.isArray(json.data) ? json.data : [];
      setCollectionPlans(rows);
      setSelectedPlanDeviceId((current) => current || rows[0]?.device?.id || '');
    } catch {
      setCollectionPlanMessage(isZh ? '采集计划加载失败' : 'Failed to load collection plans');
    } finally {
      setCollectionPlansLoading(false);
    }
  }, [authHeaders, isZh]);

  const updateCollectionPlan = useCallback(async (collector: string, enabled: boolean) => {
    const current = collectionPlans.find((row) => row.device?.id === selectedPlanDeviceId);
    if (!current) return;
    const overrides = { ...(current.plan?.overrides || {}), [collector]: enabled };
    try {
      const resp = await fetch(`/api/collection-plans/devices/${selectedPlanDeviceId}`, {
        method: 'PUT',
        headers: authHeaders,
        body: JSON.stringify({ policy: { collectors: overrides } }),
      });
      const json = await resp.json();
      if (!resp.ok) throw new Error(json.detail || 'update failed');
      setCollectionPlanMessage(isZh ? '采集计划已更新' : 'Collection plan updated');
      fetchCollectionPlans();
    } catch {
      setCollectionPlanMessage(isZh ? '采集计划更新失败' : 'Failed to update collection plan');
    }
  }, [authHeaders, collectionPlans, fetchCollectionPlans, isZh, selectedPlanDeviceId]);

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
    }
  }, [authHeaders]);

  /* ─── Effects ─── */

  useEffect(() => { fetchHistory(); }, [fetchHistory]);
  useEffect(() => { fetchRecentRuns(); }, [fetchRecentRuns]);
  useEffect(() => { fetchCollectionPlans(); }, [fetchCollectionPlans]);
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
        allRecords.push(...items);
        if (items.length < limit || (json.data?.total && allRecords.length >= json.data.total)) break;
        offset += limit;
      }

      if (allRecords.length === 0) return;

      const headers = [
        isZh ? '时间' : 'Time',
        isZh ? '类型' : 'Type',
        isZh ? '状态' : 'Status',
        isZh ? '设备总数' : 'Total Devices',
        isZh ? '健康' : 'Healthy',
        isZh ? '告警' : 'Warning',
        isZh ? '严重' : 'Critical',
        isZh ? '平均分' : 'Avg Score',
        isZh ? '操作人' : 'Created By'
      ];

      const rows = allRecords.map(r => [
        new Date(r.started_at).toLocaleString(),
        r.trigger_type,
        r.status,
        r.total_devices,
        r.healthy_count,
        r.warning_count,
        r.critical_count,
        r.avg_health_score,
        r.created_by
      ]);

      const csvContent = "\ufeff" + [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
      const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
      const link = document.createElement("a");
      const url = URL.createObjectURL(blob);
      link.setAttribute("href", url);
      link.setAttribute("download", `inspection_records_${new Date().toISOString().slice(0, 10)}.csv`);
      link.style.visibility = 'hidden';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    } catch (err) {
      console.error('Export failed:', err);
    }
  };

  const handleDownloadReport = async (runId: string, format: 'xlsx' | 'html' | 'json' | 'pdf' = 'xlsx') => {
    try {
      const resp = await fetch(`/api/inspections/${runId}/export?format=${format}`, { headers: authHeaders });
      if (!resp.ok) {
        alert(isZh ? `报表生成失败 (${resp.status})` : `Report generation failed (${resp.status})`);
        return;
      }
      const blob = await resp.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const today = new Date().toISOString().slice(0, 10).replace(/-/g, '');
      a.download = `${systemInfo?.system_name || 'Nexora'}_Inspection_${runId}_${today}.${format}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Download failed:', err);
      alert(isZh ? '报表下载失败' : 'Report download failed');
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
      <PageHero
        icon={ClipboardCheck}
        title={isZh ? '巡检概览' : 'Inspection Overview'}
        subtitle={isZh ? '按计划或手动触发网络健康巡检，一眼看清全网状态' : 'Schedule or trigger network health inspection runs and view the fleet at a glance'}
        actions={
          <button
            onClick={() => triggerInspection('all')}
            disabled={isRunning}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-bold shadow-lg transition-all
              bg-gradient-to-r from-cyan-500 to-cyan-600 text-white hover:from-cyan-400 hover:to-cyan-500
              disabled:opacity-50 disabled:cursor-not-allowed active:scale-[0.97]"
          >
            {isRunning ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            {isRunning ? (isZh ? '巡检中' : 'Running') : (isZh ? '立即巡检全部' : 'Run All Inspection')}
          </button>
        }
      />

      <div className="flex-1 flex flex-col overflow-hidden px-6 py-5 space-y-4 min-h-0">
      <div className="rounded-2xl border border-cyan-100 bg-white p-4 shadow-sm shrink-0">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
          <div>
            <p className="text-sm font-bold text-[#0b2340]">{isZh ? '设备采集计划' : 'Device Collection Plan'}</p>
            <p className="text-[11px] text-black/40 mt-1">{isZh ? '默认采集基本信息；L3 设备额外采集路由表和 BGP 状态，其他拓扑、表项和动态协议可按设备单独开启。' : 'The default plan collects device basics; L3 devices also collect the main route table and BGP state. Other topology, tables, and dynamic protocols are opt-in per device.'}</p>
          </div>
          <div className="flex items-center gap-2">
            <select
              value={selectedPlanDeviceId}
              onChange={(event) => { setSelectedPlanDeviceId(event.target.value); setCollectionPlanMessage(''); }}
              className="rounded-lg border border-black/10 bg-white px-3 py-2 text-xs text-[#0b2340] min-w-[210px]"
              disabled={collectionPlansLoading || collectionPlans.length === 0}
            >
              {collectionPlans.map((row) => <option key={row.device?.id} value={row.device?.id}>{row.device?.hostname || row.device?.ip_address}</option>)}
            </select>
            <button onClick={fetchCollectionPlans} className={alertSecondaryButtonClass} title={isZh ? '刷新采集计划' : 'Refresh collection plans'}>
              <RefreshCw className={`w-4 h-4 ${collectionPlansLoading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>
        {(() => {
          const selected = collectionPlans.find((row) => row.device?.id === selectedPlanDeviceId);
          const effective = selected?.plan?.effective || {};
          const keys = ['reachability', 'health_metrics', 'interface_status', 'interface_ip', 'lldp', 'arp', 'mac_table', 'vlan', 'routes', 'bgp', 'ospf', 'eigrp', 'isis', 'rip', 'bfd', 'endpoint_location', 'prefix_projection'];
          const labels: Record<string, string> = { reachability: '可达性', health_metrics: '健康指标', interface_status: '接口状态', interface_ip: '接口 IP', arp: 'ARP', mac_table: 'MAC', vlan: 'VLAN', lldp: 'LLDP', routes: '路由', bgp: 'BGP', ospf: 'OSPF', eigrp: 'EIGRP', isis: 'IS-IS', rip: 'RIP', bfd: 'BFD', endpoint_location: '终端定位', prefix_projection: 'Prefix 投影' };
          return selected ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[10px] font-bold text-black/35 mr-1">{selected.plan?.profile || selected.device?.role || 'default'}</span>
              {keys.map((key) => (
                <button
                  key={key}
                  onClick={() => updateCollectionPlan(key, !Boolean(effective[key]))}
                  className={`rounded-full px-3 py-1.5 text-[11px] font-semibold border transition-colors ${effective[key] ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-slate-50 text-slate-400 border-slate-200'}`}
                >
                  {labels[key]} · {effective[key] ? (isZh ? '启用' : 'ON') : (isZh ? '关闭' : 'OFF')}
                </button>
              ))}
              {collectionPlanMessage && <span className="text-[11px] text-cyan-600 ml-2">{collectionPlanMessage}</span>}
            </div>
          ) : <span className="text-xs text-black/35">{isZh ? '暂无设备采集计划' : 'No collection plans available'}</span>;
        })()}
      </div>
      {/* ═══════ Hero gauge strip ═══════ */}
      <div className="relative rounded-2xl overflow-hidden bg-gradient-to-r from-[#0c1e35] via-[#0e2942] to-[#0a3455] p-5 shadow-lg shrink-0">
        <div className="absolute inset-0 opacity-[0.04]" style={{ backgroundImage: 'radial-gradient(circle, white 1px, transparent 1px)', backgroundSize: '18px 18px' }} />
        <div className="relative flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
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
        <div className="rounded-xl border border-cyan-200 bg-gradient-to-r from-cyan-50 to-white p-3.5 flex items-center justify-between gap-3 shadow-sm shrink-0">
          <div className="flex items-center gap-3 text-sm">
            <div className="w-7 h-7 rounded-full bg-cyan-100 flex items-center justify-center shrink-0"><CheckCircle2 className="w-4 h-4 text-cyan-600" /></div>
            <span className="text-[#0b2340]">
              {isZh ? '巡检完成' : 'Inspection complete'} — {isZh ? '设备' : 'Devices'}: {String(runResult.total_devices || 0)}, <span className="text-emerald-600 font-semibold">{isZh ? '健康' : 'healthy'} {String(runResult.healthy_count || 0)}</span>, <span className="text-amber-600 font-semibold">{isZh ? '告警' : 'warning'} {String(runResult.warning_count || 0)}</span>, <span className="text-red-600 font-semibold">{isZh ? '严重' : 'critical'} {String(runResult.critical_count || 0)}</span>
            </span>
          </div>
          <button onClick={() => setRunResult(null)} className="p-1 rounded-md text-black/30 hover:text-black/60 hover:bg-black/5 transition-colors"><X className="w-4 h-4" /></button>
        </div>
      )}

      {/* ═══════ Main Content Area ═══════ */}
      <div className={`${alertPanelClass} flex-1 min-h-0 flex flex-col overflow-hidden`}>
        {/* Navigation Tabs — only shown when NOT driven by sidebar navigation.
            When initialView is set, the sidebar already provides the navigation
            so showing these tabs would duplicate the menu items. */}
        {!initialView && (
          <div className="flex items-center gap-1.5 border-b border-black/5 px-5 py-3 shrink-0">
            {[
              { key: 'overview', label: isZh ? '巡检概览' : 'Overview', icon: <BarChart3 className="w-3.5 h-3.5" /> },
              { key: 'records', label: isZh ? '巡检记录' : 'Records', icon: <Clock className="w-3.5 h-3.5" /> },
            ].map((tab) => (
              <button
                key={tab.key}
                onClick={() => { setSubTab(tab.key as SubTab); setSelectedRunDetail(null); }}
                className={`flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-bold transition-all ${subTab === tab.key ? 'bg-[#00172d] text-white shadow-lg' : 'text-black/40 hover:bg-black/5 hover:text-black/60'}`}
              >
                {tab.icon}
                {tab.label}
              </button>
            ))}
          </div>
        )}

        {/* Scrollable Body */}
        <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
          {/* ═══════ SUB-TAB: OVERVIEW ═══════ */}
          {subTab === 'overview' && (
            <div className="p-5 space-y-5">
              {/* Health Trend Chart */}
              <div className="rounded-2xl border border-black/[0.06] bg-white p-5 shadow-sm">
                <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 mb-4">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center"><Activity className="w-4 h-4 text-blue-600" /></div>
                    <div>
                      <h3 className="text-sm font-bold text-[#0b2340]">{isZh ? '设备健康趋势' : 'Device Health Trend'}</h3>
                      <p className="text-[11px] text-black/35">{isZh ? '柱状图为异常设备数量，折线为平均健康评分' : 'Bars = abnormal devices, Line = avg health score'}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-0.5 rounded-lg bg-black/[0.03] p-0.5">
                    {([{ h: 1, l: '1H' }, { h: 24, l: '24H' }, { h: 168, l: '7D' }] as const).map(({ h, l }) => (
                      <button key={h} onClick={() => setRangeHours(h)} className={`px-2.5 py-1 rounded-md text-[10px] font-bold tracking-wide transition-all ${rangeHours === h ? 'bg-white text-[#0b2340] shadow-sm ring-1 ring-black/5' : 'text-black/40 hover:text-black/60'}`}>{l}</button>
                    ))}
                  </div>
                </div>

                <div className="h-[240px]">
                  {historySeries.length > 0 ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <ComposedChart data={historySeries} margin={{ top: 8, right: 12, left: -4, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 6" vertical={false} stroke={ct.gridAlt} />
                        <XAxis dataKey="ts" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: ct.axisAlt }} tickFormatter={(v) => new Date(String(v)).toLocaleString(isZh ? 'zh-CN' : 'en-US', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })} minTickGap={36} />
                        <YAxis yAxisId="count" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: ct.axisAlt }} width={28} allowDecimals={false} />
                        <YAxis yAxisId="score" orientation="right" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: ct.axisAlt }} domain={[0, 100]} width={32} />
                        <Tooltip contentStyle={{ borderRadius: 12, border: 'none', boxShadow: '0 8px 32px rgba(0,0,0,0.12)', padding: '12px 16px', background: ct.tooltipBg, color: ct.tooltipText, fontSize: 12 }} />
                        <Bar yAxisId="count" dataKey="critical" stackId="devices" fill="#f87171" radius={[0, 0, 2, 2]} barSize={16} />
                        <Bar yAxisId="count" dataKey="warning" stackId="devices" fill="#fbbf24" radius={[2, 2, 0, 0]} barSize={16} />
                        <Line yAxisId="score" type="monotone" dataKey="average_score" stroke="#3b82f6" strokeWidth={2.5} dot={false} activeDot={{ r: 4, fill: '#3b82f6', stroke: '#fff', strokeWidth: 2 }} />
                      </ComposedChart>
                    </ResponsiveContainer>
                  ) : <div className="h-full flex flex-col items-center justify-center gap-2 text-black/25"><BarChart3 className="w-8 h-8" /><p className="text-sm">{isZh ? '暂无趋势数据' : 'No trend data'}</p></div>}
                </div>
              </div>

              {/* Recent runs + risk devices */}
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
                <div className="rounded-2xl border border-black/[0.06] bg-white shadow-sm overflow-hidden flex flex-col">
                  <div className="px-5 pt-4 pb-3 flex items-center justify-between shrink-0">
                    <div className="flex items-center gap-2.5">
                      <div className="w-7 h-7 rounded-lg bg-cyan-50 flex items-center justify-center"><Clock className="w-3.5 h-3.5 text-cyan-600" /></div>
                      <h3 className="text-sm font-bold text-[#0b2340]">{isZh ? '最近巡检' : 'Recent Inspections'}</h3>
                    </div>
                  </div>
                  <div className="px-4 pb-4 space-y-2">
                    {recentRuns.map((run) => (
                      <button key={run.id} onClick={() => { setSubTab('records'); fetchRunDetail(run.id); }} className="w-full group rounded-xl border border-black/[0.06] bg-white px-4 py-3 text-left transition-all hover:border-cyan-300/60 hover:shadow-sm">
                        <div className="flex items-center justify-between gap-3">
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2">
                              <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-bold uppercase ${run.status === 'completed' ? 'bg-emerald-50 text-emerald-600' : 'bg-cyan-50 text-cyan-600'}`}>{run.status}</span>
                              <span className="text-[10px] text-black/30">{new Date(run.started_at).toLocaleString(isZh ? 'zh-CN' : 'en-US', { hour12: false })}</span>
                            </div>
                          </div>
                          <div className="w-10 h-10 rounded-lg bg-slate-50 flex items-center justify-center group-hover:bg-cyan-50 transition-colors">
                            <span className="text-sm font-bold tabular-nums text-[#0b2340]">{run.avg_health_score ?? '—'}</span>
                          </div>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>

                <div className="rounded-2xl border border-black/[0.06] bg-white shadow-sm overflow-hidden flex flex-col">
                  <div className="px-5 pt-4 pb-3 flex items-center gap-2.5 shrink-0">
                    <div className="w-7 h-7 rounded-lg bg-red-50 flex items-center justify-center"><AlertTriangle className="w-3.5 h-3.5 text-red-500" /></div>
                    <h3 className="text-sm font-bold text-[#0b2340]">{isZh ? '高风险设备' : 'High-Risk Devices'}</h3>
                  </div>
                  <div className="px-4 pb-4 space-y-2">
                    {riskyDevices.map((device) => (
                      <button key={device.id} onClick={() => onShowDetails(device)} className="w-full group rounded-xl border border-black/[0.06] px-4 py-3 text-left transition-all hover:border-red-200/80 hover:shadow-sm">
                        <div className="flex items-center justify-between gap-3">
                          <div className="min-w-0 flex-1">
                            <p className="text-sm font-semibold text-[#0b2340] truncate">{device.hostname || device.ip_address}</p>
                            <p className="text-[11px] text-black/35 truncate mt-0.5">{device.site} · {device.platform}</p>
                          </div>
                          <div className="w-9 h-9 rounded-lg bg-slate-50 flex items-center justify-center group-hover:bg-red-50 transition-colors">
                            <span className="text-sm font-bold tabular-nums text-[#0b2340]">{device.health_score}</span>
                          </div>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ═══════ SUB-TAB: RECORDS ═══════ */}
          {subTab === 'records' && !selectedRunDetail && (
            <div className="flex flex-col min-h-full">
              <div className="p-5 border-b border-black/5 bg-slate-50/30 flex items-center gap-3 shrink-0">
                <div className="relative flex-1 max-w-sm">
                  <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-black/25" />
                  <input type="text" placeholder={isZh ? '搜索巡检记录…' : 'Search runs...'} value={recordSearch} onChange={(e) => setRecordSearch(e.target.value)} className="w-full pl-10 pr-3 py-2 rounded-xl border border-black/[0.08] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20" />
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={handleExportRecords}
                    title={isZh ? '导出所有巡检记录' : 'Export all records'}
                    className={alertSecondaryButtonClass}
                  >
                    <Download className="w-4 h-4" />
                    <span className="ml-1 hidden sm:inline">{isZh ? '导出' : 'Export'}</span>
                  </button>
                  <button onClick={fetchRuns} className={alertSecondaryButtonClass}><RefreshCw className={`w-4 h-4 ${runsLoading ? 'animate-spin' : ''}`} /></button>
                </div>
              </div>

              <div className="flex-1 min-h-0">
                <table className="nx-data-table text-left text-sm">
                  <thead className="sticky top-0 bg-white border-b border-black/[0.05] z-10">
                    <tr className="bg-slate-50/50">
                      <Th>{isZh ? '时间' : 'Time'}</Th>
                      <Th>{isZh ? '类型' : 'Type'}</Th>
                      <Th>{isZh ? '状态' : 'Status'}</Th>
                      <Th>{isZh ? '设备数' : 'Devices'}</Th>
                      <Th>{isZh ? '健康/告警/严重' : 'H/W/C'}</Th>
                      <Th>{isZh ? '平均分' : 'Avg'}</Th>
                      <Th>{isZh ? '操作人' : 'User'}</Th>
                      <Th className="w-10"></Th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-black/[0.04]">
                    {filteredRuns.map((run) => (
                      <tr key={run.id} className="group hover:bg-cyan-50/30 cursor-pointer transition-colors" onClick={() => fetchRunDetail(run.id)}>
                        <td className="px-4 py-3 text-[12px] text-black/55">{new Date(run.started_at).toLocaleString(isZh ? 'zh-CN' : 'en-US', { hour12: false })}</td>
                        <td className="px-4 py-3"><span className={`inline-flex rounded-md px-2 py-0.5 text-[10px] font-bold uppercase ${run.trigger_type === 'manual' ? 'bg-blue-50 text-blue-600' : 'bg-violet-50 text-violet-600'}`}>{run.trigger_type}</span></td>
                        <td className="px-4 py-3"><span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-bold uppercase ${run.status === 'completed' ? 'bg-emerald-50 text-emerald-600' : 'bg-red-50 text-red-600'}`}>{run.status}</span></td>
                        <td className="px-4 py-3 font-semibold tabular-nums">{run.total_devices}</td>
                        <td className="px-4 py-3 font-bold tabular-nums"><span className="text-emerald-600">{run.healthy_count}</span><span className="text-black/10 mx-1">/</span><span className="text-amber-500">{run.warning_count}</span><span className="text-black/10 mx-1">/</span><span className="text-red-500">{run.critical_count}</span></td>
                        <td className="px-4 py-3 font-bold tabular-nums text-[#0b2340]">{run.avg_health_score ?? '—'}</td>
                        <td className="px-4 py-3 text-[12px] text-black/40">{run.created_by}</td>
                        <td className="px-4 py-3"><Eye className="w-3.5 h-3.5 text-black/20 group-hover:text-cyan-500" /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* ═══════ RECORDS: Run Detail ═══════ */}
          {subTab === 'records' && selectedRunDetail && (
            <div className="p-5 space-y-5">
              <button onClick={() => setSelectedRunDetail(null)} className="flex items-center gap-1.5 text-sm text-cyan-600 font-medium"><ChevronRight className="w-3.5 h-3.5 rotate-180" />{isZh ? '返回列表' : 'Back'}</button>
              
              <div className="rounded-2xl border border-black/[0.06] bg-white p-5 shadow-sm">
                <div className="flex items-center gap-4 mb-5">
                  <ScoreGauge score={selectedRunDetail.avg_health_score} size={64} />
                  <div className="flex-1">
                    <h3 className="text-base font-bold text-[#0b2340]">{isZh ? '巡检详情' : 'Inspection Detail'}</h3>
                    <p className="text-[11px] text-black/35 mt-0.5">{new Date(selectedRunDetail.started_at).toLocaleString(isZh ? 'zh-CN' : 'en-US', { hour12: false })}</p>
                  </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => handleDownloadReport(selectedRunDetail.id, 'xlsx')}
                        className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-bold bg-emerald-600 text-white hover:bg-emerald-500 shadow-md active:scale-95 transition-all"
                        title={isZh ? '下载 Excel 报表（含 7 个 Sheet）' : 'Download Excel report (7 sheets)'}
                      >
                        <Download className="w-4 h-4" />
                        Excel
                      </button>
                      <button
                        onClick={() => handleDownloadReport(selectedRunDetail.id, 'html')}
                        className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-bold bg-indigo-600 text-white hover:bg-indigo-500 shadow-md active:scale-95 transition-all"
                        title={isZh ? '下载 HTML 报表（含 ECharts 图表）' : 'Download HTML report (ECharts inline)'}
                      >
                        <Download className="w-4 h-4" />
                        HTML
                      </button>
                      <button
                        onClick={() => handleDownloadReport(selectedRunDetail.id, 'pdf')}
                        className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-bold bg-rose-600 text-white hover:bg-rose-500 shadow-md active:scale-95 transition-all"
                        title={isZh ? '下载 PDF 报表（适合打印和归档）' : 'Download PDF report (Archive-ready)'}
                      >
                        <Download className="w-4 h-4" />
                        PDF
                      </button>
                      <button
                        onClick={() => handleDownloadReport(selectedRunDetail.id, 'json')}
                        className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-bold bg-slate-700 text-white hover:bg-slate-600 shadow-md active:scale-95 transition-all"
                        title={isZh ? '下载 JSON 原始数据（机器可读）' : 'Download raw JSON data'}
                      >
                        <Download className="w-4 h-4" />
                        JSON
                      </button>
                    </div>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {[{ label: 'Total', value: selectedRunDetail.total_devices, bg: 'bg-slate-50' }, { label: 'Healthy', value: selectedRunDetail.healthy_count, bg: 'bg-emerald-50' }, { label: 'Warning', value: selectedRunDetail.warning_count, bg: 'bg-amber-50' }, { label: 'Critical', value: selectedRunDetail.critical_count, bg: 'bg-red-50' }].map(s => (
                    <div key={s.label} className={`${s.bg} rounded-xl p-3 text-center`}><p className="text-[10px] font-bold uppercase opacity-60">{s.label}</p><p className="text-xl font-bold tabular-nums mt-1">{s.value}</p></div>
                  ))}
                </div>
              </div>

              <div className="rounded-2xl border border-black/[0.06] bg-white shadow-sm overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="nx-data-table text-left text-sm">
                    <thead className="bg-slate-50 border-b border-black/[0.05]">
                      <tr>
                        <Th>{isZh ? '设备' : 'Device'}</Th>
                        <Th>Ping/SSH</Th>
                        <Th>{isZh ? '精细化指标 (取值)' : 'Granular Metrics'}</Th>
                        <Th>{isZh ? '状态/评分' : 'Status/Score'}</Th>
                        <Th>{isZh ? '详细发现' : 'Findings'}</Th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-black/[0.04]">
                      {selectedRunDetail.results.map(r => {
                        const metrics = JSON.parse(r.metrics_json || '{}');
                        const findings = JSON.parse(r.findings_json || '[]');
                        
                        return (
                          <tr key={r.id} className="hover:bg-slate-50/50">
                            <td className="px-4 py-3">
                              <div className="font-semibold text-[#0b2340]">{r.hostname}</div>
                              <div className="text-[10px] text-black/30 font-mono">{r.ip_address}</div>
                            </td>
                            <td className="px-4 py-3 flex flex-col gap-1">
                              <span className={`text-[10px] font-bold ${r.ping_ok ? 'text-emerald-600' : 'text-red-500'}`}>PING {r.ping_ok ? 'OK' : 'FAIL'}</span>
                              <span className={`text-[10px] font-bold ${r.ssh_ok ? 'text-emerald-600' : 'text-red-500'}`}>SSH {r.ssh_ok ? 'OK' : 'FAIL'}</span>
                            </td>
                            <td className="px-4 py-3">
                              <div className="flex flex-wrap gap-1.5 max-w-[300px]">
                                {Object.entries(metrics)
                                  .filter(([key]) => !key.endsWith('_status'))
                                  .map(([key, val]) => {
                                    const status = metrics[`${key}_status`] || (typeof val === 'number' ? 'SUCCESS' : 'ERROR');
                                    const isError = status === 'ERROR';
                                    return (
                                      <div key={key} className={`px-2 py-0.5 rounded-md text-[10px] font-bold border ${!isError ? 'bg-emerald-50 border-emerald-200 text-emerald-700' : 'bg-red-50 border-red-100 text-red-600'}`}>
                                        <span className="opacity-50 mr-1">{key}:</span>
                                        <span className="font-mono">
                                          {typeof val === 'number'
                                            ? val.toFixed(1) + (key.includes('util') || key.includes('avail') || key.includes('pct') ? '%' : '')
                                            : (val && typeof val === 'object' && 'error' in val)
                                              ? String(val.error)
                                              : String(val)}
                                        </span>
                                        <span className="ml-1 text-[8px] opacity-75">({status})</span>
                                      </div>
                                    );
                                  })}
                                {Object.keys(metrics).length === 0 && <span className="text-black/20 text-[10px] italic">No metrics collected</span>}
                              </div>
                            </td>
                            <td className="px-4 py-3">
                              <div className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${
                                r.health_status === 'healthy' 
                                  ? 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200/60' 
                                  : (r.health_status === 'warning' || r.health_status === 'critical') 
                                    ? 'bg-red-50 text-red-700 ring-1 ring-red-200/60' 
                                    : 'bg-slate-50 text-slate-600 ring-1 ring-slate-200/60'
                              }`}>
                                {r.health_status === 'healthy' ? 'SUCCESS' : (r.health_status === 'warning' || r.health_status === 'critical') ? 'ERROR' : r.health_status} ({r.health_score ?? '—'})
                              </div>
                            </td>
                            <td className="px-4 py-3">
                              <div className="space-y-1">
                                {findings.map((f: any, idx: number) => (
                                  <div key={idx} className={`text-[11px] leading-tight ${f.severity === 'critical' ? 'text-red-600 font-medium' : 'text-amber-600'}`}>
                                    • {f.message}
                                  </div>
                                ))}
                                {findings.length === 0 && <span className="text-emerald-600 text-[11px] font-medium">✓ Passed all checks</span>}
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Fixed Pagination Bar (Only for Records) */}
        {subTab === 'records' && !selectedRunDetail && (
          <div className="shrink-0 border-t border-black/5 bg-white p-3">
            <Pagination
              currentPage={recordPage}
              totalItems={recordTotal}
              itemsPerPage={recordPageSize}
              onPageChange={setRecordPage}
              onItemsPerPageChange={(size) => { setRecordPageSize(size); setRecordPage(1); }}
              language={language}
            />
          </div>
        )}
      </div>
      </div>
    </div>
  );
};

export default InspectionTab;
