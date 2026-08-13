import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Terminal as XTerm } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import 'xterm/css/xterm.css';
import {
  Package, Plus, Trash2, Search, X, RefreshCw, Download, Pencil, Copy,
  Server, Router, AlertTriangle, SlidersHorizontal,
  Wifi, Upload, FileText,
  AlertCircle, CheckCircle2, Info,
  Flame, LayoutList, Lock, Terminal, Eye, EyeOff, Loader2, Shield, User, MonitorSpeaker, Settings2, Check
} from 'lucide-react';
import * as XLSX from 'xlsx';
import { AnimatePresence, motion } from 'motion/react';

import Pagination from '../../components/Pagination';
import { DataTable, DataTableFrame } from '../../components/DataTable';
import PageHero from '../../components/PageHero';
import TagFilterDropdown from '../../components/TagFilterDropdown';
import { fetchAllPaginatedItems } from '../../utils/pagination';
import { useSystem } from '../../hooks/useSystem';
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
} from './constants';
import { statusMeta, typeMeta, severityOf } from './helpers';
import {
  ASSET_INFO_SHEET_RE,
  MANAGEMENT_ENTRY_SHEET_RE,
  mergeManagementMethods,
  parseManagementMethodSheet,
  type ManagementMethodImportRow,
} from './importUtils';

import { DeleteConfirmModal } from './components/DeleteConfirmModal';
import { AssetImportValidationModal, MissingRackInfo, RackResolution } from './components/AssetImportValidationModal';
import { TerminalAccessModal } from './components/TerminalAccessModal';
import { AssetDetailDrawer } from './components/AssetDetailDrawer';
import { AssetModal } from './components/AssetModal';

