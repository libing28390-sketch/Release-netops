import React, { useState, useCallback, useRef, useEffect } from 'react';
import {
  Upload, Download, Plus, Search, Activity, ChevronDown, ChevronUp,
  MoreHorizontal, Eye, Pencil, Trash2, Wifi, WifiOff, AlertTriangle,
  CheckCircle2, XCircle, Server, Shield, ChevronRight,
} from 'lucide-react';
import type { Device, DeviceConnectionCheckSummary } from '../types';
import Sparkline from '../components/Sparkline';
import Pagination from '../components/Pagination';

/* ─── Helpers ─── */
const clampPercent = (value?: number) => {
  const n = Number(value ?? 0);
  return Number.isFinite(n) ? Math.max(0, Math.min(100, n)) : 0;
};

const formatCheckTime = (value: string, language: string) => {
  try {
    return new Date(value).toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US', {
      month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
    });
  } catch { return value; }
};

const vendorOf = (platform: string): string => {
  if (!platform) return 'Unknown';
  const p = platform.toLowerCase();
  if (p.includes('cisco')) return 'Cisco';
  if (p.includes('huawei') || p.includes('vrp')) return 'Huawei';
  if (p.includes('juniper') || p.includes('junos')) return 'Juniper';
  if (p.includes('arista')) return 'Arista';
  if (p.includes('fortinet')) return 'Fortinet';
  if (p.includes('h3c') || p.includes('comware')) return 'H3C';
  if (p.includes('ruijie')) return 'Ruijie';
  return platform.split('_')[0] || 'Other';
};

/* ─── Status / Health config ─── */
const STATUS_CFG = {
  online:  { dot: 'bg-emerald-500', text: 'text-emerald-600 dark:text-emerald-400', ping: true,  labelZh: '在线',   labelEn: 'Online' },
  offline: { dot: 'bg-red-500',     text: 'text-red-500 dark:text-red-400',         ping: false, labelZh: '离线',   labelEn: 'Offline' },
  pending: { dot: 'bg-amber-500',   text: 'text-amber-600 dark:text-amber-400',     ping: false, labelZh: '等待中', labelEn: 'Pending' },
} as const;

const HEALTH_CFG: Record<string, { bg: string; text: string; labelZh: string; labelEn: string }> = {
  healthy:  { bg: 'bg-emerald-500/10 dark:bg-emerald-500/15', text: 'text-emerald-600 dark:text-emerald-400', labelZh: '健康', labelEn: 'Healthy' },
  warning:  { bg: 'bg-amber-500/10 dark:bg-amber-500/15',    text: 'text-amber-600 dark:text-amber-400',     labelZh: '警告', labelEn: 'Warning' },
  critical: { bg: 'bg-red-500/10 dark:bg-red-500/15',        text: 'text-red-600 dark:text-red-400',         labelZh: '严重', labelEn: 'Critical' },
  unknown:  { bg: 'bg-slate-500/10 dark:bg-slate-500/15',    text: 'text-slate-500 dark:text-slate-400',     labelZh: '未知', labelEn: 'Unknown' },
};

