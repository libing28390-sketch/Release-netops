import React, { useEffect, useState } from 'react';
import { Activity, Eye, EyeOff, Lock, RotateCcw, ArrowRight, User, XCircle, Shield, Cpu, Wifi, HelpCircle } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import './LoginScreen.css';
import ForgotPasswordModal from './ForgotPasswordModal';

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
  mfaRequired?: boolean;
  onMfaSubmit?: (code: string) => void;
  onCancelMfa?: () => void;
  onUsernameChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  onTogglePassword: () => void;
  onRememberMeChange: (value: boolean) => void;
  onSubmit: () => void;
}

/* ── live clock ── */
function useClock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return now;
}

const LoginScreen: React.FC<LoginScreenProps> = ({
  isDark,
  t,
  loginForm,
  loginError,
  showLoginPwd,
  rememberMe,
  isAuthenticating,
  mfaRequired = false,
  onMfaSubmit,
  onCancelMfa,
  onUsernameChange,
  onPasswordChange,
  onTogglePassword,
  onRememberMeChange,
  onSubmit,
}) => {
  const clock = useClock();
  const [mfaCode, setMfaCode] = useState('');
  const timeStr = clock.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const dateStr = clock.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', weekday: 'short' });

  /* live platform stats from /api/health */
  const [platformStats, setPlatformStats] = useState<{ devices: string; status: string; online: string }>({
    devices: '—', status: '—', online: '—',
  });
  const [sysName, setSysName] = useState('Nexora');
  const [sysVersion, setSysVersion] = useState('v2.0');
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch('/api/system/info');
        if (resp.ok) {
          const d = await resp.json();
          if (cancelled) return;
          if (d.system_name) setSysName(d.system_name);
          if (d.version) setSysVersion('v' + d.version);
        }
      } catch { /* ignore */ }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch('/api/health');
        if (!resp.ok) return;
        const d = await resp.json();
        if (cancelled) return;
        const total = d.device_total ?? 0;
        const online = d.device_online ?? 0;
        const status = d.status === 'healthy' ? 'Healthy' : d.status === 'degraded' ? 'Degraded' : d.status || '—';
        setPlatformStats({
          devices: String(total),
          status,
          online: total > 0 ? `${online}/${total}` : '—',
        });
      } catch { /* ignore */ }
    })();
    return () => { cancelled = true; };
  }, []);

  const [showForgotPwd, setShowForgotPwd] = useState(false);

  const stats = [
    { icon: Cpu, label: t('loginStatDevices'), value: platformStats.devices },
    { icon: Shield, label: t('loginStatStatus'), value: platformStats.status },
    { icon: Wifi, label: t('loginStatOnline'), value: platformStats.online },
  ];

  return (
    <div className="min-h-screen flex font-sans relative overflow-hidden select-none bg-[#060e1a]">


      {/* ── background layers ── */}
      <div className="absolute inset-0 pointer-events-none">
        {/* aurora blobs */}
        <div className="login-aurora-blob absolute top-[-25%] right-[-10%] w-[70vw] h-[70vh] rounded-full bg-[radial-gradient(circle,rgba(6,182,212,0.15)_0%,rgba(6,182,212,0.04)_40%,transparent_70%)]" />
        <div className="login-aurora-blob-2 absolute bottom-[-20%] left-[-15%] w-[60vw] h-[60vh] rounded-full bg-[radial-gradient(circle,rgba(14,116,144,0.18)_0%,rgba(8,145,178,0.05)_40%,transparent_70%)]" />
        <div className="login-aurora-blob-3 absolute top-[30%] left-[40%] w-[40vw] h-[40vh] rounded-full bg-[radial-gradient(circle,rgba(6,182,212,0.08)_0%,transparent_60%)]" />
        {/* dot grid — scrolling */}
        <div className="absolute inset-0 login-grid-flow bg-[radial-gradient(rgba(6,182,212,0.45)_1px,transparent_1px)] bg-[length:40px_40px] opacity-[0.06]" />
        {/* scan line */}
        <div className="login-scan-line absolute left-0 w-full h-[2px] bg-gradient-to-r from-transparent via-[#06b6d4]/30 to-transparent" />
      </div>

      {/* ── network topology SVG overlay ── */}
      <svg className="absolute inset-0 w-full h-full opacity-[0.10] pointer-events-none" xmlns="http://www.w3.org/2000/svg">
        {/* lines */}
        <line x1="8%"  y1="18%" x2="28%" y2="40%" stroke="#06b6d4" strokeWidth="0.7" className="login-line-flow" />
        <line x1="28%" y1="40%" x2="52%" y2="25%" stroke="#06b6d4" strokeWidth="0.7" className="login-line-flow" />
        <line x1="52%" y1="25%" x2="78%" y2="42%" stroke="#06b6d4" strokeWidth="0.7" className="login-line-flow" />
        <line x1="28%" y1="40%" x2="42%" y2="68%" stroke="#0e7490" strokeWidth="0.5" className="login-line-flow" />
        <line x1="42%" y1="68%" x2="70%" y2="78%" stroke="#0e7490" strokeWidth="0.5" className="login-line-flow" />
        <line x1="52%" y1="25%" x2="42%" y2="68%" stroke="#164e63" strokeWidth="0.4" className="login-line-flow" />
        <line x1="78%" y1="42%" x2="92%" y2="60%" stroke="#164e63" strokeWidth="0.4" className="login-line-flow" />
        <line x1="8%"  y1="82%" x2="28%" y2="40%" stroke="#164e63" strokeWidth="0.4" className="login-line-flow" />
        <line x1="85%" y1="12%" x2="52%" y2="25%" stroke="#06b6d4" strokeWidth="0.5" className="login-line-flow" />
        {/* nodes */}
        {[
          ['8%','18%',0],['28%','40%',0.6],['52%','25%',1.2],['78%','42%',1.8],
          ['42%','68%',2.4],['70%','78%',0.9],['8%','82%',1.5],['85%','12%',2.1],['92%','60%',0.3],
        ].map(([cx,cy,d], i) => (
          <g key={i}>
            <circle cx={cx} cy={cy} r="3" fill="#06b6d4" className="login-node-p" style={{ animationDelay: `${d}s` }} />
            <circle cx={cx} cy={cy} r="8" fill="none" stroke="#06b6d4" strokeWidth="0.4" className="login-ring-p" style={{ animationDelay: `${Number(d)+0.5}s` }} />
          </g>
        ))}
      </svg>

      {/* ── LEFT decorative panel (hidden on small screens) ── */}
      <div className="hidden lg:flex lg:w-[46%] relative z-10 flex-col items-center justify-center p-12 xl:p-16">
        <div className="w-full max-w-md flex flex-col items-center text-center">
          {/* brand */}
          <motion.div
            initial={{ opacity: 0, y: -16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.1 }}
            className="flex flex-col items-center"
          >
            <div className="inline-flex h-[72px] w-[72px] items-center justify-center rounded-[22px] bg-gradient-to-br from-[#164e63] to-[#06b6d4] shadow-[0_0_60px_rgba(6,182,212,0.3),0_8px_32px_rgba(0,0,0,0.3)]">
              <Activity size={34} className="text-white" />
            </div>
            <h1 className="mt-7 text-[48px] font-extrabold tracking-tight leading-none text-white">
              {sysName === 'Nexora' ? (
                <>Nex<span className="text-[#06b6d4]">ora</span></>
              ) : (
                sysName
              )}
            </h1>
            <p className="text-[#06b6d4]/50 text-[10px] font-bold uppercase tracking-[0.32em] mt-2">
              Network Automation Platform
            </p>
            <p className="mt-5 text-white/30 text-[13px] leading-relaxed max-w-[320px]">
              统一网络运维管理平台 —— 设备管理、自动化编排、合规审计、实时监控，一站式掌控全网。
            </p>
          </motion.div>

          {/* divider */}
          <motion.div
            initial={{ opacity: 0, scaleX: 0 }}
            animate={{ opacity: 1, scaleX: 1 }}
            transition={{ duration: 0.5, delay: 0.3 }}
            className="w-48 h-px bg-gradient-to-r from-transparent via-[#06b6d4]/25 to-transparent my-10"
          />

          {/* stat row */}
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.4 }}
            className="flex gap-6 items-center"
          >
            {stats.map((s, i) => (
              <React.Fragment key={i}>
                {i > 0 && <div className="w-px h-8 bg-white/[0.06]" />}
                <div className="flex flex-col items-center gap-1.5 min-w-[72px]">
                  <div className="p-2 rounded-xl bg-white/[0.04] border border-white/[0.06]">
                    <s.icon size={16} className="text-[#06b6d4]/50" />
                  </div>
                  <p className="text-white/50 text-base font-bold font-mono">{s.value}</p>
                  <p className="text-white/20 text-[9px] font-semibold uppercase tracking-[0.2em]">{s.label}</p>
                </div>
              </React.Fragment>
            ))}
          </motion.div>

          {/* clock */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.5, delay: 0.55 }}
            className="mt-10 flex flex-col items-center"
          >
            <p className="text-white/40 text-[32px] font-mono font-light tracking-[0.12em]">{timeStr}</p>
            <p className="text-white/15 text-[11px] font-mono mt-1 tracking-wider">{dateStr}</p>
          </motion.div>
        </div>
      </div>

      {/* ── RIGHT login card ── */}
      <div className="flex-1 flex items-center justify-center p-6 relative z-10">
        <motion.div
          initial={{ y: 24, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
          className="w-full max-w-[420px]"
        >
          {/* mobile-only brand */}
          <div className="lg:hidden text-center mb-8">
            <div className="mb-4 inline-flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-[#164e63] to-[#06b6d4] shadow-[0_0_40px_rgba(6,182,212,0.25)]">
              <Activity size={32} className="text-white" />
            </div>
            <h1 className="text-3xl font-extrabold tracking-tight text-white">
              {sysName === 'Nexora' ? (
                <>Nex<span className="text-[#06b6d4]">ora</span></>
              ) : (
                sysName
              )}
            </h1>
            <p className="text-[#06b6d4]/50 text-[10px] font-bold uppercase tracking-[0.26em] mt-1.5">Network Automation Platform</p>
          </div>

          {/* card */}
          <div className="rounded-[28px] border border-white/[0.08] bg-white/[0.04] backdrop-blur-xl shadow-[0_32px_80px_rgba(0,0,0,0.45),inset_0_1px_0_rgba(255,255,255,0.06)]">
            {/* top accent line */}
            <div className="h-[2px] rounded-t-[28px] bg-gradient-to-r from-transparent via-[#06b6d4]/60 to-transparent" />

            <div className="px-9 pt-9 pb-8 sm:px-10 sm:pt-10 sm:pb-9">
              {/* heading */}
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.15 }}
                className="mb-8"
              >
                <h2 className="text-xl font-bold text-white/90 tracking-tight">
                  {mfaRequired ? '双因子二次验证 (MFA)' : t('welcomeBack')}
                </h2>
                <p className="text-[13px] mt-1 text-white/30">
                  {mfaRequired
                    ? '您的账户已启用二次认证，请输入手机身份验证器中显示的 6 位动态验证码。'
                    : t('loginSubtitle')}
                </p>
              </motion.div>

              {/* form */}
              {mfaRequired ? (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    onMfaSubmit && onMfaSubmit(mfaCode);
                  }}
                  className="space-y-5"
                >
                  <motion.div
                    animate={loginError ? { x: [-8, 8, -6, 6, 0] } : {}}
                    transition={{ duration: 0.32 }}
                    className="space-y-5"
                  >
                    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
                      <label htmlFor="login-mfa-code" className="block ml-0.5 mb-1.5 text-[10px] font-bold uppercase tracking-[0.2em] text-[#06b6d4]/60">动态验证码</label>
                      <div className="relative group">
                        <div className="absolute left-4 top-1/2 -translate-y-1/2 text-white/20 group-focus-within:text-[#06b6d4]/70 transition-colors">
                          <Shield size={16} />
                        </div>
                        <input
                          id="login-mfa-code"
                          type="text"
                          maxLength={6}
                          placeholder="000000"
                          autoFocus
                          value={mfaCode}
                          onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, ''))}
                          className={`w-full rounded-xl border py-3 pl-11 pr-4 text-sm text-white placeholder-white/15 outline-none transition-all bg-white/[0.04] focus:bg-white/[0.07] focus:shadow-[0_0_0_3px_rgba(6,182,212,0.12)] ${
                            loginError ? 'border-red-500/50' : 'border-white/[0.08] focus:border-[#06b6d4]/50'
                          }`}
                          style={{ letterSpacing: '0.25em' }}
                        />
                      </div>
                    </motion.div>

                    {/* error */}
                    <AnimatePresence>
                      {loginError && (
                        <motion.div
                          initial={{ opacity: 0, y: -4, height: 0 }}
                          animate={{ opacity: 1, y: 0, height: 'auto' }}
                          exit={{ opacity: 0, y: -4, height: 0 }}
                          className="overflow-hidden"
                        >
                          <p className="text-xs font-medium text-red-400 flex items-center gap-1.5 py-1">
                            <XCircle size={13} />{loginError}
                          </p>
                        </motion.div>
                      )}
                    </AnimatePresence>

                    {/* submit */}
                    <motion.div
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: 0.3 }}
                      className="pt-2 flex gap-3"
                    >
                      <button
                        type="button"
                        onClick={onCancelMfa}
                        className="flex-1 py-3 rounded-xl border border-white/10 text-xs font-semibold text-white/70 hover:bg-white/5 transition-colors"
                      >
                        返回密码登录
                      </button>
                      <button
                        type="submit"
                        disabled={isAuthenticating || mfaCode.length < 6}
                        className="flex-1 py-3 rounded-xl bg-gradient-to-r from-[#0e7490] via-[#06b6d4] to-[#22d3ee] hover:shadow-[0_0_48px_rgba(6,182,212,0.3)] disabled:opacity-50 disabled:cursor-not-allowed text-xs font-semibold text-white transition-all flex items-center justify-center gap-1.5"
                      >
                        {isAuthenticating ? (
                          <><RotateCcw className="animate-spin" size={14} />验证中...</>
                        ) : (
                          <>验证并登录 <ArrowRight size={14} /></>
                        )}
                      </button>
                    </motion.div>
                  </motion.div>
                </form>
              ) : (
                <form
                  onSubmit={(e) => { e.preventDefault(); onSubmit(); }}
                  className="space-y-5"
                  autoComplete="on"
                >
                <motion.div
                  animate={loginError ? { x: [-8, 8, -6, 6, 0] } : {}}
                  transition={{ duration: 0.32 }}
                  className="space-y-5"
                >
                  {/* username */}
                  <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
                    <label htmlFor="login-username" className="block ml-0.5 mb-1.5 text-[10px] font-bold uppercase tracking-[0.2em] text-[#06b6d4]/60">{t('username')}</label>
                    <div className="relative group">
                      <div className="absolute left-4 top-1/2 -translate-y-1/2 text-white/20 group-focus-within:text-[#06b6d4]/70 transition-colors">
                        <User size={16} />
                      </div>
                      <input
                        id="login-username"
                        name="username"
                        type="text"
                        placeholder="admin"
                        autoComplete="username"
                        autoFocus
                        value={loginForm.username}
                        onChange={(event) => onUsernameChange(event.target.value)}
                        className={`w-full rounded-xl border py-3 pl-11 pr-4 text-sm text-white placeholder-white/15 outline-none transition-all bg-white/[0.04] focus:bg-white/[0.07] focus:shadow-[0_0_0_3px_rgba(6,182,212,0.12)] ${
                          loginError
                            ? 'border-red-500/50'
                            : 'border-white/[0.08] focus:border-[#06b6d4]/50'
                        }`}
                      />
                    </div>
                  </motion.div>

                  {/* password */}
                  <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.25 }}>
                    <label htmlFor="login-password" className="block ml-0.5 mb-1.5 text-[10px] font-bold uppercase tracking-[0.2em] text-[#06b6d4]/60">{t('password')}</label>
                    <div className="relative group">
                      <div className="absolute left-4 top-1/2 -translate-y-1/2 text-white/20 group-focus-within:text-[#06b6d4]/70 transition-colors">
                        <Lock size={16} />
                      </div>
                      <input
                        id="login-password"
                        name="password"
                        type={showLoginPwd ? 'text' : 'password'}
                        autoComplete="current-password"
                        placeholder="••••••••"
                        value={loginForm.password}
                        onChange={(event) => onPasswordChange(event.target.value)}
                        className={`w-full rounded-xl border py-3 pl-11 pr-12 text-sm text-white placeholder-white/15 outline-none transition-all bg-white/[0.04] focus:bg-white/[0.07] focus:shadow-[0_0_0_3px_rgba(6,182,212,0.12)] ${
                          loginError
                            ? 'border-red-500/50'
                            : 'border-white/[0.08] focus:border-[#06b6d4]/50'
                        }`}
                      />
                      <button
                        type="button"
                        onClick={onTogglePassword}
                        aria-label={showLoginPwd ? 'Hide password' : 'Show password'}
                        className="absolute right-4 top-1/2 -translate-y-1/2 text-white/20 hover:text-white/50 transition-colors"
                      >
                        {showLoginPwd ? <EyeOff size={15} /> : <Eye size={15} />}
                      </button>
                    </div>
                  </motion.div>

                  {/* error */}
                  <AnimatePresence>
                    {loginError && (
                      <motion.div
                        initial={{ opacity: 0, y: -4, height: 0 }}
                        animate={{ opacity: 1, y: 0, height: 'auto' }}
                        exit={{ opacity: 0, y: -4, height: 0 }}
                        className="overflow-hidden"
                      >
                        <p className="text-xs font-medium text-red-400 flex items-center gap-1.5 py-1">
                          <XCircle size={13} />{loginError}
                        </p>
                      </motion.div>
                    )}
                  </AnimatePresence>

                  {/* remember me */}
                  <motion.label
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: 0.3 }}
                    className="flex items-center gap-2.5 cursor-pointer"
                  >
                    <div className="relative">
                      <input
                        id="login-remember-me"
                        type="checkbox"
                        checked={rememberMe}
                        onChange={(event) => onRememberMeChange(event.target.checked)}
                        className="peer sr-only"
                      />
                      <div className={`w-4 h-4 rounded border transition-all flex items-center justify-center ${
                        rememberMe
                          ? 'bg-[#06b6d4] border-[#06b6d4] shadow-[0_0_8px_rgba(6,182,212,0.3)]'
                          : 'border-white/15 bg-white/[0.04]'
                      }`}>
                        {rememberMe && (
                          <svg width="10" height="8" viewBox="0 0 10 8" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <path d="M1 4L3.5 6.5L9 1" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        )}
                      </div>
                    </div>
                    <span className="text-xs text-white/30">{t('rememberMe')}</span>
                  </motion.label>

                  {/* forgot password hint */}
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: 0.32 }}
                    className="flex items-center justify-end"
                  >
                    <button
                      type="button"
                      onClick={() => setShowForgotPwd(true)}
                      className="text-[11px] text-white/20 hover:text-[#06b6d4]/70 flex items-center gap-1 transition-colors"
                    >
                      <HelpCircle size={11} />{t('forgotPassword')}
                    </button>
                  </motion.div>

                  {/* submit */}
                  <motion.div
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.35 }}
                    className="pt-1"
                  >
                    <button
                      type="submit"
                      disabled={isAuthenticating}
                      className={`group relative flex w-full items-center justify-center gap-2.5 rounded-xl py-3.5 text-[13px] font-bold tracking-wide text-white transition-all duration-200 disabled:opacity-50 hover:shadow-[0_0_48px_rgba(6,182,212,0.3)] active:scale-[0.98] overflow-hidden ${
                        loginError
                          ? 'bg-red-500/70 shadow-[0_0_20px_rgba(239,68,68,0.25)]'
                          : 'bg-gradient-to-r from-[#0e7490] via-[#06b6d4] to-[#22d3ee] shadow-[0_4px_24px_rgba(6,182,212,0.3)]'
                      }`}
                    >
                      {!loginError && !isAuthenticating && (
                        <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/[0.08] to-transparent translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
                      )}
                      <span className="relative z-10 flex items-center gap-2">
                        {isAuthenticating ? (
                          <><RotateCcw className="animate-spin" size={15} />{t('authenticating')}</>
                        ) : (
                          <>{t('login')}<ArrowRight size={15} className="group-hover:translate-x-0.5 transition-transform" /></>
                        )}
                      </span>
                    </button>
                  </motion.div>
                </motion.div>
                </form>
              )}

              {/* footer */}
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.45 }}
                className="mt-8 pt-5 border-t border-white/[0.06]"
              >
                <div className="flex items-center justify-center gap-2.5 flex-wrap">
                  <div className="flex items-center gap-1.5">
                    <div className="h-1.5 w-1.5 rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.7)]" />
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-white/20">{t('systemOnline')}</span>
                  </div>
                  <span className="text-[10px] text-white/8">·</span>
                  <span className="text-[10px] font-mono text-white/12">{sysName} {sysVersion}</span>
                  <span className="text-[10px] text-white/8">·</span>
                  <span className="text-[10px] text-white/12">© {new Date().getFullYear()} {sysName}</span>
                </div>
              </motion.div>
            </div>

            {/* bottom accent */}
            <div className="h-px rounded-b-[28px] bg-gradient-to-r from-transparent via-[#0e7490]/30 to-transparent" />
          </div>
        </motion.div>
      </div>

      {/* Forgot password modal */}
      <ForgotPasswordModal
        open={showForgotPwd}
        onClose={() => setShowForgotPwd(false)}
        t={t}
        initialUsername={loginForm.username}
      />
    </div>
  );
};

export default LoginScreen;