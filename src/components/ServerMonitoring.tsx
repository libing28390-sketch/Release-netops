import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Server, Search, RefreshCw, Cpu, MemoryStick, HardDrive, Activity,
  Shield, Gauge, Network, AlertTriangle, CheckCircle2, Database, Clock,
} from 'lucide-react';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine } from 'recharts';
import type { Device, HostResourceHistoryPayload, HostResourceSnapshot } from '../types';
import PageHero from './PageHero';
import { useChartTheme } from '../hooks/useChartTheme';
import { useMonitoringStore } from '../store/monitoringStore';
import { VirtualizedDeviceList } from './VirtualizedDeviceList';

interface ServerMonitoringProps {
  language: 'zh' | 'en';
  devices: Device[];
  hostResources: HostResourceSnapshot | null;
  showToast: (message: string, type?: string) => void;
  isAuthenticated?: boolean;
}

type ServerListItem = Device & { isLocalHost?: boolean };

const LOCAL_HOST_ID = '__deployment_host__';

/* ── Metric catalog item (from /api/inspections/items/all) ── */
interface MetricItem {
  check_key: string;
  name: string;
  name_zh: string;
  vendor: string;
  method: string;
  script_id: string;
  warning_threshold: number | null;
  critical_threshold: number | null;
  unit?: string;
}

/* Telemetry sample point keyed by check_key columns */
interface SamplePoint {
  ts: string;
  cpu_load?: number | null;
  cpu_util?: number | null;
  mem_avail?: number | null;
  swap_util?: number | null;
  io_wait?: number | null;
  io_latency?: number | null;
  disk_util?: number | null;
  inode_util?: number | null;
  tcp_conns?: number | null;
  tcp_retrans?: number | null;
  tcp_estab?: number | null;
  tcp_time_wait?: number | null;
  tcp_close_wait?: number | null;
  tcp_syn_recv?: number | null;
  tcp_listen?: number | null;
  process_health?: number | null;
  service_sshd?: number | null;
  service_crond?: number | null;
  service_docker?: number | null;
  [k: string]: any;
}

/* Per-metric display metadata: icon + unit + whether higher is worse */
const METRIC_META: Record<string, { icon: React.ComponentType<any>; unit: string; higherIsWorse: boolean }> = {
  cpu_util:       { icon: Cpu,         unit: '%',    higherIsWorse: true },
  cpu_load:       { icon: Gauge,       unit: '%',    higherIsWorse: true },
  mem_avail:      { icon: MemoryStick, unit: '%',    higherIsWorse: true },
  swap_util:      { icon: MemoryStick, unit: '%',    higherIsWorse: true },
  disk_util:      { icon: HardDrive,   unit: '%',    higherIsWorse: true },
  inode_util:     { icon: HardDrive,   unit: '%',    higherIsWorse: true },
  io_wait:        { icon: Activity,    unit: '%',    higherIsWorse: true },
  io_latency:     { icon: Activity,    unit: 'ms',   higherIsWorse: true },
  tcp_conns:      { icon: Network,     unit: '',     higherIsWorse: true },
  tcp_retrans:    { icon: Network,     unit: '%',    higherIsWorse: true },
  tcp_estab:      { icon: Network,     unit: '',     higherIsWorse: true },
  tcp_time_wait:  { icon: Network,     unit: '',     higherIsWorse: true },
  tcp_close_wait: { icon: Network,     unit: '',     higherIsWorse: true },
  tcp_syn_recv:   { icon: Network,     unit: '',     higherIsWorse: true },
  tcp_listen:     { icon: Network,     unit: '',     higherIsWorse: false },
};

/* Metrics shown on the monitoring page. These now all map to columns that the
   per-minute telemetry sampler (device_telemetry_samples) stores, so each has
   real values + history. */
const METRIC_ORDER = [
  'cpu_util', 'cpu_load', 'mem_avail', 'swap_util', 'disk_util', 'inode_util',
  'io_wait', 'io_latency', 'tcp_conns', 'tcp_retrans',
  'tcp_estab', 'tcp_time_wait', 'tcp_close_wait', 'tcp_syn_recv', 'tcp_listen',
];

const SERVICE_KEYS = [
  { key: 'service_sshd', name: 'SSHD' },
  { key: 'service_docker', name: 'Docker' },
  { key: 'service_crond', name: 'Cron' },
];

const isServerDevice = (d: any): boolean => {
  if (!d) return false;
  const serverKeywords = ['linux', 'ubuntu', 'centos', 'debian', 'redhat', 'rocky', 'alma', 'windows', 'winrm', 'server'];
  const p = (d.platform || '').toLowerCase();
  if (serverKeywords.some((kw) => p.includes(kw))) return true;
  const category = (d.device_category || '').toLowerCase();
  const role = (d.role || '').toLowerCase();
  const assetType = (d.asset_type || '').toLowerCase();
  return category.includes('server') || role.includes('server') || assetType.includes('server');
};

const serverOsBucket = (d: any): 'windows' | 'linux' => {
  const platform = String(d?.platform || '').toLowerCase();
  return platform.includes('windows') || platform.includes('winrm') || platform === 'win' ? 'windows' : 'linux';
};

