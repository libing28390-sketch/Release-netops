import React, { useState, useEffect, useCallback } from 'react';
import {
  ShieldCheck,
  Plus,
  Trash2,
  Search,
  Pencil,
  X,
  PlusCircle,
  Link2,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import PageHero from '../../components/PageHero';
import Pagination from '../../components/Pagination';
import { ActionIconButton, ActionIconGroup } from '../../components/ui/ActionIconButton';

interface VIP {
  id: string;
  address: string;
  vip_type: string;
  device_id: string | null;
  device_name: string | null;
  backup_device_id: string | null;
  backup_device_name: string | null;
  interface_name: string;
  description: string;
  real_servers: string;
  status: string;
  tenant_id: string;
  tenant_name: string | null;
}

interface VIPManagementTabProps {
  language: string;
  t: (key: string) => string;
}

const VIPManagementTab: React.FC<VIPManagementTabProps> = ({ language, t }) => {
  const zh = language === 'zh';

  const [vips, setVips] = useState<VIP[]>([]);
  const [devices, setDevices] = useState<any[]>([]);
  const [tenants, setTenants] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('all');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [totalVips, setTotalVips] = useState(0);

  // Modals
  const [showAddEdit, setShowAddEdit] = useState(false);
  const [editingVip, setEditingVip] = useState<VIP | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<string | null>(null);

  // Form State
  const [form, setForm] = useState({
    address: '',
    vip_type: 'F5',
    device_id: '',
    backup_device_id: '',
    interface_name: '',
    real_servers: '',
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
      const [vipRes, devRes, tenantRes] = await Promise.all([
        fetch(`/api/ipam/vips?q=${encodeURIComponent(search.trim())}&vip_type=${encodeURIComponent(typeFilter)}&page=${page}&page_size=${pageSize}`, { headers: hdrs }),
        fetch('/api/devices?mode=light', { headers: hdrs }),
        fetch('/api/cmdb/tenants', { headers: hdrs }),
      ]);
      const unwrap = (j: any) => (Array.isArray(j) ? j : (j?.data ?? j?.items ?? []));
      if (vipRes.ok) {
        const payload = await vipRes.json();
        const data = payload?.data && !Array.isArray(payload.data) ? payload.data : payload;
        setVips(Array.isArray(data) ? data : (data?.items || []));
        setTotalVips(Array.isArray(data) ? data.length : Number(data?.total || 0));
      }
      if (devRes.ok) {
        setDevices(unwrap(await devRes.json()));
      }
      if (tenantRes.ok) setTenants(unwrap(await tenantRes.json()));
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [authHeaders, page, pageSize, search, typeFilter]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const openForm = (vipItem: VIP | null = null) => {
    setErrorMsg('');
    if (vipItem) {
      setEditingVip(vipItem);
      setForm({
        address: vipItem.address,
        vip_type: vipItem.vip_type,
        device_id: vipItem.device_id || '',
        backup_device_id: vipItem.backup_device_id || '',
        interface_name: vipItem.interface_name || '',
        real_servers: vipItem.real_servers || '',
        description: vipItem.description || '',
        status: vipItem.status || 'active',
        tenant_id: vipItem.tenant_id || 'tenant-default',
      });
    } else {
      setEditingVip(null);
      setForm({
        address: '',
        vip_type: 'F5',
        device_id: '',
        backup_device_id: '',
        interface_name: '',
        real_servers: '',
        description: '',
        status: 'active',
        tenant_id: 'tenant-default',
      });
    }
    setShowAddEdit(true);
  };

  const handleSave = async () => {
    setErrorMsg('');
    if (!form.address || !form.vip_type) {
      setErrorMsg(zh ? '请填写所有必填字段' : 'Please fill all required fields');
      return;
    }

    const payload = {
      ...form,
      device_id: form.device_id || null,
      backup_device_id: form.backup_device_id || null,
      tenant_id: form.tenant_id || 'tenant-default',
    };

    try {
      const url = editingVip ? `/api/ipam/vips/${editingVip.id}` : '/api/ipam/vips';
      const method = editingVip ? 'PUT' : 'POST';
      const res = await fetch(url, {
        method,
        headers: {
          'Content-Type': 'application/json',
          ...authHeaders(),
        },
        body: JSON.stringify(payload),
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
      const res = await fetch(`/api/ipam/vips/${id}`, {
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

  const getDeviceName = (devId: string) => {
    const dev = devices.find((d) => d.id === devId);
    return dev ? dev.hostname : devId;
  };

  const filteredVips = vips;
  const paginatedVips = vips;

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden px-6 py-5 space-y-4">
      <PageHero
        icon={ShieldCheck}
        title={zh ? 'Virtual IP (VIP) 虚拟IP管理' : 'Virtual IP (VIP) Management'}
        subtitle={zh ? '统一登记管理网络负载均衡、高可用冗余协议下的虚拟IP（VIP），并关联底层真实物理服务器(Real Servers)' : 'Manage Virtual IPs supporting HSRP, VRRP, Keepalived, or load balancers.'}
        actions={
          <button
            onClick={() => openForm(null)}
            className="flex items-center gap-1.5 px-4 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-600 hover:to-blue-700 text-white rounded-xl text-xs font-bold shadow-lg shadow-cyan-500/20 active:scale-95 transition-all"
          >
            <Plus size={14} />
            {zh ? '新增虚拟 IP' : 'Create VIP'}
          </button>
        }
        extras={
          <div className="flex items-center gap-3 w-full md:w-auto">
            {/* Type Filter */}
            <select
              value={typeFilter}
              onChange={(e) => { setTypeFilter(e.target.value); setPage(1); }}
              className="px-3.5 py-1.5 rounded-xl border border-black/5 bg-white text-xs font-semibold text-gray-500 outline-none"
            >
              <option value="all">{zh ? '所有高可用类型' : 'All VIP Types'}</option>
              <option value="F5">F5 LTM</option>
              <option value="HSRP">Cisco HSRP</option>
              <option value="VRRP">VRRP</option>
              <option value="Keepalived">Keepalived</option>
              <option value="Nginx">Nginx Reverse Proxy</option>
              <option value="SLB">Cloud SLB</option>
            </select>

            {/* Search Input */}
            <div className="relative w-full md:w-64">
              <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                value={search}
                onChange={(e) => { setSearch(e.target.value); setPage(1); }}
                placeholder={zh ? '搜索VIP地址、真实服务器...' : 'Search VIPs...'}
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
              {zh ? '加载中...' : 'Loading VIP configs...'}
            </div>
          ) : (
            <table className="nx-data-table text-left">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/40 text-[10px] font-bold text-gray-400 uppercase tracking-wider select-none">
                  <th className="pl-6 py-4">{zh ? '虚拟IP (VIP)' : 'Virtual IP'}</th>
                  <th className="px-4 py-4">{zh ? '高可用模式类型' : 'VIP Protocol Type'}</th>
                  <th className="px-4 py-4">{zh ? '绑定控制设备' : 'Bound Controller'}</th>
                  <th className="px-4 py-4">{zh ? '备用/Standby 设备' : 'Standby Device'}</th>
                  <th className="px-4 py-4">{zh ? '控制接口' : 'Interface'}</th>
                  <th className="px-4 py-4">{zh ? '物理服务器组 (Real Servers)' : 'Underlying Real Servers'}</th>
                  <th className="px-4 py-4">{zh ? '所属租户' : 'Tenant'}</th>
                  <th className="px-4 py-4">{zh ? '状态' : 'Status'}</th>
                  <th className="px-4 py-4">{zh ? '备注说明' : 'Description'}</th>
                  <th className="pr-6 py-4 text-right">{zh ? '操作' : 'Actions'}</th>
                </tr>
              </thead>
              <tbody>
                {paginatedVips.length > 0 ? (
                  paginatedVips.map((node) => (
                    <tr 
                      key={node.id} 
                      className="hover:bg-gray-50/50 transition-colors border-b border-gray-100 group"
                    >
                      <td className="pl-6 py-4 font-mono font-extrabold text-xs text-gray-800">{node.address}</td>
                      <td className="px-4 py-4">
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-cyan-50 text-cyan-600 border border-cyan-500/10">
                          {node.vip_type}
                        </span>
                      </td>
                      <td className="px-4 py-4 text-xs font-semibold text-gray-500">{node.device_id ? getDeviceName(node.device_id) : '-'}</td>
                      <td className="px-4 py-4 text-xs font-semibold text-gray-500">{node.backup_device_id ? getDeviceName(node.backup_device_id) : '-'}</td>
                      <td className="px-4 py-4 text-xs text-gray-600 font-semibold">{node.interface_name || '-'}</td>
                      <td className="px-4 py-4">
                        {node.real_servers ? (
                          <div className="flex items-center gap-1">
                            <Link2 size={12} className="text-gray-400" />
                            <span className="font-mono text-xs text-indigo-600 font-semibold bg-indigo-50/50 px-2 py-0.5 rounded-md">
                              {node.real_servers}
                            </span>
                          </div>
                        ) : (
                          '-'
                        )}
                      </td>
                      <td className="px-4 py-4 text-xs text-gray-500 font-medium">{node.tenant_name || '-'}</td>
                      <td className="px-4 py-4">
                        <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-emerald-50 text-emerald-600 border border-emerald-500/10`}>
                          <span className="w-1 h-1 rounded-full bg-emerald-500" />
                          {node.status.toUpperCase()}
                        </span>
                      </td>
                      <td className="px-4 py-4 text-xs text-gray-400 font-medium max-w-[150px] truncate">{node.description || '-'}</td>
                      <td className="pr-6 py-4 text-right">
                        <ActionIconGroup label={zh ? 'VIP 操作' : 'VIP actions'} className="opacity-0 transition-opacity group-hover:opacity-100">
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
                    <td colSpan={10} className="py-12 text-center text-xs text-gray-400 font-medium">
                      {zh ? '暂无高可用虚拟IP (VIP) 记录' : 'No Virtual IPs configured'}
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
            totalItems={totalVips}
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
                    <h3 className="font-bold text-gray-900">{editingVip ? (zh ? '编辑虚拟 IP' : 'Edit Virtual IP') : (zh ? '新增虚拟 IP' : 'Create Virtual IP')}</h3>
                    <p className="text-xs text-gray-500 mt-0.5">{zh ? '声明一个新的VIP并绑定网络设备控制器' : 'Create a new VIP bound to a network device controller.'}</p>
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
                  {/* VIP Address */}
                  <div className="space-y-1.5 col-span-2">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '虚拟 IP 地址 (VIP) *' : 'Virtual IP Address *'}</label>
                    <input
                      type="text"
                      value={form.address}
                      onChange={(e) => setForm({ ...form, address: e.target.value })}
                      placeholder="e.g. 10.1.1.100"
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                  </div>

                  {/* VIP Type Select */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '高可用技术模式 *' : 'VIP Mode *'}</label>
                    <select
                      value={form.vip_type}
                      onChange={(e) => setForm({ ...form, vip_type: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    >
                      <option value="F5">F5 LTM</option>
                      <option value="HSRP">Cisco HSRP</option>
                      <option value="VRRP">VRRP</option>
                      <option value="Keepalived">Keepalived</option>
                      <option value="Nginx">Nginx Proxy</option>
                      <option value="SLB">Cloud SLB</option>
                    </select>
                  </div>

                  {/* Controller Device Select */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '绑定控制主设备' : 'Bound Device'}</label>
                    <select
                      value={form.device_id}
                      onChange={(e) => setForm({ ...form, device_id: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    >
                      <option value="">{zh ? '请选择控制设备' : 'None'}</option>
                      {devices.map((d) => (
                        <option key={d.id} value={d.id}>{d.hostname} ({d.ip_address})</option>
                      ))}
                    </select>
                  </div>

                  {/* Backup / Standby Device Select */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '备用/Standby 设备' : 'Standby Device'}</label>
                    <select
                      value={form.backup_device_id}
                      onChange={(e) => setForm({ ...form, backup_device_id: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    >
                      <option value="">{zh ? '请选择备用设备' : 'None'}</option>
                      {devices.map((d) => (
                        <option key={d.id} value={d.id}>{d.hostname} ({d.ip_address})</option>
                      ))}
                    </select>
                  </div>

                  {/* Controller Interface */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '虚拟/物理控制接口' : 'Interface'}</label>
                    <input
                      type="text"
                      value={form.interface_name}
                      onChange={(e) => setForm({ ...form, interface_name: e.target.value })}
                      placeholder="e.g. VIP100"
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

                  {/* Real Server IPs */}
                  <div className="space-y-1.5 col-span-2">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '底层物理服务器 (Real Servers) IP' : 'Underlying Real Servers'}</label>
                    <textarea
                      value={form.real_servers}
                      onChange={(e) => setForm({ ...form, real_servers: e.target.value })}
                      placeholder={zh ? '例如：10.1.1.11, 10.1.1.12（多IP使用逗号/空格分隔）' : 'e.g. 10.1.1.11, 10.1.1.12'}
                      rows={2}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50 resize-none"
                    />
                  </div>

                  {/* Description */}
                  <div className="space-y-1.5 col-span-2">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '备注说明' : 'Description'}</label>
                    <textarea
                      value={form.description}
                      onChange={(e) => setForm({ ...form, description: e.target.value })}
                      placeholder={zh ? '在此输入负载分发的用途说明...' : 'VIP description...'}
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
                <h3 className="text-base font-bold text-gray-900 mb-2">{zh ? '删除虚拟 IP 记录？' : 'Delete VIP?'}</h3>
                <p className="text-xs text-gray-500 leading-relaxed">
                  {zh ? '确定要删除此负载均衡 VIP 虚拟IP配置记录吗？删除后关联的底层物理服务器映射也会一并清理。' : 'Are you sure you want to delete this Virtual IP? Relational servers mapped below it will also be cleared.'}
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

export default VIPManagementTab;
