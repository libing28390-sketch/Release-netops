import React, { useEffect, useState, useCallback } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Database, RotateCcw, Calendar, Clock, Server, ChevronDown, Play, Info, Zap } from 'lucide-react';
import type { ConfigSnapshot, Device } from '../types';

/* ─────────── Cron Presets ─────────── */
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

/* ─────────── Types ─────────── */
interface UpcomingDevice {
  id: string;
  hostname: string;
  ip_address: string;
  platform: string;
  status: string;
}

interface PreviewData {
  enabled: boolean;
  cron: string;
  upcoming: string[];
  devices: UpcomingDevice[];
  device_count: number;
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

/* ─────────── Component ─────────── */
const ConfigScheduleTab: React.FC<ConfigScheduleTabProps> = ({
  t,
  language,
  devices,
  configSnapshots,
  isTakingSnapshot,
  scheduleEnabled,
  scheduleCron,
  scheduleLoading,
  retentionDays,
  getVendorFromPlatform,
  onToggleScheduleEnabled,
  onCronChange,
  onRetentionDaysChange,
  onSaveSchedule,
  onRunBackupNow,
  showToast,
}) => {
  const zh = language === 'zh';
  const onlineDeviceCount = devices.filter((d) => d.status === 'online').length;

  // Cron fields
  const cronParts = scheduleCron.split(/\s+/);
  const cronFields = [
    cronParts[0] ?? '0',
    cronParts[1] ?? '*',
    cronParts[2] ?? '*',
    cronParts[3] ?? '*',
    cronParts[4] ?? '*',
  ];

  const updateCronField = (index: number, value: string) => {
    const parts = [...cronFields];
    parts[index] = value || '*';
    onCronChange(parts.join(' '));
  };

  // Preview data
  const [preview, setPreview] = useState<PreviewData | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [presetOpen, setPresetOpen] = useState(false);

  const loadPreview = useCallback(async () => {
    setPreviewLoading(true);
    try {
      const resp = await fetch('/api/configs/schedule/preview?n=10');
      if (resp.ok) {
        setPreview(await resp.json());
      }
    } catch { /* ignore */ }
    finally { setPreviewLoading(false); }
  }, []);

  useEffect(() => { void loadPreview(); }, [loadPreview]);

  const handleSave = async () => {
    await onSaveSchedule();
    void loadPreview();
  };

  const applyPreset = (cron: string) => {
    onCronChange(cron);
    setPresetOpen(false);
  };

  // Human-readable description
  const describeCron = (cron: string): string => {
    const parts = cron.split(/\s+/);
    if (parts.length < 5) return cron;
    const [min, hour, day, month, dow] = parts;

    if (day === '*' && month === '*' && dow === '*') {
      if (hour.startsWith('*/')) return zh ? `每 ${hour.slice(2)} 小时的第 ${min} 分钟` : `Every ${hour.slice(2)}h at :${min.padStart(2, '0')}`;
      if (hour === '*') return zh ? `每小时的第 ${min} 分钟` : `Hourly at :${min.padStart(2, '0')}`;
      return zh ? `每天 ${hour.padStart(2, '0')}:${min.padStart(2, '0')}` : `Daily at ${hour.padStart(2, '0')}:${min.padStart(2, '0')}`;
    }
    if (day === '*' && month === '*' && dow === '1-5') {
      return zh ? `工作日 ${hour.padStart(2, '0')}:${min.padStart(2, '0')}` : `Weekdays at ${hour.padStart(2, '0')}:${min.padStart(2, '0')}`;
    }
    if (day === '*' && month === '*') {
      const dowMap: Record<string, string> = zh
        ? { '0': '周日', '1': '周一', '2': '周二', '3': '周三', '4': '周四', '5': '周五', '6': '周六' }
        : { '0': 'Sun', '1': 'Mon', '2': 'Tue', '3': 'Wed', '4': 'Thu', '5': 'Fri', '6': 'Sat' };
      const dayName = dowMap[dow] || (zh ? `星期${dow}` : `DoW ${dow}`);
      return zh ? `每${dayName} ${hour.padStart(2, '0')}:${min.padStart(2, '0')}` : `Every ${dayName} at ${hour.padStart(2, '0')}:${min.padStart(2, '0')}`;
    }
    if (month === '*' && dow === '*') {
      return zh ? `每月 ${day} 日 ${hour.padStart(2, '0')}:${min.padStart(2, '0')}` : `${day}th of month at ${hour.padStart(2, '0')}:${min.padStart(2, '0')}`;
    }
    return cron;
  };

  const formatPreviewTime = (iso: string) => {
    try {
      const d = new Date(iso);
      const pad = (v: number) => String(v).padStart(2, '0');
      const dayNames = zh
        ? ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
        : ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
      return {
        date: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`,
        day: dayNames[d.getDay()],
        time: `${pad(d.getHours())}:${pad(d.getMinutes())}`,
      };
    } catch {
      return { date: iso, day: '', time: '' };
    }
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

  return (
    <div className="space-y-3">
      {/* ── 页头（紧凑） ── */}
      <div className="rounded-2xl border border-black/5 bg-white shadow-sm">
        <div className="flex items-center justify-between px-5 py-3">
          <div className="flex items-center gap-4">
            <div>
              <h2 className="text-lg font-semibold text-[#164e63]">{zh ? '备份计划' : 'Backup Schedule'}</h2>
              <p className="text-[11px] text-black/40">{zh ? 'Cron 定时 · 自动备份在线设备' : 'Cron-based auto-backup for online devices'}</p>
            </div>
            <div className="hidden lg:flex items-center gap-4 ml-4 text-xs text-black/45">
              <div className="flex items-center gap-1.5">
                <div className={`h-2 w-2 rounded-full ${scheduleEnabled ? 'bg-emerald-500 shadow-[0_0_5px_rgba(16,185,129,0.45)]' : 'bg-black/15'}`} />
                <span>{scheduleEnabled ? (zh ? '已启用' : 'On') : (zh ? '已禁用' : 'Off')}</span>
              </div>
              <span className="text-black/15">|</span>
              <div className="flex items-center gap-1">
                <Clock size={11} />
                <code className="text-[10px] text-[#164e63]">{scheduleCron}</code>
                <span className="text-black/30">({describeCron(scheduleCron)})</span>
              </div>
              <span className="text-black/15">|</span>
              <span><Server size={11} className="inline -mt-px mr-0.5" />{onlineDeviceCount} {zh ? '在线' : 'online'}</span>
              <span className="text-black/15">|</span>
              <span><Database size={11} className="inline -mt-px mr-0.5" />{configSnapshots.length} {zh ? '备份' : 'snaps'}</span>
            </div>
          </div>
          <button
            onClick={() => void onRunBackupNow()}
            disabled={isTakingSnapshot}
            className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#06b6d4] px-3.5 text-xs font-semibold text-white shadow-sm transition-all hover:bg-[#0891b2] disabled:opacity-45"
          >
            {isTakingSnapshot ? <RotateCcw size={12} className="animate-spin" /> : <Play size={12} />}
            {zh ? '立即备份' : 'Run Now'}
          </button>
        </div>
      </div>

      {/* ── 主区域: 左编辑 + 右预览 ── */}
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-5">
        {/* 左侧: Cron 编辑器 */}
        <div className="xl:col-span-2 space-y-3">
          <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between pb-4 border-b border-black/5">
              <div>
                <h3 className="text-sm font-bold text-[#164e63]">{zh ? '启用定时备份' : 'Enable Scheduled Backup'}</h3>
                <p className="text-[11px] text-black/35 mt-0.5">{zh ? '开启后按计划自动备份所有在线设备' : 'Auto-backup all online devices on schedule'}</p>
              </div>
              <button
                onClick={onToggleScheduleEnabled}
                title={scheduleEnabled ? (zh ? '关闭' : 'Disable') : (zh ? '开启' : 'Enable')}
                className={`relative w-12 h-[26px] rounded-full transition-colors duration-200 ${scheduleEnabled ? 'bg-[#06b6d4]' : 'bg-black/10'}`}
              >
                <span className={`absolute top-[3px] left-[3px] w-5 h-5 bg-white rounded-full shadow-sm transition-transform duration-200 ${scheduleEnabled ? 'translate-x-[22px]' : ''}`} />
              </button>
            </div>

            {/* 快速预设 */}
            <div className="mt-4">
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
                      {CRON_PRESETS.map((p) => (
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
            </div>

            {/* Cron 5 段编辑 */}
            <div className={`mt-4 space-y-2 transition-opacity ${scheduleEnabled ? '' : 'opacity-35 pointer-events-none'}`}>
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
                      onChange={(e) => updateCronField(i, e.target.value)}
                      placeholder="*"
                      className="w-full rounded-lg border border-black/8 bg-[#f8fafc] px-2 py-1.5 text-center font-mono text-sm text-[#164e63] outline-none placeholder:text-black/20 focus:border-[#06b6d4]/40 focus:bg-white focus:ring-2 focus:ring-[#06b6d4]/10 transition-all"
                    />
                    <p className="mt-0.5 text-[8px] text-black/20 text-center truncate">
                      {zh ? CRON_FIELD_HINTS_ZH[i] : CRON_FIELD_HINTS_EN[i]}
                    </p>
                  </div>
                ))}
              </div>

              {/* 完整表达式展示 */}
              <div className="flex items-center gap-3 rounded-lg bg-[#0c4a6e]/[0.04] px-3 py-2">
                <code className="flex-1 font-mono text-sm text-[#164e63] font-semibold">{scheduleCron}</code>
                <span className="text-[11px] text-black/40">{describeCron(scheduleCron)}</span>
              </div>
            </div>

            {/* 保留周期 */}
            <div className={`mt-4 pt-4 border-t border-black/5 transition-opacity ${scheduleEnabled ? '' : 'opacity-35 pointer-events-none'}`}>
              <label className="block text-[10px] font-bold uppercase tracking-wider text-black/30 mb-1.5">{zh ? '保留周期' : 'Retention'}</label>
              <div className="flex items-center gap-3">
                <select
                  value={retentionDays}
                  onChange={(e) => onRetentionDaysChange(Number(e.target.value))}
                  title={zh ? '备份保留天数' : 'Retention days'}
                  className="rounded-xl border border-black/8 bg-[#f8fafc] px-3 py-2 text-sm outline-none focus:border-[#06b6d4]/40 focus:ring-2 focus:ring-[#06b6d4]/10 transition-all"
                >
                  <option value={30}>30 {zh ? '天' : 'days'}</option>
                  <option value={90}>90 {zh ? '天' : 'days'}</option>
                  <option value={180}>180 {zh ? '天' : 'days'}</option>
                  <option value={365}>1 {zh ? '年' : 'year'}</option>
                  <option value={730}>2 {zh ? '年' : 'years'}</option>
                </select>
                <p className="text-[11px] text-black/30">{zh ? '超过期限的快照将自动清理' : 'Expired snapshots auto-removed'}</p>
              </div>
            </div>

            {/* 保存按钮 */}
            <div className="mt-4">
              <button
                onClick={() => void handleSave()}
                disabled={scheduleLoading}
                className="inline-flex h-9 items-center justify-center gap-2 rounded-xl bg-[#164e63] px-5 text-sm font-semibold text-white shadow-sm transition-all hover:bg-[#0c4a6e] disabled:opacity-45"
              >
                {scheduleLoading && <RotateCcw size={12} className="animate-spin" />}
                {zh ? '保存计划' : 'Save Schedule'}
              </button>
            </div>
          </div>
        </div>

        {/* 右侧: 未来 10 次执行预览 */}
        <div className="xl:col-span-3">
          <div className="rounded-2xl border border-black/5 bg-white shadow-sm">
            <div className="flex items-center justify-between border-b border-black/5 px-5 py-3">
              <h3 className="text-sm font-bold text-[#164e63] flex items-center gap-2">
                <Calendar size={14} className="text-[#06b6d4]" />
                {zh ? '未来执行计划' : 'Upcoming Executions'}
                <span className="text-[10px] font-normal text-black/30">
                  ({zh ? '未来 10 次' : 'next 10'})
                </span>
              </h3>
              <button
                onClick={() => void loadPreview()}
                disabled={previewLoading}
                className="inline-flex h-7 items-center gap-1 rounded-lg border border-black/8 bg-[#f8fafc] px-2.5 text-[11px] font-medium text-[#0e7490] transition-all hover:bg-white hover:border-[#06b6d4]/30"
              >
                <RotateCcw size={11} className={previewLoading ? 'animate-spin' : ''} />
                {zh ? '刷新' : 'Refresh'}
              </button>
            </div>

            {/* 执行时间线 */}
            <div className="px-5 py-2">
              {previewLoading ? (
                <div className="flex items-center justify-center py-8 text-black/30">
                  <RotateCcw size={14} className="animate-spin mr-2" />
                  <span className="text-xs">{zh ? '计算中...' : 'Computing...'}</span>
                </div>
              ) : !preview || !preview.enabled ? (
                <div className="flex flex-col items-center py-8 text-black/25">
                  <Calendar size={24} strokeWidth={1} />
                  <p className="mt-2 text-xs font-medium">{zh ? '定时备份未启用' : 'Scheduled backup disabled'}</p>
                </div>
              ) : preview.upcoming.length === 0 ? (
                <div className="flex flex-col items-center py-8 text-black/25">
                  <Calendar size={24} strokeWidth={1} />
                  <p className="mt-2 text-xs">{zh ? '暂无计划' : 'No upcoming runs'}</p>
                </div>
              ) : (
                <div>
                  {preview.upcoming.map((iso, idx) => {
                    const { date, day, time } = formatPreviewTime(iso);
                    const rel = relativeTime(iso);
                    const isFirst = idx === 0;
                    return (
                      <div key={idx} className={`flex items-center gap-3 py-1.5 ${idx < preview.upcoming.length - 1 ? 'border-b border-black/[0.03]' : ''}`}>
                        {/* 圆点 */}
                        <div className={`w-2 h-2 rounded-full flex-shrink-0 ${isFirst ? 'bg-[#06b6d4] shadow-[0_0_6px_rgba(6,182,212,0.4)]' : 'bg-black/10'}`} />
                        {/* 序号 */}
                        <span className={`w-5 text-center text-[10px] font-bold flex-shrink-0 ${isFirst ? 'text-[#0891b2]' : 'text-black/25'}`}>
                          {idx + 1}
                        </span>
                        {/* 时间 */}
                        <span className={`font-mono text-xs w-11 flex-shrink-0 ${isFirst ? 'text-[#164e63] font-semibold' : 'text-black/55'}`}>{time}</span>
                        {/* 日期 + 星期 */}
                        <span className="text-[11px] text-black/35 flex-shrink-0">{date}</span>
                        <span className="text-[10px] text-black/25 flex-shrink-0 w-7">{day}</span>
                        {/* 撑开 */}
                        <span className="flex-1" />
                        {/* 倒计时 */}
                        <span className={`rounded-full px-1.5 py-px text-[9px] font-medium ${isFirst ? 'bg-[#ecfeff] text-[#0891b2]' : 'text-black/25'}`}>
                          {rel}
                        </span>
                        {/* 设备数 */}
                        <span className="text-[9px] text-black/20 w-12 text-right flex-shrink-0">
                          {preview.device_count} {zh ? '台' : 'dev'}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* 设备清单 */}
            {preview && preview.devices.length > 0 && (
              <div className="border-t border-black/5 px-5 py-3">
                <h4 className="text-[9px] font-bold uppercase tracking-widest text-black/30 mb-2">
                  {zh ? '备份涉及设备' : 'Devices in Scope'}
                </h4>
                <div className="flex flex-wrap gap-1">
                  {preview.devices.map((d) => (
                    <span key={d.id} className="inline-flex items-center gap-1.5 rounded-lg bg-black/[0.02] border border-black/[0.04] px-2 py-1 text-[10px]">
                      <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 flex-shrink-0" />
                      <span className="font-medium text-[#164e63]">{d.hostname}</span>
                      <span className="font-mono text-black/25">{d.ip_address}</span>
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* 设备备份统计 */}
          <div className="mt-3 rounded-2xl border border-black/5 bg-white px-5 py-4 shadow-sm">
            <h3 className="text-[9px] font-bold uppercase tracking-widest text-black/30 mb-2">
              {zh ? '设备备份概况' : 'Device Backup Overview'}
            </h3>
            <div>
              {devices.map((device) => {
                const count = configSnapshots.filter((s) => s.device_id === device.id).length;
                const latest = configSnapshots.find((s) => s.device_id === device.id);
                return (
                  <div key={device.id} className="flex items-center justify-between py-1.5 border-b border-black/[0.03] last:border-0">
                    <div className="flex items-center gap-1.5">
                      <div className={`w-1.5 h-1.5 rounded-full ${device.status === 'online' ? 'bg-emerald-500' : 'bg-red-400'}`} />
                      <span className="text-[11px] font-medium text-[#164e63]">{device.hostname}</span>
                      <span className="text-[9px] text-black/25">{getVendorFromPlatform(device.platform)}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] text-black/30">{latest ? new Date(latest.timestamp).toLocaleString() : '—'}</span>
                      <span className={`text-[10px] font-bold px-1.5 py-px rounded-full ${count > 0 ? 'bg-black/[0.03] text-black/50' : 'bg-red-50 text-red-400'}`}>
                        {count}
                      </span>
                    </div>
                  </div>
                );
              })}
              {devices.length === 0 && (
                <p className="text-center text-xs text-black/25 py-6">{zh ? '暂无设备' : 'No devices'}</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ConfigScheduleTab;