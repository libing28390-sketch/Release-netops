import React, { useState } from 'react';
import { AlertCircle, KeyRound, Loader2, Monitor, ShieldCheck, Smartphone, X } from 'lucide-react';
import { ApiError } from '../../api/http';
import { createPamRemoteDesktopSession, type PamRemoteDesktopSession } from '../../api/pamRemoteDesktop';
import type { RemoteDesktopAccessLevel } from '../../api/pamRemoteDesktop';
import type { RemoteDesktopProfile, RemoteDesktopProtocol } from '../../pages/AssetManagement/types';
import RemoteDesktopClient from './RemoteDesktopClient';

interface RemoteDesktopAccessModalProps {
  assetId: string;
  hostname: string;
  ipAddress: string;
  protocol: RemoteDesktopProtocol;
  profile: RemoteDesktopProfile;
  language: string;
  initialAccessLevel?: RemoteDesktopAccessLevel;
  onClose: () => void;
}

function requestErrorMessage(error: unknown, isZh: boolean): string {
  if (error instanceof ApiError && error.status === 401) return isZh ? '登录状态已失效，请重新登录后再申请会话。' : 'Your login session has expired. Sign in again to request a session.';
  if (error instanceof ApiError && error.status === 403) return isZh ? '当前用户无权访问此资产或没有管理员授权权限。' : 'You are not authorized to access this asset or request administrator access.';
  return error instanceof Error ? error.message : (isZh ? '远程桌面会话申请失败。' : 'Remote desktop session request failed.');
}

