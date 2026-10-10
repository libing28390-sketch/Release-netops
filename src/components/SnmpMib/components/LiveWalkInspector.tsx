import React, { useEffect, useMemo, useState } from 'react';
import { Activity, AlertTriangle, CheckCircle2, Copy, Play, RefreshCw, Server, ShieldCheck } from 'lucide-react';
import { ApiError, apiRequest } from '../../../api/http';
import HardwareDiagnosticSummary from './HardwareDiagnosticSummary';
import type { SnmpHardwareDiscoveryTestResult } from './hardwareDiagnosticTypes';

export type { SnmpHardwareDiscoveryTestResult } from './hardwareDiagnosticTypes';
export type InspectorTab = 'validate' | 'snmpwalk' | 'system';

export interface CandidateDevice {
  device_id: string;
  hostname: string;
  ip_address?: string;
  status?: string;
  vendor?: string;
  platform?: string;
  model?: string;
  version?: string;
}

interface LibreNMSRuleSensor {
  source_type: 'librenms_rule' | 'librenms_adapter' | string;
  source_id: string;
  component_class: string;
  measurement_type: string;
  sensor_name: string;
  group_name: string;
  oid: string;
  index: number[] | string[];
  value: number | null;
  raw_value: string | null;
  unit: string;
  quality: string;
  source_path: string;
  source_commit: string;
}

interface LibreNMSRuleProbeResult {
  status: string;
  message: string;
  host: string;
  version: string;
  matched_device_id: string;
  matched_hostname: string;
  identity: Record<string, unknown>;
  rule: {
    id: string;
    os_key: string;
    vendor: string;
    platform: string;
    source_path: string;
    source_commit: string;
  } | null;
  rule_source_path: string;
  rule_source_commit: string;
  category_results: Array<{
    source_type?: string;
    component_class?: string;
    status?: string;
    reason_code?: string;
    reason?: string;
  }>;
  sensor_count: number;
  sensors: LibreNMSRuleSensor[];
}

interface SnmpSystemInfo {
  sys_name?: string | number | null;
  sys_descr?: string | number | null;
  sys_object_id?: string | number | null;
  sys_uptime?: string | number | null;
  uptime?: string | number | null;
  uptime_seconds?: number | null;
  sys_location?: string | number | null;
  sys_contact?: string | number | null;
}

interface SnmpLldpNeighbor {
  local_interface?: string | number | null;
  neighbor_name?: string | number | null;
  neighbor_interface?: string | number | null;
  mgmt_address?: string | number | null;
  neighbor_platform?: string | number | null;
  system_description?: string | number | null;
}

interface SnmpSystemLldpTestResult {
  device_id: string;
  hostname?: string | null;
  host?: string | null;
  version?: string | null;
  status: string;
  system_info: SnmpSystemInfo;
  lldp: {
    status: string;
    neighbors: SnmpLldpNeighbor[];
    message?: string | null;
  };
}

const formatValue = (value: unknown): string => {
  if (typeof value !== 'string' && typeof value !== 'number') return '—';
  const formatted = String(value).trim();
  return formatted || '—';
};

const getStatusTone = (status: string): 'success' | 'warning' | 'error' | 'neutral' => {
  const normalized = status.trim().toLowerCase();
  if (normalized.includes('partial')) return 'warning';
  if (['error', 'fail', 'denied', 'unsupported', 'unavailable'].some(value => normalized.includes(value))) return 'error';
  if (['success', 'ok', 'available', 'complete'].some(value => normalized.includes(value))) return 'success';
  return 'neutral';
};

const statusToneClass = (tone: ReturnType<typeof getStatusTone>): string => {
  if (tone === 'success') return 'border-emerald-500/20 bg-emerald-500/[.07] text-emerald-700 dark:text-emerald-300';
  if (tone === 'warning') return 'border-amber-500/25 bg-amber-500/[.08] text-amber-800 dark:text-amber-200';
  if (tone === 'error') return 'border-rose-500/25 bg-rose-500/[.07] text-rose-700 dark:text-rose-300';
  return 'border-black/10 bg-black/[.025] text-black/60 dark:border-white/10 dark:bg-white/[.035] dark:text-white/60';
};

const getStatusLabel = (status: string, zh: boolean): string => {
  const normalized = status.trim().toLowerCase();
  if (['success', 'ok', 'complete'].includes(normalized)) return zh ? '正常' : 'Complete';
  if (normalized === 'partial') return zh ? '部分数据' : 'Partial data';
  if (['failed', 'error', 'denied'].includes(normalized)) return zh ? '读取失败' : 'Failed';
  if (['unsupported', 'unavailable'].includes(normalized)) return zh ? '暂不可用' : 'Unavailable';
  return status ? (zh ? '状态未知（' + status + '）' : 'Unknown (' + status + ')') : (zh ? '未知' : 'Unknown');
};

