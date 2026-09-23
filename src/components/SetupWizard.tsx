import React, { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Shield, Globe, Bell, CheckCircle2, ChevronRight,
  Eye, EyeOff, Send, Loader2, SkipForward, ArrowRight,
  Rocket, Lock, Settings2,
} from 'lucide-react';

interface SetupWizardProps {
  language: string;
  onComplete: () => void;
  onLanguageChange: (lang: 'en' | 'zh') => void;
  showToast: (msg: string, type?: 'success' | 'error' | 'info') => void;
}

const STEPS = [
  { key: 'password', icon: Shield },
  { key: 'platform', icon: Settings2 },
  { key: 'notification', icon: Bell },
  { key: 'done', icon: Rocket },
] as const;

/* ── FeishuIcon inline SVG ── */
const FeishuIcon = () => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none">
    <path d="M5.59 7.41C7.34 5.12 10.14 3 12.5 3c.96 0 1.72.39 2.25 1.1a8.7 8.7 0 0 0-3.82 2.32C9.36 8.02 7.82 10 6.73 12.6l-1.14-5.2Z" fill="#00D6B9"/>
    <path d="M6.73 12.6c-.55 1.32-.89 2.78-.96 4.4h5.6a14.5 14.5 0 0 1 3.56-10.58C12.4 6.6 9.23 8.67 6.73 12.6Z" fill="#3370FF"/>
    <path d="M5.77 17c.03 1.66.5 3.16 1.55 4h8.34c1.62-1.36 2.68-3.67 2.74-6.63a12 12 0 0 0-3.47 2.63H5.77Z" fill="#133C9A"/>
  </svg>
);

const DingtalkIcon = () => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none">
    <rect width="24" height="24" rx="4" fill="#0089FF"/>
    <path d="M16.6 10.5c-.3.4-1 .8-1.5 1l.3 1.2-2.6-1.5c-.5.1-1.1.2-1.8.2-2.8 0-5-1.5-5-3.4s2.2-3.4 5-3.4 5 1.5 5 3.4c0 .9-.5 1.7-1.4 2.3l2 .2Z" fill="white"/>
  </svg>
);

const WechatIcon = () => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none">
    <rect width="24" height="24" rx="4" fill="#07C160"/>
    <path d="M9.5 6C6.46 6 4 7.9 4 10.25c0 1.35.75 2.55 1.93 3.37l-.5 1.5 1.75-1c.7.23 1.46.38 2.25.38.1 0 .2 0 .3-.01A4.2 4.2 0 0 1 9.5 13c0-2.5 2.35-4.5 5.25-4.5.18 0 .36.01.53.03C14.43 6.98 12.17 6 9.5 6Z" fill="white"/>
    <ellipse cx="14.75" cy="13" rx="4.25" ry="3.5" fill="white" fillOpacity=".85"/>
  </svg>
);

