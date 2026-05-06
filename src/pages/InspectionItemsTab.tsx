import React, { useEffect, useState, useCallback, useMemo } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  Activity, Plus, X, Trash2, Edit3, Save, RotateCcw,
  Shield, CheckCircle2, Search, Filter, Info, ListFilter, Copy, Check, Download, Database, FileCode
} from 'lucide-react';
import Pagination from '../components/Pagination';
import {
  alertPanelClass,
  alertSecondaryButtonClass,
  alertTableActionButtonClass,
} from './alertManagementShared';

interface InspectionItem {
  id: string;
  name: string;
  name_zh: string;
  category: string;
  check_key: string;
  description: string;
  method: string;
  command: string;
  vendor: string;
  oid: string;
  created_at: string;
  updated_at: string;
  script_id: string;
  warning_threshold?: number | null;
  critical_threshold?: number | null;
}


const VENDORS = ['Generic', 'Cisco', 'Huawei', 'H3C', 'Juniper', 'Arista', 'Linux', 'Windows', 'VMware', 'Dell', 'HP', 'F5', 'PaloAlto', 'Fortinet', 'Checkpoint'];
const CATEGORIES = [
  { id: 'Network', en: 'Network Device', zh: '网络设备' },
  { id: 'Server', en: 'Server / Host', zh: '服务器/主机' },
  { id: 'Connectivity', en: 'Connectivity', zh: '基础连通性' },
  { id: 'Interface', en: 'Interface', zh: '接口统计' },
  { id: 'Health', en: 'Health', zh: '业务健康度' },
  { id: 'Compliance', en: 'Compliance', zh: '合规性检查' }
];

interface InspectionItemsTabProps {
  t: (key: string) => string;
  language: string;
  showToast: (msg: string, type?: 'success' | 'error' | 'info') => void;
}

