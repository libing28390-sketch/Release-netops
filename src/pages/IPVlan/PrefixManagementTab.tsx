import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  Network,
  Plus,
  Trash2,
  Search,
  Pencil,
  TableProperties,
  GitBranch,
  Settings,
  X,
  PlusCircle,
  Eye,
  Info,
  Package,
  RefreshCw,
  Check,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import PageHero from '../../components/PageHero';
import Pagination from '../../components/Pagination';
import { ActionButton, ActionIconButton, ActionIconGroup } from '../../components/ui/ActionIconButton';
import { TableExportMenu } from '../../components/ui/TableExportMenu';
import { buildVisibleIpamExportData, fetchAllIpamExportItems } from './ipamExport';
import { useEscapeClose } from '../../hooks/useEscapeClose';
import { useNavigate } from 'react-router-dom';
import { isValidIPv4, isValidIPv6, toNum } from './helpers';
import IPPoolTab from './IPPoolTab';

import { TableActionCell, TableActionHeader } from '../../components/ui/TableActionColumn';
interface Prefix {
  id: string;
  prefix: string;
  network: string;
  prefix_len: number;
  vrf_id: string | null;
  vrf_name: string | null;
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
  active_ips: number;
  utilization: number;
  network_type: string;
  classification_status?: string;
  classification_confidence?: number;
  manual_override?: number;
  mixed_network?: number;
  conflict_status?: string;
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
  status: 'existing' | 'to_create';
  interface_count: number;
  ip_count: number;
  interfaces: Array<{
    interface_id: string;
    device_id: string;
    device_name: string;
    device_ip?: string;
    interface_name: string;
    address: string;
  }>;
}

type InterfaceCandidateFilter = 'to_create' | 'existing' | 'all';

