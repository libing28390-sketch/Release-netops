import React, { useCallback, useEffect, useState } from 'react';
import {
  AlertCircle,
  Bell,
  CheckCircle2,
  ChevronDown,
  Loader2,
  Mail,
  RefreshCw,
  Save,
  Send,
  Server,
  ShieldAlert,
} from 'lucide-react';
import PageHero from '../components/PageHero';
import { ApiError, apiRequest } from '../api/http';

interface SmtpSettingsDraft {
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
type ToastTone = 'success' | 'error' | 'info';

interface NotificationChannelSettingsPageProps {
  language: string;
  showToast: (message: string, type?: ToastTone) => void;
}

const EMPTY_SETTINGS: SmtpSettingsDraft = {
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

const getErrorMessage = (error: unknown, zh: boolean, action: 'load' | 'save' | 'test'): string => {
  if (error instanceof ApiError) {
    if (error.status === 401) return zh ? '登录已失效，请重新登录。' : 'Your session has expired. Please sign in again.';
    if (error.status === 403) return zh ? '你没有管理 SMTP 邮件通道的权限。' : 'You do not have permission to manage the SMTP email channel.';
    if (error.status >= 500) return zh ? '邮件服务暂时不可用，请稍后重试。' : 'The mail service is temporarily unavailable. Please try again.';
    const cleanMessage = error.message.replace(/\s*\(Request ID:.*\)$/i, '').trim();
    if (cleanMessage) return cleanMessage;
  }
  if (error instanceof Error && error.message.trim()) return error.message;
  if (action === 'load') return zh ? 'SMTP 配置加载失败，请重试。' : 'Failed to load SMTP settings. Please retry.';
  if (action === 'save') return zh ? 'SMTP 配置保存失败，请重试。' : 'Failed to save SMTP settings. Please retry.';
  return zh ? '测试邮件发送失败，请检查配置后重试。' : 'The test email could not be sent. Check the settings and retry.';
};

const NotificationChannelSettingsPage: React.FC<NotificationChannelSettingsPageProps> = ({ language, showToast }) => {
  const zh = language === 'zh';
  const [settings, setSettings] = useState<SmtpSettingsDraft>(EMPTY_SETTINGS);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [permissionDenied, setPermissionDenied] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [recipient, setRecipient] = useState('');
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [dirty, setDirty] = useState(false);

  const loadSettings = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    setFeedback(null);
    try {
      const payload = await apiRequest<{ smtp?: Partial<SmtpSettingsDraft> }>('/api/alerts/notification-channels');
      const smtp = payload.smtp;
      if (!smtp) throw new Error(zh ? '响应中缺少 SMTP 配置。' : 'The response did not include SMTP settings.');
      setSettings({
        enabled: Boolean(smtp.enabled),
        host: String(smtp.host || ''),
        port: Number(smtp.port || 587),
        security: smtp.security === 'ssl' || smtp.security === 'none' ? smtp.security : 'starttls',
        username: String(smtp.username || ''),
        password: '',
        from_address: String(smtp.from_address || ''),
        from_name: String(smtp.from_name || 'Nexora'),
        reply_to: String(smtp.reply_to || ''),
        connect_timeout_seconds: Number(smtp.connect_timeout_seconds || 10),
        send_timeout_seconds: Number(smtp.send_timeout_seconds || 20),
        rate_limit_per_minute: Number(smtp.rate_limit_per_minute || 60),
        has_password: Boolean(smtp.has_password),
        configured: Boolean(smtp.configured),
        updated_at: smtp.updated_at || null,
      });
      setLoaded(true);
      setPermissionDenied(false);
      setFieldErrors({});
      setDirty(false);
    } catch (error) {
      setLoadError(getErrorMessage(error, zh, 'load'));
      if (error instanceof ApiError && error.status === 403) setPermissionDenied(true);
    } finally {
      setLoading(false);
    }
  }, [zh]);

  useEffect(() => { void loadSettings(); }, [loadSettings]);

