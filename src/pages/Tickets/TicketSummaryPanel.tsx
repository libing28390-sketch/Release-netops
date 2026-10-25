import React, { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronUp, LoaderCircle } from 'lucide-react';
import { ActionButton } from '../../components/ui/ActionIconButton';
import { ticketInputClass, ticketLabelClass, ticketSurfaceClass } from '../../components/tickets/TicketUI';
import { getTicketSummary, TicketApiError } from './api';
import type { TicketSummaryResponse } from './types';

interface TicketSummaryPanelProps {
  language: string;
  refreshKey?: number;
}

interface DateRange {
  from: string;
  to: string;
}

const dateInputValue = (date: Date): string => date.toISOString().slice(0, 10);

const defaultDateRange = (): DateRange => {
  const end = new Date();
  const start = new Date(end);
  start.setUTCDate(start.getUTCDate() - 29);
  return { from: dateInputValue(start), to: dateInputValue(end) };
};

const rangeDays = ({ from, to }: DateRange): number => {
  const start = Date.parse(`${from}T00:00:00Z`);
  const end = Date.parse(`${to}T00:00:00Z`);
  return Number.isFinite(start) && Number.isFinite(end) ? Math.floor((end - start) / 86400000) + 1 : 0;
};

const formatDuration = (seconds: number, zh: boolean): string => {
  const safeSeconds = Math.max(0, Math.round(seconds));
  if (safeSeconds < 60) return zh ? '不足 1 分钟' : '< 1 min';
  const totalMinutes = Math.round(safeSeconds / 60);
  if (totalMinutes < 60) return zh ? `${totalMinutes} 分钟` : `${totalMinutes} min`;
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours < 24) return zh ? `${hours} 小时${minutes ? ` ${minutes} 分钟` : ''}` : `${hours}h${minutes ? ` ${minutes}m` : ''}`;
  const days = Math.floor(hours / 24);
  const remainingHours = hours % 24;
  return zh ? `${days} 天${remainingHours ? ` ${remainingHours} 小时` : ''}` : `${days}d${remainingHours ? ` ${remainingHours}h` : ''}`;
};

const countText = (value: number, zh: boolean): string => zh ? `${value} 条` : String(value);

const metricLabel = (metric: 'first_response' | 'incident_restore' | 'service_fulfillment' | 'close', zh: boolean): string => ({
  first_response: zh ? '首次响应平均耗时' : 'Average first response',
  incident_restore: zh ? '故障恢复平均耗时' : 'Average incident restoration',
  service_fulfillment: zh ? '申请履约平均耗时' : 'Average service fulfillment',
  close: zh ? '关闭平均耗时' : 'Average time to close',
}[metric]);

