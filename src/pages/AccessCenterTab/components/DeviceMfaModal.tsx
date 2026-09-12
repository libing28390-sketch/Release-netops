import React from 'react';
import { KeyRound, ShieldCheck, Smartphone, X } from 'lucide-react';
import { motion } from 'framer-motion';

interface MfaTarget {
  device: { hostname: string; ip_address: string; management_port?: number };
  appType: 'xshell' | 'web';
  identity: 'normal' | 'privileged';
}

interface DeviceMfaModalProps {
  isZh: boolean;
  currentUsername?: string;
  target: MfaTarget;
  fixedPin: string;
  dynamicCode: string;
  showFixedPin: boolean;
  onFixedPinChange: (value: string) => void;
  onDynamicCodeChange: (value: string) => void;
  onToggleFixedPin: () => void;
  onClose: () => void;
  onVerify: () => void;
}

/** Compact, app-based MFA dialog for privileged device access. */
export default function DeviceMfaModal({
  isZh,
  currentUsername,
  target,
  fixedPin,
  dynamicCode,
  showFixedPin,
  onFixedPinChange,
  onDynamicCodeChange,
  onToggleFixedPin,
  onClose,
  onVerify,
}: DeviceMfaModalProps) {
  const port = Number(target.device.management_port || 22) || 22;
  const canVerify = fixedPin.length === 6 && dynamicCode.length === 6;

  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-sm">
      <motion.div
        initial={{ opacity: 0, y: 12, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 12, scale: 0.98 }}
        className="w-full max-w-[440px] overflow-hidden rounded-[1.75rem] border border-white/70 bg-white shadow-[0_24px_80px_rgba(15,23,42,0.28)]"
      >
        <div className="flex items-start justify-between border-b border-slate-100 bg-gradient-to-br from-cyan-50 via-white to-white px-6 py-5">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-cyan-500 text-white shadow-lg shadow-cyan-500/20">
              <ShieldCheck size={22} />
            </div>
            <div>
              <h3 className="text-base font-black tracking-tight text-slate-800">
                {isZh ? '管理员访问验证' : 'Administrator verification'}
              </h3>
              <p className="mt-1 text-[10px] font-bold uppercase tracking-[0.18em] text-cyan-600">
                {isZh ? '固定安全码 + MFA 验证器' : 'Fixed PIN + authenticator'}
              </p>
            </div>
          </div>
          <button type="button" onClick={onClose} className="rounded-xl p-2 text-slate-300 transition hover:bg-white hover:text-slate-600" aria-label={isZh ? '关闭' : 'Close'}>
            <X size={18} />
          </button>
        </div>

        <div className="space-y-5 px-6 py-5">
          <div className="rounded-2xl border border-slate-100 bg-slate-50 px-4 py-3">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-black text-slate-800">{target.device.hostname}</p>
                <p className="mt-1 text-xs font-medium text-slate-400">{target.device.ip_address}:{port}</p>
              </div>
              <span className="shrink-0 rounded-full bg-amber-50 px-2.5 py-1 text-[10px] font-black uppercase tracking-wider text-amber-700">
                {isZh ? '管理员账号' : 'Admin account'}
              </span>
            </div>
            {currentUsername && (
              <p className="mt-2 border-t border-slate-200 pt-2 text-[10px] font-semibold text-slate-400">
                {isZh ? '当前管理员：' : 'Administrator: '}{currentUsername}
              </p>
            )}
          </div>

          <label className="block">
            <span className="mb-2 flex items-center gap-2 text-[11px] font-black uppercase tracking-wider text-slate-500">
              <KeyRound size={14} className="text-cyan-600" />
              {isZh ? '固定安全码（6 位）' : 'Fixed PIN (6 digits)'}
            </span>
            <div className="relative">
              <input
                autoFocus
                type={showFixedPin ? 'text' : 'password'}
                inputMode="numeric"
                maxLength={6}
                value={fixedPin}
                onChange={(event) => onFixedPinChange(event.target.value.replace(/\D/g, ''))}
                onKeyDown={(event) => { if (event.key === 'Enter' && canVerify) onVerify(); }}
                placeholder="••••••"
                className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 pr-12 text-center text-lg font-black tracking-[0.45em] text-slate-800 outline-none transition focus:border-cyan-500 focus:ring-4 focus:ring-cyan-500/10"
              />
              <button type="button" tabIndex={-1} onClick={onToggleFixedPin} className="absolute right-3 top-1/2 -translate-y-1/2 text-[11px] font-bold text-slate-400 hover:text-cyan-600">
                {showFixedPin ? (isZh ? '隐藏' : 'Hide') : (isZh ? '显示' : 'Show')}
              </button>
            </div>
          </label>

          <label className="block">
            <span className="mb-2 flex items-center gap-2 text-[11px] font-black uppercase tracking-wider text-slate-500">
              <Smartphone size={14} className="text-cyan-600" />
              {isZh ? 'MFA 验证器动态码' : 'Authenticator code'}
            </span>
            <input
              type="text"
              inputMode="numeric"
              maxLength={6}
              value={dynamicCode}
              onChange={(event) => onDynamicCodeChange(event.target.value.replace(/\D/g, ''))}
              onKeyDown={(event) => { if (event.key === 'Enter' && canVerify) onVerify(); }}
              placeholder="000000"
              className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-center text-lg font-black tracking-[0.45em] text-slate-800 outline-none transition focus:border-cyan-500 focus:ring-4 focus:ring-cyan-500/10"
            />
            <span className="mt-2 block text-[10px] leading-relaxed text-slate-400">
              {isZh ? '请输入 Google Authenticator、腾讯/阿里等兼容 TOTP 验证器显示的 6 位动态码。' : 'Enter the current six-digit code from a compatible TOTP authenticator.'}
            </span>
          </label>

          <div className="rounded-xl border border-cyan-100 bg-cyan-50/70 px-3.5 py-3 text-[10px] leading-relaxed text-cyan-800">
            {isZh ? '验证通过后仅释放本次管理员设备会话，固定安全码不会发送到设备或浏览器。' : 'Only this administrator session is released after verification; the fixed PIN is never sent to the device or browser.'}
          </div>
        </div>

        <div className="flex gap-3 border-t border-slate-100 bg-slate-50/70 px-6 py-4">
          <button type="button" onClick={onClose} className="flex-1 rounded-xl border border-slate-200 bg-white py-3 text-sm font-bold text-slate-500 transition hover:border-slate-300 hover:text-slate-700">
            {isZh ? '取消' : 'Cancel'}
          </button>
          <button type="button" disabled={!canVerify} onClick={onVerify} className="flex-[1.5] rounded-xl bg-gradient-to-r from-cyan-500 to-blue-500 py-3 text-sm font-black text-white shadow-lg shadow-cyan-500/20 transition hover:from-cyan-600 hover:to-blue-600 disabled:cursor-not-allowed disabled:opacity-40">
            {isZh ? '验证并登录' : 'Verify & connect'}
          </button>
        </div>
      </motion.div>
    </div>
  );
}
