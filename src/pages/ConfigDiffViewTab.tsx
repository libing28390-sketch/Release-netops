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
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
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
  const loadSnapshots = useCallback(async (deviceId: string, autoCompare = true) => {
    setSnapshotsLoading(true);
    try {
      const data = await apiRequest<DiffSnapshot[]>(`/api/config-drift/device/${encodeURIComponent(deviceId)}/snapshots`);
      const sorted = data.sort((a, b) => b.timestamp.localeCompare(a.timestamp));
      setSnapshots(sorted);
      if (autoCompare) {
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
          await onSelectSnapshotPair(previous.id, latest.id);
        }
      }
    } catch (error) {
      setAnalysisError(error instanceof Error ? error.message : (zh ? '快照加载失败' : 'Failed to load snapshots'));
    }
    finally { setSnapshotsLoading(false); }
  }, [onSelectSnapshotPair, zh]);

  const handleSelectDevice = (dev: BackupDevice) => {
    setSelectedDevice(dev);
    setPickLeft(null);
    setPickRight(null);
    setAnalysis(null);
    setAnalysisError('');
    setRollbackPlan(null);
    onReset();
    void loadSnapshots(dev.id);
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

  const formatTime = (ts: string) => {
    if (!ts) return '--';
    try { return new Date(ts).toLocaleString(); } catch { return ts; }
  };

  const formatSize = (size?: number) => {
    if (!size) return '';
    if (size >= 1048576) return `${(size / 1048576).toFixed(1)} MB`;
    if (size >= 1024) return `${(size / 1024).toFixed(1)} KB`;
    return `${size} B`;
  };

  const timeSince = (ts: string) => {
    if (!ts) return '';
    try {
      const diff = Date.now() - new Date(ts).getTime();
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
      <PageHero
        icon={GitCompare}
        eyebrow={zh ? '配置管理 / 配置差异分析' : 'Config / Difference Analysis'}
        title={zh ? '配置差异分析' : t('diffCompare')}
        subtitle={showDiffViewer
          ? (zh ? `${configDiffLeft.hostname} · 识别高风险变更、合规偏差与变更来源` : `Risk, compliance, and source analysis for ${configDiffLeft.hostname}`)
          : (zh ? '自动对比最近两个有效快照，识别高风险变更并生成回滚依据' : 'Automatically compare the latest valid snapshots and identify risky changes')}
        actions={
          (selectedDevice || showDiffViewer) ? (
            <button
              onClick={showDiffViewer ? () => { onReset(); } : handleBackToDevices}
              className="text-xs text-black/40 hover:text-black transition px-3 py-1.5 border border-black/10 rounded-xl hover:bg-black/[0.03]"
            >
              {showDiffViewer ? (zh ? '重新选择' : 'Re-select') : (zh ? '返回设备列表' : 'Back to devices')}
            </button>
          ) : undefined
        }
      />

      <div className="flex-1 overflow-hidden px-6 py-5 flex flex-col">
      <div className="flex-1 overflow-hidden rounded-[28px] border border-black/5 bg-white shadow-[0_16px_36px_rgba(11,35,64,0.06)] flex flex-col">
        {/* ════════ Step 1 + 2: Selection area ════════ */}
        {!showDiffViewer && (
          <div className="flex-1 overflow-auto">
            {!selectedDevice ? (
              /* ──── Step 1: Device list ──── */
              <div className="flex flex-col h-full bg-[#f7fbfc]">
                <div className="px-6 pt-6 pb-5 bg-gradient-to-br from-[#f0fbfc] via-white to-white border-b border-cyan-100/70">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.16em] text-[#0891b2]">
                        <Server size={14} /> {zh ? '配置审计工作台' : 'Configuration audit workspace'}
                      </div>
                      <h2 className="mt-2 text-xl font-bold tracking-tight text-[#123b50]">{zh ? '选择要对比的设备' : 'Choose a device to compare'}</h2>
                      <p className="mt-1 text-xs text-slate-500">{zh ? '先定位设备，再从正式基线或历史快照中选择两个版本。' : 'Locate a device first, then choose two versions from its baseline or history.'}</p>
                    </div>
                    <div className="hidden md:flex items-center gap-1.5 rounded-xl border border-white bg-white/80 p-1 shadow-sm">
                      {[zh ? '设备' : 'Device', zh ? '快照' : 'Snapshots', zh ? '差异' : 'Diff'].map((step, idx) => (
                        <div key={step} className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[10px] font-bold ${idx === 0 ? 'bg-[#123b50] text-white' : 'text-slate-400'}`}>
                          <span className="font-mono opacity-70">0{idx + 1}</span>{step}
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="mt-5 grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                    <div className="rounded-xl border border-white bg-white/80 px-3.5 py-3 shadow-sm">
                      <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{zh ? '可审计设备' : 'Auditable devices'}</div>
                      <div className="mt-1 text-lg font-bold tabular-nums text-[#123b50]">{devicesTotal}</div>
                    </div>
                    <div className="rounded-xl border border-white bg-white/80 px-3.5 py-3 shadow-sm">
                      <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{zh ? '当前页结果' : 'Current page'}</div>
                      <div className="mt-1 text-lg font-bold tabular-nums text-[#0891b2]">{devices.length}<span className="ml-1 text-xs font-medium text-slate-400">/ {devPageSize}</span></div>
                    </div>
                    <div className="rounded-xl border border-white bg-white/80 px-3.5 py-3 shadow-sm">
                      <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{zh ? '对比方式' : 'Compare mode'}</div>
                      <div className="mt-1 flex items-center gap-1.5 text-sm font-bold text-[#123b50]"><ShieldCheck size={14} className="text-emerald-500" />{diffMode === 'normalized' ? (zh ? '标准化审阅' : 'Normalized review') : (zh ? '原始文本' : 'Raw text')}</div>
                    </div>
                  </div>
                </div>

                <div className="flex-1 overflow-auto px-6 py-5">
                  <div className={`mb-4 grid gap-4 ${deviceTreeCollapsed ? 'xl:grid-cols-[56px_minmax(0,1fr)]' : 'xl:grid-cols-[290px_minmax(0,1fr)]'}`}>
                    <aside className={`rounded-2xl border border-slate-200 bg-white shadow-sm ${deviceTreeCollapsed ? 'p-2' : 'p-3'}`}>
                      <div className={`mb-3 flex items-center border-b border-slate-100 pb-3 ${deviceTreeCollapsed ? 'justify-center' : 'justify-between px-2'}`}>
                        {!deviceTreeCollapsed && <div><div className="text-sm font-bold text-slate-800">{zh ? '资产分类树' : 'Asset tree'}</div><div className="mt-0.5 text-[11px] text-slate-400">{zh ? '站点 → 类型 → 分类 → 角色' : 'Site → type → category → role'}</div></div>}
                        <button type="button" onClick={() => setDeviceTreeCollapsed((current) => !current)} className="rounded-lg p-1.5 text-slate-400 hover:bg-cyan-50 hover:text-cyan-700" title={deviceTreeCollapsed ? (zh ? '展开资产分类树' : 'Expand asset tree') : (zh ? '折叠资产分类树' : 'Collapse asset tree')}>
                          {deviceTreeCollapsed ? <FolderTree size={15} /> : <ChevronRight size={15} className="rotate-180" />}
                        </button>
                      </div>
                      {!deviceTreeCollapsed && <div className="max-h-[280px] overflow-y-auto">{deviceScopeTree.length ? deviceScopeTree.map((node) => renderDeviceScopeNode(node)) : <p className="px-2 py-8 text-center text-xs text-slate-400">{zh ? '暂无资产分类' : 'No asset groups'}</p>}</div>}
                    </aside>
                    <div className="min-w-0">
                  <div className="rounded-2xl border border-slate-200 bg-white shadow-[0_12px_30px_rgba(18,59,80,0.06)] overflow-hidden">
                    <div className="flex flex-wrap items-center gap-3 px-4 py-3 border-b border-slate-100 bg-white">
                      <div className="flex items-center gap-2 text-xs font-bold text-[#123b50]"><SlidersHorizontal size={14} className="text-[#0891b2]" />{zh ? '设备范围' : 'Device scope'}</div>
                      <div className="relative flex-1 min-w-[220px] max-w-xl">
                        <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                        <input
                          value={deviceSearchDraft}
                          onChange={(e) => setDeviceSearchDraft(e.target.value)}
                          onKeyDown={(e) => { if (e.key === 'Enter') submitDeviceSearch(); }}
                          placeholder={zh ? '搜索主机名或管理 IP，按回车执行' : 'Search hostname or management IP, press Enter'}
                          className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2.5 pl-9 pr-9 text-xs text-[#123b50] outline-none placeholder:text-slate-400 focus:border-cyan-300 focus:bg-white focus:ring-4 focus:ring-cyan-50 transition-all"
                        />
                        {deviceSearchDraft && <button onClick={() => { setDeviceSearchDraft(''); setDeviceSearch(''); setDevPage(1); }} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700"><X size={13} /></button>}
                      </div>
                      <button onClick={submitDeviceSearch} className="inline-flex items-center gap-1.5 rounded-xl bg-[#123b50] px-3.5 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-[#0b2d3e] transition-colors"><Search size={13} />{zh ? '搜索' : 'Search'}</button>
                      {deviceSearch && <span className="rounded-full bg-cyan-50 px-2.5 py-1 text-[10px] font-bold text-cyan-700">{zh ? `已筛选：${deviceSearch}` : `Filter: ${deviceSearch}`}</span>}
                    </div>

                    <div className="grid grid-cols-[minmax(210px,1.8fr)_minmax(130px,1fr)_90px_120px_32px] items-center gap-x-4 px-5 py-2.5 bg-slate-50/80 text-[10px] font-bold uppercase tracking-wider text-slate-400 border-b border-slate-100">
                      <span>{zh ? '设备资产' : 'Device asset'}</span><span>{zh ? '平台' : 'Platform'}</span><span>{zh ? '快照' : 'Snapshots'}</span><span>{zh ? '最近备份' : 'Last backup'}</span><span />
                    </div>

                    {devicesLoading ? (
                      <div className="py-20 text-center text-sm text-slate-400 flex items-center justify-center gap-2"><RotateCcw size={15} className="animate-spin text-cyan-500" />{zh ? '正在加载设备资产...' : 'Loading device assets...'}</div>
                    ) : devices.length === 0 ? (
                      <div className="py-20 text-center text-slate-400"><div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-slate-50"><Database size={28} strokeWidth={1.4} className="text-slate-300" /></div><p className="text-sm font-bold text-slate-600">{deviceSearch ? (zh ? '没有匹配的设备' : 'No matching devices') : (zh ? '暂无配置备份' : 'No config backups yet')}</p><p className="mt-1 text-xs">{deviceSearch ? (zh ? '请调整关键词后重试。' : 'Adjust the search and try again.') : (zh ? '请先到备份中心执行一次配置备份。' : 'Run a configuration backup from Backup Center first.')}</p></div>
                    ) : (
                      <div>
                        {devices.map((dev) => {
                          const online = dev.status === 'online';
                          return <button key={dev.id} onClick={() => handleSelectDevice(dev)} className="group w-full text-left grid grid-cols-[minmax(210px,1.8fr)_minmax(130px,1fr)_90px_120px_32px] items-center gap-x-4 px-5 py-3.5 border-b border-slate-100 last:border-b-0 hover:bg-cyan-50/50 transition-colors">
                            <div className="flex items-center gap-3 min-w-0"><div className={`flex h-9 w-9 items-center justify-center rounded-xl ${online ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600'}`}><Server size={15} /></div><div className="min-w-0"><div className="flex items-center gap-2"><span className="truncate text-[13px] font-bold text-[#123b50]">{dev.hostname}</span><span className={`h-1.5 w-1.5 rounded-full ${online ? 'bg-emerald-500' : 'bg-amber-400'}`} /></div><span className="mt-0.5 block truncate text-[10px] font-mono text-slate-400">{dev.ip_address}</span></div></div>
                            <span className="truncate rounded-lg bg-slate-50 px-2.5 py-1.5 text-[10px] font-semibold text-slate-600 max-w-[150px]">{dev.platform || '--'}</span>
                            <span className="inline-flex w-fit items-center gap-1 rounded-full bg-cyan-50 px-2.5 py-1 text-[10px] font-bold text-cyan-700 tabular-nums"><Database size={11} />{dev.backup_count}</span>
                            <span className="text-[11px] text-slate-500 whitespace-nowrap"><span className="block font-semibold text-slate-600">{timeSince(dev.latest_backup) || '--'}</span><span className="block text-[9px] text-slate-400">{formatTime(dev.latest_backup).split(',')[0]}</span></span>
                            <ChevronRight size={16} className="text-slate-300 group-hover:translate-x-0.5 group-hover:text-cyan-600 transition-all" />
                          </button>;
                        })}
                      </div>
                    )}
                  </div>
                  {devicesTotal > devPageSize && <div className="mt-4 rounded-xl border border-slate-200 bg-white px-4 py-2.5"><Pagination currentPage={devPage} totalItems={devicesTotal} itemsPerPage={devPageSize} onPageChange={setDevPage} onItemsPerPageChange={(v) => { setDevPage(1); setDevPageSize(v); }} language={language} /></div>}
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              /* ──── Step 2: Snapshot selection ──── */
              <div className="flex flex-col h-full">
                {/* ── Top bar: back + device info + quick action ── */}
                <div className="flex items-center gap-3 px-5 pt-4 pb-3 border-b border-black/[0.04]">
                  <button onClick={handleBackToDevices} className="inline-flex items-center gap-1 text-xs text-[#0e7490] hover:text-[#06b6d4] transition font-medium">
                    <ChevronLeft size={14} /> {zh ? '设备列表' : 'Devices'}
                  </button>
                  <div className="h-4 w-px bg-black/10" />
                  <div className={`h-2 w-2 rounded-full flex-shrink-0 ${selectedDevice.status === 'online' ? 'bg-emerald-500' : 'bg-red-400'}`} />
                  <span className="text-sm font-bold text-[#164e63]">{selectedDevice.hostname}</span>
                  <span className="text-xs font-mono text-black/35">{selectedDevice.ip_address}</span>
                  <span className="text-[11px] text-black/30">{selectedDevice.platform || ''}</span>
                  {snapshots.length >= 2 && (
                    <button
                      onClick={() => void handleQuickCompare()}
                      className="ml-auto inline-flex h-8 items-center gap-1.5 rounded-lg bg-gradient-to-r from-[#06b6d4] to-[#0891b2] px-3.5 text-[11px] font-bold text-white shadow-[0_2px_10px_rgba(6,182,212,0.2)] hover:shadow-[0_4px_16px_rgba(6,182,212,0.3)] transition-all active:scale-[0.97]"
                    >
                      <Zap size={12} />
                      {zh ? '快速对比最近两次' : 'Compare Latest 2'}
                    </button>
                  )}
                </div>

                {snapshotsLoading ? (
                  <div className="flex-1 flex items-center justify-center">
                    <div className="text-sm text-black/40 flex items-center gap-2">
                      <RotateCcw size={14} className="animate-spin" /> {zh ? '加载快照...' : 'Loading...'}
                    </div>
                  </div>
                ) : snapshots.length === 0 ? (
                  <div className="flex-1 flex items-center justify-center">
                    <div className="text-center">
                      <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-black/[0.03]">
                        <Clock size={28} strokeWidth={1.2} className="text-black/20" />
                      </div>
                      <p className="text-sm font-semibold text-[#164e63]">{zh ? '该设备暂无配置备份' : 'No backups yet'}</p>
                      <p className="text-xs mt-1.5 text-black/30">{zh ? '请先到备份中心执行备份操作' : 'Go to Backup Center first'}</p>
                    </div>
                  </div>
                ) : snapshots.length < 2 ? (
                  /* ── Insufficient snapshots ── */
                  <div className="flex-1 flex items-center justify-center px-5">
                    <div className="text-center max-w-md">
                      <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-amber-50 ring-1 ring-amber-200/60">
                        <ArrowLeftRight size={24} className="text-amber-500" />
                      </div>
                      <p className="text-sm font-semibold text-[#164e63]">
                        {zh ? '需要至少 2 份备份才能对比' : 'Need ≥ 2 Backups'}
                      </p>
                      <p className="mt-2 text-xs text-black/40 leading-relaxed">
                        {zh
                          ? '当前仅有 1 份快照，请在「备份中心」再次备份或等待定时任务。'
                          : 'Only 1 snapshot exists. Back up again or wait for the next scheduled backup.'}
                      </p>
                      <div className="mt-5 inline-flex items-center gap-2.5 rounded-xl border border-black/5 bg-[#fafbfc] px-4 py-3">
                        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#ecfeff]">
                          <Database size={13} className="text-[#0e7490]" />
                        </div>
                        <div className="text-left">
                          <div className="text-xs font-medium text-[#164e63]">{formatTime(snapshots[0].timestamp)}</div>
                          <div className="text-[10px] text-black/30">{snapshots[0].trigger || 'manual'} · {snapshots[0].vendor || ''} · {formatSize(snapshots[0].size)}</div>
                        </div>
                      </div>
                    </div>
                  </div>
                ) : (
                  /* ── Main: A/B staging + timeline ── */
                  <div className="flex-1 flex flex-col min-h-0">
                    {/* ━━ A vs B staging area ━━ */}
                    <div className="px-5 py-4 border-b border-black/[0.04] bg-gradient-to-b from-[#fafffe] to-white">
                      <div className="grid grid-cols-[1fr_auto_1fr_auto] items-center gap-3">
                        {/* Card A */}
                        {(() => {
                          const snapA = pickLeft ? snapshots.find(s => s.id === pickLeft) : null;
                          return (
                            <div className={`relative rounded-xl border-2 border-dashed px-4 py-3 transition-all min-h-[68px] flex items-center ${
                              snapA
                                ? 'border-[#06b6d4] bg-[#ecfeff]/60 border-solid'
                                : 'border-black/10 bg-black/[0.01]'
                            }`}>
                              <div className="absolute -top-2.5 left-3 px-1.5 bg-white">
                                <span className={`text-[10px] font-bold uppercase tracking-wider ${snapA ? 'text-[#06b6d4]' : 'text-black/25'}`}>
                                  {zh ? '基准 A' : 'Baseline A'}
                                </span>
                              </div>
                              {snapA ? (
                                <div className="flex items-center gap-3 w-full">
                                  <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#06b6d4] text-white text-sm font-bold flex-shrink-0">A</div>
                                  <div className="flex-1 min-w-0">
                                    <div className="text-sm font-semibold text-[#164e63] truncate">{formatTime(snapA.timestamp)}</div>
                                    <div className="text-[10px] text-black/35">{snapA.trigger || 'manual'} · {snapA.vendor || ''} · {formatSize(snapA.size)}</div>
                                  </div>
                                  <button onClick={() => setPickLeft(null)} className="p-1 rounded-md text-black/25 hover:text-red-400 hover:bg-red-50 transition flex-shrink-0">
                                    <X size={12} />
                                  </button>
                                </div>
                              ) : (
                                <div className="flex items-center gap-2 text-black/25">
                                  <div className="flex h-9 w-9 items-center justify-center rounded-lg border-2 border-dashed border-black/10 text-[11px] font-bold">A</div>
                                  <span className="text-xs">{zh ? '点击下方快照选择基准' : 'Select a baseline snapshot'}</span>
                                </div>
                              )}
                            </div>
                          );
                        })()}

                        {/* VS divider */}
                        <div className="flex flex-col items-center gap-1">
                          <div className="h-8 w-8 rounded-full bg-[#164e63]/5 flex items-center justify-center">
                            <ArrowLeftRight size={14} className="text-[#164e63]/40" />
                          </div>
                        </div>

                        {/* Card B */}
                        {(() => {
                          const snapB = pickRight ? snapshots.find(s => s.id === pickRight) : null;
                          return (
                            <div className={`relative rounded-xl border-2 border-dashed px-4 py-3 transition-all min-h-[68px] flex items-center ${
                              snapB
                                ? 'border-[#164e63] bg-[#f0f9ff]/60 border-solid'
                                : 'border-black/10 bg-black/[0.01]'
                            }`}>
                              <div className="absolute -top-2.5 left-3 px-1.5 bg-white">
                                <span className={`text-[10px] font-bold uppercase tracking-wider ${snapB ? 'text-[#164e63]' : 'text-black/25'}`}>
                                  {zh ? '对比 B' : 'Compare B'}
                                </span>
                              </div>
                              {snapB ? (
                                <div className="flex items-center gap-3 w-full">
                                  <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#164e63] text-white text-sm font-bold flex-shrink-0">B</div>
                                  <div className="flex-1 min-w-0">
                                    <div className="text-sm font-semibold text-[#164e63] truncate">{formatTime(snapB.timestamp)}</div>
                                    <div className="text-[10px] text-black/35">{snapB.trigger || 'manual'} · {snapB.vendor || ''} · {formatSize(snapB.size)}</div>
                                  </div>
                                  <button onClick={() => setPickRight(null)} className="p-1 rounded-md text-black/25 hover:text-red-400 hover:bg-red-50 transition flex-shrink-0">
                                    <X size={12} />
                                  </button>
                                </div>
                              ) : (
                                <div className="flex items-center gap-2 text-black/25">
                                  <div className="flex h-9 w-9 items-center justify-center rounded-lg border-2 border-dashed border-black/10 text-[11px] font-bold">B</div>
                                  <span className="text-xs">{zh ? '点击下方快照选择对比' : 'Select a compare snapshot'}</span>
                                </div>
                              )}
                            </div>
                          );
                        })()}

                        {/* Compare button */}
                        <button
                          disabled={!pickLeft || !pickRight}
                          onClick={() => void handleStartCompare()}
                          className="h-12 w-12 rounded-xl bg-gradient-to-br from-[#164e63] to-[#155e75] text-white shadow-[0_4px_16px_rgba(22,78,99,0.25)] flex items-center justify-center transition-all hover:-translate-y-0.5 hover:shadow-[0_8px_24px_rgba(22,78,99,0.35)] active:scale-95 disabled:opacity-25 disabled:cursor-not-allowed disabled:translate-y-0 disabled:shadow-none"
                          title={zh ? '开始对比' : 'Start Compare'}
                        >
                          <ArrowLeftRight size={18} />
                        </button>
                      </div>

                      {/* hint text */}
                      {!pickLeft && !pickRight && (
                        <p className="mt-3 text-center text-[11px] text-black/30">
                          {zh ? '↓ 点击快照行自动选择 A → B，也可点击行内 A / B 按钮手动指定' : '↓ Click rows to auto-assign A then B, or use A/B buttons'}
                        </p>
                      )}
                    </div>

                    {/* ━━ Snapshot timeline ━━ */}
                    <div className="flex-1 overflow-auto px-5 py-3">
                      <div className="text-[10px] font-bold uppercase tracking-widest text-black/25 mb-3">{zh ? `${snapshots.length} 份配置快照` : `${snapshots.length} Snapshots`}</div>
                      <div className="relative">
                        {/* Timeline rail */}
                        <div className="absolute left-[15px] top-2 bottom-2 w-0.5 bg-gradient-to-b from-[#06b6d4]/25 via-[#06b6d4]/10 to-transparent rounded-full" />

                        <div className="space-y-px">
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
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* ════════ Step 3: Diff viewer ════════ */}
        {showDiffViewer && (
          <div className="flex-1 overflow-auto font-mono text-xs leading-6 bg-[#f7fbfc]">
            <div className="h-full flex flex-col">
              <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-5 py-3 text-xs">
                <div className="flex min-w-0 items-center gap-3">
                  <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-cyan-50 text-cyan-700"><Server size={15} /></div>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate font-sans text-sm font-black text-[#123b50]">{analysis?.device.hostname || configDiffRight.hostname}</span>
                      {analysis?.device.ip_address && <code className="text-[10px] text-slate-400">{analysis.device.ip_address}</code>}
                      {analysis?.device.platform && <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[9px] font-bold text-slate-600">{analysis.device.platform}</span>}
                      <span className={`rounded-full px-1.5 py-0.5 text-[8px] font-bold ${analysis?.device.status === 'online' ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>{analysis?.device.status || '—'}</span>
                    </div>
                    <p className="mt-0.5 font-sans text-[9px] text-slate-400">
                      {zh ? '变化方向' : 'Direction'}：A {formatTime(configDiffLeft.timestamp)} → B {formatTime(configDiffRight.timestamp)}
                      {analysis?.direction_reversed && <span className="ml-2 font-bold text-amber-600">{zh ? '时间方向已反转' : 'Time direction reversed'}</span>}
                    </p>
                  </div>
                </div>
                <div className="ml-auto flex flex-wrap items-center gap-1.5">
                  {analysisLoading && <span className="inline-flex items-center gap-1 text-[9px] text-cyan-700"><Loader2 size={11} className="animate-spin" />{zh ? '对象分析中' : 'Analyzing'}</span>}
                  <button type="button" onClick={() => void onSelectSnapshotPair(configDiffRight.id, configDiffLeft.id)} className="rounded-lg border border-slate-200 p-1.5 text-slate-500 hover:border-cyan-300 hover:text-cyan-700" title={zh ? '交换 A/B' : 'Swap A/B'}><ArrowLeftRight size={12} /></button>
                  <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-0.5">
                    {(['normalized', 'raw'] as const).map((mode) => (
                      <button key={mode} type="button" onClick={() => onDiffModeChange(mode)} className={`rounded px-2 py-0.5 text-[9px] transition-colors ${diffMode === mode ? 'bg-[#123b50] text-white shadow-sm' : 'text-slate-500 hover:text-[#123b50]'}`}>
                        {mode === 'normalized' ? (zh ? '标准化' : 'Normalized') : (zh ? '原始' : 'Raw')}
                      </button>
                    ))}
                  </div>
                  {(['markdown', 'html', 'json'] as const).map((format) => (
                    <button key={format} type="button" disabled={Boolean(exporting)} onClick={() => void exportAnalysis(format)} className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1.5 text-[8px] font-bold uppercase text-slate-500 hover:border-cyan-200 hover:text-cyan-700 disabled:opacity-40">
                      {exporting === format ? <Loader2 size={10} className="animate-spin" /> : <Download size={10} />}{format === 'markdown' ? 'MD' : format}
                    </button>
                  ))}
                  <button type="button" disabled={confirming} onClick={() => void confirmAnalysis()} className="inline-flex items-center gap-1 rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-1.5 text-[9px] font-bold text-emerald-700 disabled:opacity-40">
                    {confirming ? <Loader2 size={10} className="animate-spin" /> : <CheckCircle2 size={10} />}{zh ? '标记已确认' : 'Confirm'}
                  </button>
                </div>
              </div>
              {analysis && (
                <div className="shrink-0 border-b border-slate-200 bg-gradient-to-r from-slate-50 via-white to-cyan-50/40 px-5 py-3">
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
                    {[
                      { label: zh ? '新增行' : 'Added', value: analysis.summary.added_lines, cls: 'text-emerald-700 bg-emerald-50' },
                      { label: zh ? '删除行' : 'Removed', value: analysis.summary.removed_lines, cls: 'text-rose-700 bg-rose-50' },
                      { label: zh ? '变更对象' : 'Objects', value: analysis.summary.changed_objects, cls: 'text-cyan-700 bg-cyan-50' },
                      { label: zh ? '影响模块' : 'Modules', value: analysis.summary.affected_modules, cls: 'text-blue-700 bg-blue-50' },
                      { label: zh ? '高风险' : 'High risk', value: analysis.summary.high_risk_changes, cls: 'text-orange-700 bg-orange-50' },
                      { label: zh ? '合规率' : 'Compliance', value: `${analysis.compliance.compliance_rate}%`, cls: 'text-violet-700 bg-violet-50' },
                    ].map((item) => (
                      <div key={item.label} className="flex items-center justify-between rounded-xl border border-white bg-white/80 px-3 py-2 shadow-sm">
                        <span className="font-sans text-[9px] font-bold text-slate-400">{item.label}</span>
                        <span className={`rounded-lg px-2 py-0.5 font-sans text-sm font-black ${item.cls}`}>{item.value}</span>
                      </div>
                    ))}
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    {Object.entries(analysis.summary.object_counts).map(([name, count]) => (
                      <button type="button" key={name} onClick={() => {
                        setAnalysisView('objects');
                        setObjectFilter(name);
                      }} className="rounded-full border border-slate-200 bg-white px-2 py-0.5 font-sans text-[8px] font-bold text-slate-500 hover:border-cyan-200 hover:text-cyan-700">{name} {count}</button>
                    ))}
                    {analysis.source_correlation.out_of_band_suspected && (
                      <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-rose-50 px-2 py-0.5 font-sans text-[8px] font-black text-rose-700"><FileWarning size={10} />{zh ? '疑似带外变更' : 'Possible out-of-band change'}</span>
                    )}
                    {analysis.requires_mfa && <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 font-sans text-[8px] font-black text-amber-700"><ShieldAlert size={10} />MFA</span>}
                    {analysis.cache.hit && <span className="rounded-full bg-slate-100 px-2 py-0.5 font-sans text-[8px] text-slate-500">{zh ? '缓存命中' : 'Cache hit'}</span>}
                  </div>
                </div>
              )}
              {analysisError && (
                <div className="flex shrink-0 items-center gap-2 border-b border-rose-100 bg-rose-50 px-5 py-2 font-sans text-[10px] text-rose-700">
                  <AlertTriangle size={12} /><span className="flex-1">{analysisError}</span>
                  <button type="button" onClick={() => void loadStructuredAnalysis(true)} className="font-bold underline">{zh ? '重试' : 'Retry'}</button>
                  <button type="button" onClick={() => setAnalysisError('')}><X size={12} /></button>
                </div>
              )}
              <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 bg-slate-50/80 px-5 py-2 font-sans text-[10px] text-slate-500">
                <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5">
                  {([
                    ['text', zh ? '统一 Diff' : 'Unified diff', GitBranch],
                    ['objects', zh ? '对象视图' : 'Object view', Boxes],
                    ['risks', zh ? '风险与合规' : 'Risk & compliance', ShieldAlert],
                  ] as const).map(([view, label, Icon]) => (
                    <button type="button" key={view} onClick={() => setAnalysisView(view)} className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-[9px] font-bold ${analysisView === view ? 'bg-[#123b50] text-white' : 'text-slate-500 hover:text-slate-800'}`}>
                      <Icon size={10} />{label}
                    </button>
                  ))}
                </div>
                {analysisView === 'text' && (
                  <>
                    {activeChangeLineIndexes.length > 0 && <span className="rounded-md bg-slate-100 px-2 py-1 text-[9px] font-bold text-slate-500 tabular-nums">{safeFocusIdx + 1}/{activeChangeLineIndexes.length}</span>}
                    <button onClick={() => onJumpToDiff('prev')} disabled={activeChangeLineIndexes.length === 0} className="rounded-lg border border-slate-200 bg-white p-1.5 text-slate-500 disabled:opacity-30"><ChevronLeft size={11} /></button>
                    <button onClick={() => onJumpToDiff('next')} disabled={activeChangeLineIndexes.length === 0} className="rounded-lg border border-slate-200 bg-white p-1.5 text-slate-500 disabled:opacity-30"><ChevronRight size={11} /></button>
                    <button onClick={onToggleOnlyChanges} className={`rounded-lg border px-2 py-1 text-[9px] font-bold ${diffOnlyChanges ? 'border-cyan-300 bg-cyan-50 text-cyan-700' : 'border-slate-200 bg-white text-slate-500'}`}>{zh ? '仅变更' : 'Changes only'}</button>
                    <button onClick={onToggleFullBoth} className={`rounded-lg border px-2 py-1 text-[9px] font-bold ${diffShowFullBoth ? 'border-cyan-300 bg-cyan-50 text-cyan-700' : 'border-slate-200 bg-white text-slate-500'}`}>{zh ? '左右对照' : 'Side by side'}</button>
                  </>
                )}
                <span className="ml-auto hidden items-center gap-1 font-semibold text-emerald-600 sm:inline-flex"><ShieldCheck size={11} />{diffMode === 'normalized' ? (zh ? '已隐藏采集噪声' : 'Collection noise hidden') : (zh ? '原始审计文本' : 'Raw audit text')}</span>
              </div>
              <div className="flex-1 min-h-0 overflow-hidden p-4">
                {analysisView === 'objects' ? (
                  <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
                    <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 bg-slate-50/70 px-4 py-3">
                      <span className="font-sans text-[10px] font-black uppercase tracking-wider text-[#123b50]">{zh ? '结构化变更对象' : 'Structured change objects'}</span>
                      <button type="button" onClick={() => setObjectFilter('all')} className={`rounded-full px-2.5 py-1 font-sans text-[9px] font-bold ${objectFilter === 'all' ? 'bg-[#123b50] text-white' : 'border border-slate-200 bg-white text-slate-500'}`}>
                        {zh ? '全部' : 'All'} {analysis?.objects.length || 0}
                      </button>
                      {Object.entries(analysis?.summary.object_counts || {}).map(([name, count]) => (
                        <button type="button" key={name} onClick={() => setObjectFilter(name)} className={`rounded-full px-2.5 py-1 font-sans text-[9px] font-bold ${objectFilter === name ? 'bg-cyan-600 text-white' : 'border border-slate-200 bg-white text-slate-500 hover:border-cyan-200 hover:text-cyan-700'}`}>
                          {name} {count}
                        </button>
                      ))}
                      {analysisLoading && <Loader2 size={13} className="ml-auto animate-spin text-cyan-600" />}
                    </div>
                    <div className="flex-1 overflow-auto p-3">
                      {filteredObjects.length > 0 ? (
                        <div className="grid gap-3 xl:grid-cols-2">
                          {filteredObjects.map((item) => (
                            <article key={item.id} className="overflow-hidden rounded-xl border border-slate-200 bg-white">
                              <div className="flex items-start gap-3 border-b border-slate-100 bg-slate-50/60 px-4 py-3">
                                <span className={`mt-0.5 rounded-lg px-2 py-1 font-sans text-[8px] font-black uppercase ${
                                  item.change_type === 'added' ? 'bg-emerald-50 text-emerald-700' : item.change_type === 'deleted' ? 'bg-rose-50 text-rose-700' : 'bg-amber-50 text-amber-700'
                                }`}>{item.change_type === 'added' ? (zh ? '新增' : 'Added') : item.change_type === 'deleted' ? (zh ? '删除' : 'Deleted') : (zh ? '修改' : 'Modified')}</span>
                                <div className="min-w-0 flex-1">
                                  <div className="truncate font-sans text-xs font-black text-[#123b50]">{item.object_name}</div>
                                  <div className="mt-0.5 font-sans text-[9px] text-slate-400">{item.object_type} · {item.module}</div>
                                </div>
                                <span className={`rounded-full px-2 py-0.5 font-sans text-[8px] font-black ${
                                  item.risk_level === 'critical' || item.risk_level === 'high' ? 'bg-rose-50 text-rose-700' : item.risk_level === 'medium' ? 'bg-amber-50 text-amber-700' : 'bg-slate-100 text-slate-500'
                                }`}>{item.risk_level || 'low'}</span>
                              </div>
                              <div className="space-y-3 px-4 py-3">
                                {item.field_changes.length > 0 && (
                                  <div className="overflow-hidden rounded-lg border border-slate-100">
                                    {item.field_changes.map((field, index) => (
                                      <div key={`${field.field}-${index}`} className="grid grid-cols-[100px_1fr_18px_1fr] items-start gap-2 border-b border-slate-100 px-3 py-2 font-sans text-[9px] last:border-b-0">
                                        <span className="font-bold text-slate-500">{field.field}</span>
                                        <code className="break-all text-rose-600">{String(field.before ?? '--')}</code>
                                        <ArrowLeftRight size={10} className="mt-0.5 text-slate-300" />
                                        <code className="break-all text-emerald-600">{String(field.after ?? '--')}</code>
                                      </div>
                                    ))}
                                  </div>
                                )}
                                <div className="grid gap-2 md:grid-cols-2">
                                  <div className="rounded-lg bg-rose-50/70 p-2.5">
                                    <div className="font-sans text-[8px] font-black uppercase text-rose-500">{zh ? '变更前' : 'Before'}</div>
                                    <pre className="mt-1 max-h-28 overflow-auto whitespace-pre-wrap break-all font-mono text-[8px] leading-4 text-rose-800">{item.before_lines.join('\n') || '--'}</pre>
                                  </div>
                                  <div className="rounded-lg bg-emerald-50/70 p-2.5">
                                    <div className="font-sans text-[8px] font-black uppercase text-emerald-500">{zh ? '变更后' : 'After'}</div>
                                    <pre className="mt-1 max-h-28 overflow-auto whitespace-pre-wrap break-all font-mono text-[8px] leading-4 text-emerald-800">{item.after_lines.join('\n') || '--'}</pre>
                                  </div>
                                </div>
                                {(item.risk_reason || item.potential_impact) && (
                                  <div className="rounded-lg border border-amber-100 bg-amber-50/70 px-3 py-2 font-sans text-[9px] leading-4 text-amber-800">
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
                  <div className="grid h-full min-h-0 gap-4 overflow-auto xl:grid-cols-[1.15fr_0.85fr]">
                    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
                      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 bg-slate-50/70 px-4 py-3">
                        <ShieldAlert size={13} className="text-rose-600" />
                        <span className="font-sans text-[10px] font-black uppercase tracking-wider text-[#123b50]">{zh ? '变更风险' : 'Change risks'}</span>
                        {['all', 'critical', 'high', 'medium', 'low'].map((level) => (
                          <button type="button" key={level} onClick={() => setRiskFilter(level)} className={`rounded-full px-2 py-1 font-sans text-[8px] font-bold ${riskFilter === level ? 'bg-[#123b50] text-white' : 'border border-slate-200 bg-white text-slate-500'}`}>
                            {level === 'all' ? (zh ? '全部' : 'All') : level}
                          </button>
                        ))}
                      </div>
                      <div className="max-h-full space-y-2 overflow-auto p-3">
                        {filteredRisks.map((risk, index) => (
                          <div key={`${risk.rule_id}-${risk.object_name}-${index}`} className={`rounded-xl border p-3 ${
                            risk.severity === 'critical' || risk.severity === 'high' ? 'border-rose-200 bg-rose-50/60' : risk.severity === 'medium' ? 'border-amber-200 bg-amber-50/60' : 'border-slate-200 bg-slate-50'
                          }`}>
                            <div className="flex items-start gap-2">
                              <span className="rounded-md bg-white px-2 py-0.5 font-sans text-[8px] font-black uppercase text-slate-600 shadow-sm">{risk.severity}</span>
                              <div className="min-w-0 flex-1">
                                <div className="font-sans text-[10px] font-black text-[#123b50]">{risk.message}</div>
                                <div className="mt-1 font-sans text-[9px] text-slate-500">{risk.object_type} · {risk.object_name}</div>
                                {risk.potential_impact && <p className="mt-2 font-sans text-[9px] leading-4 text-slate-600">{risk.potential_impact}</p>}
                              </div>
                              {(risk.requires_mfa || risk.requires_secondary_approval) && (
                                <div className="flex flex-col items-end gap-1">
                                  {risk.requires_mfa && <span className="rounded bg-amber-100 px-1.5 py-0.5 font-sans text-[7px] font-black text-amber-700">MFA</span>}
                                  {risk.requires_secondary_approval && <span className="rounded bg-violet-100 px-1.5 py-0.5 font-sans text-[7px] font-black text-violet-700">{zh ? '复核' : 'Review'}</span>}
                                </div>
                              )}
                            </div>
                          </div>
                        ))}
                        {filteredRisks.length === 0 && <p className="py-12 text-center font-sans text-xs font-bold text-slate-400">{zh ? '未发现匹配风险' : 'No matching risks found'}</p>}
                      </div>
                    </section>
                    <div className="space-y-4 overflow-auto">
                      <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
                        <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
                          <span className="inline-flex items-center gap-1.5 font-sans text-[10px] font-black text-[#123b50]"><FileCheck2 size={12} className="text-violet-600" />{zh ? '合规检查' : 'Compliance checks'}</span>
                          <span className="font-sans text-xs font-black text-violet-700">{analysis?.compliance.compliance_rate ?? 0}%</span>
                        </div>
                        <div className="space-y-2 p-3">
                          {(analysis?.compliance.findings || []).map((finding) => (
                            <div key={finding.rule_id} className={`rounded-lg border px-3 py-2 ${finding.status === 'compliant' ? 'border-emerald-100 bg-emerald-50/50' : 'border-rose-100 bg-rose-50/50'}`}>
                              <div className="flex items-center gap-2 font-sans text-[9px]">
                                {finding.status === 'compliant' ? <CheckCircle2 size={11} className="text-emerald-600" /> : <AlertTriangle size={11} className="text-rose-600" />}
                                <span className="flex-1 font-black text-slate-700">{finding.name}</span>
                                <span className="text-slate-400">{finding.observed_count}/{finding.expected_count}</span>
                              </div>
                              {finding.status !== 'compliant' && finding.remediation && <p className="mt-1.5 pl-5 font-sans text-[8px] leading-4 text-rose-700">{finding.remediation}</p>}
                            </div>
                          ))}
                        </div>
                      </section>
                      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                        <div className="font-sans text-[10px] font-black text-[#123b50]">{zh ? '变更来源关联' : 'Change source correlation'}</div>
                        <p className={`mt-2 rounded-lg px-3 py-2 font-sans text-[9px] leading-4 ${analysis?.source_correlation.out_of_band_suspected ? 'bg-rose-50 text-rose-700' : 'bg-emerald-50 text-emerald-700'}`}>
                          {analysis?.source_correlation.message || (zh ? '暂无关联结果' : 'No correlation result')}
                        </p>
                        <div className="mt-2 space-y-1.5">
                          {(analysis?.source_correlation.correlations || []).map((source) => (
                            <div key={`${source.source_type}-${source.source_id}`} className="flex items-center gap-2 rounded-lg border border-slate-100 px-3 py-2 font-sans text-[8px] text-slate-500">
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
                <div className="flex h-full min-h-0 gap-4 overflow-hidden">
                <div className="flex-1 overflow-auto rounded-xl border border-slate-200 bg-white shadow-sm">
                  {diffShowFullBoth ? (
                    <div className="min-w-[960px]">
                      <div className="sticky top-0 z-10 grid grid-cols-2 border-b border-slate-200 bg-slate-50 text-[10px] uppercase tracking-wider text-slate-500">
                        <div className="px-4 py-2 border-r border-slate-200">{zh ? '左侧配置 (A)' : 'Left Config (A)'}</div>
                        <div className="px-4 py-1.5">{zh ? '右侧配置 (B)' : 'Right Config (B)'}</div>
                      </div>
                      {fullSideBySideRows.map((row) => {
                        const isFocused = focusedLineIndex !== undefined && row.originalIndex === focusedLineIndex;
                        return (
                          <div key={row.originalIndex} ref={(el) => { diffLineRefs.current[row.originalIndex] = el; }} className={`grid grid-cols-2 ${isFocused ? 'ring-1 ring-cyan-300 bg-cyan-50' : ''}`}>
                            <div className={`flex items-start px-4 py-0.5 border-r border-slate-100 ${row.rowType === 'remove' ? 'bg-red-50' : ''}`}>
                              <span className="w-10 text-right text-slate-300 pr-3 select-none flex-shrink-0">{row.leftLine || ''}</span>
                              <span className="w-4 select-none flex-shrink-0 text-red-400">{row.rowType === 'remove' ? '−' : ' '}</span>
                              <span className={`${row.rowType === 'remove' ? 'text-red-700' : 'text-slate-600'} whitespace-pre`}>{row.leftContent}</span>
                            </div>
                            <div className={`flex items-start px-4 py-0.5 ${row.rowType === 'add' ? 'bg-emerald-50' : ''}`}>
                              <span className="w-10 text-right text-slate-300 pr-3 select-none flex-shrink-0">{row.rightLine || ''}</span>
                              <span className="w-4 select-none flex-shrink-0 text-emerald-400">{row.rowType === 'add' ? '+' : ' '}</span>
                              <span className={`${row.rowType === 'add' ? 'text-emerald-700' : 'text-slate-600'} whitespace-pre`}>{row.rightContent}</span>
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
                           className={`flex items-start px-4 py-0.5 ${line.type === 'add' ? 'bg-emerald-50' : line.type === 'remove' ? 'bg-red-50' : ''} ${isFocused ? 'ring-1 ring-cyan-300 bg-cyan-50' : ''}`}
                        >
                           <span className="w-10 text-right text-slate-300 pr-3 select-none flex-shrink-0">{line.lineA || ''}</span>
                           <span className="w-10 text-right text-slate-300 pr-3 select-none flex-shrink-0">{line.lineB || ''}</span>
                           <span className={`w-4 select-none flex-shrink-0 ${line.type === 'add' ? 'text-emerald-600' : line.type === 'remove' ? 'text-red-600' : 'text-slate-300'}`}>
                            {line.type === 'add' ? '+' : line.type === 'remove' ? '−' : ' '}
                          </span>
                           <span className={`${line.type === 'add' ? 'text-emerald-700' : line.type === 'remove' ? 'text-red-700' : 'text-slate-600'} whitespace-pre`}>{line.content}</span>
                        </div>
                      );
                    })
                  )}
                </div>
                {diffChangeBlocks.length > 0 && (
                  <aside className="hidden xl:block w-64 rounded-xl border border-slate-200 bg-white overflow-auto shadow-sm">
                    <div className="px-3 py-3 border-b border-slate-100">
                      <div className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">{zh ? '变更目录' : 'Change Map'}</div>
                      <input
                        value={diffBlockQuery}
                        onChange={(e) => onDiffBlockQueryChange(e.target.value)}
                        placeholder={zh ? '过滤: interface / route / acl' : 'Filter: interface / route / acl'}
                        className="mt-2 w-full px-2.5 py-2 rounded-lg border border-slate-200 bg-slate-50 text-[10px] text-slate-700 placeholder:text-slate-400 outline-none focus:border-cyan-300 focus:bg-white"
                      />
                      <div className="mt-2 flex flex-wrap gap-1">
                        {['interface', 'route', 'acl', 'bgp', 'ospf', 'vlan'].map((kw) => (
                          <button
                            key={kw}
                            onClick={() => onToggleQuickKeyword(kw)}
                            className={`px-1.5 py-0.5 rounded text-[9px] border transition-colors ${diffBlockQuery.toLowerCase() === kw ? 'border-cyan-300 text-cyan-700 bg-cyan-50' : 'border-slate-200 text-slate-500 hover:text-[#123b50] hover:border-slate-300'}`}
                          >
                            {kw}
                          </button>
                        ))}
                      </div>
                    </div>
                    <div className="p-2 space-y-1.5">
                      {filteredDiffChangeBlocks.map((block, idx) => {
                        const isActive = diffFocusChangeIdx >= block.startChangeIdx && diffFocusChangeIdx <= block.endChangeIdx;
                        return (
                          <button
                            key={`${block.startChangeIdx}-${block.endChangeIdx}`}
                            onClick={() => onFocusDiffChangeAt(block.startChangeIdx)}
                            className={`w-full text-left px-2.5 py-2 rounded-lg border transition-all ${isActive ? 'border-cyan-300 bg-cyan-50 text-cyan-800' : 'border-slate-200 text-slate-500 hover:text-[#123b50] hover:border-slate-300 hover:bg-slate-50'}`}
                            title={block.label}
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="text-[10px] font-bold">#{idx + 1}</span>
                              <span className="text-[10px] font-mono text-slate-400">{block.startChangeIdx + 1}-{block.endChangeIdx + 1}</span>
                            </div>
                            <div className="mt-1 text-[10px] leading-4 truncate">{block.label}</div>
                          </button>
                        );
                      })}
                      {filteredDiffChangeBlocks.length === 0 && (
                        <p className="px-2 py-2 text-[10px] text-slate-400">{zh ? '没有匹配的变更块' : 'No matching change block'}</p>
                      )}
                    </div>
                  </aside>
                )}
                </div>
                )}
              </div>
              <div className="flex shrink-0 flex-wrap items-center gap-2 border-t border-slate-100 bg-white px-5 py-3">
                <div className="mr-auto font-sans text-[9px] text-slate-400">
                  {zh ? '任何回滚都只生成受控恢复方案，不会从差异页直接下发设备。' : 'Rollback actions only create a governed recovery plan; this page never pushes commands directly.'}
                </div>
                {configDiffRight && (
                  <button type="button" onClick={() => void handleSetBaseline(configDiffRight.id)} disabled={baselineSaving === configDiffRight.id} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2 font-sans text-[9px] font-bold text-slate-600 hover:border-cyan-200 hover:text-cyan-700 disabled:opacity-50">
                    {baselineSaving === configDiffRight.id ? <Loader2 size={11} className="animate-spin" /> : <Database size={11} />}{zh ? '设 B 为基准' : 'Set B as baseline'}
                  </button>
                )}
                <button type="button" onClick={() => void prepareRollback()} disabled={rollbackLoading} className="inline-flex items-center gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 font-sans text-[9px] font-bold text-amber-700 disabled:opacity-50">
                  {rollbackLoading ? <Loader2 size={11} className="animate-spin" /> : <RotateCcw size={11} />}{zh ? '生成回滚预案' : 'Prepare rollback'}
                </button>
                <button type="button" onClick={() => navigate(`/change-orders?device_id=${encodeURIComponent(analysisDeviceId)}&snapshot_a=${encodeURIComponent(configDiffLeft?.id || '')}&snapshot_b=${encodeURIComponent(configDiffRight?.id || '')}`)} className="inline-flex items-center gap-1.5 rounded-lg bg-[#123b50] px-3 py-2 font-sans text-[9px] font-bold text-white hover:bg-[#0b2d3e]">
                  <Zap size={11} />{zh ? '创建变更工单' : 'Create change order'}
                </button>
              </div>
              {rollbackPlan && (
                <div className="shrink-0 border-t border-amber-100 bg-amber-50/70 px-5 py-3">
                  <div className="flex flex-wrap items-start gap-3">
                    <ShieldAlert size={14} className="mt-0.5 text-amber-700" />
                    <div className="min-w-0 flex-1">
                      <div className="font-sans text-[10px] font-black text-amber-900">{zh ? '受控回滚预案已生成' : 'Governed rollback plan prepared'} · {rollbackPlan.plan_id}</div>
                      <p className="mt-1 font-sans text-[9px] leading-4 text-amber-800">{rollbackPlan.warning || (zh ? `目标 ${rollbackPlan.line_count} 行配置；必须经过变更工单、MFA、恢复前备份和回滚计时器。` : `${rollbackPlan.line_count} target lines; change order, MFA, pre-restore backup, and rollback timer are required.`)}</p>
                      {rollbackPlan.blockers.length > 0 && <p className="mt-1 font-sans text-[8px] font-bold text-rose-700">{zh ? '阻断项：' : 'Blockers: '}{rollbackPlan.blockers.join('；')}</p>}
                    </div>
                    <button type="button" onClick={() => setRollbackPlan(null)} className="text-amber-700"><X size={13} /></button>
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
