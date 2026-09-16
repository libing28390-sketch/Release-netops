import React, { useState, useRef, useEffect } from 'react';
import {
  Activity, RotateCcw, Play, CalendarClock, Clock, Eye,
  FileText, FileSpreadsheet, FileJson, ChevronDown, Download,
  Search, Globe, User, CheckCircle2, AlertCircle, RefreshCw
} from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
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

// ── Export Dropdown Component ─────────────────────────────
const ExportDropdown: React.FC<{
  zh: boolean;
  logId: string;
  source: string;
  onExport: (logId: string, format: string, source: string) => void;
}> = ({ zh, logId, source, onExport }) => {
  const [open, setOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    if (open) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [open]);

  return (
    <div className="relative inline-block text-left" ref={dropdownRef}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-xl border border-slate-200 text-xs font-semibold text-slate-700 bg-white hover:bg-slate-50 hover:text-slate-900 transition-all shadow-2xs active:scale-95"
      >
        <Download size={13} className="text-slate-500" />
        <span>{zh ? '导出' : 'Export'}</span>
        <ChevronDown size={12} className={`text-slate-400 transition-transform duration-200 ${open ? 'rotate-180' : ''}`} />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: -4 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: -4 }}
            transition={{ duration: 0.12 }}
            className="absolute right-0 z-50 mt-1.5 w-44 rounded-xl border border-slate-200 bg-white shadow-xl py-1 overflow-hidden"
          >
            <button
              type="button"
              onClick={() => { onExport(logId, 'pdf', source); setOpen(false); }}
              className="flex w-full items-center gap-2.5 px-3.5 py-2 text-xs text-slate-700 hover:bg-rose-50 hover:text-rose-700 transition-colors text-left"
            >
              <div className="w-5 h-5 rounded-md bg-rose-50 text-rose-600 flex items-center justify-center shrink-0">
                <FileText size={12} />
              </div>
              <div className="flex flex-col">
                <span className="font-semibold">{zh ? 'PDF 报告' : 'PDF Report'}</span>
                <span className="text-[10px] text-slate-400 font-mono">.pdf</span>
              </div>
            </button>

            <button
              type="button"
              onClick={() => { onExport(logId, 'xlsx', source); setOpen(false); }}
              className="flex w-full items-center gap-2.5 px-3.5 py-2 text-xs text-slate-700 hover:bg-emerald-50 hover:text-emerald-700 transition-colors text-left"
            >
              <div className="w-5 h-5 rounded-md bg-emerald-50 text-emerald-600 flex items-center justify-center shrink-0">
                <FileSpreadsheet size={12} />
              </div>
              <div className="flex flex-col">
                <span className="font-semibold">{zh ? 'Excel 表格' : 'Excel Sheet'}</span>
                <span className="text-[10px] text-slate-400 font-mono">.xlsx</span>
              </div>
            </button>

            <button
              type="button"
              onClick={() => { onExport(logId, 'html', source); setOpen(false); }}
              className="flex w-full items-center gap-2.5 px-3.5 py-2 text-xs text-slate-700 hover:bg-cyan-50 hover:text-cyan-700 transition-colors text-left"
            >
              <div className="w-5 h-5 rounded-md bg-cyan-50 text-cyan-600 flex items-center justify-center shrink-0">
                <Globe size={12} />
              </div>
              <div className="flex flex-col">
                <span className="font-semibold">{zh ? 'HTML 网页' : 'HTML Page'}</span>
                <span className="text-[10px] text-slate-400 font-mono">.html</span>
              </div>
            </button>

            <button
              type="button"
              onClick={() => { onExport(logId, 'json', source); setOpen(false); }}
              className="flex w-full items-center gap-2.5 px-3.5 py-2 text-xs text-slate-700 hover:bg-indigo-50 hover:text-indigo-700 transition-colors text-left"
            >
              <div className="w-5 h-5 rounded-md bg-indigo-50 text-indigo-600 flex items-center justify-center shrink-0">
                <FileJson size={12} />
              </div>
              <div className="flex flex-col">
                <span className="font-semibold">{zh ? 'JSON 数据' : 'JSON Data'}</span>
                <span className="text-[10px] text-slate-400 font-mono">.json</span>
              </div>
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

