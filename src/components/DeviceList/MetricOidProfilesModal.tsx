import React, { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Cpu,
  Database,
  GitBranch,
  Plus,
  RefreshCw,
  Save,
  Search,
  Settings2,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';
import { apiRequest } from '../../api/http';
import { ALL_VENDOR_NAMES, NETWORK_VENDOR_GROUPS } from '../../pages/AssetManagement/constants';
import Pagination from '../Pagination';
import OidPickerModal, { MibNodeItem } from '../SnmpMib/OidPickerModal';
import MibUploadModal from '../SnmpMib/MibUploadModal';
import PresetProfilesModal, { ModelPresetItem } from '../SnmpMib/PresetProfilesModal';

type MetricMode = 'direct_percent' | 'direct_value' | 'used_total_percent' | 'used_free_percent' | 'counter_rate_percent' | 'status_code';
type CounterBits = '' | '32' | '64';
type InterfaceCounterMode = 'auto' | '32' | '64';
type Aggregation = 'first' | 'average' | 'max' | 'min' | 'sum';

interface InterfaceOidConfig {
  enabled: boolean;
  if_name_oid: string;
  if_descr_oid: string;
  if_alias_oid: string;
  if_oper_status_oid: string;
  if_high_speed_oid: string;
  if_speed_oid: string;
  if_last_change_oid: string;
  if_in_octets_oid: string;
  if_out_octets_oid: string;
  if_hc_in_octets_oid: string;
  if_hc_out_octets_oid: string;
  if_in_errors_oid: string;
  if_out_errors_oid: string;
  if_in_discards_oid: string;
  if_out_discards_oid: string;
  if_in_ucast_oid: string;
  if_out_ucast_oid: string;
  counter_mode: InterfaceCounterMode;
}

interface MetricDefinition {
  mode: MetricMode;
  oid: string;
  used_oid: string;
  total_oid: string;
  free_oid: string;
  capacity_oid: string;
  counter_bits: CounterBits;
  counter_unit: 'bits' | 'octets';
  status_ok_values: string;
  status_warning_values: string;
  status_fail_values: string;
  unit: string;
  aggregation: Aggregation;
  selector: string;
  scale: string;
  offset: string;
}

interface MetricRow {
  key: string;
  definition: MetricDefinition;
}

interface MetricOidProfile {
  profile_id: string | null;
  vendor: string;
  model: string;
  cpu_oid: string;
  memory_oid: string;
  cpu_config?: Record<string, unknown>;
  memory_config?: Record<string, unknown>;
  metric_definitions?: Record<string, Record<string, unknown>>;
  metric_keys?: string[];
  configured: boolean;
  verification_status: 'verified' | 'failed' | 'unverified' | string;
  device_count: number;
  matched_device_count?: number;
  profile_applied_device_count?: number;
  blocked_device_count?: number;
  collector_status?: 'active' | 'blocked_unverified' | 'blocked_failed' | 'no_matching_device' | 'builtin_only' | string;
  interface_config?: Partial<InterfaceOidConfig>;
  interface_configured?: boolean;
  interface_verification_status?: 'verified' | 'failed' | 'unverified' | string;
  interface_collector_status?: string;
  sample_device_id?: string | null;
  platforms: string[];
}

interface MetricProfileListResponse {
  success: boolean;
  data: MetricOidProfile[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

interface MetricProfileMapping {
  collector_status: string;
  matched_device_count: number;
  profile_applied_device_count: number;
  blocked_device_count: number;
  metric_keys?: string[];
  interface_configured?: boolean;
  interface_verification_status?: string;
  interface_collector_status?: string;
  sample_device_id?: string | null;
}

interface ProfileForm {
  vendor: string;
  model: string;
  metrics: MetricRow[];
  interfaceConfig: InterfaceOidConfig;
}

interface InterfaceTestResult {
  passed?: boolean;
  status?: string;
  message?: string;
  counter_mode?: string;
  selected_counter_bits?: number | null;
  interfaces?: number;
  counter_supported?: number;
  checks?: Record<string, { oid?: string; passed?: boolean; rows?: number; message?: string; counter_bits?: number }>;
}

type SnmpWalkVersion = '1' | '2c';

interface SnmpWalkResult {
  host: string;
  oid: string;
  version: SnmpWalkVersion;
  port: number;
  status: 'ok' | 'no_data' | string;
  message: string;
  row_count: number;
  truncated: boolean;
  rows: Array<{ oid: string; value: string }>;
}

type SnmpWalkTargetStatus = 'idle' | 'loading' | 'matched' | 'multiple' | 'none' | 'error';

interface MetricCatalogEntry {
  key: string;
  labelZh: string;
  labelEn: string;
  defaultMode: MetricMode;
  output: 'percent' | 'status' | 'value';
  defaultUnit: string;
}

const METRIC_CATALOG: MetricCatalogEntry[] = [
  { key: 'cpu', labelZh: 'CPU', labelEn: 'CPU', defaultMode: 'direct_percent', output: 'percent', defaultUnit: '%' },
  { key: 'memory', labelZh: '内存', labelEn: 'Memory', defaultMode: 'direct_percent', output: 'percent', defaultUnit: '%' },
  { key: 'temperature', labelZh: '温度', labelEn: 'Temperature', defaultMode: 'direct_value', output: 'value', defaultUnit: '°C' },
  { key: 'fan', labelZh: '风扇状态', labelEn: 'Fan status', defaultMode: 'status_code', output: 'status', defaultUnit: 'bool' },
  { key: 'power_supply', labelZh: '电源状态', labelEn: 'Power supply status', defaultMode: 'status_code', output: 'status', defaultUnit: 'bool' },
  { key: 'storage', labelZh: '存储使用率', labelEn: 'Storage usage', defaultMode: 'used_total_percent', output: 'percent', defaultUnit: '%' },
  { key: 'voltage', labelZh: '电压', labelEn: 'Voltage', defaultMode: 'direct_value', output: 'value', defaultUnit: 'V' },
  { key: 'power', labelZh: '功耗', labelEn: 'Power consumption', defaultMode: 'direct_value', output: 'value', defaultUnit: 'W' },
];

const EMPTY_DEFINITION: MetricDefinition = {
  mode: 'direct_percent',
  oid: '',
  used_oid: '',
  total_oid: '',
  free_oid: '',
  capacity_oid: '',
  counter_bits: '',
  counter_unit: 'bits',
  status_ok_values: '',
  status_warning_values: '',
  status_fail_values: '',
  unit: '%',
  aggregation: 'average',
  selector: '',
  scale: '1',
  offset: '0',
};

const DEFAULT_INTERFACE_CONFIG: InterfaceOidConfig = {
  enabled: false,
  if_name_oid: '1.3.6.1.2.1.31.1.1.1.1',
  if_descr_oid: '1.3.6.1.2.1.2.2.1.2',
  if_alias_oid: '1.3.6.1.2.1.31.1.1.1.18',
  if_oper_status_oid: '1.3.6.1.2.1.2.2.1.8',
  if_high_speed_oid: '1.3.6.1.2.1.31.1.1.1.15',
  if_speed_oid: '1.3.6.1.2.1.2.2.1.5',
  if_last_change_oid: '1.3.6.1.2.1.2.2.1.9',
  if_in_octets_oid: '1.3.6.1.2.1.2.2.1.10',
  if_out_octets_oid: '1.3.6.1.2.1.2.2.1.16',
  if_hc_in_octets_oid: '1.3.6.1.2.1.31.1.1.1.6',
  if_hc_out_octets_oid: '1.3.6.1.2.1.31.1.1.1.10',
  if_in_errors_oid: '1.3.6.1.2.1.2.2.1.14',
  if_out_errors_oid: '1.3.6.1.2.1.2.2.1.20',
  if_in_discards_oid: '1.3.6.1.2.1.2.2.1.13',
  if_out_discards_oid: '1.3.6.1.2.1.2.2.1.19',
  if_in_ucast_oid: '1.3.6.1.2.1.2.2.1.11',
  if_out_ucast_oid: '1.3.6.1.2.1.2.2.1.17',
  counter_mode: 'auto',
};

const INTERFACE_OID_FIELDS: Array<{ key: Exclude<keyof InterfaceOidConfig, 'enabled' | 'counter_mode'>; labelZh: string; labelEn: string }> = [
  { key: 'if_name_oid', labelZh: '接口名称', labelEn: 'ifName' },
  { key: 'if_descr_oid', labelZh: '接口描述', labelEn: 'ifDescr' },
  { key: 'if_alias_oid', labelZh: '接口别名', labelEn: 'ifAlias' },
  { key: 'if_oper_status_oid', labelZh: '运行状态', labelEn: 'ifOperStatus' },
  { key: 'if_high_speed_oid', labelZh: '高速速率', labelEn: 'ifHighSpeed' },
  { key: 'if_speed_oid', labelZh: '接口速率', labelEn: 'ifSpeed' },
  { key: 'if_last_change_oid', labelZh: '最后变更', labelEn: 'ifLastChange' },
  { key: 'if_in_octets_oid', labelZh: '入方向 32 位', labelEn: 'ifInOctets (32)' },
  { key: 'if_out_octets_oid', labelZh: '出方向 32 位', labelEn: 'ifOutOctets (32)' },
  { key: 'if_hc_in_octets_oid', labelZh: '入方向 64 位', labelEn: 'ifHCInOctets (64)' },
  { key: 'if_hc_out_octets_oid', labelZh: '出方向 64 位', labelEn: 'ifHCOutOctets (64)' },
  { key: 'if_in_errors_oid', labelZh: '入方向错误', labelEn: 'ifInErrors' },
  { key: 'if_out_errors_oid', labelZh: '出方向错误', labelEn: 'ifOutErrors' },
  { key: 'if_in_discards_oid', labelZh: '入方向丢弃', labelEn: 'ifInDiscards' },
  { key: 'if_out_discards_oid', labelZh: '出方向丢弃', labelEn: 'ifOutDiscards' },
  { key: 'if_in_ucast_oid', labelZh: '入方向单播包', labelEn: 'ifInUcastPkts' },
  { key: 'if_out_ucast_oid', labelZh: '出方向单播包', labelEn: 'ifOutUcastPkts' },
];

const AGGREGATIONS: Aggregation[] = ['average', 'first', 'max', 'min', 'sum'];
const METRIC_MODES: MetricMode[] = ['direct_percent', 'direct_value', 'used_total_percent', 'used_free_percent', 'counter_rate_percent', 'status_code'];
const KNOWN_VENDOR_SET = new Set<string>(ALL_VENDOR_NAMES as readonly string[]);

interface Props {
  open: boolean;
  onClose: () => void;
  onChanged?: () => void;
  language: string;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
  embedded?: boolean;
}

const catalogEntry = (key: string) => METRIC_CATALOG.find(item => item.key === key);

const metricLabel = (key: string, zh: boolean) => {
  const item = catalogEntry(key);
  return item ? (zh ? item.labelZh : item.labelEn) : key;
};

const modeLabel = (mode: MetricMode, zh: boolean) => {
  if (mode === 'direct_value') return zh ? '直接数值' : 'Direct value';
  if (mode === 'used_total_percent') return zh ? '已用 / 总量' : 'Used / total';
  if (mode === 'used_free_percent') return zh ? '已用 /（已用 + 空闲）' : 'Used / (used + free)';
  if (mode === 'counter_rate_percent') return zh ? '计数器速率 / 容量' : 'Counter rate / capacity';
  if (mode === 'status_code') return zh ? '状态码 → 布尔值' : 'Status code → boolean';
  return zh ? '直接百分比（Gauge）' : 'Direct percentage (Gauge)';
};

const allowedModes = (key: string): MetricMode[] => {
  const item = catalogEntry(key);
  if (!item) return METRIC_MODES;
  if (item.output === 'status') return ['status_code'];
  if (item.output === 'value') return ['direct_value'];
  return ['direct_percent', 'used_total_percent', 'used_free_percent', 'counter_rate_percent'];
};

const createDefinition = (key: string): MetricDefinition => {
  const item = catalogEntry(key);
  const mode = item?.defaultMode || 'direct_value';
  return {
    ...EMPTY_DEFINITION,
    mode,
    unit: item?.defaultUnit || (mode === 'status_code' ? 'bool' : ''),
    status_ok_values: mode === 'status_code' ? '1' : '',
    status_warning_values: '',
    status_fail_values: mode === 'status_code' ? '2,3' : '',
  };
};

const textValue = (value: unknown, fallback = '') => {
  if (Array.isArray(value)) return value.join(',');
  return value === undefined || value === null ? fallback : String(value);
};

const definitionFromProfile = (
  key: string,
  config: Record<string, unknown> | undefined,
  legacyOid = '',
): MetricDefinition => {
  const base = createDefinition(key);
  const raw = config || {};
  const requestedMode = textValue(raw.mode, base.mode) as MetricMode;
  const mode = METRIC_MODES.includes(requestedMode) ? requestedMode : base.mode;
  const requestedAggregation = textValue(raw.aggregation, base.aggregation) as Aggregation;
  return {
    ...base,
    mode,
    oid: textValue(raw.oid, legacyOid),
    used_oid: textValue(raw.used_oid),
    total_oid: textValue(raw.total_oid),
    free_oid: textValue(raw.free_oid),
    capacity_oid: textValue(raw.capacity_oid),
    counter_bits: textValue(raw.counter_bits) === '32' || textValue(raw.counter_bits) === '64' ? (textValue(raw.counter_bits) as CounterBits) : '',
    counter_unit: textValue(raw.counter_unit, 'bits') === 'octets' ? 'octets' : 'bits',
    status_ok_values: textValue(raw.status_ok_values, textValue(raw.normal_values, base.status_ok_values)),
    status_warning_values: textValue(raw.status_warning_values, textValue(raw.warning_values)),
    status_fail_values: textValue(raw.status_fail_values, textValue(raw.failure_values, base.status_fail_values)),
    unit: textValue(raw.unit, mode === 'status_code' ? 'bool' : base.unit),
    aggregation: AGGREGATIONS.includes(requestedAggregation) ? requestedAggregation : 'average',
    selector: textValue(raw.selector),
    scale: textValue(raw.scale, '1'),
    offset: textValue(raw.offset, '0'),
  };
};

const DEFAULT_METRIC_KEYS = ['cpu', 'memory'];

const createDefaultRows = (keys = DEFAULT_METRIC_KEYS) =>
  keys
    .map(key => catalogEntry(key))
    .filter((item): item is MetricCatalogEntry => Boolean(item))
    .map(item => ({ key: item.key, definition: createDefinition(item.key) }));

const profileDefinitions = (profile: MetricOidProfile) => {
  const definitions = { ...(profile.metric_definitions || {}) };
  if (!definitions.cpu && (profile.cpu_config || profile.cpu_oid)) definitions.cpu = profile.cpu_config || { mode: 'direct_percent', oid: profile.cpu_oid };
  if (!definitions.memory && (profile.memory_config || profile.memory_oid)) definitions.memory = profile.memory_config || { mode: 'direct_percent', oid: profile.memory_oid };
  return definitions;
};

const interfaceConfigFromProfile = (profile?: MetricOidProfile): InterfaceOidConfig => {
  const raw = profile?.interface_config || {};
  const mode = textValue(raw.counter_mode, 'auto');
  return {
    ...DEFAULT_INTERFACE_CONFIG,
    ...raw,
    enabled: raw.enabled === true || textValue(raw.enabled).toLowerCase() === 'true',
    counter_mode: mode === '32' || mode === '64' ? mode : 'auto',
  } as InterfaceOidConfig;
};

const rowsFromProfile = (profile: MetricOidProfile): MetricRow[] => {
  const definitions = profileDefinitions(profile);
  const configuredKeys = Object.keys(definitions);
  const keys = configuredKeys.length ? configuredKeys : DEFAULT_METRIC_KEYS;
  return Array.from(new Set(keys)).map(key => ({
    key,
    definition: definitionFromProfile(key, definitions[key], key === 'cpu' ? profile.cpu_oid : key === 'memory' ? profile.memory_oid : ''),
  }));
};

const hasAdvancedSettings = (key: string, definition: MetricDefinition) => {
  const defaults = createDefinition(key);
  return Boolean(
    definition.selector.trim() ||
      definition.aggregation !== defaults.aggregation ||
      definition.scale.trim() !== defaults.scale ||
      definition.offset.trim() !== defaults.offset ||
      definition.status_warning_values.trim() !== defaults.status_warning_values.trim() ||
      definition.status_fail_values.trim() !== defaults.status_fail_values.trim(),
  );
};

const hasDefinition = (definition: MetricDefinition) => {
  if (definition.mode === 'used_total_percent') return Boolean(definition.used_oid.trim() && definition.total_oid.trim());
  if (definition.mode === 'used_free_percent') return Boolean(definition.used_oid.trim() && definition.free_oid.trim());
  if (definition.mode === 'counter_rate_percent') return Boolean(definition.oid.trim() && definition.capacity_oid.trim());
  return Boolean(definition.oid.trim());
};

const toPayload = (definition: MetricDefinition): Record<string, unknown> => {
  if (!hasDefinition(definition)) return {};
  const payload: Record<string, unknown> = {
    mode: definition.mode,
    oid: definition.oid.trim(),
    used_oid: definition.used_oid.trim(),
    total_oid: definition.total_oid.trim(),
    free_oid: definition.free_oid.trim(),
    capacity_oid: definition.capacity_oid.trim(),
    aggregation: definition.aggregation,
    selector: definition.selector.trim(),
    scale: Number(definition.scale || 1),
    offset: Number(definition.offset || 0),
    unit: definition.unit.trim(),
  };
  if (definition.mode === 'counter_rate_percent') {
    payload.counter_bits = definition.counter_bits ? Number(definition.counter_bits) : null;
    payload.counter_unit = definition.counter_unit;
  }
  if (definition.mode === 'status_code') {
    payload.status_ok_values = definition.status_ok_values.trim();
    payload.status_warning_values = definition.status_warning_values.trim();
    payload.status_fail_values = definition.status_fail_values.trim();
  }
  return payload;
};

const outputContract = (definition: MetricDefinition, zh: boolean) => {
  if (definition.mode === 'status_code') return zh ? 'true 正常 · false 异常 · null 未知' : 'true normal · false abnormal · null unknown';
  if (definition.mode === 'direct_percent' || definition.mode === 'used_total_percent' || definition.mode === 'used_free_percent' || definition.mode === 'counter_rate_percent') return '%（0–100）';
  return definition.unit.trim() || (zh ? '数值' : 'value');
};

const collectorStatusLabel = (status: string | undefined, zh: boolean) => {
  if (status === 'active') return zh ? '已应用' : 'Active';
  if (status === 'blocked_failed') return zh ? '验证失败，未应用' : 'Failed, not applied';
  if (status === 'no_matching_device') return zh ? '无匹配设备' : 'No matching device';
  if (status === 'blocked_unverified') return zh ? '待验证，未应用' : 'Unverified, not applied';
  return zh ? '使用默认逻辑' : 'Built-in fallback';
};

const collectorStatusClass = (status: string | undefined) => {
  if (status === 'active') return 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400';
  if (status === 'blocked_failed') return 'bg-red-500/10 text-red-600 dark:text-red-400';
  if (status === 'no_matching_device') return 'bg-slate-500/10 text-slate-600 dark:text-slate-300';
  if (status === 'blocked_unverified') return 'bg-amber-500/10 text-amber-600 dark:text-amber-400';
  return 'bg-slate-500/10 text-slate-600 dark:text-slate-300';
};

const inputClass = 'w-full rounded-md border border-black/8 bg-transparent px-2 py-1.5 font-mono text-[10px] outline-none focus:border-[#00bceb]/55 dark:border-white/10';
const selectClass = 'w-full rounded-md border border-black/8 bg-transparent px-2 py-1.5 text-[10px] outline-none focus:border-[#00bceb]/55 dark:border-white/10';
const tinyLabelClass = 'mb-1 block text-[9px] text-black/45 dark:text-white/45';

const MetricTableRow: React.FC<{
  row: MetricRow;
  zh: boolean;
  onChange: (definition: MetricDefinition) => void;
  onRemove: () => void;
  onPickOid: (metricKey: string, field: 'oid' | 'used_oid' | 'total_oid' | 'free_oid' | 'capacity_oid') => void;
}> = ({ row, zh, onChange, onRemove, onPickOid }) => {
  const item = catalogEntry(row.key);
  const definition = row.definition;
  const modes = allowedModes(row.key);
  const [advancedOpen, setAdvancedOpen] = useState(() => hasAdvancedSettings(row.key, definition));
  const set = (patch: Partial<MetricDefinition>) => onChange({ ...definition, ...patch });
  const advancedConfigured = hasAdvancedSettings(row.key, definition);

  const sourceLabel = (
    label: string,
    value: string,
    field: 'oid' | 'used_oid' | 'total_oid' | 'free_oid' | 'capacity_oid',
    placeholder = '1.3.6.1.4.1...',
  ) => (
    <label className="block">
      <div className="flex items-center justify-between">
        <span className={tinyLabelClass}>{label}</span>
        <button
          type="button"
          onClick={() => onPickOid(row.key, field)}
          className="inline-flex items-center gap-0.5 text-[9px] font-medium text-[#008aad] hover:underline dark:text-[#00bceb]"
        >
          <Search size={10} />
          {zh ? 'MIB 拾取' : 'Pick MIB'}
        </button>
      </div>
      <input
        value={value}
        onChange={event => set({ [field]: event.target.value })}
        className={inputClass}
        placeholder={placeholder}
      />
    </label>
  );

  const advancedToggle = (
    <button
      type="button"
      onClick={() => setAdvancedOpen(value => !value)}
      aria-expanded={advancedOpen}
      className="inline-flex items-center gap-1 text-[9px] font-medium text-[#008aad] hover:text-[#006f89]"
    >
      <Settings2 size={11} />
      {zh ? '高级设置' : 'Advanced settings'}
      {advancedConfigured && !advancedOpen && <span className="h-1.5 w-1.5 rounded-full bg-[#00a9ce]" aria-label={zh ? '已配置高级设置' : 'Advanced settings configured'} />}
      {advancedOpen ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
    </button>
  );

  return (
    <tr className="border-t border-black/6 align-top dark:border-white/8">
      <td className="min-w-[125px] px-3 py-3">
        <div className="font-medium text-black/75 dark:text-white/80">{item ? (zh ? item.labelZh : item.labelEn) : row.key}</div>
        <div className="mt-1 text-[9px] leading-4 text-black/40 dark:text-white/40">{outputContract(definition, zh)}</div>
      </td>
      <td className="min-w-[165px] px-2 py-3">
        <label className="block">
          <span className={tinyLabelClass}>{zh ? '采集方式' : 'Collection mode'}</span>
          {modes.length === 1 ? (
            <div className="flex min-h-[29px] items-center rounded-md bg-black/[.035] px-2 py-1.5 text-[10px] text-black/65 dark:bg-white/[.05] dark:text-white/65">
              {modeLabel(modes[0], zh)}
            </div>
          ) : (
            <select value={definition.mode} onChange={event => set({ mode: event.target.value as MetricMode })} className={selectClass}>
              {modes.map(mode => (
                <option key={mode} value={mode}>
                  {modeLabel(mode, zh)}
                </option>
              ))}
            </select>
          )}
        </label>
      </td>
      <td className="min-w-[280px] px-2 py-3">
        {definition.mode === 'used_total_percent' && (
          <div className="grid gap-2 sm:grid-cols-2">
            {sourceLabel(zh ? '已用 OID' : 'Used OID', definition.used_oid, 'used_oid')}
            {sourceLabel(zh ? '总量 OID' : 'Total OID', definition.total_oid, 'total_oid')}
          </div>
        )}
        {definition.mode === 'used_free_percent' && (
          <div className="grid gap-2 sm:grid-cols-2">
            {sourceLabel(zh ? '已用 OID' : 'Used OID', definition.used_oid, 'used_oid')}
            {sourceLabel(zh ? '空闲 OID' : 'Free OID', definition.free_oid, 'free_oid')}
          </div>
        )}
        {definition.mode !== 'used_total_percent' && definition.mode !== 'used_free_percent' && (
          <div className="space-y-2">
            {sourceLabel(definition.mode === 'counter_rate_percent' ? (zh ? '计数器 OID' : 'Counter OID') : 'OID', definition.oid, 'oid')}
            {definition.mode === 'counter_rate_percent' && sourceLabel(zh ? '容量 OID（单位/秒）' : 'Capacity OID (units/sec)', definition.capacity_oid, 'capacity_oid')}
          </div>
        )}
      </td>
      <td className="min-w-[190px] px-2 py-3">
        {definition.mode === 'status_code' ? (
          <label className="block">
            <span className={tinyLabelClass}>{zh ? '正常码 → true' : 'Normal codes → true'}</span>
            <input value={definition.status_ok_values} onChange={event => set({ status_ok_values: event.target.value })} className={inputClass} placeholder="1" />
          </label>
        ) : definition.mode === 'direct_value' ? (
          <label className="block">
            <span className={tinyLabelClass}>{zh ? '结果单位' : 'Output unit'}</span>
            <input value={definition.unit} onChange={event => set({ unit: event.target.value })} className={inputClass} placeholder="°C / V / W" />
          </label>
        ) : (
          <div className="rounded-md border border-dashed border-[#00bceb]/30 px-2 py-2 text-[10px] leading-4 text-[#008aad]">
            {zh ? '数值结果：百分比（0–100）' : 'Numeric result: percentage (0–100)'}
          </div>
        )}
      </td>
      <td className="min-w-[205px] px-2 py-3">
        <div className="space-y-2">
          {definition.mode === 'status_code' && (
            <div className="rounded-md bg-black/[.025] px-2 py-2 text-[10px] leading-4 text-black/50 dark:bg-white/[.04] dark:text-white/50">
              {zh ? '布尔输出：true = 正常，false = 异常，null = 未知码/无数据' : 'Boolean output: true normal, false abnormal, null unknown/no data'}
            </div>
          )}
          {definition.mode === 'counter_rate_percent' && (
            <>
              <label className="block">
                <span className={tinyLabelClass}>{zh ? '计数器位宽（必选）' : 'Counter width (required)'}</span>
                <select value={definition.counter_bits} onChange={event => set({ counter_bits: event.target.value as CounterBits })} className={selectClass}>
                  <option value="">{zh ? '选择 32 / 64 位' : 'Select 32 / 64 bits'}</option>
                  <option value="32">Counter32</option>
                  <option value="64">Counter64</option>
                </select>
              </label>
              <label className="block">
                <span className={tinyLabelClass}>{zh ? '计数单位' : 'Counter unit'}</span>
                <select value={definition.counter_unit} onChange={event => set({ counter_unit: event.target.value as 'bits' | 'octets' })} className={selectClass}>
                  <option value="bits">bits</option>
                  <option value="octets">octets × 8</option>
                </select>
              </label>
            </>
          )}
          {advancedToggle}
          {advancedOpen && (
            <div className="space-y-2 rounded-md border border-[#00bceb]/15 bg-[#00bceb]/[.035] p-2 dark:bg-[#00bceb]/[.06]">
              {definition.mode === 'status_code' && (
                <>
                  <label className="block">
                    <span className={tinyLabelClass}>{zh ? '告警码 → false' : 'Warning codes → false'}</span>
                    <input value={definition.status_warning_values} onChange={event => set({ status_warning_values: event.target.value })} className={inputClass} placeholder="4" />
                  </label>
                  <label className="block">
                    <span className={tinyLabelClass}>{zh ? '故障码 → false' : 'Failure codes → false'}</span>
                    <input value={definition.status_fail_values} onChange={event => set({ status_fail_values: event.target.value })} className={inputClass} placeholder="2,3" />
                  </label>
                </>
              )}
              <label className="block">
                <span className={tinyLabelClass}>{zh ? '表项索引（可选）' : 'Table row selector (optional)'}</span>
                <input value={definition.selector} onChange={event => set({ selector: event.target.value })} className={inputClass} placeholder="1 or 1.2" />
              </label>
              <label className="block">
                <span className={tinyLabelClass}>{zh ? '聚合方式' : 'Aggregation'}</span>
                <select value={definition.aggregation} onChange={event => set({ aggregation: event.target.value as Aggregation })} className={selectClass}>
                  {AGGREGATIONS.map(value => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </label>
              <div className="grid gap-2 sm:grid-cols-2">
                <label className="block">
                  <span className={tinyLabelClass}>{zh ? '缩放' : 'Scale'}</span>
                  <input value={definition.scale} onChange={event => set({ scale: event.target.value })} className={inputClass} />
                </label>
                <label className="block">
                  <span className={tinyLabelClass}>{zh ? '偏移' : 'Offset'}</span>
                  <input value={definition.offset} onChange={event => set({ offset: event.target.value })} className={inputClass} />
                </label>
              </div>
            </div>
          )}
        </div>
      </td>
      <td className="w-[52px] px-2 py-3 text-right">
        <button type="button" onClick={onRemove} title={zh ? '移除指标行' : 'Remove metric'} className="rounded-md p-1.5 text-black/35 hover:bg-red-500/10 hover:text-red-600 dark:text-white/35 dark:hover:text-red-400">
          <Trash2 size={13} />
        </button>
      </td>
    </tr>
  );
};

const MetricOidProfilesModal: React.FC<Props> = ({ open, onClose, onChanged, language, showToast, embedded = false }) => {
  const zh = language === 'zh';
  const [profiles, setProfiles] = useState<MetricOidProfile[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [form, setForm] = useState<ProfileForm>({ vendor: '', model: '', metrics: createDefaultRows(), interfaceConfig: { ...DEFAULT_INTERFACE_CONFIG } });
  const [addMetricKey, setAddMetricKey] = useState('');
  const [lastTestDetails, setLastTestDetails] = useState<{ hardware?: Record<string, any>; interface?: InterfaceTestResult } | null>(null);

  // MIB Modals
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerTarget, setPickerTarget] = useState<{ metricKey: string; field: string } | null>(null);
  const [mibModalOpen, setMibModalOpen] = useState(false);
  const [presetModalOpen, setPresetModalOpen] = useState(false);
  const [autoMatchResult, setAutoMatchResult] = useState<{ matched_series?: string; confidence?: number; preset?: ModelPresetItem } | null>(null);

  // Auto match on vendor / model change
  useEffect(() => {
    if (!editorOpen || !form.vendor.trim() || !form.model.trim()) {
      setAutoMatchResult(null);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const params = new URLSearchParams({ vendor: form.vendor.trim(), model: form.model.trim() });
        const res = await apiRequest<{ success: boolean; matched: boolean; data: any }>(`/api/platform-registry/mibs/auto-match?${params.toString()}`);
        if (res.matched && res.data?.preset) {
          setAutoMatchResult(res.data);
        } else {
          setAutoMatchResult(null);
        }
      } catch {
        setAutoMatchResult(null);
      }
    }, 350);
    return () => clearTimeout(timer);
  }, [form.vendor, form.model, editorOpen]);

  // SNMP Walk State
  const [walkTesting, setWalkTesting] = useState(false);
  const [walkIp, setWalkIp] = useState('');
  const [walkDeviceId, setWalkDeviceId] = useState('');
  const [walkTargetStatus, setWalkTargetStatus] = useState<SnmpWalkTargetStatus>('idle');
  const [walkTargetCount, setWalkTargetCount] = useState(0);
  const [walkTargetLabel, setWalkTargetLabel] = useState('');
  const [walkTargetError, setWalkTargetError] = useState('');
  const [walkVersion, setWalkVersion] = useState<SnmpWalkVersion>('2c');
  const [walkOid, setWalkOid] = useState('');
  const [walkMaxRows, setWalkMaxRows] = useState(2000);
  const [walkResult, setWalkResult] = useState<SnmpWalkResult | null>(null);
  const [walkActionNotice, setWalkActionNotice] = useState('');

  const loadProfiles = async (): Promise<MetricOidProfile[]> => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
      if (searchInput.trim()) params.set('search', searchInput.trim());
      const response = await apiRequest<MetricProfileListResponse>('/api/platform-registry/snmp-metric-profiles?' + params.toString());
      const items = Array.isArray(response.data) ? response.data : [];
      setProfiles(items);
      setTotal(Number(response.total) || 0);
      if (Number.isFinite(response.page) && response.page >= 1 && response.page !== page) setPage(response.page);
      return items;
    } catch (error) {
      showToast(error instanceof Error ? error.message : (zh ? '型号指标模板加载失败' : 'Failed to load model metric profiles'), 'error');
      return [];
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) void loadProfiles();
  }, [open, page, pageSize, searchInput]);

  const clearWalkTargetConfirmation = (value: string) => {
    setWalkIp(value);
    setWalkDeviceId('');
    setWalkTargetStatus('idle');
    setWalkTargetCount(0);
    setWalkTargetLabel('');
    setWalkTargetError('');
    setWalkResult(null);
  };

  const confirmSnmpWalkTarget = async () => {
    const query = walkIp.trim();
    if (!query) {
      showToast(zh ? '请输入设备 IP 后按回车确认' : 'Enter a device IP and press Enter to confirm', 'error');
      return;
    }
    setWalkTargetStatus('loading');
    setWalkTargetError('');
    try {
      const response = await apiRequest<{ success: boolean; data: { ip: string; device_id: string; hostname?: string } }>(`/api/platform-registry/snmp-walk-target?ip=${encodeURIComponent(query)}`);
      const targetIp = String(response.data?.ip || '').trim();
      if (!targetIp) throw new Error(zh ? '资产未返回有效 IP' : 'The asset did not return a valid IP');
      setWalkIp(targetIp);
      setWalkDeviceId(String(response.data.device_id || ''));
      setWalkTargetCount(1);
      setWalkTargetLabel([response.data.hostname, targetIp].filter(Boolean).join(' / '));
      setWalkTargetStatus('matched');
      showToast(zh ? `已确认 IP：${targetIp}` : `IP confirmed: ${targetIp}`, 'success');
    } catch (error) {
      const message = error instanceof Error ? error.message : (zh ? '未找到该 IP' : 'IP not found in asset management');
      setWalkDeviceId('');
      setWalkTargetCount(0);
      setWalkTargetLabel('');
      setWalkTargetStatus('none');
      setWalkTargetError(message);
      showToast(zh ? '未找到该 IP，请先在资产管理中录入' : 'IP not found; add it in asset management first', 'error');
    }
  };

  const vendorOptions = useMemo(() => {
    const values = new Set<string>(ALL_VENDOR_NAMES as readonly string[]);
    profiles.forEach(profile => {
      if (profile.vendor.trim()) values.add(profile.vendor.trim());
    });
    return Array.from(values);
  }, [profiles]);

  const resetForm = () => {
    setEditingId(null);
    setForm({ vendor: '', model: '', metrics: createDefaultRows(), interfaceConfig: { ...DEFAULT_INTERFACE_CONFIG } });
    setAddMetricKey('');
    setLastTestDetails(null);
    setWalkIp('');
    setWalkDeviceId('');
    setWalkTargetStatus('idle');
    setWalkTargetCount(0);
    setWalkTargetLabel('');
    setWalkTargetError('');
    setWalkOid('');
    setWalkResult(null);
  };

  const openCreate = () => {
    resetForm();
    setEditorOpen(true);
  };

  const closeEditor = () => {
    if (!saving) setEditorOpen(false);
  };

  const submitSearch = () => {
    const nextSearch = search.trim();
    if (nextSearch === searchInput && page === 1) {
      void loadProfiles();
      return;
    }
    setPage(1);
    setSearchInput(nextSearch);
  };

  const startEdit = (profile: MetricOidProfile) => {
    setEditingId(profile.profile_id);
    const rows = rowsFromProfile(profile);
    const missing = METRIC_CATALOG.find(item => !rows.some(row => row.key === item.key));
    setAddMetricKey(missing?.key || '');
    setForm({ vendor: profile.vendor, model: profile.model, metrics: rows, interfaceConfig: interfaceConfigFromProfile(profile) });
    setLastTestDetails(null);
    setEditorOpen(true);
  };

  const addMetric = () => {
    if (!addMetricKey || form.metrics.some(row => row.key === addMetricKey)) return;
    setForm(prev => ({ ...prev, metrics: [...prev.metrics, { key: addMetricKey, definition: createDefinition(addMetricKey) }] }));
    const next = METRIC_CATALOG.find(item => item.key !== addMetricKey && !form.metrics.some(row => row.key === item.key));
    setAddMetricKey(next?.key || '');
  };

  // OID Picker Handlers
  const openOidPicker = (metricKey: string, field: string) => {
    setPickerTarget({ metricKey, field });
    setPickerOpen(true);
  };

  const handleOidSelected = (node: MibNodeItem) => {
    if (!pickerTarget) return;
    const { metricKey, field } = pickerTarget;

    if (metricKey === '__interface') {
      setForm(prev => ({
        ...prev,
        interfaceConfig: {
          ...prev.interfaceConfig,
          [field]: node.oid,
        },
      }));
      showToast(zh ? `已填入接口 OID: ${node.oid}` : `Interface OID updated: ${node.oid}`, 'success');
      return;
    }

    setForm(prev => ({
      ...prev,
      metrics: prev.metrics.map(row => {
        if (row.key !== metricKey) return row;
        const patch: Partial<MetricDefinition> = { [field]: node.oid };
        if (node.recommended_mode && (allowedModes(row.key) as string[]).includes(node.recommended_mode)) {
          patch.mode = node.recommended_mode as MetricMode;
        }
        if (node.recommended_counter_bits) {
          patch.counter_bits = String(node.recommended_counter_bits) as CounterBits;
        }
        return {
          ...row,
          definition: {
            ...row.definition,
            ...patch,
          },
        };
      }),
    }));
    showToast(zh ? `已填入 ${metricKey} OID: ${node.oid}` : `${metricKey} OID updated: ${node.oid}`, 'success');
  };

  const handleMibNodeMappedToTemplate = (node: MibNodeItem, metricKey: string) => {
    const targetKey = catalogEntry(metricKey) ? metricKey : 'cpu';
    const baseForm: ProfileForm = editorOpen
      ? form
      : {
          vendor: '',
          model: '',
          metrics: createDefaultRows(),
          interfaceConfig: { ...DEFAULT_INTERFACE_CONFIG },
        };
    const targetField = targetKey === 'storage' ? 'used_oid' : 'oid';
    const nextMetrics = baseForm.metrics.some(row => row.key === targetKey)
      ? baseForm.metrics.map(row => {
          if (row.key !== targetKey) return row;
          const patch: Partial<MetricDefinition> = { [targetField]: node.oid };
          if (node.recommended_mode && (allowedModes(row.key) as string[]).includes(node.recommended_mode)) {
            patch.mode = node.recommended_mode as MetricMode;
          }
          if (node.recommended_counter_bits) {
            patch.counter_bits = String(node.recommended_counter_bits) as CounterBits;
          }
          return { ...row, definition: { ...row.definition, ...patch } };
        })
      : [
          ...baseForm.metrics,
          {
            key: targetKey,
            definition: { ...createDefinition(targetKey), [targetField]: node.oid },
          },
        ];

    setForm({
      ...baseForm,
      vendor: baseForm.vendor.trim() || node.vendor,
      metrics: nextMetrics,
    });
    setEditingId(editorOpen ? editingId : null);
    setAddMetricKey(METRIC_CATALOG.find(item => !nextMetrics.some(row => row.key === item.key))?.key || '');
    setLastTestDetails(null);
    setMibModalOpen(false);
    setEditorOpen(true);
    showToast(
      zh
        ? `已将 ${node.node_name} 映射到${metricLabel(targetKey, true)}，请补充精确型号后保存模板`
        : `${node.node_name} mapped to ${metricLabel(targetKey, false)}; complete the exact model and save the template`,
      'success',
    );
  };

  // Reverse backfill from Walk Result to form
  const backfillWalkOidToMetric = (metricKey: string, oid: string) => {
    let exists = form.metrics.some(m => m.key === metricKey);
    let updatedMetrics = form.metrics;
    if (!exists) {
      updatedMetrics = [...form.metrics, { key: metricKey, definition: createDefinition(metricKey) }];
    }
    setForm(prev => ({
      ...prev,
      metrics: updatedMetrics.map(row => {
        if (row.key !== metricKey) return row;
        return {
          ...row,
          definition: {
            ...row.definition,
            oid,
          },
        };
      }),
    }));
    showToast(zh ? `已将 ${oid} 设为 ${metricLabel(metricKey, true)} OID` : `Set ${oid} to ${metricKey} OID`, 'success');
  };

  // Apply Official Preset Model Profile
  const handleApplyPreset = (preset: ModelPresetItem) => {
    const rows: MetricRow[] = [];
    Object.entries(preset.metric_definitions || {}).forEach(([key, def]: [string, any]) => {
      rows.push({
        key,
        definition: definitionFromProfile(key, def, def.oid || ''),
      });
    });

    setForm({
      vendor: preset.vendor,
      model: preset.model,
      metrics: rows.length ? rows : createDefaultRows(),
      interfaceConfig: preset.interface_config ? ({ ...DEFAULT_INTERFACE_CONFIG, ...preset.interface_config } as InterfaceOidConfig) : { ...DEFAULT_INTERFACE_CONFIG },
    });
    setEditingId(null);
    setEditorOpen(true);
    showToast(zh ? `已套用预置模板：${preset.vendor} ${preset.model}` : `Applied preset: ${preset.vendor} ${preset.model}`, 'success');
  };

  const handleAutoMatchFromRow = async (profile: MetricOidProfile) => {
    try {
      const params = new URLSearchParams({ vendor: profile.vendor.trim(), model: profile.model.trim() });
      const res = await apiRequest<{ success: boolean; matched: boolean; data: any }>(`/api/platform-registry/mibs/auto-match?${params.toString()}`);
      if (res.matched && res.data?.preset) {
        handleApplyPreset({
          ...res.data.preset,
          vendor: profile.vendor,
          model: profile.model,
        });
        showToast(
          zh
            ? `✨ 已根据【${profile.model}】智能匹配到【${res.data.matched_series || res.data.preset.model}】MIB 规则`
            : `Auto-matched [${res.data.matched_series || res.data.preset.model}] for ${profile.model}`,
          'success',
        );
      } else {
        startEdit(profile);
        showToast(zh ? '未匹配到预设型号系列，请手动配置' : 'No pre-set series matched, configure manually', 'info');
      }
    } catch {
      startEdit(profile);
    }
  };

  const saveProfile = async () => {
    if (!form.vendor.trim() || !form.model.trim()) {
      showToast(zh ? '请先选择厂商并填写精确型号' : 'Select a vendor and enter the exact model', 'error');
      return;
    }
    const metricDefinitions: Record<string, Record<string, unknown>> = {};
    for (const row of form.metrics) {
      const payload = toPayload(row.definition);
      if (Object.keys(payload).length) metricDefinitions[row.key] = payload;
    }
    if (!Object.keys(metricDefinitions).length && !form.interfaceConfig.enabled) {
      showToast(zh ? '请至少配置一项硬件指标或启用接口模板' : 'Configure a hardware metric or enable the interface template', 'error');
      return;
    }
    const invalidCounter = form.metrics.find(row => row.definition.mode === 'counter_rate_percent' && hasDefinition(row.definition) && !row.definition.counter_bits);
    if (invalidCounter) {
      showToast(zh ? metricLabel(invalidCounter.key, true) + '计数器必须明确选择 32 位或 64 位' : metricLabel(invalidCounter.key, false) + ' counter width must be 32 or 64 bits', 'error');
      return;
    }
    const invalidStatus = form.metrics.find(row => row.definition.mode === 'status_code' && hasDefinition(row.definition) && !row.definition.status_ok_values.trim());
    if (invalidStatus) {
      showToast(zh ? metricLabel(invalidStatus.key, true) + '必须配置至少一个正常状态码' : metricLabel(invalidStatus.key, false) + ' requires at least one normal status code', 'error');
      return;
    }
    const invalidNumber = form.metrics.find(row => {
      if (!hasDefinition(row.definition)) return false;
      return !Number.isFinite(Number(row.definition.scale || 1)) || !Number.isFinite(Number(row.definition.offset || 0));
    });
    if (invalidNumber) {
      showToast(zh ? metricLabel(invalidNumber.key, true) + '的缩放或偏移必须是数字' : metricLabel(invalidNumber.key, false) + ' scale/offset must be numeric', 'error');
      return;
    }
    const cpuConfig = metricDefinitions.cpu || {};
    const memoryConfig = metricDefinitions.memory || {};
    const interfacePayload = form.interfaceConfig.enabled ? { ...form.interfaceConfig } : {};
    setSaving(true);
    try {
      const isEdit = Boolean(editingId);
      const endpoint = isEdit ? '/api/platform-registry/snmp-metric-profiles/' + editingId : '/api/platform-registry/snmp-metric-profiles';
      const saved = await apiRequest<{ success: boolean; data?: { id?: string; profile_id?: string } }>(endpoint, {
        method: isEdit ? 'PUT' : 'POST',
        body: JSON.stringify({
          vendor: form.vendor.trim(),
          model: form.model.trim(),
          metric_definitions: metricDefinitions,
          cpu_config: cpuConfig,
          memory_config: memoryConfig,
          cpu_oid: String(cpuConfig.oid || ''),
          memory_oid: String(memoryConfig.oid || ''),
          interface_config: interfacePayload,
        }),
      });
      const savedProfileId = String(saved.data?.profile_id || saved.data?.id || editingId || '');
      await loadProfiles();
      setEditorOpen(false);
      resetForm();
      if (!savedProfileId) {
        showToast(zh ? '模板已保存，但无法确定模板编号，请刷新后检查映射状态' : 'Profile saved, but its identifier was not returned; refresh and check mapping status.', 'error');
        onChanged?.();
        return;
      }
      const mappingEndpoint = '/api/platform-registry/snmp-metric-profiles/' + savedProfileId + '/mapping-validation';
      const mappingResponse = await apiRequest<{ success: boolean; data: MetricProfileMapping }>(mappingEndpoint);
      const mapping = mappingResponse.data;
      if (mapping.sample_device_id) {
        showToast(zh ? '模板已保存，正在用匹配设备验证 OID…' : 'Profile saved; validating the OIDs on a matching device…', 'info');
        await testProfile({ profile_id: savedProfileId, sample_device_id: mapping.sample_device_id });
      } else {
        showToast(
          zh ? '模板已保存，但没有匹配的样例设备，当前仍未应用；请检查厂商/精确型号。' : 'Profile saved, but no matching sample device was found; it is not applied yet. Check vendor and exact model.',
          'info',
        );
        onChanged?.();
      }
    } catch (error) {
      showToast(error instanceof Error ? error.message : (zh ? '保存或自动映射校验失败' : 'Save or automatic mapping validation failed'), 'error');
    } finally {
      setSaving(false);
    }
  };

  const deleteProfile = async () => {
    if (!editingId) return;
    if (!window.confirm(zh ? '删除后该型号将回退到内置厂商逻辑，确定继续吗？' : 'Delete this profile and fall back to built-in vendor logic?')) return;
    setSaving(true);
    try {
      await apiRequest('/api/platform-registry/snmp-metric-profiles/' + editingId, { method: 'DELETE' });
      showToast(zh ? '指标模板已删除' : 'Metric profile deleted', 'success');
      await loadProfiles();
      onChanged?.();
      setEditorOpen(false);
      resetForm();
    } catch (error) {
      showToast(error instanceof Error ? error.message : (zh ? '删除失败' : 'Delete failed'), 'error');
    } finally {
      setSaving(false);
    }
  };

  const testProfile = async (profile: Pick<MetricOidProfile, 'profile_id' | 'sample_device_id'>) => {
    if (!profile.profile_id || !profile.sample_device_id) {
      showToast(zh ? '该型号没有可验证的样例设备' : 'No sample device is available for this model', 'error');
      return;
    }
    setTestingId(profile.profile_id);
    try {
      const endpoint = '/api/platform-registry/snmp-metric-profiles/' + profile.profile_id + '/test';
      const response = await apiRequest<{
        success: boolean;
        data: { passed: boolean; hardware_passed?: boolean | null; interface_passed?: boolean | null; message?: string; sample_hostname?: string; metrics?: Record<string, any>; interface?: InterfaceTestResult };
      }>(endpoint, {
        method: 'POST',
        body: JSON.stringify({ device_id: profile.sample_device_id }),
      });
      const result = response.data;
      setLastTestDetails({ hardware: result.metrics, interface: result.interface });
      const message = result.passed
        ? (zh ? '验证通过：' + (result.sample_hostname || '样例设备') : 'Verification passed: ' + (result.sample_hostname || 'sample device'))
        : (zh ? '验证失败：' + (result.message || '请检查接口 OID、计数器位宽和权限') : 'Verification failed: ' + (result.message || 'Check interface OIDs, counter width, and SNMP view'));
      showToast(message, result.passed ? 'success' : 'error');
      await loadProfiles();
      onChanged?.();
    } catch (error) {
      showToast(error instanceof Error ? error.message : (zh ? '验证请求失败' : 'Verification request failed'), 'error');
    } finally {
      setTestingId(null);
    }
  };

  const testSnmpWalk = async () => {
    const fallbackOid = form.metrics.map(row => String(toPayload(row.definition).oid || '').trim()).find(Boolean) || (form.interfaceConfig.enabled ? form.interfaceConfig.if_name_oid : '');
    const oid = walkOid.trim() || fallbackOid;
    if (!walkIp.trim()) {
      showToast(zh ? '请输入设备 IP' : 'Enter a device IP or hostname first', 'error');
      return;
    }
    if (walkTargetStatus === 'multiple') {
      showToast(zh ? '匹配到多台资产，请输入更完整的 IP 或主机名' : 'Multiple assets matched; enter a more specific IP or hostname', 'error');
      return;
    }
    if (walkTargetStatus === 'none') {
      showToast(zh ? '资产管理中没有匹配的设备，请先录入并配置 SNMP' : 'No matching managed asset; add the device and configure SNMP first', 'error');
      return;
    }
    if (walkTargetStatus === 'error') {
      showToast(walkTargetError || (zh ? '资产匹配失败' : 'Asset matching failed'), 'error');
      return;
    }
    if (walkTargetStatus === 'loading') {
      showToast(zh ? '正在匹配资产，请稍候再测试' : 'Asset matching is still in progress', 'info');
      return;
    }
    if (!walkDeviceId) {
      showToast(zh ? '请输入资产管理中的设备 IP 或主机名' : 'Enter an IP or hostname from asset management', 'error');
      return;
    }
    if (!oid) {
      showToast(zh ? '请输入或配置 OID' : 'Enter an OID or configure one in the template', 'error');
      return;
    }
    if (!walkOid.trim()) setWalkOid(oid);
    setWalkTesting(true);
    setWalkResult(null);
    setWalkActionNotice('');
    try {
      const response = await apiRequest<{ success: boolean; data: SnmpWalkResult }>('/api/platform-registry/snmp-walk-test', {
        method: 'POST',
        body: JSON.stringify({
          device_id: walkDeviceId,
          version: walkVersion,
          oid,
          timeout: 5,
          max_rows: walkMaxRows,
        }),
      });
      setWalkResult(response.data);
      showToast(
        response.data.status === 'ok'
          ? (zh ? `WALK 成功，返回 ${response.data.row_count} 行` : `WALK succeeded with ${response.data.row_count} rows`)
          : (response.data.message || (zh ? 'WALK 没有返回数据' : 'WALK returned no data')),
        response.data.status === 'ok' ? 'success' : 'error',
      );
    } catch (error) {
      showToast(error instanceof Error ? error.message : (zh ? 'SNMP WALK 测试失败' : 'SNMP WALK test failed'), 'error');
    } finally {
      setWalkTesting(false);
    }
  };

  const walkText = walkResult?.rows.map(row => `${row.oid} = ${row.value}`).join('\n') || '';
  const walkJson = walkResult ? JSON.stringify(walkResult, null, 2) : '';

  const copyWalkOutput = async (format: 'text' | 'json') => {
    const content = format === 'json' ? walkJson : walkText;
    if (!content) return;
    try {
      const fallbackCopy = () => {
        const helper = document.createElement('textarea');
        helper.value = content;
        helper.setAttribute('readonly', 'true');
        helper.style.position = 'fixed';
        helper.style.opacity = '0';
        document.body.appendChild(helper);
        helper.select();
        const copied = document.execCommand('copy');
        helper.remove();
        if (!copied) throw new Error('clipboard_unavailable');
      };
      if (navigator.clipboard?.writeText) {
        try {
          await navigator.clipboard.writeText(content);
        } catch {
          fallbackCopy();
        }
      } else {
        fallbackCopy();
      }
      setWalkActionNotice(zh ? '复制成功' : 'Copied successfully');
      window.setTimeout(() => setWalkActionNotice(''), 3000);
      showToast(zh ? 'WALK 结果已复制' : 'WALK output copied', 'success');
    } catch {
      showToast(zh ? '复制失败，请手动选择结果文本' : 'Copy failed; select the output and copy it manually', 'error');
    }
  };

  const downloadWalkOutput = (format: 'text' | 'json') => {
    const content = format === 'json' ? walkJson : walkText;
    if (!content) return;
    const blob = new Blob([content], { type: format === 'json' ? 'application/json;charset=utf-8' : 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `snmpwalk-${walkResult?.host || 'result'}-${walkResult?.oid || 'oid'}.${format === 'json' ? 'json' : 'txt'}`.replace(/[^a-zA-Z0-9_.-]/g, '_');
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
    setWalkActionNotice(format === 'json' ? (zh ? 'JSON 下载已开始' : 'JSON download started') : (zh ? 'TXT 下载已开始' : 'TXT download started'));
    window.setTimeout(() => setWalkActionNotice(''), 3000);
  };

  const validateMapping = async (profile: MetricOidProfile) => {
    if (!profile.profile_id) return;
    try {
      const endpoint = '/api/platform-registry/snmp-metric-profiles/' + profile.profile_id + '/mapping-validation';
      const response = await apiRequest<{ success: boolean; data: MetricProfileMapping }>(endpoint);
      const mapping = response.data;
      const message = zh
        ? '映射范围：' + mapping.matched_device_count + ' 台；生效 ' + mapping.profile_applied_device_count + ' 台；阻断 ' + mapping.blocked_device_count + ' 台；指标 ' + ((mapping.metric_keys || []).map(key => metricLabel(key, true)).join('、') || '无') + '。'
        : 'Mapping: ' + mapping.matched_device_count + ' matched; ' + mapping.profile_applied_device_count + ' active; ' + mapping.blocked_device_count + ' blocked; metrics ' + ((mapping.metric_keys || []).join(', ') || 'none') + '.';
      showToast(message, mapping.collector_status === 'active' || mapping.collector_status === 'builtin_only' || mapping.collector_status === 'no_matching_device' ? 'info' : 'error');
    } catch (error) {
      showToast(error instanceof Error ? error.message : (zh ? '映射校验失败' : 'Mapping validation failed'), 'error');
    }
  };

  const addableMetrics = METRIC_CATALOG.filter(item => !form.metrics.some(row => row.key === item.key));
  const visibleProfiles = profiles;
  const customVendorOptions = vendorOptions.filter(vendor => !KNOWN_VENDOR_SET.has(vendor));

  if (!open) return null;
  return (
    <div className={embedded ? 'h-full min-h-0 w-full' : 'fixed inset-0 z-[120] flex items-center justify-center bg-black/45 p-4 backdrop-blur-sm'} onMouseDown={embedded ? undefined : onClose}>
      <div className={embedded ? 'flex h-full min-h-0 w-full flex-col overflow-hidden rounded-2xl border border-black/8 bg-[var(--card-bg)] dark:border-white/10' : 'flex max-h-[92vh] w-full max-w-[1500px] flex-col overflow-hidden rounded-2xl border border-black/8 bg-[var(--card-bg)] shadow-2xl dark:border-white/10'} onMouseDown={event => event.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-black/6 px-5 py-4 dark:border-white/8">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-black/80 dark:text-white/85">
              <Cpu size={17} className="text-[#009ec4]" />
              {zh ? 'SNMP 型号指标模板与 MIB 知识库' : 'SNMP Model Metric Profiles & MIB Repository'}
            </div>
            <p className="mt-1 text-[11px] text-black/45 dark:text-white/45">
              {zh
                ? '厂商来自资产管理共享目录；按精确型号维护完整硬件指标。支持 MIB 符号库在线拾取与主流型号官方模板快速导入。'
                : 'Vendors use the shared asset catalog. Maintain the complete hardware contract by exact model with MIB Picker support.'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setPresetModalOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/25 bg-emerald-500/10 px-3 py-2 text-[11px] font-medium text-emerald-700 hover:bg-emerald-500/20 dark:text-emerald-400"
            >
              <Sparkles size={13} />
              {zh ? '官方预置模板' : 'Presets'}
            </button>
            <button
              type="button"
              onClick={() => setMibModalOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[#00bceb]/25 bg-[#00bceb]/10 px-3 py-2 text-[11px] font-medium text-[#008aad] hover:bg-[#00bceb]/20 dark:text-[#00bceb]"
            >
              <Database size={13} />
              {zh ? 'MIB 知识库' : 'MIBs'}
            </button>
            <button
              type="button"
              onClick={openCreate}
              className="inline-flex items-center gap-1.5 rounded-lg bg-[#00a9ce] px-3 py-2 text-[11px] font-medium text-white shadow-sm hover:bg-[#008fb1]"
            >
              <Plus size={13} />
              {zh ? '新建' : 'New'}
            </button>
            {!embedded && (
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg p-1.5 text-black/40 hover:bg-black/5 dark:text-white/45 dark:hover:bg-white/8"
              >
                <X size={17} />
              </button>
            )}
          </div>
        </div>

        <div className="flex min-h-0 flex-1 overflow-hidden p-5">
          <section className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-xl border border-black/6 dark:border-white/8">
            <div className="flex items-center gap-2 border-b border-black/6 p-3 dark:border-white/8">
              <div className="relative min-w-0 flex-1">
                <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-black/30 dark:text-white/25" />
                <input
                  value={search}
                  onChange={event => setSearch(event.target.value)}
                  placeholder={zh ? '搜索厂商 / 型号 / 指标' : 'Search vendor / model / metric'}
                  className="w-full rounded-lg border border-black/8 bg-transparent py-1.5 pl-8 pr-2 text-xs outline-none focus:border-[#00bceb]/50 dark:border-white/10"
                />
              </div>
              <button
                type="button"
                onClick={submitSearch}
                disabled={loading}
                className="inline-flex items-center gap-1 rounded-lg border border-[#00bceb]/25 px-2.5 py-1.5 text-[11px] font-medium text-[#008aad] hover:bg-[#00bceb]/10 disabled:opacity-40"
              >
                <Search size={13} />
                {zh ? '搜索' : 'Search'}
              </button>
              <button
                type="button"
                onClick={() => void loadProfiles()}
                disabled={loading}
                className="rounded-lg border border-black/8 p-2 text-black/45 hover:bg-black/5 disabled:opacity-40 dark:border-white/10 dark:text-white/45 dark:hover:bg-white/8"
              >
                <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-auto">
              {loading ? (
                <div className="p-8 text-center text-xs text-black/40 dark:text-white/40">{zh ? '加载中…' : 'Loading…'}</div>
              ) : visibleProfiles.length === 0 ? (
                <div className="p-8 text-center text-xs text-black/40 dark:text-white/40">{zh ? '没有发现型号或搜索无结果。' : 'No model groups found.'}</div>
              ) : (
                <table className="w-full text-left text-[11px]">
                  <thead className="sticky top-0 bg-[var(--card-bg)] text-black/40 dark:text-white/40">
                    <tr>
                      <th className="px-3 py-2 font-medium">{zh ? '厂商 / 型号' : 'Vendor / Model'}</th>
                      <th className="px-3 py-2 font-medium">{zh ? '采集指标' : 'Metrics'}</th>
                      <th className="px-3 py-2 font-medium">{zh ? '设备数' : 'Devices'}</th>
                      <th className="px-3 py-2 font-medium">{zh ? '状态' : 'Status'}</th>
                      <th className="px-3 py-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {visibleProfiles.map(profile => {
                      const collectorStatus = profile.collector_status || (profile.configured ? 'blocked_unverified' : 'builtin_only');
                      const matchedDeviceCount = Number(profile.matched_device_count ?? profile.device_count ?? 0);
                      const appliedDeviceCount = Number(profile.profile_applied_device_count ?? (collectorStatus === 'active' ? matchedDeviceCount : 0));
                      return (
                        <tr key={profile.vendor + ':' + profile.model} className="border-t border-black/5 dark:border-white/6">
                          <td className="max-w-[220px] px-3 py-2.5">
                            <div className="truncate font-medium text-black/75 dark:text-white/80">{profile.vendor}</div>
                            <div className="truncate text-black/45 dark:text-white/45">{profile.model}</div>
                          </td>
                          <td className="max-w-[260px] px-3 py-2.5 text-black/55 dark:text-white/55">
                            <div className="flex flex-wrap gap-1">
                              {(profile.metric_keys || Object.keys(profile.metric_definitions || {})).map(key => (
                                <span key={key} className="rounded bg-black/[.04] px-1.5 py-0.5 text-[9px] dark:bg-white/[.06]">
                                  {metricLabel(key, zh)}
                                </span>
                              ))}
                              {profile.interface_configured && (
                                <span className="rounded bg-[#00bceb]/10 px-1.5 py-0.5 text-[9px] text-[#008aad]">
                                  {zh ? '接口' : 'Interfaces'}
                                </span>
                              )}
                            </div>
                          </td>
                          <td className="px-3 py-2.5 tabular-nums text-black/55 dark:text-white/55">{profile.device_count}</td>
                          <td className="px-3 py-2.5">
                            <div className="flex flex-wrap gap-1">
                              <span className={(profile.configured || profile.interface_configured ? 'bg-slate-500/10 text-slate-600 dark:text-slate-300' : 'bg-amber-500/10 text-amber-600 dark:text-amber-400') + ' rounded-full px-2 py-1 text-[10px]'}>
                                {profile.configured || profile.interface_configured ? (zh ? '已配置' : 'Configured') : (zh ? '使用默认' : 'Default')}
                              </span>
                              {profile.configured && (
                                <span className={(profile.verification_status === 'verified' ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400' : profile.verification_status === 'failed' ? 'bg-red-500/10 text-red-600 dark:text-red-400' : 'bg-amber-500/10 text-amber-600 dark:text-amber-400') + ' inline-flex items-center gap-1 rounded-full px-2 py-1 text-[10px]'}>
                                  {profile.verification_status === 'verified' && <CheckCircle2 size={10} />}
                                  {profile.verification_status === 'verified' ? (zh ? '硬件已验证' : 'Hardware verified') : profile.verification_status === 'failed' ? (zh ? '硬件失败' : 'Hardware failed') : (zh ? '硬件待验证' : 'Hardware unverified')}
                                </span>
                              )}
                              {profile.interface_configured && (
                                <span className={(profile.interface_verification_status === 'verified' ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400' : profile.interface_verification_status === 'failed' ? 'bg-red-500/10 text-red-600 dark:text-red-400' : 'bg-amber-500/10 text-amber-600 dark:text-amber-400') + ' rounded-full px-2 py-1 text-[10px]'}>
                                  {profile.interface_verification_status === 'verified' ? (zh ? '接口已验证' : 'Interface verified') : profile.interface_verification_status === 'failed' ? (zh ? '接口失败' : 'Interface failed') : (zh ? '接口待验证' : 'Interface unverified')}
                                </span>
                              )}
                              <span className={collectorStatusClass(collectorStatus) + ' rounded-full px-2 py-1 text-[10px]'}>
                                {collectorStatusLabel(collectorStatus, zh)}
                              </span>
                            </div>
                            <div className="mt-1 text-[9px] text-black/40 dark:text-white/40">
                              {zh ? `匹配 ${matchedDeviceCount} 台 · 已应用 ${appliedDeviceCount} 台` : `${matchedDeviceCount} matched · ${appliedDeviceCount} applied`}
                            </div>
                          </td>
                          <td className="px-3 py-2.5 text-right">
                            <div className="flex items-center justify-end gap-1">
                              {!profile.configured && (
                                <button
                                  type="button"
                                  onClick={() => void handleAutoMatchFromRow(profile)}
                                  className="inline-flex items-center gap-1 rounded-md border border-emerald-500/25 bg-emerald-500/10 px-2 py-1 text-[10px] font-semibold text-emerald-700 hover:bg-emerald-500/20 dark:text-emerald-400"
                                  title={zh ? '根据此型号智能匹配 MIB 并生成配置' : 'Auto-match MIB and generate profile'}
                                >
                                  <Sparkles size={11} />
                                  {zh ? '智能匹配' : 'Auto Match'}
                                </button>
                              )}
                              {profile.profile_id && (
                                <button type="button" onClick={() => void validateMapping(profile)} className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[10px] font-medium text-[#008aad] hover:bg-[#00bceb]/10">
                                  <GitBranch size={11} />
                                  {zh ? '映射' : 'Map'}
                                </button>
                              )}
                              {profile.profile_id && profile.sample_device_id && (
                                <button type="button" onClick={() => void testProfile(profile)} disabled={testingId === profile.profile_id} className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[10px] font-medium text-emerald-700 hover:bg-emerald-500/10 disabled:opacity-40 dark:text-emerald-400">
                                  <Activity size={11} className={testingId === profile.profile_id ? 'animate-pulse' : ''} />
                                  {testingId === profile.profile_id ? (zh ? '测试中' : 'Testing') : (zh ? '验证' : 'Test')}
                                </button>
                              )}
                              <button type="button" onClick={() => startEdit(profile)} className="rounded-md px-2 py-1 text-[10px] font-medium text-[#008aad] hover:bg-[#00bceb]/10">
                                {zh ? '编辑' : 'Edit'}
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
            <Pagination
              currentPage={page}
              totalItems={total}
              itemsPerPage={pageSize}
              onPageChange={setPage}
              onItemsPerPageChange={size => {
                setPageSize(size);
                setPage(1);
              }}
              language={language}
              alwaysVisible
            />
            {lastTestDetails?.interface && (
              <div className="mx-3 mb-3 rounded-lg border border-black/8 bg-black/[.02] p-3 text-[10px] dark:border-white/10 dark:bg-white/[.03]">
                <div className="font-medium text-black/65 dark:text-white/70">{zh ? '最近一次接口校验' : 'Latest interface verification'}</div>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <span className={lastTestDetails.interface.passed ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}>
                    {lastTestDetails.interface.passed ? '✓' : '✕'}
                  </span>
                  <span className="text-black/55 dark:text-white/55">{lastTestDetails.interface.message}</span>
                  <span className="text-black/40 dark:text-white/40">
                    {zh
                      ? `接口 ${lastTestDetails.interface.interfaces || 0}，支持计数器 ${lastTestDetails.interface.counter_supported || 0}，位宽 ${lastTestDetails.interface.selected_counter_bits || '-'}`
                      : `${lastTestDetails.interface.interfaces || 0} interfaces · ${lastTestDetails.interface.counter_supported || 0} counters · width ${lastTestDetails.interface.selected_counter_bits || '-'}`}
                  </span>
                </div>
                {lastTestDetails.interface.checks && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {Object.entries(lastTestDetails.interface.checks).map(([key, check]) => (
                      <span key={key} className={(check.passed ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400' : 'bg-red-500/10 text-red-700 dark:text-red-400') + ' rounded px-1.5 py-0.5 text-[9px]'}>
                        {check.passed ? '✓' : '✕'} {key} {check.rows !== undefined ? `(${check.rows})` : ''}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
          </section>

          {editorOpen && (
            <div className="fixed inset-0 z-[130] flex items-center justify-center bg-black/45 p-4 backdrop-blur-sm" onMouseDown={closeEditor}>
              <div className="flex max-h-[94vh] w-full max-w-[1500px] flex-col overflow-hidden rounded-2xl border border-[#00bceb]/25 bg-[var(--card-bg)] shadow-2xl dark:border-white/10" onMouseDown={event => event.stopPropagation()}>
                <div className="flex justify-end border-b border-black/6 px-4 py-2 dark:border-white/8">
                  <button type="button" onClick={closeEditor} className="rounded-lg p-1.5 text-black/40 hover:bg-black/5 dark:text-white/45 dark:hover:bg-white/8" aria-label={zh ? '关闭' : 'Close'}>
                    <X size={16} />
                  </button>
                </div>
                <aside className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-xl border border-[#00bceb]/20 bg-[#00bceb]/[.04] dark:bg-[#00bceb]/[.06]">
                  <div className="border-b border-black/6 p-4 dark:border-white/8">
                    <div className="text-xs font-semibold text-black/75 dark:text-white/80">{editingId ? (zh ? '编辑型号模板' : 'Edit model profile') : (zh ? '新增型号模板' : 'New model profile')}</div>
                    <div className="mt-1 text-[10px] text-black/40 dark:text-white/40">
                      {zh ? '先填写厂商、精确型号和需要采集的 OID；可点击【MIB 拾取】自动填充 OID 或通过下方 WALK 探测后一键设为指标。' : 'Set vendor, model, and OIDs. Use MIB Picker or backfill from WALK results.'}
                    </div>
                  </div>
                  <div className="min-h-0 flex-1 overflow-auto p-4">
                    {/* Live Inspector SNMP Walk */}
                    <section className="mb-4 rounded-xl border border-emerald-500/25 bg-emerald-500/[.035] p-3 dark:bg-emerald-500/[.06]">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div>
                          <div className="flex items-center gap-1.5 text-[11px] font-semibold text-black/70 dark:text-white/75">
                            <Activity size={13} className="text-emerald-600 dark:text-emerald-400" />
                            {zh ? 'SNMP WALK 实时探测与反向填充（只读）' : 'Live SNMP WALK & Backfill Inspector'}
                          </div>
                          <div className="mt-0.5 text-[9px] leading-4 text-black/45 dark:text-white/45">
                            {zh ? '探测设备返回的所有 OID；可直接在结果中点击【设为 CPU / 内存 / 温度】一键填充到左侧表单。' : 'Inspect device OIDs and backfill them directly into your profile.'}
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <button type="button" onClick={() => void testSnmpWalk()} disabled={walkTesting || saving} className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-3 py-1.5 text-[10px] font-medium text-white hover:bg-emerald-700 disabled:opacity-45">
                            <Activity size={12} className={walkTesting ? 'animate-spin' : ''} />
                            {walkTesting ? (zh ? '探测中...' : 'Testing...') : (zh ? '执行 WALK 探测' : 'Run WALK')}
                          </button>
                        </div>
                      </div>

                      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                        <label className="block">
                          <span className={tinyLabelClass}>{zh ? '设备 IP（回车确认）' : 'Target IP (press Enter)'}</span>
                          <input
                            value={walkIp}
                            onChange={event => clearWalkTargetConfirmation(event.target.value)}
                            onKeyDown={event => {
                              if (event.key === 'Enter') {
                                event.preventDefault();
                                void confirmSnmpWalkTarget();
                              }
                            }}
                            className={inputClass}
                            placeholder="10.254.0.1"
                          />
                        </label>
                        <label className="block">
                          <span className={tinyLabelClass}>{zh ? 'SNMP 版本' : 'SNMP version'}</span>
                          <select value={walkVersion} onChange={event => setWalkVersion(event.target.value as SnmpWalkVersion)} className={selectClass}>
                            <option value="2c">SNMPv2c</option>
                            <option value="1">SNMPv1</option>
                          </select>
                        </label>
                        <label className="block">
                          <span className={tinyLabelClass}>{zh ? '起始探测 OID' : 'Start OID'}</span>
                          <input value={walkOid} onChange={event => setWalkOid(event.target.value)} className={inputClass} placeholder="1.3.6.1.2.1..." />
                        </label>
                      </div>

                      <div className={(walkTargetStatus === 'matched' ? 'text-emerald-700 dark:text-emerald-400' : walkTargetStatus === 'multiple' || walkTargetStatus === 'none' || walkTargetStatus === 'error' ? 'text-amber-700 dark:text-amber-400' : 'text-black/45 dark:text-white/45') + ' mt-1 text-[9px] leading-4'}>
                        {walkTargetStatus === 'idle' && (zh ? '输入资产管理中的设备 IP，系统自动读取 SNMP 认证。' : 'Enter device IP; SNMP settings are read automatically.')}
                        {walkTargetStatus === 'loading' && (zh ? '正在匹配资产…' : 'Matching assets…')}
                        {walkTargetStatus === 'matched' && (zh ? `已匹配：${walkTargetLabel || '设备'}` : `Matched: ${walkTargetLabel || 'device'}`)}
                        {walkTargetStatus === 'none' && (zh ? '未匹配到资产，请确认设备已录入资产管理。' : 'No managed asset matched.')}
                        {walkTargetStatus === 'error' && (walkTargetError || (zh ? '匹配失败' : 'Matching failed'))}
                      </div>

                      {walkResult && (
                        <div className="mt-3 rounded-lg border border-black/8 bg-white/70 p-3 dark:border-white/10 dark:bg-white/[.04]">
                          <div className="flex flex-wrap items-center justify-between gap-2 text-[10px]">
                            <span className={walkResult.status === 'ok' ? 'font-medium text-emerald-700 dark:text-emerald-400' : 'font-medium text-red-700 dark:text-red-400'}>
                              {walkResult.status === 'ok' ? '✓' : '✕'} {walkResult.message} ({walkResult.row_count} 行)
                            </span>
                            <div className="flex flex-wrap gap-1">
                              <button type="button" onClick={() => void copyWalkOutput('text')} disabled={!walkText} className="rounded border border-black/10 px-2 py-0.5 text-[9px] hover:bg-black/5 dark:border-white/10">
                                {zh ? '复制文本' : 'Copy'}
                              </button>
                              <button type="button" onClick={() => downloadWalkOutput('text')} disabled={!walkText} className="rounded border border-black/10 px-2 py-0.5 text-[9px] hover:bg-black/5 dark:border-white/10">
                                {zh ? '下载 TXT' : 'Download'}
                              </button>
                            </div>
                          </div>

                          {/* Structured Rows Table for Backfill */}
                          <div className="mt-2 max-h-48 overflow-y-auto rounded border border-black/6 bg-black/[.02] dark:border-white/6 dark:bg-black/20">
                            <table className="w-full text-left text-[10px]">
                              <thead className="sticky top-0 bg-[var(--card-bg)] text-[9px] text-black/45 dark:text-white/45">
                                <tr>
                                  <th className="px-2 py-1.5 font-mono">OID</th>
                                  <th className="px-2 py-1.5">{zh ? '当前返回值' : 'Value'}</th>
                                  <th className="px-2 py-1.5 text-right">{zh ? '快捷反向填充' : 'Quick Backfill'}</th>
                                </tr>
                              </thead>
                              <tbody>
                                {walkResult.rows.slice(0, 30).map((row, idx) => (
                                  <tr key={idx} className="border-t border-black/5 hover:bg-[#00bceb]/[0.05] dark:border-white/5">
                                    <td className="select-all px-2 py-1 font-mono text-[#008aad] dark:text-[#00bceb]">{row.oid}</td>
                                    <td className="max-w-[200px] truncate px-2 py-1 text-black/70 dark:text-white/70">{row.value}</td>
                                    <td className="px-2 py-1 text-right">
                                      <div className="inline-flex items-center gap-1">
                                        <button
                                          type="button"
                                          onClick={() => backfillWalkOidToMetric('cpu', row.oid)}
                                          className="rounded bg-black/[.04] px-1.5 py-0.5 text-[9px] font-medium text-black/70 hover:bg-[#00bceb]/20 hover:text-[#008aad] dark:bg-white/[.06] dark:text-white/80"
                                        >
                                          {zh ? '设为 CPU' : 'Set CPU'}
                                        </button>
                                        <button
                                          type="button"
                                          onClick={() => backfillWalkOidToMetric('memory', row.oid)}
                                          className="rounded bg-black/[.04] px-1.5 py-0.5 text-[9px] font-medium text-black/70 hover:bg-[#00bceb]/20 hover:text-[#008aad] dark:bg-white/[.06] dark:text-white/80"
                                        >
                                          {zh ? '设为 内存' : 'Set Mem'}
                                        </button>
                                        <button
                                          type="button"
                                          onClick={() => backfillWalkOidToMetric('temperature', row.oid)}
                                          className="rounded bg-black/[.04] px-1.5 py-0.5 text-[9px] font-medium text-black/70 hover:bg-[#00bceb]/20 hover:text-[#008aad] dark:bg-white/[.06] dark:text-white/80"
                                        >
                                          {zh ? '设为 温度' : 'Set Temp'}
                                        </button>
                                      </div>
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      )}
                    </section>

                    {/* Vendor and Model inputs */}
                    <div className="mb-3 grid gap-2 sm:grid-cols-2">
                      <label className="block text-[11px] text-black/55 dark:text-white/55">
                        {zh ? '厂商（同步资产管理）' : 'Vendor (shared with assets)'}
                        <select
                          value={form.vendor}
                          onChange={event => setForm(prev => ({ ...prev, vendor: event.target.value }))}
                          className="mt-1 w-full rounded-lg border border-black/8 bg-white/40 px-2.5 py-2 text-xs outline-none focus:border-[#00bceb]/50 dark:border-white/10 dark:bg-white/[.03]"
                        >
                          <option value="">{zh ? '选择设备厂商...' : 'Select device vendor...'}</option>
                          {NETWORK_VENDOR_GROUPS.map(group => (
                            <optgroup key={group.key} label={zh ? group.labelZh : group.labelEn}>
                              {group.vendors.map(vendor => (
                                <option key={vendor} value={vendor}>
                                  {vendor}
                                </option>
                              ))}
                            </optgroup>
                          ))}
                          {customVendorOptions.length > 0 && (
                            <optgroup label={zh ? '历史/自定义厂商' : 'Legacy / custom vendors'}>
                              {customVendorOptions.map(vendor => (
                                <option key={vendor} value={vendor}>
                                  {vendor}
                                </option>
                              ))}
                            </optgroup>
                          )}
                        </select>
                      </label>
                      <label className="block text-[11px] text-black/55 dark:text-white/55">
                        {zh ? '精确型号' : 'Exact model'}
                        <input
                          value={form.model}
                          onChange={event => setForm(prev => ({ ...prev, model: event.target.value }))}
                          className="mt-1 w-full rounded-lg border border-black/8 bg-white/40 px-2.5 py-2 text-xs outline-none focus:border-[#00bceb]/50 dark:border-white/10 dark:bg-white/[.03]"
                          placeholder="C9300-48P"
                        />
                      </label>
                    </div>

                    {/* Auto Match Recommendation Banner */}
                    {autoMatchResult && autoMatchResult.preset && (
                      <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-emerald-500/25 bg-emerald-500/[0.06] p-3 text-xs dark:bg-emerald-500/[0.1]">
                        <div className="flex items-center gap-2">
                          <Sparkles size={16} className="shrink-0 text-emerald-600 dark:text-emerald-400" />
                          <div>
                            <div className="font-semibold text-emerald-800 dark:text-emerald-300">
                              {zh
                                ? `✨ 已根据型号智能匹配到【${autoMatchResult.matched_series || autoMatchResult.preset.model}】MIB 规则`
                                : `✨ Inferred MIB profile for [${autoMatchResult.matched_series || autoMatchResult.preset.model}]`}
                            </div>
                            <div className="mt-0.5 text-[10px] text-emerald-700/80 dark:text-emerald-400/80">
                              {zh
                                ? `置信度 ${Math.round((autoMatchResult.confidence || 0.9) * 100)}% · 包含 CPU、内存、温度、风扇与 IF-MIB 完整配置`
                                : `Confidence ${Math.round((autoMatchResult.confidence || 0.9) * 100)}% · includes CPU, Memory, Temp, and IF-MIB`}
                            </div>
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={() => {
                            const originalVendor = form.vendor;
                            const originalModel = form.model;
                            handleApplyPreset({
                              ...autoMatchResult.preset!,
                              vendor: originalVendor,
                              model: originalModel,
                            });
                          }}
                          className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-emerald-700"
                        >
                          <Sparkles size={12} />
                          {zh ? '一键采纳并填充全部 OID' : 'Apply Recommended OIDs'}
                        </button>
                      </div>
                    )}

                    {/* Metrics list */}
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <div className="text-[10px] font-medium text-black/55 dark:text-white/55">{zh ? '采集指标' : 'Metrics to collect'}</div>
                        <div className="mt-0.5 text-[9px] text-black/40 dark:text-white/40">{zh ? '默认带有 CPU、内存；只添加设备实际提供的指标。' : 'CPU and memory are included by default; add optional metrics.'}</div>
                      </div>
                      <div className="flex min-w-0 items-center gap-1">
                        <select
                          aria-label={zh ? '选择要添加的指标' : 'Metric to add'}
                          value={addMetricKey}
                          onChange={event => setAddMetricKey(event.target.value)}
                          className="max-w-[170px] rounded-md border border-black/8 bg-transparent px-2 py-1.5 text-[10px] outline-none dark:border-white/10"
                        >
                          <option value="">{zh ? '按需添加指标...' : 'Add optional metric...'}</option>
                          {addableMetrics.map(item => (
                            <option key={item.key} value={item.key}>
                              {zh ? item.labelZh : item.labelEn}
                            </option>
                          ))}
                        </select>
                        <button
                          type="button"
                          onClick={addMetric}
                          disabled={!addMetricKey}
                          className="inline-flex shrink-0 items-center gap-1 rounded-md bg-[#00a9ce] px-2 py-1.5 text-[10px] font-medium text-white hover:bg-[#008fb1] disabled:opacity-40"
                        >
                          <Plus size={12} />
                          {zh ? '添加指标' : 'Add metric'}
                        </button>
                      </div>
                    </div>

                    <div className="overflow-x-auto rounded-lg border border-black/7 bg-white/35 dark:border-white/8 dark:bg-white/[.03]">
                      <table className="w-full min-w-[1030px] text-left">
                        <thead className="sticky top-0 z-10 bg-[var(--card-bg)] text-[9px] text-black/45 dark:text-white/45">
                          <tr>
                            <th className="px-3 py-2 font-medium">{zh ? '指标' : 'Metric'}</th>
                            <th className="px-2 py-2 font-medium">{zh ? '采集方式' : 'Mode'}</th>
                            <th className="px-2 py-2 font-medium">{zh ? 'OID / 公式' : 'OID / formula'}</th>
                            <th className="px-2 py-2 font-medium">{zh ? '结果类型' : 'Output'}</th>
                            <th className="px-2 py-2 font-medium">{zh ? '计算与计数器' : 'Calculation / counter'}</th>
                            <th className="px-2 py-2" />
                          </tr>
                        </thead>
                        <tbody>
                          {form.metrics.map(row => (
                            <MetricTableRow
                              key={row.key}
                              row={row}
                              zh={zh}
                              onPickOid={openOidPicker}
                              onChange={definition =>
                                setForm(prev => ({
                                  ...prev,
                                  metrics: prev.metrics.map(item => (item.key === row.key ? { ...item, definition } : item)),
                                }))
                              }
                              onRemove={() =>
                                setForm(prev => ({
                                  ...prev,
                                  metrics: prev.metrics.filter(item => item.key !== row.key),
                                }))
                              }
                            />
                          ))}
                        </tbody>
                      </table>
                    </div>

                    {/* Interface Config Section */}
                    <section className="mt-4 rounded-lg border border-[#00bceb]/25 bg-[#00bceb]/[.035] p-3 dark:bg-[#00bceb]/[.06]">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <div className="text-[11px] font-semibold text-black/70 dark:text-white/75">{zh ? '接口流量模板（可选覆盖默认 IF-MIB）' : 'Interface template (optional IF-MIB override)'}</div>
                          <div className="mt-1 text-[9px] leading-4 text-black/45 dark:text-white/45">
                            {zh ? '启用后，接口表、状态、速率、错误和流量计数器都从这里读取；不启用时继续使用内置 IF-MIB。' : 'When enabled, interface table, speed, and counters use these OIDs.'}
                          </div>
                        </div>
                        <label className="inline-flex items-center gap-2 text-[10px] font-medium text-[#008aad]">
                          <input
                            type="checkbox"
                            checked={form.interfaceConfig.enabled}
                            onChange={event =>
                              setForm(prev => ({
                                ...prev,
                                interfaceConfig: { ...prev.interfaceConfig, enabled: event.target.checked },
                              }))
                            }
                          />
                          {zh ? '启用接口模板' : 'Enable interface template'}
                        </label>
                      </div>

                      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                        {INTERFACE_OID_FIELDS.map(field => (
                          <label key={field.key} className="block">
                            <div className="flex items-center justify-between">
                              <span className={tinyLabelClass}>{zh ? field.labelZh : field.labelEn}</span>
                              <button
                                type="button"
                                disabled={!form.interfaceConfig.enabled}
                                onClick={() => openOidPicker('__interface', field.key)}
                                className="inline-flex items-center gap-0.5 text-[9px] font-medium text-[#008aad] hover:underline disabled:opacity-40 dark:text-[#00bceb]"
                              >
                                <Search size={10} />
                                {zh ? '拾取' : 'Pick'}
                              </button>
                            </div>
                            <input
                              value={form.interfaceConfig[field.key]}
                              onChange={event =>
                                setForm(prev => ({
                                  ...prev,
                                  interfaceConfig: { ...prev.interfaceConfig, [field.key]: event.target.value },
                                }))
                              }
                              disabled={!form.interfaceConfig.enabled}
                              className={inputClass + ' disabled:cursor-not-allowed disabled:opacity-45'}
                              placeholder="1.3.6.1.2.1..."
                            />
                          </label>
                        ))}
                      </div>

                      <div className="mt-3 grid gap-2 sm:grid-cols-2">
                        <label className="block">
                          <span className={tinyLabelClass}>{zh ? '流量计数器位宽' : 'Traffic counter width'}</span>
                          <select
                            value={form.interfaceConfig.counter_mode}
                            onChange={event =>
                              setForm(prev => ({
                                ...prev,
                                interfaceConfig: { ...prev.interfaceConfig, counter_mode: event.target.value as InterfaceCounterMode },
                              }))
                            }
                            disabled={!form.interfaceConfig.enabled}
                            className={selectClass + ' disabled:cursor-not-allowed disabled:opacity-45'}
                          >
                            <option value="auto">{zh ? '自动：优先 64 位，缺失时成对回退 32 位' : 'Auto: prefer paired 64-bit, fall back to paired 32-bit'}</option>
                            <option value="32">Counter32（仅 32 位）</option>
                            <option value="64">Counter64（仅 64 位）</option>
                          </select>
                        </label>
                        <div className="rounded-md bg-white/50 px-2 py-2 text-[9px] leading-4 text-black/50 dark:bg-white/[.04] dark:text-white/50">
                          {zh ? '入、出方向必须使用同一位宽；采集器不会把一侧 64 位与另一侧 32 位混算。' : 'Ingress and egress must use the same width.'}
                        </div>
                      </div>
                    </section>

                    {lastTestDetails && (
                      <div className="mt-3 rounded-lg border border-black/8 bg-black/[.02] p-3 text-[10px] dark:border-white/10 dark:bg-white/[.03]">
                        <div className="font-medium text-black/65 dark:text-white/70">{zh ? '最近一次校验明细' : 'Latest verification details'}</div>
                        {lastTestDetails.interface && (
                          <div className="mt-2 flex flex-wrap items-center gap-2">
                            <span className={lastTestDetails.interface.passed ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}>
                              {lastTestDetails.interface.passed ? '✓' : '✕'} {zh ? '接口' : 'Interfaces'}
                            </span>
                            <span className="text-black/50 dark:text-white/50">{lastTestDetails.interface.message}</span>
                          </div>
                        )}
                        {lastTestDetails.hardware && (
                          <div className="mt-1 text-black/45 dark:text-white/45">
                            {zh ? '硬件指标：' : 'Hardware: '}
                            {Object.entries(lastTestDetails.hardware).map(([key, detail]) => `${key} ${detail?.passed ? '✓' : '✕'}`).join(' · ')}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="flex items-center justify-between gap-2 border-t border-black/6 p-4 dark:border-white/8">
                    {editingId ? (
                      <button type="button" onClick={() => void deleteProfile()} disabled={saving} className="inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-[10px] text-red-600 hover:bg-red-500/10 disabled:opacity-40 dark:text-red-400">
                        <Trash2 size={12} />
                        {zh ? '删除并回退默认' : 'Delete / use default'}
                      </button>
                    ) : (
                      <span />
                    )}
                    <button type="button" onClick={() => void saveProfile()} disabled={saving} className="inline-flex items-center gap-1.5 rounded-lg bg-[#00a9ce] px-3 py-2 text-[11px] font-medium text-white hover:bg-[#008fb1] disabled:opacity-50">
                      <Save size={13} />
                      {saving ? (zh ? '保存中…' : 'Saving…') : (zh ? '保存模板' : 'Save profile')}
                    </button>
                  </div>
                </aside>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Sub-Modals */}
      <OidPickerModal
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onSelect={handleOidSelected}
        targetMetricName={pickerTarget?.metricKey}
        initialVendor={form.vendor}
        language={language}
      />

      <MibUploadModal
        open={mibModalOpen}
        onClose={() => setMibModalOpen(false)}
        language={language}
        showToast={showToast}
        onMapNodeToTemplate={handleMibNodeMappedToTemplate}
      />

      <PresetProfilesModal
        open={presetModalOpen}
        onClose={() => setPresetModalOpen(false)}
        onApplyPreset={handleApplyPreset}
        language={language}
        showToast={showToast}
      />
    </div>
  );
};

export default MetricOidProfilesModal;
