import React, { useEffect, useMemo, useState } from 'react';
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
import { apiRequest } from '../api/http';
import PlatformProfileSelector, { type PlatformProfileOption } from './PlatformProfileSelector';
import { inferPlatformVendor, platformVendorLabel } from '../utils/platformVendor';

interface PlatformIdentificationResult {
  status?: string;
  version?: string;
  commands?: string[];
  selected?: { platform_profile_id?: string; platform_code?: string; name_zh?: string; name_en?: string } | null;
  suggestions?: Array<{ platform_profile_id?: string; platform_code?: string; name_zh?: string; name_en?: string; score?: number }>;
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
  onTestConnection: (device: Device, mode: 'quick' | 'deep') => void;
  isTestingConnection: boolean;
  onSnmpTest: (deviceId: string) => void;
  snmpTestingId: string | null;
  onSnmpSyncNow: (deviceId: string) => void;
  snmpSyncingId: string | null;
  onPlatformBindingSaved?: (binding: Pick<Device, 'platform' | 'platform_profile_id' | 'platform_locked'>) => void;
  onGoToAutomation: (device: Device) => void;
}

const getHealthToneClass = (status?: string) => {
  if (status === 'critical') return 'bg-red-100 text-red-700';
  if (status === 'warning') return 'bg-amber-100 text-amber-700';
  if (status === 'healthy') return 'bg-emerald-100 text-emerald-700';
  return 'bg-slate-100 text-slate-600';
};

const isHardwareStatusNormal = (value: unknown) => {
  if (value === true || value === 1) return true;
  const normalized = String(value ?? '').trim().toLowerCase();
  return ['true', '1', 'ok', 'normal', 'redundant', 'single', 'up', 'running', 'ready'].includes(normalized);
};

const DEVICE_ROLE_ZH: Record<string, string> = {
  core: '核心',
  distribution: '汇聚',
  access: '接入',
  firewall: '防火墙',
  router: '路由器',
  switch: '交换机',
  server: '服务器',
  wireless: '无线',
  unassigned: '未分配',
};

const formatRoleLabel = (value: unknown, language: string) => {
  const raw = String(value ?? '').trim();
  if (!raw) return '—';
  if (language !== 'zh') return raw;
  return DEVICE_ROLE_ZH[raw.toLowerCase()] || raw;
};

const formatStatusLabel = (value: unknown, language: string) => {
  const raw = String(value ?? '').trim();
  if (!raw) return '—';
  if (language !== 'zh') return raw;
  const labels: Record<string, string> = {
    online: '在线',
    offline: '离线',
    pending: '待确认',
    unknown: '未知',
    normal: '正常',
    abnormal: '异常',
    healthy: '健康',
    warning: '告警',
    critical: '严重',
    major: '重要',
    minor: '次要',
    up: '正常',
    down: '异常',
  };
  return labels[raw.toLowerCase()] || raw;
};

const formatPlatformLabel = (value: unknown, language: string) => {
  const raw = String(value ?? '').trim();
  if (!raw) return '—';
  if (language !== 'zh') return raw;
  const labels: Record<string, string> = {
    h3c_comware: '华三 Comware',
    h3c_comware_v3: '华三 Comware V3',
    hp_comware: '华三 Comware',
    huawei_vrp: '华为 VRP',
    cisco_ios: 'Cisco IOS',
    cisco_nxos: 'Cisco NX-OS',
    generic: '通用平台',
    unknown: '未知平台',
  };
  return labels[raw.toLowerCase()] || raw;
};

const formatUptime = (value: unknown, language: string) => {
  const raw = String(value ?? '').trim();
  if (!raw) return '—';

  // H3C sysUpTime is sometimes exposed by the API as HH:MM:SS.microseconds.
  const clock = raw.match(/^(?:(\d+):)?(\d+):(\d+)(?:\.\d+)?$/);
  if (clock) {
    const hours = Number(clock[1] || 0);
    const minutes = Number(clock[2] || 0);
    const seconds = Number(clock[3] || 0);
    if (language === 'zh') {
      return [hours ? `${hours}小时` : '', minutes ? `${minutes}分钟` : '', `${seconds}秒`]
        .filter(Boolean)
        .join('');
    }
    return `${hours}h ${minutes}m ${seconds}s`;
  }

  const days = raw.match(/^(\d+)d\s+(\d+)h\s+(\d+)m(?:\s+(\d+)s)?$/i);
  if (days) {
    const [day, hour, minute, second] = days.slice(1).map((item) => Number(item || 0));
    if (language === 'zh') {
      return [day ? `${day}天` : '', hour ? `${hour}小时` : '', minute ? `${minute}分钟` : '', second ? `${second}秒` : '']
        .filter(Boolean)
        .join('') || '0秒';
    }
    return `${day}d ${hour}h ${minute}m${second ? ` ${second}s` : ''}`;
  }

  return raw;
};

