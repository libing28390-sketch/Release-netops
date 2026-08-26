import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  ArrowLeftRight,
  Boxes,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  Database,
  Download,
  FileCheck2,
  FileWarning,
  FolderTree,
  GitBranch,
  Link2,
  Loader2,
  RotateCcw,
  Search,
  Server,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
  Tag,
  X,
  Zap,
  Maximize2,
  Minimize2,
  ChevronUp,
  ChevronDown,
  PanelRightClose,
  PanelRightOpen,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { ActionButton } from '../components/ui/ActionIconButton';
import type { DiffLine } from '../types';
import Pagination from '../components/Pagination';
import PageHero from '../components/PageHero';
import { GitCompare } from 'lucide-react';
import { apiRequest, authHeaders } from '../api/http';

/* ── shared interfaces (kept compatible with App.tsx) ── */

interface DiffSnapshot {
  id: string;
  device_id?: string;
  hostname: string;
  ip_address?: string;
  timestamp: string;
  trigger?: string;
  content?: string;
  size?: number;
  vendor?: string;
  is_baseline?: number | boolean;
  integrity_status?: string;
  validation_status?: string;
  validation_message?: string;
  config_type?: string;
  collection_source?: string;
  collection_task_id?: string;
  change_ticket_id?: string;
  line_count?: number;
}

interface DiffRenderEntry {
  line: DiffLine;
  originalIndex: number;
}

interface FullSideBySideRow {
  originalIndex: number;
  rowType: 'context' | 'add' | 'remove';
  leftLine: number | null;
  rightLine: number | null;
  leftContent: string;
  rightContent: string;
}

interface DiffChangeBlock {
  startChangeIdx: number;
  endChangeIdx: number;
  label: string;
}

interface BackupDevice {
  id: string;
  hostname: string;
  ip_address: string;
  platform: string;
  status: string;
  backup_count: number;
  latest_backup: string;
  site_id?: string;
  site_name?: string;
  site_code?: string;
  asset_type?: string;
  device_category?: string;
  device_role?: string;
}

interface DeviceScopeTreeNode {
  id: string;
  kind: 'root' | 'site' | 'type' | 'category' | 'role';
  label: string;
  count: number;
  branch: {
    site_id?: string;
    asset_type?: string;
    device_category?: string;
    device_role?: string;
  };
  children: DeviceScopeTreeNode[];
}

interface StructuredObjectChange {
  id: string;
  object_type: string;
  object_name: string;
  module: string;
  change_type: 'added' | 'deleted' | 'modified';
  before_lines: string[];
  after_lines: string[];
  field_changes: Array<{ field: string; before: unknown; after: unknown }>;
  risk_level: string;
  risk_reason: string;
  potential_impact: string;
  requires_secondary_approval: boolean;
  requires_mfa: boolean;
}

interface StructuredRisk {
  rule_id: string;
  severity: string;
  message: string;
  potential_impact: string;
  object_type: string;
  object_name: string;
  requires_secondary_approval: boolean;
  requires_mfa: boolean;
}

interface StructuredAnalysis {
  device: BackupDevice & { vendor?: string; role?: string; site?: string };
  snapshot_a: DiffSnapshot;
  snapshot_b: DiffSnapshot;
  direction: string;
  direction_reversed: boolean;
  validation: {
    a: { status: string; valid_for_auto_compare: boolean; issues: Array<{ message: string }> };
    b: { status: string; valid_for_auto_compare: boolean; issues: Array<{ message: string }> };
  };
  summary: {
    added_lines: number;
    removed_lines: number;
    changed_objects: number;
    affected_modules: number;
    high_risk_changes: number;
    module_counts: Record<string, number>;
    object_counts: Record<string, number>;
    risk_counts: Record<string, number>;
  };
  objects: StructuredObjectChange[];
  risks: StructuredRisk[];
  compliance: {
    compliant_count: number;
    noncompliant_count: number;
    compliance_rate: number;
    findings: Array<{
      rule_id: string;
      name: string;
      status: string;
      severity: string;
      observed_count: number;
      expected_count: number;
      remediation: string;
    }>;
  };
  source_correlation: {
    correlations: Array<{
      source_type: string;
      source_id: string;
      label: string;
      status: string;
      actor: string;
      timestamp: string;
    }>;
    out_of_band_suspected: boolean;
    message: string;
  };
  running_startup_sync: boolean | null;
  requires_secondary_approval: boolean;
  requires_mfa: boolean;
  cache: { hit: boolean; key: string };
}

interface RollbackPlan {
  mode: string;
  plan_id: string;
  line_count: number;
  executable: boolean;
  requires_change_order: boolean;
  requires_mfa: boolean;
  requires_pre_restore_backup: boolean;
  requires_rollback_timer: boolean;
  blockers: string[];
  warning?: string;
}

interface ConfigDiffViewTabProps {
  t: (key: string) => string;
  language: string;
  /* diff viewer data (unchanged) */
  activeDiffLines: DiffLine[];
  activeChangeLineIndexes: number[];
  diffFocusChangeIdx: number;
  diffOnlyChanges: boolean;
  diffShowFullBoth: boolean;
  diffMode: 'normalized' | 'raw';
  renderedDiffLines: DiffRenderEntry[];
  fullSideBySideRows: FullSideBySideRow[];
  diffChangeBlocks: DiffChangeBlock[];
  filteredDiffChangeBlocks: DiffChangeBlock[];
  diffBlockQuery: string;
  diffLineRefs: React.MutableRefObject<Record<number, HTMLDivElement | null>>;
  /* selected snapshots (managed by parent) */
  configDiffLeft: DiffSnapshot | null;
  configDiffRight: DiffSnapshot | null;
  /* callbacks */
  onReset: () => void;
  onSelectSnapshotPair: (leftId: string, rightId: string) => Promise<void> | void;
  onJumpToDiff: (direction: 'prev' | 'next') => void;
  onToggleOnlyChanges: () => void;
  onToggleFullBoth: () => void;
  onDiffModeChange: (mode: 'normalized' | 'raw') => void;
  onDiffBlockQueryChange: (value: string) => void;
  onToggleQuickKeyword: (keyword: string) => void;
  onFocusDiffChangeAt: (changeIdx: number) => void;
  /* optional: pre-selected device from backup center */
  preSelectedDeviceId?: string;
}

