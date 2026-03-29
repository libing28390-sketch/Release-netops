import React from 'react';
import { Activity, Eye, EyeOff, Lock, Play, RotateCcw, User, XCircle } from 'lucide-react';
import { motion } from 'motion/react';

interface LoginScreenProps {
  isDark: boolean;
  t: (key: string) => string;
  loginForm: {
    username: string;
    password: string;
  };
  loginError: string | null;
  showLoginPwd: boolean;
  rememberMe: boolean;
  isAuthenticating: boolean;
  onUsernameChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  onTogglePassword: () => void;
  onRememberMeChange: (value: boolean) => void;
  onSubmit: () => void;
}

const LoginScreen: React.FC<LoginScreenProps> = ({
  isDark,
  t,
  loginForm,
  loginError,
  showLoginPwd,
  rememberMe,
  isAuthenticating,
  onUsernameChange,
  onPasswordChange,
  onTogglePassword,
  onRememberMeChange,
  onSubmit,
}) => {
  return (
    <div className={`min-h-screen flex items-center justify-center p-4 font-sans relative overflow-hidden ${isDark ? 'bg-[#050D1B]' : 'bg-[#EAF3FA]'}`}>
      <div className="absolute top-[-15%] right-[-8%] h-[55vw] w-[55vw] rounded-full bg-[radial-gradient(circle,rgba(0,188,235,0.13)_0%,transparent_65%)] pointer-events-none" />
      <div className="absolute bottom-[-20%] left-[-12%] h-[50vw] w-[50vw] rounded-full bg-[radial-gradient(circle,rgba(0,80,115,0.22)_0%,transparent_65%)] pointer-events-none" />
      <div className="absolute top-[40%] left-[20%] h-[30vw] w-[30vw] rounded-full bg-[radial-gradient(circle,rgba(0,40,90,0.18)_0%,transparent_70%)] pointer-events-none" />

      <div className="absolute inset-0 bg-[radial-gradient(rgba(0,188,235,0.9)_1px,transparent_1px)] bg-[length:36px_36px] opacity-[0.08] pointer-events-none" />

      <svg className="absolute inset-0 w-full h-full opacity-[0.13] pointer-events-none" xmlns="http://www.w3.org/2000/svg">
        <style>{`
          @keyframes nodePulse { 0%,100%{r:4;opacity:0.6} 50%{r:6;opacity:1} }
          @keyframes ringPulse { 0%,100%{r:10;opacity:0.3} 50%{r:16;opacity:0.1} }
          @keyframes dashFlow { 0%{stroke-dashoffset:0} 100%{stroke-dashoffset:-20} }
          .node-pulse { animation: nodePulse 3s ease-in-out infinite; }
          .ring-pulse { animation: ringPulse 4s ease-in-out infinite; }
          .line-flow { stroke-dasharray: 8 12; animation: dashFlow 2s linear infinite; }
          .delay-0 { animation-delay: 0s; }
          .delay-05 { animation-delay: 0.5s; }
          .delay-08 { animation-delay: 0.8s; }
          .delay-1 { animation-delay: 1s; }
          .delay-12 { animation-delay: 1.2s; }
          .delay-15 { animation-delay: 1.5s; }
          .delay-18 { animation-delay: 1.8s; }
          .delay-2 { animation-delay: 2s; }
          .delay-25 { animation-delay: 2.5s; }
        `}</style>
        <line x1="10%" y1="20%" x2="35%" y2="45%" stroke="#00bceb" strokeWidth="0.8" className="line-flow" />
        <line x1="35%" y1="45%" x2="65%" y2="30%" stroke="#00bceb" strokeWidth="0.8" className="line-flow" />
        <line x1="65%" y1="30%" x2="88%" y2="55%" stroke="#00bceb" strokeWidth="0.8" className="line-flow" />
        <line x1="35%" y1="45%" x2="50%" y2="70%" stroke="#00bceb" strokeWidth="0.8" className="line-flow" />
        <line x1="50%" y1="70%" x2="75%" y2="80%" stroke="#00bceb" strokeWidth="0.8" className="line-flow" />
        <line x1="65%" y1="30%" x2="50%" y2="70%" stroke="#005073" strokeWidth="0.6" className="line-flow" />
        <line x1="10%" y1="20%" x2="50%" y2="70%" stroke="#005073" strokeWidth="0.4" className="line-flow" />
        <line x1="20%" y1="85%" x2="35%" y2="45%" stroke="#005073" strokeWidth="0.4" className="line-flow" />
        <line x1="88%" y1="15%" x2="65%" y2="30%" stroke="#00bceb" strokeWidth="0.5" className="line-flow" />
        <line x1="75%" y1="80%" x2="92%" y2="68%" stroke="#005073" strokeWidth="0.4" className="line-flow" />
        <circle cx="10%" cy="20%" r="4" fill="#00bceb" className="node-pulse delay-0" />
        <circle cx="35%" cy="45%" r="5" fill="#00bceb" className="node-pulse delay-05" />
        <circle cx="65%" cy="30%" r="4" fill="#00bceb" className="node-pulse delay-1" />
        <circle cx="88%" cy="55%" r="3" fill="#005073" className="node-pulse delay-15" />
        <circle cx="50%" cy="70%" r="4" fill="#005073" className="node-pulse delay-2" />
        <circle cx="75%" cy="80%" r="3" fill="#00bceb" className="node-pulse delay-08" />
        <circle cx="20%" cy="85%" r="3" fill="#005073" className="node-pulse delay-12" />
        <circle cx="88%" cy="15%" r="3" fill="#00bceb" className="node-pulse delay-25" />
        <circle cx="92%" cy="68%" r="2.5" fill="#005073" className="node-pulse delay-18" />
        <circle cx="10%" cy="20%" r="10" fill="none" stroke="#00bceb" strokeWidth="0.5" className="ring-pulse delay-0" />
        <circle cx="35%" cy="45%" r="12" fill="none" stroke="#00bceb" strokeWidth="0.5" className="ring-pulse delay-1" />
        <circle cx="65%" cy="30%" r="9" fill="none" stroke="#00bceb" strokeWidth="0.5" className="ring-pulse delay-2" />
        <circle cx="50%" cy="70%" r="11" fill="none" stroke="#005073" strokeWidth="0.5" className="ring-pulse delay-15" />
      </svg>

      <motion.div
        initial={{ y: 28, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.5, ease: 'easeOut' }}
        className="relative z-10 w-full max-w-[420px]"
      >
        <div className="text-center mb-8">
          <div className="mb-5 inline-flex h-[72px] w-[72px] items-center justify-center rounded-2xl bg-[linear-gradient(135deg,#003d57_0%,#00bceb_100%)] shadow-[0_0_48px_rgba(0,188,235,0.35),0_0_0_1px_rgba(0,188,235,0.2)]">
            <Activity size={36} className="text-white" />
          </div>
          <h1 className={`text-[28px] font-black tracking-tight leading-none ${isDark ? 'text-white' : 'text-[#0B2A3C]'}`}>NetPilot</h1>
          <p className="text-[#00bceb] text-[10px] font-bold uppercase tracking-[0.28em] mt-2 opacity-80">Network Operations Command Center</p>
        </div>

        <div className={`overflow-hidden rounded-3xl backdrop-blur-2xl ${isDark
          ? 'border border-[rgba(0,188,235,0.18)] bg-white/[0.035] shadow-[0_0_80px_rgba(0,188,235,0.07),0_24px_48px_rgba(0,0,0,0.5)]'
          : 'border border-[rgba(0,80,115,0.18)] bg-white/[0.82] shadow-[0_26px_48px_rgba(0,45,85,0.22),0_0_0_1px_rgba(255,255,255,0.45)]'
        }`}>
          <div className="h-px bg-[linear-gradient(90deg,transparent_0%,rgba(0,188,235,0.7)_50%,transparent_100%)]" />

          <div className="p-10">
            <div className="text-center mb-8">
              <h2 className={`text-lg font-bold ${isDark ? 'text-white' : 'text-[#12364A]'}`}>{t('welcomeBack')}</h2>
              <p className={`text-xs mt-1.5 ${isDark ? 'text-white/45' : 'text-[#2B5A75]/70'}`}>{t('loginSubtitle')}</p>
            </div>

            <motion.div
              animate={loginError ? { x: [-8, 8, -8, 8, 0] } : {}}
              transition={{ duration: 0.35 }}
              className="space-y-5"
              onKeyDown={(event) => { if (event.key === 'Enter') onSubmit(); }}
            >
              <div className="space-y-2">
                <label className={`ml-0.5 text-[10px] font-bold uppercase tracking-[0.18em] ${isDark ? 'text-[#00bceb]/72' : 'text-[rgba(0,114,152,0.88)]'}`}>{t('username')}</label>
                <div className="relative">
                  <div className={`absolute left-4 top-1/2 -translate-y-1/2 ${isDark ? 'text-white/20' : 'text-[#0A4E70]/45'}`}>
                    <User size={16} />
                  </div>
                  <input
                    type="text"
                    placeholder="admin"
                    autoFocus
                    value={loginForm.username}
                    onChange={(event) => onUsernameChange(event.target.value)}
                    className={`w-full rounded-xl border-[1.5px] py-3.5 pl-11 pr-4 text-sm outline-none transition-all focus:shadow-[0_0_0_3px_rgba(0,188,235,0.12)] ${isDark ? 'text-white placeholder-white/20' : 'text-[#0B2A3C] placeholder-[#49728A]/45'} ${loginError ? 'border-red-500/70' : isDark ? 'border-white/8 bg-white/5 focus:border-[#00bceb]/60 focus:bg-[#00bceb]/6' : 'border-[rgba(0,80,115,0.22)] bg-white/[0.74] focus:border-[rgba(0,166,212,0.88)] focus:bg-white/[0.92]'}`}
                  />
                </div>
              </div>

              <div className="space-y-2">
                <label className={`ml-0.5 text-[10px] font-bold uppercase tracking-[0.18em] ${isDark ? 'text-[#00bceb]/72' : 'text-[rgba(0,114,152,0.88)]'}`}>{t('password')}</label>
                <div className="relative">
                  <div className={`absolute left-4 top-1/2 -translate-y-1/2 ${isDark ? 'text-white/20' : 'text-[#0A4E70]/45'}`}>
                    <Lock size={16} />
                  </div>
                  <input
                    type={showLoginPwd ? 'text' : 'password'}
                    placeholder="••••••••"
                    value={loginForm.password}
                    onChange={(event) => onPasswordChange(event.target.value)}
                    className={`w-full rounded-xl border-[1.5px] py-3.5 pl-11 pr-12 text-sm outline-none transition-all focus:shadow-[0_0_0_3px_rgba(0,188,235,0.12)] ${isDark ? 'text-white placeholder-white/20' : 'text-[#0B2A3C] placeholder-[#49728A]/45'} ${loginError ? 'border-red-500/70' : isDark ? 'border-white/8 bg-white/5 focus:border-[#00bceb]/60 focus:bg-[#00bceb]/6' : 'border-[rgba(0,80,115,0.22)] bg-white/[0.74] focus:border-[rgba(0,166,212,0.88)] focus:bg-white/[0.92]'}`}
                  />
                  <button type="button" onClick={onTogglePassword} className={`absolute right-4 top-1/2 -translate-y-1/2 transition-colors ${isDark ? 'text-white/25 hover:text-white/60' : 'text-[#0A4E70]/45 hover:text-[#0A4E70]'}`}>
                    {showLoginPwd ? <EyeOff size={15} /> : <Eye size={15} />}
                  </button>
                </div>
              </div>

              {loginError && (
                <motion.p initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} className="text-xs font-medium text-red-400 flex items-center gap-1.5">
                  <XCircle size={13} />{loginError}
                </motion.p>
              )}

              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={rememberMe}
                  onChange={(event) => onRememberMeChange(event.target.checked)}
                  className="w-3.5 h-3.5 rounded border-black/20 accent-[#00bceb]"
                />
                <span className={`text-xs ${isDark ? 'text-white/40' : 'text-[#2B5A75]/60'}`}>{t('rememberMe')}</span>
              </label>

              <div className="pt-2">
                <button
                  onClick={onSubmit}
                  disabled={isAuthenticating}
                  className={`flex w-full items-center justify-center gap-2 rounded-xl py-3.5 text-xs font-bold uppercase tracking-[0.18em] text-white transition-all disabled:opacity-50 hover:scale-[1.02] hover:shadow-[0_0_40px_rgba(0,188,235,0.4),0_6px_20px_rgba(0,0,0,0.5)] active:scale-[0.98] ${loginError ? 'bg-red-500/80 shadow-[0_0_24px_rgba(239,68,68,0.3)]' : 'bg-[linear-gradient(135deg,#00527a_0%,#00bceb_100%)] shadow-[0_0_32px_rgba(0,188,235,0.25),0_4px_16px_rgba(0,0,0,0.4)]'}`}
                >
                  {isAuthenticating ? (
                    <><RotateCcw className="animate-spin" size={15} />{t('authenticating')}</>
                  ) : (
                    <>{t('login')}<Play size={13} /></>
                  )}
                </button>
              </div>
            </motion.div>

            <div className={`mt-8 pt-5 ${isDark ? 'border-t border-white/6' : 'border-t border-[rgba(0,80,115,0.10)]'}`}>
              <div className="flex items-center justify-center gap-2.5 flex-wrap">
                <div className="flex items-center gap-1.5">
                  <div className="h-1.5 w-1.5 rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.8)]" />
                  <span className={`text-[10px] font-semibold uppercase tracking-wider ${isDark ? 'text-white/25' : 'text-[rgba(9,47,69,0.46)]'}`}>{t('systemOnline')}</span>
                </div>
                <span className={`text-[10px] ${isDark ? 'text-white/10' : 'text-[rgba(9,47,69,0.22)]'}`}>·</span>
                <span className={`text-[10px] font-mono ${isDark ? 'text-white/15' : 'text-[rgba(9,47,69,0.36)]'}`}>NOC v2.0</span>
                <span className={`text-[10px] ${isDark ? 'text-white/10' : 'text-[rgba(9,47,69,0.22)]'}`}>·</span>
                <span className={`text-[10px] ${isDark ? 'text-white/15' : 'text-[rgba(9,47,69,0.36)]'}`}>© {new Date().getFullYear()} NetPilot</span>
              </div>
            </div>
          </div>

          <div className="h-px bg-[linear-gradient(90deg,transparent_0%,rgba(0,80,115,0.5)_50%,transparent_100%)]" />
        </div>
      </motion.div>
    </div>
  );
};

export default LoginScreen;