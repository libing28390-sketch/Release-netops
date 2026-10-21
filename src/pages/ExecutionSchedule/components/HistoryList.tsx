import { DataTable } from '../../../components/DataTable';
import React, { useState, useEffect, useCallback } from 'react';
import {
  Activity, RotateCcw, Play, CalendarClock, Clock, Eye,
  FileSpreadsheet,
  Search, Globe, User, CheckCircle2, AlertCircle, RefreshCw
} from 'lucide-react';
import Pagination from '../../../components/Pagination';
import { ActionIconButton } from '../../../components/ui/ActionIconButton';
import type { UnifiedExecutionLog } from '../types';

import { TableActionCell, TableActionHeader } from '../../../components/ui/TableActionColumn';

const HISTORY_WAITING_STATUSES = new Set(['pending', 'queued', 'scheduled', 'awaiting_approval', 'approval_pending']);

const formatHistoryDate = (value: string | null | undefined, zh: boolean) => {
  if (!value) return '--';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '--' : date.toLocaleString(zh ? 'zh-CN' : 'en-US', { hour12: false });
};

const getHistoryDurationMs = (log: UnifiedExecutionLog, now: number) => {
  if (!log.ended_at && HISTORY_WAITING_STATUSES.has(log.status)) return undefined;
  if (log.duration_ms != null && Number.isFinite(log.duration_ms) && log.duration_ms >= 0) return log.duration_ms;
  const startedAt = Date.parse(log.started_at);
  if (!Number.isFinite(startedAt)) return undefined;
  if (log.ended_at) {
    const endedAt = Date.parse(log.ended_at);
    return Number.isFinite(endedAt) ? Math.max(0, endedAt - startedAt) : undefined;
  }
  return log.status === 'running' ? Math.max(0, now - startedAt) : undefined;
};

