import React, { useState, useEffect, useMemo } from 'react';
import { Sparkles, X, Check, Search, Cpu, HardDrive, Thermometer, Activity, Network } from 'lucide-react';
import { apiRequest } from '../../api/http';

export interface ModelPresetItem {
  vendor: string;
  model: string;
  category: string;
  description: string;
  metric_definitions: Record<string, any>;
  interface_config?: Record<string, any>;
}

interface PresetProfilesModalProps {
  open: boolean;
  onClose: () => void;
  onApplyPreset: (preset: ModelPresetItem) => void;
  language: string;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
}

const PresetProfilesModal: React.FC<PresetProfilesModalProps> = ({
  open,
  onClose,
  onApplyPreset,
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

  const loadPresets = async () => {
    setLoading(true);
    try {
      const res = await apiRequest<{ success: boolean; data: ModelPresetItem[] }>(
        '/api/platform-registry/mibs/presets/models'
      );
      const items = Array.isArray(res.data) ? res.data : [];
      setPresets(items);
      setSelectedPreset(current => {
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
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
              <Sparkles size={17} />
            </div>
            <div>
              <div className="text-sm font-semibold text-black/85 dark:text-white/90">
                {zh ? '官方主流型号预置模板库' : 'Official Model Metric Presets'}
              </div>
              <div className="mt-0.5 text-[11px] text-black/45 dark:text-white/45">
                {zh
                  ? '开箱即用支持主流交换机与路由器型号，一键导入标准硬件与 IF-MIB 流量采集配置'
                  : 'Ready-to-use SNMP metric profiles for major switch and router models.'}
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
                {filteredPresets.map(item => {
                  const isSelected = selectedPreset?.vendor === item.vendor && selectedPreset?.model === item.model;
                  return (
                    <div
                      key={`${item.vendor}:${item.model}`}
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
                      </div>
                    </div>
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
                      <span className="rounded-full bg-emerald-500/10 px-2.5 py-1 text-[10px] font-medium text-emerald-600 dark:text-emerald-400">
                        {categoryLabel(selectedPreset.category)}
                      </span>
                    </div>
                    <p className="mt-1.5 text-xs text-black/55 dark:text-white/55">
                      {selectedPreset.description}
                    </p>
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
                </div>

                <div className="mt-5 border-t border-black/8 pt-3 dark:border-white/8">
                  <button
                    type="button"
                    onClick={() => {
                      onApplyPreset(selectedPreset);
                      onClose();
                    }}
                    className="inline-flex w-full items-center justify-center gap-1.5 rounded-xl bg-[#00a9ce] py-2.5 text-xs font-semibold text-white shadow-sm hover:bg-[#008fb1]"
                  >
                    <Check size={15} />
                    {zh ? `应用此预置模板（${selectedPreset.vendor} ${selectedPreset.model}）` : `Apply Preset (${selectedPreset.vendor} ${selectedPreset.model})`}
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
