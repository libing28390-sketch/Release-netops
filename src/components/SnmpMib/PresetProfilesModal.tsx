import React, { useState, useEffect, useMemo } from 'react';
import {
  Activity,
  AlertTriangle,
  Check,
  CheckCircle2,
  Loader2,
  Network,
  Search,
  Sparkles,
  X,
} from 'lucide-react';
import { apiRequest } from '../../api/http';
import { formatMetricValue, formatRawValue, summarizeRawValue } from './components/metricResultFormatters';

export interface ModelPresetItem {
  id?: string;
  /** Present when this binding dialog is opened for an existing custom/official profile. */
  profile_id?: string;
  source?: string;
  family_id?: string;
  vendor: string;
  model: string;
  category: string;
  description: string;
  metric_definitions: Record<string, any>;
  interface_config?: Record<string, any>;
  source_oids?: Record<string, string[]>;
  source_modules?: string[];
  verification_level?: string;
  support_status?: string;
  firmware_scope?: string;
  testable?: boolean;
}

interface PresetMetricTestResult {
  value?: unknown;
  raw_value?: unknown;
  status?: string;
  passed?: boolean;
  message?: string;
  mode?: string;
  oid?: string;
  unit?: string;
  source?: string;
}

interface PresetHardwareTestData {
  host: string;
  status: string;
  message: string;
  metric_count: number;
  metrics: Record<string, PresetMetricTestResult>;
}

interface PresetInterfaceTestData {
  status: string;
  passed?: boolean;
  message: string;
  interfaces?: number;
  selected_counter_bits?: number | null;
}

interface PresetTestResult {
  hardware?: PresetHardwareTestData;
  interface?: PresetInterfaceTestData;
  errors: string[];
  skippedMetrics: string[];
}

type PresetTargetStatus = 'idle' | 'loading' | 'matched' | 'none' | 'error';

const TESTABLE_METRIC_KEYS = new Set([
  'cpu',
  'memory',
  'temperature',
  'fan',
  'power_supply',
  'uptime',
  'storage',
  'voltage',
  'power',
]);

interface PresetProfilesModalProps {
  open: boolean;
  onClose: () => void;
  onApplyPreset: (preset: ModelPresetItem) => void;
  onApplyOfficialPreset?: (preset: ModelPresetItem) => Promise<void>;
  initialPreset?: Pick<ModelPresetItem, 'vendor' | 'model'> | null;
  language: string;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
}