const formatHistoryDuration = (durationMs: number | undefined, zh: boolean) => {
  if (durationMs == null || !Number.isFinite(durationMs)) return '--';
  if (durationMs < 1000) return zh ? `${Math.round(durationMs)} 毫秒` : `${Math.round(durationMs)} ms`;
  const totalSeconds = Math.floor(durationMs / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (zh) {
    if (hours) return `${hours} 小时 ${minutes} 分 ${seconds} 秒`;
    if (minutes) return `${minutes} 分 ${seconds} 秒`;
    return `${seconds} 秒`;
  }
  if (hours) return `${hours}h ${minutes}m ${seconds}s`;
  if (minutes) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
};

interface HistoryListProps {
  zh: boolean;
  language: string;
  logs: UnifiedExecutionLog[];
  total: number;
  loading: boolean;
  errorMessage?: string;
  page: number;
  pageSize: number;
  onPageChange: (p: number) => void;
  onPageSizeChange: (s: number) => void;
  searchQuery: string;
  onSearchChange: (query: string) => void;
  executionTypeFilter: 'all' | 'manual' | 'plan' | 'job';
  onFilterChange: (f: 'all' | 'manual' | 'plan' | 'job') => void;
  onSelectLog: (log: UnifiedExecutionLog) => void;
  onExport: (logId: string, format: string, source: string, taskName?: string, startedAt?: string) => void;
  loadAllLogs: () => Promise<UnifiedExecutionLog[]>;
}

const HistoryList: React.FC<HistoryListProps> = ({
  zh, language, logs, total, loading, errorMessage, page, pageSize,
  onPageChange, onPageSizeChange, searchQuery, onSearchChange,
  executionTypeFilter, onFilterChange,
  onSelectLog, onExport, loadAllLogs,
}) => {
  const hasRunningLogs = logs.some((log) => log.status === 'running' && log.started_at);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!hasRunningLogs) return;
    setNow(Date.now());
    const intervalId = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(intervalId);
  }, [hasRunningLogs]);

  const exportHistory = useCallback(async () => {
    const allLogs = (await loadAllLogs()).filter((log) => executionTypeFilter === 'all' || log.trigger_type === executionTypeFilter);
    const query = searchQuery.trim().toLowerCase();
    const matchingLogs = query ? allLogs.filter((log) =>
      (log.name || '').toLowerCase().includes(query)
      || (log.created_by || '').toLowerCase().includes(query)
      || (log.status || '').toLowerCase().includes(query)) : allLogs;
    const exportNow = Date.now();
    const typeLabels: Record<string, string> = {
      manual: zh ? '手动执行' : 'Manual',
      plan: zh ? '执行计划' : 'Execution Plan',
      job: zh ? '定时作业' : 'Scheduled Job',
    };
    const statusLabels: Record<string, string> = {
      completed: zh ? '正常' : 'Completed',
      success: zh ? '正常' : 'Completed',
      running: zh ? '执行中' : 'Running',
      failed: zh ? '异常' : 'Failed',
      partial: zh ? '部分异常' : 'Partial',
      partial_failure: zh ? '部分异常' : 'Partial failure',
      partial_success: zh ? '部分成功' : 'Partial success',
      skipped: zh ? '已跳过' : 'Skipped',
      unknown: zh ? '未知' : 'Unknown',
      awaiting_approval: zh ? '待审批' : 'Awaiting approval',
      approval_rejected: zh ? '审批拒绝' : 'Approval rejected',
      denied: zh ? '权限拒绝' : 'Permission denied',
    };
    return {
      headers: zh
        ? ['任务名称', '来源', '执行方式', '执行人', '状态', '开始时间', '结束时间', '总耗时']
        : ['Task Name', 'Source', 'Type', 'Operator', 'Status', 'Start Time', 'End Time', 'Total Duration'],
      rows: matchingLogs.map((log) => [
        log.name || '--',
        log.source === 'config_backup'
          ? (zh ? '配置备份' : 'Config Backup')
          : log.source === 'inspection' ? (zh ? '巡检执行' : 'Inspection') : (zh ? '自动化执行' : 'Automation'),
        typeLabels[log.trigger_type] || log.trigger_type,
        log.created_by || 'admin',
        statusLabels[log.status] || log.status || (zh ? '未知' : 'Unknown'),
        formatHistoryDate(log.started_at, zh),
        formatHistoryDate(log.ended_at, zh),
        formatHistoryDuration(getHistoryDurationMs(log, exportNow), zh),
      ]),
    };
  }, [loadAllLogs, executionTypeFilter, searchQuery, zh]);

  return (
    <section className="bg-white rounded-2xl border border-slate-200/90 shadow-sm flex flex-col min-h-0 flex-1 overflow-hidden">
      
      {/* ── Toolbar Header ─────────────────────────────────────────── */}
      <div className="px-6 py-4 border-b border-slate-100 flex flex-wrap items-center justify-between gap-4 bg-slate-50/50">
        
        {/* Left: Title + Badge + Search Input */}
        <div className="flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-cyan-50 border border-cyan-100/80 flex items-center justify-center text-cyan-600 shadow-2xs">
              <Activity size={18} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-bold text-slate-900">
                  {zh ? '执行流水历史' : 'Execution Logs'}
                </h3>
                <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-cyan-100/80 text-cyan-800 font-mono">
                  {total}
                </span>
              </div>
              <p className="text-[11px] text-slate-400 mt-0.5">
                {zh ? '按触发方式筛选并追溯每次自动化执行详情与报告' : 'Filter by trigger type and trace each automation result'}
              </p>
            </div>
          </div>

          {/* Quick Search */}
          <div className="relative min-w-[220px]">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="search"
              value={searchQuery}
              onChange={e => onSearchChange(e.target.value)}
              placeholder={zh ? '搜索任务名称或执行人...' : 'Search task or operator...'}
              className="w-full pl-8 pr-3 py-1.5 rounded-xl border border-slate-200 text-xs bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-500 transition-all placeholder:text-slate-300"
            />
          </div>
        </div>

        {/* Right: Type Filter Segmented Buttons */}
        <div className="p-1 bg-slate-200/70 rounded-xl flex items-center gap-1 border border-slate-200/50">
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
                onClick={() => onFilterChange(type)}
                className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  isActive
                    ? 'bg-white text-cyan-700 shadow-2xs font-bold'
                    : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                {labels[type]}
              </button>
            );
          })}
        </div>
      </div>

      {/* ── Table Container ────────────────────────────────────────── */}
      <div className="min-h-0 flex-1 overflow-auto custom-scrollbar">
        {loading ? (
          <div className="flex min-h-[320px] flex-col items-center justify-center gap-3 px-6 py-20 text-slate-400">
            <RotateCcw size={28} className="animate-spin text-cyan-500" />
            <span className="text-xs font-medium">{zh ? '获取流水中...' : 'Loading history...'}</span>
          </div>
        ) : errorMessage ? (
          <div className="flex min-h-[320px] flex-col items-center justify-center gap-3 px-6 py-20 text-center text-rose-500">
            <AlertCircle size={28} />
            <p className="text-xs font-medium">{errorMessage}</p>
          </div>
        ) : logs.length > 0 ? (
          <DataTable unstyled exportConfig={{ filename: 'execution-history', language: zh ? 'zh' : 'en', disabled: logs.length === 0, exportData: exportHistory }} className="w-full min-w-[1200px] table-fixed border-collapse">
            <colgroup>
              <col style={{ width: '20%' }} /> {/* 任务名称 */}
              <col style={{ width: '8%' }} /> {/* 来源 */}
              <col style={{ width: '12%' }} /> {/* 执行方式 */}
              <col style={{ width: '11%' }} /> {/* 执行人 */}
              <col style={{ width: '9%' }} /> {/* 状态 */}
              <col style={{ width: '12%' }} /> {/* 开始时间 */}
              <col style={{ width: '12%' }} /> {/* 结束时间 */}
              <col style={{ width: '8%' }} /> {/* 总耗时 */}
              <col style={{ width: '8%' }} /> {/* 操作 */}
            </colgroup>
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50/60 text-[11px] font-bold uppercase tracking-wider text-slate-500">
                <th className="py-3.5 px-4 text-left">{zh ? '任务名称' : 'Task Name'}</th>
                <th className="py-3.5 px-4 text-left">{zh ? '来源' : 'Source'}</th>
                <th className="py-3.5 px-4 text-left">{zh ? '执行方式' : 'Type'}</th>
                <th className="py-3.5 px-4 text-left">{zh ? '执行人' : 'Operator'}</th>
                <th className="py-3.5 px-4 text-left">{zh ? '状态' : 'Status'}</th>
                <th className="py-3.5 px-4 text-left">{zh ? '开始时间' : 'Start Time'}</th>
                <th className="py-3.5 px-4 text-left">{zh ? '结束时间' : 'End Time'}</th>
                <th className="py-3.5 px-4 text-left">{zh ? '总耗时' : 'Total Duration'}</th>
                <TableActionHeader className="py-3.5 px-4 text-right pr-6">{zh ? '操作' : 'Actions'}</TableActionHeader>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {logs.map(log => {
                const statusMap: Record<string, { label: string; badgeCls: string; dotCls: string }> = {
                  completed: { label: zh ? '正常' : 'Completed', badgeCls: 'bg-emerald-50 text-emerald-700 border-emerald-200/60', dotCls: 'bg-emerald-500' },
                  success: { label: zh ? '正常' : 'Completed', badgeCls: 'bg-emerald-50 text-emerald-700 border-emerald-200/60', dotCls: 'bg-emerald-500' },
                  running: { label: zh ? '执行中' : 'Running', badgeCls: 'bg-blue-50 text-blue-700 border-blue-200/60', dotCls: 'bg-blue-500 animate-pulse' },
                  failed: { label: zh ? '异常' : 'Failed', badgeCls: 'bg-rose-50 text-rose-700 border-rose-200/60', dotCls: 'bg-rose-500' },
                  partial: { label: zh ? '部分异常' : 'Partial', badgeCls: 'bg-amber-50 text-amber-700 border-amber-200/60', dotCls: 'bg-amber-500' },
                  partial_failure: { label: zh ? '部分异常' : 'Partial failure', badgeCls: 'bg-amber-50 text-amber-700 border-amber-200/60', dotCls: 'bg-amber-500' },
                  partial_success: { label: zh ? '部分成功' : 'Partial success', badgeCls: 'bg-amber-50 text-amber-700 border-amber-200/60', dotCls: 'bg-amber-500' },
                  skipped: { label: zh ? '已跳过' : 'Skipped', badgeCls: 'bg-slate-50 text-slate-600 border-slate-200', dotCls: 'bg-slate-400' },
                  awaiting_approval: { label: zh ? '待审批' : 'Awaiting approval', badgeCls: 'bg-amber-50 text-amber-700 border-amber-200/60', dotCls: 'bg-amber-500' },
                  approval_rejected: { label: zh ? '审批拒绝' : 'Approval rejected', badgeCls: 'bg-rose-50 text-rose-700 border-rose-200/60', dotCls: 'bg-rose-500' },
                  denied: { label: zh ? '权限拒绝' : 'Permission denied', badgeCls: 'bg-rose-50 text-rose-700 border-rose-200/60', dotCls: 'bg-rose-500' },
                };
                const st = statusMap[log.status] || { label: log.status, badgeCls: 'bg-slate-50 text-slate-600 border-slate-200', dotCls: 'bg-slate-400' };
                
                const typeMap: Record<string, { label: string; icon: any; badgeCls: string }> = {
                  manual: { label: zh ? '手动执行' : 'Manual', icon: Play, badgeCls: 'bg-purple-50 text-purple-700 border-purple-200/60' },
                  plan: { label: zh ? '执行计划' : 'Execution Plan', icon: CalendarClock, badgeCls: 'bg-blue-50 text-blue-700 border-blue-200/60' },
                  job: { label: zh ? '定时作业' : 'Scheduled Job', icon: Clock, badgeCls: 'bg-cyan-50 text-cyan-700 border-cyan-200/60' },
                };
                const tl = typeMap[log.trigger_type] || { label: log.trigger_type, icon: Clock, badgeCls: 'bg-slate-50 text-slate-600 border-slate-200' };
                const TypeIcon = tl.icon;

                return (
                  <tr key={`${log.source}-${log.id}`} className="hover:bg-slate-50/70 transition-colors">
                    
                    {/* Task Name */}
                    <td className="py-3.5 px-4 text-left">
                      <div className="min-w-0">
                        <div className="text-xs font-bold text-slate-900 truncate">{log.name}</div>
                      </div>
                    </td>

                    {/* Source */}
                    <td className="py-3.5 px-4 text-xs text-slate-500">
                      {log.source === 'config_backup'
                        ? (zh ? '配置备份' : 'Config Backup')
                        : log.source === 'inspection' ? (zh ? '巡检执行' : 'Inspection') : (zh ? '自动化执行' : 'Automation')}
                    </td>

                    {/* Trigger Type */}
                    <td className="py-3.5 px-4 whitespace-nowrap text-left">
                      <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-lg border text-[11px] font-semibold ${tl.badgeCls}`}>
                        <TypeIcon size={10} />
                        <span>{tl.label}</span>
                      </span>
                    </td>

                    {/* Operator */}
                    <td className="py-3.5 px-4 whitespace-nowrap text-left">
                      <div className="flex items-center gap-1.5 text-xs text-slate-600 font-medium">
                        <User size={12} className="text-slate-400" />
                        <span>{log.created_by || 'admin'}</span>
                      </div>
                    </td>

                    {/* Status */}
                    <td className="py-3.5 px-4 whitespace-nowrap text-left">
                      <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full border text-[11px] font-bold ${st.badgeCls}`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${st.dotCls}`} />
                        <span>{st.label}</span>
                      </span>
                    </td>

                    {/* Timing summary */}
                    <td className="py-3.5 px-4 whitespace-nowrap text-left text-xs font-mono text-slate-600">
                      {formatHistoryDate(log.started_at, zh)}
                    </td>
                    <td className="py-3.5 px-4 whitespace-nowrap text-left text-xs font-mono text-slate-600">
                      {formatHistoryDate(log.ended_at, zh)}
                    </td>
                    <td className="py-3.5 px-4 whitespace-nowrap text-left text-xs font-mono text-slate-600">
                      {formatHistoryDuration(getHistoryDurationMs(log, now), zh)}
                    </td>

                    {/* Actions Column (Aligned Right with Matching Padding) */}
                    <TableActionCell className="py-3.5 px-4 text-right pr-6 whitespace-nowrap">
                      <div className="inline-flex items-center justify-end gap-2">
                        
                        {/* Primary View Details Button */}
                        <ActionIconButton
                          type="button"
                          icon={Eye}
                          label={zh ? '查看详情' : 'View details'}
                          variant="accent"
                          onClick={() => onSelectLog(log)}
                        />

                        <ActionIconButton
                          type="button"
                          icon={FileSpreadsheet}
                          label={zh ? '导出 Excel 表格' : 'Export Excel spreadsheet'}
                          variant="success"
                          onClick={() => onExport(log.id, 'xlsx', log.source, log.name, log.started_at)}
                        />
                        <ActionIconButton
                          type="button"
                          icon={Globe}
                          label={zh ? '导出 HTML 网页' : 'Export HTML page'}
                          variant="accent"
                          onClick={() => onExport(log.id, 'html', log.source, log.name, log.started_at)}
                        />
                      </div>
                    </TableActionCell>
                  </tr>
                );
              })}
            </tbody>
          </DataTable>
        ) : (
          <div className="flex min-h-[320px] flex-col items-center justify-center gap-3 px-6 py-20 text-center text-slate-400">
            <div className="w-12 h-12 rounded-2xl bg-slate-50 border border-slate-100 flex items-center justify-center text-slate-400 shadow-2xs">
              <Activity size={22} />
            </div>
            <div>
              <p className="text-sm font-bold text-slate-700">{zh ? '暂无历史执行记录' : 'No history found'}</p>
              <p className="text-xs text-slate-400 mt-1">{zh ? '执行记录将在自动化任务或巡检运行后自动显示在此' : 'Records will appear here after task execution'}</p>
            </div>
          </div>
        )}
      </div>

      {/* ── Pagination Footer ──────────────────────────────────────── */}
      {total > 0 && (
        <div className="px-6 py-3 border-t border-slate-100 bg-white">
          <Pagination
            currentPage={page}
            totalItems={total}
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
