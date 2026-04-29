import React from 'react';
import { Server, Activity, ShieldCheck, AlertCircle, AlertTriangle, Bell, TrendingUp, PieChart as PieChartIcon, History, Clock, ChevronRight, X, Zap, MonitorSmartphone, Cpu, HardDrive, MemoryStick, Play, CalendarPlus } from 'lucide-react';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, PieChart, Pie, Cell } from 'recharts';
import type { Device, Job, ScheduledTask, HostResourceSnapshot, NotificationItem } from '../types';
import { sectionHeaderRowClass, primaryActionBtnClass, secondaryActionBtnClass } from '../components/shared';
import { useChartTheme } from '../hooks/useChartTheme';

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
  dashLastRefresh, hostResources, unreadNotificationCount, notifications, language, t, setActiveTab, navigate,
  assetsTotal,
}) => {
  const ct = useChartTheme();
  const onlineCount = devices.filter(d => d.status === 'online').length;
  const onlinePct = devices.length > 0 ? Math.round((onlineCount / devices.length) * 100) : 0;
  const compPct = devices.length > 0 ? Math.round((devices.filter(d => d.compliance === 'compliant').length / devices.length) * 100) : 0;
  const now24h = Date.now() - 86400000;
  const failedCount24h = jobs.filter(j => j.status === 'failed' && j.created_at && new Date(j.created_at).getTime() > now24h).length;

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
    const days7 = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const d = new Date();
    d.setDate(d.getDate() - (complianceTrend.length - 1 - i));
    const dateStr = d.toISOString().slice(0, 10);
    const dayJobs = jobs.filter(j => j.created_at && j.created_at.startsWith(dateStr));
    const successRate = dayJobs.length > 0 ? Math.round((dayJobs.filter(j => j.status === 'success').length / dayJobs.length) * 100) : null;
    return { ...point, jobRate: successRate };
  });

  const healthLevel = hostResources?.status === 'critical' || unreadNotificationCount >= 5 || onlinePct < 30 || (devices.length > 0 && compPct === 0)
    ? 'critical'
    : hostResources?.status === 'degraded' || unreadNotificationCount > 0 || onlinePct < 60 || compPct < 50
      ? 'degraded'
      : 'healthy';
  const healthLabel = healthLevel === 'critical' ? t('systemCritical') : healthLevel === 'degraded' ? t('systemDegraded') : t('systemHealthy');
  const healthColor = healthLevel === 'critical' ? 'bg-red-100 text-red-700' : healthLevel === 'degraded' ? 'bg-orange-100 text-orange-700' : 'bg-emerald-100 text-emerald-700';
  const hostStatusText = hostResources?.status === 'critical'
    ? (language === 'zh' ? '宿主机严重' : 'Host Critical')
    : hostResources?.status === 'degraded'
      ? (language === 'zh' ? '宿主机告警' : 'Host Warning')
      : (language === 'zh' ? '宿主机正常' : 'Host Healthy');

  const dashAgoSec = Math.round((Date.now() - dashLastRefresh.getTime()) / 1000);

  return (
    <div className="space-y-5 overflow-auto h-full">
      <div className={sectionHeaderRowClass}>
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-[#00172D]">{t('networkOverview')}</h2>
          <p className="text-sm text-black/40">{t('dashboardSubtitle')}</p>
        </div>
        <div className="flex gap-2 items-center">
          <span className="text-[10px] text-black/30">{t('lastRefreshed')} {dashAgoSec}{t('secondsAgo')}</span>
          {hostResources && <span className="px-3 py-1 text-[10px] font-bold rounded-full uppercase tracking-wider bg-[#00172D]/5 text-[#00172D]">{hostStatusText}</span>}
          <span className={`px-3 py-1 text-[10px] font-bold rounded-full uppercase tracking-wider ${healthColor} ${healthLevel === 'critical' ? 'animate-pulse' : ''}`}>{healthLabel}</span>
        </div>
      </div>

      {!dashBannerCollapsed && (
        <div className="rounded-2xl border border-[#00bceb]/20 bg-gradient-to-r from-[#f4fcff] via-white to-[#eef9ff] px-5 py-3.5 shadow-sm relative">
          <button onClick={() => setDashBannerCollapsed(true)} className="absolute top-2.5 right-3 p-1 rounded-lg hover:bg-black/5 text-black/30 hover:text-black/60 transition-all" aria-label="Close banner"><X size={14} /></button>
          <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3">
            <div className="min-w-0">
              <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#00a5cd]">{language === 'zh' ? 'Nexora 运营中心' : 'Nexora Command Center'}</p>
              <h3 className="mt-0.5 text-lg font-bold text-[#0d2c40]">{t('todaySnapshot')}</h3>
              <p className="mt-0.5 text-xs text-[#21546d]/80">{t('todaySnapshotDesc')}</p>
              {hostResources && <p className="mt-1 text-[11px] text-[#21546d]/85">{language === 'zh' ? `平台宿主机: CPU ${Math.round(hostResources.cpu_percent || 0)}% / 内存 ${Math.round(hostResources.memory_percent || 0)}% / 磁盘 ${Math.round(hostResources.disk_percent || 0)}%` : `Platform host: CPU ${Math.round(hostResources.cpu_percent || 0)}% / Memory ${Math.round(hostResources.memory_percent || 0)}% / Disk ${Math.round(hostResources.disk_percent || 0)}%`}</p>}
            </div>
            <div className="flex flex-wrap gap-2 shrink-0">
              <button onClick={() => navigate('/monitoring')} className={secondaryActionBtnClass + ' !py-1.5 !text-xs'}>
                {language === 'zh' ? '查看平台资源' : 'View Host Resources'}
              </button>
              <button onClick={() => navigate('/automation/execute')} className={primaryActionBtnClass + ' !py-1.5 !text-xs'}>
                {t('openAutomation')}
              </button>
              <button onClick={() => navigate('/automation/queries')} className={secondaryActionBtnClass + ' !py-1.5 !text-xs'}>
                {t('viewExecHistory')}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-3 md:gap-4">
        {/* Total Assets */}
        <div onClick={() => setActiveTab('inventory')} className="bg-white px-5 py-4 rounded-2xl shadow-sm border border-black/5 flex items-center justify-between group hover:shadow-md hover:border-[#005073]/20 transition-all cursor-pointer" role="button" tabIndex={0} aria-label={t('totalAssets')}>
          <div>
            <p className="text-xs font-bold uppercase tracking-widest text-black/30 mb-1">{t('totalAssets')}</p>
            <p className="text-3xl font-bold monitoring-data text-[#005073]">{assetsTotal}</p>
          </div>
          <div className="p-3 rounded-xl bg-[#005073]/5 text-[#005073] group-hover:scale-110 transition-transform">
            <Server size={24} />
          </div>
        </div>

        {/* Online Nodes — with inline micro progress bar */}
        <div onClick={() => setActiveTab('inventory')} className={`bg-white px-5 py-4 rounded-2xl shadow-sm border border-black/5 group hover:shadow-md hover:border-emerald-200 transition-all cursor-pointer ${onlinePct < 30 ? 'border-l-[3px] border-l-red-500' : onlinePct < 60 ? 'border-l-[3px] border-l-orange-400' : ''}`}>
          <div className="flex items-center justify-between">
            <div className="min-w-0">
              <p className="text-xs font-bold uppercase tracking-widest text-black/30 mb-1">{t('onlineNodes')}</p>
              <div className="flex items-baseline gap-1.5">
                <span className={`text-3xl font-bold monitoring-data ${onlinePct < 30 ? 'text-red-600' : onlinePct < 60 ? 'text-orange-600' : 'text-emerald-600'}`}>{onlineCount}</span>
                <span className="text-sm text-black/30 font-medium">/ {devices.length}</span>
              </div>
            </div>
            <div className={`p-3 rounded-xl ${onlinePct < 30 ? 'bg-red-50 text-red-600' : onlinePct < 60 ? 'bg-orange-50 text-orange-600' : 'bg-emerald-50 text-emerald-600'} group-hover:scale-110 transition-transform`}>
              <Activity size={24} />
            </div>
          </div>
          {/* Micro progress bar */}
          <div className="mt-2 w-full h-1.5 bg-black/5 rounded-full overflow-hidden">
            <div className={`h-full rounded-full transition-all duration-700 ${onlinePct < 30 ? 'bg-red-500' : onlinePct < 60 ? 'bg-orange-400' : 'bg-emerald-500'}`} style={{ width: `${onlinePct}%` }} />
          </div>
          <p className="text-[10px] text-black/30 font-medium mt-1">{onlinePct}% {language === 'zh' ? '在线' : 'online'}</p>
        </div>

        {/* Compliance */}
        <div onClick={() => setActiveTab('compliance')} className={`bg-white px-5 py-4 rounded-2xl shadow-sm border border-black/5 flex items-center justify-between group hover:shadow-md hover:border-[#00bceb]/20 transition-all cursor-pointer ${compPct === 0 ? 'border-l-[3px] border-l-red-500' : compPct < 50 ? 'border-l-[3px] border-l-orange-400' : ''}`}>
          <div>
            <p className="text-xs font-bold uppercase tracking-widest text-black/30 mb-1">{t('complianceRate')}</p>
            <p className={`text-3xl font-bold monitoring-data ${compPct === 0 ? 'text-red-600' : compPct < 50 ? 'text-orange-600' : 'text-[#00bceb]'}`}>{compPct}%</p>
          </div>
          <div className={`p-3 rounded-xl ${compPct === 0 ? 'bg-red-50 text-red-600' : compPct < 50 ? 'bg-orange-50 text-orange-600' : 'bg-[#00bceb]/5 text-[#00bceb]'} group-hover:scale-110 transition-transform`}>
            <ShieldCheck size={24} />
          </div>
        </div>

        {/* Failed Tasks (24h) */}
        <div onClick={() => setActiveTab('history')} className={`bg-white px-5 py-4 rounded-2xl shadow-sm border border-black/5 flex items-center justify-between group hover:shadow-md hover:border-red-200 transition-all cursor-pointer ${failedCount24h > 0 ? 'border-l-[3px] border-l-red-500' : ''}`}>
          <div>
            <p className="text-xs font-bold uppercase tracking-widest text-black/30 mb-1">{t('failedTasks')}</p>
            <div className="flex items-baseline gap-1.5">
              <span className={`text-3xl font-bold monitoring-data ${failedCount24h > 0 ? 'text-red-600' : 'text-black/40'}`}>{failedCount24h}</span>
              <span className="text-[10px] text-black/25 font-medium">24h</span>
            </div>
          </div>
          <div className={`p-3 rounded-xl ${failedCount24h > 0 ? 'bg-red-50 text-red-600' : 'bg-black/5 text-black/40'} group-hover:scale-110 transition-transform`}>
            <AlertCircle size={24} />
          </div>
        </div>

        {/* Platform Host — expanded with CPU/MEM/DISK bars */}
        <div onClick={() => navigate('/monitoring')} className={`col-span-2 md:col-span-1 bg-white px-5 py-4 rounded-2xl shadow-sm border border-black/5 group hover:shadow-md hover:border-[#005073]/20 transition-all cursor-pointer ${hostResources?.status === 'critical' ? 'border-l-[3px] border-l-red-500' : hostResources?.status === 'degraded' ? 'border-l-[3px] border-l-orange-400' : ''}`}>
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs font-bold uppercase tracking-widest text-black/30">{language === 'zh' ? '平台宿主机' : 'Platform Host'}</p>
            <div className={`p-2 rounded-lg ${hostResources?.status === 'critical' ? 'bg-red-50 text-red-600' : hostResources?.status === 'degraded' ? 'bg-orange-50 text-orange-600' : 'bg-[#005073]/5 text-[#005073]'} group-hover:scale-110 transition-transform`}>
              <MonitorSmartphone size={18} />
            </div>
          </div>
          {hostResources ? (
            <div className="space-y-1.5">
              {[
                { label: 'CPU', value: hostResources.cpu_percent || 0, icon: Cpu },
                { label: 'MEM', value: hostResources.memory_percent || 0, icon: MemoryStick },
                { label: 'DISK', value: hostResources.disk_percent || 0, icon: HardDrive },
              ].map(res => (
                <div key={res.label} className="flex items-center gap-1.5">
                  <span className="text-[9px] font-bold text-black/30 w-7 shrink-0">{res.label}</span>
                  <div className="flex-1 h-1.5 bg-black/5 rounded-full overflow-hidden">
                    <div className={`h-full rounded-full transition-all duration-700 ${res.value > 90 ? 'bg-red-500' : res.value > 70 ? 'bg-orange-400' : 'bg-[#00bceb]'}`} style={{ width: `${Math.round(res.value)}%` }} />
                  </div>
                  <span className={`text-[10px] font-bold w-8 text-right ${res.value > 90 ? 'text-red-600' : res.value > 70 ? 'text-orange-600' : 'text-black/50'}`}>{Math.round(res.value)}%</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-2xl font-bold text-black/20 monitoring-data">--</p>
          )}
        </div>
      </div>

      {/* Alert Summary Strip */}
      {unreadNotificationCount > 0 && (
        <div onClick={() => navigate('/alerts')} className="bg-white rounded-2xl border border-black/5 shadow-sm px-6 py-4 flex items-center justify-between cursor-pointer hover:shadow-md hover:border-black/10 transition-all group">
          <div className="flex items-center gap-4">
            <div className="p-2.5 rounded-xl bg-red-50 text-red-600 group-hover:scale-110 transition-transform">
              <Bell size={20} />
            </div>
            <div>
              <p className="text-sm font-bold text-[#00172D]">{t('activeAlertsShort')}</p>
              <p className="text-[10px] text-black/40 mt-0.5">{language === 'zh' ? '点击查看告警中心' : 'Click to view Alert Center'}</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {criticalAlerts > 0 && (
              <span className="flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold bg-red-100 text-red-700">
                <AlertCircle size={12} /> {criticalAlerts} {language === 'zh' ? '严重' : 'Critical'}
              </span>
            )}
            {majorAlerts > 0 && (
              <span className="flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold bg-orange-100 text-orange-700">
                <AlertTriangle size={12} /> {majorAlerts} {language === 'zh' ? '重要' : 'Major'}
              </span>
            )}
            {warningAlerts > 0 && (
              <span className="flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold bg-amber-100 text-amber-700">
                {warningAlerts} {language === 'zh' ? '警告' : 'Warning'}
              </span>
            )}
            {infoAlerts > 0 && (
              <span className="px-2.5 py-1 rounded-full text-[10px] font-bold bg-blue-100 text-blue-700">
                {infoAlerts} {language === 'zh' ? '信息' : 'Info'}
              </span>
            )}
            <ChevronRight size={16} className="text-black/20 group-hover:text-black/40 transition-colors" />
          </div>
        </div>
      )}

      <div className="grid grid-cols-12 gap-3 md:gap-4">
        <div className="col-span-12 lg:col-span-8 bg-white rounded-2xl border border-black/5 p-4 md:p-6 shadow-sm">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h3 className="text-sm font-bold text-[#00172D] flex items-center gap-2">
                <TrendingUp size={18} className="text-[#00bceb]" />
                {t('complianceTrend')}
              </h3>
              <p className="text-xs text-black/40 mt-0.5">{t('complianceTrendSub')}</p>
            </div>
            <div className="flex gap-2">
              <div className="flex items-center gap-1.5 mr-3">
                <span className="w-4 h-0.5 bg-[#00bceb] rounded-full block" />
                <span className="text-[9px] text-black/40">{ language === 'zh' ? '合规率' : 'Compliance' }</span>
              </div>
              <div className="flex items-center gap-1.5 mr-4">
                <span className="w-4 h-0.5 bg-emerald-500 rounded-full block" style={{ backgroundImage: 'repeating-linear-gradient(90deg, #10b981, #10b981 3px, transparent 3px, transparent 6px)' }} />
                <span className="text-[9px] text-black/40">{ language === 'zh' ? '作业成功率' : 'Job Success' }</span>
              </div>
              <button onClick={() => setTrendDays(7)} className={`px-3 py-1 rounded-lg text-[10px] font-bold uppercase transition-all ${trendDays === 7 ? 'bg-black/10 text-black/70' : 'text-black/40 hover:bg-black/5'}`}>{t('days7')}</button>
              <button onClick={() => setTrendDays(30)} className={`px-3 py-1 rounded-lg text-[10px] font-bold uppercase transition-all ${trendDays === 30 ? 'bg-black/10 text-black/70' : 'text-black/40 hover:bg-black/5'}`}>{t('days30')}</button>
            </div>
          </div>
          <div className="h-[280px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={jobSuccessTrend}>
                <defs>
                  <linearGradient id="colorRate" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#00bceb" stopOpacity={0.2}/>
                    <stop offset="95%" stopColor="#00bceb" stopOpacity={0}/>
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
                <Area type="monotone" dataKey="rate" stroke="#00bceb" strokeWidth={3} fillOpacity={1} fill="url(#colorRate)" name="rate" />
                <Area type="monotone" dataKey="jobRate" stroke="#10b981" strokeWidth={2} strokeDasharray="5 3" fillOpacity={0} dot={false} connectNulls name="jobRate" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="col-span-12 lg:col-span-4 bg-white rounded-2xl border border-black/5 p-4 md:p-6 shadow-sm">
          <h3 className="text-sm font-bold text-[#00172D] mb-6 flex items-center gap-2">
            <PieChartIcon size={18} className="text-emerald-500" />
            {t('platformDistribution')}
          </h3>
          <div className="h-[200px] w-full relative" role="img" aria-label={language === 'zh' ? '平台分布图' : 'Platform distribution chart'}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={platformData} innerRadius={65} outerRadius={85} paddingAngle={platformData.length > 4 ? 4 : 8} dataKey="value" stroke="none">
                  {platformData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip contentStyle={{ background: ct.tooltipBg, color: ct.tooltipText, borderColor: ct.tooltipBorder, borderRadius: 12, boxShadow: ct.tooltipShadow }} formatter={(value: number, name: string) => [`${value}%`, name]} />
              </PieChart>
            </ResponsiveContainer>
            {/* P1: Total device count in donut center */}
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
              <span className="text-2xl font-bold text-[#00172D] monitoring-data">{devices.length}</span>
              <span className="text-[10px] text-black/40 font-medium">{language === 'zh' ? '总设备' : 'Total'}</span>
            </div>
          </div>
          <div className="mt-6 space-y-3">
            {platformData.map((item, i) => (
              <div key={i} className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-3 h-3 rounded-full" style={{backgroundColor: item.color}} />
                  <span className="text-xs font-semibold text-black/60">{item.name}</span>
                </div>
                <span className="text-xs font-bold text-[#00172D]">{item.value}%</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-3 md:gap-4">
        <div className="col-span-12 lg:col-span-7 bg-white rounded-2xl border border-black/5 p-4 md:p-6 shadow-sm">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h3 className="text-sm font-bold text-[#00172D] flex items-center gap-2">
                <History size={18} className="text-black/40" />
                {t('recentActivity')}
              </h3>
              <p className="text-xs text-black/40 mt-1">{t('recentActivitySub')}</p>
            </div>
            <button className="text-[10px] font-bold uppercase text-[#00bceb] hover:underline" onClick={() => setActiveTab('history')}>
              {t('viewAuditLog')}
            </button>
          </div>
          <div className="space-y-2">
            {jobs.slice(0, 5).map(job => (
              <div key={job.id} className="flex items-center justify-between p-4 hover:bg-black/[0.02] rounded-xl transition-all border border-transparent hover:border-black/5">
                <div className="flex items-center gap-4">
                  <div className={`p-2.5 rounded-xl ${
                    job.status === 'success' ? 'bg-emerald-50 text-emerald-600' :
                    job.status === 'failed' ? 'bg-red-50 text-red-600' : 'bg-[#00bceb]/10 text-[#00bceb]'
                  }`}>
                    <Zap size={18} />
                  </div>
                  <div>
                    <p className="text-sm font-bold text-[#00172D]">{job.task_name}</p>
                    <p className="text-[10px] text-black/40 font-medium uppercase tracking-wider">{new Date(job.created_at).toLocaleString()}</p>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  <span className={`text-[10px] font-bold uppercase px-3 py-1 rounded-full ${
                    job.status === 'success' ? 'bg-emerald-100 text-emerald-700' : job.status === 'failed' ? 'bg-red-100 text-red-700' : 'bg-blue-100 text-blue-700'
                  }`}>
                    {job.status}
                  </span>
                  <ChevronRight size={14} className="text-black/20" />
                </div>
              </div>
            ))}
            {jobs.length === 0 && (
              <div className="text-center py-10">
                <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-[#00bceb]/5 mb-3">
                  <Zap size={24} className="text-[#00bceb]/30" />
                </div>
                <p className="text-sm text-black/35 font-medium">{language === 'zh' ? '一切正常，暂无新任务' : 'All clear — no recent tasks'}</p>
                <button onClick={() => navigate('/automation/execute')} className="mt-3 inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-lg bg-[#00bceb]/10 text-[#008db1] hover:bg-[#00bceb]/20 transition-all">
                  <Play size={12} />
                  {language === 'zh' ? '执行任务' : 'Run a Task'}
                </button>
              </div>
            )}
          </div>
        </div>

        <div className="col-span-12 lg:col-span-5 bg-white rounded-2xl border border-black/5 p-4 md:p-6 shadow-sm">
          <h3 className="text-sm font-bold text-[#00172D] mb-6 flex items-center gap-2">
            <Clock size={18} className="text-orange-500" />
            {t('upcomingTasks')}
          </h3>
          <div className="space-y-4">
            {scheduledTasks.filter(st => st.status === 'active').slice(0, 4).map(task => (
              <div key={task.id} className="flex items-center justify-between p-4 bg-[#F0F2F5] rounded-2xl border border-black/5 group hover:bg-white hover:shadow-md transition-all">
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 bg-white rounded-xl shadow-sm flex items-center justify-center text-orange-500 group-hover:bg-orange-500 group-hover:text-white transition-all">
                    <Clock size={18} />
                  </div>
                  <div>
                    <p className="text-sm font-bold text-[#00172D]">{task.task_name}</p>
                    <p className="text-[10px] text-black/40 font-medium">{task.scheduled_time} ({task.timezone})</p>
                  </div>
                </div>
                <div className="text-right">
                  <p className="text-[10px] font-bold uppercase text-[#005073] bg-[#005073]/10 px-2 py-1 rounded-lg">{task.schedule_type}</p>
                </div>
              </div>
            ))}
            {scheduledTasks.filter(st => st.status === 'active').length === 0 && (
              <div className="text-center py-10">
                <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-orange-50 mb-3">
                  <Clock size={24} className="text-orange-300" />
                </div>
                <p className="text-sm text-black/35 font-medium">{language === 'zh' ? '暂无计划中的任务' : 'No scheduled tasks yet'}</p>
                <button onClick={() => navigate('/config/schedule')} className="mt-3 inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-lg bg-orange-50 text-orange-600 hover:bg-orange-100 transition-all">
                  <CalendarPlus size={12} />
                  {language === 'zh' ? '创建定时任务' : 'Create Schedule'}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default DashboardTab;
