import React, { useEffect, useState, useCallback } from 'react';
import { ChevronLeft, ChevronRight, RotateCcw, Search, X, Database, Clock, ArrowLeftRight, Zap } from 'lucide-react';
import type { DiffLine } from '../types';
import Pagination from '../components/Pagination';

/* ── shared interfaces (kept compatible with App.tsx) ── */

interface DiffSnapshot {
  id: string;
  hostname: string;
  ip_address?: string;
  timestamp: string;
  trigger?: string;
  content?: string;
  size?: number;
  vendor?: string;
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
  onDiffBlockQueryChange,
  onToggleQuickKeyword,
  onFocusDiffChangeAt,
  preSelectedDeviceId,
}) => {
  const zh = language === 'zh';
  const safeFocusIdx = activeChangeLineIndexes.length === 0 ? 0 : Math.min(diffFocusChangeIdx, activeChangeLineIndexes.length - 1);
  const focusedLineIndex = activeChangeLineIndexes[safeFocusIdx];
  const added = activeDiffLines.filter((l) => l.type === 'add').length;
  const removed = activeDiffLines.filter((l) => l.type === 'remove').length;

  /* ── Step 1: Device list ── */
  const [deviceSearch, setDeviceSearch] = useState('');
  const [devices, setDevices] = useState<BackupDevice[]>([]);
  const [devicesTotal, setDevicesTotal] = useState(0);
  const [devicesLoading, setDevicesLoading] = useState(false);
  const [devPage, setDevPage] = useState(1);
  const [devPageSize, setDevPageSize] = useState(10);
  const [selectedDevice, setSelectedDevice] = useState<BackupDevice | null>(null);

  /* ── Step 2: Snapshot list for selected device ── */
  const [snapshots, setSnapshots] = useState<DiffSnapshot[]>([]);
  const [snapshotsLoading, setSnapshotsLoading] = useState(false);
  const [pickLeft, setPickLeft] = useState<string | null>(null);
  const [pickRight, setPickRight] = useState<string | null>(null);

  /* ── Load devices ── */
  const loadDevices = useCallback(async (q = '', pg = devPage, ps = devPageSize) => {
    setDevicesLoading(true);
    try {
      const params = new URLSearchParams({ page: String(pg), page_size: String(ps) });
      if (q.trim()) params.set('search', q.trim());
      const resp = await fetch(`/api/configs/devices-with-backups?${params}`);
      if (resp.ok) {
        const data = await resp.json();
        setDevices(data.items || []);
        setDevicesTotal(data.total || 0);
      }
    } catch { /* ignore */ }
    finally { setDevicesLoading(false); }
  }, [devPage, devPageSize]);

  useEffect(() => { void loadDevices(deviceSearch); }, [loadDevices, deviceSearch]);

  /* ── Pre-select device from backup center navigation ── */
  useEffect(() => {
    if (preSelectedDeviceId && devices.length > 0 && !selectedDevice) {
      const found = devices.find(d => d.id === preSelectedDeviceId);
      if (found) handleSelectDevice(found);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preSelectedDeviceId, devices]);

  /* ── Load snapshots for selected device ── */
  const loadSnapshots = useCallback(async (deviceId: string) => {
    setSnapshotsLoading(true);
    try {
      const resp = await fetch(`/api/configs/snapshots?device_id=${encodeURIComponent(deviceId)}`);
      if (resp.ok) {
        const data: DiffSnapshot[] = await resp.json();
        setSnapshots(data.sort((a, b) => b.timestamp.localeCompare(a.timestamp)));
      }
    } catch { /* ignore */ }
    finally { setSnapshotsLoading(false); }
  }, []);

  const handleSelectDevice = (dev: BackupDevice) => {
    setSelectedDevice(dev);
    setPickLeft(null);
    setPickRight(null);
    onReset();
    void loadSnapshots(dev.id);
  };

  const handleBackToDevices = () => {
    setSelectedDevice(null);
    setSnapshots([]);
    setPickLeft(null);
    setPickRight(null);
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

  /* ── Start compare ── */
  const handleStartCompare = async () => {
    if (!pickLeft || !pickRight) return;
    await onSelectSnapshotPair(pickLeft, pickRight);
  };

  /* ── Quick compare: latest two ── */
  const handleQuickCompare = async () => {
    if (snapshots.length < 2) return;
    const leftId = snapshots[0].id;
    const rightId = snapshots[1].id;
    setPickLeft(leftId);
    setPickRight(rightId);
    await onSelectSnapshotPair(leftId, rightId);
  };

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

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div className="flex justify-between items-end mb-5 flex-shrink-0">
        <div>
          <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-black/35">
            {zh ? '配置管理 / 配置对比' : 'Config / Diff Compare'}
          </p>
          <h2 className="mt-2 text-2xl font-semibold text-[#164e63]">{t('diffCompare')}</h2>
          <p className="mt-1 text-sm text-black/40">
            {showDiffViewer
              ? (zh ? `${configDiffLeft.hostname} 的两个版本配置对比` : `Comparing two snapshots of ${configDiffLeft.hostname}`)
              : (zh ? '选择设备和快照进行配置差异对比' : 'Select a device and snapshots to compare')}
          </p>
        </div>
        {(selectedDevice || showDiffViewer) && (
          <button
            onClick={showDiffViewer ? () => { onReset(); } : handleBackToDevices}
            className="text-xs text-black/40 hover:text-black transition px-3 py-1.5 border border-black/10 rounded-xl hover:bg-black/[0.03]"
          >
            {showDiffViewer ? (zh ? '重新选择' : 'Re-select') : (zh ? '返回设备列表' : 'Back to devices')}
          </button>
        )}
      </div>

      <div className="flex-1 overflow-hidden rounded-[28px] border border-black/5 bg-white shadow-[0_16px_36px_rgba(11,35,64,0.06)] flex flex-col">
        {/* ════════ Step 1 + 2: Selection area ════════ */}
        {!showDiffViewer && (
          <div className="flex-1 overflow-auto">
            {!selectedDevice ? (
              /* ──── Step 1: Device list ──── */
              <div className="p-5">
                <div className="flex items-center gap-3 mb-4">
                  <label className="relative flex-1 max-w-md">
                    <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-black/30" />
                    <input
                      value={deviceSearch}
                      onChange={(e) => { setDeviceSearch(e.target.value); setDevPage(1); }}
                      placeholder={zh ? '搜索设备名称或 IP ...' : 'Search hostname or IP...'}
                      className="w-full rounded-xl border border-black/10 bg-white py-3 pl-9 pr-9 text-sm text-[#164e63] outline-none placeholder:text-black/30 focus:border-[#06b6d4]/40 focus:ring-2 focus:ring-[#06b6d4]/10 transition-all"
                    />
                    {deviceSearch && (
                      <button onClick={() => { setDeviceSearch(''); setDevPage(1); }} className="absolute right-3 top-1/2 -translate-y-1/2 text-black/30 hover:text-black/60">
                        <X size={14} />
                      </button>
                    )}
                  </label>
                  <span className="rounded-xl bg-[#f0f9ff] px-3 py-2.5 text-sm font-medium text-[#164e63]">
                    {zh ? `${devicesTotal} 台设备有备份` : `${devicesTotal} devices with backups`}
                  </span>
                </div>

                {devicesLoading ? (
                  <div className="py-16 text-center text-sm text-black/40 flex items-center justify-center gap-2">
                    <RotateCcw size={14} className="animate-spin" /> {zh ? '加载中...' : 'Loading...'}
                  </div>
                ) : devices.length === 0 ? (
                  <div className="py-16 text-center text-black/25">
                    <Database size={36} strokeWidth={1} className="mx-auto mb-3" />
                    <p className="text-sm font-medium">{zh ? '暂无配置备份' : 'No config backups yet'}</p>
                    <p className="text-xs mt-1">{zh ? '请先到备份中心执行备份操作' : 'Go to Backup Center first'}</p>
                  </div>
                ) : (
                  <div className="grid gap-2">
                    {devices.map((dev) => (
                      <button
                        key={dev.id}
                        onClick={() => handleSelectDevice(dev)}
                        className="group w-full text-left flex items-center gap-4 px-4 py-3.5 rounded-2xl border border-black/5 bg-white hover:bg-[#f0fdfa] hover:border-[#06b6d4]/20 hover:shadow-[0_4px_16px_rgba(6,182,212,0.08)] transition-all"
                      >
                        <div className={`h-2.5 w-2.5 flex-shrink-0 rounded-full ${dev.status === 'online' ? 'bg-emerald-500' : 'bg-red-400'}`} />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-baseline gap-2">
                            <span className="text-sm font-semibold text-[#164e63]">{dev.hostname}</span>
                            <span className="text-xs font-mono text-black/45">{dev.ip_address}</span>
                          </div>
                          <div className="mt-0.5 text-[11px] text-black/35">
                            {dev.platform || '--'} · {zh ? `最近备份: ${timeSince(dev.latest_backup)}` : `Last backup: ${timeSince(dev.latest_backup)}`}
                          </div>
                        </div>
                        <span className="rounded-full bg-[#ecfeff] px-2.5 py-1 text-[11px] font-bold text-[#0e7490]">
                          {dev.backup_count} {zh ? '份' : ''}
                        </span>
                        <ChevronRight size={14} className="text-black/20 group-hover:text-[#06b6d4] transition-colors" />
                      </button>
                    ))}
                  </div>
                )}

                {devicesTotal > devPageSize && (
                  <div className="mt-4">
                    <Pagination
                      currentPage={devPage}
                      totalItems={devicesTotal}
                      itemsPerPage={devPageSize}
                      onPageChange={setDevPage}
                      onItemsPerPageChange={(v) => { setDevPage(1); setDevPageSize(v); }}
                      language={language}
                    />
                  </div>
                )}
              </div>
            ) : (
              /* ──── Step 2: Snapshot selection ──── */
              <div className="p-5">
                <div className="mb-4 flex flex-wrap items-center gap-3">
                  <button onClick={handleBackToDevices} className="text-xs text-[#0e7490] hover:text-[#06b6d4] transition">
                    ← {zh ? '返回设备列表' : 'Back'}
                  </button>
                  <div className="flex items-center gap-2">
                    <div className={`h-2 w-2 rounded-full ${selectedDevice.status === 'online' ? 'bg-emerald-500' : 'bg-red-400'}`} />
                    <span className="text-sm font-semibold text-[#164e63]">{selectedDevice.hostname}</span>
                    <span className="text-xs font-mono text-black/45">{selectedDevice.ip_address}</span>
                  </div>
                  <div className="ml-auto flex items-center gap-2">
                    {snapshots.length >= 2 && (
                      <button
                        onClick={() => void handleQuickCompare()}
                        className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#06b6d4] px-3 text-xs font-semibold text-white shadow-[0_8px_16px_rgba(6,182,212,0.2)] hover:-translate-y-0.5 hover:bg-[#0891b2] transition-all"
                      >
                        <Zap size={13} />
                        {zh ? '最近两次对比' : 'Compare Latest 2'}
                      </button>
                    )}
                    {pickLeft && pickRight && (
                      <button
                        onClick={() => void handleStartCompare()}
                        className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#164e63] px-4 text-xs font-semibold text-white shadow-[0_8px_16px_rgba(22,78,99,0.2)] hover:-translate-y-0.5 hover:bg-[#155e75] transition-all"
                      >
                        <ArrowLeftRight size={13} />
                        {zh ? '开始对比' : 'Start Compare'}
                      </button>
                    )}
                  </div>
                </div>

                <div className="mb-3 text-xs text-black/40">
                  {zh
                    ? '请从下方列表中选择 基准(A) 和 对比(B) 两个快照，或点击「最近两次对比」快速开始。'
                    : 'Select a Baseline (A) and Compare (B) snapshot below, or click "Compare Latest 2" to start quickly.'}
                </div>

                {snapshotsLoading ? (
                  <div className="py-16 text-center text-sm text-black/40 flex items-center justify-center gap-2">
                    <RotateCcw size={14} className="animate-spin" /> {zh ? '加载快照列表...' : 'Loading snapshots...'}
                  </div>
                ) : snapshots.length === 0 ? (
                  <div className="py-16 text-center text-black/25">
                    <Clock size={36} strokeWidth={1} className="mx-auto mb-3" />
                    <p className="text-sm">{zh ? '该设备暂无配置备份' : 'No backups for this device'}</p>
                  </div>
                ) : (
                  <div className="grid gap-2">
                    {snapshots.map((snap) => {
                      const isLeft = pickLeft === snap.id;
                      const isRight = pickRight === snap.id;
                      const isPicked = isLeft || isRight;
                      return (
                        <div
                          key={snap.id}
                          className={`flex items-center gap-3 px-4 py-3 rounded-2xl border transition-all ${
                            isPicked
                              ? isLeft
                                ? 'border-[#06b6d4]/40 bg-[#ecfeff] shadow-[0_2px_12px_rgba(6,182,212,0.1)]'
                                : 'border-[#164e63]/30 bg-[#f0f9ff] shadow-[0_2px_12px_rgba(22,78,99,0.08)]'
                              : 'border-black/5 bg-white hover:bg-black/[0.01]'
                          }`}
                        >
                          <div className="flex items-center gap-1.5 flex-shrink-0">
                            <button
                              onClick={() => handlePickSnapshot('left', snap.id)}
                              className={`h-7 min-w-[28px] rounded-lg text-[10px] font-bold border transition-all ${
                                isLeft
                                  ? 'bg-[#06b6d4] border-[#06b6d4] text-white'
                                  : 'border-black/10 text-black/35 hover:border-[#06b6d4]/40 hover:text-[#06b6d4]'
                              }`}
                              title={zh ? '设为基准 (A)' : 'Set as Baseline (A)'}
                            >
                              A
                            </button>
                            <button
                              onClick={() => handlePickSnapshot('right', snap.id)}
                              className={`h-7 min-w-[28px] rounded-lg text-[10px] font-bold border transition-all ${
                                isRight
                                  ? 'bg-[#164e63] border-[#164e63] text-white'
                                  : 'border-black/10 text-black/35 hover:border-[#164e63]/40 hover:text-[#164e63]'
                              }`}
                              title={zh ? '设为对比 (B)' : 'Set as Compare (B)'}
                            >
                              B
                            </button>
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="text-sm font-medium text-[#164e63]">{formatTime(snap.timestamp)}</span>
                              <span className="text-[10px] text-black/30">{timeSince(snap.timestamp)}</span>
                            </div>
                            <div className="mt-0.5 flex items-center gap-2 text-[11px] text-black/40">
                              <span className={`inline-flex rounded-full px-2 py-0.5 text-[9px] font-bold uppercase ${
                                snap.trigger === 'manual'
                                  ? 'bg-cyan-50 text-cyan-600'
                                  : 'bg-amber-50 text-amber-600'
                              }`}>
                                {snap.trigger || 'manual'}
                              </span>
                              {snap.vendor && <span>{snap.vendor}</span>}
                              {snap.size != null && snap.size > 0 && <span className="font-mono">{formatSize(snap.size)}</span>}
                            </div>
                          </div>
                          {isPicked && (
                            <span className={`text-[10px] font-bold ${isLeft ? 'text-[#06b6d4]' : 'text-[#164e63]'}`}>
                              {isLeft ? (zh ? '基准' : 'Baseline') : (zh ? '对比' : 'Compare')}
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* ════════ Step 3: Diff viewer ════════ */}
        {showDiffViewer && (
          <div className="flex-1 overflow-auto font-mono text-xs leading-6">
            <div className="h-full bg-[#1E1E1E] flex flex-col">
              <div className="flex items-center gap-3 px-5 py-2.5 border-b border-white/5 text-xs">
                <span className="font-mono text-white/40">{configDiffLeft.hostname}</span>
                <span className="text-white/20">→</span>
                <span className="font-mono text-white/40">{configDiffRight.hostname}</span>
                <span className="ml-auto text-emerald-400">+{added} {t('linesAdded')}</span>
                <span className="text-red-400">−{removed} {t('linesRemoved')}</span>
                {added === 0 && removed === 0 && <span className="text-white/40">{t('noDiff')}</span>}
                {activeChangeLineIndexes.length > 0 && <span className="text-white/45 font-mono">{safeFocusIdx + 1}/{activeChangeLineIndexes.length}</span>}
                <button
                  onClick={() => onJumpToDiff('prev')}
                  disabled={activeChangeLineIndexes.length === 0}
                  className="p-1 rounded border border-white/15 text-white/60 hover:text-white hover:border-white/30 disabled:opacity-30 disabled:cursor-not-allowed"
                  title={zh ? '上一处差异 (P)' : 'Previous change (P)'}
                >
                  <ChevronLeft size={13} />
                </button>
                <button
                  onClick={() => onJumpToDiff('next')}
                  disabled={activeChangeLineIndexes.length === 0}
                  className="p-1 rounded border border-white/15 text-white/60 hover:text-white hover:border-white/30 disabled:opacity-30 disabled:cursor-not-allowed"
                  title={zh ? '下一处差异 (N)' : 'Next change (N)'}
                >
                  <ChevronRight size={13} />
                </button>
                <button
                  onClick={onToggleOnlyChanges}
                  className={`px-2 py-1 rounded border transition-colors ${diffOnlyChanges ? 'border-[#00bceb]/60 text-[#00d3ff] bg-[#00bceb]/10' : 'border-white/15 text-white/60 hover:text-white hover:border-white/30'}`}
                  title={zh ? '仅显示变更行 (F)' : 'Show changed lines only (F)'}
                >
                  {zh ? '仅变更' : 'Changes only'}
                </button>
                <button
                  onClick={onToggleFullBoth}
                  className={`px-2 py-1 rounded border transition-colors ${diffShowFullBoth ? 'border-[#00bceb]/60 text-[#00d3ff] bg-[#00bceb]/10' : 'border-white/15 text-white/60 hover:text-white hover:border-white/30'}`}
                  title={zh ? '显示两侧完整配置' : 'Show full configs on both sides'}
                >
                  {zh ? '两侧全部' : 'Both full'}
                </button>
              </div>
              <div className="px-5 py-1.5 border-b border-white/5 text-[11px] text-white/35">
                {zh ? '可使用右上角按钮快速定位与筛选差异块' : 'Use toolbar buttons above to jump and filter change blocks quickly'}
              </div>
              <div className="flex-1 min-h-0 flex overflow-hidden">
                <div className="flex-1 overflow-auto">
                  {diffShowFullBoth ? (
                    <div className="min-w-[960px]">
                      <div className="sticky top-0 z-10 grid grid-cols-2 border-b border-white/10 bg-[#181818] text-[10px] uppercase tracking-wider text-white/45">
                        <div className="px-4 py-1.5 border-r border-white/10">{zh ? '左侧配置 (A)' : 'Left Config (A)'}</div>
                        <div className="px-4 py-1.5">{zh ? '右侧配置 (B)' : 'Right Config (B)'}</div>
                      </div>
                      {fullSideBySideRows.map((row) => {
                        const isFocused = focusedLineIndex !== undefined && row.originalIndex === focusedLineIndex;
                        return (
                          <div key={row.originalIndex} ref={(el) => { diffLineRefs.current[row.originalIndex] = el; }} className={`grid grid-cols-2 ${isFocused ? 'ring-1 ring-[#00d3ff]/80 bg-[#00bceb]/10' : ''}`}>
                            <div className={`flex items-start px-4 py-0.5 border-r border-white/10 ${row.rowType === 'remove' ? 'bg-red-500/15' : ''}`}>
                              <span className="w-10 text-right text-white/20 pr-3 select-none flex-shrink-0">{row.leftLine || ''}</span>
                              <span className="w-4 select-none flex-shrink-0 text-red-400">{row.rowType === 'remove' ? '−' : ' '}</span>
                              <span className={`${row.rowType === 'remove' ? 'text-red-300' : 'text-[#d4d4d4]'} whitespace-pre`}>{row.leftContent}</span>
                            </div>
                            <div className={`flex items-start px-4 py-0.5 ${row.rowType === 'add' ? 'bg-emerald-500/15' : ''}`}>
                              <span className="w-10 text-right text-white/20 pr-3 select-none flex-shrink-0">{row.rightLine || ''}</span>
                              <span className="w-4 select-none flex-shrink-0 text-emerald-400">{row.rowType === 'add' ? '+' : ' '}</span>
                              <span className={`${row.rowType === 'add' ? 'text-emerald-300' : 'text-[#d4d4d4]'} whitespace-pre`}>{row.rightContent}</span>
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
                          className={`flex items-start px-4 py-0.5 ${line.type === 'add' ? 'bg-emerald-500/15' : line.type === 'remove' ? 'bg-red-500/15' : ''} ${isFocused ? 'ring-1 ring-[#00d3ff]/80 bg-[#00bceb]/10' : ''}`}
                        >
                          <span className="w-10 text-right text-white/20 pr-3 select-none flex-shrink-0">{line.lineA || ''}</span>
                          <span className="w-10 text-right text-white/20 pr-3 select-none flex-shrink-0">{line.lineB || ''}</span>
                          <span className={`w-4 select-none flex-shrink-0 ${line.type === 'add' ? 'text-emerald-400' : line.type === 'remove' ? 'text-red-400' : 'text-white/20'}`}>
                            {line.type === 'add' ? '+' : line.type === 'remove' ? '−' : ' '}
                          </span>
                          <span className={`${line.type === 'add' ? 'text-emerald-300' : line.type === 'remove' ? 'text-red-300' : 'text-[#d4d4d4]'} whitespace-pre`}>{line.content}</span>
                        </div>
                      );
                    })
                  )}
                </div>
                {diffChangeBlocks.length > 0 && (
                  <aside className="hidden xl:block w-64 border-l border-white/10 bg-[#181818] overflow-auto">
                    <div className="px-3 py-2 border-b border-white/10">
                      <div className="text-[10px] uppercase tracking-wider text-white/45 font-bold">{zh ? '变更目录' : 'Change Map'}</div>
                      <input
                        value={diffBlockQuery}
                        onChange={(e) => onDiffBlockQueryChange(e.target.value)}
                        placeholder={zh ? '过滤: interface / route / acl' : 'Filter: interface / route / acl'}
                        className="mt-2 w-full px-2 py-1.5 rounded-md border border-white/15 bg-black/25 text-[10px] text-white/80 placeholder:text-white/30 outline-none focus:border-[#00bceb]/50"
                      />
                      <div className="mt-2 flex flex-wrap gap-1">
                        {['interface', 'route', 'acl', 'bgp', 'ospf', 'vlan'].map((kw) => (
                          <button
                            key={kw}
                            onClick={() => onToggleQuickKeyword(kw)}
                            className={`px-1.5 py-0.5 rounded text-[9px] border transition-colors ${diffBlockQuery.toLowerCase() === kw ? 'border-[#00bceb]/60 text-[#7ee8ff] bg-[#00bceb]/10' : 'border-white/15 text-white/55 hover:text-white hover:border-white/30'}`}
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
                            className={`w-full text-left px-2.5 py-2 rounded-lg border transition-all ${isActive ? 'border-[#00bceb]/60 bg-[#00bceb]/15 text-[#7ee8ff]' : 'border-white/10 text-white/60 hover:text-white hover:border-white/25 hover:bg-white/5'}`}
                            title={block.label}
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="text-[10px] font-bold">#{idx + 1}</span>
                              <span className="text-[10px] font-mono text-white/45">{block.startChangeIdx + 1}-{block.endChangeIdx + 1}</span>
                            </div>
                            <div className="mt-1 text-[10px] leading-4 truncate">{block.label}</div>
                          </button>
                        );
                      })}
                      {filteredDiffChangeBlocks.length === 0 && (
                        <p className="px-2 py-2 text-[10px] text-white/35">{zh ? '没有匹配的变更块' : 'No matching change block'}</p>
                      )}
                    </div>
                  </aside>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default ConfigDiffViewTab;