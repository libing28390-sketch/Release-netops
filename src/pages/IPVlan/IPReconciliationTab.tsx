import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  ClipboardCheck,
  AlertTriangle,
  RefreshCw,
  CheckCircle2,
  Trash2,
  Plus,
  Search,
  X,
  Info,
  Database,
  WifiOff,
  UserCheck,
  ArrowRight,
  ShieldAlert,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import PageHero from '../../components/PageHero';
import Pagination from '../../components/Pagination';

interface UndocumentedEndpoint {
  ip: string;
  mac: string;
  hostname: string;
  vendor: string;
  switch_id: string;
  switch_name: string;
  switch_port: string;
  vlan: string;
  vrf: string;
  site: string;
  last_seen: string;
  source_type: string;
  confidence: string;
  subnet_id: string;
  subnet_prefix: string;
  subnet_name: string;
}

interface StaleIPAddress {
  id: string;
  address: string;
  hostname: string;
  mac_address: string;
  subnet_id: string;
  subnet_prefix: string;
  subnet_name: string;
  status: string;
}

interface MismatchedEndpoint {
  ip: string;
  ipam_address_id: string;
  ipam_hostname: string;
  endpoint_hostname: string;
  ipam_mac: string;
  endpoint_mac: string;
  subnet_id: string;
  subnet_prefix: string;
  subnet_name: string;
  mac_mismatch: boolean;
  hostname_mismatch: boolean;
}

interface ReconciliationData {
  undocumented_endpoints: UndocumentedEndpoint[];
  stale_ip_addresses: StaleIPAddress[];
  mismatched_endpoints: MismatchedEndpoint[];
  summary: {
    total_undocumented: number;
    total_stale: number;
    total_mismatched: number;
  };
}

interface IPReconciliationTabProps {
  language: string;
  t: (key: string) => string;
}

