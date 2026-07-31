import React from 'react';
import { Server, Activity, ShieldCheck, AlertCircle, AlertTriangle, Bell, TrendingUp, PieChart as PieChartIcon, History, Clock, ChevronRight, X, Zap, MonitorSmartphone, Cpu, HardDrive, MemoryStick, Play, CalendarPlus, LayoutDashboard, Pause, RefreshCw } from 'lucide-react';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, PieChart, Pie, Cell } from 'recharts';
import type { Device, Job, ScheduledTask, HostResourceSnapshot, NotificationItem } from '../types';
import { sectionHeaderRowClass, primaryActionBtnClass, secondaryActionBtnClass } from '../components/shared';
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

  const hasDevices = devices.length > 0;

  // Find latest unread notification to display message context
  const latestAlert = [...notifications]
    .filter(n => !n.read)
    .sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime())[0];

  const latestAlertColor = latestAlert?.severity === 'critical'
    ? 'text-red-600 dark:text-red-400'
    : latestAlert?.severity === 'major' || latestAlert?.severity === 'high'
      ? 'text-orange-600 dark:text-orange-400'
      : 'text-black/45 dark:text-white/40';

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
  // Use narrow domain only when data range is tight (span < 30)
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
    : hostResources?.status === 'critical' || unreadNotificationCount >= 5 || (hasDevices && onlinePct < 30) || (hasDevices && compPct === 0)
    ? 'critical'
    : hostResources?.status === 'degraded' || unreadNotificationCount > 0 || (hasDevices && onlinePct < 60) || (hasDevices && compPct < 50)
      ? 'degraded'
      : 'healthy';
  const healthLabel = healthLevel === 'unknown'
    ? (language === 'zh' ? '状态未知' : 'Status Unknown')
    : healthLevel === 'critical'
      ? t('systemCritical')
      : healthLevel === 'degraded'
        ? t('systemDegraded')
        : t('systemHealthy');
  const healthColor = healthLevel === 'unknown'
    ? 'bg-slate-100 text-slate-600'
    : healthLevel === 'critical'
      ? 'bg-red-100 text-red-700'
      : healthLevel === 'degraded'
        ? 'bg-orange-100 text-orange-700'
        : 'bg-emerald-100 text-emerald-700';
  const hostStatusText = hostResources?.status === 'critical'
    ? (language === 'zh' ? '宿主机严重' : 'Host Critical')
    : hostResources?.status === 'degraded'
      ? (language === 'zh' ? '宿主机告警' : 'Host Warning')
      : (language === 'zh' ? '宿主机正常' : 'Host Healthy');

  const dashAgoSec = Math.round((Date.now() - dashLastRefresh.getTime()) / 1000);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHero
        icon={LayoutDashboard}
        eyebrow={language === 'zh' ? `${systemInfo?.system_name || 'Nexora'} 运营中心` : `${systemInfo?.system_name || 'Nexora'} Command Center`}
        title={t('networkOverview')}
        subtitle={t('dashboardSubtitle')}
        actions={
          <div className="flex items-center gap-2 flex-wrap">
            <style dangerouslySetInnerHTML={{__html: `
              @keyframes shimmer {
                100% { transform: translateX(100%); }
              }
              @keyframes breathe-glow {
                0%, 100% { box-shadow: 0 0 4px rgba(239, 68, 68, 0.15), inset 0 0 2px rgba(239, 68, 68, 0.08); border-color: rgba(239, 68, 68, 0.15); }
                50% { box-shadow: 0 0 12px rgba(239, 68, 68, 0.4), inset 0 0 6px rgba(239, 68, 68, 0.2); border-color: rgba(239, 68, 68, 0.35); }
              }
            `}} />
            <div className="flex items-center gap-1 px-2.5 py-1.5 rounded-xl bg-black/[0.03] dark:bg-white/[0.03] border border-black/5 dark:border-white/5">
              <span className="text-[10px] text-black/50 dark:text-white/40 font-semibold select-none">
                {t('lastRefreshed')} {dashAgoSec}s {language === 'zh' ? '前' : 'ago'}
              </span>
              <div className="h-3 w-[1px] bg-black/10 dark:bg-white/10 mx-1.5" />
              <button 
                onClick={handleManualRefresh} 
                disabled={isManualRefreshing}
                className="text-black/45 dark:text-white/40 hover:text-black dark:hover:text-white transition-colors flex items-center"
                title={language === 'zh' ? '手动刷新' : 'Refresh Now'}
              >
                <RefreshCw size={11} className={`${isManualRefreshing ? 'animate-spin' : ''}`} />
              </button>
              <div className="h-3 w-[1px] bg-black/10 dark:bg-white/10 mx-1.5" />
              <button 
                onClick={() => setAutoRefreshEnabled(!autoRefreshEnabled)} 
                className={`${autoRefreshEnabled ? 'text-emerald-500' : 'text-black/30 dark:text-white/30'} hover:opacity-80 transition-colors flex items-center`}
                title={autoRefreshEnabled ? (language === 'zh' ? '已开启自动刷新(15s)' : 'Auto-refresh active(15s)') : (language === 'zh' ? '自动刷新已暂停' : 'Auto-refresh paused')}
              >
                {autoRefreshEnabled ? <Play size={11} fill="currentColor" /> : <Pause size={11} fill="currentColor" />}
              </button>
            </div>
            {hostResources && (
              <span className="px-3 py-1.5 text-[10px] font-bold rounded-xl uppercase tracking-wider bg-black/[0.03] dark:bg-white/[0.03] border border-black/5 dark:border-white/5 text-[#00172D] dark:text-white/70">
                {hostStatusText}
              </span>
            )}
            <span className={`px-3 py-1.5 text-[10px] font-bold rounded-xl uppercase tracking-wider ${healthColor} ${healthLevel === 'critical' ? 'animate-pulse' : ''}`}>
              {healthLabel}
            </span>
            <button onClick={() => navigate('/monitor/telemetry')} className={secondaryActionBtnClass + ' !py-1.5 !text-xs !rounded-xl'}>
              {language === 'zh' ? '查看平台资源' : 'View Host Resources'}
            </button>
            <button onClick={() => navigate('/automation/tasks')} className={primaryActionBtnClass + ' !py-1.5 !text-xs !rounded-xl'}>
              {t('openAutomation')}
            </button>
          </div>
        }
      />

      <div className="flex-1 overflow-auto px-6 py-5 space-y-5">
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-3 md:gap-4">
        {/* Total Assets */}
        <div onClick={() => navigate('/assets/network-devices')} className="bg-white dark:bg-[#2d2d2d] px-5 py-4 rounded-xl shadow-[0_4px_16px_rgba(0,0,0,0.04)] border border-[#e5e5e5] dark:border-white/5 flex items-center justify-between group hover:shadow-md transition-all duration-200 cursor-pointer" role="button" tabIndex={0} aria-label={t('totalAssets')}>
          <div>
            <p className="text-xs font-bold uppercase tracking-widest text-black/30 dark:text-white/30 mb-1">{t('totalAssets')}</p>
            <p className="text-3xl font-bold monitoring-data text-[#0078d4] dark:text-[#0078d4]">{assetsTotal}</p>
          </div>
          <div className="p-3 rounded-xl bg-[#0078d4]/5 dark:bg-[#0078d4]/20 text-[#0078d4] group-hover:scale-105 transition-transform">
            <Server size={24} />
          </div>
        </div>

        {/* Online Nodes — with inline micro progress bar */}
        <div 
          onClick={() => {
            const hasOffline = devices.some(d => d.status === 'offline');
            if (hasOffline) {
              navigate('/inventory/devices?status=offline');
            } else {
              navigate('/inventory/devices');
            }
          }}
          className={`bg-white dark:bg-[#2d2d2d] px-5 py-4 rounded-xl shadow-[0_4px_16px_rgba(0,0,0,0.04)] border border-[#e5e5e5] dark:border-white/5 group hover:shadow-md transition-all duration-200 cursor-pointer ${
            hasDevices ? (onlinePct < 30 ? 'border-l-[3px] border-l-red-500' : onlinePct < 60 ? 'border-l-[3px] border-l-orange-400' : '') : ''
          }`}
        >
          <div className="flex items-center justify-between">
            <div className="min-w-0">
              <p className="text-xs font-bold uppercase tracking-widest text-black/30 dark:text-white/30 mb-1">{t('onlineNodes')}</p>
              <div className="flex items-baseline gap-1.5">
                <span className={`text-3xl font-bold monitoring-data ${
                  hasDevices ? (onlinePct < 30 ? 'text-red-600 dark:text-red-400' : onlinePct < 60 ? 'text-orange-600 dark:text-orange-400' : 'text-emerald-600 dark:text-emerald-400') : 'text-[#0078d4] dark:text-[#0078d4]'
                }`}>{onlineCount}</span>
                <span className="text-sm text-black/30 dark:text-white/30 font-medium">/ {devices.length}</span>
              </div>
            </div>
            <div className={`p-3 rounded-xl ${
              hasDevices 
                ? (onlinePct < 30 ? 'bg-red-50 dark:bg-red-950/30 text-red-600 dark:text-red-400' : onlinePct < 60 ? 'bg-orange-50 dark:bg-orange-950/30 text-orange-600 dark:text-orange-400' : 'bg-emerald-50 dark:bg-emerald-950/30 text-emerald-600 dark:text-emerald-400')
                : 'bg-slate-50 dark:bg-slate-900 text-slate-500'
            } group-hover:scale-105 transition-transform`}>
              <Activity size={24} />
            </div>
          </div>
          {/* Micro progress bar */}
          <div className="mt-2 w-full h-1.5 bg-black/5 dark:bg-white/5 rounded-full overflow-hidden relative">
            <div className={`h-full rounded-full transition-all duration-700 relative overflow-hidden ${
              hasDevices ? (onlinePct < 30 ? 'bg-red-500' : onlinePct < 60 ? 'bg-orange-400' : 'bg-emerald-500') : 'bg-slate-300 dark:bg-slate-700'
            }`} style={{ width: `${hasDevices ? onlinePct : 0}%` }}>
              <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/30 to-transparent animate-[shimmer_2.5s_infinite] -translate-x-full" />
            </div>
          </div>
          <p className="text-[10px] text-black/30 dark:text-white/40 font-semibold mt-1.5">
            {hasDevices 
              ? `${onlinePct}% ${language === 'zh' ? '在线' : 'online'}` 
              : (language === 'zh' ? '暂无设备' : 'No devices')}
          </p>
        </div>

        {/* Compliance */}
        <div onClick={() => navigate('/compliance')} className={`bg-white dark:bg-[#2d2d2d] px-5 py-4 rounded-xl shadow-[0_4px_16px_rgba(0,0,0,0.04)] border border-[#e5e5e5] dark:border-white/5 flex items-center justify-between group hover:shadow-md transition-all duration-200 cursor-pointer ${
          hasDevices ? (compPct === 0 ? 'border-l-[3px] border-l-red-500' : compPct < 50 ? 'border-l-[3px] border-l-orange-400' : '') : ''
        }`}>
          <div>
            <p className="text-xs font-bold uppercase tracking-widest text-black/30 dark:text-white/30 mb-1">{t('complianceRate')}</p>
            <p className={`text-3xl font-bold monitoring-data ${
              hasDevices ? (compPct === 0 ? 'text-red-600 dark:text-red-400' : compPct < 50 ? 'text-orange-600 dark:text-orange-400' : 'text-[#0078d4] dark:text-[#0078d4]') : 'text-[#0078d4] dark:text-[#0078d4]'
            }`}>{hasDevices ? `${compPct}%` : '--'}</p>
          </div>
          <div className={`p-3 rounded-xl ${
            hasDevices 
              ? (compPct === 0 ? 'bg-red-50 dark:bg-red-950/30 text-red-600 dark:text-red-400' : compPct < 50 ? 'bg-orange-50 dark:bg-orange-950/30 text-orange-600 dark:text-orange-400' : 'bg-[#0078d4]/5 dark:bg-[#0078d4]/20 text-[#0078d4] dark:text-[#0078d4]')
              : 'bg-slate-50 dark:bg-slate-900 text-slate-500'
          } group-hover:scale-105 transition-transform`}>
            <ShieldCheck size={24} />
          </div>
        </div>

        {/* Failed Tasks (24h) */}
        <div onClick={() => navigate('/automation/history')} className={`bg-white dark:bg-[#2d2d2d] px-5 py-4 rounded-xl shadow-[0_4px_16px_rgba(0,0,0,0.04)] border border-[#e5e5e5] dark:border-white/5 flex items-center justify-between group hover:shadow-md transition-all duration-200 cursor-pointer ${failedCount24h > 0 ? 'border-l-[3px] border-l-red-500' : ''}`}>
          <div>
            <p className="text-xs font-bold uppercase tracking-widest text-black/30 dark:text-white/30 mb-1">{t('failedTasks')}</p>
            <div className="flex items-baseline gap-1.5">
              <span className={`text-3xl font-bold monitoring-data ${failedCount24h > 0 ? 'text-red-600 dark:text-red-400' : 'text-black/40 dark:text-white/30'}`}>{failedCount24h}</span>
              <span className="text-[10px] text-black/25 dark:text-white/40 font-bold">24h</span>
            </div>
          </div>
          <div className={`p-3 rounded-xl ${failedCount24h > 0 ? 'bg-red-50 dark:bg-red-950/30 text-red-600 dark:text-red-400' : 'bg-black/5 dark:bg-white/5 text-black/40 dark:text-white/40'} group-hover:scale-105 transition-transform`}>
            <AlertCircle size={24} />
          </div>
        </div>

        {/* Platform Host — expanded with circular SVG gauge charts */}
        <div onClick={() => navigate('/monitor/telemetry')} className={`col-span-2 md:col-span-1 bg-white dark:bg-[#2d2d2d] px-5 py-4 rounded-xl shadow-[0_4px_16px_rgba(0,0,0,0.04)] border border-[#e5e5e5] dark:border-white/5 group hover:shadow-md transition-all duration-200 cursor-pointer ${hostResources?.status === 'critical' ? 'border-l-[3px] border-l-red-500' : hostResources?.status === 'degraded' ? 'border-l-[3px] border-l-orange-400' : ''}`}>
          <div className="flex items-center justify-between mb-1.5">
            <p className="text-xs font-bold uppercase tracking-widest text-black/30 dark:text-white/30">{language === 'zh' ? '平台宿主机' : 'Platform Host'}</p>
            <div className={`p-2 rounded-lg ${hostResources?.status === 'critical' ? 'bg-red-50 dark:bg-red-950/30 text-red-600 dark:text-red-400' : hostResources?.status === 'degraded' ? 'bg-orange-50 dark:bg-orange-950/30 text-orange-600 dark:text-orange-400' : 'bg-[#0078d4]/5 dark:bg-[#0078d4]/20 text-[#0078d4] dark:text-[#0078d4]'} group-hover:scale-105 transition-transform`}>
              <MonitorSmartphone size={16} />
            </div>
          </div>
          {hostResources ? (
            <div className="flex items-center justify-around gap-1 mt-1">
              {[
                { label: 'CPU', value: hostResources.cpu_percent || 0 },
                { label: 'MEM', value: hostResources.memory_percent || 0 },
                { label: 'DISK', value: hostResources.disk_percent || 0 },
              ].map(res => {
                const radius = 14;
                const circ = 2 * Math.PI * radius;
                const strokePct = circ * (1 - res.value / 100);
                const strokeColor = res.value > 80 ? 'stroke-red-500' : res.value > 65 ? 'stroke-orange-400' : 'stroke-[#0078d4]';
                const textTone = res.value > 80 ? 'text-red-500 font-extrabold' : res.value > 65 ? 'text-orange-500 font-bold' : 'text-[#0078d4] dark:text-[#0078d4] font-bold';
                return (
                  <div key={res.label} className="flex flex-col items-center">
                    <div className="relative w-10 h-10 flex items-center justify-center">
                      <svg className="w-10 h-10 transform -rotate-90">
                        <circle cx="20" cy="20" r={radius} className="stroke-black/5 dark:stroke-white/5 fill-transparent" strokeWidth="2.5" />
                        <circle 
                           cx="20" 
                           cy="20" 
                           r={radius} 
                           className={`fill-transparent ${strokeColor} transition-all duration-700`} 
                           strokeWidth="2.5" 
                           strokeDasharray={circ} 
                           strokeDashoffset={strokePct}
                           strokeLinecap="round"
                        />
                      </svg>
                      <span className={`absolute text-[8px] tracking-tighter ${textTone}`}>{Math.round(res.value)}%</span>
                    </div>
                    <span className="text-[8px] font-extrabold text-black/35 dark:text-white/40 uppercase mt-0.5">{res.label}</span>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="text-2xl font-bold text-black/20 dark:text-white/20 monitoring-data">--</p>
          )}
        </div>
      </div>

      {/* Alert Summary Strip */}
      {unreadNotificationCount > 0 && (
        <div 
          onClick={() => navigate('/alerts/desk')} 
          className="bg-white dark:bg-[#2d2d2d] rounded-xl border border-[#e5e5e5] dark:border-white/5 shadow-[0_4px_16px_rgba(0,0,0,0.04)] px-6 py-4 flex items-center justify-between cursor-pointer hover:shadow-md transition-all group duration-200"
        >
          <div className="flex items-center gap-4 flex-1 min-w-0">
            <div className="p-2.5 rounded-xl bg-red-50 dark:bg-red-950/20 text-red-600 dark:text-red-400 group-hover:scale-110 transition-transform">
              <Bell size={20} />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-bold text-[#00172D] dark:text-white">{t('activeAlertsShort')}</p>
              <p className={`text-[10px] font-semibold mt-0.5 truncate max-w-[200px] sm:max-w-[400px] md:max-w-[600px] ${latestAlertColor}`}>
                {latestAlert 
                  ? `${language === 'zh' ? '最新告警' : 'Latest'}: ${latestAlert.title || latestAlert.message}`
                  : (language === 'zh' ? '点击查看告警中心' : 'Click to view Alert Center')}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0 flex-wrap">
            {criticalAlerts > 0 && (
              <span className="flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold bg-red-100 dark:bg-red-950/40 text-red-700 dark:text-red-300">
                <AlertCircle size={12} /> {criticalAlerts} {language === 'zh' ? '严重' : 'Critical'}
              </span>
            )}
            {majorAlerts > 0 && (
              <span className="flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold bg-orange-100 dark:bg-orange-950/40 text-orange-700 dark:text-orange-300">
                <AlertTriangle size={12} /> {majorAlerts} {language === 'zh' ? '重要' : 'Major'}
              </span>
            )}
            {warningAlerts > 0 && (
              <span className="flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold bg-amber-100 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300">
                {warningAlerts} {language === 'zh' ? '警告' : 'Warning'}
              </span>
            )}
            {infoAlerts > 0 && (
              <span className="px-2.5 py-1 rounded-full text-[10px] font-bold bg-blue-100 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300">
                {infoAlerts} {language === 'zh' ? '信息' : 'Info'}
              </span>
            )}
            <ChevronRight size={16} className="text-black/20 dark:text-white/20 group-hover:text-black/40 dark:group-hover:text-white/40 transition-colors" />
          </div>
        </div>
      )}

      <div className="grid grid-cols-12 gap-3 md:gap-4">
        <div className="col-span-12 lg:col-span-8 bg-white dark:bg-[#2d2d2d] rounded-xl border border-[#e5e5e5] dark:border-white/5 p-4 md:p-6 shadow-[0_4px_16px_rgba(0,0,0,0.04)]">
          <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
            <div>
              <h3 className="text-sm font-bold text-[#00172D] dark:text-white flex items-center gap-2">
                <TrendingUp size={18} className="text-[#0078d4]" />
                {t('complianceTrend')}
              </h3>
              <p className="text-xs text-black/40 dark:text-white/40 mt-0.5">{t('complianceTrendSub')}</p>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <button 
                onClick={() => setShowComplianceLine(!showComplianceLine)}
                className={`flex items-center gap-1.5 mr-2 px-2 py-1 rounded-lg hover:bg-black/5 dark:hover:bg-white/5 transition-all select-none ${showComplianceLine ? '' : 'opacity-40'}`}
                title={language === 'zh' ? '点击显示/隐藏合规率' : 'Click to Toggle Compliance Rate'}
              >
                <span className="w-3.5 h-0.5 bg-[#0078d4] rounded-full block" />
                <span className="text-[9px] font-bold text-black/50 dark:text-white/50">{ language === 'zh' ? '合规率' : 'Compliance' }</span>
              </button>
              <button 
                onClick={() => setShowJobSuccessLine(!showJobSuccessLine)}
                className={`flex items-center gap-1.5 mr-3 px-2 py-1 rounded-lg hover:bg-black/5 dark:hover:bg-white/5 transition-all select-none ${showJobSuccessLine ? '' : 'opacity-40'}`}
                title={language === 'zh' ? '点击显示/隐藏作业成功率' : 'Click to Toggle Job Success Rate'}
              >
                <span className="w-3.5 h-0.5 bg-emerald-500 rounded-full block" style={{ backgroundImage: 'repeating-linear-gradient(90deg, #10b981, #10b981 3px, transparent 3px, transparent 6px)' }} />
                <span className="text-[9px] font-bold text-black/50 dark:text-white/50">{ language === 'zh' ? '作业成功率' : 'Job Success' }</span>
              </button>
              <button onClick={() => setTrendDays(7)} className={`px-2.5 py-1 rounded-lg text-[10px] font-bold uppercase transition-all ${trendDays === 7 ? 'bg-black/10 dark:bg-white/10 text-black/75 dark:text-white/80' : 'text-black/40 dark:text-white/40 hover:bg-black/5 dark:hover:bg-white/5'}`}>{t('days7')}</button>
              <button onClick={() => setTrendDays(30)} className={`px-2.5 py-1 rounded-lg text-[10px] font-bold uppercase transition-all ${trendDays === 30 ? 'bg-black/10 dark:bg-white/10 text-black/75 dark:text-white/80' : 'text-black/40 dark:text-white/40 hover:bg-black/5 dark:hover:bg-white/5'}`}>{t('days30')}</button>
            </div>
          </div>
          <div className="h-[280px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={jobSuccessTrend}>
                <defs>
                  <linearGradient id="colorRate" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#0078d4" stopOpacity={0.2}/>
                    <stop offset="95%" stopColor="#0078d4" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={ct.grid} />
                <XAxis
                  dataKey="name"
                  axisLine={false}
                  tickLine={false}
                  tick={{fontSize: 10, fill: ct.axis, fontWeight: 600}}
                  dy={10}
                  interval={trendDays > 7 ? Math.floor(trendDays / 7) - 1 : 0}
                />
                <YAxis
                  axisLine={false}
                  tickLine={false}
                  tick={{fontSize: 10, fill: ct.axis, fontWeight: 600}}
                  domain={useNarrowDomain ? [yDomainLow, yDomainHigh] : [0, 100]}
                />
                <Tooltip
                  contentStyle={{borderRadius: '16px', border: 'none', boxShadow: ct.tooltipShadowLg, padding: '12px', background: ct.tooltipBg, color: ct.tooltipText}}
                  formatter={(value: number, name: string) => [
                    `${value}%`,
                    name === 'rate' ? (language === 'zh' ? '合规率' : 'Compliance') : (language === 'zh' ? '作业成功率' : 'Job Success'),
                  ]}
                />
                {/* Average reference line */}
                <ReferenceLine y={trendAvg} stroke={ct.reference} strokeDasharray="6 4" strokeWidth={1} label={{ value: `${language === 'zh' ? '均值' : 'Avg'} ${trendAvg}%`, position: 'insideTopRight', fill: ct.reference, fontSize: 10 }} />
                {showComplianceLine && <Area type="monotone" dataKey="rate" stroke="#0078d4" strokeWidth={3} fillOpacity={1} fill="url(#colorRate)" name="rate" />}
                {showJobSuccessLine && <Area type="monotone" dataKey="jobRate" stroke="#10b981" strokeWidth={2} strokeDasharray="5 3" fillOpacity={0} dot={false} connectNulls name="jobRate" />}
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="col-span-12 lg:col-span-4 bg-white dark:bg-[#2d2d2d] rounded-xl border border-[#e5e5e5] dark:border-white/5 p-4 md:p-6 shadow-[0_4px_16px_rgba(0,0,0,0.04)]">
          <h3 className="text-sm font-bold text-[#00172D] dark:text-white mb-6 flex items-center gap-2">
            <PieChartIcon size={18} className="text-emerald-500" />
            {t('platformDistribution')}
          </h3>
          <div className="h-[200px] w-full relative" role="img" aria-label={language === 'zh' ? '平台分布图' : 'Platform distribution chart'}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={platformData} innerRadius={63} outerRadius={83} paddingAngle={platformData.length > 4 ? 4 : 8} cornerRadius={4} dataKey="value" stroke="none">
                  {platformData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip contentStyle={{ background: ct.tooltipBg, color: ct.tooltipText, borderColor: ct.tooltipBorder, borderRadius: 12, boxShadow: ct.tooltipShadow }} formatter={(value: number, name: string) => [`${value}%`, name]} />
              </PieChart>
            </ResponsiveContainer>
            {/* P1: Total device count in donut center */}
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
              <span className="text-3xl font-extrabold text-[#00172D] dark:text-white tracking-tight monitoring-data">{devices.length}</span>
              <span className="text-[10px] text-black/40 dark:text-white/40 font-semibold uppercase tracking-wider">{language === 'zh' ? '总设备' : 'Total'}</span>
            </div>
          </div>
          <div className="mt-6 space-y-1.5">
            {platformData.map((item, i) => (
              <div 
                key={i} 
                onClick={() => {
                  const pKey = (item as any).platform;
                  if (pKey) {
                    navigate(`/inventory/devices?platform=${pKey}`);
                  } else {
                    navigate('/inventory/devices');
                  }
                }}
                className="flex items-center justify-between cursor-pointer hover:bg-black/[0.04] dark:hover:bg-white/[0.04] p-1.5 px-2 rounded-xl transition-all group"
                title={language === 'zh' ? `点击查看所有 ${item.name} 设备` : `Click to view all ${item.name} devices`}
              >
                <div className="flex items-center gap-3">
                  <div className="w-2.5 h-2.5 rounded-full group-hover:scale-110 transition-transform duration-300" style={{backgroundColor: item.color}} />
                  <span className="text-xs font-semibold text-black/60 dark:text-white/70 group-hover:text-[#0078d4] transition-colors">{item.name}</span>
                </div>
                <span className="text-xs font-bold text-[#00172D] dark:text-[#0078d4] group-hover:scale-105 transition-transform">{item.value}%</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-3 md:gap-4">
        <div className="col-span-12 lg:col-span-7 bg-white dark:bg-[#2d2d2d] rounded-xl border border-[#e5e5e5] dark:border-white/5 p-4 md:p-6 shadow-[0_4px_16px_rgba(0,0,0,0.04)]">
          <div className="flex items-center justify-between mb-6 flex-wrap gap-2">
            <div>
              <h3 className="text-sm font-bold text-[#00172D] dark:text-white flex items-center gap-2">
                <History size={18} className="text-black/40 dark:text-white/40" />
                {t('recentActivity')}
              </h3>
              <p className="text-xs text-black/40 dark:text-white/40 mt-1">{t('recentActivitySub')}</p>
            </div>
            <button className="text-[10px] font-bold uppercase text-[#0078d4] hover:underline" onClick={() => navigate('/automation/history')}>
              {t('viewFullJobHistory')}
            </button>
          </div>
          <div className="space-y-2">
            {jobs.slice(0, 5).map(job => (
              <div 
                key={job.id} 
                onClick={() => navigate('/automation/history')}
                className="flex items-center justify-between p-4 hover:bg-black/[0.02] dark:hover:bg-white/[0.02] rounded-xl transition-all border border-transparent hover:border-black/5 dark:hover:border-white/5 cursor-pointer group/item"
                title={language === 'zh' ? '点击查看作业历史详情' : 'Click to view full execution history'}
              >
                <div className="flex items-center gap-4">
                  <div className={`p-2.5 rounded-xl transition-colors ${
                    job.status === 'success' ? 'bg-emerald-50 dark:bg-emerald-950/20 text-emerald-600 dark:text-emerald-400' :
                    job.status === 'failed' ? 'bg-red-50 dark:bg-red-950/20 text-red-600 dark:text-red-400' : 'bg-[#0078d4]/10 dark:bg-[#0078d4]/20 text-[#0078d4] dark:text-[#0078d4]'
                  }`}>
                    <Zap size={18} className="group-hover/item:scale-110 transition-transform duration-300" />
                  </div>
                  <div>
                    <p className="text-sm font-bold text-[#00172D] dark:text-white group-hover/item:text-[#0078d4] transition-colors">{job.task_name}</p>
                    <p className="text-[10px] text-black/40 dark:text-white/40 font-medium uppercase tracking-wider">{new Date(job.created_at).toLocaleString()}</p>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  <span className={`text-[10px] font-bold uppercase px-3 py-1 rounded-full ${
                    job.status === 'success' ? 'bg-emerald-100 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300' : 
                    job.status === 'failed' ? 'bg-red-100 dark:bg-red-950/40 text-red-700 dark:text-red-300' : 
                    'bg-blue-100 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300'
                  }`}>
                    {job.status}
                  </span>
                  <ChevronRight size={14} className="text-black/20 dark:text-white/20 group-hover/item:translate-x-1 transition-transform" />
                </div>
              </div>
            ))}
            {jobs.length === 0 && (
              <div className="text-center py-5">
                <div className="inline-flex items-center justify-center w-10 h-10 rounded-xl bg-[#0078d4]/5 mb-2">
                  <Zap size={18} className="text-[#0078d4]/40" />
                </div>
                <p className="text-xs text-black/45 font-medium">{language === 'zh' ? '暂无近期任务记录' : 'No recent task records'}</p>
                <button onClick={() => navigate('/automation/tasks')} className="mt-2.5 inline-flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-semibold rounded-lg bg-[#0078d4]/10 text-[#0078d4] hover:bg-[#0078d4]/20 transition-all">
                  <Play size={10} />
                  {language === 'zh' ? '执行任务' : 'Run a Task'}
                </button>
              </div>
            )}
          </div>
        </div>

        <div className="col-span-12 lg:col-span-5 bg-white dark:bg-[#2d2d2d] rounded-xl border border-[#e5e5e5] dark:border-white/5 p-4 md:p-6 shadow-[0_4px_16px_rgba(0,0,0,0.04)]">
          <h3 className="text-sm font-bold text-[#00172D] dark:text-white mb-6 flex items-center gap-2">
            <Clock size={18} className="text-orange-500" />
            {t('upcomingTasks')}
          </h3>
          <div className="space-y-4">
            {scheduledTasks.filter(st => st.status === 'active').slice(0, 4).map(task => {
              // 友好显示 ISO 时间：今天则只显示 HH:mm，否则显示 MM-DD HH:mm
              const fmt = (iso: string) => {
                if (!iso) return '-';
                const d = new Date(iso);
                if (Number.isNaN(d.getTime())) return iso;
                const now = new Date();
                const sameDay = d.toDateString() === now.toDateString();
                const pad = (n: number) => String(n).padStart(2, '0');
                const hhmm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
                return sameDay ? hhmm : `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${hhmm}`;
              };
              const typeLabel = task.schedule_type === 'recurring'
                ? (language === 'zh' ? '周期' : 'Recurring')
                : (language === 'zh' ? '一次性' : 'Once');
              return (
                <div key={task.id} className="flex items-center justify-between p-4 bg-[#F9F9F9] dark:bg-[#202020] rounded-xl border border-[#e5e5e5] dark:border-white/5 group hover:bg-white dark:hover:bg-[#2d2d2d] hover:shadow-md transition-all">
                  <div className="flex items-center gap-4">
                    <div className="w-10 h-10 bg-white dark:bg-slate-900 rounded-xl shadow-sm flex items-center justify-center text-orange-500 group-hover:bg-orange-500 group-hover:text-white transition-all">
                      <Clock size={18} />
                    </div>
                    <div>
                      <p className="text-sm font-bold text-[#00172D] dark:text-white">{task.task_name}</p>
                      <p className="text-[10px] text-black/40 dark:text-white/40 font-medium tabular-nums">{fmt(task.scheduled_time)}</p>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="text-[10px] font-bold uppercase text-[#0078d4] dark:text-[#0078d4] bg-[#0078d4]/10 dark:bg-[#0078d4]/20 px-2.5 py-1 rounded-lg">{typeLabel}</p>
                  </div>
                </div>
              );
            })}
            {scheduledTasks.filter(st => st.status === 'active').length === 0 && (
              <div className="text-center py-5">
                <div className="inline-flex items-center justify-center w-10 h-10 rounded-xl bg-orange-50 mb-2">
                  <Clock size={18} className="text-orange-400/70" />
                </div>
                <p className="text-xs text-black/45 font-medium">{language === 'zh' ? '暂无计划中的任务' : 'No scheduled tasks yet'}</p>
                <button onClick={() => navigate('/automation/scheduled-jobs')} className="mt-2.5 inline-flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-semibold rounded-lg bg-orange-50 text-orange-600 hover:bg-orange-100 transition-all">
                  <CalendarPlus size={10} />
                  {language === 'zh' ? '创建定时作业' : 'Create Scheduled Job'}
                </button>
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
