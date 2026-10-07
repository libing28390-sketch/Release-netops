import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Terminal as XTerm } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import 'xterm/css/xterm.css';
import {
  Package, Plus, Trash2, Search, X, RefreshCw, Download, Pencil, Copy,
  Server, Router, AlertTriangle, SlidersHorizontal,
  Wifi, Upload, FileText,
  AlertCircle, CheckCircle2, Info,
  Flame, LayoutList, Lock, Terminal, Eye, EyeOff, Loader2, Shield, User, MonitorSpeaker
} from 'lucide-react';
import { ActionButton, ActionIconButton, ActionIconGroup } from '../../components/ui/ActionIconButton';
import { TableActionCell, TableActionHeader } from '../../components/ui/TableActionColumn';
import * as XLSX from 'xlsx';
import { AnimatePresence, motion } from 'motion/react';

import Pagination from '../../components/Pagination';
import { DataTable, DataTableFrame } from '../../components/DataTable';
import PageHero from '../../components/PageHero';
import TagFilterDropdown from '../../components/TagFilterDropdown';
import { ApiError, apiRequest, authHeaders } from '../../api/http';
import { useSystem } from '../../hooks/useSystem';
import { formatTerminalAgentError, getLocalTerminalConfig, TERMINAL_APP_LABELS } from '../../utils/localTerminal';
import type { TagDefinition } from '../../types';

import { Asset, AssetSummary, AssetManagementTabProps } from './types';
import {
  STATUSES,
  TYPES,
  LIFECYCLE_STATUSES,
  EMPTY_FORM,
  VENDOR_PLATFORMS,
  SERVER_PLATFORMS,
  ALL_PLATFORMS,
  COL_MAP,
  IMPORT_VALUE_MAP,
  NETWORK_IMPORT_PLATFORM_VALUES,
  NETWORK_IMPORT_VENDOR_VALUES,
  NETWORK_TOPOLOGY_ROLE_OPTIONS,
  TOPOLOGY_FUNCTION_OPTIONS,
  TOPOLOGY_ZONE_OPTIONS,
  SSH_ALGORITHM_PROFILE_OPTIONS,
  SSH_ALGORITHM_PROFILE_VALUES,
  isNetworkVendor,
  isValidVendorPlatform,
  normalizeImportedVendor,
  normalizeImportedPlatform,
  isValidIpAddress,
} from './constants';
import { statusMeta, typeMeta, severityOf } from './helpers';
import {
  ASSET_INFO_SHEET_RE,
  MANAGEMENT_ENTRY_SHEET_RE,
  assetTypeForSheetName,
  normalizeImportHeader,
  mergeManagementMethods,
  parseManagementMethodSheet,
  formatAssetImportError,
  type ManagementMethodImportRow,
} from './importUtils';

import { DeleteConfirmModal } from './components/DeleteConfirmModal';
import { AssetImportValidationModal, MissingRackInfo, RackResolution } from './components/AssetImportValidationModal';
import { TerminalAccessModal } from './components/TerminalAccessModal';
import { AssetDetailDrawer } from './components/AssetDetailDrawer';
import { AssetModal } from './components/AssetModal';
import { assetCategoryLabel, buildAssetExportData, fetchAllAssetPages, type AssetExportColumnKey } from './exportUtils';

type AssetImportSkippedItem = {
  asset_tag?: string;
  hostname?: string;
  reason?: string;
  existing_hostname?: string;
  duplicate_labels?: string[];
  duplicate_values?: string[];
  librenms_enrollment?: { status?: string; message?: string };
};

type BatchTakeoverResult = {
  id: string;
  hostname?: string;
  management_ip?: string;
  status: 'blocked_credential' | 'triggered' | 'running' | 'completed' | 'failed' | 'error' | 'timeout' | string;
  message?: string;
  credential_name?: string;
  device_count?: number;
  device_names?: string[];
};

type AssetColumnKey = AssetExportColumnKey;

type AssetLoadIssue = {
  status: number | null;
  message: string;
  permissionDenied: boolean;
};

const getAssetLoadIssue = (error: unknown, language: string, resource: string): AssetLoadIssue => {
  const status = error instanceof ApiError ? error.status : null;
  const zh = language === 'zh';
  const permissionDenied = status === 401 || status === 403;
  const message = status === 401
    ? (zh ? '登录状态已失效，请重新登录后重试。' : 'Your session has expired. Sign in again and retry.')
    : status === 403
      ? (zh ? `你没有权限查看${resource}。` : `You do not have permission to view ${resource.toLowerCase()}.`)
      : (zh ? `${resource}加载失败，请重试。` : `Unable to load ${resource.toLowerCase()}. Retry to check again.`);
  return { status, message, permissionDenied };
};

const getAssetSaveErrorMessage = (error: unknown, language: string, secretValues: string[]) => {
  const zh = language === 'zh';
  if (error instanceof ApiError && error.status === 401) return zh ? '登录状态已失效，请重新登录后再保存。' : 'Your session has expired. Sign in again before saving.';
  if (error instanceof ApiError && error.status === 403) return zh ? '你没有权限保存资产。' : 'You do not have permission to save assets.';
  if (error instanceof ApiError && (error.status === 400 || error.status === 422)) {
    let detail = typeof error.detail === 'string' ? error.detail : (zh ? '保存校验失败，请检查填写内容。' : 'Validation failed. Check the form and retry.');
    for (const secret of secretValues.filter(Boolean)) detail = detail.split(secret).join('[已隐藏]');
    return detail;
  }
  if (error instanceof ApiError && error.status >= 500) {
    return `${zh ? '服务暂时不可用，请稍后重试。' : 'The service is temporarily unavailable. Retry shortly.'}${error.requestId ? ` (${zh ? '请求编号' : 'Request ID'}: ${error.requestId})` : ''}`;
  }
  if (error instanceof ApiError) return `${zh ? '保存失败，请重试。' : 'Save failed. Retry.'}${error.requestId ? ` (${zh ? '请求编号' : 'Request ID'}: ${error.requestId})` : ''}`;
  return zh ? '网络错误，资产未保存。请检查连接后重试。' : 'Network error. The asset was not saved. Check your connection and retry.';
};

type AssetColumnDefinition = {
  key: AssetColumnKey;
  zh: string;
  en: string;
  width: string;
};

const ASSET_COLUMN_DEFS: AssetColumnDefinition[] = [
  { key: 'hostname', zh: '设备', en: 'Device', width: 'min-w-[150px]' },
  { key: 'asset_tag', zh: '资产编号', en: 'Asset tag', width: 'min-w-[130px]' },
  { key: 'asset_type', zh: '资产类型', en: 'Asset type', width: 'min-w-[110px]' },
  { key: 'device_category', zh: '设备分类', en: 'Category', width: 'min-w-[120px]' },
  { key: 'device_role', zh: '设备角色', en: 'Role', width: 'min-w-[110px]' },
  { key: 'site', zh: '站点', en: 'Site', width: 'min-w-[120px]' },
  { key: 'rack', zh: '机柜', en: 'Rack', width: 'min-w-[110px]' },
  { key: 'rack_unit', zh: 'U位', en: 'Rack U', width: 'w-20' },
  { key: 'status', zh: '在线状态', en: 'Status', width: 'w-[90px]' },
  { key: 'tags', zh: '标签', en: 'Tags', width: 'min-w-[120px]' },
  { key: 'vendor', zh: '厂商', en: 'Vendor', width: 'w-24' },
  { key: 'model', zh: '型号', en: 'Model', width: 'min-w-[110px]' },
  { key: 'serial_number', zh: '序列号', en: 'Serial', width: 'min-w-[130px]' },
  { key: 'management_ip', zh: '管理IP', en: 'Management IP', width: 'w-[120px]' },
  { key: 'ssh_algorithm_profile', zh: 'SSH算法策略', en: 'SSH algorithm', width: 'min-w-[150px]' },
  { key: 'lifecycle', zh: '资产状态', en: 'Asset status', width: 'w-[90px]' },
  { key: 'created_at', zh: '创建时间', en: 'Created', width: 'min-w-[145px]' },
  { key: 'updated_at', zh: '更新时间', en: 'Updated', width: 'min-w-[145px]' },
];

const DEFAULT_ASSET_COLUMNS: Record<AssetColumnKey, boolean> = {
  hostname: true,
  asset_tag: true,
  asset_type: true,
  device_category: true,
  device_role: true,
  site: true,
  rack: true,
  rack_unit: true,
  status: true,
  tags: false,
  vendor: true,
  model: true,
  serial_number: true,
  management_ip: true,
  ssh_algorithm_profile: false,
  lifecycle: true,
  created_at: true,
  updated_at: true,
};

const DEFAULT_VISIBLE_ASSET_COLUMNS = ASSET_COLUMN_DEFS.filter(column => DEFAULT_ASSET_COLUMNS[column.key]);

const NETWORK_TEMPLATE_ROLES = new Set<string>(NETWORK_TOPOLOGY_ROLE_OPTIONS.map(option => option.value));
const NETWORK_TEMPLATE_CATEGORIES = new Set([
  'switch', 'router', 'firewall', 'load_balancer', 'wireless_controller', 'wireless_ap', 'sdwan_edge', 'vpn_gateway', 'other_network',
]);
const SERVER_TEMPLATE_ROLES = new Set([
  'application_server', 'database_server', 'web_server', 'file_server', 'middleware_server',
  'virtual_host', 'storage', 'backup_server', 'other_server',
]);
const SERVER_TEMPLATE_CATEGORIES = new Set([
  'rack_server', 'blade_server', 'tower_server', 'high_density', 'gpu_server', 'storage_server', 'virtual_host', 'other_server',
]);

const FALLBACK_TEMPLATE_DATE_FORMAT = 'yyyy/mm/dd';

const toFallbackTemplateExcelSerial = (value: unknown): number | null => {
  if (value instanceof Date) {
    return (Date.UTC(value.getUTCFullYear(), value.getUTCMonth(), value.getUTCDate()) - Date.UTC(1899, 11, 30)) / 86400000;
  }
  const match = String(value ?? '').trim().match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const timestamp = Date.UTC(year, month - 1, day);
  const parsed = new Date(timestamp);
  if (parsed.getUTCFullYear() !== year || parsed.getUTCMonth() !== month - 1 || parsed.getUTCDate() !== day) return null;
  return (timestamp - Date.UTC(1899, 11, 30)) / 86400000;
};

const formatFallbackTemplateDateColumns = (worksheet: XLSX.WorkSheet, headers: string[]) => {
  const dateColumns = headers
    .map((header, index) => ({ header, index }))
    .filter(({ header }) => ['购买日期', '保修到期', 'Purchase Date', 'Warranty Expiry'].includes(header));
  const range = worksheet['!ref'] ? XLSX.utils.decode_range(worksheet['!ref']) : null;
  if (!range || dateColumns.length === 0) return;

  for (const { index } of dateColumns) {
    for (let rowIndex = range.s.r + 1; rowIndex <= range.e.r; rowIndex += 1) {
      const address = XLSX.utils.encode_cell({ r: rowIndex, c: index });
      const cell = worksheet[address];
      if (!cell || cell.v === '' || cell.v == null) continue;
      const serial = typeof cell.v === 'number' ? cell.v : toFallbackTemplateExcelSerial(cell.v);
      if (serial == null || !Number.isFinite(serial)) continue;
      cell.v = serial;
      cell.t = 'n';
      cell.z = FALLBACK_TEMPLATE_DATE_FORMAT;
    }
  }
};

