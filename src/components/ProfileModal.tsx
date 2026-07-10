import React from 'react';
import { motion } from 'motion/react';
import { Bell, Eye, EyeOff, Terminal, MonitorSpeaker, Shield, Download, Lock, Info } from 'lucide-react';
import type { ThemeMode } from '../types';
import { useSystem } from '../hooks/useSystem';
import QRCode from 'react-qr-code';

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
  const [terminalApp, setTerminalApp] = React.useState(() => localStorage.getItem('terminal_app') || 'xshell');
  const [showFixedPin, setShowFixedPin] = React.useState(false);
  const [showPathSuggestions, setShowPathSuggestions] = React.useState(false);

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

  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-[70] p-4">
      <motion.div
        initial={{ opacity: 0, y: 12, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        className={`w-full max-w-2xl rounded-2xl border shadow-2xl overflow-hidden ${isDark ? 'bg-[#121c2d] border-white/10' : 'bg-white border-black/10'}`}
      >
        <div className={`px-6 py-4 border-b ${isDark ? 'border-white/10' : 'border-black/10'}`}>
          <h3 className={`text-lg font-bold ${isDark ? 'text-white/90' : 'text-[#0b2a3c]'}`}>个人信息</h3>
          <p className={`text-xs mt-1 ${isDark ? 'text-white/45' : 'text-black/45'}`}>管理您的账户个人信息</p>
        </div>

        <div className="px-6 py-5 space-y-4 max-h-[75vh] overflow-y-auto">
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

          <div className="grid grid-cols-3 gap-3">
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
              <button type="button" title={showProfilePwd ? '隐藏' : '显示'} onClick={onToggleProfilePassword} className={`absolute right-3 top-1/2 -translate-y-1/2 ${isDark ? 'text-white/40 hover:text-white/70' : 'text-black/35 hover:text-black/60'}`}>
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
              <button type="button" title={showProfilePwd ? '隐藏密码' : '显示密码'} onClick={onToggleProfilePassword} className={`absolute right-3 top-1/2 -translate-y-1/2 ${isDark ? 'text-white/40 hover:text-white/70' : 'text-black/35 hover:text-black/60'}`}>
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
              className={`w-full rounded-xl px-3 py-2.5 text-sm outline-none border transition-all ${isDark ? 'bg-white/5 border-white/15 text-white placeholder-white/30 focus:border-[#00bceb]/60' : 'bg-black/[0.02] border-black/10 text-[#0b2a3c] placeholder-black/30 focus:border-[#00bceb]/50'}`}
            />
          </div>

          {(currentRole === 'Administrator' || currentRole === 'admin') && (
            <div className={`p-4 rounded-xl border ${isDark ? 'bg-orange-500/5 border-orange-500/20' : 'bg-orange-50 border-orange-200'}`}>
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
                <button type="button" title={showFixedPin ? '隐藏' : '显示'} onClick={() => setShowFixedPin(!showFixedPin)} className={`absolute right-3 top-1/2 -translate-y-1/2 ${isDark ? 'text-white/40 hover:text-white/70' : 'text-orange-500 hover:text-orange-700'}`}>
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
          <div className={`p-4 rounded-xl border ${isDark ? 'bg-cyan-500/5 border-cyan-500/20' : 'bg-cyan-50 border-cyan-200'}`}>
            <div className="flex items-center gap-2 mb-3">
              <Shield size={16} className={isDark ? 'text-cyan-400' : 'text-cyan-600'} />
              <span className={`text-[11px] font-bold uppercase tracking-widest ${isDark ? 'text-cyan-400' : 'text-cyan-700'}`}>
                {language === 'zh' ? 'MFA 双因子二次身份认证' : 'MFA Multi-Factor Authentication'}
              </span>
            </div>
            
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

          <div className={`pt-3 border-t ${isDark ? 'border-white/10' : 'border-black/8'}`}>
            <div className="flex items-center gap-2 mb-1">
              <MonitorSpeaker size={13} className={isDark ? 'text-cyan-400' : 'text-cyan-600'} />
              <span className={`text-[10px] font-bold uppercase tracking-widest ${isDark ? 'text-white/55' : 'text-black/45'}`}>
                终端实验室 (Terminal Lab)
              </span>
            </div>
            <p className={`text-[11px] mb-3 leading-relaxed ${isDark ? 'text-white/30' : 'text-black/35'}`}>
              配置本地终端工具（Xshell/SecureCRT/Putty）的路径，实现从浏览器一键调起外部客户端。
            </p>

            <div className={`p-4 rounded-xl border ${isDark ? 'bg-white/[0.02] border-white/10' : 'bg-black/[0.01] border-black/5'}`}>
              <div className="flex flex-col gap-4">
                <div className="flex gap-4">
                  <div className="w-1/3">
                    <label className={`block text-[10px] font-bold uppercase tracking-widest mb-2 ${isDark ? 'text-white/40' : 'text-black/40'}`}>终端工具</label>
                    <select 
                      value={terminalApp}
                      onChange={e => {
                        const val = e.target.value;
                        setTerminalApp(val);
                        localStorage.setItem('terminal_app', val);
                      }}
                      className={`w-full px-3 py-2 rounded-lg text-xs outline-none border transition-all ${isDark ? 'bg-black/20 border-white/10 text-white focus:border-cyan-500/50' : 'bg-white border-black/10 text-black focus:border-cyan-500/40'}`}
                    >
                      <option value="standard">{language === 'zh' ? '系统默认 (ssh://)' : 'System Default'}</option>
                      <option value="xshell">Xshell</option>
                      <option value="putty">PuTTY</option>
                      <option value="securecrt">SecureCRT</option>
                      <option value="mobaxterm">MobaXterm</option>
                    </select>
                  </div>
                  <div className="flex-1">
                    <label className={`block text-[10px] font-bold uppercase tracking-widest mb-2 ${isDark ? 'text-white/40' : 'text-black/40'}`}>可执行程序绝对路径</label>
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
                          placeholder={terminalApp === 'standard' ? (language === 'zh' ? '标准模式无需路径' : 'No path needed') : (language === 'zh' ? '直接粘贴路径，或点击右侧「常用路径」' : 'Paste path here, or click Presets →')}
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
                            {language === 'zh' ? '常用路径' : 'Presets'}
                          </button>
                          {showPathSuggestions && (
                            <div className={`absolute right-0 top-full mt-1 z-50 w-96 rounded-xl border shadow-xl overflow-hidden ${isDark ? 'bg-[#0d1a2a] border-white/15' : 'bg-white border-black/10'}`}>
                              <div className={`px-3 py-2 border-b text-[10px] font-bold uppercase tracking-widest ${isDark ? 'border-white/10 text-white/40' : 'border-black/8 text-black/40'}`}>
                                {language === 'zh' ? '点击填入路径，再手动确认是否正确' : 'Click to fill — verify the path is correct'}
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
                                    ? '也可直接在输入框中粘贴完整路径'
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
                
                {terminalApp !== 'standard' && (
                  <div className={`flex justify-between items-center rounded-xl p-3 border ${isDark ? 'bg-cyan-500/5 border-cyan-500/15' : 'bg-cyan-50/50 border-cyan-500/10'}`}>
                    <span className={`text-[11px] ${isDark ? 'text-white/55' : 'text-black/60'}`}>
                      {language === 'zh' ? '需要 Windows 助手？下载自注册单文件版：' : 'Need Windows assistant? Download self-registering executable:'}
                    </span>
                    <a
                      href="/api/system/download-assistant"
                      download={systemInfo?.system_name ? `${systemInfo.system_name.toLowerCase()}_assistant.exe` : "nexora.exe"}
                      className={`px-3 py-1.5 rounded-lg text-[11px] font-bold flex items-center gap-1.5 transition-all bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 hover:bg-emerald-500/20 shadow-sm`}
                    >
                      <Download size={12} />
                      {language === 'zh' ? `下载 ${systemInfo?.system_name || 'Nexora'} 助手` : `Download ${systemInfo?.system_name || 'Nexora'} Assistant`}
                    </a>
                  </div>
                )}
                
                <p className={`text-[10px] leading-relaxed flex items-center gap-1.5 ${isDark ? 'text-white/30' : 'text-black/40'}`}>
                  <Info size={12} className="text-cyan-500" />
                  {terminalApp === 'standard' 
                    ? (language === 'zh' ? '标准模式：直接调用系统默认 SSH 处理器。' : 'Standard Mode: Calls OS default SSH handler.')
                    : (language === 'zh' ? '本地模式：直接通过后台启动程序，无需注册表脚本，安全快捷。' : 'Local Mode: Direct launch via backend, no scripts needed.')}
                </p>
              </div>
            </div>
          </div>

          <p className={`text-[11px] ${isDark ? 'text-white/40' : 'text-black/40'}`}>上次登录时间：{currentUserLastLogin}</p>
        </div>

        <div className={`px-6 py-4 border-t flex gap-3 ${isDark ? 'border-white/10' : 'border-black/10'}`}>
          <button onClick={onClose} className={`flex-1 px-4 py-2.5 rounded-xl text-sm font-medium transition-all ${isDark ? 'bg-white/10 text-white/80 hover:bg-white/15' : 'bg-black/[0.04] text-black/70 hover:bg-black/[0.08]'}`}>
            取消
          </button>
          <button onClick={onSave} className="flex-1 px-4 py-2.5 rounded-xl text-sm font-semibold text-white bg-[#008bb0] hover:bg-[#00769a] transition-all shadow-lg shadow-[#00bceb]/20">
            保存个人资料
          </button>
        </div>
      </motion.div>
    </div>
  );
};

export default ProfileModal;