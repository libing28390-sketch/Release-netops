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
  LoaderCircle,
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import PageHero from '../../components/PageHero';
import Pagination from '../../components/Pagination';
import { ActionIconButton, ActionIconGroup } from '../../components/ui/ActionIconButton';
import { TableExportMenu } from '../../components/ui/TableExportMenu';
import { useEscapeClose } from '../../hooks/useEscapeClose';
import { useLocation, useNavigate } from 'react-router-dom';
import { formatMacAddress } from '../../utils/resourceFormatters';
import { buildVisibleIpamExportData, fetchAllIpamExportItems } from './ipamExport';
import { buildIPAddressInventoryQuery } from './ipAddressQuery';
import {
  getIPAddressRegisteredPrefixLabel,
  getIPAddressObservationStatus,
  getIPAddressSourceLabel,
  getIPAddressTimestampPresentation,
  formatIPAddressLocalTime,
} from './ipAddressTablePresentation';
import IpamQuickStartGuide from './IpamQuickStartGuide';
import IPAddressDetailDrawer from './IPAddressDetailDrawer';
import { describeInterfaceLiveness, type InterfaceLiveness } from './interfaceLiveness';

import { TableActionCell, TableActionHeader } from '../../components/ui/TableActionColumn';
interface IPAddress {
  id: string;
  revision: number;
  subnet_id: string;
  address: string;
  hostname: string;
  device_id: string;
  interface_name: string;
  mac_address: string;
  device_type: string;
  purpose?: string;
  /** True when type/purpose were derived from interface name, mask or device management IP. */
  classification_inferred?: boolean;
  /** Observed interface MAC (SNMP IF-MIB or neighbour ARP); never stored in the ledger. */
  interface_mac?: string;
  interface_mac_source?: 'snmp_ifmib' | 'neighbor_arp' | string;
  interface_mac_conflict?: string[];
  /** Liveness of a device interface address, judged by its interface state (not ARP). */
  interface_liveness?: InterfaceLiveness;
  status: string;
  description: string;
  expires_at?: string;
  last_seen: string;
  created_at: string;
  updated_at: string;
  site_id?: string;
  site_name?: string;
  subnet_prefix?: string;
  observed_prefix?: string;
  prefix_match_status?: 'global_default' | 'vrf_unavailable' | 'unmatched' | 'scope_pending' | 'matched';
  interface_admin_status?: string;
  interface_oper_status?: string;
  subnet_name?: string;
  network_type?: string;
  source?: 'manual' | 'manual+discovered' | 'discovered' | 'prefix_gateway' | 'interface_cli';
  source_type?: string;
  has_interface_observation?: boolean;
  is_discovered?: boolean;
  is_prefix_gateway?: boolean;
  is_virtual_gateway?: boolean;
  discovered_last_seen?: string;
  available_after?: string;
  switch_name?: string;
  switch_port?: string;
  observed_switch_name?: string;
  observed_switch_port?: string;
  observed_hostname?: string;
  observed_mac_address?: string;
  observed_source_device_name?: string;
  observed_source_type?: string;
  observed_context_type?: string;
  observed_context_key?: string;
  observed_arp_interface?: string;
  context_type?: string;
  local_context_key?: string;
  scope_status?: string;
  address_space_id?: string;
  vlan?: string;
  observed_vlan?: string;
  observed_switch_id?: string;
  bound_device_hostname?: string;
  linked_asset_id?: string;
  asset_tag?: string;
  asset_serial_number?: string;
  asset_hostname?: string;
  asset_vendor?: string;
  asset_model?: string;
  asset_management_ip?: string;
  asset_business_ip?: string;
  observed_asset_tag?: string;
  observed_asset_serial_number?: string;
  observed_asset_hostname?: string;
  observed_asset_vendor?: string;
  observed_asset_model?: string;
  observed_asset_management_ip?: string;
  observed_asset_business_ip?: string;
}

interface IPAddressPoolOption {
  id: string;
  name: string;
  start_ip: string;
  end_ip: string;
  status: string;
  management_mode: string;
  allocation_allowed: boolean | number;
  mark_populated: boolean | number;
  policy_pending: boolean | number;
}

interface PendingCreateRequest {
  fingerprint: string;
  key: string;
}

const isEnabledFlag = (value: unknown) => value === true || value === 1;
const isDisabledFlag = (value: unknown) => value === false || value === 0;

/** Only explicitly confirmed active local-static pools may be chosen for allocation. */
export function filterAllocatableAddressPools(value: unknown): IPAddressPoolOption[] {
  const rows = Array.isArray(value) ? value : [];
  return rows.filter((item): item is IPAddressPoolOption => {
    if (!item || typeof item !== 'object') return false;
    const pool = item as Partial<IPAddressPoolOption>;
    return Boolean(pool.id)
      && String(pool.status || '').toLowerCase() === 'active'
      && pool.management_mode === 'local_static'
      && isEnabledFlag(pool.allocation_allowed)
      && isDisabledFlag(pool.mark_populated)
      && isDisabledFlag(pool.policy_pending);
  }).map((pool) => ({
    ...pool,
    id: String(pool.id),
    name: String(pool.name || pool.id),
    start_ip: String(pool.start_ip || ''),
    end_ip: String(pool.end_ip || ''),
    status: String(pool.status || ''),
    management_mode: String(pool.management_mode || ''),
  }));
}

export function buildNextAvailableIpUrl(prefixId: string, poolId = ''): string {
  const query = new URLSearchParams();
  if (poolId) query.set('pool_id', poolId);
  const queryString = query.toString();
  const suffix = queryString ? `?${queryString}` : '';
  return `/api/ipam/subnets/${encodeURIComponent(prefixId)}/next-available-ip${suffix}`;
}

type RegisteredAddressEditRequest = Pick<IPAddress, 'id' | 'subnet_id' | 'address'>;

export class RegisteredAddressLookupError extends Error {
  constructor(readonly reason: 'invalid_request' | 'invalid_response' | 'missing' | 'ambiguous' | 'http', readonly status?: number) {
    super(reason);
    this.name = 'RegisteredAddressLookupError';
  }
}

/** Load the persisted IPAM record used by the edit form, never the mixed inventory row. */
export async function fetchRegisteredAddressForEdit(
  row: RegisteredAddressEditRequest,
  options: { headers?: HeadersInit; signal?: AbortSignal; fetcher?: typeof fetch } = {},
): Promise<IPAddress> {
  if (!row.id || !row.subnet_id || !row.address) {
    throw new RegisteredAddressLookupError('invalid_request');
  }

  const query = new URLSearchParams({
    site_id: 'all',
    registered_only: 'true',
    prefix_id: row.subnet_id,
    q: row.address,
    page: '1',
    page_size: '100',
  });
  const response = await (options.fetcher || fetch)(`/api/ipam/addresses?${query.toString()}`, {
    headers: options.headers,
    signal: options.signal,
  });
  if (!response.ok) throw new RegisteredAddressLookupError('http', response.status);

  const payload: unknown = await response.json();
  if (!payload || typeof payload !== 'object' || !Array.isArray((payload as { items?: unknown }).items)) {
    throw new RegisteredAddressLookupError('invalid_response');
  }
  const matches = (payload as { items: unknown[] }).items.filter((item): item is IPAddress => (
    Boolean(item)
    && typeof item === 'object'
    && typeof (item as { id?: unknown }).id === 'string'
    && (item as { id: string }).id === row.id
  ));
  if (matches.length === 0) throw new RegisteredAddressLookupError('missing');
  if (matches.length !== 1) throw new RegisteredAddressLookupError('ambiguous');
  if (!Number.isSafeInteger(matches[0].revision) || matches[0].revision < 1) {
    throw new RegisteredAddressLookupError('invalid_response');
  }
  return matches[0];
}

export function getIPAddressReadOnlyDisplayFields(address: Pick<IPAddress,
  'hostname' | 'observed_hostname' | 'switch_name' | 'observed_switch_name' | 'bound_device_hostname'
  | 'switch_port' | 'observed_switch_port' | 'interface_name' | 'mac_address' | 'observed_mac_address'
>): { hostname: string; switchName: string; switchPort: string; macAddress: string } {
  return {
    hostname: address.hostname || address.observed_hostname || '',
    switchName: address.observed_switch_name || address.switch_name || address.bound_device_hostname || '',
    switchPort: address.observed_switch_port || address.switch_port || address.interface_name || '',
    macAddress: address.mac_address || address.observed_mac_address || '',
  };
}