const SetupWizard: React.FC<SetupWizardProps> = ({ language, onComplete, onLanguageChange, showToast }) => {
  const zh = language === 'zh';
  const [step, setStep] = useState(0);

  // Step 1: Password
  const [currentPwd, setCurrentPwd] = useState('');
  const [newPwd, setNewPwd] = useState('');
  const [confirmPwd, setConfirmPwd] = useState('');
  const [showPwd, setShowPwd] = useState(false);
  const [pwdLoading, setPwdLoading] = useState(false);
  const [pwdDone, setPwdDone] = useState(false);

  // Step 2: Platform
  const [sysName, setSysName] = useState('Nexora');
  const [timezone, setTimezone] = useState('Asia/Shanghai');
  const [prefLang, setPrefLang] = useState(language);

  // Step 3: Notification (optional)
  const [feishuUrl, setFeishuUrl] = useState('');
  const [dingtalkUrl, setDingtalkUrl] = useState('');
  const [dingtalkSecret, setDingtalkSecret] = useState('');
  const [wechatUrl, setWechatUrl] = useState('');
  const [testingPlatform, setTestingPlatform] = useState('');

  const token = localStorage.getItem('netops_token') || '';
  const authHeaders = { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' };

  // ── Step 1: Change password ──
  const pwdStrength = (() => {
    if (!newPwd) return { score: 0, label: '', missing: [] };
    let s = 0;
    const missing = [];
    if (newPwd.length >= 10) s++; else missing.push(zh ? '至少10个字符' : '10+ chars');
    if (/[A-Z]/.test(newPwd)) s++; else missing.push(zh ? '大写字母' : 'uppercase');
    if (/[a-z]/.test(newPwd)) s++; else missing.push(zh ? '小写字母' : 'lowercase');
    if (/[0-9]/.test(newPwd)) s++; else missing.push(zh ? '数字' : 'digit');
    if (/[^A-Za-z0-9]/.test(newPwd)) s++; else missing.push(zh ? '特殊字符' : 'special char');
    const labels = zh
      ? ['', '弱', '弱', '中等', '强', '非常强']
      : ['', 'Weak', 'Weak', 'Medium', 'Strong', 'Very Strong'];
    return { score: s, label: labels[s], missing };
  })();

  const handleChangePassword = async () => {
    if (!currentPwd || !newPwd) {
      showToast(zh ? '请填写当前密码和新密码' : 'Fill in both passwords', 'error');
      return;
    }
    if (newPwd !== confirmPwd) {
      showToast(zh ? '两次输入的密码不一致' : 'Passwords do not match', 'error');
      return;
    }
    if (pwdStrength.score < 5) {
      const missingText = pwdStrength.missing.join(', ');
      showToast(zh ? `密码强度不足：缺少 ${missingText}` : `Password too weak: missing ${missingText}`, 'error');
      return;
    }
    setPwdLoading(true);
    try {
      const r = await fetch('/api/setup/change-password', {
        method: 'POST', headers: authHeaders,
        body: JSON.stringify({ current_password: currentPwd, new_password: newPwd }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || 'Failed');
      setPwdDone(true);
      showToast(zh ? '密码已更新' : 'Password updated', 'success');
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Unknown error';
      showToast(msg, 'error');
    } finally {
      setPwdLoading(false);
    }
  };

  // ── Step 2: Platform settings ──
  const handleSavePlatform = async () => {
    try {
      const r = await fetch('/api/setup/platform', {
        method: 'POST', headers: authHeaders,
        body: JSON.stringify({ system_name: sysName, timezone, preferred_language: prefLang }),
      });
      if (!r.ok) throw new Error('Failed');
      // Apply language change to the entire UI immediately
      if (prefLang === 'en' || prefLang === 'zh') {
        onLanguageChange(prefLang as 'en' | 'zh');
      }
      showToast(prefLang === 'zh' ? '平台设置已保存' : 'Platform settings saved', 'success');
      setStep(2);
    } catch {
      showToast(zh ? '保存失败' : 'Save failed', 'error');
    }
  };

  // ── Step 3: Test notification ──
  const handleTestNotification = async (platform: string, url: string, secret?: string) => {
    if (!url.trim()) {
      showToast(zh ? '请输入 Webhook URL' : 'Enter Webhook URL', 'error');
      return;
    }
    setTestingPlatform(platform);
    try {
      const r = await fetch('/api/setup/notification-test', {
        method: 'POST', headers: authHeaders,
        body: JSON.stringify({ platform, webhook_url: url.trim(), secret: secret || '' }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || 'Failed');
      showToast(zh ? '测试消息已发送，请检查接收端' : 'Test sent, check your channel', 'success');
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Send failed';
      showToast(msg, 'error');
    } finally {
      setTestingPlatform('');
    }
  };

  // ── Finish ──
  const handleFinish = async () => {
    try {
      await fetch('/api/setup/complete', { method: 'POST', headers: authHeaders });
    } catch { /* ignore */ }
    onComplete();
  };

  const stepTitles = zh
    ? ['修改默认密码', '平台基础设置', '告警通知渠道', '初始化完成']
    : ['Change Default Password', 'Platform Settings', 'Alert Notifications', 'Setup Complete'];

  const stepDescs = zh
    ? [
        '默认管理员密码 admin 不安全，请立即修改。',
        '配置平台名称、时区和默认语言。',
        '配置飞书、钉钉或企业微信 Webhook（可选，可稍后再配置）。',
        `一切就绪，开始使用 ${sysName || 'Nexora'}！`,
      ]
    : [
        'The default admin password is insecure. Please change it now.',
        'Configure platform name, timezone, and default language.',
        'Set up Feishu, DingTalk, or WeChat webhooks (optional, can configure later).',
        `Everything is ready. Start using ${sysName || 'Nexora'}!`,
      ];

  const canProceedStep0 = pwdDone;

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center bg-gradient-to-br from-[#0c1e30] via-[#0a2a40] to-[#071a2b]">
      {/* Decorative background */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -left-32 -top-32 h-[500px] w-[500px] rounded-full bg-[#06b6d4]/[0.06] blur-[120px]" />
        <div className="absolute -bottom-40 -right-40 h-[600px] w-[600px] rounded-full bg-[#0891b2]/[0.05] blur-[150px]" />
        <div className="absolute left-1/2 top-1/4 h-px w-[400px] -translate-x-1/2 bg-gradient-to-r from-transparent via-[#06b6d4]/20 to-transparent" />
      </div>

      <motion.div
        className="relative mx-4 flex w-full max-w-[680px] flex-col overflow-hidden rounded-3xl bg-white shadow-2xl shadow-black/40"
        initial={{ y: 40, opacity: 0, scale: 0.96 }}
        animate={{ y: 0, opacity: 1, scale: 1 }}
        transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
      >
        {/* Top progress strip */}
        <div className="flex h-1 w-full bg-black/5">
          {STEPS.map((_, i) => (
            <div
              key={i}
              className={`flex-1 transition-all duration-500 ${
                i <= step ? 'bg-[#06b6d4]' : 'bg-transparent'
              }`}
            />
          ))}
        </div>

        {/* Step indicator circles */}
        <div className="flex items-center justify-center gap-6 px-6 pt-6 pb-2">
          {STEPS.map((s, i) => {
            const Icon = s.icon;
            const active = i === step;
            const done = i < step;
            return (
              <div key={s.key} className="flex items-center gap-3">
                <div
                  className={`flex h-9 w-9 items-center justify-center rounded-full transition-all duration-300 ${
                    active
                      ? 'bg-[#06b6d4] text-white shadow-lg shadow-[#06b6d4]/30'
                      : done
                        ? 'bg-[#06b6d4]/15 text-[#06b6d4]'
                        : 'bg-black/5 text-black/25'
                  }`}
                >
                  {done ? <CheckCircle2 size={16} /> : <Icon size={16} />}
                </div>
                {i < STEPS.length - 1 && (
                  <div className={`hidden h-px w-8 sm:block ${i < step ? 'bg-[#06b6d4]/40' : 'bg-black/8'}`} />
                )}
              </div>
            );
          })}
        </div>

        {/* Title */}
        <div className="px-8 pt-3 pb-1 text-center">
          <h2 className="text-xl font-bold text-[#164e63]">{stepTitles[step]}</h2>
          <p className="mt-1.5 text-sm text-black/45">{stepDescs[step]}</p>
        </div>

        {/* Step content */}
        <div className="px-8 pb-6 pt-4" style={{ minHeight: 280 }}>
          <AnimatePresence mode="wait">
            <motion.div
              key={step}
              initial={{ x: 30, opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              exit={{ x: -30, opacity: 0 }}
              transition={{ duration: 0.22 }}
            >
              {/* ── Step 0: Password ── */}
              {step === 0 && (
                <div className="space-y-4">
                  {pwdDone ? (
                    <div className="flex flex-col items-center gap-3 py-6">
                      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-emerald-50 text-emerald-500">
                        <CheckCircle2 size={28} />
                      </div>
                      <p className="text-sm font-semibold text-emerald-600">
                        {zh ? '密码已成功修改' : 'Password changed successfully'}
                      </p>
                    </div>
                  ) : (
                    <>
                      <div>
                        <label className="mb-1 block text-xs font-semibold text-black/50">
                          {zh ? '当前密码' : 'Current Password'}
                        </label>
                        <div className="relative">
                          <Lock size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-black/25" />
                          <input
                            type={showPwd ? 'text' : 'password'}
                            value={currentPwd}
                            onChange={e => setCurrentPwd(e.target.value)}
                            placeholder={zh ? '输入当前密码（默认 admin）' : 'Enter current password (default: admin)'}
                            className="w-full rounded-xl border border-black/10 bg-white py-3 pl-9 pr-10 text-sm outline-none focus:border-[#06b6d4]/40 focus:ring-2 focus:ring-[#06b6d4]/10"
                          />
                          <button type="button" tabIndex={-1} onClick={() => setShowPwd(v => !v)} className="absolute right-3 top-1/2 -translate-y-1/2 text-black/30 hover:text-black/60">
                            {showPwd ? <EyeOff size={15} /> : <Eye size={15} />}
                          </button>
                        </div>
                      </div>
                      <div>
                        <label className="mb-1 block text-xs font-semibold text-black/50">
                          {zh ? '新密码' : 'New Password'}
                        </label>
                        <input
                          type={showPwd ? 'text' : 'password'}
                          value={newPwd}
                          onChange={e => setNewPwd(e.target.value)}
                          placeholder={zh ? '至少10位，含大小写、数字和特殊字符' : '10+ chars, upper, lower, digit, special'}
                          className="w-full rounded-xl border border-black/10 bg-white py-3 px-3 text-sm outline-none focus:border-[#06b6d4]/40 focus:ring-2 focus:ring-[#06b6d4]/10"
                        />
                        {newPwd && (
                          <div className="mt-1.5 space-y-1">
                            <div className="flex items-center gap-2">
                              <div className="flex h-1 flex-1 gap-0.5 rounded-full overflow-hidden bg-black/5">
                                {[1, 2, 3, 4, 5].map(i => (
                                  <div
                                    key={i}
                                    className={`flex-1 transition-all duration-300 ${
                                      i <= pwdStrength.score
                                        ? pwdStrength.score <= 2 ? 'bg-red-400' : pwdStrength.score <= 3 ? 'bg-amber-400' : 'bg-emerald-400'
                                        : ''
                                    }`}
                                  />
                                ))}
                              </div>
                              <span className={`text-[10px] font-bold ${
                                pwdStrength.score <= 2 ? 'text-red-400' : pwdStrength.score <= 3 ? 'text-amber-500' : 'text-emerald-500'
                              }`}>
                                {pwdStrength.label}
                              </span>
                            </div>
                            {pwdStrength.missing.length > 0 && (
                              <p className="text-xs text-red-400">
                                {zh ? `缺少: ${pwdStrength.missing.join(', ')}` : `Missing: ${pwdStrength.missing.join(', ')}`}
                              </p>
                            )}
                          </div>
                        )}
                      </div>
                      <div>
                        <label className="mb-1 block text-xs font-semibold text-black/50">
                          {zh ? '确认新密码' : 'Confirm New Password'}
                        </label>
                        <input
                          type={showPwd ? 'text' : 'password'}
                          value={confirmPwd}
                          onChange={e => setConfirmPwd(e.target.value)}
                          placeholder={zh ? '再次输入新密码' : 'Re-enter new password'}
                          className="w-full rounded-xl border border-black/10 bg-white py-3 px-3 text-sm outline-none focus:border-[#06b6d4]/40 focus:ring-2 focus:ring-[#06b6d4]/10"
                        />
                        {confirmPwd && confirmPwd !== newPwd && (
                          <p className="mt-1 text-xs text-red-400">{zh ? '密码不一致' : 'Passwords do not match'}</p>
                        )}
                      </div>
                      <button
                        onClick={() => void handleChangePassword()}
                        disabled={pwdLoading || !currentPwd || !newPwd || newPwd !== confirmPwd}
                        className="mt-1 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[#06b6d4] py-3 text-sm font-semibold text-white shadow-lg shadow-[#06b6d4]/20 transition-all hover:-translate-y-0.5 hover:bg-[#0891b2] disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:translate-y-0"
                      >
                        {pwdLoading ? <Loader2 size={15} className="animate-spin" /> : <Shield size={15} />}
                        {zh ? '修改密码' : 'Change Password'}
                      </button>
                    </>
                  )}
                </div>
              )}

              {/* ── Step 1: Platform Settings ── */}
              {step === 1 && (
                <div className="space-y-4">
                  <div>
                    <label className="mb-1 block text-xs font-semibold text-black/50">
                      {zh ? '系统名称' : 'System Name'}
                    </label>
                    <input
                      value={sysName}
                      onChange={e => setSysName(e.target.value)}
                      className="w-full rounded-xl border border-black/10 bg-white py-3 px-3 text-sm outline-none focus:border-[#06b6d4]/40 focus:ring-2 focus:ring-[#06b6d4]/10"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-semibold text-black/50">
                      {zh ? '时区' : 'Timezone'}
                    </label>
                    <select
                      value={timezone}
                      onChange={e => setTimezone(e.target.value)}
                      className="w-full rounded-xl border border-black/10 bg-white py-3 px-3 text-sm outline-none focus:border-[#06b6d4]/40"
                    >
                      <option value="Asia/Shanghai">Asia/Shanghai (UTC+8)</option>
                      <option value="Asia/Tokyo">Asia/Tokyo (UTC+9)</option>
                      <option value="Asia/Singapore">Asia/Singapore (UTC+8)</option>
                      <option value="America/New_York">America/New_York (UTC-5)</option>
                      <option value="America/Los_Angeles">America/Los_Angeles (UTC-8)</option>
                      <option value="Europe/London">Europe/London (UTC+0)</option>
                      <option value="UTC">UTC</option>
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-semibold text-black/50">
                      {zh ? '默认语言' : 'Default Language'}
                    </label>
                    <div className="flex gap-3">
                      {[
                        { val: 'zh', label: '中文' },
                        { val: 'en', label: 'English' },
                      ].map(opt => (
                        <button
                          key={opt.val}
                          onClick={() => setPrefLang(opt.val)}
                          className={`flex-1 rounded-xl border py-3 text-sm font-semibold transition-all ${
                            prefLang === opt.val
                              ? 'border-[#06b6d4] bg-[#06b6d4]/5 text-[#06b6d4]'
                              : 'border-black/10 text-black/50 hover:border-black/20'
                          }`}
                        >
                          {opt.label}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {/* ── Step 2: Notification (optional) ── */}
              {step === 2 && (
                <div className="space-y-4">
                  <div className="rounded-xl bg-amber-50 px-4 py-2.5 text-xs text-amber-700">
                    {zh ? '此步骤为可选项，可以跳过稍后在「个人设置」中配置。' : 'This step is optional. You can skip and configure later in Profile Settings.'}
                  </div>

                  {/* Feishu */}
                  <div className="rounded-xl border border-black/5 bg-black/[0.01] p-4">
                    <div className="mb-2 flex items-center gap-2">
                      <FeishuIcon />
                      <span className="text-sm font-semibold text-[#164e63]">{zh ? '飞书' : 'Feishu (Lark)'}</span>
                    </div>
                    <div className="flex gap-2">
                      <input
                        value={feishuUrl}
                        onChange={e => setFeishuUrl(e.target.value)}
                        placeholder="Webhook URL"
                        className="flex-1 rounded-lg border border-black/10 bg-white py-2 px-3 text-xs outline-none focus:border-[#06b6d4]/40"
                      />
                      <button
                        onClick={() => void handleTestNotification('feishu', feishuUrl)}
                        disabled={!feishuUrl.trim() || testingPlatform === 'feishu'}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-[#06b6d4]/10 px-3 py-2 text-xs font-semibold text-[#0891b2] hover:bg-[#06b6d4]/15 disabled:opacity-40"
                      >
                        {testingPlatform === 'feishu' ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
                        {zh ? '测试' : 'Test'}
                      </button>
                    </div>
                  </div>

                  {/* DingTalk */}
                  <div className="rounded-xl border border-black/5 bg-black/[0.01] p-4">
                    <div className="mb-2 flex items-center gap-2">
                      <DingtalkIcon />
                      <span className="text-sm font-semibold text-[#164e63]">{zh ? '钉钉' : 'DingTalk'}</span>
                    </div>
                    <div className="flex gap-2 mb-2">
                      <input
                        value={dingtalkUrl}
                        onChange={e => setDingtalkUrl(e.target.value)}
                        placeholder="Webhook URL"
                        className="flex-1 rounded-lg border border-black/10 bg-white py-2 px-3 text-xs outline-none focus:border-[#06b6d4]/40"
                      />
                      <button
                        onClick={() => void handleTestNotification('dingtalk', dingtalkUrl, dingtalkSecret)}
                        disabled={!dingtalkUrl.trim() || testingPlatform === 'dingtalk'}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-[#06b6d4]/10 px-3 py-2 text-xs font-semibold text-[#0891b2] hover:bg-[#06b6d4]/15 disabled:opacity-40"
                      >
                        {testingPlatform === 'dingtalk' ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
                        {zh ? '测试' : 'Test'}
                      </button>
                    </div>
                    <input
                      value={dingtalkSecret}
                      onChange={e => setDingtalkSecret(e.target.value)}
                      placeholder={zh ? '签名密钥 Secret（可选）' : 'Signing Secret (optional)'}
                      className="w-full rounded-lg border border-black/10 bg-white py-2 px-3 text-xs outline-none focus:border-[#06b6d4]/40"
                    />
                  </div>

                  {/* WeChat */}
                  <div className="rounded-xl border border-black/5 bg-black/[0.01] p-4">
                    <div className="mb-2 flex items-center gap-2">
                      <WechatIcon />
                      <span className="text-sm font-semibold text-[#164e63]">{zh ? '企业微信' : 'WeChat Work'}</span>
                    </div>
                    <div className="flex gap-2">
                      <input
                        value={wechatUrl}
                        onChange={e => setWechatUrl(e.target.value)}
                        placeholder="Webhook URL"
                        className="flex-1 rounded-lg border border-black/10 bg-white py-2 px-3 text-xs outline-none focus:border-[#06b6d4]/40"
                      />
                      <button
                        onClick={() => void handleTestNotification('wechat', wechatUrl)}
                        disabled={!wechatUrl.trim() || testingPlatform === 'wechat'}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-[#06b6d4]/10 px-3 py-2 text-xs font-semibold text-[#0891b2] hover:bg-[#06b6d4]/15 disabled:opacity-40"
                      >
                        {testingPlatform === 'wechat' ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
                        {zh ? '测试' : 'Test'}
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* ── Step 3: Done ── */}
              {step === 3 && (
                <div className="flex flex-col items-center gap-5 py-6">
                  <motion.div
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    transition={{ type: 'spring', stiffness: 200, damping: 15, delay: 0.1 }}
                    className="flex h-20 w-20 items-center justify-center rounded-full bg-gradient-to-br from-[#06b6d4] to-[#0891b2] text-white shadow-xl shadow-[#06b6d4]/30"
                  >
                    <Rocket size={36} />
                  </motion.div>
                  <div className="text-center">
                    <h3 className="text-lg font-bold text-[#164e63]">
                      {zh ? '🎉 初始化已完成！' : '🎉 Setup Complete!'}
                    </h3>
                    <p className="mt-2 text-sm text-black/45 leading-relaxed max-w-md">
                      {zh
                        ? '您可以在「平台管理」中继续添加设备、创建用户和配置其他功能。'
                        : 'You can continue adding devices, creating users, and configuring features in Platform Management.'}
                    </p>
                  </div>
                  <button
                    onClick={() => void handleFinish()}
                    className="mt-2 inline-flex items-center gap-2 rounded-2xl bg-gradient-to-r from-[#06b6d4] to-[#0891b2] px-8 py-3.5 text-sm font-bold text-white shadow-xl shadow-[#06b6d4]/25 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-2xl hover:shadow-[#06b6d4]/35"
                  >
                    {zh ? `进入 ${sysName || 'Nexora'}` : `Enter ${sysName || 'Nexora'}`}
                    <ArrowRight size={16} />
                  </button>
                </div>
              )}
            </motion.div>
          </AnimatePresence>
        </div>

        {/* Footer navigation (not on last step) */}
        {step < 3 && (
          <div className="flex items-center justify-between border-t border-black/5 px-8 py-4">
            <div>
              {step === 0 && !pwdDone && (
                <span className="text-[10px] font-semibold text-black/30 uppercase tracking-wider">
                  {zh ? '步骤 1 / 3' : 'Step 1 / 3'}
                </span>
              )}
            </div>
            <div className="flex items-center gap-3">
              {/* Skip button for optional steps (notification = step 2) */}
              {step === 2 && (
                <button
                  onClick={() => setStep(3)}
                  className="inline-flex items-center gap-1.5 rounded-xl px-4 py-2.5 text-xs font-semibold text-black/40 hover:bg-black/5 hover:text-black/60 transition-all"
                >
                  <SkipForward size={13} />
                  {zh ? '跳过此步骤' : 'Skip'}
                </button>
              )}
              {/* Next button */}
              {step === 0 && (
                <button
                  onClick={() => setStep(1)}
                  disabled={!canProceedStep0}
                  className="inline-flex items-center gap-1.5 rounded-xl bg-[#06b6d4] px-5 py-2.5 text-xs font-semibold text-white shadow-md shadow-[#06b6d4]/15 transition-all hover:-translate-y-0.5 hover:bg-[#0891b2] disabled:cursor-not-allowed disabled:opacity-35 disabled:hover:translate-y-0"
                >
                  {zh ? '下一步' : 'Next'}
                  <ChevronRight size={14} />
                </button>
              )}
              {step === 1 && (
                <button
                  onClick={() => void handleSavePlatform()}
                  className="inline-flex items-center gap-1.5 rounded-xl bg-[#06b6d4] px-5 py-2.5 text-xs font-semibold text-white shadow-md shadow-[#06b6d4]/15 transition-all hover:-translate-y-0.5 hover:bg-[#0891b2]"
                >
                  {zh ? '保存并继续' : 'Save & Continue'}
                  <ChevronRight size={14} />
                </button>
              )}
              {step === 2 && (
                <button
                  onClick={() => setStep(3)}
                  className="inline-flex items-center gap-1.5 rounded-xl bg-[#06b6d4] px-5 py-2.5 text-xs font-semibold text-white shadow-md shadow-[#06b6d4]/15 transition-all hover:-translate-y-0.5 hover:bg-[#0891b2]"
                >
                  {zh ? '完成配置' : 'Finish'}
                  <ChevronRight size={14} />
                </button>
              )}
            </div>
          </div>
        )}
      </motion.div>
    </div>
  );
};

export default SetupWizard;
