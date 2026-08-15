import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { X, User, KeyRound, ShieldCheck, ArrowRight, ArrowLeft, RotateCcw, CheckCircle2, Eye, EyeOff, Send } from 'lucide-react';

interface ForgotPasswordModalProps {
  open: boolean;
  onClose: () => void;
  t: (key: string) => string;
  initialUsername?: string;
}

type Step = 'username' | 'code' | 'newpwd' | 'done';
type RecoveryMethod = 'notification' | 'mfa';

const ForgotPasswordModal: React.FC<ForgotPasswordModalProps> = ({ open, onClose, t, initialUsername = '' }) => {
  const [step, setStep] = useState<Step>('username');
  const [username, setUsername] = useState(initialUsername);
  const [code, setCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPwd, setShowPwd] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [countdown, setCountdown] = useState(0);
  const [channels, setChannels] = useState<{ platform: string; success: boolean }[]>([]);
  const [recoveryMethod, setRecoveryMethod] = useState<RecoveryMethod>('notification');

  // Reset state when modal opens
  useEffect(() => {
    if (open) {
      setStep('username');
      setUsername(initialUsername);
      setCode('');
      setNewPassword('');
      setConfirmPassword('');
      setShowPwd(false);
      setError(null);
      setSending(false);
      setCountdown(0);
      setChannels([]);
      setRecoveryMethod('notification');
    }
  }, [open, initialUsername]);

  // Countdown timer for resend
  useEffect(() => {
    if (countdown <= 0) return;
    const id = setInterval(() => setCountdown((c) => c - 1), 1000);
    return () => clearInterval(id);
  }, [countdown]);

  const handleSendCode = useCallback(async () => {
    if (!username.trim()) {
      setError(t('fpUsernameRequired'));
      return;
    }
    setSending(true);
    setError(null);
    try {
      const resp = await fetch('/api/forgot-password/send-code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.trim() }),
      });
      const data = await resp.json();
      if (data.success) {
        setChannels(data.channels || []);
        setStep('code');
        setCountdown(60);
      } else {
        setError(data.detail || data.message || t('fpSendFailed'));
      }
    } catch {
      setError(t('fpNetworkError'));
    } finally {
      setSending(false);
    }
  }, [username, t]);

  const handleUseMfa = useCallback(() => {
    if (!username.trim()) {
      setError(t('fpUsernameRequired'));
      return;
    }
    setRecoveryMethod('mfa');
    setCode('');
    setError(null);
    setStep('code');
  }, [username, t]);

  const handleVerifyAndReset = useCallback(async () => {
    if (!code.trim() || code.trim().length !== 6) {
      setError(t('fpCodeInvalid'));
      return;
    }
    if (newPassword.length < 10) {
      setError(t('fpPasswordTooShort'));
      return;
    }
    if (newPassword !== confirmPassword) {
      setError(t('fpPasswordMismatch'));
      return;
    }
    setSending(true);
    setError(null);
    try {
      const resp = await fetch(recoveryMethod === 'mfa' ? '/api/forgot-password/mfa-reset' : '/api/forgot-password/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.trim(), code: code.trim(), new_password: newPassword }),
      });
      const data = await resp.json();
      if (data.success || resp.ok) {
        setStep('done');
      } else {
        setError(data.detail || data.message || t('fpResetFailed'));
      }
    } catch {
      setError(t('fpNetworkError'));
    } finally {
      setSending(false);
    }
  }, [username, code, newPassword, confirmPassword, recoveryMethod, t]);

  if (!open) return null;

  const stepIndicators: { key: Step; icon: React.ReactNode; label: string }[] = [
    { key: 'username', icon: <User size={14} />, label: t('fpStepUser') },
    { key: 'code', icon: <ShieldCheck size={14} />, label: t('fpStepVerify') },
    { key: 'newpwd', icon: <KeyRound size={14} />, label: t('fpStepReset') },
  ];
  const stepOrder: Step[] = ['username', 'code', 'newpwd'];
  const currentIdx = step === 'done' ? 3 : stepOrder.indexOf(step);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-[9999] flex items-center justify-center p-4"
        >
          {/* backdrop */}
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />

          <motion.div
            initial={{ scale: 0.92, opacity: 0, y: 20 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: 0.92, opacity: 0, y: 20 }}
            transition={{ type: 'spring', duration: 0.4 }}
            className="relative w-full max-w-[440px] rounded-[24px] border border-white/[0.08] bg-[#0a1628]/95 backdrop-blur-xl shadow-[0_32px_80px_rgba(0,0,0,0.5),inset_0_1px_0_rgba(255,255,255,0.06)]"
          >
            {/* top accent */}
            <div className="h-[2px] rounded-t-[24px] bg-gradient-to-r from-transparent via-[#06b6d4]/60 to-transparent" />

            {/* close */}
            <button
              onClick={onClose}
              className="absolute right-4 top-4 p-1.5 rounded-lg text-white/20 hover:text-white/50 hover:bg-white/[0.06] transition-colors"
              aria-label="Close"
            >
              <X size={16} />
            </button>

            <div className="px-8 pt-7 pb-7">
              {/* header */}
              <div className="mb-6">
                <h3 className="text-lg font-bold text-white/90 tracking-tight">{t('fpTitle')}</h3>
                <p className="text-[12px] text-white/30 mt-1">{t('fpSubtitle')}</p>
              </div>

              {/* step indicator */}
              {step !== 'done' && (
                <div className="flex items-center gap-1 mb-7">
                  {stepIndicators.map((s, i) => {
                    const isActive = i === currentIdx;
                    const isCompleted = i < currentIdx;
                    return (
                      <React.Fragment key={s.key}>
                        {i > 0 && (
                          <div className={`flex-1 h-px transition-colors duration-300 ${
                            isCompleted ? 'bg-[#06b6d4]/50' : 'bg-white/[0.06]'
                          }`} />
                        )}
                        <div className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-medium transition-all duration-300 ${
                          isActive
                            ? 'bg-[#06b6d4]/15 text-[#06b6d4] border border-[#06b6d4]/30'
                            : isCompleted
                              ? 'text-[#06b6d4]/60'
                              : 'text-white/15'
                        }`}>
                          {s.icon}
                          <span className="hidden sm:inline">{s.label}</span>
                        </div>
                      </React.Fragment>
                    );
                  })}
                </div>
              )}

              {/* error */}
              <AnimatePresence>
                {error && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    exit={{ opacity: 0, height: 0 }}
                    className="overflow-hidden mb-4"
                  >
                    <p className="text-xs font-medium text-red-400 bg-red-400/[0.08] border border-red-400/20 rounded-lg px-3 py-2">
                      {error}
                    </p>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* STEP 1: Username */}
              <AnimatePresence mode="wait">
                {step === 'username' && (
                  <motion.div
                    key="step-username"
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: -20 }}
                    transition={{ duration: 0.2 }}
                    className="space-y-4"
                  >
                    <div>
                      <label htmlFor="fp-username" className="block ml-0.5 mb-1.5 text-[10px] font-bold uppercase tracking-[0.2em] text-[#06b6d4]/60">
                        {t('username')}
                      </label>
                      <div className="relative group">
                        <div className="absolute left-4 top-1/2 -translate-y-1/2 text-white/20 group-focus-within:text-[#06b6d4]/70 transition-colors">
                          <User size={16} />
                        </div>
                        <input
                          id="fp-username"
                          type="text"
                          value={username}
                          onChange={(e) => { setUsername(e.target.value); setError(null); }}
                          onKeyDown={(e) => { if (e.key === 'Enter') handleSendCode(); }}
                          placeholder={t('fpUsernamePlaceholder')}
                          autoFocus
                          className="w-full rounded-xl border border-white/[0.08] py-3 pl-11 pr-4 text-sm text-white placeholder-white/15 outline-none transition-all bg-white/[0.04] focus:bg-white/[0.07] focus:border-[#06b6d4]/50 focus:shadow-[0_0_0_3px_rgba(6,182,212,0.12)]"
                        />
                      </div>
                      <p className="text-[11px] text-white/20 mt-2 leading-relaxed">{t('fpSendHint')}</p>
                    </div>
                    <button
                      onClick={handleSendCode}
                      disabled={sending || !username.trim()}
                      className="group flex w-full items-center justify-center gap-2 rounded-xl py-3 text-[13px] font-bold tracking-wide text-white bg-gradient-to-r from-[#0e7490] via-[#06b6d4] to-[#22d3ee] shadow-[0_4px_24px_rgba(6,182,212,0.3)] transition-all hover:shadow-[0_0_48px_rgba(6,182,212,0.3)] active:scale-[0.98] disabled:opacity-50"
                    >
                      {sending ? (
                        <><RotateCcw className="animate-spin" size={14} />{t('fpSending')}</>
                      ) : (
                        <><Send size={14} />{t('fpSendCode')}<ArrowRight size={14} className="group-hover:translate-x-0.5 transition-transform" /></>
                      )}
                    </button>
                    <div className="flex items-center gap-2 py-1 text-[10px] text-white/15">
                      <span className="h-px flex-1 bg-white/[0.06]" />
                      <span>{t('fpOr')}</span>
                      <span className="h-px flex-1 bg-white/[0.06]" />
                    </div>
                    <button
                      type="button"
                      onClick={handleUseMfa}
                      disabled={!username.trim()}
                      className="flex w-full items-center justify-center gap-2 rounded-xl border border-[#06b6d4]/20 py-2.5 text-[12px] font-semibold text-[#06b6d4]/70 transition-colors hover:bg-[#06b6d4]/[0.08] disabled:opacity-40"
                    >
                      <ShieldCheck size={14} />{t('fpUseMfa')}
                    </button>
                  </motion.div>
                )}

                {/* STEP 2: Enter code */}
                {step === 'code' && (
                  <motion.div
                    key="step-code"
                    initial={{ opacity: 0, x: 20 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: 20 }}
                    transition={{ duration: 0.2 }}
                    className="space-y-4"
                  >
                    {/* channel badges */}
                    {recoveryMethod === 'notification' && channels.length > 0 && (
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-[10px] text-white/25 uppercase tracking-wider">{t('fpSentTo')}:</span>
                        {channels.filter(c => c.success).map((ch) => (
                          <span key={ch.platform} className="inline-flex items-center gap-1 text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded-md px-2 py-0.5">
                            <CheckCircle2 size={10} />
                            {ch.platform === 'feishu' ? '飞书' : ch.platform === 'dingtalk' ? '钉钉' : '企业微信'}
                          </span>
                        ))}
                      </div>
                    )}
                    {recoveryMethod === 'mfa' && (
                      <p className="rounded-lg border border-[#06b6d4]/15 bg-[#06b6d4]/[0.06] px-3 py-2 text-[11px] leading-relaxed text-white/45">
                        {t('fpMfaHint')}
                      </p>
                    )}
                    <div>
                      <label htmlFor="fp-code" className="block ml-0.5 mb-1.5 text-[10px] font-bold uppercase tracking-[0.2em] text-[#06b6d4]/60">
                        {recoveryMethod === 'mfa' ? t('fpMfaCodeLabel') : t('fpCodeLabel')}
                      </label>
                      <input
                        id="fp-code"
                        type="text"
                        inputMode="numeric"
                        maxLength={6}
                        value={code}
                        onChange={(e) => { setCode(e.target.value.replace(/\D/g, '').slice(0, 6)); setError(null); }}
                        onKeyDown={(e) => { if (e.key === 'Enter' && code.length === 6) setStep('newpwd'); }}
                        placeholder="000000"
                        autoFocus
                        className="w-full rounded-xl border border-white/[0.08] py-3 px-4 text-center text-2xl font-mono tracking-[0.5em] text-white placeholder-white/10 outline-none transition-all bg-white/[0.04] focus:bg-white/[0.07] focus:border-[#06b6d4]/50 focus:shadow-[0_0_0_3px_rgba(6,182,212,0.12)]"
                      />
                    </div>
                    {/* resend */}
                    {recoveryMethod === 'notification' ? <div className="flex items-center justify-between">
                      <button
                        onClick={() => { setStep('username'); setError(null); }}
                        className="text-[11px] text-white/25 hover:text-white/50 flex items-center gap-1 transition-colors"
                      >
                        <ArrowLeft size={12} />{t('fpBack')}
                      </button>
                      <button
                        onClick={handleSendCode}
                        disabled={countdown > 0 || sending}
                        className="text-[11px] text-[#06b6d4]/60 hover:text-[#06b6d4] disabled:text-white/15 transition-colors"
                      >
                        {countdown > 0 ? `${t('fpResend')} (${countdown}s)` : t('fpResend')}
                      </button>
                    </div> : <div className="flex items-center justify-start">
                      <button onClick={() => { setStep('username'); setRecoveryMethod('notification'); setError(null); }} className="text-[11px] text-white/25 hover:text-white/50 flex items-center gap-1 transition-colors"><ArrowLeft size={12} />{t('fpBack')}</button>
                    </div>}
                    <button
                      onClick={() => {
                        if (code.trim().length !== 6) {
                          setError(t('fpCodeInvalid'));
                          return;
                        }
                        setError(null);
                        setStep('newpwd');
                      }}
                      disabled={code.length !== 6}
                      className="group flex w-full items-center justify-center gap-2 rounded-xl py-3 text-[13px] font-bold tracking-wide text-white bg-gradient-to-r from-[#0e7490] via-[#06b6d4] to-[#22d3ee] shadow-[0_4px_24px_rgba(6,182,212,0.3)] transition-all hover:shadow-[0_0_48px_rgba(6,182,212,0.3)] active:scale-[0.98] disabled:opacity-50"
                    >
                      {t('fpNext')}<ArrowRight size={14} className="group-hover:translate-x-0.5 transition-transform" />
                    </button>
                  </motion.div>
                )}

                {/* STEP 3: New password */}
                {step === 'newpwd' && (
                  <motion.div
                    key="step-newpwd"
                    initial={{ opacity: 0, x: 20 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: 20 }}
                    transition={{ duration: 0.2 }}
                    className="space-y-4"
                  >
                    <div>
                      <label htmlFor="fp-newpwd" className="block ml-0.5 mb-1.5 text-[10px] font-bold uppercase tracking-[0.2em] text-[#06b6d4]/60">
                        {t('fpNewPassword')}
                      </label>
                      <div className="relative group">
                        <div className="absolute left-4 top-1/2 -translate-y-1/2 text-white/20 group-focus-within:text-[#06b6d4]/70 transition-colors">
                          <KeyRound size={16} />
                        </div>
                        <input
                          id="fp-newpwd"
                          type={showPwd ? 'text' : 'password'}
                          value={newPassword}
                          onChange={(e) => { setNewPassword(e.target.value); setError(null); }}
                          placeholder={t('fpNewPasswordPlaceholder')}
                          autoFocus
                          autoComplete="new-password"
                          className="w-full rounded-xl border border-white/[0.08] py-3 pl-11 pr-12 text-sm text-white placeholder-white/15 outline-none transition-all bg-white/[0.04] focus:bg-white/[0.07] focus:border-[#06b6d4]/50 focus:shadow-[0_0_0_3px_rgba(6,182,212,0.12)]"
                        />
                        <button
                          tabIndex={-1}
                          type="button"
                          onClick={() => setShowPwd(!showPwd)}
                          aria-label={showPwd ? 'Hide password' : 'Show password'}
                          className="absolute right-4 top-1/2 -translate-y-1/2 text-white/20 hover:text-white/50 transition-colors"
                        >
                          {showPwd ? <EyeOff size={15} /> : <Eye size={15} />}
                        </button>
                      </div>
                    </div>
                    <div>
                      <label htmlFor="fp-confirm" className="block ml-0.5 mb-1.5 text-[10px] font-bold uppercase tracking-[0.2em] text-[#06b6d4]/60">
                        {t('fpConfirmPassword')}
                      </label>
                      <div className="relative group">
                        <div className="absolute left-4 top-1/2 -translate-y-1/2 text-white/20 group-focus-within:text-[#06b6d4]/70 transition-colors">
                          <KeyRound size={16} />
                        </div>
                        <input
                          id="fp-confirm"
                          type={showPwd ? 'text' : 'password'}
                          value={confirmPassword}
                          onChange={(e) => { setConfirmPassword(e.target.value); setError(null); }}
                          onKeyDown={(e) => { if (e.key === 'Enter') handleVerifyAndReset(); }}
                          placeholder={t('fpConfirmPlaceholder')}
                          autoComplete="new-password"
                          className="w-full rounded-xl border border-white/[0.08] py-3 pl-11 pr-4 text-sm text-white placeholder-white/15 outline-none transition-all bg-white/[0.04] focus:bg-white/[0.07] focus:border-[#06b6d4]/50 focus:shadow-[0_0_0_3px_rgba(6,182,212,0.12)]"
                        />
                      </div>
                    </div>
                    <p className="text-[10px] text-white/20 leading-relaxed">{t('fpPasswordHint')}</p>
                    <div className="flex gap-3">
                      <button
                        onClick={() => { setStep('code'); setError(null); }}
                        className="flex items-center justify-center gap-1.5 rounded-xl py-3 px-4 text-[13px] font-medium text-white/40 border border-white/[0.08] hover:bg-white/[0.04] transition-colors"
                      >
                        <ArrowLeft size={14} />{t('fpBack')}
                      </button>
                      <button
                        onClick={handleVerifyAndReset}
                        disabled={sending || !newPassword || !confirmPassword}
                        className="group flex-1 flex items-center justify-center gap-2 rounded-xl py-3 text-[13px] font-bold tracking-wide text-white bg-gradient-to-r from-[#0e7490] via-[#06b6d4] to-[#22d3ee] shadow-[0_4px_24px_rgba(6,182,212,0.3)] transition-all hover:shadow-[0_0_48px_rgba(6,182,212,0.3)] active:scale-[0.98] disabled:opacity-50"
                      >
                        {sending ? (
                          <><RotateCcw className="animate-spin" size={14} />{t('fpResetting')}</>
                        ) : (
                          <><ShieldCheck size={14} />{t('fpResetPassword')}</>
                        )}
                      </button>
                    </div>
                  </motion.div>
                )}

                {/* DONE */}
                {step === 'done' && (
                  <motion.div
                    key="step-done"
                    initial={{ opacity: 0, scale: 0.9 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ type: 'spring', duration: 0.4 }}
                    className="flex flex-col items-center text-center py-4 space-y-4"
                  >
                    <div className="h-16 w-16 rounded-full bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
                      <CheckCircle2 size={32} className="text-emerald-400" />
                    </div>
                    <h4 className="text-base font-bold text-white/90">{t('fpDoneTitle')}</h4>
                    <p className="text-[13px] text-white/40 max-w-[280px]">{t('fpDoneMessage')}</p>
                    <button
                      onClick={onClose}
                      className="mt-2 flex items-center justify-center gap-2 rounded-xl py-3 px-8 text-[13px] font-bold text-white bg-gradient-to-r from-[#0e7490] via-[#06b6d4] to-[#22d3ee] shadow-[0_4px_24px_rgba(6,182,212,0.3)] transition-all hover:shadow-[0_0_48px_rgba(6,182,212,0.3)] active:scale-[0.98]"
                    >
                      {t('fpBackToLogin')}
                    </button>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            {/* bottom accent */}
            <div className="h-px rounded-b-[24px] bg-gradient-to-r from-transparent via-[#0e7490]/30 to-transparent" />
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};

export default ForgotPasswordModal;
