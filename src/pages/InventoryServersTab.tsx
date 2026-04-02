import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Search, Plus, Download, Upload, Trash2, Pencil,
  Server, ChevronDown, ChevronUp, ChevronRight,
  CheckCircle2, XCircle, AlertTriangle, Wrench, X,
} from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import Pagination from '../components/Pagination';

/* ═══════════════════════════════════════════════════════
   Types
   ═══════════════════════════════════════════════════════ */

interface ServerAsset {
  id: string; asset_type: string; asset_tag: string; serial_number: string;
  vendor: string; model: string; hostname: string; datacenter: string;
  rack: string; rack_unit: string; management_ip: string; business_ip: string;
  device_role: string; vlan: string; uplink_switch: string; uplink_port: string;
  status: string; purchase_date: string;
  warranty_expiry: string; department: string; notes: string;
  created_at: string; updated_at: string;
}

interface Props {
  language: string;
  t: (key: string) => string;
}

/* ═══════════════════════════════════════════════════════
   Constants
   ═══════════════════════════════════════════════════════ */

const STATUSES = [
  { value: 'active',         zh: '在线',   en: 'Online',      dot: 'bg-emerald-500', badge: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20' },
  { value: 'inactive',       zh: '离线',   en: 'Offline',     dot: 'bg-red-400',     badge: 'bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/20' },
  { value: 'maintenance',    zh: '维护中', en: 'Maintenance', dot: 'bg-amber-500',   badge: 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20' },
  { value: 'decommissioned', zh: '已退役', en: 'Retired',     dot: 'bg-slate-400',   badge: 'bg-slate-500/10 text-slate-500 dark:text-slate-400 border-slate-500/20' },
] as const;

const PAGE_SIZE = 25;

const statusMeta = (v: string) => STATUSES.find(s => s.value === v) || STATUSES[3];

/* ═══════════════════════════════════════════════════════
   SortHeader
   ═══════════════════════════════════════════════════════ */

const SortHeader: React.FC<{
  col: string;
  sortConfig: { key: string; direction: 'asc' | 'desc' } | null;
  onSort: (key: string) => void;
  children: React.ReactNode;
  className?: string;
}> = ({ col, sortConfig, onSort, children, className = '' }) => {
  const active = sortConfig?.key === col;
  return (
    <th
      className={`px-3 py-2.5 text-[10px] font-bold uppercase tracking-wider cursor-pointer select-none transition-colors
        ${active ? 'text-[#00bceb]' : 'text-black/35 dark:text-white/30 hover:text-black/55 dark:hover:text-white/55'} ${className}`}
      onClick={() => onSort(col)}
    >
      <span className="inline-flex items-center gap-0.5">
        {children}
        {active && (sortConfig?.direction === 'asc'
          ? <ChevronUp size={10} />
          : <ChevronDown size={10} />
        )}
      </span>
    </th>
  );
};

/* ═══════════════════════════════════════════════════════
   QuickTag
   ═══════════════════════════════════════════════════════ */

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

/* ═══════════════════════════════════════════════════════
   Detail Modal
   ═══════════════════════════════════════════════════════ */

const ReadonlyField: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div>
    <label className="block text-[10px] font-semibold uppercase tracking-wider text-black/35 dark:text-white/30 mb-1">{label}</label>
    <div className="px-3 py-2 text-xs text-black/70 dark:text-white/70 bg-black/[.02] dark:bg-white/[.03]
      border border-black/6 dark:border-white/8 rounded-lg min-h-[36px] flex items-center">
      {value || '—'}
    </div>
  </div>
);

const DetailModal: React.FC<{
  server: ServerAsset; language: string; onClose: () => void;
}> = ({ server, language, onClose }) => {
  const zh = language === 'zh';
  const st = statusMeta(server.status);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <motion.div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      onClick={onClose}
    >
      <motion.div
        className="bg-white dark:bg-[#0d1526] rounded-2xl shadow-2xl border border-black/8 dark:border-white/10
          w-full max-w-2xl max-h-[85vh] overflow-y-auto mx-4"
        initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }}
        transition={{ duration: 0.18 }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-black/6 dark:border-white/8">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-[#00bceb]/10 flex items-center justify-center">
              <Server size={18} className="text-[#00bceb]" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-black/85 dark:text-white/90">{server.hostname || server.management_ip || 'Unknown'}</h3>
              <div className="flex items-center gap-1.5 mt-0.5">
                <span className={`w-1.5 h-1.5 rounded-full ${st.dot}`} />
                <span className="text-[10px] text-black/45 dark:text-white/40">{zh ? st.zh : st.en}</span>
              </div>
            </div>
          </div>
          <button onClick={onClose} title="Close" className="p-1.5 rounded-lg hover:bg-black/5 dark:hover:bg-white/8 transition-colors">
            <X size={16} className="text-black/40 dark:text-white/40" />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 grid grid-cols-2 gap-x-6 gap-y-4">
          <ReadonlyField label={zh ? '主机名' : 'Hostname'} value={server.hostname} />
          <ReadonlyField label={zh ? '管理 IP' : 'Management IP'} value={server.management_ip} />
          <ReadonlyField label={zh ? '业务 IP' : 'Business IP'} value={server.business_ip} />
          <ReadonlyField label={zh ? '资产编号' : 'Asset Tag'} value={server.asset_tag} />
          <ReadonlyField label={zh ? '序列号' : 'Serial Number'} value={server.serial_number} />
          <ReadonlyField label={zh ? '厂商' : 'Vendor'} value={server.vendor} />
          <ReadonlyField label={zh ? '型号' : 'Model'} value={server.model} />
          <ReadonlyField label={zh ? '状态' : 'Status'} value={zh ? st.zh : st.en} />
          <ReadonlyField label={zh ? '数据中心' : 'Datacenter'} value={server.datacenter} />
          <ReadonlyField label={zh ? '机柜 / U位' : 'Rack / U'} value={[server.rack, server.rack_unit].filter(Boolean).join(' / ') || '—'} />
          <ReadonlyField label={zh ? '角色' : 'Role'} value={server.device_role} />
          <ReadonlyField label={zh ? '部门' : 'Department'} value={server.department} />
          <ReadonlyField label="VLAN" value={server.vlan} />
          <ReadonlyField label={zh ? '上联交换机' : 'Uplink Switch'} value={server.uplink_switch} />
          <ReadonlyField label={zh ? '上联端口' : 'Uplink Port'} value={server.uplink_port} />
          <ReadonlyField label={zh ? '采购日期' : 'Purchase Date'} value={server.purchase_date} />
          <ReadonlyField label={zh ? '保修到期' : 'Warranty Expiry'} value={server.warranty_expiry} />
          <ReadonlyField label={zh ? '备注' : 'Notes'} value={server.notes} />
        </div>
      </motion.div>
    </motion.div>
  );
};

