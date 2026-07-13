import React, { useEffect, useState, useCallback, useRef } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Database, Download, Eye, RefreshCw, Search, X, FileText, Copy, ArrowLeftRight, Trash2, CheckCircle2, AlertTriangle, ChevronDown, ChevronUp } from 'lucide-react';
import Pagination from '../components/Pagination';
import PageHero from '../components/PageHero';

interface LatestBackup {
  id: string;
  device_id: string;
  hostname: string;
  ip_address: string;
  vendor: string;
  platform: string;
  device_status: string;
  trigger: string;
  timestamp: string;
  size: number;
}

interface ConfigBackupTabProps {
  t: (key: string) => string;
  language: string;
  isTakingSnapshot: boolean;
  onBackupAllOnline: () => Promise<void> | void;
  onBackupDevice: (deviceId: string) => Promise<void>;
  onNavigateToDiff: (deviceId: string) => void;
  showToast: (msg: string, type?: 'success' | 'error' | 'info') => void;
  /** run_id returned by POST /configs/run-now — used to poll live progress */
  activeRunId?: string | null;
}

const copyTextToClipboard = async (text: string): Promise<boolean> => {
  if (window.isSecureContext && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {}
  }

  const textArea = document.createElement('textarea');
  textArea.value = text;
  textArea.setAttribute('readonly', '');
  textArea.style.position = 'fixed';
  textArea.style.left = '-9999px';
  textArea.style.top = '0';
  textArea.style.opacity = '0';
  document.body.appendChild(textArea);

  try {
    textArea.focus();
    textArea.select();
    textArea.setSelectionRange(0, text.length);
    return document.execCommand('copy');
  } catch {
    return false;
  } finally {
    document.body.removeChild(textArea);
  }
};

