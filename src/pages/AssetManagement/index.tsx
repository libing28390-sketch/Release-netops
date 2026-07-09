import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Terminal as XTerm } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import 'xterm/css/xterm.css';
import {
  Package, Plus, Trash2, Search, X, RefreshCw, Download, Pencil, Copy,
  Server, Router, AlertTriangle, Network, SlidersHorizontal,
  Wifi, Building2, Upload, FileText, ChevronDown, ChevronUp,
  Zap, AlertCircle, CheckCircle2, Tag, Info,
  Flame, LayoutList, LayoutGrid, Lock, Terminal, Eye, EyeOff, Loader2, Shield, User, MonitorSpeaker, Check
} from 'lucide-react';
import * as XLSX from 'xlsx';
import { AnimatePresence, motion } from 'motion/react';

import Pagination from '../../components/Pagination';
import PageHero from '../../components/PageHero';
import { fetchAllPaginatedItems } from '../../utils/pagination';
import { useSystem } from '../../hooks/useSystem';

import { Asset, AssetSummary, AssetManagementTabProps, ViewMode, GroupBy } from './types';
import { STATUSES, TYPES, LIFECYCLE_STATUSES, EMPTY_FORM, VENDOR_PLATFORMS, SERVER_PLATFORMS, ALL_PLATFORMS, COL_MAP } from './constants';
import { statusMeta, typeMeta, severityOf } from './helpers';

import { DeleteConfirmModal } from './components/DeleteConfirmModal';
import { BatchTagModal } from './components/BatchTagModal';
import { AssetImportValidationModal, MissingRackInfo, RackResolution } from './components/AssetImportValidationModal';
import { TerminalAccessModal } from './components/TerminalAccessModal';
import { AssetDetailDrawer } from './components/AssetDetailDrawer';
import { AssetModal } from './components/AssetModal';