/* ═══════════════════════════════════════════════════════
   Main Component
   ═══════════════════════════════════════════════════════ */

const InventoryServersTab: React.FC<Props> = ({ language, t }) => {
  const zh = language === 'zh';

  /* ─── State ─── */
  const [servers, setServers]           = useState<ServerAsset[]>([]);
  const [total, setTotal]               = useState(0);
  const [page, setPage]                 = useState(1);
  const [pageSize, setPageSize]         = useState(PAGE_SIZE);
  const [loading, setLoading]           = useState(true);
  const [search, setSearch]             = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [vendorFilter, setVendorFilter] = useState('');
  const [dcFilter, setDcFilter]         = useState('');
  const [sortConfig, setSortConfig]     = useState<{ key: string; direction: 'asc' | 'desc' } | null>(null);
  const [selectedIds, setSelectedIds]   = useState<Set<string>>(new Set());
  const [quickFilter, setQuickFilter]   = useState<'all' | 'offline' | 'warning' | 'healthy'>('all');
  const [detailServer, setDetailServer] = useState<ServerAsset | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ServerAsset | null>(null);
  const [deleting, setDeleting]         = useState(false);

  /* ─── Data Fetching ─── */
  const fetchServers = useCallback(async () => {
    setLoading(true);
    try {
      const p = new URLSearchParams({
        asset_type: 'server',
        status: statusFilter,
        vendor: vendorFilter,
        datacenter: dcFilter,
        q: search,
        page: page.toString(),
        page_size: pageSize.toString(),
      });
      const r = await fetch(`/api/assets?${p}`);
      if (r.ok) {
        const data = await r.json();
        setServers(data.items || []);
        setTotal(data.total || 0);
      }
    } catch { /* noop */ }
    setLoading(false);
  }, [page, pageSize, search, statusFilter, vendorFilter, dcFilter]);

  useEffect(() => { fetchServers(); }, [fetchServers]);

  /* ─── Sorting (client-side on current page) ─── */
  const handleSort = useCallback((key: string) => {
    setSortConfig(prev => {
      if (prev?.key === key) return { key, direction: prev.direction === 'asc' ? 'desc' : 'asc' };
      return { key, direction: 'asc' };
    });
  }, []);

  const sortedServers = useMemo(() => {
    if (!sortConfig) return servers;
    const { key, direction } = sortConfig;
    return [...servers].sort((a, b) => {
      const av = (a as Record<string, unknown>)[key] ?? '';
      const bv = (b as Record<string, unknown>)[key] ?? '';
      const cmp = String(av).localeCompare(String(bv));
      return direction === 'asc' ? cmp : -cmp;
    });
  }, [servers, sortConfig]);

  /* ─── Quick filter ─── */
  const counts = useMemo(() => {
    const active = servers.filter(s => s.status === 'active').length;
    const inactive = servers.filter(s => s.status === 'inactive').length;
    const maint = servers.filter(s => s.status === 'maintenance').length;
    return { all: servers.length, healthy: active, offline: inactive, warning: maint };
  }, [servers]);

  const displayRows = useMemo(() => {
    if (quickFilter === 'all') return sortedServers;
    if (quickFilter === 'offline') return sortedServers.filter(s => s.status === 'inactive');
    if (quickFilter === 'warning') return sortedServers.filter(s => s.status === 'maintenance');
    return sortedServers.filter(s => s.status === 'active');
  }, [sortedServers, quickFilter]);

  /* ─── Actions ─── */
  const handleDelete = async (server: ServerAsset) => {
    setDeleting(true);
    try {
      const r = await fetch(`/api/assets/${server.id}`, { method: 'DELETE' });
      if (r.ok) {
        fetchServers();
        setDeleteTarget(null);
      }
    } catch { /* noop */ }
    setDeleting(false);
  };

  const handleDeleteSelected = async () => {
    for (const id of selectedIds) {
      try {
        await fetch(`/api/assets/${id}`, { method: 'DELETE' });
      } catch { /* noop */ }
    }
    setSelectedIds(new Set());
    fetchServers();
  };

  /* ─── Selection ─── */
  const allChecked = displayRows.length > 0 && displayRows.every(s => selectedIds.has(s.id));
  const someChecked = selectedIds.size > 0 && !allChecked;

  const handleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedIds(new Set(displayRows.map(s => s.id)));
    } else {
      setSelectedIds(new Set());
    }
  };

  /* ─── Unique filter options ─── */
  const vendors = useMemo(() => [...new Set(servers.map(s => s.vendor).filter(Boolean))], [servers]);
  const datacenters = useMemo(() => [...new Set(servers.map(s => s.datacenter).filter(Boolean))], [servers]);

  return (
    <div className="space-y-4">
      {/* ════ Header ════ */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold tracking-tight">{zh ? '服务器管理' : 'Server Management'}</h2>
          <p className="text-xs text-black/40 dark:text-white/40 mt-0.5">{zh ? '管理和查看数据中心服务器资产。' : 'Manage and view datacenter server assets.'}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button onClick={fetchServers}
            title={zh ? '刷新' : 'Refresh'}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 border border-black/8 dark:border-white/10
              rounded-lg text-xs font-medium text-black/55 dark:text-white/55 hover:bg-black/[.03] dark:hover:bg-white/[.05] transition-all">
            <Download size={14} />
            {t('export')}
          </button>
        </div>
      </div>

      {/* ════ Toolbar: Search + Filters ════ */}
      <div className="flex flex-col lg:flex-row gap-3 p-3 rounded-xl border border-black/5 dark:border-white/8 bg-[var(--card-bg)]">
        <div className="relative flex-1 min-w-0">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-black/30 dark:text-white/25 pointer-events-none" size={14} />
          <input
            type="text"
            placeholder={zh ? '搜索 IP / 主机名 / SN …' : 'Search IP / hostname / SN …'}
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1); }}
            className="w-full pl-8 pr-3 py-1.5 text-xs bg-transparent border border-black/6 dark:border-white/8
              rounded-lg outline-none focus:border-[#00bceb]/40 dark:focus:border-[#00bceb]/40
              text-black/80 dark:text-white/80 placeholder:text-black/25 dark:placeholder:text-white/20"
          />
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <select value={statusFilter} onChange={e => { setStatusFilter(e.target.value); setPage(1); }}
            title={zh ? '按状态筛选' : 'Filter by status'}
            className="px-2.5 py-1.5 text-[11px] border border-black/6 dark:border-white/8 rounded-lg bg-transparent
              outline-none text-black/55 dark:text-white/55 focus:border-[#00bceb]/40">
            <option value="all">{zh ? '全部状态' : 'All Status'}</option>
            {STATUSES.map(s => (
              <option key={s.value} value={s.value}>{zh ? s.zh : s.en}</option>
            ))}
          </select>
          {vendors.length > 0 && (
            <select value={vendorFilter} onChange={e => { setVendorFilter(e.target.value); setPage(1); }}
              title={zh ? '按厂商筛选' : 'Filter by vendor'}
              className="px-2.5 py-1.5 text-[11px] border border-black/6 dark:border-white/8 rounded-lg bg-transparent
                outline-none text-black/55 dark:text-white/55 focus:border-[#00bceb]/40">
              <option value="">{zh ? '全部厂商' : 'All Vendors'}</option>
              {vendors.map(v => <option key={v} value={v}>{v}</option>)}
            </select>
          )}
          {datacenters.length > 0 && (
            <select value={dcFilter} onChange={e => { setDcFilter(e.target.value); setPage(1); }}
              title={zh ? '按数据中心筛选' : 'Filter by datacenter'}
              className="px-2.5 py-1.5 text-[11px] border border-black/6 dark:border-white/8 rounded-lg bg-transparent
                outline-none text-black/55 dark:text-white/55 focus:border-[#00bceb]/40">
              <option value="">{zh ? '全部数据中心' : 'All Datacenters'}</option>
              {datacenters.map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          )}
        </div>
      </div>

      {/* ════ Quick Filters + Batch Actions ════ */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-1.5 flex-wrap">
          <QuickTag icon={<Server size={11} />} label={zh ? '全部' : 'All'} count={total}
            active={quickFilter === 'all'}
            tone="bg-[#00bceb]/10 border-[#00bceb]/25 text-[#0096bd] dark:text-[#5dd8f0] dark:border-[#00bceb]/20"
            onClick={() => setQuickFilter('all')} />
          <QuickTag icon={<XCircle size={11} />} label={zh ? '离线' : 'Offline'} count={counts.offline}
            active={quickFilter === 'offline'}
            tone="bg-red-500/10 border-red-500/25 text-red-600 dark:text-red-400 dark:border-red-500/20"
            onClick={() => setQuickFilter(quickFilter === 'offline' ? 'all' : 'offline')} />
          <QuickTag icon={<AlertTriangle size={11} />} label={zh ? '维护中' : 'Maintenance'} count={counts.warning}
            active={quickFilter === 'warning'}
            tone="bg-amber-500/10 border-amber-500/25 text-amber-600 dark:text-amber-400 dark:border-amber-500/20"
            onClick={() => setQuickFilter(quickFilter === 'warning' ? 'all' : 'warning')} />
          <QuickTag icon={<CheckCircle2 size={11} />} label={zh ? '在线' : 'Online'} count={counts.healthy}
            active={quickFilter === 'healthy'}
            tone="bg-emerald-500/10 border-emerald-500/25 text-emerald-600 dark:text-emerald-400 dark:border-emerald-500/20"
            onClick={() => setQuickFilter(quickFilter === 'healthy' ? 'all' : 'healthy')} />
        </div>

        {selectedIds.size > 0 && (
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-medium text-black/45 dark:text-white/40 tabular-nums">
              {selectedIds.size} {zh ? '已选' : 'selected'}
            </span>
            <button onClick={handleDeleteSelected}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-medium
                border border-red-200 dark:border-red-500/25 bg-red-500/10 text-red-600 dark:text-red-400
                hover:bg-red-500/20 transition-all">
              <Trash2 size={11} />
              {zh ? '批量删除' : 'Batch Delete'}
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
                    title={zh ? '选择全部' : 'Select all'}
                    className="rounded border-black/20 dark:border-white/20 text-[#00bceb] focus:ring-[#00bceb] focus:ring-offset-0"
                    checked={allChecked}
                    ref={(el) => { if (el) el.indeterminate = someChecked; }}
                    onChange={e => handleSelectAll(e.target.checked)}
                  />
                </th>
                <SortHeader col="hostname" sortConfig={sortConfig} onSort={handleSort}>
                  {zh ? '服务器' : 'Server'}
                </SortHeader>
                <SortHeader col="vendor" sortConfig={sortConfig} onSort={handleSort}>
                  {zh ? '厂商 / 型号' : 'Vendor / Model'}
                </SortHeader>
                <SortHeader col="datacenter" sortConfig={sortConfig} onSort={handleSort}>
                  {zh ? '数据中心' : 'Datacenter'}
                </SortHeader>
                <SortHeader col="status" sortConfig={sortConfig} onSort={handleSort}>
                  {zh ? '状态' : 'Status'}
                </SortHeader>
                <th className="px-3 py-2.5 text-[10px] font-bold uppercase tracking-wider text-black/35 dark:text-white/30">
                  {zh ? '部门' : 'Dept'}
                </th>
                <th className="px-3 py-2.5 text-[10px] font-bold uppercase tracking-wider text-black/35 dark:text-white/30 text-right pr-4">
                  {zh ? '操作' : 'Actions'}
                </th>
              </tr>
            </thead>
            <tbody>
              {displayRows.map(server => {
                const selected = selectedIds.has(server.id);
                const st = statusMeta(server.status);

                return (
                  <tr
                    key={server.id}
                    onClick={() => setDetailServer(server)}
                    className={`border-b border-black/[.04] dark:border-white/[.04] transition-colors cursor-pointer
                      hover:bg-black/[.02] dark:hover:bg-white/[.025] group
                      ${selected ? 'bg-[#00bceb]/[.04] dark:bg-[#00bceb]/[.06]' : ''}`}
                  >
                    {/* Checkbox */}
                    <td className="px-3 py-2" onClick={e => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        title={`Select ${server.hostname || server.management_ip}`}
                        className="rounded border-black/20 dark:border-white/20 text-[#00bceb] focus:ring-[#00bceb] focus:ring-offset-0"
                        checked={selected}
                        onChange={e => {
                          setSelectedIds(prev => {
                            const next = new Set(prev);
                            if (e.target.checked) next.add(server.id); else next.delete(server.id);
                            return next;
                          });
                        }}
                      />
                    </td>
                    {/* Hostname + IP */}
                    <td className="px-3 py-2">
                      <div className="text-left">
                        <span className="text-[12px] font-semibold text-black/80 dark:text-white/85 group-hover:text-[#00bceb] transition-colors">
                          {server.hostname || 'Unknown'}
                        </span>
                        <span className="block text-[10px] font-mono text-black/35 dark:text-white/30 mt-0.5">
                          {server.management_ip || '0.0.0.0'}
                        </span>
                      </div>
                      {server.device_role && (
                        <span className="inline-block mt-0.5 text-[9px] font-semibold uppercase px-1.5 py-0.5 rounded
                          bg-black/[.04] dark:bg-white/6 text-black/30 dark:text-white/30">
                          {server.device_role}
                        </span>
                      )}
                    </td>
                    {/* Vendor / Model */}
                    <td className="px-3 py-2">
                      <span className="text-[11px] font-medium text-black/65 dark:text-white/65">{server.vendor || '—'}</span>
                      <span className="block text-[10px] text-black/35 dark:text-white/30 mt-0.5">{server.model || '—'}</span>
                    </td>
                    {/* Datacenter */}
                    <td className="px-3 py-2">
                      <span className="text-[11px] text-black/55 dark:text-white/55">{server.datacenter || '—'}</span>
                      {server.rack && (
                        <span className="block text-[10px] text-black/30 dark:text-white/25 mt-0.5">
                          {server.rack}{server.rack_unit ? ` / U${server.rack_unit}` : ''}
                        </span>
                      )}
                    </td>
                    {/* Status */}
                    <td className="px-3 py-2">
                      <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold border ${st.badge}`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${st.dot}`} />
                        {zh ? st.zh : st.en}
                      </span>
                    </td>
                    {/* Department */}
                    <td className="px-3 py-2">
                      <span className="text-[11px] text-black/55 dark:text-white/55">{server.department || '—'}</span>
                    </td>
                    {/* Actions */}
                    <td className="px-3 py-2" onClick={e => e.stopPropagation()}>
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => setDeleteTarget(server)}
                          title={zh ? '删除' : 'Delete'}
                          className="inline-flex items-center justify-center w-7 h-7 rounded-md
                            text-black/30 dark:text-white/25 hover:bg-red-500/10
                            hover:text-red-500 dark:hover:text-red-400 transition-all">
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}

              {/* Empty state */}
              {!loading && displayRows.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-6 py-12 text-center">
                    <Server size={28} className="mx-auto mb-2 text-black/15 dark:text-white/15" />
                    <p className="text-sm text-black/35 dark:text-white/30">
                      {zh ? '没有匹配的服务器' : 'No servers found for current filters.'}
                    </p>
                  </td>
                </tr>
              )}

              {/* Loading state */}
              {loading && displayRows.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-6 py-12 text-center">
                    <div className="inline-block w-5 h-5 border-2 border-[#00bceb]/30 border-t-[#00bceb] rounded-full animate-spin mb-2" />
                    <p className="text-sm text-black/35 dark:text-white/30">
                      {zh ? '加载中…' : 'Loading servers...'}
                    </p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <Pagination
          currentPage={page}
          totalItems={total}
          itemsPerPage={pageSize}
          onItemsPerPageChange={setPageSize}
          onPageChange={setPage}
          language={language}
        />
      </div>

      {/* ════ Detail Modal ════ */}
      <AnimatePresence>
        {detailServer && (
          <DetailModal server={detailServer} language={language} onClose={() => setDetailServer(null)} />
        )}
      </AnimatePresence>

      {/* ════ Delete Confirmation ════ */}
      <AnimatePresence>
        {deleteTarget && (
          <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onClick={() => setDeleteTarget(null)}
          >
            <motion.div
              className="bg-white dark:bg-[#0d1526] rounded-2xl shadow-2xl border border-black/8 dark:border-white/10
                w-full max-w-sm mx-4 p-6"
              initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }}
              transition={{ duration: 0.15 }}
              onClick={e => e.stopPropagation()}
            >
              <div className="flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-full bg-red-500/10 flex items-center justify-center">
                  <AlertTriangle size={20} className="text-red-500" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-black/85 dark:text-white/90">
                    {zh ? '确认删除' : 'Confirm Delete'}
                  </h3>
                  <p className="text-xs text-black/50 dark:text-white/45 mt-0.5">
                    {zh ? '此操作不可撤销' : 'This action cannot be undone'}
                  </p>
                </div>
              </div>
              <p className="text-xs text-black/60 dark:text-white/55 mb-5">
                {zh ? '确定要删除服务器 ' : 'Are you sure you want to delete server '}
                <span className="font-semibold">{deleteTarget.hostname || deleteTarget.management_ip}</span>
                {zh ? ' 吗？' : '?'}
              </p>
              <div className="flex justify-end gap-2">
                <button onClick={() => setDeleteTarget(null)}
                  className="px-4 py-1.5 text-xs font-medium rounded-lg border border-black/8 dark:border-white/10
                    text-black/60 dark:text-white/55 hover:bg-black/5 dark:hover:bg-white/8 transition-all">
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button onClick={() => handleDelete(deleteTarget)} disabled={deleting}
                  className="px-4 py-1.5 text-xs font-medium rounded-lg bg-red-500 text-white hover:bg-red-600
                    disabled:opacity-50 transition-all">
                  {deleting ? (zh ? '删除中…' : 'Deleting…') : (zh ? '确认删除' : 'Delete')}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default InventoryServersTab;
