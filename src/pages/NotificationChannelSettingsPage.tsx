import React, { useCallback, useEffect, useState } from 'react';
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  Bell,
  CheckCircle2,
  Cloud,
  Edit3,
  Loader2,
  Mail,
  Plus,
  Power,
  RefreshCw,
  Search,
  Save,
  Send,
  Server,
  ShieldAlert,
  Trash2,
  UserRound,
  Users,
} from 'lucide-react';
import PageHero from '../components/PageHero';
import { DataTable, DataTableFrame } from '../components/DataTable';
import { ApiError, apiRequest } from '../api/http';

interface SmtpSettingsDraft {
  display_name: string;
  enabled: boolean;
  host: string;
  port: number;
  security: 'ssl' | 'starttls' | 'none';
  username: string;
  password: string;
  from_address: string;
  from_name: string;
  reply_to: string;
  connect_timeout_seconds: number;
  send_timeout_seconds: number;
  rate_limit_per_minute: number;
  has_password?: boolean;
  configured?: boolean;
  updated_at?: string | null;
}

type Feedback = { tone: 'success' | 'error'; message: string };
type WizardStep = 1 | 2 | 3;
type ValidationScope = 'connection' | 'account' | 'all';
type ProviderGroup = 'domestic' | 'international' | 'selfHosted';

interface SmtpPreset {
  id: string;
  group: ProviderGroup;
  labelZh: string;
  labelEn: string;
  host: string;
  port: number;
  security: SmtpSettingsDraft['security'];
  requiresUsername: boolean;
  noteZh: string;
  noteEn: string;
  helpUrl?: string;
}

const SMTP_PRESETS: SmtpPreset[] = [
  { id: 'qq', group: 'domestic', labelZh: 'QQ 邮箱', labelEn: 'QQ Mail', host: 'smtp.qq.com', port: 465, security: 'ssl', requiresUsername: true, noteZh: '使用完整邮箱地址作为用户名，密码框填写客户端授权码，不是 QQ 登录密码。SSL 可用 465；按 QQ 邮箱说明也可尝试 587。', noteEn: 'Use your full email address and the mailbox app password, not your QQ account password. Use SSL on 465; QQ Mail also documents 587.', helpUrl: 'https://wx.mail.qq.com/list/readtemplate?name=app_intro.html#/agreement/authorizationCode' },
  { id: 'tencent-exmail', group: 'domestic', labelZh: '腾讯企业邮箱', labelEn: 'Tencent Exmail', host: 'smtp.exmail.qq.com', port: 465, security: 'ssl', requiresUsername: true, noteZh: '使用完整企业邮箱地址；需在邮箱或管理员后台允许 SMTP。开启安全登录时使用客户端专用密码。', noteEn: 'Use the full work email address and ensure SMTP is allowed by the account or administrator. Secure login may require a client-specific password.', helpUrl: 'https://exmail.qq.com/cgi-bin/help' },
  { id: 'netease-163', group: 'domestic', labelZh: '网易 163 邮箱', labelEn: 'NetEase 163 Mail', host: 'smtp.163.com', port: 465, security: 'ssl', requiresUsername: true, noteZh: '使用邮箱客户端授权密码。网易帮助说明 SSL 可用端口 465 或 587，不要选择 STARTTLS。', noteEn: 'Use a mailbox client authorization password. NetEase documents SSL on port 465 or 587; do not select STARTTLS.', helpUrl: 'https://help.mail.126.com/faqDetail.do?code=d7a5dc8471cd0c0e8b4b8f4f8e49998b374173cfe9171305fa1ce630d7f67ac25c12dcb3d46222b6' },
  { id: 'netease-126', group: 'domestic', labelZh: '网易 126 邮箱', labelEn: 'NetEase 126 Mail', host: 'smtp.126.com', port: 465, security: 'ssl', requiresUsername: true, noteZh: '使用邮箱客户端授权密码。网易帮助说明 SSL 可用端口 465 或 587，不要选择 STARTTLS。', noteEn: 'Use a mailbox client authorization password. NetEase documents SSL on port 465 or 587; do not select STARTTLS.', helpUrl: 'https://help.mail.126.com/faqDetail.do?code=d7a5dc8471cd0c0e8b4b8f4f8e49998b374173cfe9171305fa1ce630d7f67ac25c12dcb3d46222b6' },
  { id: 'netease-yeah', group: 'domestic', labelZh: '网易 yeah.net 邮箱', labelEn: 'NetEase yeah.net Mail', host: 'smtp.yeah.net', port: 465, security: 'ssl', requiresUsername: true, noteZh: '使用邮箱客户端授权密码。网易帮助说明 SSL 可用端口 465 或 587，不要选择 STARTTLS。', noteEn: 'Use a mailbox client authorization password. NetEase documents SSL on port 465 or 587; do not select STARTTLS.', helpUrl: 'https://help.mail.126.com/faqDetail.do?code=d7a5dc8471cd0c0e8b4b8f4f8e49998b374173cfe9171305fa1ce630d7f67ac25c12dcb3d46222b6' },
  { id: 'sina', group: 'domestic', labelZh: '新浪邮箱', labelEn: 'Sina Mail', host: 'smtp.sina.com', port: 465, security: 'ssl', requiresUsername: true, noteZh: '新浪不同邮箱后缀可能使用不同 SMTP 主机（如 sina.cn、vip.sina.com）；请核对官方客户端设置并使用授权码。', noteEn: 'Sina SMTP hostnames vary by mailbox suffix, such as sina.cn or vip.sina.com. Check the provider guide and use its authorization code.', helpUrl: 'https://help.sina.com.cn/comquestiondetail/view/160/' },
  { id: '139', group: 'domestic', labelZh: '中国移动 139 邮箱', labelEn: 'China Mobile 139 Mail', host: 'smtp.139.com', port: 465, security: 'ssl', requiresUsername: true, noteZh: '使用 SSL 465；SMTP 需要身份验证。部分账号可使用 smtp.10086.cn，请按邮箱账号资料核对。', noteEn: 'Use SSL on port 465 and enable SMTP authentication. Some accounts may use smtp.10086.cn; check your mailbox settings.', helpUrl: 'https://mail.10086.cn/help/help.html' },
  { id: '189', group: 'domestic', labelZh: '中国电信 189 邮箱', labelEn: 'China Telecom 189 Mail', host: 'smtp.189.cn', port: 465, security: 'ssl', requiresUsername: true, noteZh: '使用邮箱账号和邮箱专用密码。官方说明 SSL 端口支持 465 或 587。', noteEn: 'Use your 189 mailbox account and its dedicated password. The provider documents SSL ports 465 and 587.', helpUrl: 'https://help.189.cn/client/client.html' },
  { id: 'aliyun', group: 'domestic', labelZh: '阿里企业邮箱', labelEn: 'Alibaba Mail', host: 'smtp.qiye.aliyun.com', port: 465, security: 'ssl', requiresUsername: true, noteZh: '推荐 SSL 465；需允许第三方客户端访问。启用了第三方客户端安全密码时，使用该安全密码；587 未开放。', noteEn: 'Use SSL on port 465 and allow third-party client access. Use a client security password if enabled. Port 587 is not available.', helpUrl: 'https://help.aliyun.com/zh/document_detail/36576.html' },
  { id: 'google', group: 'international', labelZh: 'Gmail / Google Workspace', labelEn: 'Gmail / Google Workspace', host: 'smtp.gmail.com', port: 587, security: 'starttls', requiresUsername: true, noteZh: '465 使用隐式 SSL/TLS；587 使用 STARTTLS。认证需应用专用密码或 OAuth2；本系统当前仅支持用户名/密码 SMTP AUTH。', noteEn: 'Port 465 uses implicit SSL/TLS; 587 uses STARTTLS. Authentication requires an app password or OAuth2; this integration currently supports SMTP username/password only.', helpUrl: 'https://developers.google.com/workspace/gmail/imap/imap-smtp' },
  { id: 'outlook', group: 'international', labelZh: 'Outlook.com / Hotmail', labelEn: 'Outlook.com / Hotmail', host: 'smtp-mail.outlook.com', port: 587, security: 'starttls', requiresUsername: true, noteZh: '微软要求 Modern Auth / OAuth2；当前系统不支持 OAuth，因此该预设用于填写参数，测试可能因认证方式不兼容而失败。', noteEn: 'Microsoft requires Modern Auth / OAuth2. This integration does not support OAuth, so the preset only fills connection details and authentication may fail.', helpUrl: 'https://support.microsoft.com/en-US/Outlook/pop-imap-and-smtp-settings-for-outlook-com' },
  { id: 'microsoft365', group: 'international', labelZh: 'Microsoft 365', labelEn: 'Microsoft 365', host: 'smtp.office365.com', port: 587, security: 'starttls', requiresUsername: true, noteZh: '使用 STARTTLS 587。租户和邮箱必须允许 SMTP AUTH；微软建议 OAuth，本系统当前使用用户名和密码认证。中国 21Vianet 租户使用 smtp.partner.outlook.cn。', noteEn: 'Use STARTTLS on 587. SMTP AUTH must be allowed for the tenant and mailbox. Microsoft recommends OAuth; this integration currently uses username/password. 21Vianet tenants use smtp.partner.outlook.cn.', helpUrl: 'https://learn.microsoft.com/en-us/exchange/mail-flow-best-practices/how-to-set-up-a-multifunction-device-or-application-to-send-email-using-microsoft-365-or-office-365' },
  { id: 'icloud', group: 'international', labelZh: 'Apple iCloud 邮件', labelEn: 'Apple iCloud Mail', host: 'smtp.mail.me.com', port: 587, security: 'starttls', requiresUsername: true, noteZh: '使用完整 iCloud 邮箱地址和 App 专用密码；默认使用 STARTTLS 587。', noteEn: 'Use your full iCloud email address and an app-specific password. The preset uses STARTTLS on port 587.', helpUrl: 'https://support.apple.com/en-ie/102525' },
  { id: 'yahoo', group: 'international', labelZh: 'Yahoo Mail', labelEn: 'Yahoo Mail', host: 'smtp.mail.yahoo.com', port: 465, security: 'ssl', requiresUsername: true, noteZh: '使用 SSL 465；账号安全设置可能要求应用密码。也可手动改为 587 + STARTTLS。', noteEn: 'Use SSL on port 465. Your account security settings may require an app password. You can also use STARTTLS on 587.', helpUrl: 'https://help.yahoo.com/kb/SLN28681.html' },
  { id: 'zoho', group: 'international', labelZh: 'Zoho Mail', labelEn: 'Zoho Mail', host: 'smtp.zoho.com', port: 465, security: 'ssl', requiresUsername: true, noteZh: '默认使用 SSL 465。组织邮箱、数据中心或双重验证可能需要 smtppro.zoho.com、587 STARTTLS 或应用专用密码。', noteEn: 'The preset uses SSL on 465. Organization plans, data center, or 2FA settings may require smtppro.zoho.com, STARTTLS 587, or an app-specific password.', helpUrl: 'https://www.zoho.com/mail/help/zoho-smtp.html' },
  { id: 'mailpit', group: 'selfHosted', labelZh: 'Mailpit（本地邮件测试）', labelEn: 'Mailpit (local mail testing)', host: 'mailpit', port: 1025, security: 'none', requiresUsername: false, noteZh: 'Mailpit 默认 SMTP 为 1025、Web UI 为 8025，无加密且无需认证；邮件只进入测试收件箱，不会发送给真实收件人。Docker 部署时 SMTP 主机通常为服务名 mailpit。', noteEn: 'Mailpit defaults to SMTP port 1025 and Web UI port 8025, without encryption or authentication. Messages stay in its test inbox; they are not sent to real recipients. In Docker, the SMTP hostname is commonly the service name mailpit.', helpUrl: 'https://mailpit.axllent.org/docs/configuration/smtp/' },
  { id: 'mailcow', group: 'selfHosted', labelZh: 'Mailcow', labelEn: 'Mailcow', host: '', port: 587, security: 'starttls', requiresUsername: true, noteZh: '主机名使用你部署的 Mailcow 邮件服务器域名；常见方式为 STARTTLS 587 或 SSL 465，以部署设置为准。', noteEn: 'Use your Mailcow server hostname. Common submission options are STARTTLS 587 or SSL 465; follow your deployment settings.', helpUrl: 'https://docs.mailcow.email/client/client-manual/' },
  { id: 'postfix', group: 'selfHosted', labelZh: 'Postfix / Exim / OpenSMTPD', labelEn: 'Postfix / Exim / OpenSMTPD', host: '', port: 587, security: 'starttls', requiresUsername: false, noteZh: '填写管理员配置的 SMTP 主机名。587 STARTTLS 和 465 SSL 是常见方式，端口和认证规则取决于 MTA 配置。', noteEn: 'Enter the SMTP hostname from your administrator. 587 STARTTLS and 465 SSL are common options; ports and authentication depend on the MTA configuration.', helpUrl: 'https://www.postfix.org/TLS_README.html' },
  { id: 'custom', group: 'selfHosted', labelZh: '其他 / 自定义 SMTP', labelEn: 'Other / custom SMTP', host: '', port: 587, security: 'starttls', requiresUsername: false, noteZh: '适用于 Mailu、其他开源邮件服务或厂商专用 SMTP。请按管理员提供的信息填写主机名、端口、加密和认证方式。', noteEn: 'For Mailu, other open-source mail servers, or provider-specific SMTP. Enter the hostname, port, security, and authentication details supplied by the administrator.' },
];

