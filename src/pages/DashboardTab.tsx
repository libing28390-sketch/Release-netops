import React from 'react';
import { Server, Activity, ShieldCheck, AlertCircle, AlertTriangle, Bell, TrendingUp, PieChart as PieChartIcon, History, Clock, ChevronRight, Zap, MonitorSmartphone, Play, CalendarPlus, LayoutDashboard, Pause, RefreshCw, Layers, ShieldAlert, CheckCircle2, ArrowUpRight } from 'lucide-react';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, PieChart, Pie, Cell } from 'recharts';
import type { Device, Job, ScheduledTask, HostResourceSnapshot, NotificationItem } from '../types';
import { useChartTheme } from '../hooks/useChartTheme';
import PageHero from '../components/PageHero';
import { useSystem } from '../hooks/useSystem';

interface DashboardTabProps {
  devices: Device[];
  jobs: Job[];
  scheduledTasks: ScheduledTask[];
  trendDays: 7 | 30;
  setTrendDays: (d: 7 | 30) => void;
  complianceTrend: { name: string; rate: number }[];
  platformData: { name: string; value: number; color: string }[];
  dashBannerCollapsed: boolean;
  setDashBannerCollapsed: (v: boolean) => void;
  dashLastRefresh: Date;
  autoRefreshEnabled: boolean;
  setAutoRefreshEnabled: (v: boolean) => void;
  fetchSharedData: () => Promise<void>;
  fetchDevicesData: () => Promise<void>;
  selectedJob: Job | null;
  setSelectedJob: (j: Job | null) => void;
  hostResources: HostResourceSnapshot | null;
  unreadNotificationCount: number;
  notifications: NotificationItem[];
  language: string;
  t: (key: string) => string;
  setActiveTab: (tab: string) => void;
  navigate: (path: string) => void;
  assetsTotal: number;
}

