import React, { useEffect, useMemo, useState } from 'react';
import { Activity, AlertTriangle, CheckCircle2, HelpCircle, Server } from 'lucide-react';
import { apiRequest } from '../../../api/http';
import { MetricRow, metricLabel, toPayload } from './MetricRowItem';
import type { InterfaceOidConfig } from './InterfaceConfigSection';

export type SnmpWalkVersion = '1' | '2c';
export type SnmpWalkTargetStatus = 'idle' | 'loading' | 'matched' | 'multiple' | 'none' | 'error';

export interface SnmpMetricProbeResult {
  value: unknown;
  raw_value?: unknown;
  status: string;
  passed?: boolean;
  message?: string;
  mode?: string;
  oid?: string;
  unit?: string;
  rows?: number;
  source?: string;
}

export interface SnmpHardwareTestResult {
  host: string;
  version: SnmpWalkVersion;
  port: number;
  status: 'ok' | 'abnormal' | 'unknown' | string;
  message: string;
  metric_count: number;
  metrics: Record<string, SnmpMetricProbeResult>;
  target_source?: string;
  matched_device_id?: string | null;
  matched_hostname?: string;
}

export interface SnmpInterfaceCheckResult {
  oid?: string;
  passed?: boolean;
  rows?: number;
  counter_bits?: number;
  message?: string;
  sample?: Array<{ index?: string; value?: unknown; [key: string]: unknown }>;
}

export interface SnmpInterfaceTestResult {
  host: string;
  version: SnmpWalkVersion;
  port: number;
  status: string;
  passed: boolean;
  message: string;
  counter_mode?: string;
  selected_counter_bits?: number | null;
  interfaces?: number;
  counter_supported?: number;
  warnings?: Array<{
    code?: string;
    severity?: string;
    message?: string;
    [key: string]: unknown;
  }>;
  checks: Record<string, SnmpInterfaceCheckResult>;
  interface_config?: InterfaceOidConfig;
}

export interface CandidateDevice {
  device_id: string;
  hostname: string;
  ip_address?: string;
}

interface LiveWalkInspectorProps {
  zh: boolean;
  candidateDevices?: CandidateDevice[];
  metrics: MetricRow[];
  interfaceConfig?: InterfaceOidConfig;
  saving?: boolean;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
  onTestResult?: (result: SnmpHardwareTestResult) => void;
}

const inputClass =
  'w-full rounded-md border border-black/8 bg-transparent px-2 py-1.5 font-mono text-[10px] outline-none focus:border-[#00bceb]/55 dark:border-white/10';
const selectClass =
  'w-full rounded-md border border-black/8 bg-transparent px-2 py-1.5 text-[10px] outline-none focus:border-[#00bceb]/55 dark:border-white/10';