const getSystemStatusMessage = (status: string, zh: boolean): string => {
  const normalized = status.trim().toLowerCase();
  if (['success', 'ok', 'complete'].includes(normalized)) {
    return zh ? '设备系统信息读取正常。' : 'Device system information was read successfully.';
  }
  if (normalized === 'partial') {
    return zh ? '已读取到部分系统信息；可展开详情查看完整字段。' : 'Some system fields were read; expand details to review all fields.';
  }
  if (['unsupported', 'unavailable'].includes(normalized)) {
    return zh ? '没有读取到系统信息，请检查 SNMP 配置和设备响应。' : 'No system information was returned; check the SNMP profile and device response.';
  }
  if (normalized.includes('failed') || normalized.includes('error') || normalized.includes('denied')) {
    return zh ? '系统信息读取失败，请展开诊断详情查看原因。' : 'System information could not be read; expand diagnostic details for the reason.';
  }
  return zh ? '系统信息状态未知，请查看诊断详情。' : 'System information status is unknown; review diagnostic details.';
};

const getLldpStatusMessage = (status: string, neighborCount: number, zh: boolean): string => {
  const normalized = status.trim().toLowerCase();
  if (normalized === 'partial') {
    return zh
      ? '已读取到 ' + neighborCount + ' 台邻居，但部分 LLDP 信息未能完整返回。'
      : neighborCount + ' neighbors were found, but some LLDP fields did not return completely.';
  }
  if (['success', 'ok', 'complete'].includes(normalized)) {
    return neighborCount > 0
      ? (zh ? '已读取到 ' + neighborCount + ' 台直连邻居。' : neighborCount + ' direct neighbors were found.')
      : (zh ? '设备响应正常，暂未发现开启 LLDP 的直连邻居。' : 'The device responded, but no direct LLDP neighbors were found.');
  }
  if (['unsupported', 'unavailable'].includes(normalized)) {
    return zh
      ? '没有获得 LLDP 邻居数据；设备可能未启用 LLDP，或 SNMP 尚不可用。'
      : 'No LLDP neighbor data was returned; LLDP may be disabled or SNMP may be unavailable.';
  }
  if (normalized.includes('failed') || normalized.includes('error') || normalized.includes('denied')) {
    return zh
      ? 'LLDP 邻居读取失败，请展开诊断详情查看原因。'
      : 'LLDP neighbors could not be read; expand diagnostic details for the reason.';
  }
  return zh ? 'LLDP 状态未知，请查看诊断详情。' : 'LLDP status is unknown; review diagnostic details.';
};

const formatUptimeDisplay = (secondsValue: unknown, fallbackValue: unknown, zh: boolean): string => {
  if (typeof secondsValue !== 'number' || !Number.isFinite(secondsValue) || secondsValue < 0) {
    return formatValue(fallbackValue);
  }

  let remaining = Math.floor(secondsValue);
  const days = Math.floor(remaining / 86400);
  remaining %= 86400;
  const hours = Math.floor(remaining / 3600);
  remaining %= 3600;
  const minutes = Math.floor(remaining / 60);
  const seconds = remaining % 60;
  const parts: string[] = [];
  if (days > 0) parts.push(zh ? days + '天' : days + 'd');
  if (hours > 0) parts.push(zh ? hours + '小时' : hours + 'h');
  if (minutes > 0) parts.push(zh ? minutes + '分' : minutes + 'm');
  if (seconds > 0 || parts.length === 0) parts.push(zh ? seconds + '秒' : seconds + 's');
  return parts.join(zh ? '' : ' ');
};


interface LiveWalkInspectorProps {
  zh: boolean;
  initialIp?: string;
  selectedDevice?: CandidateDevice;
  candidateDevices?: CandidateDevice[];
  showCandidateSelector?: boolean;
  showHardwareValidationTab?: boolean;
  showSystemInfoTab?: boolean;
  initialTab?: InspectorTab;
  saving?: boolean;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
}