const AssetManagementTab: React.FC<AssetManagementTabProps> = ({ language, setActiveTab }) => {
  const { systemInfo } = useSystem();
  const zh = language === 'zh';
  const goTo = (tab: string) => setActiveTab?.(tab);

  /* ─── State ─── */
  const [assets, setAssets]             = useState<Asset[]>([]);
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

  useEffect(() => () => { if (rotationPollRef.current) clearInterval(rotationPollRef.current); }, []);

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

  useEffect(() => {
    if (!drawerAsset) return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setDrawerAsset(null); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [drawerAsset]);

  useEffect(() => {
    if (!feedbackMsg) return;
    if (rotatingAssetId) return;
    const t = setTimeout(() => setFeedbackMsg(null), feedbackMsg.type === 'error' ? 8000 : 5000);
    return () => clearTimeout(t);
  }, [feedbackMsg, rotatingAssetId]);

  const vendorList = useMemo(() => summary?.by_vendor ? Object.keys(summary.by_vendor).sort() : [], [summary]);
  const dcList     = useMemo(() => summary?.by_datacenter ? Object.keys(summary.by_datacenter).sort() : [], [summary]);
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
      // Guard: a server must never carry a network-device platform (e.g. stale
      // cisco_ios). If the stored value isn't a valid server platform, coerce
      // it to a sane Linux default so we don't persist an inconsistent platform.
      let normalizedPlatform = form.platform;
      if (form.asset_type === 'server') {
        const serverValues = SERVER_PLATFORMS.map(p => p.value);
        if (!serverValues.includes(String(form.platform))) {
          normalizedPlatform = 'linux';
        }
      }
      const payload = {
        ...form,
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

  const handleSave = async () => {
    if (!form.hostname.trim() && !form.asset_tag.trim()) return;
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
      vendor: a.vendor, model: a.model, hostname: '', datacenter: a.datacenter,
      rack: a.rack, rack_unit: '', u_height: String(a.u_height ?? 1), planned_start_u: a.planned_start_u != null ? String(a.planned_start_u) : '', management_ip: '',
      business_ip: '', device_role: a.device_role,
      vlan: a.vlan || '', uplink_switch: a.uplink_switch || '', uplink_port: a.uplink_port || '',
      status: a.status, lifecycle_status: 'staging',
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
    if (dcFilter !== 'all')     params.set('datacenter', dcFilter);
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
        [zh ? '数据中心' : 'Datacenter']: a.datacenter,
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
    try {
      const r = await fetch('/api/assets/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (r.ok) {
        const res = await r.json();
        setFeedbackMsg({
          type: 'success',
          text: zh ? `导入完成：新增 ${res.created} 条，跳过 ${res.skipped} 条` : `Import done: ${res.created} created, ${res.skipped} skipped`,
        });
        fetchAssets();
        fetchSummary();
        fetchAllRacks();
      } else {
        setFeedbackMsg({ type: 'error', text: zh ? '导入失败' : 'Import failed' });
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
      const autoCreateList: { name: string; datacenter: string; total_u: number }[] = [];
      const createdKeys = new Set<string>();

      Object.entries(resolutions).forEach(([key, res]) => {
        const [dc, rk] = key.split('|');
        if (res.action === 'skip') {
          skipKeys.add(key);
        } else if (res.action === 'map' && res.targetRack) {
          mapConfig[key] = res.targetRack;
        } else if (res.action === 'create') {
          if (!createdKeys.has(key)) {
            autoCreateList.push({ name: rk, datacenter: dc, total_u: 42 });
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
        const dc = row.datacenter || '';
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
      setFeedbackMsg({
        type: 'error',
        text: err.message || (zh ? '处理异常失败' : 'Failed to process import validation'),
      });
    } finally {
      setValidationModalSaving(false);
    }
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
        if (!mapped.length) { setFeedbackMsg({ type: 'error', text: zh ? '未找到有效 data 行' : 'No valid rows found' }); return; }
        
        // Scan for missing racks
        const missingMap: Record<string, { datacenter: string; rack: string; rowCount: number }> = {};
        mapped.forEach(row => {
          if (row.rack) {
            const dcName = row.datacenter || '';
            const exists = allRacks.some(r => r.name === row.rack && (r.datacenter || '') === dcName);
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

  const handleDownloadTemplate = () => {
    const wb = XLSX.utils.book_new();

    const srvHeaders = zh
      ? ['主机名', '资产编号', '序列号', '厂商', '型号', '平台', '管理IP', '管理端口', '业务IP', '连接方式', '状态', '角色', '设备分类', 'VLAN', '上联交换机', '上联端口', '数据中心', '机柜', 'U位', 'U高度', '规划起始U', '功耗(W)', 'SNMP社区名', 'SNMP端口', '普通用户', '特权用户', '普通密码', '特权密码', 'Enable密码', '部门', '购买日期', '投产状态', '保修到期', '备注']
      : ['Hostname', 'Asset Tag', 'Serial Number', 'Vendor', 'Model', 'Platform', 'Mgmt IP', 'Mgmt Port', 'Business IP', 'Connection', 'Status', 'Role', 'Device Category', 'VLAN', 'Uplink Switch', 'Uplink Port', 'Datacenter', 'Rack', 'Rack Unit', 'U Height', 'Planned Start U', 'Power(W)', 'SNMP Community', 'SNMP Port', 'Normal User', 'Admin User', 'Normal Password', 'Admin Password', 'Enable Secret', 'Department', 'Purchase Date', 'Lifecycle', 'Warranty Expiry', 'Notes'];
    const srvExample = zh
      ? ['web-srv-01', 'SRV-BJ-001', 'CZJ2345G0HN', 'Dell', 'PowerEdge R750', 'linux', '10.0.1.10', '22', '192.168.1.10', 'ssh', 'active', 'web', '服务器', 'VLAN100', 'core-sw-01', 'Gi0/1', 'BJ-DC1', 'A-01', '12', '1', '12', '200', 'public', '161', 'user', 'admin', '', '', '', 'IT部', '2024-01-15', '待投产', '2027-01-15', '服务器备注']
      : ['web-srv-01', 'SRV-BJ-001', 'CZJ2345G0HN', 'Dell', 'PowerEdge R750', 'linux', '10.0.1.10', '22', '192.168.1.10', 'ssh', 'active', 'web', 'server', 'VLAN100', 'core-sw-01', 'Gi0/1', 'BJ-DC1', 'A-01', '12', '1', '12', '200', 'public', '161', 'user', 'admin', '', '', '', 'IT Dept', '2024-01-15', 'staging', '2027-01-15', 'Production srv'];
    const wsSrv = XLSX.utils.aoa_to_sheet([srvHeaders, srvExample]);
    wsSrv['!cols'] = srvHeaders.map(() => ({ wch: 16 }));
    XLSX.utils.book_append_sheet(wb, wsSrv, zh ? '服务器模板' : 'Server Template');

    const netHeaders = zh
      ? ['主机名', '资产编号', '序列号', '厂商', '型号', '平台', '管理IP', '管理端口', '连接方式', '状态', '角色', '设备分类', '数据中心', '机柜', 'U位', 'U高度', '规划起始U', '功耗(W)', 'SNMP社区名', 'SNMP端口', '普通用户', '特权用户', '普通密码', '特权密码', 'Enable密码', '部门', '购买日期', '投产状态', '保修到期', '备注']
      : ['Hostname', 'Asset Tag', 'Serial Number', 'Vendor', 'Model', 'Platform', 'Mgmt IP', 'Mgmt Port', 'Connection', 'Status', 'Role', 'Device Category', 'Datacenter', 'Rack', 'Rack Unit', 'U Height', 'Planned Start U', 'Power(W)', 'SNMP Community', 'SNMP Port', 'Normal User', 'Admin User', 'Normal Password', 'Admin Password', 'Enable Secret', 'Department', 'Purchase Date', 'Lifecycle', 'Warranty Expiry', 'Notes'];
    const netExample = zh
      ? ['core-sw-01', 'NET-BJ-001', 'FCW2345L0AB', 'Cisco', 'C9300-48P', 'cisco_ios', '10.0.0.1', '22', 'ssh', 'active', 'switch', '交换机', 'BJ-DC1', 'A-02', '40', '1', '40', '200', 'public', '161', 'user', 'admin', '', '', '', 'IT部', '2023-06-01', '待投产', '2026-06-01', '核心交换机']
      : ['core-sw-01', 'NET-BJ-001', 'FCW2345L0AB', 'Cisco', 'C9300-48P', 'cisco_ios', '10.0.0.1', '22', 'ssh', 'active', 'switch', 'switch', 'BJ-DC1', 'A-02', '40', '1', '40', '200', 'public', '161', 'user', 'admin', '', '', '', 'IT Dept', '2023-06-01', 'staging', '2026-06-01', 'Core switch'];
    const wsNet = XLSX.utils.aoa_to_sheet([netHeaders, netExample]);
    wsNet['!cols'] = netHeaders.map(() => ({ wch: 16 }));
    XLSX.utils.book_append_sheet(wb, wsNet, zh ? '网络设备模板' : 'Network Device Template');

    XLSX.writeFile(wb, zh ? '资产导入模板.xlsx' : 'asset_import_template.xlsx');
  };

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

        <div className="bg-white rounded-xl border border-black/5 shadow-sm overflow-hidden">
          <div className="flex items-center justify-between px-3 py-1.5 border-b border-black/5 bg-black/[0.008]">
            <div className="flex items-center gap-0.5">
              {([
                { mode: 'table' as ViewMode, Icon: LayoutList, label: zh ? '表格' : 'Table' },
                { mode: 'group' as ViewMode, Icon: LayoutGrid, label: zh ? '分组' : 'Group' },
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
                  <option value="datacenter">{zh ? '机房' : 'Data Center'}</option>
                  <option value="department">{zh ? '业务/部门' : 'Service'}</option>
                  <option value="vendor">{zh ? '厂商' : 'Vendor'}</option>
                </select>
              )}
            </div>

            <div className="flex items-center gap-1">
              <AnimatePresence>
                {selectedIds.size > 0 && (
                  <motion.div initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 12 }} className="flex items-center gap-0.5 mr-1.5 pr-1.5 border-r border-black/8">
                    <span className="text-[10px] font-bold text-[#00bceb] tabular-nums mr-1">{selectedIds.size}</span>
                    <button onClick={() => setShowBatchTag(true)} className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-black/35 text-[9px] font-medium hover:bg-blue-50 hover:text-blue-600 transition-colors"><Tag size={10} />{zh ? '标签' : 'Tag'}</button>
                    <button onClick={handleBatchTakeover} className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-cyan-500 text-[9px] font-medium hover:bg-cyan-50 hover:text-cyan-600 transition-colors"><Shield size={10} />{zh ? '批量上收' : 'Takeover'}</button>
                    <button onClick={handleBatchDelete} className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-black/35 text-[9px] font-medium hover:bg-red-50 hover:text-red-600 transition-colors"><Trash2 size={10} />{zh ? '删除' : 'Delete'}</button>
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
                  className={`px-1.5 py-1.5 rounded-md border text-[10px] focus:outline-none cursor-pointer transition-colors ${f.val !== 'all' ? 'bg-[#00bceb]/5 border-[#00bceb]/15 text-[#0088b0] font-semibold' : 'bg-transparent border-black/5 text-black/30'}`}
                >
                  <option value="all">{f.label}</option>
                  {f.opts.map(o => <option key={o.v} value={o.v}>{o.l}</option>)}
                </select>
              ))}

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
                      { val: dcFilter,     set: setDcFilter,     label: zh ? '机房' : 'DC',     opts: dcList.map(d => ({ v: d, l: d })),     hide: !dcList.length },
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
                    {([
                      { l: zh ? '主机名' : 'Hostname',        w: 'min-w-[150px]' },
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
                    <tr><td colSpan={12} className="py-16">
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
                    const sm  = statusMeta(a.status);
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
                        <td className="px-1.5 py-1">
                          <p className="font-semibold text-[11px] text-black/80 leading-tight truncate max-w-[180px]">{a.hostname || '—'}</p>
                          <p className="text-[9px] text-black/20 font-mono truncate">{a.asset_tag || a.serial_number || ''}</p>
                        </td>
                        <td className="px-1.5 py-1">
                          <span className={`inline-flex items-center gap-1 text-[10px] ${a.asset_type === 'server' ? 'text-violet-500' : 'text-cyan-600'}`}>
                            {a.asset_type === 'server' ? <Server size={9} /> : <Router size={9} />}
                            {typeDisplay(a)}
                          </span>
                        </td>
                        <td className="px-1.5 py-1 text-[10px]">
                          <span className="text-black/55">{a.vendor}</span>
                          {a.model && <span className="text-black/20 block text-[9px] truncate max-w-[100px]">{a.model}</span>}
                        </td>
                        <td className="px-1.5 py-1 font-mono text-[10px] text-black/50">{a.management_ip || '—'}</td>
                        <td className="px-1.5 py-1">
                          <span className={`inline-flex items-center gap-1 text-[10px] font-medium ${sm.text}`}>
                            <span className={`h-1.5 w-1.5 rounded-full ${sm.dot} ${a.status === 'active' ? 'animate-pulse' : ''}`} />
                            {sm.label[zh ? 'zh' : 'en']}
                          </span>
                        </td>
                        <td className="px-1.5 py-1">
                          {rotatingAssetId === a.id ? (
                            <span className="inline-flex items-center gap-1 text-[10px] font-medium text-cyan-600">
                              <Loader2 size={9} className="animate-spin" />
                              {zh ? '上收中' : 'Rotating'}
                            </span>
                          ) : (
                            <div className="flex flex-col gap-0.5">
                              <span className={`inline-flex items-center gap-1 text-[10px] font-medium ${a.lifecycle_status === 'production' ? 'text-emerald-600' : a.lifecycle_status === 'decommissioned' ? 'text-slate-400' : a.lifecycle_status === 'maintenance' ? 'text-amber-600' : 'text-blue-500'}`}>
                                <span className={`h-1.5 w-1.5 rounded-full ${a.lifecycle_status === 'production' ? 'bg-emerald-500' : a.lifecycle_status === 'decommissioned' ? 'bg-slate-400' : a.lifecycle_status === 'maintenance' ? 'bg-amber-500' : 'bg-blue-400'}`} />
                                {LIFECYCLE_STATUSES.find(l => l.value === a.lifecycle_status)?.label[zh ? 'zh' : 'en'] || (zh ? '待投产' : 'Staging')}
                                {a.is_managed === 1 && <span title={zh ? '凭据受管' : 'Managed'}><Lock size={8} className="text-emerald-500/50" /></span>}
                              </span>
                              {a.takeover_error && (
                                <div className="flex items-center gap-1 text-[8px] text-red-500 font-medium bg-red-50 px-1 rounded truncate max-w-[60px]" title={a.takeover_error}>
                                  <AlertTriangle size={8} /><span>{a.takeover_error}</span>
                                </div>
                              )}
                            </div>
                          )}
                        </td>
                        <td className="px-1.5 py-1 text-[9px] text-black/30 capitalize">{a.device_role || '—'}</td>
                        <td className="px-1.5 py-1 text-[10px] text-black/30 truncate max-w-[80px]">
                          {a.datacenter || '—'}
                          {a.rack && <span className="text-black/15 block text-[9px]">{a.rack}{a.rack_unit ? `U${a.rack_unit}` : ''}</span>}
                        </td>
                        <td className="px-1.5 py-1 text-[10px] text-black/30 truncate max-w-[80px]">{a.department || '—'}</td>
                        <td className="px-1.5 py-1 text-[10px] tabular-nums">
                          {a.warranty_expiry ? (
                            <span className={new Date(a.warranty_expiry) <= new Date(Date.now() + 90 * 86400000) ? 'text-red-500 font-semibold' : 'text-black/30'}>{a.warranty_expiry}</span>
                          ) : <span className="text-black/12">—</span>}
                        </td>
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
                        let url = '';
                        let user = '';
                        let host = '';

                        if (terminalTarget) {
                          user = terminalAccessLevel === 'admin' ? (terminalTarget.admin_username || 'admin') : (terminalTarget.normal_username || 'user');
                          host = terminalTarget.management_ip;
                        } else if (terminalSession.title.includes('@')) {
                          const [u, h] = terminalSession.title.split('@');
                          user = u;
                          host = h.split(':')[0];
                        }

                        if (host && user) {
                          let sessionToken = '';
                          try {
                            const res = await fetch('/api/system/launch-terminal', {
                              method: 'POST',
                              headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify({
                                app_type: terminalType,
                                path: '__client_side_launch__',
                                host, user,
                                requester_username: 'unknown',
                                access_level: terminalTarget ? terminalAccessLevel : 'normal',
                              })
                            });
                            const result = await res.json();
                            if (result.success && result.session_token) {
                              sessionToken = result.session_token;
                            }
                          } catch (err) {
                            console.error(err);
                          }

                          if (terminalType !== 'standard') {
                            const isSsl = window.location.protocol === 'https:' ? '1' : '0';
                            url = `nexora://${window.location.host}?token=${sessionToken}&client=${terminalType}&path=${encodeURIComponent(terminalPath)}&ssl=${isSsl}`;
                          } else {
                            url = `ssh://${encodeURIComponent(user)}@${host}:22`;
                          }
                        }

                        if (url) {
                          window.location.href = url;
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

      {/* Batch Tag */}
      <BatchTagModal
        isOpen={showBatchTag}
        onClose={() => setShowBatchTag(false)}
        selectedCount={selectedIds.size}
        batchTagValue={batchTagValue}
        setBatchTagValue={setBatchTagValue}
        batchTag={batchTag}
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
