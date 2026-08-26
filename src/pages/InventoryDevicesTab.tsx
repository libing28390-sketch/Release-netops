import React, { useState, useRef, useEffect, useMemo } from 'react';
import { useInventoryStore } from '../store/inventoryStore';
import { useInventoryTableActions } from '../hooks/useInventoryTableActions';
import {
  Upload, Download, Plus, Search, Activity,
  AlertTriangle, CheckCircle2, XCircle, Server, Router,
  Shield, Trash2, SlidersHorizontal, Tag, RefreshCw, X, WifiOff, Settings2,
} from 'lucide-react';
import type { Device, DeviceConnectionCheckSummary, TagDefinition } from '../types';
import Pagination from '../components/Pagination';
import { ActionButton } from '../components/ui/ActionIconButton';
import DeviceTable, { DEFAULT_COLUMNS, type ColumnVisibility, type ColumnKey } from '../components/DeviceList/DeviceTable';
import TagFilterDropdown from '../components/TagFilterDropdown';
import PageHero from '../components/PageHero';
import BatchPlatformBindingModal from '../components/BatchPlatformBindingModal';

/* ─── Column Visibility Toggle ─── */
const COLUMN_LABELS: Record<ColumnKey, { zh: string; en: string }> = {
  device:   { zh: '设备',   en: 'Device' },
  platform: { zh: '系统',   en: 'System' },
  site:     { zh: '位置',   en: 'Location' },
  tags:     { zh: '标签',   en: 'Tags' },
  status:   { zh: '状态',   en: 'Status' },
  cpuMem:   { zh: 'CPU/MEM', en: 'CPU/MEM' },
  actions:  { zh: '操作',   en: 'Actions' },
};

