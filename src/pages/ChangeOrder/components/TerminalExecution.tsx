import React from 'react';
import { Zap, CheckCircle2, XCircle, RefreshCw } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';

interface Props {
  language: string;
  executeModal: {
    order: any;
    phase: 'confirm' | 'running' | 'done';
    output: string;
    error: string;
    success: boolean;
  } | null;
  setExecuteModal: (m: any) => void;
  runOrderCommands: () => void;
  handleTransition: (orderId: string, status: string, payload?: any) => void;
}

export const TerminalExecution: React.FC<Props> = ({
  language,
  executeModal,
  setExecuteModal,
  runOrderCommands,
  handleTransition,
}) => {
  const zh = language === 'zh';

  if (!executeModal) return null;

  return (
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.15 }}
        onMouseDown={(e) => {
          // Block backdrop click while running
          if (e.target === e.currentTarget && executeModal.phase !== 'running') {
            setExecuteModal(null);
          }
        }}
      >
        <motion.div
          initial={{ scale: 0.96, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.96, opacity: 0 }}
          className="bg-white rounded-2xl shadow-xl w-full max-w-3xl flex flex-col overflow-hidden"
        >
          <div className="px-6 py-5 border-b border-black/5 bg-[linear-gradient(to_right,#f4fbfc_0%,#ffffff_100%)] flex items-center gap-3">
            <Zap size={18} className="text-[#00bceb]" />
            <div className="flex-1 min-w-0">
              <h3 className="text-lg font-bold text-[#164e63]">
                {zh ? '下发命令到目标设备' : 'Push commands to target devices'}
              </h3>
              <p className="text-xs text-black/45 mt-0.5 font-medium">
                {zh
                  ? `工单 ${executeModal.order.order_number} · ${(executeModal.order.target_devices || []).length} 台设备`
                  : `Order ${executeModal.order.order_number} · ${(executeModal.order.target_devices || []).length} device(s)`}
              </p>
            </div>
          </div>

          <div className="px-6 py-5 space-y-4 max-h-[70vh] overflow-y-auto">
            {/* Devices */}
            <div>
              <p className="text-xs font-semibold text-black/50 mb-2">{zh ? '目标设备' : 'Target Devices'}</p>
              <div className="flex flex-wrap gap-2">
                {(executeModal.order.target_devices || []).map((dev: any, i: number) => (
                  <span key={i} className="inline-flex items-center gap-1.5 rounded-xl bg-cyan-50/80 px-3 py-1.5 text-xs font-medium text-cyan-800 ring-1 ring-cyan-200/70">
                    {dev.hostname || (zh ? '未命名' : 'Unnamed')}
                    <span className="text-cyan-600/70">({dev.ip_address || ''})</span>
                  </span>
                ))}
              </div>
            </div>

            {/* Commands */}
            <div>
              <p className="text-xs font-semibold text-black/50 mb-2">
                {zh ? '即将下发的配置命令' : 'Commands to be pushed'}
                <span className="ml-2 text-black/30 font-normal">
                  ({(executeModal.order.commands || []).length} {zh ? '条' : 'lines'})
                </span>
              </p>
              <div className="bg-slate-900 rounded-xl p-3 font-mono text-xs text-emerald-400 leading-relaxed whitespace-pre-wrap break-all max-h-48 overflow-y-auto">
                {(executeModal.order.commands || []).map((cmd: string, i: number) => (
                  <div key={i} className="flex">
                    <span className="text-slate-500 select-none mr-2 w-6 text-right">{i + 1}</span>
                    <span className="flex-1">{cmd}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Output / Error */}
            {executeModal.phase !== 'confirm' && (
              <div>
                <p className="text-xs font-semibold text-black/50 mb-2 flex items-center gap-2">
                  {zh ? '执行结果' : 'Execution Output'}
                  {executeModal.phase === 'running' && (
                    <RefreshCw size={12} className="animate-spin text-[#00bceb]" />
                  )}
                  {executeModal.phase === 'done' && (
                    executeModal.success
                      ? <CheckCircle2 size={12} className="text-emerald-500" />
                      : <XCircle size={12} className="text-rose-500" />
                  )}
                </p>
                {executeModal.error && (
                  <div className="rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-700 ring-1 ring-rose-200 mb-2 whitespace-pre-line font-medium">
                    {executeModal.error}
                  </div>
                )}
                {executeModal.output && (
                  <div className="bg-slate-900 rounded-xl p-3 font-mono text-xs text-slate-200 leading-relaxed whitespace-pre-wrap break-all max-h-72 overflow-y-auto">
                    {executeModal.output}
                  </div>
                )}
              </div>
            )}

            {executeModal.phase === 'confirm' && (
              <div className="rounded-xl bg-amber-50 px-3 py-2.5 text-xs text-amber-800 ring-1 ring-amber-200 leading-relaxed font-medium">
                {zh
                  ? '⚠ 命令将通过自动化引擎以管理员权限直接下发到上述设备。请确认命令清单和目标设备无误后再执行。'
                  : '⚠ Commands will be pushed to the listed devices with admin credentials via the automation engine. Confirm before proceeding.'}
              </div>
            )}
          </div>

          <div className="flex items-center justify-end gap-3 px-6 py-4 bg-[#f8fafc] border-t border-black/5">
            {executeModal.phase === 'confirm' && (
              <>
                <button
                  type="button"
                  onClick={() => setExecuteModal(null)}
                  className="px-4 py-2 rounded-xl border border-black/10 text-sm font-semibold text-black/50 hover:bg-black/5 transition-all"
                >
                  {zh ? '取消' : 'Cancel'}
                </button>
                <button
                  type="button"
                  onClick={runOrderCommands}
                  className="px-4 py-2 rounded-xl bg-[#00bceb] text-white text-sm font-bold shadow-sm hover:bg-[#0096bd] transition-all flex items-center gap-2"
                >
                  <Zap size={14} />
                  {zh ? '确认下发' : 'Confirm & Push'}
                </button>
              </>
            )}
            {executeModal.phase === 'running' && (
              <button disabled className="px-4 py-2 rounded-xl bg-black/10 text-black/40 text-sm font-bold cursor-not-allowed flex items-center gap-2">
                <RefreshCw size={14} className="animate-spin" />
                {zh ? '执行中...' : 'Running...'}
              </button>
            )}
            {executeModal.phase === 'done' && (
              <>
                <button
                  type="button"
                  onClick={() => setExecuteModal(null)}
                  className="px-4 py-2 rounded-xl border border-black/10 text-sm font-semibold text-black/50 hover:bg-black/5 transition-all"
                >
                  {zh ? '关闭' : 'Close'}
                </button>
                {!executeModal.success && (
                  <button
                    type="button"
                    onClick={runOrderCommands}
                    className="px-4 py-2 rounded-xl bg-amber-500 text-white text-sm font-bold shadow-sm hover:bg-amber-600 transition-all flex items-center gap-2"
                  >
                    <RefreshCw size={14} />
                    {zh ? '重试' : 'Retry'}
                  </button>
                )}
                {executeModal.success && (
                  <button
                    type="button"
                    onClick={() => {
                      const orderId = executeModal.order.id;
                      const summary = executeModal.output.slice(0, 4000);
                      setExecuteModal(null);
                      handleTransition(orderId, 'completed', { result_summary: summary });
                    }}
                    className="px-4 py-2 rounded-xl bg-emerald-500 text-white text-sm font-bold shadow-sm hover:bg-emerald-600 transition-all flex items-center gap-2"
                  >
                    <CheckCircle2 size={14} />
                    {zh ? '标记完成并保存输出' : 'Mark Completed & Save Output'}
                  </button>
                )}
              </>
            )}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
};