const HistoryList: React.FC<HistoryListProps> = ({
  zh, language, logs, loading, paginatedLogs, page, pageSize,
  onPageChange, onPageSizeChange, executionTypeFilter, onFilterChange,
  onSelectLog, onExport,
}) => {
  const [searchQuery, setSearchQuery] = useState('');

  const displayLogs = React.useMemo(() => {
    if (!searchQuery.trim()) return paginatedLogs;
    const q = searchQuery.toLowerCase();
    return paginatedLogs.filter(log =>
      (log.name || '').toLowerCase().includes(q) ||
      (log.created_by || '').toLowerCase().includes(q) ||
      (log.status || '').toLowerCase().includes(q)
    );
  }, [paginatedLogs, searchQuery]);

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
                  {logs.length}
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
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
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
        ) : displayLogs.length > 0 ? (
          <table className="w-full table-fixed border-collapse">
            <colgroup>
              <col style={{ width: '18%' }} /> {/* 触发时间 */}
              <col style={{ width: '22%' }} /> {/* 任务名称 */}
              <col style={{ width: '13%' }} /> {/* 执行方式 */}
              <col style={{ width: '12%' }} /> {/* 状态 */}
              <col style={{ width: '15%' }} /> {/* 执行概况 */}
              <col style={{ width: '10%' }} /> {/* 执行人 */}
              <col style={{ width: '10%' }} /> {/* 操作 */}
            </colgroup>
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50/60 text-[11px] font-bold uppercase tracking-wider text-slate-500">
                <th className="py-3.5 px-4 text-left">{zh ? '触发时间' : 'Triggered At'}</th>
                <th className="py-3.5 px-4 text-left">{zh ? '任务名称' : 'Task Name'}</th>
                <th className="py-3.5 px-4 text-left">{zh ? '执行方式' : 'Type'}</th>
                <th className="py-3.5 px-4 text-left">{zh ? '状态' : 'Status'}</th>
                <th className="py-3.5 px-4 text-left">{zh ? '执行概况' : 'Summary'}</th>
                <th className="py-3.5 px-4 text-left">{zh ? '执行人' : 'Operator'}</th>
                <th className="py-3.5 px-4 text-right pr-6">{zh ? '操作' : 'Actions'}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {displayLogs.map(log => {
                const statusMap: Record<string, { label: string; badgeCls: string; dotCls: string }> = {
                  completed: { label: zh ? '已完成' : 'Completed', badgeCls: 'bg-emerald-50 text-emerald-700 border-emerald-200/60', dotCls: 'bg-emerald-500' },
                  success: { label: zh ? '已完成' : 'Completed', badgeCls: 'bg-emerald-50 text-emerald-700 border-emerald-200/60', dotCls: 'bg-emerald-500' },
                  running: { label: zh ? '执行中' : 'Running', badgeCls: 'bg-blue-50 text-blue-700 border-blue-200/60', dotCls: 'bg-blue-500 animate-pulse' },
                  failed: { label: zh ? '已失败' : 'Failed', badgeCls: 'bg-rose-50 text-rose-700 border-rose-200/60', dotCls: 'bg-rose-500' },
                  awaiting_approval: { label: zh ? '待审批' : 'Awaiting approval', badgeCls: 'bg-amber-50 text-amber-700 border-amber-200/60', dotCls: 'bg-amber-500' },
                  approval_rejected: { label: zh ? '审批拒绝' : 'Approval rejected', badgeCls: 'bg-rose-50 text-rose-700 border-rose-200/60', dotCls: 'bg-rose-500' },
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
                    
                    {/* Trigger Time */}
                    <td className="py-3.5 px-4 whitespace-nowrap text-left">
                      <span className="text-xs font-mono text-slate-600">
                        {new Date(log.started_at).toLocaleString(zh ? 'zh-CN' : 'en-US', { hour12: false })}
                      </span>
                    </td>

                    {/* Task Name */}
                    <td className="py-3.5 px-4 text-left">
                      <div className="min-w-0">
                        <div className="text-xs font-bold text-slate-900 truncate">{log.name}</div>
                        <div className="text-[10px] text-slate-400 mt-0.5">
                          {log.source === 'inspection' ? (zh ? '巡检执行' : 'Inspection') : (zh ? '自动化执行' : 'Automation')}
                        </div>
                      </div>
                    </td>

                    {/* Trigger Type */}
                    <td className="py-3.5 px-4 whitespace-nowrap text-left">
                      <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-lg border text-[11px] font-semibold ${tl.badgeCls}`}>
                        <TypeIcon size={10} />
                        <span>{tl.label}</span>
                      </span>
                    </td>

                    {/* Status */}
                    <td className="py-3.5 px-4 whitespace-nowrap text-left">
                      <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full border text-[11px] font-bold ${st.badgeCls}`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${st.dotCls}`} />
                        <span>{st.label}</span>
                      </span>
                    </td>

                    {/* Execution Summary */}
                    <td className="py-3.5 px-4 text-left">
                      <div className="flex flex-col gap-0.5">
                        <span className="text-xs font-bold text-slate-800 font-mono">
                          {log.total_devices} <span className="text-[10px] font-normal text-slate-400 font-sans">{zh ? '台设备' : 'devices'}</span>
                        </span>
                        <div className="flex items-center gap-2 text-[11px] font-mono">
                          {log.source === 'inspection' ? (
                            <div className="flex items-center gap-1 text-[10px]">
                              <span className="text-slate-400 font-sans">{zh ? '评分' : 'Score'}:</span>
                              <span className={`font-bold tabular-nums ${
                                (log.avg_health_score || 0) >= 80 ? 'text-emerald-600' : (log.avg_health_score || 0) >= 60 ? 'text-amber-600' : 'text-rose-600'
                              }`}>
                                {log.avg_health_score?.toFixed(1) ?? '—'}
                              </span>
                            </div>
                          ) : (
                            <>
                              <span className="text-emerald-600 font-semibold flex items-center gap-0.5 text-[10px]">
                                <span className="w-1 h-1 rounded-full bg-emerald-500" />
                                {log.success_count} {zh ? '成功' : 'ok'}
                              </span>
                              {log.failed_count > 0 && (
                                <span className="text-rose-600 font-semibold flex items-center gap-0.5 text-[10px]">
                                  <span className="w-1 h-1 rounded-full bg-rose-500" />
                                  {log.failed_count} {zh ? '失败' : 'failed'}
                                </span>
                              )}
                            </>
                          )}
                        </div>
                      </div>
                    </td>

                    {/* Operator */}
                    <td className="py-3.5 px-4 whitespace-nowrap text-left">
                      <div className="flex items-center gap-1.5 text-xs text-slate-600 font-medium">
                        <User size={12} className="text-slate-400" />
                        <span>{log.created_by || 'admin'}</span>
                      </div>
                    </td>

                    {/* Actions Column (Aligned Right with Matching Padding) */}
                    <td className="py-3.5 px-4 text-right pr-6 whitespace-nowrap">
                      <div className="inline-flex items-center justify-end gap-2">
                        
                        {/* Primary View Details Button */}
                        <button
                          type="button"
                          onClick={() => onSelectLog(log)}
                          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-xl bg-cyan-50 hover:bg-cyan-100/80 text-cyan-700 border border-cyan-200/60 text-xs font-bold transition-all shadow-2xs active:scale-95"
                        >
                          <Eye size={13} className="text-cyan-600" />
                          <span>{zh ? '详情' : 'Details'}</span>
                        </button>

                        {/* Elegant Export Dropdown */}
                        <ExportDropdown
                          zh={zh}
                          logId={log.id}
                          source={log.source}
                          onExport={onExport}
                        />
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
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
      {logs.length > 0 && (
        <div className="px-6 py-3 border-t border-slate-100 bg-white">
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
