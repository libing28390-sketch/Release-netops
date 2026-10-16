import React, { useState, useEffect, useCallback } from 'react';
import {
  TrendingUp,
  Activity,
  Layers,
  CheckCircle,
  AlertOctagon,
  Calendar,
  Sparkles,
} from 'lucide-react';
import PageHero from '../../components/PageHero';

interface AnalyticsData {
  overview: {
    prefixes_count: number;
    ips_count: number;
    pools_count: number;
    vips_count: number;
    leases_count: number;
    total_ips: number;
    used_ips: number;
    free_ips: number;
    utilization_rate: number;
    capacity_prefixes_count: number;
    excluded_prefixes_count: number;
    capacity_policy: string;
  };
  top_utilized_prefixes: Array<{
    id: string;
    prefix: string;
    name: string;
    status: string;
    total_ips: number;
    used_ips: number;
    utilization: number;
  }>;
  site_breakdown: Array<{
    site: string;
    total_ips: number;
    used_ips: number;
    utilization: number;
  }>;
  forecast_trend: Array<{
    day: string;
    allocated: number;
  }>;
}

interface IPUtilizationTabProps {
  language: string;
  t: (key: string) => string;
}

const IPUtilizationTab: React.FC<IPUtilizationTabProps> = ({ language, t }) => {
  const zh = language === 'zh';
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);

  const authHeaders = useCallback(() => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, []);

  useEffect(() => {
    setLoading(true);
    fetch('/api/ipam/analytics', { headers: authHeaders() })
      .then((res) => (res.ok ? res.json() : null))
      .then((payload) => {
        if (payload) setData(payload);
        setLoading(false);
      })
      .catch((e) => {
        console.error(e);
        setLoading(false);
      });
  }, [authHeaders]);

  const getUtilColor = (util: number) => {
    if (util < 60) return 'text-emerald-500 bg-emerald-50 border-emerald-500/10';
    if (util < 80) return 'text-amber-500 bg-amber-50 border-amber-500/10';
    return 'text-rose-500 bg-rose-50 border-rose-500/10';
  };

  const getUtilBarColor = (util: number) => {
    if (util < 60) return 'bg-gradient-to-r from-emerald-400 to-green-500';
    if (util < 80) return 'bg-gradient-to-r from-amber-400 to-orange-500';
    return 'bg-gradient-to-r from-rose-400 to-red-500';
  };

  // Render responsive SVG line chart
  const renderSVGChart = (trend: Array<{ day: string; allocated: number }>) => {
    if (!trend || trend.length === 0) return null;
    const width = 500;
    const height = 150;
    const padding = 30;

    const maxVal = Math.max(...trend.map((d) => d.allocated)) * 1.15 || 100;
    const minVal = Math.min(...trend.map((d) => d.allocated)) * 0.85 || 0;
    const range = maxVal - minVal;

    // Project coordinates
    const points = trend.map((d, index) => {
      const x = trend.length === 1
        ? width / 2
        : padding + (index / (trend.length - 1)) * (width - padding * 2);
      const y = height - padding - ((d.allocated - minVal) / range) * (height - padding * 2);
      return { x, y, label: d.day, val: d.allocated };
    });

    const pathData = points.reduce((acc, p, i) => {
      return i === 0 ? `M ${p.x} ${p.y}` : `${acc} L ${p.x} ${p.y}`;
    }, '');

    // Fill area path
    const areaData = `${pathData} L ${points[points.length - 1].x} ${height - padding} L ${points[0].x} ${height - padding} Z`;

    return (
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-full">
        {/* Gradients */}
        <defs>
          <linearGradient id="chartGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#06b6d4" stopOpacity="0.25" />
            <stop offset="100%" stopColor="#06b6d4" stopOpacity="0.0" />
          </linearGradient>
        </defs>

        {/* Horizontal grid lines */}
        {[0, 0.5, 1].map((ratio, index) => {
          const y = padding + ratio * (height - padding * 2);
          return (
            <line
              key={index}
              x1={padding}
              y1={y}
              x2={width - padding}
              y2={y}
              stroke="#f1f5f9"
              strokeDasharray="4 4"
            />
          );
        })}

        {/* Shaded Area */}
        <path d={areaData} fill="url(#chartGradient)" />

        {/* Smooth line */}
        <path d={pathData} fill="none" stroke="#06b6d4" strokeWidth="2.5" strokeLinecap="round" />

        {/* Data points */}
        {points.map((p, index) => (
          <g key={index} className="group cursor-pointer">
            <circle
              cx={p.x}
              cy={p.y}
              r="4"
              fill="#ffffff"
              stroke="#06b6d4"
              strokeWidth="2"
            />
            {/* Label background and text on hover */}
            <text
              x={p.x}
              y={p.y - 12}
              textAnchor="middle"
              className="text-[9px] font-mono font-bold fill-cyan-700 opacity-80"
            >
              {p.val}
            </text>
            <text
              x={p.x}
              y={height - 10}
              textAnchor="middle"
              className="text-[8px] font-semibold fill-gray-400"
            >
              {p.label}
            </text>
          </g>
        ))}
      </svg>
    );
  };

  if (loading || !data) {
    return (
      <div className="flex-1 flex items-center justify-center text-xs text-gray-400 font-semibold">
        {zh ? '加载分析数据中...' : 'Loading IPAM analytics...'}
      </div>
    );
  }

  const {
    overview,
    top_utilized_prefixes = [],
    site_breakdown = [],
    forecast_trend = [],
  } = data;

  if (!overview) {
    return (
      <div className="flex-1 flex items-center justify-center text-xs text-gray-400 font-semibold">
        {zh ? '暂无分析数据' : 'No analytics data available.'}
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden px-6 py-5 space-y-4">
      <PageHero
        icon={TrendingUp}
        title={zh ? 'IP 利用率与水位分析' : 'IPAM Capacity Analytics'}
        subtitle={zh ? '查看容量网段分配量、整体利用率和站点分布。' : 'Review allocated capacity, network-wide utilization, and site distribution.'}
      />

      {/* Grid Dashboard */}
      <div className="flex-1 overflow-y-auto space-y-4 pr-1">
        
        {/* 1. Overview Cards */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {/* Total Prefixes */}
          <div className="min-w-0 rounded-2xl border border-slate-200/70 bg-white p-4 shadow-sm transition-shadow hover:shadow-md sm:p-5 flex items-center gap-4">
            <div className="w-12 h-12 rounded-2xl bg-cyan-50 flex items-center justify-center text-cyan-500">
              <Layers size={22} />
            </div>
            <div className="min-w-0">
              <p className="truncate text-[10px] font-bold text-gray-400 uppercase tracking-wider">{zh ? '容量网段数' : 'Capacity Prefixes'}</p>
              <h3 className="text-xl font-extrabold text-gray-900 mt-0.5">
                {overview.capacity_prefixes_count}
                <span className="ml-1 text-[10px] font-semibold text-gray-400">
                  {zh ? `排除 ${overview.excluded_prefixes_count}` : `${overview.excluded_prefixes_count} excluded`}
                </span>
              </h3>
            </div>
          </div>

          {/* Allocated IPs */}
          <div className="min-w-0 rounded-2xl border border-slate-200/70 bg-white p-4 shadow-sm transition-shadow hover:shadow-md sm:p-5 flex items-center gap-4">
            <div className="w-12 h-12 rounded-2xl bg-indigo-50 flex items-center justify-center text-indigo-500">
              <Activity size={22} />
            </div>
            <div className="min-w-0">
              <p className="truncate text-[10px] font-bold text-gray-400 uppercase tracking-wider">{zh ? '已分配 IP 数' : 'Allocated IPs'}</p>
              <h3 className="text-xl font-extrabold text-gray-900 mt-0.5">
                {overview.used_ips} <span className="text-xs font-semibold text-gray-400">/ {overview.total_ips}</span>
              </h3>
            </div>
          </div>

          {/* Dynamic Pools & VIPs */}
          <div className="min-w-0 rounded-2xl border border-slate-200/70 bg-white p-4 shadow-sm transition-shadow hover:shadow-md sm:p-5 flex items-center gap-4">
            <div className="w-12 h-12 rounded-2xl bg-emerald-50 flex items-center justify-center text-emerald-500">
              <CheckCircle size={22} />
            </div>
            <div className="min-w-0">
              <p className="truncate text-[10px] font-bold text-gray-400 uppercase tracking-wider">{zh ? '动态池与 VIP 数' : 'Pools & VIPs'}</p>
              <h3 className="text-xl font-extrabold text-gray-900 mt-0.5">
                {overview.pools_count} <span className="text-xs font-semibold text-gray-400">P / {overview.vips_count} V</span>
              </h3>
            </div>
          </div>

          {/* Global Utilization */}
          <div className="min-w-0 rounded-2xl border border-slate-200/70 bg-white p-4 shadow-sm transition-shadow hover:shadow-md sm:p-5 flex items-center gap-4">
            <div className={`w-12 h-12 rounded-2xl flex items-center justify-center border ${getUtilColor(overview.utilization_rate)}`}>
              <TrendingUp size={22} />
            </div>
            <div className="min-w-0">
              <p className="truncate text-[10px] font-bold text-gray-400 uppercase tracking-wider">{zh ? '全网IP利用率' : 'Utilization Rate'}</p>
              <h3 className="text-xl font-extrabold text-gray-900 mt-0.5">{overview.utilization_rate}%</h3>
            </div>
          </div>
        </div>

        {/* 2. Visual Graphs Section */}
        <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-3">
          
          {/* Top Utilized Prefixes */}
          <div className={"flex min-w-0 flex-col rounded-2xl border border-slate-200/70 bg-white p-4 shadow-sm sm:p-5 " + (
            forecast_trend.length > 0 ? 'lg:col-span-2 min-h-[300px]' : 'lg:col-span-3 min-h-[260px]'
          )}>
            <div className="flex items-center justify-between mb-4">
              <h4 className="text-sm font-bold text-gray-900 flex items-center gap-2">
                <AlertOctagon size={16} className="text-rose-500" />
                {zh ? '容量网段利用率 Top 5' : 'Capacity Prefix Utilization (Top 5)'}
              </h4>
              <span className="px-2 py-0.5 rounded-md text-[9px] font-bold bg-slate-50 text-slate-500 border border-slate-200">
                {zh ? '已排除 /31、/32' : '/31 and /32 excluded'}
              </span>
            </div>

            <div className="flex-1 space-y-3">
              {top_utilized_prefixes.length > 0 ? (
                top_utilized_prefixes.map((item) => {
                  const utilization = Math.max(0, Math.min(Number(item.utilization) || 0, 100));
                  return (
                    <div key={item.id} className="rounded-xl border border-slate-100 px-3 py-2.5">
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                        <div className="flex min-w-0 flex-1 items-center gap-2">
                          <span className="shrink-0 font-mono text-xs font-bold text-slate-800">{item.prefix}</span>
                          {item.name && <span className="truncate text-[10px] font-medium text-slate-400">{item.name}</span>}
                        </div>
                        <span className="shrink-0 text-[11px] font-bold text-cyan-700">
                          {item.utilization}% <span className="font-medium text-slate-400">({item.used_ips}/{item.total_ips})</span>
                        </span>
                      </div>
                      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
                        <div
                          className={"h-full rounded-full " + getUtilBarColor(utilization)}
                          style={{ width: `${utilization}%` }}
                        />
                      </div>
                    </div>
                  );
                })
              ) : (
                <div className="flex h-full items-center justify-center rounded-xl border border-dashed border-slate-200 text-xs font-medium text-gray-400">
                  {zh ? '尚无可计算容量的网段' : 'No allocatable capacity prefixes are available.'}
                </div>
              )}
            </div>
          </div>

          {/* Allocation forecast trend */}
          {forecast_trend.length > 0 && (
            <div className="flex min-w-0 flex-col rounded-2xl border border-slate-200/70 bg-white p-4 shadow-sm sm:p-5">
              <h4 className="mb-3 flex items-center gap-2 text-sm font-bold text-gray-900">
                <Sparkles size={16} className="text-cyan-500" />
                {zh ? '容量分配趋势' : 'Capacity Allocation Trend'}
              </h4>
              <div className="flex min-h-[180px] flex-1 items-center justify-center">
                {renderSVGChart(forecast_trend)}
              </div>
            </div>
          )}
        </div>
        {forecast_trend.length === 0 && (
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-xl border border-dashed border-slate-200 bg-white px-4 py-3 text-xs text-slate-500">
            <Sparkles size={15} className="text-cyan-500" />
            <span className="font-semibold">{zh ? '容量分配趋势' : 'Capacity Allocation Trend'}</span>
            <span>{zh ? '暂无历史样本' : 'No historical samples yet'}</span>
          </div>
        )}

        {/* 3. Site breakdowns */}
        <div className="bg-white p-6 rounded-[28px] border border-black/5 shadow-sm">
          <div className="flex items-center gap-2 mb-4">
            <Calendar size={16} className="text-indigo-500" />
            <h4 className="text-sm font-bold text-gray-900">{zh ? '站点物理分区利用率概览' : 'IP Allocation by Site'}</h4>
          </div>

          <div
            className="grid gap-3"
            style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 280px), 1fr))' }}
          >
            {site_breakdown.map((siteItem, index) => (
              <div key={index} className="min-w-0 rounded-xl border border-slate-100 bg-slate-50/60 p-4 transition-colors hover:bg-slate-50">
                <div className="flex justify-between items-start">
                  <span className="min-w-0 flex-1 truncate pr-2 text-xs font-bold text-gray-700">{siteItem.site}</span>
                  <span className={"shrink-0 rounded-full px-2 py-0.5 text-[9px] font-bold " + (
                    siteItem.utilization < 60
                      ? 'bg-emerald-50 text-emerald-600'
                      : siteItem.utilization < 80
                        ? 'bg-amber-50 text-amber-600'
                        : 'bg-rose-50 text-rose-600'
                  )}>
                    {siteItem.utilization}%
                  </span>
                </div>
                <div>
                  <div className="flex justify-between text-[10px] text-gray-400 font-semibold mb-1">
                    <span>{zh ? '分配' : 'Used'}: {siteItem.used_ips}</span>
                    <span>{zh ? '总容量' : 'Total'}: {siteItem.total_ips}</span>
                  </div>
                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-gray-100">
                    <div
                      className={"h-full rounded-full " + getUtilBarColor(Math.max(0, Math.min(Number(siteItem.utilization) || 0, 100)))}
                      style={{ width: `${Math.max(0, Math.min(Number(siteItem.utilization) || 0, 100))}%` }}
                    />
                  </div>
                </div>
              </div>
            ))}
            {site_breakdown.length === 0 && (
              <div className="col-span-full rounded-2xl border border-dashed border-gray-200 py-8 text-center text-xs text-gray-400">
                {zh ? '尚无可按站点汇总的容量网段' : 'No site-scoped capacity prefixes are available.'}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default IPUtilizationTab;
