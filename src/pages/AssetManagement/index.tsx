import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Terminal as XTerm } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import 'xterm/css/xterm.css';
import {
  Package, Plus, Trash2, Search, X, RefreshCw, Download, Pencil, Copy,
  Server, Router, AlertTriangle, Network, SlidersHorizontal,
  Wifi, Building2, Upload, FileText, ChevronDown, ChevronRight, ChevronUp,
  Zap, AlertCircle, CheckCircle2, Info,
  Flame, LayoutList, LayoutGrid, Lock, Terminal, Eye, EyeOff, Loader2, Shield, User, MonitorSpeaker, Settings2, Check
} from 'lucide-react';
import * as XLSX from 'xlsx';
import { AnimatePresence, motion } from 'motion/react';

import Pagination from '../../components/Pagination';
import PageHero from '../../components/PageHero';
import TagFilterDropdown from '../../components/TagFilterDropdown';
import { fetchAllPaginatedItems } from '../../utils/pagination';
import { useSystem } from '../../hooks/useSystem';
import type { TagDefinition } from '../../types';

import { Asset, AssetSummary, AssetManagementTabProps, ViewMode, GroupBy } from './types';
import { STATUSES, TYPES, LIFECYCLE_STATUSES, EMPTY_FORM, VENDOR_PLATFORMS, SERVER_PLATFORMS, ALL_PLATFORMS, COL_MAP, IMPORT_VALUE_MAP } from './constants';
import { statusMeta, typeMeta, severityOf } from './helpers';

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

type AssetTreeRow = {
  asset_type: string;
  device_category: string;
  site_id: string;
  site_name: string;
  device_role: string;
  online_status: 'online' | 'offline' | 'pending' | string;
  asset_count: number;
};

type AssetTreeNode = {
  key: string;
  label: string;
  kind: 'root' | 'category' | 'site' | 'status';
  count: number;
  filters: { asset_type?: string; device_category?: string; site_id?: string; device_role?: string; status?: string };
  children: AssetTreeNode[];
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
  tags: true,
  vendor: true,
  model: true,
  serial_number: true,
  management_ip: true,
  lifecycle: true,
  created_at: true,
  updated_at: true,
};

const FIXED_ASSET_COLUMNS = new Set<AssetColumnKey>([
  'hostname', 'category_role', 'site', 'status', 'tags', 'created_at', 'updated_at',
]);

const NETWORK_TEMPLATE_ROLES = new Set([
  'core', 'distribution', 'access', 'edge', 'switch', 'router', 'firewall',
  'wireless_controller', 'wireless_ap', 'load_balancer', 'vpn_gateway', 'sdwan_edge', 'other_network',
]);
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