const CHECK_BADGE: Record<DeviceConnectionCheckSummary['status'], { zh: string; en: string; cls: string }> = {
  ok:            { zh: 'OK',        en: 'OK',          cls: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400' },
  tcp_fail:      { zh: 'TCP 失败',  en: 'TCP Fail',    cls: 'bg-red-500/10 text-red-600 dark:text-red-400' },
  ssh_auth_fail: { zh: 'SSH 认证失败', en: 'SSH Auth Fail', cls: 'bg-rose-500/10 text-rose-600 dark:text-rose-400' },
  ssh_timeout:   { zh: 'SSH 超时',  en: 'SSH Timeout',  cls: 'bg-orange-500/10 text-orange-600 dark:text-orange-400' },
  ssh_transport: { zh: 'SSH 传输',  en: 'SSH Transport', cls: 'bg-slate-500/10 text-slate-500 dark:text-slate-400' },
  ssh_legacy:    { zh: '旧SSH',     en: 'Legacy SSH',  cls: 'bg-amber-500/10 text-amber-600 dark:text-amber-400' },
  fail:          { zh: '失败',      en: 'Fail',        cls: 'bg-red-500/10 text-red-600 dark:text-red-400' },
};

/* ─── MiniBar for CPU/MEM ─── */
const MiniBar: React.FC<{ value: number; color: string; label: string }> = ({ value, color, label }) => (
  <div className="flex items-center gap-1.5 min-w-0" title={`${label} ${value}%`}>
    <span className="text-[9px] font-semibold text-black/40 dark:text-white/40 w-7 shrink-0 tabular-nums text-right">{value}%</span>
    <div className="flex-1 h-[5px] rounded-full bg-black/5 dark:bg-white/8 overflow-hidden min-w-[36px] max-w-[52px]">
      <div
        className="h-full rounded-full transition-all duration-500"
        style={{ width: `${value}%`, backgroundColor: value > 85 ? '#ef4444' : value > 65 ? '#f59e0b' : color }}
      />
    </div>
  </div>
);

/* ─── Action Dropdown (... menu) ─── */
const ActionDropdown: React.FC<{
  language: string;
  onDetails: () => void;
  onEdit: () => void;
  onDelete: () => void;
}> = ({ language, onDetails, onEdit, onDelete }) => {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const items = [
    { icon: Eye, label: language === 'zh' ? '查看详情' : 'Details', action: onDetails, cls: '' },
    { icon: Pencil, label: language === 'zh' ? '编辑设备' : 'Edit', action: onEdit, cls: '' },
    { icon: Trash2, label: language === 'zh' ? '删除' : 'Delete', action: onDelete, cls: 'text-red-500 dark:text-red-400' },
  ];

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        title={language === 'zh' ? '更多操作' : 'More actions'}
        className="p-1 rounded-md text-black/30 dark:text-white/30 hover:text-black/60 dark:hover:text-white/60
          hover:bg-black/5 dark:hover:bg-white/8 transition-all"
      >
        <MoreHorizontal size={15} />
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 w-36 rounded-lg border border-black/8 dark:border-white/12
          bg-white dark:bg-[#111b2d] shadow-lg shadow-black/10 dark:shadow-black/40 py-1">
          {items.map(({ icon: Icon, label, action, cls }) => (
            <button
              key={label}
              onClick={() => { setOpen(false); action(); }}
              className={`w-full flex items-center gap-2 px-3 py-1.5 text-[11px] font-medium
                hover:bg-black/5 dark:hover:bg-white/8 transition-colors ${cls || 'text-black/65 dark:text-white/65'}`}
            >
              <Icon size={13} />
              {label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

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

/* ─── Expanded Row Panel ─── */
const ExpandedPanel: React.FC<{
  device: Device; language: string;
  deviceConnectionChecks: Record<string, DeviceConnectionCheckSummary>;
}> = ({ device, language, deviceConnectionChecks }) => {
  const check = deviceConnectionChecks[device.id];
  const badge = check ? CHECK_BADGE[check.status] || CHECK_BADGE.fail : null;
  const h = HEALTH_CFG[device.health_status || 'unknown'] || HEALTH_CFG.unknown;

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-x-6 gap-y-3 px-6 py-4 bg-black/[.015] dark:bg-white/[.02]
      border-t border-black/4 dark:border-white/6 text-[11px]">
      <div>
        <span className="text-[9px] uppercase tracking-wider font-semibold text-black/30 dark:text-white/25 block mb-1">
          {language === 'zh' ? '硬件' : 'Hardware'}
        </span>
        <p className="text-black/65 dark:text-white/65">{language === 'zh' ? '型号' : 'Model'}: <span className="font-medium">{device.model || 'N/A'}</span></p>
        <p className="text-black/65 dark:text-white/65">SN: <span className="font-mono font-medium">{device.sn || 'N/A'}</span></p>
        <p className="text-black/65 dark:text-white/65">{language === 'zh' ? '运行时间' : 'Uptime'}: <span className="font-medium">{device.uptime || 'N/A'}</span></p>
      </div>
      <div>
        <span className="text-[9px] uppercase tracking-wider font-semibold text-black/30 dark:text-white/25 block mb-1">
          {language === 'zh' ? '软件' : 'Software'}
        </span>
        <p className="text-black/65 dark:text-white/65">{language === 'zh' ? '版本' : 'Version'}: <span className="font-medium">{device.version || 'N/A'}</span></p>
        <p className="text-black/65 dark:text-white/65">{language === 'zh' ? '协议' : 'Method'}: <span className="font-medium uppercase">{device.connection_method || 'ssh'}</span></p>
        <p className="text-black/65 dark:text-white/65">{language === 'zh' ? '合规' : 'Compliance'}:
          <span className={`ml-1 font-medium ${device.compliance === 'compliant' ? 'text-emerald-600 dark:text-emerald-400' : device.compliance === 'non-compliant' ? 'text-red-500 dark:text-red-400' : 'text-black/40 dark:text-white/40'}`}>
            {device.compliance || 'unknown'}
          </span>
        </p>
      </div>
      <div>
        <span className="text-[9px] uppercase tracking-wider font-semibold text-black/30 dark:text-white/25 block mb-1">
          {language === 'zh' ? '健康详情' : 'Health Detail'}
        </span>
        <p className="text-black/65 dark:text-white/65">
          {language === 'zh' ? '评分' : 'Score'}: <span className="font-semibold">{Math.max(0, Math.min(100, Number(device.health_score || 0)))}</span>
          <span className={`ml-1.5 inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-bold uppercase ${h.bg} ${h.text}`}>
            {language === 'zh' ? h.labelZh : h.labelEn}
          </span>
        </p>
        <p className="text-black/45 dark:text-white/40 mt-0.5 line-clamp-2">{device.health_summary || (language === 'zh' ? '暂无摘要' : 'No summary')}</p>
        <div className="flex gap-3 mt-1 text-[10px] text-black/40 dark:text-white/35">
          <span>{language === 'zh' ? '告警' : 'Alerts'} {Number(device.open_alert_count || 0)}</span>
          <span>{language === 'zh' ? '接口Down' : 'IF Down'} {Number(device.interface_down_count || 0)}</span>
        </div>
      </div>
      <div>
        <span className="text-[9px] uppercase tracking-wider font-semibold text-black/30 dark:text-white/25 block mb-1">
          {language === 'zh' ? '趋势' : 'Trends'}
        </span>
        <div className="flex items-center gap-2 mb-1">
          <span className="text-[9px] font-semibold text-black/40 dark:text-white/40 w-8">CPU</span>
          <Sparkline data={device.cpu_history || [20, 30, 25, 40, 35, 45, 40]} color="#00bceb" />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[9px] font-semibold text-black/40 dark:text-white/40 w-8">MEM</span>
          <Sparkline data={device.memory_history || [60, 62, 65, 63, 68, 70, 65]} color="#10b981" />
        </div>
        {check && badge && (
          <div className="mt-1.5 flex items-center gap-1.5">
            <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-bold uppercase ${badge.cls}`}>
              {language === 'zh' ? badge.zh : badge.en}
            </span>
            <span className="text-[9px] text-black/30 dark:text-white/25">{formatCheckTime(check.checked_at, language)}</span>
          </div>
        )}
      </div>
    </div>
  );
};

/* ════════════════════════════════════════════════════════
   Main Component
   ════════════════════════════════════════════════════════ */
interface InventoryDevicesTabProps {
  inventoryRows: Device[];
  inventoryTotal: number;
  inventoryPage: number;
  setInventoryPage: (v: number) => void;
  inventoryPageSize: number;
  setInventoryPageSize: (v: number) => void;
  inventorySearch: string;
  setInventorySearch: (v: string) => void;
  inventoryPlatformFilter: string;
  setInventoryPlatformFilter: (v: string) => void;
  inventoryRoleFilter: string;
  setInventoryRoleFilter: (v: string) => void;
  inventoryStatusFilter: string;
  setInventoryStatusFilter: (v: string) => void;
  inventorySortConfig: { key: string; direction: 'asc' | 'desc' } | null;
  inventoryLoading: boolean;
  selectedDeviceIds: string[];
  setSelectedDeviceIds: React.Dispatch<React.SetStateAction<string[]>>;
  handleSort: (key: string) => void;
  handleImport: (e: React.ChangeEvent<HTMLInputElement>) => void;
  handleExport: () => void;
  handleDeleteDevice: (id: string) => void;
  handleDeleteSelected: () => void;
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
  language: string;
  t: (key: string) => string;
}

const InventoryDevicesTab: React.FC<InventoryDevicesTabProps> = ({
  inventoryRows, inventoryTotal, inventoryPage, setInventoryPage,
  inventoryPageSize, setInventoryPageSize,
  inventorySearch, setInventorySearch,
  inventoryPlatformFilter, setInventoryPlatformFilter,
  inventoryRoleFilter, setInventoryRoleFilter,
  inventoryStatusFilter, setInventoryStatusFilter,
  inventorySortConfig, inventoryLoading,
  selectedDeviceIds, setSelectedDeviceIds,
  handleSort, handleImport, handleExport,
  handleDeleteDevice, handleDeleteSelected, handleShowDetails,
  handleTestConnection,
  deviceConnectionChecks, connectionTestingDeviceId,
  setShowAddModal, setShowEditModal, setEditingDevice, setEditForm,
  setSelectedDevice, setActiveTab, language, t,
}) => {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [quickFilter, setQuickFilter] = useState<'all' | 'offline' | 'warning' | 'healthy'>('all');

  const toggleExpand = useCallback((id: string) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }, []);

  const offlineCount = inventoryRows.filter(d => d.status === 'offline').length;
  const warningCount = inventoryRows.filter(d => d.health_status === 'warning' || d.health_status === 'critical').length;
  const healthyCount = inventoryRows.filter(d => d.status === 'online' && (d.health_status === 'healthy' || !d.health_status)).length;

  const displayRows = quickFilter === 'all' ? inventoryRows
    : quickFilter === 'offline' ? inventoryRows.filter(d => d.status === 'offline')
    : quickFilter === 'warning' ? inventoryRows.filter(d => d.health_status === 'warning' || d.health_status === 'critical')
    : inventoryRows.filter(d => d.status === 'online' && (d.health_status === 'healthy' || !d.health_status));

  const allChecked = displayRows.length > 0 && displayRows.every(d => selectedDeviceIds.includes(d.id));
  const someChecked = selectedDeviceIds.length > 0 && !allChecked;

  const handleSelectAll = (checked: boolean) => {
    if (checked) {
      const ids = displayRows.map(d => d.id);
      setSelectedDeviceIds(prev => Array.from(new Set([...prev, ...ids])));
    } else {
      const ids = new Set(displayRows.map(d => d.id));
      setSelectedDeviceIds(prev => prev.filter(id => !ids.has(id)));
    }
  };

  const SortHeader: React.FC<{ col: string; children: React.ReactNode; className?: string }> = ({ col, children, className = '' }) => {
    const active = inventorySortConfig?.key === col;
    return (
      <th
        className={`px-3 py-2.5 text-[10px] font-bold uppercase tracking-wider cursor-pointer select-none transition-colors
          ${active ? 'text-[#00bceb]' : 'text-black/35 dark:text-white/30 hover:text-black/55 dark:hover:text-white/55'} ${className}`}
        onClick={() => handleSort(col)}
      >
        <span className="inline-flex items-center gap-0.5">
          {children}
          {active && (inventorySortConfig?.direction === 'asc'
            ? <ChevronUp size={10} />
            : <ChevronDown size={10} />
          )}
        </span>
      </th>
    );
  };

  return (
    <div className="space-y-4">
      {/* ════ Header ════ */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold tracking-tight">{t('deviceInventory')}</h2>
          <p className="text-xs text-black/40 dark:text-white/40 mt-0.5">{t('manageMonitor')}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <label className="inline-flex items-center gap-1.5 px-3 py-1.5 border border-black/8 dark:border-white/10
            rounded-lg text-xs font-medium text-black/55 dark:text-white/55 hover:bg-black/[.03] dark:hover:bg-white/[.05] transition-all cursor-pointer">
            <Upload size={14} />
            {t('import')}
            <input type="file" className="hidden" onChange={handleImport} accept=".xlsx,.xls,.csv"
              title={language === 'zh' ? '导入设备文件' : 'Import device file'} />
          </label>
          <button onClick={handleExport}
            title={language === 'zh' ? '导出设备清单' : 'Export device inventory'}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 border border-black/8 dark:border-white/10
              rounded-lg text-xs font-medium text-black/55 dark:text-white/55 hover:bg-black/[.03] dark:hover:bg-white/[.05] transition-all">
            <Download size={14} />
            {t('export')}
          </button>
          <button onClick={() => setShowAddModal(true)}
            title={language === 'zh' ? '新增设备' : 'Add device'}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-[#00bceb] text-white rounded-lg text-xs
              font-medium hover:bg-[#0096bd] transition-all shadow-sm shadow-[#00bceb]/20">
            <Plus size={14} />
            {t('addDevice')}
          </button>
        </div>
      </div>

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
            <option value="cisco_nxos">Cisco NX-OS</option>
            <option value="juniper_junos">Juniper Junos</option>
            <option value="arista_eos">Arista EOS</option>
            <option value="fortinet_fortios">Fortinet FortiOS</option>
            <option value="huawei_vrp">Huawei VRP</option>
            <option value="h3c_comware">H3C Comware</option>
            <option value="ruijie_rgos">Ruijie RGOS</option>
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
          <select value={inventoryPageSize} onChange={e => setInventoryPageSize(Number(e.target.value))}
            title={language === 'zh' ? '每页数量' : 'Items per page'}
            className="px-2.5 py-1.5 text-[11px] border border-black/6 dark:border-white/8 rounded-lg bg-transparent
              outline-none text-black/55 dark:text-white/55 focus:border-[#00bceb]/40">
            <option value={10}>10 / {language === 'zh' ? '页' : 'page'}</option>
            <option value={20}>20 / {language === 'zh' ? '页' : 'page'}</option>
            <option value={50}>50 / {language === 'zh' ? '页' : 'page'}</option>
            <option value={100}>100 / {language === 'zh' ? '页' : 'page'}</option>
          </select>
        </div>
      </div>

      {/* ════ Quick Filters + Batch Actions ════ */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-1.5 flex-wrap">
          <QuickTag icon={<Server size={11} />} label={language === 'zh' ? '全部' : 'All'} count={inventoryRows.length}
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
          <QuickTag icon={<CheckCircle2 size={11} />} label={language === 'zh' ? '健康' : 'Healthy'} count={healthyCount}
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
                if (selected.length > 0) { setSelectedDevice(selected[0]); setActiveTab('automation'); }
              }}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-medium
                border border-[#00bceb]/25 bg-[#00bceb]/10 text-[#0096bd] dark:text-[#5dd8f0]
                hover:bg-[#00bceb]/20 transition-all">
              <Shield size={11} />
              {language === 'zh' ? '批量配置' : 'Batch Config'}
            </button>
            <button
              onClick={handleDeleteSelected}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-medium
                border border-red-200 dark:border-red-500/25 bg-red-500/10 text-red-600 dark:text-red-400
                hover:bg-red-500/20 transition-all">
              <Trash2 size={11} />
              {language === 'zh' ? '批量删除' : 'Batch Delete'}
            </button>
          </div>
        )}
      </div>

      {/* ════ Table ════ */}
      <div className="rounded-xl border border-black/5 dark:border-white/8 bg-[var(--card-bg)] overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse min-w-[860px]">
            <thead>
              <tr className="bg-black/[.02] dark:bg-white/[.02] border-b border-black/5 dark:border-white/6">
                <th className="px-3 py-2.5 w-9">
                  <input
                    type="checkbox"
                    title={language === 'zh' ? '选择全部' : 'Select all'}
                    className="rounded border-black/20 dark:border-white/20 text-[#00bceb] focus:ring-[#00bceb] focus:ring-offset-0"
                    checked={allChecked}
                    ref={(el) => { if (el) el.indeterminate = someChecked; }}
                    onChange={e => handleSelectAll(e.target.checked)}
                  />
                </th>
                <th className="px-1 py-2.5 w-6" />
                <SortHeader col="hostname">{language === 'zh' ? '设备' : 'Device'}</SortHeader>
                <SortHeader col="platform">{language === 'zh' ? '系统' : 'System'}</SortHeader>
                <SortHeader col="site">{language === 'zh' ? '位置' : 'Location'}</SortHeader>
                <SortHeader col="status">{language === 'zh' ? '状态' : 'Status'}</SortHeader>
                <th className="px-3 py-2.5 text-[10px] font-bold uppercase tracking-wider text-black/35 dark:text-white/30">
                  CPU / MEM
                </th>
                <th className="px-3 py-2.5 text-[10px] font-bold uppercase tracking-wider text-black/35 dark:text-white/30 text-right pr-4">
                  {language === 'zh' ? '操作' : 'Actions'}
                </th>
              </tr>
            </thead>
            <tbody>
              {displayRows.map(device => {
                const status = STATUS_CFG[device.status] || STATUS_CFG.pending;
                const health = HEALTH_CFG[device.health_status || 'unknown'] || HEALTH_CFG.unknown;
                const selected = selectedDeviceIds.includes(device.id);
                const expanded = expandedIds.has(device.id);
                const testing = connectionTestingDeviceId === device.id;
                const cpu = clampPercent(device.cpu_usage);
                const mem = clampPercent(device.memory_usage);

                return (
                  <React.Fragment key={device.id}>
                    <tr className={`border-b border-black/[.04] dark:border-white/[.04] transition-colors
                      hover:bg-black/[.02] dark:hover:bg-white/[.025] group
                      ${selected ? 'bg-[#00bceb]/[.04] dark:bg-[#00bceb]/[.06]' : ''}
                      ${expanded ? 'bg-black/[.015] dark:bg-white/[.02]' : ''}`}>
                      <td className="px-3 py-2">
                        <input
                          type="checkbox"
                          title={`Select ${device.hostname || device.ip_address}`}
                          className="rounded border-black/20 dark:border-white/20 text-[#00bceb] focus:ring-[#00bceb] focus:ring-offset-0"
                          checked={selected}
                          onChange={e => {
                            if (e.target.checked) setSelectedDeviceIds(prev => [...prev, device.id]);
                            else setSelectedDeviceIds(prev => prev.filter(id => id !== device.id));
                          }}
                        />
                      </td>
                      <td className="px-1 py-2">
                        <button onClick={() => toggleExpand(device.id)}
                          className="p-0.5 rounded text-black/25 dark:text-white/20 hover:text-black/50 dark:hover:text-white/50 transition-colors"
                          title={language === 'zh' ? '展开详情' : 'Expand details'}>
                          <ChevronRight size={13} className={`transition-transform duration-200 ${expanded ? 'rotate-90' : ''}`} />
                        </button>
                      </td>
                      <td className="px-3 py-2">
                        <button onClick={() => handleShowDetails(device)} className="text-left group/name">
                          <span className="text-[12px] font-semibold text-black/80 dark:text-white/85 group-hover/name:text-[#00bceb] transition-colors">
                            {device.hostname || 'Unknown'}
                          </span>
                          <span className="block text-[10px] font-mono text-black/35 dark:text-white/30 mt-0.5">
                            {device.ip_address || '0.0.0.0'}
                          </span>
                        </button>
                        {device.role && (
                          <span className="inline-block mt-0.5 text-[9px] font-semibold uppercase px-1.5 py-0.5 rounded
                            bg-black/[.04] dark:bg-white/6 text-black/30 dark:text-white/30">
                            {device.role}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <span className="text-[11px] font-medium text-black/65 dark:text-white/65">{vendorOf(device.platform)}</span>
                        <span className="block text-[10px] text-black/35 dark:text-white/30 mt-0.5">{device.platform || 'unknown'}</span>
                        {device.version && <span className="block text-[10px] font-mono text-black/25 dark:text-white/20 mt-0.5 truncate max-w-[120px]" title={device.version}>{device.version}</span>}
                      </td>
                      <td className="px-3 py-2">
                        <span className="text-[11px] text-black/55 dark:text-white/55">{device.site || 'N/A'}</span>
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-1.5 mb-1">
                          <span className="relative flex h-[7px] w-[7px]">
                            {status.ping && <span className={`animate-ping absolute inline-flex h-full w-full rounded-full ${status.dot} opacity-60`} />}
                            <span className={`relative inline-flex rounded-full h-[7px] w-[7px] ${status.dot}`} />
                          </span>
                          <span className={`text-[10px] font-bold uppercase ${status.text}`}>
                            {language === 'zh' ? status.labelZh : status.labelEn}
                          </span>
                        </div>
                        <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-bold uppercase ${health.bg} ${health.text}`}>
                          {language === 'zh' ? health.labelZh : health.labelEn}
                        </span>
                        {device.uptime && (
                          <span className="block text-[9px] text-black/25 dark:text-white/20 mt-1 font-mono" title={device.uptime}>
                            ⏱ {device.uptime.length > 20 ? device.uptime.slice(0, 20) + '…' : device.uptime}
                          </span>
                        )}
                        {deviceConnectionChecks[device.id] && (() => {
                          const chk = deviceConnectionChecks[device.id];
                          const badge = CHECK_BADGE[chk.status] || CHECK_BADGE.fail;
                          return (
                            <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[8px] font-bold mt-1 ${badge.cls}`}
                              title={chk.checked_at ? formatCheckTime(chk.checked_at, language) : ''}>
                              {language === 'zh' ? badge.zh : badge.en}
                            </span>
                          );
                        })()}
                      </td>
                      <td className="px-3 py-2">
                        {cpu === 0 && mem === 0 ? (
                          <span className="text-[10px] text-black/20 dark:text-white/15 italic">{language === 'zh' ? '未采集' : 'N/A'}</span>
                        ) : (
                          <div className="space-y-1">
                            <MiniBar value={cpu} color="#00bceb" label="CPU" />
                            <MiniBar value={mem} color="#10b981" label="MEM" />
                          </div>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            onClick={() => { setSelectedDevice(device); setActiveTab('automation'); }}
                            title={language === 'zh' ? '管理 / 配置' : 'Manage / Config'}
                            className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-semibold
                              bg-[#00bceb]/10 text-[#0096bd] dark:text-[#5dd8f0] hover:bg-[#00bceb]/20 transition-all">
                            <Wifi size={11} />
                            {language === 'zh' ? '管理' : 'Manage'}
                          </button>
                          <button
                            onClick={() => handleTestConnection(device, 'quick')}
                            title={language === 'zh' ? '连通性检测' : 'Check connectivity'}
                            className={`inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-semibold transition-all
                              ${testing ? 'bg-blue-500/10 text-blue-600 dark:text-blue-400' : 'bg-violet-500/10 text-violet-600 dark:text-violet-400 hover:bg-violet-500/20'}`}>
                            <Activity size={11} className={testing ? 'animate-pulse' : ''} />
                            {testing ? (language === 'zh' ? '检测中' : 'Checking') : (language === 'zh' ? '检查' : 'Check')}
                          </button>
                          <ActionDropdown
                            language={language}
                            onDetails={() => handleShowDetails(device)}
                            onEdit={() => {
                              setEditingDevice(device);
                              setEditForm({ ...device, password: '' } as Device);
                              setShowEditModal(true);
                            }}
                            onDelete={() => handleDeleteDevice(device.id)}
                          />
                        </div>
                      </td>
                    </tr>
                    {expanded && (
                      <tr>
                        <td colSpan={8} className="p-0">
                          <ExpandedPanel device={device} language={language} deviceConnectionChecks={deviceConnectionChecks} />
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
              {!inventoryLoading && displayRows.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-6 py-12 text-center">
                    <WifiOff size={28} className="mx-auto mb-2 text-black/15 dark:text-white/15" />
                    <p className="text-sm text-black/35 dark:text-white/30">
                      {language === 'zh' ? '没有匹配的设备' : 'No devices found for current filters.'}
                    </p>
                  </td>
                </tr>
              )}
              {inventoryLoading && displayRows.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-6 py-12 text-center">
                    <div className="inline-block w-5 h-5 border-2 border-[#00bceb]/30 border-t-[#00bceb] rounded-full animate-spin mb-2" />
                    <p className="text-sm text-black/35 dark:text-white/30">
                      {language === 'zh' ? '加载中…' : 'Loading devices...'}
                    </p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
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
  );
};

export default InventoryDevicesTab;
