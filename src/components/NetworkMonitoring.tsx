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

  const [search, setSearch] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Read ?q= URL param on mount to pre-fill search (deep-link from NPA hop popover)
  useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      const q = params.get('q');
      if (q) {
        setSearch(q);
        // Auto-select matching device
        const match = (devices || []).find(d => !isServerDevice(d) && d.ip_address === q);
        if (match) setSelectedId(String(match.id));
      }
    } catch { /* ignore */ }
  }, [devices]);
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

  const networkDevices = useMemo(() => (devices || []).filter((d) => !isServerDevice(d)), [devices]);

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

  const filteredDevices = useMemo(() => {
    const q = search.trim().toLowerCase();
    let list = networkDevices;
    if (siteFilter !== 'all') {
      list = list.filter((d) => String(d.site_id || d.site || '') === siteFilter);
    }
    if (statusFilter === 'online') {
      list = list.filter((d) => String(d.status || '').toLowerCase() === 'online');
    } else if (statusFilter === 'offline') {
      list = list.filter((d) => String(d.status || '').toLowerCase() !== 'online');
    }
    if (!q) return list;
    return list.filter((d) =>
      (d.hostname || '').toLowerCase().includes(q) || (d.ip_address || '').toLowerCase().includes(q),
    );
  }, [networkDevices, search, siteFilter, statusFilter]);

  const selectedDevice = useMemo(
    () => networkDevices.find((d) => d.id === selectedId) || null,
    [networkDevices, selectedId],
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
    if (!selectedId && filteredDevices.length > 0) {
      setSelectedId(filteredDevices[0].id);
    }
  }, [filteredDevices, selectedId]);

  const fetchRealtime = useCallback(async (deviceId: string, signal?: AbortSignal) => {
    const resp = await fetch(`/api/monitoring/device/${deviceId}/realtime?window_minutes=15&limit=1000`, {
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
    if (!autoRefresh || !selectedId) return;

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
  }, [autoRefresh, selectedId, rangeHours, trendInterface, alertsPage, alertsSeverity, alertsPhase, loadDeviceData]);

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
    }));
  }, [trendSeries]);

  const trendMetricDefs = [
    { key: 'in_bps', label: zh ? '入流量' : 'IN Throughput', short: 'IN', color: '#2563eb', unit: 'bps' },
    { key: 'out_bps', label: zh ? '出流量' : 'OUT Throughput', short: 'OUT', color: '#ea580c', unit: 'bps' },
    { key: 'in_pkts', label: zh ? '入包数' : 'IN Packets', short: 'IN Pkts', color: '#7c3aed', unit: 'pps' },
    { key: 'out_pkts', label: zh ? '出包数' : 'OUT Packets', short: 'OUT Pkts', color: '#0891b2', unit: 'pps' },
    { key: 'errors', label: zh ? '错包数' : 'Errors', short: 'Errors', color: '#dc2626', unit: 'cnt' },
    { key: 'drops', label: zh ? '丢包数' : 'Drops', short: 'Drops', color: '#16a34a', unit: 'cnt' },
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

  const interfaceOptions = useMemo(() => {
    const list = realtimeData?.latest_interfaces || [];
    return list.map((it: any) => String(it.interface_name || '')).filter(Boolean);
  }, [realtimeData]);

  // Empty state check
  if (networkDevices.length === 0) {
    return (
      <div className="network-monitoring-page flex flex-col h-full overflow-hidden">
        <PageHero
          icon={Router}
          title={zh ? '网络监控' : 'Network Monitoring'}
          subtitle={zh ? '网络交换机/路由器性能遥测 · 接口 SNMP 流量分析' : 'Network switch/router telemetry · Interface SNMP traffic analysis'}
        />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center max-w-md px-6">
            <Router size={40} className="mx-auto mb-3 text-[var(--muted-text)] opacity-40" />
            <p className="text-sm font-semibold text-[var(--app-text)]">{zh ? '暂无网络设备' : 'No network devices'}</p>
            <p className="mt-1 text-xs text-[var(--muted-text)]">
              {zh
                ? '请在「资产管理」中添加平台类型不是 Linux 的交换机、路由器等网络设备。'
                : 'Add switch, router or firewall network devices in Asset Management.'}
            </p>
          </div>
        </div>
      </div>
    );
  }

  const latestTrendPoint = trendData.length > 0 ? trendData[trendData.length - 1] : null;
  const snapshotDevice = realtimeData?.device || selectedDevice;
  const lastSampleAt = realtimeData?.updated_at || realtimeData?.timestamp;
  const collectionLabel = (collector: string) => ({
    reachability: zh ? '可达性' : 'Reachability',
    snmp_metrics: zh ? 'SNMP 整机' : 'SNMP Metrics',
    snmp_interfaces: zh ? 'SNMP 接口' : 'SNMP Interfaces',
    snmp_inventory: zh ? 'SNMP 资产信息' : 'SNMP Inventory',
    topology_lldp: zh ? 'LLDP 拓扑' : 'LLDP Topology',
  }[collector] || collector);
  const collectionTone = (status: string) => {
    if (status === 'success') return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10';
    if (status === 'stale') return 'border-amber-200 bg-amber-50 text-amber-700 dark:bg-amber-500/10';
    if (status === 'skipped') return 'border-slate-200 bg-slate-50 text-slate-600 dark:bg-white/[0.04]';
    return 'border-rose-200 bg-rose-50 text-rose-700 dark:bg-rose-500/10';
  };

  return (
    <div className="network-monitoring-page flex flex-col h-full overflow-hidden">
      <PageHero
        icon={Router}
        title={zh ? '网络监控' : 'Network Monitoring'}
        subtitle={zh ? '网络交换机/路由器性能遥测 · 接口 SNMP 流量分析' : 'Network switch/router telemetry · Interface SNMP traffic analysis'}
        actions={
          <>
            <div className="inline-flex rounded-xl border border-[var(--card-border)] overflow-hidden">
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

      <div className="ops-page-scroll flex-1 overflow-hidden flex">
        {/* ── Left: Switch list ── */}
        <div className="w-[276px] shrink-0 border-r border-[var(--ops-line)] bg-[color:var(--ops-bg)]/60 flex flex-col overflow-hidden">
          <div className="p-3 border-b border-[var(--card-border)] space-y-2">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted-text)]" size={14} />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={zh ? '搜索设备名 / IP' : 'Search switch / IP'}
              className="ops-control w-full pl-9 pr-3 py-2 rounded-xl text-sm outline-none text-[var(--app-text)]"
              />
            </div>

            <select
              value={siteFilter}
              onChange={(e) => setSiteFilter(e.target.value)}
              className="ops-control w-full rounded-xl px-2 py-1.5 text-xs outline-none"
            >
              <option value="all" className="bg-[var(--card-bg)]">{zh ? '全部区域' : 'All Sites'}</option>
              {uniqueSites.map((site) => (
                <option key={site.id} value={site.id} className="bg-[var(--card-bg)]">{site.name}</option>
              ))}
            </select>

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

            <p className="text-[10px] font-bold uppercase tracking-wider text-[var(--muted-text)]">
              {filteredDevices.length} {zh ? '台网络设备' : 'switches'}
            </p>
          </div>

          <VirtualizedDeviceList
            items={filteredDevices}
            getKey={(dev) => dev.id}
            empty={<p className="p-4 text-center text-xs text-[var(--muted-text)]">{zh ? '无匹配设备' : 'No match'}</p>}
            renderItem={(dev) => {
              const online = String(dev.status || '').toLowerCase() === 'online';
              const active = selectedId === dev.id;
              return (
                <button
                  type="button"
                  onClick={() => setSelectedId(dev.id)}
                  className={`w-full flex items-center gap-2.5 rounded-xl border px-3 py-2.5 text-left transition-all ${active ? 'border-sky-400 bg-sky-500/[0.07] shadow-sm' : 'border-transparent hover:border-[var(--card-border)] hover:bg-black/[0.02]'}`}
                >
                  <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${active ? 'bg-sky-500/15 text-sky-600' : 'bg-black/[0.04] text-[var(--muted-text)]'}`}>
                    <Router size={15} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <p className="truncate text-sm font-semibold text-[var(--app-text)]">{dev.hostname || dev.ip_address}</p>
                      <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ backgroundColor: online ? '#10b981' : '#94a3b8' }} />
                    </div>
                    <p className="truncate text-[11px] font-mono text-[var(--muted-text)]">{dev.ip_address}</p>
                  </div>
                </button>
              );
            }}
          />
        </div>

        {/* ── Right: Telemetry details ── */}
        <div className="flex-1 overflow-auto p-6 space-y-5">
          {!selectedDevice ? (
            <div className="flex h-full items-center justify-center text-sm text-[var(--muted-text)]">
              {zh ? '从左侧选择一台网络设备' : 'Select a network device from the left'}
            </div>
          ) : (
            <>
              {/* Header card */}
              <div className="ops-surface flex items-center justify-between rounded-2xl px-5 py-3.5">
                <div className="flex items-center gap-3">
                  <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-sky-500/10 text-sky-600">
                    <Router size={18} />
                  </span>
                  <div>
                    <p className="text-base font-bold text-[var(--app-text)]">{selectedDevice.hostname || selectedDevice.ip_address}</p>
                    <p className="text-[11px] font-mono text-[var(--muted-text)]">
                      {selectedDevice.ip_address} · {selectedDevice.platform || 'SNMP Agent'}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2 text-[11px] text-[var(--muted-text)]">
                  <Clock size={13} />
                  {lastSampleAt ? (zh ? `最近采样 ${fmtTime(lastSampleAt)}` : `Last sample ${fmtTime(lastSampleAt)}`) : (zh ? '等待数据' : 'Awaiting data')}
                </div>
              </div>

              {dataError && (
                <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800 dark:bg-amber-500/10">
                  {zh ? '本次刷新失败，当前保留上一次有效数据：' : 'Refresh failed; the last valid snapshot is retained: '}{dataError}
                </div>
              )}

              <div className="ops-surface rounded-2xl p-4">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="text-xs font-extrabold uppercase tracking-wider text-[var(--muted-text)]">
                      {zh ? '采集健康与数据新鲜度' : 'Collection Health & Freshness'}
                    </h3>
                    <span className="text-[10px] text-[var(--muted-text)]">
                      {zh ? '快照 30 秒 / 趋势 60 秒刷新' : 'Snapshot 30s / trend 60s refresh'}
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={runCollectionDiagnostics}
                    disabled={diagnosticsLoading}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-sky-200 bg-sky-50 px-2.5 py-1.5 text-[10px] font-bold text-sky-700 transition hover:bg-sky-100 disabled:cursor-wait disabled:opacity-60"
                  >
                    <Activity size={12} className={diagnosticsLoading ? 'animate-pulse' : ''} />
                    {diagnosticsLoading ? (zh ? '诊断中…' : 'Diagnosing…') : (zh ? '诊断采集链路' : 'Diagnose Collection')}
                  </button>
                </div>
                {collectionStatus.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-[var(--card-border)] px-4 py-5 text-center text-xs text-[var(--muted-text)]">
                    {zh ? '尚无采集状态；等待下一轮后台采集或执行 SNMP 测试。' : 'No collector state yet. Wait for the next poll or run an SNMP test.'}
                  </div>
                ) : (
                  <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
                    {collectionStatus.map((item) => (
                      <div key={item.collector} className={`rounded-xl border px-3 py-2.5 ${collectionTone(item.effective_status)}`}>
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate text-[11px] font-bold">{collectionLabel(item.collector)}</span>
                          <span className="text-[9px] font-extrabold uppercase">{item.effective_status}</span>
                        </div>
                        <p className="mt-1 truncate text-[10px] opacity-75">
                          {item.last_success_at
                            ? `${zh ? '成功于' : 'Success'} ${fmtFullTime(item.last_success_at)}`
                            : (item.error_code || (zh ? '尚未成功' : 'No successful sample'))}
                        </p>
                        {(item.coverage_total > 0 || item.consecutive_failures > 0) && (
                          <p className="mt-1 text-[9px] opacity-70">
                            {item.coverage_total > 0 ? `${zh ? '覆盖' : 'Coverage'} ${item.coverage_supported}/${item.coverage_total}` : ''}
                            {item.consecutive_failures > 0 ? ` · ${zh ? '连续失败' : 'Failures'} ${item.consecutive_failures}` : ''}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                {diagnosticResult && (
                  <div className="mt-3 grid gap-2 sm:grid-cols-3">
                    {Object.entries(diagnosticResult.checks).map(([key, check]) => (
                      <div key={key} className={`rounded-lg border px-3 py-2 text-[10px] ${check.status === 'success' ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : check.status === 'not_configured' || check.status === 'skipped' ? 'border-slate-200 bg-slate-50 text-slate-600' : 'border-rose-200 bg-rose-50 text-rose-700'}`}>
                        <div className="flex items-center justify-between gap-2 font-bold"><span>{key.toUpperCase()}</span><span>{check.status}</span></div>
                        <p className="mt-1 opacity-75">{check.code || check.error || ''}{check.port ? ` · ${check.port}` : ''}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Hardware Performance Snapshot (Gracefully handles null/0 OID values for EVE-IOU) */}
              <div className="ops-surface rounded-2xl p-5">
                <h3 className="text-xs font-extrabold uppercase tracking-wider text-[var(--muted-text)] mb-4">
                  {zh ? '最新整机状态快照 (SNMP)' : 'Latest Hardware Status Snapshot (SNMP)'}
                </h3>
                <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                  <div className="flex flex-col items-center justify-center p-4 rounded-xl border border-[var(--card-border)] bg-black/[0.015] dark:bg-white/[0.015]">
                    <Cpu size={20} className="text-sky-500 mb-2" />
                    <span className="text-[10px] uppercase font-bold text-[var(--muted-text)]">CPU</span>
                    <p className="text-xl font-extrabold text-[var(--app-text)] mt-1 font-mono">
                      {snapshotDevice?.cpu_usage != null && Number.isFinite(Number(snapshotDevice.cpu_usage)) ? `${snapshotDevice.cpu_usage}%` : '--'}
                    </p>
                  </div>

                  <div className="flex flex-col items-center justify-center p-4 rounded-xl border border-[var(--card-border)] bg-black/[0.015] dark:bg-white/[0.015]">
                    <MemoryStick size={20} className="text-violet-500 mb-2" />
                    <span className="text-[10px] uppercase font-bold text-[var(--muted-text)]">Memory</span>
                    <p className="text-xl font-extrabold text-[var(--app-text)] mt-1 font-mono">
                      {snapshotDevice?.memory_usage != null && Number.isFinite(Number(snapshotDevice.memory_usage)) ? `${snapshotDevice.memory_usage}%` : '--'}
                    </p>
                  </div>

                  <div className="flex flex-col items-center justify-center p-4 rounded-xl border border-[var(--card-border)] bg-black/[0.015] dark:bg-white/[0.015]">
                    <Thermometer size={20} className="text-amber-500 mb-2" />
                    <span className="text-[10px] uppercase font-bold text-[var(--muted-text)]">Temperature</span>
                    <p className="text-xl font-extrabold text-[var(--app-text)] mt-1 font-mono">
                      {snapshotDevice?.temp != null && Number.isFinite(Number(snapshotDevice.temp)) ? `${snapshotDevice.temp}°C` : '--'}
                    </p>
                  </div>

                  <div className="flex flex-col items-center justify-center p-4 rounded-xl border border-[var(--card-border)] bg-black/[0.015] dark:bg-white/[0.015]">
                    <Wind size={20} className="text-emerald-500 mb-2" />
                    <span className="text-[10px] uppercase font-bold text-[var(--muted-text)]">Fan Status</span>
                    <p className={`text-sm font-extrabold mt-2 ${hardwareStatusTone(snapshotDevice?.fan_status)}`}>
                      {getFanStatusLabel(snapshotDevice?.fan_status)}
                    </p>
                  </div>

                  <div className="flex flex-col items-center justify-center p-4 rounded-xl border border-[var(--card-border)] bg-black/[0.015] dark:bg-white/[0.015]">
                    <Zap size={20} className="text-orange-500 mb-2" />
                    <span className="text-[10px] uppercase font-bold text-[var(--muted-text)]">Power (PSU)</span>
                    <p className={`text-sm font-extrabold mt-2 ${hardwareStatusTone(snapshotDevice?.psu_status)}`}>
                      {getPsuStatusLabel(snapshotDevice?.psu_status)}
                    </p>
                  </div>
                </div>
              </div>

              {/* Interface Table */}
              <div className="ops-surface rounded-2xl p-5">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-xs font-extrabold uppercase tracking-wider text-[var(--muted-text)]">
                    {zh ? '接口流量与丢包统计 (SNMP)' : 'Interfaces & Realtime Telemetry (SNMP)'}
                  </h3>
                  {realtimeData?.summary && (
                    <div className="text-[10px] font-mono text-[var(--muted-text)] flex gap-4">
                      <span>IN: {fmtRate(Number(realtimeData.summary.in_bps || 0))}</span>
                      <span>OUT: {fmtRate(Number(realtimeData.summary.out_bps || 0))}</span>
                      {realtimeData.summary.errors > 0 && <span className="text-red-500 font-bold">ERR: {realtimeData.summary.errors}</span>}
                    </div>
                  )}
                </div>

                <div className="max-h-[300px] overflow-auto border border-[var(--card-border)] rounded-xl">
                  <table className="w-full text-xs">
                    <thead className="bg-black/[0.02] dark:bg-white/[0.02] sticky top-0 backdrop-blur-md">
                      <tr>
                        <th className="px-4 py-2.5 text-left text-[10px] uppercase tracking-wider text-[var(--muted-text)]">Interface</th>
                        <th className="px-4 py-2.5 text-left text-[10px] uppercase tracking-wider text-[var(--muted-text)]">Status</th>
                        <th className="px-4 py-2.5 text-right text-[10px] uppercase tracking-wider text-[var(--muted-text)]">IN</th>
                        <th className="px-4 py-2.5 text-right text-[10px] uppercase tracking-wider text-[var(--muted-text)]">OUT</th>
                        <th className="px-4 py-2.5 text-right text-[10px] uppercase tracking-wider text-[var(--muted-text)]">BW%</th>
                        <th className="px-4 py-2.5 text-right text-[10px] uppercase tracking-wider text-[var(--muted-text)]">Errors</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-black/5 dark:divide-white/5">
                      {(realtimeData?.latest_interfaces || []).map((it: any, idx: number) => {
                        const bw = Math.max(Number(it.bw_in_pct || 0), Number(it.bw_out_pct || 0));
                        const isUp = String(it.status).toLowerCase() === 'up';
                        return (
                          <tr key={`${it.interface_name}-${idx}`} className="hover:bg-black/[0.015] dark:hover:bg-white/[0.015]">
                            <td className="px-4 py-2 font-mono text-[var(--app-text)] font-semibold">{it.interface_name}</td>
                            <td className="px-4 py-2">
                              <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[9px] font-extrabold uppercase ${isUp ? 'bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10' : 'bg-red-50 text-red-500 dark:bg-red-500/10'}`}>
                                <span className={`h-1.5 w-1.5 rounded-full ${isUp ? 'bg-emerald-500' : 'bg-red-500'}`} />
                                {it.status}
                              </span>
                            </td>
                            <td className="px-4 py-2 text-right font-mono text-blue-600 dark:text-blue-400">{fmtRate(it.in_bps)}</td>
                            <td className="px-4 py-2 text-right font-mono text-orange-600 dark:text-orange-400">{fmtRate(it.out_bps)}</td>
                            <td className="px-4 py-2 text-right font-mono text-[var(--app-text)]">{bw.toFixed(1)}%</td>
                            <td className="px-4 py-2 text-right font-mono text-[var(--app-text)]">{Number(it.in_errors || 0) + Number(it.out_errors || 0)}</td>
                          </tr>
                        );
                      })}
                      {(!realtimeData?.latest_interfaces || realtimeData.latest_interfaces.length === 0) && (
                        <tr>
                          <td colSpan={6} className="px-4 py-8 text-center text-sm text-[var(--muted-text)]">
                            {zh ? '暂无实时接口样本' : 'No realtime interface samples yet'}
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Trend Chart */}
              <div className="ops-surface rounded-2xl p-5 space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-extrabold uppercase tracking-wider text-[var(--muted-text)]">{zh ? '性能趋势分析' : 'Performance Trends'}</h3>
                    <p className="text-[11px] text-[var(--muted-text)]">{zh ? '接口或整机的流量与包速率变化趋势' : 'Interface or device traffic history'}</p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <select
                      value={trendInterface}
                      onChange={(e) => setTrendInterface(e.target.value)}
                      className="rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-1 text-xs outline-none text-[var(--app-text)]"
                      title={zh ? '接口选择' : 'Select Interface'}
                    >
                      <option value="">{zh ? '整机吞吐量' : 'Device Total'}</option>
                      {interfaceOptions.map((name: string) => (
                        <option key={name} value={name}>{name}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  {trendMetricDefs.map((m) => {
                    const active = trendMetrics.includes(m.key);
                    return (
                      <button
                        key={m.key}
                        type="button"
                        onClick={() => toggleTrendMetric(m.key)}
                        className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[11px] font-semibold transition-all ${active ? 'border-black/20 bg-black/[0.04] dark:bg-white/[0.06] text-[var(--app-text)]' : 'border-transparent text-[var(--muted-text)] hover:bg-black/[0.02]'}`}
                      >
                        <span className={`h-2 w-2 rounded-full ${!active ? 'bg-slate-300' : ''}`} style={active ? { backgroundColor: m.color } : undefined} />
                        {m.short}
                      </button>
                    );
                  })}
                </div>

                <div className="h-[250px] min-h-[250px] min-w-0 rounded-xl border border-[var(--card-border)] bg-black/[0.01] p-2">
                  {loading && trendData.length === 0 ? (
                    <div className="h-full flex flex-col items-center justify-center gap-2 text-sm text-[var(--muted-text)]">
                      <RefreshCw size={20} className="animate-spin text-sky-500" />
                      {zh ? '加载遥测趋势...' : 'Loading trends...'}
                    </div>
                  ) : trendData.length === 0 ? (
                    <div className="h-full flex flex-col items-center justify-center gap-2 text-center">
                      <Database size={24} className="text-[var(--muted-text)] opacity-40" />
                      <p className="text-sm font-medium text-[var(--muted-text)]">{zh ? '暂无流量趋势数据' : 'No trend data yet'}</p>
                    </div>
                  ) : (
                    <ResponsiveContainer width="100%" height="100%" minWidth={240} minHeight={220}>
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
                            width={80}
                            axisLine={false}
                            tickLine={false}
                            tick={{ fontSize: 9, fill: ct.axisAlt }}
                            tickFormatter={(v) => fmtRate(Number(v))}
                          />
                        )}
                        {hasCountMetric && (
                          <YAxis
                            yAxisId="count"
                            width={68}
                            orientation="right"
                            axisLine={false}
                            tickLine={false}
                            tick={{ fontSize: 9, fill: ct.axisAlt }}
                            tickFormatter={(v) => Number(v || 0).toLocaleString()}
                          />
                        )}
                        <Tooltip
                          contentStyle={{ borderRadius: 12, borderColor: ct.tooltipBorder, padding: '10px 14px', background: ct.tooltipBg, color: ct.tooltipText }}
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

                {latestTrendPoint && selectedMetricDefs.length > 0 && (
                  <div className="flex flex-wrap gap-2 text-[10px] font-semibold text-[var(--muted-text)] font-mono">
                    {selectedMetricDefs.map((m) => {
                      const val = (latestTrendPoint as any)[m.key];
                      return (
                        <span key={`legend-${m.key}`} className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-0.5">
                          <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: m.color }} />
                          <span>{m.short}: {val != null ? (m.unit === 'bps' ? fmtRate(val) : Number(val).toLocaleString()) : '--'}</span>
                        </span>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Alert History Timeline */}
              <div className="ops-surface rounded-2xl overflow-hidden">
                <div className="px-4 py-3 border-b border-[var(--card-border)] flex items-center justify-between gap-4 bg-black/[0.01] dark:bg-white/[0.01]">
                  <div>
                    <h3 className="text-xs font-extrabold uppercase tracking-wider text-[var(--app-text)]">{zh ? '设备告警时间线' : 'Device Alert Timeline'}</h3>
                    <p className="text-[10px] text-[var(--muted-text)]">{zh ? '当前设备发生的活跃与历史告警记录' : 'Active and history alerts for this device'}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <select
                      value={alertsSeverity}
                      onChange={(e) => { setAlertsSeverity(e.target.value); setAlertsPage(1); }}
                      className="bg-[var(--card-bg)] border border-[var(--card-border)] rounded-lg px-2 py-1 text-xs outline-none text-[var(--app-text)]"
                    >
                      <option value="all">{zh ? '全部级别' : 'All Severities'}</option>
                      <option value="critical">{zh ? '严重' : 'Critical'}</option>
                      <option value="major">{zh ? '主要' : 'Major'}</option>
                      <option value="warning">{zh ? '次要' : 'Minor'}</option>
                    </select>
                    <select
                      value={alertsPhase}
                      onChange={(e) => { setAlertsPhase(e.target.value); setAlertsPage(1); }}
                      className="bg-[var(--card-bg)] border border-[var(--card-border)] rounded-lg px-2 py-1 text-xs outline-none text-[var(--app-text)]"
                    >
                      <option value="all">{zh ? '全部阶段' : 'All Phases'}</option>
                      <option value="active">{zh ? '告警中' : 'Active'}</option>
                      <option value="recovered">{zh ? '已恢复' : 'Recovered'}</option>
                    </select>
                  </div>
                </div>

                <div className="overflow-auto">
                  <table className="w-full text-xs">
                    <thead className="bg-black/[0.02] dark:bg-white/[0.02]">
                      <tr>
                        <th className="px-4 py-2 text-left text-[10px] uppercase tracking-wider text-[var(--muted-text)]">{zh ? '发生时间' : 'Time'}</th>
                        <th className="px-4 py-2 text-left text-[10px] uppercase tracking-wider text-[var(--muted-text)]">{zh ? '级别' : 'Severity'}</th>
                        <th className="px-4 py-2 text-left text-[10px] uppercase tracking-wider text-[var(--muted-text)]">{zh ? '状态' : 'Phase'}</th>
                        <th className="px-4 py-2 text-left text-[10px] uppercase tracking-wider text-[var(--muted-text)]">{zh ? '告警项' : 'Title'}</th>
                        <th className="px-4 py-2 text-left text-[10px] uppercase tracking-wider text-[var(--muted-text)]">{zh ? '详情' : 'Message'}</th>
                        <th className="px-4 py-2 text-left text-[10px] uppercase tracking-wider text-[var(--muted-text)]">{zh ? '恢复时间' : 'Recovered At'}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-black/5 dark:divide-white/5">
                      {alerts.map((a) => {
                        const sev = String(a.severity).toLowerCase();
                        const isRecovered = a.resolved_at !== null;
                        return (
                          <tr key={a.id} className="hover:bg-black/[0.01] dark:hover:bg-white/[0.01]">
                            <td className="px-4 py-2 text-[var(--muted-text)] whitespace-nowrap">{fmtFullTime(a.created_at)}</td>
                            <td className="px-4 py-2">
                              <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full ${sev === 'critical' ? 'bg-red-100 text-red-700' : sev === 'major' ? 'bg-orange-100 text-orange-700' : 'bg-black/5 text-[var(--muted-text)]'}`}>
                                {sev === 'critical' ? (zh ? '严重' : 'Critical') : sev === 'major' ? (zh ? '主要' : 'Major') : (zh ? '次要' : 'Minor')}
                              </span>
                            </td>
                            <td className="px-4 py-2">
                              <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-bold ${isRecovered ? 'bg-emerald-100 text-emerald-700' : 'bg-sky-100 text-sky-700'}`}>
                                {isRecovered ? (zh ? '已恢复' : 'Recovered') : (zh ? '告警中' : 'Active')}
                              </span>
                            </td>
                            <td className="px-4 py-2 font-semibold text-[var(--app-text)] max-w-[150px] truncate">{a.title}</td>
                            <td className="px-4 py-2 text-[var(--muted-text)] max-w-[200px] truncate">{a.message}</td>
                            <td className="px-4 py-2 text-[var(--muted-text)] whitespace-nowrap">{a.resolved_at ? fmtFullTime(a.resolved_at) : '-'}</td>
                          </tr>
                        );
                      })}
                      {alerts.length === 0 && (
                        <tr>
                          <td colSpan={6} className="px-4 py-8 text-center text-sm text-[var(--muted-text)]">
                            {zh ? '暂无告警记录' : 'No alerts recorded'}
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>

                {alertTotal > 10 && (
                  <div className="flex flex-col gap-3 px-5 py-3 border-t border-[var(--card-border)] lg:flex-row lg:items-center lg:justify-between">
                    <p className="text-[10px] font-bold uppercase text-[var(--muted-text)] tracking-widest">
                      {zh ? `第 ${(alertsPage - 1) * 10 + 1}-${Math.min(alertsPage * 10, alertTotal)} 条 / 共 ${alertTotal} 条` : `${(alertsPage - 1) * 10 + 1}-${Math.min(alertsPage * 10, alertTotal)} / ${alertTotal}`}
                    </p>
                    <div className="flex items-center gap-1.5">
                      <button
                        type="button"
                        disabled={alertsPage === 1}
                        onClick={() => setAlertsPage((p) => p - 1)}
                        className="inline-flex h-8 items-center gap-1 rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 text-[11px] font-semibold text-[var(--muted-text)] transition-all hover:border-black/15 disabled:opacity-25"
                      >
                        <ChevronLeft size={14} />
                      </button>
                      <span className="text-xs font-bold px-2">{alertsPage} / {Math.ceil(alertTotal / 10)}</span>
                      <button
                        type="button"
                        disabled={alertsPage >= Math.ceil(alertTotal / 10)}
                        onClick={() => setAlertsPage((p) => p + 1)}
                        className="inline-flex h-8 items-center gap-1 rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 text-[11px] font-semibold text-[var(--muted-text)] transition-all hover:border-black/15 disabled:opacity-25"
                      >
                        <ChevronRight size={14} />
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
