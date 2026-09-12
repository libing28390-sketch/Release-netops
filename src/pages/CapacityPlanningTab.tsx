import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  TrendingUp, AlertTriangle, RefreshCw, Download, Clock, Shield, Flame,
  ChevronDown, ArrowUpDown, Activity, Server, Search, X
} from 'lucide-react';
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ReferenceLine, Legend
} from 'recharts';
import * as XLSX from 'xlsx';
import { useChartTheme } from '../hooks/useChartTheme';
import PageHero from '../components/PageHero';
import { ActionButton } from '../components/ui/ActionIconButton';

/* ───────── Types ───────── */

interface RiskItem {
  id: string;
  hostname: string;
  resource: string;
  resourceEn: string;
  usage: number;
  daysLeft: number | null; // null = 60+
  severity: 'critical' | 'warning' | 'normal';
  trend: number[]; // last 7d usage snapshots
  worstInterface?: string;
  capacityScore?: number;
}

interface CapacityOverview {
  total_devices: number;
  avg_cpu: number;
  avg_memory: number;
  high_cpu_count: number;
  high_memory_count: number;
  high_cpu_devices: any[];
  high_memory_devices: any[];
  hot_interfaces: any[];
  all_devices?: any[];
}

interface ForecastWarning {
  device_id: string;
  hostname: string;
  ip_address: string;
  platform: string;
  cpu: number;
  memory: number;
  peak_link_util: number;
  avg_link_util: number;
  risk_level: 'critical' | 'high' | 'warning' | 'healthy';
  reasons: string[];
  worst_interface: string;
  capacity_score: number;
}

interface CapacityPlanningTabProps {
  language: string;
  t: (key: string) => string;
}



/* ───────── Helpers ───────── */

type SortKey = 'daysLeft' | 'usage' | 'severity';

const severityOrder = { critical: 0, warning: 1, normal: 2 };

function sortRisks(items: RiskItem[], key: SortKey): RiskItem[] {
  return [...items].sort((a, b) => {
    if (key === 'daysLeft') {
      const da = a.daysLeft ?? 999;
      const db = b.daysLeft ?? 999;
      return da - db;
    }
    if (key === 'usage') return b.usage - a.usage;
    return severityOrder[a.severity] - severityOrder[b.severity];
  });
}

const severityConfig = {
  critical: {
    label: '高危', labelEn: 'Critical',
    bg: 'rgba(239,68,68,0.10)', text: '#dc2626', border: '#fca5a5',
    dot: '#ef4444',
  },
  warning: {
    label: '警告', labelEn: 'Warning',
    bg: 'rgba(245,158,11,0.10)', text: '#d97706', border: '#fcd34d',
    dot: '#f59e0b',
  },
  normal: {
    label: '正常', labelEn: 'Normal',
    bg: 'rgba(16,185,129,0.10)', text: '#059669', border: '#6ee7b7',
    dot: '#10b981',
  },
};

/* ───────── Component ───────── */

