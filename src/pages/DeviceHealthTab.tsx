import React from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  Clock3,
  Filter,
  Gauge,
  RefreshCw,
  Search,
  Server,
  ShieldAlert,
  ShieldCheck,
  WifiOff,
  X,
} from 'lucide-react';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { Device, DeviceHealthHistoryResponse, DeviceHealthOverview } from '../types';

interface DeviceHealthTabProps {
  devices: Device[];
  overview: DeviceHealthOverview | null;
  language: string;
  onShowDetails: (device: Device) => void;
  onOpenMonitoring: () => void;
}

type HealthStatus = 'healthy' | 'warning' | 'critical' | 'unknown';

const statusConfig: Record<HealthStatus, { zh: string; en: string; color: string; soft: string; bar: string; icon: typeof CheckCircle2 }> = {
  healthy: { zh: '\u5065\u5eb7', en: 'Healthy', color: 'text-emerald-300', soft: 'bg-emerald-400/10 border-emerald-300/20', bar: 'bg-emerald-400', icon: CheckCircle2 },
  warning: { zh: '\u544a\u8b66', en: 'Warning', color: 'text-amber-300', soft: 'bg-amber-400/10 border-amber-300/20', bar: 'bg-amber-400', icon: AlertTriangle },
  critical: { zh: '\u4e25\u91cd', en: 'Critical', color: 'text-rose-300', soft: 'bg-rose-400/10 border-rose-300/20', bar: 'bg-rose-400', icon: ShieldAlert },
  unknown: { zh: '\u672a\u77e5', en: 'Unknown', color: 'text-slate-300', soft: 'bg-slate-400/10 border-slate-300/20', bar: 'bg-slate-400', icon: CircleHelp },
};

