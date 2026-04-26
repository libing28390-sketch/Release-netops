import { useState, useCallback, useEffect, useRef } from 'react';
import type { HostResourceSnapshot } from '../types';

interface UseMonitoringProps {
  isAuthenticated: boolean;
  activeTab: string;
  language: string;
}

const isAbortError = (error: unknown) => {
  if (!error) return false;
  if (error instanceof DOMException && error.name === 'AbortError') return true;
  return typeof error === 'object' && (error as { name?: string }).name === 'AbortError';
};

export const useMonitoring = ({ isAuthenticated, activeTab, language }: UseMonitoringProps) => {
  const [monitorSearch, setMonitorSearch] = useState('');
  const [monitorSearchResults, setMonitorSearchResults] = useState<any[]>([]);
  const [monitorSearching, setMonitorSearching] = useState(false);
  const [monitorSelectedDevice, setMonitorSelectedDevice] = useState<any | null>(null);
  const [monitorOverview, setMonitorOverview] = useState<any | null>(null);
  const [monitorRealtime, setMonitorRealtime] = useState<any | null>(null);
  const [monitorTrend, setMonitorTrend] = useState<any | null>(null);
  const [monitorTrendInterface, setMonitorTrendInterface] = useState('');
  const [monitorTrendResolution, setMonitorTrendResolution] = useState<'1m' | '5m'>('1m');
  const [monitorTrendStartInput, setMonitorTrendStartInput] = useState('');
  const [monitorTrendEndInput, setMonitorTrendEndInput] = useState('');
  const [monitorTrendRange, setMonitorTrendRange] = useState<{ start_time?: string; end_time?: string }>({});
  const [monitorTrendZoom, setMonitorTrendZoom] = useState<{ startIndex: number; endIndex: number } | null>(null);
  const [monitorTrendDragStart, setMonitorTrendDragStart] = useState<number | null>(null);
  const [monitorTrendDragEnd, setMonitorTrendDragEnd] = useState<number | null>(null);
  const [monitorTrendMetrics, setMonitorTrendMetrics] = useState<string[]>(['in_bps', 'out_bps']);
  const [monitorTrendUiMode, setMonitorTrendUiMode] = useState<'pro' | 'compact'>(() => {
    const saved = localStorage.getItem('netops_monitor_trend_ui_mode');
    return saved === 'pro' ? 'pro' : 'compact';
  });
  const [monitorAlerts, setMonitorAlerts] = useState<any[]>([]);
  const [monitorAlertTotal, setMonitorAlertTotal] = useState(0);
  const [monitorAlertsPage, setMonitorAlertsPage] = useState(1);
  const [monitorAlertsPageSize] = useState(10);
  const [monitorAlertsSeverity, setMonitorAlertsSeverity] = useState('all');
  const [monitorAlertsPhase, setMonitorAlertsPhase] = useState('all');
  const [monitorLoading, setMonitorLoading] = useState(false);
  const [monitorPageVisible, setMonitorPageVisible] = useState(() => typeof document === 'undefined' ? true : document.visibilityState === 'visible');
  const [monitorDashboardSiteFilter, setMonitorDashboardSiteFilter] = useState('all');
  const [monitorDashboardAlertFilter, setMonitorDashboardAlertFilter] = useState<'all' | 'critical' | 'major' | 'warning'>('all');
  const [hostResources, setHostResources] = useState<HostResourceSnapshot | null>(null);
  const monitorRequestEpochRef = useRef(0);

  const fetchMonitoringOverview = useCallback(async (forceRefresh = false, signal?: AbortSignal) => {
    const reqEpoch = monitorRequestEpochRef.current;
    try {
      const suffix = forceRefresh ? '?force_refresh=1' : '';
      const resp = await fetch(`/api/monitoring/overview${suffix}`, { signal });
      if (!resp.ok) return;
      const payload = await resp.json();
      if (reqEpoch !== monitorRequestEpochRef.current) return;
      setMonitorOverview(payload);
    } catch (error) {
      if (isAbortError(error)) return;
    }
  }, []);

  const fetchHostResources = useCallback(async (signal?: AbortSignal) => {
    try {
      const resp = await fetch('/api/health/resources', { signal });
      if (!resp.ok) return;
      const payload = await resp.json() as HostResourceSnapshot;
      setHostResources(payload);
    } catch (error) {
      if (isAbortError(error)) return;
    }
  }, []);

  const fetchMonitoringAlerts = useCallback(async (signal?: AbortSignal) => {
    const reqEpoch = monitorRequestEpochRef.current;
    try {
      const params = new URLSearchParams({
        page: String(monitorAlertsPage),
        page_size: String(monitorAlertsPageSize),
        severity: monitorAlertsSeverity,
        phase: monitorAlertsPhase,
      });
      if (monitorSelectedDevice?.id) params.set('device_id', monitorSelectedDevice.id);
      const resp = await fetch(`/api/monitoring/alerts?${params.toString()}`, { signal });
      if (!resp.ok) return;
      const data = await resp.json();
      if (reqEpoch !== monitorRequestEpochRef.current) return;
      setMonitorAlerts(Array.isArray(data.items) ? data.items : []);
      setMonitorAlertTotal(typeof data.total === 'number' ? data.total : 0);
    } catch (error) {
      if (isAbortError(error)) return;
    }
  }, [monitorAlertsPage, monitorAlertsPageSize, monitorAlertsSeverity, monitorAlertsPhase, monitorSelectedDevice?.id]);

  const fetchMonitoringRealtime = useCallback(async (deviceId: string, signal?: AbortSignal) => {
    const reqEpoch = monitorRequestEpochRef.current;
    const resp = await fetch(`/api/monitoring/device/${deviceId}/realtime?window_minutes=15&limit=1000`, { signal });
    if (!resp.ok) throw new Error('realtime fetch failed');
    const payload = await resp.json();
    if (reqEpoch !== monitorRequestEpochRef.current) throw new Error('stale monitoring realtime response');
    return payload;
  }, []);

  const fetchMonitoringTrend = useCallback(async (
    deviceId: string,
    interfaceName?: string,
    resolution: '1m' | '5m' = '1m',
    range?: { start_time?: string; end_time?: string },
    signal?: AbortSignal,
  ) => {
    const reqEpoch = monitorRequestEpochRef.current;
    const params = new URLSearchParams({ range_hours: '24', resolution });
    const name = (interfaceName || '').trim();
    if (name) params.set('interface_name', name);
    if (range?.start_time) params.set('start_time', range.start_time);
    if (range?.end_time) params.set('end_time', range.end_time);
    const resp = await fetch(`/api/monitoring/device/${deviceId}/trend?${params.toString()}`, { signal });
    if (!resp.ok) throw new Error('trend fetch failed');
    const payload = await resp.json();
    if (reqEpoch !== monitorRequestEpochRef.current) throw new Error('stale monitoring trend response');
    return payload;
  }, []);

  // Reset monitoring state when leaving monitoring tab
  useEffect(() => {
    monitorRequestEpochRef.current += 1;
    if (activeTab === 'monitoring' || activeTab === 'health') return;
    setMonitorSearch('');
    setMonitorSearchResults([]);
    setMonitorSearching(false);
    setMonitorSelectedDevice(null);
    setMonitorOverview(null);
    setMonitorRealtime(null);
    setMonitorTrend(null);
    setMonitorTrendInterface('');
    setMonitorTrendResolution('1m');
    setMonitorTrendStartInput('');
    setMonitorTrendEndInput('');
    setMonitorTrendRange({});
    setMonitorTrendZoom(null);
    setMonitorTrendDragStart(null);
    setMonitorTrendDragEnd(null);
    setMonitorTrendMetrics(['in_bps', 'out_bps']);
    setMonitorAlerts([]);
    setMonitorAlertTotal(0);
    setMonitorAlertsPage(1);
    setMonitorAlertsSeverity('all');
    setMonitorAlertsPhase('all');
    setMonitorLoading(false);
    setMonitorDashboardSiteFilter('all');
    setMonitorDashboardAlertFilter('all');
  }, [activeTab]);

  // Page visibility
  useEffect(() => {
    const handleVisibilityChange = () => {
      setMonitorPageVisible(document.visibilityState === 'visible');
    };
    handleVisibilityChange();
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, []);

  // Host resources polling
  useEffect(() => {
    if (!isAuthenticated) return;
    let currentController: AbortController | null = null;
    const runResources = () => {
      if (currentController) currentController.abort();
      currentController = new AbortController();
      fetchHostResources(currentController.signal);
    };
    runResources();
    if (!monitorPageVisible) return;
    const timer = window.setInterval(runResources, 30000);
    return () => {
      window.clearInterval(timer);
      if (currentController) currentController.abort();
    };
  }, [isAuthenticated, fetchHostResources, monitorPageVisible]);

  // Overview polling
  useEffect(() => {
    if (!isAuthenticated || !['monitoring', 'health'].includes(activeTab)) return;
    let currentController: AbortController | null = null;
    const runOverview = (forceRefresh = false) => {
      if (currentController) currentController.abort();
      currentController = new AbortController();
      fetchMonitoringOverview(forceRefresh, currentController.signal);
    };
    runOverview(true);
    if (!monitorPageVisible) return;
    const timer = window.setInterval(() => runOverview(false), 5000);
    return () => {
      window.clearInterval(timer);
      if (currentController) currentController.abort();
    };
  }, [isAuthenticated, activeTab, fetchMonitoringOverview, monitorPageVisible]);

  // Alerts polling
  useEffect(() => {
    if (!isAuthenticated || activeTab !== 'monitoring') return;
    let currentController: AbortController | null = null;
    const runAlerts = () => {
      if (currentController) currentController.abort();
      currentController = new AbortController();
      fetchMonitoringAlerts(currentController.signal);
    };
    runAlerts();
    if (!monitorPageVisible) return;
    const timer = window.setInterval(runAlerts, 10000);
    return () => {
      window.clearInterval(timer);
      if (currentController) currentController.abort();
    };
  }, [isAuthenticated, activeTab, fetchMonitoringAlerts, monitorPageVisible]);

  // Reset alerts page on filter change
  useEffect(() => {
    setMonitorAlertsPage(1);
  }, [monitorAlertsSeverity, monitorAlertsPhase, monitorSelectedDevice?.id]);

  // Search devices
  useEffect(() => {
    if (!isAuthenticated || activeTab !== 'monitoring') return;
    const q = monitorSearch.trim();
    if (!q) {
      setMonitorSearchResults([]);
      setMonitorSearching(false);
      return;
    }
    let cancelled = false;
    let searchController: AbortController | null = null;
    setMonitorSearching(true);
    const timer = window.setTimeout(async () => {
      try {
        searchController = new AbortController();
        const resp = await fetch(`/api/monitoring/search-devices?q=${encodeURIComponent(q)}&limit=20`, { signal: searchController.signal });
        if (!resp.ok) return;
        const data = await resp.json();
        if (!cancelled) {
          setMonitorSearchResults(Array.isArray(data.items) ? data.items : []);
        }
      } catch (error) {
        if (isAbortError(error)) return;
        if (!cancelled) setMonitorSearchResults([]);
      } finally {
        if (!cancelled) setMonitorSearching(false);
      }
    }, 350);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      if (searchController) searchController.abort();
    };
  }, [isAuthenticated, activeTab, monitorSearch]);

  // Realtime + trend data loading
  useEffect(() => {
    if (!isAuthenticated || activeTab !== 'monitoring' || !monitorSelectedDevice?.id) {
      setMonitorRealtime(null);
      setMonitorTrend(null);
      return;
    }
    let cancelled = false;
    let realtimeController: AbortController | null = null;
    let trendController: AbortController | null = null;

    const loadRealtime = async () => {
      if (realtimeController) realtimeController.abort();
      realtimeController = new AbortController();
      return fetchMonitoringRealtime(monitorSelectedDevice.id, realtimeController.signal);
    };
    const loadTrend = async () => {
      if (trendController) trendController.abort();
      trendController = new AbortController();
      return fetchMonitoringTrend(monitorSelectedDevice.id, monitorTrendInterface, monitorTrendResolution, monitorTrendRange, trendController.signal);
    };
    const load = async () => {
      setMonitorLoading(true);
      try {
        const [rt, tr] = await Promise.all([loadRealtime(), loadTrend()]);
        if (!cancelled) { setMonitorRealtime(rt); setMonitorTrend(tr); }
      } catch (error) {
        if (isAbortError(error)) return;
        if (!cancelled) { setMonitorRealtime(null); setMonitorTrend(null); }
      } finally {
        if (!cancelled) setMonitorLoading(false);
      }
    };
    load();
    if (!monitorPageVisible) {
      return () => { cancelled = true; if (realtimeController) realtimeController.abort(); if (trendController) trendController.abort(); };
    }
    const realtimeTimer = window.setInterval(async () => {
      try { const rt = await loadRealtime(); if (!cancelled) setMonitorRealtime(rt); } catch (error) { if (isAbortError(error)) return; }
    }, 5000);
    const trendTimer = window.setInterval(async () => {
      try { const tr = await loadTrend(); if (!cancelled) setMonitorTrend(tr); } catch (error) { if (isAbortError(error)) return; }
    }, 60000);
    return () => {
      cancelled = true;
      window.clearInterval(realtimeTimer);
      window.clearInterval(trendTimer);
      if (realtimeController) realtimeController.abort();
      if (trendController) trendController.abort();
    };
  }, [isAuthenticated, activeTab, monitorSelectedDevice?.id, monitorTrendInterface, monitorTrendResolution, monitorTrendRange.start_time, monitorTrendRange.end_time, fetchMonitoringRealtime, fetchMonitoringTrend, monitorPageVisible]);

  // Reset trend state on device change
  useEffect(() => {
    setMonitorTrendInterface('');
    setMonitorTrendStartInput('');
    setMonitorTrendEndInput('');
    setMonitorTrendRange({});
  }, [monitorSelectedDevice?.id]);

  useEffect(() => {
    setMonitorTrendZoom(null);
    setMonitorTrendDragStart(null);
    setMonitorTrendDragEnd(null);
  }, [monitorSelectedDevice?.id, monitorTrendInterface, monitorTrendResolution]);

  useEffect(() => {
    localStorage.setItem('netops_monitor_trend_ui_mode', monitorTrendUiMode);
  }, [monitorTrendUiMode]);

  return {
    monitorSearch, setMonitorSearch,
    monitorSearchResults, monitorSearching,
    monitorSelectedDevice, setMonitorSelectedDevice,
    monitorOverview,
    monitorRealtime, setMonitorRealtime,
    monitorTrend,
    monitorTrendInterface, setMonitorTrendInterface,
    monitorTrendResolution, setMonitorTrendResolution,
    monitorTrendStartInput, setMonitorTrendStartInput,
    monitorTrendEndInput, setMonitorTrendEndInput,
    monitorTrendRange, setMonitorTrendRange,
    monitorTrendZoom, setMonitorTrendZoom,
    monitorTrendDragStart, setMonitorTrendDragStart,
    monitorTrendDragEnd, setMonitorTrendDragEnd,
    monitorTrendMetrics, setMonitorTrendMetrics,
    monitorTrendUiMode, setMonitorTrendUiMode,
    monitorAlerts,
    monitorAlertTotal,
    monitorAlertsPage, setMonitorAlertsPage,
    monitorAlertsPageSize,
    monitorAlertsSeverity, setMonitorAlertsSeverity,
    monitorAlertsPhase, setMonitorAlertsPhase,
    monitorLoading,
    monitorPageVisible,
    monitorDashboardSiteFilter, setMonitorDashboardSiteFilter,
    monitorDashboardAlertFilter, setMonitorDashboardAlertFilter,
    hostResources,
    fetchMonitoringOverview,
    fetchMonitoringAlerts,
    fetchMonitoringRealtime,
    fetchHostResources,
  };
};
