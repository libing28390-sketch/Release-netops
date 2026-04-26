import React from 'react';
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
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
  onSelectExecution: (execution: PlaybookExecution) => Promise<void> | void;
  onDeleteExecution: (execution: PlaybookExecution) => Promise<void> | void;
  onExecDevicesStatusFilterChange: (value: string) => Promise<void> | void;
  onExecDevicesPageChange: (page: number) => Promise<void> | void;
  onSelectExecDevice: (deviceId: string) => Promise<void> | void;
  onCloseDeviceDetail: () => void;
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
}) => {
  const isZh = language === 'zh';

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

      <div className="flex-1 grid grid-cols-1 md:grid-cols-12 gap-5 overflow-hidden">
        <div className="md:col-span-4 flex flex-col bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden">
          <div className="border-b border-black/5 bg-black/[0.01]">
            <div className="px-4 pt-3 pb-2 flex items-center justify-between">
              <h3 className="text-[10px] font-bold uppercase tracking-widest text-black/40">
                {playbookHistoryTotal > 0 ? `${playbookHistoryTotal} ${t('executions')}` : `${playbookExecutions.length} ${t('executions')}`}
              </h3>
            </div>
            <div className="px-3 pb-2">
              <div className="relative">
                <Search size={11} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-black/25" />
                <input
                  type="text"
                  value={playbookHistoryScenarioSearch}
                  onChange={(event) => {
                    onScenarioSearchChange(event.target.value);
                    onHistoryPageChange(1);
                    void onRefreshHistory(1, playbookHistoryStatusFilter, event.target.value);
                  }}
                  placeholder={isZh ? '搜索场景名称...' : 'Search scenario...'}
                  className="w-full text-[11px] pl-7 pr-7 py-1.5 rounded-lg bg-black/[0.03] border border-black/5 focus:outline-none focus:border-black/15 focus:bg-white transition-all placeholder:text-black/20"
                />
                {playbookHistoryScenarioSearch && (
                  <button
                    onClick={() => {
                      onScenarioSearchChange('');
                      onHistoryPageChange(1);
                      void onRefreshHistory(1, playbookHistoryStatusFilter, '');
                    }}
                    title={isZh ? '清空搜索' : 'Clear search'}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-black/25 hover:text-black/50"
                  >
                    <X size={11} />
                  </button>
                )}
              </div>
            </div>
            <div className="px-3 pb-2.5 flex items-center gap-1 flex-wrap">
              {[
                { key: 'all', label: isZh ? '全部' : 'All', cls: 'bg-black/10 text-black/70' },
                { key: 'success', label: '✓', cls: 'bg-emerald-100 text-emerald-700' },
                { key: 'failed', label: '✗', cls: 'bg-red-100 text-red-700' },
                { key: 'partial_failure', label: isZh ? '部分' : 'Partial', cls: 'bg-amber-100 text-amber-700' },
                { key: 'dry_run_complete', label: 'DRY', cls: 'bg-cyan-100 text-cyan-700' },
              ].map((filterItem) => (
                <button
                  key={filterItem.key}
                  onClick={() => {
                    onHistoryStatusFilterChange(filterItem.key);
                    onHistoryPageChange(1);
                    void onRefreshHistory(1, filterItem.key, playbookHistoryScenarioSearch);
                  }}
                  className={`text-[9px] font-bold px-2 py-0.5 rounded-md transition-all ${
                    playbookHistoryStatusFilter === filterItem.key ? `${filterItem.cls} shadow-sm` : 'text-black/30 hover:bg-black/[0.04]'
                  }`}
                >
                  {filterItem.label}
                </button>
              ))}
            </div>
          </div>
          <div className="flex-1 overflow-auto custom-scrollbar">
            {playbookExecutions.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-black/20 p-8">
                <History size={28} strokeWidth={1} />
                <p className="mt-2 text-xs">{t('noExecutions')}</p>
              </div>
            ) : playbookExecutions.map((execution) => {
              const isLive = execution.id === activeExecutionId && executionStatus === 'running';
              const accentColor = execution.status === 'success'
                ? 'bg-emerald-400'
                : execution.status === 'running' || execution.status === 'pending'
                  ? 'bg-blue-400'
                  : execution.status === 'dry_run_complete'
                    ? 'bg-amber-400'
                    : 'bg-red-400';
              const deviceCount = execution.total_devices || (() => {
                try {
                  return JSON.parse(execution.device_ids || '[]').length;
                } catch {
                  return 0;
                }
              })();

              return (
                <button
                  key={execution.id}
                  onClick={() => void onSelectExecution(execution)}
                  className={`w-full text-left border-b border-black/5 transition-all flex group/row ${
                    activeExecutionId === execution.id ? 'bg-black/[0.04]' : 'hover:bg-black/[0.015]'
                  }`}
                >
                  <div className={`w-1 shrink-0 ${activeExecutionId === execution.id ? accentColor : 'bg-transparent'}`} />
                  <div className="flex-1 p-3.5 pl-3 min-w-0">
                    <div className="flex items-center gap-2">
                      {isLive && <span className="w-2 h-2 rounded-full bg-[#00bceb] animate-pulse shrink-0" />}
                      <span className="text-xs font-bold truncate">{execution.scenario_name}</span>
                      {execution._type === 'job' && <span className="text-[8px] font-bold uppercase px-1.5 py-0.5 rounded bg-cyan-50 text-cyan-600 shrink-0">DIRECT</span>}
                      <span className={`ml-auto shrink-0 text-[9px] font-bold uppercase px-2 py-0.5 rounded-full ${
                        execution.status === 'success' ? 'bg-emerald-50 text-emerald-600' :
                        execution.status === 'running' || execution.status === 'pending' ? 'bg-blue-50 text-blue-600' :
                        execution.status === 'dry_run_complete' ? 'bg-amber-50 text-amber-600' :
                        'bg-red-50 text-red-600'
                      }`}>{execution._type === 'job' ? execution.status : (execution.dry_run ? 'DRY-RUN' : execution.status?.replace(/_/g, ' '))}</span>
                      {execution._type !== 'job' && !isLive && (
                        <button
                          title={isZh ? '删除此记录' : 'Delete this record'}
                          onClick={(event) => {
                            event.stopPropagation();
                            void onDeleteExecution(execution);
                          }}
                          className="ml-1 shrink-0 p-1 rounded-md text-black/0 group-hover/row:text-black/25 hover:!text-red-500 hover:!bg-red-50 transition-all"
                        >
                          <Trash2 size={11} />
                        </button>
                      )}
                    </div>
                    <div className="flex items-center gap-2.5 mt-1.5 text-[10px] text-black/35">
                      {execution._type === 'job'
                        ? <span className="truncate">{devices.find((device) => device.id === execution.device_id)?.hostname || `Device #${execution.device_id}`}</span>
                        : <span className="flex items-center gap-0.5"><Server size={9} />{deviceCount}</span>}
                      <span className="text-black/15">·</span>
                      <span className="truncate">{new Date(execution.created_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
                      {(execution.success_count || 0) > 0 && <span className="text-emerald-500">✓{execution.success_count}</span>}
                      {(execution.failed_count || 0) > 0 && <span className="text-red-500">✗{execution.failed_count}</span>}
                    </div>
                  </div>
                </button>
            );
          })}
        </div>
        {playbookHistoryTotal > 20 && (
            <div className="px-3 py-2.5 border-t border-black/5 bg-black/[0.01]">
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

        <div className="md:col-span-8 flex flex-col bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden relative">
          {activeExecutionId && executionStatus === 'running' ? (
            <div className="flex flex-col h-full">
              <div className="p-4 border-b border-black/5 bg-black/[0.01] flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-[#00bceb] animate-pulse" />
                  <h3 className="text-xs font-bold">{t('liveExecution')}</h3>
                  <span className="text-[10px] text-black/30 font-mono">{activeExecutionId.slice(0, 8)}...</span>
                </div>
                <span className="text-[9px] font-bold uppercase text-blue-600 bg-blue-50 px-2 py-0.5 rounded-full">{t('running')}</span>
              </div>
              <div className="flex-1 overflow-auto bg-[#1E1E1E] font-mono text-xs p-4 space-y-1">
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
                      {message.type === 'phase_start' && `│  ⏳ ${message.phase?.replace('_', ' ').toUpperCase()} — ${message.commands?.length || 0} command(s) ${message.dry_run ? '[DRY-RUN]' : ''}`}
                      {message.type === 'phase_done' && `│  ✓ ${message.phase?.replace('_', ' ').toUpperCase()} ${message.dry_run ? '[DRY-RUN]' : '— done'}`}
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
            </div>
          ) : activeExecutionId ? (
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

              if (execution._type === 'job') {
                const device = devices.find((item) => item.id === execution.device_id);
                return (
                  <div className="flex flex-col h-full">
                    <div className="p-4 border-b border-black/5 bg-black/[0.01]">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h3 className="text-sm font-bold">{execution.task_name}</h3>
                        <span className="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded-full bg-cyan-50 text-cyan-600">DIRECT</span>
                        <span className={`text-[9px] font-bold uppercase px-2 py-0.5 rounded-full ${
                          execution.status === 'success' ? 'bg-emerald-50 text-emerald-600' :
                          execution.status === 'failed' || execution.status === 'blocked' ? 'bg-red-50 text-red-600' :
                          execution.status === 'running' ? 'bg-blue-50 text-blue-600' :
                          'bg-gray-50 text-gray-600'
                        }`}>{execution.status}</span>
                      </div>
                      <p className="text-[10px] text-black/40 mt-0.5">
                        {device?.hostname || `Device #${execution.device_id}`}{device?.ip_address ? ` (${device.ip_address})` : ''} · {new Date(execution.created_at).toLocaleString()}
                      </p>
                    </div>
                    <div className="flex-1 overflow-auto p-4">
                      <pre className="text-[11px] font-mono text-black/60 bg-black/[0.02] rounded-xl p-3 whitespace-pre-wrap min-h-full">{execution.output || 'No output'}</pre>
                    </div>
                  </div>
                );
              }

              const totalDevices = execution.total_devices || (() => {
                try {
                  return JSON.parse(execution.device_ids || '[]').length;
                } catch {
                  return 0;
                }
              })();
              const successCount = execution.success_count || 0;
              const failedCount = execution.failed_count || 0;
              const partialCount = execution.partial_count || 0;
              const durationSec = execution.duration_ms ? (execution.duration_ms / 1000).toFixed(1) : null;
              const statusBadge = execution.status === 'success'
                ? 'bg-emerald-50 text-emerald-600'
                : execution.status === 'dry_run_complete'
                  ? 'bg-amber-50 text-amber-600'
                  : 'bg-red-50 text-red-600';

              return (
                <div className="flex flex-col h-full">
                  <div className="p-5 border-b border-black/5 bg-gradient-to-r from-black/[0.015] to-transparent">
                    <div className="flex items-center gap-3 mb-2">
                      <h3 className="text-base font-bold tracking-tight">{execution.scenario_name}</h3>
                      <span className={`text-[9px] font-bold uppercase px-2.5 py-1 rounded-full ${statusBadge}`}>{execution.dry_run ? 'DRY-RUN' : execution.status?.replace(/_/g, ' ')}</span>
                    </div>
                    <div className="flex items-center gap-4 text-[10px] text-black/40">
                      <span className="flex items-center gap-1"><Server size={10} />{totalDevices} {isZh ? '台设备' : 'devices'}</span>
                      <span className="flex items-center gap-1"><User size={10} />{execution.author}</span>
                      <span className="flex items-center gap-1"><Clock size={10} />{new Date(execution.created_at).toLocaleString()}</span>
                      {durationSec && <span className="flex items-center gap-1">⏱ {durationSec}s</span>}
                    </div>
                    {totalDevices > 0 && (
                      <div className="flex gap-2 mt-3">
                        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-50 border border-emerald-100">
                          <CheckCircle2 size={11} className="text-emerald-500" />
                          <span className="text-[11px] font-bold text-emerald-700">{successCount}</span>
                          <span className="text-[9px] text-emerald-500">{isZh ? '成功' : 'OK'}</span>
                        </div>
                        {failedCount > 0 && (
                          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-50 border border-red-100">
                            <XCircle size={11} className="text-red-500" />
                            <span className="text-[11px] font-bold text-red-700">{failedCount}</span>
                            <span className="text-[9px] text-red-500">{isZh ? '失败' : 'Failed'}</span>
                          </div>
                        )}
                        {partialCount > 0 && (
                          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-50 border border-amber-100">
                            <AlertTriangle size={11} className="text-amber-500" />
                            <span className="text-[11px] font-bold text-amber-700">{partialCount}</span>
                            <span className="text-[9px] text-amber-500">{isZh ? '部分' : 'Partial'}</span>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="px-4 py-2.5 border-b border-black/5 flex items-center gap-1.5 flex-wrap bg-black/[0.008]">
                    {[
                      { key: 'all', label: isZh ? '全部' : 'All', activeCls: 'bg-black/10 text-black/70', icon: null },
                      { key: 'success', label: isZh ? '成功' : 'Success', activeCls: 'bg-emerald-100 text-emerald-700', icon: '✓' },
                      { key: 'failed', label: isZh ? '失败' : 'Failed', activeCls: 'bg-red-100 text-red-700', icon: '✗' },
                      { key: 'error', label: isZh ? '错误' : 'Error', activeCls: 'bg-orange-100 text-orange-700', icon: '!' },
                      { key: 'post_check_failed', label: isZh ? '检查失败' : 'Check Failed', activeCls: 'bg-amber-100 text-amber-700', icon: '⚠' },
                    ].map((statusItem) => (
                      <button
                        key={statusItem.key}
                        onClick={() => void onExecDevicesStatusFilterChange(statusItem.key)}
                        className={`text-[10px] font-semibold px-2.5 py-1 rounded-lg transition-all flex items-center gap-1 ${
                          selectedExecDevicesStatusFilter === statusItem.key
                            ? `${statusItem.activeCls} shadow-sm`
                            : 'text-black/35 hover:bg-black/[0.04] hover:text-black/50'
                        }`}
                      >
                        {statusItem.icon && <span className="text-[9px]">{statusItem.icon}</span>}
                        {statusItem.key === 'all' ? `${statusItem.label} (${selectedExecDevicesTotal})` : statusItem.label}
                      </button>
                    ))}
                  </div>
                  <div className="flex-1 overflow-auto p-4 space-y-3 custom-scrollbar">
                    {selectedExecDevicesLoading ? (
                      <div className="flex items-center justify-center py-8">
                        <RotateCcw size={16} className="animate-spin text-black/30" />
                      </div>
                    ) : selectedExecDevices.length === 0 ? (
                      <div className="text-center py-12 text-black/20">
                        <Search size={24} strokeWidth={1} className="mx-auto mb-2 text-black/15" />
                        <p className="text-xs">{isZh ? '没有匹配的设备' : 'No matching devices'}</p>
                      </div>
                    ) : selectedExecDevices.map((device) => {
                      const isOk = device.status === 'success';
                      const borderCls = isOk ? 'border-emerald-100 hover:border-emerald-200' : 'border-red-100 hover:border-red-200';
                      const bgCls = isOk ? 'bg-emerald-50/30' : 'bg-red-50/30';
                      const iconBgCls = isOk ? 'bg-emerald-100' : 'bg-red-100';
                      const statusBadgeCls = isOk ? 'bg-emerald-50 text-emerald-600' : 'bg-red-50 text-red-600';
                      return (
                        <button
                          key={device.device_id}
                          onClick={() => void onSelectExecDevice(device.device_id)}
                          className={`w-full rounded-xl border overflow-hidden text-left transition-all group hover:shadow-md ${borderCls}`}
                        >
                          <div className={`flex items-center justify-between px-4 py-3 ${bgCls}`}>
                            <div className="flex items-center gap-2.5">
                              <div className={`w-7 h-7 rounded-lg flex items-center justify-center ${iconBgCls}`}>
                                {isOk ? <CheckCircle2 size={13} className="text-emerald-600" /> : <XCircle size={13} className="text-red-600" />}
                              </div>
                              <div>
                                <span className="text-xs font-bold text-black/75 block">{device.hostname}</span>
                                {device.ip_address && <span className="text-[10px] text-black/30">{device.ip_address}</span>}
                              </div>
                            </div>
                            <div className="flex items-center gap-2.5">
                              {(device.duration_ms || 0) > 0 && (
                                <span className="text-[10px] text-black/25 flex items-center gap-0.5">
                                  <Clock size={9} />{((device.duration_ms || 0) / 1000).toFixed(1)}s
                                </span>
                              )}
                              <span className={`text-[9px] font-bold uppercase px-2 py-0.5 rounded-full ${statusBadgeCls}`}>
                                {device.status?.replace(/_/g, ' ')}
                              </span>
                              <ChevronRight size={12} className="text-black/15 group-hover:text-black/30 transition-colors" />
                            </div>
                          </div>
                          {device.error_message && (
                            <div className="px-4 py-2 bg-red-50/50 border-t border-red-100/50">
                              <p className="text-[10px] text-red-600 font-mono truncate flex items-center gap-1">
                                <AlertCircle size={9} className="shrink-0" />{device.error_message}
                              </p>
                            </div>
                          )}
                        </button>
                      );
                    })}
                  </div>
                  {selectedExecDevicesTotal > 20 && (
                    <div className="px-4 py-3 border-t border-black/5 bg-black/[0.01]">
                      <Pagination
                        currentPage={selectedExecDevicesPage}
                        totalItems={selectedExecDevicesTotal}
                        itemsPerPage={20}
                        onPageChange={onExecDevicesPageChange}
                        language={language}
                      />
                    </div>
                  )}
                  {(selectedDeviceDetail || selectedDeviceDetailLoading) && (
                    <div className="absolute inset-0 bg-white z-10 flex flex-col rounded-2xl">
                      <div className="p-4 border-b border-black/5 flex items-center gap-3 bg-gradient-to-r from-black/[0.015] to-transparent">
                        <button onClick={onCloseDeviceDetail} className="p-1.5 rounded-lg hover:bg-black/5 transition-colors" title="Back">
                          <ChevronLeft size={14} />
                        </button>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-bold truncate">{selectedDeviceDetail?.hostname || '...'}</span>
                            {selectedDeviceDetail?.ip_address && <span className="text-[10px] text-black/30">{selectedDeviceDetail.ip_address}</span>}
                            {selectedDeviceDetail?.status && (
                              <span className={`text-[9px] font-bold uppercase px-2 py-0.5 rounded-full ${
                                selectedDeviceDetail.status === 'success' ? 'bg-emerald-50 text-emerald-600' : 'bg-red-50 text-red-600'
                              }`}>{selectedDeviceDetail.status.replace(/_/g, ' ')}</span>
                            )}
                          </div>
                          {(selectedDeviceDetail?.duration_ms || 0) > 0 && (
                            <p className="text-[10px] text-black/30 mt-0.5">⏱ {((selectedDeviceDetail?.duration_ms || 0) / 1000).toFixed(1)}s</p>
                          )}
                        </div>
                      </div>
                      {selectedDeviceDetailLoading ? (
                        <div className="flex-1 flex items-center justify-center"><RotateCcw size={16} className="animate-spin text-black/30" /></div>
                      ) : selectedDeviceDetail && (
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
                      )}
                    </div>
                  )}
                </div>
              );
            })()
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
    </div>
  );
};

export default AutomationHistoryTab;