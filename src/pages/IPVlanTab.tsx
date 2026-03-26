import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Network, Plus, Trash2, AlertTriangle, RefreshCw, Download, Search, X, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, ShieldAlert, ClipboardList, RotateCcw, Ticket, CheckCircle2, Clock3, Pencil, ChevronUp, Server, LayoutGrid, LayoutList } from 'lucide-react';
import * as XLSX from 'xlsx';
import { sectionHeaderRowClass } from '../components/shared';

interface Subnet {
  id: string;
  name: string;
  network: string;
  prefix_len: number;
  vlan_id: number | null;
  vlan_name: string;
  gateway: string;
  description: string;
  site: string;
  status: string;
  total_ips: number;
  used_ips: number;
  utilization: number;
}

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
}

interface Conflict {
  ip_conflicts: { address: string; subnets: string; cnt: number }[];
  mac_conflicts: { mac_address: string; addresses: string; cnt: number }[];
  total_conflicts: number;
}

interface IPVlanTabProps {
  language: string;
  t: (key: string) => string;
}

type PrecheckStatus = 'idle' | 'pass' | 'fail';

type TicketStatus = 'open' | 'processing' | 'resolved';

const IPVLAN_MINIMAL_MODE_KEY = 'ipVlan.minimalMode';
const IPVLAN_ACTION_PANEL_KEY = 'ipVlan.actionPanelOpen';

const DEVICE_TYPES = [
  { value: '', label: { zh: '未分类', en: 'Unclassified' }, icon: '—', color: 'text-black/40' },
  { value: 'server', label: { zh: '服务器', en: 'Server' }, icon: 'S', color: 'text-violet-600 bg-violet-50' },
  { value: 'switch', label: { zh: '交换机', en: 'Switch' }, icon: 'SW', color: 'text-blue-600 bg-blue-50' },
  { value: 'router', label: { zh: '路由器', en: 'Router' }, icon: 'R', color: 'text-emerald-600 bg-emerald-50' },
  { value: 'firewall', label: { zh: '防火墙', en: 'Firewall' }, icon: 'FW', color: 'text-red-600 bg-red-50' },
  { value: 'ap', label: { zh: 'AP', en: 'AP' }, icon: 'AP', color: 'text-cyan-600 bg-cyan-50' },
  { value: 'other', label: { zh: '其他', en: 'Other' }, icon: '?', color: 'text-gray-600 bg-gray-50' },
] as const;