const PROVIDER_MARKS: Record<string, { label: string; className: string; microsoft?: boolean; icon?: 'cloud' }> = {
  qq: { label: 'Q', className: 'bg-sky-50 text-sky-600' },
  'tencent-exmail': { label: '企', className: 'bg-blue-50 text-blue-700' },
  'netease-163': { label: '163', className: 'bg-red-50 text-red-600' },
  'netease-126': { label: '126', className: 'bg-rose-50 text-rose-600' },
  'netease-yeah': { label: 'Y', className: 'bg-orange-50 text-orange-600' },
  sina: { label: 'S', className: 'bg-red-50 text-red-600' },
  '139': { label: '139', className: 'bg-blue-50 text-blue-600' },
  '189': { label: '189', className: 'bg-orange-50 text-orange-600' },
  aliyun: { label: 'A', className: 'bg-amber-50 text-amber-700' },
  google: { label: 'G', className: 'bg-white text-blue-600 ring-1 ring-slate-200' },
  outlook: { label: 'O', className: 'bg-sky-50 text-sky-700' },
  microsoft365: { label: '', className: 'bg-white ring-1 ring-slate-200', microsoft: true },
  icloud: { label: '', className: 'bg-slate-100 text-slate-600', icon: 'cloud' },
  yahoo: { label: 'Y!', className: 'bg-violet-50 text-violet-700' },
  zoho: { label: 'Z', className: 'bg-red-50 text-red-600' },
  mailpit: { label: 'MP', className: 'bg-orange-50 text-orange-700' },
  mailcow: { label: 'MC', className: 'bg-emerald-50 text-emerald-700' },
  postfix: { label: 'MTA', className: 'bg-slate-100 text-slate-700' },
  custom: { label: '+', className: 'bg-cyan-50 text-cyan-700' },
};

function ProviderMark({ providerId }: { providerId: string }) {
  const mark = PROVIDER_MARKS[providerId] ?? { label: 'SMTP', className: 'bg-slate-100 text-slate-600' };
  return (
    <span aria-hidden="true" className={'flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-xs font-extrabold tracking-tight ' + mark.className}>
      {mark.microsoft ? <span className="grid grid-cols-2 gap-0.5">{['bg-red-500', 'bg-green-500', 'bg-blue-500', 'bg-amber-400'].map((color) => <span key={color} className={'h-2.5 w-2.5 ' + color} />)}</span> : mark.icon === 'cloud' ? <Cloud size={19} /> : mark.label}
    </span>
  );
}

const getPresetIdForHost = (host: string): string =>
  SMTP_PRESETS.find((preset) => preset.host && preset.host === host.trim().toLowerCase())?.id ?? 'custom';

const WIZARD_STEPS: { number: WizardStep; zh: string; en: string; captionZh: string; captionEn: string }[] = [
  { number: 1, zh: '选择邮箱服务', en: 'Choose provider', captionZh: '服务器和连接方式', captionEn: 'Server and connection' },
  { number: 2, zh: '填写账号信息', en: 'Enter account details', captionZh: '授权码和发件人', captionEn: 'Credentials and sender' },
  { number: 3, zh: '测试并启用', en: 'Test and enable', captionZh: '确认收到后开告警', captionEn: 'Confirm delivery and enable' },
];
type ToastTone = 'success' | 'error' | 'info';

interface NotificationChannelSettingsPageProps {
  language: string;
  showToast: (message: string, type?: ToastTone) => void;
}

const EMPTY_SETTINGS: SmtpSettingsDraft = {
  display_name: '',
  enabled: false,
  host: '',
  port: 587,
  security: 'starttls',
  username: '',
  password: '',
  from_address: '',
  from_name: 'Nexora',
  reply_to: '',
  connect_timeout_seconds: 10,
  send_timeout_seconds: 20,
  rate_limit_per_minute: 60,
  has_password: false,
  configured: false,
};

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const inputClass = 'w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-700 outline-none transition placeholder:text-slate-400 focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400';
const fieldLabelClass = 'mb-1.5 block text-xs font-semibold text-slate-600';

const SMTP_TEST_ERROR_MESSAGES: Record<string, { zh: string; en: string }> = {
  smtp_auth_failed: {
    zh: 'SMTP 认证失败。检查完整邮箱用户名和服务商专用授权码；QQ 邮箱不能填写 QQ 登录密码。',
    en: 'SMTP authentication failed. Check the full mailbox username and provider app password. QQ Mail does not use your QQ account password.',
  },
  smtp_tls_failed: {
    zh: 'TLS 握手失败。请核对端口和加密方式（常见组合为 465 + SSL/TLS、587 + STARTTLS）；QQ 和网易邮箱须按各自说明设置。',
    en: 'TLS negotiation failed. Check the port and encryption pair (commonly 465 + SSL/TLS or 587 + STARTTLS); follow QQ and NetEase instructions where applicable.',
  },
  smtp_timeout: {
    zh: '连接或发送超时。请检查邮件服务器能否访问 SMTP 主机和端口，以及服务器或容器的出站防火墙规则。',
    en: 'The SMTP connection or send timed out. Check access to the SMTP host and port, including outbound firewall rules on the server or container.',
  },
  smtp_dns_or_connect_failed: {
    zh: '无法连接 SMTP 服务器。请检查主机名、端口、DNS 解析和服务器出站网络。',
    en: 'Could not connect to the SMTP server. Check the hostname, port, DNS resolution, and outbound network access.',
  },
  smtp_recipient_rejected: {
    zh: 'SMTP 服务器拒绝了测试收件人，请检查收件人地址或服务商的发信限制。',
    en: 'The SMTP server rejected the test recipient. Check the address and your provider’s sending restrictions.',
  },
  smtp_invalid_recipient: {
    zh: '测试收件人邮箱格式无效，请输入有效邮箱地址。',
    en: 'The test recipient is not a valid email address.',
  },
  email_no_recipients: {
    zh: '没有可用的测试收件人，请填写测试收件人邮箱。',
    en: 'No test recipient is available. Enter a recipient email address.',
  },
  smtp_config_missing: {
    zh: 'SMTP 配置不完整，请检查主机、发件人地址和凭据后保存。',
    en: 'SMTP settings are incomplete. Check the host, sender address, and credentials, then save.',
  },
  smtp_rate_limited: {
    zh: '邮件发送过于频繁，请稍后再试。',
    en: 'The email rate limit was reached. Try again later.',
  },
  smtp_provider_error: {
    zh: '邮件服务商未能处理本次 SMTP 请求，请检查配置或稍后重试。',
    en: 'The mail provider could not process this SMTP request. Check the settings or try again later.',
  },
};

