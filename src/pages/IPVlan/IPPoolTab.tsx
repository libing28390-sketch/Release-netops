import React, { useState, useEffect, useCallback } from 'react';
import {
  Package,
  Plus,
  Trash2,
  Search,
  Pencil,
  X,
  PlusCircle,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import PageHero from '../../components/PageHero';
import Pagination from '../../components/Pagination';
import { ActionIconButton, ActionIconGroup } from '../../components/ui/ActionIconButton';

interface IPPool {
  id: string;
  name: string;
  prefix_id: string;
  prefix: string;
  prefix_name: string | null;
  start_ip: string;
  end_ip: string;
  description: string;
  status: string;
  tenant_id: string;
  tenant_name: string | null;
  total_ips: number;
  used_ips: number;
  utilization: number;
}

interface Prefix {
  id: string;
  prefix: string;
  name: string;
}

interface IPPoolTabProps {
  language: string;
  t: (key: string) => string;
}

const IPPoolTab: React.FC<IPPoolTabProps> = ({ language, t }) => {
  const zh = language === 'zh';

  const [pools, setPools] = useState<IPPool[]>([]);
  const [prefixes, setPrefixes] = useState<Prefix[]>([]);
  const [tenants, setTenants] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [totalPools, setTotalPools] = useState(0);

  // Modals
  const [showAddEdit, setShowAddEdit] = useState(false);
  const [editingPool, setEditingPool] = useState<IPPool | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<string | null>(null);

  // Form State
  const [form, setForm] = useState({
    name: '',
    prefix_id: '',
    start_ip: '',
    end_ip: '',
    description: '',
    status: 'active',
    tenant_id: 'tenant-default',
  });
  const [errorMsg, setErrorMsg] = useState('');

  const authHeaders = useCallback(() => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, []);

  const loadData = useCallback(async () => {
    setLoading(true);
    const hdrs = authHeaders();
    try {
      const [poolRes, prefRes, tenantRes] = await Promise.all([
        fetch(`/api/ipam/pools?q=${encodeURIComponent(search.trim())}&page=${page}&page_size=${pageSize}`, { headers: hdrs }),
        fetch('/api/ipam/subnets', { headers: hdrs }),
        fetch('/api/cmdb/tenants', { headers: hdrs }),
      ]);
      const unwrap = (j: any) => (Array.isArray(j) ? j : (j?.data ?? j?.items ?? []));
      if (poolRes.ok) {
        const payload = await poolRes.json();
        const data = payload?.data && !Array.isArray(payload.data) ? payload.data : payload;
        setPools(Array.isArray(data) ? data : (data?.items || []));
        setTotalPools(Array.isArray(data) ? data.length : Number(data?.total || 0));
      }
      if (prefRes.ok) setPrefixes(await prefRes.json());
      if (tenantRes.ok) setTenants(unwrap(await tenantRes.json()));
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [authHeaders, page, pageSize, search]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const openForm = (poolItem: IPPool | null = null) => {
    setErrorMsg('');
    if (poolItem) {
      setEditingPool(poolItem);
      setForm({
        name: poolItem.name,
        prefix_id: poolItem.prefix_id,
        start_ip: poolItem.start_ip,
        end_ip: poolItem.end_ip,
        description: poolItem.description || '',
        status: poolItem.status || 'active',
        tenant_id: poolItem.tenant_id || 'tenant-default',
      });
    } else {
      setEditingPool(null);
      setForm({
        name: '',
        prefix_id: prefixes[0]?.id || '',
        start_ip: '',
        end_ip: '',
        description: '',
        status: 'active',
        tenant_id: 'tenant-default',
      });
    }
    setShowAddEdit(true);
  };

  const handleSave = async () => {
    setErrorMsg('');
    if (!form.name || !form.prefix_id || !form.start_ip || !form.end_ip) {
      setErrorMsg(zh ? '请填写所有必填字段' : 'Please fill all required fields');
      return;
    }

    try {
      const url = editingPool ? `/api/ipam/pools/${editingPool.id}` : '/api/ipam/pools';
      const method = editingPool ? 'PUT' : 'POST';
      const res = await fetch(url, {
        method,
        headers: {
          'Content-Type': 'application/json',
          ...authHeaders(),
        },
        body: JSON.stringify(form),
      });

      if (res.ok) {
        setShowAddEdit(false);
        loadData();
      } else {
        const err = await res.json();
        setErrorMsg(err.detail || (zh ? '操作失败' : 'Operation failed'));
      }
    } catch (e) {
      setErrorMsg(zh ? '网络请求错误' : 'Network request error');
    }
  };

  const handleDelete = async (id: string) => {
    try {
      const res = await fetch(`/api/ipam/pools/${id}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (res.ok) {
        setShowDeleteConfirm(null);
        loadData();
      }
    } catch (e) {
      console.error(e);
    }
  };

  // Filter pool list
  const filteredPools = pools;
  const paginatedPools = pools;

  const getUtilColor = (util: number) => {
    if (util < 60) return 'from-emerald-400 to-green-500';
    if (util < 80) return 'from-amber-400 to-orange-500';
    return 'from-rose-400 to-red-500';
  };

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden px-6 py-5 space-y-4">
      <PageHero
        icon={Package}
        title={zh ? 'IP地址池管理' : 'IP Pool Management'}
        subtitle={zh ? '定义网段内的连续IP范围（如办公网DHCP池、动态分配池），监控各地址池的实时水位与利用率' : 'Manage IP range sub-allocations like DHCP dynamic pools or server range pools.'}
        actions={
          <button
            onClick={() => openForm(null)}
            className="flex items-center gap-1.5 px-4 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-600 hover:to-blue-700 text-white rounded-xl text-xs font-bold shadow-lg shadow-cyan-500/20 active:scale-95 transition-all"
          >
            <Plus size={14} />
            {zh ? '创建地址池' : 'Create Pool'}
          </button>
        }
        extras={
          <div className="relative w-full md:w-64">
            <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1); }}
              placeholder={zh ? '搜索地址池名称、网段...' : 'Search pools...'}
              className="w-full pl-10 pr-4 py-1.5 text-xs rounded-xl border border-black/5 bg-gray-50/50 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium"
            />
          </div>
        }
      />

      {/* Main Table Card */}
      <div className="flex-1 min-h-0 bg-white rounded-[28px] border border-black/5 shadow-[0_16px_36px_rgba(11,35,64,0.06)] overflow-hidden flex flex-col">
        <div className="flex-1 overflow-auto">
          {loading ? (
            <div className="h-full flex items-center justify-center text-xs text-gray-400 font-semibold">
              {zh ? '加载中...' : 'Loading IP pools...'}
            </div>
          ) : (
            <table className="nx-data-table text-left">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/40 text-[10px] font-bold text-gray-400 uppercase tracking-wider select-none">
                  <th className="pl-6 py-4">{zh ? '地址池名称' : 'Pool Name'}</th>
                  <th className="px-4 py-4">{zh ? '所属前缀' : 'Parent Prefix'}</th>
                  <th className="px-4 py-4">{zh ? '起始IP' : 'Start IP'}</th>
                  <th className="px-4 py-4">{zh ? '结束IP' : 'End IP'}</th>
                  <th className="px-4 py-4">{zh ? '池容量 (IP数)' : 'Pool Capacity'}</th>
                  <th className="px-4 py-4">{zh ? '所属租户' : 'Tenant'}</th>
                  <th className="px-4 py-4">{zh ? '状态' : 'Status'}</th>
                  <th className="px-4 py-4">{zh ? '利用率' : 'Utilization'}</th>
                  <th className="pr-6 py-4 text-right">{zh ? '操作' : 'Actions'}</th>
                </tr>
              </thead>
              <tbody>
                {paginatedPools.length > 0 ? (
                  paginatedPools.map((node) => (
                    <tr 
                      key={node.id} 
                      className="hover:bg-gray-50/50 transition-colors border-b border-gray-100 group"
                    >
                      <td className="pl-6 py-4 text-sm font-semibold text-gray-800">{node.name}</td>
                      <td className="px-4 py-4 text-xs font-mono font-bold text-cyan-600">{node.prefix}</td>
                      <td className="px-4 py-4 font-mono text-xs text-gray-700">{node.start_ip}</td>
                      <td className="px-4 py-4 font-mono text-xs text-gray-700">{node.end_ip}</td>
                      <td className="px-4 py-4 text-xs text-gray-600 font-semibold">{node.total_ips} IPs</td>
                      <td className="px-4 py-4 text-xs text-gray-500 font-medium">{node.tenant_name || '-'}</td>
                      <td className="px-4 py-4">
                        <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-emerald-50 text-emerald-600 border border-emerald-500/10`}>
                          <span className="w-1 h-1 rounded-full bg-emerald-500" />
                          {node.status.toUpperCase()}
                        </span>
                      </td>
                      <td className="px-4 py-4">
                        <div className="flex flex-col gap-1 w-24">
                          <div className="flex justify-between text-[10px] font-bold text-gray-400">
                            <span>{node.used_ips}/{node.total_ips}</span>
                            <span>{node.utilization}%</span>
                          </div>
                          <div className="w-full h-1.5 bg-gray-100 rounded-full overflow-hidden">
                            <div 
                              className={`h-full rounded-full bg-gradient-to-r ${getUtilColor(node.utilization)}`} 
                              style={{ width: `${node.utilization}%` }}
                            />
                          </div>
                        </div>
                      </td>
                      <td className="pr-6 py-4 text-right">
                        <ActionIconGroup label={zh ? '地址池操作' : 'Pool actions'} className="opacity-0 transition-opacity group-hover:opacity-100">
                          <ActionIconButton
                            icon={Pencil}
                            label={zh ? '编辑' : 'Edit'}
                            onClick={() => openForm(node)}
                          />
                          <ActionIconButton
                            icon={Trash2}
                            label={zh ? '删除' : 'Delete'}
                            variant="danger"
                            onClick={() => setShowDeleteConfirm(node.id)}
                          />
                        </ActionIconGroup>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={9} className="py-12 text-center text-xs text-gray-400 font-medium">
                      {zh ? '暂无动态分配地址池记录' : 'No IP pools configured'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination */}
        <div className="px-6 py-4 border-t border-gray-100">
          <Pagination
            currentPage={page}
            totalItems={totalPools}
            itemsPerPage={pageSize}
            onPageChange={setPage}
            onItemsPerPageChange={(size) => { setPageSize(size); setPage(1); }}
            language={language}
            alwaysVisible={true}
          />
        </div>
      </div>

      {/* Add / Edit Modal */}
      <AnimatePresence>
        {showAddEdit && (
          <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-white w-full max-w-lg rounded-3xl overflow-hidden shadow-2xl border border-black/5 flex flex-col max-h-[90vh]"
            >
              <div className="px-6 py-5 border-b border-gray-100 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-2xl bg-cyan-50 flex items-center justify-center text-cyan-600">
                    <PlusCircle size={20} />
                  </div>
                  <div>
                    <h3 className="font-bold text-gray-900">{editingPool ? (zh ? '编辑地址池' : 'Edit IP Pool') : (zh ? '新建地址池' : 'Create IP Pool')}</h3>
                    <p className="text-xs text-gray-500 mt-0.5">{zh ? '划定前缀段内的起始与结束IP范围用作特定池' : 'Define start/end IP ranges for dedicated pools.'}</p>
                  </div>
                </div>
                <button onClick={() => setShowAddEdit(false)} className="p-1.5 rounded-lg hover:bg-gray-50 transition-colors text-gray-400">
                  <X size={16} />
                </button>
              </div>

              <div className="flex-1 overflow-y-auto p-6 space-y-4">
                {errorMsg && (
                  <div className="p-3.5 rounded-2xl bg-rose-50 border border-rose-200 text-xs font-semibold text-rose-600">
                    {errorMsg}
                  </div>
                )}

                <div className="grid grid-cols-2 gap-4">
                  {/* Name */}
                  <div className="space-y-1.5 col-span-2">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '地址池名称 *' : 'Pool Name *'}</label>
                    <input
                      type="text"
                      value={form.name}
                      onChange={(e) => setForm({ ...form, name: e.target.value })}
                      placeholder="e.g. DHCP Range Pool"
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                  </div>

                  {/* Prefix Select */}
                  <div className="space-y-1.5 col-span-2">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '归属前缀网段 *' : 'Belongs to Prefix *'}</label>
                    <select
                      value={form.prefix_id}
                      onChange={(e) => setForm({ ...form, prefix_id: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    >
                      <option value="">{zh ? '请选择前缀网段' : 'Select Prefix'}</option>
                      {prefixes.map((item) => (
                        <option key={item.id} value={item.id}>{item.prefix} {item.name ? `(${item.name})` : ''}</option>
                      ))}
                    </select>
                  </div>

                  {/* Start IP */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '起始 IP 地址 *' : 'Start IP *'}</label>
                    <input
                      type="text"
                      value={form.start_ip}
                      onChange={(e) => setForm({ ...form, start_ip: e.target.value })}
                      placeholder="e.g. 10.1.1.100"
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                  </div>

                  {/* End IP */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '结束 IP 地址 *' : 'End IP *'}</label>
                    <input
                      type="text"
                      value={form.end_ip}
                      onChange={(e) => setForm({ ...form, end_ip: e.target.value })}
                      placeholder="e.g. 10.1.1.200"
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                  </div>

                  {/* Tenant Select */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '归属租户' : 'Tenant'}</label>
                    <select
                      value={form.tenant_id}
                      onChange={(e) => setForm({ ...form, tenant_id: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    >
                      {tenants.map((item) => (
                        <option key={item.id} value={item.id}>{item.name}</option>
                      ))}
                    </select>
                  </div>

                  {/* Status */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '状态' : 'Status'}</label>
                    <select
                      value={form.status}
                      onChange={(e) => setForm({ ...form, status: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    >
                      <option value="active">ACTIVE</option>
                      <option value="reserved">RESERVED</option>
                    </select>
                  </div>

                  {/* Description */}
                  <div className="space-y-1.5 col-span-2">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '说明备注描述' : 'Description'}</label>
                    <textarea
                      value={form.description}
                      onChange={(e) => setForm({ ...form, description: e.target.value })}
                      placeholder={zh ? '在此输入地址池的主要分配角色用途...' : 'Allocations usage...'}
                      rows={2}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50 resize-none"
                    />
                  </div>
                </div>
              </div>

              <div className="px-6 py-4 bg-gray-50 border-t border-gray-100 flex items-center justify-end gap-3 flex-shrink-0">
                <button onClick={() => setShowAddEdit(false)} className="px-4 py-2 text-xs font-bold text-gray-500 hover:bg-gray-100 rounded-xl">
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button onClick={handleSave} className="px-6 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-600 hover:to-blue-700 text-white text-xs font-extrabold rounded-xl shadow-md transition-all active:scale-95">
                  {zh ? '确认保存' : 'Save'}
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* Delete Confirmation Modal */}
      <AnimatePresence>
        {showDeleteConfirm && (
          <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-white w-full max-w-md rounded-3xl overflow-hidden shadow-2xl border border-black/5"
            >
              <div className="p-6">
                <h3 className="text-base font-bold text-gray-900 mb-2">{zh ? '删除地址池？' : 'Delete IP Pool?'}</h3>
                <p className="text-xs text-gray-500 leading-relaxed">
                  {zh ? '确定要删除此动态地址池划定吗？删除后，池内的分配范围记录将被移除，但不会物理释放网段里已登记的静态IP地址。' : 'Are you sure you want to delete this dynamic pool range? Nested IP addresses will not be deleted.'}
                </p>
              </div>
              <div className="px-6 py-4 bg-gray-50 flex items-center justify-end gap-3 border-t border-gray-100">
                <button onClick={() => setShowDeleteConfirm(null)} className="px-3 py-1.5 text-xs text-gray-500 hover:bg-gray-100 rounded-lg">
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button onClick={() => handleDelete(showDeleteConfirm)} className="px-4 py-1.5 text-xs bg-rose-500 hover:bg-rose-600 text-white rounded-lg font-bold">
                  {zh ? '确定删除' : 'Delete'}
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default IPPoolTab;
