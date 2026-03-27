import React from 'react';
import type { DeviceConnectionCheckSummary } from '../../types';

/* ─── Config ─── */
const STATUS_CFG = {
  online:  { dot: 'bg-emerald-500', text: 'text-emerald-600 dark:text-emerald-400', ping: true,  labelZh: '在线',   labelEn: 'Online' },
  offline: { dot: 'bg-red-500',     text: 'text-red-500 dark:text-red-400',         ping: false, labelZh: '离线',   labelEn: 'Offline' },
  pending: { dot: 'bg-amber-500',   text: 'text-amber-600 dark:text-amber-400',     ping: false, labelZh: '等待中', labelEn: 'Pending' },
} as const;

const HEALTH_CFG: Record<string, { bg: string; border: string; text: string; labelZh: string; labelEn: string }> = {
  healthy:  { bg: 'bg-emerald-500/10', border: 'border-emerald-500/20', text: 'text-emerald-600 dark:text-emerald-400', labelZh: '健康', labelEn: 'Healthy' },
  warning:  { bg: 'bg-amber-500/10',   border: 'border-amber-500/20',  text: 'text-amber-600 dark:text-amber-400',     labelZh: '警告', labelEn: 'Warning' },
  critical: { bg: 'bg-red-500/10',     border: 'border-red-500/20',    text: 'text-red-600 dark:text-red-400',         labelZh: '严重', labelEn: 'Critical' },
  unknown:  { bg: 'bg-slate-500/10',   border: 'border-slate-500/20',  text: 'text-slate-500 dark:text-slate-400',     labelZh: '未知', labelEn: 'Unknown' },
};

const CHECK_BADGE: Record<DeviceConnectionCheckSummary['status'], { zh: string; en: string; cls: string }> = {
  ok:            { zh: 'OK',            en: 'OK',           cls: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20' },
  tcp_fail:      { zh: 'TCP 失败',      en: 'TCP Fail',     cls: 'bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/20' },
  ssh_auth_fail: { zh: 'SSH 认证失败',  en: 'SSH Auth Fail', cls: 'bg-rose-500/10 text-rose-600 dark:text-rose-400 border-rose-500/20' },
  ssh_timeout:   { zh: 'SSH 超时',      en: 'SSH Timeout',   cls: 'bg-orange-500/10 text-orange-600 dark:text-orange-400 border-orange-500/20' },
  ssh_transport: { zh: 'SSH 传输',      en: 'SSH Transport',  cls: 'bg-slate-500/10 text-slate-500 dark:text-slate-400 border-slate-500/20' },
  ssh_legacy:    { zh: '旧SSH',         en: 'Legacy SSH',    cls: 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20' },
  fail:          { zh: '失败',          en: 'Fail',          cls: 'bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/20' },
};

const formatCheckTime = (value: string, language: string) => {
  try {
    return new Date(value).toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US', {
      month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
    });
  } catch { return value; }
};

/* ─── Props ─── */
interface StatusBadgeProps {
  status: string;
  healthStatus?: string;
  uptime?: string;
  connectionCheck?: DeviceConnectionCheckSummary;
  language: string;
}

/* ─── Component ─── */
const StatusBadge: React.FC<StatusBadgeProps> = ({
  status, healthStatus, uptime, connectionCheck, language,
}) => {
  const zh = language === 'zh';
  const st = STATUS_CFG[status as keyof typeof STATUS_CFG] || STATUS_CFG.pending;
  const health = HEALTH_CFG[healthStatus || 'unknown'] || HEALTH_CFG.unknown;
  const chkBadge = connectionCheck ? (CHECK_BADGE[connectionCheck.status] || CHECK_BADGE.fail) : null;

  return (
    <div className="space-y-1">
      {/* Status dot + label */}
      <div className="flex items-center gap-1.5">
        <span className="relative flex h-[7px] w-[7px]">
          {st.ping && (
            <span className={`animate-ping absolute inline-flex h-full w-full rounded-full ${st.dot} opacity-60`} />
          )}
          <span className={`relative inline-flex rounded-full h-[7px] w-[7px] ${st.dot}`} />
        </span>
        <span className={`text-[10px] font-bold uppercase ${st.text}`}>
          {zh ? st.labelZh : st.labelEn}
        </span>
      </div>

      {/* Health severity badge */}
      <span className={`inline-flex items-center px-1.5 py-0.5 rounded border text-[9px] font-bold uppercase
        ${health.bg} ${health.border} ${health.text}`}>
        {zh ? health.labelZh : health.labelEn}
      </span>

      {/* Uptime */}
      {uptime && (
        <span className="block text-[9px] text-black/25 dark:text-white/20 font-mono" title={uptime}>
          ⏱ {uptime.length > 20 ? uptime.slice(0, 20) + '…' : uptime}
        </span>
      )}

      {/* Connection check result */}
      {chkBadge && (
        <span
          className={`inline-flex items-center px-1.5 py-0.5 rounded border text-[8px] font-bold ${chkBadge.cls}`}
          title={connectionCheck?.checked_at ? formatCheckTime(connectionCheck.checked_at, language) : ''}
        >
          {zh ? chkBadge.zh : chkBadge.en}
        </span>
      )}
    </div>
  );
};

export default StatusBadge;
export { STATUS_CFG, HEALTH_CFG, CHECK_BADGE, formatCheckTime };