const PresetProfilesModal: React.FC<PresetProfilesModalProps> = ({
  open,
  onClose,
  onApplyPreset,
  onApplyOfficialPreset,
  initialPreset = null,
  language,
  showToast,
}) => {
  const zh = language === 'zh';
  const [presets, setPresets] = useState<ModelPresetItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [vendorFilter, setVendorFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [selectedPreset, setSelectedPreset] = useState<ModelPresetItem | null>(null);
  const [testIp, setTestIp] = useState('');
  const [testDeviceId, setTestDeviceId] = useState('');
  const [testTargetStatus, setTestTargetStatus] = useState<PresetTargetStatus>('idle');
  const [testTargetLabel, setTestTargetLabel] = useState('');
  const [testTargetError, setTestTargetError] = useState('');
  const [testVersion, setTestVersion] = useState<'1' | '2c'>('2c');
  const [testingPreset, setTestingPreset] = useState(false);
  const [presetTestResult, setPresetTestResult] = useState<PresetTestResult | null>(null);
  const [applyingPreset, setApplyingPreset] = useState(false);

  const loadPresets = async () => {
    setLoading(true);
    try {
      const res = await apiRequest<{ success: boolean; data: ModelPresetItem[] }>(
        '/api/platform-registry/mibs/presets/models'
      );
      const items = Array.isArray(res.data) ? res.data : [];
      setPresets(items);
      const preferred = initialPreset
        ? items.find(item => item.vendor === initialPreset.vendor && item.model === initialPreset.model)
        : null;
      setSelectedPreset(current => {
        if (preferred) return preferred;
        if (current && items.some(item => item.vendor === current.vendor && item.model === current.model)) {
          return current;
        }
        return items[0] || null;
      });
    } catch (err) {
      showToast(err instanceof Error ? err.message : (zh ? '加载预置模板失败' : 'Failed to load presets'), 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) {
      setSearch('');
      setVendorFilter('');
      setCategoryFilter('');
      setSelectedPreset(null);
      setTestIp('');
      setTestDeviceId('');
      setTestTargetStatus('idle');
      setTestTargetLabel('');
      setTestTargetError('');
      setTestVersion('2c');
      setTestingPreset(false);
      setPresetTestResult(null);
      setApplyingPreset(false);
      void loadPresets();
    }
  }, [open]);

  const vendorOptions = useMemo(
    () => Array.from(new Set(presets.map(item => item.vendor))).sort((a, b) => a.localeCompare(b)),
    [presets],
  );
  const categoryOptions = useMemo(
    () => Array.from(new Set(presets.map(item => item.category))).sort((a, b) => a.localeCompare(b)),
    [presets],
  );
  const categoryLabel = (category: string) => {
    if (!zh) return category;
    const labels: Record<string, string> = {
      'Campus Switch': '园区交换机',
      'Campus Core Switch': '园区核心交换机',
      'Access Switch': '接入交换机',
      'Aggregation Switch': '汇聚交换机',
      'Aggregation/Core Switch': '汇聚/核心交换机',
      'Data Center Switch': '数据中心交换机',
      'Firewall / Gateway': '防火墙/网关',
    };
    return labels[category] || category;
  };
  const filteredPresets = useMemo(() => {
    const term = search.trim().toLowerCase();
    return presets
      .filter(item => !vendorFilter || item.vendor === vendorFilter)
      .filter(item => !categoryFilter || item.category === categoryFilter)
      .filter(item => {
        if (!term) return true;
        return (
          item.vendor.toLowerCase().includes(term) ||
          item.model.toLowerCase().includes(term) ||
          item.category.toLowerCase().includes(term) ||
          item.description.toLowerCase().includes(term)
        );
      })
      .sort((a, b) => a.vendor.localeCompare(b.vendor) || a.model.localeCompare(b.model));
  }, [categoryFilter, presets, search, vendorFilter]);

  useEffect(() => {
    setSelectedPreset(current => {
      if (current && filteredPresets.some(item => item.vendor === current.vendor && item.model === current.model)) {
        return current;
      }
      return filteredPresets[0] || null;
    });
  }, [filteredPresets]);

  const applyOfficialPreset = async () => {
    if (!selectedPreset || !onApplyOfficialPreset) return;
    setApplyingPreset(true);
    try {
      await onApplyOfficialPreset(selectedPreset);
      onClose();
    } finally {
      setApplyingPreset(false);
    }
  };

  useEffect(() => {
    setPresetTestResult(null);
  }, [selectedPreset?.id, selectedPreset?.vendor, selectedPreset?.model]);

  const supportStatusLabel = (preset: ModelPresetItem) => {
    if (!zh) {
      if (preset.support_status === 'tested_in_md') return 'Tested in MD';
      if (preset.support_status === 'firmware_specific_pending') return 'Firmware-specific OID pending';
      if (preset.support_status === 'oid_pending') return 'OID verification pending';
      if (preset.support_status === 'series_unspecified') return 'Series unspecified in MD';
      return 'Documented in MD';
    }
    if (preset.support_status === 'tested_in_md') return 'MD 已测试';
    if (preset.support_status === 'firmware_specific_pending') return '固件专用 OID 待补';
    if (preset.support_status === 'oid_pending') return 'OID 待 Walk 核验';
    if (preset.support_status === 'series_unspecified') return 'MD 未指定具体型号';
    return 'MD 已列出范围';
  };

  const confirmPresetTarget = async (): Promise<boolean> => {
    const query = testIp.trim();
    if (!query) {
      showToast(zh ? '请输入设备 IP 后确认' : 'Enter a device IP first', 'error');
      return false;
    }
    setTestTargetStatus('loading');
    setTestTargetError('');
    try {
      const response = await apiRequest<{ success: boolean; data: { ip: string; device_id: string; hostname?: string } }>(
        `/api/platform-registry/snmp-walk-target?ip=${encodeURIComponent(query)}`,
      );
      const targetIp = String(response.data?.ip || '').trim();
      const deviceId = String(response.data?.device_id || '').trim();
      if (!targetIp || !deviceId) {
        throw new Error(zh ? '资产未返回完整的设备信息' : 'The asset did not return a complete device target');
      }
      setTestIp(targetIp);
      setTestDeviceId(deviceId);
      setTestTargetLabel([response.data.hostname, targetIp].filter(Boolean).join(' / '));
      setTestTargetStatus('matched');
      showToast(zh ? `已确认测试设备：${targetIp}` : `Test target confirmed: ${targetIp}`, 'success');
      return true;
    } catch (error) {
      const message = error instanceof Error ? error.message : zh ? '未找到该 IP' : 'IP not found';
      setTestDeviceId('');
      setTestTargetLabel('');
      setTestTargetStatus('none');
      setTestTargetError(message);
      showToast(zh ? '未找到该 IP，请先在资产管理中录入' : 'IP not found; add it in asset management first', 'error');
      return false;
    }
  };

  const testSelectedPreset = async () => {
    if (!selectedPreset || selectedPreset.testable === false) {
      showToast(
        zh ? '该型号只有文档范围信息，尚无可直接测试的完整 OID' : 'This row has no complete testable OID set yet',
        'info',
      );
      return;
    }
    if (!testDeviceId) {
      showToast(zh ? '请先输入 IP 并点击确认设备' : 'Confirm a managed device before testing', 'error');
      return;
    }

    const entries = Object.entries(selectedPreset.metric_definitions || {});
    const metricDefinitions = Object.fromEntries(
      entries.filter(([key]) => TESTABLE_METRIC_KEYS.has(key.toLowerCase())),
    );
    const skippedMetrics = entries
      .map(([key]) => key)
      .filter(key => !TESTABLE_METRIC_KEYS.has(key.toLowerCase()));

    setTestingPreset(true);
    setPresetTestResult(null);
    const result: PresetTestResult = { errors: [], skippedMetrics };
    try {
      const requests: Array<Promise<unknown>> = [
        apiRequest<{ success: boolean; data: PresetHardwareTestData }>(
          '/api/platform-registry/snmp-hardware-test',
          {
            method: 'POST',
            body: JSON.stringify({
              device_id: testDeviceId,
              version: testVersion,
              include_default_metrics: true,
              metric_definitions: metricDefinitions,
            }),
          },
        ),
      ];
      if (selectedPreset.interface_config?.enabled) {
        requests.push(
          apiRequest<{ success: boolean; data: PresetInterfaceTestData }>(
            '/api/platform-registry/snmp-interface-test',
            {
              method: 'POST',
              body: JSON.stringify({
                device_id: testDeviceId,
                version: testVersion,
                interface_config: selectedPreset.interface_config,
              }),
            },
          ),
        );
      }

      const responses = await Promise.allSettled(requests);
      const hardwareResponse = responses[0];
      if (hardwareResponse.status === 'fulfilled') {
        result.hardware = (hardwareResponse.value as { data: PresetHardwareTestData }).data;
      } else {
        result.errors.push(zh ? '硬件指标测试失败' : 'Hardware metric test failed');
      }
      const interfaceResponse = responses[1];
      if (interfaceResponse) {
        if (interfaceResponse.status === 'fulfilled') {
          result.interface = (interfaceResponse.value as { data: PresetInterfaceTestData }).data;
        } else {
          result.errors.push(zh ? '接口 IF-MIB 测试失败' : 'Interface IF-MIB test failed');
        }
      }
      setPresetTestResult(result);
      showToast(
        result.errors.length === 0
          ? zh ? '内置模板一键测试已返回结果' : 'Built-in preset test returned results'
          : zh ? '内置模板测试部分返回，请查看明细' : 'Preset test partially returned; review the details',
        result.errors.length === 0 ? 'success' : 'info',
      );
    } finally {
      setTestingPreset(false);
    }
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[150] flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm"
      onMouseDown={onClose}
    >
      <div
        className="flex max-h-[88vh] w-full max-w-[1000px] flex-col overflow-hidden rounded-2xl border border-black/10 bg-[var(--card-bg)] shadow-2xl dark:border-white/10"
        onMouseDown={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-black/8 px-5 py-4 dark:border-white/8">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#00bceb]/10 text-[#008aad] dark:text-[#00bceb]">
              <Sparkles size={17} />
            </div>
            <div>
              <div className="text-sm font-semibold text-black/85 dark:text-white/90">
                {zh ? '官方主流型号预置模板库' : 'Official Model Metric Presets'}
              </div>
              <div className="mt-0.5 text-[11px] text-black/45 dark:text-white/45">
                {zh
                  ? '按 MD 文档厂商分类，展示可导入指标与原始 OID 清单'
                  : 'Vendor-grouped SNMP templates and source OIDs from the MD document.'}
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-black/40 hover:bg-black/5 dark:text-white/45 dark:hover:bg-white/8"
          >
            <X size={17} />
          </button>
        </div>

        {/* Search and classification toolbar */}
        <div className="flex flex-wrap items-center gap-2 border-b border-black/6 bg-black/[.015] p-3 dark:border-white/6 dark:bg-white/[.015]">
          <div className="relative min-w-[200px] flex-1">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-black/30 dark:text-white/25" />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder={zh ? '搜索厂商 / 型号 (如: Cisco, S5700, Catalyst 9300)...' : 'Search vendor or model...'}
              className="w-full rounded-lg border border-black/10 bg-transparent py-1.5 pl-8 pr-3 text-xs outline-none focus:border-[#00bceb]/60 dark:border-white/10"
            />
          </div>
          <select
            value={vendorFilter}
            onChange={e => setVendorFilter(e.target.value)}
            aria-label={zh ? '按厂商筛选' : 'Filter by vendor'}
            className="min-w-[135px] rounded-lg border border-black/10 bg-transparent px-2.5 py-1.5 text-xs outline-none focus:border-[#00bceb]/60 dark:border-white/10"
          >
            <option value="">{zh ? '全部厂商' : 'All vendors'}</option>
            {vendorOptions.map(vendor => <option key={vendor} value={vendor}>{vendor}</option>)}
          </select>
          <select
            value={categoryFilter}
            onChange={e => setCategoryFilter(e.target.value)}
            aria-label={zh ? '按类别筛选' : 'Filter by category'}
            className="min-w-[145px] rounded-lg border border-black/10 bg-transparent px-2.5 py-1.5 text-xs outline-none focus:border-[#00bceb]/60 dark:border-white/10"
          >
            <option value="">{zh ? '全部类别' : 'All categories'}</option>
            {categoryOptions.map(category => <option key={category} value={category}>{categoryLabel(category)}</option>)}
          </select>
          <span className="whitespace-nowrap text-[10px] text-black/40 dark:text-white/40">
            {filteredPresets.length}/{presets.length}
          </span>
        </div>

        {/* Master / Detail Split */}
        <div className="grid min-h-[400px] flex-1 grid-cols-1 overflow-hidden lg:grid-cols-12">
          {/* Preset Model List */}
          <div className="min-h-0 overflow-y-auto border-b border-black/6 p-3 dark:border-white/6 lg:col-span-5 lg:border-b-0 lg:border-r">
            {loading ? (
              <div className="py-16 text-center text-xs text-black/40 dark:text-white/40">
                {zh ? '正在加载官方预置模板…' : 'Loading presets…'}
              </div>
            ) : filteredPresets.length === 0 ? (
              <div className="py-16 text-center text-xs text-black/40 dark:text-white/40">
                {zh ? '未找到匹配的型号预置模板' : 'No presets found.'}
              </div>
            ) : (
              <div className="space-y-2">
                {filteredPresets.map((item, index) => {
                  const isSelected = selectedPreset?.vendor === item.vendor && selectedPreset?.model === item.model;
                  const showVendorGroup = index === 0 || filteredPresets[index - 1]?.vendor !== item.vendor;
                  return (
                    <React.Fragment key={`${item.vendor}:${item.model}`}>
                      {showVendorGroup && (
                        <div className="px-1 pt-2 text-[10px] font-semibold uppercase tracking-wide text-black/40 first:pt-0 dark:text-white/40">
                          {item.vendor}
                        </div>
                      )}
                      <div
                        onClick={() => setSelectedPreset(item)}
                        className={`cursor-pointer rounded-xl border p-3 transition-colors ${
                          isSelected
                            ? 'border-[#00bceb] bg-[#00bceb]/10 dark:bg-[#00bceb]/15'
                            : 'border-black/6 hover:border-black/15 hover:bg-black/[.02] dark:border-white/6 dark:hover:border-white/15 dark:hover:bg-white/[.03]'
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="font-semibold text-xs text-black/85 dark:text-white/90">
                            {item.vendor} {item.model}
                          </div>
                          <span className="rounded bg-black/[.05] px-1.5 py-0.5 text-[9px] text-black/60 dark:bg-white/[.06] dark:text-white/60">
                            {categoryLabel(item.category)}
                          </span>
                        </div>
                      <div className="mt-1 flex flex-wrap gap-1">
                        <span className={`rounded px-1.5 py-0.5 text-[9px] ${
                          item.testable === false
                            ? 'bg-amber-500/10 text-amber-700 dark:text-amber-300'
                            : item.verification_level === 'md_tested'
                              ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
                              : 'bg-slate-500/10 text-slate-600 dark:text-slate-300'
                        }`}>
                          {supportStatusLabel(item)}
                        </span>
                        {item.firmware_scope && (
                          <span className="rounded bg-black/[.04] px-1.5 py-0.5 text-[9px] text-black/55 dark:bg-white/[.06] dark:text-white/55">
                            {item.firmware_scope}
                          </span>
                        )}
                      </div>
                      <div className="mt-1 text-[11px] text-black/50 dark:text-white/50">
                        {item.description}
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1">
                        {Object.keys(item.metric_definitions || {}).map(mKey => (
                          <span
                            key={mKey}
                            className="rounded bg-black/[.04] px-1.5 py-0.5 text-[9px] dark:bg-white/[.06]"
                          >
                            {mKey}
                          </span>
                        ))}
                        {item.interface_config?.enabled && (
                          <span className="rounded bg-[#00bceb]/10 px-1.5 py-0.5 text-[9px] text-[#008aad] dark:text-[#00bceb]">
                            {zh ? '接口' : 'IF-MIB'}
                          </span>
                        )}
                        {item.source_oids && Object.keys(item.source_oids).length > 0 && (
                          <span className="rounded bg-violet-500/10 px-1.5 py-0.5 text-[9px] text-violet-700 dark:text-violet-300">
                            MD OID {Object.values(item.source_oids).reduce((total, values) => total + values.length, 0)}
                          </span>
                        )}
                        {item.source_modules && item.source_modules.length > 0 && (
                          <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[9px] text-amber-700 dark:text-amber-300">
                            {zh ? `模块 ${item.source_modules.length}` : `${item.source_modules.length} modules`}
                          </span>
                        )}
                      </div>
                      </div>
                    </React.Fragment>
                  );
                })}
              </div>
            )}
          </div>

          {/* Preset Detail & Preview */}
          <div className="flex flex-col overflow-y-auto bg-black/[.01] p-5 dark:bg-white/[.01] lg:col-span-7">
            {selectedPreset ? (
              <div className="flex flex-1 flex-col justify-between">
                <div className="space-y-4">
                  <div className="border-b border-black/8 pb-3 dark:border-white/8">
                    <div className="flex items-center justify-between">
                      <div>
                        <span className="text-xs font-semibold text-[#008aad] dark:text-[#00bceb]">
                          {selectedPreset.vendor}
                        </span>
                        <h3 className="text-base font-bold text-black/85 dark:text-white/90">
                          {selectedPreset.model}
                        </h3>
                      </div>
                      <span className="rounded-full bg-[#00bceb]/10 px-2.5 py-1 text-[10px] font-medium text-[#008aad] dark:text-[#00bceb]">
                        {categoryLabel(selectedPreset.category)}
                      </span>
                    </div>
                    <p className="mt-1.5 text-xs text-black/55 dark:text-white/55">
                      {selectedPreset.description}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                        selectedPreset.testable === false
                          ? 'bg-amber-500/10 text-amber-700 dark:text-amber-300'
                          : selectedPreset.verification_level === 'md_tested'
                            ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
                            : 'bg-slate-500/10 text-slate-600 dark:text-slate-300'
                      }`}>
                        {supportStatusLabel(selectedPreset)}
                      </span>
                      {selectedPreset.firmware_scope && (
                        <span className="rounded-full bg-black/[.05] px-2 py-0.5 text-[10px] text-black/55 dark:bg-white/[.06] dark:text-white/55">
                          {selectedPreset.firmware_scope}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Metrics Table */}
                  <div>
                    <div className="text-xs font-semibold text-black/75 dark:text-white/80">
                      {zh ? '配置的硬件采集指标' : 'Configured Hardware Metrics'}
                    </div>
                    <div className="mt-2 space-y-1.5">
                      {Object.entries(selectedPreset.metric_definitions || {}).map(([key, def]: [string, any]) => (
                        <div
                          key={key}
                          className="rounded-lg border border-black/6 bg-white/50 p-2 text-xs dark:border-white/6 dark:bg-white/[.03]"
                        >
                          <div className="flex items-center justify-between">
                            <span className="font-semibold text-black/80 dark:text-white/85 uppercase">
                              {key}
                            </span>
                            <span className="text-[10px] text-black/45 dark:text-white/45">
                              {def.mode} ({def.unit || '-'})
                            </span>
                          </div>
                          <div className="mt-1 font-mono text-[10px] text-[#008aad] dark:text-[#00bceb]">
                            {def.oid || def.used_oid || '-'}
                          </div>
                        </div>
                      ))}
                      {Object.keys(selectedPreset.metric_definitions || {}).length === 0 && (
                        <div className="rounded-lg border border-amber-500/20 bg-amber-500/[.05] p-2.5 text-[11px] text-amber-800 dark:text-amber-200">
                          {zh
                            ? '当前条目没有可直接套用的硬件指标 OID。请先导入对应 MIB 或使用 Walk 核验后再建立模板。'
                            : 'This row has no directly applicable hardware OIDs. Import the matching MIB or verify the OIDs with Walk first.'}
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Interface config summary */}
                  {selectedPreset.interface_config?.enabled && (
                    <div className="rounded-lg border border-[#00bceb]/20 bg-[#00bceb]/[0.04] p-3 text-xs text-black/70 dark:text-white/75">
                      <div className="flex items-center gap-1.5 font-semibold text-[#008aad] dark:text-[#00bceb]">
                        <Network size={14} />
                        {zh ? '接口流量模板已就绪' : 'Interface IF-MIB Ready'}
                      </div>
                      <div className="mt-1 text-[11px] text-black/50 dark:text-white/50">
                        {zh
                          ? `计数器模式: ${selectedPreset.interface_config.counter_mode} · 支持 64位/32位自适应进出流量与错包丢包计数`
                          : `Counter mode: ${selectedPreset.interface_config.counter_mode}`}
                      </div>
                    </div>
                  )}

                  {/* Source OID inventory from the MD document */}
                  {selectedPreset.source_oids && Object.keys(selectedPreset.source_oids).length > 0 && (
                    <div className="rounded-lg border border-violet-500/20 bg-violet-500/[0.04] p-3 text-xs text-black/70 dark:text-white/75">
                      <div className="font-semibold text-violet-700 dark:text-violet-300">
                        {zh ? 'MD 原始 OID 清单' : 'Source OIDs from MD'}
                      </div>
                      <div className="mt-2 max-h-48 space-y-2 overflow-y-auto pr-1">
                        {Object.entries(selectedPreset.source_oids).map(([group, oids]) => (
                          <div key={group}>
                            <div className="text-[10px] font-semibold uppercase text-black/50 dark:text-white/50">
                              {group}
                            </div>
                            <div className="mt-0.5 space-y-0.5 font-mono text-[10px] text-violet-700 dark:text-violet-300">
                              {oids.map(oid => <div key={`${group}:${oid}`}>{oid}</div>)}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {selectedPreset.source_modules && selectedPreset.source_modules.length > 0 && (
                    <div className="rounded-lg border border-amber-500/20 bg-amber-500/[0.04] p-3 text-xs text-amber-800 dark:text-amber-200">
                      <div className="font-semibold">{zh ? 'MD 提到的模块（正文未给具体 OID）' : 'Modules named by MD (concrete OIDs not in text)'}</div>
                      <div className="mt-1 flex flex-wrap gap-1.5 font-mono text-[10px]">
                        {selectedPreset.source_modules.map(module => (
                          <span key={module} className="rounded bg-amber-500/10 px-1.5 py-0.5">{module}</span>
                        ))}
                      </div>
                    </div>
                  )}

                  {!onApplyOfficialPreset && (
                    <>
                  {/* Read-only one-click test for the selected official preset */}
                  <div className="rounded-xl border border-[#00bceb]/20 bg-[#00bceb]/[.035] p-3 text-xs text-black/70 dark:text-white/75">
                    <div className="flex items-center gap-1.5 font-semibold text-[#008aad] dark:text-[#00c2e8]">
                      <Activity size={14} />
                      {zh ? '内置模板一键测试并返回结果' : 'One-click test and return results'}
                    </div>
                    <div className="mt-1 text-[10px] leading-4 text-black/50 dark:text-white/50">
                      {zh
                        ? '仅对已录入资产执行只读 SNMP 测试；Community 与端口由服务端从资产凭据解析，不在页面展示。'
                        : 'Runs a read-only SNMP test against a managed asset; the server resolves the stored credential and port.'}
                    </div>
                    <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_auto_auto]">
                      <input
                        aria-label={zh ? '内置模板测试设备 IP' : 'Preset test device IP'}
                        value={testIp}
                        onChange={event => {
                          setTestIp(event.target.value);
                          setTestDeviceId('');
                          setTestTargetStatus('idle');
                          setTestTargetLabel('');
                          setTestTargetError('');
                          setPresetTestResult(null);
                        }}
                        onKeyDown={event => {
                          if (event.key === 'Enter') {
                            event.preventDefault();
                            void confirmPresetTarget();
                          }
                        }}
                        placeholder={zh ? '输入设备 IP，回车确认' : 'Enter device IP and confirm'}
                        className="rounded-md border border-black/8 bg-transparent px-2.5 py-1.5 text-xs outline-none focus:border-[#00bceb]/55 dark:border-white/10"
                      />
                      <select
                        aria-label={zh ? '内置模板测试 SNMP 版本' : 'Preset test SNMP version'}
                        value={testVersion}
                        onChange={event => setTestVersion(event.target.value as '1' | '2c')}
                        className="rounded-md border border-black/8 bg-transparent px-2.5 py-1.5 text-xs outline-none dark:border-white/10"
                      >
                        <option value="2c">SNMPv2c</option>
                        <option value="1">SNMPv1</option>
                      </select>
                      <button
                        type="button"
                        onClick={() => void confirmPresetTarget()}
                        disabled={testTargetStatus === 'loading'}
                        className="rounded-md border border-[#00bceb]/35 px-2.5 py-1.5 text-xs font-semibold text-[#007391] hover:bg-[#00bceb]/10 disabled:opacity-45 dark:text-[#00c2e8]"
                      >
                        {testTargetStatus === 'loading' ? (zh ? '确认中…' : 'Checking…') : zh ? '确认设备' : 'Confirm device'}
                      </button>
                    </div>
                    <div className="mt-1.5 text-[10px] leading-4">
                      {testTargetStatus === 'matched' && (
                        <span className="text-emerald-700 dark:text-emerald-400">✓ {testTargetLabel || testIp}</span>
                      )}
                      {testTargetStatus === 'none' && (
                        <span className="text-amber-700 dark:text-amber-300">{testTargetError || (zh ? '未找到资产' : 'Asset not found')}</span>
                      )}
                      {testTargetStatus === 'idle' && (
                        <span className="text-black/40 dark:text-white/40">{zh ? '请先确认一个唯一的受管设备。' : 'Confirm one unique managed asset first.'}</span>
                      )}
                    </div>
                    <button
                      type="button"
                      onClick={() => void testSelectedPreset()}
                      disabled={testingPreset || !testDeviceId || selectedPreset.testable === false}
                      className="mt-2 inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-[#00a9ce] py-2 text-xs font-semibold text-white shadow-sm hover:bg-[#008fb1] disabled:cursor-not-allowed disabled:opacity-45"
                    >
                      {testingPreset ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
                      {testingPreset ? (zh ? '正在读取 SNMP…' : 'Reading SNMP…') : zh ? '一键测试当前内置模板' : 'Test this built-in preset'}
                    </button>
                    {selectedPreset.testable === false && (
                      <div className="mt-1.5 flex items-start gap-1 text-[10px] leading-4 text-amber-700 dark:text-amber-300">
                        <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                        {zh ? '该条目仅用于展示 MD 范围，具体 OID 尚未核验，因此暂不执行一键测试。' : 'Documentation-only row; concrete OIDs are not verified, so one-click testing is disabled.'}
                      </div>
                    )}

                    {presetTestResult && (
                      <div className="mt-3 space-y-2 border-t border-[#00bceb]/15 pt-2.5">
                        {presetTestResult.hardware && (
                          <div>
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <span className="font-semibold">{zh ? '硬件结果' : 'Hardware result'}</span>
                              <span className={`rounded-full px-2 py-0.5 text-[10px] ${
                                presetTestResult.hardware.status === 'ok'
                                  ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
                                  : 'bg-amber-500/10 text-amber-700 dark:text-amber-300'
                              }`}>
                                {presetTestResult.hardware.status}
                              </span>
                            </div>
                            <div className="mt-1 text-[10px] text-black/50 dark:text-white/50">
                              {presetTestResult.hardware.message} · {presetTestResult.hardware.metric_count} {zh ? '项' : 'metrics'}
                            </div>
                            <div className="mt-1.5 grid gap-1 sm:grid-cols-2">
                              {Object.entries(presetTestResult.hardware.metrics || {}).map(([key, detail]) => {
                                const hasRawValue = detail.raw_value !== undefined && detail.raw_value !== detail.value;
                                return (
                                  <div key={key} className="min-w-0 rounded border border-black/6 bg-white/45 px-2 py-1.5 dark:border-white/8 dark:bg-white/[.03]">
                                    <div className="flex items-center justify-between gap-2">
                                      <span className="truncate font-medium" title={key}>{key}</span>
                                      <span className={detail.status === 'ok' ? 'text-emerald-700 dark:text-emerald-300' : 'text-amber-700 dark:text-amber-300'}>
                                        {detail.status || '-'}
                                      </span>
                                    </div>
                                    <div className="mt-0.5 break-words font-mono text-[10px] text-black/55 dark:text-white/55">
                                      {formatMetricValue(key, detail, zh)}
                                    </div>
                                    {hasRawValue && (
                                      <div className="mt-0.5 truncate text-[9px] text-black/40 dark:text-white/40" title={formatRawValue(detail.raw_value)}>
                                        {zh ? '原始摘要：' : 'Raw summary: '}{summarizeRawValue(detail.raw_value, zh)}
                                      </div>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        )}
                        {presetTestResult.interface && (
                          <div className="rounded border border-violet-500/15 bg-violet-500/[.035] px-2 py-1.5">
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-semibold">{zh ? '接口 IF-MIB 结果' : 'Interface IF-MIB result'}</span>
                              <span className={presetTestResult.interface.passed ? 'text-emerald-700 dark:text-emerald-300' : 'text-amber-700 dark:text-amber-300'}>
                                {presetTestResult.interface.passed ? 'ok' : presetTestResult.interface.status}
                              </span>
                            </div>
                            <div className="mt-0.5 text-[10px] text-black/50 dark:text-white/50">
                              {presetTestResult.interface.message} · {presetTestResult.interface.interfaces || 0} {zh ? '个接口' : 'interfaces'}
                            </div>
                          </div>
                        )}
                        {presetTestResult.skippedMetrics.length > 0 && (
                          <div className="text-[10px] text-amber-700 dark:text-amber-300">
                            {zh ? `未送入硬件测试的文档字段：${presetTestResult.skippedMetrics.join('、')}` : `Document fields skipped by hardware test: ${presetTestResult.skippedMetrics.join(', ')}`}
                          </div>
                        )}
                        {presetTestResult.errors.map(error => (
                          <div key={error} className="text-[10px] text-amber-700 dark:text-amber-300">{error}</div>
                        ))}
                      </div>
                    )}
                  </div>
                    </>
                  )}
                </div>

                <div className="mt-5 space-y-2 border-t border-black/8 pt-3 dark:border-white/8">
                  {onApplyOfficialPreset && (
                    <button
                      type="button"
                      disabled={applyingPreset || selectedPreset.testable === false || Object.keys(selectedPreset.metric_definitions || {}).length === 0}
                      onClick={() => void applyOfficialPreset()}
                      className="inline-flex w-full items-center justify-center gap-1.5 rounded-xl bg-[#00a9ce] py-2.5 text-xs font-semibold text-white shadow-sm hover:bg-[#008fb1] disabled:cursor-not-allowed disabled:opacity-45"
                    >
                      {applyingPreset ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
                      {applyingPreset
                          ? (zh ? '准备绑定…' : 'Preparing binding…')
                        : selectedPreset.testable === false
                          ? (zh ? '文档范围条目，需先核验 OID' : 'Documentation-only row; verify OIDs first')
                          : (zh ? `测试并绑定（${selectedPreset.vendor} ${selectedPreset.model}）` : `Test & bind (${selectedPreset.vendor} ${selectedPreset.model})`)}
                    </button>
                  )}
                  <button
                    type="button"
                    disabled={applyingPreset || selectedPreset.testable === false || Object.keys(selectedPreset.metric_definitions || {}).length === 0}
                    onClick={() => {
                      onApplyPreset(selectedPreset);
                      onClose();
                    }}
                    className="inline-flex w-full items-center justify-center gap-1.5 rounded-xl border border-[#00bceb]/30 bg-[#00bceb]/8 py-2 text-xs font-semibold text-[#008aad] hover:bg-[#00bceb]/15 disabled:cursor-not-allowed disabled:opacity-45 dark:text-[#00bceb]"
                  >
                    <Sparkles size={14} />
                    {zh ? '复制并自定义' : 'Clone & customize'}
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
};

export default PresetProfilesModal;