const IPVlanTab: React.FC<IPVlanTabProps> = ({ language, t }) => {
  const [subnets, setSubnets] = useState<Subnet[]>([]);
  const [selectedSubnet, setSelectedSubnet] = useState<Subnet | null>(null);
  const [addresses, setAddresses] = useState<IPAddress[]>([]);
  const [conflicts, setConflicts] = useState<Conflict>({ ip_conflicts: [], mac_conflicts: [], total_conflicts: 0 });
  const [summary, setSummary] = useState({ total_subnets: 0, total_addresses: 0, total_capacity: 0, total_used: 0, high_utilization_subnets: [] as any[] });
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [utilFilter, setUtilFilter] = useState<'all' | 'high' | 'critical'>('all');
  const [subnetSort, setSubnetSort] = useState<'util_desc' | 'name_asc'>('util_desc');
  const [riskOnlyMode, setRiskOnlyMode] = useState(false);
  const [minimalMode, setMinimalMode] = useState(true);
  const [actionPanelOpen, setActionPanelOpen] = useState(false);
  const [precheckStatus, setPrecheckStatus] = useState<PrecheckStatus>('idle');
  const [precheckTarget, setPrecheckTarget] = useState('');
  const [lastRollbackAt, setLastRollbackAt] = useState('');
  const [ticketStatusMap, setTicketStatusMap] = useState<Record<string, TicketStatus>>({});
  const [showAddSubnet, setShowAddSubnet] = useState(false);
  const [showAddIP, setShowAddIP] = useState(false);
  const [formSubnet, setFormSubnet] = useState({ name: '', network: '', prefix_len: 24, vlan_id: '', vlan_name: '', gateway: '', description: '', site: '' });
  const [formIP, setFormIP] = useState({ address: '', hostname: '', interface_name: '', mac_address: '', device_type: '', description: '', status: 'active' });
  const [editingIP, setEditingIP] = useState<IPAddress | null>(null);
  const [addrStatusFilter, setAddrStatusFilter] = useState<'all' | 'active' | 'reserved' | 'deprecated'>('all');
  const [confirmDelete, setConfirmDelete] = useState<{ type: 'subnet' | 'ip'; id: string; label: string } | null>(null);
  const [editingSubnet, setEditingSubnet] = useState<Subnet | null>(null);
  const [addrSearch, setAddrSearch] = useState('');
  const [addrPage, setAddrPage] = useState(1);
  const addrPageSize = 20;
  const [subnetPage, setSubnetPage] = useState(1);
  const subnetPageSize = 15;
  const [addrDeviceTypeFilter, setAddrDeviceTypeFilter] = useState('');
  const [addrViewMode, setAddrViewMode] = useState<'table' | 'card'>('table');

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [subRes, conflictRes, summaryRes] = await Promise.all([
        fetch(`/api/ipam/subnets?q=${encodeURIComponent(search)}`),
        fetch('/api/ipam/conflicts'),
        fetch('/api/ipam/summary'),
      ]);
      if (subRes.ok) setSubnets(await subRes.json());
      if (conflictRes.ok) setConflicts(await conflictRes.json());
      if (summaryRes.ok) setSummary(await summaryRes.json());
    } catch { /* ignore */ }
    setLoading(false);
  }, [search]);

  useEffect(() => { loadData(); }, [loadData]);
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const savedMinimalMode = window.localStorage.getItem(IPVLAN_MINIMAL_MODE_KEY);
    const savedActionPanelOpen = window.localStorage.getItem(IPVLAN_ACTION_PANEL_KEY);
    if (savedMinimalMode === 'true' || savedMinimalMode === 'false') {
      setMinimalMode(savedMinimalMode === 'true');
    }
    if (savedActionPanelOpen === 'true' || savedActionPanelOpen === 'false') {
      setActionPanelOpen(savedActionPanelOpen === 'true');
    }
  }, []);
  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(IPVLAN_MINIMAL_MODE_KEY, String(minimalMode));
  }, [minimalMode]);
  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(IPVLAN_ACTION_PANEL_KEY, String(actionPanelOpen));
  }, [actionPanelOpen]);

  const loadAddresses = async (subnet: Subnet) => {
    setSelectedSubnet(subnet);
    try {
      const r = await fetch(`/api/ipam/subnets/${subnet.id}/addresses`);
      if (r.ok) setAddresses(await r.json());
    } catch { /* ignore */ }
  };

  const handleAddSubnet = async () => {
    try {
      const r = await fetch('/api/ipam/subnets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...formSubnet,
          vlan_id: formSubnet.vlan_id ? parseInt(formSubnet.vlan_id) : null,
        }),
      });
      if (r.ok) {
        setShowAddSubnet(false);
        setFormSubnet({ name: '', network: '', prefix_len: 24, vlan_id: '', vlan_name: '', gateway: '', description: '', site: '' });
        loadData();
      }
    } catch { /* ignore */ }
  };

  const handleEditSubnet = async () => {
    if (!editingSubnet) return;
    try {
      const r = await fetch(`/api/ipam/subnets/${editingSubnet.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...formSubnet,
          vlan_id: formSubnet.vlan_id ? parseInt(formSubnet.vlan_id) : null,
        }),
      });
      if (r.ok) {
        setShowAddSubnet(false);
        setEditingSubnet(null);
        setFormSubnet({ name: '', network: '', prefix_len: 24, vlan_id: '', vlan_name: '', gateway: '', description: '', site: '' });
        loadData();
        if (selectedSubnet?.id === editingSubnet.id) {
          const updated = await r.json().catch(() => null);
          if (updated) setSelectedSubnet(updated);
        }
      }
    } catch { /* ignore */ }
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
    try {
      const r = await fetch(`/api/ipam/subnets/${selectedSubnet.id}/addresses`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formIP),
      });
      if (r.ok) {
        setShowAddIP(false);
        setEditingIP(null);
        setFormIP({ address: '', hostname: '', interface_name: '', mac_address: '', device_type: '', description: '', status: 'active' });
        loadAddresses(selectedSubnet);
        loadData();
      }
    } catch { /* ignore */ }
  };

  const handleEditIP = async () => {
    if (!editingIP) return;
    try {
      const r = await fetch(`/api/ipam/addresses/${editingIP.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
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
        setFormIP({ address: '', hostname: '', interface_name: '', mac_address: '', device_type: '', description: '', status: 'active' });
        if (selectedSubnet) loadAddresses(selectedSubnet);
        loadData();
      }
    } catch { /* ignore */ }
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
    try {
      await fetch(`/api/ipam/subnets/${id}`, { method: 'DELETE' });
      if (selectedSubnet?.id === id) {
        setSelectedSubnet(null);
        setAddresses([]);
      }
      loadData();
    } catch { /* ignore */ }
  };

  const handleDeleteIP = async (id: string) => {
    try {
      await fetch(`/api/ipam/addresses/${id}`, { method: 'DELETE' });
      if (selectedSubnet) loadAddresses(selectedSubnet);
      loadData();
    } catch { /* ignore */ }
  };

  const executeConfirmedDelete = async () => {
    if (!confirmDelete) return;
    if (confirmDelete.type === 'subnet') await handleDeleteSubnet(confirmDelete.id);
    else await handleDeleteIP(confirmDelete.id);
    setConfirmDelete(null);
  };

  const filteredAddresses = useMemo(() => {
    let result = addresses;
    if (addrStatusFilter !== 'all') {
      result = result.filter(a => a.status === addrStatusFilter);
    }
    if (addrDeviceTypeFilter) {
      result = result.filter(a => (a.device_type || '') === addrDeviceTypeFilter);
    }
    if (addrSearch) {
      const q = addrSearch.toLowerCase();
      result = result.filter(a =>
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
    addresses.forEach(a => {
      if (a.status === 'reserved') counts.reserved++;
      else if (a.status === 'deprecated') counts.deprecated++;
      else counts.active++;
    });
    return counts;
  }, [addresses]);

  const addrDeviceTypeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    addresses.forEach(a => {
      const dt = a.device_type || '';
      counts[dt] = (counts[dt] || 0) + 1;
    });
    return counts;
  }, [addresses]);

  const addrTotalPages = Math.max(1, Math.ceil(filteredAddresses.length / addrPageSize));
  const safeAddrPage = Math.min(addrPage, addrTotalPages);
  const pagedAddresses = filteredAddresses.slice((safeAddrPage - 1) * addrPageSize, safeAddrPage * addrPageSize);

  const handleExport = () => {
    const wb = XLSX.utils.book_new();
    if (subnets.length > 0) {
      const subData = subnets.map(s => ({
        Name: s.name,
        Network: `${s.network}/${s.prefix_len}`,
        'VLAN ID': s.vlan_id || '',
        'VLAN Name': s.vlan_name,
        Gateway: s.gateway,
        Site: s.site,
        'Total IPs': s.total_ips,
        'Used IPs': s.used_ips,
        'Utilization': `${s.utilization}%`,
        Description: s.description,
      }));
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(subData), 'Subnets');
    }
    if (addresses.length > 0) {
      const addrData = addresses.map(a => ({
        Address: a.address,
        Hostname: a.hostname,
        Interface: a.interface_name,
        MAC: a.mac_address,
        Status: a.status,
        Description: a.description,
      }));
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(addrData), 'Addresses');
    }
    XLSX.writeFile(wb, 'ipam_export.xlsx');
  };

  const utilColor = (pct: number) => pct >= 90 ? 'text-red-600' : pct >= 80 ? 'text-orange-500' : pct >= 50 ? 'text-[#00172D]' : 'text-emerald-600';
  const utilBarColor = (pct: number) => pct >= 90 ? '#ef4444' : pct >= 80 ? '#f97316' : pct >= 50 ? '#00bceb' : '#10b981';

  const overallUtil = summary.total_capacity > 0 ? Math.round(summary.total_used / summary.total_capacity * 100) : 0;
  const highUtilSubnets = subnets.filter((subnet) => subnet.utilization >= 80).length;
  const criticalUtilSubnets = subnets.filter((subnet) => subnet.utilization >= 90).length;
  const conflictHintText = useMemo(() => `${conflicts.ip_conflicts.map((item) => `${item.address} ${item.subnets}`).join(' ')} ${conflicts.mac_conflicts.map((item) => `${item.mac_address} ${item.addresses}`).join(' ')}`.toLowerCase(), [conflicts]);
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
  const riskSubnetCount = useMemo(() => subnets.filter((subnet) => (subnetRiskScoreMap.get(subnet.id) || 0) >= 70).length, [subnets, subnetRiskScoreMap]);
  const visibleSubnets = useMemo(() => {
    const filtered = subnets.filter((subnet) => {
      const riskScore = subnetRiskScoreMap.get(subnet.id) || 0;
      if (riskOnlyMode && riskScore < 70) return false;
      if (utilFilter === 'critical') return subnet.utilization >= 90;
      if (utilFilter === 'high') return subnet.utilization >= 80;
      return true;
    });
    if (subnetSort === 'name_asc') {
      return [...filtered].sort((left, right) => String(left.name || `${left.network}/${left.prefix_len}`).localeCompare(String(right.name || `${right.network}/${right.prefix_len}`)));
    }
    return [...filtered].sort((left, right) => (subnetRiskScoreMap.get(right.id) || 0) - (subnetRiskScoreMap.get(left.id) || 0) || right.utilization - left.utilization || String(left.network).localeCompare(String(right.network)));
  }, [subnets, utilFilter, subnetSort, riskOnlyMode, subnetRiskScoreMap]);
  const subnetTotalPages = Math.max(1, Math.ceil(visibleSubnets.length / subnetPageSize));
  const safeSubnetPage = Math.min(subnetPage, subnetTotalPages);
  const pagedVisibleSubnets = visibleSubnets.slice((safeSubnetPage - 1) * subnetPageSize, safeSubnetPage * subnetPageSize);

  const validationRows = useMemo(() => visibleSubnets.slice(0, 5).map((subnet) => {
    const sviOk = Boolean(subnet.gateway);
    const dhcpScopeOk = subnet.total_ips > subnet.used_ips;
    const relayOk = subnet.vlan_id !== null;
    const passCount = [sviOk, dhcpScopeOk, relayOk].filter(Boolean).length;
    return {
      subnet,
      sviOk,
      dhcpScopeOk,
      relayOk,
      status: passCount === 3 ? 'pass' : passCount === 2 ? 'warning' : 'fail',
    };
  }), [visibleSubnets]);
  const conflictRows = useMemo(() => {
    const ipRows = conflicts.ip_conflicts.slice(0, 4).map((item, idx) => ({
      id: `ip-${idx}-${item.address}`,
      type: 'ip' as const,
      key: item.address,
      detail: language === 'zh' ? `重复出现 ${item.cnt} 次` : `${item.cnt} duplicate records`,
      impact: item.cnt >= 3 ? 'high' : item.cnt === 2 ? 'medium' : 'low',
    }));
    const macRows = conflicts.mac_conflicts.slice(0, 4).map((item, idx) => ({
      id: `mac-${idx}-${item.mac_address}`,
      type: 'mac' as const,
      key: item.mac_address,
      detail: language === 'zh' ? `关联 ${item.cnt} 个地址` : `${item.cnt} linked addresses`,
      impact: item.cnt >= 3 ? 'high' : item.cnt === 2 ? 'medium' : 'low',
    }));
    return [...ipRows, ...macRows];
  }, [conflicts, language]);

  const runPrecheck = () => {
    const targetSubnet = selectedSubnet || visibleSubnets[0];
    if (!targetSubnet) return;
    const pass = Boolean(targetSubnet.gateway) && targetSubnet.vlan_id !== null && targetSubnet.utilization < 95;
    setPrecheckStatus(pass ? 'pass' : 'fail');
    setPrecheckTarget(targetSubnet.name || `${targetSubnet.network}/${targetSubnet.prefix_len}`);
  };

  const runRollback = () => {
    setLastRollbackAt(new Date().toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US', { hour12: false }));
  };

  const createOrUpdateTicket = (id: string) => {
    setTicketStatusMap((prev) => {
      const current = prev[id];
      if (!current) return { ...prev, [id]: 'open' };
      if (current === 'open') return { ...prev, [id]: 'processing' };
      if (current === 'processing') return { ...prev, [id]: 'resolved' };
      return prev;
    });
  };
  const toggleMinimalMode = () => {
    setMinimalMode((prev) => {
      const next = !prev;
      setActionPanelOpen(!next);
      return next;
    });
  };
  const showActionPanel = !minimalMode || actionPanelOpen;

  return (
    <div className="space-y-4 overflow-auto h-full pb-2">
      <div className={sectionHeaderRowClass}>
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-[#00172D]">
            {language === 'zh' ? 'IP/VLAN 资源管理' : 'IP/VLAN Management'}
          </h2>
          <p className="text-sm text-black/40">
            {language === 'zh' ? '子网与IP地址分配管理，冲突检测' : 'Subnet & IP address management with conflict detection'}
          </p>
        </div>
        <div className="flex gap-2 items-center">
          <button
            type="button"
            onClick={toggleMinimalMode}
            className={`inline-flex items-center gap-1.5 px-3 py-2 rounded-xl border text-xs font-semibold transition-all ${minimalMode ? 'border-black/15 text-black/60 hover:border-black/25 hover:text-black/75' : 'border-[#00bceb]/35 bg-[#00bceb]/10 text-[#007b9a]'}`}
          >
            <ChevronRight size={12} className={`transition-transform ${minimalMode ? '-rotate-90' : 'rotate-90'}`} />
            {minimalMode ? (language === 'zh' ? '极简模式' : 'Minimal') : (language === 'zh' ? '完整模式' : 'Full')}
          </button>
          {minimalMode && (
            <button
              type="button"
              onClick={() => setActionPanelOpen((prev) => !prev)}
              className={`inline-flex items-center gap-1.5 px-3 py-2 rounded-xl border text-xs font-semibold transition-all ${actionPanelOpen ? 'border-[#00bceb]/35 bg-[#00bceb]/10 text-[#007b9a]' : 'border-black/15 text-black/60 hover:border-black/25 hover:text-black/75'}`}
            >
              <ChevronRight size={12} className={`transition-transform ${actionPanelOpen ? 'rotate-180' : 'rotate-0'}`} />
              {actionPanelOpen ? (language === 'zh' ? '收起处置栏' : 'Hide Actions') : (language === 'zh' ? '展开处置栏' : 'Show Actions')}
            </button>
          )}
          <button onClick={handleExport} className="p-1.5 rounded-lg border border-black/10 text-black/40 hover:text-[#00bceb] hover:border-[#00bceb]/30 transition-all" title={language === 'zh' ? '导出' : 'Export'}>
            <Download size={14} />
          </button>
          <button onClick={() => setShowAddSubnet(true)} className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-[#00bceb] text-white text-sm font-semibold hover:bg-[#00a5d0] transition-all">
            <Plus size={14} />
            {language === 'zh' ? '添加子网' : 'Add Subnet'}
          </button>
        </div>
      </div>
      <div className="bg-white rounded-2xl border border-black/5 shadow-sm p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-[#00172D]">{language === 'zh' ? '资源总览' : 'Resource Overview'}</h3>
          {conflicts.total_conflicts > 0 && (
            <span className="inline-flex items-center gap-1 rounded-full bg-red-50 border border-red-200 px-2 py-0.5 text-[11px] font-semibold text-red-600 animate-pulse">
              <AlertTriangle size={11} />
              {language === 'zh' ? `${conflicts.total_conflicts} 个冲突待处理` : `${conflicts.total_conflicts} conflicts`}
            </span>
          )}
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
          <div className="rounded-xl border border-black/8 px-4 py-3">
            <p className="text-[10px] font-bold uppercase tracking-wider text-black/30">{language === 'zh' ? '子网总数' : 'Subnets'}</p>
            <p className="text-xl font-bold monitoring-data mt-1 text-[#00172D]">{summary.total_subnets}</p>
          </div>
          <div className="rounded-xl border border-black/8 px-4 py-3">
            <p className="text-[10px] font-bold uppercase tracking-wider text-black/30">{language === 'zh' ? '总容量' : 'Total IPs'}</p>
            <p className="text-xl font-bold monitoring-data mt-1 text-[#00172D]">{summary.total_capacity}</p>
          </div>
          <div className="rounded-xl border border-black/8 px-4 py-3">
            <p className="text-[10px] font-bold uppercase tracking-wider text-black/30">{language === 'zh' ? '已使用' : 'Used IPs'}</p>
            <p className="text-xl font-bold monitoring-data mt-1 text-[#00172D]">{summary.total_used}</p>
          </div>
          {/* Utilization - prominent colored card */}
          <div className={`rounded-xl px-4 py-3 border ${overallUtil >= 90 ? 'bg-red-50 border-red-200' : overallUtil >= 80 ? 'bg-orange-50 border-orange-200' : overallUtil >= 50 ? 'bg-blue-50 border-blue-200' : 'bg-emerald-50 border-emerald-200'}`}>
            <p className={`text-[10px] font-bold uppercase tracking-wider ${overallUtil >= 90 ? 'text-red-500' : overallUtil >= 80 ? 'text-orange-500' : overallUtil >= 50 ? 'text-blue-500' : 'text-emerald-500'}`}>{language === 'zh' ? '利用率' : 'Utilization'}</p>
            <p className={`text-xl font-bold monitoring-data mt-1 ${utilColor(overallUtil)}`}>{overallUtil}%</p>
            <div className="mt-1.5 h-1.5 bg-white/80 rounded-full overflow-hidden">
              <div className="h-full rounded-full transition-all duration-700" style={{ width: `${Math.min(100, overallUtil)}%`, backgroundColor: utilBarColor(overallUtil) }} />
            </div>
          </div>
          {/* Risk - prominent colored card */}
          <div className={`rounded-xl px-4 py-3 border ${riskSubnetCount > 0 ? 'bg-red-50 border-red-200' : 'bg-emerald-50 border-emerald-200'}`}>
            <p className={`text-[10px] font-bold uppercase tracking-wider ${riskSubnetCount > 0 ? 'text-red-500' : 'text-emerald-500'}`}>{language === 'zh' ? '高风险网段' : 'Risky Subnets'}</p>
            <div className="flex items-end gap-2 mt-1">
              <p className={`text-xl font-bold monitoring-data ${riskSubnetCount > 0 ? 'text-red-600' : 'text-emerald-600'}`}>{riskSubnetCount}</p>
              {riskSubnetCount === 0 && <span className="text-[11px] text-emerald-500 font-medium mb-0.5">{language === 'zh' ? '无风险' : 'Clear'}</span>}
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-4">
        <div className={`col-span-12 ${showActionPanel ? 'xl:col-span-7' : ''} space-y-4`}>
          <div className="bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden">
            <div className="px-4 py-3 border-b border-black/5 bg-black/[0.02]">
              <div className="flex items-center justify-between gap-3 mb-2">
                <h3 className="text-sm font-semibold text-[#00172D]">{language === 'zh' ? '网段工作台' : 'Subnet Workspace'}</h3>
                <button
                  type="button"
                  onClick={() => setSubnetSort((prev) => prev === 'util_desc' ? 'name_asc' : 'util_desc')}
                  className="inline-flex items-center gap-1 rounded-full border border-black/10 px-2 py-1 text-[10px] font-semibold text-black/50 transition-all hover:border-black/20 hover:text-black/70"
                  title={language === 'zh' ? '切换排序' : 'Toggle sort'}
                >
                  <ChevronRight size={12} className={`transition-transform ${subnetSort === 'name_asc' ? 'rotate-90' : 'rotate-0'}`} />
                  <span>{subnetSort === 'util_desc' ? (language === 'zh' ? '按风险/利用率' : 'By Risk/Util') : (language === 'zh' ? '按名称' : 'By Name')}</span>
                </button>
              </div>
              <div className="relative">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-black/30" />
                <input value={search} onChange={e => { setSearch(e.target.value); setSubnetPage(1); }} placeholder={language === 'zh' ? '搜索子网/VLAN...' : 'Search subnets...'} className="w-full pl-9 pr-3 py-2 text-sm border border-black/10 rounded-lg outline-none focus:border-[#00bceb]/50" />
              </div>
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
                      onClick={() => { setUtilFilter(item.id); setSubnetPage(1); }}
                      className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[10px] font-semibold transition-all ${utilFilter === item.id ? 'border-[#00bceb]/45 bg-[#00bceb]/10 text-[#007b9a]' : 'border-black/10 text-black/45 hover:border-black/20 hover:text-black/65'}`}
                    >
                      <span>{item.label}</span>
                      <span className="monitoring-data">{item.count}</span>
                    </button>
                  ))}
                </div>
                <button
                  type="button"
                  onClick={() => { setRiskOnlyMode((prev) => !prev); setSubnetPage(1); }}
                  className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[10px] font-semibold transition-all ${riskOnlyMode ? 'border-red-300 bg-red-50 text-red-700' : 'border-black/15 text-black/55 hover:border-black/20 hover:text-black/70'}`}
                >
                  <CheckCircle2 size={11} />
                  {language === 'zh' ? '仅高风险' : 'High Risk Only'}
                </button>
              </div>
            </div>
            <div className="max-h-[420px] overflow-y-auto divide-y divide-black/5">
              {visibleSubnets.length === 0 && !loading && (
                subnets.length === 0 ? (
                  <div className="py-16 flex flex-col items-center justify-center gap-4">
                    <div className="w-16 h-16 rounded-2xl bg-[#00bceb]/10 flex items-center justify-center">
                      <Network size={28} className="text-[#00bceb]" />
                    </div>
                    <div className="text-center">
                      <p className="text-sm font-semibold text-[#00172D]">{language === 'zh' ? '还没有子网' : 'No subnets yet'}</p>
                      <p className="text-xs text-black/40 mt-1 max-w-xs">{language === 'zh' ? '添加第一个子网来开始管理IP地址分配和VLAN规划。' : 'Add your first subnet to start managing IP allocation and VLAN planning.'}</p>
                    </div>
                    <button onClick={() => setShowAddSubnet(true)} className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-[#00bceb] text-white text-sm font-semibold hover:bg-[#00a5d0] transition-all shadow-lg shadow-[#00bceb]/20">
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
              {pagedVisibleSubnets.map(subnet => (
                <button key={subnet.id} onClick={() => { if (selectedSubnet?.id === subnet.id) { setSelectedSubnet(null); setAddresses([]); } else { loadAddresses(subnet); } }} className={`group/subnet w-full text-left px-4 py-3 hover:bg-black/[0.02] transition-colors ${selectedSubnet?.id === subnet.id ? 'bg-[#00bceb]/5 border-l-[3px] border-l-[#00bceb]' : ''}`}>
                  <div className="flex items-center justify-between">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <Network size={14} className="text-[#00bceb] flex-shrink-0" />
                        <p className="text-sm font-semibold text-[#00172D] truncate">{subnet.name || `${subnet.network}/${subnet.prefix_len}`}</p>
                        <span
                          role="button"
                          title={language === 'zh' ? '编辑子网' : 'Edit subnet'}
                          onClick={(e) => openEditSubnet(subnet, e)}
                          className="opacity-0 group-hover/subnet:opacity-100 p-0.5 rounded hover:bg-black/10 text-black/30 hover:text-black/60 transition-all"
                        >
                          <Pencil size={12} />
                        </span>
                      </div>
                      <p className="text-[11px] text-black/40 mt-0.5">{subnet.network}/{subnet.prefix_len} {subnet.vlan_id ? `· VLAN ${subnet.vlan_id}` : ''} {subnet.site ? `· ${subnet.site}` : ''}</p>
                    </div>
                    <div className="text-right flex-shrink-0 ml-2">
                      <p className="text-[10px] font-semibold text-black/35 monitoring-data">RISK {(subnetRiskScoreMap.get(subnet.id) || 0)}</p>
                      <p className={`text-xs font-bold monitoring-data ${utilColor(subnet.utilization)}`}>{subnet.utilization}%</p>
                      <p className="text-[10px] text-black/30 monitoring-data">{subnet.used_ips}/{subnet.total_ips}</p>
                    </div>
                  </div>
                  <div className="mt-2 h-1.5 bg-black/5 rounded-full overflow-hidden">
                    <div className="h-full rounded-full transition-all duration-500" style={{ width: `${Math.min(100, subnet.utilization)}%`, backgroundColor: utilBarColor(subnet.utilization) }} />
                  </div>
                </button>
              ))}
            </div>
            {/* Subnet pagination */}
            {visibleSubnets.length > subnetPageSize && (
              <div className="px-4 py-2 border-t border-black/5 flex items-center justify-between">
                <span className="text-[10px] text-black/35 tabular-nums">
                  {language === 'zh' ? `${(safeSubnetPage-1)*subnetPageSize+1}-${Math.min(safeSubnetPage*subnetPageSize, visibleSubnets.length)} / ${visibleSubnets.length}` : `${(safeSubnetPage-1)*subnetPageSize+1}-${Math.min(safeSubnetPage*subnetPageSize, visibleSubnets.length)} of ${visibleSubnets.length}`}
                </span>
                <div className="flex items-center gap-1">
                  <button disabled={safeSubnetPage <= 1} onClick={() => setSubnetPage(1)} className="p-1 rounded border border-black/8 hover:bg-black/5 disabled:opacity-30 transition-all" title={language === 'zh' ? '首页' : 'First'}><ChevronsLeft size={12} /></button>
                  <button disabled={safeSubnetPage <= 1} onClick={() => setSubnetPage(safeSubnetPage - 1)} className="p-1 rounded border border-black/8 hover:bg-black/5 disabled:opacity-30 transition-all"><ChevronLeft size={12} /></button>
                  <span className="text-[10px] text-black/40 px-1 tabular-nums">{safeSubnetPage}/{subnetTotalPages}</span>
                  <button disabled={safeSubnetPage >= subnetTotalPages} onClick={() => setSubnetPage(safeSubnetPage + 1)} className="p-1 rounded border border-black/8 hover:bg-black/5 disabled:opacity-30 transition-all"><ChevronRight size={12} /></button>
                  <button disabled={safeSubnetPage >= subnetTotalPages} onClick={() => setSubnetPage(subnetTotalPages)} className="p-1 rounded border border-black/8 hover:bg-black/5 disabled:opacity-30 transition-all" title={language === 'zh' ? '末页' : 'Last'}><ChevronsRight size={12} /></button>
                </div>
              </div>
            )}
          </div>

          {selectedSubnet && (
            <div className="bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden">
                <div className="flex flex-col h-full">
                  <div className="px-4 py-3 border-b border-black/5 bg-gradient-to-r from-[#00bceb]/5 to-transparent">
                    <div className="flex items-center justify-between mb-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <Network size={16} className="text-[#00bceb]" />
                          <p className="text-base font-bold text-[#00172D]">{selectedSubnet.name || `${selectedSubnet.network}/${selectedSubnet.prefix_len}`}</p>
                        </div>
                        <p className="text-[11px] text-black/40 mt-0.5 ml-6">
                          {selectedSubnet.network}/{selectedSubnet.prefix_len}
                          {selectedSubnet.vlan_id ? ` · VLAN ${selectedSubnet.vlan_id}` : ''}
                          {selectedSubnet.vlan_name ? ` (${selectedSubnet.vlan_name})` : ''}
                          {selectedSubnet.site ? ` · ${selectedSubnet.site}` : ''}
                        </p>
                      </div>
                    </div>
                    <div className="flex gap-2 items-center flex-shrink-0">
                      <div className="relative">
                        <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-black/25" />
                        <input
                          value={addrSearch}
                          onChange={e => { setAddrSearch(e.target.value); setAddrPage(1); }}
                          placeholder={language === 'zh' ? '搜索IP/主机/MAC...' : 'Search IP/host/MAC...'}
                          className="pl-7 pr-2 py-1.5 text-xs border border-black/10 rounded-lg outline-none focus:border-[#00bceb]/50 w-40"
                        />
                        {addrSearch && (
                          <button onClick={() => { setAddrSearch(''); setAddrPage(1); }} className="absolute right-2 top-1/2 -translate-y-1/2 text-black/25 hover:text-black/50">
                            <X size={11} />
                          </button>
                        )}
                      </div>
                      <button onClick={() => setShowAddIP(true)} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#00bceb] text-white text-xs font-semibold hover:bg-[#00a5d0] transition-all">
                        <Plus size={12} />
                        {language === 'zh' ? '添加IP' : 'Add IP'}
                      </button>
                      <button onClick={() => setConfirmDelete({ type: 'subnet', id: selectedSubnet.id, label: selectedSubnet.name || `${selectedSubnet.network}/${selectedSubnet.prefix_len}` })} className="p-1.5 rounded-lg border border-black/10 text-black/40 hover:text-red-500 hover:border-red-300 transition-all" title={language === 'zh' ? '删除子网' : 'Delete Subnet'}>
                        <Trash2 size={14} />
                      </button>
                      <button onClick={() => { setSelectedSubnet(null); setAddresses([]); }} className="p-1.5 rounded-lg border border-black/10 text-black/40 hover:text-[#00bceb] hover:border-[#00bceb]/30 transition-all" title={language === 'zh' ? '收起' : 'Collapse'}>
                        <ChevronUp size={14} />
                      </button>
                    </div>
                    {/* Subnet summary cards */}
                    <div className="grid grid-cols-4 gap-2 mt-1">
                      <div className="rounded-lg bg-white/80 border border-black/6 px-2.5 py-1.5 text-center">
                        <p className="text-[9px] font-bold uppercase tracking-wider text-black/30">{language === 'zh' ? '总容量' : 'Capacity'}</p>
                        <p className="text-sm font-bold text-[#00172D] monitoring-data mt-0.5">{selectedSubnet.total_ips}</p>
                      </div>
                      <div className="rounded-lg bg-white/80 border border-black/6 px-2.5 py-1.5 text-center">
                        <p className="text-[9px] font-bold uppercase tracking-wider text-black/30">{language === 'zh' ? '已分配' : 'Assigned'}</p>
                        <p className="text-sm font-bold text-[#00bceb] monitoring-data mt-0.5">{addresses.length}</p>
                      </div>
                      <div className="rounded-lg bg-white/80 border border-black/6 px-2.5 py-1.5 text-center">
                        <p className="text-[9px] font-bold uppercase tracking-wider text-black/30">{language === 'zh' ? '已使用' : 'Used'}</p>
                        <p className={`text-sm font-bold monitoring-data mt-0.5 ${utilColor(selectedSubnet.utilization)}`}>{selectedSubnet.used_ips}</p>
                      </div>
                      <div className="rounded-lg bg-white/80 border border-black/6 px-2.5 py-1.5 text-center">
                        <p className="text-[9px] font-bold uppercase tracking-wider text-black/30">{language === 'zh' ? '可用' : 'Available'}</p>
                        <p className="text-sm font-bold text-emerald-600 monitoring-data mt-0.5">{Math.max(0, selectedSubnet.total_ips - selectedSubnet.used_ips)}</p>
                      </div>
                    </div>
                    {selectedSubnet.gateway && (
                      <p className="text-[10px] text-black/35 mt-2 ml-0.5">Gateway: <span className="font-mono font-semibold text-black/50">{selectedSubnet.gateway}</span></p>
                    )}
                    {/* Utilization bar */}
                    <div className="mt-2 flex items-center gap-2">
                      <div className="flex-1 h-2 bg-black/5 rounded-full overflow-hidden">
                        <div className="h-full rounded-full transition-all duration-700" style={{ width: `${Math.min(100, selectedSubnet.utilization)}%`, backgroundColor: utilBarColor(selectedSubnet.utilization) }} />
                      </div>
                      <span className={`text-[11px] font-bold monitoring-data ${utilColor(selectedSubnet.utilization)}`}>{selectedSubnet.utilization}%</span>
                    </div>
                    {/* Status filter tabs + device type filter + view toggle */}
                    <div className="mt-3 flex items-center justify-between gap-2 flex-wrap">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        {([
                          { id: 'all' as const, label: language === 'zh' ? '全部' : 'All', count: addrStatusCounts.all },
                          { id: 'active' as const, label: language === 'zh' ? '在用' : 'Active', count: addrStatusCounts.active, color: 'emerald' },
                          { id: 'reserved' as const, label: language === 'zh' ? '预留' : 'Reserved', count: addrStatusCounts.reserved, color: 'amber' },
                          { id: 'deprecated' as const, label: language === 'zh' ? '停用' : 'Deprecated', count: addrStatusCounts.deprecated, color: 'gray' },
                        ]).map(tab => (
                          <button
                            key={tab.id}
                            onClick={() => { setAddrStatusFilter(tab.id); setAddrPage(1); }}
                            className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold transition-all ${addrStatusFilter === tab.id ? 'border-[#00bceb]/45 bg-[#00bceb]/10 text-[#007b9a]' : 'border-black/8 text-black/40 hover:border-black/15 hover:text-black/55'}`}
                          >
                            {tab.label}
                            <span className="tabular-nums">{tab.count}</span>
                          </button>
                        ))}
                        <span className="w-px h-4 bg-black/10 mx-0.5" />
                        {DEVICE_TYPES.filter(dt => dt.value && (addrDeviceTypeCounts[dt.value] || 0) > 0).map(dt => (
                          <button
                            key={dt.value}
                            onClick={() => { setAddrDeviceTypeFilter(prev => prev === dt.value ? '' : dt.value); setAddrPage(1); }}
                            className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold transition-all ${addrDeviceTypeFilter === dt.value ? 'border-[#00bceb]/45 bg-[#00bceb]/10 text-[#007b9a]' : 'border-black/8 text-black/40 hover:border-black/15 hover:text-black/55'}`}
                            title={dt.label[language === 'zh' ? 'zh' : 'en']}
                          >
                            <span className={`inline-flex items-center justify-center w-4 h-4 rounded text-[8px] font-bold ${dt.color}`}>{dt.icon}</span>
                            <span className="tabular-nums">{addrDeviceTypeCounts[dt.value] || 0}</span>
                          </button>
                        ))}
                      </div>
                      <div className="flex items-center gap-0.5 border border-black/8 rounded-lg p-0.5">
                        <button onClick={() => setAddrViewMode('table')} className={`p-1 rounded ${addrViewMode === 'table' ? 'bg-[#00bceb]/10 text-[#007b9a]' : 'text-black/30 hover:text-black/50'}`} title={language === 'zh' ? '表格视图' : 'Table view'}><LayoutList size={13} /></button>
                        <button onClick={() => setAddrViewMode('card')} className={`p-1 rounded ${addrViewMode === 'card' ? 'bg-[#00bceb]/10 text-[#007b9a]' : 'text-black/30 hover:text-black/50'}`} title={language === 'zh' ? '卡片视图' : 'Card view'}><LayoutGrid size={13} /></button>
                      </div>
                    </div>
                  </div>

                  <div className="flex-1 overflow-y-auto max-h-[420px]">
                    {addrViewMode === 'table' ? (
                    <table className="w-full text-left border-collapse">
                      <thead>
                        <tr className="bg-black/[0.01] border-b border-black/5">
                          <th className="px-3 py-2.5 text-[10px] font-bold uppercase tracking-widest text-black/40">{language === 'zh' ? 'IP地址' : 'Address'}</th>
                          <th className="px-3 py-2.5 text-[10px] font-bold uppercase tracking-widest text-black/40">{language === 'zh' ? '主机名' : 'Hostname'}</th>
                          <th className="px-3 py-2.5 text-[10px] font-bold uppercase tracking-widest text-black/40">{language === 'zh' ? '类型' : 'Type'}</th>
                          <th className="px-3 py-2.5 text-[10px] font-bold uppercase tracking-widest text-black/40">{language === 'zh' ? '接口' : 'Interface'}</th>
                          <th className="px-3 py-2.5 text-[10px] font-bold uppercase tracking-widest text-black/40">{language === 'zh' ? '状态' : 'Status'}</th>
                          <th className="px-3 py-2.5 text-[10px] font-bold uppercase tracking-widest text-black/40 w-16"></th>
                        </tr>
                      </thead>
                      <tbody>
                        {pagedAddresses.length === 0 && (
                          <tr><td colSpan={6} className="px-4 py-12 text-center text-sm text-black/30">{addrSearch || addrStatusFilter !== 'all' ? (language === 'zh' ? '无匹配结果' : 'No matches') : (language === 'zh' ? '暂无IP分配记录' : 'No IP assignments')}</td></tr>
                        )}
                        {pagedAddresses.map(addr => {
                          const statusBadge = addr.status === 'reserved'
                            ? { bg: 'bg-amber-50 border-amber-200 text-amber-700', label: language === 'zh' ? '预留' : 'Reserved' }
                            : addr.status === 'deprecated'
                              ? { bg: 'bg-gray-100 border-gray-300 text-gray-500', label: language === 'zh' ? '停用' : 'Deprecated' }
                              : { bg: 'bg-emerald-50 border-emerald-200 text-emerald-700', label: language === 'zh' ? '在用' : 'Active' };
                          const dtMeta = DEVICE_TYPES.find(d => d.value === (addr.device_type || '')) || DEVICE_TYPES[0];
                          return (
                          <tr key={addr.id} className={`border-b border-black/5 hover:bg-black/[0.01] group/row ${addr.status === 'deprecated' ? 'opacity-50' : ''}`}>
                            <td className="px-3 py-2 text-sm font-mono font-semibold text-[#00172D]">{addr.address}</td>
                            <td className="px-3 py-2 text-xs text-black/60">{addr.hostname || '-'}</td>
                            <td className="px-3 py-2">
                              {addr.device_type ? (
                                <span className={`inline-flex items-center justify-center w-5 h-5 rounded text-[8px] font-bold ${dtMeta.color}`} title={dtMeta.label[language === 'zh' ? 'zh' : 'en']}>{dtMeta.icon}</span>
                              ) : <span className="text-xs text-black/25">-</span>}
                            </td>
                            <td className="px-3 py-2 text-xs text-black/60">{addr.interface_name || '-'}</td>
                            <td className="px-3 py-2">
                              <span className={`inline-flex items-center rounded-full border px-1.5 py-0.5 text-[9px] font-semibold ${statusBadge.bg}`}>{statusBadge.label}</span>
                            </td>
                            <td className="px-3 py-2">
                              <div className="flex items-center gap-0.5 opacity-0 group-hover/row:opacity-100 transition-opacity">
                                <button onClick={() => openEditIP(addr)} className="p-1 rounded text-black/25 hover:text-[#00bceb] transition-colors" title={language === 'zh' ? '编辑' : 'Edit'}>
                                  <Pencil size={13} />
                                </button>
                                <button onClick={() => setConfirmDelete({ type: 'ip', id: addr.id, label: addr.address })} className="p-1 rounded text-black/25 hover:text-red-500 transition-colors" title={language === 'zh' ? '删除' : 'Delete'}>
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
                        <div className="col-span-full py-12 text-center text-sm text-black/30">{addrSearch || addrStatusFilter !== 'all' || addrDeviceTypeFilter ? (language === 'zh' ? '无匹配结果' : 'No matches') : (language === 'zh' ? '暂无IP分配记录' : 'No IP assignments')}</div>
                      )}
                      {pagedAddresses.map(addr => {
                        const statusBadge = addr.status === 'reserved'
                          ? { bg: 'bg-amber-50 border-amber-200 text-amber-700', label: language === 'zh' ? '预留' : 'Reserved', dot: 'bg-amber-400' }
                          : addr.status === 'deprecated'
                            ? { bg: 'bg-gray-100 border-gray-300 text-gray-500', label: language === 'zh' ? '停用' : 'Deprecated', dot: 'bg-gray-400' }
                            : { bg: 'bg-emerald-50 border-emerald-200 text-emerald-700', label: language === 'zh' ? '在用' : 'Active', dot: 'bg-emerald-400' };
                        const dtMeta = DEVICE_TYPES.find(d => d.value === (addr.device_type || '')) || DEVICE_TYPES[0];
                        return (
                          <div key={addr.id} className={`group/card relative rounded-xl border border-black/8 px-3 py-2.5 hover:border-[#00bceb]/30 hover:shadow-sm transition-all cursor-default ${addr.status === 'deprecated' ? 'opacity-50' : ''}`}>
                            <div className="flex items-center justify-between gap-1">
                              <p className="text-xs font-mono font-bold text-[#00172D] truncate">{addr.address}</p>
                              {addr.device_type && <span className={`inline-flex items-center justify-center w-5 h-5 rounded text-[8px] font-bold flex-shrink-0 ${dtMeta.color}`} title={dtMeta.label[language === 'zh' ? 'zh' : 'en']}>{dtMeta.icon}</span>}
                            </div>
                            <p className="text-[11px] text-black/50 truncate mt-1">{addr.hostname || (language === 'zh' ? '未命名' : 'Unnamed')}</p>
                            {addr.interface_name && <p className="text-[10px] text-black/35 truncate">{addr.interface_name}</p>}
                            <div className="flex items-center justify-between mt-1.5">
                              <div className="flex items-center gap-1">
                                <span className={`w-1.5 h-1.5 rounded-full ${statusBadge.dot}`} />
                                <span className="text-[9px] text-black/40">{statusBadge.label}</span>
                              </div>
                            </div>
                            {/* Card hover actions */}
                            <div className="absolute top-1.5 right-1.5 flex items-center gap-0.5 opacity-0 group-hover/card:opacity-100 transition-opacity">
                              <button onClick={() => openEditIP(addr)} className="p-0.5 rounded text-black/20 hover:text-[#00bceb] transition-colors"><Pencil size={11} /></button>
                              <button onClick={() => setConfirmDelete({ type: 'ip', id: addr.id, label: addr.address })} className="p-0.5 rounded text-black/20 hover:text-red-500 transition-colors"><Trash2 size={11} /></button>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                    )}
                  </div>
                  {/* IP pagination */}
                  {filteredAddresses.length > addrPageSize && (
                    <div className="px-4 py-2 border-t border-black/5 flex items-center justify-between">
                      <span className="text-[10px] text-black/35">
                        {language === 'zh' ? `${(safeAddrPage-1)*addrPageSize+1}-${Math.min(safeAddrPage*addrPageSize, filteredAddresses.length)} / ${filteredAddresses.length}` : `${(safeAddrPage-1)*addrPageSize+1}-${Math.min(safeAddrPage*addrPageSize, filteredAddresses.length)} of ${filteredAddresses.length}`}
                      </span>
                      <div className="flex items-center gap-1">
                        <button disabled={safeAddrPage <= 1} onClick={() => setAddrPage(safeAddrPage - 1)} className="p-1 rounded border border-black/8 hover:bg-black/5 disabled:opacity-30 transition-all"><ChevronLeft size={12} /></button>
                        <span className="text-[10px] text-black/40 px-1 tabular-nums">{safeAddrPage}/{addrTotalPages}</span>
                        <button disabled={safeAddrPage >= addrTotalPages} onClick={() => setAddrPage(safeAddrPage + 1)} className="p-1 rounded border border-black/8 hover:bg-black/5 disabled:opacity-30 transition-all"><ChevronRight size={12} /></button>
                      </div>
                    </div>
                  )}
                </div>
            </div>
          )}
        </div>

        {showActionPanel && (
          <div className="col-span-12 xl:col-span-5 space-y-4">
          <div className="bg-white rounded-2xl border border-black/5 shadow-sm p-4">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-[11px] font-bold uppercase tracking-wider text-black/35">{language === 'zh' ? '变更保障' : 'Change Safety'}</p>
                <h3 className="text-base font-semibold text-[#00172D] mt-1">{language === 'zh' ? '风险与预检' : 'Risk & Pre-check'}</h3>
              </div>
              <ShieldAlert size={16} className="text-red-500" />
            </div>
            <div className="grid grid-cols-3 gap-2 mt-3">
              <div className="rounded-lg border border-black/10 px-2.5 py-2">
                <p className="text-[10px] text-black/35 uppercase">{language === 'zh' ? '风险网段' : 'Risky'}</p>
                <p className="text-base font-bold text-red-600 monitoring-data">{riskSubnetCount}</p>
              </div>
              <div className="rounded-lg border border-black/10 px-2.5 py-2">
                <p className="text-[10px] text-black/35 uppercase">{language === 'zh' ? '冲突' : 'Conflicts'}</p>
                <p className="text-base font-bold text-orange-500 monitoring-data">{conflicts.total_conflicts}</p>
              </div>
              <div className="rounded-lg border border-black/10 px-2.5 py-2">
                <p className="text-[10px] text-black/35 uppercase">{language === 'zh' ? '利用率' : 'Util'}</p>
                <p className="text-base font-bold text-[#00172D] monitoring-data">{overallUtil}%</p>
              </div>
            </div>
            <div className="mt-3 rounded-xl border border-black/10 px-3 py-2">
              <p className="text-xs text-black/45">{language === 'zh' ? '当前目标' : 'Current Target'}</p>
              <p className="text-sm font-semibold text-[#00172D] mt-0.5">{precheckTarget || (selectedSubnet?.name || selectedSubnet?.network || (language === 'zh' ? '未选择网段' : 'No subnet selected'))}</p>
              <p className={`text-xs mt-2 ${precheckStatus === 'pass' ? 'text-emerald-600' : precheckStatus === 'fail' ? 'text-red-600' : 'text-black/40'}`}>
                {precheckStatus === 'pass'
                  ? (language === 'zh' ? '预检通过：可执行变更' : 'Pre-check passed: ready to change')
                  : precheckStatus === 'fail'
                    ? (language === 'zh' ? '预检失败：建议先修复配置项' : 'Pre-check failed: fix config before change')
                    : (language === 'zh' ? '尚未执行预检' : 'Pre-check not executed')}
              </p>
              {lastRollbackAt && (
                <p className="text-[11px] text-black/40 mt-1">{language === 'zh' ? `最近回滚：${lastRollbackAt}` : `Last rollback: ${lastRollbackAt}`}</p>
              )}
            </div>
            <div className="mt-3 flex items-center gap-2">
              <button type="button" onClick={runPrecheck} className="inline-flex items-center gap-1.5 rounded-lg bg-[#00bceb] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#00a5d0] transition-all">
                <RefreshCw size={12} />
                {language === 'zh' ? '执行预检' : 'Run Pre-check'}
              </button>
              <button type="button" onClick={runRollback} className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-semibold text-amber-700 hover:bg-amber-100 transition-all">
                <RotateCcw size={12} />
                {language === 'zh' ? '一键回滚' : 'Rollback'}
              </button>
              <span className="ml-auto rounded-full border border-black/8 bg-black/[0.03] px-2 py-0.5 text-[9px] font-medium text-black/35 select-none">{language === 'zh' ? '模拟' : 'Simulated'}</span>
            </div>
          </div>

          <div className="bg-white rounded-2xl border border-black/5 shadow-sm p-4">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-[11px] font-bold uppercase tracking-wider text-black/35">{language === 'zh' ? '联动校验' : 'Linked Validation'}</p>
                <h3 className="text-base font-semibold text-[#00172D] mt-1">{language === 'zh' ? 'VLAN-SVI-DHCP 校验' : 'VLAN-SVI-DHCP Checks'}</h3>
              </div>
              <ClipboardList size={16} className="text-[#00bceb]" />
            </div>
            <div className="mt-3 space-y-2 max-h-[180px] overflow-y-auto pr-1">
              {validationRows.length === 0 && (
                <p className="text-xs text-black/35">{language === 'zh' ? '暂无可校验网段' : 'No subnets for validation'}</p>
              )}
              {validationRows.map((item) => (
                <div key={item.subnet.id} className="rounded-xl border border-black/8 px-3 py-2">
                  <p className="text-xs font-semibold text-[#00172D] truncate">{item.subnet.name || `${item.subnet.network}/${item.subnet.prefix_len}`}</p>
                  <p className="text-[11px] text-black/45 mt-1">
                    SVI {item.sviOk ? '✓' : '✕'} · DHCP {item.dhcpScopeOk ? '✓' : '✕'} · Relay {item.relayOk ? '✓' : '✕'}
                  </p>
                </div>
              ))}
            </div>
          </div>

          <div className="bg-white rounded-2xl border border-black/5 shadow-sm p-4">
            <div className="flex items-center justify-between mb-3">
              <div>
                <p className="text-[11px] font-bold uppercase tracking-wider text-black/35">{language === 'zh' ? '冲突处置' : 'Conflict Handling'}</p>
                <div className="flex items-center gap-2 mt-1">
                  <h3 className="text-base font-semibold text-[#00172D]">{language === 'zh' ? '定位与工单' : 'Localization & Ticketing'}</h3>
                  <span className="rounded-full border border-black/8 bg-black/[0.03] px-2 py-0.5 text-[9px] font-medium text-black/35 select-none">{language === 'zh' ? '模拟' : 'Simulated'}</span>
                </div>
              </div>
              <Ticket size={16} className="text-[#00bceb]" />
            </div>
            {conflictRows.length === 0 ? (
              <p className="text-xs text-black/35">{language === 'zh' ? '当前无冲突。' : 'No conflicts currently.'}</p>
            ) : (
              <div className="space-y-2 max-h-[220px] overflow-y-auto pr-1">
                {conflictRows.map((item) => {
                  const status = ticketStatusMap[item.id];
                  const statusLabel = status === 'open'
                    ? (language === 'zh' ? '已建单' : 'Open')
                    : status === 'processing'
                      ? (language === 'zh' ? '处理中' : 'Processing')
                      : status === 'resolved'
                        ? (language === 'zh' ? '已解决' : 'Resolved')
                        : (language === 'zh' ? '未建单' : 'No ticket');
                  return (
                    <div key={item.id} className="rounded-xl border border-black/10 px-3 py-2 flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-xs font-semibold text-[#00172D] truncate">{item.type.toUpperCase()} {item.key}</p>
                        <p className="text-[11px] text-black/45">{item.detail} · {item.impact.toUpperCase()}</p>
                        <p className="text-[11px] mt-1 text-black/35 inline-flex items-center gap-1"><Clock3 size={11} />{statusLabel}</p>
                      </div>
                      <button type="button" onClick={() => createOrUpdateTicket(item.id)} className="inline-flex items-center gap-1 rounded-lg border border-black/15 px-2 py-1 text-[11px] font-semibold text-black/65 hover:border-black/30 hover:text-black/85 transition-all">
                        <Ticket size={11} />
                        {status ? (language === 'zh' ? '推进状态' : 'Advance') : (language === 'zh' ? '创建工单' : 'Create')}
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
          </div>
        )}
      </div>

      {showAddSubnet && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-[80]" onClick={() => { setShowAddSubnet(false); setEditingSubnet(null); }}>
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg p-6" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-5">
              <h3 className="text-lg font-semibold text-[#00172D]">{editingSubnet ? (language === 'zh' ? '编辑子网' : 'Edit Subnet') : (language === 'zh' ? '添加子网' : 'Add Subnet')}</h3>
              <button onClick={() => { setShowAddSubnet(false); setEditingSubnet(null); }} className="p-1 text-black/30 hover:text-black/60" title="Close"><X size={18} /></button>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-[11px] font-semibold text-black/40 uppercase">{language === 'zh' ? '名称' : 'Name'}</label>
                <input value={formSubnet.name} onChange={e => setFormSubnet(f => ({ ...f, name: e.target.value }))} placeholder="Subnet-A" className="w-full mt-1 px-3 py-2 border border-black/10 rounded-lg text-sm outline-none focus:border-[#00bceb]/50" />
              </div>
              <div>
                <label className="text-[11px] font-semibold text-black/40 uppercase">{language === 'zh' ? '网段' : 'Network'}*</label>
                <input value={formSubnet.network} onChange={e => setFormSubnet(f => ({ ...f, network: e.target.value }))} placeholder="192.168.1.0" className="w-full mt-1 px-3 py-2 border border-black/10 rounded-lg text-sm outline-none focus:border-[#00bceb]/50" />
              </div>
              <div>
                <label className="text-[11px] font-semibold text-black/40 uppercase">{language === 'zh' ? '掩码' : 'Prefix'}*</label>
                <input type="number" value={formSubnet.prefix_len} onChange={e => setFormSubnet(f => ({ ...f, prefix_len: parseInt(e.target.value) || 24 }))} min={8} max={30} placeholder="24" className="w-full mt-1 px-3 py-2 border border-black/10 rounded-lg text-sm outline-none focus:border-[#00bceb]/50" />
              </div>
              <div>
                <label className="text-[11px] font-semibold text-black/40 uppercase">VLAN ID</label>
                <input value={formSubnet.vlan_id} onChange={e => setFormSubnet(f => ({ ...f, vlan_id: e.target.value }))} placeholder="100" className="w-full mt-1 px-3 py-2 border border-black/10 rounded-lg text-sm outline-none focus:border-[#00bceb]/50" />
              </div>
              <div>
                <label className="text-[11px] font-semibold text-black/40 uppercase">{language === 'zh' ? 'VLAN名称' : 'VLAN Name'}</label>
                <input value={formSubnet.vlan_name} onChange={e => setFormSubnet(f => ({ ...f, vlan_name: e.target.value }))} placeholder="Management" className="w-full mt-1 px-3 py-2 border border-black/10 rounded-lg text-sm outline-none focus:border-[#00bceb]/50" />
              </div>
              <div>
                <label className="text-[11px] font-semibold text-black/40 uppercase">{language === 'zh' ? '网关' : 'Gateway'}</label>
                <input value={formSubnet.gateway} onChange={e => setFormSubnet(f => ({ ...f, gateway: e.target.value }))} placeholder="192.168.1.1" className="w-full mt-1 px-3 py-2 border border-black/10 rounded-lg text-sm outline-none focus:border-[#00bceb]/50" />
              </div>
              <div>
                <label className="text-[11px] font-semibold text-black/40 uppercase">{language === 'zh' ? '站点' : 'Site'}</label>
                <input value={formSubnet.site} onChange={e => setFormSubnet(f => ({ ...f, site: e.target.value }))} placeholder="DC-1" className="w-full mt-1 px-3 py-2 border border-black/10 rounded-lg text-sm outline-none focus:border-[#00bceb]/50" />
              </div>
              <div className="col-span-2">
                <label className="text-[11px] font-semibold text-black/40 uppercase">{language === 'zh' ? '描述' : 'Description'}</label>
                <input value={formSubnet.description} onChange={e => setFormSubnet(f => ({ ...f, description: e.target.value }))} placeholder="..." className="w-full mt-1 px-3 py-2 border border-black/10 rounded-lg text-sm outline-none focus:border-[#00bceb]/50" />
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-5">
              <button onClick={() => { setShowAddSubnet(false); setEditingSubnet(null); }} className="px-4 py-2 text-sm text-black/50 hover:text-black/70">{language === 'zh' ? '取消' : 'Cancel'}</button>
              <button onClick={editingSubnet ? handleEditSubnet : handleAddSubnet} disabled={!formSubnet.network} className="px-5 py-2 rounded-xl bg-[#00bceb] text-white text-sm font-semibold hover:bg-[#00a5d0] disabled:opacity-40">{editingSubnet ? (language === 'zh' ? '保存' : 'Save') : (language === 'zh' ? '添加' : 'Add')}</button>
            </div>
          </div>
        </div>
      )}

      {showAddIP && selectedSubnet && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-[80]" onClick={() => { setShowAddIP(false); setEditingIP(null); }}>
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-5">
              <h3 className="text-lg font-semibold text-[#00172D]">{editingIP ? (language === 'zh' ? '编辑IP地址' : 'Edit IP Address') : (language === 'zh' ? '添加IP地址' : 'Add IP Address')}</h3>
              <button onClick={() => { setShowAddIP(false); setEditingIP(null); }} className="p-1 text-black/30 hover:text-black/60" title="Close"><X size={18} /></button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="text-[11px] font-semibold text-black/40 uppercase">{language === 'zh' ? 'IP地址' : 'Address'}*</label>
                <input value={formIP.address} onChange={e => setFormIP(f => ({ ...f, address: e.target.value }))} placeholder="192.168.1.10" disabled={!!editingIP} className={`w-full mt-1 px-3 py-2 border border-black/10 rounded-lg text-sm outline-none focus:border-[#00bceb]/50 ${editingIP ? 'bg-black/[0.03] text-black/40 cursor-not-allowed' : ''}`} />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[11px] font-semibold text-black/40 uppercase">{language === 'zh' ? '状态' : 'Status'}</label>
                  <select value={formIP.status} onChange={e => setFormIP(f => ({ ...f, status: e.target.value }))} className="w-full mt-1 px-3 py-2 border border-black/10 rounded-lg text-sm outline-none focus:border-[#00bceb]/50 bg-white">
                    <option value="active">{language === 'zh' ? '在用 (Active)' : 'Active'}</option>
                    <option value="reserved">{language === 'zh' ? '预留 (Reserved)' : 'Reserved'}</option>
                    <option value="deprecated">{language === 'zh' ? '停用 (Deprecated)' : 'Deprecated'}</option>
                  </select>
                </div>
                <div>
                  <label className="text-[11px] font-semibold text-black/40 uppercase">{language === 'zh' ? '设备类型' : 'Device Type'}</label>
                  <select value={formIP.device_type} onChange={e => setFormIP(f => ({ ...f, device_type: e.target.value }))} className="w-full mt-1 px-3 py-2 border border-black/10 rounded-lg text-sm outline-none focus:border-[#00bceb]/50 bg-white">
                    {DEVICE_TYPES.map(dt => (
                      <option key={dt.value} value={dt.value}>{dt.label[language === 'zh' ? 'zh' : 'en']}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div>
                <label className="text-[11px] font-semibold text-black/40 uppercase">{language === 'zh' ? '主机名' : 'Hostname'}</label>
                <input value={formIP.hostname} onChange={e => setFormIP(f => ({ ...f, hostname: e.target.value }))} placeholder="switch-01" className="w-full mt-1 px-3 py-2 border border-black/10 rounded-lg text-sm outline-none focus:border-[#00bceb]/50" />
              </div>
              <div>
                <label className="text-[11px] font-semibold text-black/40 uppercase">{language === 'zh' ? '接口' : 'Interface'}</label>
                <input value={formIP.interface_name} onChange={e => setFormIP(f => ({ ...f, interface_name: e.target.value }))} placeholder="GigabitEthernet0/1" className="w-full mt-1 px-3 py-2 border border-black/10 rounded-lg text-sm outline-none focus:border-[#00bceb]/50" />
              </div>
              <div>
                <label className="text-[11px] font-semibold text-black/40 uppercase">MAC</label>
                <input value={formIP.mac_address} onChange={e => setFormIP(f => ({ ...f, mac_address: e.target.value }))} placeholder="00:11:22:33:44:55" className="w-full mt-1 px-3 py-2 border border-black/10 rounded-lg text-sm outline-none focus:border-[#00bceb]/50" />
              </div>
              <div>
                <label className="text-[11px] font-semibold text-black/40 uppercase">{language === 'zh' ? '描述' : 'Description'}</label>
                <input value={formIP.description} onChange={e => setFormIP(f => ({ ...f, description: e.target.value }))} placeholder="..." className="w-full mt-1 px-3 py-2 border border-black/10 rounded-lg text-sm outline-none focus:border-[#00bceb]/50" />
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-5">
              <button onClick={() => { setShowAddIP(false); setEditingIP(null); }} className="px-4 py-2 text-sm text-black/50 hover:text-black/70">{language === 'zh' ? '取消' : 'Cancel'}</button>
              <button onClick={editingIP ? handleEditIP : handleAddIP} disabled={!formIP.address} className="px-5 py-2 rounded-xl bg-[#00bceb] text-white text-sm font-semibold hover:bg-[#00a5d0] disabled:opacity-40">{editingIP ? (language === 'zh' ? '保存' : 'Save') : (language === 'zh' ? '添加' : 'Add')}</button>
            </div>
          </div>
        </div>
      )}

      {/* Delete confirmation modal */}
      {confirmDelete && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-[90]" onClick={() => setConfirmDelete(null)}>
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm p-6" onClick={e => e.stopPropagation()}>
            <div className="flex flex-col items-center gap-3">
              <div className="w-12 h-12 rounded-full bg-red-50 flex items-center justify-center">
                <Trash2 size={20} className="text-red-500" />
              </div>
              <h3 className="text-base font-semibold text-[#00172D]">
                {language === 'zh' ? '确认删除' : 'Confirm Delete'}
              </h3>
              <p className="text-sm text-black/50 text-center">
                {confirmDelete.type === 'subnet'
                  ? (language === 'zh' ? `确定删除子网 "${confirmDelete.label}" 及其所有IP分配记录？此操作不可撤销。` : `Delete subnet "${confirmDelete.label}" and all its IP assignments? This cannot be undone.`)
                  : (language === 'zh' ? `确定删除IP地址 ${confirmDelete.label}？` : `Delete IP address ${confirmDelete.label}?`)}
              </p>
            </div>
            <div className="flex gap-3 mt-5">
              <button onClick={() => setConfirmDelete(null)} className="flex-1 px-4 py-2.5 rounded-xl border border-black/10 text-sm font-semibold text-black/60 hover:bg-black/5 transition-all">
                {language === 'zh' ? '取消' : 'Cancel'}
              </button>
              <button onClick={executeConfirmedDelete} className="flex-1 px-4 py-2.5 rounded-xl bg-red-500 text-white text-sm font-semibold hover:bg-red-600 transition-all">
                {language === 'zh' ? '确认删除' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default IPVlanTab;