const tinyLabelClass = 'mb-1 block text-[9px] text-black/45 dark:text-white/45';
const DEFAULT_HARDWARE_METRIC_KEYS = ['cpu', 'memory', 'temperature', 'fan', 'power_supply'];
const INTERFACE_CHECK_LABELS: Record<string, { zh: string; en: string }> = {
  identity: { zh: '接口名称/描述', en: 'Interface identity' },
  oper_status: { zh: '运行状态', en: 'Operational status' },
  high_speed: { zh: '高速速率', en: 'High speed' },
  speed: { zh: '接口速率', en: 'Interface speed' },
  alias: { zh: '接口别名', en: 'Interface alias' },
  last_change: { zh: '最后变更', en: 'Last change' },
  in_errors: { zh: '入方向错误', en: 'Input errors' },
  out_errors: { zh: '出方向错误', en: 'Output errors' },
  in_discards: { zh: '入方向丢弃', en: 'Input discards' },
  out_discards: { zh: '出方向丢弃', en: 'Output discards' },
  in_ucast: { zh: '入方向单播', en: 'Input unicast' },
  out_ucast: { zh: '出方向单播', en: 'Output unicast' },
  counter64_in_ucast: { zh: '入单播包（64位）', en: '64-bit input unicast' },
  counter64_in_multicast: { zh: '入组播包（64位）', en: '64-bit input multicast' },
  counter64_in_broadcast: { zh: '入广播包（64位）', en: '64-bit input broadcast' },
  counter64_out_ucast: { zh: '出单播包（64位）', en: '64-bit output unicast' },
  counter64_out_multicast: { zh: '出组播包（64位）', en: '64-bit output multicast' },
  counter64_out_broadcast: { zh: '出广播包（64位）', en: '64-bit output broadcast' },
  dot3_hc_fcs_errors: { zh: 'CRC/FCS（64位）', en: '64-bit CRC/FCS' },
  dot3_hc_frame_too_long: { zh: '超长帧错误（64位）', en: '64-bit frame-too-long errors' },
  dot3_hc_internal_mac_rx_errors: { zh: 'MAC接收错误（64位）', en: '64-bit MAC receive errors' },
  dot3_hc_symbol_errors: { zh: '符号错误（64位）', en: '64-bit symbol errors' },
  dot3_fcs_errors_32_fallback: { zh: 'CRC/FCS（32位回退）', en: '32-bit CRC/FCS fallback' },
  counter64_in: { zh: '64 位入流量', en: '64-bit input octets' },
  counter64_out: { zh: '64 位出流量', en: '64-bit output octets' },
  counter32_in: { zh: '32 位入流量', en: '32-bit input octets' },
  counter32_out: { zh: '32 位出流量', en: '32-bit output octets' },
};

const statusTone = (status: string) => {
  const normalized = status.trim().toLowerCase();
  if (normalized === 'ok') {
    return {
      box: 'border-emerald-500/20 bg-emerald-500/[.04]',
      text: 'text-emerald-700 dark:text-emerald-400',
      icon: <CheckCircle2 size={14} />,
    };
  }
  if (normalized === 'fail' || normalized === 'warning' || normalized === 'abnormal') {
    return {
      box: 'border-red-500/20 bg-red-500/[.04]',
      text: 'text-red-700 dark:text-red-400',
      icon: <AlertTriangle size={14} />,
    };
  }
  return {
    box: 'border-amber-500/20 bg-amber-500/[.04]',
    text: 'text-amber-700 dark:text-amber-400',
    icon: <HelpCircle size={14} />,
  };
};

const statusLabel = (status: string, zh: boolean) => {
  const normalized = status.trim().toLowerCase();
  if (normalized === 'ok') return zh ? '正常' : 'Normal';
  if (normalized === 'fail' || normalized === 'abnormal') return zh ? '异常' : 'Abnormal';
  if (normalized === 'warning') return zh ? '告警' : 'Warning';
  if (normalized === 'missing') return zh ? '无返回值' : 'No value';
  if (normalized === 'invalid_value' || normalized === 'out_of_range') return zh ? '值无效' : 'Invalid value';
  if (normalized === 'probe_error') return zh ? '探测失败' : 'Probe failed';
  return zh ? '未知' : 'Unknown';
};

const formatValue = (detail: SnmpMetricProbeResult, zh: boolean) => {
  if (detail.value === true) return zh ? '正常' : 'Normal';
  if (detail.value === false) return zh ? '异常' : 'Abnormal';
  if (detail.value === null || detail.value === undefined || detail.value === '') return '—';
  return `${String(detail.value)}${detail.unit ? ` ${detail.unit}` : ''}`;
};

const formatRawValue = (value: unknown) => {
  if (Array.isArray(value)) return value.join(', ');
  if (value === null || value === undefined || value === '') return '—';
  return String(value);
};

const formatInterfaceSample = (sample: SnmpInterfaceCheckResult['sample'], zh: boolean) => {
  const first = sample?.[0];
  if (!first) return '';
  const index = first.index ? `#${first.index} ` : '';
  return `${zh ? '样例' : 'Sample'} ${index}${formatRawValue(first.value)}`;
};

