import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { BarChart3, TrendingUp, ShieldCheck, AlertTriangle, Activity, Server, RefreshCw, Download } from 'lucide-react';
import { ResponsiveContainer, BarChart, Bar, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, PieChart, Pie, Cell } from 'recharts';
import * as XLSX from 'xlsx';
import type { Device, Job, ComplianceOverview } from '../types';
import { sectionHeaderRowClass } from '../components/shared';

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

interface ReportsTabProps {
  devices: Device[];
  jobs: Job[];
  complianceOverview: ComplianceOverview | null;
  platformData: { name: string; value: number; color: string }[];
  language: string;
  t: (key: string) => string;
}

const REFRESH_INTERVAL = 30_000; // 30s

const ReportsTab: React.FC<ReportsTabProps> = ({
  devices, jobs, complianceOverview, platformData, language, t,
}) => {
  const [alertSummary, setAlertSummary] = useState<AlertSummary | null>(null);
  const [reportRange, setReportRange] = useState<'7d' | '30d'>('7d');
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [refreshing, setRefreshing] = useState(false);

  const fetchAlertSummary = useCallback(async () => {
    const token = localStorage.getItem('sessionToken') || '';
    try {
      const r = await fetch('/api/alerts/summary', { headers: { 'Authorization': `Bearer ${token}` } });
      if (r.ok) {
        const data = await r.json();
        setAlertSummary(data);
      }
    } catch { /* ignore */ }
    setLastRefresh(new Date());
  }, []);

  // Initial fetch + 30s auto-refresh
  useEffect(() => {
    fetchAlertSummary();
    const timer = setInterval(fetchAlertSummary, REFRESH_INTERVAL);
    return () => clearInterval(timer);
  }, [fetchAlertSummary]);

  const handleManualRefresh = async () => {
    setRefreshing(true);
    await fetchAlertSummary();
    setRefreshing(false);
  };

  const handleExportReport = () => {
    const wb = XLSX.utils.book_new();
    // KPI sheet
    const kpiSheet = XLSX.utils.json_to_sheet([
      { Metric: language === 'zh' ? '设备可用率' : 'Device Availability', Value: `${onlinePct}%`, Detail: `${onlineCount}/${devices.length}` },
      { Metric: language === 'zh' ? '任务成功率' : 'Task Success Rate', Value: `${successRate}%`, Detail: `${successJobsInRange}/${totalJobsInRange}` },
      { Metric: language === 'zh' ? '合规评分' : 'Compliance Score', Value: `${compScore}`, Detail: `${compOpen} open / ${compResolved} resolved` },
      { Metric: language === 'zh' ? '活跃告警' : 'Active Alerts', Value: `${alertSummary?.open_count ?? '-'}`, Detail: `Critical: ${alertSummary?.critical_open ?? '-'}` },
      { Metric: 'MTTR', Value: alertSummary ? `${Math.round(alertSummary.avg_mttr_minutes)}m` : '-', Detail: '' },
      { Metric: 'MTTA', Value: alertSummary ? `${Math.round(alertSummary.avg_mtta_minutes)}m` : '-', Detail: '' },
    ]);
    XLSX.utils.book_append_sheet(wb, kpiSheet, 'KPI');
    // Job trend sheet
    const jtSheet = XLSX.utils.json_to_sheet(jobTrend.map(d => ({ Date: d.name, Success: d.success, Failed: d.failed, Total: d.total })));
    XLSX.utils.book_append_sheet(wb, jtSheet, 'Job Trend');
    // Compliance trend sheet
    const ctSheet = XLSX.utils.json_to_sheet(complianceTrend.map(d => ({ Date: d.name, 'Compliance Rate (%)': d.rate })));
    XLSX.utils.book_append_sheet(wb, ctSheet, 'Compliance Trend');
    // Device status sheet
    const dsSheet = XLSX.utils.json_to_sheet(deviceStatusData.map(d => ({ Status: d.name, Count: d.value })));
    XLSX.utils.book_append_sheet(wb, dsSheet, 'Device Status');
    // Alert summary sheet
    if (alertSummary) {
      const asSheet = XLSX.utils.json_to_sheet([{
        'Open': alertSummary.open_count, 'Critical': alertSummary.critical_open,
        'Major': alertSummary.major_open, 'Warning': alertSummary.warning_open,
        '24h New': alertSummary.alerts_24h, '24h Resolved': alertSummary.resolved_24h,
      }]);
      XLSX.utils.book_append_sheet(wb, asSheet, 'Alert Summary');
    }
    const ts = new Date().toISOString().replace(/[-:]/g, '').replace('T', '_').slice(0, 15);
    XLSX.writeFile(wb, `operations_report_${reportRange}_${ts}.xlsx`);
  };

  // Device availability
  const onlineCount = devices.filter(d => d.status === 'online').length;
  const offlineCount = devices.filter(d => d.status === 'offline').length;
  const onlinePct = devices.length > 0 ? Math.round((onlineCount / devices.length) * 100) : 0;

  // Job success rate by day
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

  // Compliance trend — computed locally, synced with reportRange
  const complianceTrend = useMemo(() => {
    const dayLabels = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const monthLabels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return Array.from({ length: rangeDays }, (_, i) => {
      const d = new Date();
      d.setDate(d.getDate() - (rangeDays - 1 - i));
      const dateStr = d.toISOString().slice(0, 10);
      const dayJobs = jobs.filter(j => j.created_at && j.created_at.startsWith(dateStr));
      let rate: number;
      if (dayJobs.length === 0) {
        const total = devices.length;
        rate = total > 0 ? Math.round((devices.filter(dv => dv.compliance === 'compliant').length / total) * 100) : 100;
      } else {
        const success = dayJobs.filter(j => j.status === 'success').length;
        rate = Math.round((success / dayJobs.length) * 100);
      }
      const label = rangeDays <= 7 ? dayLabels[d.getDay()] : `${monthLabels[d.getMonth()]} ${d.getDate()}`;
      return { name: label, rate };
    });
  }, [jobs, devices, rangeDays]);

  const totalJobsInRange = jobTrend.reduce((s, d) => s + d.total, 0);
  const successJobsInRange = jobTrend.reduce((s, d) => s + d.success, 0);
  const failedJobsInRange = jobTrend.reduce((s, d) => s + d.failed, 0);
  const successRate = totalJobsInRange > 0 ? Math.round((successJobsInRange / totalJobsInRange) * 100) : 100;

  // Compliance
  const compScore = complianceOverview?.latest_score ?? 0;
  const compOpen = complianceOverview?.open_findings ?? 0;
  const compResolved = complianceOverview?.resolved_findings ?? 0;

  // Severity distribution from compliance
  const severityData = useMemo(() => {
    if (!complianceOverview?.severity_breakdown) return [];
    const colors: Record<string, string> = { critical: '#ef4444', high: '#f97316', medium: '#f59e0b', low: '#3b82f6' };
    return Object.entries(complianceOverview.severity_breakdown)
      .filter(([, v]) => (v as number) > 0)
      .map(([k, v]) => ({ name: k.charAt(0).toUpperCase() + k.slice(1), value: v as number, color: colors[k] || '#94a3b8' }));
  }, [complianceOverview]);

  // Device status distribution for pie
  const deviceStatusData = useMemo(() => {
    if (devices.length === 0) return [];
    return [
      { name: language === 'zh' ? '在线' : 'Online', value: onlineCount, color: '#10b981' },
      { name: language === 'zh' ? '离线' : 'Offline', value: offlineCount, color: '#ef4444' },
      { name: language === 'zh' ? '待定' : 'Pending', value: devices.length - onlineCount - offlineCount, color: '#94a3b8' },
    ].filter(d => d.value > 0);
  }, [devices, onlineCount, offlineCount, language]);

  const kpiCards = [
    { label: language === 'zh' ? '设备可用率' : 'Device Availability', value: `${onlinePct}%`, sub: `${onlineCount}/${devices.length}`, color: onlinePct >= 90 ? 'text-emerald-600' : onlinePct >= 60 ? 'text-orange-500' : 'text-red-600', border: onlinePct >= 90 ? '' : onlinePct >= 60 ? 'border-l-[3px] border-l-orange-400' : 'border-l-[3px] border-l-red-500' },
    { label: language === 'zh' ? '任务成功率' : 'Task Success Rate', value: `${successRate}%`, sub: `${successJobsInRange}/${totalJobsInRange}`, color: successRate >= 90 ? 'text-emerald-600' : successRate >= 60 ? 'text-orange-500' : 'text-red-600', border: successRate >= 90 ? '' : 'border-l-[3px] border-l-orange-400' },
    { label: language === 'zh' ? '合规评分' : 'Compliance Score', value: `${compScore}`, sub: language === 'zh' ? `${compOpen} 未解决` : `${compOpen} open`, color: compScore >= 80 ? 'text-[#00bceb]' : compScore >= 50 ? 'text-orange-500' : 'text-red-600', border: compScore >= 80 ? '' : 'border-l-[3px] border-l-orange-400' },
    { label: language === 'zh' ? '活跃告警' : 'Active Alerts', value: `${alertSummary?.open_count ?? '--'}`, sub: alertSummary ? (language === 'zh' ? `严重 ${alertSummary.critical_open}` : `Critical ${alertSummary.critical_open}`) : '', color: (alertSummary?.critical_open ?? 0) > 0 ? 'text-red-600' : 'text-emerald-600', border: (alertSummary?.critical_open ?? 0) > 0 ? 'border-l-[3px] border-l-red-500' : '' },
    { label: 'MTTR', value: alertSummary ? `${Math.round(alertSummary.avg_mttr_minutes)}m` : '--', sub: language === 'zh' ? '平均修复时间' : 'Mean Time to Repair', color: 'text-[#005073]', border: '' },
    { label: 'MTTA', value: alertSummary ? `${Math.round(alertSummary.avg_mtta_minutes)}m` : '--', sub: language === 'zh' ? '平均确认时间' : 'Mean Time to Ack', color: 'text-[#005073]', border: '' },
  ];

  return (
    <div className="space-y-5 overflow-auto h-full">
      <div className={sectionHeaderRowClass}>
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-[#00172D]">{language === 'zh' ? '运维报表' : 'Operations Report'}</h2>
          <p className="text-sm text-black/40">{language === 'zh' ? '网络运维关键指标汇总与趋势分析' : 'Key metrics summary and trend analysis for network operations'}</p>
        </div>
        <div className="flex gap-3 items-center">
          <span className="text-[10px] text-black/30">
            {language === 'zh' ? '上次刷新' : 'Refreshed'} {Math.round((Date.now() - lastRefresh.getTime()) / 1000) < 5 ? (language === 'zh' ? '刚刚' : 'just now') : `${Math.round((Date.now() - lastRefresh.getTime()) / 1000)}s`}
          </span>
          <button
            onClick={handleExportReport}
            title={language === 'zh' ? '导出报表' : 'Export Report'}
            className="p-1.5 rounded-lg border border-black/10 text-black/40 hover:text-[#00bceb] hover:border-[#00bceb]/30 transition-all"
          >
            <Download size={14} />
          </button>
          <button
            onClick={handleManualRefresh}
            disabled={refreshing}
            title={language === 'zh' ? '刷新数据' : 'Refresh data'}
            className={`p-1.5 rounded-lg border border-black/10 text-black/40 hover:text-[#00bceb] hover:border-[#00bceb]/30 transition-all ${refreshing ? 'animate-spin' : ''}`}
          >
            <RefreshCw size={14} />
          </button>
          <div className="flex gap-1 bg-black/5 rounded-lg p-0.5">
            <button onClick={() => setReportRange('7d')} className={`px-3 py-1.5 rounded-md text-[11px] font-bold transition-all ${reportRange === '7d' ? 'bg-white shadow-sm text-[#00172D]' : 'text-black/40 hover:text-black/60'}`}>{language === 'zh' ? '近7天' : '7 Days'}</button>
            <button onClick={() => setReportRange('30d')} className={`px-3 py-1.5 rounded-md text-[11px] font-bold transition-all ${reportRange === '30d' ? 'bg-white shadow-sm text-[#00172D]' : 'text-black/40 hover:text-black/60'}`}>{language === 'zh' ? '近30天' : '30 Days'}</button>
          </div>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3">
        {kpiCards.map((kpi, i) => (
          <div key={i} className={`bg-white px-5 py-4 rounded-2xl shadow-sm border border-black/5 ${kpi.border}`}>
            <p className="text-[11px] font-bold uppercase tracking-wider text-black/30 mb-1">{kpi.label}</p>
            <p className={`text-2xl font-bold monitoring-data ${kpi.color}`}>{kpi.value}</p>
            {kpi.sub && <p className="text-[11px] text-black/40 mt-0.5">{kpi.sub}</p>}
          </div>
        ))}
      </div>

      {/* Charts Row 1: Job Trend + Device Status */}
      <div className="grid grid-cols-12 gap-3 md:gap-5">
        <div className="col-span-12 lg:col-span-8 bg-white rounded-2xl border border-black/5 p-5 shadow-sm">
          <div className="flex items-center justify-between mb-5">
            <h3 className="text-sm font-bold text-[#00172D] flex items-center gap-2">
              <BarChart3 size={18} className="text-[#00bceb]" />
              {language === 'zh' ? '任务执行趋势' : 'Task Execution Trend'}
            </h3>
            <div className="flex gap-4 text-[10px] font-semibold">
              <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-emerald-500" />{language === 'zh' ? '成功' : 'Success'}</span>
              <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-red-400" />{language === 'zh' ? '失败' : 'Failed'}</span>
            </div>
          </div>
          <div className="h-[240px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={jobTrend} barGap={2}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#94a3b8', fontWeight: 600 }} dy={8} interval={rangeDays > 7 ? Math.floor(rangeDays / 7) - 1 : 0} />
                <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#94a3b8', fontWeight: 600 }} allowDecimals={false} />
                <Tooltip contentStyle={{ borderRadius: '12px', border: 'none', boxShadow: '0 10px 25px -5px rgb(0 0 0 / 0.1)', padding: '10px', fontSize: '12px' }} />
                <Bar dataKey="success" fill="#10b981" radius={[4, 4, 0, 0]} maxBarSize={32} />
                <Bar dataKey="failed" fill="#f87171" radius={[4, 4, 0, 0]} maxBarSize={32} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="col-span-12 lg:col-span-4 bg-white rounded-2xl border border-black/5 p-5 shadow-sm">
          <h3 className="text-sm font-bold text-[#00172D] mb-5 flex items-center gap-2">
            <Server size={18} className="text-[#005073]" />
            {language === 'zh' ? '设备状态分布' : 'Device Status'}
          </h3>
          <div className="h-[160px] w-full relative">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={deviceStatusData} innerRadius={50} outerRadius={70} paddingAngle={6} dataKey="value" stroke="none">
                  {deviceStatusData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
              <span className="text-xl font-bold text-[#00172D] monitoring-data">{devices.length}</span>
              <span className="text-[10px] text-black/40">{language === 'zh' ? '总设备' : 'Total'}</span>
            </div>
          </div>
          <div className="mt-4 space-y-2">
            {deviceStatusData.map((item, i) => (
              <div key={i} className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: item.color }} />
                  <span className="text-xs font-medium text-black/60">{item.name}</span>
                </div>
                <span className="text-xs font-bold text-[#00172D] monitoring-data">{item.value}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Charts Row 2: Compliance Trend + Severity Distribution */}
      <div className="grid grid-cols-12 gap-3 md:gap-5">
        <div className="col-span-12 lg:col-span-8 bg-white rounded-2xl border border-black/5 p-5 shadow-sm">
          <div className="flex items-center justify-between mb-5">
            <h3 className="text-sm font-bold text-[#00172D] flex items-center gap-2">
              <TrendingUp size={18} className="text-[#00bceb]" />
              {language === 'zh' ? '合规趋势' : 'Compliance Trend'}
            </h3>
          </div>
          <div className="h-[220px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={complianceTrend}>
                <defs>
                  <linearGradient id="colorRateReport" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#00bceb" stopOpacity={0.15} />
                    <stop offset="95%" stopColor="#00bceb" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#94a3b8', fontWeight: 600 }} dy={8} />
                <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#94a3b8', fontWeight: 600 }} domain={[0, 100]} />
                <Tooltip contentStyle={{ borderRadius: '12px', border: 'none', boxShadow: '0 10px 25px -5px rgb(0 0 0 / 0.1)', padding: '10px' }} />
                <Area type="monotone" dataKey="rate" stroke="#00bceb" strokeWidth={2.5} fillOpacity={1} fill="url(#colorRateReport)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="col-span-12 lg:col-span-4 bg-white rounded-2xl border border-black/5 p-5 shadow-sm">
          <h3 className="text-sm font-bold text-[#00172D] mb-5 flex items-center gap-2">
            <ShieldCheck size={18} className="text-orange-500" />
            {language === 'zh' ? '合规问题分布' : 'Finding Severity'}
          </h3>
          {severityData.length > 0 ? (
            <>
              <div className="space-y-3 mt-2">
                {severityData.map((item, i) => {
                  const maxVal = Math.max(...severityData.map(s => s.value));
                  const pct = maxVal > 0 ? (item.value / maxVal) * 100 : 0;
                  return (
                    <div key={i}>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-semibold text-black/60">{item.name}</span>
                        <span className="text-xs font-bold monitoring-data" style={{ color: item.color }}>{item.value}</span>
                      </div>
                      <div className="h-2 bg-black/5 rounded-full overflow-hidden">
                        <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, backgroundColor: item.color }} />
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="mt-5 pt-4 border-t border-black/5">
                <div className="flex justify-between text-xs">
                  <span className="text-black/40">{language === 'zh' ? '已解决' : 'Resolved'}</span>
                  <span className="font-bold text-emerald-600 monitoring-data">{compResolved}</span>
                </div>
                <div className="flex justify-between text-xs mt-1.5">
                  <span className="text-black/40">{language === 'zh' ? '未解决' : 'Open'}</span>
                  <span className="font-bold text-orange-500 monitoring-data">{compOpen}</span>
                </div>
              </div>
            </>
          ) : (
            <div className="flex flex-col items-center justify-center py-10">
              <ShieldCheck size={32} className="text-black/10 mb-2" />
              <p className="text-xs text-black/30">{language === 'zh' ? '暂无合规数据' : 'No compliance data'}</p>
            </div>
          )}
        </div>
      </div>

      {/* Platform Distribution + Alert Summary */}
      <div className="grid grid-cols-12 gap-3 md:gap-5">
        <div className="col-span-12 lg:col-span-6 bg-white rounded-2xl border border-black/5 p-5 shadow-sm">
          <h3 className="text-sm font-bold text-[#00172D] mb-5 flex items-center gap-2">
            <Activity size={18} className="text-emerald-500" />
            {language === 'zh' ? '平台分布' : 'Platform Distribution'}
          </h3>
          {platformData.length > 0 ? (
            <div className="space-y-3">
              {platformData.map((item, i) => {
                const maxVal = Math.max(...platformData.map(p => p.value));
                const pct = maxVal > 0 ? (item.value / maxVal) * 100 : 0;
                return (
                  <div key={i}>
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center gap-2">
                        <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: item.color }} />
                        <span className="text-xs font-medium text-black/60">{item.name}</span>
                      </div>
                      <span className="text-xs font-bold text-[#00172D] monitoring-data">{item.value}%</span>
                    </div>
                    <div className="h-2 bg-black/5 rounded-full overflow-hidden">
                      <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, backgroundColor: item.color }} />
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="text-xs text-black/30 text-center py-8">{language === 'zh' ? '暂无设备' : 'No devices'}</p>
          )}
        </div>

        <div className="col-span-12 lg:col-span-6 bg-white rounded-2xl border border-black/5 p-5 shadow-sm">
          <h3 className="text-sm font-bold text-[#00172D] mb-5 flex items-center gap-2">
            <AlertTriangle size={18} className="text-red-500" />
            {language === 'zh' ? '告警概览' : 'Alert Overview'}
          </h3>
          {alertSummary ? (
            <div className="grid grid-cols-2 gap-3">
              {[
                { label: language === 'zh' ? '活跃告警' : 'Open Alerts', value: alertSummary.open_count, color: alertSummary.open_count > 0 ? 'text-orange-500' : 'text-emerald-600' },
                { label: language === 'zh' ? '严重告警' : 'Critical', value: alertSummary.critical_open, color: alertSummary.critical_open > 0 ? 'text-red-600' : 'text-emerald-600' },
                { label: language === 'zh' ? '24h新增' : '24h New', value: alertSummary.alerts_24h, color: 'text-[#005073]' },
                { label: language === 'zh' ? '24h已解决' : '24h Resolved', value: alertSummary.resolved_24h, color: 'text-emerald-600' },
                { label: language === 'zh' ? '主要告警' : 'Major', value: alertSummary.major_open, color: alertSummary.major_open > 0 ? 'text-orange-500' : 'text-black/40' },
                { label: language === 'zh' ? '次要告警' : 'Warning', value: alertSummary.warning_open, color: alertSummary.warning_open > 0 ? 'text-yellow-600' : 'text-black/40' },
              ].map((item, i) => (
                <div key={i} className="bg-[#f8f9fa] rounded-xl px-4 py-3">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-black/30 mb-0.5">{item.label}</p>
                  <p className={`text-xl font-bold monitoring-data ${item.color}`}>{item.value}</p>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-10">
              <AlertTriangle size={32} className="text-black/10 mb-2" />
              <p className="text-xs text-black/30">{language === 'zh' ? '加载中...' : 'Loading...'}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default ReportsTab;
