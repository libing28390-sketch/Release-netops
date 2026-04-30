import React, { useState, useEffect } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Download,
  History,
  RotateCcw,
  Search,
  Server,
  Trash2,
  User,
  X,
  XCircle,
} from 'lucide-react';
import type { Device } from '../types';
import Pagination from '../components/Pagination';

type WsMessage = {
  type?: string;
  total_devices?: number;
  dry_run?: boolean;
  hostname?: string;
  index?: number;
  total?: number;
  phase?: string;
  commands?: string[];
  output?: { output?: string };
  status?: string;
  device_id?: string;
  error?: string;
  summary?: { success?: number; total?: number; failed?: number };
};

type PlaybookExecution = {
  id: string;
  _type?: 'job' | 'playbook';
  status?: string;
  scenario_name?: string;
  total_devices?: number;
  device_ids?: string;
  device_id?: string;
  created_at: string;
  success_count?: number;
  failed_count?: number;
  partial_count?: number;
  duration_ms?: number;
  dry_run?: boolean;
  task_name?: string;
  output?: string;
  author?: string;
  ip_address?: string;
};

type ExecutionDevice = {
  device_id: string;
  hostname: string;
  ip_address?: string;
  status?: string;
  duration_ms?: number;
  error_message?: string;
};

type ExecutionDeviceDetail = {
  hostname?: string;
  ip_address?: string;
  status?: string;
  duration_ms?: number;
  error_message?: string;
  phases_json?: string;
};

interface AutomationHistoryTabProps {
  t: (key: string) => string;
  language: string;
  devices: Device[];
  playbookExecutions: PlaybookExecution[];
  playbookHistoryTotal: number;
  playbookHistoryPage: number;
  playbookHistoryStatusFilter: string;
  playbookHistoryScenarioSearch: string;
  activeExecutionId: string | null;
  executionStatus: string;
  wsMessages: WsMessage[];
  selectedExecutionLoading: boolean;
  selectedExecutionDetail: PlaybookExecution | null;
  selectedExecDevices: ExecutionDevice[];
  selectedExecDevicesTotal: number;
  selectedExecDevicesPage: number;
  selectedExecDevicesStatusFilter: string;
  selectedExecDevicesLoading: boolean;
  selectedDeviceDetail: ExecutionDeviceDetail | null;
  selectedDeviceDetailLoading: boolean;
  onRefreshHistory: (page?: number, statusFilter?: string, scenarioFilter?: string) => Promise<void> | void;
  onScenarioSearchChange: (value: string) => void;
  onHistoryPageChange: (page: number) => void;
  onHistoryStatusFilterChange: (value: string) => void;
  playbookHistoryPageSize?: number;
  onHistoryPageSizeChange?: (size: number) => void;
  onSelectExecution: (execution: PlaybookExecution) => Promise<void> | void;
  onDeleteExecution: (execution: PlaybookExecution) => Promise<void> | void;
  onExecDevicesStatusFilterChange: (value: string) => Promise<void> | void;
  onExecDevicesPageChange: (page: number) => Promise<void> | void;
  onSelectExecDevice: (deviceId: string) => Promise<void> | void;
  onCloseDeviceDetail: () => void;
  onRerun: (execution: PlaybookExecution) => void;
}