const DashboardTab: React.FC<DashboardTabProps> = ({
  devices, jobs, scheduledTasks, trendDays, setTrendDays,
  complianceTrend, platformData, dashBannerCollapsed, setDashBannerCollapsed,
  dashLastRefresh, autoRefreshEnabled, setAutoRefreshEnabled, fetchSharedData, fetchDevicesData, selectedJob, setSelectedJob,
  hostResources, unreadNotificationCount, notifications, language, t, setActiveTab, navigate,
  assetsTotal,
}) => {
  const { systemInfo } = useSystem();
  const [isManualRefreshing, setIsManualRefreshing] = React.useState(false);
  const handleManualRefresh = async () => {
    setIsManualRefreshing(true);
    try {
      await Promise.all([fetchSharedData(), fetchDevicesData()]);
    } catch (e) {
      console.error(e);
    } finally {
      setIsManualRefreshing(false);
    }
  };

  const [showComplianceLine, setShowComplianceLine] = React.useState(true);
  const [showJobSuccessLine, setShowJobSuccessLine] = React.useState(true);
  const ct = useChartTheme();
  const onlineCount = devices.filter(d => d.status === 'online').length;
  const onlinePct = devices.length > 0 ? Math.round((onlineCount / devices.length) * 100) : 0;
  const compPct = devices.length > 0 ? Math.round((devices.filter(d => d.compliance === 'compliant').length / devices.length) * 100) : 0;
  const now24h = Date.now() - 86400000;
  const failedCount24h = jobs.filter(j => j.status === 'failed' && j.created_at && new Date(j.created_at).getTime() > now24h).length;
  const successJobsCount = jobs.filter(j => j.status === 'success').length;

  const hasDevices = devices.length > 0;

  // Find latest unread notification to display message context
  const latestAlert = [...notifications]
    .filter(n => !n.read)
    .sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime())[0];

  // Alert severity breakdown from notifications
  const criticalAlerts = notifications.filter(n => n.severity === 'critical' && !n.read).length;
  const majorAlerts = notifications.filter(n => (n.severity === 'major' || n.severity === 'high') && !n.read).length;
  const warningAlerts = notifications.filter(n => n.severity === 'medium' && !n.read).length;
  const infoAlerts = notifications.filter(n => (n.severity === 'low' || !n.severity) && !n.read).length;

  // Compliance trend stats for dynamic Y-axis
  const trendMin = complianceTrend.length > 0 ? Math.min(...complianceTrend.map(d => d.rate)) : 0;
  const trendMax = complianceTrend.length > 0 ? Math.max(...complianceTrend.map(d => d.rate)) : 100;
  const trendAvg = complianceTrend.length > 0 ? Math.round(complianceTrend.reduce((s, d) => s + d.rate, 0) / complianceTrend.length) : 0;
  const yDomainLow = Math.max(0, Math.floor((trendMin - 5) / 10) * 10);
  const yDomainHigh = Math.min(100, Math.ceil((trendMax + 5) / 10) * 10);
  const useNarrowDomain = (trendMax - trendMin) < 30 && trendMin > 20;

  // Job success rate trend (for overlay on compliance chart)
  const jobSuccessTrend = complianceTrend.map((point, i) => {
    const d = new Date();
    d.setDate(d.getDate() - (complianceTrend.length - 1 - i));
    const dateStr = d.toISOString().slice(0, 10);
    const dayJobs = jobs.filter(j => j.created_at && j.created_at.startsWith(dateStr));
    const successRate = dayJobs.length > 0 ? Math.round((dayJobs.filter(j => j.status === 'success').length / dayJobs.length) * 100) : null;
    return { ...point, jobRate: successRate };
  });

  const hasHealthEvidence = Boolean(hostResources) || hasDevices;
  const healthLevel = !hasHealthEvidence
    ? 'unknown'
    : hostResources?.status === 'critical' || unreadNotificationCount >= 5 || (hasDevices && onlinePct < 30)
    ? 'critical'
    : hostResources?.status === 'degraded' || unreadNotificationCount > 0 || (hasDevices && onlinePct < 60)
      ? 'degraded'
      : 'healthy';

  const healthBadgeStyle = healthLevel === 'unknown'
    ? 'bg-gray-100 text-gray-700 border-gray-200/60'
    : healthLevel === 'critical'
      ? 'bg-red-50 text-red-700 border-red-200/60'
      : healthLevel === 'degraded'
        ? 'bg-amber-50 text-amber-700 border-amber-200/60'
        : 'bg-emerald-50 text-emerald-700 border-emerald-200/60';

  const healthLabel = healthLevel === 'unknown'
    ? (language === 'zh' ? '状态未知' : 'Unknown')
    : healthLevel === 'critical'
      ? (language === 'zh' ? '严重告警' : 'Critical')
      : healthLevel === 'degraded'
        ? (language === 'zh' ? '存在预警' : 'Degraded')
        : (language === 'zh' ? '全网健康' : 'Healthy');

  const dashAgoSec = Math.round((Date.now() - dashLastRefresh.getTime()) / 1000);

  return (
    <div className="nx-page-shell flex flex-col h-full overflow-hidden">
      {/* ── 1. Modern Page Hero with Consolidated Actions ── */}
      <PageHero
        icon={LayoutDashboard}
        eyebrow={language === 'zh' ? `${systemInfo?.system_name || 'Nexora'} 运营总控台` : `${systemInfo?.system_name || 'Nexora'} Control Center`}
        title={t('networkOverview')}
        subtitle={language === 'zh' ? '全网基础设施实时健康感知、自动化编排与合规审计总览' : 'Real-time infrastructure health, automation orchestration and compliance overview'}
        actions={
          <div className="flex items-center gap-2.5 flex-wrap">
            {/* Refresh & Polling Micro-Capsule */}
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-white dark:bg-zinc-800 border border-gray-200/70 dark:border-zinc-700/60 shadow-2xs">
              <span className="text-[11px] text-gray-500 dark:text-zinc-400 font-mono font-medium">
                {dashAgoSec}s {language === 'zh' ? '前刷新' : 'ago'}
              </span>
              <span className="text-gray-200 dark:text-zinc-700">|</span>
              <button 
                onClick={handleManualRefresh} 
                disabled={isManualRefreshing}
                className="text-gray-500 hover:text-blue-600 dark:text-zinc-400 dark:hover:text-white transition-colors cursor-pointer"
                title={language === 'zh' ? '手动刷新' : 'Refresh Now'}
              >
                <RefreshCw size={12} className={isManualRefreshing ? 'animate-spin text-blue-600' : ''} />
              </button>
              <button 
                onClick={() => setAutoRefreshEnabled(!autoRefreshEnabled)} 
                className={`${autoRefreshEnabled ? 'text-emerald-500' : 'text-gray-400 dark:text-zinc-500'} hover:opacity-80 transition-colors cursor-pointer`}
                title={autoRefreshEnabled ? (language === 'zh' ? '已开启轮询(15s)' : 'Auto-polling on') : (language === 'zh' ? '轮询已暂停' : 'Paused')}
              >
                {autoRefreshEnabled ? <Play size={11} fill="currentColor" /> : <Pause size={11} fill="currentColor" />}
              </button>
            </div>

            {/* Health Status Pill */}
            <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-[11px] font-semibold ${healthBadgeStyle}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${healthLevel === 'healthy' ? 'bg-emerald-500' : healthLevel === 'degraded' ? 'bg-amber-500' : 'bg-red-500 animate-pulse'}`} />
              <span>{healthLabel}</span>
            </div>

            {/* Secondary Action: Platform Telemetry */}
            <button 
              onClick={() => navigate('/monitor/telemetry')}
              className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs font-semibold text-gray-700 dark:text-zinc-200 bg-white dark:bg-zinc-800 border border-gray-200/80 dark:border-zinc-700/70 hover:bg-gray-50 dark:hover:bg-zinc-700/50 shadow-2xs transition-all cursor-pointer"
            >
              <MonitorSmartphone size={13} className="text-gray-500 dark:text-zinc-400" />
              <span>{language === 'zh' ? '宿主机指标' : 'Host Telemetry'}</span>
            </button>

            {/* Primary Action: Run Automation */}
            <button 
              onClick={() => navigate('/automation/tasks')}
              className="flex items-center gap-1.5 px-4 py-1.5 rounded-full text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700 shadow-xs hover:shadow-sm transition-all cursor-pointer active:scale-98"
            >
              <Zap size={13} fill="currentColor" />
              <span>{t('openAutomation')}</span>
            </button>
          </div>
        }
      />

      <div className="flex-1 overflow-auto px-6 py-5 space-y-4">
        {/* ── 2. Standardized Bento KPI Grid (5 Cards) ── */}
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-3.5">
          {/* Card 1: Network Assets */}
          <div 
            onClick={() => navigate('/assets/network-devices')} 
            className="bg-white dark:bg-zinc-900/90 p-4 rounded-2xl border border-gray-200/70 dark:border-zinc-800/80 shadow-2xs hover:shadow-md hover:border-blue-500/30 transition-all duration-200 cursor-pointer group flex flex-col justify-between"
            role="button" 
            tabIndex={0}
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-gray-500 dark:text-zinc-400">{t('totalAssets')}</span>
              <div className="h-7 w-7 rounded-xl bg-blue-50 dark:bg-blue-950/30 text-blue-600 dark:text-blue-400 flex items-center justify-center group-hover:scale-110 transition-transform">
                <Server size={14} />
              </div>
            </div>
            <div className="mt-2.5">
              <div className="flex items-baseline gap-1">
                <span className="nx-kpi-value text-gray-900 dark:text-white">
                  {assetsTotal > 0 ? assetsTotal : devices.length}
                </span>
                <span className="text-xs font-medium text-gray-400">台</span>
              </div>
              <p className="text-[11px] text-gray-400 dark:text-zinc-500 mt-1 flex items-center gap-1">
                <span>{devices.length} 台设备已纳管</span>
              </p>
            </div>
          </div>

          {/* Card 2: Online Reachability */}
          <div 
            onClick={() => {
              const hasOffline = devices.some(d => d.status === 'offline');
              navigate(hasOffline ? '/inventory/devices?status=offline' : '/inventory/devices');
            }}
            className="bg-white dark:bg-zinc-900/90 p-4 rounded-2xl border border-gray-200/70 dark:border-zinc-800/80 shadow-2xs hover:shadow-md hover:border-emerald-500/30 transition-all duration-200 cursor-pointer group flex flex-col justify-between"
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-gray-500 dark:text-zinc-400">{t('onlineNodes')}</span>
              <div className="h-7 w-7 rounded-xl bg-emerald-50 dark:bg-emerald-950/30 text-emerald-600 dark:text-emerald-400 flex items-center justify-center group-hover:scale-110 transition-transform">
                <Activity size={14} />
              </div>
            </div>
            <div className="mt-2.5">
              <div className="flex items-baseline gap-1.5">
                <span className="nx-kpi-value text-gray-900 dark:text-white">{onlineCount}</span>
                <span className="text-xs font-medium text-gray-400">/ {devices.length}</span>
              </div>
              {/* Progress bar */}
              <div className="mt-2 w-full h-1.5 bg-gray-100 dark:bg-zinc-800 rounded-full overflow-hidden">
                <div 
                  className="h-full bg-emerald-500 rounded-full transition-all duration-500" 
                  style={{ width: `${hasDevices ? onlinePct : 0}%` }}
                />
              </div>
              <p className="text-[11px] font-medium text-emerald-600 dark:text-emerald-400 mt-1">
                {hasDevices ? `${onlinePct}% 在线达标` : '暂无节点'}
              </p>
            </div>
          </div>

          {/* Card 3: Compliance Baseline */}
          <div 
            onClick={() => navigate('/compliance')} 
            className="bg-white dark:bg-zinc-900/90 p-4 rounded-2xl border border-gray-200/70 dark:border-zinc-800/80 shadow-2xs hover:shadow-md hover:border-blue-500/30 transition-all duration-200 cursor-pointer group flex flex-col justify-between"
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-gray-500 dark:text-zinc-400">{t('complianceRate')}</span>
              <div className="h-7 w-7 rounded-xl bg-purple-50 dark:bg-purple-950/30 text-purple-600 dark:text-purple-400 flex items-center justify-center group-hover:scale-110 transition-transform">
                <ShieldCheck size={14} />
              </div>
            </div>
            <div className="mt-2.5">
              <div className="flex items-baseline gap-1">
                <span className="nx-kpi-value text-gray-900 dark:text-white">
                  {hasDevices && compPct > 0 ? `${compPct}%` : '100%'}
                </span>
              </div>
              <p className="text-[11px] text-gray-400 dark:text-zinc-500 mt-1">
                {hasDevices && compPct > 0 ? `${devices.filter(d => d.compliance === 'compliant').length} 台基线已核验` : '全网基准巡检已就绪'}
              </p>
            </div>
          </div>

          {/* Card 4: Automation Executions */}
          <div 
            onClick={() => navigate('/automation/history')} 
            className="bg-white dark:bg-zinc-900/90 p-4 rounded-2xl border border-gray-200/70 dark:border-zinc-800/80 shadow-2xs hover:shadow-md hover:border-blue-500/30 transition-all duration-200 cursor-pointer group flex flex-col justify-between"
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-gray-500 dark:text-zinc-400">{t('failedTasks')}</span>
              <div className="h-7 w-7 rounded-xl bg-amber-50 dark:bg-amber-950/30 text-amber-600 dark:text-amber-400 flex items-center justify-center group-hover:scale-110 transition-transform">
                <Zap size={14} />
              </div>
            </div>
            <div className="mt-2.5">
              <div className="flex items-baseline gap-1.5">
                <span className="nx-kpi-value text-gray-900 dark:text-white">
                  {jobs.length > 0 ? successJobsCount : 0}
                </span>
                <span className="text-xs font-medium text-gray-400">次成功</span>
              </div>
              <p className="text-[11px] text-gray-400 dark:text-zinc-500 mt-1">
                {failedCount24h > 0 ? (
                  <span className="text-rose-600 font-medium">{failedCount24h} 次作业需关注</span>
                ) : (
                  <span className="text-emerald-600 font-medium">近 24H 零失败</span>
                )}
              </p>
            </div>
          </div>

          {/* Card 5: Host Telemetry (Sleek Horizontal Meters) */}
          <div 
            onClick={() => navigate('/monitor/telemetry')} 
            className="col-span-2 md:col-span-1 bg-white dark:bg-zinc-900/90 p-4 rounded-2xl border border-gray-200/70 dark:border-zinc-800/80 shadow-2xs hover:shadow-md hover:border-blue-500/30 transition-all duration-200 cursor-pointer group flex flex-col justify-between"
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-gray-500 dark:text-zinc-400">{language === 'zh' ? '宿主机性能' : 'Host Vitals'}</span>
              <div className="h-7 w-7 rounded-xl bg-slate-100 dark:bg-zinc-800 text-gray-600 dark:text-zinc-300 flex items-center justify-center group-hover:scale-110 transition-transform">
                <MonitorSmartphone size={14} />
              </div>
            </div>
            
            {hostResources ? (
              <div className="mt-2 space-y-1.5">
                {[
                  { label: 'CPU', val: Math.round(hostResources.cpu_percent || 0), max: 100, color: 'bg-blue-500' },
                  { label: 'MEM', val: Math.round(hostResources.memory_percent || 0), max: 100, color: (hostResources.memory_percent || 0) > 85 ? 'bg-amber-500' : 'bg-indigo-500' },
                  { label: 'DISK', val: Math.round(hostResources.disk_percent || 0), max: 100, color: 'bg-emerald-500' },
                ].map(m => (
                  <div key={m.label} className="flex items-center gap-2 text-[10px]">
                    <span className="w-7 font-mono font-bold text-gray-400">{m.label}</span>
                    <div className="flex-1 h-1.5 bg-gray-100 dark:bg-zinc-800 rounded-full overflow-hidden">
                      <div className={`h-full rounded-full ${m.color}`} style={{ width: `${m.val}%` }} />
                    </div>
                    <span className="w-7 text-right font-mono font-semibold text-gray-700 dark:text-zinc-300">{m.val}%</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-gray-400 mt-2">就绪</p>
            )}
          </div>
        </div>

        {/* ── 3. Actionable Incident Stream Banner (If alerts exist) ── */}
        {unreadNotificationCount > 0 && (
          <div 
            onClick={() => navigate('/alerts/desk')} 
            className="bg-white dark:bg-zinc-900/90 rounded-2xl border border-rose-200/70 dark:border-rose-950/50 shadow-2xs p-3.5 sm:px-5 flex items-center justify-between cursor-pointer hover:shadow-md transition-all group duration-200"
          >
            <div className="flex items-center gap-3.5 min-w-0 flex-1">
              <div className="h-8 w-8 rounded-xl bg-rose-50 dark:bg-rose-950/40 text-rose-600 flex items-center justify-center flex-shrink-0 group-hover:scale-105 transition-transform">
                <Bell size={16} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold text-gray-900 dark:text-white">待处理告警</span>
                  {criticalAlerts > 0 && (
                    <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-red-100 text-red-700">
                      {criticalAlerts} 严重
                    </span>
                  )}
                  {majorAlerts > 0 && (
                    <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-100 text-amber-700">
                      {majorAlerts} 重要
                    </span>
                  )}
                </div>
                <p className="text-xs text-gray-500 dark:text-zinc-400 mt-0.5 truncate">
                  {latestAlert ? `${latestAlert.title || latestAlert.message}` : '全网监控告警中心有新事件'}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-1.5 text-xs font-semibold text-blue-600 group-hover:translate-x-0.5 transition-transform shrink-0 ml-3">
              <span>前往处置</span>
              <ChevronRight size={14} />
            </div>
          </div>
        )}

        {/* ── 4. Charts: Compliance Trend & Multi-Vendor Fleet Matrix ── */}
        <div className="grid grid-cols-12 gap-3.5">
          {/* Trend Chart (8 Cols) */}
          <div className="col-span-12 lg:col-span-8 bg-white dark:bg-zinc-900/90 rounded-2xl border border-gray-200/70 dark:border-zinc-800/80 p-5 shadow-2xs">
            <div className="flex items-center justify-between mb-5 flex-wrap gap-2">
              <div>
                <h3 className="text-sm font-bold text-gray-900 dark:text-white flex items-center gap-2">
                  <TrendingUp size={16} className="text-blue-600" />
                  <span>{t('complianceTrend')}</span>
                </h3>
                <p className="text-xs text-gray-400 dark:text-zinc-500 mt-0.5">{t('complianceTrendSub')}</p>
              </div>
              
              <div className="flex items-center gap-2">
                {/* Legend Toggles */}
                <div className="flex items-center gap-3 mr-2">
                  <button 
                    onClick={() => setShowComplianceLine(!showComplianceLine)}
                    className={`flex items-center gap-1.5 text-xs font-medium cursor-pointer transition-opacity ${showComplianceLine ? 'text-gray-700 dark:text-zinc-300' : 'opacity-40'}`}
                  >
                    <span className="w-2.5 h-2.5 rounded-full bg-blue-600" />
                    <span>合规率</span>
                  </button>
                  <button 
                    onClick={() => setShowJobSuccessLine(!showJobSuccessLine)}
                    className={`flex items-center gap-1.5 text-xs font-medium cursor-pointer transition-opacity ${showJobSuccessLine ? 'text-gray-700 dark:text-zinc-300' : 'opacity-40'}`}
                  >
                    <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
                    <span>作业成功率</span>
                  </button>
                </div>

                {/* Days Filter Pills */}
                <div className="flex items-center p-0.5 rounded-xl bg-gray-100 dark:bg-zinc-800">
                  <button 
                    onClick={() => setTrendDays(7)} 
                    className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer ${trendDays === 7 ? 'bg-white dark:bg-zinc-700 text-gray-900 dark:text-white shadow-2xs' : 'text-gray-500 dark:text-zinc-400 hover:text-gray-900'}`}
                  >
                    7天
                  </button>
                  <button 
                    onClick={() => setTrendDays(30)} 
                    className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer ${trendDays === 30 ? 'bg-white dark:bg-zinc-700 text-gray-900 dark:text-white shadow-2xs' : 'text-gray-500 dark:text-zinc-400 hover:text-gray-900'}`}
                  >
                    30天
                  </button>
                </div>
              </div>
            </div>

            <div className="h-[250px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={jobSuccessTrend}>
                  <defs>
                    <linearGradient id="colorRateBlue" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#2563eb" stopOpacity={0.25}/>
                      <stop offset="95%" stopColor="#2563eb" stopOpacity={0.01}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={ct.grid} />
                  <XAxis
                    dataKey="name"
                    axisLine={false}
                    tickLine={false}
                    tick={{ fontSize: 10, fill: ct.axis, fontWeight: 500 }}
                    dy={8}
                    interval={trendDays > 7 ? Math.floor(trendDays / 7) - 1 : 0}
                  />
                  <YAxis
                    axisLine={false}
                    tickLine={false}
                    tick={{ fontSize: 10, fill: ct.axis, fontWeight: 500 }}
                    domain={useNarrowDomain ? [yDomainLow, yDomainHigh] : [0, 100]}
                  />
                  <Tooltip
                    contentStyle={{ borderRadius: '14px', border: 'none', boxShadow: ct.tooltipShadowLg, padding: '10px 14px', background: ct.tooltipBg, color: ct.tooltipText }}
                    formatter={(value: number, name: string) => [
                      `${value}%`,
                      name === 'rate' ? '合规率' : '作业成功率',
                    ]}
                  />
                  {trendAvg > 0 && (
                    <ReferenceLine y={trendAvg} stroke={ct.reference} strokeDasharray="4 4" strokeWidth={1} label={{ value: `均值 ${trendAvg}%`, position: 'insideTopRight', fill: ct.reference, fontSize: 10 }} />
                  )}
                  {showComplianceLine && (
                    <Area type="monotone" dataKey="rate" stroke="#2563eb" strokeWidth={2.5} fillOpacity={1} fill="url(#colorRateBlue)" name="rate" />
                  )}
                  {showJobSuccessLine && (
                    <Area type="monotone" dataKey="jobRate" stroke="#10b981" strokeWidth={2} strokeDasharray="4 4" fillOpacity={0} dot={false} connectNulls name="jobRate" />
                  )}
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Fleet Platform Matrix (4 Cols) */}
          <div className="col-span-12 lg:col-span-4 bg-white dark:bg-zinc-900/90 rounded-2xl border border-gray-200/70 dark:border-zinc-800/80 p-5 shadow-2xs flex flex-col justify-between">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-bold text-gray-900 dark:text-white flex items-center gap-2">
                <Layers size={16} className="text-emerald-600" />
                <span>{t('platformDistribution')}</span>
              </h3>
              <span className="text-[11px] font-semibold text-gray-400 font-mono">
                {devices.length} 台在网
              </span>
            </div>

            <div className="h-[160px] w-full relative flex items-center justify-center">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie 
                    data={platformData} 
                    innerRadius={54} 
                    outerRadius={72} 
                    paddingAngle={platformData.length > 1 ? 4 : 0} 
                    cornerRadius={3} 
                    dataKey="value" 
                    stroke="none"
                  >
                    {platformData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={{ background: ct.tooltipBg, color: ct.tooltipText, borderColor: ct.tooltipBorder, borderRadius: 12, boxShadow: ct.tooltipShadow }} formatter={(value: number, name: string) => [`${value}%`, name]} />
                </PieChart>
              </ResponsiveContainer>
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                <span className="text-2xl font-extrabold text-gray-900 dark:text-white">{devices.length}</span>
                <span className="text-[10px] text-gray-400 font-semibold uppercase">总纳管</span>
              </div>
            </div>

            {/* Platform breakdown list */}
            <div className="mt-3 space-y-2">
              {platformData.map((item, i) => (
                <div 
                  key={i} 
                  onClick={() => {
                    const pKey = (item as any).platform;
                    navigate(pKey ? `/inventory/devices?platform=${pKey}` : '/inventory/devices');
                  }}
                  className="flex items-center justify-between px-3 py-2 rounded-xl bg-gray-50 dark:bg-zinc-800/60 hover:bg-blue-50/60 dark:hover:bg-zinc-700/60 cursor-pointer transition-all group"
                >
                  <div className="flex items-center gap-2.5">
                    <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: item.color }} />
                    <span className="text-xs font-semibold text-gray-700 dark:text-zinc-300 group-hover:text-blue-600 transition-colors">{item.name}</span>
                  </div>
                  <span className="text-xs font-bold text-gray-900 dark:text-white font-mono">{item.value}%</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ── 5. Recent Activity & Upcoming Jobs ── */}
        <div className="grid grid-cols-12 gap-3.5">
          {/* Recent Activity */}
          <div className="col-span-12 lg:col-span-7 bg-white dark:bg-zinc-900/90 rounded-2xl border border-gray-200/70 dark:border-zinc-800/80 p-5 shadow-2xs">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-sm font-bold text-gray-900 dark:text-white flex items-center gap-2">
                  <History size={16} className="text-gray-500" />
                  <span>{t('recentActivity')}</span>
                </h3>
                <p className="text-xs text-gray-400 mt-0.5">{t('recentActivitySub')}</p>
              </div>
              <button 
                onClick={() => navigate('/automation/history')}
                className="text-xs font-semibold text-blue-600 hover:text-blue-700 flex items-center gap-0.5 cursor-pointer"
              >
                <span>全部日志</span>
                <ArrowUpRight size={13} />
              </button>
            </div>

            <div className="space-y-2">
              {jobs.slice(0, 4).map(job => (
                <div 
                  key={job.id} 
                  onClick={() => navigate('/automation/history')}
                  className="flex items-center justify-between p-3 rounded-xl hover:bg-gray-50 dark:hover:bg-zinc-800/60 transition-all border border-transparent hover:border-gray-200/50 cursor-pointer group"
                >
                  <div className="flex items-center gap-3">
                    <div className={`h-8 w-8 rounded-xl flex items-center justify-center ${
                      job.status === 'success' ? 'bg-emerald-50 text-emerald-600' :
                      job.status === 'failed' ? 'bg-rose-50 text-rose-600' : 'bg-blue-50 text-blue-600'
                    }`}>
                      <Zap size={14} />
                    </div>
                    <div>
                      <p className="text-xs font-bold text-gray-800 dark:text-zinc-100 group-hover:text-blue-600 transition-colors">{job.task_name}</p>
                      <p className="text-[10px] text-gray-400 mt-0.5 font-mono">{new Date(job.created_at).toLocaleString()}</p>
                    </div>
                  </div>
                  <span className={`text-[10px] font-bold px-2.5 py-0.5 rounded-full uppercase ${
                    job.status === 'success' ? 'bg-emerald-50 text-emerald-700 border border-emerald-200/60' : 
                    job.status === 'failed' ? 'bg-rose-50 text-rose-700 border border-rose-200/60' : 
                    'bg-blue-50 text-blue-700 border border-blue-200/60'
                  }`}>
                    {job.status}
                  </span>
                </div>
              ))}
              {jobs.length === 0 && (
                <div className="text-center py-6 text-xs text-gray-400">
                  暂无近期任务记录
                </div>
              )}
            </div>
          </div>

          {/* Upcoming Scheduled Tasks */}
          <div className="col-span-12 lg:col-span-5 bg-white dark:bg-zinc-900/90 rounded-2xl border border-gray-200/70 dark:border-zinc-800/80 p-5 shadow-2xs">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-bold text-gray-900 dark:text-white flex items-center gap-2">
                <Clock size={16} className="text-amber-500" />
                <span>{t('upcomingTasks')}</span>
              </h3>
              <button 
                onClick={() => navigate('/automation/scheduled-jobs')}
                className="text-xs font-semibold text-blue-600 hover:text-blue-700 flex items-center gap-0.5 cursor-pointer"
              >
                <span>计划调度</span>
                <ArrowUpRight size={13} />
              </button>
            </div>

            <div className="space-y-2">
              {scheduledTasks.filter(st => st.status === 'active').slice(0, 3).map(task => (
                <div key={task.id} className="flex items-center justify-between p-3 bg-gray-50/70 dark:bg-zinc-800/40 rounded-xl border border-gray-100 dark:border-zinc-800/60">
                  <div className="flex items-center gap-3">
                    <div className="h-8 w-8 bg-amber-50 dark:bg-amber-950/40 text-amber-600 rounded-xl flex items-center justify-center">
                      <Clock size={14} />
                    </div>
                    <div>
                      <p className="text-xs font-bold text-gray-800 dark:text-zinc-100">{task.task_name}</p>
                      <p className="text-[10px] text-gray-400 font-mono mt-0.5">{task.scheduled_time || '周期调度'}</p>
                    </div>
                  </div>
                  <span className="text-[10px] font-semibold px-2 py-0.5 rounded-lg bg-blue-50 text-blue-600">
                    {task.schedule_type === 'recurring' ? '周期' : '单次'}
                  </span>
                </div>
              ))}
              {scheduledTasks.filter(st => st.status === 'active').length === 0 && (
                <div className="text-center py-6 text-xs text-gray-400">
                  暂无进行中的定时调度
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default DashboardTab;
