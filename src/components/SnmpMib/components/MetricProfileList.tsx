import { DataTable } from '../../DataTable';
import React, { useState, useEffect, useMemo } from 'react';
import {
  Check,
  CheckCircle2,
  Database,
  Activity,
  Eye,
  Loader2,
  Link2,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  Sparkles,
  Server,
  Terminal,
  Pencil,
  Trash2,
  X,
} from 'lucide-react';
import Pagination from '../../Pagination';
import { ActionIconButton } from '../../ui/ActionIconButton';
import { TableActionCell, TableActionHeader } from '../../ui/TableActionColumn';
import { metricLabel } from './MetricRowItem';
import { ModelPresetItem } from '../PresetProfilesModal';
import type { CandidateDevice } from './LiveWalkInspector';
import type { TableExportData } from '../../ui/TableExportMenu';

export interface MetricOidProfile {
  profile_id: string | null;
  vendor: string;
  model: string;
  platform?: string;
  model_pattern?: string;
  software_version_scope?: string[];
  min_version?: string;
  max_version?: string;
  excluded_versions?: string[];
  scope_priority?: number;
  template_name?: string;
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
  collector_status?:
    | 'active'
    | 'blocked_unverified'
    | 'blocked_failed'
    | 'no_matching_device'
    | 'template_required'
    | 'builtin_only'
    | string;
  interface_config?: Record<string, unknown>;
  interface_configured?: boolean;
  interface_verification_status?: 'verified' | 'failed' | 'unverified' | string;
  interface_collector_status?: string;
  sample_device_id?: string | null;
  sample_device_ip?: string | null;
  sample_device_status?: string | null;
  platforms: string[];
  source?: string;
  official_preset_id?: string;
  bound_device_count?: number;
  inventory_device_count?: number;
  unbound_device_count?: number;
  applied_preset_id?: string;
  applied_preset_family_id?: string;
}

export type StatusFilterType = 'all' | 'verified' | 'unverified' | 'failed' | 'configured' | 'default';
export type ProfileTabType = 'all' | 'custom' | 'presets';

interface MetricProfileListProps {
  profiles: MetricOidProfile[];
  presets?: ModelPresetItem[];
  loading: boolean;
  total: number;
  page: number;
  pageSize: number;
  search: string;
  language: string;
  onSearchChange: (search: string) => void;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
  onRefresh: () => void;
  onOpenCreate: () => void;
  onOpenPresets: (preset?: ModelPresetItem) => void;
  onApplyOfficialPreset?: (preset: ModelPresetItem, fallbackDevice?: CandidateDevice) => Promise<void>;
  onOpenBinding?: (profile: MetricOidProfile) => void;
  onOpenMibs: () => void;
  onEdit: (profile: MetricOidProfile) => void;
  onDeleteProfile?: (profile: MetricOidProfile) => void;
  loadAllProfilesForExport: (search: string) => Promise<MetricOidProfile[]>;
  onOpenSnmpWalk?: (item: MetricOidProfile | ModelPresetItem, target?: CandidateDevice) => void;
  onOpenCollectionResult?: (item: MetricOidProfile | ModelPresetItem, target?: CandidateDevice) => void;
  onValidateMapping: (profile: MetricOidProfile) => void;
}

interface PresetDisplayGroup {
  key: string;
  primary: ModelPresetItem;
  items: ModelPresetItem[];
  models: string[];
  metricKeys: string[];
  interfaceEnabled: boolean;
}

const displayKey = (value: unknown) => String(value || '').trim().toLowerCase().replace(/\s+/g, ' ');

const modelDisplayKey = (value: unknown) => displayKey(value).replace(/[^a-z0-9\u4e00-\u9fff]+/g, '');

const presetCategoryLabel = (category: string, zh: boolean) => {
  if (!zh) return category;
  const labels: Record<string, string> = {
    'Campus Switch': '园区网交换机',
    'Campus Core Switch': '园区核心交换机',
    'Access Switch': '接入交换机',
    'Aggregation Switch': '汇聚交换机',
    'Aggregation/Core Switch': '汇聚/核心交换机',
    'Data Center Switch': '数据中心交换机',
    'Firewall / Gateway': '防火墙/网关',
  };
  return labels[category] || category;
};

const vendorDisplayLabel = (vendor: string, zh: boolean) => {
  if (!zh) return vendor;
  return ({ H3C: '华三', Huawei: '华为', ZTE: '中兴', Cisco: '思科' } as Record<string, string>)[vendor] || vendor;
};