export const LiveWalkInspector: React.FC<LiveWalkInspectorProps> = ({
  zh,
  candidateDevices = [],
  metrics,
  interfaceConfig,
  saving = false,
  showToast,
  onTestResult,
}) => {
  const [metricTesting, setMetricTesting] = useState(false);
  const [interfaceTesting, setInterfaceTesting] = useState(false);
  const [walkIp, setWalkIp] = useState('');
  const [walkDeviceId, setWalkDeviceId] = useState('');
  const [walkTargetStatus, setWalkTargetStatus] = useState<SnmpWalkTargetStatus>('idle');
  const [walkTargetLabel, setWalkTargetLabel] = useState('');
  const [walkTargetError, setWalkTargetError] = useState('');
  const [walkVersion, setWalkVersion] = useState<SnmpWalkVersion>('2c');
  const [testResult, setTestResult] = useState<SnmpHardwareTestResult | null>(null);
  const [interfaceTestResult, setInterfaceTestResult] = useState<SnmpInterfaceTestResult | null>(null);

  const interfaceConfigFingerprint = useMemo(
    () => JSON.stringify(interfaceConfig || null),
    [interfaceConfig],
  );

  useEffect(() => {
    // A previous result is no longer evidence after any draft OID changes.
    setInterfaceTestResult(null);
  }, [interfaceConfigFingerprint]);

  const configuredMetrics = useMemo(
    () =>
      metrics
        .map(row => ({ row, definition: toPayload(row.definition) }))
        .filter(item => Object.keys(item.definition).length > 0),
    [metrics],
  );
  const testMetricKeys = useMemo(
    () =>
      Array.from(
        new Set([
          ...DEFAULT_HARDWARE_METRIC_KEYS,
          ...configuredMetrics.map(item => item.row.key),
        ]),
      ),
    [configuredMetrics],
  );
  const configuredMetricKeys = useMemo(
    () => new Set(configuredMetrics.map(item => item.row.key)),
    [configuredMetrics],
  );
  const hasTemplateExtras = configuredMetrics.some(item => !DEFAULT_HARDWARE_METRIC_KEYS.includes(item.row.key));

  const handleSelectCandidate = (event: React.ChangeEvent<HTMLSelectElement>) => {
    const deviceId = event.target.value;
    if (!deviceId) return;
    const device = candidateDevices.find(item => item.device_id === deviceId);
    if (!device) return;

    const ip = device.ip_address || '';
    setWalkDeviceId(device.device_id);
    setWalkIp(ip);
    setWalkTargetStatus('matched');
    setWalkTargetLabel(`${device.hostname}${ip ? ` (${ip})` : ''}`);
    setWalkTargetError('');
    setTestResult(null);
    setInterfaceTestResult(null);
    showToast(
      zh
        ? `已选中样例设备：${device.hostname}${ip ? ` (${ip})` : ''}`
        : `Selected sample device: ${device.hostname}`,
      'info',
    );
  };

  const clearWalkTargetConfirmation = (value: string) => {
    setWalkIp(value);
    setWalkDeviceId('');
    setWalkTargetStatus('idle');
    setWalkTargetLabel('');
    setWalkTargetError('');
    setTestResult(null);
    setInterfaceTestResult(null);
  };

  const confirmSnmpTarget = async () => {
    const query = walkIp.trim();
    if (!query) {
      showToast(zh ? '请输入设备 IP 后按回车确认' : 'Enter a device IP and press Enter to confirm', 'error');
      return;
    }
    setWalkTargetStatus('loading');
    setWalkTargetError('');
    try {
      const response = await apiRequest<{ success: boolean; data: { ip: string; device_id: string; hostname?: string } }>(
        `/api/platform-registry/snmp-walk-target?ip=${encodeURIComponent(query)}`,
      );
      const targetIp = String(response.data?.ip || '').trim();
      if (!targetIp) throw new Error(zh ? '资产未返回有效 IP' : 'The asset did not return a valid IP');
      setWalkIp(targetIp);
      setWalkDeviceId(String(response.data.device_id || ''));
      setWalkTargetLabel([response.data.hostname, targetIp].filter(Boolean).join(' / '));
      setWalkTargetStatus('matched');
      showToast(zh ? `已确认 IP：${targetIp}` : `IP confirmed: ${targetIp}`, 'success');
    } catch (error) {
      const message = error instanceof Error ? error.message : zh ? '未找到该 IP' : 'IP not found';
      setWalkDeviceId('');
      setWalkTargetLabel('');
      setWalkTargetStatus('none');
      setWalkTargetError(message);
      showToast(zh ? '未找到该 IP，请先在资产管理中录入' : 'IP not found; add it in asset management first', 'error');
    }
  };

  const executeHardwareTest = async () => {
    if (!walkIp.trim() && !walkDeviceId) {
      showToast(zh ? '请先选择样例设备或输入 IP' : 'Select a device or enter an IP first', 'error');
      return;
    }
    if (!walkDeviceId) {
      await confirmSnmpTarget();
      return;
    }
    setMetricTesting(true);
    setTestResult(null);
    try {
      const response = await apiRequest<{ success: boolean; data: SnmpHardwareTestResult }>(
        '/api/platform-registry/snmp-hardware-test',
        {
          method: 'POST',
          body: JSON.stringify({
            device_id: walkDeviceId,
            version: walkVersion,
            include_default_metrics: true,
            metric_definitions: Object.fromEntries(
              configuredMetrics.map(item => [item.row.key, item.definition]),
            ),
          }),
        },
      );
      setTestResult(response.data);
      onTestResult?.(response.data);
      const isHealthy = response.data.status === 'ok';
      showToast(
        isHealthy
          ? zh
            ? `硬件指标测试通过，共 ${response.data.metric_count} 项`
            : `Hardware metric test passed (${response.data.metric_count} metrics)`
          : response.data.message || (zh ? '硬件指标存在异常或无法确认' : 'Some hardware metrics are abnormal or unknown'),
        isHealthy ? 'success' : response.data.status === 'unknown' ? 'info' : 'error',
      );
    } catch (error) {
      showToast(error instanceof Error ? error.message : zh ? '硬件指标测试失败' : 'Hardware metric test failed', 'error');
    } finally {
      setMetricTesting(false);
    }
  };

  const executeInterfaceTest = async () => {
    if (!interfaceConfig?.enabled) {
      showToast(zh ? '请先启用接口模板' : 'Enable the interface template first', 'error');
      return;
    }
    if (!walkIp.trim() && !walkDeviceId) {
      showToast(zh ? '请先选择样例设备或输入 IP' : 'Select a device or enter an IP first', 'error');
      return;
    }
    if (!walkDeviceId) {
      await confirmSnmpTarget();
      return;
    }
    setInterfaceTesting(true);
    setInterfaceTestResult(null);
    try {
      const response = await apiRequest<{ success: boolean; data: SnmpInterfaceTestResult }>(
        '/api/platform-registry/snmp-interface-test',
        {
          method: 'POST',
          body: JSON.stringify({
            device_id: walkDeviceId,
            version: walkVersion,
            interface_config: interfaceConfig,
          }),
        },
      );
      setInterfaceTestResult(response.data);
      showToast(
        response.data.passed
          ? zh
            ? `接口 OID 验证通过：${response.data.interfaces || 0} 个接口`
            : `Interface OIDs passed (${response.data.interfaces || 0} interfaces)`
          : response.data.message || (zh ? '接口 OID 未通过验证' : 'Interface OID validation failed'),
        response.data.passed ? 'success' : 'error',
      );
    } catch (error) {
      showToast(error instanceof Error ? error.message : zh ? '接口 OID 验证失败' : 'Interface OID validation failed', 'error');
    } finally {
      setInterfaceTesting(false);
    }
  };

  return (
    <section className="mb-4 rounded-xl border border-[#00bceb]/25 bg-[#00bceb]/[0.03] p-3.5 dark:bg-[#00bceb]/[0.05]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="flex items-center gap-1.5 text-[11px] font-semibold text-black/75 dark:text-white/80">
            <Activity size={13} className="text-[#008aad] dark:text-[#00bceb]" />
            {zh ? 'SNMP 硬件与接口 MIB 实时验证（只读）' : 'Live SNMP Hardware & Interface MIB Validation (Read-only)'}
          </div>
          <div className="mt-0.5 text-[9px] leading-4 text-black/45 dark:text-white/45">
            {zh
              ? '硬件指标按模板读取；接口 OID 单独验证返回行数和样例值，不展开整棵 OID 树。'
              : 'Read hardware metrics from the template and validate interface OIDs with row counts and samples, without dumping an OID tree.'}
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-1.5">
          <button
            type="button"
            onClick={executeHardwareTest}
            disabled={metricTesting || interfaceTesting || saving}
            className="inline-flex items-center gap-1 rounded-lg bg-[#00a9ce] px-3 py-1.5 text-[10px] font-semibold text-white shadow-sm hover:bg-[#008fb1] disabled:opacity-45"
          >
            <Activity size={12} className={metricTesting ? 'animate-spin' : ''} />
            {metricTesting ? (zh ? '测试中...' : 'Testing...') : zh ? '测试硬件指标' : 'Test Hardware Metrics'}
          </button>
          <button
            type="button"
            onClick={executeInterfaceTest}
            disabled={metricTesting || interfaceTesting || saving || !interfaceConfig?.enabled}
            className="inline-flex items-center gap-1 rounded-lg border border-[#00a9ce]/40 bg-white/75 px-3 py-1.5 text-[10px] font-semibold text-[#007391] shadow-sm hover:bg-white disabled:opacity-45 dark:bg-white/[.08] dark:text-[#00c2e8] dark:hover:bg-white/[.12]"
          >
            <CheckCircle2 size={12} className={interfaceTesting ? 'animate-spin' : ''} />
            {interfaceTesting ? (zh ? '验证中...' : 'Validating...') : zh ? '验证接口 OID' : 'Validate interface OIDs'}
          </button>
        </div>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {candidateDevices.length > 0 && (
          <label className="block">
            <span className={tinyLabelClass}>{zh ? '从匹配资产快速选择' : 'Select matched device'}</span>
            <select value={walkDeviceId} onChange={handleSelectCandidate} className={selectClass}>
              <option value="">{zh ? '选择匹配型号的设备...' : 'Choose matched device...'}</option>
              {candidateDevices.map(device => (
                <option key={device.device_id} value={device.device_id}>
                  {device.hostname} {device.ip_address ? `(${device.ip_address})` : ''}
                </option>
              ))}
            </select>
          </label>
        )}

        <label className="block">
          <span className={tinyLabelClass}>{zh ? '设备 IP（输入后回车确认）' : 'Target IP (press Enter)'}</span>
          <input
            value={walkIp}
            onChange={event => clearWalkTargetConfirmation(event.target.value)}
            onKeyDown={event => {
              if (event.key === 'Enter') {
                event.preventDefault();
                void confirmSnmpTarget();
              }
            }}
            className={inputClass}
            placeholder="10.254.0.1"
          />
        </label>

        <label className="block">
          <span className={tinyLabelClass}>{zh ? 'SNMP 版本' : 'SNMP version'}</span>
          <select
            value={walkVersion}
            onChange={event => setWalkVersion(event.target.value as SnmpWalkVersion)}
            className={selectClass}
          >
            <option value="2c">SNMPv2c</option>
            <option value="1">SNMPv1</option>
          </select>
        </label>
      </div>

      <div
        className={
          (walkTargetStatus === 'matched'
            ? 'text-emerald-700 dark:text-emerald-400'
            : walkTargetStatus === 'multiple' || walkTargetStatus === 'none' || walkTargetStatus === 'error'
              ? 'text-amber-700 dark:text-amber-400'
              : 'text-black/45 dark:text-white/45') + ' mt-1.5 text-[9px] leading-4'
        }
      >
        {walkTargetStatus === 'idle' &&
          (zh
            ? '💡 选择已有资产或输入 IP 按回车关联 SNMP 凭据；测试使用服务端保存的凭据。'
            : 'Select an asset or confirm an IP; the server resolves the stored SNMP credential.')}
        {walkTargetStatus === 'loading' && (zh ? '正在匹配资产…' : 'Matching assets…')}
        {walkTargetStatus === 'matched' &&
          (zh ? `✓ 已匹配设备：${walkTargetLabel || '在线设备'}` : `✓ Matched: ${walkTargetLabel}`)}
        {walkTargetStatus === 'none' && (zh ? '未匹配到资产，请确认设备已录入资产管理。' : 'No managed asset matched.')}
        {walkTargetStatus === 'error' && (walkTargetError || (zh ? '匹配失败' : 'Matching failed'))}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5 rounded-lg border border-black/6 bg-white/45 p-2 dark:border-white/8 dark:bg-white/[.03]">
        <Server size={12} className="text-black/45 dark:text-white/45" />
        <span className="text-[9px] text-black/45 dark:text-white/45">{zh ? '本次测试指标：' : 'Metrics in this test: '}</span>
        {testMetricKeys.map(key => (
          <span key={key} className="rounded bg-[#00bceb]/10 px-1.5 py-0.5 text-[9px] font-medium text-[#007391] dark:text-[#00bceb]">
            {metricLabel(key, zh)}{configuredMetricKeys.has(key) ? '' : zh ? '（默认）' : ' (default)'}
          </span>
        ))}
        {hasTemplateExtras && (
          <span className="text-[9px] text-black/40 dark:text-white/40">
            {zh ? '模板额外指标也会一并验证' : 'Template extras are tested too'}
          </span>
        )}
        {interfaceConfig?.enabled && (
          <span className="rounded bg-violet-500/10 px-1.5 py-0.5 text-[9px] font-medium text-violet-700 dark:text-violet-300">
            {zh ? '接口 IF-MIB（需单独验证）' : 'Interface IF-MIB (validate separately)'}
          </span>
        )}
      </div>

      {testResult && (
        <div className="mt-3 rounded-lg border border-black/8 bg-white/70 p-3 shadow-sm dark:border-white/10 dark:bg-white/[.04]">
          <div className="flex flex-wrap items-center justify-between gap-2 text-[10px]">
            <div className={`flex items-center gap-1.5 font-semibold ${statusTone(testResult.status).text}`}>
              {statusTone(testResult.status).icon}
              {testResult.message}
            </div>
            <span className="rounded bg-black/[.05] px-1.5 py-0.5 text-[9px] dark:bg-white/[.08]">
              {zh ? `${testResult.metric_count} 项指标` : `${testResult.metric_count} metrics`}
            </span>
          </div>

          <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(testResult.metrics || {}).map(([key, detail]) => {
              const tone = statusTone(detail.status);
              return (
                <div key={key} className={`rounded-lg border p-2.5 ${tone.box}`}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[10px] font-semibold text-black/75 dark:text-white/80">{metricLabel(key, zh)}</span>
                    <span className={`inline-flex items-center gap-1 text-[9px] font-semibold ${tone.text}`}>
                      {tone.icon}
                      {statusLabel(detail.status, zh)}
                    </span>
                  </div>
                  <div className={`mt-2 text-base font-semibold ${tone.text}`}>{formatValue(detail, zh)}</div>
                  {detail.raw_value !== undefined && detail.raw_value !== detail.value && (
                    <div className="mt-1 text-[9px] text-black/45 dark:text-white/45">
                      {zh ? '原始值：' : 'Raw: '}{formatRawValue(detail.raw_value)}
                    </div>
                  )}
                  {detail.message && (
                    <div className="mt-1 text-[9px] leading-4 text-black/50 dark:text-white/50">{detail.message}</div>
                  )}
                  {detail.source && (
                    <div className={`mt-2 inline-flex rounded-full px-1.5 py-0.5 text-[9px] font-semibold ${detail.source === 'template_definition' ? 'bg-cyan-500/10 text-cyan-700 dark:text-cyan-300' : 'bg-slate-500/10 text-slate-600 dark:text-slate-300'}`}>
                      {detail.source === 'template_definition'
                        ? (zh ? '来源：已关联 SNMP 型号模板' : 'Source: linked SNMP model template')
                        : (zh ? '来源：厂商内置采集器' : 'Source: vendor built-in collector')}
                    </div>
                  )}
                  <details className="mt-1.5 text-[9px] text-black/35 dark:text-white/35">
                    <summary className="cursor-pointer select-none hover:text-black/60 dark:hover:text-white/60">
                      {zh ? '查看采集定义' : 'View collection definition'}
                    </summary>
                    <div className="mt-1 break-all font-mono">
                      {detail.mode || '—'} · {detail.oid || '—'}{detail.rows ? ` · ${detail.rows} ${zh ? '行' : 'rows'}` : ''}
                    </div>
                  </details>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {interfaceTestResult && (
        <div className="mt-3 rounded-lg border border-black/8 bg-white/70 p-3 shadow-sm dark:border-white/10 dark:bg-white/[.04]">
          <div className="flex flex-wrap items-center justify-between gap-2 text-[10px]">
            <div className={`flex items-center gap-1.5 font-semibold ${statusTone(interfaceTestResult.status).text}`}>
              {statusTone(interfaceTestResult.status).icon}
              {interfaceTestResult.message}
            </div>
            <span className="rounded bg-black/[.05] px-1.5 py-0.5 text-[9px] dark:bg-white/[.08]">
              {zh
                ? `${interfaceTestResult.interfaces || 0} 个接口 · Counter${interfaceTestResult.selected_counter_bits || '32/64'}`
                : `${interfaceTestResult.interfaces || 0} interfaces · Counter${interfaceTestResult.selected_counter_bits || '32/64'}`}
            </span>
          </div>
          {interfaceTestResult.warnings?.length ? (
            <div className="mt-2 rounded-md border border-amber-300/60 bg-amber-50/80 px-2.5 py-2 text-[9px] leading-4 text-amber-800 dark:border-amber-300/20 dark:bg-amber-400/[.08] dark:text-amber-200">
              <div className="font-semibold">{zh ? '数值质量提醒' : 'Value quality warning'}</div>
              {interfaceTestResult.warnings.map((warning, index) => (
                <div key={`${warning.code || 'warning'}-${index}`}>{warning.message || (zh ? '返回值需要进一步核对设备 SNMP Agent。' : 'Returned values need further verification against the device SNMP Agent.')}</div>
              ))}
            </div>
          ) : null}
          <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(interfaceTestResult.checks || {}).map(([key, check]) => {
              const label = INTERFACE_CHECK_LABELS[key] || { zh: key, en: key };
              const passed = Boolean(check.passed);
              return (
                <div
                  key={key}
                  className={`rounded-lg border p-2.5 ${passed ? 'border-emerald-500/20 bg-emerald-500/[.04]' : 'border-amber-500/20 bg-amber-500/[.04]'}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[10px] font-semibold text-black/75 dark:text-white/80">
                      {zh ? label.zh : label.en}
                    </span>
                    <span className={`text-[9px] font-semibold ${passed ? 'text-emerald-700 dark:text-emerald-400' : 'text-amber-700 dark:text-amber-300'}`}>
                      {passed ? (zh ? '已返回' : 'Returned') : (zh ? '无返回' : 'No value')}
                    </span>
                  </div>
                  <div className="mt-1 break-all font-mono text-[8px] text-black/40 dark:text-white/40">
                    OID {check.oid || '—'} · {check.rows ?? 0} {zh ? '行' : 'rows'}
                  </div>
                  {check.sample?.length ? (
                    <div className="mt-1 text-[9px] text-black/55 dark:text-white/55">
                      {formatInterfaceSample(check.sample, zh)}
                    </div>
                  ) : null}
                  {check.message && (
                    <div className="mt-1 text-[9px] leading-4 text-black/45 dark:text-white/45">{check.message}</div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
};
