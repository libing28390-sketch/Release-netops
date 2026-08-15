import React, { useState, useCallback, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Search, ChevronLeft, ChevronRight, RefreshCw,
  AlertTriangle, CheckCircle2, Database, HeartPulse,
  Zap, Bell, Clock, ArrowUpRight, Eye, Activity,
  Radio, Play, ChevronDown, ChevronUp,
  Terminal, Download, Wrench, Map as MapIcon, Globe, Layers, BarChart3,
} from 'lucide-react';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, Brush } from 'recharts';
import type { Device, HostResourceSnapshot, HostResourceHistoryPayload, MonitoringHealthDevice, MonitoringIncident, MonitoringIncidentImpact, MonitoringPlaybookRecommendationsResponse } from '../types';
import DateTimePicker from './DateTimePicker';
import PageHero from './PageHero';
import { useChartTheme } from '../hooks/useChartTheme';
import { useMonitoringStore } from '../store/monitoringStore';
import { useMonitoring } from '../hooks/useMonitoring';
import { useSystem } from '../hooks/useSystem';

type MonitorDevice = {
  id?: string;
  device_id?: string;
  hostname?: string;
  ip_address?: string;
  platform?: string;
  role?: string;
  site?: string;
};

interface MonitoringCenterProps {
  language: 'zh' | 'en';
  devices: Device[];
  showToast: (message: string, type?: string) => void;
  isAuthenticated?: boolean;
}

/* ─── sub-components ─── */

const StatusCard: React.FC<{
  label: string; value: string | number; sub?: string;
  tone?: 'default' | 'green' | 'red' | 'amber' | 'blue';
  pulse?: boolean; onClick?: () => void; icon?: React.ReactNode;
}> = ({ label, value, sub, tone = 'default', pulse, onClick, icon }) => {
  const toneMap: Record<string, string> = {
    default: 'border-[var(--card-border)]',
    green: 'border-emerald-400/40',
    red: 'border-red-400/50',
    amber: 'border-amber-400/40',
    blue: 'border-sky-400/40',
  };
  const valueTone: Record<string, string> = {
    default: 'text-[var(--app-text)]', green: 'text-emerald-600',
    red: 'text-red-600', amber: 'text-amber-600', blue: 'text-sky-600',
  };
  const accentTone: Record<string, string> = {
    default: '#94a3b8', green: '#10b981', red: '#ef4444', amber: '#f59e0b', blue: '#0ea5e9',
  };
  const fillTone: Record<string, string> = {
    default: 'color-mix(in srgb, var(--card-bg) 94%, #94a3b8 6%)',
    green: 'color-mix(in srgb, var(--card-bg) 92%, #10b981 8%)',
    red: 'color-mix(in srgb, var(--card-bg) 91%, #ef4444 9%)',
    amber: 'color-mix(in srgb, var(--card-bg) 92%, #f59e0b 8%)',
    blue: 'color-mix(in srgb, var(--card-bg) 92%, #0ea5e9 8%)',
  };
  return (
    <button type="button" onClick={onClick} disabled={!onClick}
      style={{ borderLeftColor: accentTone[tone], backgroundColor: fillTone[tone] }}
      className={`ops-surface relative overflow-hidden rounded-2xl border-l-4 border-y border-r p-5 text-left transition-all ${toneMap[tone]} ${onClick ? 'cursor-pointer hover:-translate-y-0.5 hover:shadow-lg active:translate-y-0' : 'cursor-default'}`}>
      {pulse && <span className="absolute top-3 right-3 flex h-2.5 w-2.5"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-400 opacity-60" /><span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-red-500" /></span>}
      <div className="flex items-center gap-2">
        {icon && <span className="text-[var(--muted-text)]">{icon}</span>}
        <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-[var(--muted-text)]">{label}</p>
      </div>
      <p className={`mt-2 text-[2.35rem] leading-none font-extrabold tracking-tight ${valueTone[tone]}`}>{value}</p>
      {sub && <p className="mt-1 text-[11px] text-[var(--muted-text)]">{sub}</p>}
    </button>
  );
};

const HealthSegment: React.FC<{
  label: string; count: number; total: number; color: string; onClick?: () => void;
}> = ({ label, count, total, color, onClick }) => {
  const pct = total > 0 ? (count / total) * 100 : 0;
  const className = `group flex items-center gap-3 rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)] px-4 py-3 transition-all ${onClick ? 'cursor-pointer hover:border-black/20 hover:shadow-sm' : 'cursor-default'}`;
  const details = (
    <>
      <span className="h-8 w-1.5 rounded-full" style={{ backgroundColor: color }} />
      <div className="min-w-0 flex-1">
        <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-[var(--muted-text)]">{label}</p>
        <p className="mt-0.5 text-xl font-bold text-[var(--app-text)]">{count}</p>
      </div>
      <span className="text-xs font-semibold text-[var(--muted-text)]">{pct.toFixed(0)}%</span>
    </>
  );
  return onClick ? (
    <button type="button" onClick={onClick} className={className}>{details}</button>
  ) : (
    <div className={className}>{details}</div>
  );
};

const RiskDeviceRow: React.FC<{
  device: any; language: 'zh' | 'en'; onClick: () => void; index: number;
}> = ({ device, language, onClick, index }) => {
  const scoreAvailable = device.health_score_available !== false && device.health_score != null;
  const statusColor = device.health_status === 'critical' ? '#ef4444' : device.health_status === 'warning' ? '#f59e0b' : device.health_status === 'healthy' ? '#10b981' : '#94a3b8';
  const statusLabel = device.health_status === 'critical' ? (language === 'zh' ? '严重' : 'Critical') : device.health_status === 'warning' ? (language === 'zh' ? '告警' : 'Warning') : device.health_status === 'healthy' ? (language === 'zh' ? '健康' : 'Healthy') : (language === 'zh' ? '待评估' : 'Not evaluated');
  const availabilityLabel = device.availability_status === 'offline' ? (language === 'zh' ? '离线' : 'Offline') : device.availability_status === 'online' ? (language === 'zh' ? '在线' : 'Online') : (language === 'zh' ? '未知' : 'Unknown');
  const isOffline = String(device.status || '').toLowerCase() === 'offline';
  const score = scoreAvailable ? Number(device.health_score) : null;
  const scoreColor = score == null ? '#94a3b8' : score < 30 ? '#ef4444' : score < 60 ? '#f59e0b' : '#10b981';
  return (
    <button type="button" onClick={onClick} className="group w-full flex items-center gap-3 rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)] px-3 py-2.5 text-left transition-all hover:border-red-300 hover:bg-red-50/30" style={{ borderLeftWidth: 3, borderLeftColor: statusColor }}>
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-black/5 text-[10px] font-bold text-[var(--muted-text)]">{index + 1}</span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="text-sm font-semibold text-[var(--app-text)] truncate">{device.hostname || device.ip_address}</p>
          {isOffline && <span className="shrink-0 h-1.5 w-1.5 rounded-full bg-red-500" title="Offline" />}
        </div>
      <p className="text-[11px] text-[var(--muted-text)] truncate">{[device.site, device.platform, availabilityLabel].filter(Boolean).join(' · ') || device.ip_address}</p>
      <p className="mt-0.5 truncate text-[10px] text-[var(--muted-text)]">{device.health_summary || (language === 'zh' ? '\u6682\u65e0\u5065\u5eb7\u539f\u56e0' : 'No health finding')} · {device.open_alert_count || 0} {language === 'zh' ? '\u6761\u6d3b\u8dc3\u544a\u8b66' : 'open alerts'}</p>
      </div>
      <div className="shrink-0 flex items-center gap-2.5">
        <span className="inline-flex rounded-full px-2 py-0.5 text-[10px] font-bold" style={{ backgroundColor: `${statusColor}18`, color: statusColor }}>{statusLabel}</span>
        <span className="text-lg font-extrabold tabular-nums" style={{ color: scoreColor }}>{score == null ? '--' : score}</span>
      </div>
      <ArrowUpRight size={14} className="shrink-0 text-[var(--muted-text)] opacity-0 transition-opacity group-hover:opacity-100" />
    </button>
  );
};

const EventStreamItem: React.FC<{
  alert: any; language: 'zh' | 'en'; onClick: () => void;
  formatTs: (v?: string, withSec?: boolean) => string;
}> = ({ alert, language, onClick, formatTs: fmtTs }) => {
  const sev = String(alert.severity || '').toLowerCase();
  const sevColor = sev === 'critical' ? '#ef4444' : sev === 'major' ? '#f97316' : '#eab308';
  const sevLabel = sev === 'critical' ? (language === 'zh' ? '\u4e25' : 'C') : sev === 'major' ? (language === 'zh' ? '\u4e3b' : 'M') : (language === 'zh' ? '\u6b21' : 'W');
  return (
    <button type="button" onClick={onClick} className="group w-full flex items-start gap-2.5 rounded-lg border border-transparent px-2.5 py-2 text-left transition-all hover:border-[var(--card-border)] hover:bg-[var(--card-bg)]">
      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md text-[9px] font-black text-white" style={{ backgroundColor: sevColor }}>{sevLabel}</span>
      <div className="min-w-0 flex-1">
        <p className="text-xs font-semibold text-[var(--app-text)] line-clamp-1">{alert.title}</p>
        <p className="mt-0.5 text-[11px] text-[var(--muted-text)] line-clamp-1">{alert.message || (alert.hostname ? `${alert.hostname}` : '')}</p>
      </div>
      <span className="shrink-0 text-[10px] tabular-nums text-[var(--muted-text)]">{fmtTs(alert.created_at, true)}</span>
    </button>
  );
};

const MiniGauge: React.FC<{ value: number | null; label: string; max?: number }> = ({ value, label, max = 100 }) => {
  const pct = value != null && Number.isFinite(value) ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  const color = pct > 85 ? '#ef4444' : pct > 65 ? '#f59e0b' : '#10b981';
  return (
    <div className="flex flex-col items-center gap-1.5">
      <div className="relative h-14 w-14">
        <svg viewBox="0 0 36 36" className="h-full w-full -rotate-90">
          <circle cx="18" cy="18" r="15.5" fill="none" stroke="currentColor" strokeWidth="3" className="text-black/[0.06]" />
          <circle cx="18" cy="18" r="15.5" fill="none" stroke={color} strokeWidth="3" strokeLinecap="round" strokeDasharray={`${pct * 0.975} 100`} />
        </svg>
        <span className="absolute inset-0 flex items-center justify-center text-xs font-bold text-[var(--app-text)]">{value != null ? `${Math.round(value)}%` : '--'}</span>
      </div>
      <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--muted-text)]">{label}</span>
    </div>
  );
};

/* ─── pagination helper ─── */

const buildPaginationItems = (currentPage: number, totalPages: number) => {
  if (totalPages <= 7) return Array.from({ length: totalPages }, (_, index) => index + 1);
  const items: Array<number | string> = [1];
  const windowStart = Math.max(2, currentPage - 1);
  const windowEnd = Math.min(totalPages - 1, currentPage + 1);
  if (windowStart > 2) items.push('left-ellipsis');
  for (let page = windowStart; page <= windowEnd; page += 1) items.push(page);
  if (windowEnd < totalPages - 1) items.push('right-ellipsis');
  items.push(totalPages);
  return items;
};

const MonitoringPagination: React.FC<{
  language: 'zh' | 'en'; currentPage: number; totalItems: number;
  onPageChange: (page: number) => void; itemsPerPage?: number;
}> = ({ language, currentPage, totalItems, onPageChange, itemsPerPage = 10 }) => {
  const totalPages = Math.max(1, Math.ceil(totalItems / itemsPerPage));
  if (totalItems === 0) return null;
  const startItem = Math.min((currentPage - 1) * itemsPerPage + 1, totalItems);
  const endItem = Math.min(currentPage * itemsPerPage, totalItems);
  const pageItems = buildPaginationItems(currentPage, totalPages);
  return (
    <div className="flex flex-col gap-3 px-5 py-3 border-t border-[var(--card-border)] lg:flex-row lg:items-center lg:justify-between">
      <p className="text-[10px] font-bold uppercase text-[var(--muted-text)] tracking-widest">
        {language === 'zh' ? `\u7B2C ${startItem}-${endItem} \u6761 / \u5171 ${totalItems} \u6761` : `${startItem}-${endItem} / ${totalItems}`}
      </p>
      {totalPages > 1 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <button type="button" disabled={currentPage === 1} onClick={() => onPageChange(currentPage - 1)} className="inline-flex h-8 items-center gap-1 rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 text-[11px] font-semibold text-[var(--muted-text)] transition-all hover:border-black/15 disabled:opacity-25">
            <ChevronLeft size={14} />
          </button>
          {pageItems.map((item, index) => typeof item !== 'number'
            ? <span key={`${item}-${index}`} className="px-1 text-xs text-[var(--muted-text)]">\u00b7\u00b7\u00b7</span>
            : <button key={item} type="button" onClick={() => onPageChange(item)} className={`h-8 min-w-8 rounded-lg px-2.5 text-xs font-bold transition-all ${currentPage === item ? 'bg-[var(--app-text)] text-[var(--card-bg)] shadow-sm' : 'text-[var(--muted-text)] hover:bg-black/[0.04]'}`}>{item}</button>
          )}
          <button type="button" disabled={currentPage === totalPages} onClick={() => onPageChange(currentPage + 1)} className="inline-flex h-8 items-center gap-1 rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 text-[11px] font-semibold text-[var(--muted-text)] transition-all hover:border-black/15 disabled:opacity-25">
            <ChevronRight size={14} />
          </button>
        </div>
      )}
    </div>
  );
};

