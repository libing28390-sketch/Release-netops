import { useCallback, useEffect, useRef } from 'react';
import { useMonitoringStore } from '../store/monitoringStore';
import { authHeaders } from '../api/http';
import type { OutboundTarget } from '../types/outbound';
import type { DeviceHealthHistoryResponse, MonitoringHealthDevicesResponse, MonitoringIncident, MonitoringIncidentImpact, MonitoringIncidentListResponse, MonitoringPlaybookRecommendationsResponse } from '../types';

interface UseMonitoringProps {
  isAuthenticated: boolean;
  activeTab: string;
  language: string;
  pollOutbound?: boolean;
  healthHistoryRange?: number;
}

const isAbortError = (error: unknown) => {
  if (!error) return false;
  if (error instanceof DOMException && error.name === 'AbortError') return true;
  return typeof error === 'object' && (error as { name?: string }).name === 'AbortError';
};

export const useMonitoring = ({ isAuthenticated, activeTab, pollOutbound = true, healthHistoryRange = 24 }: UseMonitoringProps) => {
  const {
    monitorSearch,
    monitorSearchResults,
    monitorSearching,
    monitorSelectedDevice,
    monitorOverview,
    monitorHealthHistory,
    monitorRealtime,
    monitorTrend,
    monitorTrendInterface,
    monitorTrendResolution,
    monitorTrendStartInput,
    monitorTrendEndInput,
    monitorTrendRange,
    monitorTrendZoom,
    monitorTrendDragStart,
    monitorTrendDragEnd,
    monitorTrendMetrics,
    monitorTrendUiMode,
    monitorAlerts,
    monitorAlertTotal,
    monitorAlertsPage,
    monitorAlertsPageSize,
    monitorAlertsSeverity,
    monitorAlertsPhase,
    monitorIncidents,
    monitorIncidentTotal,
    monitorLoading,
    monitorPageVisible,
    monitorDashboardSiteFilter,
    monitorDashboardAlertFilter,
    hostResources,
    outboundHealth,
    outboundLoading,
    outboundModalOpen,
    outboundTargetHistory,
    outboundTargetHistoryLoading,
    outboundHistoryHours,
    setMonitorSearch,
    setMonitorSearchResults,
    setMonitorSearching,
    setMonitorSelectedDevice,
    setMonitorOverview,
    setMonitorHealthHistory,
    setMonitorRealtime,
    setMonitorTrend,
    setMonitorTrendInterface,
    setMonitorTrendResolution,
    setMonitorTrendStartInput,
    setMonitorTrendEndInput,
    setMonitorTrendRange,
    setMonitorTrendZoom,
    setMonitorTrendDragStart,
    setMonitorTrendDragEnd,
    setMonitorTrendMetrics,
    setMonitorTrendUiMode,
    setMonitorAlerts,
    setMonitorAlertTotal,
    setMonitorAlertsPage,
    setMonitorAlertsSeverity,
    setMonitorAlertsPhase,
    setMonitorIncidents,
    setMonitorIncidentTotal,
    setMonitorLoading,
    setMonitorPageVisible,
    setMonitorDashboardSiteFilter,
    setMonitorDashboardAlertFilter,
    setHostResources,
    setOutboundHealth,
    setOutboundLoading,
    setOutboundModalOpen,
    setOutboundTargetHistory,
    setOutboundTargetHistoryLoading,
    setOutboundHistoryHours,
    resetMonitoringState,
  } = useMonitoringStore();

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
  }, [setMonitorOverview]);

  const fetchHostResources = useCallback(async (signal?: AbortSignal) => {
    try {
      const resp = await fetch('/api/health/resources', { signal });
      if (!resp.ok) return;
      const payload = await resp.json();
      setHostResources(payload);
    } catch (error) {
      if (isAbortError(error)) return;
    }
  }, [setHostResources]);

  const fetchMonitoringHealthHistory = useCallback(async (rangeHours = 24, signal?: AbortSignal) => {
    try {
      const resp = await fetch(`/api/device-health/history?range_hours=${rangeHours}`, { signal, headers: authHeaders() });
      if (!resp.ok) return null;
      const payload = await resp.json() as DeviceHealthHistoryResponse;
      setMonitorHealthHistory(payload);
      return payload;
    } catch (error) {
      if (isAbortError(error)) return null;
      return null;
    }
  }, [setMonitorHealthHistory]);

  const fetchMonitoringCollectionStatus = useCallback(async (signal?: AbortSignal) => {
    const token = localStorage.getItem('netops_token');
    const resp = await fetch('/api/monitoring/collection-status', { signal, headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!resp.ok) throw new Error('Unable to load collection status');
    return await resp.json() as { items: any[]; summary?: Record<string, unknown> };
  }, []);

  const outboundHeaders = useCallback(() => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, []);

  const fetchMonitoringHealthDevices = useCallback(async (filters: {
    health_status?: string;
    availability_status?: string;
    collection_status?: string;
    site?: string;
    role?: string;
    severity?: string;
    problem_type?: string;
  } = {}, signal?: AbortSignal) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) {
      if (value && value !== 'all') params.set(key, value);
    }
    params.set('limit', '200');
    const resp = await fetch(`/api/monitoring/health-devices?${params.toString()}`, { signal, headers: outboundHeaders() });
    const payload = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const detail = payload?.detail?.message || payload?.detail;
      throw new Error(detail ? String(detail) : 'Unable to load health drilldown');
    }
    return payload as MonitoringHealthDevicesResponse;
  }, [outboundHeaders]);

  const fetchMonitoringIncidentPlaybookRecommendations = useCallback(async (incidentId: string, signal?: AbortSignal) => {
    if (!incidentId) return null;
    const resp = await fetch(`/api/monitoring/incidents/${encodeURIComponent(incidentId)}/playbook-recommendations`, {
      signal,
      headers: outboundHeaders(),
    });
    if (!resp.ok) return null;
    return await resp.json() as MonitoringPlaybookRecommendationsResponse;
  }, [outboundHeaders]);

  const runMonitoringIncidentPlaybook = useCallback(async (incidentId: string, scenarioId: string, variables: Record<string, unknown> = {}) => {
    const resp = await fetch(`/api/monitoring/incidents/${encodeURIComponent(incidentId)}/playbooks/execute`, {
      method: 'POST',
      headers: { ...outboundHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenario_id: scenarioId, variables }),
    });
    const payload = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const detail = payload?.detail?.message || payload?.detail || 'Unable to start incident Playbook';
      throw new Error(String(detail));
    }
    return payload as { execution_id?: string; status?: string; scenario_id?: string; platform?: string; read_only?: boolean };
  }, [outboundHeaders]);

  const fetchOutboundHealth = useCallback(async (signal?: AbortSignal, historyHours?: number) => {
    const range = historyHours ?? useMonitoringStore.getState().outboundHistoryHours;
    try {
      const resp = await fetch(`/api/monitoring/outbound-status?history_hours=${range}`, {
        signal,
        headers: outboundHeaders(),
      });
      if (!resp.ok) return null;
      const payload = await resp.json();
      setOutboundHealth(payload);
      return payload;
    } catch (error) {
      if (isAbortError(error)) return null;
      return null;
    }
  }, [outboundHeaders, setOutboundHealth]);

  const triggerOutboundProbe = useCallback(async () => {
    setOutboundLoading(true);
    try {
      const resp = await fetch('/api/monitoring/outbound-trigger', {
        method: 'POST',
        headers: { ...outboundHeaders(), 'Content-Type': 'application/json' },
      });
      const payload = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        const detail = payload?.detail?.message || payload?.detail || 'Outbound probe failed';
        throw new Error(String(detail));
      }
      await fetchOutboundHealth();
      return payload;
    } finally {
      setOutboundLoading(false);
    }
  }, [fetchOutboundHealth, outboundHeaders, setOutboundLoading]);

  const saveOutboundTarget = useCallback(async (target: Partial<OutboundTarget>) => {
    const method = target.id ? 'PATCH' : 'POST';
    const path = target.id ? `/api/monitoring/outbound-targets/${encodeURIComponent(target.id)}` : '/api/monitoring/outbound-targets';
    const resp = await fetch(path, {
      method,
      headers: { ...outboundHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify(target),
    });
    const payload = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(String(payload?.detail?.message || payload?.detail || 'Unable to save target'));
    }
    await fetchOutboundHealth();
    return payload;
  }, [fetchOutboundHealth, outboundHeaders]);

  const deleteOutboundTarget = useCallback(async (targetId: string) => {
    const resp = await fetch(`/api/monitoring/outbound-targets/${encodeURIComponent(targetId)}`, {
      method: 'DELETE',
      headers: outboundHeaders(),
    });
    const payload = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(String(payload?.detail?.message || payload?.detail || 'Unable to delete target'));
    await fetchOutboundHealth();
  }, [fetchOutboundHealth, outboundHeaders]);

  const fetchOutboundTargetHistory = useCallback(async (
    targetId: string,
    signal?: AbortSignal,
    historyHours?: number,
    startTime?: string,
    endTime?: string
  ) => {
    if (!targetId) return null;
    setOutboundTargetHistoryLoading(true);
    try {
      let url = `/api/monitoring/outbound-targets/${encodeURIComponent(targetId)}/history`;
      if (startTime && endTime) {
        url += `?start_time=${encodeURIComponent(startTime)}&end_time=${encodeURIComponent(endTime)}`;
      } else {
        const range = historyHours ?? useMonitoringStore.getState().outboundHistoryHours;
        url += `?history_hours=${range}`;
      }
      const resp = await fetch(url, {
        signal,
        headers: outboundHeaders(),
      });
      if (!resp.ok) return null;
      const payload = await resp.json();
      setOutboundTargetHistory(payload);
      return payload;
    } catch (error) {
      if (isAbortError(error)) return null;
      return null;
    } finally {
      setOutboundTargetHistoryLoading(false);
    }
  }, [outboundHeaders, setOutboundTargetHistory, setOutboundTargetHistoryLoading]);

  const fetchMonitoringAlerts = useCallback(async (signal?: AbortSignal) => {
    const reqEpoch = monitorRequestEpochRef.current;
    // Read latest values directly from store to avoid stale closure
    const state = useMonitoringStore.getState();
    try {
      const params = new URLSearchParams({
        page: String(state.monitorAlertsPage),
        page_size: String(state.monitorAlertsPageSize),
        severity: state.monitorAlertsSeverity,
        phase: state.monitorAlertsPhase,
      });
      if (state.monitorSelectedDevice?.id) params.set('device_id', state.monitorSelectedDevice.id);
      const resp = await fetch(`/api/monitoring/alerts?${params.toString()}`, { signal, headers: outboundHeaders() });
      if (!resp.ok) return;
      const data = await resp.json();
      if (reqEpoch !== monitorRequestEpochRef.current) return;
      setMonitorAlerts(Array.isArray(data.items) ? data.items : []);
      setMonitorAlertTotal(typeof data.total === 'number' ? data.total : 0);
    } catch (error) {
      if (isAbortError(error)) return;
    }
  }, [outboundHeaders, setMonitorAlerts, setMonitorAlertTotal]);

  const fetchMonitoringIncidents = useCallback(async (signal?: AbortSignal) => {
    const reqEpoch = monitorRequestEpochRef.current;
    try {
      const params = new URLSearchParams({ status: 'active', page: '1', page_size: '8' });
      const resp = await fetch(`/api/monitoring/incidents?${params.toString()}`, {
        signal,
        headers: outboundHeaders(),
      });
      if (!resp.ok) return;
      const data = await resp.json() as MonitoringIncidentListResponse;
      if (reqEpoch !== monitorRequestEpochRef.current) return;
      setMonitorIncidents(Array.isArray(data.items) ? data.items : []);
      setMonitorIncidentTotal(typeof data.total === 'number' ? data.total : 0);
    } catch (error) {
      if (isAbortError(error)) return;
    }
  }, [outboundHeaders, setMonitorIncidentTotal, setMonitorIncidents]);

  const fetchMonitoringIncidentDetail = useCallback(async (incidentId: string, signal?: AbortSignal) => {
    if (!incidentId) return null;
    const resp = await fetch(`/api/monitoring/incidents/${encodeURIComponent(incidentId)}`, {
      signal,
      headers: outboundHeaders(),
    });
    if (!resp.ok) return null;
    const payload = await resp.json() as { item?: MonitoringIncident };
    return payload.item || null;
  }, [outboundHeaders]);

  const fetchMonitoringIncidentImpact = useCallback(async (incidentId: string, signal?: AbortSignal) => {
    if (!incidentId) return null;
    const resp = await fetch(`/api/monitoring/incidents/${encodeURIComponent(incidentId)}/impact`, {
      signal,
      headers: outboundHeaders(),
    });
    if (!resp.ok) return null;
    return await resp.json() as MonitoringIncidentImpact;
  }, [outboundHeaders]);

  const runMonitoringDeviceDiagnostics = useCallback(async (deviceId: string, incidentId?: string) => {
    if (!deviceId) return null;
    const query = incidentId ? `?incident_id=${encodeURIComponent(incidentId)}` : '';
    const resp = await fetch(`/api/monitoring/device/${encodeURIComponent(deviceId)}/diagnostics${query}`, {
      method: 'POST',
      headers: { ...outboundHeaders(), 'Content-Type': 'application/json' },
    });
    const payload = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const detail = payload?.detail?.message || payload?.detail || 'Unable to diagnose collection';
      throw new Error(String(detail));
    }
    return payload;
  }, [outboundHeaders]);

  const updateMonitoringIncident = useCallback(async (
    incidentId: string,
    action: 'acknowledge' | 'assign' | 'resolve',
    body: Record<string, string>,
  ) => {
    const resp = await fetch(`/api/monitoring/incidents/${encodeURIComponent(incidentId)}/${action}`, {
      method: 'POST',
      headers: { ...outboundHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const payload = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const detail = payload?.detail?.message || payload?.detail || 'Unable to update incident';
      throw new Error(String(detail));
    }
    await fetchMonitoringIncidents();
    return payload.item as MonitoringIncident | undefined;
  }, [fetchMonitoringIncidents, outboundHeaders]);

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
    if (activeTab === 'monitoring' || activeTab === 'outbound-monitoring' || activeTab === 'health') return;
    resetMonitoringState();
  }, [activeTab, resetMonitoringState]);

  // Page visibility
  useEffect(() => {
    const handleVisibilityChange = () => {
      setMonitorPageVisible(document.visibilityState === 'visible');
    };
    handleVisibilityChange();
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, [setMonitorPageVisible]);

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

  // Fleet health history powers the NOC trend view. Keep this separate from
  // host-resource telemetry so a missing device sample is not presented as a
  // healthy zero.
  useEffect(() => {
    if (!isAuthenticated || activeTab !== 'monitoring') return;
    let controller: AbortController | null = null;
    const run = () => {
      if (controller) controller.abort();
      controller = new AbortController();
      fetchMonitoringHealthHistory(healthHistoryRange, controller.signal);
    };
    run();
    if (!monitorPageVisible) return () => { if (controller) controller.abort(); };
    const timer = window.setInterval(run, 30000);
    return () => {
      window.clearInterval(timer);
      if (controller) controller.abort();
    };
  }, [activeTab, fetchMonitoringHealthHistory, healthHistoryRange, isAuthenticated, monitorPageVisible]);

  // Outbound health is sampled by the backend every minute. Polling the latest
  // aggregate more slowly keeps the dashboard responsive without duplicating
  // probe traffic from the browser.
  useEffect(() => {
    if (!isAuthenticated || !pollOutbound || !['monitoring', 'outbound-monitoring'].includes(activeTab)) return;
    let controller: AbortController | null = null;
    const run = () => {
      if (controller) controller.abort();
      controller = new AbortController();
      fetchOutboundHealth(controller.signal, useMonitoringStore.getState().outboundHistoryHours);
    };
    run();
    if (!monitorPageVisible) return () => { if (controller) controller.abort(); };
    const timer = window.setInterval(run, 30000);
    return () => {
      window.clearInterval(timer);
      if (controller) controller.abort();
    };
  }, [activeTab, fetchOutboundHealth, isAuthenticated, monitorPageVisible, outboundHistoryHours, pollOutbound]);

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

  // Incident projection polling. Incidents are a compact read model over the
  // alert timeline, so poll them with the same cadence as the dashboard feed.
  useEffect(() => {
    if (!isAuthenticated || activeTab !== 'monitoring') return;
    let currentController: AbortController | null = null;
    const runIncidents = () => {
      if (currentController) currentController.abort();
      currentController = new AbortController();
      fetchMonitoringIncidents(currentController.signal);
    };
    runIncidents();
    if (!monitorPageVisible) return;
    const timer = window.setInterval(runIncidents, 10000);
    return () => {
      window.clearInterval(timer);
      if (currentController) currentController.abort();
    };
  }, [isAuthenticated, activeTab, fetchMonitoringIncidents, monitorPageVisible]);

  // Reset alerts page on filter change
  useEffect(() => {
    setMonitorAlertsPage(1);
  }, [monitorAlertsSeverity, monitorAlertsPhase, monitorSelectedDevice?.id, setMonitorAlertsPage]);

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
  }, [isAuthenticated, activeTab, monitorSearch, setMonitorSearchResults, setMonitorSearching]);

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
  }, [
    isAuthenticated, activeTab, monitorSelectedDevice?.id,
    monitorTrendInterface, monitorTrendResolution,
    monitorTrendRange.start_time, monitorTrendRange.end_time,
    fetchMonitoringRealtime, fetchMonitoringTrend, monitorPageVisible,
    setMonitorRealtime, setMonitorTrend, setMonitorLoading,
  ]);

  // Reset trend state on device change
  useEffect(() => {
    setMonitorTrendInterface('');
    setMonitorTrendStartInput('');
    setMonitorTrendEndInput('');
    setMonitorTrendRange({});
  }, [monitorSelectedDevice?.id, setMonitorTrendInterface, setMonitorTrendStartInput, setMonitorTrendEndInput, setMonitorTrendRange]);

  useEffect(() => {
    setMonitorTrendZoom(null);
    setMonitorTrendDragStart(null);
    setMonitorTrendDragEnd(null);
  }, [monitorSelectedDevice?.id, monitorTrendInterface, monitorTrendResolution, setMonitorTrendZoom, setMonitorTrendDragStart, setMonitorTrendDragEnd]);

  return {
    monitorSearch, setMonitorSearch,
    monitorSearchResults, monitorSearching,
    monitorSelectedDevice, setMonitorSelectedDevice,
    monitorOverview,
    monitorHealthHistory,
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
    monitorIncidents,
    monitorIncidentTotal,
    monitorLoading,
    monitorPageVisible,
    monitorDashboardSiteFilter, setMonitorDashboardSiteFilter,
    monitorDashboardAlertFilter, setMonitorDashboardAlertFilter,
    hostResources,
    outboundHealth,
    outboundLoading,
    outboundModalOpen,
    setOutboundModalOpen,
    outboundTargetHistory,
    outboundTargetHistoryLoading,
    outboundHistoryHours,
    setOutboundHistoryHours,
    fetchMonitoringOverview,
    fetchMonitoringHealthHistory,
    fetchMonitoringCollectionStatus,
    fetchMonitoringHealthDevices,
    fetchMonitoringAlerts,
    fetchMonitoringIncidents,
    fetchMonitoringIncidentDetail,
    fetchMonitoringIncidentImpact,
    fetchMonitoringIncidentPlaybookRecommendations,
    runMonitoringIncidentPlaybook,
    runMonitoringDeviceDiagnostics,
    updateMonitoringIncident,
    fetchMonitoringRealtime,
    fetchHostResources,
    fetchOutboundHealth,
    triggerOutboundProbe,
    saveOutboundTarget,
    deleteOutboundTarget,
    fetchOutboundTargetHistory,
  };
};
