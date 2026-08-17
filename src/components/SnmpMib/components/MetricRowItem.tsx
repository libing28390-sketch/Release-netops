import React, { useState } from 'react';
import { ChevronDown, ChevronUp, Search, Trash2 } from 'lucide-react';

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
  if (mode === 'used_total_percent') return zh ? '已用 / 总量' : 'Used / total';
  if (mode === 'used_free_percent') return zh ? '已用 /（已用 + 空闲）' : 'Used / (used + free)';
  if (mode === 'counter_rate_percent') return zh ? '计数器速率 / 容量' : 'Counter rate / capacity';
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
    status_ok_values: mode === 'status_code' ? '1' : '',
    status_warning_values: '',
    status_fail_values: mode === 'status_code' ? '2,3' : '',
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
  'w-full rounded-md border border-black/8 bg-transparent px-2 py-1.5 font-mono text-[10px] outline-none focus:border-[#00bceb]/55 dark:border-white/10';
const selectClass =
  'w-full rounded-md border border-black/8 bg-transparent px-2 py-1.5 text-[10px] outline-none focus:border-[#00bceb]/55 dark:border-white/10';
const tinyLabelClass = 'mb-1 block text-[9px] text-black/45 dark:text-white/45';

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
            {zh ? 'MIB 拾取' : 'Pick'}
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
        onClick={() => setAdvancedOpen(prev => !prev)}
        className="inline-flex items-center gap-1 text-[10px] text-black/50 hover:text-black/80 dark:text-white/50 dark:hover:text-white/80"
      >
        {advancedOpen ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
        <span>{zh ? '高级计算与表项' : 'Advanced calculation'}</span>
        {advancedConfigured && (
          <span className="rounded bg-[#00bceb]/10 px-1 py-0.2 text-[8px] font-medium text-[#008aad]">
            {zh ? '已改' : 'Custom'}
          </span>
        )}
      </button>
    );

    return (
      <tr className="border-t border-black/5 hover:bg-black/[.01] dark:border-white/6 dark:hover:bg-white/[.01]">
        {/* Metric Name */}
        <td className="min-w-[130px] px-3 py-3 align-top">
          <div className="font-semibold text-black/80 dark:text-white/85">{metricLabel(row.key, zh)}</div>
          <div className="mt-0.5 font-mono text-[9px] text-black/35 dark:text-white/35">{row.key}</div>
        </td>

        {/* Mode */}
        <td className="min-w-[170px] px-2 py-3 align-top">
          <label className="block">
            <span className={tinyLabelClass}>{zh ? '采集方式' : 'Collection mode'}</span>
            {modes.length === 1 ? (
              <div className="rounded-md border border-black/8 bg-black/[.02] px-2 py-1.5 text-[10px] font-medium text-black/65 dark:border-white/10 dark:bg-white/[.04] dark:text-white/70">
                {modeLabel(modes[0], zh)}
              </div>
            ) : (
              <select
                value={definition.mode}
                onChange={event => set({ mode: event.target.value as MetricMode })}
                className={selectClass}
              >
                {modes.map(mode => (
                  <option key={mode} value={mode}>
                    {modeLabel(mode, zh)}
                  </option>
                ))}
              </select>
            )}
          </label>
        </td>

        {/* OIDs */}
        <td className="min-w-[280px] px-2 py-3 align-top">
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
              {sourceLabel(
                definition.mode === 'counter_rate_percent' ? (zh ? '计数器 OID' : 'Counter OID') : 'OID',
                definition.oid,
                'oid',
              )}
              {definition.mode === 'counter_rate_percent' &&
                sourceLabel(
                  zh ? '容量 OID（单位/秒）' : 'Capacity OID (units/sec)',
                  definition.capacity_oid,
                  'capacity_oid',
                )}
            </div>
          )}
        </td>

        {/* Output & Status Mapping */}
        <td className="min-w-[190px] px-2 py-3 align-top">
          {definition.mode === 'status_code' ? (
            <label className="block">
              <span className={tinyLabelClass}>{zh ? '正常码 → true' : 'Normal codes → true'}</span>
              <input
                value={definition.status_ok_values}
                onChange={event => set({ status_ok_values: event.target.value })}
                className={inputClass}
                placeholder="1"
              />
            </label>
          ) : definition.mode === 'direct_value' ? (
            <label className="block">
              <span className={tinyLabelClass}>{zh ? '结果单位' : 'Output unit'}</span>
              <input
                value={definition.unit}
                onChange={event => set({ unit: event.target.value })}
                className={inputClass}
                placeholder="°C / V / W"
              />
            </label>
          ) : (
            <div className="rounded-md border border-dashed border-[#00bceb]/30 px-2 py-2 text-[10px] leading-4 text-[#008aad]">
              {zh ? '数值结果：百分比（0–100）' : 'Numeric result: percentage (0–100)'}
            </div>
          )}
        </td>

        {/* Calculation & Advanced Drawer */}
        <td className="min-w-[215px] px-2 py-3 align-top">
          <div className="space-y-2">
            {definition.mode === 'status_code' && (
              <div className="rounded-md bg-black/[.025] px-2 py-2 text-[10px] leading-4 text-black/50 dark:bg-white/[.04] dark:text-white/50">
                {zh
                  ? '布尔输出：true = 正常，false = 异常，null = 未知码/无数据'
                  : 'Boolean output: true normal, false abnormal, null unknown'}
              </div>
            )}
            {definition.mode === 'counter_rate_percent' && (
              <>
                <label className="block">
                  <span className={tinyLabelClass}>{zh ? '计数器位宽（必选）' : 'Counter width (required)'}</span>
                  <select
                    value={definition.counter_bits}
                    onChange={event => set({ counter_bits: event.target.value as CounterBits })}
                    className={selectClass}
                  >
                    <option value="">{zh ? '选择 32 / 64 位' : 'Select 32 / 64 bits'}</option>
                    <option value="32">Counter32</option>
                    <option value="64">Counter64</option>
                  </select>
                </label>
                <label className="block">
                  <span className={tinyLabelClass}>{zh ? '计数单位' : 'Counter unit'}</span>
                  <select
                    value={definition.counter_unit}
                    onChange={event => set({ counter_unit: event.target.value as 'bits' | 'octets' })}
                    className={selectClass}
                  >
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
                      <input
                        value={definition.status_warning_values}
                        onChange={event => set({ status_warning_values: event.target.value })}
                        className={inputClass}
                        placeholder="4"
                      />
                    </label>
                    <label className="block">
                      <span className={tinyLabelClass}>{zh ? '故障码 → false' : 'Failure codes → false'}</span>
                      <input
                        value={definition.status_fail_values}
                        onChange={event => set({ status_fail_values: event.target.value })}
                        className={inputClass}
                        placeholder="2,3"
                      />
                    </label>
                  </>
                )}
                <label className="block">
                  <span className={tinyLabelClass}>{zh ? '表项索引（可选）' : 'Table row selector (optional)'}</span>
                  <input
                    value={definition.selector}
                    onChange={event => set({ selector: event.target.value })}
                    className={inputClass}
                    placeholder="1 or 1.2"
                  />
                </label>
                <label className="block">
                  <span className={tinyLabelClass}>{zh ? '聚合方式' : 'Aggregation'}</span>
                  <select
                    value={definition.aggregation}
                    onChange={event => set({ aggregation: event.target.value as Aggregation })}
                    className={selectClass}
                  >
                    {AGGREGATIONS.map(value => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="grid gap-2 sm:grid-cols-2">
                  <label className="block">
                    <span className={tinyLabelClass}>{zh ? '缩放倍数' : 'Scale multiplier'}</span>
                    <div className="space-y-1">
                      <input
                        value={definition.scale}
                        onChange={event => set({ scale: event.target.value })}
                        className={inputClass}
                      />
                      <div className="flex flex-wrap gap-1">
                        {['1', '0.1', '0.01', '0.001'].map(val => (
                          <button
                            key={val}
                            type="button"
                            onClick={() => set({ scale: val })}
                            className={`rounded px-1 py-0.5 text-[8px] font-mono transition-colors ${
                              definition.scale === val
                                ? 'bg-[#00bceb]/20 font-semibold text-[#008aad]'
                                : 'bg-black/[.04] text-black/50 hover:bg-black/[.08] dark:bg-white/[.06] dark:text-white/50'
                            }`}
                          >
                            ×{val}
                          </button>
                        ))}
                      </div>
                    </div>
                  </label>
                  <label className="block">
                    <span className={tinyLabelClass}>{zh ? '偏移' : 'Offset'}</span>
                    <input
                      value={definition.offset}
                      onChange={event => set({ offset: event.target.value })}
                      className={inputClass}
                    />
                  </label>
                </div>
              </div>
            )}
          </div>
        </td>

        {/* Remove Row Button */}
        <td className="w-[48px] px-2 py-3 text-right align-top">
          <button
            type="button"
            onClick={onRemove}
            title={zh ? '移除指标行' : 'Remove metric'}
            className="rounded-md p-1.5 text-black/35 hover:bg-red-500/10 hover:text-red-600 dark:text-white/35 dark:hover:text-red-400"
          >
            <Trash2 size={13} />
          </button>
        </td>
      </tr>
    );
  },
);

MetricRowItem.displayName = 'MetricRowItem';
