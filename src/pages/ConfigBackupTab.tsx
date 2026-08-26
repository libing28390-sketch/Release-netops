import React, { useEffect, useState, useCallback, useRef } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import * as XLSX from 'xlsx';
import { Database, Download, Eye, RefreshCw, Search, X, FileText, Copy, ArrowLeftRight, Trash2, CheckCircle2, AlertTriangle, ChevronDown, ChevronUp, ChevronLeft, ChevronRight, BarChart3, CalendarDays, UploadCloud, Server, Check } from 'lucide-react';
import Pagination from '../components/Pagination';
import PageHero from '../components/PageHero';
import { DataTable } from '../components/DataTable';
import { ActionButton, ActionIconButton, ActionIconGroup } from '../components/ui/ActionIconButton';

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
  config_type?: string;
  has_unsaved_changes?: boolean | number;
  unsaved_diff_summary?: string;
  raw_hash?: string;
  normalized_hash?: string;
  line_count?: number;
  section_count?: number;
  integrity_status?: string;
  lifecycle_status?: string;
}

interface BackupRun {
  id: string;
  trigger: string;
  author: string;
  status: string;
  started_at: string;
  finished_at?: string | null;
  total_devices: number;
  success_count: number;
  failed_count: number;
  skipped_count: number;
  error_message?: string;
  tftp_status?: string;
  tftp_server?: string;
  tftp_log?: string;
  tftp_uploaded_count?: number;
  site_summary?: Array<{
    site: string;
    total: number;
    success: number;
    failed: number;
    skipped: number;
    unknown: number;
  }>;
}

interface BackupRunDevice {
  id: string;
  device_id?: string | null;
  hostname: string;
  ip_address: string;
  platform: string;
  site?: string;
  status: string;
  reason?: string;
  detail?: string;
  snapshot_id?: string | null;
  started_at?: string;
  finished_at?: string | null;
  duration_ms?: number | null;
}

type DetailStatusFilter = 'all' | 'success' | 'failed' | 'unknown' | 'skipped' | 'abnormal';

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

type ArchiveProtocol = 'sftp' | 'ftp' | 'tftp';

interface ArchiveSettings {
  enabled: boolean;
  protocol: ArchiveProtocol;
  server_ip: string;
  server_port: number;
  username: string;
  password: string;
  password_configured?: boolean;
  path_prefix: string;
}

const archiveProtocolPort = (protocol: ArchiveProtocol): number => (
  protocol === 'sftp' ? 22 : protocol === 'ftp' ? 21 : 69
);

const archiveProtocolLabel = (protocol: ArchiveProtocol): string => {
  if (protocol === 'sftp') return 'SFTP';
  if (protocol === 'ftp') return 'FTP';
  return 'TFTP';
};

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

interface DateRangeCalendarProps {
  start: string;
  end: string;
  today: string;
  zh: boolean;
  onChange: (start: string, end: string) => void;
}

