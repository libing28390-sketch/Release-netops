import React from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Bell, Eye, EyeOff, Terminal, MonitorSpeaker, Shield, Download, Lock,
  Info, UserRound, KeyRound, X, CheckCircle2, AlertCircle, Phone, Mail,
  Clock, ExternalLink, Sparkles, Check, ChevronRight
} from 'lucide-react';
import { useSystem } from '../hooks/useSystem';
import QRCode from 'react-qr-code';
import { ActionLink } from './ui/ActionIconButton';
import { detectTerminalPlatform, getLocalTerminalConfig, TERMINAL_APP_LABELS, type TerminalApp } from '../utils/localTerminal';

interface AvatarPreset {
  id: string;
  emoji: string;
  label: string;
  bgClass: string;
}

export interface ProfileFormState {
  username: string;
  oldPassword?: string;
  password: string;
  confirmPassword: string;
  fixedPin: string;
  displayName: string;
  phone: string;
  email: string;
}

interface NotificationChannelsState {
  feishu: { webhook_url: string; enabled: boolean; creator_username?: string };
  dingtalk: { webhook_url: string; enabled: boolean; secret: string; creator_username?: string };
  wechat: { webhook_url: string; enabled: boolean; creator_username?: string };
}

interface ProfileModalProps {
  open: boolean;
  language: string;
  resolvedTheme: 'light' | 'dark';
  currentRole: string;
  currentUserLastLogin: string;
  profileAvatarPreview: string;
  avatarPresets: readonly AvatarPreset[];
  profileForm: ProfileFormState;
  showProfilePwd: boolean;
  notificationChannels: NotificationChannelsState;
  notifyTestLoading: string;
  renderAvatarContent: (avatarValue: string, fallbackIconSize: number) => React.ReactNode;
  onClose: () => void;
  onSave: () => void;
  onAvatarFileChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
  onClearAvatar: () => void;
  onSelectAvatarPreset: (presetId: string) => void;
  onProfileFormChange: (updater: (prev: ProfileFormState) => ProfileFormState) => void;
  onToggleProfilePassword: () => void;
  onNotificationChannelToggle: (channel: keyof NotificationChannelsState) => void;
  onNotificationWebhookChange: (channel: keyof NotificationChannelsState, value: string) => void;
  onNotificationSecretChange: (value: string) => void;
  onTestNotificationChannel: (channel: keyof NotificationChannelsState) => void;
  mfaEnabled: boolean;
  onMfaStatusChange: (enabled: boolean) => void;
}

