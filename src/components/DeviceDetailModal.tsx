import React, { useMemo } from 'react';
import { motion } from 'motion/react';
import {
  Activity,
  RotateCcw,
  Server,
  ShieldCheck,
  XCircle,
  Zap,
} from 'lucide-react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type {
  Device,
  DeviceConnectionCheckSummary,
  DeviceHealthAlertItem,
  DeviceHealthTrendResponse,
} from '../types';
import { connectionCheckBadgeMeta, formatConnectionCheckTime } from '../utils/connectionHelpers';
import { useChartTheme } from '../hooks/useChartTheme';

interface DeviceOperationalCategory {
  key: string;
  success?: boolean;
  count?: number;
  commands?: string[];
  error?: string;
  records?: unknown[];
  raw_outputs?: Array<{ command?: string; output?: string }>;
}

interface DeviceOperationalData {
  summary?: {
    successful_categories?: number;
    failed_categories?: number;
    total_records?: number;
  };
  collected_at?: string;
  categories?: DeviceOperationalCategory[];
}

interface DeviceDetailModalProps {
  language: string;
  t: (key: string) => string;
  viewingDevice: Device;
  viewingDeviceAlerts: DeviceHealthAlertItem[];
  deviceDetailLoading: boolean;
  viewingDeviceConnectionSummary: DeviceConnectionCheckSummary | null;
  connectionTestingDeviceId: string | null;
  onClose: () => void;
  deviceTrendRangeHours: number;
  onDeviceTrendRangeHoursChange: (hours: number) => void;
  deviceHealthTrend: DeviceHealthTrendResponse | null;
  deviceHealthTrendLoading: boolean;
  deviceOperationalData: DeviceOperationalData | null;
  deviceOperationalDataLoading: boolean;
  onLoadOperationalData: (deviceId: string) => void;
  onTestConnection: (device: Device, mode: 'quick' | 'deep') => void;
  isTestingConnection: boolean;
  onSnmpTest: (deviceId: string) => void;
  snmpTestingId: string | null;
  onSnmpSyncNow: (deviceId: string) => void;
  snmpSyncingId: string | null;
  onGoToAutomation: (device: Device) => void;
}

const operationalCategoryLabelMap: Record<string, { zh: string; en: string }> = {
  interfaces: { zh: '接口信息', en: 'Interfaces' },
  neighbors: { zh: '邻居信息', en: 'Neighbors' },
  arp: { zh: 'ARP', en: 'ARP' },
  mac_table: { zh: 'MAC 地址表', en: 'MAC Table' },
  routing_table: { zh: '路由表', en: 'Routing Table' },
  bgp: { zh: 'BGP', en: 'BGP' },
  ospf: { zh: 'OSPF', en: 'OSPF' },
};

const getHealthToneClass = (status?: string) => {
  if (status === 'critical') return 'bg-red-100 text-red-700';
  if (status === 'warning') return 'bg-amber-100 text-amber-700';
  if (status === 'healthy') return 'bg-emerald-100 text-emerald-700';
  return 'bg-slate-100 text-slate-600';
};

