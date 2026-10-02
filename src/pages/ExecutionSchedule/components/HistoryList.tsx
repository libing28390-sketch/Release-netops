import { DataTable } from '../../../components/DataTable';
import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  Activity, RotateCcw, Play, CalendarClock, Clock, Eye,
  FileText, FileSpreadsheet, FileJson, Download,
  Search, Globe, User, CheckCircle2, AlertCircle, RefreshCw
} from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import Pagination from '../../../components/Pagination';
import { ActionIconButton } from '../../../components/ui/ActionIconButton';
import type { UnifiedExecutionLog } from '../types';
import { useEscapeClose } from '../../../hooks/useEscapeClose';

import { TableActionCell, TableActionHeader } from '../../../components/ui/TableActionColumn';
interface HistoryListProps {
  zh: boolean;
  language: string;
  logs: UnifiedExecutionLog[];
  loading: boolean;
  page: number;
  pageSize: number;
  onPageChange: (p: number) => void;
  onPageSizeChange: (s: number) => void;
  executionTypeFilter: 'all' | 'manual' | 'plan' | 'job';
  onFilterChange: (f: 'all' | 'manual' | 'plan' | 'job') => void;
  onSelectLog: (log: UnifiedExecutionLog) => void;
  onExport: (logId: string, format: string, source: string) => void;
  loadAllLogs: () => Promise<UnifiedExecutionLog[]>;
}

