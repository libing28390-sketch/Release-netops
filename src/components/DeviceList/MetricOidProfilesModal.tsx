
import React, { useEffect, useMemo, useState } from 'react';
import { Activity, CheckCircle2, Cpu, GitBranch, Plus, RefreshCw, Save, Search, Trash2, X } from 'lucide-react';
import { apiRequest } from '../../api/http';
import { ALL_VENDOR_NAMES, NETWORK_VENDOR_GROUPS } from '../../pages/AssetManagement/constants';
import Pagination from '../Pagination';

type MetricMode = 'direct_percent' | 'direct_value' | 'used_total_percent' | 'used_free_percent' | 'counter_rate_percent' | 'status_code';
type CounterBits = '' | '32' | '64';
type Aggregation = 'first' | 'average' | 'max' | 'min' | 'sum';

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

interface ProfileForm {
  vendor: string;
  model: string;
  metrics: MetricRow[];
}

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
    counter_bits: textValue(raw.counter_bits) === '32' || textValue(raw.counter_bits) === '64' ? textValue(raw.counter_bits) as CounterBits : '',
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

const createDefaultRows = () => METRIC_CATALOG.map(item => ({ key: item.key, definition: createDefinition(item.key) }));

const profileDefinitions = (profile: MetricOidProfile) => {
  const definitions = { ...(profile.metric_definitions || {}) };
  if (!definitions.cpu && (profile.cpu_config || profile.cpu_oid)) definitions.cpu = profile.cpu_config || { mode: 'direct_percent', oid: profile.cpu_oid };
  if (!definitions.memory && (profile.memory_config || profile.memory_oid)) definitions.memory = profile.memory_config || { mode: 'direct_percent', oid: profile.memory_oid };
  return definitions;
};