const IPReconciliationTab: React.FC<IPReconciliationTabProps> = ({ language, t }) => {
  const zh = language === 'zh';
  const [data, setData] = useState<ReconciliationData>({
    undocumented_endpoints: [],
    stale_ip_addresses: [],
    mismatched_endpoints: [],
    summary: { total_undocumented: 0, total_stale: 0, total_mismatched: 0 },
  });
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'undocumented' | 'stale' | 'mismatched'>('undocumented');
  const [search, setSearch] = useState('');
  const [apiError, setApiError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [resultTotal, setResultTotal] = useState(0);

  // Modals state
  const [registeringItem, setRegisteringItem] = useState<UndocumentedEndpoint | null>(null);
  const [releasingItem, setReleasingItem] = useState<StaleIPAddress | null>(null);
  const [syncingItem, setSyncingItem] = useState<MismatchedEndpoint | null>(null);

  // Subnet list (for registering items where subnet is not auto-matched)
  const [subnets, setSubnets] = useState<any[]>([]);

  // Form State for Registration
  const [registerForm, setRegisterForm] = useState({
    subnet_id: '',
    address: '',
    hostname: '',
    device_type: 'host',
    mac_address: '',
    interface_name: '',
    status: 'active',
    description: '',
  });

  const authHeaders = useCallback(() => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, []);

  const loadData = useCallback(async () => {
    setLoading(true);
    setApiError('');
    try {
      const hdrs = authHeaders();
      const params = new URLSearchParams({
        active_tab: activeTab,
        q: search.trim(),
        page: String(page),
        page_size: String(pageSize),
      });
      const res = await fetch(`/api/ipam/reconciliation?${params.toString()}`, { headers: hdrs });
      if (res.ok) {
        const payload = await res.json();
        setData(payload);
        const summaryKey = activeTab === 'undocumented' ? 'total_undocumented' : activeTab === 'stale' ? 'total_stale' : 'total_mismatched';
        setResultTotal(Number(payload.result_total ?? payload.summary?.[summaryKey] ?? 0));
      } else {
        setApiError(zh ? '获取对账数据失败' : 'Failed to fetch reconciliation data');
      }

      // Fetch subnets for the fallback select
      const subRes = await fetch('/api/ipam/subnets', { headers: hdrs });
      if (subRes.ok) {
        const payload = await subRes.json();
        setSubnets(Array.isArray(payload) ? payload : (payload?.items || payload?.data?.items || payload?.data || []));
      }
    } catch (e) {
      setApiError(`Network error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  }, [authHeaders, zh, activeTab, search, page, pageSize]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Flash messages helper
  const triggerSuccess = (msg: string) => {
    setSuccessMsg(msg);
    setTimeout(() => setSuccessMsg(''), 4000);
  };

  // Actions implementation
  const handleOpenRegister = (item: UndocumentedEndpoint) => {
    setRegisterForm({
      subnet_id: item.subnet_id || (subnets.length > 0 ? subnets[0].id : ''),
      address: item.ip,
      hostname: item.hostname,
      device_type: 'host',
      mac_address: item.mac,
      interface_name: item.switch_port ? `${item.switch_name || item.switch_id}:${item.switch_port}` : '',
      status: 'active',
      description: zh ? '从对账中心自动登记' : 'Discovered via reconciliation audit',
    });
    setRegisteringItem(item);
  };

  const submitRegister = async () => {
    setApiError('');
    if (!registerForm.subnet_id) {
      setApiError(zh ? '请选择一个子网网段' : 'Please select a subnet');
      return;
    }
    try {
      const res = await fetch(`/api/ipam/subnets/${registerForm.subnet_id}/addresses`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...authHeaders(),
        },
        body: JSON.stringify(registerForm),
      });
      if (res.ok) {
        setRegisteringItem(null);
        triggerSuccess(zh ? `成功登记 IP ${registerForm.address}` : `Successfully registered IP ${registerForm.address}`);
        loadData();
      } else {
        const err = await res.json();
        setApiError(err.detail || (zh ? '登记失败' : 'Registration failed'));
      }
    } catch (e) {
      setApiError(zh ? '网络请求出错' : 'Network request error');
    }
  };

  const submitRelease = async () => {
    if (!releasingItem) return;
    setApiError('');
    try {
      const res = await fetch(`/api/ipam/addresses/${releasingItem.id}/release`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: '{}',
      });
      if (res.ok) {
        setReleasingItem(null);
        triggerSuccess(zh ? `成功释放 IP ${releasingItem.address}` : `Successfully released IP ${releasingItem.address}`);
        loadData();
      } else {
        const err = await res.json();
        setApiError(err.detail || (zh ? '释放 IP 失败' : 'Failed to release IP'));
      }
    } catch (e) {
      setApiError(zh ? '网络请求出错' : 'Network request error');
    }
  };

  const submitSync = async () => {
    if (!syncingItem) return;
    setApiError('');
    try {
      const res = await fetch(`/api/ipam/addresses/${syncingItem.ipam_address_id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          ...authHeaders(),
        },
        body: JSON.stringify({
          hostname: syncingItem.endpoint_hostname,
          mac_address: syncingItem.endpoint_mac,
        }),
      });
      if (res.ok) {
        setSyncingItem(null);
        triggerSuccess(zh ? `已将 IP ${syncingItem.ip} 同步为发现的真实数据` : `Successfully synced IP ${syncingItem.ip} with active data`);
        loadData();
      } else {
        const err = await res.json();
        setApiError(err.detail || (zh ? '同步失败' : 'Failed to sync info'));
      }
    } catch (e) {
      setApiError(zh ? '网络请求出错' : 'Network request error');
    }
  };

  // Pagination & Filtering
  const filteredList = useMemo(() => {
    const q = search.toLowerCase().trim();
    if (activeTab === 'undocumented') {
      return data.undocumented_endpoints.filter(
        (item) =>
          item.ip.includes(q) ||
          (item.hostname || '').toLowerCase().includes(q) ||
          (item.mac || '').toLowerCase().includes(q) ||
          (item.subnet_prefix || '').toLowerCase().includes(q)
      );
    } else if (activeTab === 'stale') {
      return data.stale_ip_addresses.filter(
        (item) =>
          item.address.includes(q) ||
          (item.hostname || '').toLowerCase().includes(q) ||
          (item.mac_address || '').toLowerCase().includes(q) ||
          (item.subnet_prefix || '').toLowerCase().includes(q)
      );
    } else {
      return data.mismatched_endpoints.filter(
        (item) =>
          item.ip.includes(q) ||
          (item.ipam_hostname || '').toLowerCase().includes(q) ||
          (item.endpoint_hostname || '').toLowerCase().includes(q) ||
          (item.ipam_mac || '').toLowerCase().includes(q) ||
          (item.endpoint_mac || '').toLowerCase().includes(q)
      );
    }
  }, [data, activeTab, search]);

  const paginatedList = filteredList;

  useEffect(() => {
    setPage(1);
  }, [activeTab, search]);

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden px-6 py-5 space-y-4">
      <PageHero
        icon={ClipboardCheck}
        title={zh ? 'IPAM 对账中心' : 'IP Reconciliation Center'}
        subtitle={zh ? '自动比对 IPAM 登记数据与网络中实际在线主机的 ARP/MAC 映射表，对审计差异进行闭环处理' : 'Automated comparison of documented IP allocations against discovered online network hosts.'}
        actions={
          <button
            onClick={loadData}
            disabled={loading}
            className="flex items-center gap-1.5 px-4 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-600 hover:to-blue-700 text-white rounded-xl text-xs font-bold shadow-lg shadow-cyan-500/20 active:scale-95 transition-all cursor-pointer disabled:opacity-55"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            {zh ? '重新对账' : 'Re-Audit'}
          </button>
        }
      />

      {/* Message Notifications */}
      {apiError && (
        <div className="flex items-center gap-2.5 px-4 py-3 rounded-2xl bg-red-50 border border-red-200 text-red-700 text-xs font-semibold">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          <span className="flex-1">{apiError}</span>
          <button onClick={() => setApiError('')} className="text-red-400 hover:text-red-600">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {successMsg && (
        <div className="flex items-center gap-2.5 px-4 py-3 rounded-2xl bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs font-semibold">
          <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
          <span className="flex-1">{successMsg}</span>
          <button onClick={() => setSuccessMsg('')} className="text-emerald-400 hover:text-emerald-600">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Undocumented */}
        <div
          onClick={() => setActiveTab('undocumented')}
          className={`cursor-pointer p-4 rounded-3xl border transition-all ${
            activeTab === 'undocumented'
              ? 'bg-cyan-500/[0.04] border-cyan-400 shadow-md shadow-cyan-500/5'
              : 'bg-white border-black/5 hover:border-black/10'
          }`}
        >
          <div className="flex justify-between items-start">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400">{zh ? '未登记活跃设备' : 'Undocumented Active Hosts'}</p>
              <h3 className="text-2xl font-black mt-1 text-[#00172D] font-mono">{data.summary.total_undocumented}</h3>
            </div>
            <div className={`p-2.5 rounded-2xl ${activeTab === 'undocumented' ? 'bg-cyan-500 text-white' : 'bg-cyan-50 text-cyan-600'}`}>
              <Plus size={18} />
            </div>
          </div>
          <p className="text-[10px] text-gray-400 mt-2.5 leading-relaxed">
            {zh ? '真实在线但 IPAM 尚未建档的终端设备，可能存在管理盲区。' : 'Active IP endpoints not recorded in IPAM database.'}
          </p>
        </div>

        {/* Stale */}
        <div
          onClick={() => setActiveTab('stale')}
          className={`cursor-pointer p-4 rounded-3xl border transition-all ${
            activeTab === 'stale'
              ? 'bg-amber-500/[0.04] border-amber-400 shadow-md shadow-amber-500/5'
              : 'bg-white border-black/5 hover:border-black/10'
          }`}
        >
          <div className="flex justify-between items-start">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400">{zh ? '离线已登记IP (僵尸IP)' : 'Stale/Zombie IP Addresses'}</p>
              <h3 className="text-2xl font-black mt-1 text-[#00172D] font-mono">{data.summary.total_stale}</h3>
            </div>
            <div className={`p-2.5 rounded-2xl ${activeTab === 'stale' ? 'bg-amber-500 text-white' : 'bg-amber-50 text-amber-600'}`}>
              <WifiOff size={18} />
            </div>
          </div>
          <p className="text-[10px] text-gray-400 mt-2.5 leading-relaxed">
            {zh ? '已建档但在网络中长时间不活跃的 IP 地址，可释放回收。' : 'Documented IP allocations with no recent network activity.'}
          </p>
        </div>

        {/* Mismatched */}
        <div
          onClick={() => setActiveTab('mismatched')}
          className={`cursor-pointer p-4 rounded-3xl border transition-all ${
            activeTab === 'mismatched'
              ? 'bg-rose-500/[0.04] border-rose-400 shadow-md shadow-rose-500/5'
              : 'bg-white border-black/5 hover:border-black/10'
          }`}
        >
          <div className="flex justify-between items-start">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400">{zh ? '信息不一致设备' : 'Mismatched Configurations'}</p>
              <h3 className="text-2xl font-black mt-1 text-[#00172D] font-mono">{data.summary.total_mismatched}</h3>
            </div>
            <div className={`p-2.5 rounded-2xl ${activeTab === 'mismatched' ? 'bg-rose-500 text-white' : 'bg-rose-50 text-rose-600'}`}>
              <ShieldAlert size={18} />
            </div>
          </div>
          <p className="text-[10px] text-gray-400 mt-2.5 leading-relaxed">
            {zh ? '建档信息与发现的真实主机名或 MAC 地址不吻合，建议校准。' : 'IPAM records mismatching actual discovered hostnames/MACs.'}
          </p>
        </div>
      </div>

      {/* Main content table card */}
      <div className="flex-1 min-h-0 bg-white rounded-[28px] border border-black/5 shadow-[0_16px_36px_rgba(11,35,64,0.06)] overflow-hidden flex flex-col">
        {/* Table Toolbar */}
        <div className="px-6 py-4 bg-gray-50/40 border-b border-gray-100 flex flex-col md:flex-row md:items-center justify-between gap-3 select-none flex-shrink-0">
          <h4 className="text-xs font-bold text-gray-700 uppercase tracking-widest">
            {activeTab === 'undocumented' && (zh ? '未登记的活跃主机列表' : 'Undocumented Active Hosts')}
            {activeTab === 'stale' && (zh ? '已建档离线的主机列表 (僵尸IP)' : 'Stale/Offline Documented IPs')}
            {activeTab === 'mismatched' && (zh ? 'MAC或主机名不一致的IP列表' : 'Mismatched Hostnames / MACs')}
          </h4>

          {/* Search */}
          <div className="relative w-full md:w-64">
            <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={zh ? '过滤搜索 IP / MAC / 描述...' : 'Filter IP / MAC...'}
              className="w-full pl-10 pr-4 py-1.5 text-xs rounded-xl border border-black/5 bg-gray-50/50 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium"
            />
          </div>
        </div>

        {/* Table Area */}
        <div className="flex-1 overflow-auto">
          {loading ? (
            <div className="h-full flex items-center justify-center text-xs text-gray-400 font-semibold gap-2">
              <RefreshCw className="w-4 h-4 animate-spin text-cyan-500" />
              {zh ? '正在执行网络对账分析...' : 'Auditing databases...'}
            </div>
          ) : (
            <table className="nx-data-table text-left">
              {/* Tab 1: Undocumented */}
              {activeTab === 'undocumented' && (
                <>
                  <thead>
                    <tr className="border-b border-gray-100 bg-gray-50/20 text-[10px] font-bold text-gray-400 uppercase tracking-wider select-none">
                      <th className="pl-6 py-4">{zh ? 'IP地址' : 'IP Address'}</th>
                      <th className="px-4 py-4">{zh ? '发现 MAC' : 'Discovered MAC'}</th>
                      <th className="px-4 py-4">{zh ? '发现主机名' : 'Hostname'}</th>
                      <th className="px-4 py-4">{zh ? '接入交换机 / 端口' : 'Access Switch / Port'}</th>
                      <th className="px-4 py-4">{zh ? 'VLAN' : 'VLAN'}</th>
                      <th className="px-4 py-4">{zh ? '匹配的网段前缀' : 'Resolved Prefix'}</th>
                      <th className="px-4 py-4">{zh ? '最后活跃时间' : 'Last Seen'}</th>
                      <th className="pr-6 py-4 text-right">{zh ? '操作' : 'Actions'}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {paginatedList.length > 0 ? (
                      (paginatedList as UndocumentedEndpoint[]).map((node) => (
                        <tr key={node.ip} className="hover:bg-gray-50/50 transition-colors border-b border-gray-100 group">
                          <td className="pl-6 py-4 font-mono font-bold text-xs text-gray-800">{node.ip}</td>
                          <td className="px-4 py-4 font-mono text-xs text-gray-500">{node.mac}</td>
                          <td className="px-4 py-4 text-xs font-semibold text-gray-600">{node.hostname || '-'}</td>
                          <td className="px-4 py-4 text-xs font-semibold text-cyan-600">
                            {node.switch_name ? (
                              <div>
                                <span>{node.switch_name} [{node.switch_port}]</span>
                                <span className="mt-0.5 block text-[9px] font-medium text-gray-400">
                                  {node.source_type || 'unknown'} · {node.confidence || (zh ? '置信度未知' : 'unknown confidence')}
                                </span>
                              </div>
                            ) : '-'}
                          </td>
                          <td className="px-4 py-4 text-xs text-gray-500 font-bold">{node.vlan || '-'}</td>
                          <td className="px-4 py-4 text-xs">
                            <span className="font-mono text-gray-600 font-semibold">{node.subnet_prefix || '-'}</span>
                            {node.subnet_name && <span className="text-[10px] text-gray-400 block">{node.subnet_name}</span>}
                          </td>
                          <td className="px-4 py-4 font-mono text-[10px] text-gray-400">{node.last_seen || '-'}</td>
                          <td className="pr-6 py-4 text-right">
                            <button
                              onClick={() => handleOpenRegister(node)}
                              className="px-2.5 py-1 bg-cyan-50 hover:bg-cyan-500 text-cyan-700 hover:text-white rounded-lg text-[10px] font-extrabold transition-all active:scale-95"
                            >
                              {zh ? '标准登记' : 'Register'}
                            </button>
                          </td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td colSpan={8} className="py-12 text-center text-xs text-gray-400 font-medium">
                          {zh ? '暂无未登记的在线活跃主机' : 'No undocumented active endpoints found'}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </>
              )}

              {/* Tab 2: Stale */}
              {activeTab === 'stale' && (
                <>
                  <thead>
                    <tr className="border-b border-gray-100 bg-gray-50/20 text-[10px] font-bold text-gray-400 uppercase tracking-wider select-none">
                      <th className="pl-6 py-4">{zh ? 'IP地址' : 'IP Address'}</th>
                      <th className="px-4 py-4">{zh ? '登记 MAC' : 'Documented MAC'}</th>
                      <th className="px-4 py-4">{zh ? '登记主机名' : 'Hostname'}</th>
                      <th className="px-4 py-4">{zh ? '归属子网' : 'Subnet'}</th>
                      <th className="px-4 py-4">{zh ? '登记状态' : 'Status'}</th>
                      <th className="pr-6 py-4 text-right">{zh ? '操作' : 'Actions'}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {paginatedList.length > 0 ? (
                      (paginatedList as StaleIPAddress[]).map((node) => (
                        <tr key={node.id} className="hover:bg-gray-50/50 transition-colors border-b border-gray-100 group">
                          <td className="pl-6 py-4 font-mono font-bold text-xs text-gray-800">{node.address}</td>
                          <td className="px-4 py-4 font-mono text-xs text-gray-500">{node.mac_address || '-'}</td>
                          <td className="px-4 py-4 text-xs font-semibold text-gray-500">{node.hostname || '-'}</td>
                          <td className="px-4 py-4 text-xs">
                            <span className="font-mono text-gray-600 font-semibold">{node.subnet_prefix || '-'}</span>
                            {node.subnet_name && <span className="text-[10px] text-gray-400 block">{node.subnet_name}</span>}
                          </td>
                          <td className="px-4 py-4 text-xs">
                            <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-50 text-amber-600 border border-amber-500/10`}>
                              {node.status.toUpperCase()}
                            </span>
                          </td>
                          <td className="pr-6 py-4 text-right">
                            <button
                              onClick={() => setReleasingItem(node)}
                              className="p-1 rounded-md text-gray-400 hover:text-rose-600 hover:bg-rose-50 transition-all cursor-pointer"
                              title={zh ? '释放此 IP' : 'Release IP'}
                            >
                              <Trash2 size={15} />
                            </button>
                          </td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td colSpan={6} className="py-12 text-center text-xs text-gray-400 font-medium">
                          {zh ? '暂无长时间离线的僵尸IP' : 'No stale documented IPs discovered'}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </>
              )}

              {/* Tab 3: Mismatched */}
              {activeTab === 'mismatched' && (
                <>
                  <thead>
                    <tr className="border-b border-gray-100 bg-gray-50/20 text-[10px] font-bold text-gray-400 uppercase tracking-wider select-none">
                      <th className="pl-6 py-4">{zh ? 'IP地址' : 'IP Address'}</th>
                      <th className="px-4 py-4">{zh ? 'MAC对比 (IPAM -> Discovered)' : 'MAC (IPAM -> Discovered)'}</th>
                      <th className="px-4 py-4">{zh ? '主机名对比 (IPAM -> Discovered)' : 'Hostname (IPAM -> Discovered)'}</th>
                      <th className="px-4 py-4">{zh ? '归属子网' : 'Subnet'}</th>
                      <th className="pr-6 py-4 text-right">{zh ? '操作' : 'Actions'}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {paginatedList.length > 0 ? (
                      (paginatedList as MismatchedEndpoint[]).map((node) => (
                        <tr key={node.ip} className="hover:bg-gray-50/50 transition-colors border-b border-gray-100 group">
                          <td className="pl-6 py-4 font-mono font-bold text-xs text-gray-800">{node.ip}</td>
                          <td className="px-4 py-4 text-xs font-mono">
                            <div className="flex items-center gap-1.5">
                              <span className={node.mac_mismatch ? 'text-rose-600 line-through bg-rose-50 px-1 rounded' : 'text-gray-500'}>
                                {node.ipam_mac || '(Empty)'}
                              </span>
                              {node.mac_mismatch && (
                                <>
                                  <ArrowRight size={11} className="text-gray-400" />
                                  <span className="text-emerald-600 font-bold bg-emerald-50 px-1 rounded">{node.endpoint_mac}</span>
                                </>
                              )}
                            </div>
                          </td>
                          <td className="px-4 py-4 text-xs font-medium">
                            <div className="flex items-center gap-1.5">
                              <span className={node.hostname_mismatch ? 'text-rose-600 line-through bg-rose-50 px-1 rounded' : 'text-gray-500'}>
                                {node.ipam_hostname || '(Empty)'}
                              </span>
                              {node.hostname_mismatch && (
                                <>
                                  <ArrowRight size={11} className="text-gray-400" />
                                  <span className="text-emerald-600 font-bold bg-emerald-50 px-1 rounded">{node.endpoint_hostname}</span>
                                </>
                              )}
                            </div>
                          </td>
                          <td className="px-4 py-4 text-xs">
                            <span className="font-mono text-gray-600 font-semibold">{node.subnet_prefix || '-'}</span>
                            {node.subnet_name && <span className="text-[10px] text-gray-400 block">{node.subnet_name}</span>}
                          </td>
                          <td className="pr-6 py-4 text-right">
                            <button
                              onClick={() => setSyncingItem(node)}
                              className="px-2.5 py-1 bg-cyan-50 hover:bg-cyan-500 text-cyan-700 hover:text-white rounded-lg text-[10px] font-extrabold transition-all active:scale-95"
                            >
                              {zh ? '校准同步' : 'Sync Info'}
                            </button>
                          </td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td colSpan={5} className="py-12 text-center text-xs text-gray-400 font-medium">
                          {zh ? '暂无建档信息不吻合的IP' : 'No mismatched IPs discovered'}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </>
              )}
            </table>
          )}
        </div>

        {/* Pagination */}
        <div className="px-6 py-4 border-t border-gray-100 flex-shrink-0">
          <Pagination
            currentPage={page}
            totalItems={resultTotal}
            itemsPerPage={pageSize}
            onPageChange={setPage}
            onItemsPerPageChange={(size) => { setPageSize(size); setPage(1); }}
            language={language}
            alwaysVisible={true}
          />
        </div>
      </div>

      {/* Modal 1: Register IP */}
      <AnimatePresence>
        {registeringItem && (
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
                    <Plus size={20} />
                  </div>
                  <div>
                    <h3 className="font-bold text-gray-900">{zh ? '将发现终端标准登记到 IPAM' : 'Register Discovered Host'}</h3>
                    <p className="text-xs text-gray-500 mt-0.5">{zh ? '请核对发现来源、置信度和归属网段后再创建分配记录。' : 'Review the evidence, confidence, and resolved prefix before creating the allocation.'}</p>
                  </div>
                </div>
                <button onClick={() => setRegisteringItem(null)} className="p-1.5 rounded-lg hover:bg-gray-50 transition-colors text-gray-400">
                  <X size={16} />
                </button>
              </div>

              {/* Form Content */}
              <div className="flex-1 overflow-y-auto p-6 space-y-4">
                <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800">
                  <p className="font-bold">{zh ? '风险提示' : 'Risk notice'}</p>
                  <p className="mt-1 leading-relaxed">
                    {zh
                      ? `来源：${registeringItem.source_type || '未知'}；置信度：${registeringItem.confidence || '未知'}；最后发现：${registeringItem.last_seen || '未知'}。登记会写入正式 IPAM 数据，请先核对。`
                      : `Source: ${registeringItem.source_type || 'unknown'}; confidence: ${registeringItem.confidence || 'unknown'}; last seen: ${registeringItem.last_seen || 'unknown'}. This writes a managed IPAM record.`}
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  {/* Select Subnet */}
                  <div className="space-y-1.5 col-span-2">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '归属网段前缀' : 'Subnet Prefix'}</label>
                    <select
                      value={registerForm.subnet_id}
                      onChange={(e) => setRegisterForm({ ...registerForm, subnet_id: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    >
                      {subnets.map((sub: any) => (
                        <option key={sub.id} value={sub.id}>
                          {sub.prefix} {sub.name ? `(${sub.name})` : ''}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* IP Address */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? 'IP 地址' : 'IP Address'}</label>
                    <input
                      type="text"
                      value={registerForm.address}
                      disabled
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none transition-all font-mono font-bold bg-gray-100 text-gray-500"
                    />
                  </div>

                  {/* MAC Address */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? 'MAC 地址' : 'MAC Address'}</label>
                    <input
                      type="text"
                      value={registerForm.mac_address}
                      onChange={(e) => setRegisterForm({ ...registerForm, mac_address: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-mono font-medium bg-gray-50/50"
                    />
                  </div>

                  {/* Hostname */}
                  <div className="space-y-1.5 col-span-2">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '主机名 / 域名' : 'Hostname'}</label>
                    <input
                      type="text"
                      value={registerForm.hostname}
                      onChange={(e) => setRegisterForm({ ...registerForm, hostname: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-semibold bg-gray-50/50"
                    />
                  </div>

                  {/* Device Type */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? 'IP 角色类型' : 'Role Type'}</label>
                    <select
                      value={registerForm.device_type}
                      onChange={(e) => setRegisterForm({ ...registerForm, device_type: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    >
                      <option value="host">{zh ? '普通主机' : 'Host'}</option>
                      <option value="server">{zh ? '服务器' : 'Server'}</option>
                      <option value="device">{zh ? '网络设备' : 'Network Device'}</option>
                      <option value="gateway">{zh ? '网关' : 'Gateway'}</option>
                    </select>
                  </div>

                  {/* Bound Interface */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '绑定物理接口' : 'Access Interface'}</label>
                    <input
                      type="text"
                      value={registerForm.interface_name}
                      onChange={(e) => setRegisterForm({ ...registerForm, interface_name: e.target.value })}
                      placeholder="e.g. Switch-Core:Gi0/1"
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                  </div>

                  {/* Description */}
                  <div className="space-y-1.5 col-span-2">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '备注描述说明' : 'Description'}</label>
                    <textarea
                      value={registerForm.description}
                      onChange={(e) => setRegisterForm({ ...registerForm, description: e.target.value })}
                      rows={2}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50 resize-none"
                    />
                  </div>
                </div>
              </div>

              {/* Actions */}
              <div className="px-6 py-4 bg-gray-50 border-t border-gray-100 flex items-center justify-end gap-3 flex-shrink-0">
                <button
                  onClick={() => setRegisteringItem(null)}
                  className="px-4 py-2 text-xs font-bold text-gray-500 hover:bg-gray-100 rounded-xl transition-all"
                >
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button
                  onClick={submitRegister}
                  className="px-6 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-600 hover:to-blue-700 text-white text-xs font-extrabold rounded-xl shadow-md transition-all active:scale-95"
                >
                  {zh ? '确认标准登记' : 'Confirm Registration'}
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* Modal 2: Release IP */}
      <AnimatePresence>
        {releasingItem && (
          <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-white w-full max-w-md rounded-3xl overflow-hidden shadow-2xl border border-black/5"
            >
              <div className="p-6">
                <h3 className="text-base font-bold text-gray-900 mb-2">{zh ? '释放离线僵尸 IP 登记吗？' : 'Release Offline IP address?'}</h3>
                <p className="text-xs text-gray-500 leading-relaxed">
                  {zh ? `您确认要从 IPAM 数据库中释放 IP 地址 ${releasingItem.address} 吗？释放后此 IP 将变为空闲可分配状态，原有绑定数据将被清理。` : `Are you sure you want to release documented IP ${releasingItem.address}? It is currently offline and will be marked as free.`}
                </p>
              </div>
              <div className="px-6 py-4 bg-gray-50 flex items-center justify-end gap-3 border-t border-gray-100">
                <button
                  onClick={() => setReleasingItem(null)}
                  className="px-3 py-1.5 text-xs text-gray-500 hover:bg-gray-100 rounded-lg font-semibold transition-colors"
                >
                  {zh ? '我再想想' : 'Cancel'}
                </button>
                <button
                  onClick={submitRelease}
                  className="px-4 py-1.5 text-xs bg-rose-500 hover:bg-rose-600 text-white rounded-lg font-bold transition-colors"
                >
                  {zh ? '确认释放' : 'Release'}
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* Modal 3: Sync mismatched details */}
      <AnimatePresence>
        {syncingItem && (
          <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-white w-full max-w-md rounded-3xl overflow-hidden shadow-2xl border border-black/5"
            >
              <div className="p-6">
                <h3 className="text-base font-bold text-gray-900 mb-2">{zh ? '执行 IP 资产信息校准？' : 'Align IP asset information?'}</h3>
                <p className="text-xs text-gray-500 leading-relaxed mb-4">
                  {zh
                    ? `是否使用网络扫描发现的真实数据，来更新 IP ${syncingItem.ip} 在 IPAM 中的登记信息？`
                    : `Do you want to update the IPAM registration details for IP ${syncingItem.ip} using discovered network parameters?`}
                </p>
                <div className="space-y-2.5 p-3 rounded-2xl bg-cyan-50/50 border border-cyan-500/10 text-xs">
                  {syncingItem.hostname_mismatch && (
                    <div className="flex justify-between items-center">
                      <span className="text-gray-400">{zh ? '主机名校准' : 'Hostname'}</span>
                      <span className="font-bold text-gray-800">
                        {syncingItem.ipam_hostname || '(Empty)'} <ArrowRight size={10} className="inline mx-1" />{' '}
                        {syncingItem.endpoint_hostname}
                      </span>
                    </div>
                  )}
                  {syncingItem.mac_mismatch && (
                    <div className="flex justify-between items-center">
                      <span className="text-gray-400">{zh ? 'MAC地址校准' : 'MAC Address'}</span>
                      <span className="font-mono font-bold text-gray-800">
                        {syncingItem.ipam_mac || '(Empty)'} <ArrowRight size={10} className="inline mx-1" />{' '}
                        {syncingItem.endpoint_mac}
                      </span>
                    </div>
                  )}
                </div>
              </div>
              <div className="px-6 py-4 bg-gray-50 flex items-center justify-end gap-3 border-t border-gray-100">
                <button
                  onClick={() => setSyncingItem(null)}
                  className="px-3 py-1.5 text-xs text-gray-500 hover:bg-gray-100 rounded-lg font-semibold transition-colors"
                >
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button
                  onClick={submitSync}
                  className="px-4 py-1.5 text-xs bg-cyan-500 hover:bg-cyan-600 text-white rounded-lg font-bold transition-colors"
                >
                  {zh ? '同步并保存' : 'Align Now'}
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default IPReconciliationTab;