// ── Export Dropdown Component ─────────────────────────────
const ExportDropdown: React.FC<{
  zh: boolean;
  logId: string;
  source: string;
  onExport: (logId: string, format: string, source: string) => void;
}> = ({ zh, logId, source, onExport }) => {
  const [open, setOpen] = useState(false);
  useEscapeClose(open, () => setOpen(false));
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
      <ActionIconButton
        icon={Download}
        label={zh ? '导出执行记录' : 'Export execution log'}
        tooltip={zh ? '导出' : 'Export'}
        variant="accent"
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen(!open)}
      />

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: -4 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: -4 }}
            transition={{ duration: 0.12 }}
            role="menu"
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
  zh, language, logs, loading, page, pageSize,
  onPageChange, onPageSizeChange, executionTypeFilter, onFilterChange,
  onSelectLog, onExport, loadAllLogs,
}) => {
  const [searchQuery, setSearchQuery] = useState('');

  const searchedLogs = React.useMemo(() => {
    if (!searchQuery.trim()) return logs;
    const q = searchQuery.toLowerCase();
    return logs.filter(log =>
      (log.name || '').toLowerCase().includes(q) ||
      (log.created_by || '').toLowerCase().includes(q) ||
      (log.status || '').toLowerCase().includes(q)
    );
  }, [logs, searchQuery]);
  const displayLogs = React.useMemo(() => {
    const start = (page - 1) * pageSize;
    return searchedLogs.slice(start, start + pageSize);
  }, [searchedLogs, page, pageSize]);

  useEffect(() => { onPageChange(1); }, [searchQuery, onPageChange]);

  const exportHistory = useCallback(async () => {
    const allLogs = (await loadAllLogs()).filter((log) => executionTypeFilter === 'all' || log.trigger_type === executionTypeFilter);
    const query = searchQuery.trim().toLowerCase();
    const matchingLogs = query ? allLogs.filter((log) =>
      (log.name || '').toLowerCase().includes(query)
      || (log.created_by || '').toLowerCase().includes(query)
      || (log.status || '').toLowerCase().includes(query)) : allLogs;
    const typeLabels: Record<string, string> = {
      manual: zh ? '手动执行' : 'Manual',
      plan: zh ? '执行计划' : 'Execution Plan',
      job: zh ? '定时作业' : 'Scheduled Job',
    };
    const statusLabels: Record<string, string> = {
      completed: zh ? '已完成' : 'Completed',
      success: zh ? '已完成' : 'Completed',
      running: zh ? '执行中' : 'Running',
      failed: zh ? '已失败' : 'Failed',
      awaiting_approval: zh ? '待审批' : 'Awaiting approval',
      approval_rejected: zh ? '审批拒绝' : 'Approval rejected',
    };
    return {
      headers: zh
        ? ['触发时间', '任务名称', '来源', '执行方式', '状态', '设备数', '成功设备数', '失败设备数', '健康评分', '执行人']
        : ['Triggered At', 'Task Name', 'Source', 'Type', 'Status', 'Total Devices', 'Successful Devices', 'Failed Devices', 'Health Score', 'Operator'],
      rows: matchingLogs.map((log) => [
        log.started_at ? new Date(log.started_at).toLocaleString(zh ? 'zh-CN' : 'en-US', { hour12: false }) : '--',
        log.name || '--',
        log.source === 'inspection' ? (zh ? '巡检执行' : 'Inspection') : (zh ? '自动化执行' : 'Automation'),
        typeLabels[log.trigger_type] || log.trigger_type,
        statusLabels[log.status] || log.status,
        log.total_devices ?? 0,
        log.success_count ?? 0,
        log.failed_count ?? 0,
        log.avg_health_score == null ? '' : Number(log.avg_health_score).toFixed(1),
        log.created_by || 'admin',
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
          <DataTable unstyled exportConfig={{ filename: 'execution-history', language: zh ? 'zh' : 'en', disabled: displayLogs.length === 0, exportData: exportHistory }} className="w-full min-w-[1200px] table-fixed border-collapse">
            <colgroup>
              <col style={{ width: '12%' }} /> {/* 触发时间 */}
              <col style={{ width: '19%' }} /> {/* 任务名称 */}
              <col style={{ width: '8%' }} /> {/* 来源 */}
              <col style={{ width: '10%' }} /> {/* 执行方式 */}
              <col style={{ width: '9%' }} /> {/* 状态 */}
              <col style={{ width: '7%' }} /> {/* 设备数 */}
              <col style={{ width: '7%' }} /> {/* 成功 */}
              <col style={{ width: '7%' }} /> {/* 失败 */}
              <col style={{ width: '7%' }} /> {/* 健康评分 */}
              <col style={{ width: '7%' }} /> {/* 执行人 */}
              <col style={{ width: '7%' }} /> {/* 操作 */}
            </colgroup>
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50/60 text-[11px] font-bold uppercase tracking-wider text-slate-500">
                <th className="py-3.5 px-4 text-left">{zh ? '触发时间' : 'Triggered At'}</th>
                <th className="py-3.5 px-4 text-left">{zh ? '任务名称' : 'Task Name'}</th>
                <th className="py-3.5 px-4 text-left">{zh ? '来源' : 'Source'}</th>
                <th className="py-3.5 px-4 text-left">{zh ? '执行方式' : 'Type'}</th>
                <th className="py-3.5 px-4 text-left">{zh ? '状态' : 'Status'}</th>
                <th className="py-3.5 px-4 text-left">{zh ? '设备数' : 'Total Devices'}</th>
                <th className="py-3.5 px-4 text-left">{zh ? '成功设备数' : 'Successful Devices'}</th>
                <th className="py-3.5 px-4 text-left">{zh ? '失败设备数' : 'Failed Devices'}</th>
                <th className="py-3.5 px-4 text-left">{zh ? '健康评分' : 'Health Score'}</th>
                <th className="py-3.5 px-4 text-left">{zh ? '执行人' : 'Operator'}</th>
                <TableActionHeader className="py-3.5 px-4 text-right pr-6">{zh ? '操作' : 'Actions'}</TableActionHeader>
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
                      </div>
                    </td>

                    {/* Source */}
                    <td className="py-3.5 px-4 text-xs text-slate-500">
                      {log.source === 'inspection' ? (zh ? '巡检执行' : 'Inspection') : (zh ? '自动化执行' : 'Automation')}
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

                    {/* Device counts and health score */}
                    <td className="py-3.5 px-4 text-xs font-bold text-slate-700 font-mono">{log.total_devices}</td>
                    <td className="py-3.5 px-4 text-xs font-semibold text-emerald-600 font-mono">{log.success_count}</td>
                    <td className="py-3.5 px-4 text-xs font-semibold text-rose-600 font-mono">{log.failed_count}</td>
                    <td className={`py-3.5 px-4 text-xs font-bold tabular-nums ${
                      (log.avg_health_score || 0) >= 80 ? 'text-emerald-600' : (log.avg_health_score || 0) >= 60 ? 'text-amber-600' : 'text-rose-600'
                    }`}>
                      {log.source === 'inspection' ? (log.avg_health_score?.toFixed(1) ?? '—') : '—'}
                    </td>

                    {/* Operator */}
                    <td className="py-3.5 px-4 whitespace-nowrap text-left">
                      <div className="flex items-center gap-1.5 text-xs text-slate-600 font-medium">
                        <User size={12} className="text-slate-400" />
                        <span>{log.created_by || 'admin'}</span>
                      </div>
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

                        {/* Elegant Export Dropdown */}
                        <ExportDropdown
                          zh={zh}
                          logId={log.id}
                          source={log.source}
                          onExport={onExport}
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
      {searchedLogs.length > 0 && (
        <div className="px-6 py-3 border-t border-slate-100 bg-white">
          <Pagination
            currentPage={page}
            totalItems={searchedLogs.length}
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