const ASSET_COLUMNS_STORAGE_KEY = 'assets-dashboard-columns-v2';

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
  const [pageSize, setPageSize]         = useState(10);
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

  const [viewMode, setViewMode]         = useState<ViewMode>('table');
  const [groupBy, setGroupBy]           = useState<GroupBy>('site_id');
  const [selectedIds, setSelectedIds]   = useState<Set<string>>(new Set());
  const [drawerAsset, setDrawerAsset]   = useState<Asset | null>(null);

  const [showModal, setShowModal]       = useState(false);
  const [editingAsset, setEditingAsset] = useState<Asset | null>(null);
  const [form, setForm]                 = useState({ ...EMPTY_FORM });
  const [saving, setSaving]             = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Asset | null>(null);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [showProductionConfirm, setShowProductionConfirm] = useState(false);
  const [modalError, setModalError] = useState<string | null>(null);
  const [showEnableSecret, setShowEnableSecret] = useState(false);
  const [showAdvancedFilter, setShowAdvancedFilter] = useState(false);
  const [rotatingAssetId, setRotatingAssetId] = useState<string | null>(null);
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const rotationPollRef = React.useRef<any>(null);

  const [allRacks, setAllRacks] = useState<any[]>([]);
  const [showValidationModal, setShowValidationModal] = useState(false);
  const [missingRacks, setMissingRacks] = useState<MissingRackInfo[]>([]);
  const [pendingImportPayload, setPendingImportPayload] = useState<any[]>([]);
  const [validationModalSaving, setValidationModalSaving] = useState(false);
  const [allTags, setAllTags] = useState<TagDefinition[]>([]);
  const [assetTreeRows, setAssetTreeRows] = useState<AssetTreeRow[]>([]);
  const [assetTreeLoading, setAssetTreeLoading] = useState(false);
  const [expandedTreeNodes, setExpandedTreeNodes] = useState<Set<string>>(new Set());
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

  useEffect(() => () => { if (rotationPollRef.current) clearInterval(rotationPollRef.current); }, []);

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
      if (tagFilter.length > 0)   p.set('tag_ids', tagFilter.join(','));
      const r = await fetch(`/api/assets?${p}`);
      if (r.ok) { const d = await r.json(); setAssets(d.items); setTotal(d.total); }
    } catch { /* noop */ }
    setLoading(false);
  }, [page, pageSize, search, typeFilter, statusFilter, vendorFilter, dcFilter, deptFilter, deviceCategoryFilter, tagFilter]);

  useEffect(() => { fetchSummary(); }, [fetchSummary]);
  useEffect(() => { fetchSites(); }, [fetchSites]);
  useEffect(() => { fetchAssets(); }, [fetchAssets]);
  useEffect(() => { setPage(1); }, [search, typeFilter, statusFilter, vendorFilter, dcFilter, deptFilter, deviceCategoryFilter, tagFilter, pageSize]);

  const fetchAssetTree = useCallback(async () => {
    setAssetTreeLoading(true);
    try {
      const response = await fetch('/api/assets/tree');
      const payload = await response.json();
      setAssetTreeRows(Array.isArray(payload?.data?.items) ? payload.data.items : Array.isArray(payload?.items) ? payload.items : []);
    } catch {
      setAssetTreeRows([]);
    } finally {
      setAssetTreeLoading(false);
    }
  }, []);

  useEffect(() => {
    if (viewMode === 'tree') void fetchAssetTree();
  }, [viewMode, fetchAssetTree]);

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
      snmp_community: (a as any).snmp_community || 'public',
      snmp_port: String((a as any).snmp_port || '161'),
      management_port: String(a.management_port || '22'),
      device_category: a.device_category || '',
      power_watts: a.power_watts != null ? String(a.power_watts) : '',
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
      snmp_community: a.snmp_community || 'public',
      snmp_port: String(a.snmp_port || '161'),
      management_port: String(a.management_port || '22'),
      device_category: a.device_category || '',
      power_watts: a.power_watts != null ? String(a.power_watts) : '',
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
    if (!confirm(zh ? `确定要批量上收这 ${selectedIds.size} 台资产的口令并投产吗？（方案A：将执行改密与回连测试）` : `Confirm batch takeover and production for ${selectedIds.size} assets? (Scheme A: Rotation and post-check will be executed)`)) return;

    setLoading(true);
    try {
      const r = await fetch('/api/assets/takeover/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ asset_ids: Array.from(selectedIds) })
      });
      if (r.ok) {
        const data = await r.json();
        const errors = data.results.filter((res: any) => res.status === 'error');
        if (errors.length > 0) {
          setFeedbackMsg({ type: 'warning', text: zh ? `部分上收任务启动失败 (${errors.length}台)` : `Some takeover tasks failed to start (${errors.length})` });
        } else {
          setFeedbackMsg({ type: 'success', text: zh ? '批量上收任务已在后台启动，请刷新列表查看进度。' : 'Batch takeover tasks started in background. Refresh to see progress.' });
        }
        clearSel();
        fetchAssets();
      }
    } catch (e) {
      setFeedbackMsg({ type: 'error', text: zh ? '批量操作失败' : 'Batch operation failed' });
    }
    setLoading(false);
  };

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
        [zh ? '类型' : 'Type']: a.asset_type,
        [zh ? '厂商' : 'Vendor']: a.vendor,
        [zh ? '型号' : 'Model']: a.model,
        [zh ? '平台' : 'Platform']: (a as any).platform || '',
        [zh ? '管理IP' : 'Mgmt IP']: a.management_ip,
        [zh ? '管理端口' : 'Mgmt Port']: (a as any).management_port || '22',
        [zh ? '业务IP' : 'Business IP']: a.business_ip,
        [zh ? '连接方式' : 'Connection']: (a as any).connection_method || 'ssh',
        [zh ? '状态' : 'Status']: a.status,
        [zh ? '角色' : 'Role']: a.device_role,
        [zh ? '设备分类' : 'Device Category']: (a as any).device_category || '',
        [zh ? 'VLAN' : 'VLAN']: a.vlan,
        [zh ? '上联交换机' : 'Uplink Switch']: a.uplink_switch,
        [zh ? '上联端口' : 'Uplink Port']: a.uplink_port,
        [zh ? '站点' : 'Site']: a.site_name || a.site_code || a.site_id,
        [zh ? '机柜' : 'Rack']: a.rack,
        [zh ? 'U位' : 'Rack Unit']: a.rack_unit,
        [zh ? 'U高度' : 'U Height']: a.u_height ?? 1,
        [zh ? '规划起始U' : 'Planned Start U']: a.planned_start_u ?? '',
        [zh ? '功耗(W)' : 'Power(W)']: (a as any).power_watts ?? '',
        [zh ? 'SNMP社区名' : 'SNMP Community']: (a as any).snmp_community || 'public',
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
      XLSX.utils.book_append_sheet(wb, ws, 'Assets');
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
        const templateMismatchRows: string[] = [];
        for (const name of wb.SheetNames) {
          const ws = wb.Sheets[name];
          const raw = XLSX.utils.sheet_to_json<Record<string, string>>(ws, { defval: '' });
          const isNet = NET_SHEET.test(name);
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
            if (!obj.asset_type) obj.asset_type = isNet ? 'network_device' : 'server';
            if (obj.hostname || obj.asset_tag) {
              const allowedRoles = isNet ? NETWORK_TEMPLATE_ROLES : SERVER_TEMPLATE_ROLES;
              const allowedCategories = isNet ? NETWORK_TEMPLATE_CATEGORIES : SERVER_TEMPLATE_CATEGORIES;
              if (obj.device_role && !allowedRoles.has(obj.device_role)) {
                templateMismatchRows.push(`${name} 第${rowIndex + 2}行：角色“${obj.device_role}”不属于${isNet ? '网络设备' : '服务器'}模板`);
                continue;
              }
              if (obj.device_category && !allowedCategories.has(obj.device_category)) {
                templateMismatchRows.push(`${name} 第${rowIndex + 2}行：设备分类“${obj.device_category}”不属于${isNet ? '网络设备' : '服务器'}模板`);
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
      ['录入来源', '必填', '填写“新设备”或“存量设备”'],
      ['投产状态', '必填', '新设备填写“待投产”；存量设备可填写“待投产”或“已投产”'],
      ['主机名/资产编号', '至少一项', '主机名和资产编号不能同时为空'],
      ['普通用户/普通密码', '条件必填', '存量设备直接填写“已投产”时必须填写'],
      ['特权用户/特权密码', '标准投产必填', '标准口令上收和改密使用'],
      ['免上收投产原因', '条件必填', '录入来源为“存量设备”且投产状态为“已投产”时至少填写 5 个字符'],
    ] : [
      ['Asset Import Instructions'],
      ['Field', 'Required', 'Rule'],
      ['Asset Origin', 'Yes', 'Use new (new device) or legacy (existing device)'],
      ['Lifecycle', 'Yes', 'Use staging for new devices; legacy devices may use staging or production'],
      ['Hostname / Asset Tag', 'At least one', 'Hostname and Asset Tag cannot both be empty'],
      ['Normal User / Password', 'Conditional', 'Required for legacy devices imported as production'],
      ['Admin User / Password', 'Standard production', 'Required for managed password takeover'],
      ['Takeover Exemption Reason', 'Conditional', 'Minimum 5 characters for legacy + production'],
    ];
    const wsGuide = XLSX.utils.aoa_to_sheet(guideRows);
    wsGuide['!cols'] = [{ wch: 28 }, { wch: 18 }, { wch: 72 }];
    XLSX.utils.book_append_sheet(wb, wsGuide, zh ? '填写说明' : 'Instructions');

    const srvHeaders = zh
      ? ['主机名', '资产编号', '序列号', '厂商', '型号', '平台', '管理IP', '管理端口', '业务IP', '连接方式', '状态', '角色', '设备分类', '录入来源（必填：新设备或存量设备）', 'VLAN', '上联交换机', '上联端口', '站点', '机柜', 'U位', 'U高度', '规划起始U', '功耗(W)', 'SNMP社区名', 'SNMP端口', '普通用户', '特权用户', '普通密码', '特权密码', 'Enable密码', '部门', '购买日期', '投产状态', '免上收投产原因', '保修到期', '备注']
      : ['Hostname', 'Asset Tag', 'Serial Number', 'Vendor', 'Model', 'Platform', 'Mgmt IP', 'Mgmt Port', 'Business IP', 'Connection', 'Status', 'Role', 'Device Category', 'Asset Origin (Required: new or legacy)', 'VLAN', 'Uplink Switch', 'Uplink Port', 'Site', 'Rack', 'Rack Unit', 'U Height', 'Planned Start U', 'Power(W)', 'SNMP Community', 'SNMP Port', 'Normal User', 'Admin User', 'Normal Password', 'Admin Password', 'Enable Secret', 'Department', 'Purchase Date', 'Lifecycle', 'Takeover Exemption Reason', 'Warranty Expiry', 'Notes'];
    const srvExample = zh
      ? ['web-srv-01', 'SRV-BJ-001', 'CZJ2345G0HN', '戴尔', 'PowerEdge R750', 'Linux（通用）', '10.0.1.10', '22', '192.168.1.10', 'SSH（安全外壳）', '在用', '业务服务器', '机架式服务器', '新设备', 'VLAN100', 'core-sw-01', 'Gi0/1', 'BJ-DC1', 'A-01', '12', '1', '12', '200', 'public', '161', 'user', 'admin', '', '', '', 'IT部', '2024-01-15', '待投产', '', '2027-01-15', '服务器备注']
      : ['web-srv-01', 'SRV-BJ-001', 'CZJ2345G0HN', 'Dell', 'PowerEdge R750', 'linux', '10.0.1.10', '22', '192.168.1.10', 'ssh', 'active', 'web', 'server', 'new', 'VLAN100', 'core-sw-01', 'Gi0/1', 'BJ-DC1', 'A-01', '12', '1', '12', '200', 'public', '161', 'user', 'admin', '', '', '', 'IT Dept', '2024-01-15', 'staging', '', '2027-01-15', 'Production srv'];
    const wsSrv = XLSX.utils.aoa_to_sheet([srvHeaders, srvExample]);
    wsSrv['!cols'] = srvHeaders.map(() => ({ wch: 16 }));
    XLSX.utils.book_append_sheet(wb, wsSrv, zh ? '服务器模板' : 'Server Template');

    const netHeaders = zh
      ? ['主机名', '资产编号', '序列号', '厂商', '型号', '平台', '管理IP', '管理端口', '连接方式', '状态', '角色', '设备分类', '录入来源（必填：新设备或存量设备）', '站点', '机柜', 'U位', 'U高度', '规划起始U', '功耗(W)', 'SNMP社区名', 'SNMP端口', '普通用户', '特权用户', '普通密码', '特权密码', 'Enable密码', '部门', '购买日期', '投产状态', '免上收投产原因', '保修到期', '备注']
      : ['Hostname', 'Asset Tag', 'Serial Number', 'Vendor', 'Model', 'Platform', 'Mgmt IP', 'Mgmt Port', 'Connection', 'Status', 'Role', 'Device Category', 'Asset Origin (Required: new or legacy)', 'Site', 'Rack', 'Rack Unit', 'U Height', 'Planned Start U', 'Power(W)', 'SNMP Community', 'SNMP Port', 'Normal User', 'Admin User', 'Normal Password', 'Admin Password', 'Enable Secret', 'Department', 'Purchase Date', 'Lifecycle', 'Takeover Exemption Reason', 'Warranty Expiry', 'Notes'];
    const netExample = zh
      ? ['core-sw-01', 'NET-BJ-001', 'FCW2345L0AB', '思科', 'C9300-48P', '思科 IOS', '10.0.0.1', '22', 'SSH（安全外壳）', '在用', '核心交换机', '交换机', '存量设备', 'BJ-DC1', 'A-02', '40', '1', '40', '200', 'public', '161', 'user', 'admin', '普通账号密码', '特权账号密码', '', 'IT部', '2023-06-01', '已投产', '存量设备已在线运行', '2026-06-01', '核心交换机']
      : ['core-sw-01', 'NET-BJ-001', 'FCW2345L0AB', 'Cisco', 'C9300-48P', 'cisco_ios', '10.0.0.1', '22', 'ssh', 'active', 'switch', 'switch', 'legacy', 'BJ-DC1', 'A-02', '40', '1', '40', '200', 'public', '161', 'user', 'admin', 'normal-password', 'admin-password', '', 'IT Dept', '2023-06-01', 'production', 'Existing production device', '2026-06-01', 'Core switch'];
    const wsNet = XLSX.utils.aoa_to_sheet([netHeaders, netExample]);
    wsNet['!cols'] = netHeaders.map(() => ({ wch: 16 }));
    XLSX.utils.book_append_sheet(wb, wsNet, zh ? '网络设备模板' : 'Network Device Template');

    const optHeaders = zh
      ? ['参数类型 (Field Type)', '标准填写值 (Standard Value)', '值含义说明 (Description)']
      : ['Field Type', 'Standard Value', 'Description'];
    const optRows = zh ? [
      ['录入来源', '新设备', '新采购或新部署设备；导入时强制以待投产状态入库'],
      ['录入来源', '存量设备', '历史运行设备补录；允许填写已投产并登记免上收原因'],
      ['投产状态', '待投产', '尚未完成口令上收'],
      ['投产状态', '已投产', '已完成上收，或存量设备按豁免方式投产'],
      ['资产状态', '在用', '资产正在使用'],
      ['资产状态', '闲置', '资产当前未使用'],
      ['资产状态', '库存中', '资产位于库存'],
      ['连接方式', 'SSH', '通过 SSH 管理设备'],
      ['厂商 (Vendor)', 'Cisco', '思科'],
      ['厂商 (Vendor)', 'Huawei', '华为'],
      ['厂商 (Vendor)', 'H3C', '华三'],
      ['厂商 (Vendor)', 'Arista', '阿里斯塔'],
      ['厂商 (Vendor)', 'Juniper', '瞻博'],
      ['厂商 (Vendor)', 'Ruijie', '锐捷'],
      ['厂商 (Vendor)', 'Fortinet', '飞塔'],
      ['厂商 (Vendor)', 'ZTE', '中兴'],
      ['厂商 (Vendor)', 'Linux', '通用 Linux 服务器'],
      ['厂商 (Vendor)', 'Dell', '戴尔'],
      ['厂商 (Vendor)', 'HP', '惠普'],
      ['厂商 (Vendor)', 'generic', '其它通用厂商'],
      ['平台', 'Cisco IOS', '思科 IOS'],
      ['平台', 'Cisco NX-OS', '思科 Nexus NX-OS'],
      ['平台', 'Cisco IOS-XE', '思科 IOS-XE'],
      ['平台', '华为 VRPv5', '华为 VRP 第五版'],
      ['平台', '华为 VRPv8', '华为 VRP 第八版'],
      ['平台', 'H3C Comware', '新华三 Comware'],
      ['平台', 'Juniper JunOS', '瞻博 JunOS'],
      ['平台', 'Arista EOS', 'Arista EOS'],
      ['平台', '锐捷 RGOS', '锐捷 RGOS'],
      ['平台', 'FortiOS', '飞塔 FortiOS'],
      ['平台', 'Linux（通用）', '通用 Linux 服务器'],
      ['平台 (Platform)', 'ubuntu', 'Ubuntu'],
      ['平台 (Platform)', 'centos', 'CentOS'],
      ['平台 (Platform)', 'debian', 'Debian'],
      ['平台', '红帽 RHEL', 'Red Hat Enterprise Linux'],
      ['平台 (Platform)', 'windows', 'Windows Server'],
      ['平台 (Platform)', 'esxi', 'VMware ESXi'],
      ['服务器分类', '机架式服务器', '标准机架式服务器'],
      ['服务器分类', '刀片服务器', '刀片式服务器'],
      ['服务器分类', '塔式服务器', '塔式服务器'],
      ['服务器分类', '高密度服务器', '高密度计算节点'],
      ['服务器分类', 'GPU服务器', 'GPU 计算服务器'],
      ['服务器分类', '存储服务器', '存储用途服务器'],
      ['服务器分类', '虚拟化宿主机', '虚拟化平台宿主机'],
      ['网络设备分类', '交换机', '网络交换设备'],
      ['网络设备分类', '路由器', '网络路由设备'],
      ['网络设备分类', '防火墙', '安全防护设备'],
      ['网络设备分类', '负载均衡', '负载均衡设备'],
      ['网络设备分类', '无线AP', '无线接入点'],
    ] : [
      ['Asset Origin', 'new', 'New device; always imported as staging'],
      ['Asset Origin', 'legacy', 'Legacy device; may be imported as production with an exemption reason'],
      ['Vendor', 'Cisco', 'Cisco'],
      ['Vendor', 'Huawei', 'Huawei'],
      ['Vendor', 'H3C', 'H3C'],
      ['Vendor', 'Arista', 'Arista'],
      ['Vendor', 'Juniper', 'Juniper'],
      ['Vendor', 'Ruijie', 'Ruijie'],
      ['Vendor', 'Fortinet', 'Fortinet'],
      ['Vendor', 'ZTE', 'ZTE'],
      ['Vendor', 'Linux', 'Linux Server'],
      ['Vendor', 'Dell', 'Dell'],
      ['Vendor', 'HP', 'HP'],
      ['Vendor', 'generic', 'Generic Vendor'],
      ['Platform', 'cisco_ios', 'Cisco IOS'],
      ['Platform', 'cisco_nxos', 'Cisco NX-OS'],
      ['Platform', 'cisco_xe', 'Cisco IOS-XE'],
      ['Platform', 'huawei_vrp', 'Huawei VRPv5'],
      ['Platform', 'huawei_vrpv8', 'Huawei VRPv8'],
      ['Platform', 'hp_comware', 'H3C Comware V5'],
      ['Platform', 'h3c_comware', 'H3C Comware V7'],
      ['Platform', 'h3c_comware9', 'H3C Comware V9'],
      ['Platform', 'juniper_junos', 'Juniper JunOS'],
      ['Platform', 'arista_eos', 'Arista EOS'],
      ['Platform', 'ruijie_os', 'Ruijie RGOS'],
      ['Platform', 'fortinet', 'FortiOS'],
      ['Platform', 'linux', 'Linux (Generic)'],
      ['Platform', 'ubuntu', 'Ubuntu'],
      ['Platform', 'centos', 'CentOS'],
      ['Platform', 'debian', 'Debian'],
      ['Platform', 'redhat', 'Red Hat (RHEL)'],
      ['Platform', 'windows', 'Windows Server'],
      ['Platform', 'esxi', 'VMware ESXi'],
      ['Device Category', 'server', 'Server'],
      ['Device Category', 'network_device', 'Network Device'],
    ];

    const wsOpt = XLSX.utils.aoa_to_sheet([optHeaders, ...optRows]);
    wsOpt['!cols'] = optHeaders.map(() => ({ wch: 25 }));
    XLSX.utils.book_append_sheet(wb, wsOpt, zh ? '参数可选值参考' : 'Option Reference');

    XLSX.writeFile(wb, zh ? '资产导入模板.xlsx' : 'asset_import_template.xlsx');
  };

  const groupedAssets = useMemo<Record<string, Asset[]>>(() => {
    const g: Record<string, Asset[]> = {};
    const keyFn = (a: Asset) => {
      if (groupBy === 'site_id') return a.site_name || a.site_code || a.site_id || (zh ? '未分配站点' : 'Unassigned site');
      if (groupBy === 'department') return a.department || (zh ? '未分配' : 'Unassigned');
      if (groupBy === 'device_category') return a.device_category || typeMeta(a.asset_type).label[zh ? 'zh' : 'en'];
      if (groupBy === 'status') return statusMeta(a.status).label[zh ? 'zh' : 'en'];
      return a.vendor || (zh ? '未知厂商' : 'Unknown');
    };
    displayAssets.forEach(a => { const k = keyFn(a); (g[k] ||= []).push(a); });
    return g;
  }, [displayAssets, groupBy, zh]);

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

  const assetTree = useMemo<AssetTreeNode[]>(() => {
    const roots: AssetTreeNode[] = [];
    const ensureNode = (nodes: AssetTreeNode[], key: string, label: string, kind: AssetTreeNode['kind'], filters: AssetTreeNode['filters'], count: number) => {
      let node = nodes.find(item => item.key === key);
      if (!node) {
        node = { key, label, kind, filters, count: 0, children: [] };
        nodes.push(node);
      }
      node.count += count;
      return node;
    };
    for (const row of assetTreeRows) {
      const typeNode = ensureNode(roots, `type:${row.asset_type}`, typeMeta(row.asset_type).label[zh ? 'zh' : 'en'], 'root', { asset_type: row.asset_type }, row.asset_count);
      const categoryNode = ensureNode(typeNode.children, `${typeNode.key}:category:${row.device_category}`, categoryDisplay({ device_category: row.device_category } as Asset), 'category', { asset_type: row.asset_type, device_category: row.device_category }, row.asset_count);
      const siteNode = ensureNode(categoryNode.children, `${categoryNode.key}:site:${row.site_id}`, row.site_id === 'unassigned' ? (zh ? '未分配站点' : 'Unassigned Site') : row.site_name, 'site', { asset_type: row.asset_type, device_category: row.device_category, site_id: row.site_id === 'unassigned' ? '' : row.site_id }, row.asset_count);
      ensureNode(siteNode.children, `${siteNode.key}:role:${row.device_role}`, row.device_role === 'unassigned' ? (zh ? '未分配角色' : 'Unassigned role') : row.device_role, 'status', { asset_type: row.asset_type, device_category: row.device_category, site_id: row.site_id === 'unassigned' ? '' : row.site_id, device_role: row.device_role === 'unassigned' ? '' : row.device_role }, row.asset_count);
    }
    return roots;
  }, [assetTreeRows, categoryDisplay, zh]);

  const applyTreeFilter = (filters: AssetTreeNode['filters']) => {
    setTypeFilter(filters.asset_type || 'all');
    setDeviceCategoryFilter(filters.device_category || '');
    setDcFilter(filters.site_id || 'all');
    setStatusFilter(filters.status || 'all');
    setPage(1);
    setViewMode('table');
  };

  const renderTreeNode = (node: AssetTreeNode, depth = 0): React.ReactNode => {
    const expanded = depth < 2 || expandedTreeNodes.has(node.key);
    const statusColor = node.kind !== 'status' ? 'bg-cyan-500' : node.label === (zh ? '在线' : 'Online') ? 'bg-emerald-500' : node.label === (zh ? '离线' : 'Offline') ? 'bg-red-500' : 'bg-amber-400';
    return (
      <div key={node.key}>
        <div className="flex items-center gap-1 rounded-lg px-2 py-1.5 hover:bg-cyan-50/70">
          <button type="button" onClick={() => setExpandedTreeNodes(prev => { const next = new Set(prev); next.has(node.key) ? next.delete(node.key) : next.add(node.key); return next; })} className="h-5 w-5 shrink-0 rounded text-black/30 hover:bg-white hover:text-cyan-600" aria-label={expanded ? 'Collapse' : 'Expand'}>
            {node.children.length > 0 ? (expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />) : <span className="block w-3" />}
          </button>
          <button type="button" onClick={() => applyTreeFilter(node.filters)} className="flex min-w-0 flex-1 items-center gap-2 text-left">
            <span className={`h-2 w-2 shrink-0 rounded-full ${statusColor}`} />
            <span className="truncate text-[11px] font-medium text-black/70">{node.label}</span>
            <span className="ml-auto rounded-full bg-black/[0.04] px-1.5 text-[9px] tabular-nums text-black/40">{node.count}</span>
          </button>
        </div>
        {expanded && node.children.length > 0 && <div className="ml-4 border-l border-cyan-100 pl-2">{node.children.map(child => renderTreeNode(child, depth + 1))}</div>}
      </div>
    );
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
      case 'hostname': return <><p className="font-semibold text-[11px] text-black/80 leading-tight truncate max-w-[180px]">{a.hostname || '—'}</p><p className="text-[9px] text-black/20 font-mono truncate">{a.asset_tag || a.management_ip || a.serial_number || ''}</p></>;
      case 'category_role': return <><span className="inline-flex items-center gap-1 text-[10px] text-cyan-600">{a.asset_type === 'server' ? <Server size={9} /> : <Router size={9} />}{typeDisplay(a)}</span><span className="block text-[9px] text-black/35 truncate max-w-[120px]">{categoryDisplay(a)}{a.device_role ? ` / ${a.device_role}` : ''}</span></>;
      case 'site': return <span className="text-[10px] text-black/45 truncate max-w-[100px] block">{a.site_name || a.site_code || a.site_id || '—'}{a.rack && <span className="text-black/25 block text-[9px]">{a.rack}{a.rack_unit ? `U${a.rack_unit}` : ''}</span>}</span>;
      case 'status': return <span className={`inline-flex items-center gap-1 text-[10px] font-medium ${onlineMeta.text}`}><span className={`h-1.5 w-1.5 rounded-full ${onlineMeta.dot}`} />{onlineMeta.label}</span>;
      case 'tags': return a.tags?.length ? <div className="flex flex-wrap items-center gap-1 max-w-[180px]">{a.tags.slice(0, 3).map(tag => <span key={tag.id} className="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[8px] font-medium whitespace-nowrap" style={{ color: tag.color || '#0891b2', backgroundColor: `${tag.color || '#0891b2'}12` }}><span className="h-1 w-1 rounded-full" style={{ backgroundColor: tag.color || '#0891b2' }} />{zh ? (tag.label_zh || tag.label) : tag.label}</span>)}{a.tags.length > 3 && <span className="text-[8px] text-black/25">+{a.tags.length - 3}</span>}</div> : <span className="text-black/15">—</span>;
      case 'vendor': return <span className="text-[10px] text-black/55">{a.vendor || '—'}</span>;
      case 'model': return <span className="text-[10px] text-black/45">{a.model || '—'}</span>;
      case 'serial_number': return <span className="font-mono text-[10px] text-black/50">{a.serial_number || '—'}</span>;
      case 'management_ip': return <span className="font-mono text-[10px] text-black/50">{a.management_ip || '—'}</span>;
      case 'lifecycle': return rotatingAssetId === a.id ? <span className="inline-flex items-center gap-1 text-[10px] font-medium text-cyan-600"><Loader2 size={9} className="animate-spin" />{zh ? '上收中' : 'Rotating'}</span> : <span className={`inline-flex items-center gap-1 text-[10px] font-medium ${a.lifecycle_status === 'production' ? 'text-emerald-600' : a.lifecycle_status === 'decommissioned' ? 'text-slate-400' : a.lifecycle_status === 'maintenance' ? 'text-amber-600' : 'text-blue-500'}`}><span className={`h-1.5 w-1.5 rounded-full ${a.lifecycle_status === 'production' ? 'bg-emerald-500' : a.lifecycle_status === 'decommissioned' ? 'bg-slate-400' : a.lifecycle_status === 'maintenance' ? 'bg-amber-500' : 'bg-blue-400'}`} />{LIFECYCLE_STATUSES.find(l => l.value === a.lifecycle_status)?.label[zh ? 'zh' : 'en'] || (zh ? '待投产' : 'Staging')}</span>;
      case 'created_at': return <span className="text-[10px] text-black/45 tabular-nums">{a.created_at?.replace('T', ' ').slice(0, 19) || '—'}</span>;
      case 'updated_at': return <span className="text-[10px] text-black/45 tabular-nums">{a.updated_at?.replace('T', ' ').slice(0, 19) || '—'}</span>;
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
              {([
                { mode: 'table' as ViewMode, Icon: LayoutList, label: zh ? '表格' : 'Table' },
                { mode: 'tree' as ViewMode, Icon: LayoutGrid, label: zh ? '分组树' : 'Group Tree' },
                { mode: 'topology' as ViewMode, Icon: Network, label: zh ? '拓扑' : 'Topo' },
              ]).map(v => (
                <button
                  key={v.mode} onClick={() => setViewMode(v.mode)}
                  className={`flex items-center gap-1 px-2.5 py-1.5 rounded-md text-[11px] font-medium transition-colors ${viewMode === v.mode ? 'bg-[#00bceb]/10 text-[#0088b0] font-semibold' : 'text-black/30 hover:text-black/50 hover:bg-black/[0.02]'}`}
                >
                  <v.Icon size={12} />{v.label}
                </button>
              ))}
              {viewMode === 'group' && (
                <select
                  value={groupBy} onChange={e => setGroupBy(e.target.value as GroupBy)} title={zh ? '分组依据' : 'Group by'}
                  className="ml-1 text-[10px] px-1.5 py-1 rounded border border-[#00bceb]/20 bg-[#00bceb]/5 text-[#0088b0] font-medium focus:outline-none cursor-pointer"
                >
                  <option value="site_id">{zh ? '站点' : 'Site'}</option>
                  <option value="department">{zh ? '业务/部门' : 'Service'}</option>
                  <option value="vendor">{zh ? '厂商' : 'Vendor'}</option>
                  <option value="device_category">{zh ? '产品类型' : 'Product Type'}</option>
                  <option value="status">{zh ? '在线状态' : 'Online Status'}</option>
                </select>
              )}
            </div>

            <div className="flex items-center gap-1">
              <AnimatePresence>
                {selectedIds.size > 0 && (
                  <motion.div initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 12 }} className="flex items-center gap-0.5 mr-1.5 pr-1.5 border-r border-black/8">
                    <span className="text-[10px] font-bold text-[#00bceb] tabular-nums mr-1">{selectedIds.size}</span>
                    <button onClick={handleBatchTakeover} className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-cyan-500 text-[9px] font-medium hover:bg-cyan-50 hover:text-cyan-600 transition-colors"><Shield size={10} />{zh ? '批量上收' : 'Takeover'}</button>
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

          {viewMode === 'table' && (
            <div className="overflow-x-auto">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="border-b border-black/5 bg-black/[0.008]">
                    <th className="w-7 px-1.5 py-1.5">
                      <input type="checkbox" checked={selectedIds.size === displayAssets.length && displayAssets.length > 0} onChange={toggleAll} className="h-3 w-3 rounded border-black/12 accent-[#00bceb] cursor-pointer" />
                    </th>
                    {activeAssetColumns.map(column => (
                      <th key={column.key} className={`text-left px-1.5 py-1.5 text-[9px] font-bold uppercase tracking-wider text-black/20 ${column.width}`}>
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
                          <td key={column.key} className="px-1.5 py-1">
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
              </table>
            </div>
          )}

          {viewMode === 'tree' && (
            <div className="grid grid-cols-1 gap-3 p-3 lg:grid-cols-[300px_minmax(0,1fr)]">
              <aside className="rounded-xl border border-cyan-100 bg-gradient-to-b from-cyan-50/70 to-white p-3">
                <div className="mb-3 flex items-center justify-between">
                  <div>
                    <p className="text-xs font-bold text-[#164e63]">{zh ? '资产分类树' : 'Asset Classification Tree'}</p>
                    <p className="mt-0.5 text-[9px] text-black/35">{zh ? '类型 → 产品 → 站点 → 在线状态' : 'Type → Product → Site → Online status'}</p>
                  </div>
                  <button type="button" onClick={() => { setTypeFilter('all'); setDeviceCategoryFilter(''); setDcFilter('all'); setStatusFilter('all'); setViewMode('table'); }} className="text-[10px] font-semibold text-cyan-600 hover:underline">{zh ? '全部' : 'All'}</button>
                </div>
                {assetTreeLoading ? <div className="py-8 text-center text-[10px] text-black/30"><RefreshCw size={15} className="mx-auto mb-2 animate-spin" />{zh ? '加载分类…' : 'Loading tree…'}</div> : assetTree.length === 0 ? <div className="py-8 text-center text-[10px] text-black/30">{zh ? '暂无分类数据' : 'No classification data'}</div> : <div className="space-y-0.5">{assetTree.map(node => renderTreeNode(node))}</div>}
              </aside>
              <div className="rounded-xl border border-black/5 bg-white p-4">
                <div className="flex h-full min-h-[260px] items-center justify-center text-center">
                  <div>
                    <LayoutGrid size={28} className="mx-auto mb-2 text-cyan-300" />
                    <p className="text-sm font-semibold text-[#164e63]">{zh ? '选择左侧分类查看资产' : 'Select a category to view assets'}</p>
                    <p className="mt-1 text-[11px] text-black/35">{zh ? '点击任意节点会自动切换到资产列表并应用筛选条件。' : 'Click any node to open the asset table with its filters applied.'}</p>
                  </div>
                </div>
              </div>
            </div>
          )}

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