const copy = (isZh: boolean) => isZh ? {
  eyebrow: '\u5b9e\u65f6\u5065\u5eb7\u6001\u52bf', title: '\u8bbe\u5907\u5065\u5eb7\u68c0\u6d4b\u4e2d\u5fc3',
  subtitle: '\u7edf\u4e00\u67e5\u770b\u8bbe\u5907\u53ef\u8fbe\u6027\u3001\u544a\u8b66\u3001\u63a5\u53e3\u8d28\u91cf\u3001\u8d44\u6e90\u548c\u5408\u89c4\u72b6\u6001\uff0c\u4f18\u5148\u5b9a\u4f4d\u6700\u9700\u8981\u5904\u7406\u7684\u8bbe\u5907\u3002',
  auto: '30 \u79d2\u81ea\u52a8\u5237\u65b0', refresh: '\u5237\u65b0\u6570\u636e', monitoring: '\u6253\u5f00\u76d1\u63a7\u4e2d\u5fc3',
  total: '\u8bbe\u5907\u603b\u6570', average: '\u5e73\u5747\u5065\u5eb7\u5206', distribution: '\u5168\u7f51\u5065\u5eb7\u5206\u5e03', posture: '\u5f53\u524d\u8bbe\u5907\u72b6\u6001', healthyRate: '\u5065\u5eb7\u7387', averageShort: '\u5e73\u5747\u5206',
  triage: '\u4f18\u5148\u5904\u7406', risky: '\u9ad8\u98ce\u9669\u8bbe\u5907', sorted: '\u6309\u5065\u5eb7\u5206\u6392\u5e8f', noRisk: '\u5f53\u524d\u6ca1\u6709\u9ad8\u98ce\u9669\u8bbe\u5907', noMatch: '\u6ca1\u6709\u8bbe\u5907\u5339\u914d\u5f53\u524d\u7b5b\u9009\u6761\u4ef6',
  trend: '\u5386\u53f2\u8d8b\u52bf', trendTitle: '\u5065\u5eb7\u6001\u52bf\u53d8\u5316', loading: '\u52a0\u8f7d\u4e2d\u2026', samples: '\u4e2a\u91c7\u6837\u70b9', noTrend: '\u6682\u65e0\u8d8b\u52bf\u91c7\u6837\u6570\u636e\uff0c\u91c7\u6837\u4efb\u52a1\u8fd0\u884c\u540e\u4f1a\u5728\u8fd9\u91cc\u663e\u793a', latestScore: '\u6700\u65b0\u5e73\u5747\u5206', latestCritical: '\u6700\u65b0\u4e25\u91cd\u8bbe\u5907', latestWarning: '\u6700\u65b0\u544a\u8b66\u8bbe\u5907',
  inventory: '\u8bbe\u5907\u660e\u7ec6', results: '\u5065\u5eb7\u68c0\u6d4b\u7ed3\u679c', clear: '\u6e05\u9664\u7b5b\u9009', search: '\u641c\u7d22\u8bbe\u5907\u540d\u3001IP\u3001\u5e73\u53f0\u6216\u6458\u8981', allSites: '\u5168\u90e8\u7ad9\u70b9', allRoles: '\u5168\u90e8\u89d2\u8272', allStates: '\u5168\u90e8\u5065\u5eb7\u72b6\u6001', allRisks: '\u5168\u90e8\u98ce\u9669\u7ef4\u5ea6', openAlerts: '\u6709\u672a\u5904\u7406\u544a\u8b66', interfaceRisk: '\u63a5\u53e3\u5b58\u5728\u98ce\u9669',
  device: '\u8bbe\u5907', location: '\u4f4d\u7f6e / \u89d2\u8272', health: '\u5065\u5eb7\u72b6\u6001', score: '\u8bc4\u5206', signals: '\u98ce\u9669\u4fe1\u53f7', summary: '\u6458\u8981', clearState: '\u6b63\u5e38', noData: '\u6682\u65e0\u8bbe\u5907\u5065\u5eb7\u6570\u636e\u3002\u8bf7\u786e\u8ba4\u8bbe\u5907\u5df2\u540c\u6b65\u5e76\u7b49\u5f85\u5065\u5eb7\u91c7\u6837\u3002', noIssue: '\u672a\u53d1\u73b0\u660e\u663e\u5065\u5eb7\u95ee\u9898', retry: '\u91cd\u8bd5', unavailable: '\u5065\u5eb7\u6570\u636e\u6682\u65f6\u65e0\u6cd5\u52a0\u8f7d\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5', alerts: '\u6761\u544a\u8b66', noMetadata: '\u6682\u65e0\u8bbe\u5907\u4fe1\u606f', interface: '\u63a5\u53e3\u98ce\u9669',
} : {
  eyebrow: 'Live health posture', title: 'Device Health Center', subtitle: 'Unify reachability, alerts, interface quality, resource and compliance signals to focus triage on the devices that need attention first.', auto: '30s auto refresh', refresh: 'Refresh', monitoring: 'Open monitoring', total: 'Total devices', average: 'Average score', distribution: 'Fleet distribution', posture: 'Current device posture', healthyRate: 'Healthy rate', averageShort: 'AVG', triage: 'Priority triage', risky: 'High-risk devices', sorted: 'Sorted by health score', noRisk: 'No high-risk devices right now.', noMatch: 'No devices match the active filters.', trend: 'History trend', trendTitle: 'Health posture over time', loading: 'Loading...', samples: 'samples', noTrend: 'No trend samples yet. Data will appear after the sampler runs.', latestScore: 'Latest score', latestCritical: 'Latest critical', latestWarning: 'Latest warning', inventory: 'Device inventory', results: 'Health check results', clear: 'Clear filters', search: 'Search hostname, IP, platform or summary', allSites: 'All sites', allRoles: 'All roles', allStates: 'All health states', allRisks: 'All risk types', openAlerts: 'Open alerts', interfaceRisk: 'Interface risk', device: 'Device', location: 'Location / role', health: 'Health', score: 'Score', signals: 'Signals', summary: 'Summary', clearState: 'Clear', noData: 'No device health data. Confirm devices are synced and wait for a health sample.', noIssue: 'No material health issue detected', retry: 'Retry', unavailable: 'Health data is temporarily unavailable. Please retry.', alerts: 'alerts', noMetadata: 'No device metadata', interface: 'Interface risk',
};