const DateRangeCalendar: React.FC<DateRangeCalendarProps> = ({ start, end, today, zh, onChange }) => {
  const initialMonth = (start || end || today).slice(0, 7);
  const [viewMonth, setViewMonth] = useState(initialMonth);
  const [selectingEnd, setSelectingEnd] = useState(Boolean(start && !end));
  const [year, month] = viewMonth.split('-').map(Number);
  const firstDay = new Date(year, month - 1, 1).getDay();
  const daysInMonth = new Date(year, month, 0).getDate();
  const cells = Array.from({ length: Math.ceil((firstDay + daysInMonth) / 7) * 7 }, (_, index) => {
    const day = index - firstDay + 1;
    return day > 0 && day <= daysInMonth ? `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}` : '';
  });
  const currentMonth = today.slice(0, 7);
  const monthLabel = new Date(year, month - 1, 1).toLocaleDateString(zh ? 'zh-CN' : 'en-US', { year: 'numeric', month: 'long' });
  const moveMonth = (offset: number) => {
    const next = new Date(year, month - 1 + offset, 1);
    setViewMonth(`${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}`);
  };
  const chooseDay = (key: string) => {
    if (!key || key > today) return;
    if (!start || (start && end) || !selectingEnd) {
      onChange(key, '');
      setSelectingEnd(true);
      return;
    }
    if (key < start) onChange(key, start);
    else onChange(start, key);
    setSelectingEnd(false);
  };
  const quickRange = (days: number) => {
    const endDate = new Date(`${today}T00:00:00`);
    const startDate = new Date(endDate);
    startDate.setDate(startDate.getDate() - days + 1);
    const startKey = `${startDate.getFullYear()}-${String(startDate.getMonth() + 1).padStart(2, '0')}-${String(startDate.getDate()).padStart(2, '0')}`;
    onChange(startKey, today);
    setViewMonth(startKey.slice(0, 7));
    setSelectingEnd(false);
  };
  const calendarWeekdayLabels = zh ? ['\u65e5', '\u4e00', '\u4e8c', '\u4e09', '\u56db', '\u4e94', '\u516d'] : ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'];
  const quickRangeLabel = (days: number) => zh ? `\u8fd1${days}\u5929` : `Last ${days}d`;
  const clearLabel = zh ? '\u6e05\u9664' : 'Clear';
  return (
    <div className="mt-3 rounded-2xl border border-black/5 bg-slate-50/80 p-3">
      <div className="flex items-center justify-between">
        <button type="button" onClick={() => moveMonth(-1)} className="rounded-lg p-1.5 text-black/45 hover:bg-white hover:text-[#0e7490]" aria-label="Previous month"><ChevronLeft size={14} /></button>
        <span className="text-xs font-bold text-[#164e63]">{monthLabel}</span>
        <button type="button" disabled={viewMonth >= currentMonth} onClick={() => moveMonth(1)} className="rounded-lg p-1.5 text-black/45 hover:bg-white hover:text-[#0e7490] disabled:cursor-default disabled:opacity-25" aria-label="Next month"><ChevronRight size={14} /></button>
      </div>
      <div className="mt-2 grid grid-cols-7 text-center text-[10px] font-semibold text-black/35">
        {calendarWeekdayLabels.map((label) => <span key={label} className="py-1">{label}</span>)}
      </div>
      <div className="grid grid-cols-7 gap-1 text-center">
        {cells.map((key, index) => {
          const disabled = !key || key > today;
          const selected = key === start || key === end;
          const inRange = Boolean(key && start && end && key > start && key < end);
          return <button key={`${key}-${index}`} type="button" disabled={disabled} onClick={() => chooseDay(key)} className={`h-7 rounded-lg text-[11px] transition ${disabled ? 'cursor-default text-black/15' : selected ? 'bg-[#0e7490] font-bold text-white shadow-sm' : inRange ? 'bg-cyan-100 text-[#164e63]' : 'text-black/60 hover:bg-white hover:text-[#0e7490]'}`}>{key ? Number(key.slice(-2)) : ''}</button>;
        })}
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5 border-t border-black/5 pt-2">
        {[7, 30, 90].map((days) => <button key={days} type="button" onClick={() => quickRange(days)} className="rounded-lg bg-white px-2 py-1 text-[10px] font-semibold text-[#0e7490] shadow-sm hover:bg-cyan-50">{quickRangeLabel(days)}</button>)}
        <button type="button" onClick={() => { onChange('', ''); setSelectingEnd(false); }} className="ml-auto rounded-lg px-2 py-1 text-[10px] font-semibold text-black/40 hover:bg-white">{clearLabel}</button>
      </div>
    </div>
  );
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
  const [pageSize, setPageSize] = useState(20);
  const [search, setSearch] = useState('');
  const [runs, setRuns] = useState<BackupRun[]>([]);
  const [historyRuns, setHistoryRuns] = useState<BackupRun[]>([]);
  const [runsTotal, setRunsTotal] = useState(0);
  const [runsPage, setRunsPage] = useState(1);
  const runsPageSize = 10;
  const [backupStartDate, setBackupStartDate] = useState('');
  const [backupEndDate, setBackupEndDate] = useState('');
  const [dateDraftStart, setDateDraftStart] = useState('');
  const [dateDraftEnd, setDateDraftEnd] = useState('');
  const [dateRangeOpen, setDateRangeOpen] = useState(false);
  const [showHistory, setShowHistory] = useState(true);
  const localToday = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  const backupDateQuery = backupStartDate && backupEndDate
    ? `${backupStartDate} ~ ${backupEndDate}`
    : backupStartDate || backupEndDate;
  const setBackupDateQuery = (value: string) => {
    setBackupStartDate(value);
    setBackupEndDate(value);
  };
  const [runsLoading, setRunsLoading] = useState(false);
  const [selectedRun, setSelectedRun] = useState<{ run: BackupRun; devices: BackupRunDevice[]; total: number; page: number; page_size: number } | null>(null);
  const [runDetailsLoading, setRunDetailsLoading] = useState(false);
  const [detailSiteFilter, setDetailSiteFilter] = useState('all');
  const [detailStatusFilter, setDetailStatusFilter] = useState<DetailStatusFilter>('all');
  const [detailSearch, setDetailSearch] = useState('');
  const [detailPage, setDetailPage] = useState(1);
  const [detailPageSize, setDetailPageSize] = useState(20);
  const [detailExpanded, setDetailExpanded] = useState(false);
  const detailRequestRef = useRef<AbortController | null>(null);

  // Remote archive modal & actions state.  The endpoint keeps its legacy
  // /tftp URL for compatibility, but the selected protocol is explicit.
  const [tftpModalOpen, setTftpModalOpen] = useState(false);
  const [tftpSettings, setTftpSettings] = useState<ArchiveSettings>({
    enabled: false,
    protocol: 'sftp',
    server_ip: '',
    server_port: 22,
    username: '',
    password: '',
    password_configured: false,
    path_prefix: 'backups',
  });
  const [tftpTesting, setTftpTesting] = useState(false);
  const [tftpTestResult, setTftpTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [tftpSaving, setTftpSaving] = useState(false);
  const [tftpSyncing, setTftpSyncing] = useState(false);
  const [tftpSyncingSnapshotId, setTftpSyncingSnapshotId] = useState<string | null>(null);

  const loadTftpSettings = useCallback(async () => {
    try {
      const token = localStorage.getItem('netops_token');
      const resp = await fetch('/api/configs/tftp/settings', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (resp.ok) {
        const res = await resp.json();
        if (res.data) {
          setTftpSettings({
            enabled: Boolean(res.data.enabled),
            protocol: (res.data.protocol === 'ftp' || res.data.protocol === 'tftp' ? res.data.protocol : 'sftp') as ArchiveProtocol,
            server_ip: res.data.server_ip || '',
            server_port: Number(res.data.server_port || archiveProtocolPort(res.data.protocol || 'sftp')),
            username: res.data.username || '',
            password: '',
            password_configured: Boolean(res.data.password_configured),
            path_prefix: res.data.path_prefix || 'backups',
          });
        }
      }
    } catch {
      // ignore
    }
  }, []);

  const handleTestTftp = async () => {
    if (!tftpSettings.server_ip.trim()) {
      showToast(zh ? '请输入文件归档服务器地址' : 'Please input archive server address', 'info');
      return;
    }
    setTftpTesting(true);
    setTftpTestResult(null);
    try {
      const token = localStorage.getItem('netops_token');
      const resp = await fetch('/api/configs/tftp/test', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          protocol: tftpSettings.protocol,
          server_ip: tftpSettings.server_ip.trim(),
          server_port: tftpSettings.server_port,
          username: tftpSettings.username.trim(),
          password: tftpSettings.password,
          path_prefix: tftpSettings.path_prefix.trim(),
        }),
      });
      const data = await resp.json();
      setTftpTestResult({
        success: Boolean(data.success),
        message: data.message || (data.success ? (zh ? '探测成功' : 'Probe succeeded') : (data.detail || (zh ? '探测失败' : 'Probe failed'))),
      });
      if (data.success) {
        showToast(zh ? `${archiveProtocolLabel(tftpSettings.protocol)} 文件服务器连通探测成功` : `${archiveProtocolLabel(tftpSettings.protocol)} probe succeeded`, 'success');
      } else {
        showToast(data.message || (zh ? '文件服务器探测失败' : 'Archive probe failed'), 'error');
      }
    } catch (err) {
      setTftpTestResult({
        success: false,
        message: String(err),
      });
      showToast(zh ? '网络请求异常' : 'Network error', 'error');
    } finally {
      setTftpTesting(false);
    }
  };

  const handleSaveTftpSettings = async () => {
    setTftpSaving(true);
    try {
      const token = localStorage.getItem('netops_token');
      const resp = await fetch('/api/configs/tftp/settings', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(tftpSettings),
      });
      if (!resp.ok) throw new Error('Failed to save');
      showToast(zh ? '文件归档默认配置已保存' : 'Archive settings saved', 'success');
    } catch {
      showToast(zh ? '保存文件归档配置失败' : 'Failed to save archive settings', 'error');
    } finally {
      setTftpSaving(false);
    }
  };

  const handleSyncLatestBatchToTftp = async () => {
    if (!latestRun) {
      showToast(zh ? '暂无可用备份批次' : 'No backup batch available', 'info');
      return;
    }
    setTftpSyncing(true);
    try {
      const token = localStorage.getItem('netops_token');
      const resp = await fetch('/api/configs/tftp/sync-batch', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          run_id: latestRun.id,
          protocol: tftpSettings.protocol,
          server_ip: tftpSettings.server_ip.trim(),
          server_port: tftpSettings.server_port,
          username: tftpSettings.username.trim(),
          password: tftpSettings.password,
          path_prefix: tftpSettings.path_prefix.trim(),
        }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || data.message || 'Sync failed');
      showToast(data.message || (zh ? '批次文件归档完成' : 'Batch archive completed'), data.success ? 'success' : 'info');
      void loadBackupRuns();
    } catch (err: any) {
      showToast(err.message || (zh ? '文件归档失败' : 'Archive sync failed'), 'error');
    } finally {
      setTftpSyncing(false);
    }
  };

  const handleSyncBatchFromModal = async (runId: string) => {
    setTftpSyncing(true);
    try {
      const token = localStorage.getItem('netops_token');
      const resp = await fetch('/api/configs/tftp/sync-batch', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          run_id: runId,
          protocol: tftpSettings.protocol,
          server_ip: tftpSettings.server_ip.trim(),
          server_port: tftpSettings.server_port,
          username: tftpSettings.username.trim(),
          password: tftpSettings.password,
          path_prefix: tftpSettings.path_prefix.trim(),
        }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || data.message || 'Sync failed');
      showToast(data.message || (zh ? '已将本批次归档' : 'Batch archived'), data.success ? 'success' : 'info');
      void loadBackupRuns();
    } catch (err: any) {
      showToast(err.message || (zh ? '文件归档失败' : 'Archive sync failed'), 'error');
    } finally {
      setTftpSyncing(false);
    }
  };

  const handleSyncSingleSnapshotToTftp = async (snapshotId: string) => {
    setTftpSyncingSnapshotId(snapshotId);
    try {
      const token = localStorage.getItem('netops_token');
      const resp = await fetch('/api/configs/tftp/sync-snapshot', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          snapshot_id: snapshotId,
          protocol: tftpSettings.protocol,
          server_ip: tftpSettings.server_ip.trim(),
          server_port: tftpSettings.server_port,
          username: tftpSettings.username.trim(),
          password: tftpSettings.password,
          path_prefix: tftpSettings.path_prefix.trim(),
        }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || data.message || 'Upload failed');
      showToast(data.message || (zh ? '已上传至文件归档服务器' : 'Uploaded to archive server'), 'success');
    } catch (err: any) {
      showToast(err.message || (zh ? '上传文件归档服务器失败' : 'Failed to upload to archive server'), 'error');
    } finally {
      setTftpSyncingSnapshotId(null);
    }
  };

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
          void loadBackupRuns();
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

  const loadBackupRuns = useCallback(async () => {
    setRunsLoading(true);
    try {
      const token = localStorage.getItem('netops_token');
      const headers = token ? { Authorization: `Bearer ${token}` } : {};
      const params = new URLSearchParams({ page: String(runsPage), page_size: String(runsPageSize) });
      if (backupStartDate) params.set('start_date', backupStartDate);
      if (backupEndDate) params.set('end_date', backupEndDate);
      const resp = await fetch(`/api/configs/backup-runs?${params.toString()}`, {
        headers,
      });
      if (!resp.ok) throw new Error('Failed');
      const data = await resp.json();
      const items = data.items || [];
      setHistoryRuns(items);
      // The overview needs enough batch metadata for the cards and Site
      // summaries. A date query is already scoped, so its result is the
      // overview as well; otherwise fetch the wider metadata window.
      if (backupStartDate || backupEndDate) {
        setRuns(items);
      } else if (runsPage === 1) {
        const overviewResp = await fetch('/api/configs/backup-runs?page=1&page_size=100', { headers });
        if (overviewResp.ok) {
          const overviewData = await overviewResp.json();
          setRuns(overviewData.items || items);
        } else {
          setRuns(items);
        }
      }
      setRunsTotal(data.total || 0);
    } catch {
      showToast(zh ? '备份批次加载失败' : 'Failed to load backup batches', 'error');
    } finally {
      setRunsLoading(false);
    }
  }, [backupStartDate, backupEndDate, runsPage, runsPageSize, zh, showToast]);

  const exportBackupRuns = async () => {
    try {
      const token = localStorage.getItem('netops_token');
      const headers = token ? { Authorization: `Bearer ${token}` } : {};
      const params = new URLSearchParams({ page: '1', page_size: '100' });
      if (backupStartDate) params.set('start_date', backupStartDate);
      if (backupEndDate) params.set('end_date', backupEndDate);
      const resp = await fetch(`/api/configs/backup-runs?${params.toString()}`, {
        headers,
      });
      if (!resp.ok) throw new Error('Failed');
      const data = await resp.json();
      const batchItems = (data.items || []) as BackupRun[];
      const details = await Promise.all(batchItems.map(async (run) => {
        try {
          const detailResp = await fetch(`/api/configs/backup-runs/${encodeURIComponent(run.id)}?site=all&status=all&page=1&page_size=100`, { headers });
          if (!detailResp.ok) return [] as BackupRunDevice[];
          const detailData = await detailResp.json();
          const devices = [...((detailData.devices || []) as BackupRunDevice[])];
          const totalDevices = Number(detailData.total || devices.length);
          for (let pageNumber = 2; pageNumber <= Math.ceil(totalDevices / 100); pageNumber += 1) {
            const pageResp = await fetch(`/api/configs/backup-runs/${encodeURIComponent(run.id)}?site=all&status=all&page=${pageNumber}&page_size=100`, { headers });
            if (!pageResp.ok) break;
            const pageData = await pageResp.json();
            devices.push(...((pageData.devices || []) as BackupRunDevice[]));
          }
          return devices;
        } catch {
          return [] as BackupRunDevice[];
        }
      }));
      const formatExportTime = (value?: string | null) => {
        if (!value) return '';
        const date = parseIsoDate(value);
        if (!date) return value;
        return date.toLocaleString(zh ? 'zh-CN' : 'en-US', {
          year: 'numeric', month: '2-digit', day: '2-digit',
          hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
        });
      };
      const statusLabel = (status: string) => {
        const normalized = String(status || '').toLowerCase();
        if (normalized === 'success') return zh ? '成功' : 'Success';
        if (normalized === 'skipped') return zh ? '跳过' : 'Skipped';
        if (normalized === 'unknown' || normalized === 'pending') return zh ? '未知' : 'Unknown';
        if (zh) return normalized === 'completed' ? '已完成' : normalized === 'partial' ? '部分成功' : normalized === 'running' ? '执行中' : normalized === 'failed' ? '失败' : (status || '未知');
        return normalized === 'completed' ? 'Completed' : normalized === 'partial' ? 'Partial' : normalized === 'running' ? 'Running' : normalized === 'failed' ? 'Failed' : (status || 'Unknown');
      };
      const parserPlatform = (platform: string) => /(?:h3c|comware)/i.test(String(platform || '')) ? 'h3c_comware' : (platform || '');
      const batchHeader = zh
        ? ['批次ID', '开始时间', '结束时间', '耗时(ms)', '触发方式', '执行人', '状态', '设备总数', '成功', '失败', '未知', '跳过', '成功率', 'Site汇总', '错误信息']
        : ['Batch ID', 'Started', 'Finished', 'Duration(ms)', 'Trigger', 'Author', 'Status', 'Total Devices', 'Success', 'Failed', 'Unknown', 'Skipped', 'Success Rate', 'Site Summary', 'Error'];
      batchHeader.pop();
      const batchRows = batchItems.map((run) => {
        const duration = run.started_at && run.finished_at
          ? Math.max(0, new Date(run.finished_at).getTime() - new Date(run.started_at).getTime())
          : '';
        const unknown = (run.site_summary || []).reduce((sum, site) => sum + Number(site.unknown || 0), 0);
        const rate = Number(run.total_devices || 0) > 0 ? `${Math.round((Number(run.success_count || 0) / Number(run.total_devices)) * 100)}%` : '0%';
        const siteSummary = (run.site_summary || []).map((site) => `${site.site}: ${zh ? `成功${site.success}/失败${site.failed}/未知${site.unknown}/跳过${site.skipped}` : `ok ${site.success}/failed ${site.failed}/unknown ${site.unknown}/skipped ${site.skipped}`}`).join('；');
        return [run.id, formatExportTime(run.started_at), formatExportTime(run.finished_at), duration, run.trigger, run.author, statusLabel(run.status), run.total_devices, run.success_count, run.failed_count, unknown, run.skipped_count, rate, siteSummary, run.error_message || ''];
      });
      const deviceHeader = zh
        ? ['批次ID', '批次开始时间', 'Site', '设备', 'IP地址', '平台', '结果', '原因', '详细说明', '耗时(ms)']
        : ['Batch ID', 'Batch Started', 'Site', 'Device', 'IP Address', 'Platform', 'Result', 'Reason', 'Detail', 'Duration(ms)'];
      deviceHeader.splice(6, 0, zh ? '解析器平台' : 'Parser Platform');
      const deviceRows = batchItems.flatMap((run, index) => details[index].map((device) => [
        run.id, formatExportTime(run.started_at), device.site || 'Unassigned', device.hostname, device.ip_address,
        device.platform, parserPlatform(device.platform), statusLabel(device.status), device.reason || '', device.detail || '', device.duration_ms ?? '',
      ]));
      const workbook = XLSX.utils.book_new();
      const summarySheet = XLSX.utils.aoa_to_sheet([batchHeader, ...batchRows.map((row) => row.slice(0, -1))]);
      const deviceSheet = XLSX.utils.aoa_to_sheet([deviceHeader, ...deviceRows]);
      summarySheet['!cols'] = [
        { wch: 34 }, { wch: 20 }, { wch: 20 }, { wch: 12 }, { wch: 12 }, { wch: 12 },
        { wch: 14 }, { wch: 12 }, { wch: 10 }, { wch: 10 }, { wch: 10 }, { wch: 10 },
        { wch: 12 }, { wch: 70 }, { wch: 35 },
      ];
      deviceSheet['!cols'] = [
        { wch: 34 }, { wch: 20 }, { wch: 18 }, { wch: 22 }, { wch: 18 }, { wch: 18 },
        { wch: 14 }, { wch: 18 }, { wch: 24 }, { wch: 54 }, { wch: 12 },
      ];
      summarySheet['!autofilter'] = { ref: `A1:${XLSX.utils.encode_col(batchHeader.length - 1)}${batchRows.length + 1}` };
      deviceSheet['!autofilter'] = { ref: `A1:${XLSX.utils.encode_col(deviceHeader.length - 1)}${deviceRows.length + 1}` };
      XLSX.utils.book_append_sheet(workbook, summarySheet, zh ? '批次汇总' : 'Batch Summary');
      XLSX.utils.book_append_sheet(workbook, deviceSheet, zh ? '设备明细' : 'Device Details');
      XLSX.writeFile(workbook, `backup-runs-${new Date().toISOString().slice(0, 10)}.xlsx`);
      return;

    } catch {
      showToast(zh ? '备份报告导出失败' : 'Failed to export backup report', 'error');
    }
  };

  const loadBackupRunDetails = async (
    runId: string,
    filters: { site?: string; status?: DetailStatusFilter; search?: string; page?: number; pageSize?: number } = {},
  ) => {
    setRunDetailsLoading(true);
    let controller: AbortController | null = null;
    try {
      detailRequestRef.current?.abort();
      controller = new AbortController();
      detailRequestRef.current = controller;
      const token = localStorage.getItem('netops_token');
      const params = new URLSearchParams({
        site: filters.site ?? detailSiteFilter,
        status: filters.status ?? detailStatusFilter,
        search: filters.search ?? detailSearch,
        page: String(filters.page ?? detailPage),
        page_size: String(filters.pageSize ?? detailPageSize),
      });
      const resp = await fetch(`/api/configs/backup-runs/${encodeURIComponent(runId)}?${params.toString()}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal: controller.signal,
      });
      if (!resp.ok) throw new Error('Failed');
      const data = await resp.json();
      setSelectedRun(data);
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return;
      showToast(zh ? '备份批次详情加载失败' : 'Failed to load backup batch details', 'error');
    } finally {
      if (detailRequestRef.current === controller) setRunDetailsLoading(false);
    }
  };

  const openBackupRunDetails = (runId: string, site = 'all', status: DetailStatusFilter = 'all') => {
    setDetailSiteFilter(site);
    setDetailStatusFilter(status);
    setDetailSearch('');
    setDetailPage(1);
    setDetailExpanded(false);
    // Show the complete first page immediately.  The Site and status summaries
    // are still calculated server-side, while the paged device result makes the
    // default "All sites / All" view useful without loading an unbounded batch.
    setDetailExpanded(true);
    void loadBackupRunDetails(runId, { site, status, search: '', page: 1, pageSize: detailPageSize });
  };

  const applyDetailFilter = (
    next: { site?: string; status?: DetailStatusFilter; search?: string; page?: number; pageSize?: number },
    options: { expand?: boolean } = {},
  ) => {
    if (!selectedRun) return;
    const site = next.site ?? detailSiteFilter;
    // Switching Site always starts from the complete Site result set. This
    // prevents a Site card opened from the attention view from carrying the
    // previous failed/unknown filter into the next Site selection.
    const status = next.status ?? (next.site != null ? 'all' : detailStatusFilter);
    const searchValue = next.search ?? detailSearch;
    const pageValue = next.page ?? 1;
    const expanded = options.expand ?? detailExpanded;
    const pageSizeValue = expanded ? (next.pageSize ?? detailPageSize) : 1;
    setDetailExpanded(expanded);
    setDetailSiteFilter(site);
    setDetailStatusFilter(status);
    setDetailSearch(searchValue);
    setDetailPage(pageValue);
    // A collapsed summary request uses page_size=1 only as a lightweight
    // metadata probe. Never let that probe change the user's detail page size.
    if (expanded && next.pageSize != null) setDetailPageSize(pageSizeValue);
    void loadBackupRunDetails(selectedRun.run.id, { site, status, search: searchValue, page: pageValue, pageSize: pageSizeValue });
  };

  const closeBackupRunDetails = () => {
    detailRequestRef.current?.abort();
    detailRequestRef.current = null;
    setSelectedRun(null);
    setDetailExpanded(false);
  };

  useEffect(() => { void loadLatestBackups(); void loadBackupRuns(); }, [loadLatestBackups, loadBackupRuns]);

  const handleBackupAllClick = async () => {
    await onBackupAllOnline();
    void loadLatestBackups();
    void loadBackupRuns();
  };

  const handleBackupDeviceClick = async (deviceId: string) => {
    setBackupingDeviceId(deviceId);
    try {
      await onBackupDevice(deviceId);
      void loadLatestBackups();
      void loadBackupRuns();
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

  const handleViewBackupDevice = async (device: BackupRunDevice) => {
    if (!device.snapshot_id) {
      showToast(zh ? '该设备没有可查看的备份内容' : 'No backup content is available for this device', 'info');
      return;
    }
    await handleView({
      id: device.snapshot_id,
      device_id: device.device_id || '',
      hostname: device.hostname,
      ip_address: device.ip_address,
      vendor: '',
      platform: device.platform,
      device_status: 'unknown',
      trigger: 'backup-run',
      timestamp: device.started_at || selectedRun?.run.started_at || '',
      size: 0,
    });
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

  // Keep every backup overlay keyboard-accessible. Escape closes the top-most
  // layer first so a device config view or delete confirmation never leaks a
  // keypress through to the batch details underneath it.
  useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (deleteTarget) {
        event.preventDefault();
        setDeleteTarget(null);
      } else if (viewSnapshot) {
        event.preventDefault();
        closeView();
      } else if (selectedRun) {
        event.preventDefault();
        closeBackupRunDetails();
      }
    };
    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [deleteTarget, selectedRun, viewSnapshot]);

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
      void loadBackupRuns();
    } catch {
      showToast(zh ? '删除失败' : 'Delete failed', 'error');
    } finally {
      setDeleting(false);
    }
  };

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

  const formatSize = (size: number) => {
    if (!size) return '--';
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
      if (hours < 24) return zh ? `${hours} 小时前` : `${hours}h ago`;
      const days = Math.floor(hours / 24);
      if (days < 30) return zh ? `${days} 天前` : `${days}d ago`;
      return zh ? `${Math.floor(days / 30)} 月前` : `${Math.floor(days / 30)}mo ago`;
    } catch { return ''; }
  };

  const latestRun = runs[0] || null;
  const latestRunTotal = Number(latestRun?.total_devices || 0);
  const latestRunSuccess = Number(latestRun?.success_count || 0);
  const latestRunFailed = Number(latestRun?.failed_count || 0);
  const latestRunSkipped = Number(latestRun?.skipped_count || 0);
  const latestRunRate = latestRunTotal > 0 ? Math.round((latestRunSuccess / latestRunTotal) * 100) : null;
  const selectedRunSiteGroups = selectedRun
    ? Object.entries(selectedRun.devices.reduce<Record<string, BackupRunDevice[]>>((groups, device) => {
      const site = device.site || 'Unassigned';
      (groups[site] ||= []).push(device);
      return groups;
    }, {})).sort(([a], [b]) => a.localeCompare(b))
    : [];
  const selectedRunSiteSummaries = selectedRun?.run.site_summary || [];
  const selectedRunSiteSummary = detailSiteFilter === 'all'
    ? null
    : selectedRunSiteSummaries.find((site) => site.site === detailSiteFilter) || null;
  const detailStatusSummary = selectedRunSiteSummary || {
    total: Number(selectedRun?.run.total_devices || 0),
    success: Number(selectedRun?.run.success_count || 0),
    failed: Number(selectedRun?.run.failed_count || 0),
    skipped: Number(selectedRun?.run.skipped_count || 0),
    unknown: selectedRunSiteSummaries.reduce((sum, site) => sum + Number(site.unknown || 0), 0),
  };
  const detailStatusCounts: Record<DetailStatusFilter, number> = {
    all: detailStatusSummary.total,
    abnormal: detailStatusSummary.failed + detailStatusSummary.unknown,
    failed: detailStatusSummary.failed,
    unknown: detailStatusSummary.unknown,
    success: detailStatusSummary.success,
    skipped: detailStatusSummary.skipped,
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHero
        icon={Database}
        eyebrow={zh ? '配置管理 / 备份中心' : 'Config / Backup Center'}
        title={zh ? '备份中心' : 'Backup Center'}
        subtitle={zh ? '按 Site、日期和备份批次查看执行情况，点击设备进入备份详情。' : 'Review backup health by Site, date, and batch; open a device backup on demand.'}
        actions={
          <>
            <button
              onClick={() => { void loadTftpSettings(); setTftpModalOpen(true); }}
              className="inline-flex h-11 items-center justify-center gap-2 rounded-2xl border border-[#d8e1eb] bg-[#f7f9fc] px-4 text-sm font-semibold text-[#0e7490] transition-all duration-200 hover:-translate-y-0.5 hover:border-[#c7d4e2] hover:bg-white hover:text-[#0891b2]"
              title={zh ? '配置文件归档服务器及同步协议' : 'Configure archive server and sync protocol'}
            >
              <UploadCloud size={15} />
              {zh ? '文件归档' : 'File Archive'}
            </button>
            <button
              onClick={() => void handleBackupAllClick()}
              disabled={isTakingSnapshot}
              className="inline-flex h-11 items-center justify-center gap-2 rounded-2xl bg-[#06b6d4] px-4 text-sm font-semibold text-white shadow-[0_12px_24px_rgba(6,182,212,0.22)] transition-all duration-200 hover:-translate-y-0.5 hover:bg-[#0891b2] disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:translate-y-0"
            >
              {isTakingSnapshot ? <RefreshCw size={14} className="animate-spin" /> : <Database size={14} />}
              {zh ? '备份全部在线设备' : 'Backup All Online'}
            </button>
            <button
              onClick={() => { void loadLatestBackups(); void loadBackupRuns(); }}
              className="inline-flex h-11 items-center justify-center gap-2 rounded-2xl border border-[#d8e1eb] bg-[#f7f9fc] px-4 text-sm font-semibold text-[#0e7490] transition-all duration-200 hover:-translate-y-0.5 hover:border-[#c7d4e2] hover:bg-white hover:text-[#0891b2]"
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              {zh ? '刷新' : 'Refresh'}
            </button>
          </>
        }
      />

      <div className="flex-1 overflow-auto px-6 py-5 space-y-4">
      <div className="flex items-center justify-between gap-3 rounded-2xl border border-black/5 bg-white px-4 py-3 shadow-[0_8px_24px_rgba(11,35,64,0.04)]">
        <div className="flex items-center gap-2 text-xs font-semibold text-[#0e7490]">
          <BarChart3 size={14} />
          {zh ? '备份概览' : 'Backup overview'}
        </div>
        <span className="text-[11px] text-black/35">
          {zh ? '按 Site、日期和批次定位备份详情' : 'Locate backup details by Site, date, and batch'}
        </span>
      </div>

      {(
        <div className="space-y-4">
          {progress && (
            <div className={`flex flex-wrap items-center justify-between gap-3 rounded-2xl border px-4 py-3 ${progress.finished && progress.failed > 0 ? 'border-amber-200 bg-amber-50/70' : progress.finished ? 'border-emerald-200 bg-emerald-50/70' : 'border-cyan-200 bg-cyan-50/70'}`}>
              <div className="flex items-center gap-2">
                {progress.finished && progress.failed === 0 ? <CheckCircle2 size={16} className="text-emerald-600" /> : progress.finished ? <AlertTriangle size={16} className="text-amber-600" /> : <RefreshCw size={16} className="animate-spin text-cyan-600" />}
                <span className="text-xs font-semibold text-[#164e63]">{progress.finished ? (zh ? '最近批次已完成' : 'Latest batch completed') : (zh ? '备份正在执行' : 'Backup in progress')}</span>
              </div>
              <span className="text-xs text-black/50">{progress.done}/{progress.total} {zh ? '设备' : 'devices'} · {progress.success} {zh ? '成功' : 'success'} · {progress.failed} {zh ? '失败' : 'failed'}</span>
            </div>
          )}
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-[0_12px_28px_rgba(11,35,64,0.05)]">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-black/35">{zh ? '最近批次' : 'LATEST BATCH'}</span>
                <CalendarDays size={16} className="text-cyan-500/50" />
              </div>
              <p className="mt-3 text-lg font-bold text-[#164e63]">{latestRun ? formatTime(latestRun.started_at) : '--'}</p>
              <p className="mt-1 text-xs text-black/40">{latestRun ? `${latestRun.trigger || '--'} · ${latestRun.author || '--'}` : (zh ? '暂无批次记录' : 'No batch recorded')}</p>
            </div>
            <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-[0_12px_28px_rgba(11,35,64,0.05)]">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-black/35">{zh ? '最近完成率' : 'LATEST COMPLETION'}</span>
                <CheckCircle2 size={16} className="text-emerald-500/50" />
              </div>
              <p className="mt-3 text-3xl font-bold text-emerald-600">{latestRunRate == null ? '--' : `${latestRunRate}%`}</p>
              <p className="mt-1 text-xs text-black/40">{latestRunSuccess} {zh ? '成功' : 'success'} / {latestRunTotal} {zh ? '台设备' : 'devices'}</p>
            </div>
            <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-[0_12px_28px_rgba(11,35,64,0.05)]">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-black/35">{zh ? '最近异常' : 'LATEST EXCEPTIONS'}</span>
                <AlertTriangle size={16} className="text-amber-500/50" />
              </div>
              <p className={`mt-3 text-3xl font-bold ${latestRunFailed > 0 ? 'text-red-500' : 'text-slate-700'}`}>{latestRunFailed}</p>
              <p className="mt-1 text-xs text-black/40">{latestRunSkipped} {zh ? '台跳过' : 'skipped'} · {zh ? '失败按设备统计' : 'failed devices'}</p>
            </div>
            <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-[0_12px_28px_rgba(11,35,64,0.05)]">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-black/35">{zh ? '历史批次' : 'RECENT BATCHES'}</span>
                <Database size={16} className="text-violet-500/50" />
              </div>
              <p className="mt-3 text-3xl font-bold text-[#164e63]">{runsTotal}</p>
              <p className="mt-1 text-xs text-black/40">{zh ? '点击下方批次查看设备结果' : 'Open a batch below for device outcomes'}</p>
            </div>
          </div>

          <div className="rounded-2xl border border-black/5 bg-white px-5 py-4 shadow-[0_12px_28px_rgba(11,35,64,0.05)]">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-black/35">{zh ? '按 Site 汇总最近批次' : 'LATEST BATCH BY SITE'}</p>
                <p className="mt-1 text-xs text-black/40">{zh ? '以 Site 作为第一层业务颗粒度，成功、失败和未知状态分别统计。' : 'Site is the primary business dimension; success, failed and unknown states stay separate.'}</p>
              </div>
              <span className="text-[11px] text-black/35">{latestRun?.site_summary?.length || 0} {zh ? '个 Site' : 'sites'}</span>
            </div>
            <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3">
              {latestRun?.site_summary && latestRun.site_summary.length > 0 ? latestRun.site_summary.map((site) => (
                <button
                  type="button"
                  key={site.site}
                  onClick={() => latestRun && openBackupRunDetails(latestRun.id, site.site, site.failed > 0 || site.unknown > 0 ? 'abnormal' : 'all')}
                  className={`w-full rounded-xl border p-4 text-left transition hover:-translate-y-0.5 hover:shadow-sm ${site.failed > 0 ? 'border-red-200 bg-red-50/60' : site.unknown > 0 ? 'border-amber-200 bg-amber-50/60' : 'border-emerald-100 bg-emerald-50/50'}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-bold text-[#164e63]">{site.site === 'Unassigned' && zh ? '未分配 Site' : site.site}</p>
                    <span className="text-[10px] font-semibold text-black/40">{site.total} {zh ? '台' : 'devices'}</span>
                  </div>
                  <div className="mt-3 flex items-center justify-between text-[10px] font-semibold">
                    <span className="text-emerald-700">{zh ? '成功率' : 'Success rate'} {site.total > 0 ? Math.round((site.success / site.total) * 100) : 0}%</span>
                    <span className={site.failed + site.unknown > 0 ? 'text-amber-700' : 'text-black/40'}>{zh ? '待处理' : 'Attention'} {site.failed + site.unknown}</span>
                  </div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-black/5" aria-label={`${site.total > 0 ? Math.round((site.success / site.total) * 100) : 0}% success rate`}>
                    <div className={`h-full rounded-full transition-all ${site.failed + site.unknown > 0 ? 'bg-amber-400' : 'bg-emerald-400'}`} style={{ width: `${site.total > 0 ? Math.round((site.success / site.total) * 100) : 0}%` }} />
                  </div>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    <span className="rounded-full bg-emerald-100 px-2 py-1 text-[10px] font-semibold text-emerald-700">{zh ? '成功' : 'Success'} {site.success}</span>
                    <span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${site.failed > 0 ? 'bg-red-100 text-red-700' : 'bg-slate-100 text-slate-500'}`}>{zh ? '失败' : 'Failed'} {site.failed}</span>
                    <span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${site.unknown > 0 ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-500'}`}>{zh ? '未知' : 'Unknown'} {site.unknown}</span>
                    {site.skipped > 0 && <span className="rounded-full bg-slate-100 px-2 py-1 text-[10px] font-semibold text-slate-600">{zh ? '跳过' : 'Skipped'} {site.skipped}</span>}
                  </div>
                  <div className="mt-3 text-[10px] font-semibold text-[#0e7490]">{site.failed > 0 || site.unknown > 0 ? (zh ? '查看异常设备 →' : 'View attention items →') : (zh ? '查看设备 →' : 'View devices →')}</div>
                </button>
              )) : <div className="col-span-full rounded-xl border border-dashed border-black/10 px-4 py-6 text-center text-xs text-black/35">{zh ? '暂无 Site 汇总数据，请先执行一次备份。' : 'No site summary yet. Run a backup to populate it.'}</div>}
            </div>
          </div>

        </div>
      )}

      {false && (
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
          <DataTable className="min-w-full text-left">
            <thead>
              <tr className="border-y border-black/5 bg-[#f8fafc] text-[11px] font-bold uppercase tracking-[0.16em] text-black/40">
                <th className="px-5 py-3">{zh ? '设备名称' : 'Device'}</th>
                <th className="px-5 py-3">IP</th>
                <th className="px-5 py-3">{zh ? '厂商' : 'Vendor'}</th>
                <th className="px-5 py-3">{zh ? '最后备份时间' : 'Last Backup'}</th>
                <th className="px-5 py-3">{zh ? '完整性 / 指纹' : 'Integrity / Hash'}</th>
                <th className="px-5 py-3">{zh ? '大小' : 'Size'}</th>
                <th className="px-5 py-3 text-right">{zh ? '操作' : 'Actions'}</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={7} className="px-5 py-12 text-center text-sm text-black/40">
                    {zh ? '正在加载...' : 'Loading...'}
                  </td>
                </tr>
              ) : rows.length > 0 ? (
                rows.map(row => (
                  <tr key={row.device_id} className="border-b border-black/5 hover:bg-black/[0.02] transition-colors">
                    <td className="px-5 py-4 align-top">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <div className={`h-2 w-2 flex-shrink-0 rounded-full ${row.device_status === 'online' ? 'bg-emerald-500' : 'bg-red-400'}`} />
                        <span className="text-sm font-semibold text-[#164e63]">{row.hostname}</span>
                        {row.config_type === 'startup' ? (
                          <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[9px] font-bold text-blue-600 border border-blue-100">
                            {zh ? '启动配置' : 'Startup'}
                          </span>
                        ) : (
                          <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[9px] font-bold text-emerald-600 border border-emerald-100">
                            {zh ? '运行配置' : 'Running'}
                          </span>
                        )}
                        {Boolean(row.has_unsaved_changes) && (
                          <span
                            className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[9px] font-bold text-amber-700 border border-amber-200"
                            title={row.unsaved_diff_summary || (zh ? '存在未保存运行配置' : 'Unsaved changes detected')}
                          >
                            <AlertTriangle size={10} />
                            {zh ? '未保存' : 'Unsaved'}
                          </span>
                        )}
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
                    <td className="px-5 py-4 align-top">
                      <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                        row.integrity_status === 'verified'
                          ? 'bg-emerald-50 text-emerald-700'
                          : 'bg-amber-50 text-amber-700'
                      }`}>
                        {row.integrity_status === 'verified'
                          ? (zh ? '已校验' : 'Verified')
                          : (zh ? '待校验' : 'Unverified')}
                      </span>
                      <div className="mt-1 max-w-[140px] truncate font-mono text-[10px] text-black/35" title={row.raw_hash || ''}>
                        {row.raw_hash ? `sha256:${row.raw_hash.slice(0, 12)}…` : 'sha256:—'}
                      </div>
                      <div className="text-[10px] text-black/30">{row.line_count || 0} {zh ? '行' : 'lines'} · {row.section_count || 0} sections</div>
                    </td>
                    <td className="px-5 py-4 align-top text-sm text-black/50 font-mono">{formatSize(row.size)}</td>
                    <td className="px-5 py-4 align-top text-right">
                      <ActionIconGroup label={zh ? '备份操作' : 'Backup actions'}>
                        <ActionIconButton
                          icon={tftpSyncingSnapshotId === row.id ? RefreshCw : UploadCloud}
                          label={zh ? '上传此配置快照至文件归档服务器' : 'Upload this snapshot to archive server'}
                          variant="accent"
                          iconClassName={tftpSyncingSnapshotId === row.id ? 'animate-spin' : undefined}
                          onClick={() => void handleSyncSingleSnapshotToTftp(row.id)}
                          disabled={tftpSyncingSnapshotId === row.id || !row.id}
                        />
                        <ActionIconButton
                          icon={backupingDeviceId === row.device_id ? RefreshCw : Database}
                          label={zh ? '备份此设备' : 'Backup this device'}
                          variant="accent"
                          iconClassName={backupingDeviceId === row.device_id ? 'animate-spin' : undefined}
                          onClick={() => void handleBackupDeviceClick(row.device_id)}
                          disabled={backupingDeviceId === row.device_id || isTakingSnapshot}
                        />
                        <ActionIconButton
                          icon={ArrowLeftRight}
                          label={zh ? '对比配置变更' : 'Compare config changes'}
                          variant="accent"
                          onClick={() => onNavigateToDiff(row.device_id)}
                        />
                        <ActionIconButton
                          icon={Eye}
                          label={zh ? '查看配置' : 'View config'}
                          variant="accent"
                          onClick={() => void handleView(row)}
                          disabled={!row.id}
                        />
                        <ActionIconButton
                          icon={Download}
                          label={zh ? '下载配置' : 'Download'}
                          variant="accent"
                          onClick={() => handleDownload(row)}
                          disabled={!row.id}
                        />
                        <ActionIconButton
                          icon={Trash2}
                          label={zh ? '删除备份' : 'Delete backup'}
                          variant="danger"
                          onClick={() => setDeleteTarget(row)}
                          disabled={!row.id}
                        />
                      </ActionIconGroup>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={7} className="px-5 py-16 text-center">
                    <div className="flex flex-col items-center gap-3 text-black/25">
                      <FileText size={36} strokeWidth={1} />
                      <p className="text-sm font-medium">{zh ? '暂无配置备份' : 'No config backups yet'}</p>
                      <p className="text-xs">{zh ? '点击上方「备份全部在线设备」开始首次备份。' : 'Click "Backup All Online" above to start.'}</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </DataTable>
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
      )}

      <div className="rounded-[28px] border border-black/5 bg-white shadow-[0_16px_36px_rgba(11,35,64,0.06)]">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-black/5 px-5 py-4">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-black/35">{zh ? '备份批次历史' : 'BACKUP BATCH HISTORY'}</p>
            <p className="mt-1 text-xs text-black/40">{backupDateQuery ? (zh ? `仅显示 ${backupDateQuery} 的批次` : `Showing batches from ${backupDateQuery}`) : (zh ? '按日期、触发方式和状态快速定位批次，点击详情查看设备结果。' : 'Filter by date, trigger, and status, then open device outcomes on demand.')}</p>
          </div>
          <div className="flex items-center gap-2">
            <div className="relative">
              <button
                type="button"
                onClick={() => { setDateDraftStart(backupStartDate); setDateDraftEnd(backupEndDate); setDateRangeOpen((open) => !open); }}
                className={`inline-flex h-9 items-center gap-2 rounded-xl border px-3 text-xs font-semibold transition ${backupStartDate || backupEndDate ? 'border-cyan-300 bg-cyan-50 text-[#0e7490]' : 'border-black/10 bg-white text-black/50 hover:bg-cyan-50'}`}
                aria-expanded={dateRangeOpen}
              >
                <CalendarDays size={13} className="text-cyan-600" />
                <span>{backupStartDate && backupEndDate ? `${backupStartDate} — ${backupEndDate}` : backupStartDate || backupEndDate || (zh ? '选择日期范围' : 'Select date range')}</span>
                <ChevronDown size={13} className={dateRangeOpen ? 'rotate-180 transition-transform' : 'transition-transform'} />
              </button>
              {dateRangeOpen && (
                <div className="absolute right-0 z-30 mt-2 w-[310px] rounded-2xl border border-black/10 bg-white p-4 shadow-[0_18px_40px_rgba(11,35,64,0.16)]">
                  <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-black/35">{zh ? '备份批次时间范围' : 'BACKUP DATE RANGE'}</p>
                  <DateRangeCalendar start={dateDraftStart} end={dateDraftEnd} today={localToday} zh={zh} onChange={(nextStart, nextEnd) => { setDateDraftStart(nextStart); setDateDraftEnd(nextEnd); setBackupStartDate(nextStart); setBackupEndDate(nextEnd); setRunsPage(1); }} />
                  <div className="hidden mt-3 grid grid-cols-2 gap-2">
                    <label className="text-[11px] font-semibold text-black/50">
                      {zh ? '开始日期' : 'Start date'}
                      <input type="date" value={dateDraftStart} onChange={(event) => { setDateDraftStart(event.target.value); setBackupStartDate(event.target.value); setRunsPage(1); }} className="mt-1 h-9 w-full rounded-xl border border-black/10 px-2.5 text-xs font-medium text-[#164e63] outline-none focus:border-cyan-400" />
                    </label>
                    <label className="text-[11px] font-semibold text-black/50">
                      {zh ? '结束日期' : 'End date'}
                      <input type="date" value={dateDraftEnd} onChange={(event) => { setDateDraftEnd(event.target.value); setBackupEndDate(event.target.value); setRunsPage(1); }} className="mt-1 h-9 w-full rounded-xl border border-black/10 px-2.5 text-xs font-medium text-[#164e63] outline-none focus:border-cyan-400" />
                    </label>
                  </div>
                  <div className="mt-3 flex items-center justify-between gap-2">
                    <span className="text-[10px] text-black/35">{zh ? '留空一侧可查询单边日期' : 'Leave one side empty for an open range'}</span>
                    <button type="button" onClick={() => { setRunsPage(1); setDateRangeOpen(false); }} className="rounded-xl bg-[#0e7490] px-3 py-2 text-[11px] font-semibold text-white hover:bg-[#155e75]">{zh ? '查询' : 'Apply'}</button>
                  </div>
                </div>
              )}
            </div>
            <label className="hidden flex h-9 items-center gap-2 rounded-xl border border-black/10 bg-white px-3 text-xs text-black/45">
              <CalendarDays size={13} className="text-cyan-600" />
              <span className="sr-only">{zh ? '按日期查询备份批次' : 'Filter backup batches by date'}</span>
              <input
                type="date"
                value={backupDateQuery}
                max={new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10)}
                onChange={(event) => { setRunsPage(1); setBackupDateQuery(event.target.value); }}
                className="bg-transparent text-xs font-semibold text-[#0e7490] outline-none"
                aria-label={zh ? '按日期查询备份批次' : 'Filter backup batches by date'}
              />
            </label>
            {backupDateQuery && (
              <button
                type="button"
                onClick={() => { setRunsPage(1); setBackupDateQuery(''); }}
                className="hidden inline-flex h-9 items-center rounded-xl border border-black/10 bg-white px-2.5 text-xs font-semibold text-black/45 hover:bg-cyan-50"
              >
                {zh ? '清除日期' : 'Clear date'}
              </button>
            )}
            <ActionButton icon={Download} variant="accent" size="sm" onClick={() => void exportBackupRuns()}>
              {zh ? '导出' : 'Export'}
            </ActionButton>
            <button
              type="button"
              onClick={() => setShowHistory((visible) => !visible)}
              className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-black/10 bg-white px-3 text-xs font-semibold text-[#0e7490] hover:bg-[#ecfeff]"
              aria-expanded={showHistory}
            >
              {showHistory ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
              {showHistory ? (zh ? '\u6536\u8d77\u5386\u53f2' : 'Collapse history') : (zh ? `\u67e5\u770b\u5386\u53f2 (${runsTotal})` : `View history (${runsTotal})`)}
            </button>
            <button
              onClick={() => void loadBackupRuns()}
              className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-black/10 bg-white px-3 text-xs font-semibold text-[#0e7490] hover:bg-[#ecfeff]"
            >
              <RefreshCw size={13} className={runsLoading ? 'animate-spin' : ''} />
              {zh ? '刷新' : 'Refresh'}
            </button>
          </div>
        </div>
        {showHistory && runsLoading && historyRuns.length === 0 ? (
          <div className="px-5 py-8 text-center text-sm text-black/35">{zh ? '加载中...' : 'Loading...'}</div>
        ) : showHistory && historyRuns.length === 0 ? (
          <div className="px-5 py-8 text-center text-sm text-black/35">{zh ? '暂无备份批次记录' : 'No backup batches recorded yet.'}</div>
        ) : showHistory ? (
          <div className="max-h-[420px] overflow-auto">
            <DataTable className="min-w-full text-left">
              <thead className="sticky top-0 z-10">
                <tr className="border-b border-black/5 bg-[#f8fafc] text-[10px] font-bold uppercase tracking-[0.14em] text-black/40">
                  <th className="px-5 py-3">{zh ? '开始时间' : 'Started'}</th>
                  <th className="px-5 py-3">{zh ? '触发方式' : 'Trigger'}</th>
                  <th className="px-5 py-3">{zh ? 'Site' : 'Sites'}</th>
                  <th className="px-5 py-3">{zh ? '结果' : 'Result'}</th>
                  <th className="px-5 py-3 text-right">{zh ? '设备数' : 'Devices'}</th>
                  <th className="px-5 py-3 text-right">{zh ? '操作' : 'Action'}</th>
                </tr>
              </thead>
              <tbody>
                {historyRuns.map((run) => {
                  const failed = Number(run.failed_count || 0);
                  const unknown = (run.site_summary || []).reduce((sum, site) => sum + Number(site.unknown || 0), 0);
                  const status = String(run.status || '').toLowerCase();
                  const statusLabel = status === 'completed' && failed === 0 && unknown === 0 ? (zh ? '成功' : 'Success') : status === 'partial' || failed > 0 || unknown > 0 ? (zh ? '需关注' : 'Attention') : status || '--';
                  return (
                    <tr key={run.id} className="border-b border-black/5 last:border-0 hover:bg-black/[0.02]">
                      <td className="px-5 py-3 text-sm text-black/60">{formatTime(run.started_at)}</td>
                      <td className="px-5 py-3 text-xs font-semibold text-black/55">
                        <div>{run.trigger || '--'}</div>
                        <div className="mt-0.5 text-[10px] font-normal text-black/35">{run.author || '--'}</div>
                      </td>
                      <td className="px-5 py-3 text-xs text-black/50">
                        <div className="flex max-w-[280px] flex-wrap gap-1">
                          {(run.site_summary || []).slice(0, 3).map((site) => {
                            const siteAttention = Number(site.failed || 0) + Number(site.unknown || 0);
                            return (
                              <span
                                key={site.site}
                                title={`${site.site}: ${site.success} success, ${site.failed} failed, ${site.unknown} unknown`}
                                className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${siteAttention > 0 ? 'bg-red-50 text-red-700' : 'bg-emerald-50 text-emerald-700'}`}
                              >
                                {site.site} · {siteAttention > 0 ? `${zh ? '异常' : 'attention'} ${siteAttention}` : `${zh ? '成功' : 'ok'} ${site.success}`}
                              </span>
                            );
                          })}
                          {(run.site_summary?.length || 0) > 3 && (
                            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-500">
                              +{(run.site_summary?.length || 0) - 3} {zh ? '个 Site' : 'sites'}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-5 py-3">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${failed > 0 || unknown > 0 ? 'bg-amber-50 text-amber-700' : 'bg-emerald-50 text-emerald-700'}`}>
                            {failed > 0 || unknown > 0 ? <AlertTriangle size={11} /> : <CheckCircle2 size={11} />}
                            {statusLabel}
                          </span>
                          <span className="text-[10px] text-black/35">{run.success_count || 0} ✓ / {failed} ! / {unknown} ? / {run.skipped_count || 0} {zh ? '跳过' : 'skipped'}</span>
                        </div>
                      </td>
                      <td className="px-5 py-3 text-right text-xs font-mono text-black/50">{run.total_devices || 0}</td>
                      <td className="px-5 py-3 text-right">
                        <button
                          onClick={() => openBackupRunDetails(run.id)}
                          className="inline-flex h-8 items-center gap-1 rounded-lg border border-black/10 bg-white px-2.5 text-[11px] font-semibold text-[#0e7490] hover:bg-[#ecfeff]"
                        >
                          <Eye size={12} />
                          {zh ? '详情' : 'Details'}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </DataTable>
            <Pagination
              currentPage={runsPage}
              totalItems={runsTotal}
              itemsPerPage={runsPageSize}
              onPageChange={setRunsPage}
              language={language}
            />
          </div>
        ) : null}
      </div>

      <AnimatePresence>
        {selectedRun && (
          <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 p-4"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onMouseDown={(event) => { if (event.target === event.currentTarget) closeBackupRunDetails(); }}
          >
            <motion.div
              className="flex max-h-[88vh] w-full max-w-5xl flex-col overflow-hidden rounded-3xl bg-white shadow-2xl"
              initial={{ y: 18, opacity: 0, scale: 0.98 }}
              animate={{ y: 0, opacity: 1, scale: 1 }}
              exit={{ y: 18, opacity: 0, scale: 0.98 }}
            >
              <div className="flex items-start justify-between gap-4 border-b border-black/5 px-6 py-5">
                <div>
                  <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-black/35">{zh ? '备份批次详情' : 'BACKUP BATCH DETAILS'}</p>
                  <h3 className="mt-1 text-lg font-semibold text-[#164e63]">{formatTime(selectedRun.run.started_at)}</h3>
                  <p className="mt-1 text-xs text-black/45">
                    {selectedRun.run.trigger || '--'} · {selectedRun.run.author || '--'} · {selectedRun.run.success_count || 0} {zh ? '成功' : 'success'} / {selectedRun.run.failed_count || 0} {zh ? '失败' : 'failed'} / {selectedRun.run.skipped_count || 0} {zh ? '跳过' : 'skipped'}
                  </p>
                  {selectedRun.run.tftp_status && selectedRun.run.tftp_status !== 'none' && (
                    <div className="mt-1.5 flex items-center gap-2">
                      <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[10px] font-bold ${
                        selectedRun.run.tftp_status === 'success'
                          ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                          : 'bg-amber-50 text-amber-700 border border-amber-200'
                      }`} title={selectedRun.run.tftp_log || ''}>
                        文件归档: {selectedRun.run.tftp_status === 'success' ? (zh ? '已完成' : 'Completed') : (zh ? '部分/失败' : 'Failed')} ({selectedRun.run.tftp_uploaded_count || 0} {zh ? '个文件' : 'files'}) → {selectedRun.run.tftp_server}
                      </span>
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => void handleSyncBatchFromModal(selectedRun.run.id)}
                    disabled={tftpSyncing}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-[#0e7490]/30 bg-[#ecfeff] px-3 py-1.5 text-xs font-semibold text-[#0e7490] transition-all hover:bg-[#cffafe] hover:border-[#0e7490] disabled:opacity-50"
                    title={zh ? '将该批次所有快照及汇总日志推送到文件归档服务器' : 'Offload all snapshots and summary in this batch to archive server'}
                  >
                    {tftpSyncing ? <RefreshCw size={13} className="animate-spin" /> : <UploadCloud size={13} />}
                    {zh ? '归档本批次' : 'Archive Batch'}
                  </button>
                  <button title={zh ? '关闭' : 'Close'} onClick={closeBackupRunDetails} className="rounded-xl border border-black/10 p-2 text-black/55 hover:bg-black/[0.03]">
                    <X size={16} />
                  </button>
                </div>
              </div>
              <div className="flex-1 overflow-auto p-5">
                <div className="mb-5 rounded-2xl border border-black/5 bg-[#f8fafc] p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="mr-1 text-[10px] font-bold uppercase tracking-[0.14em] text-black/35">{zh ? 'Site' : 'Site'}</span>
                    <button type="button" onClick={() => applyDetailFilter({ site: 'all' }, { expand: true })} className={`rounded-full px-3 py-1.5 text-[11px] font-semibold ${detailSiteFilter === 'all' ? 'bg-[#0e7490] text-white' : 'bg-white text-black/50 hover:bg-cyan-50'}`}>{zh ? '全部 Site' : 'All sites'}</button>
                    {selectedRunSiteSummaries.map((site) => (
                      <button type="button" key={site.site} onClick={() => applyDetailFilter({ site: site.site }, { expand: true })} className={`rounded-full px-3 py-1.5 text-[11px] font-semibold ${detailSiteFilter === site.site ? 'bg-[#0e7490] text-white' : 'bg-white text-black/50 hover:bg-cyan-50'}`}>
                        {site.site === 'Unassigned' && zh ? '未分配 Site' : site.site} <span className="ml-1 opacity-70">{site.total}</span>
                      </button>
                    ))}
                    {selectedRunSiteSummary && (
                      <div className="ml-auto flex items-center gap-1.5 text-[10px]">
                        <span className="rounded-full bg-emerald-100 px-2 py-1 font-semibold text-emerald-700">{zh ? '成功' : 'Success'} {selectedRunSiteSummary.success}</span>
                        <span className={`rounded-full px-2 py-1 font-semibold ${selectedRunSiteSummary.failed > 0 ? 'bg-red-100 text-red-700' : 'bg-slate-100 text-slate-500'}`}>{zh ? '失败' : 'Failed'} {selectedRunSiteSummary.failed}</span>
                        <span className={`rounded-full px-2 py-1 font-semibold ${selectedRunSiteSummary.unknown > 0 ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-500'}`}>{zh ? '未知' : 'Unknown'} {selectedRunSiteSummary.unknown}</span>
                      </div>
                    )}
                  </div>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <span className="mr-1 text-[10px] font-bold uppercase tracking-[0.14em] text-black/35">{zh ? '状态' : 'Status'}</span>
                    {(['all', 'failed', 'unknown', 'success', 'skipped'] as DetailStatusFilter[]).map((status) => (
                      <button type="button" key={status} onClick={() => applyDetailFilter({ status, page: 1 }, { expand: true })} className={`rounded-full px-3 py-1.5 text-[11px] font-semibold ${detailStatusFilter === status ? 'bg-[#164e63] text-white' : 'bg-white text-black/50 hover:bg-cyan-50'}`}>
                        {status === 'all' ? (zh ? '全部' : 'All') : status === 'abnormal' ? (zh ? '异常' : 'Attention') : status === 'failed' ? (zh ? '失败' : 'Failed') : status === 'unknown' ? (zh ? '未知' : 'Unknown') : status === 'success' ? (zh ? '成功' : 'Success') : (zh ? '跳过' : 'Skipped')} {detailStatusCounts[status]}
                      </button>
                    ))}
                    <span className="rounded-full bg-amber-50 px-3 py-1.5 text-[10px] font-semibold text-amber-700" title={zh ? '需关注 = 失败 + 未知，不是额外的设备状态' : 'Attention = Failed + Unknown; it is not a separate device state'}>
                      {zh ? '需关注' : 'Attention'} {detailStatusCounts.abnormal} ({zh ? `失败${detailStatusCounts.failed} + 未知${detailStatusCounts.unknown}` : `failed ${detailStatusCounts.failed} + unknown ${detailStatusCounts.unknown}`})
                    </span>
                    <div className="ml-auto flex min-w-[240px] flex-1 items-center gap-2 sm:max-w-[360px]">
                      <div className="flex flex-1 items-center gap-2 rounded-xl border border-black/10 bg-white px-3 py-2">
                        <Search size={14} className="text-black/30" />
                        <input
                          value={detailSearch}
                          onChange={(event) => setDetailSearch(event.target.value)}
                          onKeyDown={(event) => { if (event.key === 'Enter') applyDetailFilter({ search: detailSearch }); }}
                          placeholder={zh ? '设备名称或 IP' : 'Device name or IP'}
                          className="min-w-0 flex-1 bg-transparent text-xs outline-none placeholder:text-black/30"
                        />
                      </div>
                      <button type="button" onClick={() => applyDetailFilter({ search: detailSearch, page: 1 }, { expand: true })} className="rounded-xl bg-[#0e7490] px-3 py-2 text-xs font-semibold text-white hover:bg-[#155e75]">{zh ? '定位' : 'Find'}</button>
                      <button type="button" onClick={() => applyDetailFilter({ site: 'all', status: 'all', search: '', page: 1 }, { expand: false })} className="rounded-xl border border-black/10 bg-white px-3 py-2 text-xs font-semibold text-black/50 hover:bg-cyan-50">{zh ? '重置' : 'Reset'}</button>
                    </div>
                  </div>
                  <div className="mt-3 flex items-center justify-between text-[10px] text-black/35">
                    <span>{detailExpanded ? (zh ? `当前显示 ${selectedRun?.devices.length || 0} 台，共 ${selectedRun?.total || 0} 台` : `${selectedRun?.devices.length || 0} shown of ${selectedRun?.total || 0}`) : (zh ? '设备明细已收起，可点击 Site 或状态重新加载' : 'Device details are collapsed; choose a Site or status to load them again')}</span>
                    <span>{detailExpanded ? (zh ? `每页 ${detailPageSize} 台，避免一次加载全部设备` : `${detailPageSize} devices per page to keep large batches responsive`) : (zh ? '批次统计仍保留，设备列表按需分页加载' : 'Batch counts remain available; device rows load on demand with pagination')}</span>
                  </div>
                </div>
                {runDetailsLoading ? (
                  <div className="flex items-center justify-center py-12 text-sm text-black/35"><RefreshCw size={16} className="mr-2 animate-spin" />{zh ? '加载中...' : 'Loading...'}</div>
                ) : !detailExpanded ? (
                  <div className="rounded-2xl border border-dashed border-cyan-200 bg-cyan-50/40 px-5 py-12 text-center">
                    <p className="text-sm font-semibold text-[#164e63]">{zh ? '设备明细已收起' : 'Device details are collapsed'}</p>
                    <p className="mt-1 text-xs text-black/40">{zh ? '请选择 Site 或状态即可按页显示设备，避免数量过多导致页面变长。' : 'Choose a Site or status to show devices with pagination and keep large batches responsive.'}</p>
                  </div>
                ) : selectedRun.devices.length === 0 ? (
                  <div className="py-12 text-center text-sm text-black/35">{selectedRun.total === 0 ? (zh ? '没有匹配的设备，请调整 Site、状态或搜索条件。' : 'No devices match the current Site, status, or search filters.') : (zh ? '暂无设备结果' : 'No device outcomes recorded.')}</div>
                ) : (
                  <>
                    {false && detailSiteFilter === 'all' && <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-3">
                      {selectedRunSiteSummaries.map((site) => {
                        return (
                          <div key={site.site} className={`rounded-xl border p-4 ${site.failed > 0 ? 'border-red-200 bg-red-50/60' : site.unknown > 0 ? 'border-amber-200 bg-amber-50/60' : 'border-emerald-100 bg-emerald-50/50'}`}>
                            <div className="flex items-center justify-between gap-2">
                              <p className="text-sm font-bold text-[#164e63]">{site.site === 'Unassigned' && zh ? '未分配 Site' : site.site}</p>
                              <span className="text-[10px] font-semibold text-black/40">{site.total} {zh ? '台设备' : 'devices'}</span>
                            </div>
                            <div className="mt-3 flex flex-wrap gap-1.5">
                              <span className="rounded-full bg-emerald-100 px-2 py-1 text-[10px] font-semibold text-emerald-700">{zh ? '成功' : 'Success'} {site.success}</span>
                              <span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${site.failed > 0 ? 'bg-red-100 text-red-700' : 'bg-slate-100 text-slate-500'}`}>{zh ? '失败' : 'Failed'} {site.failed}</span>
                              <span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${site.unknown > 0 ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-500'}`}>{zh ? '未知' : 'Unknown'} {site.unknown}</span>
                              {site.skipped > 0 && <span className="rounded-full bg-slate-100 px-2 py-1 text-[10px] font-semibold text-slate-600">{zh ? '跳过' : 'Skipped'} {site.skipped}</span>}
                            </div>
                          </div>
                        );
                      })}
                    </div>}
                    <div className="overflow-x-auto rounded-2xl border border-black/5">
                    <DataTable className="min-w-full text-left">
                      <thead>
                        <tr className="border-b border-black/5 bg-[#f8fafc] text-[10px] font-bold uppercase tracking-[0.14em] text-black/40">
                          <th className="px-4 py-3">{zh ? '设备' : 'Device'}</th>
                          <th className="px-4 py-3">IP</th>
                          <th className="px-4 py-3">{zh ? '结果' : 'Result'}</th>
                          <th className="px-4 py-3">{zh ? '原因/说明' : 'Reason / Detail'}</th>
                          <th className="px-4 py-3 text-right">{zh ? '耗时' : 'Duration'}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selectedRunSiteGroups.map(([site, devices]) => (
                          <React.Fragment key={site}>
                            {detailSiteFilter === 'all' && <tr className="border-b border-black/5 bg-slate-50/80">
                              <td colSpan={5} className="px-4 py-2.5">
                                <div className="flex flex-wrap items-center gap-2">
                                  <span className="text-xs font-bold text-[#164e63]">{site === 'Unassigned' && zh ? '未分配 Site' : site}</span>
                                  <span className="text-[10px] text-black/40">{devices.length} {zh ? '台设备' : 'devices'}</span>
                                </div>
                              </td>
                            </tr>}
                            {devices.map((device) => {
                           const ok = device.status === 'success';
                           const failed = device.status === 'failed';
                           const skipped = device.status === 'skipped';
                           const unknown = !ok && !failed && !skipped;
                          return (
                            <tr key={device.id} onClick={() => void handleViewBackupDevice(device)} className="cursor-pointer border-b border-black/5 last:border-0 hover:bg-cyan-50/40">
                              <td className="px-4 py-3">
                                <button type="button" onClick={(event) => { event.stopPropagation(); void handleViewBackupDevice(device); }} className="text-left text-sm font-semibold text-[#0e7490] hover:underline">
                                  {device.hostname || '--'}
                                </button>
                                <div className="mt-0.5 text-[10px] text-black/35">{device.platform || '--'}</div>
                              </td>
                              <td className="px-4 py-3 text-xs font-mono text-black/50">{device.ip_address || '--'}</td>
                              <td className="px-4 py-3">
                                <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${ok ? 'bg-emerald-50 text-emerald-700' : failed ? 'bg-red-50 text-red-700' : unknown ? 'bg-amber-50 text-amber-700' : 'bg-slate-100 text-slate-600'}`}>
                                  {ok ? <CheckCircle2 size={11} /> : <AlertTriangle size={11} />}
                                  {ok ? (zh ? '成功' : 'Success') : failed ? (zh ? '失败' : 'Failed') : skipped ? (zh ? '跳过' : 'Skipped') : (zh ? '未知' : 'Unknown')}
                                </span>
                              </td>
                              <td className="max-w-[420px] px-4 py-3">
                                <div className="text-xs font-semibold text-black/75">{device.reason || '--'}</div>
                                {device.detail && (
                                  <div className="mt-0.5 text-[11px] leading-relaxed text-black/45 break-words" title={device.detail}>
                                    {device.detail}
                                  </div>
                                )}
                              </td>
                              <td className="px-4 py-3 text-right text-xs font-mono text-black/45">{device.duration_ms != null ? `${device.duration_ms} ms` : '--'}</td>
                            </tr>
                          );
                            })}
                          </React.Fragment>
                        ))}
                      </tbody>
                    </DataTable>
                  </div>
                  <Pagination
                    currentPage={selectedRun.page}
                    totalItems={selectedRun.total}
                    itemsPerPage={selectedRun.page_size}
                    onItemsPerPageChange={(size) => applyDetailFilter({ page: 1, pageSize: size })}
                    onPageChange={(nextPage) => applyDetailFilter({ page: nextPage })}
                    language={language}
                  />
                  </>
                )}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

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
                  <ActionIconButton icon={Copy} label={zh ? '复制' : 'Copy'} variant="accent" disabled={!viewContent} onClick={() => void handleCopy()} />
                  <ActionIconButton icon={Download} label={zh ? '下载' : 'Download'} variant="accent" onClick={() => handleDownload(viewSnapshot)} />
                  <ActionIconButton icon={X} label={zh ? '关闭' : 'Close'} onClick={closeView} />
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
      {/* Remote archive settings & sync modal */}
      <AnimatePresence>
        {tftpModalOpen && (
          <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setTftpModalOpen(false)}
          >
            <motion.div
              className="flex w-full max-w-lg flex-col overflow-hidden rounded-3xl bg-white shadow-2xl border border-black/5"
              onClick={(e) => e.stopPropagation()}
              initial={{ scale: 0.96, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.96, opacity: 0 }}
            >
              <div className="flex items-center justify-between border-b border-black/5 px-6 py-4 bg-slate-50/50">
                <div className="flex items-center gap-2.5">
                  <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-cyan-100/70 text-[#0891b2]">
                    <UploadCloud size={18} />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-[#164e63]">{zh ? '文件远端归档与同步' : 'Remote File Archive & Synchronization'}</h3>
                    <p className="text-[11px] text-black/40">{zh ? 'SFTP 主用，FTP 兼容，TFTP 仅作为老设备/实验环境兜底' : 'SFTP primary, FTP compatible, TFTP fallback for legacy or lab environments'}</p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setTftpModalOpen(false)}
                  className="rounded-xl border border-black/10 p-1.5 text-black/45 hover:bg-black/5"
                >
                  <X size={16} />
                </button>
              </div>

              <div className="p-6 space-y-4">
                <div className="grid grid-cols-4 gap-3">
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-slate-700">{zh ? '传输协议' : 'Protocol'}</label>
                    <select
                      value={tftpSettings.protocol}
                      onChange={(e) => {
                        const protocol = e.target.value as ArchiveProtocol;
                        setTftpSettings({ ...tftpSettings, protocol, server_port: archiveProtocolPort(protocol) });
                      }}
                      className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-800 focus:border-[#0891b2] focus:outline-none"
                    >
                      <option value="sftp">SFTP（推荐）</option>
                      <option value="ftp">FTP（兼容）</option>
                      <option value="tftp">TFTP（兜底）</option>
                    </select>
                  </div>
                  <div className="col-span-2 space-y-1.5">
                    <label className="text-xs font-semibold text-slate-700">{zh ? '文件服务器 IP / 主机名' : 'Archive Server IP / Host'}</label>
                    <input
                      type="text"
                      placeholder="192.168.1.100"
                      value={tftpSettings.server_ip}
                      onChange={(e) => setTftpSettings({ ...tftpSettings, server_ip: e.target.value })}
                      className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-800 focus:border-[#0891b2] focus:outline-none"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-slate-700">{zh ? '端口' : 'Port'}</label>
                    <input
                      type="number"
                      placeholder={String(archiveProtocolPort(tftpSettings.protocol))}
                      value={tftpSettings.server_port}
                      onChange={(e) => setTftpSettings({ ...tftpSettings, server_port: parseInt(e.target.value, 10) || archiveProtocolPort(tftpSettings.protocol) })}
                      className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-800 focus:border-[#0891b2] focus:outline-none"
                    />
                  </div>
                </div>

                {tftpSettings.protocol !== 'tftp' && (
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <label className="text-xs font-semibold text-slate-700">{zh ? '用户名' : 'Username'}</label>
                      <input
                        type="text"
                        value={tftpSettings.username}
                        onChange={(e) => setTftpSettings({ ...tftpSettings, username: e.target.value })}
                        className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-800 focus:border-[#0891b2] focus:outline-none"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <label className="text-xs font-semibold text-slate-700">{zh ? '密码' : 'Password'}</label>
                      <input
                        type="password"
                        placeholder={tftpSettings.password_configured ? (zh ? '已配置，留空保持不变' : 'Configured; leave blank to keep') : ''}
                        value={tftpSettings.password}
                        onChange={(e) => setTftpSettings({ ...tftpSettings, password: e.target.value })}
                        className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-800 focus:border-[#0891b2] focus:outline-none"
                      />
                    </div>
                  </div>
                )}

                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-slate-700">{zh ? '远端目录 / 路径前缀' : 'Remote Directory / Prefix'}</label>
                  <input
                    type="text"
                    placeholder="backups"
                    value={tftpSettings.path_prefix}
                    onChange={(e) => setTftpSettings({ ...tftpSettings, path_prefix: e.target.value })}
                    className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-800 focus:border-[#0891b2] focus:outline-none"
                  />
                  <p className="text-[10px] text-slate-400">{zh ? `本批次文件将压缩为一个 ZIP 后上传至 ${archiveProtocolLabel(tftpSettings.protocol)} 服务器的该前缀路径中（如 backups/config_backup_YYYYMMDD_HHMMSS.zip）` : `Each backup batch is compressed into one time-stamped ZIP archive under the ${archiveProtocolLabel(tftpSettings.protocol)} remote prefix`}</p>
                </div>

                {tftpTestResult && (
                  <div className={`rounded-xl border p-3 text-xs ${tftpTestResult.success ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-red-200 bg-red-50 text-red-800'}`}>
                    <div className="flex items-center gap-1.5 font-bold">
                      {tftpTestResult.success ? <CheckCircle2 size={14} className="text-emerald-600" /> : <AlertTriangle size={14} className="text-red-600" />}
                      {tftpTestResult.success ? (zh ? '探测成功' : 'Connection Successful') : (zh ? '探测失败' : 'Connection Failed')}
                    </div>
                    <p className="mt-1 text-[11px] opacity-90">{tftpTestResult.message}</p>
                  </div>
                )}

                <div className="flex items-center justify-between pt-2 border-t border-slate-100">
                  <button
                    type="button"
                    onClick={() => void handleTestTftp()}
                    disabled={tftpTesting}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
                  >
                    {tftpTesting ? <RefreshCw size={13} className="animate-spin" /> : <Server size={13} />}
                    {zh ? '测试连通性' : 'Test Connection'}
                  </button>

                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => void handleSaveTftpSettings()}
                      disabled={tftpSaving}
                      className="inline-flex items-center gap-1.5 rounded-xl border border-cyan-200 bg-cyan-50 px-3.5 py-2 text-xs font-semibold text-[#0891b2] transition hover:bg-cyan-100 disabled:opacity-50"
                    >
                      {tftpSaving ? <RefreshCw size={13} className="animate-spin" /> : <Check size={13} />}
                      {zh ? '保存默认配置' : 'Save Default'}
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleSyncLatestBatchToTftp()}
                      disabled={tftpSyncing || !latestRun}
                      className="inline-flex items-center gap-1.5 rounded-xl bg-[#0891b2] px-4 py-2 text-xs font-bold text-white shadow-sm transition hover:bg-[#0e7490] disabled:opacity-40"
                    >
                      {tftpSyncing ? <RefreshCw size={13} className="animate-spin" /> : <UploadCloud size={13} />}
                      {zh ? '归档最新批次' : 'Archive Latest Batch'}
                    </button>
                  </div>
                </div>
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