const MonitoringCenter: React.FC<MonitoringCenterProps> = ({ language, devices: allDevices, showToast, isAuthenticated = true }) => {
  const { systemInfo } = useSystem();
  const ct = useChartTheme();
  const navigate = useNavigate();



  const [refreshing, setRefreshing] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [hostResourceRange, setHostResourceRange] = useState<1 | 24 | 168>(24);
  const [hostResourceHistory, setHostResourceHistory] = useState<HostResourceHistoryPayload | null>(null);
  const [hostResourceHistoryLoading, setHostResourceHistoryLoading] = useState(false);
  const [nocClock, setNocClock] = useState(() => new Date());
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [impactedShowAll, setImpactedShowAll] = useState(false);
  const [selectedIncident, setSelectedIncident] = useState<MonitoringIncident | null>(null);
  const [incidentDetailLoading, setIncidentDetailLoading] = useState(false);
  const [incidentMutationLoading, setIncidentMutationLoading] = useState(false);
  const [incidentAssignee, setIncidentAssignee] = useState('');
  const [incidentImpact, setIncidentImpact] = useState<MonitoringIncidentImpact | null>(null);
  const [incidentImpactLoading, setIncidentImpactLoading] = useState(false);
  const [incidentDiagnostics, setIncidentDiagnostics] = useState<any | null>(null);
  const [incidentDiagnosticsLoading, setIncidentDiagnosticsLoading] = useState(false);
  const [incidentRecommendations, setIncidentRecommendations] = useState<MonitoringPlaybookRecommendationsResponse | null>(null);
  const [incidentRecommendationsLoading, setIncidentRecommendationsLoading] = useState(false);
  const [incidentPlaybookRunning, setIncidentPlaybookRunning] = useState<string | null>(null);
  const [collectionDrilldownOpen, setCollectionDrilldownOpen] = useState(false);
  const [collectionDrilldownLoading, setCollectionDrilldownLoading] = useState(false);
  const [collectionStatusItems, setCollectionStatusItems] = useState<any[]>([]);
  const [healthDrilldownFilter, setHealthDrilldownFilter] = useState<string | null>(null);
  const [healthDrilldownLoading, setHealthDrilldownLoading] = useState(false);
  const [healthDrilldownItems, setHealthDrilldownItems] = useState<MonitoringHealthDevice[]>([]);
  const [healthHistoryRange, setHealthHistoryRange] = useState<1 | 24 | 168>(24);
  const autoRefreshRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [hostResourceAlertView, setHostResourceAlertView] = useState<'active' | 'history'>('active');
  const advancedSectionRef = useRef<HTMLDivElement | null>(null);

  // Read all monitoring state from store
  const {
    monitorSearch,
    setMonitorSearch,
    monitorSearchResults,
    monitorSearching,
    monitorSelectedDevice,
    setMonitorSelectedDevice,
    monitorOverview,
    monitorHealthHistory,
    monitorRealtime,
    setMonitorRealtime,
    monitorTrend,
    monitorTrendInterface,
    setMonitorTrendInterface,
    monitorTrendResolution,
    setMonitorTrendResolution,
    monitorTrendStartInput,
    setMonitorTrendStartInput,
    monitorTrendEndInput,
    setMonitorTrendEndInput,
    monitorTrendRange,
    setMonitorTrendRange,
    monitorTrendZoom,
    setMonitorTrendZoom,
    monitorTrendDragStart,
    setMonitorTrendDragStart,
    monitorTrendDragEnd,
    setMonitorTrendDragEnd,
    monitorTrendMetrics,
    setMonitorTrendMetrics,
    monitorTrendUiMode,
    setMonitorTrendUiMode,
    monitorAlerts,
    monitorAlertTotal,
    monitorAlertsPage,
    setMonitorAlertsPage,
    monitorAlertsPageSize,
    monitorAlertsSeverity,
    setMonitorAlertsSeverity,
    monitorAlertsPhase,
    setMonitorAlertsPhase,
    monitorIncidents,
    monitorIncidentTotal,
    monitorLoading,
    monitorPageVisible,
    monitorDashboardSiteFilter,
    setMonitorDashboardSiteFilter,
    monitorDashboardAlertFilter,
    setMonitorDashboardAlertFilter,
    hostResources,
  } = useMonitoringStore();

  const isServerDevice = (d: any) => {
    if (!d) return false;
    const serverKeywords = ['linux', 'ubuntu', 'centos', 'debian', 'redhat', 'rocky', 'alma', 'windows', 'winrm', 'server'];
    const p = (d.platform || '').toLowerCase();
    if (serverKeywords.some((kw) => p.includes(kw))) return true;
    // Fallback: some servers are mis-tagged with a network platform (e.g. cisco_ios)
    // but carry a server-ish category / role / asset_type. Mirror the backend's
    // `'server' in category` heuristic so detection stays consistent.
    const category = (d.device_category || '').toLowerCase();
    const role = (d.role || '').toLowerCase();
    const assetType = (d.asset_type || '').toLowerCase();
    return category.includes('server') || role.includes('server') || assetType.includes('server');
  };
  const isSelectedServer = isServerDevice(monitorSelectedDevice) || (monitorRealtime as any)?.is_server === true || (monitorTrend as any)?.is_server === true;

  const selectedFullDevice = React.useMemo(() => {
    if (!monitorSelectedDevice?.id) return null;
    const found = allDevices.find((d) => d.id === monitorSelectedDevice.id);
    if (found) return found;
    if (monitorRealtime?.device && monitorRealtime.device.id === monitorSelectedDevice.id) {
      return monitorRealtime.device;
    }
    return monitorSelectedDevice;
  }, [allDevices, monitorSelectedDevice, monitorRealtime]);

  // Device inventory split by class — drives the always-visible classified
  // explorer so Linux servers (LinuxDriver telemetry) and network devices
  // (Netmiko/SNMP telemetry) are reachable without guessing.

  // Get fetch functions from the hook (they use store internally)
  const {
    fetchMonitoringOverview,
    fetchMonitoringHealthHistory,
    fetchMonitoringAlerts,
    fetchMonitoringIncidentDetail,
    fetchMonitoringIncidentImpact,
    fetchMonitoringIncidentPlaybookRecommendations,
    runMonitoringIncidentPlaybook,
    fetchMonitoringCollectionStatus,
    fetchMonitoringHealthDevices,
    runMonitoringDeviceDiagnostics,
    updateMonitoringIncident,
    fetchMonitoringRealtime,
    fetchHostResources,
  } = useMonitoring({ isAuthenticated, activeTab: 'monitoring', language, pollOutbound: false, healthHistoryRange });

  const openIncidentDetail = useCallback(async (incident: MonitoringIncident) => {
    setSelectedIncident(incident);
    setIncidentAssignee(incident.assigned_to || '');
    setIncidentDetailLoading(true);
    setIncidentImpact(null);
    setIncidentImpactLoading(true);
    setIncidentDiagnostics(null);
    setIncidentRecommendations(null);
    setIncidentRecommendationsLoading(true);
    try {
      const [detail, impact, recommendations] = await Promise.all([
        fetchMonitoringIncidentDetail(incident.id),
        fetchMonitoringIncidentImpact(incident.id),
        fetchMonitoringIncidentPlaybookRecommendations(incident.id),
      ]);
      if (detail) setSelectedIncident(detail);
      if (impact) setIncidentImpact(impact);
      if (recommendations) setIncidentRecommendations(recommendations);
    } finally {
      setIncidentDetailLoading(false);
      setIncidentImpactLoading(false);
      setIncidentRecommendationsLoading(false);
    }
  }, [fetchMonitoringIncidentDetail, fetchMonitoringIncidentImpact, fetchMonitoringIncidentPlaybookRecommendations]);

  const runIncidentDiagnostics = useCallback(async () => {
    const deviceId = selectedIncident?.primary_device_id;
    if (!deviceId || incidentDiagnosticsLoading) return;
    setIncidentDiagnosticsLoading(true);
    try {
      const result = await runMonitoringDeviceDiagnostics(deviceId, selectedIncident?.id);
      setIncidentDiagnostics(result);
      showToast(language === 'zh' ? '采集链路诊断已完成' : 'Collection diagnostics completed', result?.status === 'success' ? 'success' : 'warning');
      fetchMonitoringOverview();
    } catch (error) {
      showToast(error instanceof Error ? error.message : (language === 'zh' ? '采集诊断失败' : 'Collection diagnostics failed'), 'error');
    } finally {
      setIncidentDiagnosticsLoading(false);
    }
  }, [fetchMonitoringOverview, incidentDiagnosticsLoading, language, runMonitoringDeviceDiagnostics, selectedIncident, showToast]);

  const runIncidentPlaybook = useCallback(async (scenarioId: string) => {
    if (!selectedIncident || incidentPlaybookRunning) return;
    setIncidentPlaybookRunning(scenarioId);
    try {
      const result = await runMonitoringIncidentPlaybook(selectedIncident.id, scenarioId);
      showToast(
        language === 'zh' ? `只读 Playbook 已启动${result.platform ? `（${result.platform}）` : ''}` : 'Read-only Playbook started',
        'success',
      );
      const detail = await fetchMonitoringIncidentDetail(selectedIncident.id);
      if (detail) setSelectedIncident(detail);
      fetchMonitoringOverview();
    } catch (error) {
      showToast(error instanceof Error ? error.message : (language === 'zh' ? 'Playbook 启动失败' : 'Unable to start Playbook'), 'error');
    } finally {
      setIncidentPlaybookRunning(null);
    }
  }, [fetchMonitoringIncidentDetail, fetchMonitoringOverview, incidentPlaybookRunning, language, runMonitoringIncidentPlaybook, selectedIncident, showToast]);

  const openCollectionDrilldown = useCallback(async () => {
    setCollectionDrilldownOpen(true);
    setCollectionDrilldownLoading(true);
    try {
      const payload = await fetchMonitoringCollectionStatus();
      setCollectionStatusItems(Array.isArray(payload?.items) ? payload.items : []);
    } catch (error) {
      showToast(error instanceof Error ? error.message : (language === 'zh' ? '加载采集状态失败' : 'Unable to load collection status'), 'error');
    } finally {
      setCollectionDrilldownLoading(false);
    }
  }, [fetchMonitoringCollectionStatus, language, showToast]);

  const openHealthDrilldown = useCallback(async (filter: { label: string; health_status?: string; availability_status?: string; collection_status?: string }) => {
    setHealthDrilldownFilter(filter.label);
    setHealthDrilldownLoading(true);
    try {
      const query = Object.fromEntries(Object.entries(filter).filter(([key]) => key !== 'label')) as { health_status?: string; availability_status?: string; collection_status?: string };
      const payload = await fetchMonitoringHealthDevices(query);
      setHealthDrilldownItems(payload.items || []);
    } catch (error) {
      showToast(error instanceof Error ? error.message : (language === 'zh' ? '加载健康下钻失败' : 'Unable to load health drilldown'), 'error');
    } finally {
      setHealthDrilldownLoading(false);
    }
  }, [fetchMonitoringHealthDevices, language, showToast]);

  const mutateIncident = useCallback(async (action: 'acknowledge' | 'assign' | 'resolve', body: Record<string, string>) => {
    if (!selectedIncident) return;
    setIncidentMutationLoading(true);
    try {
      const updated = await updateMonitoringIncident(selectedIncident.id, action, body);
      if (updated) setSelectedIncident(updated);
      showToast(language === 'zh' ? '事件状态已更新' : 'Incident updated', 'success');
      fetchMonitoringOverview();
    } catch (error) {
      showToast(error instanceof Error ? error.message : (language === 'zh' ? '事件更新失败' : 'Unable to update incident'), 'error');
    } finally {
      setIncidentMutationLoading(false);
    }
  }, [fetchMonitoringOverview, language, selectedIncident, showToast, updateMonitoringIncident]);

  const fetchHostResourceHistory = useCallback(async (rangeHours = hostResourceRange) => {
    setHostResourceHistoryLoading(true);
    try {
      const resp = await fetch(`/api/health/resources/history?range_hours=${rangeHours}`);
      if (!resp.ok) throw new Error('Failed to fetch host resource history');
      const payload = await resp.json() as HostResourceHistoryPayload;
      setHostResourceHistory(payload);
    } catch {
      showToast(language === 'zh' ? '无法加载宿主机资源趋势' : 'Unable to load host resource trend', 'error');
    } finally {
      setHostResourceHistoryLoading(false);
    }
  }, [hostResourceRange, language, showToast]);

  const fmtRate = (bps?: number) => {
    if (bps == null || !Number.isFinite(bps) || bps < 0) return '-';
    if (bps >= 1_000_000_000) return `${(bps / 1_000_000_000).toFixed(2)} Gbps`;
    if (bps >= 1_000_000) return `${(bps / 1_000_000).toFixed(2)} Mbps`;
    if (bps >= 1_000) return `${(bps / 1_000).toFixed(1)} Kbps`;
    return `${bps.toFixed(0)} bps`;
  };

  const fmtThroughput = (bps?: number) => {
    if (bps == null || !Number.isFinite(bps) || bps < 0) return '-';
    const bytes = bps / 8;
    if (bytes >= 1024 ** 4) return `${(bytes / (1024 ** 4)).toFixed(2)} TB/s`;
    if (bytes >= 1024 ** 3) return `${(bytes / (1024 ** 3)).toFixed(2)} GB/s`;
    if (bytes >= 1024 ** 2) return `${(bytes / (1024 ** 2)).toFixed(2)} MB/s`;
    if (bytes >= 1024) return `${(bytes / 1024).toFixed(2)} KB/s`;
    return `${bytes.toFixed(0)} B/s`;
  };

  const formatThroughputParts = (bps?: number) => {
    if (bps == null || !Number.isFinite(bps) || bps < 0) {
      return { value: '-', unit: '' };
    }
    const bytes = bps / 8;
    if (bytes >= 1024 ** 4) return { value: (bytes / (1024 ** 4)).toFixed(2), unit: 'TB/s' };
    if (bytes >= 1024 ** 3) return { value: (bytes / (1024 ** 3)).toFixed(bytes >= 10 * 1024 ** 3 ? 1 : 2), unit: 'GB/s' };
    if (bytes >= 1024 ** 2) return { value: (bytes / (1024 ** 2)).toFixed(bytes >= 100 * 1024 ** 2 ? 0 : bytes >= 10 * 1024 ** 2 ? 1 : 2), unit: 'MB/s' };
    if (bytes >= 1024) return { value: (bytes / 1024).toFixed(bytes >= 100 * 1024 ? 0 : bytes >= 10 * 1024 ? 1 : 2), unit: 'KB/s' };
    return { value: bytes.toFixed(0), unit: 'B/s' };
  };

  const formatPromThroughputParts = (bps?: number) => {
    if (bps == null || !Number.isFinite(bps) || bps < 0) {
      return { value: '-', unit: '' };
    }
    let value = bps / 8;
    const units = ['B/s', 'KiB/s', 'MiB/s', 'GiB/s', 'TiB/s'];
    let unitIndex = 0;
    while (value >= 1024 && unitIndex < units.length - 1) {
      value /= 1024;
      unitIndex += 1;
    }
    if (unitIndex === 0) {
      return { value: value.toFixed(0), unit: units[unitIndex] };
    }
    if (value >= 100) {
      return { value: value.toFixed(0), unit: units[unitIndex] };
    }
    if (value >= 10) {
      return { value: value.toFixed(1), unit: units[unitIndex] };
    }
    return { value: value.toFixed(2), unit: units[unitIndex] };
  };

  const fmtThroughputProm = (bps?: number) => {
    const parts = formatPromThroughputParts(bps);
    return parts.unit ? `${parts.value} ${parts.unit}` : parts.value;
  };

  const fmtPercent = (value?: number | null) => {
    if (value == null || !Number.isFinite(value)) return '--';
    return `${Math.round(value)}%`;
  };

  const fmtThroughputAxis = (bps?: number) => {
    const parts = formatPromThroughputParts(bps);
    return parts.unit ? `${parts.value} ${parts.unit}` : parts.value;
  };

  const formatTs = (value?: string, withSeconds = false) => {
    if (!value) return '-';
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value);
    return d.toLocaleTimeString(language === 'zh' ? 'zh-CN' : 'en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: withSeconds ? '2-digit' : undefined,
    });
  };

  const formatPromTimestamp = (value?: string) => {
    if (!value) return '--';
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  };

  const formatPromAxisTimestamp = (value?: string, rangeMs?: number) => {
    if (!value) return '--';
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value);
    const pad = (n: number) => String(n).padStart(2, '0');
    const safeRange = Number(rangeMs || 0);
    if (safeRange <= 6 * 60 * 60 * 1000) {
      return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    }
    if (safeRange <= 7 * 24 * 60 * 60 * 1000) {
      return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    }
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  };

  const formatFreshness = (value?: string) => {
    if (!value) return language === 'zh' ? '等待数据' : 'Awaiting data';
    const ts = new Date(value).getTime();
    if (Number.isNaN(ts)) return String(value);
    const diffSec = Math.max(0, Math.floor((Date.now() - ts) / 1000));
    if (language === 'zh') {
      if (diffSec < 5) return '刚刚更新';
      if (diffSec < 60) return `${diffSec} 秒前更新`;
      const diffMin = Math.floor(diffSec / 60);
      if (diffMin < 60) return `${diffMin} 分钟前更新`;
      const diffHr = Math.floor(diffMin / 60);
      return `${diffHr} 小时前更新`;
    }
    if (diffSec < 5) return 'Updated just now';
    if (diffSec < 60) return `Updated ${diffSec}s ago`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `Updated ${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    return `Updated ${diffHr}h ago`;
  };

  const severityLabel = (sev: string) => {
    const s = String(sev || '').toLowerCase();
    if (s === 'critical') return language === 'zh' ? '严重' : 'Critical';
    if (s === 'major') return language === 'zh' ? '主要' : 'Major';
    if (s === 'warning') return language === 'zh' ? '次要' : 'Minor';
    return sev;
  };

  const phaseLabel = (resolvedAt?: string | null) => {
    if (language === 'zh') {
      return resolvedAt ? '已恢复' : '告警中';
    }
    return resolvedAt ? 'Recovered' : 'Active';
  };

  const hostAlertTitle = (metricKey?: string, fallbackTitle?: string) => {
    if (metricKey === 'cpu_percent') return language === 'zh' ? '宿主机 CPU 使用率过高' : 'Host CPU usage high';
    if (metricKey === 'memory_percent') return language === 'zh' ? '宿主机内存使用率过高' : 'Host memory usage high';
    if (metricKey === 'disk_percent') return language === 'zh' ? '宿主机磁盘使用率过高' : 'Host disk usage high';
    if (metricKey === 'database_status') return language === 'zh' ? '数据库连接异常' : 'Database connection unhealthy';
    return fallbackTitle || (language === 'zh' ? '宿主机资源告警' : 'Host resource alert');
  };

  const toNumOrNull = (value: any): number | null => {
    if (value == null || value === '') return null;
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  };

  const trendData = (monitorTrend?.series || []).map((p: any) => {
    const base = {
      ts: p.ts_minute,
      time: formatTs(p.ts_minute, false),
    };
    if (isSelectedServer) {
      return {
        ...base,
        cpu_load: toNumOrNull(p.cpu_load),
        cpu_util: toNumOrNull(p.cpu_util),
        mem_avail: toNumOrNull(p.mem_avail),
        swap_util: toNumOrNull(p.swap_util),
        io_wait: toNumOrNull(p.io_wait),
        disk_util: toNumOrNull(p.disk_util),
        inode_util: toNumOrNull(p.inode_util),
        tcp_conns: toNumOrNull(p.tcp_conns),
        process_health: toNumOrNull(p.process_health),
        service_sshd: toNumOrNull(p.service_sshd),
        service_crond: toNumOrNull(p.service_crond),
        service_docker: toNumOrNull(p.service_docker),
      };
    }
    return {
      ...base,
      in_bps: toNumOrNull(p.total_in_bps),
      out_bps: toNumOrNull(p.total_out_bps),
      in_pkts: toNumOrNull(p.total_in_pkts),
      out_pkts: toNumOrNull(p.total_out_pkts),
      errors: toNumOrNull(p.total_errors),
      drops: toNumOrNull(p.total_drops),
    };
  });

  const realtimeData = (monitorRealtime?.series || []).map((p: any) => {
    const base = {
      ts: p.ts,
      time: formatTs(p.ts, true),
    };
    if (isSelectedServer) {
      return {
        ...base,
        cpu_load: toNumOrNull(p.cpu_load),
        cpu_util: toNumOrNull(p.cpu_util),
        mem_avail: toNumOrNull(p.mem_avail),
        swap_util: toNumOrNull(p.swap_util),
        io_wait: toNumOrNull(p.io_wait),
        disk_util: toNumOrNull(p.disk_util),
        inode_util: toNumOrNull(p.inode_util),
        tcp_conns: toNumOrNull(p.tcp_conns),
        process_health: toNumOrNull(p.process_health),
        service_sshd: toNumOrNull(p.service_sshd),
        service_crond: toNumOrNull(p.service_crond),
        service_docker: toNumOrNull(p.service_docker),
      };
    }
    return {
      ...base,
      in_bps: toNumOrNull(p.in_bps),
      out_bps: toNumOrNull(p.out_bps),
      in_pkts: toNumOrNull(p.in_pkts),
      out_pkts: toNumOrNull(p.out_pkts),
      errors: toNumOrNull(p.errors),
      drops: toNumOrNull(p.drops),
    };
  });

  const trendMetricDefs = [
    { key: 'in_bps', label: language === 'zh' ? '入流量' : 'IN Throughput', short: 'IN', color: '#2563eb', unit: 'throughput' },
    { key: 'out_bps', label: language === 'zh' ? '出流量' : 'OUT Throughput', short: 'OUT', color: '#ea580c', unit: 'throughput' },
    { key: 'in_pkts', label: language === 'zh' ? '入包' : 'IN Packets', short: language === 'zh' ? '入包' : 'IN Pkts', color: '#7c3aed', unit: 'count' },
    { key: 'out_pkts', label: language === 'zh' ? '出包' : 'OUT Packets', short: language === 'zh' ? '出包' : 'OUT Pkts', color: '#0891b2', unit: 'count' },
    { key: 'errors', label: language === 'zh' ? '错误' : 'Errors', short: language === 'zh' ? '错误' : 'Errors', color: '#dc2626', unit: 'count' },
    { key: 'drops', label: language === 'zh' ? '丢包' : 'Drops', short: language === 'zh' ? '丢包' : 'Drops', color: '#16a34a', unit: 'count' },
  ] as const;
  const trendMetricMap = Object.fromEntries(trendMetricDefs.map((d) => [d.key, d]));
  const selectedMetricDefs = trendMetricDefs.filter((d) => monitorTrendMetrics.includes(d.key));
  const hasThroughputMetric = selectedMetricDefs.some((d) => d.unit === 'throughput');
  const hasCountMetric = selectedMetricDefs.some((d) => d.unit === 'count');
  const hasTrendResponse = !!monitorTrend;
  const chartData = trendData.length > 0 ? trendData : (hasTrendResponse ? [] : realtimeData);
  const fullEndIndex = Math.max(0, chartData.length - 1);
  const rawZoomRange = monitorTrendZoom ?? { startIndex: 0, endIndex: fullEndIndex };
  const zoomRange = {
    startIndex: Math.max(0, Math.min(rawZoomRange.startIndex, fullEndIndex)),
    endIndex: Math.max(0, Math.min(rawZoomRange.endIndex, fullEndIndex)),
  };
  if (zoomRange.endIndex < zoomRange.startIndex) zoomRange.endIndex = zoomRange.startIndex;
  const zoomActive = monitorTrendZoom !== null && (zoomRange.startIndex > 0 || zoomRange.endIndex < fullEndIndex);
  const visibleChartData = chartData.slice(zoomRange.startIndex, zoomRange.endIndex + 1);
  const displayedChartData = zoomActive ? visibleChartData : chartData;
  const displayedRangeMs = (() => {
    if (displayedChartData.length < 2) return 0;
    const startTs = new Date(displayedChartData[0]?.ts || '').getTime();
    const endTs = new Date(displayedChartData[displayedChartData.length - 1]?.ts || '').getTime();
    if (Number.isNaN(startTs) || Number.isNaN(endTs)) return 0;
    return Math.max(0, endTs - startTs);
  })();
  const isCompactTrend = monitorTrendUiMode === 'compact';
  const axisTickCount = (() => {
    const points = displayedChartData.length;
    if (points <= 2) return points;
    const maxTicksByMode = isCompactTrend ? 5 : 8;
    const maxTicksByPoints = Math.max(3, Math.min(maxTicksByMode, Math.floor(points / 2)));
    if (displayedRangeMs <= 15 * 60 * 1000) return Math.min(maxTicksByPoints, 4);
    if (displayedRangeMs <= 60 * 60 * 1000) return Math.min(maxTicksByPoints, 5);
    if (displayedRangeMs <= 6 * 60 * 60 * 1000) return Math.min(maxTicksByPoints, 6);
    if (displayedRangeMs <= 24 * 60 * 60 * 1000) return Math.min(maxTicksByPoints, 7);
    if (displayedRangeMs <= 7 * 24 * 60 * 60 * 1000) return Math.min(maxTicksByPoints, 8);
    return Math.min(maxTicksByPoints, 6);
  })();
  const dragPreviewActive = monitorTrendDragStart != null && monitorTrendDragEnd != null;
  const dragStartIndex = dragPreviewActive ? Math.max(0, Math.min(monitorTrendDragStart as number, monitorTrendDragEnd as number)) : null;
  const dragEndIndex = dragPreviewActive ? Math.min(fullEndIndex, Math.max(monitorTrendDragStart as number, monitorTrendDragEnd as number)) : null;
  const dragBaseIndex = zoomActive ? zoomRange.startIndex : 0;
  const showChart = monitorSelectedDevice && displayedChartData.length > 0 && selectedMetricDefs.length > 0;
  const fmtMetricValue = (metric: { unit: string }, raw?: number | null) => {
    if (raw == null || !Number.isFinite(raw)) return language === 'zh' ? '无样本' : 'No sample';
    return metric.unit === 'throughput' ? fmtThroughput(raw) : Number(raw).toLocaleString();
  };
  const latestPoint = displayedChartData.length > 0 ? displayedChartData[displayedChartData.length - 1] : null;
  const windowStartPoint = displayedChartData.length > 0 ? displayedChartData[0] : null;
  const [watchlistScope, setWatchlistScope] = React.useState<'focus' | 'all'>('focus');
  const defaultHotInterfaces = Array.isArray(monitorOverview?.top_hot_interfaces) ? monitorOverview.top_hot_interfaces : [];
  const defaultOpenAlerts = Array.isArray(monitorOverview?.recent_open_alerts) ? monitorOverview.recent_open_alerts : [];
  const dashboardSiteOptions = Array.from(new Set([
    ...defaultHotInterfaces.map((item: any) => String(item.site || '').trim()).filter(Boolean),
    ...defaultOpenAlerts.map((item: any) => String(item.site || '').trim()).filter(Boolean),
  ])).sort((a, b) => a.localeCompare(b));
  const filteredHotInterfaces = defaultHotInterfaces.filter((item: any) => monitorDashboardSiteFilter === 'all' || String(item.site || '').trim() === monitorDashboardSiteFilter);
  const watchlistLimit = 6;
  const uniqueWatchlistItems = (() => {
    const seenDevices = new Set<string>();
    const items: any[] = [];
    for (const item of filteredHotInterfaces) {
      const deviceKey = String(item.device_id || item.id || item.hostname || '');
      if (!deviceKey || seenDevices.has(deviceKey)) continue;
      seenDevices.add(deviceKey);
      items.push(item);
    }
    return items;
  })();
  const anomalousWatchlistItems = uniqueWatchlistItems.filter((item: any) => {
    const statusLower = String(item.status || '').toLowerCase();
    return statusLower === 'down' || Number(item.errors || 0) > 0 || Number(item.drops || 0) > 0 || Number(item.utilization_pct || 0) >= 85;
  });
  const watchlistItems = watchlistScope === 'all'
    ? uniqueWatchlistItems
    : (anomalousWatchlistItems.length > 0 ? anomalousWatchlistItems.slice(0, watchlistLimit) : uniqueWatchlistItems.slice(0, watchlistLimit));
  const hiddenWatchlistCount = Math.max(0, (watchlistScope === 'all' ? uniqueWatchlistItems.length : (anomalousWatchlistItems.length > 0 ? anomalousWatchlistItems.length : uniqueWatchlistItems.length)) - watchlistItems.length);
  const displaySearchResults = (() => {
    if (monitorSearchResults.length > 0) return monitorSearchResults;
    if (monitorSelectedDevice?.id) return [monitorSelectedDevice];
    return [] as any[];
  })();
  const showDefaultWatchlist = monitorSearch.trim().length === 0 && !monitorSelectedDevice?.id;
  const filteredOpenAlerts = defaultOpenAlerts.filter((item: any) => {
    const siteMatch = monitorDashboardSiteFilter === 'all' || String(item.site || '').trim() === monitorDashboardSiteFilter;
    const severityMatch = monitorDashboardAlertFilter === 'all' || String(item.severity || '').toLowerCase() === monitorDashboardAlertFilter;
    return siteMatch && severityMatch;
  });

  // Group duplicate alerts by title+severity, keep newest, attach count
  const groupedOpenAlerts = React.useMemo(() => {
    const map = new Map<string, any>();
    for (const a of filteredOpenAlerts) {
      const key = `${a.title}||${a.severity}`;
      const existing = map.get(key);
      if (!existing) {
        map.set(key, { ...a, _groupCount: 1 });
      } else {
        existing._groupCount += 1;
        // keep the newest created_at
        if (a.created_at > existing.created_at) {
          Object.assign(existing, { ...a, _groupCount: existing._groupCount });
        }
      }
    }
    return Array.from(map.values());
  }, [filteredOpenAlerts]);

  const toggleTrendMetric = (metricKey: string) => {
    setMonitorTrendMetrics((prev) => prev.includes(metricKey) ? prev.filter((k) => k !== metricKey) : [...prev, metricKey]);
  };

  const selectAllTrendMetrics = () => {
    setMonitorTrendMetrics(trendMetricDefs.map((m) => m.key));
  };

  const clearAllTrendMetrics = () => {
    setMonitorTrendMetrics([]);
  };

  const openMonitorDevice = (device: any) => {
    if (!device?.id && !device?.device_id) return;
    const nextDevice = {
      id: device.id || device.device_id,
      hostname: device.hostname || '-',
      ip_address: device.ip_address || '-',
      platform: device.platform || '-',
      role: device.role || '',
      site: device.site || '',
    };
    setMonitorSearch(nextDevice.hostname === '-' ? nextDevice.ip_address : nextDevice.hostname);
    setMonitorSelectedDevice(nextDevice);
  };

  const toUtcIso = (localVal: string) => {
    if (!localVal) return '';
    const dt = new Date(localVal);
    if (Number.isNaN(dt.getTime())) return '';
    return dt.toISOString();
  };

  const toLocalInputValue = (d: Date) => {
    const pad = (v: number) => String(v).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };

  const applyQuickRange = (hours: number) => {
    const end = new Date();
    const start = new Date(end.getTime() - hours * 60 * 60 * 1000);
    setMonitorTrendStartInput(toLocalInputValue(start));
    setMonitorTrendEndInput(toLocalInputValue(end));
    setMonitorTrendZoom(null);
    setMonitorTrendDragStart(null);
    setMonitorTrendDragEnd(null);
    setMonitorTrendRange({ start_time: start.toISOString(), end_time: end.toISOString() });
  };

  const interfaceOptions = (monitorRealtime?.latest_interfaces || []).map((it: any) => String(it.interface_name || '')).filter(Boolean);
  const latestInSummary = formatPromThroughputParts((latestPoint as any)?.in_bps);
  const latestOutSummary = formatPromThroughputParts((latestPoint as any)?.out_bps);
  const promExpressionLabel = monitorTrendInterface
    ? `rate(interface_bytes_total{if="${monitorTrendInterface}"}[5m])`
    : 'sum(rate(interface_bytes_total[5m]))';
  const hostResourceTone = hostResources?.status === 'critical'
    ? 'bg-red-50 text-red-700 border-red-200'
    : hostResources?.status === 'degraded'
      ? 'bg-amber-50 text-amber-700 border-amber-200'
      : 'bg-emerald-50 text-emerald-700 border-emerald-200';
  const hostStatusLabel = hostResources?.status === 'critical'
    ? (language === 'zh' ? '严重' : 'Critical')
    : hostResources?.status === 'degraded'
      ? (language === 'zh' ? '告警' : 'Degraded')
      : (language === 'zh' ? '健康' : 'Healthy');
  const hostTrendData = (hostResourceHistory?.series || []).map((point) => ({
    ts: point.ts,
    time: formatTs(point.ts, hostResourceRange === 1),
    cpu_percent: point.cpu_percent,
    memory_percent: point.memory_percent,
    disk_percent: point.disk_percent,
  }));
  const hostAlertHistory = Array.isArray(hostResourceHistory?.alerts) ? hostResourceHistory.alerts : [];
  const currentHostActiveAlerts = ((hostResourceHistory?.current?.active_alerts || hostResources?.active_alerts || [])).map((alert, index) => {
    const matchedOpenAlert = hostAlertHistory.find((item) => !item.resolved_at && item.metric_key === alert.metric_key);
    return {
      ...matchedOpenAlert,
      ...alert,
      id: matchedOpenAlert?.id || alert.id || `${alert.metric_key || 'host-alert'}-${index}`,
      created_at: matchedOpenAlert?.created_at,
      resolved_at: null,
    };
  });
  const hostActiveAlerts = currentHostActiveAlerts.length > 0
    ? currentHostActiveAlerts
    : hostAlertHistory.filter((alert) => !alert.resolved_at);
  const hostHistoricalAlerts = hostAlertHistory.slice(0, 10);
  const deviceHealthSummary = monitorOverview?.device_health_summary || null;
  const riskyDevices = Array.isArray(monitorOverview?.top_risky_devices) ? monitorOverview.top_risky_devices : [];
  const platformHealth = monitorOverview?.platform_health || null;
  const workerRunningCount = Object.values((platformHealth?.workers || {}) as Record<string, { running?: number }>).reduce((total, item) => total + Number(item?.running || 0), 0);
  const healthHistoryData = (monitorHealthHistory?.series || []).map((point) => ({
    ...point,
    time: formatTs(point.ts, true),
  }));

  /* NOC auto-refresh (30s) */
  useEffect(() => {
    fetchHostResourceHistory(hostResourceRange);
  }, [fetchHostResourceHistory, hostResourceRange]);

  useEffect(() => {
    if (!monitorPageVisible || !autoRefresh) {
      if (autoRefreshRef.current) { clearInterval(autoRefreshRef.current); autoRefreshRef.current = null; }
      return;
    }
    autoRefreshRef.current = setInterval(() => {
      fetchMonitoringOverview();
      fetchMonitoringAlerts();
      fetchHostResources();
      fetchHostResourceHistory(hostResourceRange);
      if (monitorSelectedDevice?.id) {
        fetchMonitoringRealtime(monitorSelectedDevice.id).then(setMonitorRealtime).catch(() => undefined);
      }
    }, 30000);
    return () => { if (autoRefreshRef.current) clearInterval(autoRefreshRef.current); };
  }, [autoRefresh, monitorPageVisible, hostResourceRange, fetchMonitoringOverview, fetchMonitoringAlerts, fetchHostResources, fetchHostResourceHistory, monitorSelectedDevice, fetchMonitoringRealtime, setMonitorRealtime]);

  useEffect(() => {
    const timer = setInterval(() => setNocClock(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (monitorSelectedDevice?.id) {
      setShowAdvanced(true);
    }
  }, [monitorSelectedDevice]);

  const doRefreshAll = useCallback(() => {
    setRefreshing(true);
    fetchMonitoringOverview();
    fetchMonitoringAlerts();
    fetchHostResources();
    fetchHostResourceHistory(hostResourceRange);
    if (monitorSelectedDevice?.id) {
      fetchMonitoringRealtime(monitorSelectedDevice.id).then(setMonitorRealtime).catch(() => undefined);
    }
    setTimeout(() => setRefreshing(false), 1200);
  }, [fetchMonitoringOverview, fetchMonitoringAlerts, fetchHostResources, fetchHostResourceHistory, hostResourceRange, monitorSelectedDevice, fetchMonitoringRealtime, setMonitorRealtime]);

  /* derived data for dashboard */
  const onlineDevices = monitorOverview?.online_devices ?? 0;
  const rawTotalDevices = (monitorOverview?.online_devices ?? 0) + (monitorOverview?.offline_devices ?? 0);
  const totalDevices = monitorOverview?.total_devices ?? (rawTotalDevices > 0 ? rawTotalDevices : (deviceHealthSummary?.total_devices ?? 0));
  const offlineDevices = monitorOverview?.offline_devices ?? deviceHealthSummary?.offline_devices ?? Math.max(0, totalDevices - onlineDevices);
  const unknownAvailabilityDevices = monitorOverview?.unknown_devices ?? deviceHealthSummary?.unknown_availability_devices ?? 0;
  const openAlerts = monitorOverview?.open_alerts ?? 0;
  const healthyCount = deviceHealthSummary?.healthy ?? 0;
  const warningCount = deviceHealthSummary?.warning ?? 0;
  const criticalCount = deviceHealthSummary?.critical ?? 0;
  const unknownCount = deviceHealthSummary?.unknown ?? 0;
  const healthTotal = deviceHealthSummary?.total_devices ?? (healthyCount + warningCount + criticalCount + unknownCount);
  const healthEvaluableCount = deviceHealthSummary?.health_evaluable_count ?? (healthyCount + warningCount + criticalCount);
  const healthPct = healthEvaluableCount > 0 ? Math.round((healthyCount / healthEvaluableCount) * 100) : null;
  const collectionAnomalyDevices = monitorOverview?.collection_anomaly_devices ?? deviceHealthSummary?.collection_anomaly_devices ?? 0;
  const dataConfidenceAvg = monitorOverview?.data_confidence_avg ?? deviceHealthSummary?.data_confidence_avg ?? null;
  const lastCollectionAt = monitorOverview?.last_collection_at ?? deviceHealthSummary?.last_collection_at ?? null;
  const healthBarWidth = (count: number) => {
    if (healthTotal <= 0 || count <= 0) return '0%';
    const pct = (count / healthTotal) * 100;
    // Ensure tiny segments are still visible (min 6%)
    return `${Math.max(6, pct)}%`;
  };
  const alertSeverityCounts = monitorOverview?.open_alert_severity_counts || {};
  const criticalAlertCount = alertSeverityCounts.critical ?? defaultOpenAlerts.filter((a: any) => String(a.severity || '').toLowerCase() === 'critical').length;
  const majorAlertCount = alertSeverityCounts.major ?? defaultOpenAlerts.filter((a: any) => String(a.severity || '').toLowerCase() === 'major').length;
  const warningAlertCount = alertSeverityCounts.warning ?? defaultOpenAlerts.filter((a: any) => !['critical', 'major'].includes(String(a.severity || '').toLowerCase())).length;

  const nocTimeStr = nocClock.toLocaleTimeString(language === 'zh' ? 'zh-CN' : 'en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });

  return (
    <div className="monitoring-center flex flex-col h-full overflow-hidden">
      <PageHero
        icon={Radio}
        title={language === 'zh' ? '运维指挥中心' : 'NOC Command Center'}
        subtitle={language === 'zh' ? '实时监控 · 全网态势 · 快速处置' : 'Real-time monitoring · Network posture · Quick response'}
        actions={
          <>
            <button type="button" onClick={() => { fetchMonitoringOverview(); fetchHostResources(); showToast(language === 'zh' ? '已下发全网设备检查' : 'Device check initiated', 'info'); }} className="inline-flex items-center gap-1.5 rounded-xl border border-sky-200 bg-sky-50 px-3 py-1.5 text-[11px] font-semibold text-sky-700 transition-all hover:bg-sky-100 hover:shadow-sm">
              <Zap size={13} />{language === 'zh' ? '一键检查' : 'Check All'}
            </button>
            <button type="button" onClick={() => navigate('/alerts')} className="inline-flex items-center gap-1.5 rounded-xl border border-red-200 bg-red-50 px-3 py-1.5 text-[11px] font-semibold text-red-700 transition-all hover:bg-red-100 hover:shadow-sm">
              <Bell size={13} />{language === 'zh' ? '告警中心' : 'Alert Center'}
            </button>
            <button type="button" onClick={() => navigate('/automation/execute')} className="inline-flex items-center gap-1.5 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-[11px] font-semibold text-emerald-700 transition-all hover:bg-emerald-100 hover:shadow-sm">
              <Play size={13} />{language === 'zh' ? '自动化任务' : 'Automation'}
            </button>
            <button type="button" onClick={() => navigate('/topology')} className="inline-flex items-center gap-1.5 rounded-xl border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-[11px] font-semibold text-indigo-700 transition-all hover:bg-indigo-100 hover:shadow-sm">
              <MapIcon size={13} />{language === 'zh' ? '网络拓扑' : 'Topology'}
            </button>
            <div className="h-6 w-px bg-black/10" />
            <button type="button" onClick={() => setAutoRefresh(!autoRefresh)} className={`inline-flex items-center gap-1.5 rounded-xl border px-2.5 py-1.5 text-[10px] font-bold uppercase tracking-wider transition-all ${autoRefresh ? 'border-emerald-300 bg-emerald-50 text-emerald-700' : 'border-[var(--card-border)] bg-[var(--card-bg)] text-[var(--muted-text)]'}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${autoRefresh ? 'bg-emerald-500 animate-pulse' : 'bg-black/20'}`} />
              {autoRefresh ? '30s' : 'OFF'}
            </button>
            <button type="button" disabled={refreshing} onClick={doRefreshAll} className={`inline-flex items-center gap-1.5 rounded-xl border px-2.5 py-1.5 text-[10px] font-bold uppercase tracking-wider transition-all ${refreshing ? 'border-sky-300 bg-sky-50 text-sky-700 cursor-not-allowed' : 'border-[var(--card-border)] bg-[var(--card-bg)] text-[var(--muted-text)] hover:border-black/20'}`}>
              <RefreshCw size={12} className={refreshing ? 'animate-spin' : ''} />
              {refreshing ? (language === 'zh' ? '刷新中' : 'Sync') : (language === 'zh' ? '立即刷新' : 'Refresh')}
            </button>
            <span className="hidden rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-1.5 text-[10px] text-[var(--muted-text)] xl:inline-flex xl:items-center xl:gap-1.5" title={language === 'zh' ? '\u6570\u636e\u53ef\u4fe1\u5ea6\u4e0e\u6700\u8fd1\u91c7\u96c6\u65f6\u95f4' : 'Data confidence and last collection'}>
              <span className={lastCollectionAt ? 'text-emerald-600' : 'text-amber-600'}>●</span>
              {lastCollectionAt ? formatTs(lastCollectionAt, true) : (language === 'zh' ? '\u6682\u65e0\u91c7\u96c6' : 'No collection')}
              <span>· {dataConfidenceAvg == null ? '--' : Math.round(dataConfidenceAvg)}%</span>
            </span>
            <span className="tabular-nums text-[11px] font-mono text-[var(--muted-text)]">{nocTimeStr}</span>
          </>
        }
      />

      <div className="ops-page-scroll flex-1 overflow-auto p-4 md:p-6">
      <div className="monitoring-cockpit-frame space-y-4 pb-2">

      {/* CRITICAL BANNER */}
      {(criticalCount > 0 || criticalAlertCount > 0) && (
        <button type="button" onClick={() => navigate('/alerts')} className="ops-incident-ribbon w-full flex items-center gap-3 rounded-2xl border border-l-4 border-l-rose-400 px-5 py-3.5 text-white transition-all hover:-translate-y-0.5 hover:shadow-[0_16px_32px_rgba(166,27,50,0.28)] active:translate-y-0">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white/20">
            <AlertTriangle size={18} className="animate-pulse" />
          </span>
          <div className="flex-1 text-left">
            <p className="text-sm font-bold">
              {language === 'zh'
                ? `\ud83d\udea8 ${criticalCount} \u53f0\u4e25\u91cd\u8bbe\u5907 + ${criticalAlertCount} \u6761\u4e25\u91cd\u544a\u8b66\u6b63\u5728\u5f71\u54cd\u7f51\u7edc`
                : `\ud83d\udea8 ${criticalCount} Critical Devices + ${criticalAlertCount} Critical Alerts Impacting Network`}
            </p>
            <p className="text-[11px] text-white/80">
              {language === 'zh'
                ? `${offlineDevices} \u53f0\u79bb\u7ebf · ${openAlerts} \u6761\u6d3b\u8dc3\u544a\u8b66 · \u70b9\u51fb\u67e5\u770b\u8be6\u60c5`
                : `${offlineDevices} offline · ${openAlerts} active alerts · Click for details`}
            </p>
          </div>
          <ArrowUpRight size={16} className="shrink-0 text-white/60" />
        </button>
      )}

      {/* SECTION 1: EXPLICIT NOC DIMENSIONS */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatusCard
          label={language === 'zh' ? '\u8bbe\u5907\u53ef\u7528\u6027' : 'Availability'}
          value={`${onlineDevices} / ${totalDevices}`}
          tone={offlineDevices > 0 ? 'amber' : 'green'}
          pulse={offlineDevices > 0}
          sub={`${offlineDevices} ${language === 'zh' ? '\u79bb\u7ebf' : 'offline'} · ${unknownAvailabilityDevices} ${language === 'zh' ? '\u72b6\u6001\u672a\u77e5' : 'unknown'}`}
          onClick={() => openHealthDrilldown({ label: language === 'zh' ? '\u79bb\u7ebf\u8bbe\u5907' : 'Offline devices', availability_status: offlineDevices > 0 ? 'offline' : 'online' })}
          icon={<Radio size={14} />}
        />
        <StatusCard
          label={language === 'zh' ? '\u5065\u5eb7\u8bc4\u4f30' : 'Health Evaluation'}
          value={healthPct == null ? '--' : `${healthPct}%`}
          tone={healthPct == null ? 'default' : healthPct >= 85 ? 'green' : healthPct >= 60 ? 'amber' : 'red'}
          sub={`${healthyCount} ${language === 'zh' ? '\u5065\u5eb7' : 'healthy'} / ${healthEvaluableCount} ${language === 'zh' ? '\u53ef\u8bc4\u4f30' : 'evaluable'} · ${dataConfidenceAvg == null ? '--' : `${Math.round(dataConfidenceAvg)}%`} ${language === 'zh' ? '\u6570\u636e\u53ef\u4fe1\u5ea6' : 'confidence'}`}
          onClick={() => openHealthDrilldown({ label: language === 'zh' ? '\u5065\u5eb7\u8bbe\u5907' : 'Healthy devices', health_status: 'healthy' })}
          icon={<HeartPulse size={14} />}
        />
        <StatusCard
          label={language === 'zh' ? '\u91c7\u96c6\u5b8c\u6574\u6027' : 'Collection Integrity'}
          value={collectionAnomalyDevices}
          tone={collectionAnomalyDevices > 0 ? 'amber' : 'green'}
          sub={language === 'zh' ? '\u53f0\u8bbe\u5907\u5b58\u5728\u5931\u8d25\u3001\u8fc7\u671f\u6216\u90e8\u5206\u5931\u8d25\u91c7\u96c6' : 'devices with failed, stale, or partial collection'}
          onClick={openCollectionDrilldown}
          icon={<Database size={14} />}
        />
        <StatusCard
          label={language === 'zh' ? '\u6d3b\u52a8\u544a\u8b66' : 'Active Alerts'}
          value={openAlerts}
          tone={openAlerts > 0 ? 'red' : 'green'}
          sub={`${criticalAlertCount} ${language === 'zh' ? '\u4e25\u91cd' : 'critical'} · ${majorAlertCount} ${language === 'zh' ? '\u4e3b\u8981' : 'major'} · ${warningAlertCount} ${language === 'zh' ? '\u4e00\u822c' : 'warning'}`}
          onClick={() => navigate('/alerts')}
          icon={<Bell size={14} />}
        />
      </div>

      {/* ACTIVE INCIDENTS: grouped operator-facing work queue */}
      <section className="ops-surface rounded-2xl p-5 space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-rose-600">{language === 'zh' ? '事件聚合' : 'Incident Queue'}</p>
            <h3 className="mt-1 text-lg font-bold text-[var(--app-text)]">{language === 'zh' ? '活跃事件与处置' : 'Active incidents & response'}</h3>
            <p className="text-xs text-[var(--muted-text)]">{language === 'zh' ? '关联同一设备的连通性告警，避免重复派单，并保留原始告警时间线。' : 'Grouped alerts become one actionable incident while the original timeline remains available.'}</p>
          </div>
          <button type="button" onClick={() => navigate('/alerts')} className="rounded-lg border border-[var(--card-border)] px-3 py-1.5 text-[11px] font-semibold text-[var(--muted-text)] hover:border-rose-300 hover:bg-rose-50 hover:text-rose-700">
            {language === 'zh' ? `查看全部 ${monitorIncidentTotal} 个` : `View all ${monitorIncidentTotal}`}
          </button>
        </div>
        {monitorIncidents.length > 0 ? (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
            {monitorIncidents.slice(0, 8).map((incident) => {
              const severity = String(incident.severity || 'warning').toLowerCase();
              const tone = severity === 'critical' ? 'border-rose-300 bg-rose-50/60' : severity === 'major' ? 'border-orange-300 bg-orange-50/60' : 'border-amber-200 bg-amber-50/50';
              return (
                <button key={incident.id} type="button" onClick={() => openIncidentDetail(incident)} className={`group rounded-xl border px-3 py-3 text-left transition-all hover:-translate-y-0.5 hover:shadow-sm ${tone}`}>
                  <div className="flex items-start gap-3">
                    <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-white/80 text-rose-600"><AlertTriangle size={14} /></span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center justify-between gap-2">
                        <span className="truncate text-xs font-bold text-[var(--app-text)]">{incident.title}</span>
                        <span className="shrink-0 rounded-full bg-white/80 px-2 py-0.5 text-[9px] font-bold uppercase text-[var(--muted-text)]">{incident.status}</span>
                      </span>
                      <span className="mt-1 block truncate text-[10px] text-[var(--muted-text)]">{incident.hostname || incident.primary_device_id || '--'} · {incident.site || (language === 'zh' ? '未分配站点' : 'No site')}</span>
                      <span className="mt-2 flex flex-wrap gap-1.5 text-[10px] font-semibold text-[var(--muted-text)]">
                        <span className="rounded-full bg-white/80 px-2 py-0.5">{incident.impact_alert_count} {language === 'zh' ? '条告警' : 'alerts'}</span>
                        <span className="rounded-full bg-white/80 px-2 py-0.5">{incident.impact_device_count} {language === 'zh' ? '台设备' : 'devices'}</span>
                        <span className="rounded-full bg-white/80 px-2 py-0.5">{severity}</span>
                      </span>
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-[var(--card-border)] px-4 py-6 text-center text-sm text-[var(--muted-text)]">
            <CheckCircle2 size={20} className="mx-auto mb-2 text-emerald-500" />
            {language === 'zh' ? '当前没有活跃事件。' : 'No active incidents.'}
          </div>
        )}
      </section>

      <section className="ops-surface rounded-2xl p-5 platform-health-section">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-indigo-600">{language === 'zh' ? '平台自监控' : 'Platform health'}</p>
            <h3 className="mt-1 text-lg font-bold text-[var(--app-text)]">{language === 'zh' ? '监控平台运行状态' : 'Monitoring platform status'}</h3>
          </div>
          <span className={`rounded-full px-2.5 py-1 text-[10px] font-bold ${platformHealth?.collectors?.status === 'degraded' ? 'bg-amber-100 text-amber-700' : 'bg-emerald-100 text-emerald-700'}`}>{platformHealth?.collectors?.status === 'degraded' ? (language === 'zh' ? '存在采集器异常' : 'Collector degraded') : (language === 'zh' ? '平台正常' : 'Platform healthy')}</span>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-4">
          <div className="rounded-xl bg-black/[0.03] px-3 py-2"><p className="text-[10px] text-[var(--muted-text)]">{language === 'zh' ? '数据库' : 'Database'}</p><p className="mt-1 text-sm font-bold text-emerald-600">{language === 'zh' ? '正常' : 'Healthy'}</p></div>
          <div className="rounded-xl bg-black/[0.03] px-3 py-2"><p className="text-[10px] text-[var(--muted-text)]">{language === 'zh' ? '采集器' : 'Collectors'}</p><p className="mt-1 text-sm font-bold text-[var(--app-text)]">{platformHealth?.collectors?.total ?? '--'} <span className="text-[10px] font-normal text-[var(--muted-text)]">/ {platformHealth?.collectors?.failed ?? 0} {language === 'zh' ? '异常' : 'failed'}</span></p></div>
          <div className="rounded-xl bg-black/[0.03] px-3 py-2"><p className="text-[10px] text-[var(--muted-text)]">{language === 'zh' ? '采集异常设备' : 'Collection anomalies'}</p><p className="mt-1 text-sm font-bold text-amber-600">{collectionAnomalyDevices}</p></div>
          <div className="rounded-xl bg-black/[0.03] px-3 py-2"><p className="text-[10px] text-[var(--muted-text)]">{language === 'zh' ? '最近采集' : 'Last collection'}</p><p className="mt-1 truncate text-sm font-bold text-[var(--app-text)]">{lastCollectionAt ? formatTs(lastCollectionAt, true) : '--'}</p></div>
        </div>
         <div className="mt-2 grid grid-cols-2 gap-2 md:grid-cols-4">
           <div className="rounded-xl bg-black/[0.03] px-3 py-2"><p className="text-[10px] text-[var(--muted-text)]">{language === 'zh' ? '\u961f\u5217\u7b49\u5f85' : 'Queue pending'}</p><p className="mt-1 text-sm font-bold text-[var(--app-text)]">{platformHealth?.queue?.arp?.pending ?? '--'}</p></div>
           <div className="rounded-xl bg-black/[0.03] px-3 py-2"><p className="text-[10px] text-[var(--muted-text)]">{language === 'zh' ? '\u6700\u8fd1\u91c7\u96c6\u5ef6\u8fdf' : 'Collection delay'}</p><p className="mt-1 text-sm font-bold text-[var(--app-text)]">{lastCollectionAt ? formatTs(lastCollectionAt, true) : '--'}</p></div>
           <div className="rounded-xl bg-black/[0.03] px-3 py-2"><p className="text-[10px] text-[var(--muted-text)]">{language === 'zh' ? '\u5bbf\u4e3b CPU' : 'Host CPU'}</p><p className="mt-1 text-sm font-bold text-[var(--app-text)]">{hostResources?.cpu_percent == null ? '--' : `${Math.round(hostResources.cpu_percent)}%`}</p></div>
           <div className="rounded-xl bg-black/[0.03] px-3 py-2"><p className="text-[10px] text-[var(--muted-text)]">{language === 'zh' ? '\u5bbf\u4e3b\u5185\u5b58' : 'Host memory'}</p><p className="mt-1 text-sm font-bold text-[var(--app-text)]">{hostResources?.memory_percent == null ? '--' : `${Math.round(hostResources.memory_percent)}%`}</p></div>
           <div className="rounded-xl bg-black/[0.03] px-3 py-2"><p className="text-[10px] text-[var(--muted-text)]">{language === 'zh' ? 'Worker 槽位' : 'Worker slots'}</p><p className="mt-1 text-sm font-bold text-[var(--app-text)]">{workerRunningCount || '--'}</p></div>
           <div className="rounded-xl bg-black/[0.03] px-3 py-2"><p className="text-[10px] text-[var(--muted-text)]">{language === 'zh' ? 'WebSocket 会话' : 'WebSocket sessions'}</p><p className="mt-1 text-sm font-bold text-[var(--app-text)]">{platformHealth?.websocket?.active_sessions ?? '--'}</p></div>
           <div className="rounded-xl bg-black/[0.03] px-3 py-2"><p className="text-[10px] text-[var(--muted-text)]">{language === 'zh' ? 'Redis' : 'Redis'}</p><p className={`mt-1 text-sm font-bold ${platformHealth?.redis?.status === 'not_configured' ? 'text-slate-500' : 'text-amber-600'}`}>{platformHealth?.redis?.status || '--'}</p></div>
         </div>
         {collectionDrilldownOpen && (
          <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50/50 p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[10px] font-bold uppercase tracking-wider text-amber-700">{language === 'zh' ? '采集异常明细' : 'Collection anomaly details'}</span>
              <button type="button" onClick={() => setCollectionDrilldownOpen(false)} className="rounded-lg px-2 py-1 text-[10px] font-semibold text-[var(--muted-text)] hover:bg-white/70">{language === 'zh' ? '收起' : 'Collapse'}</button>
            </div>
            {collectionDrilldownLoading ? <p className="mt-2 text-[11px] text-[var(--muted-text)]">{language === 'zh' ? '正在加载采集状态…' : 'Loading collection status…'}</p> : (
              <div className="mt-2 max-h-36 space-y-1.5 overflow-auto">
                {collectionStatusItems.filter((item) => !['healthy', 'success', 'ok'].includes(String(item.effective_status || item.status || '').toLowerCase())).slice(0, 20).map((item, index) => (
                  <div key={`${item.device_id || item.collector || 'item'}-${index}`} className="flex items-center justify-between gap-2 rounded-lg bg-white/70 px-2.5 py-1.5 text-[10px]">
                    <span className="truncate font-semibold text-[var(--app-text)]">{item.hostname || item.device_id || item.collector || '--'}</span>
                    <span className="shrink-0 font-bold text-amber-700">{item.effective_status || item.status || 'unknown'}</span>
                  </div>
                ))}
                {!collectionStatusItems.some((item) => !['healthy', 'success', 'ok'].includes(String(item.effective_status || item.status || '').toLowerCase())) && <p className="py-2 text-center text-[11px] text-emerald-700">{language === 'zh' ? '当前没有独立采集异常。' : 'No independent collection anomalies.'}</p>}
              </div>
            )}
          </div>
        )}
      </section>

       <section className="ops-surface rounded-2xl p-5">
         <div className="flex flex-wrap items-start justify-between gap-3">
           <div>
             <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-violet-600">{language === 'zh' ? '\u5065\u5eb7\u8d8b\u52bf' : 'Health trend'}</p>
             <h3 className="mt-1 text-lg font-bold text-[var(--app-text)]">{language === 'zh' ? '\u5168\u7f51\u5065\u5eb7\u8d8b\u52bf' : 'Fleet health trend'}</h3>
             <p className="text-xs text-[var(--muted-text)]">{language === 'zh' ? '\u4ee5\u91c7\u96c6\u5feb\u7167\u5c55\u793a\u5728\u7ebf\u7387\u548c\u91c7\u96c6\u6210\u529f\u7387\uff0c\u672a\u77e5\u6570\u636e\u4e0d\u4f1a\u88ab\u5f53\u4f5c\u5065\u5eb7\u3002' : 'Snapshot-based availability and collection success; unknown data is not counted as healthy.'}</p>
             <p className="mt-1 text-[10px] text-[var(--muted-text)]">{language === 'zh' ? ('\u65f6\u95f4\u8303\u56f4\uff1a' + (healthHistoryRange === 1 ? '1\u5c0f\u65f6' : healthHistoryRange === 24 ? '24\u5c0f\u65f6' : '7\u5929') + ' \u00b7 \u91c7\u6837\u70b9\uff1a' + (monitorHealthHistory?.sample_count ?? 0)) : ('Range: ' + (healthHistoryRange === 168 ? '7 days' : healthHistoryRange + ' hours') + ' · Samples: ' + (monitorHealthHistory?.sample_count ?? 0))}</p>
           </div>
           <div className="flex items-center gap-1.5">
              <div className="flex items-center gap-1 rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] p-0.5">
                {([1, 24, 168] as const).map((hours) => (
                  <button key={hours} type="button" onClick={() => { setHealthHistoryRange(hours); fetchMonitoringHealthHistory(hours); }} className={`rounded-md px-2 py-1 text-[10px] font-semibold ${healthHistoryRange === hours ? 'bg-sky-100 text-sky-700' : 'text-[var(--muted-text)] hover:bg-black/[0.03]'}`}>
                    {hours === 1 ? '1h' : hours === 24 ? '24h' : '7d'}
                  </button>
                ))}
              </div>
              <button type="button" onClick={() => fetchMonitoringHealthHistory(healthHistoryRange)} className="inline-flex items-center gap-1 rounded-lg border border-[var(--card-border)] px-2.5 py-1 text-[10px] font-semibold text-sky-700 hover:border-sky-300 hover:bg-sky-50">
                <RefreshCw size={11} />{language === 'zh' ? '\u5237\u65b0\u8d8b\u52bf' : 'Refresh'}
              </button>
            </div>
         </div>
         <div className="mt-3 grid grid-cols-3 gap-2">
           {[
             [language === 'zh' ? '\u65b0\u589e\u544a\u8b66' : 'New alerts', monitorHealthHistory?.new_alerts ?? 0, 'text-rose-600'],
             [language === 'zh' ? '\u5df2\u6062\u590d' : 'Recovered', monitorHealthHistory?.recovered_alerts ?? 0, 'text-emerald-600'],
             [language === 'zh' ? '\u5e73\u5747\u6062\u590d\u65f6\u95f4' : 'Avg MTTR', monitorHealthHistory?.avg_mttr_minutes == null ? '--' : `${monitorHealthHistory.avg_mttr_minutes}m`, 'text-amber-600'],
           ].map(([label, value, tone]) => (
             <div key={String(label)} className="rounded-xl border border-[var(--card-border)] bg-black/[0.015] px-3 py-2">
               <p className="text-[10px] text-[var(--muted-text)]">{label}</p>
               <p className={`mt-1 text-sm font-bold ${tone}`}>{value}</p>
             </div>
           ))}
         </div>
         <div className="mt-3 h-44 rounded-xl border border-[var(--card-border)] bg-black/[0.015] p-2">
           {healthHistoryData.length > 0 ? (
             <ResponsiveContainer width="100%" height="100%">
               <AreaChart data={healthHistoryData} margin={{ top: 8, right: 12, left: -16, bottom: 0 }}>
                 <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} vertical={false} />
                 <XAxis dataKey="time" tickLine={false} axisLine={false} tick={{ fontSize: 10, fill: ct.axisAlt }} minTickGap={36} />
                 <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tickFormatter={(value) => `${value}%`} tickLine={false} axisLine={false} tick={{ fontSize: 10, fill: ct.axisAlt }} width={34} />
                 <Tooltip contentStyle={{ borderRadius: 12, border: `1px solid ${ct.grid}`, background: 'var(--card-bg)', fontSize: 11 }} formatter={(value: any, name: any) => [`${Number(value || 0).toFixed(1)}%`, String(name)]} />
                 <Area type="monotone" dataKey="online_rate" name={language === 'zh' ? '\u5728\u7ebf\u7387' : 'Online rate'} stroke="#0ea5e9" fill="#0ea5e920" strokeWidth={2} isAnimationActive={false} connectNulls />
                 <Area type="monotone" dataKey="collection_success_rate" name={language === 'zh' ? '\u91c7\u96c6\u6210\u529f\u7387' : 'Collection success'} stroke="#8b5cf6" fill="none" strokeWidth={2} isAnimationActive={false} connectNulls />
               </AreaChart>
             </ResponsiveContainer>
           ) : (
             <div className="flex h-full items-center justify-center gap-2 text-sm text-[var(--muted-text)]"><BarChart3 size={20} className="opacity-50" />{language === 'zh' ? '\u6682\u65e0\u5065\u5eb7\u8d8b\u52bf\u6570\u636e' : 'No health samples yet'}</div>
           )}
          </div>
          <div className="mt-3 rounded-xl border border-[var(--card-border)] bg-black/[0.015] p-3">
            <div className="mb-1 flex items-center justify-between gap-2">
              <span className="text-[10px] font-bold uppercase tracking-wider text-rose-600">{language === 'zh' ? '\u544a\u8b66\u8d8b\u52bf' : 'Alert trend'}</span>
              <span className="text-[10px] text-[var(--muted-text)]">{language === 'zh' ? '\u6d3b\u8dc3 / \u4e25\u91cd' : 'open / critical'}</span>
            </div>
            <div className="h-28">
              {healthHistoryData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={healthHistoryData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} vertical={false} />
                    <XAxis dataKey="time" tickLine={false} axisLine={false} tick={{ fontSize: 9, fill: ct.axisAlt }} minTickGap={32} />
                    <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fontSize: 9, fill: ct.axisAlt }} width={26} />
                    <Tooltip contentStyle={{ borderRadius: 10, border: `1px solid ${ct.grid}`, background: 'var(--card-bg)', fontSize: 10 }} />
                    <Area type="monotone" dataKey="open_alerts" name={language === 'zh' ? '\u6d3b\u8dc3\u544a\u8b66' : 'Open alerts'} stroke="#f97316" fill="#f9731620" strokeWidth={2} isAnimationActive={false} connectNulls />
                    <Area type="monotone" dataKey="critical_open_alerts" name={language === 'zh' ? '\u4e25\u91cd\u544a\u8b66' : 'Critical alerts'} stroke="#ef4444" fill="none" strokeWidth={2} isAnimationActive={false} connectNulls />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <div className="flex h-full items-center justify-center text-xs text-[var(--muted-text)]">{language === 'zh' ? '\u6682\u65e0\u544a\u8b66\u8d8b\u52bf\u6570\u636e' : 'No alert trend data'}</div>
              )}
            </div>
          </div>
        </section>

       {/* SECTION 2: MIDDLE - HEALTH + RISK */}
      <div className="grid grid-cols-1 xl:grid-cols-[1.15fr_0.85fr] gap-4">

        {/* LEFT: Fleet Health Distribution */}
        <div className="ops-surface rounded-2xl p-5 space-y-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-sky-600">{language === 'zh' ? '\u5168\u7f51\u5065\u5eb7' : 'Fleet Health'}</p>
              <h3 className="mt-1 text-lg font-bold text-[var(--app-text)]">{language === 'zh' ? '\u5065\u5eb7\u5206\u5e03\u603b\u89c8' : 'Health Distribution'}</h3>
              <p className="text-xs text-[var(--muted-text)]">{language === 'zh' ? '\u57fa\u4e8e\u8bbe\u5907\u72b6\u6001\u3001\u544a\u8b66\u548c\u5065\u5eb7\u8bc4\u5206\u7efc\u5408\u8ba1\u7b97\u3002' : 'Computed from device status, alerts, and health scores.'}</p>
              <p className="mt-1 text-[10px] text-[var(--muted-text)]">{lastCollectionAt ? (language === 'zh' ? `\u6700\u8fd1\u91c7\u96c6\uff1a${formatTs(lastCollectionAt, true)}` : `Last collection: ${formatTs(lastCollectionAt, true)}`) : (language === 'zh' ? '\u6682\u65e0\u91c7\u96c6\u6210\u529f\u8bb0\u5f55' : 'No successful collection recorded')}</p>
            </div>
            <div className="flex items-center gap-3">
              <div className="flex h-12 w-12 flex-col items-center justify-center rounded-2xl border border-sky-200 bg-sky-50 text-sky-700">
                <span className="text-lg font-extrabold leading-none">{healthPct == null ? '--' : `${healthPct}%`}</span>
                <span className="mt-1 text-[8px] font-bold uppercase tracking-wider">{language === 'zh' ? '\u5065\u5eb7\u8bc4\u4f30\u7387' : 'evaluable'}</span>
              </div>
              <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--muted-text)]">
                {language === 'zh' ? `${healthTotal} \u53f0\u8bbe\u5907 · ${healthEvaluableCount} \u53ef\u8bc4\u4f30` : `${healthTotal} devices · ${healthEvaluableCount} evaluable`}
              </span>
            </div>
          </div>

          {healthTotal > 0 && (
            <div className="flex h-5 w-full overflow-hidden rounded-full bg-black/[0.04]">
              {[
                { count: healthyCount, color: '#10b981' },
                { count: warningCount, color: '#f59e0b' },
                { count: criticalCount, color: '#ef4444' },
                { count: unknownCount, color: '#94a3b8' },
              ].map(({ count, color }) => (
                count > 0 ? (
                  <div key={color} className="flex items-center justify-center text-[9px] font-bold text-white transition-all duration-700" style={{ width: healthBarWidth(count), backgroundColor: color }}>{count}</div>
                ) : (
                  <div key={color} className="transition-all duration-700" style={{ width: '2px', backgroundColor: `${color}40` }} />
                )
              ))}
            </div>
          )}

          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <HealthSegment label={language === 'zh' ? '\u5065\u5eb7' : 'Healthy'} count={healthyCount} total={healthTotal} color="#10b981" onClick={() => openHealthDrilldown({ label: language === 'zh' ? '\u5065\u5eb7\u8bbe\u5907' : 'Healthy devices', health_status: 'healthy' })} />
            <HealthSegment label={language === 'zh' ? '\u544a\u8b66' : 'Warning'} count={warningCount} total={healthTotal} color="#f59e0b" onClick={() => openHealthDrilldown({ label: language === 'zh' ? '\u544a\u8b66\u8bbe\u5907' : 'Warning devices', health_status: 'warning' })} />
            <HealthSegment label={language === 'zh' ? '\u4e25\u91cd' : 'Critical'} count={criticalCount} total={healthTotal} color="#ef4444" onClick={() => openHealthDrilldown({ label: language === 'zh' ? '\u4e25\u91cd\u8bbe\u5907' : 'Critical devices', health_status: 'critical' })} />
            <HealthSegment label={language === 'zh' ? '\u672a\u77e5' : 'Unknown'} count={unknownCount} total={healthTotal} color="#94a3b8" onClick={() => openHealthDrilldown({ label: language === 'zh' ? '\u672a\u77e5\u8bbe\u5907' : 'Unknown devices', health_status: 'unknown' })} />
          </div>

          {healthDrilldownFilter && (
            <div className="rounded-xl border border-sky-200 bg-sky-50/50 p-3">
              <div className="flex items-center justify-between gap-2">
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-wider text-sky-700">{healthDrilldownFilter}</p>
                  <p className="mt-1 text-[11px] text-[var(--muted-text)]">{healthDrilldownLoading ? (language === 'zh' ? '\u6b63\u5728\u52a0\u8f7d\u4e0b\u94bb\u7ed3\u679c\u2026' : 'Loading drilldown…') : `${healthDrilldownItems.length} ${language === 'zh' ? '\u53f0\u8bbe\u5907' : 'devices'}`}</p>
                </div>
                <button type="button" onClick={() => setHealthDrilldownFilter(null)} className="rounded-lg px-2 py-1 text-[10px] font-semibold text-[var(--muted-text)] hover:bg-white/70">{language === 'zh' ? '\u6536\u8d77' : 'Collapse'}</button>
              </div>
              {!healthDrilldownLoading && (
                <div className="mt-2 max-h-44 space-y-1.5 overflow-auto">
                  {healthDrilldownItems.map((item) => (
                    <button key={item.id} type="button" onClick={() => openMonitorDevice(item)} className="flex w-full items-center justify-between gap-2 rounded-lg bg-white/75 px-2.5 py-2 text-left text-[10px] hover:bg-white">
                      <span className="min-w-0 truncate font-semibold text-[var(--app-text)]">{item.hostname || item.ip_address || item.id}</span>
                      <span className="shrink-0 text-[var(--muted-text)]">{item.health_status || 'unknown'} · {item.collection_status || 'unknown'}</span>
                    </button>
                  ))}
                  {!healthDrilldownItems.length && <p className="py-2 text-center text-[11px] text-[var(--muted-text)]">{language === 'zh' ? '\u6ca1\u6709\u5339\u914d\u8bbe\u5907' : 'No matching devices'}</p>}
                </div>
              )}
            </div>
          )}

          {/* Host resource telemetry is now shown under Server Monitoring. */}
          {false && hostResources && (
            <div className="flex items-center justify-between rounded-xl border border-[var(--card-border)] bg-black/[0.015] px-5 py-3">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-[var(--muted-text)]">{language === 'zh' ? `${systemInfo?.system_name || 'Nexora'} 宿主机` : `${systemInfo?.system_name || 'Nexora'} Host`}</p>
                <div className="flex items-center gap-2 mt-0.5">
                  <p className="text-xs text-[var(--app-text)] font-medium">{hostResources.hostname || '--'}</p>
                  <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider ${hostResources.status === 'critical' ? 'bg-red-100 text-red-700' : hostResources.status === 'degraded' ? 'bg-amber-100 text-amber-700' : 'bg-emerald-100 text-emerald-700'}`}>
                    <span className={`h-1.5 w-1.5 rounded-full ${hostResources.status === 'critical' ? 'bg-red-500' : hostResources.status === 'degraded' ? 'bg-amber-500' : 'bg-emerald-500'}`} />
                    {hostResources.status}
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-5">
                <MiniGauge value={hostResources.cpu_percent} label="CPU" />
                <MiniGauge value={hostResources.memory_percent} label={language === 'zh' ? '内存' : 'MEM'} />
                <MiniGauge value={hostResources.disk_percent} label={language === 'zh' ? '磁盘' : 'DISK'} />
              </div>
            </div>
          )}
        </div>

        {/* RIGHT: TOP IMPACTED DEVICES */}
        <div className="ops-surface rounded-2xl p-5 space-y-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-red-600">{language === 'zh' ? '\u5f71\u54cd\u6700\u5927' : 'Most Impacted'}</p>
              <h3 className="mt-1 text-lg font-bold text-[var(--app-text)]">{language === 'zh' ? 'Top \u5f71\u54cd\u8bbe\u5907' : 'Top Impacted Devices'}</h3>
              <p className="text-xs text-[var(--muted-text)]">{language === 'zh' ? '\u79bb\u7ebf\u8bbe\u5907\u4f18\u5148\u6392\u5217\uff0c\u5176\u6b21\u6309\u5065\u5eb7\u5206\u5347\u5e8f\u3002' : 'Offline first, then by health score ascending.'}</p>
            </div>
            <span className="rounded-full bg-red-100 px-2.5 py-1 text-[10px] font-bold uppercase text-red-700">
              {riskyDevices.length} {language === 'zh' ? '\u53f0' : 'devices'}
            </span>
          </div>
          <div className="space-y-2 max-h-[380px] overflow-auto pr-1">
            {riskyDevices.length > 0
              ? riskyDevices.slice(0, impactedShowAll ? riskyDevices.length : 5).map((device: any, idx: number) => (
                <div key={device.id} className="group">
                  <RiskDeviceRow device={device} language={language} index={idx} onClick={() => openMonitorDevice(device)} />
                  {/* Quick Action Buttons */}
                  <div className="flex items-center gap-1.5 mt-1 ml-9 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button type="button" onClick={(e) => { e.stopPropagation(); navigate('/automation/execute'); }} className="inline-flex items-center gap-1 rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-1 text-[10px] font-semibold text-[var(--muted-text)] hover:border-sky-300 hover:bg-sky-50 hover:text-sky-700 transition-all">
                      <Terminal size={10} />SSH
                    </button>
                    <button type="button" onClick={(e) => { e.stopPropagation(); navigate('/automation/execute'); }} className="inline-flex items-center gap-1 rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-1 text-[10px] font-semibold text-[var(--muted-text)] hover:border-emerald-300 hover:bg-emerald-50 hover:text-emerald-700 transition-all">
                      <Play size={10} />{language === 'zh' ? '\u6267\u884c' : 'Script'}
                    </button>
                    <button type="button" onClick={(e) => { e.stopPropagation(); navigate('/configs'); }} className="inline-flex items-center gap-1 rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-1 text-[10px] font-semibold text-[var(--muted-text)] hover:border-amber-300 hover:bg-amber-50 hover:text-amber-700 transition-all">
                      <Download size={10} />{language === 'zh' ? '\u5907\u4efd' : 'Backup'}
                    </button>
                  </div>
                </div>
              ))
              : <div className="rounded-xl border border-dashed border-[var(--card-border)] p-8 text-center text-sm text-[var(--muted-text)]">
                  <CheckCircle2 size={24} className="mx-auto mb-2 text-emerald-500" />
                  {language === 'zh' ? '\u5f53\u524d\u6ca1\u6709\u98ce\u9669\u8bbe\u5907\uff0c\u5168\u7f51\u5065\u5eb7\uff01' : 'No risky devices \u2014 fleet is healthy!'}
                </div>
            }
            {riskyDevices.length > 5 && (
              <button type="button" onClick={() => setImpactedShowAll(!impactedShowAll)} className="w-full rounded-xl border border-[var(--card-border)] bg-black/[0.015] px-3 py-2 text-xs font-semibold text-[var(--muted-text)] transition-all hover:border-black/20 hover:bg-black/[0.03]">
                {impactedShowAll
                  ? (language === 'zh' ? '\u6536\u8d77' : 'Show less')
                  : (language === 'zh' ? `\u67e5\u770b\u5168\u90e8 ${riskyDevices.length} \u53f0 \u2192` : `View all ${riskyDevices.length} devices \u2192`)}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* SECTION 3: BOTTOM - TRENDS + EVENTS */}
      <div className="grid grid-cols-1 xl:grid-cols-1 gap-4">

        {/* Host resource telemetry is now shown under Server Monitoring. */}
        {false && (
        /* LEFT: Performance Trends */
        <div className="ops-surface rounded-2xl p-5 space-y-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-sky-600">{language === 'zh' ? '\u6027\u80fd\u8d8b\u52bf' : 'Performance Trends'}</p>
              <h3 className="mt-1 text-lg font-bold text-[var(--app-text)]">{language === 'zh' ? 'CPU / \u5185\u5b58 / \u78c1\u76d8' : 'CPU / Memory / Disk'}</h3>
            </div>
            {/* Segmented range control */}
            <div className="inline-flex items-center gap-0.5 rounded-xl bg-black/[0.04] p-0.5">
              {([1, 24, 168] as const).map((h) => {
                const active = hostResourceRange === h;
                return (
                  <button
                    key={h}
                    type="button"
                    onClick={() => setHostResourceRange(h)}
                    className={`rounded-lg px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider transition-all tabular-nums ${
                      active
                        ? 'bg-white text-[var(--app-text)] shadow-sm'
                        : 'text-[var(--muted-text)] hover:text-[var(--app-text)]'
                    }`}
                  >
                    {h === 1 ? '1h' : h === 24 ? '24h' : '7d'}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="h-[220px] -mx-1">
            {hostTrendData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={hostTrendData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="cpuFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#0ea5e9" stopOpacity={0.28} />
                      <stop offset="100%" stopColor="#0ea5e9" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="memFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#f97316" stopOpacity={0.22} />
                      <stop offset="100%" stopColor="#f97316" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="diskFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#10b981" stopOpacity={0.18} />
                      <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid vertical={false} stroke={ct.gridAlt} strokeOpacity={0.45} />
                  <XAxis
                    dataKey="ts"
                    axisLine={false}
                    tickLine={false}
                    tick={{ fontSize: 10, fill: ct.axisAlt, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }}
                    tickFormatter={(value) => formatTs(String(value), hostResourceRange === 1)}
                    minTickGap={48}
                    padding={{ left: 4, right: 4 }}
                  />
                  <YAxis
                    axisLine={false}
                    tickLine={false}
                    tick={{ fontSize: 10, fill: ct.axisAlt }}
                    domain={[0, 100]}
                    ticks={[0, 25, 50, 75, 100]}
                    tickFormatter={(v) => `${v}%`}
                    width={36}
                  />
                  <Tooltip
                    contentStyle={{
                      borderRadius: 12,
                      border: '1px solid rgba(255,255,255,0.06)',
                      boxShadow: '0 12px 32px -12px rgba(15, 23, 42, 0.45)',
                      padding: '10px 12px',
                      background: 'rgba(15, 23, 42, 0.94)',
                      backdropFilter: 'blur(8px)',
                      color: '#f1f5f9',
                      fontSize: 12,
                    }}
                    itemStyle={{ color: '#f1f5f9', padding: '2px 0' }}
                    labelStyle={{ color: '#94a3b8', fontSize: 10, fontWeight: 700, marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.08em' }}
                    cursor={{ stroke: '#0ea5e9', strokeOpacity: 0.35, strokeWidth: 1, strokeDasharray: '3 3' }}
                    formatter={(value: any, name: any) => [`${Math.round(Number(value || 0))}%`, String(name)]}
                  />
                  <Area type="monotone" dataKey="cpu_percent" name="CPU" stroke="#0ea5e9" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" fill="url(#cpuFill)" isAnimationActive={false} connectNulls dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: '#ffffff' }} />
                  <Area type="monotone" dataKey="memory_percent" name={language === 'zh' ? '\u5185\u5b58' : 'Memory'} stroke="#f97316" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" fill="url(#memFill)" isAnimationActive={false} connectNulls dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: '#ffffff' }} />
                  <Area type="monotone" dataKey="disk_percent" name={language === 'zh' ? '\u78c1\u76d8' : 'Disk'} stroke="#10b981" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" fill="url(#diskFill)" isAnimationActive={false} connectNulls dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: '#ffffff' }} />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
                {hostResourceHistoryLoading ? (
                  <>
                    <RefreshCw size={20} className="animate-spin text-sky-400" />
                    <p className="text-sm text-[var(--muted-text)]">{language === 'zh' ? '正在加载趋势数据...' : 'Loading trend data...'}</p>
                  </>
                ) : (
                  <>
                    <BarChart3 size={28} className="text-[var(--muted-text)] opacity-40" />
                    <p className="text-sm font-medium text-[var(--muted-text)]">{language === 'zh' ? '暂无趋势数据' : 'No trend data yet'}</p>
                    <p className="max-w-[220px] text-[11px] text-[var(--muted-text)] opacity-60">{language === 'zh' ? '系统将在采集到足够数据后自动生成趋势图，请稍候。' : 'Trends will appear once enough data points have been collected.'}</p>
                    <button type="button" onClick={() => fetchHostResourceHistory(hostResourceRange)} className="mt-1 inline-flex items-center gap-1 rounded-lg border border-[var(--card-border)] px-3 py-1.5 text-[11px] font-semibold text-sky-600 transition-all hover:bg-sky-50 hover:border-sky-200">
                      <RefreshCw size={11} />{language === 'zh' ? '立即刷新' : 'Refresh now'}
                    </button>
                  </>
                )}
              </div>
            )}
          </div>

          {/* Inline metric strip — current values, color-keyed to chart series */}
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[11px] tabular-nums">
            {[
              { key: 'cpu', label: 'CPU', color: '#0ea5e9', value: hostResources?.cpu_percent },
              { key: 'mem', label: language === 'zh' ? '\u5185\u5b58' : 'MEM', color: '#f97316', value: hostResources?.memory_percent },
              { key: 'disk', label: language === 'zh' ? '\u78c1\u76d8' : 'DISK', color: '#10b981', value: hostResources?.disk_percent },
            ].map((m) => (
              <span key={m.key} className="inline-flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: m.color, boxShadow: `0 0 0 3px ${m.color}1f` }} />
                <span className="font-semibold text-[var(--muted-text)]">{m.label}</span>
                <span className="font-bold text-[var(--app-text)]">{m.value != null ? `${Math.round(m.value)}%` : '--'}</span>
              </span>
            ))}
            <span className="ml-auto text-[10px] text-[var(--muted-text)] opacity-70">
              {hostResourceHistoryLoading ? '...' : `${hostResourceHistory?.sample_count || hostTrendData.length} pts \u00b7 ${hostResourceHistory?.resolution_hint || '1m'}`}
            </span>
          </div>

          {/* Status pills — system health at a glance */}
          <div className="flex flex-wrap items-center gap-2 text-[11px] tabular-nums">
            <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-semibold ${hostResources?.database_ok ? 'bg-emerald-500/10 text-emerald-700' : 'bg-red-500/10 text-red-700'}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${hostResources?.database_ok ? 'bg-emerald-500' : 'bg-red-500'} ${hostResources?.database_ok ? '' : 'animate-pulse'}`} />
              DB {hostResources?.database_ok ? 'OK' : 'ERR'}
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-black/[0.04] px-2.5 py-1 text-[var(--muted-text)]">
              <span className="font-semibold opacity-70">Load</span>
              <span className="font-bold text-[var(--app-text)]">{hostResources?.load_1m?.toFixed(2) ?? '--'}</span>
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-black/[0.04] px-2.5 py-1 text-[var(--muted-text)]">
              <span className="font-semibold opacity-70">Up</span>
              <span className="font-bold text-[var(--app-text)]">{hostResources?.uptime_hours != null ? `${hostResources.uptime_hours.toFixed(0)}h` : '--'}</span>
            </span>
          </div>
        </div>
        )}

        {/* RIGHT: Real-time Event Stream */}
        <div className="ops-surface rounded-2xl p-5 space-y-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-red-600">{language === 'zh' ? '\u4e8b\u4ef6\u6d41' : 'Event Feed'}</p>
              <h3 className="mt-1 text-lg font-bold text-[var(--app-text)]">{language === 'zh' ? '\u6700\u8fd1\u544a\u8b66 / \u4e8b\u4ef6' : 'Recent Alerts & Events'}</h3>
            </div>
            <div className="flex items-center gap-2">
              <select value={monitorDashboardSiteFilter} onChange={(e) => setMonitorDashboardSiteFilter(e.target.value)} className="rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-1 text-[11px] outline-none text-[var(--app-text)]" title={language === 'zh' ? '\u6309\u7ad9\u70b9' : 'By site'}>
                <option value="all">{language === 'zh' ? '\u5168\u90e8\u7ad9\u70b9' : 'All Sites'}</option>
                {dashboardSiteOptions.map((site: string) => <option key={site} value={site}>{site}</option>)}
              </select>
              <select value={monitorDashboardAlertFilter} onChange={(e) => setMonitorDashboardAlertFilter(e.target.value as any)} className="rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-1 text-[11px] outline-none text-[var(--app-text)]" title={language === 'zh' ? '\u6309\u7ea7\u522b' : 'By severity'}>
                <option value="all">{language === 'zh' ? '\u5168\u90e8' : 'All'}</option>
                <option value="critical">{language === 'zh' ? '\u4e25\u91cd' : 'Critical'}</option>
                <option value="major">{language === 'zh' ? '\u4e3b\u8981' : 'Major'}</option>
                <option value="warning">{language === 'zh' ? '\u6b21\u8981' : 'Minor'}</option>
              </select>
            </div>
          </div>

          <div className="space-y-0.5 max-h-[280px] overflow-auto rounded-xl border border-[var(--card-border)] bg-black/[0.01] p-1">
            {groupedOpenAlerts.length > 0
              ? groupedOpenAlerts.slice(0, 30).map((alert: any) => (
                <div key={alert.id} className="relative">
                  <EventStreamItem alert={alert} language={language} onClick={() => openMonitorDevice(alert)} formatTs={formatTs} />
                  {alert._groupCount > 1 && (
                    <span className="absolute top-1.5 right-16 rounded-full bg-slate-200 px-1.5 py-0.5 text-[9px] font-bold text-slate-600">×{alert._groupCount}</span>
                  )}
                </div>
              ))
              : <div className="flex h-32 items-center justify-center text-sm text-[var(--muted-text)]">
                  <CheckCircle2 size={18} className="mr-2 text-emerald-500" />
                  {language === 'zh' ? '当前无活跃告警，一切正常。' : 'No active alerts — all clear.'}
                </div>
            }
          </div>

          <div className="flex flex-wrap gap-2 text-[10px] font-bold uppercase tracking-wider">
            <span className="rounded-full bg-red-100 px-2.5 py-1 text-red-700">{language === 'zh' ? '\u4e25\u91cd' : 'CRIT'} {filteredOpenAlerts.filter((a: any) => String(a.severity || '').toLowerCase() === 'critical').length}</span>
            <span className="rounded-full bg-orange-100 px-2.5 py-1 text-orange-700">{language === 'zh' ? '\u4e3b\u8981' : 'MAJOR'} {filteredOpenAlerts.filter((a: any) => String(a.severity || '').toLowerCase() === 'major').length}</span>
            <span className="rounded-full bg-amber-100 px-2.5 py-1 text-amber-700">{language === 'zh' ? '\u6b21\u8981' : 'WARN'} {filteredOpenAlerts.filter((a: any) => String(a.severity || '').toLowerCase() === 'warning').length}</span>
          </div>
          <button type="button" onClick={() => navigate('/alerts')} className="w-full rounded-xl border border-[var(--card-border)] bg-black/[0.015] px-4 py-2 text-xs font-semibold text-[var(--muted-text)] transition-all hover:border-red-300 hover:bg-red-50 hover:text-red-700">
            {language === 'zh' ? '\u6253\u5f00\u544a\u8b66\u4e2d\u5fc3\u67e5\u770b\u5168\u90e8 \u2192' : 'Open Alert Center for full view \u2192'}
          </button>
        </div>
      </div>


      </div>

      </div>
      {selectedIncident && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/30 p-4 backdrop-blur-[2px]" role="dialog" aria-modal="true" aria-label={language === 'zh' ? '事件详情' : 'Incident detail'}>
          <div className="w-full max-w-2xl rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-5 shadow-2xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-rose-600">{selectedIncident.incident_key}</p>
                <h3 className="mt-1 text-lg font-bold text-[var(--app-text)]">{selectedIncident.title}</h3>
                <p className="mt-1 text-xs text-[var(--muted-text)]">{selectedIncident.summary || '--'}</p>
              </div>
              <button type="button" onClick={() => setSelectedIncident(null)} className="rounded-lg px-2 py-1 text-lg text-[var(--muted-text)] hover:bg-black/5" aria-label={language === 'zh' ? '关闭' : 'Close'}>×</button>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {[
                [language === 'zh' ? '严重级别' : 'Severity', selectedIncident.severity],
                [language === 'zh' ? '状态' : 'Status', selectedIncident.status],
                [language === 'zh' ? '影响设备' : 'Devices', selectedIncident.impact_device_count],
                [language === 'zh' ? '关联告警' : 'Alerts', selectedIncident.impact_alert_count],
              ].map(([label, value]) => <div key={String(label)} className="rounded-xl bg-black/[0.03] px-3 py-2"><p className="text-[10px] text-[var(--muted-text)]">{label}</p><p className="mt-1 text-sm font-bold text-[var(--app-text)]">{value}</p></div>)}
            </div>
            <div className="mt-4 max-h-56 space-y-1.5 overflow-auto rounded-xl border border-[var(--card-border)] p-2">
              {incidentDetailLoading ? <p className="p-4 text-center text-xs text-[var(--muted-text)]">{language === 'zh' ? '正在加载事件时间线…' : 'Loading incident timeline…'}</p> : (selectedIncident.timeline || selectedIncident.alerts || []).map((alert: any) => (
                  <div key={`${alert.event_type || 'alert'}-${alert.id}`} className="rounded-lg bg-black/[0.025] px-3 py-2">
                    <div className="flex items-center justify-between gap-2"><span className="text-xs font-semibold text-[var(--app-text)]">{alert.event_type && alert.event_type !== 'alert' ? alert.event_type : (alert.title || alert.message)}</span><span className="text-[10px] text-[var(--muted-text)]">{formatTs(alert.created_at, true)}</span></div>
                  <p className="mt-0.5 text-[10px] text-[var(--muted-text)]">{alert.message || '--'} · {alert.severity || 'warning'}</p>
                </div>
              ))}
            </div>
            <div className="mt-3 rounded-xl border border-[var(--card-border)] bg-sky-50/50 p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] font-bold uppercase tracking-wider text-sky-700">{language === 'zh' ? '拓扑影响范围' : 'Topology impact'}</span>
                {incidentImpact && <span className="text-[10px] font-semibold text-[var(--muted-text)]">{incidentImpact.summary.affected_devices} {language === 'zh' ? '台受影响设备' : 'affected devices'} · {incidentImpact.summary.related_links} {language === 'zh' ? '条关联链路' : 'related links'}</span>}
              </div>
              {incidentImpactLoading ? <p className="mt-2 text-[11px] text-[var(--muted-text)]">{language === 'zh' ? '正在加载拓扑关系…' : 'Loading topology impact…'}</p> : incidentImpact?.links.length ? (
                <div className="mt-2 space-y-1.5">
                  {incidentImpact.links.slice(0, 4).map((link) => <div key={link.id} className="flex items-center justify-between gap-2 rounded-lg bg-white/70 px-2.5 py-1.5 text-[10px] text-[var(--muted-text)]"><span className="truncate font-semibold text-[var(--app-text)]">{link.source_hostname || link.source_device_id || '--'} → {link.target_hostname || link.target_device_id || '--'}</span><span className="shrink-0">{link.status || '--'} · {link.confidence != null ? `${Math.round(link.confidence * 100)}%` : '--'}</span></div>)}
                </div>
              ) : <p className="mt-2 text-[11px] text-[var(--muted-text)]">{language === 'zh' ? '暂无可用拓扑链路，影响范围以事件关联设备为准。' : 'No topology links are available; scope is based on incident devices.'}</p>}
            </div>
            {incidentImpact?.inference && (
              <div className="mt-3 rounded-xl border border-violet-200 bg-violet-50/50 p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-violet-700">{language === 'zh' ? '根因推断依据' : 'Root-cause inference'}</span>
                  <span className="rounded-full bg-white/80 px-2 py-0.5 text-[10px] font-bold text-violet-700">{incidentImpact.inference.confidence}</span>
                </div>
                <div className="mt-2 space-y-1 text-[10px] text-[var(--muted-text)]">
                  {incidentImpact.inference.candidate_hostname && <p className="font-semibold text-violet-800">{language === 'zh' ? '自动根因候选：' : 'Automatic root-cause candidate: '}{incidentImpact.inference.candidate_hostname}{incidentImpact.inference.candidate_score != null ? ` · ${incidentImpact.inference.candidate_score}` : ''}</p>}
                  {incidentImpact.inference.evidence.map((evidence) => <p key={evidence}>• {evidence}</p>)}
                  <p className="text-violet-700">{language === 'zh' ? '该结论仅基于当前证据，需由运维人员确认。' : incidentImpact.inference.disclaimer}</p>
                </div>
              </div>
            )}
            {incidentImpact?.business_impact && (
              <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50/70 p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-slate-700">{language === 'zh' ? '业务影响' : 'Business impact'}</span>
                  <span className="text-[10px] font-semibold text-slate-500">{incidentImpact.business_impact.confidence}</span>
                </div>
                <p className="mt-1 text-[10px] text-[var(--muted-text)]">{incidentImpact.business_impact.sites.length ? incidentImpact.business_impact.sites.join(' · ') : (language === 'zh' ? '暂无站点业务映射' : 'No site mapping')}</p>
                {incidentImpact.business_impact.services.length > 0 && <p className="mt-1 text-[10px] text-[var(--muted-text)]">{language === 'zh' ? '业务系统：' : 'Services: '}{incidentImpact.business_impact.services.join(' · ')}</p>}
                {incidentImpact.business_impact.owners?.length ? <p className="mt-1 text-[10px] text-[var(--muted-text)]">{language === 'zh' ? '业务负责人：' : 'Owners: '}{incidentImpact.business_impact.owners.join(' · ')}</p> : null}
                {incidentImpact.business_impact.contacts?.length ? <p className="mt-1 text-[10px] text-[var(--muted-text)]">{language === 'zh' ? '站点联系人：' : 'Contacts: '}{incidentImpact.business_impact.contacts.map((contact) => contact.name || contact.email || contact.phone).filter(Boolean).join(' · ')}</p> : null}
                {incidentImpact.business_impact.data_gaps.map((gap) => <p key={gap} className="mt-1 text-[10px] text-amber-700">{gap}</p>)}
              </div>
            )}
            <div className="mt-3 rounded-xl border border-[var(--card-border)] bg-amber-50/50 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-wider text-amber-700">{language === 'zh' ? '采集链路诊断' : 'Collection diagnostics'}</p>
                  <p className="mt-1 text-[11px] text-[var(--muted-text)]">{language === 'zh' ? '检查设备到采集器的连通性、凭据和最近采集状态。' : 'Check connectivity, credentials, and recent collector state.'}</p>
                </div>
                <button type="button" disabled={!selectedIncident.primary_device_id || incidentDiagnosticsLoading} onClick={runIncidentDiagnostics} className="inline-flex items-center gap-1.5 rounded-lg border border-amber-200 bg-amber-100 px-2.5 py-1.5 text-[11px] font-semibold text-amber-800 disabled:cursor-not-allowed disabled:opacity-50">
                  <Activity size={12} className={incidentDiagnosticsLoading ? 'animate-pulse' : ''} />
                  {incidentDiagnosticsLoading ? (language === 'zh' ? '诊断中…' : 'Diagnosing…') : (language === 'zh' ? '立即诊断' : 'Run diagnostics')}
                </button>
              </div>
              {incidentDiagnostics && (
                <div className="mt-2 space-y-1.5 text-[10px]">
                  {Object.entries(incidentDiagnostics.checks || {}).map(([checkName, checkValue]: [string, any]) => (
                    <div key={checkName} className="flex items-center justify-between gap-2 rounded-lg bg-white/70 px-2.5 py-1.5">
                      <span className="font-semibold text-[var(--app-text)]">{checkName}</span>
                      <span className={`shrink-0 font-bold ${checkValue?.status === 'success' ? 'text-emerald-700' : checkValue?.status === 'skipped' || checkValue?.status === 'not_configured' ? 'text-slate-500' : 'text-rose-700'}`}>{checkValue?.status || '--'}</span>
                    </div>
                  ))}
                  <div className="rounded-lg bg-white/70 px-2.5 py-2"><span className="text-[var(--muted-text)]">{language === 'zh' ? '结果' : 'Result'}</span><p className={`mt-0.5 font-bold ${incidentDiagnostics.status === 'success' ? 'text-emerald-700' : 'text-rose-700'}`}>{incidentDiagnostics.status || '--'}</p></div>
                  <div className="rounded-lg bg-white/70 px-2.5 py-2"><span className="text-[var(--muted-text)]">{language === 'zh' ? '诊断项' : 'Checks'}</span><p className="mt-0.5 font-bold text-[var(--app-text)]">{Array.isArray(incidentDiagnostics.checks) ? incidentDiagnostics.checks.length : '--'}</p></div>
                  <p className="col-span-2 truncate text-[var(--muted-text)]" title={incidentDiagnostics.message || incidentDiagnostics.summary || ''}>{incidentDiagnostics.message || incidentDiagnostics.summary || (language === 'zh' ? '已返回诊断结果' : 'Diagnostic result returned')}</p>
                </div>
              )}
            </div>
            <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50/50 p-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-wider text-emerald-700">{language === 'zh' ? '平台感知 Playbook 建议' : 'Platform-aware Playbook recommendations'}</p>
                  <p className="mt-1 text-[11px] text-[var(--muted-text)]">{language === 'zh' ? '仅展示与设备平台匹配、没有配置执行阶段的只读检查。配置变更仍需工单审批。' : 'Only platform-compatible read-only checks are shown. Configuration changes still require an approved work order.'}</p>
                </div>
                {incidentRecommendations?.device?.platform && <span className="shrink-0 rounded-full bg-white/80 px-2 py-1 text-[10px] font-bold text-emerald-700">{incidentRecommendations.device.platform}</span>}
              </div>
              {incidentRecommendationsLoading ? <p className="mt-2 text-[11px] text-[var(--muted-text)]">{language === 'zh' ? '正在匹配平台与厂商…' : 'Matching vendor and platform…'}</p> : incidentRecommendations?.items?.length ? (
                <div className="mt-2 space-y-1.5">
                  {incidentRecommendations.items.slice(0, 3).map((recommendation) => (
                    <div key={recommendation.scenario_id} className="flex items-start justify-between gap-2 rounded-lg bg-white/75 px-2.5 py-2">
                      <div className="min-w-0">
                        <p className="truncate text-[11px] font-bold text-[var(--app-text)]">{language === 'zh' ? (recommendation.name_zh || recommendation.name) : recommendation.name}</p>
                        <p className="mt-0.5 text-[10px] text-[var(--muted-text)]">{recommendation.command_count} {language === 'zh' ? '条只读检查命令' : 'read-only checks'} · {recommendation.reason}</p>
                      </div>
                      <div className="flex shrink-0 items-center gap-1.5">
                        <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[9px] font-bold text-emerald-700">{language === 'zh' ? '只读' : 'READ ONLY'}</span>
                        {recommendation.manual_execution_allowed && <button type="button" disabled={incidentPlaybookRunning !== null} onClick={() => runIncidentPlaybook(recommendation.scenario_id)} className="rounded-lg border border-emerald-200 bg-white px-2 py-1 text-[10px] font-semibold text-emerald-700 hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-50">{incidentPlaybookRunning === recommendation.scenario_id ? (language === 'zh' ? '启动中' : 'Starting') : (language === 'zh' ? '执行检查' : 'Run check')}</button>}
                      </div>
                    </div>
                  ))}
                </div>
              ) : <p className="mt-2 text-[11px] text-[var(--muted-text)]">{incidentRecommendations?.message || (language === 'zh' ? '当前平台暂无安全只读 Playbook，建议先执行采集诊断。' : 'No safe read-only Playbook is available for this platform; run collection diagnostics first.')}</p>}
            </div>
            {selectedIncident.work_orders?.length ? (
              <div className="mt-3 rounded-xl border border-indigo-200 bg-indigo-50/50 p-3">
                <p className="text-[10px] font-bold uppercase tracking-wider text-indigo-700">{language === 'zh' ? '关联工单' : 'Linked work orders'}</p>
                <div className="mt-2 space-y-1.5">
                  {selectedIncident.work_orders.map((order) => (
                    <button key={order.id} type="button" onClick={() => navigate(`/change-orders/all?order_id=${encodeURIComponent(order.id)}`)} className="flex w-full items-center justify-between gap-2 rounded-lg bg-white/80 px-2.5 py-1.5 text-left text-[10px] hover:bg-white">
                      <span className="truncate font-semibold text-[var(--app-text)]">{order.order_number} · {order.title}</span>
                      <span className="shrink-0 font-bold text-indigo-700">{order.status}</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
            <div className="mt-4 rounded-xl border border-[var(--card-border)] bg-black/[0.02] p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="mr-auto text-[10px] font-bold uppercase tracking-wider text-[var(--muted-text)]">{language === 'zh' ? '处置操作' : 'Response actions'}</span>
                <button type="button" disabled={incidentMutationLoading || selectedIncident.status === 'acknowledged'} onClick={() => mutateIncident('acknowledge', { status: 'acknowledged' })} className="rounded-lg border border-sky-200 bg-sky-50 px-2.5 py-1.5 text-[11px] font-semibold text-sky-700 disabled:cursor-not-allowed disabled:opacity-50">{language === 'zh' ? '确认' : 'Acknowledge'}</button>
                <button type="button" disabled={incidentMutationLoading || selectedIncident.status === 'investigating'} onClick={() => mutateIncident('acknowledge', { status: 'investigating' })} className="rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-[11px] font-semibold text-amber-700 disabled:cursor-not-allowed disabled:opacity-50">{language === 'zh' ? '调查中' : 'Investigate'}</button>
                <button type="button" disabled={incidentMutationLoading || selectedIncident.status === 'resolved'} onClick={() => { if (window.confirm(language === 'zh' ? '确认关闭该事件并同步关闭关联告警吗？' : 'Resolve this incident and its related alerts?')) mutateIncident('resolve', {}); }} className="rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-1.5 text-[11px] font-semibold text-emerald-700 disabled:cursor-not-allowed disabled:opacity-50">{language === 'zh' ? '关闭事件' : 'Resolve'}</button>
              </div>
              <div className="mt-3 flex items-center gap-2">
                <input value={incidentAssignee} onChange={(event) => setIncidentAssignee(event.target.value)} placeholder={language === 'zh' ? '输入负责人用户名' : 'Assignee username'} className="min-w-0 flex-1 rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-1.5 text-xs text-[var(--app-text)] outline-none focus:border-sky-300" />
                <button type="button" disabled={incidentMutationLoading || !incidentAssignee.trim()} onClick={() => mutateIncident('assign', { assignee: incidentAssignee.trim() })} className="rounded-lg border border-indigo-200 bg-indigo-50 px-2.5 py-1.5 text-[11px] font-semibold text-indigo-700 disabled:cursor-not-allowed disabled:opacity-50">{incidentMutationLoading ? (language === 'zh' ? '处理中…' : 'Updating…') : (language === 'zh' ? '分派' : 'Assign')}</button>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap justify-end gap-2">
              {selectedIncident.primary_device_id && <button type="button" onClick={() => { openMonitorDevice({ id: selectedIncident.primary_device_id, hostname: selectedIncident.hostname, ip_address: selectedIncident.ip_address }); setSelectedIncident(null); }} className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-1.5 text-xs font-semibold text-sky-700 hover:bg-sky-100">{language === 'zh' ? '查看设备' : 'View device'}</button>}
              <button type="button" onClick={() => navigate(`/change-orders/new?incident_id=${encodeURIComponent(selectedIncident.id)}`)} className="rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-xs font-semibold text-indigo-700 hover:bg-indigo-100">{language === 'zh' ? '\u521b\u5efa\u5de5\u5355' : 'Create work order'}</button>
              <button type="button" onClick={() => navigate('/alerts')} className="rounded-lg border border-[var(--card-border)] px-3 py-1.5 text-xs font-semibold text-[var(--muted-text)] hover:border-rose-300 hover:bg-rose-50 hover:text-rose-700">{language === 'zh' ? '打开告警中心' : 'Open alert center'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default MonitoringCenter;
