import React from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Shield, X, RotateCcw, AlertTriangle } from 'lucide-react';
import { ScheduledJob, EligibleApprover, type ApprovalVerificationMethod } from '../types';
import { useEscapeClose } from '../../../hooks/useEscapeClose';
import CountdownText from './CountdownText';

interface DeleteApprovalModalProps {
  isOpen: boolean;
  onClose: () => void;
  deleteTarget: ScheduledJob | null;
  deleteReason: string;
  setDeleteReason: (val: string) => void;
  deleteApprover: string;
  setDeleteApprover: (val: string) => void;
  deleteApprovalMethod: ApprovalVerificationMethod;
  setDeleteApprovalMethod: (val: ApprovalVerificationMethod) => void;
  deleteStatus: 'idle' | 'sending' | 'sent' | 'verifying' | 'verified';
  deleteCountdown: number;
  deleteDeadline: number;
  onDeleteCountdownExpire: () => void;
  deleteCode: string;
  setDeleteCode: (val: string) => void;
  deleteError: string;
  setDeleteError: (val: string) => void;
  approvers: EligibleApprover[];
  approverLoadStatus: 'idle' | 'loading' | 'loaded' | 'error';
  refreshApprovers: () => void;
  requestDeleteApproval: () => void;
  verifyDeleteApproval: (code?: string) => void;
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
  deleteApprovalMethod,
  setDeleteApprovalMethod,
  deleteStatus,
  deleteCountdown,
  deleteDeadline,
  onDeleteCountdownExpire,
  deleteCode,
  setDeleteCode,
  deleteError,
  setDeleteError,
  approvers,
  approverLoadStatus,
  refreshApprovers,
  requestDeleteApproval,
  verifyDeleteApproval,
  executeDeleteJob,
  language,
}) => {
  useEscapeClose(isOpen && deleteStatus !== 'sending' && deleteStatus !== 'verifying', onClose);
  const zh = language === 'zh';
  const selectedApprover = approvers.find(item => item.username === deleteApprover);
  const availableApprovalMethods = selectedApprover?.verification_methods || [];
  const verificationMethodLabel = (method: ApprovalVerificationMethod) => {
    if (method === 'mfa') return zh ? 'MFA 动态码' : 'MFA code';
    if (method === 'email') return zh ? '邮箱验证码' : 'Email code';
    return zh ? '飞书验证码' : 'Feishu code';
  };

  return (
    <AnimatePresence>
      {isOpen && deleteTarget && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
        >
          <div className="fixed inset-0 bg-black/40" onClick={() => { if (deleteStatus !== 'sending' && deleteStatus !== 'verifying') onClose(); }} />
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            className="relative w-full max-w-sm rounded-2xl bg-white border border-slate-100 shadow-2xl overflow-hidden z-10"
            onClick={e => e.stopPropagation()}
          >
            <div className="bg-rose-50 border-b border-rose-100 px-4 py-3 flex items-center justify-between">
              <div className="flex items-center gap-2.5 text-rose-700">
                <Shield className="w-5 h-5 text-rose-600" />
                <h3 className="font-bold text-sm">{zh ? '删除安全校验与工单授权' : 'Delete Security Verification'}</h3>
              </div>
              <button onClick={onClose} disabled={deleteStatus === 'sending' || deleteStatus === 'verifying'} className="text-rose-400 hover:text-rose-600 p-1 disabled:opacity-40">
                <X size={16} />
              </button>
            </div>

            <div className="p-4 space-y-3 text-xs text-slate-600">
              <div className="bg-slate-50 px-3 py-2 rounded-xl border border-slate-100">
                <span className="text-[10px] text-slate-400 font-semibold">{zh ? '删除目标' : 'Delete target'}</span>
                <div className="mt-0.5 font-bold text-slate-800 truncate">{deleteTarget.name}</div>
                <div className="font-mono text-[10px] text-slate-500">{deleteTarget.cron_expr} · {deleteTarget.action_type}</div>
              </div>

              <div className="space-y-1.5">
                <label className="font-bold text-slate-700 block">{zh ? '删除原因说明' : 'Deletion Reason'}</label>
                <input
                  type="text"
                  value={deleteReason}
                  onChange={e => setDeleteReason(e.target.value)}
                  placeholder={zh ? '输入删除原因...' : 'Enter reason...'}
                  className="w-full px-3 py-1.5 rounded-xl border border-slate-200 bg-white outline-none focus:border-rose-500 transition-all"
                />
              </div>

              <div className="space-y-1.5">
                <label className="font-bold text-slate-700 block">{zh ? '选择授权审批人' : 'Select Approver'}</label>
                <select
                  value={deleteApprover}
                  onChange={e => setDeleteApprover(e.target.value)}
                  disabled={deleteStatus !== 'idle'}
                  className="w-full px-3 py-1.5 rounded-xl border border-slate-200 bg-white outline-none focus:border-rose-500 transition-all disabled:opacity-60"
                >
                  <option value="">{zh ? '选择审批人...' : 'Select approver...'}</option>
                  {approvers.map(u => (
                    <option key={u.id} value={u.username}>{u.username}</option>
                  ))}
                </select>
                {approverLoadStatus === 'loading' && <p className="text-[11px] text-slate-500">{zh ? '正在加载审批人…' : 'Loading approvers…'}</p>}
                {approverLoadStatus === 'error' && (
                  <div className="flex items-center justify-between gap-2 text-[11px] text-rose-700" role="alert">
                    <span>{zh ? '审批人加载失败，可能是登录或权限问题。' : 'Approver loading failed. Check your session or permissions.'}</span>
                    <button type="button" onClick={refreshApprovers} className="shrink-0 font-semibold underline">{zh ? '重试' : 'Retry'}</button>
                  </div>
                )}
                {approverLoadStatus === 'loaded' && approvers.length === 0 && <p className="text-[11px] text-amber-700">{zh ? '当前没有可用审批人。' : 'No eligible approvers are available.'}</p>}
              </div>

              {deleteApprover && availableApprovalMethods.length > 0 && (
                <div className="space-y-1.5">
                  <label className="font-bold text-slate-700 block">{zh ? '验证方式' : 'Verification method'}</label>
                  <select
                    value={deleteApprovalMethod}
                    onChange={e => setDeleteApprovalMethod(e.target.value as ApprovalVerificationMethod)}
                    disabled={deleteStatus !== 'idle'}
                    className="w-full px-3 py-1.5 rounded-xl border border-slate-200 bg-white outline-none focus:border-rose-500 transition-all disabled:opacity-60"
                  >
                    {availableApprovalMethods.map(method => (
                      <option key={method} value={method}>{verificationMethodLabel(method)}</option>
                    ))}
                  </select>
                </div>
              )}

              {deleteApprover && deleteStatus !== 'verified' && (
                <button
                  type="button"
                  onClick={requestDeleteApproval}
                  disabled={!deleteReason.trim() || deleteStatus === 'sending' || deleteStatus === 'verifying' || (deleteStatus === 'sent' && deleteCountdown > 0)}
                  className={`w-full px-3 py-2 rounded-xl font-bold whitespace-nowrap transition-all flex items-center justify-center gap-1 ${
                    deleteReason.trim() && deleteStatus !== 'sending' && deleteStatus !== 'verifying' && !(deleteStatus === 'sent' && deleteCountdown > 0)
                      ? 'bg-rose-600 text-white hover:bg-rose-700 shadow-sm'
                      : 'bg-slate-100 text-slate-400 cursor-not-allowed'
                  }`}
                >
                  {deleteStatus === 'sending' ? (
                    <RotateCcw className="w-3 h-3 animate-spin" />
                  ) : deleteStatus === 'verifying' ? (
                    <>{zh ? '正在验证…' : 'Verifying…'}</>
                  ) : deleteStatus === 'sent' && deleteCountdown > 0 ? (
                    <CountdownText deadline={deleteDeadline} onExpire={onDeleteCountdownExpire}>
                      {secondsRemaining => `${Math.floor(secondsRemaining / 60)}:${String(secondsRemaining % 60).padStart(2, '0')}`}
                    </CountdownText>
                  ) : (
                    deleteApprovalMethod === 'mfa'
                      ? (zh ? '开始 MFA 验证' : 'Start MFA verification')
                      : (zh ? '发送验证码' : 'Send Code')
                  )}
                </button>
              )}

              {(deleteStatus === 'sent' || deleteStatus === 'verifying') && (
                <div className="space-y-1.5 pt-2 border-t border-slate-100">
                  <label className="text-[11px] text-slate-500 block">{deleteApprovalMethod === 'mfa' ? (zh ? '输入审批人的 6 位 MFA 动态码' : 'Enter approver’s 6-digit MFA code') : (zh ? '输入 6 位工单验证码' : 'Enter 6-digit verification code')}</label>
                  <div className="flex items-center gap-2">
                    <input
                      value={deleteCode}
                      disabled={deleteStatus === 'verifying'}
                      onChange={e => {
                        const code = e.target.value.replace(/\D/g, '').slice(0, 6);
                        setDeleteCode(code);
                        setDeleteError('');
                        if (code.length === 6) verifyDeleteApproval(code);
                      }}
                      placeholder="000000"
                      maxLength={6}
                      className="w-32 tracking-[0.3em] text-center font-mono rounded-xl border border-slate-200 py-1.5 text-sm outline-none focus:border-rose-500 transition-all disabled:bg-slate-50"
                    />
                    {deleteStatus === 'verifying' && <span className="text-[11px] text-cyan-700">{zh ? '正在验证…' : 'Verifying…'}</span>}
                  </div>
                  <p className="text-[10px] text-slate-400">{zh ? '输入满 6 位后将自动验证。验证失败时修改验证码即可重试。' : 'Verification starts after 6 digits. Edit the code to retry if it fails.'}</p>
                </div>
              )}

              {deleteStatus === 'verified' && <p className="rounded-lg bg-emerald-50 px-3 py-2 text-[11px] font-semibold text-emerald-700">{zh ? '审批验证通过，请确认后删除。' : 'Approval verified. Confirm to delete the job.'}</p>}

              {deleteError && (
                <div role="alert" className="flex items-center gap-1.5 text-rose-600 text-xs pt-1">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                  <span>{deleteError}</span>
                </div>
              )}
            </div>

            <div className="px-6 py-4 bg-slate-50/80 border-t border-slate-100 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                disabled={deleteStatus === 'sending' || deleteStatus === 'verifying'}
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
