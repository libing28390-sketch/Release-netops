import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  MapPin,
  Plus,
  Trash2,
  Search,
  Pencil,
  AlertTriangle,
  Settings,
  X,
  Router,
  PlusCircle,
  Eye,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import PageHero from '../../components/PageHero';
import Pagination from '../../components/Pagination';
import { useLocation, useNavigate } from 'react-router-dom';

interface IPAddress {
  id: string;
  subnet_id: string;
  address: string;
  hostname: string;
  device_id: string;
  interface_name: string;
  mac_address: string;
  device_type: string;
  status: string;
  description: string;
  last_seen: string;
  created_at: string;
  updated_at: string;
}

interface Prefix {
  id: string;
  prefix: string;
  name: string;
}

interface IPAddressTabProps {
  language: string;
  t: (key: string) => string;
}

// IP 角色类型（含迁移自动产生的 transit / host）
const ROLE_OPTIONS: { value: string; zh: string; en: string }[] = [
  { value: 'gateway', zh: '网关', en: 'Gateway' },
  { value: 'server', zh: '服务器', en: 'Server' },
  { value: 'device', zh: '网络设备', en: 'Network Device' },
  { value: 'vip', zh: 'VIP', en: 'VIP' },
  { value: 'physical', zh: '物理接口', en: 'Physical Interface' },
  { value: 'loopback', zh: '环回接口', en: 'Loopback Interface' },
  { value: 'vlan', zh: 'VLAN接口', en: 'VLAN Interface' },
  { value: 'tunnel', zh: '隧道接口', en: 'Tunnel Interface' },
  { value: 'transit', zh: '互联接口', en: 'Transit Link' },
  { value: 'host', zh: '普通主机', en: 'Host' },
];

// IP 地址状态
const STATUS_OPTIONS: { value: string; zh: string; en: string }[] = [
  { value: 'active', zh: '使用中', en: 'Active' },
  { value: 'reserved', zh: '已保留', en: 'Reserved' },
  { value: 'deprecated', zh: '已弃用', en: 'Deprecated' },
];

// 可搜索的绑定设备下拉
const roleLabel = (v: string, zh: boolean): string => {
  const o = ROLE_OPTIONS.find((x) => x.value === v);
  return o ? (zh ? o.zh : o.en) : (v || '').toUpperCase();
};

const statusLabel = (v: string, zh: boolean): string => {
  const o = STATUS_OPTIONS.find((x) => x.value === v);
  return o ? (zh ? o.zh : o.en) : (v || '').toUpperCase();
};

