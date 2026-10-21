import React from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Shield, Terminal, X, User, Lock, Check, Loader2 } from 'lucide-react';
import { Asset } from '../types';
import { useEscapeClose } from '../../../hooks/useEscapeClose';
import { useFocusTrap } from '../../../hooks/useFocusTrap';

interface TerminalAccessModalProps {
  isOpen: boolean;
  onClose: () => void;
  terminalTarget: Asset | null;
  terminalAccessLevel: 'normal' | 'admin';
  setTerminalAccessLevel: (level: 'normal' | 'admin') => void;
  approvalData: { ticket: string; reason: string; mfa: string };
  setApprovalData: React.Dispatch<React.SetStateAction<{ ticket: string; reason: string; mfa: string }>>;
  terminalReason: string;
  setTerminalReason: (val: string) => void;
  terminalRequesting: boolean;
  systemInfo: any;
  requestTerminalAccess: () => void;
  setIsApproved: (val: boolean) => void;
  language: string;
}

export const TerminalAccessModal: React.FC<TerminalAccessModalProps> = ({
  isOpen,
  onClose,
  terminalTarget,
  terminalAccessLevel,
  setTerminalAccessLevel,
  approvalData,
  setApprovalData,
  terminalReason,
  setTerminalReason,
  terminalRequesting,
  systemInfo,
  requestTerminalAccess,
  setIsApproved,
  language,
}) => {
  useEscapeClose(isOpen, onClose);
  const dialogRef = React.useRef<HTMLDivElement>(null);
  const dialogTitleId = React.useId();
  const accessLevelLabelId = React.useId();
  const ticketInputId = React.useId();
  const reasonInputId = React.useId();
  const mfaInputId = React.useId();
  useFocusTrap(dialogRef, isOpen, 'input');
  const zh = language === 'zh';

  return (
    <AnimatePresence>
      {isOpen && terminalTarget && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/60 p-3 backdrop-blur-md"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={() => !terminalRequesting && onClose()}
        >
          <motion.div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={dialogTitleId}
            tabIndex={-1}
            className="max-h-[calc(100dvh-24px)] w-full max-w-[440px] overflow-y-auto rounded-3xl border border-white/10 bg-[#0d1117] shadow-2xl"
            onClick={(e) => e.stopPropagation()}
            initial={{ scale: 0.95, y: 20, opacity: 0 }}
            animate={{ scale: 1, y: 0, opacity: 1 }}
            exit={{ scale: 0.95, y: 20, opacity: 0 }}
          >
            <div className={`px-6 py-5 border-b border-white/[0.06] bg-gradient-to-r ${terminalAccessLevel === 'admin' ? 'from-orange-500/10' : 'from-cyan-500/10'} to-transparent`}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className={`p-2 rounded-xl ${terminalAccessLevel === 'admin' ? 'bg-orange-500/20 text-orange-400' : 'bg-cyan-500/20 text-cyan-400'}`}>
                    {terminalAccessLevel === 'admin' ? <Shield size={20} /> : <Terminal size={20} />}
                  </div>
                  <div>
                    <h3 id={dialogTitleId} className="text-sm font-bold text-white">{zh ? '终端访问申请' : 'Access Request'}</h3>
                    <p className="text-[10px] text-white/40 mt-0.5 uppercase tracking-widest">{terminalTarget.hostname || terminalTarget.management_ip}</p>
                  </div>
                </div>
                <button type="button" onClick={onClose} aria-label={zh ? '关闭' : 'Close'} className="min-h-10 min-w-10 rounded-lg text-white/60 transition-colors hover:bg-white/10 hover:text-white"><X size={18} /></button>
              </div>
            </div>

            <div className="p-6 space-y-5">
              <div>
                <span id={accessLevelLabelId} className="mb-2 block text-[10px] font-bold uppercase tracking-widest text-white/55">{zh ? '权限级别' : 'AUTHORIZATION'}</span>
                <div role="group" aria-labelledby={accessLevelLabelId} className="flex rounded-xl border border-white/5 bg-white/[0.03] p-1">
                  <button
                    type="button"
                    aria-pressed={terminalAccessLevel === 'normal'}
                    onClick={() => setTerminalAccessLevel('normal')}
                    className={`min-h-10 flex-1 flex items-center justify-center gap-2 rounded-lg py-2 text-xs font-bold transition-all ${terminalAccessLevel === 'normal' ? 'bg-white/10 text-white shadow-sm' : 'text-white/55 hover:text-white/80'}`}
                  >
                    <User size={12} />{zh ? '普通用户' : 'User'}
                  </button>
                  <button
                    type="button"
                    aria-pressed={terminalAccessLevel === 'admin'}
                    onClick={() => setTerminalAccessLevel('admin')}
                    className={`min-h-10 flex-1 flex items-center justify-center gap-2 rounded-lg py-2 text-xs font-bold transition-all ${terminalAccessLevel === 'admin' ? 'bg-orange-500/20 text-orange-100 shadow-sm' : 'text-white/55 hover:text-white/80'}`}
                  >
                    <Shield size={12} />{zh ? '特权账号' : 'Admin'}
                  </button>
                </div>
              </div>

              {terminalAccessLevel === 'admin' ? (
                <div className="space-y-4 animate-in fade-in slide-in-from-top-2 duration-300">
                  <div>
                    <label htmlFor={ticketInputId} className="mb-2 block text-[10px] font-bold uppercase tracking-widest text-white/60">{zh ? '关联变更单 (CR)' : 'CHANGE TICKET'}</label>
                    <input
                      id={ticketInputId}
                      type="text"
                      placeholder="CR-2026-XXXX"
                      value={approvalData.ticket}
                      onChange={e => setApprovalData({...approvalData, ticket: e.target.value})}
                      className="w-full bg-white/[0.03] border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white focus:border-orange-500 outline-none transition-all"
                    />
                  </div>
                  <div>
                    <label htmlFor={reasonInputId} className="mb-2 block text-[10px] font-bold uppercase tracking-widest text-white/60">{zh ? '申请理由' : 'JUSTIFICATION'}</label>
                    <textarea
                      id={reasonInputId}
                      rows={2}
                      value={terminalReason}
                      onChange={(e) => setTerminalReason(e.target.value)}
                      placeholder={zh ? '简述操作目的...' : 'Purpose of access...'}
                      className="w-full bg-white/[0.03] border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white focus:border-orange-500 outline-none transition-all resize-none"
                    />
                  </div>
                  <div>
                    <label htmlFor={mfaInputId} className="mb-2 block text-[10px] font-bold uppercase tracking-widest text-white/60">{zh ? '动态验证码 (MFA)' : 'MFA CODE'}</label>
                    <input
                      id={mfaInputId}
                      type="text"
                      maxLength={6}
                      placeholder="******"
                      value={approvalData.mfa}
                      onChange={e => setApprovalData({...approvalData, mfa: e.target.value})}
                      className="w-full bg-white/[0.03] border border-white/10 rounded-xl px-4 py-2.5 text-center text-xl font-mono tracking-[0.5em] text-orange-400 focus:border-orange-500 outline-none transition-all"
                    />
                  </div>
                </div>
              ) : (
                <div className="py-4 text-center">
                  <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-cyan-500/10 text-cyan-400 text-[11px] font-medium border border-cyan-500/20">
                    <Check size={12} /> {zh ? '直连模式：无需审批与 MFA' : 'Direct Access: No Approval Required'}
                  </div>
                </div>
              )}
            </div>

            <div className="px-6 py-5 bg-white/[0.02] border-t border-white/[0.06] flex items-center justify-between">
              <div className="text-[10px] text-white/20 flex items-center gap-1.5 font-medium italic">
                <Lock size={10} />
                {zh ? `受 ${systemInfo?.system_name || 'Nexora'} PAM 审计保护` : `Audited by ${systemInfo?.system_name || 'Nexora'} PAM`}
              </div>
              <div className="flex gap-2">
                <button type="button" onClick={onClose} className="min-h-10 rounded-lg px-4 py-2 text-xs font-bold text-white/70 transition-colors hover:bg-white/5 hover:text-white">{zh ? '取消' : 'Cancel'}</button>
                <button
                  type="button"
                  onClick={() => {
                    if (terminalAccessLevel === 'admin') {
                      setIsApproved(true);
                    }
                    requestTerminalAccess();
                  }}
                  disabled={terminalRequesting || (terminalAccessLevel === 'admin' && (!approvalData.ticket || !approvalData.mfa || !terminalReason.trim()))}
                  className={`px-6 py-2 rounded-xl text-xs font-bold shadow-lg transition-all ${terminalAccessLevel === 'admin' ? 'bg-gradient-to-r from-orange-500 to-red-500 text-white shadow-orange-500/20' : 'bg-[#00bceb] text-white shadow-cyan-500/20'} hover:scale-[1.02] active:scale-[0.98] disabled:opacity-30`}
                >
                  {terminalRequesting ? <Loader2 size={14} className="animate-spin" /> : (zh ? '提交并登录' : 'Submit & Login')}
                </button>
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};