type AssetImportSkippedItem = {
  asset_tag?: string;
  hostname?: string;
  reason?: string;
  existing_hostname?: string;
  duplicate_labels?: string[];
  duplicate_values?: string[];
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

type AssetColumnKey =
  | 'hostname'
  | 'category_role'
  | 'site'
  | 'status'
  | 'tags'
  | 'vendor'
  | 'model'
  | 'serial_number'
  | 'management_ip'
  | 'lifecycle'
  | 'created_at'
  | 'updated_at';

type AssetColumnDefinition = {
  key: AssetColumnKey;
  zh: string;
  en: string;
  width: string;
};

const ASSET_COLUMN_DEFS: AssetColumnDefinition[] = [
  { key: 'hostname', zh: '设备', en: 'Asset', width: 'min-w-[150px]' },
  { key: 'category_role', zh: '分类 / 角色', en: 'Category / role', width: 'min-w-[130px]' },
  { key: 'site', zh: '站点', en: 'Site', width: 'w-24' },
  { key: 'status', zh: '在线状态', en: 'Status', width: 'w-[90px]' },
  { key: 'tags', zh: '标签', en: 'Tags', width: 'min-w-[120px]' },
  { key: 'vendor', zh: '厂商', en: 'Vendor', width: 'w-24' },
  { key: 'model', zh: '型号', en: 'Model', width: 'min-w-[110px]' },
  { key: 'serial_number', zh: '序列号', en: 'Serial', width: 'min-w-[130px]' },
  { key: 'management_ip', zh: '管理IP', en: 'Management IP', width: 'w-[120px]' },
  { key: 'lifecycle', zh: '资产状态', en: 'Asset status', width: 'w-[90px]' },
  { key: 'created_at', zh: '创建时间', en: 'Created', width: 'min-w-[145px]' },
  { key: 'updated_at', zh: '更新时间', en: 'Updated', width: 'min-w-[145px]' },
];

const DEFAULT_ASSET_COLUMNS: Record<AssetColumnKey, boolean> = {
  hostname: true,
  category_role: true,
  site: true,
  status: true,
  tags: false,
  vendor: true,
  model: true,
  serial_number: true,
  management_ip: true,
  lifecycle: true,
  created_at: true,
  updated_at: true,
};

const FIXED_ASSET_COLUMNS = new Set<AssetColumnKey>([
  'hostname', 'category_role', 'site', 'status', 'created_at', 'updated_at',
]);

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

const normalizeAssetColumns = (columns: Partial<Record<AssetColumnKey, boolean>>): Record<AssetColumnKey, boolean> => {
  const normalized = { ...DEFAULT_ASSET_COLUMNS, ...columns };
  FIXED_ASSET_COLUMNS.forEach(key => { normalized[key] = true; });
  return normalized;
};

const ASSET_COLUMNS_STORAGE_KEY = 'assets-dashboard-columns-v3';

const AssetManagementTab: React.FC<AssetManagementTabProps> = ({ language, setActiveTab }) => {
  const { systemInfo } = useSystem();
  const zh = language === 'zh';
  const goTo = (tab: string) => setActiveTab?.(tab);

  /* ─── State ─── */
  const [assets, setAssets]             = useState<Asset[]>([]);
  const [sites, setSites]               = useState<Array<{ id: string; site_name: string; site_code: string }>>([]);
  const [summary, setSummary]           = useState<AssetSummary | null>(null);
  const [total, setTotal]               = useState(0);
  const [page, setPage]                 = useState(1);
  const [pageSize, setPageSize]         = useState(20);
  const [loading, setLoading]           = useState(true);

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
  const [deleteTarget, setDeleteTarget] = useState<Asset | null>(null);
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
  const [columnsOpen, setColumnsOpen] = useState(false);
  const columnsMenuRef = React.useRef<HTMLDivElement>(null);
  const [visibleColumns, setVisibleColumns] = useState<Record<AssetColumnKey, boolean>>(() => {
    try {
      const stored = JSON.parse(localStorage.getItem(ASSET_COLUMNS_STORAGE_KEY) || '{}') as Partial<Record<AssetColumnKey, boolean>>;
      return normalizeAssetColumns(stored);
    } catch {
      return normalizeAssetColumns({});
    }
  });

  useEffect(() => {
    localStorage.setItem(ASSET_COLUMNS_STORAGE_KEY, JSON.stringify(visibleColumns));
  }, [visibleColumns]);

  useEffect(() => {
    if (!columnsOpen) return;
    const handleOutsideClick = (event: MouseEvent) => {
      if (columnsMenuRef.current && !columnsMenuRef.current.contains(event.target as Node)) {
        setColumnsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleOutsideClick);
    return () => document.removeEventListener('mousedown', handleOutsideClick);
  }, [columnsOpen]);

  const activeAssetColumns = useMemo(
    () => ASSET_COLUMN_DEFS.filter(column => visibleColumns[column.key]),
    [visibleColumns],
  );
  const allAssetColumnsSelected = activeAssetColumns.length === ASSET_COLUMN_DEFS.length;

  const fetchAllRacks = useCallback(async () => {
    try {
      const token = localStorage.getItem('netops_token');
      const res = await fetch('/api/racks', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      const data = await res.json();
      if (res.ok && data.success && Array.isArray(data.data)) {
        setAllRacks(data.data);
      }
    } catch (err) {
      console.error('Failed to load racks in AssetManagement:', err);
    }
  }, []);

  useEffect(() => {
    fetchAllRacks();
  }, [fetchAllRacks]);

  useEffect(() => {
    const token = localStorage.getItem('netops_token');
    fetch('/api/tags/definitions', { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(payload => setAllTags(Array.isArray(payload?.data) ? payload.data : []))
      .catch(() => setAllTags([]));
  }, []);

  useEffect(() => () => {
    if (rotationPollRef.current) clearInterval(rotationPollRef.current);
    if (batchTakeoverPollRef.current) clearInterval(batchTakeoverPollRef.current);
  }, []);

  const fetchSummary = useCallback(async () => {
    try { const r = await fetch('/api/assets/summary'); if (r.ok) setSummary(await r.json()); } catch { /* noop */ }
  }, []);

  const fetchSites = useCallback(async () => {
    try {
      const token = localStorage.getItem('netops_token');
      const response = await fetch('/api/cmdb/sites', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      const payload = await response.json();
      setSites(Array.isArray(payload?.data) ? payload.data : []);
    } catch {
      setSites([]);
    }
  }, []);

  const fetchAssets = useCallback(async () => {
    setLoading(true);
    try {
      const p = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
      if (search.trim()) p.set('q', search.trim());
      if (typeFilter !== 'all')   p.set('asset_type', typeFilter);
      if (statusFilter !== 'all') p.set('status', statusFilter);
      if (vendorFilter !== 'all') p.set('vendor', vendorFilter);
      if (dcFilter !== 'all')     p.set('site_id', dcFilter);
      if (deptFilter !== 'all')   p.set('department', deptFilter);
      if (deviceCategoryFilter)   p.set('device_category', deviceCategoryFilter);
      if (lifecycleFilter !== 'all') p.set('lifecycle_status', lifecycleFilter);
      if (tagFilter.length > 0)   p.set('tag_ids', tagFilter.join(','));
      const r = await fetch(`/api/assets?${p}`);
      if (r.ok) { const d = await r.json(); setAssets(d.items); setTotal(d.total); }
    } catch { /* noop */ }
    setLoading(false);
  }, [page, pageSize, search, typeFilter, statusFilter, vendorFilter, dcFilter, deptFilter, deviceCategoryFilter, tagFilter]);

  useEffect(() => { fetchSummary(); }, [fetchSummary]);
  useEffect(() => { fetchSites(); }, [fetchSites]);
  useEffect(() => { fetchAssets(); }, [fetchAssets]);
  useEffect(() => { setPage(1); }, [search, typeFilter, statusFilter, vendorFilter, dcFilter, deptFilter, deviceCategoryFilter, lifecycleFilter, tagFilter, pageSize]);

  useEffect(() => {
    if (!drawerAsset) return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setDrawerAsset(null); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [drawerAsset]);

  useEffect(() => {
    if (!feedbackMsg) return;
    if (rotatingAssetId) return;
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

  const criticalCount  = (summary?.by_status?.['inactive'] ?? 0);
  const majorCount     = (summary?.by_status?.['maintenance'] ?? 0);
  const warningCount   = summary?.warranty_expiring_soon ?? 0;
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
      platform: (a as any).platform || (a.asset_type === 'server' ? 'linux' : 'cisco_ios'),
      connection_method: (a as any).connection_method || 'ssh',
      username: (a as any).username || '',
      password: '',
      normal_username: (a as any).normal_username || '',
      normal_password: '',
      admin_username: (a as any).admin_username || '',
      admin_password: '',
      enable_password: '',
      auth_model: 'dual',
      snmp_community: (a as any).snmp_community || '',
      snmp_port: String((a as any).snmp_port || '161'),
      snmp_credential_id: (a as any).snmp_credential_id || '',
      snmp_community_set: Boolean((a as any).snmp_community_set),
      management_port: String(a.management_port ?? '22'),
      device_category: a.device_category || '',
      function: a.function || '',
      zone: a.zone || 'Unknown',
      power_watts: a.power_watts != null ? String(a.power_watts) : '',
      credential_id: (a as any).credential_id || '',
      admin_credential_id: (a as any).admin_credential_id || '',
      tag_ids: (a.tags || []).filter(tag => tag.category !== 'system_auto').map(tag => tag.id),
      web_profiles: (a.web_profiles || []).map(profile => ({ ...profile, port: String(profile.port) })),
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
        const r = await fetch(`/api/assets/${assetId}/rotation-status`);
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
    setSaving(true);
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
      let normalizedPlatform = form.platform;
      if (form.asset_type === 'server') {
        const serverValues = SERVER_PLATFORMS.map(p => p.value);
        if (!serverValues.includes(String(form.platform))) {
          normalizedPlatform = 'linux';
        }
      } else if (form.asset_type === 'network_device') {
        const vendorPlatforms = VENDOR_PLATFORMS[form.vendor] || [];
        if (vendorPlatforms.length > 0 && !vendorPlatforms.some(p => p.value === String(form.platform))) {
          normalizedPlatform = vendorPlatforms[0].value;
        }
      }
      const payload = {
        ...form,
        ...overrides,
        platform: normalizedPlatform,
        u_height: Math.max(1, Math.min(60, parseInt(String(form.u_height), 10) || 1)),
        planned_start_u,
        power_watts: parseInt(String(form.power_watts), 10) || 0,
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
      const r = await fetch(url, { method: editingAsset ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      if (r.ok) {
        const data = await r.json().catch(() => null);
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
      } else if (r.status === 422 || r.status === 400) {
        const err = await r.json().catch(() => null);
        setShowProductionConfirm(false);
        setModalError(zh ? (err?.detail || '保存校验失败') : (err?.detail || 'Validation failed'));
      } else {
        const err = await r.json().catch(() => null);
        setFeedbackMsg({ type: 'error', text: zh ? `保存失败: ${err?.detail || r.statusText}` : `Save failed: ${err?.detail || r.statusText}` });
      }
    } catch (e) { setFeedbackMsg({ type: 'error', text: zh ? `网络错误: ${e}` : `Network error: ${e}` }); }
    setSaving(false);
  };

  const handleSave = async () => {
    if (!form.hostname.trim() && !form.asset_tag.trim()) {
      setModalError(zh ? '主机名和资产编号至少填写一项' : 'Hostname or Asset Tag is required');
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
    try {
      const r = await fetch(`/api/assets/${deleteTarget.id}`, { method: 'DELETE' });
      if (r.ok) { setDeleteTarget(null); fetchAssets(); fetchSummary(); if (drawerAsset?.id === deleteTarget.id) setDrawerAsset(null); }
    } catch { /* noop */ }
  };

  const toggle    = (id: string) => setSelectedIds(p => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const toggleAll = () => setSelectedIds(p => p.size === displayAssets.length ? new Set() : new Set(displayAssets.map(a => a.id)));
  const clearSel  = () => setSelectedIds(new Set());

  const handleBatchDelete = async () => {
    if (selectedIds.size === 0) return;
    if (!confirm(zh ? '确定删除选中的资产吗？' : 'Delete selected assets?')) return;
    const promises = Array.from(selectedIds).map(id =>
      fetch(`/api/assets/${id}`, { method: 'DELETE' })
    );
    await Promise.allSettled(promises);
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
        headers: { 'Content-Type': 'application/json' },
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
                const response = await fetch(`/api/assets/${encodeURIComponent(item.id)}/rotation-status`);
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
        headers: { 'Content-Type': 'application/json' },
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

  const handleExport = async () => {
    const params = new URLSearchParams({ page: '1', page_size: '200' });
    if (search.trim()) params.set('q', search.trim());
    if (typeFilter !== 'all') params.set('asset_type', typeFilter);
    if (statusFilter !== 'all') params.set('status', statusFilter);
    if (vendorFilter !== 'all') params.set('vendor', vendorFilter);
    if (dcFilter !== 'all')     params.set('site_id', dcFilter);
    if (deptFilter !== 'all')   params.set('department', deptFilter);

    try {
      const allAssets = await fetchAllPaginatedItems<Asset>('/api/assets', params);
      if (!allAssets.length) return;
      const rows = allAssets.map(a => ({
        [zh ? '主机名' : 'Hostname']: a.hostname,
        [zh ? '资产编号' : 'Asset Tag']: a.asset_tag,
        [zh ? '序列号' : 'Serial Number']: a.serial_number,
        [zh ? '资产类型' : 'Asset Type']: a.asset_type,
        [zh ? '厂商' : 'Vendor']: a.vendor,
        [zh ? '型号' : 'Model']: a.model,
        [zh ? '平台' : 'Platform']: (a as any).platform || '',
        [zh ? '管理IP' : 'Mgmt IP']: a.management_ip,
        [zh ? '业务IP' : 'Business IP']: a.business_ip,
        [zh ? '状态' : 'Status']: a.status,
        [zh ? '角色' : 'Role']: a.device_role,
        [zh ? '设备分类' : 'Device Category']: (a as any).device_category || '',
        [zh ? '功能' : 'Function']: (a as any).function || '',
        [zh ? '区域' : 'Zone']: (a as any).zone || 'Unknown',
        [zh ? 'VLAN' : 'VLAN']: a.vlan,
        [zh ? '上联交换机' : 'Uplink Switch']: a.uplink_switch,
        [zh ? '上联端口' : 'Uplink Port']: a.uplink_port,
        [zh ? '站点' : 'Site']: a.site_name || a.site_code || a.site_id,
        [zh ? '机柜' : 'Rack']: a.rack,
        [zh ? 'U位' : 'Rack Unit']: a.rack_unit,
        [zh ? 'U高度' : 'U Height']: a.u_height ?? 1,
        [zh ? '规划起始U' : 'Planned Start U']: a.planned_start_u ?? '',
        [zh ? '功耗(W)' : 'Power(W)']: (a as any).power_watts ?? '',
        [zh ? 'SNMP社区名' : 'SNMP Community']: (a as any).snmp_community || '',
        [zh ? 'SNMP端口' : 'SNMP Port']: (a as any).snmp_port || '161',
        [zh ? '普通用户' : 'Normal User']: (a as any).normal_username || '',
        [zh ? '特权用户' : 'Admin User']: (a as any).admin_username || '',
        [zh ? '部门' : 'Department']: a.department,
        [zh ? '购买日期' : 'Purchase Date']: a.purchase_date,
        [zh ? '投产状态' : 'Lifecycle']: LIFECYCLE_STATUSES.find(l => l.value === a.lifecycle_status)?.label[zh ? 'zh' : 'en'] || '',
        [zh ? '保修到期' : 'Warranty Expiry']: a.warranty_expiry,
        [zh ? '备注' : 'Notes']: a.notes,
      }));
      const ws = XLSX.utils.json_to_sheet(rows);
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, zh ? '资产信息' : 'Asset Information');
      const methodRows = allAssets.flatMap(a => {
        const rowsForAsset: Record<string, unknown>[] = [];
        if (!['web', 'none'].includes(String(a.connection_method || '').toLowerCase())) {
          rowsForAsset.push({
            [zh ? '资产编号（手工填写）' : 'Asset Tag (manual)']: a.asset_tag,
            [zh ? '主机名（手工填写/核对）' : 'Hostname (manual/check)']: a.hostname,
            [zh ? '管理协议（每行一个）' : 'Management Protocol (one per row)']: String(a.connection_method || 'ssh').toUpperCase(),
            [zh ? '入口显示名称（仅展示）' : 'Entry Display Name (label only)']: zh ? '命令行管理' : 'CLI management',
            [zh ? '端口（可留空自动默认）' : 'Port (blank = default)']: a.management_port || (a.connection_method === 'netconf' ? 830 : 22),
            [zh ? '登录路径（Web填写，如 /login）' : 'Login Path (Web only)']: '',
            [zh ? '是否启用' : 'Enabled']: zh ? '是' : 'yes',
            [zh ? '凭据模式（默认继承资产）' : 'Credential Mode (default: inherit asset)']: zh ? '继承资产凭据' : 'inherit_asset',
            [zh ? '普通用户（可选）' : 'Normal User (optional)']: a.normal_username || '',
            [zh ? '特权用户（可选）' : 'Admin User (optional)']: a.admin_username || '',
          });
        } else if (String(a.connection_method || '').toLowerCase() === 'none') {
          rowsForAsset.push({
            [zh ? '资产编号（手工填写）' : 'Asset Tag (manual)']: a.asset_tag,
            [zh ? '主机名（手工填写/核对）' : 'Hostname (manual/check)']: a.hostname,
            [zh ? '管理协议（每行一个）' : 'Management Protocol (one per row)']: 'NONE',
            [zh ? '入口显示名称（仅展示）' : 'Entry Display Name (label only)']: zh ? '无登录入口' : 'No login entry',
            [zh ? '端口（可留空自动默认）' : 'Port (blank = default)']: '',
            [zh ? '登录路径（Web填写，如 /login）' : 'Login Path (Web only)']: '',
            [zh ? '是否启用' : 'Enabled']: zh ? '是' : 'yes',
            [zh ? '凭据模式（默认继承资产）' : 'Credential Mode (default: inherit asset)']: zh ? '继承资产凭据' : 'inherit_asset',
          });
        }
        (a.web_profiles || []).forEach(profile => rowsForAsset.push({
          [zh ? '资产编号（手工填写）' : 'Asset Tag (manual)']: a.asset_tag,
          [zh ? '主机名（手工填写/核对）' : 'Hostname (manual/check)']: a.hostname,
          [zh ? '管理协议（每行一个）' : 'Management Protocol (one per row)']: profile.scheme.toUpperCase(),
          [zh ? '入口显示名称（仅展示）' : 'Entry Display Name (label only)']: profile.profile_name,
          [zh ? '端口（可留空自动默认）' : 'Port (blank = default)']: profile.port,
          [zh ? '登录路径（Web填写，如 /login）' : 'Login Path (Web only)']: profile.path,
          [zh ? '是否启用' : 'Enabled']: profile.enabled ? (zh ? '是' : 'yes') : (zh ? '否' : 'no'),
          [zh ? '凭据模式（默认继承资产）' : 'Credential Mode (default: inherit asset)']: profile.credential_mode === 'independent' ? (zh ? '独立凭据' : 'independent') : (zh ? '继承资产凭据' : 'inherit_asset'),
          [zh ? '普通用户（可选）' : 'Normal User (optional)']: profile.normal_username || '',
          [zh ? '特权用户（可选）' : 'Admin User (optional)']: profile.admin_username || '',
          [zh ? '绑定凭据（推荐）' : 'Credential ID (recommended)']: profile.credential_id || '',
          [zh ? '绑定特权凭据（推荐）' : 'Admin Credential ID (recommended)']: profile.admin_credential_id || '',
        }));
        return rowsForAsset;
      });
      if (methodRows.length) {
        XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(methodRows), zh ? '管理入口' : 'Management Entries');
      }
      const ts = new Date().toISOString().replace(/[-:]/g, '').replace('T', '_').slice(0, 15);
      XLSX.writeFile(wb, `assets_${ts}.xlsx`);
    } catch {
      setFeedbackMsg({ type: 'error', text: zh ? '导出失败' : 'Export failed' });
    }
  };

  const doImport = async (payload: any[]) => {
    // Keep failures visible above the validation dialog and page content.
    setShowValidationModal(false);
    try {
      const r = await fetch('/api/assets/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
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
            return zh
              ? `${identity}：${fields || '主机名/资产编号/序列号/管理IP'}已存在${existing}`
              : `${identity}: ${fields || 'hostname/asset tag/serial number/management IP'} already exists${item.existing_hostname ? ` (existing device: ${item.existing_hostname})` : ''}`;
          }
          return zh ? `${identity}：导入规则跳过` : `${identity}: skipped by import rule`;
        });
        if (res.skipped > skippedDetails.length) {
          skippedDetails.push(zh
            ? `另有 ${res.skipped - skippedDetails.length} 条跳过记录未展开`
            : `${res.skipped - skippedDetails.length} more skipped rows are not shown`);
        }
        const hasSkipped = Number(res.skipped || 0) > 0;
        setFeedbackMsg({
          type: hasSkipped ? 'warning' : 'success',
          text: zh ? `导入完成：新增 ${res.created} 条，跳过 ${res.skipped} 条${hasSkipped ? '（请查看跳过原因）' : ''}` : `Import done: ${res.created} created, ${res.skipped} skipped${hasSkipped ? ' (review skipped rows)' : ''}`,
          details: skippedDetails.length > 0 ? skippedDetails : undefined,
        });
        fetchAssets();
        fetchSummary();
        fetchAllRacks();
      } else {
        const error = await r.json().catch(() => null);
        setFeedbackMsg({ type: 'error', text: error?.detail || (zh ? '导入失败' : 'Import failed') });
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
        const NET_SHEET = /网络设备|network.?device/i;
        const mapped: Record<string, string>[] = [];
        const managementMethods: ManagementMethodImportRow[] = [];
        const managementMethodErrors: string[] = [];
        const templateMismatchRows: string[] = [];
        let hasUnifiedAssetSheet = false;
        for (const name of wb.SheetNames) {
          const ws = wb.Sheets[name];
          if (MANAGEMENT_ENTRY_SHEET_RE.test(name.trim())) {
            const parsed = parseManagementMethodSheet(ws);
            managementMethods.push(...parsed.rows);
            managementMethodErrors.push(...parsed.errors);
            continue;
          }
          const raw = XLSX.utils.sheet_to_json<Record<string, string>>(ws, { defval: '' });
          const isNet = NET_SHEET.test(name);
          const isUnifiedAssetSheet = ASSET_INFO_SHEET_RE.test(name.trim());
          if (isUnifiedAssetSheet) hasUnifiedAssetSheet = true;
          for (const [rowIndex, row] of raw.entries()) {
            const obj: Record<string, string> = {};
            for (const [col, val] of Object.entries(row)) {
              const key = COL_MAP[col.trim()];
              if (key) {
                let mappedVal = String(val).trim();
                const valueMap = IMPORT_VALUE_MAP[key];
                if (valueMap) {
                  mappedVal = valueMap[mappedVal] || valueMap[mappedVal.toLowerCase()] || mappedVal;
                }
                if (key === 'asset_type') {
                  const v = mappedVal.toLowerCase();
                  if (v.includes('server') || v.includes('服务器')) mappedVal = 'server';
                  else if (v.includes('network') || v.includes('网络') || v.includes('switch') || v.includes('router')) mappedVal = 'network_device';
                } else if (key === 'purchase_date' || key === 'warranty_expiry') {
                  mappedVal = formatExcelDate(val);
                }
                obj[key] = mappedVal;
              }
            }
            if (obj.hostname || obj.asset_tag) {
              if (!obj.asset_type) {
                if (isUnifiedAssetSheet) {
                  templateMismatchRows.push(`${name} 第${rowIndex + 2}行：资产类型必填，请选择“服务器”或“网络设备”`);
                  continue;
                }
                obj.asset_type = isNet ? 'network_device' : 'server';
              }
              const rowIsNet = obj.asset_type === 'network_device';
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
              mapped.push(obj);
            }
          }
        }
        if (templateMismatchRows.length > 0) {
          setFeedbackMsg({
            type: 'error',
            text: `${zh ? '模板角色/设备分类不匹配，请检查：' : 'Template role/category mismatch:'} ${templateMismatchRows.slice(0, 3).join('；')}`,
          });
          return;
        }
        const merged = mergeManagementMethods(mapped, managementMethods, {
          requireEntryForAllAssets: hasUnifiedAssetSheet,
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
    // The distributable template contains native Excel list validation rules.
    // Keep the generated fallback below for development/older deployments.
    try {
      const templateResponse = await fetch('/templates/asset_import_template.xlsx', { cache: 'no-store' });
      if (templateResponse.ok) {
        const blob = await templateResponse.blob();
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = zh ? '资产导入模板.xlsx' : 'asset_import_template.xlsx';
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(url);
        return;
      }
    } catch {
      // Fall through to the in-browser legacy generator.
    }

    const wb = XLSX.utils.book_new();

    const guideRows = zh ? [
      ['资产导入填写说明'],
      ['字段', '是否必填', '填写规则'],
      ['资产信息', '每台资产一行', '服务器和网络设备统一填写；不要因存在多个管理入口而重复资产行'],
      ['资产类型', '必填', '填写“服务器”或“网络设备”'],
      ['管理入口', '每个协议一行', 'A、B列都从“资产信息”手工复制；支持 SSH、NETCONF、HTTP、HTTPS；同一设备同时支持 HTTP+HTTPS 时填写两行；没有登录入口时填写 NONE'],
      ['入口协议与路径', '按协议填写', 'SSH/NETCONF 不填路径；HTTP/HTTPS 填 Web 路径，如 /login。端口可留空，系统默认 SSH 22、NETCONF 830、HTTP 80、HTTPS 443'],
      ['管理入口凭据', '可选', '默认继承资产信息中的凭据；账号不同时选择“独立凭据”。优先填写绑定凭据，不建议在表格中填写密码'],
      ['录入来源', '必填', '填写“新设备”或“存量设备”'],
      ['投产状态', '必填', '新设备填写“待投产”；存量设备可填写“待投产”或“已投产”'],
      ['主机名/资产编号', 'A、B列手工填写', '从“资产信息”复制资产编号和主机名；A、B两列都是人工核对信息，不使用自动填充'],
      ['普通用户/普通密码', '条件必填', '存量设备直接填写“已投产”时必须填写（若绑定已存凭据则可选填）'],
      ['特权用户/特权密码', '标准投产必填', '标准口令上收和改密使用'],
      ['免上收投产原因', '条件必填', '录入来源为“存量设备”且投产状态为“已投产”时至少填写 5 个字符'],
      ['绑定凭据', '可选', '普通/登录凭据名称或 ID，如：cred-cisco-core'],
      ['绑定特权凭据', '可选', '特权/管理员凭据名称或 ID，如：cred-cisco-admin'],
      ['标签代码', '可选', '多个标签代码用英文逗号分隔，例如：vendor.cisco,platform.cisco_ios'],
      ['拓扑角色', '网络设备必填', '使用统一下拉值；核心/汇聚/接入用于拓扑视觉分层，链路关系证据仍保留用于关系语义。'],
      ['功能/区域', '推荐填写', '使用统一下拉值，便于拓扑筛选与语义展示。'],
    ] : [
      ['Asset Import Instructions'],
      ['Field', 'Required', 'Rule'],
      ['Asset Information', 'One row per asset', 'Servers and network devices share one sheet; do not duplicate assets for multiple management entries'],
      ['Asset Type', 'Yes', 'Use server or network_device'],
      ['Management Entries', 'One row per protocol', 'Copy Asset Tag and Hostname manually from Asset Information. Supports SSH, NETCONF, HTTP and HTTPS. Use two rows for HTTP + HTTPS, or NONE when there is no login entry'],
      ['Protocol / Path', 'By protocol', 'Leave path blank for SSH/NETCONF; fill a Web path such as /login for HTTP/HTTPS. Blank port uses protocol defaults: 22/830/80/443'],
      ['Entry Credentials', 'Optional', 'Entries inherit asset credentials by default; choose independent credentials only when the account differs. Prefer credential IDs and avoid passwords in the sheet'],
      ['Role', 'Optional', 'Use the canonical device role value; both Role and role headers are accepted on import'],
      ['Asset Origin', 'Yes', 'Use new (new device) or legacy (existing device)'],
      ['Lifecycle', 'Yes', 'Use staging for new devices; legacy devices may use staging or production'],
      ['Hostname / Asset Tag', 'Manual entry', 'Copy both values from Asset Information; both columns are manual association/check fields'],
      ['Normal User / Password', 'Conditional', 'Required for legacy devices imported as production (optional if credential is bound)'],
      ['Admin User / Password', 'Standard production', 'Required for managed password takeover'],
      ['Takeover Exemption Reason', 'Conditional', 'Minimum 5 characters for legacy + production'],
      ['Credential', 'Optional', 'Existing normal credential name or ID from the vault, e.g. cred-cisco-core'],
      ['Admin Credential', 'Optional', 'Existing admin credential name or ID from the vault, e.g. cred-cisco-admin'],
      ['Tags', 'Optional', 'Comma-separated stable tag codes, e.g. vendor.cisco,platform.cisco_ios'],
      ['Topology Role', 'Network devices', 'Use the unified list; Core/Distribution/Access drive the visual tiers while relationship evidence remains semantic.'],
      ['Function / Zone', 'Recommended', 'Use the unified lists for topology filtering and semantics.'],
    ];
    const wsGuide = XLSX.utils.aoa_to_sheet(guideRows);
    wsGuide['!cols'] = [{ wch: 28 }, { wch: 18 }, { wch: 72 }];
    XLSX.utils.book_append_sheet(wb, wsGuide, zh ? '填写说明' : 'Instructions');

    const assetHeaders = zh
      ? ['资产类型', '主机名', '资产编号', '序列号', '厂商', '型号', '平台', '管理IP', '业务IP', '状态', '角色', '设备分类', '录入来源（必填：新设备或存量设备）', 'VLAN', '上联交换机', '上联端口', '站点', '机柜', 'U位', 'U高度', '规划起始U', '功耗(W)', 'SNMP社区名', 'SNMP端口', '普通用户', '特权用户', '普通密码', '特权密码', 'Enable密码', '绑定凭据', '绑定特权凭据', '标签代码', '部门', '购买日期', '投产状态', '免上收投产原因', '保修到期', '备注', '功能', '区域']
      : ['Asset Type', 'Hostname', 'Asset Tag', 'Serial Number', 'Vendor', 'Model', 'Platform', 'Mgmt IP', 'Business IP', 'Status', 'Role', 'Device Category', 'Asset Origin (Required: new or legacy)', 'VLAN', 'Uplink Switch', 'Uplink Port', 'Site', 'Rack', 'Rack Unit', 'U Height', 'Planned Start U', 'Power(W)', 'SNMP Community', 'SNMP Port', 'Normal User', 'Admin User', 'Normal Password', 'Admin Password', 'Enable Secret', 'Credential', 'Admin Credential', 'Tags', 'Department', 'Purchase Date', 'Lifecycle', 'Takeover Exemption Reason', 'Warranty Expiry', 'Notes', 'Function', 'Zone'];
    const assetExamples = zh ? [
      ['网络设备', 'core-sw-01', 'NET-BJ-001', 'FCW2345L0AB', '思科', 'C9300-48P', '思科 IOS', '10.0.0.1', '', '在用', '核心层', '交换机', '存量设备', '', '', '', 'BJ-DC1', 'A-02', '40', '1', '40', '', 'public', '161', 'user', 'admin', '', '', '', 'cred-cisco-core', 'cred-cisco-admin', 'vendor.cisco,platform.cisco_ios', 'IT部', '2023-06-01', '已投产', '存量设备已在线运行', '2027-06-01', 'A：只支持 SSH', '园区核心', '生产区'],
      ['网络设备', 'web-fw-01', 'NET-BJ-002', 'HS20260813A1', '山石', 'Hillstone E-Series', 'Hillstone StoneOS', '10.0.0.2', '', '在用', '防火墙', '防火墙', '新设备', '', '', '', 'BJ-DC1', 'A-02', '38', '2', '38', '', 'public', '161', '', '', '', '', '', '', '', 'vendor.hillstone', 'IT部', '2026-08-13', '待投产', '', '2029-08-13', 'B：同时支持 HTTP 和 HTTPS', '互联网边界', 'DMZ 区'],
      ['服务器', 'web-srv-01', 'SRV-BJ-001', 'CZJ2345G0HN', '戴尔', 'PowerEdge R750', 'Linux（通用）', '10.0.1.10', '192.168.1.10', '在用', '业务服务器', '机架式服务器', '新设备', 'VLAN100', 'core-sw-01', 'Gi0/1', 'BJ-DC1', 'A-01', '12', '1', '12', '200', '', '', 'ops', 'root', '', '', '', 'cred-server-ops', '', 'platform.linux', 'IT部', '2026-08-13', '待投产', '', '2029-08-13', 'C：SSH + HTTPS（管理入口需两行）', '服务器接入', '生产区'],
    ] : [
      ['network_device', 'core-sw-01', 'NET-BJ-001', 'FCW2345L0AB', 'Cisco', 'C9300-48P', 'cisco_ios', '10.0.0.1', '', 'active', 'core', 'switch', 'legacy', '', '', '', 'BJ-DC1', 'A-02', '40', '1', '40', '', 'public', '161', 'user', 'admin', '', '', '', 'cred-cisco-core', 'cred-cisco-admin', 'vendor.cisco,platform.cisco_ios', 'IT Dept', '2023-06-01', 'production', 'Existing production device', '2027-06-01', 'A: SSH only', 'Campus Core', 'Production'],
      ['network_device', 'web-fw-01', 'NET-BJ-002', 'HS20260813A1', 'Hillstone', 'Hillstone E-Series', 'hillstone_stoneos', '10.0.0.2', '', 'active', 'firewall', 'firewall', 'new', '', '', '', 'BJ-DC1', 'A-02', '38', '2', '38', '', 'public', '161', '', '', '', '', '', '', '', 'vendor.hillstone', 'IT Dept', '2026-08-13', 'staging', '', '2029-08-13', 'B: HTTP + HTTPS', 'Internet Edge', 'DMZ'],
      ['server', 'web-srv-01', 'SRV-BJ-001', 'CZJ2345G0HN', 'Dell', 'PowerEdge R750', 'linux', '10.0.1.10', '192.168.1.10', 'active', 'application_server', 'rack_server', 'new', 'VLAN100', 'core-sw-01', 'Gi0/1', 'BJ-DC1', 'A-01', '12', '1', '12', '200', '', '', 'ops', 'root', '', '', '', 'cred-server-ops', '', 'platform.linux', 'IT Dept', '2026-08-13', 'staging', '', '2029-08-13', 'C: SSH + HTTPS (two entry rows)', 'Server Access', 'Production'],
    ];
    const wsAssets = XLSX.utils.aoa_to_sheet([assetHeaders, ...assetExamples]);
    wsAssets['!cols'] = assetHeaders.map((_, index) => ({ wch: index === 0 || index === 2 ? 18 : 16 }));
    XLSX.utils.book_append_sheet(wb, wsAssets, zh ? '资产信息' : 'Asset Information');

    const methodHeaders = zh
      ? ['资产编号（手工填写）', '主机名（手工填写/核对）', '管理协议（每行一个）', '入口显示名称（仅展示）', '端口（可留空自动默认）', '登录路径（Web填写，如 /login）', '是否启用', '凭据模式（默认继承资产）', '普通用户（可选）', '普通密码（不建议填写）', '特权用户（可选）', '特权密码（不建议填写）', '绑定凭据（推荐）', '绑定特权凭据（推荐）', '备注（填写场景）']
      : ['Asset Tag (manual)', 'Hostname (manual/check)', 'Management Protocol (one per row)', 'Entry Display Name (label only)', 'Port (blank = default)', 'Login Path (Web only)', 'Enabled', 'Credential Mode (default: inherit asset)', 'Normal User (optional)', 'Normal Password (avoid)', 'Admin User (optional)', 'Admin Password (avoid)', 'Credential ID (recommended)', 'Admin Credential ID (recommended)', 'Notes (scenario)'];
    const methodExamples = zh ? [
      ['NET-BJ-001', 'core-sw-01', 'SSH', '命令行管理', 22, '', '是', '继承资产凭据', '', '', '', '', '', '', 'A：只支持 SSH；一行一个协议'],
      ['NET-BJ-002', 'web-fw-01', 'HTTP', 'HTTP管理', 80, '/', '是', '独立凭据', 'web-user', '', 'web-admin', '', '', '', 'B：HTTP + HTTPS 需要两行'],
      ['NET-BJ-002', 'web-fw-01', 'HTTPS', 'HTTPS管理', 443, '/login', '是', '独立凭据', 'web-user', '', 'web-admin', '', '', '', 'B：HTTP + HTTPS 需要两行'],
      ['SRV-BJ-001', 'web-srv-01', 'SSH', '命令行管理', 22, '', '是', '继承资产凭据', '', '', '', '', '', '', 'C：SSH 主通道；HTTPS 另加一行'],
      ['SRV-BJ-001', 'web-srv-01', 'HTTPS', 'HTTPS管理', 443, '/login', '是', '继承资产凭据', '', '', '', '', '', '', 'C：SSH + HTTPS'],
    ] : [
      ['NET-BJ-001', 'core-sw-01', 'SSH', 'CLI management', 22, '', 'yes', 'inherit_asset', '', '', '', '', '', '', 'A: SSH only; one protocol per row'],
      ['NET-BJ-002', 'web-fw-01', 'HTTP', 'HTTP management', 80, '/', 'yes', 'independent', 'web-user', '', 'web-admin', '', '', '', 'B: HTTP + HTTPS uses two rows'],
      ['NET-BJ-002', 'web-fw-01', 'HTTPS', 'HTTPS management', 443, '/login', 'yes', 'independent', 'web-user', '', 'web-admin', '', '', '', 'B: HTTP + HTTPS uses two rows'],
      ['SRV-BJ-001', 'web-srv-01', 'SSH', 'CLI management', 22, '', 'yes', 'inherit_asset', '', '', '', '', '', '', 'C: SSH channel; add HTTPS row'],
      ['SRV-BJ-001', 'web-srv-01', 'HTTPS', 'HTTPS management', 443, '/login', 'yes', 'inherit_asset', '', '', '', '', '', '', 'C: SSH + HTTPS'],
    ];
    const wsMethods = XLSX.utils.aoa_to_sheet([methodHeaders, ...methodExamples]);
    wsMethods['!cols'] = [18, 20, 14, 16, 14, 18, 10, 18, 14, 16, 14, 16, 18, 20, 24].map(wch => ({ wch }));
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

    const wsOpt = XLSX.utils.aoa_to_sheet([optHeaders, ...optRows]);
    wsOpt['!cols'] = optHeaders.map(() => ({ wch: 25 }));
    XLSX.utils.book_append_sheet(wb, wsOpt, zh ? '参数可选值参考' : 'Option Reference');

    XLSX.writeFile(wb, zh ? '资产导入模板.xlsx' : 'asset_import_template.xlsx');
  };

  const typeDisplay = (a: Asset) => typeMeta(a.asset_type).label[zh ? 'zh' : 'en'];

  const categoryDisplay = (a: Asset) => {
    const labels: Record<string, { zh: string; en: string }> = {
      rack_server: { zh: '机架式服务器', en: 'Rack Server' },
      blade_server: { zh: '刀片服务器', en: 'Blade Server' },
      tower_server: { zh: '塔式服务器', en: 'Tower Server' },
      high_density: { zh: '高密度服务器', en: 'High-Density Server' },
      gpu_server: { zh: 'GPU 服务器', en: 'GPU Server' },
      storage_server: { zh: '存储服务器', en: 'Storage Server' },
      virtual_host: { zh: '虚拟/物理宿主机', en: 'Virtual Host' },
      switch: { zh: '交换机', en: 'Switch' },
      router: { zh: '路由器', en: 'Router' },
      firewall: { zh: '防火墙', en: 'Firewall' },
      load_balancer: { zh: '负载均衡', en: 'Load Balancer' },
      wireless_ap: { zh: '无线 AP', en: 'Wireless AP' },
      other: { zh: '其他', en: 'Other' },
    };
    return labels[a.device_category || '']?.[zh ? 'zh' : 'en'] || a.device_category || '—';
  };

  const hasFilters = typeFilter !== 'all' || statusFilter !== 'all' || vendorFilter !== 'all' || dcFilter !== 'all' || deptFilter !== 'all' || lifecycleFilter !== 'all' || deviceCategoryFilter !== '' || tagFilter.length > 0;
  const advancedFilterCount = [vendorFilter, dcFilter, deptFilter, lifecycleFilter].filter(f => f !== 'all').length + (tagFilter.length > 0 ? 1 : 0);
  const clearAllFilters = () => { setTypeFilter('all'); setStatusFilter('all'); setVendorFilter('all'); setDcFilter('all'); setDeptFilter('all'); setSeverityFilter('all'); setLifecycleFilter('all'); setDeviceCategoryFilter(''); setTagFilter([]); };

  const renderAssetCell = (column: AssetColumnKey, a: Asset): React.ReactNode => {
    const onlineStatus = a.online_status || (a.status === 'active' ? 'online' : a.status === 'inactive' ? 'offline' : 'pending');
    const onlineMeta = onlineStatus === 'online'
      ? { label: zh ? '在线' : 'Online', text: 'text-emerald-600', dot: 'bg-emerald-500' }
      : onlineStatus === 'offline'
        ? { label: zh ? '离线' : 'Offline', text: 'text-red-500', dot: 'bg-red-500' }
        : { label: zh ? '待确认' : 'Pending', text: 'text-amber-600', dot: 'bg-amber-400' };
    switch (column) {
      case 'hostname': return <><p className="font-semibold text-[12px] text-black/80 leading-tight truncate max-w-[180px]">{a.hostname || '—'}</p><p className="text-[10px] text-black/20 font-mono truncate">{a.asset_tag || a.management_ip || a.serial_number || ''}</p></>;
      case 'category_role': return <><span className="inline-flex items-center gap-1 text-[11px] text-cyan-600">{a.asset_type === 'server' ? <Server size={10} /> : <Router size={10} />}{typeDisplay(a)}</span><span className="block text-[10px] text-black/35 truncate max-w-[120px]">{categoryDisplay(a)}{a.device_role ? ` / ${a.device_role}` : ''}</span></>;
      case 'site': return <span className="text-[11px] text-black/45 truncate max-w-[100px] block">{a.site_name || a.site_code || a.site_id || '—'}{a.rack && <span className="text-black/25 block text-[10px]">{a.rack}{a.rack_unit ? `U${a.rack_unit}` : ''}</span>}</span>;
      case 'status': return <span className={`inline-flex items-center gap-1 text-[11px] font-medium ${onlineMeta.text}`}><span className={`h-1.5 w-1.5 rounded-full ${onlineMeta.dot}`} />{onlineMeta.label}</span>;
      case 'tags': return a.tags?.length ? <div className="flex flex-wrap items-center gap-1 max-w-[180px]">{a.tags.slice(0, 3).map(tag => <span key={tag.id} className="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[9px] font-medium whitespace-nowrap" style={{ color: tag.color || '#0891b2', backgroundColor: `${tag.color || '#0891b2'}12` }}><span className="h-1 w-1 rounded-full" style={{ backgroundColor: tag.color || '#0891b2' }} />{zh ? (tag.label_zh || tag.label) : tag.label}</span>)}{a.tags.length > 3 && <span className="text-[9px] text-black/25">+{a.tags.length - 3}</span>}</div> : <span className="text-black/15">—</span>;
      case 'vendor': return <span className="text-[11px] text-black/55">{a.vendor || '—'}</span>;
      case 'model': return <span className="text-[11px] text-black/45">{a.model || '—'}</span>;
      case 'serial_number': return <span className="font-mono text-[11px] text-black/50">{a.serial_number || '—'}</span>;
      case 'management_ip': return <span className="font-mono text-[11px] text-black/50">{a.management_ip || '—'}</span>;
      case 'lifecycle': return rotatingAssetId === a.id ? <span className="inline-flex items-center gap-1 text-[11px] font-medium text-cyan-600"><Loader2 size={10} className="animate-spin" />{zh ? '上收中' : 'Rotating'}</span> : <span className={`inline-flex items-center gap-1 text-[11px] font-medium ${a.lifecycle_status === 'production' ? 'text-emerald-600' : a.lifecycle_status === 'decommissioned' ? 'text-slate-400' : a.lifecycle_status === 'maintenance' ? 'text-amber-600' : 'text-blue-500'}`}><span className={`h-1.5 w-1.5 rounded-full ${a.lifecycle_status === 'production' ? 'bg-emerald-500' : a.lifecycle_status === 'decommissioned' ? 'bg-slate-400' : a.lifecycle_status === 'maintenance' ? 'bg-amber-500' : 'bg-blue-400'}`} />{LIFECYCLE_STATUSES.find(l => l.value === a.lifecycle_status)?.label[zh ? 'zh' : 'en'] || (zh ? '待投产' : 'Staging')}</span>;
      case 'created_at': return <span className="text-[11px] text-black/45 tabular-nums">{a.created_at?.replace('T', ' ').slice(0, 19) || '—'}</span>;
      case 'updated_at': return <span className="text-[11px] text-black/45 tabular-nums">{a.updated_at?.replace('T', ' ').slice(0, 19) || '—'}</span>;
    }
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHero
        icon={Package}
        title={zh ? '资产管理' : 'Asset Management'}
        subtitle={zh ? '设备台账 · 资产生命周期 · 租户归属' : 'Device inventory, lifecycle and tenant ownership'}
      />

      <div className="flex-1 overflow-auto px-6 py-5 space-y-2.5">
        <input ref={fileInputRef} type="file" accept=".xlsx,.xls,.csv" className="hidden" onChange={handleImport} />

        <AnimatePresence>
          {feedbackMsg && (
            <motion.div
              role="alert"
              initial={{ opacity: 0, y: -12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -12 }}
              transition={{ duration: 0.25 }}
              className={`fixed right-6 top-20 z-[220] flex w-[min(560px,calc(100vw-2rem))] items-start gap-3 px-4 py-3 rounded-xl border shadow-2xl backdrop-blur-sm ${
                feedbackMsg.type === 'success' ? 'bg-emerald-50/90 border-emerald-200 text-emerald-800' :
                feedbackMsg.type === 'warning' ? 'bg-amber-50/90 border-amber-200 text-amber-800' :
                feedbackMsg.type === 'info' ? 'bg-cyan-50/90 border-cyan-200 text-cyan-800' :
                'bg-red-50/90 border-red-200 text-red-800'
              }`}
            >
              {feedbackMsg.type === 'success' ? <CheckCircle2 size={18} className="text-emerald-500 shrink-0" /> :
               feedbackMsg.type === 'warning' ? <AlertTriangle size={18} className="text-amber-500 shrink-0" /> :
               feedbackMsg.type === 'info' ? (rotatingAssetId ? <Loader2 size={18} className="text-cyan-500 shrink-0 animate-spin" /> : <Info size={18} className="text-cyan-500 shrink-0" />) :
               <AlertCircle size={18} className="text-red-500 shrink-0" />}
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium">{feedbackMsg.text}</div>
                {feedbackMsg.details?.length ? (
                  <ul className="mt-1 space-y-0.5 text-[11px] font-normal leading-4 opacity-90">
                    {feedbackMsg.details.map((detail, index) => <li key={`${detail}-${index}`}>{detail}</li>)}
                  </ul>
                ) : null}
              </div>
              <button onClick={() => setFeedbackMsg(null)} className="p-0.5 rounded-md hover:bg-black/5 transition-colors">
                <X size={14} />
              </button>
            </motion.div>
          )}
        </AnimatePresence>

        {batchTakeoverResults.length > 0 && (
          <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 bg-slate-50/80 px-4 py-2.5">
              <div>
                <div className="text-xs font-bold text-slate-700">{zh ? '批量口令上收结果' : 'Batch takeover results'}</div>
                <div className="mt-0.5 text-[10px] text-slate-400">{zh ? '绑定凭据的设备已在任务创建前拦截，不会修改设备口令。' : 'Credential-bound devices are blocked before task creation and will not be modified.'}</div>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-[10px] font-medium">
                {[
                  { key: 'running', label: zh ? '处理中' : 'Running', cls: 'text-cyan-600' },
                  { key: 'completed', label: zh ? '成功' : 'Completed', cls: 'text-emerald-600' },
                  { key: 'failed', label: zh ? '失败' : 'Failed', cls: 'text-red-600' },
                  { key: 'blocked_credential', label: zh ? '已拦截' : 'Blocked', cls: 'text-amber-600' },
                ].map(item => {
                  const count = batchTakeoverResults.filter(result => result.status === item.key).length;
                  return <span key={item.key} className={item.cls}>{item.label} {count}</span>;
                })}
              </div>
            </div>
            <div className="max-h-56 overflow-auto divide-y divide-slate-100">
              {batchTakeoverDisplayResults.map(result => {
                const statusMeta = result.status === 'completed'
                  ? { label: zh ? '成功' : 'Completed', cls: 'bg-emerald-50 text-emerald-700', Icon: CheckCircle2 }
                  : result.status === 'failed' || result.status === 'error' || result.status === 'timeout'
                    ? { label: result.status === 'timeout' ? (zh ? '超时' : 'Timeout') : (zh ? '失败' : 'Failed'), cls: 'bg-red-50 text-red-700', Icon: AlertCircle }
                    : result.status === 'blocked_credential'
                      ? { label: zh ? '绑定凭据，未执行' : 'Blocked', cls: 'bg-amber-50 text-amber-700', Icon: Lock }
                      : { label: zh ? '处理中' : 'Running', cls: 'bg-cyan-50 text-cyan-700', Icon: Loader2 };
                const StatusIcon = statusMeta.Icon;
                return (
                  <div key={result.id} className="flex flex-wrap items-center gap-3 px-4 py-2.5 text-[10px]">
                    <div className="min-w-[170px] flex-1">
                      <div className="font-semibold text-slate-700">{result.status === 'blocked_credential' ? (zh ? `${result.device_count || 1} 台设备` : `${result.device_count || 1} devices`) : (result.hostname || result.id)}</div>
                      <div className="font-mono text-slate-400">{result.status === 'blocked_credential' ? (result.device_names || []).slice(0, 3).join('、') + ((result.device_count || 0) > 3 ? ` +${(result.device_count || 0) - 3}` : '') : (result.management_ip || '—')}</div>
                    </div>
                    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-1 font-semibold ${statusMeta.cls}`}>
                      <StatusIcon size={11} className={result.status === 'running' ? 'animate-spin' : ''} />
                      {statusMeta.label}
                    </span>
                    <div className="min-w-[260px] flex-[2] text-slate-500">
                      {result.status === 'blocked_credential' && result.credential_name ? <span className="font-medium text-amber-700">{zh ? '关联凭据：' : 'Credential: '}{result.credential_name} · </span> : null}
                      {result.message || '—'}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
          {([
            { key: 'critical', value: criticalCount, label: zh ? '严重故障' : 'Critical', sub: 'P1', Icon: Flame, gradient: 'from-red-600 to-red-700', filterVal: 'critical', pulse: true },
            { key: 'major', value: majorCount, label: zh ? '重要问题' : 'Major Issues', sub: 'P2', Icon: AlertTriangle, gradient: 'from-orange-600 to-orange-700', filterVal: 'major' },
            { key: 'warning', value: warningCount, label: zh ? '需要关注' : 'Warning', sub: 'P3', Icon: AlertCircle, gradient: 'from-amber-600 to-amber-700', filterVal: 'warning' },
            { key: 'healthy', value: healthyCount, label: zh ? '运行正常' : 'Healthy', sub: zh ? '正常' : 'OK', Icon: CheckCircle2, gradient: 'from-emerald-600 to-emerald-700', filterVal: 'healthy' },
          ]).map(c => {
            const isActive = severityFilter === c.filterVal;
            const isEmpty = c.value === 0;
            return (
              <button
                key={c.key}
                onClick={() => setSeverityFilter(isActive ? 'all' : c.filterVal)}
                className={`group relative rounded-xl overflow-hidden transition-all hover:shadow-md hover:scale-[1.01] active:scale-[0.99] bg-gradient-to-br ${c.gradient} ${isEmpty ? 'opacity-60' : ''} ${isActive ? 'ring-2 ring-white/30 shadow-lg' : 'shadow-sm'}`}
              >
                <div className="px-3 py-2.5 flex items-center justify-between relative z-10">
                  <div className="text-left">
                    <div className="flex items-center gap-1.5 mb-0.5">
                      <span className="text-[9px] font-bold uppercase tracking-widest text-white/50">{c.sub}</span>
                      <span className="text-[10px] font-medium text-white/60">{c.label}</span>
                    </div>
                    <p className="text-2xl font-black tabular-nums leading-none mt-0.5 text-white">{c.value}</p>
                    {c.value > 0 && totalCount > 0 && (
                      <p className="text-[9px] mt-0.5 text-white/30">
                        {Math.round((c.value / totalCount) * 100)}% {zh ? '资产' : 'of fleet'}
                      </p>
                    )}
                  </div>
                  <div className="h-8 w-8 rounded-lg flex items-center justify-center bg-white/[0.08]">
                    <c.Icon size={16} className={`text-white/77 ${!isEmpty && c.pulse ? 'animate-pulse' : ''}`} />
                  </div>
                </div>
                {isActive && <div className="absolute bottom-0 left-0 right-0 h-1 bg-white/20" />}
              </button>
            );
          })}
        </div>

        <div className="relative z-20 bg-white rounded-xl border border-black/5 shadow-sm overflow-visible">
          <div className="flex items-center justify-between px-3 py-1.5 border-b border-black/5 bg-black/[0.008]">
            <div className="flex items-center gap-0.5">
              <span className="flex items-center gap-1 px-2.5 py-1.5 rounded-md bg-[#00bceb]/10 text-[#0088b0] text-[11px] font-semibold">
                <LayoutList size={12} />{zh ? '表格' : 'Table'}
              </span>
            </div>

            <div className="flex items-center gap-1">
              <AnimatePresence>
                {selectedIds.size > 0 && (
                  <motion.div initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 12 }} className="flex items-center gap-0.5 mr-1.5 pr-1.5 border-r border-black/8">
                    <span className="text-[10px] font-bold text-[#00bceb] tabular-nums mr-1">{selectedIds.size}</span>
                    <button onClick={requestBatchTakeover} className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-cyan-500 text-[9px] font-medium hover:bg-cyan-50 hover:text-cyan-600 transition-colors"><Shield size={10} />{zh ? '批量上收' : 'Takeover'}</button>
                    <button onClick={handleBatchDelete} className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-black/35 text-[9px] font-medium hover:bg-red-50 hover:text-red-600 transition-colors"><Trash2 size={10} />{zh ? '删除' : 'Delete'}</button>
                    <button onClick={clearSel} className="p-0.5 ml-0.5 text-black/20 hover:text-black/45" title="Clear"><X size={10} /></button>
                  </motion.div>
                )}
              </AnimatePresence>

              <div ref={columnsMenuRef} className="relative">
                <button
                  onClick={() => setColumnsOpen(open => !open)}
                  className={`flex items-center gap-1 px-2 py-1 rounded-md border text-[11px] font-semibold transition-colors ${columnsOpen ? 'border-[#00bceb]/30 bg-[#00bceb]/5 text-[#0088b0]' : 'border-black/8 bg-white text-black/45 hover:border-[#00bceb]/25 hover:text-[#0088b0]'}`}
                  title={zh ? '配置展示列' : 'Configure columns'}
                >
                  <Settings2 size={13} /><span className="hidden sm:inline">{zh ? '展示列' : 'Columns'}</span>
                </button>
                {columnsOpen && (
                  <div className="absolute right-0 top-full z-40 mt-2 w-64 rounded-xl border border-slate-200 bg-white p-3 shadow-xl">
                    <div className="mb-2 flex items-center justify-between">
                      <span className="text-xs font-bold text-slate-700">{zh ? '选择展示列' : 'Visible columns'}</span>
                      <span className="text-[10px] text-slate-400">{activeAssetColumns.length}/{ASSET_COLUMN_DEFS.length}</span>
                    </div>
                    <button
                      onClick={() => setVisibleColumns(normalizeAssetColumns(Object.fromEntries(ASSET_COLUMN_DEFS.map(column => [column.key, true]))))}
                      disabled={allAssetColumnsSelected}
                      className="mb-2 w-full rounded-lg bg-cyan-50 px-2 py-1.5 text-left text-[11px] font-semibold text-cyan-700 disabled:cursor-default disabled:opacity-50"
                    >
                      {zh ? '一键全选' : 'Select all'}
                    </button>
                    <div className="max-h-80 overflow-y-auto pr-1">
                      {ASSET_COLUMN_DEFS.map(column => {
                        const fixed = FIXED_ASSET_COLUMNS.has(column.key);
                        return (
                        <label key={column.key} className={`flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs ${fixed ? 'cursor-default text-slate-400' : 'cursor-pointer text-slate-600 hover:bg-slate-50'}`}>
                          <input
                            type="checkbox"
                            checked={visibleColumns[column.key]}
                            disabled={fixed}
                            onChange={() => { if (!fixed) setVisibleColumns(current => normalizeAssetColumns({ ...current, [column.key]: !current[column.key] })); }}
                            className="accent-[#00bceb] disabled:opacity-50"
                          />
                          <span className="flex-1">{zh ? column.zh : column.en}</span>
                          {visibleColumns[column.key] && <Check size={13} className={fixed ? 'text-cyan-600/60' : 'text-cyan-600'} />}
                        </label>
                        );
                      })}
                    </div>
                    <button
                      onClick={() => setVisibleColumns(normalizeAssetColumns({}))}
                      className="mt-2 w-full border-t border-slate-100 pt-2 text-left text-[11px] text-cyan-600"
                    >
                      {zh ? '恢复默认展示' : 'Reset to default'}
                    </button>
                  </div>
                )}
              </div>
              <button onClick={openAdd} className="flex items-center gap-1 px-2 py-1 rounded-md bg-[#00bceb] text-white text-[11px] font-semibold hover:bg-[#00a5d0] shadow-sm shadow-[#00bceb]/20" title={zh ? '新增资产' : 'Add Asset'}><Plus size={13} /><span className="hidden sm:inline">{zh ? '新增' : 'Add'}</span></button>
              <button onClick={() => { fetchAssets(); fetchSummary(); }} className="p-1.5 rounded-md text-black/20 hover:text-[#00bceb] hover:bg-[#00bceb]/5" title={zh ? '刷新' : 'Refresh'}><RefreshCw size={13} /></button>
              <button onClick={handleDownloadTemplate} className="p-1.5 rounded-md text-black/20 hover:text-[#00bceb] hover:bg-[#00bceb]/5" title={zh ? '下载模板' : 'Template'}><FileText size={13} /></button>
              <button onClick={handleExport} className="p-1.5 rounded-md text-black/20 hover:text-[#00bceb] hover:bg-[#00bceb]/5" title={zh ? '导出' : 'Export'}><Download size={13} /></button>
              <button onClick={() => fileInputRef.current?.click()} className="p-1.5 rounded-md text-black/20 hover:text-[#00bceb] hover:bg-[#00bceb]/5" title={zh ? '导入' : 'Import'}><Upload size={13} /></button>
            </div>
          </div>

          <div className="border-b border-black/[0.03]">
            <div className="flex items-center gap-1.5 px-3 py-1.5">
              <div className="relative flex-1 max-w-[280px]">
                <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-black/15" />
                <input
                  value={search} onChange={e => setSearch(e.target.value)}
                  placeholder={zh ? 'IP / 主机名 / 资产编号 / 序列号...' : 'IP / hostname / tag / serial...'}
                  className="w-full pl-7 pr-6 py-1.5 rounded-md bg-black/[0.015] border border-black/5 text-[11px] text-black/75 placeholder:text-black/15 focus:outline-none focus:border-[#00bceb]/25 focus:ring-1 focus:ring-[#00bceb]/10 focus:bg-white"
                />
                {search && <button onClick={() => setSearch('')} title="Clear" className="absolute right-1.5 top-1/2 -translate-y-1/2 text-black/15 hover:text-black/35"><X size={10} /></button>}
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
                  key={f.label} value={f.val} onChange={e => f.set(e.target.value)} title={f.label}
                  className={`px-1.5 py-1.5 rounded-md border text-[10px] focus:outline-none cursor-pointer transition-colors ${f.val !== 'all' ? 'bg-[#00bceb]/5 border-[#00bceb]/15 text-[#0088b0] font-semibold' : 'bg-transparent border-black/5 text-black/30'}`}
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
                onClick={() => setShowAdvancedFilter(p => !p)}
                className={`flex items-center gap-1 px-1.5 py-1.5 rounded-md border text-[10px] font-medium transition-colors ${showAdvancedFilter || advancedFilterCount > 0 ? 'bg-[#00bceb]/5 border-[#00bceb]/15 text-[#0088b0]' : 'bg-transparent border-black/5 text-black/30 hover:text-black/50'}`}
                title={zh ? '高级筛选' : 'Advanced Filters'}
              >
                <SlidersHorizontal size={11} />
                <span>{zh ? '筛选' : 'Filter'}</span>
                {advancedFilterCount > 0 && (
                  <span className="ml-0.5 h-3.5 min-w-[14px] inline-flex items-center justify-center rounded-full bg-[#00bceb] text-white text-[8px] font-bold">{advancedFilterCount}</span>
                )}
              </button>

              {(hasFilters || severityFilter !== 'all') && (
                <button onClick={clearAllFilters} className="text-[9px] text-[#00bceb] hover:underline ml-0.5 whitespace-nowrap">{zh ? '清除全部' : 'Clear all'}</button>
              )}

              <div className="flex-1" />
              <span className="text-[10px] text-black/20 tabular-nums whitespace-nowrap">{total} {zh ? '条记录' : 'records'}</span>
            </div>

            <AnimatePresence>
              {showAdvancedFilter && (
                <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.15 }} className="overflow-hidden">
                  <div className="flex items-center gap-1.5 px-3 py-1.5 bg-black/[0.008] border-t border-black/[0.02]">
                    <span className="text-[9px] text-black/20 mr-0.5">{zh ? '高级:' : 'More:'}</span>
                    {([
                      { val: vendorFilter, set: setVendorFilter, label: zh ? '厂商' : 'Vendor', opts: vendorList.map(v => ({ v, l: v })),   hide: !vendorList.length },
                      { val: dcFilter,     set: setDcFilter,     label: zh ? '站点' : 'Site',   opts: dcList.map(d => ({ v: d.value, l: d.label })), hide: !dcList.length },
                      { val: deptFilter,   set: setDeptFilter,   label: zh ? '业务' : 'Service', opts: deptList.map(d => ({ v: d, l: d })),  hide: !deptList.length },
                      { val: lifecycleFilter, set: setLifecycleFilter, label: zh ? '投产' : 'Lifecycle', opts: LIFECYCLE_STATUSES.map(s => ({ v: s.value, l: s.label[zh ? 'zh' : 'en'] })), hide: false },
                    ] as const).filter(f => !f.hide).map(f => (
                      <select
                        key={f.label} value={f.val} onChange={e => f.set(e.target.value)} title={f.label}
                        className={`px-1.5 py-1.5 rounded-md border text-[10px] focus:outline-none cursor-pointer transition-colors ${f.val !== 'all' ? 'bg-[#00bceb]/5 border-[#00bceb]/15 text-[#0088b0] font-semibold' : 'bg-transparent border-black/5 text-black/30'}`}
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
              <DataTable className="text-[12px]">
                <thead>
                  <tr className="border-b border-black/5 bg-black/[0.008]">
                    <th className="w-7 px-1.5 py-1.5">
                      <input type="checkbox" checked={selectedIds.size === displayAssets.length && displayAssets.length > 0} onChange={toggleAll} className="h-3 w-3 rounded border-black/12 accent-[#00bceb] cursor-pointer" />
                    </th>
                    {activeAssetColumns.map(column => (
                      <th key={column.key} className={`text-left px-1.5 py-2 text-[10px] font-bold uppercase tracking-wider text-black/35 ${column.width}`}>
                        {zh ? column.zh : column.en}
                      </th>
                    ))}
                    <th className="w-20 px-1.5 py-1.5 text-center text-[9px] font-bold uppercase tracking-wider text-black/20">{zh ? '操作' : 'Actions'}</th>
                  </tr>
                </thead>
                <tbody>
                  {loading ? (
                    <tr><td colSpan={activeAssetColumns.length + 2} className="text-center py-16 text-black/15">
                      <RefreshCw size={16} className="mx-auto mb-1.5 animate-spin text-[#00bceb]/25" />
                      <p className="text-[10px]">{zh ? '加载中...' : 'Loading...'}</p>
                    </td></tr>
                  ) : displayAssets.length === 0 ? (
                    <tr><td colSpan={activeAssetColumns.length + 2} className="py-16">
                      <div className="text-center max-w-lg mx-auto">
                        <div className="relative h-24 w-24 mx-auto mb-5">
                          <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-[#00bceb]/5 to-[#00bceb]/10 flex items-center justify-center">
                            <Package size={36} className="text-[#00bceb]/20" />
                          </div>
                          <div className="absolute -right-1 -top-1 h-6 w-6 rounded-full bg-emerald-100 flex items-center justify-center">
                            <Wifi size={10} className="text-emerald-500" />
                          </div>
                        </div>
                        <p className="text-lg font-bold text-black/50 mb-1">{zh ? '开始管理你的网络' : 'Start Managing Your Network'}</p>
                        <p className="text-[11px] text-black/20 mb-6 leading-relaxed max-w-sm mx-auto">
                          {zh ? '添加网络设备和服务器，自动发现拓扑，连接监控系统' : 'Add devices, discover topology, connect monitoring'}
                        </p>
                        <div className="flex items-center justify-center gap-2 flex-wrap">
                          <button onClick={openAdd} className="flex items-center gap-1.5 px-5 py-2 rounded-lg bg-[#00bceb] text-white text-[11px] font-bold hover:bg-[#00a5d0] shadow-sm shadow-[#00bceb]/20"><Plus size={13} />{zh ? '添加资产' : 'Add Asset'}</button>
                          <button onClick={() => fileInputRef.current?.click()} className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-black/8 text-black/35 text-[11px] font-medium hover:bg-black/[0.01]"><Upload size={12} />{zh ? '导入 Excel' : 'Import Excel'}</button>
                        </div>
                      </div>
                    </td></tr>
                  ) : displayAssets.map(a => {
                    const sel = selectedIds.has(a.id);
                    const isDrawerTarget = drawerAsset?.id === a.id;

                    return (
                      <tr
                        key={a.id} onClick={() => setDrawerAsset(a)}
                        className={`border-b border-black/[0.02] cursor-pointer transition-colors ${sel ? 'bg-[#00bceb]/[0.025]' : isDrawerTarget ? 'bg-black/[0.015]' : 'hover:bg-black/[0.008]'}`}
                      >
                        <td className="px-1.5 py-1" onClick={e => e.stopPropagation()}>
                          <input type="checkbox" checked={sel} onChange={() => toggle(a.id)} className="h-3 w-3 rounded border-black/12 accent-[#00bceb] cursor-pointer" />
                        </td>
                        {activeAssetColumns.map(column => (
                        <td key={column.key} className="px-1.5 py-1.5 text-[12px]">
                            {renderAssetCell(column.key, a)}
                          </td>
                        ))}
                        <td className="px-1.5 py-1" onClick={e => e.stopPropagation()}>
                          <div className="flex items-center justify-center gap-px">
                            <button onClick={() => openCopy(a)} className="p-1 rounded text-black/12 hover:text-emerald-500 hover:bg-emerald-50" title={zh ? '复制' : 'Copy'}><Copy size={12} /></button>
                            <button onClick={() => openEdit(a)} className="p-1 rounded text-black/12 hover:text-[#00bceb] hover:bg-[#00bceb]/5" title={zh ? '编辑' : 'Edit'}><Pencil size={12} /></button>
                            <button onClick={() => setDeleteTarget(a)} className="p-1 rounded text-black/12 hover:text-red-500 hover:bg-red-50" title={zh ? '删除' : 'Delete'}><Trash2 size={12} /></button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </DataTable>
            </DataTableFrame>

          {/* Legacy grouped view removed; assets are now shown only in the table view.
          {viewMode === 'group' && false && (
            <div className="divide-y divide-black/[0.03]">
              {loading ? (
                <div className="text-center py-14 text-black/15"><RefreshCw size={16} className="mx-auto mb-1.5 animate-spin text-[#00bceb]/25" /></div>
              ) : Object.keys(groupedAssets).length === 0 ? (
                <div className="text-center py-14"><Building2 size={24} className="mx-auto mb-1.5 text-black/8" /><p className="text-xs text-black/20">{zh ? '无分组数据' : 'No groups'}</p></div>
              ) : (Object.entries(groupedAssets) as [string, Asset[]][]).sort((a, b) => b[1].length - a[1].length).map(([gk, items]) => {
                const isExp = expandedGroups.has(gk);
                const onlineIn = items.filter(a => a.status === 'active').length;
                const offlineIn = items.filter(a => a.status === 'inactive').length;
                const GroupIcon = groupBy === 'site_id' ? Building2 : groupBy === 'vendor' ? MonitorSpeaker : Zap;
                return (
                  <div key={gk}>
                    <button
                      onClick={() => setExpandedGroups(p => { const n = new Set(p); n.has(gk) ? n.delete(gk) : n.add(gk); return n; })}
                      className="w-full flex items-center justify-between px-4 py-2 hover:bg-black/[0.005] transition-colors"
                    >
                      <div className="flex items-center gap-2.5">
                        <GroupIcon size={14} className="text-black/15" />
                        <span className="text-[12px] font-semibold text-black/65">{gk}</span>
                        <span className="text-[9px] text-black/20 tabular-nums">{items.length}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <div className="flex h-1.5 w-16 rounded-full overflow-hidden bg-black/[0.03]">
                          {onlineIn > 0 && <div className="bg-emerald-400" style={{ width: `${(onlineIn / items.length) * 100}%` }} />}
                          {offlineIn > 0 && <div className="bg-red-400" style={{ width: `${(offlineIn / items.length) * 100}%` }} />}
                        </div>
                        <span className="text-[9px] text-black/15 tabular-nums w-8 text-right">{onlineIn}/{items.length}</span>
                        {isExp ? <ChevronUp size={12} className="text-black/15" /> : <ChevronDown size={12} className="text-black/15" />}
                      </div>
                    </button>
                    <AnimatePresence>
                      {isExp && (
                        <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                          <table className="w-full text-[10px]">
                            <tbody>
                              {items.map(a => {
                                const sm = statusMeta(a.status);
                                return (
                                  <tr key={a.id} onClick={() => setDrawerAsset(a)} className="border-b border-black/[0.015] hover:bg-black/[0.006] cursor-pointer transition-colors">
                                    <td className="pl-10 pr-2 py-1.5 font-semibold text-black/65 text-[11px]">{a.hostname || a.asset_tag || '—'}</td>
                                    <td className="px-2 py-1.5 text-black/25">{typeDisplay(a)}</td>
                                    <td className="px-2 py-1.5 font-mono text-black/35">{a.management_ip || '—'}</td>
                                    <td className="px-2 py-1.5">
                                      <span className={`inline-flex items-center gap-1 text-[9px] font-bold ${sm.text}`}>
                                        <span className={`h-1.5 w-1.5 rounded-full ${sm.dot}`} />{sm.label[zh ? 'zh' : 'en']}
                                      </span>
                                    </td>
                                    <td className="px-2 py-1.5 text-[9px] text-black/30">{categoryDisplay(a)}</td>
                                    <td className="px-2 py-1.5">
                                      <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-bold ${a.lifecycle_status === 'production' ? 'bg-emerald-50 text-emerald-600' : a.lifecycle_status === 'decommissioned' ? 'bg-slate-100 text-slate-400' : a.lifecycle_status === 'maintenance' ? 'bg-amber-50 text-amber-600' : 'bg-blue-50 text-blue-500'}`}>
                                        {LIFECYCLE_STATUSES.find(l => l.value === a.lifecycle_status)?.label[zh ? 'zh' : 'en'] || (zh ? '待投产' : 'Staging')}
                                      </span>
                                    </td>
                                    <td className="px-2 py-1.5 text-right">
                                      <button onClick={e => { e.stopPropagation(); openCopy(a); }} title={zh ? '复制' : 'Copy'} className="p-1 rounded text-black/10 hover:text-emerald-500 hover:bg-emerald-50"><Copy size={11} /></button>
                                      <button onClick={e => { e.stopPropagation(); openEdit(a); }} title="Edit" className="p-1 rounded text-black/10 hover:text-[#00bceb] hover:bg-[#00bceb]/5"><Pencil size={11} /></button>
                                    </td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                );
              })}
            </div>
          )}
          */}

          {terminalSession && (
            <motion.div
              className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 backdrop-blur-sm"
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              onClick={() => setTerminalSession(null)}
            >
              <motion.div
                className="bg-[#0b1220] rounded-xl w-[900px] max-w-[95vw] h-[560px] border border-white/10 shadow-2xl flex flex-col"
                onClick={(e) => e.stopPropagation()}
                initial={{ scale: 0.98, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.98, opacity: 0 }}
              >
                <div className="h-10 border-b border-white/10 px-3 flex items-center justify-between text-white/80 text-xs">
                  <div className="font-semibold">{terminalSession.title}</div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={async () => {
                        const terminalType = localStorage.getItem('terminal_app') || 'xshell';
                        const terminalPath = localStorage.getItem('local_terminal_path') || '';
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
                              throw new Error(result.error || 'Unable to create local terminal session');
                            }
                            if (!result.client_side) {
                              setTerminalSession(null);
                              return;
                            }
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
                            setTerminalSession(null);
                            return;
                          } catch (err) {
                            console.error('Local Terminal Agent launch failed', err);
                            setTerminalSession(null);
                            return;
                          }
                        }
                      }}
                      className="text-[10px] bg-emerald-500/20 text-emerald-400 px-2 py-0.5 rounded hover:bg-emerald-500/30 transition-all flex items-center gap-1"
                    >
                      <MonitorSpeaker size={10} />
                      {(() => {
                        const app = localStorage.getItem('terminal_app') || 'xshell';
                        const appName = app === 'standard' ? 'SSH' : app === 'xshell' ? 'Xshell' : app === 'putty' ? 'PuTTY' : app === 'securecrt' ? 'SecureCRT' : app === 'mobaxterm' ? 'MobaXterm' : 'Terminal';
                        return zh ? `${appName} 调起` : `Launch ${appName}`;
                      })()}
                    </button>
                    <button onClick={() => setTerminalSession(null)} className="text-white/50 hover:text-white ml-2"><X size={14} /></button>
                  </div>
                </div>
                <div className="flex-1 bg-black/20 relative overflow-hidden">
                  <div
                    ref={el => el && initTerminal(el, 'asset-terminal')}
                    className="absolute inset-0 p-2"
                  />
                </div>
                <div className="h-12 border-t border-white/10 px-2 flex items-center gap-2">
                  <input
                    value={terminalInput}
                    onChange={(e) => setTerminalInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') sendTerminalInput(); }}
                    placeholder={zh ? '输入命令并回车' : 'Type command and press Enter'}
                    className="flex-1 h-8 bg-black/30 border border-white/15 rounded px-2 text-xs text-white outline-none"
                  />
                  <button onClick={sendTerminalInput} className="h-8 px-3 rounded bg-[#00bceb] text-white text-xs font-bold hover:bg-[#00a5d0]">{zh ? '发送' : 'Send'}</button>
                </div>
              </motion.div>
            </motion.div>
          )}
        </div>

        {total > 0 && (
          <div className="mt-auto pt-4 border-t border-black/5 bg-white">
            <Pagination currentPage={page} totalItems={total} itemsPerPage={pageSize} onPageChange={setPage} onItemsPerPageChange={setPageSize} language={language} />
          </div>
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
        onClose={() => setDeleteTarget(null)}
        deleteTarget={deleteTarget}
        handleDelete={handleDelete}
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
