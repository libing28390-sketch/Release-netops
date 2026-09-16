import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  Copy,
  Cpu,
  Eye,
  Filter,
  Flame,
  HardDrive,
  HelpCircle,
  Play,
  Plus,
  RefreshCw,
  Search,
  Server,
  Sparkles,
  Zap,
} from 'lucide-react';
import { apiRequest } from '../../../api/http';
import { ActionButton, ActionIconButton } from '../../ui/ActionIconButton';
import { MetricRow, metricLabel, toPayload } from './MetricRowItem';
import type { InterfaceOidConfig } from './InterfaceConfigSection';
import { formatMetricValue, formatRawValue, summarizeRawValue } from './metricResultFormatters';

export type SnmpWalkVersion = '1' | '2c';
export type SnmpWalkTargetStatus = 'idle' | 'loading' | 'matched' | 'multiple' | 'none' | 'error';
export type InspectorTab = 'validate' | 'snmpwalk';

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
  status?: string;
}

export interface SnmpWalkRow {
  oid: string;
  value: unknown;
}

export interface SnmpWalkResponseData {
  host: string;
  oid: string;
  version: string;
  port: number;
  status: string;
  message: string;
  row_count: number;
  truncated: boolean;
  rows: SnmpWalkRow[];
  target_source?: string;
  matched_device_id?: string | null;
  matched_hostname?: string;
}

interface LiveWalkInspectorProps {
  zh: boolean;
  candidateDevices?: CandidateDevice[];
  metrics: MetricRow[];
  interfaceConfig?: InterfaceOidConfig;
  initialTab?: InspectorTab;
  saving?: boolean;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
  onTestResult?: (result: SnmpHardwareTestResult) => void;
  onSelectOidForMetric?: (metricKey: string, oid: string) => void;
}

const inputClass =
  'w-full rounded-md border border-black/8 bg-transparent px-2.5 py-1.5 font-mono text-xs outline-none focus:border-[#00bceb]/55 dark:border-white/10';
const selectClass =
  'w-full rounded-md border border-black/8 bg-transparent px-2.5 py-1.5 text-xs outline-none focus:border-[#00bceb]/55 dark:border-white/10';
const tinyLabelClass = 'mb-1 block text-[10px] font-medium text-black/50 dark:text-white/50';
const DEFAULT_HARDWARE_METRIC_KEYS = ['cpu', 'memory', 'temperature', 'fan', 'power_supply'];
const candidateStatusRank = (status?: string) => String(status || '').trim().toLowerCase() === 'online' ? 0 : 1;

const QUICK_OIDS = [
  { label: 'H3C 实体扩展根', oid: '1.3.6.1.4.1.25506.2.6.1.1.1', desc: 'HH3C Entity Ext MIB' },
  { label: 'H3C CPU 利用率', oid: '1.3.6.1.4.1.25506.2.6.1.1.1.1.6', desc: 'hh3cEntityExtCpuUsage (%)' },
  { label: 'H3C 内存利用率', oid: '1.3.6.1.4.1.25506.2.6.1.1.1.1.8', desc: 'hh3cEntityExtMemUsage (%)' },
  { label: 'H3C 设备温度', oid: '1.3.6.1.4.1.25506.2.6.1.1.1.1.12', desc: 'hh3cEntityExtTemperature (°C)' },
  { label: 'H3C 实体错误状态', oid: '1.3.6.1.4.1.25506.2.6.1.1.1.1.19', desc: 'hh3cEntityExtErrorStatus' },
  { label: '系统基本信息 (MIB-2)', oid: '1.3.6.1.2.1.1', desc: 'sysDescr, sysName, sysUpTime' },
  { label: '实体物理表 (RFC 4133)', oid: '1.3.6.1.2.1.47.1.1.1.1', desc: 'entPhysicalEntry' },
  { label: '接口表 (RFC 1213)', oid: '1.3.6.1.2.1.2.2.1', desc: 'ifEntry' },
  { label: 'IF-MIB 扩展 (64位)', oid: '1.3.6.1.2.1.31.1.1.1', desc: 'ifXEntry (ifHCIn/Out, ifHighSpeed)' },
];