const ConfigDiffViewTab: React.FC<ConfigDiffViewTabProps> = ({
  t,
  language,
  activeDiffLines,
  activeChangeLineIndexes,
  diffFocusChangeIdx,
  diffOnlyChanges,
  diffShowFullBoth,
  diffMode,
  renderedDiffLines,
  fullSideBySideRows,
  diffChangeBlocks,
  filteredDiffChangeBlocks,
  diffBlockQuery,
  diffLineRefs,
  configDiffLeft,
  configDiffRight,
  onReset,
  onSelectSnapshotPair,
  onJumpToDiff,
  onToggleOnlyChanges,
  onToggleFullBoth,
  onDiffModeChange,
  onDiffBlockQueryChange,
  onToggleQuickKeyword,
  onFocusDiffChangeAt,
  preSelectedDeviceId,
}) => {
  const zh = language === 'zh';
  const navigate = useNavigate();
  const safeFocusIdx = activeChangeLineIndexes.length === 0 ? 0 : Math.min(diffFocusChangeIdx, activeChangeLineIndexes.length - 1);
  const focusedLineIndex = activeChangeLineIndexes[safeFocusIdx];
  const added = activeDiffLines.filter((l) => l.type === 'add').length;
  const removed = activeDiffLines.filter((l) => l.type === 'remove').length;

  /* ── Step 1: Device list ── */
  const [deviceSearch, setDeviceSearch] = useState('');
  const [deviceSearchDraft, setDeviceSearchDraft] = useState('');
  const [devices, setDevices] = useState<BackupDevice[]>([]);
  const [devicesTotal, setDevicesTotal] = useState(0);
  const [devicesLoading, setDevicesLoading] = useState(false);
  const [devPage, setDevPage] = useState(1);
  const [devPageSize, setDevPageSize] = useState(15);
  const [selectedDevice, setSelectedDevice] = useState<BackupDevice | null>(null);
  const [deviceScopeTree, setDeviceScopeTree] = useState<DeviceScopeTreeNode[]>([]);
  const [expandedDeviceTree, setExpandedDeviceTree] = useState<Set<string>>(new Set(['root']));
  const [deviceTreeCollapsed, setDeviceTreeCollapsed] = useState(false);
  const [deviceBranch, setDeviceBranch] = useState<DeviceScopeTreeNode['branch']>({});

  /* ── Step 2: Snapshot list for selected device ── */
  const [snapshots, setSnapshots] = useState<DiffSnapshot[]>([]);
  const [snapshotsLoading, setSnapshotsLoading] = useState(false);
  const [pickLeft, setPickLeft] = useState<string | null>(null);
  const [pickRight, setPickRight] = useState<string | null>(null);
  const [baselineSaving, setBaselineSaving] = useState('');
  const deviceAbortRef = React.useRef<AbortController | null>(null);
  const [analysis, setAnalysis] = useState<StructuredAnalysis | null>(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState('');
  const [analysisView, setAnalysisView] = useState<'text' | 'objects' | 'risks'>('objects');
  const [objectFilter, setObjectFilter] = useState('all');
  const [riskFilter, setRiskFilter] = useState('all');
  const [exporting, setExporting] = useState('');
  const [confirming, setConfirming] = useState(false);
  const [rollbackPlan, setRollbackPlan] = useState<RollbackPlan | null>(null);
  const [rollbackLoading, setRollbackLoading] = useState(false);

  /* ── Diff viewer layout & readability state ── */
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [metricsCollapsed, setMetricsCollapsed] = useState(false);
  const [changeMapVisible, setChangeMapVisible] = useState(true);
  const [fontSize, setFontSize] = useState<'xs' | 'sm' | 'base'>('xs');
  const [wrapLines, setWrapLines] = useState(false);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isFullscreen) {
        setIsFullscreen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isFullscreen]);

  /* ── Load devices ── */
  const loadDevices = useCallback(async (q = '', pg = devPage, ps = devPageSize, branch = deviceBranch) => {
    deviceAbortRef.current?.abort();
    const controller = new AbortController();
    deviceAbortRef.current = controller;
    setDevicesLoading(true);
    try {
      const params = new URLSearchParams({ page: String(pg), page_size: String(ps) });
      if (q.trim()) params.set('search', q.trim());
      Object.entries(branch).forEach(([key, value]) => {
        if (value) params.set(key, value);
      });
      const resp = await fetch(`/api/configs/devices-with-backups?${params}`, { signal: controller.signal });
      if (resp.ok) {
        const data = await resp.json();
        setDevices(data.items || []);
        setDevicesTotal(data.total || 0);
        setDeviceScopeTree(data.tree || []);
      }
    } catch (error) {
      if (!(error instanceof DOMException && error.name === 'AbortError')) {
        // The page already has a meaningful empty/loading state; keep network
        // failures quiet here so a transient request does not replace it.
      }
    } finally {
      if (!controller.signal.aborted) setDevicesLoading(false);
    }
  }, [deviceBranch, devPage, devPageSize]);

  useEffect(() => {
    void loadDevices(deviceSearch);
    return () => deviceAbortRef.current?.abort();
  }, [loadDevices, deviceSearch]);

  const submitDeviceSearch = () => {
    setDevPage(1);
    setDeviceSearch(deviceSearchDraft.trim());
  };

  const toggleDeviceTreeNode = (nodeId: string) => {
    setExpandedDeviceTree((current) => {
      const next = new Set(current);
      if (next.has(nodeId)) next.delete(nodeId);
      else next.add(nodeId);
      return next;
    });
  };

  const selectDeviceBranch = (node: DeviceScopeTreeNode) => {
    setDeviceBranch(node.branch || {});
    setDevPage(1);
  };

  /* ── Pre-select device from backup center navigation ── */
  useEffect(() => {
    if (preSelectedDeviceId && devices.length > 0 && !selectedDevice) {
      const found = devices.find(d => d.id === preSelectedDeviceId);
      if (found) handleSelectDevice(found);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preSelectedDeviceId, devices]);

  /* ── Load snapshots for selected device ── */
  const loadSnapshots = useCallback(async (deviceId: string, autoCompare = false) => {
    setSnapshotsLoading(true);
    try {
      const data = await apiRequest<DiffSnapshot[]>(`/api/config-drift/device/${encodeURIComponent(deviceId)}/snapshots`);
      const sorted = data.sort((a, b) => b.timestamp.localeCompare(a.timestamp));
      setSnapshots(sorted);
      
      const valid = sorted.filter((snapshot) => (
        !['invalid', 'corrupt'].includes(String(snapshot.integrity_status || '').toLowerCase())
        && !['invalid', 'empty', 'command_error', 'permission_denied', 'connection_interrupted'].includes(String(snapshot.validation_status || '').toLowerCase())
        && (snapshot.config_type || 'running') === 'running'
      ));
      if (valid.length >= 2) {
        const latest = valid[0];
        const previous = valid[1];
        setPickLeft(previous.id);
        setPickRight(latest.id);
        if (autoCompare) {
          await onSelectSnapshotPair(previous.id, latest.id);
        }
      } else if (valid.length === 1) {
        setPickRight(valid[0].id);
      }
    } catch (error) {
      setAnalysisError(error instanceof Error ? error.message : (zh ? '快照加载失败' : 'Failed to load snapshots'));
    }
    finally { setSnapshotsLoading(false); }
  }, [onSelectSnapshotPair, zh]);

  const handleSelectDevice = (dev: BackupDevice, autoCompare = false) => {
    setSelectedDevice(dev);
    setPickLeft(null);
    setPickRight(null);
    setAnalysis(null);
    setAnalysisError('');
    setRollbackPlan(null);
    onReset();
    void loadSnapshots(dev.id, autoCompare);
  };

  const handleBackToDevices = () => {
    setSelectedDevice(null);
    setSnapshots([]);
    setPickLeft(null);
    setPickRight(null);
    setAnalysis(null);
    setAnalysisError('');
    setRollbackPlan(null);
    onReset();
  };

  /* ── Snapshot pick ── */
  const handlePickSnapshot = (side: 'left' | 'right', snapId: string) => {
    if (side === 'left') {
      setPickLeft(snapId);
      if (pickRight === snapId) setPickRight(null);
    } else {
      setPickRight(snapId);
      if (pickLeft === snapId) setPickLeft(null);
    }
  };

  /* ── Smart click: auto-assign A then B ── */
  const handleSmartPick = (snapId: string) => {
    if (!pickLeft) {
      setPickLeft(snapId);
    } else if (pickLeft === snapId) {
      setPickLeft(null);
    } else if (!pickRight) {
      setPickRight(snapId);
    } else if (pickRight === snapId) {
      setPickRight(null);
    } else {
      // both set, replace B
      setPickRight(snapId);
    }
  };

  /* ── Start compare ── */
  const handleStartCompare = async () => {
    if (!pickLeft || !pickRight) return;
    await onSelectSnapshotPair(pickLeft, pickRight);
  };

  const handleSetBaseline = async (snapshotId: string) => {
    if (!selectedDevice) return;
    setBaselineSaving(snapshotId);
    try {
      await apiRequest(
        `/api/config-drift/device/${encodeURIComponent(selectedDevice.id)}/baseline`,
        {
          method: 'PUT',
          body: JSON.stringify({
            snapshot_id: snapshotId,
            description: zh ? '从配置对比页面设为基准' : 'Designated from config comparison',
          }),
        },
      );
      setPickLeft(snapshotId);
      await loadSnapshots(selectedDevice.id);
    } finally {
      setBaselineSaving('');
    }
  };

  /* ── Quick compare: latest two ── */
  const handleQuickCompare = async () => {
    if (snapshots.length < 2) return;
    const leftId = snapshots[1].id;
    const rightId = snapshots[0].id;
    setPickLeft(leftId);
    setPickRight(rightId);
    await onSelectSnapshotPair(leftId, rightId);
  };

  const analysisDeviceId = selectedDevice?.id || configDiffLeft?.device_id || configDiffRight?.device_id || '';

  const loadStructuredAnalysis = useCallback(async (forceRefresh = false) => {
    if (!analysisDeviceId || !configDiffLeft?.id || !configDiffRight?.id) return;
    setAnalysisLoading(true);
    setAnalysisError('');
    try {
      const result = await apiRequest<StructuredAnalysis>('/api/config-diff/analysis', {
        method: 'POST',
        body: JSON.stringify({
          device_id: analysisDeviceId,
          snapshot_a_id: configDiffLeft.id,
          snapshot_b_id: configDiffRight.id,
          mode: diffMode,
          force_refresh: forceRefresh,
        }),
      });
      setAnalysis(result);
      setRollbackPlan(null);
    } catch (error) {
      setAnalysis(null);
      setAnalysisError(error instanceof Error ? error.message : (zh ? '结构化差异分析失败' : 'Structured analysis failed'));
    } finally {
      setAnalysisLoading(false);
    }
  }, [analysisDeviceId, configDiffLeft?.id, configDiffRight?.id, diffMode, zh]);

  useEffect(() => {
    if (configDiffLeft && configDiffRight) {
      void loadStructuredAnalysis(false);
    } else {
      setAnalysis(null);
      setAnalysisError('');
    }
  }, [configDiffLeft, configDiffRight, loadStructuredAnalysis]);

  const exportAnalysis = useCallback(async (format: 'markdown' | 'html' | 'json') => {
    if (!analysisDeviceId || !configDiffLeft?.id || !configDiffRight?.id) return;
    setExporting(format);
    try {
      const response = await fetch(`/api/config-diff/export?format=${format}`, {
        method: 'POST',
        headers: authHeaders(true),
        body: JSON.stringify({
          device_id: analysisDeviceId,
          snapshot_a_id: configDiffLeft.id,
          snapshot_b_id: configDiffRight.id,
          mode: diffMode,
        }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || `HTTP ${response.status}`);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `config-diff-${new Date().toISOString().slice(0, 10)}.${format === 'markdown' ? 'md' : format}`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      setAnalysisError(error instanceof Error ? error.message : (zh ? '差异报告导出失败' : 'Failed to export report'));
    } finally {
      setExporting('');
    }
  }, [analysisDeviceId, configDiffLeft?.id, configDiffRight?.id, diffMode, zh]);

  const confirmAnalysis = useCallback(async () => {
    if (!analysisDeviceId || !configDiffLeft?.id || !configDiffRight?.id) return;
    setConfirming(true);
    try {
      await apiRequest('/api/config-diff/confirm', {
        method: 'POST',
        body: JSON.stringify({
          device_id: analysisDeviceId,
          snapshot_a_id: configDiffLeft.id,
          snapshot_b_id: configDiffRight.id,
          status: 'confirmed',
          note: zh ? '在配置差异分析页面确认' : 'Confirmed in configuration diff analysis',
        }),
      });
    } catch (error) {
      setAnalysisError(error instanceof Error ? error.message : (zh ? '确认失败' : 'Confirmation failed'));
    } finally {
      setConfirming(false);
    }
  }, [analysisDeviceId, configDiffLeft?.id, configDiffRight?.id, zh]);

  const prepareRollback = useCallback(async () => {
    if (!analysisDeviceId || !configDiffLeft?.id) return;
    setRollbackLoading(true);
    try {
      const result = await apiRequest<RollbackPlan>('/api/config-drift/rollback-preview', {
        method: 'POST',
        body: JSON.stringify({
          device_id: analysisDeviceId,
          snapshot_id: configDiffLeft.id,
          selected_lines: [],
        }),
      });
      setRollbackPlan(result);
    } catch (error) {
      setAnalysisError(error instanceof Error ? error.message : (zh ? '回滚方案预检失败' : 'Rollback preflight failed'));
    } finally {
      setRollbackLoading(false);
    }
  }, [analysisDeviceId, configDiffLeft?.id, zh]);

  const filteredObjects = useMemo(() => (
    (analysis?.objects || []).filter((item) => objectFilter === 'all' || item.object_type === objectFilter)
  ), [analysis?.objects, objectFilter]);

  const filteredRisks = useMemo(() => (
    (analysis?.risks || []).filter((item) => riskFilter === 'all' || item.severity === riskFilter)
  ), [analysis?.risks, riskFilter]);

  const parseIsoDate = (ts?: string | null): Date | null => {
    if (!ts) return null;
    let s = String(ts).trim();
    if (!s) return null;
    if (s.includes('T') && !s.endsWith('Z') && !/[+-]\d{2}:?\d{2}$/.test(s)) {
      s = s + 'Z';
    }
    const d = new Date(s);
    return Number.isNaN(d.getTime()) ? null : d;
  };

  const formatTime = (ts: string) => {
    if (!ts) return '--';
    const d = parseIsoDate(ts);
    return d ? d.toLocaleString(zh ? 'zh-CN' : 'en-US', { hour12: false }) : ts;
  };

  const formatSize = (size?: number) => {
    if (!size) return '';
    if (size >= 1048576) return `${(size / 1048576).toFixed(1)} MB`;
    if (size >= 1024) return `${(size / 1024).toFixed(1)} KB`;
    return `${size} B`;
  };

  const timeSince = (ts: string) => {
    if (!ts) return '';
    const d = parseIsoDate(ts);
    if (!d) return '';
    try {
      const diff = Date.now() - d.getTime();
      const hours = Math.floor(diff / 3600000);
      if (hours < 1) return zh ? '刚刚' : 'Just now';
      if (hours < 24) return zh ? `${hours}h前` : `${hours}h ago`;
      const days = Math.floor(hours / 24);
      if (days < 30) return zh ? `${days}天前` : `${days}d ago`;
      return zh ? `${Math.floor(days / 30)}月前` : `${Math.floor(days / 30)}mo ago`;
    } catch { return ''; }
  };

  const showDiffViewer = configDiffLeft && configDiffRight;

  const scopeLabel = (node: DeviceScopeTreeNode) => {
    const labels: Record<string, string> = {
      network_device: zh ? '网络设备' : 'Network devices',
      server: zh ? '服务器' : 'Servers',
      other: zh ? '其他资产' : 'Other assets',
      router: zh ? '路由器' : 'Routers',
      switch: zh ? '交换机' : 'Switches',
      firewall: zh ? '防火墙' : 'Firewalls',
      load_balancer: zh ? '负载均衡' : 'Load balancers',
      unassigned: zh ? '未分配' : 'Unassigned',
    };
    return labels[node.label] || node.label;
  };

  const renderDeviceScopeNode = (node: DeviceScopeTreeNode, depth = 0): React.ReactNode => {
    const expanded = expandedDeviceTree.has(node.id);
    const selected = JSON.stringify(deviceBranch) === JSON.stringify(node.branch || {});
    const Icon = node.kind === 'root' ? Database : node.kind === 'site' ? FolderTree : node.kind === 'type' ? Server : node.kind === 'category' ? Boxes : Tag;
    return (
      <div key={node.id}>
        <div className={`group flex items-center gap-1.5 rounded-lg px-2 py-2 text-xs ${selected ? 'bg-cyan-50 text-cyan-800' : 'text-slate-600 hover:bg-slate-50'}`} style={{ paddingLeft: `${8 + depth * 13}px` }}>
          {node.children.length > 0 ? (
            <button type="button" onClick={() => toggleDeviceTreeNode(node.id)} className="shrink-0 text-slate-400" aria-label={expanded ? 'Collapse' : 'Expand'}>
              <ChevronRight size={14} className={expanded ? 'rotate-90 transition-transform' : 'transition-transform'} />
            </button>
          ) : <span className="w-[14px]" />}
          <button type="button" onClick={() => selectDeviceBranch(node)} className="flex min-w-0 flex-1 items-center gap-2 text-left">
            <Icon size={14} className={node.kind === 'site' ? 'text-cyan-600' : node.kind === 'type' ? 'text-indigo-500' : 'text-slate-400'} />
            <span className="truncate">{node.kind === 'root' ? (zh ? '全部资产' : 'All assets') : scopeLabel(node)}</span>
            <span className="ml-auto rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] tabular-nums text-slate-500">{node.count}</span>
          </button>
        </div>
        {expanded && node.children.map((child) => renderDeviceScopeNode(child, depth + 1))}
      </div>
    );
  };

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex-1 overflow-hidden p-1.5 sm:p-2.5 flex flex-col">
      <div className="flex-1 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xs flex flex-col">
        {/* ════════ Step 1 + 2: Selection area ════════ */}
        {!showDiffViewer && (
          <div className="flex-1 overflow-auto">
            {!selectedDevice ? (
              /* ──── Step 1: Streamlined Device list ──── */
              <div className="flex flex-col h-full bg-[#f7fbfc]">
                {/* ── Sleek Compact Header (~42px) ── */}
                <div className="flex h-11 items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 text-xs shrink-0">
                  <div className="flex items-center gap-2">
                    <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-cyan-50 text-cyan-700">
                      <Server size={14} />
                    </div>
                    <span className="font-sans text-xs font-black text-[#123b50]">{zh ? '选择审计设备' : 'Select Device'}</span>
                    <span className="rounded-full bg-cyan-50 px-2 py-0.5 font-sans text-[10px] font-bold text-cyan-700 tabular-nums">
                      {devicesTotal} {zh ? '台设备' : 'devices'}
                    </span>
                  </div>

                  <div className="flex items-center gap-2">
                    <div className="relative w-48 sm:w-72">
                      <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
                      <input
                        value={deviceSearchDraft}
                        onChange={(e) => setDeviceSearchDraft(e.target.value)}
                        onKeyDown={(e) => { if (e.key === 'Enter') submitDeviceSearch(); }}
                        placeholder={zh ? '搜索主机名或 IP (回车)' : 'Search hostname / IP (Enter)'}
                        className="w-full rounded-lg border border-slate-200 bg-slate-50 py-1 pl-8 pr-7 text-xs text-[#123b50] outline-none placeholder:text-slate-400 focus:border-cyan-300 focus:bg-white"
                      />
                      {deviceSearchDraft && (
                        <button onClick={() => { setDeviceSearchDraft(''); setDeviceSearch(''); setDevPage(1); }} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700">
                          <X size={12} />
                        </button>
                      )}
                    </div>
                    <button onClick={submitDeviceSearch} className="inline-flex items-center gap-1 rounded-lg bg-[#123b50] px-2.5 py-1 text-xs font-bold text-white hover:bg-[#0b2d3e] transition-colors">
                      <Search size={11} />{zh ? '搜索' : 'Search'}
                    </button>
                    <div className="h-4 w-px bg-slate-200" />
                    <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-0.5 text-[9px]">
                      {(['normalized', 'raw'] as const).map((mode) => (
                        <button key={mode} type="button" onClick={() => onDiffModeChange(mode)} className={`rounded px-1.5 py-0.5 font-bold transition-colors ${diffMode === mode ? 'bg-[#123b50] text-white shadow-xs' : 'text-slate-500 hover:text-[#123b50]'}`}>
                          {mode === 'normalized' ? (zh ? '标准化' : 'Norm') : (zh ? '原始' : 'Raw')}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>

                {/* ── Main Layout: Asset Tree + Device Table ── */}
                <div className="flex-1 min-h-0 overflow-hidden p-2.5 flex gap-3">
                  <aside className={`rounded-xl border border-slate-200 bg-white shadow-xs flex flex-col shrink-0 overflow-hidden transition-all ${deviceTreeCollapsed ? 'w-12' : 'w-64'}`}>
                    <div className="flex h-9 items-center justify-between border-b border-slate-100 px-3 shrink-0">
                      {!deviceTreeCollapsed && <span className="font-sans text-[11px] font-bold text-slate-700">{zh ? '资产分类' : 'Asset Tree'}</span>}
                      <button type="button" onClick={() => setDeviceTreeCollapsed((c) => !c)} className="rounded p-1 text-slate-400 hover:bg-cyan-50 hover:text-cyan-700 ml-auto" title={deviceTreeCollapsed ? (zh ? '展开资产树' : 'Expand') : (zh ? '折叠资产树' : 'Collapse')}>
                        {deviceTreeCollapsed ? <FolderTree size={14} /> : <ChevronRight size={14} className="rotate-180" />}
                      </button>
                    </div>
                    {!deviceTreeCollapsed && (
                      <div className="flex-1 overflow-y-auto p-1.5">
                        {deviceScopeTree.length ? deviceScopeTree.map((node) => renderDeviceScopeNode(node)) : <p className="py-8 text-center text-[10px] text-slate-400">{zh ? '暂无分类' : 'No categories'}</p>}
                      </div>
                    )}
                  </aside>

                  <div className="flex-1 min-h-0 flex flex-col rounded-xl border border-slate-200 bg-white shadow-xs overflow-hidden">
                    <div className="grid grid-cols-[minmax(200px,1.8fr)_minmax(120px,1fr)_80px_130px_110px] items-center gap-x-3 px-4 py-2 bg-slate-50/90 text-[10px] font-bold uppercase tracking-wider text-slate-400 border-b border-slate-100 shrink-0">
                      <span>{zh ? '设备资产' : 'Device'}</span>
                      <span>{zh ? '平台' : 'Platform'}</span>
                      <span>{zh ? '快照数' : 'Snapshots'}</span>
                      <span>{zh ? '最近备份' : 'Last backup'}</span>
                      <span className="text-right">{zh ? '操作' : 'Actions'}</span>
                    </div>

                    <div className="flex-1 overflow-y-auto">
                      {devicesLoading ? (
                        <div className="py-20 text-center text-xs text-slate-400 flex items-center justify-center gap-2">
                          <RotateCcw size={14} className="animate-spin text-cyan-500" />{zh ? '正在加载设备资产...' : 'Loading devices...'}
                        </div>
                      ) : devices.length === 0 ? (
                        <div className="py-20 text-center text-slate-400">
                          <Database size={24} className="mx-auto mb-2 text-slate-300" />
                          <p className="text-xs font-bold text-slate-600">{deviceSearch ? (zh ? '没有匹配的设备' : 'No matching devices') : (zh ? '暂无配置备份' : 'No config backups')}</p>
                        </div>
                      ) : (
                        devices.map((dev) => {
                          const online = dev.status === 'online';
                          return (
                            <div
                              key={dev.id}
                              onClick={() => handleSelectDevice(dev, false)}
                              className="group w-full text-left grid grid-cols-[minmax(200px,1.8fr)_minmax(120px,1fr)_80px_130px_110px] items-center gap-x-3 px-4 py-2.5 border-b border-slate-100 last:border-b-0 hover:bg-cyan-50/40 transition-colors cursor-pointer"
                            >
                              <div className="flex items-center gap-2.5 min-w-0">
                                <div className={`flex h-7 w-7 items-center justify-center rounded-lg ${online ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600'} shrink-0`}>
                                  <Server size={13} />
                                </div>
                                <div className="min-w-0">
                                  <div className="flex items-center gap-1.5">
                                    <span className="truncate text-xs font-bold text-[#123b50]">{dev.hostname}</span>
                                    <span className={`h-1.5 w-1.5 rounded-full ${online ? 'bg-emerald-500' : 'bg-amber-400'}`} />
                                  </div>
                                  <span className="block truncate text-[10px] font-mono text-slate-400">{dev.ip_address}</span>
                                </div>
                              </div>
                              <span className="truncate rounded bg-slate-50 px-2 py-0.5 text-[10px] font-semibold text-slate-600 max-w-[130px]">{dev.platform || '--'}</span>
                              <span className="inline-flex w-fit items-center gap-1 rounded-full bg-cyan-50 px-2 py-0.5 text-[10px] font-bold text-cyan-700 tabular-nums">
                                <Database size={10} />{dev.backup_count}
                              </span>
                              <span className="text-[10px] text-slate-500 whitespace-nowrap">
                                <span className="block font-semibold text-slate-600">{timeSince(dev.latest_backup) || '--'}</span>
                              </span>
                              <div className="flex items-center justify-end gap-1.5">
                                {dev.backup_count >= 2 && (
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleSelectDevice(dev, true);
                                    }}
                                    className="inline-flex items-center gap-0.5 rounded-md border border-cyan-200 bg-cyan-50 px-2 py-0.5 text-[9px] font-bold text-cyan-700 hover:bg-cyan-100 transition-colors"
                                    title={zh ? '一键直接对比最近两次快照' : 'Directly compare latest 2'}
                                  >
                                    <Zap size={10} />
                                    {zh ? '对比最新' : 'Compare'}
                                  </button>
                                )}
                                <ChevronRight size={14} className="text-slate-300 group-hover:translate-x-0.5 group-hover:text-cyan-600 transition-all" />
                              </div>
                            </div>
                          );
                        })
                      )}
                    </div>

                    {devicesTotal > devPageSize && (
                      <div className="border-t border-slate-100 bg-white px-3 py-2 shrink-0">
                        <Pagination currentPage={devPage} totalItems={devicesTotal} itemsPerPage={devPageSize} onPageChange={setDevPage} onItemsPerPageChange={(v) => { setDevPage(1); setDevPageSize(v); }} language={language} />
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              /* ──── Step 2: Streamlined Snapshot selection ──── */
              <div className="flex flex-col h-full bg-[#f7fbfc]">
                {/* ── Compact Header (~40px) ── */}
                <div className="flex h-10 items-center justify-between gap-2 border-b border-slate-200 bg-white px-4 text-xs shrink-0">
                  <div className="flex items-center gap-2 min-w-0">
                    <button onClick={handleBackToDevices} className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] font-bold text-slate-700 hover:bg-slate-100 transition-colors shrink-0">
                      <ChevronLeft size={13} /> {zh ? '返回设备' : 'Devices'}
                    </button>
                    <div className="h-3.5 w-px bg-slate-200 shrink-0" />
                    <span className="text-xs font-bold text-[#123b50] truncate">{selectedDevice.hostname}</span>
                    <span className="text-[10px] font-mono text-slate-400 hidden sm:inline">{selectedDevice.ip_address}</span>
                    <span className="text-[9px] font-semibold text-slate-500 rounded bg-slate-100 px-1.5 py-0.5 hidden md:inline">{selectedDevice.platform || ''}</span>
                    <span className="rounded-full bg-cyan-50 px-2 py-0.2 text-[9px] font-bold text-cyan-700">{snapshots.length} {zh ? '份快照' : 'snapshots'}</span>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      type="button"
                      onClick={async () => {
                        const runningSnap = snapshots.find(s => (s.config_type || 'running') === 'running');
                        const startupSnap = snapshots.find(s => s.config_type === 'startup');
                        if (runningSnap && startupSnap) {
                          setPickLeft(startupSnap.id);
                          setPickRight(runningSnap.id);
                          await onSelectSnapshotPair(startupSnap.id, runningSnap.id);
                        } else {
                          setAnalysisError(zh ? '该设备暂无启动配置快照，请在备份策略中开启“启动配置采集”后执行备份。' : 'No startup config snapshot found.');
                        }
                      }}
                      className="inline-flex items-center gap-1 rounded-lg border border-cyan-200 bg-cyan-50 px-2.5 py-1 text-[10px] font-bold text-cyan-700 hover:bg-cyan-100 transition-colors"
                      title={zh ? '对比启动配置与运行配置' : 'Compare Startup vs Running'}
                    >
                      <ArrowLeftRight size={11} />
                      {zh ? '启动 vs 运行' : 'Startup vs Running'}
                    </button>

                    {snapshots.length >= 2 && (
                      <button
                        onClick={() => void handleQuickCompare()}
                        className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-[10px] font-bold text-slate-700 hover:bg-slate-50 transition-colors"
                      >
                        <Zap size={11} className="text-amber-500" />
                        {zh ? '最新两次' : 'Latest 2'}
                      </button>
                    )}

                    <button
                      disabled={!pickLeft || !pickRight}
                      onClick={() => void handleStartCompare()}
                      className="inline-flex items-center gap-1 rounded-lg bg-[#123b50] px-3.5 py-1 text-[11px] font-bold text-white shadow-xs hover:bg-[#0b2d3e] transition-all disabled:opacity-30 disabled:cursor-not-allowed"
                    >
                      <ArrowLeftRight size={12} />
                      {zh ? '开始对比 (A vs B)' : 'Start Diff (A vs B)'}
                    </button>
                  </div>
                </div>

                {snapshotsLoading ? (
                  <div className="flex-1 flex items-center justify-center">
                    <div className="text-xs text-slate-400 flex items-center gap-2">
                      <RotateCcw size={14} className="animate-spin text-cyan-500" /> {zh ? '正在加载快照...' : 'Loading snapshots...'}
                    </div>
                  </div>
                ) : snapshots.length === 0 ? (
                  <div className="flex-1 flex items-center justify-center">
                    <div className="text-center">
                      <Clock size={24} className="mx-auto mb-2 text-slate-300" />
                      <p className="text-xs font-bold text-slate-600">{zh ? '该设备暂无配置备份' : 'No backups yet'}</p>
                    </div>
                  </div>
                ) : snapshots.length < 2 ? (
                  <div className="flex-1 flex items-center justify-center px-5">
                    <div className="text-center max-w-sm">
                      <ArrowLeftRight size={24} className="mx-auto mb-2 text-amber-500" />
                      <p className="text-xs font-bold text-slate-700">{zh ? '需要至少 2 份备份才能对比' : 'Need ≥ 2 Backups'}</p>
                      <p className="mt-1 text-[11px] text-slate-400">{zh ? '当前仅有 1 份快照，请在备份中心再次备份。' : 'Only 1 snapshot exists.'}</p>
                    </div>
                  </div>
                ) : (
                  /* ── Staging bar + Timeline ── */
                  <div className="flex-1 flex flex-col min-h-0">
                    {/* ━━ A vs B compact staging strip ━━ */}
                    {(() => {
                      const snapA = pickLeft ? snapshots.find(s => s.id === pickLeft) : null;
                      const snapB = pickRight ? snapshots.find(s => s.id === pickRight) : null;
                      return (
                        <div className="flex items-center justify-between gap-3 border-b border-slate-200 bg-gradient-to-r from-cyan-50/50 via-white to-sky-50/50 px-4 py-2 text-xs shrink-0">
                          <div className="flex items-center gap-2 flex-1 min-w-0">
                            {/* Pill A */}
                            <div className={`flex items-center gap-2 rounded-lg border px-2.5 py-1 text-xs transition-all ${
                              snapA ? 'border-cyan-300 bg-cyan-50/80 text-[#123b50]' : 'border-dashed border-slate-300 bg-slate-50 text-slate-400'
                            }`}>
                              <span className="flex h-5 w-5 items-center justify-center rounded bg-cyan-600 text-[10px] font-bold text-white">A</span>
                              {snapA ? (
                                <>
                                  <span className="font-semibold text-xs truncate">{formatTime(snapA.timestamp)}</span>
                                  <span className="text-[10px] text-slate-400">({snapA.config_type === 'startup' ? (zh ? '启动' : 'startup') : (zh ? '运行' : 'running')})</span>
                                  <button type="button" onClick={() => setPickLeft(null)} className="text-slate-400 hover:text-red-500"><X size={12} /></button>
                                </>
                              ) : (
                                <span className="text-[11px] text-slate-400">{zh ? '选择基准快照 A' : 'Select Baseline A'}</span>
                              )}
                            </div>

                            <ArrowLeftRight size={13} className="text-slate-400 shrink-0" />

                            {/* Pill B */}
                            <div className={`flex items-center gap-2 rounded-lg border px-2.5 py-1 text-xs transition-all ${
                              snapB ? 'border-sky-300 bg-sky-50/80 text-[#123b50]' : 'border-dashed border-slate-300 bg-slate-50 text-slate-400'
                            }`}>
                              <span className="flex h-5 w-5 items-center justify-center rounded bg-[#123b50] text-[10px] font-bold text-white">B</span>
                              {snapB ? (
                                <>
                                  <span className="font-semibold text-xs truncate">{formatTime(snapB.timestamp)}</span>
                                  <span className="text-[10px] text-slate-400">({snapB.config_type === 'startup' ? (zh ? '启动' : 'startup') : (zh ? '运行' : 'running')})</span>
                                  <button type="button" onClick={() => setPickRight(null)} className="text-slate-400 hover:text-red-500"><X size={12} /></button>
                                </>
                              ) : (
                                <span className="text-[11px] text-slate-400">{zh ? '选择对比快照 B' : 'Select Compare B'}</span>
                              )}
                            </div>
                          </div>

                          <span className="text-[10px] text-slate-400 hidden md:inline">
                            {zh ? '提示: 点击快照行自动分配 A → B，或点击行内 A / B 按钮指定' : 'Click row to assign A then B'}
                          </span>
                        </div>
                      );
                    })()}

                    {/* ━━ Snapshot timeline ━━ */}
                    <div className="flex-1 overflow-y-auto px-4 py-2.5">
                      <div className="space-y-1">
                          {snapshots.map((snap, idx) => {
                            const isLeft = pickLeft === snap.id;
                            const isRight = pickRight === snap.id;
                            const isPicked = isLeft || isRight;
                            const isNewest = idx === 0;
                            return (
                              <div
                                key={snap.id}
                                onClick={() => handleSmartPick(snap.id)}
                                className={`group relative flex items-center gap-2.5 pl-8 pr-3 py-2 rounded-lg cursor-pointer transition-all ${
                                  isPicked
                                    ? isLeft
                                      ? 'bg-[#ecfeff] ring-1 ring-[#06b6d4]/20'
                                      : 'bg-[#f0f9ff] ring-1 ring-[#164e63]/15'
                                    : 'hover:bg-black/[0.02]'
                                }`}
                              >
                                {/* Timeline dot */}
                                <div className="absolute left-2.5 top-1/2 -translate-y-1/2 z-10">
                                  <div className={`h-2 w-2 rounded-full ring-2 ring-white transition-colors ${
                                    isPicked
                                      ? isLeft ? 'bg-[#06b6d4] ring-[#ecfeff]' : 'bg-[#164e63] ring-[#f0f9ff]'
                                      : isNewest ? 'bg-emerald-400' : 'bg-black/12 group-hover:bg-black/20'
                                  }`} />
                                </div>

                                {/* A / B buttons */}
                                <div className="flex items-center gap-0.5 flex-shrink-0">
                                  <button
                                    onClick={(e) => { e.stopPropagation(); handlePickSnapshot('left', snap.id); }}
                                    className={`h-6 w-6 rounded text-[9px] font-bold border transition-all ${
                                      isLeft
                                        ? 'bg-[#06b6d4] border-[#06b6d4] text-white'
                                        : 'border-black/8 text-black/20 hover:border-[#06b6d4]/40 hover:text-[#06b6d4]'
                                    }`}
                                  >A</button>
                                  <button
                                    onClick={(e) => { e.stopPropagation(); handlePickSnapshot('right', snap.id); }}
                                    className={`h-6 w-6 rounded text-[9px] font-bold border transition-all ${
                                      isRight
                                        ? 'bg-[#164e63] border-[#164e63] text-white'
                                        : 'border-black/8 text-black/20 hover:border-[#164e63]/40 hover:text-[#164e63]'
                                    }`}
                                  >B</button>
                                </div>

                                {/* Time + meta inline */}
                                <span className="text-[12px] font-semibold text-[#164e63] tabular-nums">{formatTime(snap.timestamp)}</span>
                                <span className="text-[10px] text-black/20">{timeSince(snap.timestamp)}</span>
                                {snap.config_type === 'startup' ? (
                                  <span className="rounded bg-blue-50 px-1.5 py-px text-[8px] font-bold text-blue-600 border border-blue-100">
                                    {zh ? '启动配置' : 'Startup'}
                                  </span>
                                ) : (
                                  <span className="rounded bg-emerald-50 px-1.5 py-px text-[8px] font-bold text-emerald-600 border border-emerald-100">
                                    {zh ? '运行配置' : 'Running'}
                                  </span>
                                )}
                                {isNewest && (
                                  <span className="rounded bg-emerald-50 px-1 py-px text-[8px] font-bold text-emerald-600">
                                    {zh ? '最新' : 'NEW'}
                                  </span>
                                )}
                                {Boolean(snap.is_baseline) ? (
                                  <span className="rounded bg-cyan-50 px-1.5 py-px text-[8px] font-bold text-cyan-700">
                                    {zh ? '正式基线' : 'BASELINE'}
                                  </span>
                                ) : (
                                  <button
                                    type="button"
                                    disabled={baselineSaving === snap.id}
                                    onClick={(event) => {
                                      event.stopPropagation();
                                      void handleSetBaseline(snap.id);
                                    }}
                                    className="ml-auto hidden rounded border border-black/8 px-1.5 py-0.5 text-[9px] text-black/25 hover:border-cyan-300 hover:text-cyan-700 group-hover:inline-flex disabled:opacity-40"
                                  >
                                    {baselineSaving === snap.id ? '...' : (zh ? '设为基线' : 'Set baseline')}
                                  </button>
                                )}
                                <span className={`hidden sm:inline-flex rounded-full px-1.5 py-px text-[8px] font-bold uppercase ${
                                  snap.trigger === 'manual'
                                    ? 'bg-cyan-50 text-cyan-600'
                                    : snap.trigger === 'scheduled'
                                      ? 'bg-violet-50 text-violet-600'
                                      : 'bg-amber-50 text-amber-600'
                                }`}>
                                  {snap.trigger || 'manual'}
                                </span>
                                {snap.vendor && <span className="hidden sm:inline text-[10px] text-black/25">{snap.vendor}</span>}
                                {snap.size != null && snap.size > 0 && <span className="hidden sm:inline text-[10px] font-mono text-black/20">{formatSize(snap.size)}</span>}

                                {/* Role pill (far right) */}
                                {isPicked && (
                                  <span className={`flex-shrink-0 text-[9px] font-bold ${
                                    isLeft ? 'text-[#06b6d4]' : 'text-[#164e63]'
                                  }`}>
                                    {isLeft ? (zh ? '基准' : 'A') : (zh ? '对比' : 'B')}
                                  </span>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    </div>
                  )}
              </div>
            )}
          </div>
        )}

        {/* ════════ Step 3: Diff viewer (Ultra-compact 2-row header & max viewport) ════════ */}
        {showDiffViewer && (
          <div className={`flex-1 min-h-0 flex flex-col font-mono bg-[#f7fbfc] ${
            isFullscreen ? 'fixed inset-0 z-50 bg-white' : ''
          }`}>
            <div className="h-full flex flex-col min-h-0">
              {/* ── Row 1: Compact Device Info & Global Action Bar (~38px) ── */}
              <div className="flex h-10 items-center justify-between gap-2 border-b border-slate-200 bg-white px-3 text-xs shrink-0">
                <div className="flex min-w-0 items-center gap-2">
                  <button
                    type="button"
                    onClick={() => { onReset(); }}
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] font-bold text-slate-600 hover:bg-slate-100 hover:text-slate-900 transition-colors shrink-0"
                    title={zh ? '重新选择设备或快照' : 'Re-select device or snapshots'}
                  >
                    <ChevronLeft size={13} />
                    {zh ? '重选' : 'Re-select'}
                  </button>
                  <div className="h-3.5 w-px bg-slate-200 shrink-0" />
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="truncate font-sans text-xs font-black text-[#123b50]">{analysis?.device.hostname || configDiffRight.hostname}</span>
                    {analysis?.device.ip_address && <code className="hidden sm:inline text-[10px] text-slate-400 font-mono">{analysis.device.ip_address}</code>}
                    {analysis?.device.platform && <span className="hidden md:inline rounded bg-slate-100 px-1.5 py-0.5 text-[9px] font-bold text-slate-600">{analysis.device.platform}</span>}
                    <span className={`rounded-full px-1.5 py-0.2 text-[8px] font-bold ${analysis?.device.status === 'online' ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>{analysis?.device.status || '—'}</span>
                  </div>
                  <div className="hidden xl:flex items-center gap-1 font-sans text-[10px] text-slate-400 ml-2">
                    <span>{zh ? '对比:' : 'Diff:'}</span>
                    <span className="text-slate-600 font-bold">A ({formatTime(configDiffLeft.timestamp)})</span>
                    <ArrowLeftRight size={10} className="text-slate-300 mx-0.5" />
                    <span className="text-slate-600 font-bold">B ({formatTime(configDiffRight.timestamp)})</span>
                    {analysis?.direction_reversed && <span className="font-bold text-amber-600 ml-1">({zh ? '反向' : 'reversed'})</span>}
                  </div>
                </div>

                <div className="flex items-center gap-1.5 shrink-0">
                  {analysisLoading && <span className="inline-flex items-center gap-1 text-[9px] text-cyan-700 mr-1"><Loader2 size={11} className="animate-spin" />{zh ? '解析中' : 'Parsing'}</span>}
                  <button type="button" onClick={() => void onSelectSnapshotPair(configDiffRight.id, configDiffLeft.id)} className="rounded-lg border border-slate-200 p-1 text-slate-500 hover:border-cyan-300 hover:text-cyan-700 transition-colors" title={zh ? '交换 A/B 对比方向' : 'Swap A/B'}><ArrowLeftRight size={12} /></button>
                  <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-0.5">
                    {(['normalized', 'raw'] as const).map((mode) => (
                      <button key={mode} type="button" onClick={() => onDiffModeChange(mode)} className={`rounded px-1.5 py-0.5 text-[9px] font-bold transition-colors ${diffMode === mode ? 'bg-[#123b50] text-white shadow-xs' : 'text-slate-500 hover:text-[#123b50]'}`}>
                        {mode === 'normalized' ? (zh ? '标准化' : 'Norm') : (zh ? '原始' : 'Raw')}
                      </button>
                    ))}
                  </div>
                  {(['markdown', 'html', 'json'] as const).map((format) => (
                    <ActionButton
                      key={format}
                      type="button"
                      icon={exporting === format ? Loader2 : Download}
                      iconClassName={exporting === format ? 'animate-spin' : undefined}
                      variant="default"
                      size="sm"
                      disabled={Boolean(exporting)}
                      onClick={() => void exportAnalysis(format)}
                      className="hidden !h-7 !px-2 !text-[9px] uppercase sm:inline-flex"
                    >
                      {format === 'markdown' ? 'MD' : format}
                    </ActionButton>
                  ))}
                  <button type="button" disabled={confirming} onClick={() => void confirmAnalysis()} className="inline-flex items-center gap-1 rounded-lg border border-emerald-200 bg-emerald-50 px-2 py-1 text-[9px] font-bold text-emerald-700 disabled:opacity-40">
                    {confirming ? <Loader2 size={10} className="animate-spin" /> : <CheckCircle2 size={10} />}{zh ? '确认' : 'Confirm'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setIsFullscreen((prev) => !prev)}
                    className={`rounded-lg border p-1 transition-colors ${
                      isFullscreen
                        ? 'bg-[#123b50] border-[#123b50] text-white shadow-sm'
                        : 'border-slate-200 text-slate-600 hover:border-cyan-400 hover:text-cyan-700'
                    }`}
                    title={isFullscreen ? (zh ? '退出全屏 (Esc)' : 'Exit Fullscreen (Esc)') : (zh ? '全屏沉浸对比' : 'Fullscreen')}
                  >
                    {isFullscreen ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
                  </button>
                </div>
              </div>

              {/* ── Row 2: View Switcher + Tools + Inline Metrics Badge Capsule (~36px) ── */}
              <div className="flex h-9 items-center justify-between gap-2 border-b border-slate-200 bg-slate-50/90 px-3 text-xs shrink-0">
                <div className="flex items-center gap-2 overflow-x-auto py-0.5">
                  <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5 shrink-0">
                    {([
                      ['text', zh ? '统一 Diff' : 'Unified diff', GitBranch],
                      ['objects', zh ? '对象视图' : 'Object view', Boxes],
                      ['risks', zh ? '风险与合规' : 'Risk & compliance', ShieldAlert],
                    ] as const).map(([view, label, Icon]) => (
                      <button
                        type="button"
                        key={view}
                        onClick={() => setAnalysisView(view)}
                        className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[9px] font-bold transition-all ${
                          analysisView === view ? 'bg-[#123b50] text-white shadow-xs' : 'text-slate-500 hover:text-slate-800'
                        }`}
                      >
                        <Icon size={10} />
                        {label}
                        {view === 'objects' && analysis && <span className="opacity-75 tabular-nums">({analysis.objects.length})</span>}
                        {view === 'risks' && analysis && <span className="opacity-75 tabular-nums">({analysis.risks.length})</span>}
                      </button>
                    ))}
                  </div>

                  {/* Tools when view === 'text' */}
                  {analysisView === 'text' && (
                    <div className="flex items-center gap-1 shrink-0">
                      {activeChangeLineIndexes.length > 0 && <span className="rounded bg-slate-200/80 px-1.5 py-0.5 text-[9px] font-bold text-slate-600 tabular-nums">{safeFocusIdx + 1}/{activeChangeLineIndexes.length}</span>}
                      <button onClick={() => onJumpToDiff('prev')} disabled={activeChangeLineIndexes.length === 0} className="rounded border border-slate-200 bg-white p-1 text-slate-500 hover:border-cyan-300 disabled:opacity-30" title={zh ? '上一处变更' : 'Previous'}><ChevronLeft size={10} /></button>
                      <button onClick={() => onJumpToDiff('next')} disabled={activeChangeLineIndexes.length === 0} className="rounded border border-slate-200 bg-white p-1 text-slate-500 hover:border-cyan-300 disabled:opacity-30" title={zh ? '下一处变更' : 'Next'}><ChevronRight size={10} /></button>
                      <button onClick={onToggleOnlyChanges} className={`rounded border px-1.5 py-0.5 text-[9px] font-bold transition-colors ${diffOnlyChanges ? 'border-cyan-300 bg-cyan-50 text-cyan-700' : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300'}`}>{zh ? '仅变更' : 'Only diff'}</button>
                      <button onClick={onToggleFullBoth} className={`rounded border px-1.5 py-0.5 text-[9px] font-bold transition-colors ${diffShowFullBoth ? 'border-cyan-300 bg-cyan-50 text-cyan-700' : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300'}`}>{zh ? '左右并排' : 'Side-by-side'}</button>
                      <button onClick={() => setWrapLines((w) => !w)} className={`rounded border px-1.5 py-0.5 text-[9px] font-bold transition-colors ${wrapLines ? 'border-cyan-300 bg-cyan-50 text-cyan-700' : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300'}`} title={zh ? '长行自动换行' : 'Wrap lines'}>{zh ? '换行' : 'Wrap'}</button>
                      <div className="inline-flex rounded border border-slate-200 bg-white p-0.5 text-[9px]">
                        <button onClick={() => setFontSize('xs')} className={`px-1 py-0.5 rounded font-bold ${fontSize === 'xs' ? 'bg-[#123b50] text-white' : 'text-slate-500'}`} title={zh ? '紧凑字号' : 'Compact'}>A-</button>
                        <button onClick={() => setFontSize('sm')} className={`px-1 py-0.5 rounded font-bold ${fontSize === 'sm' ? 'bg-[#123b50] text-white' : 'text-slate-500'}`} title={zh ? '标准字号' : 'Standard'}>A</button>
                        <button onClick={() => setFontSize('base')} className={`px-1 py-0.5 rounded font-bold ${fontSize === 'base' ? 'bg-[#123b50] text-white' : 'text-slate-500'}`} title={zh ? '大字号' : 'Large'}>A+</button>
                      </div>
                      <button onClick={() => setChangeMapVisible((v) => !v)} className={`hidden xl:inline-flex items-center gap-0.5 rounded border px-1.5 py-0.5 text-[9px] font-bold transition-colors ${changeMapVisible ? 'border-cyan-300 bg-cyan-50 text-cyan-700' : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300'}`} title={zh ? '切换变更目录' : 'Change Map'}>
                        {changeMapVisible ? <PanelRightClose size={10} /> : <PanelRightOpen size={10} />}
                        {zh ? '目录' : 'Map'}
                      </button>
                    </div>
                  )}

                  {/* Filters when view === 'objects' */}
                  {analysisView === 'objects' && (
                    <div className="flex items-center gap-1 shrink-0">
                      <button type="button" onClick={() => setObjectFilter('all')} className={`rounded-full px-2 py-0.5 font-sans text-[8px] font-bold ${objectFilter === 'all' ? 'bg-[#123b50] text-white' : 'border border-slate-200 bg-white text-slate-500'}`}>
                        {zh ? '全部' : 'All'} {analysis?.objects.length || 0}
                      </button>
                      {Object.entries(analysis?.summary.object_counts || {}).map(([name, count]) => (
                        <button type="button" key={name} onClick={() => setObjectFilter(name)} className={`rounded-full px-2 py-0.5 font-sans text-[8px] font-bold ${objectFilter === name ? 'bg-cyan-600 text-white' : 'border border-slate-200 bg-white text-slate-500 hover:border-cyan-200 hover:text-cyan-700'}`}>
                          {name} {count}
                        </button>
                      ))}
                    </div>
                  )}

                  {/* Filters when view === 'risks' */}
                  {analysisView === 'risks' && (
                    <div className="flex items-center gap-1 shrink-0">
                      {['all', 'critical', 'high', 'medium', 'low'].map((level) => (
                        <button type="button" key={level} onClick={() => setRiskFilter(level)} className={`rounded-full px-2 py-0.5 font-sans text-[8px] font-bold ${riskFilter === level ? 'bg-[#123b50] text-white' : 'border border-slate-200 bg-white text-slate-500'}`}>
                          {level === 'all' ? (zh ? '全部' : 'All') : level}
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                {/* Right side: Inline Metrics Badge Capsule */}
                {analysis && (
                  <div className="hidden md:flex items-center gap-1 text-[9px] shrink-0 font-sans">
                    <span className="rounded bg-emerald-50 text-emerald-700 font-bold px-1.5 py-0.5 border border-emerald-100" title={zh ? '新增行' : 'Added'}>+{analysis.summary.added_lines}</span>
                    <span className="rounded bg-rose-50 text-rose-700 font-bold px-1.5 py-0.5 border border-rose-100" title={zh ? '删除行' : 'Removed'}>-{analysis.summary.removed_lines}</span>
                    <span className="rounded bg-cyan-50 text-cyan-700 font-bold px-1.5 py-0.5 border border-cyan-100" title={zh ? '变更对象数' : 'Objects'}>{analysis.summary.changed_objects} {zh ? '对象' : 'objs'}</span>
                    {analysis.summary.high_risk_changes > 0 && (
                      <span className="rounded bg-orange-50 text-orange-700 font-bold px-1.5 py-0.5 border border-orange-100" title={zh ? '高风险变更' : 'High risk'}>{analysis.summary.high_risk_changes} {zh ? '高风险' : 'risks'}</span>
                    )}
                    <span className="rounded bg-violet-50 text-violet-700 font-bold px-1.5 py-0.5 border border-violet-100" title={zh ? '合规率' : 'Compliance'}>{analysis.compliance.compliance_rate}% {zh ? '合规' : 'comp'}</span>
                    {analysis.source_correlation.out_of_band_suspected && (
                      <span className="rounded bg-rose-100 text-rose-800 font-black px-1.5 py-0.5" title={zh ? '疑似带外变更' : 'Possible out-of-band change'}>! {zh ? '带外' : 'OOB'}</span>
                    )}
                  </div>
                )}
              </div>

              {analysisError && (
                <div className="flex shrink-0 items-center gap-2 border-b border-rose-100 bg-rose-50 px-3 py-1.5 font-sans text-[10px] text-rose-700">
                  <AlertTriangle size={12} /><span className="flex-1">{analysisError}</span>
                  <button type="button" onClick={() => void loadStructuredAnalysis(true)} className="font-bold underline">{zh ? '重试' : 'Retry'}</button>
                  <button type="button" onClick={() => setAnalysisError('')}><X size={12} /></button>
                </div>
              )}

              {/* ── Main Viewport Content Area ── */}
              <div className="flex-1 min-h-0 overflow-hidden p-2 sm:p-2.5">
                {analysisView === 'objects' ? (
                  <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xs">
                    <div className="flex-1 overflow-auto p-3">
                      {filteredObjects.length > 0 ? (
                        <div className="grid gap-3 xl:grid-cols-2">
                          {filteredObjects.map((item) => (
                            <article key={item.id} className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xs">
                              <div className="flex items-start gap-3 border-b border-slate-100 bg-slate-50/60 px-4 py-2.5">
                                <span className={`mt-0.5 rounded-md px-1.5 py-0.5 font-sans text-[8px] font-black uppercase ${
                                  item.change_type === 'added' ? 'bg-emerald-50 text-emerald-700 border border-emerald-200/60' : item.change_type === 'deleted' ? 'bg-rose-50 text-rose-700 border border-rose-200/60' : 'bg-amber-50 text-amber-700 border border-amber-200/60'
                                }`}>{item.change_type === 'added' ? (zh ? '新增' : 'Added') : item.change_type === 'deleted' ? (zh ? '删除' : 'Deleted') : (zh ? '修改' : 'Modified')}</span>
                                <div className="min-w-0 flex-1">
                                  <div className="truncate font-sans text-xs font-black text-[#123b50]">{item.object_name}</div>
                                  <div className="mt-0.5 font-sans text-[9px] text-slate-400">{item.object_type} · {item.module}</div>
                                </div>
                                <span className={`rounded-full px-2 py-0.5 font-sans text-[8px] font-black ${
                                  item.risk_level === 'critical' || item.risk_level === 'high' ? 'bg-rose-50 text-rose-700' : item.risk_level === 'medium' ? 'bg-amber-50 text-amber-700' : 'bg-slate-100 text-slate-500'
                                }`}>{item.risk_level || 'low'}</span>
                              </div>
                              <div className="space-y-2.5 px-4 py-2.5">
                                {item.field_changes.length > 0 && (
                                  <div className="overflow-hidden rounded-lg border border-slate-100">
                                    {item.field_changes.map((field, index) => (
                                      <div key={`${field.field}-${index}`} className="grid grid-cols-[100px_1fr_18px_1fr] items-start gap-2 border-b border-slate-100 px-3 py-1.5 font-sans text-[9px] last:border-b-0">
                                        <span className="font-bold text-slate-500">{field.field}</span>
                                        <code className="break-all text-rose-600">{String(field.before ?? '--')}</code>
                                        <ArrowLeftRight size={10} className="mt-0.5 text-slate-300" />
                                        <code className="break-all text-emerald-600">{String(field.after ?? '--')}</code>
                                      </div>
                                    ))}
                                  </div>
                                )}
                                <div className="grid gap-2 md:grid-cols-2">
                                  <div className="rounded-lg bg-rose-50/70 p-2">
                                    <div className="font-sans text-[8px] font-black uppercase text-rose-500">{zh ? '变更前' : 'Before'}</div>
                                    <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-all font-mono text-[9px] leading-4 text-rose-800">{item.before_lines.join('\n') || '--'}</pre>
                                  </div>
                                  <div className="rounded-lg bg-emerald-50/70 p-2">
                                    <div className="font-sans text-[8px] font-black uppercase text-emerald-500">{zh ? '变更后' : 'After'}</div>
                                    <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-all font-mono text-[9px] leading-4 text-emerald-800">{item.after_lines.join('\n') || '--'}</pre>
                                  </div>
                                </div>
                                {(item.risk_reason || item.potential_impact) && (
                                  <div className="rounded-lg border border-amber-100 bg-amber-50/70 px-3 py-1.5 font-sans text-[9px] leading-4 text-amber-800">
                                    <span className="font-black">{item.risk_reason || (zh ? '风险提示' : 'Risk')}</span>
                                    {item.potential_impact && <span> · {item.potential_impact}</span>}
                                  </div>
                                )}
                              </div>
                            </article>
                          ))}
                        </div>
                      ) : (
                        <div className="flex h-full flex-col items-center justify-center text-slate-400">
                          <Boxes size={28} className="mb-2 text-slate-300" />
                          <p className="font-sans text-xs font-bold">{analysisLoading ? (zh ? '正在解析配置对象…' : 'Parsing configuration objects…') : (zh ? '当前筛选下没有结构化变更对象' : 'No structured changes match this filter')}</p>
                        </div>
                      )}
                    </div>
                  </div>
                ) : analysisView === 'risks' ? (
                  <div className="grid h-full min-h-0 gap-3 overflow-auto xl:grid-cols-[1.15fr_0.85fr]">
                    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xs flex flex-col min-h-0">
                      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 bg-slate-50/70 px-3 py-2 shrink-0">
                        <ShieldAlert size={13} className="text-rose-600" />
                        <span className="font-sans text-[10px] font-black uppercase tracking-wider text-[#123b50]">{zh ? '变更风险清单' : 'Change risks'}</span>
                      </div>
                      <div className="flex-1 space-y-2 overflow-auto p-3">
                        {filteredRisks.map((risk, index) => (
                          <div key={`${risk.rule_id}-${risk.object_name}-${index}`} className={`rounded-xl border p-2.5 ${
                            risk.severity === 'critical' || risk.severity === 'high' ? 'border-rose-200 bg-rose-50/60' : risk.severity === 'medium' ? 'border-amber-200 bg-amber-50/60' : 'border-slate-200 bg-slate-50'
                          }`}>
                            <div className="flex items-start gap-2">
                              <span className="rounded-md bg-white px-1.5 py-0.5 font-sans text-[8px] font-black uppercase text-slate-600 shadow-xs">{risk.severity}</span>
                              <div className="min-w-0 flex-1">
                                <div className="font-sans text-[10px] font-black text-[#123b50]">{risk.message}</div>
                                <div className="mt-0.5 font-sans text-[9px] text-slate-500">{risk.object_type} · {risk.object_name}</div>
                                {risk.potential_impact && <p className="mt-1 font-sans text-[9px] leading-4 text-slate-600">{risk.potential_impact}</p>}
                              </div>
                              {(risk.requires_mfa || risk.requires_secondary_approval) && (
                                <div className="flex flex-col items-end gap-0.5">
                                  {risk.requires_mfa && <span className="rounded bg-amber-100 px-1.5 py-0.2 font-sans text-[7px] font-black text-amber-700">MFA</span>}
                                  {risk.requires_secondary_approval && <span className="rounded bg-violet-100 px-1.5 py-0.2 font-sans text-[7px] font-black text-violet-700">{zh ? '复核' : 'Review'}</span>}
                                </div>
                              )}
                            </div>
                          </div>
                        ))}
                        {filteredRisks.length === 0 && <p className="py-12 text-center font-sans text-xs font-bold text-slate-400">{zh ? '未发现匹配风险' : 'No matching risks found'}</p>}
                      </div>
                    </section>
                    <div className="space-y-3 overflow-auto">
                      <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xs">
                        <div className="flex items-center justify-between border-b border-slate-100 px-3 py-2">
                          <span className="inline-flex items-center gap-1.5 font-sans text-[10px] font-black text-[#123b50]"><FileCheck2 size={12} className="text-violet-600" />{zh ? '合规检查' : 'Compliance checks'}</span>
                          <span className="font-sans text-xs font-black text-violet-700">{analysis?.compliance.compliance_rate ?? 0}%</span>
                        </div>
                        <div className="space-y-1.5 p-2.5">
                          {(analysis?.compliance.findings || []).map((finding) => (
                            <div key={finding.rule_id} className={`rounded-lg border px-2.5 py-1.5 ${finding.status === 'compliant' ? 'border-emerald-100 bg-emerald-50/50' : 'border-rose-100 bg-rose-50/50'}`}>
                              <div className="flex items-center gap-2 font-sans text-[9px]">
                                {finding.status === 'compliant' ? <CheckCircle2 size={11} className="text-emerald-600" /> : <AlertTriangle size={11} className="text-rose-600" />}
                                <span className="flex-1 font-black text-slate-700">{finding.name}</span>
                                <span className="text-slate-400">{finding.observed_count}/{finding.expected_count}</span>
                              </div>
                              {finding.status !== 'compliant' && finding.remediation && <p className="mt-1 pl-5 font-sans text-[8px] leading-4 text-rose-700">{finding.remediation}</p>}
                            </div>
                          ))}
                        </div>
                      </section>
                      <section className="rounded-xl border border-slate-200 bg-white p-3 shadow-xs">
                        <div className="font-sans text-[10px] font-black text-[#123b50]">{zh ? '变更来源关联' : 'Change source correlation'}</div>
                        <p className={`mt-1.5 rounded-lg px-2.5 py-1.5 font-sans text-[9px] leading-4 ${analysis?.source_correlation.out_of_band_suspected ? 'bg-rose-50 text-rose-700' : 'bg-emerald-50 text-emerald-700'}`}>
                          {analysis?.source_correlation.message || (zh ? '暂无关联结果' : 'No correlation result')}
                        </p>
                        <div className="mt-1.5 space-y-1">
                          {(analysis?.source_correlation.correlations || []).map((source) => (
                            <div key={`${source.source_type}-${source.source_id}`} className="flex items-center gap-2 rounded-lg border border-slate-100 px-2.5 py-1.5 font-sans text-[8px] text-slate-500">
                              <Link2 size={10} className="text-cyan-600" />
                              <span className="rounded bg-slate-100 px-1.5 py-0.5 font-bold">{source.source_type}</span>
                              <span className="min-w-0 flex-1 truncate font-bold text-slate-700">{source.label}</span>
                              <span>{source.actor}</span>
                            </div>
                          ))}
                        </div>
                      </section>
                    </div>
                  </div>
                ) : (
                <div className={`flex h-full min-h-0 gap-3 overflow-hidden ${
                  fontSize === 'xs' ? 'text-[11px] leading-5' : fontSize === 'sm' ? 'text-[13px] leading-6' : 'text-[14px] leading-7'
                }`}>
                <div className="flex-1 overflow-auto rounded-xl border border-slate-200 bg-white shadow-xs">
                  {diffShowFullBoth ? (
                    <div className="min-w-[960px]">
                      <div className="sticky top-0 z-10 grid grid-cols-2 border-b border-slate-200 bg-slate-50 text-[10px] uppercase tracking-wider text-slate-500 font-bold">
                        <div className="px-4 py-1.5 border-r border-slate-200 bg-rose-50/40 text-rose-700">{zh ? '左侧基准配置 (A)' : 'Left Baseline Config (A)'}</div>
                        <div className="px-4 py-1.5 bg-emerald-50/40 text-emerald-700">{zh ? '右侧目标配置 (B)' : 'Right Target Config (B)'}</div>
                      </div>
                      {fullSideBySideRows.map((row) => {
                        const isFocused = focusedLineIndex !== undefined && row.originalIndex === focusedLineIndex;
                        return (
                          <div key={row.originalIndex} ref={(el) => { diffLineRefs.current[row.originalIndex] = el; }} className={`grid grid-cols-2 ${isFocused ? 'ring-2 ring-cyan-400 bg-cyan-50/80' : ''}`}>
                            <div className={`flex items-start px-3 py-[2px] border-r border-slate-100 ${row.rowType === 'remove' ? 'bg-red-50/90 text-red-800' : ''}`}>
                              <span className="w-9 text-right text-slate-300 pr-2.5 select-none flex-shrink-0 font-mono">{row.leftLine || ''}</span>
                              <span className="w-3.5 select-none flex-shrink-0 text-red-500 font-bold">{row.rowType === 'remove' ? '−' : ' '}</span>
                              <span className={`${row.rowType === 'remove' ? 'text-red-800 font-semibold' : 'text-slate-700'} ${wrapLines ? 'whitespace-pre-wrap break-all' : 'whitespace-pre'}`}>{row.leftContent}</span>
                            </div>
                            <div className={`flex items-start px-3 py-[2px] ${row.rowType === 'add' ? 'bg-emerald-50/90 text-emerald-800' : ''}`}>
                              <span className="w-9 text-right text-slate-300 pr-2.5 select-none flex-shrink-0 font-mono">{row.rightLine || ''}</span>
                              <span className="w-3.5 select-none flex-shrink-0 text-emerald-500 font-bold">{row.rowType === 'add' ? '+' : ' '}</span>
                              <span className={`${row.rowType === 'add' ? 'text-emerald-800 font-semibold' : 'text-slate-700'} ${wrapLines ? 'whitespace-pre-wrap break-all' : 'whitespace-pre'}`}>{row.rightContent}</span>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    renderedDiffLines.map(({ line, originalIndex }) => {
                      const isFocused = focusedLineIndex !== undefined && originalIndex === focusedLineIndex;
                      return (
                        <div
                          key={originalIndex}
                          ref={(el) => { diffLineRefs.current[originalIndex] = el; }}
                           className={`flex items-start px-3 py-[2px] ${line.type === 'add' ? 'bg-emerald-50/90' : line.type === 'remove' ? 'bg-red-50/90' : ''} ${isFocused ? 'ring-2 ring-cyan-400 bg-cyan-50/80' : ''}`}
                        >
                           <span className="w-9 text-right text-slate-300 pr-2 select-none flex-shrink-0 font-mono">{line.lineA || ''}</span>
                           <span className="w-9 text-right text-slate-300 pr-2 select-none flex-shrink-0 font-mono">{line.lineB || ''}</span>
                           <span className={`w-3.5 select-none flex-shrink-0 font-bold ${line.type === 'add' ? 'text-emerald-600' : line.type === 'remove' ? 'text-red-600' : 'text-slate-300'}`}>
                            {line.type === 'add' ? '+' : line.type === 'remove' ? '−' : ' '}
                          </span>
                           <span className={`${line.type === 'add' ? 'text-emerald-800 font-semibold' : line.type === 'remove' ? 'text-red-800 font-semibold' : 'text-slate-700'} ${wrapLines ? 'whitespace-pre-wrap break-all' : 'whitespace-pre'}`}>{line.content}</span>
                        </div>
                      );
                    })
                  )}
                </div>
                {diffChangeBlocks.length > 0 && changeMapVisible && (
                  <aside className="hidden xl:block w-60 rounded-xl border border-slate-200 bg-white overflow-auto shadow-xs shrink-0">
                    <div className="px-3 py-2 border-b border-slate-100">
                      <div className="flex items-center justify-between">
                        <div className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">{zh ? '变更目录' : 'Change Map'}</div>
                        <button onClick={() => setChangeMapVisible(false)} className="text-slate-400 hover:text-slate-600" title={zh ? '收起目录' : 'Hide'}>
                          <PanelRightClose size={11} />
                        </button>
                      </div>
                      <input
                        value={diffBlockQuery}
                        onChange={(e) => onDiffBlockQueryChange(e.target.value)}
                        placeholder={zh ? '过滤: interface / route' : 'Filter: interface / route'}
                        className="mt-1.5 w-full px-2 py-1 rounded-lg border border-slate-200 bg-slate-50 text-[10px] text-slate-700 placeholder:text-slate-400 outline-none focus:border-cyan-300 focus:bg-white"
                      />
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {['interface', 'route', 'acl', 'bgp', 'ospf', 'vlan'].map((kw) => (
                          <button
                            key={kw}
                            onClick={() => onToggleQuickKeyword(kw)}
                            className={`px-1 py-0.5 rounded text-[8px] border transition-colors ${diffBlockQuery.toLowerCase() === kw ? 'border-cyan-300 text-cyan-700 bg-cyan-50' : 'border-slate-200 text-slate-500 hover:text-[#123b50] hover:border-slate-300'}`}
                          >
                            {kw}
                          </button>
                        ))}
                      </div>
                    </div>
                    <div className="p-1.5 space-y-1">
                      {filteredDiffChangeBlocks.map((block, idx) => {
                        const isActive = diffFocusChangeIdx >= block.startChangeIdx && diffFocusChangeIdx <= block.endChangeIdx;
                        return (
                          <button
                            key={`${block.startChangeIdx}-${block.endChangeIdx}`}
                            onClick={() => onFocusDiffChangeAt(block.startChangeIdx)}
                            className={`w-full text-left px-2 py-1.5 rounded-lg border transition-all ${isActive ? 'border-cyan-300 bg-cyan-50 text-cyan-800' : 'border-slate-200 text-slate-500 hover:text-[#123b50] hover:border-slate-300 hover:bg-slate-50'}`}
                            title={block.label}
                          >
                            <div className="flex items-center justify-between gap-1">
                              <span className="text-[9px] font-bold">#{idx + 1}</span>
                              <span className="text-[9px] font-mono text-slate-400">{block.startChangeIdx + 1}-{block.endChangeIdx + 1}</span>
                            </div>
                            <div className="mt-0.5 text-[9px] leading-3.5 truncate">{block.label}</div>
                          </button>
                        );
                      })}
                      {filteredDiffChangeBlocks.length === 0 && (
                        <p className="px-2 py-2 text-[9px] text-slate-400">{zh ? '没有匹配的变更块' : 'No matching change block'}</p>
                      )}
                    </div>
                  </aside>
                )}
                </div>
                )}
              </div>

              {/* ── Row 4: Slim Compact Bottom Bar (~36px) ── */}
              <div className="flex h-10 shrink-0 flex-wrap items-center gap-2 border-t border-slate-200 bg-white px-3 text-xs">
                <div className="mr-auto font-sans text-[9px] text-slate-400 truncate">
                  {zh ? '任何回滚都只生成受控恢复方案，不会从差异页直接下发设备。' : 'Rollback actions only create a governed recovery plan.'}
                </div>
                {configDiffRight && (
                  <button type="button" onClick={() => void handleSetBaseline(configDiffRight.id)} disabled={baselineSaving === configDiffRight.id} className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1 font-sans text-[9px] font-bold text-slate-600 hover:border-cyan-200 hover:text-cyan-700 disabled:opacity-50">
                    {baselineSaving === configDiffRight.id ? <Loader2 size={10} className="animate-spin" /> : <Database size={10} />}{zh ? '设 B 为基准' : 'Set B as baseline'}
                  </button>
                )}
                <button type="button" onClick={() => void prepareRollback()} disabled={rollbackLoading} className="inline-flex items-center gap-1 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-1 font-sans text-[9px] font-bold text-amber-700 disabled:opacity-50">
                  {rollbackLoading ? <Loader2 size={10} className="animate-spin" /> : <RotateCcw size={10} />}{zh ? '生成回滚预案' : 'Prepare rollback'}
                </button>
                <button type="button" onClick={() => navigate(`/change-orders?device_id=${encodeURIComponent(analysisDeviceId)}&snapshot_a=${encodeURIComponent(configDiffLeft?.id || '')}&snapshot_b=${encodeURIComponent(configDiffRight?.id || '')}`)} className="inline-flex items-center gap-1 rounded-lg bg-[#123b50] px-2.5 py-1 font-sans text-[9px] font-bold text-white hover:bg-[#0b2d3e]">
                  <Zap size={10} />{zh ? '创建工单' : 'Create order'}
                </button>
              </div>

              {rollbackPlan && (
                <div className="shrink-0 border-t border-amber-100 bg-amber-50/80 px-3 py-2">
                  <div className="flex flex-wrap items-start gap-2">
                    <ShieldAlert size={13} className="mt-0.5 text-amber-700" />
                    <div className="min-w-0 flex-1">
                      <div className="font-sans text-[9px] font-black text-amber-900">{zh ? '受控回滚预案已生成' : 'Governed rollback plan prepared'} · {rollbackPlan.plan_id}</div>
                      <p className="mt-0.5 font-sans text-[8px] leading-3.5 text-amber-800">{rollbackPlan.warning || (zh ? `目标 ${rollbackPlan.line_count} 行配置；必须经过工单、MFA 和回滚计时器。` : `${rollbackPlan.line_count} target lines; change order required.`)}</p>
                      {rollbackPlan.blockers.length > 0 && <p className="mt-0.5 font-sans text-[8px] font-bold text-rose-700">{zh ? '阻断项：' : 'Blockers: '}{rollbackPlan.blockers.join('；')}</p>}
                    </div>
                    <button type="button" onClick={() => setRollbackPlan(null)} className="text-amber-700"><X size={12} /></button>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
      </div>
    </div>
  );
};

export default ConfigDiffViewTab;
