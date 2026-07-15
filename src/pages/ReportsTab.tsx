import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  RefreshCw, Download, ChevronUp, ChevronDown, BarChart3,
} from 'lucide-react';
import {
  ResponsiveContainer, ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip,
} from 'recharts';
import * as XLSX from 'xlsx';
import { motion } from 'motion/react';
import type { Device, Job, ComplianceOverview } from '../types';
import { useChartTheme } from '../hooks/useChartTheme';
import PageHero from '../components/PageHero';

/* ═══════════════════════════════════════════════════════════════════
   Types
   ═══════════════════════════════════════════════════════════════════ */

interface AlertSummary {
  open_count: number;
  critical_open: number;
  major_open: number;
  warning_open: number;
  alerts_24h: number;
  resolved_24h: number;
  avg_mttr_minutes: number;
  avg_mtta_minutes: number;
}

interface ReportDashboardData {
  sla_availability: number;
  avg_mttr_minutes: number;
  avg_mtta_minutes: number;
  incident_trend: { date: string; incidents: number; mttr: number }[];
  top_alerting: { name: string; ip: string; alerts: number; owner: string; spark: number[] }[];
  top_consumers: { name: string; ip: string; metric: string; value: number; unit: string }[];
}

interface ReportsTabProps {
  devices: Device[];
  jobs: Job[];
  complianceOverview: ComplianceOverview | null;
  platformData: { name: string; value: number; color: string }[];
  language: string;
  t: (key: string) => string;
}

/* ═══════════════════════════════════════════════════════════════════
   Mock Data — Actionable Insights
   ═══════════════════════════════════════════════════════════════════ */

const MOCK_TOP_ALERTING = [
  { name: 'Core-SW-Datacenter-01', ip: '10.0.1.1', alerts: 14, owner: 'Zhang Wei', spark: [2, 1, 4, 3, 1, 2, 1] },
  { name: 'Edge-FW-Campus-03', ip: '10.2.3.1', alerts: 11, owner: 'Li Hua', spark: [1, 3, 2, 1, 2, 1, 1] },
  { name: 'WAN-RTR-Branch-07', ip: '172.16.7.1', alerts: 9, owner: 'Wang Jun', spark: [0, 2, 1, 2, 1, 2, 1] },
  { name: 'AP-Controller-HQ', ip: '10.1.10.5', alerts: 7, owner: 'Chen Xia', spark: [1, 1, 0, 2, 1, 1, 1] },
  { name: 'Dist-SW-Floor3-02', ip: '10.3.3.2', alerts: 5, owner: 'Liu Yang', spark: [0, 1, 1, 0, 1, 1, 1] },
];

const MOCK_TOP_CONSUMERS = [
  { name: 'DB-Cluster-Master', ip: '10.1.20.10', metric: 'CPU', value: 96, unit: '%' },
  { name: 'Log-Collector-01', ip: '10.1.20.15', metric: 'MEM', value: 94, unit: '%' },
  { name: 'Core-SW-Datacenter-01', ip: '10.0.1.1', metric: 'BW', value: 92, unit: '%' },
  { name: 'Monitor-Server-02', ip: '10.1.20.22', metric: 'CPU', value: 89, unit: '%' },
  { name: 'Backup-NAS-01', ip: '10.1.30.5', metric: 'DISK', value: 87, unit: '%' },
];

const METRIC_LABELS: Record<string, { zh: string; en: string }> = {
  CPU: { zh: 'CPU', en: 'CPU' },
  MEM: { zh: '内存', en: 'Memory' },
  BW: { zh: '带宽', en: 'Bandwidth' },
  DISK: { zh: '存储', en: 'Storage' },
};

/* ═══════════════════════════════════════════════════════════════════
   Combo Chart — 14 day mock data
   ═══════════════════════════════════════════════════════════════════ */

