import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  TrendingUp, AlertTriangle, RefreshCw, Download, Clock, Shield, Flame,
  ChevronDown, ArrowUpDown, Activity, Server
} from 'lucide-react';
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ReferenceLine, Legend
} from 'recharts';
import * as XLSX from 'xlsx';
import { useChartTheme } from '../hooks/useChartTheme';
import PageHero from '../components/PageHero';

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
  risk_level: 'critical' | 'warning';
  reasons: string[];
}

interface CapacityPlanningTabProps {
  language: string;
  t: (key: string) => string;
}

/* ───────── Mock data for demo ───────── */

const MOCK_RISKS: RiskItem[] = [
  {
    id: 'core-sw-a', hostname: '核心交换机-A区', resource: 'ARP 表项', resourceEn: 'ARP Table',
    usage: 88, daysLeft: 7, severity: 'critical',
    trend: [72, 75, 78, 80, 83, 85, 88],
  },
  {
    id: 'fw-01', hostname: '边界防火墙-01', resource: 'IPsec VPN 隧道', resourceEn: 'IPsec VPN Tunnels',
    usage: 75, daysLeft: 22, severity: 'warning',
    trend: [60, 63, 65, 68, 70, 73, 75],
  },
  {
    id: 'db-cluster', hostname: 'DB-Server-集群', resource: 'IOPS', resourceEn: 'IOPS',
    usage: 60, daysLeft: null, severity: 'normal',
    trend: [55, 56, 57, 58, 58, 59, 60],
  },
  {
    id: 'core-rt-b', hostname: '核心路由器-B栋', resource: '路由表容量', resourceEn: 'Route Table',
    usage: 82, daysLeft: 14, severity: 'warning',
    trend: [68, 70, 73, 75, 78, 80, 82],
  },
  {
    id: 'access-sw-3f', hostname: '接入交换机-3F', resource: 'MAC 表项', resourceEn: 'MAC Table',
    usage: 91, daysLeft: 4, severity: 'critical',
    trend: [78, 81, 84, 86, 88, 90, 91],
  },
];