const AutomationHistoryTab: React.FC<AutomationHistoryTabProps> = ({
  t,
  language,
  devices,
  playbookExecutions,
  playbookHistoryTotal,
  playbookHistoryPage,
  playbookHistoryStatusFilter,
  playbookHistoryScenarioSearch,
  activeExecutionId,
  executionStatus,
  wsMessages,
  selectedExecutionLoading,
  selectedExecutionDetail,
  selectedExecDevices,
  selectedExecDevicesTotal,
  selectedExecDevicesPage,
  selectedExecDevicesStatusFilter,
  selectedExecDevicesLoading,
  selectedDeviceDetail,
  selectedDeviceDetailLoading,
  onRefreshHistory,
  onScenarioSearchChange,
  onHistoryPageChange,
  onHistoryStatusFilterChange,
  onSelectExecution,
  onDeleteExecution,
  onExecDevicesStatusFilterChange,
  onExecDevicesPageChange,
  onSelectExecDevice,
  onCloseDeviceDetail,
  onRerun,
}) => {
  const isZh = language === 'zh';
  const [isDetailModalOpen, setIsDetailModalOpen] = useState(false);
  const isLive = !!(activeExecutionId && executionStatus === 'running');

  useEffect(() => {
    if (isLive) {
      setIsDetailModalOpen(true);
    }
  }, [isLive]);

  // Helper mapping for execution status badge
  const getStatusMap = (status?: string) => {
    const statusMap: Record<string, { label: string; cls: string; dot: string }> = {
      success: { label: isZh ? '执行成功' : 'Success', cls: 'bg-emerald-50 text-emerald-700', dot: 'bg-emerald-500' },
      running: { label: isZh ? '执行中' : 'Running', cls: 'bg-cyan-50 text-cyan-700', dot: 'bg-cyan-500 animate-pulse' },
      pending: { label: isZh ? '排队中' : 'Pending', cls: 'bg-blue-50 text-blue-700', dot: 'bg-blue-500' },
      dry_run_complete: { label: isZh ? '模拟完成' : 'Dry-Run', cls: 'bg-amber-50 text-amber-700', dot: 'bg-amber-500' },
    };
    return statusMap[status || ''] || { 
      label: isZh ? '执行失败' : 'Failed', 
      cls: 'bg-red-50 text-red-700 border-red-100', 
      dot: 'bg-red-500' 
    };
  };

  const handleDownloadSummary = () => {
    if (!selectedExecutionDetail) return;
    const dataStr = JSON.stringify(selectedExecutionDetail, null, 2);
    const blob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `execution_summary_${selectedExecutionDetail.id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleDownloadLogStream = () => {
    if (!wsMessages || wsMessages.length === 0) return;
    const logStr = wsMessages
      .map((msg, idx) => {
        let line = `[${idx + 1}] `;
        if (msg.type === 'start') line += `▶ Playbook started — ${msg.total_devices} devices`;
        else if (msg.type === 'device_start') line += `┌─ ${msg.hostname}`;
        else if (msg.type === 'phase_start') line += `│  ⏳ ${msg.phase?.toUpperCase()} commands`;
        else if (msg.type === 'phase_done') line += `│  ✓ ${msg.phase?.toUpperCase()} complete`;
        else if (msg.type === 'device_done') line += `└─ ${msg.hostname} — ${msg.status}`;
        else if (msg.type === 'device_error') line += `✗ ERROR — ${msg.device_id}: ${msg.error}`;
        else if (msg.type === 'complete') line += `\n✦ COMPLETE — Status: ${msg.status}`;
        return line;
      })
      .join('\n');

    const blob = new Blob([logStr], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `live_log_stream_${activeExecutionId}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex justify-between items-end mb-5 flex-shrink-0">
        <div>
          <h2 className="text-2xl font-medium tracking-tight">{t('executionHistory')}</h2>
          <p className="text-sm text-black/40">{t('executionHistoryDesc')}</p>
        </div>
        <button
          onClick={() => void onRefreshHistory()}
          title={isZh ? '刷新执行历史' : 'Refresh execution history'}
          className="p-2 rounded-xl border border-black/10 hover:bg-black/5 transition-all"
        >
          <RotateCcw size={14} />
        </button>
      </div>

      <div className="flex-1 bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden flex flex-col min-h-[500px]">
        {/* Toolbar */}
        <div className="px-6 py-4 border-b border-black/5 bg-black/[0.01] flex items-center justify-between flex-wrap gap-4 flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-indigo-50 flex items-center justify-center">
              <History size={16} className="text-indigo-600" />
            </div>
            <h3 className="text-sm font-bold text-[#164e63]">
              {playbookHistoryTotal > 0 ? `${playbookHistoryTotal} ${isZh ? '条记录' : 'Records'}` : `${playbookExecutions.length} ${isZh ? '条记录' : 'Records'}`}
            </h3>
          </div>
          
          <div className="flex items-center gap-3 flex-wrap">
            {/* Search Input */}
            <div className="relative w-64">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-black/25" />
              <input
                type="text"
                value={playbookHistoryScenarioSearch}
                onChange={(event) => {
                  onScenarioSearchChange(event.target.value);
                  onHistoryPageChange(1);
                  void onRefreshHistory(1, playbookHistoryStatusFilter, event.target.value);
                }}
                placeholder={isZh ? '搜索任务名称...' : 'Search scenario...'}
                className="w-full text-xs pl-9 pr-8 py-2 rounded-xl bg-black/[0.03] border border-transparent focus:outline-none focus:border-black/10 focus:bg-white transition-all shadow-inner"
              />
              {playbookHistoryScenarioSearch && (
                <button
                  onClick={() => {
                    onScenarioSearchChange('');
                    onHistoryPageChange(1);
                    void onRefreshHistory(1, playbookHistoryStatusFilter, '');
                  }}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-black/25 hover:text-black/50"
                >
                  <X size={12} />
                </button>
              )}
            </div>

            {/* Filter Buttons */}
            <div className="flex items-center gap-1.5 p-1 rounded-xl bg-black/[0.03] border border-black/5">
              {[
                { key: 'all', label: isZh ? '全部' : 'All', cls: 'bg-white shadow-sm text-black' },
                { key: 'success', label: isZh ? '成功' : '✓', cls: 'bg-emerald-500 text-white shadow-sm shadow-emerald-500/20' },
                { key: 'failed', label: isZh ? '失败' : '✗', cls: 'bg-red-500 text-white shadow-sm shadow-red-500/20' },
                { key: 'partial_failure', label: isZh ? '部分' : 'Partial', cls: 'bg-amber-500 text-white shadow-sm shadow-amber-500/20' },
                { key: 'dry_run_complete', label: 'DRY', cls: 'bg-cyan-500 text-white shadow-sm shadow-cyan-500/20' },
              ].map((filterItem) => {
                const isActive = playbookHistoryStatusFilter === filterItem.key;
                return (
                  <button
                    key={filterItem.key}
                    onClick={() => {
                      onHistoryStatusFilterChange(filterItem.key);
                      onHistoryPageChange(1);
                      void onRefreshHistory(1, filterItem.key, playbookHistoryScenarioSearch);
                    }}
                    className={`text-[10px] font-bold px-3 py-1.5 rounded-lg transition-all ${
                      isActive ? filterItem.cls : 'text-black/40 hover:text-black/60 hover:bg-white/50'
                    }`}
                  >
                    {filterItem.label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* Table Content */}
        <div className="flex-1 overflow-auto">
          {playbookExecutions.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-black/20 py-24">
              <History size={48} strokeWidth={1} className="opacity-10" />
              <p className="mt-3 text-sm font-medium">{t('noExecutions')}</p>
            </div>
          ) : (
            <table className="w-full text-left border-collapse min-w-[900px]">
              <thead className="sticky top-0 bg-slate-50 border-b border-black/5 z-10">
                <tr className="bg-black/[0.01]">
                  <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{isZh ? '任务名称' : 'Scenario Name'}</th>
                  <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{isZh ? '触发时间' : 'Triggered At'}</th>
                  <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{isZh ? '状态' : 'Status'}</th>
                  <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{isZh ? '设备概况' : 'Devices Info'}</th>
                  <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{isZh ? '执行人' : 'Operator'}</th>
                  <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider text-right">{isZh ? '操作' : 'Actions'}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-black/[0.03]">
                {playbookExecutions.map((execution) => {
                  const isRowLive = execution.id === activeExecutionId && executionStatus === 'running';
                  const deviceCount = execution.total_devices || (() => {
                    try { return JSON.parse(execution.device_ids || '[]').length; } catch { return 0; }
                  })();
                  const st = getStatusMap(execution.status);

                  return (
                    <tr key={execution.id} className="group hover:bg-indigo-50/20 transition-colors">
                      <td className="px-6 py-4">
                        <div className="flex flex-col">
                          <span className="text-sm font-bold text-[#164e63] group-hover:text-cyan-700 transition-colors">
                            {execution.scenario_name || execution.task_name || (isZh ? '快捷命令' : 'Direct Command')}
                          </span>
                          {execution._type === 'job' && (
                            <span className="text-[8px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-cyan-50 text-cyan-600 self-start mt-1">DIRECT</span>
                          )}
                        </div>
                      </td>
                      <td className="px-6 py-4 text-xs font-mono text-black/60 whitespace-nowrap">
                        {new Date(execution.created_at).toLocaleString()}
                      </td>
                      <td className="px-6 py-4">
                        <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-bold ${st.cls}`}>
                          <div className={`w-1.5 h-1.5 rounded-full ${st.dot}`} />
                          {st.label}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-2 text-xs font-bold text-black/60">
                          <span className="flex items-center gap-1"><Server size={12} />{deviceCount}</span>
                          {(execution.success_count || 0) > 0 && <span className="text-emerald-500">✓{execution.success_count}</span>}
                          {(execution.failed_count || 0) > 0 && <span className="text-red-500">✗{execution.failed_count}</span>}
                        </div>
                      </td>
                      <td className="px-6 py-4 text-xs text-black/60 font-medium">
                        {execution.author || 'admin'}
                      </td>
                      <td className="px-6 py-4 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => onRerun(execution)}
                            className="flex items-center gap-1 px-2 py-1.5 text-xs text-amber-600 hover:bg-amber-50 font-bold rounded-lg transition-all"
                            title={isZh ? '重复执行' : 'Rerun'}
                          >
                            <RotateCcw size={14} />
                            <span className="hidden sm:inline">{isZh ? '重试' : 'Retry'}</span>
                          </button>
                          <button
                            onClick={() => {
                              void onSelectExecution(execution);
                              setIsDetailModalOpen(true);
                            }}
                            className="flex items-center gap-1 px-2 py-1.5 text-xs text-[#0e7490] hover:bg-cyan-50 font-bold rounded-lg transition-all"
                          >
                            {isZh ? '详情' : 'Details'}
                          </button>
                          {!isRowLive && (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                void onDeleteExecution(execution);
                              }}
                              className="p-2 rounded-lg text-black/25 hover:text-red-500 hover:bg-red-50 transition-all"
                              title={isZh ? '删除' : 'Delete'}
                            >
                              <Trash2 size={14} />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination footer */}
        {playbookHistoryTotal > 20 && (
          <div className="px-6 py-4 border-t border-black/5 bg-black/[0.01] flex-shrink-0">
            <Pagination
              currentPage={playbookHistoryPage}
              totalItems={playbookHistoryTotal}
              itemsPerPage={20}
              onPageChange={onHistoryPageChange}
              language={language}
            />
          </div>
        )}
      </div>

      {/* Detail Modal */}
      <AnimatePresence>
        {isDetailModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setIsDetailModalOpen(false)}
              className="absolute inset-0 bg-black/50 backdrop-blur-sm"
            />
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
              className="relative bg-white rounded-[2rem] shadow-2xl w-full max-w-6xl h-[90vh] overflow-hidden flex flex-col z-10 border border-black/10"
            >
              {/* Modal Header */}
              <div className="px-6 py-4 border-b border-black/5 flex items-center justify-between bg-black/[0.015] flex-shrink-0">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-indigo-50 flex items-center justify-center text-indigo-600 border border-indigo-100">
                    <History size={18} />
                  </div>
                  <div>
                    <h3 className="text-base font-bold text-[#164e63]">
                      {isLive ? (isZh ? '正在执行详情' : 'Live Execution Log') : (isZh ? '执行历史详情' : 'Execution Log Details')}
                    </h3>
                    <p className="text-[10px] text-black/30 font-mono mt-0.5">ID: {activeExecutionId || selectedExecutionDetail?.id}</p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {!isLive && selectedExecutionDetail && (
                    <button
                      onClick={handleDownloadSummary}
                      title={isZh ? '下载汇总报告' : 'Download Summary'}
                      className="p-2 rounded-xl text-[#0891b2] border border-cyan-100 bg-cyan-50/30 hover:bg-cyan-50 hover:text-[#0e7490] transition-all"
                    >
                      <Download size={16} />
                    </button>
                  )}
                  {isLive && wsMessages.length > 0 && (
                    <button
                      onClick={handleDownloadLogStream}
                      title={isZh ? '导出实时日志' : 'Export Live Stream'}
                      className="p-2 rounded-xl text-[#0891b2] border border-cyan-100 bg-cyan-50/30 hover:bg-cyan-50 hover:text-[#0e7490] transition-all"
                    >
                      <Download size={16} />
                    </button>
                  )}
                  <button
                    onClick={() => setIsDetailModalOpen(false)}
                    className="p-2 rounded-xl text-black/20 hover:bg-black/5 hover:text-black/40 transition-all"
                  >
                    <X size={20} />
                  </button>
                </div>
              </div>

              {/* Modal Content */}
              <div className="flex-1 overflow-hidden relative">
                {isLive ? (
                  /* Live Streaming Panel */
                  <div className="flex flex-col h-full bg-[#1E1E1E] font-mono text-xs p-6 overflow-auto space-y-1">
                    {wsMessages.map((message, index) => {
                      const color =
                        message.type === 'start' ? 'text-blue-400' :
                          message.type === 'device_start' ? 'text-cyan-400' :
                            message.type === 'phase_start' ? 'text-purple-400' :
                              message.type === 'phase_done' ? 'text-emerald-400' :
                                message.type === 'device_done' ? 'text-green-300' :
                                  message.type === 'rollback_start' || message.type === 'rollback_done' ? 'text-red-400' :
                                    message.type === 'device_error' ? 'text-red-500' :
                                      message.type === 'complete' ? 'text-yellow-300' :
                                        'text-[#d4d4d4]';
                      return (
                        <div key={index} className={`${color} leading-5`}>
                          <span className="text-white/20 mr-2">{String(index + 1).padStart(3, ' ')}</span>
                          {message.type === 'start' && `▶ Playbook started — ${message.total_devices} device(s) ${message.dry_run ? '[DRY-RUN]' : ''}`}
                          {message.type === 'device_start' && `┌─ ${message.hostname} (${message.index! + 1}/${message.total})`}
                          {message.type === 'phase_start' && `│  ⏳ ${message.phase?.replace(/_/g, ' ').toUpperCase()} — ${message.commands?.length || 0} command(s) ${message.dry_run ? '[DRY-RUN]' : ''}`}
                          {message.type === 'phase_done' && `│  ✓ ${message.phase?.replace(/_/g, ' ').toUpperCase()} ${message.dry_run ? '[DRY-RUN]' : '— done'}`}
                          {message.type === 'phase_done' && message.output?.output && (
                            <div className="ml-8 text-[#d4d4d4]/60 whitespace-pre-wrap">{message.output.output.slice(0, 500)}</div>
                          )}
                          {message.type === 'device_done' && `└─ ${message.hostname} — ${message.status}`}
                          {message.type === 'rollback_start' && `│  ⚠ ROLLBACK TRIGGERED — ${message.hostname}`}
                          {message.type === 'rollback_done' && `│  ↩ Rollback complete — ${message.hostname}`}
                          {message.type === 'device_error' && `✗ ERROR — ${message.device_id}: ${message.error}`}
                          {message.type === 'complete' && `\n✦ COMPLETE — Status: ${message.status} | Success: ${message.summary?.success}/${message.summary?.total} | Failed: ${message.summary?.failed}`}
                        </div>
                      );
                    })}
                    <div className="h-4" />
                  </div>
                ) : (
                  /* Loaded Results Panel */
                  (() => {
                    if (selectedExecutionLoading) {
                      return (
                        <div className="h-full flex items-center justify-center text-black/30">
                          <RotateCcw size={20} className="animate-spin" />
                        </div>
                      );
                    }

                    const execution = selectedExecutionDetail || playbookExecutions.find((item) => item.id === activeExecutionId);
                    if (!execution) {
                      return <div className="p-8 text-center text-black/20 text-sm">{t('noData')}</div>;
                    }

                    const executionStatusMap: Record<string, { label: string; cls: string }> = {
                      success: { label: isZh ? '成功' : 'Success', cls: 'bg-emerald-500 text-white' },
                      failed: { label: isZh ? '失败' : 'Failed', cls: 'bg-red-500 text-white' },
                      partial_failure: { label: isZh ? '部分失败' : 'Partial Failure', cls: 'bg-amber-500 text-white' },
                      dry_run_complete: { label: 'DRY-RUN', cls: 'bg-cyan-500 text-white' },
                    };
                    const executionSt = executionStatusMap[execution.status || ''] || { label: execution.status || 'Failed', cls: 'bg-red-500 text-white' };

                    return (
                      <div className="flex flex-col md:flex-row h-full">
                        {/* Device List (Left) */}
                        <div className="w-full md:w-5/12 border-r border-black/5 flex flex-col h-full bg-slate-50/50">
                          {/* Left Header */}
                          <div className="p-4 border-b border-black/5 bg-white">
                            <div className="flex items-center justify-between mb-3">
                              <div className="flex items-center gap-2">
                                <span className="text-xs font-bold text-black/50">{isZh ? '设备执行情况' : 'Device Execution'}</span>
                                <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${executionSt.cls}`}>{executionSt.label}</span>
                              </div>
                              <span className="text-[10px] font-mono text-black/40">{new Date(execution.created_at).toLocaleString()}</span>
                            </div>
                            
                            {/* Device List Filters */}
                            <div className="flex items-center gap-2 flex-wrap">
                              {/* Search */}
                              <div className="flex items-center gap-1.5 p-1 rounded-lg bg-black/[0.03] border border-black/5">
                                {[
                                  { key: 'all', label: isZh ? '全部' : 'All' },
                                  { key: 'success', label: isZh ? '成功' : 'Pass' },
                                  { key: 'failed', label: isZh ? '失败' : 'Fail' },
                                ].map((filterItem) => {
                                  const isActive = selectedExecDevicesStatusFilter === filterItem.key;
                                  return (
                                    <button
                                      key={filterItem.key}
                                      onClick={() => void onExecDevicesStatusFilterChange(filterItem.key)}
                                      className={`text-[9px] font-bold px-2.5 py-1 rounded-md transition-all ${
                                        isActive ? 'bg-white shadow-sm text-[#164e63]' : 'text-black/40 hover:text-black/60'
                                      }`}
                                    >
                                      {filterItem.label}
                                    </button>
                                  );
                                })}
                              </div>
                            </div>
                          </div>

                          {/* Device Items */}
                          <div className="flex-1 overflow-auto p-2 space-y-1">
                            {selectedExecDevicesLoading ? (
                              <div className="h-32 flex items-center justify-center text-black/20"><RotateCcw size={16} className="animate-spin" /></div>
                            ) : selectedExecDevices.length === 0 ? (
                              <p className="text-center text-[10px] text-black/20 py-8">{t('noData')}</p>
                            ) : (
                              selectedExecDevices.map((dev) => {
                                const stMap: Record<string, { cls: string; label: string }> = {
                                  success: { cls: 'bg-emerald-500', label: isZh ? '完成' : 'Pass' },
                                  failed: { cls: 'bg-red-500', label: isZh ? '失败' : 'Fail' },
                                  running: { cls: 'bg-cyan-500 animate-pulse', label: isZh ? '执行中' : 'Live' },
                                };
                                const dst = stMap[dev.status || ''] || { cls: 'bg-red-500', label: isZh ? '错误' : 'Fail' };

                                return (
                                  <div
                                    key={dev.device_id}
                                    onClick={() => void onSelectExecDevice(dev.device_id)}
                                    className="flex items-center justify-between p-3 rounded-xl bg-white border border-black/5 hover:border-black/10 hover:shadow-sm cursor-pointer transition-all"
                                  >
                                    <div className="min-w-0">
                                      <p className="text-xs font-bold text-[#164e63] truncate">{dev.hostname}</p>
                                      <p className="text-[10px] text-black/30 font-mono mt-0.5">{dev.ip_address || '0.0.0.0'}</p>
                                    </div>
                                    <div className="flex items-center gap-2 shrink-0">
                                      {dev.duration_ms !== undefined && (
                                        <span className="text-[10px] text-black/40 font-mono">{dev.duration_ms >= 1000 ? `${(dev.duration_ms / 1000).toFixed(1)}s` : `${dev.duration_ms}ms`}</span>
                                      )}
                                      <span className={`text-[9px] font-bold text-white px-2 py-0.5 rounded-md ${dst.cls}`}>{dst.label}</span>
                                    </div>
                                  </div>
                                );
                              })
                            )}
                          </div>

                          {/* Left Pagination */}
                          {selectedExecDevicesTotal > 20 && (
                            <div className="p-3 border-t border-black/5 bg-white flex-shrink-0">
                              <Pagination
                                currentPage={selectedExecDevicesPage}
                                totalItems={selectedExecDevicesTotal}
                                itemsPerPage={20}
                                onPageChange={onExecDevicesPageChange}
                                language={language}
                              />
                            </div>
                          )}
                        </div>

                        {/* Device Detail Output (Right) */}
                        <div className="w-full md:w-7/12 flex flex-col h-full bg-white relative">
                          {selectedDeviceDetailLoading ? (
                            <div className="h-full flex items-center justify-center text-black/30"><RotateCcw size={20} className="animate-spin" /></div>
                          ) : selectedDeviceDetail ? (
                            <div className="flex flex-col h-full">
                              <div className="p-4 border-b border-black/5 bg-black/[0.01] flex-shrink-0">
                                <div className="flex items-center justify-between mb-3">
                                  <div>
                                    <p className="text-xs font-bold text-[#164e63]">{selectedDeviceDetail.hostname}</p>
                                    <p className="text-[10px] font-mono text-black/40 mt-0.5">{selectedDeviceDetail.ip_address}</p>
                                  </div>
                                  <div className="flex items-center gap-2">
                                    {selectedDeviceDetail.duration_ms !== undefined && (
                                      <span className="text-[10px] font-bold px-2 py-1 bg-black/[0.03] text-black/40 rounded-lg">
                                        {selectedDeviceDetail.duration_ms >= 1000 ? `${(selectedDeviceDetail.duration_ms / 1000).toFixed(2)} s` : `${selectedDeviceDetail.duration_ms} ms`}
                                      </span>
                                    )}
                                  </div>
                                </div>

                                {/* Key Device Information */}
                                {(() => {
                                  const dev = devices.find(d => d.hostname === selectedDeviceDetail.hostname || d.ip_address === selectedDeviceDetail.ip_address);
                                  if (!dev) return null;
                                  return (
                                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-1">
                                      <div className="px-2 py-1.5 rounded-lg bg-black/[0.02] border border-black/5">
                                        <p className="text-[9px] font-bold text-black/20 uppercase tracking-tighter">{isZh ? '平台' : 'Platform'}</p>
                                        <p className="text-[10px] font-bold text-black/60 truncate">{dev.platform || '-'}</p>
                                      </div>
                                      <div className="px-2 py-1.5 rounded-lg bg-black/[0.02] border border-black/5">
                                        <p className="text-[9px] font-bold text-black/20 uppercase tracking-tighter">{isZh ? '角色' : 'Role'}</p>
                                        <p className="text-[10px] font-bold text-black/60 truncate">{dev.role || '-'}</p>
                                      </div>
                                      <div className="px-2 py-1.5 rounded-lg bg-black/[0.02] border border-black/5">
                                        <p className="text-[9px] font-bold text-black/20 uppercase tracking-tighter">{isZh ? '站点' : 'Site'}</p>
                                        <p className="text-[10px] font-bold text-black/60 truncate">{dev.site || '-'}</p>
                                      </div>
                                      <div className="px-2 py-1.5 rounded-lg bg-black/[0.02] border border-black/5">
                                        <p className="text-[9px] font-bold text-black/20 uppercase tracking-tighter">{isZh ? '型号' : 'Model'}</p>
                                        <p className="text-[10px] font-bold text-black/60 truncate">{dev.model || '-'}</p>
                                      </div>
                                    </div>
                                  );
                                })()}
                              </div>
                              
                              {/* Output Stream Content */}
                              <div className="flex-1 overflow-auto p-4 space-y-3">
                                {selectedDeviceDetail.error_message && (
                                  <div className="rounded-xl border border-red-100 bg-red-50/60 p-4 flex items-start gap-3">
                                    <div className="w-8 h-8 rounded-lg bg-red-100 flex items-center justify-center shrink-0">
                                      <AlertCircle size={14} className="text-red-600" />
                                    </div>
                                    <div className="min-w-0">
                                      <p className="text-[10px] font-bold text-red-700 mb-1">{isZh ? '错误信息' : 'Error Message'}</p>
                                      <pre className="text-[11px] font-mono text-red-600 whitespace-pre-wrap break-all">{selectedDeviceDetail.error_message}</pre>
                                    </div>
                                  </div>
                                )}
                                {Object.entries((() => {
                                  try {
                                    return JSON.parse(selectedDeviceDetail.phases_json || '{}') as Record<string, { success?: boolean; commands?: string[]; output?: unknown }>;
                                  } catch {
                                    return {};
                                  }
                                })()).map(([phase, data]) => (
                                  <div key={phase} className="rounded-xl border border-black/5 overflow-hidden">
                                    <div className="flex items-center justify-between px-4 py-2.5 bg-black/[0.02] border-b border-black/5">
                                      <p className="text-[10px] font-bold uppercase tracking-wider text-black/40">{phase.replace(/_/g, ' ')}</p>
                                      {data?.success !== undefined && (
                                        <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full ${data.success ? 'bg-emerald-50 text-emerald-600' : 'bg-red-50 text-red-600'}`}>
                                          {data.success ? '✓ Pass' : '✗ Fail'}
                                        </span>
                                      )}
                                    </div>
                                    <div className="px-4 py-3">
                                      {data?.commands && (
                                        <p className="text-[10px] text-black/30 mb-1.5">{Array.isArray(data.commands) ? data.commands.length : 0} {isZh ? '条命令' : 'commands'}</p>
                                      )}
                                      {data?.output ? (
                                        <pre className="text-[11px] font-mono text-black/60 bg-black/[0.02] rounded-lg p-3 max-h-48 overflow-auto whitespace-pre-wrap">{typeof data.output === 'string' ? data.output : JSON.stringify(data.output, null, 2)}</pre>
                                      ) : (
                                        <p className="text-[10px] text-black/20 italic">{isZh ? '无输出' : 'No output'}</p>
                                      )}
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </div>
                          ) : (
                            <div className="h-full flex flex-col items-center justify-center text-black/20 p-8">
                              <div className="w-16 h-16 rounded-2xl bg-black/[0.03] flex items-center justify-center mb-4">
                                <History size={28} strokeWidth={1} className="text-black/15" />
                              </div>
                              <p className="text-sm font-medium text-black/25">{t('selectExecutionHint')}</p>
                              <p className="text-[11px] text-black/15 mt-1">{isZh ? '点击左侧列表查看详情' : 'Click an item from the list to view details'}</p>
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })()
                )}
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default AutomationHistoryTab;