const getErrorMessage = (error: unknown, zh: boolean, action: 'load' | 'save' | 'delete' | 'test' | 'connection'): string => {
  if (error instanceof ApiError) {
    if (error.status === 401) return zh ? '登录已失效，请重新登录。' : 'Your session has expired. Please sign in again.';
    if (error.status === 403) return zh ? '你没有管理 SMTP 邮件通道的权限。' : 'You do not have permission to manage the SMTP email channel.';
    if ((action === 'test' || action === 'connection') && error.status === 502) {
      const code = typeof error.detail === 'string' ? error.detail : error.code;
      const knownError = code ? SMTP_TEST_ERROR_MESSAGES[code] : undefined;
      if (knownError) return zh ? knownError.zh : knownError.en;
    }
    if (error.status >= 500) return zh ? '邮件服务暂时不可用，请稍后重试。' : 'The mail service is temporarily unavailable. Please try again.';
    const cleanMessage = error.message.replace(/\s*\(Request ID:.*\)$/i, '').trim();
    if (cleanMessage) return cleanMessage;
  }
  if (error instanceof Error && error.message.trim()) return error.message;
  if (action === 'load') return zh ? 'SMTP 配置加载失败，请重试。' : 'Failed to load SMTP settings. Please retry.';
  if (action === 'save') return zh ? 'SMTP 配置保存失败，请重试。' : 'Failed to save SMTP settings. Please retry.';
  if (action === 'delete') return zh ? 'SMTP 配置删除失败，请重试。' : 'Failed to delete SMTP settings. Please retry.';
  if (action === 'connection') return zh ? 'SMTP 连接测试失败，请检查主机、端口和加密设置。' : 'SMTP connection testing failed. Check the host, port, and encryption settings.';
  return zh ? '测试邮件发送失败，请检查配置后重试。' : 'The test email could not be sent. Check the settings and retry.';
};



type RecipientTarget =
  | { kind: 'group'; group_name: string }
  | { kind: 'user'; user_id: string };

interface NotificationProfile extends SmtpSettingsDraft {
  id: string;
  recipient_targets: RecipientTarget[];
  inherited: boolean;
  legacy_primary: boolean;
}

interface RecipientGroup {
  name: string;
  member_count: number;
}

interface RecipientUser {
  id: string;
  username: string;
  display_name: string;
  email: string;
  group_name?: string | null;
}

interface RecipientDirectory {
  groups: RecipientGroup[];
  users: RecipientUser[];
}

const EMAIL_PROFILE_BASE = '/api/alerts/notification-channels/email/profiles';

const normalizeProfile = (profile: Partial<NotificationProfile>, fallbackId?: string): NotificationProfile => ({
  ...EMPTY_SETTINGS,
  ...profile,
  id: String(profile.id ?? fallbackId ?? ''),
  display_name: String(profile.display_name ?? ''),
  enabled: Boolean(profile.enabled),
  host: String(profile.host ?? ''),
  port: Number(profile.port ?? 587),
  security: profile.security === 'ssl' || profile.security === 'none' ? profile.security : 'starttls',
  username: String(profile.username ?? ''),
  password: '',
  from_address: String(profile.from_address ?? ''),
  from_name: String(profile.from_name ?? 'Nexora'),
  reply_to: String(profile.reply_to ?? ''),
  connect_timeout_seconds: Number(profile.connect_timeout_seconds ?? 10),
  send_timeout_seconds: Number(profile.send_timeout_seconds ?? 20),
  rate_limit_per_minute: Number(profile.rate_limit_per_minute ?? 60),
  has_password: Boolean(profile.has_password),
  configured: Boolean(profile.configured),
  updated_at: profile.updated_at ?? null,
  recipient_targets: Array.isArray(profile.recipient_targets) ? profile.recipient_targets.filter((target): target is RecipientTarget => Boolean(target && (target.kind === 'group' || target.kind === 'user'))) : [],
  inherited: Boolean(profile.inherited),
  legacy_primary: Boolean(profile.legacy_primary),
});

const targetKey = (target: RecipientTarget): string => target.kind === 'group' ? `group:${target.group_name}` : `user:${target.user_id}`;

