import React, { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  Database, RotateCcw, Calendar, CalendarClock, Server, ChevronDown, Play, Info, Zap,
  Activity, Timer, TrendingUp, BarChart3, AlertTriangle, RefreshCw,
  Shield, GitCompareArrows, Hash, Eye, HardDrive, CheckCircle2, XCircle,
} from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import type { ConfigSnapshot, Device } from '../types';
import Pagination from '../components/Pagination';
import PageHero from '../components/PageHero';
import { DataTable } from '../components/DataTable';
import BackupPolicyManager from './ConfigSchedule/BackupPolicyManager';

/* ═══════════════════════════════════════════════════════ */
/*  Constants                                              */
/* ═══════════════════════════════════════════════════════ */

const CRON_PRESETS = [
  { label: '每天 02:00', labelEn: 'Daily at 02:00', cron: '0 2 * * *' },
  { label: '每天 06:00', labelEn: 'Daily at 06:00', cron: '0 6 * * *' },
  { label: '每天 22:00', labelEn: 'Daily at 22:00', cron: '0 22 * * *' },
  { label: '每12小时', labelEn: 'Every 12 hours', cron: '0 */12 * * *' },
  { label: '每6小时', labelEn: 'Every 6 hours', cron: '0 */6 * * *' },
  { label: '每小时', labelEn: 'Every hour', cron: '0 * * * *' },
  { label: '工作日 08:00', labelEn: 'Weekdays at 08:00', cron: '0 8 * * 1-5' },
  { label: '每周一 03:00', labelEn: 'Mon at 03:00', cron: '0 3 * * 1' },
  { label: '每月1日 02:00', labelEn: '1st of month at 02:00', cron: '0 2 1 * *' },
];

const CRON_FIELD_LABELS_ZH = ['分钟', '小时', '日', '月', '星期'];
const CRON_FIELD_LABELS_EN = ['Minute', 'Hour', 'Day', 'Month', 'Weekday'];
const CRON_FIELD_HINTS_ZH = ['0-59, */5, 0,30', '0-23, */2, 0-6', '1-31, */2', '1-12, */3', '0-6, 1-5'];
const CRON_FIELD_HINTS_EN = ['0-59, */5, 0,30', '0-23, */2, 0-6', '1-31, */2', '1-12, */3', '0-6 (Sun=0), 1-5'];
const WEEKDAY_ZH = ['日', '一', '二', '三', '四', '五', '六'];
const WEEKDAY_EN = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

/* ═══════════════════════════════════════════════════════ */
/*  Types                                                  */
/* ═══════════════════════════════════════════════════════ */

type CronFreq = 'hourly' | 'daily' | 'weekly' | 'monthly';
interface SimpleForm { freq: CronFreq; hour: number; minute: number; weekday: number; monthday: number; interval: number }

interface UpcomingDevice { id: string; hostname: string; ip_address: string; platform: string; status: string }
interface PreviewData { enabled: boolean; cron: string; upcoming: string[]; devices: UpcomingDevice[]; device_count: number }

interface DeviceStat {
  id: string; hostname: string; ip_address: string; platform: string; status: string;
  backup_count: number; latest_backup: string | null; last_trigger: string | null;
}
interface RecentBackup {
  id: string; device_id: string; hostname: string; vendor: string;
  timestamp: string; trigger: string; author: string; tag: string; size: number;
}
interface BackupStats {
  today: { total: number; scheduled: number; manual: number; success?: number; failed?: number; skipped?: number; unobserved?: number };
  daily_history: { date: string; scheduled: number; manual: number; total: number }[];
  total_snapshots: number; total_devices_backed: number;
  storage_bytes?: number;
  device_stats: DeviceStat[]; recent_backups: RecentBackup[];
}

interface ConfigScheduleTabProps {
  t: (key: string) => string;
  language: string;
  devices: Device[];
  configSnapshots: ConfigSnapshot[];
  isTakingSnapshot: boolean;
  scheduleEnabled: boolean;
  scheduleCron: string;
  scheduleLoading: boolean;
  retentionDays: number;
  retentionMaxPerDevice: number;
  getVendorFromPlatform: (platform?: string) => string;
  onToggleScheduleEnabled: () => void;
  onCronChange: (value: string) => void;
  onRetentionDaysChange: (value: number) => void;
  onRetentionMaxPerDeviceChange: (value: number) => void;
  onSaveSchedule: () => Promise<void> | void;
  onRunBackupNow: () => Promise<void> | void;
  showToast: (msg: string, type?: 'success' | 'error' | 'info') => void;
}