const rowsFromProfile = (profile: MetricOidProfile): MetricRow[] => {
  const definitions = profileDefinitions(profile);
  const keys = [...METRIC_CATALOG.map(item => item.key), ...Object.keys(definitions).filter(key => !catalogEntry(key))];
  return Array.from(new Set(keys)).map(key => ({
    key,
    definition: definitionFromProfile(key, definitions[key], key === 'cpu' ? profile.cpu_oid : key === 'memory' ? profile.memory_oid : ''),
  }));
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

const inputClass = 'w-full rounded-md border border-black/8 bg-transparent px-2 py-1.5 font-mono text-[10px] outline-none focus:border-[#00bceb]/55 dark:border-white/10';
const selectClass = 'w-full rounded-md border border-black/8 bg-transparent px-2 py-1.5 text-[10px] outline-none focus:border-[#00bceb]/55 dark:border-white/10';
const tinyLabelClass = 'mb-1 block text-[9px] text-black/45 dark:text-white/45';

const MetricTableRow: React.FC<{
  row: MetricRow;
  zh: boolean;
  onChange: (definition: MetricDefinition) => void;
  onRemove: () => void;
}> = ({ row, zh, onChange, onRemove }) => {
  const item = catalogEntry(row.key);
  const definition = row.definition;
  const modes = allowedModes(row.key);
  const set = (patch: Partial<MetricDefinition>) => onChange({ ...definition, ...patch });
  const sourceLabel = (label: string, value: string, field: 'oid' | 'used_oid' | 'total_oid' | 'free_oid' | 'capacity_oid', placeholder = '1.3.6.1.4.1...') => (
    <label className="block">
      <span className={tinyLabelClass}>{label}</span>
      <input value={value} onChange={event => set({ [field]: event.target.value })} className={inputClass} placeholder={placeholder} />
    </label>
  );

  return (
    <tr className="align-top border-t border-black/6 dark:border-white/8">
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
              {modes.map(mode => <option key={mode} value={mode}>{modeLabel(mode, zh)}</option>)}
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
        <label className="mt-2 block">
          <span className={tinyLabelClass}>{zh ? '表项索引（可选）' : 'Table row selector (optional)'}</span>
          <input value={definition.selector} onChange={event => set({ selector: event.target.value })} className={inputClass} placeholder="1 or 1.2" />
        </label>
      </td>
      <td className="min-w-[190px] px-2 py-3">
        {definition.mode === 'status_code' ? (
          <div className="space-y-2">
            <label className="block"><span className={tinyLabelClass}>{zh ? '正常码 → true' : 'Normal codes → true'}</span><input value={definition.status_ok_values} onChange={event => set({ status_ok_values: event.target.value })} className={inputClass} placeholder="1" /></label>
            <label className="block"><span className={tinyLabelClass}>{zh ? '告警码 → false' : 'Warning codes → false'}</span><input value={definition.status_warning_values} onChange={event => set({ status_warning_values: event.target.value })} className={inputClass} placeholder="4" /></label>
            <label className="block"><span className={tinyLabelClass}>{zh ? '故障码 → false' : 'Failure codes → false'}</span><input value={definition.status_fail_values} onChange={event => set({ status_fail_values: event.target.value })} className={inputClass} placeholder="2,3" /></label>
          </div>
        ) : definition.mode === 'direct_value' ? (
          <label className="block"><span className={tinyLabelClass}>{zh ? '结果单位' : 'Output unit'}</span><input value={definition.unit} onChange={event => set({ unit: event.target.value })} className={inputClass} placeholder="°C / V / W" /></label>
        ) : (
          <div className="rounded-md border border-dashed border-[#00bceb]/30 px-2 py-2 text-[10px] leading-4 text-[#008aad]">{zh ? '数值结果：百分比（0–100）' : 'Numeric result: percentage (0–100)'}</div>
        )}
      </td>
      <td className="min-w-[205px] px-2 py-3">
        {definition.mode === 'status_code' ? (
          <div className="rounded-md bg-black/[.025] px-2 py-2 text-[10px] leading-4 text-black/50 dark:bg-white/[.04] dark:text-white/50">{zh ? '布尔输出：true = 正常，false = 异常，null = 未知码/无数据' : 'Boolean output: true normal, false abnormal, null unknown/no data'}</div>
        ) : definition.mode === 'counter_rate_percent' ? (
          <div className="space-y-2">
            <label className="block"><span className={tinyLabelClass}>{zh ? '计数器位宽（必选）' : 'Counter width (required)'}</span><select value={definition.counter_bits} onChange={event => set({ counter_bits: event.target.value as CounterBits })} className={selectClass}><option value="">{zh ? '选择 32 / 64 位' : 'Select 32 / 64 bits'}</option><option value="32">Counter32</option><option value="64">Counter64</option></select></label>
            <label className="block"><span className={tinyLabelClass}>{zh ? '计数单位' : 'Counter unit'}</span><select value={definition.counter_unit} onChange={event => set({ counter_unit: event.target.value as 'bits' | 'octets' })} className={selectClass}><option value="bits">bits</option><option value="octets">octets × 8</option></select></label>
          </div>
        ) : (
          <div className="grid gap-2 sm:grid-cols-3">
            <label className="block sm:col-span-3"><span className={tinyLabelClass}>{zh ? '聚合方式' : 'Aggregation'}</span><select value={definition.aggregation} onChange={event => set({ aggregation: event.target.value as Aggregation })} className={selectClass}>{AGGREGATIONS.map(value => <option key={value} value={value}>{value}</option>)}</select></label>
            <label className="block"><span className={tinyLabelClass}>{zh ? '缩放' : 'Scale'}</span><input value={definition.scale} onChange={event => set({ scale: event.target.value })} className={inputClass} /></label>
            <label className="block"><span className={tinyLabelClass}>{zh ? '偏移' : 'Offset'}</span><input value={definition.offset} onChange={event => set({ offset: event.target.value })} className={inputClass} /></label>
          </div>
        )}
      </td>
      <td className="w-[52px] px-2 py-3 text-right">
        <button type="button" onClick={onRemove} title={zh ? '移除指标行' : 'Remove metric'} className="rounded-md p-1.5 text-black/35 hover:bg-red-500/10 hover:text-red-600 dark:text-white/35 dark:hover:text-red-400"><Trash2 size={13} /></button>
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
  const [form, setForm] = useState<ProfileForm>({ vendor: '', model: '', metrics: createDefaultRows() });
  const [addMetricKey, setAddMetricKey] = useState('');

  const loadProfiles = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
      if (searchInput.trim()) params.set('search', searchInput.trim());
      const response = await apiRequest<MetricProfileListResponse>('/api/platform-registry/snmp-metric-profiles?' + params.toString());
      setProfiles(Array.isArray(response.data) ? response.data : []);
      setTotal(Number(response.total) || 0);
      if (Number.isFinite(response.page) && response.page >= 1 && response.page !== page) setPage(response.page);
    } catch (error) {
      showToast(error instanceof Error ? error.message : (zh ? '型号指标模板加载失败' : 'Failed to load model metric profiles'), 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) void loadProfiles();
  }, [open, page, pageSize, searchInput]);

  const vendorOptions = useMemo(() => {
    const values = new Set<string>(ALL_VENDOR_NAMES as readonly string[]);
    profiles.forEach(profile => {
      if (profile.vendor.trim()) values.add(profile.vendor.trim());
    });
    return Array.from(values);
  }, [profiles]);

  const resetForm = () => {
    setEditingId(null);
    setForm({ vendor: '', model: '', metrics: createDefaultRows() });
    setAddMetricKey('');
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
    setForm({ vendor: profile.vendor, model: profile.model, metrics: rows });
    setEditorOpen(true);
  };

  const addMetric = () => {
    if (!addMetricKey || form.metrics.some(row => row.key === addMetricKey)) return;
    setForm(prev => ({ ...prev, metrics: [...prev.metrics, { key: addMetricKey, definition: createDefinition(addMetricKey) }] }));
    const next = METRIC_CATALOG.find(item => item.key !== addMetricKey && !form.metrics.some(row => row.key === item.key));
    setAddMetricKey(next?.key || '');
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
    if (!Object.keys(metricDefinitions).length) {
      showToast(zh ? '至少配置一项硬件指标' : 'Configure at least one hardware metric', 'error');
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
    setSaving(true);
    try {
      const isEdit = Boolean(editingId);
      const endpoint = isEdit ? '/api/platform-registry/snmp-metric-profiles/' + editingId : '/api/platform-registry/snmp-metric-profiles';
      await apiRequest(endpoint, {
        method: isEdit ? 'PUT' : 'POST',
        body: JSON.stringify({
          vendor: form.vendor.trim(),
          model: form.model.trim(),
          metric_definitions: metricDefinitions,
          cpu_config: cpuConfig,
          memory_config: memoryConfig,
          cpu_oid: String(cpuConfig.oid || ''),
          memory_oid: String(memoryConfig.oid || ''),
        }),
      });
      showToast(zh ? '指标模板已保存，请执行真实设备验证' : 'Metric profile saved; live verification is required', 'success');
      await loadProfiles();
      onChanged?.();
      setEditorOpen(false);
      resetForm();
    } catch (error) {
      showToast(error instanceof Error ? error.message : (zh ? '保存失败' : 'Save failed'), 'error');
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

  const testProfile = async (profile: MetricOidProfile) => {
    if (!profile.profile_id || !profile.sample_device_id) {
      showToast(zh ? '该型号没有可验证的样例设备' : 'No sample device is available for this model', 'error');
      return;
    }
    setTestingId(profile.profile_id);
    try {
      const endpoint = '/api/platform-registry/snmp-metric-profiles/' + profile.profile_id + '/test';
      const response = await apiRequest<{ success: boolean; data: { passed: boolean; message?: string; sample_hostname?: string } }>(endpoint, {
        method: 'POST',
        body: JSON.stringify({ device_id: profile.sample_device_id }),
      });
      const result = response.data;
      const message = result.passed
        ? (zh ? '验证通过：' + (result.sample_hostname || '样例设备') : 'Verification passed: ' + (result.sample_hostname || 'sample device'))
        : (zh ? '验证失败：' + (result.message || '请检查类型、位宽和公式') : 'Verification failed: ' + (result.message || 'Check type, width, and formula'));
      showToast(message, result.passed ? 'success' : 'error');
      await loadProfiles();
      onChanged?.();
    } catch (error) {
      showToast(error instanceof Error ? error.message : (zh ? '验证请求失败' : 'Verification request failed'), 'error');
    } finally {
      setTestingId(null);
    }
  };

  const validateMapping = async (profile: MetricOidProfile) => {
    if (!profile.profile_id) return;
    try {
      const endpoint = '/api/platform-registry/snmp-metric-profiles/' + profile.profile_id + '/mapping-validation';
      const response = await apiRequest<{ success: boolean; data: { collector_status: string; matched_device_count: number; profile_applied_device_count: number; blocked_device_count: number; metric_keys?: string[] } }>(endpoint);
      const mapping = response.data;
      const message = zh
        ? '映射范围：' + mapping.matched_device_count + ' 台；生效 ' + mapping.profile_applied_device_count + ' 台；阻断 ' + mapping.blocked_device_count + ' 台；指标 ' + ((mapping.metric_keys || []).map(key => metricLabel(key, true)).join('、') || '无') + '。'
        : 'Mapping: ' + mapping.matched_device_count + ' matched; ' + mapping.profile_applied_device_count + ' active; ' + mapping.blocked_device_count + ' blocked; metrics ' + ((mapping.metric_keys || []).join(', ') || 'none') + '.';
      showToast(message, mapping.collector_status === 'active' || mapping.collector_status === 'builtin_only' ? 'info' : 'error');
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
            <div className="flex items-center gap-2 text-sm font-semibold text-black/80 dark:text-white/85"><Cpu size={17} className="text-[#009ec4]" />{zh ? 'SNMP 型号指标模板' : 'SNMP Model Metric Profiles'}</div>
            <p className="mt-1 text-[11px] text-black/45 dark:text-white/45">{zh ? '厂商来自资产管理共享目录；按精确型号维护完整硬件指标。只有通过真实设备类型/公式验证的模板才会被采集器调用。' : 'Vendors use the shared asset catalog. Maintain the complete hardware contract by exact model; only verified definitions are activated.'}</p>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={openCreate} className="inline-flex items-center gap-1.5 rounded-lg bg-[#00a9ce] px-3 py-2 text-[11px] font-medium text-white shadow-sm hover:bg-[#008fb1]"><Plus size={13} />{zh ? '新建' : 'New'}</button>
            {!embedded && <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-black/40 hover:bg-black/5 dark:text-white/45 dark:hover:bg-white/8"><X size={17} /></button>}
          </div>
        </div>

        <div className="flex min-h-0 flex-1 overflow-hidden p-5">
          <section className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-xl border border-black/6 dark:border-white/8">
            <div className="flex items-center gap-2 border-b border-black/6 p-3 dark:border-white/8">
              <div className="relative min-w-0 flex-1"><Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-black/30 dark:text-white/25" /><input value={search} onChange={event => setSearch(event.target.value)} placeholder={zh ? '搜索厂商 / 型号 / 指标' : 'Search vendor / model / metric'} className="w-full rounded-lg border border-black/8 bg-transparent py-1.5 pl-8 pr-2 text-xs outline-none focus:border-[#00bceb]/50 dark:border-white/10" /></div>
              <button type="button" onClick={submitSearch} disabled={loading} className="inline-flex items-center gap-1 rounded-lg border border-[#00bceb]/25 px-2.5 py-1.5 text-[11px] font-medium text-[#008aad] hover:bg-[#00bceb]/10 disabled:opacity-40"><Search size={13} />{zh ? '搜索' : 'Search'}</button>
              <button type="button" onClick={() => void loadProfiles()} disabled={loading} className="rounded-lg border border-black/8 p-2 text-black/45 hover:bg-black/5 disabled:opacity-40 dark:border-white/10 dark:text-white/45 dark:hover:bg-white/8"><RefreshCw size={14} className={loading ? 'animate-spin' : ''} /></button>
            </div>
            <div className="min-h-0 flex-1 overflow-auto">
              {loading ? <div className="p-8 text-center text-xs text-black/40 dark:text-white/40">{zh ? '加载中…' : 'Loading…'}</div> : visibleProfiles.length === 0 ? <div className="p-8 text-center text-xs text-black/40 dark:text-white/40">{zh ? '没有发现型号或搜索无结果。' : 'No model groups found.'}</div> : (
                <table className="w-full text-left text-[11px]"><thead className="sticky top-0 bg-[var(--card-bg)] text-black/40 dark:text-white/40"><tr><th className="px-3 py-2 font-medium">{zh ? '厂商 / 型号' : 'Vendor / Model'}</th><th className="px-3 py-2 font-medium">{zh ? '采集指标' : 'Metrics'}</th><th className="px-3 py-2 font-medium">{zh ? '设备数' : 'Devices'}</th><th className="px-3 py-2 font-medium">{zh ? '状态' : 'Status'}</th><th className="px-3 py-2" /></tr></thead><tbody>{visibleProfiles.map(profile => <tr key={profile.vendor + ':' + profile.model} className="border-t border-black/5 dark:border-white/6"><td className="max-w-[220px] px-3 py-2.5"><div className="truncate font-medium text-black/75 dark:text-white/80">{profile.vendor}</div><div className="truncate text-black/45 dark:text-white/45">{profile.model}</div></td><td className="max-w-[260px] px-3 py-2.5 text-black/55 dark:text-white/55"><div className="flex flex-wrap gap-1">{(profile.metric_keys || Object.keys(profile.metric_definitions || {})).map(key => <span key={key} className="rounded bg-black/[.04] px-1.5 py-0.5 text-[9px] dark:bg-white/[.06]">{metricLabel(key, zh)}</span>)}</div></td><td className="px-3 py-2.5 tabular-nums text-black/55 dark:text-white/55">{profile.device_count}</td><td className="px-3 py-2.5"><div className="flex flex-wrap gap-1"><span className={(profile.configured ? 'bg-slate-500/10 text-slate-600 dark:text-slate-300' : 'bg-amber-500/10 text-amber-600 dark:text-amber-400') + ' rounded-full px-2 py-1 text-[10px]'}>{profile.configured ? (zh ? '已配置' : 'Configured') : (zh ? '使用默认' : 'Default')}</span>{profile.configured && <span className={(profile.verification_status === 'verified' ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400' : profile.verification_status === 'failed' ? 'bg-red-500/10 text-red-600 dark:text-red-400' : 'bg-amber-500/10 text-amber-600 dark:text-amber-400') + ' inline-flex items-center gap-1 rounded-full px-2 py-1 text-[10px]'}>{profile.verification_status === 'verified' && <CheckCircle2 size={10} />}{profile.verification_status === 'verified' ? (zh ? '已验证' : 'Verified') : profile.verification_status === 'failed' ? (zh ? '验证失败' : 'Failed') : (zh ? '待验证' : 'Unverified')}</span>}</div></td><td className="px-3 py-2.5 text-right"><div className="flex items-center justify-end gap-1">{profile.profile_id && <button type="button" onClick={() => void validateMapping(profile)} className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[10px] font-medium text-[#008aad] hover:bg-[#00bceb]/10"><GitBranch size={11} />{zh ? '映射' : 'Map'}</button>}{profile.profile_id && profile.sample_device_id && <button type="button" onClick={() => void testProfile(profile)} disabled={testingId === profile.profile_id} className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[10px] font-medium text-emerald-700 hover:bg-emerald-500/10 disabled:opacity-40 dark:text-emerald-400"><Activity size={11} className={testingId === profile.profile_id ? 'animate-pulse' : ''} />{testingId === profile.profile_id ? (zh ? '测试中' : 'Testing') : (zh ? '验证' : 'Test')}</button>}<button type="button" onClick={() => startEdit(profile)} className="rounded-md px-2 py-1 text-[10px] font-medium text-[#008aad] hover:bg-[#00bceb]/10">{zh ? '编辑' : 'Edit'}</button></div></td></tr>)}</tbody></table>
              )}
            </div>
            <Pagination
              currentPage={page}
              totalItems={total}
              itemsPerPage={pageSize}
              onPageChange={setPage}
              onItemsPerPageChange={size => { setPageSize(size); setPage(1); }}
              language={language}
              alwaysVisible
            />
          </section>

          {editorOpen && (
            <div className="fixed inset-0 z-[130] flex items-center justify-center bg-black/45 p-4 backdrop-blur-sm" onMouseDown={closeEditor}>
              <div className="flex max-h-[94vh] w-full max-w-[1500px] flex-col overflow-hidden rounded-2xl border border-[#00bceb]/25 bg-[var(--card-bg)] shadow-2xl dark:border-white/10" onMouseDown={event => event.stopPropagation()}>
                <div className="flex justify-end border-b border-black/6 px-4 py-2 dark:border-white/8">
                  <button type="button" onClick={closeEditor} className="rounded-lg p-1.5 text-black/40 hover:bg-black/5 dark:text-white/45 dark:hover:bg-white/8" aria-label={zh ? '关闭' : 'Close'}><X size={16} /></button>
                </div>
          <aside className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-xl border border-[#00bceb]/20 bg-[#00bceb]/[.04] dark:bg-[#00bceb]/[.06]">
            <div className="flex items-center justify-between gap-3 border-b border-black/6 p-4 dark:border-white/8"><div><div className="text-xs font-semibold text-black/75 dark:text-white/80">{editingId ? (zh ? '编辑型号模板' : 'Edit model profile') : (zh ? '新增型号模板' : 'New model profile')}</div><div className="mt-1 text-[10px] text-black/40 dark:text-white/40">{zh ? '每一行是一个硬件指标，结果类型由指标类别约束。' : 'One row per hardware metric; the output type is constrained by metric category.'}</div></div><button type="button" onClick={resetForm} className="inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-[10px] text-[#008aad] hover:bg-[#00bceb]/10"><Plus size={12} />{zh ? '新建' : 'New'}</button></div>
            <div className="min-h-0 flex-1 overflow-auto p-4">
              <div className="mb-3 grid gap-2 sm:grid-cols-2">
                <label className="block text-[11px] text-black/55 dark:text-white/55">{zh ? '厂商（同步资产管理）' : 'Vendor (shared with assets)'}<select value={form.vendor} onChange={event => setForm(prev => ({ ...prev, vendor: event.target.value }))} className="mt-1 w-full rounded-lg border border-black/8 bg-white/40 px-2.5 py-2 text-xs outline-none focus:border-[#00bceb]/50 dark:border-white/10 dark:bg-white/[.03]"><option value="">{zh ? '选择设备厂商...' : 'Select device vendor...'}</option>{NETWORK_VENDOR_GROUPS.map(group => <optgroup key={group.key} label={zh ? group.labelZh : group.labelEn}>{group.vendors.map(vendor => <option key={vendor} value={vendor}>{vendor}</option>)}</optgroup>)}{customVendorOptions.length > 0 && <optgroup label={zh ? '历史/自定义厂商' : 'Legacy / custom vendors'}>{customVendorOptions.map(vendor => <option key={vendor} value={vendor}>{vendor}</option>)}</optgroup>}</select></label>
                <label className="block text-[11px] text-black/55 dark:text-white/55">{zh ? '精确型号' : 'Exact model'}<input value={form.model} onChange={event => setForm(prev => ({ ...prev, model: event.target.value }))} className="mt-1 w-full rounded-lg border border-black/8 bg-white/40 px-2.5 py-2 text-xs outline-none focus:border-[#00bceb]/50 dark:border-white/10 dark:bg-white/[.03]" placeholder="C9300-48P" /></label>
              </div>
              <div className="mb-3 flex items-center justify-between gap-2"><div className="text-[10px] font-medium text-black/55 dark:text-white/55">{zh ? '硬件指标明细' : 'Hardware metric definitions'}</div><div className="flex min-w-0 items-center gap-1"><select value={addMetricKey} onChange={event => setAddMetricKey(event.target.value)} className="max-w-[170px] rounded-md border border-black/8 bg-transparent px-2 py-1.5 text-[10px] outline-none dark:border-white/10"><option value="">{zh ? '选择指标...' : 'Select metric...'}</option>{addableMetrics.map(item => <option key={item.key} value={item.key}>{zh ? item.labelZh : item.labelEn}</option>)}</select><button type="button" onClick={addMetric} disabled={!addMetricKey} className="inline-flex shrink-0 items-center gap-1 rounded-md bg-[#00a9ce] px-2 py-1.5 text-[10px] font-medium text-white hover:bg-[#008fb1] disabled:opacity-40"><Plus size={12} />{zh ? '添加行' : 'Add row'}</button></div></div>
              <div className="overflow-x-auto rounded-lg border border-black/7 bg-white/35 dark:border-white/8 dark:bg-white/[.03]">
                <table className="min-w-[1030px] w-full text-left"><thead className="sticky top-0 z-10 bg-[var(--card-bg)] text-[9px] text-black/45 dark:text-white/45"><tr><th className="px-3 py-2 font-medium">{zh ? '指标' : 'Metric'}</th><th className="px-2 py-2 font-medium">{zh ? '采集方式' : 'Mode'}</th><th className="px-2 py-2 font-medium">{zh ? 'OID / 公式' : 'OID / formula'}</th><th className="px-2 py-2 font-medium">{zh ? '结果类型' : 'Output'}</th><th className="px-2 py-2 font-medium">{zh ? '计算与计数器' : 'Calculation / counter'}</th><th className="px-2 py-2" /></tr></thead><tbody>{form.metrics.map(row => <MetricTableRow key={row.key} row={row} zh={zh} onChange={definition => setForm(prev => ({ ...prev, metrics: prev.metrics.map(item => item.key === row.key ? { ...item, definition } : item) }))} onRemove={() => setForm(prev => ({ ...prev, metrics: prev.metrics.filter(item => item.key !== row.key) }))} />)}</tbody></table>
              </div>
              <div className="mt-3 rounded-lg border border-dashed border-[#00bceb]/25 px-3 py-2 text-[10px] leading-4 text-black/45 dark:text-white/45">{zh ? '输出约定：CPU、内存、存储为 0–100 百分比；温度/电压/功耗为带单位数值；风扇和电源状态为 true=正常、false=异常、null=未知。计数器必须明确选择 Counter32 或 Counter64，首个采样只建立基线。' : 'Output contract: CPU, memory, and storage are 0–100 percentages; temperature, voltage, and power are unit-bearing values; fan and PSU are true=normal, false=abnormal, null=unknown. Counters require an explicit 32/64-bit width and the first sample only establishes a baseline.'}</div>
            </div>
            <div className="flex items-center justify-between gap-2 border-t border-black/6 p-4 dark:border-white/8">{editingId ? <button type="button" onClick={() => void deleteProfile()} disabled={saving} className="inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-[10px] text-red-600 hover:bg-red-500/10 disabled:opacity-40 dark:text-red-400"><Trash2 size={12} />{zh ? '删除并回退默认' : 'Delete / use default'}</button> : <span />}<button type="button" onClick={() => void saveProfile()} disabled={saving} className="inline-flex items-center gap-1.5 rounded-lg bg-[#00a9ce] px-3 py-2 text-[11px] font-medium text-white hover:bg-[#008fb1] disabled:opacity-50"><Save size={13} />{saving ? (zh ? '保存中…' : 'Saving…') : (zh ? '保存模板' : 'Save profile')}</button></div>
           </aside>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default MetricOidProfilesModal;
