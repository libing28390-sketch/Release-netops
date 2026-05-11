import React from 'react';
import { Activity, AlertTriangle, Filter, ShieldCheck, Server, Stethoscope } from 'lucide-react';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { Device, DeviceHealthHistoryResponse, DeviceHealthOverview } from '../types';
import { severityBadgeClass } from '../components/shared';
import { useChartTheme } from '../hooks/useChartTheme';
import PageHero from '../components/PageHero';

interface DeviceHealthTabProps {
  devices: Device[];
  overview: DeviceHealthOverview | null;
  language: string;
  onShowDetails: (device: Device) => void;
  onOpenMonitoring: () => void;
}

const statusToneMap: Record<string, string> = {
  healthy: 'bg-emerald-100 text-emerald-700',
  warning: 'bg-amber-100 text-amber-700',
  critical: 'bg-red-100 text-red-700',
  unknown: 'bg-slate-100 text-slate-600',
};

const DeviceHealthTab: React.FC<DeviceHealthTabProps> = ({
  devices,
  overview,
  language,
  onShowDetails,
  onOpenMonitoring,
}) => {
  const ct = useChartTheme();
  const isZh = language === 'zh';
  const [rangeHours, setRangeHours] = React.useState(24);
  const [history, setHistory] = React.useState<DeviceHealthHistoryResponse | null>(null);
  const [historyLoading, setHistoryLoading] = React.useState(false);
  const [siteFilter, setSiteFilter] = React.useState('all');
  const [roleFilter, setRoleFilter] = React.useState('all');
  const [statusFilter, setStatusFilter] = React.useState('all');
  const [alertFilter, setAlertFilter] = React.useState('all');
  const [searchTerm, setSearchTerm] = React.useState('');

  React.useEffect(() => {
    let cancelled = false;
    const loadHistory = async () => {
      setHistoryLoading(true);
      try {
        const resp = await fetch(`/api/device-health/history?range_hours=${rangeHours}`);
        if (!resp.ok) return;
        const data = await resp.json() as DeviceHealthHistoryResponse;
        if (!cancelled) setHistory(data);
      } finally {
        if (!cancelled) setHistoryLoading(false);
      }
    };

    loadHistory();
    const timer = window.setInterval(loadHistory, 60000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [rangeHours]);

  const summary = overview || {
    total_devices: devices.length,
    average_score: devices.length > 0 ? Number((devices.reduce((sum, item) => sum + Number(item.health_score || 0), 0) / devices.length).toFixed(1)) : 0,
    healthy: devices.filter((item) => item.health_status === 'healthy').length,
    warning: devices.filter((item) => item.health_status === 'warning').length,
    critical: devices.filter((item) => item.health_status === 'critical').length,
    unknown: devices.filter((item) => !item.health_status || item.health_status === 'unknown').length,
    top_risky_devices: [],
  };

  const riskyDevices = (overview?.top_risky_devices?.length ? overview.top_risky_devices : [...devices]
    .sort((a, b) => {
      const rank = (value?: string) => value === 'critical' ? 0 : value === 'warning' ? 1 : value === 'unknown' ? 2 : 3;
      return rank(a.health_status) - rank(b.health_status) || Number(a.health_score || 0) - Number(b.health_score || 0) || Number(b.open_alert_count || 0) - Number(a.open_alert_count || 0);
    })
    .slice(0, 8));

  const siteOptions = React.useMemo<string[]>(
    () => Array.from(new Set<string>(devices.map((item) => String(item.site || '').trim()).filter((value): value is string => Boolean(value)))).sort((a, b) => a.localeCompare(b)),
    [devices],
  );
  const roleOptions = React.useMemo<string[]>(
    () => Array.from(new Set<string>(devices.map((item) => String(item.role || '').trim()).filter((value): value is string => Boolean(value)))).sort((a, b) => a.localeCompare(b)),
    [devices],
  );
  const filteredDevices = React.useMemo(() => {
    const keyword = searchTerm.trim().toLowerCase();
    return devices.filter((device) => {
      if (siteFilter !== 'all' && (device.site || '') !== siteFilter) return false;
      if (roleFilter !== 'all' && (device.role || '') !== roleFilter) return false;
      if (statusFilter !== 'all' && (device.health_status || 'unknown') !== statusFilter) return false;
      if (alertFilter === 'open' && Number(device.open_alert_count || 0) <= 0) return false;
      if (alertFilter === 'critical' && Number(device.critical_open_alerts || 0) <= 0) return false;
      if (alertFilter === 'interface' && (Number(device.interface_down_count || 0) + Number(device.interface_flap_count || 0) + Number(device.interface_error_count || 0)) <= 0) return false;
      if (!keyword) return true;
      const haystack = [device.hostname, device.ip_address, device.platform, device.site, device.role, device.health_summary]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return haystack.includes(keyword);
    });
  }, [alertFilter, devices, roleFilter, searchTerm, siteFilter, statusFilter]);
  const filteredSummary = React.useMemo(() => ({
    total: filteredDevices.length,
    healthy: filteredDevices.filter((item) => item.health_status === 'healthy').length,
    warning: filteredDevices.filter((item) => item.health_status === 'warning').length,
    critical: filteredDevices.filter((item) => item.health_status === 'critical').length,
    unknown: filteredDevices.filter((item) => item.health_status === 'unknown' || !item.health_status).length,
  }), [filteredDevices]);
  const filteredRiskyDevices = React.useMemo(
    () => [...filteredDevices].sort((a, b) => {
      const rank = (value?: string) => value === 'critical' ? 0 : value === 'warning' ? 1 : value === 'unknown' ? 2 : 3;
      return rank(a.health_status) - rank(b.health_status) || Number(a.health_score || 0) - Number(b.health_score || 0) || Number(b.open_alert_count || 0) - Number(a.open_alert_count || 0);
    }).slice(0, 8),
    [filteredDevices],
  );
  const fleetRows = React.useMemo(
    () => [...filteredDevices].sort((a, b) => Number(a.health_score || 0) - Number(b.health_score || 0) || String(a.hostname || '').localeCompare(String(b.hostname || ''))),
    [filteredDevices],
  );
  const historySeries = history?.series || [];
  const hasActiveFilters = siteFilter !== 'all' || roleFilter !== 'all' || statusFilter !== 'all' || alertFilter !== 'all' || searchTerm.trim().length > 0;
  const displayedRiskyDevices = hasActiveFilters ? filteredRiskyDevices : riskyDevices;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHero
        icon={Stethoscope}
        title={isZh ? '健康检测中心' : 'Health Detection Center'}
        subtitle={isZh ? '把可达性、资源、硬件、接口异常和开放告警整合到统一健康模型，便于快速排障。' : 'Unify reachability, resource, hardware, interface anomalies, and open alerts into one health model for fast triage.'}
        actions={
          <button
            type="button"
            onClick={onOpenMonitoring}
            className="px-4 py-2 rounded-xl border border-black/10 text-sm font-medium hover:bg-black/5 transition-all"
            title={isZh ? '打开监控中心' : 'Open Monitoring Center'}
          >
            {isZh ? '打开监控中心' : 'Open Monitoring'}
          </button>
        }
      />

      <div className="flex-1 overflow-auto px-6 py-5 space-y-4">

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-3">
        {[
          { label: isZh ? '设备总数' : 'Total Devices', value: summary.total_devices, icon: Server, tone: 'text-slate-700 bg-slate-100', filter: 'all' as const },
          { label: isZh ? '平均健康分' : 'Average Score', value: summary.average_score, icon: Activity, tone: 'text-cyan-700 bg-cyan-100', filter: null },
          { label: isZh ? '健康' : 'Healthy', value: summary.healthy, icon: ShieldCheck, tone: 'text-emerald-700 bg-emerald-100', filter: 'healthy' as const },
          { label: isZh ? '告警' : 'Warning', value: summary.warning, icon: AlertTriangle, tone: 'text-amber-700 bg-amber-100', filter: 'warning' as const },
          { label: isZh ? '严重' : 'Critical', value: summary.critical, icon: AlertTriangle, tone: 'text-red-700 bg-red-100', filter: 'critical' as const },
        ].map((card) => (
          <button
            key={card.label}
            type="button"
            onClick={() => {
              if (card.filter === null) return;
              setStatusFilter(card.filter === statusFilter ? 'all' : card.filter);
            }}
            className={`bg-white rounded-2xl border shadow-sm p-4 text-left transition-all ${card.filter !== null ? 'cursor-pointer hover:border-black/15 hover:shadow-md active:scale-[0.98]' : ''} ${statusFilter !== 'all' && card.filter === statusFilter ? 'border-black/20 ring-2 ring-black/5' : 'border-black/5'}`}
          >
            <div className="flex items-center justify-between gap-3">
              <p className="text-[10px] font-bold uppercase tracking-widest text-black/35">{card.label}</p>
              <span className={`inline-flex rounded-full p-2 ${card.tone}`}><card.icon size={14} /></span>
            </div>
            <p className="mt-2 text-3xl font-semibold text-[#00172D]">{card.value}</p>
          </button>
        ))}
      </div>

      <div className="rounded-2xl border border-black/5 bg-white shadow-sm px-4 py-3 space-y-2.5">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Filter size={14} className="text-black/30" />
            <span className="text-sm font-semibold text-[#0b2340]">{isZh ? '按站点、角色和风险聚焦设备' : 'Filter by site, role & risk'}</span>
          </div>
          <div className="flex flex-wrap items-center gap-1.5 text-[10px]">
            <span className="rounded-full bg-slate-100 px-2 py-0.5 font-semibold text-slate-700">{isZh ? '命中' : 'Hit'} {filteredSummary.total}</span>
            <span className="rounded-full bg-red-100 px-2 py-0.5 font-semibold text-red-700">{isZh ? '严重' : 'Crit'} {filteredSummary.critical}</span>
            <span className="rounded-full bg-amber-100 px-2 py-0.5 font-semibold text-amber-700">{isZh ? '告警' : 'Warn'} {filteredSummary.warning}</span>
            <span className="rounded-full bg-emerald-100 px-2 py-0.5 font-semibold text-emerald-700">{isZh ? '健康' : 'OK'} {filteredSummary.healthy}</span>
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-[1.2fr_repeat(4,minmax(0,0.9fr))] gap-2">
          <label className="space-y-1">
            <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-black/35">{isZh ? '搜索' : 'Search'}</span>
            <input
              value={searchTerm}
              onChange={(event) => setSearchTerm(event.target.value)}
              placeholder={isZh ? '设备名 / IP / 平台 / 摘要' : 'Hostname / IP / platform / summary'}
              className="w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm outline-none transition-all focus:border-black/25 focus:ring-2 focus:ring-black/5"
            />
          </label>
          <label className="space-y-1">
            <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-black/35">{isZh ? '站点' : 'Site'}</span>
            <select value={siteFilter} onChange={(event) => setSiteFilter(event.target.value)} className="w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm outline-none transition-all focus:border-black/25 focus:ring-2 focus:ring-black/5">
              <option value="all">{isZh ? '全部站点' : 'All sites'}</option>
              {siteOptions.map((site) => <option key={site} value={site}>{site}</option>)}
            </select>
          </label>
          <label className="space-y-1">
            <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-black/35">{isZh ? '角色' : 'Role'}</span>
            <select value={roleFilter} onChange={(event) => setRoleFilter(event.target.value)} className="w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm outline-none transition-all focus:border-black/25 focus:ring-2 focus:ring-black/5">
              <option value="all">{isZh ? '全部角色' : 'All roles'}</option>
              {roleOptions.map((role) => <option key={role} value={role}>{role}</option>)}
            </select>
          </label>
          <label className="space-y-1">
            <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-black/35">{isZh ? '健康状态' : 'Status'}</span>
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm outline-none transition-all focus:border-black/25 focus:ring-2 focus:ring-black/5">
              <option value="all">{isZh ? '全部状态' : 'All states'}</option>
              <option value="critical">{isZh ? '严重' : 'Critical'}</option>
              <option value="warning">{isZh ? '告警' : 'Warning'}</option>
              <option value="healthy">{isZh ? '健康' : 'Healthy'}</option>
              <option value="unknown">{isZh ? '未知' : 'Unknown'}</option>
            </select>
          </label>
          <label className="space-y-1">
            <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-black/35">{isZh ? '风险维度' : 'Risk'}</span>
            <select value={alertFilter} onChange={(event) => setAlertFilter(event.target.value)} className="w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm outline-none transition-all focus:border-black/25 focus:ring-2 focus:ring-black/5">
              <option value="all">{isZh ? '全部风险' : 'All risk types'}</option>
              <option value="open">{isZh ? '有开放告警' : 'Open alerts'}</option>
              <option value="critical">{isZh ? '有严重告警' : 'Critical alerts'}</option>
              <option value="interface">{isZh ? '接口风险' : 'Interface risk'}</option>
            </select>
          </label>
        </div>
        {hasActiveFilters && (
          <div className="flex items-center justify-between gap-3 rounded-lg border border-dashed border-black/10 bg-black/[0.015] px-3 py-2 text-xs text-black/50">
            <span>{isZh ? '已按筛选条件收敛' : 'Filtered'}</span>
            <button
              type="button"
              onClick={() => {
                setSearchTerm('');
                setSiteFilter('all');
                setRoleFilter('all');
                setStatusFilter('all');
                setAlertFilter('all');
              }}
              className="rounded-md border border-black/10 px-2.5 py-1 text-[11px] font-semibold text-black/60 transition-all hover:bg-black/[0.03]"
            >
              {isZh ? '清空' : 'Clear'}
            </button>
          </div>
        )}
      </div>

      <div className="rounded-2xl border border-black/5 bg-white shadow-sm p-4 space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#0089ac]">{isZh ? '健康趋势' : 'Trend'}</p>
            <h3 className="text-base font-semibold text-[#0b2340]">{isZh ? '全网健康分演进' : 'Fleet Health Evolution'}</h3>
          </div>
          <div className="flex items-center gap-2">
            {[1, 24, 168].map((hours) => (
              <button
                key={hours}
                type="button"
                onClick={() => setRangeHours(hours)}
                className={`px-2.5 py-1 rounded-md text-[10px] font-bold uppercase tracking-[0.14em] transition-all ${rangeHours === hours ? 'bg-black text-white' : 'border border-black/10 text-black/60 hover:bg-black/[0.03]'}`}
              >
                {hours === 1 ? (isZh ? '1 小时' : '1h') : hours === 24 ? (isZh ? '24 小时' : '24h') : (isZh ? '7 天' : '7d')}
              </button>
            ))}
            <span className="text-[11px] text-black/40">{historyLoading ? (isZh ? '加载中...' : 'Loading...') : `${history?.sample_count || 0} ${isZh ? '个样本' : 'samples'}`}</span>
          </div>
        </div>
        <div className="grid grid-cols-1 xl:grid-cols-[1.4fr_0.6fr] gap-3">
          <div className="rounded-xl border border-black/8 bg-[linear-gradient(180deg,rgba(2,6,23,0.01),rgba(2,6,23,0.04))] p-3 h-[240px]">
            {historySeries.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={historySeries} margin={{ top: 6, right: 10, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="2 4" vertical={false} stroke={ct.gridAlt} />
                  <XAxis dataKey="ts" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: ct.axisAlt }} tickFormatter={(value) => new Date(String(value)).toLocaleString(isZh ? 'zh-CN' : 'en-US', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })} minTickGap={28} />
                  <YAxis yAxisId="score" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: ct.axisAlt }} domain={[0, 100]} width={32} />
                  <YAxis yAxisId="count" orientation="right" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: ct.axisAlt }} width={28} />
                  <Tooltip
                    contentStyle={{ borderRadius: 10, borderColor: ct.tooltipBorder, boxShadow: ct.tooltipShadow, padding: '10px 12px', background: ct.tooltipBg, color: ct.tooltipText }}
                    labelFormatter={(value) => new Date(String(value)).toLocaleString(isZh ? 'zh-CN' : 'en-US', { hour12: false })}
                  />
                  <Area yAxisId="score" type="monotone" dataKey="average_score" name={isZh ? '平均健康分' : 'Average score'} stroke="#2563eb" fill="#2563eb1f" strokeWidth={2} isAnimationActive={false} />
                  <Area yAxisId="count" type="monotone" dataKey="critical" name={isZh ? '严重设备' : 'Critical devices'} stroke="#dc2626" fill="#dc262618" strokeWidth={1.6} isAnimationActive={false} />
                  <Area yAxisId="count" type="monotone" dataKey="warning" name={isZh ? '告警设备' : 'Warning devices'} stroke="#d97706" fill="#d9770612" strokeWidth={1.6} isAnimationActive={false} />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex items-center justify-center text-sm text-black/35">{isZh ? '当前还没有健康趋势样本。' : 'No health trend samples are available yet.'}</div>
            )}
          </div>
          <div className="space-y-1.5 max-h-[240px] overflow-y-auto">
            {(historySeries.length > 0 ? [...historySeries].slice(-6).reverse() : []).map((point) => (
              <div key={point.ts} className="rounded-lg border border-black/8 bg-white px-3 py-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-[10px] text-black/35 truncate">{new Date(point.ts).toLocaleString(isZh ? 'zh-CN' : 'en-US', { hour12: false })}</p>
                    <p className="text-base font-semibold text-[#00172D]">{isZh ? '平均分' : 'Avg'} {point.average_score}</p>
                  </div>
                  <span className="shrink-0 text-[10px] font-semibold text-slate-500">{point.total_devices} {isZh ? '台' : 'dev'}</span>
                </div>
                <div className="mt-1.5 flex flex-wrap gap-1.5 text-[10px] font-bold uppercase">
                  <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-emerald-700">{isZh ? '健康' : 'OK'} {point.healthy}</span>
                  <span className="rounded-full bg-amber-100 px-2 py-0.5 text-amber-700">{isZh ? '告警' : 'W'} {point.warning}</span>
                  <span className="rounded-full bg-red-100 px-2 py-0.5 text-red-700">{isZh ? '严重' : 'C'} {point.critical}</span>
                </div>
              </div>
            ))}
            {historySeries.length === 0 && (
              <div className="rounded-lg border border-dashed border-black/10 bg-black/[0.01] p-4 text-center text-sm text-black/40">
                {isZh ? '趋势样本将在采样器运行后出现。' : 'Trend samples will appear after the sampler runs.'}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_1.15fr] gap-3">
        <div className="rounded-2xl border border-black/5 bg-white shadow-sm p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-red-600">{isZh ? '优先排障' : 'Triage'}</p>
              <h3 className="text-base font-semibold text-[#0b2340]">{isZh ? '高风险设备' : 'High-Risk Devices'}</h3>
            </div>
          </div>
          <div className="space-y-1.5">
            {displayedRiskyDevices.length > 0 ? displayedRiskyDevices.map((device) => (
              <button
                key={device.id}
                type="button"
                onClick={() => onShowDetails(device)}
                className="w-full rounded-lg border border-black/10 px-3 py-2 text-left transition-all hover:border-red-200 hover:bg-red-50/20"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-[#0b2340] truncate">{device.hostname || device.ip_address}</p>
                    <p className="text-[11px] text-black/40 truncate">{[device.site, device.role, device.platform].filter(Boolean).join(' · ')}</p>
                  </div>
                  <div className="shrink-0 flex items-center gap-2">
                    <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${statusToneMap[device.health_status || 'unknown'] || statusToneMap.unknown}`}>
                      {device.health_status || 'unknown'}
                    </span>
                    <span className="text-sm font-semibold text-[#00172D] tabular-nums">{Number(device.health_score || 0)}</span>
                  </div>
                </div>
                <div className="mt-1 flex items-center gap-3 text-[11px] text-black/40">
                  <span>{isZh ? '告警' : 'Alerts'} {Number(device.open_alert_count || 0)}</span>
                  <span>{isZh ? 'Down' : 'Down'} {Number(device.interface_down_count || 0)}</span>
                </div>
              </button>
            )) : (
              <div className="rounded-lg border border-dashed border-black/10 bg-black/[0.01] p-4 text-center text-sm text-black/40">
                {hasActiveFilters
                  ? (isZh ? '没有设备匹配当前筛选条件。' : 'No devices match the active filters.')
                  : (isZh ? '当前没有风险设备。' : 'No risky devices right now.')}
              </div>
            )}
          </div>
        </div>

        <div className="rounded-2xl border border-black/5 bg-white shadow-sm p-4 space-y-3">
          <div className="flex items-center gap-2">
            <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#0089ac]">{isZh ? '全网视图' : 'Fleet'}</p>
            <h3 className="text-base font-semibold text-[#0b2340]">{isZh ? '设备健康清单' : 'Device Health Inventory'}</h3>
          </div>
          <div className="overflow-hidden rounded-xl border border-black/10">
            <div className="max-h-[620px] overflow-auto">
              <table className="w-full text-left text-sm">
                <thead className="sticky top-0 bg-black/[0.02] border-b border-black/5">
                  <tr>
                    <th className="px-4 py-3 text-[10px] font-bold uppercase tracking-widest text-black/35">{isZh ? '设备' : 'Device'}</th>
                    <th className="px-4 py-3 text-[10px] font-bold uppercase tracking-widest text-black/35">{isZh ? '健康状态' : 'Health'}</th>
                    <th className="px-4 py-3 text-[10px] font-bold uppercase tracking-widest text-black/35">{isZh ? '评分' : 'Score'}</th>
                    <th className="px-4 py-3 text-[10px] font-bold uppercase tracking-widest text-black/35">{isZh ? '开放告警' : 'Open Alerts'}</th>
                    <th className="px-4 py-3 text-[10px] font-bold uppercase tracking-widest text-black/35">{isZh ? '摘要' : 'Summary'}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-black/5">
                  {fleetRows.map((device) => (
                    <tr key={device.id} className="hover:bg-black/[0.01] cursor-pointer" onClick={() => onShowDetails(device)}>
                      <td className="px-4 py-3">
                        <div className="font-medium text-[#0b2340]">{device.hostname || '-'}</div>
                        <div className="text-[11px] font-mono text-black/40">{device.ip_address || '-'}</div>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex rounded-full px-2 py-1 text-[10px] font-bold uppercase ${statusToneMap[device.health_status || 'unknown'] || statusToneMap.unknown}`}>
                          {device.health_status || 'unknown'}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-semibold text-[#00172D]">{Number(device.health_score || 0)}</td>
                      <td className="px-4 py-3">
                        <span className={severityBadgeClass(Number(device.open_alert_count || 0) > 0 ? (Number(device.critical_open_alerts || 0) > 0 ? 'critical' : 'warning') : 'minor')}>
                          {Number(device.open_alert_count || 0)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-[12px] text-black/55 max-w-[320px] truncate" title={device.health_summary || ''}>{device.health_summary || '-'}</td>
                    </tr>
                  ))}
                  {fleetRows.length === 0 && (
                    <tr>
                      <td colSpan={5} className="px-4 py-8 text-center text-sm text-black/40">
                        {isZh ? '当前没有可展示的健康检测结果。' : 'No device health results are available yet.'}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
      </div>
    </div>
  );
};

export default DeviceHealthTab;