/* ═══════════════════════════════════════════════════════ */
/*  Helpers                                                */
/* ═══════════════════════════════════════════════════════ */

const describeCron = (cron: string, zh: boolean): string => {
  const parts = cron.trim().split(/\s+/);
  if (parts.length < 5) return cron;
  const [min, hour, day, month, dow] = parts;
  const weekDaysZh = ['日', '一', '二', '三', '四', '五', '六'];
  const weekDaysEn = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const fmtTime = (h: string, m: string) => `${h.padStart(2, '0')}:${m.padStart(2, '0')}`;
  if (min.startsWith('*/') && hour === '*') return zh ? `每 ${min.slice(2)} 分钟` : `Every ${min.slice(2)} minutes`;
  if (hour === '*' && !min.includes('/') && day === '*' && month === '*') return zh ? `每小时第 ${min} 分钟` : `Hourly at :${min.padStart(2, '0')}`;
  if (hour.startsWith('*/') && day === '*' && month === '*' && dow === '*') return zh ? `每 ${hour.slice(2)} 小时的第 ${min} 分钟` : `Every ${hour.slice(2)}h at :${min.padStart(2, '0')}`;
  const timeList = (hour.includes(',') ? hour.split(',') : [hour]).map(h => fmtTime(h, min));
  const timeStr = timeList.join(zh ? '、' : ', ');
  if (day === '*' && month === '*' && dow !== '*') {
    if (dow === '1-5') return zh ? `工作日 ${timeStr}` : `Weekdays at ${timeStr}`;
    const days = dow.split(',').map(d => { const n = parseInt(d, 10); return isNaN(n) ? d : (zh ? `周${weekDaysZh[n % 7]}` : weekDaysEn[n % 7]); });
    return zh ? `${days.join('、')} ${timeStr}` : `${days.join(', ')} at ${timeStr}`;
  }
  if (day === '*' && month === '*' && dow === '*') return zh ? `每天 ${timeStr}` : `Daily at ${timeStr}`;
  if (day !== '*' && month === '*') return zh ? `每月 ${day} 日 ${timeStr}` : `Monthly on ${day} at ${timeStr}`;
  return cron;
};

const parseSimpleCron = (cron: string): SimpleForm | null => {
  const p = cron.trim().split(/\s+/);
  if (p.length !== 5) return null;
  const [min, hour, day, month, dow] = p;
  if (/^\d+$/.test(min) && /^\*\/\d+$/.test(hour) && day === '*' && month === '*' && dow === '*')
    return { freq: 'hourly', hour: 0, minute: parseInt(min), weekday: 1, monthday: 1, interval: parseInt(hour.slice(2)) };
  if (/^\d+$/.test(min) && /^\d+$/.test(hour) && day === '*' && month === '*' && /^\d$/.test(dow))
    return { freq: 'weekly', hour: parseInt(hour), minute: parseInt(min), weekday: parseInt(dow), monthday: 1, interval: 6 };
  if (/^\d+$/.test(min) && /^\d+$/.test(hour) && /^\d+$/.test(day) && month === '*' && dow === '*')
    return { freq: 'monthly', hour: parseInt(hour), minute: parseInt(min), weekday: 1, monthday: parseInt(day), interval: 6 };
  if (/^\d+$/.test(min) && /^\d+$/.test(hour) && day === '*' && month === '*' && dow === '*')
    return { freq: 'daily', hour: parseInt(hour), minute: parseInt(min), weekday: 1, monthday: 1, interval: 6 };
  return null;
};

const buildSimpleCron = (f: SimpleForm): string => {
  switch (f.freq) {
    case 'hourly': return `0 */${f.interval} * * *`;
    case 'daily': return `${f.minute} ${f.hour} * * *`;
    case 'weekly': return `${f.minute} ${f.hour} * * ${f.weekday}`;
    case 'monthly': return `${f.minute} ${f.hour} ${f.monthday} * *`;
  }
};

const fmtSize = (bytes: number | null): string => {
  if (!bytes) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
};

/* ═══════════════════════════════════════════════════════ */
/*  Component                                              */
/* ═══════════════════════════════════════════════════════ */

