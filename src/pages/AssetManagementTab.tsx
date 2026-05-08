import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Terminal as XTerm } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import 'xterm/css/xterm.css';
import {
  Package, Plus, Trash2, Search, X, RefreshCw, Download, Pencil, Copy,
  Server, Router, ChevronLeft, ChevronRight,
  AlertTriangle, Network, SlidersHorizontal,
  ExternalLink, Wifi, Building2, Upload,
  FileText, ChevronDown, ChevronUp,
  Zap, AlertCircle, CheckCircle2, Tag, Info,
  Flame, LayoutList, LayoutGrid,
  Lock, Terminal, Eye, EyeOff, Loader2, Shield, User, MonitorSpeaker, Check,
} from 'lucide-react';
import * as XLSX from 'xlsx';
import { AnimatePresence, motion } from 'motion/react';
import DateTimePicker from '../components/DateTimePicker';
import Pagination from '../components/Pagination';
import { fetchAllPaginatedItems } from '../utils/pagination';
import { AssetReadonlyDetailInner } from '../components/AssetReadonlyDetail';

/* ═══════════════════════════════════════════════════════════════════
   Types
   ═══════════════════════════════════════════════════════════════════ */

interface Asset {
  id: string; asset_type: string; asset_tag: string; serial_number: string;
  vendor: string; model: string; hostname: string; datacenter: string;
  rack: string; rack_unit: string;
  u_height?: number;
  planned_start_u?: number | null;
  management_ip: string; business_ip: string;
  device_role: string; vlan: string; uplink_switch: string; uplink_port: string;
  status: string; lifecycle_status: string; purchase_date: string;
  warranty_expiry: string; department: string; notes: string;
  platform: string; connection_method: string; username: string;
  snmp_community: string; snmp_port: string;
  created_at: string; updated_at: string;
  admin_username?: string;
  normal_username?: string;
}

interface AssetSummary {
  total: number;
  by_type: Record<string, number>;
  by_status: Record<string, number>;
  by_vendor: Record<string, number>;
  by_datacenter: Record<string, number>;
  by_department: Record<string, number>;
  warranty_expiring_soon: number;
}

interface Props {
  language: string;
  t: (key: string) => string;
  setActiveTab?: (tab: string) => void;
}

/* ═══════════════════════════════════════════════════════════════════
   Constants
   ═══════════════════════════════════════════════════════════════════ */

const STATUSES = [
  { value: 'active',         label: { zh: '在用', en: 'In Use' },        dot: 'bg-emerald-500', badge: 'bg-emerald-50 text-emerald-700', text: 'text-emerald-600' },
  { value: 'inactive',       label: { zh: '闲置', en: 'Idle' },          dot: 'bg-sky-400',     badge: 'bg-sky-50 text-sky-600',         text: 'text-sky-500' },
  { value: 'in_storage',     label: { zh: '库存中', en: 'In Storage' },  dot: 'bg-blue-400',    badge: 'bg-blue-50 text-blue-600',       text: 'text-blue-500' },
  { value: 'maintenance',    label: { zh: '维护中', en: 'Maintenance' }, dot: 'bg-amber-500',   badge: 'bg-amber-50 text-amber-700',     text: 'text-amber-600' },
  { value: 'decommissioned', label: { zh: '已退役', en: 'Retired' },     dot: 'bg-slate-400',   badge: 'bg-slate-100 text-slate-500',    text: 'text-slate-400' },
] as const;

const TYPES = [
  { value: 'server',         label: { zh: '服务器', en: 'Server' },    icon: Server },
  { value: 'network_device', label: { zh: '网络设备', en: 'Network' }, icon: Router },
] as const;

const LIFECYCLE_STATUSES = [
  { value: 'staging',        label: { zh: '待投产', en: 'Staging' } },
  { value: 'production',     label: { zh: '已投产', en: 'Production' } },
  { value: 'maintenance',    label: { zh: '维护中', en: 'Maintenance' } },
  { value: 'decommissioned', label: { zh: '已退役', en: 'Decommissioned' } },
] as const;

type ViewMode = 'table' | 'group' | 'topology';
type GroupBy = 'datacenter' | 'department' | 'vendor';

const EMPTY_FORM = {
  asset_type: 'server', asset_tag: '', serial_number: '', vendor: '', model: '',
  hostname: '', datacenter: '', rack: '', rack_unit: '', u_height: '1', planned_start_u: '', management_ip: '',
  business_ip: '', device_role: '', vlan: '', uplink_switch: '', uplink_port: '',
  status: 'active', lifecycle_status: 'staging', purchase_date: '', warranty_expiry: '', department: '', notes: '',
  // network_device specific
  platform: '', connection_method: 'ssh', 
  username: '', password: '',
  normal_username: '', normal_password: '',
  admin_username: '', admin_password: '',
  auth_model: 'single',
  snmp_community: 'public', snmp_port: '161',
};

const VENDOR_PLATFORMS: Record<string, { value: string; label: string }[]> = {
  Cisco:      [{ value: 'cisco_ios', label: 'Cisco IOS' }, { value: 'cisco_nxos', label: 'Cisco NX-OS' }, { value: 'cisco_xe', label: 'Cisco IOS-XE' }],
  Huawei:     [{ value: 'huawei_vrp', label: 'Huawei VRP' }],
  H3C:        [{ value: 'hp_comware', label: 'H3C Comware' }],
  Arista:     [{ value: 'arista_eos', label: 'Arista EOS' }],
  Juniper:    [{ value: 'juniper_junos', label: 'Juniper JunOS' }],
  Ruijie:     [{ value: 'ruijie_os', label: 'Ruijie RGOS' }],
  Fortinet:   [{ value: 'fortinet', label: 'FortiOS' }],
  'Palo Alto':[{ value: 'paloalto_panos', label: 'PAN-OS' }],
  ZTE:        [{ value: 'zte_zxros', label: 'ZTE ZXROS' }],
};

const SERVER_PLATFORMS = [
  { value: 'linux',   label: 'Linux (Generic)' },
  { value: 'ubuntu',  label: 'Ubuntu' },
  { value: 'centos',  label: 'CentOS' },
  { value: 'debian',  label: 'Debian' },
  { value: 'redhat',  label: 'Red Hat (RHEL)' },
  { value: 'windows', label: 'Windows Server' },
  { value: 'esxi',    label: 'VMware ESXi' },
];

const ALL_PLATFORMS = [...Object.values(VENDOR_PLATFORMS).flat(), ...SERVER_PLATFORMS];

/* ═══════════════════════════════════════════════════════════════════
   Helpers
   ═══════════════════════════════════════════════════════════════════ */

const statusMeta = (v: string) => STATUSES.find(s => s.value === v) || STATUSES[3];
const typeMeta   = (v: string) => TYPES.find(t => t.value === v) || TYPES[0];

