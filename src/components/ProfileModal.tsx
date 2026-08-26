import React from 'react';
import { motion } from 'motion/react';
import { Bell, Eye, EyeOff, Terminal, MonitorSpeaker, Shield, Download, Lock, Info, UserRound, KeyRound, ChevronLeft, ChevronRight, CheckCircle2 } from 'lucide-react';
import type { ThemeMode } from '../types';
import { useSystem } from '../hooks/useSystem';
import QRCode from 'react-qr-code';
import { ActionLink } from './ui/ActionIconButton';

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
  
  // MFA local states
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

  // Sync state when prop changes
  React.useEffect(() => {
    setMfaActive(mfaEnabled);
  }, [mfaEnabled]);

  const handleStartSetup = async () => {
    setMfaErrorMsg('');
    setMfaLoading(true);
    try {
      const token = localStorage.getItem('netops_token');
      const res = await fetch('/api/mfa/setup', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });
      const data = await res.json();
      if (res.ok && data.success) {
        setMfaSecret(data.secret);
        setMfaQrUri(data.qr_code_uri);
        setSetupMode(true);
      } else {
        setMfaErrorMsg(data.detail || '初始化 MFA 失败');
      }
    } catch (err: any) {
      setMfaErrorMsg('网络连接错误，请稍后重试');
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
        body: JSON.stringify({
          code: mfaCodeInput,
          secret: mfaSecret
        })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        setMfaActive(true);
        setSetupMode(false);
        setMfaCodeInput('');
        onMfaStatusChange(true);
        alert(language === 'zh' ? '双因子二次认证开启成功！' : 'MFA enabled successfully!');
      } else {
        setMfaErrorMsg(data.detail || '验证码错误或校验失败');
      }
    } catch (err) {
      setMfaErrorMsg('网络错误，启用失败');
    } finally {
      setMfaLoading(false);
    }
  };

  const handleDisableMfa = async () => {
    if (!disablePasswordInput) {
      setMfaErrorMsg('请输入密码以确认关闭');
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
        body: JSON.stringify({
          password: disablePasswordInput
        })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        setMfaActive(false);
        setDisableMode(false);
        setDisablePasswordInput('');
        onMfaStatusChange(false);
        alert(language === 'zh' ? '双因子二次认证已成功关闭！' : 'MFA disabled successfully!');
      } else {
        setMfaErrorMsg(data.detail || '密码不正确');
      }
    } catch (err) {
      setMfaErrorMsg('网络错误，关闭失败');
    } finally {
      setMfaLoading(false);
    }
  };
  const [localTerminalPath, setLocalTerminalPath] = React.useState(() => localStorage.getItem('local_terminal_path') || '');
  const [terminalApp, setTerminalApp] = React.useState(() => localStorage.getItem('terminal_app') || 'standard');
  const [showFixedPin, setShowFixedPin] = React.useState(false);
  const [showPathSuggestions, setShowPathSuggestions] = React.useState(false);
  const [wizardStep, setWizardStep] = React.useState(0);
  const isZh = language === 'zh';

  const wizardSteps = [
    { key: 'profile', label: isZh ? '基本资料' : 'Profile', description: isZh ? '头像与联系方式' : 'Avatar and contact details', icon: UserRound },
    { key: 'security', label: isZh ? '登录安全' : 'Login security', description: isZh ? '密码与 MFA 保护' : 'Password and MFA protection', icon: KeyRound },
    { key: 'notifications', label: isZh ? '告警通知' : 'Notifications', description: isZh ? '可选的消息推送' : 'Optional message delivery', icon: Bell },
    { key: 'terminal', label: isZh ? '终端工具' : 'Terminal tools', description: isZh ? '本机启动配置' : 'Local launch settings', icon: MonitorSpeaker },
  ] as const;

  // Validate the confirmation field as soon as the second password input is
  // used. The save handler keeps the same check as a final safety net.
  const passwordConfirmationError = profileForm.confirmPassword
    ? !profileForm.password
      ? (isZh ? '请先输入新密码' : 'Enter the new password first')
      : profileForm.password !== profileForm.confirmPassword
        ? (isZh ? '两次输入的密码不一致' : 'Passwords do not match')
        : ''
    : '';

  React.useEffect(() => {
    if (open) {
      setWizardStep(0);
      setShowPathSuggestions(false);
      setSetupMode(false);
      setMfaCodeInput('');
      setMfaErrorMsg('');
      setDisableMode(false);
      setDisablePasswordInput('');
    }
  }, [open]);

  const activeWizardStep = wizardSteps[wizardStep];
  const goToWizardStep = (step: number) => {
    setWizardStep(Math.min(Math.max(step, 0), wizardSteps.length - 1));
  };

  // 各终端工具的常见安装路径（Windows）
  const PATH_PRESETS: Record<string, string[]> = {
    xshell: [
      'C:\\Program Files (x86)\\NetSarang\\Xshell 8\\Xshell.exe',
      'C:\\Program Files (x86)\\NetSarang\\Xshell 7\\Xshell.exe',
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
  
  if (!open) return null;

  const channels = [
    {
      key: 'feishu',
      label: '飞书',
      sub: 'Feishu',
      icon: 'FS',
      iconBg: 'bg-[#1664FF]',
      badge: 'bg-blue-500/10 text-blue-500',
      hint: 'https://open.feishu.cn/open-apis/bot/v2/hook/…',
      hasSecret: false,
      docsUrl: 'https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot',
      docsLabel: '配置教程 →',
      tip: '在飞书群 ➜ 设置 ➜ 群机器人 ➜ 添加机器人 ➜ 自定义机器人，复制 Webhook URL 粘贴到此处。消息格式：彩色卡片（含8字段）。',
    },
    {
      key: 'dingtalk',
      label: '钉钉',
      sub: 'DingTalk',
      icon: 'DT',
      iconBg: 'bg-[#3296FA]',
      badge: 'bg-sky-500/10 text-sky-500',
      hint: 'https://oapi.dingtalk.com/robot/send?access_token=…',
      hasSecret: true,
      docsUrl: 'https://open.dingtalk.com/document/robots/custom-robot-access',
      docsLabel: '配置教程 →',
      tip: `在钉钉群 ➜ 群设置 ➜ 智能群助手 ➜ 添加机器人 ➜ 自定义。安全设置选「加签」时把密钥填入下方 Secret 栏；选「自定义关键词」时关键词填 ${systemInfo?.system_name || 'Nexora'} 即可。`,
    },
    {
      key: 'wechat',
      label: '企业微信',
      sub: 'WeCom',
      icon: 'WC',
      iconBg: 'bg-[#07C160]',
      badge: 'bg-green-500/10 text-green-500',
      hint: 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…',
      hasSecret: false,
      docsUrl: 'https://developer.work.weixin.qq.com/document/path/91770',
      docsLabel: '配置教程 →',
      tip: '在企业微信群 ➜ 右键群名称 ➜ 添加群机器人 ➜ 新创建一个机器人，复制 Webhook URL 粘贴到此处。',
    },
  ] as const;

  const isDark = resolvedTheme === 'dark';
  const ActiveStepIcon = activeWizardStep.icon;

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-sm">
      <motion.div
        initial={{ opacity: 0, y: 12, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        className={`w-full max-w-4xl overflow-hidden rounded-[1.75rem] border shadow-[0_24px_80px_rgba(15,23,42,0.28)] ${isDark ? 'bg-[#121c2d] border-white/10' : 'bg-slate-50 border-white/80'}`}
      >
        <div className={`border-b px-6 py-5 ${isDark ? 'border-white/10' : 'border-black/10'}`}>
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2.5">
                <span className={`flex h-9 w-9 items-center justify-center rounded-xl ${isDark ? 'bg-cyan-400/15 text-cyan-300' : 'bg-cyan-50 text-cyan-700'}`}>
                  <Shield size={18} />
                </span>
                <h3 className={`text-lg font-bold ${isDark ? 'text-white/90' : 'text-[#0b2a3c]'}`}>{isZh ? '个人设置向导' : 'Personal setup guide'}</h3>
                <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${isDark ? 'bg-white/10 text-white/50' : 'bg-slate-100 text-slate-500'}`}>
                  {wizardStep + 1} / {wizardSteps.length}
                </span>
              </div>
              <p className={`mt-1.5 text-xs ${isDark ? 'text-white/45' : 'text-black/45'}`}>{isZh ? '按步骤完成账户安全、告警通知和本机终端配置' : 'Complete account security, notifications, and local terminal settings step by step'}</p>
            </div>
            <div className={`hidden shrink-0 items-center gap-1.5 rounded-xl px-3 py-2 text-right sm:flex ${isDark ? 'bg-white/5' : 'bg-white/75'}`}>
              <ActiveStepIcon size={15} className={isDark ? 'text-cyan-300' : 'text-cyan-600'} />
              <div>
                <div className={`text-[10px] font-bold ${isDark ? 'text-white/75' : 'text-slate-700'}`}>{activeWizardStep.label}</div>
                <div className={`text-[9px] ${isDark ? 'text-white/35' : 'text-slate-400'}`}>{activeWizardStep.description}</div>
              </div>
            </div>
          </div>

          <div className="mt-5 flex items-center gap-1.5 overflow-x-auto pb-0.5">
            {wizardSteps.map((step, index) => {
              const StepIcon = step.icon;
              const completed = index < wizardStep;
              const active = index === wizardStep;
              return (
                <React.Fragment key={step.key}>
                  <button
                    type="button"
                    onClick={() => goToWizardStep(index)}
                    className={`flex min-w-max items-center gap-2 rounded-xl px-2.5 py-2 text-left transition-all ${active ? (isDark ? 'bg-cyan-400/15 text-cyan-200 ring-1 ring-cyan-300/20' : 'bg-cyan-50 text-cyan-800 ring-1 ring-cyan-200') : (isDark ? 'text-white/40 hover:bg-white/5 hover:text-white/70' : 'text-slate-400 hover:bg-slate-50 hover:text-slate-700')}`}
                  >
                    <span className={`flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-black ${active ? (isDark ? 'bg-cyan-300 text-slate-950' : 'bg-cyan-600 text-white') : completed ? 'bg-emerald-500 text-white' : (isDark ? 'bg-white/10 text-white/45' : 'bg-slate-100 text-slate-400')}`}>
                      {completed ? <CheckCircle2 size={13} /> : <StepIcon size={13} />}
                    </span>
                    <span className="text-[11px] font-bold">{step.label}</span>
                  </button>
                  {index < wizardSteps.length - 1 && <span className={`h-px min-w-3 flex-1 ${index < wizardStep ? (isDark ? 'bg-emerald-400/50' : 'bg-emerald-300') : (isDark ? 'bg-white/10' : 'bg-slate-200')}`} />}
                </React.Fragment>
              );
            })}
          </div>
        </div>

        <div className={`max-h-[78vh] overflow-y-auto px-6 py-5 ${isDark ? 'bg-[#0f172a]' : 'bg-slate-50/70'}`}>
          <div className={`mb-5 flex items-start gap-3 rounded-2xl border px-4 py-3 ${isDark ? 'border-cyan-400/15 bg-cyan-400/5' : 'border-cyan-100 bg-cyan-50/70'}`} aria-live="polite">
            <ActiveStepIcon size={16} className={`mt-0.5 shrink-0 ${isDark ? 'text-cyan-300' : 'text-cyan-700'}`} />
            <div>
              <div className={`text-xs font-bold ${isDark ? 'text-cyan-100' : 'text-cyan-900'}`}>{isZh ? `第 ${wizardStep + 1} 步：${activeWizardStep.label}` : `Step ${wizardStep + 1}: ${activeWizardStep.label}`}</div>
              <p className={`mt-0.5 text-[11px] leading-relaxed ${isDark ? 'text-white/45' : 'text-cyan-800/70'}`}>{activeWizardStep.description}{wizardStep === 1 && (isZh ? '；密码只在本次提交时处理，不会显示在页面上。' : '; passwords are processed on submit and are not displayed.')}</p>
            </div>
          </div>
          <div className={wizardStep === 0 ? 'space-y-5' : 'hidden'}>
            <div className={`flex items-start gap-3 rounded-2xl border p-4 ${isDark ? 'border-white/10 bg-white/[0.03]' : 'border-slate-200 bg-white/80'}`}>
              <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${isDark ? 'bg-cyan-400/15 text-cyan-300' : 'bg-cyan-50 text-cyan-700'}`}><UserRound size={17} /></span>
              <div>
                <div className={`text-xs font-bold ${isDark ? 'text-white/85' : 'text-slate-800'}`}>{isZh ? '先完善你的账户资料' : 'Start with your account profile'}</div>
                <p className={`mt-1 text-[11px] leading-relaxed ${isDark ? 'text-white/45' : 'text-slate-500'}`}>{isZh ? '头像、显示名称和联系方式用于识别与通知展示，不会改变你的登录权限。' : 'Avatar, display name, and contact details help identify you in the workspace and notifications; they do not change your access role.'}</p>
              </div>
            </div>
            <div>
            <label className={`block text-[10px] font-bold uppercase tracking-widest mb-1.5 ${isDark ? 'text-white/55' : 'text-black/45'}`}>个人头像</label>
            <div className="flex items-center gap-3">
              <div className={`w-14 h-14 rounded-full border overflow-hidden flex items-center justify-center ${isDark ? 'bg-white/10 border-white/10 text-white/75' : 'bg-black/10 border-black/10 text-black/60'}`}>
                {renderAvatarContent(profileAvatarPreview, 24)}
              </div>
              <div className="flex gap-2">
                <label className={`px-3 py-1.5 rounded-lg text-xs font-semibold cursor-pointer transition-all ${isDark ? 'bg-white/10 text-white/80 hover:bg-white/15' : 'bg-black/[0.05] text-black/70 hover:bg-black/[0.08]'}`}>
                  上传图片
                  <input type="file" accept="image/*" className="hidden" onChange={onAvatarFileChange} />
                </label>
                <button type="button" onClick={onClearAvatar} className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${isDark ? 'bg-red-500/15 text-red-300 hover:bg-red-500/20' : 'bg-red-50 text-red-600 hover:bg-red-100'}`}>
                  恢复默认
                </button>
              </div>
            </div>
            <div className="mt-2 grid grid-cols-5 gap-2">
              {avatarPresets.map((preset) => {
                const active = profileAvatarPreview === preset.id;
                return (
                  <button
                    key={preset.id}
                    type="button"
                    onClick={() => onSelectAvatarPreset(preset.id)}
                    className={`w-9 h-9 rounded-full border overflow-hidden flex items-center justify-center transition-all ${active ? 'ring-2 ring-[#00bceb]/60 border-[#00bceb]/40' : (isDark ? 'border-white/15 hover:border-white/35' : 'border-black/10 hover:border-black/25')}`}
                    title={preset.label}
                  >
                    <div className={`w-full h-full ${preset.bgClass} flex items-center justify-center`}>
                      <span className="text-sm leading-none">{preset.emoji}</span>
                    </div>
                  </button>
                );
              })}
            </div>
            <p className={`text-[10px] mt-1.5 ${isDark ? 'text-white/35' : 'text-black/35'}`}>支持 PNG/JPG/WebP 格式，大小不超过 2MB。</p>
          </div>

          <div>
            <label className={`block text-[10px] font-bold uppercase tracking-widest mb-1.5 ${isDark ? 'text-white/55' : 'text-black/45'}`}>用户名</label>
            <input
              type="text"
              value={profileForm.username}
              onChange={(event) => onProfileFormChange((prev) => ({ ...prev, username: event.target.value }))}
              title="Profile username"
              placeholder="请输入用户名"
              className={`w-full rounded-xl px-3 py-2.5 text-sm outline-none border transition-all ${isDark ? 'bg-white/5 border-white/15 text-white placeholder-white/30 focus:border-[#00bceb]/60' : 'bg-black/[0.02] border-black/10 text-[#0b2a3c] placeholder-black/30 focus:border-[#00bceb]/50'}`}
            />
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <label className={`block text-[10px] font-bold uppercase tracking-widest mb-1.5 ${isDark ? 'text-white/55' : 'text-black/45'}`}>真实姓名</label>
              <input
                type="text"
                value={profileForm.displayName}
                onChange={(event) => onProfileFormChange((prev) => ({ ...prev, displayName: event.target.value }))}
                title="Display name"
                placeholder="如：李兵"
                className={`w-full rounded-xl px-3 py-2.5 text-sm outline-none border transition-all ${isDark ? 'bg-white/5 border-white/15 text-white placeholder-white/30 focus:border-[#00bceb]/60' : 'bg-black/[0.02] border-black/10 text-[#0b2a3c] placeholder-black/30 focus:border-[#00bceb]/50'}`}
              />
            </div>
            <div>
              <label className={`block text-[10px] font-bold uppercase tracking-widest mb-1.5 ${isDark ? 'text-white/55' : 'text-black/45'}`}>手机号</label>
              <input
                type="tel"
                value={profileForm.phone}
                onChange={(event) => onProfileFormChange((prev) => ({ ...prev, phone: event.target.value }))}
                title="Phone number"
                placeholder="如：138xxxx8888"
                className={`w-full rounded-xl px-3 py-2.5 text-sm outline-none border transition-all ${isDark ? 'bg-white/5 border-white/15 text-white placeholder-white/30 focus:border-[#00bceb]/60' : 'bg-black/[0.02] border-black/10 text-[#0b2a3c] placeholder-black/30 focus:border-[#00bceb]/50'}`}
              />
            </div>
            <div>
              <label className={`block text-[10px] font-bold uppercase tracking-widest mb-1.5 ${isDark ? 'text-white/55' : 'text-black/45'}`}>邮箱</label>
              <input
                type="email"
                value={profileForm.email}
                onChange={(event) => onProfileFormChange((prev) => ({ ...prev, email: event.target.value }))}
                title="Email address"
                placeholder="如：li@example.com"
                className={`w-full rounded-xl px-3 py-2.5 text-sm outline-none border transition-all ${isDark ? 'bg-white/5 border-white/15 text-white placeholder-white/30 focus:border-[#00bceb]/60' : 'bg-black/[0.02] border-black/10 text-[#0b2a3c] placeholder-black/30 focus:border-[#00bceb]/50'}`}
              />
            </div>
          </div>

          <div>
            <label className={`block text-[10px] font-bold uppercase tracking-widest mb-1.5 ${isDark ? 'text-white/55' : 'text-black/45'}`}>当前角色</label>
            <input
              type="text"
              value={language === 'zh' ? (currentRole === 'Administrator' ? '管理员' : currentRole === 'Operator' ? '操作员' : currentRole === 'Viewer' ? '只读用户' : currentRole) : currentRole}
              disabled
              title="Profile role"
              className={`w-full rounded-xl px-3 py-2.5 text-sm border ${isDark ? 'bg-white/5 border-white/10 text-white/60' : 'bg-black/[0.03] border-black/10 text-black/55'}`}
            />
          </div>

          </div>

          <div className={wizardStep === 1 ? 'space-y-5' : 'hidden'}>
            <div className={`flex items-start gap-3 rounded-2xl border p-4 ${isDark ? 'border-amber-400/15 bg-amber-400/5' : 'border-amber-100 bg-amber-50/70'}`}>
              <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${isDark ? 'bg-amber-400/15 text-amber-300' : 'bg-amber-50 text-amber-700'}`}><KeyRound size={17} /></span>
              <div>
                <div className={`text-xs font-bold ${isDark ? 'text-white/85' : 'text-slate-800'}`}>{isZh ? '保护你的登录入口' : 'Protect your login'}</div>
                <p className={`mt-1 text-[11px] leading-relaxed ${isDark ? 'text-white/45' : 'text-slate-500'}`}>{isZh ? '不修改密码时全部密码框留空；建议为管理员开启 MFA，降低凭据泄露后的风险。' : 'Leave all password fields empty when you do not want to change the password. MFA is recommended for administrators.'}</p>
              </div>
            </div>
            <div>
            <label className={`block text-[10px] font-bold uppercase tracking-widest mb-1.5 ${isDark ? 'text-white/55' : 'text-black/45'}`}>
              {language === 'zh' ? '当前密码' : 'Current Password'}
            </label>
            <div className="relative">
              <input
                type={showProfilePwd ? 'text' : 'password'}
                value={profileForm.oldPassword || ''}
                onChange={(event) => onProfileFormChange((prev) => ({ ...prev, oldPassword: event.target.value }))}
                title="Current password"
                placeholder={language === 'zh' ? '修改密码前请先验证当前密码' : 'Enter current password to change'}
                className={`w-full rounded-xl px-3 pr-10 py-2.5 text-sm outline-none border transition-all ${isDark ? 'bg-white/5 border-white/15 text-white placeholder-white/30 focus:border-[#00bceb]/60' : 'bg-black/[0.02] border-black/10 text-[#0b2a3c] placeholder-black/30 focus:border-[#00bceb]/50'}`}
              />
              <button type="button" tabIndex={-1} title={showProfilePwd ? '隐藏' : '显示'} onClick={onToggleProfilePassword} className={`absolute right-3 top-1/2 -translate-y-1/2 ${isDark ? 'text-white/40 hover:text-white/70' : 'text-black/35 hover:text-black/60'}`}>
                {showProfilePwd ? <EyeOff size={15} /> : <Eye size={15} />}
              </button>
            </div>
          </div>

          <div>
            <label className={`block text-[10px] font-bold uppercase tracking-widest mb-1.5 ${isDark ? 'text-white/55' : 'text-black/45'}`}>
              {language === 'zh' ? '新密码' : 'New Password'}
            </label>
            <div className="relative">
              <input
                type={showProfilePwd ? 'text' : 'password'}
                value={profileForm.password}
                onChange={(event) => onProfileFormChange((prev) => ({ ...prev, password: event.target.value }))}
                title="New password"
                placeholder={language === 'zh' ? '留空则保持原密码不变' : 'Leave empty to keep current password'}
                className={`w-full rounded-xl px-3 pr-10 py-2.5 text-sm outline-none border transition-all ${isDark ? 'bg-white/5 border-white/15 text-white placeholder-white/30 focus:border-[#00bceb]/60' : 'bg-black/[0.02] border-black/10 text-[#0b2a3c] placeholder-black/30 focus:border-[#00bceb]/50'}`}
              />
              <button type="button" tabIndex={-1} title={showProfilePwd ? '隐藏密码' : '显示密码'} onClick={onToggleProfilePassword} className={`absolute right-3 top-1/2 -translate-y-1/2 ${isDark ? 'text-white/40 hover:text-white/70' : 'text-black/35 hover:text-black/60'}`}>
                {showProfilePwd ? <EyeOff size={15} /> : <Eye size={15} />}
              </button>
            </div>
          </div>

          <div>
            <label className={`block text-[10px] font-bold uppercase tracking-widest mb-1.5 ${isDark ? 'text-white/55' : 'text-black/45'}`}>
              {language === 'zh' ? '确认新密码' : 'Confirm New Password'}
            </label>
            <input
              type={showProfilePwd ? 'text' : 'password'}
              value={profileForm.confirmPassword}
              onChange={(event) => onProfileFormChange((prev) => ({ ...prev, confirmPassword: event.target.value }))}
              title="Confirm password"
              placeholder={language === 'zh' ? '请再次输入新密码' : 'Confirm new password'}
              aria-invalid={Boolean(passwordConfirmationError)}
              aria-describedby={passwordConfirmationError ? 'profile-confirm-password-error' : undefined}
              className={`w-full rounded-xl px-3 py-2.5 text-sm outline-none border transition-all ${passwordConfirmationError ? (isDark ? 'bg-rose-500/5 border-rose-400/70 text-white placeholder-white/30 focus:border-rose-400' : 'bg-rose-50/60 border-rose-300 text-[#0b2a3c] placeholder-black/30 focus:border-rose-500') : isDark ? 'bg-white/5 border-white/15 text-white placeholder-white/30 focus:border-[#00bceb]/60' : 'bg-black/[0.02] border-black/10 text-[#0b2a3c] placeholder-black/30 focus:border-[#00bceb]/50'}`}
            />
            {passwordConfirmationError && (
              <p id="profile-confirm-password-error" role="alert" className={`mt-1.5 flex items-center gap-1 text-[11px] font-semibold ${isDark ? 'text-rose-300' : 'text-rose-600'}`}>
                <Info size={12} />
                {passwordConfirmationError}
              </p>
            )}
          </div>

          {(currentRole === 'Administrator' || currentRole === 'admin') && (
            <div className={`rounded-2xl border p-5 ${isDark ? 'bg-orange-500/5 border-orange-500/20' : 'bg-orange-50/80 border-orange-200'}`}>
              <div className="flex items-center gap-2 mb-3">
                <Shield size={16} className={isDark ? 'text-orange-400' : 'text-orange-600'} />
                <span className={`text-[11px] font-bold uppercase tracking-widest ${isDark ? 'text-orange-400' : 'text-orange-700'}`}>
                  MFA 双人审批固定安全码 (Fixed PIN)
                </span>
              </div>
              <div className="relative">
                <input
                  type={showFixedPin ? 'text' : 'password'}
                  maxLength={6}
                  value={profileForm.fixedPin || ''}
                  onChange={(event) => onProfileFormChange((prev) => ({ ...prev, fixedPin: event.target.value.replace(/\D/g, '') }))}
                  title="Fixed PIN for MFA"
                  placeholder="6位数字密码 (留空保持不变)"
                  className={`w-full rounded-xl px-3 pr-10 py-2.5 text-lg font-black tracking-widest outline-none border transition-all ${isDark ? 'bg-black/20 border-orange-500/30 text-white placeholder-white/20 focus:border-orange-500/60' : 'bg-white border-orange-300 text-orange-900 placeholder-black/20 focus:border-orange-500/60'}`}
                />
                <button type="button" tabIndex={-1} title={showFixedPin ? '隐藏' : '显示'} onClick={() => setShowFixedPin(!showFixedPin)} className={`absolute right-3 top-1/2 -translate-y-1/2 ${isDark ? 'text-white/40 hover:text-white/70' : 'text-orange-500 hover:text-orange-700'}`}>
                  {showFixedPin ? <EyeOff size={15} /> : <Eye size={15} />}
                </button>
              </div>
              <p className={`text-[10px] mt-2 leading-relaxed ${isDark ? 'text-orange-300/60' : 'text-orange-800/70'}`}>
                该密码用于特权终端登录的 MFA 二步验证。由于采取加密存储，仅在发起验证时比对。请妥善保管。
                {mfaActive && (
                  <span className="block mt-1 text-[#06b6d4] font-semibold">
                    提示：由于您已开启“MFA 双因子二次身份认证”，在特权登录或双人审批时，固定安全码将自动升级为使用您的手机 App 动态验证码进行验证。
                  </span>
                )}
              </p>
            </div>
          )}

          {/* MFA (Multi-Factor Authentication) optional card */}
          <div className={`rounded-2xl border p-5 ${isDark ? 'bg-cyan-500/5 border-cyan-500/20' : 'bg-cyan-50/80 border-cyan-200'}`}>
            <div className="flex items-center gap-2 mb-3">
              <Shield size={16} className={isDark ? 'text-cyan-400' : 'text-cyan-600'} />
              <span className={`text-[11px] font-bold uppercase tracking-widest ${isDark ? 'text-cyan-400' : 'text-cyan-700'}`}>
                {language === 'zh' ? 'MFA 双因子二次身份认证' : 'MFA Multi-Factor Authentication'}
              </span>
            </div>
            <p className={`mb-3 rounded-xl border px-3 py-2 text-[10px] leading-relaxed ${isDark ? 'border-cyan-500/15 bg-cyan-500/5 text-white/55' : 'border-cyan-200 bg-white/70 text-slate-500'}`}>
              {language === 'zh'
                ? '兼容标准 TOTP 的验证器，包括 Google Authenticator、Microsoft Authenticator，以及支持标准 TOTP 的腾讯/阿里等国产验证器。每位管理员使用自己的绑定密钥。'
                : 'Compatible with standard TOTP authenticators, including Google Authenticator, Microsoft Authenticator, and domestic apps that support TOTP. Each administrator uses their own secret.'}
            </p>
            {!mfaActive ? (
              // MFA not enabled
              !setupMode ? (
                <div>
                  <p className={`text-[11px] mb-3 leading-relaxed ${isDark ? 'text-white/50' : 'text-black/60'}`}>
                    开启二次认证后，登录系统时不仅需要输入密码，还需要输入手机身份验证器生成的 6 位动态验证码，极大地保护账号安全免受密码泄露威胁。
                  </p>
                  <button
                    type="button"
                    disabled={mfaLoading}
                    onClick={handleStartSetup}
                    className="px-3.5 py-1.5 rounded-lg text-xs font-semibold text-white bg-cyan-600 hover:bg-cyan-700 transition-colors shadow-sm"
                  >
                    {mfaLoading ? '初始化中...' : '配置并启用二次认证'}
                  </button>
                  {mfaErrorMsg && <p className="mt-2 text-xs text-red-500">{mfaErrorMsg}</p>}
                </div>
              ) : (
                // Setup MFA (Scan QR Code)
                <div className="space-y-4">
                  <p className={`text-[11px] leading-relaxed ${isDark ? 'text-white/60' : 'text-black/70'}`}>
                    1. 请使用手机下载并打开 <strong>谷歌身份验证器 (Google Authenticator)</strong> 或其他支持 TOTP 算法的认证 App。<br />
                    2. 扫描下方二维码，或手动输入下面的密钥添加账户。
                  </p>
                  
                  <div className="flex flex-col sm:flex-row items-center gap-4 py-2">
                    <div className="p-3 bg-white rounded-xl shadow-inner flex items-center justify-center border border-black/5">
                      <QRCode value={mfaQrUri} size={130} />
                    </div>
                    <div className="flex-1 space-y-2 text-center sm:text-left">
                      <div>
                        <span className={`text-[10px] uppercase font-bold tracking-wider block ${isDark ? 'text-white/40' : 'text-black/40'}`}>密钥 (Secret Key)</span>
                        <code className={`text-xs font-mono font-bold block px-2.5 py-1 rounded bg-black/10 select-all border ${isDark ? 'border-white/5 text-cyan-300' : 'border-black/5 text-cyan-700'}`}>{mfaSecret}</code>
                      </div>
                      <p className={`text-[10px] ${isDark ? 'text-white/30' : 'text-black/40'}`}>请妥善保管此密钥，一旦丢失将无法找回账户。</p>
                    </div>
                  </div>

                  <div className="space-y-2 border-t pt-3" style={{ borderColor: 'var(--card-border)' }}>
                    <label className={`block text-[10px] font-bold uppercase tracking-wider ${isDark ? 'text-white/60' : 'text-black/60'}`}>
                      3. 输入手机上显示的 6 位动态验证码进行验证：
                    </label>
                    <div className="flex gap-3">
                      <input
                        type="text"
                        maxLength={6}
                        placeholder="000000"
                        value={mfaCodeInput}
                        onChange={(e) => setMfaCodeInput(e.target.value.replace(/\D/g, ''))}
                        className={`w-32 rounded-lg px-3 py-2 text-sm font-bold tracking-[0.2em] outline-none border transition-all ${isDark ? 'bg-black/20 border-white/10 text-white placeholder-white/20 focus:border-cyan-500/50' : 'bg-white border-black/10 text-black placeholder-black/20 focus:border-cyan-500/40'}`}
                      />
                      <button
                        type="button"
                        disabled={mfaLoading || mfaCodeInput.length < 6}
                        onClick={handleEnableMfa}
                        className="px-4 py-2 rounded-lg text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      >
                        {mfaLoading ? '验证中...' : '绑定并开启'}
                      </button>
                      <button
                        type="button"
                        onClick={() => { setSetupMode(false); setMfaCodeInput(''); setMfaErrorMsg(''); }}
                        className={`px-3 py-2 rounded-lg text-xs font-medium transition-colors ${isDark ? 'bg-white/10 text-white/80 hover:bg-white/15' : 'bg-black/[0.05] text-black/70 hover:bg-black/[0.08]'}`}
                      >
                        取消
                      </button>
                    </div>
                    {mfaErrorMsg && <p className="text-xs text-red-500 mt-1">{mfaErrorMsg}</p>}
                  </div>
                </div>
              )
            ) : (
              // MFA enabled
              !disableMode ? (
                <div className="flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-1.5 text-emerald-500 font-bold text-xs">
                      <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
                      二次认证 (MFA) 已启用保护中
                    </div>
                    <p className={`text-[10px] mt-1 ${isDark ? 'text-white/30' : 'text-black/40'}`}>
                      每次登录系统均需输入手机身份验证器生成的动态验证码。
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => { setDisableMode(true); setMfaErrorMsg(''); }}
                    className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${isDark ? 'bg-red-500/15 text-red-300 hover:bg-red-500/20' : 'bg-red-50 text-red-600 hover:bg-red-100'}`}
                  >
                    关闭二次认证
                  </button>
                </div>
              ) : (
                // Confirm Disable MFA (Verify Password)
                <div className="space-y-3">
                  <label className={`block text-[10px] font-bold uppercase tracking-wider ${isDark ? 'text-white/60' : 'text-black/60'}`}>
                    请输入当前登录密码确认关闭二次身份验证：
                  </label>
                  <div className="flex gap-3 items-center">
                    <div className="relative flex-1">
                      <input
                        type={showDisablePassword ? 'text' : 'password'}
                        placeholder="您的登录密码"
                        value={disablePasswordInput}
                        onChange={(e) => setDisablePasswordInput(e.target.value)}
                        className={`w-full rounded-lg px-3 py-2 pr-9 text-xs outline-none border transition-all ${isDark ? 'bg-black/20 border-white/10 text-white placeholder-white/20 focus:border-cyan-500/50' : 'bg-white border-black/10 text-black placeholder-black/20 focus:border-cyan-500/40'}`}
                      />
                      <button
                        type="button"
                        onClick={() => setShowDisablePassword(!showDisablePassword)}
                        className={`absolute right-2.5 top-1/2 -translate-y-1/2 p-0.5 focus:outline-none ${isDark ? 'text-white/25 hover:text-white/50' : 'text-black/25 hover:text-black/50'}`}
                      >
                        {showDisablePassword ? <EyeOff size={14} /> : <Eye size={14} />}
                      </button>
                    </div>
                    <button
                      type="button"
                      disabled={mfaLoading || !disablePasswordInput}
                      onClick={handleDisableMfa}
                      className="px-4 py-2 rounded-lg text-xs font-semibold text-white bg-red-600 hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      {mfaLoading ? '验证中...' : '确认关闭'}
                    </button>
                    <button
                      type="button"
                      onClick={() => { setDisableMode(false); setDisablePasswordInput(''); setShowDisablePassword(false); setMfaErrorMsg(''); }}
                      className={`px-3 py-2 rounded-lg text-xs font-medium transition-colors ${isDark ? 'bg-white/10 text-white/80 hover:bg-white/15' : 'bg-black/[0.05] text-black/70 hover:bg-black/[0.08]'}`}
                    >
                      取消
                    </button>
                  </div>
                  {mfaErrorMsg && <p className="text-xs text-red-500">{mfaErrorMsg}</p>}
                </div>
              )
            )}
          </div>

          </div>

          <div className={wizardStep === 2 ? 'space-y-4' : 'hidden'}>
            <div className={`flex items-start gap-3 rounded-2xl border p-4 ${isDark ? 'border-blue-400/15 bg-blue-400/5' : 'border-blue-100 bg-blue-50/70'}`}>
              <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${isDark ? 'bg-blue-400/15 text-blue-300' : 'bg-blue-50 text-blue-700'}`}><Bell size={17} /></span>
              <div>
                <div className={`text-xs font-bold ${isDark ? 'text-white/85' : 'text-slate-800'}`}>{isZh ? '把重要告警送到你常用的群' : 'Send important alerts to your team'}</div>
                <p className={`mt-1 text-[11px] leading-relaxed ${isDark ? 'text-white/45' : 'text-slate-500'}`}>{isZh ? '告警通知是可选项，不配置也不影响登录和设备访问。填入地址后先发送测试消息，确认成功再保存。' : 'Alert delivery is optional and does not affect login or device access. Send a test message after entering a URL before saving.'}</p>
              </div>
            </div>
            <div className={`pt-3 border-t ${isDark ? 'border-white/10' : 'border-black/8'}`}>
            <div className="flex items-center gap-2 mb-1">
              <Bell size={13} className={isDark ? 'text-[#00bceb]' : 'text-[#008bb0]'} />
              <span className={`text-[10px] font-bold uppercase tracking-widest ${isDark ? 'text-white/55' : 'text-black/45'}`}>
                告警通知渠道
              </span>
            </div>
            <p className={`text-[11px] mb-3 leading-relaxed ${isDark ? 'text-white/30' : 'text-black/35'}`}>
              接收接口 DOWN、带宽超阈值等网络告警推送。<br />
              开启后填入 Webhook 地址，点击「发送测试消息」验证连通性，确认无误后保存。
            </p>

            {channels.map(({ key, label, sub, icon, iconBg, badge, hint, hasSecret, docsUrl, docsLabel, tip }) => {
              const channel = notificationChannels[key];
              const isEnabled = channel.enabled;
              const isCreator = !channel.creator_username || channel.creator_username === profileForm.username;

              return (
                <div
                  key={key}
                  className={`mb-2.5 rounded-xl border overflow-hidden transition-all ${
                    isEnabled
                      ? (isDark ? 'border-[#00bceb]/25 bg-[#00bceb]/[0.04]' : 'border-[#00bceb]/30 bg-[#00bceb]/[0.03]')
                      : (isDark ? 'border-white/8 bg-transparent' : 'border-black/6 bg-transparent')
                  }`}
                >
                  <div className="flex items-center gap-2.5 px-3 py-2.5">
                    <span className={`w-7 h-7 rounded-lg ${iconBg} flex items-center justify-center text-[9px] font-black text-white shrink-0 shadow-sm`}>
                      {icon}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className={`text-[12px] font-semibold ${isDark ? 'text-white/85' : 'text-black/75'}`}>{label}</span>
                        <span className={`text-[9px] font-medium px-1.5 py-0.5 rounded-full ${badge}`}>{sub}</span>
                      </div>
                    </div>
                    <a
                      href={docsUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={`text-[10px] shrink-0 mr-1 ${isDark ? 'text-white/25 hover:text-[#00bceb]' : 'text-black/30 hover:text-[#008bb0]'} transition-colors`}
                    >
                      {docsLabel}
                    </a>
                    <button
                      type="button"
                      title={!isCreator ? `仅创建者 ${channel.creator_username} 有权操作` : (isEnabled ? '关闭此渠道' : '开启此渠道')}
                      disabled={!isCreator}
                      onClick={() => onNotificationChannelToggle(key)}
                      className={`relative w-9 h-5 rounded-full transition-colors shrink-0 ${!isCreator ? 'opacity-30 cursor-not-allowed bg-gray-500/30' : (isEnabled ? 'bg-[#00bceb]' : (isDark ? 'bg-white/15' : 'bg-black/12'))}`}
                    >
                      <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all ${isEnabled ? 'left-[18px]' : 'left-0.5'}`} />
                    </button>
                  </div>

                  <div className="px-3 pb-3 flex flex-col gap-1.5">
                    <p className={`text-[10px] leading-relaxed ${isDark ? 'text-white/30' : 'text-black/35'}`}>{tip}</p>
                    <input
                      type="text"
                      disabled={!isCreator}
                      value={channel.webhook_url}
                      onChange={(event) => onNotificationWebhookChange(key, event.target.value)}
                      title={`${label} Webhook URL`}
                      placeholder={hint}
                      className={`w-full rounded-lg px-2.5 py-2 text-[11px] outline-none border transition-all font-mono ${!isCreator ? (isDark ? 'bg-black/40 text-white/30 cursor-not-allowed border-white/5' : 'bg-black/[0.04] text-black/30 cursor-not-allowed border-black/5') : (isDark ? 'bg-black/20 border-white/10 text-white/80 placeholder-white/20 focus:border-[#00bceb]/50' : 'bg-white/60 border-black/8 text-[#0b2a3c] placeholder-black/20 focus:border-[#00bceb]/40')}`}
                    />
                    {!isCreator ? (
                      <p className={`text-[9px] font-sans ${isDark ? 'text-red-400/70' : 'text-red-500/70'}`}>
                        🔒 仅创建者（{channel.creator_username}）有权修改与启闭。
                      </p>
                    ) : (
                      (channel.webhook_url.includes('***') || channel.webhook_url.includes('****')) && (
                        <p className={`text-[9px] font-sans ${isDark ? 'text-[#00bceb]/70' : 'text-[#007fa3]'}`}>
                          ℹ 已加密。如需更换，请直接输入新的 Webhook 地址并保存。
                        </p>
                      )
                    )}
                    {hasSecret && (
                      <>
                        <div className="relative">
                          <input
                            type={showDingtalkSecret ? 'text' : 'password'}
                            disabled={!isCreator}
                            value={notificationChannels.dingtalk.secret}
                            onChange={(event) => onNotificationSecretChange(event.target.value)}
                            title={`${label} Secret`}
                            placeholder="加签 Secret（可选，留空则不验签）"
                            className={`w-full rounded-lg px-2.5 py-2 pr-8 text-[11px] outline-none border transition-all font-mono ${!isCreator ? (isDark ? 'bg-black/40 text-white/30 cursor-not-allowed border-white/5' : 'bg-black/[0.04] text-black/30 cursor-not-allowed border-black/5') : (isDark ? 'bg-black/20 border-white/10 text-white/80 placeholder-white/20 focus:border-[#00bceb]/50' : 'bg-white/60 border-black/8 text-[#0b2a3c] placeholder-black/20 focus:border-[#00bceb]/40')}`}
                          />
                          {isCreator && (
                            <button
                              type="button"
                              onClick={() => setShowDingtalkSecret(!showDingtalkSecret)}
                              className={`absolute right-2.5 top-1/2 -translate-y-1/2 p-0.5 focus:outline-none ${isDark ? 'text-white/25 hover:text-white/50' : 'text-black/25 hover:text-black/50'}`}
                            >
                              {showDingtalkSecret ? <EyeOff size={14} /> : <Eye size={14} />}
                            </button>
                          )}
                        </div>
                        {isCreator && notificationChannels.dingtalk.secret === '***' && (
                          <p className={`text-[9px] font-sans ${isDark ? 'text-[#00bceb]/70' : 'text-[#007fa3]'}`}>
                            ℹ 密钥已加密。如需更换，请直接输入新密钥。
                          </p>
                        )}
                      </>
                    )}
                    <button
                      type="button"
                      title={`向 ${label} 发送测试告警`}
                      disabled={!channel.webhook_url.trim() || notifyTestLoading === key || !isCreator}
                      onClick={() => onTestNotificationChannel(key)}
                      className={`w-full py-1.5 rounded-lg text-[11px] font-semibold transition-all flex items-center justify-center gap-1.5 ${
                        !channel.webhook_url.trim() || notifyTestLoading === key || !isCreator
                          ? (isDark ? 'bg-white/5 text-white/20 cursor-not-allowed' : 'bg-black/4 text-black/20 cursor-not-allowed')
                          : (isDark ? 'bg-[#00bceb]/12 text-[#00bceb] hover:bg-[#00bceb]/22 border border-[#00bceb]/20' : 'bg-[#e8f9ff] text-[#007fa3] hover:bg-[#d2f2fd] border border-[#00bceb]/20')
                      }`}
                    >
                      {notifyTestLoading === key
                        ? <><span className="w-3 h-3 border border-current border-t-transparent rounded-full animate-spin" />发送中...</>
                        : '📨 发送测试消息'}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>

          </div>

          <div className={wizardStep === 3 ? 'space-y-4' : 'hidden'}>
            <div className={`pt-3 border-t ${isDark ? 'border-white/10' : 'border-black/8'}`}>
              <div className="flex items-start gap-3">
                <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${isDark ? 'bg-cyan-400/15 text-cyan-300' : 'bg-cyan-50 text-cyan-700'}`}><MonitorSpeaker size={17} /></span>
                <div>
                  <div className={`text-xs font-bold ${isDark ? 'text-white/85' : 'text-slate-800'}`}>{isZh ? '配置本机如何打开设备终端' : 'Choose how this workstation opens terminals'}</div>
                  <p className={`mt-1 text-[11px] leading-relaxed ${isDark ? 'text-white/45' : 'text-slate-500'}`}>{isZh ? '这里的路径指当前电脑上的程序，不是远程设备路径。没有桌面客户端时，直接使用推荐的系统 SSH。' : 'The path below belongs to this workstation, not the remote device. If you do not have a desktop client, use the recommended System SSH option.'}</p>
                </div>
              </div>
            </div>

            <div className={`rounded-2xl border p-4 ${isDark ? 'border-cyan-400/15 bg-cyan-400/5' : 'border-cyan-100 bg-cyan-50/45'}`}>
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="flex gap-2">
                  <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-black ${isDark ? 'bg-cyan-300 text-slate-950' : 'bg-cyan-600 text-white'}`}>1</span>
                  <div>
                    <div className={`text-[11px] font-bold ${isDark ? 'text-white/80' : 'text-slate-700'}`}>{isZh ? '选启动方式' : 'Choose a launcher'}</div>
                    <p className={`mt-0.5 text-[10px] leading-relaxed ${isDark ? 'text-white/40' : 'text-slate-500'}`}>{isZh ? '推荐系统 SSH，免填路径。' : 'System SSH is recommended; no path needed.'}</p>
                  </div>
                </div>
                <div className="flex gap-2">
                  <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-black ${isDark ? 'bg-cyan-300 text-slate-950' : 'bg-cyan-600 text-white'}`}>2</span>
                  <div>
                    <div className={`text-[11px] font-bold ${isDark ? 'text-white/80' : 'text-slate-700'}`}>{isZh ? '只选客户端时填路径' : 'Add a path for desktop clients'}</div>
                    <p className={`mt-0.5 text-[10px] leading-relaxed ${isDark ? 'text-white/40' : 'text-slate-500'}`}>{isZh ? '路径必须是本机 exe 文件。' : 'Use the local client executable path.'}</p>
                  </div>
                </div>
                <div className="flex gap-2">
                  <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-black ${isDark ? 'bg-cyan-300 text-slate-950' : 'bg-cyan-600 text-white'}`}>3</span>
                  <div>
                    <div className={`text-[11px] font-bold ${isDark ? 'text-white/80' : 'text-slate-700'}`}>{isZh ? '下载并运行 Agent' : 'Run the local Agent'}</div>
                    <p className={`mt-0.5 text-[10px] leading-relaxed ${isDark ? 'text-white/40' : 'text-slate-500'}`}>{isZh ? 'Agent 负责把浏览器请求交给本机程序。' : 'The Agent hands browser requests to local apps.'}</p>
                  </div>
                </div>
              </div>
            </div>

            <div className={`p-4 rounded-xl border ${isDark ? 'bg-white/[0.02] border-white/10' : 'bg-black/[0.01] border-black/5'}`}>
              <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-4 sm:flex-row">
                  <div className="w-full sm:w-1/3">
                    <label className={`block text-[10px] font-bold uppercase tracking-widest mb-2 ${isDark ? 'text-white/40' : 'text-black/40'}`}>{isZh ? '启动方式' : 'Launch method'}</label>
                    <select 
                      value={terminalApp}
                      onChange={e => {
                        const val = e.target.value;
                        setTerminalApp(val);
                        localStorage.setItem('terminal_app', val);
                      }}
                      className={`w-full px-3 py-2 rounded-lg text-xs outline-none border transition-all ${isDark ? 'bg-black/20 border-white/10 text-white focus:border-cyan-500/50' : 'bg-white border-black/10 text-black focus:border-cyan-500/40'}`}
                    >
                      <option value="standard">{isZh ? '系统 SSH（推荐，无需路径）' : 'System SSH (recommended)'}</option>
                      <option value="xshell">Xshell</option>
                      <option value="putty">PuTTY</option>
                      <option value="securecrt">SecureCRT</option>
                      <option value="mobaxterm">MobaXterm</option>
                    </select>
                  </div>
                  <div className="flex-1">
                    <label className={`block text-[10px] font-bold uppercase tracking-widest mb-2 ${isDark ? 'text-white/40' : 'text-black/40'}`}>{isZh ? '客户端程序路径（仅本机）' : 'Client path (this workstation)'}</label>
                    <div className="flex gap-2">
                      <div className="relative flex-1">
                        <Terminal size={14} className={`absolute left-3 top-1/2 -translate-y-1/2 ${isDark ? 'text-white/20' : 'text-black/20'}`} />
                        <input 
                          type="text"
                          disabled={terminalApp === 'standard'}
                          value={localTerminalPath}
                          onChange={e => {
                            const val = e.target.value;
                            setLocalTerminalPath(val);
                            localStorage.setItem('local_terminal_path', val);
                          }}
                          placeholder={terminalApp === 'standard' ? (isZh ? '系统 SSH 不需要填写' : 'Not needed for System SSH') : (isZh ? '例如 C:\\Program Files\\...\\Xshell.exe' : 'e.g. C:\\Program Files\\...\\Xshell.exe')}
                          className={`w-full pl-9 pr-3 py-2 rounded-lg text-xs outline-none border transition-all ${terminalApp === 'standard' ? 'opacity-40 cursor-not-allowed bg-black/5' : (isDark ? 'bg-black/20 border-white/10 text-white placeholder-white/30 focus:border-cyan-500/50' : 'bg-white border-black/10 text-black placeholder-black/20 focus:border-cyan-500/40')}`}
                        />
                      </div>
                      {terminalApp !== 'standard' && (
                        <div className="relative">
                          <button
                            type="button"
                            onClick={() => setShowPathSuggestions(v => !v)}
                            className={`px-3 py-2 rounded-lg text-[11px] font-bold flex items-center gap-1.5 transition-all bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 hover:bg-cyan-500/20 shadow-sm`}
                          >
                            <MonitorSpeaker size={14} />
                            {isZh ? '选择常见路径' : 'Choose a common path'}
                          </button>
                          {showPathSuggestions && (
                            <div className={`absolute right-0 top-full mt-1 z-50 w-96 rounded-xl border shadow-xl overflow-hidden ${isDark ? 'bg-[#0d1a2a] border-white/15' : 'bg-white border-black/10'}`}>
                              <div className={`px-3 py-2 border-b text-[10px] font-bold uppercase tracking-widest ${isDark ? 'border-white/10 text-white/40' : 'border-black/8 text-black/40'}`}>
                                {isZh ? '选择后请确认这是当前电脑上的路径' : 'Confirm the selected path belongs to this workstation'}
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
                                  className={`w-full text-left px-3 py-2 text-[11px] font-mono transition-colors ${isDark ? 'text-white/70 hover:bg-white/8' : 'text-black/70 hover:bg-black/5'}`}
                                >
                                  {p}
                                </button>
                              ))}
                              <div className={`px-3 py-2 border-t ${isDark ? 'border-white/10' : 'border-black/8'}`}>
                                <p className={`text-[10px] ${isDark ? 'text-white/30' : 'text-black/35'}`}>
                                  {language === 'zh'
                                    ? '也可以直接粘贴完整路径；服务器上的路径不能使用。'
                                    : 'Or paste the full path directly into the input box'}
                                </p>
                              </div>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
                
                <div className={`flex flex-col gap-3 rounded-xl border p-3 ${isDark ? 'border-cyan-500/15 bg-cyan-500/5' : 'border-cyan-500/10 bg-cyan-50/50'}`}>
                  <div>
                    <div className={`flex items-center gap-1.5 text-[11px] font-bold ${isDark ? 'text-white/75' : 'text-slate-700'}`}>
                      <Download size={13} className={isDark ? 'text-cyan-300' : 'text-cyan-600'} />
                      {isZh ? '还没有 Terminal Agent？先下载到当前工作站' : 'Need the Terminal Agent? Download it to this workstation'}
                    </div>
                    <p className={`mt-1 text-[10px] leading-relaxed ${isDark ? 'text-white/35' : 'text-slate-500'}`}>
                      {isZh ? '下载后运行 Agent，它只负责接收本机浏览器请求，不会把设备密码保存在本地。' : 'Run the Agent after downloading. It only receives browser requests on this workstation and does not store device passwords locally.'}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <ActionLink
                      href="/api/system/download-terminal-agent?platform=windows"
                      download="NexoraTerminalAgent.exe"
                      icon={Download}
                      variant="success"
                      size="sm"
                      className="!text-[11px]"
                    >
                      {isZh ? '下载 Windows Agent' : 'Download Windows Agent'}
                    </ActionLink>
                    <ActionLink
                      href="/api/system/download-terminal-agent?platform=ubuntu"
                      download="install-terminal-agent.sh"
                      icon={Download}
                      variant="accent"
                      size="sm"
                      className="!text-[11px]"
                    >
                      {isZh ? '下载 Ubuntu 安装脚本' : 'Download Ubuntu script'}
                    </ActionLink>
                  </div>
                </div>
                
                <p className={`text-[10px] leading-relaxed flex items-center gap-1.5 ${isDark ? 'text-white/30' : 'text-black/40'}`}>
                  <Info size={12} className="text-cyan-500" />
                  {terminalApp === 'standard' 
                    ? (isZh ? '当前选择系统 SSH：只需让 127.0.0.1:17890 的 Terminal Agent 运行，程序路径留空即可。' : 'System SSH selected: keep the Terminal Agent running at 127.0.0.1:17890; no program path is required.')
                    : (isZh ? '当前选择桌面客户端：Agent 会在本机启动上面填写的程序；路径必须指向当前电脑的 exe 文件。' : 'Desktop client selected: the Agent launches the program above; the path must point to an exe on this workstation.')}
                </p>
              </div>
            </div>
          </div>

          <p className={`text-[11px] ${isDark ? 'text-white/40' : 'text-black/40'}`}>上次登录时间：{currentUserLastLogin}</p>

          </div>

        <div className={`sticky bottom-0 flex gap-3 border-t bg-white/95 px-6 py-4 backdrop-blur ${isDark ? 'border-white/10 bg-[#121c2d]/95' : 'border-slate-200/80'}`}>
          <button type="button" onClick={wizardStep === 0 ? onClose : () => goToWizardStep(wizardStep - 1)} className={`flex-1 px-4 py-2.5 rounded-xl text-sm font-medium transition-all ${isDark ? 'bg-white/10 text-white/80 hover:bg-white/15' : 'bg-black/[0.04] text-black/70 hover:bg-black/[0.08]'}`}>
            {wizardStep === 0 ? (isZh ? '取消' : 'Cancel') : <><ChevronLeft size={15} className="mr-1 inline" />{isZh ? '上一步' : 'Back'}</>}
          </button>
          {wizardStep < wizardSteps.length - 1 ? (
            <button type="button" onClick={() => goToWizardStep(wizardStep + 1)} className="flex-1 px-4 py-2.5 rounded-xl text-sm font-semibold text-white bg-[#008bb0] hover:bg-[#00769a] transition-all shadow-lg shadow-[#00bceb]/20">
              {isZh ? '下一步' : 'Next'} <ChevronRight size={15} className="ml-1 inline" />
            </button>
          ) : (
            <button type="button" disabled={Boolean(passwordConfirmationError)} onClick={onSave} className={`flex-1 px-4 py-2.5 rounded-xl text-sm font-semibold text-white transition-all shadow-lg shadow-[#00bceb]/20 ${passwordConfirmationError ? 'cursor-not-allowed bg-slate-300 shadow-none' : 'bg-[#008bb0] hover:bg-[#00769a]'}`}>
              {isZh ? '保存个人设置' : 'Save settings'}
            </button>
          )}
          <button type="button" onClick={onClose} className={`hidden px-4 py-2.5 text-sm font-medium transition-all sm:block ${isDark ? 'text-white/50 hover:text-white/80' : 'text-slate-400 hover:text-slate-700'}`}>
            {isZh ? '退出' : 'Close'}
          </button>
        </div>
      </motion.div>
    </div>
  );
};

export default ProfileModal;