const ConfigScheduleTab: React.FC<ConfigScheduleTabProps> = ({
  t, language, devices, configSnapshots, isTakingSnapshot,
  scheduleEnabled, scheduleCron, scheduleLoading, retentionDays, retentionMaxPerDevice,
  getVendorFromPlatform, onToggleScheduleEnabled, onCronChange,
  onRetentionDaysChange, onRetentionMaxPerDeviceChange, onSaveSchedule, onRunBackupNow, showToast,
}) => {
  const zh = language === 'zh';
  const onlineCount = devices.filter(d => d.status === 'online').length;

  const cronParts = scheduleCron.split(/\s+/);
  const cronFields = [cronParts[0] ?? '0', cronParts[1] ?? '*', cronParts[2] ?? '*', cronParts[3] ?? '*', cronParts[4] ?? '*'];
  const updateCronField = (index: number, value: string) => {
    const p = [...cronFields]; p[index] = value || '*'; onCronChange(p.join(' '));
  };

  const [cronMode, setCronMode] = useState<'simple' | 'advanced'>(() => parseSimpleCron(scheduleCron) ? 'simple' : 'advanced');
  const [simpleForm, setSimpleForm] = useState<SimpleForm>(() => parseSimpleCron(scheduleCron) || { freq: 'daily', hour: 2, minute: 0, weekday: 1, monthday: 1, interval: 6 });

  const handleSimpleChange = (upd: Partial<SimpleForm>) => {
    const next = { ...simpleForm, ...upd };
    setSimpleForm(next);
    onCronChange(buildSimpleCron(next));
  };
  const switchToSimple = () => {
    const parsed = parseSimpleCron(scheduleCron);
    const form = parsed || { freq: 'daily' as CronFreq, hour: 2, minute: 0, weekday: 1, monthday: 1, interval: 6 };
    setSimpleForm(form);
    setCronMode('simple');
    onCronChange(buildSimpleCron(form));
  };

  const [preview, setPreview] = useState<PreviewData | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [presetOpen, setPresetOpen] = useState(false);

  const loadPreview = useCallback(async () => {
    setPreviewLoading(true);
    try { const r = await fetch('/api/configs/schedule/preview?n=10'); if (r.ok) setPreview(await r.json()); }
    catch { /* ignore */ } finally { setPreviewLoading(false); }
  }, []);

  const [backupStats, setBackupStats] = useState<BackupStats | null>(null);
  const fetchBackupStats = useCallback(async () => {
    try {
      const r = await fetch('/api/configs/backup-stats');
      if (r.ok) { const j = await r.json(); if (j.success) setBackupStats(j.data); }
    } catch { /* ignore */ }
  }, []);

  const [countdown, setCountdown] = useState('--:--:--');
  const countdownRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);
  useEffect(() => {
    if (countdownRef.current) clearInterval(countdownRef.current);
    if (!preview?.upcoming?.[0]) { setCountdown('--:--:--'); return; }
    const target = new Date(preview.upcoming[0]).getTime();
    const tick = () => {
      const diff = target - Date.now();
      if (diff <= 0) { setCountdown(zh ? '即将执行' : 'Imminent'); return; }
      const h = Math.floor(diff / 3600000);
      const m = Math.floor((diff % 3600000) / 60000);
      const s = Math.floor((diff % 60000) / 1000);
      setCountdown(`${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`);
    };
    tick();
    countdownRef.current = setInterval(tick, 1000);
    return () => { if (countdownRef.current) clearInterval(countdownRef.current); };
  }, [preview, zh]);

  useEffect(() => { void loadPreview(); void fetchBackupStats(); }, [loadPreview, fetchBackupStats]);

  const handleSave = async () => { await onSaveSchedule(); void loadPreview(); };
  const handleRunBackup = async () => { await onRunBackupNow(); setTimeout(() => { void fetchBackupStats(); }, 2000); };
  const applyPreset = (cron: string) => { onCronChange(cron); setPresetOpen(false); };

  const formatPreviewTime = (iso: string) => {
    try {
      const d = new Date(iso);
      const pad = (v: number) => String(v).padStart(2, '0');
      const dayNames = zh ? ['周日', '周一', '周二', '周三', '周四', '周五', '周六'] : ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
      return { date: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`, day: dayNames[d.getDay()], time: `${pad(d.getHours())}:${pad(d.getMinutes())}` };
    } catch { return { date: iso, day: '', time: '' }; }
  };
  const relativeTime = (iso: string) => {
    try {
      const diff = new Date(iso).getTime() - Date.now();
      if (diff < 0) return zh ? '已过期' : 'Overdue';
      const hours = Math.floor(diff / 3600000);
      if (hours < 1) return zh ? '不到1小时' : '<1h';
      if (hours < 24) return zh ? `${hours}小时后` : `in ${hours}h`;
      const days = Math.floor(hours / 24);
      if (days < 7) return zh ? `${days}天后` : `in ${days}d`;
      return zh ? `${Math.floor(days / 7)}周后` : `in ${Math.floor(days / 7)}w`;
    } catch { return ''; }
  };

  const chartData = useMemo(() => {
    if (!backupStats?.daily_history) return [];
    return backupStats.daily_history.map(d => ({ ...d, label: d.date.slice(5) }));
  }, [backupStats]);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const renderTooltip = useCallback(({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null;
    return (
      <div className="rounded-lg bg-[#0f172a] px-3 py-2 text-xs text-white shadow-xl border border-white/10">
        <p className="font-medium mb-1 text-white/50">{label}</p>
        {payload.map((p: { name: string; value: number; fill: string }) => (
          <p key={p.name} className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-sm" style={{ background: p.fill }} />
            <span className="text-white/70">{p.name === 'scheduled' ? (zh ? '定时' : 'Scheduled') : (zh ? '手动' : 'Manual')}</span>
            <span className="font-bold ml-auto">{p.value}</span>
          </p>
        ))}
      </div>
    );
  }, [zh]);

  const [devicePage, setDevicePage] = useState(1);
  const DEVICE_PAGE_SIZE = 5;
  const [timelineExpanded, setTimelineExpanded] = useState(false);

  const displayDeviceStats = useMemo(() => {
    const stats = backupStats?.device_stats || [];
    const start = (devicePage - 1) * DEVICE_PAGE_SIZE;
    return stats.slice(start, start + DEVICE_PAGE_SIZE);
  }, [backupStats, devicePage]);

  const sevenDayTotal = backupStats?.daily_history?.reduce((a, d) => a + d.total, 0) ?? 0;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* ── Sleek Compact Header (~42px) ── */}
      <div className="flex h-11 items-center justify-between border-b border-slate-200 bg-white px-4 shrink-0">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-cyan-50 text-cyan-700">
            <CalendarClock size={14} />
          </div>
          <span className="font-sans text-xs font-black text-[#123b50]">{zh ? '备份计划与策略' : 'Backup Schedule'}</span>
          <span className="text-[11px] text-slate-400 hidden sm:inline">{zh ? '管理定时备份与数据保留' : 'Automation & Retention'}</span>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 rounded-full bg-slate-900 px-3 py-1 text-white shadow-xs">
            <span className={`h-1.5 w-1.5 rounded-full ${scheduleEnabled ? 'bg-emerald-400 animate-pulse' : 'bg-slate-400'}`} />
            <span className="font-mono text-[10px] font-bold text-slate-300">{zh ? '调度' : 'STATUS'}:</span>
            <span className="font-sans text-[10px] font-bold text-emerald-400">{scheduleEnabled ? (zh ? '运行中' : 'Active') : (zh ? '已停用' : 'Idle')}</span>
            <div className="h-3 w-px bg-white/20" />
            <span className="font-mono text-[10px] text-slate-400">{zh ? '下次' : 'Next'}:</span>
            <span className="font-mono text-[11px] font-bold text-cyan-300">{countdown}</span>
          </div>

          <button
            onClick={() => void handleRunBackup()}
            disabled={isTakingSnapshot}
            className="inline-flex h-7 items-center gap-1.5 rounded-lg bg-cyan-600 px-3 text-xs font-bold text-white shadow-xs hover:bg-cyan-700 active:scale-95 disabled:opacity-50 transition-all"
          >
            {isTakingSnapshot ? <RefreshCw size={12} className="animate-spin" /> : <Play size={12} className="fill-current" />}
            {zh ? '立即备份' : 'Run Backup'}
          </button>
        </div>
      </div>

      {/* ── Main Content Area ── */}
      <div className="flex-1 overflow-y-auto p-2.5 sm:p-3 space-y-2.5">
        <BackupPolicyManager
          language={language}
          devices={devices}
          getVendorFromPlatform={getVendorFromPlatform}
          showToast={showToast}
        />

        {/* ── Full-Width Mini Stat Cards (4 in a row) ── */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-2.5">
          <div className="rounded-xl bg-white border border-slate-200 p-3 shadow-xs hover:border-cyan-200 transition-all">
            <div className="flex items-center justify-between text-slate-400 mb-1">
              <span className="text-[10px] font-bold uppercase tracking-wider">{zh ? '总快照数' : 'TOTAL SNAPSHOTS'}</span>
              <Database size={14} className="text-cyan-500" />
            </div>
            <p className="text-xl font-bold text-slate-800 tabular-nums">{backupStats?.total_snapshots ?? '—'}</p>
            <div className="mt-1 flex items-center gap-1">
              <div className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              <p className="text-[10px] text-slate-400 truncate">{zh ? '保留策略生效中' : 'Retention active'}</p>
            </div>
          </div>

          <div className="rounded-xl bg-white border border-slate-200 p-3 shadow-xs hover:border-emerald-200 transition-all">
            <div className="flex items-center justify-between text-slate-400 mb-1">
              <span className="text-[10px] font-bold uppercase tracking-wider">{zh ? '资产覆盖' : 'ASSET COVERAGE'}</span>
              <Server size={14} className="text-emerald-500" />
            </div>
            <div className="flex items-baseline gap-1">
              <p className="text-xl font-bold text-slate-800 tabular-nums">
                {backupStats?.device_stats?.filter(d => d.backup_count > 0).length ?? 0}
              </p>
              <p className="text-xs font-semibold text-slate-400">/{backupStats?.device_stats?.length ?? devices.length}</p>
            </div>
            <div className="mt-1.5">
              <div className="h-1 rounded-full bg-slate-100 overflow-hidden">
                <div className={`h-full rounded-full transition-all duration-700 ${((backupStats?.device_stats?.filter(d => d.backup_count > 0).length ?? 0) / (backupStats?.device_stats?.length || devices.length || 1) * 100) >= 80 ? 'bg-emerald-500' : 'bg-amber-500'}`} style={{ width: `${((backupStats?.device_stats?.filter(d => d.backup_count > 0).length ?? 0) / (backupStats?.device_stats?.length || devices.length || 1) * 100)}%` }} />
              </div>
            </div>
          </div>

          <div className="rounded-xl bg-white border border-slate-200 p-3 shadow-xs hover:border-amber-200 transition-all">
            <div className="flex items-center justify-between text-slate-400 mb-1">
              <span className="text-[10px] font-bold uppercase tracking-wider">{zh ? '今日执行' : 'TODAY RUNS'}</span>
              <TrendingUp size={14} className="text-amber-500" />
            </div>
            {(() => {
              const success = backupStats?.today?.success ?? 0;
              const failed = backupStats?.today?.failed ?? 0;
              return (
                <div className="flex items-baseline justify-between">
                  <p className="text-xl font-bold text-emerald-600 tabular-nums">{success} <span className="text-[10px] font-normal text-slate-400">{zh ? '成功' : 'ok'}</span></p>
                  <p className={`text-sm font-bold tabular-nums ${failed > 0 ? 'text-red-500' : 'text-slate-300'}`}>{failed} <span className="text-[10px] font-normal text-slate-400">{zh ? '失败' : 'fail'}</span></p>
                </div>
              );
            })()}
            <p className="text-[9px] text-slate-400 mt-1 truncate">
              {zh ? `总计 ${backupStats?.today?.total ?? 0} 次任务` : `Total ${backupStats?.today?.total ?? 0} tasks`}
            </p>
          </div>

          <div className="rounded-xl bg-white border border-slate-200 p-3 shadow-xs hover:border-violet-200 transition-all">
            <div className="flex items-center justify-between text-slate-400 mb-1">
              <span className="text-[10px] font-bold uppercase tracking-wider">{zh ? '存储占用' : 'STORAGE'}</span>
              <HardDrive size={14} className="text-violet-500" />
            </div>
            <p className="text-xl font-bold text-slate-800 tabular-nums">
              {(() => {
                const bytes = backupStats?.storage_bytes ?? backupStats?.recent_backups?.reduce((a, b) => a + (b.size || 0), 0) ?? 0;
                if (bytes < 1048576) return (bytes / 1024).toFixed(1);
                return (bytes / 1048576).toFixed(1);
              })()}
              <span className="text-xs font-semibold text-slate-400 ml-1">{backupStats?.storage_bytes && backupStats.storage_bytes < 1048576 ? 'KB' : 'MB'}</span>
            </p>
            <div className="mt-1 flex items-center gap-1">
              <BarChart3 size={10} className="text-slate-400" />
              <p className="text-[10px] text-slate-400 truncate">{zh ? '7日趋势稳定' : 'Stable 7d'}</p>
            </div>
          </div>
        </div>

        {/* ── Main 8:4 Balanced Grid ── */}
        <div className="grid grid-cols-12 gap-2.5 items-stretch">
          {/* Left Column: Trend/Schedule + Recent Backups (8 cols) */}
          <div className="col-span-12 lg:col-span-8 flex flex-col gap-2.5">
            {/* Middle Row: Trend chart & upcoming tasks */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
              <div className="rounded-xl border border-slate-200 bg-white p-3 shadow-xs">
                <div className="flex items-center justify-between mb-2">
                  <h4 className="text-xs font-bold text-slate-700">{zh ? '近期备份趋势' : 'Backup Trends'}</h4>
                  <div className="flex items-center gap-2 text-[9px] font-bold">
                    <span className="flex items-center gap-1 text-cyan-600"><span className="w-1.5 h-1.5 rounded-full bg-cyan-500" />{zh ? '定时' : 'Sched'}</span>
                    <span className="flex items-center gap-1 text-violet-600"><span className="w-1.5 h-1.5 rounded-full bg-violet-500" />{zh ? '手动' : 'Manual'}</span>
                  </div>
                </div>
                <div className="h-36">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={chartData} barGap={3}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                      <XAxis dataKey="label" tick={{ fontSize: 9, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                      <YAxis tick={{ fontSize: 9, fill: '#94a3b8' }} axisLine={false} tickLine={false} allowDecimals={false} width={24} />
                      <Tooltip content={renderTooltip} cursor={{ fill: '#f8fafc' }} />
                      <Bar dataKey="scheduled" fill="#06b6d4" radius={[3, 3, 0, 0]} name="scheduled" />
                      <Bar dataKey="manual" fill="#8b5cf6" radius={[3, 3, 0, 0]} name="manual" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="rounded-xl border border-slate-200 bg-white shadow-xs flex flex-col overflow-hidden">
                <div className="flex items-center justify-between px-3 py-2 border-b border-slate-100">
                  <h3 className="text-xs font-bold text-slate-700 flex items-center gap-1.5">
                    <Calendar size={13} className="text-cyan-500" />
                    {zh ? '未来执行计划' : 'Upcoming Schedule'}
                  </h3>
                  <button onClick={() => void loadPreview()} disabled={previewLoading}
                    className="p-1 rounded-lg text-slate-400 hover:bg-slate-50 transition-colors disabled:opacity-50">
                    <RotateCcw size={12} className={previewLoading ? 'animate-spin' : ''} />
                  </button>
                </div>
                <div className="flex-1 p-2.5">
                  {!preview || !preview.enabled ? (
                    <div className="flex flex-col items-center justify-center h-full text-slate-300 py-3">
                      <Calendar size={22} strokeWidth={1.5} className="mb-1 opacity-50" />
                      <p className="text-[11px] font-semibold">{zh ? '未启用定时计划' : 'No Active Schedule'}</p>
                    </div>
                  ) : (
                    <div className="space-y-1">
                      {(timelineExpanded ? preview.upcoming : preview.upcoming.slice(0, 4)).map((iso, idx) => {
                        const { time, date, day } = formatPreviewTime(iso);
                        const rel = relativeTime(iso);
                        return (
                          <div key={idx} className="flex items-center justify-between p-1 rounded-lg hover:bg-slate-50 transition-colors text-xs">
                            <div className="flex items-center gap-2 min-w-0">
                              <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${idx === 0 ? 'bg-cyan-500' : 'bg-slate-300'}`} />
                              <span className={`font-mono font-bold ${idx === 0 ? 'text-slate-800' : 'text-slate-500'}`}>{time}</span>
                              <span className="text-[10px] text-slate-400 truncate">{date} · {day}</span>
                            </div>
                            <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${idx === 0 ? 'bg-cyan-50 text-cyan-600' : 'bg-slate-100 text-slate-400'} shrink-0`}>
                              {rel}
                            </span>
                          </div>
                        );
                      })}
                      {preview.upcoming.length > 4 && (
                        <button onClick={() => setTimelineExpanded(!timelineExpanded)}
                          className="w-full text-center text-[10px] font-bold text-slate-400 hover:text-cyan-600 transition-colors pt-0.5">
                          {timelineExpanded ? (zh ? '收起' : 'Show less') : (zh ? `查看全部 (${preview.upcoming.length})` : `View all (${preview.upcoming.length})`)}
                        </button>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Bottom Row: Recent Backups Table */}
            <div className="rounded-xl border border-slate-200 bg-white shadow-xs overflow-hidden flex-1 flex flex-col">
              <div className="flex items-center justify-between px-3 py-2 border-b border-slate-100">
                <h3 className="text-xs font-bold text-slate-700 flex items-center gap-1.5">
                  <Activity size={13} className="text-violet-500" />
                  {zh ? '最近执行记录' : 'Recent Backups'}
                </h3>
                <span className="text-[9px] font-bold text-slate-400 uppercase">{zh ? '实时更新' : 'LIVE'}</span>
              </div>
              <div className="overflow-x-auto flex-1">
                <DataTable className="text-left">
                  <thead>
                    <tr className="bg-slate-50/70 border-b border-slate-100">
                      <th className="px-3 py-1.5 text-[10px] font-bold text-slate-400 uppercase">{zh ? '设备' : 'DEVICE'}</th>
                      <th className="px-3 py-1.5 text-[10px] font-bold text-slate-400 uppercase">{zh ? '时间' : 'TIME'}</th>
                      <th className="px-3 py-1.5 text-[10px] font-bold text-slate-400 uppercase">{zh ? '类型' : 'TYPE'}</th>
                      <th className="px-3 py-1.5 text-[10px] font-bold text-slate-400 uppercase text-right">{zh ? '大小' : 'SIZE'}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {backupStats?.recent_backups?.slice(0, 5).map(bk => (
                      <tr key={bk.id} className="hover:bg-slate-50/60 transition-colors text-xs">
                        <td className="px-3 py-1.5">
                          <div className="flex items-center gap-2">
                            <div className="w-5 h-5 rounded bg-slate-100 flex items-center justify-center text-slate-500 shrink-0">
                              <Server size={11} />
                            </div>
                            <div className="min-w-0">
                              <p className="font-bold text-slate-700 truncate">{bk.hostname}</p>
                              <p className="text-[9px] text-slate-400">{bk.vendor}</p>
                            </div>
                          </div>
                        </td>
                        <td className="px-3 py-1.5">
                          <span className="font-mono text-slate-600 font-semibold">{new Date(bk.timestamp).toLocaleTimeString(zh ? 'zh-CN' : 'en-US', { hour12: false, hour: '2-digit', minute: '2-digit' })}</span>
                          <span className="block text-[9px] text-slate-400">{new Date(bk.timestamp).toLocaleDateString()}</span>
                        </td>
                        <td className="px-3 py-1.5">
                          <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-bold ${bk.trigger === 'scheduled' ? 'bg-cyan-50 text-cyan-700' : 'bg-violet-50 text-violet-700'}`}>
                            {bk.trigger === 'scheduled' ? (zh ? '定时' : 'Sched') : (zh ? '手动' : 'Manual')}
                          </span>
                        </td>
                        <td className="px-3 py-1.5 text-right font-mono text-slate-600 font-medium">
                          {fmtSize(bk.size)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </DataTable>
              </div>
            </div>
          </div>

          {/* Right Column: Settings Panel (4 cols) Stretched to exactly match left column */}
          <div className="col-span-12 lg:col-span-4 flex flex-col">
            <div className="rounded-xl border border-slate-200 bg-white p-3.5 shadow-xs flex-1 flex flex-col justify-between">
              <div className="space-y-2.5">
                <div className="flex items-center justify-between border-b border-slate-100 pb-2.5">
                  <div>
                    <h3 className="text-xs font-bold text-slate-800">{zh ? '默认执行配置' : 'Default Schedule'}</h3>
                    <p className="text-[10px] text-slate-400">{zh ? '全局定时调度与数据保留' : 'Global cron & retention'}</p>
                  </div>
                  <button onClick={onToggleScheduleEnabled}
                    className={`relative w-10 h-5 rounded-full transition-colors duration-200 ${scheduleEnabled ? 'bg-cyan-600' : 'bg-slate-200'}`}>
                    <div className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow-xs transition-transform duration-200 ${scheduleEnabled ? 'translate-x-5' : ''}`} />
                  </button>
                </div>

                <div className={`space-y-2.5 transition-all ${scheduleEnabled ? '' : 'opacity-40 grayscale pointer-events-none'}`}>
                  <div>
                    <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1 mb-1">
                      <Timer size={11} className="text-slate-400" />
                      {zh ? '执行模式' : 'MODE'}
                    </label>
                    <div className="grid grid-cols-2 gap-1 p-0.5 bg-slate-50 rounded-lg">
                      <button onClick={switchToSimple}
                        className={`py-1 rounded text-xs font-bold transition-all ${cronMode === 'simple' ? 'bg-white text-slate-800 shadow-xs' : 'text-slate-400'}`}>
                        {zh ? '常规' : 'Simple'}
                      </button>
                      <button onClick={() => setCronMode('advanced')}
                        className={`py-1 rounded text-xs font-bold transition-all ${cronMode === 'advanced' ? 'bg-white text-slate-800 shadow-xs' : 'text-slate-400'}`}>
                        {zh ? '高级 Cron' : 'Expert'}
                      </button>
                    </div>
                  </div>

                  <div className="bg-slate-50/70 rounded-xl p-2.5 space-y-2.5 border border-slate-100">
                    {cronMode === 'simple' ? (
                      <div className="space-y-2">
                        <div>
                          <p className="text-[10px] font-bold text-slate-400 mb-1">{zh ? '执行频率' : 'FREQUENCY'}</p>
                          <select value={simpleForm.freq} onChange={e => handleSimpleChange({ freq: e.target.value as CronFreq })}
                            className="w-full bg-white border border-slate-200 rounded-lg px-2.5 py-1 text-xs font-semibold text-slate-700 outline-none focus:border-cyan-400">
                            <option value="daily">{zh ? '每天' : 'Daily'}</option>
                            <option value="weekly">{zh ? '每周' : 'Weekly'}</option>
                            <option value="hourly">{zh ? '每隔N小时' : 'Every N Hours'}</option>
                          </select>
                        </div>
                        {simpleForm.freq !== 'hourly' && (
                          <div>
                            <p className="text-[10px] font-bold text-slate-400 mb-1">{zh ? '执行时间' : 'START TIME'}</p>
                            <div className="grid grid-cols-2 gap-2">
                              <select value={simpleForm.hour} onChange={e => handleSimpleChange({ hour: parseInt(e.target.value) })}
                                className="bg-white border border-slate-200 rounded-lg px-2 py-1 text-xs font-mono font-bold text-slate-700">
                                {Array.from({ length: 24 }, (_, i) => <option key={i} value={i}>{String(i).padStart(2, '0')}:00</option>)}
                              </select>
                              <select value={simpleForm.minute} onChange={e => handleSimpleChange({ minute: parseInt(e.target.value) })}
                                className="bg-white border border-slate-200 rounded-lg px-2 py-1 text-xs font-mono font-bold text-slate-700">
                                {[0, 5, 10, 15, 20, 30, 45].map(m => <option key={m} value={m}>{String(m).padStart(2, '0')} {zh ? '分' : 'min'}</option>)}
                              </select>
                            </div>
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="space-y-1.5">
                        <div className="grid grid-cols-5 gap-1">
                          {cronFields.map((val, i) => (
                            <div key={i} className="space-y-0.5">
                              <p className="text-[8px] font-bold text-slate-400 text-center">{zh ? CRON_FIELD_LABELS_ZH[i] : CRON_FIELD_LABELS_EN[i].slice(0, 3)}</p>
                              <input value={val} onChange={e => updateCronField(i, e.target.value)}
                                className="w-full bg-white border border-slate-200 rounded py-0.5 text-center text-xs font-mono font-bold text-slate-700 outline-none focus:border-cyan-400" />
                            </div>
                          ))}
                        </div>
                        <div className="p-1.5 bg-cyan-50/70 rounded-lg border border-cyan-100">
                          <p className="text-[10px] font-bold text-cyan-700 font-mono">{scheduleCron}</p>
                          <p className="text-[9px] text-cyan-600 mt-0.5">{describeCron(scheduleCron, zh)}</p>
                        </div>
                      </div>
                    )}

                    <div className="space-y-1.5 pt-1.5 border-t border-slate-200">
                      <div>
                        <p className="text-[10px] font-bold text-slate-400 mb-0.5">{zh ? '保留天数' : 'RETENTION'}</p>
                        <select value={retentionDays} onChange={e => onRetentionDaysChange(Number(e.target.value))}
                          className="w-full bg-white border border-slate-200 rounded-lg px-2.5 py-1 text-xs font-semibold text-slate-700 outline-none">
                          <option value={30}>30 {zh ? '天' : 'Days'}</option>
                          <option value={90}>90 {zh ? '天' : 'Days'}</option>
                          <option value={365}>1 {zh ? '年' : 'Year'}</option>
                          <option value={730}>2 {zh ? '年' : 'Years'}</option>
                        </select>
                      </div>
                      <div>
                        <p className="text-[10px] font-bold text-slate-400 mb-0.5">{zh ? '每台设备最大快照数' : 'MAX SNAPSHOTS / DEVICE'}</p>
                        <input
                          type="number"
                          min={1}
                          max={5000}
                          value={retentionMaxPerDevice}
                          onChange={e => onRetentionMaxPerDeviceChange(Math.max(1, Number(e.target.value) || 1))}
                          className="w-full bg-white border border-slate-200 rounded-lg px-2.5 py-1 text-xs font-semibold text-slate-700 outline-none"
                        />
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Pinned Bottom Button */}
              <div className="pt-3">
                <button onClick={() => void handleSave()} disabled={scheduleLoading}
                  className="w-full h-8 rounded-lg bg-[#123b50] text-white font-bold text-xs shadow-xs transition-all hover:bg-[#0b2d3e] active:scale-95 disabled:opacity-50 flex items-center justify-center gap-1.5">
                  {scheduleLoading ? <RefreshCw size={12} className="animate-spin" /> : <Shield size={12} />}
                  {zh ? '保存并应用策略' : 'Save & Apply'}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ConfigScheduleTab;
