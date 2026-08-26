import React from 'react';
import {
  Activity, RotateCcw, Play, CalendarClock, Clock, Eye,
  FileText, FileSpreadsheet, FileJson,
} from 'lucide-react';
import Pagination from '../../../components/Pagination';
import type { UnifiedExecutionLog } from '../types';
import { ActionIconButton, ActionIconGroup } from '../../../components/ui/ActionIconButton';

interface HistoryListProps {
  zh: boolean;
  language: string;
  logs: UnifiedExecutionLog[];
  loading: boolean;
  paginatedLogs: UnifiedExecutionLog[];
  page: number;
  pageSize: number;
  onPageChange: (p: number) => void;
  onPageSizeChange: (s: number) => void;
  executionTypeFilter: 'all' | 'manual' | 'plan' | 'job';
  onFilterChange: (f: 'all' | 'manual' | 'plan' | 'job') => void;
  onSelectLog: (log: UnifiedExecutionLog) => void;
  onExport: (logId: string, format: string, source: string) => void;
}

const HistoryList: React.FC<HistoryListProps> = ({
  zh, language, logs, loading, paginatedLogs, page, pageSize,
  onPageChange, onPageSizeChange, executionTypeFilter, onFilterChange,
  onSelectLog, onExport,
}) => {
  return (
    <section className="ops-surface nx-history-panel flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b px-5 py-4 sm:px-6" style={{ borderColor: 'var(--ops-line)' }}>
        <div className="flex min-w-0 items-center gap-3">
          <div
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border"
            style={{
              background: 'var(--ui-accent-subtle)',
              borderColor: 'color-mix(in srgb, var(--ui-accent) 18%, var(--ui-border))',
              color: 'var(--ui-accent)',
            }}
          >
            <Activity size={17} strokeWidth={1.8} />
          </div>
          <div className="min-w-0">
            <div className="flex min-w-0 items-center gap-2">
              <h3 className="nx-section-title truncate" style={{ color: 'var(--ops-ink)' }}>
                {zh ? '执行流水历史' : 'Execution Logs'}
              </h3>
              <span className="inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 nx-micro-text tabular-nums" style={{ borderColor: 'var(--ops-line)', background: 'var(--ui-surface-muted)', color: 'var(--ops-muted)' }}>
                {logs.length}
              </span>
            </div>
            <p className="nx-micro-text mt-0.5 truncate" style={{ color: 'var(--ops-muted)' }}>
              {zh ? '按触发方式筛选并追溯每次自动化执行结果' : 'Filter by trigger and trace each automation result'}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div
            className="flex items-center gap-0.5 rounded-lg border p-0.5"
            style={{ borderColor: 'var(--ops-line)', background: 'var(--ui-surface-muted)' }}
            role="tablist"
            aria-label={zh ? '执行类型筛选' : 'Execution type filter'}
          >
            {(['all', 'manual', 'plan', 'job'] as const).map(type => {
              const labels = {
                all: zh ? '全部' : 'All',
                manual: zh ? '手动执行' : 'Manual',
                plan: zh ? '执行计划' : 'Plan',
                job: zh ? '定时作业' : 'Job',
              };
              const isActive = executionTypeFilter === type;
              return (
                <button
                  key={type}
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  onClick={() => onFilterChange(type)}
                  className={`h-8 rounded-md px-3 text-xs font-semibold transition-colors ${
                    isActive
                      ? 'bg-[var(--ui-accent)] text-white shadow-sm'
                      : 'text-[var(--ui-fg-muted)] hover:bg-[var(--ui-surface)] hover:text-[var(--ui-fg)]'
                  }`}
                >
                  {labels[type]}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto custom-scrollbar">
        {loading ? (
          <div className="flex min-h-[320px] flex-col items-center justify-center gap-3 px-6 py-20" style={{ color: 'var(--ops-muted)' }}>
            <RotateCcw size={26} className="animate-spin" style={{ opacity: 0.45, color: 'var(--ui-accent)' }} />
            <span className="nx-meta-text">{zh ? '获取流水中...' : 'Loading history...'}</span>
          </div>
        ) : paginatedLogs.length > 0 ? (
          <table className="nx-data-table min-w-[1180px] table-auto text-left">
            <colgroup>
              <col className="w-[180px]" />
              <col className="w-[250px]" />
              <col className="w-[150px]" />
              <col className="w-[145px]" />
              <col className="w-[190px]" />
              <col className="w-[120px]" />
              <col className="w-[220px]" />
            </colgroup>
            <thead className="sticky top-0 z-10">
              <tr>
                <th>{zh ? '触发时间' : 'Triggered At'}</th>
                <th>{zh ? '任务名称' : 'Task Name'}</th>
                <th>{zh ? '执行方式' : 'Type'}</th>
                <th>{zh ? '状态' : 'Status'}</th>
                <th>{zh ? '执行概况' : 'Execution Summary'}</th>
                <th>{zh ? '执行人' : 'Operator'}</th>
                <th className="text-right">{zh ? '操作' : 'Actions'}</th>
              </tr>
            </thead>
            <tbody>
              {paginatedLogs.map(log => {
                const statusMap: Record<string, { label: string; tone: 'success' | 'info' | 'danger' | 'warning' | 'neutral' }> = {
                  completed: { label: zh ? '已完成' : 'Completed', tone: 'success' },
                  success: { label: zh ? '已完成' : 'Completed', tone: 'success' },
                  running: { label: zh ? '执行中' : 'Running', tone: 'info' },
                  failed: { label: zh ? '已失败' : 'Failed', tone: 'danger' },
                  awaiting_approval: { label: zh ? '待审批' : 'Awaiting approval', tone: 'warning' },
                  approval_rejected: { label: zh ? '审批拒绝' : 'Approval rejected', tone: 'danger' },
                };
                const st = statusMap[log.status] || { label: log.status, tone: 'neutral' as const };
                
                const typeLabels: Record<string, { label: string; tone: 'manual' | 'plan' | 'job' | 'neutral' }> = {
                  manual: { label: zh ? '手动执行' : 'Manual', tone: 'manual' },
                  plan: { label: zh ? '执行计划' : 'Execution Plan', tone: 'plan' },
                  job: { label: zh ? '定时作业' : 'Scheduled Job', tone: 'job' },
                };
                const tl = typeLabels[log.trigger_type] || { label: log.trigger_type, tone: 'neutral' as const };

                return (
                  <tr key={`${log.source}-${log.id}`}>
                    <td className="whitespace-nowrap">
                      <span className="nx-code-text" style={{ color: 'var(--ui-fg-muted)' }}>
                        {new Date(log.started_at).toLocaleString(zh ? 'zh-CN' : 'en-US', { hour12: false })}
                      </span>
                    </td>
                    <td>
                      <div className="min-w-0">
                        <div className="truncate text-sm font-semibold" style={{ color: 'var(--ops-ink)' }}>{log.name}</div>
                        <div className="nx-micro-text mt-0.5" style={{ color: 'var(--ui-fg-subtle)' }}>
                          {log.source === 'inspection' ? (zh ? '巡检执行' : 'Inspection run') : (zh ? '自动化执行' : 'Automation run')}
                        </div>
                      </div>
                    </td>
                    <td>
                      <span className={`nx-history-type-pill nx-history-type-pill--${tl.tone}`}>
                        {log.trigger_type === 'manual' ? <Play size={10} /> : log.trigger_type === 'plan' ? <CalendarClock size={10} /> : <Clock size={10} />}
                        {tl.label}
                      </span>
                    </td>
                    <td>
                      <span className={`nx-history-status-pill nx-history-status-pill--${st.tone}`}>
                        <span className={`h-1.5 w-1.5 rounded-full ${log.status === 'running' ? 'animate-pulse' : ''}`} />
                        {st.label}
                      </span>
                    </td>
                    <td>
                      <div className="flex flex-col gap-1">
                        <span className="text-sm font-semibold" style={{ color: 'var(--ops-ink)' }}>
                          {log.total_devices} <span className="text-xs font-normal" style={{ color: 'var(--ops-muted)' }}>{zh ? '台设备' : 'Devices'}</span>
                        </span>
                        <div className="flex items-center gap-2 nx-micro-text" style={{ color: 'var(--ops-muted)' }}>
                          {log.source === 'inspection' ? (
                            <>
                              <span>{zh ? '平均分' : 'Avg score'}:</span>
                              <span className={`font-semibold tabular-nums ${
                              (log.avg_health_score || 0) >= 80 ? 'text-emerald-600' : (log.avg_health_score || 0) >= 60 ? 'text-amber-600' : 'text-red-600'
                              }`}>
                                {log.avg_health_score?.toFixed(1) ?? '—'}
                              </span>
                            </>
                          ) : (
                            <>
                              <span className="inline-flex items-center gap-1 text-emerald-600">
                                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                                {log.success_count} {zh ? '成功' : 'ok'}
                              </span>
                              <span className="inline-flex items-center gap-1 text-red-600">
                                <span className="h-1.5 w-1.5 rounded-full bg-red-500" />
                                {log.failed_count} {zh ? '失败' : 'failed'}
                              </span>
                            </>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="whitespace-nowrap">
                      <span className="text-sm font-medium" style={{ color: 'var(--ops-muted)' }}>{log.created_by}</span>
                    </td>
                    <td className="whitespace-nowrap">
                      <ActionIconGroup className="nx-action-group--table" label={zh ? '执行记录操作' : 'Execution log actions'}>
                        <ActionIconButton
                          icon={Eye}
                          label={zh ? '查看执行详情' : 'View execution details'}
                          variant="accent"
                          onClick={() => onSelectLog(log)}
                        />
                        <ActionIconButton
                          icon={FileText}
                          label={zh ? '导出 HTML' : 'Export HTML'}
                          onClick={() => onExport(log.id, 'html', log.source)}
                        />
                        <ActionIconButton
                          icon={FileText}
                          label={zh ? '导出 PDF' : 'Export PDF'}
                          onClick={() => onExport(log.id, 'pdf', log.source)}
                        />
                        <ActionIconButton
                          icon={FileSpreadsheet}
                          label={zh ? '导出 Excel' : 'Export Excel'}
                          onClick={() => onExport(log.id, 'xlsx', log.source)}
                        />
                        <ActionIconButton
                          icon={FileJson}
                          label={zh ? '导出 JSON' : 'Export JSON'}
                          onClick={() => onExport(log.id, 'json', log.source)}
                        />
                      </ActionIconGroup>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <div className="flex min-h-[320px] flex-col items-center justify-center gap-3 px-6 py-20 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl border" style={{ borderColor: 'var(--ops-line)', background: 'var(--ui-surface-muted)', color: 'var(--ui-fg-subtle)' }}>
              <Activity size={24} strokeWidth={1.6} />
            </div>
            <div>
              <p className="nx-section-title" style={{ color: 'var(--ops-ink)' }}>{zh ? '暂无历史执行记录' : 'No history found'}</p>
              <p className="nx-meta-text mt-1" style={{ color: 'var(--ops-muted)' }}>{zh ? '执行记录将在自动化任务运行后显示在这里' : 'Execution records will appear here after an automation run'}</p>
            </div>
          </div>
        )}
      </div>

      {logs.length > 0 && (
        <div className="flex-shrink-0">
          <Pagination
            currentPage={page}
            totalItems={logs.length}
            onPageChange={onPageChange}
            itemsPerPage={pageSize}
            onItemsPerPageChange={onPageSizeChange}
            language={language}
          />
        </div>
      )}
    </section>
  );
};

export default HistoryList;
