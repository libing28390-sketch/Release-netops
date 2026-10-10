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
import { ActionIconButton, ActionIconGroup } from '../../components/ui/ActionIconButton';
import { TableExportMenu } from '../../components/ui/TableExportMenu';
import { useEscapeClose } from '../../hooks/useEscapeClose';
import { useLocation, useNavigate } from 'react-router-dom';
import { formatMacAddress } from '../../utils/resourceFormatters';
import { buildVisibleIpamExportData, fetchAllIpamExportItems } from './ipamExport';

import { TableActionCell, TableActionHeader } from '../../components/ui/TableActionColumn';
interface IPAddress {
  id: string;
  subnet_id: string;
  address: string;
  hostname: string;
  device_id: string;
  interface_name: string;
  mac_address: string;
  device_type: string;
  purpose?: string;
  status: string;
  description: string;
  expires_at?: string;
  last_seen: string;
  created_at: string;
  updated_at: string;
  site_id?: string;
  site_name?: string;
  subnet_prefix?: string;
  subnet_name?: string;
  network_type?: string;
  source?: 'manual' | 'manual+discovered' | 'discovered' | 'prefix_gateway';
  is_discovered?: boolean;
  is_prefix_gateway?: boolean;
  is_virtual_gateway?: boolean;
  discovered_last_seen?: string;
  available_after?: string;
  switch_name?: string;
  switch_port?: string;
  vlan?: string;
  bound_device_hostname?: string;
  linked_asset_id?: string;
  asset_tag?: string;
  asset_serial_number?: string;
  asset_hostname?: string;
  asset_vendor?: string;
  asset_model?: string;
  asset_management_ip?: string;
  asset_business_ip?: string;
}

function sourceLabel(address: IPAddress, zh: boolean): string {
  if (address.source === 'manual+discovered') return zh ? 'IPAM + 采集' : 'IPAM + Discovery';
  if (address.source === 'prefix_gateway' || address.is_prefix_gateway) return zh ? '前缀网关' : 'Prefix gateway';
  if (address.source === 'discovered' || address.is_discovered) return zh ? '自动发现' : 'Discovered';
  if (address.source === 'manual') return zh ? '手工登记' : 'Manual';
  return address.is_virtual_gateway ? (zh ? '前缀配置' : 'Prefix config') : (zh ? '手工登记' : 'Manual');
}

function assetInfoLabel(address: IPAddress, zh: boolean): string {
  const values = [
    address.asset_tag ? `${zh ? '编号' : 'Tag'}: ${address.asset_tag}` : '',
    address.asset_serial_number ? `${zh ? '序列号' : 'Serial'}: ${address.asset_serial_number}` : '',
  ].filter(Boolean);
  return values.join(' · ') || '-';
}

interface DeviceCandidate {
  id: string;
  hostname?: string;
  ip_address?: string;
  asset_id?: string;
  asset_tag?: string;
  asset_serial_number?: string;
  asset_hostname?: string;
  asset_vendor?: string;
  asset_model?: string;
  asset_management_ip?: string;
  asset_business_ip?: string;
  asset_type?: string;
}

interface SiteSummary {
  id: string;
  name: string;
  code: string;
  count: number;
  ip_count?: number;
}

interface Prefix {
  id: string;
  prefix: string;
  name: string;
  site_id?: string;
  parent_prefix_id?: string | null;
  status?: string;
  network_type?: string;
  gateway?: string;
  vrf_id?: string;
  vlan_id?: string;
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
  { value: 'available', zh: '空闲', en: 'Available' },
  { value: 'active', zh: '使用中', en: 'Active' },
  { value: 'reserved', zh: '已保留', en: 'Reserved' },
  { value: 'deprecated', zh: '已弃用', en: 'Deprecated' },
];

const IP_PURPOSE_OPTIONS: { value: string; zh: string; en: string }[] = [
  { value: 'management', zh: '管理地址', en: 'Management' },
  { value: 'business', zh: '业务地址', en: 'Business' },
  { value: 'infrastructure', zh: '基础设施', en: 'Infrastructure' },
  { value: 'transit', zh: '设备互联', en: 'Transit' },
  { value: 'loopback', zh: 'Loopback', en: 'Loopback' },
  { value: 'vip', zh: 'VIP / 服务地址', en: 'VIP / Service' },
  { value: 'dhcp', zh: 'DHCP 动态地址', en: 'DHCP' },
  { value: 'temporary', zh: '临时 / 测试', en: 'Temporary / Test' },
  { value: 'other', zh: '其他', en: 'Other' },
];

const PREFIX_PURPOSE_MAP: Record<string, string> = {
  management: 'management',
  server: 'business',
  user: 'business',
  user_access: 'business',
  dmz: 'business',
  wireless: 'business',
  voice: 'business',
  storage: 'business',
  container: 'business',
  network_service: 'infrastructure',
  transit: 'transit',
  p2p: 'transit',
  wan: 'transit',
  loopback: 'loopback',
  vip: 'vip',
  vpn: 'business',
};

const inferIpPurpose = (networkType?: string): string => PREFIX_PURPOSE_MAP[String(networkType || '').trim().toLowerCase()] || 'business';

const defaultRoleForPurpose = (purpose: string): string => ({
  management: 'device',
  business: 'server',
  infrastructure: 'gateway',
  transit: 'transit',
  loopback: 'loopback',
  vip: 'vip',
  dhcp: 'host',
  temporary: 'host',
  other: 'host',
}[purpose] || 'host');

const purposeLabel = (value: string | undefined, zh: boolean): string => {
  const option = IP_PURPOSE_OPTIONS.find((item) => item.value === value);
  return option ? (zh ? option.zh : option.en) : (value || (zh ? '未分类' : 'Unclassified'));
};

// 可搜索的绑定设备下拉
const roleLabel = (v: string, zh: boolean): string => {
  const o = ROLE_OPTIONS.find((x) => x.value === v);
  return o ? (zh ? o.zh : o.en) : (v || '').toUpperCase();
};

const statusLabel = (v: string, zh: boolean): string => {
  const o = STATUS_OPTIONS.find((x) => x.value === v);
  return o ? (zh ? o.zh : o.en) : (v || '').toUpperCase();
};

const prefixMaskLength = (prefix: string): number => {
  const raw = prefix.split('/')[1];
  const value = Number.parseInt(raw || '', 10);
  return Number.isFinite(value) ? value : -1;
};

const isHostRoutePrefix = (prefix: string): boolean => {
  const mask = prefixMaskLength(prefix);
  return prefix.includes(':') ? mask === 128 : mask === 32;
};