const buildPresetDisplayGroups = (items: ModelPresetItem[]): PresetDisplayGroup[] => {
  const groups = new Map<string, ModelPresetItem[]>();
  items.forEach(item => {
    const key = displayKey(item.family_id || `${item.vendor}:${item.category}`);
    groups.set(key, [...(groups.get(key) || []), item]);
  });
  return Array.from(groups.entries()).map(([key, groupItems]) => {
    const sortedItems = [...groupItems].sort((a, b) => a.model.localeCompare(b.model, undefined, { numeric: true }));
    return {
      key,
      primary: sortedItems[0],
      items: sortedItems,
      models: sortedItems.map(item => item.model),
      metricKeys: Array.from(new Set(sortedItems.flatMap(item => Object.keys(item.metric_definitions || {})))).sort(),
      interfaceEnabled: sortedItems.some(item => item.interface_config?.enabled),
    };
  }).sort((a, b) => {
    const vendorCompare = a.primary.vendor.localeCompare(b.primary.vendor);
    return vendorCompare || a.primary.category.localeCompare(b.primary.category);
  });
};

const presetMatchesSearch = (preset: ModelPresetItem, term: string) => (
  !term || [preset.vendor, preset.model, preset.category, preset.description]
    .some(value => String(value || '').toLowerCase().includes(term))
);

const profilesForPresetGroup = (group: PresetDisplayGroup, profiles: MetricOidProfile[]) => {
  const groupModels = new Set(group.items.map(item => modelDisplayKey(item.model)));
  return profiles.filter(profile => (
    displayKey(profile.vendor) === displayKey(group.primary.vendor) &&
    groupModels.has(modelDisplayKey(profile.model))
  ));
};

// Inventory-only rows are generated when a device has no saved model profile.
// They are model matches only, not templates managed by this page. Keep them
// available for official-preset matching counts while excluding them from the
// applied-template list itself.
const isBuiltinFallbackProfile = (profile: MetricOidProfile) => (
  !profile.profile_id && !profile.configured && !profile.interface_configured
);

const matchesProfileFilters = (profile: MetricOidProfile, vendorFilter: string, statusFilter: StatusFilterType) => {
  if (isBuiltinFallbackProfile(profile)) return false;
  if (vendorFilter && profile.vendor.toLowerCase() !== vendorFilter.toLowerCase()) return false;
  if (statusFilter === 'verified') return profile.verification_status === 'verified' || profile.interface_verification_status === 'verified';
  if (statusFilter === 'unverified') return (
    (profile.configured && profile.verification_status === 'unverified') ||
    (profile.interface_configured && profile.interface_verification_status === 'unverified')
  );
  if (statusFilter === 'failed') return profile.verification_status === 'failed' || profile.interface_verification_status === 'failed';
  if (statusFilter === 'configured') return profile.configured || profile.interface_configured;
  if (statusFilter === 'default') return !profile.configured && !profile.interface_configured;
  return true;
};

export function buildMetricProfileExportData(
  profiles: MetricOidProfile[],
  presets: ModelPresetItem[],
  options: { vendorFilter: string; statusFilter: StatusFilterType; activeTab: ProfileTabType; search: string; zh: boolean },
): TableExportData {
  const { vendorFilter, statusFilter, activeTab, search, zh } = options;
  const headers = [
    zh ? '厂商' : 'Vendor',
    zh ? '模板来源' : 'Template source',
    zh ? '分类' : 'Category',
    zh ? '型号' : 'Model',
    zh ? '型号匹配模式' : 'Model pattern',
    zh ? '平台' : 'Platforms',
    zh ? '软件版本范围' : 'Software version scope',
    zh ? '采集指标' : 'Collected metrics',
  ];
  const term = search.trim().toLowerCase();
  const groups = buildPresetDisplayGroups(presets).filter(group => (
    (!vendorFilter || group.primary.vendor.toLowerCase() === vendorFilter.toLowerCase()) &&
    group.items.some(item => presetMatchesSearch(item, term))
  ));
  const profileRows = profiles
    .filter(profile => matchesProfileFilters(profile, vendorFilter, statusFilter))
    .map(profile => {
      const officialApplied = Boolean(
        profile.source === 'official' || profile.source === 'official_preset' || profile.official_preset_id || profile.applied_preset_id,
      );
      const metricKeys = profile.metric_keys || Object.keys(profile.metric_definitions || {});
      const metricNames = metricKeys.map(key => metricLabel(key, zh));
      if (profile.interface_configured) metricNames.push(zh ? '接口 IF-MIB' : 'IF-MIB');
      if (!profile.configured && !profile.interface_configured) metricNames.push(zh ? '默认 CPU / 内存' : 'Default CPU/Mem');
      return [
        profile.vendor,
        officialApplied ? (zh ? '官方已绑定' : 'Official bound') : (zh ? '自定义模板' : 'Custom'),
        '-',
        profile.model,
        profile.model_pattern && profile.model_pattern !== profile.model ? profile.model_pattern : '-',
        profile.platforms?.length ? profile.platforms.join(', ') : '-',
        profile.software_version_scope?.length ? profile.software_version_scope.join(', ') : '-',
        metricNames.join(', ') || '-',
      ];
    });
  const presetRows = groups.map(group => {
    const unique = (values: string[]) => Array.from(new Set(values.map(value => value.trim()).filter(Boolean)));
    const patterns = unique(group.items
      .filter(item => item.model_pattern && item.model_pattern !== item.model)
      .map(item => item.model_pattern || ''));
    const platforms = unique(group.items.flatMap(item => item.platforms || []));
    const versions = unique(group.items.flatMap(item => item.software_version_scope || []));
    const metrics = group.metricKeys.map(key => metricLabel(key, zh));
    if (group.interfaceEnabled) metrics.push(zh ? '接口 IF-MIB' : 'IF-MIB');
    return [
      vendorDisplayLabel(group.primary.vendor, zh),
      zh ? '官方预置' : 'Official preset',
      presetCategoryLabel(group.primary.category || 'Network Device', zh),
      group.models.join(', '),
      patterns.length ? patterns.join(', ') : '-',
      platforms.length ? platforms.join(', ') : '-',
      versions.length ? versions.join(', ') : '-',
      metrics.join(', ') || (zh ? '暂无硬件指标' : 'No hardware metrics'),
    ];
  });
  return {
    headers,
    rows: [
      ...((activeTab === 'all' || activeTab === 'presets') ? presetRows : []),
      ...((activeTab === 'all' || activeTab === 'custom') ? profileRows : []),
    ],
  };
}

