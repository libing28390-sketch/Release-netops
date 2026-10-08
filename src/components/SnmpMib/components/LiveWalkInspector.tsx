import React, { useEffect, useMemo, useState } from 'react';
import { Activity, CheckCircle2, Copy, Play, RefreshCw, Server, ShieldCheck } from 'lucide-react';
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
            {zh ? 'LibreNMS 规则诊断' : 'LibreNMS Rule Diagnostics'}
          </div>
          <div className="inline-flex flex-wrap rounded-lg border border-black/8 bg-black/[.03] p-0.5 dark:border-white/10 dark:bg-white/[.04]">
            <button type="button" className={tabClass('snmpwalk')} onClick={() => setActiveTab('snmpwalk')}>
              <Play size={12} />{zh ? '规则探测' : 'Rule probe'}
            </button>
            {showSystemInfoTab && (
              <button type="button" className={tabClass('system')} onClick={() => setActiveTab('system')}>
                <Server size={12} />{zh ? '系统识别' : 'System identity'}
              </button>
            )}
            {showHardwareValidationTab && (
              <button type="button" className={tabClass('validate')} onClick={() => setActiveTab('validate')}>
                <CheckCircle2 size={12} />{zh ? '已采集样本' : 'Stored samples'}
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
          <span className="ml-2">{zh ? '凭据由服务端从 CMDB 读取；OID 和规则均由固定 LibreNMS 规则包决定。' : 'Credentials are resolved server-side; OIDs and probes come only from the pinned LibreNMS bundle.'}</span>
        </div>
        {activeTab === 'snmpwalk' || activeTab === 'system' ? (
          <button
            type="button"
            onClick={() => void runLibreNMSRuleProbe()}
            disabled={probeLoading || saving || (!target && !candidateId && !initialIp)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[#00a9ce] px-3.5 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-[#008fb1] disabled:opacity-45"
          >
            {probeLoading ? <RefreshCw size={13} className="animate-spin" /> : <Activity size={13} />}
            {probeLoading ? (zh ? '按 LibreNMS 规则探测中…' : 'Running LibreNMS rules…') : (zh ? '执行 LibreNMS 规则探测' : 'Run LibreNMS rule probe')}
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

      {(activeTab === 'snmpwalk' || activeTab === 'system') && (
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
