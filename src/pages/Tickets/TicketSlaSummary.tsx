import React from 'react';
import { Clock3 } from 'lucide-react';
import { ticketSurfaceClass } from '../../components/tickets/TicketUI';
import type { TicketSlaClock, TicketSlaSummary as TicketSlaSummaryData } from './types';

interface TicketSlaSummaryProps {
  sla?: TicketSlaSummaryData | null;
  language: string;
}

const dateText = (value: string | null | undefined, timezone?: string | null, locale = 'en-US'): string => {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  try {
    return new Intl.DateTimeFormat(locale, {
      ...(timezone ? { timeZone: timezone } : {}),
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(date);
  } catch {
    return date.toLocaleString(locale);
  }
};

const clockLabel = (kind: string, zh: boolean): string => ({
  response: zh ? '首次响应' : 'First response',
  restore: zh ? '故障恢复' : 'Restoration',
  fulfillment: zh ? '申请履约' : 'Fulfillment',
}[kind] || kind);

const stateLabel = (status: string, zh: boolean): string => ({
  running: zh ? '计时中' : 'Running',
  paused: zh ? '已暂停' : 'Paused',
  met: zh ? '已达成' : 'Met',
  breached: zh ? '已超时' : 'Breached',
  stopped: zh ? '已停止' : 'Stopped',
  not_configured: zh ? '未配置时限' : 'No target configured',
}[status] || status);

const stateTone = (status: string): string => {
  if (status === 'breached') return 'bg-[var(--ui-danger-subtle)] text-[var(--ui-danger)]';
  if (status === 'met') return 'bg-[var(--ui-success-subtle)] text-[var(--ui-success)]';
  if (status === 'paused') return 'bg-[var(--ui-warning-subtle)] text-[var(--ui-warning)]';
  return 'bg-[var(--ui-surface-muted)] text-[var(--ui-fg-muted)]';
};

const SlaClock: React.FC<{ clock: TicketSlaClock; zh: boolean }> = ({ clock, zh }) => {
  const remainingMinutes = clock.remaining_seconds == null
    ? null
    : Math.max(0, Math.ceil(clock.remaining_seconds / 60));
  const status = clock.configured ? stateLabel(clock.status, zh) : (zh ? '未配置时限' : 'No target configured');

  return (
    <div className="min-w-0 border-t border-[var(--ui-border)] py-2 first:border-t-0 first:pt-0 sm:first:border-t sm:first:pt-2">
      <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
        <span className="text-[var(--ui-text-label)] font-semibold text-[var(--ui-fg)]">{clockLabel(clock.kind, zh)}</span>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-[var(--ui-text-caption)] font-medium ${stateTone(clock.configured ? clock.status : 'not_configured')}`}>{status}</span>
      </div>
      {clock.configured && (
        <p className="mt-1 break-words text-[var(--ui-text-caption)] leading-4 text-[var(--ui-fg-muted)]">
          {zh ? '截止' : 'Due'}：{dateText(clock.deadline_at, clock.calendar_timezone, zh ? 'zh-CN' : 'en-US')}
          {remainingMinutes != null && <span className="ml-2 tabular-nums">{zh ? `剩余 ${remainingMinutes} 分钟` : `${remainingMinutes} min remaining`}</span>}
          {clock.calendar_timezone && <span className="ml-2">{clock.calendar_timezone}</span>}
        </p>
      )}
    </div>
  );
};

const TicketSlaSummary: React.FC<TicketSlaSummaryProps> = ({ sla, language }) => {
  const zh = language === 'zh';
  const clocks = sla?.clocks || [];
  const hasConfiguredTargets = Boolean(sla?.configured && clocks.some((clock) => clock.configured));

  return (
    <section aria-label={zh ? '工单服务时限' : 'Ticket service targets'} className={`${ticketSurfaceClass} px-3 py-2.5`}>
      <div className="flex items-center gap-2">
        <Clock3 size={14} className="shrink-0 text-[var(--ui-fg-muted)]" aria-hidden="true" />
        <h3 className="text-[var(--ui-text-label)] font-semibold text-[var(--ui-fg)]">{zh ? '服务时限' : 'Service targets'}</h3>
        {!hasConfiguredTargets && <span className="ml-auto text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">{zh ? '未配置' : 'Not configured'}</span>}
      </div>
      {clocks.length > 0 ? (
        <div className="mt-1 grid gap-x-4 sm:grid-cols-2 lg:grid-cols-3">
          {clocks.map((clock, index) => <SlaClock key={`${clock.kind}-${index}`} clock={clock} zh={zh} />)}
        </div>
      ) : (
        <p className="mt-1 text-[var(--ui-text-caption)] leading-4 text-[var(--ui-fg-muted)]">{zh ? '未配置时限' : 'No target configured'}</p>
      )}
    </section>
  );
};

export default TicketSlaSummary;