const PrefixSearchSelect: React.FC<{
  prefixes: Prefix[];
  value: string;
  onChange: (id: string) => void;
  zh: boolean;
}> = ({ prefixes, value, onChange, zh }) => {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const wrapRef = useRef<HTMLDivElement>(null);
  const selected = prefixes.find((prefix) => prefix.id === value);
  const prefixById = useMemo(() => new Map(prefixes.map(prefix => [prefix.id, prefix])), [prefixes]);

  useEffect(() => {
    const onDocumentMouseDown = (event: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) {
        setOpen(false);
        setQuery('');
      }
    };
    document.addEventListener('mousedown', onDocumentMouseDown);
    return () => document.removeEventListener('mousedown', onDocumentMouseDown);
  }, []);

  const visiblePrefixes = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return prefixes.filter(prefix => !normalized ||
      prefix.prefix.toLowerCase().includes(normalized) ||
      (prefix.name || '').toLowerCase().includes(normalized)
    );
  }, [prefixes, query]);

  const depthOf = (prefix: Prefix) => {
    let depth = 0;
    let parentId = prefix.parent_prefix_id;
    const visited = new Set<string>();
    while (parentId && prefixById.has(parentId) && !visited.has(parentId) && depth < 6) {
      visited.add(parentId);
      depth += 1;
      parentId = prefixById.get(parentId)?.parent_prefix_id;
    }
    return depth;
  };

  const renderGroup = (title: string, items: Prefix[]) => (
    <>
      <div className="sticky top-0 bg-slate-50 px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400">
        {title} · {items.length}
      </div>
      {items.map(prefix => {
        const depth = depthOf(prefix);
        return (
          <button
            type="button"
            key={prefix.id}
            onClick={() => {
              onChange(prefix.id);
              setOpen(false);
              setQuery('');
            }}
            className={`flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-cyan-50 ${
              prefix.id === value ? 'bg-cyan-50 font-bold text-cyan-700' : 'text-gray-700'
            }`}
          >
            <span className="shrink-0 text-gray-300" style={{ width: `${depth * 12}px` }} />
            {depth > 0 && <span className="text-gray-300">└</span>}
            <span className="font-mono font-semibold">{prefix.prefix}</span>
            {prefix.name && <span className="truncate text-gray-400">({prefix.name})</span>}
          </button>
        );
      })}
    </>
  );

  const capacityPrefixes = visiblePrefixes.filter(prefix => !isHostRoutePrefix(prefix.prefix));
  const hostRoutes = visiblePrefixes.filter(prefix => isHostRoutePrefix(prefix.prefix));

  return (
    <div ref={wrapRef} className="relative min-w-[280px]">
      <div className="relative">
        <Search size={13} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
        <input type="search"
          value={open ? query : selected ? `${selected.prefix}${selected.name ? ` (${selected.name})` : ''}` : ''}
          onChange={event => {
            setQuery(event.target.value);
            setOpen(true);
          }}
          onFocus={() => {
            setOpen(true);
            setQuery('');
          }}
          placeholder={zh ? '搜索 CIDR 或名称...' : 'Search CIDR or name...'}
          className="w-full rounded-xl border border-black/5 bg-white py-1.5 pl-8 pr-3 text-xs font-bold text-gray-700 outline-none transition-all focus:border-cyan-400 focus:shadow-sm"
        />
      </div>
      {open && (
        <div className="absolute right-0 z-50 mt-1 max-h-80 w-full min-w-[360px] overflow-auto rounded-xl border border-gray-150 bg-white py-1 shadow-xl">
          {capacityPrefixes.length > 0 && renderGroup(zh ? '容量与业务网段' : 'Capacity & business prefixes', capacityPrefixes)}
          {hostRoutes.length > 0 && renderGroup(zh ? '主机路由（不计容量）' : 'Host routes (excluded from capacity)', hostRoutes)}
          {visiblePrefixes.length === 0 && (
            <div className="px-4 py-5 text-center text-xs text-gray-400">
              {zh ? '没有匹配的 Prefix' : 'No matching prefix'}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const deviceHostLabel = (device: DeviceCandidate): string =>
  device.hostname || device.asset_hostname || device.ip_address || device.id;

const deviceAssetLabel = (device: DeviceCandidate): string =>
  device.asset_tag || device.asset_hostname || '';

const deviceDisplayLabel = (device: DeviceCandidate): string => {
  const host = deviceHostLabel(device);
  const asset = deviceAssetLabel(device);
  return asset && asset !== host ? `${asset} · ${host}` : host;
};

const DeviceSearchSelect: React.FC<{
  devices: DeviceCandidate[];
  value: string;
  onChange: (id: string) => void;
  zh: boolean;
}> = ({ devices, value, onChange, zh }) => {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const wrapRef = useRef<HTMLDivElement>(null);

  const selected = devices.find((d) => d.id === value);
  const display = selected
    ? `${deviceDisplayLabel(selected)}${selected.ip_address && selected.hostname ? ` (${selected.ip_address})` : ''}`
    : '';

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
        return [
          d.hostname, d.ip_address, d.asset_tag, d.asset_serial_number,
          d.asset_hostname, d.asset_vendor, d.asset_model,
          d.asset_management_ip, d.asset_business_ip,
        ].some(value => String(value || '').toLowerCase().includes(q));
      })
    : devices;

  return (
    <div className="relative" ref={wrapRef}>
      <input
        type="search"
        value={open ? query : display}
        onChange={(e) => {
          setQuery(e.target.value);
          if (!open) setOpen(true);
        }}
        onFocus={() => {
          setOpen(true);
          setQuery('');
        }}
        placeholder={zh ? '搜索资产编号 / 序列号 / 主机名 / IP...' : 'Search asset tag / serial / hostname / IP...'}
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
              <div className="truncate font-semibold">{deviceDisplayLabel(d)}</div>
              <div className="mt-0.5 truncate text-[10px] text-gray-400">
                {d.ip_address || (zh ? '未填写管理IP' : 'No management IP')}
                {d.asset_serial_number ? ` · SN ${d.asset_serial_number}` : ''}
                {!d.asset_tag && d.asset_id ? ` · ${zh ? '已关联资产' : 'Linked asset'}` : ''}
              </div>
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
  const addressTableRef = useRef<HTMLTableElement>(null);

  // Get search params
  const params = new URLSearchParams(location.search);
  const prefixIdParam = params.get('prefix_id') || '';

  const [addresses, setAddresses] = useState<IPAddress[]>([]);
  const [prefixes, setPrefixes] = useState<Prefix[]>([]);
  const [sites, setSites] = useState<SiteSummary[]>([]);
  const [inventorySummary, setInventorySummary] = useState({ total: 0, discovered: 0, manual: 0, gateways: 0, prefixes: 0 });
  const [loading, setLoading] = useState(true);
  const [inventoryError, setInventoryError] = useState('');
  const inventoryRequest = useRef<AbortController | null>(null);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [typeFilter, setTypeFilter] = useState('all');
  const [purposeFilter, setPurposeFilter] = useState('all');
  const [isMatrixView, setIsMatrixView] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [totalItems, setTotalItems] = useState(0);

  // Lookup data
  const [devices, setDevices] = useState<DeviceCandidate[]>([]);
  const [selectedPrefixId, setSelectedPrefixId] = useState(prefixIdParam);
  const [selectedSiteId, setSelectedSiteId] = useState('all');
  const [activePrefix, setActivePrefix] = useState<Prefix | null>(null);

  // Modals
  const [showAddEdit, setShowAddEdit] = useState(false);
  const [editingIP, setEditingIP] = useState<IPAddress | null>(null);
  const [isQuickAllocation, setIsQuickAllocation] = useState(false);
  const [showAdvancedFields, setShowAdvancedFields] = useState(false);
  const hasLoadedInventory = useRef(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<string | null>(null);
  useEscapeClose(showAddEdit, () => { setShowAddEdit(false); setEditingIP(null); });
  useEscapeClose(Boolean(showDeleteConfirm), () => setShowDeleteConfirm(null));

  // Form State
  const [form, setForm] = useState({
    subnet_id: '', // selected prefix ID
    address: '',
    hostname: '',
    device_id: '',
    interface_name: '',
    mac_address: '',
    device_type: 'server',
    purpose: 'business',
    status: 'active',
    description: '',
    expires_at: '',
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
      const devRes = await fetch('/api/devices?mode=light&page=1&page_size=1000', { headers: hdrs });
      if (devRes.ok) {
        const raw = await devRes.json();
        setDevices(Array.isArray(raw) ? raw : (raw.items || []));
      }
    } catch (e) {
      console.error(e);
    }
  }, [authHeaders, prefixIdParam]);

  const loadData = useCallback(async () => {
    inventoryRequest.current?.abort();
    const controller = new AbortController();
    inventoryRequest.current = controller;
    if (!hasLoadedInventory.current) setLoading(true);
    setInventoryError('');
    const hdrs = authHeaders();
    let loadSucceeded = false;
    try {
      const query = new URLSearchParams({
        site_id: selectedSiteId,
        page: String(isMatrixView ? 1 : page),
        page_size: String(isMatrixView ? 100 : pageSize),
      });
      if (selectedPrefixId) query.set('prefix_id', selectedPrefixId);
      if (search.trim()) query.set('q', search.trim());
      if (statusFilter !== 'all' && (!isMatrixView || statusFilter !== 'available')) query.set('status', statusFilter);
      if (typeFilter !== 'all' && (!isMatrixView || statusFilter !== 'available')) query.set('device_type', typeFilter);
      if (purposeFilter !== 'all' && (!isMatrixView || statusFilter !== 'available')) query.set('purpose', purposeFilter);
      const loadedItems: IPAddress[] = [];
      let responseTotal = 0;
      let firstPageData: {
        items?: IPAddress[];
        total?: number;
        has_more?: boolean;
        sites?: SiteSummary[];
        summary?: { total?: number; discovered?: number; manual?: number; gateways?: number; prefixes?: number };
      } | null = null;
      let queryFailed = false;
      let currentPage = isMatrixView ? 1 : page;
      while (true) {
        const requestQuery = new URLSearchParams(query);
        requestQuery.set('page', String(currentPage));
        const res = await fetch(`/api/ipam/addresses?${requestQuery.toString()}`, { headers: hdrs, signal: controller.signal });
        if (!res.ok) {
          queryFailed = true;
          setInventoryError(res.status === 401
            ? (zh ? '登录已过期，请重新登录后重试。' : 'Your session has expired. Sign in and retry.')
            : res.status === 403
              ? (zh ? '当前账号没有查看 IP 清单的权限。' : 'You do not have permission to view the IP inventory.')
              : (zh ? '加载 IP 地址库存失败，请重试。' : 'Failed to load IP inventory. Please retry.'));
          break;
        }
        const data = await res.json();
        if (Array.isArray(data)) {
          loadedItems.push(...data);
          responseTotal = data.length;
          break;
        }
        if (!firstPageData) firstPageData = data;
        const pageItems: IPAddress[] = data.items || [];
        loadedItems.push(...pageItems);
        responseTotal = Number(data.total || 0);
        if (!isMatrixView || !data.has_more || pageItems.length === 0 || loadedItems.length >= responseTotal) break;
        currentPage += 1;
      }
      if (queryFailed) {
        if (!hasLoadedInventory.current) {
          setAddresses([]);
          setTotalItems(0);
          setInventorySummary({ total: 0, discovered: 0, manual: 0, gateways: 0, prefixes: 0 });
        }
        return;
      }
      loadSucceeded = true;
      setAddresses(loadedItems);
      setTotalItems(responseTotal);
      if (firstPageData) {
        setSites(firstPageData.sites || []);
        setInventorySummary({
          total: Number(firstPageData.summary?.total || 0),
          discovered: Number(firstPageData.summary?.discovered || 0),
          manual: Number(firstPageData.summary?.manual || 0),
          gateways: Number(firstPageData.summary?.gateways || 0),
          prefixes: Number(firstPageData.summary?.prefixes || 0),
        });
      }
    } catch (e) {
      if (controller.signal.aborted) return;
      console.error(e);
      if (!hasLoadedInventory.current) {
        setAddresses([]);
        setTotalItems(0);
        setInventorySummary({ total: 0, discovered: 0, manual: 0, gateways: 0, prefixes: 0 });
      }
      setInventoryError(zh ? '加载 IP 地址库存失败，请重试。' : 'Failed to load IP inventory. Please retry.');
    } finally {
      if (inventoryRequest.current === controller) {
        inventoryRequest.current = null;
        if (loadSucceeded) hasLoadedInventory.current = true;
        setLoading(false);
      }
    }
  }, [selectedPrefixId, selectedSiteId, search, statusFilter, typeFilter, purposeFilter, page, isMatrixView, authHeaders, zh]);

  useEffect(() => {
    fetchLookups();
  }, [fetchLookups]);

  useEffect(() => () => {
    const activeRequest = inventoryRequest.current;
    inventoryRequest.current = null;
    activeRequest?.abort();
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const siteScopedPrefixes = useMemo(
    () => selectedSiteId === 'all'
      ? prefixes
      : prefixes.filter((prefix) => prefix.site_id === selectedSiteId),
    [prefixes, selectedSiteId],
  );

  // Handle prefix switch
  const handlePrefixChange = (id: string) => {
    setSelectedPrefixId(id);
    setPage(1);
    const matched = siteScopedPrefixes.find((p) => p.id === id) || null;
    setActivePrefix(matched);
    navigate(`/ipam/ips?prefix_id=${id}`);
  };

  const handleSiteChange = (id: string) => {
    setSelectedSiteId(id);
    setSelectedPrefixId('');
    setActivePrefix(null);
    setPage(1);
    navigate('/ipam/ips');
  };

  const prefixMask = useMemo(() => {
    if (!activePrefix?.prefix || !activePrefix.prefix.includes('/')) return 0;
    const mask = parseInt(activePrefix.prefix.split('/')[1], 10);
    return isNaN(mask) ? 0 : mask;
  }, [activePrefix]);

  const canUseMatrix = prefixMask >= 24 && prefixMask <= 30 && !activePrefix?.prefix.includes(':');
  const matrixPrefixCandidate = useMemo(() => {
    if (canUseMatrix && activePrefix) return activePrefix;
    return siteScopedPrefixes.find((prefix) => {
      const mask = prefixMaskLength(prefix.prefix);
      return mask >= 24 && mask <= 30 && !prefix.prefix.includes(':');
    }) || null;
  }, [activePrefix, canUseMatrix, siteScopedPrefixes]);

  const handleMatrixClick = () => {
    const target = matrixPrefixCandidate;
    if (!target) return;
    if (activePrefix?.id !== target.id) {
      setSelectedPrefixId(target.id);
      setActivePrefix(target);
      navigate(`/ipam/ips?prefix_id=${target.id}`);
    }
    setPage(1);
    setIsMatrixView(true);
  };

  // Filtered IP list
  const filteredAddresses = addresses;

  const matrixData = useMemo(() => {
    if (!isMatrixView || !canUseMatrix || !activePrefix) return [];
    const cidr = activePrefix.prefix;
    const [ipPart, maskPart] = cidr.split('/');
    const mask = parseInt(maskPart, 10);
    const ipParts = ipPart.split('.').map(Number);
    if (ipParts.length !== 4 || ipParts.some(isNaN)) return [];
    
    const rawBaseInt = ipParts[0] * 16777216 + ipParts[1] * 65536 + ipParts[2] * 256 + ipParts[3];
    const numHosts = Math.pow(2, 32 - mask);
    const baseInt = rawBaseInt - (rawBaseInt % numHosts);
    const gateway = activePrefix.gateway || '';

    const hasActiveFilters = statusFilter !== 'all' || typeFilter !== 'all' || purposeFilter !== 'all' || Boolean(search.trim());
    const allRegisteredMap = new Map<string, IPAddress>();
    addresses.forEach((addr) => {
      allRegisteredMap.set(addr.address, addr);
    });
    const registeredMap = new Map<string, IPAddress>();
    filteredAddresses.forEach((addr) => {
      registeredMap.set(addr.address, addr);
    });

    const list: Array<{ ip: string; data: IPAddress | null; status: string; systemReason?: string; isGateway: boolean }> = [];
    const isReusableRecord = (item: IPAddress | undefined) => {
      if (!item || !['available', 'released'].includes(item.status)) return false;
      if (!item.available_after) return true;
      const availableAt = new Date(item.available_after).getTime();
      return Number.isNaN(availableAt) || availableAt <= Date.now();
    };
    for (let i = 0; i < numHosts; i++) {
      const currentVal = baseInt + i;
      const p1 = Math.floor(currentVal / 16777216) % 256;
      const p2 = Math.floor(currentVal / 65536) % 256;
      const p3 = Math.floor(currentVal / 256) % 256;
      const p4 = currentVal % 256;
      const ipStr = `${p1}.${p2}.${p3}.${p4}`;
      const registeredData = allRegisteredMap.get(ipStr);
      const occupiedData = isReusableRecord(registeredData) ? null : (registeredData || null);
      const isNetworkOrBroadcast = mask < 31 && (i === 0 || i === numHosts - 1);
      const isGateway = Boolean(gateway && gateway === ipStr && !isNetworkOrBroadcast);
      const systemReason = isNetworkOrBroadcast
        ? (i === 0 ? (zh ? '网络地址' : 'Network address') : (zh ? '广播地址' : 'Broadcast address'))
        : '';
      const systemReserved = !occupiedData && Boolean(systemReason);
      if (statusFilter === 'available') {
        if (occupiedData || isGateway || systemReserved || (search.trim() && !ipStr.includes(search.trim()))) continue;
      }
      const filteredData = registeredMap.get(ipStr);
      const matchedData = statusFilter === 'available' || isReusableRecord(filteredData)
        ? null
        : (filteredData || null);
      if (hasActiveFilters && statusFilter !== 'available' && !matchedData) continue;
      
      let status = 'available';
      if (matchedData) {
        status = matchedData.status;
      } else if (isGateway) {
        status = 'active';
      } else if (systemReserved) {
        status = 'system';
      }
      
      list.push({
        ip: ipStr,
        data: matchedData,
        status,
        systemReason,
        isGateway,
      });
    }
    return list;
  }, [isMatrixView, canUseMatrix, activePrefix, addresses, filteredAddresses, search, statusFilter, typeFilter, purposeFilter, zh]);

  const paginatedAddresses = filteredAddresses;

  const exportData = useCallback(async () => {
    const params = new URLSearchParams({ site_id: selectedSiteId });
    if (selectedPrefixId) params.set('prefix_id', selectedPrefixId);
    if (search.trim()) params.set('q', search.trim());
    if (statusFilter !== 'all' && (!isMatrixView || statusFilter !== 'available')) params.set('status', statusFilter);
    if (typeFilter !== 'all' && (!isMatrixView || statusFilter !== 'available')) params.set('device_type', typeFilter);
    if (purposeFilter !== 'all' && (!isMatrixView || statusFilter !== 'available')) params.set('purpose', purposeFilter);
    const allAddresses = await fetchAllIpamExportItems<IPAddress>('/api/ipam/addresses', params);
    const linkedDeviceName = (node: IPAddress) => {
      if (node.switch_name || node.bound_device_hostname) return node.switch_name || node.bound_device_hostname || '-';
      const device = devices.find((candidate) => candidate.id === node.device_id);
      return device ? deviceHostLabel(device) : '-';
    };
    return buildVisibleIpamExportData(addressTableRef.current, [
      { header: zh ? '站点' : 'Site', value: (node) => node.site_name || '-' },
      { header: zh ? '网段' : 'Prefix', value: (node) => node.subnet_prefix || '-' },
      { header: zh ? 'IP地址' : 'IP Address', value: (node) => node.address },
      { header: zh ? '用途' : 'Purpose', value: (node) => purposeLabel(node.purpose || inferIpPurpose(node.network_type), zh) },
      { header: zh ? '类型' : 'Role Type', value: (node) => roleLabel(node.device_type, zh) },
      { header: zh ? '主机名 / 域名' : 'DNS Hostname', value: (node) => node.hostname || '-' },
      { header: zh ? '关联设备' : 'Linked Device', value: linkedDeviceName },
      { header: zh ? '资产编号' : 'Asset Tag', value: (node) => node.asset_tag || '-' },
      { header: zh ? '资产序列号' : 'Asset Serial', value: (node) => node.asset_serial_number || '-' },
      { header: zh ? '接口' : 'Interface', value: (node) => node.switch_port || node.interface_name || '-' },
      { header: zh ? 'MAC地址' : 'MAC Address', value: (node) => formatMacAddress(node.mac_address) || '-' },
      { header: zh ? '状态' : 'Status', value: (node) => statusLabel(node.status, zh) },
      { header: zh ? '备注描述' : 'Description', value: (node) => node.description || '-' },
      { header: zh ? '发现时间' : 'Last Seen', value: (node) => (node.discovered_last_seen || node.last_seen) ? (node.discovered_last_seen || node.last_seen).replace('T', ' ').slice(0, 19) : '-' },
    ], allAddresses);
  }, [selectedSiteId, selectedPrefixId, search, statusFilter, isMatrixView, typeFilter, purposeFilter, zh, devices]);

  // Form handling
  const openForm = (ipItem: IPAddress | null = null, quickAllocation = false) => {
    setErrorMsg('');
    setIsQuickAllocation(quickAllocation && !ipItem?.id);
    setShowAdvancedFields(Boolean(ipItem?.id));
    const inheritedPurpose = inferIpPurpose(ipItem?.network_type || activePrefix?.network_type);
    if (ipItem?.id) {
      setEditingIP(ipItem);
      setForm({
        subnet_id: ipItem.subnet_id || selectedPrefixId,
        address: ipItem.address,
        hostname: ipItem.hostname || '',
        device_id: ipItem.device_id || '',
        interface_name: ipItem.interface_name || '',
        mac_address: ipItem.mac_address || '',
        device_type: ipItem.device_type || defaultRoleForPurpose(inheritedPurpose),
        purpose: ipItem.purpose || inheritedPurpose,
        status: ipItem.status || 'active',
        description: ipItem.description || '',
        expires_at: ipItem.expires_at || '',
      });
    } else {
      setEditingIP(null);
      setForm({
        subnet_id: ipItem?.subnet_id || selectedPrefixId,
        address: ipItem?.address || '',
        hostname: ipItem?.hostname || '',
        device_id: ipItem?.device_id || '',
        interface_name: ipItem?.interface_name || '',
        mac_address: ipItem?.mac_address || '',
        device_type: ipItem?.device_type || defaultRoleForPurpose(inheritedPurpose),
        purpose: ipItem?.purpose || inheritedPurpose,
        status: ipItem?.status && ipItem.status !== 'available' ? ipItem.status : 'active',
        description: ipItem?.description || '',
        expires_at: ipItem?.expires_at || '',
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
      const res = await fetch(`/api/ipam/addresses/${id}/release`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: '{}',
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
    return dev ? deviceHostLabel(dev) : '-';
  };

  return (
    <div className="flex-1 flex min-w-0 flex-col h-full overflow-hidden px-4 py-4 lg:px-6 lg:py-5 space-y-4">
      <PageHero
        icon={MapPin}
        title={zh ? 'IP地址分配管理' : 'IP Address Management'}
        subtitle={zh ? '精细管理每一个网段内的IP分配，区分网段用途、IP用途、设备角色与生命周期' : 'Manage prefix and IP purposes separately from device roles and lifecycle.'}
        actions={
          <div className="flex items-center gap-2">
            {!loading && (!isMatrixView || !canUseMatrix) && <TableExportMenu tableRef={addressTableRef} exportData={exportData} filename="ipam-addresses" language={zh ? 'zh' : 'en'} disabled={paginatedAddresses.length === 0} />}
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
          </div>
        }
        extras={
          <div className="w-full space-y-3">
            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 xl:grid-cols-[minmax(220px,0.9fr)_minmax(280px,1.1fr)_auto]">
              {/* Site scope */}
              <label className="flex min-w-0 items-center gap-2">
                <span className="shrink-0 text-xs font-bold uppercase tracking-wider text-gray-400">{zh ? '站点' : 'Site'}</span>
                <select
                  value={selectedSiteId}
                  onChange={(e) => handleSiteChange(e.target.value)}
                  className="min-w-0 flex-1 rounded-xl border border-black/5 bg-white px-3 py-2 text-xs font-semibold text-gray-600 outline-none transition-all"
                >
                  <option value="all">{zh ? `全部站点 (${inventorySummary.prefixes} 个网段)` : `All Sites (${inventorySummary.prefixes} prefixes)`}</option>
                  {sites.map((site) => (
                    <option key={site.id} value={site.id}>{site.name} ({site.count} {zh ? '个网段' : 'prefixes'})</option>
                  ))}
                </select>
              </label>

              {/* Prefix Selector */}
              <div className="flex min-w-0 items-center gap-2">
                <span className="shrink-0 text-xs font-bold uppercase tracking-wider text-gray-400">{zh ? '网段' : 'Prefix'}</span>
                <div className="min-w-0 flex-1">
                  <PrefixSearchSelect
                    prefixes={siteScopedPrefixes}
                    value={selectedPrefixId}
                    onChange={handlePrefixChange}
                    zh={zh}
                  />
                </div>
              </div>

              <div className="flex min-h-9 flex-wrap items-center gap-2 text-[10px] text-gray-400 sm:col-span-2 xl:col-span-1 xl:justify-end">
                <span className="rounded-full bg-cyan-50 px-2.5 py-1 font-bold text-cyan-600">{zh ? `IP记录 ${inventorySummary.total}` : `${inventorySummary.total} IPs`}</span>
                <span className="rounded-full bg-emerald-50 px-2.5 py-1 font-bold text-emerald-600">{zh ? `自动发现 ${inventorySummary.discovered}` : `${inventorySummary.discovered} discovered`}</span>
                {inventorySummary.gateways > 0 && <span className="rounded-full bg-amber-50 px-2.5 py-1 font-bold text-amber-700">{zh ? `前缀网关 ${inventorySummary.gateways}` : `${inventorySummary.gateways} gateways`}</span>}
              </div>
            </div>

            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-[repeat(3,minmax(0,0.75fr))_minmax(220px,1.35fr)_auto]">
              {/* Filters */}
              <select
                aria-label={zh ? '按状态筛选 IP 地址' : 'Filter IP addresses by status'}
                value={statusFilter}
                onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
                className="w-full min-w-0 rounded-xl border border-black/5 bg-white px-3 py-2 text-xs font-semibold text-gray-600 outline-none transition-all"
              >
                <option value="all">{zh ? '所有状态' : 'All Status'}</option>
                {STATUS_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{zh ? o.zh : o.en}</option>
                ))}
              </select>

              <select
                aria-label={zh ? '按类型筛选 IP 地址' : 'Filter IP addresses by role type'}
                value={typeFilter}
                onChange={(e) => { setTypeFilter(e.target.value); setPage(1); }}
                className="w-full min-w-0 rounded-xl border border-black/5 bg-white px-3 py-2 text-xs font-semibold text-gray-600 outline-none transition-all"
              >
                <option value="all">{zh ? '所有类型' : 'All Types'}</option>
                {ROLE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{zh ? o.zh : o.en}</option>
                ))}
              </select>

              <select
                aria-label={zh ? '按用途筛选 IP 地址' : 'Filter IP addresses by purpose'}
                value={purposeFilter}
                onChange={(e) => { setPurposeFilter(e.target.value); setPage(1); }}
                className="w-full min-w-0 rounded-xl border border-black/5 bg-white px-3 py-2 text-xs font-semibold text-gray-600 outline-none transition-all"
              >
                <option value="all">{zh ? '所有用途' : 'All Purposes'}</option>
                {IP_PURPOSE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{zh ? o.zh : o.en}</option>
                ))}
              </select>

              {/* Search Input */}
              <div className="relative min-w-0">
                <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
                <input
                  type="search"
                  value={search}
                  onChange={(e) => { setSearch(e.target.value); setPage(1); }}
                  aria-label={zh ? '搜索 IP、主机名、接口' : 'Search IP, hostname, or interface'}
                  placeholder={zh ? '搜索 IP、主机名、接口...' : 'Search IP, hostname...'}
                  className="w-full min-w-0 rounded-xl border border-black/5 bg-gray-50/50 py-2 pl-10 pr-4 text-xs font-medium outline-none transition-all focus:border-cyan-400 focus:bg-white"
                />
              </div>

              {/* View Switcher Toggle */}
              <div className="flex w-fit items-center justify-self-start rounded-xl border border-black/5 bg-gray-50 p-0.5 sm:col-span-2 xl:col-span-1 xl:justify-self-end">
                <button
                  onClick={() => { setPage(1); setIsMatrixView(false); }}
                  className={`px-3 py-1 text-[10px] font-bold rounded-lg transition-all ${
                    !isMatrixView
                      ? 'bg-white shadow-sm text-cyan-600'
                      : 'text-gray-450 hover:text-gray-600'
                  }`}
                >
                  {zh ? '列表' : 'List'}
                </button>
                <button
                  disabled={!matrixPrefixCandidate}
                  onClick={handleMatrixClick}
                  title={!matrixPrefixCandidate ? (zh ? '当前站点没有可用的 IPv4 /24 - /30 网段' : 'No IPv4 /24-/30 prefix is available for the current site') : (zh ? '矩阵按单个网段展示' : 'Matrix view is scoped to one prefix')}
                  className={`px-3 py-1 text-[10px] font-bold rounded-lg transition-all ${
                    isMatrixView
                      ? 'bg-white shadow-sm text-cyan-600'
                      : !matrixPrefixCandidate
                      ? 'text-gray-250 cursor-not-allowed opacity-50'
                      : 'text-gray-450 hover:text-gray-600'
                  }`}
                >
                  {zh ? '矩阵' : 'Matrix'}
                </button>
              </div>
            </div>
          </div>
        }
      />

      {inventoryError && (
        <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2 text-xs font-semibold text-rose-700">
          <span>{inventoryError}</span>
          <button type="button" onClick={loadData} className="rounded-lg bg-white px-3 py-1.5 text-rose-700 shadow-sm hover:bg-rose-100">
            {zh ? '重试' : 'Retry'}
          </button>
        </div>
      )}

      {/* Main Table Card */}
      <div className="flex-1 min-h-0 min-w-0 bg-white rounded-[28px] border border-black/5 shadow-[0_16px_36px_rgba(11,35,64,0.06)] overflow-hidden flex flex-col">
        <div className="flex-1 min-h-0 min-w-0 overflow-auto">
          {loading ? (
            <div className="h-full flex items-center justify-center text-xs text-gray-400 font-semibold">
              {zh ? '加载中...' : 'Loading IP allocations...'}
            </div>
          ) : isMatrixView && canUseMatrix ? (
            /* Render Grid Matrix View */
            <div className="p-6 overflow-auto">
              <div className="mb-4.5 flex flex-wrap items-center justify-between gap-4 text-xs text-gray-500 border-b border-gray-100 pb-3">
                <div className="flex items-center gap-4">
                  <div className="flex items-center gap-1.5">
                    <span className="w-3.5 h-3.5 rounded-lg bg-gray-50 border border-gray-150" />
                    <span>{zh ? '空闲 (Available)' : 'Available'}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-3.5 h-3.5 rounded-lg bg-emerald-500" />
                    <span>{zh ? '使用中 (Active)' : 'Active'}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="rounded border border-amber-300 px-1 text-[9px] font-bold text-amber-700">GW</span>
                    <span>{zh ? '前缀网关' : 'Prefix gateway'}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-3.5 h-3.5 rounded-lg bg-amber-500" />
                    <span>{zh ? '已保留 (Reserved)' : 'Reserved'}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-3.5 h-3.5 rounded-lg bg-rose-500" />
                    <span>{zh ? '已弃用 (Deprecated)' : 'Deprecated'}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-3.5 h-3.5 rounded-lg bg-slate-200 border border-slate-300" />
                    <span>{zh ? '系统保留 (不可分配)' : 'System reserved'}</span>
                  </div>
                </div>
                <div className="font-semibold text-gray-400">
                  {zh ? '点击已使用 IP 查看定位详情，点击空闲地址进行分配' : 'Click an occupied IP to view locator details, or an available address to allocate it'}
                </div>
              </div>
              
              <div className="flex flex-wrap gap-2">
                {matrixData.map((cell) => {
                  let bgClass = "bg-gray-50 hover:bg-cyan-50 text-gray-400 border-gray-150";
                  if (cell.status === 'system') {
                    bgClass = "bg-slate-200 text-slate-400 border-slate-300 cursor-not-allowed";
                  } else if (cell.status === 'active') {
                    bgClass = "bg-emerald-500 text-white hover:bg-emerald-600 border-emerald-600 shadow-sm";
                  } else if (cell.status === 'reserved') {
                    bgClass = "bg-amber-500 text-white hover:bg-amber-600 border-amber-600 shadow-sm";
                  } else if (cell.status === 'deprecated') {
                    bgClass = "bg-rose-505 text-white hover:bg-rose-600 border-rose-600 shadow-sm";
                  }
                  
                  const lastOctet = cell.ip.split('.').pop() || '';
                  const tooltip = cell.status === 'system'
                    ? `${cell.ip} (${cell.systemReason})`
                    : cell.isGateway
                    ? `${cell.ip} (${zh ? '前缀网关' : 'Prefix gateway'})`
                    : cell.data
                    ? `${cell.ip} (${cell.data.hostname || (zh ? '无域名' : 'No Hostname')}) - ${roleLabel(cell.data.device_type, zh)} [${statusLabel(cell.data.status, zh)}]`
                    : `${cell.ip} (${zh ? '空闲' : 'Available'})`;
                  
                  return (
                    <div
                      key={cell.ip}
                      onClick={() => {
                        if (cell.status === 'system') return;
                        if (cell.isGateway) {
                          navigate(`/ipam/locate?ip=${encodeURIComponent(cell.ip)}`);
                          return;
                        }
                        if (cell.data) {
                          navigate(`/ipam/locate?ip=${encodeURIComponent(cell.ip)}`);
                        } else {
                          openForm({
                            id: '',
                            subnet_id: selectedPrefixId,
                            address: cell.ip,
                            hostname: '',
                            device_id: '',
                            interface_name: '',
                            mac_address: '',
                            device_type: 'host',
                            purpose: inferIpPurpose(activePrefix?.network_type),
                            status: 'active',
                            description: '',
                            last_seen: '',
                            created_at: '',
                            updated_at: '',
                          }, true);
                        }
                      }}
                      title={tooltip}
                      className={`h-14 w-14 rounded-lg border flex flex-col items-center justify-center text-sm font-bold font-mono transition-all duration-150 cursor-pointer active:scale-95 select-none ${bgClass}`}
                    >
                      <span>.{lastOctet}</span>
                      {cell.isGateway && <span className="text-[8px] leading-none font-black tracking-wide">GW</span>}
                    </div>
                  );
                })}
              </div>
            </div>
          ) : (
            <table ref={addressTableRef} style={{ minWidth: 1613, tableLayout: 'fixed' }} className="nx-data-table w-full min-w-[1613px] table-fixed text-left [&_thead_th]:!px-2 [&_thead_th]:!py-2 [&_tbody_td]:!px-2 [&_tbody_td]:!py-2">
              <colgroup>
                <col className="w-[77px]" />
                <col className="w-[97px]" />
                <col className="w-[222px]" />
                <col className="w-[102px]" />
                <col className="w-[92px]" />
                <col className="w-[117px]" />
                <col className="w-[117px]" />
                <col className="w-[127px]" />
                <col className="w-[97px]" />
                <col className="w-[137px]" />
                <col className="w-[102px]" />
                <col className="w-[112px]" />
                <col className="w-[137px]" />
                <col className="w-[77px]" />
              </colgroup>
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/40 text-[10px] font-bold text-gray-400 uppercase tracking-wider select-none">
                  <th className="whitespace-nowrap px-3 py-3">{zh ? '站点' : 'Site'}</th>
                  <th className="whitespace-nowrap px-3 py-3">{zh ? '网段' : 'Prefix'}</th>
                  <th className="whitespace-nowrap px-3 py-3">{zh ? 'IP地址' : 'IP Address'}</th>
                  <th className="whitespace-nowrap px-3 py-3">{zh ? '用途' : 'Purpose'}</th>
                  <th className="whitespace-nowrap px-3 py-3">{zh ? '类型' : 'Role Type'}</th>
                  <th className="whitespace-nowrap px-3 py-3">{zh ? '主机名 / 域名' : 'DNS Hostname'}</th>
                  <th className="whitespace-nowrap px-3 py-3">{zh ? '关联设备' : 'Linked Device'}</th>
                  <th className="whitespace-nowrap px-3 py-3">{zh ? '资产信息' : 'Asset Info'}</th>
                  <th className="whitespace-nowrap px-3 py-3">{zh ? '接口' : 'Interface'}</th>
                  <th className="whitespace-nowrap px-3 py-3">{zh ? 'MAC地址' : 'MAC Address'}</th>
                  <th className="whitespace-nowrap px-3 py-3">{zh ? '状态' : 'Status'}</th>
                  <th className="whitespace-nowrap px-3 py-3">{zh ? '备注描述' : 'Description'}</th>
                  <th className="whitespace-nowrap px-3 py-3">{zh ? '发现时间' : 'Last Seen'}</th>
                  <TableActionHeader className="whitespace-nowrap px-3 py-3 text-right">{zh ? '操作' : 'Actions'}</TableActionHeader>
                </tr>
              </thead>
              <tbody className="whitespace-nowrap">
                {paginatedAddresses.length > 0 ? (
                  paginatedAddresses.map((node) => (
                    <tr 
                      key={node.id} 
                      className="hover:bg-gray-50/50 transition-colors border-b border-gray-100 group"
                    >
                      <td className="px-3 py-3 text-xs font-bold text-cyan-700"><span className="block max-w-[60px] truncate" title={node.site_name || '-'}>{node.site_name || '-'}</span></td>
                      <td className="px-3 py-3 font-mono text-[10px] text-gray-500"><span className="block max-w-[80px] truncate" title={node.subnet_prefix || '-'}>{node.subnet_prefix || '-'}</span></td>
                      <td className="px-3 py-3 font-mono font-bold text-xs text-gray-800">
                        <button
                          type="button"
                          onClick={() => navigate(`/ipam/locate?ip=${encodeURIComponent(node.address)}`)}
                          title={`${node.address} · ${zh ? '点击查看 IP 定位详情' : 'View IP locator details'}`}
                          className="inline-block max-w-[206px] truncate align-bottom whitespace-nowrap text-cyan-700 hover:text-cyan-500 hover:underline transition-colors"
                        >
                          {node.address}
                        </button>
                        <span className={`mt-1 inline-flex rounded-full px-1.5 py-0.5 text-[9px] font-bold ${
                          node.source === 'manual+discovered'
                            ? 'bg-emerald-50 text-emerald-600'
                            : node.source === 'prefix_gateway' || (!node.source && node.is_prefix_gateway)
                            ? 'bg-amber-50 text-amber-700'
                            : node.is_discovered || node.source === 'discovered'
                            ? 'bg-cyan-50 text-cyan-600'
                            : 'bg-slate-50 text-slate-500'
                        }`}>
                          <span className="whitespace-nowrap">{sourceLabel(node, zh)}</span>
                        </span>
                      </td>
                      <td className="px-3 py-3">
                        <span className="inline-flex max-w-[86px] truncate whitespace-nowrap rounded-full border border-cyan-500/10 bg-cyan-50 px-2 py-0.5 text-[10px] font-bold text-cyan-700" title={purposeLabel(node.purpose || inferIpPurpose(node.network_type), zh)}>
                          {purposeLabel(node.purpose || inferIpPurpose(node.network_type), zh)}
                        </span>
                      </td>
                      <td className="px-3 py-3">
                        <span className={`inline-block max-w-[76px] truncate whitespace-nowrap px-2 py-0.5 rounded-full text-[10px] font-bold ${
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
                        }`} title={roleLabel(node.device_type, zh)}>
                          {roleLabel(node.device_type, zh)}
                        </span>
                      </td>
                      <td className="px-3 py-3 text-xs font-semibold text-gray-500"><span className="block max-w-[101px] truncate" title={node.hostname || '-'}>{node.hostname || '-'}</span></td>
                      <td className="px-3 py-3 text-xs font-bold text-cyan-600 hover:underline cursor-pointer"><span className="block max-w-[101px] truncate" title={node.switch_name || node.bound_device_hostname || (node.device_id ? getDeviceName(node.device_id) : '-')}>{node.switch_name || node.bound_device_hostname || (node.device_id ? getDeviceName(node.device_id) : '-')}</span></td>
                      <td className="px-3 py-3 text-xs font-medium text-gray-500"><span className="block max-w-[111px] truncate" title={assetInfoLabel(node, zh)}>{assetInfoLabel(node, zh)}</span></td>
                      <td className="px-3 py-3 text-xs font-semibold text-gray-600"><span className="block max-w-[81px] truncate" title={node.switch_port || node.interface_name || '-'}>{node.switch_port || node.interface_name || '-'}</span></td>
                      <td className="px-3 py-3 font-mono text-xs text-gray-500">{formatMacAddress(node.mac_address) || '-'}</td>
                      <td className="px-3 py-3">
                        <span className={`inline-flex max-w-[86px] items-center gap-1 truncate whitespace-nowrap px-1.5 py-0.5 rounded-full text-[10px] font-bold ${
                          node.status === 'active' 
                            ? 'bg-emerald-50 text-emerald-600 border border-emerald-500/10' 
                            : node.status === 'reserved' 
                            ? 'bg-amber-50 text-amber-600 border border-amber-500/10' 
                            : 'bg-rose-50 text-rose-600 border border-rose-500/10'
                        }`} title={statusLabel(node.status, zh)}>
                          <span className={`w-1 h-1 rounded-full ${
                            node.status === 'active' ? 'bg-emerald-500' : node.status === 'reserved' ? 'bg-amber-500' : 'bg-rose-500'
                          }`} />
                          {statusLabel(node.status, zh)}
                        </span>
                      </td>
                      <td className="px-3 py-3 text-xs font-medium text-gray-400"><span className="block max-w-[96px] truncate" title={node.description || '-'}>{node.description || '-'}</span></td>
                      <td className="px-3 py-3 font-mono text-[10px] text-gray-400">{(node.discovered_last_seen || node.last_seen) ? (node.discovered_last_seen || node.last_seen).replace('T', ' ').slice(0, 19) : '-'}</td>
                      <TableActionCell className="px-3 py-3 text-right">
                        {!node.is_discovered && !node.is_virtual_gateway ? (
                          <ActionIconGroup label={zh ? '地址操作' : 'Address actions'} className="opacity-0 transition-opacity group-hover:opacity-100">
                            <ActionIconButton
                              icon={Pencil}
                              label={zh ? '编辑' : 'Edit'}
                              onClick={() => openForm(node)}
                            />
                            {!node.is_prefix_gateway && <ActionIconButton
                              icon={Trash2}
                              label={zh ? '删除' : 'Delete'}
                              variant="danger"
                              onClick={() => setShowDeleteConfirm(node.id)}
                            />}
                          </ActionIconGroup>
                        ) : <span className="text-[10px] font-semibold text-cyan-500">{node.is_virtual_gateway ? (zh ? '只读前缀配置' : 'Read-only prefix config') : (zh ? '只读采集' : 'Read-only')}</span>}
                      </TableActionCell>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={14} className="py-12 text-center text-xs text-gray-400 font-medium">
                      {zh ? '当前筛选范围暂无 IP 记录' : 'No IP record in the current scope'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination */}
        {!isMatrixView && (
          <div className="px-6 py-4 border-t border-gray-100">
            <Pagination
              currentPage={page}
              totalItems={totalItems}
              itemsPerPage={pageSize}
              onPageChange={setPage}
              onItemsPerPageChange={(size) => { setPageSize(size); setPage(1); }}
              language={language}
              alwaysVisible={true}
            />
          </div>
        )}
      </div>

      {/* Add / Edit Modal */}
      <AnimatePresence>
        {showAddEdit && (
          <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="bg-white w-full max-w-lg rounded-3xl overflow-hidden shadow-2xl border border-black/5 flex flex-col max-h-[90vh]"
            >
              {/* Header */}
              <div className="px-6 py-5 border-b border-gray-100 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-2xl bg-cyan-50 flex items-center justify-center text-cyan-600">
                    <PlusCircle size={20} />
                  </div>
                  <div>
                    <h3 className="font-bold text-gray-900">{editingIP ? (zh ? '编辑IP记录' : 'Edit IP Address') : isQuickAllocation ? (zh ? '快速分配 IP' : 'Quick Allocate IP') : (zh ? '分配IP地址' : 'Allocate IP Address')}</h3>
                    <p className="text-xs text-gray-500 mt-0.5">{isQuickAllocation ? (zh ? '矩阵已选定 IP；填写主机名即可，其他信息可按需补充' : 'The matrix selected the IP. Add a hostname now and other details only if needed.') : (zh ? '填写 IP 和主机名即可；设备、接口等信息按需补充' : 'Enter the IP and hostname; add device and interface details only when needed.')}</p>
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
                    <div>
                      <span className="font-bold text-gray-400">{zh ? '归属前缀网段' : 'Allocating Under Prefix'}</span>
                      {activePrefix?.network_type && (
                        <p className="mt-1 text-[10px] font-semibold text-cyan-700">
                          {zh ? `网段用途：${purposeLabel(inferIpPurpose(activePrefix.network_type), true)}` : `Prefix purpose: ${purposeLabel(inferIpPurpose(activePrefix.network_type), false)}`}
                        </p>
                      )}
                    </div>
                    <div className="text-right">
                      <span className="font-mono font-bold text-cyan-700 bg-cyan-500/10 px-2 py-0.5 rounded-md">
                        {activePrefix ? activePrefix.prefix : ''}
                      </span>
                      {activePrefix?.gateway && (
                        <p className="mt-1 text-[10px] font-semibold text-gray-400">
                          {zh ? `网关：${activePrefix.gateway}` : `Gateway: ${activePrefix.gateway}`}
                        </p>
                      )}
                    </div>
                  </div>

                  {/* IP Purpose */}
                  <div className="space-y-1.5 col-span-2">
                    <div className="flex items-center justify-between">
                      <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? 'IP用途分类' : 'IP Purpose'}</label>
                      <span className="text-[9px] font-semibold text-cyan-600">{zh ? '默认继承网段用途；用途与角色独立' : 'Inherited from prefix; purpose and role are independent'}</span>
                    </div>
                    <select
                      value={form.purpose}
                      onChange={(e) => {
                        const purpose = e.target.value;
                        setForm({ ...form, purpose });
                      }}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    >
                      {IP_PURPOSE_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>{zh ? option.zh : option.en}</option>
                      ))}
                    </select>
                  </div>

                  {/* IP Address */}
                  <div className="space-y-1.5 col-span-2">
                    <div className="flex justify-between items-center">
                      <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? 'IP地址 *' : 'IP Address *'}</label>
                      {!editingIP && !isQuickAllocation && (
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
                      disabled={editingIP !== null || isQuickAllocation}
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

                  {showAdvancedFields && (
                    <>
                  {/* Bound Device (searchable) */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '关联资产 / 设备' : 'Linked Asset / Device'}</label>
                    <DeviceSearchSelect
                      devices={devices}
                      value={form.device_id}
                      onChange={(id) => setForm({ ...form, device_id: id })}
                      zh={zh}
                    />
                    <p className="ml-1 text-[10px] font-medium text-gray-400">
                      {zh ? '资产管理新增的网络设备/服务器会自动出现在这里，保存后通过设备关联回资产。' : 'New network devices and servers from Asset Management appear here automatically.'}
                    </p>
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
                      {STATUS_OPTIONS.filter((opt) => opt.value !== 'available').map((opt) => (
                        <option key={opt.value} value={opt.value}>{zh ? opt.zh : opt.en}</option>
                      ))}
                    </select>
                  </div>

                  {(form.status === 'reserved' || form.purpose === 'temporary') && (
                    <div className="space-y-1.5">
                      <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '预留到期时间（可选）' : 'Reservation expiry (optional)'}</label>
                      <input
                        type="datetime-local"
                        value={form.expires_at}
                        onChange={(e) => setForm({ ...form, expires_at: e.target.value })}
                        className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                      />
                    </div>
                  )}

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
                    </>
                  )}
                </div>

                <button
                  type="button"
                  onClick={() => setShowAdvancedFields((current) => !current)}
                  className="w-full rounded-xl border border-dashed border-gray-200 bg-gray-50 px-3 py-2.5 text-xs font-semibold text-gray-600 hover:border-cyan-200 hover:bg-cyan-50/40 hover:text-cyan-700 transition-colors"
                  aria-expanded={showAdvancedFields}
                >
                  {showAdvancedFields
                    ? (zh ? '收起更多属性' : 'Hide additional fields')
                    : (zh ? '其他信息：关联设备、接口、MAC、角色、状态、到期时间和备注' : 'More details: device, interface, MAC, role, status, expiry and notes')}
                </button>

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
                  {isQuickAllocation ? (zh ? '确认分配' : 'Allocate') : zh ? '确定保存' : 'Save'}
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
