import React, { useState, useEffect, useCallback } from 'react';
import { TrendingUp, Cpu, HardDrive, Activity, AlertTriangle, RefreshCw, Download } from 'lucide-react';
import { ResponsiveContainer, AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from 'recharts';
import * as XLSX from 'xlsx';
import { sectionHeaderRowClass } from '../components/shared';
import { useChartTheme } from '../hooks/useChartTheme';

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

interface DeviceTrend {
  date: string;
  health_score: number;
  avg_in_util: number;
  avg_out_util: number;
  peak_in_util: number;
  peak_out_util: number;
  busiest_interface: string;
}

interface CapacityPlanningTabProps {
  language: string;
  t: (key: string) => string;
}

const CapacityPlanningTab: React.FC<CapacityPlanningTabProps> = ({ language, t }) => {
  const ct = useChartTheme();
  const [overview, setOverview] = useState<CapacityOverview | null>(null);
  const [warnings, setWarnings] = useState<ForecastWarning[]>([]);
  const [forecastSummary, setForecastSummary] = useState({ total: 0, critical: 0, warning: 0 });
  const [loading, setLoading] = useState(true);
  const [selectedDevice, setSelectedDevice] = useState<ForecastWarning | null>(null);
  const [trend, setTrend] = useState<DeviceTrend[]>([]);
  const [forecast, setForecast] = useState<{ date: string; predicted_util: number }[]>([]);
  const [daysTo80, setDaysTo80] = useState<number | null>(null);
  const [daysTo95, setDaysTo95] = useState<number | null>(null);
  const [trendLoading, setTrendLoading] = useState(false);
  const [trendDays, setTrendDays] = useState(30);

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
        setWarnings(fc.items || []);
        setForecastSummary({ total: fc.total_warnings, critical: fc.critical_count, warning: fc.warning_count });
      }
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const loadDeviceTrend = async (dev: ForecastWarning) => {
    setSelectedDevice(dev);
    setTrendLoading(true);
    try {
      const r = await fetch(`/api/capacity/device/${dev.device_id}/trend?days=${trendDays}`);
      if (r.ok) {
        const data = await r.json();
        setTrend(data.trends || []);
        setForecast(data.forecast || []);
        setDaysTo80(data.days_to_80_pct);
        setDaysTo95(data.days_to_95_pct);
      }
    } catch { /* ignore */ }
    setTrendLoading(false);
  };

  useEffect(() => {
    if (selectedDevice) loadDeviceTrend(selectedDevice);
  }, [trendDays]);

  const handleExport = () => {
    if (warnings.length === 0) return;
    const data = warnings.map(w => ({
      Hostname: w.hostname,
      IP: w.ip_address,
      Platform: w.platform,
      'Risk Level': w.risk_level,
      CPU: `${w.cpu}%`,
      Memory: `${w.memory}%`,
      'Peak Link Util': `${w.peak_link_util}%`,
      Reasons: w.reasons.join(', '),
    }));
    const ws = XLSX.utils.json_to_sheet(data);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, 'Capacity Warnings');
    const ts = new Date().toISOString().replace(/[-:]/g, '').replace('T', '_').slice(0, 15);
    XLSX.writeFile(wb, `capacity_planning_${ts}.xlsx`);
  };

  // Combine trend + forecast for chart
  const chartData = [
    ...trend.map(t => ({ date: t.date, actual: Math.max(t.peak_in_util, t.peak_out_util), predicted: null as number | null })),
    ...forecast.map(f => ({ date: f.date, actual: null as number | null, predicted: f.predicted_util })),
  ];

  return (
    <div className="space-y-5 overflow-auto h-full">
      <div className={sectionHeaderRowClass}>
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-[#00172D]">
            {language === 'zh' ? '容量规划' : 'Capacity Planning'}
          </h2>
          <p className="text-sm text-black/40">
            {language === 'zh' ? '资源使用趋势分析与容量预测，提前发现扩容需求' : 'Resource utilization trends and capacity forecasting'}
          </p>
        </div>
        <div className="flex gap-2 items-center">
          <button onClick={handleExport} className="p-1.5 rounded-lg border border-black/10 text-black/40 hover:text-[#00bceb] hover:border-[#00bceb]/30 transition-all" title={language === 'zh' ? '导出' : 'Export'}>
            <Download size={14} />
          </button>
          <button onClick={loadData} disabled={loading} className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-[#00bceb] text-white text-sm font-semibold hover:bg-[#00a5d0] transition-all disabled:opacity-50">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            {language === 'zh' ? '刷新' : 'Refresh'}
          </button>
        </div>
      </div>

      {/* Overview Cards */}
      {overview && (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
          {[
            { label: language === 'zh' ? '在线设备' : 'Online Devices', value: overview.total_devices, color: 'text-[#00172D]', border: '', icon: Activity },
            { label: language === 'zh' ? '平均CPU' : 'Avg CPU', value: `${overview.avg_cpu}%`, color: overview.avg_cpu >= 80 ? 'text-red-600' : 'text-emerald-600', border: overview.avg_cpu >= 80 ? 'border-l-[3px] border-l-red-500' : '', icon: Cpu },
            { label: language === 'zh' ? '平均内存' : 'Avg Memory', value: `${overview.avg_memory}%`, color: overview.avg_memory >= 80 ? 'text-red-600' : 'text-emerald-600', border: overview.avg_memory >= 80 ? 'border-l-[3px] border-l-red-500' : '', icon: HardDrive },
            { label: language === 'zh' ? 'CPU告警' : 'CPU Warnings', value: overview.high_cpu_count, color: overview.high_cpu_count > 0 ? 'text-red-600' : 'text-emerald-600', border: overview.high_cpu_count > 0 ? 'border-l-[3px] border-l-red-500' : '', icon: AlertTriangle },
            { label: language === 'zh' ? '内存告警' : 'Memory Warnings', value: overview.high_memory_count, color: overview.high_memory_count > 0 ? 'text-orange-500' : 'text-emerald-600', border: overview.high_memory_count > 0 ? 'border-l-[3px] border-l-orange-400' : '', icon: AlertTriangle },
          ].map((card, i) => (
            <div key={i} className={`bg-white px-5 py-4 rounded-2xl shadow-sm border border-black/5 ${card.border}`}>
              <div className="flex items-center justify-between mb-1">
                <p className="text-[11px] font-bold uppercase tracking-wider text-black/30">{card.label}</p>
                <card.icon size={14} className="text-black/20" />
              </div>
              <p className={`text-2xl font-bold monitoring-data ${card.color}`}>{card.value}</p>
            </div>
          ))}
        </div>
      )}

      <div className="grid grid-cols-12 gap-4">
        {/* Warnings List */}
        <div className="col-span-12 lg:col-span-5 bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden">
          <div className="px-4 py-3 border-b border-black/5 bg-black/[0.02] flex items-center justify-between">
            <span className="text-sm font-semibold text-[#00172D]">
              {language === 'zh' ? `容量预警 (${forecastSummary.total})` : `Capacity Warnings (${forecastSummary.total})`}
            </span>
            <div className="flex gap-2 text-[10px] font-bold">
              <span className="px-2 py-0.5 bg-red-100 text-red-700 rounded-full">{language === 'zh' ? '严重' : 'Critical'} {forecastSummary.critical}</span>
              <span className="px-2 py-0.5 bg-orange-100 text-orange-700 rounded-full">{language === 'zh' ? '预警' : 'Warning'} {forecastSummary.warning}</span>
            </div>
          </div>
          <div className="max-h-[500px] overflow-y-auto divide-y divide-black/5">
            {warnings.length === 0 && !loading && (
              <div className="py-16 text-center text-sm text-black/30">
                {language === 'zh' ? '所有设备容量正常' : 'All devices within capacity limits'}
              </div>
            )}
            {warnings.map(w => (
              <button key={w.device_id} onClick={() => loadDeviceTrend(w)} className={`w-full text-left px-4 py-3 hover:bg-black/[0.02] transition-colors ${selectedDevice?.device_id === w.device_id ? 'bg-[#00bceb]/5 border-l-[3px] border-l-[#00bceb]' : ''}`}>
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-semibold text-[#00172D]">{w.hostname}</p>
                    <p className="text-[11px] text-black/40">{w.ip_address} · {w.platform}</p>
                    <div className="flex gap-3 mt-1 text-[10px] monitoring-data">
                      <span className={w.cpu >= 90 ? 'text-red-600' : w.cpu >= 80 ? 'text-orange-500' : 'text-black/40'}>CPU {w.cpu}%</span>
                      <span className={w.memory >= 90 ? 'text-red-600' : w.memory >= 80 ? 'text-orange-500' : 'text-black/40'}>MEM {w.memory}%</span>
                      <span className={w.peak_link_util >= 90 ? 'text-red-600' : w.peak_link_util >= 75 ? 'text-orange-500' : 'text-black/40'}>Link {w.peak_link_util}%</span>
                    </div>
                  </div>
                  <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full ${
                    w.risk_level === 'critical' ? 'bg-red-100 text-red-700' : 'bg-orange-100 text-orange-700'
                  }`}>{w.risk_level}</span>
                </div>
              </button>
            ))}
          </div>

          {/* Hot Interfaces */}
          {overview && overview.hot_interfaces.length > 0 && (
            <div className="border-t border-black/5">
              <div className="px-4 py-3 bg-black/[0.02]">
                <span className="text-xs font-semibold text-[#00172D]">{language === 'zh' ? '热点接口 (>50%利用率)' : 'Hot Interfaces (>50% util)'}</span>
              </div>
              <div className="divide-y divide-black/5 max-h-[200px] overflow-y-auto">
                {overview.hot_interfaces.slice(0, 8).map((intf, i) => (
                  <div key={i} className="px-4 py-2 flex items-center justify-between">
                    <div>
                      <p className="text-xs font-medium text-[#00172D]">{intf.hostname}</p>
                      <p className="text-[10px] text-black/40">{intf.interface_name}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-xs font-bold text-orange-500 monitoring-data">{Math.round(Math.max(intf.avg_in_util || 0, intf.avg_out_util || 0))}%</p>
                      <p className="text-[10px] text-black/30 monitoring-data">peak {Math.round(Math.max(intf.peak_in_util || 0, intf.peak_out_util || 0))}%</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Trend Chart */}
        <div className="col-span-12 lg:col-span-7 bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden">
          {!selectedDevice ? (
            <div className="flex flex-col items-center justify-center h-[500px]">
              <TrendingUp size={40} className="text-black/10 mb-3" />
              <p className="text-sm text-black/30">{language === 'zh' ? '选择设备查看趋势分析' : 'Select a device to view trend analysis'}</p>
            </div>
          ) : trendLoading ? (
            <div className="flex items-center justify-center h-[500px]">
              <RefreshCw size={24} className="animate-spin text-[#00bceb]" />
            </div>
          ) : (
            <div className="flex flex-col h-full">
              <div className="px-4 py-3 border-b border-black/5 bg-black/[0.02] flex items-center justify-between">
                <div>
                  <p className="text-sm font-semibold text-[#00172D]">{selectedDevice.hostname}</p>
                  <p className="text-[11px] text-black/40">{selectedDevice.ip_address}</p>
                </div>
                <div className="flex items-center gap-3">
                  {daysTo80 !== null && (
                    <span className="text-[10px] px-2 py-1 rounded-full bg-orange-100 text-orange-700 font-bold">
                      {language === 'zh' ? `${daysTo80}天达80%` : `80% in ${daysTo80}d`}
                    </span>
                  )}
                  {daysTo95 !== null && (
                    <span className="text-[10px] px-2 py-1 rounded-full bg-red-100 text-red-700 font-bold">
                      {language === 'zh' ? `${daysTo95}天达95%` : `95% in ${daysTo95}d`}
                    </span>
                  )}
                  <div className="flex gap-1 bg-black/5 rounded-lg p-0.5">
                    {[7, 30, 90].map(d => (
                      <button key={d} onClick={() => setTrendDays(d)} className={`px-2 py-1 rounded-md text-[10px] font-bold transition-all ${trendDays === d ? 'bg-white shadow-sm text-[#00172D]' : 'text-black/40 hover:text-black/60'}`}>{d}d</button>
                    ))}
                  </div>
                </div>
              </div>

              {/* Utilization Trend Chart */}
              <div className="px-4 pt-4">
                <h3 className="text-xs font-semibold text-[#00172D] mb-3 flex items-center gap-2">
                  <TrendingUp size={14} className="text-[#00bceb]" />
                  {language === 'zh' ? '链路利用率趋势与预测' : 'Link Utilization Trend & Forecast'}
                </h3>
                <div className="h-[220px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={chartData}>
                      <defs>
                        <linearGradient id="colorActual" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#00bceb" stopOpacity={0.15} />
                          <stop offset="95%" stopColor="#00bceb" stopOpacity={0} />
                        </linearGradient>
                        <linearGradient id="colorPredicted" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#f97316" stopOpacity={0.15} />
                          <stop offset="95%" stopColor="#f97316" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={ct.grid} />
                      <XAxis dataKey="date" axisLine={false} tickLine={false} tick={{ fontSize: 9, fill: ct.axis }} interval={Math.max(0, Math.floor(chartData.length / 8) - 1)} />
                      <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 9, fill: ct.axis }} domain={[0, 100]} unit="%" />
                      <Tooltip contentStyle={{ borderRadius: 12, border: 'none', boxShadow: ct.tooltipShadow, fontSize: 12, background: ct.tooltipBg, color: ct.tooltipText }} />
                      <Area type="monotone" dataKey="actual" stroke="#00bceb" strokeWidth={2} fillOpacity={1} fill="url(#colorActual)" name={language === 'zh' ? '实际利用率' : 'Actual'} connectNulls={false} />
                      <Area type="monotone" dataKey="predicted" stroke="#f97316" strokeWidth={2} strokeDasharray="5 3" fillOpacity={1} fill="url(#colorPredicted)" name={language === 'zh' ? '预测' : 'Forecast'} connectNulls={false} />
                      {/* Threshold lines */}
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </div>

              {/* Resource Bars */}
              <div className="px-4 py-4 mt-auto border-t border-black/5">
                <h3 className="text-xs font-semibold text-[#00172D] mb-3">{language === 'zh' ? '当前资源使用' : 'Current Resource Usage'}</h3>
                <div className="space-y-3">
                  {[
                    { label: 'CPU', value: selectedDevice.cpu, color: selectedDevice.cpu >= 90 ? '#ef4444' : selectedDevice.cpu >= 80 ? '#f97316' : '#10b981' },
                    { label: language === 'zh' ? '内存' : 'Memory', value: selectedDevice.memory, color: selectedDevice.memory >= 90 ? '#ef4444' : selectedDevice.memory >= 80 ? '#f97316' : '#10b981' },
                    { label: language === 'zh' ? '链路峰值' : 'Link Peak', value: selectedDevice.peak_link_util, color: selectedDevice.peak_link_util >= 90 ? '#ef4444' : selectedDevice.peak_link_util >= 75 ? '#f97316' : '#10b981' },
                  ].map((item, i) => (
                    <div key={i}>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-medium text-black/60">{item.label}</span>
                        <span className="text-xs font-bold monitoring-data" style={{ color: item.color }}>{item.value}%</span>
                      </div>
                      <div className="h-2 bg-black/5 rounded-full overflow-hidden">
                        <div className="h-full rounded-full transition-all duration-500" style={{ width: `${item.value}%`, backgroundColor: item.color }} />
                      </div>
                    </div>
                  ))}
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