const NotificationChannelSettingsPage: React.FC<NotificationChannelSettingsPageProps> = ({ language, showToast }) => {
  const zh = language === 'zh';
  const [profiles, setProfiles] = useState<NotificationProfile[]>([]);
  const [directory, setDirectory] = useState<RecipientDirectory>({ groups: [], users: [] });
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [permissionDenied, setPermissionDenied] = useState(false);
  const [recipientPermissionDenied, setRecipientPermissionDenied] = useState(false);
  const [view, setView] = useState<'list' | 'wizard'>('list');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingLegacyPrimary, setEditingLegacyPrimary] = useState(false);
  const [settings, setSettings] = useState<SmtpSettingsDraft>(EMPTY_SETTINGS);
  const [recipientTargets, setRecipientTargets] = useState<RecipientTarget[]>([]);
  const [currentStep, setCurrentStep] = useState<WizardStep>(1);
  const [selectedPresetId, setSelectedPresetId] = useState('custom');
  const [providerGroup, setProviderGroup] = useState<ProviderGroup>('domestic');
  const [providerSearch, setProviderSearch] = useState('');
  const [persistedHost, setPersistedHost] = useState('');
  const [credentialsNeedRefresh, setCredentialsNeedRefresh] = useState(false);
  const [recipient, setRecipient] = useState('');
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [connectionTested, setConnectionTested] = useState(false);
  const [testAccepted, setTestAccepted] = useState(false);
  const [deliveryConfirmed, setDeliveryConfirmed] = useState(false);
  const [quickTestingId, setQuickTestingId] = useState<string | null>(null);
  const [rowFeedback, setRowFeedback] = useState<Record<string, Feedback>>({});
  const [rowBusyId, setRowBusyId] = useState<string | null>(null);

  const loadChannels = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      const [profileResult, recipientResult] = await Promise.allSettled([
        apiRequest<{ items: Partial<NotificationProfile>[] }>(EMAIL_PROFILE_BASE),
        apiRequest<RecipientDirectory>('/api/alerts/notification-channels/email/recipients'),
      ]);
      if (profileResult.status === 'rejected') throw profileResult.reason;
      const profilePayload = profileResult.value;
      setProfiles((profilePayload.items ?? []).map((profile) => normalizeProfile(profile)));
      setDirectory(recipientResult.status === 'fulfilled' ? { groups: recipientResult.value.groups ?? [], users: recipientResult.value.users ?? [] } : { groups: [], users: [] });
      setRecipientPermissionDenied(recipientResult.status === 'rejected' && recipientResult.reason instanceof ApiError && recipientResult.reason.status === 403);
      setLoaded(true);
      setPermissionDenied(false);
    } catch (error) {
      setLoaded(false);
      setLoadError(getErrorMessage(error, zh, 'load'));
      if (error instanceof ApiError && error.status === 403) setPermissionDenied(true);
    } finally {
      setLoading(false);
    }
  }, [zh]);

  useEffect(() => { void loadChannels(); }, [loadChannels]);

  const resetWizard = () => {
    setSettings(EMPTY_SETTINGS);
    setRecipientTargets([]);
    setEditingId(null);
    setEditingLegacyPrimary(false);
    setCurrentStep(1);
    setSelectedPresetId('custom');
    setProviderGroup('domestic');
    setProviderSearch('');
    setPersistedHost('');
    setCredentialsNeedRefresh(false);
    setRecipient('');
    setFieldErrors({});
    setFeedback(null);
    setDirty(false);
    setConnectionTested(false);
    setTestAccepted(false);
    setDeliveryConfirmed(false);
  };

  const openCreate = () => {
    resetWizard();
    setView('wizard');
  };

  const openEdit = (profile: NotificationProfile) => {
    const loadedHost = profile.host.trim().toLowerCase();
    const presetId = getPresetIdForHost(loadedHost);
    const preset = SMTP_PRESETS.find((item) => item.id === presetId) ?? SMTP_PRESETS[SMTP_PRESETS.length - 1];
    setSettings({ ...normalizeProfile(profile), password: '' });
    setRecipientTargets(profile.recipient_targets.map((target) => ({ ...target })));
    setEditingId(profile.id);
    setEditingLegacyPrimary(profile.legacy_primary);
    setCurrentStep(1);
    setSelectedPresetId(presetId);
    setProviderGroup(preset.group);
    setProviderSearch('');
    setPersistedHost(loadedHost);
    setCredentialsNeedRefresh(false);
    setRecipient('');
    setFieldErrors({});
    setFeedback(null);
    setDirty(false);
    setConnectionTested(false);
    setTestAccepted(false);
    setDeliveryConfirmed(false);
    setView('wizard');
  };

  const validate = useCallback((scope: ValidationScope, includeRecipient = false): Record<string, string> => {
    const errors: Record<string, string> = {};
    const validateConnection = scope === 'connection' || scope === 'all';
    const validateAccount = scope === 'account' || scope === 'all';
    const validateAdvanced = scope === 'all';
    const selectedPreset = SMTP_PRESETS.find((preset) => preset.id === selectedPresetId);
    const port = Number(settings.port);
    if (validateConnection) {
      if (!settings.display_name.trim()) errors.display_name = zh ? '请输入通道名称。' : 'Channel name is required.';
      if (!settings.host.trim()) errors.host = zh ? '请输入 SMTP 主机。' : 'SMTP host is required.';
      if (!Number.isInteger(port) || port < 1 || port > 65535) errors.port = zh ? '端口须为 1–65535 的整数。' : 'Port must be an integer from 1 to 65535.';
      const sslOnlyProvider = ['qq', 'netease-163', 'netease-126', 'netease-yeah'].includes(selectedPresetId);
      if (sslOnlyProvider && (settings.security !== 'ssl' || ![465, 587].includes(port))) errors.security = zh ? '该邮箱要求 SSL/TLS，请使用 465 或 587 端口。' : 'This provider requires SSL/TLS on port 465 or 587.';
    }
    if (validateAccount) {
      if (selectedPreset?.requiresUsername && !settings.username.trim()) errors.username = zh ? '该邮箱服务需要完整邮箱地址作为 SMTP 用户名。' : 'This provider requires your full email address as the SMTP username.';
      if (!settings.from_address.trim()) errors.from_address = zh ? '请输入发件人邮箱。' : 'From address is required.';
      else if (!EMAIL_PATTERN.test(settings.from_address.trim())) errors.from_address = zh ? '请输入有效的邮箱地址。' : 'Enter a valid email address.';
      if (settings.reply_to.trim() && !EMAIL_PATTERN.test(settings.reply_to.trim())) errors.reply_to = zh ? '请输入有效的回复邮箱。' : 'Enter a valid reply-to address.';
      const needsPassword = Boolean(selectedPreset?.requiresUsername || settings.username.trim()) && (!settings.has_password || credentialsNeedRefresh);
      if (needsPassword && !settings.password.trim()) errors.password = zh ? '请输入该邮箱生成的授权码或 SMTP 密码。' : 'Enter the app password or SMTP password for this mailbox.';
      if (recipientTargets.length === 0 && !editingLegacyPrimary) errors.recipient_targets = zh ? '新建通道至少选择一个用户组或系统用户。' : 'Select at least one group or user for this channel.';
    }
    if (validateAdvanced) {
      const connectTimeout = Number(settings.connect_timeout_seconds);
      const sendTimeout = Number(settings.send_timeout_seconds);
      const rateLimit = Number(settings.rate_limit_per_minute);
      if (!Number.isInteger(connectTimeout) || connectTimeout < 1 || connectTimeout > 120) errors.connect_timeout_seconds = zh ? '连接超时须为 1–120 秒。' : 'Connect timeout must be from 1 to 120 seconds.';
      if (!Number.isInteger(sendTimeout) || sendTimeout < 1 || sendTimeout > 120) errors.send_timeout_seconds = zh ? '发送超时须为 1–120 秒。' : 'Send timeout must be from 1 to 120 seconds.';
      if (!Number.isInteger(rateLimit) || rateLimit < 1 || rateLimit > 10000) errors.rate_limit_per_minute = zh ? '速率上限须为 1–10000。' : 'Rate limit must be from 1 to 10000.';
    }
    if (includeRecipient && recipient.trim() && !EMAIL_PATTERN.test(recipient.trim())) errors.recipient = zh ? '测试收件人须为有效的邮箱地址。' : 'Test recipient must be a valid email address.';
    return errors;
  }, [credentialsNeedRefresh, editingLegacyPrimary, recipient, recipientTargets.length, selectedPresetId, settings, zh]);

  const updateField = <K extends keyof SmtpSettingsDraft>(field: K, value: SmtpSettingsDraft[K]) => {
    if (field === 'host') {
      const host = String(value).trim().toLowerCase();
      setSettings((current) => host !== current.host.trim().toLowerCase() ? { ...current, host, username: '', password: '', from_address: '' } : { ...current, host });
      const matchingPreset = SMTP_PRESETS.find((preset) => preset.host && preset.host === host);
      setSelectedPresetId(matchingPreset?.id ?? 'custom');
      setProviderGroup(matchingPreset?.group ?? 'selfHosted');
      setCredentialsNeedRefresh(host !== persistedHost);
    } else setSettings((current) => ({ ...current, [field]: value }));
    setConnectionTested(false);
    setTestAccepted(false);
    setDeliveryConfirmed(false);
    setFieldErrors((current) => { const next = { ...current }; delete next[field]; if (field === 'host' || field === 'port' || field === 'security') delete next.security; return next; });
    setDirty(true);
    setFeedback(null);
  };

  const applyPreset = (presetId: string) => {
    const preset = SMTP_PRESETS.find((item) => item.id === presetId) ?? SMTP_PRESETS[SMTP_PRESETS.length - 1];
    setSelectedPresetId(preset.id);
    setProviderGroup(preset.group);
    setProviderSearch('');
    setSettings((current) => {
      const hostChanged = preset.host.trim().toLowerCase() !== current.host.trim().toLowerCase();
      return { ...current, host: preset.host, port: preset.port, security: preset.security, ...(hostChanged ? { username: '', password: '', from_address: '' } : {}) };
    });
    setCredentialsNeedRefresh(preset.host.trim().toLowerCase() !== persistedHost);
    setConnectionTested(false);
    setTestAccepted(false);
    setDeliveryConfirmed(false);
    setDirty(true);
  };

  const toggleTarget = (target: RecipientTarget) => {
    setRecipientTargets((current) => current.some((item) => targetKey(item) === targetKey(target)) ? current.filter((item) => targetKey(item) !== targetKey(target)) : [...current, target]);
    setFieldErrors((current) => { const next = { ...current }; delete next.recipient_targets; return next; });
    setDirty(true);
  };

  const saveProfile = async (): Promise<NotificationProfile | null> => {
    if (permissionDenied) return null;
    const errors = validate('all');
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) {
      setFeedback({ tone: 'error', message: zh ? '请先修正标记的字段。' : 'Fix the highlighted fields before saving.' });
      showToast(zh ? 'SMTP 配置校验未通过' : 'SMTP settings are invalid', 'info');
      return null;
    }
    setSaving(true);
    setFeedback(null);
    try {
      const payload: Record<string, unknown> = {
        display_name: settings.display_name.trim(), enabled: settings.enabled, host: settings.host.trim(), port: Number(settings.port), security: settings.security,
        username: settings.username.trim(), from_address: settings.from_address.trim(), from_name: settings.from_name.trim() || 'Nexora', reply_to: settings.reply_to.trim(),
        connect_timeout_seconds: Number(settings.connect_timeout_seconds), send_timeout_seconds: Number(settings.send_timeout_seconds), rate_limit_per_minute: Number(settings.rate_limit_per_minute), recipient_targets: recipientTargets,
      };
      if (settings.password.trim()) payload.password = settings.password.trim();
      const url = editingId ? `${EMAIL_PROFILE_BASE}/${encodeURIComponent(editingId)}` : EMAIL_PROFILE_BASE;
      const saved = await apiRequest<Partial<NotificationProfile>> (url, { method: editingId ? 'PUT' : 'POST', body: JSON.stringify(payload) });
      const normalized = normalizeProfile(saved, editingId ?? undefined);
      setProfiles((current) => editingId ? current.map((profile) => profile.id === normalized.id ? normalized : profile) : [...current, normalized]);
      setEditingId(normalized.id);
      setEditingLegacyPrimary(normalized.legacy_primary);
      setSettings({ ...normalized, password: '', has_password: normalized.has_password });
      setRecipientTargets(normalized.recipient_targets);
      setPersistedHost(normalized.host.trim().toLowerCase());
      setCredentialsNeedRefresh(false);
      setDirty(false);
      setPermissionDenied(false);
      const message = zh ? 'SMTP 通道已保存，密码输入已清空。' : 'SMTP channel saved. The password field was cleared.';
      setFeedback({ tone: 'success', message });
      showToast(message, 'success');
      return normalized;
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) setPermissionDenied(true);
      const message = getErrorMessage(error, zh, 'save');
      setFeedback({ tone: 'error', message });
      showToast(message, 'error');
      return null;
    } finally {
      setSaving(false);
    }
  };

  const testConnection = async () => {
    if (dirty) { const saved = await saveProfile(); if (!saved) return; }
    if (!editingId) return;
    setTesting(true);
    try {
      const result = await apiRequest<{ connected?: boolean; authenticated?: boolean }>(`${EMAIL_PROFILE_BASE}/${encodeURIComponent(editingId)}/test-connection`, { method: 'POST' });
      setConnectionTested(true);
      const message = result.authenticated === false ? (zh ? 'SMTP 连接和加密成功；此配置未使用 SMTP 账号认证。' : 'SMTP connection and encryption succeeded; this channel does not use SMTP authentication.') : (zh ? 'SMTP 连接、加密和账号认证均成功。' : 'SMTP connection, encryption, and authentication succeeded.');
      setFeedback({ tone: 'success', message });
      showToast(message, 'success');
    } catch (error) {
      setConnectionTested(false);
      if (error instanceof ApiError && error.status === 403) setPermissionDenied(true);
      const message = getErrorMessage(error, zh, 'connection');
      setFeedback({ tone: 'error', message });
      showToast(message, 'error');
    } finally { setTesting(false); }
  };

  const testSettings = async () => {
    const errors = validate('all', true);
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) { setFeedback({ tone: 'error', message: zh ? '请先修正标记的字段，并保存配置后再测试。' : 'Fix the highlighted fields and save the settings before testing.' }); return; }
    const saved = dirty ? await saveProfile() : normalizeProfile(settings, editingId ?? undefined);
    if (!saved?.id) return;
    setTesting(true);
    try {
      await apiRequest(`${EMAIL_PROFILE_BASE}/${encodeURIComponent(saved.id)}/test`, { method: 'POST', body: JSON.stringify({ recipient: recipient.trim() || undefined }) });
      const message = zh ? '测试邮件已被 SMTP 服务器接受，请检查收件箱。' : 'The SMTP server accepted the test email. Check your inbox.';
      setTestAccepted(true);
      setDeliveryConfirmed(false);
      setFeedback({ tone: 'success', message });
      showToast(message, 'success');
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) setPermissionDenied(true);
      const message = getErrorMessage(error, zh, 'test');
      setFeedback({ tone: 'error', message });
      showToast(message, 'error');
    } finally { setTesting(false); }
  };

  const quickTest = async (profile: NotificationProfile) => {
    setQuickTestingId(profile.id);
    setRowFeedback((current) => { const next = { ...current }; delete next[profile.id]; return next; });
    try {
      await apiRequest(`${EMAIL_PROFILE_BASE}/${encodeURIComponent(profile.id)}/test`, { method: 'POST', body: JSON.stringify({}) });
      setRowFeedback((current) => ({ ...current, [profile.id]: { tone: 'success', message: zh ? 'SMTP 已接受测试邮件，请确认当前管理员邮箱已收到后再启用通道。' : 'SMTP accepted the test email. Confirm the current administrator received it before enabling this channel.' } }));
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) setPermissionDenied(true);
      setRowFeedback((current) => ({ ...current, [profile.id]: { tone: 'error', message: getErrorMessage(error, zh, 'test') } }));
    } finally { setQuickTestingId(null); }
  };

  const toggleEnabled = async (profile: NotificationProfile) => {
    if (profile.inherited) return;
    if (!profile.enabled && !window.confirm(zh ? '请确认你已收到该通道的测试邮件，再启用正式告警。' : 'Confirm that you received this channel’s test email before enabling real alerts.')) return;
    setRowBusyId(profile.id);
    try {
      const updated = await apiRequest<Partial<NotificationProfile>>(`${EMAIL_PROFILE_BASE}/${encodeURIComponent(profile.id)}/enabled`, { method: 'PATCH', body: JSON.stringify({ enabled: !profile.enabled }) });
      const normalized = normalizeProfile({ ...profile, ...updated, enabled: updated.enabled ?? !profile.enabled });
      setProfiles((current) => current.map((item) => item.id === profile.id ? normalized : item));
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) setPermissionDenied(true);
      showToast(getErrorMessage(error, zh, 'save'), 'error');
    } finally { setRowBusyId(null); }
  };

  const deleteProfile = async (profile: NotificationProfile) => {
    if (profile.inherited || !window.confirm(zh ? `确定删除“${profile.display_name}”吗？邮件告警将停止使用该通道。` : `Delete “${profile.display_name}”? Email alerts will stop using this channel.`)) return;
    setRowBusyId(profile.id);
    try {
      await apiRequest(`${EMAIL_PROFILE_BASE}/${encodeURIComponent(profile.id)}`, { method: 'DELETE' });
      setProfiles((current) => current.filter((item) => item.id !== profile.id));
      const message = zh ? 'SMTP 通道已删除。' : 'SMTP channel deleted.';
      showToast(message, 'success');
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) setPermissionDenied(true);
      showToast(getErrorMessage(error, zh, 'delete'), 'error');
    } finally { setRowBusyId(null); }
  };

  const activePreset = SMTP_PRESETS.find((item) => item.id === selectedPresetId) ?? SMTP_PRESETS[SMTP_PRESETS.length - 1];
  const isQqMail = selectedPresetId === 'qq';
  const smtpAuthenticationExpected = activePreset.requiresUsername || Boolean(settings.username.trim());
  const sslOnlyProvider = ['qq', 'netease-163', 'netease-126', 'netease-yeah'].includes(selectedPresetId);
  const sslOnlyCompatible = !sslOnlyProvider || (settings.security === 'ssl' && [465, 587].includes(Number(settings.port)));
  const fieldError = (name: string) => fieldErrors[name] && <p className="mt-1 text-xs text-rose-600">{fieldErrors[name]}</p>;
  const locked = !loaded || permissionDenied || recipientPermissionDenied || saving || testing;
  const groupNames: Record<ProviderGroup, { zh: string; en: string }> = { domestic: { zh: '国内邮箱', en: 'Domestic providers' }, international: { zh: '国际邮箱', en: 'International providers' }, selfHosted: { zh: '开源 / 自建 / 其他', en: 'Open-source / self-hosted / other' } };
  const providerGroups: ProviderGroup[] = ['domestic', 'international', 'selfHosted'];
  const normalizedProviderSearch = providerSearch.trim().toLocaleLowerCase();
  const visiblePresets = SMTP_PRESETS.filter((preset) => { if (!normalizedProviderSearch) return preset.group === providerGroup; const searchable = `${preset.id} ${preset.labelZh} ${preset.labelEn} ${preset.host}`.toLocaleLowerCase(); return searchable.includes(normalizedProviderSearch); });
  const selectedTarget = (target: RecipientTarget) => recipientTargets.some((item) => targetKey(item) === targetKey(target));
  const userName = (id: string) => { const user = directory.users.find((item) => item.id === id); return user?.display_name || user?.username || id; };
  const formatUpdated = (value?: string | null) => value ? new Date(value).toLocaleString(zh ? 'zh-CN' : undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '—';

  const renderRecipientPicker = () => <div className="space-y-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 sm:p-5">
    <div><p className="text-sm font-bold text-slate-800">{zh ? '告警收件人' : 'Alert recipients'}</p><p className="mt-1 text-xs leading-5 text-slate-500">{zh ? '选择用户组和系统用户；发送时会合并并去重。' : 'Select groups and system users; deliveries are merged and deduplicated.'}</p>{fieldError('recipient_targets')}</div>
    <div><p className="mb-2 flex items-center gap-2 text-xs font-semibold text-slate-600"><Users size={14} />{zh ? '用户组' : 'Groups'}</p><div className="grid gap-2 sm:grid-cols-2">{directory.groups.map((group) => { const target: RecipientTarget = { kind: 'group', group_name: group.name }; return <label key={group.name} className={'flex cursor-pointer items-center gap-3 rounded-xl border bg-white px-3 py-2.5 ' + (selectedTarget(target) ? 'border-cyan-300 ring-1 ring-cyan-100' : 'border-slate-200')}><input type="checkbox" checked={selectedTarget(target)} disabled={locked} onChange={() => toggleTarget(target)} className="h-4 w-4 accent-cyan-700" /><span className="min-w-0 flex-1"><span className="block truncate text-sm font-semibold text-slate-700">{group.name}</span><span className="text-[11px] text-slate-500">{group.member_count} {zh ? '名成员' : 'members'}</span></span></label>; })}{directory.groups.length === 0 && <p className="text-xs text-slate-500">{zh ? '暂无用户组。' : 'No groups available.'}</p>}</div></div>
    <div><p className="mb-2 flex items-center gap-2 text-xs font-semibold text-slate-600"><UserRound size={14} />{zh ? '系统用户' : 'System users'}</p><div className="grid max-h-64 gap-2 overflow-y-auto sm:grid-cols-2">{directory.users.map((user) => { const target: RecipientTarget = { kind: 'user', user_id: user.id }; return <label key={user.id} className={'flex cursor-pointer items-center gap-3 rounded-xl border bg-white px-3 py-2.5 ' + (selectedTarget(target) ? 'border-cyan-300 ring-1 ring-cyan-100' : 'border-slate-200')}><input type="checkbox" checked={selectedTarget(target)} disabled={locked} onChange={() => toggleTarget(target)} className="h-4 w-4 accent-cyan-700" /><span className="min-w-0 flex-1"><span className="block truncate text-sm font-semibold text-slate-700">{user.display_name || user.username}</span><span className="block truncate text-[11px] text-slate-500">{user.email || user.username}{user.group_name ? ` · ${user.group_name}` : ''}</span></span></label>; })}{directory.users.length === 0 && <p className="text-xs text-slate-500">{zh ? '暂无系统用户。' : 'No system users available.'}</p>}</div></div>
  </div>;

  return <div className="flex h-full min-h-0 flex-col overflow-y-auto bg-slate-50/80">
    <PageHero icon={Bell} eyebrow={zh ? '平台管理' : 'Platform management'} title={zh ? '邮件通知' : 'Email notifications'} subtitle={view === 'list' ? (zh ? '管理多个独立 SMTP 通道和各自的告警收件人。' : 'Manage independent SMTP channels and their alert recipients.') : (zh ? '按步骤配置 SMTP、收件人和邮件投递。' : 'Configure SMTP, recipients, and email delivery step by step.')} actions={<div className="flex items-center gap-2">{view === 'wizard' && <button type="button" onClick={() => { setView('list'); setFeedback(null); }} className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-600"><ArrowLeft size={14} />{zh ? '返回通道列表' : 'Back to channels'}</button>}{view === 'list' && <button type="button" onClick={openCreate} disabled={permissionDenied || recipientPermissionDenied || loading} className="inline-flex items-center gap-2 rounded-xl bg-cyan-700 px-3 py-2 text-xs font-semibold text-white shadow-sm disabled:opacity-50"><Plus size={14} />{zh ? '新增通道' : 'Add channel'}</button>}<button type="button" onClick={() => void loadChannels()} disabled={loading || saving || testing} className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-600 shadow-sm disabled:opacity-50"><RefreshCw size={14} className={loading ? 'animate-spin' : ''} />{zh ? '刷新' : 'Refresh'}</button></div>} />
    <div className="mx-auto w-full max-w-[1536px] space-y-5 p-4 sm:p-6 lg:p-8">
      {loading && <div className="flex items-center gap-3 rounded-2xl border border-cyan-100 bg-white px-5 py-6 text-sm text-cyan-800 shadow-sm"><Loader2 size={18} className="animate-spin" />{zh ? '正在读取邮件通道和收件人…' : 'Loading channels and recipients…'}</div>}
      {loadError && <div role="alert" className="flex items-center gap-3 rounded-2xl border border-rose-200 bg-white px-5 py-4 text-sm text-rose-700"><AlertCircle size={18} /><span className="flex-1">{loadError}</span>{!permissionDenied && <button type="button" onClick={() => void loadChannels()} className="rounded-lg border px-3 py-1.5 text-xs">{zh ? '重试' : 'Retry'}</button>}</div>}
      {permissionDenied && <div role="alert" className="flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-800"><ShieldAlert size={18} /><span>{zh ? '当前账号没有管理 SMTP 配置的权限，请联系管理员。' : 'You do not have permission to manage SMTP settings.'}</span></div>}
      {loaded && !loadError && view === 'list' && <section className="overflow-hidden rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] shadow-sm"><header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4 sm:px-6"><div><h2 className="text-base font-bold text-slate-800">{zh ? 'SMTP 通道列表' : 'SMTP channels'}</h2><p className="mt-1 text-xs text-slate-500">{profiles.length} {zh ? '个通道；共享继承通道仅可测试。' : `channel${profiles.length === 1 ? '' : 's'}; inherited shared channels are test-only.`}</p></div><span className="rounded-full bg-cyan-50 px-3 py-1 text-xs font-semibold text-cyan-700">{profiles.length}</span></header>{profiles.length === 0 ? <DataTableFrame density="compact" className="overflow-x-auto rounded-md border border-[var(--ui-border)]"><DataTable density="compact" className="min-w-[980px] w-full text-left text-sm"><tbody><tr><td colSpan={6} className="px-4 py-14 text-center"><div className="mx-auto flex max-w-md flex-col items-center"><Mail size={30} className="text-slate-300" /><strong className="mt-3 text-sm font-semibold text-slate-700">{zh ? '还没有 SMTP 通道' : 'No SMTP channels yet'}</strong><p className="mt-1 text-xs text-slate-500">{zh ? '新增通道后，为每个通道设置独立 SMTP 参数、凭据和收件人。' : 'Add a channel to configure independent SMTP settings, credentials, and recipients.'}</p><button type="button" onClick={openCreate} disabled={permissionDenied || recipientPermissionDenied} className="mt-4 rounded-xl bg-cyan-700 px-4 py-2.5 text-xs font-semibold text-white disabled:opacity-50">{zh ? '新增第一个通道' : 'Add the first channel'}</button></div></td></tr></tbody></DataTable></DataTableFrame> : <DataTableFrame density="compact" className="overflow-x-auto rounded-md border border-[var(--ui-border)]"><DataTable density="compact" className="min-w-[980px] w-full text-left text-sm"><thead className="bg-slate-50 text-[11px] font-semibold uppercase tracking-wide text-slate-500"><tr><th className="px-5 py-3">{zh ? '名称' : 'Name'}</th><th className="px-5 py-3">SMTP / {zh ? '发件人' : 'Sender'}</th><th className="px-5 py-3">{zh ? '收件人' : 'Recipients'}</th><th className="px-5 py-3">{zh ? '状态' : 'Status'}</th><th className="px-5 py-3">{zh ? '更新' : 'Updated'}</th><th className="px-5 py-3 text-right">{zh ? '操作' : 'Actions'}</th></tr></thead><tbody className="divide-y divide-slate-100">{profiles.map((profile) => { const groupCount = profile.recipient_targets.filter((target) => target.kind === 'group').length; const userCount = profile.recipient_targets.filter((target) => target.kind === 'user').length; const busy = rowBusyId === profile.id; const rowTest = rowFeedback[profile.id]; return <React.Fragment key={profile.id}><tr className="align-top hover:bg-slate-50/70"><td className="px-5 py-4"><div className="flex items-start gap-2"><div><p className="font-semibold text-slate-800">{profile.display_name || profile.id}</p><p className="mt-1 font-mono text-[11px] text-slate-400">{profile.id}</p></div>{profile.inherited && <span className="rounded-full bg-violet-50 px-2 py-1 text-[10px] font-semibold text-violet-700">{zh ? '共享' : 'Shared'}</span>}</div></td><td className="px-5 py-4"><p className="font-mono text-sm text-slate-700">{profile.host}:{profile.port}</p><p className="mt-1 truncate text-xs text-slate-500">{profile.from_name ? `${profile.from_name} · ` : ''}{profile.from_address || '—'}</p></td><td className="px-5 py-4"><div className="flex flex-wrap gap-2 text-xs text-slate-600"><span className="rounded-full bg-slate-100 px-2 py-1"><Users size={12} className="mr-1 inline" />{groupCount} {zh ? '组' : 'groups'}</span><span className="rounded-full bg-slate-100 px-2 py-1"><UserRound size={12} className="mr-1 inline" />{userCount} {zh ? '人' : 'users'}</span></div>{profile.recipient_targets.length > 0 && <p className="mt-2 max-w-[260px] truncate text-[11px] text-slate-500">{profile.recipient_targets.map((target) => target.kind === 'group' ? target.group_name : userName(target.user_id)).join('、')}</p>}{profile.recipient_targets.length === 0 && <p className="mt-2 text-[11px] text-amber-700">{profile.legacy_primary ? (zh ? '沿用个人通知偏好' : 'Uses personal preferences') : (zh ? '未配置收件人' : 'No recipients')}</p>}</td><td className="px-5 py-4"><span className={'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ' + (profile.enabled ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500')}><span className={'h-1.5 w-1.5 rounded-full ' + (profile.enabled ? 'bg-emerald-500' : 'bg-slate-400')} />{profile.enabled ? (zh ? '已启用' : 'Enabled') : (zh ? '已停用' : 'Disabled')}</span></td><td className="whitespace-nowrap px-5 py-4 text-xs text-slate-500">{formatUpdated(profile.updated_at)}</td><td className="px-5 py-4"><div className="flex flex-wrap justify-end gap-1.5"><button type="button" title={zh ? '发送测试邮件' : 'Send test email'} onClick={() => void quickTest(profile)} disabled={quickTestingId === profile.id || busy || recipientPermissionDenied} className="inline-flex items-center gap-1.5 rounded-lg border border-cyan-200 px-2.5 py-2 text-xs font-semibold text-cyan-800 disabled:opacity-50">{quickTestingId === profile.id ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}{zh ? '测试' : 'Test'}</button>{!profile.inherited && !recipientPermissionDenied && <><button type="button" title={profile.enabled ? (zh ? '停用' : 'Disable') : (zh ? '启用' : 'Enable')} onClick={() => void toggleEnabled(profile)} disabled={busy} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-2 text-xs font-semibold text-slate-600 disabled:opacity-50">{busy ? <Loader2 size={14} className="animate-spin" /> : <Power size={14} />}{profile.enabled ? (zh ? '停用' : 'Disable') : (zh ? '启用' : 'Enable')}</button><button type="button" onClick={() => openEdit(profile)} disabled={busy} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-2 text-xs font-semibold text-slate-600 disabled:opacity-50"><Edit3 size={14} />{zh ? '编辑' : 'Edit'}</button><button type="button" onClick={() => void deleteProfile(profile)} disabled={busy} className="inline-flex items-center gap-1.5 rounded-lg border border-rose-200 px-2.5 py-2 text-xs font-semibold text-rose-700 disabled:opacity-50"><Trash2 size={14} />{zh ? '删除' : 'Delete'}</button></>}</div></td></tr>{rowTest && <tr><td colSpan={6} className="bg-slate-50 px-5 py-2"><span role="status" className={'inline-flex items-center rounded-lg px-2.5 py-1.5 text-[11px] ' + (rowTest.tone === 'success' ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700')}>{rowTest.message}</span></td></tr>}</React.Fragment>; })}</tbody></DataTable></DataTableFrame>}</section>}
      {loaded && !loadError && view === 'wizard' && <>
        <section aria-label={zh ? '邮件配置步骤' : 'Email setup steps'} className="grid gap-2 rounded-2xl border border-slate-200 bg-white p-3 shadow-sm sm:grid-cols-3">{WIZARD_STEPS.map((step) => { const done = step.number < currentStep; const current = step.number === currentStep; return <button key={step.number} type="button" disabled={!done || locked} onClick={() => { if (done) { setCurrentStep(step.number); setFeedback(null); } }} aria-current={current ? 'step' : undefined} className={'flex items-center gap-3 rounded-xl border p-3 text-left ' + (current ? 'border-cyan-300 bg-cyan-50' : done ? 'border-emerald-200 bg-emerald-50/50' : 'border-slate-100 bg-slate-50')}><span className={'flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-bold ' + (current ? 'bg-cyan-700 text-white' : done ? 'bg-emerald-600 text-white' : 'bg-white text-slate-400')}>{done ? <CheckCircle2 size={17} /> : step.number}</span><span><span className="block text-sm font-bold text-slate-800">{zh ? step.zh : step.en}</span><span className="text-[11px] text-slate-500">{zh ? step.captionZh : step.captionEn}</span></span>{step.number < 3 && <ArrowRight size={15} className="ml-auto hidden text-slate-300 sm:block" />}</button>; })}</section>
        <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-md"><header className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-100 bg-slate-50/70 px-5 py-4 sm:px-7"><div><div className="flex flex-wrap items-center gap-2"><h2 className="text-base font-bold text-slate-800">{editingId ? (zh ? '编辑 SMTP 通道' : 'Edit SMTP channel') : (zh ? '新增 SMTP 通道' : 'Add SMTP channel')}</h2><span className="rounded-full bg-cyan-50 px-2.5 py-1 text-[11px] font-semibold text-cyan-700">{zh ? `第 ${currentStep} 步 / 3 步` : `Step ${currentStep} of 3`}</span></div><p className="mt-1 text-xs text-slate-500">{zh ? '凭据不会在页面中显示；留空密码可保持已保存的凭据。' : 'Credentials are never displayed; leave the password blank to keep the saved credential.'}</p></div><span className="text-xs font-semibold text-slate-500">{zh ? WIZARD_STEPS[currentStep - 1].zh : WIZARD_STEPS[currentStep - 1].en}</span></header><div className="space-y-5 p-5 sm:p-6 lg:p-7">
          {currentStep === 1 && <div className="space-y-5"><div><h3 className="text-sm font-bold text-slate-800">{zh ? '1. 命名通道并选择邮箱服务' : '1. Name the channel and choose a provider'}</h3><p className="mt-1 text-xs text-slate-500">{zh ? '每个 SMTP 通道拥有独立参数、凭据和收件人。' : 'Each SMTP channel has independent settings, credentials, and recipients.'}</p></div><label className="block"><span className={fieldLabelClass}>{zh ? '通道名称' : 'Channel name'} *</span><input value={settings.display_name} disabled={locked} onChange={(event) => updateField('display_name', event.target.value)} placeholder={zh ? '例如：生产告警邮箱' : 'e.g. Production alerts'} className={inputClass} aria-invalid={Boolean(fieldErrors.display_name)} />{fieldError('display_name')}</label><section aria-label={zh ? '选择邮箱服务商' : 'Choose a mail provider'} className="space-y-3"><div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between"><label className="relative block min-w-0 flex-1 xl:max-w-md"><span className="sr-only">{zh ? '搜索邮箱服务商' : 'Search providers'}</span><Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" /><input value={providerSearch} disabled={locked} onChange={(event) => setProviderSearch(event.target.value)} placeholder={zh ? '搜索邮箱名称或 SMTP 主机' : 'Search provider or SMTP hostname'} className="w-full rounded-xl border border-slate-200 bg-white py-2.5 pl-9 pr-3 text-sm text-slate-700 outline-none placeholder:text-slate-400 focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100 disabled:bg-slate-50" /></label><div role="group" aria-label={zh ? '邮箱服务类别' : 'Provider categories'} className="flex flex-wrap gap-1 rounded-xl bg-slate-100 p-1">{providerGroups.map((group) => { const active = providerGroup === group && !normalizedProviderSearch; const count = SMTP_PRESETS.filter((preset) => preset.group === group).length; return <button key={group} type="button" aria-pressed={active} disabled={locked} onClick={() => { setProviderGroup(group); setProviderSearch(''); }} className={'inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold ' + (active ? 'bg-white text-cyan-800 shadow-sm' : 'text-slate-500') + ' disabled:opacity-50'}><span>{zh ? groupNames[group].zh : groupNames[group].en}</span><span className="rounded-full bg-white/70 px-1.5 py-0.5 text-[10px] text-slate-400">{count}</span></button>; })}</div></div>{normalizedProviderSearch && <p className="text-xs text-slate-500">{zh ? `搜索所有类别 · ${visiblePresets.length} 个结果` : `Searching all categories · ${visiblePresets.length} results`}</p>}<div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">{visiblePresets.map((preset) => { const selected = selectedPresetId === preset.id; const encryption = preset.security === 'ssl' ? 'SSL/TLS' : preset.security === 'starttls' ? 'STARTTLS' : (zh ? '无加密' : 'No TLS'); return <button key={preset.id} type="button" disabled={locked} aria-pressed={selected} onClick={() => applyPreset(preset.id)} className={'flex min-h-[104px] flex-col justify-between rounded-xl border p-3.5 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 disabled:opacity-60 ' + (selected ? 'border-cyan-400 bg-cyan-50/80 ring-2 ring-cyan-100' : 'border-slate-200 bg-white hover:border-slate-300')}><span className="flex min-w-0 items-start gap-3"><ProviderMark providerId={preset.id} /><span className="min-w-0 flex-1"><span className="flex items-center justify-between gap-2 text-sm font-bold text-slate-800">{zh ? preset.labelZh : preset.labelEn}{selected && <CheckCircle2 size={16} className="shrink-0 text-cyan-700" />}</span><span className="mt-1 block truncate font-mono text-[11px] text-slate-500">{preset.host || (zh ? '填写自建 SMTP 主机' : 'Enter your SMTP host')}</span></span></span><span className="mt-3 flex items-center justify-end border-t border-slate-100 pt-2.5 text-[10px] font-semibold text-slate-500"><span className="rounded-full bg-slate-100 px-2 py-1 text-slate-600">{preset.port} · {encryption}</span></span></button>; })}</div></section><div className="rounded-xl border border-slate-200 bg-slate-50 p-4"><div className="flex flex-wrap items-start justify-between gap-3"><p className="flex-1 text-xs leading-5 text-slate-600">{zh ? activePreset.noteZh : activePreset.noteEn}</p>{activePreset.helpUrl && <a href={activePreset.helpUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs font-semibold text-cyan-800">{zh ? '官方配置说明' : 'Provider guide'}<ArrowUpRight size={13} /></a>}</div>{(selectedPresetId === 'google' || selectedPresetId === 'outlook' || selectedPresetId === 'microsoft365') && <p className="mt-3 rounded-lg bg-amber-50 p-3 text-[11px] leading-5 text-amber-900">{zh ? '认证限制：当前系统只支持 SMTP 用户名/密码，尚未实现 OAuth2 / Modern Auth。这些服务可能连接成功，但认证阶段仍会失败。' : 'Authentication limit: this system supports SMTP username/password only, not OAuth2 / Modern Auth. Connection may work while authentication fails.'}</p>}</div><div className="grid gap-4 sm:grid-cols-2"><label className="sm:col-span-2"><span className={fieldLabelClass}>SMTP {zh ? '主机' : 'host'} *</span><input value={settings.host} disabled={locked} onChange={(event) => updateField('host', event.target.value)} placeholder="smtp.example.com" className={inputClass} aria-invalid={Boolean(fieldErrors.host)} />{fieldError('host')}</label><label><span className={fieldLabelClass}>{zh ? '端口' : 'Port'} *</span><input type="number" min={1} max={65535} value={settings.port} disabled={locked} onChange={(event) => updateField('port', Number(event.target.value))} className={inputClass} aria-invalid={Boolean(fieldErrors.port)} />{fieldError('port')}</label><label><span className={fieldLabelClass}>{zh ? '加密方式' : 'Encryption'}</span><select value={settings.security} disabled={locked} onChange={(event) => updateField('security', event.target.value as SmtpSettingsDraft['security'])} className={inputClass}><option value="ssl">SSL/TLS</option><option value="starttls">STARTTLS</option><option value="none">{zh ? '无加密（仅受控测试网络）' : 'None (controlled test network only)'}</option></select>{!sslOnlyCompatible && <p role="alert" className="mt-2 text-xs text-rose-600">{zh ? '该邮箱要求 SSL/TLS + 465 或 587。' : 'This provider requires SSL/TLS on port 465 or 587.'}</p>}{fieldError('security')}</label></div></div>}
          {currentStep === 2 && <div className="space-y-5"><div><h3 className="text-sm font-bold text-slate-800">{zh ? '2. 填写账号、发件人和收件人' : '2. Enter credentials, sender, and recipients'}</h3><p className="mt-1 text-xs text-slate-500">{zh ? '密码保存后不会再次显示。' : 'Saved passwords are never displayed again.'}</p></div><div className="grid gap-4 sm:grid-cols-2"><label><span className={fieldLabelClass}>{zh ? 'SMTP 用户名' : 'SMTP username'}{activePreset.requiresUsername ? ' *' : ''}</span><input value={settings.username} disabled={locked} onChange={(event) => updateField('username', event.target.value)} placeholder={zh ? '通常填写完整邮箱地址' : 'Usually your full email address'} className={inputClass} autoComplete="username" aria-invalid={Boolean(fieldErrors.username)} />{fieldError('username')}</label><label><span className={fieldLabelClass}>{isQqMail ? (zh ? 'SMTP 授权码' : 'SMTP app password') : (zh ? 'SMTP 密码 / 授权码' : 'SMTP password / app password')}{smtpAuthenticationExpected ? ' *' : ''}</span><input type="password" value={settings.password} disabled={locked} onChange={(event) => updateField('password', event.target.value)} placeholder={settings.has_password && !credentialsNeedRefresh ? (zh ? '留空保持已保存的密码' : 'Leave blank to keep saved password') : (zh ? '输入服务商授权码或 SMTP 密码' : 'Enter app password or SMTP password')} className={inputClass} autoComplete="new-password" aria-invalid={Boolean(fieldErrors.password)} />{fieldError('password')}<span className="mt-1 block text-[11px] text-slate-500">{!smtpAuthenticationExpected ? (zh ? '无需认证时可以留空。' : 'Leave blank when authentication is not required.') : settings.has_password && !credentialsNeedRefresh ? (zh ? '已保存，留空可保持不变。' : 'Saved; leave blank to keep it.') : (zh ? '密码只会安全保存，不会回显。' : 'The password is stored securely and never echoed.')}</span></label><label><span className={fieldLabelClass}>{zh ? '发件人邮箱' : 'From address'} *</span><input type="email" value={settings.from_address} disabled={locked} onChange={(event) => updateField('from_address', event.target.value)} placeholder={settings.username || 'alerts@example.com'} className={inputClass} aria-invalid={Boolean(fieldErrors.from_address)} />{fieldError('from_address')}</label><label><span className={fieldLabelClass}>{zh ? '发件人名称' : 'From name'}</span><input value={settings.from_name} disabled={locked} onChange={(event) => updateField('from_name', event.target.value)} className={inputClass} placeholder="Nexora" /></label><label className="sm:col-span-2"><span className={fieldLabelClass}>{zh ? '回复地址（可选）' : 'Reply-to (optional)'}</span><input type="email" value={settings.reply_to} disabled={locked} onChange={(event) => updateField('reply_to', event.target.value)} className={inputClass} aria-invalid={Boolean(fieldErrors.reply_to)} />{fieldError('reply_to')}</label></div>{renderRecipientPicker()}</div>}
          {currentStep === 3 && <div className="space-y-5"><div><h3 className="text-sm font-bold text-slate-800">{zh ? '3. 测试连接、发送邮件，再启用告警' : '3. Test connection, send mail, then enable alerts'}</h3><p className="mt-1 text-xs text-slate-500">{zh ? '连接测试只检查 SMTP/TLS/认证；邮件测试使用你填写的收件人。' : 'Connection testing checks SMTP/TLS/authentication; email testing uses the recipient you enter.'}</p></div><div className="grid gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-4 sm:grid-cols-2 lg:grid-cols-4"><div><span className="text-[11px] text-slate-400">{zh ? '邮箱服务' : 'Provider'}</span><p className="mt-1 truncate text-sm font-semibold text-slate-700">{zh ? activePreset.labelZh : activePreset.labelEn}</p></div><div><span className="text-[11px] text-slate-400">SMTP</span><p className="mt-1 break-all font-mono text-sm text-slate-700">{settings.host}:{settings.port}</p></div><div><span className="text-[11px] text-slate-400">{zh ? '收件人目标' : 'Recipients'}</span><p className="mt-1 text-sm font-semibold text-slate-700">{recipientTargets.length}</p></div><div><span className="text-[11px] text-slate-400">{zh ? '发件人' : 'Sender'}</span><p className="mt-1 truncate text-sm font-semibold text-slate-700">{settings.from_address || '—'}</p></div></div><label className="block"><span className={fieldLabelClass}>{zh ? '测试收件人（可选）' : 'Test recipient (optional)'}</span><input type="email" value={recipient} disabled={locked} onChange={(event) => { setRecipient(event.target.value); setTestAccepted(false); setDeliveryConfirmed(false); setFieldErrors((current) => { const next = { ...current }; delete next.recipient; return next; }); }} placeholder={zh ? '留空使用当前管理员邮箱' : 'Leave blank to use the current administrator email'} className={inputClass} aria-invalid={Boolean(fieldErrors.recipient)} />{fieldError('recipient')}</label><div className="grid gap-3 sm:grid-cols-2"><div className={'rounded-xl border p-3 ' + (connectionTested ? 'border-emerald-200 bg-emerald-50' : 'border-slate-200 bg-white')}><p className="flex items-center gap-2 text-sm font-semibold text-slate-800"><Server size={15} />{zh ? 'SMTP 连接' : 'SMTP connection'}{connectionTested && <CheckCircle2 size={15} className="ml-auto text-emerald-600" />}</p><p className="mt-1 text-[11px] text-slate-500">{connectionTested ? (zh ? '连接和认证检查成功。' : 'Connection and authentication succeeded.') : (zh ? '不发送邮件，验证网络、TLS 和账号认证。' : 'Checks network, TLS, and authentication.')}</p></div><div className={'rounded-xl border p-3 ' + (testAccepted ? 'border-emerald-200 bg-emerald-50' : 'border-slate-200 bg-white')}><p className="flex items-center gap-2 text-sm font-semibold text-slate-800"><Send size={15} />{zh ? '邮件投递' : 'Email delivery'}{testAccepted && <CheckCircle2 size={15} className="ml-auto text-emerald-600" />}</p><p className="mt-1 text-[11px] text-slate-500">{testAccepted ? (zh ? 'SMTP 已接受邮件，请检查收件箱。' : 'SMTP accepted the message; check your inbox.') : (zh ? '确认目标邮箱可以收到测试信。' : 'Confirms the target mailbox receives the test.')}</p></div></div><div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900">{zh ? '确认在收件箱看到测试邮件后，再勾选确认并启用正式告警。' : 'Confirm the test email arrived before enabling real alerts.'}{testAccepted && <label className="mt-3 flex cursor-pointer items-start gap-2 rounded-lg bg-white p-2.5 font-semibold"><input type="checkbox" checked={deliveryConfirmed} disabled={locked} onChange={(event) => setDeliveryConfirmed(event.target.checked)} className="mt-1" /><span>{zh ? '我已确认收到测试邮件' : 'I confirmed the test email arrived'}</span></label>}</div><div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-slate-200 p-4"><div><p className="text-sm font-bold text-slate-800">{zh ? '正式告警投递' : 'Real alert delivery'}</p><p className="mt-1 text-xs text-slate-500">{settings.enabled ? (zh ? '当前已启用。' : 'Currently enabled.') : (zh ? '确认测试邮件后开启并保存。' : 'Turn on and save after confirming delivery.')}</p></div><label className={'flex items-center gap-3 rounded-xl border px-3 py-2 text-sm font-semibold ' + (settings.enabled ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-slate-200 bg-white text-slate-600')}><span>{settings.enabled ? (zh ? '已启用' : 'Enabled') : (zh ? '启用邮件告警' : 'Enable email alerts')}</span><input type="checkbox" checked={settings.enabled} disabled={locked || (!settings.enabled && !deliveryConfirmed)} onChange={(event) => updateField('enabled', event.target.checked)} className="h-4 w-4 accent-emerald-600" /></label></div><details className="rounded-xl border border-slate-200"><summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-slate-700">{zh ? '高级参数：超时与发送速率' : 'Advanced: timeouts and send rate'}</summary><div className="grid gap-4 border-t bg-slate-50 p-4 sm:grid-cols-3"><label><span className={fieldLabelClass}>{zh ? '连接超时（秒）' : 'Connect timeout (sec)'}</span><input type="number" min={1} max={120} value={settings.connect_timeout_seconds} disabled={locked} onChange={(event) => updateField('connect_timeout_seconds', Number(event.target.value))} className={inputClass} />{fieldError('connect_timeout_seconds')}</label><label><span className={fieldLabelClass}>{zh ? '发送超时（秒）' : 'Send timeout (sec)'}</span><input type="number" min={1} max={120} value={settings.send_timeout_seconds} disabled={locked} onChange={(event) => updateField('send_timeout_seconds', Number(event.target.value))} className={inputClass} />{fieldError('send_timeout_seconds')}</label><label><span className={fieldLabelClass}>{zh ? '每分钟发送上限' : 'Rate limit per minute'}</span><input type="number" min={1} max={10000} value={settings.rate_limit_per_minute} disabled={locked} onChange={(event) => updateField('rate_limit_per_minute', Number(event.target.value))} className={inputClass} />{fieldError('rate_limit_per_minute')}</label></div></details></div>}
        </div><footer className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 bg-slate-50/60 px-5 py-4 sm:px-7"><div className="flex gap-2">{currentStep > 1 && <button type="button" onClick={() => { setCurrentStep((step) => step === 3 ? 2 : 1); setFeedback(null); }} disabled={locked} className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-600"><ArrowLeft size={15} />{zh ? '上一步' : 'Back'}</button>}{currentStep < 3 && <button type="button" onClick={() => { const errors = validate(currentStep === 1 ? 'connection' : 'account'); setFieldErrors(errors); if (Object.keys(errors).length === 0) { setCurrentStep((step) => step === 1 ? 2 : 3); setFeedback(null); } else setFeedback({ tone: 'error', message: zh ? '请先修正标记的字段，再继续下一步。' : 'Fix the highlighted fields before continuing.' }); }} disabled={locked} className="inline-flex items-center gap-2 rounded-xl bg-cyan-700 px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{zh ? '下一步' : 'Next'}<ArrowRight size={15} /></button>}</div>{currentStep === 3 && <div className="flex flex-wrap items-center gap-2"><button type="button" onClick={() => void testConnection()} disabled={locked} className="inline-flex items-center gap-2 rounded-xl border border-cyan-200 bg-white px-3.5 py-2.5 text-sm font-semibold text-cyan-800 disabled:opacity-50"><Server size={15} />{zh ? '测试连接' : 'Test connection'}</button><button type="button" onClick={() => void saveProfile()} disabled={locked} className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm font-semibold text-slate-700 disabled:opacity-50"><Save size={15} />{zh ? '仅保存' : 'Save'}</button><button type="button" onClick={() => void testSettings()} disabled={locked} className="inline-flex items-center gap-2 rounded-xl bg-cyan-700 px-3.5 py-2.5 text-sm font-semibold text-white disabled:opacity-50"><Send size={15} />{dirty ? (zh ? '保存并发送测试邮件' : 'Save and send test') : (zh ? '发送测试邮件' : 'Send test email')}</button></div>}</footer></section>{feedback && <div role="status" className={'flex items-start gap-3 rounded-xl border px-4 py-3 text-sm leading-6 ' + (feedback.tone === 'success' ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-rose-200 bg-rose-50 text-rose-700')}>{feedback.tone === 'success' ? <CheckCircle2 size={17} /> : <AlertCircle size={17} />}{feedback.message}</div>}</>}
    </div>
  </div>;
};

export default NotificationChannelSettingsPage;
