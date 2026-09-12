import React, { useState, useEffect, useCallback } from 'react';
import {
  Clock,
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

interface DHCPLease {
  id: string;
  address: string;
  mac_address: string;
  hostname: string;
  dhcp_server: string;
  lease_state: string;
  lease_start: string;
  lease_end: string;
  created_at: string;
  updated_at: string;
}

interface DHCPLeaseTabProps {
  language: string;
  t: (key: string) => string;
}

const DHCPLeaseTab: React.FC<DHCPLeaseTabProps> = ({ language, t }) => {
  const zh = language === 'zh';

  const [leases, setLeases] = useState<DHCPLease[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [stateFilter, setStateFilter] = useState('all');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [totalLeases, setTotalLeases] = useState(0);

  // Modals
  const [showAddEdit, setShowAddEdit] = useState(false);
  const [editingLease, setEditingLease] = useState<DHCPLease | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<string | null>(null);

  // Form State
  const [form, setForm] = useState({
    address: '',
    mac_address: '',
    hostname: '',
    dhcp_server: '',
    lease_state: 'active',
    lease_start: '',
    lease_end: '',
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
      const res = await fetch(`/api/ipam/leases?q=${encodeURIComponent(search.trim())}&state=${encodeURIComponent(stateFilter)}&page=${page}&page_size=${pageSize}`, { headers: hdrs });
      if (res.ok) {
        const payload = await res.json();
        const data = payload?.data && !Array.isArray(payload.data) ? payload.data : payload;
        setLeases(Array.isArray(data) ? data : (data?.items || []));
        setTotalLeases(Array.isArray(data) ? data.length : Number(data?.total || 0));
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [authHeaders, page, pageSize, search, stateFilter]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const openForm = (leaseItem: DHCPLease | null = null) => {
    setErrorMsg('');
    if (leaseItem) {
      setEditingLease(leaseItem);
      setForm({
        address: leaseItem.address,
        mac_address: leaseItem.mac_address,
        hostname: leaseItem.hostname || '',
        dhcp_server: leaseItem.dhcp_server || '',
        lease_state: leaseItem.lease_state || 'active',
        lease_start: leaseItem.lease_start || '',
        lease_end: leaseItem.lease_end || '',
      });
    } else {
      setEditingLease(null);
      setForm({
        address: '',
        mac_address: '',
        hostname: '',
        dhcp_server: 'Infoblox',
        lease_state: 'active',
        lease_start: new Date().toISOString().split('T')[0],
        lease_end: new Date(Date.now() + 86400000 * 7).toISOString().split('T')[0], // default 7 days lease
      });
    }
    setShowAddEdit(true);
  };

  const handleSave = async () => {
    setErrorMsg('');
    if (!form.address || !form.mac_address) {
      setErrorMsg(zh ? '请填写所有必填字段' : 'Please fill all required fields');
      return;
    }

    try {
      const url = editingLease ? `/api/ipam/leases/${editingLease.id}` : '/api/ipam/leases';
      const method = editingLease ? 'PUT' : 'POST';
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
      const res = await fetch(`/api/ipam/leases/${id}`, {
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

  // Filter lease list
  const filteredLeases = leases;
  const paginatedLeases = leases;

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden px-6 py-5 space-y-4">
      <PageHero
        icon={Clock}
        title={zh ? 'DHCP 租约分配管理' : 'DHCP Leases'}
        subtitle={zh ? '记录与管理网络动态分发中各DHCP主机的状态，跟踪IP与MAC对应关系的过期周期' : 'Monitor temporary IP mappings allocated to dynamically bound client MACs.'}
        actions={
          <button
            onClick={() => openForm(null)}
            className="flex items-center gap-1.5 px-4 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-600 hover:to-blue-700 text-white rounded-xl text-xs font-bold shadow-lg shadow-cyan-500/20 active:scale-95 transition-all"
          >
            <Plus size={14} />
            {zh ? '创建租约' : 'Add Lease'}
          </button>
        }
        extras={
          <div className="flex items-center gap-3 w-full md:w-auto">
            {/* State Filter */}
            <select
              value={stateFilter}
              onChange={(e) => { setStateFilter(e.target.value); setPage(1); }}
              className="px-3.5 py-1.5 rounded-xl border border-black/5 bg-white text-xs font-semibold text-gray-500 outline-none"
            >
              <option value="all">{zh ? '所有租约状态' : 'All Lease States'}</option>
              <option value="active">ACTIVE (活跃)</option>
              <option value="expired">EXPIRED (过期)</option>
            </select>

            {/* Search Input */}
            <div className="relative w-full md:w-64">
              <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                value={search}
                onChange={(e) => { setSearch(e.target.value); setPage(1); }}
                placeholder={zh ? '搜索IP、MAC地址、DHCP服务器...' : 'Search DHCP leases...'}
                className="w-full pl-10 pr-4 py-1.5 text-xs rounded-xl border border-black/5 bg-gray-50/50 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium"
              />
            </div>
          </div>
        }
      />

      {/* Main Table Card */}
      <div className="flex-1 min-h-0 bg-white rounded-[28px] border border-black/5 shadow-[0_16px_36px_rgba(11,35,64,0.06)] overflow-hidden flex flex-col">
        <div className="flex-1 overflow-auto">
          {loading ? (
            <div className="h-full flex items-center justify-center text-xs text-gray-400 font-semibold">
              {zh ? '加载中...' : 'Loading leases...'}
            </div>
          ) : (
            <table className="nx-data-table text-left">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/40 text-[10px] font-bold text-gray-400 uppercase tracking-wider select-none">
                  <th className="pl-6 py-4">{zh ? '动态分配IP' : 'Assigned IP'}</th>
                  <th className="px-4 py-4">{zh ? 'MAC地址' : 'MAC Address'}</th>
                  <th className="px-4 py-4">{zh ? '终端主机名' : 'Client Hostname'}</th>
                  <th className="px-4 py-4">{zh ? 'DHCP 服务源' : 'DHCP Server'}</th>
                  <th className="px-4 py-4">{zh ? '租约状态' : 'Lease State'}</th>
                  <th className="px-4 py-4">{zh ? '租用生效时间' : 'Lease Started'}</th>
                  <th className="px-4 py-4">{zh ? '租用过期时间' : 'Lease Expires'}</th>
                  <th className="pr-6 py-4 text-right">{zh ? '操作' : 'Actions'}</th>
                </tr>
              </thead>
              <tbody>
                {paginatedLeases.length > 0 ? (
                  paginatedLeases.map((node) => (
                    <tr 
                      key={node.id} 
                      className="hover:bg-gray-50/50 transition-colors border-b border-gray-100 group"
                    >
                      <td className="pl-6 py-4 font-mono font-bold text-xs text-gray-800">{node.address}</td>
                      <td className="px-4 py-4 font-mono text-xs text-gray-600">{node.mac_address}</td>
                      <td className="px-4 py-4 text-xs font-semibold text-gray-500">{node.hostname || '-'}</td>
                      <td className="px-4 py-4 text-xs font-bold text-indigo-600">{node.dhcp_server}</td>
                      <td className="px-4 py-4">
                        <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-bold ${
                          node.lease_state === 'active' 
                            ? 'bg-emerald-50 text-emerald-600 border border-emerald-500/10' 
                            : 'bg-rose-50 text-rose-600 border border-rose-500/10'
                        }`}>
                          <span className={`w-1 h-1 rounded-full ${node.lease_state === 'active' ? 'bg-emerald-500' : 'bg-rose-500'}`} />
                          {node.lease_state.toUpperCase()}
                        </span>
                      </td>
                      <td className="px-4 py-4 font-mono text-[10px] text-gray-500">{node.lease_start || '-'}</td>
                      <td className="px-4 py-4 font-mono text-[10px] text-gray-500">{node.lease_end || '-'}</td>
                      <td className="pr-6 py-4 text-right">
                        <ActionIconGroup label={zh ? '租约操作' : 'Lease actions'} className="opacity-0 transition-opacity group-hover:opacity-100">
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
                    <td colSpan={8} className="py-12 text-center text-xs text-gray-400 font-medium">
                      {zh ? '当前无任何DHCP租约分配数据' : 'No active DHCP lease mappings found'}
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
            totalItems={totalLeases}
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
                    <h3 className="font-bold text-gray-900">{editingLease ? (zh ? '编辑租约' : 'Edit DHCP Lease') : (zh ? '登记租约' : 'Create DHCP Lease')}</h3>
                    <p className="text-xs text-gray-500 mt-0.5">{zh ? '输入动态分配IP的MAC物理地址绑定与有效期' : 'Enter MAC bindings and lease durations.'}</p>
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
                  {/* IP Address */}
                  <div className="space-y-1.5 col-span-2">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '分配 IP 地址 *' : 'Assigned IP Address *'}</label>
                    <input
                      type="text"
                      value={form.address}
                      onChange={(e) => setForm({ ...form, address: e.target.value })}
                      placeholder="e.g. 10.1.1.21"
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                  </div>

                  {/* MAC Address */}
                  <div className="space-y-1.5 col-span-2">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '客户端 MAC 物理地址 *' : 'Client MAC Address *'}</label>
                    <input
                      type="text"
                      value={form.mac_address}
                      onChange={(e) => setForm({ ...form, mac_address: e.target.value })}
                      placeholder="e.g. aa:bb:cc:dd:ee:ff"
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                  </div>

                  {/* Hostname */}
                  <div className="space-y-1.5 col-span-2">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '终端主机名' : 'Client Hostname'}</label>
                    <input
                      type="text"
                      value={form.hostname}
                      onChange={(e) => setForm({ ...form, hostname: e.target.value })}
                      placeholder="e.g. workstation-john"
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                  </div>

                  {/* DHCP Server */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? 'DHCP 服务源' : 'DHCP Server'}</label>
                    <input
                      type="text"
                      value={form.dhcp_server}
                      onChange={(e) => setForm({ ...form, dhcp_server: e.target.value })}
                      placeholder="e.g. Infoblox, Windows DHCP"
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                  </div>

                  {/* Lease State */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '租约状态' : 'Lease State'}</label>
                    <select
                      value={form.lease_state}
                      onChange={(e) => setForm({ ...form, lease_state: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    >
                      <option value="active">ACTIVE</option>
                      <option value="expired">EXPIRED</option>
                    </select>
                  </div>

                  {/* Lease Start */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '租约生效时间' : 'Lease Start'}</label>
                    <input
                      type="date"
                      value={form.lease_start}
                      onChange={(e) => setForm({ ...form, lease_start: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                  </div>

                  {/* Lease End */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '租约失效过期时间' : 'Lease Expires'}</label>
                    <input
                      type="date"
                      value={form.lease_end}
                      onChange={(e) => setForm({ ...form, lease_end: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
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
                <h3 className="text-base font-bold text-gray-900 mb-2">{zh ? '删除租约记录？' : 'Delete Lease?'}</h3>
                <p className="text-xs text-gray-500 leading-relaxed">
                  {zh ? '确定要手动删除这行DHCP客户端IP租约记录吗？' : 'Are you sure you want to remove this DHCP host lease record?'}
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

export default DHCPLeaseTab;
