import React, { useState, useEffect, useMemo } from 'react';
import {
  Activity,
  CheckCircle2,
  Copy,
  Cpu,
  Database,
  GitBranch,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  X,
  Filter,
  Layers,
} from 'lucide-react';
import Pagination from '../../Pagination';
import { metricLabel } from './MetricRowItem';
import { ModelPresetItem } from '../PresetProfilesModal';

export interface MetricOidProfile {
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
  collector_status?:
    | 'active'
    | 'blocked_unverified'
    | 'blocked_failed'
    | 'no_matching_device'
    | 'builtin_only'
    | string;
  interface_config?: Record<string, unknown>;
  interface_configured?: boolean;
  interface_verification_status?: 'verified' | 'failed' | 'unverified' | string;
  interface_collector_status?: string;
  sample_device_id?: string | null;
  platforms: string[];
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
  testingId: string | null;
  language: string;
  onSearchChange: (search: string) => void;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
  onRefresh: () => void;
  onOpenCreate: () => void;
  onOpenPresets: () => void;
  onOpenMibs: () => void;
  onEdit: (profile: MetricOidProfile) => void;
  onDeleteProfile?: (profile: MetricOidProfile) => void;
  onCloneProfile?: (profile: MetricOidProfile) => void;
  onClonePreset?: (preset: ModelPresetItem) => void;
  onAutoMatch: (profile: MetricOidProfile) => void;
  onValidateMapping: (profile: MetricOidProfile) => void;
  onTestProfile: (profile: Pick<MetricOidProfile, 'profile_id' | 'sample_device_id'>) => void;
}

const collectorStatusLabel = (status: string | undefined, zh: boolean) => {
  if (status === 'active') return zh ? '已生效应用' : 'Active';
  if (status === 'blocked_failed') return zh ? '校验未过，已阻断' : 'Blocked (Failed)';
  if (status === 'no_matching_device') return zh ? '无匹配设备' : 'No matching device';
  if (status === 'blocked_unverified') return zh ? '待验证，暂未应用' : 'Unverified (Blocked)';
  return zh ? '使用内置默认' : 'Built-in fallback';
};

const collectorStatusClass = (status: string | undefined) => {
  if (status === 'active') return 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400';
  if (status === 'blocked_failed') return 'bg-red-500/10 text-red-600 dark:text-red-400';
  if (status === 'no_matching_device') return 'bg-slate-500/10 text-slate-600 dark:text-slate-300';
  if (status === 'blocked_unverified') return 'bg-amber-500/10 text-amber-600 dark:text-amber-400';
  return 'bg-slate-500/10 text-slate-600 dark:text-slate-300';
};