const InspectionItemsTab: React.FC<InspectionItemsTabProps> = ({ language, showToast }) => {
  const zh = language === 'zh';

  const [items, setItems] = useState<InspectionItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  
  const [form, setForm] = useState({
    name: '', name_zh: '', category: 'Network', check_key: '', description: '',
    method: 'SNMP', command: '', vendor: '', oid: ''
  });

  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [categoryFilter, setCategoryFilter] = useState<string>('All');
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [scripts, setScripts] = useState<any[]>([]);

  const copyToClipboard = (text: string, id: string) => {
    try {
      // Primary method
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text);
      } else {
        // Fallback for non-HTTPS/older browsers
        const textArea = document.createElement("textarea");
        textArea.value = text;
        textArea.style.position = "fixed";
        textArea.style.left = "-9999px";
        textArea.style.top = "0";
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
      }
      
      setCopiedId(id);
      setTimeout(() => setCopiedId(null), 2000);
      showToast(zh ? '已成功复制到剪贴板' : 'Copied to clipboard successfully', 'success');
    } catch (err) {
      console.error('Failed to copy: ', err);
      showToast(zh ? '复制失败' : 'Failed to copy', 'error');
    }
  };


  const authHeaders = useMemo(() => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' };
  }, []);

  const fetchItems = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch('/api/inspections/items/all', { headers: authHeaders });
      if (r.ok) {
        const j = await r.json();
        setItems(j.data || []);
      }
    } finally {
      setLoading(false);
    }
  }, [authHeaders]);

  const fetchScripts = useCallback(async () => {
    try {
      const r = await fetch('/api/scripts', { headers: authHeaders });
      if (r.ok) {
        const j = await r.json();
        setScripts(j || []);
      }
    } catch { /* ignore */ }
  }, [authHeaders]);

  useEffect(() => { 
    fetchItems();
    fetchScripts();
  }, [fetchItems, fetchScripts]);

  const handleAdd = async () => {
    if (!form.name || !form.name_zh || !form.check_key) {
      showToast(zh ? '请填写完整信息' : 'Please fill all fields', 'error');
      return;
    }
    try {
      const r = await fetch('/api/inspections/items', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify(form)
      });
      if (r.ok) {
        showToast(zh ? '指标创建成功' : 'Item created', 'success');
        setShowAdd(false);
        setForm({ 
          name: '', name_zh: '', category: 'Network', check_key: '', 
          description: '', method: 'SNMP', command: '', vendor: '', oid: '' 
        });
        fetchItems();
      }
    } catch {
      showToast(zh ? '创建失败' : 'Failed to create', 'error');
    }
  };

  const handleUpdate = async (id: string, updates: Partial<InspectionItem>) => {
    try {
      const r = await fetch(`/api/inspections/items/${id}`, {
        method: 'PUT',
        headers: authHeaders,
        body: JSON.stringify(updates)
      });
      if (r.ok) {
        showToast(zh ? '更新成功' : 'Updated', 'success');
        setEditingId(null);
        fetchItems();
      }
    } catch {
      showToast(zh ? '更新失败' : 'Failed to update', 'error');
    }
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm(zh ? '确认删除该指标吗？' : 'Confirm delete?')) return;
    try {
      const r = await fetch(`/api/inspections/items/${id}`, {
        method: 'DELETE',
        headers: authHeaders
      });
      if (r.ok) {
        showToast(zh ? '指标已删除' : 'Deleted', 'success');
        fetchItems();
      }
    } catch {
      showToast(zh ? '删除失败' : 'Failed to delete', 'error');
    }
  };

  const handleExport = () => {
    try {
      if (items.length === 0) {
        showToast(zh ? '没有可导出的数据' : 'No data to export', 'error');
        return;
      }
      
      const headers = [
        zh ? '名称' : 'Name',
        zh ? '中文名称' : 'Name (ZH)',
        zh ? '分类' : 'Category',
        zh ? '检查Key' : 'Check Key',
        zh ? '方式' : 'Method',
        zh ? '厂商' : 'Vendor',
        zh ? 'OID' : 'OID',
        zh ? '指令' : 'Command',
        zh ? '创建时间' : 'Created At'
      ];
      
      const rows = items.map(i => [
        i.name,
        i.name_zh,
        i.category,
        i.check_key,
        i.method,
        i.vendor,
        i.oid,
        `"${(i.command || '').replace(/"/g, '""')}"`,
        i.created_at
      ]);
      
      const csvContent = "\ufeff" + [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
      const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
      const link = document.createElement("a");
      const url = URL.createObjectURL(blob);
      link.setAttribute("href", url);
      link.setAttribute("download", `inspection_metrics_${new Date().toISOString().slice(0, 10)}.csv`);
      link.style.visibility = 'hidden';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      showToast(zh ? '导出成功' : 'Export success', 'success');
    } catch (err) {
      console.error('Export failed:', err);
      showToast(zh ? '导出失败' : 'Export failed', 'error');
    }
  };

  const filteredItems = useMemo(() => {
    let result = items;
    
    // Category Filter
    if (categoryFilter !== 'All') {
      result = result.filter(i => i.category === categoryFilter);
    }

    // Search Query
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      result = result.filter(i => 
        (i.name || '').toLowerCase().includes(q) || 
        (i.name_zh || '').toLowerCase().includes(q) || 
        (i.category || '').toLowerCase().includes(q) ||
        (i.check_key || '').toLowerCase().includes(q)
      );
    }
    return result;
  }, [items, searchQuery, categoryFilter]);

  const paginatedItems = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredItems.slice(start, start + pageSize);
  }, [filteredItems, currentPage, pageSize]);

  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, categoryFilter]);

  const groupedItems = useMemo(() => {
    const groups: Record<string, Record<string, InspectionItem[]>> = {};
    paginatedItems.forEach(item => {
      const cat = item.category || 'Other';
      const ven = item.vendor || (zh ? '未分类' : 'Uncategorized');
      if (!groups[cat]) groups[cat] = {};
      if (!groups[cat][ven]) groups[cat][ven] = [];
      groups[cat][ven].push(item);
    });
    return groups;
  }, [paginatedItems, zh]);

  return (
    <div className="flex-1 flex flex-col overflow-hidden space-y-4 min-h-0">
      <div className={`${alertPanelClass} flex-1 min-h-0 flex flex-col overflow-hidden`}>
        {/* Header */}
        <div className="flex flex-col gap-4 border-b border-black/5 px-5 py-5 lg:flex-row lg:items-end lg:justify-between bg-[linear-gradient(to_right,#f4fbfc_0%,#ffffff_100%)] rounded-t-[28px]">
          <div className="flex-1">
            <div className="flex items-center gap-2 overflow-x-auto pb-1 no-scrollbar mb-4">
            <div className="flex items-center gap-2 overflow-x-auto pb-2 no-scrollbar mb-4">
              <button
                onClick={() => setCategoryFilter('All')}
                className={`px-4 py-2 rounded-2xl text-[11px] font-black tracking-widest uppercase transition-all whitespace-nowrap shadow-sm border ${
                  categoryFilter === 'All' 
                  ? 'bg-gradient-to-br from-[#164e63] to-[#0e3f52] text-white border-[#164e63] shadow-lg shadow-cyan-900/20 scale-[1.02]' 
                  : 'bg-white text-slate-400 border-slate-100 hover:border-slate-200 hover:text-slate-600'
                }`}
              >
                {zh ? '全部指标' : 'All Metrics'}
                <span className={`ml-2 px-1.5 py-0.5 rounded-lg text-[9px] ${categoryFilter === 'All' ? 'bg-white/20 text-white' : 'bg-slate-100 text-slate-400'}`}>
                  {items.length}
                </span>
              </button>
              {CATEGORIES.map(cat => {
                const count = items.filter(i => i.category === cat.id).length;
                const isActive = categoryFilter === cat.id;
                return (
                  <button
                    key={cat.id}
                    onClick={() => setCategoryFilter(cat.id)}
                    className={`px-4 py-2 rounded-2xl text-[11px] font-black tracking-widest uppercase transition-all whitespace-nowrap shadow-sm border ${
                      isActive 
                      ? 'bg-gradient-to-br from-cyan-600 to-cyan-700 text-white border-cyan-500 shadow-lg shadow-cyan-600/20 scale-[1.02]' 
                      : 'bg-white text-slate-400 border-slate-100 hover:border-slate-200 hover:text-slate-600'
                    }`}
                  >
                    {zh ? cat.zh : cat.en}
                    <span className={`ml-2 px-1.5 py-0.5 rounded-lg text-[9px] ${isActive ? 'bg-white/20 text-white' : 'bg-slate-100 text-slate-400'}`}>
                      {count}
                    </span>
                  </button>
                );
              })}
            </div>
            </div>

            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-2xl bg-cyan-500/10 flex items-center justify-center">
                <ListFilter className="w-5 h-5 text-cyan-600" />
              </div>
              <div>
                <h2 className="text-xl font-bold text-[#164e63]">
                  {zh ? '巡检指标项管理' : 'Inspection Items Management'}
                </h2>
                <p className="text-[10px] text-black/35 font-bold uppercase tracking-widest mt-0.5">
                  {zh ? '定义与维护自动化巡检的核心监控指标' : 'Define and manage core metrics for automated inspection'}
                </p>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="relative group">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-black/20 group-focus-within:text-cyan-500 transition-colors" />
              <input
                type="text"
                placeholder={zh ? '搜索指标...' : 'Search items...'}
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                className="pl-9 pr-4 py-2 rounded-xl border border-black/[0.08] bg-white text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all w-48 lg:w-64 shadow-sm"
              />
            </div>
            <button
              onClick={handleExport}
              title={zh ? '导出所有指标' : 'Export all items'}
              className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-white border border-black/10 text-black/60 text-sm font-bold shadow-sm hover:bg-black/5 transition-all active:scale-[0.97]"
            >
              <Download className="w-4 h-4" />
              {zh ? '导出' : 'Export'}
            </button>
            <button
              onClick={() => setShowAdd(!showAdd)}
              className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-[#164e63] text-white text-sm font-bold shadow-sm hover:bg-[#0e3f52] transition-all active:scale-[0.97]"
            >
              <Plus className="w-4 h-4" />
              {zh ? '新增指标' : 'Add Item'}
            </button>
          </div>
        </div>

        <AnimatePresence>
          {showAdd && (
            <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden bg-black/5 border-b border-black/5">
              <div className="p-6 space-y-4">
                <div className="flex items-center justify-between">
                  <h4 className="text-sm font-bold text-[#164e63] flex items-center gap-2">
                    <Plus className="w-4 h-4 text-cyan-500" />
                    {zh ? '配置新指标' : 'Configure New Item'}
                  </h4>
                  <button onClick={() => setShowAdd(false)} className="p-1 rounded-lg text-black/30 hover:bg-black/10 transition-all">
                    <X className="w-4 h-4" />
                  </button>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                  <div>
                    <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '英文名称' : 'Name (EN)'}</label>
                    <input
                      type="text" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })}
                      className="w-full px-3.5 py-2 rounded-xl border border-black/[0.08] text-sm focus:outline-none shadow-sm"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '中文名称' : 'Name (ZH)'}</label>
                    <input
                      type="text" value={form.name_zh} onChange={e => setForm({ ...form, name_zh: e.target.value })}
                      className="w-full px-3.5 py-2 rounded-xl border border-black/[0.08] text-sm focus:outline-none shadow-sm"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '分类' : 'Category'}</label>
                    <select
                      value={form.category} onChange={e => setForm({ ...form, category: e.target.value })}
                      className="w-full px-3.5 py-2 rounded-xl border border-black/[0.08] text-sm focus:outline-none bg-white shadow-sm"
                    >
                      <option value="Network">{zh ? '网络设备' : 'Network Device'}</option>
                      <option value="Server">{zh ? '服务器/主机' : 'Server / Host'}</option>
                      <option value="Connectivity">{zh ? '基础连通性' : 'Connectivity'}</option>
                      <option value="Interface">{zh ? '接口统计' : 'Interface'}</option>
                      <option value="Health">{zh ? '业务健康度' : 'Health'}</option>
                      <option value="Compliance">{zh ? '合规性检查' : 'Compliance'}</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '检查 Key' : 'Check Key'}</label>
                    <input
                      type="text" value={form.check_key} onChange={e => setForm({ ...form, check_key: e.target.value })}
                      className="w-full px-3.5 py-2 rounded-xl border border-black/[0.08] text-sm focus:outline-none shadow-sm"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '采集方式' : 'Method'}</label>
                    <select
                      value={form.method} onChange={e => setForm({ ...form, method: e.target.value })}
                      className="w-full px-3.5 py-2 rounded-xl border border-black/[0.08] text-sm focus:outline-none bg-white shadow-sm"
                    >
                      <option value="SNMP">SNMP</option>
                      <option value="SSH">SSH</option>
                      <option value="Shell">Shell</option>
                      <option value="ICMP">ICMP</option>
                      <option value="TCP">TCP</option>
                      <option value="Agent">Agent</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '厂商' : 'Vendor'}</label>
                    <select
                      value={form.vendor} onChange={e => setForm({ ...form, vendor: e.target.value })}
                      className="w-full px-3.5 py-2 rounded-xl border border-black/[0.08] text-sm focus:outline-none bg-white shadow-sm"
                    >
                      <option value="">{zh ? '请选择厂商' : 'Select Vendor'}</option>
                      {VENDORS.map(v => <option key={v} value={v}>{v}</option>)}
                    </select>
                  </div>
                  {form.method === 'SNMP' && (
                    <div>
                      <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? 'OID' : 'OID'}</label>
                      <input
                        type="text" value={form.oid} onChange={e => setForm({ ...form, oid: e.target.value })}
                        className="w-full px-3.5 py-2 rounded-xl border border-black/[0.08] text-sm focus:outline-none shadow-sm"
                        placeholder={zh ? "请输入 OID" : "1.3.6.1..."}
                      />
                    </div>
                  )}
                  <div className="lg:col-span-2">
                    <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '采集指令' : 'Command'}</label>
                    <input
                      type="text" value={form.command} onChange={e => setForm({ ...form, command: e.target.value })}
                      className="w-full px-3.5 py-2 rounded-xl border border-black/[0.08] text-sm focus:outline-none shadow-sm"
                    />
                  </div>
                </div>
                <div className="flex justify-end gap-2 pt-2">
                  <button onClick={() => setShowAdd(false)} className="px-4 py-2 text-xs font-semibold text-black/40 hover:text-black transition-colors">{zh ? '取消' : 'Cancel'}</button>
                  <button onClick={handleAdd} className="px-6 py-2 rounded-xl bg-cyan-600 text-white text-xs font-bold shadow-lg shadow-cyan-600/20 hover:bg-cyan-700 transition-all">{zh ? '保存' : 'Save'}</button>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Table Container */}
        <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar border-b border-black/5">
          <table className="min-w-full border-collapse text-left">
            <thead className="sticky top-0 z-10">
              <tr className="border-y border-black/5 bg-[#f8fafc] text-[10px] font-bold uppercase tracking-widest text-black/40">
                <th className="px-6 py-4">{zh ? '名称' : 'Name'}</th>
                <th className="px-6 py-4">{zh ? '分类 / 厂商' : 'Category / Vendor'}</th>
                <th className="px-6 py-4">{zh ? '检查 Key' : 'Check Key'}</th>
                <th className="px-6 py-4">{zh ? '采集详情' : 'Acquisition'}</th>
                <th className="px-6 py-4 text-right">{zh ? '操作' : 'Actions'}</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={5} className="px-6 py-12 text-center text-black/20 italic">
                    <div className="flex flex-col items-center gap-2">
                      <RotateCcw className="w-5 h-5 animate-spin" />
                      <span>{zh ? '获取中...' : 'Loading...'}</span>
                    </div>
                  </td>
                </tr>
              ) : Object.keys(groupedItems).length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-6 py-12 text-center text-black/20 italic">
                    {zh ? '暂无匹配的指标项' : 'No items found'}
                  </td>
                </tr>
              ) : (
                Object.entries(groupedItems).map(([category, vendors]) => {
                  return (
                    <React.Fragment key={category}>
                      <tr className="bg-[#164e63]/[0.02]">
                        <td colSpan={5} className="px-6 py-2 border-y border-black/[0.05]">
                          <div className="flex items-center gap-2">
                            <Activity className="w-3.5 h-3.5 text-cyan-500" />
                            <span className="text-[10px] font-black uppercase tracking-[0.2em] text-[#164e63]">
                              {zh ? (CATEGORIES.find(c => c.id === category)?.zh || category) : category}
                            </span>
                          </div>
                        </td>
                      </tr>
                      {Object.entries(vendors).map(([vendor, vendorItems]) => {
                        return (
                          <React.Fragment key={`${category}-${vendor}`}>
                            <tr className="bg-white">
                              <td colSpan={5} className="px-10 py-2">
                                <div className="flex items-center gap-2 opacity-50">
                                  <Shield className="w-3 h-3 text-cyan-400" />
                                  <span className="text-[9px] font-bold text-black/40 uppercase tracking-[0.15em]">
                                    {vendor}
                                  </span>
                                </div>
                              </td>
                            </tr>
                            {vendorItems.map((item) => {
                              const isEditing = editingId === item.id;
                              const isExpanded = expandedId === item.id;
                              return (
                                <React.Fragment key={item.id}>
                                  <tr 
                                    className={`hover:bg-black/[0.01] transition-colors group cursor-pointer ${isExpanded ? 'bg-cyan-50/30' : ''}`}
                                    onClick={() => !isEditing && setExpandedId(isExpanded ? null : item.id)}
                                  >
                                    <td className="px-6 py-4 pl-12">
                                      {isEditing ? (
                                        <div className="space-y-2">
                                          <input
                                            type="text" value={form.name_zh} onChange={e => setForm({ ...form, name_zh: e.target.value })}
                                            className="w-full px-2 py-1 rounded border border-cyan-200 text-xs focus:outline-none"
                                            placeholder="Name (ZH)"
                                          />
                                          <input
                                            type="text" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })}
                                            className="w-full px-2 py-1 rounded border border-cyan-100 text-[10px] text-black/40 focus:outline-none"
                                            placeholder="Name (EN)"
                                          />
                                        </div>
                                      ) : (
                                        <div className="flex items-center gap-3">
                                          <div className={`w-1.5 h-1.5 rounded-full ${isExpanded ? 'bg-cyan-500 scale-150 shadow-lg' : 'bg-black/10'}`} />
                                          <div className="flex flex-col">
                                            <span className="font-bold text-[#164e63]">{zh ? item.name_zh : item.name}</span>
                                            <span className="text-[10px] text-black/30 font-mono">{item.name}</span>
                                          </div>
                                        </div>
                                      )}
                                    </td>
                                    <td className="px-6 py-4">
                                      {isEditing ? (
                                        <div className="space-y-2">
                                          <select
                                            value={form.category} onChange={e => setForm({ ...form, category: e.target.value })}
                                            className="w-full px-2 py-1 rounded border border-cyan-200 text-xs focus:outline-none bg-white"
                                          >
                                            <option value="Network">Network</option>
                                            <option value="Server">Server</option>
                                            <option value="Connectivity">Connectivity</option>
                                            <option value="Interface">Interface</option>
                                            <option value="Health">Health</option>
                                            <option value="Compliance">Compliance</option>
                                          </select>
                                          <select
                                            value={form.vendor} onChange={e => setForm({ ...form, vendor: e.target.value })}
                                            className="w-full px-2 py-1 rounded border border-cyan-100 text-[10px] focus:outline-none bg-white"
                                          >
                                            <option value="">{zh ? '选择厂商' : 'Vendor'}</option>
                                            {VENDORS.map(v => <option key={v} value={v}>{v}</option>)}
                                          </select>
                                        </div>
                                      ) : (
                                        <div className="flex flex-col gap-1">
                                          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase bg-cyan-50 text-cyan-600 w-fit">
                                            {zh ? (CATEGORIES.find(c => c.id === item.category)?.zh || item.category) : item.category}
                                          </span>
                                          {item.vendor && (
                                            <span className="text-[9px] text-black/30 font-bold px-2 tracking-widest">{item.vendor}</span>
                                          )}
                                        </div>
                                      )}
                                    </td>
                                    <td className="px-6 py-4 font-mono text-[11px] text-black/50 tracking-tight">
                                      {isEditing ? (
                                        <input
                                          type="text" value={form.check_key} onChange={e => setForm({ ...form, check_key: e.target.value })}
                                          className="w-full px-2 py-1 rounded border border-cyan-200 text-xs focus:outline-none"
                                        />
                                      ) : item.check_key}
                                    </td>
                                    <td className="px-6 py-4 text-xs text-black/60 italic">
                                      {isEditing ? (
                                        <div className="space-y-2">
                                          <textarea
                                            value={form.description} onChange={e => setForm({ ...form, description: e.target.value })}
                                            className="w-full px-2 py-1 rounded border border-cyan-200 text-[10px] focus:outline-none"
                                            rows={1}
                                            placeholder={zh ? "指标描述" : "Description"}
                                          />
                                          <div className="flex gap-2">
                                            <select
                                              value={form.method} onChange={e => setForm({ ...form, method: e.target.value })}
                                              className="flex-1 px-2 py-1 rounded border border-cyan-200 text-[10px] focus:outline-none bg-white"
                                            >
                                              <option value="SNMP">SNMP</option>
                                              <option value="SSH">SSH</option>
                                              <option value="Shell">Shell</option>
                                              <option value="ICMP">ICMP</option>
                                              <option value="TCP">TCP</option>
                                              <option value="Agent">Agent</option>
                                            </select>
                                            {form.method === 'SNMP' && (
                                              <input
                                                type="text" value={form.oid} onChange={e => setForm({ ...form, oid: e.target.value })}
                                                className="flex-1 px-2 py-1 rounded border border-cyan-200 text-[10px] focus:outline-none"
                                                placeholder="OID"
                                              />
                                            )}
                                          </div>
                                          <textarea
                                            value={form.command} onChange={e => setForm({ ...form, command: e.target.value })}
                                            className="w-full px-2 py-1 rounded border border-cyan-200 text-[10px] focus:outline-none font-mono"
                                            rows={2}
                                            placeholder={zh ? "采集指令" : "Command"}
                                          />
                                        </div>
                                      ) : (
                                        <div className="space-y-2">
                                          <div className="line-clamp-1 max-w-[240px] break-all text-slate-400 text-[10px] font-medium leading-relaxed" title={item.description}>
                                            {item.description || (zh ? "暂无指标业务描述" : "No description")}
                                          </div>
                                          <div className="flex items-center gap-2">
                                            {(() => {
                                              const method = item.method?.toUpperCase();
                                              const isScript = !!item.script_id;
                                              const scriptName = isScript ? (scripts.find(s => s.id === item.script_id)?.name || item.script_id).replace(/（精细化）|\(精细化\)/g, '').trim() : null;
                                              
                                              const cfg = method === 'SNMP' ? { bg: 'bg-blue-50', text: 'text-blue-600', border: 'border-blue-100', icon: Database }
                                                        : method === 'SSH' ? { bg: 'bg-emerald-50', text: 'text-emerald-600', border: 'border-emerald-100', icon: Shield }
                                                        : method === 'ICMP' ? { bg: 'bg-amber-50', text: 'text-amber-600', border: 'border-amber-100', icon: Activity }
                                                        : isScript ? { bg: 'bg-cyan-50', text: 'text-cyan-700', border: 'border-cyan-100', icon: FileCode }
                                                        : { bg: 'bg-slate-50', text: 'text-slate-500', border: 'border-slate-100', icon: Info };
                                              const Icon = cfg.icon;
                                              return (
                                                <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border ${cfg.bg} ${cfg.text} ${cfg.border} text-[10px] font-black uppercase tracking-wider shadow-sm`}>
                                                  <Icon size={12} />
                                                  {isScript ? `${zh ? '脚本: ' : 'Script: '}${scriptName}` : method}
                                                </span>
                                              );
                                            })()}
                                            {item.warning_threshold !== undefined && item.warning_threshold !== null && (
                                              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-lg bg-orange-50 text-orange-600 border border-orange-100 text-[9px] font-bold">
                                                W: {item.warning_threshold}%
                                              </span>
                                            )}
                                            {item.critical_threshold !== undefined && item.critical_threshold !== null && (
                                              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-lg bg-red-50 text-red-600 border border-red-100 text-[9px] font-bold">
                                                C: {item.critical_threshold}%
                                              </span>
                                            )}
                                          </div>
                                        </div>
                                      )}
                                    </td>
                                    <td className="px-6 py-4 text-right">
                                      <div className="flex justify-end gap-2">
                                        {isEditing ? (
                                          <>
                                            <button onClick={(e) => { e.stopPropagation(); handleUpdate(item.id, form); }} className="p-1.5 rounded-lg hover:bg-cyan-50 text-cyan-600 transition-colors shadow-sm border border-cyan-100"><Save className="w-4 h-4" /></button>
                                            <button onClick={(e) => { e.stopPropagation(); setEditingId(null); }} className="p-1.5 rounded-lg hover:bg-red-50 text-red-400 transition-colors shadow-sm border border-red-100"><X className="w-4 h-4" /></button>
                                          </>
                                        ) : (
                                          <>
                                            <button 
                                              onClick={(e) => { e.stopPropagation(); setEditingId(item.id); setForm(item); }} 
                                              className="p-1.5 rounded-lg bg-slate-50 text-slate-400 hover:text-cyan-600 hover:bg-cyan-50 border border-slate-100 transition-all shadow-sm"
                                              title={zh ? '编辑指标' : 'Edit Metric'}
                                            >
                                              <Edit3 size={14} />
                                            </button>
                                            <button 
                                              onClick={(e) => { e.stopPropagation(); handleDelete(item.id); }} 
                                              className="p-1.5 rounded-lg bg-slate-50 text-slate-400 hover:text-red-500 hover:bg-red-50 border border-slate-100 transition-all shadow-sm"
                                              title={zh ? '删除指标' : 'Delete Metric'}
                                            >
                                              <Trash2 size={14} />
                                            </button>
                                          </>
                                        )}
                                      </div>
                                    </td>
                                  </tr>
                                  <AnimatePresence>
                                    {isExpanded && !isEditing && (
                                      <tr>
                                        <td colSpan={5} className="px-6 py-0 border-none">
                                          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                                            <div className="py-4 px-8 bg-black/[0.01] rounded-xl mb-4 mt-1 border border-black/[0.03] grid grid-cols-1 md:grid-cols-2 gap-8 relative">
                                              <div className="absolute top-4 left-4 w-1 h-12 bg-cyan-500/20 rounded-full" />
                                              <div className="space-y-4">
                                                <div>
                                                  <h4 className="text-[10px] font-black uppercase tracking-[0.2em] text-black/20 mb-2">{zh ? '详细描述' : 'DETAILED DESCRIPTION'}</h4>
                                                  <p className="text-xs text-black/70 leading-relaxed font-medium break-all">{item.description || '-'}</p>
                                                </div>
                                                <div className="flex gap-8">
                                                  <div>
                                                    <h4 className="text-[10px] font-black uppercase tracking-[0.2em] text-black/20 mb-1.5">{zh ? '更新时间' : 'UPDATED AT'}</h4>
                                                    <p className="text-[10px] font-mono text-black/40">{item.updated_at}</p>
                                                  </div>
                                                  <div>
                                                    <h4 className="text-[10px] font-black uppercase tracking-[0.2em] text-black/20 mb-1.5">{zh ? '指标 ID' : 'METRIC ID'}</h4>
                                                    <p className="text-[10px] font-mono text-black/40 uppercase">{item.id}</p>
                                                  </div>
                                                </div>
                                              </div>
                                              <div className="bg-white/40 backdrop-blur-sm p-5 rounded-2xl border border-black/[0.03] space-y-4 shadow-sm">
                                                <div className="flex items-center justify-between">
                                                  <h4 className="text-[10px] font-black uppercase tracking-[0.2em] text-black/30">
                                                    {item.script_id ? (zh ? '自动化采集脚本源代码' : 'AUTOMATED SCRIPT SOURCE') : (zh ? '数据采集与指令' : 'ACQUISITION & COMMAND')}
                                                  </h4>
                                                  <div className="flex gap-2">
                                                    {item.oid && <span className="px-2.5 py-1 rounded-lg bg-indigo-500 text-white text-[10px] font-black shadow-lg shadow-indigo-500/20">OID: {item.oid}</span>}
                                                    <span className="px-2.5 py-1 rounded-lg bg-cyan-500 text-white text-[10px] font-black shadow-lg shadow-cyan-500/20">{item.method}</span>
                                                  </div>
                                                </div>
                                                <div className="bg-[#00172d] p-4 rounded-xl border border-white/5 relative group/code overflow-hidden shadow-inner">
                                                  <div className="absolute top-0 right-0 w-24 h-24 bg-cyan-500/5 rounded-full -translate-y-1/2 translate-x-1/2 blur-2xl" />
                                                  <div className="relative group/copy-cmd">
                                                    <code className="text-[11px] text-cyan-300 font-mono whitespace-pre-wrap break-all relative z-10 block pr-8 leading-relaxed">
                                                      {item.script_id 
                                                        ? (scripts.find(s => s.id === item.script_id)?.content || '# Script content loading...') 
                                                        : (item.command || '# No command defined')}
                                                    </code>
                                                    <button 
                                                      onClick={(e) => { e.stopPropagation(); copyToClipboard(item.command, `${item.id}-cmd`); }}
                                                      className={`absolute top-0 right-0 z-20 p-1.5 rounded-lg transition-all ${
                                                        copiedId === `${item.id}-cmd` 
                                                        ? 'bg-green-500/20 text-green-400 opacity-100' 
                                                        : 'bg-white/5 hover:bg-white/10 text-cyan-300/50 hover:text-cyan-300 opacity-0 group-hover/copy-cmd:opacity-100'
                                                      }`}
                                                      title={zh ? '复制指令' : 'Copy Command'}
                                                    >
                                                      {copiedId === `${item.id}-cmd` ? (
                                                        <div className="flex items-center gap-1">
                                                          <Check className="w-3 h-3 animate-in zoom-in duration-200" />
                                                          <span className="text-[9px] font-bold">{zh ? '已复制' : 'Copied'}</span>
                                                        </div>
                                                      ) : (
                                                        <Copy className="w-3 h-3" />
                                                      )}
                                                    </button>
                                                  </div>
                                                </div>
                                              </div>
                                            </div>
                                          </motion.div>
                                        </td>
                                      </tr>
                                    )}
                                  </AnimatePresence>
                                </React.Fragment>
                              );
                            })}
                          </React.Fragment>
                        );
                      })}
                    </React.Fragment>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div className="flex-shrink-0 bg-white border-t border-black/5 px-6 py-4">
          <Pagination
            currentPage={currentPage}
            totalItems={filteredItems.length}
            itemsPerPage={pageSize}
            onPageChange={setCurrentPage}
            onItemsPerPageChange={(size) => { setPageSize(size); setCurrentPage(1); }}
            language={language}
            alwaysVisible
          />
        </div>
      </div>
    </div>
  );
};

export default InspectionItemsTab;
