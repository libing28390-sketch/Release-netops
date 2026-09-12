import React, { useState } from 'react';
import { ChevronDown, ChevronUp, Search, Settings2, Trash2 } from 'lucide-react';
import { ActionIconButton } from '../../ui/ActionIconButton';

export type MetricMode =
  | 'direct_percent'
  | 'direct_value'
  | 'used_total_percent'
  | 'used_free_percent'
  | 'counter_rate_percent'
  | 'status_code';

export type CounterBits = '' | '32' | '64';
export type Aggregation = 'first' | 'average' | 'max' | 'min' | 'sum';

export interface MetricDefinition {
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

export interface MetricRow {
  key: string;
  definition: MetricDefinition;
}

export interface MetricCatalogEntry {
  key: string;
  labelZh: string;
  labelEn: string;
  defaultMode: MetricMode;
  output: 'percent' | 'status' | 'value';
  defaultUnit: string;
}

export const METRIC_CATALOG: MetricCatalogEntry[] = [
  { key: 'cpu', labelZh: 'CPU 使用率', labelEn: 'CPU', defaultMode: 'direct_percent', output: 'percent', defaultUnit: '%' },
  { key: 'memory', labelZh: '内存使用率', labelEn: 'Memory', defaultMode: 'direct_percent', output: 'percent', defaultUnit: '%' },
  { key: 'temperature', labelZh: '设备温度', labelEn: 'Temperature', defaultMode: 'direct_value', output: 'value', defaultUnit: '°C' },
  { key: 'fan', labelZh: '风扇状态', labelEn: 'Fan status', defaultMode: 'status_code', output: 'status', defaultUnit: 'bool' },
  { key: 'power_supply', labelZh: '电源状态', labelEn: 'Power supply status', defaultMode: 'status_code', output: 'status', defaultUnit: 'bool' },
  { key: 'uptime', labelZh: '设备运行时间', labelEn: 'Device uptime', defaultMode: 'direct_value', output: 'value', defaultUnit: 's' },
  { key: 'storage', labelZh: '存储使用率', labelEn: 'Storage usage', defaultMode: 'used_total_percent', output: 'percent', defaultUnit: '%' },
  { key: 'voltage', labelZh: '电压', labelEn: 'Voltage', defaultMode: 'direct_value', output: 'value', defaultUnit: 'V' },
  { key: 'power', labelZh: '整机功耗', labelEn: 'Power consumption', defaultMode: 'direct_value', output: 'value', defaultUnit: 'W' },
];

export const EMPTY_DEFINITION: MetricDefinition = {
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

export const AGGREGATIONS: Aggregation[] = ['average', 'first', 'max', 'min', 'sum'];
export const METRIC_MODES: MetricMode[] = [
  'direct_percent',
  'direct_value',
  'used_total_percent',
  'used_free_percent',
  'counter_rate_percent',
  'status_code',
];

export const catalogEntry = (key: string) => METRIC_CATALOG.find(item => item.key === key);

export const metricLabel = (key: string, zh: boolean) => {
  const item = catalogEntry(key);
  return item ? (zh ? item.labelZh : item.labelEn) : key;
};

export const modeLabel = (mode: MetricMode, zh: boolean) => {
  if (mode === 'direct_value') return zh ? '直接数值' : 'Direct value';
  if (mode === 'used_total_percent') return zh ? '已用/总量 (%)' : 'Used / total (%)';
  if (mode === 'used_free_percent') return zh ? '已用/(已用+空闲)' : 'Used / (used + free)';
  if (mode === 'counter_rate_percent') return zh ? '计数器速率' : 'Counter rate';
  if (mode === 'status_code') return zh ? '状态码 → 布尔值' : 'Status code → boolean';
  return zh ? '直接百分比（Gauge）' : 'Direct percentage (Gauge)';
};

export const allowedModes = (key: string): MetricMode[] => {
  const item = catalogEntry(key);
  if (!item) return METRIC_MODES;
  if (item.output === 'status') return ['status_code'];
  if (item.output === 'value') return ['direct_value'];
  return ['direct_percent', 'used_total_percent', 'used_free_percent', 'counter_rate_percent'];
};

export const createDefinition = (key: string): MetricDefinition => {
  const item = catalogEntry(key);
  const mode = item?.defaultMode || 'direct_value';
  return {
    ...EMPTY_DEFINITION,
    mode,
    unit: item?.defaultUnit || (mode === 'status_code' ? 'bool' : ''),
    status_ok_values: mode === 'status_code' ? '1,2' : '',
    status_warning_values: '',
    status_fail_values: mode === 'status_code' ? '3,4' : '',
  };
};

export const hasAdvancedSettings = (key: string, definition: MetricDefinition) => {
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

export const hasDefinition = (definition: MetricDefinition) => {
  if (definition.mode === 'used_total_percent') return Boolean(definition.used_oid.trim() && definition.total_oid.trim());
  if (definition.mode === 'used_free_percent') return Boolean(definition.used_oid.trim() && definition.free_oid.trim());
  if (definition.mode === 'counter_rate_percent') return Boolean(definition.oid.trim() && definition.capacity_oid.trim());
  return Boolean(definition.oid.trim());
};

export const toPayload = (definition: MetricDefinition): Record<string, unknown> => {
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

const inputClass =
  'w-full rounded-md border border-black/8 bg-transparent px-2.5 py-1.5 font-mono text-xs outline-none focus:border-[#00bceb]/55 dark:border-white/10';
const selectClass =
  'w-full rounded-md border border-black/8 bg-transparent px-2 py-1.5 text-xs outline-none focus:border-[#00bceb]/55 dark:border-white/10';

interface MetricRowItemProps {
  row: MetricRow;
  zh: boolean;
  onChange: (definition: MetricDefinition) => void;
  onRemove: () => void;
  onPickOid: (metricKey: string, field: 'oid' | 'used_oid' | 'total_oid' | 'free_oid' | 'capacity_oid') => void;
}

export const MetricRowItem: React.FC<MetricRowItemProps> = React.memo(
  ({ row, zh, onChange, onRemove, onPickOid }) => {
    const definition = row.definition;
    const modes = allowedModes(row.key);
    const [advancedOpen, setAdvancedOpen] = useState(() => hasAdvancedSettings(row.key, definition));
    const set = (patch: Partial<MetricDefinition>) => onChange({ ...definition, ...patch });
    const advancedConfigured = hasAdvancedSettings(row.key, definition);

    return (
      <tr className="border-t border-black/5 hover:bg-black/[.01] dark:border-white/6 dark:hover:bg-white/[.01]">
        {/* Metric Name */}
        <td className="w-[180px] px-3.5 py-2.5 align-top">
          <div className="flex items-center gap-1.5">
            <span className="font-semibold text-black/80 dark:text-white/85">{metricLabel(row.key, zh)}</span>
          </div>
          <div className="font-mono text-[10px] text-black/35 dark:text-white/35">{row.key}</div>
        </td>

        {/* OID Input Area */}
        <td className="px-2.5 py-2.5 align-top">
          {definition.mode === 'used_total_percent' ? (
            <div className="grid gap-1.5 sm:grid-cols-2">
              <div className="relative">
                <input
                  value={definition.used_oid}
                  onChange={e => set({ used_oid: e.target.value })}
                  placeholder="已用 OID (例如 1.3.6.1.2.1.25.2.3.1.6)"
                  className={`${inputClass} pr-7`}
                />
                <button
                  type="button"
                  onClick={() => onPickOid(row.key, 'used_oid')}
                  className="absolute right-1.5 top-2 text-[#008aad] hover:text-[#00bceb] dark:text-[#00bceb]"
                  title={zh ? '从 MIB 库拾取已用 OID' : 'Pick Used OID'}
                >
                  <Search size={12} />
                </button>
              </div>
              <div className="relative">
                <input
                  value={definition.total_oid}
                  onChange={e => set({ total_oid: e.target.value })}
                  placeholder="总量 OID (例如 1.3.6.1.2.1.25.2.3.1.5)"
                  className={`${inputClass} pr-7`}
                />
                <button
                  type="button"
                  onClick={() => onPickOid(row.key, 'total_oid')}
                  className="absolute right-1.5 top-2 text-[#008aad] hover:text-[#00bceb] dark:text-[#00bceb]"
                  title={zh ? '从 MIB 库拾取总量 OID' : 'Pick Total OID'}
                >
                  <Search size={12} />
                </button>
              </div>
            </div>
          ) : (
            <div className="relative">
              <input
                value={definition.oid}
                onChange={e => set({ oid: e.target.value })}
                placeholder="SNMP OID，例如 1.3.6.1.4.1.25506.2.6.1.1.1.1.6"
                className={`${inputClass} pr-7`}
              />
              <button
                type="button"
                onClick={() => onPickOid(row.key, 'oid')}
                className="absolute right-2 top-2 text-[#008aad] hover:text-[#00bceb] dark:text-[#00bceb]"
                title={zh ? '从 MIB 库拾取 OID' : 'Pick OID from MIB'}
              >
                <Search size={13} />
              </button>
            </div>
          )}

          {/* Collapsible Advanced Parameters */}
          {advancedOpen && (
            <div className="mt-2.5 rounded-lg border border-black/8 bg-black/[.02] p-2.5 dark:border-white/10 dark:bg-white/[.02]">
              <div className="grid gap-2 sm:grid-cols-3">
                <label className="block">
                  <span className="mb-0.5 block text-[10px] text-black/45 dark:text-white/45">{zh ? '聚合方式' : 'Aggregation'}</span>
                  <select
                    value={definition.aggregation}
                    onChange={e => set({ aggregation: e.target.value as Aggregation })}
                    className={selectClass}
                  >
                    {AGGREGATIONS.map(agg => (
                      <option key={agg} value={agg}>
                        {agg}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block">
                  <span className="mb-0.5 block text-[10px] text-black/45 dark:text-white/45">{zh ? '缩放 (Scale)' : 'Scale multiplier'}</span>
                  <input
                    value={definition.scale}
                    onChange={e => set({ scale: e.target.value })}
                    className={inputClass}
                    placeholder={zh ? '1' : '1 or 1.2'}
                  />
                </label>
                <label className="block">
                  <span className="mb-0.5 block text-[10px] text-black/45 dark:text-white/45">{zh ? '偏移 (Offset)' : 'Offset'}</span>
                  <input
                    value={definition.offset}
                    onChange={e => set({ offset: e.target.value })}
                    className={inputClass}
                    placeholder="0"
                  />
                </label>
              </div>

              {definition.mode === 'status_code' && (
                <div className="mt-2 grid gap-2 sm:grid-cols-3">
                  <label className="block">
                    <span className="mb-0.5 block text-[10px] text-emerald-600 dark:text-emerald-400">{zh ? '正常状态码' : 'OK Code'}</span>
                    <input
                      value={definition.status_ok_values}
                      onChange={e => set({ status_ok_values: e.target.value })}
                      className={inputClass}
                      placeholder="1,2"
                    />
                  </label>
                  <label className="block">
                    <span className="mb-0.5 block text-[10px] text-amber-600 dark:text-amber-400">{zh ? '告警状态码' : 'Warn Code'}</span>
                    <input
                      value={definition.status_warning_values}
                      onChange={e => set({ status_warning_values: e.target.value })}
                      className={inputClass}
                      placeholder="41,31"
                    />
                  </label>
                  <label className="block">
                    <span className="mb-0.5 block text-[10px] text-red-600 dark:text-red-400">{zh ? '故障状态码' : 'Fail Code'}</span>
                    <input
                      value={definition.status_fail_values}
                      onChange={e => set({ status_fail_values: e.target.value })}
                      className={inputClass}
                      placeholder="3,4"
                    />
                  </label>
                </div>
              )}
            </div>
          )}
        </td>

        {/* Mode & Unit */}
        <td className="w-[180px] px-2.5 py-2.5 align-top">
          {modes.length > 1 ? (
            <select
              value={definition.mode}
              onChange={e => set({ mode: e.target.value as MetricMode })}
              className={selectClass}
            >
              {modes.map(mode => (
                <option key={mode} value={mode}>
                  {modeLabel(mode, zh)}
                </option>
              ))}
            </select>
          ) : (
            <div className="rounded-md border border-black/8 bg-black/[.02] px-2 py-1.5 text-xs text-black/65 dark:border-white/10 dark:bg-white/[.04] dark:text-white/70">
              {modeLabel(modes[0], zh)}
            </div>
          )}
        </td>

        {/* Actions & Advanced Toggle */}
        <td className="w-[90px] px-3 py-2.5 text-right align-top">
          <div className="flex items-center justify-end gap-1.5">
            <button
              type="button"
              onClick={() => setAdvancedOpen(prev => !prev)}
              aria-label={zh ? '高级计算与参数选项' : 'Advanced calculation options'}
              className={`rounded-md p-1.5 transition-colors ${
                advancedConfigured || advancedOpen
                  ? 'bg-[#00a9ce]/15 text-[#007391] dark:text-[#00c2e8]'
                  : 'text-black/40 hover:bg-black/5 hover:text-black/70 dark:text-white/40 dark:hover:bg-white/5 dark:hover:text-white/70'
              }`}
              title={zh ? '高级计算与参数选项' : 'Advanced Parameters'}
            >
              <Settings2 size={14} />
            </button>
            <ActionIconButton
              icon={Trash2}
              label={zh ? '移除此指标' : 'Remove Metric'}
              size="sm"
              variant="danger"
              onClick={onRemove}
            />
          </div>
        </td>
      </tr>
    );
  },
);

export default MetricRowItem;