const LiveWalkInspector: React.FC<LiveWalkInspectorProps> = ({
  zh,
  initialIp = '',
  selectedDevice,
  candidateDevices = [],
  showCandidateSelector = true,
  showHardwareValidationTab = true,
  showSystemInfoTab = false,
  initialTab = 'snmpwalk',
  saving = false,
  showToast,
}) => {
  const [activeTab, setActiveTab] = useState<InspectorTab>(initialTab);
  const [candidateId, setCandidateId] = useState(selectedDevice?.device_id || '');
  const [systemLoading, setSystemLoading] = useState(false);
  const [systemError, setSystemError] = useState<{ message: string; permissionDenied: boolean } | null>(null);
  const [systemResult, setSystemResult] = useState<SnmpSystemLldpTestResult | null>(null);
  const [probeLoading, setProbeLoading] = useState(false);
  const [snapshotLoading, setSnapshotLoading] = useState(false);
  const [probeError, setProbeError] = useState('');
  const [snapshotError, setSnapshotError] = useState<{ message: string; permissionDenied: boolean } | null>(null);
  const [probeResult, setProbeResult] = useState<LibreNMSRuleProbeResult | null>(null);
  const [snapshotResult, setSnapshotResult] = useState<SnmpHardwareDiscoveryTestResult | null>(null);

  const target = useMemo(
    () => selectedDevice || candidateDevices.find(item => item.device_id === candidateId) || null,
    [candidateDevices, candidateId, selectedDevice],
  );

  useEffect(() => {
    setCandidateId(selectedDevice?.device_id || '');
    setSystemResult(null);
    setSystemError(null);
    setProbeResult(null);
    setSnapshotResult(null);
    setProbeError('');
    setSnapshotError(null);
  }, [selectedDevice?.device_id, selectedDevice?.ip_address]);

  const resolveDeviceId = async (): Promise<string> => {
    if (target?.device_id) return target.device_id;
    if (candidateId) return candidateId;
    if (!initialIp.trim()) throw new Error(zh ? '请先选择 CMDB 设备' : 'Select a managed device first');
    const response = await apiRequest<{ success: boolean; data: { device_id?: string; hostname?: string; ip?: string } }>(
      `/api/platform-registry/snmp-walk-target?ip=${encodeURIComponent(initialIp.trim())}`,
    );
    if (!response.data.device_id) throw new Error(zh ? '该 IP 未匹配到唯一 CMDB 设备' : 'The IP did not resolve to one managed device');
    return response.data.device_id;
  };

  const runSystemLldpTest = async () => {
    setSystemLoading(true);
    setSystemError(null);
    setSystemResult(null);
    try {
      const deviceId = await resolveDeviceId();
      const response = await apiRequest<{ success: boolean; data: SnmpSystemLldpTestResult }>(
        '/api/platform-registry/snmp-system-lldp-test',
        { method: 'POST', body: JSON.stringify({ device_id: deviceId }) },
      );
      setSystemResult(response.data);
      const tone = getStatusTone(response.data.status);
      showToast(
        tone === 'success'
          ? (zh ? '系统与 LLDP 查询完成' : 'System and LLDP query complete')
          : (zh ? `系统与 LLDP 查询状态：${response.data.status}` : `System and LLDP status: ${response.data.status}`),
        tone === 'success' ? 'success' : tone === 'error' ? 'error' : 'info',
      );
    } catch (error) {
      const permissionDenied = error instanceof ApiError && (error.status === 401 || error.status === 403);
      const message = permissionDenied
        ? (zh ? '没有权限执行 SNMP 系统与 LLDP 诊断。' : 'You do not have permission to run SNMP system and LLDP diagnostics.')
        : error instanceof Error
          ? error.message
          : (zh ? '系统与 LLDP 查询失败。' : 'System and LLDP query failed.');
      setSystemError({ message, permissionDenied });
      showToast(message, 'error');
    } finally {
      setSystemLoading(false);
    }
  };

  const runLibreNMSRuleProbe = async () => {
    setProbeLoading(true);
    setProbeError('');
    setProbeResult(null);
    try {
      const deviceId = await resolveDeviceId();
      const response = await apiRequest<{ success: boolean; data: LibreNMSRuleProbeResult }>(
        '/api/platform-registry/snmp-librenms-rule-test',
        { method: 'POST', body: JSON.stringify({ device_id: deviceId }) },
      );
      setProbeResult(response.data);
      showToast(
        response.data.rule
          ? `${zh ? 'LibreNMS 规则探测完成' : 'LibreNMS rule probe complete'} · ${response.data.rule.os_key} · ${response.data.sensor_count}`
          : response.data.message,
        response.data.rule ? 'success' : 'info',
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : zh ? 'LibreNMS 规则探测失败' : 'LibreNMS rule probe failed';
      setProbeError(message);
      showToast(message, 'error');
    } finally {
      setProbeLoading(false);
    }
  };

  const readSavedHardwareResults = async () => {
    setSnapshotLoading(true);
    setSnapshotError(null);
    setSnapshotResult(null);
    try {
      const deviceId = await resolveDeviceId();
      const response = await apiRequest<{ success: boolean; data: SnmpHardwareDiscoveryTestResult }>(
        '/api/platform-registry/snmp-hardware-discovery-test',
        { method: 'POST', body: JSON.stringify({ device_id: deviceId }) },
      );
      setSnapshotResult(response.data);
    } catch (error) {
      const permissionDenied = error instanceof ApiError && (error.status === 401 || error.status === 403);
      const message = error instanceof Error ? error.message : zh ? '读取硬件结果失败' : 'Failed to read hardware results';
      setSnapshotError({ message, permissionDenied });
    } finally {
      setSnapshotLoading(false);
    }
  };

  const copyProbeResult = async () => {
    if (!probeResult) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(probeResult, null, 2));
      showToast(zh ? '已复制 LibreNMS 规则诊断 JSON' : 'LibreNMS rule diagnostic JSON copied', 'success');
    } catch {
      showToast(zh ? '复制失败' : 'Copy failed', 'error');
    }
  };

  const tabClass = (tab: InspectorTab) => `inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-[11px] font-semibold ${activeTab === tab ? 'bg-white text-[#007391] shadow-sm dark:bg-white/[.15] dark:text-[#00c2e8]' : 'text-black/50 hover:text-black/80 dark:text-white/50 dark:hover:text-white/80'}`;

  return (
    <section className="mb-4 rounded-xl border border-[#00bceb]/25 bg-gradient-to-br from-[#00bceb]/[.055] to-[var(--card-bg)] p-4 shadow-sm dark:from-[#00bceb]/[.08] dark:to-[var(--card-bg)] md:p-5">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-black/6 pb-3.5 dark:border-white/8">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-black/80 dark:text-white/85">
            <Activity size={15} className="text-[#008aad] dark:text-[#00bceb]" />
            {zh ? 'SNMP 诊断' : 'SNMP Diagnostics'}
          </div>
          <div className="inline-flex flex-wrap rounded-lg border border-black/8 bg-black/[.03] p-0.5 dark:border-white/10 dark:bg-white/[.04]">
            {showSystemInfoTab && (
              <button type="button" className={tabClass('system')} onClick={() => setActiveTab('system')}>
                <Server size={12} />{zh ? '系统与 LLDP' : 'System & LLDP'}
              </button>
            )}
            <button type="button" className={tabClass('snmpwalk')} onClick={() => setActiveTab('snmpwalk')}>
              <Play size={12} />{zh ? '硬件规则诊断' : 'Hardware rule diagnostics'}
            </button>
            {showHardwareValidationTab && (
              <button type="button" className={tabClass('validate')} onClick={() => setActiveTab('validate')}>
                <CheckCircle2 size={12} />{zh ? '已采集硬件样本' : 'Stored hardware samples'}
              </button>
            )}
          </div>
        </div>
        {showCandidateSelector && !selectedDevice && candidateDevices.length > 0 && (
          <select
            aria-label={zh ? '选择诊断设备' : 'Choose diagnostic device'}
            value={candidateId}
            onChange={event => { setCandidateId(event.target.value); setProbeResult(null); setSnapshotResult(null); }}
            className="max-w-full rounded-md border border-black/10 bg-transparent px-2.5 py-1.5 text-xs dark:border-white/10"
          >
            <option value="">{zh ? '选择设备' : 'Select device'}</option>
            {candidateDevices.map(item => <option key={item.device_id} value={item.device_id}>{item.hostname} · {item.ip_address || '—'}</option>)}
          </select>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-black/6 bg-white/50 px-3 py-2 dark:border-white/8 dark:bg-white/[.025]">
        <div className="min-w-0 text-[10px] text-black/55 dark:text-white/55">
          <ShieldCheck size={12} className="mr-1 inline text-emerald-600" />
          {target ? `${target.hostname} · ${target.ip_address || initialIp || '—'}` : initialIp || (zh ? '请先选择设备' : 'Select a device first')}
          <span className="ml-2">{zh ? '只读查询；凭据由服务端读取。' : 'Read-only queries; credentials are resolved server-side.'}</span>
        </div>
        {activeTab === 'system' ? (
          <button
            type="button"
            onClick={() => void runSystemLldpTest()}
            disabled={systemLoading || saving || (!target && !candidateId && !initialIp)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[#00a9ce] px-3.5 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-[#008fb1] disabled:opacity-45"
          >
            {systemLoading ? <RefreshCw size={13} className="animate-spin" /> : <Activity size={13} />}
            {systemLoading ? (zh ? '查询系统与 LLDP…' : 'Querying system & LLDP…') : (zh ? '查询系统与 LLDP' : 'Query system & LLDP')}
          </button>
        ) : activeTab === 'snmpwalk' ? (
          <button
            type="button"
            onClick={() => void runLibreNMSRuleProbe()}
            disabled={probeLoading || saving || (!target && !candidateId && !initialIp)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[#00a9ce] px-3.5 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-[#008fb1] disabled:opacity-45"
          >
            {probeLoading ? <RefreshCw size={13} className="animate-spin" /> : <Activity size={13} />}
            {probeLoading ? (zh ? '硬件规则诊断中…' : 'Running hardware rule diagnostics…') : (zh ? '运行硬件规则诊断' : 'Run hardware rule diagnostics')}
          </button>
        ) : (
          <button
            type="button"
            onClick={() => void readSavedHardwareResults()}
            disabled={snapshotLoading || saving || (!target && !candidateId && !initialIp)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-black/10 bg-white/70 px-3 py-1.5 text-xs font-semibold text-black/70 hover:border-[#00bceb]/40 dark:border-white/10 dark:bg-white/[.04] dark:text-white/75 disabled:opacity-45"
          >
            {snapshotLoading ? <RefreshCw size={13} className="animate-spin" /> : <Server size={13} />}
            {snapshotLoading ? (zh ? '读取中…' : 'Reading…') : (zh ? '读取最新已保存样本' : 'Read latest saved samples')}
          </button>
        )}
      </div>

      {activeTab === 'system' && showSystemInfoTab && (
        <div className="mt-3 space-y-3">
          {systemLoading && (
            <div role="status" aria-live="polite" className="flex items-center justify-center gap-2 rounded-lg border border-sky-500/15 bg-sky-500/[.04] px-3 py-8 text-xs text-sky-800 dark:text-sky-200">
              <RefreshCw size={14} className="animate-spin" />
              {zh ? '正在读取设备系统信息和 LLDP 邻居…' : 'Reading device system information and LLDP neighbors…'}
            </div>
          )}

          {systemError && (
            <div role="alert" className="flex items-start gap-2 rounded-lg border border-rose-500/20 bg-rose-500/[.06] px-3 py-3 text-xs text-rose-700 dark:text-rose-300">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              <div>
                <div className="font-semibold">{systemError.permissionDenied ? (zh ? '权限不足' : 'Permission denied') : (zh ? '查询失败' : 'Query failed')}</div>
                <div className="mt-0.5 break-words">{systemError.message}</div>
              </div>
            </div>
          )}

          {systemResult && (() => {
            const systemTone = getStatusTone(systemResult.status);
            const lldpTone = getStatusTone(systemResult.lldp.status);
            const neighbors = systemResult.lldp.neighbors || [];
            const info = systemResult.system_info || {};
            const uptimeFallback = formatValue(info.uptime) !== '—' ? info.uptime : info.sys_uptime;
            const uptimeDisplay = formatUptimeDisplay(info.uptime_seconds, uptimeFallback, zh);
            const deviceName = formatValue(systemResult.hostname || info.sys_name || target?.hostname);
            const deviceAddress = formatValue(systemResult.host || target?.ip_address || initialIp);
            const systemDescription = formatValue(info.sys_descr);
            const hasSystemInfo = [info.sys_name, info.sys_descr, uptimeDisplay, info.sys_location, info.sys_object_id, info.sys_contact]
              .some(value => formatValue(value) !== '—');
            const hasLldpMessage = Boolean(String(systemResult.lldp.message || '').trim());

            return (
              <div className="space-y-3">
                <section className="rounded-xl border border-[#00bceb]/20 bg-gradient-to-r from-sky-50/80 to-white p-3 dark:from-sky-950/25 dark:to-slate-900/50">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-[10px] font-medium text-black/45 dark:text-white/45">{zh ? '诊断结果' : 'Diagnostic result'}</p>
                      <h3 className="mt-0.5 truncate text-sm font-semibold text-black/85 dark:text-white/90">{deviceName}</h3>
                      <p className="mt-0.5 text-[10px] text-black/55 dark:text-white/55">
                        {deviceAddress}{systemResult.version ? ' · SNMP ' + systemResult.version : ''}
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className={'rounded-full border px-2.5 py-1 text-[10px] font-semibold ' + statusToneClass(systemTone)} title={systemResult.status}>
                        {zh ? '整体状态：' : 'Overall: '}{getStatusLabel(systemResult.status, zh)}
                      </span>
                      <span className="rounded-full border border-[#00bceb]/20 bg-[#00bceb]/[.06] px-2.5 py-1 text-[10px] font-semibold text-[#007391] dark:text-[#00c2e8]">
                        {zh ? '邻居 ' : 'Neighbors '}{neighbors.length}
                      </span>
                    </div>
                  </div>
                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    <div className="rounded-lg border border-black/6 bg-white/70 px-3 py-2 dark:border-white/8 dark:bg-black/10">
                      <div className="text-[10px] font-semibold text-black/70 dark:text-white/75">{zh ? '系统信息' : 'System information'} · {getStatusLabel(systemResult.status, zh)}</div>
                      <p className="mt-0.5 text-[11px] leading-5 text-black/55 dark:text-white/55">{getSystemStatusMessage(systemResult.status, zh)}</p>
                    </div>
                    <div className="rounded-lg border border-black/6 bg-white/70 px-3 py-2 dark:border-white/8 dark:bg-black/10">
                      <div className="text-[10px] font-semibold text-black/70 dark:text-white/75">{zh ? 'LLDP 邻居' : 'LLDP neighbors'} · {getStatusLabel(systemResult.lldp.status, zh)}</div>
                      <p className="mt-0.5 text-[11px] leading-5 text-black/55 dark:text-white/55">{getLldpStatusMessage(systemResult.lldp.status, neighbors.length, zh)}</p>
                    </div>
                  </div>
                  {hasLldpMessage && (
                    <details className="mt-2 rounded-md border border-black/8 bg-white/55 px-2.5 py-2 text-[10px] dark:border-white/10 dark:bg-white/[.025]">
                      <summary className="cursor-pointer font-medium text-black/60 hover:text-black/80 dark:text-white/60 dark:hover:text-white/80">{zh ? '查看 SNMP 诊断详情' : 'View SNMP diagnostic details'}</summary>
                      <p className="mt-2 break-words text-black/50 dark:text-white/50">{systemResult.lldp.message}</p>
                      <p className="mt-1 text-black/40 dark:text-white/40">{zh ? '原始状态：' : 'Raw status: '}{systemResult.status} / {systemResult.lldp.status}</p>
                    </details>
                  )}
                </section>

                <section className="rounded-lg border border-black/8 bg-white/65 p-3 dark:border-white/10 dark:bg-white/[.035]">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <h3 className="text-xs font-semibold text-black/80 dark:text-white/85">{zh ? '设备信息' : 'Device information'}</h3>
                      <p className="mt-0.5 text-[10px] text-black/45 dark:text-white/45">{zh ? '常用字段优先显示，完整 SNMP 字段按需展开。' : 'Common fields are shown first; expand to review all SNMP fields.'}</p>
                    </div>
                    <span className={'rounded-full border px-2.5 py-1 text-[10px] font-medium ' + statusToneClass(systemTone)} title={systemResult.status}>
                      {getStatusLabel(systemResult.status, zh)}
                    </span>
                  </div>
                  {hasSystemInfo ? (
                    <>
                      <dl className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                        <div className="min-w-0 rounded-md border border-black/6 bg-black/[.02] px-2.5 py-2 dark:border-white/8 dark:bg-white/[.025]">
                          <dt className="text-[10px] text-black/45 dark:text-white/45">{zh ? '系统名称' : 'System name'}</dt>
                          <dd className="mt-1 break-words text-xs font-medium text-black/80 dark:text-white/80">{formatValue(info.sys_name)}</dd>
                        </div>
                        <div className="min-w-0 rounded-md border border-black/6 bg-black/[.02] px-2.5 py-2 dark:border-white/8 dark:bg-white/[.025]">
                          <dt className="text-[10px] text-black/45 dark:text-white/45">{zh ? '运行时间' : 'Uptime'}</dt>
                          <dd className="mt-1 break-words text-xs text-black/80 dark:text-white/80">{uptimeDisplay}</dd>
                        </div>
                        <div className="min-w-0 rounded-md border border-black/6 bg-black/[.02] px-2.5 py-2 dark:border-white/8 dark:bg-white/[.025]">
                          <dt className="text-[10px] text-black/45 dark:text-white/45">{zh ? '位置' : 'Location'}</dt>
                          <dd className="mt-1 break-words text-xs text-black/80 dark:text-white/80">{formatValue(info.sys_location)}</dd>
                        </div>
                        <div className="min-w-0 rounded-md border border-black/6 bg-black/[.02] px-2.5 py-2 dark:border-white/8 dark:bg-white/[.025] sm:col-span-2 lg:col-span-1">
                          <dt className="text-[10px] text-black/45 dark:text-white/45">{zh ? '设备描述' : 'Device description'}</dt>
                          <dd className="mt-1 line-clamp-2 break-words text-xs text-black/80 dark:text-white/80" title={systemDescription}>{systemDescription}</dd>
                        </div>
                      </dl>
                      <details className="mt-2 rounded-md border border-black/8 px-2.5 py-2 text-[10px] dark:border-white/10">
                        <summary className="cursor-pointer font-medium text-black/55 hover:text-black/80 dark:text-white/55 dark:hover:text-white/80">{zh ? '展开完整系统字段' : 'Expand complete system fields'}</summary>
                        <dl className="mt-2 grid gap-2 sm:grid-cols-2">
                          <div className="rounded-md bg-black/[.025] px-2.5 py-2 dark:bg-white/[.035]">
                            <dt className="text-[10px] text-black/45 dark:text-white/45">{zh ? '完整系统描述' : 'Full system description'}</dt>
                            <dd className="mt-1 whitespace-pre-wrap break-words text-xs text-black/75 dark:text-white/75">{systemDescription}</dd>
                          </div>
                          <div className="rounded-md bg-black/[.025] px-2.5 py-2 dark:bg-white/[.035]">
                            <dt className="text-[10px] text-black/45 dark:text-white/45">{zh ? '系统对象 OID' : 'System object OID'}</dt>
                            <dd className="mt-1 break-all font-mono text-xs text-black/75 dark:text-white/75">{formatValue(info.sys_object_id)}</dd>
                          </div>
                          <div className="rounded-md bg-black/[.025] px-2.5 py-2 dark:bg-white/[.035]">
                            <dt className="text-[10px] text-black/45 dark:text-white/45">{zh ? '联系人' : 'Contact'}</dt>
                            <dd className="mt-1 break-words text-xs text-black/75 dark:text-white/75">{formatValue(info.sys_contact)}</dd>
                          </div>
                          <div className="rounded-md bg-black/[.025] px-2.5 py-2 dark:bg-white/[.035]">
                            <dt className="text-[10px] text-black/45 dark:text-white/45">{zh ? '统一格式运行时间' : 'Formatted uptime'}</dt>
                            <dd className="mt-1 break-words text-xs text-black/75 dark:text-white/75">{uptimeDisplay}</dd>
                            {formatValue(info.sys_uptime) !== '—' && (
                              <details className="mt-1.5 text-[10px] text-black/45 dark:text-white/45">
                                <summary className="cursor-pointer">{zh ? '查看 SNMP 返回原值' : 'View raw SNMP value'}</summary>
                                <p className="mt-1 break-words font-mono">{formatValue(info.sys_uptime)}</p>
                              </details>
                            )}
                          </div>
                        </dl>
                      </details>
                    </>
                  ) : (
                    <div className="mt-3 rounded-md border border-dashed border-black/10 px-3 py-5 text-center text-xs text-black/50 dark:border-white/10 dark:text-white/50">
                      {zh ? '服务端未返回系统信息。' : 'The server returned no system information.'}
                    </div>
                  )}
                </section>

                <section className="rounded-lg border border-black/8 bg-white/65 p-3 dark:border-white/10 dark:bg-white/[.035]">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <h3 className="text-xs font-semibold text-black/80 dark:text-white/85">{zh ? 'LLDP 邻居' : 'LLDP neighbors'} <span className="ml-1 font-normal text-black/45 dark:text-white/45">({neighbors.length})</span></h3>
                      <p className="mt-0.5 text-[10px] text-black/50 dark:text-white/50">{getLldpStatusMessage(systemResult.lldp.status, neighbors.length, zh)}</p>
                    </div>
                    <span className={'rounded-full border px-2.5 py-1 text-[10px] font-medium ' + statusToneClass(lldpTone)} title={systemResult.lldp.status}>
                      {getStatusLabel(systemResult.lldp.status, zh)}
                    </span>
                  </div>

                  {neighbors.length > 0 ? (
                    <div className="mt-3 max-h-[28rem] overflow-auto rounded-md border border-black/8 dark:border-white/10">
                      <table className="min-w-[680px] w-full text-left text-[10px]">
                        <caption className="sr-only">{zh ? 'LLDP 邻居列表' : 'LLDP neighbor list'}</caption>
                        <thead className="sticky top-0 z-[1] bg-slate-50 text-black/55 dark:bg-slate-900 dark:text-white/55">
                          <tr>
                            {[zh ? '本端端口' : 'Local interface', zh ? '邻居名称' : 'Neighbor name', zh ? '对端端口' : 'Neighbor port', zh ? '管理地址' : 'Management address'].map(label => <th key={label} className="px-2.5 py-2 font-medium">{label}</th>)}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-black/[.05] dark:divide-white/[.06]">
                          {neighbors.map((neighbor, index) => {
                            const platform = formatValue(neighbor.neighbor_platform);
                            const description = formatValue(neighbor.system_description);
                            const hasDetails = platform !== '—' || description !== '—';
                            return (
                              <tr key={formatValue(neighbor.local_interface) + '-' + formatValue(neighbor.neighbor_name) + '-' + String(index)} className="align-top">
                                <td className="px-2.5 py-2 font-mono">{formatValue(neighbor.local_interface)}</td>
                                <td className="px-2.5 py-2 font-medium">
                                  <div>{formatValue(neighbor.neighbor_name)}</div>
                                  {hasDetails && (
                                    <details className="mt-1.5 text-[10px] font-normal text-black/45 dark:text-white/45">
                                      <summary className="cursor-pointer">{zh ? '查看设备描述' : 'View device details'}</summary>
                                      <div className="mt-1.5 space-y-1 rounded-md bg-black/[.025] p-2 text-black/60 dark:bg-white/[.035] dark:text-white/60">
                                        {platform !== '—' && <p><span className="font-medium">{zh ? '平台：' : 'Platform: '}</span>{platform}</p>}
                                        {description !== '—' && <p className="whitespace-pre-wrap break-words">{description}</p>}
                                      </div>
                                    </details>
                                  )}
                                </td>
                                <td className="px-2.5 py-2 font-mono">{formatValue(neighbor.neighbor_interface)}</td>
                                <td className="px-2.5 py-2 font-mono">{formatValue(neighbor.mgmt_address)}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div className="mt-3 rounded-md border border-dashed border-black/10 px-3 py-6 text-center text-xs text-black/50 dark:border-white/10 dark:text-white/50">
                      {lldpTone === 'error' || lldpTone === 'warning'
                        ? (zh ? '暂时没有可展示的邻居；请查看诊断状态和详情。' : 'No neighbors are available; review the status and diagnostic details.')
                        : (zh ? '设备响应正常，未发现 LLDP 直连邻居。' : 'The device responded, but no direct LLDP neighbors were found.')}
                    </div>
                  )}
                </section>
              </div>
            );
          })()}
          {!systemResult && !systemError && !systemLoading && (
            <div className="rounded-md border border-dashed border-black/10 px-3 py-7 text-center text-xs text-black/50 dark:border-white/10 dark:text-white/50">
              {zh ? '选择设备后查询系统信息和 LLDP 邻居。' : 'Select a device and query its system information and LLDP neighbors.'}
            </div>
          )}
        </div>
      )}

      {activeTab === 'snmpwalk' && (
        <div className="mt-3 space-y-3">
          {probeError && <div role="alert" className="rounded-md border border-rose-500/20 bg-rose-500/[.06] px-3 py-2 text-xs text-rose-700 dark:text-rose-300">{probeError}</div>}
          {probeResult && (
            <div className="space-y-3">
              <div className="rounded-lg border border-black/8 bg-white/65 p-3 dark:border-white/10 dark:bg-white/[.035]">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="text-xs font-semibold text-black/80 dark:text-white/85">{zh ? 'LibreNMS OS 规则命中' : 'LibreNMS OS rule match'}</div>
                  <button type="button" onClick={() => void copyProbeResult()} className="inline-flex items-center gap-1 rounded-md border border-black/10 px-2 py-1 text-[10px] dark:border-white/10"><Copy size={11} />{zh ? '复制诊断 JSON' : 'Copy diagnostic JSON'}</button>
                </div>
                <div className="mt-2 grid gap-x-5 gap-y-1.5 text-[10px] sm:grid-cols-2 lg:grid-cols-3">
                  <div>{zh ? '状态' : 'Status'}: <b>{probeResult.status}</b></div>
                  <div>{zh ? '设备' : 'Device'}: <b>{probeResult.matched_hostname || probeResult.host || '—'}</b></div>
                  <div>{zh ? '规则键' : 'OS key'}: <b>{probeResult.rule?.os_key || '—'}</b></div>
                  <div>{zh ? '厂商 / 平台' : 'Vendor / platform'}: <b>{[probeResult.rule?.vendor, probeResult.rule?.platform].filter(Boolean).join(' / ') || '—'}</b></div>
                  <div className="break-all">{zh ? 'LibreNMS 源文件' : 'LibreNMS source file'}: <b>{probeResult.rule_source_path || '—'}</b></div>
                  <div className="break-all">{zh ? '固定 Commit' : 'Pinned commit'}: <b>{probeResult.rule_source_commit || '—'}</b></div>
                  <div>{zh ? '识别 OID' : 'sysObjectID'}: <b>{String(probeResult.identity?.sys_object_id || '—')}</b></div>
                  <div className="break-all">{zh ? '系统描述' : 'sysDescr'}: <b>{String(probeResult.identity?.sys_descr || '—')}</b></div>
                  <div>{zh ? '规则返回传感器数' : 'Rule sensor rows'}: <b>{probeResult.sensor_count}</b></div>
                </div>
                <div role="status" className="mt-2 rounded-md border border-sky-500/15 bg-sky-500/[.04] px-2.5 py-2 text-[10px]">{probeResult.message}</div>
              </div>

              <div className="overflow-x-auto rounded-lg border border-black/8 dark:border-white/10">
                <table className="min-w-[900px] w-full text-left text-[10px]">
                  <thead className="bg-black/[.025] text-black/50 dark:bg-white/[.035] dark:text-white/50">
                    <tr>{[zh ? '部件' : 'Component', zh ? '读数' : 'Value', 'OID', zh ? 'LibreNMS 规则来源' : 'LibreNMS rule source', zh ? '质量' : 'Quality'].map(label => <th key={label} className="px-2.5 py-2 font-medium">{label}</th>)}</tr>
                  </thead>
                  <tbody className="divide-y divide-black/[.05] dark:divide-white/[.06]">
                    {probeResult.sensors.map((sensor, index) => (
                      <tr key={`${sensor.source_id}-${sensor.oid}-${index}`}>
                        <td className="px-2.5 py-2"><div className="font-medium">{sensor.sensor_name || sensor.component_class}</div><div className="text-black/45 dark:text-white/45">{sensor.measurement_type} · {sensor.group_name || sensor.component_class}</div></td>
                        <td className="px-2.5 py-2 font-mono">{sensor.value ?? sensor.raw_value ?? '—'} {sensor.unit}</td>
                        <td className="px-2.5 py-2 font-mono">{sensor.oid}{Array.isArray(sensor.index) && sensor.index.length ? `.${sensor.index.join('.')}` : ''}</td>
                        <td className="px-2.5 py-2"><div className="break-all">{sensor.source_path}</div><div className="mt-0.5 break-all text-black/40 dark:text-white/40">{sensor.source_commit}</div></td>
                        <td className="px-2.5 py-2">{sensor.quality}</td>
                      </tr>
                    ))}
                    {!probeResult.sensors.length && <tr><td colSpan={5} className="px-3 py-5 text-center text-black/45 dark:text-white/45">{zh ? '规则未发现硬件传感器；查看下方分类结果。' : 'No hardware sensors matched; review category results below.'}</td></tr>}
                  </tbody>
                </table>
              </div>

              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {probeResult.category_results.map((item, index) => (
                  <div key={`${item.component_class}-${index}`} className="rounded-md border border-black/8 bg-white/50 px-2.5 py-2 text-[10px] dark:border-white/10 dark:bg-white/[.025]">
                    <div className="font-semibold">{item.component_class || (zh ? '规则类别' : 'Rule category')} · {item.status || 'unknown'}</div>
                    <div className="mt-1 text-black/55 dark:text-white/55">{item.reason || item.reason_code || '—'}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
          {!probeResult && !probeError && !probeLoading && <div className="rounded-md border border-dashed border-black/10 px-3 py-6 text-center text-xs text-black/50 dark:border-white/10 dark:text-white/50">{zh ? '执行探测后，页面将显示命中的 LibreNMS 规则、来源文件和规则返回的传感器。' : 'Run the probe to see the matched LibreNMS rule, source file, and returned sensors.'}</div>}
        </div>
      )}

      {activeTab === 'validate' && (
        <div className="mt-3">
          <HardwareDiagnosticSummary result={snapshotResult} loading={snapshotLoading} error={snapshotError} zh={zh} />
          <p className="mt-2 flex items-center gap-1 text-[10px] text-black/45 dark:text-white/45"><ShieldCheck size={12} />{zh ? '这里只读取由同一固定 LibreNMS 规则采集并校验来源的已保存样本。' : 'This only reads saved samples collected and provenance-checked through the same pinned LibreNMS rules.'}</p>
        </div>
      )}
    </section>
  );
};

export { LiveWalkInspector };
export default LiveWalkInspector;