const ago = (iso: string) => {
  if (!iso) return '—';
  const ms = Date.now() - new Date(iso).getTime();
  const m = Math.floor(ms / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return `${Math.floor(d / 30)}mo`;
};

/** Map status to severity for P1-P4 classification */
const severityOf = (a: Asset): 'critical' | 'major' | 'warning' | 'healthy' => {
  if (a.status === 'decommissioned') return 'critical';
  if (a.status === 'maintenance') return 'major';
  if (a.warranty_expiry && new Date(a.warranty_expiry) <= new Date(Date.now() + 90 * 86400000)) return 'warning';
  if (a.status === 'inactive' || a.status === 'in_storage') return 'warning';
  return 'healthy';
};

/* ═══════════════════════════════════════════════════════════════════
   Main Component
   ═══════════════════════════════════════════════════════════════════ */

const AssetManagementTab: React.FC<Props> = ({ language, setActiveTab }) => {
  const zh = language === 'zh';
  const goTo = (tab: string) => setActiveTab?.(tab);

  /* ─── State ─── */
  const [assets, setAssets]             = useState<Asset[]>([]);
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

  const [feedbackMsg, setFeedbackMsg] = useState<{ type: 'success' | 'error' | 'warning' | 'info'; text: string } | null>(null);
  const [deptFilter, setDeptFilter]     = useState('all');
  const [severityFilter, setSeverityFilter] = useState<string>('all');
  const [lifecycleFilter, setLifecycleFilter] = useState('all');

  const [viewMode, setViewMode]         = useState<ViewMode>('table');
  const [groupBy, setGroupBy]           = useState<GroupBy>('datacenter');
  const [selectedIds, setSelectedIds]   = useState<Set<string>>(new Set());
  const [drawerAsset, setDrawerAsset]   = useState<Asset | null>(null);

  const [showModal, setShowModal]       = useState(false);
  const [editingAsset, setEditingAsset] = useState<Asset | null>(null);
  const [form, setForm]                 = useState({ ...EMPTY_FORM });
  const [saving, setSaving]             = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Asset | null>(null);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [showBatchTag, setShowBatchTag] = useState(false);
  const [batchTagValue, setBatchTagValue] = useState('');
  const [showProductionConfirm, setShowProductionConfirm] = useState(false);
  const [modalError, setModalError] = useState<string | null>(null);
  const [showAdvancedFilter, setShowAdvancedFilter] = useState(false);
  const [rotatingAssetId, setRotatingAssetId] = useState<string | null>(null);
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const rotationPollRef = React.useRef<any>(null);

  /* Cleanup rotation polling on unmount */
  useEffect(() => () => { if (rotationPollRef.current) clearInterval(rotationPollRef.current); }, []);

  /* ─── Data Fetching ─── */
  const fetchSummary = useCallback(async () => {
    try { const r = await fetch('/api/assets/summary'); if (r.ok) setSummary(await r.json()); } catch { /* noop */ }
  }, []);

  const fetchAssets = useCallback(async () => {
    setLoading(true);
    try {
      const p = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
      if (search.trim()) p.set('q', search.trim());
      if (typeFilter !== 'all')   p.set('asset_type', typeFilter);
      if (statusFilter !== 'all') p.set('status', statusFilter);
      if (vendorFilter !== 'all') p.set('vendor', vendorFilter);
      if (dcFilter !== 'all')     p.set('datacenter', dcFilter);
      if (deptFilter !== 'all')   p.set('department', deptFilter);
      const r = await fetch(`/api/assets?${p}`);
      if (r.ok) { const d = await r.json(); setAssets(d.items); setTotal(d.total); }
    } catch { /* noop */ }
    setLoading(false);
  }, [page, pageSize, search, typeFilter, statusFilter, vendorFilter, dcFilter, deptFilter]);

  useEffect(() => { fetchSummary(); }, [fetchSummary]);
  useEffect(() => { fetchAssets(); }, [fetchAssets]);
  useEffect(() => { setPage(1); }, [search, typeFilter, statusFilter, vendorFilter, dcFilter, deptFilter, pageSize]);

  /* ESC key to close drawer */
  useEffect(() => {
    if (!drawerAsset) return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setDrawerAsset(null); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [drawerAsset]);

  /* Auto-dismiss feedback toast (skip while rotation is polling) */
  useEffect(() => {
    if (!feedbackMsg) return;
    if (rotatingAssetId) return; // Don't auto-dismiss during rotation polling
    const t = setTimeout(() => setFeedbackMsg(null), feedbackMsg.type === 'error' ? 8000 : 5000);
    return () => clearTimeout(t);
  }, [feedbackMsg, rotatingAssetId]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const vendorList = useMemo(() => summary?.by_vendor ? Object.keys(summary.by_vendor).sort() : [], [summary]);
  const dcList     = useMemo(() => summary?.by_datacenter ? Object.keys(summary.by_datacenter).sort() : [], [summary]);
  const deptList   = useMemo(() => summary?.by_department ? Object.keys(summary.by_department).sort() : [], [summary]);

  /* ─── Severity metrics ─── */
  const severityCounts = useMemo(() => {
    const c = { critical: 0, major: 0, warning: 0, healthy: 0 };
    assets.forEach(a => { c[severityOf(a)]++; });
    return c;
  }, [assets]);

  /* Filtered assets by severity card click + lifecycle filter */
  const displayAssets = useMemo(() => {
    let result = assets;
    if (severityFilter !== 'all') result = result.filter(a => severityOf(a) === severityFilter);
    if (lifecycleFilter !== 'all') result = result.filter(a => (a.lifecycle_status || 'staging') === lifecycleFilter);
    return result;
  }, [assets, severityFilter, lifecycleFilter]);

  /* ─── CRUD ─── */
  const openAdd = () => { setEditingAsset(null); setForm({ ...EMPTY_FORM }); setModalError(null); setShowModal(true); };
  const openEdit = (a: Asset) => {
    setEditingAsset(a);
    setModalError(null);
    setForm({
      asset_type: a.asset_type, asset_tag: a.asset_tag, serial_number: a.serial_number,
      vendor: a.vendor, model: a.model, hostname: a.hostname, datacenter: a.datacenter,
      rack: a.rack, rack_unit: a.rack_unit,
      u_height: String(a.u_height ?? 1),
      planned_start_u: a.planned_start_u != null && a.planned_start_u !== undefined ? String(a.planned_start_u) : '',
      management_ip: a.management_ip,
      business_ip: a.business_ip, device_role: a.device_role,
      vlan: a.vlan || '', uplink_switch: a.uplink_switch || '', uplink_port: a.uplink_port || '',
      status: a.status, lifecycle_status: a.lifecycle_status || 'staging',
      purchase_date: a.purchase_date, warranty_expiry: a.warranty_expiry,
      department: a.department, notes: a.notes,
      platform: (a as any).platform || 'cisco_ios',
      connection_method: (a as any).connection_method || 'ssh',
      username: (a as any).username || '',
      password: '',
      normal_username: (a as any).normal_username || '',
      normal_password: '',
      admin_username: (a as any).admin_username || '',
      admin_password: '',
      auth_model: (a as any).auth_model || 'single',
      snmp_community: (a as any).snmp_community || 'public',
      snmp_port: String((a as any).snmp_port || '161'),
    });
    setShowModal(true);
  };

  const handleSave = async () => {
    if (!form.hostname.trim() && !form.asset_tag.trim()) return;

    // Detect production transition → show confirmation first
    const oldLifecycle = editingAsset ? (editingAsset.lifecycle_status || 'staging') : 'staging';
    if (editingAsset && form.lifecycle_status === 'production' && oldLifecycle !== 'production') {
      setShowProductionConfirm(true);
      return;
    }

    await doSave();
  };

  const startRotationPoll = useCallback((assetId: string) => {
    if (rotationPollRef.current) clearInterval(rotationPollRef.current);
    setRotatingAssetId(assetId);
    setFeedbackMsg({ type: 'info', text: zh ? '⏳ 口令上收中，请稍候...' : '⏳ Rotating password, please wait...' });
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

  const doSave = async () => {
    setSaving(true);
    try {
      const url = editingAsset ? `/api/assets/${editingAsset.id}` : '/api/assets';
      const plannedRaw = String(form.planned_start_u ?? '').trim();
      let planned_start_u: number | null = null;
      if (plannedRaw) {
        const n = parseInt(plannedRaw, 10);
        if (!Number.isNaN(n) && n >= 1 && n <= 60) planned_start_u = n;
      }
      const payload = {
        ...form,
        u_height: Math.max(1, Math.min(60, parseInt(String(form.u_height), 10) || 1)),
        planned_start_u,
      };
      const r = await fetch(url, { method: editingAsset ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      if (r.ok) {
        const data = await r.json().catch(() => null);
        setShowModal(false);
        setShowProductionConfirm(false);
        fetchAssets();
        fetchSummary();
        // Async rotation → start polling
        if (data?.rotation_pending && editingAsset) {
          startRotationPoll(editingAsset.id);
        } else if (data?.password_rotated) {
          setFeedbackMsg({ type: 'success', text: zh ? '已投产，默认口令已自动修改上收。' : 'Marked as production. Default password has been auto-rotated.' });
        } else if (data?.lifecycle_reverted && data?.rotation_detail) {
          setFeedbackMsg({ type: 'warning', text: zh ? `口令自动轮换失败，投产已回滚: ${data.rotation_detail}` : `Auto-rotation failed, production transition reverted: ${data.rotation_detail}` });
          fetchAssets();
        } else if (data?.rotation_detail) {
          setFeedbackMsg({ type: 'warning', text: zh ? `已投产，但口令自动轮换失败: ${data.rotation_detail}` : `Marked as production, but auto-rotation failed: ${data.rotation_detail}` });
        }
      } else if (r.status === 422) {
        const err = await r.json().catch(() => null);
        setShowProductionConfirm(false);
        setModalError(zh ? (err?.detail || '前置校验未通过') : (err?.detail || 'Pre-flight check failed'));
      } else {
        const err = await r.json().catch(() => null);
        setFeedbackMsg({ type: 'error', text: zh ? `保存失败: ${err?.detail || r.statusText}` : `Save failed: ${err?.detail || r.statusText}` });
      }
    } catch (e) { setFeedbackMsg({ type: 'error', text: zh ? `网络错误: ${e}` : `Network error: ${e}` }); }
    setSaving(false);
  };

  const openCopy = (a: Asset) => {
    setEditingAsset(null);
    const copyTag = a.asset_tag ? `${a.asset_tag}-${Date.now().toString(36).slice(-4)}` : '';
    setForm({
      asset_type: a.asset_type, asset_tag: copyTag, serial_number: '',
      vendor: a.vendor, model: a.model, hostname: '', datacenter: a.datacenter,
      rack: a.rack, rack_unit: '', u_height: String(a.u_height ?? 1), planned_start_u: a.planned_start_u != null ? String(a.planned_start_u) : '', management_ip: '',
      business_ip: '', device_role: a.device_role,
      vlan: a.vlan || '', uplink_switch: a.uplink_switch || '', uplink_port: a.uplink_port || '',
      status: a.status, lifecycle_status: 'staging',
      purchase_date: a.purchase_date, warranty_expiry: a.warranty_expiry,
      department: a.department, notes: a.notes,
      platform: a.platform || 'cisco_ios',
      connection_method: a.connection_method || 'ssh',
      username: a.username || '',
      password: '',
      normal_username: (a as any).normal_username || '',
      normal_password: '',
      admin_username: (a as any).admin_username || '',
      admin_password: '',
      auth_model: (a as any).auth_model || 'single',
      snmp_community: a.snmp_community || 'public',
      snmp_port: String(a.snmp_port || '161'),
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

  /* ─── Selection & Batch ─── */
  const toggle    = (id: string) => setSelectedIds(p => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const toggleAll = () => setSelectedIds(p => p.size === displayAssets.length ? new Set() : new Set(displayAssets.map(a => a.id)));
  const clearSel  = () => setSelectedIds(new Set());

  const batchTag = async () => {
    if (!batchTagValue.trim()) return;
    const promises = Array.from(selectedIds).map(id =>
      fetch(`/api/assets/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ notes: batchTagValue.trim() }) })
    );
    await Promise.allSettled(promises);
    setShowBatchTag(false);
    setBatchTagValue('');
    clearSel();
    fetchAssets();
  };

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
          ticket_id: approvalData.ticket, // Pass ticket if admin
          mfa_code: approvalData.mfa     // Pass MFA if admin
        }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        setFeedbackMsg({ type: 'error', text: (data?.detail || (zh ? '申请失败' : 'Request failed')) as string });
        return;
      }

      if (data.status === 'approved' || (terminalAccessLevel === 'admin' && isApproved)) {
        // Auto-approve if needed (logic matches backend expectations)
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

  /* ─── Export ─── */
  const handleExport = async () => {
    const params = new URLSearchParams({ page: '1', page_size: '200' });
    if (search.trim()) params.set('q', search.trim());
    if (typeFilter !== 'all') params.set('asset_type', typeFilter);
    if (statusFilter !== 'all') params.set('status', statusFilter);
    if (vendorFilter !== 'all') params.set('vendor', vendorFilter);
    if (dcFilter !== 'all') params.set('datacenter', dcFilter);
    if (deptFilter !== 'all') params.set('department', deptFilter);

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
        [zh ? '管理IP' : 'Mgmt IP']: a.management_ip,
        [zh ? '业务IP' : 'Business IP']: a.business_ip,
        [zh ? '状态' : 'Status']: a.status,
        [zh ? '角色' : 'Role']: a.device_role,
        [zh ? 'VLAN' : 'VLAN']: a.vlan,
        [zh ? '上联交换机' : 'Uplink Switch']: a.uplink_switch,
        [zh ? '上联端口' : 'Uplink Port']: a.uplink_port,
        [zh ? '数据中心' : 'Datacenter']: a.datacenter,
        [zh ? '机柜' : 'Rack']: a.rack,
        [zh ? 'U位' : 'Rack Unit']: a.rack_unit,
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
    } catch (error) {
      console.error('Failed to export assets:', error);
    }
  };

  /* ─── Import ─── */
  const COL_MAP: Record<string, string> = {
    '主机名': 'hostname', 'Hostname': 'hostname', 'hostname': 'hostname',
    '资产编号': 'asset_tag', 'Asset Tag': 'asset_tag', 'asset_tag': 'asset_tag', 'Tag': 'asset_tag',
    '序列号': 'serial_number', 'Serial Number': 'serial_number', 'serial_number': 'serial_number',
    '类型': 'asset_type', 'Type': 'asset_type', 'asset_type': 'asset_type',
    '厂商': 'vendor', 'Vendor': 'vendor', 'vendor': 'vendor',
    '型号': 'model', 'Model': 'model', 'model': 'model',
    '管理IP': 'management_ip', 'Mgmt IP': 'management_ip', 'management_ip': 'management_ip',
    '业务IP': 'business_ip', 'Business IP': 'business_ip', 'business_ip': 'business_ip',
    '状态': 'status', 'Status': 'status', 'status': 'status',
    '角色': 'device_role', 'Role': 'device_role', 'device_role': 'device_role',
    '数据中心': 'datacenter', 'Datacenter': 'datacenter', 'DC': 'datacenter', 'datacenter': 'datacenter',
    '机柜': 'rack', 'Rack': 'rack', 'rack': 'rack',
    'U位': 'rack_unit', 'Rack Unit': 'rack_unit', 'rack_unit': 'rack_unit',
    '部门': 'department', 'Department': 'department', 'Dept': 'department', 'department': 'department',
    '购买日期': 'purchase_date', 'Purchase Date': 'purchase_date', 'purchase_date': 'purchase_date',
    '保修到期': 'warranty_expiry', 'Warranty Expiry': 'warranty_expiry', 'warranty_expiry': 'warranty_expiry',
    '备注': 'notes', 'Notes': 'notes', 'notes': 'notes',
    'VLAN': 'vlan', 'vlan': 'vlan',
    '上联交换机': 'uplink_switch', 'Uplink Switch': 'uplink_switch', 'uplink_switch': 'uplink_switch',
    '上联端口': 'uplink_port', 'Uplink Port': 'uplink_port', 'uplink_port': 'uplink_port',
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
        for (const name of wb.SheetNames) {
          const ws = wb.Sheets[name];
          const raw = XLSX.utils.sheet_to_json<Record<string, string>>(ws, { defval: '' });
          const isNet = NET_SHEET.test(name);
          for (const row of raw) {
            const obj: Record<string, string> = {};
            for (const [col, val] of Object.entries(row)) {
              const key = COL_MAP[col.trim()];
             if (key) {
               let mappedVal = String(val).trim();
               if (key === 'asset_type') {
                 const v = mappedVal.toLowerCase();
                 if (v.includes('server') || v.includes('服务器')) mappedVal = 'server';
                 else if (v.includes('network') || v.includes('网络') || v.includes('switch') || v.includes('router')) mappedVal = 'network_device';
               }
               obj[key] = mappedVal;
             }
           }
           if (!obj.asset_type) obj.asset_type = isNet ? 'network_device' : 'server';
            if (obj.hostname || obj.asset_tag) mapped.push(obj);
          }
        }
        if (!mapped.length) { setFeedbackMsg({ type: 'error', text: zh ? '未找到有效数据行（需包含主机名或资产编号列）' : 'No valid rows found (need Hostname or Asset Tag column)' }); return; }
        const r = await fetch('/api/assets/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(mapped) });
        if (r.ok) {
          const res = await r.json();
          setFeedbackMsg({ type: 'success', text: zh ? `导入完成：新增 ${res.created} 条，跳过 ${res.skipped} 条` : `Import done: ${res.created} created, ${res.skipped} skipped` });
          fetchAssets(); fetchSummary();
        } else {
          setFeedbackMsg({ type: 'error', text: zh ? '导入失败，请检查文件格式' : 'Import failed, please check file format' });
        }
      } catch { setFeedbackMsg({ type: 'error', text: zh ? '文件解析失败' : 'Failed to parse file' }); }
    };
    reader.readAsArrayBuffer(file);
    e.target.value = '';
  };

  /* ─── Download Import Template ─── */
  const handleDownloadTemplate = () => {
    const wb = XLSX.utils.book_new();

    // ── 服务器模板 ──
    const srvHeaders = zh
      ? ['主机名', '资产编号', '序列号', '厂商', '型号', '管理IP', '业务IP', 'VLAN', '上联交换机', '上联端口', '状态', '角色', '数据中心', '机柜', 'U位', '部门', '购买日期', '保修到期', '备注']
      : ['Hostname', 'Asset Tag', 'Serial Number', 'Vendor', 'Model', 'Mgmt IP', 'Business IP', 'VLAN', 'Uplink Switch', 'Uplink Port', 'Status', 'Role', 'Datacenter', 'Rack', 'Rack Unit', 'Department', 'Purchase Date', 'Warranty Expiry', 'Notes'];
    const srvExample = zh
      ? ['web-srv-01', 'SRV-BJ-001', 'CZJ2345G0HN', 'Dell', 'PowerEdge R750', '10.0.1.10', '192.168.1.10', 'VLAN100', 'core-sw-01', 'Gi0/1', 'active', 'web', 'BJ-DC1', 'A-01', '12', '网络部', '2024-01-15', '2027-01-15', '生产服务器']
      : ['web-srv-01', 'SRV-BJ-001', 'CZJ2345G0HN', 'Dell', 'PowerEdge R750', '10.0.1.10', '192.168.1.10', 'VLAN100', 'core-sw-01', 'Gi0/1', 'active', 'web', 'BJ-DC1', 'A-01', '12', 'IT Dept', '2024-01-15', '2027-01-15', 'Production server'];
    const wsSrv = XLSX.utils.aoa_to_sheet([srvHeaders, srvExample]);
    wsSrv['!cols'] = srvHeaders.map(() => ({ wch: 16 }));
    XLSX.utils.book_append_sheet(wb, wsSrv, zh ? '服务器模板' : 'Server Template');

    // ── 网络设备模板 ──
    const netHeaders = zh
      ? ['主机名', '资产编号', '序列号', '厂商', '型号', '管理IP', '状态', '角色', '数据中心', '机柜', 'U位', '部门', '购买日期', '保修到期', '备注']
      : ['Hostname', 'Asset Tag', 'Serial Number', 'Vendor', 'Model', 'Mgmt IP', 'Status', 'Role', 'Datacenter', 'Rack', 'Rack Unit', 'Department', 'Purchase Date', 'Warranty Expiry', 'Notes'];
    const netExample = zh
      ? ['core-sw-01', 'NET-BJ-001', 'FCW2345L0AB', 'Cisco', 'C9300-48P', '10.0.0.1', 'active', 'switch', 'BJ-DC1', 'A-02', '40', '网络部', '2023-06-01', '2026-06-01', '核心交换机']
      : ['core-sw-01', 'NET-BJ-001', 'FCW2345L0AB', 'Cisco', 'C9300-48P', '10.0.0.1', 'active', 'switch', 'BJ-DC1', 'A-02', '40', 'IT Dept', '2023-06-01', '2026-06-01', 'Core switch'];
    const wsNet = XLSX.utils.aoa_to_sheet([netHeaders, netExample]);
    wsNet['!cols'] = netHeaders.map(() => ({ wch: 16 }));
    XLSX.utils.book_append_sheet(wb, wsNet, zh ? '网络设备模板' : 'Network Device Template');

    XLSX.writeFile(wb, zh ? '资产导入模板.xlsx' : 'asset_import_template.xlsx');
  };

  /* ─── Computed ─── */
  const byStatus = summary?.by_status ?? {};
  const criticalCount  = (byStatus['inactive'] ?? 0);
  const majorCount     = (byStatus['maintenance'] ?? 0);
  const warningCount   = summary?.warranty_expiring_soon ?? 0;
  const healthyCount   = byStatus['active'] ?? 0;
  const totalCount     = summary
    ? (summary.by_type?.network_device ?? 0) + (summary.by_type?.server ?? 0)
    : 0;

  const groupedAssets = useMemo<Record<string, Asset[]>>(() => {
    const g: Record<string, Asset[]> = {};
    const keyFn = (a: Asset) => {
      if (groupBy === 'datacenter') return a.datacenter || (zh ? '未分配' : 'Unassigned');
      if (groupBy === 'department') return a.department || (zh ? '未分配' : 'Unassigned');
      return a.vendor || (zh ? '未知厂商' : 'Unknown');
    };
    displayAssets.forEach(a => { const k = keyFn(a); (g[k] ||= []).push(a); });
    return g;
  }, [displayAssets, groupBy, zh]);

  const typeDisplay = (a: Asset) => {
    if (a.asset_type === 'network_device' && a.device_role) return a.device_role.charAt(0).toUpperCase() + a.device_role.slice(1);
    return typeMeta(a.asset_type).label[zh ? 'zh' : 'en'];
  };

  const hasFilters = typeFilter !== 'all' || statusFilter !== 'all' || vendorFilter !== 'all' || dcFilter !== 'all' || deptFilter !== 'all' || lifecycleFilter !== 'all';
  const advancedFilterCount = [vendorFilter, dcFilter, deptFilter, lifecycleFilter].filter(f => f !== 'all').length;
  const clearAllFilters = () => { setTypeFilter('all'); setStatusFilter('all'); setVendorFilter('all'); setDcFilter('all'); setDeptFilter('all'); setSeverityFilter('all'); setLifecycleFilter('all'); };

  /* ═══════════════════════════════════════════════════════════════════
     RENDER
     ═══════════════════════════════════════════════════════════════════ */
  return (
    <div className="space-y-2.5">
      {/* Hidden file input for Excel import */}
      <input ref={fileInputRef} type="file" accept=".xlsx,.xls,.csv" className="hidden" onChange={handleImport} />

      {/* ══════════════════ FEEDBACK TOAST ══════════════════ */}
      <AnimatePresence>
        {feedbackMsg && (
          <motion.div
            initial={{ opacity: 0, y: -12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: 0.25 }}
            className={`flex items-center gap-3 px-4 py-3 rounded-xl border shadow-lg backdrop-blur-sm ${
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
            <span className="text-sm font-medium flex-1">{feedbackMsg.text}</span>
            <button onClick={() => setFeedbackMsg(null)} className="p-0.5 rounded-md hover:bg-black/5 transition-colors">
              <X size={14} />
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ══════════════════ SEVERITY CARDS (P1–P4) ══════════════════ */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
        {([
          { key: 'critical', value: criticalCount, label: zh ? '严重故障' : 'Critical', sub: 'P1', Icon: Flame,
            gradient: 'from-red-600 to-red-700', filterVal: 'critical' as string, pulse: true },
          { key: 'major', value: majorCount, label: zh ? '重要问题' : 'Major Issues', sub: 'P2', Icon: AlertTriangle,
            gradient: 'from-orange-600 to-orange-700', filterVal: 'major' as string },
          { key: 'warning', value: warningCount, label: zh ? '需要关注' : 'Warning', sub: 'P3', Icon: AlertCircle,
            gradient: 'from-amber-600 to-amber-700', filterVal: 'warning' as string },
          { key: 'healthy', value: healthyCount, label: zh ? '运行正常' : 'Healthy', sub: zh ? '正常' : 'OK', Icon: CheckCircle2,
            gradient: 'from-emerald-600 to-emerald-700', filterVal: 'healthy' as string },
        ]).map(c => {
          const isActive = severityFilter === c.filterVal;
          const isEmpty = c.value === 0;
          return (
            <button
              key={c.key}
              onClick={() => setSeverityFilter(isActive ? 'all' : c.filterVal)}
              className={`group relative rounded-xl overflow-hidden transition-all hover:shadow-md hover:scale-[1.01] active:scale-[0.99]
                bg-gradient-to-br ${c.gradient} ${isEmpty ? 'opacity-60' : ''}
                ${isActive ? 'ring-2 ring-white/30 shadow-lg' : 'shadow-sm'}`}
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
                  <c.Icon size={16} className={`text-white/70 ${!isEmpty && c.pulse ? 'animate-pulse' : ''}`} />
                </div>
              </div>
              {isActive && <div className="absolute bottom-0 left-0 right-0 h-1 bg-white/20" />}
            </button>
          );
        })}
      </div>

      {/* ══════════════════ CONSOLE PANEL ══════════════════ */}
      <div className="bg-white rounded-xl border border-black/5 shadow-sm overflow-hidden">

        {/* ── Header: View tabs + batch + actions ── */}
        <div className="flex items-center justify-between px-3 py-1.5 border-b border-black/5 bg-black/[0.008]">
          {/* Left: views + groupBy selector */}
          <div className="flex items-center gap-0.5">
            {([
              { mode: 'table' as ViewMode, Icon: LayoutList, label: zh ? '表格' : 'Table' },
              { mode: 'group' as ViewMode, Icon: LayoutGrid, label: zh ? '分组' : 'Group' },
              { mode: 'topology' as ViewMode, Icon: Network, label: zh ? '拓扑' : 'Topo' },
            ]).map(v => (
              <button
                key={v.mode} onClick={() => setViewMode(v.mode)}
                className={`flex items-center gap-1 px-2.5 py-1.5 rounded-md text-[11px] font-medium transition-colors ${
                  viewMode === v.mode ? 'bg-[#00bceb]/10 text-[#0088b0] font-semibold' : 'text-black/30 hover:text-black/50 hover:bg-black/[0.02]'
                }`}
              >
                <v.Icon size={12} />{v.label}
              </button>
            ))}
            {viewMode === 'group' && (
              <select
                value={groupBy} onChange={e => setGroupBy(e.target.value as GroupBy)} title={zh ? '分组依据' : 'Group by'}
                className="ml-1 text-[10px] px-1.5 py-1 rounded border border-[#00bceb]/20 bg-[#00bceb]/5 text-[#0088b0] font-medium focus:outline-none cursor-pointer"
              >
                <option value="datacenter">{zh ? '机房' : 'Data Center'}</option>
                <option value="department">{zh ? '业务/部门' : 'Service'}</option>
                <option value="vendor">{zh ? '厂商' : 'Vendor'}</option>
              </select>
            )}
          </div>

          {/* Right: batch bar + utility buttons */}
          <div className="flex items-center gap-1">
            {/* Batch operations */}
            <AnimatePresence>
              {selectedIds.size > 0 && (
                <motion.div initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 12 }} className="flex items-center gap-0.5 mr-1.5 pr-1.5 border-r border-black/8">
                  <span className="text-[10px] font-bold text-[#00bceb] tabular-nums mr-1">{selectedIds.size}</span>
                  <BatchBtn icon={Tag}       label={zh ? '标签' : 'Tag'}     onClick={() => setShowBatchTag(true)} hoverCls="hover:bg-blue-50 hover:text-blue-600" />
                  <BatchBtn icon={Trash2}    label={zh ? '删除' : 'Delete'}  onClick={handleBatchDelete} hoverCls="hover:bg-red-50 hover:text-red-600" />
                  <button onClick={clearSel} className="p-0.5 ml-0.5 text-black/20 hover:text-black/45" title="Clear"><X size={10} /></button>
                </motion.div>
              )}
            </AnimatePresence>

            <button onClick={openAdd} className="flex items-center gap-1 px-2 py-1 rounded-md bg-[#00bceb] text-white text-[11px] font-semibold hover:bg-[#00a5d0] shadow-sm shadow-[#00bceb]/20" title={zh ? '新增资产' : 'Add Asset'}><Plus size={13} /><span className="hidden sm:inline">{zh ? '新增' : 'Add'}</span></button>
            <button onClick={() => { fetchAssets(); fetchSummary(); }} className="p-1.5 rounded-md text-black/20 hover:text-[#00bceb] hover:bg-[#00bceb]/5" title={zh ? '刷新' : 'Refresh'}><RefreshCw size={13} /></button>
            <button onClick={handleDownloadTemplate} className="p-1.5 rounded-md text-black/20 hover:text-[#00bceb] hover:bg-[#00bceb]/5" title={zh ? '下载模板' : 'Template'}><FileText size={13} /></button>
            <button onClick={handleExport} className="p-1.5 rounded-md text-black/20 hover:text-[#00bceb] hover:bg-[#00bceb]/5" title={zh ? '导出' : 'Export'}><Download size={13} /></button>
            <button onClick={() => fileInputRef.current?.click()} className="p-1.5 rounded-md text-black/20 hover:text-[#00bceb] hover:bg-[#00bceb]/5" title={zh ? '导入' : 'Import'}><Upload size={13} /></button>
          </div>
        </div>

        {/* ── Filter Bar ── */}
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
              { val: statusFilter, set: setStatusFilter, label: zh ? '状态' : 'Status', opts: STATUSES.map(s => ({ v: s.value, l: s.label[zh ? 'zh' : 'en'] })) },
            ] as const).map(f => (
              <select
                key={f.label} value={f.val} onChange={e => f.set(e.target.value)} title={f.label}
                className={`px-1.5 py-1.5 rounded-md border text-[10px] focus:outline-none cursor-pointer transition-colors ${
                  f.val !== 'all' ? 'bg-[#00bceb]/5 border-[#00bceb]/15 text-[#0088b0] font-semibold' : 'bg-transparent border-black/5 text-black/30'
                }`}
              >
                <option value="all">{f.label}</option>
                {f.opts.map(o => <option key={o.v} value={o.v}>{o.l}</option>)}
              </select>
            ))}

            <button
              onClick={() => setShowAdvancedFilter(p => !p)}
              className={`flex items-center gap-1 px-1.5 py-1.5 rounded-md border text-[10px] font-medium transition-colors ${
                showAdvancedFilter || advancedFilterCount > 0
                  ? 'bg-[#00bceb]/5 border-[#00bceb]/15 text-[#0088b0]'
                  : 'bg-transparent border-black/5 text-black/30 hover:text-black/50'
              }`}
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

          {/* ── Advanced Filter Row ── */}
          <AnimatePresence>
            {showAdvancedFilter && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="overflow-hidden"
              >
                <div className="flex items-center gap-1.5 px-3 py-1.5 bg-black/[0.008] border-t border-black/[0.02]">
                  <span className="text-[9px] text-black/20 mr-0.5">{zh ? '高级:' : 'More:'}</span>
                  {([
                    { val: vendorFilter, set: setVendorFilter, label: zh ? '厂商' : 'Vendor', opts: vendorList.map(v => ({ v, l: v })),   hide: !vendorList.length },
                    { val: dcFilter,     set: setDcFilter,     label: zh ? '机房' : 'DC',     opts: dcList.map(d => ({ v: d, l: d })),     hide: !dcList.length },
                    { val: deptFilter,   set: setDeptFilter,   label: zh ? '业务' : 'Service', opts: deptList.map(d => ({ v: d, l: d })),  hide: !deptList.length },
                    { val: lifecycleFilter, set: setLifecycleFilter, label: zh ? '投产' : 'Lifecycle', opts: LIFECYCLE_STATUSES.map(s => ({ v: s.value, l: s.label[zh ? 'zh' : 'en'] })), hide: false },
                  ] as const).filter(f => !f.hide).map(f => (
                    <select
                      key={f.label} value={f.val} onChange={e => f.set(e.target.value)} title={f.label}
                      className={`px-1.5 py-1.5 rounded-md border text-[10px] focus:outline-none cursor-pointer transition-colors ${
                        f.val !== 'all' ? 'bg-[#00bceb]/5 border-[#00bceb]/15 text-[#0088b0] font-semibold' : 'bg-transparent border-black/5 text-black/30'
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

        {/* ══════════════════ TABLE VIEW ══════════════════ */}
        {viewMode === 'table' && (
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-black/5 bg-black/[0.008]">
                  <th className="w-7 px-1.5 py-1.5">
                    <input type="checkbox" checked={selectedIds.size === displayAssets.length && displayAssets.length > 0} onChange={toggleAll}
                      title="Select all" className="h-3 w-3 rounded border-black/12 accent-[#00bceb] cursor-pointer" />
                  </th>
                  {([
                    { l: zh ? '主机名' : 'Hostname',        w: 'min-w-[150px]', sticky: true },
                    { l: zh ? '类型'   : 'Type',            w: 'w-20' },
                    { l: zh ? '厂商/型号' : 'Vendor/Model', w: 'min-w-[110px]' },
                    { l: zh ? '管理IP' : 'Mgmt IP',         w: 'w-[110px]' },
                    { l: zh ? '状态'   : 'Status',          w: 'w-[80px]' },
                    { l: zh ? '投产'   : 'Lifecycle',       w: 'w-[80px]' },
                    { l: zh ? '角色'   : 'Role',            w: 'w-16' },
                    { l: zh ? '机房'   : 'DC',              w: 'w-20' },
                    { l: zh ? '部门'   : 'Dept',            w: 'w-20' },
                    { l: zh ? '保修到期' : 'Warranty',       w: 'w-24' },
                    { l: zh ? '操作'   : 'Actions',         w: 'w-16', align: 'text-center' },
                  ]).map(c => (
                    <th key={c.l} className={`text-left px-1.5 py-1.5 text-[9px] font-bold uppercase tracking-wider text-black/20 ${c.w} ${c.align || ''}`}>{c.l}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan={12} className="text-center py-16 text-black/15">
                    <RefreshCw size={16} className="mx-auto mb-1.5 animate-spin text-[#00bceb]/25" />
                    <p className="text-[10px]">{zh ? '加载中...' : 'Loading...'}</p>
                  </td></tr>
                ) : displayAssets.length === 0 ? (
                  /* ── Empty State ── */
                  <tr><td colSpan={12} className="py-16">
                    <EmptyState zh={zh} openAdd={openAdd} onImport={() => fileInputRef.current?.click()} />
                  </td></tr>
                ) : displayAssets.map(a => {
                  const sm  = statusMeta(a.status);
                  const sel = selectedIds.has(a.id);
                  const isDrawerTarget = drawerAsset?.id === a.id;

                  return (
                    <tr
                      key={a.id} onClick={() => setDrawerAsset(a)}
                      className={`border-b border-black/[0.02] cursor-pointer transition-colors ${
                        sel ? 'bg-[#00bceb]/[0.025]' : isDrawerTarget ? 'bg-black/[0.015]' : 'hover:bg-black/[0.008]'
                      }`}
                    >
                      {/* Checkbox */}
                      <td className="px-1.5 py-1" onClick={e => e.stopPropagation()}>
                        <input type="checkbox" checked={sel} onChange={() => toggle(a.id)}
                          title="Select" className="h-3 w-3 rounded border-black/12 accent-[#00bceb] cursor-pointer" />
                      </td>
                      {/* Hostname */}
                      <td className="px-1.5 py-1">
                        <p className="font-semibold text-[11px] text-black/80 leading-tight truncate max-w-[180px]">{a.hostname || '—'}</p>
                        <p className="text-[9px] text-black/20 font-mono truncate">{a.asset_tag || a.serial_number || ''}</p>
                      </td>
                      {/* Type */}
                      <td className="px-1.5 py-1">
                        <span className={`inline-flex items-center gap-1 text-[10px] ${
                          a.asset_type === 'server' ? 'text-violet-500' : 'text-cyan-600'
                        }`}>
                          {a.asset_type === 'server' ? <Server size={9} /> : <Router size={9} />}
                          {typeDisplay(a)}
                        </span>
                      </td>
                      {/* Vendor/Model */}
                      <td className="px-1.5 py-1 text-[10px]">
                        <span className="text-black/55">{a.vendor}</span>
                        {a.model && <span className="text-black/20 block text-[9px] truncate max-w-[100px]">{a.model}</span>}
                      </td>
                      {/* IP */}
                      <td className="px-1.5 py-1 font-mono text-[10px] text-black/50">{a.management_ip || '—'}</td>
                      {/* Status */}
                      <td className="px-1.5 py-1">
                        <span className={`inline-flex items-center gap-1 text-[10px] font-medium ${sm.text}`}>
                          <span className={`h-1.5 w-1.5 rounded-full ${sm.dot} ${a.status === 'active' ? 'animate-pulse' : ''}`} />
                          {sm.label[zh ? 'zh' : 'en']}
                        </span>
                      </td>
                      {/* Lifecycle */}
                      <td className="px-1.5 py-1">
                        {rotatingAssetId === a.id ? (
                          <span className="inline-flex items-center gap-1 text-[10px] font-medium text-cyan-600">
                            <Loader2 size={9} className="animate-spin" />
                            {zh ? '上收中' : 'Rotating'}
                          </span>
                        ) : (
                          <span className={`inline-flex items-center gap-1 text-[10px] font-medium ${
                            a.lifecycle_status === 'production' ? 'text-emerald-600' :
                            a.lifecycle_status === 'decommissioned' ? 'text-slate-400' :
                            a.lifecycle_status === 'maintenance' ? 'text-amber-600' :
                            'text-blue-500'
                          }`}>
                            <span className={`h-1.5 w-1.5 rounded-full ${
                              a.lifecycle_status === 'production' ? 'bg-emerald-500' :
                              a.lifecycle_status === 'decommissioned' ? 'bg-slate-400' :
                              a.lifecycle_status === 'maintenance' ? 'bg-amber-500' :
                              'bg-blue-400'
                            }`} />
                            {LIFECYCLE_STATUSES.find(l => l.value === a.lifecycle_status)?.label[zh ? 'zh' : 'en'] || (zh ? '待投产' : 'Staging')}
                          </span>
                        )}
                      </td>
                      {/* Role */}
                      <td className="px-1.5 py-1 text-[9px] text-black/30 capitalize">{a.device_role || '—'}</td>
                      {/* DC */}
                      <td className="px-1.5 py-1 text-[10px] text-black/30 truncate max-w-[80px]">
                        {a.datacenter || '—'}
                        {a.rack && <span className="text-black/15 block text-[9px]">{a.rack}{a.rack_unit ? `U${a.rack_unit}` : ''}</span>}
                      </td>
                      {/* Dept */}
                      <td className="px-1.5 py-1 text-[10px] text-black/30 truncate max-w-[80px]">{a.department || '—'}</td>
                      {/* Warranty */}
                      <td className="px-1.5 py-1 text-[10px] tabular-nums">
                        {a.warranty_expiry ? (
                          <span className={new Date(a.warranty_expiry) <= new Date(Date.now() + 90 * 86400000) ? 'text-red-500 font-semibold' : 'text-black/30'}>{a.warranty_expiry}</span>
                        ) : <span className="text-black/12">—</span>}
                      </td>
                      {/* Actions */}
                      <td className="px-1.5 py-1" onClick={e => e.stopPropagation()}>
                        <div className="flex items-center justify-center gap-px">
                          <ActionBtn icon={Copy}    title={zh ? '复制' : 'Copy'}  hoverCls="hover:text-emerald-500 hover:bg-emerald-50" onClick={() => openCopy(a)} />
                          <ActionBtn icon={Pencil}  title={zh ? '编辑' : 'Edit'}  hoverCls="hover:text-[#00bceb] hover:bg-[#00bceb]/5" onClick={() => openEdit(a)} />
                          <ActionBtn icon={Trash2}  title={zh ? '删除' : 'Delete'} hoverCls="hover:text-red-500 hover:bg-red-50" onClick={() => setDeleteTarget(a)} />
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* ══════════════════ GROUP VIEW ══════════════════ */}
        {viewMode === 'group' && (
          <div className="divide-y divide-black/[0.03]">
            {loading ? (
              <div className="text-center py-14 text-black/15"><RefreshCw size={16} className="mx-auto mb-1.5 animate-spin text-[#00bceb]/25" /></div>
            ) : Object.keys(groupedAssets).length === 0 ? (
              <div className="text-center py-14"><Building2 size={24} className="mx-auto mb-1.5 text-black/8" /><p className="text-xs text-black/20">{zh ? '无分组数据' : 'No groups'}</p></div>
            ) : (Object.entries(groupedAssets) as [string, Asset[]][]).sort((a, b) => b[1].length - a[1].length).map(([gk, items]) => {
              const isExp = expandedGroups.has(gk);
              const onlineIn = items.filter(a => a.status === 'active').length;
              const offlineIn = items.filter(a => a.status === 'inactive').length;
              const GroupIcon = groupBy === 'datacenter' ? Building2 : groupBy === 'vendor' ? MonitorSpeaker : Zap;
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
                      {/* Mini status bar */}
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
                                  <td className="px-2 py-1.5 text-[9px] text-black/30 capitalize">{a.device_role || '—'}</td>
                                  <td className="px-2 py-1.5">
                                    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-bold ${
                                      a.lifecycle_status === 'production' ? 'bg-emerald-50 text-emerald-600' :
                                      a.lifecycle_status === 'decommissioned' ? 'bg-slate-100 text-slate-400' :
                                      a.lifecycle_status === 'maintenance' ? 'bg-amber-50 text-amber-600' :
                                      'bg-blue-50 text-blue-500'
                                    }`}>
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
                    onClick={() => {
                      if (terminalTarget) {
                        const user = terminalAccessLevel === 'admin' ? (terminalTarget.admin_username || 'admin') : (terminalTarget.normal_username || 'user');
                        const url = `nexora://${terminalTarget.management_ip}?user=${encodeURIComponent(user)}&role=${terminalAccessLevel}&client=xshell`;
                        window.location.href = url;
                      } else if (terminalSession.title.includes('@')) {
                        const [u, h] = terminalSession.title.split('@');
                        const ip = h.split(':')[0];
                        window.location.href = `nexora://${ip}?user=${u}&client=xshell`;
                      }
                    }}
                    className="text-[10px] bg-emerald-500/20 text-emerald-400 px-2 py-0.5 rounded hover:bg-emerald-500/30 transition-all flex items-center gap-1"
                  >
                    <MonitorSpeaker size={10} />
                    {zh ? 'Xshell 调起' : 'Launch Xshell'}
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

        {terminalTarget && (
          <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-md"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onClick={() => !terminalRequesting && setTerminalTarget(null)}
          >
            <motion.div
              className="bg-[#0d1117] rounded-3xl w-[440px] border border-white/10 shadow-2xl overflow-hidden"
              onClick={(e) => e.stopPropagation()}
              initial={{ scale: 0.95, y: 20, opacity: 0 }} animate={{ scale: 1, y: 0, opacity: 1 }} exit={{ scale: 0.95, y: 20, opacity: 0 }}
            >
              <div className={`px-6 py-5 border-b border-white/[0.06] bg-gradient-to-r ${terminalAccessLevel === 'admin' ? 'from-orange-500/10' : 'from-cyan-500/10'} to-transparent`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className={`p-2 rounded-xl ${terminalAccessLevel === 'admin' ? 'bg-orange-500/20 text-orange-400' : 'bg-cyan-500/20 text-cyan-400'}`}>
                      {terminalAccessLevel === 'admin' ? <Shield size={20} /> : <Terminal size={20} />}
                    </div>
                    <div>
                      <h3 className="text-sm font-bold text-white">{zh ? '终端访问申请' : 'Access Request'}</h3>
                      <p className="text-[10px] text-white/40 mt-0.5 uppercase tracking-widest">{terminalTarget.hostname || terminalTarget.management_ip}</p>
                    </div>
                  </div>
                  <button onClick={() => setTerminalTarget(null)} className="text-white/20 hover:text-white/60 transition-colors"><X size={18} /></button>
                </div>
              </div>

              <div className="p-6 space-y-5">
                <div>
                  <label className="block text-[10px] font-bold text-white/30 uppercase tracking-widest mb-2">{zh ? '权限级别' : 'AUTHORIZATION'}</label>
                  <div className="flex bg-white/[0.03] rounded-xl p-1 border border-white/5">
                    <button 
                      onClick={() => setTerminalAccessLevel('normal')}
                      className={`flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-xs font-bold transition-all ${terminalAccessLevel === 'normal' ? 'bg-white/10 text-white shadow-sm' : 'text-white/30 hover:text-white/50'}`}
                    >
                      <User size={12} />{zh ? '普通用户' : 'User'}
                    </button>
                    <button 
                      onClick={() => setTerminalAccessLevel('admin')}
                      className={`flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-xs font-bold transition-all ${terminalAccessLevel === 'admin' ? 'bg-orange-500 text-white shadow-sm' : 'text-white/30 hover:text-white/50'}`}
                    >
                      <Shield size={12} />{zh ? '特权账号' : 'Admin'}
                    </button>
                  </div>
                </div>

                {terminalAccessLevel === 'admin' ? (
                  <div className="space-y-4 animate-in fade-in slide-in-from-top-2 duration-300">
                    <div>
                      <label className="block text-[10px] font-bold text-white/30 uppercase tracking-widest mb-2">{zh ? '关联变更单 (CR)' : 'CHANGE TICKET'}</label>
                      <input 
                        type="text" 
                        placeholder="CR-2026-XXXX"
                        value={approvalData.ticket}
                        onChange={e => setApprovalData({...approvalData, ticket: e.target.value})}
                        className="w-full bg-white/[0.03] border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white focus:border-orange-500 outline-none transition-all"
                      />
                    </div>
                    <div>
                      <label className="block text-[10px] font-bold text-white/30 uppercase tracking-widest mb-2">{zh ? '申请理由' : 'JUSTIFICATION'}</label>
                      <textarea 
                        rows={2}
                        value={terminalReason}
                        onChange={(e) => setTerminalReason(e.target.value)}
                        placeholder={zh ? '简述操作目的...' : 'Purpose of access...'}
                        className="w-full bg-white/[0.03] border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white focus:border-orange-500 outline-none transition-all resize-none"
                      />
                    </div>
                    <div>
                      <label className="block text-[10px] font-bold text-white/30 uppercase tracking-widest mb-2">{zh ? '动态验证码 (MFA)' : 'MFA CODE'}</label>
                      <input 
                        type="text" 
                        maxLength={6}
                        placeholder="******"
                        value={approvalData.mfa}
                        onChange={e => setApprovalData({...approvalData, mfa: e.target.value})}
                        className="w-full bg-white/[0.03] border border-white/10 rounded-xl px-4 py-2.5 text-center text-xl font-mono tracking-[0.5em] text-orange-400 focus:border-orange-500 outline-none transition-all"
                      />
                    </div>
                  </div>
                ) : (
                  <div className="py-4 text-center">
                    <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-cyan-500/10 text-cyan-400 text-[11px] font-medium border border-cyan-500/20">
                      <Check size={12} /> {zh ? '直连模式：无需审批与 MFA' : 'Direct Access: No Approval Required'}
                    </div>
                  </div>
                )}
              </div>

              <div className="px-6 py-5 bg-white/[0.02] border-t border-white/[0.06] flex items-center justify-between">
                <div className="text-[10px] text-white/20 flex items-center gap-1.5 font-medium italic">
                  <Lock size={10} />
                  {zh ? '受 Nexora PAM 审计保护' : 'Audited by Nexora PAM'}
                </div>
                <div className="flex gap-2">
                  <button onClick={() => setTerminalTarget(null)} className="px-4 py-2 text-xs font-bold text-white/40 hover:text-white/60 transition-colors">{zh ? '取消' : 'Cancel'}</button>
                  <button 
                    onClick={() => {
                      if (terminalAccessLevel === 'admin') {
                        setIsApproved(true);
                      }
                      requestTerminalAccess();
                    }}
                    disabled={terminalRequesting || (terminalAccessLevel === 'admin' && (!approvalData.ticket || !approvalData.mfa || !terminalReason.trim()))}
                    className={`px-6 py-2 rounded-xl text-xs font-bold shadow-lg transition-all ${terminalAccessLevel === 'admin' ? 'bg-gradient-to-r from-orange-500 to-red-500 text-white shadow-orange-500/20' : 'bg-[#00bceb] text-white shadow-cyan-500/20'} hover:scale-[1.02] active:scale-[0.98] disabled:opacity-30`}
                  >
                    {terminalRequesting ? <Loader2 size={14} className="animate-spin" /> : (zh ? '提交并登录' : 'Submit & Login')}
                  </button>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}

        {/* ══════════════════ TOPOLOGY VIEW ══════════════════ */}
        {viewMode === 'topology' && (
          <div className="py-16 text-center">
            <div className="h-14 w-14 rounded-xl bg-gradient-to-br from-black/[0.02] to-black/[0.04] flex items-center justify-center mx-auto mb-3">
              <Network size={24} className="text-black/10" />
            </div>
            <p className="text-sm font-semibold text-black/35 mb-1">{zh ? '网络拓扑视图' : 'Network Topology'}</p>
            <p className="text-[10px] text-black/15 mb-4 max-w-xs mx-auto">{zh ? '在拓扑页面中查看设备间的连接关系和位置分布' : 'View device connections and placement in the topology page'}</p>
            <button onClick={() => goTo('topology')} className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[#00bceb] text-white text-[11px] font-bold hover:bg-[#00a5d0] shadow-sm shadow-[#00bceb]/20">
              <ExternalLink size={12} />{zh ? '打开拓扑' : 'Open Topology'}
            </button>
          </div>
        )}

        {/* ── Pagination / footer ── */}
        {viewMode !== 'topology' && (
          <Pagination
            currentPage={page}
            totalItems={total}
            itemsPerPage={pageSize}
            onItemsPerPageChange={(v) => { setPage(1); setPageSize(v); }}
            onPageChange={setPage}
            language={language}
          />
        )}
      </div>

      {/* ═══════════════════ DETAIL MODAL (centered) ═══════════════════ */}
      <AnimatePresence>
        {drawerAsset && (
          <motion.div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-[3px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setDrawerAsset(null)}>
            <motion.div
              className="w-full max-w-2xl max-h-[85vh] bg-white rounded-2xl shadow-2xl shadow-black/10 overflow-y-auto flex flex-col ring-1 ring-black/5"
              initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }}
              transition={{ type: 'spring', damping: 28, stiffness: 320 }}
              onClick={e => e.stopPropagation()}
            >
              <DrawerContent asset={drawerAsset} zh={zh} onClose={() => setDrawerAsset(null)} />
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ═══════════════════ ADD/EDIT MODAL ═══════════════════ */}
      <AnimatePresence>
        {showModal && (
          <motion.div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setShowModal(false)}>
            <motion.div
              className="relative bg-white rounded-2xl w-full max-w-2xl max-h-[85vh] overflow-y-auto p-5 shadow-2xl border border-black/5"
              onClick={e => e.stopPropagation()}
              initial={{ scale: 0.96, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.96, opacity: 0 }}
            >
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-bold text-black/80">{editingAsset ? (zh ? '编辑资产' : 'Edit Asset') : (zh ? '新增资产' : 'Add Asset')}</h3>
                <button onClick={() => setShowModal(false)} title="Close" className="p-1 text-black/15 hover:text-black/35"><X size={16} /></button>
              </div>

              <div className="flex gap-2 mb-4">
                {TYPES.map(t => (
                  <button key={t.value} onClick={() => setForm(f => ({ 
                      ...f, 
                      asset_type: t.value,
                      platform: t.value === 'server' ? 'linux' : 'cisco_ios'
                    }))}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                      form.asset_type === t.value ? 'bg-[#00bceb]/10 border-[#00bceb]/25 text-[#0088b0] font-semibold' : 'bg-black/[0.01] border-black/5 text-black/30 hover:bg-black/[0.02]'
                    }`}>
                    <t.icon size={13} />{t.label[zh ? 'zh' : 'en']}
                  </button>
                ))}
              </div>

              <div className="grid grid-cols-2 gap-x-3 gap-y-2.5">
                {/* ─── 基础信息 ─── */}
                <Field label={zh ? '主机名 *' : 'Hostname *'}   value={form.hostname}      onChange={v => setForm(f => ({ ...f, hostname: v }))}      placeholder="core-sw-01" />
                <Field label={zh ? '资产编号' : 'Asset Tag'}     value={form.asset_tag}     onChange={v => setForm(f => ({ ...f, asset_tag: v }))}     placeholder="SRV-BJ-001" />
                <Field label={zh ? '序列号' : 'Serial No.'}     value={form.serial_number} onChange={v => setForm(f => ({ ...f, serial_number: v }))} />
                <div>
                  <label className="block text-[10px] text-black/30 mb-0.5">{zh ? '厂商' : 'Vendor'}</label>
                  <select value={form.vendor} onChange={e => {
                    const v = e.target.value;
                    const plats = VENDOR_PLATFORMS[v];
                    setForm(f => ({ ...f, vendor: v, platform: plats?.[0]?.value || f.platform }));
                  }} title="Vendor"
                    className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 focus:outline-none focus:border-[#00bceb]/25">
                    <option value="">{zh ? '请选择' : 'Select...'}</option>
                    <option value="Cisco">Cisco</option>
                    <option value="Huawei">Huawei</option>
                    <option value="H3C">H3C</option>
                    <option value="Arista">Arista</option>
                    <option value="Juniper">Juniper</option>
                    <option value="Dell">Dell</option>
                    <option value="HPE">HPE</option>
                    <option value="Lenovo">Lenovo</option>
                    <option value="Inspur">Inspur (浪潮)</option>
                    <option value="Ruijie">Ruijie (锐捷)</option>
                    <option value="ZTE">ZTE (中兴)</option>
                    <option value="Fortinet">Fortinet</option>
                    <option value="Palo Alto">Palo Alto</option>
                    <option value="Other">{zh ? '其他' : 'Other'}</option>
                  </select>
                </div>
                <Field label={zh ? '型号' : 'Model'}            value={form.model}         onChange={v => setForm(f => ({ ...f, model: v }))}         placeholder="C9300-48P" />
                <div>
                  <label className="block text-[10px] text-black/30 mb-0.5">{zh ? '状态' : 'Status'}</label>
                  <select value={form.status} onChange={e => setForm(f => ({ ...f, status: e.target.value }))} title="Status"
                    className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 focus:outline-none focus:border-[#00bceb]/25">
                    {STATUSES.map(s => <option key={s.value} value={s.value}>{s.label[zh ? 'zh' : 'en']}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-[10px] text-black/30 mb-0.5">{zh ? '投产状态' : 'Lifecycle'}</label>
                  <select value={form.lifecycle_status} onChange={e => setForm(f => ({ ...f, lifecycle_status: e.target.value }))} title="Lifecycle"
                    className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 focus:outline-none focus:border-[#00bceb]/25">
                    {LIFECYCLE_STATUSES.map(s => <option key={s.value} value={s.value}>{s.label[zh ? 'zh' : 'en']}</option>)}
                  </select>
                </div>
                <Field label={zh ? '管理IP' : 'Mgmt IP'}        value={form.management_ip} onChange={v => setForm(f => ({ ...f, management_ip: v }))} placeholder="10.0.0.1" />
                <Field label={zh ? '角色' : 'Role'}             value={form.device_role}   onChange={v => setForm(f => ({ ...f, device_role: v }))}   placeholder="Core, Access..." />
              </div>

              {/* ─── 连接配置 & PAM ─── */}
              {(form.asset_type === 'network_device' || form.asset_type === 'server') && (
                <div className="col-span-2 space-y-4">
                  <div className="flex items-center gap-1.5 mt-4 mb-1">
                    <Terminal size={12} className="text-[#00bceb]/60" />
                    <span className="text-[10px] font-bold text-black/30 uppercase tracking-wider">{zh ? '连接与凭据' : 'Connection & Credentials'}</span>
                  </div>
                  
                  <div className="grid grid-cols-2 gap-x-3 gap-y-2.5">
                    <div>
                      <label className="block text-[10px] text-black/30 mb-0.5">{zh ? '平台' : 'Platform'}</label>
                      <select value={form.platform} onChange={e => setForm(f => ({ ...f, platform: e.target.value }))} title="Platform"
                        className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 focus:outline-none focus:border-[#00bceb]/25">
                        {form.asset_type === 'server' ? (
                          SERVER_PLATFORMS.map(p => (
                            <option key={p.value} value={p.value}>{p.label}</option>
                          ))
                        ) : (
                          (VENDOR_PLATFORMS[form.vendor] || ALL_PLATFORMS).map(p => (
                            <option key={p.value} value={p.value}>{p.label}</option>
                          ))
                        )}
                      </select>
                    </div>
                    <div>
                      <label className="block text-[10px] text-black/30 mb-0.5">{zh ? '连接方式' : 'Method'}</label>
                      <select value={form.connection_method} onChange={e => setForm(f => ({ ...f, connection_method: e.target.value }))} title="Connection"
                        className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 focus:outline-none focus:border-[#00bceb]/25">
                        <option value="ssh">SSH</option>
                        <option value="netconf">NETCONF</option>
                      </select>
                    </div>
                  </div>

                  {/* PAM Toggle */}
                  <div className="flex items-center justify-between p-2.5 rounded-xl bg-slate-50 border border-black/5 mt-1">
                    <div className="flex items-center gap-2">
                      <Shield size={14} className={form.auth_model === 'dual' ? 'text-cyan-500' : 'text-slate-300'} />
                      <div>
                        <div className="flex items-center gap-2">
                          <p className="text-[10px] font-bold text-slate-700">{zh ? '多角色认证 (PAM)' : 'Multi-Role Auth (PAM)'}</p>
                          {editingAsset && (
                            <button
                              type="button"
                              onClick={async () => {
                                setModalError(null);
                                setFeedbackMsg({ type: 'info', text: zh ? '正在验证连通性...' : 'Verifying connectivity...' });
                                try {
                                  const r = await fetch(`/api/assets/${editingAsset.id}/verify`);
                                  const d = await r.json();
                                  if (d.success || d.ssh) {
                                    setFeedbackMsg({ type: 'success', text: zh ? '✅ 验证通过！' : '✅ Verification success!' });
                                  } else {
                                    const err = d.ssh_error || d.error || (zh ? '连接失败' : 'Connection failed');
                                    setModalError(`${zh ? '验证失败' : 'Verify failed'}: ${err}`);
                                    setFeedbackMsg({ type: 'error', text: zh ? '❌ 验证失败' : '❌ Verification failed' });
                                  }
                                } catch (e) {
                                  setModalError(String(e));
                                }
                              }}
                              className="text-[9px] px-1.5 py-0.5 rounded bg-cyan-100 text-cyan-700 hover:bg-cyan-200 transition-colors"
                            >
                              {zh ? '测试连通性' : 'Test Connectivity'}
                            </button>
                          )}
                        </div>
                        <p className="text-[8px] text-slate-400">{zh ? '同时管理普通账户和管理员账户凭据' : 'Manage both normal and admin account credentials'}</p>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => setForm(f => ({ ...f, auth_model: f.auth_model === 'dual' ? 'single' : 'dual' }))}
                      className={`relative inline-flex h-4 w-8 items-center rounded-full transition-colors ${form.auth_model === 'dual' ? 'bg-cyan-500' : 'bg-slate-200'}`}
                    >
                      <span className={`inline-block h-2.5 w-2.5 transform rounded-full bg-white transition-transform ${form.auth_model === 'dual' ? 'translate-x-4.5' : 'translate-x-1'}`} />
                    </button>
                  </div>

                  {form.auth_model === 'dual' ? (
                    <div className="grid grid-cols-2 gap-3 p-3 rounded-xl border border-black/5 bg-slate-50/30">
                      <div className="space-y-2">
                        <p className="text-[9px] font-black uppercase tracking-widest text-blue-500">{zh ? '普通账户' : 'Normal'}</p>
                        <Field label={zh ? '用户名' : 'User'} value={form.normal_username} onChange={v => setForm(f => ({ ...f, normal_username: v }))} placeholder="user" />
                        <PasswordField label={zh ? '密码' : 'Pass'} value={form.normal_password} onChange={v => setForm(f => ({ ...f, normal_password: v }))} placeholder={editingAsset ? (zh ? '留空不变' : 'Keep') : ''} />
                      </div>
                      <div className="space-y-2">
                        <p className="text-[9px] font-black uppercase tracking-widest text-orange-500">{zh ? '特权账户' : 'Admin'}</p>
                        <Field label={zh ? '用户名' : 'User'} value={form.admin_username} onChange={v => setForm(f => ({ ...f, admin_username: v }))} placeholder="root" />
                        <PasswordField label={zh ? '密码' : 'Pass'} value={form.admin_password} onChange={v => setForm(f => ({ ...f, admin_password: v }))} placeholder={editingAsset ? (zh ? '留空不变' : 'Keep') : ''} />
                      </div>
                    </div>
                  ) : (
                    <div className="grid grid-cols-2 gap-x-3 gap-y-2.5">
                      <Field label={zh ? '用户名' : 'Username'} value={form.username} onChange={v => setForm(f => ({ ...f, username: v }))} placeholder="admin" />
                      <PasswordField label={zh ? '密码' : 'Password'} value={form.password} onChange={v => setForm(f => ({ ...f, password: v }))} placeholder={editingAsset ? (zh ? '留空保持不变' : 'Leave empty to keep') : ''} />
                    </div>
                  )}

                  <div className="flex items-center gap-1.5 mt-2 mb-1">
                    <Wifi size={12} className="text-[#00bceb]/60" />
                    <span className="text-[10px] font-bold text-black/30 uppercase tracking-wider">SNMP</span>
                  </div>
                  <div className="grid grid-cols-2 gap-x-3 gap-y-2.5">
                    <Field label={zh ? '团体字' : 'Community'} value={form.snmp_community} onChange={v => setForm(f => ({ ...f, snmp_community: v }))} placeholder="public" />
                    <Field label={zh ? '端口' : 'Port'} value={form.snmp_port} onChange={v => setForm(f => ({ ...f, snmp_port: v }))} placeholder="161" />
                  </div>
                </div>
              )}

              {/* ─── 服务器: 网络接入 ─── */}
              {form.asset_type === 'server' && (
                <>
                  <div className="flex items-center gap-1.5 mt-4 mb-2">
                    <Network size={12} className="text-violet-400" />
                    <span className="text-[10px] font-bold text-black/30 uppercase tracking-wider">{zh ? '网络接入' : 'Network'}</span>
                  </div>
                  <div className="grid grid-cols-2 gap-x-3 gap-y-2.5">
                    <Field label={zh ? '业务IP' : 'Biz IP'}       value={form.business_ip}   onChange={v => setForm(f => ({ ...f, business_ip: v }))}   placeholder="192.168.1.10" />
                    <Field label="VLAN"                            value={form.vlan}          onChange={v => setForm(f => ({ ...f, vlan: v }))}          placeholder="VLAN 100" />
                    <Field label={zh ? '上联交换机' : 'Uplink Switch'} value={form.uplink_switch} onChange={v => setForm(f => ({ ...f, uplink_switch: v }))} placeholder="core-sw-01" />
                    <Field label={zh ? '上联端口' : 'Uplink Port'} value={form.uplink_port}   onChange={v => setForm(f => ({ ...f, uplink_port: v }))}   placeholder="Gi0/1" />
                  </div>
                </>
              )}

              {/* ─── 位置 & 资产 ─── */}
              <div className="flex items-center gap-1.5 mt-4 mb-2">
                <Building2 size={12} className="text-black/20" />
                <span className="text-[10px] font-bold text-black/30 uppercase tracking-wider">{zh ? '位置 & 资产' : 'Location & Asset'}</span>
              </div>
              <div className="grid grid-cols-2 gap-x-3 gap-y-2.5">
                <Field label={zh ? '数据中心' : 'DC'}            value={form.datacenter}    onChange={v => setForm(f => ({ ...f, datacenter: v }))}    placeholder="BJ-DC1" />
                <Field label={zh ? '机柜' : 'Rack'}             value={form.rack}          onChange={v => setForm(f => ({ ...f, rack: v }))}          placeholder="A-01" />
                <Field type="number" label={zh ? '设备高度(U)' : 'Height (U)'} value={form.u_height} onChange={v => setForm(f => ({ ...f, u_height: v }))} placeholder="1" />
                <Field type="number" label={zh ? '计划起始U(选填)' : 'Planned start U'} value={form.planned_start_u} onChange={v => setForm(f => ({ ...f, planned_start_u: v }))} placeholder="" />
                <Field label={zh ? '机位备注(选填)' : 'Location note'} value={form.rack_unit} onChange={v => setForm(f => ({ ...f, rack_unit: v }))} placeholder={zh ? '文本备注' : 'Optional note'} />
                <Field label={zh ? '部门/业务' : 'Service'}      value={form.department}    onChange={v => setForm(f => ({ ...f, department: v }))} />
                <DateTimePicker label={zh ? '购买日期' : 'Purchased'} value={form.purchase_date} onChange={v => setForm(f => ({ ...f, purchase_date: v }))} language={language} mode="date" />
                <DateTimePicker label={zh ? '保修到期' : 'Warranty'} value={form.warranty_expiry} onChange={v => setForm(f => ({ ...f, warranty_expiry: v }))} language={language} mode="date" />
                <div className="col-span-2">
                  <label className="block text-[10px] text-black/30 mb-0.5">{zh ? '备注' : 'Notes'}</label>
                  <textarea value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} rows={2}
                    placeholder={zh ? '可选备注...' : 'Optional notes...'} className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 placeholder:text-black/12 focus:outline-none focus:border-[#00bceb]/25 resize-none" />
                </div>
              </div>

              {/* ─── Inline validation error ─── */}
              {modalError && (
                <div className="flex items-center gap-2 mt-4 px-3 py-2.5 rounded-lg bg-red-50 border border-red-200 text-red-700">
                  <AlertCircle size={14} className="shrink-0 text-red-500" />
                  <span className="text-xs font-medium">{modalError}</span>
                  <button onClick={() => setModalError(null)} title="Dismiss" className="ml-auto p-0.5 text-red-400 hover:text-red-600"><X size={12} /></button>
                </div>
              )}

              <div className="flex justify-end gap-2 mt-5">
                <button onClick={() => setShowModal(false)} className="px-3 py-1.5 rounded-lg bg-black/[0.01] border border-black/5 text-black/40 text-xs hover:bg-black/[0.02]">{zh ? '取消' : 'Cancel'}</button>
                <button onClick={() => { setModalError(null); handleSave(); }} disabled={saving || (!form.hostname.trim() && !form.asset_tag.trim())}
                  className="px-4 py-1.5 rounded-lg bg-[#00bceb] text-white text-xs font-bold hover:bg-[#00a5d0] disabled:opacity-50 shadow-sm shadow-[#00bceb]/20">
                  {saving ? (zh ? '保存中...' : 'Saving...') : (zh ? '保存' : 'Save')}
                </button>
              </div>

              {/* Production confirmation overlay */}
              {showProductionConfirm && (
                <motion.div
                  initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                  className="absolute inset-0 z-10 flex items-center justify-center rounded-2xl bg-black/40"
                >
                  <div className="mx-6 max-w-sm rounded-xl bg-white p-5 shadow-xl">
                    <div className="flex items-center gap-2 mb-2">
                      <div className="h-7 w-7 rounded-full bg-amber-50 flex items-center justify-center">
                        <AlertTriangle size={14} className="text-amber-500" />
                      </div>
                      <h4 className="text-sm font-bold text-black/80">{zh ? '投产确认' : 'Production Confirmation'}</h4>
                    </div>
                    <p className="text-xs leading-relaxed text-black/50 mb-4">
                      {zh
                        ? '设备即将标记为已投产，系统将自动修改默认口令并完成凭据上收，确保安全合规。'
                        : 'Device will be marked as in production. Default passwords will be auto-rotated and credentials secured.'}
                    </p>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setShowProductionConfirm(false)}
                        className="flex-1 px-3 py-1.5 rounded-lg bg-black/[0.01] border border-black/5 text-black/40 text-xs hover:bg-black/[0.02]"
                      >
                        {zh ? '取消' : 'Cancel'}
                      </button>
                      <button
                        onClick={() => { setShowProductionConfirm(false); doSave(); }}
                        disabled={saving}
                        className="flex-1 px-3 py-1.5 rounded-lg bg-[#00bceb] text-white text-xs font-bold hover:bg-[#00a5d0] disabled:opacity-50"
                      >
                        {saving ? (zh ? '处理中...' : 'Processing...') : (zh ? '确认投产' : 'Confirm')}
                      </button>
                    </div>
                  </div>
                </motion.div>
              )}
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ═══════════════════ DELETE CONFIRM ═══════════════════ */}
      <AnimatePresence>
        {deleteTarget && (
          <motion.div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setDeleteTarget(null)}>
            <motion.div className="bg-white rounded-xl w-full max-w-sm p-5 shadow-2xl border border-black/5"
              onClick={e => e.stopPropagation()} initial={{ scale: 0.96, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.96, opacity: 0 }}>
              <div className="flex items-center gap-3 mb-3">
                <div className="h-9 w-9 rounded-full bg-red-50 flex items-center justify-center"><Trash2 size={16} className="text-red-500" /></div>
                <div>
                  <h3 className="text-sm font-bold text-black/80">{zh ? '确认删除' : 'Confirm Delete'}</h3>
                  <p className="text-[10px] text-black/25 mt-0.5">{deleteTarget.hostname || deleteTarget.asset_tag}</p>
                </div>
              </div>
              <p className="text-[11px] text-black/35 mb-4">{zh ? '删除后不可恢复，是否继续？' : 'This action cannot be undone. Continue?'}</p>
              <div className="flex justify-end gap-2">
                <button onClick={() => setDeleteTarget(null)} className="px-3 py-1.5 rounded-lg bg-black/[0.01] border border-black/5 text-black/40 text-xs hover:bg-black/[0.02]">{zh ? '取消' : 'Cancel'}</button>
                <button onClick={handleDelete} className="px-3 py-1.5 rounded-lg bg-red-600 text-white text-xs font-bold hover:bg-red-700">{zh ? '删除' : 'Delete'}</button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ═══════════════════ BATCH TAG MODAL ═══════════════════ */}
      <AnimatePresence>
        {showBatchTag && (
          <motion.div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setShowBatchTag(false)}>
            <motion.div className="bg-white rounded-xl w-full max-w-sm p-5 shadow-2xl border border-black/5"
              onClick={e => e.stopPropagation()} initial={{ scale: 0.96, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.96, opacity: 0 }}>
              <h3 className="text-sm font-bold text-black/80 mb-3">{zh ? '批量添加标签' : 'Assign Tag to Selected'}</h3>
              <p className="text-[10px] text-black/25 mb-3">{selectedIds.size} {zh ? '个资产将被标记' : 'assets selected'}</p>
              <input value={batchTagValue} onChange={e => setBatchTagValue(e.target.value)} placeholder={zh ? '输入标签内容...' : 'Enter tag value...'}
                className="w-full bg-white border border-black/8 rounded-lg px-3 py-2 text-xs text-black/65 placeholder:text-black/15 focus:outline-none focus:border-[#00bceb]/25 mb-4" />
              <div className="flex justify-end gap-2">
                <button onClick={() => setShowBatchTag(false)} className="px-3 py-1.5 rounded-lg bg-black/[0.01] border border-black/5 text-black/40 text-xs">{zh ? '取消' : 'Cancel'}</button>
                <button onClick={batchTag} disabled={!batchTagValue.trim()} className="px-4 py-1.5 rounded-lg bg-[#00bceb] text-white text-xs font-bold hover:bg-[#00a5d0] disabled:opacity-50">{zh ? '应用' : 'Apply'}</button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

/* ═══════════════════════════════════════════════════════════════════
   Sub-components
   ═══════════════════════════════════════════════════════════════════ */

/* --- Empty State --- */
function EmptyState({ zh, openAdd, onImport }: { zh: boolean; openAdd: () => void; onImport: () => void }) {
  return (
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
        {zh ? '添加网络设备和服务器，自动发现拓扑，连接监控系统——统一资产控制台从这里开始' : 'Add devices, discover topology, connect monitoring — your unified control plane starts here'}
      </p>
      <div className="flex items-center justify-center gap-2 flex-wrap">
        <button onClick={openAdd} className="flex items-center gap-1.5 px-5 py-2 rounded-lg bg-[#00bceb] text-white text-[11px] font-bold hover:bg-[#00a5d0] shadow-sm shadow-[#00bceb]/20">
          <Plus size={13} />{zh ? '添加资产' : 'Add Asset'}
        </button>
        <button onClick={onImport} className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-black/8 text-black/35 text-[11px] font-medium hover:bg-black/[0.01]">
          <Upload size={12} />{zh ? '导入 Excel' : 'Import Excel'}
        </button>
      </div>
    </div>
  );
}

/* --- Readonly field (mirrors edit Field style) --- */
function ReadonlyField({ label, value, mono, warn }: { label: string; value: string; mono?: boolean; warn?: boolean }) {
  return (
    <div>
      <label className="block text-[10px] text-black/30 mb-0.5">{label}</label>
      <div className={`w-full border border-black/8 rounded-lg px-2.5 py-1.5 text-xs bg-black/[0.01] min-h-[30px] flex items-center ${warn ? 'text-amber-600 font-bold' : 'text-black/65'} ${mono ? 'font-mono' : ''}`}>
        {value}
      </div>
    </div>
  );
}

/* --- Drawer Content --- */
function DrawerContent({ asset: a, zh, onClose }: {
  asset: Asset; zh: boolean; onClose: () => void;
}) {
  return (
    <div className="p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-bold text-black/80">{a.hostname || a.asset_tag || '—'}</h3>
        <button onClick={onClose} title="Close" className="p-1 text-black/15 hover:text-black/35"><X size={16} /></button>
      </div>
      <AssetReadonlyDetailInner asset={a} zh={zh} />
    </div>
  );
}

/* --- Form field --- */
function Field({ label, value, onChange, placeholder, type = 'text' }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string; type?: string;
}) {
  return (
    <div>
      <label className="block text-[10px] text-black/30 mb-0.5">{label}</label>
      <input type={type} value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
        className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 placeholder:text-black/12 focus:outline-none focus:border-[#00bceb]/25" />
    </div>
  );
}

function PasswordField({ label, value, onChange, placeholder }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string;
}) {
  const [show, setShow] = React.useState(false);
  return (
    <div>
      <label className="block text-[10px] text-black/30 mb-0.5">{label}</label>
      <div className="relative">
        <input type={show ? 'text' : 'password'} value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
          className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 pr-7 text-xs text-black/65 placeholder:text-black/12 focus:outline-none focus:border-[#00bceb]/25" />
        <button type="button" onClick={() => setShow(!show)} className="absolute right-1.5 top-1/2 -translate-y-1/2 p-0.5 text-black/15 hover:text-black/30">
          {show ? <EyeOff size={12} /> : <Eye size={12} />}
        </button>
      </div>
    </div>
  );
}

/* --- Table action icon button --- */
function ActionBtn({ icon: Icon, title, hoverCls, onClick }: { icon: React.FC<{ size?: number }>; title: string; hoverCls: string; onClick: () => void }) {
  return <button onClick={onClick} className={`p-1 rounded text-black/12 ${hoverCls} transition-colors`} title={title}><Icon size={12} /></button>;
}

/* --- Batch toolbar button --- */
function BatchBtn({ icon: Icon, label, onClick, hoverCls }: { icon: React.FC<{ size?: number }>; label: string; onClick: () => void; hoverCls: string }) {
  return (
    <button onClick={onClick} className={`flex items-center gap-0.5 px-1.5 py-0.5 rounded text-black/35 text-[9px] font-medium ${hoverCls} transition-colors`} title={label}>
      <Icon size={10} />{label}
    </button>
  );
}

/* --- Info section in drawer --- */
function InfoSection({ title, rows }: { title: string; rows: { k: string; v: string; mono?: boolean; warn?: boolean }[] }) {
  return (
    <div>
      <p className="text-[9px] font-bold uppercase tracking-widest text-black/15 mb-1.5">{title}</p>
      <div className="space-y-0.5">
        {rows.map(r => (
          <div key={r.k} className="flex items-center justify-between py-0.5">
            <span className="text-[10px] text-black/25">{r.k}</span>
            <span className={`text-[10px] ${r.warn ? 'text-amber-600 font-bold' : 'text-black/55'} ${r.mono ? 'font-mono' : ''}`}>{r.v}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default AssetManagementTab;
