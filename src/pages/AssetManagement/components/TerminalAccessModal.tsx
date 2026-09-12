import React from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Shield, Terminal, X, User, Lock, Check, Loader2 } from 'lucide-react';
import { Asset } from '../types';

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
  const zh = language === 'zh';

  return (
    <AnimatePresence>
      {isOpen && terminalTarget && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-md"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={() => !terminalRequesting && onClose()}
        >
          <motion.div
            className="bg-[#0d1117] rounded-3xl w-[440px] border border-white/10 shadow-2xl overflow-hidden"
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
                    <h3 className="text-sm font-bold text-white">{zh ? '终端访问申请' : 'Access Request'}</h3>
                    <p className="text-[10px] text-white/40 mt-0.5 uppercase tracking-widest">{terminalTarget.hostname || terminalTarget.management_ip}</p>
                  </div>
                </div>
                <button onClick={onClose} className="text-white/20 hover:text-white/60 transition-colors"><X size={18} /></button>
              </div>
            </div>

            <div className="p-6 space-y-5">
              <div>
                <label className="block text-[10px] font-bold text-white/30 uppercase tracking-widest mb-2">{zh ? '权限级别' : 'AUTHORIZATION'}</label>
                <div className="flex bg-white/[0.03] rounded-xl p-1 border border-white/5">
                  <button
                    onClick={() => setTerminalAccessLevel('normal')}
                    className={`flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-xs font-bold transition-all ${terminalAccessLevel === 'normal' ? 'bg-white/10 text-white shadow-sm' : 'text-white/30 hover:text-white/50'}`}
                  >
                    <User size={12} />{zh ? '普通用户' : 'User'}
                  </button>
                  <button
                    onClick={() => setTerminalAccessLevel('admin')}
                    className={`flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-xs font-bold transition-all ${terminalAccessLevel === 'admin' ? 'bg-orange-50 text-white shadow-sm' : 'text-white/30 hover:text-white/50'}`}
                  >
                    <Shield size={12} />{zh ? '特权账号' : 'Admin'}
                  </button>
                </div>
              </div>

              {terminalAccessLevel === 'admin' ? (
                <div className="space-y-4 animate-in fade-in slide-in-from-top-2 duration-300">
                  <div>
                    <label className="block text-[10px] font-bold text-white/30 uppercase tracking-widest mb-2">{zh ? '关联变更单 (CR)' : 'CHANGE TICKET'}</label>
                    <input
                      type="text"
                      placeholder="CR-2026-XXXX"
                      value={approvalData.ticket}
                      onChange={e => setApprovalData({...approvalData, ticket: e.target.value})}
                      className="w-full bg-white/[0.03] border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white focus:border-orange-500 outline-none transition-all"
                    />
                  </div>
                  <div>
                    <label className="block text-[10px] font-bold text-white/30 uppercase tracking-widest mb-2">{zh ? '申请理由' : 'JUSTIFICATION'}</label>
                    <textarea
                      rows={2}
                      value={terminalReason}
                      onChange={(e) => setTerminalReason(e.target.value)}
                      placeholder={zh ? '简述操作目的...' : 'Purpose of access...'}
                      className="w-full bg-white/[0.03] border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white focus:border-orange-500 outline-none transition-all resize-none"
                    />
                  </div>
                  <div>
                    <label className="block text-[10px] font-bold text-white/30 uppercase tracking-widest mb-2">{zh ? '动态验证码 (MFA)' : 'MFA CODE'}</label>
                    <input
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
                <button onClick={onClose} className="px-4 py-2 text-xs font-bold text-white/40 hover:text-white/60 transition-colors">{zh ? '取消' : 'Cancel'}</button>
                <button
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