export default function RemoteDesktopAccessModal({
  assetId,
  hostname,
  ipAddress,
  protocol,
  profile,
  language,
  initialAccessLevel = 'normal',
  onClose,
}: RemoteDesktopAccessModalProps) {
  const isZh = language === 'zh';
  const [accessLevel, setAccessLevel] = useState<RemoteDesktopAccessLevel>(initialAccessLevel);
  const [reason, setReason] = useState('');
  const [fixedPin, setFixedPin] = useState('');
  const [mfaCode, setMfaCode] = useState('');
  const [requesting, setRequesting] = useState(false);
  const [requestError, setRequestError] = useState('');
  const [session, setSession] = useState<PamRemoteDesktopSession | null>(null);

  const canSubmit = !requesting
    && reason.trim().length > 0
    && (accessLevel === 'normal' || (fixedPin.length === 6 && mfaCode.length === 6));

  const startSession = async () => {
    if (!canSubmit) return;
    setRequesting(true);
    setRequestError('');
    try {
      const result = await createPamRemoteDesktopSession({
        assetId,
        protocol,
        accessLevel,
        reason,
        ...(accessLevel === 'admin' ? { fixedPin, mfaCode } : {}),
      });
      setSession(result);
      setFixedPin('');
      setMfaCode('');
    } catch (error) {
      setRequestError(requestErrorMessage(error, isZh));
    } finally {
      setRequesting(false);
    }
  };

  if (session) {
    return <RemoteDesktopClient session={session} protocol={protocol} hostname={hostname} language={language} onClose={onClose} />;
  }

  return (
    <div className="fixed inset-0 z-[160] flex items-center justify-center bg-slate-950/70 p-3 backdrop-blur-sm sm:p-5">
      <div role="dialog" aria-modal="true" aria-labelledby="remote-desktop-request-title" className="w-full max-w-xl overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 bg-gradient-to-r from-violet-50 via-white to-cyan-50 px-5 py-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-violet-100 text-violet-700"><Monitor size={19} /></span>
            <div className="min-w-0">
              <h2 id="remote-desktop-request-title" className="text-sm font-black text-slate-800">{isZh ? '申请远程桌面会话' : 'Request remote desktop session'}</h2>
              <p className="mt-1 truncate text-xs text-slate-500">{hostname} · {ipAddress}:{profile.port} · {protocol.toUpperCase()}</p>
            </div>
          </div>
          <button type="button" onClick={onClose} disabled={requesting} aria-label={isZh ? '关闭' : 'Close'} className="rounded-lg p-2 text-slate-400 transition hover:bg-white hover:text-slate-700 disabled:opacity-50"><X size={17} /></button>
        </div>

        <div className="space-y-4 px-5 py-5 sm:px-6">
          <fieldset>
            <legend className="mb-2 text-[10px] font-black uppercase tracking-wider text-slate-500">{isZh ? '访问级别' : 'Access level'}</legend>
            <div className="grid grid-cols-2 gap-2">
              {(['normal', 'admin'] as const).map(level => (
                <button
                  key={level}
                  type="button"
                  onClick={() => {
                    setAccessLevel(level);
                    setFixedPin('');
                    setMfaCode('');
                    setRequestError('');
                  }}
                  disabled={requesting}
                  aria-pressed={accessLevel === level}
                  className={`rounded-xl border px-3 py-3 text-left transition ${accessLevel === level ? (level === 'admin' ? 'border-rose-300 bg-rose-50 text-rose-700 ring-2 ring-rose-100' : 'border-cyan-300 bg-cyan-50 text-cyan-800 ring-2 ring-cyan-100') : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300'}`}
                >
                  <span className="flex items-center gap-2 text-xs font-bold">{level === 'admin' ? <ShieldCheck size={15} /> : <Monitor size={15} />}{level === 'admin' ? (isZh ? '管理员' : 'Administrator') : (isZh ? '普通' : 'Normal')}</span>
                  <span className="mt-1 block text-[10px] opacity-70">{level === 'admin' ? (isZh ? '需固定 PIN 与 MFA 验证' : 'Fixed PIN and MFA required') : (isZh ? '使用普通凭据' : 'Uses normal credentials')}</span>
                </button>
              ))}
            </div>
          </fieldset>

          <label className="block">
            <span className="mb-1.5 block text-[10px] font-black uppercase tracking-wider text-slate-500">{isZh ? '访问用途' : 'Purpose'} <span className="text-rose-500">*</span></span>
            <textarea
              value={reason}
              onChange={event => setReason(event.target.value)}
              maxLength={500}
              rows={3}
              disabled={requesting}
              placeholder={isZh ? '说明本次远程桌面访问的工作目的' : 'Describe why you need this remote desktop session'}
              className="w-full resize-y rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-xs text-slate-700 outline-none transition placeholder:text-slate-300 focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100 disabled:bg-slate-50"
            />
          </label>

          {accessLevel === 'admin' && (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="block">
                <span className="mb-1.5 flex items-center gap-1.5 text-[10px] font-black uppercase tracking-wider text-slate-500"><KeyRound size={13} className="text-rose-500" />{isZh ? '固定 PIN（6 位）' : 'Fixed PIN (6 digits)'}</span>
                <input
                  type="password"
                  value={fixedPin}
                  onChange={event => setFixedPin(event.target.value.replace(/\D/g, '').slice(0, 6))}
                  disabled={requesting}
                  inputMode="numeric"
                  autoComplete="off"
                  placeholder="••••••"
                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-center text-sm font-bold tracking-[0.4em] text-slate-700 outline-none focus:border-rose-300 focus:ring-2 focus:ring-rose-100 disabled:bg-slate-50"
                />
              </label>
              <label className="block">
                <span className="mb-1.5 flex items-center gap-1.5 text-[10px] font-black uppercase tracking-wider text-slate-500"><Smartphone size={13} className="text-cyan-600" />{isZh ? 'MFA 验证器动态码' : 'Authenticator code'}</span>
                <input
                  type="text"
                  value={mfaCode}
                  onChange={event => setMfaCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
                  disabled={requesting}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  placeholder="000000"
                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-center text-sm font-bold tracking-[0.4em] text-slate-700 outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100 disabled:bg-slate-50"
                />
              </label>
              <p className="sm:col-span-2 -mt-1 text-[10px] leading-4 text-slate-400">{isZh ? '固定 PIN 和 MFA 只提交给 Nexora 进行本次管理员授权，不发送到远程桌面目标。' : 'The PIN and MFA code are submitted to Nexora for this authorization and are not sent to the remote desktop target.'}</p>
            </div>
          )}

          {requestError && <p role="alert" className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2.5 text-xs text-rose-700"><AlertCircle size={15} className="mt-0.5 shrink-0" />{requestError}</p>}
          <div className="rounded-xl border border-slate-100 bg-slate-50 px-3 py-2.5 text-[10px] leading-4 text-slate-500">
            {isZh ? '会话会通过 Nexora 安全网关连接并记录图形录像。浏览器不会接收目标密码或 Guacamole 授权令牌。' : 'The session is brokered by Nexora and recorded. The browser does not receive the target password or a Guacamole authorization token.'}
          </div>
        </div>

        <div className="flex flex-col-reverse gap-2 border-t border-slate-100 bg-slate-50/70 px-5 py-4 sm:flex-row sm:justify-end sm:px-6">
          <button type="button" onClick={onClose} disabled={requesting} className="rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-xs font-bold text-slate-500 transition hover:border-slate-300 hover:text-slate-700 disabled:opacity-50">{isZh ? '取消' : 'Cancel'}</button>
          <button type="button" onClick={() => void startSession()} disabled={!canSubmit} className="inline-flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-cyan-600 px-5 py-2.5 text-xs font-black text-white shadow-lg shadow-cyan-600/15 transition hover:from-violet-500 hover:to-cyan-500 disabled:cursor-not-allowed disabled:opacity-45">
            {requesting ? <Loader2 size={14} className="animate-spin" /> : <ShieldCheck size={14} />}
            {requesting ? (isZh ? '正在申请…' : 'Requesting…') : (isZh ? '申请并连接' : 'Request & connect')}
          </button>
        </div>
      </div>
    </div>
  );
}
