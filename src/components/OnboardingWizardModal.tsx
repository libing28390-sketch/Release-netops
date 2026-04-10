import React, { useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { X, CheckCircle2, Shield, Wifi, Rocket, AlertTriangle, Loader2, RotateCcw, Eye, EyeOff } from 'lucide-react';
import type { Device } from '../types';

interface OnboardingWizardModalProps {
  device: Device;
  language: string;
  onClose: () => void;
  onComplete: (device: Device) => void;
}

const STEPS = [
  { key: 'pending_credentials', icon: Shield,   label_en: 'Set Credentials',   label_zh: '设置凭据' },
  { key: 'credentials_set',     icon: Wifi,      label_en: 'Verify Connection', label_zh: '验证连通' },
  { key: 'verified',            icon: Rocket,    label_en: 'Activate',          label_zh: '激活设备' },
  { key: 'active',              icon: CheckCircle2, label_en: 'Complete',       label_zh: '完成' },
] as const;

type OnboardingStatus = 'pending_credentials' | 'credentials_set' | 'verified' | 'active';
const STATUS_INDEX: Record<OnboardingStatus, number> = {
  pending_credentials: 0,
  credentials_set: 1,
  verified: 2,
  active: 3,
};

const API_BASE = import.meta.env.VITE_API_BASE || '';

export default function OnboardingWizardModal({ device, language, onClose, onComplete }: OnboardingWizardModalProps) {
  const zh = language === 'zh';
  const currentStatus = (device.onboarding_status as OnboardingStatus) || 'pending_credentials';
  const currentIndex = STATUS_INDEX[currentStatus] ?? 0;

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Credential form state
  const [username, setUsername] = useState(device.username || '');
  const [password, setPassword] = useState('');
  const [enablePassword, setEnablePassword] = useState('');
  const [privUsername, setPrivUsername] = useState(device.priv_username || '');
  const [pwdVisible, setPwdVisible] = useState(false);
  const [enablePwdVisible, setEnablePwdVisible] = useState(false);

  const callOnboard = useCallback(async (action: string, extra: Record<string, string> = {}) => {
    setLoading(true);
    setError(null);
    try {
      const token = localStorage.getItem('netops_token') || '';
      const resp = await fetch(`${API_BASE}/api/devices/${device.id}/onboard`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ action, ...extra }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || data.message || 'Failed');
      return data.onboarding_status as OnboardingStatus;
    } catch (e: any) {
      setError(e.message || 'Unknown error');
      return null;
    } finally {
      setLoading(false);
    }
  }, [device.id]);

  const handleSetCredentials = async () => {
    if (!username.trim()) {
      setError(zh ? '请输入用户名' : 'Username is required');
      return;
    }
    if (!password.trim()) {
      setError(zh ? '请输入密码' : 'Password is required');
      return;
    }
    const result = await callOnboard('set_credentials', {
      username: username.trim(),
      password: password.trim(),
      enable_password: enablePassword.trim(),
      priv_username: privUsername.trim(),
    });
    if (result) {
      onComplete({ ...device, onboarding_status: result, username: username.trim() });
    }
  };

  const handleVerify = async () => {
    const result = await callOnboard('verify');
    if (result) {
      onComplete({ ...device, onboarding_status: result });
    }
  };

  const handleActivate = async () => {
    const result = await callOnboard('activate');
    if (result) {
      onComplete({ ...device, onboarding_status: result, status: 'online' });
    }
  };

  const handleReset = async () => {
    const result = await callOnboard('reset');
    if (result) {
      onComplete({ ...device, onboarding_status: result });
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={onClose}>
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        exit={{ opacity: 0, scale: 0.95 }}
        className="bg-gray-800 rounded-xl shadow-2xl border border-cyan-800/40 w-full max-w-lg mx-4 overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700/50">
          <h2 className="text-lg font-semibold text-cyan-100">
            {zh ? '设备口令上手' : 'Device Onboarding'} — {device.hostname || device.ip_address}
          </h2>
          <button onClick={onClose} className="p-1 rounded hover:bg-gray-700 text-gray-400 hover:text-gray-200 transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Step Indicator */}
        <div className="px-6 py-4 border-b border-gray-700/30">
          <div className="flex items-center justify-between">
            {STEPS.map((step, i) => {
              const Icon = step.icon;
              const done = currentIndex > i;
              const active = currentIndex === i;
              return (
                <React.Fragment key={step.key}>
                  <div className="flex flex-col items-center gap-1">
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center transition-colors ${done ? 'bg-cyan-600 text-white' : active ? 'bg-cyan-500/30 text-cyan-300 ring-2 ring-cyan-400' : 'bg-gray-700 text-gray-500'}`}>
                      {done ? <CheckCircle2 className="w-5 h-5" /> : <Icon className="w-5 h-5" />}
                    </div>
                    <span className={`text-xs ${active ? 'text-cyan-300 font-medium' : done ? 'text-cyan-400' : 'text-gray-500'}`}>
                      {zh ? step.label_zh : step.label_en}
                    </span>
                  </div>
                  {i < STEPS.length - 1 && (
                    <div className={`flex-1 h-0.5 mx-2 rounded ${done ? 'bg-cyan-600' : 'bg-gray-700'}`} />
                  )}
                </React.Fragment>
              );
            })}
          </div>
        </div>

        {/* Content Area */}
        <div className="px-6 py-5 min-h-[200px]">
          <AnimatePresence mode="wait">
            {/* Step 1: Set Credentials */}
            {currentStatus === 'pending_credentials' && (
              <motion.div key="creds" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }} className="space-y-3">
                <p className="text-sm text-gray-400 mb-3">
                  {zh ? '请为该设备配置 SSH 登录凭据：' : 'Configure SSH credentials for this device:'}
                </p>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">{zh ? '用户名' : 'Username'}</label>
                  <input className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm text-gray-100 focus:border-cyan-500 outline-none" value={username} onChange={e => setUsername(e.target.value)} />
                </div>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">{zh ? '密码' : 'Password'}</label>
                  <div className="relative">
                    <input type={pwdVisible ? 'text' : 'password'} className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 pr-10 text-sm text-gray-100 focus:border-cyan-500 outline-none" value={password} onChange={e => setPassword(e.target.value)} />
                    <button type="button" className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-200" onClick={() => setPwdVisible(!pwdVisible)}>
                      {pwdVisible ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">{zh ? 'Enable 密码（可选）' : 'Enable Password (optional)'}</label>
                  <div className="relative">
                    <input type={enablePwdVisible ? 'text' : 'password'} className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 pr-10 text-sm text-gray-100 focus:border-cyan-500 outline-none" value={enablePassword} onChange={e => setEnablePassword(e.target.value)} />
                    <button type="button" className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-200" onClick={() => setEnablePwdVisible(!enablePwdVisible)}>
                      {enablePwdVisible ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">{zh ? '特权用户名（可选）' : 'Privileged Username (optional)'}</label>
                  <input className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm text-gray-100 focus:border-cyan-500 outline-none" value={privUsername} onChange={e => setPrivUsername(e.target.value)} />
                </div>
              </motion.div>
            )}

            {/* Step 2: Verify */}
            {currentStatus === 'credentials_set' && (
              <motion.div key="verify" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }} className="text-center py-6">
                <Wifi className="w-12 h-12 mx-auto text-cyan-400 mb-3" />
                <p className="text-sm text-gray-300">
                  {zh ? '凭据已保存，点击下方按钮进行 SSH 连通性验证。' : 'Credentials saved. Click below to verify SSH connectivity.'}
                </p>
              </motion.div>
            )}

            {/* Step 3: Activate */}
            {currentStatus === 'verified' && (
              <motion.div key="activate" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }} className="text-center py-6">
                <Rocket className="w-12 h-12 mx-auto text-emerald-400 mb-3" />
                <p className="text-sm text-gray-300">
                  {zh ? '连通性验证通过！点击激活将设备纳入正常运维。' : 'Connectivity verified! Click Activate to bring the device online.'}
                </p>
              </motion.div>
            )}

            {/* Step 4: Complete */}
            {currentStatus === 'active' && (
              <motion.div key="done" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }} className="text-center py-6">
                <CheckCircle2 className="w-12 h-12 mx-auto text-green-400 mb-3" />
                <p className="text-sm text-gray-300">
                  {zh ? '设备已完成口令上手，处于活跃状态。' : 'Device onboarding complete. Device is active.'}
                </p>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Error */}
          {error && (
            <div className="mt-3 flex items-start gap-2 bg-red-900/30 border border-red-700/50 rounded px-3 py-2">
              <AlertTriangle className="w-4 h-4 text-red-400 flex-shrink-0 mt-0.5" />
              <span className="text-xs text-red-300">{error}</span>
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div className="px-6 py-4 border-t border-gray-700/50 flex items-center justify-between">
          <div>
            {currentStatus !== 'pending_credentials' && currentStatus !== 'active' && (
              <button
                onClick={handleReset}
                disabled={loading}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs text-yellow-300 hover:bg-yellow-900/30 border border-yellow-700/40 transition-colors disabled:opacity-50"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                {zh ? '重置' : 'Reset'}
              </button>
            )}
          </div>
          <div className="flex gap-2">
            <button onClick={onClose} className="px-4 py-2 text-sm rounded bg-gray-700 text-gray-300 hover:bg-gray-600 transition-colors">
              {zh ? '关闭' : 'Close'}
            </button>
            {currentStatus === 'pending_credentials' && (
              <button onClick={handleSetCredentials} disabled={loading} className="flex items-center gap-2 px-4 py-2 text-sm rounded bg-cyan-600 text-white hover:bg-cyan-500 transition-colors disabled:opacity-50">
                {loading && <Loader2 className="w-4 h-4 animate-spin" />}
                {zh ? '保存凭据' : 'Save Credentials'}
              </button>
            )}
            {currentStatus === 'credentials_set' && (
              <button onClick={handleVerify} disabled={loading} className="flex items-center gap-2 px-4 py-2 text-sm rounded bg-cyan-600 text-white hover:bg-cyan-500 transition-colors disabled:opacity-50">
                {loading && <Loader2 className="w-4 h-4 animate-spin" />}
                {zh ? '验证连通' : 'Verify'}
              </button>
            )}
            {currentStatus === 'verified' && (
              <button onClick={handleActivate} disabled={loading} className="flex items-center gap-2 px-4 py-2 text-sm rounded bg-emerald-600 text-white hover:bg-emerald-500 transition-colors disabled:opacity-50">
                {loading && <Loader2 className="w-4 h-4 animate-spin" />}
                {zh ? '激活设备' : 'Activate'}
              </button>
            )}
          </div>
        </div>
      </motion.div>
    </div>
  );
}