const ProfileModal: React.FC<ProfileModalProps> = ({
  open,
  language,
  resolvedTheme,
  currentRole,
  currentUserLastLogin,
  profileAvatarPreview,
  avatarPresets,
  profileForm,
  showProfilePwd,
  notificationChannels,
  notifyTestLoading,
  renderAvatarContent,
  onClose,
  onSave,
  onAvatarFileChange,
  onClearAvatar,
  onSelectAvatarPreset,
  onProfileFormChange,
  onToggleProfilePassword,
  onNotificationChannelToggle,
  onNotificationWebhookChange,
  onNotificationSecretChange,
  onTestNotificationChannel,
  mfaEnabled,
  onMfaStatusChange,
}) => {
  const { systemInfo } = useSystem();
  const isZh = language === 'zh';
  const isDark = resolvedTheme === 'dark';

  // Active Tab Index: 0: Profile, 1: Security, 2: Notifications, 3: Terminal Tools
  const [activeTab, setActiveTab] = React.useState(0);

  // MFA states
  const [mfaActive, setMfaActive] = React.useState(mfaEnabled);
  const [setupMode, setSetupMode] = React.useState(false);
  const [mfaSecret, setMfaSecret] = React.useState('');
  const [mfaQrUri, setMfaQrUri] = React.useState('');
  const [mfaCodeInput, setMfaCodeInput] = React.useState('');
  const [disablePasswordInput, setDisablePasswordInput] = React.useState('');
  const [showDisablePassword, setShowDisablePassword] = React.useState(false);
  const [showDingtalkSecret, setShowDingtalkSecret] = React.useState(false);
  const [disableMode, setDisableMode] = React.useState(false);
  const [mfaErrorMsg, setMfaErrorMsg] = React.useState('');
  const [mfaLoading, setMfaLoading] = React.useState(false);
  const [secretCopied, setSecretCopied] = React.useState(false);

  // Terminal tool local state
  const terminalPlatform = React.useMemo(() => detectTerminalPlatform(), []);
  const initialTerminalConfig = React.useMemo(() => getLocalTerminalConfig(terminalPlatform), [terminalPlatform]);
  const [localTerminalPath, setLocalTerminalPath] = React.useState(() => initialTerminalConfig.path);
  const [terminalApp, setTerminalApp] = React.useState<TerminalApp>(() => initialTerminalConfig.app);
  const [showFixedPin, setShowFixedPin] = React.useState(false);
  const [showPathSuggestions, setShowPathSuggestions] = React.useState(false);

  React.useEffect(() => {
    setMfaActive(mfaEnabled);
  }, [mfaEnabled]);

  React.useEffect(() => {
    if (open) {
      setActiveTab(0);
      setShowPathSuggestions(false);
      setSetupMode(false);
      setMfaCodeInput('');
      setMfaErrorMsg('');
      setDisableMode(false);
      setDisablePasswordInput('');
    }
  }, [open]);

  const handleStartSetup = async () => {
    setMfaErrorMsg('');
    setMfaLoading(true);
    try {
      const token = localStorage.getItem('netops_token');
      const res = await fetch('/api/mfa/setup', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      const data = await res.json();
      if (res.ok && data.success) {
        setMfaSecret(data.secret);
        setMfaQrUri(data.qr_code_uri);
        setSetupMode(true);
      } else {
        setMfaErrorMsg(data.detail || (isZh ? '初始化 MFA 失败' : 'Failed to initialize MFA'));
      }
    } catch (err: any) {
      setMfaErrorMsg(isZh ? '网络连接错误，请稍后重试' : 'Network connection error');
    } finally {
      setMfaLoading(false);
    }
  };

  const handleEnableMfa = async () => {
    if (mfaCodeInput.length < 6) return;
    setMfaErrorMsg('');
    setMfaLoading(true);
    try {
      const token = localStorage.getItem('netops_token');
      const res = await fetch('/api/mfa/enable', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ code: mfaCodeInput, secret: mfaSecret })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        setMfaActive(true);
        setSetupMode(false);
        setMfaCodeInput('');
        onMfaStatusChange(true);
        alert(isZh ? '双因子二次认证开启成功！' : 'MFA enabled successfully!');
      } else {
        setMfaErrorMsg(data.detail || (isZh ? '验证码错误或校验失败' : 'Invalid code or verification failed'));
      }
    } catch (err) {
      setMfaErrorMsg(isZh ? '网络错误，启用失败' : 'Network error, failed to enable');
    } finally {
      setMfaLoading(false);
    }
  };

  const handleDisableMfa = async () => {
    if (!disablePasswordInput) {
      setMfaErrorMsg(isZh ? '请输入密码以确认关闭' : 'Enter password to confirm');
      return;
    }
    setMfaErrorMsg('');
    setMfaLoading(true);
    try {
      const token = localStorage.getItem('netops_token');
      const res = await fetch('/api/mfa/disable', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ password: disablePasswordInput })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        setMfaActive(false);
        setDisableMode(false);
        setDisablePasswordInput('');
        onMfaStatusChange(false);
        alert(isZh ? '双因子二次认证已成功关闭！' : 'MFA disabled successfully!');
      } else {
        setMfaErrorMsg(data.detail || (isZh ? '密码不正确' : 'Incorrect password'));
      }
    } catch (err) {
      setMfaErrorMsg(isZh ? '网络错误，关闭失败' : 'Network error, failed to disable');
    } finally {
      setMfaLoading(false);
    }
  };

  const handleCopySecret = () => {
    if (!mfaSecret) return;
    navigator.clipboard.writeText(mfaSecret);
    setSecretCopied(true);
    setTimeout(() => setSecretCopied(false), 2000);
  };

  const passwordConfirmationError = profileForm.confirmPassword
    ? !profileForm.password
      ? (isZh ? '请先输入新密码' : 'Enter the new password first')
      : profileForm.password !== profileForm.confirmPassword
        ? (isZh ? '两次输入的密码不一致' : 'Passwords do not match')
        : ''
    : '';

  const PATH_PRESETS: Record<string, string[]> = {
    xshell: [
      'C:\\Program Files (x86)\\NetSarang\\Xshell 6\\Xshell.exe',
      'C:\\Program Files (x86)\\NetSarang\\Xshell 7\\Xshell.exe',
      'C:\\Program Files (x86)\\NetSarang\\Xshell 8\\Xshell.exe',
      'C:\\Program Files\\NetSarang\\Xshell 8\\Xshell.exe',
    ],
    putty: [
      'C:\\Program Files\\PuTTY\\putty.exe',
      'C:\\Program Files (x86)\\PuTTY\\putty.exe',
      'C:\\Windows\\System32\\putty.exe',
    ],
    securecrt: [
      'C:\\Program Files\\VanDyke Software\\SecureCRT\\SecureCRT.exe',
      'C:\\Program Files (x86)\\VanDyke Software\\SecureCRT\\SecureCRT.exe',
    ],
    mobaxterm: [
      'C:\\Program Files (x86)\\Mobatek\\MobaXterm\\MobaXterm.exe',
      'C:\\Program Files\\Mobatek\\MobaXterm\\MobaXterm.exe',
    ],
  };

  const tabs = [
    { key: 'profile', label: isZh ? '基本资料' : 'Profile', icon: UserRound, desc: isZh ? '头像与个人信息' : 'Avatar & details' },
    { key: 'security', label: isZh ? '登录安全' : 'Login Security', icon: KeyRound, desc: isZh ? '密码与 MFA 认证' : 'Password & MFA' },
    { key: 'notifications', label: isZh ? '告警通知' : 'Notifications', icon: Bell, desc: isZh ? '机器人消息推送' : 'Bot Webhooks' },
    { key: 'terminal', label: isZh ? '终端工具' : 'Terminal Tools', icon: MonitorSpeaker, desc: isZh ? '工作站 Agent 配置' : 'Workstation agent' },
  ] as const;

  const channels = [
    {
      key: 'feishu',
      label: isZh ? '飞书群机器人' : 'Feishu Bot',
      sub: 'Feishu',
      icon: 'FS',
      iconBg: 'bg-[#1664FF]',
      badge: 'bg-blue-500/10 text-blue-500 border border-blue-500/20',
      hint: 'https://open.feishu.cn/open-apis/bot/v2/hook/…',
      hasSecret: false,
      docsUrl: 'https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot',
      docsLabel: isZh ? '配置教程 →' : 'Docs →',
      tip: isZh ? '在飞书群「设置」➜「群机器人」➜「添加机器人」➜「自定义机器人」，复制 Webhook URL 填入下方。' : 'Copy the custom bot Webhook URL from your Feishu group settings.',
    },
    {
      key: 'dingtalk',
      label: isZh ? '钉钉群机器人' : 'DingTalk Bot',
      sub: 'DingTalk',
      icon: 'DT',
      iconBg: 'bg-[#3296FA]',
      badge: 'bg-sky-500/10 text-sky-500 border border-sky-500/20',
      hint: 'https://oapi.dingtalk.com/robot/send?access_token=…',
      hasSecret: true,
      docsUrl: 'https://open.dingtalk.com/document/robots/custom-robot-access',
      docsLabel: isZh ? '配置教程 →' : 'Docs →',
      tip: isZh ? `在钉钉群「智能群助手」中添加自定义机器人。安全设置选加签时将密钥填入下方 Secret 栏；若选自定义关键词，填 ${systemInfo?.system_name || 'Nexora'} 即可。` : 'Add a custom robot in DingTalk group. Set sign secret or keywords.',
    },
    {
      key: 'wechat',
      label: isZh ? '企业微信群机器人' : 'WeCom Bot',
      sub: 'WeCom',
      icon: 'WC',
      iconBg: 'bg-[#07C160]',
      badge: 'bg-green-500/10 text-green-500 border border-green-500/20',
      hint: 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…',
      hasSecret: false,
      docsUrl: 'https://developer.work.weixin.qq.com/document/path/91770',
      docsLabel: isZh ? '配置教程 →' : 'Docs →',
      tip: isZh ? '在企业微信群中右键群名 ➜「添加群机器人」➜ 新建机器人，复制 Webhook URL 填入下方。' : 'Copy the Webhook URL from your WeChat Work group bot.',
    },
  ] as const;

  const roleLabel = isZh
    ? (currentRole === 'Administrator' ? '系统管理员' : currentRole === 'Operator' ? '运维操作员' : currentRole === 'Viewer' ? '只读用户' : currentRole)
    : currentRole;

  const terminalPlatformLabel = terminalPlatform === 'windows' ? 'Windows' : 'Ubuntu / Linux';

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/60 p-3 sm:p-4 backdrop-blur-md">
      <motion.div
        initial={{ opacity: 0, y: 16, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 16, scale: 0.98 }}
        transition={{ duration: 0.2, ease: 'easeOut' }}
        className={`w-full max-w-5xl overflow-hidden rounded-2xl sm:rounded-3xl border shadow-[0_24px_80px_rgba(0,0,0,0.35)] flex flex-col max-h-[92vh] sm:h-[680px] ${
          isDark ? 'bg-[#0f172a] border-white/10 text-white' : 'bg-white border-slate-200 text-slate-900'
        }`}
      >
        {/* Top Header */}
        <div className={`flex items-center justify-between px-6 py-4 border-b shrink-0 ${
          isDark ? 'border-white/10 bg-[#141e33]' : 'border-slate-100 bg-slate-50/80'
        }`}>
          <div className="flex items-center gap-3">
            <div className={`flex h-10 w-10 items-center justify-center rounded-xl shadow-sm ${
              isDark ? 'bg-cyan-500/15 text-cyan-300 ring-1 ring-cyan-400/20' : 'bg-cyan-50 text-cyan-700 ring-1 ring-cyan-200'
            }`}>
              <Shield size={20} />
            </div>
            <div>
              <h3 className="text-base sm:text-lg font-bold tracking-tight">
                {isZh ? '个人中心设置' : 'Account & Personal Settings'}
              </h3>
              <p className={`text-xs ${isDark ? 'text-white/45' : 'text-slate-400'}`}>
                {isZh ? '自定义您的个人资料、登录安全保护、告警通知与终端工具' : 'Manage your profile details, security credentials, and alert preferences'}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            title={isZh ? '关闭' : 'Close'}
            className={`p-2 rounded-xl transition-colors ${
              isDark ? 'text-white/40 hover:text-white hover:bg-white/10' : 'text-slate-400 hover:text-slate-700 hover:bg-slate-100'
            }`}
          >
            <X size={18} />
          </button>
        </div>

        {/* Master-Detail Dual Column Body */}
        <div className="flex-1 grid grid-cols-1 md:grid-cols-12 min-h-0 overflow-hidden">
          {/* Left Sidebar: User Card + Navigation Tabs */}
          <div className={`md:col-span-4 border-r flex flex-col p-4 sm:p-5 overflow-y-auto ${
            isDark ? 'border-white/10 bg-[#121c2d]/70' : 'border-slate-100 bg-slate-50/50'
          }`}>
            {/* Identity Card */}
            <div className={`p-4 rounded-2xl border mb-4 shadow-sm relative overflow-hidden ${
              isDark ? 'bg-gradient-to-br from-white/[0.06] to-white/[0.02] border-white/10' : 'bg-white border-slate-200/80'
            }`}>
              <div className="flex items-center gap-3.5">
                <div className="relative">
                  <div className={`w-13 h-13 rounded-2xl border overflow-hidden flex items-center justify-center shadow-inner shrink-0 ${
                    isDark ? 'bg-slate-800 border-white/15' : 'bg-slate-100 border-slate-200'
                  }`}>
                    {renderAvatarContent(profileAvatarPreview, 28)}
                  </div>
                  {mfaActive && (
                    <span className="absolute -bottom-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full bg-emerald-500 text-white ring-2 ring-slate-900 shadow-sm" title="MFA Protected">
                      <Check size={10} strokeWidth={3} />
                    </span>
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="font-bold text-sm truncate">
                      {profileForm.displayName || profileForm.username || 'User'}
                    </span>
                  </div>
                  <div className={`text-xs font-mono ${isDark ? 'text-white/45' : 'text-slate-400'}`}>
                    @{profileForm.username}
                  </div>
                  <div className="mt-1.5 flex items-center gap-1.5 flex-wrap">
                    <span className={`px-2 py-0.5 rounded-md text-[10px] font-bold tracking-wide ${
                      isDark ? 'bg-cyan-400/15 text-cyan-300 border border-cyan-400/20' : 'bg-cyan-50 text-cyan-700 border border-cyan-200'
                    }`}>
                      {roleLabel}
                    </span>
                    <span className={`px-1.5 py-0.5 rounded-md text-[9px] font-medium flex items-center gap-1 ${
                      mfaActive
                        ? (isDark ? 'bg-emerald-500/15 text-emerald-300' : 'bg-emerald-50 text-emerald-700')
                        : (isDark ? 'bg-white/5 text-white/40' : 'bg-slate-100 text-slate-400')
                    }`}>
                      <span className={`h-1.5 w-1.5 rounded-full ${mfaActive ? 'bg-emerald-500 animate-pulse' : 'bg-slate-400'}`} />
                      {mfaActive ? (isZh ? 'MFA 已启用' : 'MFA Active') : (isZh ? 'MFA 未开启' : 'MFA Disabled')}
                    </span>
                  </div>
                </div>
              </div>

              {currentUserLastLogin && currentUserLastLogin !== 'Never' && (
                <div className={`mt-3 pt-2.5 border-t flex items-center gap-1.5 text-[10px] ${
                  isDark ? 'border-white/5 text-white/35' : 'border-slate-100 text-slate-400'
                }`}>
                  <Clock size={11} className="shrink-0" />
                  <span className="truncate">{isZh ? '上次登录: ' : 'Last login: '}{currentUserLastLogin}</span>
                </div>
              )}
            </div>

            {/* Navigation Tabs */}
            <div className="space-y-1.5 flex-1">
              {tabs.map((tab, idx) => {
                const active = activeTab === idx;
                const Icon = tab.icon;
                return (
                  <button
                    key={tab.key}
                    type="button"
                    onClick={() => setActiveTab(idx)}
                    className={`w-full flex items-center gap-3 px-3.5 py-3 rounded-xl text-left transition-all duration-150 relative ${
                      active
                        ? (isDark
                            ? 'bg-cyan-500/15 text-cyan-200 font-bold shadow-sm ring-1 ring-cyan-400/30'
                            : 'bg-cyan-50/80 text-cyan-900 font-bold shadow-sm ring-1 ring-cyan-200')
                        : (isDark
                            ? 'text-white/60 hover:text-white hover:bg-white/[0.04]'
                            : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100/70')
                    }`}
                  >
                    <span className={`flex h-8 w-8 items-center justify-center rounded-lg transition-colors ${
                      active
                        ? (isDark ? 'bg-cyan-400 text-slate-950 shadow' : 'bg-cyan-600 text-white shadow')
                        : (isDark ? 'bg-white/5 text-white/50' : 'bg-slate-100 text-slate-400')
                    }`}>
                      <Icon size={16} />
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="text-xs leading-none">{tab.label}</div>
                      <div className={`text-[10px] mt-1 font-normal truncate ${
                        active ? (isDark ? 'text-cyan-300/70' : 'text-cyan-700/80') : (isDark ? 'text-white/35' : 'text-slate-400')
                      }`}>
                        {tab.desc}
                      </div>
                    </div>
                    {active && <ChevronRight size={14} className={isDark ? 'text-cyan-400' : 'text-cyan-600'} />}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Right Main Content Area */}
          <div className={`md:col-span-8 overflow-y-auto p-5 sm:p-7 ${
            isDark ? 'bg-[#0f172a]' : 'bg-slate-50/40'
          }`}>
            <AnimatePresence mode="wait">
              {/* Tab 0: 基本资料 (Profile) */}
              {activeTab === 0 && (
                <motion.div
                  key="tab-profile"
                  initial={{ opacity: 0, x: 8 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -8 }}
                  transition={{ duration: 0.15 }}
                  className="space-y-6"
                >
                  <div>
                    <h4 className="text-sm font-bold tracking-tight">{isZh ? '基本资料设置' : 'Profile Settings'}</h4>
                    <p className={`text-xs mt-0.5 ${isDark ? 'text-white/45' : 'text-slate-400'}`}>
                      {isZh ? '个性化您的展示头像、显示名称与通知联系方式' : 'Customize your avatar, display name, and contact details'}
                    </p>
                  </div>

                  {/* Avatar Picker Card */}
                  <div className={`p-4 sm:p-5 rounded-2xl border ${
                    isDark ? 'bg-white/[0.03] border-white/10' : 'bg-white border-slate-200/80 shadow-sm'
                  }`}>
                    <label className={`block text-[11px] font-bold uppercase tracking-wider mb-3 ${
                      isDark ? 'text-white/60' : 'text-slate-500'
                    }`}>
                      {isZh ? '个性头像' : 'Avatar'}
                    </label>

                    <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4 mb-4">
                      <div className={`w-16 h-16 rounded-2xl border overflow-hidden flex items-center justify-center shrink-0 shadow-sm ${
                        isDark ? 'bg-slate-800 border-white/15' : 'bg-slate-100 border-slate-200'
                      }`}>
                        {renderAvatarContent(profileAvatarPreview, 32)}
                      </div>
                      <div className="space-y-2">
                        <div className="flex items-center gap-2">
                          <label className={`px-3 py-1.5 rounded-xl text-xs font-semibold cursor-pointer transition-all shadow-sm flex items-center gap-1.5 ${
                            isDark ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-400/30 hover:bg-cyan-500/30' : 'bg-cyan-50 text-cyan-800 border border-cyan-200 hover:bg-cyan-100'
                          }`}>
                            <Sparkles size={13} />
                            {isZh ? '上传自定义图片' : 'Upload custom image'}
                            <input type="file" accept="image/*" className="hidden" onChange={onAvatarFileChange} />
                          </label>
                          <button
                            type="button"
                            onClick={onClearAvatar}
                            className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition-all border ${
                              isDark ? 'bg-rose-500/10 text-rose-300 border-rose-500/20 hover:bg-rose-500/20' : 'bg-rose-50 text-rose-700 border-rose-200 hover:bg-rose-100'
                            }`}
                          >
                            {isZh ? '恢复默认' : 'Reset default'}
                          </button>
                        </div>
                        <p className={`text-[11px] ${isDark ? 'text-white/40' : 'text-slate-400'}`}>
                          {isZh ? '支持 PNG、JPG、WebP 格式，文件大小不超过 2MB。' : 'Supports PNG, JPG, WebP. Max size: 2MB.'}
                        </p>
                      </div>
                    </div>

                    {/* Presets 6x2 Symmetry Grid */}
                    <div className="pt-3 border-t" style={{ borderColor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)' }}>
                      <span className={`block text-[10px] font-bold uppercase tracking-wider mb-2.5 ${
                        isDark ? 'text-white/45' : 'text-slate-400'
                      }`}>
                        {isZh ? '或者从预设库中选择' : 'Or choose from presets'}
                      </span>
                      <div className="grid grid-cols-6 gap-2.5 sm:gap-3">
                        {avatarPresets.map((preset) => {
                          const active = profileAvatarPreview === preset.id;
                          return (
                            <button
                              key={preset.id}
                              type="button"
                              onClick={() => onSelectAvatarPreset(preset.id)}
                              className={`h-11 rounded-xl border flex items-center justify-center transition-all relative overflow-hidden group ${
                                active
                                  ? 'ring-2 ring-cyan-400 border-transparent scale-105 shadow-md shadow-cyan-500/20'
                                  : (isDark ? 'border-white/10 hover:border-white/30 hover:scale-105' : 'border-slate-200 hover:border-slate-400 hover:scale-105')
                              }`}
                              title={preset.label}
                            >
                              <div className={`w-full h-full ${preset.bgClass} flex items-center justify-center`}>
                                <span className="text-lg leading-none transition-transform group-hover:scale-115">{preset.emoji}</span>
                              </div>
                              {active && (
                                <span className="absolute top-1 right-1 h-2 w-2 rounded-full bg-cyan-400 ring-1 ring-white" />
                              )}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  </div>

                  {/* Account & Contact Details Card */}
                  <div className={`p-4 sm:p-5 rounded-2xl border space-y-4 ${
                    isDark ? 'bg-white/[0.03] border-white/10' : 'bg-white border-slate-200/80 shadow-sm'
                  }`}>
                    <label className={`block text-[11px] font-bold uppercase tracking-wider ${
                      isDark ? 'text-white/60' : 'text-slate-500'
                    }`}>
                      {isZh ? '账户与联系方式' : 'Account & Contact Details'}
                    </label>

                    {/* Username (Readonly/Protected) */}
                    <div>
                      <label className={`block text-[11px] font-medium mb-1.5 ${isDark ? 'text-white/50' : 'text-slate-600'}`}>
                        {isZh ? '登录用户名' : 'Username'}
                      </label>
                      <div className="relative">
                        <div className={`absolute left-3.5 top-1/2 -translate-y-1/2 ${isDark ? 'text-white/30' : 'text-slate-400'}`}>
                          <Lock size={14} />
                        </div>
                        <input
                          type="text"
                          value={profileForm.username}
                          disabled
                          title="Profile username"
                          className={`w-full rounded-xl pl-9 pr-4 py-2.5 text-xs font-mono font-medium border ${
                            isDark ? 'bg-white/[0.02] border-white/10 text-white/50 cursor-not-allowed' : 'bg-slate-100 border-slate-200 text-slate-500 cursor-not-allowed'
                          }`}
                        />
                      </div>
                    </div>

                    {/* Display Name / Phone / Email */}
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                      <div>
                        <label className={`block text-[11px] font-medium mb-1.5 ${isDark ? 'text-white/50' : 'text-slate-600'}`}>
                          {isZh ? '真实姓名 / 昵称' : 'Display Name'}
                        </label>
                        <div className="relative">
                          <div className={`absolute left-3.5 top-1/2 -translate-y-1/2 ${isDark ? 'text-white/30' : 'text-slate-400'}`}>
                            <UserRound size={14} />
                          </div>
                          <input
                            type="text"
                            value={profileForm.displayName}
                            onChange={(e) => onProfileFormChange((prev) => ({ ...prev, displayName: e.target.value }))}
                            placeholder={isZh ? '如：李兵' : 'e.g. John Doe'}
                            className={`w-full rounded-xl pl-9 pr-3.5 py-2.5 text-xs outline-none border transition-all ${
                              isDark ? 'bg-black/20 border-white/15 text-white placeholder-white/20 focus:border-cyan-400 focus:ring-2 focus:ring-cyan-500/20' : 'bg-white border-slate-200 text-slate-800 placeholder-slate-300 focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/10'
                            }`}
                          />
                        </div>
                      </div>

                      <div>
                        <label className={`block text-[11px] font-medium mb-1.5 ${isDark ? 'text-white/50' : 'text-slate-600'}`}>
                          {isZh ? '手机号码' : 'Phone'}
                        </label>
                        <div className="relative">
                          <div className={`absolute left-3.5 top-1/2 -translate-y-1/2 ${isDark ? 'text-white/30' : 'text-slate-400'}`}>
                            <Phone size={14} />
                          </div>
                          <input
                            type="tel"
                            value={profileForm.phone}
                            onChange={(e) => onProfileFormChange((prev) => ({ ...prev, phone: e.target.value }))}
                            placeholder={isZh ? '如：138xxxx8888' : 'e.g. +1 555-0100'}
                            className={`w-full rounded-xl pl-9 pr-3.5 py-2.5 text-xs outline-none border transition-all ${
                              isDark ? 'bg-black/20 border-white/15 text-white placeholder-white/20 focus:border-cyan-400 focus:ring-2 focus:ring-cyan-500/20' : 'bg-white border-slate-200 text-slate-800 placeholder-slate-300 focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/10'
                            }`}
                          />
                        </div>
                      </div>

                      <div>
                        <label className={`block text-[11px] font-medium mb-1.5 ${isDark ? 'text-white/50' : 'text-slate-600'}`}>
                          {isZh ? '电子邮箱' : 'Email'}
                        </label>
                        <div className="relative">
                          <div className={`absolute left-3.5 top-1/2 -translate-y-1/2 ${isDark ? 'text-white/30' : 'text-slate-400'}`}>
                            <Mail size={14} />
                          </div>
                          <input
                            type="email"
                            value={profileForm.email}
                            onChange={(e) => onProfileFormChange((prev) => ({ ...prev, email: e.target.value }))}
                            placeholder={isZh ? '如：li@example.com' : 'e.g. li@example.com'}
                            className={`w-full rounded-xl pl-9 pr-3.5 py-2.5 text-xs outline-none border transition-all ${
                              isDark ? 'bg-black/20 border-white/15 text-white placeholder-white/20 focus:border-cyan-400 focus:ring-2 focus:ring-cyan-500/20' : 'bg-white border-slate-200 text-slate-800 placeholder-slate-300 focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/10'
                            }`}
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                </motion.div>
              )}

              {/* Tab 1: 登录安全 (Security) */}
              {activeTab === 1 && (
                <motion.div
                  key="tab-security"
                  initial={{ opacity: 0, x: 8 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -8 }}
                  transition={{ duration: 0.15 }}
                  className="space-y-5"
                >
                  <div>
                    <h4 className="text-sm font-bold tracking-tight">{isZh ? '登录安全与凭据保护' : 'Login Security & Credentials'}</h4>
                    <p className={`text-xs mt-0.5 ${isDark ? 'text-white/45' : 'text-slate-400'}`}>
                      {isZh ? '保护您的系统访问密码，支持绑定 TOTP 双因子动态验证器' : 'Manage your system password and multi-factor authentication (MFA)'}
                    </p>
                  </div>

                  {/* Password Change Card */}
                  <div className={`p-4 sm:p-5 rounded-2xl border space-y-3.5 ${
                    isDark ? 'bg-white/[0.03] border-white/10' : 'bg-white border-slate-200/80 shadow-sm'
                  }`}>
                    <div className="flex items-center justify-between">
                      <label className={`text-[11px] font-bold uppercase tracking-wider ${
                        isDark ? 'text-white/60' : 'text-slate-500'
                      }`}>
                        {isZh ? '修改系统登录密码' : 'Change Password'}
                      </label>
                      <span className={`text-[10px] ${isDark ? 'text-white/35' : 'text-slate-400'}`}>
                        {isZh ? '留空表示保持当前密码不变' : 'Leave blank to keep unchanged'}
                      </span>
                    </div>

                    {/* Current Password */}
                    <div>
                      <label className={`block text-[11px] font-medium mb-1 ${isDark ? 'text-white/50' : 'text-slate-600'}`}>
                        {isZh ? '当前密码' : 'Current Password'}
                      </label>
                      <div className="relative">
                        <input
                          type={showProfilePwd ? 'text' : 'password'}
                          value={profileForm.oldPassword || ''}
                          onChange={(e) => onProfileFormChange((prev) => ({ ...prev, oldPassword: e.target.value }))}
                          placeholder={isZh ? '修改密码前请先输入当前密码' : 'Enter current password'}
                          className={`w-full rounded-xl px-3.5 pr-10 py-2.5 text-xs outline-none border transition-all ${
                            isDark ? 'bg-black/20 border-white/15 text-white placeholder-white/20 focus:border-cyan-400 focus:ring-2 focus:ring-cyan-500/20' : 'bg-white border-slate-200 text-slate-800 placeholder-slate-300 focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/10'
                          }`}
                        />
                        <button
                          type="button"
                          onClick={onToggleProfilePassword}
                          className={`absolute right-3 top-1/2 -translate-y-1/2 p-1 ${isDark ? 'text-white/30 hover:text-white/60' : 'text-slate-400 hover:text-slate-600'}`}
                        >
                          {showProfilePwd ? <EyeOff size={14} /> : <Eye size={14} />}
                        </button>
                      </div>
                    </div>

                    {/* New Password & Confirm Password */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div>
                        <label className={`block text-[11px] font-medium mb-1 ${isDark ? 'text-white/50' : 'text-slate-600'}`}>
                          {isZh ? '新密码' : 'New Password'}
                        </label>
                        <div className="relative">
                          <input
                            type={showProfilePwd ? 'text' : 'password'}
                            value={profileForm.password}
                            onChange={(e) => onProfileFormChange((prev) => ({ ...prev, password: e.target.value }))}
                            placeholder={isZh ? '输入新密码' : 'Enter new password'}
                            className={`w-full rounded-xl px-3.5 pr-10 py-2.5 text-xs outline-none border transition-all ${
                              isDark ? 'bg-black/20 border-white/15 text-white placeholder-white/20 focus:border-cyan-400 focus:ring-2 focus:ring-cyan-500/20' : 'bg-white border-slate-200 text-slate-800 placeholder-slate-300 focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/10'
                            }`}
                          />
                          <button
                            type="button"
                            onClick={onToggleProfilePassword}
                            className={`absolute right-3 top-1/2 -translate-y-1/2 p-1 ${isDark ? 'text-white/30 hover:text-white/60' : 'text-slate-400 hover:text-slate-600'}`}
                          >
                            {showProfilePwd ? <EyeOff size={14} /> : <Eye size={14} />}
                          </button>
                        </div>
                      </div>

                      <div>
                        <label className={`block text-[11px] font-medium mb-1 ${isDark ? 'text-white/50' : 'text-slate-600'}`}>
                          {isZh ? '确认新密码' : 'Confirm New Password'}
                        </label>
                        <input
                          type={showProfilePwd ? 'text' : 'password'}
                          value={profileForm.confirmPassword}
                          onChange={(e) => onProfileFormChange((prev) => ({ ...prev, confirmPassword: e.target.value }))}
                          placeholder={isZh ? '再次输入新密码' : 'Re-enter new password'}
                          className={`w-full rounded-xl px-3.5 py-2.5 text-xs outline-none border transition-all ${
                            passwordConfirmationError
                              ? (isDark ? 'border-rose-400 bg-rose-500/5 text-white' : 'border-rose-400 bg-rose-50 text-slate-900')
                              : isDark ? 'bg-black/20 border-white/15 text-white placeholder-white/20 focus:border-cyan-400 focus:ring-2 focus:ring-cyan-500/20' : 'bg-white border-slate-200 text-slate-800 placeholder-slate-300 focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/10'
                          }`}
                        />
                      </div>
                    </div>

                    {passwordConfirmationError && (
                      <p className="text-[11px] font-semibold text-rose-500 flex items-center gap-1.5 mt-1">
                        <AlertCircle size={13} />
                        {passwordConfirmationError}
                      </p>
                    )}
                  </div>

                  {/* Fixed PIN (Administrator Only) */}
                  {(currentRole === 'Administrator' || currentRole === 'admin') && (
                    <div className={`p-4 sm:p-5 rounded-2xl border ${
                      isDark ? 'bg-amber-500/[0.04] border-amber-500/20' : 'bg-amber-50/60 border-amber-200'
                    }`}>
                      <div className="flex items-center gap-2 mb-2">
                        <Shield size={16} className={isDark ? 'text-amber-400' : 'text-amber-600'} />
                        <span className={`text-xs font-bold ${isDark ? 'text-amber-300' : 'text-amber-800'}`}>
                          {isZh ? '特权审批固定安全码 (Fixed PIN)' : 'Fixed PIN for Admin Approvals'}
                        </span>
                      </div>
                      <p className={`text-[11px] mb-3 leading-relaxed ${isDark ? 'text-white/45' : 'text-slate-500'}`}>
                        {isZh
                          ? '用于特权终端登录及双人复核时的快速固定 PIN 码（6 位纯数字）。如已开启 TOTP 动态认证，系统将自动升级为动态验证码。'
                          : 'Used for privileged terminal approval. 6-digit number.'}
                      </p>
                      <div className="relative max-w-xs">
                        <input
                          type={showFixedPin ? 'text' : 'password'}
                          maxLength={6}
                          value={profileForm.fixedPin || ''}
                          onChange={(e) => onProfileFormChange((prev) => ({ ...prev, fixedPin: e.target.value.replace(/\D/g, '') }))}
                          placeholder={isZh ? '6 位纯数字安全码' : '6-digit PIN'}
                          className={`w-full rounded-xl px-3.5 pr-10 py-2 text-sm font-mono font-bold tracking-widest outline-none border transition-all ${
                            isDark ? 'bg-black/30 border-amber-500/30 text-amber-200 placeholder-white/20 focus:border-amber-400' : 'bg-white border-amber-300 text-amber-900 placeholder-slate-300 focus:border-amber-500'
                          }`}
                        />
                        <button
                          type="button"
                          onClick={() => setShowFixedPin(!showFixedPin)}
                          className={`absolute right-3 top-1/2 -translate-y-1/2 p-1 ${isDark ? 'text-amber-400/60 hover:text-amber-300' : 'text-amber-600 hover:text-amber-800'}`}
                        >
                          {showFixedPin ? <EyeOff size={14} /> : <Eye size={14} />}
                        </button>
                      </div>
                    </div>
                  )}

                  {/* MFA Multi-Factor Authentication Card */}
                  <div className={`p-4 sm:p-5 rounded-2xl border ${
                    isDark ? 'bg-cyan-500/[0.04] border-cyan-500/20' : 'bg-cyan-50/50 border-cyan-200'
                  }`}>
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <Shield size={16} className={isDark ? 'text-cyan-400' : 'text-cyan-600'} />
                        <span className={`text-xs font-bold ${isDark ? 'text-cyan-200' : 'text-cyan-900'}`}>
                          {isZh ? 'MFA 双因子二次身份认证 (TOTP)' : 'Multi-Factor Authentication (TOTP)'}
                        </span>
                      </div>
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                        mfaActive
                          ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                          : 'bg-slate-500/15 text-slate-400 border border-slate-500/20'
                      }`}>
                        {mfaActive ? (isZh ? '已开启保护' : 'Protected') : (isZh ? '未开启' : 'Disabled')}
                      </span>
                    </div>

                    <p className={`text-[11px] leading-relaxed mb-4 ${isDark ? 'text-white/50' : 'text-slate-500'}`}>
                      {isZh
                        ? '兼容标准 TOTP 算法，支持 Google Authenticator、Microsoft Authenticator、腾讯/阿里等手机认证器。开启后登录需额外输入 6 位动态验证码。'
                        : 'Compatible with Google Authenticator, Microsoft Authenticator and standard TOTP apps.'}
                    </p>

                    {!mfaActive ? (
                      !setupMode ? (
                        <button
                          type="button"
                          disabled={mfaLoading}
                          onClick={handleStartSetup}
                          className="px-4 py-2 rounded-xl text-xs font-bold text-white bg-cyan-600 hover:bg-cyan-500 transition-all shadow-md shadow-cyan-600/20 flex items-center gap-2"
                        >
                          <Shield size={14} />
                          {mfaLoading ? (isZh ? '初始化中...' : 'Initializing...') : (isZh ? '绑定并启用二次认证' : 'Set up & Enable MFA')}
                        </button>
                      ) : (
                        <div className="space-y-4 pt-2 border-t border-cyan-500/15">
                          <p className={`text-xs font-medium ${isDark ? 'text-cyan-200' : 'text-cyan-800'}`}>
                            {isZh ? '请使用手机身份验证器扫描下方二维码绑定：' : 'Scan QR code with your authenticator app:'}
                          </p>

                          <div className="flex flex-col sm:flex-row items-center gap-4">
                            <div className="p-3 bg-white rounded-2xl shadow-inner flex items-center justify-center border border-slate-200 shrink-0">
                              <QRCode value={mfaQrUri} size={120} />
                            </div>
                            <div className="flex-1 space-y-2 text-center sm:text-left min-w-0">
                              <span className={`text-[10px] uppercase font-bold tracking-wider block ${isDark ? 'text-white/40' : 'text-slate-400'}`}>
                                {isZh ? '手动密钥 (Secret Key)' : 'Manual Secret'}
                              </span>
                              <div className="flex items-center gap-2 justify-center sm:justify-start">
                                <code className={`text-xs font-mono font-bold px-2.5 py-1 rounded-lg select-all border truncate max-w-xs ${
                                  isDark ? 'bg-black/30 border-white/10 text-cyan-300' : 'bg-white border-slate-200 text-cyan-800'
                                }`}>
                                  {mfaSecret}
                                </code>
                                <button
                                  type="button"
                                  onClick={handleCopySecret}
                                  className={`p-1.5 rounded-lg border text-xs transition-colors ${
                                    isDark ? 'border-white/10 hover:bg-white/10' : 'border-slate-200 hover:bg-slate-100'
                                  }`}
                                  title={isZh ? '复制密钥' : 'Copy secret'}
                                >
                                  {secretCopied ? <Check size={13} className="text-emerald-400" /> : <ExternalLink size={13} />}
                                </button>
                              </div>
                              <p className={`text-[10px] ${isDark ? 'text-white/35' : 'text-slate-400'}`}>
                                {isZh ? '提示：请妥善保存此密钥，换手机或重置时可用于恢复认证器。' : 'Store this key safely for account recovery.'}
                              </p>
                            </div>
                          </div>

                          <div className="space-y-2 pt-3 border-t border-cyan-500/15">
                            <label className={`block text-[11px] font-bold ${isDark ? 'text-white/70' : 'text-slate-700'}`}>
                              {isZh ? '输入 App 上的 6 位动态验证码确认绑定：' : 'Enter 6-digit code to verify:'}
                            </label>
                            <div className="flex items-center gap-3">
                              <input
                                type="text"
                                maxLength={6}
                                placeholder="000000"
                                value={mfaCodeInput}
                                onChange={(e) => setMfaCodeInput(e.target.value.replace(/\D/g, ''))}
                                className={`w-32 rounded-xl px-3 py-2 text-center text-sm font-bold tracking-[0.25em] outline-none border transition-all ${
                                  isDark ? 'bg-black/30 border-cyan-500/40 text-cyan-300 focus:border-cyan-400' : 'bg-white border-cyan-300 text-cyan-900 focus:border-cyan-500'
                                }`}
                              />
                              <button
                                type="button"
                                disabled={mfaLoading || mfaCodeInput.length < 6}
                                onClick={handleEnableMfa}
                                className="px-4 py-2 rounded-xl text-xs font-bold text-white bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-md shadow-emerald-600/20"
                              >
                                {mfaLoading ? (isZh ? '验证中...' : 'Verifying...') : (isZh ? '确认开启' : 'Verify & Enable')}
                              </button>
                              <button
                                type="button"
                                onClick={() => { setSetupMode(false); setMfaCodeInput(''); setMfaErrorMsg(''); }}
                                className={`px-3 py-2 rounded-xl text-xs font-medium transition-colors ${
                                  isDark ? 'bg-white/10 text-white/80 hover:bg-white/15' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                                }`}
                              >
                                {isZh ? '取消' : 'Cancel'}
                              </button>
                            </div>
                            {mfaErrorMsg && <p className="text-xs text-rose-500 font-semibold mt-1.5">{mfaErrorMsg}</p>}
                          </div>
                        </div>
                      )
                    ) : (
                      !disableMode ? (
                        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 pt-2 border-t border-cyan-500/15">
                          <div className="flex items-center gap-2 text-xs font-semibold text-emerald-500">
                            <CheckCircle2 size={16} />
                            {isZh ? '您的账号已受 TOTP 二次认证严密保护' : 'Account is protected by TOTP MFA'}
                          </div>
                          <button
                            type="button"
                            onClick={() => { setDisableMode(true); setMfaErrorMsg(''); }}
                            className={`px-3 py-1.5 rounded-xl text-xs font-semibold border transition-all ${
                              isDark ? 'bg-rose-500/10 text-rose-300 border-rose-500/20 hover:bg-rose-500/20' : 'bg-rose-50 text-rose-700 border-rose-200 hover:bg-rose-100'
                            }`}
                          >
                            {isZh ? '关闭二次认证' : 'Disable MFA'}
                          </button>
                        </div>
                      ) : (
                        <div className="space-y-3 pt-2 border-t border-cyan-500/15">
                          <label className={`block text-[11px] font-bold ${isDark ? 'text-white/70' : 'text-slate-700'}`}>
                            {isZh ? '请输入当前登录密码以关闭二次认证：' : 'Enter current password to disable MFA:'}
                          </label>
                          <div className="flex gap-2.5 items-center">
                            <div className="relative flex-1 max-w-sm">
                              <input
                                type={showDisablePassword ? 'text' : 'password'}
                                placeholder={isZh ? '您的登录密码' : 'Your password'}
                                value={disablePasswordInput}
                                onChange={(e) => setDisablePasswordInput(e.target.value)}
                                className={`w-full rounded-xl px-3.5 pr-9 py-2 text-xs outline-none border transition-all ${
                                  isDark ? 'bg-black/20 border-white/15 text-white placeholder-white/20 focus:border-cyan-400' : 'bg-white border-slate-200 text-slate-900 placeholder-slate-300 focus:border-cyan-500'
                                }`}
                              />
                              <button
                                type="button"
                                onClick={() => setShowDisablePassword(!showDisablePassword)}
                                className={`absolute right-2.5 top-1/2 -translate-y-1/2 p-1 ${isDark ? 'text-white/30 hover:text-white/60' : 'text-slate-400 hover:text-slate-600'}`}
                              >
                                {showDisablePassword ? <EyeOff size={13} /> : <Eye size={13} />}
                              </button>
                            </div>
                            <button
                              type="button"
                              disabled={mfaLoading || !disablePasswordInput}
                              onClick={handleDisableMfa}
                              className="px-4 py-2 rounded-xl text-xs font-bold text-white bg-rose-600 hover:bg-rose-500 disabled:opacity-50 transition-all shadow-sm"
                            >
                              {mfaLoading ? (isZh ? '验证中...' : 'Verifying...') : (isZh ? '确认关闭' : 'Confirm')}
                            </button>
                            <button
                              type="button"
                              onClick={() => { setDisableMode(false); setDisablePasswordInput(''); setShowDisablePassword(false); setMfaErrorMsg(''); }}
                              className={`px-3 py-2 rounded-xl text-xs font-medium transition-colors ${
                                isDark ? 'bg-white/10 text-white/80 hover:bg-white/15' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                              }`}
                            >
                              {isZh ? '取消' : 'Cancel'}
                            </button>
                          </div>
                          {mfaErrorMsg && <p className="text-xs text-rose-500 font-semibold">{mfaErrorMsg}</p>}
                        </div>
                      )
                    )}
                  </div>
                </motion.div>
              )}

              {/* Tab 2: 告警通知 (Notifications) */}
              {activeTab === 2 && (
                <motion.div
                  key="tab-notifications"
                  initial={{ opacity: 0, x: 8 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -8 }}
                  transition={{ duration: 0.15 }}
                  className="space-y-4"
                >
                  <div>
                    <h4 className="text-sm font-bold tracking-tight">{isZh ? '告警通知渠道配置' : 'Alert Notification Channels'}</h4>
                    <p className={`text-xs mt-0.5 ${isDark ? 'text-white/45' : 'text-slate-400'}`}>
                      {isZh ? '配置网络异常、接口 DOWN、CPU 超阈值等告警的群机器人实时推送' : 'Configure bot webhooks to receive real-time network incident alerts'}
                    </p>
                  </div>

                  <div className="space-y-3">
                    {channels.map(({ key, label, sub, icon, iconBg, badge, hint, hasSecret, docsUrl, docsLabel, tip }) => {
                      const channel = notificationChannels[key];
                      const isEnabled = channel.enabled;
                      const isCreator = !channel.creator_username || channel.creator_username === profileForm.username;

                      return (
                        <div
                          key={key}
                          className={`rounded-2xl border transition-all duration-200 p-4 ${
                            isEnabled
                              ? (isDark ? 'border-cyan-500/30 bg-cyan-500/[0.04] shadow-sm' : 'border-cyan-300 bg-cyan-50/40 shadow-sm')
                              : (isDark ? 'border-white/10 bg-white/[0.02]' : 'border-slate-200/80 bg-white')
                          }`}
                        >
                          <div className="flex items-center justify-between gap-3 mb-3">
                            <div className="flex items-center gap-3">
                              <span className={`w-8 h-8 rounded-xl ${iconBg} flex items-center justify-center text-[10px] font-black text-white shrink-0 shadow-sm`}>
                                {icon}
                              </span>
                              <div>
                                <div className="flex items-center gap-2">
                                  <span className="text-xs font-bold">{label}</span>
                                  <span className={`text-[10px] font-medium px-2 py-0.5 rounded-md ${badge}`}>{sub}</span>
                                </div>
                              </div>
                            </div>
                            <div className="flex items-center gap-3">
                              <a
                                href={docsUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                className={`text-[11px] flex items-center gap-1 transition-colors ${
                                  isDark ? 'text-cyan-400/80 hover:text-cyan-300' : 'text-cyan-700 hover:text-cyan-900'
                                }`}
                              >
                                {docsLabel}
                              </a>
                              <button
                                type="button"
                                title={!isCreator ? `仅创建者 ${channel.creator_username} 有权操作` : (isEnabled ? '关闭此渠道' : '开启此渠道')}
                                disabled={!isCreator}
                                onClick={() => onNotificationChannelToggle(key)}
                                className={`relative w-10 h-6 rounded-full transition-colors shrink-0 ${
                                  !isCreator
                                    ? 'opacity-30 cursor-not-allowed bg-slate-500'
                                    : (isEnabled ? 'bg-cyan-500' : (isDark ? 'bg-white/20' : 'bg-slate-300'))
                                }`}
                              >
                                <span className={`absolute top-1 w-4 h-4 rounded-full bg-white shadow-md transition-all ${isEnabled ? 'left-5' : 'left-1'}`} />
                              </button>
                            </div>
                          </div>

                          <p className={`text-[11px] leading-relaxed mb-3 ${isDark ? 'text-white/40' : 'text-slate-500'}`}>{tip}</p>

                          <div className="space-y-2">
                            <div>
                              <input
                                type="text"
                                disabled={!isCreator}
                                value={channel.webhook_url}
                                onChange={(e) => onNotificationWebhookChange(key, e.target.value)}
                                placeholder={hint}
                                className={`w-full rounded-xl px-3.5 py-2 text-xs font-mono outline-none border transition-all ${
                                  !isCreator
                                    ? (isDark ? 'bg-black/40 text-white/30 cursor-not-allowed border-white/5' : 'bg-slate-100 text-slate-400 cursor-not-allowed border-slate-200')
                                    : (isDark ? 'bg-black/20 border-white/15 text-white placeholder-white/20 focus:border-cyan-400' : 'bg-white border-slate-200 text-slate-800 placeholder-slate-300 focus:border-cyan-500')
                                }`}
                              />
                            </div>

                            {hasSecret && (
                              <div className="relative">
                                <input
                                  type={showDingtalkSecret ? 'text' : 'password'}
                                  disabled={!isCreator}
                                  value={notificationChannels.dingtalk.secret}
                                  onChange={(e) => onNotificationSecretChange(e.target.value)}
                                  placeholder={isZh ? '加签密钥 Secret（可选，留空则不验签）' : 'Sign Secret (Optional)'}
                                  className={`w-full rounded-xl px-3.5 pr-9 py-2 text-xs font-mono outline-none border transition-all ${
                                    !isCreator
                                      ? (isDark ? 'bg-black/40 text-white/30 cursor-not-allowed border-white/5' : 'bg-slate-100 text-slate-400 cursor-not-allowed border-slate-200')
                                      : (isDark ? 'bg-black/20 border-white/15 text-white placeholder-white/20 focus:border-cyan-400' : 'bg-white border-slate-200 text-slate-800 placeholder-slate-300 focus:border-cyan-500')
                                  }`}
                                />
                                {isCreator && (
                                  <button
                                    type="button"
                                    onClick={() => setShowDingtalkSecret(!showDingtalkSecret)}
                                    className={`absolute right-2.5 top-1/2 -translate-y-1/2 p-1 ${isDark ? 'text-white/30 hover:text-white/60' : 'text-slate-400 hover:text-slate-600'}`}
                                  >
                                    {showDingtalkSecret ? <EyeOff size={13} /> : <Eye size={13} />}
                                  </button>
                                )}
                              </div>
                            )}

                            <div className="flex justify-end pt-1">
                              <button
                                type="button"
                                disabled={!channel.webhook_url.trim() || notifyTestLoading === key || !isCreator}
                                onClick={() => onTestNotificationChannel(key)}
                                className={`px-4 py-1.5 rounded-xl text-xs font-bold transition-all flex items-center gap-1.5 ${
                                  !channel.webhook_url.trim() || notifyTestLoading === key || !isCreator
                                    ? (isDark ? 'bg-white/5 text-white/20 cursor-not-allowed' : 'bg-slate-100 text-slate-300 cursor-not-allowed')
                                    : (isDark ? 'bg-cyan-500/20 text-cyan-300 hover:bg-cyan-500/30 border border-cyan-400/30 shadow-sm' : 'bg-cyan-50 text-cyan-800 hover:bg-cyan-100 border border-cyan-200 shadow-sm')
                                }`}
                              >
                                {notifyTestLoading === key ? (
                                  <><span className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin" />{isZh ? '发送中...' : 'Sending...'}</>
                                ) : (
                                  <>📨 {isZh ? '发送测试消息' : 'Send Test Message'}</>
                                )}
                              </button>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </motion.div>
              )}

              {/* Tab 3: 终端工具 (Terminal) */}
              {activeTab === 3 && (
                <motion.div
                  key="tab-terminal"
                  initial={{ opacity: 0, x: 8 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -8 }}
                  transition={{ duration: 0.15 }}
                  className="space-y-5"
                >
                  <div>
                    <h4 className="text-sm font-bold tracking-tight">{isZh ? '本机终端工具与 Agent 配置' : 'Terminal Tools & Agent Setup'}</h4>
                    <p className={`text-xs mt-0.5 ${isDark ? 'text-white/45' : 'text-slate-400'}`}>
                      {isZh ? '配置从浏览器一键唤起本机终端（Xshell、PuTTY 等）进行设备运维' : 'Configure local terminal software integration and agent launch paths'}
                    </p>
                  </div>

                  {/* Detected System Badge */}
                  <div className={`p-4 rounded-2xl border flex items-center justify-between gap-3 ${
                    isDark ? 'bg-cyan-500/[0.04] border-cyan-500/20' : 'bg-cyan-50/60 border-cyan-200'
                  }`}>
                    <div className="flex items-center gap-3">
                      <div className={`p-2 rounded-xl ${isDark ? 'bg-cyan-400/15 text-cyan-300' : 'bg-white text-cyan-700 shadow-sm'}`}>
                        <MonitorSpeaker size={18} />
                      </div>
                      <div>
                        <div className="text-xs font-bold">{isZh ? '当前浏览器工作站系统' : 'Current Workstation OS'}</div>
                        <div className={`text-[11px] ${isDark ? 'text-white/50' : 'text-slate-500'}`}>
                          {isZh ? `已识别为您正在使用 ${terminalPlatformLabel}` : `Detected platform: ${terminalPlatformLabel}`}
                        </div>
                      </div>
                    </div>
                    <span className={`px-2.5 py-1 rounded-lg text-xs font-bold ${
                      isDark ? 'bg-cyan-400/20 text-cyan-300 border border-cyan-400/30' : 'bg-cyan-100 text-cyan-800 border border-cyan-300'
                    }`}>
                      {terminalPlatformLabel}
                    </span>
                  </div>

                  {/* Windows Client Path Config */}
                  {terminalPlatform === 'windows' ? (
                    <div className={`p-4 sm:p-5 rounded-2xl border space-y-3.5 ${
                      isDark ? 'bg-white/[0.03] border-white/10' : 'bg-white border-slate-200/80 shadow-sm'
                    }`}>
                      <div className="flex flex-col sm:flex-row gap-4">
                        <div className="w-full sm:w-1/3">
                          <label className={`block text-[11px] font-bold uppercase tracking-wider mb-1.5 ${isDark ? 'text-white/60' : 'text-slate-500'}`}>
                            {isZh ? '终端程序类型' : 'Terminal App'}
                          </label>
                          <select
                            value={terminalApp}
                            onChange={(e) => {
                              const val = e.target.value as TerminalApp;
                              setTerminalApp(val);
                              localStorage.setItem('terminal_app', val);
                            }}
                            className={`w-full px-3 py-2.5 rounded-xl text-xs outline-none border transition-all font-semibold ${
                              isDark ? 'bg-black/30 border-white/15 text-white focus:border-cyan-400' : 'bg-white border-slate-200 text-slate-800 focus:border-cyan-500'
                            }`}
                          >
                            <option value="xshell">Xshell</option>
                            <option value="putty">PuTTY</option>
                            <option value="securecrt">SecureCRT</option>
                            <option value="mobaxterm">MobaXterm</option>
                          </select>
                        </div>

                        <div className="flex-1">
                          <label className={`block text-[11px] font-bold uppercase tracking-wider mb-1.5 ${isDark ? 'text-white/60' : 'text-slate-500'}`}>
                            {isZh ? '客户端可执行程序路径 (EXE)' : 'Client Executable Path (EXE)'}
                          </label>
                          <div className="flex gap-2">
                            <div className="relative flex-1">
                              <Terminal size={14} className={`absolute left-3.5 top-1/2 -translate-y-1/2 ${isDark ? 'text-white/30' : 'text-slate-400'}`} />
                              <input
                                type="text"
                                value={localTerminalPath}
                                onChange={(e) => {
                                  const val = e.target.value;
                                  setLocalTerminalPath(val);
                                  localStorage.setItem('local_terminal_path', val);
                                }}
                                placeholder="C:\Program Files\...\Xshell.exe"
                                className={`w-full pl-9 pr-3.5 py-2.5 rounded-xl text-xs font-mono outline-none border transition-all ${
                                  isDark ? 'bg-black/30 border-white/15 text-white placeholder-white/20 focus:border-cyan-400' : 'bg-white border-slate-200 text-slate-800 placeholder-slate-300 focus:border-cyan-500'
                                }`}
                              />
                            </div>
                            <div className="relative">
                              <button
                                type="button"
                                onClick={() => setShowPathSuggestions((v) => !v)}
                                className={`px-3 py-2.5 rounded-xl text-xs font-bold flex items-center gap-1.5 transition-all border shrink-0 ${
                                  isDark ? 'bg-cyan-500/20 text-cyan-300 border-cyan-400/30 hover:bg-cyan-500/30' : 'bg-cyan-50 text-cyan-800 border-cyan-200 hover:bg-cyan-100'
                                }`}
                              >
                                <Sparkles size={13} />
                                {isZh ? '常见路径' : 'Presets'}
                              </button>

                              {showPathSuggestions && (
                                <div className={`absolute right-0 top-full mt-1.5 z-50 w-80 rounded-2xl border shadow-2xl overflow-hidden p-1.5 ${
                                  isDark ? 'bg-[#0f172a] border-white/15' : 'bg-white border-slate-200'
                                }`}>
                                  <div className={`px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider ${isDark ? 'text-white/40' : 'text-slate-400'}`}>
                                    {isZh ? '选择匹配的本地路径：' : 'Select matching path:'}
                                  </div>
                                  {(PATH_PRESETS[terminalApp] || []).map((p) => (
                                    <button
                                      key={p}
                                      type="button"
                                      onClick={() => {
                                        setLocalTerminalPath(p);
                                        localStorage.setItem('local_terminal_path', p);
                                        setShowPathSuggestions(false);
                                      }}
                                      className={`w-full text-left px-3 py-2 rounded-xl text-xs font-mono transition-colors truncate ${
                                        isDark ? 'text-white/80 hover:bg-white/10' : 'text-slate-700 hover:bg-slate-100'
                                      }`}
                                    >
                                      {p}
                                    </button>
                                  ))}
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className={`p-4 rounded-2xl border ${isDark ? 'border-white/10 bg-white/[0.02]' : 'border-slate-200 bg-white'}`}>
                      <p className={`text-xs leading-relaxed ${isDark ? 'text-white/60' : 'text-slate-600'}`}>
                        {isZh ? '当前为 Linux/Ubuntu 系统，无需指定 Windows 客户端路径，只需启动匹配的 Terminal Agent 即可。' : 'No client path needed on Linux. Run the local agent script.'}
                      </p>
                    </div>
                  )}

                  {/* Agent Download Card */}
                  <div className={`p-4 sm:p-5 rounded-2xl border flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 ${
                    isDark ? 'bg-gradient-to-r from-cyan-500/10 to-blue-500/10 border-cyan-500/25' : 'bg-gradient-to-r from-cyan-50/80 to-blue-50/80 border-cyan-200'
                  }`}>
                    <div>
                      <div className="flex items-center gap-2 font-bold text-xs">
                        <Download size={15} className={isDark ? 'text-cyan-400' : 'text-cyan-600'} />
                        <span>{isZh ? `下载 ${terminalPlatformLabel} 专用 Terminal Agent` : `Download ${terminalPlatformLabel} Terminal Agent`}</span>
                      </div>
                      <p className={`text-[11px] mt-1 ${isDark ? 'text-white/50' : 'text-slate-500'}`}>
                        {isZh ? '在本地工作站运行该轻量级守护程序，即可从网页端秒级唤醒原生终端。' : 'Run this lightweight daemon to launch native terminal sessions directly from web.'}
                      </p>
                    </div>
                    <ActionLink
                      href={`/api/system/download-terminal-agent?platform=${terminalPlatform}`}
                      download={terminalPlatform === 'windows' ? 'NexoraTerminalAgent.exe' : 'install-terminal-agent.sh'}
                      icon={Download}
                      variant={terminalPlatform === 'windows' ? 'success' : 'accent'}
                      size="sm"
                      className="!rounded-xl shrink-0 font-bold"
                    >
                      {terminalPlatform === 'windows'
                        ? (isZh ? '下载 Windows EXE' : 'Download Windows EXE')
                        : (isZh ? '下载 Ubuntu 脚本' : 'Download Ubuntu Script')}
                    </ActionLink>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>

        {/* Footer Actions */}
        <div className={`flex items-center justify-end gap-3 px-6 py-4 border-t shrink-0 ${
          isDark ? 'border-white/10 bg-[#141e33]' : 'border-slate-100 bg-slate-50/80'
        }`}>
          <button
            type="button"
            onClick={onClose}
            className={`px-5 py-2.5 rounded-xl text-xs font-semibold transition-all ${
              isDark ? 'bg-white/10 text-white/80 hover:bg-white/15' : 'bg-slate-200/80 text-slate-700 hover:bg-slate-300/80'
            }`}
          >
            {isZh ? '取消' : 'Cancel'}
          </button>
          <button
            type="button"
            disabled={Boolean(passwordConfirmationError)}
            onClick={onSave}
            className={`px-6 py-2.5 rounded-xl text-xs font-bold text-white transition-all shadow-lg ${
              passwordConfirmationError
                ? 'bg-slate-400 cursor-not-allowed opacity-50 shadow-none'
                : 'bg-gradient-to-r from-[#008bb0] to-[#00bceb] hover:from-[#00769a] hover:to-[#00a8d4] shadow-cyan-500/25'
            }`}
          >
            {isZh ? '保存个人设置' : 'Save Changes'}
          </button>
        </div>
      </motion.div>
    </div>
  );
};

export default ProfileModal;