const DeviceDetailModal: React.FC<DeviceDetailModalProps> = ({
  language,
  t,
  viewingDevice,
  viewingDeviceAlerts,
  deviceDetailLoading,
  viewingDeviceConnectionSummary,
  connectionTestingDeviceId,
  onClose,
  deviceTrendRangeHours,
  onDeviceTrendRangeHoursChange,
  deviceHealthTrend,
  deviceHealthTrendLoading,
  deviceOperationalData,
  deviceOperationalDataLoading,
  onLoadOperationalData,
  onTestConnection,
  isTestingConnection,
  onSnmpTest,
  snmpTestingId,
  onSnmpSyncNow,
  snmpSyncingId,
  onGoToAutomation,
}) => {
  const ct = useChartTheme();
  const deviceTrendInsights = useMemo(() => {
    const series = deviceHealthTrend?.series || [];
    if (series.length === 0) {
      return {
        latest: null,
        previous: null,
        scoreDelta: 0,
        alertDelta: 0,
        addedReasons: [] as string[],
        removedReasons: [] as string[],
      };
    }

    const latest = series[series.length - 1];
    const previous = series.length > 1 ? series[series.length - 2] : null;
    const latestReasons = Array.isArray(latest.health_reasons) ? latest.health_reasons : [];
    const previousReasons = previous && Array.isArray(previous.health_reasons) ? previous.health_reasons : [];

    return {
      latest,
      previous,
      scoreDelta: latest && previous ? Number(latest.health_score || 0) - Number(previous.health_score || 0) : 0,
      alertDelta: latest && previous ? Number(latest.open_alert_count || 0) - Number(previous.open_alert_count || 0) : 0,
      addedReasons: latestReasons.filter((reason) => !previousReasons.includes(reason)),
      removedReasons: previousReasons.filter((reason) => !latestReasons.includes(reason)),
    };
  }, [deviceHealthTrend]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        className="flex max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
      >
        <div className="flex shrink-0 flex-wrap items-start justify-between gap-3 border-b border-black/5 bg-black/[0.02] px-5 py-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <Server className="text-black/60" size={24} />
            <div className="min-w-0">
              <h3 className="text-lg font-medium">{t('deviceDetails')}</h3>
              <p className="truncate text-xs text-black/40">{viewingDevice.hostname}</p>
              {(viewingDeviceConnectionSummary || connectionTestingDeviceId === viewingDevice.id) && (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  {connectionTestingDeviceId === viewingDevice.id ? (
                    <span className="rounded-full border border-blue-200 bg-blue-100 px-2 py-1 text-[10px] font-bold uppercase text-blue-700">
                      {language === 'zh' ? '检测中' : 'Running'}
                    </span>
                  ) : viewingDeviceConnectionSummary ? (
                    <span className={`rounded-full border px-2 py-1 text-[10px] font-bold uppercase ${connectionCheckBadgeMeta[viewingDeviceConnectionSummary.status].className}`}>
                      {language === 'zh' ? connectionCheckBadgeMeta[viewingDeviceConnectionSummary.status].zh : connectionCheckBadgeMeta[viewingDeviceConnectionSummary.status].en}
                    </span>
                  ) : null}
                  {viewingDeviceConnectionSummary && (
                    <span className="text-[11px] text-black/40">
                      {(viewingDeviceConnectionSummary.mode === 'deep'
                        ? (language === 'zh' ? 'SSH 登录校验' : 'SSH login check')
                        : (language === 'zh' ? '快速连通性检测' : 'Reachability check'))}
                      {' · '}
                      {formatConnectionCheckTime(viewingDeviceConnectionSummary.checked_at, language)}
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>
          <div className="flex items-center gap-3 self-start sm:self-center">
            <span className="hidden text-[11px] text-black/40 sm:inline">
              {deviceDetailLoading
                ? (language === 'zh' ? '健康详情加载中...' : 'Loading health detail...')
                : (language === 'zh' ? '健康详情已更新' : 'Health detail updated')}
            </span>
            <button onClick={onClose} title={language === 'zh' ? '关闭设备详情' : 'Close device details'} className="text-black/20 hover:text-black">
              <XCircle size={24} />
            </button>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
          <div className="grid grid-cols-1 gap-6 p-5 sm:p-6 xl:grid-cols-[1fr_1fr_0.95fr] xl:gap-8 xl:p-8">
            <div className="space-y-6 self-start xl:sticky xl:top-0">
              <div>
                <h4 className="mb-2 text-[10px] font-bold uppercase tracking-widest text-black/30">{language === 'zh' ? '健康概览' : 'Health Overview'}</h4>
                <div className="space-y-3 rounded-2xl border border-black/5 bg-[linear-gradient(180deg,rgba(0,0,0,0.01),rgba(0,0,0,0.03))] p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-black/35">{language === 'zh' ? '健康评分' : 'Health Score'}</p>
                      <p className="mt-1 text-2xl font-semibold text-[#00172D]">{Math.max(0, Math.min(100, Number(viewingDevice.health_score || 0)))}</p>
                      <p className="text-[11px] text-black/45">{language === 'zh' ? '统一设备健康分' : 'Unified device health score'}</p>
                    </div>
                    <span className={`rounded-full px-3 py-1 text-[10px] font-bold uppercase ${getHealthToneClass(viewingDevice.health_status)}`}>
                      {viewingDevice.health_status === 'critical'
                        ? (language === 'zh' ? '严重' : 'Critical')
                        : viewingDevice.health_status === 'warning'
                          ? (language === 'zh' ? '告警' : 'Warning')
                          : viewingDevice.health_status === 'healthy'
                            ? (language === 'zh' ? '健康' : 'Healthy')
                            : (language === 'zh' ? '未知' : 'Unknown')}
                    </span>
                  </div>
                  <p className="text-sm text-black/60">{viewingDevice.health_summary || (language === 'zh' ? '当前没有检测到明显健康问题。' : 'No material health issue is currently detected.')}</p>
                  <div className="grid grid-cols-2 gap-3 text-xs text-black/50">
                    <div className="rounded-xl border border-black/5 bg-white px-3 py-2">{language === 'zh' ? '开放告警' : 'Open alerts'} <span className="ml-1 font-semibold text-[#00172D]">{Number(viewingDevice.open_alert_count || 0)}</span></div>
                    <div className="rounded-xl border border-black/5 bg-white px-3 py-2">{language === 'zh' ? '接口 Down' : 'Interfaces down'} <span className="ml-1 font-semibold text-[#00172D]">{Number(viewingDevice.interface_down_count || 0)}</span></div>
                    <div className="rounded-xl border border-black/5 bg-white px-3 py-2">{language === 'zh' ? '接口抖动' : 'Flapping'} <span className="ml-1 font-semibold text-[#00172D]">{Number(viewingDevice.interface_flap_count || 0)}</span></div>
                    <div className="rounded-xl border border-black/5 bg-white px-3 py-2">{language === 'zh' ? '高利用率' : 'High util'} <span className="ml-1 font-semibold text-[#00172D]">{Number(viewingDevice.high_util_interface_count || 0)}</span></div>
                  </div>
                </div>
              </div>

              <div>
                <h4 className="mb-2 text-[10px] font-bold uppercase tracking-widest text-black/30">{t('basicInfo')}</h4>
                <div className="space-y-3">
                  <div className="flex justify-between text-sm"><span className="text-black/40">{t('hostname')}</span><span className="font-medium">{viewingDevice.hostname}</span></div>
                  <div className="flex justify-between text-sm"><span className="text-black/40">{t('ipAddress')}</span><span className="font-mono">{viewingDevice.ip_address}</span></div>
                  <div className="flex justify-between text-sm"><span className="text-black/40">{t('platform')}</span><span className="font-medium">{viewingDevice.platform}</span></div>
                  <div className="flex justify-between text-sm"><span className="text-black/40">{t('status')}</span><span className={`text-[10px] font-bold uppercase ${viewingDevice.status === 'online' ? 'text-emerald-600' : 'text-red-600'}`}>{viewingDevice.status}</span></div>
                </div>
              </div>

              {/* ── Tags Section ── */}
              {viewingDevice.tags && viewingDevice.tags.length > 0 && (
                <div>
                  <h4 className="mb-2 text-[10px] font-bold uppercase tracking-widest text-black/30">{language === 'zh' ? '标签' : 'Tags'}</h4>
                  <div className="flex flex-wrap gap-1.5">
                    {viewingDevice.tags.map(tag => (
                      <span
                        key={tag.id}
                        className="inline-flex items-center gap-1 rounded-full border border-black/5 bg-black/[0.03] px-2 py-0.5 text-[11px]"
                        title={tag.description || tag.value}
                      >
                        <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: tag.color || '#06b6d4' }} />
                        <span className="font-medium text-black/70">{language === 'zh' ? (tag.label_zh || tag.label) : tag.label}</span>
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <div>
                <h4 className="mb-2 text-[10px] font-bold uppercase tracking-widest text-black/30">{t('locationRole')}</h4>
                <div className="space-y-3">
                  <div className="flex justify-between text-sm"><span className="text-black/40">{t('site')}</span><span className="font-medium">{viewingDevice.site}</span></div>
                  <div className="flex justify-between text-sm"><span className="text-black/40">{t('role')}</span><span className="font-medium">{viewingDevice.role}</span></div>
                  <div className="flex justify-between text-sm"><span className="text-black/40">SNMP Name</span><span className="font-medium">{viewingDevice.sys_name || '-'}</span></div>
                  <div className="flex justify-between text-sm"><span className="text-black/40">{language === 'zh' ? 'SNMP 位置' : 'SNMP Location'}</span><span className="max-w-[180px] truncate text-right font-medium" title={viewingDevice.sys_location || ''}>{viewingDevice.sys_location || '-'}</span></div>
                  <div className="flex justify-between text-sm"><span className="text-black/40">{language === 'zh' ? '联系人' : 'Contact'}</span><span className="font-medium">{viewingDevice.sys_contact || '-'}</span></div>
                </div>
              </div>
            </div>

            <div className="space-y-6">
              <div>
                <h4 className="mb-2 text-[10px] font-bold uppercase tracking-widest text-black/30">{t('hardwareInfo')}</h4>
                <div className="space-y-3">
                  <div className="flex justify-between text-sm"><span className="text-black/40">{t('model')}</span><span className="font-medium">{viewingDevice.model}</span></div>
                  <div className="flex justify-between text-sm"><span className="text-black/40">{t('serialNumber')}</span><span className="font-mono">{viewingDevice.sn}</span></div>
                  <div className="flex justify-between text-sm"><span className="text-black/40">{t('version')}</span><span className="font-medium">{viewingDevice.version}</span></div>
                  <div className="flex justify-between text-sm"><span className="text-black/40">{t('uptime')}</span><span className="font-medium">{viewingDevice.uptime}</span></div>
                </div>
              </div>

              <div>
                <h4 className="mb-2 text-[10px] font-bold uppercase tracking-widest text-black/30">Environmental Health</h4>
                <div className="space-y-3">
                  <div className="flex justify-between text-sm"><span className="text-black/40">Temperature</span><span className={`font-medium ${viewingDevice.temp == null ? 'text-black/30' : viewingDevice.temp > 50 ? 'text-orange-600' : 'text-emerald-600'}`}>{viewingDevice.temp != null ? `${viewingDevice.temp}°C` : 'N/A'}</span></div>
                  <div className="flex justify-between text-sm"><span className="text-black/40">Fan Status</span><span className={`text-[10px] font-bold uppercase ${!viewingDevice.fan_status ? 'text-black/30' : viewingDevice.fan_status === 'ok' ? 'text-emerald-600' : 'text-red-600'}`}>{viewingDevice.fan_status || 'N/A'}</span></div>
                  <div className="flex justify-between text-sm"><span className="text-black/40">PSU Status</span><span className={`text-[10px] font-bold uppercase ${!viewingDevice.psu_status ? 'text-black/30' : viewingDevice.psu_status === 'redundant' ? 'text-emerald-600' : 'text-orange-600'}`}>{viewingDevice.psu_status || 'N/A'}</span></div>
                </div>
              </div>

              <div>
                <h4 className="mb-2 text-[10px] font-bold uppercase tracking-widest text-black/30">{language === 'zh' ? '健康原因' : 'Health Reasons'}</h4>
                <div className="space-y-2 rounded-2xl border border-black/5 bg-black/[0.01] p-4">
                  {Array.isArray(viewingDevice.health_reasons) && viewingDevice.health_reasons.length > 0 ? viewingDevice.health_reasons.slice(0, 6).map((reason, index) => (
                    <div key={`${reason}-${index}`} className="rounded-xl border border-black/5 bg-white px-3 py-2 text-sm text-black/60">{reason}</div>
                  )) : (
                    <div className="rounded-xl border border-dashed border-black/10 bg-white px-3 py-4 text-sm text-black/40">
                      {language === 'zh' ? '当前没有需要升级处理的健康原因。' : 'There are no escalated health reasons right now.'}
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="space-y-6">
              <div>
                <h4 className="mb-2 text-[10px] font-bold uppercase tracking-widest text-black/30">{language === 'zh' ? '开放告警' : 'Open Alerts'}</h4>
                <div className="max-h-[520px] space-y-2 overflow-auto rounded-2xl border border-black/5 bg-black/[0.01] p-4">
                  {viewingDeviceAlerts.length > 0 ? viewingDeviceAlerts.map((alert) => {
                    const tone = String(alert.severity || '').toLowerCase() === 'critical' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700';
                    return (
                      <div key={alert.id} className="rounded-xl border border-black/5 bg-white p-3">
                        <div className="flex items-center justify-between gap-2">
                          <span className={`rounded-full px-2 py-1 text-[10px] font-bold uppercase ${tone}`}>{String(alert.severity || '').toUpperCase()}</span>
                          <span className="text-[11px] text-black/40">{new Date(alert.created_at).toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US', { hour12: false })}</span>
                        </div>
                        <p className="mt-2 text-sm font-semibold text-[#0b2340]">{alert.title}</p>
                        <p className="mt-1 text-[11px] text-black/55">{alert.message}</p>
                        {alert.interface_name && <p className="mt-2 text-[11px] font-mono text-black/35">{alert.interface_name}</p>}
                      </div>
                    );
                  }) : (
                    <div className="rounded-xl border border-dashed border-black/10 bg-white px-3 py-4 text-sm text-black/40">
                      {deviceDetailLoading
                        ? (language === 'zh' ? '正在加载告警详情...' : 'Loading alert detail...')
                        : (language === 'zh' ? '当前没有未恢复告警。' : 'There are no open alerts right now.')}
                    </div>
                  )}
                </div>
              </div>

              <div>
                <div className="mb-2 flex items-center justify-between gap-3">
                  <h4 className="text-[10px] font-bold uppercase tracking-widest text-black/30">{language === 'zh' ? '健康趋势' : 'Health Trend'}</h4>
                  <div className="flex items-center gap-2">
                    {[1, 24, 168].map((hours) => (
                      <button
                        key={hours}
                        type="button"
                        onClick={() => onDeviceTrendRangeHoursChange(hours)}
                        className={`rounded-lg px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.14em] transition-all ${deviceTrendRangeHours === hours ? 'bg-black text-white' : 'border border-black/10 text-black/50 hover:bg-black/[0.03]'}`}
                      >
                        {hours === 1 ? (language === 'zh' ? '1 小时' : '1h') : hours === 24 ? (language === 'zh' ? '24 小时' : '24h') : (language === 'zh' ? '7 天' : '7d')}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="space-y-3 rounded-2xl border border-black/5 bg-[linear-gradient(180deg,rgba(0,0,0,0.01),rgba(0,0,0,0.03))] p-4">
                  <div className="flex items-center justify-between gap-3 text-[11px] text-black/45">
                    <span>
                      {deviceHealthTrendLoading
                        ? (language === 'zh' ? '趋势加载中...' : 'Loading trend...')
                        : `${deviceHealthTrend?.sample_count || 0} ${language === 'zh' ? '个采样点' : 'samples'}`}
                    </span>
                    <span>{language === 'zh' ? '开放告警' : 'Open alerts'} {Number(viewingDevice.open_alert_count || 0)}</span>
                  </div>
                  <div className="h-[220px] rounded-xl border border-black/5 bg-white p-3">
                    {deviceHealthTrend?.series?.length ? (
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={deviceHealthTrend.series} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                          <CartesianGrid strokeDasharray="2 4" vertical={false} stroke={ct.gridAlt} />
                          <XAxis
                            dataKey="ts"
                            axisLine={false}
                            tickLine={false}
                            tick={{ fontSize: 11, fill: ct.axisAlt }}
                            tickFormatter={(value) => new Date(String(value)).toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })}
                            minTickGap={28}
                          />
                          <YAxis yAxisId="score" axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: ct.axisAlt }} domain={[0, 100]} width={32} />
                          <YAxis yAxisId="alerts" orientation="right" axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: ct.axisAlt }} width={28} />
                          <Tooltip
                            contentStyle={{ borderRadius: 14, borderColor: ct.tooltipBorder, boxShadow: ct.tooltipShadow, padding: '14px 16px', background: ct.tooltipBg, color: ct.tooltipText }}
                            labelFormatter={(value) => new Date(String(value)).toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US', { hour12: false })}
                          />
                          <Area yAxisId="score" type="monotone" dataKey="health_score" name={language === 'zh' ? '健康分' : 'Health score'} stroke="#2563eb" fill="#2563eb1f" strokeWidth={2.1} isAnimationActive={false} />
                          <Area yAxisId="alerts" type="monotone" dataKey="open_alert_count" name={language === 'zh' ? '开放告警' : 'Open alerts'} stroke="#dc2626" fill="#dc262618" strokeWidth={1.8} isAnimationActive={false} />
                        </AreaChart>
                      </ResponsiveContainer>
                    ) : (
                      <div className="flex h-full items-center justify-center text-sm text-black/35">
                        {deviceHealthTrendLoading
                          ? (language === 'zh' ? '正在拉取设备趋势...' : 'Loading device trend...')
                          : (language === 'zh' ? '当前没有该设备的健康趋势样本。' : 'No health trend samples are available for this device yet.')}
                      </div>
                    )}
                  </div>
                  {deviceHealthTrend?.series?.length ? (
                    <div className="grid grid-cols-1 gap-2 text-xs text-black/55">
                      {[...deviceHealthTrend.series].slice(-2).reverse().map((point) => (
                        <div key={point.ts} className="rounded-xl border border-black/5 bg-white px-3 py-2">
                          <div className="flex items-center justify-between gap-3">
                            <span className="font-medium text-[#00172D]">{new Date(point.ts).toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US', { hour12: false })}</span>
                            <span className={`rounded-full px-2 py-1 text-[10px] font-bold uppercase ${getHealthToneClass(point.health_status)}`}>{point.health_status}</span>
                          </div>
                          <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-black/45">
                            <span>{language === 'zh' ? '健康分' : 'Score'} {Number(point.health_score || 0)}</span>
                            <span>{language === 'zh' ? '开放告警' : 'Open alerts'} {Number(point.open_alert_count || 0)}</span>
                            <span>{language === 'zh' ? 'Down 接口' : 'Down links'} {Number(point.interface_down_count || 0)}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : null}
                  <div className="space-y-3 rounded-xl border border-black/5 bg-white p-4">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-black/35">{language === 'zh' ? '最近一次变化' : 'Latest Change'}</p>
                      <span className="text-[11px] text-black/40">
                        {deviceTrendInsights.latest
                          ? new Date(deviceTrendInsights.latest.ts).toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US', { hour12: false })
                          : (language === 'zh' ? '暂无样本' : 'No samples')}
                      </span>
                    </div>
                    {deviceTrendInsights.latest ? (
                      <>
                        <div className="grid grid-cols-2 gap-3 text-xs">
                          <div className="rounded-xl border border-black/5 bg-black/[0.015] px-3 py-2 text-black/55">
                            <span className="block text-[10px] font-bold uppercase tracking-[0.14em] text-black/35">{language === 'zh' ? '健康分变化' : 'Score delta'}</span>
                            <span className={`mt-1 block text-sm font-semibold ${deviceTrendInsights.scoreDelta < 0 ? 'text-red-600' : deviceTrendInsights.scoreDelta > 0 ? 'text-emerald-600' : 'text-[#00172D]'}`}>{deviceTrendInsights.scoreDelta > 0 ? '+' : ''}{deviceTrendInsights.scoreDelta}</span>
                          </div>
                          <div className="rounded-xl border border-black/5 bg-black/[0.015] px-3 py-2 text-black/55">
                            <span className="block text-[10px] font-bold uppercase tracking-[0.14em] text-black/35">{language === 'zh' ? '告警数变化' : 'Alert delta'}</span>
                            <span className={`mt-1 block text-sm font-semibold ${deviceTrendInsights.alertDelta > 0 ? 'text-red-600' : deviceTrendInsights.alertDelta < 0 ? 'text-emerald-600' : 'text-[#00172D]'}`}>{deviceTrendInsights.alertDelta > 0 ? '+' : ''}{deviceTrendInsights.alertDelta}</span>
                          </div>
                        </div>
                        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
                          <div className="rounded-xl border border-red-100 bg-red-50/50 p-3">
                            <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-red-600">{language === 'zh' ? '新增风险原因' : 'New risk reasons'}</p>
                            <div className="mt-2 space-y-2">
                              {deviceTrendInsights.addedReasons.length > 0 ? deviceTrendInsights.addedReasons.slice(0, 4).map((reason) => (
                                <div key={reason} className="rounded-lg border border-red-100 bg-white px-3 py-2 text-xs text-red-700">{reason}</div>
                              )) : (
                                <div className="rounded-lg border border-dashed border-red-200 bg-white/80 px-3 py-2 text-xs text-red-400">{language === 'zh' ? '最近一次采样没有新增风险原因。' : 'No new risk reasons appeared in the latest sample.'}</div>
                              )}
                            </div>
                          </div>
                          <div className="rounded-xl border border-emerald-100 bg-emerald-50/50 p-3">
                            <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-emerald-700">{language === 'zh' ? '已缓解原因' : 'Cleared reasons'}</p>
                            <div className="mt-2 space-y-2">
                              {deviceTrendInsights.removedReasons.length > 0 ? deviceTrendInsights.removedReasons.slice(0, 4).map((reason) => (
                                <div key={reason} className="rounded-lg border border-emerald-100 bg-white px-3 py-2 text-xs text-emerald-700">{reason}</div>
                              )) : (
                                <div className="rounded-lg border border-dashed border-emerald-200 bg-white/80 px-3 py-2 text-xs text-emerald-500">{language === 'zh' ? '最近一次采样没有观察到已缓解原因。' : 'No reasons were cleared in the latest sample.'}</div>
                              )}
                            </div>
                          </div>
                        </div>
                      </>
                    ) : (
                      <div className="rounded-xl border border-dashed border-black/10 bg-black/[0.015] px-3 py-4 text-sm text-black/40">{language === 'zh' ? '至少需要一次健康采样后才能比较原因变化。' : 'At least one health sample is required before reason changes can be compared.'}</div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="px-5 pb-5 sm:px-6 xl:px-8">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div>
                <h4 className="text-[10px] font-bold uppercase tracking-widest text-black/30">{language === 'zh' ? '运行数据视图' : 'Operational Data'}</h4>
                <p className="mt-1 text-xs text-black/40">{language === 'zh' ? '采集接口、邻居、ARP、MAC、路由表、BGP 和 OSPF 的结构化结果。' : 'Collect structured views for interfaces, neighbors, ARP, MAC, routing, BGP, and OSPF.'}</p>
              </div>
              <button
                type="button"
                onClick={() => onLoadOperationalData(viewingDevice.id)}
                disabled={deviceOperationalDataLoading}
                className={`inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold text-white transition-all ${deviceOperationalDataLoading ? 'bg-slate-400' : 'bg-[#00172D] hover:bg-[#0b2849]'}`}
              >
                <RotateCcw size={15} className={deviceOperationalDataLoading ? 'animate-spin' : ''} />
                {deviceOperationalDataLoading
                  ? (language === 'zh' ? '采集中...' : 'Collecting...')
                  : (deviceOperationalData ? (language === 'zh' ? '重新采集' : 'Refresh') : (language === 'zh' ? '开始采集' : 'Collect'))}
              </button>
            </div>

            {!deviceOperationalData ? (
              <div className="rounded-2xl border border-dashed border-black/10 bg-black/[0.015] px-4 py-5 text-sm text-black/40">{language === 'zh' ? '点击“开始采集”后，会按平台命令模板抓取这 6 类运行数据，并用 ntc-templates 解析后展示。' : 'Click Collect to run platform-specific commands for these six categories and display ntc-templates parsing results.'}</div>
            ) : (
              <div className="space-y-4">
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  <div className="rounded-xl border border-black/5 bg-white px-4 py-3 text-sm text-black/55"><p className="text-[10px] font-bold uppercase tracking-[0.14em] text-black/35">{language === 'zh' ? '成功分类' : 'Successful'}</p><p className="mt-1 text-xl font-semibold text-[#00172D]">{Number(deviceOperationalData.summary?.successful_categories || 0)}</p></div>
                  <div className="rounded-xl border border-black/5 bg-white px-4 py-3 text-sm text-black/55"><p className="text-[10px] font-bold uppercase tracking-[0.14em] text-black/35">{language === 'zh' ? '失败分类' : 'Failed'}</p><p className="mt-1 text-xl font-semibold text-[#00172D]">{Number(deviceOperationalData.summary?.failed_categories || 0)}</p></div>
                  <div className="rounded-xl border border-black/5 bg-white px-4 py-3 text-sm text-black/55"><p className="text-[10px] font-bold uppercase tracking-[0.14em] text-black/35">{language === 'zh' ? '结构化记录' : 'Records'}</p><p className="mt-1 text-xl font-semibold text-[#00172D]">{Number(deviceOperationalData.summary?.total_records || 0)}</p></div>
                  <div className="rounded-xl border border-black/5 bg-white px-4 py-3 text-sm text-black/55"><p className="text-[10px] font-bold uppercase tracking-[0.14em] text-black/35">{language === 'zh' ? '采集时间' : 'Collected'}</p><p className="mt-1 text-sm font-semibold text-[#00172D]">{new Date(String(deviceOperationalData.collected_at || '')).toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US', { hour12: false })}</p></div>
                </div>

                <div className="grid gap-4 xl:grid-cols-2">
                  {(Array.isArray(deviceOperationalData.categories) ? deviceOperationalData.categories : []).map((category) => {
                    const records = Array.isArray(category.records) ? category.records : [];
                    const rawOutputs = Array.isArray(category.raw_outputs) ? category.raw_outputs : [];
                    const toneClass = category.success ? 'border-emerald-100' : 'border-red-100';
                    const label = operationalCategoryLabelMap[category.key]?.[language === 'zh' ? 'zh' : 'en'] || category.key;
                    return (
                      <div key={category.key} className={`overflow-hidden rounded-2xl border bg-white ${toneClass}`}>
                        <div className="flex items-center justify-between gap-3 border-b border-black/5 bg-black/[0.02] px-4 py-3">
                          <div>
                            <p className="text-sm font-semibold text-[#00172D]">{label}</p>
                            <p className="mt-1 text-[11px] text-black/40">{Array.isArray(category.commands) ? category.commands.join(' | ') : '-'}</p>
                          </div>
                          <div className="text-right">
                            <span className={`rounded-full px-2 py-1 text-[10px] font-bold uppercase ${category.success ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'}`}>{category.success ? (language === 'zh' ? '成功' : 'OK') : (language === 'zh' ? '失败' : 'Fail')}</span>
                            <p className="mt-1 text-[11px] font-medium text-black/45">{Number(category.count || 0)} {language === 'zh' ? '条' : 'rows'}</p>
                          </div>
                        </div>
                        <div className="space-y-3 p-4">
                          {category.error && <div className="rounded-xl border border-red-100 bg-red-50/60 px-3 py-2 text-xs text-red-700">{category.error}</div>}
                          {records.length > 0 ? (
                            <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-xl bg-black/[0.025] p-3 text-[11px] text-black/65">{JSON.stringify(records.slice(0, 12), null, 2)}</pre>
                          ) : rawOutputs.length > 0 ? (
                            <div className="space-y-2">
                              {rawOutputs.slice(0, 2).map((item, index) => (
                                <div key={`${category.key}-raw-${index}`} className="rounded-xl border border-black/5 bg-black/[0.015] p-3">
                                  <p className="mb-2 text-[10px] font-bold uppercase tracking-[0.14em] text-black/35">{item.command}</p>
                                  <pre className="max-h-40 overflow-auto whitespace-pre-wrap text-[11px] text-black/60">{String(item.output || '').slice(0, 3000)}</pre>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <div className="rounded-xl border border-dashed border-black/10 bg-black/[0.015] px-3 py-4 text-sm text-black/40">{language === 'zh' ? '已执行命令，但没有得到可展示的结构化记录。' : 'Commands ran, but no displayable structured records were returned.'}</div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>

          {viewingDevice.interface_data && viewingDevice.interface_data.length > 0 && (
            <div className="px-5 pb-5 sm:px-6 sm:pb-6 xl:px-8 xl:pb-6">
              <h4 className="mb-3 text-[10px] font-bold uppercase tracking-widest text-black/30">{language === 'zh' ? '接口监控' : 'Interface Monitoring'} ({viewingDevice.interface_data.length})</h4>
              <div className="max-h-60 overflow-auto rounded-xl border border-black/5">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-black/[0.02]">
                    <tr>
                      <th className="px-3 py-2 text-left text-[10px] font-bold uppercase text-black/40">{language === 'zh' ? '接口' : 'Interface'}</th>
                      <th className="px-3 py-2 text-left text-[10px] font-bold uppercase text-black/40">{language === 'zh' ? '状态' : 'Status'}</th>
                      <th className="px-3 py-2 text-right text-[10px] font-bold uppercase text-black/40">{language === 'zh' ? '速率' : 'Speed'}</th>
                      <th className="px-3 py-2 text-right text-[10px] font-bold uppercase text-black/40">IN</th>
                      <th className="px-3 py-2 text-right text-[10px] font-bold uppercase text-black/40">OUT</th>
                      <th className="px-3 py-2 text-right text-[10px] font-bold uppercase text-black/40">{language === 'zh' ? '带宽' : 'BW%'}</th>
                      <th className="px-3 py-2 text-right text-[10px] font-bold uppercase text-black/40">{language === 'zh' ? '错误' : 'Err'}</th>
                      <th className="px-3 py-2 text-right text-[10px] font-bold uppercase text-black/40">{language === 'zh' ? '丢包' : 'Drop'}</th>
                      <th className="px-3 py-2 text-left text-[10px] font-bold uppercase text-black/40">{language === 'zh' ? '描述' : 'Desc'}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-black/5">
                    {viewingDevice.interface_data.map((intf, index) => {
                      const fmtBytes = (bytes: number) => bytes > 1073741824 ? `${(bytes / 1073741824).toFixed(1)} GB` : bytes > 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : bytes > 1024 ? `${(bytes / 1024).toFixed(0)} KB` : `${bytes} B`;
                      const fmtRate = (bps?: number) => {
                        if (bps == null || !Number.isFinite(bps) || bps < 0) return '-';
                        if (bps >= 1_000_000_000) return `${(bps / 1_000_000_000).toFixed(2)} Gbps`;
                        if (bps >= 1_000_000) return `${(bps / 1_000_000).toFixed(2)} Mbps`;
                        if (bps >= 1_000) return `${(bps / 1_000).toFixed(1)} Kbps`;
                        return `${bps.toFixed(0)} bps`;
                      };
                      const totalErr = (intf.in_errors || 0) + (intf.out_errors || 0);
                      const totalDrop = (intf.in_discards || 0) + (intf.out_discards || 0);
                      const maxBw = (intf.bw_in_pct != null || intf.bw_out_pct != null) ? Math.max(intf.bw_in_pct || 0, intf.bw_out_pct || 0) : null;

                      return (
                        <tr key={index} className="hover:bg-black/[0.01]">
                          <td className="px-3 py-1.5 font-mono text-[11px]">{intf.name}</td>
                          <td className="px-3 py-1.5"><span className={`inline-flex items-center gap-1 text-[10px] font-bold uppercase ${intf.status === 'up' ? 'text-emerald-600' : 'text-red-500'}`}><span className={`h-1.5 w-1.5 rounded-full ${intf.status === 'up' ? 'bg-emerald-500' : 'bg-red-500'}`} />{intf.status}</span></td>
                          <td className="px-3 py-1.5 text-right text-black/60">{intf.speed_mbps > 0 ? `${intf.speed_mbps >= 1000 ? `${intf.speed_mbps / 1000}G` : `${intf.speed_mbps}M`}` : '-'}</td>
                          <td className="px-3 py-1.5 text-right font-mono text-[10px]"><div className="text-blue-600">{fmtRate(intf.in_bps)}</div><div className="text-black/30">{fmtBytes(intf.in_octets || 0)}</div></td>
                          <td className="px-3 py-1.5 text-right font-mono text-[10px]"><div className="text-orange-600">{fmtRate(intf.out_bps)}</div><div className="text-black/30">{fmtBytes(intf.out_octets || 0)}</div></td>
                          <td className="px-3 py-1.5 text-right font-mono text-[10px]">{maxBw != null ? <span className={maxBw > 80 ? 'text-red-600' : maxBw > 50 ? 'text-orange-600' : 'text-black/50'}>{maxBw.toFixed(1)}%</span> : <span className="text-black/20">-</span>}</td>
                          <td className="px-3 py-1.5 text-right font-mono text-[10px]"><span className={totalErr > 0 ? 'font-bold text-red-600' : 'text-black/30'}>{totalErr}</span></td>
                          <td className="px-3 py-1.5 text-right font-mono text-[10px]"><span className={totalDrop > 0 ? 'font-bold text-orange-600' : 'text-black/30'}>{totalDrop}</span></td>
                          <td className="max-w-[120px] truncate px-3 py-1.5 text-black/40">{intf.description || '-'}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

        <div className="shrink-0 border-t border-black/5 bg-black/[0.01] px-5 py-4 sm:px-6">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
            <div className="flex flex-wrap gap-3">
              <button onClick={() => onTestConnection(viewingDevice, 'quick')} disabled={isTestingConnection} className="flex items-center gap-2 rounded-xl bg-blue-50 px-6 py-2 text-sm font-medium text-blue-600 transition-all hover:bg-blue-100 disabled:opacity-50"><Activity size={16} />{isTestingConnection ? 'Testing...' : (language === 'zh' ? '快速连通性' : 'Reachability Check')}</button>
              <button onClick={() => onTestConnection(viewingDevice, 'deep')} disabled={isTestingConnection} className="flex items-center gap-2 rounded-xl bg-violet-50 px-6 py-2 text-sm font-medium text-violet-700 transition-all hover:bg-violet-100 disabled:opacity-50"><ShieldCheck size={16} />{isTestingConnection ? 'Testing...' : (language === 'zh' ? 'SSH 登录校验' : 'SSH Login Check')}</button>
              <button onClick={() => onSnmpTest(viewingDevice.id)} disabled={snmpTestingId === viewingDevice.id} className="flex items-center gap-2 rounded-xl bg-emerald-50 px-6 py-2 text-sm font-medium text-emerald-600 transition-all hover:bg-emerald-100 disabled:opacity-50"><Activity size={16} />{snmpTestingId === viewingDevice.id ? 'Testing...' : 'SNMP Test'}</button>
              <button onClick={() => onSnmpSyncNow(viewingDevice.id)} disabled={snmpSyncingId === viewingDevice.id} className="flex items-center gap-2 rounded-xl bg-cyan-50 px-6 py-2 text-sm font-medium text-cyan-700 transition-all hover:bg-cyan-100 disabled:opacity-50"><RotateCcw size={16} className={snmpSyncingId === viewingDevice.id ? 'animate-spin' : ''} />{snmpSyncingId === viewingDevice.id ? (language === 'zh' ? '同步中...' : 'Syncing...') : (language === 'zh' ? '立即同步SNMP' : 'SNMP Sync Now')}</button>
              <button onClick={() => onGoToAutomation(viewingDevice)} className="flex items-center gap-2 rounded-xl border border-black/10 px-6 py-2 text-sm font-medium text-black transition-all hover:bg-black/5"><Zap size={16} />Go to Automation</button>
            </div>
            <div className="flex justify-end"><button onClick={onClose} className="rounded-xl bg-black px-8 py-2 text-sm font-medium text-white shadow-lg shadow-black/20 transition-all hover:bg-black/80">{t('close')}</button></div>
          </div>
        </div>
      </motion.div>
    </div>
  );
};

export default DeviceDetailModal;