const TicketSummaryPanel: React.FC<TicketSummaryPanelProps> = ({ language, refreshKey = 0 }) => {
  const zh = language === 'zh';
  const initialRange = useMemo(defaultDateRange, []);
  const [draftFrom, setDraftFrom] = useState(initialRange.from);
  const [draftTo, setDraftTo] = useState(initialRange.to);
  const [appliedRange, setAppliedRange] = useState(initialRange);
  const [expanded, setExpanded] = useState(false);
  const [summary, setSummary] = useState<TicketSummaryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [permissionDenied, setPermissionDenied] = useState(false);

  useEffect(() => {
    if (!expanded) return undefined;
    const controller = new AbortController();
    setLoading(true);
    setError('');
    setPermissionDenied(false);
    void getTicketSummary(appliedRange.from, appliedRange.to, controller.signal).then((result) => {
      if (!controller.signal.aborted) setSummary(result);
    }).catch((cause: unknown) => {
      if (controller.signal.aborted) return;
      setError(cause instanceof Error ? cause.message : (zh ? '工单统计加载失败' : 'Unable to load ticket summary'));
      setPermissionDenied(cause instanceof TicketApiError && cause.status === 403);
      setSummary(null);
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [appliedRange, expanded, refreshKey, zh]);

  const submitRange = (event: React.FormEvent) => {
    event.preventDefault();
    const nextRange = { from: draftFrom, to: draftTo };
    if (!nextRange.from || !nextRange.to || nextRange.from > nextRange.to) {
      setError(zh ? '请选择有效的起止日期。' : 'Choose a valid date range.');
      return;
    }
    if (rangeDays(nextRange) > 366) {
      setError(zh ? '统计范围不能超过 366 天。' : 'The range cannot exceed 366 days.');
      return;
    }
    setError('');
    setAppliedRange(nextRange);
  };

  const metrics = summary ? [
    { label: zh ? '全部工单' : 'All tickets', value: summary.totals.all },
    { label: zh ? '故障工单' : 'Incidents', value: summary.totals.incident },
    { label: zh ? '服务申请' : 'Service requests', value: summary.totals.service_request },
    { label: zh ? '未关闭' : 'Active', value: summary.totals.active },
    { label: zh ? '已关闭' : 'Closed', value: summary.totals.closed },
  ] : [];

  const durations = summary ? [
    { key: 'first_response' as const, seconds: summary.durations_seconds.first_response_avg, samples: summary.sample_counts.first_response_avg },
    { key: 'incident_restore' as const, seconds: summary.durations_seconds.incident_restore_avg, samples: summary.sample_counts.incident_restore_avg },
    { key: 'service_fulfillment' as const, seconds: summary.durations_seconds.service_fulfillment_avg, samples: summary.sample_counts.service_fulfillment_avg },
    { key: 'close' as const, seconds: summary.durations_seconds.close_avg, samples: summary.sample_counts.close_avg },
  ] : [];

  return (
    <section data-testid="ticket-summary-panel" className={`${ticketSurfaceClass} shrink-0 overflow-visible`}>
      <button type="button" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)} className="flex min-h-10 w-full items-center justify-between gap-3 px-3 py-2 text-left sm:px-4">
        <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
          <span className="text-[var(--ui-text-label)] font-semibold text-[var(--ui-fg)]">{zh ? '工单统计' : 'Ticket summary'}</span>
          <span className="text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">{zh ? `UTC 日期：${appliedRange.from} 至 ${appliedRange.to}` : `UTC dates: ${appliedRange.from} to ${appliedRange.to}`}</span>
          {summary && <span className="text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">{zh ? `共 ${summary.totals.all} 条` : `${summary.totals.all} total`}</span>}
        </span>
        {expanded ? <ChevronUp size={15} className="shrink-0 text-[var(--ui-fg-muted)]" /> : <ChevronDown size={15} className="shrink-0 text-[var(--ui-fg-muted)]" />}
      </button>
      {expanded && <div className="border-t border-[var(--ui-border)] px-3 py-3 sm:px-4">
        <form onSubmit={submitRange} className="mb-3 flex flex-wrap items-end gap-x-3 gap-y-2">
          <label className={ticketLabelClass}>{zh ? '开始日期（UTC）' : 'From (UTC)'}<input aria-label={zh ? '统计开始日期' : 'Summary start date'} type="date" value={draftFrom} onChange={(event) => setDraftFrom(event.target.value)} className={`${ticketInputClass} mt-1 block min-h-9 w-auto px-2`} /></label>
          <label className={ticketLabelClass}>{zh ? '结束日期（UTC）' : 'To (UTC)'}<input aria-label={zh ? '统计结束日期' : 'Summary end date'} type="date" value={draftTo} onChange={(event) => setDraftTo(event.target.value)} className={`${ticketInputClass} mt-1 block min-h-9 w-auto px-2`} /></label>
          <ActionButton type="submit" variant="primary" disabled={loading} icon={loading ? LoaderCircle : undefined} iconClassName={loading ? 'animate-spin' : undefined}>{zh ? '查询' : 'Apply'}</ActionButton>
          <span className="pb-2 text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">{zh ? '含首尾两天，最多 366 天。' : 'Both dates are included; up to 366 days.'}</span>
        </form>
        {error && <div role="alert" className="mb-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[var(--ui-danger)]/30 bg-[var(--ui-danger-subtle)] px-3 py-2 text-[var(--ui-text-body)] text-[var(--ui-danger)]"><span>{permissionDenied ? (zh ? '当前账号无权查看工单统计。' : 'This account cannot view ticket statistics.') : error}</span><ActionButton onClick={() => setAppliedRange((range) => ({ ...range }))}>{zh ? '重试' : 'Retry'}</ActionButton></div>}
        {loading && !summary ? <p role="status" className="flex items-center gap-2 py-5 text-[var(--ui-text-body)] text-[var(--ui-fg-muted)]"><LoaderCircle size={14} className="animate-spin" />{zh ? '正在加载统计…' : 'Loading summary…'}</p> : summary && <div className="space-y-4">
          <dl className="grid grid-cols-2 gap-x-4 sm:grid-cols-3 lg:grid-cols-5">
            {metrics.map((metric) => <div key={metric.label} className="min-w-0 border-t border-[var(--ui-border)] py-2 first:border-t-0"><dt className="text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">{metric.label}</dt><dd className="mt-0.5 text-[var(--ui-text-body)] font-semibold text-[var(--ui-fg)]">{countText(metric.value, zh)}</dd></div>)}
          </dl>

          <div className="grid gap-4 border-t border-[var(--ui-border)] pt-3 lg:grid-cols-[minmax(220px,.7fr)_minmax(0,1.3fr)]">
            <div className="space-y-3">
              <section>
                <h3 className="mb-2 text-[var(--ui-text-label)] font-semibold text-[var(--ui-fg)]">{zh ? '优先级分布' : 'By priority'}</h3>
                {summary.by_priority.length ? <ul className="flex flex-wrap gap-3">{summary.by_priority.map((row) => <li key={row.priority} className="flex items-baseline gap-1.5 text-[var(--ui-text-caption)]"><span className="text-[var(--ui-fg-muted)]">{row.priority}</span><span className="font-semibold tabular-nums text-[var(--ui-fg)]">{row.count}</span></li>)}</ul> : <p className="text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">{zh ? '暂无数据' : 'No data'}</p>}
              </section>
              <section className="border-t border-[var(--ui-border)] pt-3">
                <h3 className="mb-2 text-[var(--ui-text-label)] font-semibold text-[var(--ui-fg)]">{zh ? '责任组工单数' : 'By assignment group'}</h3>
                {summary.by_assignment_group.length ? <ul className="max-h-28 space-y-1 overflow-auto">{summary.by_assignment_group.slice(0, 6).map((row) => <li key={row.id || row.name} className="flex items-center justify-between gap-2 text-[var(--ui-text-caption)]"><span className="min-w-0 truncate text-[var(--ui-fg-muted)]">{row.name}</span><span className="shrink-0 font-semibold tabular-nums text-[var(--ui-fg)]">{row.count}</span></li>)}</ul> : <p className="text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">{zh ? '暂无数据' : 'No data'}</p>}
              </section>
            </div>

            <section className="min-w-0 border-t border-[var(--ui-border)] pt-3 lg:border-t-0 lg:border-l lg:pl-4 lg:pt-0">
              <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1"><h3 className="text-[var(--ui-text-label)] font-semibold text-[var(--ui-fg)]">{zh ? '平均耗时' : 'Average durations'}</h3><p className="text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">{zh ? 'UTC 事件经过时间，不等同于工作日历 SLA。' : 'Elapsed UTC event time; separate from working-calendar SLA.'}</p></div>
              <dl className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
                {durations.map((row) => <div key={row.key} className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] gap-x-2 border-t border-[var(--ui-border)] py-2"><dt className="min-w-0 text-[var(--ui-text-caption)] leading-4 text-[var(--ui-fg-muted)]">{metricLabel(row.key, zh)}</dt><dd className="text-right"><span className="block text-[var(--ui-text-body)] font-semibold text-[var(--ui-fg)]">{row.samples > 0 && row.seconds != null ? formatDuration(row.seconds, zh) : (zh ? '暂无数据' : 'No data')}</span>{row.samples > 0 && row.seconds != null && <span className="block text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">{zh ? `${row.samples} 个样本` : `${row.samples} samples`}</span>}</dd></div>)}
              </dl>
            </section>
          </div>
        </div>}
      </div>}
    </section>
  );
};

export default TicketSummaryPanel;