export function getIPAddressDeviceAssignmentDisplay(address: Pick<IPAddress,
  'device_id' | 'bound_device_hostname' | 'asset_hostname' | 'observed_switch_name' | 'switch_name'
  | 'source' | 'is_discovered'
>, zh: boolean): string {
  const isObservationOnly = address.is_discovered || address.source === 'discovered' || address.source === 'interface_cli';
  const assignedDevice = isObservationOnly
    ? (zh ? '未登记' : 'Unregistered')
    : address.device_id
    ? address.bound_device_hostname || address.asset_hostname || address.device_id
    : (zh ? '未绑定' : 'Unassigned');
  const observedSwitch = address.observed_switch_name || address.switch_name || '';
  if (address.source === 'interface_cli') {
    const sourceDevice = address.bound_device_hostname || observedSwitch || address.device_id || '-';
    return `${zh ? '采集设备' : 'Collected device'}: ${sourceDevice} · ${zh ? 'IPAM 未登记' : 'Not registered in IPAM'}`;
  }
  if (observedSwitch) {
    return `${zh ? '登记' : 'Assigned'}: ${assignedDevice} · ${zh ? '接入' : 'Access'}: ${observedSwitch}`;
  }
  return address.device_id ? assignedDevice : '-';
}

function assetInfoLabel(address: IPAddress, zh: boolean): string {
  const values = [
    address.asset_tag ? `${zh ? '编号' : 'Tag'}: ${address.asset_tag}` : '',
    address.asset_serial_number ? `${zh ? '序列号' : 'Serial'}: ${address.asset_serial_number}` : '',
  ].filter(Boolean);
  return values.join(' · ') || '-';
}

export function observedPrefixScopeLabel(status: IPAddress['prefix_match_status'], zh: boolean): string {
  if (status === 'vrf_unavailable') return zh ? 'VRF 待确认' : 'VRF needs confirmation';
  if (status === 'scope_pending') return zh ? '地址空间待确认' : 'Address space needs confirmation';
  if (status === 'unmatched') return zh ? '未匹配网段' : 'No matching prefix';
  if (status === 'matched') return zh ? '已匹配地址空间内网段' : 'Matching prefix in address space';
  if (status === 'global_default') return zh ? '全局/默认' : 'Global/default';
  return zh ? '地址空间待确认' : 'Address space needs confirmation';
}

