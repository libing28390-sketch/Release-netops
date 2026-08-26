import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Router, Search, RefreshCw, Cpu, MemoryStick, Thermometer, Wind, Zap,
  Activity, Clock, AlertTriangle, CheckCircle2, Database, Eye,
  ChevronLeft, ChevronRight, Network,
} from 'lucide-react';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid, Brush } from 'recharts';
import type { Device } from '../types';
import PageHero from './PageHero';
import { useChartTheme } from '../hooks/useChartTheme';
import { useMonitoringStore } from '../store/monitoringStore';
import { VirtualizedDeviceList } from './VirtualizedDeviceList';

interface NetworkMonitoringProps {
  language: 'zh' | 'en';
  devices: Device[];
  showToast: (message: string, type?: string) => void;
  isAuthenticated?: boolean;
}

interface AlertItem {
  id: string;
  created_at: string;
  resolved_at: string | null;
  severity: string;
  title: string;
  message: string;
}

interface CollectionStatusItem {
  collector: string;
  status: string;
  effective_status: string;
  last_attempt_at?: string | null;
  last_success_at?: string | null;
  consecutive_failures: number;
  coverage_total: number;
  coverage_supported: number;
  error_code?: string;
  error_message?: string;
  age_seconds?: number | null;
}

interface CollectionDiagnosticResult {
  status: string;
  checks: Record<string, { status: string; code?: string; port?: number; error?: string }>;
}

interface MonitoringDevicePage {
  items?: Array<Partial<Device> & Pick<Device, 'id' | 'hostname' | 'ip_address'>>;
  total?: number;
  page?: number;
  page_size?: number;
  site_options?: Array<{ id: string; name: string; device_count?: number }>;
}

const isServerDevice = (d: any): boolean => {
  if (!d) return false;
  const serverKeywords = ['linux', 'ubuntu', 'centos', 'debian', 'redhat', 'rocky', 'alma', 'server'];
  const p = (d.platform || '').toLowerCase();
  if (serverKeywords.some((kw) => p.includes(kw))) return true;
  const category = (d.device_category || '').toLowerCase();
  const role = (d.role || '').toLowerCase();
  const assetType = (d.asset_type || '').toLowerCase();
  return category.includes('server') || role.includes('server') || assetType.includes('server');
};