function buildComboData(language: string): { name: string; incidents: number; mttr: number }[] {
  const base = new Date();
  // Use deterministic pseudo-random based on day of year
  const seed = base.getFullYear() * 1000 + Math.floor((base.getTime() - new Date(base.getFullYear(), 0, 0).getTime()) / 86400000);
  const rng = (i: number) => ((seed * 9301 + 49297 + i * 233) % 233280) / 233280;
  return Array.from({ length: 14 }, (_, i) => {
    const d = new Date(base);
    d.setDate(d.getDate() - 13 + i);
    const dow = d.getDay();
    const isTuTh = dow === 2 || dow === 4;
    const incidents = isTuTh ? 5 + Math.floor(rng(i) * 4) : 1 + Math.floor(rng(i + 100) * 3);
    const mttr = 30 + Math.floor(rng(i + 200) * 20) + (isTuTh ? 5 : 0);
    const label = language === 'zh'
      ? `${d.getMonth() + 1}/${d.getDate()}`
      : d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    return { name: label, incidents, mttr };
  });
}

/* ═══════════════════════════════════════════════════════════════════
   Sparkline Mini SVG
   ═══════════════════════════════════════════════════════════════════ */

const Sparkline: React.FC<{ data: number[]; color?: string; width?: number; height?: number }> = ({
  data, color = '#ef4444', width = 56, height = 20,
}) => {
  const max = Math.max(...data, 1);
  const barW = width / data.length - 1;
  return (
    <svg width={width} height={height} className="flex-shrink-0">
      {data.map((v, i) => {
        const barH = Math.max((v / max) * height, 1.5);
        const x = (i / data.length) * width + 0.5;
        return (
          <rect
            key={i}
            x={x}
            y={height - barH}
            width={Math.max(barW, 3)}
            height={barH}
            rx={1.5}
            fill={color}
            opacity={0.25 + (v / max) * 0.65}
          />
        );
      })}
    </svg>
  );
};

/* ═══════════════════════════════════════════════════════════════════
   Custom Tooltip
   ═══════════════════════════════════════════════════════════════════ */

const ComboTooltip: React.FC<{
  active?: boolean;
  payload?: Array<{ value: number; dataKey: string }>;
  label?: string;
  zh: boolean;
}> = ({ active, payload, label, zh }) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl px-4 py-3 shadow-xl border border-black/5 bg-white/95 backdrop-blur-sm">
      <p className="text-[11px] font-semibold text-black/50 mb-1.5">{label}</p>
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-2 text-xs">
          <span className={`w-2 h-2 rounded-full ${p.dataKey === 'incidents' ? 'bg-rose-400' : 'bg-[#00bceb]'}`} />
          <span className="text-black/50">
            {p.dataKey === 'incidents' ? (zh ? '严重故障' : 'Critical Incidents') : 'MTTR'}
          </span>
          <span className="font-bold monitoring-data text-[#00172D] ml-auto pl-3">
            {p.value}{p.dataKey === 'mttr' ? 'm' : ''}
          </span>
        </div>
      ))}
    </div>
  );
};

/* ═══════════════════════════════════════════════════════════════════
   Main Component
   ═══════════════════════════════════════════════════════════════════ */

const REFRESH_INTERVAL = 30_000;