export function formatPendingDiscoveryWarning(count: number, zh: boolean): string {
  const pendingCount = Number.isFinite(count) ? Math.max(0, Math.trunc(count)) : 0;
  if (pendingCount === 0) return '';
  return zh
    ? `当前页面中另有 ${pendingCount} 个 VRF 待确认的观测 IP 已临时保留；刷新当前采集数据或确认归属后会重新计算。`
    : `${pendingCount} IP observations currently shown are temporarily reserved while their VRF is unconfirmed. Availability is recalculated after the current data refreshes or scope is confirmed.`;
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

interface IPAddressInventorySummary {
  gateways: number;
  prefixes: number;
  manual: number;
  interface_observed: number;
  discovered: number;
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
  { value: 'interface', zh: '设备接口', en: 'Device Interface' },
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

const inferIpPurpose = (networkType?: string): string => PREFIX_PURPOSE_MAP[String(networkType || '').trim().toLowerCase()] || 'other';

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
        <div className="absolute right-0 z-50 mt-1 max-h-80 w-full min-w-[360px] overflow-auto rounded-xl border border-gray-200 bg-white py-1 shadow-xl">
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

const deviceCandidateFromAddress = (address: IPAddress): DeviceCandidate | null => {
  if (!address.device_id) return null;
  return {
    id: address.device_id,
    hostname: address.bound_device_hostname || address.asset_hostname || undefined,
    ip_address: address.asset_management_ip || address.asset_business_ip || undefined,
    asset_id: address.linked_asset_id,
    asset_tag: address.asset_tag,
    asset_serial_number: address.asset_serial_number,
    asset_hostname: address.asset_hostname,
    asset_vendor: address.asset_vendor,
    asset_model: address.asset_model,
    asset_management_ip: address.asset_management_ip,
    asset_business_ip: address.asset_business_ip,
  };
};

const DeviceSearchSelect: React.FC<{
  value: string;
  onChange: (id: string) => void;
  zh: boolean;
  authHeaders: () => Record<string, string>;
  initialDevice: DeviceCandidate | null;
}> = ({ value, onChange, zh, authHeaders, initialDevice }) => {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [devices, setDevices] = useState<DeviceCandidate[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [retryCount, setRetryCount] = useState(0);
  const [selectedDevice, setSelectedDevice] = useState<DeviceCandidate | null>(initialDevice);
  const wrapRef = useRef<HTMLDivElement>(null);
  const requestRef = useRef<AbortController | null>(null);

  const selected = value
    ? devices.find((device) => device.id === value)
      || (selectedDevice?.id === value ? selectedDevice : null)
      || (initialDevice?.id === value ? initialDevice : null)
      || { id: value }
    : null;
  const selectedIsKnown = Boolean(
    selected && (
      selectedDevice?.id === value
      || initialDevice?.id === value
      || devices.some((device) => device.id === value)
    ),
  );
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

  useEffect(() => {
    if (!value || selectedDevice?.id === value) return;
    const loadedSelection = devices.find((device) => device.id === value);
    if (loadedSelection) setSelectedDevice(loadedSelection);
  }, [devices, selectedDevice?.id, value]);

  useEffect(() => {
    if (!open) return;

    const controller = new AbortController();
    requestRef.current?.abort();
    requestRef.current = controller;
    setLoading(true);
    setLoadError('');
    setDevices([]);

    const timeoutId = window.setTimeout(async () => {
      const params = new URLSearchParams({ mode: 'light', page: '1', page_size: '50' });
      const searchTerm = query.trim();
      if (searchTerm) params.set('search', searchTerm);

      try {
        const response = await fetch(`/api/devices?${params.toString()}`, {
          headers: authHeaders(),
          signal: controller.signal,
        });
        if (controller.signal.aborted || requestRef.current !== controller) return;
        if (!response.ok) {
          setLoadError(response.status === 401
            ? (zh ? '登录已过期，请重新登录后重试。' : 'Your session has expired. Sign in and retry.')
            : response.status === 403
              ? (zh ? '当前账号没有查看设备的权限。' : 'You do not have permission to view devices.')
              : (zh ? '加载设备列表失败，请重试。' : 'Failed to load devices. Please retry.'));
          return;
        }

        const data = await response.json();
        if (controller.signal.aborted || requestRef.current !== controller) return;
        const items = Array.isArray(data) ? data : (Array.isArray(data?.items) ? data.items : []);
        setDevices(items);
      } catch {
        if (controller.signal.aborted || requestRef.current !== controller) return;
        setLoadError(zh ? '加载设备列表失败，请检查网络后重试。' : 'Failed to load devices. Check the connection and retry.');
      } finally {
        if (!controller.signal.aborted && requestRef.current === controller) {
          requestRef.current = null;
          setLoading(false);
        }
      }
    }, 250);

    return () => {
      window.clearTimeout(timeoutId);
      controller.abort();
      if (requestRef.current === controller) requestRef.current = null;
    };
  }, [open, query, retryCount, authHeaders, zh]);

  const hasSelectedDeviceOutsideResults = selectedIsKnown && !devices.some((device) => device.id === value);

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
        className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-200 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
      />
      {open && (
        <div className="absolute z-50 mt-1 w-full max-h-56 overflow-auto bg-white border border-gray-200 rounded-xl shadow-xl py-1">
          <div
            onClick={() => {
              setSelectedDevice(null);
              onChange('');
              setOpen(false);
              setQuery('');
            }}
            className="px-4 py-2 text-xs text-gray-400 hover:bg-gray-50 cursor-pointer"
          >
            {zh ? '— 不绑定设备 —' : '— None —'}
          </div>
          {hasSelectedDeviceOutsideResults && selected && (
            <div className="border-b border-gray-100 px-4 py-2 text-xs text-gray-700">
              <div className="flex items-center justify-between gap-2">
                <div className="truncate font-semibold">{deviceDisplayLabel(selected)}</div>
                <span className="shrink-0 text-[10px] font-bold text-cyan-700">{zh ? '当前已选' : 'Selected'}</span>
              </div>
              <div className="mt-0.5 truncate text-[10px] text-gray-400">
                {selected.ip_address || (zh ? '未填写管理IP' : 'No management IP')}
                {selected.asset_serial_number ? ` · SN ${selected.asset_serial_number}` : ''}
                {!selected.asset_tag && selected.asset_id ? ` · ${zh ? '已关联资产' : 'Linked asset'}` : ''}
              </div>
            </div>
          )}
          {devices.map((d) => (
            <div
              key={d.id}
              onClick={() => {
                setSelectedDevice(d);
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
          {loading && (
            <div className="px-4 py-3 text-xs text-gray-400 text-center">
              {zh ? '正在加载设备...' : 'Loading devices...'}
            </div>
          )}
          {!loading && loadError && (
            <div role="alert" className="px-4 py-3 text-center">
              <div className="text-xs text-rose-600">{loadError}</div>
              <button
                type="button"
                onClick={() => setRetryCount((count) => count + 1)}
                className="mt-2 text-xs font-bold text-cyan-700 hover:text-cyan-800"
              >
                {zh ? '重试' : 'Retry'}
              </button>
            </div>
          )}
          {!loading && !loadError && devices.length === 0 && (
            <div className="px-4 py-3 text-xs text-gray-400 text-center">
              {query.trim()
                ? (zh ? '没有匹配的设备' : 'No matching devices')
                : (zh ? '暂无可关联设备' : 'No devices available')}
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
  const [includeObservations] = useState(params.get('view') === 'sources');

  const [addresses, setAddresses] = useState<IPAddress[]>([]);
  const [prefixes, setPrefixes] = useState<Prefix[]>([]);
  const [sites, setSites] = useState<SiteSummary[]>([]);
  const [inventorySummary, setInventorySummary] = useState<IPAddressInventorySummary>({
    gateways: 0, prefixes: 0, manual: 0, interface_observed: 0, discovered: 0,
  });
  const [loading, setLoading] = useState(true);
  const [inventoryError, setInventoryError] = useState('');
  const inventoryRequest = useRef<AbortController | null>(null);
  const registeredAddressEditRequest = useRef<AbortController | null>(null);
  const poolRequest = useRef<AbortController | null>(null);
  const [isLoadingRegisteredAddress, setIsLoadingRegisteredAddress] = useState(false);
  const [loadingRegisteredAddressId, setLoadingRegisteredAddressId] = useState('');
  const [registeredAddressEditError, setRegisteredAddressEditError] = useState('');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [typeFilter, setTypeFilter] = useState('all');
  const [purposeFilter, setPurposeFilter] = useState('all');
  const [isMatrixView, setIsMatrixView] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [totalItems, setTotalItems] = useState(0);

  // Lookup data
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
  const [detailAddress, setDetailAddress] = useState<IPAddress | null>(null);
  useEscapeClose(showAddEdit, () => { setShowAddEdit(false); setEditingIP(null); });
  useEscapeClose(Boolean(showDeleteConfirm), () => setShowDeleteConfirm(null));

  // Form State
  const [form, setForm] = useState({
    subnet_id: '', // selected prefix ID
    pool_id: '', // optional allocation range; empty means the whole Prefix
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
  const pendingCreateRequest = useRef<PendingCreateRequest | null>(null);
  const [suggestionWarning, setSuggestionWarning] = useState('');
  const [poolOptions, setPoolOptions] = useState<IPAddressPoolOption[]>([]);
  const [isLoadingPools, setIsLoadingPools] = useState(false);
  const [poolLoadError, setPoolLoadError] = useState('');
  const [poolRetryCount, setPoolRetryCount] = useState(0);

  const authHeaders = useCallback(() => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, []);

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

  // Fetch lookups
  const fetchLookups = useCallback(async () => {
    const hdrs = authHeaders();
    try {
      // Fetch Prefixes
      const prefRes = await fetch('/api/ipam/subnets?include_metrics=false', { headers: hdrs });
      if (prefRes.ok) {
        const data = await prefRes.json();
        setPrefixes(data);
        if (prefixIdParam) {
          const matched = data.find((p: Prefix) => p.id === prefixIdParam);
          if (matched) setActivePrefix(matched);
        }
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
      const query = buildIPAddressInventoryQuery({
        includeObservations,
        siteId: selectedSiteId,
        prefixId: selectedPrefixId,
        search,
        statusFilter,
        typeFilter,
        purposeFilter,
        isMatrixView,
      });
      query.set('page_size', String(isMatrixView ? 100 : pageSize));
      const loadedItems: IPAddress[] = [];
      let responseTotal = 0;
      let firstPageData: {
        items?: IPAddress[];
        total?: number;
        has_more?: boolean;
        sites?: SiteSummary[];
        summary?: Partial<IPAddressInventorySummary>;
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
          setInventorySummary({ gateways: 0, prefixes: 0, manual: 0, interface_observed: 0, discovered: 0 });
        }
        return;
      }
      loadSucceeded = true;
      setAddresses(loadedItems);
      setTotalItems(responseTotal);
      if (firstPageData) {
        setSites(firstPageData.sites || []);
        setInventorySummary({
          gateways: Number(firstPageData.summary?.gateways || 0),
          prefixes: Number(firstPageData.summary?.prefixes || 0),
          manual: Number(firstPageData.summary?.manual || 0),
          interface_observed: Number(firstPageData.summary?.interface_observed || 0),
          discovered: Number(firstPageData.summary?.discovered || 0),
        });
      }
    } catch (e) {
      if (controller.signal.aborted) return;
      console.error(e);
      if (!hasLoadedInventory.current) {
        setAddresses([]);
        setTotalItems(0);
        setInventorySummary({ gateways: 0, prefixes: 0, manual: 0, interface_observed: 0, discovered: 0 });
      }
      setInventoryError(zh ? '加载 IP 地址库存失败，请重试。' : 'Failed to load IP inventory. Please retry.');
    } finally {
      if (inventoryRequest.current === controller) {
        inventoryRequest.current = null;
        if (loadSucceeded) hasLoadedInventory.current = true;
        setLoading(false);
      }
    }
  }, [selectedPrefixId, selectedSiteId, search, statusFilter, typeFilter, purposeFilter, page, pageSize, isMatrixView, includeObservations, authHeaders, zh]);

  useEffect(() => {
    fetchLookups();
  }, [fetchLookups]);

  useEffect(() => () => {
    const activeRequest = inventoryRequest.current;
    inventoryRequest.current = null;
    activeRequest?.abort();
    registeredAddressEditRequest.current?.abort();
    registeredAddressEditRequest.current = null;
    poolRequest.current?.abort();
    poolRequest.current = null;
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    poolRequest.current?.abort();
    poolRequest.current = null;
    setPoolOptions([]);
    setPoolLoadError('');
    setIsLoadingPools(false);

    if (!showAddEdit || editingIP || isQuickAllocation || !form.subnet_id) return undefined;

    const controller = new AbortController();
    poolRequest.current = controller;
    setIsLoadingPools(true);
    const query = new URLSearchParams({ prefix_id: form.subnet_id, page: '1', page_size: '100' });

    const failPoolLoad = (message: string) => {
      setPoolOptions([]);
      setPoolLoadError(message);
      setForm((current) => ({ ...current, pool_id: '' }));
    };

    void (async () => {
      try {
        const response = await fetch(`/api/ipam/pools?${query.toString()}`, {
          headers: authHeaders(),
          signal: controller.signal,
        });
        if (controller.signal.aborted || poolRequest.current !== controller) return;
        if (!response.ok) {
          failPoolLoad(response.status === 401
            ? (zh ? '登录已过期，无法加载地址池，请重新登录后重试。' : 'Your session expired. Sign in to load allocation pools.')
            : response.status === 403
              ? (zh ? '当前账号没有查看此网段地址池的权限，已停止池选择。' : 'You do not have permission to view pools for this prefix. Pool selection is unavailable.')
              : (zh ? '加载地址池失败，已停止池选择。请重试。' : 'Failed to load pools. Pool selection is unavailable; retry to continue.'));
          return;
        }

        const payload: unknown = await response.json();
        if (controller.signal.aborted || poolRequest.current !== controller) return;
        const root = payload && typeof payload === 'object' && 'data' in payload
          ? (payload as { data?: unknown }).data
          : payload;
        const rows = Array.isArray(root)
          ? root
          : root && typeof root === 'object' && Array.isArray((root as { items?: unknown }).items)
            ? (root as { items: unknown[] }).items
            : null;
        if (!rows) {
          failPoolLoad(zh ? '地址池响应无效，已停止池选择。' : 'The pool response was invalid. Pool selection is unavailable.');
          return;
        }
        const eligible = filterAllocatableAddressPools(rows);
        setPoolOptions(eligible);
        setPoolLoadError('');
        setForm((current) => current.pool_id && eligible.some((pool) => pool.id === current.pool_id)
          ? current
          : { ...current, pool_id: '' });
      } catch (error) {
        if (controller.signal.aborted || poolRequest.current !== controller) return;
        console.error(error);
        failPoolLoad(zh ? '加载地址池失败，已停止池选择。请检查网络后重试。' : 'Failed to load pools. Pool selection is unavailable; check the connection and retry.');
      } finally {
        if (poolRequest.current === controller) {
          poolRequest.current = null;
          setIsLoadingPools(false);
        }
      }
    })();

    return () => {
      controller.abort();
      if (poolRequest.current === controller) poolRequest.current = null;
    };
  }, [authHeaders, editingIP, form.subnet_id, isQuickAllocation, poolRetryCount, showAddEdit, zh]);

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
    if (!editingIP) {
      setForm((current) => ({ ...current, subnet_id: id, pool_id: '', address: '' }));
      setPoolOptions([]);
      setPoolLoadError('');
      setSuggestionWarning('');
      setErrorMsg('');
    }
    navigate(`/ipam/ips?prefix_id=${id}`);
  };

  const handleSiteChange = (id: string) => {
    setSelectedSiteId(id);
    setSelectedPrefixId('');
    setActivePrefix(null);
    setPage(1);
    if (!editingIP) {
      setForm((current) => ({ ...current, subnet_id: '', pool_id: '', address: '' }));
      setPoolOptions([]);
      setPoolLoadError('');
      setSuggestionWarning('');
      setErrorMsg('');
    }
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
      setForm((current) => ({ ...current, subnet_id: target.id, pool_id: '', address: '' }));
      setPoolOptions([]);
      setPoolLoadError('');
      setSuggestionWarning('');
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
    const params = buildIPAddressInventoryQuery({
      includeObservations,
      siteId: selectedSiteId,
      prefixId: selectedPrefixId,
      search,
      statusFilter,
      typeFilter,
      purposeFilter,
      isMatrixView,
    });
    const allAddresses = await fetchAllIpamExportItems<IPAddress>('/api/ipam/addresses', params);
    const linkedDeviceName = (node: IPAddress) => getIPAddressDeviceAssignmentDisplay(node, zh);
    return buildVisibleIpamExportData(addressTableRef.current, [
      { header: zh ? '站点' : 'Site', value: (node) => node.site_name || '-' },
      {
        header: zh ? 'IPAM登记网段 / CIDR' : 'IPAM Registered Prefix / CIDR',
        value: (node) => {
          const registeredPrefix = node.subnet_prefix || (zh ? '未关联网段' : 'No linked prefix');
          return node.source === 'interface_cli' && node.observed_prefix
            ? `${registeredPrefix} · ${zh ? '接口观察' : 'Observed'} ${node.observed_prefix} · ${observedPrefixScopeLabel(node.prefix_match_status, zh)}`
            : registeredPrefix;
        },
      },
      { header: zh ? 'IP地址' : 'IP Address', value: (node) => node.address },
      { header: zh ? '用途' : 'Purpose', value: (node) => purposeLabel(node.purpose || inferIpPurpose(node.network_type), zh) },
      { header: zh ? '类型' : 'Role Type', value: (node) => roleLabel(node.device_type, zh) },
      { header: zh ? '主机名 / 域名' : 'DNS Hostname', value: (node) => getIPAddressReadOnlyDisplayFields(node).hostname || '-' },
      { header: zh ? 'IPAM分配对象 / 接入交换机' : 'IPAM Assignment / Access Switch', value: linkedDeviceName },
      { header: zh ? '资产编号' : 'Asset Tag', value: (node) => node.asset_tag || '-' },
      { header: zh ? '资产序列号' : 'Asset Serial', value: (node) => node.asset_serial_number || '-' },
      { header: zh ? '接口' : 'Interface', value: (node) => getIPAddressReadOnlyDisplayFields(node).switchPort || '-' },
      { header: zh ? 'MAC地址' : 'MAC Address', value: (node) => formatMacAddress(getIPAddressReadOnlyDisplayFields(node).macAddress) || '-' },
      { header: zh ? '状态' : 'Status', value: (node) => statusLabel(node.status, zh) },
      { header: zh ? '备注描述' : 'Description', value: (node) => node.description || '-' },
      {
        header: zh ? '最近发现 / 采集 / 更新时间' : 'Last Discovered / Collected / Updated',
        value: (node) => {
          const timestamp = getIPAddressTimestampPresentation(node, zh);
          return timestamp.value ? `${timestamp.label}: ${timestamp.value}` : timestamp.label;
        },
      },
    ], allAddresses);
  }, [selectedSiteId, selectedPrefixId, search, statusFilter, isMatrixView, includeObservations, typeFilter, purposeFilter, zh]);

  // Form handling
  const openForm = async (ipItem: IPAddress | null = null, quickAllocation = false) => {
    pendingCreateRequest.current = null;
    registeredAddressEditRequest.current?.abort();
    registeredAddressEditRequest.current = null;
    setIsLoadingRegisteredAddress(false);
    setLoadingRegisteredAddressId('');
    setRegisteredAddressEditError('');
    setErrorMsg('');
    setSuggestionWarning('');
    setIsQuickAllocation(quickAllocation && !ipItem?.id);
    setShowAdvancedFields(Boolean(ipItem?.id));
    setShowAddEdit(false);
    setEditingIP(null);
    if (ipItem?.id) {
      const controller = new AbortController();
      registeredAddressEditRequest.current = controller;
      setIsLoadingRegisteredAddress(true);
      setLoadingRegisteredAddressId(ipItem.id);
      try {
        const registeredRecord = await fetchRegisteredAddressForEdit(ipItem, {
          headers: authHeaders(),
          signal: controller.signal,
        });
        if (registeredAddressEditRequest.current !== controller) return;
        const inheritedPurpose = inferIpPurpose(registeredRecord.network_type || activePrefix?.network_type);
        setEditingIP(registeredRecord);
        setIsQuickAllocation(false);
        setShowAdvancedFields(true);
        setForm({
          subnet_id: registeredRecord.subnet_id || selectedPrefixId,
          pool_id: '',
          address: registeredRecord.address,
          hostname: registeredRecord.hostname || '',
          device_id: registeredRecord.device_id || '',
          interface_name: registeredRecord.interface_name || '',
          mac_address: registeredRecord.mac_address || '',
          device_type: registeredRecord.device_type || defaultRoleForPurpose(inheritedPurpose),
          purpose: registeredRecord.purpose || inheritedPurpose,
          status: registeredRecord.status || 'active',
          description: registeredRecord.description || '',
          expires_at: registeredRecord.expires_at || '',
        });
        setShowAddEdit(true);
      } catch (error) {
        if (controller.signal.aborted || registeredAddressEditRequest.current !== controller) return;
        const reason = error instanceof RegisteredAddressLookupError ? error.reason : '';
        const status = error instanceof RegisteredAddressLookupError ? error.status : undefined;
        setRegisteredAddressEditError(status === 401
          ? (zh ? '登录已过期，无法读取登记记录，请重新登录后重试。' : 'Your session expired. Sign in and retry loading the registered record.')
          : status === 403
            ? (zh ? '当前账号没有读取此 IP 登记记录的权限。' : 'You do not have permission to read this registered IP record.')
            : reason === 'missing'
              ? (zh ? '该 IP 登记记录已不存在或已变更，请刷新清单后重试。' : 'The registered IP record is missing or has changed. Refresh the inventory and retry.')
              : reason === 'ambiguous'
                ? (zh ? '无法唯一确认该 IP 登记记录，请刷新清单后重试。' : 'The registered IP record could not be uniquely identified. Refresh the inventory and retry.')
                : (zh ? '无法加载 IP 登记记录，编辑已停止。请刷新清单后重试。' : 'Failed to load the registered IP record. Editing was stopped; refresh the inventory and retry.'));
      } finally {
        if (registeredAddressEditRequest.current === controller) {
          registeredAddressEditRequest.current = null;
          setIsLoadingRegisteredAddress(false);
          setLoadingRegisteredAddressId('');
        }
      }
      return;
    }

    const inheritedPurpose = inferIpPurpose(ipItem?.network_type || activePrefix?.network_type);
    setEditingIP(null);
    setForm({
      subnet_id: ipItem?.subnet_id || selectedPrefixId,
      pool_id: '',
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
    setShowAddEdit(true);
  };

  const handleGetSuggestedIP = async () => {
    setErrorMsg('');
    setSuggestionWarning('');
    if (!form.subnet_id) {
      setErrorMsg(zh ? '请先选择一个归属前缀网段' : 'Please select an allocating prefix first');
      return;
    }
    try {
      const res = await fetch(buildNextAvailableIpUrl(form.subnet_id, form.pool_id), { headers: authHeaders() });
      if (res.ok) {
        const data = await res.json();
        setForm((prev) => ({ ...prev, address: data.next_available_ip || '' }));
        setSuggestionWarning(formatPendingDiscoveryWarning(
          Number(data.pending_discovery_count || 0), zh,
        ));
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
      const { pool_id, ...addressFields } = form;
      const payload = editingIP
        ? { ...addressFields, expected_revision: editingIP.revision }
        : !isQuickAllocation && pool_id
          ? { ...addressFields, pool_id }
          : addressFields;
      const res = await fetch(url, {
        method,
        headers: {
          'Content-Type': 'application/json',
          ...authHeaders(),
          ...(!editingIP ? { 'Idempotency-Key': getCreateIdempotencyKey(payload) } : {}),
        },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        if (!editingIP) pendingCreateRequest.current = null;
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
    const address = addresses.find((item) => item.id === id);
    if (!address) return;
    try {
      const res = await fetch(`/api/ipam/addresses/${encodeURIComponent(id)}/release`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ expected_revision: address.revision }),
      });
      if (res.ok) {
        setShowDeleteConfirm(null);
        loadData();
      }
    } catch (e) {
      console.error(e);
    }
  };

  // Use the linked-device summary returned with the IP address.
  const getDeviceName = (address: IPAddress) => {
    return getIPAddressDeviceAssignmentDisplay(address, zh);
  };

  return (
    <div className="flex-1 flex min-w-0 flex-col h-full overflow-hidden px-4 py-4 lg:px-6 lg:py-5 space-y-4">
      <PageHero
        icon={MapPin}
        title={zh ? 'IP 地址管理' : 'IP Address Management'}
        subtitle={zh ? '按站点与网段查看、分配及维护 IP 台账，支持自动推荐可用地址。' : 'View, allocate, and manage IP inventory by site and prefix.'}
        actions={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => navigate('/ipam/endpoints')}
              className="rounded-xl border border-cyan-200/80 dark:border-cyan-900/60 bg-cyan-50/70 dark:bg-cyan-950/40 px-3 py-2 text-xs font-semibold text-cyan-700 dark:text-cyan-300 hover:bg-cyan-100/80 transition-colors cursor-pointer"
            >
              {zh ? '发现终端' : 'Discovered Endpoints'}
            </button>
            <button
              onClick={() => openForm(null)}
              disabled={!selectedPrefixId}
              title={!selectedPrefixId ? (zh ? '请先在右侧“网段”下拉框中选择一个网段，再分配 IP' : 'Select a prefix first, then allocate an IP') : undefined}
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
                <span className="shrink-0 text-xs font-bold uppercase tracking-wider text-[var(--ui-fg-muted)]">{zh ? '站点' : 'Site'}</span>
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
                <span className="shrink-0 text-xs font-bold uppercase tracking-wider text-[var(--ui-fg-muted)]">{zh ? '网段' : 'Prefix'}</span>
                <div className="min-w-0 flex-1">
                  <PrefixSearchSelect
                    prefixes={siteScopedPrefixes}
                    value={selectedPrefixId}
                    onChange={handlePrefixChange}
                    zh={zh}
                  />
                </div>
              </div>

              <div className="flex min-h-9 flex-wrap items-center gap-2 text-[10px] text-[var(--ui-fg-muted)] sm:col-span-2 xl:col-span-1 xl:justify-end">
                <span className="rounded-full bg-cyan-50 px-2.5 py-1 font-bold text-cyan-600">{zh ? `IPAM登记地址 ${loading ? '—' : inventorySummary.manual}` : `${loading ? '—' : inventorySummary.manual} registered IPs`}</span>
                {inventorySummary.interface_observed > 0 && <span className="rounded-full bg-violet-50 px-2.5 py-1 font-bold text-violet-700">{zh ? `接口观察 ${inventorySummary.interface_observed}` : `${inventorySummary.interface_observed} interface observations`}</span>}
                {inventorySummary.discovered > 0 && <span className="rounded-full bg-blue-50 px-2.5 py-1 font-bold text-blue-700">{zh ? `终端发现 ${inventorySummary.discovered}` : `${inventorySummary.discovered} discovered`}</span>}
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
                className="w-full min-w-0 rounded-xl border border-slate-200/80 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-3 py-2 text-xs font-semibold text-slate-700 dark:text-zinc-200 outline-none transition-all focus:border-cyan-500"
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
                className="w-full min-w-0 rounded-xl border border-slate-200/80 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-3 py-2 text-xs font-semibold text-slate-700 dark:text-zinc-200 outline-none transition-all focus:border-cyan-500"
              >
                <option value="all">{zh ? '所有用途' : 'All Purposes'}</option>
                {IP_PURPOSE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{zh ? o.zh : o.en}</option>
                ))}
              </select>

              {/* Search Input */}
              <div className="relative min-w-0">
                <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  type="search"
                  value={search}
                  onChange={(e) => { setSearch(e.target.value); setPage(1); }}
                  aria-label={zh ? '搜索 IP、主机名、接口' : 'Search IP, hostname, or interface'}
                  placeholder={zh ? '搜索 IP、主机名、接口...' : 'Search IP, hostname...'}
                  className="w-full min-w-0 rounded-xl border border-slate-200/80 dark:border-zinc-700 bg-slate-50/70 dark:bg-zinc-800/80 py-2 pl-10 pr-4 text-xs font-medium text-slate-800 dark:text-zinc-100 placeholder:text-slate-400 outline-none transition-all focus:border-cyan-500 focus:bg-white dark:focus:bg-zinc-800"
                />
              </div>

              {/* View Switcher Toggle */}
              <div className="flex w-fit items-center justify-self-start rounded-xl border border-slate-200/80 dark:border-zinc-700 bg-slate-100/80 dark:bg-zinc-800 p-0.5 sm:col-span-2 xl:col-span-1 xl:justify-self-end">
                <button
                  onClick={() => { setPage(1); setIsMatrixView(false); }}
                  className={`px-3 py-1 text-[11px] font-bold rounded-lg transition-all cursor-pointer ${
                    !isMatrixView
                      ? 'bg-white dark:bg-zinc-700 shadow-xs text-cyan-600 dark:text-cyan-300'
                      : 'text-slate-500 dark:text-zinc-400 hover:text-slate-800 dark:hover:text-zinc-200'
                  }`}
                >
                  {zh ? '列表' : 'List'}
                </button>
                <button
                  disabled={!matrixPrefixCandidate}
                  onClick={handleMatrixClick}
                  title={!matrixPrefixCandidate ? (zh ? '当前站点没有可用的 IPv4 /24 - /30 网段' : 'No IPv4 /24-/30 prefix is available for the current site') : (zh ? '矩阵按单个网段展示' : 'Matrix view is scoped to one prefix')}
                  className={`px-3 py-1 text-[11px] font-bold rounded-lg transition-all ${
                    isMatrixView
                      ? 'bg-white dark:bg-zinc-700 shadow-xs text-cyan-600 dark:text-cyan-300 cursor-pointer'
                      : !matrixPrefixCandidate
                      ? 'text-slate-300 dark:text-zinc-600 cursor-not-allowed opacity-50'
                      : 'text-slate-500 dark:text-zinc-400 hover:text-slate-800 dark:hover:text-zinc-200 cursor-pointer'
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
        <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-rose-200 dark:border-rose-900/60 bg-rose-50 dark:bg-rose-950/40 px-4 py-2 text-xs font-semibold text-rose-700 dark:text-rose-300">
          <span>{inventoryError}</span>
          <button type="button" onClick={loadData} className="rounded-lg bg-white dark:bg-zinc-800 px-3 py-1.5 text-rose-700 dark:text-rose-300 shadow-2xs hover:bg-rose-100 dark:hover:bg-zinc-700 cursor-pointer">
            {zh ? '重试' : 'Retry'}
          </button>
        </div>
      )}

      {isLoadingRegisteredAddress && (
        <div role="status" className="rounded-xl border border-cyan-200 dark:border-cyan-900/60 bg-cyan-50 dark:bg-cyan-950/40 px-4 py-2 text-xs font-semibold text-cyan-800 dark:text-cyan-300">
          {zh ? '正在读取正式 IP 登记记录…' : 'Loading the registered IP record…'}
        </div>
      )}
      {registeredAddressEditError && (
        <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-rose-200 dark:border-rose-900/60 bg-rose-50 dark:bg-rose-950/40 px-4 py-2 text-xs font-semibold text-rose-700 dark:text-rose-300">
          <span>{registeredAddressEditError}</span>
          <button type="button" onClick={() => setRegisteredAddressEditError('')} className="rounded-lg bg-white dark:bg-zinc-800 px-3 py-1.5 text-rose-700 dark:text-rose-300 shadow-2xs hover:bg-rose-100 dark:hover:bg-zinc-700 cursor-pointer">
            {zh ? '关闭' : 'Dismiss'}
          </button>
        </div>
      )}

      <IpamQuickStartGuide
        zh={zh}
        loading={loading}
        prefixCount={inventorySummary.prefixes}
        addressCount={inventorySummary.manual || totalItems}
      />

      {/* Main Table Card */}
      <div className="flex-1 min-h-0 min-w-0 bg-white dark:bg-zinc-900/95 rounded-2xl border border-slate-200/80 dark:border-zinc-800 shadow-xs overflow-hidden flex flex-col">
        <div className="flex-1 min-h-0 min-w-0 overflow-auto">
          {loading ? (
            <div className="h-full flex items-center justify-center text-xs text-slate-400 font-semibold">
              {zh ? '加载中...' : 'Loading IP allocations...'}
            </div>
          ) : isMatrixView && canUseMatrix ? (
            /* Render Grid Matrix View */
            <div className="p-6 overflow-auto">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-4 text-xs text-slate-500 dark:text-zinc-400 border-b border-slate-100 dark:border-zinc-800 pb-3">
                <div className="flex flex-wrap items-center gap-4">
                  <div className="flex items-center gap-1.5">
                    <span className="w-3.5 h-3.5 rounded-lg bg-slate-50 dark:bg-zinc-800 border border-slate-200 dark:border-zinc-700" />
                    <span>{zh ? '空闲 (Available)' : 'Available'}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-3.5 h-3.5 rounded-lg bg-emerald-500" />
                    <span>{zh ? '使用中 (Active)' : 'Active'}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="rounded border border-amber-300 px-1 text-[9px] font-bold text-amber-700 dark:text-amber-300">GW</span>
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
                    <span className="w-3.5 h-3.5 rounded-lg bg-slate-200 dark:bg-zinc-700 border border-slate-300 dark:border-zinc-600" />
                    <span>{zh ? '系统保留 (不可分配)' : 'System reserved'}</span>
                  </div>
                </div>
                <div className="font-semibold text-slate-400 dark:text-zinc-500">
                  {zh ? '点击已使用 IP 查看定位详情，点击空闲地址进行分配' : 'Click an occupied IP to view locator details, or an available address to allocate it'}
                </div>
              </div>
              
              <div className="flex flex-wrap gap-2">
                {matrixData.map((cell) => {
                  let bgClass = "bg-slate-50 dark:bg-zinc-800/70 hover:bg-cyan-50 dark:hover:bg-cyan-950/50 text-slate-500 dark:text-zinc-400 border-slate-200 dark:border-zinc-700";
                  if (cell.status === 'system') {
                    bgClass = "bg-slate-200 dark:bg-zinc-700 text-slate-400 dark:text-zinc-500 border-slate-300 dark:border-zinc-600 cursor-not-allowed";
                  } else if (cell.status === 'active') {
                    bgClass = "bg-emerald-500 text-white hover:bg-emerald-600 border-emerald-600 shadow-xs";
                  } else if (cell.status === 'reserved') {
                    bgClass = "bg-amber-500 text-white hover:bg-amber-600 border-amber-600 shadow-xs";
                  } else if (cell.status === 'deprecated') {
                    bgClass = "bg-rose-500 text-white hover:bg-rose-600 border-rose-600 shadow-xs";
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
                          if (cell.data.id) setDetailAddress(cell.data);
                          else navigate(`/ipam/locate?ip=${encodeURIComponent(cell.ip)}`);
                        } else {
                          openForm({
                            id: '',
                            revision: 0,
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
            <table ref={addressTableRef} style={{ minWidth: 2227, tableLayout: 'fixed' }} className="nx-data-table w-full min-w-[2227px] table-fixed text-left [&_thead_th]:!px-2 [&_thead_th]:!py-2 [&_tbody_td]:!px-2 [&_tbody_td]:!py-2">
              <colgroup>
                <col style={{ width: 170 }} />
                <col style={{ width: 260 }} />
                <col style={{ width: 250 }} />
                <col style={{ width: 110 }} />
                <col style={{ width: 250 }} />
                <col style={{ width: 105 }} />
                <col style={{ width: 105 }} />
                <col style={{ width: 145 }} />
                <col style={{ width: 155 }} />
                <col style={{ width: 150 }} />
                <col style={{ width: 110 }} />
                <col style={{ width: 135 }} />
                <col style={{ width: 170 }} />
                <col style={{ width: 112 }} />
              </colgroup>
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/40 text-[10px] font-bold text-[var(--ui-fg-muted)] uppercase tracking-wider select-none">
                  <th className="sticky top-0 z-20 whitespace-nowrap bg-[var(--ui-surface-muted)] px-3 py-3 xl:sticky xl:left-0 xl:z-30">{zh ? '站点' : 'Site'}</th>
                  <th className="sticky top-0 z-20 whitespace-nowrap bg-[var(--ui-surface-muted)] px-3 py-3 xl:sticky xl:left-[170px] xl:z-30">{zh ? 'IPAM登记网段 / CIDR' : 'IPAM Registered Prefix / CIDR'}</th>
                  <th className="sticky top-0 z-20 whitespace-nowrap bg-[var(--ui-surface-muted)] px-3 py-3 xl:sticky xl:left-[430px] xl:z-30">{zh ? 'IP地址' : 'IP Address'}</th>
                  <th className="sticky top-0 z-10 whitespace-nowrap bg-[var(--ui-surface-muted)] px-3 py-3">{zh ? '状态' : 'Status'}</th>
                  <th className="sticky top-0 z-10 whitespace-nowrap bg-[var(--ui-surface-muted)] px-3 py-3">{zh ? '最近发现 / 采集 / 更新时间' : 'Last Discovered / Collected / Updated'}</th>
                  <th className="sticky top-0 z-10 whitespace-nowrap bg-[var(--ui-surface-muted)] px-3 py-3">{zh ? '用途' : 'Purpose'}</th>
                  <th className="sticky top-0 z-10 whitespace-nowrap bg-[var(--ui-surface-muted)] px-3 py-3">{zh ? '类型' : 'Role Type'}</th>
                  <th className="sticky top-0 z-10 whitespace-nowrap bg-[var(--ui-surface-muted)] px-3 py-3">{zh ? '主机名 / 域名' : 'DNS Hostname'}</th>
                  <th className="sticky top-0 z-10 whitespace-nowrap bg-[var(--ui-surface-muted)] px-3 py-3">{zh ? '关联设备' : 'Linked Device'}</th>
                  <th className="sticky top-0 z-10 whitespace-nowrap bg-[var(--ui-surface-muted)] px-3 py-3">{zh ? '资产信息' : 'Asset Info'}</th>
                  <th className="sticky top-0 z-10 whitespace-nowrap bg-[var(--ui-surface-muted)] px-3 py-3">{zh ? '接口' : 'Interface'}</th>
                  <th className="sticky top-0 z-10 whitespace-nowrap bg-[var(--ui-surface-muted)] px-3 py-3">{zh ? 'MAC地址' : 'MAC Address'}</th>
                  <th className="sticky top-0 z-10 whitespace-nowrap bg-[var(--ui-surface-muted)] px-3 py-3">{zh ? '备注描述' : 'Description'}</th>
                  <TableActionHeader className="sticky top-0 z-10 whitespace-nowrap bg-[var(--ui-surface-muted)] px-3 py-3 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <span>{zh ? '操作' : 'Actions'}</span>
                      <TableExportMenu tableRef={addressTableRef} exportData={exportData} filename="ipam-addresses" language={zh ? 'zh' : 'en'} disabled={paginatedAddresses.length === 0} />
                    </div>
                  </TableActionHeader>
                </tr>
              </thead>
              <tbody>
                {paginatedAddresses.length > 0 ? (
                  paginatedAddresses.map((node) => (
                    <tr 
                      key={node.id} 
                      className="hover:bg-gray-50/50 transition-colors border-b border-gray-100 group"
                    >
                      <td className="bg-[var(--ui-surface)] px-3 py-3 text-xs font-bold text-cyan-700 group-hover:bg-[var(--ui-surface-muted)] xl:sticky xl:left-0 xl:z-20"><span className="block whitespace-normal break-words" title={node.site_name || '-'}>{node.site_name || '-'}</span></td>
                      <td className="bg-[var(--ui-surface)] px-3 py-3 text-gray-600 group-hover:bg-[var(--ui-surface-muted)] xl:sticky xl:z-20" style={{ left: 170 }}>
                        <span className="font-mono text-[10px] text-gray-700">{getIPAddressRegisteredPrefixLabel(node.subnet_prefix, zh)}</span>
                        {node.source === 'interface_cli' && node.observed_prefix && (
                          <span className="mt-1 block break-all font-mono text-[9px] font-semibold text-[var(--ui-fg-muted)]" title={zh ? '接口观察网段来自采集的 IP 和掩码；与 IPAM 正式网段的归属需按地址空间核对' : 'The observed prefix comes from the collected IP and mask; IPAM prefix association is checked within its address space'}>
                            {zh
                              ? `接口观察 ${node.observed_prefix} · ${observedPrefixScopeLabel(node.prefix_match_status, zh)}`
                              : `Observed ${node.observed_prefix} · ${observedPrefixScopeLabel(node.prefix_match_status, zh)}`}
                          </span>
                        )}
                      </td>
                      <td className="bg-[var(--ui-surface)] px-3 py-3 font-mono font-bold text-xs text-gray-800 group-hover:bg-[var(--ui-surface-muted)] xl:sticky xl:z-20" style={{ left: 430 }}>
                        <button
                          type="button"
                          onClick={() => {
                            if (node.id && !node.is_discovered && !node.is_virtual_gateway) {
                              setDetailAddress(node);
                            } else {
                              navigate(`/ipam/locate?ip=${encodeURIComponent(node.address)}`);
                            }
                          }}
                          title={node.id && !node.is_discovered && !node.is_virtual_gateway
                            ? `${node.address} · ${zh ? '点击查看详情（归属、设备接口、发现记录、变更历史）' : 'Open detail'}`
                            : `${node.address} · ${zh ? '点击在“IP 定位”中查询该地址所在交换机端口' : 'Locate this address on the switch port'}`}
                          className="block max-w-full whitespace-normal break-all text-left text-cyan-700 hover:text-cyan-500 hover:underline transition-colors"
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
                          <span className="whitespace-nowrap">{getIPAddressSourceLabel(node, zh)}</span>
                        </span>
                        {(includeObservations && (node.is_discovered || node.source === 'manual+discovered')) && <details className="mt-1 max-w-xs text-[10px] font-normal text-[var(--ui-fg-muted)]">
                          <summary className="cursor-pointer">{zh ? '查看来源依据' : 'Source evidence'}</summary>
                          <dl className="mt-1 space-y-1 whitespace-normal break-words">
                            <div><dt className="inline">{zh ? '来源设备：' : 'Source device: '}</dt><dd className="inline">{node.observed_source_device_name || node.bound_device_hostname || node.switch_name || (zh ? '未提供' : 'Not provided')}</dd></div>
                            <div><dt className="inline">{zh ? '来源：' : 'Source: '}</dt><dd className="inline">{node.source === 'interface_cli' ? (zh ? '接口采集' : 'Interface collection') : node.observed_source_type?.toUpperCase() || (zh ? '发现缓存' : 'Discovery cache')}</dd></div>
                            <div><dt className="inline">{zh ? '设备上下文：' : 'Device context: '}</dt><dd className="inline">{node.local_context_key || node.observed_context_key || (zh ? '未提供，不能据此认定 Global' : 'Not provided; Global is unconfirmed')}</dd></div>
                            <div><dt className="inline">{zh ? '地址空间：' : 'Address space: '}</dt><dd className="inline">{node.address_space_id ? (zh ? '已确认' : 'Confirmed') : (zh ? '待确认' : 'Pending confirmation')}</dd></div>
                            {node.observed_arp_interface && <div>{zh ? 'ARP 来源接口：' : 'ARP source interface: '}{node.observed_arp_interface}</div>}
                          </dl>
                        </details>}
                      </td>
                      <td className="px-3 py-3">
                        {getIPAddressObservationStatus(node, zh) ? (
                          <span className={`inline-flex max-w-[120px] truncate whitespace-nowrap rounded-full border px-1.5 py-0.5 text-[10px] font-bold ${
                            getIPAddressObservationStatus(node, zh)?.tone === 'success'
                              ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                              : getIPAddressObservationStatus(node, zh)?.tone === 'warning'
                                ? 'border-amber-200 bg-amber-50 text-amber-800'
                                : 'border-[var(--ui-border)] bg-[var(--ui-surface-muted)] text-[var(--ui-fg-muted)]'
                          }`} title={zh ? '采集快照状态；不代表终端当前在线' : 'Collected snapshot; does not prove current endpoint availability'}>
                            {getIPAddressObservationStatus(node, zh)?.label}
                          </span>
                        ) : <span className={`inline-flex max-w-[96px] items-center gap-1 truncate whitespace-nowrap px-1.5 py-0.5 rounded-full text-[10px] font-bold ${
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
                        </span>}
                        {(() => {
                          const badge = describeInterfaceLiveness(node.interface_liveness, zh);
                          if (!badge) return null;
                          const tone = badge.tone === 'current'
                            ? 'text-emerald-700'
                            : badge.tone === 'stale' ? 'text-[var(--ui-fg-muted)]' : 'text-rose-700';
                          return (
                            <span
                              data-testid="ip-interface-liveness"
                              data-tone={badge.tone}
                              className={`mt-1 block whitespace-nowrap text-[9px] font-semibold ${tone}`}
                              title={badge.title}
                            >
                              {badge.label}{badge.ageText ? ` · ${badge.ageText}` : ''}
                            </span>
                          );
                        })()}
                      </td>
                      <td className="px-3 py-3">
                        {(() => {
                          const timestamp = getIPAddressTimestampPresentation(node, zh);
                          return timestamp.kind === 'missing' ? (
                            <span className="text-[10px] font-medium text-[var(--ui-fg-muted)]">{timestamp.label}</span>
                          ) : (
                            <div className="flex min-w-0 flex-col gap-0.5">
                              <span className="text-[9px] font-semibold text-[var(--ui-fg-muted)]">{timestamp.label}</span>
                              <time className="break-all font-mono text-[10px] leading-4 text-[var(--ui-fg)]" dateTime={timestamp.value.replace(' ', 'T')} title={zh ? `原始时间：${timestamp.value}` : `Raw: ${timestamp.value}`}>{formatIPAddressLocalTime(timestamp.value)}</time>
                            </div>
                          );
                        })()}
                      </td>
                      <td className="px-3 py-3">
                        <span className="inline-flex max-w-[92px] truncate whitespace-nowrap rounded-full border border-cyan-500/10 bg-cyan-50 px-2 py-0.5 text-[10px] font-bold text-cyan-700" title={node.classification_inferred ? (zh ? `${purposeLabel(node.purpose || inferIpPurpose(node.network_type), zh)}（系统根据接口名、掩码或设备管理 IP 推断，编辑后即固定）` : `${purposeLabel(node.purpose || inferIpPurpose(node.network_type), zh)} (inferred from interface name, mask or device management IP; edit to confirm)`) : purposeLabel(node.purpose || inferIpPurpose(node.network_type), zh)}>
                          {purposeLabel(node.purpose || inferIpPurpose(node.network_type), zh)}
                        </span>
                        {node.classification_inferred && (
                          <span className="ml-1 align-middle text-[9px] font-semibold text-[var(--ui-fg-muted)]">{zh ? '推断' : 'inferred'}</span>
                        )}
                      </td>
                      <td className="px-3 py-3">
                        <span className={`inline-block max-w-[92px] truncate whitespace-nowrap px-2 py-0.5 rounded-full text-[10px] font-bold ${
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
                      <td className="px-3 py-3 text-xs font-semibold text-[var(--ui-fg)]">{(() => {
                        const hostname = getIPAddressReadOnlyDisplayFields(node).hostname || '';
                        const sameAsDevice = Boolean(hostname) && hostname === getDeviceName(node);
                        return sameAsDevice
                          ? <span className="block max-w-[130px] truncate text-[10px] font-medium text-[var(--ui-fg-muted)]" title={hostname}>{zh ? '同关联设备' : 'Same as device'}</span>
                          : <span className="block max-w-[130px] truncate" title={hostname || '-'}>{hostname || '-'}</span>;
                      })()}</td>
                      <td className="px-3 py-3 text-xs font-bold text-[var(--ui-accent)] hover:underline cursor-pointer"><span className="block max-w-[140px] truncate" title={getDeviceName(node)}>{getDeviceName(node)}</span></td>
                      <td className="px-3 py-3 text-xs font-medium text-[var(--ui-fg-muted)]"><span className="block max-w-[135px] truncate" title={assetInfoLabel(node, zh)}>{assetInfoLabel(node, zh)}</span></td>
                      <td className="px-3 py-3 text-xs font-semibold text-[var(--ui-fg)]"><span className="block max-w-[100px] truncate" title={getIPAddressReadOnlyDisplayFields(node).switchPort || '-'}>{getIPAddressReadOnlyDisplayFields(node).switchPort || '-'}</span></td>
                      <td className="px-3 py-3 font-mono text-xs text-[var(--ui-fg)]">{(() => {
                        const stored = formatMacAddress(getIPAddressReadOnlyDisplayFields(node).macAddress);
                        if (stored) return stored;
                        if (node.interface_mac) {
                          const sourceLabel = node.interface_mac_source === 'snmp_ifmib'
                            ? (zh ? 'SNMP 接口表' : 'SNMP IF-MIB')
                            : (zh ? '邻居 ARP' : 'Neighbor ARP');
                          return (
                            <span title={zh ? `采集值（来源：${sourceLabel}），未写入台账` : `Observed (${sourceLabel}); not stored`}>
                              {formatMacAddress(node.interface_mac)}
                              <span className="ml-1 font-sans text-[9px] font-semibold text-[var(--ui-fg-muted)]">{sourceLabel}</span>
                            </span>
                          );
                        }
                        if (node.interface_mac_conflict && node.interface_mac_conflict.length > 1) {
                          return <span className="font-sans text-[10px] font-semibold text-amber-700" title={node.interface_mac_conflict.map((mac) => formatMacAddress(mac)).join(', ')}>{zh ? `多个 MAC（${node.interface_mac_conflict.length}）` : `${node.interface_mac_conflict.length} MACs`}</span>;
                        }
                        return '-';
                      })()}</td>
                      <td className="px-3 py-3 text-xs font-medium text-[var(--ui-fg-muted)]"><span className="block max-w-[150px] truncate" title={node.description || '-'}>{node.description || '-'}</span></td>
                      <TableActionCell className="px-3 py-3 text-right">
                        {!node.is_discovered && !node.is_virtual_gateway ? (
                          <ActionIconGroup label={zh ? '地址操作' : 'Address actions'} className="opacity-0 transition-opacity group-hover:opacity-100">
                            <ActionIconButton
                              icon={loadingRegisteredAddressId === node.id ? LoaderCircle : Pencil}
                              iconClassName={loadingRegisteredAddressId === node.id ? 'animate-spin' : undefined}
                              label={loadingRegisteredAddressId === node.id ? (zh ? '正在读取登记记录' : 'Loading registered record') : (zh ? '编辑' : 'Edit')}
                              disabled={loadingRegisteredAddressId === node.id}
                              onClick={() => openForm(node)}
                            />
                            {!node.is_prefix_gateway && <ActionIconButton
                              icon={Trash2}
                              label={zh ? '删除' : 'Delete'}
                              variant="danger"
                              onClick={() => setShowDeleteConfirm(node.id)}
                            />}
                          </ActionIconGroup>
                        ) : <span className="text-[10px] font-semibold text-[var(--ui-accent)]">{node.is_virtual_gateway ? (zh ? '只读前缀配置' : 'Read-only prefix config') : (zh ? '只读采集' : 'Read-only')}</span>}
                      </TableActionCell>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={14} className="py-12 text-center text-xs text-[var(--ui-fg-muted)] font-medium">
                      <div className="flex flex-col items-center gap-2">
                        <span>{zh ? '当前筛选范围暂无已登记的 IP 记录' : 'No registered IP record in the current scope'}</span>
                        <span className="text-[11px] font-normal text-slate-400">
                          {zh
                            ? '网络自动采集的终端展示在「发现终端」中，确认所属网络后可登记到本台账。'
                            : 'Network-discovered endpoints appear under Discovered Endpoints and can be registered here once confirmed.'}
                        </span>
                        <button
                          type="button"
                          onClick={() => navigate('/ipam/endpoints')}
                          className="mt-1 inline-flex items-center gap-1 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-[11px] font-semibold text-blue-700 hover:bg-blue-100 transition-colors"
                        >
                          {zh ? '前往「发现终端」查看与登记' : 'Go to Discovered Endpoints'}
                        </button>
                      </div>
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

      <IPAddressDetailDrawer
        zh={zh}
        seed={detailAddress}
        authHeaders={authHeaders}
        onClose={() => setDetailAddress(null)}
        onDataChanged={() => { void loadData(); }}
        onEdit={() => {
          const target = detailAddress;
          setDetailAddress(null);
          if (target) void openForm(target);
        }}
        statusLabel={statusLabel}
        purposeLabel={purposeLabel}
        roleLabel={roleLabel}
      />

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
                {suggestionWarning && (
                  <div className="p-3.5 rounded-2xl bg-amber-50 border border-amber-200 text-xs font-semibold text-amber-800">
                    {suggestionWarning}
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

                  {!editingIP && !isQuickAllocation && (
                    <div className="space-y-1.5 col-span-2">
                      <label htmlFor="ip-address-pool" className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">
                        {zh ? '分配范围' : 'Allocation Range'}
                      </label>
                      <select
                        id="ip-address-pool"
                        aria-label={zh ? '分配范围' : 'Allocation Range'}
                        value={form.pool_id}
                        disabled={isLoadingPools || Boolean(poolLoadError)}
                        onChange={(e) => {
                          setForm((current) => ({ ...current, pool_id: e.target.value, address: '' }));
                          setSuggestionWarning('');
                          setErrorMsg('');
                        }}
                        className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-200 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        <option value="">{zh ? '整个 Prefix（按当前策略计算）' : 'Entire Prefix (apply current range policies)'}</option>
                        {poolOptions.map((pool) => (
                          <option key={pool.id} value={pool.id}>
                            {pool.name} · {pool.start_ip} – {pool.end_ip}
                          </option>
                        ))}
                      </select>
                      {isLoadingPools && (
                        <div role="status" className="ml-1 text-[10px] text-gray-500">
                          {zh ? '正在加载此网段的可分配地址池…' : 'Loading eligible pools for this prefix…'}
                        </div>
                      )}
                      {poolLoadError && (
                        <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 px-3.5 py-2.5 text-[10px] font-semibold text-rose-700">
                          <span>{poolLoadError}</span>
                          <button type="button" onClick={() => setPoolRetryCount((count) => count + 1)} className="shrink-0 rounded-lg bg-white px-2.5 py-1.5 text-rose-700 shadow-sm hover:bg-rose-100">
                            {zh ? '重试' : 'Retry'}
                          </button>
                        </div>
                      )}
                      {!isLoadingPools && !poolLoadError && poolOptions.length === 0 && (
                        <p className="ml-1 text-[10px] text-gray-500">
                          {zh ? '没有符合本地分配策略的地址池；仍可使用整个 Prefix 的可用地址。' : 'No pool is eligible for local allocation. You can still allocate within the Prefix according to its range policies.'}
                        </p>
                      )}
                      {form.pool_id && poolOptions.find((pool) => pool.id === form.pool_id) && (
                        <p className="ml-1 text-[10px] text-cyan-700">
                          {zh ? `推荐和提交都会限制在 ${poolOptions.find((pool) => pool.id === form.pool_id)?.name} 范围内。` : `Suggestions and submission will both be bounded to ${poolOptions.find((pool) => pool.id === form.pool_id)?.name}.`}
                        </p>
                      )}
                    </div>
                  )}

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
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-200 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
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
                      onChange={(e) => {
                        setForm({ ...form, address: e.target.value });
                        setSuggestionWarning('');
                      }}
                      placeholder="e.g. 10.1.1.10"
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-200 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
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
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-200 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                  </div>

                  {showAdvancedFields && (
                    <>
                  {/* Bound Device (searchable) */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '关联资产 / 设备' : 'Linked Asset / Device'}</label>
                    <DeviceSearchSelect
                      value={form.device_id}
                      onChange={(id) => setForm({ ...form, device_id: id })}
                      zh={zh}
                      authHeaders={authHeaders}
                      initialDevice={editingIP?.device_id === form.device_id ? deviceCandidateFromAddress(editingIP) : null}
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
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-200 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
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
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-200 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                  </div>

                  {/* Device Type Select */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? 'IP 角色类型' : 'Role Type'}</label>
                    <select
                      value={form.device_type}
                      onChange={(e) => setForm({ ...form, device_type: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-200 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
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
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-200 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
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
                        className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-200 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
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
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-200 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50 resize-none"
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
              <div className="px-6 py-3.5 bg-gray-50 border-t border-gray-200 flex items-center justify-between gap-3 flex-shrink-0">
                <div className="min-w-0 flex-1">
                  {errorMsg && (
                    <p role="alert" className="text-xs font-semibold text-rose-600 truncate" title={errorMsg}>
                      {errorMsg}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-2.5">
                  <button
                    onClick={() => setShowAddEdit(false)}
                    className="px-4 py-2 text-xs font-bold text-gray-600 hover:bg-gray-200/70 rounded-lg transition-all"
                  >
                    {zh ? '取消' : 'Cancel'}
                  </button>
                  <button
                    onClick={handleSave}
                    className="px-5 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-600 hover:to-blue-700 text-white text-xs font-bold rounded-lg shadow-sm transition-all active:scale-95"
                  >
                    {isQuickAllocation ? (zh ? '确认分配' : 'Allocate') : zh ? '确定保存' : 'Save'}
                  </button>
                </div>
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