const authHeaders = (): Record<string, string> => {
  const token = localStorage.getItem('netops_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
};

// Keep the realtime view tight enough for quick SNMP verification. The
// backend collector runs on roughly a 60-second cycle, while this page polls
// every 30 seconds, so a one-minute window is sufficient without showing
// stale samples as current data.
const REALTIME_WINDOW_MINUTES = 1;

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

const fmtRate = (bps?: number) => {
  if (bps == null || !Number.isFinite(bps) || bps < 0) return '-';
  if (bps >= 1_000_000_000) return `${(bps / 1_000_000_000).toFixed(2)} Gbps`;
  if (bps >= 1_000_000) return `${(bps / 1_000_000).toFixed(2)} Mbps`;
  if (bps >= 1_000) return `${(bps / 1_000).toFixed(1)} Kbps`;
  return `${bps.toFixed(0)} bps`;
};

const NetworkMonitoring: React.FC<NetworkMonitoringProps> = ({ language, devices, showToast, isAuthenticated = true }) => {
  const zh = language === 'zh';
  const ct = useChartTheme();

  const [searchInput, setSearchInput] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [deviceRows, setDeviceRows] = useState<Device[]>([]);
  const [deviceTotal, setDeviceTotal] = useState(0);
  const [devicePage, setDevicePage] = useState(1);
  const [deviceListLoading, setDeviceListLoading] = useState(false);
  const [deviceListError, setDeviceListError] = useState('');
  const [siteOptions, setSiteOptions] = useState<Array<{ id: string; name: string; device_count?: number }>>([]);
  const devicePageSize = 30;

  // Read ?q= URL param on mount to pre-fill search (deep-link from NPA hop popover)
  useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      const q = params.get('q');
      if (q) {
        setSearchInput(q);
        setSearchQuery(q.trim());
      }
    } catch { /* ignore */ }
  }, []);
  const [realtimeData, setRealtimeData] = useState<any>(null);
  const [trendSeries, setTrendSeries] = useState<any[]>([]);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [collectionStatus, setCollectionStatus] = useState<CollectionStatusItem[]>([]);
  const [diagnosticResult, setDiagnosticResult] = useState<CollectionDiagnosticResult | null>(null);
  const [diagnosticsLoading, setDiagnosticsLoading] = useState(false);
  const [dataError, setDataError] = useState('');
  const [alertTotal, setAlertTotal] = useState(0);
  const [alertsPage, setAlertsPage] = useState(1);
  const [alertsSeverity, setAlertsSeverity] = useState('all');
  const [alertsPhase, setAlertsPhase] = useState('all');

  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [rangeHours, setRangeHours] = useState<number>(24);
  const [autoRefresh, setAutoRefresh] = useState(true);

  // Trend plot configuration
  const [trendInterface, setTrendInterface] = useState<string>('');
  const [trendMetrics, setTrendMetrics] = useState<string[]>(['in_bps', 'out_bps']);

  // Filters
  const [siteFilter, setSiteFilter] = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<'all' | 'online' | 'offline'>('all');

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollCycleRef = useRef(0);
  const networkDevicesRef = useRef<Device[]>([]);
  const deviceListRequestRef = useRef(0);

  const networkDevices = useMemo(() => (devices || []).filter((d) => !isServerDevice(d)), [devices]);

  // The shared inventory is refreshed independently from this page's
  // server-paginated list. Keep it only as an outage fallback; it must not be
  // a dependency of the list request or every telemetry refresh will restart
  // the left-hand loading state.
  useEffect(() => {
    networkDevicesRef.current = networkDevices;
  }, [networkDevices]);

  const uniqueSites = useMemo(() => {
    const sites = new Map<string, string>();
    networkDevices.forEach((d) => {
      const key = String(d.site_id || d.site || '').trim();
      if (key) sites.set(key, d.site || key);
    });
    return Array.from(sites.entries())
      .map(([id, name]) => ({ id, name }))
      .sort((left, right) => left.name.localeCompare(right.name));
  }, [networkDevices]);

  const availableSites = siteOptions.length > 0 ? siteOptions : uniqueSites;

  // Search and filtering are server-side.  Only one bounded page is kept in
  // the browser, which avoids rendering/fetching the complete inventory.
  useEffect(() => {
    if (!isAuthenticated) {
      setDeviceRows([]);
      setDeviceTotal(0);
      setDeviceListError('');
      setDeviceListLoading(false);
      return;
    }
    const controller = new AbortController();
    const requestId = ++deviceListRequestRef.current;
    const params = new URLSearchParams({
      q: searchQuery,
      site_id: siteFilter,
      status: statusFilter,
      page: String(devicePage),
      page_size: String(devicePageSize),
    });
    setDeviceListLoading(true);
    setDeviceListError('');
    fetch(`/api/monitoring/network-devices?${params.toString()}`, {
      headers: authHeaders(),
      signal: controller.signal,
    })
      .then(async (response) => {
        const payload = await response.json().catch(() => ({} as MonitoringDevicePage));
        if (!response.ok) throw new Error(payload && 'detail' in payload ? String((payload as any).detail) : 'device list fetch failed');
        return payload as MonitoringDevicePage;
      })
      .then((payload) => {
        if (requestId !== deviceListRequestRef.current) return;
        const items = Array.isArray(payload.items) ? payload.items as Device[] : [];
        setDeviceRows(items);
        setDeviceTotal(Number(payload.total) || 0);
        if (Array.isArray(payload.site_options)) setSiteOptions(payload.site_options);
        setSelectedId((current) => items.some((item) => item.id === current) ? current : (items[0]?.id || null));
      })
      .catch((error) => {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        if (requestId !== deviceListRequestRef.current) return;
        setDeviceListError(error instanceof Error ? error.message : 'device list fetch failed');
        // Keep the page usable during a temporary API failure.
        const fallbackStart = (devicePage - 1) * devicePageSize;
        const fallback = networkDevicesRef.current.slice(fallbackStart, fallbackStart + devicePageSize);
        setDeviceRows(fallback);
        setDeviceTotal(networkDevicesRef.current.length);
        setSelectedId((current) => fallback.some((item) => item.id === current) ? current : (fallback[0]?.id || null));
      })
      .finally(() => {
        if (requestId === deviceListRequestRef.current) setDeviceListLoading(false);
      });
    return () => controller.abort();
  }, [devicePage, devicePageSize, isAuthenticated, searchQuery, siteFilter, statusFilter]);

  const selectedDevice = useMemo(
    () => deviceRows.find((d) => d.id === selectedId) || null,
    [deviceRows, selectedId],
  );

  const { monitorSelectedDevice, setMonitorSelectedDevice } = useMonitoringStore();

  // Sync selected device from topology redirects (Zustand store)
  useEffect(() => {
    if (monitorSelectedDevice && !isServerDevice(monitorSelectedDevice)) {
      setSelectedId(monitorSelectedDevice.id);
      setMonitorSelectedDevice(null);
    }
  }, [monitorSelectedDevice, setMonitorSelectedDevice]);

  // Auto-select first network device once data is available
  useEffect(() => {
    if (!selectedId && deviceRows.length > 0) {
      setSelectedId(deviceRows[0].id);
    }
  }, [deviceRows, selectedId]);

  const fetchRealtime = useCallback(async (deviceId: string, signal?: AbortSignal) => {
    const resp = await fetch(`/api/monitoring/device/${deviceId}/realtime?window_minutes=${REALTIME_WINDOW_MINUTES}&limit=1000`, {
      headers: authHeaders(),
      signal,
    });
    if (!resp.ok) throw new Error('realtime fetch failed');
    return resp.json();
  }, []);

  const fetchTrend = useCallback(async (deviceId: string, hours: number, interfaceName?: string, signal?: AbortSignal) => {
    const resolution = hours <= 24 ? '1m' : '5m';
    const params = new URLSearchParams({
      range_hours: String(hours),
      resolution,
    });
    if (interfaceName) {
      params.set('interface_name', interfaceName);
    }
    const resp = await fetch(`/api/monitoring/device/${deviceId}/trend?${params.toString()}`, {
      headers: authHeaders(),
      signal,
    });
    if (!resp.ok) throw new Error('trend fetch failed');
    const payload = await resp.json();
    return Array.isArray(payload?.series) ? payload.series : [];
  }, []);

  const fetchAlerts = useCallback(async (deviceId: string, page: number, severity: string, phase: string, signal?: AbortSignal) => {
    const params = new URLSearchParams({
      device_id: deviceId,
      page: String(page),
      page_size: '10',
      severity,
      phase,
    });
    const resp = await fetch(`/api/monitoring/alerts?${params.toString()}`, {
      headers: authHeaders(),
      signal,
    });
    if (!resp.ok) throw new Error('alerts fetch failed');
    return resp.json();
  }, []);

  const fetchCollectionStatus = useCallback(async (deviceId: string, signal?: AbortSignal) => {
    const resp = await fetch(`/api/monitoring/device/${deviceId}/collection-status`, {
      headers: authHeaders(),
      signal,
    });
    if (!resp.ok) throw new Error('collection status fetch failed');
    const payload = await resp.json();
    return Array.isArray(payload?.items) ? payload.items : [];
  }, []);

  const runCollectionDiagnostics = useCallback(async () => {
    if (!selectedId || diagnosticsLoading) return;
    setDiagnosticsLoading(true);
    try {
      const response = await fetch(`/api/monitoring/device/${selectedId}/diagnostics`, {
        method: 'POST',
        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload?.detail || 'collection_diagnostics_failed');
      setDiagnosticResult(payload);
      setCollectionStatus(await fetchCollectionStatus(selectedId));
      showToast(zh ? '采集链路诊断完成。' : 'Collection path diagnostics completed.', payload.status === 'success' ? 'success' : 'error');
    } catch (error) {
      showToast(zh ? `诊断失败：${error instanceof Error ? error.message : '连接错误'}` : `Diagnostics failed: ${error instanceof Error ? error.message : 'connection error'}`, 'error');
    } finally {
      setDiagnosticsLoading(false);
    }
  }, [diagnosticsLoading, fetchCollectionStatus, selectedId, showToast, zh]);

  // Load telemetry data when selected device changes or range changes
  const loadDeviceData = useCallback(async (deviceId: string, hours: number, iface: string, page: number, sev: string, ph: string, showSpinner = true, signal?: AbortSignal, includeTrend = true) => {
    if (showSpinner) setLoading(true);
    try {
      const [rt, tr, al, cs] = await Promise.all([
        fetchRealtime(deviceId, signal),
        includeTrend ? fetchTrend(deviceId, hours, iface, signal) : Promise.resolve(null),
        fetchAlerts(deviceId, page, sev, ph, signal),
        fetchCollectionStatus(deviceId, signal),
      ]);
      setRealtimeData(rt);
      if (Array.isArray(tr)) setTrendSeries(tr);
      setAlerts(Array.isArray(al?.items) ? al.items : []);
      setAlertTotal(typeof al?.total === 'number' ? al.total : 0);
      setCollectionStatus(cs);
      setDataError('');
    } catch (e) {
      if (!(e instanceof DOMException && e.name === 'AbortError')) {
        setDataError(e instanceof Error ? e.message : 'monitoring data fetch failed');
      }
    } finally {
      if (showSpinner) setLoading(false);
    }
  }, [fetchRealtime, fetchTrend, fetchAlerts, fetchCollectionStatus]);

  useEffect(() => {
    if (!isAuthenticated || !selectedId) {
      setRealtimeData(null);
      setTrendSeries([]);
      setAlerts([]);
      setAlertTotal(0);
      setCollectionStatus([]);
      setDiagnosticResult(null);
      setDataError('');
      return;
    }
    let cancelled = false;
    const controller = new AbortController();

    loadDeviceData(
      selectedId,
      rangeHours,
      trendInterface,
      alertsPage,
      alertsSeverity,
      alertsPhase,
      true,
      controller.signal
    );

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [isAuthenticated, selectedId, rangeHours, trendInterface, alertsPage, alertsSeverity, alertsPhase, loadDeviceData]);
  // Reset trend configuration and pagination when selected device changes
  useEffect(() => {
    setTrendInterface('');
    setAlertsPage(1);
    setDiagnosticResult(null);
  }, [selectedId]);

  // Auto-refresh polling (every 30 seconds for realtime and alerts, 60 seconds for trend)
  useEffect(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (!isAuthenticated || !autoRefresh || !selectedId) return;

    pollRef.current = setInterval(async () => {
      try {
        pollCycleRef.current += 1;
        await loadDeviceData(
          selectedId,
          rangeHours,
          trendInterface,
          alertsPage,
          alertsSeverity,
          alertsPhase,
          false,
          undefined,
          pollCycleRef.current % 2 === 0
        );
      } catch {
        /* ignore */
      }
    }, 30000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [autoRefresh, isAuthenticated, selectedId, rangeHours, trendInterface, alertsPage, alertsSeverity, alertsPhase, loadDeviceData]);

  const doRefresh = useCallback(async () => {
    if (!selectedId) return;
    setRefreshing(true);
    try {
      await loadDeviceData(
        selectedId,
        rangeHours,
        trendInterface,
        alertsPage,
        alertsSeverity,
        alertsPhase,
        false
      );
      showToast(zh ? '数据刷新成功' : 'Data refreshed successfully', 'success');
    } catch {
      showToast(zh ? '刷新失败' : 'Refresh failed', 'error');
    } finally {
      setTimeout(() => setRefreshing(false), 600);
    }
  }, [selectedId, rangeHours, trendInterface, alertsPage, alertsSeverity, alertsPhase, loadDeviceData, showToast, zh]);

  // Derived Trend Chart Data
  const trendData = useMemo(() => {
    return trendSeries.map((p: any) => ({
      ts: p.ts ?? p.ts_minute ?? p.ts_hour,
      in_bps: p.in_bps ?? p.total_in_bps ?? null,
      out_bps: p.out_bps ?? p.total_out_bps ?? null,
      in_pkts: p.in_pkts ?? p.total_in_pkts ?? null,
      out_pkts: p.out_pkts ?? p.total_out_pkts ?? null,
      errors: p.errors ?? p.total_errors ?? null,
      drops: p.drops ?? p.total_drops ?? null,
      crc_errors: p.crc_errors ?? p.total_crc_errors ?? null,
    }));
  }, [trendSeries]);

  const trendMetricDefs = [
    { key: 'in_bps', label: zh ? '入流量' : 'IN Throughput', short: 'IN', color: '#2563eb', unit: 'bps' },
    { key: 'out_bps', label: zh ? '出流量' : 'OUT Throughput', short: 'OUT', color: '#ea580c', unit: 'bps' },
    { key: 'in_pkts', label: zh ? '入包数' : 'IN Packets', short: 'IN Pkts', color: '#7c3aed', unit: 'pps' },
    { key: 'out_pkts', label: zh ? '出包数' : 'OUT Packets', short: 'OUT Pkts', color: '#0891b2', unit: 'pps' },
    { key: 'errors', label: zh ? '错包数' : 'Errors', short: 'Errors', color: '#dc2626', unit: 'cnt' },
    { key: 'drops', label: zh ? '丢包数' : 'Drops', short: 'Drops', color: '#16a34a', unit: 'cnt' },
    { key: 'crc_errors', label: zh ? 'CRC/FCS' : 'CRC/FCS', short: 'CRC', color: '#b91c1c', unit: 'cnt' },
  ] as const;

  const trendMetricMap = Object.fromEntries(trendMetricDefs.map((d) => [d.key, d]));
  const selectedMetricDefs = trendMetricDefs.filter((d) => trendMetrics.includes(d.key));
  const hasThroughputMetric = selectedMetricDefs.some((d) => d.unit === 'bps');
  const hasCountMetric = selectedMetricDefs.some((d) => d.unit !== 'bps');

  const toggleTrendMetric = (metricKey: string) => {
    setTrendMetrics((prev) => prev.includes(metricKey) ? prev.filter((k) => k !== metricKey) : [...prev, metricKey]);
  };

  // UI status formats
  const getFanStatusLabel = (status: any) => {
    if (status == null || status === '') return zh ? '未知' : 'Unknown';
    if (status === true || status === 1) return zh ? '正常' : 'OK';
    if (status === false || status === 0) return zh ? '故障' : 'FAIL';
    const s = String(status).toLowerCase();
    if (s === 'fail' || s === 'failed' || s === 'error' || s === 'down') return zh ? '故障' : 'FAIL';
    if (s === 'ok' || s === 'normal' || s === 'up' || s === 'healthy' || s === 'true' || s === '1') return zh ? '正常' : 'OK';
    if (s === 'false' || s === '0') return zh ? '故障' : 'FAIL';
    return String(status).toUpperCase();
  };

  const getPsuStatusLabel = (status: any) => {
    if (status == null || status === '') return zh ? '未知' : 'Unknown';
    if (status === true || status === 1) return zh ? '正常' : 'OK';
    if (status === false || status === 0) return zh ? '故障' : 'FAIL';
    const s = String(status).toLowerCase();
    if (s === 'fail' || s === 'failed' || s === 'error' || s === 'down') return zh ? '故障' : 'FAIL';
    if (s === 'ok' || s === 'normal' || s === 'up' || s === 'healthy' || s === 'true' || s === '1') return zh ? '正常' : 'OK';
    if (s === 'false' || s === '0') return zh ? '故障' : 'FAIL';
    return String(status).toUpperCase();
  };

  const hardwareStatusTone = (status: any) => {
    if (status == null || status === '') return 'text-slate-500';
    if (status === true || status === 1) return 'text-emerald-500';
    if (status === false || status === 0) return 'text-red-500';
    const normalized = String(status).toLowerCase();
    if (['fail', 'failed', 'error', 'down', 'false', '0'].includes(normalized)) return 'text-red-500';
    if (['ok', 'normal', 'up', 'healthy', 'true', '1'].includes(normalized)) return 'text-emerald-500';
    return 'text-slate-500';
  };

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

  const fmtFullTime = (ts?: string) => {
    if (!ts) return '';
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return String(ts);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  };

  const upInterfaces = useMemo(() => {
    const list = realtimeData?.latest_interfaces || [];
    return list.filter((it: any) => String(it.status || '').toLowerCase() === 'up');
  }, [realtimeData]);

  const interfaceOptions = useMemo(() => {
    return upInterfaces.map((it: any) => String(it.interface_name || '')).filter(Boolean);
  }, [upInterfaces]);

  const latestTrendPoint = trendData.length > 0 ? trendData[trendData.length - 1] : null;
  const snapshotDevice = realtimeData?.device || selectedDevice;
  const lastSampleAt = realtimeData?.updated_at || realtimeData?.timestamp;

  const collectionLabel = (collector: string) => ({
    reachability: zh ? '可达性' : 'Reachability',
    snmp_metrics: zh ? 'SNMP 整机' : 'SNMP Metrics',
    snmp_interfaces: zh ? 'SNMP 接口' : 'SNMP Interfaces',
    snmp_inventory: zh ? 'SNMP 资产' : 'SNMP Inventory',
    topology_lldp: zh ? 'LLDP 拓扑' : 'LLDP Topology',
    arp: zh ? 'ARP 邻居' : 'ARP Neighbor',
    diagnostics: zh ? '诊断状态' : 'Diagnostics',
    dns: zh ? 'DNS 解析' : 'DNS Resolve',
    ssh_tcp: zh ? 'SSH 连通' : 'SSH TCP',
    snmp_udp: zh ? 'SNMP UDP' : 'SNMP UDP',
  }[collector] || collector);

  const collectionStatusLabel = (status: string) => ({
    success: zh ? '成功' : 'Success',
    stale: zh ? '已过期' : 'Stale',
    skipped: zh ? '已跳过' : 'Skipped',
    not_configured: zh ? '未配置' : 'Not configured',
    failed: zh ? '失败' : 'Failed',
  }[status] || status);

  const collectionTone = (status: string) => {
    if (status === 'success') return 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400 border border-emerald-200/80 dark:border-emerald-800/60';
    if (status === 'stale') return 'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400 border border-amber-200/80 dark:border-amber-800/60';
    if (status === 'skipped') return 'bg-gray-100 text-gray-600 dark:bg-zinc-800 dark:text-zinc-400 border border-gray-200/80 dark:border-zinc-700';
    return 'bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-400 border border-rose-200/80 dark:border-rose-800/60';
  };

  const submitDeviceSearch = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setDevicePage(1);
    setSearchQuery(searchInput.trim());
  };
  const totalDevicePages = Math.max(1, Math.ceil(deviceTotal / devicePageSize));
  const pageStart = deviceTotal === 0 ? 0 : (devicePage - 1) * devicePageSize + 1;
  const pageEnd = Math.min(deviceTotal, devicePage * devicePageSize);

  return (
    <div className="network-monitoring-page flex flex-col h-full overflow-hidden">
      <PageHero
        icon={Router}
        title={zh ? '网络监控' : 'Network Monitoring'}
        subtitle={zh ? '网络交换机/路由器性能遥测 · 接口 SNMP 流量分析' : 'Network switch/router telemetry · Interface SNMP traffic analysis'}
        actions={
          <div className="flex items-center gap-2">
            <div className="flex items-center p-0.5 rounded-xl bg-gray-100 dark:bg-zinc-800">
              {[
                { h: 1, label: '1h' },
                { h: 6, label: '6h' },
                { h: 24, label: '24h' },
                { h: 168, label: '7d' },
              ].map((opt) => (
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

      <div className="ops-page-scroll flex-1 overflow-hidden flex">
        {/* ── Left: Switch list ── */}
        <div className="w-[270px] shrink-0 border-r border-gray-200/70 dark:border-zinc-800/80 bg-gray-50/40 dark:bg-zinc-900/30 flex flex-col overflow-hidden">
          <div className="p-3 border-b border-gray-200/70 dark:border-zinc-800/80 space-y-2.5">
            <form onSubmit={submitDeviceSearch} className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={13} />
              <input
                type="text"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder={zh ? '输入设备名 / IP...' : 'Search switch / IP...'}
                className="w-full pl-8 pr-8 py-1.5 bg-white dark:bg-zinc-800 border border-gray-200/80 dark:border-zinc-700 rounded-xl text-xs outline-none focus:border-blue-500 text-gray-800 dark:text-zinc-100 placeholder-gray-400 shadow-2xs"
              />
              <button
                type="submit"
                aria-label={zh ? '搜索设备' : 'Search devices'}
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-gray-400 transition hover:bg-gray-100 dark:hover:bg-zinc-700 hover:text-gray-700 disabled:opacity-50 cursor-pointer"
                disabled={deviceListLoading}
              >
                <Search size={12} />
              </button>
            </form>

            <select
              value={siteFilter}
              onChange={(e) => { setSiteFilter(e.target.value); setDevicePage(1); }}
              className="w-full bg-white dark:bg-zinc-800 border border-gray-200/80 dark:border-zinc-700 rounded-xl px-2.5 py-1.5 text-xs outline-none text-gray-700 dark:text-zinc-200 focus:border-blue-500 shadow-2xs cursor-pointer"
            >
              <option value="all">{zh ? '全部区域' : 'All Sites'}</option>
              {availableSites.map((site) => (
                <option key={site.id} value={site.id}>{site.name}</option>
              ))}
            </select>

            <div className="flex rounded-xl bg-gray-200/60 dark:bg-zinc-800 p-0.5">
              {(['all', 'online', 'offline'] as const).map((status) => (
                <button
                  key={status}
                  type="button"
                  onClick={() => { setStatusFilter(status); setDevicePage(1); }}
                  className={`flex-1 py-1 rounded-lg text-[11px] font-semibold transition-all cursor-pointer ${statusFilter === status ? 'bg-white dark:bg-zinc-700 text-gray-900 dark:text-white shadow-2xs' : 'text-gray-500 dark:text-zinc-400 hover:text-gray-800'}`}
                >
                  {status === 'all' && (zh ? '全部' : 'All')}
                  {status === 'online' && (zh ? '在线' : 'Online')}
                  {status === 'offline' && (zh ? '离线' : 'Offline')}
                </button>
              ))}
            </div>

            <div className="flex items-center justify-between text-[11px] font-medium text-gray-400 px-0.5">
              <span>{deviceListLoading ? (zh ? '正在加载设备…' : 'Loading…') : `${deviceTotal} ${zh ? '台在管网络设备' : 'switches'}`}</span>
            </div>
            {deviceListError && <p className="truncate text-[9px] text-amber-700" title={deviceListError}>{zh ? '列表接口暂时不可用，显示本地缓存' : 'List API unavailable; showing local fallback'}</p>}
          </div>

          <div className="min-h-0 flex-1 flex flex-col p-2">
            <VirtualizedDeviceList
              items={deviceRows}
              getKey={(dev) => dev.id}
              empty={<p className="p-4 text-center text-xs text-gray-400">{deviceListLoading ? (zh ? '加载中…' : 'Loading…') : (zh ? '无匹配设备' : 'No match')}</p>}
              renderItem={(dev) => {
                const online = String(dev.status || '').toLowerCase() === 'online';
                const active = selectedId === dev.id;
                return (
                  <button
                    type="button"
                    onClick={() => setSelectedId(dev.id)}
                    className={`w-full flex items-center gap-2.5 rounded-2xl border px-3 py-2.5 text-left transition-all cursor-pointer mb-1.5 ${active ? 'border-blue-500/50 bg-blue-50/70 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300 shadow-2xs' : 'border-transparent bg-white/70 dark:bg-zinc-800/40 hover:border-gray-20 dark:hover:border-zinc-700 hover:bg-white'}`}
                  >
                    <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-xl ${active ? 'bg-blue-600 text-white' : 'bg-gray-100 dark:bg-zinc-700 text-gray-500 dark:text-zinc-400'}`}>
                      <Router size={14} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-1.5">
                        <p className={`truncate text-xs font-bold ${active ? 'text-blue-900 dark:text-blue-100' : 'text-gray-800 dark:text-zinc-200'}`}>
                          {dev.hostname || dev.ip_address}
                        </p>
                        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${online ? 'bg-emerald-500' : 'bg-gray-300'}`} />
                      </div>
                      <p className="truncate text-[10px] font-mono text-gray-400 mt-0.5">{dev.ip_address}</p>
                    </div>
                  </button>
                );
              }}
            />
            <div className="flex items-center justify-between gap-2 border-t border-gray-200/70 dark:border-zinc-800/80 px-2 py-2 mt-auto">
              <span className="text-[10px] tabular-nums text-gray-400">
                {pageStart}-{pageEnd} / {deviceTotal || 0}
              </span>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  aria-label={zh ? '上一页' : 'Previous page'}
                  disabled={devicePage <= 1 || deviceListLoading}
                  onClick={() => setDevicePage((page) => Math.max(1, page - 1))}
                  className="rounded-lg p-1 text-gray-400 hover:bg-gray-100 dark:hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-35 cursor-pointer"
                >
                  <ChevronLeft size={13} />
                </button>
                <span className="min-w-[40px] text-center text-[10px] font-semibold tabular-nums text-gray-500">
                  {devicePage} / {totalDevicePages}
                </span>
                <button
                  type="button"
                  aria-label={zh ? '下一页' : 'Next page'}
                  disabled={devicePage >= totalDevicePages || deviceListLoading}
                  onClick={() => setDevicePage((page) => Math.min(totalDevicePages, page + 1))}
                  className="rounded-lg p-1 text-gray-400 hover:bg-gray-100 dark:hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-35 cursor-pointer"
                >
                  <ChevronRight size={13} />
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* ── Right: Telemetry details ── */}
        <div className="flex-1 overflow-auto p-5 space-y-4">
          {!selectedDevice ? (
            <div className="flex h-full items-center justify-center text-sm text-gray-400">
              {deviceListLoading
                ? (zh ? '正在加载网络设备…' : 'Loading network devices…')
                : deviceTotal === 0
                  ? (zh ? '暂无符合条件的网络设备' : 'No matching network devices')
                  : (zh ? '从左侧选择一台网络设备' : 'Select a network device from the left')}
            </div>
          ) : (
            <>
              {/* Header card */}
              <div className="bg-white dark:bg-zinc-900/90 border border-gray-200/70 dark:border-zinc-800/80 flex items-center justify-between rounded-2xl p-4 shadow-2xs">
                <div className="flex items-center gap-3.5">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400">
                    <Router size={18} />
                  </div>
                  <div>
                    <p className="text-base font-bold text-gray-900 dark:text-white">{selectedDevice.hostname || selectedDevice.ip_address}</p>
                    <p className="text-xs font-mono text-gray-400 mt-0.5">
                      {selectedDevice.ip_address} · {selectedDevice.platform || 'SNMP Agent'}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2 text-xs text-gray-400">
                  <Clock size={13} />
                  {lastSampleAt ? (zh ? `最近采样 ${fmtTime(lastSampleAt)}` : `Last sample ${fmtTime(lastSampleAt)}`) : (zh ? '等待数据' : 'Awaiting data')}
                </div>
              </div>

              {dataError && (
                <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
                  {zh ? '本次刷新失败，当前保留上一次有效数据：' : 'Refresh failed; the last valid snapshot is retained: '}{dataError}
                </div>
              )}

              {/* Diagnostics Matrix */}
              <div className="bg-white dark:bg-zinc-900/90 border border-gray-200/70 dark:border-zinc-800/80 rounded-2xl p-4 shadow-2xs">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-blue-600 bg-blue-50 px-2 py-0.5 rounded-full">
                      {zh ? '采集遥测' : 'Telemetry'}
                    </span>
                    <h3 className="text-sm font-bold text-gray-900 dark:text-white">
                      {zh ? '采集链路与微观诊断' : 'Collection Health & Diagnostics'}
                    </h3>
                  </div>
                  <button
                    type="button"
                    onClick={runCollectionDiagnostics}
                    disabled={diagnosticsLoading}
                    className="flex items-center gap-1.5 px-3 py-1 rounded-xl text-xs font-semibold border border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100 transition cursor-pointer disabled:cursor-wait disabled:opacity-60"
                  >
                    <Activity size={12} className={diagnosticsLoading ? 'animate-pulse' : ''} />
                    {diagnosticsLoading ? (zh ? '诊断中…' : 'Diagnosing…') : (zh ? '诊断采集链路' : 'Diagnose Collection')}
                  </button>
                </div>
                {collectionStatus.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-gray-200 dark:border-zinc-800 p-6 text-center text-xs text-gray-400">
                    {zh ? '尚无采集状态；等待下一轮后台采集或执行 SNMP 测试。' : 'No collector state yet. Wait for the next poll or run an SNMP test.'}
                  </div>
                ) : (
                  <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
                    {collectionStatus.map((item) => (
                      <div key={item.collector} className="rounded-xl border border-gray-100 dark:border-zinc-800 bg-gray-50/70 dark:bg-zinc-800/40 p-2.5 flex flex-col justify-between">
                        <div className="flex items-center justify-between gap-1.5">
                          <span className="truncate text-xs font-bold text-gray-800 dark:text-zinc-200">{collectionLabel(item.collector)}</span>
                          <span className={`shrink-0 px-1.5 py-0.2 rounded-md text-[9px] font-bold ${collectionTone(item.effective_status)}`}>
                            {collectionStatusLabel(item.effective_status)}
                          </span>
                        </div>
                        <p className="mt-1.5 truncate text-[10px] text-gray-400 font-mono">
                          {item.last_success_at
                            ? `${zh ? '成功于' : 'Success'} ${fmtTime(item.last_success_at)}`
                            : (item.error_code || (zh ? '尚未成功' : 'No sample'))}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Hardware Performance Snapshot */}
              <div className="bg-white dark:bg-zinc-900/90 border border-gray-200/70 dark:border-zinc-800/80 rounded-2xl p-4 shadow-2xs">
                <div className="flex items-center gap-2 mb-3">
                  <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-purple-600 bg-purple-50 px-2 py-0.5 rounded-full">
                    SNMP
                  </span>
                  <h3 className="text-sm font-bold text-gray-900 dark:text-white">
                    {zh ? '最新整机状态快照' : 'Latest Hardware Status Snapshot'}
                  </h3>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                  <div className="flex flex-col items-center justify-center p-3.5 rounded-xl border border-gray-100 dark:border-zinc-800 bg-gray-50/70 dark:bg-zinc-800/40">
                    <Cpu size={18} className="text-blue-500 mb-1.5" />
                    <span className="text-[10px] font-semibold text-gray-400">{zh ? 'CPU 使用率' : 'CPU'}</span>
                    <p className="text-xl font-extrabold text-gray-900 dark:text-white mt-0.5 font-mono">
                      {snapshotDevice?.cpu_usage != null && Number.isFinite(Number(snapshotDevice.cpu_usage)) ? `${snapshotDevice.cpu_usage}%` : '--'}
                    </p>
                  </div>

                  <div className="flex flex-col items-center justify-center p-3.5 rounded-xl border border-gray-100 dark:border-zinc-800 bg-gray-50/70 dark:bg-zinc-800/40">
                    <MemoryStick size={18} className="text-purple-500 mb-1.5" />
                    <span className="text-[10px] font-semibold text-gray-400">{zh ? '内存使用率' : 'Memory'}</span>
                    <p className="text-xl font-extrabold text-gray-900 dark:text-white mt-0.5 font-mono">
                      {snapshotDevice?.memory_usage != null && Number.isFinite(Number(snapshotDevice.memory_usage)) ? `${snapshotDevice.memory_usage}%` : '--'}
                    </p>
                  </div>

                  <div className="flex flex-col items-center justify-center p-3.5 rounded-xl border border-gray-100 dark:border-zinc-800 bg-gray-50/70 dark:bg-zinc-800/40">
                    <Thermometer size={18} className="text-amber-500 mb-1.5" />
                    <span className="text-[10px] font-semibold text-gray-400">{zh ? '设备温度' : 'Temperature'}</span>
                    <p className="text-xl font-extrabold text-gray-900 dark:text-white mt-0.5 font-mono">
                      {snapshotDevice?.temp != null && Number.isFinite(Number(snapshotDevice.temp)) ? `${snapshotDevice.temp}°C` : '--'}
                    </p>
                  </div>

                  <div className="flex flex-col items-center justify-center p-3.5 rounded-xl border border-gray-100 dark:border-zinc-800 bg-gray-50/70 dark:bg-zinc-800/40">
                    <Wind size={18} className="text-emerald-500 mb-1.5" />
                    <span className="text-[10px] font-semibold text-gray-400">{zh ? '风扇状态' : 'Fan Status'}</span>
                    <p className={`text-xs font-bold mt-1 px-2 py-0.5 rounded-md ${hardwareStatusTone(snapshotDevice?.fan_status)}`}>
                      {getFanStatusLabel(snapshotDevice?.fan_status)}
                    </p>
                  </div>

                  <div className="flex flex-col items-center justify-center p-3.5 rounded-xl border border-gray-100 dark:border-zinc-800 bg-gray-50/70 dark:bg-zinc-800/40">
                    <Zap size={18} className="text-orange-500 mb-1.5" />
                    <span className="text-[10px] font-semibold text-gray-400">{zh ? '电源状态' : 'Power (PSU)'}</span>
                    <p className={`text-xs font-bold mt-1 px-2 py-0.5 rounded-md ${hardwareStatusTone(snapshotDevice?.psu_status)}`}>
                      {getPsuStatusLabel(snapshotDevice?.psu_status)}
                    </p>
                  </div>
                </div>
              </div>

              {/* Interface Table */}
              <div className="bg-white dark:bg-zinc-900/90 border border-gray-200/70 dark:border-zinc-800/80 rounded-2xl p-4 shadow-2xs">
                <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-blue-600 bg-blue-50 px-2 py-0.5 rounded-full">
                        SNMP
                      </span>
                      <h3 className="text-sm font-bold text-gray-900 dark:text-white">
                        {zh ? '接口流量与错误包统计' : 'Interfaces & Realtime Telemetry'}
                      </h3>
                    </div>
                    <p className="text-[11px] text-gray-400 mt-0.5">
                      {zh
                        ? `仅显示最近 ${REALTIME_WINDOW_MINUTES} 分钟内的 UP 接口；IN/OUT 速率使用 SNMP Counter64 计算，分栏显示丢弃与 CRC 错误。`
                        : `UP interfaces sampled within the last ${REALTIME_WINDOW_MINUTES} minute; IN/OUT rates use SNMP Counter64 byte counters.`}
                    </p>
                  </div>
                  {realtimeData?.summary && (
                    <div className="text-xs font-mono text-gray-500 flex items-center gap-3">
                      <span className="text-blue-600">IN: {fmtRate(Number(realtimeData.summary.in_bps || 0))}</span>
                      <span className="text-orange-600">OUT: {fmtRate(Number(realtimeData.summary.out_bps || 0))}</span>
                      {realtimeData.summary.errors > 0 && <span className="text-rose-500 font-bold">{zh ? '错误' : 'Errors'}: {realtimeData.summary.errors}</span>}
                    </div>
                  )}
                </div>

                <div className="max-h-[260px] overflow-auto border border-gray-100 dark:border-zinc-800 rounded-xl">
                  <table className="nx-data-table nx-data-table--compact">
                    <thead className="bg-gray-50 dark:bg-zinc-800 sticky top-0 backdrop-blur-md">
                      <tr>
                        <th className="px-4 py-2.5 text-left text-[10px] uppercase tracking-wider text-gray-400">{zh ? '接口' : 'Interface'}</th>
                        <th className="px-4 py-2.5 text-left text-[10px] uppercase tracking-wider text-gray-400">{zh ? '状态' : 'Status'}</th>
                        <th className="px-4 py-2.5 text-right text-[10px] uppercase tracking-wider text-gray-400">IN</th>
                        <th className="px-4 py-2.5 text-right text-[10px] uppercase tracking-wider text-gray-400">OUT</th>
                        <th className="px-4 py-2.5 text-right text-[10px] uppercase tracking-wider text-gray-400">BW%</th>
                        <th className="px-4 py-2.5 text-right text-[10px] uppercase tracking-wider text-gray-400">{zh ? '通用错误' : 'Errors'}</th>
                        <th className="px-4 py-2.5 text-right text-[10px] uppercase tracking-wider text-gray-400">CRC/FCS</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 dark:divide-zinc-800">
                      {upInterfaces.map((it: any, idx: number) => {
                        const bw = Math.max(Number(it.bw_in_pct || 0), Number(it.bw_out_pct || 0));
                        return (
                          <tr key={`${it.interface_name}-${idx}`} className="hover:bg-gray-50/70 dark:hover:bg-zinc-800/40">
                            <td className="px-4 py-2 font-mono text-gray-900 dark:text-white font-semibold">{it.interface_name}</td>
                            <td className="px-4 py-2">
                              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[9px] font-bold text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300">
                                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                                {zh ? 'UP' : 'UP'}
                              </span>
                            </td>
                            <td className="px-4 py-2 text-right font-mono text-blue-600 dark:text-blue-400">
                              <div>{fmtRate(it.in_bps)}</div>
                            </td>
                            <td className="px-4 py-2 text-right font-mono text-orange-600 dark:text-orange-400">
                              <div>{fmtRate(it.out_bps)}</div>
                            </td>
                            <td className="px-4 py-2 text-right font-mono text-gray-800 dark:text-zinc-200">{`${bw.toFixed(1)}%`}</td>
                            <td className="px-4 py-2 text-right font-mono text-gray-400">{Number(it.in_errors || 0)} / {Number(it.out_errors || 0)}</td>
                            <td className="px-4 py-2 text-right font-mono text-gray-400">{Number(it.fcs_errors || 0)}</td>
                          </tr>
                        );
                      })}
                      {upInterfaces.length === 0 && (
                        <tr>
                          <td colSpan={7} className="px-4 py-8 text-center text-xs text-gray-400">
                            {zh ? '暂无 UP 接口实时样本' : 'No realtime UP interface samples yet'}
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Trend Chart */}
              <div className="bg-white dark:bg-zinc-900/90 border border-gray-200/70 dark:border-zinc-800/80 rounded-2xl p-4 shadow-2xs space-y-3">
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-blue-600 bg-blue-50 px-2 py-0.5 rounded-full">
                        {zh ? '性能趋势' : 'Trends'}
                      </span>
                      <h3 className="text-sm font-bold text-gray-900 dark:text-white">{zh ? '流量与包速率趋势' : 'Performance Trends'}</h3>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <select
                      value={trendInterface}
                      onChange={(e) => setTrendInterface(e.target.value)}
                      className="rounded-xl border border-gray-200/80 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-800 px-2.5 py-1 text-xs outline-none text-gray-700 dark:text-zinc-200 cursor-pointer"
                      title={zh ? '接口选择' : 'Select Interface'}
                    >
                      <option value="">{zh ? '整机吞吐量' : 'Device Total'}</option>
                      {interfaceOptions.map((name: string) => (
                        <option key={name} value={name}>{name}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-1.5">
                  {trendMetricDefs.map((m) => {
                    const active = trendMetrics.includes(m.key);
                    return (
                      <button
                        key={m.key}
                        type="button"
                        onClick={() => toggleTrendMetric(m.key)}
                        className={`inline-flex items-center gap-1.5 rounded-xl px-2.5 py-1 text-xs font-semibold transition-all cursor-pointer ${active ? 'bg-gray-900 text-white dark:bg-white dark:text-zinc-900 shadow-2xs' : 'bg-gray-100 dark:bg-zinc-800 text-gray-600 dark:text-zinc-300 hover:bg-gray-200'}`}
                      >
                        <span className={`h-1.5 w-1.5 rounded-full ${!active ? 'bg-gray-400' : 'bg-current'}`} />
                        {m.short}
                      </button>
                    );
                  })}
                </div>

                <div className="h-[240px] min-h-[240px] min-w-0 rounded-xl border border-gray-100 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-2">
                  {loading && trendData.length === 0 ? (
                    <div className="h-full flex flex-col items-center justify-center gap-2 text-xs text-gray-400">
                      <RefreshCw size={18} className="animate-spin text-blue-600" />
                      {zh ? '加载遥测趋势...' : 'Loading trends...'}
                    </div>
                  ) : trendData.length === 0 ? (
                    <div className="h-full flex flex-col items-center justify-center gap-2 text-center text-xs text-gray-400">
                      <Database size={22} className="opacity-40" />
                      <p className="font-medium">{zh ? '暂无流量趋势数据' : 'No trend data yet'}</p>
                    </div>
                  ) : (
                    <ResponsiveContainer width="100%" height="100%" minWidth={240} minHeight={200}>
                      <AreaChart data={trendData} margin={{ top: 8, right: 16, left: 8, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="2 4" vertical={false} stroke={ct.gridAlt} />
                        <XAxis
                          dataKey="ts"
                          axisLine={false}
                          tickLine={false}
                          tick={{ fontSize: 9, fill: ct.axisAlt }}
                          tickFormatter={(v) => fmtTime(String(v))}
                          minTickGap={40}
                        />
                        {hasThroughputMetric && (
                          <YAxis
                            yAxisId="throughput"
                            width={75}
                            axisLine={false}
                            tickLine={false}
                            tick={{ fontSize: 9, fill: ct.axisAlt }}
                            tickFormatter={(v) => fmtRate(Number(v))}
                          />
                        )}
                        {hasCountMetric && (
                          <YAxis
                            yAxisId="count"
                            width={60}
                            orientation="right"
                            axisLine={false}
                            tickLine={false}
                            tick={{ fontSize: 9, fill: ct.axisAlt }}
                            tickFormatter={(v) => Number(v || 0).toLocaleString()}
                          />
                        )}
                        <Tooltip
                          contentStyle={{ borderRadius: 12, border: 'none', padding: '8px 12px', background: ct.tooltipBg, color: ct.tooltipText, boxShadow: ct.tooltipShadow, fontSize: '11px' }}
                          labelFormatter={(v) => fmtFullTime(String(v))}
                          formatter={(v: any, _n: any, entry: any) => {
                            const mk = String(entry?.dataKey || '');
                            const def = trendMetricMap[mk as keyof typeof trendMetricMap];
                            if (v == null || !Number.isFinite(Number(v))) return ['--', def?.short || mk];
                            if (def?.unit === 'bps') return [fmtRate(Number(v)), def.short];
                            return [Number(v).toLocaleString() + ` ${def?.unit || ''}`, def?.short || mk];
                          }}
                        />
                        {selectedMetricDefs.map((m) => (
                          <Area
                            key={m.key}
                            type="monotone"
                            dataKey={m.key}
                            yAxisId={m.unit === 'bps' ? 'throughput' : 'count'}
                            stroke={m.color}
                            fill={`${m.color}14`}
                            strokeWidth={1.8}
                            name={m.short}
                            isAnimationActive={false}
                            connectNulls
                          />
                        ))}
                      </AreaChart>
                    </ResponsiveContainer>
                  )}
                </div>
              </div>

              {/* Alert History Timeline */}
              <div className="bg-white dark:bg-zinc-900/90 border border-gray-200/70 dark:border-zinc-800/80 rounded-2xl overflow-hidden shadow-2xs">
                <div className="px-4 py-3 border-b border-gray-200/70 dark:border-zinc-800/80 flex items-center justify-between gap-4">
                  <div>
                    <h3 className="text-sm font-bold text-gray-900 dark:text-white">{zh ? '设备告警时间线' : 'Device Alert Timeline'}</h3>
                    <p className="text-xs text-gray-400">{zh ? '当前设备发生的活跃与历史告警记录' : 'Active and history alerts for this device'}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <select
                      value={alertsSeverity}
                      onChange={(e) => { setAlertsSeverity(e.target.value); setAlertsPage(1); }}
                      className="bg-gray-50 dark:bg-zinc-800 border border-gray-200 dark:border-zinc-700 rounded-xl px-2.5 py-1 text-xs outline-none text-gray-700 dark:text-zinc-200 cursor-pointer"
                    >
                      <option value="all">{zh ? '全部级别' : 'All Severities'}</option>
                      <option value="critical">{zh ? '严重' : 'Critical'}</option>
                      <option value="major">{zh ? '主要' : 'Major'}</option>
                      <option value="warning">{zh ? '次要' : 'Minor'}</option>
                    </select>
                    <select
                      value={alertsPhase}
                      onChange={(e) => { setAlertsPhase(e.target.value); setAlertsPage(1); }}
                      className="bg-gray-50 dark:bg-zinc-800 border border-gray-200 dark:border-zinc-700 rounded-xl px-2.5 py-1 text-xs outline-none text-gray-700 dark:text-zinc-200 cursor-pointer"
                    >
                      <option value="all">{zh ? '全部阶段' : 'All Phases'}</option>
                      <option value="active">{zh ? '告警中' : 'Active'}</option>
                      <option value="recovered">{zh ? '已恢复' : 'Recovered'}</option>
                    </select>
                  </div>
                </div>

                <div className="overflow-auto max-h-[240px]">
                  <table className="nx-data-table nx-data-table--compact">
                    <thead className="bg-gray-50 dark:bg-zinc-800 sticky top-0">
                      <tr>
                        <th className="px-4 py-2 text-left text-[10px] uppercase tracking-wider text-gray-400">{zh ? '发生时间' : 'Time'}</th>
                        <th className="px-4 py-2 text-left text-[10px] uppercase tracking-wider text-gray-400">{zh ? '级别' : 'Severity'}</th>
                        <th className="px-4 py-2 text-left text-[10px] uppercase tracking-wider text-gray-400">{zh ? '状态' : 'Phase'}</th>
                        <th className="px-4 py-2 text-left text-[10px] uppercase tracking-wider text-gray-400">{zh ? '告警项' : 'Title'}</th>
                        <th className="px-4 py-2 text-left text-[10px] uppercase tracking-wider text-gray-400">{zh ? '详情' : 'Message'}</th>
                        <th className="px-4 py-2 text-left text-[10px] uppercase tracking-wider text-gray-400">{zh ? '恢复时间' : 'Recovered At'}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 dark:divide-zinc-800">
                      {alerts.map((a) => {
                        const sev = String(a.severity).toLowerCase();
                        const isRecovered = a.resolved_at !== null;
                        return (
                          <tr key={a.id} className="hover:bg-gray-50/70 dark:hover:bg-zinc-800/40">
                            <td className="px-4 py-2 text-gray-400 whitespace-nowrap">{fmtFullTime(a.created_at)}</td>
                            <td className="px-4 py-2">
                              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${sev === 'critical' ? 'bg-rose-50 text-rose-700' : sev === 'major' ? 'bg-amber-50 text-amber-700' : 'bg-blue-50 text-blue-700'}`}>
                                {sev === 'critical' ? (zh ? '严重' : 'Critical') : sev === 'major' ? (zh ? '主要' : 'Major') : (zh ? '次要' : 'Minor')}
                              </span>
                            </td>
                            <td className="px-4 py-2">
                              <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-bold ${isRecovered ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'}`}>
                                {isRecovered ? (zh ? '已恢复' : 'Recovered') : (zh ? '告警中' : 'Active')}
                              </span>
                            </td>
                            <td className="px-4 py-2 font-semibold text-gray-800 dark:text-zinc-200 max-w-[150px] truncate">{a.title}</td>
                            <td className="px-4 py-2 text-gray-400 max-w-[200px] truncate">{a.message}</td>
                            <td className="px-4 py-2 text-gray-400 whitespace-nowrap">{a.resolved_at ? fmtFullTime(a.resolved_at) : '-'}</td>
                          </tr>
                        );
                      })}
                      {alerts.length === 0 && (
                        <tr>
                          <td colSpan={6} className="px-4 py-8 text-center text-xs text-gray-400">
                            {zh ? '暂无告警记录' : 'No alerts recorded'}
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>

                {alertTotal > 10 && (
                  <div className="flex flex-col gap-3 px-5 py-3 border-t border-gray-200/70 dark:border-zinc-800/80 lg:flex-row lg:items-center lg:justify-between">
                    <p className="text-[10px] font-bold uppercase text-gray-400 tracking-widest">
                      {zh ? `第 ${(alertsPage - 1) * 10 + 1}-${Math.min(alertsPage * 10, alertTotal)} 条 / 共 ${alertTotal} 条` : `${(alertsPage - 1) * 10 + 1}-${Math.min(alertsPage * 10, alertTotal)} / ${alertTotal}`}
                    </p>
                    <div className="flex items-center gap-1.5">
                      <button
                        type="button"
                        disabled={alertsPage === 1}
                        onClick={() => setAlertsPage((p) => p - 1)}
                        className="inline-flex h-7 items-center gap-1 rounded-lg border border-gray-200/80 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-2 text-[11px] font-semibold text-gray-600 dark:text-zinc-300 hover:bg-gray-50 transition-all cursor-pointer disabled:opacity-30"
                      >
                        <ChevronLeft size={13} />
                      </button>
                      <span className="text-xs font-bold px-2 text-gray-700 dark:text-zinc-300">{alertsPage} / {Math.ceil(alertTotal / 10)}</span>
                      <button
                        type="button"
                        disabled={alertsPage >= Math.ceil(alertTotal / 10)}
                        onClick={() => setAlertsPage((p) => p + 1)}
                        className="inline-flex h-7 items-center gap-1 rounded-lg border border-gray-200/80 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-2 text-[11px] font-semibold text-gray-600 dark:text-zinc-300 hover:bg-gray-50 transition-all cursor-pointer disabled:opacity-30"
                      >
                        <ChevronRight size={13} />
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default NetworkMonitoring;
