import React, { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  Database, RotateCcw, Calendar, Server, ChevronDown, Play, Info, Zap,
  Activity, Timer, TrendingUp, BarChart3,
} from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import type { ConfigSnapshot, Device } from '../types';
import Pagination from '../components/Pagination';

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
  today: { total: number; scheduled: number; manual: number };
  daily_history: { date: string; scheduled: number; manual: number; total: number }[];
  total_snapshots: number; total_devices_backed: number;
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
  getVendorFromPlatform: (platform?: string) => string;
  onToggleScheduleEnabled: () => void;
  onCronChange: (value: string) => void;
  onRetentionDaysChange: (value: number) => void;
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
  scheduleEnabled, scheduleCron, scheduleLoading, retentionDays,
  getVendorFromPlatform, onToggleScheduleEnabled, onCronChange,
  onRetentionDaysChange, onSaveSchedule, onRunBackupNow, showToast,
}) => {
  const zh = language === 'zh';
  const onlineCount = devices.filter(d => d.status === 'online').length;

  // Backup-only page (inspection moved to /automation/schedule)

  /* ═══ BACKUP STATE ═══ */

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
  const countdownRef = useRef<ReturnType<typeof setInterval>>();
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

  const DEVICE_PAGE_SIZE = 5;
  const [devicePage, setDevicePage] = useState(1);
  const [scopeExpanded, setScopeExpanded] = useState(false);
  const SCOPE_PREVIEW_COUNT = 4;
  const TIMELINE_PREVIEW = 5;
  const [timelineExpanded, setTimelineExpanded] = useState(false);
  const displayDeviceStats = useMemo(() => {
    const stats = backupStats?.device_stats || [];
    const start = (devicePage - 1) * DEVICE_PAGE_SIZE;
    return stats.slice(start, start + DEVICE_PAGE_SIZE);
  }, [backupStats, devicePage]);

  /* ═══ INSPECTION STATE ═══ */

  /* ═══ RENDER ═══ */

  const sevenDayTotal = backupStats?.daily_history?.reduce((a, d) => a + d.total, 0) ?? 0;

  return (
    <div className="space-y-3">
      {/* ═══ Page Header ═══ */}
      <div className="rounded-2xl border border-black/5 bg-white shadow-sm">
        <div className="flex items-center justify-between px-5 py-3">
          <div>
            <h2 className="text-lg font-semibold text-[#164e63]">{zh ? '备份计划' : 'Backup Schedule'}</h2>
            <p className="text-[11px] text-black/40">{zh ? '自动化运维控制台 · 管理配置备份计划' : 'Automation Console · Manage config backup schedules'}</p>
          </div>
        </div>
      </div>

      {/* ═══════════════════════════════════════ */}
      {/*  BACKUP CONTENT                         */}
      {/* ═══════════════════════════════════════ */}
        <div className="space-y-3">
          {/* ── NOC Status Bar ── */}
          <motion.div
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
            className="rounded-2xl bg-gradient-to-r from-[#0f172a] to-[#1e293b] p-4 shadow-lg"
          >
            <div className="flex items-center justify-between flex-wrap gap-3">
              {/* Left: Status */}
              <div className="flex items-center gap-3 flex-wrap">
                <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg ${scheduleEnabled ? 'bg-emerald-500/15' : 'bg-white/5'}`}>
                  <div className={`w-2 h-2 rounded-full ${scheduleEnabled ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]' : 'bg-white/20'}`} />
                  <span className={`text-[11px] font-bold uppercase tracking-wider ${scheduleEnabled ? 'text-emerald-400' : 'text-white/30'}`}>
                    {scheduleEnabled ? (zh ? '运行中' : 'ACTIVE') : (zh ? '已停用' : 'IDLE')}
                  </span>
                </div>
                <div className="hidden sm:flex items-center gap-2 text-xs text-white/40">
                  <code className="text-cyan-400/80 font-mono text-[11px]">{scheduleCron}</code>
                  <span className="text-white/25">{describeCron(scheduleCron, zh)}</span>
                </div>
                <div className="hidden md:flex items-center gap-1.5 text-xs text-white/35">
                  <Server size={11} className="text-white/25" />
                  <span>{onlineCount} {zh ? '在线' : 'online'}</span>
                </div>
              </div>

              {/* Center: Today stats */}
              <div className="hidden lg:flex items-center gap-4">
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-white/25">{zh ? '今日' : 'Today'}</span>
                  <span className="text-xl font-bold text-white tabular-nums">{backupStats?.today?.total ?? 0}</span>
                </div>
                <div className="w-px h-5 bg-white/10" />
                <div className="flex items-center gap-1.5 text-xs">
                  <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
                  <span className="text-cyan-400/80 tabular-nums">{backupStats?.today?.scheduled ?? 0}</span>
                  <span className="text-white/20">{zh ? '定时' : 'sched'}</span>
                </div>
                <div className="flex items-center gap-1.5 text-xs">
                  <span className="w-1.5 h-1.5 rounded-full bg-violet-400" />
                  <span className="text-violet-400/80 tabular-nums">{backupStats?.today?.manual ?? 0}</span>
                  <span className="text-white/20">{zh ? '手动' : 'manual'}</span>
                </div>
              </div>

              {/* Right: Countdown + CTA */}
              <div className="flex items-center gap-3">
                {scheduleEnabled && preview?.upcoming?.[0] && (
                  <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/5">
                    <Timer size={12} className="text-cyan-400/60" />
                    <span className="text-[10px] text-white/30 uppercase tracking-wide">{zh ? '下次' : 'Next'}</span>
                    <span className="font-mono text-sm font-bold text-cyan-400 tabular-nums tracking-wider">{countdown}</span>
                  </div>
                )}
                <button
                  onClick={() => void handleRunBackup()}
                  disabled={isTakingSnapshot}
                  className="inline-flex h-9 items-center gap-2 rounded-xl bg-gradient-to-r from-cyan-500 to-teal-400 px-4 text-xs font-bold text-white shadow-lg shadow-cyan-500/25 transition-all hover:shadow-cyan-500/40 hover:brightness-110 disabled:opacity-40 active:scale-[0.97]"
                >
                  {isTakingSnapshot ? <RotateCcw size={13} className="animate-spin" /> : <Play size={13} />}
                  {zh ? '立即备份' : 'Run Now'}
                </button>
              </div>
            </div>
          </motion.div>

          {/* ── Main Grid: Dashboard + Config ── */}
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
            {/* Config Card (right on XL via order) */}
            <div className="xl:order-2">
              <div className="rounded-2xl border border-black/5 bg-white p-4 shadow-sm xl:sticky xl:top-3">
                {/* Enable toggle */}
                <div className="flex items-center justify-between pb-4 border-b border-black/5">
                  <div>
                    <h3 className="text-sm font-bold text-[#164e63]">{zh ? '启用定时备份' : 'Enable Scheduled Backup'}</h3>
                    <p className="text-[11px] text-black/35 mt-0.5">{zh ? '开启后按计划自动备份所有在线设备' : 'Auto-backup all online devices on schedule'}</p>
                  </div>
                  <button
                    onClick={onToggleScheduleEnabled}
                    className={`relative w-12 h-[26px] rounded-full transition-colors duration-200 ${scheduleEnabled ? 'bg-[#06b6d4]' : 'bg-black/10'}`}
                  >
                    <span className={`absolute top-[3px] left-[3px] w-5 h-5 bg-white rounded-full shadow-sm transition-transform duration-200 ${scheduleEnabled ? 'translate-x-[22px]' : ''}`} />
                  </button>
                </div>

                {/* Cron mode switch */}
                <div className={`mt-4 transition-opacity ${scheduleEnabled ? '' : 'opacity-35 pointer-events-none'}`}>
                  <div className="flex items-center gap-1 rounded-lg bg-black/[0.03] p-0.5">
                    <button
                      onClick={switchToSimple}
                      className={`flex-1 px-3 py-1.5 rounded-md text-xs font-semibold transition-all ${cronMode === 'simple' ? 'bg-white text-[#164e63] shadow-sm' : 'text-black/40'}`}
                    >
                      {zh ? '简易模式' : 'Simple'}
                    </button>
                    <button
                      onClick={() => setCronMode('advanced')}
                      className={`flex-1 px-3 py-1.5 rounded-md text-xs font-semibold transition-all ${cronMode === 'advanced' ? 'bg-white text-[#164e63] shadow-sm' : 'text-black/40'}`}
                    >
                      {zh ? '高级模式' : 'Advanced'}
                    </button>
                  </div>

                  {/* ── Simple Mode ── */}
                  {cronMode === 'simple' && (
                    <div className="mt-3 space-y-3">
                      <div>
                        <label className="text-[10px] font-bold uppercase tracking-wider text-black/30 mb-1 block">{zh ? '执行频率' : 'Frequency'}</label>
                        <select
                          value={simpleForm.freq}
                          onChange={e => handleSimpleChange({ freq: e.target.value as CronFreq })}
                          className="w-full h-10 rounded-xl border border-black/8 bg-[#f8fafc] px-3 text-sm outline-none focus:border-[#06b6d4]/40 focus:ring-2 focus:ring-[#06b6d4]/10 transition-all"
                        >
                          <option value="hourly">{zh ? '每N小时' : 'Every N hours'}</option>
                          <option value="daily">{zh ? '每天' : 'Daily'}</option>
                          <option value="weekly">{zh ? '每周' : 'Weekly'}</option>
                          <option value="monthly">{zh ? '每月' : 'Monthly'}</option>
                        </select>
                      </div>

                      {simpleForm.freq === 'hourly' && (
                        <div>
                          <label className="text-[10px] font-bold uppercase tracking-wider text-black/30 mb-1 block">{zh ? '间隔' : 'Interval'}</label>
                          <select
                            value={simpleForm.interval}
                            onChange={e => handleSimpleChange({ interval: parseInt(e.target.value) })}
                            className="w-full h-10 rounded-xl border border-black/8 bg-[#f8fafc] px-3 text-sm outline-none focus:border-[#06b6d4]/40 focus:ring-2 focus:ring-[#06b6d4]/10 transition-all"
                          >
                            {[1, 2, 3, 4, 6, 8, 12].map(n => (
                              <option key={n} value={n}>{zh ? `每 ${n} 小时` : `Every ${n} hours`}</option>
                            ))}
                          </select>
                        </div>
                      )}

                      {simpleForm.freq !== 'hourly' && (
                        <div>
                          <label className="text-[10px] font-bold uppercase tracking-wider text-black/30 mb-1 block">{zh ? '执行时间' : 'Time'}</label>
                          <div className="flex items-center gap-2">
                            <select
                              value={simpleForm.hour}
                              onChange={e => handleSimpleChange({ hour: parseInt(e.target.value) })}
                              className="flex-1 h-10 rounded-xl border border-black/8 bg-[#f8fafc] px-3 text-sm font-mono outline-none focus:border-[#06b6d4]/40 focus:ring-2 focus:ring-[#06b6d4]/10 transition-all"
                            >
                              {Array.from({ length: 24 }, (_, i) => (
                                <option key={i} value={i}>{String(i).padStart(2, '0')}</option>
                              ))}
                            </select>
                            <span className="text-lg font-bold text-black/20">:</span>
                            <select
                              value={simpleForm.minute}
                              onChange={e => handleSimpleChange({ minute: parseInt(e.target.value) })}
                              className="flex-1 h-10 rounded-xl border border-black/8 bg-[#f8fafc] px-3 text-sm font-mono outline-none focus:border-[#06b6d4]/40 focus:ring-2 focus:ring-[#06b6d4]/10 transition-all"
                            >
                              {[0, 5, 10, 15, 20, 30, 45].map(m => (
                                <option key={m} value={m}>{String(m).padStart(2, '0')}</option>
                              ))}
                            </select>
                          </div>
                        </div>
                      )}

                      {simpleForm.freq === 'weekly' && (
                        <div>
                          <label className="text-[10px] font-bold uppercase tracking-wider text-black/30 mb-1.5 block">{zh ? '星期' : 'Day'}</label>
                          <div className="grid grid-cols-7 gap-1">
                            {(zh ? WEEKDAY_ZH : WEEKDAY_EN).map((label, i) => (
                              <button
                                key={i}
                                onClick={() => handleSimpleChange({ weekday: i })}
                                className={`h-8 rounded-lg text-[11px] font-semibold transition-all ${
                                  simpleForm.weekday === i
                                    ? 'bg-[#06b6d4] text-white shadow-sm'
                                    : 'bg-black/[0.03] text-black/40 hover:bg-black/[0.06]'
                                }`}
                              >
                                {label}
                              </button>
                            ))}
                          </div>
                        </div>
                      )}

                      {simpleForm.freq === 'monthly' && (
                        <div>
                          <label className="text-[10px] font-bold uppercase tracking-wider text-black/30 mb-1 block">{zh ? '日期' : 'Date'}</label>
                          <select
                            value={simpleForm.monthday}
                            onChange={e => handleSimpleChange({ monthday: parseInt(e.target.value) })}
                            className="w-full h-10 rounded-xl border border-black/8 bg-[#f8fafc] px-3 text-sm outline-none focus:border-[#06b6d4]/40 focus:ring-2 focus:ring-[#06b6d4]/10 transition-all"
                          >
                            {Array.from({ length: 28 }, (_, i) => (
                              <option key={i + 1} value={i + 1}>{zh ? `每月 ${i + 1} 日` : `Day ${i + 1}`}</option>
                            ))}
                          </select>
                        </div>
                      )}
                    </div>
                  )}

                  {/* ── Advanced Mode ── */}
                  {cronMode === 'advanced' && (
                    <div className="mt-3 space-y-3">
                      {/* Quick presets */}
                      <div className="relative">
                        <button
                          onClick={() => setPresetOpen(!presetOpen)}
                          className="inline-flex h-10 w-full items-center justify-between gap-2 rounded-xl border border-black/8 bg-[#f8fafc] px-3.5 text-sm text-[#164e63] transition-all hover:border-[#06b6d4]/30 hover:bg-white"
                        >
                          <div className="flex items-center gap-2">
                            <Zap size={13} className="text-[#06b6d4]" />
                            <span>{zh ? '快速预设' : 'Quick Presets'}</span>
                          </div>
                          <ChevronDown size={14} className={`text-black/30 transition-transform ${presetOpen ? 'rotate-180' : ''}`} />
                        </button>
                        <AnimatePresence>
                          {presetOpen && (
                            <motion.div
                              initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
                              className="absolute z-20 mt-1.5 w-full rounded-xl border border-black/8 bg-white shadow-lg overflow-hidden"
                            >
                              {CRON_PRESETS.map(p => (
                                <button
                                  key={p.cron}
                                  onClick={() => applyPreset(p.cron)}
                                  className={`flex w-full items-center justify-between px-3.5 py-2.5 text-sm transition-colors hover:bg-[#ecfeff] ${scheduleCron === p.cron ? 'bg-[#ecfeff] text-[#0891b2] font-medium' : 'text-black/60'}`}
                                >
                                  <span>{zh ? p.label : p.labelEn}</span>
                                  <code className="text-[10px] font-mono text-black/30">{p.cron}</code>
                                </button>
                              ))}
                            </motion.div>
                          )}
                        </AnimatePresence>
                      </div>

                      {/* 5-field cron editor */}
                      <div>
                        <div className="flex items-center gap-1.5 mb-1.5">
                          <Info size={11} className="text-black/25" />
                          <p className="text-[10px] text-black/30">{zh ? '标准 5 段 Cron：分 时 日 月 周' : '5-field Cron: min hour day month weekday'}</p>
                        </div>
                        <div className="grid grid-cols-5 gap-1.5">
                          {cronFields.map((val, i) => (
                            <div key={i}>
                              <label className="block text-[9px] font-bold uppercase tracking-wider text-black/30 mb-0.5">
                                {zh ? CRON_FIELD_LABELS_ZH[i] : CRON_FIELD_LABELS_EN[i]}
                              </label>
                              <input
                                value={val}
                                onChange={e => updateCronField(i, e.target.value)}
                                placeholder="*"
                                className="w-full rounded-lg border border-black/8 bg-[#f8fafc] px-2 py-1.5 text-center font-mono text-sm text-[#164e63] outline-none placeholder:text-black/20 focus:border-[#06b6d4]/40 focus:bg-white focus:ring-2 focus:ring-[#06b6d4]/10 transition-all"
                              />
                              <p className="mt-0.5 text-[8px] text-black/20 text-center truncate">
                                {zh ? CRON_FIELD_HINTS_ZH[i] : CRON_FIELD_HINTS_EN[i]}
                              </p>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Cron display line */}
                  <div className="flex items-center gap-3 mt-3 rounded-lg bg-[#0c4a6e]/[0.04] px-3 py-2">
                    <code className="flex-1 font-mono text-sm text-[#164e63] font-semibold">{scheduleCron}</code>
                    <span className="text-[11px] text-black/40">{describeCron(scheduleCron, zh)}</span>
                  </div>
                </div>

                {/* Retention */}
                <div className={`mt-4 pt-4 border-t border-black/5 transition-opacity ${scheduleEnabled ? '' : 'opacity-35 pointer-events-none'}`}>
                  <label className="block text-[10px] font-bold uppercase tracking-wider text-black/30 mb-1.5">{zh ? '保留周期' : 'Retention'}</label>
                  <div className="flex items-center gap-3">
                    <select
                      value={retentionDays}
                      onChange={e => onRetentionDaysChange(Number(e.target.value))}
                      title={zh ? '备份保留天数' : 'Retention days'}
                      className="rounded-xl border border-black/8 bg-[#f8fafc] px-3 py-2 text-sm outline-none focus:border-[#06b6d4]/40 focus:ring-2 focus:ring-[#06b6d4]/10 transition-all"
                    >
                      <option value={30}>30 {zh ? '天' : 'days'}</option>
                      <option value={90}>90 {zh ? '天' : 'days'}</option>
                      <option value={180}>180 {zh ? '天' : 'days'}</option>
                      <option value={365}>1 {zh ? '年' : 'year'}</option>
                      <option value={730}>2 {zh ? '年' : 'years'}</option>
                    </select>
                    <p className="text-[11px] text-black/30">{zh ? '超过期限自动清理' : 'Auto-removed when expired'}</p>
                  </div>
                </div>

                {/* Save button */}
                <div className="mt-4">
                  <button
                    onClick={() => void handleSave()}
                    disabled={scheduleLoading}
                    className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-xl bg-[#164e63] text-sm font-semibold text-white shadow-sm transition-all hover:bg-[#0c4a6e] disabled:opacity-45"
                  >
                    {scheduleLoading && <RotateCcw size={12} className="animate-spin" />}
                    {zh ? '应用策略' : 'Apply Policy'}
                  </button>
                </div>
              </div>
            </div>

            {/* Left: Stats + Chart + Timeline (2/3 width) */}
            <div className="xl:col-span-2 xl:order-1 space-y-3">
              {/* Stats Cards */}
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-2.5">
                <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}
                  className="rounded-xl bg-white border border-black/[0.06] p-3.5 shadow-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-black/35">{zh ? '总备份' : 'Total'}</span>
                    <Database size={13} className="text-[#06b6d4]/50" />
                  </div>
                  <p className="mt-1.5 text-2xl font-bold text-[#164e63] tabular-nums">{backupStats?.total_snapshots ?? '—'}</p>
                  <p className="text-[10px] text-black/30 mt-0.5">{zh ? '份配置快照' : 'config snapshots'}</p>
                </motion.div>

                <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}
                  className="rounded-xl bg-white border border-black/[0.06] p-3.5 shadow-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-black/35">{zh ? '设备覆盖' : 'Coverage'}</span>
                    <Server size={13} className="text-emerald-500/50" />
                  </div>
                  <p className="mt-1.5 text-2xl font-bold text-[#164e63] tabular-nums">
                    {backupStats?.device_stats?.filter(d => d.backup_count > 0).length ?? 0}
                    <span className="text-sm font-normal text-black/25">/{backupStats?.device_stats?.length ?? devices.length}</span>
                  </p>
                  <p className="text-[10px] text-black/30 mt-0.5">{zh ? '台设备已备份' : 'devices backed up'}</p>
                </motion.div>

                <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}
                  className="rounded-xl bg-white border border-black/[0.06] p-3.5 shadow-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-black/35">{zh ? '今日执行' : 'Today'}</span>
                    <TrendingUp size={13} className="text-amber-500/50" />
                  </div>
                  <p className="mt-1.5 text-2xl font-bold text-[#164e63] tabular-nums">{backupStats?.today?.total ?? 0}</p>
                  <p className="text-[10px] text-black/30 mt-0.5">
                    {zh ? `定时 ${backupStats?.today?.scheduled ?? 0} · 手动 ${backupStats?.today?.manual ?? 0}` : `Sched ${backupStats?.today?.scheduled ?? 0} · Manual ${backupStats?.today?.manual ?? 0}`}
                  </p>
                </motion.div>

                <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}
                  className="rounded-xl bg-white border border-black/[0.06] p-3.5 shadow-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-black/35">{zh ? '7日总量' : '7-Day'}</span>
                    <BarChart3 size={13} className="text-violet-500/50" />
                  </div>
                  <p className="mt-1.5 text-2xl font-bold text-[#164e63] tabular-nums">{sevenDayTotal}</p>
                  <p className="text-[10px] text-black/30 mt-0.5">{zh ? '近7日备份总数' : 'backups last 7 days'}</p>
                </motion.div>
              </div>

              {/* Chart + Timeline side by side */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                {/* 7-Day Trend Chart */}
                {chartData.length > 0 && (
                  <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.25 }}
                    className="rounded-2xl border border-black/[0.06] bg-white p-4 shadow-sm">
                    <h4 className="text-[10px] font-bold uppercase tracking-wider text-black/30 mb-3">{zh ? '7日备份趋势' : '7-Day Backup Trend'}</h4>
                    <div className="h-36">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={chartData} barGap={2}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                          <XAxis dataKey="label" tick={{ fontSize: 10, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                          <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} axisLine={false} tickLine={false} allowDecimals={false} width={28} />
                          <Tooltip content={renderTooltip} cursor={{ fill: 'rgba(6,182,212,0.04)' }} />
                          <Bar dataKey="scheduled" fill="#06b6d4" radius={[3, 3, 0, 0]} name="scheduled" />
                          <Bar dataKey="manual" fill="#8b5cf6" radius={[3, 3, 0, 0]} name="manual" />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                    <div className="flex items-center gap-4 mt-2 text-[10px]">
                      <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-sm bg-[#06b6d4]" />{zh ? '定时' : 'Scheduled'}</span>
                      <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-sm bg-violet-500" />{zh ? '手动' : 'Manual'}</span>
                    </div>
                  </motion.div>
                )}

                {/* Upcoming Executions Timeline */}
                <div className="rounded-2xl border border-black/[0.06] bg-white shadow-sm">
                  <div className="flex items-center justify-between border-b border-black/5 px-4 py-3">
                    <h3 className="text-xs font-bold text-[#164e63] flex items-center gap-1.5">
                      <Calendar size={13} className="text-[#06b6d4]" />
                      {zh ? '执行计划' : 'Upcoming'}
                    </h3>
                    <button
                      onClick={() => void loadPreview()}
                      disabled={previewLoading}
                      className="inline-flex h-6 items-center gap-1 rounded-md border border-black/8 bg-[#f8fafc] px-2 text-[10px] font-medium text-[#0e7490] transition-all hover:bg-white hover:border-[#06b6d4]/30"
                    >
                      <RotateCcw size={10} className={previewLoading ? 'animate-spin' : ''} />
                      {zh ? '刷新' : 'Refresh'}
                    </button>
                  </div>
                  <div className="px-4 py-2">
                    {previewLoading ? (
                      <div className="flex items-center justify-center py-6 text-black/30">
                        <RotateCcw size={14} className="animate-spin mr-2" />
                        <span className="text-xs">{zh ? '计算中...' : 'Computing...'}</span>
                      </div>
                    ) : !preview || !preview.enabled ? (
                      <div className="flex flex-col items-center py-6 text-black/25">
                        <Calendar size={22} strokeWidth={1} />
                        <p className="mt-2 text-xs font-medium">{zh ? '定时备份未启用' : 'Scheduled backup disabled'}</p>
                      </div>
                    ) : preview.upcoming.length === 0 ? (
                      <div className="flex flex-col items-center py-6 text-black/25">
                        <Calendar size={22} strokeWidth={1} />
                        <p className="mt-2 text-xs">{zh ? '暂无计划' : 'No upcoming runs'}</p>
                      </div>
                    ) : (
                      <div>
                        {(timelineExpanded ? preview.upcoming : preview.upcoming.slice(0, TIMELINE_PREVIEW)).map((iso, idx) => {
                          const { date, day, time } = formatPreviewTime(iso);
                          const rel = relativeTime(iso);
                          const isFirst = idx === 0;
                          const totalVisible = timelineExpanded ? preview.upcoming.length : Math.min(preview.upcoming.length, TIMELINE_PREVIEW);
                          return (
                            <div key={idx} className={`flex items-center gap-2 py-1.5 ${idx < totalVisible - 1 ? 'border-b border-black/[0.03]' : ''}`}>
                              <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${isFirst ? 'bg-[#06b6d4] shadow-[0_0_6px_rgba(6,182,212,0.4)]' : 'bg-black/10'}`} />
                              <span className={`font-mono text-[11px] flex-shrink-0 ${isFirst ? 'text-[#164e63] font-semibold' : 'text-black/55'}`}>{time}</span>
                              <span className="text-[10px] text-black/30 flex-shrink-0">{date}</span>
                              <span className="text-[10px] text-black/20 flex-shrink-0">{day}</span>
                              <span className="flex-1" />
                              <span className={`rounded-full px-1.5 py-px text-[9px] font-medium ${isFirst ? 'bg-[#ecfeff] text-[#0891b2]' : 'text-black/25'}`}>{rel}</span>
                            </div>
                          );
                        })}
                        {preview.upcoming.length > TIMELINE_PREVIEW && (
                          <button
                            onClick={() => setTimelineExpanded(v => !v)}
                            className="w-full mt-1 py-1 text-[10px] font-semibold text-[#0891b2] hover:text-[#06b6d4] transition-colors"
                          >
                            {timelineExpanded ? (zh ? '收起' : 'Collapse') : `${zh ? '查看全部' : 'Show all'} ${preview.upcoming.length} ${zh ? '条' : ''}`}
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                  {preview && preview.devices.length > 0 && (
                    <div className="border-t border-black/5 px-4 py-2.5">
                      <div className="flex flex-wrap gap-1">
                        {(scopeExpanded ? preview.devices : preview.devices.slice(0, SCOPE_PREVIEW_COUNT)).map(d => (
                          <span key={d.id} className="inline-flex items-center gap-1 rounded-md bg-black/[0.02] border border-black/[0.04] px-1.5 py-0.5 text-[9px]">
                            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 flex-shrink-0" />
                            <span className="font-medium text-[#164e63]">{d.hostname}</span>
                          </span>
                        ))}
                        {!scopeExpanded && preview.devices.length > SCOPE_PREVIEW_COUNT && (
                          <button
                            onClick={() => setScopeExpanded(true)}
                            className="inline-flex items-center rounded-md bg-[#ecfeff] border border-[#06b6d4]/15 px-1.5 py-0.5 text-[9px] font-semibold text-[#0891b2] hover:bg-[#cffafe] transition-colors"
                          >
                            +{preview.devices.length - SCOPE_PREVIEW_COUNT} {zh ? '更多' : 'more'}
                          </button>
                        )}
                        {scopeExpanded && preview.devices.length > SCOPE_PREVIEW_COUNT && (
                          <button
                            onClick={() => setScopeExpanded(false)}
                            className="inline-flex items-center rounded-md bg-black/[0.02] border border-black/[0.04] px-1.5 py-0.5 text-[9px] font-medium text-black/35 hover:bg-black/[0.04] transition-colors"
                          >
                            {zh ? '收起' : 'Less'}
                          </button>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* ── Device Backup Status Table ── */}
          {(backupStats?.device_stats?.length ?? 0) > 0 && (
            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}
              className="rounded-2xl border border-black/[0.06] bg-white shadow-sm overflow-hidden">
              <div className="flex items-center justify-between px-5 py-3 border-b border-black/5">
                <h3 className="text-sm font-bold text-[#164e63] flex items-center gap-2">
                  <Server size={14} className="text-[#06b6d4]" />
                  {zh ? '设备备份状态' : 'Device Backup Status'}
                  <span className="text-[10px] font-normal text-black/30">({backupStats?.device_stats?.length ?? 0})</span>
                </h3>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead>
                    <tr className="border-b border-black/5 bg-black/[0.015]">
                      <th className="px-4 py-2.5 text-[10px] font-bold uppercase tracking-wider text-black/35">{zh ? '设备' : 'Device'}</th>
                      <th className="px-4 py-2.5 text-[10px] font-bold uppercase tracking-wider text-black/35">{zh ? '状态' : 'Status'}</th>
                      <th className="px-4 py-2.5 text-[10px] font-bold uppercase tracking-wider text-black/35">{zh ? '平台' : 'Platform'}</th>
                      <th className="px-4 py-2.5 text-[10px] font-bold uppercase tracking-wider text-black/35">{zh ? '备份数' : 'Backups'}</th>
                      <th className="px-4 py-2.5 text-[10px] font-bold uppercase tracking-wider text-black/35">{zh ? '最近备份' : 'Latest'}</th>
                      <th className="px-4 py-2.5 text-[10px] font-bold uppercase tracking-wider text-black/35">{zh ? '触发方式' : 'Trigger'}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {displayDeviceStats.map(dev => (
                      <tr key={dev.id} className="border-b border-black/[0.03] hover:bg-black/[0.01] transition-colors">
                        <td className="px-4 py-2.5">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-semibold text-[#164e63]">{dev.hostname}</span>
                            <span className="text-[10px] text-black/25 font-mono">{dev.ip_address}</span>
                          </div>
                        </td>
                        <td className="px-4 py-2.5">
                          <span className={`inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full ${
                            dev.status === 'online' ? 'bg-emerald-50 text-emerald-600' : 'bg-red-50 text-red-500'
                          }`}>
                            <span className={`w-1.5 h-1.5 rounded-full ${dev.status === 'online' ? 'bg-emerald-500' : 'bg-red-400'}`} />
                            {dev.status === 'online' ? (zh ? '在线' : 'Online') : (zh ? '离线' : 'Offline')}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 text-[11px] text-black/40">{getVendorFromPlatform(dev.platform)}</td>
                        <td className="px-4 py-2.5">
                          <span className={`text-xs font-bold tabular-nums px-2 py-0.5 rounded-full ${
                            dev.backup_count > 0 ? 'bg-black/[0.03] text-[#164e63]' : 'bg-red-50 text-red-400'
                          }`}>
                            {dev.backup_count}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 text-[11px] text-black/45 font-mono">
                          {dev.latest_backup ? new Date(dev.latest_backup).toLocaleString(zh ? 'zh-CN' : 'en-US', { hour12: false }) : '—'}
                        </td>
                        <td className="px-4 py-2.5">
                          {dev.last_trigger ? (
                            <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${
                              dev.last_trigger === 'scheduled' ? 'bg-cyan-50 text-cyan-600' : 'bg-violet-50 text-violet-600'
                            }`}>
                              {dev.last_trigger === 'scheduled' ? (zh ? '定时' : 'Sched') : dev.last_trigger === 'manual' ? (zh ? '手动' : 'Manual') : dev.last_trigger}
                            </span>
                          ) : <span className="text-black/20">—</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {(backupStats?.device_stats?.length ?? 0) > DEVICE_PAGE_SIZE && (
                <div className="px-4 py-3 border-t border-black/5">
                  <Pagination
                    currentPage={devicePage}
                    totalItems={backupStats?.device_stats?.length ?? 0}
                    onPageChange={setDevicePage}
                    itemsPerPage={DEVICE_PAGE_SIZE}
                    language={language}
                  />
                </div>
              )}
            </motion.div>
          )}

          {/* ── Recent Execution Log ── */}
          {backupStats?.recent_backups && backupStats.recent_backups.length > 0 && (
            <div className="rounded-2xl border border-black/[0.06] bg-white shadow-sm overflow-hidden">
              <div className="px-5 py-3 border-b border-black/5">
                <h3 className="text-sm font-bold text-[#164e63] flex items-center gap-2">
                  <Activity size={14} className="text-[#06b6d4]" />
                  {zh ? '最近执行记录' : 'Recent Executions'}
                  <span className="text-[10px] font-normal text-black/30">({zh ? '最近 5 条' : 'last 5'})</span>
                </h3>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead>
                    <tr className="border-b border-black/5 bg-black/[0.015]">
                      <th className="px-4 py-2.5 text-[10px] font-bold uppercase tracking-wider text-black/35">{zh ? '时间' : 'Time'}</th>
                      <th className="px-4 py-2.5 text-[10px] font-bold uppercase tracking-wider text-black/35">{zh ? '设备' : 'Device'}</th>
                      <th className="px-4 py-2.5 text-[10px] font-bold uppercase tracking-wider text-black/35">{zh ? '厂商' : 'Vendor'}</th>
                      <th className="px-4 py-2.5 text-[10px] font-bold uppercase tracking-wider text-black/35">{zh ? '触发' : 'Trigger'}</th>
                      <th className="px-4 py-2.5 text-[10px] font-bold uppercase tracking-wider text-black/35">{zh ? '操作者' : 'Author'}</th>
                      <th className="px-4 py-2.5 text-[10px] font-bold uppercase tracking-wider text-black/35">{zh ? '大小' : 'Size'}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {backupStats.recent_backups.slice(0, 5).map(bk => (
                      <tr key={bk.id} className="border-b border-black/[0.03] hover:bg-black/[0.01] transition-colors">
                        <td className="px-4 py-2 text-[11px] text-black/50 font-mono">
                          {new Date(bk.timestamp).toLocaleString(zh ? 'zh-CN' : 'en-US', { hour12: false })}
                        </td>
                        <td className="px-4 py-2 text-xs font-medium text-[#164e63]">{bk.hostname}</td>
                        <td className="px-4 py-2 text-[11px] text-black/40">{bk.vendor}</td>
                        <td className="px-4 py-2">
                          <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${
                            bk.trigger === 'scheduled' ? 'bg-cyan-50 text-cyan-600' : 'bg-violet-50 text-violet-600'
                          }`}>
                            {bk.trigger === 'scheduled' ? (zh ? '定时' : 'Sched') : bk.trigger === 'manual' ? (zh ? '手动' : 'Manual') : bk.trigger}
                          </span>
                        </td>
                        <td className="px-4 py-2 text-[11px] text-black/40">{bk.author || '—'}</td>
                        <td className="px-4 py-2 text-[11px] text-black/40 tabular-nums">{fmtSize(bk.size)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
    </div>
  );
};

export default ConfigScheduleTab;
