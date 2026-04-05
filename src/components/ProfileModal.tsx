import React from 'react';
import { motion } from 'motion/react';
import { Bell, Eye, EyeOff } from 'lucide-react';
import type { ThemeMode } from '../types';

interface AvatarPreset {
  id: string;
  emoji: string;
  label: string;
  bgClass: string;
}

interface ProfileFormState {
  username: string;
  password: string;
  confirmPassword: string;
}

interface NotificationChannelsState {
  feishu: { webhook_url: string; enabled: boolean };
  dingtalk: { webhook_url: string; enabled: boolean; secret: string };
  wechat: { webhook_url: string; enabled: boolean };
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
}) => {
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
      tip: '在钉钉群 ➜ 群设置 ➜ 智能群助手 ➜ 添加机器人 ➜ 自定义。安全设置选「加签」时把密钥填入下方 Secret 栏；选「自定义关键词」时关键词填 Nexora 即可。',
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
        className={`w-full max-w-lg rounded-2xl border shadow-2xl overflow-hidden ${isDark ? 'bg-[#121c2d] border-white/10' : 'bg-white border-black/10'}`}
      >
        <div className={`px-6 py-4 border-b ${isDark ? 'border-white/10' : 'border-black/10'}`}>
          <h3 className={`text-lg font-bold ${isDark ? 'text-white/90' : 'text-[#0b2a3c]'}`}>Profile</h3>
          <p className={`text-xs mt-1 ${isDark ? 'text-white/45' : 'text-black/45'}`}>Manage your account information</p>
        </div>

        <div className="px-6 py-5 space-y-4 max-h-[75vh] overflow-y-auto">
          <div>
            <label className={`block text-[10px] font-bold uppercase tracking-widest mb-1.5 ${isDark ? 'text-white/55' : 'text-black/45'}`}>Avatar</label>
            <div className="flex items-center gap-3">
              <div className={`w-14 h-14 rounded-full border overflow-hidden flex items-center justify-center ${isDark ? 'bg-white/10 border-white/10 text-white/75' : 'bg-black/10 border-black/10 text-black/60'}`}>
                {renderAvatarContent(profileAvatarPreview, 24)}
              </div>
              <div className="flex gap-2">
                <label className={`px-3 py-1.5 rounded-lg text-xs font-semibold cursor-pointer transition-all ${isDark ? 'bg-white/10 text-white/80 hover:bg-white/15' : 'bg-black/[0.05] text-black/70 hover:bg-black/[0.08]'}`}>
                  Upload
                  <input type="file" accept="image/*" className="hidden" onChange={onAvatarFileChange} />
                </label>
                <button type="button" onClick={onClearAvatar} className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${isDark ? 'bg-red-500/15 text-red-300 hover:bg-red-500/20' : 'bg-red-50 text-red-600 hover:bg-red-100'}`}>
                  Use Default
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
            <p className={`text-[10px] mt-1.5 ${isDark ? 'text-white/35' : 'text-black/35'}`}>Supports PNG/JPG/WebP, max 2MB. Stored in your user profile.</p>
          </div>

          <div>
            <label className={`block text-[10px] font-bold uppercase tracking-widest mb-1.5 ${isDark ? 'text-white/55' : 'text-black/45'}`}>Username</label>
            <input
              type="text"
              value={profileForm.username}
              onChange={(event) => onProfileFormChange((prev) => ({ ...prev, username: event.target.value }))}
              title="Profile username"
              placeholder="Username"
              className={`w-full rounded-xl px-3 py-2.5 text-sm outline-none border transition-all ${isDark ? 'bg-white/5 border-white/15 text-white placeholder-white/30 focus:border-[#00bceb]/60' : 'bg-black/[0.02] border-black/10 text-[#0b2a3c] placeholder-black/30 focus:border-[#00bceb]/50'}`}
            />
          </div>

          <div>
            <label className={`block text-[10px] font-bold uppercase tracking-widest mb-1.5 ${isDark ? 'text-white/55' : 'text-black/45'}`}>Role</label>
            <input
              type="text"
              value={currentRole}
              disabled
              title="Profile role"
              className={`w-full rounded-xl px-3 py-2.5 text-sm border ${isDark ? 'bg-white/5 border-white/10 text-white/60' : 'bg-black/[0.03] border-black/10 text-black/55'}`}
            />
          </div>

          <div>
            <label className={`block text-[10px] font-bold uppercase tracking-widest mb-1.5 ${isDark ? 'text-white/55' : 'text-black/45'}`}>New Password</label>
            <div className="relative">
              <input
                type={showProfilePwd ? 'text' : 'password'}
                value={profileForm.password}
                onChange={(event) => onProfileFormChange((prev) => ({ ...prev, password: event.target.value }))}
                title="New password"
                placeholder="Leave blank to keep unchanged"
                className={`w-full rounded-xl px-3 pr-10 py-2.5 text-sm outline-none border transition-all ${isDark ? 'bg-white/5 border-white/15 text-white placeholder-white/30 focus:border-[#00bceb]/60' : 'bg-black/[0.02] border-black/10 text-[#0b2a3c] placeholder-black/30 focus:border-[#00bceb]/50'}`}
              />
              <button type="button" title={showProfilePwd ? 'Hide password' : 'Show password'} onClick={onToggleProfilePassword} className={`absolute right-3 top-1/2 -translate-y-1/2 ${isDark ? 'text-white/40 hover:text-white/70' : 'text-black/35 hover:text-black/60'}`}>
                {showProfilePwd ? <EyeOff size={15} /> : <Eye size={15} />}
              </button>
            </div>
          </div>

          <div>
            <label className={`block text-[10px] font-bold uppercase tracking-widest mb-1.5 ${isDark ? 'text-white/55' : 'text-black/45'}`}>Confirm Password</label>
            <input
              type={showProfilePwd ? 'text' : 'password'}
              value={profileForm.confirmPassword}
              onChange={(event) => onProfileFormChange((prev) => ({ ...prev, confirmPassword: event.target.value }))}
              title="Confirm password"
              placeholder="Confirm new password"
              className={`w-full rounded-xl px-3 py-2.5 text-sm outline-none border transition-all ${isDark ? 'bg-white/5 border-white/15 text-white placeholder-white/30 focus:border-[#00bceb]/60' : 'bg-black/[0.02] border-black/10 text-[#0b2a3c] placeholder-black/30 focus:border-[#00bceb]/50'}`}
            />
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
                      title={isEnabled ? '关闭此渠道' : '开启此渠道'}
                      onClick={() => onNotificationChannelToggle(key)}
                      className={`relative w-9 h-5 rounded-full transition-colors shrink-0 ${isEnabled ? 'bg-[#00bceb]' : (isDark ? 'bg-white/15' : 'bg-black/12')}`}
                    >
                      <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all ${isEnabled ? 'left-[18px]' : 'left-0.5'}`} />
                    </button>
                  </div>

                  <div className="px-3 pb-3 flex flex-col gap-1.5">
                    <p className={`text-[10px] leading-relaxed ${isDark ? 'text-white/30' : 'text-black/35'}`}>{tip}</p>
                    <input
                      type="text"
                      value={channel.webhook_url}
                      onChange={(event) => onNotificationWebhookChange(key, event.target.value)}
                      title={`${label} Webhook URL`}
                      placeholder={hint}
                      className={`w-full rounded-lg px-2.5 py-2 text-[11px] outline-none border transition-all font-mono ${isDark ? 'bg-black/20 border-white/10 text-white/80 placeholder-white/20 focus:border-[#00bceb]/50' : 'bg-white/60 border-black/8 text-[#0b2a3c] placeholder-black/20 focus:border-[#00bceb]/40'}`}
                    />
                    {hasSecret && (
                      <input
                        type="password"
                        value={notificationChannels.dingtalk.secret}
                        onChange={(event) => onNotificationSecretChange(event.target.value)}
                        title={`${label} Secret`}
                        placeholder="加签 Secret（可选，留空则不验签）"
                        className={`w-full rounded-lg px-2.5 py-2 text-[11px] outline-none border transition-all font-mono ${isDark ? 'bg-black/20 border-white/10 text-white/80 placeholder-white/20 focus:border-[#00bceb]/50' : 'bg-white/60 border-black/8 text-[#0b2a3c] placeholder-black/20 focus:border-[#00bceb]/40'}`}
                      />
                    )}
                    <button
                      type="button"
                      title={`向 ${label} 发送测试告警`}
                      disabled={!channel.webhook_url.trim() || notifyTestLoading === key}
                      onClick={() => onTestNotificationChannel(key)}
                      className={`w-full py-1.5 rounded-lg text-[11px] font-semibold transition-all flex items-center justify-center gap-1.5 ${
                        !channel.webhook_url.trim() || notifyTestLoading === key
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

          <p className={`text-[11px] ${isDark ? 'text-white/40' : 'text-black/40'}`}>Last login: {currentUserLastLogin}</p>
        </div>

        <div className={`px-6 py-4 border-t flex gap-3 ${isDark ? 'border-white/10' : 'border-black/10'}`}>
          <button onClick={onClose} className={`flex-1 px-4 py-2.5 rounded-xl text-sm font-medium transition-all ${isDark ? 'bg-white/10 text-white/80 hover:bg-white/15' : 'bg-black/[0.04] text-black/70 hover:bg-black/[0.08]'}`}>
            Cancel
          </button>
          <button onClick={onSave} className="flex-1 px-4 py-2.5 rounded-xl text-sm font-semibold text-white bg-[#008bb0] hover:bg-[#00769a] transition-all shadow-lg shadow-[#00bceb]/20">
            Save Profile
          </button>
        </div>
      </motion.div>
    </div>
  );
};

export default ProfileModal;