import React from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Shield, X, RotateCcw, AlertTriangle } from 'lucide-react';
import { ScheduledJob, EligibleApprover } from '../types';

interface DeleteApprovalModalProps {
  isOpen: boolean;
  onClose: () => void;
  deleteTarget: ScheduledJob | null;
  deleteReason: string;
  setDeleteReason: (val: string) => void;
  deleteApprover: string;
  setDeleteApprover: (val: string) => void;
  deleteStatus: 'idle' | 'sending' | 'sent' | 'verified';
  deleteCountdown: number;
  deleteCode: string;
  setDeleteCode: (val: string) => void;
  deleteError: string;
  setDeleteError: (val: string) => void;
  approvers: EligibleApprover[];
  requestDeleteApproval: () => void;
  verifyDeleteApproval: () => void;
  executeDeleteJob: () => void;
  language: string;
}

export const DeleteApprovalModal: React.FC<DeleteApprovalModalProps> = ({
  isOpen,
  onClose,
  deleteTarget,
  deleteReason,
  setDeleteReason,
  deleteApprover,
  setDeleteApprover,
  deleteStatus,
  deleteCountdown,
  deleteCode,
  setDeleteCode,
  deleteError,
  setDeleteError,
  approvers,
  requestDeleteApproval,
  verifyDeleteApproval,
  executeDeleteJob,
  language,
}) => {
  const zh = language === 'zh';

  return (
    <AnimatePresence>
      {isOpen && deleteTarget && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
        >
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            className="relative w-full max-w-md rounded-2xl bg-white border border-slate-100 shadow-2xl overflow-hidden z-10"
            onClick={e => e.stopPropagation()}
          >
            <div className="bg-rose-50 border-b border-rose-100 px-6 py-4 flex items-center justify-between">
              <div className="flex items-center gap-2.5 text-rose-700">
                <Shield className="w-5 h-5 text-rose-600" />
                <h3 className="font-bold text-sm">{zh ? '删除安全校验与工单授权' : 'Delete Security Verification'}</h3>
              </div>
              <button onClick={onClose} className="text-rose-400 hover:text-rose-600 p-1">
                <X size={16} />
              </button>
            </div>

            <div className="p-6 space-y-4 text-xs text-slate-600">
              <div className="bg-slate-50 p-3 rounded-xl border border-slate-100 space-y-1">
                <span className="text-[10px] text-slate-400 font-semibold">{zh ? '即将永久删除作业' : 'Target Job to Delete'}</span>
                <div className="font-bold text-slate-800 text-sm truncate">{deleteTarget.name}</div>
                <div className="font-mono text-[10px] text-slate-500">{deleteTarget.cron_expr} · {deleteTarget.action_type}</div>
              </div>

              <div className="space-y-1.5">
                <label className="font-bold text-slate-700 block">{zh ? '删除原因说明' : 'Deletion Reason'}</label>
                <input
                  type="text"
                  value={deleteReason}
                  onChange={e => setDeleteReason(e.target.value)}
                  placeholder={zh ? '输入删除原因...' : 'Enter reason...'}
                  className="w-full px-3 py-2 rounded-xl border border-slate-200 bg-white outline-none focus:border-rose-500 transition-all"
                />
              </div>

              <div className="space-y-1.5">
                <label className="font-bold text-slate-700 block">{zh ? '选择授权审批人' : 'Select Approver'}</label>
                <div className="flex items-center gap-2">
                  <select
                    value={deleteApprover}
                    onChange={e => setDeleteApprover(e.target.value)}
                    disabled={deleteStatus === 'sending' || deleteStatus === 'sent'}
                    className="flex-1 px-3 py-2 rounded-xl border border-slate-200 bg-white outline-none focus:border-rose-500 transition-all"
                  >
                    <option value="">{zh ? '选择审批人...' : 'Select approver...'}</option>
                    {approvers.map(u => (
                      <option key={u.id} value={u.username}>{u.username} ({u.role})</option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={requestDeleteApproval}
                    disabled={!deleteApprover || !deleteReason.trim() || deleteStatus === 'sending' || (deleteStatus === 'sent' && deleteCountdown > 0)}
                    className={`px-3 py-2 rounded-xl font-bold whitespace-nowrap transition-all flex items-center gap-1 ${
                      deleteApprover && deleteReason.trim() && !(deleteStatus === 'sent' && deleteCountdown > 0)
                        ? 'bg-rose-600 text-white hover:bg-rose-700 shadow-sm'
                        : 'bg-slate-100 text-slate-400 cursor-not-allowed'
                    }`}
                  >
                    {deleteStatus === 'sending' ? (
                      <RotateCcw className="w-3 h-3 animate-spin" />
                    ) : deleteStatus === 'sent' && deleteCountdown > 0 ? (
                      `${Math.floor(deleteCountdown / 60)}:${String(deleteCountdown % 60).padStart(2, '0')}`
                    ) : (
                      zh ? '发验证码' : 'Send Code'
                    )}
                  </button>
                </div>
              </div>

              {deleteStatus === 'sent' && (
                <div className="space-y-1.5 pt-2 border-t border-slate-100">
                  <label className="text-[11px] text-slate-500 block">{zh ? '输入 6 位工单验证码' : 'Enter 6-digit verification code'}</label>
                  <div className="flex items-center gap-2">
                    <input
                      value={deleteCode}
                      onChange={e => { setDeleteCode(e.target.value.replace(/\D/g, '').slice(0, 6)); setDeleteError(''); }}
                      placeholder="000000"
                      maxLength={6}
                      className="w-32 tracking-[0.3em] text-center font-mono rounded-xl border border-slate-200 py-2 text-sm outline-none focus:border-rose-500 transition-all"
                    />
                    <button
                      type="button"
                      onClick={verifyDeleteApproval}
                      disabled={deleteCode.length !== 6}
                      className={`px-4 py-2 rounded-xl font-bold transition-all ${deleteCode.length === 6 ? 'bg-emerald-600 text-white hover:bg-emerald-700' : 'bg-slate-100 text-slate-400 cursor-not-allowed'}`}
                    >
                      {zh ? '验证' : 'Verify'}
                    </button>
                  </div>
                </div>
              )}

              {deleteError && (
                <div className="flex items-center gap-1.5 text-rose-600 text-xs pt-1">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                  <span>{deleteError}</span>
                </div>
              )}
            </div>

            <div className="px-6 py-4 bg-slate-50/80 border-t border-slate-100 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 rounded-xl border border-slate-200 font-semibold text-slate-600 hover:bg-slate-100 transition-all"
              >
                {zh ? '取消' : 'Cancel'}
              </button>
              <button
                type="button"
                onClick={executeDeleteJob}
                disabled={deleteStatus !== 'verified'}
                className="px-4 py-2 rounded-xl bg-rose-600 text-white font-bold hover:bg-rose-700 disabled:opacity-40 disabled:cursor-not-allowed transition-all shadow-md shadow-rose-600/10"
              >
                {zh ? '确认安全删除' : 'Secure Delete'}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};