const CapacityPlanningTab: React.FC<CapacityPlanningTabProps> = ({ language, t }) => {
  const ct = useChartTheme();
  const zh = language === 'zh';
  const [overview, setOverview] = useState<CapacityOverview | null>(null);
  const [apiWarnings, setApiWarnings] = useState<ForecastWarning[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState<SortKey>('daysLeft');
  const [filterSeverity, setFilterSeverity] = useState<string>('all');
  const [selectedRisk, setSelectedRisk] = useState<RiskItem | null>(null);

  // New capacity forecasting states
  const [deviceTrendData, setDeviceTrendData] = useState<any>(null);
  const [selectedInterfaceIndex, setSelectedInterfaceIndex] = useState<number>(0);
  const [trendLoading, setTrendLoading] = useState<boolean>(false);
  const [searchTerm, setSearchTerm] = useState('');

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [ovRes, fcRes] = await Promise.all([
        fetch('/api/capacity/overview'),
        fetch('/api/capacity/forecast'),
      ]);
      if (ovRes.ok) setOverview(await ovRes.json());
      if (fcRes.ok) {
        const fc = await fcRes.json();
        setApiWarnings(fc.items || []);
      }
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  // Fetch interface-specific capacity forecasting details when device is clicked
  useEffect(() => {
    if (!selectedRisk) {
      setDeviceTrendData(null);
      return;
    }
    const fetchTrend = async () => {
      setTrendLoading(true);
      try {
        const res = await fetch(`/api/capacity/device/${selectedRisk.id}/trend`);
        if (res.ok) {
          const data = await res.json();
          if (data && data.interfaces && data.interfaces.length > 0) {
            setDeviceTrendData(data);
            setSelectedInterfaceIndex(0); // Default to the busiest interface
          } else {
            setDeviceTrendData(null);
          }
        } else {
          setDeviceTrendData(null);
        }
      } catch (err) {
        console.error(err);
        setDeviceTrendData(null);
      }
      setTrendLoading(false);
    };
    fetchTrend();
  }, [selectedRisk]);

  // Merge API warnings and other online devices into risk items
  const riskItems = useMemo(() => {
    // 1. Process real alert devices
    const apiRisks: RiskItem[] = apiWarnings.map(w => ({
      id: w.device_id,
      hostname: w.hostname,
      resource: `接口 ${w.worst_interface} (P95: ${w.peak_link_util}%)`,
      resourceEn: `Intf ${w.worst_interface} (P95: ${w.peak_link_util}%)`,
      usage: w.peak_link_util,
      daysLeft: w.risk_level === 'critical' ? 7 : 30,
      severity: (w.risk_level === 'critical' || w.risk_level === 'high') ? 'critical' as const : 'warning' as const,
      trend: Array.from({ length: 7 }, (_, i) => w.peak_link_util - (6 - i) * 2),
      capacityScore: w.capacity_score,
      worstInterface: w.worst_interface
    } as any));

    // 2. Add remaining healthy online devices from overview
    const alertIds = new Set(apiRisks.map(r => r.id));
    const healthyDevices: RiskItem[] = [];
    
    if (overview && overview.all_devices) {
      overview.all_devices.forEach((d: any) => {
        if (!alertIds.has(d.id)) {
          const cpuDisp = d.cpu_usage !== null && d.cpu_usage !== undefined ? `${d.cpu_usage}` : '--';
          const memDisp = d.memory_usage !== null && d.memory_usage !== undefined ? `${d.memory_usage}` : '--';
          healthyDevices.push({
            id: d.id,
            hostname: d.hostname || d.ip_address || 'Unknown',
            resource: `CPU ${cpuDisp}% / 内存 ${memDisp}%`,
            resourceEn: `CPU ${cpuDisp}% / MEM ${memDisp}%`,
            usage: Math.max(d.cpu_usage || 0, d.memory_usage || 0),
            daysLeft: null,
            severity: 'normal' as const,
            trend: Array.from({ length: 7 }, () => Math.max(d.cpu_usage || 0, d.memory_usage || 0)),
            capacityScore: 100, // Healthy score is 100
            worstInterface: 'N/A'
          } as any);
        }
      });
    }

    const merged = [...apiRisks, ...healthyDevices];
    return merged;
  }, [apiWarnings, overview]);

  // Default to selecting the first risk item if none selected
  useEffect(() => {
    if (riskItems.length > 0 && !selectedRisk) {
      setSelectedRisk(riskItems[0]);
    } else if (riskItems.length === 0 && selectedRisk) {
      setSelectedRisk(null);
    }
  }, [riskItems, selectedRisk]);

  const filteredRisks = useMemo(() => {
    let items = riskItems;
    if (filterSeverity !== 'all') items = items.filter(r => r.severity === filterSeverity);
    if (searchTerm.trim() !== '') {
      const low = searchTerm.toLowerCase();
      items = items.filter(r => 
        r.hostname.toLowerCase().includes(low) || 
        (r.resource && r.resource.toLowerCase().includes(low)) ||
        (r.resourceEn && r.resourceEn.toLowerCase().includes(low)) ||
        (r.worstInterface && r.worstInterface.toLowerCase().includes(low))
      );
    }
    return sortRisks(items, sortKey);
  }, [riskItems, sortKey, filterSeverity, searchTerm]);

  // Extract selected interface metrics
  const activeIntf = useMemo(() => {
    if (deviceTrendData && deviceTrendData.interfaces && deviceTrendData.interfaces.length > 0) {
      return deviceTrendData.interfaces[selectedInterfaceIndex];
    }
    return null;
  }, [deviceTrendData, selectedInterfaceIndex]);

  // Merge historical trends & future forecasts for active interface
  const chartData = useMemo(() => {
    // If there is no interface telemetry data
    if (!activeIntf) {
      if (selectedRisk) {
        // Real device but no telemetry data yet: Draw a flat 0% baseline
        const today = new Date();
        const emptyData = [];
        for (let i = 29; i >= 0; i--) {
          const d = new Date(today);
          d.setDate(d.getDate() - i);
          emptyData.push({
            date: `${d.getMonth() + 1}/${d.getDate()}`,
            actual: 0.0,
            smoothed: 0.0,
            predicted: null
          });
        }
        return emptyData;
      }
      return [];
    }
    const data: any[] = [];
    // 1. Fill 30 days of actual historical metrics
    activeIntf.trends.forEach((t: any) => {
      data.push({
        date: t.date,
        actual: t.avg_in_util,       // Raw telemetry
        smoothed: t.avg_out_util,    // 7-day smoothed trend
        predicted: null
      });
    });
    // 2. Connector point between history and prediction
    if (data.length > 0) {
      const lastHist = data[data.length - 1];
      data.push({
        date: lastHist.date,
        actual: null,
        smoothed: null,
        predicted: lastHist.smoothed
      });
    }
    // 3. Fill 30 days of future predictions
    activeIntf.forecast_30d.forEach((f: any) => {
      data.push({
        date: f.date,
        actual: null,
        smoothed: null,
        predicted: f.predicted_util
      });
    });
    return data;
  }, [activeIntf, selectedRisk, zh]);

  const stats = useMemo(() => {
    const critical = riskItems.filter(r => r.severity === 'critical').length;
    const warning = riskItems.filter(r => r.severity === 'warning').length;
    const normal = riskItems.filter(r => r.severity === 'normal').length;
    return { total: riskItems.length, critical, warning, normal };
  }, [riskItems]);

  const handleExport = () => {
    const data = filteredRisks.map(r => ({
      [zh ? '主机名' : 'Hostname']: r.hostname,
      [zh ? '资源类型' : 'Resource']: zh ? r.resource : r.resourceEn,
      [zh ? '使用率' : 'Usage']: `${r.usage}%`,
      [zh ? '剩余天数' : 'Days Left']: r.daysLeft ?? '60+',
      [zh ? '容量评分' : 'Capacity Score']: (r as any).capacityScore ?? 'N/A',
      [zh ? '风险等级' : 'Severity']: zh
        ? severityConfig[r.severity].label
        : severityConfig[r.severity].labelEn,
    }));
    const ws = XLSX.utils.json_to_sheet(data);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, 'Capacity Risks');
    const ts = new Date().toISOString().replace(/[-:]/g, '').replace('T', '_').slice(0, 15);
    XLSX.writeFile(wb, `capacity_risks_${ts}.xlsx`);
  };

  // Mini sparkline via SVG
  const Sparkline: React.FC<{ data: number[]; color: string }> = ({ data, color }) => {
    const max = Math.max(...data, 100);
    const min = Math.min(...data, 0);
    const h = 24;
    const w = 56;
    const points = data.map((v, i) => {
      const x = (i / (data.length - 1)) * w;
      const y = h - ((v - min) / (max - min)) * h;
      return `${x},${y}`;
    }).join(' ');
    return (
      <svg width={w} height={h} className="flex-shrink-0">
        <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHero
        icon={TrendingUp}
        title={zh ? '容量预测与风险分析' : 'Capacity Forecast & Risk Analysis'}
        subtitle={zh ? '基于历史趋势的资源耗尽预测，提前规划扩容' : 'Resource exhaustion prediction based on historical trends'}
        actions={
          <>
            <ActionButton icon={Download} variant="accent" size="md" onClick={handleExport} title={zh ? '导出' : 'Export'}>
              {zh ? '导出' : 'Export'}
            </ActionButton>
            <ActionButton icon={RefreshCw} variant="primary" size="md" onClick={loadData} disabled={loading} iconClassName={loading ? 'animate-spin' : undefined}>
              {zh ? '刷新' : 'Refresh'}
            </ActionButton>
          </>
        }
      />

      <div className="flex flex-1 gap-4 overflow-hidden min-h-0 px-6 py-5">

        {/* ══════ LEFT: Risk Queue ══════ */}
        <div className="w-[340px] flex-shrink-0 flex flex-col rounded-2xl border overflow-hidden"
          style={{ background: 'var(--card-bg)', borderColor: 'var(--card-border)' }}>

          {/* Queue header */}
          <div className="flex items-center justify-between px-4 py-3 border-b flex-shrink-0"
            style={{ borderColor: 'var(--card-border)', background: ct.isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.015)' }}>
            <div className="flex items-center gap-2">
              <Shield size={15} style={{ color: '#06b6d4' }} />
              <span className="text-sm font-semibold" style={{ color: 'var(--heading-text)' }}>
                {zh ? '风险队列' : 'Risk Queue'}
              </span>
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full"
                style={{ background: 'rgba(6,182,212,0.1)', color: '#06b6d4' }}>
                {stats.total}
              </span>
            </div>
            <button onClick={() => setSortKey(k => k === 'daysLeft' ? 'usage' : k === 'usage' ? 'severity' : 'daysLeft')}
              className="flex items-center gap-1 text-[11px] font-medium px-2 py-1 rounded-lg transition-colors"
              style={{ color: 'var(--muted-text)' }}
              onMouseEnter={e => { e.currentTarget.style.background = 'var(--app-hover-bg)'; }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
              title={zh ? '切换排序' : 'Toggle sort'}>
              <ArrowUpDown size={12} />
              {sortKey === 'daysLeft' ? (zh ? '倒计时' : 'Days') : sortKey === 'usage' ? (zh ? '使用率' : 'Usage') : (zh ? '等级' : 'Level')}
            </button>
          </div>

          {/* Search bar */}
          <div className="px-4 py-2 border-b flex-shrink-0" style={{ borderColor: 'var(--card-border)' }}>
            <div className="relative flex items-center">
              <input
                type="text"
                value={searchTerm}
                onChange={e => setSearchTerm(e.target.value)}
                placeholder={zh ? '搜索设备或指标...' : 'Search device/metric...'}
                className="w-full pl-8 pr-8 py-1.5 rounded-lg text-xs transition-all border outline-none"
                style={{
                  background: 'var(--app-hover-bg)',
                  borderColor: 'var(--card-border)',
                  color: 'var(--body-text)',
                }}
              />
              <span className="absolute left-2.5 animate-pulse" style={{ color: 'var(--dim-text)' }}>
                <Search size={14} />
              </span>
              {searchTerm && (
                <button
                  onClick={() => setSearchTerm('')}
                  className="absolute right-2.5 p-0.5 rounded-full hover:bg-neutral-200 dark:hover:bg-neutral-700 transition-colors"
                  style={{ color: 'var(--dim-text)', border: 'none', background: 'transparent', cursor: 'pointer' }}
                >
                  <X size={12} />
                </button>
              )}
            </div>
          </div>

          {/* Severity filter pills */}
          <div className="flex gap-1.5 px-4 py-2.5 border-b flex-shrink-0" style={{ borderColor: 'var(--card-border)' }}>
            {(['all', 'critical', 'warning', 'normal'] as const).map(s => {
              const active = filterSeverity === s;
              const cfg = s === 'all' ? null : severityConfig[s];
              const label = s === 'all' ? (zh ? '全部' : 'All') : (zh ? cfg!.label : cfg!.labelEn);
              const count = s === 'all' ? stats.total : stats[s];
              return (
                <button key={s} onClick={() => setFilterSeverity(s)}
                  className="flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-medium transition-all"
                  style={{
                    background: active ? (cfg?.bg || 'rgba(6,182,212,0.1)') : 'transparent',
                    color: active ? (cfg?.text || '#06b6d4') : 'var(--muted-text)',
                    border: `1px solid ${active ? (cfg?.border || 'rgba(6,182,212,0.3)') : 'transparent'}`,
                  }}>
                  {cfg && <span className="w-1.5 h-1.5 rounded-full" style={{ background: cfg.dot }} />}
                  {label} {count}
                </button>
              );
            })}
          </div>

          {/* Risk list */}
          <div className="flex-1 overflow-y-auto" style={{ scrollbarWidth: 'thin', scrollbarColor: 'rgba(0,0,0,0.1) transparent' }}>
            {filteredRisks.length === 0 && (
              <div className="flex flex-col items-center justify-center py-16" style={{ color: 'var(--dim-text)' }}>
                <Shield size={32} className="mb-2 opacity-30" />
                <p className="text-sm">{zh ? '暂无风险项' : 'No risks found'}</p>
              </div>
            )}
            {filteredRisks.map(risk => {
              const cfg = severityConfig[risk.severity];
              const isSelected = selectedRisk?.id === risk.id;
              const daysLabel = risk.daysLeft === null ? '60+' : `${risk.daysLeft}`;
              return (
                <button key={risk.id} onClick={() => setSelectedRisk(risk)}
                  className="w-full text-left px-4 py-3 border-b transition-all"
                  style={{
                    borderColor: 'var(--card-border)',
                    background: isSelected ? (ct.isDark ? 'rgba(6,182,212,0.08)' : 'rgba(6,182,212,0.04)') : 'transparent',
                    borderLeft: isSelected ? '3px solid #06b6d4' : '3px solid transparent',
                  }}
                  onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = 'var(--app-hover-bg)'; }}
                  onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = 'transparent'; }}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-[13px] font-semibold truncate" style={{ color: 'var(--heading-text)' }}>
                          {risk.hostname}
                        </span>
                        <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full flex-shrink-0"
                          style={{ background: cfg.bg, color: cfg.text, border: `1px solid ${cfg.border}` }}>
                          {zh ? cfg.label : cfg.labelEn}
                        </span>
                      </div>
                      <p className="text-[11px] mb-2" style={{ color: 'var(--muted-text)' }}>
                        {zh ? risk.resource : risk.resourceEn}
                      </p>
                      {/* Progress bar */}
                      <div className="flex items-center gap-2">
                        <div className="flex-1 h-[6px] rounded-full overflow-hidden"
                          style={{ background: ct.isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)' }}>
                          <div className="h-full rounded-full transition-all duration-700"
                            style={{
                              width: `${risk.usage}%`,
                              background: risk.severity === 'critical'
                                ? 'linear-gradient(90deg, #ef4444, #dc2626)'
                                : risk.severity === 'warning'
                                  ? 'linear-gradient(90deg, #f59e0b, #d97706)'
                                  : 'linear-gradient(90deg, #10b981, #059669)',
                            }} />
                        </div>
                        <span className="text-[11px] font-bold tabular-nums w-[36px] text-right" style={{ color: cfg.text }}>
                          {risk.usage}%
                        </span>
                      </div>
                    </div>
                    {/* Countdown badge */}
                    <div className="flex flex-col items-center flex-shrink-0 mt-0.5">
                      <Sparkline data={risk.trend} color={cfg.dot} />
                      <div className="flex items-center gap-1 mt-1">
                        <Clock size={10} style={{ color: cfg.text }} />
                        <span className="text-[11px] font-bold tabular-nums" style={{ color: cfg.text }}>
                          {daysLabel}{zh ? '天' : 'd'}
                        </span>
                      </div>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* ══════ RIGHT: Predictive Analytics ══════ */}
        <div className="flex-1 flex flex-col gap-4 overflow-hidden min-w-0">

          {/* Summary cards */}
          <div className="grid grid-cols-4 gap-3 flex-shrink-0">
            {[
              {
                label: zh ? '风险设备' : 'At Risk', value: stats.total,
                icon: Server, color: '#06b6d4', bg: 'rgba(6,182,212,0.08)',
              },
              {
                label: zh ? '高危' : 'Critical', value: stats.critical,
                icon: Flame, color: '#dc2626', bg: 'rgba(239,68,68,0.08)',
              },
              {
                label: zh ? '警告' : 'Warning', value: stats.warning,
                icon: AlertTriangle, color: '#d97706', bg: 'rgba(245,158,11,0.08)',
              },
              {
                label: zh ? '正常' : 'Normal', value: stats.normal,
                icon: Activity, color: '#059669', bg: 'rgba(16,185,129,0.08)',
              },
            ].map((card, i) => (
              <div key={i} className="rounded-xl border px-4 py-3"
                style={{ background: 'var(--card-bg)', borderColor: 'var(--card-border)' }}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: 'var(--dim-text)' }}>
                    {card.label}
                  </span>
                  <div className="p-1.5 rounded-lg" style={{ background: card.bg }}>
                    <card.icon size={14} style={{ color: card.color }} />
                  </div>
                </div>
                <p className="text-2xl font-bold tabular-nums" style={{ color: card.color }}>
                  {card.value}
                </p>
              </div>
            ))}
          </div>

          {/* Chart area */}
          <div className="flex-1 flex flex-col rounded-2xl border overflow-hidden min-h-0"
            style={{ background: 'var(--card-bg)', borderColor: 'var(--card-border)' }}>
            <div className="flex items-center justify-between px-5 py-3 border-b flex-shrink-0"
              style={{ borderColor: 'var(--card-border)', background: ct.isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.015)' }}>
              <div className="flex items-center gap-2">
                <TrendingUp size={15} style={{ color: '#06b6d4' }} />
                <span className="text-sm font-semibold truncate max-w-[240px]" style={{ color: 'var(--heading-text)' }}>
                  {selectedRisk
                    ? `${selectedRisk.hostname} — ${zh ? '资源趋势预测' : 'Resource Trend Forecast'}`
                    : (zh ? '整体容量趋势预测' : 'Overall Capacity Trend Forecast')}
                </span>

                {/* Interface selector dropdown */}
                {deviceTrendData && deviceTrendData.interfaces && deviceTrendData.interfaces.length > 0 && (
                  <select
                    value={selectedInterfaceIndex}
                    onChange={(e) => setSelectedInterfaceIndex(Number(e.target.value))}
                    className="ml-3 px-2.5 py-1 text-xs rounded-lg border transition-all"
                    style={{
                      background: 'var(--card-bg)',
                      borderColor: 'var(--card-border)',
                      color: 'var(--body-text)',
                      outline: 'none',
                      cursor: 'pointer'
                    }}
                  >
                    {deviceTrendData.interfaces.map((intf: any, idx: number) => (
                      <option key={idx} value={idx}>
                        {intf.interface_name} (P95: {intf.current_p95_util}%)
                      </option>
                    ))}
                  </select>
                )}
              </div>
              <div className="flex items-center gap-4 text-[11px]" style={{ color: 'var(--muted-text)' }}>
                <span className="flex items-center gap-1.5">
                  <span className="w-4 h-[2px] rounded" style={{ background: '#06b6d4' }} />
                  {zh ? '实际 P95' : 'Actual P95'}
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="w-4 h-[2px] rounded" style={{ background: '#10b981' }} />
                  {zh ? '7日平滑' : '7D Smoothed'}
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="w-4 h-[2px] rounded" style={{ background: '#f97316', borderTop: '2px dashed #f97316', height: 0 }} />
                  {zh ? '预测趋势' : 'Forecast'}
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="w-4 h-[2px] rounded" style={{ background: '#ef4444', opacity: 0.5 }} />
                  {zh ? '警示线' : 'Threshold'}
                </span>
              </div>
            </div>

            <div className="flex-1 px-4 py-4 min-h-0">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
                  <defs>
                    <linearGradient id="capActualGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#06b6d4" stopOpacity={0.12} />
                      <stop offset="100%" stopColor="#06b6d4" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={ct.grid} />
                  <XAxis
                    dataKey="date" axisLine={false} tickLine={false}
                    tick={{ fontSize: 10, fill: ct.axis }}
                    interval={Math.max(0, Math.floor(chartData.length / 10) - 1)}
                  />
                  <YAxis
                    axisLine={false} tickLine={false}
                    tick={{ fontSize: 10, fill: ct.axis }}
                    domain={[0, 100]} unit="%"
                  />
                  <Tooltip
                    contentStyle={{
                      borderRadius: 12,
                      border: `1px solid ${ct.tooltipBorder}`,
                      boxShadow: ct.tooltipShadow,
                      fontSize: 12,
                      background: ct.tooltipBg,
                      color: ct.tooltipText,
                    }}
                    formatter={(value: number, name: string) => [
                      `${value}%`,
                      name === 'actual' 
                        ? (zh ? '实际使用率(P95)' : 'Actual P95') 
                        : name === 'smoothed' 
                          ? (zh ? '7日平滑趋势' : '7D Smoothed') 
                          : (zh ? '预测使用率' : 'Predicted'),
                    ]}
                    labelFormatter={(label) => label}
                  />
                  {/* Professional capacity thresholds: 80% Warning, 95% Critical */}
                  <ReferenceLine y={80} stroke="#f59e0b" strokeDasharray="6 4" strokeOpacity={0.6}
                    label={{ value: '80% (Warning)', position: 'insideBottomRight', fill: '#f59e0b', fontSize: 10 }} />
                  <ReferenceLine y={95} stroke="#ef4444" strokeDasharray="4 2" strokeOpacity={0.8}
                    label={{ value: '95% (Critical)', position: 'insideBottomRight', fill: '#ef4444', fontSize: 10 }} />
                  
                  {/* Actual line — solid cyan */}
                  <Line
                    type="monotone" dataKey="actual" stroke="#06b6d4" strokeWidth={2}
                    dot={false} activeDot={{ r: 4, fill: '#06b6d4', stroke: 'var(--card-bg)', strokeWidth: 2 }}
                    connectNulls={false} name="actual"
                  />
                  {/* Smoothed line — solid green */}
                  <Line
                    type="monotone" dataKey="smoothed" stroke="#10b981" strokeWidth={1.5}
                    dot={false} activeDot={{ r: 3, fill: '#10b981', stroke: 'var(--card-bg)', strokeWidth: 1.5 }}
                    connectNulls={false} name="smoothed"
                  />
                  {/* Predicted line — dashed orange */}
                  <Line
                    type="monotone" dataKey="predicted" stroke="#f97316" strokeWidth={2}
                    strokeDasharray="6 4"
                    dot={false} activeDot={{ r: 4, fill: '#f97316', stroke: 'var(--card-bg)', strokeWidth: 2 }}
                    connectNulls={false} name="predicted"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Chassis Hardware specs card - shown when Chassis-Level Capacity is active */}
          {selectedRisk && activeIntf && activeIntf.interface_name.includes('Chassis-Level') && deviceTrendData?.chassis_spec && deviceTrendData.chassis_spec.ports_count > 0 && (
            <div className="flex-shrink-0 rounded-2xl border px-5 py-4 flex flex-col gap-3 transition-all"
              style={{ 
                background: 'linear-gradient(135deg, rgba(6,182,212,0.06), rgba(16,185,129,0.03))', 
                borderColor: 'rgba(6,182,212,0.25)',
                boxShadow: '0 4px 12px rgba(0, 0, 0, 0.05)'
              }}>
              <div className="flex items-center justify-between border-b pb-2" style={{ borderColor: 'rgba(6,182,212,0.1)' }}>
                <div className="flex items-center gap-2">
                  <Server size={15} style={{ color: '#06b6d4' }} />
                  <span className="text-sm font-semibold" style={{ color: 'var(--heading-text)' }}>
                    {zh ? '底盘硬件交换架构与超配规格' : 'Chassis Hardware Spec & Oversubscription'}
                  </span>
                </div>
                <span className="text-[10px] font-bold px-2 py-0.5 rounded-full"
                  style={{
                    background: deviceTrendData.chassis_spec.is_blocking ? 'rgba(239,68,68,0.1)' : 'rgba(16,185,129,0.1)',
                    color: deviceTrendData.chassis_spec.is_blocking ? '#ef4444' : '#10b981'
                  }}>
                  {deviceTrendData.chassis_spec.is_blocking 
                    ? (zh ? '超配收敛转发' : 'Oversubscribed') 
                    : (zh ? '无阻塞线速转发 (Non-blocking)' : 'Non-blocking Line-rate')}
                </span>
              </div>
              <div className="grid grid-cols-4 gap-4 text-[11px]">
                <div className="flex flex-col gap-0.5">
                  <span style={{ color: 'var(--muted-text)' }}>{zh ? '物理接口总数' : 'Total Ports'}</span>
                  <span className="text-sm font-bold" style={{ color: 'var(--heading-text)' }}>
                    {deviceTrendData.chassis_spec.ports_count} {zh ? '个端口' : 'Ports'}
                  </span>
                </div>
                <div className="flex flex-col gap-0.5">
                  <span style={{ color: 'var(--muted-text)' }}>{zh ? '聚合协商带宽' : 'Aggregate Line Capacity'}</span>
                  <span className="text-sm font-bold text-[#06b6d4]">
                    {deviceTrendData.chassis_spec.ports_bandwidth_gbps} Gbps
                  </span>
                </div>
                <div className="flex flex-col gap-0.5">
                  <span style={{ color: 'var(--muted-text)' }}>{zh ? '芯片背板交换容量' : 'Backplane Capacity'}</span>
                  <span className="text-sm font-bold text-[#10b981]">
                    {deviceTrendData.chassis_spec.switching_capacity_gbps} Gbps
                  </span>
                </div>
                <div className="flex flex-col gap-0.5">
                  <span style={{ color: 'var(--muted-text)' }}>{zh ? '收敛超配比 / 瓶颈类型' : 'Oversubscription / Bottleneck'}</span>
                  <span className="text-sm font-bold" style={{ color: deviceTrendData.chassis_spec.is_blocking ? '#f97316' : 'var(--heading-text)' }}>
                    {deviceTrendData.chassis_spec.oversubscription_ratio.toFixed(2)}:1 ({zh ? (deviceTrendData.chassis_spec.bottleneck_type === 'Ports Speed' ? '接口速率瓶颈' : '背板容量限制') : deviceTrendData.chassis_spec.bottleneck_type})
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Resource detail — shown when a risk is selected */}
          {selectedRisk && (
            <div className="flex-shrink-0 rounded-2xl border px-5 py-4 flex gap-6"
              style={{ background: 'var(--card-bg)', borderColor: 'var(--card-border)' }}>
              
              {/* Score panel (Left) */}
              <div className="flex flex-col items-center justify-center border-r pr-6 flex-shrink-0"
                style={{ borderColor: 'var(--card-border)' }}>
                <span className="text-[10px] font-semibold uppercase tracking-wider mb-1" style={{ color: 'var(--dim-text)' }}>
                  {zh ? '容量健康评分' : 'Capacity Score'}
                </span>
                <div className="text-4xl font-extrabold mb-1 tabular-nums" style={{ 
                  color: activeIntf 
                    ? (activeIntf.capacity_score >= 90 ? '#10b981' : activeIntf.capacity_score >= 70 ? '#f59e0b' : '#ef4444')
                    : '#06b6d4'
                }}>
                  {activeIntf ? activeIntf.capacity_score : ((selectedRisk as any).capacityScore ?? 'N/A')}
                </div>
                <span className="text-[9px] font-bold px-2 py-0.5 rounded-full uppercase" style={{
                  background: activeIntf 
                    ? (activeIntf.capacity_score >= 90 ? 'rgba(16,185,129,0.1)' : activeIntf.capacity_score >= 70 ? 'rgba(245,158,11,0.1)' : 'rgba(239,68,68,0.1)')
                    : 'rgba(6,182,212,0.1)',
                  color: activeIntf 
                    ? (activeIntf.capacity_score >= 90 ? '#10b981' : activeIntf.capacity_score >= 70 ? '#f59e0b' : '#ef4444')
                    : '#06b6d4'
                }}>
                  {activeIntf 
                    ? (zh 
                        ? (activeIntf.risk_level === 'healthy' ? '正常' : activeIntf.risk_level === 'high' || activeIntf.risk_level === 'critical' ? '高危' : '警告') 
                        : activeIntf.risk_level)
                    : (zh ? '评估' : 'Score')}
                </span>
              </div>

              {/* Metrics Detail (Right) */}
              <div className="flex-1 grid grid-cols-3 gap-4 text-[11px] leading-relaxed">
                {/* Telemetry column */}
                <div className="flex flex-col gap-1">
                  <span className="font-bold mb-0.5" style={{ color: 'var(--heading-text)' }}>{zh ? '基础性能指标' : 'Base Metrics'}</span>
                  <div style={{ color: 'var(--muted-text)' }}>
                    CPU {zh ? '利用率' : 'Util'}: <span className="font-bold text-[#06b6d4] tabular-nums">
                      {deviceTrendData && deviceTrendData.cpu_usage !== null && deviceTrendData.cpu_usage !== undefined ? `${deviceTrendData.cpu_usage}%` : '--%'}
                    </span>
                  </div>
                  <div style={{ color: 'var(--muted-text)' }}>
                    {zh ? '内存利用率' : 'Mem Util'}: <span className="font-bold text-[#06b6d4] tabular-nums">
                      {deviceTrendData && deviceTrendData.memory_usage !== null && deviceTrendData.memory_usage !== undefined ? `${deviceTrendData.memory_usage}%` : '--%'}
                    </span>
                  </div>
                  {activeIntf && (
                    <div style={{ color: 'var(--muted-text)' }}>
                      P95 {zh ? '利用率' : 'Util'}: <span className="font-bold text-[#f59e0b] tabular-nums">{activeIntf.current_p95_util}%</span>
                    </div>
                  )}
                </div>

                {/* Packet loss / Error column */}
                <div className="flex flex-col gap-1">
                  <span className="font-bold mb-0.5" style={{ color: 'var(--heading-text)' }}>{zh ? '丢包与异常' : 'Anomalies'}</span>
                  {activeIntf ? (
                    <>
                      <div style={{ color: 'var(--muted-text)' }}>
                        {zh ? '统计丢包率' : 'Loss Rate'}: <span className="font-bold text-[#ef4444] tabular-nums">{activeIntf.packet_loss_rate}%</span>
                      </div>
                      <div style={{ color: 'var(--muted-text)' }}>
                        {zh ? '网络错包数' : 'Errors count'}: <span className="font-bold text-[#ef4444] tabular-nums">{activeIntf.error_count}</span>
                      </div>
                      <div style={{ color: 'var(--muted-text)' }}>
                        {zh ? '总弃包数' : 'Discards'}: <span className="font-bold text-[#ef4444] tabular-nums">{activeIntf.discard_count}</span>
                      </div>
                    </>
                  ) : (
                    <div style={{ color: 'var(--muted-text)' }}>{zh ? '暂无接口遥测数据' : 'No interface telemetry'}</div>
                  )}
                </div>

                {/* Predict Info column */}
                <div className="flex flex-col gap-1">
                  <span className="font-bold mb-0.5" style={{ color: 'var(--heading-text)' }}>{zh ? '回归预测分析' : 'Regression analysis'}</span>
                  {activeIntf ? (
                    <>
                      <div style={{ color: 'var(--muted-text)' }}>
                        {zh ? '决定系数 R²' : 'R² Confidence'}: <span className="font-bold tabular-nums" style={{
                          color: activeIntf.trend_confidence === 'high' ? '#10b981' : activeIntf.trend_confidence === 'medium' ? '#f59e0b' : '#ef4444'
                        }}>{activeIntf.r2} ({activeIntf.trend_confidence})</span>
                      </div>
                      <div style={{ color: 'var(--muted-text)' }}>
                        {zh ? '预计到 80%' : 'Days to 80%'}: <span className="font-bold tabular-nums">{activeIntf.days_to_80 !== null ? `${activeIntf.days_to_80} ${zh ? '天' : 'd'}` : (zh ? '无明显增长' : 'No growth')}</span>
                      </div>
                      <div style={{ color: 'var(--muted-text)' }}>
                        {zh ? '预计到 95%' : 'Days to 95%'}: <span className="font-bold tabular-nums">{activeIntf.days_to_95 !== null ? `${activeIntf.days_to_95} ${zh ? '天' : 'd'}` : (zh ? '无明显增长' : 'No growth')}</span>
                      </div>
                    </>
                  ) : (
                    <div style={{ color: 'var(--muted-text)' }}>{zh ? '暂无容量预测数据' : 'No prediction'}</div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default CapacityPlanningTab;