export const MetricProfileList: React.FC<MetricProfileListProps> = ({
  profiles,
  presets = [],
  loading,
  total,
  page,
  pageSize,
  search,
  testingId,
  language,
  onSearchChange,
  onPageChange,
  onPageSizeChange,
  onRefresh,
  onOpenCreate,
  onOpenPresets,
  onOpenMibs,
  onEdit,
  onDeleteProfile,
  onCloneProfile,
  onClonePreset,
  onAutoMatch,
  onValidateMapping,
  onTestProfile,
}) => {
  const zh = language === 'zh';
  const [searchInput, setSearchInput] = useState(search);
  const [vendorFilter, setVendorFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilterType>('all');
  const [activeTab, setActiveTab] = useState<ProfileTabType>('all');

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

  // Client-side quick filter on custom profiles
  const filteredProfiles = useMemo(() => {
    return profiles.filter(profile => {
      // Vendor filter
      if (vendorFilter && profile.vendor.toLowerCase() !== vendorFilter.toLowerCase()) {
        return false;
      }
      // Status filter
      if (statusFilter === 'verified') {
        return profile.verification_status === 'verified' || profile.interface_verification_status === 'verified';
      }
      if (statusFilter === 'unverified') {
        return (
          (profile.configured && profile.verification_status === 'unverified') ||
          (profile.interface_configured && profile.interface_verification_status === 'unverified')
        );
      }
      if (statusFilter === 'failed') {
        return profile.verification_status === 'failed' || profile.interface_verification_status === 'failed';
      }
      if (statusFilter === 'configured') {
        return profile.configured || profile.interface_configured;
      }
      if (statusFilter === 'default') {
        return !profile.configured && !profile.interface_configured;
      }
      return true;
    });
  }, [profiles, vendorFilter, statusFilter]);

  // Client-side quick filter on presets
  const filteredPresets = useMemo(() => {
    const term = searchInput.trim().toLowerCase();
    return presets.filter(preset => {
      if (vendorFilter && preset.vendor.toLowerCase() !== vendorFilter.toLowerCase()) {
        return false;
      }
      if (!term) return true;
      return (
        preset.vendor.toLowerCase().includes(term) ||
        preset.model.toLowerCase().includes(term) ||
        (preset.category && preset.category.toLowerCase().includes(term)) ||
        (preset.description && preset.description.toLowerCase().includes(term))
      );
    });
  }, [presets, vendorFilter, searchInput]);

  // Unified items total count based on activeTab
  const displayTotal = useMemo(() => {
    if (activeTab === 'presets') return filteredPresets.length;
    if (activeTab === 'custom') return total;
    return total + filteredPresets.length;
  }, [activeTab, total, filteredPresets.length]);

  const handleTabChange = (nextTab: ProfileTabType) => {
    setActiveTab(nextTab);
    onPageChange(1);
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
                ({filteredProfiles.length + filteredPresets.length})
              </span>
            </button>
            <button
              type="button"
              onClick={() => handleTabChange('custom')}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                activeTab === 'custom'
                  ? 'bg-white text-black shadow-sm dark:bg-white/15 dark:text-white'
                  : 'text-black/55 hover:text-black/80 dark:text-white/55 dark:hover:text-white/80'
              }`}
            >
              {zh ? '已配置型号' : 'Custom Models'}
              <span className="ml-1 text-[10px] opacity-60">({filteredProfiles.length})</span>
            </button>
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
              <span className="ml-1 text-[10px] opacity-80">({filteredPresets.length})</span>
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
          {activeTab !== 'presets' && (
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
            {zh ? '新建模板' : 'New Profile'}
          </button>
        </div>
      </div>

      {/* Table Content */}
      <div className="min-h-0 flex-1 overflow-auto">
        {loading ? (
          <div className="p-12 text-center text-xs text-black/40 dark:text-white/40">
            <RefreshCw size={18} className="mx-auto mb-2 animate-spin text-[#009ec4]" />
            {zh ? '加载型号指标模板中…' : 'Loading profiles…'}
          </div>
        ) : filteredProfiles.length === 0 && (activeTab === 'custom' || filteredPresets.length === 0) ? (
          <div className="p-12 text-center text-xs text-black/40 dark:text-white/40">
            {zh ? '未找到符合条件的型号指标模板。' : 'No matching profiles found.'}
          </div>
        ) : (
          <table className="w-full text-left text-[11px]">
            <thead className="sticky top-0 z-10 bg-[var(--card-bg)] shadow-sm text-black/40 dark:text-white/40">
              <tr>
                <th className="px-3.5 py-2.5 font-medium">{zh ? '厂商 / 型号' : 'Vendor / Model'}</th>
                <th className="px-3 py-2.5 font-medium">{zh ? '采集指标 / 说明' : 'Metrics / Description'}</th>
                <th className="px-3 py-2.5 font-medium">{zh ? '设备范围 / 分类' : 'Devices / Scope'}</th>
                <th className="px-3 py-2.5 font-medium">{zh ? '模板属性与生效状态' : 'Status'}</th>
                <th className="px-3 py-2.5 text-right">{zh ? '操作' : 'Actions'}</th>
              </tr>
            </thead>
            <tbody>
              {/* 1. Official Presets Rows (rendered if activeTab is 'all' or 'presets') */}
              {(activeTab === 'all' || activeTab === 'presets') &&
                filteredPresets.map(preset => {
                  const metricKeys = Object.keys(preset.metric_definitions || {});
                  return (
                    <tr
                      key={`preset:${preset.vendor}:${preset.model}`}
                      className="border-t border-black/5 bg-[#00bceb]/[0.02] transition-colors hover:bg-[#00bceb]/[0.05] dark:border-white/6 dark:bg-[#00bceb]/[0.03] dark:hover:bg-[#00bceb]/[0.06]"
                    >
                      {/* Vendor and Model */}
                      <td className="max-w-[240px] px-3.5 py-2.5">
                        <div className="flex items-center gap-1.5">
                          <span className="truncate font-semibold text-black/80 dark:text-white/85">
                            {preset.vendor}
                          </span>
                          <span className="rounded-full bg-[#00bceb]/15 px-1.5 py-0.2 text-[8px] font-semibold text-[#008aad] dark:bg-[#00bceb]/25 dark:text-[#00bceb]">
                            {zh ? '官方预置' : 'Preset'}
                          </span>
                        </div>
                        <div className="truncate font-mono text-[10px] text-[#008aad] dark:text-[#00bceb]">
                          {preset.model}
                        </div>
                      </td>

                      {/* Metrics Badges & Description */}
                      <td className="max-w-[320px] px-3 py-2.5">
                        <div className="flex flex-wrap gap-1">
                          {metricKeys.map(key => (
                            <span
                              key={key}
                              className="rounded bg-[#00bceb]/10 px-1.5 py-0.5 text-[9px] font-medium text-[#007391] dark:text-[#00bceb]"
                            >
                              {metricLabel(key, zh)}
                            </span>
                          ))}
                          {preset.interface_config?.enabled && (
                            <span className="rounded bg-[#00bceb]/15 px-1.5 py-0.5 text-[9px] font-medium text-[#008aad] dark:text-[#00bceb]">
                              {zh ? '接口 IF-MIB' : 'IF-MIB'}
                            </span>
                          )}
                        </div>
                        {preset.description && (
                          <div className="mt-1 max-w-sm truncate text-[10px] text-black/45 dark:text-white/45">
                            {preset.description}
                          </div>
                        )}
                      </td>

                      {/* Scope & Category */}
                      <td className="px-3 py-2.5 text-black/60 dark:text-white/60">
                        <span className="rounded bg-black/[.04] px-1.5 py-0.5 text-[10px] font-medium dark:bg-white/[.06]">
                          {preset.category || (zh ? '网络设备' : 'Network Device')}
                        </span>
                      </td>

                      {/* Status badge */}
                      <td className="px-3 py-2.5">
                        <span className="rounded-full bg-[#00bceb]/10 px-2 py-0.5 text-[10px] font-medium text-[#008aad] dark:text-[#00bceb]">
                          {zh ? '官方已认证规则' : 'Certified Rule'}
                        </span>
                      </td>

                      {/* Actions for Presets */}
                      <td className="px-3.5 py-2.5 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            type="button"
                            onClick={() => onClonePreset?.(preset)}
                            className="inline-flex items-center gap-1 rounded-md border border-[#00bceb]/30 bg-[#00bceb]/10 px-2.5 py-1 text-[10px] font-semibold text-[#008aad] shadow-sm hover:bg-[#00bceb]/20 dark:text-[#00bceb]"
                            title={zh ? '一键复制此预置并修改为自定义模板' : 'Clone preset and customize'}
                          >
                            <Copy size={11} />
                            {zh ? '复制' : 'Clone'}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}

              {/* 2. Custom Model Profiles Rows (rendered if activeTab is 'all' or 'custom') */}
              {(activeTab === 'all' || activeTab === 'custom') &&
                filteredProfiles.map(profile => {
                  const collectorStatus =
                    profile.collector_status || (profile.configured ? 'blocked_unverified' : 'builtin_only');
                  const matchedDeviceCount = Number(profile.matched_device_count ?? profile.device_count ?? 0);
                  const appliedDeviceCount = Number(
                    profile.profile_applied_device_count ?? (collectorStatus === 'active' ? matchedDeviceCount : 0),
                  );

                  return (
                    <tr
                      key={`${profile.vendor}:${profile.model}`}
                      className="border-t border-black/5 transition-colors hover:bg-black/[.015] dark:border-white/6 dark:hover:bg-white/[.015]"
                    >
                      {/* Vendor and Model */}
                      <td className="max-w-[240px] px-3.5 py-2.5">
                        <div className="truncate font-semibold text-black/80 dark:text-white/85">{profile.vendor}</div>
                        <div className="truncate font-mono text-[10px] text-black/45 dark:text-white/45">
                          {profile.model}
                        </div>
                      </td>

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

                      {/* Device Count */}
                      <td className="px-3 py-2.5 tabular-nums text-black/60 dark:text-white/60">
                        <div className="font-semibold">{profile.device_count}</div>
                        <div className="text-[9px] text-black/40 dark:text-white/40">
                          {zh ? `匹配 ${matchedDeviceCount} 台` : `${matchedDeviceCount} matched`}
                        </div>
                      </td>

                      {/* Status Badges */}
                      <td className="px-3 py-2.5">
                        <div className="flex flex-wrap gap-1">
                          <span
                            className={
                              (profile.configured || profile.interface_configured
                                ? 'bg-slate-500/10 text-slate-700 dark:text-slate-300'
                                : 'bg-amber-500/10 text-amber-700 dark:text-amber-400') +
                              ' rounded-full px-2 py-0.5 text-[10px] font-medium'
                            }
                          >
                            {profile.configured || profile.interface_configured
                              ? zh
                                ? '已自定义'
                                : 'Configured'
                              : zh
                                ? '系统默认'
                                : 'Default'}
                          </span>
                          {profile.configured && (
                            <span
                              className={
                                (profile.verification_status === 'verified'
                                  ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400'
                                  : profile.verification_status === 'failed'
                                    ? 'bg-red-500/10 text-red-700 dark:text-red-400'
                                    : 'bg-amber-500/10 text-amber-700 dark:text-amber-400') +
                                ' inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium'
                              }
                            >
                              {profile.verification_status === 'verified' && <CheckCircle2 size={10} />}
                              {profile.verification_status === 'verified'
                                ? zh
                                  ? '硬件已验证'
                                  : 'HW Verified'
                                : profile.verification_status === 'failed'
                                  ? zh
                                    ? '硬件失败'
                                    : 'HW Failed'
                                  : zh
                                    ? '硬件待验证'
                                    : 'HW Unverified'}
                            </span>
                          )}
                          {profile.interface_configured && (
                            <span
                              className={
                                (profile.interface_verification_status === 'verified'
                                  ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400'
                                  : profile.interface_verification_status === 'failed'
                                    ? 'bg-red-500/10 text-red-700 dark:text-red-400'
                                    : 'bg-amber-500/10 text-amber-700 dark:text-amber-400') +
                                ' rounded-full px-2 py-0.5 text-[10px] font-medium'
                              }
                            >
                              {profile.interface_verification_status === 'verified'
                                ? zh
                                  ? '接口已验证'
                                  : 'IF Verified'
                                : profile.interface_verification_status === 'failed'
                                  ? zh
                                    ? '接口失败'
                                    : 'IF Failed'
                                  : zh
                                    ? '接口待验证'
                                    : 'IF Unverified'}
                            </span>
                          )}
                          <span
                            className={
                              collectorStatusClass(collectorStatus) +
                              ' rounded-full px-2 py-0.5 text-[10px] font-medium'
                            }
                          >
                            {collectorStatusLabel(collectorStatus, zh)}
                          </span>
                        </div>
                        <div className="mt-1 text-[9px] text-black/40 dark:text-white/40">
                          {zh
                            ? `应用范围：${appliedDeviceCount} / ${matchedDeviceCount} 台`
                            : `Applied: ${appliedDeviceCount} / ${matchedDeviceCount}`}
                        </div>
                      </td>

                      {/* Actions */}
                      <td className="px-3.5 py-2.5 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          {!profile.configured && (
                            <button
                              type="button"
                              onClick={() => onAutoMatch(profile)}
                              className="inline-flex items-center gap-1 rounded-md border border-emerald-500/25 bg-emerald-500/10 px-2 py-1 text-[10px] font-semibold text-emerald-700 hover:bg-emerald-500/20 dark:text-emerald-400"
                              title={zh ? '根据型号智能匹配 MIB 并填入推荐 OID' : 'Auto match MIB profile'}
                            >
                              <Sparkles size={11} />
                              {zh ? '智能匹配' : 'Auto Match'}
                            </button>
                          )}
                          {profile.profile_id && (
                            <button
                              type="button"
                              onClick={() => onValidateMapping(profile)}
                              className="inline-flex items-center gap-1 rounded-md border border-black/8 px-2 py-1 text-[10px] font-medium text-black/65 hover:bg-black/5 dark:border-white/10 dark:text-white/70 dark:hover:bg-white/8"
                              title={zh ? '查看匹配与生效的设备清单' : 'View mapped devices'}
                            >
                              <GitBranch size={11} />
                              {zh ? '映射范围' : 'Mapping'}
                            </button>
                          )}
                          {profile.profile_id && profile.sample_device_id && (
                            <button
                              type="button"
                              onClick={() => onTestProfile(profile)}
                              disabled={testingId === profile.profile_id}
                              className="inline-flex items-center gap-1 rounded-md border border-emerald-500/20 bg-emerald-500/10 px-2 py-1 text-[10px] font-medium text-emerald-700 hover:bg-emerald-500/20 disabled:opacity-40 dark:text-emerald-400"
                            >
                              <Activity
                                size={11}
                                className={testingId === profile.profile_id ? 'animate-pulse' : ''}
                              />
                              {testingId === profile.profile_id
                                ? zh
                                  ? '测试中'
                                  : 'Testing'
                                : zh
                                  ? '在线验证'
                                  : 'Test'}
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => onCloneProfile?.(profile)}
                            className="inline-flex items-center gap-1 rounded-md border border-black/8 px-2 py-1 text-[10px] font-medium text-black/65 hover:bg-black/5 dark:border-white/10 dark:text-white/70 dark:hover:bg-white/8"
                            title={zh ? '一键复制此模板配置并创建新型号模板' : 'Clone this profile for new model'}
                          >
                            <Copy size={11} />
                            {zh ? '复制' : 'Clone'}
                          </button>
                          <button
                            type="button"
                            onClick={() => onEdit(profile)}
                            className="inline-flex items-center gap-1 rounded-md bg-[#00a9ce] px-2.5 py-1 text-[10px] font-semibold text-white shadow-sm hover:bg-[#008fb1]"
                          >
                            {zh ? '修改' : 'Edit'}
                          </button>
                          {profile.profile_id && (
                            <button
                              type="button"
                              onClick={() => onDeleteProfile?.(profile)}
                              className="inline-flex items-center gap-1 rounded-md border border-red-500/20 px-2 py-1 text-[10px] font-medium text-red-600 hover:bg-red-500/10 dark:text-red-400 dark:hover:bg-red-500/20"
                              title={zh ? '删除此模板并回退系统默认' : 'Delete profile and use default'}
                            >
                              <Trash2 size={11} />
                              {zh ? '删除' : 'Delete'}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
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
