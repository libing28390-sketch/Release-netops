import React, { useState, useEffect, useCallback, useRef } from 'react';
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
import { TableExportMenu } from '../../components/ui/TableExportMenu';
import { useEscapeClose } from '../../hooks/useEscapeClose';
import { buildVisibleIpamExportData, fetchAllIpamExportItems } from './ipamExport';

import { TableActionCell, TableActionHeader } from '../../components/ui/TableActionColumn';
interface VIP {
  id: string;
  revision: number;
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
  prefix_id: string | null;
  prefix_name?: string | null;
  prefix_cidr: string | null;
  address_space_id: string | null;
  address_space_name: string | null;
  scope_pending: boolean | number;
  tenant_name: string | null;
}

interface PrefixOption {
  id: string;
  prefix: string;
  name?: string;
}

interface PendingCreateRequest {
  fingerprint: string;
  key: string;
}

interface VIPManagementTabProps {
  language: string;
  t: (key: string) => string;
  prefixId?: string;
  prefixScope?: { id: string; prefix: string; name?: string; tenant_id?: string | null } | null;
}

const VIPManagementTab: React.FC<VIPManagementTabProps> = ({ language, t, prefixId = '', prefixScope = null }) => {
  const zh = language === 'zh';
  const tableRef = useRef<HTMLTableElement>(null);

  const [vips, setVips] = useState<VIP[]>([]);
  const [devices, setDevices] = useState<any[]>([]);
  const [prefixes, setPrefixes] = useState<PrefixOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [prefixLoadError, setPrefixLoadError] = useState('');
  const [prefixesLoading, setPrefixesLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('all');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [totalVips, setTotalVips] = useState(0);

  // Modals
  const [showAddEdit, setShowAddEdit] = useState(false);
  const [editingVip, setEditingVip] = useState<VIP | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<string | null>(null);
  useEscapeClose(showAddEdit, () => { setShowAddEdit(false); setEditingVip(null); });
  useEscapeClose(Boolean(showDeleteConfirm), () => setShowDeleteConfirm(null));

  // Form State
  const [form, setForm] = useState({
    prefix_id: prefixId,
    address: '',
    vip_type: 'F5',
    device_id: '',
    backup_device_id: '',
    interface_name: '',
    real_servers: '',
    description: '',
    status: 'active',
  });
  const [errorMsg, setErrorMsg] = useState('');
  const pendingCreateRequest = useRef<PendingCreateRequest | null>(null);

  const getCreateIdempotencyKey = (payload: unknown) => {
    const fingerprint = JSON.stringify(payload);
    if (!pendingCreateRequest.current || pendingCreateRequest.current.fingerprint !== fingerprint) {
      pendingCreateRequest.current = {
        fingerprint,
        key: globalThis.crypto?.randomUUID?.() || `ipam-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      };
    }
    return pendingCreateRequest.current.key;
  };

  const authHeaders = useCallback(() => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, []);

  const loadData = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    const hdrs = authHeaders();
    try {
      const vipQuery = new URLSearchParams({
        q: search.trim(),
        vip_type: typeFilter,
        page: String(page),
        page_size: String(pageSize),
      });
      if (prefixId) vipQuery.set('prefix_id', prefixId);
      const [vipRes, devRes] = await Promise.all([
        fetch(`/api/ipam/vips?${vipQuery.toString()}`, { headers: hdrs }),
        fetch('/api/devices?mode=light', { headers: hdrs }),
      ]);
      const unwrap = (j: any) => (Array.isArray(j) ? j : (j?.data ?? j?.items ?? []));
      if (vipRes.ok) {
        const payload = await vipRes.json();
        const data = payload?.data && !Array.isArray(payload.data) ? payload.data : payload;
        setVips(Array.isArray(data) ? data : (data?.items || []));
        setTotalVips(Array.isArray(data) ? data.length : Number(data?.total || 0));
      } else {
        setVips([]);
        setTotalVips(0);
        const error = await vipRes.json().catch(() => null);
        const detail = typeof error?.detail === 'string' ? error.detail : null;
        setLoadError(vipRes.status === 401
          ? (zh ? '登录已过期，请重新登录后重试。' : 'Your session has expired. Sign in and retry.')
          : vipRes.status === 403
            ? (zh ? '当前账号没有查看 VIP 的权限。' : 'You do not have permission to view VIPs.')
            : (detail || (zh ? '加载 VIP 列表失败，请重试。' : 'Failed to load VIPs. Please retry.')));
      }
      if (devRes.ok) {
        setDevices(unwrap(await devRes.json()));
      } else {
        setDevices([]);
        setLoadError((current) => current || (devRes.status === 401
          ? (zh ? '登录已过期，请重新登录后重试。' : 'Your session has expired. Sign in and retry.')
          : devRes.status === 403
            ? (zh ? '当前账号没有读取设备选项的权限。' : 'You do not have permission to load device options.')
            : (zh ? '加载设备选项失败。' : 'Failed to load device options.')));
      }
    } catch (e) {
      console.error(e);
      setLoadError(zh ? '加载 VIP 配置失败，请检查网络后重试。' : 'Failed to load VIP data. Check the connection and retry.');
    } finally {
      setLoading(false);
    }
  }, [authHeaders, page, pageSize, prefixId, search, typeFilter, zh]);

  const loadPrefixes = useCallback(async () => {
    if (prefixId) {
      setPrefixes(prefixScope ? [{
        id: prefixId,
        prefix: prefixScope.prefix,
        name: prefixScope.name,
      }] : []);
      setPrefixLoadError('');
      return;
    }

    setPrefixesLoading(true);
    setPrefixLoadError('');
    try {
      const items = await fetchAllIpamExportItems<PrefixOption>('/api/ipam/subnets', new URLSearchParams({ status: 'all' }));
      setPrefixes(items.map((item) => ({
        ...item,
        prefix: String(item.prefix || (item as PrefixOption & { prefix_cidr?: string }).prefix_cidr || ''),
      })));
    } catch (error) {
      console.error(error);
      setPrefixes([]);
      const message = error instanceof Error ? error.message : '';
      setPrefixLoadError(message.includes('403')
        ? (zh ? '当前账号没有查看可用网段的权限。' : 'You do not have permission to view available prefixes.')
        : message.includes('401')
          ? (zh ? '登录已过期，请重新登录后重试。' : 'Your session has expired. Sign in and retry.')
          : (zh ? '加载网段列表失败，请重试。' : 'Failed to load prefixes. Please retry.'));
    } finally {
      setPrefixesLoading(false);
    }
  }, [prefixId, prefixScope, zh]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    void loadPrefixes();
  }, [loadPrefixes]);

  useEffect(() => {
    setPage(1);
  }, [prefixId]);

  const openForm = (vipItem: VIP | null = null) => {
    setErrorMsg('');
    pendingCreateRequest.current = null;
    if (vipItem) {
      setEditingVip(vipItem);
      setForm({
        prefix_id: vipItem.prefix_id || prefixId || '',
        address: vipItem.address,
        vip_type: vipItem.vip_type,
        device_id: vipItem.device_id || '',
        backup_device_id: vipItem.backup_device_id || '',
        interface_name: vipItem.interface_name || '',
        real_servers: vipItem.real_servers || '',
        description: vipItem.description || '',
        status: vipItem.status || 'active',
      });
    } else {
      setEditingVip(null);
      setForm({
        prefix_id: prefixId || '',
        address: '',
        vip_type: 'F5',
        device_id: '',
        backup_device_id: '',
        interface_name: '',
        real_servers: '',
        description: '',
        status: 'active',
      });
    }
    setShowAddEdit(true);
  };

  const handleSave = async () => {
    setErrorMsg('');
    const selectedPrefixId = prefixId || form.prefix_id;
    if (prefixId && !prefixScope) {
      setErrorMsg(zh ? '当前网段尚未加载完成，请稍后重试。' : 'The current Prefix has not loaded yet. Retry in a moment.');
      return;
    }
    if (!selectedPrefixId) {
      setErrorMsg(zh ? '请选择明确的归属前缀' : 'Select an explicit Prefix for this VIP');
      return;
    }
    if (!form.address || !form.vip_type) {
      setErrorMsg(zh ? '请填写所有必填字段' : 'Please fill all required fields');
      return;
    }

    const payload = {
      ...form,
      prefix_id: selectedPrefixId,
      device_id: form.device_id || null,
      backup_device_id: form.backup_device_id || null,
      ...(editingVip ? { expected_revision: editingVip.revision } : {}),
    };

    try {
      const url = editingVip ? `/api/ipam/vips/${editingVip.id}` : '/api/ipam/vips';
      const method = editingVip ? 'PUT' : 'POST';
      const res = await fetch(url, {
        method,
        headers: {
          'Content-Type': 'application/json',
          ...authHeaders(),
          ...(!editingVip ? { 'Idempotency-Key': getCreateIdempotencyKey(payload) } : {}),
        },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        if (!editingVip) pendingCreateRequest.current = null;
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
    const vip = vips.find((item) => item.id === id);
    if (!vip) return;
    try {
      const query = new URLSearchParams({ expected_revision: String(vip.revision) });
      const res = await fetch(`/api/ipam/vips/${encodeURIComponent(id)}?${query.toString()}`, {
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
    return dev?.hostname || '-';
  };

  const getStatusPresentation = (status: string) => {
    const normalized = String(status || '').toLowerCase();
    if (normalized === 'active') return { badge: 'bg-emerald-50 text-emerald-600 border-emerald-500/10', dot: 'bg-emerald-500' };
    if (normalized === 'reserved' || normalized === 'standby') return { badge: 'bg-amber-50 text-amber-700 border-amber-500/10', dot: 'bg-amber-500' };
    if (normalized === 'deprecated' || normalized === 'released' || normalized === 'disabled') return { badge: 'bg-slate-100 text-slate-600 border-slate-300', dot: 'bg-slate-400' };
    return { badge: 'bg-slate-50 text-slate-600 border-slate-300', dot: 'bg-slate-400' };
  };

  const filteredVips = vips;
  const paginatedVips = vips;

  const exportData = useCallback(async () => {
    const params = new URLSearchParams({ q: search.trim(), vip_type: typeFilter, status: 'all' });
    if (prefixId) params.set('prefix_id', prefixId);
    const allVips = await fetchAllIpamExportItems<VIP>('/api/ipam/vips', params);
    const deviceName = (id: string | null, suppliedName: string | null) => suppliedName || (id ? devices.find((device) => device.id === id)?.hostname || '-' : '-');
    return buildVisibleIpamExportData(tableRef.current, [
      { header: zh ? '虚拟IP (VIP)' : 'Virtual IP', value: (vip) => vip.address },
      {
        header: zh ? '地址空间 / 前缀' : 'Address Space / Prefix',
        value: (vip) => vip.scope_pending || !vip.address_space_id
          ? (zh ? '范围待确认' : 'Scope pending')
          : `${vip.address_space_name || vip.address_space_id} · ${vip.prefix_cidr || vip.prefix_id || '-'}`,
      },
      { header: zh ? '高可用模式类型' : 'VIP Protocol Type', value: (vip) => vip.vip_type },
      { header: zh ? '绑定控制设备' : 'Bound Controller', value: (vip) => deviceName(vip.device_id, vip.device_name) },
      { header: zh ? '备用/Standby 设备' : 'Standby Device', value: (vip) => deviceName(vip.backup_device_id, vip.backup_device_name) },
      { header: zh ? '控制接口' : 'Interface', value: (vip) => vip.interface_name || '-' },
      { header: zh ? '物理服务器组 (Real Servers)' : 'Underlying Real Servers', value: (vip) => vip.real_servers || '-' },
      { header: zh ? '状态' : 'Status', value: (vip) => vip.status.toUpperCase() },
      { header: zh ? '备注说明' : 'Description', value: (vip) => vip.description || '-' },
    ], allVips);
  }, [devices, prefixId, search, typeFilter, zh]);

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden px-6 py-5 space-y-4">
      <PageHero
        icon={ShieldCheck}
        title={zh ? 'Virtual IP (VIP) 虚拟IP管理' : 'Virtual IP (VIP) Management'}
        subtitle={zh ? '统一登记管理网络负载均衡、高可用冗余协议下的虚拟IP（VIP），并关联底层真实物理服务器(Real Servers)' : 'Manage Virtual IPs supporting HSRP, VRRP, Keepalived, or load balancers.'}
        actions={
          <div className="flex items-center gap-2">
            <TableExportMenu tableRef={tableRef} exportData={exportData} filename="ipam-vips" language={zh ? 'zh' : 'en'} disabled={loading || paginatedVips.length === 0} />
            <button
              onClick={() => openForm(null)}
              disabled={Boolean(prefixId && !prefixScope)}
              title={prefixId && !prefixScope ? (zh ? '正在加载当前网段…' : 'Loading current prefix…') : undefined}
              className="flex items-center gap-1.5 px-4 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-600 hover:to-blue-700 text-white rounded-xl text-xs font-bold shadow-lg shadow-cyan-500/20 active:scale-95 transition-all"
            >
              <Plus size={14} />
              {zh ? '新增虚拟 IP' : 'Create VIP'}
            </button>
          </div>
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
              <option value="anycast">{zh ? '任播 Anycast' : 'Anycast'}</option>
              <option value="Keepalived">Keepalived</option>
              <option value="Nginx">Nginx Reverse Proxy</option>
              <option value="SLB">Cloud SLB</option>
            </select>

            {/* Search Input */}
            <div className="relative w-full md:w-64">
              <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="search"
                value={search}
                onChange={(e) => { setSearch(e.target.value); setPage(1); }}
                placeholder={zh ? '搜索VIP地址、真实服务器...' : 'Search VIPs...'}
                className="w-full pl-10 pr-4 py-1.5 text-xs rounded-xl border border-black/5 bg-gray-50/50 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium"
              />
            </div>
          </div>
        }
      />

      {loadError && (
        <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2 text-xs font-semibold text-rose-700">
          <span>{loadError}</span>
          <button type="button" onClick={() => void loadData()} disabled={loading} className="shrink-0 rounded-lg bg-white px-3 py-1.5 text-rose-700 shadow-sm hover:bg-rose-100 disabled:opacity-50">
            {zh ? '重试' : 'Retry'}
          </button>
        </div>
      )}

      {/* Main Table Card */}
      <div className="flex-1 min-h-0 bg-white rounded-[28px] border border-black/5 shadow-[0_16px_36px_rgba(11,35,64,0.06)] overflow-hidden flex flex-col">
        <div className="flex-1 overflow-auto">
          {loading ? (
            <div className="h-full flex items-center justify-center text-xs text-gray-400 font-semibold">
              {zh ? '加载中...' : 'Loading VIP configs...'}
            </div>
          ) : (
            <table ref={tableRef} className="nx-data-table text-left">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/40 text-[10px] font-bold text-gray-400 uppercase tracking-wider select-none">
                  <th className="pl-6 py-4">{zh ? '虚拟IP (VIP)' : 'Virtual IP'}</th>
                  <th className="px-4 py-4">{zh ? '地址空间 / 前缀' : 'Address Space / Prefix'}</th>
                  <th className="px-4 py-4">{zh ? '高可用模式类型' : 'VIP Protocol Type'}</th>
                  <th className="px-4 py-4">{zh ? '绑定控制设备' : 'Bound Controller'}</th>
                  <th className="px-4 py-4">{zh ? '备用/Standby 设备' : 'Standby Device'}</th>
                  <th className="px-4 py-4">{zh ? '控制接口' : 'Interface'}</th>
                  <th className="px-4 py-4">{zh ? '物理服务器组 (Real Servers)' : 'Underlying Real Servers'}</th>
                  <th className="px-4 py-4">{zh ? '状态' : 'Status'}</th>
                  <th className="px-4 py-4">{zh ? '备注说明' : 'Description'}</th>
                  <TableActionHeader className="pr-6 py-4 text-right">{zh ? '操作' : 'Actions'}</TableActionHeader>
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
                        {node.scope_pending || !node.address_space_id ? (
                          <span className="inline-flex rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-800">
                            {zh ? '范围待确认' : 'Scope pending'}
                          </span>
                        ) : (
                          <div className="space-y-0.5 text-[10px]">
                            <div className="font-semibold text-gray-700">{node.address_space_name || node.address_space_id}</div>
                            <div className="font-mono text-gray-500">{node.prefix_cidr || node.prefix_id || '-'}</div>
                          </div>
                        )}
                      </td>
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
                      <td className="px-4 py-4">
                        <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full border text-[10px] font-bold ${getStatusPresentation(node.status).badge}`}>
                          <span className={`w-1 h-1 rounded-full ${getStatusPresentation(node.status).dot}`} />
                          {node.status.toUpperCase()}
                        </span>
                      </td>
                      <td className="px-4 py-4 text-xs text-gray-400 font-medium max-w-[150px] truncate">{node.description || '-'}</td>
                      <TableActionCell className="pr-6 py-4 text-right">
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
                      </TableActionCell>
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
                  <div className="space-y-1.5 col-span-2">
                    <label htmlFor="vip-prefix" className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">
                      {zh ? '归属前缀 *' : 'Parent Prefix *'}
                    </label>
                    {prefixId ? (
                      <div id="vip-prefix" className="rounded-xl border border-cyan-100 bg-cyan-50/60 px-4 py-2.5 text-xs font-semibold text-cyan-800">
                        {prefixScope?.prefix || prefixLoadError || (zh ? '正在加载当前网段…' : 'Loading current Prefix…')}
                      </div>
                    ) : (
                      <>
                        <select
                          id="vip-prefix"
                          aria-label={zh ? '归属前缀' : 'Parent Prefix'}
                          value={form.prefix_id}
                          disabled={prefixesLoading || Boolean(prefixLoadError)}
                          onChange={(event) => setForm((current) => ({ ...current, prefix_id: event.target.value }))}
                          className="w-full rounded-xl border border-gray-150 bg-gray-50/50 px-4 py-2.5 text-xs font-medium outline-none transition-all focus:border-cyan-400 focus:bg-white disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          <option value="">{zh ? '请选择明确的归属前缀' : 'Select an explicit Prefix'}</option>
                          {prefixes.map((prefix) => (
                            <option key={prefix.id} value={prefix.id}>
                              {prefix.name ? `${prefix.name} · ` : ''}{prefix.prefix}
                            </option>
                          ))}
                        </select>
                        {prefixesLoading && <p role="status" className="ml-1 text-[10px] text-gray-500">{zh ? '正在加载网段…' : 'Loading prefixes…'}</p>}
                        {prefixLoadError && (
                          <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-[10px] font-semibold text-rose-700">
                            <span>{prefixLoadError}</span>
                            <button type="button" onClick={() => void loadPrefixes()} disabled={prefixesLoading} className="rounded-lg bg-white px-2.5 py-1 text-rose-700 shadow-sm disabled:opacity-50">
                              {zh ? '重试' : 'Retry'}
                            </button>
                          </div>
                        )}
                      </>
                    )}
                    {editingVip && (editingVip.scope_pending || !editingVip.address_space_id) && (
                      <p role="status" className="ml-1 text-[10px] font-semibold text-amber-700">
                        {zh ? '此 VIP 尚未确认地址空间。请选择有权限的 Prefix 后保存，系统会按该前缀明确归属。' : 'This VIP has no confirmed scope. Select an authorized Prefix and save to establish its scope.'}
                      </p>
                    )}
                    {!prefixId && form.prefix_id && prefixes.find((prefix) => prefix.id === form.prefix_id) && (
                      <p className="ml-1 text-[10px] text-cyan-700">
                        {zh ? `VIP 地址必须位于 ${prefixes.find((prefix) => prefix.id === form.prefix_id)?.prefix} 内。` : `The VIP address must be inside ${prefixes.find((prefix) => prefix.id === form.prefix_id)?.prefix}.`}
                      </p>
                    )}
                  </div>

                  {/* VIP Address */}
                  <div className="space-y-1.5 col-span-2">
                    <label htmlFor="vip-address" className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '虚拟 IP 地址 (VIP) *' : 'Virtual IP Address *'}</label>
                    <input
                      id="vip-address"
                      type="text"
                      value={form.address}
                      onChange={(e) => setForm({ ...form, address: e.target.value })}
                      placeholder="e.g. 10.1.1.100"
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                    {prefixScope && (
                      <p className="ml-1 text-[10px] text-cyan-700">
                        {zh ? `当前工作网段：${prefixScope.prefix}；VIP 地址需要位于该网段内` : `Current prefix: ${prefixScope.prefix}; the VIP address must be within this range`}
                      </p>
                    )}
                  </div>

                  {/* VIP Type Select */}
                  <div className="space-y-1.5">
                    <label htmlFor="ipam-vip-type" className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '高可用技术模式 *' : 'VIP Mode *'}</label>
                    <select
                      id="ipam-vip-type"
                      value={form.vip_type}
                      onChange={(e) => setForm({ ...form, vip_type: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    >
                      <option value="F5">F5 LTM</option>
                      <option value="HSRP">Cisco HSRP</option>
                      <option value="VRRP">VRRP</option>
                      <option value="anycast">{zh ? '任播 Anycast' : 'Anycast'}</option>
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