function generateChartData(zh: boolean) {
  const today = new Date();
  const data: { date: string; actual: number | null; predicted: number | null }[] = [];
  // Past 30 days
  for (let i = 29; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    const label = `${d.getMonth() + 1}/${d.getDate()}`;
    const base = 62 + (30 - i) * 0.7 + Math.sin(i * 0.5) * 4;
    data.push({ date: label, actual: Math.round(base * 10) / 10, predicted: null });
  }
  // Future 30 days
  const lastActual = data[data.length - 1].actual!;
  for (let i = 1; i <= 30; i++) {
    const d = new Date(today);
    d.setDate(d.getDate() + i);
    const label = `${d.getMonth() + 1}/${d.getDate()}`;
    const val = lastActual + i * 0.55 + Math.sin(i * 0.3) * 2;
    data.push({ date: label, actual: null, predicted: Math.round(Math.min(val, 100) * 10) / 10 });
  }
  return data;
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

  // Merge API warnings into risk items, preferring mock data for demo
  const riskItems = useMemo(() => {
    const apiRisks: RiskItem[] = apiWarnings.map(w => ({
      id: w.device_id,
      hostname: w.hostname,
      resource: `CPU ${w.cpu}% / MEM ${w.memory}%`,
      resourceEn: `CPU ${w.cpu}% / MEM ${w.memory}%`,
      usage: Math.max(w.cpu, w.memory),
      daysLeft: w.risk_level === 'critical' ? 10 : 30,
      severity: w.risk_level === 'critical' ? 'critical' as const : 'warning' as const,
      trend: Array.from({ length: 7 }, (_, i) => Math.max(w.cpu, w.memory) - (6 - i) * 2),
    }));
    // Combine: API data first, then mock items not already present
    const ids = new Set(apiRisks.map(r => r.id));
    return [...apiRisks, ...MOCK_RISKS.filter(m => !ids.has(m.id))];
  }, [apiWarnings]);

  const filteredRisks = useMemo(() => {
    let items = riskItems;
    if (filterSeverity !== 'all') items = items.filter(r => r.severity === filterSeverity);
    return sortRisks(items, sortKey);
  }, [riskItems, sortKey, filterSeverity]);

  const chartData = useMemo(() => generateChartData(zh), [zh]);

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
            <button onClick={handleExport} className="p-2 rounded-lg border transition-all" style={{ borderColor: 'var(--card-border)', color: 'var(--muted-text)' }}
              onMouseEnter={e => { e.currentTarget.style.color = '#06b6d4'; e.currentTarget.style.borderColor = 'rgba(6,182,212,0.3)'; }}
              onMouseLeave={e => { e.currentTarget.style.color = 'var(--muted-text)'; e.currentTarget.style.borderColor = 'var(--card-border)'; }}
              title={zh ? '导出' : 'Export'}>
              <Download size={15} />
            </button>
            <button onClick={loadData} disabled={loading}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-white text-sm font-semibold transition-all disabled:opacity-50"
              style={{ background: '#06b6d4' }}
              onMouseEnter={e => { e.currentTarget.style.background = '#0891b2'; }}
              onMouseLeave={e => { e.currentTarget.style.background = '#06b6d4'; }}>
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              {zh ? '刷新' : 'Refresh'}
            </button>
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
                <span className="text-sm font-semibold" style={{ color: 'var(--heading-text)' }}>
                  {selectedRisk
                    ? `${selectedRisk.hostname} — ${zh ? '资源趋势预测' : 'Resource Trend Forecast'}`
                    : (zh ? '整体容量趋势预测' : 'Overall Capacity Trend Forecast')}
                </span>
              </div>
              <div className="flex items-center gap-4 text-[11px]" style={{ color: 'var(--muted-text)' }}>
                <span className="flex items-center gap-1.5">
                  <span className="w-4 h-[2px] rounded" style={{ background: '#06b6d4' }} />
                  {zh ? '实际' : 'Actual'}
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="w-4 h-[2px] rounded" style={{ background: '#f97316', borderTop: '2px dashed #f97316', height: 0 }} />
                  {zh ? '预测' : 'Forecast'}
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="w-4 h-[2px] rounded" style={{ background: '#ef4444', opacity: 0.5 }} />
                  {zh ? '阈值' : 'Threshold'}
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
                      name === 'actual' ? (zh ? '实际使用率' : 'Actual') : (zh ? '预测使用率' : 'Predicted'),
                    ]}
                    labelFormatter={(label) => label}
                  />
                  {/* Threshold lines */}
                  <ReferenceLine y={85} stroke="#ef4444" strokeDasharray="6 4" strokeOpacity={0.5}
                    label={{ value: '85%', position: 'right', fill: '#ef4444', fontSize: 10 }} />
                  <ReferenceLine y={90} stroke="#ef4444" strokeDasharray="3 2" strokeOpacity={0.7}
                    label={{ value: '90%', position: 'right', fill: '#ef4444', fontSize: 10 }} />
                  {/* Actual line — solid */}
                  <Line
                    type="monotone" dataKey="actual" stroke="#06b6d4" strokeWidth={2}
                    dot={false} activeDot={{ r: 4, fill: '#06b6d4', stroke: 'var(--card-bg)', strokeWidth: 2 }}
                    connectNulls={false} name="actual"
                  />
                  {/* Predicted line — dashed */}
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

          {/* Resource detail — shown when a risk is selected */}
          {selectedRisk && (
            <div className="flex-shrink-0 rounded-2xl border px-5 py-4"
              style={{ background: 'var(--card-bg)', borderColor: 'var(--card-border)' }}>
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-semibold" style={{ color: 'var(--heading-text)' }}>
                    {selectedRisk.hostname}
                  </span>
                  <span className="text-[11px] px-1.5 py-0.5 rounded-full font-bold"
                    style={{
                      background: severityConfig[selectedRisk.severity].bg,
                      color: severityConfig[selectedRisk.severity].text,
                    }}>
                    {zh ? severityConfig[selectedRisk.severity].label : severityConfig[selectedRisk.severity].labelEn}
                  </span>
                </div>
                <div className="flex items-center gap-1.5 text-[11px] font-bold"
                  style={{ color: severityConfig[selectedRisk.severity].text }}>
                  <Clock size={12} />
                  {selectedRisk.daysLeft === null ? '60+' : selectedRisk.daysLeft}
                  {zh ? ' 天后达到阈值' : ' days to threshold'}
                </div>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-[12px]" style={{ color: 'var(--muted-text)' }}>
                  {zh ? selectedRisk.resource : selectedRisk.resourceEn}
                </span>
                <div className="flex-1 h-2 rounded-full overflow-hidden"
                  style={{ background: ct.isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)' }}>
                  <div className="h-full rounded-full transition-all duration-700"
                    style={{
                      width: `${selectedRisk.usage}%`,
                      background: selectedRisk.severity === 'critical'
                        ? 'linear-gradient(90deg, #ef4444, #dc2626)'
                        : selectedRisk.severity === 'warning'
                          ? 'linear-gradient(90deg, #f59e0b, #d97706)'
                          : 'linear-gradient(90deg, #10b981, #059669)',
                    }} />
                </div>
                <span className="text-[12px] font-bold tabular-nums"
                  style={{ color: severityConfig[selectedRisk.severity].text }}>
                  {selectedRisk.usage}%
                </span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default CapacityPlanningTab;
