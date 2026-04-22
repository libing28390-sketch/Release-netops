import React, { useEffect, useState, useCallback, useMemo } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  Activity, Plus, X, Trash2, Edit3, Save, RotateCcw,
  Shield, CheckCircle2, Search, Filter, Info, ListFilter
} from 'lucide-react';
import Pagination from '../components/Pagination';

interface InspectionItem {
  id: string;
  name: string;
  name_zh: string;
  category: string;
  check_key: string;
  description: string;
  method: string;
  command: string;
  created_at: string;
  updated_at: string;
}

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
    method: 'SNMP', command: ''
  });

  // Pagination states
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(12);
  const [expandedId, setExpandedId] = useState<string | null>(null);

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

  useEffect(() => { fetchItems(); }, [fetchItems]);

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
        setForm({ name: '', name_zh: '', category: 'Hardware', check_key: '', description: '' });
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

  const filteredItems = useMemo(() => {
    let result = items;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      result = items.filter(i => 
        i.name.toLowerCase().includes(q) || 
        i.name_zh.toLowerCase().includes(q) || 
        i.category.toLowerCase().includes(q) ||
        i.check_key.toLowerCase().includes(q)
      );
    }
    return result;
  }, [items, searchQuery]);

  const totalPages = Math.ceil(filteredItems.length / pageSize);
  const paginatedItems = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredItems.slice(start, start + pageSize);
  }, [filteredItems, currentPage, pageSize]);

  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-[#164e63] flex items-center gap-2">
            <ListFilter className="w-6 h-6 text-cyan-500" />
            {zh ? '巡检指标项管理' : 'Inspection Items Management'}
          </h2>
          <p className="text-xs text-black/40 mt-1 uppercase font-bold tracking-widest">
            {zh ? '定义与维护自动化巡检的核心监控指标' : 'Define and manage core metrics for automated inspection'}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="relative group">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-black/20 group-focus-within:text-cyan-500 transition-colors" />
            <input
              type="text"
              placeholder={zh ? '搜索指标...' : 'Search items...'}
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              className="pl-9 pr-4 py-2.5 rounded-xl border border-black/[0.08] bg-white text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all w-48 lg:w-64"
            />
          </div>
          <button
            onClick={() => setShowAdd(!showAdd)}
            className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl bg-[#164e63] text-white text-sm font-bold shadow-sm hover:bg-[#0e3f52] transition-all active:scale-[0.97]"
          >
            <Plus className="w-4 h-4" />
            {zh ? '新增指标' : 'Add Item'}
          </button>
        </div>
      </div>

      <AnimatePresence>
        {showAdd && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
            <div className="rounded-2xl border border-cyan-200/60 bg-gradient-to-br from-cyan-50/50 to-white p-5 space-y-4 shadow-sm">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-bold text-[#164e63] flex items-center gap-2">
                  <Plus className="w-4 h-4 text-cyan-500" />
                  {zh ? '配置新指标' : 'Configure New Item'}
                </h4>
                <button onClick={() => setShowAdd(false)} className="p-1 rounded-lg text-black/30 hover:bg-black/5 transition-all">
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                <div>
                  <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '英文名称' : 'Name (EN)'}</label>
                  <input
                    type="text" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })}
                    className="w-full px-3.5 py-2 rounded-xl border border-black/[0.08] text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500/10 focus:border-cyan-400"
                  />
                </div>
                <div>
                  <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '中文名称' : 'Name (ZH)'}</label>
                  <input
                    type="text" value={form.name_zh} onChange={e => setForm({ ...form, name_zh: e.target.value })}
                    className="w-full px-3.5 py-2 rounded-xl border border-black/[0.08] text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500/10 focus:border-cyan-400"
                  />
                </div>
                <div>
                  <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '分类' : 'Category'}</label>
                  <select
                    value={form.category} onChange={e => setForm({ ...form, category: e.target.value })}
                    className="w-full px-3.5 py-2 rounded-xl border border-black/[0.08] text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500/10 focus:border-cyan-400 bg-white"
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
                  <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '检查 Key (唯一标识)' : 'Check Key (Unique)'}</label>
                  <input
                    type="text" value={form.check_key} onChange={e => setForm({ ...form, check_key: e.target.value })}
                    className="w-full px-3.5 py-2 rounded-xl border border-black/[0.08] text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500/10 focus:border-cyan-400"
                  />
                </div>
              </div>
              <div>
                <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '详细说明' : 'Description'}</label>
                <textarea
                  rows={2} value={form.description} onChange={e => setForm({ ...form, description: e.target.value })}
                  className="w-full px-3.5 py-2 rounded-xl border border-black/[0.08] text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500/10 focus:border-cyan-400"
                />
              </div>
              <div className="flex justify-end gap-2">
                <button onClick={() => setShowAdd(false)} className="px-4 py-2 text-xs font-semibold text-black/40">{zh ? '取消' : 'Cancel'}</button>
                <button onClick={handleAdd} className="px-6 py-2 rounded-xl bg-cyan-600 text-white text-xs font-bold shadow-sm">{zh ? '保存' : 'Save'}</button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="rounded-2xl border border-black/[0.06] bg-white shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm border-collapse">
            <thead>
              <tr className="bg-black/[0.01] border-b border-black/[0.05]">
                <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{zh ? '名称' : 'Name'}</th>
                <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{zh ? '分类' : 'Category'}</th>
                <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{zh ? '检查 Key' : 'Check Key'}</th>
                <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{zh ? '描述' : 'Description'}</th>
                <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40 text-right">{zh ? '操作' : 'Actions'}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-black/[0.03]">
              {loading ? (
                <tr>
                  <td colSpan={5} className="px-6 py-12 text-center text-black/20 italic">
                    <div className="flex flex-col items-center gap-2">
                      <RotateCcw className="w-5 h-5 animate-spin" />
                      <span>{zh ? '获取中...' : 'Loading...'}</span>
                    </div>
                  </td>
                </tr>
              ) : paginatedItems.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-6 py-12 text-center text-black/20 italic">
                    {zh ? '暂无匹配的指标项' : 'No items found'}
                  </td>
                </tr>
              ) : paginatedItems.map(item => {
                const isEditing = editingId === item.id;
                const isExpanded = expandedId === item.id;
                return (
                  <React.Fragment key={item.id}>
                    <tr 
                      className={`hover:bg-black/[0.01] transition-colors group cursor-pointer ${isExpanded ? 'bg-cyan-50/30' : ''}`}
                      onClick={() => !isEditing && setExpandedId(isExpanded ? null : item.id)}
                    >
                      <td className="px-6 py-4">
                        {isEditing ? (
                          <div className="space-y-2">
                            <input
                              type="text" value={form.name_zh} onChange={e => setForm({ ...form, name_zh: e.target.value })}
                              className="w-full px-2 py-1 rounded border border-cyan-200 text-xs focus:outline-none focus:ring-1 focus:ring-cyan-500"
                              placeholder={zh ? '中文名' : 'Name (ZH)'}
                            />
                            <input
                              type="text" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })}
                              className="w-full px-2 py-1 rounded border border-cyan-100 text-[10px] text-black/40 focus:outline-none"
                              placeholder={zh ? '英文名' : 'Name (EN)'}
                            />
                          </div>
                        ) : (
                          <div className="flex items-center gap-3">
                            <div className={`w-1.5 h-1.5 rounded-full transition-all duration-300 ${isExpanded ? 'bg-cyan-500 scale-[1.5] shadow-[0_0_8px_rgba(6,182,212,0.6)]' : 'bg-black/10'}`} />
                            <div className="flex flex-col">
                              <span className="font-bold text-[#164e63]">{zh ? item.name_zh : item.name}</span>
                              <span className="text-[10px] text-black/30 font-mono">{zh ? item.name : item.name_zh}</span>
                            </div>
                          </div>
                        )}
                      </td>
                      <td className="px-6 py-4">
                        {isEditing ? (
                          <select
                            value={form.category} onChange={e => setForm({ ...form, category: e.target.value })}
                            className="px-2 py-1 rounded border border-cyan-200 text-xs focus:outline-none focus:ring-1 focus:ring-cyan-500 bg-white"
                          >
                            <option value="Network">{zh ? '网络设备' : 'Network Device'}</option>
                            <option value="Server">{zh ? '服务器/主机' : 'Server / Host'}</option>
                            <option value="Connectivity">{zh ? '基础连通性' : 'Connectivity'}</option>
                            <option value="Interface">{zh ? '接口统计' : 'Interface'}</option>
                            <option value="Health">{zh ? '业务健康度' : 'Health'}</option>
                            <option value="Compliance">{zh ? '合规性检查' : 'Compliance'}</option>
                          </select>
                        ) : (
                          <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${
                            item.category === 'Network' ? 'bg-indigo-50 text-indigo-600' :
                            item.category === 'Server' ? 'bg-amber-50 text-amber-600' :
                            item.category === 'Connectivity' ? 'bg-blue-50 text-blue-600' :
                            item.category === 'Interface' ? 'bg-emerald-50 text-emerald-600' :
                            'bg-purple-50 text-purple-600'
                          }`}>
                            {item.category}
                          </span>
                        )}
                      </td>
                      <td className="px-6 py-4 font-mono text-xs text-black/50">
                        {isEditing ? (
                          <input
                            type="text" value={form.check_key} onChange={e => setForm({ ...form, check_key: e.target.value })}
                            className="w-full px-2 py-1 rounded border border-cyan-200 text-xs focus:outline-none focus:ring-1 focus:ring-cyan-500"
                            placeholder="Key"
                          />
                        ) : item.check_key}
                      </td>
                      <td className="px-6 py-4 text-xs text-black/60 italic max-w-xs truncate">
                        {isEditing ? (
                          <div className="space-y-1">
                            <input
                              type="text" value={form.method} onChange={e => setForm({ ...form, method: e.target.value })}
                              className="w-full px-2 py-1 rounded border border-cyan-200 text-[10px] focus:outline-none focus:ring-1 focus:ring-cyan-500"
                              placeholder="Method"
                            />
                            <input
                              type="text" value={form.command} onChange={e => setForm({ ...form, command: e.target.value })}
                              className="w-full px-2 py-1 rounded border border-cyan-200 text-[10px] focus:outline-none focus:ring-1 focus:ring-cyan-500"
                              placeholder="Command"
                            />
                          </div>
                        ) : item.description}
                      </td>
                      <td className="px-6 py-4 text-right">
                        <div className="flex justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          {isEditing ? (
                            <>
                              <button onClick={(e) => { e.stopPropagation(); handleUpdate(item.id); }} className="p-1.5 rounded-lg hover:bg-cyan-50 text-cyan-600" title="Save">
                                <Save className="w-4 h-4" />
                              </button>
                              <button onClick={(e) => { e.stopPropagation(); setEditingId(null); }} className="p-1.5 rounded-lg hover:bg-red-50 text-red-400" title="Cancel">
                                <X className="w-4 h-4" />
                              </button>
                            </>
                          ) : (
                            <>
                              <button 
                                onClick={(e) => { e.stopPropagation(); setEditingId(item.id); setForm(item); }} 
                                className="p-1.5 rounded-lg hover:bg-black/5 text-black/40 hover:text-black"
                              >
                                <Edit3 className="w-4 h-4" />
                              </button>
                              <button 
                                onClick={(e) => { e.stopPropagation(); handleDelete(item.id); }} 
                                className="p-1.5 rounded-lg hover:bg-red-50 text-red-400"
                              >
                                <Trash2 className="w-4 h-4" />
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
                            <motion.div
                              initial={{ height: 0, opacity: 0 }}
                              animate={{ height: 'auto', opacity: 1 }}
                              exit={{ height: 0, opacity: 0 }}
                              className="overflow-hidden"
                            >
                              <div className="py-4 px-8 bg-black/[0.02] rounded-xl mb-4 mt-1 border border-black/[0.04] grid grid-cols-1 md:grid-cols-2 gap-8 relative">
                                <div className="absolute top-4 left-4 w-1 h-12 bg-cyan-500/20 rounded-full" />
                                <div className="space-y-4">
                                  <div>
                                    <h4 className="text-[10px] font-black uppercase tracking-[0.2em] text-black/20 mb-2">{zh ? '详细描述' : 'DETAILED DESCRIPTION'}</h4>
                                    <p className="text-xs text-black/70 leading-relaxed font-medium">{item.description || '-'}</p>
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
                                    <h4 className="text-[10px] font-black uppercase tracking-[0.2em] text-black/30">{zh ? '采集方式与指令' : 'ACQUISITION & COMMAND'}</h4>
                                    <span className="px-2.5 py-1 rounded-lg bg-cyan-500 text-white text-[10px] font-black shadow-lg shadow-cyan-500/20">{item.method}</span>
                                  </div>
                                  <div className="bg-[#00172d] p-4 rounded-xl border border-white/5 relative group/code overflow-hidden">
                                    <div className="absolute top-0 right-0 w-24 h-24 bg-cyan-500/5 rounded-full -translate-y-1/2 translate-x-1/2 blur-2xl" />
                                    <code className="text-[11px] text-cyan-300 font-mono whitespace-pre relative z-10 block">
                                      {item.command || (zh ? '# 暂无指令定义' : '# No command defined')}
                                    </code>
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
            </tbody>
          </table>
        </div>
      </div>

      {/* Pagination */}
      <div className="mt-4">
        <Pagination
          currentPage={currentPage}
          totalItems={filteredItems.length}
          itemsPerPage={pageSize}
          onPageChange={setCurrentPage}
          onItemsPerPageChange={setPageSize}
          language={language}
        />
      </div>
    </div>
  );
};

export default InspectionItemsTab;
