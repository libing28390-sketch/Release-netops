import React, { useEffect, useId, useState } from 'react';

type TargetStatusCountKey = 'queued' | 'running' | 'succeeded' | 'failed' | 'timeout' | 'cancelled';

export interface CmdbInterfaceCollectionTarget {
  id?: string;
  target_id?: string;
  target_hostname?: string;
  target_ip?: string;
  status?: string;
  error_message?: string;
}

export interface CmdbInterfaceCollectionJob {
  job_id?: string;
  status?: string;
  total_targets?: unknown;
  success_count?: unknown;
  failed_count?: unknown;
  cancelled_count?: unknown;
  completed_count?: unknown;
  target_status_counts?: Partial<Record<TargetStatusCountKey, unknown>> | null;
  targets?: unknown;
  targets_truncated?: boolean;
}

interface CmdbInterfaceCollectionProgressProps {
  job: CmdbInterfaceCollectionJob | null;
  language?: string;
  loading?: boolean;
}

type TargetRecord = CmdbInterfaceCollectionTarget & Record<string, unknown>;

function parseCount(value: unknown): number | undefined {
  if (typeof value !== 'number' && typeof value !== 'string') return undefined;
  if (typeof value === 'string' && !/^\d+$/.test(value.trim())) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? Math.floor(parsed) : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function statusOf(target: TargetRecord): string {
  return String(target.status || '').trim().toLowerCase();
}

function targetCountsFromList(targets: TargetRecord[], status: TargetStatusCountKey): number {
  return targets.filter(target => statusOf(target) === status).length;
}

function labelForStatus(status: string, zh: boolean): string {
  switch (status) {
    case 'running': return zh ? '采集中' : 'Running';
    case 'queued': return zh ? '排队中' : 'Queued';
    case 'succeeded':
    case 'success':
    case 'finished':
    case 'complete':
    case 'completed': return zh ? '已完成' : 'Completed';
    case 'partially_failed':
    case 'partial': return zh ? '部分失败' : 'Partially failed';
    case 'failed': return zh ? '失败' : 'Failed';
    case 'timeout':
    case 'timed_out': return zh ? '超时' : 'Timed out';
    case 'cancelled':
    case 'canceled': return zh ? '已取消' : 'Cancelled';
    default: return zh ? '状态未知' : 'Status unknown';
  }
}

function statusTone(status: string): string {
  if (['succeeded', 'success', 'finished', 'complete', 'completed'].includes(status)) {
    return 'border-[var(--ui-success)]/30 bg-[var(--ui-success-subtle)] text-[var(--ui-success)]';
  }
  if (['partially_failed', 'partial'].includes(status)) {
    return 'border-[var(--ui-warning)]/30 bg-[var(--ui-warning-subtle)] text-[var(--ui-warning)]';
  }
  if (['failed', 'timeout', 'timed_out'].includes(status)) {
    return 'border-[var(--ui-danger)]/30 bg-[var(--ui-danger-subtle)] text-[var(--ui-danger)]';
  }
  if (['running'].includes(status)) return 'border-[var(--ui-accent)]/30 bg-[var(--ui-accent-subtle)] text-[var(--ui-accent)]';
  return 'border-[var(--ui-border)] bg-[var(--ui-surface-muted)] text-[var(--ui-fg-muted)]';
}

const CmdbInterfaceCollectionProgress: React.FC<CmdbInterfaceCollectionProgressProps> = ({
  job,
  language = 'zh',
  loading = false,
}) => {
  const zh = language !== 'en';
  const detailsId = useId();
  const [detailsOpen, setDetailsOpen] = useState(false);

  useEffect(() => {
    setDetailsOpen(false);
  }, [job?.job_id, job?.status]);

  if (!job) {
    if (!loading) return null;
    return (
      <section
        className="mb-4 rounded-xl border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 py-2.5"
        aria-label={zh ? '接口采集任务' : 'Interface collection job'}
        aria-live="polite"
      >
        <p className="text-sm font-medium text-[var(--ui-fg)]">
          {zh ? '正在创建接口采集任务…' : 'Starting interface collection…'}
        </p>
      </section>
    );
  }

  const jobStatus = String(job.status || '').trim().toLowerCase();
  const jobLabel = labelForStatus(jobStatus, zh);
  const targets = Array.isArray(job.targets) ? job.targets.filter(isRecord) as TargetRecord[] : [];
  const targetStatusCounts = isRecord(job.target_status_counts) ? job.target_status_counts : null;
  const hasFullStatusCounts = Boolean(targetStatusCounts);
  const readStatusCount = (status: TargetStatusCountKey): number | undefined => {
    if (targetStatusCounts) {
      return parseCount(targetStatusCounts[status]) ?? (targetStatusCounts[status] == null ? 0 : undefined);
    }
    if (job.targets_truncated) return undefined;
    if (status === 'running' || status === 'queued' || status === 'failed' || status === 'timeout') {
      return targetCountsFromList(targets, status);
    }
    return undefined;
  };

  const totalFromJob = parseCount(job.total_targets);
  const succeededFromJob = parseCount(job.success_count);
  const failedFromJob = parseCount(job.failed_count);
  const queuedCount = readStatusCount('queued');
  const runningCount = readStatusCount('running');
  const succeededCount = succeededFromJob ?? readStatusCount('succeeded');
  const failedStatusCount = readStatusCount('failed');
  const timedOutCount = readStatusCount('timeout');
  const cancelledCount = parseCount(job.cancelled_count) ?? readStatusCount('cancelled');
  const failedCount = failedFromJob ?? (failedStatusCount !== undefined && timedOutCount !== undefined
    ? failedStatusCount + timedOutCount
    : undefined);

  const statusCountValues = hasFullStatusCounts
    ? (['queued', 'running', 'succeeded', 'failed', 'timeout', 'cancelled'] as const)
      .map(status => readStatusCount(status))
    : [];
  const countedTotal = hasFullStatusCounts && statusCountValues.every(count => count !== undefined)
    ? statusCountValues.reduce<number>((sum, count) => sum + (count ?? 0), 0)
    : undefined;
  const totalCount = totalFromJob ?? countedTotal;
  const completedFromJob = parseCount(job.completed_count);
  const completedCount = completedFromJob ?? (succeededCount !== undefined && failedCount !== undefined && cancelledCount !== undefined
    ? succeededCount + failedCount + cancelledCount
    : undefined);
  const progressAvailable = totalCount !== undefined && totalCount > 0 && completedCount !== undefined;
  const progressValue = progressAvailable ? Math.min(totalCount, completedCount) : undefined;
  const progressPercent = progressAvailable ? Math.min(100, Math.max(0, (progressValue! / totalCount) * 100)) : 0;
  const progressLabel = zh ? '接口采集进度' : 'Interface collection progress';

  const detailTargets = targets.filter(target => ['running', 'failed', 'timeout', 'timed_out', 'cancelled', 'canceled'].includes(statusOf(target)));
  const detailsButtonLabel = detailsOpen ? (zh ? '收起详情' : 'Hide details') : (zh ? '查看详情' : 'View details');

  return (
    <section
      className="mb-4 rounded-xl border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 py-2.5"
      aria-label={progressLabel}
    >
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-semibold text-[var(--ui-fg)]">
              {zh ? '接口状态采集' : 'Interface status collection'}
            </h2>
            <span className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-medium ${statusTone(jobStatus)}`}>
              {jobLabel}
            </span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--ui-fg-muted)]">
            <span className="tabular-nums">
              {zh ? '已完成' : 'Completed'} {completedCount ?? '—'} / {totalCount ?? (zh ? '总数未知' : 'total unknown')}
            </span>
            <span className="tabular-nums">{zh ? '成功' : 'Succeeded'} {succeededCount ?? '—'}</span>
            <span className="tabular-nums">{zh ? '失败' : 'Failed'} {failedCount ?? '—'}</span>
            <span className="tabular-nums">{zh ? '运行中' : 'Running'} {runningCount ?? '—'}</span>
            <span className="tabular-nums">{zh ? '排队中' : 'Queued'} {queuedCount ?? '—'}</span>
          </div>
        </div>
        <button
          type="button"
          className="shrink-0 rounded-md px-2 py-1 text-xs font-medium text-[var(--ui-accent)] underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ui-accent)]"
          aria-expanded={detailsOpen}
          aria-controls={detailsId}
          onClick={() => setDetailsOpen(open => !open)}
        >
          {detailsButtonLabel}
        </button>
      </div>

      {progressAvailable && (
        <div
          className="mt-2 h-1.5 overflow-hidden rounded-full bg-[var(--ui-surface-muted)]"
          role="progressbar"
          aria-label={progressLabel}
          aria-valuemin={0}
          aria-valuemax={totalCount}
          aria-valuenow={progressValue}
          aria-valuetext={zh ? `已完成 ${progressValue} / ${totalCount} 台设备` : `${progressValue} of ${totalCount} devices completed`}
        >
          <div className="h-full rounded-full bg-[var(--ui-accent)] transition-[width] duration-200" style={{ width: `${progressPercent}%` }} />
        </div>
      )}

      <div id={detailsId} hidden={!detailsOpen} className="mt-3 border-t border-[var(--ui-border)] pt-2.5">
        <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-[var(--ui-fg-muted)]">
          {job.job_id && <span>{zh ? '任务编号' : 'Job'}: <span className="font-mono">{job.job_id}</span></span>}
          {!progressAvailable && (
            <span>{totalCount === 0 ? (zh ? '没有采集目标' : 'No collection targets') : (zh ? '总数暂不可用，无法计算进度' : 'Total unavailable; progress cannot be calculated')}</span>
          )}
          {job.targets_truncated && <span>{zh ? '设备明细已截断，仅展示返回的进行中和异常项。' : 'Device details are truncated; only returned active and failed targets are shown.'}</span>}
        </div>
        {detailTargets.length > 0 ? (
          <ul className="max-h-40 space-y-1.5 overflow-y-auto pr-1">
            {detailTargets.map((target, index) => {
              const targetStatus = statusOf(target);
              const isFailure = ['failed', 'timeout', 'timed_out'].includes(targetStatus);
              const targetName = String(target.target_hostname || target.target_ip || target.target_id || target.id || (zh ? `设备 ${index + 1}` : `Device ${index + 1}`));
              const reason = String(target.error_message || '').trim();
              const key = String(target.id || target.target_id || `${targetName}-${targetStatus}-${index}`);
              return (
                <li key={key} className="rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface-muted)] px-2.5 py-2 text-xs">
                  <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                    <span className="min-w-0 break-all font-medium text-[var(--ui-fg)]">{targetName}</span>
                    <span className={isFailure ? 'font-medium text-[var(--ui-danger)]' : 'text-[var(--ui-fg-muted)]'}>
                      {labelForStatus(targetStatus, zh)}
                    </span>
                  </div>
                  {isFailure && reason && <p className="mt-1 break-words leading-5 text-[var(--ui-danger)]">{reason}</p>}
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="text-xs text-[var(--ui-fg-muted)]">
            {zh ? '暂无运行设备或失败明细。' : 'No running devices or failure details.'}
          </p>
        )}
      </div>
    </section>
  );
};

export default CmdbInterfaceCollectionProgress;