  const validate = useCallback((includeRecipient: boolean): Record<string, string> => {
    const errors: Record<string, string> = {};
    const port = Number(settings.port);
    const connectTimeout = Number(settings.connect_timeout_seconds);
    const sendTimeout = Number(settings.send_timeout_seconds);
    const rateLimit = Number(settings.rate_limit_per_minute);
    if (!settings.host.trim()) errors.host = zh ? '请输入 SMTP 主机。' : 'SMTP host is required.';
    if (!Number.isInteger(port) || port < 1 || port > 65535) errors.port = zh ? '端口须为 1–65535 的整数。' : 'Port must be an integer from 1 to 65535.';
    if (!settings.from_address.trim()) errors.from_address = zh ? '请输入发件人邮箱。' : 'From address is required.';
    else if (!EMAIL_PATTERN.test(settings.from_address.trim())) errors.from_address = zh ? '请输入有效的邮箱地址。' : 'Enter a valid email address.';
    if (settings.reply_to.trim() && !EMAIL_PATTERN.test(settings.reply_to.trim())) errors.reply_to = zh ? '请输入有效的回复邮箱。' : 'Enter a valid reply-to address.';
    if (!settings.has_password && !settings.password.trim() && settings.username.trim()) errors.password = zh ? '首次配置 SMTP 用户名时请输入密码。' : 'Enter a password when configuring SMTP authentication for the first time.';
    if (!Number.isInteger(connectTimeout) || connectTimeout < 1 || connectTimeout > 120) errors.connect_timeout_seconds = zh ? '连接超时须为 1–120 秒。' : 'Connect timeout must be 1–120 seconds.';
    if (!Number.isInteger(sendTimeout) || sendTimeout < 1 || sendTimeout > 120) errors.send_timeout_seconds = zh ? '发送超时须为 1–120 秒。' : 'Send timeout must be 1–120 seconds.';
    if (!Number.isInteger(rateLimit) || rateLimit < 1 || rateLimit > 10000) errors.rate_limit_per_minute = zh ? '速率上限须为 1–10000。' : 'Rate limit must be from 1 to 10000.';
    if (includeRecipient && recipient.trim() && !EMAIL_PATTERN.test(recipient.trim())) errors.recipient = zh ? '测试收件人须为有效的邮箱地址。' : 'Test recipient must be a valid email address.';
    return errors;
  }, [recipient, settings, zh]);

  const updateField = <K extends keyof SmtpSettingsDraft>(field: K, value: SmtpSettingsDraft[K]) => {
    setSettings((current) => ({ ...current, [field]: value }));
    setFieldErrors((current) => {
      if (!current[field]) return current;
      const next = { ...current };
      delete next[field];
      return next;
    });
    setDirty(true);
    setFeedback(null);
  };

  const saveSettings = async () => {
    if (permissionDenied) return;
    const errors = validate(false);
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) {
      setFeedback({ tone: 'error', message: zh ? '请先修正标记的字段。' : 'Fix the highlighted fields before saving.' });
      showToast(zh ? 'SMTP 配置校验未通过' : 'SMTP settings are invalid', 'info');
      return;
    }
    setSaving(true);
    setFeedback(null);
    try {
      const payload: Record<string, unknown> = {
        enabled: settings.enabled,
        host: settings.host.trim(),
        port: Number(settings.port),
        security: settings.security,
        username: settings.username.trim(),
        from_address: settings.from_address.trim(),
        from_name: settings.from_name.trim() || 'Nexora',
        reply_to: settings.reply_to.trim(),
        connect_timeout_seconds: Number(settings.connect_timeout_seconds),
        send_timeout_seconds: Number(settings.send_timeout_seconds),
        rate_limit_per_minute: Number(settings.rate_limit_per_minute),
      };
      if (settings.password.trim()) payload.password = settings.password.trim();
      const saved = await apiRequest<Partial<SmtpSettingsDraft>>('/api/alerts/notification-channels/email', {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
      setSettings((current) => ({ ...current, ...saved, password: '', has_password: saved.has_password ?? current.has_password, configured: saved.configured ?? true }));
      setFeedback({ tone: 'success', message: zh ? 'SMTP 配置已保存，密码输入已清空。' : 'SMTP settings saved. The password field was cleared.' });
      setPermissionDenied(false);
      setDirty(false);
      showToast(zh ? 'SMTP 邮件通道已保存' : 'SMTP email channel saved', 'success');
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) setPermissionDenied(true);
      const message = getErrorMessage(error, zh, 'save');
      setFeedback({ tone: 'error', message });
      showToast(message, 'error');
    } finally {
      setSaving(false);
    }
  };

