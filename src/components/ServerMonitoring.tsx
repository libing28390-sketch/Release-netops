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
const METRIC_META: Record<string, { icon: React.ElementType; unit: string; higherIsWorse: boolean }> = {
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
  'huawei_vrp', 'huawei_vrpv8', 'huawei', 'h3c_comware', 'hp_comware',
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
  const statusClass = hostResources.status === 'critical' ? 'bg-red-50 text-red-700 border-red-200' : hostResources.status === 'degraded' ? 'bg-amber-50 text-amber-700 border-amber-200' : 'bg-emerald-50 text-emerald-700 border-emerald-200';
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
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] px-5 py-3.5">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-500/10 text-indigo-600"><Server size={18} /></span>
          <div>
            <p className="text-base font-bold text-[var(--app-text)]">{hostResources.hostname || (zh ? '本机部署' : 'Local Deployment')}</p>
            <p className="text-[11px] text-[var(--muted-text)]">{zh ? `${hostOsLabel} 服务器 · 当前部署主机` : `${hostOsLabel} server · Current deployment host`}</p>
          </div>
        </div>
        <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-bold ${statusClass}`}>
          <span className="h-1.5 w-1.5 rounded-full bg-current" />{statusLabel}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          { label: 'CPU', value: hostResources.cpu_percent, color: '#0ea5e9' },
          { label: zh ? '内存' : 'Memory', value: hostResources.memory_percent, color: '#f97316' },
          { label: zh ? '磁盘' : 'Disk', value: hostResources.disk_percent, color: '#10b981' },
        ].map((metric) => (
          <div key={metric.label} className="flex items-center justify-center rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] py-3">
            <RadialGauge value={metric.value} color={metric.color} size={104} label={metric.label} unit="%" />
          </div>
        ))}
        <div className="flex flex-col justify-center rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] px-4 py-3">
          <p className="text-[10px] font-bold uppercase tracking-wider text-[var(--muted-text)]">{zh ? '运行信息' : 'Runtime'}</p>
          <p className="mt-2 text-xl font-extrabold text-[var(--app-text)]">{hostResources.uptime_hours != null ? `${Math.round(hostResources.uptime_hours)}h` : '--'}</p>
          <p className="mt-1 text-[11px] text-[var(--muted-text)]">Load {hostResources.load_1m?.toFixed(2) ?? '--'}</p>
        </div>
      </div>

      <div className="rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-indigo-600">{zh ? '本机资源趋势' : 'Local Host Trends'}</p>
            <h3 className="mt-1 text-lg font-bold text-[var(--app-text)]">CPU / {zh ? '内存' : 'Memory'} / {zh ? '磁盘' : 'Disk'}</h3>
          </div>
          <div className="flex items-center gap-2">
            <div className="inline-flex rounded-xl bg-black/[0.04] p-0.5">
              {rangeOptions.map((option) => (
                <button key={option.value} type="button" onClick={() => onRangeChange(option.value)} className={`rounded-lg px-2.5 py-1 text-[10px] font-bold ${rangeHours === option.value ? 'bg-white text-[var(--app-text)] shadow-sm' : 'text-[var(--muted-text)]'}`}>
                  {option.label}
                </button>
              ))}
            </div>
            <button type="button" onClick={onRefresh} className="inline-flex items-center gap-1 rounded-lg border border-[var(--card-border)] px-2.5 py-1.5 text-[10px] font-semibold text-[var(--muted-text)] hover:border-indigo-300 hover:text-indigo-600">
              <RefreshCw size={11} className={hostResourceHistoryLoading ? 'animate-spin' : ''} />{zh ? '刷新' : 'Refresh'}
            </button>
          </div>
        </div>
        <div className="mt-4 h-[260px]">
          {hostResourceHistoryLoading && chartData.length === 0 ? (
            <div className="flex h-full items-center justify-center text-sm text-[var(--muted-text)]"><RefreshCw size={16} className="mr-2 animate-spin" />{zh ? '加载趋势数据...' : 'Loading trends...'}</div>
          ) : chartData.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-sm text-[var(--muted-text)]"><Database size={26} className="opacity-40" /><span>{zh ? '暂无本机趋势数据' : 'No local host trend data yet'}</span><button type="button" onClick={onRefresh} className="text-xs font-semibold text-indigo-600">{zh ? '立即刷新' : 'Refresh now'}</button></div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="localCpuFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#0ea5e9" stopOpacity={0.24} /><stop offset="100%" stopColor="#0ea5e9" stopOpacity={0} /></linearGradient>
                  <linearGradient id="localMemoryFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#f97316" stopOpacity={0.2} /><stop offset="100%" stopColor="#f97316" stopOpacity={0} /></linearGradient>
                  <linearGradient id="localDiskFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#10b981" stopOpacity={0.18} /><stop offset="100%" stopColor="#10b981" stopOpacity={0} /></linearGradient>
                </defs>
                <CartesianGrid vertical={false} stroke={ct.gridAlt} strokeOpacity={0.45} />
                <XAxis dataKey="ts" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: ct.axisAlt }} tickFormatter={(value) => formatTime(String(value))} minTickGap={48} />
                <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: ct.axisAlt }} domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tickFormatter={(value) => `${value}%`} width={36} />
                <Tooltip contentStyle={{ borderRadius: 12, border: '1px solid rgba(255,255,255,0.06)', background: 'rgba(15, 23, 42, 0.94)', color: '#f1f5f9', fontSize: 12 }} formatter={(value: any, name: any) => [`${Math.round(Number(value || 0))}%`, String(name)]} labelFormatter={(value) => formatTime(String(value))} />
                <Area type="monotone" dataKey="cpu" name="CPU" stroke="#0ea5e9" strokeWidth={2} fill="url(#localCpuFill)" isAnimationActive={false} connectNulls />
                <Area type="monotone" dataKey="memory" name={zh ? '内存' : 'Memory'} stroke="#f97316" strokeWidth={2} fill="url(#localMemoryFill)" isAnimationActive={false} connectNulls />
                <Area type="monotone" dataKey="disk" name={zh ? '磁盘' : 'Disk'} stroke="#10b981" strokeWidth={2} fill="url(#localDiskFill)" isAnimationActive={false} connectNulls />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-[var(--muted-text)]">
          <span className="rounded-full bg-black/[0.04] px-2.5 py-1">DB {hostResources.database_ok ? 'OK' : 'ERR'}</span>
          <span className="rounded-full bg-black/[0.04] px-2.5 py-1">{hostResourceHistory?.sample_count || chartData.length} {zh ? '个采样点' : 'samples'}</span>
          <span className="rounded-full bg-black/[0.04] px-2.5 py-1">{zh ? '平台' : 'Platform'}: {hostOsLabel}</span>
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
          <>
            <div className="inline-flex rounded-xl border border-[var(--card-border)] overflow-hidden">
              {RANGE_OPTIONS.map((opt) => (
                <button
                  key={opt.h}
                  type="button"
                  onClick={() => setRangeHours(opt.h)}
                  className={`px-3 py-1.5 text-[11px] font-bold transition-all ${rangeHours === opt.h ? 'bg-[var(--app-text)] text-[var(--card-bg)]' : 'text-[var(--muted-text)] hover:bg-black/[0.04]'}`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={() => setAutoRefresh(!autoRefresh)}
              className={`inline-flex items-center gap-1.5 rounded-xl border px-2.5 py-1.5 text-[10px] font-bold uppercase tracking-wider transition-all ${autoRefresh ? 'border-emerald-300 bg-emerald-50 text-emerald-700' : 'border-[var(--card-border)] bg-[var(--card-bg)] text-[var(--muted-text)]'}`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${autoRefresh ? 'bg-emerald-500 animate-pulse' : 'bg-black/20'}`} />
              {autoRefresh ? '30s' : 'OFF'}
            </button>
            <button
              type="button"
              disabled={refreshing}
              onClick={doRefresh}
              className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-1.5 text-[10px] font-bold uppercase tracking-wider text-[var(--muted-text)] transition-all hover:border-black/20"
            >
              <RefreshCw size={12} className={refreshing ? 'animate-spin' : ''} />
              {zh ? '刷新' : 'Refresh'}
            </button>
          </>
        }
      />

      <div className="flex-1 overflow-hidden flex">
        {/* ── Left: server list ── */}
        <div className="w-[260px] shrink-0 border-r border-[var(--card-border)] flex flex-col overflow-hidden">
          <div className="p-3 border-b border-[var(--card-border)] space-y-2">
            {/* Search Input */}
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted-text)]" size={14} />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={zh ? '搜索主机名 / IP' : 'Search host / IP'}
                className="w-full pl-9 pr-3 py-2 bg-black/[0.02] border border-[var(--card-border)] rounded-xl text-sm outline-none focus:border-sky-400 text-[var(--app-text)]"
              />
            </div>

            {/* Site Dropdown Selector */}
            <select
              value={siteFilter}
              onChange={(e) => setSiteFilter(e.target.value)}
              className="w-full bg-black/[0.02] border border-[var(--card-border)] rounded-xl px-2 py-1.5 text-xs outline-none text-[var(--app-text)] focus:border-sky-400 dark:bg-white/[0.02]"
            >
              <option value="all" className="bg-[var(--card-bg)]">{zh ? '全部区域' : 'All Sites'}</option>
              {uniqueSites.map((site) => (
                <option key={site} value={site} className="bg-[var(--card-bg)]">{site}</option>
              ))}
            </select>

            {/* Status Filter Buttons */}
            <div className="flex rounded-lg bg-black/[0.02] dark:bg-white/[0.02] border border-[var(--card-border)] p-0.5">
              {(['all', 'online', 'offline'] as const).map((status) => (
                <button
                  key={status}
                  type="button"
                  onClick={() => setStatusFilter(status)}
                  className={`flex-1 py-1 rounded-md text-[10px] font-bold transition-all ${statusFilter === status ? 'bg-[var(--app-text)] text-[var(--card-bg)] shadow-sm' : 'text-[var(--muted-text)] hover:text-[var(--app-text)]'}`}
                >
                  {status === 'all' && (zh ? '全部' : 'All')}
                  {status === 'online' && (zh ? '在线' : 'Online')}
                  {status === 'offline' && (zh ? '离线' : 'Offline')}
                </button>
              ))}
            </div>

            <div className="flex rounded-lg bg-black/[0.02] dark:bg-white/[0.02] border border-[var(--card-border)] p-0.5">
              {(['all', 'windows', 'linux'] as const).map((os) => (
                <button
                  key={os}
                  type="button"
                  onClick={() => setOsFilter(os)}
                  className={`flex-1 py-1 rounded-md text-[10px] font-bold transition-all ${osFilter === os ? 'bg-[var(--app-text)] text-[var(--card-bg)] shadow-sm' : 'text-[var(--muted-text)] hover:text-[var(--app-text)]'}`}
                >
                  {os === 'all' ? (zh ? '全部系统' : 'All OS') : os === 'windows' ? 'Windows' : 'Linux'}
                </button>
              ))}
            </div>

            <p className="text-[10px] font-bold uppercase tracking-wider text-[var(--muted-text)]">
              {filteredServers.length} {zh ? '台服务器' : 'servers'}
            </p>
          </div>

          <VirtualizedDeviceList
            items={filteredServers}
            getKey={(srv) => srv.id}
            empty={<p className="p-4 text-center text-xs text-[var(--muted-text)]">{zh ? '无匹配服务器' : 'No match'}</p>}
            renderItem={(srv) => {
              const online = String(srv.status || '').toLowerCase() === 'online';
              const active = selectedId === srv.id;
              return (
                <button
                  type="button"
                  onClick={() => setSelectedId(srv.id)}
                  className={`w-full flex items-center gap-2.5 rounded-xl border px-3 py-2.5 text-left transition-all ${active ? 'border-sky-400 bg-sky-500/[0.07] shadow-sm' : 'border-transparent hover:border-[var(--card-border)] hover:bg-black/[0.02]'}`}
                >
                  <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${active ? 'bg-sky-500/15 text-sky-600' : 'bg-black/[0.04] text-[var(--muted-text)]'}`}>
                    <Server size={15} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <p className="truncate text-sm font-semibold text-[var(--app-text)]">{srv.hostname || srv.ip_address}</p>
                      <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ backgroundColor: online ? '#10b981' : '#94a3b8' }} />
                    </div>
                      <div className="flex items-center gap-1.5">
                        <p className="truncate text-[11px] font-mono text-[var(--muted-text)]">{srv.isLocalHost ? (zh ? '当前部署主机' : 'Current deployment host') : srv.ip_address}</p>
                        <span className="shrink-0 rounded-full bg-black/[0.04] px-1.5 py-0.5 text-[9px] font-semibold text-[var(--muted-text)]">{serverOsLabel(srv)}</span>
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
              <div className="flex items-center justify-between rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] px-5 py-3.5">
                <div className="flex items-center gap-3">
                  <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-sky-500/10 text-sky-600">
                    <Server size={18} />
                  </span>
                  <div>
                    <p className="text-base font-bold text-[var(--app-text)]">{selectedDevice.hostname || selectedDevice.ip_address}</p>
                    <p className="text-[11px] font-mono text-[var(--muted-text)]">
                      {selectedDevice.ip_address} · {serverOsLabel(selectedDevice)}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2 text-[11px] text-[var(--muted-text)]">
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
                      className={`flex items-center gap-3 rounded-xl border px-4 py-3 ${!hasData ? 'border-[var(--card-border)]' : up ? 'border-emerald-200 bg-emerald-500/[0.04]' : 'border-red-200 bg-red-500/[0.06]'}`}
                    >
                      <Shield size={18} className={!hasData ? 'text-[var(--muted-text)]' : up ? 'text-emerald-600' : 'text-red-500'} />
                      <div>
                        <p className="text-sm font-bold text-[var(--app-text)]">{srv.name}</p>
                        <p className={`text-[10px] font-black uppercase ${!hasData ? 'text-[var(--muted-text)]' : up ? 'text-emerald-600' : 'text-red-500'}`}>
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
                        className={`rounded-2xl border bg-[var(--card-bg)] p-4 text-left transition-all hover:shadow-md ${focusMetric === key ? 'border-sky-400 ring-1 ring-sky-300/50' : 'border-[var(--card-border)]'}`}
                      >
                        {/* Card header */}
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="flex h-8 w-8 items-center justify-center rounded-lg" style={{ backgroundColor: `${color}1a`, color }}>
                              <Icon size={15} />
                            </span>
                            <div>
                              <p className="text-[13px] font-bold text-[var(--app-text)]">{metricLabel(key)}</p>
                              <p className="text-[9px] font-mono uppercase tracking-wider text-[var(--muted-text)]">{key}</p>
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
                            <div className="flex h-[104px] w-[104px] shrink-0 flex-col items-center justify-center rounded-xl border border-[var(--card-border)] bg-black/[0.015]">
                              <span className="text-2xl font-extrabold tabular-nums" style={{ color }}>{fmtValue(key, value)}</span>
                              <span className="mt-0.5 text-[10px] font-semibold uppercase tracking-wider text-[var(--muted-text)]">{zh ? '当前' : 'Now'}</span>
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
                                  contentStyle={{ borderRadius: 10, borderColor: ct.tooltipBorder, padding: '4px 8px', background: ct.tooltipBg, color: ct.tooltipText, fontSize: '11px' }}
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
                          <div className="mt-2 flex items-center gap-3 border-t border-[var(--card-border)] pt-2 text-[9px] font-semibold text-[var(--muted-text)]">
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
                  <div className="rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-5">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                      <div>
                        <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-sky-600">{zh ? '历史趋势' : 'History'}</p>
                        <h3 className="mt-0.5 text-lg font-bold text-[var(--app-text)]">{metricLabel(focusMetric)}</h3>
                        <p className="text-[11px] text-[var(--muted-text)]">
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
                            className={`rounded-lg px-2.5 py-1 text-[10px] font-bold transition-all ${focusMetric === k ? 'bg-sky-600 text-white' : 'bg-black/[0.04] text-[var(--muted-text)] hover:bg-black/[0.08]'}`}
                          >
                            {metricLabel(k)}
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Stat summary row */}
                    <div className="mt-3 grid grid-cols-4 gap-2">
                      {[
                        { label: zh ? '当前' : 'Current', v: curV },
                        { label: zh ? '最小' : 'Min', v: minV },
                        { label: zh ? '平均' : 'Avg', v: avgV },
                        { label: zh ? '最大' : 'Max', v: maxV },
                      ].map((s) => (
                        <div key={s.label} className="rounded-xl border border-[var(--card-border)] bg-black/[0.015] px-3 py-2">
                          <p className="text-[9px] font-bold uppercase tracking-wider text-[var(--muted-text)]">{s.label}</p>
                          <p className="text-lg font-extrabold tabular-nums text-[var(--app-text)]">{fmtValue(focusMetric, s.v)}</p>
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
