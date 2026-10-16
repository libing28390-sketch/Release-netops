import React from 'react';
import { CalendarClock, CircleAlert, Pencil, Play, PowerOff, RotateCcw, Trash2 } from 'lucide-react';
import Pagination from '../../../components/Pagination';
import type { ScheduledJob } from '../types';
import { ACTION_TYPES } from '../constants';
import { formatFuturePlanName, formatScheduleTimestamp, getScheduleStatus, describeScope } from '../helpers';

interface ScheduleListProps {
  zh: boolean;
  language: string;
  schedules: ScheduledJob[];
  loading: boolean;
  error?: string;
  total: number;
  page: number;
  pageSize: number;
  onPageChange: (p: number) => void;
  onPageSizeChange: (s: number) => void;
  onSelect: (sch: ScheduledJob) => void;
  onToggleEnabled: (sch: ScheduledJob) => void;
  onEdit: (sch: ScheduledJob) => void;
  onDelete: (id: string) => void;
  onRetry: () => void;
}

const ScheduleList: React.FC<ScheduleListProps> = ({
  zh, language, schedules, loading, error, total, page, pageSize,
  onPageChange, onPageSizeChange, onSelect, onToggleEnabled, onEdit, onDelete, onRetry,
}) => {
  const actionClass = 'inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-[11px] font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-40';

  return (
    <section className="flex min-h-[420px] flex-col overflow-hidden rounded-2xl border border-black/5 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-black/5 bg-slate-50/70 px-5 py-3.5">
        <div className="flex items-center gap-2.5">
          <CalendarClock size={17} className="text-cyan-600" />
          <h3 className="text-sm font-bold text-[#164e63]">{zh ? '执行计划' : 'Execution Plans'}</h3>
        </div>
        <span className="text-xs font-semibold tabular-nums text-slate-500">
          {zh ? `共 ${total} 条` : `${total} items`}
        </span>
      </div>

      <div className="flex-1 overflow-auto">
        <table className="w-full min-w-[1120px] border-collapse text-left">
          <thead className="sticky top-0 z-10 bg-white shadow-[0_1px_0_rgba(15,23,42,0.08)]">
            <tr className="text-[11px] font-bold text-slate-500">
              <th className="px-4 py-3">{zh ? '计划名称' : 'Plan Name'}</th>
              <th className="px-4 py-3">{zh ? '对象' : 'Target'}</th>
              <th className="px-4 py-3">{zh ? '执行方式' : 'Execution'}</th>
              <th className="px-4 py-3">{zh ? '状态' : 'Status'}</th>
              <th className="px-4 py-3">{zh ? '计划执行时间' : 'Scheduled At'}</th>
              <th className="px-4 py-3">{zh ? '创建人' : 'Creator'}</th>
              <th className="px-4 py-3 text-right">{zh ? '操作' : 'Actions'}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 text-xs">
            {loading ? (
              <tr>
                <td colSpan={7} className="py-20 text-center text-slate-400">
                  <RotateCcw size={20} className="mx-auto mb-2 animate-spin text-cyan-500" />
                  {zh ? '正在加载执行计划…' : 'Loading schedules…'}
                </td>
              </tr>
            ) : error ? (
              <tr>
                <td colSpan={7} className="py-16 text-center">
                  <CircleAlert size={22} className="mx-auto mb-2 text-rose-500" />
                  <p className="text-sm font-semibold text-slate-700">{error}</p>
                  <button type="button" onClick={onRetry} className="mt-3 rounded-lg bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-cyan-700">
                    {zh ? '重试' : 'Retry'}
                  </button>
                </td>
              </tr>
            ) : schedules.length > 0 ? (
              schedules.map((sch) => {
                const runAt = sch.run_at || sch.scheduled_at;
                const actionInfo = ACTION_TYPES.find((action) => action.value === sch.action_type);
                const status = getScheduleStatus(sch, zh);
                const statusClass = status.icon === 'disabled'
                  ? 'bg-slate-100 text-slate-600'
                  : status.icon === 'pending'
                    ? 'bg-cyan-50 text-cyan-700'
                    : status.icon === 'done'
                      ? 'bg-emerald-50 text-emerald-700'
                      : 'bg-amber-50 text-amber-700';
                const jobId = sch.job_id || sch.id;

                return (
                  <tr
                    key={`${jobId}-${runAt}`}
                    onClick={() => onSelect(sch)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        onSelect(sch);
                      }
                    }}
                    tabIndex={0}
                    className={`cursor-pointer transition-colors hover:bg-cyan-50/40 focus-within:bg-cyan-50/40 focus:outline-none ${!sch.enabled ? 'bg-slate-50/70' : ''}`}
                  >
                    <td className="max-w-[320px] px-4 py-3.5">
                      <div className="truncate font-semibold text-slate-800" title={formatFuturePlanName(runAt, zh)}>
                        {formatFuturePlanName(runAt, zh)}
                      </div>
                      <div className="mt-1 truncate text-[10px] text-slate-400" title={sch.name}>
                        {zh ? '作业：' : 'Job: '}{sch.name || '—'}
                      </div>
                    </td>
                    <td className="max-w-[220px] px-4 py-3.5">
                      <span className="block truncate font-medium text-slate-700" title={describeScope(sch.device_scope, sch.device_filter, zh)}>
                        {describeScope(sch.device_scope, sch.device_filter, zh)}
                      </span>
                    </td>
                    <td className="px-4 py-3.5">
                      <div className="font-semibold text-slate-700">
                        {zh ? (actionInfo?.labelZh || sch.action_type) : (actionInfo?.labelEn || sch.action_type)}
                      </div>
                      <div className="mt-1 text-[10px] text-slate-400">
                        {sch.use_admin_creds ? (zh ? '特权账号' : 'Privileged') : (zh ? '普通账号' : 'Standard')}
                        {sch.action_type === 'script_run' && sch.script_id ? ` · ${sch.script_id}` : ''}
                      </div>
                    </td>
                    <td className="px-4 py-3.5">
                      <span className={`inline-flex whitespace-nowrap rounded-full px-2.5 py-1 text-[10px] font-bold ${statusClass}`}>
                        {status.label}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3.5 font-mono text-[11px] font-medium text-slate-700">
                      {formatScheduleTimestamp(runAt)}
                    </td>
                    <td className="px-4 py-3.5 font-medium text-slate-600">{sch.created_by || '—'}</td>
                    <td className="px-4 py-3.5">
                      <div className="flex items-center justify-end gap-1" onClick={(event) => event.stopPropagation()}>
                        <button
                          type="button"
                          className={`${actionClass} ${sch.enabled ? 'text-amber-700 hover:bg-amber-50' : 'text-emerald-700 hover:bg-emerald-50'}`}
                          aria-label={sch.enabled ? (zh ? '停用计划' : 'Disable plan') : (zh ? '启用计划' : 'Enable plan')}
                          title={sch.enabled ? (zh ? '停用' : 'Disable') : (zh ? '启用' : 'Enable')}
                          onClick={() => onToggleEnabled(sch)}
                        >
                          {sch.enabled ? <PowerOff size={13} /> : <Play size={13} />}
                          {sch.enabled ? (zh ? '停用' : 'Disable') : (zh ? '启用' : 'Enable')}
                        </button>
                        <button
                          type="button"
                          className={`${actionClass} text-cyan-700 hover:bg-cyan-50`}
                          aria-label={zh ? '编辑计划' : 'Edit plan'}
                          onClick={() => onEdit(sch)}
                        >
                          <Pencil size={13} />{zh ? '编辑' : 'Edit'}
                        </button>
                        <button
                          type="button"
                          className={`${actionClass} text-rose-700 hover:bg-rose-50`}
                          aria-label={zh ? '删除计划' : 'Delete plan'}
                          onClick={() => onDelete(jobId)}
                        >
                          <Trash2 size={13} />{zh ? '删除' : 'Delete'}
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })
            ) : (
              <tr>
                <td colSpan={7} className="py-20 text-center text-slate-400">
                  <CalendarClock size={28} className="mx-auto mb-2 text-slate-300" />
                  <p className="font-semibold text-slate-600">{zh ? '当前时间范围内没有执行计划' : 'No schedules in this time range'}</p>
                  <p className="mt-1 text-[11px]">{zh ? '调整时间范围或新建计划后，这里会显示计划触发时间。' : 'Adjust the time range or create a plan to see upcoming run times.'}</p>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {total > 0 && (
        <Pagination
          currentPage={page}
          totalItems={total}
          itemsPerPage={pageSize}
          onPageChange={onPageChange}
          onItemsPerPageChange={onPageSizeChange}
          language={language}
        />
      )}
    </section>
  );
};

export default ScheduleList;
