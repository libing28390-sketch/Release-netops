import React from 'react';
import {
  Activity, RotateCcw, Play, CalendarClock, Clock, Eye,
  FileText, FileSpreadsheet, FileJson,
} from 'lucide-react';
import Pagination from '../../../components/Pagination';
import type { UnifiedExecutionLog } from '../types';

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
    <div className="rounded-2xl border border-black/5 bg-white shadow-sm overflow-hidden min-h-[500px] flex flex-col">
      <div className="px-6 py-4 border-b border-black/5 bg-black/[0.01] flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-indigo-50 flex items-center justify-center">
            <Activity size={16} className="text-indigo-600" />
          </div>
          <h3 className="text-sm font-bold text-[#164e63]">{zh ? '执行流水历史' : 'Execution Logs'}</h3>
        </div>
        
        <div className="flex items-center gap-4">
          {/* Type Filter Buttons */}
          <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-xl">
            {(['all', 'manual', 'plan', 'job'] as const).map(type => {
              const labels = {
                all: zh ? '全部' : 'All',
                manual: zh ? '手动执行' : 'Manual',
                plan: zh ? '执行计划' : 'Plan',
                job: zh ? '定时作业' : 'Job',
              };
              return (
                <button
                  key={type}
                  onClick={() => onFilterChange(type)}
                  className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-all ${
                    executionTypeFilter === type 
                      ? 'bg-white text-[#164e63] shadow-sm' 
                      : 'text-black/50 hover:text-black/70'
                  }`}
                >
                  {labels[type]}
                </button>
              );
            })}
          </div>

          <div className="text-[11px] font-bold text-black/25 uppercase tracking-widest tabular-nums">
            {logs.length} {zh ? '条记录' : 'Logs'}
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto max-h-[calc(100vh-380px)] custom-scrollbar">
        {loading ? (
          <div className="h-full flex flex-col items-center justify-center py-24 text-black/20 gap-3">
            <RotateCcw size={32} className="animate-spin opacity-20" />
            <span className="text-sm font-medium">{zh ? '获取流水中...' : 'Loading history...'}</span>
          </div>
        ) : paginatedLogs.length > 0 ? (
          <table className="nx-data-table min-w-[1000px] text-left">
            <thead className="sticky top-0 bg-slate-50 border-b border-black/5 z-10">
              <tr className="bg-black/[0.01]">
                <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{zh ? '触发时间' : 'Triggered At'}</th>
                <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{zh ? '任务名称' : 'Task Name'}</th>
                <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{zh ? '执行方式' : 'Type'}</th>
                <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{zh ? '状态' : 'Status'}</th>
                <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{zh ? '执行概况' : 'Execution Summary'}</th>
                <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{zh ? '执行人' : 'Operator'}</th>
                <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider text-right">{zh ? '操作' : 'Actions'}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-black/[0.03]">
              {paginatedLogs.map(log => {
                const statusMap: Record<string, { label: string; cls: string; dot: string }> = {
                  completed: { label: zh ? '已完成' : 'Completed', cls: 'bg-emerald-50 text-emerald-700', dot: 'bg-emerald-500' },
                  success: { label: zh ? '已完成' : 'Completed', cls: 'bg-emerald-50 text-emerald-700', dot: 'bg-emerald-500' },
                  running: { label: zh ? '执行中' : 'Running', cls: 'bg-cyan-50 text-cyan-700', dot: 'bg-cyan-500' },
                  failed: { label: zh ? '已失败' : 'Failed', cls: 'bg-red-50 text-red-700', dot: 'bg-red-500' },
                  awaiting_approval: { label: zh ? '待审批' : 'Awaiting approval', cls: 'bg-violet-50 text-violet-700', dot: 'bg-violet-500' },
                  approval_rejected: { label: zh ? '审批拒绝' : 'Approval rejected', cls: 'bg-rose-50 text-rose-700', dot: 'bg-rose-500' },
                };
                const st = statusMap[log.status] || { label: log.status, cls: 'bg-slate-50 text-slate-600', dot: 'bg-slate-400' };
                
                const typeLabels = {
                  manual: { label: zh ? '手动执行' : 'Manual', cls: 'bg-violet-50 text-violet-600 border-violet-100' },
                  plan: { label: zh ? '执行计划' : 'Execution Plan', cls: 'bg-blue-50 text-blue-600 border-blue-100' },
                  job: { label: zh ? '定时作业' : 'Scheduled Job', cls: 'bg-amber-50 text-amber-600 border-amber-100' },
                };
                const tl = typeLabels[log.trigger_type] || { label: log.trigger_type, cls: 'bg-slate-50 text-slate-600 border-slate-100' };

                return (
                  <tr key={`${log.source}-${log.id}`} className="hover:bg-indigo-50/20 transition-colors">
                    <td className="px-6 py-4 text-[13px] text-[#164e63] font-mono whitespace-nowrap">
                      {new Date(log.started_at).toLocaleString(zh ? 'zh-CN' : 'en-US', { hour12: false })}
                    </td>
                    <td className="px-6 py-4 text-xs font-bold text-black/80">
                      {log.name}
                    </td>
                    <td className="px-6 py-4">
                      <span className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wide border ${tl.cls}`}>
                        {log.trigger_type === 'manual' ? <Play size={10} /> : log.trigger_type === 'plan' ? <CalendarClock size={10} /> : <Clock size={10} />}
                        {tl.label}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-bold ${st.cls}`}>
                        <div className={`w-1.5 h-1.5 rounded-full ${log.status === 'running' ? 'animate-pulse' : ''} ${st.dot}`} />
                        {st.label}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex flex-col">
                        <span className="text-xs font-bold text-black/60">{log.total_devices} {zh ? '台设备' : 'Devices'}</span>
                        <div className="flex items-center gap-1.5 mt-1">
                          {log.source === 'inspection' ? (
                            <>
                              <span className="text-[10px] text-black/40">{zh ? '平均分' : 'Avg Score'}:</span>
                              <span className={`text-[11px] font-black tabular-nums ${
                              (log.avg_health_score || 0) >= 80 ? 'text-emerald-600' : (log.avg_health_score || 0) >= 60 ? 'text-amber-600' : 'text-red-600'
                              }`}>
                                {log.avg_health_score?.toFixed(1) ?? '—'}
                              </span>
                            </>
                          ) : (
                            <>
                              <div className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                              <span className="text-[10px] text-emerald-600 font-bold">{log.success_count}</span>
                              <div className="w-1.5 h-1.5 rounded-full bg-red-400 ml-1" />
                              <span className="text-[10px] text-red-600 font-bold">{log.failed_count}</span>
                            </>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <span className="text-xs font-bold text-black/40">{log.created_by}</span>
                    </td>
                    <td className="px-6 py-4 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => onSelectLog(log)}
                          className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-bold text-cyan-600 border border-cyan-100 bg-cyan-50/20 hover:bg-cyan-50 transition-all active:scale-95"
                        >
                          <Eye size={12} />
                          {zh ? '查看' : 'View'}
                        </button>
                        
                        {/* ── R7.1: 标准化导出按钮组 ── */}
                        <div className="flex items-center gap-1 ml-2 pl-2 border-l border-black/5">
                          <button
                            onClick={() => onExport(log.id, 'html', log.source)}
                            className="p-1.5 rounded-lg text-indigo-600 hover:bg-indigo-50 transition-all active:scale-90"
                            title={zh ? '导出 HTML' : 'Export HTML'}
                          >
                            <FileText size={14} />
                          </button>
                          <button
                            onClick={() => onExport(log.id, 'pdf', log.source)}
                            className="p-1.5 rounded-lg text-rose-600 hover:bg-rose-50 transition-all active:scale-90"
                            title={zh ? '导出 PDF' : 'Export PDF'}
                          >
                            <FileText size={14} />
                          </button>
                          <button
                            onClick={() => onExport(log.id, 'xlsx', log.source)}
                            className="p-1.5 rounded-lg text-emerald-600 hover:bg-emerald-50 transition-all active:scale-90"
                            title={zh ? '导出 Excel' : 'Export Excel'}
                          >
                            <FileSpreadsheet size={14} />
                          </button>
                          <button
                            onClick={() => onExport(log.id, 'json', log.source)}
                            className="p-1.5 rounded-lg text-slate-600 hover:bg-slate-50 transition-all active:scale-90"
                            title={zh ? '导出 JSON' : 'Export JSON'}
                          >
                            <FileJson size={14} />
                          </button>
                        </div>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <div className="h-full flex flex-col items-center justify-center py-32 text-black/20 gap-3">
            <Activity size={48} strokeWidth={1} className="opacity-10" />
            <p className="text-sm font-bold text-black/30">{zh ? '暂无历史执行记录' : 'No history found'}</p>
          </div>
        )}
      </div>

      {logs.length > 0 && (
        <div className="mt-auto">
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
    </div>
  );
};

export default HistoryList;