const localizeHealthText = (value: unknown, language: string) => {
  const raw = String(value ?? '').trim();
  if (!raw || language !== 'zh') return raw;
  if (/^no (?:active )?health issues detected$/i.test(raw) || /^no material health issue is currently detected\.?$/i.test(raw)) {
    return '未检测到健康问题';
  }
  if (/^fan status indicates a hardware failure$/i.test(raw)) return '风扇状态显示存在硬件故障';
  if (/^power supply status indicates a failure$/i.test(raw)) return '电源状态显示存在故障';
  if (/^power supply lost redundancy$/i.test(raw)) return '电源失去冗余';
  const temperature = raw.match(/^temperature is (?:high|elevated) at\s+([\d.]+)\s*°?C$/i);
  if (temperature) return `温度过高：${temperature[1]}℃`;
  const cpu = raw.match(/^CPU usage is (?:(?:high|elevated at)\s+)?([\d.]+)%$/i);
  if (cpu) return `CPU 使用率过高：${cpu[1]}%`;
  const memory = raw.match(/^Memory usage is (?:(?:high|elevated at)\s+)?([\d.]+)%$/i);
  if (memory) return `内存使用率过高：${memory[1]}%`;
  const interfaceP95 = raw.match(/^Interface (.+) P95 is ([\d.]+)%$/i);
  if (interfaceP95) return `接口 ${interfaceP95[1]} P95 利用率为 ${interfaceP95[2]}%`;
  const openAlerts = raw.match(/^(\d+)\s+major alert\(s\) are still open$/i);
  if (openAlerts) return `${openAlerts[1]} 个重要告警仍未恢复`;
  return raw;
};