const DeviceSearchSelect: React.FC<{
  devices: any[];
  value: string;
  onChange: (id: string) => void;
  zh: boolean;
}> = ({ devices, value, onChange, zh }) => {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const wrapRef = useRef<HTMLDivElement>(null);

  const selected = devices.find((d) => d.id === value);
  const display = selected ? `${selected.hostname} (${selected.ip_address})` : '';

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
        setQuery('');
      }
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  const filtered = query.trim()
    ? devices.filter((d) => {
        const q = query.toLowerCase();
        return (
          (d.hostname || '').toLowerCase().includes(q) ||
          (d.ip_address || '').toLowerCase().includes(q)
        );
      })
    : devices;

  return (
    <div className="relative" ref={wrapRef}>
      <input
        type="text"
        value={open ? query : display}
        onChange={(e) => {
          setQuery(e.target.value);
          if (!open) setOpen(true);
        }}
        onFocus={() => {
          setOpen(true);
          setQuery('');
        }}
        placeholder={zh ? '搜索主机名 / IP 选择设备...' : 'Search device by name / IP...'}
        className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
      />
      {open && (
        <div className="absolute z-50 mt-1 w-full max-h-56 overflow-auto bg-white border border-gray-150 rounded-xl shadow-xl py-1">
          <div
            onClick={() => {
              onChange('');
              setOpen(false);
              setQuery('');
            }}
            className="px-4 py-2 text-xs text-gray-400 hover:bg-gray-50 cursor-pointer"
          >
            {zh ? '— 不绑定设备 —' : '— None —'}
          </div>
          {filtered.map((d) => (
            <div
              key={d.id}
              onClick={() => {
                onChange(d.id);
                setOpen(false);
                setQuery('');
              }}
              className={`px-4 py-2 text-xs cursor-pointer hover:bg-cyan-50 ${
                d.id === value ? 'bg-cyan-50/60 font-bold text-cyan-700' : 'text-gray-700'
              }`}
            >
              {d.hostname} <span className="text-gray-400">({d.ip_address})</span>
            </div>
          ))}
          {filtered.length === 0 && (
            <div className="px-4 py-3 text-xs text-gray-400 text-center">
              {zh ? '无匹配设备' : 'No matching device'}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const IPAddressTab: React.FC<IPAddressTabProps> = ({ language, t }) => {
  const location = useLocation();
  const navigate = useNavigate();
  const zh = language === 'zh';

  // Get search params
  const params = new URLSearchParams(location.search);
  const prefixIdParam = params.get('prefix_id') || '';

  const [addresses, setAddresses] = useState<IPAddress[]>([]);
  const [prefixes, setPrefixes] = useState<Prefix[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [typeFilter, setTypeFilter] = useState('all');

  // Lookup data
  const [devices, setDevices] = useState<any[]>([]);
  const [selectedPrefixId, setSelectedPrefixId] = useState(prefixIdParam);
  const [activePrefix, setActivePrefix] = useState<Prefix | null>(null);

  // Modals
  const [showAddEdit, setShowAddEdit] = useState(false);
  const [editingIP, setEditingIP] = useState<IPAddress | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<string | null>(null);

  // Form State
  const [form, setForm] = useState({
    subnet_id: '', // selected prefix ID
    address: '',
    hostname: '',
    device_id: '',
    interface_name: '',
    mac_address: '',
    device_type: 'server',
    status: 'active',
    description: '',
  });
  const [errorMsg, setErrorMsg] = useState('');

  const authHeaders = useCallback(() => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, []);

  // Fetch lookups
  const fetchLookups = useCallback(async () => {
    const hdrs = authHeaders();
    try {
      // Fetch Prefixes
      const prefRes = await fetch('/api/ipam/subnets', { headers: hdrs });
      if (prefRes.ok) {
        const data = await prefRes.json();
        setPrefixes(data);
        if (prefixIdParam) {
          const matched = data.find((p: Prefix) => p.id === prefixIdParam);
          if (matched) setActivePrefix(matched);
        }
      }

      // Fetch Network Devices
      const devRes = await fetch('/api/devices', { headers: hdrs });
      if (devRes.ok) {
        const raw = await devRes.json();
        setDevices(Array.isArray(raw) ? raw : (raw.items || []));
      }
    } catch (e) {
      console.error(e);
    }
  }, [authHeaders, prefixIdParam]);

  const loadData = useCallback(async () => {
    setLoading(true);
    const hdrs = authHeaders();
    try {
      let url = '/api/ipam/subnets';
      
      // If we have selectedPrefixId, fetch addresses for that prefix
      if (selectedPrefixId) {
        url = `/api/ipam/subnets/${selectedPrefixId}/addresses`;
        const res = await fetch(url, { headers: hdrs });
        if (res.ok) {
          setAddresses(await res.json());
        }
      } else {
        // Fallback: fetch addresses of the first prefix if none selected, or all if we had a global endpoint.
        // Since original API list_addresses takes subnet_id, we fetch all prefixes first, then load their IPs.
        const prefRes = await fetch('/api/ipam/subnets', { headers: hdrs });
        if (prefRes.ok) {
          const prefData = await prefRes.json();
          if (prefData.length > 0) {
            setSelectedPrefixId(prefData[0].id);
            setActivePrefix(prefData[0]);
            const res = await fetch(`/api/ipam/subnets/${prefData[0].id}/addresses`, { headers: hdrs });
            if (res.ok) {
              setAddresses(await res.json());
            }
          }
        }
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [selectedPrefixId, authHeaders]);

  useEffect(() => {
    fetchLookups();
  }, [fetchLookups]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Handle prefix switch
  const handlePrefixChange = (id: string) => {
    setSelectedPrefixId(id);
    const matched = prefixes.find((p) => p.id === id) || null;
    setActivePrefix(matched);
    navigate(`/ipam/ips?prefix_id=${id}`);
  };

  // Filtered IP list
  const filteredAddresses = useMemo(() => {
    return addresses.filter((item) => {
      const matchesSearch =
        item.address.includes(search) ||
        (item.hostname && item.hostname.toLowerCase().includes(search.toLowerCase())) ||
        (item.interface_name && item.interface_name.toLowerCase().includes(search.toLowerCase())) ||
        (item.description && item.description.toLowerCase().includes(search.toLowerCase()));

      const matchesStatus = statusFilter === 'all' || item.status === statusFilter;
      const matchesType = typeFilter === 'all' || item.device_type === typeFilter;

      return matchesSearch && matchesStatus && matchesType;
    });
  }, [addresses, search, statusFilter, typeFilter]);

  // Pagination states
  const [page, setPage] = useState(1);
  const pageSize = 10;
  const paginatedAddresses = filteredAddresses.slice((page - 1) * pageSize, page * pageSize);

  // Form handling
  const openForm = (ipItem: IPAddress | null = null) => {
    setErrorMsg('');
    if (ipItem) {
      setEditingIP(ipItem);
      setForm({
        subnet_id: ipItem.subnet_id || selectedPrefixId,
        address: ipItem.address,
        hostname: ipItem.hostname || '',
        device_id: ipItem.device_id || '',
        interface_name: ipItem.interface_name || '',
        mac_address: ipItem.mac_address || '',
        device_type: ipItem.device_type || 'server',
        status: ipItem.status || 'active',
        description: ipItem.description || '',
      });
    } else {
      setEditingIP(null);
      setForm({
        subnet_id: selectedPrefixId,
        address: '',
        hostname: '',
        device_id: '',
        interface_name: '',
        mac_address: '',
        device_type: 'server',
        status: 'active',
        description: '',
      });
    }
    setShowAddEdit(true);
  };

  const handleGetSuggestedIP = async () => {
    setErrorMsg('');
    if (!form.subnet_id) {
      setErrorMsg(zh ? '请先选择一个归属前缀网段' : 'Please select an allocating prefix first');
      return;
    }
    try {
      const res = await fetch(`/api/ipam/subnets/${form.subnet_id}/next-available-ip`, { headers: authHeaders() });
      if (res.ok) {
        const data = await res.json();
        setForm((prev) => ({ ...prev, address: data.next_available_ip }));
      } else {
        const err = await res.json().catch(() => null);
        setErrorMsg(err?.detail || (zh ? '无法获取推荐 IP，网段可能已满。' : 'Failed to fetch suggested IP. Subnet might be full.'));
      }
    } catch (e) {
      setErrorMsg(zh ? '获取推荐 IP 出错' : 'Error fetching suggested IP');
    }
  };

  const handleSave = async () => {
    setErrorMsg('');
    if (!form.address) {
      setErrorMsg(zh ? 'IP地址是必填项' : 'IP address is required');
      return;
    }
    if (!form.subnet_id) {
      setErrorMsg(zh ? '必须选择归属前缀' : '归属前缀是必选项');
      return;
    }

    try {
      const url = editingIP ? `/api/ipam/addresses/${editingIP.id}` : `/api/ipam/subnets/${form.subnet_id}/addresses`;
      const method = editingIP ? 'PUT' : 'POST';
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
      setErrorMsg(zh ? '网络请求出错' : 'Network request error');
    }
  };

  const handleDelete = async (id: string) => {
    try {
      const res = await fetch(`/api/ipam/addresses/${id}`, {
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

  // Find hostname for device selection
  const getDeviceName = (devId: string) => {
    const dev = devices.find((d) => d.id === devId);
    return dev ? dev.hostname : devId;
  };

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden px-6 py-5 space-y-4">
      <PageHero
        icon={MapPin}
        title={zh ? 'IP地址分配管理' : 'IP Address Management'}
        subtitle={zh ? '精细管理每一个网段内的IP分配，登记设备绑定接口、类型、MAC与历史状态' : 'Track individual host allocations, interface attachments, and MAC mappings.'}
        actions={
          <button
            onClick={() => openForm(null)}
            disabled={!selectedPrefixId}
            className={`flex items-center gap-1.5 px-4 py-2 text-white rounded-xl text-xs font-bold shadow-lg transition-all ${
              selectedPrefixId 
                ? 'bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-600 hover:to-blue-700 shadow-cyan-500/20 active:scale-95 cursor-pointer'
                : 'bg-gray-200 cursor-not-allowed shadow-none'
            }`}
          >
            <Plus size={14} />
            {zh ? '分配IP地址' : 'Allocate IP'}
          </button>
        }
        extras={
          <div className="flex flex-wrap items-center gap-3 w-full md:w-auto">
            {/* Prefix Selector */}
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold text-gray-400 uppercase tracking-wider">{zh ? '当前网段' : 'Prefix'}</span>
              <select
                value={selectedPrefixId}
                onChange={(e) => handlePrefixChange(e.target.value)}
                className="px-3.5 py-1.5 rounded-xl border border-black/5 bg-white text-xs font-bold text-gray-700 outline-none focus:border-cyan-400 focus:shadow-sm transition-all"
              >
                {prefixes.map((p) => (
                  <option key={p.id} value={p.id}>{p.prefix} {p.name ? `(${p.name})` : ''}</option>
                ))}
              </select>
            </div>

            {/* Filters */}
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="px-3 py-1.5 rounded-xl border border-black/5 bg-white text-xs font-semibold text-gray-500 outline-none transition-all"
            >
              <option value="all">{zh ? '所有状态' : 'All Status'}</option>
              {STATUS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{zh ? o.zh : o.en}</option>
              ))}
            </select>

            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="px-3 py-1.5 rounded-xl border border-black/5 bg-white text-xs font-semibold text-gray-500 outline-none transition-all"
            >
              <option value="all">{zh ? '所有类型' : 'All Types'}</option>
              {ROLE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{zh ? o.zh : o.en}</option>
              ))}
            </select>

            {/* Search Input */}
            <div className="relative w-full md:w-56">
              <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                value={search}
                onChange={(e) => { setSearch(e.target.value); setPage(1); }}
                placeholder={zh ? '搜索IP、主机名、接口...' : 'Search IP, hostname...'}
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
              {zh ? '加载中...' : 'Loading IP allocations...'}
            </div>
          ) : (
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/40 text-[10px] font-bold text-gray-400 uppercase tracking-wider select-none">
                  <th className="pl-6 py-4">{zh ? 'IP地址' : 'IP Address'}</th>
                  <th className="px-4 py-4">{zh ? '类型' : 'Role Type'}</th>
                  <th className="px-4 py-4">{zh ? '主机名 / 域名' : 'DNS Hostname'}</th>
                  <th className="px-4 py-4">{zh ? '绑定设备' : 'Bound Device'}</th>
                  <th className="px-4 py-4">{zh ? '接口' : 'Interface'}</th>
                  <th className="px-4 py-4">{zh ? 'MAC地址' : 'MAC Address'}</th>
                  <th className="px-4 py-4">{zh ? '状态' : 'Status'}</th>
                  <th className="px-4 py-4">{zh ? '备注描述' : 'Description'}</th>
                  <th className="px-4 py-4">{zh ? '发现时间' : 'Last Seen'}</th>
                  <th className="pr-6 py-4 text-right">{zh ? '操作' : 'Actions'}</th>
                </tr>
              </thead>
              <tbody>
                {paginatedAddresses.length > 0 ? (
                  paginatedAddresses.map((node) => (
                    <tr 
                      key={node.id} 
                      className="hover:bg-gray-50/50 transition-colors border-b border-gray-100 group"
                    >
                      <td className="pl-6 py-4 font-mono font-bold text-xs text-gray-800">{node.address}</td>
                      <td className="px-4 py-4">
                        <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold ${
                          node.device_type === 'gateway' 
                            ? 'bg-amber-50 text-amber-600 border border-amber-500/10' 
                            : node.device_type === 'server' 
                            ? 'bg-blue-50 text-blue-600 border border-blue-500/10' 
                            : node.device_type === 'device' 
                            ? 'bg-purple-50 text-purple-600 border border-purple-500/10' 
                            : node.device_type === 'vip'
                            ? 'bg-pink-50 text-pink-600 border border-pink-500/10'
                            : node.device_type === 'loopback'
                            ? 'bg-cyan-50 text-cyan-600 border border-cyan-500/10'
                            : 'bg-emerald-50 text-emerald-600 border border-emerald-500/10'
                        }`}>
                          {roleLabel(node.device_type, zh)}
                        </span>
                      </td>
                      <td className="px-4 py-4 text-xs font-semibold text-gray-500">{node.hostname || '-'}</td>
                      <td className="px-4 py-4 text-xs text-cyan-600 font-bold hover:underline cursor-pointer">
                        {node.device_id ? getDeviceName(node.device_id) : '-'}
                      </td>
                      <td className="px-4 py-4 text-xs text-gray-600 font-semibold">{node.interface_name || '-'}</td>
                      <td className="px-4 py-4 font-mono text-xs text-gray-500">{node.mac_address || '-'}</td>
                      <td className="px-4 py-4">
                        <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold ${
                          node.status === 'active' 
                            ? 'bg-emerald-50 text-emerald-600 border border-emerald-500/10' 
                            : node.status === 'reserved' 
                            ? 'bg-amber-50 text-amber-600 border border-amber-500/10' 
                            : 'bg-rose-50 text-rose-600 border border-rose-500/10'
                        }`}>
                          <span className={`w-1 h-1 rounded-full ${
                            node.status === 'active' ? 'bg-emerald-500' : node.status === 'reserved' ? 'bg-amber-500' : 'bg-rose-500'
                          }`} />
                          {statusLabel(node.status, zh)}
                        </span>
                      </td>
                      <td className="px-4 py-4 text-xs text-gray-400 font-medium max-w-[150px] truncate">{node.description || '-'}</td>
                      <td className="px-4 py-4 font-mono text-[10px] text-gray-400">{node.last_seen ? node.last_seen.split('T')[0] : '-'}</td>
                      <td className="pr-6 py-4 text-right">
                        <div className="flex items-center justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            onClick={() => openForm(node)}
                            title={zh ? '编辑' : 'Edit'}
                            className="p-1 rounded-md text-gray-400 hover:text-cyan-600 hover:bg-cyan-50 transition-all"
                          >
                            <Pencil size={14} />
                          </button>
                          <button
                            onClick={() => setShowDeleteConfirm(node.id)}
                            title={zh ? '删除' : 'Delete'}
                            className="p-1 rounded-md text-gray-400 hover:text-rose-600 hover:bg-rose-50 transition-all"
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={10} className="py-12 text-center text-xs text-gray-400 font-medium">
                      {zh ? '当前网段无已分配IP记录' : 'No IP address registered in this prefix block'}
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
            totalItems={filteredAddresses.length}
            itemsPerPage={pageSize}
            onPageChange={setPage}
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
              {/* Header */}
              <div className="px-6 py-5 border-b border-gray-100 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-2xl bg-cyan-50 flex items-center justify-center text-cyan-600">
                    <PlusCircle size={20} />
                  </div>
                  <div>
                    <h3 className="font-bold text-gray-900">{editingIP ? (zh ? '编辑IP记录' : 'Edit IP Address') : (zh ? '分配IP地址' : 'Allocate IP Address')}</h3>
                    <p className="text-xs text-gray-500 mt-0.5">{zh ? '在此登记一个网段IP，并可与资产、机柜设备进行绑定' : 'Register an IP allocation and bind with hardware assets.'}</p>
                  </div>
                </div>
                <button onClick={() => setShowAddEdit(false)} className="p-1.5 rounded-lg hover:bg-gray-50 transition-colors text-gray-400">
                  <X size={16} />
                </button>
              </div>

              {/* Form Content */}
              <div className="flex-1 overflow-y-auto p-6 space-y-4">
                {errorMsg && (
                  <div className="p-3.5 rounded-2xl bg-rose-50 border border-rose-200 text-xs font-semibold text-rose-600">
                    {errorMsg}
                  </div>
                )}

                <div className="grid grid-cols-2 gap-4">
                  {/* Selected Prefix info */}
                  <div className="col-span-2 p-3 bg-cyan-50/50 rounded-2xl border border-cyan-500/10 flex justify-between items-center text-xs">
                    <span className="font-bold text-gray-400">{zh ? '归属前缀网段' : 'Allocating Under Prefix'}</span>
                    <span className="font-mono font-bold text-cyan-700 bg-cyan-500/10 px-2 py-0.5 rounded-md">
                      {activePrefix ? activePrefix.prefix : ''}
                    </span>
                  </div>

                  {/* IP Address */}
                  <div className="space-y-1.5 col-span-2">
                    <div className="flex justify-between items-center">
                      <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? 'IP地址 *' : 'IP Address *'}</label>
                      {!editingIP && (
                        <button
                          type="button"
                          onClick={handleGetSuggestedIP}
                          className="text-[10px] font-extrabold text-cyan-600 hover:text-cyan-800 transition-colors"
                        >
                          {zh ? '获取推荐 IP' : 'Get Suggested IP'}
                        </button>
                      )}
                    </div>
                    <input
                      type="text"
                      value={form.address}
                      onChange={(e) => setForm({ ...form, address: e.target.value })}
                      placeholder="e.g. 10.1.1.10"
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                      disabled={editingIP !== null}
                    />
                  </div>

                  {/* Hostname */}
                  <div className="space-y-1.5 col-span-2">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? 'DNS 主机名 / 域名' : 'DNS Hostname'}</label>
                    <input
                      type="text"
                      value={form.hostname}
                      onChange={(e) => setForm({ ...form, hostname: e.target.value })}
                      placeholder="e.g. app-prod-01.local"
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                  </div>

                  {/* Bound Device (searchable) */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '绑定网络设备' : 'Bound Device'}</label>
                    <DeviceSearchSelect
                      devices={devices}
                      value={form.device_id}
                      onChange={(id) => setForm({ ...form, device_id: id })}
                      zh={zh}
                    />
                  </div>

                  {/* Interface Name */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '物理 / 虚拟接口' : 'Interface'}</label>
                    <input
                      type="text"
                      value={form.interface_name}
                      onChange={(e) => setForm({ ...form, interface_name: e.target.value })}
                      placeholder="e.g. Vlan100, GigabitEthernet0/1"
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                  </div>

                  {/* MAC Address */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? 'MAC地址' : 'MAC Address'}</label>
                    <input
                      type="text"
                      value={form.mac_address}
                      onChange={(e) => setForm({ ...form, mac_address: e.target.value })}
                      placeholder="e.g. aa:bb:cc:dd:ee:ff"
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                  </div>

                  {/* Device Type Select */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? 'IP 角色类型' : 'Role Type'}</label>
                    <select
                      value={form.device_type}
                      onChange={(e) => setForm({ ...form, device_type: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    >
                      {ROLE_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>{zh ? opt.zh : opt.en}</option>
                      ))}
                    </select>
                  </div>

                  {/* Status Select */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? 'IP 地址状态' : 'IP Status'}</label>
                    <select
                      value={form.status}
                      onChange={(e) => setForm({ ...form, status: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    >
                      {STATUS_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>{zh ? opt.zh : opt.en}</option>
                      ))}
                    </select>
                  </div>

                  {/* Description */}
                  <div className="space-y-1.5 col-span-2">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '备注说明描述' : 'Description'}</label>
                    <textarea
                      value={form.description}
                      onChange={(e) => setForm({ ...form, description: e.target.value })}
                      placeholder={zh ? '在此输入IP的分配用途或绑定详情...' : 'Allocate comments...'}
                      rows={2}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50 resize-none"
                    />
                  </div>
                </div>
              </div>

              {/* Actions */}
              <div className="px-6 py-4 bg-gray-50 border-t border-gray-100 flex items-center justify-end gap-3 flex-shrink-0">
                <button
                  onClick={() => setShowAddEdit(false)}
                  className="px-4 py-2 text-xs font-bold text-gray-500 hover:bg-gray-100 rounded-xl transition-all"
                >
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button
                  onClick={handleSave}
                  className="px-6 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-600 hover:to-blue-700 text-white text-xs font-extrabold rounded-xl shadow-md transition-all active:scale-95"
                >
                  {zh ? '确定保存' : 'Save'}
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
                <h3 className="text-base font-bold text-gray-900 mb-2">{zh ? '释放IP地址记录？' : 'Release IP Address?'}</h3>
                <p className="text-xs text-gray-500 leading-relaxed">
                  {zh ? '您确定要释放/删除此IP地址记录吗？释放后，系统将重新将该IP标为可用，此操作不可撤销。' : 'Are you sure you want to release this IP registration? The IP will be freed up for future allocations.'}
                </p>
              </div>
              <div className="px-6 py-4 bg-gray-50 flex items-center justify-end gap-3 border-t border-gray-100">
                <button onClick={() => setShowDeleteConfirm(null)} className="px-3 py-1.5 text-xs text-gray-500 hover:bg-gray-100 rounded-lg font-semibold transition-colors">
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button onClick={() => handleDelete(showDeleteConfirm)} className="px-4 py-1.5 text-xs bg-rose-500 hover:bg-rose-600 text-white rounded-lg font-bold transition-colors">
                  {zh ? '释放IP' : 'Release'}
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default IPAddressTab;
