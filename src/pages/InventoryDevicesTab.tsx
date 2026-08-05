import React, { useState, useRef, useEffect } from 'react';
import { useInventoryStore } from '../store/inventoryStore';
import { useInventoryTableActions } from '../hooks/useInventoryTableActions';
import {
  Upload, Download, Plus, Search, Activity,
  AlertTriangle, CheckCircle2, XCircle, Server, Router,
  Shield, Trash2, SlidersHorizontal, Tag,
} from 'lucide-react';
import type { Device, DeviceConnectionCheckSummary, TagDefinition } from '../types';
import Pagination from '../components/Pagination';
import DeviceTable, { DEFAULT_COLUMNS, type ColumnVisibility, type ColumnKey } from '../components/DeviceList/DeviceTable';
import TagFilterDropdown from '../components/TagFilterDropdown';
import PageHero from '../components/PageHero';

/* ─── Quick Filter Tag ─── */
const QuickTag: React.FC<{
  icon: React.ReactNode; label: string; count: number; active: boolean;
  tone: string; onClick: () => void;
}> = ({ icon, label, count, active, tone, onClick }) => (
  <button
    onClick={onClick}
    className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium
      border transition-all select-none whitespace-nowrap cursor-pointer
      ${active ? tone : 'bg-transparent border-black/6 dark:border-white/8 text-black/45 dark:text-white/40 hover:border-black/12 dark:hover:border-white/15'}`}
  >
    {icon}
    {label}
    <span className={`ml-0.5 tabular-nums ${active ? 'opacity-90' : 'opacity-50'}`}>{count}</span>
  </button>
);

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
        className="inline-flex items-center gap-1.5 px-2.5 py-1.5 border border-black/8 dark:border-white/10
          rounded-lg text-[11px] font-medium text-black/55 dark:text-white/55 hover:bg-black/[.03] dark:hover:bg-white/[.05] transition-all">
        <SlidersHorizontal size={13} />
        {zh ? '列' : 'Columns'}
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 w-40 rounded-lg border border-black/8 dark:border-white/12
          bg-white dark:bg-[#111b2d] shadow-lg shadow-black/10 dark:shadow-black/40 py-1.5">
          {(Object.keys(COLUMN_LABELS) as ColumnKey[]).map(key => (
            <label key={key} className="flex items-center gap-2 px-3 py-1 text-[11px] text-black/65 dark:text-white/65
              hover:bg-black/5 dark:hover:bg-white/8 cursor-pointer transition-colors">
              <input
                type="checkbox"
                checked={columns[key]}
                onChange={e => onChange(key, e.target.checked)}
                className="rounded border-black/20 dark:border-white/20 text-[#00bceb] focus:ring-[#00bceb] focus:ring-offset-0"
              />
              {zh ? COLUMN_LABELS[key].zh : COLUMN_LABELS[key].en}
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

  const [quickFilter, setQuickFilter] = useState<'all' | 'offline' | 'warning' | 'healthy'>('all');
  const [columns, setColumns] = useState<ColumnVisibility>({ ...DEFAULT_COLUMNS });
  const [allTags, setAllTags] = useState<TagDefinition[]>([]);
  const [tagFilterIds, setTagFilterIds] = useState<string[]>([]);
  const [batchTagOpen, setBatchTagOpen] = useState(false);
  const [batchTagIds, setBatchTagIds] = useState<string[]>([]);
  const [batchTagLoading, setBatchTagLoading] = useState(false);
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

  const totalDevices = inventoryTotal || 0;
  const offlineCount = inventoryStatusCounts['offline'] || 0;
  const onlineCount = inventoryStatusCounts['online'] || 0;
  const warningCount = inventoryRows.filter(d => d.health_status === 'warning' || d.health_status === 'critical').length;
  const healthyCount = onlineCount - warningCount;

  const lifecycleRows = (inventoryLifecycleFilter && inventoryLifecycleFilter !== 'all')
    ? inventoryRows.filter(d => d.lifecycle_status === inventoryLifecycleFilter)
    : inventoryRows;

  const baseRows = tagFilterIds.length > 0
    ? lifecycleRows.filter(d => d.tag_ids && tagFilterIds.some(tid => d.tag_ids!.includes(tid)))
    : lifecycleRows;

  const displayRows = quickFilter === 'all' ? baseRows
    : quickFilter === 'offline' ? baseRows.filter(d => d.status === 'offline')
    : quickFilter === 'warning' ? baseRows.filter(d => d.health_status === 'warning' || d.health_status === 'critical')
    : baseRows.filter(d => d.status === 'online' && (d.health_status === 'healthy' || !d.health_status));

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
    <div className="flex flex-col h-full overflow-hidden">
      <PageHero
        icon={Router}
        title={t('deviceInventory')}
        subtitle={t('manageMonitor')}
        actions={
          <>
            <ColumnToggle columns={columns} onChange={handleColumnToggle} language={language} />
            <button onClick={handleExport}
              title={language === 'zh' ? '导出设备清单' : 'Export device inventory'}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 border border-black/8 dark:border-white/10
                rounded-lg text-xs font-medium text-black/55 dark:text-white/55 hover:bg-black/[.03] dark:hover:bg-white/[.05] transition-all">
              <Download size={14} />
              {t('export')}
            </button>
          </>
        }
      />

      <div className="flex-1 overflow-auto px-6 py-5 space-y-4">

      {/* ════ Toolbar: Search + Filters ════ */}
      <div className="flex flex-col lg:flex-row gap-3 p-3 rounded-xl border border-black/5 dark:border-white/8 bg-[var(--card-bg)]">
        <div className="relative flex-1 min-w-0">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-black/30 dark:text-white/25 pointer-events-none" size={14} />
          <input
            type="text"
            placeholder={language === 'zh' ? '搜索 IP / 设备名 / SN …' : 'Search IP / hostname / SN …'}
            value={inventorySearch}
            onChange={e => setInventorySearch(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 text-xs bg-transparent border border-black/6 dark:border-white/8
              rounded-lg outline-none focus:border-[#00bceb]/40 dark:focus:border-[#00bceb]/40
              text-black/80 dark:text-white/80 placeholder:text-black/25 dark:placeholder:text-white/20"
          />
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <select value={inventoryPlatformFilter} onChange={e => setInventoryPlatformFilter(e.target.value)}
            title={language === 'zh' ? '按平台筛选' : 'Filter by platform'}
            className="px-2.5 py-1.5 text-[11px] border border-black/6 dark:border-white/8 rounded-lg bg-transparent
              outline-none text-black/55 dark:text-white/55 focus:border-[#00bceb]/40">
            <option value="all">{t('allPlatforms')}</option>
            <option value="cisco_ios">Cisco IOS</option>
            <option value="cisco_xe">Cisco IOS-XE</option>
            <option value="cisco_nxos">Cisco NX-OS</option>
            <option value="juniper_junos">Juniper Junos</option>
            <option value="arista_eos">Arista EOS</option>
            <option value="fortinet_fortios">Fortinet FortiOS</option>
            <option value="huawei_vrp">Huawei VRP</option>
            <option value="huawei_vrpv8">Huawei VRPv8</option>
            <option value="hp_comware">H3C Comware V5</option>
            <option value="h3c_comware">H3C Comware V7</option>
            <option value="h3c_comware9">H3C Comware V9</option>
            <option value="ruijie_rgos">Ruijie RGOS</option>
            <option value="zte_zxros">ZTE ZXROS</option>
            <option value="maipu">Maipu Network OS</option>
          </select>
          <select value={inventoryRoleFilter} onChange={e => setInventoryRoleFilter(e.target.value)}
            title={language === 'zh' ? '按角色筛选' : 'Filter by role'}
            className="px-2.5 py-1.5 text-[11px] border border-black/6 dark:border-white/8 rounded-lg bg-transparent
              outline-none text-black/55 dark:text-white/55 focus:border-[#00bceb]/40">
            <option value="all">{language === 'zh' ? '全部角色' : 'All Roles'}</option>
            <option value="core">Core</option>
            <option value="distribution">Distribution</option>
            <option value="access">Access</option>
            <option value="edge">Edge</option>
            <option value="firewall">Firewall</option>
            <option value="vpn">VPN</option>
            <option value="test">Test</option>
          </select>
          <select value={inventoryStatusFilter} onChange={e => setInventoryStatusFilter(e.target.value)}
            title={language === 'zh' ? '按状态筛选' : 'Filter by status'}
            className="px-2.5 py-1.5 text-[11px] border border-black/6 dark:border-white/8 rounded-lg bg-transparent
              outline-none text-black/55 dark:text-white/55 focus:border-[#00bceb]/40">
            <option value="all">{language === 'zh' ? '全部状态' : 'All Status'}</option>
            <option value="online">{language === 'zh' ? '在线' : 'Online'}</option>
            <option value="offline">{language === 'zh' ? '离线' : 'Offline'}</option>
            <option value="pending">{language === 'zh' ? '等待中' : 'Pending'}</option>
          </select>
          <select value={inventoryLifecycleFilter ?? 'all'} onChange={e => setInventoryLifecycleFilter(e.target.value)}
            title={language === 'zh' ? '按投产状态筛选' : 'Filter by lifecycle'}
            className="px-2.5 py-1.5 text-[11px] border border-black/6 dark:border-white/8 rounded-lg bg-transparent
              outline-none text-black/55 dark:text-white/55 focus:border-[#00bceb]/40">
            <option value="all">{language === 'zh' ? '全部投产状态' : 'All Lifecycle'}</option>
            <option value="staging">{language === 'zh' ? '待投产' : 'Staging'}</option>
            <option value="production">{language === 'zh' ? '已投产' : 'Production'}</option>
            <option value="maintenance">{language === 'zh' ? '维护中' : 'Maintenance'}</option>
            <option value="decommissioned">{language === 'zh' ? '已退役' : 'Decommissioned'}</option>
          </select>
          <TagFilterDropdown
            allTags={allTags}
            selectedTagIds={tagFilterIds}
            onChange={setTagFilterIds}
            language={language}
          />

        </div>
      </div>

      {/* ════ Quick Filters + Batch Actions ════ */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-1.5 flex-wrap">
          <QuickTag icon={<Server size={11} />} label={language === 'zh' ? '全部' : 'All'} count={totalDevices}
            active={quickFilter === 'all'}
            tone="bg-[#00bceb]/10 border-[#00bceb]/25 text-[#0096bd] dark:text-[#5dd8f0] dark:border-[#00bceb]/20"
            onClick={() => setQuickFilter('all')} />
          <QuickTag icon={<XCircle size={11} />} label={language === 'zh' ? '离线' : 'Offline'} count={offlineCount}
            active={quickFilter === 'offline'}
            tone="bg-red-500/10 border-red-500/25 text-red-600 dark:text-red-400 dark:border-red-500/20"
            onClick={() => setQuickFilter(quickFilter === 'offline' ? 'all' : 'offline')} />
          <QuickTag icon={<AlertTriangle size={11} />} label={language === 'zh' ? '告警' : 'Warning'} count={warningCount}
            active={quickFilter === 'warning'}
            tone="bg-amber-500/10 border-amber-500/25 text-amber-600 dark:text-amber-400 dark:border-amber-500/20"
            onClick={() => setQuickFilter(quickFilter === 'warning' ? 'all' : 'warning')} />
          <QuickTag icon={<CheckCircle2 size={11} />} label={language === 'zh' ? '健康' : 'Healthy'} count={Math.max(0, healthyCount)}
            active={quickFilter === 'healthy'}
            tone="bg-emerald-500/10 border-emerald-500/25 text-emerald-600 dark:text-emerald-400 dark:border-emerald-500/20"
            onClick={() => setQuickFilter(quickFilter === 'healthy' ? 'all' : 'healthy')} />
        </div>

        {selectedDeviceIds.length > 0 && (
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-medium text-black/45 dark:text-white/40 tabular-nums">
              {selectedDeviceIds.length} {language === 'zh' ? '已选' : 'selected'}
            </span>
            <button
              onClick={() => {
                const selected = inventoryRows.filter(d => selectedDeviceIds.includes(d.id));
                selected.forEach(d => handleTestConnection(d, 'quick'));
              }}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-medium
                border border-violet-200 dark:border-violet-500/25 bg-violet-500/10 text-violet-600 dark:text-violet-400
                hover:bg-violet-500/20 transition-all">
              <Activity size={11} />
              {language === 'zh' ? '批量检查' : 'Batch Check'}
            </button>
            <button
              onClick={() => {
                const selected = inventoryRows.filter(d => selectedDeviceIds.includes(d.id));
                if (selected.length > 0) {
                  setSelectedDevice(selected[0]);
                  setActiveTab('automation');
                }
              }}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-medium
                border border-[#00bceb]/25 bg-[#00bceb]/10 text-[#0096bd] dark:text-[#5dd8f0]
                hover:bg-[#00bceb]/20 transition-all">
              <Shield size={11} />
              {language === 'zh' ? '批量配置' : 'Batch Config'}
            </button>
            <div ref={batchTagRef} className="relative">
              <button
                onClick={() => setBatchTagOpen(!batchTagOpen)}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-medium
                  border border-teal-200 dark:border-teal-500/25 bg-teal-500/10 text-teal-600 dark:text-teal-400
                  hover:bg-teal-500/20 transition-all">
                <Tag size={11} />
                {language === 'zh' ? '批量标签' : 'Batch Tags'}
              </button>
              {batchTagOpen && (
                <div className="absolute right-0 top-full mt-1 z-50 w-72 rounded-xl border border-black/8 dark:border-white/12
                  bg-white dark:bg-[#111b2d] shadow-xl shadow-black/10 dark:shadow-black/40 overflow-hidden">
                  <div className="px-3 py-2 border-b border-black/5 dark:border-white/8 text-[11px] font-medium text-black/60 dark:text-white/55">
                    {language === 'zh'
                      ? `为 ${selectedDeviceIds.length} 台设备添加标签`
                      : `Add tags to ${selectedDeviceIds.length} devices`}
                  </div>
                  <div className="p-2">
                    <TagFilterDropdown
                      allTags={allTags}
                      selectedTagIds={batchTagIds}
                      onChange={setBatchTagIds}
                      language={language}
                      excludeStatusTags
                    />
                  </div>
                  <div className="px-3 py-2 border-t border-black/5 dark:border-white/8 flex justify-end gap-2">
                    <button onClick={() => setBatchTagOpen(false)}
                      className="px-2.5 py-1 rounded-md text-[10px] font-medium text-black/50 dark:text-white/40
                        hover:bg-black/5 dark:hover:bg-white/8 transition-all">
                      {language === 'zh' ? '取消' : 'Cancel'}
                    </button>
                    <button onClick={handleBatchTagApply} disabled={batchTagIds.length === 0 || batchTagLoading}
                      className="px-2.5 py-1 rounded-md text-[10px] font-medium bg-[#00bceb] text-white
                        hover:bg-[#0096bd] disabled:opacity-40 disabled:cursor-not-allowed transition-all">
                      {batchTagLoading
                        ? (language === 'zh' ? '应用中…' : 'Applying…')
                        : (language === 'zh' ? '应用' : 'Apply')}
                    </button>
                  </div>
                </div>
              )}
            </div>
            {/* Batch delete removed — use Asset Management for CRUD */}
          </div>
        )}
      </div>

      {/* ════ Table ════ */}
      <div className="rounded-xl border border-black/5 dark:border-white/8 bg-[var(--card-bg)] overflow-hidden">
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
          totalItems={inventoryTotal}
          itemsPerPage={inventoryPageSize}
          onItemsPerPageChange={setInventoryPageSize}
          onPageChange={setInventoryPage}
          language={language}
        />
      </div>
      </div>
    </div>
  );
};

export default InventoryDevicesTab;
