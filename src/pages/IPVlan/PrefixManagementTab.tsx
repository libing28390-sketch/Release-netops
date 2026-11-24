import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  Network,
  Plus,
  Trash2,
  Search,
  Pencil,
  TableProperties,
  GitBranch,
  X,
  PlusCircle,
  Eye,
  Info,
  RefreshCw,
  Check,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  MoreHorizontal,
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { useVirtualizer } from '@tanstack/react-virtual';
import PageHero from '../../components/PageHero';
import Pagination from '../../components/Pagination';
import { ActionButton, ActionIconGroup } from '../../components/ui/ActionIconButton';
import { TableExportMenu } from '../../components/ui/TableExportMenu';
import { buildVisibleIpamExportData, fetchAllIpamExportItems } from './ipamExport';
import { useEscapeClose } from '../../hooks/useEscapeClose';
import { DEFAULT_TENANT_ID } from '../../types/cmdb';
import { Link, useNavigate } from 'react-router-dom';
import { isValidIPv4, isValidIPv6, toNum } from './helpers';
import IPPoolTab from './IPPoolTab';
import {
  buildGatewayCandidateQuery,
  getAutomaticGatewayBinding,
  getGatewayScopePendingMessage,
  isValidGatewayCandidatePrefix,
  type GatewayBindingSource,
  type GatewayCandidateEndpoint,
  type GatewayCandidateResponse,
} from './prefixGatewayBinding';
import { areAllVisiblePrefixIdsSelected, toggleVisiblePrefixSelection } from './prefixManagementSelection';
import {
  canUsePrefixTreeView,
  buildPrefixClassificationSummaryQuery,
  buildPrefixListQuery,
  togglePrefixClassificationFilter,
  type PrefixClassificationCategory,
  type PrefixClassificationFilter,
} from './prefixClassificationFilters';

import { TableActionCell, TableActionHeader } from '../../components/ui/TableActionColumn';
import InterfaceImportReview, { type InterfaceImportRequest } from './InterfaceImportReview';
interface Prefix {
  id: string;
  revision: number;
  prefix: string;
  network: string;
  prefix_len: number;
  vrf_id: string | null;
  vrf_name: string | null;
  address_space_id?: string | null;
  address_space_name?: string | null;
  address_space_kind?: 'global' | 'vrf' | null;
  scope_status?: 'resolved' | 'scope_pending' | string;
  vlan_id: number | null;
  vlan_name: string | null;
  site_id: string | null;
  site_name: string | null;
  site_code: string | null;
  tenant_id: string | null;
  tenant_name: string | null;
  status: string;
  name: string;
  gateway: string;
  description: string;
  total_ips: number;
  used_ips: number;
  registered_ips?: number;
  reserved_ips?: number;
  allocatable_free_ips?: number;
  effective_used_ips?: number;
  effective_utilization?: number;
  container_child_ips?: number;
  container_utilization?: number;
  active_ips: number;
  active_arp_ips?: number;
  active_interface_ips?: number;
  utilization: number;
  network_type: string;
  classification_status?: string;
  classification_confidence?: number;
  manual_override?: number;
  /** Read-only purpose suggestion for unclassified prefixes (never stored until applied). */
  suggested_network_type?: string;
  suggestion_reason?: 'device_management_ip' | 'loopback_interface' | 'point_to_point_mask' | string;
  mixed_network?: number;
  conflict_status?: string;
  cross_site_reuse?: boolean | number;
  address_roles_json?: string;
  last_seen_at?: string;
  is_active?: number;
  gateway_device_id: string | null;
  gateway_device_name: string | null;
  gateway_interface_id: string | null;
  traceable: number;
  created_at?: string;
  updated_at?: string;
  children?: Prefix[];
}

interface AddressSpace {
  id: string;
  name: string;
  kind: 'global' | 'vrf';
  vrf_id: string | null;
  vrf_name: string | null;
  security_tenant_id: string;
  status: string;
  revision: number;
}

interface AddressSpaceResolutionPreview {
  expected_updated_at: string;
  source_space?: AddressSpace;
  target_space?: AddressSpace;
  impact?: {
    ip_addresses?: number;
    pools?: number;
    pools_to_map?: number;
    vips?: number;
    leases?: number;
    conflicting_active_addresses?: number;
  };
  blockers?: Array<string | { message?: string; code?: string }>;
  can_confirm: boolean;
}

type AddressSpaceBlocker = string | {
  message?: string;
  code?: string;
  network?: string;
  duplicate_count?: number;
  sites?: string[];
};

interface AddressSpaceBatchResolutionItem {
  prefix_id: string;
  prefix: string;
  site_name?: string;
  current_address_space_id?: string | null;
  current_vrf_id?: string | null;
  expected_updated_at: string;
  expected_revision: number;
  impact?: AddressSpaceResolutionPreview['impact'];
  blockers?: AddressSpaceBlocker[];
  can_confirm: boolean;
}

interface AddressSpaceBatchResolutionPreview {
  address_space_id: string;
  target_space?: AddressSpace;
  expected_target_revision?: number | null;
  selected_count: number;
  can_confirm: boolean;
  items: AddressSpaceBatchResolutionItem[];
  totals?: AddressSpaceResolutionPreview['impact'];
  blockers?: Array<{ prefix_id?: string; prefix?: string; message?: string; code?: string }>;
}

interface PendingCreateRequest {
  fingerprint: string;
  key: string;
}

