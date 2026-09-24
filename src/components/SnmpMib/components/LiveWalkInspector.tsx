import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  Copy,
  Cpu,
  Database,
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
  X,
} from 'lucide-react';
import { ApiError, apiRequest } from '../../../api/http';
import { ActionButton, ActionIconButton } from '../../ui/ActionIconButton';
import { useEscapeClose } from '../../../hooks/useEscapeClose';
import { MetricRow, metricLabel, toPayload } from './MetricRowItem';
import type { InterfaceOidConfig } from './InterfaceConfigSection';
import OidPickerModal, { type MibNodeItem } from '../OidPickerModal';
import { formatMetricValue, formatRawValue, formatUptime, summarizeRawValue } from './metricResultFormatters';

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
  vendor?: string;
  platform?: string;
  model?: string;
  version?: string;
}

export interface SnmpWalkRow {
  oid: string;
  value: unknown;
  mib_node?: string;
  mib_name?: string;
  mib_vendor?: string;
  mib_oid?: string;
  syntax_type?: string;
  access_type?: string;
  mib_status?: string;
  description?: string;
  instance_suffix?: string;
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
  initialIp?: string;
  initialWalkOid?: string;
  selectedDevice?: CandidateDevice;
  candidateDevices?: CandidateDevice[];
  showCandidateSelector?: boolean;
  showHardwareValidationTab?: boolean;
  diagnosticPresetOnly?: boolean;
  hideMaxRowsSelector?: boolean;
  publicSummaryOnly?: boolean;
  metrics: MetricRow[];
  interfaceConfig?: InterfaceOidConfig;
  initialTab?: InspectorTab;
  saving?: boolean;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
  onTestResult?: (result: SnmpHardwareTestResult) => void;
}

const inputClass =
  'w-full rounded-md border border-black/8 bg-transparent px-2.5 py-1.5 font-mono text-xs outline-none focus:border-[#00bceb]/55 dark:border-white/10';
const selectClass =
  'w-full rounded-md border border-black/8 bg-transparent px-2.5 py-1.5 text-xs outline-none focus:border-[#00bceb]/55 dark:border-white/10';
const tinyLabelClass = 'mb-1 block text-[10px] font-medium text-black/50 dark:text-white/50';
const DEFAULT_HARDWARE_METRIC_KEYS = ['cpu', 'memory', 'temperature', 'fan', 'power_supply'];
const candidateStatusRank = (status?: string) => String(status || '').trim().toLowerCase() === 'online' ? 0 : 1;
const LLDP_REMOTE_ROOT_OID = '1.0.8802.1.1.2.1.4';
const LLDP_REMOTE_TABLE_ROOT_OID = '1.0.8802.1.1.2.1.4.1';
const LLDP_REMOTE_ENTRY_ROOT_OID = `${LLDP_REMOTE_TABLE_ROOT_OID}.1`;
const LLDP_KEY_FIELD_OIDS = [
  `${LLDP_REMOTE_ENTRY_ROOT_OID}.7`, // lldpRemPortId
  `${LLDP_REMOTE_ENTRY_ROOT_OID}.9`, // lldpRemSysName
  '1.0.8802.1.1.2.1.4.2.1.2', // lldpRemManAddr
  '1.0.8802.1.1.2.1.3.7.1.3', // lldpLocPortId
  '1.0.8802.1.1.2.1.3.7.1.4', // lldpLocPortDesc
  '1.3.6.1.2.1.31.1.1.1.1', // ifName fallback keyed by ifIndex
];

const isLldpRemoteWalk = (oid: string): boolean =>
  oid === LLDP_REMOTE_ROOT_OID || oid.startsWith(`${LLDP_REMOTE_ROOT_OID}.`);