const AssetManagementTab: React.FC<AssetManagementTabProps> = ({ language, setActiveTab }) => {
  const { systemInfo } = useSystem();
  const zh = language === 'zh';
  const goTo = (tab: string) => setActiveTab?.(tab);

  /* ─── State ─── */
  const [assets, setAssets]             = useState<Asset[]>([]);
  const [sites, setSites]               = useState<Array<{ id: string; site_name: string; site_code: string }>>([]);
  const [summary, setSummary]           = useState<AssetSummary | null>(null);
  const [summaryError, setSummaryError] = useState<AssetLoadIssue | null>(null);
  const [sitesError, setSitesError] = useState<AssetLoadIssue | null>(null);
  const [total, setTotal]               = useState(0);
  const [page, setPage]                 = useState(1);
  const [pageSize, setPageSize]         = useState(20);
  const [loading, setLoading]           = useState(true);
  const [assetError, setAssetError] = useState<AssetLoadIssue | null>(null);
  const [assetsLastLoadedAt, setAssetsLastLoadedAt] = useState<Date | null>(null);
  const assetFetchSequenceRef = React.useRef(0);

  const [search, setSearch]             = useState('');
  const [typeFilter, setTypeFilter]     = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [vendorFilter, setVendorFilter] = useState('all');
  const [dcFilter, setDcFilter]         = useState('all');
  const [deviceCategoryFilter, setDeviceCategoryFilter] = useState('');
  const [tagFilter, setTagFilter]       = useState<string[]>([]);
  const [terminalSession, setTerminalSession] = useState<{ token: string; title: string } | null>(null);
  const [terminalLines, setTerminalLines] = useState<string>('');
  const [terminalInput, setTerminalInput] = useState('');
  const terminalWsRef = React.useRef<WebSocket | null>(null);
  const [terminals, setTerminals] = useState<Record<string, { term: XTerm; fit: FitAddon }>>({});
  const [showApprovalModal, setShowApprovalModal] = useState(false);
  const [approvalData, setApprovalData] = useState({ ticket: '', reason: '', mfa: '' });
  const [isApproved, setIsApproved] = useState(false);

  /* ─── Terminal/PAM State ─── */
  const [terminalTarget, setTerminalTarget] = useState<Asset | null>(null);
  const [terminalAccessLevel, setTerminalAccessLevel] = useState<'normal' | 'admin'>('normal');
  const [terminalReason, setTerminalReason] = useState('');
  const [terminalRequesting, setTerminalRequesting] = useState(false);

  const initTerminal = (container: HTMLDivElement, id: string) => {
    if (terminals[id]) return;
    const term = new XTerm({
      cursorBlink: true,
      fontSize: 12,
      fontFamily: 'JetBrains Mono, Menlo, Monaco, Consolas, "Courier New", monospace',
      theme: { background: '#0b1220', foreground: '#dbeafe', cursor: '#00bceb' },
    });
    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(container);
    fitAddon.fit();

    term.onData(data => {
      if (terminalWsRef.current?.readyState === WebSocket.OPEN) {
        terminalWsRef.current.send(data);
      }
    });

    setTerminals(prev => ({ ...prev, [id]: { term, fit: fitAddon } }));
  };

  const [feedbackMsg, setFeedbackMsg] = useState<{
    type: 'success' | 'error' | 'warning' | 'info';
    text: string;
    details?: string[];
  } | null>(null);
  const [deptFilter, setDeptFilter]     = useState('all');
  const [severityFilter, setSeverityFilter] = useState<string>('all');
  const [lifecycleFilter, setLifecycleFilter] = useState('all');

  const [selectedIds, setSelectedIds]   = useState<Set<string>>(new Set());
  const [drawerAsset, setDrawerAsset]   = useState<Asset | null>(null);

  const [showModal, setShowModal]       = useState(false);
  const [editingAsset, setEditingAsset] = useState<Asset | null>(null);
  const [form, setForm]                 = useState({ ...EMPTY_FORM });
  const [saving, setSaving]             = useState(false);
  const saveInFlightRef = React.useRef(false);
  const [deleteTarget, setDeleteTarget] = useState<Asset | null>(null);
  const [deleteError, setDeleteError]   = useState<string | null>(null);
  const [showProductionConfirm, setShowProductionConfirm] = useState(false);
  const [showBatchTakeoverConfirm, setShowBatchTakeoverConfirm] = useState(false);
  const [modalError, setModalError] = useState<string | null>(null);
  const [showEnableSecret, setShowEnableSecret] = useState(false);
  const [showAdvancedFilter, setShowAdvancedFilter] = useState(false);
  const [rotatingAssetId, setRotatingAssetId] = useState<string | null>(null);
  const [batchTakeoverResults, setBatchTakeoverResults] = useState<BatchTakeoverResult[]>([]);
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const rotationPollRef = React.useRef<any>(null);
  const batchTakeoverPollRef = React.useRef<any>(null);

  const [allRacks, setAllRacks] = useState<any[]>([]);
  const [showValidationModal, setShowValidationModal] = useState(false);
  const [missingRacks, setMissingRacks] = useState<MissingRackInfo[]>([]);
  const [pendingImportPayload, setPendingImportPayload] = useState<any[]>([]);
  const [validationModalSaving, setValidationModalSaving] = useState(false);
  const [allTags, setAllTags] = useState<TagDefinition[]>([]);
  const fetchAllRacks = useCallback(async () => {
    try {
      const data = await apiRequest<{ success?: boolean; data?: unknown }>('/api/racks');
      if (data.success && Array.isArray(data.data)) setAllRacks(data.data);
      else throw new Error('Invalid rack lookup response');
    } catch (error) {
      setFeedbackMsg({ type: 'error', text: getAssetLoadIssue(error, language, zh ? '机柜选项' : 'Rack options').message });
    }
  }, [language, zh]);

  useEffect(() => {
    fetchAllRacks();
  }, [fetchAllRacks]);

  useEffect(() => {
    apiRequest<{ data?: unknown }>('/api/tags/definitions')
      .then(payload => {
        if (!Array.isArray(payload?.data)) throw new Error('Invalid tag lookup response');
        setAllTags(payload.data as TagDefinition[]);
      })
      .catch(error => setFeedbackMsg({ type: 'error', text: getAssetLoadIssue(error, language, zh ? '标签选项' : 'Tag options').message }));
  }, [language, zh]);

  useEffect(() => () => {
    if (rotationPollRef.current) clearInterval(rotationPollRef.current);
    if (batchTakeoverPollRef.current) clearInterval(batchTakeoverPollRef.current);
  }, []);

  const fetchSummary = useCallback(async () => {
    try {
      const payload = await apiRequest<AssetSummary>('/api/assets/summary');
      setSummary(payload);
      setSummaryError(null);
    } catch (error) {
      setSummaryError(getAssetLoadIssue(error, language, zh ? '资产概览' : 'asset summary'));
    }
  }, [language, zh]);

  const fetchSites = useCallback(async () => {
    try {
      const payload = await apiRequest<{ data?: unknown }>('/api/cmdb/sites');
      if (!Array.isArray(payload?.data)) throw new Error('Invalid site lookup response');
      setSites(payload.data as Array<{ id: string; site_name: string; site_code: string }>);
      setSitesError(null);
    } catch (error) {
      setSitesError(getAssetLoadIssue(error, language, zh ? '站点选项' : 'site options'));
    }
  }, [language, zh]);

  const buildAssetParams = useCallback((requestedPage: number, requestedPageSize: number) => {
    const params = new URLSearchParams({
      page: String(requestedPage),
      page_size: String(requestedPageSize),
    });
    if (search.trim()) params.set('q', search.trim());
    if (typeFilter !== 'all') params.set('asset_type', typeFilter);
    if (statusFilter !== 'all') params.set('status', statusFilter);
    if (vendorFilter !== 'all') params.set('vendor', vendorFilter);
    if (dcFilter !== 'all') params.set('site_id', dcFilter);
    if (deptFilter !== 'all') params.set('department', deptFilter);
    if (deviceCategoryFilter) params.set('device_category', deviceCategoryFilter);
    if (lifecycleFilter !== 'all') params.set('lifecycle_status', lifecycleFilter);
    if (tagFilter.length > 0) params.set('tag_ids', tagFilter.join(','));
    return params;
  }, [search, typeFilter, statusFilter, vendorFilter, dcFilter, deptFilter, deviceCategoryFilter, lifecycleFilter, tagFilter]);

  const fetchAssets = useCallback(async () => {
    const requestSequence = ++assetFetchSequenceRef.current;
    setLoading(true);
    setAssetError(null);
    try {
      const params = buildAssetParams(page, pageSize);
      const payload = await apiRequest<{ items?: unknown; total?: unknown }>(`/api/assets?${params}`);
      if (!Array.isArray(payload.items)) throw new Error('Invalid asset list response');
      if (requestSequence !== assetFetchSequenceRef.current) return;
      setAssets(payload.items as Asset[]);
      setTotal(Number(payload.total) || 0);
      setAssetsLastLoadedAt(new Date());
    } catch (error) {
      if (requestSequence === assetFetchSequenceRef.current) {
        setAssetError(getAssetLoadIssue(error, language, zh ? '资产列表' : 'asset list'));
      }
    } finally {
      if (requestSequence === assetFetchSequenceRef.current) setLoading(false);
    }
  }, [buildAssetParams, language, page, pageSize, zh]);

  const exportAssetData = useCallback(async () => {
    const allAssets = await fetchAllAssetPages(async (requestedPage, requestedPageSize) => {
      const params = buildAssetParams(requestedPage, requestedPageSize);
      const response = await fetch(`/api/assets?${params}`, { headers: authHeaders() });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.detail || payload.message || (zh ? '读取完整资产清单失败' : 'Failed to load the complete asset list'));
      }
      if (!Array.isArray(payload.items)) {
        throw new Error(zh ? '资产清单响应格式无效' : 'Invalid asset list response');
      }
      return { items: payload.items as Asset[], total: Number(payload.total) || 0 };
    });

    const filteredAssets = severityFilter === 'all'
      ? allAssets
      : allAssets.filter((asset) => severityOf(asset) === severityFilter);
    return buildAssetExportData(filteredAssets, ASSET_COLUMN_DEFS, zh ? 'zh' : 'en');
  }, [buildAssetParams, severityFilter, zh]);

  useEffect(() => { fetchSummary(); }, [fetchSummary]);
  useEffect(() => { fetchSites(); }, [fetchSites]);
  useEffect(() => { fetchAssets(); }, [fetchAssets]);
  useEffect(() => { setPage(1); }, [search, typeFilter, statusFilter, vendorFilter, dcFilter, deptFilter, deviceCategoryFilter, lifecycleFilter, tagFilter, pageSize, severityFilter]);

  useEffect(() => {
    if (!drawerAsset) return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setDrawerAsset(null); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [drawerAsset]);

  useEffect(() => {
    if (!feedbackMsg) return;
    if (rotatingAssetId) return;
    if (feedbackMsg.type === 'warning' && feedbackMsg.details?.length) return;
    const t = setTimeout(() => setFeedbackMsg(null), feedbackMsg.type === 'error' || feedbackMsg.type === 'warning' ? 10000 : 5000);
    return () => clearTimeout(t);
  }, [feedbackMsg, rotatingAssetId]);

  const vendorList = useMemo(() => summary?.by_vendor ? Object.keys(summary.by_vendor).sort() : [], [summary]);
  const dcList = useMemo(
    () => sites
      .map(site => ({ value: site.id, label: site.site_name || site.site_code || site.id }))
      .sort((a, b) => a.label.localeCompare(b.label)),
    [sites],
  );
  const deptList   = useMemo(() => summary?.by_department ? Object.keys(summary.by_department).sort() : [], [summary]);

  const criticalCount  = (summary?.by_status?.['inactive'] ?? 0) + (summary?.by_status?.['decommissioned'] ?? 0);
  const majorCount     = (summary?.by_status?.['maintenance'] ?? 0);
  const warningCount   = (summary?.warranty_expiring_soon ?? 0) + (summary?.by_status?.['in_storage'] ?? 0);
  const healthyCount   = summary?.by_status?.['active'] ?? 0;
  const totalCount     = summary
    ? (summary.by_type?.network_device ?? 0) + (summary.by_type?.server ?? 0)
    : 0;

  const displayAssets = useMemo(() => {
    let result = assets;
    if (severityFilter !== 'all') result = result.filter(a => severityOf(a) === severityFilter);
    if (lifecycleFilter !== 'all') result = result.filter(a => (a.lifecycle_status || 'staging') === lifecycleFilter);
    return result;
  }, [assets, severityFilter, lifecycleFilter]);

  const hasFilters = Boolean(
    search.trim() ||
    typeFilter !== 'all' ||
    statusFilter !== 'all' ||
    tagFilter.length > 0 ||
    vendorFilter !== 'all' ||
    dcFilter !== 'all' ||
    deptFilter !== 'all' ||
    lifecycleFilter !== 'all' ||
    deviceCategoryFilter ||
    severityFilter !== 'all'
  );

  const advancedFilterCount = [
    vendorFilter !== 'all',
    dcFilter !== 'all',
    deptFilter !== 'all',
    lifecycleFilter !== 'all',
    Boolean(deviceCategoryFilter),
  ].filter(Boolean).length;

  const clearAllFilters = () => {
    setSearch('');
    setTypeFilter('all');
    setStatusFilter('all');
    setTagFilter([]);
    setVendorFilter('all');
    setDcFilter('all');
    setDeptFilter('all');
    setLifecycleFilter('all');
    setDeviceCategoryFilter('');
    setSeverityFilter('all');
  };

  const openAdd = () => {
    setEditingAsset(null);
    setForm({ ...EMPTY_FORM });
    setModalError(null);
    setShowEnableSecret(false);
    setShowModal(true);
  };

  const openEdit = (a: Asset) => {
    setEditingAsset(a);
    setModalError(null);
    setShowEnableSecret(!!(a as any).enable_password_set || !!(a as any).enable_password);
    setForm({
      asset_type: a.asset_type, asset_tag: a.asset_tag, serial_number: a.serial_number,
      vendor: a.vendor, model: a.model, hostname: a.hostname, site_id: a.site_id || '',
      rack: a.rack, rack_unit: a.rack_unit,
      u_height: String(a.u_height ?? 1),
      planned_start_u: a.planned_start_u != null && a.planned_start_u !== undefined ? String(a.planned_start_u) : '',
      management_ip: a.management_ip,
      business_ip: a.business_ip, device_role: a.device_role,
      vlan: a.vlan || '', uplink_switch: a.uplink_switch || '', uplink_port: a.uplink_port || '',
      status: a.status, lifecycle_status: a.lifecycle_status || 'staging', asset_origin: a.asset_origin || 'legacy', takeover_exempt_reason: '',
      purchase_date: a.purchase_date, warranty_expiry: a.warranty_expiry,
      department: a.department, notes: a.notes,
      platform: normalizeImportedPlatform((a as any).platform || (a.asset_type === 'server' ? 'linux' : 'cisco_ios')),
      connection_method: (a as any).connection_method || 'ssh',
      ssh_algorithm_profile: a.ssh_algorithm_profile || 'auto',
      username: (a as any).username || '',
      password: '',
      normal_username: (a as any).normal_username || '',
      normal_password: '',
      admin_username: (a as any).admin_username || '',
      admin_password: '',
      enable_password: '',
      auth_model: 'dual',
      // Asset responses expose only a configured flag; never hydrate a secret
      // into an editable field, so an untouched save cannot echo it back.
      snmp_community: '',
      snmp_port: String((a as any).snmp_port || '161'),
      snmp_credential_id: (a as any).snmp_credential_id || '',
      snmp_community_set: Boolean((a as any).snmp_community_set),
      management_port: String(a.management_port ?? '22'),
      winrm_enabled: Boolean(a.winrm_enabled),
      winrm_port: String(a.winrm_port ?? 5986),
      winrm_auth_mode: a.winrm_auth_mode || 'ntlm',
      winrm_tls_mode: a.winrm_tls_mode || 'pin_fingerprint',
      winrm_cert_fingerprint: a.winrm_cert_fingerprint || '',
      device_category: a.device_category || '',
      function: a.function || '',
      zone: a.zone || 'Unknown',
      power_watts: a.power_watts != null ? String(a.power_watts) : '',
      credential_id: (a as any).credential_id || '',
      admin_credential_id: (a as any).admin_credential_id || '',
      tag_ids: (a.tags || []).filter(tag => tag.category !== 'system_auto').map(tag => tag.id),
      web_profiles: (a.web_profiles || []).map(profile => ({
        ...profile,
        port: String(profile.port),
        normal_password: '',
        admin_password: '',
      })),
    });
    setShowModal(true);
  };

  const startRotationPoll = useCallback((assetId: string) => {
    if (rotationPollRef.current) clearInterval(rotationPollRef.current);
    setRotatingAssetId(assetId);
    setFeedbackMsg({ type: 'info', text: zh ? '⏳ 口令上收中，上收成功后将自动投产...' : '⏳ Taking over credentials. Production status will be applied after success...' });
    let attempts = 0;
    rotationPollRef.current = setInterval(async () => {
      attempts++;
      try {
        const r = await fetch(`/api/assets/${assetId}/rotation-status`, { headers: authHeaders() });
        if (!r.ok) return;
        const d = await r.json();
        if (d.rotation_status === 'completed') {
          clearInterval(rotationPollRef.current);
          rotationPollRef.current = undefined;
          setRotatingAssetId(null);
          setFeedbackMsg({ type: 'success', text: zh ? '✅ 已投产，默认口令已自动修改上收。' : '✅ Marked as production. Password auto-rotated.' });
          fetchAssets();
        } else if (d.rotation_status === 'failed') {
          clearInterval(rotationPollRef.current);
          rotationPollRef.current = undefined;
          setRotatingAssetId(null);
          setFeedbackMsg({ type: 'warning', text: zh ? '⚠️ 口令自动轮换失败，投产已回滚。' : '⚠️ Auto-rotation failed, production reverted.' });
          fetchAssets();
        } else if (attempts >= 60) {
          clearInterval(rotationPollRef.current);
          rotationPollRef.current = undefined;
          setRotatingAssetId(null);
          setFeedbackMsg({ type: 'warning', text: zh ? '口令上收超时，请稍后到凭据管理页面确认。' : 'Rotation timed out. Please check credentials page later.' });
        }
      } catch { /* ignore network blips */ }
    }, 2000);
  }, [zh, fetchAssets]);

  const doSave = async (overrides: Record<string, unknown> = {}) => {
    if (saveInFlightRef.current) return;
    saveInFlightRef.current = true;
    setSaving(true);
    setModalError(null);
    try {
      const url = editingAsset ? `/api/assets/${editingAsset.id}` : '/api/assets';
      const plannedRaw = String(form.planned_start_u ?? '').trim();
      let planned_start_u: number | null = null;
      if (plannedRaw) {
        const n = parseInt(plannedRaw, 10);
        if (!Number.isNaN(n) && n >= 1 && n <= 60) planned_start_u = n;
      }
      // Guard: a server must never carry a network-device platform (e.g. stale
      // cisco_ios). If the stored value isn't a valid server platform, coerce
      // it to a sane Linux default so we don't persist an inconsistent platform.
      let normalizedPlatform = normalizeImportedPlatform(form.platform);
      if (form.asset_type === 'server') {
        const serverValues = SERVER_PLATFORMS.map(p => p.value);
        if (!serverValues.includes(normalizedPlatform)) {
          normalizedPlatform = 'linux';
        }
      } else if (form.asset_type === 'network_device') {
        const vendorPlatforms = VENDOR_PLATFORMS[normalizeImportedVendor(String(form.vendor || ''))] || [];
        if (vendorPlatforms.length > 0 && !vendorPlatforms.some(p => p.value === normalizedPlatform)) {
          normalizedPlatform = vendorPlatforms[0].value;
        }
      }
      const requestedSshProfile = String(overrides.ssh_algorithm_profile ?? form.ssh_algorithm_profile ?? 'auto');
      const normalizedSshProfile = SSH_ALGORITHM_PROFILE_VALUES.includes(requestedSshProfile as typeof SSH_ALGORITHM_PROFILE_VALUES[number])
        ? requestedSshProfile
        : 'auto';
      const payload = {
        ...form,
        ...overrides,
        platform: normalizedPlatform,
        ssh_algorithm_profile: normalizedSshProfile,
        u_height: Math.max(1, Math.min(60, parseInt(String(form.u_height), 10) || 1)),
        planned_start_u,
        power_watts: parseInt(String(form.power_watts), 10) || 0,
        winrm_port: parseInt(String(form.winrm_port), 10) || 5986,
        enable_password: (form.enable_password || '').trim(),
        web_profiles: (form.web_profiles || []).map((profile: any) => ({
          ...(profile.id ? { id: profile.id } : {}),
          profile_name: String(profile.profile_name || '').trim() || (form.asset_type === 'server' ? 'BMC' : 'Web管理'),
          scheme: profile.scheme === 'http' ? 'http' : 'https',
          port: parseInt(String(profile.port), 10) || (profile.scheme === 'http' ? 80 : 443),
          path: String(profile.path || '/').trim() || '/',
          enabled: profile.enabled !== false,
          credential_mode: profile.credential_mode === 'independent' ? 'independent' : 'inherit_asset',
          normal_username: String(profile.normal_username || '').trim(),
          normal_password: String(profile.normal_password || ''),
          admin_username: String(profile.admin_username || '').trim(),
          admin_password: String(profile.admin_password || ''),
          credential_id: String(profile.credential_id || '').trim(),
          admin_credential_id: String(profile.admin_credential_id || '').trim(),
        })),
      };
      const data = await apiRequest<any>(url, {
        method: editingAsset ? 'PUT' : 'POST',
        body: JSON.stringify(payload),
      });
      setShowModal(false);
      setShowProductionConfirm(false);
      fetchAssets();
      fetchSummary();
      if (data?.rotation_pending && editingAsset) {
        startRotationPoll(editingAsset.id);
      } else if (data?.legacy_exempt) {
        setFeedbackMsg({ type: 'success', text: zh ? '存量设备已免上收投产，可使用普通账号执行只读任务。' : 'Legacy device marked as production without takeover; read-only tasks remain available.' });
      } else if (data?.password_rotated) {
        setFeedbackMsg({ type: 'success', text: zh ? '已投产，默认口令已自动修改上收。' : 'Marked as production. Default password has been auto-rotated.' });
      } else if (data?.lifecycle_reverted && data?.rotation_detail) {
        setFeedbackMsg({ type: 'warning', text: zh ? `口令自动轮换失败，投产已回滚: ${data.rotation_detail}` : `Auto-rotation failed, production transition reverted: ${data.rotation_detail}` });
        fetchAssets();
      } else if (data?.rotation_detail) {
        setFeedbackMsg({ type: 'warning', text: zh ? `已投产，但口令自动轮换失败: ${data.rotation_detail}` : `Marked as production, but auto-rotation failed: ${data.rotation_detail}` });
      }
    } catch (error) {
      setShowProductionConfirm(false);
      setModalError(getAssetSaveErrorMessage(error, language, [
        String(form.password || ''),
        String(form.normal_password || ''),
        String(form.admin_password || ''),
        String(form.enable_password || ''),
        String(form.snmp_community || ''),
        ...(Array.isArray(form.web_profiles) ? form.web_profiles.flatMap((profile: any) => [String(profile.normal_password || ''), String(profile.admin_password || '')]) : []),
      ]));
    } finally {
      saveInFlightRef.current = false;
      setSaving(false);
    }
  };

  const handleSave = async () => {
    if (!form.hostname.trim() && !form.asset_tag.trim()) {
      setModalError(zh ? '主机名和资产编号至少填写一项' : 'Hostname or Asset Tag is required');
      return;
    }
    const mgmtIp = String(form.management_ip || '').trim();
    if (mgmtIp && !isValidIpAddress(mgmtIp)) {
      setModalError(zh ? `管理IP "${mgmtIp}" 格式不正确，请输入有效的 IPv4 或 IPv6 地址` : `Management IP "${mgmtIp}" is not a valid IP address`);
      return;
    }
    const bizIp = String(form.business_ip || '').trim();
    if (bizIp && !isValidIpAddress(bizIp)) {
      setModalError(zh ? `业务IP "${bizIp}" 格式不正确，请输入有效的 IPv4 或 IPv6 地址` : `Business IP "${bizIp}" is not a valid IP address`);
      return;
    }
    const oldLifecycle = editingAsset ? (editingAsset.lifecycle_status || 'staging') : 'staging';
    if (editingAsset && form.lifecycle_status === 'production' && oldLifecycle !== 'production') {
      setShowProductionConfirm(true);
      return;
    }
    await doSave();
  };

  const openCopy = (a: Asset) => {
    setEditingAsset(null);
    const copyTag = a.asset_tag ? `${a.asset_tag}-${Date.now().toString(36).slice(-4)}` : '';
    setForm({
      asset_type: a.asset_type, asset_tag: copyTag, serial_number: '',
      vendor: a.vendor, model: a.model, hostname: '', site_id: a.site_id || '',
      rack: a.rack, rack_unit: '', u_height: String(a.u_height ?? 1), planned_start_u: a.planned_start_u != null ? String(a.planned_start_u) : '', management_ip: '',
      business_ip: '', device_role: a.device_role,
      vlan: a.vlan || '', uplink_switch: a.uplink_switch || '', uplink_port: a.uplink_port || '',
      status: a.status, lifecycle_status: 'staging', asset_origin: 'new', takeover_exempt_reason: '',
      purchase_date: a.purchase_date, warranty_expiry: a.warranty_expiry,
      department: a.department, notes: a.notes,
      platform: a.platform || (a.asset_type === 'server' ? 'linux' : 'cisco_ios'),
      connection_method: a.connection_method || 'ssh',
      ssh_algorithm_profile: a.ssh_algorithm_profile || 'auto',
      username: a.username || '',
      password: '',
      normal_username: (a as any).normal_username || '',
      normal_password: '',
      admin_username: (a as any).admin_username || '',
      admin_password: '',
      enable_password: '',
      auth_model: 'dual',
      snmp_community: a.snmp_community || '',
      snmp_port: String(a.snmp_port || '161'),
      snmp_credential_id: (a as any).snmp_credential_id || '',
      snmp_community_set: Boolean((a as any).snmp_community_set),
      management_port: String(a.management_port ?? '22'),
      winrm_enabled: Boolean(a.winrm_enabled),
      winrm_port: String(a.winrm_port ?? 5986),
      winrm_auth_mode: a.winrm_auth_mode || 'ntlm',
      winrm_tls_mode: a.winrm_tls_mode || 'pin_fingerprint',
      winrm_cert_fingerprint: a.winrm_cert_fingerprint || '',
      device_category: a.device_category || '',
      function: a.function || '',
      zone: a.zone || 'Unknown',
      power_watts: a.power_watts != null ? String(a.power_watts) : '',
      credential_id: (a as any).credential_id || '',
      admin_credential_id: (a as any).admin_credential_id || '',
      tag_ids: (a.tags || []).filter(tag => tag.category !== 'system_auto').map(tag => tag.id),
      web_profiles: (a.web_profiles || []).map(profile => ({
        profile_name: profile.profile_name,
        scheme: profile.scheme,
        port: String(profile.port),
        path: profile.path,
        enabled: profile.enabled,
        credential_mode: profile.credential_mode || 'inherit_asset',
        normal_username: profile.normal_username || '',
        normal_password: '',
        admin_username: profile.admin_username || '',
        admin_password: '',
        credential_id: profile.credential_id || '',
        admin_credential_id: profile.admin_credential_id || '',
      })),
    });
    setModalError(null);
    setShowModal(true);
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleteError(null);
    try {
      await apiRequest(`/api/assets/${deleteTarget.id}`, { method: 'DELETE' });
      setDeleteTarget(null);
      fetchAssets();
      fetchSummary();
      if (drawerAsset?.id === deleteTarget.id) setDrawerAsset(null);
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : (zh ? '删除资产失败' : 'Failed to delete asset'));
    }
  };

  const toggle    = (id: string) => setSelectedIds(p => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const toggleAll = () => setSelectedIds(p => p.size === displayAssets.length ? new Set() : new Set(displayAssets.map(a => a.id)));
  const clearSel  = () => setSelectedIds(new Set());

  const handleBatchDelete = async () => {
    if (selectedIds.size === 0) return;
    if (!confirm(zh ? '确定删除选中的资产吗？' : 'Delete selected assets?')) return;
    const promises = Array.from(selectedIds).map(id =>
      apiRequest(`/api/assets/${id}`, { method: 'DELETE' })
    );
    const results = await Promise.allSettled(promises);
    const failures = results
      .filter((result): result is PromiseRejectedResult => result.status === 'rejected')
      .map(result => result.reason instanceof Error ? result.reason.message : (zh ? '删除资产失败' : 'Failed to delete asset'));
    if (failures.length > 0) {
      setFeedbackMsg({
        type: 'error',
        text: zh ? `${failures.length} 台资产删除失败` : `${failures.length} asset(s) failed to delete`,
        details: failures.slice(0, 8),
      });
    }
    clearSel();
    fetchAssets();
    fetchSummary();
  };

  const handleBatchTakeover = async () => {
    if (selectedIds.size === 0) return;

    setLoading(true);
    try {
      const r = await fetch('/api/assets/takeover/batch', {
        method: 'POST',
        headers: authHeaders(true),
        body: JSON.stringify({ asset_ids: Array.from(selectedIds) })
      });
      if (r.ok) {
        const data = await r.json();
        const results = Array.isArray(data.results) ? data.results as BatchTakeoverResult[] : [];
        setBatchTakeoverResults(results.map(item => item.status === 'triggered' ? { ...item, status: 'running' } : item));

        const blocked = results.filter(item => item.status === 'blocked_credential');
        const triggered = results.filter(item => item.status === 'triggered');
        const failedToStart = results.filter(item => item.status === 'error');
        // The result panel is the persistent status surface. Avoid stacking a
        // large fixed warning toast on top of it, especially when many devices
        // are blocked by the same shared credential.
        setFeedbackMsg(null);

        if (batchTakeoverPollRef.current) clearInterval(batchTakeoverPollRef.current);
        if (triggered.length) {
          const startedAt = Date.now();
          batchTakeoverPollRef.current = setInterval(async () => {
            const snapshots = await Promise.all(triggered.map(async item => {
              try {
                const response = await fetch(`/api/assets/${encodeURIComponent(item.id)}/rotation-status`, { headers: authHeaders() });
                const statusData = await response.json().catch(() => ({}));
                const rotationStatus = String(statusData.rotation_status || '').toLowerCase();
                if (rotationStatus === 'completed') return { ...item, status: 'completed', message: zh ? '口令上收成功，设备已投产' : 'Takeover completed; device is in production', rotation_status: rotationStatus };
                if (rotationStatus === 'failed') return { ...item, status: 'failed', message: statusData.takeover_error || (zh ? '口令上收失败，已回滚' : 'Takeover failed and was rolled back'), rotation_status: rotationStatus };
                return { ...item, status: 'running', message: zh ? '后台处理中...' : 'Processing in background...', rotation_status: rotationStatus };
              } catch {
                return { ...item, status: 'running', message: zh ? '正在等待设备返回结果...' : 'Waiting for device result...' };
              }
            }));
            setBatchTakeoverResults(previous => {
              const snapshotById = new Map(snapshots.map(item => [item.id, item]));
              return previous.map(item => snapshotById.get(item.id) || item);
            });
            const done = snapshots.every(item => item.status === 'completed' || item.status === 'failed');
            if (done || Date.now() - startedAt > 120000) {
              clearInterval(batchTakeoverPollRef.current);
              batchTakeoverPollRef.current = undefined;
              if (!done) {
                setBatchTakeoverResults(previous => previous.map(item => item.status === 'running'
                  ? { ...item, status: 'timeout', message: zh ? '等待超时，请查看后端日志和设备状态' : 'Polling timed out; check backend logs and device status' }
                  : item));
              }
              fetchAssets();
            }
          }, 2000);
        }
        clearSel();
        fetchAssets();
      } else {
        const data = await r.json().catch(() => ({}));
        setFeedbackMsg({ type: 'error', text: data?.detail || (zh ? '批量上收请求失败' : 'Batch takeover request failed') });
      }
    } catch (e) {
      setFeedbackMsg({ type: 'error', text: zh ? '批量操作失败' : 'Batch operation failed' });
    }
    setLoading(false);
  };

  const requestBatchTakeover = () => {
    if (selectedIds.size > 0) setShowBatchTakeoverConfirm(true);
  };

  const batchTakeoverDisplayResults = useMemo(() => {
    const rows: BatchTakeoverResult[] = [];
    const blockedGroups = new Map<string, BatchTakeoverResult>();
    batchTakeoverResults.forEach(result => {
      if (result.status !== 'blocked_credential') {
        rows.push(result);
        return;
      }
      const key = result.credential_name || 'bound-credential';
      const existing = blockedGroups.get(key);
      if (existing) {
        existing.device_count = (existing.device_count || 1) + 1;
        existing.device_names = [...(existing.device_names || []), result.hostname || result.id];
      } else {
        blockedGroups.set(key, { ...result, id: `blocked:${key}`, device_count: 1, device_names: [result.hostname || result.id] });
      }
    });
    return [...rows, ...blockedGroups.values()];
  }, [batchTakeoverResults]);

  const requestTerminalAccess = async () => {
    if (!terminalTarget) return;
    setTerminalRequesting(true);
    try {
      const requester = localStorage.getItem('netops_user') || 'unknown';
      const r = await fetch('/api/pam/access-request', {
        method: 'POST',
        headers: authHeaders(true),
        body: JSON.stringify({
          asset_id: terminalTarget.id,
          access_level: terminalAccessLevel,
          reason: terminalReason.trim() || (terminalAccessLevel === 'normal' ? 'Direct access' : ''),
          requester_username: requester,
          ticket_id: approvalData.ticket,
          mfa_code: approvalData.mfa
        }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        setFeedbackMsg({ type: 'error', text: (data?.detail || (zh ? '申请失败' : 'Request failed')) as string });
        return;
      }

      if (data.status === 'approved' || (terminalAccessLevel === 'admin' && isApproved)) {
        if (terminalAccessLevel === 'admin' && data.status !== 'approved') {
           await fetch(`/api/pam/access-requests/${data.request_id}/approve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ reviewer_username: 'system', comment: `MFA Verified: ${approvalData.ticket}`, ttl_minutes: 60 }),
          });
        }

        const sr = await fetch('/api/pam/terminal-session', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ request_id: data.request_id }),
        });
        const sd = await sr.json().catch(() => ({}));
        if (sr.ok && sd?.session_token) {
          const connHint = `${sd.connect?.username || '-'}@${sd.connect?.host || '-'}:${sd.connect?.port || 22}`;
          setTerminalLines('');
          setTerminalInput('');
          setTerminalSession({ token: sd.session_token, title: connHint });
          setTerminalTarget(null);
          setTerminalReason('');
          setApprovalData({ ticket: '', reason: '', mfa: '' });
          setIsApproved(false);
        } else {
          setFeedbackMsg({ type: 'error', text: (sd?.detail || (zh ? '终端会话创建失败' : 'Failed to create terminal session')) as string });
        }
      } else {
        setFeedbackMsg({
          type: 'info',
          text: zh ? `已提交申请，单号 ${data.request_id}，等待审批。` : `Request ${data.request_id} submitted, waiting for approval.`,
        });
        setTerminalTarget(null);
      }
    } catch (e) {
      setFeedbackMsg({ type: 'error', text: zh ? '网络异常' : 'Network error' });
    } finally {
      setTerminalRequesting(false);
    }
  };

  const sendTerminalInput = () => {
    const text = terminalInput;
    if (!text.trim()) return;
    const ws = terminalWsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      setFeedbackMsg({ type: 'warning', text: zh ? '终端连接未就绪' : 'Terminal not ready' });
      return;
    }
    ws.send(`${text}\n`);
    setTerminalInput('');
  };

  const doImport = async (payload: any[]) => {
    // Keep failures visible above the validation dialog and page content.
    setShowValidationModal(false);
    try {
      const r = await fetch('/api/assets/import', {
        method: 'POST',
        headers: authHeaders(true),
        body: JSON.stringify(payload),
      });
      if (r.ok) {
        const res = await r.json();
        const skippedItems = Array.isArray(res.skipped_items) ? res.skipped_items as AssetImportSkippedItem[] : [];
        const skippedDetails = skippedItems.slice(0, 8).map((item) => {
          const identity = [item.asset_tag, item.hostname].filter(Boolean).join(' / ') || 'Unknown row';
          if (item.reason === 'duplicate_asset_tag') {
            const existing = item.existing_hostname ? `（现有设备：${item.existing_hostname}）` : '';
            return zh
              ? `${identity}：资产编号已存在${existing}`
              : `${identity}: asset tag already exists${item.existing_hostname ? ` (existing device: ${item.existing_hostname})` : ''}`;
          }
          if (item.reason === 'duplicate_identity') {
            const fields = (item.duplicate_labels || []).map((label, index) =>
              `${label}「${item.duplicate_values?.[index] || ''}」`,
            ).join('、');
            const existing = item.existing_hostname ? `（现有设备：${item.existing_hostname}）` : '';
            const enrollmentNote = item.librenms_enrollment?.message
              ? `；${item.librenms_enrollment.message}`
              : '';
            return zh
              ? `${identity}：${fields || '主机名/资产编号/序列号/管理IP'}已存在${existing}${enrollmentNote}`
              : `${identity}: ${fields || 'hostname/asset tag/serial number/management IP'} already exists${item.existing_hostname ? ` (existing device: ${item.existing_hostname})` : ''}${item.librenms_enrollment?.message ? `; ${item.librenms_enrollment.message}` : ''}`;
          }
          return zh ? `${identity}：导入规则跳过` : `${identity}: skipped by import rule`;
        });
        if (res.skipped > skippedDetails.length) {
          skippedDetails.push(zh
            ? `另有 ${res.skipped - skippedDetails.length} 条跳过记录未展开`
            : `${res.skipped - skippedDetails.length} more skipped rows are not shown`);
        }
        const hostnameSync = res.hostname_sync || {};
        const hostnameSyncFailures = Array.isArray(hostnameSync.failed_items) ? hostnameSync.failed_items : [];
        const hostnameSyncFailedCount = Math.max(hostnameSyncFailures.length, Number(hostnameSync.failed) || 0);
        const hostnameSyncDetails = hostnameSyncFailures.map((item: any) => {
          const identity = [item.previous_hostname || item.hostname, item.asset_tag]
            .filter(Boolean)
            .join(' / ') || (item.device_id || 'Unknown device');
          const ip = item.ip ? ` (${item.ip})` : '';
          const error = item.error || (zh ? '未知错误' : 'unknown error');
          const failureLabel = error.includes('写回 CMDB')
            ? (zh ? '主机名写回 CMDB 失败' : 'failed to save hostname to CMDB')
            : (zh ? 'SNMP 获取主机名失败' : 'failed to read hostname via SNMP');
          return zh
            ? `${identity}${ip}：${failureLabel}（${error}）`
            : `${identity}${ip}: ${failureLabel} (${error})`;
        });
        const hasSkipped = Number(res.skipped || 0) > 0;
        const hasHostnameSyncFailures = hostnameSyncFailedCount > 0;
        const syncSummary = Number(hostnameSync.total || 0) > 0 && !hasHostnameSyncFailures
          ? (zh
            ? `；SNMP 主机名已同步 ${hostnameSync.succeeded || 0}/${hostnameSync.total} 台`
            : `; SNMP hostnames synced for ${hostnameSync.succeeded || 0}/${hostnameSync.total} devices`)
          : '';
        const hostnameSyncFailureSummary = hasHostnameSyncFailures
          ? (zh
            ? `；${hostnameSyncFailedCount} 台设备主机名未自动同步，已保留现有名称。请检查 SNMP Community，并确认 CMDB 主机名与实际设备一致。`
            : `; ${hostnameSyncFailedCount} device${hostnameSyncFailedCount === 1 ? '' : 's'} could not sync the hostname automatically, so the existing name was kept. Check the SNMP Community and confirm that CMDB hostnames match the actual device names.`)
          : '';
        const enrollment = res.librenms_enrollment || {};
        const enrollmentFailures = Array.isArray(enrollment.failed_items) ? enrollment.failed_items : [];
        const enrollmentFailedCount = Math.max(enrollmentFailures.length, Number(enrollment.failed) || 0);
        const enrollmentRows = Array.isArray(enrollment.items) ? enrollment.items : enrollmentFailures;
        const enrollmentDetails = enrollmentRows.slice(0, 8).map((item: any) => {
          const identity = [item.hostname, item.asset_tag].filter(Boolean).join(' / ')
            || item.ip || item.device_id || (zh ? '未知设备' : 'Unknown device');
          const row = item.row ? (zh ? `第 ${item.row} 行 ` : `row ${item.row} `) : '';
          const succeeded = ['added_and_bound', 'profile_updated_and_bound', 'found_after_retry_and_bound', 'profile_updated_after_retry_and_bound'].includes(item.status);
          const state = succeeded
            ? (zh ? '纳管成功' : 'enrolled')
            : item.status === 'skipped_duplicate_profile_mismatch'
              ? (zh ? '未修改已有资产' : 'existing asset unchanged')
              : item.status === 'not_attempted_import_failed'
                ? (zh ? '资产导入失败，未纳管' : 'asset import failed; not enrolled')
                : (zh ? `纳管状态：${item.status || '未执行'}` : `enrollment: ${item.status || 'not attempted'}`);
          return `${row}${identity}：${state}${item.message ? `；${item.message}` : ''}`;
        });
        if (enrollmentRows.length > enrollmentDetails.length) {
          enrollmentDetails.push(zh
            ? `另有 ${enrollmentRows.length - enrollmentDetails.length} 行纳管状态未展开`
            : `${enrollmentRows.length - enrollmentDetails.length} more enrollment rows are not shown`);
        }
        const enrollmentSummary = Number(enrollment.total || 0) > 0
          ? (zh
            ? `；LibreNMS 纳管成功 ${enrollment.succeeded || 0}/${enrollment.total} 台${enrollmentFailedCount ? `，失败 ${enrollmentFailedCount} 台` : ''}`
            : `; LibreNMS enrollment succeeded for ${enrollment.succeeded || 0}/${enrollment.total} device${Number(enrollment.total) === 1 ? '' : 's'}${enrollmentFailedCount ? `, ${enrollmentFailedCount} failed` : ''}`)
          : '';
        const enrollmentFailureSummary = enrollmentFailedCount > 0
          ? (zh
            ? '；资产已保存，但部分设备未能按所选 Profile 纳入 LibreNMS，请查看详情并修复配置后重新导入对应行重试。'
            : '; assets were saved, but some devices were not enrolled with the selected profile. Review details and retry those rows after fixing the configuration.')
          : '';
        const hasEnrollmentFailures = enrollmentFailedCount > 0;
        const details = [...skippedDetails, ...hostnameSyncDetails, ...enrollmentDetails];
        setFeedbackMsg({
          type: hasSkipped || hasHostnameSyncFailures || hasEnrollmentFailures ? 'warning' : 'success',
          text: zh
            ? `导入完成：新增 ${res.created} 条，跳过 ${res.skipped} 条${hasSkipped ? '（请查看跳过原因）' : ''}${enrollmentSummary}${enrollmentFailureSummary}${syncSummary}${hostnameSyncFailureSummary}`
            : `Import done: ${res.created} created, ${res.skipped} skipped${hasSkipped ? ' (review skipped rows)' : ''}${enrollmentSummary}${enrollmentFailureSummary}${syncSummary}${hostnameSyncFailureSummary}`,
          details: details.length > 0 ? details : undefined,
        });
        fetchAssets();
        fetchSummary();
        fetchAllRacks();
      } else {
        const error = await r.json().catch(() => null);
        const formatted = formatAssetImportError(error?.detail, language);
        setFeedbackMsg({ type: 'error', ...formatted });
      }
    } catch {
      setFeedbackMsg({ type: 'error', text: zh ? '连接失败，导入未完成' : 'Connection failed, import incomplete' });
    }
  };

  const handleValidationConfirm = async (resolutions: Record<string, RackResolution>) => {
    setValidationModalSaving(true);
    try {
      let finalPayload = [...pendingImportPayload];
      const skipKeys = new Set<string>();
      const mapConfig: Record<string, string> = {};
      const autoCreateList: { name: string; site_id: string; total_u: number }[] = [];
      const createdKeys = new Set<string>();

      Object.entries(resolutions).forEach(([key, res]) => {
        const [dc, rk] = key.split('|');
        if (res.action === 'skip') {
          skipKeys.add(key);
        } else if (res.action === 'map' && res.targetRack) {
          mapConfig[key] = res.targetRack;
        } else if (res.action === 'create') {
          if (!createdKeys.has(key)) {
            autoCreateList.push({ name: rk, site_id: dc, total_u: 42 });
            createdKeys.add(key);
          }
        }
      });

      if (autoCreateList.length > 0) {
        const token = localStorage.getItem('netops_token');
        const r = await fetch('/api/racks/batch', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify(autoCreateList),
        });
        if (!r.ok) {
          const errData = await r.json().catch(() => ({}));
          throw new Error(errData.detail || (zh ? '自动新建机柜失败' : 'Failed to auto-create racks'));
        }
      }

      finalPayload = finalPayload.filter(row => {
        const dc = row.site_id || row.datacenter || '';
        const rk = row.rack || '';
        const key = `${dc}|${rk}`;
        if (skipKeys.has(key)) {
          return false;
        }
        if (mapConfig[key]) {
          row.rack = mapConfig[key];
        }
        return true;
      });

      if (finalPayload.length > 0) {
        await doImport(finalPayload);
      } else {
        setFeedbackMsg({
          type: 'info',
          text: zh ? '所有异常行已被跳过，未导入任何数据' : 'All exception rows were skipped, no data imported',
        });
      }
      
      setShowValidationModal(false);
    } catch (err: any) {
      setShowValidationModal(false);
      setFeedbackMsg({
        type: 'error',
        text: err.message || (zh ? '处理异常失败' : 'Failed to process import validation'),
      });
    } finally {
      setValidationModalSaving(false);
    }
  };

  const formatExcelDate = (val: any): string => {
    if (val instanceof Date) {
      return val.toISOString().split('T')[0];
    }
    const str = String(val).trim();
    if (!str) return '';
    if (/^\d+(\.\d+)?$/.test(str)) {
      const num = Number(str);
      if (num > 0) {
        const excelEpoch = new Date(1899, 11, 30);
        excelEpoch.setDate(excelEpoch.getDate() + num);
        const y = excelEpoch.getFullYear();
        const m = String(excelEpoch.getMonth() + 1).padStart(2, '0');
        const d = String(excelEpoch.getDate()).padStart(2, '0');
        return `${y}-${m}-${d}`;
      }
    }
    const parts = str.split(/[-/.]/);
    if (parts.length === 3) {
      const y = parts[0];
      const m = parts[1];
      const d = parts[2];
      if (y.length === 4) {
        return `${y}-${m.padStart(2, '0')}-${d.padStart(2, '0')}`;
      } else if (d.length === 4) {
        const parsedDate = new Date(str);
        if (!isNaN(parsedDate.getTime())) {
          const y2 = parsedDate.getFullYear();
          const m2 = String(parsedDate.getMonth() + 1).padStart(2, '0');
          const d2 = String(parsedDate.getDate()).padStart(2, '0');
          return `${y2}-${m2}-${d2}`;
        }
      }
    }
    return str;
  };

  const handleImport = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async (ev) => {
      try {
        const data = new Uint8Array(ev.target?.result as ArrayBuffer);
        const wb = XLSX.read(data, { type: 'array' });
        const mapped: Record<string, string>[] = [];
        const managementMethods: ManagementMethodImportRow[] = [];
        const managementMethodErrors: string[] = [];
        const templateMismatchRows: string[] = [];
        const snmpPreflightErrors: string[] = [];
        const sshProfilePreflightErrors: string[] = [];
        let hasAssetSheet = false;
        for (const name of wb.SheetNames) {
          const ws = wb.Sheets[name];
          if (MANAGEMENT_ENTRY_SHEET_RE.test(name.trim())) {
            const parsed = parseManagementMethodSheet(ws);
            managementMethods.push(...parsed.rows);
            managementMethodErrors.push(...parsed.errors);
            continue;
          }
          const raw = XLSX.utils.sheet_to_json<Record<string, string>>(ws, { defval: '' });
          const sheetAssetType = assetTypeForSheetName(name);
          const isUnifiedAssetSheet = ASSET_INFO_SHEET_RE.test(name.trim());
          if (isUnifiedAssetSheet || sheetAssetType) hasAssetSheet = true;
          for (const [rowIndex, row] of raw.entries()) {
            const obj: Record<string, string> = {};
            for (const [col, val] of Object.entries(row)) {
              const key = COL_MAP[normalizeImportHeader(col)];
              if (key) {
                let mappedVal = String(val).trim();
                const valueMap = IMPORT_VALUE_MAP[key];
                if (valueMap) {
                  mappedVal = valueMap[mappedVal] || valueMap[mappedVal.toLowerCase()] || mappedVal;
                }
                if (key === 'platform') {
                  mappedVal = normalizeImportedPlatform(mappedVal);
                }
                if (key === 'asset_type') {
                  const v = mappedVal.toLowerCase();
                  if (v.includes('server') || v.includes('服务器')) mappedVal = 'server';
                  else if (v.includes('network') || v.includes('网络') || v.includes('switch') || v.includes('router')) mappedVal = 'network_device';
                } else if (key === 'purchase_date' || key === 'warranty_expiry') {
                  mappedVal = formatExcelDate(val);
                } else if (key === 'snmp_port' && mappedVal) {
                  const port = Number(mappedVal);
                  if (!Number.isInteger(port) || port < 1 || port > 65535) {
                    snmpPreflightErrors.push(`${name} 第${rowIndex + 2}行：SNMP端口必须是 1 到 65535 的整数`);
                  }
                } else if (key === 'ssh_algorithm_profile' && mappedVal && !SSH_ALGORITHM_PROFILE_VALUES.includes(mappedVal as typeof SSH_ALGORITHM_PROFILE_VALUES[number])) {
                  sshProfilePreflightErrors.push(`${name} 第${rowIndex + 2}行：SSH算法策略“${mappedVal}”不受支持，请使用 auto、modern、legacy_compat 或 legacy_break_glass`);
                }
                obj[key] = mappedVal;
              }
            }
            if (obj.hostname || obj.asset_tag || obj.management_ip) {
              if (!obj.asset_type) {
                if (isUnifiedAssetSheet) {
                  templateMismatchRows.push(`${name} 第${rowIndex + 2}行：资产类型必填，请选择“服务器”或“网络设备”`);
                  continue;
                }
                obj.asset_type = sheetAssetType || 'server';
              }
              const rowIsNet = obj.asset_type === 'network_device';
              if (sheetAssetType && obj.asset_type !== sheetAssetType) {
                templateMismatchRows.push(`${name} 第${rowIndex + 2}行：该工作表只允许导入${sheetAssetType === 'network_device' ? '网络设备' : '服务器'}，当前资产类型不匹配`);
                continue;
              }
              if (rowIsNet && obj.vendor && !isNetworkVendor(obj.vendor)) {
                templateMismatchRows.push(`${name} 第${rowIndex + 2}行：网络设备厂商“${obj.vendor}”不在网络/安全设备厂商列表中`);
                continue;
              }
              if (rowIsNet && obj.vendor) {
                obj.vendor = normalizeImportedVendor(obj.vendor);
              }
              if (obj.platform && !isValidVendorPlatform(obj.asset_type, obj.vendor || '', obj.platform)) {
                templateMismatchRows.push(`${name} 第${rowIndex + 2}行：平台“${obj.platform}”不属于厂商“${obj.vendor || '当前选择'}”，请按厂商下拉选项填写`);
                continue;
              }
              const allowedRoles = rowIsNet ? NETWORK_TEMPLATE_ROLES : SERVER_TEMPLATE_ROLES;
              const allowedCategories = rowIsNet ? NETWORK_TEMPLATE_CATEGORIES : SERVER_TEMPLATE_CATEGORIES;
              if (obj.device_role && !allowedRoles.has(obj.device_role)) {
                templateMismatchRows.push(`${name} 第${rowIndex + 2}行：角色“${obj.device_role}”不属于${rowIsNet ? '网络设备' : '服务器'}`);
                continue;
              }
              if (obj.device_category && !allowedCategories.has(obj.device_category)) {
                templateMismatchRows.push(`${name} 第${rowIndex + 2}行：设备分类“${obj.device_category}”不属于${rowIsNet ? '网络设备' : '服务器'}`);
                continue;
              }
              if (obj.snmp_credential_name && obj.snmp_credential_id) {
                snmpPreflightErrors.push(`${name} 第${rowIndex + 2}行：SNMP凭据名称与SNMP凭据ID不能同时填写，请只保留一个`);
                continue;
              }
              // An explicit SNMP credential takes precedence at runtime, but
              // a legacy/device-local community remains a valid fallback.
              // Accept both fields so imports can migrate gradually without
              // treating SSH credentials as SNMP credentials.
              obj.ssh_algorithm_profile = obj.ssh_algorithm_profile || 'auto';
              mapped.push(obj);
            }
          }
        }
        if (snmpPreflightErrors.length > 0) {
          setFeedbackMsg({
            type: 'error',
            text: zh ? 'SNMP 凭据预检失败，请修正后重新导入' : 'SNMP credential preflight failed; fix the rows and retry',
            details: snmpPreflightErrors.slice(0, 8),
          });
          return;
        }
        if (sshProfilePreflightErrors.length > 0) {
          setFeedbackMsg({
            type: 'error',
            text: zh ? 'SSH 算法策略预检失败，请修正后重新导入' : 'SSH algorithm profile preflight failed; fix the rows and retry',
            details: sshProfilePreflightErrors.slice(0, 8),
          });
          return;
        }
        if (templateMismatchRows.length > 0) {
          setFeedbackMsg({
            type: 'error',
            text: `${zh ? '模板角色/设备分类不匹配，请检查：' : 'Template role/category mismatch:'} ${templateMismatchRows.slice(0, 3).join('；')}`,
          });
          return;
        }
        const merged = mergeManagementMethods(mapped, managementMethods, {
          requireEntryForAllAssets: hasAssetSheet,
        });
        const methodErrors = [...managementMethodErrors, ...merged.errors];
        if (methodErrors.length > 0) {
          setFeedbackMsg({
            type: 'error',
            text: zh ? '管理入口配置存在错误，请检查' : 'Management entry configuration has errors',
            details: methodErrors.slice(0, 8),
          });
          return;
        }
        if (!mapped.length) { setFeedbackMsg({ type: 'error', text: zh ? '未找到有效 data 行' : 'No valid rows found' }); return; }
        
        // Scan for missing racks
        const missingMap: Record<string, { datacenter: string; rack: string; rowCount: number }> = {};
        mapped.forEach(row => {
          if (row.rack) {
            const dcName = row.site_id || row.datacenter || '';
            const exists = allRacks.some(r => r.name === row.rack && [r.site_id, r.site_code, r.site_name, r.datacenter].filter(Boolean).includes(dcName));
            if (!exists) {
              const key = `${dcName}|${row.rack}`;
              if (!missingMap[key]) {
                missingMap[key] = { datacenter: dcName, rack: row.rack, rowCount: 0 };
              }
              missingMap[key].rowCount += 1;
            }
          }
        });

        const missingList = Object.values(missingMap);
        if (missingList.length > 0) {
          setPendingImportPayload(mapped);
          setMissingRacks(missingList);
          setShowValidationModal(true);
        } else {
          await doImport(mapped);
        }
      } catch { setFeedbackMsg({ type: 'error', text: zh ? '文件解析失败' : 'Failed to parse' }); }
    };
    reader.readAsArrayBuffer(file);
    e.target.value = '';
  };

  const handleDownloadTemplate = async () => {
    const downloadTemplateBlob = (blob: Blob) => {
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = zh ? '资产导入模板.xlsx' : 'asset_import_template.xlsx';
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    };

    // The authenticated endpoint adds this vault's complete SNMPv2/v3 profile names to a native
    // Excel dropdown. Keep static and browser-generated fallbacks for older deployments.
    try {
      const response = await fetch('/api/assets/import-template', { headers: authHeaders(), cache: 'no-store' });
      if (response.ok) {
        downloadTemplateBlob(await response.blob());
        return;
      }
    } catch {
      // Fall through to the static distributable template.
    }

    try {
      const response = await fetch('/templates/asset_import_template.xlsx', { cache: 'no-store' });
      if (response.ok) {
        downloadTemplateBlob(await response.blob());
        return;
      }
    } catch {
      // Fall through to the in-browser legacy generator.
    }

    const wb = XLSX.utils.book_new();

    const guideRows = zh ? [
      ['资产导入填写说明'],
      ['项目', '怎么填', '只需要填写“网络设备”“服务器”和“管理入口”；红色 * 表示必填；其它工作表仅供参考，不用修改。'],
      ['网络设备', '每台设备一行', '只填写网络设备；资产类型固定填写“网络设备”，不要混入服务器。'],
      ['服务器', '每台设备一行', '只填写服务器；资产类型固定填写“服务器”，不要混入网络设备。'],
      ['资产类型', '必填', '按当前工作表填写对应值：“网络设备”或“服务器”。'],
      ['主机名/资产编号', '选填（支持留空）', '网络设备主机名可留空，但必须填写管理 IP；系统将先用管理 IP 将设备和 SNMP Profile 提交给 LibreNMS，再由 LibreNMS 执行原生识别与采集。'],
      ['录入来源', '必填', '填写“新设备”或“存量设备”。'],
      ['投产状态', '必填', '新设备填“待投产”；存量设备按实际状态填写。'],
      ['管理入口', '每个资产一行', '资产编号和主机名会从两张资产表自动带出；SSH 只填一行，导入后自动提供“SSH 终端”和“Web SSH”。'],
      ['网页管理', '有网页才填', '只有设备自带 HTTP/HTTPS 管理页面才另填 HTTP 或 HTTPS；这不是 Web SSH。'],
      ['没有登录入口', '填 NONE', '协议填 NONE，其它入口信息留空。'],
      ['端口/路径', '可留空', 'SSH 默认 22；HTTP 默认 80；HTTPS 默认 443。SSH 和 Web SSH 不填路径。'],
      ['凭据', '可选', '默认使用资产凭据；填写名称或ID时先确认凭据中心中存在。样例名称需核实或替换，不要填密码。'],
      ['SNMP凭据名称', '选填', '填写凭据中心中已存在且配置完整的 SNMPv2/v3 Profile 名称，须完全一致；Profile 密钥不会写入表格。'],
      ['其它列', '可选', '不需要的字段全部留空。'],
      ['安全提示', '注意', '优先填写绑定凭据，不要在表格中填写密码。'],
      ['重复资产', '会跳过', '主机名、资产编号、序列号或管理 IP 重复时跳过整行，不更新旧资产；修改旧资产请到资产管理编辑。'],
    ] : [
      ['Asset Import Instructions'],
      ['Item', 'How to fill', 'Only complete Network Devices, Servers and Management Entries; a red * means required; other sheets are reference-only.'],
      ['Network Devices', 'One row per device', 'Enter network devices only; keep Asset Type as network_device.'],
      ['Servers', 'One row per device', 'Enter servers only; keep Asset Type as server.'],
      ['Asset Type', 'Required', 'Use the value matching the current sheet: network_device or server.'],
      ['Hostname / Asset Tag', 'Optional', 'For network devices, hostname may be blank when a management IP is provided. Nexora submits the IP and selected SNMP profile to LibreNMS for native discovery and polling.'],
      ['Asset Origin', 'Required', 'Use new or legacy.'],
      ['Lifecycle', 'Required', 'Use staging for new devices; use the actual state for legacy devices.'],
      ['Management Entries', 'One row per asset', 'Asset Tag and Hostname are read from Network Devices and Servers. For SSH, enter one row only; the imported asset automatically provides SSH terminal and Web SSH.'],
      ['Device Web Page', 'Only when present', 'Use HTTP or HTTPS only for the device\'s own web page; this is not Web SSH.'],
      ['No Login', 'Use NONE', 'Set the protocol to NONE and leave the remaining entry fields blank.'],
      ['Port / Path', 'Optional', 'Defaults are SSH 22, HTTP 80 and HTTPS 443. Leave SSH and Web SSH paths blank.'],
      ['Credentials', 'Optional', 'Asset credentials are inherited by default. Verify that a bound name or ID exists in the credential center; replace sample names and never enter passwords.'],
      ['SNMP Credential Name', 'Optional', 'Enter an existing, complete SNMPv2/v3 profile name exactly. Profile secrets are never written to the workbook.'],
      ['Other columns', 'Optional', 'Leave fields you do not need blank.'],
      ['Security', 'Important', 'Prefer credential bindings and avoid putting passwords in the sheet.'],
      ['Duplicate assets', 'Skipped', 'Rows matching an existing hostname, asset tag, serial number or management IP are skipped, not updated. Edit existing assets in Asset Management.'],
    ];
    const wsGuide = XLSX.utils.aoa_to_sheet(guideRows);
    wsGuide['!cols'] = [{ wch: 28 }, { wch: 18 }, { wch: 72 }];
    XLSX.utils.book_append_sheet(wb, wsGuide, zh ? '填写说明' : 'Instructions');

    // Keep the fallback workbook on the same named-column contract as the
    // full legacy workbook. Old 41-column files remain valid because parsing
    // is header based; this version additionally exposes SSH policy.
    const rawAssetHeaders = zh
      ? ['资产类型', '主机名', '资产编号', '序列号', '厂商', '型号', '平台', 'SSH算法策略', '管理IP', '业务IP', '状态', '角色', '设备分类', '录入来源（必填：新设备或存量设备）', 'VLAN', '上联交换机', '上联端口', '站点', '机柜', 'U位', 'U高度', '规划起始U', '功耗(W)', 'SNMP社区名', 'SNMP端口', '普通用户', '特权用户', '普通密码', '特权密码', 'Enable密码', '绑定凭据', '绑定特权凭据', 'SNMP凭据名称（选填）', '标签代码', '部门', '购买日期', '投产状态', '免上收投产原因', '保修到期', '备注', '功能', '区域']
      : ['Asset Type', 'Hostname', 'Asset Tag', 'Serial Number', 'Vendor', 'Model', 'Platform', 'SSH Algorithm Profile', 'Mgmt IP', 'Business IP', 'Status', 'Role', 'Device Category', 'Asset Origin (Required: new or legacy)', 'VLAN', 'Uplink Switch', 'Uplink Port', 'Site', 'Rack', 'Rack Unit', 'U Height', 'Planned Start U', 'Power(W)', 'SNMP Community', 'SNMP Port', 'Normal User', 'Admin User', 'Normal Password', 'Admin Password', 'Enable Secret', 'Credential', 'Admin Credential', 'SNMP Credential Name (optional)', 'Tags', 'Department', 'Purchase Date', 'Lifecycle', 'Takeover Exemption Reason', 'Warranty Expiry', 'Notes', 'Function', 'Zone'];
    const requiredHeaders = zh
      ? new Set(['资产类型', '资产编号', '录入来源（必填：新设备或存量设备）', '投产状态', '免上收投产原因'])
      : new Set(['Asset Type', 'Asset Tag', 'Asset Origin (Required: new or legacy)', 'Lifecycle', 'Takeover Exemption Reason']);
    // Keep the fallback on the same field order as the user-supplied split
    // workbook. Network sheets omit Business IP; server sheets omit the SNMP
    // community/port, Enable password and SNMP credential fields.
    const networkAssetIndexes = [0, 1, 2, 3, 4, 5, 6, 8, 10, 11, 12, 13, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41];
    const serverAssetIndexes = [0, 1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 25, 26, 27, 28, 30, 31, 33, 34, 35, 36, 37, 38, 39, 40, 41];
    const networkAssetHeaders = networkAssetIndexes.map(index => rawAssetHeaders[index]);
    networkAssetHeaders[25] = zh ? '绑定普通用户凭据' : 'Normal Credential';
    networkAssetHeaders[27] = zh ? 'SNMP凭据名称（选填）' : 'SNMP Credential Name (optional)';
    const serverAssetHeaders = serverAssetIndexes.map(index => rawAssetHeaders[index]);
    const markRequiredHeaders = (headers: string[]) => headers.map(header => requiredHeaders.has(header) ? `${header} *` : header);
    const markedNetworkAssetHeaders = markRequiredHeaders(networkAssetHeaders);
    const markedServerAssetHeaders = markRequiredHeaders(serverAssetHeaders);
    const projectRows = (rows: (string | number)[][], indexes: number[]) => rows.map(row => indexes.map(index => row[index] ?? ''));
    const legacyAssetExamples = zh ? [
      ['网络设备', 'core-sw-01', 'NET-BJ-001', 'FCW2345L0AB', 'Cisco', 'C9300-48P', 'Cisco IOS', 'auto', '10.0.0.1', '', '在用', '核心层', '交换机', '存量设备', '', '', '', 'BJ-DC1', 'A-02', '40', '1', '40', '', '', '161', 'user', 'admin', '', '', '', 'cred-cisco-core', 'cred-cisco-admin', '', 'vendor.cisco,platform.cisco_ios', 'IT部', '2023-06-01', '已投产', '存量设备已在线运行', '2027-06-01', 'A：只支持 SSH', '园区核心', '生产区'],
      ['网络设备', 'web-fw-01', 'NET-BJ-002', 'HS20260813A1', 'Hillstone', 'Hillstone E-Series', 'Hillstone StoneOS', 'auto', '10.0.0.2', '', '在用', '防火墙', '防火墙', '新设备', '', '', '', 'BJ-DC1', 'A-02', '38', '2', '38', '', '', '161', '', '', '', '', '', '', '', 'cred-snmp-edge', 'vendor.hillstone', 'IT部', '2026-08-13', '待投产', '', '2029-08-13', 'B：同时支持 HTTP 和 HTTPS', '互联网边界', 'DMZ 区'],
      ['服务器', 'web-srv-01', 'SRV-BJ-001', 'CZJ2345G0HN', 'Dell', 'PowerEdge R750', 'Linux (Generic)', 'auto', '10.0.1.10', '192.168.1.10', '在用', '业务服务器', '机架式服务器', '新设备', 'VLAN100', 'core-sw-01', 'Gi0/1', 'BJ-DC1', 'A-01', '12', '1', '12', '200', '', '', 'ops', 'root', '', '', '', 'cred-server-ops', '', '', 'platform.linux', 'IT部', '2026-08-13', '待投产', '', '2029-08-13', 'C：SSH + HTTPS（管理入口需两行）', '服务器接入', '生产区'],
    ] : [
      ['network_device', 'core-sw-01', 'NET-BJ-001', 'FCW2345L0AB', 'Cisco', 'C9300-48P', 'cisco_ios', 'auto', '10.0.0.1', '', 'active', 'core', 'switch', 'legacy', '', '', '', 'BJ-DC1', 'A-02', '40', '1', '40', '', '', '161', 'user', 'admin', '', '', '', 'cred-cisco-core', 'cred-cisco-admin', '', 'vendor.cisco,platform.cisco_ios', 'IT Dept', '2023-06-01', 'production', 'Existing production device', '2027-06-01', 'A: SSH only', 'Campus Core', 'Production'],
      ['network_device', 'web-fw-01', 'NET-BJ-002', 'HS20260813A1', 'Hillstone', 'Hillstone E-Series', 'hillstone_stoneos', 'auto', '10.0.0.2', '', 'active', 'firewall', 'firewall', 'new', '', '', '', 'BJ-DC1', 'A-02', '38', '2', '38', '', '', '161', '', '', '', '', '', '', '', 'cred-snmp-edge', 'vendor.hillstone', 'IT Dept', '2026-08-13', 'staging', '', '2029-08-13', 'B: HTTP + HTTPS', 'Internet Edge', 'DMZ'],
      ['server', 'web-srv-01', 'SRV-BJ-001', 'CZJ2345G0HN', 'Dell', 'PowerEdge R750', 'linux', 'auto', '10.0.1.10', '192.168.1.10', 'active', 'application_server', 'rack_server', 'new', 'VLAN100', 'core-sw-01', 'Gi0/1', 'BJ-DC1', 'A-01', '12', '1', '12', '200', '', '', 'ops', 'root', '', '', '', 'cred-server-ops', '', '', 'platform.linux', 'IT Dept', '2026-08-13', 'staging', '', '2029-08-13', 'C: SSH + HTTPS (two entry rows)', 'Server Access', 'Production'],
    ];
    const networkAssetExamples = projectRows(legacyAssetExamples.filter(row => row[0] === (zh ? '网络设备' : 'network_device')), networkAssetIndexes);
    const serverAssetExamples = projectRows(legacyAssetExamples.filter(row => row[0] === (zh ? '服务器' : 'server')), serverAssetIndexes);
    const appendAssetSheet = (sheetName: string, headers: string[], examples: (string | number)[][]) => {
      const sheet = XLSX.utils.aoa_to_sheet([headers, ...examples]);
      formatFallbackTemplateDateColumns(sheet, headers);
      sheet['!cols'] = headers.map((_, index) => ({ wch: index === 0 || index === 2 ? 18 : 16 }));
      XLSX.utils.book_append_sheet(wb, sheet, sheetName);
    };
    appendAssetSheet(zh ? '网络设备' : 'Network Devices', markedNetworkAssetHeaders, networkAssetExamples);
    appendAssetSheet(zh ? '服务器' : 'Servers', markedServerAssetHeaders, serverAssetExamples);

    const methodHeaders = zh
      ? ['资产编号', '主机名', '管理协议（SSH/NETCONF/HTTP/HTTPS/NONE）', '端口（可留空自动默认）', '登录路径（Web填写，如 /login）', '是否启用', '凭据模式（默认继承资产）', '绑定凭据（推荐）', '绑定特权凭据（推荐）', '备注（填写场景）']
      : ['Asset Tag', 'Hostname', 'Management Protocol (SSH/NETCONF/HTTP/HTTPS/NONE)', 'Port (blank = default)', 'Login Path (Web only)', 'Enabled', 'Credential Mode (default: inherit asset)', 'Credential ID (recommended)', 'Admin Credential ID (recommended)', 'Notes (scenario)'];
    const methodExamples = zh ? [
      ['', '', 'SSH', 22, '', '是', '继承资产凭据', '', '', 'SSH 一行即可；自动提供 SSH 终端和 Web SSH'],
      ['', '', 'SSH', 22, '', '是', '继承资产凭据', '', '', 'SSH 一行即可；自动提供 SSH 终端和 Web SSH'],
      ['', '', 'SSH', 22, '', '是', '继承资产凭据', '', '', 'SSH 一行即可；自动提供 SSH 终端和 Web SSH'],
      ['', '', 'HTTP', 80, '/login', '是', '继承资产凭据', '', '', 'HTTP 示例：填写设备 Web 登录路径'],
      ['', '', 'HTTPS', 443, '/admin/login', '是', '继承资产凭据', '', '', 'HTTPS 示例：填写设备 Web 登录路径'],
    ] : [
      ['', '', 'SSH', 22, '', 'yes', 'inherit_asset', '', '', 'One SSH row automatically provides both SSH terminal and Web SSH'],
      ['', '', 'SSH', 22, '', 'yes', 'inherit_asset', '', '', 'One SSH row automatically provides both SSH terminal and Web SSH'],
      ['', '', 'SSH', 22, '', 'yes', 'inherit_asset', '', '', 'One SSH row automatically provides both SSH terminal and Web SSH'],
      ['', '', 'HTTP', 80, '/login', 'yes', 'inherit_asset', '', '', 'HTTP example: enter the device Web login path'],
      ['', '', 'HTTPS', 443, '/admin/login', 'yes', 'inherit_asset', '', '', 'HTTPS example: enter the device Web login path'],
    ];
    const wsMethods = XLSX.utils.aoa_to_sheet([methodHeaders, ...methodExamples]);
    wsMethods['!cols'] = [18, 20, 34, 16, 24, 10, 22, 22, 26, 42].map(wch => ({ wch }));
    wsMethods['!rows'] = [{ hpt: 54 }, ...methodExamples.map(() => ({ hpt: 36 }))];
    const networkSheetName = zh ? '网络设备' : 'Network Devices';
    const serverSheetName = zh ? '服务器' : 'Servers';
    const networkAssetCount = `MAX(COUNTA('${networkSheetName}'!$B$2:$B$2000),COUNTA('${networkSheetName}'!$C$2:$C$2000))`;
    const serverAssetCount = `MAX(COUNTA('${serverSheetName}'!$B$2:$B$2000),COUNTA('${serverSheetName}'!$C$2:$C$2000))`;
    const managementIdentityFormula = (column: 'B' | 'C') => `IF(ROW()-1<=${networkAssetCount},INDEX('${networkSheetName}'!$${column}$2:$${column}$2000,ROW()-1),IF(ROW()-1-${networkAssetCount}<=${serverAssetCount},INDEX('${serverSheetName}'!$${column}$2:$${column}$2000,ROW()-1-${networkAssetCount}),""))`;
    const identityExamples = zh
      ? [['NET-BJ-001', 'core-sw-01'], ['NET-BJ-002', 'web-fw-01'], ['SRV-BJ-001', 'web-srv-01']]
      : [['NET-BJ-001', 'core-sw-01'], ['NET-BJ-002', 'web-fw-01'], ['SRV-BJ-001', 'web-srv-01']];
    for (let rowNumber = 2; rowNumber <= identityExamples.length + 1; rowNumber += 1) {
      const example = identityExamples[rowNumber - 2];
      wsMethods[`A${rowNumber}`] = { t: 'str', f: managementIdentityFormula('C'), v: example?.[0] || '' };
      wsMethods[`B${rowNumber}`] = { t: 'str', f: managementIdentityFormula('B'), v: example?.[1] || '' };
    }
    const sampleEntryFormula = (column: 'B' | 'C') => `='${networkSheetName}'!$${column}$2`;
    wsMethods['A5'] = { t: 'str', f: sampleEntryFormula('C'), v: identityExamples[0]?.[0] || '' };
    wsMethods['B5'] = { t: 'str', f: sampleEntryFormula('B'), v: identityExamples[0]?.[1] || '' };
    wsMethods['A6'] = { t: 'str', f: sampleEntryFormula('C'), v: identityExamples[0]?.[0] || '' };
    wsMethods['B6'] = { t: 'str', f: sampleEntryFormula('B'), v: identityExamples[0]?.[1] || '' };
    wsMethods['!ref'] = 'A1:J6';
    XLSX.utils.book_append_sheet(wb, wsMethods, zh ? '管理入口' : 'Management Entries');

    const optHeaders = zh
      ? ['分类类型', '参数名称 (Field Name)', '标准填写值 (Standard Value)', '值含义说明 (Description)']
      : ['Category', 'Field Name', 'Standard Value', 'Description'];
    const networkVendorRowsZh = NETWORK_IMPORT_VENDOR_VALUES.map(value => [
      '网络/安全设备',
      '厂商 (Vendor)',
      value,
      IMPORT_VALUE_MAP.vendor[value] && IMPORT_VALUE_MAP.vendor[value] !== value
        ? `导入后归一化为 ${IMPORT_VALUE_MAP.vendor[value]}`
        : '网络设备或网络安全厂商',
    ]);
    const networkVendorRowsEn = NETWORK_IMPORT_VENDOR_VALUES.map(value => [
      'Network/Security',
      'Vendor',
      value,
      IMPORT_VALUE_MAP.vendor[value] && IMPORT_VALUE_MAP.vendor[value] !== value
        ? `Normalized to ${IMPORT_VALUE_MAP.vendor[value]}`
        : 'Network or security vendor',
    ]);
    const networkPlatformRowsZh = NETWORK_IMPORT_PLATFORM_VALUES.map(value => [
      '网络/安全设备',
      '平台 (Platform)',
      value,
      IMPORT_VALUE_MAP.platform[value] || value,
    ]);
    const networkPlatformRowsEn = NETWORK_IMPORT_PLATFORM_VALUES.map(value => [
      'Network/Security',
      'Platform',
      value,
      IMPORT_VALUE_MAP.platform[value] || value,
    ]);
    const optRows = zh ? [
      ['通用', '录入来源', '新设备', '新采购或新部署设备；导入时强制以待投产状态入库'],
      ['通用', '录入来源', '存量设备', '历史运行设备补录；允许填写已投产并登记免上收原因'],
      ['通用', '投产状态', '待投产', '尚未完成口令上收'],
      ['通用', '投产状态', '已投产', '已完成上收，或存量设备按豁免方式投产'],
      ['通用', '资产状态', '在用', '资产正在使用'],
      ['通用', '资产状态', '闲置', '资产当前未使用'],
      ['通用', '资产状态', '库存中', '资产位于库存'],
      ['通用', '连接方式', 'SSH', '通过 SSH 管理设备'],
      ['管理入口', '管理方式', 'Web管理', 'Web 管理入口；默认 HTTPS/443，端口填写 80 时按 HTTP 处理'],
      ['管理入口', 'SSH算法策略', '自动', '默认策略：现代算法优先，并兼容安全的旧算法'],
      ['管理入口', 'SSH算法策略', '现代算法', '严格限制为现代算法；设备较旧时可能无法连接'],
      ['管理入口', 'SSH算法策略', '兼容旧算法', '受控启用 group14-sha1、ssh-rsa、AES-CBC、HMAC-SHA1 等安全旧算法'],
      ['管理入口', 'SSH算法策略', '极旧设备兼容', '紧急 break-glass 模式；可能启用 group1、ssh-dss、MD5、RC4 等高风险算法，必须审计'],
      ['服务器', '厂商 (Vendor)', 'Linux', '通用 Linux 服务器'],
      ['服务器', '厂商 (Vendor)', 'Dell', '戴尔'],
      ['服务器', '厂商 (Vendor)', 'HP', '惠普'],
      ['服务器', '厂商 (Vendor)', 'generic', '其它通用厂商'],
      ['服务器', '平台', 'Linux（通用）', '通用 Linux 服务器'],
      ['服务器', '平台 (Platform)', 'ubuntu', 'Ubuntu'],
      ['服务器', '平台 (Platform)', 'centos', 'CentOS'],
      ['服务器', '平台 (Platform)', 'debian', 'Debian'],
      ['服务器', '平台', '红帽 RHEL', 'Red Hat Enterprise Linux'],
      ['服务器', '平台 (Platform)', 'windows', 'Windows Server'],
      ['服务器', '平台 (Platform)', 'esxi', 'VMware ESXi'],
      ...networkVendorRowsZh,
      ...networkPlatformRowsZh,
      ...NETWORK_TOPOLOGY_ROLE_OPTIONS.map(option => ['网络/安全设备', '拓扑角色', option.label.zh, option.value]),
      ...TOPOLOGY_FUNCTION_OPTIONS.map(option => ['通用', '功能', option.label.zh, option.value]),
      ...TOPOLOGY_ZONE_OPTIONS.map(option => ['通用', '区域', option.label.zh, option.value]),
      ['服务器', '设备分类', '机架式服务器', '标准机架式服务器'],
      ['服务器', '设备分类', '刀片服务器', '刀片式服务器'],
      ['服务器', '设备分类', '塔式服务器', '塔式服务器'],
      ['服务器', '设备分类', '高密度服务器', '高密度计算节点'],
      ['服务器', '设备分类', 'GPU服务器', 'GPU 计算服务器'],
      ['服务器', '设备分类', '存储服务器', '存储用途服务器'],
      ['服务器', '设备分类', '虚拟化宿主机', '虚拟化平台宿主机'],
      ['网络/安全设备', '设备分类', '交换机', '网络交换设备'],
      ['网络/安全设备', '设备分类', '路由器', '网络路由设备'],
      ['网络/安全设备', '设备分类', '防火墙', '安全防护设备'],
      ['网络/安全设备', '设备分类', '负载均衡', '负载均衡设备'],
      ['网络/安全设备', '设备分类', '无线AP', '无线接入点'],
    ] : [
      ['Common', 'Connection Method', 'SSH', 'Manage the device over SSH'],
      ['Management Entry', 'Management Method', 'Web Management', 'Web entry; defaults to HTTPS/443, or HTTP when port 80 is entered'],
      ['Management Entry', 'SSH Algorithm Profile', 'auto', 'Modern algorithms first with the safe legacy fallback set'],
      ['Management Entry', 'SSH Algorithm Profile', 'modern', 'Strict modern-only policy; older devices may fail to connect'],
      ['Management Entry', 'SSH Algorithm Profile', 'legacy_compat', 'Controlled fallback for group14-sha1, ssh-rsa, AES-CBC and HMAC-SHA1'],
      ['Management Entry', 'SSH Algorithm Profile', 'legacy_break_glass', 'Emergency break-glass mode; may enable group1, ssh-dss, MD5 and RC4. Audit every use'],
      ['Common', 'Asset Origin', 'new', 'New device; always imported as staging'],
      ['Common', 'Asset Origin', 'legacy', 'Legacy device; may be imported as production with an exemption reason'],
      ['Server', 'Vendor', 'Linux', 'Linux Server'],
      ['Server', 'Vendor', 'Dell', 'Dell'],
      ['Server', 'Vendor', 'HP', 'HP'],
      ['Server', 'Vendor', 'generic', 'Generic Vendor'],
      ['Server', 'Platform', 'linux', 'Linux (Generic)'],
      ['Server', 'Platform', 'ubuntu', 'Ubuntu'],
      ['Server', 'Platform', 'centos', 'CentOS'],
      ['Server', 'Platform', 'debian', 'Debian'],
      ['Server', 'Platform', 'redhat', 'Red Hat (RHEL)'],
      ['Server', 'Platform', 'windows', 'Windows Server'],
      ['Server', 'Platform', 'esxi', 'VMware ESXi'],
      ...networkVendorRowsEn,
      ...networkPlatformRowsEn,
      ...NETWORK_TOPOLOGY_ROLE_OPTIONS.map(option => ['Network/Security', 'Topology Role', option.value, option.label.en]),
      ...TOPOLOGY_FUNCTION_OPTIONS.map(option => ['Common', 'Function', option.value, option.label.en]),
      ...TOPOLOGY_ZONE_OPTIONS.map(option => ['Common', 'Zone', option.value, option.label.en]),
      ['Server', 'Device Category', 'server', 'Server'],
      ['Network/Security', 'Device Category', 'network_device', 'Network Device'],
    ];

    const visibleOptRows = zh
      ? [
        ...optRows.slice(0, 8),
        ['管理入口', '浏览器终端', 'Web SSH', 'SSH 只需填一行；导入后同时提供 SSH 终端和 Web SSH，不要另填一行'],
      ]
      : [
        ...optRows.slice(0, 2),
        ['Management Entry', 'Browser Terminal', 'Web SSH', 'One SSH row automatically provides both SSH terminal and Web SSH; do not add another row'],
        ...optRows.slice(2, 8),
      ];
    const wsOpt = XLSX.utils.aoa_to_sheet([optHeaders, ...visibleOptRows]);
    wsOpt['!cols'] = optHeaders.map(() => ({ wch: 25 }));
    XLSX.utils.book_append_sheet(wb, wsOpt, zh ? '参数可选值参考' : 'Option Reference');

    XLSX.writeFile(wb, zh ? '资产导入模板.xlsx' : 'asset_import_template.xlsx');
  };

  const typeDisplay = (a: Asset) => typeMeta(a.asset_type).label[zh ? 'zh' : 'en'];

  const categoryDisplay = (a: Asset) => assetCategoryLabel(a.device_category, zh ? 'zh' : 'en');

  const renderAssetCell = (column: AssetColumnKey, a: Asset): React.ReactNode => {
    const onlineStatus = a.online_status || (a.status === 'active' ? 'online' : a.status === 'inactive' ? 'offline' : 'pending');
    const onlineMeta = onlineStatus === 'online'
      ? { label: zh ? '在线' : 'Online', badge: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300', dot: 'bg-emerald-500' }
      : onlineStatus === 'offline'
        ? { label: zh ? '离线' : 'Offline', badge: 'bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300', dot: 'bg-rose-500' }
        : { label: zh ? '待确认' : 'Pending', badge: 'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300', dot: 'bg-amber-400' };
    switch (column) {
      case 'hostname': return <span className="font-bold text-xs text-gray-900 dark:text-white leading-tight">{a.hostname || '—'}</span>;
      case 'asset_tag': return <span className="font-mono text-xs text-gray-600 dark:text-zinc-400">{a.asset_tag || '—'}</span>;
      case 'asset_type': return (
        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300 text-[10px] font-semibold">
          {a.asset_type === 'server' ? <Server size={11} /> : <Router size={11} />}
          {typeDisplay(a)}
        </span>
      );
      case 'device_category': return <span className="text-xs text-gray-700 dark:text-zinc-300">{categoryDisplay(a)}</span>;
      case 'device_role': return <span className="text-xs text-gray-600 dark:text-zinc-400">{a.device_role || '—'}</span>;
      case 'site': return (
        <span className="text-xs font-medium text-gray-800 dark:text-zinc-200 truncate block">{a.site_name || a.site_code || '—'}</span>
      );
      case 'rack': return <span className="font-mono text-xs text-gray-600 dark:text-zinc-400">{a.rack || '—'}</span>;
      case 'rack_unit': return <span className="font-mono text-xs text-gray-600 dark:text-zinc-400">{a.rack_unit ? `U${a.rack_unit}` : '—'}</span>;
      case 'status': return (
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold ${onlineMeta.badge}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${onlineMeta.dot}`} />
          {onlineMeta.label}
        </span>
      );
      case 'tags': return a.tags?.length ? (
        <div className="flex flex-wrap items-center gap-1 max-w-[200px]">
          {a.tags.slice(0, 3).map(tag => (
            <span key={tag.id} className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[9px] font-semibold whitespace-nowrap" style={{ color: tag.color || '#2563eb', backgroundColor: `${tag.color || '#2563eb'}15` }}>
              <span className="h-1 w-1 rounded-full" style={{ backgroundColor: tag.color || '#2563eb' }} />
              {zh ? (tag.label_zh || tag.label) : tag.label}
            </span>
          ))}
          {a.tags.length > 3 && <span className="text-[9px] font-mono text-gray-400">+{a.tags.length - 3}</span>}
        </div>
      ) : <span className="text-gray-300 dark:text-zinc-600">—</span>;
      case 'vendor': return <span className="text-xs font-semibold text-gray-700 dark:text-zinc-300">{a.vendor || '—'}</span>;
      case 'model': return <span className="text-xs text-gray-600 dark:text-zinc-400">{a.model || '—'}</span>;
      case 'serial_number': return <span className="font-mono text-xs text-gray-600 dark:text-zinc-400">{a.serial_number || '—'}</span>;
      case 'management_ip': return <span className="font-mono text-xs font-semibold text-gray-800 dark:text-zinc-200">{a.management_ip || '—'}</span>;
      case 'ssh_algorithm_profile': {
        const profile = a.ssh_algorithm_profile || 'auto';
        const option = SSH_ALGORITHM_PROFILE_OPTIONS.find(item => item.value === profile);
        const risky = profile === 'legacy_break_glass';
        return (
          <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${risky ? 'bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300' : profile === 'legacy_compat' ? 'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300' : 'bg-slate-100 text-slate-600 dark:bg-zinc-800 dark:text-zinc-300'}`}>
            {risky && <AlertTriangle size={10} />}
            {option ? option.label[zh ? 'zh' : 'en'] : profile}
          </span>
        );
      }
      case 'lifecycle': return rotatingAssetId === a.id ? (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 text-[10px] font-semibold">
          <Loader2 size={10} className="animate-spin" />{zh ? '上收中' : 'Rotating'}
        </span>
      ) : (
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold ${
          a.lifecycle_status === 'production' ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300' :
          a.lifecycle_status === 'decommissioned' ? 'bg-gray-100 text-gray-600 dark:bg-zinc-800 dark:text-zinc-400' :
          a.lifecycle_status === 'maintenance' ? 'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300' :
          'bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300'
        }`}>
          <span className={`h-1.5 w-1.5 rounded-full ${
            a.lifecycle_status === 'production' ? 'bg-emerald-500' :
            a.lifecycle_status === 'decommissioned' ? 'bg-gray-400' :
            a.lifecycle_status === 'maintenance' ? 'bg-amber-500' :
            'bg-blue-500'
          }`} />
          {LIFECYCLE_STATUSES.find(l => l.value === a.lifecycle_status)?.label[zh ? 'zh' : 'en'] || (zh ? '待投产' : 'Staging')}
        </span>
      );
      case 'created_at': return <span className="text-xs font-mono text-gray-400 tabular-nums">{a.created_at?.replace('T', ' ').slice(0, 19) || '—'}</span>;
      case 'updated_at': return <span className="text-xs font-mono text-gray-400 tabular-nums">{a.updated_at?.replace('T', ' ').slice(0, 19) || '—'}</span>;
    }
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHero
        icon={Package}
        title={zh ? '资产管理' : 'Asset Management'}
        subtitle={zh
          ? '设备台账 · 资产生命周期 · 网络设备导入时通过 SNMP 校准主机名'
          : 'Device inventory and lifecycle · SNMP hostname sync runs during network device import'}
      />

      <div className="flex-1 overflow-auto p-5 space-y-4">
        <input ref={fileInputRef} type="file" accept=".xlsx,.xls,.csv" className="hidden" onChange={handleImport} />

        {summaryError && (
          <div role="alert" className={`flex flex-wrap items-center justify-between gap-3 rounded-xl border px-4 py-3 text-xs ${summaryError.permissionDenied ? 'border-amber-200 bg-amber-50 text-amber-800' : 'border-rose-200 bg-rose-50 text-rose-800'}`}>
            <span>{summaryError.message}</span>
            <button type="button" onClick={() => { void fetchSummary(); }} className="rounded-lg border border-current/20 px-3 py-1.5 font-semibold hover:bg-black/5">{zh ? '重试' : 'Retry'}</button>
          </div>
        )}
        {sitesError && (
          <div role="alert" className={`flex flex-wrap items-center justify-between gap-3 rounded-xl border px-4 py-3 text-xs ${sitesError.permissionDenied ? 'border-amber-200 bg-amber-50 text-amber-800' : 'border-rose-200 bg-rose-50 text-rose-800'}`}>
            <span>{sitesError.message}</span>
            <button type="button" onClick={() => { void fetchSites(); }} className="rounded-lg border border-current/20 px-3 py-1.5 font-semibold hover:bg-black/5">{zh ? '重试' : 'Retry'}</button>
          </div>
        )}

        <AnimatePresence>
          {feedbackMsg && (
            <motion.div
              role="alert"
              initial={{ opacity: 0, y: -12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -12 }}
              transition={{ duration: 0.25 }}
              className={`fixed right-6 top-20 z-[220] flex w-[min(560px,calc(100vw-2rem))] items-start gap-3 px-4 py-3 rounded-2xl border shadow-2xl backdrop-blur-sm ${
                feedbackMsg.type === 'success' ? 'bg-emerald-50/95 border-emerald-200 text-emerald-800 dark:bg-emerald-950/90 dark:text-emerald-200 dark:border-emerald-800' :
                feedbackMsg.type === 'warning' ? 'bg-amber-50/95 border-amber-200 text-amber-800 dark:bg-amber-950/90 dark:text-amber-200 dark:border-amber-800' :
                feedbackMsg.type === 'info' ? 'bg-blue-50/95 border-blue-200 text-blue-800 dark:bg-blue-950/90 dark:text-blue-200 dark:border-blue-800' :
                'bg-rose-50/95 border-rose-200 text-rose-800 dark:bg-rose-950/90 dark:text-rose-200 dark:border-rose-800'
              }`}
            >
              {feedbackMsg.type === 'success' ? <CheckCircle2 size={18} className="text-emerald-500 shrink-0 mt-0.5" /> :
               feedbackMsg.type === 'warning' ? <AlertTriangle size={18} className="text-amber-500 shrink-0 mt-0.5" /> :
               feedbackMsg.type === 'info' ? (rotatingAssetId ? <Loader2 size={18} className="text-blue-500 shrink-0 animate-spin mt-0.5" /> : <Info size={18} className="text-blue-500 shrink-0 mt-0.5" />) :
               <AlertCircle size={18} className="text-rose-500 shrink-0 mt-0.5" />}
              <div className="flex-1 min-w-0">
                <div className="text-sm font-bold">{feedbackMsg.text}</div>
                {feedbackMsg.details?.length ? (
                  <ul className="mt-1 max-h-52 space-y-0.5 overflow-auto text-xs font-normal leading-4 opacity-90">
                    {feedbackMsg.details.map((detail, index) => <li key={`${detail}-${index}`}>{detail}</li>)}
                  </ul>
                ) : null}
              </div>
              <button onClick={() => setFeedbackMsg(null)} className="p-1 rounded-lg hover:bg-black/5 dark:hover:bg-white/10 transition-colors cursor-pointer">
                <X size={14} />
              </button>
            </motion.div>
          )}
        </AnimatePresence>

        {batchTakeoverResults.length > 0 && (
          <div className="rounded-2xl border border-gray-200/70 dark:border-zinc-800/80 bg-white dark:bg-zinc-900/90 shadow-2xs overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-100 dark:border-zinc-800 bg-gray-50/70 dark:bg-zinc-800/40 px-4 py-3">
              <div>
                <div className="text-xs font-bold text-gray-900 dark:text-white">{zh ? '批量口令上收结果' : 'Batch takeover results'}</div>
                <div className="mt-0.5 text-[11px] text-gray-400">{zh ? '绑定凭据的设备已在任务创建前拦截，不会修改设备口令。' : 'Credential-bound devices are blocked before task creation and will not be modified.'}</div>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-xs font-semibold">
                {[
                  { key: 'running', label: zh ? '处理中' : 'Running', cls: 'text-blue-600 dark:text-blue-400' },
                  { key: 'completed', label: zh ? '成功' : 'Completed', cls: 'text-emerald-600 dark:text-emerald-400' },
                  { key: 'failed', label: zh ? '失败' : 'Failed', cls: 'text-rose-600 dark:text-rose-400' },
                  { key: 'blocked_credential', label: zh ? '已拦截' : 'Blocked', cls: 'text-amber-600 dark:text-amber-400' },
                ].map(item => {
                  const count = batchTakeoverResults.filter(result => result.status === item.key).length;
                  return <span key={item.key} className={item.cls}>{item.label} {count}</span>;
                })}
              </div>
            </div>
            <div className="max-h-56 overflow-auto divide-y divide-gray-100 dark:divide-zinc-800">
              {batchTakeoverDisplayResults.map(result => {
                const statusMeta = result.status === 'completed'
                  ? { label: zh ? '成功' : 'Completed', cls: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300', Icon: CheckCircle2 }
                  : result.status === 'failed' || result.status === 'error' || result.status === 'timeout'
                    ? { label: result.status === 'timeout' ? (zh ? '超时' : 'Timeout') : (zh ? '失败' : 'Failed'), cls: 'bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300', Icon: AlertCircle }
                    : result.status === 'blocked_credential'
                      ? { label: zh ? '绑定凭据，未执行' : 'Blocked', cls: 'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300', Icon: Lock }
                      : { label: zh ? '处理中' : 'Running', cls: 'bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300', Icon: Loader2 };
                const StatusIcon = statusMeta.Icon;
                return (
                  <div key={result.id} className="flex flex-wrap items-center gap-3 px-4 py-2.5 text-xs">
                    <div className="min-w-[170px] flex-1">
                      <div className="font-bold text-gray-800 dark:text-zinc-200">{result.status === 'blocked_credential' ? (zh ? `${result.device_count || 1} 台设备` : `${result.device_count || 1} devices`) : (result.hostname || result.id)}</div>
                      <div className="font-mono text-xs text-gray-400">{result.status === 'blocked_credential' ? (result.device_names || []).slice(0, 3).join('、') + ((result.device_count || 0) > 3 ? ` +${(result.device_count || 0) - 3}` : '') : (result.management_ip || '—')}</div>
                    </div>
                    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[10px] font-semibold ${statusMeta.cls}`}>
                      <StatusIcon size={12} className={result.status === 'running' ? 'animate-spin' : ''} />
                      {statusMeta.label}
                    </span>
                    <div className="min-w-[260px] flex-[2] text-gray-500 dark:text-zinc-400">
                      {result.status === 'blocked_credential' && result.credential_name ? <span className="font-medium text-amber-700 dark:text-amber-300">{zh ? '关联凭据：' : 'Credential: '}{result.credential_name} · </span> : null}
                      {result.message || '—'}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* 5-Bento Status Cards */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3.5">
          {([
            {
              key: 'all',
              value: summary ? totalCount : '—',
              label: zh ? '全部资产' : 'All Assets',
              sub: zh ? '全部' : 'ALL',
              Icon: Package,
              pill: 'bg-slate-100 dark:bg-zinc-800 text-slate-700 dark:text-zinc-300 border-slate-200/80 dark:border-zinc-700/80',
              iconBg: 'bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-300',
              activeBorder: 'border-blue-500 ring-2 ring-blue-500/20 shadow-sm',
              filterVal: 'all',
            },
            {
              key: 'critical',
              value: summary ? criticalCount : '—',
              label: zh ? '严重故障' : 'Critical',
              sub: 'P1',
              Icon: Flame,
              pill: 'bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300 border-rose-200/80 dark:border-rose-900/50',
              iconBg: 'bg-rose-50 dark:bg-rose-950/50 text-rose-600 dark:text-rose-400',
              activeBorder: 'border-rose-500 ring-2 ring-rose-500/20',
              filterVal: 'critical',
              pulse: true,
            },
            {
              key: 'major',
              value: summary ? majorCount : '—',
              label: zh ? '重要问题' : 'Major Issues',
              sub: 'P2',
              Icon: AlertTriangle,
              pill: 'bg-orange-50 text-orange-700 dark:bg-orange-950/40 dark:text-orange-300 border-orange-200/80 dark:border-orange-900/50',
              iconBg: 'bg-orange-50 dark:bg-orange-950/50 text-orange-600 dark:text-orange-400',
              activeBorder: 'border-orange-500 ring-2 ring-orange-500/20',
              filterVal: 'major',
            },
            {
              key: 'warning',
              value: summary ? warningCount : '—',
              label: zh ? '需要关注' : 'Warning',
              sub: 'P3',
              Icon: AlertCircle,
              pill: 'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300 border-amber-200/80 dark:border-amber-900/50',
              iconBg: 'bg-amber-50 dark:bg-amber-950/50 text-amber-600 dark:text-amber-400',
              activeBorder: 'border-amber-500 ring-2 ring-amber-500/20',
              filterVal: 'warning',
            },
            {
              key: 'healthy',
              value: summary ? healthyCount : '—',
              label: zh ? '运行正常' : 'Healthy',
              sub: zh ? '正常' : 'OK',
              Icon: CheckCircle2,
              pill: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300 border-emerald-200/80 dark:border-emerald-900/50',
              iconBg: 'bg-emerald-50 dark:bg-emerald-950/50 text-emerald-600 dark:text-emerald-400',
              activeBorder: 'border-emerald-500 ring-2 ring-emerald-500/20',
              filterVal: 'healthy',
            },
          ]).map(c => {
            const isActive = severityFilter === c.filterVal;
            const isEmpty = !summary || c.value === 0;
            const numericValue = typeof c.value === 'number' ? c.value : 0;
            const pct = summary && totalCount > 0 ? Math.round((numericValue / totalCount) * 100) : 0;
            return (
              <button
                key={c.key}
                type="button"
                onClick={() => setSeverityFilter(c.filterVal === 'all' ? 'all' : isActive ? 'all' : c.filterVal)}
                className={`group relative rounded-2xl border p-4 text-left transition-all duration-200 bg-white dark:bg-zinc-900/90 shadow-2xs cursor-pointer ${
                  isActive
                    ? `${c.activeBorder} shadow-sm`
                    : 'border-gray-200/70 dark:border-zinc-800/80 hover:border-gray-300 dark:hover:border-zinc-700 hover:shadow-xs'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="flex items-center gap-1.5">
                      <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[9px] font-bold tracking-wider uppercase font-mono ${c.pill}`}>
                        {c.sub}
                      </span>
                      <span className="text-xs font-semibold text-gray-500 dark:text-zinc-400">{c.label}</span>
                    </div>
                    <div className="mt-2.5 flex items-baseline gap-2">
                      <span className="text-2xl font-black tabular-nums tracking-tight font-mono text-gray-900 dark:text-white">
                        {c.value}
                      </span>
                      {totalCount > 0 && (
                        <span className="text-xs font-mono text-gray-400">
                          ({pct}%)
                        </span>
                      )}
                    </div>
                  </div>
                  <div className={`flex h-9 w-9 items-center justify-center rounded-xl transition-transform group-hover:scale-105 ${c.iconBg}`}>
                    <c.Icon size={18} className={!isEmpty && (c as any).pulse ? 'animate-pulse' : ''} />
                  </div>
                </div>

                {/* Micro fluid indicator */}
                <div className="mt-3 h-1 w-full overflow-hidden rounded-full bg-gray-100 dark:bg-zinc-800">
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${
                      c.key === 'all' ? 'bg-blue-500' :
                      c.key === 'critical' ? 'bg-rose-500' :
                      c.key === 'major' ? 'bg-orange-500' :
                      c.key === 'warning' ? 'bg-amber-500' :
                      'bg-emerald-500'
                    }`}
                    style={{ width: `${Math.max(numericValue > 0 ? 6 : 0, pct)}%` }}
                  />
                </div>
              </button>
            );
          })}
        </div>

        {/* Main Table Container */}
        <div className="bg-white dark:bg-zinc-900/90 border border-gray-200/70 dark:border-zinc-800/80 rounded-2xl shadow-2xs overflow-hidden">
          {assetError && (
            <div role="alert" className={`flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3 text-xs ${assetError.permissionDenied ? 'border-amber-200 bg-amber-50 text-amber-800' : 'border-rose-200 bg-rose-50 text-rose-800'}`}>
              <div>
                <p className="font-semibold">{assetError.message}</p>
                {assetsLastLoadedAt && <p className="mt-1 opacity-80">{zh ? '保留的资产列表更新时间：' : 'Showing asset data last updated: '}{assetsLastLoadedAt.toLocaleString(zh ? 'zh-CN' : 'en-US')}</p>}
              </div>
              <button type="button" onClick={() => { void fetchAssets(); }} className="rounded-lg border border-current/20 px-3 py-1.5 font-semibold hover:bg-black/5">{zh ? '重试' : 'Retry'}</button>
            </div>
          )}
          {/* Header Bar */}
          <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-b border-gray-100 dark:border-zinc-800 bg-gray-50/50 dark:bg-zinc-800/30">
            <div className="flex items-center gap-2">
              <span className="flex items-center gap-1.5 px-3 py-1 rounded-xl bg-blue-50 dark:bg-blue-950/50 text-blue-600 dark:text-blue-400 text-xs font-bold shadow-2xs">
                <LayoutList size={13} />
                {zh ? '资产台账' : 'Inventory Table'}
              </span>

              <AnimatePresence>
                {selectedIds.size > 0 && (
                  <motion.div
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.95 }}
                    className="flex items-center gap-1.5 ml-2 pl-3 border-l border-gray-200 dark:border-zinc-700"
                  >
                    <span className="text-xs font-bold text-blue-600 dark:text-blue-400 font-mono px-2 py-0.5 rounded-full bg-blue-50 dark:bg-blue-950/40">
                      {selectedIds.size} {zh ? '已选' : 'selected'}
                    </span>
                    <button
                      type="button"
                      onClick={requestBatchTakeover}
                      className="flex items-center gap-1 px-2.5 py-1 rounded-xl bg-blue-50 text-blue-600 hover:bg-blue-100 text-xs font-semibold transition-all cursor-pointer"
                    >
                      <Shield size={12} />
                      {zh ? '批量上收' : 'Takeover'}
                    </button>
                    <ActionButton icon={Trash2} variant="danger" size="sm" onClick={handleBatchDelete}>
                      {zh ? '批量删除' : 'Delete'}
                    </ActionButton>
                    <button
                      type="button"
                      onClick={clearSel}
                      className="p-1 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100 cursor-pointer"
                      title="Clear"
                    >
                      <X size={12} />
                    </button>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={openAdd}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-blue-600 text-white text-xs font-semibold hover:bg-blue-700 shadow-2xs transition-all cursor-pointer"
                title={zh ? '新增资产' : 'Add Asset'}
              >
                <Plus size={13} />
                <span>{zh ? '新增' : 'Add'}</span>
              </button>

              <div className="flex items-center gap-1 border-l border-gray-200 dark:border-zinc-700 pl-2">
                <button
                  type="button"
                  onClick={() => { fetchAssets(); fetchSummary(); }}
                  className="p-1.5 rounded-xl border border-gray-200/80 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-gray-600 dark:text-zinc-300 hover:bg-gray-50 hover:text-blue-600 transition-all cursor-pointer"
                  title={zh ? '刷新' : 'Refresh'}
                >
                  <RefreshCw size={13} />
                </button>
                <button
                  type="button"
                  onClick={handleDownloadTemplate}
                  className="p-1.5 rounded-xl border border-gray-200/80 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-gray-600 dark:text-zinc-300 hover:bg-gray-50 hover:text-blue-600 transition-all cursor-pointer"
                  title={zh ? '下载模板' : 'Template'}
                >
                  <FileText size={13} />
                </button>
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="p-1.5 rounded-xl border border-gray-200/80 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-gray-600 dark:text-zinc-300 hover:bg-gray-50 hover:text-blue-600 transition-all cursor-pointer"
                  title={zh ? '导入' : 'Import'}
                >
                  <Upload size={13} />
                </button>
              </div>
            </div>
          </div>

          {/* Filter Bar */}
          <div className="border-b border-gray-100 dark:border-zinc-800 px-4 py-2.5">
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative flex-1 min-w-[220px] max-w-[320px]">
                <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <input
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder={zh ? '搜索 IP / 主机名 / 资产编号 / 序列号...' : 'Search IP / hostname / tag / serial...'}
                  className="w-full pl-8 pr-7 py-1.5 rounded-xl bg-gray-50 dark:bg-zinc-800 border border-gray-200/80 dark:border-zinc-700 text-xs text-gray-800 dark:text-zinc-100 placeholder:text-gray-400 focus:outline-none focus:border-blue-500 focus:bg-white transition-all"
                />
                {search && (
                  <button onClick={() => setSearch('')} title="Clear" className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 cursor-pointer">
                    <X size={11} />
                  </button>
                )}
              </div>

              {([
                { val: typeFilter,   set: setTypeFilter,   label: zh ? '类型' : 'Type',   opts: TYPES.map(t => ({ v: t.value, l: t.label[zh ? 'zh' : 'en'] })) },
                { val: statusFilter, set: setStatusFilter, label: zh ? '状态' : 'Status', opts: [
                  ...STATUSES.map(s => ({ v: s.value, l: s.label[zh ? 'zh' : 'en'] })),
                  { v: 'online', l: zh ? '在线' : 'Online' },
                  { v: 'offline', l: zh ? '离线' : 'Offline' },
                  { v: 'pending', l: zh ? '待确认' : 'Pending' },
                ] },
              ] as const).map(f => (
                <select
                  key={f.label}
                  value={f.val}
                  onChange={e => f.set(e.target.value)}
                  title={f.label}
                  className={`px-3 py-1.5 rounded-xl border text-xs outline-none cursor-pointer transition-all ${
                    f.val !== 'all'
                      ? 'bg-blue-50 border-blue-200 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300 font-semibold'
                      : 'bg-gray-50 dark:bg-zinc-800 border-gray-200/80 dark:border-zinc-700 text-gray-600 dark:text-zinc-300'
                  }`}
                >
                  <option value="all">{f.label}</option>
                  {f.opts.map(o => <option key={o.v} value={o.v}>{o.l}</option>)}
                </select>
              ))}

              <TagFilterDropdown
                allTags={allTags}
                selectedTagIds={tagFilter}
                onChange={setTagFilter}
                language={language}
              />

              <button
                type="button"
                onClick={() => setShowAdvancedFilter(p => !p)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-xs font-semibold transition-all cursor-pointer ${
                  showAdvancedFilter || advancedFilterCount > 0
                    ? 'bg-blue-50 border-blue-200 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300'
                    : 'bg-gray-50 dark:bg-zinc-800 border-gray-200/80 dark:border-zinc-700 text-gray-600 dark:text-zinc-300 hover:bg-gray-100'
                }`}
                title={zh ? '高级筛选' : 'Advanced Filters'}
              >
                <SlidersHorizontal size={12} />
                <span>{zh ? '高级筛选' : 'Filters'}</span>
                {advancedFilterCount > 0 && (
                  <span className="h-4 min-w-[16px] inline-flex items-center justify-center rounded-full bg-blue-600 text-white text-[9px] font-bold font-mono">
                    {advancedFilterCount}
                  </span>
                )}
              </button>

              {(hasFilters || severityFilter !== 'all') && (
                <button
                  type="button"
                  onClick={clearAllFilters}
                  className="text-xs font-semibold text-blue-600 hover:underline ml-1 cursor-pointer whitespace-nowrap"
                >
                  {zh ? '重置筛选' : 'Reset'}
                </button>
              )}

              <div className="flex-1" />
              <span className="text-xs font-mono text-gray-400 tabular-nums whitespace-nowrap">
                {zh ? `共 ${severityFilter !== 'all' ? displayAssets.length : total} 条资产` : `${severityFilter !== 'all' ? displayAssets.length : total} assets`}
              </span>
            </div>

            <AnimatePresence>
              {showAdvancedFilter && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.15 }}
                  className="overflow-hidden"
                >
                  <div className="flex flex-wrap items-center gap-2 pt-2.5 mt-2.5 border-t border-gray-100 dark:border-zinc-800">
                    <span className="text-xs font-medium text-gray-400 mr-1">{zh ? '高级筛选:' : 'Filters:'}</span>
                    {([
                      { val: vendorFilter, set: setVendorFilter, label: zh ? '厂商' : 'Vendor', opts: vendorList.map(v => ({ v, l: v })),   hide: !vendorList.length },
                      { val: dcFilter,     set: setDcFilter,     label: zh ? '站点' : 'Site',   opts: dcList.map(d => ({ v: d.value, l: d.label })), hide: !dcList.length },
                      { val: deptFilter,   set: setDeptFilter,   label: zh ? '业务部门' : 'Department', opts: deptList.map(d => ({ v: d, l: d })),  hide: !deptList.length },
                      { val: lifecycleFilter, set: setLifecycleFilter, label: zh ? '生命周期' : 'Lifecycle', opts: LIFECYCLE_STATUSES.map(s => ({ v: s.value, l: s.label[zh ? 'zh' : 'en'] })), hide: false },
                    ] as const).filter(f => !f.hide).map(f => (
                      <select
                        key={f.label}
                        value={f.val}
                        onChange={e => f.set(e.target.value)}
                        title={f.label}
                        className={`px-3 py-1.5 rounded-xl border text-xs outline-none cursor-pointer transition-all ${
                          f.val !== 'all'
                            ? 'bg-blue-50 border-blue-200 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300 font-semibold'
                            : 'bg-gray-50 dark:bg-zinc-800 border-gray-200/80 dark:border-zinc-700 text-gray-600 dark:text-zinc-300'
                        }`}
                      >
                        <option value="all">{f.label}</option>
                        {f.opts.map(o => <option key={o.v} value={o.v}>{o.l}</option>)}
                      </select>
                    ))}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          <DataTableFrame className="rounded-none border-0 shadow-none">
              <DataTable className="text-xs" exportConfig={{ filename: 'assets', language: zh ? 'zh' : 'en', disabled: loading || displayAssets.length === 0, exportData: exportAssetData }}>
                <thead>
                  <tr className="border-b border-gray-100 dark:border-zinc-800 bg-gray-50/50 dark:bg-zinc-800/40">
                    <th className="w-8 px-3 py-3 text-center">
                      <input type="checkbox" checked={selectedIds.size === displayAssets.length && displayAssets.length > 0} onChange={toggleAll} className="h-3.5 w-3.5 rounded border-gray-300 accent-blue-600 cursor-pointer" />
                    </th>
                    {DEFAULT_VISIBLE_ASSET_COLUMNS.map(column => (
                      <th key={column.key} className={`text-left px-3 py-3 text-[11px] font-bold uppercase tracking-wider text-gray-400 ${column.width}`}>
                        {zh ? column.zh : column.en}
                      </th>
                    ))}
                    <TableActionHeader className="w-24 px-3 py-3 text-[11px] font-bold uppercase tracking-wider text-gray-400 pr-4">{zh ? '操作' : 'Actions'}</TableActionHeader>
                  </tr>
                </thead>
                <tbody>
                  {loading && assets.length === 0 ? (
                    <tr><td colSpan={DEFAULT_VISIBLE_ASSET_COLUMNS.length + 2} className="text-center py-20 text-gray-400">
                      <RefreshCw size={18} className="mx-auto mb-2 animate-spin text-blue-500" />
                      <p className="text-xs font-medium">{zh ? '加载资产中...' : 'Loading...'}</p>
                    </td></tr>
                  ) : assetError && displayAssets.length === 0 ? (
                    <tr><td colSpan={DEFAULT_VISIBLE_ASSET_COLUMNS.length + 2} className="py-20 text-center text-sm text-rose-600">{assetError.permissionDenied ? (zh ? '无权查看资产列表。' : 'You do not have permission to view the asset list.') : (zh ? '资产列表加载失败，请使用上方按钮重试。' : 'The asset list could not be loaded. Use the retry button above.')}</td></tr>
                  ) : displayAssets.length === 0 ? (
                    <tr><td colSpan={DEFAULT_VISIBLE_ASSET_COLUMNS.length + 2} className="py-20">
                      <div className="text-center max-w-lg mx-auto">
                        <div className="relative h-20 w-20 mx-auto mb-4">
                          <div className="absolute inset-0 rounded-2xl bg-blue-50 dark:bg-blue-950/40 flex items-center justify-center">
                            <Package size={32} className="text-blue-500" />
                          </div>
                        </div>
                        <p className="text-base font-bold text-gray-800 dark:text-zinc-200 mb-1">
                          {hasFilters || severityFilter !== 'all' ? (zh ? '暂无匹配当前筛选条件的资产' : 'No assets match the filters') : (zh ? '暂无资产数据' : 'No asset records')}
                        </p>
                        <p className="text-xs text-gray-400 mb-5 leading-relaxed max-w-sm mx-auto">
                          {hasFilters || severityFilter !== 'all' ? (zh ? '请尝试重置筛选或切换严重级别分类' : '添加网络设备和服务器，自动发现拓扑，连接监控系统') : (zh ? '添加网络设备和服务器，自动发现拓扑，连接监控系统' : 'Add devices, discover topology, connect monitoring')}
                        </p>
                        <div className="flex items-center justify-center gap-2 flex-wrap">
                          {hasFilters || severityFilter !== 'all' ? (
                            <button
                              type="button"
                              onClick={clearAllFilters}
                              className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-blue-600 text-white text-xs font-bold hover:bg-blue-700 shadow-2xs cursor-pointer"
                            >
                              <RefreshCw size={13} />
                              {zh ? '重置所有筛选' : 'Reset All Filters'}
                            </button>
                          ) : (
                            <>
                              <button onClick={openAdd} className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-blue-600 text-white text-xs font-bold hover:bg-blue-700 shadow-2xs cursor-pointer"><Plus size={13} />{zh ? '添加资产' : 'Add Asset'}</button>
                              <button onClick={() => fileInputRef.current?.click()} className="flex items-center gap-1.5 px-4 py-2 rounded-xl border border-gray-200 dark:border-zinc-700 text-gray-600 dark:text-zinc-300 text-xs font-semibold hover:bg-gray-50 cursor-pointer"><Upload size={12} />{zh ? '导入 Excel' : 'Import Excel'}</button>
                            </>
                          )}
                        </div>
                      </div>
                    </td></tr>
                  ) : displayAssets.map(a => {
                    const sel = selectedIds.has(a.id);
                    const isDrawerTarget = drawerAsset?.id === a.id;

                    return (
                      <tr
                        key={a.id}
                        onClick={() => setDrawerAsset(a)}
                        className={`border-b border-gray-100 dark:border-zinc-800 cursor-pointer transition-colors ${sel ? 'bg-blue-50/50 dark:bg-blue-950/20' : isDrawerTarget ? 'bg-gray-50 dark:bg-zinc-800/40' : 'hover:bg-gray-50/70 dark:hover:bg-zinc-800/30'}`}
                      >
                        <td className="px-3 py-2.5 text-right" onClick={e => e.stopPropagation()}>
                          <input type="checkbox" checked={sel} onChange={() => toggle(a.id)} className="h-3.5 w-3.5 rounded border-gray-300 accent-blue-600 cursor-pointer" />
                        </td>
                        {DEFAULT_VISIBLE_ASSET_COLUMNS.map(column => (
                          <td key={column.key} className="px-3 py-2.5 text-xs">
                            {renderAssetCell(column.key, a)}
                          </td>
                        ))}
                        <TableActionCell className="px-3 py-2.5 whitespace-nowrap" onClick={e => e.stopPropagation()}>
                          <ActionIconGroup label={zh ? '资产操作' : 'Asset actions'}>
                            <ActionIconButton icon={Copy} label={zh ? '复制' : 'Copy'} variant="accent" onClick={() => openCopy(a)} />
                            <ActionIconButton icon={Pencil} label={zh ? '编辑' : 'Edit'} onClick={() => openEdit(a)} />
                            <ActionIconButton icon={Trash2} label={zh ? '删除' : 'Delete'} variant="danger" onClick={() => { setDeleteError(null); setDeleteTarget(a); }} />
                          </ActionIconGroup>
                        </TableActionCell>
                      </tr>
                    );
                  })}
                </tbody>
              </DataTable>
            </DataTableFrame>

            {/* Bottom Pagination */}
            <Pagination
              currentPage={page}
              totalItems={severityFilter !== 'all' ? displayAssets.length : total}
              onPageChange={setPage}
              itemsPerPage={pageSize}
              onItemsPerPageChange={setPageSize}
              language={language}
              alwaysVisible
            />
          </div>

          {terminalSession && (
            <motion.div
              className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 backdrop-blur-sm"
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              onClick={() => setTerminalSession(null)}
            >
              <motion.div
                className="bg-[#0b1220] rounded-2xl w-[900px] max-w-[95vw] h-[560px] border border-white/10 shadow-2xl flex flex-col overflow-hidden"
                onClick={(e) => e.stopPropagation()}
                initial={{ scale: 0.98, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.98, opacity: 0 }}
              >
                <div className="h-10 border-b border-white/10 px-3 flex items-center justify-between text-white/80 text-xs">
                  <div className="font-semibold">{terminalSession.title}</div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={async () => {
                        const { app: terminalType, path: terminalPath } = getLocalTerminalConfig();
                        let user = '';
                        let host = '';
                        let port = 22;

                        if (terminalTarget) {
                          user = terminalAccessLevel === 'admin' ? (terminalTarget.admin_username || 'admin') : (terminalTarget.normal_username || 'user');
                          host = terminalTarget.management_ip;
                          port = Number(terminalTarget.management_port || 22) || 22;
                        } else if (terminalSession.title.includes('@')) {
                          const [u, h] = terminalSession.title.split('@');
                          user = u;
                          host = h.split(':')[0];
                          port = Number(h.split(':')[1] || 22) || 22;
                        }

                        if (host && user) {
                          let sessionToken = '';
                          try {
                            const res = await fetch('/api/system/launch-terminal', {
                              method: 'POST',
                              headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify({
                                app_type: terminalType,
                                path: terminalPath,
                                host, user,
                                requester_username: 'unknown',
                                access_level: terminalTarget ? terminalAccessLevel : 'normal',
                              })
                            });
                            const result = await res.json();
                            if (result.success && result.session_token) {
                              sessionToken = result.session_token;
                            }
                            if (result.success && result.port) {
                              port = Number(result.port) || port;
                            }
                            if (!result.success) {
                              setFeedbackMsg({
                                type: 'error',
                                text: zh
                                  ? `设备会话创建失败：${result.error || '无法创建本地终端会话'}`
                                  : `Device session creation failed: ${result.error || 'Unable to create the local terminal session'}`,
                              });
                              setTerminalSession(null);
                              return;
                            }
                            if (!result.client_side) {
                              setTerminalSession(null);
                              return;
                            }
                            try {
                              const agentBase = (localStorage.getItem('terminal_agent_url') || 'http://127.0.0.1:17890').replace(/\/$/, '');
                              const agentRes = await fetch(`${agentBase}/v1/terminal/launch`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                  backend_url: window.location.origin,
                                  session_token: sessionToken,
                                  client: terminalType,
                                  path: terminalPath,
                                }),
                              });
                              const agentResult = await agentRes.json().catch(() => ({}));
                              if (!agentRes.ok || !agentResult.success) {
                                throw new Error(agentResult.error || `HTTP ${agentRes.status}`);
                              }
                            } catch (agentError) {
                              console.error('Local Terminal Agent launch failed', agentError);
                              setFeedbackMsg({ type: 'error', text: formatTerminalAgentError(agentError, zh) });
                              setTerminalSession(null);
                              return;
                            }
                            setTerminalSession(null);
                            return;
                          } catch (err) {
                            console.error('Local terminal session request failed', err);
                            const detail = err instanceof Error ? err.message : String(err || 'Unknown error');
                            setFeedbackMsg({
                              type: 'error',
                              text: zh ? `设备会话请求失败，请检查后端服务或网络连接：${detail}` : `Device session request failed. Check the backend service or network: ${detail}`,
                            });
                            setTerminalSession(null);
                            return;
                          }
                        }
                      }}
                      className="text-[10px] bg-emerald-500/20 text-emerald-400 px-2 py-0.5 rounded-lg hover:bg-emerald-500/30 transition-all flex items-center gap-1 cursor-pointer"
                    >
                      <MonitorSpeaker size={10} />
                      {(() => {
                        const app = getLocalTerminalConfig().app;
                        const appName = TERMINAL_APP_LABELS[app] || 'Terminal';
                        return zh ? `${appName} 调起` : `Launch ${appName}`;
                      })()}
                    </button>
                    <button onClick={() => setTerminalSession(null)} className="text-white/50 hover:text-white ml-2 cursor-pointer"><X size={14} /></button>
                  </div>
                </div>
                <div className="flex-1 bg-black/20 relative overflow-hidden">
                  <div
                    ref={el => el && initTerminal(el, 'asset-terminal')}
                    className="absolute inset-0 p-2"
                  />
                </div>
                <div className="h-12 border-t border-white/10 px-3 flex items-center gap-2">
                  <input
                    value={terminalInput}
                    onChange={(e) => setTerminalInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') sendTerminalInput(); }}
                    placeholder={zh ? '输入命令并回车' : 'Type command and press Enter'}
                    className="flex-1 h-8 bg-black/30 border border-white/15 rounded-lg px-2 text-xs text-white outline-none"
                  />
                  <button onClick={sendTerminalInput} className="h-8 px-3 rounded-lg bg-blue-600 text-white text-xs font-bold hover:bg-blue-700 cursor-pointer">{zh ? '发送' : 'Send'}</button>
                </div>
              </motion.div>
            </motion.div>
          )}
        </div>

      {/* Drawer */}
      <AssetDetailDrawer
        isOpen={!!drawerAsset}
        onClose={() => setDrawerAsset(null)}
        drawerAsset={drawerAsset}
        language={language}
      />

      {/* Delete Confirmation */}
      {showBatchTakeoverConfirm && (
        <div className="fixed inset-0 z-[230] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-slate-950/45 backdrop-blur-sm" onClick={() => setShowBatchTakeoverConfirm(false)} />
          <motion.div initial={{ opacity: 0, scale: 0.96, y: 8 }} animate={{ opacity: 1, scale: 1, y: 0 }} className="relative w-full max-w-md rounded-2xl border border-black/10 bg-white p-5 shadow-2xl">
            <div className="flex items-start gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-cyan-50 text-cyan-600"><Shield size={18} /></div>
              <div>
                <h3 className="text-base font-bold text-slate-800">{zh ? '确认批量口令上收' : 'Confirm batch takeover'}</h3>
                <p className="mt-1 text-xs leading-5 text-slate-500">{zh ? `将检查并处理已选择的 ${selectedIds.size} 台资产。已绑定凭据的设备会自动跳过，不会修改设备口令。` : `The selected ${selectedIds.size} asset(s) will be checked and processed. Credential-bound devices will be skipped without changing their passwords.`}</p>
              </div>
            </div>
            <div className="mt-4 rounded-xl border border-cyan-100 bg-cyan-50/70 px-3 py-2 text-[11px] leading-5 text-cyan-800">
              {zh ? '未绑定凭据的设备才会进入后台上收，并在下方显示逐设备结果。' : 'Only unbound devices enter the background takeover task; per-device results will appear below.'}
            </div>
            <div className="mt-5 flex justify-end gap-2 border-t border-black/5 pt-4">
              <button type="button" onClick={() => setShowBatchTakeoverConfirm(false)} className="h-9 rounded-xl border border-black/10 px-4 text-sm font-semibold text-slate-500 hover:bg-slate-50">{zh ? '取消' : 'Cancel'}</button>
              <button type="button" onClick={() => { setShowBatchTakeoverConfirm(false); void handleBatchTakeover(); }} className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-cyan-500 px-4 text-sm font-semibold text-white shadow-sm hover:bg-cyan-600"><Shield size={14} />{zh ? '确认上收' : 'Start takeover'}</button>
            </div>
          </motion.div>
        </div>
      )}

      <DeleteConfirmModal
        isOpen={!!deleteTarget}
        onClose={() => { setDeleteTarget(null); setDeleteError(null); }}
        deleteTarget={deleteTarget}
        handleDelete={handleDelete}
        error={deleteError}
        language={language}
      />

      {/* Terminal Access */}
      <TerminalAccessModal
        isOpen={!!terminalTarget}
        onClose={() => setTerminalTarget(null)}
        terminalTarget={terminalTarget}
        terminalAccessLevel={terminalAccessLevel}
        setTerminalAccessLevel={setTerminalAccessLevel}
        approvalData={approvalData}
        setApprovalData={setApprovalData}
        terminalReason={terminalReason}
        setTerminalReason={setTerminalReason}
        terminalRequesting={terminalRequesting}
        systemInfo={systemInfo}
        requestTerminalAccess={requestTerminalAccess}
        setIsApproved={setIsApproved}
        language={language}
      />

      {/* Create/Edit Asset Modal */}
      <AssetModal
        isOpen={showModal}
        onClose={() => setShowModal(false)}
        isEditMode={!!editingAsset}
        editingAsset={editingAsset}
        form={form}
        setForm={setForm}
        saving={saving}
        modalError={modalError}
        setModalError={setModalError}
        showEnableSecret={showEnableSecret}
        setShowEnableSecret={setShowEnableSecret}
        showProductionConfirm={showProductionConfirm}
        setShowProductionConfirm={setShowProductionConfirm}
        handleSave={handleSave}
        doSave={doSave}
        language={language}
        setFeedbackMsg={setFeedbackMsg}
        allTags={allTags}
      />

      {/* Asset Import Validation Modal */}
      <AssetImportValidationModal
        isOpen={showValidationModal}
        onClose={() => setShowValidationModal(false)}
        language={language}
        missingRacks={missingRacks}
        existingRacks={allRacks}
        onConfirm={handleValidationConfirm}
        saving={validationModalSaving}
      />
    </div>
  );
};

export default AssetManagementTab;