const getPendingRequestKey = (
  pendingRequest: { current: PendingCreateRequest | null },
  payload: unknown,
): string => {
  const fingerprint = JSON.stringify(payload);
  if (!pendingRequest.current || pendingRequest.current.fingerprint !== fingerprint) {
    pendingRequest.current = {
      fingerprint,
      key: globalThis.crypto?.randomUUID?.() || `ipam-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    };
  }
  return pendingRequest.current.key;
};

const findPrefixInTree = (items: Prefix[], id: string): Prefix | undefined => {
  for (const item of items) {
    if (item.id === id) return item;
    const child = item.children ? findPrefixInTree(item.children, id) : undefined;
    if (child) return child;
  }
  return undefined;
};

interface PrefixManagementTabProps {
  language: string;
  t: (key: string) => string;
}

interface InterfacePrefixCandidate {
  candidate_id: string;
  prefix: string;
  tenant_id: string;
  site_id: string | null;
  vrf_id: string | null;
  address_space_id?: string | null;
  status: 'existing' | 'to_create' | 'scope_pending';
  vrf_scope_pending?: boolean;
  scope_review_reason?: string;
  interface_count: number;
  ip_count: number;
  interfaces: Array<{
    interface_id: string | null;
    source_ref?: string;
    device_id: string;
    device_name: string;
    device_ip?: string;
    interface_name: string;
    address: string;
  }>;
}

type InterfaceCandidateFilter = 'to_create' | 'existing' | 'scope_pending' | 'all';

const DEFAULT_NEW_PREFIX_NETWORK_TYPE = 'unclassified';

function prefixAddressSpaceLabel(prefix: Prefix, zh: boolean): string {
  const ownership = prefixNetworkOwnership(prefix, zh);
  return [ownership.label, ownership.detail].filter(Boolean).join(' · ');
}

interface PrefixNetworkOwnership {
  label: string;
  detail?: string;
  unconfirmed: boolean;
}

function prefixNetworkOwnership(prefix: Prefix, zh: boolean): PrefixNetworkOwnership {
  if (prefix.scope_status === 'scope_pending' || !prefix.address_space_id) {
    return { label: zh ? '网络归属未确认' : 'Network ownership unconfirmed', unconfirmed: true };
  }

  const addressSpaceName = prefix.address_space_name?.trim() || '';
  if (prefix.address_space_kind === 'global') {
    const genericGlobalNames = new Set(['global', 'global address space', '全局', '全局地址空间']);
    return {
      label: zh ? '全局（无 VRF）' : 'Global (no VRF)',
      detail: addressSpaceName && !genericGlobalNames.has(addressSpaceName.toLowerCase())
        ? addressSpaceName
        : undefined,
      unconfirmed: false,
    };
  }

  if (prefix.address_space_kind === 'vrf') {
    const vrfName = prefix.vrf_name?.trim() || prefix.vrf_id?.trim() || '';
    const label = vrfName ? `${zh ? 'VRF' : 'VRF'} ${vrfName}` : addressSpaceName || 'VRF';
    return {
      label,
      detail: addressSpaceName && addressSpaceName !== label && addressSpaceName !== vrfName ? addressSpaceName : undefined,
      unconfirmed: false,
    };
  }

  return {
    label: addressSpaceName || prefix.address_space_id,
    unconfirmed: false,
  };
}

function PrefixNetworkOwnershipCell({ prefix, zh }: { prefix: Prefix; zh: boolean }) {
  const ownership = prefixNetworkOwnership(prefix, zh);
  return (
    <span className={`block ${ownership.unconfirmed ? 'text-amber-700' : 'text-gray-700'}`}>
      <span>{ownership.label}</span>
      {ownership.detail && <span className="mt-0.5 block text-[10px] font-normal text-gray-500">{ownership.detail}</span>}
    </span>
  );
}

interface PrefixRowActionsProps {
  prefix: Prefix;
  zh: boolean;
  onEdit: () => void;
  onResolveOwnership: () => void;
  onMoveOwnership: () => void;
  onManagePools: () => void;
  onDelete: () => void;
}

function PrefixRowActions({
  prefix,
  zh,
  onEdit,
  onResolveOwnership,
  onMoveOwnership,
  onManagePools,
  onDelete,
}: PrefixRowActionsProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuId = React.useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const hasConfirmedOwnership = Boolean(prefix.address_space_id) && prefix.scope_status !== 'scope_pending';
  const closeMenu = useCallback(() => {
    setMenuOpen(false);
    triggerRef.current?.focus();
  }, []);

  useEscapeClose(menuOpen, closeMenu);
  useEffect(() => {
    if (!menuOpen) return;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (event.target instanceof Node && !rootRef.current?.contains(event.target)) setMenuOpen(false);
    };
    document.addEventListener('pointerdown', closeOnOutsidePointer);
    return () => document.removeEventListener('pointerdown', closeOnOutsidePointer);
  }, [menuOpen]);
  useEffect(() => {
    if (!menuOpen) return;
    menuRef.current?.querySelector<HTMLElement>('a[href], button')?.focus();
  }, [menuOpen]);

  const runMenuAction = (action: () => void) => {
    setMenuOpen(false);
    action();
  };

  return (
    <div ref={rootRef} className="relative inline-flex items-center gap-1 whitespace-nowrap text-[11px]">
      <Link
        to={`/ipam/ips?prefix_id=${encodeURIComponent(prefix.id)}`}
        className="inline-flex items-center rounded-lg border border-cyan-200 bg-cyan-50/70 px-2 py-1.5 font-semibold text-cyan-800 hover:bg-cyan-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500"
        title={zh ? `查看 ${prefix.prefix} 下的 IP` : `View IPs in ${prefix.prefix}`}
      >
        {zh ? '查看 IP' : 'IPs'}
      </Link>
      <button
        type="button"
        onClick={onEdit}
        className="inline-flex items-center rounded-lg border border-gray-200 bg-white px-2 py-1.5 font-semibold text-gray-700 hover:border-cyan-200 hover:bg-cyan-50 hover:text-cyan-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500"
        title={zh ? `编辑 ${prefix.prefix}` : `Edit ${prefix.prefix}`}
      >
        {zh ? '编辑' : 'Edit'}
      </button>
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="true"
        aria-expanded={menuOpen}
        aria-controls={menuId}
        aria-label={zh ? `管理 ${prefix.prefix}` : `Manage ${prefix.prefix}`}
        onClick={() => setMenuOpen((current) => !current)}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown' && !menuOpen) {
            event.preventDefault();
            setMenuOpen(true);
          }
        }}
        className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-2 py-1.5 font-bold text-gray-600 hover:border-cyan-200 hover:bg-cyan-50 hover:text-cyan-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500"
      >
        <span>{zh ? '更多' : 'More'}</span>
        <MoreHorizontal size={14} aria-hidden="true" />
      </button>
      {menuOpen && (
        <div
          ref={menuRef}
          id={menuId}
          className="absolute right-0 top-full z-40 mt-1 min-w-40 rounded-lg border border-gray-200 bg-white p-1 text-left shadow-lg"
        >
          <Link
            to={`/ipam/ips?prefix_id=${encodeURIComponent(prefix.id)}`}
            onClick={() => setMenuOpen(false)}
            className="block w-full rounded-md px-3 py-2 text-left text-[11px] font-semibold text-cyan-800 hover:bg-cyan-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500"
          >
            {zh ? '管理 IP' : 'Manage IPs'}
          </Link>
          <button type="button" onClick={() => runMenuAction(onEdit)} className="block w-full rounded-md px-3 py-2 text-left text-[11px] font-semibold text-gray-700 hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500">
            {zh ? '编辑网段（用途、网关等）' : 'Edit prefix (purpose, gateway, etc.)'}
          </button>
          <button type="button" onClick={() => runMenuAction(hasConfirmedOwnership ? onMoveOwnership : onResolveOwnership)} className="block w-full rounded-md px-3 py-2 text-left text-[11px] font-semibold text-gray-700 hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500">
            {hasConfirmedOwnership ? (zh ? '迁移网络归属' : 'Move network ownership') : (zh ? '确认网络归属' : 'Confirm network ownership')}
          </button>
          <button type="button" onClick={() => runMenuAction(onManagePools)} className="block w-full rounded-md px-3 py-2 text-left text-[11px] font-semibold text-gray-700 hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500">
            {zh ? '管理地址池' : 'Manage address pools'}
          </button>
          <button type="button" onClick={() => runMenuAction(onDelete)} className="block w-full rounded-md px-3 py-2 text-left text-[11px] font-semibold text-rose-700 hover:bg-rose-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-500">
            {zh ? '删除' : 'Delete'}
          </button>
        </div>
      )}
    </div>
  );
}

function extractVlanIdFromInterfaceName(interfaceName?: string | null): number | null {
  const raw = String(interfaceName || '').trim();
  if (!raw) return null;
  const svi = raw.match(/^(?:vlan-?interface|vlanif|vlan|vl)[\s\-_]*(\d+)$/i);
  if (svi) return Number(svi[1]);
  const sub = raw.match(/\.(\d+)$/);
  if (sub) return Number(sub[1]);
  return null;
}

function addressSpaceOptionLabel(space: AddressSpace, zh: boolean): string {
  if (space.kind === 'vrf') {
    const vrfName = space.vrf_name || space.vrf_id || space.name;
    const spaceName = space.name && space.name !== vrfName ? ` · ${space.name}` : '';
    return `${zh ? 'VRF：' : 'VRF: '}${vrfName}${spaceName}`;
  }
  const genericGlobalNames = new Set(['global', 'global address space', '全局', '全局地址空间']);
  const spaceName = space.name && !genericGlobalNames.has(space.name.toLowerCase()) ? ` · ${space.name}` : '';
  return `${zh ? '全局（无 VRF）' : 'Global (no VRF)'}${spaceName}`;
}

function addressSpaceBlockerLabel(
  blocker: AddressSpaceBlocker,
  zh: boolean,
): string {
  if (typeof blocker === 'string') return blocker;
  const message = blocker.message || blocker.code || (zh ? '存在未解决冲突' : 'An unresolved conflict exists');
  if (!zh) return message;
  if (blocker.code === 'duplicate_prefix_cidr_in_batch' && blocker.network) {
    const siteDetails = blocker.sites?.length ? `涉及站点：${blocker.sites.join('、')}。` : '';
    const count = Number(blocker.duplicate_count || 2);
    return `本批次选中的 ${count} 条记录使用了相同 CIDR：${blocker.network}。${siteDetails}同一地址空间不能重复登记。请核实：若是重复记录，取消多余项或先整理数据；若为不同路由域的合法复用，请分开映射到各自的地址空间。`;
  }
  const labels: Record<string, string> = {
    duplicate_active_ip: '目标地址空间中已存在一个或多个相同的活跃 IP 地址。',
    duplicate_active_ip_in_batch: '所选网段之间存在重复的活跃 IP 地址。',
    duplicate_prefix_cidr: '目标地址空间中已存在相同的 CIDR 网段。',
    duplicate_prefix_cidr_in_batch: '本批次包含多个相同 CIDR 的网段，请先处理重复记录。',
    invalid_prefix: '网段 CIDR 无效。',
    pool_range_invalid: '地址池范围无效或超出所属网段。',
    pool_range_overlap: '地址池范围与目标地址空间内的其他地址池重叠。',
    pool_range_overlap_in_batch: '本批次中多个地址池范围重叠。',
    pool_scope_inconsistent: '地址池与所属网段的地址空间不一致。',
    pool_tenant_mismatch: '地址池与所属网段的安全租户不一致。',
    prefix_already_mapped: '该网段已归属地址空间；此批量操作只处理待归属网段。',
    prefix_tenant_unknown: '网段的安全租户未确认。',
    target_pool_range_invalid: '目标地址空间中存在无效的地址池范围。',
    target_pool_scope_inconsistent: '目标地址空间中存在归属不一致的地址池。',
    target_pool_tenant_mismatch: '目标地址空间中存在租户不一致的地址池。',
    target_space_inactive: '目标地址空间未启用。',
    target_space_unavailable: '目标地址空间不存在或不属于该网段的安全租户。',
    vrf_mismatch: '目标地址空间与网段当前 VRF 不一致。',
  };
  return labels[blocker.code || ''] || message;
}

interface InterfaceCandidateSummary {
  candidate_count: number;
  existing_count: number;
  to_create_count: number;
  interface_count: number;
  vrf_pending_count: number;
  skipped_count: number;
}

interface InterfaceCandidatePage {
  page: number;
  page_size: number;
  filtered_count: number;
  total_pages: number;
}

interface PrefixClassificationSummary {
  total: number;
  auto_count: number;
  manual_count: number;
  unclassified_count: number;
  mixed_count: number;
  conflict_count: number;
  reuse_count?: number;
  address_space_pending_count?: number;
  pending_duplicate_group_count?: number;
  pending_duplicate_record_count?: number;
  stale_count: number;
}

function formatPrefixTimestamp(value: string | undefined, language: string): string {
  const raw = String(value || '').trim();
  if (!raw) return '—';
  const date = new Date(raw);
  return Number.isNaN(date.getTime())
    ? raw
    : date.toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US', { hour12: false });
}

function parseAddressRoles(value: string | undefined): Array<{ address_role?: string }> {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed.filter((item) => item && typeof item === 'object') : [];
  } catch {
    return [];
  }
}

function prefixStatusLabel(status: string, zh: boolean): string {
  const labels: Record<string, { zh: string; en: string }> = {
    container: { zh: '容器', en: 'Container' },
    active: { zh: '使用中', en: 'Active' },
    reserved: { zh: '已保留', en: 'Reserved' },
    deprecated: { zh: '已弃用', en: 'Deprecated' },
  };
  const label = labels[status];
  return label ? (zh ? label.zh : label.en) : status;
}

function gatewayCandidateEndpointLabel(endpoint: GatewayCandidateEndpoint, zh: boolean): string {
  return [
    endpoint.device_name || endpoint.device_id || (zh ? '未知设备' : 'Unknown device'),
    endpoint.interface_name,
    endpoint.address || endpoint.ip_address,
  ].filter(Boolean).join(' · ');
}

function gatewayCandidateStatusMessage(
  response: GatewayCandidateResponse,
  source: GatewayBindingSource,
  zh: boolean,
): string {
  if (response.status === 'matched') {
    return source === 'manual'
      ? (zh ? `发现唯一候选 ${response.selected ? gatewayCandidateEndpointLabel(response.selected, zh) : ''}；已保留当前人工设备选择。` : `Unique candidate found${response.selected ? `: ${gatewayCandidateEndpointLabel(response.selected, zh)}` : ''}; the manual device selection is preserved.`)
      : (zh ? `已按唯一证据自动关联：${response.selected ? gatewayCandidateEndpointLabel(response.selected, zh) : '设备'}` : `Automatically bound from unique evidence: ${response.selected ? gatewayCandidateEndpointLabel(response.selected, zh) : 'device'}`);
  }
  if (response.status === 'needs_site') return zh ? '请先选择物理站点，再匹配网关候选。' : 'Choose a physical site to match gateway candidates.';
  if (response.status === 'scope_pending') return getGatewayScopePendingMessage(source, zh);
  if (response.status === 'ambiguous' || response.status === 'no_unique_gateway') {
    if (source === 'manual') return response.status === 'ambiguous'
      ? (zh ? '多个接口与网关 IP 完全匹配，无法唯一选择；已保留人工设备选择。' : 'Multiple interfaces exactly match this gateway IP; the manual device selection is preserved.')
      : (zh ? '发现多个接口端点，没有唯一网关证据；已保留人工设备选择。' : 'Multiple interface endpoints have no unique gateway evidence; the manual device selection is preserved.');
    return response.status === 'ambiguous'
      ? (zh ? '多个接口与网关 IP 完全匹配，无法唯一选择；当前未自动关联。' : 'Multiple interfaces exactly match this gateway IP; no automatic binding was selected.')
      : (zh ? '发现多个接口端点，没有唯一网关证据；当前未绑定网关。' : 'Multiple interface endpoints have no unique gateway evidence; no gateway is bound.');
  }

  if (response.endpoints.length > 0 && response.endpoints.some((endpoint) => endpoint.scope_status !== 'resolved')) {
    return source === 'manual'
      ? (zh ? '发现接口候选，但它们的 VRF / 全局归属尚未映射到当前地址空间；已保留人工设备选择。' : 'Interface candidates exist, but their VRF / Global scope is not mapped to this address space; the manual device choice is preserved.')
      : (zh ? '发现接口候选，但它们的 VRF / 全局归属尚未映射到当前地址空间，因此不能自动关联。可先维护设备路由上下文，或在下方手动选择候选设备。' : 'Interface candidates exist, but their VRF / Global scope is not mapped to this address space, so they cannot be auto-bound. Map the device routing context or choose a candidate below.');
  }
  if (response.gateway_ip) {
    return source === 'manual'
      ? (zh ? '没有接口与填写的网关 IP 匹配；已保留人工设备选择。' : 'No interface matches the entered gateway IP; the manual device selection is preserved.')
      : (zh ? '没有接口与填写的网关 IP 匹配，当前未关联设备。' : 'No interface matches the entered gateway IP; no device is bound.');
  }
  if (response.endpoints.length > 1) {
    return source === 'manual'
      ? (zh ? `找到 ${response.endpoints.length} 个接口候选；已保留人工设备选择。` : `${response.endpoints.length} interface candidates were found; the manual device choice is preserved.`)
      : (zh ? `找到 ${response.endpoints.length} 个接口候选，无法确定哪一个是网关；请填写网关 IP 或手动选择设备。` : `${response.endpoints.length} interface candidates were found; the gateway is ambiguous. Enter its IP or choose a device manually.`);
  }
  if (response.endpoints.length === 1) {
    return source === 'manual'
      ? (zh ? '找到唯一接口候选；已保留人工设备选择。' : 'A unique interface candidate was found; the manual device choice is preserved.')
      : (zh ? '找到一个接口候选，但它没有确认属于当前地址空间；当前未自动关联。' : 'One interface candidate was found, but it is not confirmed in this address space; it was not auto-bound.');
  }
  return source === 'manual'
    ? (zh ? '当前网段没有接口候选；已保留人工设备选择。' : 'No interface candidate was found in this prefix; the manual device choice is preserved.')
    : (zh ? '当前网段没有接口候选；请填写网关 IP 或手动选择设备。' : 'No interface candidate was found in this prefix; enter a gateway IP or choose a device manually.');
}

const PrefixManagementTab: React.FC<PrefixManagementTabProps> = ({ language, t }) => {
  const treeTableRef = useRef<HTMLTableElement>(null);
  const tableScrollContainerRef = useRef<HTMLDivElement>(null);
  const prefixTableRef = useRef<HTMLTableElement>(null);
  const hasLoadedPrefixDataRef = useRef(false);
  const pendingCreateRequest = useRef<PendingCreateRequest | null>(null);
  const pendingInterfaceGeneration = useRef<PendingCreateRequest | null>(null);
  const navigate = useNavigate();
  const zh = language === 'zh';
  
  const [prefixes, setPrefixes] = useState<Prefix[]>([]);
  const [classificationSummary, setClassificationSummary] = useState<PrefixClassificationSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [search, setSearch] = useState('');
  const [viewMode, setViewMode] = useState<'table' | 'tree'>('table');
  const [familyFilter, setFamilyFilter] = useState<'all' | 'ipv4' | 'ipv6'>('all');
  const [siteFilter, setSiteFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [classificationFilter, setClassificationFilter] = useState<PrefixClassificationFilter>('all');
  const [classificationMethodOpen, setClassificationMethodOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [selectedRevisions, setSelectedRevisions] = useState<Record<string, number>>({});
  const [collapsedSites, setCollapsedSites] = useState<Record<string, boolean>>({});

  // CMDB Dropdowns
  const [sites, setSites] = useState<any[]>([]);
  const [addressSpaces, setAddressSpaces] = useState<AddressSpace[]>([]);
  const [addressSpacesLoading, setAddressSpacesLoading] = useState(false);
  const [addressSpacesError, setAddressSpacesError] = useState('');
  const [globalSpaceName, setGlobalSpaceName] = useState('');
  const [globalSpaceCreating, setGlobalSpaceCreating] = useState(false);
  const [vlans, setVlans] = useState<any[]>([]);
  const [devices, setDevices] = useState<any[]>([]);

  // Modals
  const [showAddEdit, setShowAddEdit] = useState(false);
  const [editingPrefix, setEditingPrefix] = useState<Prefix | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<string | null>(null);
  const [deletePreview, setDeletePreview] = useState<{
    prefix_id: string;
    prefix: string;
    active_ip_count: number;
    released_ip_count: number;
    pool_count: number;
    vip_count: number;
    lease_count: number;
    child_prefix_count: number;
    can_delete: boolean;
    blockers: string[];
  } | null>(null);
  const [deletePreviewLoading, setDeletePreviewLoading] = useState(false);
  const [deletePreviewError, setDeletePreviewError] = useState('');
  const [showBatchDeleteConfirm, setShowBatchDeleteConfirm] = useState(false);
  const [showBatchNetworkTypeModal, setShowBatchNetworkTypeModal] = useState(false);
  const [showBatchAddressSpaceModal, setShowBatchAddressSpaceModal] = useState(false);
  const [batchNetworkType, setBatchNetworkType] = useState('server');
  const [batchNetworkTypeError, setBatchNetworkTypeError] = useState('');
  const [batchNetworkTypeUpdating, setBatchNetworkTypeUpdating] = useState(false);
  const [batchNetworkTypeResult, setBatchNetworkTypeResult] = useState('');
  const [batchAddressSpaceTargetId, setBatchAddressSpaceTargetId] = useState('');
  const [batchAddressSpacePreview, setBatchAddressSpacePreview] = useState<AddressSpaceBatchResolutionPreview | null>(null);
  const [batchAddressSpaceLoading, setBatchAddressSpaceLoading] = useState(false);
  const [batchAddressSpaceSaving, setBatchAddressSpaceSaving] = useState(false);
  const [batchAddressSpaceConfirmed, setBatchAddressSpaceConfirmed] = useState(false);
  const [batchAddressSpaceError, setBatchAddressSpaceError] = useState('');
  const [batchAddressSpaceResult, setBatchAddressSpaceResult] = useState('');
  const [showInterfaceGeneration, setShowInterfaceGeneration] = useState(false);
  const [interfaceImportReviewRequest, setInterfaceImportReviewRequest] = useState<InterfaceImportRequest | null>(null);
  const [poolManagerPrefix, setPoolManagerPrefix] = useState<Prefix | null>(null);
  useEscapeClose(showAddEdit, () => { setShowAddEdit(false); setEditingPrefix(null); });
  useEscapeClose(Boolean(showDeleteConfirm), () => setShowDeleteConfirm(null));

  useEffect(() => {
    if (!showDeleteConfirm) {
      setDeletePreview(null);
      setDeletePreviewLoading(false);
      setDeletePreviewError('');
      return;
    }
    const controller = new AbortController();
    setDeletePreview(null);
    setDeletePreviewLoading(true);
    setDeletePreviewError('');
    const token = localStorage.getItem('netops_token');
    fetch(`/api/ipam/subnets/${encodeURIComponent(showDeleteConfirm)}/delete-preview`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      signal: controller.signal,
    })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((payload) => {
        if (!controller.signal.aborted && payload && typeof payload.can_delete === 'boolean') {
          setDeletePreview({
            ...payload,
            blockers: Array.isArray(payload.blockers) ? payload.blockers : [],
          });
        }
      })
      .catch((err) => {
        if (!controller.signal.aborted) {
          setDeletePreviewError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setDeletePreviewLoading(false);
      });
    return () => controller.abort();
  }, [showDeleteConfirm]);
  useEscapeClose(showBatchDeleteConfirm, () => setShowBatchDeleteConfirm(false));
  useEscapeClose(showBatchNetworkTypeModal && !batchNetworkTypeUpdating, () => setShowBatchNetworkTypeModal(false));
  useEscapeClose(showInterfaceGeneration, () => setShowInterfaceGeneration(false));
  useEscapeClose(Boolean(poolManagerPrefix), () => setPoolManagerPrefix(null));
  const [interfaceCandidates, setInterfaceCandidates] = useState<InterfacePrefixCandidate[]>([]);
  const [selectedInterfaceCandidates, setSelectedInterfaceCandidates] = useState<Set<string>>(new Set());
  const [selectedInterfaceCandidateSnapshots, setSelectedInterfaceCandidateSnapshots] = useState<Record<string, InterfacePrefixCandidate>>({});
  const [selectedInterfaceSpaces, setSelectedInterfaceSpaces] = useState<Record<string, string>>({});
  const [bulkInterfaceSpaceId, setBulkInterfaceSpaceId] = useState('');
  const [bulkGlobalInterfaceSpaceId, setBulkGlobalInterfaceSpaceId] = useState('');
  const [interfaceSkipped, setInterfaceSkipped] = useState<Array<{ device_name: string; interface_name: string; address: string; reason: string }>>([]);
  const [interfaceCandidateSummary, setInterfaceCandidateSummary] = useState<InterfaceCandidateSummary>({
    candidate_count: 0,
    existing_count: 0,
    to_create_count: 0,
    interface_count: 0,
    vrf_pending_count: 0,
    skipped_count: 0,
  });
  const [interfaceCandidatePage, setInterfaceCandidatePage] = useState<InterfaceCandidatePage>({
    page: 1,
    page_size: 25,
    filtered_count: 0,
    total_pages: 0,
  });
  const [interfaceCandidateFilter, setInterfaceCandidateFilter] = useState<InterfaceCandidateFilter>('all');
  const [interfaceCandidateSearchInput, setInterfaceCandidateSearchInput] = useState('');
  const [interfaceCandidateSearch, setInterfaceCandidateSearch] = useState('');
  const [interfaceGenerationLoading, setInterfaceGenerationLoading] = useState(false);
  const [interfaceCandidatesLoading, setInterfaceCandidatesLoading] = useState(false);
  const [interfaceGenerationError, setInterfaceGenerationError] = useState('');
  const [interfaceGenerationScopeError, setInterfaceGenerationScopeError] = useState('');
  const [interfaceGenerationResult, setInterfaceGenerationResult] = useState('');
  const [showSkippedDetails, setShowSkippedDetails] = useState(false);
  const [showGenerateAllPendingConfirm, setShowGenerateAllPendingConfirm] = useState(false);
  const interfaceCandidateRequestId = useRef(0);
  useEscapeClose(showGenerateAllPendingConfirm, () => setShowGenerateAllPendingConfirm(false));

  // Form State
  const [form, setForm] = useState({
    prefix: '',
    name: '',
    vrf_id: '',
    address_space_id: '',
    vlan_id: '',
    site_id: '',
    status: 'active',
    gateway: '',
    description: '',
    network_type: DEFAULT_NEW_PREFIX_NETWORK_TYPE,
    gateway_device_id: '',
    gateway_interface_id: '',
    traceable: 1,
  });
  const findVrfAddressSpace = (vrfId: string | null | undefined) =>
    addressSpaces.find((space) => space.kind === 'vrf'
      && space.vrf_id === vrfId
      && space.status === 'active');
  const interfaceCandidateAddressSpaceId = (candidate: InterfacePrefixCandidate) =>
    selectedInterfaceSpaces[candidate.candidate_id]
      || candidate.address_space_id
      || findVrfAddressSpace(candidate.vrf_id)?.id
      || '';
  const interfaceCandidateHasResolvedSpace = (candidate: InterfacePrefixCandidate) =>
    Boolean(selectedInterfaceSpaces[candidate.candidate_id]
      || candidate.address_space_id
      || (!candidate.vrf_scope_pending && candidate.vrf_id && findVrfAddressSpace(candidate.vrf_id)));
  const interfaceCandidateNeedsManualSpace = (candidate: InterfacePrefixCandidate) =>
    Boolean(candidate.vrf_scope_pending || (!candidate.vrf_id && !candidate.address_space_id));
  const interfaceCandidateSpaceOptions = (candidate: InterfacePrefixCandidate) =>
    addressSpaces.filter((space) => space.status === 'active'
      && (!candidate.tenant_id || space.security_tenant_id === candidate.tenant_id)
      && (!candidate.vrf_id || (space.kind === 'vrf' && space.vrf_id === candidate.vrf_id)));
  const selectedInterfaceCandidateItems = Array.from(selectedInterfaceCandidates)
    .map((candidateId) => selectedInterfaceCandidateSnapshots[candidateId]
      || interfaceCandidates.find((candidate) => candidate.candidate_id === candidateId))
    .filter((candidate): candidate is InterfacePrefixCandidate => Boolean(candidate));
  const selectedInterfacePendingScopeCandidates = selectedInterfaceCandidateItems
    .filter((candidate) => Boolean(candidate.vrf_scope_pending) && !interfaceCandidateHasResolvedSpace(candidate));
  const selectedInterfaceUnscopedCandidates = selectedInterfacePendingScopeCandidates
    .filter((candidate) => !candidate.vrf_id);
  const selectedInterfaceCommonVrfSpaces = addressSpaces.filter((space) =>
    space.status === 'active'
    && space.kind === 'vrf'
    && selectedInterfacePendingScopeCandidates.length > 0
    && selectedInterfacePendingScopeCandidates.every((candidate) =>
      (!candidate.tenant_id || candidate.tenant_id === space.security_tenant_id)
      && (!candidate.vrf_id || candidate.vrf_id === space.vrf_id)));
  const activeGlobalInterfaceSpaces = addressSpaces.filter((space) => space.status === 'active' && space.kind === 'global');
  const selectedInterfaceCommonGlobalSpaces = activeGlobalInterfaceSpaces.filter((space) =>
    selectedInterfaceUnscopedCandidates.length > 0
    && selectedInterfaceUnscopedCandidates.every((candidate) =>
      !candidate.tenant_id || candidate.tenant_id === space.security_tenant_id));
  const selectedInterfaceCandidatesMissingSpace = selectedInterfaceCandidateItems.filter((candidate) => {
    if (interfaceCandidateHasResolvedSpace(candidate)) return false;
    return Boolean(candidate.vrf_scope_pending || !candidate.vrf_id);
  });
  const selectedInterfaceCandidateMetadataMissing = selectedInterfaceCandidates.size - selectedInterfaceCandidateItems.length;
  const selectedInterfaceHasMissingSpace = selectedInterfaceCandidatesMissingSpace.length > 0
    || selectedInterfaceCandidateMetadataMissing > 0;
  const selectedInterfaceMissingSpaceLabels = selectedInterfaceCandidatesMissingSpace.map((candidate) => candidate.prefix);
  const selectedInterfaceMissingSpaceMessage = selectedInterfaceHasMissingSpace
    ? (zh
      ? `已选候选中有 ${selectedInterfaceCandidatesMissingSpace.length + selectedInterfaceCandidateMetadataMissing} 项尚未确认地址空间${selectedInterfaceMissingSpaceLabels.length > 0 ? `：${selectedInterfaceMissingSpaceLabels.slice(0, 3).join('、')}${selectedInterfaceMissingSpaceLabels.length > 3 ? '…' : ''}` : ''}。请先批量或逐项选择地址空间，再生成。`
      : `${selectedInterfaceCandidatesMissingSpace.length + selectedInterfaceCandidateMetadataMissing} selected candidates still need an address space${selectedInterfaceMissingSpaceLabels.length > 0 ? `: ${selectedInterfaceMissingSpaceLabels.slice(0, 3).join(', ')}${selectedInterfaceMissingSpaceLabels.length > 3 ? '…' : ''}` : ''}. Choose a space for each candidate before generating.`)
    : '';
  const gatewayBindingSourceRef = useRef<GatewayBindingSource>('none');
  const gatewayCandidateRequestId = useRef(0);
  const [gatewayCandidates, setGatewayCandidates] = useState<GatewayCandidateResponse | null>(null);
  const [gatewayCandidatesLoading, setGatewayCandidatesLoading] = useState(false);
  const [gatewayCandidatesError, setGatewayCandidatesError] = useState('');
  const gatewayCandidateDevices = Array.from(new Map(
    (gatewayCandidates?.endpoints || [])
      .filter((endpoint) => endpoint.device_id)
      .map((endpoint) => [endpoint.device_id as string, endpoint]),
  ).values());
  const [scopeResolutionPrefix, setScopeResolutionPrefix] = useState<Prefix | null>(null);
  const [scopeResolutionMode, setScopeResolutionMode] = useState<'resolve' | 'move'>('resolve');
  const [scopeResolutionSpaceId, setScopeResolutionSpaceId] = useState('');
  const [scopeResolutionPreview, setScopeResolutionPreview] = useState<AddressSpaceResolutionPreview | null>(null);
  const [scopeResolutionLoading, setScopeResolutionLoading] = useState(false);
  const [scopeResolutionSaving, setScopeResolutionSaving] = useState(false);
  const [scopeResolutionConfirmed, setScopeResolutionConfirmed] = useState(false);
  const [scopeResolutionError, setScopeResolutionError] = useState('');
  useEscapeClose(Boolean(scopeResolutionPrefix) && !scopeResolutionSaving, () => setScopeResolutionPrefix(null));
  useEscapeClose(Boolean(showBatchAddressSpaceModal) && !batchAddressSpaceSaving, () => setShowBatchAddressSpaceModal(false));
  const [errorMsg, setErrorMsg] = useState('');
  const [gatewayDeviceSearch, setGatewayDeviceSearch] = useState('');
  const [parentSubnetId, setParentSubnetId] = useState('');
  const [desiredPrefixLen, setDesiredPrefixLen] = useState(24);
  const [showSubnetRecommendation, setShowSubnetRecommendation] = useState(false);
  const [showIpPlanningHelper, setShowIpPlanningHelper] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [excludeNetBroadcast, setExcludeNetBroadcast] = useState(true);
  const [excludeGateway, setExcludeGateway] = useState(true);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [totalPrefixes, setTotalPrefixes] = useState(0);
  const canUseTreeView = canUsePrefixTreeView({
    q: search,
    site: siteFilter,
    status: statusFilter,
    classification: classificationFilter,
  });

  const usableIpDetails = useMemo(() => {
    const cidr = form.prefix.trim();
    if (!cidr || !cidr.includes('/')) return null;
    const parts = cidr.split('/');
    const ipStr = parts[0].trim();
    const maskStr = parts[1].trim();
    const mask = parseInt(maskStr, 10);
    if (isNaN(mask)) return null;

    const isV6 = ipStr.includes(':');

    if (!isV6) {
      // IPv4
      if (mask < 0 || mask > 32) return null;
      if (!isValidIPv4(ipStr)) return null;

      const ipNum = toNum(ipStr);
      const maskBin = mask === 0 ? 0 : (0xFFFFFFFF << (32 - mask)) >>> 0;
      const netNum = (ipNum & maskBin) >>> 0;
      const broadNum = (netNum | ~maskBin) >>> 0;

      const networkIp = [
        (netNum >>> 24) & 0xFF,
        (netNum >>> 16) & 0xFF,
        (netNum >>> 8) & 0xFF,
        netNum & 0xFF
      ].join('.');

      const broadcastIp = [
        (broadNum >>> 24) & 0xFF,
        (broadNum >>> 16) & 0xFF,
        (broadNum >>> 8) & 0xFF,
        broadNum & 0xFF
      ].join('.');

      const total = Math.pow(2, 32 - mask);
      let subtracted = 0;
      let netBroadcastLabel = '';
      
      const hasNetBroadcast = mask <= 30;
      if (hasNetBroadcast && excludeNetBroadcast) {
        subtracted += 2;
        netBroadcastLabel = zh 
          ? `已排除网络地址 (${networkIp}) 与广播地址 (${broadcastIp})`
          : `Excluded network (${networkIp}) & broadcast (${broadcastIp})`;
      } else if (hasNetBroadcast) {
        netBroadcastLabel = zh
          ? `网络地址 (${networkIp}) 与广播地址 (${broadcastIp}) 计入可用`
          : `Network (${networkIp}) & broadcast (${broadcastIp}) included`;
      } else {
        netBroadcastLabel = zh
          ? '点对点/主机网段，无网络或广播地址'
          : 'P2P or host subnet, no network/broadcast';
      }

      // Check gateway
      const hasGateway = form.gateway.trim() !== '';
      let gatewayValidAndInSubnet = false;
      let gatewayIp = form.gateway.trim();
      if (hasGateway && isValidIPv4(gatewayIp)) {
        const gwNum = toNum(gatewayIp);
        if ((gwNum & maskBin) === netNum) {
          gatewayValidAndInSubnet = true;
        }
      }

      let gatewayLabel = '';
      if (hasGateway) {
        if (!gatewayValidAndInSubnet) {
          gatewayLabel = zh 
            ? '网关 IP 不在当前子网范围内' 
            : 'Gateway IP is not within the subnet';
        } else if (excludeGateway) {
          subtracted += 1;
          gatewayLabel = zh 
            ? `已排除网关地址 (${gatewayIp})` 
            : `Excluded gateway (${gatewayIp})`;
        } else {
          gatewayLabel = zh 
            ? `网关地址 (${gatewayIp}) 计入可用` 
            : `Gateway (${gatewayIp}) included`;
        }
      } else {
        gatewayLabel = zh ? '未设置网关' : 'Gateway not set';
      }

      const usable = Math.max(0, total - subtracted);

      // Usable Host Range
      let firstUsableNum = netNum;
      let lastUsableNum = broadNum;
      if (mask <= 30) {
        if (excludeNetBroadcast) {
          firstUsableNum = netNum + 1;
          lastUsableNum = broadNum - 1;
        }
      }

      let usableRangeStr = '';
      if (usable === 0) {
        usableRangeStr = zh ? '无可用地址' : 'No usable addresses';
      } else if (usable === 1) {
        const singleIp = [
          (firstUsableNum >>> 24) & 0xFF,
          (firstUsableNum >>> 16) & 0xFF,
          (firstUsableNum >>> 8) & 0xFF,
          firstUsableNum & 0xFF
        ].join('.');
        usableRangeStr = singleIp;
      } else {
        const startIp = [
          (firstUsableNum >>> 24) & 0xFF,
          (firstUsableNum >>> 16) & 0xFF,
          (firstUsableNum >>> 8) & 0xFF,
          firstUsableNum & 0xFF
        ].join('.');
        const endIp = [
          (lastUsableNum >>> 24) & 0xFF,
          (lastUsableNum >>> 16) & 0xFF,
          (lastUsableNum >>> 8) & 0xFF,
          lastUsableNum & 0xFF
        ].join('.');
        usableRangeStr = `${startIp} ~ ${endIp}`;
        if (hasGateway && gatewayValidAndInSubnet && excludeGateway) {
          usableRangeStr += zh ? ` (排除 ${gatewayIp})` : ` (excluding ${gatewayIp})`;
        }
      }

      return {
        total,
        usable,
        networkIp,
        broadcastIp,
        hasNetBroadcast,
        netBroadcastLabel,
        hasGateway,
        gatewayValidAndInSubnet,
        gatewayIp,
        gatewayLabel,
        usableRangeStr,
        isV6: false
      };
    } else {
      // IPv6
      if (mask < 0 || mask > 128) return null;
      if (!isValidIPv6(ipStr)) return null;

      let total = 0;
      let usable = 0;
      const exponent = 128 - mask;
      let isMassive = false;

      if (exponent >= 60) {
        isMassive = true;
      } else {
        total = Math.pow(2, exponent);
      }

      const networkIp = ipStr;
      let netBroadcastLabel = '';
      let subtracted = 0;

      const hasNetBroadcast = mask <= 126;
      if (hasNetBroadcast && excludeNetBroadcast) {
        subtracted += 1; // Exclude subnet router anycast
        netBroadcastLabel = zh
          ? `已排除子网路由器任播地址 (${networkIp})`
          : `Excluded Subnet Router Anycast (${networkIp})`;
      } else if (hasNetBroadcast) {
        netBroadcastLabel = zh
          ? `所有子网地址均计入可用`
          : `All subnet addresses included`;
      } else {
        netBroadcastLabel = zh
          ? '点对点/主机网段，无保留地址'
          : 'P2P or host subnet, no reserved addresses';
      }

      const hasGateway = form.gateway.trim() !== '';
      let gatewayValidAndInSubnet = false;
      let gatewayIp = form.gateway.trim();
      if (hasGateway && isValidIPv6(gatewayIp)) {
        gatewayValidAndInSubnet = true;
      }

      let gatewayLabel = '';
      if (hasGateway) {
        if (!gatewayValidAndInSubnet) {
          gatewayLabel = zh 
            ? '网关 IP 格式不正确' 
            : 'Gateway IP format is invalid';
        } else if (excludeGateway) {
          subtracted += 1;
          gatewayLabel = zh 
            ? `已排除网关地址 (${gatewayIp})` 
            : `Excluded gateway (${gatewayIp})`;
        } else {
          gatewayLabel = zh 
            ? `网关地址 (${gatewayIp}) 计入可用` 
            : `Gateway (${gatewayIp}) included`;
        }
      } else {
        gatewayLabel = zh ? '未设置网关' : 'Gateway not set';
      }

      if (isMassive) {
        usable = -1;
      } else {
        usable = Math.max(0, total - subtracted);
      }

      let usableRangeStr = '';
      if (isMassive) {
        usableRangeStr = zh ? '海量可用 IP (极多)' : 'Massive usable capacity';
      } else {
        usableRangeStr = zh ? `共可分配 ${usable.toLocaleString()} 个 IP` : `${usable.toLocaleString()} usable IPs`;
      }

      return {
        total: isMassive ? -1 : total,
        usable,
        networkIp,
        broadcastIp: 'N/A',
        hasNetBroadcast,
        netBroadcastLabel,
        hasGateway,
        gatewayValidAndInSubnet,
        gatewayIp,
        gatewayLabel,
        usableRangeStr,
        isV6: true
      };
    }
  }, [form.prefix, form.gateway, excludeNetBroadcast, excludeGateway, zh]);

  const authHeaders = useCallback(() => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, []);

  // Fetch CMDB lookup tables
  const fetchLookups = useCallback(async () => {
    const hdrs = authHeaders();
    setAddressSpacesLoading(true);
    setAddressSpacesError('');
    try {
      const [sitesRes, spacesRes, vlansRes, devicesRes] = await Promise.all([
        fetch('/api/cmdb/sites', { headers: hdrs }),
        fetch('/api/ipam/address-spaces', { headers: hdrs }),
        fetch('/api/cmdb/vlans', { headers: hdrs }),
        fetch('/api/devices?mode=light', { headers: hdrs }),
      ]);
      const unwrap = (j: any) => (Array.isArray(j) ? j : (j?.data ?? j?.items ?? []));
      if (sitesRes.ok) setSites(unwrap(await sitesRes.json()));
      if (spacesRes.ok) {
        const payload = await spacesRes.json();
        setAddressSpaces(Array.isArray(payload) ? payload : (Array.isArray(payload?.items) ? payload.items : []));
      } else {
        const payload = await spacesRes.json().catch(() => ({}));
        setAddressSpaces([]);
        setAddressSpacesError(spacesRes.status === 401
          ? (zh ? '登录已过期，请重新登录后重试。' : 'Your session has expired. Sign in and retry.')
          : spacesRes.status === 403
            ? (zh ? '当前账号没有查看地址空间的权限。' : 'You do not have permission to view address spaces.')
            : payload?.detail || (zh ? '加载地址空间失败，请重试。' : 'Failed to load address spaces.'));
      }
      if (vlansRes.ok) setVlans(unwrap(await vlansRes.json()));
      if (devicesRes.ok) {
        setDevices(unwrap(await devicesRes.json()));
      }
    } catch (e) {
      console.error('Failed to load CMDB lookup data:', e);
      setAddressSpacesError(zh ? '加载地址空间失败，请检查网络后重试。' : 'Failed to load address spaces. Check the connection and retry.');
    } finally {
      setAddressSpacesLoading(false);
    }
  }, [authHeaders, zh]);

  const loadData = useCallback(async (options?: { silent?: boolean }) => {
    const silent = options?.silent === true || hasLoadedPrefixDataRef.current;
    if (!silent) setLoading(true);
    setLoadError('');
    try {
      const headers = authHeaders();
      const prefixQuery = buildPrefixListQuery({
        q: search,
        site: siteFilter,
        status: statusFilter,
        family: familyFilter,
        page,
        pageSize,
        classification: classificationFilter,
      });
      const summaryQuery = buildPrefixClassificationSummaryQuery({
        q: search,
        site: siteFilter,
        status: statusFilter,
        family: familyFilter,
      });
      const [prefixRes, summaryRes] = await Promise.all([
        fetch(`/api/ipam/subnets?${prefixQuery.toString()}`, { headers }),
        fetch(`/api/ipam/prefixes/classification-summary?${summaryQuery.toString()}`, { headers }),
      ]);
      if (prefixRes.ok) {
        const payload = await prefixRes.json();
        setPrefixes(Array.isArray(payload) ? payload : (payload.items || []));
        setTotalPrefixes(Array.isArray(payload) ? payload.length : Number(payload.total || 0));
        hasLoadedPrefixDataRef.current = true;
      } else {
        setLoadError(prefixRes.status === 401
          ? (zh ? '登录已过期，请重新登录后重试。' : 'Your session has expired. Sign in and retry.')
          : prefixRes.status === 403
            ? (zh ? '当前账号没有查看网段的权限。' : 'You do not have permission to view prefixes.')
            : (zh ? '加载网段列表失败，请重试。' : 'Failed to load prefixes. Please retry.'));
      }
      if (summaryRes.ok) setClassificationSummary(await summaryRes.json());
      else {
        setClassificationSummary(null);
        if (prefixRes.ok) {
          setLoadError(summaryRes.status === 401 || summaryRes.status === 403
            ? (zh ? '当前账号无法读取网段分类汇总。' : 'You do not have permission to view the prefix summary.')
            : (zh ? '加载网段分类汇总失败。' : 'Failed to load prefix classification summary.'));
        }
      }
    } catch (e) {
      console.error(e);
      setLoadError(zh ? '加载网段信息失败，请检查网络后重试。' : 'Failed to load prefix data. Check the connection and retry.');
    } finally {
      if (!silent) setLoading(false);
    }
  }, [search, siteFilter, statusFilter, familyFilter, page, pageSize, classificationFilter, authHeaders, zh]);

  const loadInterfaceCandidates = async (
    requestedPage = 1,
    status: InterfaceCandidateFilter = interfaceCandidateFilter,
    searchQuery = interfaceCandidateSearch,
  ) => {
    const requestId = ++interfaceCandidateRequestId.current;
    setInterfaceCandidatesLoading(true);
    setInterfaceGenerationError('');
    setInterfaceGenerationScopeError('');
    try {
      const query = new URLSearchParams({ page: String(requestedPage), page_size: '25', status });
      const normalizedSearch = searchQuery.trim();
      if (normalizedSearch) query.set('q', normalizedSearch);
      const res = await fetch(`/api/ipam/prefixes/interface-candidates?${query.toString()}`, { headers: authHeaders() });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = res.status === 401
          ? (zh ? '登录已过期，请重新登录后重试。' : 'Your session has expired. Sign in and retry.')
          : res.status === 403
            ? (zh ? '当前账号没有读取接口候选项的权限。' : 'You do not have permission to read interface candidates.')
            : data?.detail || (zh ? '无法读取当前接口采集结果。' : 'Unable to load interface collection.');
        throw new Error(message);
      }
      if (requestId !== interfaceCandidateRequestId.current) return;

      const candidates = Array.isArray(data?.candidates) ? data.candidates : [];
      setInterfaceCandidates(candidates);
      setSelectedInterfaceCandidateSnapshots((current) => {
        const next = { ...current };
        candidates.forEach((candidate) => {
          if (selectedInterfaceCandidates.has(candidate.candidate_id)) {
            next[candidate.candidate_id] = candidate;
          }
        });
        return next;
      });
      setSelectedInterfaceSpaces((current) => {
        const next = { ...current };
        candidates.forEach((candidate) => {
          if (selectedInterfaceCandidates.has(candidate.candidate_id) && !candidate.vrf_scope_pending) {
            delete next[candidate.candidate_id];
          }
        });
        return next;
      });
      setInterfaceSkipped(Array.isArray(data?.skipped) ? data.skipped : []);
      setInterfaceCandidateSummary({
        candidate_count: Number(data?.candidate_count || 0),
        existing_count: Number(data?.existing_count || 0),
        to_create_count: Number(data?.to_create_count || 0),
        interface_count: Number(data?.interface_count || 0),
        vrf_pending_count: Number(data?.vrf_pending_count || 0),
        skipped_count: Number(data?.skipped_count || 0),
      });
      setInterfaceCandidatePage({
        page: Number(data?.page || requestedPage),
        page_size: Number(data?.page_size || 25),
        filtered_count: Number(data?.filtered_count || 0),
        total_pages: Number(data?.total_pages || 0),
      });
    } catch (error) {
      if (requestId === interfaceCandidateRequestId.current) {
        setInterfaceGenerationError(error instanceof Error ? error.message : String(error));
      }
    } finally {
      if (requestId === interfaceCandidateRequestId.current) setInterfaceCandidatesLoading(false);
    }
  };

  const openInterfaceGeneration = async () => {
    setInterfaceGenerationError('');
    setInterfaceGenerationResult('');
    setSelectedInterfaceCandidates(new Set());
    setSelectedInterfaceCandidateSnapshots({});
    setSelectedInterfaceSpaces({});
    setBulkInterfaceSpaceId('');
    setBulkGlobalInterfaceSpaceId('');
    setInterfaceGenerationScopeError('');
    setInterfaceCandidateFilter('all');
    setInterfaceCandidateSearchInput('');
    setInterfaceCandidateSearch('');
    setInterfaceCandidatePage((current) => ({ ...current, page: 1 }));
    setShowSkippedDetails(false);
    setShowGenerateAllPendingConfirm(false);
    setShowInterfaceGeneration(true);
    await loadInterfaceCandidates(1, 'all', '');
  };

  const toggleInterfaceCandidate = (candidate: InterfacePrefixCandidate) => {
    const candidateId = candidate.candidate_id;
    const next = new Set(selectedInterfaceCandidates);
    const isSelected = next.has(candidateId);
    if (isSelected) next.delete(candidateId);
    else next.add(candidateId);
    setSelectedInterfaceCandidates(next);
    setSelectedInterfaceCandidateSnapshots((current) => {
      const updated = { ...current };
      if (isSelected) delete updated[candidateId];
      else updated[candidateId] = candidate;
      return updated;
    });
    setBulkInterfaceSpaceId('');
    setBulkGlobalInterfaceSpaceId('');
    setInterfaceGenerationScopeError('');
  };

  const selectVisibleInterfaceCandidates = () => {
    const visibleIds = interfaceCandidates.map((candidate) => candidate.candidate_id);
    const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((candidateId) => selectedInterfaceCandidates.has(candidateId));
    const next = new Set(selectedInterfaceCandidates);
    const nextSnapshots = { ...selectedInterfaceCandidateSnapshots };
    visibleIds.forEach((candidateId) => {
      if (allVisibleSelected) {
        next.delete(candidateId);
        delete nextSnapshots[candidateId];
      } else {
        next.add(candidateId);
        const candidate = interfaceCandidates.find((item) => item.candidate_id === candidateId);
        if (candidate) nextSnapshots[candidateId] = candidate;
      }
    });
    setSelectedInterfaceCandidates(next);
    setSelectedInterfaceCandidateSnapshots(nextSnapshots);
    setBulkInterfaceSpaceId('');
    setBulkGlobalInterfaceSpaceId('');
    setInterfaceGenerationScopeError('');
  };

  const applyBulkInterfaceSpace = () => {
    const targetSpace = selectedInterfaceCommonVrfSpaces.find((space) => space.id === bulkInterfaceSpaceId);
    if (!targetSpace || selectedInterfacePendingScopeCandidates.length === 0) return;
    setSelectedInterfaceSpaces((current) => ({
      ...current,
      ...Object.fromEntries(selectedInterfacePendingScopeCandidates.map((candidate) => [candidate.candidate_id, targetSpace.id])),
    }));
    setInterfaceGenerationScopeError('');
  };

  const confirmUnscopedCandidatesUseGlobal = () => {
    const targetSpace = selectedInterfaceCommonGlobalSpaces.find((space) => space.id === bulkGlobalInterfaceSpaceId)
      || (selectedInterfaceCommonGlobalSpaces.length === 1 ? selectedInterfaceCommonGlobalSpaces[0] : undefined);
    if (!targetSpace || selectedInterfaceUnscopedCandidates.length === 0) return;
    setSelectedInterfaceSpaces((current) => ({
      ...current,
      ...Object.fromEntries(selectedInterfaceUnscopedCandidates.map((candidate) => [candidate.candidate_id, targetSpace.id])),
    }));
    setInterfaceGenerationScopeError('');
  };

  const generateFromInterfaces = async (allPending = false, confirmedRequest?: InterfaceImportRequest) => {
    if (!confirmedRequest && (allPending ? interfaceCandidateSummary.to_create_count === 0 : selectedInterfaceCandidates.size === 0)) return;
    if (!confirmedRequest && !allPending) {
      const missingCandidates = selectedInterfaceCandidateItems.filter((candidate) => {
        if (selectedInterfaceSpaces[candidate.candidate_id] || candidate.address_space_id) return false;
        return Boolean(candidate.vrf_scope_pending || !candidate.vrf_id);
      });
      const missingMetadataCount = selectedInterfaceCandidateMetadataMissing;
      const invalidVrfOverride = selectedInterfaceCandidateItems.find((candidate) => {
        const overrideId = selectedInterfaceSpaces[candidate.candidate_id];
        if (!overrideId || !candidate.vrf_id) return false;
        const target = addressSpaces.find((space) => space.id === overrideId && space.status === 'active');
        return !target
          || (candidate.tenant_id && target.security_tenant_id !== candidate.tenant_id)
          || target.kind !== 'vrf'
          || target.vrf_id !== candidate.vrf_id;
      });
      if (missingCandidates.length > 0 || missingMetadataCount > 0) {
        const names = missingCandidates.map((candidate) => candidate.prefix).slice(0, 5);
        const message = zh
          ? `所选候选仍缺少地址空间${names.length ? `：${names.join('、')}${missingCandidates.length > names.length ? '…' : ''}` : ''}${missingMetadataCount ? `；另有 ${missingMetadataCount} 项候选信息已失效，请刷新` : ''}。`
          : `Selected candidates still need an address space${names.length ? `: ${names.join(', ')}${missingCandidates.length > names.length ? '…' : ''}` : ''}${missingMetadataCount ? `; ${missingMetadataCount} candidate records are unavailable. Refresh the preview` : ''}.`;
        setInterfaceGenerationScopeError(message);
        return;
      }
      if (invalidVrfOverride) {
        setInterfaceGenerationScopeError(zh
          ? `${invalidVrfOverride.prefix} 已知 VRF ${invalidVrfOverride.vrf_id}，只能使用该 VRF 的地址空间。`
          : `${invalidVrfOverride.prefix} has known VRF ${invalidVrfOverride.vrf_id}; choose an address space for that VRF.`);
        return;
      }
    }
    setInterfaceGenerationScopeError('');
    if (!confirmedRequest) {
      let candidateIds = Array.from(selectedInterfaceCandidates);
      const addressSpaceOverrides = Object.fromEntries(
        Object.entries(selectedInterfaceSpaces)
          .filter(([candidateId, addressSpaceId]) => candidateIds.includes(candidateId)
            && Boolean(addressSpaceId)
            && selectedInterfaceCandidateItems.some((candidate) => candidate.candidate_id === candidateId && !candidate.address_space_id)),
      );
      if (allPending) {
        try {
          const firstResponse = await fetch('/api/ipam/prefixes/interface-candidates?page=1&page_size=100&status=to_create', { headers: authHeaders() });
          const firstPage = await firstResponse.json().catch(() => ({}));
          if (!firstResponse.ok || !Array.isArray(firstPage.candidates)) throw new Error(firstPage?.detail || (zh ? '无法读取待创建候选，请刷新后重试。' : 'Could not load pending candidates. Refresh and retry.'));
          candidateIds = firstPage.candidates.map((candidate: InterfacePrefixCandidate) => candidate.candidate_id);
          const totalPages = Math.max(1, Number(firstPage.total_pages) || 1);
          for (let pageNumber = 2; pageNumber <= totalPages; pageNumber += 1) {
            const response = await fetch(`/api/ipam/prefixes/interface-candidates?page=${pageNumber}&page_size=100&status=to_create`, { headers: authHeaders() });
            const pageData = await response.json().catch(() => ({}));
            if (!response.ok || !Array.isArray(pageData.candidates)) throw new Error(pageData?.detail || (zh ? '待创建候选已变化，请刷新后重试。' : 'Pending candidates changed. Refresh and retry.'));
            candidateIds.push(...pageData.candidates.map((candidate: InterfacePrefixCandidate) => candidate.candidate_id));
          }
        } catch (error) {
          setInterfaceGenerationError(error instanceof Error ? error.message : String(error));
          return;
        }
      }
      setInterfaceImportReviewRequest({
        candidate_ids: candidateIds,
        ...(Object.keys(addressSpaceOverrides).length > 0 ? { address_space_overrides: addressSpaceOverrides } : {}),
      });
      return;
    }
    setInterfaceGenerationLoading(true);
    setInterfaceGenerationError('');
    try {
      const requestBody = allPending
        ? { all_pending: true }
        : confirmedRequest;
      const res = await fetch('/api/ipam/prefixes/generate-from-interfaces', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...authHeaders(),
          'Idempotency-Key': getPendingRequestKey(pendingInterfaceGeneration, requestBody),
        },
        body: JSON.stringify(requestBody),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = res.status === 401
          ? (zh ? '登录已过期，请重新登录后重试。' : 'Your session has expired. Sign in and retry.')
          : res.status === 403
            ? (zh ? '当前账号没有生成 IPAM 网段的权限。' : 'You do not have permission to generate IPAM prefixes.')
            : data?.detail || (zh ? '生成前缀失败' : 'Prefix generation failed');
        throw new Error(message);
      }
      pendingInterfaceGeneration.current = null;
      setInterfaceImportReviewRequest(null);
      setInterfaceGenerationResult(
        zh
          ? `已创建 ${data.created_prefixes || 0} 个网段${data.updated_prefixes ? `、补齐同步 ${data.updated_prefixes} 个已有网段（网关/接口/VLAN）` : ''}，并登记 ${data.created_addresses || 0} 个接口 IP`
          : `Created ${data.created_prefixes || 0} prefixes${data.updated_prefixes ? `, synced ${data.updated_prefixes} existing prefixes` : ''}, and registered ${data.created_addresses || 0} interface IPs`,
      );
      setShowGenerateAllPendingConfirm(false);
      setSelectedInterfaceCandidates(new Set());
      setSelectedInterfaceCandidateSnapshots({});
      setSelectedInterfaceSpaces({});
      setBulkInterfaceSpaceId('');
      setBulkGlobalInterfaceSpaceId('');
      setInterfaceCandidateFilter('all');
      await loadData({ silent: true });
      await loadInterfaceCandidates(1, 'all');
    } catch (error) {
      setShowGenerateAllPendingConfirm(false);
      setInterfaceGenerationError(error instanceof Error ? error.message : String(error));
    } finally {
      setInterfaceGenerationLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    fetchLookups();
  }, [loadData, fetchLookups]);

  useEffect(() => {
    const requestId = ++gatewayCandidateRequestId.current;
    setGatewayCandidatesError('');
    if (!showAddEdit || !isValidGatewayCandidatePrefix(form.prefix)) {
      setGatewayCandidates(null);
      setGatewayCandidatesLoading(false);
      return undefined;
    }
    if (!form.site_id) {
      setGatewayCandidates({ status: 'needs_site', selected: null, endpoints: [] });
      setGatewayCandidatesLoading(false);
      if (gatewayBindingSourceRef.current === 'auto') {
        gatewayBindingSourceRef.current = 'none';
        setForm((current) => gatewayBindingSourceRef.current === 'manual'
          ? current
          : { ...current, gateway_device_id: '', gateway_interface_id: '' });
      }
      return undefined;
    }

    setGatewayCandidates(null);
    setGatewayCandidatesLoading(true);
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const query = buildGatewayCandidateQuery({
          prefix: form.prefix,
          siteId: form.site_id,
          gatewayIp: form.gateway,
          addressSpaceId: form.address_space_id,
        });
        const response = await fetch(`/api/ipam/prefixes/gateway-candidates?${query.toString()}`, {
          headers: authHeaders(),
          signal: controller.signal,
        });
        const data = await response.json().catch(() => ({})) as GatewayCandidateResponse & { detail?: unknown };
        if (requestId !== gatewayCandidateRequestId.current) return;
        if (!response.ok) {
          setGatewayCandidatesError(response.status === 401
            ? (zh ? '登录已过期，无法查询网关候选。' : 'Your session expired; gateway candidates could not be loaded.')
            : response.status === 403
              ? (zh ? '当前账号没有读取网关候选的权限。' : 'You do not have permission to read gateway candidates.')
              : (zh ? '读取网关候选失败，请稍后重试。' : 'Failed to load gateway candidates. Retry shortly.'));
          setGatewayCandidates(null);
          return;
        }

        const automaticBinding = getAutomaticGatewayBinding(
          gatewayBindingSourceRef.current,
          data,
          form.address_space_id,
        );
        const automaticEndpoint = automaticBinding
          ? data.selected?.device_id === automaticBinding.deviceId
            ? data.selected
            : (Array.isArray(data.endpoints) ? data.endpoints : []).find((endpoint) =>
              endpoint.device_id === automaticBinding.deviceId
              && (endpoint.interface_id || '') === automaticBinding.interfaceId)
          : null;
        setGatewayCandidates({
          status: automaticBinding && automaticEndpoint ? 'matched' : data.status,
          selected: automaticEndpoint || data.selected || null,
          endpoints: Array.isArray(data.endpoints) ? data.endpoints : [],
          gateway_ip: data.gateway_ip || null,
        });
        if (automaticBinding && automaticEndpoint) {
          gatewayBindingSourceRef.current = 'auto';
          setForm((current) => gatewayBindingSourceRef.current === 'manual'
            ? current
            : {
              ...current,
              gateway_device_id: automaticBinding.deviceId,
              gateway_interface_id: automaticBinding.interfaceId,
            });
        } else if (gatewayBindingSourceRef.current === 'auto') {
          gatewayBindingSourceRef.current = 'none';
          setForm((current) => gatewayBindingSourceRef.current === 'manual'
            ? current
            : { ...current, gateway_device_id: '', gateway_interface_id: '' });
        }
      } catch (error) {
        if (controller.signal.aborted || requestId !== gatewayCandidateRequestId.current) return;
        setGatewayCandidatesError(zh ? '查询网关候选时发生网络错误。' : 'A network error occurred while loading gateway candidates.');
        setGatewayCandidates(null);
      } finally {
        if (requestId === gatewayCandidateRequestId.current) setGatewayCandidatesLoading(false);
      }
    }, 250);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [showAddEdit, form.prefix, form.site_id, form.gateway, form.address_space_id, authHeaders, zh]);

  // Tree mode support
  const [treeData, setTreeData] = useState<Prefix[]>([]);
  useEffect(() => {
    if (viewMode === 'tree' && search === '') {
      fetch('/api/ipam/subnets/tree', { headers: authHeaders() })
        .then((res) => (res.ok ? res.json() : []))
        .then((data) => setTreeData(data))
        .catch((err) => console.error(err));
    }
  }, [viewMode, search, authHeaders]);

  // Open Create/Edit Form
  const NETWORK_TYPES: Record<string, { label: string; labelZh: string; color: string }> = {
    management: { label: 'Management', labelZh: '管理网', color: 'bg-amber-50 text-amber-600 border-amber-500/10' },
    server: { label: 'Server', labelZh: '服务器网', color: 'bg-blue-50 text-blue-600 border-blue-500/10' },
    user: { label: 'User Access', labelZh: '办公/用户网', color: 'bg-violet-50 text-violet-600 border-violet-500/10' },
    user_access: { label: 'User Access', labelZh: '办公/用户网', color: 'bg-violet-50 text-violet-600 border-violet-500/10' },
    network_service: { label: 'Network Service', labelZh: '网络服务', color: 'bg-cyan-50 text-cyan-600 border-cyan-500/10' },
    unclassified: { label: 'Unclassified', labelZh: '用途未确定', color: 'bg-slate-50 text-slate-600 border-slate-500/10' },
    wireless: { label: 'Wireless', labelZh: '无线网', color: 'bg-sky-50 text-sky-600 border-sky-500/10' },
    voice: { label: 'Voice', labelZh: '语音网', color: 'bg-fuchsia-50 text-fuchsia-600 border-fuchsia-500/10' },
    dmz: { label: 'DMZ', labelZh: 'DMZ隔离', color: 'bg-orange-50 text-orange-600 border-orange-500/10' },
    transit: { label: 'Transit', labelZh: '设备互联', color: 'bg-teal-50 text-teal-600 border-teal-500/10' },
    loopback: { label: 'Loopback', labelZh: 'Loopback', color: 'bg-gray-50 text-gray-600 border-gray-500/10' },
    wan: { label: 'WAN', labelZh: 'WAN骨干', color: 'bg-rose-50 text-rose-600 border-rose-500/10' },
    vpn: { label: 'VPN', labelZh: 'VPN', color: 'bg-purple-50 text-purple-600 border-purple-500/10' },
    storage: { label: 'Storage', labelZh: '存储网', color: 'bg-indigo-50 text-indigo-600 border-indigo-500/10' },
    vip: { label: 'VIP', labelZh: 'VIP业务', color: 'bg-pink-50 text-pink-600 border-pink-500/10' },
    p2p: { label: 'Point-to-Point', labelZh: '点对点', color: 'bg-cyan-50 text-cyan-600 border-cyan-500/10' },
    container: { label: 'Container/K8s', labelZh: '容器网', color: 'bg-emerald-50 text-emerald-600 border-emerald-500/10' },
  };

  const openForm = (prefixItem: Prefix | null = null) => {
    pendingCreateRequest.current = null;
    gatewayCandidateRequestId.current += 1;
    setGatewayCandidates(null);
    setGatewayCandidatesError('');
    setGatewayCandidatesLoading(false);
    setErrorMsg('');
    setParentSubnetId('');
    setDesiredPrefixLen(24);
    setShowSubnetRecommendation(false);
    setShowIpPlanningHelper(false);
    setIsSaving(false);
    setExcludeNetBroadcast(true);
    setExcludeGateway(true);
    if (prefixItem) {
      gatewayBindingSourceRef.current = prefixItem.gateway_device_id || prefixItem.gateway_interface_id ? 'manual' : 'none';
      setEditingPrefix(prefixItem);
      setForm({
        prefix: prefixItem.prefix,
        name: prefixItem.name || '',
        vrf_id: prefixItem.vrf_id || '',
        address_space_id: prefixItem.address_space_id || '',
        vlan_id: prefixItem.vlan_id ? String(prefixItem.vlan_id) : '',
        site_id: prefixItem.site_id || '',
        status: prefixItem.status || 'active',
        gateway: prefixItem.gateway || '',
        description: prefixItem.description || '',
        network_type: prefixItem.network_type === 'user' ? 'user_access' : (prefixItem.network_type || DEFAULT_NEW_PREFIX_NETWORK_TYPE),
        gateway_device_id: prefixItem.gateway_device_id || '',
        gateway_interface_id: prefixItem.gateway_interface_id || '',
        traceable: prefixItem.traceable ?? 1,
      });
    } else {
      gatewayBindingSourceRef.current = 'none';
      setEditingPrefix(null);
      setForm({
        prefix: '',
        name: '',
        vrf_id: '',
        address_space_id: '',
        vlan_id: '',
        site_id: '',
        status: 'active',
        gateway: '',
        description: '',
        network_type: DEFAULT_NEW_PREFIX_NETWORK_TYPE,
        gateway_device_id: '',
        gateway_interface_id: '',
        traceable: 1,
      });
    }
    setShowAddEdit(true);
  };

  const createGlobalAddressSpace = async (selectInPrefixForm = true) => {
    const name = globalSpaceName.trim();
    if (!name || globalSpaceCreating) return;
    setAddressSpacesError('');
    setGlobalSpaceCreating(true);
    try {
      const response = await fetch('/api/ipam/address-spaces', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ name, kind: 'global' }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = typeof data?.detail === 'string' ? data.detail : data?.detail?.message;
        throw new Error(response.status === 403
          ? (zh ? '当前账号没有创建地址空间的权限。' : 'You do not have permission to create address spaces.')
          : detail || (zh ? '创建全局地址空间失败。' : 'Failed to create global address space.'));
      }
      const created = data?.item || data;
      if (!created?.id) throw new Error(zh ? '服务端未返回地址空间 ID。' : 'The server did not return an address-space ID.');
      const createdSpace: AddressSpace = {
        ...created,
        id: String(created.id),
        name: String(created.name || name),
        kind: 'global',
        vrf_id: null,
        vrf_name: null,
        security_tenant_id: String(created.security_tenant_id || ''),
        status: String(created.status || 'active'),
        revision: Number(created.revision || 1),
      };
      let refreshedSpaces = [...addressSpaces.filter((item) => item.id !== createdSpace.id), createdSpace];
      try {
        const refreshResponse = await fetch('/api/ipam/address-spaces', { headers: authHeaders() });
        if (refreshResponse.ok) {
          const refreshData = await refreshResponse.json().catch(() => ({}));
          const returnedSpaces = Array.isArray(refreshData) ? refreshData : refreshData?.items;
          if (Array.isArray(returnedSpaces)) {
            refreshedSpaces = returnedSpaces.some((item: AddressSpace) => item.id === createdSpace.id)
              ? returnedSpaces
              : [...returnedSpaces, createdSpace];
          }
        } else {
          setAddressSpacesError(refreshResponse.status === 403
            ? (zh ? '地址空间已创建，但当前账号不能刷新地址空间列表。' : 'The address space was created, but you cannot refresh the list.')
            : (zh ? '地址空间已创建，但刷新列表失败。' : 'The address space was created, but refreshing the list failed.'));
        }
      } catch {
        setAddressSpacesError(zh ? '地址空间已创建，但刷新列表失败。' : 'The address space was created, but refreshing the list failed.');
      }
      setAddressSpaces(refreshedSpaces);
      if (selectInPrefixForm) setForm((current) => ({ ...current, address_space_id: createdSpace.id, vrf_id: '' }));
      else if (scopeResolutionPrefix) {
        setScopeResolutionSpaceId(createdSpace.id);
        setScopeResolutionPreview(null);
        setScopeResolutionConfirmed(false);
        setScopeResolutionError('');
      } else if (showBatchAddressSpaceModal) {
        setBatchAddressSpaceTargetId(createdSpace.id);
        setBatchAddressSpacePreview(null);
        setBatchAddressSpaceConfirmed(false);
        setBatchAddressSpaceError('');
      }
      setGlobalSpaceName('');
    } catch (error) {
      setAddressSpacesError(error instanceof Error ? error.message : String(error));
    } finally {
      setGlobalSpaceCreating(false);
    }
  };

  const openAddressSpaceResolution = (prefix: Prefix) => {
    setScopeResolutionMode('resolve');
    setScopeResolutionPrefix(prefix);
    setScopeResolutionSpaceId('');
    setScopeResolutionPreview(null);
    setScopeResolutionConfirmed(false);
    setScopeResolutionError('');
  };

  const openAddressSpaceMove = (prefix: Prefix) => {
    setScopeResolutionMode('move');
    setScopeResolutionPrefix(prefix);
    setScopeResolutionSpaceId('');
    setScopeResolutionPreview(null);
    setScopeResolutionConfirmed(false);
    setScopeResolutionError('');
  };

  const openBatchAddressSpaceResolution = () => {
    if (selectedIds.size === 0) return;
    setBatchAddressSpaceTargetId('');
    setBatchAddressSpacePreview(null);
    setBatchAddressSpaceConfirmed(false);
    setBatchAddressSpaceError('');
    setShowBatchAddressSpaceModal(true);
  };

  useEffect(() => {
    if (!scopeResolutionPrefix || !scopeResolutionSpaceId) {
      setScopeResolutionPreview(null);
      setScopeResolutionLoading(false);
      return undefined;
    }
    const controller = new AbortController();
    setScopeResolutionLoading(true);
    setScopeResolutionError('');
    const query = new URLSearchParams({ address_space_id: scopeResolutionSpaceId });
    const previewPath = scopeResolutionMode === 'move'
      ? 'address-space-move-preview'
      : 'address-space-preview';
    fetch(`/api/ipam/subnets/${encodeURIComponent(scopeResolutionPrefix.id)}/${previewPath}?${query.toString()}`, {
      headers: authHeaders(),
      signal: controller.signal,
    })
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(response.status === 401
            ? (zh ? '登录已过期，请重新登录后重试。' : 'Your session has expired. Sign in and retry.')
            : response.status === 403
              ? (zh ? '当前账号没有查看此网段归属的权限。' : 'You do not have permission to review this prefix.')
              : data?.detail || (zh ? '无法预览地址空间映射。' : 'Unable to preview address-space mapping.'));
        }
        setScopeResolutionPreview(data);
      })
      .catch((error) => {
        if (error?.name !== 'AbortError') {
          setScopeResolutionPreview(null);
          setScopeResolutionError(error instanceof Error ? error.message : String(error));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setScopeResolutionLoading(false);
      });
    return () => controller.abort();
  }, [scopeResolutionPrefix, scopeResolutionSpaceId, scopeResolutionMode, authHeaders, zh]);

  useEffect(() => {
    if (!showBatchAddressSpaceModal || !batchAddressSpaceTargetId) {
      setBatchAddressSpacePreview(null);
      setBatchAddressSpaceLoading(false);
      return undefined;
    }
    const ids = Array.from(selectedIds);
    if (ids.length === 0 || ids.length > 100) {
      setBatchAddressSpacePreview(null);
      setBatchAddressSpaceError(ids.length > 100
        ? (zh ? '一次最多批量处理 100 个网段，请缩小选择范围。' : 'Select no more than 100 prefixes per batch.')
        : (zh ? '请先选择网段。' : 'Select prefixes first.'));
      setBatchAddressSpaceLoading(false);
      return undefined;
    }
    const controller = new AbortController();
    setBatchAddressSpaceLoading(true);
    setBatchAddressSpaceError('');
    fetch('/api/ipam/subnets/address-space-batch-preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ ids, address_space_id: batchAddressSpaceTargetId }),
      signal: controller.signal,
    })
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          const detail = typeof data?.detail === 'string' ? data.detail : '';
          throw new Error(response.status === 401
            ? (zh ? '登录已过期，请重新登录后重试。' : 'Your session has expired. Sign in and retry.')
            : response.status === 403
              ? (zh ? '当前账号没有查看全部所选网段的权限。' : 'You do not have permission to review every selected prefix.')
              : detail || (zh ? '无法预览批量地址空间映射。' : 'Unable to preview the batch address-space mapping.'));
        }
        setBatchAddressSpacePreview(data as AddressSpaceBatchResolutionPreview);
        setBatchAddressSpaceConfirmed(false);
      })
      .catch((error) => {
        if (error?.name !== 'AbortError') {
          setBatchAddressSpacePreview(null);
          setBatchAddressSpaceConfirmed(false);
          setBatchAddressSpaceError(error instanceof Error ? error.message : String(error));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setBatchAddressSpaceLoading(false);
      });
    return () => controller.abort();
  }, [showBatchAddressSpaceModal, batchAddressSpaceTargetId, selectedIds, authHeaders, zh]);

  const resolveAddressSpace = async () => {
    if (!scopeResolutionPrefix || !scopeResolutionPreview?.can_confirm || !scopeResolutionConfirmed || scopeResolutionSaving) return;
    setScopeResolutionSaving(true);
    setScopeResolutionError('');
    try {
      const operationPath = scopeResolutionMode === 'move'
        ? 'move-address-space'
        : 'resolve-address-space';
      const response = await fetch(`/api/ipam/subnets/${encodeURIComponent(scopeResolutionPrefix.id)}/${operationPath}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          address_space_id: scopeResolutionSpaceId,
          expected_revision: scopeResolutionPrefix.revision,
          expected_updated_at: scopeResolutionPreview.expected_updated_at,
          confirmed: true,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(response.status === 401
          ? (zh ? '登录已过期，请重新登录后重试。' : 'Your session has expired. Sign in and retry.')
          : response.status === 403
            ? (zh ? '当前账号没有修改此网段归属的权限。' : 'You do not have permission to change this prefix scope.')
            : data?.detail || (zh
              ? (scopeResolutionMode === 'move' ? '迁移地址空间失败。请刷新预览并重试。' : '确认地址空间失败。请刷新预览并重试。')
              : (scopeResolutionMode === 'move' ? 'Address-space move failed. Refresh the preview and retry.' : 'Address-space resolution failed. Refresh the preview and retry.')));
      }
      setScopeResolutionPrefix(null);
      await loadData({ silent: true });
      if (viewMode === 'tree' && !search) {
        const treeResponse = await fetch('/api/ipam/subnets/tree', { headers: authHeaders() });
        if (treeResponse.ok) setTreeData(await treeResponse.json());
      }
    } catch (error) {
      setScopeResolutionError(error instanceof Error ? error.message : String(error));
    } finally {
      setScopeResolutionSaving(false);
    }
  };

  const resolveBatchAddressSpace = async () => {
    const preview = batchAddressSpacePreview;
    if (
      !preview?.can_confirm
      || !preview.expected_target_revision
      || !batchAddressSpaceConfirmed
      || batchAddressSpaceSaving
      || preview.items.length !== selectedIds.size
    ) return;
    setBatchAddressSpaceSaving(true);
    setBatchAddressSpaceError('');
    try {
      const response = await fetch('/api/ipam/subnets/address-space-batch-resolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          address_space_id: batchAddressSpaceTargetId,
          expected_target_revision: preview.expected_target_revision,
          items: preview.items.map((item) => ({
            prefix_id: item.prefix_id,
            expected_updated_at: item.expected_updated_at,
            expected_revision: item.expected_revision,
          })),
          confirmed: true,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = typeof data?.detail === 'string' ? data.detail : '';
        throw new Error(response.status === 401
          ? (zh ? '登录已过期，请重新登录后重试。' : 'Your session has expired. Sign in and retry.')
          : response.status === 403
            ? (zh ? '当前账号没有修改全部所选网段的权限。' : 'You do not have permission to update every selected prefix.')
            : detail || (zh ? '批量修改地址空间失败；没有提交部分结果，请刷新预览后重试。' : 'Batch mapping failed; no partial changes were committed. Refresh the preview and retry.'));
      }
      const updatedCount = Number(data?.updated || preview.items.length);
      const targetName = String(data?.address_space_name || preview.target_space?.name || '');
      setBatchAddressSpaceResult(zh
        ? `已将 ${updatedCount} 个网段映射到 ${targetName}。`
        : `Mapped ${updatedCount} prefixes to ${targetName}.`);
      setShowBatchAddressSpaceModal(false);
      setSelectedIds(new Set());
      setSelectedRevisions({});
      await loadData({ silent: true });
      if (viewMode === 'tree' && !search) {
        const treeResponse = await fetch('/api/ipam/subnets/tree', { headers: authHeaders() });
        if (treeResponse.ok) setTreeData(await treeResponse.json());
      }
    } catch (error) {
      setBatchAddressSpaceError(error instanceof Error ? error.message : String(error));
    } finally {
      setBatchAddressSpaceSaving(false);
    }
  };

  const handleGetSuggestedPrefix = async () => {
    setErrorMsg('');
    if (!parentSubnetId) {
      setErrorMsg(zh ? '请先选择父网段' : 'Please select a parent prefix');
      return;
    }
    try {
      const res = await fetch(`/api/ipam/subnets/${parentSubnetId}/next-available-prefix?prefix_len=${desiredPrefixLen}`, { headers: authHeaders() });
      if (res.ok) {
        const data = await res.json();
        setForm((prev) => ({ ...prev, prefix: data.next_available_prefix }));
      } else {
        const err = await res.json().catch(() => null);
        setErrorMsg(err?.detail || (zh ? '无法获取推荐子网，父网段容量可能已满或存在冲突。' : 'Failed to fetch suggested prefix. Parent subnet might be full or conflicting.'));
      }
    } catch (e) {
      setErrorMsg(zh ? '获取推荐子网出错' : 'Error fetching suggested prefix');
    }
  };

  const handleSave = async () => {
    if (isSaving) return;
    setErrorMsg('');
    if (!form.prefix) {
      setErrorMsg(zh ? 'Prefix网段是必填项' : 'Prefix CIDR is required');
      return;
    }
    if (!editingPrefix && !form.address_space_id) {
      setErrorMsg(zh ? '请选择明确的地址空间；不能根据站点或空 VRF 自动推断。' : 'Select an explicit address space. Site or an empty VRF cannot determine it.');
      return;
    }

    const payload = {
      ...form,
      vrf_id: addressSpaces.find((space) => space.id === form.address_space_id)?.vrf_id || null,
      vlan_id: form.vlan_id ? form.vlan_id : null,
      site_id: form.site_id || null,
      tenant_id: DEFAULT_TENANT_ID,
      gateway_device_id: form.gateway_device_id || null,
      gateway_interface_id: form.gateway_interface_id || null,
      ...(editingPrefix ? { expected_revision: editingPrefix.revision } : {}),
    };
    if (editingPrefix) {
      delete (payload as Partial<typeof payload>).address_space_id;
      delete (payload as Partial<typeof payload>).vrf_id;
    }

    setIsSaving(true);
    try {
      const url = editingPrefix ? `/api/ipam/subnets/${editingPrefix.id}` : '/api/ipam/subnets';
      const method = editingPrefix ? 'PUT' : 'POST';
      const res = await fetch(url, {
        method,
        headers: {
          'Content-Type': 'application/json',
          ...authHeaders(),
          ...(!editingPrefix ? { 'Idempotency-Key': getPendingRequestKey(pendingCreateRequest, payload) } : {}),
        },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        if (!editingPrefix) pendingCreateRequest.current = null;
        setShowAddEdit(false);
        await loadData({ silent: true });
      } else {
        const err = await res.json().catch(() => ({}));
        const detailText = Array.isArray(err.detail)
          ? err.detail.map((item: any) => item?.msg || JSON.stringify(item)).join('；')
          : typeof err.detail === 'string'
            ? err.detail
            : (err.detail ? JSON.stringify(err.detail) : '');
        setErrorMsg(res.status === 401
          ? (zh ? '登录已过期，请重新登录后重试。' : 'Your session has expired. Sign in and retry.')
          : res.status === 403
            ? (zh ? '当前账号没有保存网段的权限。' : 'You do not have permission to save this prefix.')
            : detailText || (zh ? `保存失败 (HTTP ${res.status})` : `Operation failed (HTTP ${res.status})`));
      }
    } catch (e) {
      setErrorMsg(zh ? '网络请求出错' : 'Network request error');
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    const prefix = prefixes.find((item) => item.id === id) || findPrefixInTree(treeData, id);
    if (!prefix) return;
    try {
      const query = new URLSearchParams({ expected_revision: String(prefix.revision) });
      const res = await fetch(`/api/ipam/subnets/${encodeURIComponent(id)}?${query.toString()}`, {
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

  const handleBatchDelete = async () => {
    const expectedRevisions = Object.fromEntries(Array.from(selectedIds, (id) => [id, selectedRevisions[id]]));
    try {
      const res = await fetch('/api/ipam/subnets/batch-delete', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...authHeaders(),
        },
        body: JSON.stringify({ ids: Array.from(selectedIds), expected_revisions: expectedRevisions }),
      });
      if (res.ok) {
        setSelectedIds(new Set());
        setSelectedRevisions({});
        setShowBatchDeleteConfirm(false);
        loadData();
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleBatchNetworkTypeUpdate = async () => {
    if (batchNetworkTypeUpdating || selectedIds.size === 0) return;
    setBatchNetworkTypeError('');
    setBatchNetworkTypeResult('');
    setBatchNetworkTypeUpdating(true);
    const selectedCount = selectedIds.size;
    const expectedRevisions = Object.fromEntries(Array.from(selectedIds, (id) => [id, selectedRevisions[id]]));
    try {
      const response = await fetch('/api/ipam/subnets/batch-update-network-type', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...authHeaders(),
        },
        body: JSON.stringify({
          ids: Array.from(selectedIds),
          expected_revisions: expectedRevisions,
          network_type: batchNetworkType,
        }),
      });
      const data = await response.json().catch(() => ({})) as { detail?: unknown };
      if (!response.ok) {
        const detail = typeof data.detail === 'string' ? data.detail.trim().slice(0, 300) : '';
        setBatchNetworkTypeError(response.status === 401
          ? (zh ? '登录已过期，请重新登录后重试。' : 'Your session has expired. Sign in and retry.')
          : response.status === 403
            ? (zh ? '当前账号没有批量修改网段用途的权限。' : 'You do not have permission to batch update prefix purposes.')
            : detail || (zh ? '批量修改网段用途失败，请检查所选记录后重试。' : 'Batch purpose update failed. Review the selected prefixes and retry.'));
        return;
      }

      setSelectedIds(new Set());
      setSelectedRevisions({});
      setShowBatchNetworkTypeModal(false);
      setBatchNetworkTypeResult(zh ? `已将 ${selectedCount} 个网段设为人工保护。` : `${selectedCount} prefixes were updated and protected from automatic classification.`);
      await loadData({ silent: true });
    } catch {
      setBatchNetworkTypeError(zh ? '网络请求失败，所选网段未更新，请重试。' : 'The request failed; selected prefixes were not updated. Retry.');
    } finally {
      setBatchNetworkTypeUpdating(false);
    }
  };

  const [confirmApplySuggestions, setConfirmApplySuggestions] = useState(false);
  const [applyingSuggestions, setApplyingSuggestions] = useState(false);
  const [suggestionApplyError, setSuggestionApplyError] = useState('');
  const suggestedPrefixes = prefixes.filter((item) => item.suggested_network_type && !item.manual_override
    && (!item.network_type || item.network_type === 'unclassified'));
  const suggestionGroups = suggestedPrefixes.reduce<Record<string, Prefix[]>>((groups, item) => {
    const key = String(item.suggested_network_type);
    (groups[key] = groups[key] || []).push(item);
    return groups;
  }, {});
  const suggestionReasonLabel = (reason?: string) => {
    if (reason === 'device_management_ip') return zh ? '网段内地址是 CMDB 设备的管理 IP' : 'Contains a CMDB device management IP';
    if (reason === 'loopback_interface') return zh ? '网段内地址都配置在 Loopback 接口上' : 'All addresses are on loopback interfaces';
    if (reason === 'point_to_point_mask') return zh ? '/30、/31 掩码，典型的设备互联链路' : '/30 or /31 mask: a point-to-point link';
    return '';
  };

  const handleApplySuggestions = async () => {
    if (applyingSuggestions || suggestedPrefixes.length === 0) return;
    setApplyingSuggestions(true);
    setBatchNetworkTypeResult('');
    setSuggestionApplyError('');
    let applied = 0;
    const failures: string[] = [];
    try {
      for (const [networkType, items] of Object.entries(suggestionGroups)) {
        const type = NETWORK_TYPES[networkType];
        const label = (zh ? type?.labelZh : type?.label) || networkType;
        try {
          const response = await fetch('/api/ipam/subnets/batch-update-network-type', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...authHeaders() },
            body: JSON.stringify({
              ids: items.map((item) => item.id),
              expected_revisions: Object.fromEntries(items.map((item) => [item.id, item.revision])),
              network_type: networkType,
            }),
          });
          if (response.ok) {
            applied += items.length;
          } else {
            const data = await response.json().catch(() => ({})) as { detail?: unknown };
            failures.push(`${label} · ${typeof data.detail === 'string' ? data.detail.slice(0, 120) : `HTTP ${response.status}`}`);
          }
        } catch {
          failures.push(zh ? `${label} · 连接中断，提交结果待确认` : `${label} · Connection interrupted. Update result unconfirmed.`);
        }
      }
      setConfirmApplySuggestions(false);
      await loadData({ silent: true });
      if (applied > 0) {
        setBatchNetworkTypeResult(zh ? `已采纳推荐用途：${applied} 个网段（已人工锁定，可随时在“管理”中修改）。` : `Applied suggested purposes to ${applied} prefixes.`);
      }
      if (failures.length > 0) {
        setSuggestionApplyError((zh ? '请核对以下用途组：' : 'Review these purpose groups: ') + failures.join('；'));
      }
    } finally {
      setApplyingSuggestions(false);
    }
  };

  // Toggle selection
  const toggleSelectRow = (id: string) => {
    setBatchNetworkTypeResult('');
    setBatchAddressSpaceResult('');
    const next = new Set(selectedIds);
    const isSelected = next.has(id);
    if (isSelected) next.delete(id);
    else next.add(id);
    setSelectedIds(next);
    setSelectedRevisions((current) => {
      const revisions = { ...current };
      if (isSelected) delete revisions[id];
      else {
        const prefix = prefixes.find((item) => item.id === id);
        if (prefix) revisions[id] = prefix.revision;
      }
      return revisions;
    });
  };

  const toggleSelectAll = () => {
    setBatchNetworkTypeResult('');
    setBatchAddressSpaceResult('');
    const next = toggleVisiblePrefixSelection(selectedIds, visiblePrefixIds);
    setSelectedIds(next);
    setSelectedRevisions((current) => {
      const revisions = { ...current };
      visiblePrefixIds.forEach((id) => {
        if (!next.has(id)) delete revisions[id];
        else {
          const prefix = prefixes.find((item) => item.id === id);
          if (prefix) revisions[id] = prefix.revision;
        }
      });
      return revisions;
    });
  };

  // IPv4 / IPv6 family filter (an IPv6 prefix always contains a colon)
  const matchFamily = useCallback(
    (p: Prefix) => {
      if (familyFilter === 'all') return true;
      const isV6 = (p.prefix || '').includes(':');
      return familyFilter === 'ipv6' ? isV6 : !isV6;
    },
    [familyFilter],
  );
  const paginatedPrefixes = prefixes;
  const visiblePrefixIds = paginatedPrefixes
    .filter((prefix) => !collapsedSites[String(prefix.site_id || 'unassigned')])
    .map((prefix) => prefix.id);

  const exportData = useCallback(async () => {
    const table = viewMode === 'tree' ? treeTableRef.current : prefixTableRef.current;
    let allPrefixes: Prefix[];
    if (viewMode === 'tree') {
      const flatten = (prefix: Prefix): Prefix[] => [prefix, ...(prefix.children || []).flatMap(flatten)];
      allPrefixes = treeData.filter(matchFamily).flatMap(flatten);
    } else {
      const params = buildPrefixListQuery({
        q: search,
        site: siteFilter,
        status: statusFilter,
        family: familyFilter,
        page: 1,
        pageSize,
        classification: classificationFilter,
      });
      allPrefixes = await fetchAllIpamExportItems<Prefix>('/api/ipam/subnets', params);
    }

    const roleText = (prefix: Prefix) => {
      const networkType = NETWORK_TYPES[prefix.network_type || ''] || NETWORK_TYPES.unclassified;
      const addressRoles = parseAddressRoles(prefix.address_roles_json);
      const labels = [zh ? networkType.labelZh : networkType.label];
      if (addressRoles.some((role) => role.address_role && role.address_role !== 'dhcp_lease')) labels.push('VIP');
      if (addressRoles.some((role) => role.address_role === 'dhcp_lease')) labels.push('DHCP');
      if (viewMode !== 'tree') {
        if (prefix.manual_override) labels.push(zh ? '人工' : 'Manual');
        if (prefix.mixed_network) labels.push(zh ? '混合' : 'Mixed');
        if (prefix.conflict_status) labels.push(zh ? '冲突' : 'Conflict');
        if (prefix.cross_site_reuse) labels.push(zh ? '跨站点复用（同租户同 CIDR）' : 'Cross-site reuse (same tenant/CIDR)');
      }
      return labels.join(' · ');
    };

    return buildVisibleIpamExportData(table, [
      { header: zh ? 'Prefix网段' : 'Prefix / CIDR', value: (prefix) => prefix.prefix },
      { header: zh ? '网段名称' : 'Name', value: (prefix) => prefix.name || '-' },
      { header: zh ? '用途' : 'Role', value: roleText },
      { header: zh ? '网络归属' : 'Network ownership', value: (prefix) => prefixAddressSpaceLabel(prefix, zh) },
      { header: zh ? '所属VLAN' : 'VLAN', value: (prefix) => prefix.vlan_id ? `VLAN ${prefix.vlan_id}` : '-' },
      { header: zh ? '网关IP' : 'Gateway IP', value: (prefix) => prefix.gateway || '-' },
      { header: zh ? '网关设备' : 'Gateway Device', value: (prefix) => prefix.gateway_device_name || '-' },
      { header: zh ? '物理站点' : 'Site', value: (prefix) => prefix.site_name || prefix.site_code || '-' },
      { header: zh ? '创建时间' : 'Created At', value: (prefix) => formatPrefixTimestamp(prefix.created_at, language) },
      { header: zh ? '网段状态' : 'Status', value: (prefix) => prefixStatusLabel(prefix.status, zh) },
      { header: zh ? '已分配IP数' : 'Allocated IPs', value: (prefix) => prefix.used_ips ?? 0 },
      { header: zh ? '保留/不可分配IP数' : 'Reserved / Blocked IPs', value: (prefix) => prefix.reserved_ips ?? 0 },
      { header: zh ? '实际可分配IP数' : 'Allocatable Free IPs', value: (prefix) => prefix.allocatable_free_ips ?? Math.max(0, (prefix.total_ips ?? 0) - (prefix.used_ips ?? 0)) },
      { header: zh ? '活跃发现IP数' : 'Active Discovery IPs', value: (prefix) => prefix.active_ips ?? 0 },
      { header: zh ? '可用容量' : 'Usable Capacity', value: (prefix) => prefix.total_ips ?? 0 },
      { header: zh ? '利用率' : 'Utilization', value: (prefix) => `${prefix.utilization ?? 0}%` },
      { header: zh ? '实际占用率' : 'Effective Utilization', value: (prefix) => `${prefix.effective_utilization ?? prefix.utilization ?? 0}%` },
    ], allPrefixes);
  }, [viewMode, treeData, matchFamily, search, siteFilter, statusFilter, familyFilter, classificationFilter, pageSize, zh, language]);

  const classificationCards = classificationSummary ? [
    { key: 'unclassified', label: zh ? '用途未确定' : 'Purpose unconfirmed', value: classificationSummary.unclassified_count, tone: 'text-slate-700 bg-slate-100' },
    { key: 'mixed', label: zh ? '混合网段' : 'Mixed', value: classificationSummary.mixed_count, tone: 'text-amber-700 bg-amber-50' },
    { key: 'conflict', label: zh ? '地址冲突' : 'Address conflicts', value: classificationSummary.conflict_count, tone: 'text-rose-700 bg-rose-50' },
    { key: 'reuse', label: zh ? '跨站点复用' : 'Cross-site reuse', value: classificationSummary.reuse_count ?? 0, tone: 'text-blue-700 bg-blue-50' },
    { key: 'stale', label: zh ? '已老化' : 'Stale', value: classificationSummary.stale_count, tone: 'text-gray-600 bg-gray-100' },
  ] as const : [];
  const classificationMethodCards = classificationSummary ? [
    { key: 'auto', label: zh ? '系统维护' : 'System maintained', value: classificationSummary.auto_count, tone: 'text-cyan-700 bg-cyan-50' },
    { key: 'manual', label: zh ? '人工锁定' : 'Manually locked', value: classificationSummary.manual_count, tone: 'text-violet-700 bg-violet-50' },
  ] as const : [];
  const activeClassificationLabel = [...classificationCards, ...classificationMethodCards]
    .find((item) => item.key === classificationFilter)?.label || '';
  const handleClassificationCardClick = (classification: PrefixClassificationCategory) => {
    setClassificationFilter((current) => togglePrefixClassificationFilter(current, classification));
    setPage(1);
    setViewMode('table');
  };

  const flattenedTreeRows = useMemo(() => {
    const rows: Array<{ node: Prefix; depth: number }> = [];
    const visit = (node: Prefix, depth: number) => {
      rows.push({ node, depth });
      if (node.children && node.children.length > 0) {
        for (const child of node.children) {
          visit(child, depth + 1);
        }
      }
    };
    for (const root of treeData.filter(matchFamily)) {
      visit(root, 0);
    }
    return rows;
  }, [treeData, matchFamily]);

  const shouldVirtualizeTree = viewMode === 'tree' && flattenedTreeRows.length > 80;
  const treeRowVirtualizer = useVirtualizer({
    count: shouldVirtualizeTree ? flattenedTreeRows.length : 0,
    getScrollElement: () => tableScrollContainerRef.current,
    estimateSize: () => 56,
    overscan: 12,
  });

  // Single tree row renderer (flattened for optional @tanstack/react-virtual virtualization)
  const renderTreeRow = (node: Prefix, depth = 0) => {
    return (
        <tr key={node.id} className="hover:bg-gray-50/50 transition-colors border-b border-gray-100 group">
          <td className="pl-6 py-4">
            <div className="flex items-center gap-2" style={{ paddingLeft: `${depth * 24}px` }}>
              <GitBranch size={14} className="text-gray-300 flex-shrink-0" />
              <button
                onClick={() => navigate(`/ipam/ips?prefix_id=${node.id}`)}
                className="text-sm font-semibold text-cyan-600 hover:text-cyan-700 hover:underline"
              >
                {node.prefix}
              </button>
            </div>
          </td>
          <td className="px-4 py-4 text-xs font-semibold text-gray-500">{node.name || node.prefix}</td>
          <td className="px-4 py-4">
            {(() => {
              const nt = NETWORK_TYPES[node.network_type] || NETWORK_TYPES['unclassified'];
              const addressRoles = parseAddressRoles(node.address_roles_json);
              const hasVip = addressRoles.some((role) => role.address_role && role.address_role !== 'dhcp_lease');
              const hasDhcp = addressRoles.some((role) => role.address_role === 'dhcp_lease');
              return (
                <div className="flex flex-wrap gap-1 items-center">
                <span className={`whitespace-nowrap px-2 py-0.5 rounded-full text-[10px] font-bold border ${nt.color}`}>
                    {zh ? nt.labelZh : nt.label}
                  </span>
                {hasVip ? <span className="whitespace-nowrap px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-pink-50 text-pink-700 border border-pink-200">VIP</span> : null}
                {hasDhcp ? <span className="whitespace-nowrap px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-sky-50 text-sky-700 border border-sky-200">DHCP</span> : null}
                </div>
              );
            })()}
          </td>
          <td className="px-4 py-4 text-xs font-medium">
            <PrefixNetworkOwnershipCell prefix={node} zh={zh} />
          </td>
          <td className="px-4 py-4">
            {node.vlan_id ? (
              <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-indigo-50 text-indigo-600 border border-indigo-500/10">
                VLAN {node.vlan_id}
              </span>
            ) : (
              '-'
            )}
          </td>
          <td className="px-4 py-4 text-xs font-mono font-bold text-gray-700">{node.gateway || '-'}</td>
          <td className="px-4 py-4 text-xs text-gray-600 font-medium">{node.gateway_device_name || '-'}</td>
          <td className="px-4 py-4 text-xs text-gray-600 font-semibold">{node.site_name || node.site_code || '-'}</td>
          <td className="px-4 py-4 text-xs text-gray-500 whitespace-nowrap">{formatPrefixTimestamp(node.created_at, language)}</td>
          <td className="px-4 py-4">
            <span className={`inline-flex items-center gap-1.5 whitespace-nowrap px-2.5 py-0.5 rounded-full text-[10px] font-bold ${
              node.status === 'active' 
                ? 'bg-emerald-50 text-emerald-600 border border-emerald-500/10' 
                : node.status === 'reserved' 
                ? 'bg-amber-50 text-amber-600 border border-amber-500/10' 
                : 'bg-rose-50 text-rose-600 border border-rose-500/10'
            }`}>
              <span className={`w-1.5 h-1.5 rounded-full ${
                node.status === 'active' ? 'bg-emerald-500' : node.status === 'reserved' ? 'bg-amber-500' : 'bg-rose-500'
              }`} />
              {prefixStatusLabel(node.status, zh)}
            </span>
          </td>
          <td className="px-4 py-4 text-xs text-gray-600 tabular-nums">{node.used_ips}</td>
          <td className="px-4 py-4 text-xs text-gray-600 tabular-nums" title={zh ? `ARP/ND 当前观察到 ${node.active_arp_ips ?? 0} 个；设备接口 up ${node.active_interface_ips ?? 0} 个` : `ARP/ND current ${node.active_arp_ips ?? 0}; interface up ${node.active_interface_ips ?? 0}`}>{node.active_ips || 0}</td>
          <td className="px-4 py-4 text-xs text-gray-600 tabular-nums">{node.total_ips}</td>
          <td className="px-4 py-4 text-xs font-semibold text-gray-600 tabular-nums">
            <div>{node.utilization}%</div>
            {node.status === 'container' ? (
              <div className="text-[10px] font-normal text-indigo-600">
                {zh ? '容器子网占比' : 'Child prefix space'}
              </div>
            ) : (node.reserved_ips ?? 0) > 0 ? (
              <div className="text-[10px] font-normal text-amber-700">
                {zh
                  ? `保留 ${node.reserved_ips} · 可分配 ${node.allocatable_free_ips ?? 0}`
                  : `Blocked ${node.reserved_ips} · Free ${node.allocatable_free_ips ?? 0}`}
              </div>
            ) : null}
          </td>
          <td className="pr-6 py-4 text-right">
            <ActionIconGroup label={zh ? '前缀操作' : 'Prefix actions'}>
              <PrefixRowActions
                prefix={node}
                zh={zh}
                onEdit={() => openForm(node)}
                onResolveOwnership={() => openAddressSpaceResolution(node)}
                onMoveOwnership={() => openAddressSpaceMove(node)}
                onManagePools={() => setPoolManagerPrefix(node)}
                onDelete={() => setShowDeleteConfirm(node.id)}
              />
            </ActionIconGroup>
          </td>
        </tr>
    );
  };

  return (
    <div className="flex h-full min-h-0 w-full min-w-0 flex-1 flex-col overflow-hidden space-y-4 px-4 py-4 sm:px-6 sm:py-5">
      <PageHero
        icon={Network}
        title={zh ? '网段管理' : 'Prefix Management'}
        subtitle={zh
          ? '管理各站点与路由域的网段台账、用途及网关绑定；支持从设备接口自动导入。'
          : 'Manage prefixes, purposes, and gateway bindings across sites and routing domains.'}
        className="[&>div:first-child]:flex-wrap [&>div:first-child>div:last-child]:max-w-full"
        actions={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <TableExportMenu tableRef={viewMode === 'tree' ? treeTableRef : prefixTableRef} exportData={exportData} filename="ipam-prefixes" language={zh ? 'zh' : 'en'} disabled={loading} />
            <ActionButton
              icon={RefreshCw}
              variant="accent"
              onClick={() => openInterfaceGeneration()}
            >
              {zh ? '从设备接口导入' : 'Import from Interfaces'}
            </ActionButton>
            <ActionButton
              icon={Plus}
              variant="primary"
              onClick={() => openForm(null)}
            >
              {zh ? '新增网段' : 'Add Prefix'}
            </ActionButton>
          </div>
        }
        extras={
          <div className="flex flex-wrap items-center gap-3 w-full md:w-auto">
            <select
              value={siteFilter}
              onChange={(e) => {
                setSiteFilter(e.target.value);
                setPage(1);
                if (viewMode === 'tree') setViewMode('table');
              }}
              className="min-w-[150px] px-3 py-1.5 rounded-xl border border-black/5 bg-white text-xs font-semibold text-gray-500 outline-none transition-all"
            >
              <option value="all">{zh ? '全部站点' : 'All Sites'}</option>
              {sites.map((site) => (
                <option key={site.id} value={site.id}>{site.site_name || site.site_code || site.id}</option>
              ))}
            </select>
            <select
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value);
                setPage(1);
                if (viewMode === 'tree') setViewMode('table');
              }}
              className="px-3 py-1.5 rounded-xl border border-black/5 bg-white text-xs font-semibold text-gray-500 outline-none transition-all"
            >
              <option value="all">{zh ? '所有状态' : 'All Status'}</option>
              <option value="active">{zh ? '使用中' : 'Active'}</option>
              <option value="reserved">{zh ? '已保留' : 'Reserved'}</option>
              <option value="deprecated">{zh ? '已弃用' : 'Deprecated'}</option>
              <option value="container">{zh ? '容器' : 'Container'}</option>
            </select>
            {/* IPv4 / IPv6 Family Switch */}
            <div className="flex rounded-xl bg-gray-100 p-0.5 border border-black/5">
              {([
                { key: 'all', label: zh ? '全部' : 'All' },
                { key: 'ipv4', label: 'IPv4' },
                { key: 'ipv6', label: 'IPv6' },
              ] as const).map((opt) => (
                <button
                  key={opt.key}
                  onClick={() => { setFamilyFilter(opt.key); setPage(1); }}
                  className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                    familyFilter === opt.key ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-400 hover:text-gray-600'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>

            {/* View Mode Switch */}
            <div className="flex rounded-xl bg-gray-100 p-0.5 border border-black/5">
              <button
                onClick={() => { setViewMode('table'); setPage(1); }}
                className={`flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  viewMode === 'table' ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-400 hover:text-gray-600'
                }`}
              >
                <TableProperties size={13} />
                {zh ? '列表视图' : 'Flat List'}
              </button>
              {search === '' && (
                <button
                  type="button"
                  disabled={!canUseTreeView}
                  title={!canUseTreeView
                    ? (zh ? '层次树不支持搜索、站点、状态或分类筛选；请先清除这些条件。' : 'Hierarchy view does not support search, site, status, or classification filters. Clear them first.')
                    : undefined}
                  onClick={() => setViewMode('tree')}
                  className={`flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                    viewMode === 'tree' ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-400 hover:text-gray-600'
                  } ${!canUseTreeView ? 'cursor-not-allowed opacity-40' : ''}`}
                >
                  <GitBranch size={13} />
                  {zh ? '层次树视图' : 'Hierarchy Tree'}
                </button>
              )}
            </div>

            {/* Search Input */}
            <div className="relative min-w-[220px] flex-1 md:w-64">
              <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="search"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                  if (viewMode === 'tree') setViewMode('table');
                }}
                placeholder={zh ? '搜索前缀、网段、名称...' : 'Search prefixes, subnets...'}
                className="w-full pl-10 pr-4 py-2 text-xs rounded-xl border border-black/5 bg-gray-50/50 outline-none focus:border-cyan-400 focus:bg-white focus:shadow-md transition-all font-medium"
              />
            </div>
          </div>
        }
      />

      {loadError && (
        <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2 text-xs font-semibold text-rose-700">
          <span>{loadError}</span>
          <button type="button" onClick={() => loadData()} className="shrink-0 rounded-lg bg-white px-3 py-1.5 text-rose-700 shadow-sm hover:bg-rose-100">
            {zh ? '重试' : 'Retry'}
          </button>
        </div>
      )}

      {classificationSummary && (
        <div>
          {((classificationSummary.address_space_pending_count ?? 0) > 0
            || (classificationSummary.pending_duplicate_group_count ?? 0) > 0) && (
            <div
              role="status"
              aria-label={zh ? '待确认地址归属与重复网段' : 'Pending address scope and duplicate prefixes'}
              className="mb-2 rounded-xl border border-amber-200 bg-amber-50/80 px-4 py-2.5 text-xs text-amber-900"
            >
              <p className="font-semibold">
                {zh
                  ? `待分配地址空间 ${classificationSummary.address_space_pending_count ?? 0} 条 · 跨站点重复网段 ${classificationSummary.pending_duplicate_group_count ?? 0} 组（共 ${classificationSummary.pending_duplicate_record_count ?? 0} 条）— 勾选后可批量分配地址空间`
                  : `${classificationSummary.address_space_pending_count ?? 0} prefixes need an address space · ${classificationSummary.pending_duplicate_group_count ?? 0} cross-site duplicate groups (${classificationSummary.pending_duplicate_record_count ?? 0} prefixes)`}
              </p>
            </div>
          )}
          <div aria-label={zh ? '用途与异常筛选' : 'Purpose and anomaly filters'} className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-5">
            {classificationCards.map((item) => (
              <button
                key={item.key}
                type="button"
                aria-pressed={classificationFilter === item.key}
                aria-label={`${item.label}: ${item.value}. ${zh ? '点击筛选此类网段' : 'Click to filter this category'}`}
                title={item.key === 'reuse'
                  ? (zh
                    ? '同一租户下相同 CIDR 出现在不同站点，且已明确归属到同一地址空间时，按跨站点复用统计提示，不等同于地址冲突；未映射的重复记录会单独列为待裁决。数字按受影响的网段记录数统计。'
                    : 'The same tenant and CIDR appear at different sites with an explicit shared address space. This is counted as a cross-site reuse notice, not an address-conflict finding; unmapped duplicates are shown separately as pending. Count is affected prefix records.')
                  : item.key === 'conflict'
                    ? (zh ? '当前筛选范围内的真实地址冲突网段记录数；点击查看记录。' : 'True address-conflict prefix records in the current filter scope; click to review.')
                    : (zh ? '点击查看当前筛选范围内此分类的网段记录。' : 'Click to view this category within the current filter scope.')}
                onClick={() => handleClassificationCardClick(item.key)}
                className={`w-full rounded-2xl border border-black/5 px-3 py-2 text-left transition hover:-translate-y-0.5 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 focus-visible:ring-offset-2 ${item.tone} ${
                  classificationFilter === item.key ? 'ring-2 ring-cyan-600 ring-offset-1 shadow-sm' : ''
                }`}
              >
                <span className="block text-[10px] font-bold uppercase tracking-wider opacity-70">{item.label}</span>
                <span className="block text-lg font-extrabold tabular-nums">{item.value}</span>
              </button>
            ))}
          </div>
          <details
            open={classificationMethodOpen || classificationFilter === 'auto' || classificationFilter === 'manual'}
            onToggle={(event) => setClassificationMethodOpen(event.currentTarget.open)}
            className="mt-2 rounded-xl border border-gray-200 bg-gray-50/70 px-3 py-2"
          >
            <summary className="cursor-pointer list-none text-[11px] font-bold text-gray-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500">
              <span className="inline-flex items-center gap-1.5">
                <ChevronRight size={13} className="transition-transform open:rotate-90" aria-hidden="true" />
                {zh ? '按识别方式筛选（自动识别 / 人工指定）' : 'Filter by source (auto / manual)'}
              </span>
            </summary>
            <div className="mt-2 grid grid-cols-2 gap-2 sm:max-w-xl">
              {classificationMethodCards.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  aria-pressed={classificationFilter === item.key}
                  aria-label={`${item.label}: ${item.value}. ${zh ? '点击筛选此类网段' : 'Click to filter this category'}`}
                  title={zh ? '用途维护方式与用途是否已识别是两个维度。' : 'Purpose maintenance method and whether the purpose is known are separate dimensions.'}
                  onClick={() => handleClassificationCardClick(item.key)}
                  className={`w-full rounded-xl border border-black/5 px-3 py-2 text-left transition hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 focus-visible:ring-offset-2 ${item.tone} ${classificationFilter === item.key ? 'ring-2 ring-cyan-600 ring-offset-1 shadow-sm' : ''}`}
                >
                  <span className="block text-[10px] font-bold uppercase tracking-wider opacity-70">{item.label}</span>
                  <span className="block text-lg font-extrabold tabular-nums">{item.value}</span>
                </button>
              ))}
            </div>
          </details>
          {classificationFilter !== 'all' && (
            <div className="mt-2 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-cyan-100 bg-cyan-50/70 px-3 py-2 text-[11px] text-cyan-900" role="status" aria-live="polite">
              <span>{zh ? `当前分类筛选：${activeClassificationLabel} · ${totalPrefixes} 条网段记录` : `Classification filter: ${activeClassificationLabel} · ${totalPrefixes} prefix records`}</span>
              <button
                type="button"
                onClick={() => { setClassificationFilter('all'); setPage(1); }}
                className="rounded-md px-2 py-1 font-bold text-cyan-800 underline-offset-2 hover:bg-white hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500"
              >
                {zh ? '清除分类筛选' : 'Clear category filter'}
              </button>
            </div>
          )}
        </div>
      )}

      {suggestedPrefixes.length > 0 && (
        <div role="note" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50/80 px-4 py-3 text-xs text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200">
          <div className="min-w-0 flex-1">
            <p className="font-semibold">
              {zh ? `本页有 ${suggestedPrefixes.length} 个网段待确认用途：` : `${suggestedPrefixes.length} prefixes have suggested purposes: `}
              <span className="font-normal">
                {Object.entries(suggestionGroups).map(([type, items]) => `${NETWORK_TYPES[type] ? (zh ? NETWORK_TYPES[type].labelZh : NETWORK_TYPES[type].label) : type} ${items.length} 个`).join('、')}
              </span>
            </p>
          </div>
          {confirmApplySuggestions ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">{zh ? `确认将这 ${suggestedPrefixes.length} 个网段设为推荐用途？` : `Apply to ${suggestedPrefixes.length} prefixes?`}</span>
              <button type="button" disabled={applyingSuggestions} onClick={handleApplySuggestions} className="rounded-lg bg-amber-600 px-3 py-1.5 font-bold text-white hover:bg-amber-700 disabled:opacity-60 cursor-pointer">
                {applyingSuggestions ? (zh ? '应用中…' : 'Applying…') : (zh ? '确认采纳' : 'Confirm')}
              </button>
              <button type="button" disabled={applyingSuggestions} onClick={() => setConfirmApplySuggestions(false)} className="rounded-lg border border-amber-300 bg-white px-3 py-1.5 font-semibold text-amber-800 hover:bg-amber-100 cursor-pointer dark:bg-zinc-900">
                {zh ? '取消' : 'Cancel'}
              </button>
            </div>
          ) : (
            <button type="button" onClick={() => setConfirmApplySuggestions(true)} className="shrink-0 rounded-lg bg-amber-600 px-3 py-1.5 font-bold text-white hover:bg-amber-700 cursor-pointer">
              {zh ? '采纳推荐用途' : 'Apply suggestions'}
            </button>
          )}
        </div>
      )}

      {suggestionApplyError && (
        <div role="alert" className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          {suggestionApplyError}
        </div>
      )}
      {batchNetworkTypeResult && (
        <div role="status" aria-live="polite" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2 text-xs font-semibold text-emerald-800">
          {batchNetworkTypeResult}
        </div>
      )}
      {batchAddressSpaceResult && (
        <div role="status" aria-live="polite" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2 text-xs font-semibold text-emerald-800">
          {batchAddressSpaceResult}
        </div>
      )}

      {selectedIds.size > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-cyan-200 bg-cyan-50/80 px-4 py-3" aria-label={zh ? '所选网段操作' : 'Selected prefix actions'}>
          <div className="text-xs font-bold text-cyan-900">
            {zh ? `已选 ${selectedIds.size} 个网段` : `${selectedIds.size} prefixes selected`}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <ActionButton
              icon={Network}
              variant="default"
              disabled={batchAddressSpaceSaving || selectedIds.size > 100}
              onClick={openBatchAddressSpaceResolution}
            >
              {zh ? '批量修改地址空间' : 'Batch change address space'}
            </ActionButton>
            <ActionButton
              icon={Pencil}
              variant="default"
              onClick={() => {
                setBatchNetworkTypeError('');
                setBatchNetworkTypeResult('');
                setShowBatchNetworkTypeModal(true);
              }}
            >
              {zh ? '批量修改用途' : 'Batch change purpose'}
            </ActionButton>
            <ActionButton
              icon={Trash2}
              variant="danger"
              onClick={() => setShowBatchDeleteConfirm(true)}
            >
              {zh ? '批量删除' : 'Batch delete'}
            </ActionButton>
            <button
              type="button"
              onClick={() => {
                setSelectedIds(new Set());
                setSelectedRevisions({});
                setBatchNetworkTypeResult('');
                setBatchAddressSpaceResult('');
              }}
              className="rounded-lg px-2.5 py-2 text-xs font-semibold text-cyan-800 hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500"
            >
              {zh ? '清除选择' : 'Clear selection'}
            </button>
          </div>
        </div>
      )}

      {/* Main Table Card */}
      <div className="flex-1 min-h-0 min-w-0 w-full bg-white rounded-[28px] border border-black/5 shadow-[0_16px_36px_rgba(11,35,64,0.06)] overflow-hidden flex flex-col">
        <div ref={tableScrollContainerRef} className="min-h-0 min-w-0 flex-1 overflow-auto overscroll-contain">
          {loading ? (
            <div className="h-full flex items-center justify-center text-xs text-gray-400 font-semibold">
              {zh ? '加载中...' : 'Loading prefixes data...'}
            </div>
          ) : viewMode === 'tree' ? (
            <table ref={treeTableRef} className="nx-data-table min-w-[1800px] text-left">
              <thead className="sticky top-0 z-20">
                <tr className="border-b border-gray-100 bg-gray-50/40 text-[10px] font-bold text-gray-400 uppercase tracking-wider select-none">
                  <th className="pl-6 py-4">{zh ? 'Prefix网段' : 'Prefix / CIDR'}</th>
                  <th className="px-4 py-4">{zh ? '网段名称' : 'Name'}</th>
                  <th className="px-4 py-4">{zh ? '用途' : 'Role'}</th>
                  <th className="px-4 py-4">{zh ? '网络归属' : 'Network ownership'}</th>
                  <th className="px-4 py-4">{zh ? '所属VLAN' : 'VLAN'}</th>
                  <th className="px-4 py-4">{zh ? '网关IP' : 'Gateway IP'}</th>
                  <th className="px-4 py-4">{zh ? '网关设备' : 'Gateway Device'}</th>
                  <th className="px-4 py-4">{zh ? '物理站点' : 'Site'}</th>
                  <th className="px-4 py-4">{zh ? '创建时间' : 'Created At'}</th>
                  <th className="px-4 py-4">{zh ? '网段状态' : 'Status'}</th>
                  <th className="px-4 py-4">{zh ? '已分配IP数' : 'Allocated IPs'}</th>
                  <th className="px-4 py-4" title={zh ? '网段内当前存活的已登记 IP 数：终端地址按 ARP/ND 采集（约 2 小时内）判断；设备接口地址（Loopback、互联口、SVI）按接口状态判断（接口 up 且 1 天内采集过）。悬停数字可看分项。' : 'Live registered IPs: endpoints by current ARP/ND, device interface addresses by interface up within 1 day'}>{zh ? '活跃发现IP数' : 'Active Discovery IPs'}</th>
                  <th className="px-4 py-4">{zh ? '可用容量' : 'Usable Capacity'}</th>
                  <th className="px-4 py-4">{zh ? '利用率' : 'Utilization'}
                  </th>
                  <TableActionHeader className="pr-6 py-4 text-right">{zh ? '操作' : 'Actions'}</TableActionHeader>
                </tr>
              </thead>
              <tbody>
                {flattenedTreeRows.length > 0 ? (
                  shouldVirtualizeTree ? (() => {
                    const virtualItems = treeRowVirtualizer.getVirtualItems();
                    const paddingTop = virtualItems.length > 0 ? virtualItems[0].start : 0;
                    const paddingBottom = virtualItems.length > 0
                      ? Math.max(0, treeRowVirtualizer.getTotalSize() - virtualItems[virtualItems.length - 1].end)
                      : 0;
                    return (
                      <>
                        {paddingTop > 0 && (
                          <tr aria-hidden="true">
                            <td colSpan={15} style={{ height: `${paddingTop}px`, padding: 0, border: 0 }} />
                          </tr>
                        )}
                        {virtualItems.map((vItem) => {
                          const row = flattenedTreeRows[vItem.index];
                          return row ? renderTreeRow(row.node, row.depth) : null;
                        })}
                        {paddingBottom > 0 && (
                          <tr aria-hidden="true">
                            <td colSpan={15} style={{ height: `${paddingBottom}px`, padding: 0, border: 0 }} />
                          </tr>
                        )}
                      </>
                    );
                  })() : (
                    flattenedTreeRows.map(({ node, depth }) => renderTreeRow(node, depth))
                  )
                ) : (
                  <tr>
                    <td colSpan={15} className="py-12 text-center text-xs text-gray-400 font-medium">
                      {zh ? '无层次树数据' : 'No subnet structure tree available'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          ) : (
            <table ref={prefixTableRef} className="nx-data-table min-w-[1900px] text-left">
              <thead className="sticky top-0 z-20">
                <tr className="border-b border-gray-100 bg-gray-50/40 text-[10px] font-bold text-gray-400 uppercase tracking-wider select-none">
                  <th className="pl-6 py-4 w-10">
                    <input
                      type="checkbox"
                      aria-label={zh ? '选择本页可见网段' : 'Select visible prefixes on this page'}
                      checked={areAllVisiblePrefixIdsSelected(selectedIds, visiblePrefixIds)}
                      onChange={toggleSelectAll}
                      className="rounded border-gray-300 text-cyan-600 focus:ring-cyan-500"
                    />
                  </th>
                  <th className="px-4 py-4">{zh ? 'Prefix网段' : 'Prefix / CIDR'}</th>
                  <th className="px-4 py-4">{zh ? '网段名称' : 'Name'}</th>
                  <th className="px-4 py-4">{zh ? '用途' : 'Role'}</th>
                  <th className="px-4 py-4">{zh ? '网络归属' : 'Network ownership'}</th>
                  <th className="px-4 py-4">{zh ? '所属VLAN' : 'VLAN'}</th>
                  <th className="px-4 py-4">{zh ? '网关IP' : 'Gateway IP'}</th>
                  <th className="px-4 py-4">{zh ? '网关设备' : 'Gateway Device'}</th>
                  <th className="px-4 py-4">{zh ? '物理站点' : 'Site'}</th>
                  <th className="px-4 py-4">{zh ? '创建时间' : 'Created At'}</th>
                  <th className="px-4 py-4">{zh ? '网段状态' : 'Status'}</th>
                  <th className="px-4 py-4">{zh ? '已分配IP数' : 'Allocated IPs'}</th>
                  <th className="px-4 py-4" title={zh ? '网段内当前存活的已登记 IP 数：终端地址按 ARP/ND 采集（约 2 小时内）判断；设备接口地址（Loopback、互联口、SVI）按接口状态判断（接口 up 且 1 天内采集过）。悬停数字可看分项。' : 'Live registered IPs: endpoints by current ARP/ND, device interface addresses by interface up within 1 day'}>{zh ? '活跃发现IP数' : 'Active Discovery IPs'}</th>
                  <th className="px-4 py-4">{zh ? '可用容量' : 'Usable Capacity'}</th>
                  <th className="px-4 py-4">{zh ? '利用率' : 'Utilization'}</th>
                  <TableActionHeader className="pr-6 py-4 text-right">{zh ? '操作' : 'Actions'}</TableActionHeader>
                </tr>
              </thead>
              <tbody>
                {paginatedPrefixes.length > 0 ? (
                  paginatedPrefixes.map((node, index) => {
                    const isSelected = selectedIds.has(node.id);
                    const siteKey = String(node.site_id || 'unassigned');
                    const siteLabel = node.site_name || node.site_code || (zh ? '未分配站点' : 'Unassigned');
                    const previousSiteKey = index > 0 ? String(paginatedPrefixes[index - 1].site_id || 'unassigned') : '';
                    const showSiteHeader = siteKey !== previousSiteKey;
                    const collapsed = Boolean(collapsedSites[siteKey]);
                    return (
                      <React.Fragment key={node.id}>
                      {showSiteHeader && (
                        <tr className="border-b border-cyan-100 bg-cyan-50/60">
                          <td colSpan={16} className="px-5 py-2.5">
                            <button
                              type="button"
                              onClick={() => setCollapsedSites((current) => ({ ...current, [siteKey]: !current[siteKey] }))}
                              className="flex w-full items-center justify-between text-left"
                            >
                              <span className="inline-flex items-center gap-2 text-xs font-bold text-cyan-800">
                                {collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
                                {siteLabel}
                              </span>
                              <span className="rounded-full bg-white px-2 py-0.5 text-[10px] font-semibold text-cyan-700 shadow-sm">
                                {zh ? '本页网段' : 'Prefixes on page'}
                              </span>
                            </button>
                          </td>
                        </tr>
                      )}
                      {!collapsed && <tr
                        key={`${node.id}-row`}
                        className={`hover:bg-gray-50/50 transition-colors border-b border-gray-100 group ${
                          isSelected ? 'bg-cyan-50/10' : ''
                        }`}
                      >
                        <td className="pl-6 py-4">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleSelectRow(node.id)}
                            className="rounded border-gray-300 text-cyan-600 focus:ring-cyan-500"
                          />
                        </td>
                        <td className="px-4 py-4">
                          <button
                            onClick={() => navigate(`/ipam/ips?prefix_id=${node.id}`)}
                            className="whitespace-nowrap text-sm font-semibold text-cyan-600 hover:text-cyan-700 hover:underline"
                          >
                            {node.prefix}
                          </button>
                        </td>
                        <td className="max-w-[180px] truncate px-4 py-4 text-xs font-semibold text-gray-500" title={node.name || node.prefix}>{node.name || node.prefix}</td>
                        <td className="px-4 py-4">
                          {(() => {
                            const nt = NETWORK_TYPES[node.network_type] || NETWORK_TYPES['unclassified'];
                            const addressRoles = parseAddressRoles(node.address_roles_json);
                            const hasVip = addressRoles.some((role) => role.address_role && role.address_role !== 'dhcp_lease');
                            const hasDhcp = addressRoles.some((role) => role.address_role === 'dhcp_lease');
                            return (
                              <div className="flex flex-wrap gap-1 items-center">
                                <span className={`whitespace-nowrap px-2 py-0.5 rounded-full text-[10px] font-bold border ${nt.color}`}>
                                  {zh ? nt.labelZh : nt.label}
                                </span>
                                {node.suggested_network_type && !node.manual_override && NETWORK_TYPES[node.suggested_network_type] ? (
                                  <span title={zh ? `推荐依据：${suggestionReasonLabel(node.suggestion_reason)}。点击上方“采纳推荐用途”或在“管理 → 编辑网段”中设置。` : `Why: ${suggestionReasonLabel(node.suggestion_reason)}`} className="whitespace-nowrap px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-amber-50 text-amber-700 border border-dashed border-amber-300">
                                    {zh ? `推荐：${NETWORK_TYPES[node.suggested_network_type].labelZh}` : `Suggested: ${NETWORK_TYPES[node.suggested_network_type].label}`}
                                  </span>
                                ) : null}
                                {hasVip ? <span className="whitespace-nowrap px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-pink-50 text-pink-700 border border-pink-200">VIP</span> : null}
                                {hasDhcp ? <span className="whitespace-nowrap px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-sky-50 text-sky-700 border border-sky-200">DHCP</span> : null}
                                {node.manual_override ? (
                                  <span title={zh ? '用途由人工锁定，系统维护不会改写' : 'Purpose is manually locked and will not be changed by system maintenance'} className="whitespace-nowrap px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-violet-50 text-violet-700 border border-violet-200">
                                    {zh ? '人工锁定' : 'Manually locked'}
                                  </span>
                                ) : null}
                                {node.mixed_network ? (
                                  <span title={zh ? '同一网段存在多种接口角色，需要确认' : 'Multiple interface roles detected; review required'} className="inline-flex items-center gap-0.5 whitespace-nowrap px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-amber-50 text-amber-700 border border-amber-200">
                                    <AlertTriangle size={10} />{zh ? '混合' : 'Mixed'}
                                  </span>
                                ) : null}
                                {node.conflict_status ? (
                                  <span title={zh ? `IPAM 检测到地址冲突：${node.conflict_status}。请核对所属站点、VRF 与地址规划。` : `IPAM detected an address conflict (${node.conflict_status}). Review the site, VRF, and address plan.`} className="inline-flex items-center gap-0.5 whitespace-nowrap px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-rose-50 text-rose-700 border border-rose-200">
                                    <AlertTriangle size={10} />{zh ? '冲突' : 'Conflict'}
                                  </span>
                                ) : null}
                                {node.cross_site_reuse ? (
                                  <span title={zh ? '同一租户、相同 CIDR 位于不同站点，且已有相同明确地址空间归属，因此显示为跨站点复用提示；它不等同于地址冲突。未映射重复记录会单列待裁决。' : 'The same tenant and CIDR appear at different sites with the same explicit address-space mapping, so this is shown as a cross-site reuse notice, not an address-conflict finding. Unmapped duplicates are listed separately as pending.'} className="inline-flex items-center gap-0.5 whitespace-nowrap px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-blue-50 text-blue-700 border border-blue-200">
                                    {zh ? '跨站点复用' : 'Cross-site reuse'}
                                  </span>
                                ) : null}
                              </div>
                            );
                          })()}
                        </td>
                        <td className="whitespace-nowrap px-4 py-4 text-xs font-medium">
                          <PrefixNetworkOwnershipCell prefix={node} zh={zh} />
                        </td>
                        <td className="px-4 py-4">
                          {node.vlan_id ? (
                            <span className="whitespace-nowrap px-2 py-0.5 rounded-full text-[10px] font-bold bg-indigo-50 text-indigo-600 border border-indigo-500/10">
                              VLAN {node.vlan_id}
                            </span>
                          ) : (
                            '-'
                          )}
                        </td>
                        <td className="whitespace-nowrap px-4 py-4 text-xs font-mono font-bold text-gray-700">{node.gateway || '-'}</td>
                        <td className="whitespace-nowrap px-4 py-4 text-xs text-gray-600 font-medium">{node.gateway_device_name || '-'}</td>
                        <td className="whitespace-nowrap px-4 py-4 text-xs text-gray-600 font-semibold">{node.site_name || node.site_code || '-'}</td>
                        <td className="px-4 py-4 text-xs text-gray-500 whitespace-nowrap">{formatPrefixTimestamp(node.created_at, language)}</td>
                        <td className="px-4 py-4">
                          <span className={`inline-flex items-center gap-1.5 whitespace-nowrap px-2.5 py-0.5 rounded-full text-[10px] font-bold ${
                            node.status === 'active' 
                              ? 'bg-emerald-50 text-emerald-600 border border-emerald-500/10' 
                              : node.status === 'reserved' 
                              ? 'bg-amber-50 text-amber-600 border border-amber-500/10' 
                              : 'bg-rose-50 text-rose-600 border border-rose-500/10'
                          }`}>
                            <span className={`w-1.5 h-1.5 rounded-full ${
                              node.status === 'active' ? 'bg-emerald-500' : node.status === 'reserved' ? 'bg-amber-500' : 'bg-rose-500'
                            }`} />
                            {prefixStatusLabel(node.status, zh)}
                          </span>
                        </td>
                        <td className="px-4 py-4 text-xs text-gray-600 tabular-nums">{node.used_ips}</td>
                        <td className="px-4 py-4 text-xs text-gray-600 tabular-nums" title={zh ? `ARP/ND 当前观察到 ${node.active_arp_ips ?? 0} 个；设备接口 up ${node.active_interface_ips ?? 0} 个` : `ARP/ND current ${node.active_arp_ips ?? 0}; interface up ${node.active_interface_ips ?? 0}`}>{node.active_ips || 0}</td>
                        <td className="px-4 py-4 text-xs text-gray-600 tabular-nums">{node.total_ips}</td>
                        <td className="px-4 py-4 text-xs font-semibold text-gray-600 tabular-nums">
                          <div>{node.utilization}%</div>
                          {node.status === 'container' ? (
                            <div className="text-[10px] font-normal text-indigo-600">
                              {zh ? '容器子网占比' : 'Child prefix space'}
                            </div>
                          ) : (node.reserved_ips ?? 0) > 0 ? (
                            <div className="text-[10px] font-normal text-amber-700">
                              {zh
                                ? `保留 ${node.reserved_ips} · 可分配 ${node.allocatable_free_ips ?? 0}`
                                : `Blocked ${node.reserved_ips} · Free ${node.allocatable_free_ips ?? 0}`}
                            </div>
                          ) : null}
                        </td>
                        <TableActionCell className="pr-6 py-4 text-right" label={zh ? '前缀操作' : 'Prefix actions'}>
                          <PrefixRowActions
                            prefix={node}
                            zh={zh}
                            onEdit={() => openForm(node)}
                            onResolveOwnership={() => openAddressSpaceResolution(node)}
                            onMoveOwnership={() => openAddressSpaceMove(node)}
                            onManagePools={() => setPoolManagerPrefix(node)}
                            onDelete={() => setShowDeleteConfirm(node.id)}
                          />
                        </TableActionCell>
                      </tr>}
                      </React.Fragment>
                    );
                  })
                ) : (
                  <tr>
                    <td colSpan={16} className="py-12 text-center text-xs text-gray-400 font-medium">
                      {zh ? '无前缀网段数据' : 'No prefixes data registered'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination */}
        {viewMode === 'table' && (
          <div className="shrink-0 border-t border-gray-100 px-3 py-3 sm:px-6 sm:py-4">
            <Pagination
              currentPage={page}
              totalItems={totalPrefixes}
              itemsPerPage={pageSize}
              onPageChange={setPage}
              onItemsPerPageChange={(size) => { setPageSize(size); setPage(1); }}
              language={language}
              alwaysVisible={true}
            />
          </div>
        )}
      </div>

      {/* Generate canonical IPAM data from current interface collection */}
      <AnimatePresence>
        {showInterfaceGeneration && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-3 backdrop-blur-sm sm:p-5">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              role="dialog"
              aria-modal="true"
              aria-label={zh ? '从接口采集生成 IPAM 网段' : 'Generate IPAM Prefixes from Interfaces'}
              className="flex h-[88vh] max-h-[820px] w-full max-w-5xl flex-col overflow-hidden rounded-3xl border border-black/5 bg-white shadow-2xl"
            >
              <div className="flex shrink-0 items-center justify-between gap-3 border-b border-gray-100 px-4 py-4 sm:px-6">
                <div className="min-w-0">
                  <h3 className="font-bold text-gray-900">{zh ? '从设备接口导入网段' : 'Import Prefixes from Device Interfaces'}</h3>
                <p className="mt-1 text-xs text-gray-500">{zh ? '基于最新设备接口快照提取候选网段：勾选需要导入的网段，为待确认项指定路由域（全局或对应 VRF），点击导入即可。' : 'Extract candidate prefixes from the latest device interface snapshot: select prefixes, assign a routing domain (Global or matching VRF) for pending items, and import.'}</p>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  {interfaceCandidates.length > 0 && <>
                    <span className="hidden text-[10px] text-gray-400 sm:inline">{zh ? '导出当前页' : 'Export current page'}</span>
                    <TableExportMenu
                      filename="ipam-interface-prefix-candidates"
                      language={zh ? 'zh' : 'en'}
                      disabled={interfaceGenerationLoading || interfaceCandidatesLoading}
                      exportData={{
                        headers: [zh ? '候选前缀' : 'Candidate Prefix', zh ? '接口数' : 'Interfaces', zh ? '状态' : 'Status'],
                        rows: interfaceCandidates.map(candidate => [
                          candidate.prefix,
                          candidate.interface_count,
                          candidate.status === 'existing' ? (zh ? '已存在' : 'Existing') : (zh ? '新建项' : 'New'),
                        ]),
                      }}
                    />
                  </>}
                  <button
                    type="button"
                    onClick={() => loadInterfaceCandidates(interfaceCandidatePage.page, interfaceCandidateFilter)}
                    disabled={interfaceCandidatesLoading || interfaceGenerationLoading}
                    aria-label={zh ? '刷新候选项' : 'Refresh candidates'}
                    className="rounded-lg p-2 text-gray-400 transition-colors hover:bg-gray-50 hover:text-cyan-600 disabled:opacity-50"
                  >
                    <RefreshCw size={15} className={interfaceCandidatesLoading ? 'animate-spin' : ''} />
                  </button>
                  <button type="button" onClick={() => setShowInterfaceGeneration(false)} aria-label={zh ? '关闭' : 'Close'} className="rounded-lg p-2 text-gray-400 transition-colors hover:bg-gray-50">
                    <X size={16} />
                  </button>
                </div>
              </div>

              <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4 sm:p-5">
                {interfaceGenerationError && (
                  <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs font-semibold text-rose-700">
                    <span>{interfaceGenerationError}</span>
                    <button type="button" onClick={() => loadInterfaceCandidates(interfaceCandidatePage.page, interfaceCandidateFilter)} disabled={interfaceCandidatesLoading} className="shrink-0 rounded-lg bg-white px-3 py-1.5 text-rose-700 shadow-sm hover:bg-rose-100 disabled:opacity-50">
                      {zh ? '重试' : 'Retry'}
                    </button>
                  </div>
                )}
                {(interfaceGenerationScopeError || selectedInterfaceMissingSpaceMessage) && (
                  <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs font-semibold text-amber-800">
                    {interfaceGenerationScopeError || selectedInterfaceMissingSpaceMessage}
                  </div>
                )}
                {addressSpacesError && (
                  <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs font-semibold text-rose-700">
                    {addressSpacesError}
                  </div>
                )}
                {addressSpaces.filter((space) => space.status === 'active' && space.kind === 'global').length === 0 && (
                  <div className="flex flex-col gap-2 rounded-xl border border-amber-200 bg-amber-50/70 p-3 sm:flex-row sm:items-center">
                    <p className="flex-1 text-[11px] text-amber-800">
                      {zh ? '当前没有全局地址空间。若已确认目标属于独立全局路由域，可在此显式创建；不会按站点自动创建。' : 'No global address space is available. If the target is a verified independent global domain, create it explicitly here; no space is inferred from site.'}
                    </p>
                    <input
                      aria-label={zh ? '接口生成用全局空间名称' : 'Global space name for interface generation'}
                      value={globalSpaceName}
                      onChange={(event) => setGlobalSpaceName(event.target.value)}
                      placeholder={zh ? '全局空间名称' : 'Global space name'}
                      className="min-w-0 rounded-lg border border-amber-200 bg-white px-3 py-2 text-[11px] sm:w-52"
                    />
                    <button
                      type="button"
                      onClick={() => void createGlobalAddressSpace(false)}
                      disabled={globalSpaceCreating || !globalSpaceName.trim()}
                      className="rounded-lg border border-amber-300 bg-white px-3 py-2 text-[11px] font-semibold text-amber-800 disabled:opacity-50"
                    >
                      {globalSpaceCreating ? (zh ? '创建中…' : 'Creating…') : (zh ? '创建全局空间' : 'Create global space')}
                    </button>
                  </div>
                )}
                {interfaceGenerationResult && (
                  <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs font-semibold text-emerald-700">{interfaceGenerationResult}</div>
                )}
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
                  {[
                    { label: zh ? '候选网段' : 'Candidates', value: interfaceCandidateSummary.candidate_count },
                    { label: zh ? '待创建' : 'To create', value: interfaceCandidateSummary.to_create_count },
                    { label: zh ? '已存在' : 'Existing', value: interfaceCandidateSummary.existing_count },
                    { label: zh ? '接口 IP' : 'Interface IPs', value: interfaceCandidateSummary.interface_count },
                    { label: zh ? '范围待确认' : 'Scope needs confirmation', value: interfaceCandidateSummary.vrf_pending_count },
                  ].map((item) => (
                    <div key={item.label} className="rounded-xl border border-gray-100 bg-gray-50/70 px-3 py-2.5">
                      <div className="text-[10px] font-semibold text-gray-500">{item.label}</div>
                      <div className="mt-0.5 text-sm font-extrabold tabular-nums text-gray-800">{item.value.toLocaleString()}</div>
                    </div>
                  ))}
                  </div>
                {selectedInterfaceCandidates.size > 0 && (
                  <section aria-label={zh ? '批量确认接口候选地址空间' : 'Bulk interface candidate address-space assignment'} className="space-y-3 rounded-2xl border border-cyan-100 bg-cyan-50/50 p-3.5">
                    <div>
                      <div className="text-xs font-bold text-gray-800">
                        {zh ? `已选 ${selectedInterfaceCandidates.size} 个候选；其中 ${selectedInterfacePendingScopeCandidates.length} 个待确认地址空间` : `${selectedInterfaceCandidates.size} candidates selected; ${selectedInterfacePendingScopeCandidates.length} need address-space confirmation`}
                      </div>
                      <p className="mt-1 text-[10px] leading-relaxed text-gray-600">
                        {zh ? '仅对本次勾选的候选项生效（含 VRF 的候选需选对应 VRF 空间）。' : 'Applies to selected candidates in this import only.'}
                      </p>
                    </div>
                    {selectedInterfacePendingScopeCandidates.length > 0 && (
                      <div className="grid gap-2 sm:grid-cols-[minmax(180px,1fr)_auto] sm:items-end">
                        <label className="block text-[10px] font-semibold text-gray-700">
                          <span>{zh ? '统一选择待确认候选的 VRF 地址空间' : 'Choose one VRF space for the selected pending candidates'}</span>
                          <select
                            aria-label={zh ? '批量目标 VRF 地址空间' : 'Bulk target VRF address space'}
                            value={bulkInterfaceSpaceId}
                            onChange={(event) => setBulkInterfaceSpaceId(event.target.value)}
                            disabled={addressSpacesLoading || Boolean(addressSpacesError) || interfaceCandidatesLoading || interfaceGenerationLoading || Boolean(interfaceGenerationError)}
                            className="mt-1 block w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs font-normal text-gray-700 disabled:opacity-50"
                          >
                            <option value="">{zh ? '请选择 VRF 地址空间' : 'Select a VRF address space'}</option>
                            {selectedInterfaceCommonVrfSpaces.map((space) => (
                              <option key={space.id} value={space.id}>{addressSpaceOptionLabel(space, zh)}</option>
                            ))}
                          </select>
                        </label>
                        <button
                          type="button"
                          onClick={applyBulkInterfaceSpace}
                          disabled={!bulkInterfaceSpaceId || !selectedInterfaceCommonVrfSpaces.some((space) => space.id === bulkInterfaceSpaceId) || addressSpacesLoading || Boolean(addressSpacesError) || interfaceCandidatesLoading || interfaceGenerationLoading || Boolean(interfaceGenerationError)}
                          className="rounded-lg border border-cyan-200 bg-white px-3 py-2 text-[10px] font-bold text-cyan-800 hover:bg-cyan-100 disabled:opacity-50"
                        >
                          {zh ? `应用到已选待确认项 (${selectedInterfacePendingScopeCandidates.length})` : `Apply to selected pending items (${selectedInterfacePendingScopeCandidates.length})`}
                        </button>
                      </div>
                    )}
                    {selectedInterfaceUnscopedCandidates.length > 0 && (
                      <div className="grid gap-2 rounded-xl border border-amber-200 bg-white/80 p-3 sm:grid-cols-[minmax(180px,1fr)_auto] sm:items-end">
                        {selectedInterfaceCommonGlobalSpaces.length === 1 ? (
                          <div className="text-[10px] font-semibold text-amber-900">
                            <span>{zh ? `确认以下 ${selectedInterfaceUnscopedCandidates.length} 个无 VRF 候选使用唯一可用的 Global 空间：` : `Confirm these ${selectedInterfaceUnscopedCandidates.length} candidates have no VRF and use the only available Global space:`}</span>
                            <div className="mt-1 rounded-lg border border-amber-200 bg-white px-3 py-2 text-xs font-normal text-gray-700">{addressSpaceOptionLabel(selectedInterfaceCommonGlobalSpaces[0], zh)}</div>
                          </div>
                        ) : selectedInterfaceCommonGlobalSpaces.length > 1 ? (
                          <label className="block text-[10px] font-semibold text-amber-900">
                            <span>{zh ? `确认以下 ${selectedInterfaceUnscopedCandidates.length} 个无 VRF 候选使用 Global：选择目标全局地址空间` : `Confirm these ${selectedInterfaceUnscopedCandidates.length} candidates have no VRF: choose the target Global space`}</span>
                            <select
                              aria-label={zh ? '无 VRF 候选的目标 Global 地址空间' : 'Target Global address space for candidates without VRF'}
                              value={bulkGlobalInterfaceSpaceId}
                              onChange={(event) => setBulkGlobalInterfaceSpaceId(event.target.value)}
                              disabled={addressSpacesLoading || Boolean(addressSpacesError) || interfaceCandidatesLoading || interfaceGenerationLoading || Boolean(interfaceGenerationError)}
                              className="mt-1 block w-full rounded-lg border border-amber-200 bg-white px-3 py-2 text-xs font-normal text-gray-700 disabled:opacity-50"
                            >
                              <option value="">{zh ? '请选择具体 Global 地址空间' : 'Select a specific Global address space'}</option>
                              {selectedInterfaceCommonGlobalSpaces.map((space) => (
                                <option key={space.id} value={space.id}>{addressSpaceOptionLabel(space, zh)}</option>
                              ))}
                            </select>
                          </label>
                        ) : (
                          <div className="text-[10px] font-semibold text-amber-900">
                            {activeGlobalInterfaceSpaces.length === 0
                              ? (zh ? '当前没有可用的 Global 地址空间。请先使用上方“创建全局空间”入口创建并刷新列表，再确认无 VRF。' : 'No active Global space is available. Create one with the “Create global space” control above and refresh before confirming no VRF.')
                              : (zh ? '没有一个 Global 同时属于全部已选候选的安全租户。请按租户分批选择，或逐项指定地址空间。' : 'No Global space belongs to every selected candidate tenant. Select candidates by tenant or assign spaces individually.')}
                          </div>
                        )}
                        <button
                          type="button"
                          onClick={confirmUnscopedCandidatesUseGlobal}
                          disabled={(selectedInterfaceCommonGlobalSpaces.length === 0 || (selectedInterfaceCommonGlobalSpaces.length > 1 && !selectedInterfaceCommonGlobalSpaces.some((space) => space.id === bulkGlobalInterfaceSpaceId))) || addressSpacesLoading || Boolean(addressSpacesError) || interfaceCandidatesLoading || interfaceGenerationLoading || Boolean(interfaceGenerationError)}
                          className="rounded-lg bg-amber-600 px-3 py-2 text-[10px] font-bold text-white hover:bg-amber-700 disabled:opacity-50"
                        >
                          {zh ? `确认无 VRF，使用 Global 并应用 (${selectedInterfaceUnscopedCandidates.length})` : `Confirm no VRF, use Global and apply (${selectedInterfaceUnscopedCandidates.length})`}
                        </button>
                        <p className="text-[10px] leading-relaxed text-amber-800 sm:col-span-2">
                          {zh ? `必须明确确认无 VRF 并使用 Global${selectedInterfaceCommonGlobalSpaces.length > 1 ? '；存在多个可用 Global 时需选择目标。' : '。'}已知 VRF 的候选不会被此操作覆盖。` : `Explicitly confirm no VRF and use Global${selectedInterfaceCommonGlobalSpaces.length > 1 ? '; choose the target from the available Global spaces.' : '.'} Candidates with a known VRF are excluded from this action.`}
                        </p>
                      </div>
                    )}
                  </section>
                )}
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap gap-1.5" role="tablist" aria-label={zh ? '候选状态筛选' : 'Candidate status filter'}>
                    {([
                      ['to_create', zh ? '待创建' : 'To create', interfaceCandidateSummary.to_create_count],
                      ['existing', zh ? '已存在' : 'Existing', interfaceCandidateSummary.existing_count],
                      ['scope_pending', zh ? '范围待确认' : 'Scope needs confirmation', interfaceCandidateSummary.vrf_pending_count],
                      ['all', zh ? '全部候选' : 'All candidates', interfaceCandidateSummary.candidate_count],
                    ] as Array<[InterfaceCandidateFilter, string, number]>).map(([status, label, count]) => (
                      <button
                        key={status}
                        type="button"
                        role="tab"
                        aria-selected={interfaceCandidateFilter === status}
                        disabled={interfaceGenerationLoading}
                        onClick={() => {
                          setInterfaceCandidateFilter(status);
                          loadInterfaceCandidates(1, status);
                        }}
                        className={`rounded-lg px-3 py-2 text-[11px] font-bold transition-colors disabled:cursor-wait disabled:opacity-50 ${interfaceCandidateFilter === status ? 'bg-cyan-50 text-cyan-700 ring-1 ring-cyan-200' : 'text-gray-500 hover:bg-gray-50'}`}
                      >
                        {label} <span className="ml-1 tabular-nums opacity-75">{count.toLocaleString()}</span>
                      </button>
                    ))}
                  </div>
                  <div className="flex items-center gap-2 text-[10px] text-gray-500">
                    <span>{interfaceCandidatesLoading
                      ? (zh ? '正在更新候选项…' : 'Updating candidates…')
                      : (zh ? `当前筛选 ${interfaceCandidatePage.filtered_count.toLocaleString()} 项` : `${interfaceCandidatePage.filtered_count.toLocaleString()} filtered`)}</span>
                    <button type="button" onClick={selectVisibleInterfaceCandidates} disabled={interfaceCandidates.length === 0 || interfaceCandidatesLoading || interfaceGenerationLoading} className="rounded-lg border border-gray-200 px-2.5 py-1.5 font-semibold text-gray-600 hover:bg-gray-50 disabled:opacity-50">
                      {interfaceCandidates.length > 0 && interfaceCandidates
                        .every((candidate) => selectedInterfaceCandidates.has(candidate.candidate_id))
                        ? (zh ? '取消本页选择' : 'Clear page selection')
                        : (zh ? '选择本页' : 'Select page')}
                    </button>
                  </div>
                </div>

                <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                  <label className="relative min-w-0 flex-1">
                    <Search size={14} aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                    <input
                      type="search"
                      aria-label={zh ? '搜索接口候选网段' : 'Search interface prefix candidates'}
                      value={interfaceCandidateSearchInput}
                      maxLength={120}
                      placeholder={zh ? '按网段、IP、设备或接口搜索' : 'Search by prefix, IP, device, or interface'}
                      onChange={(event) => setInterfaceCandidateSearchInput(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter') {
                          event.preventDefault();
                          const normalizedSearch = interfaceCandidateSearchInput.trim();
                          setInterfaceCandidateSearch(normalizedSearch);
                          setInterfaceCandidatePage((current) => ({ ...current, page: 1 }));
                          void loadInterfaceCandidates(1, interfaceCandidateFilter, normalizedSearch);
                        }
                      }}
                      disabled={interfaceGenerationLoading}
                      className="h-9 w-full rounded-lg border border-gray-200 bg-white pl-9 pr-3 text-xs outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100 disabled:bg-gray-50"
                    />
                  </label>
                  <div className="flex shrink-0 gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        const normalizedSearch = interfaceCandidateSearchInput.trim();
                        setInterfaceCandidateSearch(normalizedSearch);
                        setInterfaceCandidatePage((current) => ({ ...current, page: 1 }));
                        void loadInterfaceCandidates(1, interfaceCandidateFilter, normalizedSearch);
                      }}
                      disabled={interfaceCandidatesLoading || interfaceGenerationLoading}
                      className="rounded-lg bg-cyan-600 px-3 py-2 text-[11px] font-bold text-white hover:bg-cyan-700 disabled:opacity-50"
                    >
                      {zh ? '搜索' : 'Search'}
                    </button>
                    {(interfaceCandidateSearch || interfaceCandidateSearchInput) && (
                      <button
                        type="button"
                        onClick={() => {
                          setInterfaceCandidateSearchInput('');
                          setInterfaceCandidateSearch('');
                          setInterfaceCandidatePage((current) => ({ ...current, page: 1 }));
                          void loadInterfaceCandidates(1, interfaceCandidateFilter, '');
                        }}
                        disabled={interfaceCandidatesLoading || interfaceGenerationLoading}
                        className="rounded-lg border border-gray-200 px-3 py-2 text-[11px] font-semibold text-gray-600 hover:bg-gray-50 disabled:opacity-50"
                      >
                        {zh ? '清除' : 'Clear'}
                      </button>
                    )}
                  </div>
                </div>

                <div className="min-h-[220px] overflow-x-auto rounded-2xl border border-gray-100">
                  <div className="grid min-w-[650px] grid-cols-[34px_minmax(190px,1fr)_62px_62px_minmax(145px,0.8fr)_82px] gap-2 bg-gray-50 px-3 py-3 text-[10px] font-bold uppercase text-gray-400 sm:grid-cols-[42px_minmax(230px,1fr)_72px_72px_minmax(170px,0.8fr)_100px] sm:gap-3 sm:px-4">
                    <span aria-label={zh ? '选择' : 'Select'} />
                    <span>{zh ? '精确候选网段与接口样例' : 'Exact candidate prefix and interface samples'}</span>
                    <span>{zh ? '接口数' : 'Interfaces'}</span>
                    <span>{zh ? 'IP 数' : 'IPs'}</span>
                    <span>{zh ? '地址空间' : 'Address space'}</span>
                    <span>{zh ? '状态' : 'Status'}</span>
                  </div>
                  {interfaceCandidatesLoading && interfaceCandidates.length === 0 ? (
                    <div role="status" className="py-16 text-center text-xs font-semibold text-gray-400">{zh ? '正在读取接口候选项…' : 'Loading interface candidates…'}</div>
                  ) : interfaceCandidates.length === 0 ? (
                    <div className="py-16 text-center text-xs text-gray-400">
                      {interfaceCandidateSummary.candidate_count === 0 && interfaceCandidateSummary.interface_count === 0
                        ? (zh ? '没有可生成的接口 IP。请先完成接口采集。' : 'No interface IP candidates. Run interface collection first.')
                        : interfaceCandidateSummary.candidate_count === 0
                          ? (zh ? `已读取 ${interfaceCandidateSummary.interface_count} 个接口 IP，但没有可生成的网段。请查看下方未纳入原因。` : `${interfaceCandidateSummary.interface_count} interface IPs were read, but none can be generated. Review the skipped reasons below.`)
                        : (zh ? '此状态下没有候选网段。' : 'No candidates match this status.')}
                    </div>
                  ) : (
                    <div className="max-h-[340px] min-w-[500px] overflow-y-auto">
                      {interfaceCandidates.map((candidate) => (
                        <div key={candidate.candidate_id} className="grid min-w-[650px] grid-cols-[34px_minmax(190px,1fr)_62px_62px_minmax(145px,0.8fr)_82px] items-center gap-2 border-t border-gray-100 px-3 py-3 hover:bg-cyan-50/30 sm:grid-cols-[42px_minmax(230px,1fr)_72px_72px_minmax(170px,0.8fr)_100px] sm:gap-3 sm:px-4">
                          <input
                            aria-label={`${zh ? '选择网段' : 'Select prefix'} ${candidate.prefix}`}
                            type="checkbox"
                            checked={selectedInterfaceCandidates.has(candidate.candidate_id)}
                            onChange={() => toggleInterfaceCandidate(candidate)}
                            disabled={interfaceCandidatesLoading || interfaceGenerationLoading || Boolean(interfaceGenerationError)}
                            className="rounded border-gray-300 text-cyan-600 focus:ring-cyan-500"
                          />
                          <div className="min-w-0">
                            <div className="truncate font-mono text-xs font-bold text-gray-800 sm:text-sm">{candidate.prefix}</div>
                            <div className="mt-1 space-y-0.5 text-[10px] text-gray-500">
                              {candidate.interfaces.slice(0, 3).map((item, index) => (
                                <div key={`${item.interface_id}-${index}`} className="truncate">{item.device_name} · {item.interface_name} · {item.address}</div>
                              ))}
                              {candidate.interface_count > candidate.interfaces.length && <div className="text-gray-400">{zh ? `另有 ${candidate.interface_count - candidate.interfaces.length} 个接口` : `${candidate.interface_count - candidate.interfaces.length} more interfaces`}</div>}
                            </div>
                          </div>
                          <span className="text-xs tabular-nums text-gray-600">{candidate.interface_count.toLocaleString()}</span>
                          <span className="text-xs tabular-nums text-gray-600">{candidate.ip_count.toLocaleString()}</span>
                          {interfaceCandidateNeedsManualSpace(candidate) ? (
                            <select
                              aria-label={`${zh ? '为' : 'Choose address space for'} ${candidate.prefix}`}
                              value={selectedInterfaceSpaces[candidate.candidate_id] || candidate.address_space_id || ''}
                              onChange={(event) => {
                                setSelectedInterfaceSpaces((current) => ({
                                  ...current, [candidate.candidate_id]: event.target.value,
                                }));
                                setInterfaceGenerationScopeError('');
                              }}
                              disabled={addressSpacesLoading || Boolean(addressSpacesError) || interfaceCandidatesLoading || interfaceGenerationLoading}
                              className="min-w-0 rounded-lg border border-amber-200 bg-white px-2 py-1.5 text-[10px] text-gray-700"
                            >
                              <option value="">{zh ? '请选择地址空间' : 'Select address space'}</option>
                              {interfaceCandidateSpaceOptions(candidate)
                                .map((item) => <option key={item.id} value={item.id}>{addressSpaceOptionLabel(item, zh)}</option>)}
                            </select>
                          ) : <span className="truncate text-[10px] text-gray-600">
                            {(() => {
                              const spaceId = interfaceCandidateAddressSpaceId(candidate);
                              const space = addressSpaces.find((item) => item.id === spaceId);
                              return space
                                ? addressSpaceOptionLabel(space, zh)
                                : (zh ? '地址空间待配置' : 'Address space pending');
                            })()}
                          </span>}
                          <span className={`inline-flex items-center gap-1 text-[10px] font-bold ${candidate.status === 'existing' ? 'text-emerald-600' : candidate.status === 'scope_pending' && !interfaceCandidateHasResolvedSpace(candidate) ? 'text-amber-600' : 'text-cyan-600'}`}>
                            {candidate.status === 'existing' || (candidate.status === 'scope_pending' && interfaceCandidateHasResolvedSpace(candidate))
                              ? <Check size={13} />
                              : candidate.status === 'scope_pending' ? <AlertTriangle size={13} /> : <Plus size={13} />}
                            {candidate.status === 'existing'
                              ? (zh ? '已存在' : 'Existing')
                              : candidate.status === 'scope_pending' && interfaceCandidateHasResolvedSpace(candidate)
                                ? (zh ? '本次已确认 · 待生成' : 'Confirmed for this run · Ready to generate')
                                : candidate.status === 'scope_pending' ? (zh ? '归属待确认' : 'Scope review') : (zh ? '待创建' : 'To create')}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className="flex items-center justify-between gap-3 text-[10px] text-gray-500">
                  <span>{zh ? `第 ${interfaceCandidatePage.page} / ${Math.max(interfaceCandidatePage.total_pages, 1)} 页` : `Page ${interfaceCandidatePage.page} of ${Math.max(interfaceCandidatePage.total_pages, 1)}`}</span>
                  <div className="flex items-center gap-2">
                    <button type="button" onClick={() => loadInterfaceCandidates(interfaceCandidatePage.page - 1)} disabled={interfaceCandidatesLoading || interfaceGenerationLoading || interfaceCandidatePage.page <= 1} className="rounded-lg border border-gray-200 px-3 py-1.5 font-semibold hover:bg-gray-50 disabled:opacity-40">{zh ? '上一页' : 'Previous'}</button>
                    <button type="button" onClick={() => loadInterfaceCandidates(interfaceCandidatePage.page + 1)} disabled={interfaceCandidatesLoading || interfaceGenerationLoading || interfaceCandidatePage.page >= interfaceCandidatePage.total_pages} className="rounded-lg border border-gray-200 px-3 py-1.5 font-semibold hover:bg-gray-50 disabled:opacity-40">{zh ? '下一页' : 'Next'}</button>
                  </div>
                </div>

                {(interfaceCandidateSummary.skipped_count > 0 || interfaceSkipped.length > 0) && (
                  <div className="rounded-2xl border border-amber-200/70 bg-amber-50/60 p-3.5 text-xs text-amber-800">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-1.5 font-bold">
                        <AlertTriangle size={14} className="text-amber-500" />
                        <span>{zh ? `${interfaceCandidateSummary.skipped_count.toLocaleString()} 个接口未纳入，显示 ${interfaceSkipped.length} 条样例` : `${interfaceCandidateSummary.skipped_count.toLocaleString()} interfaces skipped; showing ${interfaceSkipped.length} examples`}</span>
                      </div>
                      {interfaceSkipped.length > 0 && <button type="button" onClick={() => setShowSkippedDetails(!showSkippedDetails)} className="text-[10px] font-semibold text-amber-700 underline">
                        {showSkippedDetails ? (zh ? '收起样例' : 'Hide examples') : (zh ? '查看样例' : 'Show examples')}
                      </button>}
                    </div>
                    {showSkippedDetails && interfaceSkipped.length > 0 && (
                      <div className="mt-2 max-h-28 space-y-1 overflow-y-auto pr-1">
                        {interfaceSkipped.slice(0, 10).map((item, index) => (
                          <div key={`${item.device_name}-${item.interface_name}-${index}`} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-100/60 bg-white/70 p-1.5 text-[10px]">
                            <span className="font-semibold text-slate-700">{item.device_name}/{item.interface_name}{item.address ? ` · ${item.address}` : ''}</span>
                            <span className="font-medium text-amber-700">{item.reason}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>

              <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-gray-100 bg-gray-50 px-4 py-3 sm:px-6 sm:py-4">
                <span className="text-xs text-gray-600">{zh ? `已明确选择 ${selectedInterfaceCandidates.size.toLocaleString()} 个网段` : `${selectedInterfaceCandidates.size.toLocaleString()} prefixes explicitly selected`}</span>
                <div className="flex flex-wrap items-center justify-end gap-2">
                  <button type="button" onClick={() => setShowGenerateAllPendingConfirm(true)} disabled={interfaceGenerationLoading || interfaceCandidatesLoading || Boolean(interfaceGenerationError) || interfaceCandidateSummary.to_create_count === 0} className="rounded-xl border border-cyan-200 bg-white px-3 py-2 text-[11px] font-bold text-cyan-700 hover:bg-cyan-50 disabled:opacity-50">
                    {zh ? `生成全部待创建项 (${interfaceCandidateSummary.to_create_count.toLocaleString()})` : `Generate all pending (${interfaceCandidateSummary.to_create_count.toLocaleString()})`}
                  </button>
                  <button type="button" onClick={() => setShowInterfaceGeneration(false)} className="rounded-xl px-3 py-2 text-xs font-semibold text-gray-500 hover:bg-gray-100">{zh ? '关闭' : 'Close'}</button>
                  <button type="button" onClick={() => generateFromInterfaces(false)} disabled={interfaceGenerationLoading || interfaceCandidatesLoading || Boolean(interfaceGenerationError) || selectedInterfaceCandidates.size === 0 || selectedInterfaceHasMissingSpace} className="rounded-xl bg-cyan-500 px-4 py-2 text-xs font-bold text-white hover:bg-cyan-600 disabled:opacity-50">
                    {interfaceGenerationLoading ? (zh ? '处理中…' : 'Processing…') : (zh ? `导入 / 同步所选 (${selectedInterfaceCandidates.size})` : `Import / Sync selected (${selectedInterfaceCandidates.size})`)}
                  </button>
                </div>
              </div>

              <AnimatePresence>
                {showGenerateAllPendingConfirm && (
                  <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
                    <motion.div
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      role="alertdialog"
                      aria-modal="true"
                      aria-labelledby="generate-all-pending-title"
                      className="w-full max-w-md rounded-2xl border border-black/5 bg-white p-5 shadow-2xl"
                    >
                      <h4 id="generate-all-pending-title" className="text-sm font-bold text-gray-900">{zh ? '生成全部待创建网段？' : 'Generate all pending prefixes?'}</h4>
                      <p className="mt-2 text-xs leading-relaxed text-gray-600">
                        {zh
                          ? `将处理全部 ${interfaceCandidateSummary.to_create_count.toLocaleString()} 个范围已明确的待创建候选网段，并按原始 CIDR 登记接口 IP。待确认范围和已有网段不包含在全量操作中。`
                          : `This will process all ${interfaceCandidateSummary.to_create_count.toLocaleString()} pending candidates with resolved address spaces and register their interface IPs using the exact CIDRs. Scope-pending and existing prefixes are excluded.`}
                      </p>
                      <div className="mt-5 flex justify-end gap-2">
                        <button type="button" onClick={() => setShowGenerateAllPendingConfirm(false)} className="rounded-lg px-3 py-2 text-xs font-semibold text-gray-500 hover:bg-gray-100">{zh ? '取消' : 'Cancel'}</button>
                        <button type="button" onClick={() => generateFromInterfaces(true)} disabled={interfaceGenerationLoading || Boolean(interfaceGenerationError) || interfaceCandidateSummary.to_create_count === 0} className="rounded-lg bg-cyan-600 px-3 py-2 text-xs font-bold text-white hover:bg-cyan-700 disabled:opacity-50">
                          {interfaceGenerationLoading ? (zh ? '处理中…' : 'Processing…') : (zh ? '确认生成全部' : 'Confirm all')}
                        </button>
                      </div>
                    </motion.div>
                  </div>
                )}
              </AnimatePresence>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {interfaceImportReviewRequest && <InterfaceImportReview
        request={interfaceImportReviewRequest}
        spaceLabels={Object.fromEntries(addressSpaces.map((space) => [
          space.id,
          space.kind === 'global'
            ? (zh ? '全局（无 VRF）' : 'Global (no VRF)')
            : `${zh ? 'VRF' : 'VRF'}: ${space.name || space.vrf_id || space.id}`,
        ]))}
        zh={zh}
        submitting={interfaceGenerationLoading}
        generationError={interfaceGenerationError}
        onBack={() => setInterfaceImportReviewRequest(null)}
        onConfirm={(request) => void generateFromInterfaces(false, request)}
      />}

      {/* Add / Edit Modal */}
      <AnimatePresence>
        {showAddEdit && (
          <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              role="dialog"
              aria-modal="true"
              aria-labelledby="prefix-form-title"
              className="flex h-[90vh] max-h-[850px] w-full max-w-3xl flex-col overflow-hidden rounded-3xl border border-black/5 bg-white shadow-2xl"
            >
              {/* Header */}
              <div className="flex shrink-0 items-center justify-between border-b border-gray-100 px-5 py-4 sm:px-6 sm:py-5">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-2xl bg-cyan-50 flex items-center justify-center text-cyan-600">
                    <PlusCircle size={20} />
                  </div>
                  <div>
                    <h3 id="prefix-form-title" className="font-bold text-gray-900">{editingPrefix ? (zh ? '编辑网段' : 'Edit Prefix') : (zh ? '新增网段' : 'Add Prefix')}</h3>
                    <p className="mt-0.5 text-xs text-gray-500">{zh ? '先选择明确的地址空间并填写 CIDR；站点只记录位置，不会推断地址空间。' : 'Select an explicit address space and enter the CIDR. Site records location and never determines the address space.'}</p>
                  </div>
                </div>
                <button type="button" onClick={() => setShowAddEdit(false)} aria-label={zh ? '关闭网段表单' : 'Close prefix form'} className="p-1.5 rounded-lg hover:bg-gray-50 transition-colors text-gray-400">
                  <X size={16} />
                </button>
              </div>

              {/* Form Content */}
              <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 sm:p-6">
                {errorMsg && (
                  <div className="p-3.5 rounded-2xl bg-rose-50 border border-rose-200 text-xs font-semibold text-rose-600">
                    {errorMsg}
                  </div>
                )}

                <section className="space-y-2 rounded-2xl border border-cyan-100 bg-cyan-50/30 p-3.5" aria-label={zh ? '前缀地址空间' : 'Prefix address space'}>
                  <label className="block text-[10px] font-bold uppercase tracking-wider text-cyan-800">
                    {zh ? '所属地址空间 *' : 'Address space *'}
                    <select
                      aria-label={zh ? '所属地址空间' : 'Address space'}
                      value={form.address_space_id}
                      onChange={(event) => {
                        const space = addressSpaces.find((item) => item.id === event.target.value);
                        setForm((current) => ({
                          ...current,
                          address_space_id: event.target.value,
                          vrf_id: space?.vrf_id || '',
                        }));
                      }}
                      disabled={addressSpacesLoading || Boolean(editingPrefix)}
                      className="mt-1.5 h-10 w-full rounded-xl border border-cyan-100 bg-white px-3 text-xs font-medium text-gray-800 disabled:cursor-not-allowed disabled:bg-gray-100"
                    >
                      <option value="">
                        {addressSpacesLoading
                          ? (zh ? '正在加载地址空间…' : 'Loading address spaces…')
                          : (zh ? '请选择，不会自动推断' : 'Select explicitly; no scope is inferred')}
                      </option>
                      {addressSpaces.filter((item) => item.status === 'active').map((item) => (
                        <option key={item.id} value={item.id}>{addressSpaceOptionLabel(item, zh)}</option>
                      ))}
                    </select>
                  </label>
                  {addressSpacesError && <p role="alert" className="text-[10px] font-medium text-rose-700">{addressSpacesError}</p>}
                  {!addressSpacesError && addressSpaces.filter((item) => item.status === 'active').length === 0 && !addressSpacesLoading && (
                    <p role="status" className="text-[10px] text-amber-800">
                      {zh ? '当前没有可选地址空间。创建一个全局空间，或先在 CMDB 中创建 VRF。' : 'No address spaces are available. Create a global space or add a VRF in CMDB.'}
                    </p>
                  )}
                  {form.address_space_id && (
                    <p className="text-[10px] text-gray-600">
                      {zh
                        ? (addressSpaces.find((item) => item.id === form.address_space_id)?.kind === 'vrf'
                          ? `VRF：${addressSpaces.find((item) => item.id === form.address_space_id)?.vrf_name || form.vrf_id || '—'}；物理站点只表示位置，不参与地址空间判定。`
                          : '已明确选择独立全局地址空间；物理站点只表示位置，不参与地址空间判定。')
                        : (addressSpaces.find((item) => item.id === form.address_space_id)?.kind === 'vrf'
                          ? `VRF: ${addressSpaces.find((item) => item.id === form.address_space_id)?.vrf_name || form.vrf_id || '—'}; site records location only.`
                          : 'An explicit global address space is selected. Site records location only.')}
                    </p>
                  )}
                  {!editingPrefix && (
                    <div className="flex flex-col gap-2 sm:flex-row">
                      <input
                        aria-label={zh ? '新全局地址空间名称' : 'New global address-space name'}
                        value={globalSpaceName}
                        onChange={(event) => setGlobalSpaceName(event.target.value)}
                        placeholder={zh ? '需要新的独立全局域时输入名称' : 'Name a new independent global space'}
                        className="min-w-0 flex-1 rounded-lg border border-gray-200 bg-white px-3 py-2 text-[11px]"
                      />
                      <button
                        type="button"
                        onClick={() => void createGlobalAddressSpace()}
                        disabled={globalSpaceCreating || !globalSpaceName.trim()}
                        className="rounded-lg border border-cyan-200 bg-white px-3 py-2 text-[11px] font-semibold text-cyan-700 hover:bg-cyan-50 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {globalSpaceCreating ? (zh ? '创建中…' : 'Creating…') : (zh ? '创建全局空间' : 'Create global space')}
                      </button>
                    </div>
                  )}
                  {editingPrefix && !editingPrefix.address_space_id && (
                    <p role="status" className="text-[10px] text-amber-800">
                      {zh ? '此旧网段的地址空间尚未确认。普通编辑不会替它选择全局域，请使用列表中的“确认地址空间”操作。' : 'This legacy prefix has no confirmed address space. Regular editing will not assign a global domain; use “Resolve address space” from the list.'}
                    </p>
                  )}
                </section>

                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">

                  {/* CIDR Prefix */}
                  <div className="space-y-1.5 col-span-2">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '前缀/CIDR网段 *' : 'Prefix / CIDR *'}</label>
                    <input
                      type="text"
                      value={form.prefix}
                      onChange={(e) => {
                        const val = e.target.value;
                        setForm((prev) => {
                          const next = { ...prev, prefix: val };
                          // 自动识别设备互联网段：IPv4 /30、/31 或 IPv6 /127
                          const m = val.match(/\/(\d{1,3})\s*$/);
                          if (m && prev.network_type === 'server') {
                            const len = parseInt(m[1], 10);
                            const isV6 = val.includes(':');
                            if ((!isV6 && (len === 30 || len === 31)) || (isV6 && len === 127)) {
                              next.network_type = 'transit';
                            }
                          }
                          return next;
                        });
                      }}
                      placeholder="e.g. 10.1.1.0/24"
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-200 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                      disabled={editingPrefix !== null}
                    />
                    <button
                      type="button"
                      onClick={() => setShowIpPlanningHelper((visible) => !visible)}
                      disabled={!usableIpDetails}
                      aria-expanded={showIpPlanningHelper && !!usableIpDetails}
                      className="mt-1 inline-flex items-center gap-2 rounded-lg border border-cyan-100 bg-cyan-50/50 px-3 py-2 text-[11px] font-semibold text-cyan-700 transition-colors hover:bg-cyan-50 disabled:cursor-not-allowed disabled:border-gray-100 disabled:bg-gray-50 disabled:text-gray-400"
                    >
                      <Info size={13} />
                      <span>{usableIpDetails
                        ? (showIpPlanningHelper ? (zh ? '收起 IP 规划助手' : 'Hide IP planning helper') : (zh ? '查看 IP 规划助手' : 'View IP planning helper'))
                        : (zh ? '输入有效 CIDR 后可查看 IP 规划' : 'Enter a valid CIDR to view IP planning')}</span>
                      {usableIpDetails && <ChevronDown size={13} className={`transition-transform ${showIpPlanningHelper ? 'rotate-180' : ''}`} />}
                    </button>
                    {showIpPlanningHelper && usableIpDetails && (
                      <div className="col-span-2 p-4 bg-cyan-50/30 rounded-2xl border border-cyan-500/10 mt-1 space-y-3">
                        <div className="flex items-center justify-between">
                          <span className="text-[10px] font-bold text-cyan-600 uppercase tracking-wider flex items-center gap-1.5">
                            <Info size={12} />
                            {zh ? '网段 IP 规划助手' : 'Subnet IP Allocator Helper'}
                          </span>
                          <span className="text-[10px] font-bold text-gray-500 bg-gray-100 px-2 py-0.5 rounded-md">
                            {usableIpDetails.isV6 ? 'IPv6' : 'IPv4'}
                          </span>
                        </div>

                        {/* Toggles */}
                        <div className="flex flex-wrap gap-4 text-[10px] font-semibold text-gray-600 bg-white/60 p-2.5 rounded-xl border border-black/5">
                          <div className="flex items-center gap-2">
                            <input
                              id="exclude-net-broadcast-checkbox"
                              type="checkbox"
                              checked={excludeNetBroadcast}
                              onChange={(e) => setExcludeNetBroadcast(e.target.checked)}
                              className="rounded border-gray-300 text-cyan-600 focus:ring-cyan-500 w-3.5 h-3.5 cursor-pointer"
                            />
                            <label 
                              htmlFor="exclude-net-broadcast-checkbox"
                              className="cursor-pointer select-none"
                            >
                              {zh ? '排除网络与广播地址 (首尾 IP)' : 'Exclude Network & Broadcast (First/Last IP)'}
                            </label>
                          </div>
                          <div className={`flex items-center gap-2 ${!usableIpDetails.hasGateway ? 'opacity-50 cursor-not-allowed' : ''}`}>
                            <input
                              id="exclude-gateway-checkbox"
                              type="checkbox"
                              checked={excludeGateway}
                              disabled={!usableIpDetails.hasGateway}
                              onChange={(e) => setExcludeGateway(e.target.checked)}
                              className="rounded border-gray-300 text-cyan-600 focus:ring-cyan-500 w-3.5 h-3.5 cursor-pointer disabled:cursor-not-allowed"
                            />
                            <label 
                              htmlFor="exclude-gateway-checkbox"
                              className={`${!usableIpDetails.hasGateway ? 'cursor-not-allowed' : 'cursor-pointer'} select-none`}
                            >
                              {zh ? '排除默认网关' : 'Exclude Default Gateway'}
                            </label>
                          </div>
                        </div>

                        {/* Breakdown Grid */}
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[10px]">
                          <div className="p-2 bg-white/40 rounded-lg border border-black/5 flex flex-col">
                            <span className="text-gray-400 font-medium">{zh ? '总 IP 数量' : 'Total IPs'}</span>
                            <span className="font-mono font-bold text-gray-800 mt-0.5">
                              {usableIpDetails.total === -1 ? (zh ? '海量' : 'Massive') : usableIpDetails.total.toLocaleString()}
                            </span>
                          </div>

                          <div className="p-2 bg-white/40 rounded-lg border border-black/5 flex flex-col">
                            <span className="text-gray-400 font-medium">{zh ? '网络/首地址' : 'Network/First IP'}</span>
                            <span className={`font-mono font-bold mt-0.5 ${excludeNetBroadcast && usableIpDetails.hasNetBroadcast ? 'text-rose-500 line-through' : 'text-gray-700'}`}>
                              {usableIpDetails.networkIp}
                            </span>
                          </div>

                          <div className="p-2 bg-white/40 rounded-lg border border-black/5 flex flex-col">
                            <span className="text-gray-400 font-medium">{zh ? '广播/尾地址' : 'Broadcast/Last IP'}</span>
                            <span className={`font-mono font-bold mt-0.5 ${excludeNetBroadcast && usableIpDetails.hasNetBroadcast ? 'text-rose-500 line-through' : 'text-gray-700'}`}>
                              {usableIpDetails.broadcastIp}
                            </span>
                          </div>

                          <div className="p-2 bg-white/40 rounded-lg border border-black/5 flex flex-col">
                            <span className="text-gray-400 font-medium">{zh ? '默认网关' : 'Default Gateway'}</span>
                            {usableIpDetails.hasGateway ? (
                              <span className={`font-mono font-bold mt-0.5 ${excludeGateway && usableIpDetails.gatewayValidAndInSubnet ? 'text-amber-600 line-through' : 'text-gray-700'}`}>
                                {usableIpDetails.gatewayIp}
                              </span>
                            ) : (
                              <span className="text-gray-400 italic mt-0.5">{zh ? '未配置' : 'Not configured'}</span>
                            )}
                          </div>
                        </div>

                        {/* Usable Result Summary */}
                        <div className="p-3 bg-gradient-to-r from-cyan-500/10 to-blue-500/10 rounded-xl border border-cyan-500/20 flex flex-col sm:flex-row justify-between sm:items-center gap-2">
                          <div>
                            <span className="text-[10px] text-gray-500 font-bold block">{zh ? '可用主机 IP 范围' : 'Usable Host Range'}</span>
                            <span className="font-mono text-xs font-bold text-gray-700 mt-0.5 block">{usableIpDetails.usableRangeStr}</span>
                          </div>
                          <div className="text-right">
                            <span className="text-[10px] text-gray-500 font-bold block">{zh ? '最终可用 IP 数量' : 'Final Usable IPs'}</span>
                            <span className="text-sm font-extrabold text-cyan-600 block">
                              {usableIpDetails.usable === -1 ? (zh ? '海量' : 'Massive') : `${usableIpDetails.usable.toLocaleString()} 个`}
                            </span>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Network Type (Role) */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '网络用途 (Role)' : 'Network Role'}</label>
                    <select
                      value={form.network_type}
                      onChange={(e) => setForm({ ...form, network_type: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-200 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    >
                      {Object.entries(NETWORK_TYPES).filter(([key]) => key !== 'user').map(([key, val]) => (
                        <option key={key} value={key}>{zh ? val.labelZh : val.label}</option>
                      ))}
                    </select>
                  </div>

                  {!editingPrefix && (
                    <div className="sm:col-span-2">
                      <button
                        type="button"
                        aria-expanded={showSubnetRecommendation}
                        onClick={() => setShowSubnetRecommendation((visible) => !visible)}
                        className="flex w-full items-center justify-between rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 text-left text-xs font-semibold text-gray-600 transition-colors hover:bg-gray-100"
                      >
                        <span>{zh ? '父网段切分推荐（可选）' : 'Parent subnet recommendation (optional)'}</span>
                        <ChevronDown size={15} className={`text-gray-400 transition-transform ${showSubnetRecommendation ? 'rotate-180' : ''}`} />
                      </button>
                      {showSubnetRecommendation && (
                        <div className="mt-2 space-y-3 rounded-2xl border border-gray-200 bg-gray-50 p-4">
                          <p className="text-[10px] leading-relaxed text-gray-500">
                            {zh ? '按父网段和目标前缀长度查找一个可用子网；推荐结果会填入上方 CIDR。' : 'Find an available child subnet under a parent prefix; the suggestion fills the CIDR field above.'}
                          </p>
                          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                            <div className="space-y-1">
                              <label className="text-[10px] font-semibold text-gray-500">{zh ? '选择父网段' : 'Parent subnet'}</label>
                              <select
                                value={parentSubnetId}
                                onChange={(e) => setParentSubnetId(e.target.value)}
                                className="w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs outline-none focus:border-cyan-400"
                              >
                                <option value="">{zh ? '— 请选择 —' : '— Select —'}</option>
                                {prefixes.map((p) => (
                                  <option key={p.id} value={p.id}>{p.prefix} {p.name ? `(${p.name})` : ''}</option>
                                ))}
                              </select>
                            </div>
                            <div className="space-y-1">
                              <label className="text-[10px] font-semibold text-gray-500">{zh ? '期望前缀长度' : 'Desired prefix length'}</label>
                              <div className="flex gap-2">
                                <input
                                  type="number"
                                  value={desiredPrefixLen}
                                  onChange={(e) => setDesiredPrefixLen(parseInt(e.target.value, 10) || 24)}
                                  min={1}
                                  max={128}
                                  className="w-24 rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs outline-none focus:border-cyan-400"
                                />
                                <button type="button" onClick={handleGetSuggestedPrefix} className="flex-1 rounded-xl bg-cyan-500 px-3 py-2 text-[10px] font-bold text-white transition-colors hover:bg-cyan-600">
                                  {zh ? '推荐可用网段' : 'Find available subnet'}
                                </button>
                              </div>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Name */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '网段名称' : 'Name'}</label>
                    <input
                      type="text"
                      value={form.name}
                      onChange={(e) => setForm({ ...form, name: e.target.value })}
                      placeholder={zh ? '可选识别名称；留空使用 CIDR' : 'Optional label; leave blank to use the CIDR'}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-200 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                    <p className="text-[10px] leading-relaxed text-gray-400">{zh ? '这是便于识别的展示别名；留空时界面以 CIDR 显示。' : 'Optional display alias; the CIDR is shown when this is left blank.'}</p>
                  </div>

                  {/* Gateway */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '默认网关 IP（可选）' : 'Default gateway IP (optional)'}</label>
                    <input
                      type="text"
                      value={form.gateway}
                      onChange={(e) => setForm({ ...form, gateway: e.target.value })}
                      placeholder="e.g. 10.1.1.1"
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-200 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                    <p className="text-[10px] leading-relaxed text-gray-400">{zh ? '若位于此子网，它会从可分配地址中排除；这不是设备关联。' : 'When inside this subnet, the IP is excluded from assignable addresses; it is separate from the device association.'}</p>
                  </div>

                  {/* Gateway Device */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-500 ml-1">{zh ? '网关设备' : 'Gateway Device'}</label>
                    <div className="relative">
                      <Search size={13} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                      <input
                        type="search"
                        value={gatewayDeviceSearch}
                        onChange={(e) => setGatewayDeviceSearch(e.target.value)}
                        placeholder={zh ? '搜索设备名或管理 IP 过滤下拉列表…' : 'Filter devices by hostname or IP…'}
                        className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg border border-gray-200 bg-white outline-none focus:border-cyan-400 transition-all"
                      />
                    </div>
                    <select
                      value={form.gateway_device_id}
                      onChange={(e) => {
                        gatewayBindingSourceRef.current = 'manual';
                        const matchingEndpoints = e.target.value
                          ? gatewayCandidates?.endpoints.filter((endpoint) => endpoint.device_id === e.target.value) || []
                          : [];
                        const matchedEp = matchingEndpoints.length === 1 ? matchingEndpoints[0] : null;
                        const inferredVlanNum = extractVlanIdFromInterfaceName(matchedEp?.interface_name);
                        const matchedVlan = inferredVlanNum !== null
                          ? vlans.find((v) => Number(v.vlan_id) === inferredVlanNum && (!form.site_id || v.site_id === form.site_id))
                            || vlans.find((v) => Number(v.vlan_id) === inferredVlanNum)
                          : null;
                        setForm((current) => ({
                          ...current,
                          gateway_device_id: e.target.value,
                          gateway_interface_id: matchedEp?.interface_id || '',
                          ...(matchedVlan ? { vlan_id: matchedVlan.id } : {}),
                        }));
                      }}
                      className="w-full px-3 py-2 text-xs rounded-lg border border-gray-200 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/70"
                    >
                      <option value="">{zh ? '未绑定' : 'None'}</option>
                      {form.gateway_device_id
                        && !devices.some((device: any) => String(device.id) === form.gateway_device_id)
                        && !gatewayCandidateDevices.some((endpoint) => endpoint.device_id === form.gateway_device_id) && (
                        <option value={form.gateway_device_id}>
                          {gatewayCandidates?.selected?.device_id === form.gateway_device_id
                            ? gatewayCandidates.selected.device_name || form.gateway_device_id
                            : form.gateway_device_id}
                        </option>
                      )}
                      {devices
                        .filter((d: any) => {
                          const q = gatewayDeviceSearch.trim().toLowerCase();
                          if (!q) return true;
                          return String(d.id) === form.gateway_device_id
                            || String(d.hostname || '').toLowerCase().includes(q)
                            || String(d.ip_address || '').toLowerCase().includes(q);
                        })
                        .map((d: any) => (
                          <option key={d.id} value={d.id}>{d.hostname} ({d.ip_address})</option>
                        ))}
                      {gatewayCandidateDevices
                        .filter((endpoint) => !devices.some((device: any) => String(device.id) === endpoint.device_id))
                        .map((endpoint) => (
                          <option key={endpoint.device_id} value={endpoint.device_id || ''}>
                            {gatewayCandidateEndpointLabel(endpoint, zh)}
                          </option>
                        ))}
                    </select>
                    {(gatewayCandidatesLoading || gatewayCandidatesError || gatewayCandidates) && (
                      <div
                        role={gatewayCandidatesError ? 'alert' : 'status'}
                        aria-live="polite"
                        className={`rounded-lg border px-3 py-2 text-[10px] leading-relaxed ${
                          gatewayCandidatesError
                            ? 'border-rose-200 bg-rose-50 text-rose-700'
                            : gatewayCandidates?.status === 'matched'
                              ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                              : 'border-amber-200 bg-amber-50 text-amber-900'
                        }`}
                      >
                        <p>
                          {gatewayCandidatesError || (gatewayCandidatesLoading
                            ? (zh ? '正在匹配网关候选设备…' : 'Checking gateway candidates…')
                            : gatewayCandidateStatusMessage(gatewayCandidates as GatewayCandidateResponse, gatewayBindingSourceRef.current, zh))}
                        </p>
                        {gatewayCandidates && gatewayCandidates.endpoints.length > 0 && (
                          <div className="mt-1.5 flex flex-wrap gap-1.5">
                            {gatewayCandidates.endpoints.map((endpoint) => (
                              <button
                                key={`${endpoint.device_id || endpoint.device_name}-${endpoint.interface_name}-${endpoint.address || endpoint.ip_address || ''}`}
                                type="button"
                                disabled={!endpoint.device_id}
                                onClick={() => {
                                  if (!endpoint.device_id) return;
                                  gatewayBindingSourceRef.current = 'manual';
                                  const inferredVlanNum = extractVlanIdFromInterfaceName(endpoint.interface_name);
                                  const matchedVlan = inferredVlanNum !== null
                                    ? vlans.find((v) => Number(v.vlan_id) === inferredVlanNum && (!form.site_id || v.site_id === form.site_id))
                                      || vlans.find((v) => Number(v.vlan_id) === inferredVlanNum)
                                    : null;
                                  setForm((current) => ({
                                    ...current,
                                    gateway_device_id: endpoint.device_id || '',
                                    gateway_interface_id: endpoint.interface_id || '',
                                    ...(matchedVlan ? { vlan_id: matchedVlan.id } : {}),
                                  }));
                                }}
                                className="inline-flex items-center gap-1 rounded-md border border-amber-300 bg-white px-2 py-0.5 text-[10px] font-semibold text-amber-900 hover:bg-amber-100 disabled:opacity-50"
                                title={zh ? '点击一键绑定此候选设备' : 'Click to bind this candidate device'}
                              >
                                <span>{gatewayCandidateEndpointLabel(endpoint, zh)}</span>
                                <span className="text-cyan-700">{zh ? '· 绑定' : '· Bind'}</span>
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  <div className="sm:col-span-2">
                    <details className="overflow-hidden rounded-2xl border border-gray-200 bg-gray-50/60">
                      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-xs font-bold text-gray-700 marker:hidden">
                        <span>{zh ? '高级设置' : 'Advanced settings'}</span>
                        <span className="text-[10px] font-medium text-gray-400">{zh ? '作用域、状态、描述与追踪' : 'Scope, status, description and traceability'}</span>
                      </summary>
                      <div className="grid grid-cols-1 gap-4 border-t border-gray-100 p-4 sm:grid-cols-2">
                  {/* Gateway Interface */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '已保存的接口关联 ID' : 'Saved interface association ID'}</label>
                    <div className="w-full rounded-xl border border-gray-200 bg-gray-100/70 px-4 py-2.5 font-mono text-xs text-gray-500" aria-readonly="true">
                      {form.gateway_interface_id || (zh ? '无' : 'None')}
                    </div>
                    <p className="text-[10px] leading-relaxed text-gray-400">
                      {zh ? '只有快照明确提供共享接口 ID 时才写入；未提供 ID 时保持为空，不会伪造。' : 'An interface ID is saved only when the snapshot provides a shared interface ID; missing IDs remain empty and are never fabricated.'}
                    </p>
                  </div>

                  {/* VLAN Select */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '关联VLAN' : 'VLAN'}</label>
                    <select
                      value={form.vlan_id}
                      onChange={(e) => setForm({ ...form, vlan_id: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-200 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    >
                      <option value="">{zh ? '请选择VLAN' : 'None'}</option>
                      {(() => {
                        const boundDev = devices.find((d: any) => String(d.id) === form.gateway_device_id);
                        const activeSiteId = form.site_id || boundDev?.site_id || '';
                        const scoped = activeSiteId
                          ? vlans.filter((v) => !v.site_id || v.site_id === activeSiteId || v.id === form.vlan_id)
                          : vlans;
                        const seen = new Set<string>();
                        return [...scoped]
                          .sort((a, b) => Number(a.vlan_id || 0) - Number(b.vlan_id || 0))
                          .filter((item) => {
                            if (item.id === form.vlan_id) return true;
                            const key = `${item.vlan_id}|${item.name || ''}|${item.site_id || ''}`;
                            if (seen.has(key)) return false;
                            seen.add(key);
                            return true;
                          })
                          .map((item) => {
                            const siteObj = sites.find((s) => s.id === item.site_id);
                            const siteSuffix = !activeSiteId && siteObj ? ` · ${siteObj.site_name || siteObj.site_code}` : '';
                            return (
                              <option key={item.id} value={item.id}>
                                VLAN {item.vlan_id} ({item.name}){siteSuffix}
                              </option>
                            );
                          });
                      })()}
                    </select>
                  </div>

                  {/* Site Select */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '物理站点' : 'Site'}</label>
                    <select
                      value={form.site_id}
                      onChange={(e) => setForm({ ...form, site_id: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-200 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    >
                      <option value="">{zh ? '请选择站点' : 'None'}</option>
                      {sites.map((item) => (
                        <option key={item.id} value={item.id}>{item.site_name} ({item.site_code})</option>
                      ))}
                    </select>
                  </div>

                  {/* Status Select */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '网段状态' : 'Status'}</label>
                    <select
                      value={form.status}
                      onChange={(e) => setForm({ ...form, status: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-200 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    >
                      <option value="active">{zh ? '使用中' : 'Active'}</option>
                      <option value="reserved">{zh ? '已保留' : 'Reserved'}</option>
                      <option value="deprecated">{zh ? '已弃用' : 'Deprecated'}</option>
                    </select>
                  </div>

                  {/* Description */}
                  <div className="space-y-1.5 sm:col-span-2">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '备注描述说明' : 'Description'}</label>
                    <textarea
                      value={form.description}
                      onChange={(e) => setForm({ ...form, description: e.target.value })}
                      placeholder={zh ? '在此输入前缀网段的用途或其他详细说明信息...' : 'Describe prefix routing purposes...'}
                      rows={3}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-200 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50 resize-none"
                    />
                  </div>

                  {/* Traceable Toggle */}
                  <div className="flex items-center justify-between rounded-xl border border-gray-200 bg-gray-50/50 px-4 py-3 sm:col-span-2">
                    <div>
                      <p className="text-xs font-bold text-gray-700">{zh ? '可追踪 (Traceable)' : 'Traceable'}</p>
                      <p className="text-[10px] text-gray-400 mt-0.5">
                        {zh ? '是否允许该网段参与 Smart Trace 路径分析与终端定位' : 'Allow this prefix to participate in Smart Trace path analysis.'}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => setForm({ ...form, traceable: form.traceable ? 0 : 1 })}
                      className={`relative inline-flex h-6 w-11 flex-shrink-0 items-center rounded-full transition-colors ${
                        form.traceable ? 'bg-cyan-500' : 'bg-gray-300'
                      }`}
                      aria-pressed={!!form.traceable}
                    >
                      <span
                        className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                          form.traceable ? 'translate-x-6' : 'translate-x-1'
                        }`}
                      />
                    </button>
                  </div>
                      </div>
                    </details>
                  </div>
                </div>
              </div>

              {/* Actions */}
              <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-gray-200 bg-gray-50 px-4 py-3 sm:px-6 sm:py-3.5">
                <div className="min-w-0 flex-1">
                  {errorMsg && (
                    <p role="alert" className="text-xs font-semibold text-rose-600 truncate" title={errorMsg}>
                      {errorMsg}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-2.5">
                  <button
                    type="button"
                    onClick={() => setShowAddEdit(false)}
                    className="px-4 py-2 text-xs font-bold text-gray-600 hover:bg-gray-200/70 rounded-lg transition-all"
                  >
                    {zh ? '取消' : 'Cancel'}
                  </button>
                  <button
                    type="button"
                    onClick={handleSave}
                    disabled={isSaving}
                    className="rounded-lg bg-gradient-to-r from-cyan-500 to-blue-600 px-5 py-2 text-xs font-bold text-white shadow-sm transition-all hover:from-cyan-600 hover:to-blue-700 disabled:cursor-wait disabled:opacity-60"
                  >
                    {isSaving ? (zh ? '保存中…' : 'Saving…') : (zh ? '确定保存' : 'Save')}
                  </button>
                </div>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* Explicit legacy prefix scope resolution */}
      <AnimatePresence>
        {scopeResolutionPrefix && (
          <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
            <motion.section
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 8 }}
              role="dialog"
              aria-modal="true"
              aria-label={zh ? (scopeResolutionMode === 'move' ? '迁移地址空间' : '确认地址空间') : (scopeResolutionMode === 'move' ? 'Move address space' : 'Resolve address space')}
              className="w-full max-w-xl overflow-hidden rounded-2xl border border-black/5 bg-white shadow-2xl"
            >
              <header className="flex items-start justify-between gap-3 border-b border-gray-100 px-5 py-4">
                <div>
                  <h3 className="text-sm font-bold text-gray-900">{zh ? (scopeResolutionMode === 'move' ? '迁移网段地址空间' : '确认网段地址空间') : (scopeResolutionMode === 'move' ? 'Move prefix address space' : 'Resolve prefix address space')}</h3>
                  <p className="mt-1 text-xs text-gray-500">{scopeResolutionPrefix.prefix} · {scopeResolutionPrefix.site_name || (zh ? '站点未指定' : 'Site not set')}</p>
                  <p className="mt-1 text-[10px] text-amber-700">
                    {scopeResolutionMode === 'move'
                      ? (zh ? '迁移会同步更新该 Prefix 和其正式登记 IP；若关联地址池、VIP 或 DHCP 租约，系统会阻止迁移并要求先单独处理。' : 'The move updates this Prefix and its registered IPs together. Pools, VIPs, or DHCP leases block the move and must be handled separately first.')
                      : (zh ? '系统不会按站点或空 VRF 推断归属；请根据实际路由域选择。' : 'The system will not infer scope from site or an empty VRF. Choose the verified routing domain.')}
                  </p>
                </div>
                <button type="button" onClick={() => setScopeResolutionPrefix(null)} aria-label={zh ? '关闭地址空间确认' : 'Close address-space resolution'} className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-50">
                  <X size={15} />
                </button>
              </header>
              <div className="space-y-3 p-5">
                <label className="block text-xs font-semibold text-gray-700">
                  {zh ? '目标地址空间' : 'Target address space'}
                  <select
                    aria-label={zh ? '目标地址空间' : 'Target address space'}
                    value={scopeResolutionSpaceId}
                    onChange={(event) => {
                      setScopeResolutionSpaceId(event.target.value);
                      setScopeResolutionConfirmed(false);
                      setScopeResolutionPreview(null);
                    }}
                    disabled={addressSpacesLoading || scopeResolutionSaving}
                    className="mt-1.5 h-10 w-full rounded-lg border border-gray-200 bg-white px-3 text-xs"
                  >
                    <option value="">{addressSpacesLoading ? (zh ? '加载地址空间…' : 'Loading address spaces…') : (zh ? '请选择，不会自动选择' : 'Select explicitly; none is assumed')}</option>
                    {addressSpaces.filter((item) => item.status === 'active' && (scopeResolutionMode !== 'move' || item.id !== scopeResolutionPrefix.address_space_id)).map((space) => (
                      <option key={space.id} value={space.id}>{addressSpaceOptionLabel(space, zh)}</option>
                    ))}
                  </select>
                </label>
                <div className="flex flex-col gap-2 rounded-xl border border-gray-100 bg-gray-50/70 p-3 sm:flex-row sm:items-center">
                  <div className="min-w-0 flex-1">
                    <p className="text-[11px] font-semibold text-gray-700">{zh ? '需要新的独立全局域？' : 'Need a new independent global domain?'}</p>
                    <p className="mt-0.5 text-[10px] text-gray-500">{zh ? '显式创建后会刷新列表并选中，不会按站点自动创建。' : 'Create it explicitly to refresh and select it; no space is inferred from site.'}</p>
                  </div>
                  <input
                    aria-label={zh ? '新全局地址空间名称' : 'New global address-space name'}
                    value={globalSpaceName}
                    onChange={(event) => setGlobalSpaceName(event.target.value)}
                    placeholder={zh ? '全局空间名称' : 'Global space name'}
                    disabled={globalSpaceCreating || scopeResolutionSaving}
                    className="min-w-0 rounded-lg border border-gray-200 bg-white px-3 py-2 text-[11px] sm:w-48"
                  />
                  <button
                    type="button"
                    onClick={() => void createGlobalAddressSpace(false)}
                    disabled={globalSpaceCreating || scopeResolutionSaving || !globalSpaceName.trim()}
                    className="rounded-lg border border-cyan-200 bg-white px-3 py-2 text-[11px] font-semibold text-cyan-700 hover:bg-cyan-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {globalSpaceCreating ? (zh ? '创建中…' : 'Creating…') : (zh ? '创建并选中' : 'Create and select')}
                  </button>
                </div>
                {addressSpacesError && <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-2.5 text-xs text-rose-700">{addressSpacesError}</div>}
                {scopeResolutionLoading && <div role="status" className="rounded-lg border border-gray-100 bg-gray-50 p-3 text-xs text-gray-500">{zh ? '正在读取影响预览…' : 'Loading impact preview…'}</div>}
                {scopeResolutionError && <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-2.5 text-xs text-rose-700">{scopeResolutionError}</div>}
                {scopeResolutionPreview && (
                  <div className="space-y-3 rounded-xl border border-gray-100 bg-gray-50/60 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                      {scopeResolutionMode === 'move' && (
                        <>
                          <span className="font-semibold text-gray-600">{zh ? '当前空间' : 'Current space'}</span>
                          <span className="font-bold text-gray-800">
                            {scopeResolutionPreview.source_space
                              ? addressSpaceOptionLabel(scopeResolutionPreview.source_space, zh)
                              : scopeResolutionPrefix.address_space_name || scopeResolutionPrefix.address_space_id}
                          </span>
                        </>
                      )}
                      <span className="font-semibold text-gray-600">{zh ? '目标空间' : 'Target space'}</span>
                      <span className="font-bold text-gray-800">
                        {scopeResolutionPreview.target_space
                          ? addressSpaceOptionLabel(scopeResolutionPreview.target_space, zh)
                          : addressSpaces.find((item) => item.id === scopeResolutionSpaceId)
                            ? addressSpaceOptionLabel(addressSpaces.find((item) => item.id === scopeResolutionSpaceId) as AddressSpace, zh)
                            : scopeResolutionSpaceId}
                      </span>
                    </div>
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                      {[
                        [zh ? '登记 IP' : 'Registered IPs', scopeResolutionPreview.impact?.ip_addresses],
                        [zh ? '地址池' : 'Pools', scopeResolutionPreview.impact?.pools],
                        ['VIP', scopeResolutionPreview.impact?.vips],
                        [zh ? 'DHCP 租约' : 'DHCP leases', scopeResolutionPreview.impact?.leases],
                      ].map(([label, value]) => (
                        <div key={String(label)} className="rounded-lg border border-white bg-white p-2">
                          <div className="text-[10px] text-gray-500">{label}</div>
                          <div className="mt-0.5 text-sm font-bold tabular-nums text-gray-800">{Number(value || 0).toLocaleString()}</div>
                        </div>
                      ))}
                    </div>
                    {(scopeResolutionPreview.blockers || []).length > 0 && (
                      <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-2.5 text-xs text-rose-700">
                        <strong>{zh ? '当前不能确认' : 'Cannot resolve yet'}</strong>
                        <ul className="mt-1 list-disc space-y-0.5 pl-4">
                          {(scopeResolutionPreview.blockers || []).map((blocker, index) => (
                            <li key={index}>{typeof blocker === 'string' ? blocker : blocker.message || blocker.code || (zh ? '存在未解决冲突' : 'An unresolved conflict exists')}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {scopeResolutionPreview.can_confirm && (
                      <label className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-2.5 text-[11px] leading-relaxed text-amber-900">
                        <input
                          type="checkbox"
                          checked={scopeResolutionConfirmed}
                          onChange={(event) => setScopeResolutionConfirmed(event.target.checked)}
                          className="mt-0.5 rounded border-amber-300 text-cyan-600 focus:ring-cyan-500"
                        />
                        <span>{scopeResolutionMode === 'move'
                          ? (zh ? '我已核实设备的真实路由域，并确认迁移该 Prefix 及其正式登记 IP 到所选地址空间。' : 'I verified the device routing domain and confirm moving this Prefix and its registered IPs to the selected address space.')
                          : (zh ? '我已核实此网段的真实路由域，并理解映射会更新该 Prefix 及其正式登记 IP 的 VRF/地址空间。' : 'I verified the routing domain and understand this maps the Prefix and its registered IPs to the selected address space.')}</span>
                      </label>
                    )}
                  </div>
                )}
              </div>
              <footer className="flex justify-end gap-2 border-t border-gray-100 px-5 py-3">
                <button type="button" onClick={() => setScopeResolutionPrefix(null)} disabled={scopeResolutionSaving} className="rounded-lg border border-gray-200 px-3 py-2 text-xs font-semibold text-gray-600 disabled:opacity-50">
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button
                  type="button"
                  onClick={() => void resolveAddressSpace()}
                  disabled={scopeResolutionSaving || scopeResolutionLoading || !scopeResolutionPreview?.can_confirm || !scopeResolutionConfirmed}
                  className="rounded-lg bg-cyan-600 px-3 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {scopeResolutionSaving
                    ? (zh ? (scopeResolutionMode === 'move' ? '迁移中…' : '确认中…') : (scopeResolutionMode === 'move' ? 'Moving…' : 'Resolving…'))
                    : (zh ? (scopeResolutionMode === 'move' ? '确认迁移' : '确认地址空间') : (scopeResolutionMode === 'move' ? 'Move address space' : 'Resolve address space'))}
                </button>
              </footer>
            </motion.section>
          </div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {showBatchAddressSpaceModal && (
          <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
            <motion.section
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 8 }}
              role="dialog"
              aria-modal="true"
              aria-label={zh ? '批量修改地址空间' : 'Batch change address space'}
              className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-black/5 bg-white shadow-2xl"
            >
              <header className="flex shrink-0 items-start justify-between gap-3 border-b border-gray-100 px-5 py-4">
                <div>
                  <h3 className="text-sm font-bold text-gray-900">{zh ? '批量修改地址空间' : 'Batch change address space'}</h3>
                  <p className="mt-1 text-xs text-gray-500">
                    {zh
                      ? `将为已选的 ${selectedIds.size} 个网段设置同一个目标地址空间。`
                      : `Map all ${selectedIds.size} selected prefixes to one target address space.`}
                  </p>
                  <p className="mt-1 text-[10px] text-amber-700">
                    {zh
                      ? '仅处理待确认归属的网段；已归属的网段会显示阻断，不会被自动迁移。先逐条预览，任一网段有阻断，整批都不会写入；地址空间不会按站点或空 VRF 推断。'
                      : 'This operation maps pending prefixes only; already-mapped prefixes are blocked and never moved automatically. Every prefix is previewed first, and any blocker prevents the entire batch. Scope is never inferred from site or an empty VRF.'}
                  </p>
                </div>
                <button
                  type="button"
                  aria-label={zh ? '关闭批量地址空间修改' : 'Close batch address-space mapping'}
                  disabled={batchAddressSpaceSaving}
                  onClick={() => setShowBatchAddressSpaceModal(false)}
                  className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-50 disabled:opacity-40"
                >
                  <X size={15} />
                </button>
              </header>

              <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-5">
                <label className="block text-xs font-semibold text-gray-700">
                  {zh ? '目标地址空间' : 'Target address space'}
                  <select
                    aria-label={zh ? '批量目标地址空间' : 'Batch target address space'}
                    value={batchAddressSpaceTargetId}
                    onChange={(event) => {
                      setBatchAddressSpaceTargetId(event.target.value);
                      setBatchAddressSpacePreview(null);
                      setBatchAddressSpaceConfirmed(false);
                      setBatchAddressSpaceError('');
                    }}
                    disabled={addressSpacesLoading || batchAddressSpaceSaving}
                    className="mt-1.5 h-10 w-full rounded-lg border border-gray-200 bg-white px-3 text-xs"
                  >
                    <option value="">
                      {addressSpacesLoading
                        ? (zh ? '加载地址空间…' : 'Loading address spaces…')
                        : (zh ? '请选择，不会自动选择' : 'Select explicitly; none is assumed')}
                    </option>
                    {addressSpaces.filter((item) => item.status === 'active').map((space) => (
                      <option key={space.id} value={space.id}>{addressSpaceOptionLabel(space, zh)}</option>
                    ))}
                  </select>
                </label>

                <div className="flex flex-col gap-2 rounded-xl border border-gray-100 bg-gray-50/70 p-3 sm:flex-row sm:items-center">
                  <div className="min-w-0 flex-1">
                    <p className="text-[11px] font-semibold text-gray-700">{zh ? '需要新的独立全局域？' : 'Need a new independent global domain?'}</p>
                    <p className="mt-0.5 text-[10px] text-gray-500">
                      {zh ? '只有确认这些网段实际不属于 VRF 时才创建 Global。' : 'Create a Global space only when these prefixes truly have no VRF.'}
                    </p>
                  </div>
                  <input
                    aria-label={zh ? '新全局地址空间名称' : 'New global address-space name'}
                    value={globalSpaceName}
                    onChange={(event) => setGlobalSpaceName(event.target.value)}
                    placeholder={zh ? '全局空间名称' : 'Global space name'}
                    disabled={globalSpaceCreating || batchAddressSpaceSaving}
                    className="min-w-0 rounded-lg border border-gray-200 bg-white px-3 py-2 text-[11px] sm:w-48"
                  />
                  <button
                    type="button"
                    onClick={() => void createGlobalAddressSpace(false)}
                    disabled={globalSpaceCreating || batchAddressSpaceSaving || !globalSpaceName.trim()}
                    className="rounded-lg border border-cyan-200 bg-white px-3 py-2 text-[11px] font-semibold text-cyan-700 hover:bg-cyan-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {globalSpaceCreating ? (zh ? '创建中…' : 'Creating…') : (zh ? '创建并选中' : 'Create and select')}
                  </button>
                </div>

                {addressSpacesError && <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-2.5 text-xs text-rose-700">{addressSpacesError}</div>}
                {batchAddressSpaceError && <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-2.5 text-xs text-rose-700">{batchAddressSpaceError}</div>}
                {selectedIds.size > 100 && (
                  <div role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-2.5 text-xs text-amber-800">
                    {zh ? '一次最多批量处理 100 个网段，请先减少选择数量。' : 'A batch can include at most 100 prefixes. Reduce the selection to continue.'}
                  </div>
                )}
                {batchAddressSpaceLoading && <div role="status" className="rounded-lg border border-gray-100 bg-gray-50 p-3 text-xs text-gray-500">{zh ? '正在逐条检查影响与冲突…' : 'Checking each prefix impact and conflict…'}</div>}

                {batchAddressSpacePreview && (
                  <div className="space-y-3">
                    <div className="rounded-xl border border-gray-100 bg-gray-50/60 p-3">
                      <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                        <span className="font-semibold text-gray-600">{zh ? '目标空间' : 'Target space'}</span>
                        <span className="font-bold text-gray-800">
                          {batchAddressSpacePreview.target_space
                            ? addressSpaceOptionLabel(batchAddressSpacePreview.target_space, zh)
                            : batchAddressSpaceTargetId}
                        </span>
                      </div>
                      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
                        {[
                          [zh ? '登记 IP' : 'Registered IPs', batchAddressSpacePreview.totals?.ip_addresses],
                          [zh ? '地址池' : 'Pools', batchAddressSpacePreview.totals?.pools],
                          ['VIP', batchAddressSpacePreview.totals?.vips],
                          [zh ? 'DHCP 租约' : 'DHCP leases', batchAddressSpacePreview.totals?.leases],
                        ].map(([label, value]) => (
                          <div key={String(label)} className="rounded-lg border border-white bg-white p-2">
                            <div className="text-[10px] text-gray-500">{label}</div>
                            <div className="mt-0.5 text-sm font-bold tabular-nums text-gray-800">{Number(value || 0).toLocaleString()}</div>
                          </div>
                        ))}
                      </div>
                    </div>

                    <div className="max-h-64 space-y-2 overflow-y-auto rounded-xl border border-gray-100 p-3" aria-label={zh ? '逐条映射预览' : 'Per-prefix mapping preview'}>
                      {batchAddressSpacePreview.items.map((item) => (
                        <div key={item.prefix_id} className="rounded-lg border border-gray-100 bg-white p-2.5">
                          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                            <span className="font-semibold text-gray-800">{item.prefix}</span>
                            <span className="text-[10px] text-gray-500">{item.site_name || (zh ? '站点未指定' : 'Site not set')}</span>
                          </div>
                          {item.blockers?.length ? (
                            <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-[10px] text-rose-700">
                              {item.blockers.map((blocker, index) => (
                                <li key={`${item.prefix_id}-${index}`}>{addressSpaceBlockerLabel(blocker, zh)}</li>
                              ))}
                            </ul>
                          ) : (
                            <p className="mt-1.5 text-[10px] font-medium text-emerald-700">{zh ? '无阻断，可纳入本批次' : 'No blocker; eligible for this batch'}</p>
                          )}
                        </div>
                      ))}
                    </div>

                    {batchAddressSpacePreview.can_confirm && (
                      <label className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-2.5 text-[11px] leading-relaxed text-amber-900">
                        <input
                          type="checkbox"
                          checked={batchAddressSpaceConfirmed}
                          onChange={(event) => setBatchAddressSpaceConfirmed(event.target.checked)}
                          className="mt-0.5 rounded border-amber-300 text-cyan-600 focus:ring-cyan-500"
                        />
                        <span>{zh ? '我已逐条核实所有选中网段的真实路由域，并确认将它们全部映射到同一地址空间。' : 'I verified the routing domain for every selected prefix and confirm they all belong in the same address space.'}</span>
                      </label>
                    )}
                  </div>
                )}
              </div>

              <footer className="flex shrink-0 justify-end gap-2 border-t border-gray-100 px-5 py-3">
                <button
                  type="button"
                  onClick={() => setShowBatchAddressSpaceModal(false)}
                  disabled={batchAddressSpaceSaving}
                  className="rounded-lg border border-gray-200 px-3 py-2 text-xs font-semibold text-gray-600 disabled:opacity-50"
                >
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button
                  type="button"
                  onClick={() => void resolveBatchAddressSpace()}
                  disabled={batchAddressSpaceSaving || batchAddressSpaceLoading || !batchAddressSpacePreview?.can_confirm || !batchAddressSpaceConfirmed}
                  className="rounded-lg bg-cyan-600 px-3 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {batchAddressSpaceSaving ? (zh ? '批量映射中…' : 'Mapping batch…') : (zh ? `确认映射 ${selectedIds.size} 个网段` : `Map ${selectedIds.size} prefixes`)}
                </button>
              </footer>
            </motion.section>
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
              <div className="p-6 space-y-3">
                <h3 className="text-base font-bold text-gray-900">{zh ? '确认删除网段？' : 'Delete Prefix?'}</h3>
                <p className="text-xs text-gray-500 leading-relaxed">
                  {zh
                    ? '删除前会先核查该网段下是否仍有活跃正式 IP、地址池、VIP 或 DHCP 租约依赖；存在台账依赖时将默认阻止删除。'
                    : 'Deletion checks for active formal IPs, pools, VIPs, and DHCP leases first. Prefixes with active ledger dependencies are protected.'}
                </p>
                {deletePreviewLoading && (
                  <div className="text-xs text-slate-500">{zh ? '正在检查删除影响…' : 'Checking deletion impact…'}</div>
                )}
                {deletePreviewError && (
                  <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                    {zh ? `影响预览加载失败（${deletePreviewError}），后端仍会在提交时校验依赖。` : `Impact preview unavailable (${deletePreviewError}); server-side checks still apply.`}
                  </div>
                )}
                {deletePreview && (
                  <div className="space-y-2">
                    <div className="grid grid-cols-2 gap-2 rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
                      <div>{zh ? '活跃正式 IP' : 'Active formal IPs'}: <strong className="tabular-nums">{deletePreview.active_ip_count}</strong></div>
                      <div>{zh ? '地址池' : 'IP Pools'}: <strong className="tabular-nums">{deletePreview.pool_count}</strong></div>
                      <div>{zh ? 'VIP 记录' : 'VIPs'}: <strong className="tabular-nums">{deletePreview.vip_count}</strong></div>
                      <div>{zh ? '关联 DHCP 租约' : 'DHCP Leases'}: <strong className="tabular-nums">{deletePreview.lease_count}</strong></div>
                      <div>{zh ? '下级子网段' : 'Child Prefixes'}: <strong className="tabular-nums">{deletePreview.child_prefix_count}</strong></div>
                      <div>{zh ? '已释放历史 IP' : 'Released IPs'}: <strong className="tabular-nums">{deletePreview.released_ip_count}</strong></div>
                    </div>
                    {!deletePreview.can_delete && (
                      <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700 space-y-1">
                        <div className="font-bold">{zh ? '存在以下依赖，无法直接删除：' : 'Cannot delete due to active dependencies:'}</div>
                        <ul className="list-disc pl-4 space-y-0.5">
                          {(deletePreview.blockers || []).map((blocker, idx) => <li key={idx}>{blocker}</li>)}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
              </div>
              <div className="px-6 py-4 bg-gray-50 flex items-center justify-end gap-3 border-t border-gray-100">
                <button onClick={() => setShowDeleteConfirm(null)} className="px-3 py-1.5 text-xs text-gray-500 hover:bg-gray-100 rounded-lg font-semibold transition-colors">
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button
                  disabled={deletePreviewLoading || (deletePreview !== null && !deletePreview.can_delete)}
                  onClick={() => handleDelete(showDeleteConfirm)}
                  className="px-4 py-1.5 text-xs bg-rose-500 hover:bg-rose-600 text-white rounded-lg font-bold transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {zh ? '确认删除' : 'Delete'}
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* Batch Delete Confirmation Modal */}
      <AnimatePresence>
        {showBatchDeleteConfirm && (
          <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-white w-full max-w-md rounded-3xl overflow-hidden shadow-2xl border border-black/5"
            >
              <div className="p-6">
                <h3 className="text-base font-bold text-gray-900 mb-2">{zh ? '确认批量删除选中的网段？' : 'Batch Delete Prefixes?'}</h3>
                <p className="text-xs text-gray-500 leading-relaxed">
                  {zh ? `您已选中 ${selectedIds.size} 个前缀网段，删除后这些网段及旗下登记的所有关联 IP 地址都会永久丢失，确定继续吗？` : `You have selected ${selectedIds.size} prefixes. Deleting them will recursively delete all nested allocated IP addresses. Are you sure?`}
                </p>
              </div>
              <div className="px-6 py-4 bg-gray-50 flex items-center justify-end gap-3 border-t border-gray-100">
                <button onClick={() => setShowBatchDeleteConfirm(false)} className="px-3 py-1.5 text-xs text-gray-500 hover:bg-gray-100 rounded-lg font-semibold transition-colors">
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button onClick={handleBatchDelete} className="px-4 py-1.5 text-xs bg-rose-500 hover:bg-rose-600 text-white rounded-lg font-bold transition-colors">
                  {zh ? '确定批量删除' : 'Batch Delete'}
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {showBatchNetworkTypeModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
            <motion.div
              initial={{ scale: 0.97, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.97, opacity: 0 }}
              role="dialog"
              aria-modal="true"
              aria-label={zh ? '批量修改网段用途' : 'Batch change prefix purpose'}
              className="w-full max-w-lg overflow-hidden rounded-2xl border border-black/5 bg-white shadow-2xl"
            >
              <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
                <div>
                  <h3 className="text-sm font-bold text-gray-900">{zh ? '批量修改网段用途' : 'Batch change prefix purpose'}</h3>
                  <p className="mt-1 text-[11px] text-gray-500">{zh ? `将更新已选的 ${selectedIds.size} 个网段` : `Update ${selectedIds.size} selected prefixes`}</p>
                </div>
                <button
                  type="button"
                  aria-label={zh ? '关闭批量修改用途' : 'Close batch purpose update'}
                  disabled={batchNetworkTypeUpdating}
                  onClick={() => setShowBatchNetworkTypeModal(false)}
                  className="rounded-lg p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-700 disabled:opacity-40"
                >
                  <X size={16} />
                </button>
              </div>
              <div className="space-y-4 px-5 py-5">
                <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] leading-relaxed text-amber-900">
                  {zh ? '保存后，这些网段会设为人工保护，自动分类不会再覆盖所选用途。' : 'Saving marks these prefixes as manually protected; automatic classification will not overwrite the selected purpose.'}
                </div>
                <div className="space-y-1.5">
                  <label htmlFor="batch-prefix-network-type" className="text-xs font-semibold text-gray-700">{zh ? '网络用途' : 'Network purpose'}</label>
                  <select
                    id="batch-prefix-network-type"
                    value={batchNetworkType}
                    onChange={(e) => setBatchNetworkType(e.target.value)}
                    disabled={batchNetworkTypeUpdating}
                    className="w-full rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-xs font-medium text-gray-700 outline-none transition focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100 disabled:opacity-60"
                  >
                    {Object.entries(NETWORK_TYPES).filter(([key]) => key !== 'user').map(([key, value]) => (
                      <option key={key} value={key}>{zh ? value.labelZh : value.label}</option>
                    ))}
                  </select>
                </div>
                {batchNetworkTypeError && (
                  <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-medium text-rose-700">
                    {batchNetworkTypeError}
                  </div>
                )}
              </div>
              <div className="flex justify-end gap-2 border-t border-gray-100 bg-gray-50 px-5 py-4">
                <button
                  type="button"
                  disabled={batchNetworkTypeUpdating}
                  onClick={() => setShowBatchNetworkTypeModal(false)}
                  className="rounded-lg px-3 py-2 text-xs font-semibold text-gray-600 hover:bg-white disabled:opacity-40"
                >
                  {zh ? '取消' : 'Cancel'}
                </button>
                <ActionButton
                  icon={Check}
                  variant="primary"
                  disabled={batchNetworkTypeUpdating || selectedIds.size === 0}
                  onClick={handleBatchNetworkTypeUpdate}
                >
                  {batchNetworkTypeUpdating ? (zh ? '更新中…' : 'Updating…') : (zh ? '确认修改' : 'Apply changes')}
                </ActionButton>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {poolManagerPrefix && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-3 backdrop-blur-sm sm:p-5">
            <motion.div
              initial={{ scale: 0.97, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.97, opacity: 0 }}
              role="dialog"
              aria-modal="true"
              aria-label={zh ? '网段地址池管理' : 'Prefix pool management'}
              className="flex h-[88vh] max-h-[900px] w-full max-w-6xl flex-col overflow-hidden rounded-3xl border border-black/5 bg-white shadow-2xl"
            >
              <div className="flex shrink-0 items-center justify-between gap-4 border-b border-gray-100 px-5 py-4 sm:px-6">
                <div className="min-w-0">
                  <h2 className="text-sm font-bold text-gray-900">{zh ? '网段分配范围 / 地址池' : 'Prefix Allocation Ranges / Pools'}</h2>
                  <p className="mt-1 truncate font-mono text-xs text-cyan-700">
                    {poolManagerPrefix.prefix}{poolManagerPrefix.name ? ` · ${poolManagerPrefix.name}` : ''}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setPoolManagerPrefix(null)}
                  aria-label={zh ? '关闭地址池管理' : 'Close pool management'}
                  className="shrink-0 rounded-lg p-2 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700"
                >
                  <X size={16} />
                </button>
              </div>
              <div className="flex-1 min-h-0 overflow-hidden p-3 sm:p-5">
                <IPPoolTab language={language} t={t} prefixId={poolManagerPrefix.id} embedded />
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default PrefixManagementTab;