const ConfigBackupTab: React.FC<ConfigBackupTabProps> = ({
  t,
  language,
  isTakingSnapshot,
  onBackupAllOnline,
  onBackupDevice,
  onNavigateToDiff,
  showToast,
  activeRunId,
}) => {
  const zh = language === 'zh';

  const [rows, setRows] = useState<LatestBackup[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [search, setSearch] = useState('');

  // Live progress state
  const [progress, setProgress] = useState<{
    total: number;
    done: number;
    success: number;
    failed: number;
    finished: boolean;
    skipped?: number;
    started_at?: number;
    finished_at?: number | null;
    devices: Array<{ hostname: string; status: string; reason?: string; detail?: string }>;
  } | null>(null);
  const pollRef = useRef<number | null>(null);

  const [showDetails, setShowDetails] = useState(false);
  const [elapsed, setElapsed] = useState<number>(0);

  // Reset showDetails when a new progress session starts
  useEffect(() => {
    if (progress && progress.done === 0) {
      setShowDetails(false);
    }
  }, [progress?.total, progress?.done]);

  useEffect(() => {
    if (!progress) {
      setElapsed(0);
      return;
    }
    const start = progress.started_at || (Date.now() / 1000);
    
    if (progress.finished) {
      const end = progress.finished_at || (Date.now() / 1000);
      setElapsed(Math.max(0, Math.floor(end - start)));
      return;
    }

    setElapsed(Math.max(0, Math.floor(Date.now() / 1000 - start)));
    const interval = window.setInterval(() => {
      setElapsed(Math.max(0, Math.floor(Date.now() / 1000 - start)));
    }, 1000);

    return () => window.clearInterval(interval);
  }, [progress]);

  const formatElapsed = (seconds: number) => {
    if (seconds < 60) {
      return zh ? `${seconds} 秒` : `${seconds}s`;
    }
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return zh ? `${mins} 分 ${secs} 秒` : `${mins}m ${secs}s`;
  };

  // Poll progress when a run is active
  useEffect(() => {
    if (!activeRunId) {
      if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null; }
      setProgress(null);
      return;
    }
    const token = localStorage.getItem('netops_token');
    const poll = async () => {
      try {
        const r = await fetch(`/api/configs/run-now/${activeRunId}/progress`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (!r.ok) return;
        const p = await r.json();
        setProgress(p);
        if (p.finished && pollRef.current) {
          window.clearInterval(pollRef.current);
          pollRef.current = null;
          // Final list refresh
          void loadLatestBackups();
        }
      } catch { /* ignore */ }
    };
    void poll();
    pollRef.current = window.setInterval(poll, 1500);
    return () => { if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null; } };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeRunId]);

  // Clear progress banner a few seconds after finishing
  useEffect(() => {
    if (progress?.finished) {
      const t = window.setTimeout(() => setProgress(null), 8000);
      return () => window.clearTimeout(t);
    }
  }, [progress?.finished]);

  // View config modal
  const [viewSnapshot, setViewSnapshot] = useState<LatestBackup | null>(null);
  const [viewContent, setViewContent] = useState('');
  const [viewLoading, setViewLoading] = useState(false);
  const [backupingDeviceId, setBackupingDeviceId] = useState<string | null>(null);

  const loadLatestBackups = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
      });
      if (search) params.set('search', search);
      const resp = await fetch(`/api/configs/latest-backups?${params}`);
      if (!resp.ok) throw new Error('Failed');
      const data = await resp.json();
      setRows(data.items || []);
      setTotal(data.total || 0);
    } catch {
      showToast(zh ? '加载备份列表失败' : 'Failed to load backups', 'error');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, search, zh, showToast]);

  useEffect(() => { void loadLatestBackups(); }, [loadLatestBackups]);

  const handleBackupAllClick = async () => {
    await onBackupAllOnline();
    void loadLatestBackups();
  };

  const handleBackupDeviceClick = async (deviceId: string) => {
    setBackupingDeviceId(deviceId);
    try {
      await onBackupDevice(deviceId);
      void loadLatestBackups();
    } finally {
      setBackupingDeviceId(null);
    }
  };

  const handleView = async (item: LatestBackup) => {
    setViewSnapshot(item);
    setViewContent('');
    setViewLoading(true);
    try {
      const resp = await fetch(`/api/configs/snapshots/${item.id}/content`);
      if (!resp.ok) throw new Error('Failed');
      const data = await resp.json();
      setViewContent(data.content || '');
    } catch {
      showToast(zh ? '加载配置内容失败' : 'Failed to load config', 'error');
    } finally {
      setViewLoading(false);
    }
  };

  const handleDownload = (item: LatestBackup) => {
    const a = document.createElement('a');
    a.href = `/api/configs/snapshots/${item.id}/download`;
    const ts = new Date().toISOString().replace(/[-:]/g, '').replace('T', '_').slice(0, 15);
    a.download = `${item.hostname}_${ts}.cfg`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  const handleCopy = async () => {
    if (!viewContent) return;
    const copied = await copyTextToClipboard(viewContent);
    if (copied) {
      showToast(zh ? '已复制到剪贴板' : 'Copied', 'success');
    } else {
      showToast(zh ? '复制失败' : 'Copy failed', 'error');
    }
  };

  const closeView = () => {
    setViewSnapshot(null);
    setViewContent('');
  };

  const [deleteTarget, setDeleteTarget] = useState<LatestBackup | null>(null);
  const [deleting, setDeleting] = useState(false);

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      const token = localStorage.getItem('netops_token');
      const resp = await fetch(`/api/configs/snapshots/${deleteTarget.id}`, {
        method: 'DELETE',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!resp.ok) throw new Error('Failed');
      showToast(zh ? `已删除 ${deleteTarget.hostname} 的备份` : `Deleted backup for ${deleteTarget.hostname}`, 'success');
      setDeleteTarget(null);
      void loadLatestBackups();
    } catch {
      showToast(zh ? '删除失败' : 'Delete failed', 'error');
    } finally {
      setDeleting(false);
    }
  };

  const formatTime = (ts: string) => {
    if (!ts) return '--';
    try { return new Date(ts).toLocaleString(); } catch { return ts; }
  };

  const formatSize = (size: number) => {
    if (!size) return '--';
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
      if (hours < 24) return zh ? `${hours} 小时前` : `${hours}h ago`;
      const days = Math.floor(hours / 24);
      if (days < 30) return zh ? `${days} 天前` : `${days}d ago`;
      return zh ? `${Math.floor(days / 30)} 月前` : `${Math.floor(days / 30)}mo ago`;
    } catch { return ''; }
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHero
        icon={Database}
        eyebrow={zh ? '配置管理 / 备份中心' : 'Config / Backup Center'}
        title={zh ? '备份中心' : 'Backup Center'}
        subtitle={zh ? '展示所有设备的最近一次配置备份。' : 'Latest config backup for each device.'}
        actions={
          <>
            <button
              onClick={() => void handleBackupAllClick()}
              disabled={isTakingSnapshot}
              className="inline-flex h-11 items-center justify-center gap-2 rounded-2xl bg-[#06b6d4] px-4 text-sm font-semibold text-white shadow-[0_12px_24px_rgba(6,182,212,0.22)] transition-all duration-200 hover:-translate-y-0.5 hover:bg-[#0891b2] disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:translate-y-0"
            >
              {isTakingSnapshot ? <RefreshCw size={14} className="animate-spin" /> : <Database size={14} />}
              {zh ? '备份全部在线设备' : 'Backup All Online'}
            </button>
            <button
              onClick={() => void loadLatestBackups()}
              className="inline-flex h-11 items-center justify-center gap-2 rounded-2xl border border-[#d8e1eb] bg-[#f7f9fc] px-4 text-sm font-semibold text-[#0e7490] transition-all duration-200 hover:-translate-y-0.5 hover:border-[#c7d4e2] hover:bg-white hover:text-[#0891b2]"
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              {zh ? '刷新' : 'Refresh'}
            </button>
          </>
        }
      />

      <div className="flex-1 overflow-auto px-6 py-5 space-y-4">
      <div className="rounded-[28px] border border-black/5 bg-white shadow-[0_16px_36px_rgba(11,35,64,0.06)]">
        {/* Live backup progress banner */}
        <AnimatePresence>
          {progress && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden"
            >
              <div className={`mx-5 mb-5 rounded-[24px] border p-6 transition-colors duration-300 ${
                progress.finished
                  ? progress.failed > 0
                    ? 'bg-amber-50/70 border-amber-200/80 shadow-[0_8px_30px_rgba(245,158,11,0.05)]'
                    : 'bg-emerald-50/70 border-emerald-200/80 shadow-[0_8px_30px_rgba(16,185,129,0.05)]'
                  : 'bg-cyan-50/70 border-cyan-200/80 shadow-[0_8px_30px_rgba(6,182,212,0.05)]'
              }`}>
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
                  {/* Left: Progress info & Progress bar */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2.5 mb-3">
                      {progress.finished ? (
                        progress.failed > 0 ? (
                          <div className="p-1 rounded-lg bg-amber-100 text-amber-600">
                            <AlertTriangle size={16} />
                          </div>
                        ) : (
                          <div className="p-1 rounded-lg bg-emerald-100 text-emerald-600">
                            <CheckCircle2 size={16} />
                          </div>
                        )
                      ) : (
                        <div className="p-1 rounded-lg bg-cyan-100 text-cyan-600">
                          <RefreshCw size={16} className="animate-spin" />
                        </div>
                      )}
                      <div>
                        <h4 className={`text-sm font-bold tracking-tight ${
                          progress.finished
                            ? progress.failed > 0 ? 'text-amber-800' : 'text-emerald-800'
                            : 'text-cyan-800'
                        }`}>
                          {progress.finished
                            ? (zh ? '备份任务已完成' : 'Backup Task Completed')
                            : (zh ? '正在执行在线设备备份...' : 'Backing up online devices...')}
                        </h4>
                        <p className="text-xs text-black/40 mt-0.5">
                          {zh ? `已处理 ${progress.done} / ${progress.total} 台设备` : `Processed ${progress.done} of ${progress.total} devices`}
                        </p>
                      </div>
                    </div>
                    
                    {/* Progress Bar & Percentage */}
                    <div className="flex items-center gap-4">
                      <div className="flex-1 h-2.5 rounded-full bg-black/[0.05] overflow-hidden">
                        <motion.div
                          className={`h-full rounded-full ${
                            progress.finished
                              ? progress.failed > 0 ? 'bg-amber-500' : 'bg-emerald-500'
                              : 'bg-cyan-500'
                          }`}
                          initial={{ width: 0 }}
                          animate={{ width: progress.total > 0 ? `${Math.round((progress.done / progress.total) * 100)}%` : '0%' }}
                          transition={{ duration: 0.3 }}
                        />
                      </div>
                      <span className={`text-sm font-semibold font-mono ${
                        progress.finished
                          ? progress.failed > 0 ? 'text-amber-700' : 'text-emerald-700'
                          : 'text-cyan-700'
                      }`}>
                        {progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0}%
                      </span>
                    </div>
                  </div>

                  {/* Right: Metrics Grid */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 md:w-auto w-full flex-shrink-0">
                    {/* Success Counter */}
                    <div className="rounded-2xl bg-white/65 backdrop-blur-sm border border-black/[0.03] px-4 py-2.5 flex flex-col justify-center min-w-[90px]">
                      <span className="text-[10px] font-bold text-black/35 uppercase tracking-wider">{zh ? '成功' : 'Success'}</span>
                      <span className="text-base font-bold text-emerald-600 mt-0.5">{progress.success}</span>
                    </div>

                    {/* Failure Counter */}
                    <div className={`rounded-2xl bg-white/65 backdrop-blur-sm border border-black/[0.03] px-4 py-2.5 flex flex-col justify-center min-w-[90px] ${
                      progress.failed > 0 ? 'bg-red-50/50 border-red-100' : ''
                    }`}>
                      <span className="text-[10px] font-bold text-black/35 uppercase tracking-wider">{zh ? '失败' : 'Failed'}</span>
                      <span className={`text-base font-bold mt-0.5 ${progress.failed > 0 ? 'text-red-500' : 'text-black/50'}`}>
                        {progress.failed}
                      </span>
                    </div>

                    {/* Skipped Counter (if any) */}
                    {progress.skipped !== undefined && progress.skipped > 0 && (
                      <div className="rounded-2xl bg-white/65 backdrop-blur-sm border border-black/[0.03] px-4 py-2.5 flex flex-col justify-center min-w-[90px]">
                        <span className="text-[10px] font-bold text-black/35 uppercase tracking-wider">{zh ? '跳过' : 'Skipped'}</span>
                        <span className="text-base font-bold text-black/60 mt-0.5">{progress.skipped}</span>
                      </div>
                    )}

                    {/* Elapsed Time */}
                    <div className="rounded-2xl bg-white/65 backdrop-blur-sm border border-black/[0.03] px-4 py-2.5 flex flex-col justify-center min-w-[100px]">
                      <span className="text-[10px] font-bold text-black/35 uppercase tracking-wider">{zh ? '耗时' : 'Elapsed'}</span>
                      <span className="text-base font-bold text-cyan-600 mt-0.5 font-mono">
                        {formatElapsed(elapsed)}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Collapsible Details Button */}
                {progress.devices && progress.devices.length > 0 && (
                  <div className="mt-4 pt-3 border-t border-black/[0.04]">
                    <button
                      onClick={() => setShowDetails(!showDetails)}
                      className="inline-flex items-center gap-1.5 text-xs font-semibold text-black/45 hover:text-black/70 transition-colors"
                    >
                      {showDetails ? (
                        <>
                          <ChevronUp size={14} />
                          {zh ? '收起备份详情' : 'Hide Details'}
                        </>
                      ) : (
                        <>
                          <ChevronDown size={14} />
                          {zh ? `展开备份详情 (${progress.devices.length})` : `Show Details (${progress.devices.length})`}
                        </>
                      )}
                    </button>

                    {/* Collapsible Details Panel */}
                    <AnimatePresence>
                      {showDetails && (
                        <motion.div
                          initial={{ opacity: 0, height: 0 }}
                          animate={{ opacity: 1, height: 'auto' }}
                          exit={{ opacity: 0, height: 0 }}
                          transition={{ duration: 0.2 }}
                          className="overflow-hidden"
                        >
                          <div className="mt-3 max-h-48 overflow-y-auto rounded-xl bg-black/[0.02] border border-black/[0.03] p-3">
                            <div className="flex flex-wrap gap-1.5">
                              {progress.devices.map((d, i) => (
                                <span
                                  key={i}
                                  className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[10px] font-semibold border ${
                                    d.status === 'success'
                                      ? 'bg-emerald-50 border-emerald-100 text-emerald-700'
                                      : 'bg-red-50 border-red-100 text-red-700'
                                  }`}
                                  title={d.detail || (d.reason ? (zh ? `原因: ${d.reason}` : `Reason: ${d.reason}`) : undefined)}
                                >
                                  <span className={`h-1.5 w-1.5 rounded-full ${d.status === 'success' ? 'bg-emerald-500' : 'bg-red-500'}`} />
                                  {d.hostname}
                                  {d.status === 'failed' && d.reason && (
                                    <span className="opacity-60 font-normal">({d.reason})</span>
                                  )}
                                </span>
                              ))}
                            </div>
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Search */}
        <div className="flex items-center gap-3 px-5 py-4">
          <label className="relative min-w-[240px] flex-1">
            <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-black/30" />
            <input
              value={search}
              onChange={(e) => { setPage(1); setSearch(e.target.value); }}
              placeholder={zh ? '搜索设备名或 IP ...' : 'Search hostname or IP...'}
              className="w-full rounded-xl border border-black/10 bg-white py-3 pl-9 pr-3 text-sm text-[#164e63] outline-none placeholder:text-black/30 focus:border-[#06b6d4]/40 focus:ring-2 focus:ring-[#06b6d4]/10 transition-all"
            />
            {search && (
              <button onClick={() => { setSearch(''); setPage(1); }} className="absolute right-3 top-1/2 -translate-y-1/2 text-black/30 hover:text-black/60">
                <X size={14} />
              </button>
            )}
          </label>
          <span className="rounded-xl bg-[#f0f9ff] px-3 py-2.5 text-sm font-medium text-[#164e63]">
            {zh ? `${total} 台设备` : `${total} devices`}
          </span>
        </div>

        {/* Table */}
        <div className="overflow-x-auto">
          <table className="min-w-full border-collapse text-left">
            <thead>
              <tr className="border-y border-black/5 bg-[#f8fafc] text-[11px] font-bold uppercase tracking-[0.16em] text-black/40">
                <th className="px-5 py-3">{zh ? '设备名称' : 'Device'}</th>
                <th className="px-5 py-3">IP</th>
                <th className="px-5 py-3">{zh ? '厂商' : 'Vendor'}</th>
                <th className="px-5 py-3">{zh ? '最后备份时间' : 'Last Backup'}</th>
                <th className="px-5 py-3">{zh ? '大小' : 'Size'}</th>
                <th className="px-5 py-3 text-right">{zh ? '操作' : 'Actions'}</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={6} className="px-5 py-12 text-center text-sm text-black/40">
                    {zh ? '正在加载...' : 'Loading...'}
                  </td>
                </tr>
              ) : rows.length > 0 ? (
                rows.map(row => (
                  <tr key={row.device_id} className="border-b border-black/5 hover:bg-black/[0.02] transition-colors">
                    <td className="px-5 py-4 align-top">
                      <div className="flex items-center gap-2">
                        <div className={`h-2 w-2 flex-shrink-0 rounded-full ${row.device_status === 'online' ? 'bg-emerald-500' : 'bg-red-400'}`} />
                        <span className="text-sm font-semibold text-[#164e63]">{row.hostname}</span>
                      </div>
                    </td>
                    <td className="px-5 py-4 align-top text-sm font-mono text-black/55">{row.ip_address || '--'}</td>
                    <td className="px-5 py-4 align-top">
                      <span className="inline-flex rounded-full bg-black/5 px-2.5 py-1 text-[10px] font-bold uppercase text-black/50">
                        {row.vendor || '--'}
                      </span>
                    </td>
                    <td className="px-5 py-4 align-top">
                      <div className="text-sm text-black/60">{formatTime(row.timestamp)}</div>
                      <div className="mt-0.5 text-xs text-black/35">{timeSince(row.timestamp)}</div>
                    </td>
                    <td className="px-5 py-4 align-top text-sm text-black/50 font-mono">{formatSize(row.size)}</td>
                    <td className="px-5 py-4 align-top text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        <button
                          onClick={() => void handleBackupDeviceClick(row.device_id)}
                          disabled={backupingDeviceId === row.device_id || isTakingSnapshot}
                          className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-transparent bg-white text-[#0e7490] shadow-[0_1px_2px_rgba(6,182,212,0.08)] transition-all hover:-translate-y-0.5 hover:bg-[#ecfeff] hover:text-[#0891b2] disabled:opacity-40 disabled:hover:translate-y-0"
                          title={zh ? '备份此设备' : 'Backup this device'}
                        >
                          {backupingDeviceId === row.device_id
                            ? <RefreshCw size={14} className="animate-spin" />
                            : <Database size={14} />}
                        </button>
                        <button
                          onClick={() => onNavigateToDiff(row.device_id)}
                          className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-transparent bg-white text-[#0e7490] shadow-[0_1px_2px_rgba(6,182,212,0.08)] transition-all hover:-translate-y-0.5 hover:bg-[#ecfeff] hover:text-[#0891b2]"
                          title={zh ? '对比配置变更' : 'Compare config changes'}
                        >
                          <ArrowLeftRight size={14} />
                        </button>
                        <button
                          onClick={() => void handleView(row)}
                          disabled={!row.id}
                          className="inline-flex h-9 items-center justify-center gap-1.5 rounded-xl border border-transparent bg-white px-3 text-xs font-semibold text-[#0e7490] shadow-[0_1px_2px_rgba(6,182,212,0.08)] transition-all hover:-translate-y-0.5 hover:bg-[#ecfeff] hover:text-[#0891b2] disabled:opacity-40 disabled:hover:translate-y-0"
                          title={zh ? '查看配置' : 'View config'}
                        >
                          <Eye size={14} />
                          {zh ? '查看' : 'View'}
                        </button>
                        <button
                          onClick={() => handleDownload(row)}
                          disabled={!row.id}
                          className="inline-flex h-9 items-center justify-center gap-1.5 rounded-xl border border-transparent bg-white px-3 text-xs font-semibold text-[#0e7490] shadow-[0_1px_2px_rgba(6,182,212,0.08)] transition-all hover:-translate-y-0.5 hover:bg-[#ecfeff] hover:text-[#0891b2] disabled:opacity-40 disabled:hover:translate-y-0"
                          title={zh ? '下载配置' : 'Download'}
                        >
                          <Download size={14} />
                          {zh ? '下载' : 'Download'}
                        </button>
                        <button
                          onClick={() => setDeleteTarget(row)}
                          disabled={!row.id}
                          className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-transparent bg-white text-red-400 shadow-[0_1px_2px_rgba(0,0,0,0.04)] transition-all hover:-translate-y-0.5 hover:bg-red-50 hover:text-red-600 disabled:opacity-40 disabled:hover:translate-y-0"
                          title={zh ? '删除备份' : 'Delete backup'}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={6} className="px-5 py-16 text-center">
                    <div className="flex flex-col items-center gap-3 text-black/25">
                      <FileText size={36} strokeWidth={1} />
                      <p className="text-sm font-medium">{zh ? '暂无配置备份' : 'No config backups yet'}</p>
                      <p className="text-xs">{zh ? '点击上方「备份全部在线设备」开始首次备份。' : 'Click "Backup All Online" above to start.'}</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <Pagination
          currentPage={page}
          totalItems={total}
          itemsPerPage={pageSize}
          onItemsPerPageChange={(v) => { setPage(1); setPageSize(v); }}
          onPageChange={setPage}
          language={language}
        />
      </div>

      {/* View Config Modal */}
      <AnimatePresence>
        {viewSnapshot && (
          <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 p-4"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            onMouseDown={(e) => { if (e.target === e.currentTarget) closeView(); }}
          >
            <motion.div
              className="flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-3xl bg-white shadow-2xl"
              initial={{ y: 18, opacity: 0, scale: 0.98 }}
              animate={{ y: 0, opacity: 1, scale: 1 }}
              exit={{ y: 18, opacity: 0, scale: 0.98 }}
              transition={{ duration: 0.2 }}
            >
              {/* Modal header */}
              <div className="flex items-start justify-between gap-4 border-b border-black/5 px-6 py-5">
                <div>
                  <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-black/35">
                    {zh ? '配置查看' : 'Config View'}
                  </p>
                  <h3 className="mt-1 text-lg font-semibold text-[#164e63]">
                    {viewSnapshot.hostname}
                    <span className="ml-2 text-sm font-normal text-black/40">{viewSnapshot.ip_address}</span>
                  </h3>
                  <p className="mt-1 text-xs text-black/40">
                    {formatTime(viewSnapshot.timestamp)} · {formatSize(viewSnapshot.size)}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => void handleCopy()}
                    disabled={!viewContent}
                    className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-black/10 bg-white px-3 text-xs font-semibold text-black/55 hover:bg-black/[0.03] disabled:opacity-40"
                  >
                    <Copy size={13} />
                    {zh ? '复制' : 'Copy'}
                  </button>
                  <button
                    onClick={() => handleDownload(viewSnapshot)}
                    className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-black/10 bg-white px-3 text-xs font-semibold text-black/55 hover:bg-black/[0.03]"
                  >
                    <Download size={13} />
                    {zh ? '下载' : 'Download'}
                  </button>
                  <button title={zh ? '关闭' : 'Close'} onClick={closeView} className="rounded-xl border border-black/10 p-2 text-black/55 hover:bg-black/[0.03]">
                    <X size={16} />
                  </button>
                </div>
              </div>

              {/* Config content */}
              <div className="flex flex-1 overflow-hidden">
                {viewLoading ? (
                  <div className="flex flex-1 items-center justify-center bg-[#1E1E1E] text-white/30">
                    <RefreshCw size={20} className="animate-spin" />
                    <span className="ml-2 text-sm">{zh ? '加载中...' : 'Loading...'}</span>
                  </div>
                ) : viewContent ? (
                  <>
                    <div className="w-12 select-none overflow-hidden bg-[#1a1a1a] py-4 pr-3 text-right font-mono text-xs leading-6 text-white/20">
                      {viewContent.split('\n').map((_, i) => <div key={i}>{i + 1}</div>)}
                    </div>
                    <div className="flex-1 overflow-auto bg-[#1E1E1E] p-4 font-mono text-xs leading-6 text-[#d4d4d4]">
                      {viewContent.split('\n').map((line, i) => (
                        <div
                          key={i}
                          className={`rounded px-1 hover:bg-white/5 ${
                            line.startsWith('#') || line.startsWith('!')
                              ? 'text-[#6a9955]'
                              : /^(interface|vlan|ip route|ospf|bgp|acl)/.test(line)
                                ? 'text-[#569cd6]'
                                : /shutdown|down/.test(line)
                                  ? 'text-[#f48771]'
                                  : ''
                          }`}
                        >
                          {line || ' '}
                        </div>
                      ))}
                    </div>
                  </>
                ) : (
                  <div className="flex flex-1 flex-col items-center justify-center bg-[#1E1E1E] text-white/20">
                    <FileText size={32} strokeWidth={1} />
                    <p className="mt-3 text-sm">{zh ? '无配置内容' : 'No content available'}</p>
                  </div>
                )}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Delete Confirmation */}
      <AnimatePresence>
        {deleteTarget && (
          <motion.div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => !deleting && setDeleteTarget(null)}>
            <motion.div className="bg-white rounded-xl w-full max-w-sm p-5 shadow-2xl border border-black/5"
              onClick={e => e.stopPropagation()} initial={{ scale: 0.96, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.96, opacity: 0 }}>
              <div className="flex items-center gap-3 mb-3">
                <div className="h-9 w-9 rounded-full bg-red-50 flex items-center justify-center"><Trash2 size={16} className="text-red-500" /></div>
                <div>
                  <h3 className="text-sm font-bold text-black/80">{zh ? '删除备份' : 'Delete Backup'}</h3>
                  <p className="text-[10px] text-black/25 mt-0.5">{deleteTarget.hostname}</p>
                </div>
              </div>
              <p className="text-[11px] text-black/35 mb-4">{zh ? '删除后配置备份文件将被永久清除，是否继续？' : 'The backup file will be permanently removed. Continue?'}</p>
              <div className="flex justify-end gap-2">
                <button onClick={() => setDeleteTarget(null)} disabled={deleting} className="px-3 py-1.5 rounded-lg bg-black/[0.01] border border-black/5 text-black/40 text-xs hover:bg-black/[0.02]">{zh ? '取消' : 'Cancel'}</button>
                <button onClick={() => void handleDelete()} disabled={deleting} className="px-3 py-1.5 rounded-lg bg-red-600 text-white text-xs font-bold hover:bg-red-700 disabled:opacity-50">
                  {deleting ? (zh ? '删除中...' : 'Deleting...') : (zh ? '删除' : 'Delete')}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
      </div>
    </div>
  );
};

export default ConfigBackupTab;
