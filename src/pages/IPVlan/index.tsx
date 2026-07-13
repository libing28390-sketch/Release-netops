import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Network,
  Plus,
  Trash2,
  AlertTriangle,
  Download,
  Search,
  X,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  Pencil,
  ChevronUp,
  LayoutGrid,
  LayoutList,
  FolderOpen,
  Grid3x3,
  ChevronDown,
  TableProperties,
} from 'lucide-react';
import * as XLSX from 'xlsx';
import Pagination from '../../components/Pagination';
import PageHero from '../../components/PageHero';

import { Subnet, IPAddress, Conflict, IPVlanTabProps } from './types';
import { DEVICE_TYPES } from './constants';
import {
  isValidIPv4,
  isValidIPv6,
  isValidIP,
  detectIPVersion,
  toNum,
  ipInSubnet,
  alignedNetwork,
  isValidVlanId,
  isValidPrefixLen,
  utilColor,
  utilBarColor,
} from './helpers';

import IPBlockMap, { BlockMapItem } from './components/IPBlockMap';
import SubnetModal from './components/SubnetModal';
import IPModal from './components/IPModal';
import DeleteConfirmModal from './components/DeleteConfirmModal';

const IPVlanTab: React.FC<IPVlanTabProps> = ({ language, t }) => {
  const [subnets, setSubnets] = useState<Subnet[]>([]);
  const [selectedSubnet, setSelectedSubnet] = useState<Subnet | null>(null);
  const [addresses, setAddresses] = useState<IPAddress[]>([]);
  const [conflicts, setConflicts] = useState<Conflict>({ ip_conflicts: [], mac_conflicts: [], total_conflicts: 0 });
  const [summary, setSummary] = useState({
    total_subnets: 0,
    total_addresses: 0,
    total_capacity: 0,
    total_used: 0,
    high_utilization_subnets: [] as any[],
  });
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [utilFilter, setUtilFilter] = useState<'all' | 'high' | 'critical'>('all');
  const [subnetSort, setSubnetSort] = useState<'util_desc' | 'name_asc'>('util_desc');
  const [riskOnlyMode, setRiskOnlyMode] = useState(false);

  const [showAddSubnet, setShowAddSubnet] = useState(false);
  const [showAddIP, setShowAddIP] = useState(false);
  const [apiError, setApiError] = useState('');
  const [formSubnet, setFormSubnet] = useState({
    name: '',
    network: '',
    prefix_len: 24,
    vlan_id: '',
    vlan_name: '',
    gateway: '',
    description: '',
    site: '',
  });
  const [formIP, setFormIP] = useState({
    address: '',
    hostname: '',
    interface_name: '',
    mac_address: '',
    device_type: '',
    description: '',
    status: 'active',
  });

  const authHeaders = useCallback(() => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, []);

  const [editingIP, setEditingIP] = useState<IPAddress | null>(null);
  const [addrStatusFilter, setAddrStatusFilter] = useState<'all' | 'active' | 'reserved' | 'deprecated'>('all');
  const [confirmDelete, setConfirmDelete] = useState<{
    type: 'subnet' | 'ip' | 'batch-subnet';
    id: string;
    label: string;
  } | null>(null);
  const [editingSubnet, setEditingSubnet] = useState<Subnet | null>(null);
  const [selectedSubnetIds, setSelectedSubnetIds] = useState<Set<string>>(new Set());
  const [addrSearch, setAddrSearch] = useState('');
  const [addrPage, setAddrPage] = useState(1);
  const [subnetPage, setSubnetPage] = useState(1);
  const [addrDeviceTypeFilter, setAddrDeviceTypeFilter] = useState('');
  const [addrViewMode, setAddrViewMode] = useState<'table' | 'card' | 'block'>('table');
  const [subnetGroupBy, setSubnetGroupBy] = useState<'none' | 'site'>('none');
  const [siteCollapsed, setSiteCollapsed] = useState<Record<string, boolean>>({});
  const [subnetPageSizeOpt, setSubnetPageSizeOpt] = useState(10);
  const [addrPageSizeOpt, setAddrPageSizeOpt] = useState(10);
  const [overviewCollapsed, setOverviewCollapsed] = useState(true);
  const [compactSubnetList, setCompactSubnetList] = useState(false);
  const [subnetViewMode, setSubnetViewMode] = useState<'card' | 'table'>('table');

  const loadData = useCallback(async () => {
    setLoading(true);
    setApiError('');
    try {
      const hdrs = authHeaders();
      const [subRes, conflictRes, summaryRes] = await Promise.all([
        fetch(`/api/ipam/subnets?q=${encodeURIComponent(search)}`, { headers: hdrs }),
        fetch('/api/ipam/conflicts', { headers: hdrs }),
        fetch('/api/ipam/summary', { headers: hdrs }),
      ]);
      if (subRes.ok) setSubnets(await subRes.json());
      else setApiError(`加载子网失败: ${subRes.status}`);
      if (conflictRes.ok) setConflicts(await conflictRes.json());
      if (summaryRes.ok) setSummary(await summaryRes.json());
    } catch (e) {
      setApiError(`网络错误: ${e instanceof Error ? e.message : String(e)}`);
    }
    setLoading(false);
  }, [search, authHeaders]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const loadAddresses = async (subnet: Subnet) => {
    setSelectedSubnet(subnet);
    try {
      const r = await fetch(`/api/ipam/subnets/${subnet.id}/addresses`, { headers: authHeaders() });
      if (r.ok) setAddresses(await r.json());
      else setApiError(`加载地址失败: ${r.status}`);
    } catch (e) {
      setApiError(`网络错误: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const handleAddSubnet = async () => {
    setApiError('');
    try {
      const r = await fetch('/api/ipam/subnets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          ...formSubnet,
          vlan_id: formSubnet.vlan_id ? parseInt(formSubnet.vlan_id) : null,
        }),
      });
      if (r.ok) {
        setShowAddSubnet(false);
        setFormSubnet({
          name: '',
          network: '',
          prefix_len: 24,
          vlan_id: '',
          vlan_name: '',
          gateway: '',
          description: '',
          site: '',
        });
        loadData();
      } else {
        const detail = await r.json().catch(() => null);
        setApiError(detail?.detail || `创建子网失败: ${r.status}`);
      }
    } catch (e) {
      setApiError(`网络错误: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const handleEditSubnet = async () => {
    if (!editingSubnet) return;
    setApiError('');
    try {
      const r = await fetch(`/api/ipam/subnets/${editingSubnet.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          ...formSubnet,
          vlan_id: formSubnet.vlan_id ? parseInt(formSubnet.vlan_id) : null,
        }),
      });
      if (r.ok) {
        setShowAddSubnet(false);
        setEditingSubnet(null);
        setFormSubnet({
          name: '',
          network: '',
          prefix_len: 24,
          vlan_id: '',
          vlan_name: '',
          gateway: '',
          description: '',
          site: '',
        });
        loadData();
        if (selectedSubnet?.id === editingSubnet.id) {
          const updated = await r.json().catch(() => null);
          if (updated) setSelectedSubnet(updated);
        }
      } else {
        const detail = await r.json().catch(() => null);
        setApiError(detail?.detail || `编辑子网失败: ${r.status}`);
      }
    } catch (e) {
      setApiError(`网络错误: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const openEditSubnet = (subnet: Subnet, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingSubnet(subnet);
    setFormSubnet({
      name: subnet.name,
      network: subnet.network,
      prefix_len: subnet.prefix_len,
      vlan_id: subnet.vlan_id ? String(subnet.vlan_id) : '',
      vlan_name: subnet.vlan_name || '',
      gateway: subnet.gateway || '',
      description: subnet.description || '',
      site: subnet.site || '',
    });
    setShowAddSubnet(true);
  };

  const handleAddIP = async () => {
    if (!selectedSubnet) return;
    setApiError('');
    try {
      const r = await fetch(`/api/ipam/subnets/${selectedSubnet.id}/addresses`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(formIP),
      });
      if (r.ok) {
        setShowAddIP(false);
        setEditingIP(null);
        setFormIP({
          address: '',
          hostname: '',
          interface_name: '',
          mac_address: '',
          device_type: '',
          description: '',
          status: 'active',
        });
        loadAddresses(selectedSubnet);
        loadData();
      } else {
        const detail = await r.json().catch(() => null);
        setApiError(detail?.detail || `添加 IP 失败: ${r.status}`);
      }
    } catch (e) {
      setApiError(`网络错误: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const handleEditIP = async () => {
    if (!editingIP) return;
    setApiError('');
    try {
      const r = await fetch(`/api/ipam/addresses/${editingIP.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          hostname: formIP.hostname,
          interface_name: formIP.interface_name,
          mac_address: formIP.mac_address,
          device_type: formIP.device_type,
          description: formIP.description,
          status: formIP.status,
        }),
      });
      if (r.ok) {
        setShowAddIP(false);
        setEditingIP(null);
        setFormIP({
          address: '',
          hostname: '',
          interface_name: '',
          mac_address: '',
          device_type: '',
          description: '',
          status: 'active',
        });
        if (selectedSubnet) loadAddresses(selectedSubnet);
        loadData();
      } else {
        const detail = await r.json().catch(() => null);
        setApiError(detail?.detail || `编辑 IP 失败: ${r.status}`);
      }
    } catch (e) {
      setApiError(`网络错误: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const openEditIP = (addr: IPAddress) => {
    setEditingIP(addr);
    setFormIP({
      address: addr.address,
      hostname: addr.hostname || '',
      interface_name: addr.interface_name || '',
      mac_address: addr.mac_address || '',
      device_type: addr.device_type || '',
      description: addr.description || '',
      status: addr.status || 'active',
    });
    setShowAddIP(true);
  };

  const handleDeleteSubnet = async (id: string) => {
    setApiError('');
    try {
      const r = await fetch(`/api/ipam/subnets/${id}`, { method: 'DELETE', headers: authHeaders() });
      if (!r.ok) {
        const detail = await r.json().catch(() => null);
        setApiError(detail?.detail || `删除子网失败: ${r.status}`);
        return;
      }
      if (selectedSubnet?.id === id) {
        setSelectedSubnet(null);
        setAddresses([]);
      }
      loadData();
    } catch (e) {
      setApiError(`网络错误: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const handleDeleteIP = async (id: string) => {
    setApiError('');
    try {
      const r = await fetch(`/api/ipam/addresses/${id}/release`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() }, body: '{}' });
      if (!r.ok) {
        const detail = await r.json().catch(() => null);
        setApiError(detail?.detail || `删除地址失败: ${r.status}`);
        return;
      }
      if (selectedSubnet) loadAddresses(selectedSubnet);
      loadData();
    } catch (e) {
      setApiError(`网络错误: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const handleBatchDeleteSubnets = async (ids: string[]) => {
    setApiError('');
    try {
      const r = await fetch('/api/ipam/subnets/batch-delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ ids }),
      });
      if (!r.ok) {
        const detail = await r.json().catch(() => null);
        setApiError(detail?.detail || `批量删除失败: ${r.status}`);
        return;
      }
      if (selectedSubnet && ids.includes(selectedSubnet.id)) {
        setSelectedSubnet(null);
        setAddresses([]);
      }
      setSelectedSubnetIds(new Set());
      loadData();
    } catch (e) {
      setApiError(`网络错误: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const executeConfirmedDelete = async () => {
    if (!confirmDelete) return;
    if (confirmDelete.type === 'batch-subnet') {
      await handleBatchDeleteSubnets(confirmDelete.id.split(','));
    } else if (confirmDelete.type === 'subnet') {
      await handleDeleteSubnet(confirmDelete.id);
    } else {
      await handleDeleteIP(confirmDelete.id);
    }
    setConfirmDelete(null);
  };

  const filteredAddresses = useMemo(() => {
    let result = addresses;
    if (addrStatusFilter !== 'all') {
      result = result.filter((a) => a.status === addrStatusFilter);
    }
    if (addrDeviceTypeFilter) {
      result = result.filter((a) => (a.device_type || '') === addrDeviceTypeFilter);
    }
    if (addrSearch) {
      const q = addrSearch.toLowerCase();
      result = result.filter(
        (a) =>
          a.address.toLowerCase().includes(q) ||
          (a.hostname || '').toLowerCase().includes(q) ||
          (a.mac_address || '').toLowerCase().includes(q) ||
          (a.interface_name || '').toLowerCase().includes(q) ||
          (a.device_type || '').toLowerCase().includes(q)
      );
    }
    return result;
  }, [addresses, addrSearch, addrStatusFilter, addrDeviceTypeFilter]);

  const addrStatusCounts = useMemo(() => {
    const counts = { all: addresses.length, active: 0, reserved: 0, deprecated: 0 };
    addresses.forEach((a) => {
      if (a.status === 'reserved') counts.reserved++;
      else if (a.status === 'deprecated') counts.deprecated++;
      else counts.active++;
    });
    return counts;
  }, [addresses]);

  const addrDeviceTypeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    addresses.forEach((a) => {
      const dt = a.device_type || '';
      counts[dt] = (counts[dt] || 0) + 1;
    });
    return counts;
  }, [addresses]);

  const addrTotalPages = Math.max(1, Math.ceil(filteredAddresses.length / addrPageSizeOpt));
  const safeAddrPage = Math.min(addrPage, addrTotalPages);
  const pagedAddresses = filteredAddresses.slice((safeAddrPage - 1) * addrPageSizeOpt, safeAddrPage * addrPageSizeOpt);

  const handleExport = () => {
    const zh = language === 'zh';
    const wb = XLSX.utils.book_new();
    if (subnets.length > 0) {
      const subData = subnets.map((s) => ({
        [zh ? '名称' : 'Name']: s.name,
        [zh ? '网段' : 'Network']: `${s.network}/${s.prefix_len}`,
        'VLAN ID': s.vlan_id || '',
        [zh ? 'VLAN名称' : 'VLAN Name']: s.vlan_name,
        [zh ? '网关' : 'Gateway']: s.gateway,
        [zh ? '站点' : 'Site']: s.site,
        [zh ? '总IP数' : 'Total IPs']: s.total_ips,
        [zh ? '已用IP数' : 'Used IPs']: s.used_ips,
        [zh ? '利用率' : 'Utilization']: `${s.utilization}%`,
        [zh ? '描述' : 'Description']: s.description,
      }));
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(subData), zh ? '子网' : 'Subnets');
    }
    if (addresses.length > 0) {
      const addrData = addresses.map((a) => ({
        [zh ? 'IP地址' : 'Address']: a.address,
        [zh ? '主机名' : 'Hostname']: a.hostname,
        [zh ? '接口' : 'Interface']: a.interface_name,
        MAC: a.mac_address,
        [zh ? '状态' : 'Status']: a.status,
        [zh ? '描述' : 'Description']: a.description,
      }));
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(addrData), zh ? 'IP地址' : 'Addresses');
    }
    const ts = new Date().toISOString().replace(/[-:]/g, '').replace('T', '_').slice(0, 15);
    XLSX.writeFile(wb, zh ? `IP资源管理导出_${ts}.xlsx` : `ipam_export_${ts}.xlsx`);
  };

  const overallUtil = summary.total_capacity > 0 ? Math.round((summary.total_used / summary.total_capacity) * 100) : 0;
  const highUtilSubnets = subnets.filter((subnet) => subnet.utilization >= 80).length;
  const criticalUtilSubnets = subnets.filter((subnet) => subnet.utilization >= 90).length;
  const conflictHintText = useMemo(
    () =>
      `${conflicts.ip_conflicts
        .map((item) => `${item.address} ${item.subnets}`)
        .join(' ')} ${conflicts.mac_conflicts.map((item) => `${item.mac_address} ${item.addresses}`).join(' ')}`.toLowerCase(),
    [conflicts]
  );

  const subnetRiskScoreMap = useMemo(() => {
    const map = new Map<string, number>();
    subnets.forEach((subnet) => {
      const nameHint = `${subnet.name} ${subnet.network}/${subnet.prefix_len}`.toLowerCase();
      const hasConflictHint = conflictHintText.includes(subnet.network.toLowerCase()) || conflictHintText.includes(nameHint);
      const siteHint = String(subnet.site || '').toLowerCase();
      const criticalSite = ['core', 'prod', 'dc', 'edge'].some((keyword) => siteHint.includes(keyword));
      const baseScore = Math.min(60, Math.round(subnet.utilization * 0.6));
      const conflictScore = hasConflictHint ? 30 : 0;
      const siteScore = criticalSite ? 10 : 0;
      map.set(subnet.id, Math.min(100, baseScore + conflictScore + siteScore));
    });
    return map;
  }, [subnets, conflictHintText]);

  const riskSubnetCount = useMemo(
    () => subnets.filter((subnet) => (subnetRiskScoreMap.get(subnet.id) || 0) >= 70).length,
    [subnets, subnetRiskScoreMap]
  );

  const visibleSubnets = useMemo(() => {
    const filtered = subnets.filter((subnet) => {
      const riskScore = subnetRiskScoreMap.get(subnet.id) || 0;
      if (riskOnlyMode && riskScore < 70) return false;
      if (utilFilter === 'critical') return subnet.utilization >= 90;
      if (utilFilter === 'high') return subnet.utilization >= 80;
      return true;
    });
    if (subnetSort === 'name_asc') {
      return [...filtered].sort((left, right) =>
        String(left.name || `${left.network}/${left.prefix_len}`).localeCompare(
          String(right.name || `${right.network}/${right.prefix_len}`)
        )
      );
    }
    return [...filtered].sort(
      (left, right) =>
        (subnetRiskScoreMap.get(right.id) || 0) - (subnetRiskScoreMap.get(left.id) || 0) ||
        right.utilization - left.utilization ||
        String(left.network).localeCompare(String(right.network))
    );
  }, [subnets, utilFilter, subnetSort, riskOnlyMode, subnetRiskScoreMap]);

  const subnetTotalPages = Math.max(1, Math.ceil(visibleSubnets.length / subnetPageSizeOpt));
  const safeSubnetPage = Math.min(subnetPage, subnetTotalPages);
  const pagedVisibleSubnets = visibleSubnets.slice((safeSubnetPage - 1) * subnetPageSizeOpt, safeSubnetPage * subnetPageSizeOpt);

  const groupedSubnets = useMemo(() => {
    if (subnetGroupBy !== 'site') return null;
    const groups: Record<string, Subnet[]> = {};
    visibleSubnets.forEach((subnet) => {
      const key = subnet.site || (language === 'zh' ? '未分配站点' : 'Unassigned');
      if (!groups[key]) groups[key] = [];
      groups[key].push(subnet);
    });
    return Object.entries(groups).sort(([a], [b]) => a.localeCompare(b));
  }, [visibleSubnets, subnetGroupBy, language]);

  const toggleSiteCollapse = (site: string) => {
    setSiteCollapsed((prev) => ({ ...prev, [site]: !prev[site] }));
  };

  const blockMapData = useMemo(() => {
    if (!selectedSubnet) return null;
    if (detectIPVersion(selectedSubnet.network) !== 4) return null;
    if (selectedSubnet.total_ips > 1024) return null;
    const netNum = toNum(selectedSubnet.network);
    const count = selectedSubnet.total_ips + 2; // include network + broadcast
    const addrMap = new Map<number, IPAddress>();
    addresses.forEach((a) => {
      if (isValidIPv4(a.address)) addrMap.set(toNum(a.address), a);
    });
    const blocks: BlockMapItem[] = [];
    for (let i = 0; i < count; i++) {
      const ipNum = (netNum + i) >>> 0;
      const ip = [(ipNum >>> 24) & 0xff, (ipNum >>> 16) & 0xff, (ipNum >>> 8) & 0xff, ipNum & 0xff].join('.');
      const addr = addrMap.get(ipNum) || null;
      let type: BlockMapItem['type'] = 'free';
      if (i === 0) type = 'network';
      else if (i === count - 1) type = 'broadcast';
      else if (selectedSubnet.gateway && ip === selectedSubnet.gateway) type = 'gateway';
      else if (addr) type = (addr.status as BlockMapItem['type']) || 'active';
      blocks.push({ ip, ipNum, addr, type });
    }
    return blocks;
  }, [selectedSubnet, addresses]);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {apiError && (
        <div className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-red-50 border border-red-200 text-red-700 text-sm">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          <span className="flex-1">{apiError}</span>
          <button onClick={() => setApiError('')} title="关闭" className="text-red-400 hover:text-red-600">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
      <PageHero
        icon={Network}
        title={language === 'zh' ? 'IP/VLAN 资源管理' : 'IP/VLAN Management'}
        subtitle={language === 'zh' ? '子网与IP地址分配管理，冲突检测' : 'Subnet & IP address management with conflict detection'}
        actions={
          <>
            <button
              onClick={handleExport}
              className="p-1.5 rounded-lg border border-black/10 text-black/40 hover:text-[#00bceb] hover:border-[#00bceb]/30 transition-all"
              title={language === 'zh' ? '导出' : 'Export'}
            >
              <Download size={14} />
            </button>
            <button
              onClick={() => setShowAddSubnet(true)}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-[#00bceb] text-white text-sm font-semibold hover:bg-[#00a5d0] transition-all"
            >
              <Plus size={14} />
              {language === 'zh' ? '添加子网' : 'Add Subnet'}
            </button>
          </>
        }
      />

      <div className="flex-1 flex flex-col overflow-hidden px-6 py-5">
        <div className="bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden transition-all duration-300 flex-shrink-0">
          <button
            type="button"
            onClick={() => !selectedSubnet && setOverviewCollapsed((prev) => !prev)}
            className={`w-full flex items-center justify-between px-4 py-2.5 transition-colors ${
              selectedSubnet ? 'cursor-default' : 'hover:bg-black/[0.01]'
            }`}
          >
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-[#00172D]">{language === 'zh' ? '资源总览' : 'Resource Overview'}</h3>
              {(overviewCollapsed || selectedSubnet) && (
                <span className="text-[10px] text-black/40 tabular-nums">
                  {summary.total_subnets} {language === 'zh' ? '网段' : 'subnets'} · {overallUtil}% · {summary.total_used}/
                  {summary.total_capacity}
                </span>
              )}
              {conflicts.total_conflicts > 0 && (
                <span className="inline-flex items-center gap-1 rounded-full bg-red-50 border border-red-200 px-2 py-0.5 text-[11px] font-semibold text-red-600 animate-pulse">
                  <AlertTriangle size={11} />
                  {language === 'zh' ? `${conflicts.total_conflicts} 个冲突待处理` : `${conflicts.total_conflicts} conflicts`}
                </span>
              )}
            </div>
            {!selectedSubnet && (
              <ChevronDown
                size={14}
                className={`text-black/30 transition-transform duration-200 ${overviewCollapsed ? '-rotate-90' : ''}`}
              />
            )}
          </button>
          {!overviewCollapsed && !selectedSubnet && (
            <div className="px-4 pb-4">
              <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
                <div className="rounded-xl border border-black/8 px-4 py-3">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-black/30">
                    {language === 'zh' ? '子网总数' : 'Subnets'}
                  </p>
                  <p className="text-xl font-bold monitoring-data mt-1 text-[#00172D]">{summary.total_subnets}</p>
                </div>
                <div className="rounded-xl border border-black/8 px-4 py-3">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-black/30">
                    {language === 'zh' ? '总容量' : 'Total IPs'}
                  </p>
                  <p className="text-xl font-bold monitoring-data mt-1 text-[#00172D]">{summary.total_capacity}</p>
                </div>
                <div className="rounded-xl border border-black/8 px-4 py-3">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-black/30">
                    {language === 'zh' ? '已使用' : 'Used IPs'}
                  </p>
                  <p className="text-xl font-bold monitoring-data mt-1 text-[#00172D]">{summary.total_used}</p>
                </div>
                {/* Utilization - prominent colored card */}
                <div
                  className={`rounded-xl px-4 py-3 border ${
                    overallUtil >= 90
                      ? 'bg-red-50 border-red-200'
                      : overallUtil >= 80
                      ? 'bg-orange-50 border-orange-200'
                      : overallUtil >= 50
                      ? 'bg-blue-50 border-blue-200'
                      : 'bg-emerald-50 border-emerald-200'
                  }`}
                >
                  <p
                    className={`text-[10px] font-bold uppercase tracking-wider ${
                      overallUtil >= 90
                        ? 'text-red-500'
                        : overallUtil >= 80
                        ? 'text-orange-500'
                        : overallUtil >= 50
                        ? 'text-blue-500'
                        : 'text-emerald-500'
                    }`}
                  >
                    {language === 'zh' ? '利用率' : 'Utilization'}
                  </p>
                  <p className={`text-xl font-bold monitoring-data mt-1 ${utilColor(overallUtil)}`}>{overallUtil}%</p>
                  <div className="mt-1.5 h-1.5 bg-white/80 rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all duration-700"
                      style={{ width: `${Math.min(100, overallUtil)}%`, backgroundColor: utilBarColor(overallUtil) }}
                    />
                  </div>
                </div>
                {/* Risk - prominent colored card */}
                <div
                  className={`rounded-xl px-4 py-3 border ${
                    riskSubnetCount > 0 ? 'bg-red-50 border-red-200' : 'bg-emerald-50 border-emerald-200'
                  }`}
                >
                  <p className={`text-[10px] font-bold uppercase tracking-wider ${riskSubnetCount > 0 ? 'text-red-500' : 'text-emerald-500'}`}>
                    {language === 'zh' ? '高风险网段' : 'Risky Subnets'}
                  </p>
                  <div className="flex items-end gap-2 mt-1">
                    <p className={`text-xl font-bold monitoring-data ${riskSubnetCount > 0 ? 'text-red-600' : 'text-emerald-600'}`}>
                      {riskSubnetCount}
                    </p>
                    {riskSubnetCount === 0 && (
                      <span className="text-[11px] text-emerald-500 font-medium mb-0.5">
                        {language === 'zh' ? '无风险' : 'Clear'}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        <div className={`flex-1 min-h-0 ${selectedSubnet ? 'mt-3' : 'mt-3'} flex flex-col`}>
          <div className="flex-1 min-h-0">
            <div className={`${selectedSubnet ? 'flex xl:flex-row gap-3 h-full' : 'h-full'}`}>
              {/* ── Subnet List Panel ── */}
              <div
                className={`${selectedSubnet ? 'xl:w-[320px] 2xl:w-[360px] flex-shrink-0 flex flex-col' : 'w-full flex flex-col'}`}
              >
                <div
                  className={`bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden flex flex-col ${
                    selectedSubnet ? 'h-full' : ''
                  }`}
                >
                  <div className={`border-b border-black/5 bg-black/[0.02] flex-shrink-0 ${selectedSubnet ? 'px-3 py-2' : 'px-4 py-3'}`}>
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <div className="flex items-center gap-1.5">
                        {selectedSubnet && (
                          <button
                            onClick={() => {
                              setSelectedSubnet(null);
                              setAddresses([]);
                            }}
                            className="p-0.5 rounded hover:bg-black/5 text-black/40 hover:text-[#00bceb] transition-all"
                            title={language === 'zh' ? '返回列表' : 'Back to list'}
                          >
                            <ChevronLeft size={14} />
                          </button>
                        )}
                        <h3 className={`${selectedSubnet ? 'text-xs' : 'text-sm'} font-semibold text-[#00172D]`}>
                          {language === 'zh' ? '网段工作台' : 'Subnet Workspace'}
                        </h3>
                      </div>
                      <div className="flex items-center gap-1">
                        {!selectedSubnet && (
                          <div className="flex items-center gap-0.5 border border-black/8 rounded-lg p-0.5 mr-1">
                            <button
                              onClick={() => setSubnetViewMode('table')}
                              className={`p-1 rounded ${
                                subnetViewMode === 'table' ? 'bg-[#00bceb]/10 text-[#007b9a]' : 'text-black/30 hover:text-black/50'
                              }`}
                              title={language === 'zh' ? '表格视图' : 'Table view'}
                            >
                              <TableProperties size={12} />
                            </button>
                            <button
                              onClick={() => setSubnetViewMode('card')}
                              className={`p-1 rounded ${
                                subnetViewMode === 'card' ? 'bg-[#00bceb]/10 text-[#007b9a]' : 'text-black/30 hover:text-black/50'
                              }`}
                              title={language === 'zh' ? '卡片视图' : 'Card view'}
                            >
                              <LayoutGrid size={12} />
                            </button>
                          </div>
                        )}
                        <button
                          type="button"
                          onClick={() => setSubnetGroupBy((prev) => (prev === 'none' ? 'site' : 'none'))}
                          className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold transition-all ${
                            subnetGroupBy === 'site'
                              ? 'border-[#00bceb]/45 bg-[#00bceb]/10 text-[#007b9a]'
                              : 'border-black/10 text-black/50 hover:border-black/20 hover:text-black/70'
                          }`}
                          title={language === 'zh' ? '按站点分组' : 'Group by site'}
                        >
                          <FolderOpen size={11} />
                          {!selectedSubnet && <span>{language === 'zh' ? '站点' : 'Site'}</span>}
                        </button>
                        <button
                          type="button"
                          onClick={() => setSubnetSort((prev) => (prev === 'util_desc' ? 'name_asc' : 'util_desc'))}
                          className="inline-flex items-center gap-1 rounded-full border border-black/10 px-2 py-0.5 text-[10px] font-semibold text-black/50 transition-all hover:border-black/20 hover:text-black/70"
                          title={language === 'zh' ? '切换排序' : 'Toggle sort'}
                        >
                          <ChevronRight size={12} className={`transition-transform ${subnetSort === 'name_asc' ? 'rotate-90' : 'rotate-0'}`} />
                          {!selectedSubnet && <span>{subnetSort === 'util_desc' ? (language === 'zh' ? '风险' : 'Risk') : (language === 'zh' ? '名称' : 'Name')}</span>}
                        </button>
                      </div>
                    </div>
                    <div className="relative">
                      <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-black/30" />
                      <input
                        value={search}
                        onChange={(e) => {
                          setSearch(e.target.value);
                          setSubnetPage(1);
                        }}
                        placeholder={language === 'zh' ? '搜索子网/VLAN...' : 'Search subnets...'}
                        className={`w-full pl-9 pr-3 ${
                          selectedSubnet ? 'py-1.5 text-xs' : 'py-2 text-sm'
                        } border border-black/10 rounded-lg outline-none focus:border-[#00bceb]/50`}
                      />
                    </div>
                    {!selectedSubnet && (
                      <div className="flex items-center justify-between gap-2 mt-2">
                        <div className="flex items-center gap-1.5">
                          {([
                            { id: 'all', label: language === 'zh' ? '全部' : 'All', count: subnets.length },
                            { id: 'high', label: language === 'zh' ? '高利用率' : 'High', count: highUtilSubnets },
                            { id: 'critical', label: language === 'zh' ? '紧急' : 'Critical', count: criticalUtilSubnets },
                          ] as const).map((item) => (
                            <button
                              key={item.id}
                              type="button"
                              onClick={() => {
                                setUtilFilter(item.id);
                                setSubnetPage(1);
                              }}
                              className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[10px] font-semibold transition-all ${
                                utilFilter === item.id
                                  ? 'border-[#00bceb]/45 bg-[#00bceb]/10 text-[#007b9a]'
                                  : 'border-black/10 text-black/45 hover:border-black/20 hover:text-black/65'
                              }`}
                            >
                              <span>{item.label}</span>
                              <span className="monitoring-data">{item.count}</span>
                            </button>
                          ))}
                        </div>
                        <button
                          type="button"
                          onClick={() => {
                            setRiskOnlyMode((prev) => !prev);
                            setSubnetPage(1);
                          }}
                          className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[10px] font-semibold transition-all ${
                            riskOnlyMode
                              ? 'border-red-300 bg-red-50 text-red-700'
                              : 'border-black/15 text-black/55 hover:border-black/20 hover:text-black/70'
                          }`}
                        >
                          <CheckCircle2 size={11} />
                          {language === 'zh' ? '仅高风险' : 'High Risk Only'}
                        </button>
                      </div>
                    )}
                    {/* Batch delete toolbar */}
                    {!selectedSubnet && selectedSubnetIds.size > 0 && (
                      <div className="flex items-center justify-between gap-2 mt-2 px-1 py-1.5 rounded-lg bg-red-50 border border-red-200">
                        <span className="text-[11px] font-semibold text-red-700">
                          {language === 'zh' ? `已选 ${selectedSubnetIds.size} 个子网` : `${selectedSubnetIds.size} subnet(s) selected`}
                        </span>
                        <div className="flex items-center gap-1.5">
                          <button
                            type="button"
                            onClick={() => setSelectedSubnetIds(new Set())}
                            className="text-[10px] text-black/50 hover:text-black/70 underline"
                          >
                            {language === 'zh' ? '取消选择' : 'Clear'}
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              setConfirmDelete({
                                type: 'batch-subnet',
                                id: Array.from(selectedSubnetIds).join(','),
                                label: String(selectedSubnetIds.size),
                              })
                            }
                            className="inline-flex items-center gap-1 rounded-lg bg-red-500 hover:bg-red-600 text-white px-2.5 py-1 text-[11px] font-semibold transition-colors"
                          >
                            <Trash2 size={12} />
                            {language === 'zh' ? '批量删除' : 'Delete Selected'}
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                  <div className={`flex-1 min-h-0 overflow-y-auto ${subnetViewMode === 'card' ? 'divide-y divide-black/5' : ''}`}>
                    {visibleSubnets.length === 0 && !loading && (
                      subnets.length === 0 ? (
                        <div className="py-16 flex flex-col items-center justify-center gap-4">
                          <div className="w-16 h-16 rounded-2xl bg-[#00bceb]/10 flex items-center justify-center">
                            <Network size={28} className="text-[#00bceb]" />
                          </div>
                          <div className="text-center">
                            <p className="text-sm font-semibold text-[#00172D]">{language === 'zh' ? '还没有子网' : 'No subnets yet'}</p>
                            <p className="text-xs text-black/40 mt-1 max-w-xs">
                              {language === 'zh'
                                ? '添加第一个子网来开始管理IP地址分配和VLAN规划。'
                                : 'Add your first subnet to start managing IP allocation and VLAN planning.'}
                            </p>
                          </div>
                          <button
                            onClick={() => setShowAddSubnet(true)}
                            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-[#00bceb] text-white text-sm font-semibold hover:bg-[#00a5d0] transition-all shadow-lg shadow-[#00bceb]/20"
                          >
                            <Plus size={14} />
                            {language === 'zh' ? '添加第一个子网' : 'Add First Subnet'}
                          </button>
                        </div>
                      ) : (
                        <div className="py-12 text-center text-sm text-black/30">
                          {language === 'zh' ? '当前筛选条件下没有子网' : 'No subnets under current filter.'}
                        </div>
                      )
                    )}
                    {subnetViewMode === 'table' || selectedSubnet ? (
                      /* ── Subnet Table View (always table when detail is open) ── */
                      <table className="w-full text-left border-collapse">
                        {!selectedSubnet && (
                          <thead>
                            <tr className="bg-black/[0.02] border-b border-black/5">
                              <th className="px-2 py-2 w-8">
                                <input
                                  type="checkbox"
                                  className="accent-[#00bceb] w-3.5 h-3.5 cursor-pointer"
                                  checked={pagedVisibleSubnets.length > 0 && pagedVisibleSubnets.every((s) => selectedSubnetIds.has(s.id))}
                                  onChange={(e) => {
                                    const next = new Set(selectedSubnetIds);
                                    if (e.target.checked) {
                                      pagedVisibleSubnets.forEach((s) => next.add(s.id));
                                    } else {
                                      pagedVisibleSubnets.forEach((s) => next.delete(s.id));
                                    }
                                    setSelectedSubnetIds(next);
                                  }}
                                />
                              </th>
                              <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-widest text-black/40">
                                {language === 'zh' ? '名称' : 'Name'}
                              </th>
                              <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-widest text-black/40">
                                {language === 'zh' ? '网段' : 'CIDR'}
                              </th>
                              <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-widest text-black/40 hidden lg:table-cell">
                                VLAN
                              </th>
                              <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-widest text-black/40 hidden xl:table-cell">
                                {language === 'zh' ? '站点' : 'Site'}
                              </th>
                              <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-widest text-black/40 text-right">
                                {language === 'zh' ? '利用率' : 'Util'}
                              </th>
                              <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-widest text-black/40 text-right hidden sm:table-cell">
                                {language === 'zh' ? '已用/总量' : 'Used/Total'}
                              </th>
                              <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-widest text-black/40 text-right hidden md:table-cell">
                                RISK
                              </th>
                              <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-widest text-black/40 w-8"></th>
                            </tr>
                          </thead>
                        )}
                        <tbody>
                          {pagedVisibleSubnets.map((subnet) => {
                            const riskScore = subnetRiskScoreMap.get(subnet.id) || 0;
                            return selectedSubnet ? (
                              /* Compact row when detail panel is open */
                              <tr
                                key={subnet.id}
                                onClick={() => {
                                  if (selectedSubnet?.id === subnet.id) {
                                    setSelectedSubnet(null);
                                    setAddresses([]);
                                  } else {
                                    loadAddresses(subnet);
                                  }
                                }}
                                className={`group/row border-b border-black/5 cursor-pointer hover:bg-black/[0.015] transition-colors ${
                                  selectedSubnet?.id === subnet.id ? 'bg-[#00bceb]/5 border-l-2 border-l-[#00bceb]' : ''
                                }`}
                              >
                                <td className="px-2.5 py-1.5">
                                  <div className="flex items-center gap-1.5 min-w-0">
                                    <Network size={10} className="text-[#00bceb] flex-shrink-0" />
                                    <span className="text-[11px] font-semibold text-[#00172D] truncate">
                                      {subnet.name || `${subnet.network}/${subnet.prefix_len}`}
                                    </span>
                                  </div>
                                  <div className="flex items-center gap-2 mt-0.5">
                                    <span className="text-[10px] font-mono text-black/40">
                                      {subnet.network}/{subnet.prefix_len}
                                    </span>
                                    <span className={`text-[10px] font-bold tabular-nums ${utilColor(subnet.utilization)}`}>
                                      {subnet.utilization}%
                                    </span>
                                  </div>
                                </td>
                              </tr>
                            ) : (
                              <tr
                                key={subnet.id}
                                onClick={() => {
                                  if (selectedSubnet?.id === subnet.id) {
                                    setSelectedSubnet(null);
                                    setAddresses([]);
                                  } else {
                                    loadAddresses(subnet);
                                  }
                                }}
                                className={`group/row border-b border-black/5 cursor-pointer hover:bg-black/[0.015] transition-colors ${
                                  selectedSubnet?.id === subnet.id ? 'bg-[#00bceb]/5' : ''
                                } ${selectedSubnetIds.has(subnet.id) ? 'bg-[#00bceb]/[0.04]' : ''}`}
                              >
                                <td className="px-2 py-2 w-8" onClick={(e) => e.stopPropagation()}>
                                  <input
                                    type="checkbox"
                                    className="accent-[#00bceb] w-3.5 h-3.5 cursor-pointer"
                                    checked={selectedSubnetIds.has(subnet.id)}
                                    onChange={() => {
                                      const next = new Set(selectedSubnetIds);
                                      if (next.has(subnet.id)) next.delete(subnet.id);
                                      else next.add(subnet.id);
                                      setSelectedSubnetIds(next);
                                    }}
                                  />
                                </td>
                                <td className="px-3 py-2">
                                  <div className="flex items-center gap-1.5">
                                    <Network size={12} className="text-[#00bceb] flex-shrink-0" />
                                    <span className="text-xs font-semibold text-[#00172D] truncate max-w-[180px]">
                                      {subnet.name || '-'}
                                    </span>
                                    <span
                                      role="button"
                                      title={language === 'zh' ? '编辑' : 'Edit'}
                                      onClick={(e) => openEditSubnet(subnet, e)}
                                      className="opacity-0 group-hover/row:opacity-100 p-0.5 rounded hover:bg-black/10 text-black/30 hover:text-black/60 transition-all"
                                    >
                                      <Pencil size={10} />
                                    </span>
                                  </div>
                                </td>
                                <td className="px-3 py-2 text-xs font-mono text-black/60">
                                  {subnet.network}/{subnet.prefix_len}
                                </td>
                                <td className="px-3 py-2 text-xs text-black/50 tabular-nums hidden lg:table-cell">
                                  {subnet.vlan_id || '-'}
                                </td>
                                <td className="px-3 py-2 text-xs text-black/50 truncate max-w-[100px] hidden xl:table-cell">
                                  {subnet.site || '-'}
                                </td>
                                <td className="px-3 py-2 text-right">
                                  <div className="flex items-center justify-end gap-2">
                                    <div className="w-16 h-1.5 bg-black/5 rounded-full overflow-hidden hidden sm:block">
                                      <div
                                        className="h-full rounded-full transition-all duration-500"
                                        style={{
                                          width: `${Math.min(100, subnet.utilization)}%`,
                                          backgroundColor: utilBarColor(subnet.utilization),
                                        }}
                                      />
                                    </div>
                                    <span className={`text-xs font-bold tabular-nums ${utilColor(subnet.utilization)}`}>
                                      {subnet.utilization}%
                                    </span>
                                  </div>
                                </td>
                                <td className="px-3 py-2 text-[11px] text-black/40 tabular-nums text-right hidden sm:table-cell">
                                  {subnet.used_ips}/{subnet.total_ips}
                                </td>
                                <td
                                  className={`px-3 py-2 text-[11px] font-semibold tabular-nums text-right hidden md:table-cell ${
                                    riskScore > 0 ? 'text-red-500' : 'text-black/25'
                                  }`}
                                >
                                  {riskScore}
                                </td>
                                <td className="px-3 py-2">
                                  <ChevronRight
                                    size={12}
                                    className={`text-black/20 transition-transform ${
                                      selectedSubnet?.id === subnet.id ? 'rotate-90 text-[#00bceb]' : ''
                                    }`}
                                  />
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    ) : subnetGroupBy === 'site' && groupedSubnets ? (
                      groupedSubnets.map(([siteName, siteSubnets]) => {
                        const collapsed = siteCollapsed[siteName] ?? false;
                        const siteUtil =
                          siteSubnets.length > 0
                            ? Math.round(
                                siteSubnets.reduce((s, sub) => s + sub.used_ips, 0) /
                                  Math.max(1, siteSubnets.reduce((s, sub) => s + sub.total_ips, 0)) *
                                  100
                              )
                            : 0;
                        return (
                          <div key={siteName}>
                            <button
                              type="button"
                              onClick={() => toggleSiteCollapse(siteName)}
                              className="w-full flex items-center justify-between px-4 py-2 bg-black/[0.03] hover:bg-black/[0.05] transition-colors border-b border-black/5"
                            >
                              <div className="flex items-center gap-2">
                                <ChevronDown size={12} className={`transition-transform text-black/40 ${collapsed ? '-rotate-90' : ''}`} />
                                <FolderOpen size={13} className="text-[#00bceb]" />
                                <span className="text-xs font-semibold text-[#00172D]">{siteName}</span>
                                <span className="text-[10px] text-black/35 tabular-nums">{siteSubnets.length}</span>
                              </div>
                              <div className="flex items-center gap-2">
                                <div className="w-16 h-1 bg-black/5 rounded-full overflow-hidden">
                                  <div className="h-full rounded-full" style={{ width: `${Math.min(100, siteUtil)}%`, backgroundColor: utilBarColor(siteUtil) }} />
                                </div>
                                <span className={`text-[10px] font-bold tabular-nums ${utilColor(siteUtil)}`}>{siteUtil}%</span>
                              </div>
                            </button>
                            {!collapsed &&
                              siteSubnets.map((subnet) => (
                                <button
                                  key={subnet.id}
                                  onClick={() => {
                                    if (selectedSubnet?.id === subnet.id) {
                                      setSelectedSubnet(null);
                                      setAddresses([]);
                                    } else {
                                      loadAddresses(subnet);
                                    }
                                  }}
                                  className={`group/subnet w-full text-left px-4 ${
                                    compactSubnetList ? 'py-1.5' : 'py-2.5'
                                  } hover:bg-black/[0.02] transition-colors ${
                                    selectedSubnet?.id === subnet.id ? 'bg-[#00bceb]/5 border-l-[3px] border-l-[#00bceb]' : ''
                                  }`}
                                >
                                  <div className="flex items-center justify-between">
                                    <div className="flex-1 min-w-0">
                                      <div className="flex items-center gap-2">
                                        <Network size={compactSubnetList ? 10 : 12} className="text-[#00bceb] flex-shrink-0" />
                                        <p className={`${compactSubnetList ? 'text-[11px]' : 'text-xs'} font-semibold text-[#00172D] truncate`}>
                                          {subnet.name || `${subnet.network}/${subnet.prefix_len}`}
                                        </p>
                                        <span
                                          role="button"
                                          title={language === 'zh' ? '编辑子网' : 'Edit subnet'}
                                          onClick={(e) => openEditSubnet(subnet, e)}
                                          className="opacity-0 group-hover/subnet:opacity-100 p-0.5 rounded hover:bg-black/10 text-black/30 hover:text-black/60 transition-all"
                                        >
                                          <Pencil size={10} />
                                        </span>
                                      </div>
                                      {!compactSubnetList && (
                                        <p className="text-[10px] text-black/35 mt-0.5 truncate">
                                          {subnet.network}/{subnet.prefix_len} {subnet.vlan_id ? `· V${subnet.vlan_id}` : ''}
                                        </p>
                                      )}
                                    </div>
                                    <div className="text-right flex-shrink-0 ml-2">
                                      <p className={`text-[11px] font-bold tabular-nums ${utilColor(subnet.utilization)}`}>
                                        {subnet.utilization}%
                                      </p>
                                      {!compactSubnetList && <p className="text-[9px] text-black/30 tabular-nums">{subnet.used_ips}/{subnet.total_ips}</p>}
                                    </div>
                                  </div>
                                  {!compactSubnetList && (
                                    <div className="mt-1.5 h-1 bg-black/5 rounded-full overflow-hidden">
                                      <div
                                        className="h-full rounded-full transition-all duration-500"
                                        style={{ width: `${Math.min(100, subnet.utilization)}%`, backgroundColor: utilBarColor(subnet.utilization) }}
                                      />
                                    </div>
                                  )}
                                </button>
                              ))}
                          </div>
                        );
                      })
                    ) : (
                      pagedVisibleSubnets.map((subnet) => (
                        <button
                          key={subnet.id}
                          onClick={() => {
                            if (selectedSubnet?.id === subnet.id) {
                              setSelectedSubnet(null);
                              setAddresses([]);
                            } else {
                              loadAddresses(subnet);
                            }
                          }}
                          className={`group/subnet w-full text-left px-4 ${
                            compactSubnetList ? 'py-1.5' : 'py-3'
                          } hover:bg-black/[0.02] transition-colors ${
                            selectedSubnet?.id === subnet.id ? 'bg-[#00bceb]/5 border-l-[3px] border-l-[#00bceb]' : ''
                          }`}
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2">
                                <Network size={compactSubnetList ? 11 : 14} className="text-[#00bceb] flex-shrink-0" />
                                <p className={`${compactSubnetList ? 'text-xs' : 'text-sm'} font-semibold text-[#00172D] truncate`}>
                                  {subnet.name || `${subnet.network}/${subnet.prefix_len}`}
                                </p>
                                <span
                                  role="button"
                                  title={language === 'zh' ? '编辑子网' : 'Edit subnet'}
                                  onClick={(e) => openEditSubnet(subnet, e)}
                                  className="opacity-0 group-hover/subnet:opacity-100 p-0.5 rounded hover:bg-black/10 text-black/30 hover:text-black/60 transition-all"
                                >
                                  <Pencil size={12} />
                                </span>
                              </div>
                              {!compactSubnetList && (
                                <p className="text-[11px] text-black/40 mt-0.5">
                                  {subnet.network}/{subnet.prefix_len} {subnet.vlan_id ? `· VLAN ${subnet.vlan_id}` : ''}{' '}
                                  {subnet.site ? `· ${subnet.site}` : ''}
                                </p>
                              )}
                            </div>
                            <div className="text-right flex-shrink-0 ml-2">
                              {!compactSubnetList && (
                                <p className="text-[10px] font-semibold text-black/35 monitoring-data">
                                  RISK {subnetRiskScoreMap.get(subnet.id) || 0}
                                </p>
                              )}
                              <p className={`${compactSubnetList ? 'text-[11px]' : 'text-xs'} font-bold monitoring-data ${utilColor(subnet.utilization)}`}>
                                {subnet.utilization}%
                              </p>
                              {!compactSubnetList && <p className="text-[10px] text-black/30 monitoring-data">{subnet.used_ips}/{subnet.total_ips}</p>}
                            </div>
                          </div>
                          {!compactSubnetList && (
                            <div className="mt-2 h-1.5 bg-black/5 rounded-full overflow-hidden">
                              <div
                                className="h-full rounded-full transition-all duration-500"
                                style={{ width: `${Math.min(100, subnet.utilization)}%`, backgroundColor: utilBarColor(subnet.utilization) }}
                              />
                            </div>
                          )}
                        </button>
                      ))
                    )}
                  </div>
                  {/* Subnet pagination */}
                  {subnetGroupBy === 'none' && visibleSubnets.length > 0 && (
                    <div className={`${selectedSubnet ? 'px-2 py-1.5' : ''} border-t border-black/5 flex-shrink-0`}>
                      {selectedSubnet ? (
                        <div className="flex items-center justify-between">
                          <span className="text-[10px] text-black/35 tabular-nums">
                            {safeSubnetPage}/{subnetTotalPages}
                          </span>
                          <div className="flex items-center gap-1">
                            <button
                              disabled={safeSubnetPage <= 1}
                              onClick={() => setSubnetPage(safeSubnetPage - 1)}
                              title={language === 'zh' ? '上一页' : 'Previous'}
                              className="p-1 rounded border border-black/8 hover:bg-black/5 disabled:opacity-30 transition-all"
                            >
                              <ChevronLeft size={11} />
                            </button>
                            <button
                              disabled={safeSubnetPage >= subnetTotalPages}
                              onClick={() => setSubnetPage(safeSubnetPage + 1)}
                              title={language === 'zh' ? '下一页' : 'Next'}
                              className="p-1 rounded border border-black/8 hover:bg-black/5 disabled:opacity-30 transition-all"
                            >
                              <ChevronRight size={11} />
                            </button>
                          </div>
                        </div>
                      ) : (
                        <Pagination
                          currentPage={safeSubnetPage}
                          totalItems={visibleSubnets.length}
                          itemsPerPage={subnetPageSizeOpt}
                          onPageChange={setSubnetPage}
                          onItemsPerPageChange={(v) => {
                            setSubnetPageSizeOpt(v);
                            setSubnetPage(1);
                          }}
                          language={language}
                        />
                      )}
                    </div>
                  )}
                </div>
              </div>

              {/* ── Selected Subnet Detail Panel (side-by-side on xl) ── */}
              {selectedSubnet && (
                <div className="flex-1 min-w-0 min-h-0 flex flex-col">
                  <div className="bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden flex-1 min-h-0 flex flex-col">
                    <div className="flex flex-col h-full">
                      <div className="px-4 py-3 border-b border-black/5 bg-gradient-to-r from-[#00bceb]/5 to-transparent flex-shrink-0">
                        <div className="flex items-center justify-between mb-3">
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2">
                              <button
                                onClick={() => {
                                  setSelectedSubnet(null);
                                  setAddresses([]);
                                }}
                                className="p-1 rounded-lg border border-black/10 text-black/40 hover:text-[#00bceb] hover:border-[#00bceb]/30 transition-all xl:hidden"
                                title={language === 'zh' ? '返回列表' : 'Back'}
                              >
                                <ChevronLeft size={14} />
                              </button>
                              <Network size={16} className="text-[#00bceb]" />
                              <p className="text-base font-bold text-[#00172D]">
                                {selectedSubnet.name || `${selectedSubnet.network}/${selectedSubnet.prefix_len}`}
                              </p>
                            </div>
                            <p className="text-[11px] text-black/40 mt-0.5 ml-6">
                              {selectedSubnet.network}/{selectedSubnet.prefix_len}
                              {selectedSubnet.vlan_id ? ` · VLAN ${selectedSubnet.vlan_id}` : ''}
                              {selectedSubnet.vlan_name ? ` (${selectedSubnet.vlan_name})` : ''}
                              {selectedSubnet.site ? ` · ${selectedSubnet.site}` : ''}
                            </p>
                          </div>
                        </div>
                        <div className="flex gap-2 items-center flex-shrink-0 justify-between">
                          <div className="relative">
                            <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-black/25" />
                            <input
                              value={addrSearch}
                              onChange={(e) => {
                                setAddrSearch(e.target.value);
                                setAddrPage(1);
                              }}
                              placeholder={language === 'zh' ? '搜索IP/主机/MAC...' : 'Search IP/host/MAC...'}
                              className="pl-7 pr-2 py-1.5 text-xs border border-black/10 rounded-lg outline-none focus:border-[#00bceb]/50 w-40"
                            />
                            {addrSearch && (
                              <button
                                onClick={() => {
                                  setAddrSearch('');
                                  setAddrPage(1);
                                }}
                                className="absolute right-2 top-1/2 -translate-y-1/2 text-black/25 hover:text-black/50"
                              >
                                <X size={11} />
                              </button>
                            )}
                          </div>
                          <div className="flex gap-2 items-center">
                            <button
                              onClick={() => setShowAddIP(true)}
                              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#00bceb] text-white text-xs font-semibold hover:bg-[#00a5d0] transition-all"
                            >
                              <Plus size={12} />
                              {language === 'zh' ? '添加IP' : 'Add IP'}
                            </button>
                            <button
                              onClick={() =>
                                setConfirmDelete({
                                  type: 'subnet',
                                  id: selectedSubnet.id,
                                  label: selectedSubnet.name || `${selectedSubnet.network}/${selectedSubnet.prefix_len}`,
                                })
                              }
                              className="p-1.5 rounded-lg border border-black/10 text-black/40 hover:text-red-500 hover:border-red-300 transition-all"
                              title={language === 'zh' ? '删除子网' : 'Delete Subnet'}
                            >
                              <Trash2 size={14} />
                            </button>
                            <button
                              onClick={() => {
                                setSelectedSubnet(null);
                                setAddresses([]);
                              }}
                              className="p-1.5 rounded-lg border border-black/10 text-black/40 hover:text-[#00bceb] hover:border-[#00bceb]/30 transition-all"
                              title={language === 'zh' ? '收起' : 'Collapse'}
                            >
                              <ChevronUp size={14} />
                            </button>
                          </div>
                        </div>
                        {/* Subnet summary cards */}
                        <div className="grid grid-cols-4 gap-2 mt-1.5">
                          <div className="rounded-lg bg-white/80 border border-black/6 px-2.5 py-1.5 text-center">
                            <p className="text-[9px] font-bold uppercase tracking-wider text-black/30">
                              {language === 'zh' ? '总容量' : 'Capacity'}
                            </p>
                            <p className="text-sm font-bold text-[#00172D] monitoring-data mt-0.5">{selectedSubnet.total_ips}</p>
                          </div>
                          <div className="rounded-lg bg-white/80 border border-black/6 px-2.5 py-1.5 text-center">
                            <p className="text-[9px] font-bold uppercase tracking-wider text-black/30">
                              {language === 'zh' ? '已分配' : 'Assigned'}
                            </p>
                            <p className="text-sm font-bold text-[#00bceb] monitoring-data mt-0.5">{addresses.length}</p>
                          </div>
                          <div className="rounded-lg bg-white/80 border border-black/6 px-2.5 py-1.5 text-center">
                            <p className="text-[9px] font-bold uppercase tracking-wider text-black/30">
                              {language === 'zh' ? '已使用' : 'Used'}
                            </p>
                            <p className={`text-sm font-bold monitoring-data mt-0.5 ${utilColor(selectedSubnet.utilization)}`}>
                              {selectedSubnet.used_ips}
                            </p>
                          </div>
                          <div className="rounded-lg bg-white/80 border border-black/6 px-2.5 py-1.5 text-center">
                            <p className="text-[9px] font-bold uppercase tracking-wider text-black/30">
                              {language === 'zh' ? '可用' : 'Available'}
                            </p>
                            <p className="text-sm font-bold text-emerald-600 monitoring-data mt-0.5">
                              {Math.max(0, selectedSubnet.total_ips - selectedSubnet.used_ips)}
                            </p>
                          </div>
                        </div>
                        {selectedSubnet.gateway && (
                          <p className="text-[10px] text-black/35 mt-2 ml-0.5">
                            Gateway: <span className="font-mono font-semibold text-black/50">{selectedSubnet.gateway}</span>
                          </p>
                        )}
                        {/* Utilization bar */}
                        <div className="mt-2 flex items-center gap-2">
                          <div className="flex-1 h-2 bg-black/5 rounded-full overflow-hidden">
                            <div
                              className="h-full rounded-full transition-all duration-700"
                              style={{
                                width: `${Math.min(100, selectedSubnet.utilization)}%`,
                                backgroundColor: utilBarColor(selectedSubnet.utilization),
                              }}
                            />
                          </div>
                          <span className={`text-[11px] font-bold monitoring-data ${utilColor(selectedSubnet.utilization)}`}>
                            {selectedSubnet.utilization}%
                          </span>
                        </div>
                        {/* Status filter tabs + device type filter + view toggle */}
                        <div className="mt-3 flex items-center justify-between gap-2 flex-wrap">
                          <div className="flex items-center gap-1.5 flex-wrap">
                            {([
                              { id: 'all' as const, label: language === 'zh' ? '全部' : 'All', count: addrStatusCounts.all },
                              { id: 'active' as const, label: language === 'zh' ? '在用' : 'Active', count: addrStatusCounts.active },
                              { id: 'reserved' as const, label: language === 'zh' ? '预留' : 'Reserved', count: addrStatusCounts.reserved },
                              { id: 'deprecated' as const, label: language === 'zh' ? '停用' : 'Deprecated', count: addrStatusCounts.deprecated },
                            ] as const).map((tab) => (
                              <button
                                key={tab.id}
                                onClick={() => {
                                  setAddrStatusFilter(tab.id);
                                  setAddrPage(1);
                                }}
                                className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold transition-all ${
                                  addrStatusFilter === tab.id
                                    ? 'border-[#00bceb]/45 bg-[#00bceb]/10 text-[#007b9a]'
                                    : 'border-black/8 text-black/40 hover:border-black/15 hover:text-black/55'
                                }`}
                              >
                                {tab.label}
                                <span className="tabular-nums">{tab.count}</span>
                              </button>
                            ))}
                            <span className="w-px h-4 bg-black/10 mx-0.5" />
                            {DEVICE_TYPES.filter((dt) => dt.value && (addrDeviceTypeCounts[dt.value] || 0) > 0).map((dt) => (
                              <button
                                key={dt.value}
                                onClick={() => {
                                  setAddrDeviceTypeFilter((prev) => (prev === dt.value ? '' : dt.value));
                                  setAddrPage(1);
                                }}
                                className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold transition-all ${
                                  addrDeviceTypeFilter === dt.value
                                    ? 'border-[#00bceb]/45 bg-[#00bceb]/10 text-[#007b9a]'
                                    : 'border-black/8 text-black/40 hover:border-black/15 hover:text-black/55'
                                }`}
                                title={dt.label[language === 'zh' ? 'zh' : 'en']}
                              >
                                <span
                                  className={`inline-flex items-center justify-center w-4 h-4 rounded text-[8px] font-bold ${dt.color}`}
                                >
                                  {dt.icon}
                                </span>
                                <span className="tabular-nums">{addrDeviceTypeCounts[dt.value] || 0}</span>
                              </button>
                            ))}
                          </div>
                          <div className="flex items-center gap-0.5 border border-black/8 rounded-lg p-0.5">
                            <button
                              onClick={() => setAddrViewMode('table')}
                              className={`p-1 rounded ${
                                addrViewMode === 'table' ? 'bg-[#00bceb]/10 text-[#007b9a]' : 'text-black/30 hover:text-black/50'
                              }`}
                              title={language === 'zh' ? '表格视图' : 'Table view'}
                            >
                              <LayoutList size={13} />
                            </button>
                            <button
                              onClick={() => setAddrViewMode('card')}
                              className={`p-1 rounded ${
                                addrViewMode === 'card' ? 'bg-[#00bceb]/10 text-[#007b9a]' : 'text-black/30 hover:text-black/50'
                              }`}
                              title={language === 'zh' ? '卡片视图' : 'Card view'}
                            >
                              <LayoutGrid size={13} />
                            </button>
                            {blockMapData && (
                              <button
                                onClick={() => setAddrViewMode('block')}
                                className={`p-1 rounded ${
                                  addrViewMode === 'block' ? 'bg-[#00bceb]/10 text-[#007b9a]' : 'text-black/30 hover:text-black/50'
                                }`}
                                title={language === 'zh' ? '色块视图' : 'Block map'}
                              >
                                <Grid3x3 size={13} />
                              </button>
                            )}
                          </div>
                        </div>
                      </div>

                      <div className="flex-1 min-h-0 overflow-y-auto">
                        {addrViewMode === 'block' && blockMapData ? (
                          /* ── IP Block Map (Heatmap) ── */
                          <IPBlockMap language={language} blockMapData={blockMapData} onSelectAddress={openEditIP} />
                        ) : addrViewMode === 'table' ? (
                          <table className="w-full text-left border-collapse">
                            <thead>
                              <tr className="bg-black/[0.01] border-b border-black/5">
                                <th className="px-3 py-2.5 text-[10px] font-bold uppercase tracking-widest text-black/40">
                                  {language === 'zh' ? 'IP地址' : 'Address'}
                                </th>
                                <th className="px-3 py-2.5 text-[10px] font-bold uppercase tracking-widest text-black/40">
                                  {language === 'zh' ? '主机名' : 'Hostname'}
                                </th>
                                <th className="px-3 py-2.5 text-[10px] font-bold uppercase tracking-widest text-black/40 hidden xl:table-cell">
                                  {language === 'zh' ? '类型' : 'Type'}
                                </th>
                                <th className="px-3 py-2.5 text-[10px] font-bold uppercase tracking-widest text-black/40 hidden 2xl:table-cell">
                                  {language === 'zh' ? '接口' : 'Interface'}
                                </th>
                                <th className="px-3 py-2.5 text-[10px] font-bold uppercase tracking-widest text-black/40">
                                  {language === 'zh' ? '状态' : 'Status'}
                                </th>
                                <th className="px-3 py-2.5 text-[10px] font-bold uppercase tracking-widest text-black/40 w-16"></th>
                              </tr>
                            </thead>
                            <tbody>
                              {pagedAddresses.length === 0 && (
                                <tr>
                                  <td colSpan={6} className="px-4 py-12 text-center text-sm text-black/30">
                                    {addrSearch || addrStatusFilter !== 'all'
                                      ? language === 'zh'
                                        ? '无匹配结果'
                                        : 'No matches'
                                      : language === 'zh'
                                      ? '暂无IP分配记录'
                                      : 'No IP assignments'}
                                  </td>
                                </tr>
                              )}
                              {pagedAddresses.map((addr) => {
                                const statusBadge =
                                  addr.status === 'reserved'
                                    ? { bg: 'bg-amber-50 border-amber-200 text-amber-700', label: language === 'zh' ? '预留' : 'Reserved' }
                                    : addr.status === 'deprecated'
                                    ? { bg: 'bg-gray-100 border-gray-300 text-gray-500', label: language === 'zh' ? '停用' : 'Deprecated' }
                                    : { bg: 'bg-emerald-50 border-emerald-200 text-emerald-700', label: language === 'zh' ? '在用' : 'Active' };
                                const dtMeta = DEVICE_TYPES.find((d) => d.value === (addr.device_type || '')) || DEVICE_TYPES[0];
                                return (
                                  <tr
                                    key={addr.id}
                                    className={`border-b border-black/5 hover:bg-black/[0.01] group/row ${
                                      addr.status === 'deprecated' ? 'opacity-50' : ''
                                    }`}
                                  >
                                    <td className="px-3 py-2 text-sm font-mono font-semibold text-[#00172D]">{addr.address}</td>
                                    <td className="px-3 py-2 text-xs text-black/60">{addr.hostname || '-'}</td>
                                    <td className="px-3 py-2 hidden xl:table-cell">
                                      {addr.device_type ? (
                                        <span
                                          className={`inline-flex items-center justify-center w-5 h-5 rounded text-[8px] font-bold ${dtMeta.color}`}
                                          title={dtMeta.label[language === 'zh' ? 'zh' : 'en']}
                                        >
                                          {dtMeta.icon}
                                        </span>
                                      ) : (
                                        <span className="text-xs text-black/25">-</span>
                                      )}
                                    </td>
                                    <td className="px-3 py-2 text-xs text-black/60 hidden 2xl:table-cell">{addr.interface_name || '-'}</td>
                                    <td className="px-3 py-2">
                                      <span
                                        className={`inline-flex items-center rounded-full border px-1.5 py-0.5 text-[9px] font-semibold ${statusBadge.bg}`}
                                      >
                                        {statusBadge.label}
                                      </span>
                                    </td>
                                    <td className="px-3 py-2">
                                      <div className="flex items-center gap-0.5 opacity-0 group-hover/row:opacity-100 transition-opacity">
                                        <button
                                          onClick={() => openEditIP(addr)}
                                          className="p-1 rounded text-black/25 hover:text-[#00bceb] transition-colors"
                                          title={language === 'zh' ? '编辑' : 'Edit'}
                                        >
                                          <Pencil size={13} />
                                        </button>
                                        <button
                                          onClick={() => setConfirmDelete({ type: 'ip', id: addr.id, label: addr.address })}
                                          className="p-1 rounded text-black/25 hover:text-red-500 transition-colors"
                                          title={language === 'zh' ? '删除' : 'Delete'}
                                        >
                                          <Trash2 size={13} />
                                        </button>
                                      </div>
                                    </td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        ) : (
                          /* Card view for dense display */
                          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2 p-3">
                            {pagedAddresses.length === 0 && (
                              <div className="col-span-full py-12 text-center text-sm text-black/30">
                                {addrSearch || addrStatusFilter !== 'all' || addrDeviceTypeFilter
                                  ? language === 'zh'
                                    ? '无匹配结果'
                                    : 'No matches'
                                  : language === 'zh'
                                  ? '暂无IP分配记录'
                                  : 'No IP assignments'}
                              </div>
                            )}
                            {pagedAddresses.map((addr) => {
                              const statusBadge =
                                addr.status === 'reserved'
                                  ? {
                                      bg: 'bg-amber-50 border-amber-200 text-amber-700',
                                      label: language === 'zh' ? '预留' : 'Reserved',
                                      dot: 'bg-amber-400',
                                    }
                                  : addr.status === 'deprecated'
                                  ? {
                                      bg: 'bg-gray-100 border-gray-300 text-gray-500',
                                      label: language === 'zh' ? '停用' : 'Deprecated',
                                      dot: 'bg-gray-400',
                                    }
                                  : {
                                      bg: 'bg-emerald-50 border-emerald-200 text-emerald-700',
                                      label: language === 'zh' ? '在用' : 'Active',
                                      dot: 'bg-emerald-400',
                                    };
                              const dtMeta = DEVICE_TYPES.find((d) => d.value === (addr.device_type || '')) || DEVICE_TYPES[0];
                              return (
                                <div
                                  key={addr.id}
                                  className={`group/card relative rounded-xl border border-black/8 px-3 py-2.5 hover:border-[#00bceb]/30 hover:shadow-sm transition-all cursor-default ${
                                    addr.status === 'deprecated' ? 'opacity-50' : ''
                                  }`}
                                >
                                  <div className="flex items-center justify-between gap-1">
                                    <p className="text-xs font-mono font-bold text-[#00172D] truncate">{addr.address}</p>
                                    {addr.device_type && (
                                      <span
                                        className={`inline-flex items-center justify-center w-5 h-5 rounded text-[8px] font-bold flex-shrink-0 ${dtMeta.color}`}
                                        title={dtMeta.label[language === 'zh' ? 'zh' : 'en']}
                                      >
                                        {dtMeta.icon}
                                      </span>
                                    )}
                                  </div>
                                  <p className="text-[11px] text-black/50 truncate mt-1">
                                    {addr.hostname || (language === 'zh' ? '未命名' : 'Unnamed')}
                                  </p>
                                  {addr.interface_name && <p className="text-[10px] text-black/35 truncate">{addr.interface_name}</p>}
                                  <div className="flex items-center justify-between mt-1.5">
                                    <div className="flex items-center gap-1">
                                      <span className={`w-1.5 h-1.5 rounded-full ${statusBadge.dot}`} />
                                      <span className="text-[9px] text-black/40">{statusBadge.label}</span>
                                    </div>
                                  </div>
                                  {/* Card hover actions */}
                                  <div className="absolute top-1.5 right-1.5 flex items-center gap-0.5 opacity-0 group-hover/card:opacity-100 transition-opacity">
                                    <button
                                      onClick={() => openEditIP(addr)}
                                      className="p-0.5 rounded text-black/20 hover:text-[#00bceb] transition-colors"
                                    >
                                      <Pencil size={11} />
                                    </button>
                                    <button
                                      onClick={() => setConfirmDelete({ type: 'ip', id: addr.id, label: addr.address })}
                                      className="p-0.5 rounded text-black/20 hover:text-red-500 transition-colors"
                                    >
                                      <Trash2 size={11} />
                                    </button>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                      {/* IP pagination */}
                      {addrViewMode !== 'block' && filteredAddresses.length > 0 && (
                        <div className="border-t border-black/5 flex-shrink-0">
                          <Pagination
                            currentPage={safeAddrPage}
                            totalItems={filteredAddresses.length}
                            itemsPerPage={addrPageSizeOpt}
                            onPageChange={setAddrPage}
                            onItemsPerPageChange={(v) => {
                              setAddrPageSizeOpt(v);
                              setAddrPage(1);
                            }}
                            language={language}
                          />
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {showAddSubnet && (
        <SubnetModal
          language={language}
          editingSubnet={editingSubnet}
          formSubnet={formSubnet}
          setFormSubnet={setFormSubnet}
          onClose={() => {
            setShowAddSubnet(false);
            setEditingSubnet(null);
          }}
          onSubmit={editingSubnet ? handleEditSubnet : handleAddSubnet}
        />
      )}

      {showAddIP && (
        <IPModal
          language={language}
          selectedSubnet={selectedSubnet}
          editingIP={editingIP}
          formIP={formIP}
          setFormIP={setFormIP}
          onClose={() => {
            setShowAddIP(false);
            setEditingIP(null);
          }}
          onSubmit={editingIP ? handleEditIP : handleAddIP}
        />
      )}

      {confirmDelete && (
        <DeleteConfirmModal
          language={language}
          confirmDelete={confirmDelete}
          onClose={() => setConfirmDelete(null)}
          onConfirm={executeConfirmedDelete}
        />
      )}
    </div>
  );
};

export default IPVlanTab;