const ReportsTab: React.FC<ReportsTabProps> = ({
  devices, jobs, complianceOverview, platformData, language, t,
}) => {
  const ct = useChartTheme();
  const zh = language === 'zh';
  const [alertSummary, setAlertSummary] = useState<AlertSummary | null>(null);
  const [reportRange, setReportRange] = useState<'7d' | '30d'>('7d');
  const [reportData, setReportData] = useState<ReportDashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [refreshing, setRefreshing] = useState(false);
  const [hoveredAlertRow, setHoveredAlertRow] = useState<number>(-1);
  const [hoveredConsumerRow, setHoveredConsumerRow] = useState<number>(-1);

  const fetchReportData = useCallback(async () => {
    const token = localStorage.getItem('sessionToken') || '';
    try {
      const rSummary = await fetch('/api/alerts/summary', { headers: { 'Authorization': `Bearer ${token}` } });
      if (rSummary.ok) {
        const data = await rSummary.json();
        setAlertSummary(data);
      }
    } catch { /* ignore */ }

    try {
      const rDashboard = await fetch(`/api/reports/dashboard?range=${reportRange}`, { headers: { 'Authorization': `Bearer ${token}` } });
      if (rDashboard.ok) {
        const data = await rDashboard.json();
        setReportData(data);
      }
    } catch { /* ignore */ }
    setLastRefresh(new Date());
    setLoading(false);
  }, [reportRange]);

  useEffect(() => {
    fetchReportData();
    const timer = setInterval(fetchReportData, REFRESH_INTERVAL);
    return () => clearInterval(timer);
  }, [fetchReportData]);

  const handleManualRefresh = async () => {
    setRefreshing(true);
    await fetchReportData();
    setRefreshing(false);
  };

  // ── Computed metrics ──
  const onlineCount = devices.filter(d => d.status === 'online').length;
  const onlinePct = devices.length > 0 ? ((onlineCount / devices.length) * 100).toFixed(3) : '0.000';

  const rangeDays = reportRange === '7d' ? 7 : 30;
  const jobTrend = useMemo(() => {
    const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return Array.from({ length: rangeDays }, (_, i) => {
      const d = new Date();
      d.setDate(d.getDate() - (rangeDays - 1 - i));
      const dateStr = d.toISOString().slice(0, 10);
      const dayJobs = jobs.filter(j => j.created_at && j.created_at.startsWith(dateStr));
      const success = dayJobs.filter(j => j.status === 'success').length;
      const failed = dayJobs.filter(j => j.status === 'failed').length;
      const label = rangeDays <= 7 ? days[d.getDay()] : `${months[d.getMonth()]} ${d.getDate()}`;
      return { name: label, success, failed, total: dayJobs.length };
    });
  }, [jobs, rangeDays]);

  const totalJobsInRange = jobTrend.reduce((s, d) => s + d.total, 0);
  const successJobsInRange = jobTrend.reduce((s, d) => s + d.success, 0);
  const compScore = complianceOverview?.latest_score ?? 0;

  // Health Score: weighted composite
  const healthScore = useMemo(() => {
    const avail = devices.length > 0 ? onlineCount / devices.length : 1;
    const taskOk = totalJobsInRange > 0 ? successJobsInRange / totalJobsInRange : 1;
    const comp = Math.min(compScore / 100, 1);
    const alertPenalty = Math.max(0, 1 - ((alertSummary?.critical_open ?? 0) * 0.08));
    return Math.round((avail * 35 + taskOk * 25 + comp * 25 + alertPenalty * 15));
  }, [devices.length, onlineCount, totalJobsInRange, successJobsInRange, compScore, alertSummary]);

  const displaySla = reportData ? reportData.sla_availability.toFixed(3) : onlinePct;
  const mttrValue = reportData ? Math.round(reportData.avg_mttr_minutes) : (alertSummary ? Math.round(alertSummary.avg_mttr_minutes) : 42);
  const mttaValue = reportData ? Math.round(reportData.avg_mtta_minutes) : (alertSummary ? Math.round(alertSummary.avg_mtta_minutes) : 8);

  const comboData = useMemo(() => {
    if (!reportData || !reportData.incident_trend) {
      return buildComboData(language);
    }
    return reportData.incident_trend.map(item => {
      try {
        const parts = item.date.split('-');
        const year = parseInt(parts[0], 10);
        const month = parseInt(parts[1], 10);
        const day = parseInt(parts[2], 10);
        const label = language === 'zh'
          ? `${month}/${day}`
          : new Date(Date.UTC(year, month - 1, day)).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
        return {
          name: label,
          incidents: item.incidents,
          mttr: item.mttr
        };
      } catch (e) {
        return {
          name: item.date,
          incidents: item.incidents,
          mttr: item.mttr
        };
      }
    });
  }, [reportData, language]);

  // ── Export ──
  const handleExportReport = () => {
    const wb = XLSX.utils.book_new();
    const kpiSheet = XLSX.utils.json_to_sheet([
      { Metric: zh ? '网络健康度' : 'Health Score', Value: healthScore },
      { Metric: 'SLA Availability', Value: `${displaySla}%` },
      { Metric: 'MTTR', Value: `${mttrValue}m` },
      { Metric: 'MTTA', Value: `${mttaValue}m` },
    ]);
    XLSX.utils.book_append_sheet(wb, kpiSheet, 'KPI');
    const jtSheet = XLSX.utils.json_to_sheet(jobTrend.map(d => ({ Date: d.name, Success: d.success, Failed: d.failed })));
    XLSX.utils.book_append_sheet(wb, jtSheet, 'Job Trend');
    const comboSheet = XLSX.utils.json_to_sheet(comboData.map(d => ({ Date: d.name, Incidents: d.incidents, MTTR: d.mttr })));
    XLSX.utils.book_append_sheet(wb, comboSheet, 'Incident Trend');
    const ts = new Date().toISOString().replace(/[-:]/g, '').replace('T', '_').slice(0, 15);
    XLSX.writeFile(wb, `executive_report_${reportRange}_${ts}.xlsx`);
  };

  const scoreColor = healthScore >= 90 ? '#10b981' : healthScore >= 70 ? '#f59e0b' : '#ef4444';

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHero
        icon={BarChart3}
        title={zh ? '运营报告' : 'Operations Report'}
        subtitle={zh ? '高管视角 · 实时网络运营健康概览' : 'Executive View · Real-time Network Health'}
        actions={
          <>
            <span className="text-[10px] text-black/25 mr-1">
              {zh ? '更新于 ' : 'Updated '}
              {Math.round((Date.now() - lastRefresh.getTime()) / 1000) < 5
                ? (zh ? '刚刚' : 'now')
                : `${Math.round((Date.now() - lastRefresh.getTime()) / 1000)}s`}
            </span>
            <button
              onClick={handleExportReport}
              title={zh ? '导出' : 'Export'}
              className="p-2 rounded-lg text-black/30 hover:text-[#00bceb] transition-colors"
            >
              <Download size={14} />
            </button>
            <button
              onClick={handleManualRefresh}
              disabled={refreshing}
              title={zh ? '刷新' : 'Refresh'}
              className="p-2 rounded-lg text-black/30 hover:text-[#00bceb] transition-colors"
            >
              <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
            </button>
          </>
        }
      />

      <div className="flex-1 overflow-auto px-6 py-5 space-y-10 pb-10">

      {/* ══════════════════════════════════════════════════════════════
          Section 1 — Executive Overview
          ══════════════════════════════════════════════════════════════ */}
      <section>
        {/* Time range toggle */}
        <div className="flex items-center justify-end mb-8">
          <div className="flex gap-0.5 bg-black/[0.03] rounded-lg p-0.5 ml-1">
            {(['7d', '30d'] as const).map(r => (
              <button
                key={r}
                onClick={() => setReportRange(r)}
                className={`px-3 py-1.5 rounded-md text-[11px] font-bold transition-all ${
                  reportRange === r
                    ? 'bg-white shadow-sm text-[#00172D]'
                    : 'text-black/35 hover:text-black/55'
                }`}
              >
                {r === '7d' ? (zh ? '7天' : '7D') : (zh ? '30天' : '30D')}
                </button>
              ))}
            </div>
        </div>

        {/* Core KPI — no card borders, data floats on page */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-x-8 gap-y-6">

          {/* Health Score */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0, duration: 0.5 }}
            className="flex items-start gap-4"
          >
            <div className="relative flex-shrink-0">
              <svg width="60" height="60" viewBox="0 0 60 60">
                <circle cx="30" cy="30" r="26" fill="none" stroke="currentColor" strokeWidth="3" className="text-black/[0.04]" />
                <circle
                  cx="30" cy="30" r="26"
                  fill="none"
                  stroke={scoreColor}
                  strokeWidth="3.5"
                  strokeLinecap="round"
                  strokeDasharray={`${(healthScore / 100) * 163.36} 163.36`}
                  transform="rotate(-90 30 30)"
                  className="transition-all duration-700"
                />
              </svg>
              <span
                className="absolute inset-0 flex items-center justify-center text-lg font-black monitoring-data"
                style={{ color: scoreColor }}
              >
                {healthScore}
              </span>
            </div>
            <div className="pt-1">
              <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-black/30">
                {zh ? '网络健康度' : 'Health Score'}
              </p>
              <p className="text-[11px] text-black/40 mt-1 flex items-center gap-1">
                <ChevronUp size={12} className="text-emerald-500" />
                {zh ? '较上周提升 3 分' : '+3 vs last week'}
              </p>
            </div>
          </motion.div>

          {/* SLA Availability */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.06, duration: 0.5 }}
          >
            <div className="flex items-center gap-2 mb-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(16,185,129,0.5)]" />
              <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-black/30">
                {zh ? 'SLA 可用性' : 'SLA Availability'}
              </p>
            </div>
            <p className="text-[32px] font-black tracking-tight text-[#00172D] leading-none monitoring-data">
              {displaySla}<span className="text-lg text-black/25 ml-0.5">%</span>
            </p>
            <p className="text-[11px] text-black/35 mt-1.5">
              {onlineCount}/{devices.length} {zh ? '设备在线' : 'devices online'}
            </p>
          </motion.div>

          {/* MTTR */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.12, duration: 0.5 }}
          >
            <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-black/30 mb-1.5">
              MTTR
            </p>
            <p className="text-[32px] font-black tracking-tight text-[#00172D] leading-none monitoring-data">
              {mttrValue}<span className="text-base text-black/20 ml-0.5">min</span>
            </p>
            <p className="text-[11px] text-emerald-500 mt-1.5 flex items-center gap-0.5">
              <ChevronDown size={11} />
              <span>↘ 15%</span>
              <span className="text-black/25 ml-1">{zh ? '较上月' : 'vs last month'}</span>
            </p>
          </motion.div>

          {/* MTTA */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.18, duration: 0.5 }}
          >
            <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-black/30 mb-1.5">
              MTTA
            </p>
            <p className="text-[32px] font-black tracking-tight text-[#00172D] leading-none monitoring-data">
              {mttaValue}<span className="text-base text-black/20 ml-0.5">min</span>
            </p>
            <p className="text-[11px] text-rose-400 mt-1.5 flex items-center gap-0.5">
              <ChevronUp size={11} />
              <span>↗ 5%</span>
              <span className="text-black/25 ml-1">{zh ? '行业基准 10m' : 'benchmark 10m'}</span>
            </p>
          </motion.div>
        </div>
      </section>

      {/* ══════════════════════════════════════════════════════════════
          Section 2 — Trend Analytics: Combo Chart
          ══════════════════════════════════════════════════════════════ */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-sm font-bold text-[#00172D]">
              {zh ? '故障趋势与修复效率' : 'Incident Trend & Resolution Efficiency'}
            </h2>
            <p className="text-[11px] text-black/30 mt-0.5">
              {zh ? '过去 14 天 · 严重故障 vs MTTR' : 'Last 14 days · Critical Incidents vs MTTR'}
            </p>
          </div>
          <div className="flex gap-5 text-[11px] font-semibold text-black/40">
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-2.5 rounded-sm bg-rose-300/60" />
              {zh ? '严重故障数' : 'Critical Incidents'}
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-5 h-[2px] rounded-full bg-[#00bceb]" />
              {zh ? 'MTTR (分钟)' : 'MTTR (min)'}
            </span>
          </div>
        </div>

        <div className="h-[260px] w-full -ml-2">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={comboData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="barGradientReport" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#fb7185" stopOpacity={0.7} />
                  <stop offset="100%" stopColor="#fda4af" stopOpacity={0.25} />
                </linearGradient>
                <linearGradient id="lineGradientReport" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%" stopColor="#00bceb" />
                  <stop offset="100%" stopColor="#0096bd" />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={ct.grid} />
              <XAxis
                dataKey="name"
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 10, fill: '#94a3b8', fontWeight: 600 }}
                dy={8}
              />
              <YAxis
                yAxisId="left"
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 10, fill: '#94a3b8', fontWeight: 600 }}
                allowDecimals={false}
              />
              <YAxis
                yAxisId="right"
                orientation="right"
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 10, fill: '#94a3b8', fontWeight: 600 }}
                domain={[0, 80]}
              />
              <Tooltip content={<ComboTooltip zh={zh} />} />
              <Bar
                yAxisId="left"
                dataKey="incidents"
                fill="url(#barGradientReport)"
                radius={[5, 5, 0, 0]}
                maxBarSize={28}
              />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="mttr"
                stroke="url(#lineGradientReport)"
                strokeWidth={2.5}
                dot={false}
                activeDot={{ r: 4, strokeWidth: 2, fill: '#fff', stroke: '#00bceb' }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </section>

      {/* ══════════════════════════════════════════════════════════════
          Section 3 — Actionable Insights: Top N Lists
          ══════════════════════════════════════════════════════════════ */}
      <section>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-10">

          {/* Left: Top Alerting Devices */}
          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-bold text-[#00172D]">
                {zh ? 'Top 5 故障频发设备' : 'Top 5 Alerting Devices'}
              </h2>
              <span className="text-[10px] text-black/25 font-semibold uppercase tracking-wider">
                {zh ? '近 7 天' : 'Last 7 days'}
              </span>
            </div>

            <div className="space-y-0">
              {loading ? (
                <div className="text-center py-10 text-xs text-black/25 animate-pulse">
                  {zh ? '加载中...' : 'Loading...'}
                </div>
              ) : (reportData?.top_alerting || []).length === 0 ? (
                <div className="text-center py-10 text-xs text-black/25">
                  {zh ? '暂无频发告警设备' : 'No chronic alerting devices'}
                </div>
              ) : (
                (reportData?.top_alerting || []).map((item, i) => (
                  <motion.div
                    key={item.name}
                    initial={{ opacity: 0, x: -12 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.06, duration: 0.4 }}
                    onMouseEnter={() => setHoveredAlertRow(i)}
                    onMouseLeave={() => setHoveredAlertRow(-1)}
                    className={`flex items-center gap-4 px-4 py-3.5 rounded-xl transition-colors cursor-default ${
                      hoveredAlertRow === i ? 'bg-black/[0.025]' : ''
                    }`}
                  >
                    <span className={`text-xs font-black w-5 text-center monitoring-data ${
                      i === 0 ? 'text-rose-500' : i === 1 ? 'text-orange-400' : 'text-black/20'
                    }`}>
                      {i + 1}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-[13px] font-semibold text-[#00172D] truncate">{item.name}</p>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-[10px] text-black/30 monitoring-data">{item.ip}</span>
                        <span className="text-[10px] text-black/20">·</span>
                        <span className="text-[10px] text-black/30">{item.owner}</span>
                      </div>
                    </div>
                    {item.spark && item.spark.length > 0 && (
                      <Sparkline data={item.spark} color="#ef4444" />
                    )}
                    <div className="text-right flex-shrink-0 w-12">
                      <span className={`text-base font-black monitoring-data ${
                        item.alerts >= 10 ? 'text-rose-500' : 'text-orange-400'
                      }`}>
                        {item.alerts}
                      </span>
                      <p className="text-[9px] text-black/25 -mt-0.5">{zh ? '次告警' : 'alerts'}</p>
                    </div>
                  </motion.div>
                ))
              )}
            </div>
          </div>

          {/* Right: Top Resource Consumers */}
          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-bold text-[#00172D]">
                {zh ? 'Top 5 资源消耗大户' : 'Top 5 Resource Consumers'}
              </h2>
              <span className="text-[10px] text-black/25 font-semibold uppercase tracking-wider">
                {zh ? '实时监控' : 'Live monitor'}
              </span>
            </div>

            <div className="space-y-0">
              {loading ? (
                <div className="text-center py-10 text-xs text-black/25 animate-pulse">
                  {zh ? '加载中...' : 'Loading...'}
                </div>
              ) : (reportData?.top_consumers || []).length === 0 ? (
                <div className="text-center py-10 text-xs text-black/25">
                  {zh ? '暂无高负载资源' : 'No resource usage reported'}
                </div>
              ) : (
                (reportData?.top_consumers || []).map((item, i) => (
                  <motion.div
                    key={`${item.name}-${item.metric}`}
                    initial={{ opacity: 0, x: 12 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.06, duration: 0.4 }}
                    onMouseEnter={() => setHoveredConsumerRow(i)}
                    onMouseLeave={() => setHoveredConsumerRow(-1)}
                    className={`flex items-center gap-4 px-4 py-3.5 rounded-xl transition-colors cursor-default ${
                      hoveredConsumerRow === i ? 'bg-black/[0.025]' : ''
                    }`}
                  >
                    <span className={`text-xs font-black w-5 text-center monitoring-data ${
                      i === 0 ? 'text-rose-500' : i === 1 ? 'text-orange-400' : 'text-black/20'
                    }`}>
                      {i + 1}
                    </span>
                    <div className="min-w-0 w-40 flex-shrink-0">
                      <p className="text-[13px] font-semibold text-[#00172D] truncate">{item.name}</p>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-[10px] text-black/30 monitoring-data">{item.ip}</span>
                        <span className="text-[10px] text-black/20">·</span>
                        <span className={`text-[10px] font-semibold ${
                          item.metric === 'CPU' ? 'text-rose-400' : item.metric === 'MEM' ? 'text-amber-500' : 'text-sky-400'
                        }`}>
                          {(METRIC_LABELS[item.metric] || { zh: item.metric, en: item.metric })[zh ? 'zh' : 'en']}
                        </span>
                      </div>
                    </div>
                    <div className="flex-1">
                      <div className="h-[6px] bg-black/[0.04] rounded-full overflow-hidden">
                        <motion.div
                          initial={{ width: 0 }}
                          animate={{ width: `${item.value}%` }}
                          transition={{ duration: 0.8, delay: i * 0.1 }}
                          className={`h-full rounded-full ${
                            item.value >= 90
                              ? 'bg-gradient-to-r from-rose-400 to-rose-500'
                              : item.value >= 80
                                ? 'bg-gradient-to-r from-amber-400 to-amber-500'
                                : 'bg-gradient-to-r from-sky-300 to-sky-400'
                          }`}
                        />
                      </div>
                    </div>
                    <div className="text-right flex-shrink-0 w-14">
                      <span className={`text-base font-black monitoring-data ${
                        item.value >= 90 ? 'text-rose-500' : item.value >= 80 ? 'text-amber-500' : 'text-sky-500'
                      }`}>
                        {item.value}
                      </span>
                      <span className="text-[10px] text-black/25">{item.unit}</span>
                    </div>
                  </motion.div>
                ))
              )}
            </div>
          </div>
        </div>
      </section>
      </div>
    </div>
  );
};

export default ReportsTab;