const inferMibNodeName = (oid: string): string => {
  const clean = oid.trim().replace(/^\./, '');
  if (clean.startsWith('1.3.6.1.4.1.25506.2.6.1.1.1.1.6')) return 'hh3cEntityExtCpuUsage';
  if (clean.startsWith('1.3.6.1.4.1.25506.2.6.1.1.1.1.8')) return 'hh3cEntityExtMemUsage';
  if (clean.startsWith('1.3.6.1.4.1.25506.2.6.1.1.1.1.12')) return 'hh3cEntityExtTemperature';
  if (clean.startsWith('1.3.6.1.4.1.25506.2.6.1.1.1.1.19')) return 'hh3cEntityExtErrorStatus';
  if (clean.startsWith('1.3.6.1.4.1.25506.2.6.1.1.1.1.21')) return 'hh3cEntityExtOperStatus';
  if (clean.startsWith('1.3.6.1.4.1.2011.5.25.31.1.1.1.1.5')) return 'hwEntityCpuUsage';
  if (clean.startsWith('1.3.6.1.4.1.2011.5.25.31.1.1.1.1.7')) return 'hwEntityMemUsage';
  if (clean.startsWith('1.3.6.1.4.1.2011.5.25.31.1.1.1.1.11')) return 'hwEntityTemperature';
  if (clean.startsWith('1.3.6.1.4.1.9.9.109.1.1.1.1.8')) return 'cpmCPUTotal5minRev';
  if (clean.startsWith('1.3.6.1.2.1.1.1')) return 'sysDescr';
  if (clean.startsWith('1.3.6.1.2.1.1.3')) return 'sysUpTime';
  if (clean.startsWith('1.3.6.1.2.1.1.5')) return 'sysName';
  if (clean.startsWith('1.3.6.1.2.1.2.2.1.2')) return 'ifDescr';
  if (clean.startsWith('1.3.6.1.2.1.2.2.1.8')) return 'ifOperStatus';
  if (clean.startsWith('1.3.6.1.2.1.31.1.1.1.1')) return 'ifName';
  if (clean.startsWith('1.3.6.1.2.1.31.1.1.1.6')) return 'ifHCInOctets';
  if (clean.startsWith('1.3.6.1.2.1.31.1.1.1.10')) return 'ifHCOutOctets';
  if (clean.startsWith('1.3.6.1.2.1.31.1.1.1.15')) return 'ifHighSpeed';
  if (clean.startsWith('1.3.6.1.2.1.47.1.1.1.1.2')) return 'entPhysicalDescr';
  if (clean.startsWith('1.3.6.1.2.1.47.1.1.1.1.7')) return 'entPhysicalName';
  return '';
};