const QUICK_OIDS: Array<{ label: string; labelEn?: string; oid: string; desc: string; descEn?: string }> = [
  { label: '系统基本信息 (MIB-2)', labelEn: 'System (MIB-2)', oid: '1.3.6.1.2.1.1', desc: 'sysDescr, sysName, sysUpTime' },
  { label: '接口表 (IF-MIB)', labelEn: 'Interfaces (IF-MIB)', oid: '1.3.6.1.2.1.31.1.1.1', desc: 'ifName, ifHCInOctets, ifHCOutOctets, ifHighSpeed' },
  { label: 'LLDP 邻居与端口', labelEn: 'LLDP Neighbors and Ports', oid: LLDP_REMOTE_TABLE_ROOT_OID, desc: '只探测邻居名称、本端/对端端口和管理地址', descEn: 'Only neighbor name, local/remote port, and management address' },
  { label: '实体物理表 (ENTITY-MIB)', labelEn: 'Physical Entities (ENTITY-MIB)', oid: '1.3.6.1.2.1.47.1.1.1.1', desc: 'entPhysicalEntry' },
  { label: 'H3C 实体扩展根', oid: '1.3.6.1.4.1.25506.2.6.1.1.1', desc: 'HH3C Entity Ext MIB' },
  { label: 'H3C CPU 利用率', oid: '1.3.6.1.4.1.25506.2.6.1.1.1.1.6', desc: 'hh3cEntityExtCpuUsage (%)' },
  { label: 'H3C 内存利用率', oid: '1.3.6.1.4.1.25506.2.6.1.1.1.1.8', desc: 'hh3cEntityExtMemUsage (%)' },
  { label: 'H3C 设备温度', oid: '1.3.6.1.4.1.25506.2.6.1.1.1.1.12', desc: 'hh3cEntityExtTemperature (°C)' },
  { label: 'H3C 实体错误状态', oid: '1.3.6.1.4.1.25506.2.6.1.1.1.1.19', desc: 'hh3cEntityExtErrorStatus' },
  { label: '接口表 (RFC 1213)', labelEn: 'Interfaces (RFC 1213)', oid: '1.3.6.1.2.1.2.2.1', desc: 'ifEntry' },
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
  if (clean.startsWith('1.0.8802.1.1.2.1.4.1.1.9')) return 'lldpRemSysName';
  if (clean.startsWith('1.0.8802.1.1.2.1.4.1.1.2')) return 'lldpRemChassisId';
  if (clean.startsWith('1.0.8802.1.1.2.1.4.1.1.7')) return 'lldpRemPortId';
  if (clean.startsWith('1.0.8802.1.1.2.1.4.1.1.8')) return 'lldpRemPortDesc';
  if (clean.startsWith('1.0.8802.1.1.2.1.4.1.1.10')) return 'lldpRemSysDesc';
  if (clean.startsWith('1.0.8802.1.1.2.1.4.2.1.2')) return 'lldpRemManAddr';
  if (clean.startsWith('1.0.8802.1.1.2.1.3.7.1.3')) return 'lldpLocPortId';
  if (clean.startsWith('1.0.8802.1.1.2.1.3.7.1.4')) return 'lldpLocPortDesc';
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

interface WalkDiagnosticSummary {
  key: string;
  label: string;
  labelEn: string;
  value: string;
  detail?: string;
}

const numericWalkValue = (value: unknown): number | null => {
  const raw = String(value ?? '').trim();
  const match = raw.match(/(-?\d+(?:\.\d+)?)\s*(?:%|°?C)?$/i);
  if (!match) return null;
  const parsed = Number(match[1]);
  return Number.isFinite(parsed) ? parsed : null;
};

const formatWalkNumber = (value: number) => Number.isInteger(value) ? String(value) : value.toFixed(1);

const isPublicStandardWalkRow = (row: SnmpWalkRow): boolean => {
  const oid = String(row.oid || '').trim().replace(/^\./, '');
  if (oid.startsWith('1.0.8802.1.1.2.')) return true;
  if (oid.startsWith('1.3.6.1.4.1.')) return false;
  const vendor = String(row.mib_vendor || '').trim().toLowerCase();
  if (vendor) return vendor === 'standard';
  return oid.startsWith('1.3.6.1.2.1.') || oid.startsWith('1.3.6.1.6.3.');
};

const isVendorSpecificWalkRow = (row: SnmpWalkRow): boolean => {
  const oid = String(row.oid || '').trim().replace(/^\./, '');
  if (oid.startsWith('1.0.8802.1.1.2.')) return false;
  if (oid.startsWith('1.3.6.1.4.1.')) return true;
  const vendor = String(row.mib_vendor || '').trim().toLowerCase();
  if (vendor) return vendor !== 'standard';
  return false;
};

const buildWalkDiagnosticSummary = (rows: SnmpWalkRow[], rootOid: string, zh: boolean): WalkDiagnosticSummary[] => {
  const metricValues: Record<'cpu' | 'memory' | 'temperature', number[]> = {
    cpu: [],
    memory: [],
    temperature: [],
  };
  const interfaceNames = new Set<string>();
  const interfaceStates = new Map<string, string>();
  const neighborNames = new Set<string>();
  const storageDescriptions = new Map<string, string>();
  const storageUsed = new Map<string, number>();
  const storageSizes = new Map<string, number>();
  let systemName = '';
  let systemUptime = '';
  let systemDescription = '';

  rows.forEach((row, index) => {
    const node = String(inferMibNodeName(row.oid) || row.mib_node || '').trim();
    const normalizedNode = node.toLowerCase().replace(/[^a-z0-9]/g, '');
    const suffix = String(row.instance_suffix ?? walkInstanceSuffix(rootOid, row.oid) ?? '').trim() || String(index);
    const rawValue = String(row.value ?? '').trim();
    const value = numericWalkValue(row.value);

    if (normalizedNode === 'sysname') systemName = rawValue;
    else if (normalizedNode === 'sysuptime') systemUptime = rawValue;
    else if (normalizedNode === 'sysdescr') systemDescription = rawValue;

    if ((normalizedNode === 'hrprocessorload' || (normalizedNode.includes('cpu') && /(usage|util|cpmcputotal)/.test(normalizedNode))) && value !== null) {
      metricValues.cpu.push(value);
    } else if (normalizedNode.includes('mem') && /(usage|util)/.test(normalizedNode) && value !== null) {
      metricValues.memory.push(value);
    } else if (normalizedNode.includes('temp') && value !== null) {
      metricValues.temperature.push(value);
    }

    if (normalizedNode === 'hrstoragedescr') storageDescriptions.set(suffix, rawValue);
    if (normalizedNode === 'hrstorageused' && value !== null) storageUsed.set(suffix, value);
    if (normalizedNode === 'hrstoragesize' && value !== null) storageSizes.set(suffix, value);

    if (normalizedNode === 'ifname' || normalizedNode === 'ifdescr') interfaceNames.add(suffix);
    if (normalizedNode === 'ifoperstatus') interfaceStates.set(suffix, rawValue);
    if (normalizedNode === 'lldpremsysname' && rawValue) neighborNames.add(rawValue);
  });

  storageDescriptions.forEach((description, index) => {
    if (!/(physical|main memory|system memory|\bram\b|real memory)/i.test(description) || /(swap|flash|cache)/i.test(description)) return;
    const used = storageUsed.get(index);
    const size = storageSizes.get(index);
    if (used !== undefined && size !== undefined && size > 0) metricValues.memory.push((used / size) * 100);
  });

  const summaries: WalkDiagnosticSummary[] = [];
  const appendMetric = (key: 'cpu' | 'memory' | 'temperature', label: string, labelEn: string, unit: string) => {
    const values = metricValues[key];
    if (!values.length) return;
    const highest = Math.max(...values);
    const lowest = Math.min(...values);
    const formatValue = (value: number) => `${formatWalkNumber(value)}${unit === '%' ? '%' : ` ${unit}`}`;
    const detail = values.length > 1
      ? (zh
        ? `采集实例范围 ${formatValue(lowest)}–${formatValue(highest)} · 卡片显示最高值`
        : `Instance range ${formatValue(lowest)}–${formatValue(highest)} · card shows the peak`)
      : undefined;
    summaries.push({ key, label, labelEn, value: formatValue(highest), detail });
  };

  appendMetric('cpu', 'CPU 使用率', 'CPU usage', '%');
  appendMetric('memory', '内存使用率', 'Memory usage', '%');
  appendMetric('temperature', '最高温度', 'Peak temperature', '°C');

  if (interfaceStates.size > 0) {
    let up = 0;
    let down = 0;
    interfaceStates.forEach(status => {
      const numericStatus = numericWalkValue(status);
      if (numericStatus === 1) up += 1;
      else if (numericStatus === 2) down += 1;
    });
    const unknown = Math.max(0, interfaceStates.size - up - down);
    summaries.push({
      key: 'interfaces',
      label: '接口状态',
      labelEn: 'Interface status',
      value: zh ? `${up} 个 UP · ${down} 个 DOWN${unknown ? ` · ${unknown} 个其他` : ''}` : `${up} UP · ${down} DOWN${unknown ? ` · ${unknown} other` : ''}`,
      detail: interfaceNames.size ? (zh ? `识别到 ${interfaceNames.size} 个接口` : `${interfaceNames.size} interfaces identified`) : undefined,
    });
  } else if (interfaceNames.size > 0) {
    summaries.push({
      key: 'interfaces',
      label: '接口数量',
      labelEn: 'Interfaces',
      value: String(interfaceNames.size),
      detail: zh ? '已返回接口名称' : 'Interface names returned',
    });
  }

  if (neighborNames.size > 0) {
    summaries.push({
      key: 'neighbors',
      label: 'LLDP 邻居',
      labelEn: 'LLDP neighbors',
      value: String(neighborNames.size),
      detail: Array.from(neighborNames).slice(0, 3).join('、'),
    });
  }

  if (systemName) summaries.push({ key: 'system', label: '设备名称', labelEn: 'System name', value: systemName, detail: systemDescription || undefined });
  if (systemUptime) {
    const ticks = systemUptime.match(/^\s*(?:Timeticks:\s*)?\((\d+)\)/i);
    const plainTicks = systemUptime.trim().match(/^\d+$/);
    const uptimeValue = ticks
      ? formatUptime(Number(ticks[1]) / 100, zh)
      : plainTicks
        ? formatUptime(Number(plainTicks[0]) / 100, zh)
        : formatUptime(systemUptime, zh);
    summaries.push({
      key: 'uptime',
      label: '运行时间',
      labelEn: 'Uptime',
      value: uptimeValue,
    });
  }

  return summaries;
};

interface LldpNeighborSummary {
  key: string;
  name: string;
  localPort: string;
  remotePort: string;
  managementIp: string;
}

const readableLldpValue = (value: unknown): string => {
  const raw = String(value ?? '').replace(/\u0000/g, '').trim();
  if (!raw || raw.includes('\uFFFD') || /[\u0001-\u0008\u000B\u000C\u000E-\u001F]/.test(raw)) return '';
  return raw;
};

const parseLldpNeighbors = (rows: SnmpWalkRow[], rootOid: string, zh: boolean): LldpNeighborSummary[] => {
  const neighbors = new Map<string, { name: string; remotePort: string; chassisId: string; localPortNum: string; managementIp: string }>();
  const localPortIds = new Map<string, string>();
  const localPortDescriptions = new Map<string, string>();
  const localInterfaceNames = new Map<string, string>();
  const managementIps = new Map<string, string>();

  rows.forEach(row => {
    const node = String(inferMibNodeName(row.oid) || row.mib_node || '').toLowerCase().replace(/[^a-z0-9]/g, '');
    const rowOid = String(row.oid || '').trim().replace(/^\./, '');
    const matchingColumnRoot = LLDP_KEY_FIELD_OIDS.find(oid => rowOid.startsWith(`${oid}.`));
    const columnInstanceSuffix = matchingColumnRoot ? rowOid.slice(matchingColumnRoot.length) : '';
    const suffix = String(row.instance_suffix || columnInstanceSuffix || walkInstanceSuffix(rootOid, rowOid)).trim().replace(/^\./, '');
    const parts = suffix ? suffix.split('.') : [];
    const value = readableLldpValue(row.value);

    if (parts.length === 1 && value && ['lldplocportid', 'lldplocportdesc', 'ifname'].includes(node)) {
      if (node === 'lldplocportid') localPortIds.set(parts[0], value);
      else if (node === 'lldplocportdesc') localPortDescriptions.set(parts[0], value);
      else localInterfaceNames.set(parts[0], value);
      return;
    }

    if (node.startsWith('lldpremmanaddr') && parts.length >= 9) {
      for (let index = 3; index + 6 <= parts.length; index += 1) {
        if (parts[index] !== '1' || parts[index + 1] !== '4' || parts.length - index - 2 !== 4) continue;
        const address = parts.slice(index + 2).map(Number);
        if (address.every(octet => Number.isInteger(octet) && octet >= 0 && octet <= 255)) {
          managementIps.set(parts.slice(0, 3).join('.'), address.join('.'));
        }
        break;
      }
      return;
    }

    if (!node.startsWith('lldprem') || parts.length < 3) return;
    const key = parts.slice(0, 3).join('.');
    const neighbor = neighbors.get(key) || {
      name: '',
      remotePort: '',
      chassisId: '',
      localPortNum: parts[1] || '',
      managementIp: '',
    };
    if (node === 'lldpremsysname' && value) neighbor.name = value;
    else if ((node === 'lldpremportid' || node === 'lldpremportdesc') && value && !neighbor.remotePort) neighbor.remotePort = value;
    else if (node === 'lldpremchassisid' && value) neighbor.chassisId = value;
    neighbors.set(key, neighbor);
  });

  managementIps.forEach((address, key) => {
    const neighbor = neighbors.get(key);
    if (neighbor) neighbor.managementIp = address;
  });

  return Array.from(neighbors.entries())
    .map(([key, neighbor]) => ({
      key,
      name: neighbor.name || neighbor.chassisId || `#${neighbor.localPortNum}`,
      localPort: localPortIds.get(neighbor.localPortNum)
        || localPortDescriptions.get(neighbor.localPortNum)
        || localInterfaceNames.get(neighbor.localPortNum)
        || (neighbor.localPortNum
          ? zh ? `未识别端口（索引 ${neighbor.localPortNum}）` : `Unresolved port (index ${neighbor.localPortNum})`
          : '—'),
      remotePort: neighbor.remotePort || '—',
      managementIp: neighbor.managementIp || '—',
    }))
    .filter(neighbor => neighbor.name || neighbor.remotePort !== '—');
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
  initialIp = '',
  initialWalkOid = '',
  selectedDevice,
  candidateDevices = [],
  showCandidateSelector = true,
  showHardwareValidationTab = true,
  diagnosticPresetOnly = false,
  hideMaxRowsSelector = false,
  publicSummaryOnly = false,
  metrics,
  interfaceConfig,
  initialTab = 'snmpwalk',
  saving = false,
  showToast,
  onTestResult,
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
  const [walkMaxRows, setWalkMaxRows] = useState(hideMaxRowsSelector ? 10000 : 100);
  const [walkResults, setWalkResults] = useState<SnmpWalkRow[]>([]);
  const [walkResultMeta, setWalkResultMeta] = useState<SnmpWalkResponseData | null>(null);
  const [walkError, setWalkError] = useState('');
  const [walkResultOpen, setWalkResultOpen] = useState(false);
  const [walkFilter, setWalkFilter] = useState('');
  const [walkResultScope, setWalkResultScope] = useState<'public' | 'private'>('public');
  const [oidPickerOpen, setOidPickerOpen] = useState(false);
  const walkResultDialogRef = useRef<HTMLDivElement | null>(null);
  const walkResultDetailsRef = useRef<HTMLDetailsElement | null>(null);
  const walkResultCloseRef = useRef<HTMLButtonElement | null>(null);
  const previousWalkFocusRef = useRef<HTMLElement | null>(null);
  const walkRequestSequenceRef = useRef(0);
  const liveWalkContextRef = useRef('');
  liveWalkContextRef.current = [
    selectedDevice?.device_id || walkDeviceId,
    selectedDevice?.ip_address || walkIp,
    walkOidInput,
    walkVersion,
  ].join('|');
  useEscapeClose(walkResultOpen, () => setWalkResultOpen(false));
  const visibleQuickOids = diagnosticPresetOnly ? QUICK_OIDS.slice(0, 3) : QUICK_OIDS;

  useEffect(() => {
    const initial = String(initialIp || '').trim();
    walkRequestSequenceRef.current += 1;
    setWalkTesting(false);
    setWalkResults([]);
    setWalkResultMeta(null);
    setWalkError('');
    setWalkResultOpen(false);
    setWalkFilter('');
    setWalkResultScope('public');
    if (walkResultDetailsRef.current) walkResultDetailsRef.current.open = false;
    setWalkIp(initial);
    setWalkDeviceId('');
    setWalkTargetStatus('idle');
    setWalkTargetLabel('');
    setWalkTargetError('');
  }, [initialIp]);

  useEffect(() => {
    if (!selectedDevice) return;
    const ip = String(selectedDevice.ip_address || '').trim();
    if (!ip) return;
    walkRequestSequenceRef.current += 1;
    setWalkTesting(false);
    setWalkIp(ip);
    setWalkDeviceId(selectedDevice.device_id);
    setWalkTargetStatus('matched');
    setWalkTargetLabel(`${selectedDevice.hostname}${ip ? ` (${ip})` : ''}`);
    setWalkTargetError('');
    setWalkResults([]);
    setWalkResultMeta(null);
    setWalkError('');
    setWalkResultOpen(false);
    setWalkFilter('');
    setWalkResultScope('public');
  }, [selectedDevice]);

  useEffect(() => {
    const oid = String(initialWalkOid || '').trim().replace(/^\./, '');
    if (!oid) return;
    setWalkOidInput(oid);
    setWalkResults([]);
    setWalkResultMeta(null);
    setWalkError('');
    setWalkResultOpen(false);
  }, [initialWalkOid]);

  useEffect(() => {
    walkRequestSequenceRef.current += 1;
    setWalkTesting(false);
    setWalkResults([]);
    setWalkResultMeta(null);
    setWalkError('');
    setWalkResultOpen(false);
    setWalkFilter('');
    setWalkResultScope('public');
  }, [walkOidInput]);

  useEffect(() => {
    if (!walkResultOpen) return;
    const previousOverflow = document.body.style.overflow;
    previousWalkFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    document.body.style.overflow = 'hidden';
    const focusFrame = window.requestAnimationFrame(() => walkResultCloseRef.current?.focus());
    const handleDialogKeys = (event: KeyboardEvent) => {
      if (event.key !== 'Tab' || !walkResultDialogRef.current) return;
      const focusable = Array.from(walkResultDialogRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), summary, a[href], [tabindex]:not([tabindex="-1"])',
      )).filter(element => element.offsetParent !== null);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        event.stopPropagation();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        event.stopPropagation();
        first.focus();
      }
    };
    document.addEventListener('keydown', handleDialogKeys, true);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.removeEventListener('keydown', handleDialogKeys, true);
      document.body.style.overflow = previousOverflow;
      if (previousWalkFocusRef.current?.isConnected) previousWalkFocusRef.current.focus();
    };
  }, [walkResultOpen]);

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
    if (showHardwareValidationTab && interfaceConfig?.enabled && activeTab === 'snmpwalk') {
      setActiveTab('validate');
    }
  }, [interfaceConfig?.enabled, showHardwareValidationTab]);

  useEffect(() => {
    if (!showHardwareValidationTab && activeTab === 'validate') setActiveTab('snmpwalk');
  }, [activeTab, showHardwareValidationTab]);

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
    walkRequestSequenceRef.current += 1;
    setWalkTesting(false);
    setWalkDeviceId(device.device_id);
    setWalkIp(ip);
    setWalkTargetStatus('matched');
    setWalkTargetLabel(`${device.hostname}${ip ? ` (${ip})` : ''}`);
    setWalkTargetError('');
    setWalkResults([]);
    setWalkResultMeta(null);
    setWalkError('');
    setWalkResultOpen(false);
    setWalkFilter('');
    setWalkResultScope('public');
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
    walkRequestSequenceRef.current += 1;
    setWalkTesting(false);
    setWalkIp(value);
    setWalkDeviceId('');
    setWalkTargetStatus('idle');
    setWalkTargetLabel('');
    setWalkTargetError('');
    setWalkResults([]);
    setWalkResultMeta(null);
    setWalkError('');
    setWalkResultOpen(false);
    setWalkFilter('');
    setWalkResultScope('public');
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
    const targetOid = walkOidInput.trim().replace(/^\./, '').replace(/\.+$/, '');
    if (!targetOid) {
      showToast(zh ? '请输入要 WALK 的 OID 根节点' : 'Enter a root OID to walk', 'error');
      return;
    }

    const requestId = ++walkRequestSequenceRef.current;
    const requestContext = liveWalkContextRef.current;
    setWalkTesting(true);
    setWalkResults([]);
    setWalkResultMeta(null);
    setWalkError('');
    setWalkResultOpen(false);
    setWalkFilter('');
    setWalkResultScope('public');
    if (walkResultDetailsRef.current) walkResultDetailsRef.current.open = false;
    try {
      const payload: Record<string, any> = {
        version: walkVersion,
        max_rows: walkMaxRows,
        resolve_mib: true,
      };
      if (walkDeviceId) {
        payload.device_id = walkDeviceId;
      } else {
        payload.ip = walkIp.trim();
      }

      const focusedLldpWalk = isLldpRemoteWalk(targetOid);
      const requestOids = focusedLldpWalk ? LLDP_KEY_FIELD_OIDS : [targetOid];
      const settledResponses = await Promise.allSettled(
        requestOids.map(oid => apiRequest<{ success: boolean; data: SnmpWalkResponseData }>(
          '/api/platform-registry/snmp-walk-test',
          {
            method: 'POST',
            body: JSON.stringify({ ...payload, oid }),
          },
        )),
      );
      if (requestId !== walkRequestSequenceRef.current || requestContext !== liveWalkContextRef.current) return;

      const successfulResponses = settledResponses.flatMap(result => result.status === 'fulfilled' ? [result.value.data] : []);
      const failedResponses = settledResponses.filter((result): result is PromiseRejectedResult => result.status === 'rejected');
      if (successfulResponses.length === 0) {
        if (failedResponses.length > 0) throw failedResponses[0].reason;
        throw new Error(zh ? 'SNMP 请求没有返回响应' : 'The SNMP request returned no response');
      }
      const responseRows = successfulResponses.flatMap(data => Array.isArray(data.rows) ? data.rows : []);
      const partialResponse = failedResponses.length > 0 || successfulResponses.some(data => data.status === 'partial_timeout');
      const responseData: SnmpWalkResponseData = {
        ...successfulResponses[0],
        oid: targetOid,
        status: partialResponse ? 'partial' : responseRows.length > 0 ? 'ok' : 'no_data',
        message: partialResponse
          ? (zh ? 'LLDP 部分字段读取失败，当前显示已成功返回的字段。' : 'Some LLDP fields failed; showing the fields that were returned.')
          : responseRows.length > 0
            ? (zh ? 'SNMP WALK 成功' : 'SNMP WALK succeeded')
            : (zh ? 'OID 没有返回数据' : 'The OID returned no data'),
        row_count: responseRows.length,
        truncated: successfulResponses.some(data => data.truncated),
        rows: responseRows,
      };

      if (responseData) {
        const rows = responseData.rows;
        const partialWalk = responseData.status === 'partial' || responseData.status === 'partial_timeout';
        setWalkResults(rows);
        setWalkResultMeta(responseData);
        setWalkResultOpen(true);
        const summaryRows = publicSummaryOnly ? rows.filter(isPublicStandardWalkRow) : rows;
        const summary = buildWalkDiagnosticSummary(summaryRows, targetOid, zh);
        const keyMetricSummary = summary
          .filter(item => publicSummaryOnly
            ? ['system', 'uptime', 'interfaces', 'neighbors'].includes(item.key)
            : ['cpu', 'memory', 'temperature', 'interfaces', 'neighbors'].includes(item.key))
          .slice(0, 3)
        .map(item => {
          if (publicSummaryOnly && item.key === 'neighbors') {
            const names = parseLldpNeighbors(summaryRows, targetOid, zh).map(neighbor => neighbor.name).filter(Boolean);
            return `${zh ? item.label : item.labelEn}: ${names.length ? names.slice(0, 3).join('、') : item.value}`;
          }
          return `${zh ? item.label : item.labelEn}: ${item.value}`;
        });
        showToast(
          rows.length > 0
            ? partialWalk
              ? `${zh ? 'SNMP 部分响应，结果可能不完整' : 'Partial SNMP response; results may be incomplete'}${keyMetricSummary.length ? ` · ${keyMetricSummary.join(' · ')}` : ''}`
              : keyMetricSummary.length > 0
                ? `${zh ? 'SNMP 读取成功' : 'SNMP read succeeded'} · ${keyMetricSummary.join(' · ')}`
                : (zh ? 'SNMP 读取成功，查看页面中的解析结果' : 'SNMP read succeeded; see the parsed result below')
            : (responseData.message || (zh ? 'OID 没有返回数据' : 'The OID returned no data')),
          partialWalk || rows.length === 0 ? 'info' : 'success',
        );
      } else {
        showToast(responseData.message || (zh ? '未返回任何 OID 数据' : 'No rows returned'), 'info');
      }
    } catch (error) {
      if (requestId !== walkRequestSequenceRef.current || requestContext !== liveWalkContextRef.current) return;
      const message = error instanceof ApiError && error.status === 504
        ? zh
          ? '设备在超时时间内没有响应。可能是网络/路由不通、UDP/161 被拦、Community/版本不匹配或设备 ACL；仅凭 SNMP 超时无法区分具体原因。'
          : 'The device did not respond before timeout. Check network/routing, UDP/161, community/version, and device ACLs; an SNMP timeout alone cannot identify which one is wrong.'
        : error instanceof ApiError && error.status === 400 && /community/i.test(error.message)
          ? zh
            ? '该 CMDB 设备未配置 SNMP Community，请先补全设备凭据。'
            : 'No SNMP community is configured for this CMDB device. Add its SNMP credential first.'
          : error instanceof ApiError && error.status === 502
            ? zh
              ? 'SNMP 请求失败，请检查网络/路由、UDP/161、Community、SNMP 版本、OID 和设备 SNMP View/ACL。'
              : 'The SNMP request failed. Check network/routing, UDP/161, community, SNMP version, OID, and device SNMP view/ACL.'
            : error instanceof Error ? error.message : zh ? 'SNMPWALK 探测失败' : 'SNMPWALK failed';
      setWalkError(message);
      setWalkResultOpen(true);
      showToast(
        message,
        'error',
      );
    } finally {
      if (requestId === walkRequestSequenceRef.current && requestContext === liveWalkContextRef.current) setWalkTesting(false);
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
      const readableMetrics = ['cpu', 'memory', 'temperature']
        .map(key => {
          const detail = response.data.metrics?.[key];
          return detail && detail.value !== null && detail.value !== undefined
            ? `${metricLabel(key, zh)} ${formatMetricValue(key, detail, zh)}`
            : '';
        })
        .filter(Boolean);
      showToast(
        isHealthy
          ? zh
            ? `硬件指标读取成功${readableMetrics.length ? ` · ${readableMetrics.join(' · ')}` : ''}`
            : `Hardware metrics read${readableMetrics.length ? ` · ${readableMetrics.join(' · ')}` : ''}`
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

  const copyToClipboard = async (text: string, label = 'OID') => {
    if (!text.trim()) {
      showToast(zh ? '没有可复制的内容' : 'There is nothing to copy', 'info');
      return;
    }

    try {
      if (navigator.clipboard?.writeText && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        throw new Error('Clipboard API unavailable in this context');
      }
    } catch {
      let copied = false;
      let textarea: HTMLTextAreaElement | null = null;
      try {
        textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.setAttribute('readonly', '');
        textarea.setAttribute('aria-hidden', 'true');
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        textarea.style.pointerEvents = 'none';
        textarea.style.left = '-9999px';
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        textarea.setSelectionRange(0, textarea.value.length);
        copied = document.execCommand('copy');
      } catch {
        copied = false;
      } finally {
        textarea?.remove();
      }
      if (!copied) {
        showToast(zh ? '复制失败，请检查浏览器剪贴板权限' : 'Copy failed; check browser clipboard permissions', 'error');
        return;
      }
    }

    showToast(zh ? `已复制 ${label}` : `Copied ${label}`, 'success');
  };

  const visibleWalkResults = useMemo(
    () => !publicSummaryOnly
      ? walkResults
      : walkResultScope === 'public'
        ? walkResults.filter(isPublicStandardWalkRow)
        : walkResults.filter(row => !isPublicStandardWalkRow(row)),
    [publicSummaryOnly, walkResultScope, walkResults],
  );
  const filteredWalkResults = useMemo(() => {
    const term = walkFilter.trim().toLowerCase();
    if (!term) return visibleWalkResults;
    return visibleWalkResults.filter(row => {
      const oidMatch = row.oid.toLowerCase().includes(term);
      const valMatch = String(row.value).toLowerCase().includes(term);
      const nodeMatch = `${row.mib_node || inferMibNodeName(row.oid)} ${row.mib_name || ''} ${row.syntax_type || ''} ${row.description || ''}`
        .toLowerCase()
        .includes(term);
      return oidMatch || valMatch || nodeMatch;
    });
  }, [visibleWalkResults, walkFilter]);

  const walkRootOid = (walkResultMeta?.oid || walkOidInput).trim().replace(/^\./, '');
  const isFocusedLldpWalk = isLldpRemoteWalk(walkRootOid);
  const walkSummary = useMemo(
    () => {
      const rows = publicSummaryOnly ? walkResults.filter(isPublicStandardWalkRow) : walkResults;
      const summaries = buildWalkDiagnosticSummary(rows, walkRootOid, zh);
      return publicSummaryOnly
        ? summaries.filter(item => ['system', 'uptime', 'interfaces'].includes(item.key))
        : summaries;
    },
    [walkResults, walkRootOid, zh, publicSummaryOnly],
  );
  const hasVendorSpecificWalkRows = useMemo(
    () => walkResults.some(isVendorSpecificWalkRow),
    [walkResults],
  );
  const hasNonPublicWalkRows = useMemo(
    () => walkResults.some(row => !isPublicStandardWalkRow(row)),
    [walkResults],
  );
  const lldpNeighbors = useMemo(
    () => parseLldpNeighbors(
      publicSummaryOnly ? walkResults.filter(isPublicStandardWalkRow) : walkResults,
      walkRootOid,
      zh,
    ),
    [walkResults, walkRootOid, publicSummaryOnly, zh],
  );
  const hasLldpRemotePort = lldpNeighbors.some(neighbor => neighbor.remotePort !== '—');
  const hasLldpManagementIp = lldpNeighbors.some(neighbor => neighbor.managementIp !== '—');
  const walkInstanceCount = useMemo(() => {
    const instances = new Set(
      visibleWalkResults
        .map(row => walkInstanceSuffix(walkRootOid, row.oid))
        .filter(Boolean),
    );
    return instances.size;
  }, [visibleWalkResults, walkRootOid]);
  const walkHasTableInstances = walkInstanceCount > 0;

  return (
    <section className="mb-4 rounded-xl border border-[#00bceb]/25 bg-gradient-to-br from-[#00bceb]/[0.055] to-[var(--card-bg)] p-4 shadow-sm dark:from-[#00bceb]/[0.08] dark:to-[var(--card-bg)] md:p-5">
      {/* Top Header & Tab Navigation */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-black/6 pb-3.5 dark:border-white/8">
        {showHardwareValidationTab ? (
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-black/80 dark:text-white/85">
              <Activity size={15} className="text-[#008aad] dark:text-[#00bceb]" />
              {zh ? 'SNMP 实时探测与验证工具箱' : 'SNMP Live Diagnostic & Walk Toolkit'}
            </div>
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
        ) : (
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#00bceb]/12 text-xs font-bold text-[#007391] dark:text-[#00c2e8]">2</span>
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#00bceb]/12 text-[#008aad] dark:text-[#00c2e8]">
              <Activity size={18} />
            </span>
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-black/85 dark:text-white/90">{zh ? '配置并执行 SNMP 探测' : 'Configure and run an SNMP probe'}</h2>
              <p className="mt-0.5 text-[11px] leading-4 text-black/50 dark:text-white/50">
                {zh ? '使用快捷 OID 或输入目标 OID，再执行只读 WALK。' : 'Choose a quick OID or enter one, then run a read-only WALK.'}
              </p>
            </div>
          </div>
        )}

        {showHardwareValidationTab && activeTab === 'validate' && (
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
      <div className={`mt-3 grid gap-2.5 sm:grid-cols-2 ${showCandidateSelector && candidateDevices.length > 0 ? 'lg:grid-cols-3' : 'lg:grid-cols-[minmax(0,2fr)_minmax(220px,1fr)]'}`}>
        {showCandidateSelector && candidateDevices.length > 0 && (
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
                disabled={walkTesting}
            onChange={event => {
              walkRequestSequenceRef.current += 1;
              setWalkTesting(false);
              setWalkResults([]);
              setWalkResultMeta(null);
              setWalkError('');
              setWalkResultOpen(false);
              setWalkFilter('');
              setWalkVersion(event.target.value as SnmpWalkVersion);
            }}
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
              {visibleQuickOids.map(item => (
                <button
                  key={item.oid}
                  type="button"
                  onClick={() => setWalkOidInput(item.oid)}
                  className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[10px] transition-all ${
                    walkOidInput === item.oid
                      ? 'border-[#00a9ce] bg-[#00a9ce]/15 font-semibold text-[#007391] dark:text-[#00c2e8]'
                      : 'border-black/8 bg-white/50 text-black/65 hover:border-[#00a9ce]/40 hover:bg-white dark:border-white/10 dark:bg-white/[.03] dark:text-white/65 dark:hover:bg-white/[.08]'
                  }`}
                  title={`${zh ? item.desc : item.descEn || item.desc} (${item.oid})`}
                >
                  <Sparkles size={11} className="text-[#00a9ce]" />
                  <span>{zh ? item.label : item.labelEn || item.label}</span>
                </button>
              ))}
            </div>
          </div>

          {/* OID Input & Walk Execution Row */}
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setOidPickerOpen(true)}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-[#00bceb]/35 bg-[#00bceb]/[.07] px-2.5 py-1.5 text-xs font-semibold text-[#007391] transition hover:bg-[#00bceb]/15 dark:text-[#00c2e8]"
            >
              <Database size={13} />
              {zh ? '从 MIB 库选 OID' : 'Pick OID from MIB'}
            </button>
            <div className="min-w-[280px] flex-1">
              <input
                value={walkOidInput}
                disabled={walkTesting}
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
              {!hideMaxRowsSelector && (
                <select
                  aria-label={zh ? '最大获取行数' : 'Max rows'}
                  value={walkMaxRows}
                  disabled={walkTesting}
                  onChange={e => setWalkMaxRows(Number(e.target.value))}
                  className="rounded-md border border-black/8 bg-transparent px-2 py-1.5 text-xs outline-none dark:border-white/10"
                >
                  <option value={50}>50 {zh ? '行' : 'rows'}</option>
                  <option value={100}>100 {zh ? '行' : 'rows'}</option>
                  <option value={200}>200 {zh ? '行' : 'rows'}</option>
                  <option value={500}>500 {zh ? '行' : 'rows'}</option>
                </select>
              )}

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

          {(walkResultMeta || walkError) && !walkResultOpen && (
            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => setWalkResultOpen(true)}
                className="rounded-md border border-[#00bceb]/30 bg-[#00bceb]/[.06] px-2.5 py-1.5 text-[11px] font-medium text-[#007391] hover:bg-[#00bceb]/15 dark:text-[#00c2e8]"
              >
                {zh ? '查看上次探测结果' : 'View last result'}
              </button>
            </div>
          )}

          {publicSummaryOnly && !walkTesting && !walkResultMeta && !walkError && (
            <div className="flex min-h-[118px] items-center gap-3 rounded-xl border border-dashed border-[#00bceb]/25 bg-white/55 px-4 py-4 dark:bg-white/[.025]">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#00bceb]/10 text-[#008aad] dark:text-[#00c2e8]">
                <Activity size={18} />
              </span>
              <div className="min-w-0">
                <div className="text-xs font-semibold text-black/70 dark:text-white/80">{zh ? '等待探测结果' : 'Ready for a probe'}</div>
                <p className="mt-1 text-[11px] leading-5 text-black/45 dark:text-white/45">
                  {zh ? '执行 SNMP WALK 后会打开结果弹窗，集中显示设备信息、接口或 LLDP 解析和 OID 明细。' : 'Run an SNMP WALK to open the results dialog with device details, interface or LLDP summaries, and OID data.'}
                </p>
              </div>
            </div>
          )}

          {/* SNMP Walk result dialog */}
          {walkResultOpen && (
            <div
              className="fixed inset-0 z-[170] flex items-center justify-center overscroll-contain bg-slate-950/55 p-3 backdrop-blur-[2px] sm:p-5"
              onMouseDown={event => {
                if (event.target === event.currentTarget) setWalkResultOpen(false);
              }}
            >
              <div
                ref={walkResultDialogRef}
                role="dialog"
                aria-modal="true"
                aria-labelledby="snmp-walk-result-title"
                className="flex max-h-[92vh] w-full max-w-[1480px] flex-col overflow-hidden rounded-xl border border-black/10 bg-[var(--card-bg)] shadow-2xl dark:border-white/10"
                onMouseDown={event => event.stopPropagation()}
              >
                <div className="flex items-center justify-between gap-3 border-b border-black/8 px-4 py-3 dark:border-white/8 sm:px-5">
                  <div className="flex min-w-0 items-center gap-3">
                    <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${walkError ? 'bg-red-500/10 text-red-600 dark:text-red-300' : walkResults.length > 0 && walkResultMeta?.status !== 'partial_timeout' ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300' : 'bg-amber-500/10 text-amber-700 dark:text-amber-300'}`}>
                      {walkError ? <AlertTriangle size={16} /> : walkResults.length > 0 && walkResultMeta?.status !== 'partial_timeout' ? <CheckCircle2 size={16} /> : <Eye size={16} />}
                    </div>
                    <div className="min-w-0">
                      <h2 id="snmp-walk-result-title" className="truncate text-sm font-semibold text-black/85 dark:text-white/90">
                        {walkError
                          ? (zh ? 'SNMP 探测失败' : 'SNMP probe failed')
                          : walkResultMeta?.status === 'partial_timeout'
                            ? (zh ? 'SNMP 超时，以下为部分结果' : 'SNMP timed out; showing partial results')
                            : walkResults.length > 0
                              ? (zh ? 'SNMP 探测结果' : 'SNMP diagnostic result')
                              : (zh ? 'OID 无返回数据' : 'No OID data returned')}
                      </h2>
                      <p className="mt-0.5 truncate font-mono text-[10px] text-black/45 dark:text-white/45">
                        {walkResultMeta ? `${walkResultMeta.host} · ${walkResultMeta.version} · ${walkResultMeta.oid}` : `${walkIp || '—'} · SNMPv${walkVersion} · ${walkOidInput}`}
                      </p>
                    </div>
                  </div>
                  {publicSummaryOnly && hasNonPublicWalkRows && (
                    <button
                      type="button"
                      onClick={() => {
                        setWalkResultScope('private');
                        if (walkResultDetailsRef.current) {
                          walkResultDetailsRef.current.open = true;
                          walkResultDetailsRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                        }
                      }}
                      className="inline-flex shrink-0 rounded-full bg-amber-500/10 px-2 py-1 text-[9px] font-medium text-amber-800 hover:bg-amber-500/15 sm:text-[10px] dark:text-amber-200"
                    >
                      {zh
                        ? hasVendorSpecificWalkRows ? '发现厂商私有 OID · 查看' : '发现其他 OID · 查看'
                        : hasVendorSpecificWalkRows ? 'Vendor OIDs · view' : 'Other OIDs · view'}
                    </button>
                  )}
                  <button
                    ref={walkResultCloseRef}
                    type="button"
                    onClick={() => setWalkResultOpen(false)}
                    aria-label={zh ? '关闭探测结果' : 'Close diagnostic result'}
                    title={zh ? '关闭探测结果' : 'Close diagnostic result'}
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-black/45 hover:bg-black/[.05] hover:text-black/80 focus:outline-none focus:ring-2 focus:ring-[#00bceb]/50 dark:text-white/50 dark:hover:bg-white/[.08] dark:hover:text-white"
                  >
                    <X size={17} />
                  </button>
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-3 sm:p-4">
          {/* Results table & Actions */}
          {walkError && (
            <div className="mt-3 rounded-xl border border-red-500/25 bg-red-500/[.05] p-3 text-xs text-red-800 dark:text-red-200">
              <div className="flex items-center gap-1.5 font-semibold"><AlertTriangle size={14} />{zh ? 'SNMP 请求失败' : 'SNMP request failed'}</div>
              <div className="mt-1 break-all">{walkError}</div>
              <div className="mt-1 text-[10px] opacity-80">{zh ? `目标 ${walkIp || '—'} · OID ${walkOidInput}` : `Target ${walkIp || '—'} · OID ${walkOidInput}`}</div>
              <div className="mt-1 text-[10px] opacity-80">{zh ? '先检查设备管理 IP、SNMP 版本与凭据，再核对设备 ACL、路由和 UDP/161 连通性。' : 'Check the management IP, SNMP version and credentials, then verify device ACLs, routing, and UDP/161 reachability.'}</div>
            </div>
          )}
          {walkResultMeta && walkResults.length === 0 && !walkError && (
            <div className="mt-3 rounded-xl border border-amber-500/25 bg-amber-500/[.06] p-3 text-xs text-amber-900 dark:text-amber-100">
              <div className="flex items-center gap-1.5 font-semibold"><AlertTriangle size={14} />{zh ? '请求完成，但该 OID 没有返回数据' : 'Request completed, but this OID returned no data'}</div>
              <div className="mt-1 break-all font-mono text-[10px]">{walkResultMeta.host} · {walkResultMeta.version} · OID {walkResultMeta.oid}</div>
              <div className="mt-1">{zh ? '这不等同于设备离线。请先用“系统基本信息 (MIB-2)”验证基础 SNMP 读取；若它有数据，再检查 IF-MIB、LLDP 或厂商私有 OID 是否被设备视图/权限开放。' : 'This does not by itself mean the device is offline. Start with System (MIB-2); if it returns data, check whether the device view/permissions expose IF-MIB, LLDP, or vendor-private OIDs.'}</div>
              <div className="mt-1 text-[10px] opacity-80">{zh ? '如果基础 OID 有返回但 Grafana 仍无数据，再检查 vmagent 抓取目标、VictoriaMetrics 中的指标及 Dashboard 查询条件。' : 'If basic OIDs return data but Grafana remains empty, inspect vmagent targets, stored VictoriaMetrics series, and dashboard query filters.'}</div>
            </div>
          )}
          {walkResults.length > 0 && (
            <div className="rounded-xl border border-black/8 bg-white/75 p-3 shadow-sm dark:border-white/10 dark:bg-white/[.04]">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-black/6 pb-2.5 dark:border-white/8">
                <div>
                  <div className="text-xs font-semibold text-black/80 dark:text-white/85">{zh ? '解析后的设备读数' : 'Interpreted device readings'}</div>
                  <div className="mt-0.5 text-[10px] text-black/45 dark:text-white/45">{walkResultMeta?.host || walkIp} · {walkResultMeta?.version || `SNMPv${walkVersion}`}</div>
                </div>
                <div className="flex items-center gap-2">
                  {walkResultMeta?.truncated && (
                    <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-medium text-amber-700 dark:text-amber-300">
                      {zh ? '部分结果已截断' : 'Some results were truncated'}
                    </span>
                  )}
                  {(walkResultMeta?.status === 'partial_timeout' || walkResultMeta?.status === 'partial') && (
                    <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-medium text-amber-700 dark:text-amber-300">
                      {zh ? '部分字段未返回' : 'Some fields were not returned'}
                    </span>
                  )}
                  {showHardwareValidationTab && activeTab === 'snmpwalk' && (
                    <button
                      type="button"
                      onClick={() => {
                        setWalkResultOpen(false);
                        setActiveTab('validate');
                      }}
                      className="rounded-md bg-[#00bceb]/10 px-2.5 py-1.5 text-[10px] font-semibold text-[#007391] hover:bg-[#00bceb]/20 dark:text-[#00c2e8]"
                    >
                  {zh ? '查看 CPU / 内存指标' : 'View CPU / memory metrics'}
                    </button>
                  )}
                </div>
              </div>

              {publicSummaryOnly && lldpNeighbors.length > 0 && (
                <section className="mt-3 overflow-hidden rounded-lg border border-emerald-500/20 bg-emerald-500/[.025]">
                  <div className="flex items-center gap-2 border-b border-emerald-500/10 px-3 py-2.5">
                    <Activity size={14} className="text-emerald-700 dark:text-emerald-300" />
                    <div>
                      <h3 className="text-xs font-semibold text-black/80 dark:text-white/85">{zh ? 'LLDP 邻居解析' : 'Parsed LLDP neighbors'}</h3>
                    <p className="mt-0.5 text-[10px] text-black/45 dark:text-white/45">{zh ? '按端口索引关联本端端口、邻居名称、对端端口和管理地址。' : 'Shows local port, neighbor name, remote port, and management address by LLDP index.'}</p>
                    </div>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="nx-data-table nx-data-table--compact min-w-[420px] text-left">
                      <thead>
                        <tr>
                          <th>{zh ? '邻居设备' : 'Neighbor'}</th>
                          <th>{zh ? '本端端口' : 'Local port'}</th>
                          {hasLldpRemotePort && <th>{zh ? '对端端口' : 'Remote port'}</th>}
                          {hasLldpManagementIp && <th>{zh ? '管理地址' : 'Management IP'}</th>}
                        </tr>
                      </thead>
                      <tbody>
                        {lldpNeighbors.map(neighbor => (
                          <tr key={neighbor.key}>
                            <td className="font-medium text-black/80 dark:text-white/85">{neighbor.name}</td>
                            <td>{neighbor.localPort}</td>
                            {hasLldpRemotePort && <td>{neighbor.remotePort}</td>}
                            {hasLldpManagementIp && <td className="font-mono">{neighbor.managementIp}</td>}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}

              {walkSummary.length > 0 ? (
                <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                  {walkSummary.map(item => {
                    const Icon = item.key === 'cpu' ? Cpu
                      : item.key === 'memory' ? HardDrive
                        : item.key === 'temperature' ? Flame
                          : item.key === 'interfaces' ? Server
                            : item.key === 'neighbors' ? Activity
                              : Activity;
                    return (
                      <div key={`${item.key}-${item.label}`} className="min-w-0 rounded-lg border border-black/7 bg-white/85 p-3 dark:border-white/8 dark:bg-white/[.04]">
                        <div className="flex items-center gap-1.5 text-[11px] font-medium text-black/50 dark:text-white/50">
                          <Icon size={13} className="text-[#008aad] dark:text-[#00bceb]" />
                          {zh ? item.label : item.labelEn}
                        </div>
                        <div className="mt-1.5 break-words text-lg font-semibold leading-6 text-black/85 dark:text-white/90" title={item.detail}>{item.value}</div>
                        {item.detail && <div className="mt-1 line-clamp-2 text-[10px] leading-4 text-black/45 dark:text-white/45" title={item.detail}>{item.detail}</div>}
                      </div>
                    );
                  })}
                </div>
              ) : publicSummaryOnly && lldpNeighbors.length > 0 ? null : (
                <div className="mt-3 rounded-lg border border-sky-500/15 bg-sky-500/[.04] px-3 py-2.5 text-[11px] leading-5 text-sky-900/80 dark:text-sky-100/80">
                  {zh
                    ? publicSummaryOnly
                      ? hasVendorSpecificWalkRows
                        ? '已发现厂商私有 OID；此处摘要只显示公共标准信息。展开明细并切换到“厂商私有”可查看对应返回值。'
                        : hasNonPublicWalkRows
                          ? '已发现未分类的 OID；此处摘要只显示公共标准信息。展开明细并切换到“厂商私有 / 其他”可查看返回值。'
                          : 'SNMP 已返回数据，但未识别到常用系统、接口或 LLDP 字段。展开下方 OID 明细可检查完整返回值。'
                      : 'SNMP 已返回数据，但当前 MIB 定义还不能把它识别成常用指标。可以展开下方原始 OID 明细继续检查。'
                    : publicSummaryOnly
                      ? hasVendorSpecificWalkRows
                        ? 'Vendor-private OIDs were found. The summary shows only standard information; expand the details and choose Vendor-private to inspect them.'
                        : hasNonPublicWalkRows
                          ? 'Unclassified OIDs were found. The summary shows standard information; expand the details and choose Vendor-private / other to inspect them.'
                          : 'SNMP returned values, but no common system, interface, or LLDP fields were recognized. Expand the OID details to inspect the values.'
                      : 'SNMP returned values, but the current MIB definitions did not map them to common fields. Expand the raw OID details to inspect further.'}
                </div>
              )}

              <details ref={walkResultDetailsRef} className="mt-3 rounded-lg border border-black/7 dark:border-white/8">
                <summary className="cursor-pointer select-none px-3 py-2 text-[11px] font-medium text-black/60 hover:bg-black/[.02] dark:text-white/60 dark:hover:bg-white/[.03]">
                  {zh ? (publicSummaryOnly ? '查看公共 / 厂商私有 OID 明细' : '查看原始 OID 与实例明细') : (publicSummaryOnly ? 'Show public / vendor-private OID details' : 'Show raw OIDs and instances')}
                </summary>
                <div className="border-t border-black/6 p-3 dark:border-white/8">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-black/6 pb-2.5 dark:border-white/8">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-black/80 dark:text-white/85">
                    {zh ? (publicSummaryOnly ? (walkResultScope === 'public' ? '公共标准 SNMP 值' : '厂商私有 / 其他 OID') : '原始 SNMP 返回值') : (publicSummaryOnly ? (walkResultScope === 'public' ? 'Public standard SNMP values' : 'Vendor-private / other OIDs') : 'Raw SNMP values')}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  {publicSummaryOnly && (
                    <div className="inline-flex rounded-md border border-black/10 bg-black/[.02] p-0.5 dark:border-white/10 dark:bg-white/[.03]" role="tablist" aria-label={zh ? '返回值分类' : 'Returned OID category'}>
                      <button type="button" role="tab" aria-selected={walkResultScope === 'public'} onClick={() => setWalkResultScope('public')} className={`rounded px-2 py-1 text-[10px] font-medium ${walkResultScope === 'public' ? 'bg-white text-[#007391] shadow-sm dark:bg-slate-800 dark:text-[#00c2e8]' : 'text-black/50 dark:text-white/50'}`}>
                        {zh ? '公共标准' : 'Public'}
                      </button>
                      <button type="button" role="tab" aria-selected={walkResultScope === 'private'} onClick={() => setWalkResultScope('private')} className={`inline-flex items-center gap-1 rounded px-2 py-1 text-[10px] font-medium ${walkResultScope === 'private' ? 'bg-white text-amber-800 shadow-sm dark:bg-slate-800 dark:text-amber-200' : 'text-black/50 dark:text-white/50'}`}>
                        {zh ? '厂商私有 / 其他' : 'Vendor-private / other'}
                        {hasNonPublicWalkRows && <span className="h-1.5 w-1.5 rounded-full bg-amber-500" aria-label={zh ? '有数据' : 'Has results'} />}
                      </button>
                    </div>
                  )}
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
                      const text = walkResults.map(r => `${r.oid}${r.mib_node ? ` (${r.mib_node})` : ''} = ${r.value}${r.syntax_type ? ` [${r.syntax_type}]` : ''}`).join('\n');
                      copyToClipboard(text, zh ? '全部结果' : 'all WALK results');
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
                    {isFocusedLldpWalk
                      ? zh
                        ? 'LLDP 精简探测只读取邻居名称、本端和对端端口、管理地址，跳过二进制标识、能力位和系统描述等低价值字段。'
                        : 'The focused LLDP probe reads neighbor names, local and remote ports, and management addresses, skipping binary IDs, capability flags, and long system descriptions.'
                      : walkHasTableInstances
                      ? zh
                        ? `根 OID ${walkRootOid}（${inferMibNodeName(walkRootOid) || '表列'}）下的后缀是实例索引；不同索引对应不同板卡、模块或端口。相同数值也可能是不同实体的有效读数。`
                        : `The suffix under ${walkRootOid} is an instance index; different indices may represent separate boards, modules, or ports. Equal values can still belong to different entities.`
                    : zh
                        ? `根 OID：${walkRootOid}。需要单个值时，请使用具体实例 OID。`
                        : `Root OID: ${walkRootOid}. Use a concrete instance OID when you need one value.`}
                </div>
              </div>

              {/* Table */}
              <div className="mt-2 max-h-[360px] overflow-y-auto rounded-lg border border-black/6 bg-white/40 dark:border-white/8 dark:bg-white/[.02]">
                <table className="nx-data-table nx-data-table--compact">
                  <thead className="sticky top-0 z-10 bg-[var(--card-bg)] text-[10px] font-medium text-black/45 dark:text-white/45">
                    <tr>
                      <th className="px-3 py-2">OID 路径 / 实例索引 / 推断含义</th>
                      <th className="px-3 py-2">返回值 (Value)</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-black/5 font-mono dark:divide-white/5">
                    {filteredWalkResults.length === 0 && (
                      <tr><td colSpan={2} className="px-3 py-8 text-center font-sans text-xs text-black/45 dark:text-white/45">
                        {zh
                          ? publicSummaryOnly
                            ? walkResultScope === 'private' ? '当前没有匹配的厂商私有 OID 返回值。' : '当前没有匹配的公共标准 OID 返回值。'
                            : '当前没有匹配的原始 SNMP 返回值。'
                          : publicSummaryOnly
                            ? walkResultScope === 'private' ? 'No vendor-private OID values match this filter.' : 'No public standard OID values match this filter.'
                            : 'No raw SNMP values match this filter.'}
                      </td></tr>
                    )}
                    {filteredWalkResults.map((row, idx) => {
                      const inferred = isPublicStandardWalkRow(row)
                        ? inferMibNodeName(row.oid) || row.mib_node
                        : row.mib_node || inferMibNodeName(row.oid);
                      const instance = row.instance_suffix ?? walkInstanceSuffix(walkRootOid, row.oid);
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
                                🏷️ {inferred}{row.mib_name ? ` · ${row.mib_name}` : ''}{publicSummaryOnly && walkResultScope === 'private' ? ` · ${row.mib_vendor || (isVendorSpecificWalkRow(row) ? (zh ? '厂商私有' : 'Vendor-specific') : (zh ? '未分类' : 'Unclassified'))}` : ''}
                              </div>
                            )}
                            {row.syntax_type && (!publicSummaryOnly || walkResultScope === 'private') && (
                              <div className="mt-0.5 font-sans text-[10px] text-black/55 dark:text-white/55">
                                {zh ? '类型' : 'Type'}: {row.syntax_type}
                                {row.access_type ? ` · ${row.access_type}` : ''}
                              </div>
                            )}
                            <div className="mt-0.5 font-sans text-[10px] text-black/45 dark:text-white/45">
                              {instance ? `${zh ? '实例索引' : 'Instance'}: ${instance}` : (zh ? '标量/根节点' : 'Scalar/root')}
                            </div>
                            {row.description && (!publicSummaryOnly || walkResultScope === 'private') && (
                              <div className="mt-0.5 max-w-[620px] font-sans text-[10px] leading-4 text-black/45 dark:text-white/45">
                                {row.description}
                              </div>
                            )}
                          </td>
                          <td className="max-w-[320px] break-all px-3 py-2 font-sans font-medium text-black/75 dark:text-white/80">
                            {String(row.value)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
                </div>
              </details>
            </div>
          )}
                </div>
              </div>
            </div>
      )}
        </div>
      )}

      {/* ───────────────────────────────────────────────────────────── */}
      {/* TAB 2: Hardware & Interface Probing Results */}
      {/* ───────────────────────────────────────────────────────────── */}
      {showHardwareValidationTab && activeTab === 'validate' && (
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

      <OidPickerModal
        open={oidPickerOpen}
        onClose={() => setOidPickerOpen(false)}
        onSelect={(node: MibNodeItem) => {
          setWalkOidInput(node.oid);
          setOidPickerOpen(false);
          showToast(
            zh ? `已选择 ${node.node_name} (${node.oid})` : `Selected ${node.node_name} (${node.oid})`,
            'success',
          );
        }}
        language={zh ? 'zh' : 'en'}
      />
    </section>
  );
};

export default LiveWalkInspector;
