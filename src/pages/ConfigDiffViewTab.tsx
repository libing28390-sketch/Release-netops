import React, { useEffect, useState, useCallback } from 'react';
import { ChevronLeft, ChevronRight, RotateCcw, Search, X, Database, Clock, ArrowLeftRight, Zap } from 'lucide-react';
import type { DiffLine } from '../types';
import Pagination from '../components/Pagination';
import PageHero from '../components/PageHero';
import { GitCompare } from 'lucide-react';

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
  const [devPageSize, setDevPageSize] = useState(15);
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
      <PageHero
        icon={GitCompare}
        eyebrow={zh ? '配置管理 / 配置对比' : 'Config / Diff Compare'}
        title={t('diffCompare')}
        subtitle={showDiffViewer
          ? (zh ? `${configDiffLeft.hostname} 的两个版本配置对比` : `Comparing two snapshots of ${configDiffLeft.hostname}`)
          : (zh ? '选择设备和快照进行配置差异对比' : 'Select a device and snapshots to compare')}
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
              <div className="flex flex-col h-full">
                {/* Search + count bar */}
                <div className="flex items-center gap-3 px-5 pt-4 pb-3 border-b border-black/[0.04]">
                  <label className="relative flex-1 max-w-sm">
                    <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-black/25" />
                    <input
                      value={deviceSearch}
                      onChange={(e) => { setDeviceSearch(e.target.value); setDevPage(1); }}
                      placeholder={zh ? '搜索主机名 / IP ...' : 'Search hostname / IP...'}
                      className="w-full rounded-lg border border-black/8 bg-white py-2 pl-8 pr-8 text-[13px] text-[#164e63] outline-none placeholder:text-black/25 focus:border-[#06b6d4]/40 focus:ring-2 focus:ring-[#06b6d4]/10 transition-all"
                    />
                    {deviceSearch && (
                      <button onClick={() => { setDeviceSearch(''); setDevPage(1); }} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-black/25 hover:text-black/50">
                        <X size={13} />
                      </button>
                    )}
                  </label>
                  <span className="text-[11px] font-medium text-black/35">
                    {zh ? `共 ${devicesTotal} 台` : `${devicesTotal} devices`}
                  </span>
                </div>

                {/* Table header */}
                <div className="grid grid-cols-[auto_1fr_auto_auto_auto_auto] items-center gap-x-3 px-5 py-2 text-[10px] font-bold uppercase tracking-wider text-black/25 border-b border-black/[0.03]">
                  <span className="w-2" />
                  <span>{zh ? '设备' : 'Device'}</span>
                  <span className="hidden sm:block">{zh ? '平台' : 'Platform'}</span>
                  <span>{zh ? '备份数' : 'Backups'}</span>
                  <span className="hidden sm:block">{zh ? '最近备份' : 'Last Backup'}</span>
                  <span className="w-4" />
                </div>

                {/* Device rows */}
                <div className="flex-1 overflow-auto">
                  {devicesLoading ? (
                    <div className="py-16 text-center text-sm text-black/35 flex items-center justify-center gap-2">
                      <RotateCcw size={14} className="animate-spin" /> {zh ? '加载中...' : 'Loading...'}
                    </div>
                  ) : devices.length === 0 ? (
                    <div className="py-16 text-center text-black/25">
                      <Database size={32} strokeWidth={1} className="mx-auto mb-2 text-black/15" />
                      <p className="text-sm font-medium">{zh ? '暂无配置备份' : 'No config backups yet'}</p>
                      <p className="text-xs mt-1 text-black/30">{zh ? '请先到备份中心执行备份操作' : 'Go to Backup Center first'}</p>
                    </div>
                  ) : (
                    <div>
                      {devices.map((dev, idx) => (
                        <button
                          key={dev.id}
                          onClick={() => handleSelectDevice(dev)}
                          className={`group w-full text-left grid grid-cols-[auto_1fr_auto_auto_auto_auto] items-center gap-x-3 px-5 py-2.5 transition-colors hover:bg-[#f0fdfa] ${
                            idx > 0 ? 'border-t border-black/[0.03]' : ''
                          }`}
                        >
                          <div className={`h-2 w-2 flex-shrink-0 rounded-full ${dev.status === 'online' ? 'bg-emerald-500' : 'bg-red-400'}`} />
                          <div className="flex items-center gap-2 min-w-0">
                            <span className="text-[13px] font-semibold text-[#164e63] truncate">{dev.hostname}</span>
                            <span className="text-[11px] font-mono text-black/30 truncate hidden md:inline">{dev.ip_address}</span>
                          </div>
                          <span className="text-[11px] text-black/35 hidden sm:block truncate max-w-[100px]">{dev.platform || '--'}</span>
                          <span className="rounded-full bg-[#ecfeff] px-2 py-0.5 text-[10px] font-bold text-[#0e7490] tabular-nums">
                            {dev.backup_count}
                          </span>
                          <span className="text-[11px] text-black/30 hidden sm:block whitespace-nowrap">{timeSince(dev.latest_backup)}</span>
                          <ChevronRight size={13} className="text-black/15 group-hover:text-[#06b6d4] transition-colors" />
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                {devicesTotal > devPageSize && (
                  <div className="px-5 py-3 border-t border-black/[0.04]">
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
                                  <span className={`ml-auto flex-shrink-0 text-[9px] font-bold ${
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
    </div>
  );
};

export default ConfigDiffViewTab;