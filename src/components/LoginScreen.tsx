import React, { useEffect, useState } from 'react';
import { Activity, Eye, EyeOff, Lock, RotateCcw, ArrowRight, User, XCircle, Shield, HelpCircle, Clock, Server, CheckCircle2, Cpu } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import ForgotPasswordModal from './ForgotPasswordModal';
import ThreeCyberNetwork from './home/ThreeCyberNetwork';

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
  captchaRequired?: boolean;
  captchaImage?: string;
  captchaCode?: string;
  onCaptchaChange?: (value: string) => void;
  loadingCaptcha?: boolean;
  onRefreshCaptcha?: () => void;
  onMfaSubmit?: (code: string) => void;
  onCancelMfa?: () => void;
  onUsernameChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  onTogglePassword: () => void;
  onRememberMeChange: (value: boolean) => void;
  onSubmit: () => void;
}

const LoginScreen: React.FC<LoginScreenProps> = ({
  t,
  loginForm,
  loginError,
  showLoginPwd,
  rememberMe,
  isAuthenticating,
  mfaRequired = false,
  captchaRequired = false,
  captchaImage = '',
  captchaCode = '',
  onCaptchaChange,
  loadingCaptcha = false,
  onRefreshCaptcha,
  onMfaSubmit,
  onCancelMfa,
  onUsernameChange,
  onPasswordChange,
  onTogglePassword,
  onRememberMeChange,
  onSubmit,
}) => {
  const [mfaCode, setMfaCode] = useState('');
  const [sysName, setSysName] = useState('Nexora');
  const [sysVersion, setSysVersion] = useState('v2.0');
  const [managedDevices, setManagedDevices] = useState<number | null>(null);
  const [showForgotPwd, setShowForgotPwd] = useState(false);
  const [currentTime, setCurrentTime] = useState('');

  // Live real-time clock updating every second
  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      const yr = now.getFullYear();
      const mo = String(now.getMonth() + 1).padStart(2, '0');
      const da = String(now.getDate()).padStart(2, '0');
      const hh = String(now.getHours()).padStart(2, '0');
      const mm = String(now.getMinutes()).padStart(2, '0');
      const ss = String(now.getSeconds()).padStart(2, '0');
      setCurrentTime(`${yr}-${mo}-${da} ${hh}:${mm}:${ss}`);
    };

    updateTime();
    const timer = setInterval(updateTime, 1000);
    return () => clearInterval(timer);
  }, []);

  // Fetch system telemetry
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
          if (typeof d.managed_devices === 'number') setManagedDevices(d.managed_devices);
        }
      } catch { /* ignore */ }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="h-screen w-screen flex flex-col justify-between font-sans relative overflow-hidden select-none bg-[#ffffff] text-gray-900 p-5 sm:p-7 lg:p-9">
      {/* ── 1. Spatial Network Field Background ── */}
      <ThreeCyberNetwork />

      {/* ── 2. Top Header: Minimal Brand, Real-time Clock & Live Status ── */}
      <header className="w-full relative z-20 flex items-center justify-between pointer-events-none flex-shrink-0">
        {/* Left: Brand Identity with Muted Version */}
        <div className="flex items-center gap-2.5 pointer-events-auto">
          <div className="h-7 w-7 rounded-lg bg-gradient-to-tr from-[#2563EB] via-[#4F46E5] to-[#7C3AED] p-[1.5px] shadow-xs">
            <div className="h-full w-full bg-white rounded-[6.5px] flex items-center justify-center">
              <Activity size={14} className="text-[#2563EB]" />
            </div>
          </div>
          <div className="flex items-baseline gap-1.5">
            <span className="text-lg font-bold tracking-tight text-gray-950">
              {sysName}
            </span>
            <span className="text-[10px] text-gray-400 font-mono">
              {sysVersion}
            </span>
          </div>
        </div>

        {/* Right: Telemetry & Live Status (Consolidated Minimalist Header) */}
        <div className="flex items-center gap-2 pointer-events-auto">
          <div className="flex items-center gap-2.5 px-3.5 py-1.5 rounded-full bg-white/70 backdrop-blur-md border border-gray-200/50 shadow-2xs text-[11px] text-gray-500 font-normal">
            {currentTime && (
              <>
                <div className="hidden sm:flex items-center gap-1.5 font-mono text-gray-500">
                  <Clock size={11} className="text-gray-400" />
                  <span>{currentTime}</span>
                </div>
                <span className="hidden sm:inline text-gray-300">·</span>
              </>
            )}

            <div className="hidden md:flex items-center gap-1.5 text-gray-500">
              <Server size={11} className="text-blue-500" />
              <span>在管资产 <strong className="text-gray-700 font-medium">{managedDevices !== null && managedDevices > 0 ? `${managedDevices} 台` : '已接入'}</strong></span>
            </div>

            <span className="hidden md:inline text-gray-300">·</span>

            <div className="hidden lg:flex items-center gap-1.5 text-gray-500">
              <CheckCircle2 size={11} className="text-emerald-500" />
              <span>可用率 <strong className="text-gray-700 font-medium">99.99%</strong></span>
            </div>

            <span className="hidden lg:inline text-gray-300">·</span>

            <div className="flex items-center gap-1.5 font-medium text-gray-600">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
              <span>{t('systemOnline')}</span>
            </div>
          </div>
        </div>
      </header>

      {/* ── 3. Visual Centerpiece: Brand Slogan -> Core Philosophy -> Login Action Card ── */}
      <main className="w-full max-w-2xl mx-auto flex flex-col items-center justify-center relative z-20 my-auto">
        {/* Primary Philosophy & Headline */}
        <motion.div
          initial={{ opacity: 0, y: -12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.55, ease: 'easeOut' }}
          className="text-center mb-5 sm:mb-7 pointer-events-none"
        >
          <h1 className="text-3xl sm:text-4xl lg:text-[40px] font-extrabold tracking-tight text-gray-950 leading-[1.18]">
            开启下一代全网自动化运维
          </h1>
          <p className="mt-2.5 sm:mt-3 text-xs sm:text-sm text-gray-400 font-normal tracking-wide max-w-lg mx-auto">
            设备自动化编排 · 巡检合规审计 · 数字孪生全景感知
          </p>
        </motion.div>

        {/* Spatial Frosted Glass Login Card */}
        <motion.div
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.1, ease: 'easeOut' }}
          className="w-full max-w-[390px]"
        >
          <div className="rounded-3xl bg-white/80 backdrop-blur-xl border border-gray-200/70 p-7 sm:p-8 shadow-[0_20px_50px_rgba(0,0,0,0.04)] transition-all">
            <div className="mb-5">
              <h2 className="text-lg font-bold tracking-tight text-gray-950">
                {mfaRequired ? '双因子二次验证 (MFA)' : t('welcomeBack')}
              </h2>
              <p className="text-xs text-gray-400 mt-1">
                {mfaRequired
                  ? '请输入手机身份验证器中的 6 位动态验证码'
                  : '登录到网络自动化控制台'}
              </p>
            </div>

            {mfaRequired ? (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  onMfaSubmit && onMfaSubmit(mfaCode);
                }}
                className="space-y-4"
              >
                <div className="space-y-1.5">
                  <label htmlFor="login-mfa-code" className="block text-xs font-medium text-gray-700">
                    动态验证码
                  </label>
                  <div className="relative group">
                    <div className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400 group-focus-within:text-blue-600 transition-colors">
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
                      className="w-full rounded-2xl border border-gray-200/80 bg-white/70 py-3 pl-10 pr-4 text-center text-sm font-mono font-bold tracking-[0.3em] text-gray-900 placeholder:text-gray-300 outline-none transition-all focus:bg-white focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10"
                    />
                  </div>
                </div>

                {/* error */}
                <AnimatePresence>
                  {loginError && (
                    <motion.div
                      initial={{ opacity: 0, y: -4, height: 0 }}
                      animate={{ opacity: 1, y: 0, height: 'auto' }}
                      exit={{ opacity: 0, y: -4, height: 0 }}
                      className="overflow-hidden"
                    >
                      <div className="p-3.5 rounded-2xl bg-rose-50/70 border border-rose-200/60 shadow-2xs text-xs text-rose-900 leading-relaxed">
                        <div className="flex items-start gap-2.5">
                          <XCircle size={15} className="text-rose-500 flex-shrink-0 mt-0.5" />
                          <div className="flex-1 space-y-1">
                            <p className="font-semibold text-rose-950">{loginError.split('。')[0] || loginError}</p>
                            {loginError.includes('。') && (
                              <p className="text-[11px] text-rose-700/90">
                                {loginError.split('。').slice(1).join('。').trim()}
                              </p>
                            )}
                          </div>
                        </div>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>

                <div className="pt-2 flex gap-3">
                  <button
                    type="button"
                    onClick={onCancelMfa}
                    className="flex-1 py-3 rounded-full border border-gray-200 text-xs font-semibold text-gray-700 hover:bg-gray-50 transition-colors"
                  >
                    返回
                  </button>
                  <button
                    type="submit"
                    disabled={isAuthenticating || mfaCode.length < 6}
                    className="flex-1 py-3 rounded-full bg-gray-950 hover:bg-black disabled:opacity-50 text-xs font-semibold text-white shadow-sm transition-all flex items-center justify-center gap-1.5"
                  >
                    {isAuthenticating ? (
                      <><RotateCcw className="animate-spin" size={13} />验证中</>
                    ) : (
                      <>验证登录 <ArrowRight size={13} /></>
                    )}
                  </button>
                </div>
              </form>
            ) : (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  onSubmit();
                }}
                className="space-y-3.5"
              >
                {/* Username Input */}
                <div className="space-y-1.5">
                  <label htmlFor="login-username" className="block text-xs font-medium text-gray-700">
                    {t('username')}
                  </label>
                  <div className="relative group">
                    <div className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400 group-focus-within:text-blue-600 transition-colors">
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
                      onChange={(e) => onUsernameChange(e.target.value)}
                      className="w-full rounded-2xl border border-gray-200/80 bg-white/70 py-3 pl-10 pr-4 text-sm text-gray-900 placeholder:text-gray-400 outline-none transition-all focus:bg-white focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10"
                    />
                  </div>
                </div>

                {/* Password Input */}
                <div className="space-y-1.5">
                  <label htmlFor="login-password" className="block text-xs font-medium text-gray-700">
                    {t('password')}
                  </label>
                  <div className="relative group">
                    <div className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400 group-focus-within:text-blue-600 transition-colors">
                      <Lock size={16} />
                    </div>
                    <input
                      id="login-password"
                      name="password"
                      type={showLoginPwd ? 'text' : 'password'}
                      autoComplete="current-password"
                      placeholder="••••••••"
                      value={loginForm.password}
                      onChange={(e) => onPasswordChange(e.target.value)}
                      className="w-full rounded-2xl border border-gray-200/80 bg-white/70 py-3 pl-10 pr-11 text-sm text-gray-900 placeholder:text-gray-400 outline-none transition-all focus:bg-white focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10"
                    />
                    <button
                      type="button"
                      onClick={onTogglePassword}
                      aria-label={showLoginPwd ? 'Hide password' : 'Show password'}
                      className="absolute right-3.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 transition-colors"
                    >
                      {showLoginPwd ? <EyeOff size={15} /> : <Eye size={15} />}
                    </button>
                  </div>
                </div>

                {/* Captcha Block (Unified & Elegant) */}
                <AnimatePresence>
                  {captchaRequired && (
                    <motion.div
                      initial={{ opacity: 0, y: -4, height: 0 }}
                      animate={{ opacity: 1, y: 0, height: 'auto' }}
                      exit={{ opacity: 0, y: -4, height: 0 }}
                      transition={{ duration: 0.25, ease: 'easeOut' }}
                      className="overflow-hidden space-y-1.5 pt-0.5"
                    >
                      <div className="flex items-center justify-between">
                        <label htmlFor="login-captcha" className="block text-xs font-medium text-gray-700">
                          {t('loginCaptchaLabel')}
                        </label>
                        <span className="inline-flex items-center gap-1.5 text-[10px] text-amber-600 font-medium">
                          <span className="h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" />
                          安全核验
                        </span>
                      </div>
                      <div className="flex items-center gap-2.5">
                        <div className="relative flex-1 group">
                          <div className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400 group-focus-within:text-blue-600 transition-colors">
                            <Shield size={16} />
                          </div>
                          <input
                            id="login-captcha"
                            name="captcha"
                            type="text"
                            maxLength={4}
                            autoFocus
                            autoComplete="off"
                            placeholder="输入4位验证码"
                            value={captchaCode}
                            onChange={(e) => onCaptchaChange && onCaptchaChange(e.target.value.toUpperCase().slice(0, 4))}
                            className="w-full rounded-2xl border border-gray-200/80 bg-white/70 py-2.5 pl-10 pr-3 text-sm font-mono font-bold tracking-[0.2em] text-gray-900 placeholder:text-gray-400 placeholder:font-normal placeholder:tracking-normal outline-none transition-all focus:bg-white focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10 uppercase"
                          />
                        </div>

                        {/* High-res Captcha Image with Clean Hover State */}
                        <div
                          onClick={onRefreshCaptcha}
                          title="点击刷新验证码"
                          className="group relative h-10 w-28 rounded-2xl overflow-hidden cursor-pointer border border-gray-200/90 bg-slate-50/80 hover:border-blue-500 hover:shadow-2xs transition-all flex items-center justify-center flex-shrink-0 active:scale-98 select-none"
                        >
                          {captchaImage ? (
                            <img src={captchaImage} alt="Captcha" className="w-full h-full object-cover select-none pointer-events-none" />
                          ) : (
                            <span className="text-[10px] text-gray-400 animate-pulse">生成中...</span>
                          )}
                          <div className="absolute inset-0 bg-black/0 group-hover:bg-black/5 transition-colors flex items-center justify-end pr-1.5 opacity-0 group-hover:opacity-100">
                            <div className="h-6 w-6 rounded-lg bg-white/95 shadow-xs flex items-center justify-center text-gray-700">
                              <RotateCcw size={12} className={loadingCaptcha ? 'animate-spin' : ''} />
                            </div>
                          </div>
                        </div>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>

                {/* Error Banner (Refined SaaS Alert) */}
                <AnimatePresence>
                  {loginError && (
                    <motion.div
                      initial={{ opacity: 0, y: -4, height: 0 }}
                      animate={{ opacity: 1, y: 0, height: 'auto' }}
                      exit={{ opacity: 0, y: -4, height: 0 }}
                      transition={{ duration: 0.25, ease: 'easeOut' }}
                      className="overflow-hidden"
                    >
                      <div className="p-3.5 rounded-2xl bg-rose-50/70 border border-rose-200/60 shadow-2xs text-xs text-rose-900 leading-relaxed">
                        <div className="flex items-start gap-2.5">
                          <XCircle size={15} className="text-rose-500 flex-shrink-0 mt-0.5" />
                          <div className="flex-1 space-y-1">
                            <p className="font-semibold text-rose-950">
                              {loginError.includes('。') ? loginError.split('。')[0] : loginError}
                            </p>
                            {loginError.includes('。') && (
                              <p className="text-[11px] text-rose-700/90 leading-normal">
                                {loginError.split('。').slice(1).join('。').trim()}
                              </p>
                            )}
                            {(loginError.includes('连续失败') || loginError.includes('锁定') || loginError.includes('忘记密码')) && (
                              <div className="pt-1.5 mt-1 flex items-center justify-between border-t border-rose-200/50 text-[11px]">
                                <button
                                  type="button"
                                  onClick={() => setShowForgotPwd(true)}
                                  className="text-blue-600 hover:text-blue-700 font-semibold transition-colors flex items-center gap-1 cursor-pointer"
                                >
                                  <HelpCircle size={12} />
                                  <span>找回密码</span>
                                </button>
                                <span className="text-gray-400 text-[10px]">或联系系统管理员</span>
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>

                {/* Remember Me & Forgot Password */}
                <div className="flex items-center justify-between pt-1">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      id="login-remember-me"
                      type="checkbox"
                      checked={rememberMe}
                      onChange={(e) => onRememberMeChange(e.target.checked)}
                      className="h-3.5 w-3.5 rounded border-gray-300 text-gray-900 focus:ring-gray-900 cursor-pointer"
                    />
                    <span className="text-xs text-gray-400">{t('rememberMe')}</span>
                  </label>

                  <button
                    type="button"
                    onClick={() => setShowForgotPwd(true)}
                    className="text-xs text-gray-400 hover:text-gray-700 transition-colors cursor-pointer"
                  >
                    {t('forgotPassword')}
                  </button>
                </div>

                {/* Mature, Restrained Deep Pill Action Button */}
                <div className="pt-2">
                  <button
                    type="submit"
                    disabled={isAuthenticating}
                    className="group relative flex w-full items-center justify-center gap-2 rounded-full bg-gray-950 hover:bg-black py-3.5 px-6 text-sm font-medium text-white shadow-sm transition-all duration-200 hover:-translate-y-0.5 disabled:opacity-50 cursor-pointer"
                  >
                    {isAuthenticating ? (
                      <><RotateCcw className="animate-spin" size={14} />{t('authenticating')}</>
                    ) : (
                      <>
                        <span>{t('login')}</span>
                        <ArrowRight size={14} className="transition-transform duration-200 group-hover:translate-x-1" />
                      </>
                    )}
                  </button>
                </div>
              </form>
            )}
          </div>
        </motion.div>
      </main>

      {/* ── 4. Minimalist Footer: Low Contrast Copyright ── */}
      <footer className="w-full relative z-20 text-center text-[11px] text-gray-400/70 pointer-events-none flex-shrink-0">
        <p>{sysName} {sysVersion} · © {new Date().getFullYear()} Nexora Network Inc. All rights reserved.</p>
      </footer>

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