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
      <PageHero
        icon={CalendarClock}
        title={zh ? '备份计划' : 'Backup Schedule'}
        subtitle={zh ? '自动化运维控制台 · 管理全网设备配置的定时备份任务与数据保留策略' : 'Manage scheduled backup tasks and retention policies for all network assets'}
      />

      <div className="flex-1 overflow-auto px-6 py-5 space-y-4">
      <BackupPolicyManager
        language={language}
        devices={devices}
        getVendorFromPlatform={getVendorFromPlatform}
        showToast={showToast}
      />

      {/* ── Status Bar ── */}
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative overflow-hidden rounded-[28px] bg-slate-900 p-6 shadow-2xl"
      >
        <div className="absolute -right-20 -top-20 h-64 w-64 rounded-full bg-cyan-500/10 blur-[80px]" />
        <div className="absolute -left-20 -bottom-20 h-64 w-64 rounded-full bg-violet-500/10 blur-[80px]" />

        <div className="relative flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-3">
            <div className={`flex items-center gap-2 px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider ${scheduleEnabled ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-white/5 text-white/30 border border-white/10'}`}>
              <div className={`w-1.5 h-1.5 rounded-full ${scheduleEnabled ? 'bg-emerald-400 animate-pulse' : 'bg-white/20'}`} />
              {scheduleEnabled ? (zh ? '运行中' : 'ACTIVE') : (zh ? '已停用' : 'IDLE')}
            </div>
            <span className="text-[12px] text-slate-300">
              {zh ? '定时任务运行状态' : 'Scheduled task status'}
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-8 px-6 py-3 rounded-2xl bg-white/5 border border-white/5 backdrop-blur-md">
              <div className="text-center">
                <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">{zh ? '今日执行' : 'TODAY'}</p>
                <p className="text-xl font-mono font-bold text-white leading-none">{backupStats?.today?.total ?? 0}</p>
              </div>
              <div className="w-px h-8 bg-white/10" />
              <div className="text-center">
                <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">{zh ? '下次执行' : 'NEXT RUN'}</p>
                <p className="text-xl font-mono font-bold text-cyan-400 leading-none">{countdown}</p>
              </div>
            </div>

            <button
              onClick={() => void handleRunBackup()}
              disabled={isTakingSnapshot}
              className="group relative inline-flex h-12 items-center gap-3 rounded-2xl bg-white px-6 text-sm font-bold text-slate-900 shadow-[0_20px_40px_rgba(255,255,255,0.1)] transition-all hover:-translate-y-0.5 hover:bg-slate-50 active:scale-95 disabled:opacity-50"
            >
              {isTakingSnapshot ? <RefreshCw size={16} className="animate-spin" /> : <Play size={16} className="fill-current" />}
              {zh ? '立即备份' : 'Run Backup Now'}
            </button>
          </div>
        </div>
      </motion.div>

      {/* ── Main Dashboard Layout ── */}
      <div className="grid grid-cols-12 gap-5">
        {/* Left Column: Stats & Detailed Tables (8 cols) */}
        <div className="col-span-12 lg:col-span-8 space-y-5">
          {/* Top Row: Mini Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}
              className="rounded-2xl bg-white dark:bg-[#1a2333] border border-black/[0.06] dark:border-white/10 p-5 shadow-sm hover:shadow-md transition-all group overflow-hidden relative">
              <div className="absolute top-0 right-0 w-24 h-24 -mr-8 -mt-8 bg-cyan-500/5 rounded-full blur-2xl group-hover:bg-cyan-500/10 transition-colors" />
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400 dark:text-slate-500">{zh ? '总快照数' : 'TOTAL SNAPSHOTS'}</span>
                <Database size={16} className="text-cyan-500/40" />
              </div>
              <p className="text-3xl font-bold text-slate-800 dark:text-white/90 tabular-nums">{backupStats?.total_snapshots ?? '—'}</p>
              <div className="mt-2 flex items-center gap-1.5">
                <div className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                <p className="text-[10px] text-slate-400 dark:text-slate-500 font-medium">{zh ? '数据保留策略生效中' : 'Retention policy active'}</p>
              </div>
            </motion.div>

            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}
              className="rounded-2xl bg-white dark:bg-[#1a2333] border border-black/[0.06] dark:border-white/10 p-5 shadow-sm hover:shadow-md transition-all group overflow-hidden relative">
              <div className="absolute top-0 right-0 w-24 h-24 -mr-8 -mt-8 bg-emerald-500/5 rounded-full blur-2xl group-hover:bg-emerald-500/10 transition-colors" />
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400 dark:text-slate-500">{zh ? '资产覆盖' : 'ASSET COVERAGE'}</span>
                <Server size={16} className="text-emerald-500/40" />
              </div>
              <div className="flex items-baseline gap-1.5">
                <p className="text-3xl font-bold text-slate-800 dark:text-white/90 tabular-nums">
                  {backupStats?.device_stats?.filter(d => d.backup_count > 0).length ?? 0}
                </p>
                <p className="text-sm font-semibold text-slate-300 dark:text-slate-600">/{backupStats?.device_stats?.length ?? devices.length}</p>
              </div>
              <div className="mt-3">
                <div className="h-1.5 rounded-full bg-slate-100 dark:bg-white/5 overflow-hidden">
                  <div className={`h-full rounded-full transition-all duration-700 ${((backupStats?.device_stats?.filter(d => d.backup_count > 0).length ?? 0) / (backupStats?.device_stats?.length || devices.length || 1) * 100) >= 80 ? 'bg-emerald-500' : 'bg-amber-500'}`} style={{ width: `${((backupStats?.device_stats?.filter(d => d.backup_count > 0).length ?? 0) / (backupStats?.device_stats?.length || devices.length || 1) * 100)}%` }} />
                </div>
              </div>
            </motion.div>

            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}
              className="rounded-2xl bg-white dark:bg-[#1a2333] border border-black/[0.06] dark:border-white/10 p-5 shadow-sm hover:shadow-md transition-all group overflow-hidden relative">
              <div className="absolute top-0 right-0 w-24 h-24 -mr-8 -mt-8 bg-amber-500/5 rounded-full blur-2xl group-hover:bg-amber-500/10 transition-colors" />
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400 dark:text-slate-500">{zh ? '今日执行' : 'TODAY RUNS'}</span>
                <TrendingUp size={16} className="text-amber-500/40" />
              </div>
              {(() => {
                const success = backupStats?.today?.success ?? 0;
                const failed = backupStats?.today?.failed ?? 0;
                const unobserved = backupStats?.today?.unobserved ?? 0;
                return (
                  <div>
                    <div className="flex items-baseline gap-2">
                      <p className="text-3xl font-bold text-emerald-600 tabular-nums">{success}</p>
                      <p className={`text-xl font-bold tabular-nums ${failed > 0 ? 'text-red-500' : 'text-slate-200 dark:text-slate-700'}`}>{failed}</p>
                      {unobserved > 0 && <p className="text-xl font-bold text-amber-500 tabular-nums">{unobserved}</p>}
                    </div>
                    <p className="text-[10px] font-medium text-slate-400 dark:text-slate-500 mt-1 uppercase tracking-wide">
                      {zh ? `成功 ${success} · 失败 ${failed}${unobserved ? ` · 未观测 ${unobserved}` : ''}` : `SUCCESS ${success} · FAIL ${failed}${unobserved ? ` · UNOBSERVED ${unobserved}` : ''}`}
                    </p>
                  </div>
                );
              })()}
            </motion.div>

            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}
              className="rounded-2xl bg-white dark:bg-[#1a2333] border border-black/[0.06] dark:border-white/10 p-5 shadow-sm hover:shadow-md transition-all group overflow-hidden relative">
              <div className="absolute top-0 right-0 w-24 h-24 -mr-8 -mt-8 bg-violet-500/5 rounded-full blur-2xl group-hover:bg-violet-500/10 transition-colors" />
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400 dark:text-slate-500">{zh ? '存储占用' : 'STORAGE'}</span>
                <HardDrive size={16} className="text-violet-500/40" />
              </div>
              <p className="text-3xl font-bold text-slate-800 dark:text-white/90 tabular-nums">
                {(() => {
                  const bytes = backupStats?.storage_bytes ?? backupStats?.recent_backups?.reduce((a, b) => a + (b.size || 0), 0) ?? 0;
                  if (bytes < 1048576) return (bytes / 1024).toFixed(1);
                  return (bytes / 1048576).toFixed(1);
                })()}
                <span className="text-sm font-semibold text-slate-400 dark:text-slate-600 ml-1">{backupStats?.storage_bytes && backupStats.storage_bytes < 1048576 ? 'KB' : 'MB'}</span>
              </p>
              <div className="mt-2 flex items-center gap-1.5">
                <BarChart3 size={11} className="text-slate-300 dark:text-slate-600" />
                <p className="text-[10px] text-slate-400 dark:text-slate-500 font-medium">{zh ? '7日趋势稳定' : 'Stable trend last 7d'}</p>
              </div>
            </motion.div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.25 }}
              className="rounded-3xl border border-black/[0.06] bg-white p-6 shadow-sm">
              <div className="flex items-center justify-between mb-6">
                <h4 className="text-sm font-bold text-slate-700">{zh ? '近期备份趋势' : 'Backup Trends'}</h4>
                <div className="flex items-center gap-3 text-[10px] font-bold uppercase tracking-wider">
                  <span className="flex items-center gap-1.5 text-cyan-600"><span className="w-2 h-2 rounded-full bg-cyan-500" />{zh ? '定时' : 'Sched'}</span>
                  <span className="flex items-center gap-1.5 text-violet-600"><span className="w-2 h-2 rounded-full bg-violet-500" />{zh ? '手动' : 'Manual'}</span>
                </div>
              </div>
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} barGap={4}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                    <XAxis dataKey="label" tick={{ fontSize: 10, fill: '#94a3b8', fontWeight: 600 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 10, fill: '#94a3b8', fontWeight: 600 }} axisLine={false} tickLine={false} allowDecimals={false} width={28} />
                    <Tooltip content={renderTooltip} cursor={{ fill: '#f8fafc' }} />
                    <Bar dataKey="scheduled" fill="#06b6d4" radius={[4, 4, 0, 0]} name="scheduled" />
                    <Bar dataKey="manual" fill="#8b5cf6" radius={[4, 4, 0, 0]} name="manual" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </motion.div>

            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}
              className="rounded-3xl border border-black/[0.06] bg-white shadow-sm flex flex-col">
              <div className="flex items-center justify-between px-6 py-5 border-b border-slate-50">
                <h3 className="text-sm font-bold text-slate-700 flex items-center gap-2">
                  <Calendar size={16} className="text-cyan-500" />
                  {zh ? '执行计划' : 'Scheduled Tasks'}
                </h3>
                <button onClick={() => void loadPreview()} disabled={previewLoading}
                  className="p-2 rounded-xl bg-slate-50 text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-all disabled:opacity-50">
                  <RotateCcw size={14} className={previewLoading ? 'animate-spin' : ''} />
                </button>
              </div>
              <div className="flex-1 p-6">
                {!preview || !preview.enabled ? (
                  <div className="flex flex-col items-center justify-center h-full text-slate-300 py-4">
                    <Calendar size={32} strokeWidth={1.5} className="mb-2 opacity-50" />
                    <p className="text-xs font-semibold">{zh ? '未启用定时计划' : 'No Active Schedule'}</p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {(timelineExpanded ? preview.upcoming : preview.upcoming.slice(0, 4)).map((iso, idx) => {
                      const { time, date, day } = formatPreviewTime(iso);
                      const rel = relativeTime(iso);
                      return (
                        <div key={idx} className="flex items-center justify-between group p-2 rounded-2xl hover:bg-slate-50 transition-colors">
                          <div className="flex items-center gap-4">
                            <div className={`w-2 h-2 rounded-full ${idx === 0 ? 'bg-cyan-500 shadow-[0_0_10px_rgba(6,182,212,0.5)]' : 'bg-slate-200'}`} />
                            <div>
                              <p className={`text-sm font-bold font-mono ${idx === 0 ? 'text-slate-900' : 'text-slate-400'}`}>{time}</p>
                              <p className="text-[10px] font-bold text-slate-400 uppercase tracking-tight">{date} · {day}</p>
                            </div>
                          </div>
                          <span className={`text-[10px] font-bold px-2 py-1 rounded-lg ${idx === 0 ? 'bg-cyan-50 text-cyan-600' : 'bg-slate-100 text-slate-400'}`}>
                            {rel}
                          </span>
                        </div>
                      );
                    })}
                    {preview.upcoming.length > 4 && (
                      <button onClick={() => setTimelineExpanded(!timelineExpanded)}
                        className="w-full text-center text-[10px] font-bold text-slate-400 hover:text-cyan-600 transition-colors pt-2 uppercase tracking-widest">
                        {timelineExpanded ? (zh ? '收起' : 'SHOW LESS') : (zh ? `查看全部 ${preview.upcoming.length} 条` : `VIEW ALL ${preview.upcoming.length}`)}
                      </button>
                    )}
                  </div>
                )}
              </div>
            </motion.div>
          </div>

          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.35 }}
            className="rounded-3xl border border-black/[0.06] bg-white shadow-sm overflow-hidden">
            <div className="flex items-center justify-between px-6 py-5 border-b border-slate-50">
              <h3 className="text-sm font-bold text-slate-700 flex items-center gap-2">
                <Activity size={16} className="text-violet-500" />
                {zh ? '最近执行日志' : 'Recent Activity'}
              </h3>
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">{zh ? '实时更新' : 'LIVE'}</span>
            </div>
            <div className="overflow-x-auto">
              <DataTable className="text-left">
                <thead>
                  <tr className="bg-slate-50/50">
                    <th className="px-6 py-3 text-[10px] font-bold text-slate-400 uppercase tracking-widest">{zh ? '设备' : 'DEVICE'}</th>
                    <th className="px-6 py-3 text-[10px] font-bold text-slate-400 uppercase tracking-widest">{zh ? '时间' : 'TIME'}</th>
                    <th className="px-6 py-3 text-[10px] font-bold text-slate-400 uppercase tracking-widest">{zh ? '类型' : 'TYPE'}</th>
                    <th className="px-6 py-3 text-[10px] font-bold text-slate-400 uppercase tracking-widest text-right">{zh ? '大小' : 'SIZE'}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50">
                  {backupStats?.recent_backups?.slice(0, 5).map(bk => (
                    <tr key={bk.id} className="group hover:bg-slate-50/80 transition-colors">
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-lg bg-slate-100 flex items-center justify-center text-slate-500 group-hover:bg-white transition-colors">
                            <Server size={14} />
                          </div>
                          <div>
                            <p className="text-sm font-bold text-slate-700">{bk.hostname}</p>
                            <p className="text-[10px] font-semibold text-slate-400 uppercase">{bk.vendor}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <p className="text-xs font-bold text-slate-600 font-mono">
                          {new Date(bk.timestamp).toLocaleTimeString(zh ? 'zh-CN' : 'en-US', { hour12: false, hour: '2-digit', minute: '2-digit' })}
                        </p>
                        <p className="text-[10px] font-medium text-slate-400">{new Date(bk.timestamp).toLocaleDateString()}</p>
                      </td>
                      <td className="px-6 py-4">
                        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wider ${bk.trigger === 'scheduled' ? 'bg-cyan-50 text-cyan-600' : 'bg-violet-50 text-violet-600'}`}>
                          {bk.trigger === 'scheduled' ? (zh ? '定时' : 'SCHED') : (zh ? '手动' : 'MANUAL')}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-right">
                        <p className="text-xs font-bold text-slate-600 font-mono tracking-tight">{fmtSize(bk.size)}</p>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            </div>
          </motion.div>
        </div>

        {/* Right Column: Settings Panel (4 cols) */}
        <div className="col-span-12 lg:col-span-4">
          <div className="rounded-[32px] border border-black/5 bg-white p-8 shadow-xl shadow-slate-200/50 sticky top-5 space-y-8">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-lg font-bold text-slate-800">{zh ? '备份配置' : 'Backup Config'}</h3>
                <p className="text-xs text-slate-400 font-medium">{zh ? '配置自动化运行策略' : 'Automation policies'}</p>
              </div>
              <button onClick={onToggleScheduleEnabled}
                className={`relative w-14 h-8 rounded-full transition-all duration-300 ${scheduleEnabled ? 'bg-cyan-500 shadow-[0_0_15px_rgba(6,182,212,0.3)]' : 'bg-slate-200'}`}>
                <div className={`absolute top-1 left-1 w-6 h-6 bg-white rounded-full shadow-lg transition-transform duration-300 ${scheduleEnabled ? 'translate-x-6' : ''}`} />
              </button>
            </div>

            <div className={`space-y-4 transition-all duration-300 ${scheduleEnabled ? '' : 'opacity-40 grayscale pointer-events-none scale-[0.98]'}`}>
              <div className="space-y-3">
                <label className="text-[10px] font-bold text-slate-400 uppercase tracking-widest flex items-center gap-2">
                  <Timer size={12} className="text-slate-300" />
                  {zh ? '执行模式' : 'EXECUTION MODE'}
                </label>
                <div className="grid grid-cols-2 gap-2 p-1 bg-slate-50 rounded-2xl">
                  <button onClick={switchToSimple}
                    className={`px-4 py-2.5 rounded-xl text-xs font-bold transition-all ${cronMode === 'simple' ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-400'}`}>
                    {zh ? '常规' : 'SIMPLE'}
                  </button>
                  <button onClick={() => setCronMode('advanced')}
                    className={`px-4 py-2.5 rounded-xl text-xs font-bold transition-all ${cronMode === 'advanced' ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-400'}`}>
                    {zh ? '高级' : 'EXPERT'}
                  </button>
                </div>
              </div>

              <div className="bg-slate-50/50 rounded-3xl p-6 space-y-5 border border-slate-50">
                {cronMode === 'simple' ? (
                  <div className="space-y-4">
                    <div className="space-y-2">
                      <p className="text-[10px] font-bold text-slate-400">{zh ? '频率' : 'FREQUENCY'}</p>
                      <select value={simpleForm.freq} onChange={e => handleSimpleChange({ freq: e.target.value as CronFreq })}
                        className="w-full bg-white border border-slate-100 rounded-xl px-4 py-2.5 text-sm font-bold text-slate-700 outline-none focus:ring-2 focus:ring-cyan-500/20">
                        <option value="daily">{zh ? '每天' : 'Daily'}</option>
                        <option value="weekly">{zh ? '每周' : 'Weekly'}</option>
                        <option value="hourly">{zh ? '每隔N小时' : 'Every N Hours'}</option>
                      </select>
                    </div>
                    {simpleForm.freq !== 'hourly' && (
                      <div className="space-y-2">
                        <p className="text-[10px] font-bold text-slate-400">{zh ? '时间' : 'START TIME'}</p>
                        <div className="grid grid-cols-2 gap-3">
                          <select value={simpleForm.hour} onChange={e => handleSimpleChange({ hour: parseInt(e.target.value) })}
                            className="bg-white border border-slate-100 rounded-xl px-4 py-2.5 text-sm font-mono font-bold text-slate-700">
                            {Array.from({ length: 24 }, (_, i) => <option key={i} value={i}>{String(i).padStart(2, '0')}</option>)}
                          </select>
                          <select value={simpleForm.minute} onChange={e => handleSimpleChange({ minute: parseInt(e.target.value) })}
                            className="bg-white border border-slate-100 rounded-xl px-4 py-2.5 text-sm font-mono font-bold text-slate-700">
                            {[0, 5, 10, 15, 20, 30, 45].map(m => <option key={m} value={m}>{String(m).padStart(2, '0')}</option>)}
                          </select>
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="space-y-4">
                    <div className="grid grid-cols-5 gap-2">
                      {cronFields.map((val, i) => (
                        <div key={i} className="space-y-1">
                          <p className="text-[8px] font-bold text-slate-400 text-center">{zh ? CRON_FIELD_LABELS_ZH[i] : CRON_FIELD_LABELS_EN[i].slice(0, 3)}</p>
                          <input value={val} onChange={e => updateCronField(i, e.target.value)}
                            className="w-full bg-white border border-slate-100 rounded-lg py-2 text-center text-xs font-mono font-bold text-slate-700 outline-none focus:border-cyan-500" />
                        </div>
                      ))}
                    </div>
                    <div className="p-3 bg-cyan-50/50 rounded-xl border border-cyan-100">
                      <p className="text-[10px] font-bold text-cyan-700 font-mono tracking-tight">{scheduleCron}</p>
                      <p className="text-[9px] text-cyan-600 mt-1 font-medium">{describeCron(scheduleCron, zh)}</p>
                    </div>
                  </div>
                )}

                <div className="space-y-2 pt-2 border-t border-slate-100">
                  <p className="text-[10px] font-bold text-slate-400">{zh ? '数据保留' : 'RETENTION'}</p>
                  <select value={retentionDays} onChange={e => onRetentionDaysChange(Number(e.target.value))}
                    className="w-full bg-white border border-slate-100 rounded-xl px-4 py-2.5 text-sm font-bold text-slate-700 outline-none">
                    <option value={30}>30 {zh ? '天' : 'Days'}</option>
                    <option value={90}>90 {zh ? '天' : 'Days'}</option>
                    <option value={365}>1 {zh ? '年' : 'Year'}</option>
                    <option value={730}>2 {zh ? '年' : 'Years'}</option>
                  </select>
                  <div className="space-y-2 pt-2">
                    <p className="text-[10px] font-bold text-slate-400">{zh ? '姣忚澶囨渶澶у揩鐓х數' : 'MAX SNAPSHOTS / DEVICE'}</p>
                    <input
                      type="number"
                      min={1}
                      max={5000}
                      value={retentionMaxPerDevice}
                      onChange={e => onRetentionMaxPerDeviceChange(Math.max(1, Number(e.target.value) || 1))}
                      className="w-full bg-white border border-slate-100 rounded-xl px-4 py-2.5 text-sm font-bold text-slate-700 outline-none"
                    />
                  </div>
                </div>
              </div>

              <button onClick={() => void handleSave()} disabled={scheduleLoading}
                className="w-full h-14 rounded-[20px] bg-slate-900 text-white font-bold text-sm shadow-xl shadow-slate-300 transition-all hover:bg-slate-800 hover:-translate-y-0.5 active:scale-95 disabled:opacity-50 flex items-center justify-center gap-2">
                {scheduleLoading ? <RefreshCw size={18} className="animate-spin" /> : <Shield size={18} />}
                {zh ? '保存并应用策略' : 'SAVE & APPLY POLICY'}
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
