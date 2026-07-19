import React from 'react';
import { motion } from 'motion/react';
import { CheckCircle2, AlertTriangle, XCircle, RotateCcw, Terminal, ExternalLink, Plus } from 'lucide-react';
import type { DeviceExecutionState, DeviceExecutionPhase } from '../types';

interface ExecutionResultsStepProps {
  isZh: boolean;
  wsCompleteMsg: any;
  deviceStatusMap: Record<string, DeviceExecutionState>;
  targetCount: number;
  isQuickPlaybookRunning: boolean;
  quickExecutionResult: any;
  quickPlaybookScenario: any;
  logEndRef: React.RefObject<HTMLDivElement | null>;
  onNavigate: (path: string) => void;
  handleNewTask: () => void;
}

export const ExecutionResultsStep: React.FC<ExecutionResultsStepProps> = ({
  isZh,
  wsCompleteMsg,
  deviceStatusMap,
  targetCount,
  isQuickPlaybookRunning,
  quickExecutionResult,
  quickPlaybookScenario,
  logEndRef,
  onNavigate,
  handleNewTask,
}) => {
  const completeMsg = wsCompleteMsg;
  const deviceEntries = Object.entries(deviceStatusMap) as Array<[string, DeviceExecutionState]>;
  const successCount = completeMsg?.summary?.success ?? deviceEntries.filter(([, s]) => s.status === 'success').length;
  const failedCount =
    completeMsg?.summary?.failed ?? deviceEntries.filter(([, s]) => s.status === 'failed' || s.status === 'partial_failure').length;
  const runningCount = deviceEntries.filter(([, s]) => s.status === 'running').length;
  const totalDevices = Math.max(targetCount, deviceEntries.length);
  const progressPct = totalDevices > 0 ? ((successCount + failedCount) / totalDevices) * 100 : 0;

  const isDone = !isQuickPlaybookRunning && (completeMsg || quickExecutionResult);
  const overallStatus = isDone ? (failedCount === 0 ? 'success' : failedCount < totalDevices ? 'partial' : 'failed') : 'running';

  const scenarioTitle = quickExecutionResult
    ? isZh
      ? quickExecutionResult.scenarioNameZh || quickExecutionResult.scenarioName
      : quickExecutionResult.scenarioName
    : quickPlaybookScenario
    ? isZh
      ? quickPlaybookScenario.name_zh || quickPlaybookScenario.name
      : quickPlaybookScenario.name
    : '';

  return (
    <motion.div
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 20 }}
      transition={{ duration: 0.2 }}
      className="h-full flex flex-col gap-3"
    >
      {/* Execution status header */}
      <div
        className={`flex-shrink-0 rounded-2xl border shadow-sm overflow-hidden ${
          overallStatus === 'success'
            ? 'bg-gradient-to-r from-emerald-50 to-teal-50 border-emerald-200'
            : overallStatus === 'partial'
            ? 'bg-gradient-to-r from-amber-50 to-orange-50 border-amber-200'
            : overallStatus === 'failed'
            ? 'bg-gradient-to-r from-red-50 to-rose-50 border-red-200'
            : 'bg-gradient-to-r from-cyan-50 to-cyan-100/50 border-cyan-200'
        }`}
      >
        <div className="px-5 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            {isQuickPlaybookRunning ? (
              <div className="w-8 h-8 rounded-lg bg-cyan-500 flex items-center justify-center">
                <RotateCcw size={16} className="text-white animate-spin" />
              </div>
            ) : overallStatus === 'success' ? (
              <div className="w-8 h-8 rounded-lg bg-emerald-500 flex items-center justify-center">
                <CheckCircle2 size={16} className="text-white" />
              </div>
            ) : overallStatus === 'partial' ? (
              <div className="w-8 h-8 rounded-lg bg-amber-500 flex items-center justify-center">
                <AlertTriangle size={16} className="text-white" />
              </div>
            ) : (
              <div className="w-8 h-8 rounded-lg bg-red-500 flex items-center justify-center">
                <XCircle size={16} className="text-white" />
              </div>
            )}
            <div>
              <p className="text-sm font-bold text-gray-800">{scenarioTitle}</p>
              <p className="text-[11px] text-gray-500">
                {isQuickPlaybookRunning
                  ? isZh
                    ? `正在执行... ${successCount + failedCount}/${totalDevices}`
                    : `Running... ${successCount + failedCount}/${totalDevices}`
                  : isDone
                  ? isZh
                    ? `执行完成 · ${successCount} 成功 · ${failedCount} 失败`
                    : `Done · ${successCount} success · ${failedCount} failed`
                  : isZh
                  ? '已提交执行请求'
                  : 'Submitted'}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            {quickExecutionResult?.dryRun && (
              <span className="text-xs font-bold px-2.5 py-1 rounded-lg bg-amber-100 text-amber-700 border border-amber-200">DRY-RUN</span>
            )}
            <div className="flex items-center gap-2">
              <span className="flex items-center gap-1.5 text-xs font-bold text-emerald-700 bg-emerald-100 px-2.5 py-1 rounded-lg">
                <CheckCircle2 size={12} /> {successCount}
              </span>
              {failedCount > 0 && (
                <span className="flex items-center gap-1.5 text-xs font-bold text-red-700 bg-red-100 px-2.5 py-1 rounded-lg">
                  <XCircle size={12} /> {failedCount}
                </span>
              )}
              {runningCount > 0 && (
                <span className="flex items-center gap-1.5 text-xs font-bold text-cyan-700 bg-cyan-100 px-2.5 py-1 rounded-lg">
                  <RotateCcw size={12} className="animate-spin" /> {runningCount}
                </span>
              )}
            </div>
            {isDone && totalDevices > 0 && (
              <div className="flex items-center gap-2">
                <div className="relative w-10 h-10">
                  <svg className="w-10 h-10 -rotate-90" viewBox="0 0 36 36">
                    <circle cx="18" cy="18" r="15" fill="none" stroke="#e5e7eb" strokeWidth="3" />
                    <circle
                      cx="18"
                      cy="18"
                      r="15"
                      fill="none"
                      stroke={failedCount === 0 ? '#10b981' : failedCount < totalDevices ? '#f59e0b' : '#ef4444'}
                      strokeWidth="3"
                      strokeLinecap="round"
                      strokeDasharray={`${(successCount / totalDevices) * 94.2} 94.2`}
                    />
                  </svg>
                  <span className="absolute inset-0 flex items-center justify-center text-[9px] font-bold text-gray-600">
                    {Math.round((successCount / totalDevices) * 100)}%
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>
        {isQuickPlaybookRunning && (
          <div className="h-1 bg-cyan-100">
            <div
              className="h-full bg-gradient-to-r from-cyan-500 to-teal-400 transition-all duration-500 ease-out"
              style={{ width: `${Math.max(progressPct, 5)}%` }}
            />
          </div>
        )}
      </div>

      {/* Device results + terminal */}
      <div className="flex-1 min-h-0 flex gap-3 overflow-hidden">
        {/* Left: Device status cards */}
        <div className="w-[340px] flex-shrink-0 flex flex-col bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
          <div className="px-4 py-2.5 border-b border-gray-100 bg-gray-50/50">
            <span className="text-[10px] font-bold uppercase tracking-widest text-gray-400">
              {isZh ? '设备执行状态' : 'Device Status'}
            </span>
            <span className="text-[10px] font-mono text-gray-300 ml-2">
              {deviceEntries.length}/{totalDevices}
            </span>
          </div>
          <div className="flex-1 min-h-0 overflow-auto p-3 space-y-2">
            {deviceEntries.length === 0 && isQuickPlaybookRunning && (
              <div className="flex flex-col items-center justify-center h-32 gap-3">
                <RotateCcw size={24} className="text-cyan-400 animate-spin" />
                <p className="text-xs text-gray-400">{isZh ? '等待设备响应...' : 'Waiting for device response...'}</p>
              </div>
            )}
            {deviceEntries.length === 0 && !isQuickPlaybookRunning && isDone && (
              <div className="flex flex-col items-center justify-center h-32 gap-3 text-gray-400">
                <AlertTriangle size={24} className="text-amber-400" />
                <p className="text-xs font-semibold">{isZh ? '未接收到设备执行事件' : 'No device events received'}</p>
                <p className="text-[10px] text-gray-300 max-w-[200px] text-center">
                  {isZh ? 'WebSocket 连接可能中断，请查看执行历史获取详细结果。' : 'WebSocket may have disconnected. Check execution history for details.'}
                </p>
                <button onClick={() => onNavigate('/automation/queries')} className="text-[11px] text-cyan-600 hover:text-cyan-700 font-semibold mt-1">
                  {isZh ? '查看执行历史 →' : 'View History →'}
                </button>
              </div>
            )}
            {deviceEntries.map(([deviceId, deviceState]) => (
              <div
                key={deviceId}
                className={`rounded-xl border-2 p-3 transition-all ${
                  deviceState.status === 'running'
                    ? 'border-cyan-200 bg-cyan-50/40'
                    : deviceState.status === 'success'
                    ? 'border-emerald-200 bg-emerald-50/40'
                    : deviceState.status === 'partial_failure'
                    ? 'border-amber-200 bg-amber-50/40'
                    : 'border-red-200 bg-red-50/40'
                }`}
              >
                <div className="flex items-center gap-2 mb-1.5">
                  {deviceState.status === 'running' ? (
                    <RotateCcw size={13} className="text-cyan-500 animate-spin flex-shrink-0" />
                  ) : deviceState.status === 'success' ? (
                    <CheckCircle2 size={13} className="text-emerald-500 flex-shrink-0" />
                  ) : deviceState.status === 'partial_failure' ? (
                    <AlertTriangle size={13} className="text-amber-500 flex-shrink-0" />
                  ) : (
                    <XCircle size={13} className="text-red-500 flex-shrink-0" />
                  )}
                  <span className="text-xs font-bold text-gray-700 truncate">{deviceState.hostname}</span>
                </div>
                {Object.keys(deviceState.phases).length > 0 && (
                  <div className="flex flex-wrap gap-1 pl-5">
                    {(Object.entries(deviceState.phases) as Array<[string, DeviceExecutionPhase]>).map(([phase, ps]) => (
                      <span
                        key={phase}
                        className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${
                          ps.success ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'
                        }`}
                      >
                        {ps.success ? '✓' : '✗'} {phase}
                      </span>
                    ))}
                  </div>
                )}
                {deviceState.error && (
                  <p className="text-[10px] text-red-600 pl-5 font-mono mt-1 truncate" title={deviceState.error}>
                    {deviceState.error}
                  </p>
                )}
              </div>
            ))}
            <div ref={logEndRef} />
          </div>
        </div>

        {/* Right: Terminal-style execution log */}
        <div className="flex-1 min-w-0 flex flex-col bg-[#0d1117] rounded-2xl border border-white/5 shadow-lg overflow-hidden">
          <div className="flex-shrink-0 flex items-center justify-between px-4 py-2.5 bg-[#161b22] border-b border-white/5">
            <div className="flex items-center gap-2">
              <div className="flex gap-[5px]">
                <span className="w-[9px] h-[9px] rounded-full bg-[#ff5f57]/80" />
                <span className="w-[9px] h-[9px] rounded-full bg-[#febc2e]/80" />
                <span className="w-[9px] h-[9px] rounded-full bg-[#28c840]/80" />
              </div>
              <Terminal size={12} className="text-white/40" />
              <span className="text-[10px] font-bold text-white/50 uppercase tracking-wider">{isZh ? '执行日志' : 'Execution Log'}</span>
              {isQuickPlaybookRunning && (
                <span className="flex items-center gap-1 text-[10px] text-cyan-400 font-bold">
                  <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
                  LIVE
                </span>
              )}
            </div>
          </div>
          <div className="netops-terminal-font flex-1 min-h-0 overflow-auto p-4 text-[12px] leading-relaxed">
            {deviceEntries.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full gap-3 text-white/15">
                <Terminal size={32} strokeWidth={1} />
                <p className="font-sans text-sm">
                  {isQuickPlaybookRunning ? (isZh ? '等待执行输出...' : 'Waiting for output...') : isZh ? '未收到执行日志，请查看执行历史' : 'No logs received. Check execution history'}
                </p>
              </div>
            ) : (
              deviceEntries.map(([deviceId, ds]) => (
                <div key={deviceId} className="mb-4 last:mb-0">
                  <div className="flex items-center gap-2 mb-1.5">
                    <span
                      className={`w-2 h-2 rounded-full ${
                        ds.status === 'running' ? 'bg-cyan-400 animate-pulse' : ds.status === 'success' ? 'bg-emerald-400' : 'bg-red-400'
                      }`}
                    />
                    <span className="text-cyan-300 font-bold">[{ds.hostname}]</span>
                    <span
                      className={`text-[10px] uppercase font-bold ${
                        ds.status === 'running' ? 'text-cyan-400' : ds.status === 'success' ? 'text-emerald-400' : 'text-red-400'
                      }`}
                    >
                      {ds.status}
                    </span>
                  </div>
                  {Object.entries(ds.phases).map(([phase, ps]) => (
                    <div key={phase} className="pl-4 mb-1">
                      <span className={`${ps.success ? 'text-emerald-400' : 'text-red-400'}`}>
                        {ps.success ? '✓' : '✗'} {phase}
                      </span>
                      {ps.output && (
                        <pre className="text-white/40 pl-3 text-[11px] whitespace-pre-wrap mt-0.5 max-h-24 overflow-hidden">
                          {ps.output.slice(0, 500)}
                        </pre>
                      )}
                    </div>
                  ))}
                  {ds.error && <div className="pl-4 text-red-400 text-[11px]">⚠ {ds.error}</div>}
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Bottom action bar */}
      {!isQuickPlaybookRunning && (
        <div className="flex-shrink-0 flex items-center justify-between bg-white rounded-2xl border border-gray-100 shadow-sm px-5 py-3">
          <div className="flex items-center gap-3 text-sm text-gray-600">
            {isDone && (
              <>
                <span className="font-bold">{isZh ? '执行完成' : 'Execution Complete'}</span>
                <span className="text-gray-300">|</span>
                <span>
                  {isZh
                    ? `成功率：${Math.round((successCount / Math.max(totalDevices, 1)) * 100)}%`
                    : `Success: ${Math.round((successCount / Math.max(totalDevices, 1)) * 100)}%`}
                </span>
                {failedCount > 0 && <span className="text-red-500 text-xs font-bold">{failedCount} {isZh ? '台设备失败' : 'device(s) failed'}</span>}
              </>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => onNavigate('/automation/queries')}
              className="px-4 py-2 rounded-xl text-xs font-bold border border-gray-200 hover:bg-gray-50 transition-all flex items-center gap-1.5"
            >
              <ExternalLink size={12} />
              {isZh ? '查看完整历史' : 'Full History'}
            </button>
            <button
              onClick={handleNewTask}
              className="px-5 py-2 rounded-xl text-xs font-bold text-white bg-gradient-to-r from-cyan-500 to-teal-500 shadow-lg shadow-cyan-500/25 hover:shadow-cyan-500/40 transition-all flex items-center gap-1.5"
            >
              <Plus size={13} />
              {isZh ? '新建任务' : 'New Task'}
            </button>
          </div>
        </div>
      )}
    </motion.div>
  );
};