const authHeaders = (): Record<string, string> => {
  const token = localStorage.getItem('netops_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
};

/* Network platform codes — when a server is mis-tagged with one of these we
   show a clean "Linux" label instead of the raw (misleading) platform value. */
const NETWORK_PLATFORM_CODES = new Set([
  'cisco_ios', 'cisco_nxos', 'cisco_xr', 'cisco_asa', 'cisco_ftd',
  'huawei_vrp', 'huawei_vrpv8', 'huawei', 'h3c_comware', 'h3c_comware_v3',
  'juniper_junos', 'juniper', 'arista_eos', 'paloalto_panos', 'fortinet',
  'checkpoint_gaia', 'hillstone_stoneos', 'ruijie_os', 'ruijie_rgos', 'zte_zxros', 'maipu',
]);

/** Clean OS label for a server device (avoids showing 'cisco_ios' on a Linux host). */
const serverOsLabel = (d: any): string => {
  if (serverOsBucket(d) === 'windows') return 'Windows';
  const raw = String(d?.platform || '').trim();
  if (!raw || NETWORK_PLATFORM_CODES.has(raw.toLowerCase())) {
    // Fall back to a friendly label derived from category/role or generic Linux.
    const cat = String(d?.device_category || '').toLowerCase();
    if (cat.includes('rack')) return 'Linux (Rack Server)';
    return 'Linux';
  }
  return raw;
};

/* ── Radial gauge (circular progress) for percentage metrics ── */
const RadialGauge: React.FC<{
  value: number | null;
  color: string;
  size?: number;
  label: string;
  unit: string;
}> = ({ value, color, size = 120, label, unit }) => {
  const stroke = 9;
  const r = (size - stroke) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const circumference = 2 * Math.PI * r;
  // 270° arc gauge (gap at bottom)
  const arcFraction = 0.75;
  const arcLen = circumference * arcFraction;
  const pct = value != null && Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0;
  const dash = (pct / 100) * arcLen;
  const rotation = 135; // start angle so the gap is centered at bottom
  return (
    <div className="relative flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="block">
        <circle
          cx={cx} cy={cy} r={r} fill="none"
          stroke="currentColor" strokeWidth={stroke} strokeLinecap="round"
          className="text-black/[0.06] dark:text-white/[0.08]"
          strokeDasharray={`${arcLen} ${circumference}`}
          transform={`rotate(${rotation} ${cx} ${cy})`}
        />
        <circle
          cx={cx} cy={cy} r={r} fill="none"
          stroke={color} strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={`${dash} ${circumference}`}
          transform={`rotate(${rotation} ${cx} ${cy})`}
          style={{ transition: 'stroke-dasharray 0.6s ease, stroke 0.3s ease' }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-extrabold tabular-nums" style={{ color }}>
          {value != null && Number.isFinite(value) ? Math.round(value) : '--'}
          {value != null && Number.isFinite(value) && <span className="text-sm font-bold">{unit}</span>}
        </span>
        <span className="mt-0.5 text-[10px] font-semibold uppercase tracking-wider text-[var(--muted-text)]">{label}</span>
      </div>
    </div>
  );
};

const LocalHostMonitoringPanel: React.FC<{
  language: 'zh' | 'en';
  hostResources: HostResourceSnapshot;
  hostResourceHistory: HostResourceHistoryPayload | null;
  hostResourceHistoryLoading: boolean;
  rangeHours: number;
  onRangeChange: (hours: number) => void;
  onRefresh: () => void;
}> = ({ language, hostResources, hostResourceHistory, hostResourceHistoryLoading, rangeHours, onRangeChange, onRefresh }) => {
  const zh = language === 'zh';
  const ct = useChartTheme();
  const series = hostResourceHistory?.series || [];
  const statusLabel = hostResources.status === 'critical' ? (zh ? '严重' : 'Critical') : hostResources.status === 'degraded' ? (zh ? '告警' : 'Degraded') : (zh ? '健康' : 'Healthy');
  const statusClass = hostResources.status === 'critical' ? 'bg-rose-50 text-rose-700 border-rose-200/80' : hostResources.status === 'degraded' ? 'bg-amber-50 text-amber-700 border-amber-200/80' : 'bg-emerald-50 text-emerald-700 border-emerald-200/80';
  const hostOsLabel = serverOsLabel(hostResources);
  const chartData = series.map((point) => ({
    ts: point.ts,
    cpu: point.cpu_percent,
    memory: point.memory_percent,
    disk: point.disk_percent,
  }));
  const rangeOptions = [
    { value: 1, label: '1h' },
    { value: 24, label: '24h' },
    { value: 168, label: '7d' },
  ];
  const formatTime = (value: string) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return rangeHours === 1
      ? date.toLocaleTimeString(zh ? 'zh-CN' : 'en-US', { hour: '2-digit', minute: '2-digit' })
      : date.toLocaleDateString(zh ? 'zh-CN' : 'en-US', { month: '2-digit', day: '2-digit' });
  };

  return (
    <div className="space-y-4">
      {/* Host Summary Hero Card */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-gray-200/70 dark:border-zinc-800/80 bg-white dark:bg-zinc-900/90 p-4 shadow-2xs">
        <div className="flex items-center gap-3.5">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400">
            <Server size={18} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <p className="text-sm font-bold text-gray-900 dark:text-white">{hostResources.hostname || (zh ? '本机部署' : 'Local Host')}</p>
              <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-gray-100 dark:bg-zinc-800 text-gray-600 dark:text-zinc-300 font-mono">
                {hostOsLabel}
              </span>
            </div>
            <p className="text-xs text-gray-400 dark:text-zinc-500 mt-0.5">{zh ? 'Nexora 平台核心服务 · 当前运行宿主机' : 'Nexora Core Platform · Local Host'}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold ${statusClass}`}>
            <span className="h-1.5 w-1.5 rounded-full bg-current" />{statusLabel}
          </span>
        </div>
      </div>

      {/* 4 Bento KPI Cards */}
      <div className="grid grid-cols-2 gap-3.5 lg:grid-cols-4">
        {[
          { label: 'CPU 使用率', value: hostResources.cpu_percent, color: '#2563eb', bg: 'bg-blue-50 text-blue-600', icon: Cpu },
          { label: zh ? '内存使用率' : 'Memory', value: hostResources.memory_percent, color: (hostResources.memory_percent || 0) > 85 ? '#ef4444' : '#f59e0b', bg: (hostResources.memory_percent || 0) > 85 ? 'bg-rose-50 text-rose-600' : 'bg-amber-50 text-amber-600', icon: MemoryStick },
          { label: zh ? '磁盘使用率' : 'Disk', value: hostResources.disk_percent, color: '#10b981', bg: 'bg-emerald-50 text-emerald-600', icon: HardDrive },
        ].map((metric) => (
          <div key={metric.label} className="bg-white dark:bg-zinc-900/90 rounded-2xl border border-gray-200/70 dark:border-zinc-800/80 p-4 shadow-2xs flex flex-col justify-between">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-gray-500 dark:text-zinc-400">{metric.label}</span>
              <div className={`h-7 w-7 rounded-xl flex items-center justify-center ${metric.bg}`}>
                <metric.icon size={14} />
              </div>
            </div>
            <div className="mt-3 flex items-baseline gap-1">
              <span className="text-2xl font-extrabold font-mono text-gray-900 dark:text-white">
                {metric.value != null ? Math.round(metric.value) : '--'}
              </span>
              <span className="text-xs font-bold text-gray-400">%</span>
            </div>
            <div className="mt-2 w-full h-1.5 bg-gray-100 dark:bg-zinc-800 rounded-full overflow-hidden">
              <div 
                className="h-full rounded-full transition-all duration-500" 
                style={{ width: `${Math.min(100, Math.max(0, metric.value || 0))}%`, backgroundColor: metric.color }}
              />
            </div>
          </div>
        ))}

        <div className="bg-white dark:bg-zinc-900/90 rounded-2xl border border-gray-200/70 dark:border-zinc-800/80 p-4 shadow-2xs flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-gray-500 dark:text-zinc-400">{zh ? '运行健康' : 'Runtime'}</span>
            <div className="h-7 w-7 rounded-xl bg-purple-50 dark:bg-purple-950/40 text-purple-600 flex items-center justify-center">
              <Activity size={14} />
            </div>
          </div>
          <div className="mt-3 flex items-baseline gap-1">
            <span className="text-2xl font-extrabold font-mono text-gray-900 dark:text-white">
              {hostResources.uptime_hours != null ? `${Math.round(hostResources.uptime_hours)}` : '--'}
            </span>
            <span className="text-xs font-bold text-gray-400">h</span>
          </div>
          <p className="mt-2 text-[11px] text-gray-400 font-mono">
            Load {hostResources.load_1m?.toFixed(2) ?? '--'}
          </p>
        </div>
      </div>

      {/* Trend Chart */}
      <div className="rounded-2xl border border-gray-200/70 dark:border-zinc-800/80 bg-white dark:bg-zinc-900/90 p-5 shadow-2xs">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-950/40 px-2 py-0.5 rounded-full">
                {zh ? '本机资源趋势' : 'Local Host Trends'}
              </span>
              <h3 className="text-base font-bold text-gray-900 dark:text-white">CPU / {zh ? '内存' : 'Memory'} / {zh ? '磁盘' : 'Disk'}</h3>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex items-center p-0.5 rounded-xl bg-gray-100 dark:bg-zinc-800">
              {rangeOptions.map((option) => (
                <button 
                  key={option.value} 
                  type="button" 
                  onClick={() => onRangeChange(option.value)} 
                  className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer ${rangeHours === option.value ? 'bg-white dark:bg-zinc-700 text-gray-900 dark:text-white shadow-2xs' : 'text-gray-500 dark:text-zinc-400 hover:text-gray-900'}`}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <button 
              type="button" 
              onClick={onRefresh} 
              className="flex items-center gap-1 px-3 py-1.5 rounded-xl text-xs font-semibold text-gray-600 dark:text-zinc-300 bg-gray-50 dark:bg-zinc-800 border border-gray-200/70 dark:border-zinc-700 hover:bg-gray-100 transition-all cursor-pointer"
            >
              <RefreshCw size={11} className={hostResourceHistoryLoading ? 'animate-spin text-blue-600' : ''} />
              <span>{zh ? '刷新' : 'Refresh'}</span>
            </button>
          </div>
        </div>
        <div className="h-[250px]">
          {hostResourceHistoryLoading && chartData.length === 0 ? (
            <div className="flex h-full items-center justify-center text-xs text-gray-400"><RefreshCw size={16} className="mr-2 animate-spin" />{zh ? '加载趋势数据...' : 'Loading trends...'}</div>
          ) : chartData.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-xs text-gray-400"><Database size={24} className="opacity-40" /><span>{zh ? '暂无本机趋势数据' : 'No local host trend data yet'}</span><button type="button" onClick={onRefresh} className="text-xs font-semibold text-blue-600">{zh ? '立即刷新' : 'Refresh now'}</button></div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="localCpuFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#2563eb" stopOpacity={0.24} /><stop offset="100%" stopColor="#2563eb" stopOpacity={0} /></linearGradient>
                  <linearGradient id="localMemoryFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#f97316" stopOpacity={0.2} /><stop offset="100%" stopColor="#f97316" stopOpacity={0} /></linearGradient>
                  <linearGradient id="localDiskFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#10b981" stopOpacity={0.18} /><stop offset="100%" stopColor="#10b981" stopOpacity={0} /></linearGradient>
                </defs>
                <CartesianGrid vertical={false} stroke={ct.gridAlt} strokeOpacity={0.45} />
                <XAxis dataKey="ts" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: ct.axisAlt }} tickFormatter={(value) => formatTime(String(value))} minTickGap={48} />
                <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: ct.axisAlt }} domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tickFormatter={(value) => `${value}%`} width={36} />
                <Tooltip contentStyle={{ borderRadius: 12, border: 'none', background: ct.tooltipBg, color: ct.tooltipText, boxShadow: ct.tooltipShadow, fontSize: 11 }} formatter={(value: any, name: any) => [`${Math.round(Number(value || 0))}%`, String(name)]} labelFormatter={(value) => formatTime(String(value))} />
                <Area type="monotone" dataKey="cpu" name="CPU" stroke="#2563eb" strokeWidth={2} fill="url(#localCpuFill)" isAnimationActive={false} connectNulls />
                <Area type="monotone" dataKey="memory" name={zh ? '内存' : 'Memory'} stroke="#f97316" strokeWidth={2} fill="url(#localMemoryFill)" isAnimationActive={false} connectNulls />
                <Area type="monotone" dataKey="disk" name={zh ? '磁盘' : 'Disk'} stroke="#10b981" strokeWidth={2} fill="url(#localDiskFill)" isAnimationActive={false} connectNulls />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-gray-400">
          <span className="rounded-full bg-gray-100 dark:bg-zinc-800 px-2.5 py-0.5">DB {hostResources.database_ok ? 'OK' : 'ERR'}</span>
          <span className="rounded-full bg-gray-100 dark:bg-zinc-800 px-2.5 py-0.5">{hostResourceHistory?.sample_count || chartData.length} {zh ? '个采样点' : 'samples'}</span>
          <span className="rounded-full bg-gray-100 dark:bg-zinc-800 px-2.5 py-0.5">{zh ? '平台' : 'Platform'}: {hostOsLabel}</span>
        </div>
      </div>
    </div>
  );
};