const SNMP_PROFILE_STATUS_ZH: Record<string, string> = {
  verified: '已验证',
  unverified: '待验证',
  failed: '验证失败',
  none: '未配置',
};
const SNMP_PROFILE_SOURCE_ZH: Record<string, string> = {
  snmp_template: 'SNMP 型号模板',
  official: '官方内置模板',
  custom: '自定义模板',
  legacy: '迁移的旧模板',
  model_profile: '型号模板',
  device_override: '旧版单台覆盖（已忽略）',
  mixed: 'SNMP 型号模板',
  template_blocked: '模板未生效',
  template_not_applied: '未应用 SNMP 模板',
  builtin_default: '已停用的内置默认',
};
const SNMP_PROFILE_SOURCE_EN: Record<string, string> = {
  snmp_template: 'SNMP model template',
  official: 'Official built-in template',
  custom: 'Custom template',
  legacy: 'Migrated legacy template',
  none: 'No template selected',
  model_profile: 'Model template',
  device_override: 'Legacy device override (ignored)',
  mixed: 'SNMP model template',
  template_blocked: 'Template blocked',
  template_not_applied: 'SNMP template not applied',
  builtin_default: 'Disabled built-in default',
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
  onTestConnection,
  isTestingConnection,
  onSnmpTest,
  snmpTestingId,
  onSnmpSyncNow,
  snmpSyncingId,
  onPlatformBindingSaved,
  onGoToAutomation,
}) => {
  const ct = useChartTheme();
  const [platformProfiles, setPlatformProfiles] = useState<PlatformProfileOption[]>([]);
  const [platformProfilesLoading, setPlatformProfilesLoading] = useState(false);
  const [platformDetectionLoading, setPlatformDetectionLoading] = useState(false);
  const [platformBindingLoading, setPlatformBindingLoading] = useState(false);
  const [platformResult, setPlatformResult] = useState<PlatformIdentificationResult | null>(null);
  const [platformError, setPlatformError] = useState('');
  const [platformMessage, setPlatformMessage] = useState('');
  const [selectedPlatformProfileId, setSelectedPlatformProfileId] = useState(viewingDevice.platform_profile_id || '');
  const [lockPlatformBinding, setLockPlatformBinding] = useState(Boolean(viewingDevice.platform_locked));
  const snmpProfile = viewingDevice.snmp_metric_profile;
  const snmpProfileStatus = snmpProfile?.status || 'none';
  const snmpProfileSource = snmpProfile?.template_source || snmpProfile?.source || 'template_not_applied';
  const snmpProfileName = snmpProfile?.id
    ? snmpProfile.name || [snmpProfile.vendor, snmpProfile.model].filter(Boolean).join(' · ') || snmpProfile.id
    : (language === 'zh' ? '未关联型号模板' : 'No model template');
  const snmpMetricLabels: Record<string, string> = language === 'zh'
    ? { cpu: 'CPU', memory: '内存', temperature: '温度', fan: '风扇', power_supply: '电源' }
    : { cpu: 'CPU', memory: 'Memory', temperature: 'Temp', fan: 'Fan', power_supply: 'PSU' };
  const snmpHealthMetrics = (snmpProfile?.metric_keys || [])
    .map((key) => snmpMetricLabels[key] || key)
    .join(' / ');
  const identificationVersion = String(platformResult?.version || viewingDevice.version || '').trim();
  const platformAlreadyBound = Boolean(viewingDevice.platform_profile_id);
  const deviceVendor = inferPlatformVendor(viewingDevice.vendor, viewingDevice.platform);

  useEffect(() => {
    let active = true;
    setSelectedPlatformProfileId(viewingDevice.platform_profile_id || '');
    setLockPlatformBinding(Boolean(viewingDevice.platform_locked) || !viewingDevice.platform_profile_id);
    setPlatformResult(null);
    setPlatformError('');
    setPlatformMessage('');
    setPlatformProfilesLoading(true);
    void apiRequest<{ data: PlatformProfileOption[] }>('/api/platform-registry/profiles')
      .then((response) => { if (active) setPlatformProfiles(response.data || []); })
      .catch(() => { if (active) setPlatformProfiles([]); })
      .finally(() => { if (active) setPlatformProfilesLoading(false); });
    return () => { active = false; };
  }, [viewingDevice.id, viewingDevice.platform_locked, viewingDevice.platform_profile_id]);

  const detectPlatform = async () => {
    setPlatformDetectionLoading(true);
    setPlatformError('');
    setPlatformMessage('');
    try {
      const response = await apiRequest<{ data: PlatformIdentificationResult }>(
        `/api/devices/${encodeURIComponent(viewingDevice.id)}/platform-detect`,
        { method: 'POST', body: '{}' },
      );
      setPlatformResult(response.data);
      const selected = response.data?.selected?.platform_profile_id;
      // Detection is a suggestion. Never replace an existing manual binding
      // just because a later probe produced a different candidate.
      if (selected && !viewingDevice.platform_profile_id) setSelectedPlatformProfileId(selected);
    } catch (cause) {
      setPlatformError(cause instanceof Error ? cause.message : (language === 'zh' ? '自动识别失败' : 'Platform detection failed'));
    } finally {
      setPlatformDetectionLoading(false);
    }
  };

  const bindPlatform = async () => {
    if (!selectedPlatformProfileId) {
      setPlatformMessage('');
      setPlatformError(language === 'zh' ? '请选择要绑定的平台' : 'Select a platform to bind');
      return;
    }
    if (!deviceVendor) {
      setPlatformMessage('');
      setPlatformError(language === 'zh' ? '设备厂商未知，不能绑定平台。请先补充厂商或完成自动识别。' : 'The device vendor is unknown; add it or run detection before binding.');
      return;
    }
    const sameBinding = String(viewingDevice.platform_profile_id || '') === String(selectedPlatformProfileId || '')
      && Boolean(viewingDevice.platform_locked) === Boolean(lockPlatformBinding);
    const selectedProfile = platformProfiles.find((profile) => profile.id === selectedPlatformProfileId);
    const currentProfile = platformProfiles.find((profile) => profile.id === viewingDevice.platform_profile_id);
    const selectedProfileName = selectedProfile
      ? (language === 'zh' ? (selectedProfile.name_zh || selectedProfile.platform_code) : (selectedProfile.name_en || selectedProfile.platform_code))
      : selectedPlatformProfileId;
    const currentProfileName = currentProfile
      ? (language === 'zh' ? (currentProfile.name_zh || currentProfile.platform_code) : (currentProfile.name_en || currentProfile.platform_code))
      : (viewingDevice.platform || (language === 'zh' ? '未绑定' : 'Unbound'));
    if (sameBinding) {
      setPlatformError('');
      setPlatformMessage(language === 'zh'
        ? `已绑定当前平台：${selectedProfileName}，无需重复绑定。`
        : `Already bound to ${selectedProfileName}; no duplicate binding is needed.`);
      setPlatformResult((current) => current ? { ...current, status: 'BOUND' } : { status: 'BOUND' });
      return;
    }
    const platformChanged = Boolean(viewingDevice.platform_profile_id)
      && String(viewingDevice.platform_profile_id) !== String(selectedPlatformProfileId);
    if (platformChanged) {
      const confirmed = window.confirm(language === 'zh'
        ? `平台绑定会影响自动化执行所使用的驱动、命令和解析模板。\n\n当前平台：${currentProfileName}\n切换为：${selectedProfileName}\n\n确认切换平台吗？`
        : `Platform binding controls the driver, command catalog, and parser used by automation.\n\nCurrent platform: ${currentProfileName}\nSwitch to: ${selectedProfileName}\n\nConfirm the platform change?`);
      if (!confirmed) return;
    }
    const bindingLock = platformAlreadyBound ? lockPlatformBinding : true;
    setPlatformBindingLoading(true);
    setPlatformError('');
    setPlatformMessage('');
    try {
      const response = await apiRequest<{ data?: Device & { binding_unchanged?: boolean } }>(`/api/devices/${encodeURIComponent(viewingDevice.id)}/platform-binding`, {
        method: 'PUT',
        body: JSON.stringify({ platform_profile_id: selectedPlatformProfileId, lock: bindingLock, force: platformChanged }),
      });
      const saved = response.data;
      const bindingUnchanged = Boolean(saved?.binding_unchanged);
      if (saved) {
        onPlatformBindingSaved?.({
          platform: saved.platform || viewingDevice.platform,
          platform_profile_id: saved.platform_profile_id || selectedPlatformProfileId,
          platform_locked: saved.platform_locked ?? bindingLock,
        });
      }
      setPlatformError('');
      setPlatformMessage(language === 'zh'
        ? (bindingUnchanged ? `已绑定当前平台：${selectedProfileName}，无需重复绑定。` : `平台绑定已保存：${selectedProfileName}`)
        : (bindingUnchanged ? `Already bound to ${selectedProfileName}; no duplicate binding is needed.` : `Platform binding saved: ${selectedProfileName}`));
      setPlatformResult((current) => current ? { ...current, status: 'BOUND' } : { status: 'BOUND' });
    } catch (cause) {
      setPlatformError(cause instanceof Error ? cause.message : (language === 'zh' ? '平台绑定失败' : 'Platform binding failed'));
    } finally {
      setPlatformBindingLoading(false);
    }
  };
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
        className="flex max-h-[92vh] w-full max-w-[1400px] flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
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
          <div className="grid grid-cols-1 gap-5 p-4 sm:p-5 xl:grid-cols-[1.05fr_1.05fr_0.95fr] xl:items-start xl:gap-5 xl:p-6">
            <div className="space-y-4 self-start xl:sticky xl:top-0">
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
                  <p className="text-sm text-black/60">{localizeHealthText(viewingDevice.health_summary, language) || (language === 'zh' ? '未检测到健康问题。' : 'No material health issue is currently detected.')}</p>
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
                  <div className="flex justify-between text-sm"><span className="text-black/40">{language === 'zh' ? '主机名' : t('hostname')}</span><span className="font-medium">{viewingDevice.hostname}</span></div>
                  <div className="flex justify-between text-sm"><span className="text-black/40">{language === 'zh' ? '管理 IP' : t('ipAddress')}</span><span className="font-mono">{viewingDevice.ip_address}</span></div>
                  <div className="flex justify-between text-sm"><span className="text-black/40">{language === 'zh' ? '平台' : t('platform')}</span><span className="font-medium">{formatPlatformLabel(viewingDevice.platform, language)}</span></div>
                  <div className="flex justify-between text-sm"><span className="text-black/40">{language === 'zh' ? '状态' : t('status')}</span><span className={`text-[10px] font-bold ${viewingDevice.status === 'online' ? 'text-emerald-600' : 'text-red-600'}`}>{formatStatusLabel(viewingDevice.status, language)}</span></div>
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
                        title={tag.description || tag.code}
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
                  <div className="flex justify-between text-sm"><span className="text-black/40">{language === 'zh' ? '站点（资产）' : 'Asset site'}</span><span className="font-medium">{viewingDevice.site || '—'}</span></div>
                  <div className="flex justify-between text-sm"><span className="text-black/40">{language === 'zh' ? '角色（资产）' : 'Asset role'}</span><span className="font-medium">{formatRoleLabel(viewingDevice.role, language)}</span></div>
                  <div className="flex justify-between text-sm"><span className="text-black/40">{language === 'zh' ? 'SNMP 系统名称' : 'SNMP sysName'}</span><span className="font-medium">{viewingDevice.sys_name || '—'}</span></div>
                  <div className="flex justify-between text-sm"><span className="text-black/40">{language === 'zh' ? 'SNMP 位置（设备 MIB）' : 'SNMP sysLocation'}</span><span className="max-w-[180px] truncate text-right font-medium" title={viewingDevice.sys_location || ''}>{viewingDevice.sys_location || '—'}</span></div>
                  <div className="flex justify-between text-sm"><span className="text-black/40">{language === 'zh' ? 'SNMP 联系人' : 'SNMP sysContact'}</span><span className="font-medium">{viewingDevice.sys_contact || '—'}</span></div>
                </div>
                <p className="mt-2 text-[11px] leading-5 text-black/40">
                  {language === 'zh'
                    ? '资产站点/角色来自资产台账；SNMP 名称、位置和联系人来自设备标准 MIB，是设备自报信息。'
                    : 'Asset site/role come from inventory; SNMP name, location and contact are device-reported standard MIB values.'}
                </p>
              </div>
            </div>

            <div className="space-y-4">
              <div className="rounded-2xl border border-cyan-100 bg-cyan-50/60 p-4">
                <div className="mb-3 flex items-center justify-between gap-2">
                  <div>
                    <h4 className="text-[10px] font-bold uppercase tracking-widest text-cyan-900">{language === 'zh' ? '平台识别与绑定' : 'Platform identification & binding'}</h4>
                    <p className="mt-1 text-[11px] text-cyan-800/70">{platformAlreadyBound ? (language === 'zh' ? '当前绑定控制自动化驱动、命令和解析模板；修改已有绑定需要管理员确认。' : 'The current binding controls the automation driver, commands, and parser; changing it requires Administrator confirmation.') : (language === 'zh' ? '首次绑定后自动锁定，并决定自动化驱动、命令和解析模板。' : 'The first binding is locked automatically and controls the automation driver, commands, and parser.')}</p>
                  </div>
                  <button type="button" onClick={() => void detectPlatform()} disabled={platformDetectionLoading} className="inline-flex shrink-0 items-center gap-1 rounded-lg bg-cyan-700 px-2.5 py-1.5 text-[11px] font-semibold text-white disabled:opacity-50">
                    {platformDetectionLoading ? <RotateCcw size={12} className="animate-spin" /> : <Activity size={12} />}
                    {language === 'zh' ? '自动识别' : 'Detect'}
                  </button>
                </div>
                <div className="space-y-2">
                  <PlatformProfileSelector
                    profiles={platformProfiles}
                    value={selectedPlatformProfileId}
                    language={language}
                    allowedVendor={deviceVendor}
                    requireVendor
                    disabled={platformProfilesLoading || platformBindingLoading}
                    title={language === 'zh' ? '选择同厂商的平台版本' : 'Select a platform version from the same vendor'}
                    onChange={(profile) => setSelectedPlatformProfileId(profile?.id || '')}
                  />
                  {deviceVendor && <p className="mt-1 text-[10px] text-cyan-800/70">{language === 'zh' ? `设备厂商：${platformVendorLabel(deviceVendor, language)}；只能选择同厂商平台。` : `Device vendor: ${platformVendorLabel(deviceVendor, language)}; only same-vendor platforms are available.`}</p>}
                  <div className="flex justify-end">
                    <button type="button" onClick={() => void bindPlatform()} disabled={platformBindingLoading || !selectedPlatformProfileId} className="rounded-lg border border-cyan-300 bg-white px-2.5 py-1.5 text-[11px] font-semibold text-cyan-800 disabled:opacity-50">{platformBindingLoading ? (language === 'zh' ? '保存中…' : 'Saving…') : (language === 'zh' ? '保存绑定' : 'Save binding')}</button>
                  </div>
                  {platformResult && <div className="text-[11px] text-cyan-900/80"><span className="font-semibold">{platformResult.status || '—'}</span>{identificationVersion ? <span className="ml-2">{language === 'zh' ? '版本' : 'Version'} {identificationVersion}</span> : null}{platformResult.commands?.length ? <span className="ml-2 text-cyan-700/70">{platformResult.commands.join(', ')}</span> : null}{platformResult.suggestions?.length ? <div className="mt-1 space-y-1">{platformResult.suggestions.slice(0, 3).map((item) => <button type="button" key={item.platform_profile_id || item.platform_code} onClick={() => item.platform_profile_id && setSelectedPlatformProfileId(item.platform_profile_id)} className="block w-full rounded-md px-1.5 py-1 text-left hover:bg-cyan-50">{item.name_zh || item.platform_code} <span className="text-cyan-700/60">{identificationVersion ? `${language === 'zh' ? '· 版本' : '· Version'} ${identificationVersion}` : `${language === 'zh' ? '· 匹配分' : '· Score'} ${Number(item.score || 0).toFixed(2)}`}</span></button>)}</div> : null}</div>}
                  {platformMessage && <div className="text-[11px] font-semibold text-emerald-700">{platformMessage}</div>}
                  {platformError && <div className="text-[11px] text-rose-700">{platformError}</div>}
                </div>
              </div>

              <div>
                <h4 className="mb-2 text-[10px] font-bold uppercase tracking-widest text-black/30">{t('hardwareInfo')}</h4>
                <div className="space-y-3">
                  <div className="flex justify-between text-sm"><span className="text-black/40">{language === 'zh' ? '硬件型号' : t('model')}</span><span className="font-medium">{viewingDevice.model || '—'}</span></div>
                  <div className="flex justify-between text-sm"><span className="text-black/40">{language === 'zh' ? '序列号' : t('serialNumber')}</span><span className="font-mono">{viewingDevice.sn || '—'}</span></div>
                  <div className="flex justify-between text-sm"><span className="text-black/40">{language === 'zh' ? '系统版本' : t('version')}</span><span className="font-medium">{viewingDevice.version || '—'}</span></div>
                  <div className="flex justify-between text-sm"><span className="text-black/40">{language === 'zh' ? '运行时间' : t('uptime')}</span><span className="font-medium">{formatUptime(viewingDevice.uptime, language)}</span></div>
                </div>
              </div>

              <div>
                <h4 className="mb-2 text-[10px] font-bold uppercase tracking-widest text-black/30">{language === 'zh' ? '硬件健康' : 'Hardware Health'}</h4>
                <div className="space-y-3">
                  <div className="flex justify-between text-sm"><span className="text-black/40">{language === 'zh' ? '设备温度' : 'Temperature'}</span><span className={`font-medium ${viewingDevice.temp == null ? 'text-black/30' : viewingDevice.temp > 50 ? 'text-orange-600' : 'text-emerald-600'}`}>{viewingDevice.temp != null ? `${viewingDevice.temp}°C` : (language === 'zh' ? '无数据' : 'N/A')}</span></div>
                  <div className="flex justify-between text-sm"><span className="text-black/40">{language === 'zh' ? '风扇状态' : 'Fan Status'}</span><span className={`text-[10px] font-bold ${viewingDevice.fan_status == null ? 'text-black/30' : isHardwareStatusNormal(viewingDevice.fan_status) ? 'text-emerald-600' : 'text-red-600'}`}>{viewingDevice.fan_status == null ? (language === 'zh' ? '无数据' : 'N/A') : isHardwareStatusNormal(viewingDevice.fan_status) ? (language === 'zh' ? '正常' : 'NORMAL') : (language === 'zh' ? '异常' : 'ABNORMAL')}</span></div>
                  <div className="flex justify-between text-sm"><span className="text-black/40">{language === 'zh' ? '电源状态' : 'PSU Status'}</span><span className={`text-[10px] font-bold ${viewingDevice.psu_status == null ? 'text-black/30' : isHardwareStatusNormal(viewingDevice.psu_status) ? 'text-emerald-600' : 'text-red-600'}`}>{viewingDevice.psu_status == null ? (language === 'zh' ? '无数据' : 'N/A') : isHardwareStatusNormal(viewingDevice.psu_status) ? (language === 'zh' ? '正常' : 'NORMAL') : (language === 'zh' ? '异常' : 'ABNORMAL')}</span></div>
                </div>
              </div>

              <div>
                <h4 className="mb-2 text-[10px] font-bold uppercase tracking-widest text-black/30">{language === 'zh' ? '健康原因' : 'Health Reasons'}</h4>
                <div className="space-y-2 rounded-2xl border border-black/5 bg-black/[0.01] p-4">
                  {Array.isArray(viewingDevice.health_reasons) && viewingDevice.health_reasons.length > 0 ? viewingDevice.health_reasons.slice(0, 6).map((reason, index) => (
                    <div key={`${reason}-${index}`} className="rounded-xl border border-black/5 bg-white px-3 py-2 text-sm text-black/60">{localizeHealthText(reason, language)}</div>
                  )) : (
                    <div className="rounded-xl border border-dashed border-black/10 bg-white px-3 py-4 text-sm text-black/40">
                      {language === 'zh' ? '当前没有需要升级处理的健康原因。' : 'There are no escalated health reasons right now.'}
                    </div>
                  )}
                </div>
              </div>

              <div className="rounded-2xl border border-cyan-100 bg-cyan-50/50 p-3">
                <h4 className="mb-2 text-[10px] font-bold uppercase tracking-widest text-cyan-900/60">{language === 'zh' ? 'SNMP 健康模板' : 'SNMP Health Template'}</h4>
                <div className="space-y-1.5 text-sm">
                  <div className="flex justify-between gap-3"><span className="text-cyan-900/50">{language === 'zh' ? '关联模板' : 'Profile'}</span><span className="max-w-[190px] truncate text-right font-medium text-cyan-950" title={snmpProfileName}>{snmpProfileName}</span></div>
                  <div className="flex justify-between gap-3"><span className="text-cyan-900/50">{language === 'zh' ? '来源' : 'Source'}</span><span className="text-right font-medium text-cyan-950">{language === 'zh' ? SNMP_PROFILE_SOURCE_ZH[snmpProfileSource] || snmpProfileSource : SNMP_PROFILE_SOURCE_EN[snmpProfileSource] || snmpProfileSource}</span></div>
                  <div className="flex justify-between gap-3"><span className="text-cyan-900/50">{language === 'zh' ? '模板 ID' : 'Template ID'}</span><span className="max-w-[190px] truncate text-right font-mono text-[11px] font-medium text-cyan-950" title={viewingDevice.snmp_metric_profile_id || ''}>{viewingDevice.snmp_metric_profile_id || '—'}</span></div>
                  <div className="flex justify-between gap-3"><span className="text-cyan-900/50">{language === 'zh' ? '状态' : 'Status'}</span><span className={`text-right font-semibold ${snmpProfileStatus === 'verified' ? 'text-emerald-700' : snmpProfileStatus === 'failed' ? 'text-red-600' : 'text-amber-700'}`}>{language === 'zh' ? SNMP_PROFILE_STATUS_ZH[snmpProfileStatus] || snmpProfileStatus : snmpProfileStatus}</span></div>
                  <div className="flex justify-between gap-3"><span className="text-cyan-900/50">{language === 'zh' ? '健康指标' : 'Health metrics'}</span><span className="max-w-[190px] truncate text-right font-medium text-cyan-950" title={snmpHealthMetrics || 'No template metrics'}>{snmpHealthMetrics || (language === 'zh' ? '未配置模板指标' : 'No template metrics')}</span></div>
                </div>
              </div>
            </div>

            <div className="space-y-4">
              <div>
                <h4 className="mb-2 text-[10px] font-bold uppercase tracking-widest text-black/30">{language === 'zh' ? '开放告警' : 'Open Alerts'}</h4>
                <div className="max-h-[520px] space-y-2 overflow-auto rounded-2xl border border-black/5 bg-black/[0.01] p-4">
                  {viewingDeviceAlerts.length > 0 ? viewingDeviceAlerts.map((alert) => {
                    const tone = String(alert.severity || '').toLowerCase() === 'critical' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700';
                    return (
                      <div key={alert.id} className="rounded-xl border border-black/5 bg-white p-3">
                        <div className="flex items-center justify-between gap-2">
                          <span className={`rounded-full px-2 py-1 text-[10px] font-bold ${tone}`}>{formatStatusLabel(alert.severity, language)}</span>
                          <span className="text-[11px] text-black/40">{new Date(alert.created_at).toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US', { hour12: false })}</span>
                        </div>
                        <p className="mt-2 text-sm font-semibold text-[#0b2340]">{localizeHealthText(alert.title, language)}</p>
                        <p className="mt-1 text-[11px] text-black/55">{localizeHealthText(alert.message, language)}</p>
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
                            <span className={`rounded-full px-2 py-1 text-[10px] font-bold ${getHealthToneClass(point.health_status)}`}>{formatStatusLabel(point.health_status, language)}</span>
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
                                <div key={reason} className="rounded-lg border border-red-100 bg-white px-3 py-2 text-xs text-red-700">{localizeHealthText(reason, language)}</div>
                              )) : (
                                <div className="rounded-lg border border-dashed border-red-200 bg-white/80 px-3 py-2 text-xs text-red-400">{language === 'zh' ? '最近一次采样没有新增风险原因。' : 'No new risk reasons appeared in the latest sample.'}</div>
                              )}
                            </div>
                          </div>
                          <div className="rounded-xl border border-emerald-100 bg-emerald-50/50 p-3">
                            <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-emerald-700">{language === 'zh' ? '已缓解原因' : 'Cleared reasons'}</p>
                            <div className="mt-2 space-y-2">
                              {deviceTrendInsights.removedReasons.length > 0 ? deviceTrendInsights.removedReasons.slice(0, 4).map((reason) => (
                                <div key={reason} className="rounded-lg border border-emerald-100 bg-white px-3 py-2 text-xs text-emerald-700">{localizeHealthText(reason, language)}</div>
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

          {viewingDevice.interface_data && viewingDevice.interface_data.length > 0 && (
            <div className="px-5 pb-5 sm:px-6 sm:pb-6 xl:px-8 xl:pb-6">
              <h4 className="mb-3 text-[10px] font-bold uppercase tracking-widest text-black/30">{language === 'zh' ? '接口监控' : 'Interface Monitoring'} ({viewingDevice.interface_data.length})</h4>
              <div className="max-h-60 overflow-auto rounded-xl border border-black/5">
                <table className="nx-data-table nx-data-table--compact">
                  <thead className="sticky top-0 bg-black/[0.02]">
                    <tr>
                      <th className="px-3 py-2 text-left text-[10px] font-bold uppercase text-black/40">{language === 'zh' ? '接口' : 'Interface'}</th>
                      <th className="px-3 py-2 text-left text-[10px] font-bold uppercase text-black/40">{language === 'zh' ? '状态' : 'Status'}</th>
                      <th className="px-3 py-2 text-right text-[10px] font-bold uppercase text-black/40">{language === 'zh' ? '速率' : 'Speed'}</th>
                      <th className="px-3 py-2 text-right text-[10px] font-bold uppercase text-black/40">IN</th>
                      <th className="px-3 py-2 text-right text-[10px] font-bold uppercase text-black/40">OUT</th>
                      <th className="px-3 py-2 text-right text-[10px] font-bold uppercase text-black/40">{language === 'zh' ? '带宽' : 'BW%'}</th>
                      <th className="px-3 py-2 text-right text-[10px] font-bold uppercase text-black/40">{language === 'zh' ? '通用错误' : 'Generic Err'}</th>
                      <th className="px-3 py-2 text-right text-[10px] font-bold uppercase text-black/40">CRC/FCS</th>
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
                      const fcsErrors = Number(intf.fcs_errors || 0);
                      const maxBw = (intf.bw_in_pct != null || intf.bw_out_pct != null) ? Math.max(intf.bw_in_pct || 0, intf.bw_out_pct || 0) : null;

                      return (
                        <tr key={index} className="hover:bg-black/[0.01]">
                          <td className="px-3 py-1.5 font-mono text-[11px]">{intf.name}</td>
                          <td className="px-3 py-1.5"><span className={`inline-flex items-center gap-1 text-[10px] font-bold ${intf.status === 'up' ? 'text-emerald-600' : 'text-red-500'}`}><span className={`h-1.5 w-1.5 rounded-full ${intf.status === 'up' ? 'bg-emerald-500' : 'bg-red-500'}`} />{formatStatusLabel(intf.status, language)}</span></td>
                          <td className="px-3 py-1.5 text-right text-black/60">{intf.speed_mbps > 0 ? `${intf.speed_mbps >= 1000 ? `${intf.speed_mbps / 1000}G` : `${intf.speed_mbps}M`}` : '-'}</td>
                          <td className="px-3 py-1.5 text-right font-mono text-[10px]"><div className="text-blue-600">{fmtRate(intf.in_bps)}</div><div className="text-black/30">{fmtBytes(intf.in_octets || 0)}</div></td>
                          <td className="px-3 py-1.5 text-right font-mono text-[10px]"><div className="text-orange-600">{fmtRate(intf.out_bps)}</div><div className="text-black/30">{fmtBytes(intf.out_octets || 0)}</div></td>
                          <td className="px-3 py-1.5 text-right font-mono text-[10px]">{maxBw != null ? <span className={maxBw > 80 ? 'text-red-600' : maxBw > 50 ? 'text-orange-600' : 'text-black/50'}>{maxBw.toFixed(1)}%</span> : <span className="text-black/20">-</span>}</td>
                          <td className="px-3 py-1.5 text-right font-mono text-[10px]"><span className={totalErr > 0 ? 'font-bold text-red-600' : 'text-black/30'}>{totalErr}</span></td>
                          <td className="px-3 py-1.5 text-right font-mono text-[10px]" title={intf.fcs_source || 'EtherLike-MIB'}><span className={fcsErrors > 0 ? 'font-bold text-red-600' : 'text-black/30'}>{fcsErrors}</span></td>
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
              <button onClick={() => onTestConnection(viewingDevice, 'quick')} disabled={isTestingConnection} className="flex items-center gap-2 rounded-xl bg-blue-50 px-6 py-2 text-sm font-medium text-blue-600 transition-all hover:bg-blue-100 disabled:opacity-50"><Activity size={16} />{isTestingConnection ? (language === 'zh' ? '检测中…' : 'Testing...') : (language === 'zh' ? '快速连通性' : 'Reachability Check')}</button>
              <button onClick={() => onTestConnection(viewingDevice, 'deep')} disabled={isTestingConnection} className="flex items-center gap-2 rounded-xl bg-violet-50 px-6 py-2 text-sm font-medium text-violet-700 transition-all hover:bg-violet-100 disabled:opacity-50"><ShieldCheck size={16} />{isTestingConnection ? (language === 'zh' ? '检测中…' : 'Testing...') : (language === 'zh' ? 'SSH 登录校验' : 'SSH Login Check')}</button>
              <button onClick={() => onSnmpTest(viewingDevice.id)} disabled={snmpTestingId === viewingDevice.id} className="flex items-center gap-2 rounded-xl bg-emerald-50 px-6 py-2 text-sm font-medium text-emerald-600 transition-all hover:bg-emerald-100 disabled:opacity-50"><Activity size={16} />{snmpTestingId === viewingDevice.id ? (language === 'zh' ? '检测中…' : 'Testing...') : (language === 'zh' ? 'SNMP 检测' : 'SNMP Test')}</button>
              <button onClick={() => onSnmpSyncNow(viewingDevice.id)} disabled={snmpSyncingId === viewingDevice.id} className="flex items-center gap-2 rounded-xl bg-cyan-50 px-6 py-2 text-sm font-medium text-cyan-700 transition-all hover:bg-cyan-100 disabled:opacity-50"><RotateCcw size={16} className={snmpSyncingId === viewingDevice.id ? 'animate-spin' : ''} />{snmpSyncingId === viewingDevice.id ? (language === 'zh' ? '同步中...' : 'Syncing...') : (language === 'zh' ? '立即同步SNMP' : 'SNMP Sync Now')}</button>
              <button onClick={() => onGoToAutomation(viewingDevice)} className="flex items-center gap-2 rounded-xl border border-black/10 px-6 py-2 text-sm font-medium text-black transition-all hover:bg-black/5"><Zap size={16} />{language === 'zh' ? '进入自动化' : 'Go to Automation'}</button>
            </div>
            <div className="flex justify-end"><button onClick={onClose} className="rounded-xl bg-black px-8 py-2 text-sm font-medium text-white shadow-lg shadow-black/20 transition-all hover:bg-black/80">{t('close')}</button></div>
          </div>
        </div>
      </motion.div>
    </div>
  );
};

export default DeviceDetailModal;