  const testSettings = async () => {
    if (permissionDenied) return;
    if (dirty) {
      const message = zh ? '检测到未保存的配置改动，请先保存后再发送测试邮件。' : 'There are unsaved settings changes. Save them before sending a test email.';
      setFeedback({ tone: 'error', message });
      showToast(message, 'info');
      return;
    }
    const errors = validate(true);
    if (!settings.enabled) errors.enabled = zh ? '请先启用 SMTP 通道。' : 'Enable the SMTP channel before testing.';
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) {
      setFeedback({ tone: 'error', message: zh ? '测试前请修正标记的字段并启用 SMTP。' : 'Fix the highlighted fields and enable SMTP before testing.' });
      showToast(zh ? '测试前校验未通过' : 'Validation failed before test', 'info');
      return;
    }
    setTesting(true);
    setFeedback(null);
    try {
      await apiRequest('/api/alerts/notification-channels/email/test', {
        method: 'POST',
        body: JSON.stringify({ recipient: recipient.trim() || undefined }),
      });
      const message = zh ? '测试邮件发送调用已成功，请检查目标邮箱；API 成功不保证最终送达。' : 'The test email send call succeeded. Check the target mailbox; API success does not guarantee final delivery.';
      setFeedback({ tone: 'success', message });
      showToast(message, 'success');
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) setPermissionDenied(true);
      const message = getErrorMessage(error, zh, 'test');
      setFeedback({ tone: 'error', message });
      showToast(message, 'error');
    } finally {
      setTesting(false);
    }
  };

  const fieldError = (name: string) => fieldErrors[name] && <p className="mt-1 text-xs text-rose-600">{fieldErrors[name]}</p>;
  const locked = !loaded || permissionDenied || saving || testing;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto bg-slate-50">
      <PageHero
        icon={Bell}
        eyebrow={zh ? '平台管理' : 'Platform management'}
        title={zh ? '邮件通知' : 'Email notifications'}
        subtitle={zh ? '配置告警邮件投递通道并发送测试邮件。' : 'Configure alert email delivery and send a test message.'}
        actions={(
          <button type="button" onClick={() => void loadSettings()} disabled={loading || saving || testing || dirty} title={dirty ? (zh ? '请先保存或撤销未保存的改动' : 'Save or discard unsaved changes first') : undefined} className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-600 shadow-sm hover:border-cyan-300 hover:text-cyan-700 disabled:opacity-50">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />{zh ? '刷新' : 'Refresh'}
          </button>
        )}
      />

      <div className="mx-auto w-full max-w-5xl space-y-5 p-4 sm:p-6">
        {loading && (
          <div className="flex items-center gap-3 rounded-2xl border border-cyan-100 bg-white px-5 py-6 text-sm text-cyan-800 shadow-sm">
            <Loader2 size={18} className="animate-spin" />{zh ? '正在读取邮件通道配置…' : 'Loading email channel settings…'}
          </div>
        )}

        {loadError && (
          <div role="alert" className="flex flex-wrap items-center gap-3 rounded-2xl border border-rose-200 bg-white px-5 py-4 text-sm text-rose-700 shadow-sm">
            <AlertCircle size={18} className="shrink-0" />
            <span className="min-w-0 flex-1">{loadError}</span>
            {!permissionDenied && <button type="button" onClick={() => void loadSettings()} disabled={loading} className="rounded-lg border border-rose-200 px-3 py-1.5 text-xs font-semibold hover:bg-rose-50 disabled:opacity-50">{zh ? '重试' : 'Retry'}</button>}
          </div>
        )}

        {permissionDenied && (
          <div role="alert" className="flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm leading-6 text-amber-800">
            <ShieldAlert size={18} className="mt-0.5 shrink-0" />
            <span>{zh ? '当前账号没有管理 SMTP 配置的权限，请联系管理员。' : 'Your account cannot manage SMTP settings. Ask an administrator to configure this channel.'}</span>
          </div>
        )}

        {loaded && !loadError && (
          <>
            <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm" aria-labelledby="smtp-settings-title">
              <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-100 px-5 py-4 sm:px-6">
                <div className="flex min-w-0 items-start gap-3">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-cyan-50 text-cyan-700"><Mail size={19} /></span>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 id="smtp-settings-title" className="text-base font-bold text-slate-800">{zh ? 'SMTP 邮件通道' : 'SMTP email channel'}</h2>
                      <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${settings.enabled ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>{settings.enabled ? (zh ? '已启用' : 'Enabled') : (zh ? '未启用' : 'Disabled')}</span>
                      <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${settings.configured ? 'bg-cyan-50 text-cyan-700' : 'bg-amber-50 text-amber-700'}`}>{settings.configured ? (zh ? '配置完整' : 'Configured') : (zh ? '待配置' : 'Needs setup')}</span>
                    </div>
                    <p className="mt-1 text-xs leading-5 text-slate-500">{zh ? '告警规则选择“邮件”后，系统会使用此通道异步发送，并在告警历史中记录失败与重试。' : 'Rules selecting Email use this channel asynchronously; failures and retries remain visible in alert history.'}</p>
                  </div>
                </div>
                <label className={`flex shrink-0 items-center gap-2 text-sm font-semibold ${permissionDenied ? 'text-slate-400' : 'text-slate-600'}`}>
                  <input type="checkbox" checked={settings.enabled} disabled={locked} onChange={(event) => updateField('enabled', event.target.checked)} className="h-4 w-4 accent-cyan-600" />
                  {zh ? '启用邮件告警' : 'Enable email alerts'}
                </label>
              </div>

              <div className="grid gap-5 p-5 sm:p-6 lg:grid-cols-2">
                <section className="rounded-xl border border-slate-200 bg-slate-50/70 p-4" aria-labelledby="smtp-connection-title">
                  <div className="mb-4 flex items-center gap-2"><Server size={16} className="text-cyan-700" /><h3 id="smtp-connection-title" className="text-sm font-semibold text-slate-700">{zh ? '服务器连接' : 'Server connection'}</h3></div>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <label className="sm:col-span-2"><span className={fieldLabelClass}>{zh ? 'SMTP 主机' : 'SMTP host'} <span className="text-rose-500">*</span></span><input value={settings.host} disabled={locked} onChange={(event) => updateField('host', event.target.value)} className={inputClass} placeholder="smtp.example.com" aria-invalid={Boolean(fieldErrors.host)} />{fieldError('host')}</label>
                    <label><span className={fieldLabelClass}>{zh ? '端口' : 'Port'} <span className="text-rose-500">*</span></span><input type="number" min={1} max={65535} value={settings.port} disabled={locked} onChange={(event) => updateField('port', Number(event.target.value))} className={inputClass} aria-invalid={Boolean(fieldErrors.port)} />{fieldError('port')}</label>
                    <label><span className={fieldLabelClass}>{zh ? '安全方式' : 'Security'}</span><select value={settings.security} disabled={locked} onChange={(event) => updateField('security', event.target.value as SmtpSettingsDraft['security'])} className={inputClass}><option value="starttls">STARTTLS</option><option value="ssl">SSL</option><option value="none">{zh ? '无加密' : 'None'}</option></select></label>
                    <label className="sm:col-span-2"><span className={fieldLabelClass}>{zh ? 'SMTP 用户名（可选）' : 'SMTP username (optional)'}</span><input value={settings.username} disabled={locked} onChange={(event) => updateField('username', event.target.value)} className={inputClass} autoComplete="username" /></label>
                    <label className="sm:col-span-2"><span className={`${fieldLabelClass} flex items-center justify-between`}><span>{zh ? 'SMTP 密码' : 'SMTP password'}</span><span className={`font-normal ${settings.has_password ? 'text-emerald-600' : 'text-amber-600'}`}>{settings.has_password ? (zh ? '已保存，留空保持不变' : 'Saved; blank keeps it') : (zh ? '尚未保存' : 'Not saved')}</span></span><input type="password" value={settings.password} disabled={locked} onChange={(event) => updateField('password', event.target.value)} placeholder={settings.has_password ? (zh ? '留空保持已保存密码' : 'Leave blank to keep saved password') : (zh ? '输入 SMTP 密码（如需认证）' : 'Enter SMTP password if authentication is required')} className={inputClass} autoComplete="new-password" aria-invalid={Boolean(fieldErrors.password)} />{fieldError('password')}</label>
                  </div>
                </section>

                <section className="rounded-xl border border-slate-200 bg-slate-50/70 p-4" aria-labelledby="smtp-sender-title">
                  <div className="mb-4 flex items-center gap-2"><Send size={16} className="text-emerald-700" /><h3 id="smtp-sender-title" className="text-sm font-semibold text-slate-700">{zh ? '发件人和测试' : 'Sender and test'}</h3></div>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <label className="sm:col-span-2"><span className={fieldLabelClass}>{zh ? '发件人邮箱' : 'From address'} <span className="text-rose-500">*</span></span><input type="email" value={settings.from_address} disabled={locked} onChange={(event) => updateField('from_address', event.target.value)} className={inputClass} placeholder="alerts@example.com" aria-invalid={Boolean(fieldErrors.from_address)} />{fieldError('from_address')}</label>
                    <label><span className={fieldLabelClass}>{zh ? '发件人名称' : 'From name'}</span><input value={settings.from_name} disabled={locked} onChange={(event) => updateField('from_name', event.target.value)} className={inputClass} placeholder="Nexora" /></label>
                    <label><span className={fieldLabelClass}>{zh ? '回复地址（可选）' : 'Reply-to (optional)'}</span><input type="email" value={settings.reply_to} disabled={locked} onChange={(event) => updateField('reply_to', event.target.value)} className={inputClass} aria-invalid={Boolean(fieldErrors.reply_to)} />{fieldError('reply_to')}</label>
                    <label className="sm:col-span-2"><span className={fieldLabelClass}>{zh ? '测试收件人（可选）' : 'Test recipient (optional)'}</span><input type="email" value={recipient} disabled={locked} onChange={(event) => { setRecipient(event.target.value); setFieldErrors((current) => { const next = { ...current }; delete next.recipient; return next; }); }} placeholder={zh ? '留空使用当前用户邮箱' : 'Blank uses the current user email'} className={inputClass} aria-invalid={Boolean(fieldErrors.recipient)} />{fieldError('recipient')}</label>
                  </div>
                </section>
              </div>

              <div className="mx-5 mb-5 rounded-xl border border-slate-200 sm:mx-6">
                <button type="button" onClick={() => setAdvancedOpen((current) => !current)} aria-expanded={advancedOpen} className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-semibold text-slate-600 hover:bg-slate-50">
                  <ChevronDown size={15} className={`transition-transform ${advancedOpen ? 'rotate-180' : ''}`} />{zh ? '高级参数' : 'Advanced settings'}<span className="font-normal text-slate-400">{zh ? '超时与发送速率' : 'Timeouts and rate limit'}</span>
                </button>
                {advancedOpen && <div className="grid gap-4 border-t border-slate-200 bg-slate-50/60 p-4 sm:grid-cols-3">
                  <label><span className={fieldLabelClass}>{zh ? '连接超时（秒）' : 'Connect timeout (sec)'}</span><input type="number" min={1} max={120} value={settings.connect_timeout_seconds} disabled={locked} onChange={(event) => updateField('connect_timeout_seconds', Number(event.target.value))} className={inputClass} />{fieldError('connect_timeout_seconds')}</label>
                  <label><span className={fieldLabelClass}>{zh ? '发送超时（秒）' : 'Send timeout (sec)'}</span><input type="number" min={1} max={120} value={settings.send_timeout_seconds} disabled={locked} onChange={(event) => updateField('send_timeout_seconds', Number(event.target.value))} className={inputClass} />{fieldError('send_timeout_seconds')}</label>
                  <label><span className={fieldLabelClass}>{zh ? '每分钟发送上限' : 'Rate limit per minute'}</span><input type="number" min={1} max={10000} value={settings.rate_limit_per_minute} disabled={locked} onChange={(event) => updateField('rate_limit_per_minute', Number(event.target.value))} className={inputClass} />{fieldError('rate_limit_per_minute')}</label>
                </div>}
              </div>

              <div className="flex flex-wrap items-center gap-3 border-t border-slate-100 px-5 py-4 sm:px-6">
                <button type="button" onClick={() => void saveSettings()} disabled={saving || testing || permissionDenied} className="inline-flex items-center gap-2 rounded-xl bg-cyan-700 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-cyan-800 disabled:cursor-not-allowed disabled:opacity-50">{saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}{saving ? (zh ? '保存中…' : 'Saving…') : (zh ? '保存配置' : 'Save settings')}</button>
                <button type="button" onClick={() => void testSettings()} disabled={saving || testing || permissionDenied || dirty} title={dirty ? (zh ? '请先保存改动' : 'Save changes first') : undefined} className="inline-flex items-center gap-2 rounded-xl border border-cyan-200 bg-cyan-50 px-4 py-2.5 text-sm font-semibold text-cyan-800 hover:bg-cyan-100 disabled:cursor-not-allowed disabled:opacity-50">{testing ? <Loader2 size={15} className="animate-spin" /> : <CheckCircle2 size={15} />}{testing ? (zh ? '发送中…' : 'Sending…') : (zh ? '发送测试邮件' : 'Send test email')}</button>
                {dirty && <span className="text-xs text-amber-700">{zh ? '配置有未保存改动，保存后才能发送测试。' : 'Save unsaved changes before sending a test.'}</span>}
                {!dirty && <span className="text-xs text-slate-500">{zh ? '测试成功表示邮件服务接受了发送请求；最终送达请检查目标邮箱。' : 'Success means the mail service accepted the request. Check the target mailbox for delivery.'}</span>}
              </div>
            </section>

            {feedback && <div role="status" className={`flex items-start gap-3 rounded-xl border px-4 py-3 text-sm leading-6 ${feedback.tone === 'success' ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-rose-200 bg-rose-50 text-rose-700'}`}>
              {feedback.tone === 'success' ? <CheckCircle2 size={17} className="mt-0.5 shrink-0" /> : <AlertCircle size={17} className="mt-0.5 shrink-0" />}{feedback.message}
            </div>}
          </>
        )}
      </div>
    </div>
  );
};

export default NotificationChannelSettingsPage;