const ColumnToggle: React.FC<{
  columns: ColumnVisibility;
  onChange: (key: ColumnKey, val: boolean) => void;
  language: string;
}> = ({ columns, onChange, language }) => {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const zh = language === 'zh';

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        title={zh ? '列显示设置' : 'Column visibility'}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-gray-200/80 dark:border-zinc-700/80
          bg-white dark:bg-zinc-800 text-xs font-semibold text-gray-700 dark:text-zinc-300
          hover:bg-gray-50 dark:hover:bg-zinc-700/60 transition-all cursor-pointer shadow-2xs"
      >
        <SlidersHorizontal size={13} className="text-gray-500" />
        <span>{zh ? '列设置' : 'Columns'}</span>
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1.5 z-50 w-44 rounded-2xl border border-gray-100 dark:border-zinc-800
          bg-white dark:bg-zinc-900 shadow-xl shadow-black/10 dark:shadow-black/40 py-2">
          <div className="px-3 pb-1.5 mb-1 border-b border-gray-100 dark:border-zinc-800 text-[10px] font-bold uppercase tracking-wider text-gray-400">
            {zh ? '自定义展示列' : 'Visible Columns'}
          </div>
          {(Object.keys(COLUMN_LABELS) as ColumnKey[]).map(key => (
            <label key={key} className="flex items-center gap-2.5 px-3 py-1.5 text-xs text-gray-700 dark:text-zinc-300
              hover:bg-gray-50 dark:hover:bg-zinc-800 cursor-pointer transition-colors">
              <input
                type="checkbox"
                checked={columns[key]}
                onChange={e => onChange(key, e.target.checked)}
                className="h-3.5 w-3.5 rounded border-gray-300 accent-blue-600 cursor-pointer"
              />
              <span className="font-medium">{zh ? COLUMN_LABELS[key].zh : COLUMN_LABELS[key].en}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
};

/* ════════════════════════════════════════════════════════
   Main Component
   ════════════════════════════════════════════════════════ */
interface InventoryDevicesTabProps {
  handleImport: (e: React.ChangeEvent<HTMLInputElement>) => void;
  handleExport: () => void;
  handleShowDetails: (device: Device) => void;
  handleTestConnection: (device: Device, mode?: 'quick' | 'deep') => void;
  deviceConnectionChecks: Record<string, DeviceConnectionCheckSummary>;
  connectionTestingDeviceId: string | null;
  setShowAddModal: (v: boolean) => void;
  setShowEditModal: (v: boolean) => void;
  setEditingDevice: (d: Device) => void;
  setEditForm: (d: Device) => void;
  setSelectedDevice: (d: Device) => void;
  setActiveTab: (tab: string) => void;
  onRefresh: () => void;
  language: string;
  t: (key: string) => string;
}

const InventoryDevicesTab: React.FC<InventoryDevicesTabProps> = ({
  handleImport, handleExport,
  handleShowDetails,
  handleTestConnection,
  deviceConnectionChecks, connectionTestingDeviceId,
  setShowAddModal, setShowEditModal, setEditingDevice, setEditForm,
  setSelectedDevice, setActiveTab, onRefresh, language, t,
}) => {
  const zh = language === 'zh';

  const {
    inventoryRows, inventoryTotal, inventoryStatusCounts, inventoryPage, setInventoryPage,
    inventoryPageSize, setInventoryPageSize,
    inventorySearch, setInventorySearch,
    inventoryPlatformFilter, setInventoryPlatformFilter,
    inventoryRoleFilter, setInventoryRoleFilter,
    inventoryStatusFilter, setInventoryStatusFilter,
    inventoryLifecycleFilter, setInventoryLifecycleFilter,
    inventorySortConfig, inventoryLoading,
    selectedDeviceIds, setSelectedDeviceIds,
    fetchInventory, inventoryRefreshTick
  } = useInventoryStore();

  const { handleSort, handleDeleteDevice, handleDeleteSelected } = useInventoryTableActions();

  const [quickFilter, setQuickFilter] = useState<'all' | 'offline' | 'warning' | 'staging_maintenance' | 'healthy'>('all');
  const [columns, setColumns] = useState<ColumnVisibility>({ ...DEFAULT_COLUMNS });
  const [allTags, setAllTags] = useState<TagDefinition[]>([]);
  const [tagFilterIds, setTagFilterIds] = useState<string[]>([]);
  const [batchTagOpen, setBatchTagOpen] = useState(false);
  const [batchTagIds, setBatchTagIds] = useState<string[]>([]);
  const [batchTagLoading, setBatchTagLoading] = useState(false);
  const [batchPlatformOpen, setBatchPlatformOpen] = useState(false);
  const batchTagRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const token = localStorage.getItem('netops_token');
    fetch('/api/tags/definitions', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then(r => r.json())
      .then(d => {
        if (d.success && Array.isArray(d.data)) {
          setAllTags(d.data.filter((tag: TagDefinition) => Number(tag.is_active ?? 1) !== 0));
        }
      })
      .catch(() => {});
  }, []);

  // ── Fetch inventory data whenever filters / pagination / refresh tick change ──
  useEffect(() => {
    void fetchInventory();
  }, [
    fetchInventory,
    inventorySearch,
    inventoryPlatformFilter,
    inventoryRoleFilter,
    inventoryStatusFilter,
    inventoryPage,
    inventoryPageSize,
    inventorySortConfig,
    inventoryRefreshTick,
  ]);

  useEffect(() => {
    if (!batchTagOpen) return;
    const handler = (e: MouseEvent) => {
      if (batchTagRef.current && !batchTagRef.current.contains(e.target as Node)) setBatchTagOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [batchTagOpen]);

  const handleColumnToggle = (key: ColumnKey, val: boolean) => {
    setColumns(prev => ({ ...prev, [key]: val }));
  };

  // Status & Health Counts
  const totalDevices = inventoryTotal || 0;
  const offlineCount = inventoryStatusCounts['offline'] || 0;
  const onlineCount = inventoryStatusCounts['online'] || 0;
  
  const warningCount = useMemo(() => {
    return inventoryRows.filter(d => d.health_status === 'warning' || d.health_status === 'critical' || (d.open_alert_count && d.open_alert_count > 0)).length;
  }, [inventoryRows]);

  const stagingOrMaintCount = useMemo(() => {
    return inventoryRows.filter(d => d.lifecycle_status === 'staging' || d.lifecycle_status === 'maintenance' || d.status === 'pending').length;
  }, [inventoryRows]);

  const healthyCount = useMemo(() => {
    return inventoryRows.filter(d => d.status === 'online' && d.health_status !== 'warning' && d.health_status !== 'critical' && (!d.open_alert_count || d.open_alert_count === 0)).length;
  }, [inventoryRows]);

  // Client-side filtering pipeline
  const lifecycleRows = (inventoryLifecycleFilter && inventoryLifecycleFilter !== 'all')
    ? inventoryRows.filter(d => d.lifecycle_status === inventoryLifecycleFilter)
    : inventoryRows;

  const baseRows = tagFilterIds.length > 0
    ? lifecycleRows.filter(d => d.tag_ids && tagFilterIds.some(tid => d.tag_ids!.includes(tid)))
    : lifecycleRows;

  const displayRows = useMemo(() => {
    if (quickFilter === 'offline') return baseRows.filter(d => d.status === 'offline');
    if (quickFilter === 'warning') return baseRows.filter(d => d.health_status === 'warning' || d.health_status === 'critical' || (d.open_alert_count && d.open_alert_count > 0));
    if (quickFilter === 'staging_maintenance') return baseRows.filter(d => d.lifecycle_status === 'staging' || d.lifecycle_status === 'maintenance' || d.status === 'pending');
    if (quickFilter === 'healthy') return baseRows.filter(d => d.status === 'online' && d.health_status !== 'warning' && d.health_status !== 'critical' && (!d.open_alert_count || d.open_alert_count === 0));
    return baseRows;
  }, [baseRows, quickFilter]);

  const hasFilters = Boolean(
    inventorySearch.trim() ||
    inventoryPlatformFilter !== 'all' ||
    inventoryRoleFilter !== 'all' ||
    inventoryStatusFilter !== 'all' ||
    (inventoryLifecycleFilter && inventoryLifecycleFilter !== 'all') ||
    tagFilterIds.length > 0 ||
    quickFilter !== 'all'
  );

  const clearAllFilters = () => {
    setInventorySearch('');
    setInventoryPlatformFilter('all');
    setInventoryRoleFilter('all');
    setInventoryStatusFilter('all');
    setInventoryLifecycleFilter('all');
    setTagFilterIds([]);
    setQuickFilter('all');
  };

  const handleEditDevice = (device: Device) => {
    setEditingDevice(device);
    setEditForm({ ...device, password: '' } as Device);
    setShowEditModal(true);
  };

  const handleManage = (device: Device) => {
    setSelectedDevice(device);
    setActiveTab('automation');
  };

  const handleBatchTagApply = async () => {
    if (batchTagIds.length === 0 || selectedDeviceIds.length === 0) return;
    setBatchTagLoading(true);
    try {
      const token = localStorage.getItem('netops_token');
      const resp = await fetch('/api/tags/devices/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ device_ids: selectedDeviceIds, tag_ids: batchTagIds }),
      });
      if (resp.ok) {
        setBatchTagOpen(false);
        setBatchTagIds([]);
        onRefresh();
      }
    } catch { /* ignore */ }
    setBatchTagLoading(false);
  };

  return (
    <div className="nx-page-shell flex flex-col h-full overflow-hidden">
      <PageHero
        icon={Router}
        title={zh ? '网络设备' : t('deviceInventory')}
        subtitle={zh ? '网络设备台账、多厂商驱动适配、配置同步与连通性监控' : t('manageMonitor')}
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowAddModal(true)}
              className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold transition-all shadow-2xs cursor-pointer"
            >
              <Plus size={13} />
              <span>{zh ? '添加设备' : 'Add Device'}</span>
            </button>
            <button
              onClick={onRefresh}
              title={zh ? '刷新设备列表' : 'Refresh list'}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-gray-200/80 dark:border-zinc-700/80
                bg-white dark:bg-zinc-800 text-xs font-semibold text-gray-700 dark:text-zinc-300
                hover:bg-gray-50 dark:hover:bg-zinc-700/60 transition-all cursor-pointer shadow-2xs"
            >
              <RefreshCw size={13} className={inventoryLoading ? 'animate-spin text-blue-500' : 'text-gray-500'} />
              <span>{zh ? '刷新' : 'Refresh'}</span>
            </button>
            <ColumnToggle columns={columns} onChange={handleColumnToggle} language={language} />
            <ActionButton
              icon={Download}
              variant="accent"
              onClick={handleExport}
              title={zh ? '导出设备清单' : 'Export device inventory'}
            >
              <span>{zh ? '导出' : t('export')}</span>
            </ActionButton>
          </div>
        }
      />

      <div className="flex-1 overflow-auto px-6 py-5 space-y-4">

        {/* ════ 5 联 Bento 状态统计卡片 ════ */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3.5">
          {([
            {
              key: 'all',
              value: totalDevices,
              label: zh ? '全部设备' : 'All Devices',
              sub: zh ? '全部' : 'ALL',
              Icon: Server,
              pill: 'bg-slate-100 dark:bg-zinc-800 text-slate-700 dark:text-zinc-300 border-slate-200/80 dark:border-zinc-700/80',
              iconBg: 'bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-300',
              activeBorder: 'border-blue-500 ring-2 ring-blue-500/20 shadow-sm',
              filterVal: 'all' as const,
            },
            {
              key: 'offline',
              value: offlineCount,
              label: zh ? '离线设备' : 'Offline',
              sub: 'P1',
              Icon: WifiOff,
              pill: 'bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300 border-rose-200/80 dark:border-rose-900/50',
              iconBg: 'bg-rose-50 dark:bg-rose-950/50 text-rose-600 dark:text-rose-400',
              activeBorder: 'border-rose-500 ring-2 ring-rose-500/20',
              filterVal: 'offline' as const,
              pulse: offlineCount > 0,
            },
            {
              key: 'warning',
              value: warningCount,
              label: zh ? '告警异常' : 'Alerts / Warning',
              sub: 'P2',
              Icon: AlertTriangle,
              pill: 'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300 border-amber-200/80 dark:border-amber-900/50',
              iconBg: 'bg-amber-50 dark:bg-amber-950/50 text-amber-600 dark:text-amber-400',
              activeBorder: 'border-amber-500 ring-2 ring-amber-500/20',
              filterVal: 'warning' as const,
            },
            {
              key: 'staging_maintenance',
              value: stagingOrMaintCount,
              label: zh ? '待投产 / 维护' : 'Staging / Maint',
              sub: 'P3',
              Icon: Shield,
              pill: 'bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300 border-blue-200/80 dark:border-blue-900/50',
              iconBg: 'bg-blue-50 dark:bg-blue-950/50 text-blue-600 dark:text-blue-400',
              activeBorder: 'border-blue-500 ring-2 ring-blue-500/20',
              filterVal: 'staging_maintenance' as const,
            },
            {
              key: 'healthy',
              value: healthyCount,
              label: zh ? '运行正常' : 'Healthy Online',
              sub: zh ? '正常' : 'OK',
              Icon: CheckCircle2,
              pill: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300 border-emerald-200/80 dark:border-emerald-900/50',
              iconBg: 'bg-emerald-50 dark:bg-emerald-950/50 text-emerald-600 dark:text-emerald-400',
              activeBorder: 'border-emerald-500 ring-2 ring-emerald-500/20',
              filterVal: 'healthy' as const,
            },
          ]).map(c => {
            const isActive = quickFilter === c.filterVal;
            const pct = totalDevices > 0 ? Math.round((c.value / totalDevices) * 100) : 0;

            return (
              <button
                key={c.key}
                type="button"
                onClick={() => setQuickFilter(c.filterVal === 'all' ? 'all' : isActive ? 'all' : c.filterVal)}
                className={`relative text-left p-4 rounded-2xl border transition-all duration-200 cursor-pointer group flex flex-col justify-between ${
                  isActive
                    ? `bg-white dark:bg-zinc-900 shadow-md ${c.activeBorder}`
                    : 'bg-white dark:bg-zinc-900/90 border-gray-100 dark:border-zinc-800/80 hover:border-gray-200 dark:hover:border-zinc-700 hover:shadow-2xs'
                }`}
              >
                <div>
                  <div className="flex items-center justify-between gap-2 mb-3">
                    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold tracking-wide border ${c.pill}`}>
                      {(c as any).pulse && <span className="w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse" />}
                      <span>{c.sub}</span>
                      <span className="opacity-70 font-normal">· {c.label}</span>
                    </span>
                    <div className={`w-7 h-7 rounded-xl flex items-center justify-center transition-transform group-hover:scale-105 ${c.iconBg}`}>
                      <c.Icon size={14} />
                    </div>
                  </div>
                  <div className="flex items-baseline gap-2">
                    <span className="nx-kpi-value text-gray-900 dark:text-white">
                      {c.value}
                    </span>
                    <span className="nx-meta-text font-medium text-gray-400 tabular-nums">({pct}%)</span>
                  </div>
                </div>
                <div className="mt-3.5 pt-2.5 border-t border-gray-50 dark:border-zinc-800/60">
                  <div className="h-1.5 w-full bg-gray-100 dark:bg-zinc-800 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all duration-500 ${c.iconBg.split(' ')[0]}`}
                      style={{ width: `${Math.max(c.value > 0 ? 6 : 0, pct)}%` }}
                    />
                  </div>
                </div>
              </button>
            );
          })}
        </div>

        {/* ════ Toolbar: Bento 搜索与高级过滤 ════ */}
        <div className="rounded-2xl border border-gray-100 dark:border-zinc-800/80 bg-white dark:bg-zinc-900/90 shadow-2xs p-3.5">
          <div className="flex flex-wrap items-center gap-2.5">
            {/* Search Input */}
            <div className="relative flex-1 min-w-[240px]">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" size={14} />
              <input
                type="text"
                placeholder={zh ? '搜索 IP / 主机名 / 序列号 / 站点…' : 'Search IP / hostname / SN / site…'}
                value={inventorySearch}
                onChange={e => setInventorySearch(e.target.value)}
                className="w-full pl-9 pr-8 py-1.5 text-xs bg-gray-50 dark:bg-zinc-800 border border-gray-200/80 dark:border-zinc-700
                  rounded-xl outline-none focus:border-blue-500 focus:bg-white dark:focus:bg-zinc-900 transition-all
                  text-gray-800 dark:text-zinc-200 placeholder:text-gray-400"
              />
              {inventorySearch && (
                <button
                  type="button"
                  onClick={() => setInventorySearch('')}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 p-0.5 cursor-pointer"
                >
                  <X size={12} />
                </button>
              )}
            </div>

            {/* Platform Select */}
            <select
              value={inventoryPlatformFilter}
              onChange={e => setInventoryPlatformFilter(e.target.value)}
              title={zh ? '按平台筛选' : 'Filter by platform'}
              className={`px-3 py-1.5 rounded-xl border text-xs outline-none cursor-pointer transition-all ${
                inventoryPlatformFilter !== 'all'
                  ? 'bg-blue-50 border-blue-200 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300 font-semibold'
                  : 'bg-gray-50 dark:bg-zinc-800 border-gray-200/80 dark:border-zinc-700 text-gray-600 dark:text-zinc-300'
              }`}
            >
              <option value="all">{t('allPlatforms')}</option>
              <option value="cisco_ios">Cisco IOS</option>
              <option value="cisco_xe">Cisco IOS-XE</option>
              <option value="cisco_nxos">Cisco NX-OS</option>
              <option value="juniper_junos">Juniper Junos</option>
              <option value="arista_eos">Arista EOS</option>
              <option value="fortinet_fortios">Fortinet FortiOS</option>
              <option value="huawei_vrp">Huawei VRP</option>
              <option value="huawei_vrpv8">Huawei VRPv8</option>
              <option value="h3c_comware">H3C Comware</option>
              <option value="ruijie_rgos">Ruijie RGOS</option>
              <option value="zte_zxros">ZTE ZXROS</option>
              <option value="maipu">Maipu Network OS</option>
            </select>

            {/* Role Select */}
            <select
              value={inventoryRoleFilter}
              onChange={e => setInventoryRoleFilter(e.target.value)}
              title={zh ? '按角色筛选' : 'Filter by role'}
              className={`px-3 py-1.5 rounded-xl border text-xs outline-none cursor-pointer transition-all ${
                inventoryRoleFilter !== 'all'
                  ? 'bg-blue-50 border-blue-200 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300 font-semibold'
                  : 'bg-gray-50 dark:bg-zinc-800 border-gray-200/80 dark:border-zinc-700 text-gray-600 dark:text-zinc-300'
              }`}
            >
              <option value="all">{zh ? '全部角色' : 'All Roles'}</option>
              <option value="core">Core</option>
              <option value="distribution">Distribution</option>
              <option value="access">Access</option>
              <option value="edge">Edge</option>
              <option value="firewall">Firewall</option>
              <option value="vpn">VPN</option>
              <option value="test">Test</option>
            </select>

            {/* Status Select */}
            <select
              value={inventoryStatusFilter}
              onChange={e => setInventoryStatusFilter(e.target.value)}
              title={zh ? '按在线状态筛选' : 'Filter by status'}
              className={`px-3 py-1.5 rounded-xl border text-xs outline-none cursor-pointer transition-all ${
                inventoryStatusFilter !== 'all'
                  ? 'bg-blue-50 border-blue-200 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300 font-semibold'
                  : 'bg-gray-50 dark:bg-zinc-800 border-gray-200/80 dark:border-zinc-700 text-gray-600 dark:text-zinc-300'
              }`}
            >
              <option value="all">{zh ? '全部状态' : 'All Status'}</option>
              <option value="online">{zh ? '在线' : 'Online'}</option>
              <option value="offline">{zh ? '离线' : 'Offline'}</option>
              <option value="pending">{zh ? '等待中' : 'Pending'}</option>
            </select>

            {/* Lifecycle Select */}
            <select
              value={inventoryLifecycleFilter ?? 'all'}
              onChange={e => setInventoryLifecycleFilter(e.target.value)}
              title={zh ? '按生命周期筛选' : 'Filter by lifecycle'}
              className={`px-3 py-1.5 rounded-xl border text-xs outline-none cursor-pointer transition-all ${
                inventoryLifecycleFilter && inventoryLifecycleFilter !== 'all'
                  ? 'bg-blue-50 border-blue-200 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300 font-semibold'
                  : 'bg-gray-50 dark:bg-zinc-800 border-gray-200/80 dark:border-zinc-700 text-gray-600 dark:text-zinc-300'
              }`}
            >
              <option value="all">{zh ? '全部投产状态' : 'All Lifecycle'}</option>
              <option value="staging">{zh ? '待投产' : 'Staging'}</option>
              <option value="production">{zh ? '已投产' : 'Production'}</option>
              <option value="maintenance">{zh ? '维护中' : 'Maintenance'}</option>
              <option value="decommissioned">{zh ? '已退役' : 'Decommissioned'}</option>
            </select>

            {/* Tag Filter */}
            <TagFilterDropdown
              allTags={allTags}
              selectedTagIds={tagFilterIds}
              onChange={setTagFilterIds}
              language={language}
            />

            {/* Reset CTA */}
            {hasFilters && (
              <button
                type="button"
                onClick={clearAllFilters}
                className="text-xs font-semibold text-blue-600 hover:underline ml-1 cursor-pointer whitespace-nowrap"
              >
                {zh ? '重置筛选' : 'Reset'}
              </button>
            )}

            <div className="flex-1" />
            <span className="text-xs font-mono text-gray-400 tabular-nums whitespace-nowrap">
              {zh ? `共 ${displayRows.length} 台设备` : `${displayRows.length} devices`}
            </span>
          </div>
        </div>

        {/* ════ Batch Action Floating Capsule ════ */}
        {selectedDeviceIds.length > 0 && (
          <div className="rounded-2xl border border-blue-100 dark:border-blue-900/40 bg-blue-50/60 dark:bg-blue-950/30 p-3 flex items-center justify-between gap-3 shadow-2xs animate-fadeIn">
            <div className="flex items-center gap-2">
              <span className="h-6 w-6 rounded-full bg-blue-600 text-white text-xs font-bold font-mono inline-flex items-center justify-center">
                {selectedDeviceIds.length}
              </span>
              <span className="text-xs font-semibold text-gray-700 dark:text-zinc-200">
                {zh ? `已选中 ${selectedDeviceIds.length} 台网络设备` : `${selectedDeviceIds.length} devices selected`}
              </span>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() => {
                  const selected = inventoryRows.filter(d => selectedDeviceIds.includes(d.id));
                  selected.forEach(d => handleTestConnection(d, 'quick'));
                }}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold
                  border border-violet-200 dark:border-violet-500/30 bg-white dark:bg-zinc-800 text-violet-700 dark:text-violet-300
                  hover:bg-violet-50 dark:hover:bg-violet-950/40 transition-all cursor-pointer shadow-2xs"
              >
                <Activity size={13} className="text-violet-500" />
                <span>{zh ? '批量连通检查' : 'Batch Check'}</span>
              </button>

              <button
                onClick={() => {
                  const selected = inventoryRows.filter(d => selectedDeviceIds.includes(d.id));
                  if (selected.length > 0) {
                    setSelectedDevice(selected[0]);
                    setActiveTab('automation');
                  }
                }}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold
                  border border-blue-200 dark:border-blue-500/30 bg-white dark:bg-zinc-800 text-blue-700 dark:text-blue-300
                  hover:bg-blue-50 dark:hover:bg-blue-950/40 transition-all cursor-pointer shadow-2xs"
              >
                <Shield size={13} className="text-blue-500" />
                <span>{zh ? '批量配置变更' : 'Batch Config'}</span>
              </button>

              <button
                type="button"
                onClick={() => setBatchPlatformOpen(true)}
                disabled={selectedDeviceIds.length > 200}
                className="inline-flex items-center gap-1.5 rounded-xl border border-cyan-200 bg-white px-3 py-1.5 text-xs font-semibold text-cyan-700 shadow-2xs transition-all hover:bg-cyan-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-cyan-500/30 dark:bg-zinc-800 dark:text-cyan-300 dark:hover:bg-cyan-950/40"
                title={selectedDeviceIds.length > 200 ? (zh ? '批量平台操作最多支持 200 台设备' : 'Batch platform operations support up to 200 devices') : undefined}
              >
                <Settings2 size={13} className="text-cyan-500" />
                <span>{zh ? '批量平台' : 'Batch Platform'}</span>
              </button>

              <div ref={batchTagRef} className="relative">
                <button
                  onClick={() => setBatchTagOpen(!batchTagOpen)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold
                    border border-teal-200 dark:border-teal-500/30 bg-white dark:bg-zinc-800 text-teal-700 dark:text-teal-300
                    hover:bg-teal-50 dark:hover:bg-teal-950/40 transition-all cursor-pointer shadow-2xs"
                >
                  <Tag size={13} className="text-teal-500" />
                  <span>{zh ? '批量标签' : 'Batch Tags'}</span>
                </button>
                {batchTagOpen && (
                  <div className="absolute right-0 top-full mt-1.5 z-50 w-72 rounded-2xl border border-gray-100 dark:border-zinc-800
                    bg-white dark:bg-zinc-900 shadow-xl shadow-black/10 dark:shadow-black/40 overflow-hidden">
                    <div className="px-3.5 py-2.5 border-b border-gray-100 dark:border-zinc-800 text-xs font-bold text-gray-700 dark:text-zinc-200">
                      {zh
                        ? `为选中的 ${selectedDeviceIds.length} 台设备添加标签`
                        : `Add tags to ${selectedDeviceIds.length} devices`}
                    </div>
                    <div className="p-3">
                      <TagFilterDropdown
                        allTags={allTags}
                        selectedTagIds={batchTagIds}
                        onChange={setBatchTagIds}
                        language={language}
                        excludeStatusTags
                      />
                    </div>
                    <div className="px-3.5 py-2.5 border-t border-gray-100 dark:border-zinc-800 flex justify-end gap-2 bg-gray-50/50 dark:bg-zinc-800/40">
                      <button
                        onClick={() => setBatchTagOpen(false)}
                        className="px-3 py-1.5 rounded-xl text-xs font-semibold text-gray-600 dark:text-zinc-400 hover:bg-gray-100 dark:hover:bg-zinc-800 cursor-pointer"
                      >
                        {zh ? '取消' : 'Cancel'}
                      </button>
                      <button
                        onClick={handleBatchTagApply}
                        disabled={batchTagIds.length === 0 || batchTagLoading}
                        className="px-3 py-1.5 rounded-xl text-xs font-bold bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer shadow-2xs"
                      >
                        {batchTagLoading
                          ? (zh ? '应用中…' : 'Applying…')
                          : (zh ? '应用标签' : 'Apply')}
                      </button>
                    </div>
                  </div>
                )}
              </div>

              <button
                onClick={() => setSelectedDeviceIds([])}
                className="p-1.5 rounded-xl text-gray-400 hover:text-gray-600 hover:bg-gray-100 dark:hover:bg-zinc-800 cursor-pointer transition-colors"
                title={zh ? '取消全选' : 'Clear selection'}
              >
                <X size={14} />
              </button>
            </div>
          </div>
        )}

        {/* ════ Table Container ════ */}
        <div className="rounded-2xl border border-gray-100 dark:border-zinc-800/80 bg-white dark:bg-zinc-900/90 shadow-2xs overflow-hidden">
          <DeviceTable
            rows={displayRows}
            loading={inventoryLoading}
            language={language}
            sortConfig={inventorySortConfig}
            onSort={handleSort}
            selectedIds={selectedDeviceIds}
            onSelectChange={setSelectedDeviceIds}
            onShowDetails={handleShowDetails}
            onEdit={undefined}
            onDelete={undefined}
            onManage={handleManage}
            onTestConnection={handleTestConnection}
            deviceConnectionChecks={deviceConnectionChecks}
            connectionTestingDeviceId={connectionTestingDeviceId}
            columns={columns}
          />
          <Pagination
            currentPage={inventoryPage}
            totalItems={quickFilter !== 'all' || tagFilterIds.length > 0 || (inventoryLifecycleFilter && inventoryLifecycleFilter !== 'all') ? displayRows.length : inventoryTotal}
            itemsPerPage={inventoryPageSize}
            onItemsPerPageChange={setInventoryPageSize}
            onPageChange={setInventoryPage}
            language={language}
          />
        </div>

      </div>
      {batchPlatformOpen && (
        <BatchPlatformBindingModal
          deviceIds={selectedDeviceIds}
          devices={inventoryRows}
          language={language}
          onClose={() => setBatchPlatformOpen(false)}
          onCompleted={async () => {
            setBatchPlatformOpen(false);
            setSelectedDeviceIds([]);
            await fetchInventory();
            onRefresh();
          }}
        />
      )}
    </div>
  );
};

export default InventoryDevicesTab;