export const MetricProfileList: React.FC<MetricProfileListProps> = ({
  profiles,
  presets = [],
  loading,
  total,
  page,
  pageSize,
  search,
  language,
  onSearchChange,
  onPageChange,
  onPageSizeChange,
  onRefresh,
  onOpenCreate,
  onOpenPresets,
  onApplyOfficialPreset,
  onOpenBinding,
  onOpenMibs,
  onEdit,
  onDeleteProfile,
  onOpenSnmpWalk,
  onOpenCollectionResult,
  onValidateMapping,
  loadAllProfilesForExport,
}) => {
  const zh = language === 'zh';
  const [searchInput, setSearchInput] = useState(search);
  const [vendorFilter, setVendorFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilterType>('all');
  const [activeTab, setActiveTab] = useState<ProfileTabType>('all');
  const [applyingPresetKey, setApplyingPresetKey] = useState<string | null>(null);

  // Sync external search prop if changed
  useEffect(() => {
    setSearchInput(search);
  }, [search]);

  // Debounce search input (300ms)
  useEffect(() => {
    const timer = setTimeout(() => {
      if (searchInput !== search) {
        onSearchChange(searchInput.trim());
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  // Available vendor list from current profile items and presets
  const vendorOptions = useMemo(() => {
    const set = new Set<string>();
    profiles.forEach(p => {
      if (p.vendor?.trim()) set.add(p.vendor.trim());
    });
    presets.forEach(p => {
      if (p.vendor?.trim()) set.add(p.vendor.trim());
    });
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [profiles, presets]);

  // Client-side quick filter on saved custom profiles. Inventory-only model
  // matches (for example H3C F1090/S6800) are not templates and stay hidden.
  const filteredProfiles = useMemo(() => {
    return profiles.filter(profile => matchesProfileFilters(profile, vendorFilter, statusFilter));
  }, [profiles, vendorFilter, statusFilter]);

  const hasCustomProfiles = filteredProfiles.length > 0;

  // Official presets are expanded by model in the source catalog. Group them
  // back into one family row for the management view so the table stays
  // readable while the full model list remains visible in that row.
  const presetGroups = useMemo(() => buildPresetDisplayGroups(presets), [presets]);
  const filteredPresetGroups = useMemo(() => {
    const term = searchInput.trim().toLowerCase();
    return presetGroups.filter(group => (
      (!vendorFilter || group.primary.vendor.toLowerCase() === vendorFilter.toLowerCase()) &&
      group.items.some(item => presetMatchesSearch(item, term))
    ));
  }, [presetGroups, vendorFilter, searchInput]);

  // Unified items total count based on activeTab
  const displayTotal = useMemo(() => {
    if (activeTab === 'presets') return filteredPresetGroups.length;
    if (activeTab === 'custom') return filteredProfiles.length;
    return filteredProfiles.length + filteredPresetGroups.length;
  }, [activeTab, filteredProfiles.length, filteredPresetGroups.length]);

  const handleTabChange = (nextTab: ProfileTabType) => {
    setActiveTab(nextTab);
    onPageChange(1);
  };

  const applyOfficialPreset = async (preset: ModelPresetItem, fallbackDevice?: CandidateDevice) => {
    if (!onApplyOfficialPreset || applyingPresetKey) return;
    const key = `${preset.vendor}:${preset.model}`;
    setApplyingPresetKey(key);
    try {
      await onApplyOfficialPreset(preset, fallbackDevice);
    } finally {
      setApplyingPresetKey(null);
    }
  };

  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-xl border border-black/6 dark:border-white/8">
      {/* Top Filter and Actions Bar */}
      <div className="flex flex-wrap items-center justify-between gap-2.5 border-b border-black/6 p-3 dark:border-white/8">
        <div className="flex flex-1 flex-wrap items-center gap-2">
          {/* Tabs: All / Custom / Presets */}
          <div className="flex items-center rounded-lg border border-black/8 bg-black/[.03] p-0.5 dark:border-white/10 dark:bg-white/[.04]">
            <button
              type="button"
              onClick={() => handleTabChange('all')}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                activeTab === 'all'
                  ? 'bg-white text-black shadow-sm dark:bg-white/15 dark:text-white'
                  : 'text-black/55 hover:text-black/80 dark:text-white/55 dark:hover:text-white/80'
              }`}
            >
              {zh ? '全部模板' : 'All'}
              <span className="ml-1 text-[10px] opacity-60">
                ({filteredProfiles.length + filteredPresetGroups.length})
              </span>
            </button>
            {hasCustomProfiles && (
              <button
                type="button"
                onClick={() => handleTabChange('custom')}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                  activeTab === 'custom'
                    ? 'bg-white text-black shadow-sm dark:bg-white/15 dark:text-white'
                    : 'text-black/55 hover:text-black/80 dark:text-white/55 dark:hover:text-white/80'
                }`}
              >
                {zh ? '已绑定型号' : 'Bound Models'}
                <span className="ml-1 text-[10px] opacity-60">({filteredProfiles.length})</span>
              </button>
            )}
            <button
              type="button"
              onClick={() => handleTabChange('presets')}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                activeTab === 'presets'
                  ? 'bg-[#00a9ce] text-white shadow-sm'
                  : 'text-[#008aad] hover:text-[#007391] dark:text-[#00bceb] dark:hover:text-white'
              }`}
            >
              <Sparkles size={11} className="mr-1 inline text-current" />
              {zh ? '官方预置库' : 'Official Presets'}
              <span className="ml-1 text-[10px] opacity-80">({filteredPresetGroups.length})</span>
            </button>
          </div>

          {/* Search Input with Debounce */}
          <div className="relative min-w-[180px] flex-1 sm:max-w-xs">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-black/30 dark:text-white/25" />
            <input
              value={searchInput}
              onChange={e => setSearchInput(e.target.value)}
              placeholder={zh ? '搜索厂商 / 型号 / 描述...' : 'Search vendor / model...'}
              className="w-full rounded-lg border border-black/8 bg-transparent py-1.5 pl-8 pr-7 text-xs outline-none focus:border-[#00bceb]/50 dark:border-white/10"
            />
            {searchInput && (
              <button
                type="button"
                onClick={() => setSearchInput('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-black/35 hover:text-black/70 dark:text-white/35 dark:hover:text-white/70"
              >
                <X size={12} />
              </button>
            )}
          </div>

          {/* Vendor Selector */}
          <div className="flex items-center gap-1">
            <select
              value={vendorFilter}
              onChange={e => setVendorFilter(e.target.value)}
              className="h-8 rounded-lg border border-black/8 bg-transparent px-2 text-xs outline-none focus:border-[#00bceb]/50 dark:border-white/10"
            >
              <option value="">{zh ? '全部厂商' : 'All Vendors'}</option>
              {vendorOptions.map(v => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </div>

          {/* Status Filter (applicable to custom models) */}
          {activeTab !== 'presets' && hasCustomProfiles && (
            <div className="flex items-center gap-1">
              <select
                value={statusFilter}
                onChange={e => setStatusFilter(e.target.value as StatusFilterType)}
                className="h-8 rounded-lg border border-black/8 bg-transparent px-2 text-xs outline-none focus:border-[#00bceb]/50 dark:border-white/10"
              >
                <option value="all">{zh ? '全部状态' : 'All Status'}</option>
                <option value="configured">{zh ? '已自定义配置' : 'Configured'}</option>
                <option value="verified">{zh ? '已验证通过' : 'Verified'}</option>
                <option value="unverified">{zh ? '待在线验证' : 'Unverified'}</option>
                <option value="failed">{zh ? '验证失败' : 'Failed'}</option>
                <option value="default">{zh ? '使用内置默认' : 'Default'}</option>
              </select>
            </div>
          )}

          {/* Refresh button */}
          <button
            type="button"
            onClick={onRefresh}
            disabled={loading}
            className="rounded-lg border border-black/8 p-2 text-black/45 hover:bg-black/5 disabled:opacity-40 dark:border-white/10 dark:text-white/45 dark:hover:bg-white/8"
            title={zh ? '刷新列表' : 'Refresh'}
          >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>

        {/* Action Buttons */}
      <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => onOpenPresets()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[#00bceb]/25 bg-[#00bceb]/10 px-3 py-1.5 text-xs font-semibold text-[#008aad] shadow-sm hover:bg-[#00bceb]/20 dark:text-[#00bceb]"
          >
            <Sparkles size={13} />
            {zh ? '官方模板' : 'Official Templates'}
          </button>
          <button
            type="button"
            onClick={onOpenMibs}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[#00bceb]/25 bg-[#00bceb]/10 px-3 py-1.5 text-xs font-semibold text-[#008aad] shadow-sm hover:bg-[#00bceb]/20 dark:text-[#00bceb]"
          >
            <Database size={13} />
            {zh ? 'MIB 知识库' : 'MIBs'}
          </button>
          <button
            type="button"
            onClick={onOpenCreate}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[#00a9ce] px-3.5 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-[#008fb1]"
          >
            <Plus size={14} />
            {zh ? '新建自定义模板' : 'New Profile'}
          </button>
        </div>
      </div>

      <div className="flex items-center gap-1.5 border-b border-black/5 bg-[#00bceb]/[0.035] px-3 py-2 text-[10px] text-black/55 dark:border-white/6 dark:text-white/55">
        <Check size={12} className="shrink-0 text-emerald-600 dark:text-emerald-400" />
        {zh
          ? '流程：①匹配官方型号；②选择设备测试并确认绑定；③已绑定型号可管理/解绑；④无匹配或不适配时再新建自定义模板。'
          : 'Flow: match an official model; choose a device, test, and confirm binding; manage or unbind from Bound Models; create a custom template only when there is no match or the official template does not fit.'}
      </div>

      {/* Table Content */}
      <div className="min-h-0 flex-1 overflow-auto">
        {loading ? (
          <div className="p-12 text-center text-xs text-black/40 dark:text-white/40">
            <RefreshCw size={18} className="mx-auto mb-2 animate-spin text-[#009ec4]" />
            {zh ? '加载型号指标模板中…' : 'Loading profiles…'}
          </div>
        ) : filteredProfiles.length === 0 && (activeTab === 'custom' || filteredPresetGroups.length === 0) ? (
          <div className="p-12 text-center text-xs text-black/40 dark:text-white/40">
            {zh ? '未找到符合条件的型号指标模板。' : 'No matching profiles found.'}
          </div>
        ) : (
          <DataTable
            unstyled
            exportConfig={{
              filename: 'snmp-metric-profiles',
              language: zh ? 'zh' : 'en',
              disabled: loading,
              exportData: async () => buildMetricProfileExportData(
                await loadAllProfilesForExport(searchInput.trim()),
                presets,
                { vendorFilter, statusFilter, activeTab, search: searchInput, zh },
              ),
            }}
            className="nx-data-table nx-data-table--compact"
          >
            <thead className="sticky top-0 z-10 bg-[var(--card-bg)] shadow-sm text-black/40 dark:text-white/40">
              <tr>
                <th className="px-3.5 py-2.5 font-medium">{zh ? '厂商' : 'Vendor'}</th>
                <th className="px-3.5 py-2.5 font-medium">{zh ? '模板来源' : 'Template source'}</th>
                <th className="px-3.5 py-2.5 font-medium">{zh ? '分类' : 'Category'}</th>
                <th className="px-3.5 py-2.5 font-medium">{zh ? '型号' : 'Model'}</th>
                <th className="px-3.5 py-2.5 font-medium">{zh ? '型号匹配模式' : 'Model pattern'}</th>
                <th className="px-3.5 py-2.5 font-medium">{zh ? '平台' : 'Platforms'}</th>
                <th className="px-3.5 py-2.5 font-medium">{zh ? '软件版本范围' : 'Software version scope'}</th>
                <th className="px-3 py-2.5 font-medium">{zh ? '采集指标' : 'Collected metrics'}</th>
                <TableActionHeader className="px-3 py-2.5 font-medium">{zh ? '绑定与管理' : 'Binding & Management'}</TableActionHeader>
              </tr>
            </thead>
            <tbody>
              {/* 1. Official Presets Rows (rendered if activeTab is 'all' or 'presets') */}
              {(activeTab === 'all' || activeTab === 'presets') &&
                filteredPresetGroups.map(group => {
                  const preset = group.primary;
                  const linkedProfiles = profilesForPresetGroup(group, profiles);
                  const officialProfiles = linkedProfiles.filter(profile => Boolean(
                    profile.source === 'official' ||
                    profile.source === 'official_preset' ||
                    profile.official_preset_id ||
                    profile.applied_preset_id,
                  ));
                  const inventoryDeviceCount = group.models.reduce((count, model) => {
                    const modelCount = linkedProfiles
                      .filter(profile => modelDisplayKey(profile.model) === modelDisplayKey(model))
                      .reduce(
                        (max, profile) => Math.max(
                          max,
                          Number(profile.inventory_device_count ?? profile.device_count ?? 0),
                        ),
                        0,
                      );
                    return count + modelCount;
                  }, 0);
                  const appliedProfile = officialProfiles.find(profile => Boolean(profile.profile_id));
                  const sampleProfile = officialProfiles.find(profile => profile.sample_device_id)
                    || linkedProfiles.find(profile => profile.sample_device_id)
                    || appliedProfile;
                  const exactTargetPreset = sampleProfile
                    ? group.items.find(item => modelDisplayKey(item.model) === modelDisplayKey(sampleProfile.model))
                    : undefined;
                  const targetPreset = exactTargetPreset || group.primary;
                  const hasAppliedProfile = Boolean(
                    appliedProfile?.profile_id && Number(
                      appliedProfile.bound_device_count ?? appliedProfile.device_count ?? 0,
                    ) > 0,
                  );
                  const canDirectApply = Boolean(exactTargetPreset && onApplyOfficialPreset && !hasAppliedProfile);
                  const isApplying = applyingPresetKey === `${targetPreset.vendor}:${targetPreset.model}`;
                  const sampleDevice = sampleProfile?.sample_device_id
                    ? {
                        device_id: sampleProfile.sample_device_id,
                        hostname: `${sampleProfile.vendor} ${sampleProfile.model}`,
                        ip_address: sampleProfile.sample_device_ip || undefined,
                        status: sampleProfile.sample_device_status || undefined,
                      }
                    : undefined;
                  const sampleStatus = String(sampleDevice?.status || '').trim().toLowerCase();
                  return (
                    <tr
                      key={`preset-group:${group.key}`}
                      className="border-t border-black/5 bg-[#00bceb]/[0.02] transition-colors hover:bg-[#00bceb]/[0.05] dark:border-white/6 dark:bg-[#00bceb]/[0.03] dark:hover:bg-[#00bceb]/[0.06]"
                    >
                      <td className="px-3.5 py-3 align-top font-semibold text-black/80 dark:text-white/85">{vendorDisplayLabel(preset.vendor, zh)}</td>
                      <td className="px-3.5 py-3 align-top"><span className="rounded-full bg-[#00bceb]/15 px-1.5 py-0.5 text-[9px] font-semibold text-[#008aad] dark:bg-[#00bceb]/25 dark:text-[#00bceb]">{zh ? '官方预置' : 'Official preset'}</span></td>
                      <td className="px-3.5 py-3 align-top text-black/60 dark:text-white/60">{presetCategoryLabel(preset.category || 'Network Device', zh)}</td>
                      <td className="px-3.5 py-3 align-top">
                        <div className="flex flex-wrap gap-1">
                          {group.models.map(model => <span key={model} className="rounded bg-[#00bceb]/10 px-1.5 py-0.5 font-mono text-[9px] text-[#007391] dark:text-[#00bceb]">{model}</span>)}
                        </div>
                      </td>
                      <td className="px-3.5 py-3 align-top font-mono text-[10px] text-black/55 dark:text-white/55">
                        {Array.from(new Set(group.items.filter(item => item.model_pattern && item.model_pattern !== item.model).map(item => item.model_pattern))).join(', ') || '-'}
                      </td>
                      <td className="px-3.5 py-3 align-top font-mono text-[10px] text-black/55 dark:text-white/55">
                        {Array.from(new Set(group.items.flatMap(item => item.platforms || []))).join(', ') || '-'}
                      </td>
                      <td className="px-3.5 py-3 align-top font-mono text-[10px] text-black/55 dark:text-white/55">
                        {Array.from(new Set(group.items.flatMap(item => item.software_version_scope || []))).join(', ') || '-'}
                      </td>

                      {/* Collected metrics remain one field: a set of metrics attached to this preset family. */}
                      <td className="px-3 py-3 align-top">
                        <div className="flex flex-wrap gap-1">
                          {group.metricKeys.map(key => (
                            <span
                              key={key}
                              className="rounded bg-[#00bceb]/10 px-1.5 py-0.5 text-[9px] font-medium text-[#007391] dark:text-[#00bceb]"
                            >
                              {metricLabel(key, zh)}
                            </span>
                          ))}
                          {group.interfaceEnabled && (
                            <span className="rounded bg-[#00bceb]/15 px-1.5 py-0.5 text-[9px] font-medium text-[#008aad] dark:text-[#00bceb]">
                              {zh ? '接口 IF-MIB' : 'IF-MIB'}
                            </span>
                          )}
                        </div>
                      </td>

                      {/* SNMP Walk and linked devices */}
                      <TableActionCell className="px-3 py-3 align-top">
                        <div className="flex flex-wrap items-center justify-end gap-1.5">
                          <ActionIconButton
                            type="button"
                            icon={isApplying ? Loader2 : hasAppliedProfile ? CheckCircle2 : canDirectApply ? Link2 : Settings2}
                            label={isApplying
                              ? (zh ? '应用中' : 'Applying')
                              : canDirectApply
                                ? (zh ? '测试并绑定' : 'Test and bind')
                                : hasAppliedProfile
                                  ? (zh ? '官方模板已应用' : 'Official template applied')
                                  : (zh ? '选择型号并绑定' : 'Select model and bind')}
                            iconClassName={isApplying ? 'animate-spin' : undefined}
                            variant={hasAppliedProfile ? 'success' : 'accent'}
                            onClick={() => {
                              if (canDirectApply) {
                                void applyOfficialPreset(targetPreset, sampleDevice);
                              } else {
                                onOpenPresets(targetPreset);
                              }
                            }}
                            disabled={Boolean(applyingPresetKey) || hasAppliedProfile}
                            tooltip={canDirectApply
                              ? (zh ? `测试并绑定官方模板：${targetPreset.vendor} ${targetPreset.model}` : `Test and bind the official template: ${targetPreset.vendor} ${targetPreset.model}`)
                              : hasAppliedProfile
                                ? (zh ? '官方模板已应用；实际设备绑定请在“已绑定型号”中管理或解绑' : 'The official template is applied; manage or unbind actual device bindings from Bound Models')
                                 : (zh ? '选择具体型号后进入官方模板绑定流程' : 'Choose an exact model to start the official template binding flow')}
                          />
                          <span className="inline-flex items-center gap-1 rounded-md bg-black/[.04] px-2 py-1 text-[10px] text-black/55 dark:bg-white/[.06] dark:text-white/60" title={zh ? '按官方模板厂商和型号匹配到的设备候选数，不代表这些设备已经绑定模板' : 'Candidate devices matching the official vendor and model; this is not the number of devices bound to the template'}>
                            <Server size={11} />
                            {zh ? `候选设备 ${inventoryDeviceCount} 台` : `${inventoryDeviceCount} candidate devices`}
                          </span>
                        </div>
                        <div className="mt-1.5 text-[9px] text-black/40 dark:text-white/40">
                          {hasAppliedProfile
                            ? (zh ? '官方模板已应用；实际绑定数量请查看“已绑定型号”中的模板记录' : 'Official template is applied; see the Bound Models template row for the actual binding count')
                            : inventoryDeviceCount > 0
                              ? canDirectApply
                                ? (zh ? `已发现 ${inventoryDeviceCount} 台候选设备；测试只需选择其中一台` : `${inventoryDeviceCount} candidate device(s) found; test only one of them`)
                                : (zh ? '按厂商+型号找到候选设备；选择具体型号后进入测试与绑定流程' : 'Candidate devices found by vendor + model; choose an exact model to start the test-and-bind flow')
                              : (zh ? '暂未发现匹配的受管设备' : 'No matching managed device found')}
                        </div>
                        {sampleDevice && (
                          <div className={`mt-1 text-[9px] ${sampleStatus === 'online' ? 'text-emerald-700 dark:text-emerald-300' : 'text-amber-700 dark:text-amber-300'}`}>
                            {sampleStatus === 'online'
                              ? (zh ? `快速读取样例：在线设备 ${sampleDevice.ip_address || sampleDevice.hostname}` : `Quick-read sample: online device ${sampleDevice.ip_address || sampleDevice.hostname}`)
                              : sampleStatus
                                ? (zh ? `快速读取样例：当前无在线设备，已回退 ${sampleDevice.ip_address || sampleDevice.hostname}` : `Quick-read sample: no online device; fell back to ${sampleDevice.ip_address || sampleDevice.hostname}`)
                                : (zh ? `快速读取样例：设备状态待确认 ${sampleDevice.ip_address || sampleDevice.hostname}` : `Quick-read sample: device status pending ${sampleDevice.ip_address || sampleDevice.hostname}`)}
                          </div>
                        )}
                      </TableActionCell>
                    </tr>
                  );
                })}

              {/* 2. Custom Model Profiles Rows (rendered if activeTab is 'all' or 'custom') */}
              {(activeTab === 'all' || activeTab === 'custom') &&
                filteredProfiles.map(profile => {
                  const isOfficialApplied = Boolean(
                    profile.source === 'official' ||
                    profile.source === 'official_preset' ||
                    profile.official_preset_id ||
                    profile.applied_preset_id,
                  );

                  return (
                    <tr
                      key={profile.profile_id || `${profile.vendor}:${profile.model}:${profile.template_name || 'template'}`}
                      className="border-t border-black/5 transition-colors hover:bg-black/[.015] dark:border-white/6 dark:hover:bg-white/[.015]"
                    >
                      <td className="px-3.5 py-2.5 font-semibold text-black/80 dark:text-white/85">{profile.vendor}</td>
                      <td className="px-3.5 py-2.5">
                        <span className={`rounded-full px-1.5 py-0.5 text-[8px] font-semibold ${isOfficialApplied ? 'bg-emerald-500/12 text-emerald-700 dark:bg-emerald-400/15 dark:text-emerald-300' : 'bg-black/[.05] text-black/45 dark:bg-white/[.08] dark:text-white/50'}`}>
                          {isOfficialApplied ? (zh ? '官方已绑定' : 'Official bound') : (zh ? '自定义模板' : 'Custom')}
                        </span>
                      </td>
                      <td className="px-3.5 py-2.5 text-black/40 dark:text-white/40">-</td>
                      <td className="px-3.5 py-2.5 font-mono text-[10px] text-black/75 dark:text-white/75">{profile.model}</td>
                      <td className="px-3.5 py-2.5 font-mono text-[10px] text-black/55 dark:text-white/55">{profile.model_pattern && profile.model_pattern !== profile.model ? profile.model_pattern : '-'}</td>
                      <td className="px-3.5 py-2.5 font-mono text-[10px] text-black/55 dark:text-white/55">{profile.platforms?.length ? profile.platforms.join(', ') : '-'}</td>
                      <td className="px-3.5 py-2.5 font-mono text-[10px] text-black/55 dark:text-white/55">{profile.software_version_scope?.length ? profile.software_version_scope.join(', ') : '-'}</td>

                      {/* Metrics Badges */}
                      <td className="max-w-[280px] px-3 py-2.5">
                        <div className="flex flex-wrap gap-1">
                          {(profile.metric_keys || Object.keys(profile.metric_definitions || {})).map(key => (
                            <span
                              key={key}
                              className="rounded bg-black/[.04] px-1.5 py-0.5 text-[9px] font-medium dark:bg-white/[.06]"
                            >
                              {metricLabel(key, zh)}
                            </span>
                          ))}
                          {profile.interface_configured && (
                            <span className="rounded bg-[#00bceb]/10 px-1.5 py-0.5 text-[9px] font-medium text-[#008aad] dark:text-[#00bceb]">
                              {zh ? '接口 IF-MIB' : 'IF-MIB'}
                            </span>
                          )}
                          {!profile.configured && !profile.interface_configured && (
                            <span className="text-[10px] text-black/35 dark:text-white/35">
                              {zh ? '默认 CPU / 内存' : 'Default CPU/Mem'}
                            </span>
                          )}
                        </div>
                      </td>

                      {/* SNMP Walk and linked devices */}
                      <TableActionCell className="px-3 py-3 align-top" label={zh ? '模板操作' : 'Profile actions'}>
                          <ActionIconButton
                            type="button"
                            icon={Eye}
                            label={zh ? '查看模板采集结果' : 'View template collection results'}
                            tooltip={zh ? '直接查看模板采集结果' : 'View collected metric results'}
                            variant="accent"
                            onClick={() => onOpenCollectionResult?.(profile)}
                          />
                          <ActionIconButton
                            type="button"
                            icon={Terminal}
                            label="SNMP Walk"
                            tooltip={zh ? '打开此型号的 SNMP Walk 调试工具' : 'Open SNMP Walk for this model'}
                            variant="accent"
                            onClick={() => onOpenSnmpWalk?.(profile)}
                          />
                          <ActionIconButton
                            type="button"
                            icon={Eye}
                            label={zh ? '查看关联设备清单' : 'View linked devices'}
                            onClick={() => onValidateMapping(profile)}
                            disabled={!profile.profile_id}
                          />
                          {profile.profile_id && onOpenBinding && (
                            <ActionIconButton
                              type="button"
                              icon={Link2}
                              label={zh ? '绑定或解绑设备' : 'Bind or unbind devices'}
                              tooltip={zh ? '选择设备并绑定或解绑模板' : 'Select devices to bind or unbind this template'}
                              variant="accent"
                              onClick={() => onOpenBinding(profile)}
                            />
                          )}
                          <ActionIconButton
                            type="button"
                            icon={Pencil}
                            label={zh ? '管理模板' : 'Manage profile'}
                            variant="accent"
                            onClick={() => onEdit(profile)}
                          />
                          {profile.profile_id && (
                            <ActionIconButton
                              type="button"
                              icon={Trash2}
                              label={zh ? '删除已保存模板' : 'Delete saved template'}
                              tooltip={zh ? '删除已保存模板记录（需先解绑设备）' : 'Delete saved template record (unbind devices first)'}
                              variant="danger"
                              onClick={() => onDeleteProfile?.(profile)}
                            />
                          )}
                      </TableActionCell>
                    </tr>
                  );
                })}
            </tbody>
          </DataTable>
        )}
      </div>

      {/* Pagination */}
      <Pagination
        currentPage={page}
        totalItems={displayTotal}
        itemsPerPage={pageSize}
        onPageChange={onPageChange}
        onItemsPerPageChange={onPageSizeChange}
        language={language}
        alwaysVisible
      />
    </section>
  );
};