const walkInstanceSuffix = (rootOid: string, rowOid: string): string => {
  const root = rootOid.trim().replace(/^\./, '').replace(/\.$/, '');
  const row = rowOid.trim().replace(/^\./, '').replace(/\.$/, '');
  if (!root || row === root) return '';
  const prefix = `${root}.`;
  return row.startsWith(prefix) ? row.slice(prefix.length) : '';
};

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
  initialTab = 'snmpwalk',
  saving = false,
  showToast,
  onTestResult,
  onSelectOidForMetric,
}) => {
  const [activeTab, setActiveTab] = useState<InspectorTab>(initialTab);
  const [metricTesting, setMetricTesting] = useState(false);
  const [interfaceTesting, setInterfaceTesting] = useState(false);
  const [walkTesting, setWalkTesting] = useState(false);

  // Target State
  const [walkIp, setWalkIp] = useState('');
  const [walkDeviceId, setWalkDeviceId] = useState('');
  const [walkTargetStatus, setWalkTargetStatus] = useState<SnmpWalkTargetStatus>('idle');
  const [walkTargetLabel, setWalkTargetLabel] = useState('');
  const [walkTargetError, setWalkTargetError] = useState('');
  const [walkVersion, setWalkVersion] = useState<SnmpWalkVersion>('2c');

  // SNMPWALK specific state
  const [walkOidInput, setWalkOidInput] = useState('1.3.6.1.4.1.25506.2.6.1.1.1');
  const [walkMaxRows, setWalkMaxRows] = useState(100);
  const [walkResults, setWalkResults] = useState<SnmpWalkRow[]>([]);
  const [walkResultMeta, setWalkResultMeta] = useState<SnmpWalkResponseData | null>(null);
  const [walkFilter, setWalkFilter] = useState('');

  // Probe Test Results
  const [testResult, setTestResult] = useState<SnmpHardwareTestResult | null>(null);
  const [interfaceTestResult, setInterfaceTestResult] = useState<SnmpInterfaceTestResult | null>(null);
  const autoSelectedCandidateRef = useRef('');

  const interfaceConfigFingerprint = useMemo(
    () => JSON.stringify(interfaceConfig || null),
    [interfaceConfig],
  );

  useEffect(() => {
    setInterfaceTestResult(null);
  }, [interfaceConfigFingerprint]);

  useEffect(() => {
    if (interfaceConfig?.enabled && activeTab === 'snmpwalk') {
      setActiveTab('validate');
    }
  }, [interfaceConfig?.enabled]);

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
  const orderedCandidateDevices = useMemo(
    () => [...candidateDevices].sort((left, right) => (
      candidateStatusRank(left.status) - candidateStatusRank(right.status)
      || left.hostname.localeCompare(right.hostname)
      || left.device_id.localeCompare(right.device_id)
    )),
    [candidateDevices],
  );
  useEffect(() => {
    const candidate = orderedCandidateDevices.find(item => String(item.ip_address || '').trim());
    const ip = String(candidate?.ip_address || '').trim();
    if (!candidate || !ip || autoSelectedCandidateRef.current === candidate.device_id) return;
    if (walkTargetStatus !== 'idle' || walkIp.trim() || walkDeviceId) return;

    autoSelectedCandidateRef.current = candidate.device_id;
    setWalkDeviceId(candidate.device_id);
    setWalkIp(ip);
    setWalkTargetStatus('matched');
    setWalkTargetLabel(`${candidate.hostname}${ip ? ` (${ip})` : ''}`);
    setWalkTargetError('');
  }, [orderedCandidateDevices, walkDeviceId, walkIp, walkTargetStatus]);
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

  const executeSnmpWalk = async () => {
    if (!walkIp.trim() && !walkDeviceId) {
      showToast(zh ? '请先选择样例设备或输入 IP' : 'Select a device or enter an IP first', 'error');
      return;
    }
    if (walkTargetStatus !== 'matched') {
      showToast(zh ? '请先选择设备或按回车确认 IP' : 'Select a device or confirm the IP first', 'error');
      return;
    }
    const targetOid = walkOidInput.trim().replace(/^\./, '');
    if (!targetOid) {
      showToast(zh ? '请输入要 WALK 的 OID 根节点' : 'Enter a root OID to walk', 'error');
      return;
    }

    setWalkTesting(true);
    setWalkResults([]);
    setWalkResultMeta(null);
    try {
      const payload: Record<string, any> = {
        oid: targetOid,
        version: walkVersion,
        max_rows: walkMaxRows,
      };
      if (walkDeviceId) {
        payload.device_id = walkDeviceId;
      } else {
        payload.ip = walkIp.trim();
      }

      const res = await apiRequest<{ success: boolean; data: SnmpWalkResponseData }>(
        '/api/platform-registry/snmp-walk-test',
        {
          method: 'POST',
          body: JSON.stringify(payload),
        },
      );

      if (res.data?.rows) {
        setWalkResults(res.data.rows);
        setWalkResultMeta(res.data);
        showToast(
          zh
            ? `SNMPWALK 探测成功，获取到 ${res.data.rows.length} 行数据`
            : `SNMPWALK succeeded, returned ${res.data.rows.length} rows`,
          'success',
        );
      } else {
        showToast(res.data?.message || (zh ? '未返回任何 OID 数据' : 'No rows returned'), 'info');
      }
    } catch (error) {
      showToast(
        error instanceof Error ? error.message : zh ? 'SNMPWALK 探测失败' : 'SNMPWALK failed',
        'error',
      );
    } finally {
      setWalkTesting(false);
    }
  };

  const executeHardwareTest = async () => {
    const targetDeviceId = walkDeviceId;
    if (!walkIp.trim() && !targetDeviceId) {
      showToast(zh ? '请先选择样例设备或输入 IP' : 'Select a device or enter an IP first', 'error');
      return;
    }
    if (walkTargetStatus !== 'matched') {
      showToast(zh ? '请先选择设备或按回车确认 IP' : 'Select a device or confirm the IP first', 'error');
      return;
    }
    if (!targetDeviceId) {
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
            device_id: targetDeviceId,
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
    if (walkTargetStatus !== 'matched') {
      showToast(zh ? '请先选择设备或按回车确认 IP' : 'Select a device or confirm the IP first', 'error');
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

  const copyToClipboard = (text: string, label = 'OID') => {
    navigator.clipboard.writeText(text);
    showToast(zh ? `已复制 ${label}: ${text}` : `Copied ${label}: ${text}`, 'success');
  };

  const filteredWalkResults = useMemo(() => {
    const term = walkFilter.trim().toLowerCase();
    if (!term) return walkResults;
    return walkResults.filter(row => {
      const oidMatch = row.oid.toLowerCase().includes(term);
      const valMatch = String(row.value).toLowerCase().includes(term);
      const nodeMatch = inferMibNodeName(row.oid).toLowerCase().includes(term);
      return oidMatch || valMatch || nodeMatch;
    });
  }, [walkResults, walkFilter]);

  const walkRootOid = (walkResultMeta?.oid || walkOidInput).trim().replace(/^\./, '');
  const walkInstanceCount = useMemo(() => {
    const instances = new Set(
      walkResults
        .map(row => walkInstanceSuffix(walkRootOid, row.oid))
        .filter(Boolean),
    );
    return instances.size;
  }, [walkResults, walkRootOid]);
  const walkHasTableInstances = walkInstanceCount > 0;

  return (
    <section className="mb-4 rounded-xl border border-[#00bceb]/25 bg-[#00bceb]/[0.03] p-3.5 dark:bg-[#00bceb]/[0.05]">
      {/* Top Header & Tab Navigation */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-black/6 pb-3 dark:border-white/8">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-black/80 dark:text-white/85">
            <Activity size={15} className="text-[#008aad] dark:text-[#00bceb]" />
            {zh ? 'SNMP 实时探测与验证工具箱' : 'SNMP Live Diagnostic & Walk Toolkit'}
          </div>
          {/* Tab buttons */}
          <div className="inline-flex rounded-lg border border-black/8 bg-black/[.03] p-0.5 dark:border-white/10 dark:bg-white/[.04]">
            <button
              type="button"
              onClick={() => setActiveTab('snmpwalk')}
              className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-[11px] font-semibold transition-all ${
                activeTab === 'snmpwalk'
                  ? 'bg-white text-[#007391] shadow-sm dark:bg-white/[.15] dark:text-[#00c2e8]'
                  : 'text-black/50 hover:text-black/80 dark:text-white/50 dark:hover:text-white/80'
              }`}
            >
              <Eye size={12} />
              {zh ? 'SNMPWALK 实时探测与抓取' : 'SNMP Walk Live Capture'}
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('validate')}
              className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-[11px] font-semibold transition-all ${
                activeTab === 'validate'
                  ? 'bg-white text-[#007391] shadow-sm dark:bg-white/[.15] dark:text-[#00c2e8]'
                  : 'text-black/50 hover:text-black/80 dark:text-white/50 dark:hover:text-white/80'
              }`}
            >
              <CheckCircle2 size={12} />
              {zh ? '硬件与接口指标综合验证' : 'Hardware & Interface Health Probing'}
            </button>
          </div>
        </div>

        {activeTab === 'validate' && (
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              onClick={() => void executeHardwareTest()}
              disabled={metricTesting || interfaceTesting || saving || walkTargetStatus !== 'matched'}
              className="inline-flex items-center gap-1 rounded-lg bg-[#00a9ce] px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-[#008fb1] disabled:opacity-45"
            >
              <Activity size={13} className={metricTesting ? 'animate-spin' : ''} />
              {metricTesting ? (zh ? '测试中...' : 'Testing...') : zh ? '测试硬件指标' : 'Test Hardware Metrics'}
            </button>
            <button
              type="button"
              onClick={executeInterfaceTest}
              disabled={metricTesting || interfaceTesting || saving || !interfaceConfig?.enabled || walkTargetStatus !== 'matched'}
              className="inline-flex items-center gap-1 rounded-lg border border-[#00a9ce]/40 bg-white/75 px-3 py-1.5 text-xs font-semibold text-[#007391] shadow-sm hover:bg-white disabled:opacity-45 dark:bg-white/[.08] dark:text-[#00c2e8] dark:hover:bg-white/[.12]"
            >
              <CheckCircle2 size={13} className={interfaceTesting ? 'animate-spin' : ''} />
              {interfaceTesting ? (zh ? '验证中...' : 'Validating...') : zh ? '验证接口 OID' : 'Validate interface OIDs'}
            </button>
          </div>
        )}
      </div>

      {/* Target Device Selector Form */}
      <div className="mt-3 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
        {candidateDevices.length > 0 && (
          <label className="block">
            <span className={tinyLabelClass}>{zh ? '从匹配资产快速选择（在线优先）' : 'Select matched device (online first)'}</span>
            <select value={walkDeviceId} onChange={handleSelectCandidate} className={selectClass}>
              <option value="">{zh ? '选择匹配型号的设备...' : 'Choose matched device...'}</option>
              {orderedCandidateDevices.map(device => (
                <option key={device.device_id} value={device.device_id}>
                  {device.hostname} {device.ip_address ? `(${device.ip_address})` : ''}{candidateStatusRank(device.status) === 0 ? (zh ? ' · 在线' : ' · online') : ''}
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
            placeholder={zh ? '例如：192.168.1.1' : '10.254.0.1'}
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

      {/* Target status tip */}
      <div
        className={
          (walkTargetStatus === 'matched'
            ? 'text-emerald-700 dark:text-emerald-400'
            : walkTargetStatus === 'multiple' || walkTargetStatus === 'none' || walkTargetStatus === 'error'
              ? 'text-amber-700 dark:text-amber-400'
              : 'text-black/45 dark:text-white/45') + ' mt-1.5 text-[10px] leading-4'
        }
      >
        {walkTargetStatus === 'idle' &&
          (zh
            ? '💡 选择已有资产或输入 IP 关联 SNMP 凭据；系统将自动使用该设备的 SNMP Community 与端口。'
            : 'Select an asset or confirm an IP; the server resolves the stored SNMP credential.')}
        {walkTargetStatus === 'loading' && (zh ? '正在匹配资产…' : 'Matching assets…')}
        {walkTargetStatus === 'matched' &&
          (zh ? `✓ 已匹配设备：${walkTargetLabel || '在线设备'}` : `✓ Matched: ${walkTargetLabel}`)}
        {walkTargetStatus === 'none' && (zh ? '未匹配到资产，请确认设备已录入资产管理。' : 'No managed asset matched.')}
        {walkTargetStatus === 'error' && (walkTargetError || (zh ? '匹配失败' : 'Matching failed'))}
      </div>

      {/* ───────────────────────────────────────────────────────────── */}
      {/* TAB 1: SNMPWALK Live Capture */}
      {/* ───────────────────────────────────────────────────────────── */}
      {activeTab === 'snmpwalk' && (
        <div className="mt-3.5 space-y-3">
          {/* Quick OID Presets bar */}
          <div>
            <span className={tinyLabelClass}>
              {zh ? '⚡ 常用 OID 快捷填充探测（点击直接填入并可执行 WALK）：' : '⚡ Quick OID Presets:'}
            </span>
            <div className="flex flex-wrap gap-1.5">
              {QUICK_OIDS.map(item => (
                <button
                  key={item.oid}
                  type="button"
                  onClick={() => setWalkOidInput(item.oid)}
                  className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[10px] transition-all ${
                    walkOidInput === item.oid
                      ? 'border-[#00a9ce] bg-[#00a9ce]/15 font-semibold text-[#007391] dark:text-[#00c2e8]'
                      : 'border-black/8 bg-white/50 text-black/65 hover:border-[#00a9ce]/40 hover:bg-white dark:border-white/10 dark:bg-white/[.03] dark:text-white/65 dark:hover:bg-white/[.08]'
                  }`}
                  title={`${item.desc} (${item.oid})`}
                >
                  <Sparkles size={11} className="text-[#00a9ce]" />
                  <span>{item.label}</span>
                </button>
              ))}
            </div>
          </div>

          {/* OID Input & Walk Execution Row */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="min-w-[280px] flex-1">
              <input
                value={walkOidInput}
                onChange={e => setWalkOidInput(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    void executeSnmpWalk();
                  }
                }}
                className={inputClass}
                placeholder="输入 OID 根节点，例如 1.3.6.1.4.1.25506.2.6.1.1.1"
              />
            </div>
            <div className="flex items-center gap-1.5">
              <select
                aria-label={zh ? '最大获取行数' : 'Max rows'}
                value={walkMaxRows}
                onChange={e => setWalkMaxRows(Number(e.target.value))}
                className="rounded-md border border-black/8 bg-transparent px-2 py-1.5 text-xs outline-none dark:border-white/10"
              >
                <option value={50}>50 {zh ? '行' : 'rows'}</option>
                <option value={100}>100 {zh ? '行' : 'rows'}</option>
                <option value={200}>200 {zh ? '行' : 'rows'}</option>
                <option value={500}>500 {zh ? '行' : 'rows'}</option>
              </select>

              <button
                type="button"
                onClick={executeSnmpWalk}
                disabled={walkTesting || saving || walkTargetStatus !== 'matched'}
                className="inline-flex items-center gap-1 rounded-lg bg-[#00a9ce] px-3.5 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-[#008fb1] disabled:opacity-45"
              >
                <Play size={13} className={walkTesting ? 'animate-spin' : ''} />
                {walkTesting ? (zh ? 'WALK 探测中...' : 'Walking...') : zh ? '执行 SNMP WALK' : 'Run SNMP Walk'}
              </button>
            </div>
          </div>

          {/* Results table & Actions */}
          {walkResults.length > 0 && (
            <div className="rounded-xl border border-black/8 bg-white/75 p-3 shadow-sm dark:border-white/10 dark:bg-white/[.04]">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-black/6 pb-2.5 dark:border-white/8">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-black/80 dark:text-white/85">
                    {zh ? `WALK 返回结果 (${walkResults.length} 项)` : `Walk Results (${walkResults.length})`}
                  </span>
                  {walkResultMeta?.truncated && (
                    <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-medium text-amber-700 dark:text-amber-300">
                      {zh ? '结果已按上限截断' : 'Truncated at limit'}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <div className="relative">
                    <Search size={12} className="absolute left-2 top-2 text-black/35 dark:text-white/35" />
                    <input
                      value={walkFilter}
                      onChange={e => setWalkFilter(e.target.value)}
                      placeholder={zh ? '快速过滤 OID / 名称 / 值...' : 'Filter OID/name/value...'}
                      className="rounded-md border border-black/8 bg-transparent py-1 pl-6 pr-2 text-xs outline-none focus:border-[#00bceb]/55 dark:border-white/10"
                    />
                  </div>
                  <ActionButton
                    type="button"
                    icon={Copy}
                    variant="accent"
                    size="sm"
                    onClick={() => {
                      const text = walkResults.map(r => `${r.oid} = ${r.value}`).join('\n');
                      copyToClipboard(text, 'All WALK results');
                    }}
                  >
                    {zh ? '复制全部结果' : 'Copy All'}
                  </ActionButton>
                </div>
              </div>

              <div className="mt-2 rounded-lg border border-blue-500/20 bg-blue-500/[.045] px-2.5 py-2 text-[10px] leading-4 text-blue-800 dark:text-blue-200">
                <div className="font-semibold">
                  {walkHasTableInstances
                    ? zh
                      ? 'ℹ️ 当前 WALK 命中的是表列，不是单个标量值。'
                      : 'ℹ️ This WALK hit a table column, not a single scalar value.'
                    : zh
                      ? 'ℹ️ WALK 会返回根节点下的多个子节点或实例。'
                      : 'ℹ️ WALK returns child nodes or instances below the selected root.'}
                </div>
                <div className="mt-0.5 text-blue-900/70 dark:text-blue-100/70">
                  {walkHasTableInstances
                    ? zh
                      ? `根 OID ${walkRootOid}（${inferMibNodeName(walkRootOid) || '表列'}）下的最后一段是实体索引；${walkInstanceCount} 个实例可能对应不同板卡、模块或端口，即使值都为 0 也不是重复数据。模板采集时会按聚合方式处理这些行。`
                      : `The final OID segment is an entity index under ${walkRootOid}; ${walkInstanceCount} instances may represent different boards, modules, or ports. Equal values are still distinct rows, and the template aggregation handles them.`
                    : zh
                      ? `本次根 OID：${walkRootOid}；返回 ${walkResults.length} 行。若只需要一个标量，请改用具体实例 OID 或 GET。`
                      : `Root OID: ${walkRootOid}; ${walkResults.length} rows returned. Use a concrete instance OID or GET when a single scalar is needed.`}
                </div>
              </div>

              {/* Table */}
              <div className="mt-2 max-h-[360px] overflow-y-auto rounded-lg border border-black/6 bg-white/40 dark:border-white/8 dark:bg-white/[.02]">
                <table className="nx-data-table nx-data-table--compact">
                  <thead className="sticky top-0 z-10 bg-[var(--card-bg)] text-[10px] font-medium text-black/45 dark:text-white/45">
                    <tr>
                      <th className="px-3 py-2">OID 路径 / 实例索引 / 推断含义</th>
                      <th className="px-3 py-2">返回值 (Value)</th>
                      <th className="px-3 py-2 text-right">一键填入模板指标</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-black/5 font-mono dark:divide-white/5">
                    {filteredWalkResults.map((row, idx) => {
                      const inferred = inferMibNodeName(row.oid);
                      const instance = walkInstanceSuffix(walkRootOid, row.oid);
                      return (
                        <tr key={`${row.oid}-${idx}`} className="hover:bg-[#00bceb]/[0.04]">
                          <td className="px-3 py-2">
                            <div className="flex items-center gap-1.5">
                              <span className="font-semibold text-[#007391] dark:text-[#00c2e8]">{row.oid}</span>
                              <ActionIconButton
                                icon={Copy}
                                label={zh ? '复制 OID' : 'Copy OID'}
                                size="xs"
                                variant="accent"
                                onClick={() => copyToClipboard(row.oid, 'OID')}
                              />
                            </div>
                            {inferred && (
                              <div className="mt-0.5 font-sans text-[10px] text-[#008aad] dark:text-[#00bceb]">
                                🏷️ {inferred}
                              </div>
                            )}
                            <div className="mt-0.5 font-sans text-[10px] text-black/45 dark:text-white/45">
                              {instance ? `${zh ? '实例索引' : 'Instance'}: ${instance}` : (zh ? '标量/根节点' : 'Scalar/root')}
                            </div>
                          </td>
                          <td className="max-w-[320px] break-all px-3 py-2 font-sans font-medium text-black/75 dark:text-white/80">
                            {String(row.value)}
                          </td>
                          <td className="px-3 py-2 text-right font-sans">
                            <div className="inline-flex flex-wrap justify-end gap-1">
                              <button
                                type="button"
                                onClick={() => onSelectOidForMetric?.('cpu', row.oid)}
                                className="rounded bg-[#00a9ce]/10 px-1.5 py-0.5 text-[10px] font-medium text-[#007391] hover:bg-[#00a9ce]/25 dark:text-[#00c2e8]"
                                title={zh ? '将此 OID 填入 CPU 利用率' : 'Set as CPU OID'}
                              >
                                + CPU
                              </button>
                              <button
                                type="button"
                                onClick={() => onSelectOidForMetric?.('memory', row.oid)}
                                className="rounded bg-[#00a9ce]/10 px-1.5 py-0.5 text-[10px] font-medium text-[#007391] hover:bg-[#00a9ce]/25 dark:text-[#00c2e8]"
                                title={zh ? '将此 OID 填入内存利用率' : 'Set as Memory OID'}
                              >
                                + 内存
                              </button>
                              <button
                                type="button"
                                onClick={() => onSelectOidForMetric?.('temperature', row.oid)}
                                className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 hover:bg-amber-500/25 dark:text-amber-300"
                                title={zh ? '将此 OID 填入设备温度' : 'Set as Temperature OID'}
                              >
                                + 温度
                              </button>
                              <button
                                type="button"
                                onClick={() => onSelectOidForMetric?.('fan', row.oid)}
                                className="rounded bg-blue-500/10 px-1.5 py-0.5 text-[10px] font-medium text-blue-700 hover:bg-blue-500/25 dark:text-blue-300"
                                title={zh ? '将此 OID 填入风扇状态' : 'Set as Fan OID'}
                              >
                                + 风扇
                              </button>
                              <button
                                type="button"
                                onClick={() => onSelectOidForMetric?.('power_supply', row.oid)}
                                className="rounded bg-indigo-500/10 px-1.5 py-0.5 text-[10px] font-medium text-indigo-700 hover:bg-indigo-500/25 dark:text-indigo-300"
                                title={zh ? '将此 OID 填入电源状态' : 'Set as Power OID'}
                              >
                                + 电源
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ───────────────────────────────────────────────────────────── */}
      {/* TAB 2: Hardware & Interface Probing Results */}
      {/* ───────────────────────────────────────────────────────────── */}
      {activeTab === 'validate' && (
        <div className="mt-3.5 space-y-3">
          <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-black/6 bg-white/45 p-2 dark:border-white/8 dark:bg-white/[.03]">
            <Server size={13} className="text-black/45 dark:text-white/45" />
            <span className="text-[10px] text-black/50 dark:text-white/50">{zh ? '本次测试指标：' : 'Metrics in this test: '}</span>
            {testMetricKeys.map(key => (
              <span key={key} className="rounded bg-[#00bceb]/10 px-1.5 py-0.5 text-[10px] font-medium text-[#007391] dark:text-[#00bceb]">
                {metricLabel(key, zh)}{configuredMetricKeys.has(key) ? '' : zh ? '（默认）' : ' (default)'}
              </span>
            ))}
            {hasTemplateExtras && (
              <span className="text-[10px] text-black/40 dark:text-white/40">
                {zh ? '模板额外指标也会一并验证' : 'Template extras are tested too'}
              </span>
            )}
            {interfaceConfig?.enabled && (
              <span className="rounded bg-violet-500/10 px-1.5 py-0.5 text-[10px] font-medium text-violet-700 dark:text-violet-300">
                {zh ? '接口 IF-MIB（需单独验证）' : 'Interface IF-MIB (validate separately)'}
              </span>
            )}
          </div>

          {testResult && (
            <div className="rounded-lg border border-black/8 bg-white/70 p-3 shadow-sm dark:border-white/10 dark:bg-white/[.04]">
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                <div className={`flex items-center gap-1.5 font-semibold ${statusTone(testResult.status).text}`}>
                  {statusTone(testResult.status).icon}
                  {testResult.message}
                </div>
                <span className="rounded bg-black/[.05] px-1.5 py-0.5 text-[10px] dark:bg-white/[.08]">
                  {zh ? `${testResult.metric_count} 项指标` : `${testResult.metric_count} metrics`}
                </span>
              </div>

              <div className="mt-2.5 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {Object.entries(testResult.metrics || {}).map(([key, detail]) => {
                  const tone = statusTone(detail.status);
                  const hasRawValue = detail.raw_value !== undefined && detail.raw_value !== detail.value;
                  return (
                    <div key={key} className={`flex min-h-[148px] min-w-0 flex-col rounded-lg border p-2.5 ${tone.box}`}>
                      <div className="flex items-center justify-between gap-2">
                        <span className="min-w-0 truncate text-xs font-semibold text-black/75 dark:text-white/80" title={metricLabel(key, zh)}>{metricLabel(key, zh)}</span>
                        <span className={`inline-flex items-center gap-1 text-[10px] font-semibold ${tone.text}`}>
                          {tone.icon}
                          {statusLabel(detail.status, zh)}
                        </span>
                      </div>
                      <div
                        className={`mt-2 min-h-7 break-words text-lg font-semibold leading-7 tabular-nums ${tone.text}`}
                        title={key === 'uptime' ? `${formatRawValue(detail.value)}${detail.unit ? ` ${detail.unit}` : ''}` : undefined}
                      >
                        {formatMetricValue(key, detail, zh)}
                      </div>
                      {hasRawValue && (
                        <div
                          className="mt-1 min-w-0 truncate text-[10px] text-black/45 dark:text-white/45"
                          title={formatRawValue(detail.raw_value)}
                        >
                          {zh ? '原始摘要：' : 'Raw summary: '}{summarizeRawValue(detail.raw_value, zh)}
                        </div>
                      )}
                      {detail.message && (
                        <div className="mt-1 max-h-8 overflow-hidden text-[10px] leading-4 text-black/50 dark:text-white/50">{detail.message}</div>
                      )}
                      <div className="mt-auto pt-2">
                        {detail.source && (
                          <div className={`inline-flex max-w-full truncate rounded-full px-1.5 py-0.5 text-[9px] font-semibold ${detail.source === 'template_definition' ? 'bg-cyan-500/10 text-cyan-700 dark:text-cyan-300' : 'bg-slate-500/10 text-slate-600 dark:text-slate-300'}`} title={detail.source}>
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
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {interfaceTestResult && (
            <div className="rounded-lg border border-black/8 bg-white/70 p-3 shadow-sm dark:border-white/10 dark:bg-white/[.04]">
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                <div className={`flex items-center gap-1.5 font-semibold ${statusTone(interfaceTestResult.status).text}`}>
                  {statusTone(interfaceTestResult.status).icon}
                  {interfaceTestResult.message}
                </div>
                <span className="rounded bg-black/[.05] px-1.5 py-0.5 text-[10px] dark:bg-white/[.08]">
                  {zh
                    ? `${interfaceTestResult.interfaces || 0} 个接口 · Counter${interfaceTestResult.selected_counter_bits || '32/64'}`
                    : `${interfaceTestResult.interfaces || 0} interfaces · Counter${interfaceTestResult.selected_counter_bits || '32/64'}`}
                </span>
              </div>
              {interfaceTestResult.warnings?.length ? (
                <div className="mt-2 rounded-md border border-amber-300/60 bg-amber-50/80 px-2.5 py-2 text-[10px] leading-4 text-amber-800 dark:border-amber-300/20 dark:bg-amber-400/[.08] dark:text-amber-200">
                  <div className="font-semibold">{zh ? '数值质量提醒' : 'Value quality warning'}</div>
                  {interfaceTestResult.warnings.map((warning, index) => (
                    <div key={`${warning.code || 'warning'}-${index}`}>{warning.message || (zh ? '返回值需要进一步核对设备 SNMP Agent。' : 'Returned values need further verification against the device SNMP Agent.')}</div>
                  ))}
                </div>
              ) : null}
              <div className="mt-2.5 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {Object.entries(interfaceTestResult.checks || {}).map(([key, check]) => {
                  const label = INTERFACE_CHECK_LABELS[key] || { zh: key, en: key };
                  const passed = Boolean(check.passed);
                  return (
                    <div
                      key={key}
                      className={`rounded-lg border p-2.5 ${passed ? 'border-emerald-500/20 bg-emerald-500/[.04]' : 'border-amber-500/20 bg-amber-500/[.04]'}`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-semibold text-black/75 dark:text-white/80">
                          {zh ? label.zh : label.en}
                        </span>
                        <span className={`text-[10px] font-semibold ${passed ? 'text-emerald-700 dark:text-emerald-400' : 'text-amber-700 dark:text-amber-300'}`}>
                          {passed ? (zh ? '已返回' : 'Returned') : (zh ? '无返回' : 'No value')}
                        </span>
                      </div>
                      <div className="mt-1 break-all font-mono text-[9px] text-black/45 dark:text-white/45">
                        OID {check.oid || '—'} · {check.rows ?? 0} {zh ? '行' : 'rows'}
                      </div>
                      {check.sample?.length ? (
                        <div className="mt-1 text-[10px] text-black/60 dark:text-white/60">
                          {formatInterfaceSample(check.sample, zh)}
                        </div>
                      ) : null}
                      {check.message && (
                        <div className="mt-1 text-[10px] leading-4 text-black/50 dark:text-white/50">{check.message}</div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
};

export default LiveWalkInspector;