interface InterfaceCandidateSummary {
  candidate_count: number;
  existing_count: number;
  to_create_count: number;
  interface_count: number;
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

const PrefixManagementTab: React.FC<PrefixManagementTabProps> = ({ language, t }) => {
  const treeTableRef = useRef<HTMLTableElement>(null);
  const prefixTableRef = useRef<HTMLTableElement>(null);
  const hasLoadedPrefixDataRef = useRef(false);
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
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [collapsedSites, setCollapsedSites] = useState<Record<string, boolean>>({});

  // CMDB Dropdowns
  const [sites, setSites] = useState<any[]>([]);
  const [vrfs, setVrfs] = useState<any[]>([]);
  const [vlans, setVlans] = useState<any[]>([]);
  const [tenants, setTenants] = useState<any[]>([]);
  const [devices, setDevices] = useState<any[]>([]);

  // Modals
  const [showAddEdit, setShowAddEdit] = useState(false);
  const [editingPrefix, setEditingPrefix] = useState<Prefix | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<string | null>(null);
  const [showBatchDeleteConfirm, setShowBatchDeleteConfirm] = useState(false);
  const [showInterfaceGeneration, setShowInterfaceGeneration] = useState(false);
  const [poolManagerPrefix, setPoolManagerPrefix] = useState<Prefix | null>(null);
  useEscapeClose(showAddEdit, () => { setShowAddEdit(false); setEditingPrefix(null); });
  useEscapeClose(Boolean(showDeleteConfirm), () => setShowDeleteConfirm(null));
  useEscapeClose(showBatchDeleteConfirm, () => setShowBatchDeleteConfirm(false));
  useEscapeClose(showInterfaceGeneration, () => setShowInterfaceGeneration(false));
  useEscapeClose(Boolean(poolManagerPrefix), () => setPoolManagerPrefix(null));
  const [interfaceCandidates, setInterfaceCandidates] = useState<InterfacePrefixCandidate[]>([]);
  const [selectedInterfaceCandidates, setSelectedInterfaceCandidates] = useState<Set<string>>(new Set());
  const [interfaceSkipped, setInterfaceSkipped] = useState<Array<{ device_name: string; interface_name: string; address: string; reason: string }>>([]);
  const [interfaceCandidateSummary, setInterfaceCandidateSummary] = useState<InterfaceCandidateSummary>({
    candidate_count: 0,
    existing_count: 0,
    to_create_count: 0,
    interface_count: 0,
    skipped_count: 0,
  });
  const [interfaceCandidatePage, setInterfaceCandidatePage] = useState<InterfaceCandidatePage>({
    page: 1,
    page_size: 25,
    filtered_count: 0,
    total_pages: 0,
  });
  const [interfaceCandidateFilter, setInterfaceCandidateFilter] = useState<InterfaceCandidateFilter>('to_create');
  const [interfaceGenerationLoading, setInterfaceGenerationLoading] = useState(false);
  const [interfaceCandidatesLoading, setInterfaceCandidatesLoading] = useState(false);
  const [interfaceGenerationError, setInterfaceGenerationError] = useState('');
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
    vlan_id: '',
    site_id: '',
    tenant_id: 'tenant-default',
    status: 'active',
    gateway: '',
    description: '',
    network_type: 'server',
    gateway_device_id: '',
    gateway_interface_id: '',
    traceable: 1,
  });
  const [errorMsg, setErrorMsg] = useState('');
  const [parentSubnetId, setParentSubnetId] = useState('');
  const [desiredPrefixLen, setDesiredPrefixLen] = useState(24);
  const [showSubnetRecommendation, setShowSubnetRecommendation] = useState(false);
  const [showIpPlanningHelper, setShowIpPlanningHelper] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [excludeNetBroadcast, setExcludeNetBroadcast] = useState(true);
  const [excludeGateway, setExcludeGateway] = useState(true);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [totalPrefixes, setTotalPrefixes] = useState(0);

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
    try {
      const [sitesRes, vrfsRes, vlansRes, tenantsRes, devicesRes] = await Promise.all([
        fetch('/api/cmdb/sites', { headers: hdrs }),
        fetch('/api/cmdb/vrfs', { headers: hdrs }),
        fetch('/api/cmdb/vlans', { headers: hdrs }),
        fetch('/api/cmdb/tenants', { headers: hdrs }),
        fetch('/api/devices?mode=light', { headers: hdrs }),
      ]);
      const unwrap = (j: any) => (Array.isArray(j) ? j : (j?.data ?? j?.items ?? []));
      if (sitesRes.ok) setSites(unwrap(await sitesRes.json()));
      if (vrfsRes.ok) setVrfs(unwrap(await vrfsRes.json()));
      if (vlansRes.ok) setVlans(unwrap(await vlansRes.json()));
      if (tenantsRes.ok) setTenants(unwrap(await tenantsRes.json()));
      if (devicesRes.ok) {
        setDevices(unwrap(await devicesRes.json()));
      }
    } catch (e) {
      console.error('Failed to load CMDB lookup data:', e);
    }
  }, [authHeaders]);

  const loadData = useCallback(async (options?: { silent?: boolean }) => {
    const silent = options?.silent === true || hasLoadedPrefixDataRef.current;
    if (!silent) setLoading(true);
    setLoadError('');
    try {
      const headers = authHeaders();
      const prefixQuery = new URLSearchParams({
        q: search,
        site: siteFilter,
        status: statusFilter,
        family: familyFilter,
        page: String(page),
        page_size: String(pageSize),
      });
      const [prefixRes, summaryRes] = await Promise.all([
        fetch(`/api/ipam/subnets?${prefixQuery.toString()}`, { headers }),
        fetch('/api/ipam/prefixes/classification-summary', { headers }),
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
      else if (prefixRes.ok) {
        setLoadError(summaryRes.status === 401 || summaryRes.status === 403
          ? (zh ? '当前账号无法读取网段分类汇总。' : 'You do not have permission to view the prefix summary.')
          : (zh ? '加载网段分类汇总失败。' : 'Failed to load prefix classification summary.'));
      }
    } catch (e) {
      console.error(e);
      setLoadError(zh ? '加载网段信息失败，请检查网络后重试。' : 'Failed to load prefix data. Check the connection and retry.');
    } finally {
      if (!silent) setLoading(false);
    }
  }, [search, siteFilter, statusFilter, familyFilter, page, pageSize, authHeaders, zh]);

  const loadInterfaceCandidates = async (requestedPage = 1, status: InterfaceCandidateFilter = interfaceCandidateFilter) => {
    const requestId = ++interfaceCandidateRequestId.current;
    setInterfaceCandidatesLoading(true);
    setInterfaceGenerationError('');
    try {
      const query = new URLSearchParams({ page: String(requestedPage), page_size: '25', status });
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

      setInterfaceCandidates(Array.isArray(data?.candidates) ? data.candidates : []);
      setInterfaceSkipped(Array.isArray(data?.skipped) ? data.skipped : []);
      setInterfaceCandidateSummary({
        candidate_count: Number(data?.candidate_count || 0),
        existing_count: Number(data?.existing_count || 0),
        to_create_count: Number(data?.to_create_count || 0),
        interface_count: Number(data?.interface_count || 0),
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
    setInterfaceCandidateFilter('to_create');
    setInterfaceCandidatePage((current) => ({ ...current, page: 1 }));
    setShowSkippedDetails(false);
    setShowGenerateAllPendingConfirm(false);
    setShowInterfaceGeneration(true);
    await loadInterfaceCandidates(1, 'to_create');
  };

  const toggleInterfaceCandidate = (candidateId: string) => {
    const next = new Set(selectedInterfaceCandidates);
    if (next.has(candidateId)) next.delete(candidateId);
    else next.add(candidateId);
    setSelectedInterfaceCandidates(next);
  };

  const selectVisibleInterfaceCandidates = () => {
    const visibleIds = interfaceCandidates.map((candidate) => candidate.candidate_id);
    const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((candidateId) => selectedInterfaceCandidates.has(candidateId));
    const next = new Set(selectedInterfaceCandidates);
    visibleIds.forEach((candidateId) => {
      if (allVisibleSelected) next.delete(candidateId);
      else next.add(candidateId);
    });
    setSelectedInterfaceCandidates(next);
  };

  const generateFromInterfaces = async (allPending = false) => {
    if (allPending ? interfaceCandidateSummary.to_create_count === 0 : selectedInterfaceCandidates.size === 0) return;
    setInterfaceGenerationLoading(true);
    setInterfaceGenerationError('');
    try {
      const res = await fetch('/api/ipam/prefixes/generate-from-interfaces', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(allPending
          ? { all_pending: true }
          : { candidate_ids: Array.from(selectedInterfaceCandidates) }),
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
      setInterfaceGenerationResult(
        zh
          ? `已创建 ${data.created_prefixes || 0} 个网段，并登记 ${data.created_addresses || 0} 个接口 IP`
          : `Created ${data.created_prefixes || 0} prefixes and ${data.created_addresses || 0} interface IPs`,
      );
      setShowGenerateAllPendingConfirm(false);
      setSelectedInterfaceCandidates(new Set());
      setInterfaceCandidateFilter('to_create');
      await loadData({ silent: true });
      await loadInterfaceCandidates(1, 'to_create');
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
    unclassified: { label: 'Unclassified', labelZh: '待确认', color: 'bg-slate-50 text-slate-600 border-slate-500/10' },
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
    setErrorMsg('');
    setParentSubnetId('');
    setDesiredPrefixLen(24);
    setShowSubnetRecommendation(false);
    setShowIpPlanningHelper(false);
    setIsSaving(false);
    setExcludeNetBroadcast(true);
    setExcludeGateway(true);
    if (prefixItem) {
      setEditingPrefix(prefixItem);
      setForm({
        prefix: prefixItem.prefix,
        name: prefixItem.name || '',
        vrf_id: prefixItem.vrf_id || '',
        vlan_id: prefixItem.vlan_id ? String(prefixItem.vlan_id) : '',
        site_id: prefixItem.site_id || '',
        tenant_id: prefixItem.tenant_id || 'tenant-default',
        status: prefixItem.status || 'active',
        gateway: prefixItem.gateway || '',
        description: prefixItem.description || '',
        network_type: prefixItem.network_type || 'server',
        gateway_device_id: prefixItem.gateway_device_id || '',
        gateway_interface_id: prefixItem.gateway_interface_id || '',
        traceable: prefixItem.traceable ?? 1,
      });
    } else {
      setEditingPrefix(null);
      setForm({
        prefix: '',
        name: '',
        vrf_id: '',
        vlan_id: '',
        site_id: '',
        tenant_id: 'tenant-default',
        status: 'active',
        gateway: '',
        description: '',
        network_type: 'server',
        gateway_device_id: '',
        gateway_interface_id: '',
        traceable: 1,
      });
    }
    setShowAddEdit(true);
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

    const payload = {
      ...form,
      vrf_id: form.vrf_id || null,
      vlan_id: form.vlan_id ? form.vlan_id : null,
      site_id: form.site_id || null,
      tenant_id: form.tenant_id || 'tenant-default',
      gateway_device_id: form.gateway_device_id || null,
      gateway_interface_id: editingPrefix?.gateway_interface_id || null,
    };

    setIsSaving(true);
    try {
      const url = editingPrefix ? `/api/ipam/subnets/${editingPrefix.id}` : '/api/ipam/subnets';
      const method = editingPrefix ? 'PUT' : 'POST';
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
        await loadData({ silent: true });
      } else {
        const err = await res.json().catch(() => ({}));
        setErrorMsg(res.status === 401
          ? (zh ? '登录已过期，请重新登录后重试。' : 'Your session has expired. Sign in and retry.')
          : res.status === 403
            ? (zh ? '当前账号没有保存网段的权限。' : 'You do not have permission to save this prefix.')
            : err.detail || (zh ? '操作失败' : 'Operation failed'));
      }
    } catch (e) {
      setErrorMsg(zh ? '网络请求出错' : 'Network request error');
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      const res = await fetch(`/api/ipam/subnets/${id}`, {
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
    try {
      const res = await fetch('/api/ipam/subnets/batch-delete', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...authHeaders(),
        },
        body: JSON.stringify({ ids: Array.from(selectedIds) }),
      });
      if (res.ok) {
        setSelectedIds(new Set());
        setShowBatchDeleteConfirm(false);
        loadData();
      }
    } catch (e) {
      console.error(e);
    }
  };

  // Toggle selection
  const toggleSelectRow = (id: string) => {
    const next = new Set(selectedIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelectedIds(next);
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === filteredPrefixes.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filteredPrefixes.map((p) => p.id)));
    }
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
  const filteredPrefixes = prefixes;
  const paginatedPrefixes = prefixes;

  const exportData = useCallback(async () => {
    const table = viewMode === 'tree' ? treeTableRef.current : prefixTableRef.current;
    let allPrefixes: Prefix[];
    if (viewMode === 'tree') {
      const flatten = (prefix: Prefix): Prefix[] => [prefix, ...(prefix.children || []).flatMap(flatten)];
      allPrefixes = treeData.filter(matchFamily).flatMap(flatten);
    } else {
      const params = new URLSearchParams({ q: search, site: siteFilter, status: statusFilter, family: familyFilter });
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
      }
      return labels.join(' · ');
    };

    return buildVisibleIpamExportData(table, [
      { header: zh ? 'Prefix网段' : 'Prefix / CIDR', value: (prefix) => prefix.prefix },
      { header: zh ? '网段名称' : 'Name', value: (prefix) => prefix.name || '-' },
      { header: zh ? '用途' : 'Role', value: roleText },
      { header: zh ? '所属VRF' : 'VRF', value: (prefix) => prefix.vrf_name || '-' },
      { header: zh ? '所属VLAN' : 'VLAN', value: (prefix) => prefix.vlan_id ? `VLAN ${prefix.vlan_id}` : '-' },
      { header: zh ? '网关IP' : 'Gateway IP', value: (prefix) => prefix.gateway || '-' },
      { header: zh ? '网关设备' : 'Gateway Device', value: (prefix) => prefix.gateway_device_name || '-' },
      { header: zh ? '物理站点' : 'Site', value: (prefix) => prefix.site_name || prefix.site_code || '-' },
      { header: zh ? '创建时间' : 'Created At', value: (prefix) => formatPrefixTimestamp(prefix.created_at, language) },
      { header: zh ? '网段状态' : 'Status', value: (prefix) => prefixStatusLabel(prefix.status, zh) },
      { header: zh ? '已分配IP数' : 'Allocated IPs', value: (prefix) => prefix.used_ips ?? 0 },
      { header: zh ? '活跃发现IP数' : 'Active Discovery IPs', value: (prefix) => prefix.active_ips ?? 0 },
      { header: zh ? '可用容量' : 'Usable Capacity', value: (prefix) => prefix.total_ips ?? 0 },
      { header: zh ? '利用率' : 'Utilization', value: (prefix) => `${prefix.utilization ?? 0}%` },
    ], allPrefixes);
  }, [viewMode, treeData, matchFamily, search, siteFilter, statusFilter, familyFilter, zh, language]);

  // Recursive tree renderer
  const renderTreeNode = (node: Prefix, depth = 0) => {
    return (
      <React.Fragment key={node.id}>
        <tr className="hover:bg-gray-50/50 transition-colors border-b border-gray-100 group">
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
          <td className="px-4 py-4 text-xs font-medium text-gray-600">{node.vrf_name || '-'}</td>
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
          <td className="px-4 py-4 text-xs text-gray-600 tabular-nums">{node.active_ips || 0}</td>
          <td className="px-4 py-4 text-xs text-gray-600 tabular-nums">{node.total_ips}</td>
          <td className="px-4 py-4 text-xs font-semibold text-gray-600 tabular-nums">{node.utilization}%</td>
          <td className="pr-6 py-4 text-right">
            <ActionIconGroup label={zh ? '前缀操作' : 'Prefix actions'} className="opacity-0 transition-opacity group-hover:opacity-100">
              <ActionIconButton
                icon={Package}
                label={zh ? '分配范围 / 地址池' : 'Allocation ranges / pools'}
                onClick={() => setPoolManagerPrefix(node)}
              />
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
        {node.children && node.children.map((child) => renderTreeNode(child, depth + 1))}
      </React.Fragment>
    );
  };

  return (
    <div className="flex h-full min-h-0 w-full min-w-0 flex-1 flex-col overflow-hidden space-y-4 px-4 py-4 sm:px-6 sm:py-5">
      <PageHero
        icon={Network}
        title={zh ? 'Prefix前缀网段管理' : 'Prefix Management'}
        subtitle={zh ? '管理全局IP前缀与网段的层次树结构，并绑定所属的VRF、VLAN与物理站点' : 'Manage global IP prefixes, hierarchical routing network blocks, and CMDB associations.'}
        className="[&>div:first-child]:flex-wrap [&>div:first-child>div:last-child]:max-w-full"
        actions={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <TableExportMenu tableRef={viewMode === 'tree' ? treeTableRef : prefixTableRef} exportData={exportData} filename="ipam-prefixes" language={zh ? 'zh' : 'en'} disabled={loading} />
            <ActionButton
              icon={Plus}
              variant="primary"
              onClick={() => openForm(null)}
            >
              {zh ? '新增网段' : 'Add Prefix'}
            </ActionButton>
            <ActionButton
              icon={RefreshCw}
              variant="accent"
              onClick={() => openInterfaceGeneration()}
            >
              {zh ? '从接口 IP 生成' : 'Generate from Interfaces'}
            </ActionButton>
            {selectedIds.size > 0 && (
              <ActionButton
                icon={Trash2}
                variant="danger"
                onClick={() => setShowBatchDeleteConfirm(true)}
              >
                {zh ? '批量删除' : 'Batch Delete'}
              </ActionButton>
            )}
          </div>
        }
        extras={
          <div className="flex flex-wrap items-center gap-3 w-full md:w-auto">
            <select
              value={siteFilter}
              onChange={(e) => { setSiteFilter(e.target.value); setPage(1); }}
              className="min-w-[150px] px-3 py-1.5 rounded-xl border border-black/5 bg-white text-xs font-semibold text-gray-500 outline-none transition-all"
            >
              <option value="all">{zh ? '全部站点' : 'All Sites'}</option>
              {sites.map((site) => (
                <option key={site.id} value={site.id}>{site.site_name || site.site_code || site.id}</option>
              ))}
            </select>
            <select
              value={statusFilter}
              onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
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
                  onClick={() => setViewMode('tree')}
                  className={`flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                    viewMode === 'tree' ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-400 hover:text-gray-600'
                  }`}
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
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
          {[
            { label: zh ? '自动分类' : 'Auto', value: classificationSummary.auto_count, tone: 'text-cyan-700 bg-cyan-50' },
            { label: zh ? '人工保护' : 'Manual', value: classificationSummary.manual_count, tone: 'text-violet-700 bg-violet-50' },
            { label: zh ? '待确认' : 'Unclassified', value: classificationSummary.unclassified_count, tone: 'text-slate-700 bg-slate-100' },
            { label: zh ? '混合网段' : 'Mixed', value: classificationSummary.mixed_count, tone: 'text-amber-700 bg-amber-50' },
            { label: zh ? '冲突' : 'Conflicts', value: classificationSummary.conflict_count, tone: 'text-rose-700 bg-rose-50' },
            { label: zh ? '已老化' : 'Stale', value: classificationSummary.stale_count, tone: 'text-gray-600 bg-gray-100' },
          ].map((item) => (
            <div key={item.label} className={`rounded-2xl px-3 py-2 ${item.tone} border border-black/5`}>
              <div className="text-[10px] font-bold uppercase tracking-wider opacity-70">{item.label}</div>
              <div className="text-lg font-extrabold">{item.value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Main Table Card */}
      <div className="flex-1 min-h-0 min-w-0 w-full bg-white rounded-[28px] border border-black/5 shadow-[0_16px_36px_rgba(11,35,64,0.06)] overflow-hidden flex flex-col">
        <div className="min-h-0 min-w-0 flex-1 overflow-auto overscroll-contain">
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
                  <th className="px-4 py-4">{zh ? '所属VRF' : 'VRF'}</th>
                  <th className="px-4 py-4">{zh ? '所属VLAN' : 'VLAN'}</th>
                  <th className="px-4 py-4">{zh ? '网关IP' : 'Gateway IP'}</th>
                  <th className="px-4 py-4">{zh ? '网关设备' : 'Gateway Device'}</th>
                  <th className="px-4 py-4">{zh ? '物理站点' : 'Site'}</th>
                  <th className="px-4 py-4">{zh ? '创建时间' : 'Created At'}</th>
                  <th className="px-4 py-4">{zh ? '网段状态' : 'Status'}</th>
                  <th className="px-4 py-4">{zh ? '已分配IP数' : 'Allocated IPs'}</th>
                  <th className="px-4 py-4">{zh ? '活跃发现IP数' : 'Active Discovery IPs'}</th>
                  <th className="px-4 py-4">{zh ? '可用容量' : 'Usable Capacity'}</th>
                  <th className="px-4 py-4">{zh ? '利用率' : 'Utilization'}
                  </th>
                  <TableActionHeader className="pr-6 py-4 text-right">{zh ? '操作' : 'Actions'}</TableActionHeader>
                </tr>
              </thead>
              <tbody>
                {treeData.length > 0 ? (
                  treeData.filter(matchFamily).map((node) => renderTreeNode(node, 0))
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
                      checked={filteredPrefixes.length > 0 && selectedIds.size === filteredPrefixes.length}
                      onChange={toggleSelectAll}
                      className="rounded border-gray-300 text-cyan-600 focus:ring-cyan-500"
                    />
                  </th>
                  <th className="px-4 py-4">{zh ? 'Prefix网段' : 'Prefix / CIDR'}</th>
                  <th className="px-4 py-4">{zh ? '网段名称' : 'Name'}</th>
                  <th className="px-4 py-4">{zh ? '用途' : 'Role'}</th>
                  <th className="px-4 py-4">{zh ? '所属VRF' : 'VRF'}</th>
                  <th className="px-4 py-4">{zh ? '所属VLAN' : 'VLAN'}</th>
                  <th className="px-4 py-4">{zh ? '网关IP' : 'Gateway IP'}</th>
                  <th className="px-4 py-4">{zh ? '网关设备' : 'Gateway Device'}</th>
                  <th className="px-4 py-4">{zh ? '物理站点' : 'Site'}</th>
                  <th className="px-4 py-4">{zh ? '创建时间' : 'Created At'}</th>
                  <th className="px-4 py-4">{zh ? '网段状态' : 'Status'}</th>
                  <th className="px-4 py-4">{zh ? '已分配IP数' : 'Allocated IPs'}</th>
                  <th className="px-4 py-4">{zh ? '活跃发现IP数' : 'Active Discovery IPs'}</th>
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
                                {hasVip ? <span className="whitespace-nowrap px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-pink-50 text-pink-700 border border-pink-200">VIP</span> : null}
                                {hasDhcp ? <span className="whitespace-nowrap px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-sky-50 text-sky-700 border border-sky-200">DHCP</span> : null}
                                {node.manual_override ? (
                                  <span title={zh ? '人工覆盖，自动分类不会改写' : 'Manual override protected from automatic rewrite'} className="whitespace-nowrap px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-violet-50 text-violet-700 border border-violet-200">
                                    {zh ? '人工' : 'Manual'}
                                  </span>
                                ) : null}
                                {node.mixed_network ? (
                                  <span title={zh ? '同一网段存在多种接口角色，需要确认' : 'Multiple interface roles detected; review required'} className="inline-flex items-center gap-0.5 whitespace-nowrap px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-amber-50 text-amber-700 border border-amber-200">
                                    <AlertTriangle size={10} />{zh ? '混合' : 'Mixed'}
                                  </span>
                                ) : null}
                                {node.conflict_status ? (
                                  <span title={zh ? '同租户同前缀跨站点冲突' : 'Same tenant/prefix appears across sites'} className="inline-flex items-center gap-0.5 whitespace-nowrap px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-rose-50 text-rose-700 border border-rose-200">
                                    <AlertTriangle size={10} />{zh ? '冲突' : 'Conflict'}
                                  </span>
                                ) : null}
                              </div>
                            );
                          })()}
                        </td>
                          <td className="whitespace-nowrap px-4 py-4 text-xs font-medium text-gray-600">{node.vrf_name || '-'}</td>
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
                        <td className="px-4 py-4 text-xs text-gray-600 tabular-nums">{node.active_ips || 0}</td>
                        <td className="px-4 py-4 text-xs text-gray-600 tabular-nums">{node.total_ips}</td>
                        <td className="px-4 py-4 text-xs font-semibold text-gray-600 tabular-nums">{node.utilization}%</td>
                        <TableActionCell className="pr-6 py-4 text-right">
                          <ActionIconGroup label={zh ? '前缀操作' : 'Prefix actions'} className="opacity-0 transition-opacity group-hover:opacity-100">
                            <ActionIconButton
                              icon={Package}
                              label={zh ? '分配范围 / 地址池' : 'Allocation ranges / pools'}
                              onClick={() => setPoolManagerPrefix(node)}
                            />
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
                  <h3 className="font-bold text-gray-900">{zh ? '从接口采集生成 IPAM 网段' : 'Generate IPAM Prefixes from Interfaces'}</h3>
                  <p className="mt-1 text-xs text-gray-500">{zh ? '来源为当前接口采集结果；按精确 CIDR 生成，不合并相邻网段。' : 'Uses current interface collection and preserves each exact CIDR without merging adjacent prefixes.'}</p>
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
                {interfaceGenerationResult && (
                  <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs font-semibold text-emerald-700">{interfaceGenerationResult}</div>
                )}
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
                  {[
                    { label: zh ? '候选网段' : 'Candidates', value: interfaceCandidateSummary.candidate_count },
                    { label: zh ? '待创建' : 'To create', value: interfaceCandidateSummary.to_create_count },
                    { label: zh ? '已存在' : 'Existing', value: interfaceCandidateSummary.existing_count },
                    { label: zh ? '接口 IP' : 'Interface IPs', value: interfaceCandidateSummary.interface_count },
                    { label: zh ? '未纳入接口' : 'Skipped interfaces', value: interfaceCandidateSummary.skipped_count },
                  ].map((item) => (
                    <div key={item.label} className="rounded-xl border border-gray-100 bg-gray-50/70 px-3 py-2.5">
                      <div className="text-[10px] font-semibold text-gray-500">{item.label}</div>
                      <div className="mt-0.5 text-sm font-extrabold tabular-nums text-gray-800">{item.value.toLocaleString()}</div>
                    </div>
                  ))}
                  </div>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap gap-1.5" role="tablist" aria-label={zh ? '候选状态筛选' : 'Candidate status filter'}>
                    {([
                      ['to_create', zh ? '待创建' : 'To create', interfaceCandidateSummary.to_create_count],
                      ['existing', zh ? '已存在' : 'Existing', interfaceCandidateSummary.existing_count],
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
                      {interfaceCandidates.length > 0 && interfaceCandidates.every((candidate) => selectedInterfaceCandidates.has(candidate.candidate_id))
                        ? (zh ? '取消本页选择' : 'Clear page selection')
                        : (zh ? '选择本页' : 'Select page')}
                    </button>
                  </div>
                </div>

                <div className="min-h-[220px] overflow-x-auto rounded-2xl border border-gray-100">
                  <div className="grid min-w-[500px] grid-cols-[34px_minmax(200px,1fr)_70px_70px_82px] gap-2 bg-gray-50 px-3 py-3 text-[10px] font-bold uppercase text-gray-400 sm:grid-cols-[42px_minmax(260px,1fr)_88px_88px_100px] sm:gap-3 sm:px-4">
                    <span aria-label={zh ? '选择' : 'Select'} />
                    <span>{zh ? '精确候选网段与接口样例' : 'Exact candidate prefix and interface samples'}</span>
                    <span>{zh ? '接口数' : 'Interfaces'}</span>
                    <span>{zh ? 'IP 数' : 'IPs'}</span>
                    <span>{zh ? '状态' : 'Status'}</span>
                  </div>
                  {interfaceCandidatesLoading && interfaceCandidates.length === 0 ? (
                    <div role="status" className="py-16 text-center text-xs font-semibold text-gray-400">{zh ? '正在读取接口候选项…' : 'Loading interface candidates…'}</div>
                  ) : interfaceCandidates.length === 0 ? (
                    <div className="py-16 text-center text-xs text-gray-400">
                      {interfaceCandidateSummary.candidate_count === 0
                        ? (zh ? '没有可生成的接口 IP。请先完成接口采集。' : 'No interface IP candidates. Run interface collection first.')
                        : (zh ? '此状态下没有候选网段。' : 'No candidates match this status.')}
                    </div>
                  ) : (
                    <div className="max-h-[340px] min-w-[500px] overflow-y-auto">
                      {interfaceCandidates.map((candidate) => (
                        <label key={candidate.candidate_id} className="grid grid-cols-[34px_minmax(200px,1fr)_70px_70px_82px] items-center gap-2 border-t border-gray-100 px-3 py-3 hover:bg-cyan-50/30 sm:grid-cols-[42px_minmax(260px,1fr)_88px_88px_100px] sm:gap-3 sm:px-4">
                          <input
                            type="checkbox"
                            checked={selectedInterfaceCandidates.has(candidate.candidate_id)}
                            onChange={() => toggleInterfaceCandidate(candidate.candidate_id)}
                            disabled={interfaceCandidatesLoading || interfaceGenerationLoading || Boolean(interfaceGenerationError)}
                            aria-label={`${zh ? '选择网段' : 'Select prefix'} ${candidate.prefix}`}
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
                          <span className={`inline-flex items-center gap-1 text-[10px] font-bold ${candidate.status === 'existing' ? 'text-emerald-600' : 'text-cyan-600'}`}>
                            {candidate.status === 'existing' ? <Check size={13} /> : <Plus size={13} />}
                            {candidate.status === 'existing' ? (zh ? '已存在' : 'Existing') : (zh ? '待创建' : 'To create')}
                          </span>
                        </label>
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
                  <button type="button" onClick={() => generateFromInterfaces(false)} disabled={interfaceGenerationLoading || interfaceCandidatesLoading || Boolean(interfaceGenerationError) || selectedInterfaceCandidates.size === 0} className="rounded-xl bg-cyan-500 px-4 py-2 text-xs font-bold text-white hover:bg-cyan-600 disabled:opacity-50">
                    {interfaceGenerationLoading ? (zh ? '处理中…' : 'Processing…') : (zh ? `生成所选 (${selectedInterfaceCandidates.size})` : `Generate selected (${selectedInterfaceCandidates.size})`)}
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
                          ? `将处理全部 ${interfaceCandidateSummary.to_create_count.toLocaleString()} 个待创建候选网段，并按原始 CIDR 登记接口 IP。已有网段不会在本次全量操作中补齐。`
                          : `This will process all ${interfaceCandidateSummary.to_create_count.toLocaleString()} pending prefixes and register their interface IPs using the exact CIDRs. Existing prefixes are not included in this bulk action.`}
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
                    <p className="mt-0.5 text-xs text-gray-500">{zh ? '只需先填写 CIDR；名称、网关及其他信息均可选，也可以稍后补充。' : 'Start with the CIDR. Name, gateway and other details are optional and can be added later.'}</p>
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
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
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
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    >
                      {Object.entries(NETWORK_TYPES).map(([key, val]) => (
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
                        className="flex w-full items-center justify-between rounded-xl border border-gray-150 bg-gray-50 px-4 py-3 text-left text-xs font-semibold text-gray-600 transition-colors hover:bg-gray-100"
                      >
                        <span>{zh ? '父网段切分推荐（可选）' : 'Parent subnet recommendation (optional)'}</span>
                        <ChevronDown size={15} className={`text-gray-400 transition-transform ${showSubnetRecommendation ? 'rotate-180' : ''}`} />
                      </button>
                      {showSubnetRecommendation && (
                        <div className="mt-2 space-y-3 rounded-2xl border border-gray-150 bg-gray-50 p-4">
                          <p className="text-[10px] leading-relaxed text-gray-500">
                            {zh ? '按父网段和目标前缀长度查找一个可用子网；推荐结果会填入上方 CIDR。' : 'Find an available child subnet under a parent prefix; the suggestion fills the CIDR field above.'}
                          </p>
                          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                            <div className="space-y-1">
                              <label className="text-[10px] font-semibold text-gray-500">{zh ? '选择父网段' : 'Parent subnet'}</label>
                              <select
                                value={parentSubnetId}
                                onChange={(e) => setParentSubnetId(e.target.value)}
                                className="w-full rounded-xl border border-gray-250 bg-white px-3 py-2 text-xs outline-none focus:border-cyan-400"
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
                                  className="w-24 rounded-xl border border-gray-250 bg-white px-3 py-2 text-xs outline-none focus:border-cyan-400"
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
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
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
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    />
                    <p className="text-[10px] leading-relaxed text-gray-400">{zh ? '若位于此子网，它会从可分配地址中排除；这不是设备关联。' : 'When inside this subnet, the IP is excluded from assignable addresses; it is separate from the device association.'}</p>
                  </div>

                  {/* Gateway Device */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '网关设备' : 'Gateway Device'}</label>
                    <select
                      value={form.gateway_device_id}
                      onChange={(e) => setForm({ ...form, gateway_device_id: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    >
                      <option value="">{zh ? '未绑定' : 'None'}</option>
                      {devices.map((d: any) => (
                        <option key={d.id} value={d.id}>{d.hostname} ({d.ip_address})</option>
                      ))}
                    </select>
                    <p className="text-[10px] leading-relaxed text-gray-400">{zh ? '可选 CMDB 设备关联，用于 IP 定位和 ARP 上下文；不会代填网关 IP。' : 'Optional CMDB device association for IP location and ARP context; it does not set the gateway IP.'}</p>
                  </div>

                  <div className="sm:col-span-2">
                    <details className="overflow-hidden rounded-2xl border border-gray-150 bg-gray-50/60">
                      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-xs font-bold text-gray-700 marker:hidden">
                        <span>{zh ? '高级设置' : 'Advanced settings'}</span>
                        <span className="text-[10px] font-medium text-gray-400">{zh ? '作用域、状态、描述与追踪' : 'Scope, status, description and traceability'}</span>
                      </summary>
                      <div className="grid grid-cols-1 gap-4 border-t border-gray-100 p-4 sm:grid-cols-2">
                  {/* Gateway Interface */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '已保存的接口关联 ID' : 'Saved interface association ID'}</label>
                    <div className="w-full rounded-xl border border-gray-150 bg-gray-100/70 px-4 py-2.5 font-mono text-xs text-gray-500" aria-readonly="true">
                      {editingPrefix?.gateway_interface_id || (zh ? '无' : 'None')}
                    </div>
                    <p className="text-[10px] leading-relaxed text-gray-400">
                      {zh ? '此处需要数据库接口 ID；当前表单未加载接口 ID 选项，因此只读保留已有值，新建时留空。' : 'This field requires a database interface ID. Since interface ID options are not loaded here, existing values are preserved read-only and new prefixes leave it empty.'}
                    </p>
                  </div>

                  {/* VRF Select */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '所属VRF' : 'VRF'}</label>
                    <select
                      value={form.vrf_id}
                      onChange={(e) => setForm({ ...form, vrf_id: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    >
                      <option value="">{zh ? '请选择VRF' : 'None'}</option>
                      {vrfs.map((item) => (
                        <option key={item.id} value={item.id}>{item.vrf_name}</option>
                      ))}
                    </select>
                  </div>

                  {/* VLAN Select */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '关联VLAN' : 'VLAN'}</label>
                    <select
                      value={form.vlan_id}
                      onChange={(e) => setForm({ ...form, vlan_id: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    >
                      <option value="">{zh ? '请选择VLAN' : 'None'}</option>
                      {vlans.map((item) => (
                        <option key={item.id} value={item.id}>VLAN {item.vlan_id} ({item.name})</option>
                      ))}
                    </select>
                  </div>

                  {/* Site Select */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '物理站点' : 'Site'}</label>
                    <select
                      value={form.site_id}
                      onChange={(e) => setForm({ ...form, site_id: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
                    >
                      <option value="">{zh ? '请选择站点' : 'None'}</option>
                      {sites.map((item) => (
                        <option key={item.id} value={item.id}>{item.site_name} ({item.site_code})</option>
                      ))}
                    </select>
                  </div>

                  {/* Tenant Select */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '所属租户' : 'Tenant'}</label>
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

                  {/* Status Select */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-wider text-gray-400 ml-1">{zh ? '网段状态' : 'Status'}</label>
                    <select
                      value={form.status}
                      onChange={(e) => setForm({ ...form, status: e.target.value })}
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50"
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
                      className="w-full px-4 py-2.5 text-xs rounded-xl border border-gray-150 outline-none focus:border-cyan-400 focus:bg-white transition-all font-medium bg-gray-50/50 resize-none"
                    />
                  </div>

                  {/* Traceable Toggle */}
                  <div className="flex items-center justify-between rounded-xl border border-gray-150 bg-gray-50/50 px-4 py-3 sm:col-span-2">
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
              <div className="flex shrink-0 items-center justify-end gap-3 border-t border-gray-100 bg-gray-50 px-4 py-3 sm:px-6 sm:py-4">
                <button
                  type="button"
                  onClick={() => setShowAddEdit(false)}
                  className="px-4 py-2 text-xs font-bold text-gray-500 hover:bg-gray-100 rounded-xl transition-all"
                >
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={isSaving}
                  className="rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 px-6 py-2 text-xs font-extrabold text-white shadow-md transition-all hover:from-cyan-600 hover:to-blue-700 disabled:cursor-wait disabled:opacity-60"
                >
                  {isSaving ? (zh ? '保存中…' : 'Saving…') : (zh ? '确定保存' : 'Save')}
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
                <h3 className="text-base font-bold text-gray-900 mb-2">{zh ? '确认删除网段？' : 'Delete Prefix?'}</h3>
                <p className="text-xs text-gray-500 leading-relaxed">
                  {zh ? '警告：删除此Prefix前缀网段将同时永久删除该网段下登记的所有IP地址数据！此操作无法恢复，请问是否继续？' : 'Warning: Deleting this prefix will also cascade delete all registered IP addresses allocated under this block! This cannot be undone.'}
                </p>
              </div>
              <div className="px-6 py-4 bg-gray-50 flex items-center justify-end gap-3 border-t border-gray-100">
                <button onClick={() => setShowDeleteConfirm(null)} className="px-3 py-1.5 text-xs text-gray-500 hover:bg-gray-100 rounded-lg font-semibold transition-colors">
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button onClick={() => handleDelete(showDeleteConfirm)} className="px-4 py-1.5 text-xs bg-rose-500 hover:bg-rose-600 text-white rounded-lg font-bold transition-colors">
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