const ServerMonitoring: React.FC<ServerMonitoringProps> = ({ language, devices, hostResources, showToast, isAuthenticated = true }) => {
  const zh = language === 'zh';
  const ct = useChartTheme();

  const [search, setSearch] = useState('');
  const [metricCatalog, setMetricCatalog] = useState<MetricItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Read ?q= URL param on mount to pre-fill search (deep-link from NPA hop popover)
  useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      const q = params.get('q');
      if (q) {
        setSearch(q);
        const match = (devices || []).find(d => isServerDevice(d) && d.ip_address === q);
        if (match) setSelectedId(String(match.id));
      }
    } catch { /* ignore */ }
  }, [devices]);
  const [series, setSeries] = useState<SamplePoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [rangeHours, setRangeHours] = useState<number>(1);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [focusMetric, setFocusMetric] = useState<string>('cpu_util');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [osFilter, setOsFilter] = useState<'all' | 'windows' | 'linux'>('all');
  const [hostResourceHistory, setHostResourceHistory] = useState<HostResourceHistoryPayload | null>(null);
  const [hostResourceHistoryLoading, setHostResourceHistoryLoading] = useState(false);

  // Filters for listing multiple servers
  const [siteFilter, setSiteFilter] = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<'all' | 'online' | 'offline'>('all');

  // Available time ranges (Zabbix-style), in hours
  const RANGE_OPTIONS: Array<{ h: number; label: string }> = [
    { h: 1, label: '1h' },
    { h: 6, label: '6h' },
    { h: 24, label: '24h' },
    { h: 168, label: '7d' },
    { h: 720, label: '30d' },
  ];

  const serverDevices = useMemo(() => (devices || []).filter(isServerDevice), [devices]);
  const localHostDevice = useMemo<ServerListItem | null>(() => {
    if (!hostResources) return null;
    return {
      id: LOCAL_HOST_ID,
      hostname: hostResources.hostname || (zh ? '本机部署' : 'Local Deployment'),
      ip_address: '',
      platform: serverOsBucket(hostResources) === 'windows' ? 'windows' : 'linux',
      site: zh ? '本机部署' : 'Local Deployment',
      status: 'online',
      device_category: 'server',
      isLocalHost: true,
    } as ServerListItem;
  }, [hostResources, zh]);
  const serverEntries = useMemo<ServerListItem[]>(() => {
    return localHostDevice ? [localHostDevice, ...serverDevices] : serverDevices;
  }, [localHostDevice, serverDevices]);

  const uniqueSites = useMemo(() => {
    const sites = new Set<string>();
    serverEntries.forEach((d) => {
      if (d.site) sites.add(d.site);
    });
    return Array.from(sites).sort();
  }, [serverEntries]);

  const filteredServers = useMemo(() => {
    const q = search.trim().toLowerCase();
    let list = serverEntries;
    if (siteFilter !== 'all') {
      list = list.filter((d) => d.site === siteFilter);
    }
    if (statusFilter === 'online') {
      list = list.filter((d) => String(d.status || '').toLowerCase() === 'online');
    } else if (statusFilter === 'offline') {
      list = list.filter((d) => String(d.status || '').toLowerCase() !== 'online');
    }
    if (osFilter !== 'all') {
      list = list.filter((d) => serverOsBucket(d) === osFilter);
    }
    if (!q) return list;
    return list.filter((d) =>
      (d.hostname || '').toLowerCase().includes(q) || (d.ip_address || '').toLowerCase().includes(q),
    );
  }, [serverEntries, search, siteFilter, statusFilter, osFilter]);

  const selectedDevice = useMemo(
    () => serverEntries.find((d) => d.id === selectedId) || null,
    [serverEntries, selectedId],
  );
  const isLocalHostSelected = selectedDevice?.isLocalHost === true;

  const { monitorSelectedDevice, setMonitorSelectedDevice } = useMonitoringStore();

  // Sync selected device from topology redirects (Zustand store)
  useEffect(() => {
    if (monitorSelectedDevice && isServerDevice(monitorSelectedDevice)) {
      setSelectedId(monitorSelectedDevice.id);
      setMonitorSelectedDevice(null);
    }
  }, [monitorSelectedDevice, setMonitorSelectedDevice]);

  // Auto-select first server once data is available
  useEffect(() => {
    if ((!selectedId || !serverEntries.some((d) => d.id === selectedId)) && filteredServers.length > 0) {
      setSelectedId(filteredServers[0].id);
    }
  }, [filteredServers, selectedId, serverEntries]);

  // Load metric catalog (Linux Shell items) once
  useEffect(() => {
    if (!isAuthenticated) return;
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch('/api/inspections/items/all', { headers: authHeaders() });
        if (!resp.ok) return;
        const json = await resp.json();
        const items: MetricItem[] = Array.isArray(json?.data) ? json.data : [];
        const linuxShell = items.filter(
          (it) => (it.vendor || '').toLowerCase() === 'linux' && (it.method || '').toLowerCase() === 'shell',
        );
        if (!cancelled) setMetricCatalog(linuxShell);
      } catch {
        /* ignore */
      }
    })();
    return () => { cancelled = true; };
  }, [isAuthenticated]);

  const fetchTrend = useCallback(async (deviceId: string, hours: number, signal?: AbortSignal) => {
    const resolution = hours <= 24 ? '1m' : 'auto';
    const resp = await fetch(`/api/monitoring/device/${deviceId}/trend?range_hours=${hours}&resolution=${resolution}`, {
      headers: authHeaders(), signal,
    });
    if (!resp.ok) throw new Error('trend fetch failed');
    const payload = await resp.json();
    const raw = Array.isArray(payload?.series) ? payload.series : [];
    return raw.map((p: any) => ({ ...p, ts: p.ts ?? p.ts_minute ?? p.ts_hour }));
  }, []);

  const fetchHostResourceHistory = useCallback(async (hours = rangeHours) => {
    if (!isAuthenticated) return;
    setHostResourceHistoryLoading(true);
    try {
      const resp = await fetch(`/api/health/resources/history?range_hours=${hours}`, { headers: authHeaders() });
      if (!resp.ok) throw new Error('host trend fetch failed');
      const payload = await resp.json() as HostResourceHistoryPayload;
      setHostResourceHistory(payload);
    } catch {
      setHostResourceHistory(null);
    } finally {
      setHostResourceHistoryLoading(false);
    }
  }, [isAuthenticated, rangeHours]);

  // Load trend series for selected device
  useEffect(() => {
    if (!isAuthenticated || !selectedId || isLocalHostSelected) { setSeries([]); return; }
    let cancelled = false;
    const controller = new AbortController();
    const load = async () => {
      setLoading(true);
      try {
        const data = await fetchTrend(selectedId, rangeHours, controller.signal);
        if (!cancelled) setSeries(data);
      } catch (e) {
        if (!cancelled && !(e instanceof DOMException && e.name === 'AbortError')) {
          setSeries([]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; controller.abort(); };
  }, [isAuthenticated, selectedId, rangeHours, fetchTrend, isLocalHostSelected]);

  useEffect(() => {
    if (!isAuthenticated || !isLocalHostSelected) return;
    void fetchHostResourceHistory(rangeHours);
  }, [fetchHostResourceHistory, isAuthenticated, isLocalHostSelected, rangeHours]);

  // Auto-refresh polling (30s)
  useEffect(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    if (!autoRefresh || !selectedId || isLocalHostSelected) return;
    pollRef.current = setInterval(async () => {
      try {
        const data = await fetchTrend(selectedId, rangeHours);
        setSeries(data);
      } catch { /* ignore */ }
    }, 30000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [autoRefresh, selectedId, rangeHours, fetchTrend, isLocalHostSelected]);

  const doRefresh = useCallback(async () => {
    if (!selectedId) return;
    setRefreshing(true);
    try {
      if (isLocalHostSelected) {
        await fetchHostResourceHistory(rangeHours);
      } else {
        const data = await fetchTrend(selectedId, rangeHours);
        setSeries(data);
      }
    } catch {
      showToast(zh ? '刷新失败' : 'Refresh failed', 'error');
    } finally {
      setTimeout(() => setRefreshing(false), 600);
    }
  }, [selectedId, rangeHours, fetchTrend, fetchHostResourceHistory, isLocalHostSelected, showToast, zh]);

  const latest = series.length > 0 ? series[series.length - 1] : null;

  // Build catalog map by check_key for labels + thresholds
  const catalogMap = useMemo(() => {
    const m: Record<string, MetricItem> = {};
    for (const it of metricCatalog) m[it.check_key] = it;
    return m;
  }, [metricCatalog]);

  // Determine which metrics to show: those in METRIC_ORDER that have either
  // catalog entry or sample data present.
  const visibleMetrics = useMemo(() => {
    return METRIC_ORDER.filter((k) => catalogMap[k] || (latest && latest[k] != null));
  }, [catalogMap, latest]);

  const fmtTime = (ts?: string) => {
    if (!ts) return '';
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return String(ts);
    const pad = (n: number) => String(n).padStart(2, '0');
    if (rangeHours <= 1) return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
    if (rangeHours <= 24) return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
    if (rangeHours <= 168) return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:00`;
    return `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  };

  // Full timestamp for tooltips (history view)
  const fmtFullTime = (ts?: string) => {
    if (!ts) return '';
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return String(ts);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };

  const metricLabel = (key: string) => {
    const item = catalogMap[key];
    if (item) return zh ? (item.name_zh || item.name) : (item.name || item.name_zh);
    // Fallback labels for metrics without a catalog entry
    const fallback: Record<string, [string, string]> = {
      cpu_util: ['CPU 使用率', 'CPU Usage'],
      cpu_load: ['CPU 负载', 'CPU Load'],
      mem_avail: ['内存使用率', 'Memory Usage'],
      swap_util: ['Swap 使用率', 'Swap Usage'],
      disk_util: ['磁盘使用率', 'Disk Usage'],
      inode_util: ['Inode 使用率', 'Inode Usage'],
      io_wait: ['IO Wait', 'IO Wait'],
      io_latency: ['磁盘 IO 延迟', 'Disk IO Latency'],
      tcp_conns: ['活动连接总数', 'Active Connections'],
      tcp_retrans: ['TCP 重传率', 'TCP Retransmission'],
      tcp_estab: ['ESTABLISHED 连接数', 'ESTABLISHED'],
      tcp_time_wait: ['TIME_WAIT 连接数', 'TIME_WAIT'],
      tcp_close_wait: ['CLOSE_WAIT 连接数', 'CLOSE_WAIT'],
      tcp_syn_recv: ['SYN_RECV 连接数', 'SYN_RECV'],
      tcp_listen: ['LISTEN 端口数', 'LISTEN Ports'],
    };
    const f = fallback[key];
    return f ? (zh ? f[0] : f[1]) : key;
  };

  /** status tone for a metric value vs its thresholds */
  const metricTone = (key: string, value: number | null | undefined): 'ok' | 'warning' | 'critical' | 'none' => {
    if (value == null || !Number.isFinite(value)) return 'none';
    const item = catalogMap[key];
    if (!item) return 'ok';
    const w = item.warning_threshold;
    const c = item.critical_threshold;
    if (key === 'process_health') {
      if (c != null && value <= c) return 'critical';
      if (w != null && value < w) return 'warning';
      return 'ok';
    }
    if (c != null && value >= c) return 'critical';
    if (w != null && value >= w) return 'warning';
    return 'ok';
  };

  const toneColor: Record<string, string> = {
    ok: '#10b981', warning: '#f59e0b', critical: '#ef4444', none: '#94a3b8',
  };

  const fmtValue = (key: string, value: number | null | undefined) => {
    if (value == null || !Number.isFinite(value)) return '--';
    const meta = METRIC_META[key];
    const unit = meta?.unit ?? '';
    if (unit === '%') return `${Math.round(value)}%`;
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  };

  /* ── Empty state: no servers ── */
  if (serverEntries.length === 0) {
    return (
      <div className="flex flex-col h-full overflow-hidden">
        <PageHero
          icon={Server}
          title={zh ? '服务器监控' : 'Server Monitoring'}
          subtitle={zh ? 'Windows / Linux 主机性能遥测 · 本机资源与服务器指标' : 'Windows / Linux host telemetry · Local resources and server metrics'}
        />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center max-w-md px-6">
            <Server size={40} className="mx-auto mb-3 text-[var(--muted-text)] opacity-40" />
            <p className="text-sm font-semibold text-[var(--app-text)]">{zh ? '暂无服务器设备' : 'No server devices'}</p>
            <p className="mt-1 text-xs text-[var(--muted-text)]">
              {zh
                ? '请在「资产管理」中添加 Windows / Linux 平台或分类为服务器的设备。'
                : 'Add Windows / Linux devices or server-class assets in Asset Management.'}
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHero
        icon={Server}
        title={zh ? '服务器监控' : 'Server Monitoring'}
        subtitle={zh ? 'Windows / Linux 主机性能遥测 · 本机资源与服务器指标' : 'Windows / Linux host telemetry · Local resources and server metrics'}
        actions={
          <div className="flex items-center gap-2">
            <div className="flex items-center p-0.5 rounded-xl bg-gray-100 dark:bg-zinc-800">
              {RANGE_OPTIONS.map((opt) => (
                <button
                  key={opt.h}
                  type="button"
                  onClick={() => setRangeHours(opt.h)}
                  className={`px-3 py-1 text-xs font-semibold rounded-lg transition-all cursor-pointer ${rangeHours === opt.h ? 'bg-white dark:bg-zinc-700 text-gray-900 dark:text-white shadow-2xs' : 'text-gray-500 dark:text-zinc-400 hover:text-gray-900'}`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={() => setAutoRefresh(!autoRefresh)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold border transition-all cursor-pointer ${autoRefresh ? 'border-emerald-200/80 bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-800' : 'border-gray-200/70 bg-white text-gray-500 dark:bg-zinc-800 dark:border-zinc-700 dark:text-zinc-400'}`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${autoRefresh ? 'bg-emerald-500 animate-pulse' : 'bg-gray-300'}`} />
              {autoRefresh ? '30s' : 'OFF'}
            </button>
            <button
              type="button"
              disabled={refreshing}
              onClick={doRefresh}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold border border-gray-200/70 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-gray-700 dark:text-zinc-200 hover:bg-gray-50 transition-all cursor-pointer"
            >
              <RefreshCw size={12} className={refreshing ? 'animate-spin text-blue-600' : ''} />
              <span>{zh ? '刷新' : 'Refresh'}</span>
            </button>
          </div>
        }
      />

      <div className="flex-1 overflow-hidden flex">
        {/* ── Left: server list ── */}
        <div className="w-[270px] shrink-0 border-r border-gray-200/70 dark:border-zinc-800/80 bg-gray-50/40 dark:bg-zinc-900/30 flex flex-col overflow-hidden">
          <div className="p-3 border-b border-gray-200/70 dark:border-zinc-800/80 space-y-2.5">
            {/* Search Input */}
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={13} />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={zh ? '搜索主机名 / IP...' : 'Search host / IP...'}
                className="w-full pl-8 pr-3 py-1.5 bg-white dark:bg-zinc-800 border border-gray-200/80 dark:border-zinc-700 rounded-xl text-xs outline-none focus:border-blue-500 text-gray-800 dark:text-zinc-100 placeholder-gray-400 shadow-2xs"
              />
            </div>

            {/* Site Dropdown Selector */}
            <select
              value={siteFilter}
              onChange={(e) => setSiteFilter(e.target.value)}
              className="w-full bg-white dark:bg-zinc-800 border border-gray-200/80 dark:border-zinc-700 rounded-xl px-2.5 py-1.5 text-xs outline-none text-gray-700 dark:text-zinc-200 focus:border-blue-500 shadow-2xs cursor-pointer"
            >
              <option value="all">{zh ? '全部区域' : 'All Sites'}</option>
              {uniqueSites.map((site) => (
                <option key={site} value={site}>{site}</option>
              ))}
            </select>

            {/* Status Filter Buttons */}
            <div className="flex rounded-xl bg-gray-200/60 dark:bg-zinc-800 p-0.5">
              {(['all', 'online', 'offline'] as const).map((status) => (
                <button
                  key={status}
                  type="button"
                  onClick={() => setStatusFilter(status)}
                  className={`flex-1 py-1 rounded-lg text-[11px] font-semibold transition-all cursor-pointer ${statusFilter === status ? 'bg-white dark:bg-zinc-700 text-gray-900 dark:text-white shadow-2xs' : 'text-gray-500 dark:text-zinc-400 hover:text-gray-800'}`}
                >
                  {status === 'all' && (zh ? '全部' : 'All')}
                  {status === 'online' && (zh ? '在线' : 'Online')}
                  {status === 'offline' && (zh ? '离线' : 'Offline')}
                </button>
              ))}
            </div>

            <div className="flex rounded-xl bg-gray-200/60 dark:bg-zinc-800 p-0.5">
              {(['all', 'windows', 'linux'] as const).map((os) => (
                <button
                  key={os}
                  type="button"
                  onClick={() => setOsFilter(os)}
                  className={`flex-1 py-1 rounded-lg text-[11px] font-semibold transition-all cursor-pointer ${osFilter === os ? 'bg-white dark:bg-zinc-700 text-gray-900 dark:text-white shadow-2xs' : 'text-gray-500 dark:text-zinc-400 hover:text-gray-800'}`}
                >
                  {os === 'all' ? (zh ? '全部系统' : 'All OS') : os === 'windows' ? 'Windows' : 'Linux'}
                </button>
              ))}
            </div>

            <div className="flex items-center justify-between text-[11px] font-medium text-gray-400 px-0.5">
              <span>{filteredServers.length} {zh ? '台在管服务器' : 'servers'}</span>
            </div>
          </div>

          <VirtualizedDeviceList
            items={filteredServers}
            getKey={(srv) => srv.id}
            empty={<p className="p-4 text-center text-xs text-gray-400">{zh ? '无匹配服务器' : 'No match'}</p>}
            renderItem={(srv) => {
              const online = String(srv.status || '').toLowerCase() === 'online';
              const active = selectedId === srv.id;
              return (
                <button
                  type="button"
                  onClick={() => setSelectedId(srv.id)}
                  className={`w-full flex items-center gap-2.5 rounded-2xl border px-3 py-2.5 text-left transition-all cursor-pointer mb-1.5 ${active ? 'border-blue-500/50 bg-blue-50/70 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300 shadow-2xs' : 'border-transparent bg-white/70 dark:bg-zinc-800/40 hover:border-gray-200 dark:hover:border-zinc-700 hover:bg-white'}`}
                >
                  <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-xl ${active ? 'bg-blue-600 text-white' : 'bg-gray-100 dark:bg-zinc-700 text-gray-500 dark:text-zinc-400'}`}>
                    <Server size={14} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-1.5">
                      <p className={`truncate text-xs font-bold ${active ? 'text-blue-900 dark:text-blue-100' : 'text-gray-800 dark:text-zinc-200'}`}>
                        {srv.hostname || srv.ip_address}
                      </p>
                      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${online ? 'bg-emerald-500' : 'bg-gray-300'}`} />
                    </div>
                    <div className="flex items-center justify-between gap-1.5 mt-0.5">
                      <p className="truncate text-[10px] font-mono text-gray-400">
                        {srv.isLocalHost ? (zh ? '当前部署主机' : 'Local Host') : srv.ip_address}
                      </p>
                      <span className="shrink-0 rounded-md bg-gray-100 dark:bg-zinc-700/80 px-1.5 py-0.2 text-[9px] font-medium text-gray-500 dark:text-zinc-400">
                        {serverOsLabel(srv)}
                      </span>
                    </div>
                  </div>
                </button>
              );
            }}
          />
        </div>

        {/* ── Right: metrics ── */}
        <div className="flex-1 overflow-auto p-5 space-y-5">
          {!selectedDevice ? (
            <div className="flex h-full items-center justify-center text-sm text-[var(--muted-text)]">
              {zh ? '从左侧选择一台服务器' : 'Select a server from the left'}
            </div>
          ) : (
            <>
              {/* Header strip */}
              <div className="flex items-center justify-between rounded-2xl border border-gray-200/70 dark:border-zinc-800/80 bg-white dark:bg-zinc-900/90 p-4 shadow-2xs">
                <div className="flex items-center gap-3.5">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400">
                    <Server size={18} />
                  </div>
                  <div>
                    <p className="text-base font-bold text-gray-900 dark:text-white">{selectedDevice.hostname || selectedDevice.ip_address}</p>
                    <p className="text-xs font-mono text-gray-400">
                      {selectedDevice.ip_address} · {serverOsLabel(selectedDevice)}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2 text-xs text-gray-400">
                  <Clock size={13} />
                  {latest?.ts ? (zh ? `最近采样 ${fmtTime(latest.ts)}` : `Last ${fmtTime(latest.ts)}`) : (zh ? '等待数据' : 'Awaiting data')}
                </div>
              </div>

              {isLocalHostSelected ? (
                <LocalHostMonitoringPanel
                  language={language}
                  hostResources={hostResources!}
                  hostResourceHistory={hostResourceHistory}
                  hostResourceHistoryLoading={hostResourceHistoryLoading}
                  rangeHours={rangeHours}
                  onRangeChange={setRangeHours}
                  onRefresh={() => void fetchHostResourceHistory(rangeHours)}
                />
              ) : (
                <>
              {/* Services row */}
              <div className="grid grid-cols-3 gap-3">
                {SERVICE_KEYS.map((srv) => {
                  const up = latest?.[srv.key] === 1;
                  const hasData = latest?.[srv.key] != null;
                  return (
                    <div
                      key={srv.key}
                      className={`flex items-center gap-3 rounded-2xl border p-4 shadow-2xs transition-all ${!hasData ? 'border-gray-200/70 bg-white dark:bg-zinc-900/90 dark:border-zinc-800' : up ? 'border-emerald-200/80 bg-emerald-50/50 dark:bg-emerald-950/30' : 'border-rose-200/80 bg-rose-50/50 dark:bg-rose-950/30'}`}
                    >
                      <div className={`flex h-8 w-8 items-center justify-center rounded-xl ${!hasData ? 'bg-gray-100 text-gray-400' : up ? 'bg-emerald-500 text-white' : 'bg-rose-500 text-white'}`}>
                        <Shield size={16} />
                      </div>
                      <div>
                        <p className="text-xs font-bold text-gray-900 dark:text-white">{srv.name}</p>
                        <p className={`text-[10px] font-extrabold uppercase mt-0.5 ${!hasData ? 'text-gray-400' : up ? 'text-emerald-700 dark:text-emerald-400' : 'text-rose-700 dark:text-rose-400'}`}>
                          {!hasData ? '--' : up ? (zh ? '运行中' : 'Active') : (zh ? '未运行' : 'Inactive')}
                        </p>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Metric cards */}
              {loading && series.length === 0 ? (
                <div className="flex h-40 items-center justify-center gap-2 text-sm text-[var(--muted-text)]">
                  <RefreshCw size={16} className="animate-spin" />
                  {zh ? '加载遥测数据...' : 'Loading telemetry...'}
                </div>
              ) : series.length === 0 ? (
                <div className="flex h-40 flex-col items-center justify-center gap-2 text-center">
                  <Database size={26} className="text-[var(--muted-text)] opacity-40" />
                  <p className="text-sm font-medium text-[var(--muted-text)]">{zh ? '暂无遥测数据' : 'No telemetry data yet'}</p>
                  <p className="max-w-xs text-[11px] text-[var(--muted-text)] opacity-60">
                    {zh
                      ? '系统每分钟自动执行 Linux 指标脚本采集，待数据累积后将自动显示。'
                      : 'The platform samples Linux metrics every minute; data will appear once collected.'}
                  </p>
                </div>
              ) : (
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
                  {visibleMetrics.map((key) => {
                    const meta = METRIC_META[key] || { icon: Activity, unit: '', higherIsWorse: true };
                    const Icon = meta.icon;
                    const value = latest?.[key] as number | null | undefined;
                    const tone = metricTone(key, value as number);
                    const color = toneColor[tone];
                    const item = catalogMap[key];
                    const chartData = series.map((p) => ({ ts: p.ts, v: p[key] == null ? null : Number(p[key]) }));
                    const isPercent = meta.unit === '%';
                    const toneBadge =
                      tone === 'critical'
                        ? { cls: 'bg-red-50 text-red-600', label: zh ? '超阈值' : 'Critical', Ico: AlertTriangle }
                        : tone === 'warning'
                          ? { cls: 'bg-amber-50 text-amber-600', label: zh ? '告警' : 'Warning', Ico: AlertTriangle }
                          : tone === 'ok'
                            ? { cls: 'bg-emerald-50 text-emerald-600', label: zh ? '正常' : 'OK', Ico: CheckCircle2 }
                            : { cls: 'bg-slate-100 text-slate-500', label: '--', Ico: Activity };
                    return (
                      <button
                        type="button"
                        key={key}
                        onClick={() => setFocusMetric(key)}
                        className={`rounded-2xl border bg-white dark:bg-zinc-900/90 p-4 text-left transition-all hover:shadow-md cursor-pointer ${focusMetric === key ? 'border-blue-500 ring-2 ring-blue-500/20 shadow-sm' : 'border-gray-200/70 dark:border-zinc-800/80'}`}
                      >
                        {/* Card header */}
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2.5">
                            <div className="flex h-8 w-8 items-center justify-center rounded-xl" style={{ backgroundColor: `${color}18`, color }}>
                              <Icon size={15} />
                            </div>
                            <div>
                              <p className="text-xs font-bold text-gray-900 dark:text-white">{metricLabel(key)}</p>
                              <p className="text-[9px] font-mono uppercase tracking-wider text-gray-400">{key}</p>
                            </div>
                          </div>
                          <span className={`inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-[9px] font-bold ${toneBadge.cls}`}>
                            <toneBadge.Ico size={9} />{toneBadge.label}
                          </span>
                        </div>

                        {/* Graphical body */}
                        <div className="mt-3 flex items-center gap-3">
                          {isPercent ? (
                            <RadialGauge value={value ?? null} color={color} size={104} label={zh ? '当前' : 'Now'} unit="%" />
                          ) : (
                            <div className="flex h-[104px] w-[104px] shrink-0 flex-col items-center justify-center rounded-2xl border border-gray-100 dark:border-zinc-800 bg-gray-50/70 dark:bg-zinc-800/40">
                              <span className="text-2xl font-extrabold tabular-nums font-mono" style={{ color }}>{fmtValue(key, value)}</span>
                              <span className="mt-0.5 text-[10px] font-semibold uppercase tracking-wider text-gray-400">{zh ? '当前' : 'Now'}</span>
                            </div>
                          )}

                          {/* Trend sparkline */}
                          <div className="h-[104px] flex-1">
                            <ResponsiveContainer width="100%" height="100%">
                              <AreaChart data={chartData} margin={{ top: 8, right: 4, left: 4, bottom: 0 }}>
                                <defs>
                                  <linearGradient id={`grad-${key}`} x1="0" y1="0" x2="0" y2="1">
                                    <stop offset="0%" stopColor={color} stopOpacity={0.28} />
                                    <stop offset="100%" stopColor={color} stopOpacity={0.02} />
                                  </linearGradient>
                                </defs>
                                <CartesianGrid strokeDasharray="2 4" vertical={false} stroke={ct.gridAlt} />
                                <XAxis dataKey="ts" hide />
                                <YAxis hide domain={isPercent ? [0, 100] : ['auto', 'auto']} />
                                <Tooltip
                                  contentStyle={{ borderRadius: 10, border: 'none', padding: '4px 8px', background: ct.tooltipBg, color: ct.tooltipText, fontSize: '11px', boxShadow: ct.tooltipShadow }}
                                  labelFormatter={(v) => fmtTime(String(v))}
                                  formatter={(v: any) => [fmtValue(key, v == null ? null : Number(v)), metricLabel(key)]}
                                />
                                <Area type="monotone" dataKey="v" stroke={color} strokeWidth={1.8} fill={`url(#grad-${key})`} isAnimationActive={false} connectNulls />
                              </AreaChart>
                            </ResponsiveContainer>
                          </div>
                        </div>

                        {/* Threshold legend */}
                        {item && (item.warning_threshold != null || item.critical_threshold != null) && (
                          <div className="mt-2 flex items-center gap-3 border-t border-gray-100 dark:border-zinc-800 pt-2 text-[9px] font-semibold text-gray-400">
                            {item.warning_threshold != null && (
                              <span className="inline-flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-amber-500" />{zh ? '告警阈值' : 'Warn'} {item.warning_threshold}{meta.unit}</span>
                            )}
                            {item.critical_threshold != null && (
                              <span className="inline-flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-red-500" />{zh ? '严重阈值' : 'Crit'} {item.critical_threshold}{meta.unit}</span>
                            )}
                          </div>
                        )}
                      </button>
                    );
                  })}
                </div>
              )}

              {/* ── Historical time-series (Zabbix-style) ── */}
              {series.length > 0 && (() => {
                const meta = METRIC_META[focusMetric] || { icon: Activity, unit: '', higherIsWorse: true };
                const isPercent = meta.unit === '%';
                const item = catalogMap[focusMetric];
                const histData = series.map((p) => ({ ts: p.ts, v: p[focusMetric] == null ? null : Number(p[focusMetric]) }));
                const vals = histData.map((d) => d.v).filter((v): v is number => v != null && Number.isFinite(v));
                const minV = vals.length ? Math.min(...vals) : 0;
                const maxV = vals.length ? Math.max(...vals) : 0;
                const avgV = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
                const curV = vals.length ? vals[vals.length - 1] : null;
                const lineColor = '#2563eb';
                const rangeLabel = RANGE_OPTIONS.find((r) => r.h === rangeHours)?.label || `${rangeHours}h`;
                return (
                  <div className="rounded-2xl border border-gray-200/70 dark:border-zinc-800/80 bg-white dark:bg-zinc-900/90 p-5 shadow-2xs">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-blue-600 bg-blue-50 px-2 py-0.5 rounded-full">
                            {zh ? '历史趋势' : 'History'}
                          </span>
                          <h3 className="text-base font-bold text-gray-900 dark:text-white">{metricLabel(focusMetric)}</h3>
                        </div>
                        <p className="text-xs text-gray-400 dark:text-zinc-500 mt-1">
                          {zh ? `最近 ${rangeLabel} · ${histData.length} 个采样点` : `Last ${rangeLabel} · ${histData.length} samples`}
                        </p>
                      </div>
                      {/* Metric chips to switch focus */}
                      <div className="flex flex-wrap gap-1.5">
                        {visibleMetrics.map((k) => (
                          <button
                            key={k}
                            type="button"
                            onClick={() => setFocusMetric(k)}
                            className={`rounded-xl px-2.5 py-1 text-xs font-semibold transition-all cursor-pointer ${focusMetric === k ? 'bg-blue-600 text-white shadow-2xs' : 'bg-gray-100 dark:bg-zinc-800 text-gray-600 dark:text-zinc-300 hover:bg-gray-200'}`}
                          >
                            {metricLabel(k)}
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Stat summary row */}
                    <div className="mt-3 grid grid-cols-4 gap-2.5">
                      {[
                        { label: zh ? '当前' : 'Current', v: curV },
                        { label: zh ? '最小' : 'Min', v: minV },
                        { label: zh ? '平均' : 'Avg', v: avgV },
                        { label: zh ? '最大' : 'Max', v: maxV },
                      ].map((s) => (
                        <div key={s.label} className="rounded-xl border border-gray-100 dark:border-zinc-800 bg-gray-50/70 dark:bg-zinc-800/40 p-3">
                          <p className="text-[11px] font-semibold text-gray-400">{s.label}</p>
                          <p className="text-lg font-extrabold font-mono text-gray-900 dark:text-white mt-1">{fmtValue(focusMetric, s.v)}</p>
                        </div>
                      ))}
                    </div>

                    {/* Large historical line chart */}
                    <div className="mt-3 h-[300px]">
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={histData} margin={{ top: 10, right: 16, left: 0, bottom: 0 }}>
                          <defs>
                            <linearGradient id="hist-grad" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="0%" stopColor={lineColor} stopOpacity={0.22} />
                              <stop offset="100%" stopColor={lineColor} stopOpacity={0.02} />
                            </linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="2 4" vertical={false} stroke={ct.gridAlt} />
                          <XAxis
                            dataKey="ts"
                            axisLine={false}
                            tickLine={false}
                            tick={{ fontSize: 10, fill: ct.axisAlt }}
                            minTickGap={40}
                            tickFormatter={(v) => fmtTime(String(v))}
                          />
                          <YAxis
                            axisLine={false}
                            tickLine={false}
                            tick={{ fontSize: 10, fill: ct.axisAlt }}
                            domain={isPercent ? [0, 100] : ['auto', 'auto']}
                            tickFormatter={(v) => (isPercent ? `${v}%` : String(v))}
                            width={44}
                          />
                          <Tooltip
                            contentStyle={{ borderRadius: 12, borderColor: ct.tooltipBorder, padding: '8px 12px', background: ct.tooltipBg, color: ct.tooltipText, fontSize: '12px' }}
                            labelFormatter={(v) => fmtFullTime(String(v))}
                            formatter={(v: any) => [fmtValue(focusMetric, v == null ? null : Number(v)), metricLabel(focusMetric)]}
                          />
                          {/* Threshold reference lines */}
                          {item?.warning_threshold != null && (
                            <ReferenceLine y={item.warning_threshold} stroke="#f59e0b" strokeDasharray="4 4" strokeWidth={1} />
                          )}
                          {item?.critical_threshold != null && (
                            <ReferenceLine y={item.critical_threshold} stroke="#ef4444" strokeDasharray="4 4" strokeWidth={1} />
                          )}
                          <Area type="monotone" dataKey="v" stroke={lineColor} strokeWidth={2} fill="url(#hist-grad)" isAnimationActive={false} connectNulls dot={false} />
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>
                    {item && (item.warning_threshold != null || item.critical_threshold != null) && (
                      <div className="mt-2 flex items-center gap-4 text-[10px] font-semibold text-[var(--muted-text)]">
                        {item.warning_threshold != null && (
                          <span className="inline-flex items-center gap-1"><span className="h-2 w-3 rounded-sm bg-amber-500/70" />{zh ? '告警阈值' : 'Warning'} {item.warning_threshold}{meta.unit}</span>
                        )}
                        {item.critical_threshold != null && (
                          <span className="inline-flex items-center gap-1"><span className="h-2 w-3 rounded-sm bg-red-500/70" />{zh ? '严重阈值' : 'Critical'} {item.critical_threshold}{meta.unit}</span>
                        )}
                      </div>
                    )}
                  </div>
                );
              })()}
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default ServerMonitoring;