const toHealthStatus = (value: string | undefined): HealthStatus => value === 'healthy' || value === 'warning' || value === 'critical' ? value : 'unknown';
const formatTime = (value: string | undefined, language: string) => {
  if (!value) return '--';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
};

const DeviceHealthTab: React.FC<DeviceHealthTabProps> = ({ devices, overview, language, onShowDetails, onOpenMonitoring }) => {
  const isZh = language === 'zh';
  const labels = copy(isZh);
  const [rangeHours, setRangeHours] = React.useState(24);
  const [history, setHistory] = React.useState<DeviceHealthHistoryResponse | null>(null);
  const [liveOverview, setLiveOverview] = React.useState<DeviceHealthOverview | null>(overview);
  const [historyLoading, setHistoryLoading] = React.useState(false);
  const [overviewLoading, setOverviewLoading] = React.useState(false);
  const [loadError, setLoadError] = React.useState('');
  const [siteFilter, setSiteFilter] = React.useState('all');
  const [roleFilter, setRoleFilter] = React.useState('all');
  const [statusFilter, setStatusFilter] = React.useState<'all' | HealthStatus>('all');
  const [riskFilter, setRiskFilter] = React.useState<'all' | 'alerts' | 'interfaces'>('all');
  const [searchTerm, setSearchTerm] = React.useState('');

  const loadOverview = React.useCallback(async () => {
    setOverviewLoading(true);
    try {
      const response = await fetch('/api/device-health/overview');
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setLiveOverview(await response.json() as DeviceHealthOverview);
      setLoadError('');
    } catch (error) {
      console.error('Failed to load device health overview:', error);
      if (!liveOverview && !overview) setLoadError(labels.unavailable);
    } finally {
      setOverviewLoading(false);
    }
  }, [labels.unavailable, liveOverview, overview]);

  const loadHistory = React.useCallback(async () => {
    setHistoryLoading(true);
    try {
      const response = await fetch(`/api/device-health/history?range_hours=${rangeHours}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setHistory(await response.json() as DeviceHealthHistoryResponse);
    } catch (error) {
      console.error('Failed to load device health history:', error);
    } finally {
      setHistoryLoading(false);
    }
  }, [rangeHours]);

  React.useEffect(() => { void loadOverview(); const timer = window.setInterval(() => void loadOverview(), 30000); return () => window.clearInterval(timer); }, [loadOverview]);
  React.useEffect(() => { void loadHistory(); const timer = window.setInterval(() => void loadHistory(), 60000); return () => window.clearInterval(timer); }, [loadHistory]);
  React.useEffect(() => { if (overview) setLiveOverview((current) => current || overview); }, [overview]);

  const summary = liveOverview || overview || {
    total_devices: devices.length,
    average_score: devices.length ? Number((devices.reduce((sum, device) => sum + Number(device.health_score || 0), 0) / devices.length).toFixed(1)) : 0,
    healthy: devices.filter((device) => toHealthStatus(device.health_status) === 'healthy').length,
    warning: devices.filter((device) => toHealthStatus(device.health_status) === 'warning').length,
    critical: devices.filter((device) => toHealthStatus(device.health_status) === 'critical').length,
    unknown: devices.filter((device) => toHealthStatus(device.health_status) === 'unknown').length,
    top_risky_devices: [],
  };
  const siteOptions = React.useMemo(() => Array.from(new Set(devices.map((device) => device.site).filter(Boolean))).sort(), [devices]);
  const roleOptions = React.useMemo(() => Array.from(new Set(devices.map((device) => device.role).filter(Boolean))).sort(), [devices]);
  const filteredDevices = React.useMemo(() => {
    const keyword = searchTerm.trim().toLowerCase();
    return devices.filter((device) => {
      const status = toHealthStatus(device.health_status);
      if (siteFilter !== 'all' && device.site !== siteFilter) return false;
      if (roleFilter !== 'all' && device.role !== roleFilter) return false;
      if (statusFilter !== 'all' && status !== statusFilter) return false;
      if (riskFilter === 'alerts' && Number(device.open_alert_count || 0) <= 0) return false;
      if (riskFilter === 'interfaces' && Number(device.interface_down_count || 0) + Number(device.interface_flap_count || 0) + Number(device.interface_error_count || 0) <= 0) return false;
      return !keyword || [device.hostname, device.ip_address, device.platform, device.role, device.site, device.health_summary].filter(Boolean).join(' ').toLowerCase().includes(keyword);
    });
  }, [devices, riskFilter, roleFilter, searchTerm, siteFilter, statusFilter]);
  const activeFilters = siteFilter !== 'all' || roleFilter !== 'all' || statusFilter !== 'all' || riskFilter !== 'all' || Boolean(searchTerm.trim());
  const riskyDevices = React.useMemo(() => {
    const source = activeFilters ? filteredDevices : (summary.top_risky_devices?.length ? summary.top_risky_devices : devices);
    return [...source].sort((a, b) => ({ critical: 0, warning: 1, unknown: 2, healthy: 3 }[toHealthStatus(a.health_status)] - ({ critical: 0, warning: 1, unknown: 2, healthy: 3 }[toHealthStatus(b.health_status)]) || Number(a.health_score || 0) - Number(b.health_score || 0) || Number(b.open_alert_count || 0) - Number(a.open_alert_count || 0))).slice(0, 6);
  }, [activeFilters, devices, filteredDevices, summary.top_risky_devices]);
  const total = Math.max(Number(summary.total_devices || 0), 1);
  const distribution = (['healthy', 'warning', 'critical', 'unknown'] as HealthStatus[]).map((status) => ({ status, count: Number(summary[status] || 0), percent: Math.round(Number(summary[status] || 0) / total * 100) }));
  const historySeries = history?.series || [];
  const lastPoint = historySeries[historySeries.length - 1];
  const clearFilters = () => { setSiteFilter('all'); setRoleFilter('all'); setStatusFilter('all'); setRiskFilter('all'); setSearchTerm(''); };

  return <div className="nx-dark-page flex h-full min-h-0 flex-col overflow-hidden bg-[#06111f] text-white">
    <div className="shrink-0 border-b border-white/10 bg-[radial-gradient(circle_at_78%_0%,rgba(14,165,233,0.20),transparent_35%),linear-gradient(120deg,#06111f,#0b1d32)] px-6 py-5">
      <div className="flex flex-wrap items-start justify-between gap-4"><div><div className="flex items-center gap-3"><span className="grid h-11 w-11 place-items-center rounded-2xl border border-cyan-300/20 bg-cyan-300/10 text-cyan-300 shadow-[0_0_30px_rgba(34,211,238,0.12)]"><Activity size={22} /></span><div><div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.22em] text-cyan-300/75"><span className="h-2 w-2 animate-pulse rounded-full bg-emerald-400" /> {labels.eyebrow}</div><h1 className="mt-1 text-2xl font-semibold tracking-tight">{labels.title}</h1></div></div><p className="mt-3 max-w-2xl text-sm text-slate-300">{labels.subtitle}</p></div><div className="flex items-center gap-2"><span className="hidden items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-slate-300 sm:flex"><Clock3 size={13} /> {labels.auto}</span><button type="button" onClick={() => { void loadOverview(); void loadHistory(); }} className="inline-flex items-center gap-2 rounded-xl border border-cyan-300/25 bg-cyan-300/10 px-3 py-2 text-xs font-semibold text-cyan-200 transition hover:bg-cyan-300/20" disabled={overviewLoading || historyLoading}><RefreshCw size={14} className={overviewLoading || historyLoading ? 'animate-spin' : ''} /> {labels.refresh}</button><button type="button" onClick={onOpenMonitoring} className="inline-flex items-center gap-1 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs font-semibold text-slate-200 transition hover:bg-white/10">{labels.monitoring} <ChevronRight size={14} /></button></div></div>
    </div>
    <div className="min-h-0 flex-1 overflow-auto px-6 py-5">
      {loadError && <div className="mb-4 flex items-center justify-between gap-3 rounded-2xl border border-rose-300/25 bg-rose-400/10 px-4 py-3 text-sm text-rose-100"><span className="flex items-center gap-2"><WifiOff size={16} /> {loadError}</span><button type="button" onClick={() => void loadOverview()} className="rounded-lg border border-rose-200/25 px-3 py-1.5 text-xs font-semibold hover:bg-rose-300/10">{labels.retry}</button></div>}
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-6">{[
        { label: labels.total, value: summary.total_devices, icon: Server, color: 'text-cyan-300', filter: 'all' as const }, { label: labels.average, value: summary.average_score, icon: Gauge, color: 'text-sky-300', filter: null }, { label: statusConfig.healthy[isZh ? 'zh' : 'en'], value: summary.healthy, icon: ShieldCheck, color: 'text-emerald-300', filter: 'healthy' as const }, { label: statusConfig.warning[isZh ? 'zh' : 'en'], value: summary.warning, icon: AlertTriangle, color: 'text-amber-300', filter: 'warning' as const }, { label: statusConfig.critical[isZh ? 'zh' : 'en'], value: summary.critical, icon: ShieldAlert, color: 'text-rose-300', filter: 'critical' as const }, { label: statusConfig.unknown[isZh ? 'zh' : 'en'], value: summary.unknown, icon: CircleHelp, color: 'text-slate-300', filter: 'unknown' as const },
      ].map((card) => { const Icon = card.icon; return <button key={card.label} type="button" onClick={() => card.filter && setStatusFilter(card.filter === statusFilter ? 'all' : card.filter)} className={`rounded-2xl border border-white/10 bg-white/[0.045] p-4 text-left shadow-[0_8px_30px_rgba(0,0,0,0.12)] transition ${card.filter ? 'hover:-translate-y-0.5 hover:border-white/20' : 'cursor-default'} ${card.filter && statusFilter === card.filter ? 'ring-2 ring-cyan-300/40' : ''}`}><div className="flex items-center justify-between gap-2"><span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">{card.label}</span><Icon size={17} className={card.color} /></div><div className={`mt-2 text-3xl font-semibold tabular-nums ${card.color}`}>{card.value}</div></button>; })}</div>
      <div className="mt-4 grid gap-4 xl:grid-cols-[1.05fr_1.5fr]"><section className="rounded-2xl border border-white/10 bg-white/[0.045] p-5 shadow-[0_8px_30px_rgba(0,0,0,0.12)]"><div className="flex items-start justify-between gap-3"><div><p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-cyan-300/70">{labels.distribution}</p><h2 className="mt-1 text-lg font-semibold">{labels.posture}</h2></div><span className="rounded-xl border border-cyan-300/20 bg-cyan-300/10 px-3 py-2 text-xl font-semibold text-cyan-200">{summary.average_score}<small className="ml-1 text-[10px] font-medium text-cyan-200/60">{labels.averageShort}</small></span></div><div className="mt-5 flex items-center gap-6"><div className="relative grid h-36 w-36 shrink-0 place-items-center rounded-full" style={{ background: `conic-gradient(#34d399 0 ${summary.healthy / total * 360}deg, #fbbf24 ${summary.healthy / total * 360}deg ${(summary.healthy + summary.warning) / total * 360}deg, #fb7185 ${(summary.healthy + summary.warning) / total * 360}deg ${(summary.healthy + summary.warning + summary.critical) / total * 360}deg, #64748b ${(summary.healthy + summary.warning + summary.critical) / total * 360}deg 360deg)` }}><div className="grid h-24 w-24 place-items-center rounded-full bg-[#0b1d32]"><span className="text-center"><strong className="block text-2xl">{Math.round(summary.healthy / total * 100)}%</strong><small className="text-[10px] text-slate-400">{labels.healthyRate}</small></span></div></div><div className="min-w-0 flex-1 space-y-3">{distribution.map(({ status, count, percent }) => { const config = statusConfig[status]; const Icon = config.icon; return <div key={status}><div className="flex items-center justify-between text-xs"><span className={`flex items-center gap-2 ${config.color}`}><Icon size={14} /> {isZh ? config.zh : config.en}</span><span className="tabular-nums text-slate-300">{count} <span className="text-slate-500">({percent}%)</span></span></div><div className="mt-1 h-1.5 overflow-hidden rounded-full bg-white/10"><div className={`h-full rounded-full ${config.bar}`} style={{ width: `${percent}%` }} /></div></div>; })}</div></div></section><section className="rounded-2xl border border-white/10 bg-white/[0.045] p-5 shadow-[0_8px_30px_rgba(0,0,0,0.12)]"><div className="flex items-start justify-between gap-3"><div><p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-rose-300/80">{labels.triage}</p><h2 className="mt-1 text-lg font-semibold">{labels.risky}</h2></div><span className="text-xs text-slate-400">{labels.sorted}</span></div><div className="mt-4 grid gap-2 md:grid-cols-2">{riskyDevices.map((device) => { const status = toHealthStatus(device.health_status); const config = statusConfig[status]; const Icon = config.icon; return <button key={device.id} type="button" onClick={() => onShowDetails(device)} className="group flex items-center gap-3 rounded-xl border border-white/10 bg-black/10 px-3 py-3 text-left transition hover:border-cyan-300/30 hover:bg-cyan-300/[0.06]"><span className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl ${config.soft} ${config.color}`}><Icon size={17} /></span><span className="min-w-0 flex-1"><strong className="block truncate text-sm text-slate-100">{device.hostname || device.ip_address || '--'}</strong><small className="mt-0.5 block truncate text-[11px] text-slate-400">{[device.site, device.role, device.platform].filter(Boolean).join(' · ') || labels.noMetadata}</small></span><span className="text-right"><strong className={`block text-lg tabular-nums ${config.color}`}>{Number(device.health_score || 0)}</strong><small className="text-[10px] text-slate-500">{Number(device.open_alert_count || 0)} {labels.alerts}</small></span><ChevronRight size={15} className="text-slate-600 transition group-hover:translate-x-0.5 group-hover:text-cyan-300" /></button>; })}{riskyDevices.length === 0 && <div className="col-span-full rounded-xl border border-dashed border-white/15 px-4 py-8 text-center text-sm text-slate-400">{activeFilters ? labels.noMatch : labels.noRisk}</div>}</div></section></div>
      <section className="mt-4 rounded-2xl border border-white/10 bg-white/[0.045] p-5 shadow-[0_8px_30px_rgba(0,0,0,0.12)]"><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-sky-300/70">{labels.trend}</p><h2 className="mt-1 text-lg font-semibold">{labels.trendTitle}</h2></div><div className="flex items-center gap-2">{[1, 24, 168].map((hours) => <button key={hours} type="button" onClick={() => setRangeHours(hours)} className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition ${rangeHours === hours ? 'bg-cyan-300 text-[#062039]' : 'border border-white/10 text-slate-300 hover:bg-white/10'}`}>{hours === 1 ? '1h' : hours === 24 ? '24h' : '7d'}</button>)}<span className="ml-1 text-xs text-slate-500">{historyLoading ? labels.loading : `${history?.sample_count || 0} ${labels.samples}`}</span></div></div><div className="mt-4 grid gap-4 xl:grid-cols-[1fr_220px]"><div className="h-56 rounded-xl border border-white/10 bg-black/10 p-2">{historySeries.length ? <ResponsiveContainer width="100%" height="100%"><AreaChart data={historySeries} margin={{ top: 8, right: 8, left: -22, bottom: 0 }}><defs><linearGradient id="healthScoreFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#22d3ee" stopOpacity={0.35} /><stop offset="100%" stopColor="#22d3ee" stopOpacity={0} /></linearGradient></defs><CartesianGrid stroke="rgba(148,163,184,0.13)" strokeDasharray="3 5" vertical={false} /><XAxis dataKey="ts" axisLine={false} tickLine={false} tick={{ fill: '#94a3b8', fontSize: 10 }} tickFormatter={(value) => formatTime(String(value), language)} minTickGap={36} /><YAxis domain={[0, 100]} axisLine={false} tickLine={false} tick={{ fill: '#94a3b8', fontSize: 10 }} /><Tooltip contentStyle={{ border: '1px solid rgba(148,163,184,.2)', borderRadius: 12, background: '#0b1d32', color: '#e2e8f0' }} labelFormatter={(value) => formatTime(String(value), language)} /><Area type="monotone" dataKey="average_score" name={isZh ? '\u5e73\u5747\u5065\u5eb7\u5206' : 'Average score'} stroke="#22d3ee" fill="url(#healthScoreFill)" strokeWidth={2} dot={false} isAnimationActive={false} /></AreaChart></ResponsiveContainer> : <div className="grid h-full place-items-center text-sm text-slate-500">{labels.noTrend}</div>}</div><div className="grid grid-cols-2 gap-2 xl:grid-cols-1">{[{ label: labels.latestScore, value: lastPoint?.average_score ?? summary.average_score, color: 'text-cyan-300' }, { label: labels.latestCritical, value: lastPoint?.critical ?? summary.critical, color: 'text-rose-300' }, { label: labels.latestWarning, value: lastPoint?.warning ?? summary.warning, color: 'text-amber-300' }].map((item) => <div key={item.label} className="rounded-xl border border-white/10 bg-black/10 px-3 py-3"><div className="text-[10px] uppercase tracking-widest text-slate-500">{item.label}</div><div className={`mt-1 text-xl font-semibold tabular-nums ${item.color}`}>{item.value}</div></div>)}</div></div></section>
      <section className="mt-4 rounded-2xl border border-white/10 bg-white/[0.045] shadow-[0_8px_30px_rgba(0,0,0,0.12)]"><div className="border-b border-white/10 p-5"><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-cyan-300/70">{labels.inventory}</p><h2 className="mt-1 text-lg font-semibold">{labels.results} <span className="ml-2 text-sm font-normal text-slate-500">{filteredDevices.length}/{devices.length}</span></h2></div>{activeFilters && <button type="button" onClick={clearFilters} className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-xs font-semibold text-slate-300 hover:bg-white/10"><X size={13} /> {labels.clear}</button>}</div><div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-[1.5fr_repeat(4,minmax(0,1fr))]"><label className="relative"><Search size={15} className="pointer-events-none absolute left-3 top-2.5 text-slate-500" /><input value={searchTerm} onChange={(event) => setSearchTerm(event.target.value)} placeholder={labels.search} className="w-full rounded-lg border border-white/10 bg-black/10 py-2 pl-9 pr-3 text-sm text-slate-200 outline-none placeholder:text-slate-600 focus:border-cyan-300/40" /></label><select value={siteFilter} onChange={(event) => setSiteFilter(event.target.value)} className="rounded-lg border border-white/10 bg-[#0b1d32] px-3 py-2 text-sm text-slate-200 outline-none"><option value="all">{labels.allSites}</option>{siteOptions.map((site) => <option key={site} value={site}>{site}</option>)}</select><select value={roleFilter} onChange={(event) => setRoleFilter(event.target.value)} className="rounded-lg border border-white/10 bg-[#0b1d32] px-3 py-2 text-sm text-slate-200 outline-none"><option value="all">{labels.allRoles}</option>{roleOptions.map((role) => <option key={role} value={role}>{role}</option>)}</select><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as typeof statusFilter)} className="rounded-lg border border-white/10 bg-[#0b1d32] px-3 py-2 text-sm text-slate-200 outline-none"><option value="all">{labels.allStates}</option>{(Object.keys(statusConfig) as HealthStatus[]).map((status) => <option key={status} value={status}>{isZh ? statusConfig[status].zh : statusConfig[status].en}</option>)}</select><select value={riskFilter} onChange={(event) => setRiskFilter(event.target.value as typeof riskFilter)} className="rounded-lg border border-white/10 bg-[#0b1d32] px-3 py-2 text-sm text-slate-200 outline-none"><option value="all">{labels.allRisks}</option><option value="alerts">{labels.openAlerts}</option><option value="interfaces">{labels.interfaceRisk}</option></select></div></div><div className="max-h-[480px] overflow-auto"><table className="w-full min-w-[780px] text-left"><thead className="sticky top-0 z-10 bg-[#0b1d32] text-[10px] uppercase tracking-[0.16em] text-slate-500"><tr><th className="px-5 py-3 font-semibold">{labels.device}</th><th className="px-4 py-3 font-semibold">{labels.location}</th><th className="px-4 py-3 font-semibold">{labels.health}</th><th className="px-4 py-3 font-semibold">{labels.score}</th><th className="px-4 py-3 font-semibold">{labels.signals}</th><th className="px-5 py-3 font-semibold">{labels.summary}</th></tr></thead><tbody className="divide-y divide-white/5">{filteredDevices.map((device) => { const status = toHealthStatus(device.health_status); const config = statusConfig[status]; const Icon = config.icon; const signalCount = Number(device.open_alert_count || 0) + Number(device.interface_down_count || 0) + Number(device.interface_flap_count || 0) + Number(device.interface_error_count || 0); return <tr key={device.id} onClick={() => onShowDetails(device)} className="cursor-pointer transition hover:bg-cyan-300/[0.06]"><td className="px-5 py-3"><div className="font-semibold text-slate-100">{device.hostname || '--'}</div><div className="mt-0.5 font-mono text-[11px] text-slate-500">{device.ip_address || '--'}</div></td><td className="px-4 py-3"><div className="text-sm text-slate-300">{device.site || '--'}</div><div className="mt-0.5 text-[11px] text-slate-500">{[device.role, device.platform].filter(Boolean).join(' · ') || '--'}</div></td><td className="px-4 py-3"><span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${config.soft} ${config.color}`}><Icon size={12} /> {isZh ? config.zh : config.en}</span></td><td className={`px-4 py-3 text-base font-semibold tabular-nums ${config.color}`}>{Number(device.health_score || 0)}</td><td className="px-4 py-3"><span className={`inline-flex items-center gap-1.5 text-xs ${signalCount ? 'text-amber-200' : 'text-slate-500'}`}><Filter size={12} /> {signalCount || labels.clearState}</span></td><td className="max-w-[300px] truncate px-5 py-3 text-xs text-slate-400" title={device.health_summary || ''}>{device.health_summary || labels.noIssue}</td></tr>; })}{filteredDevices.length === 0 && <tr><td colSpan={6} className="px-5 py-12 text-center text-sm text-slate-500">{devices.length === 0 ? labels.noData : labels.noMatch}</td></tr>}</tbody></table></div></section>
    </div>
  </div>;
};

export default DeviceHealthTab;
