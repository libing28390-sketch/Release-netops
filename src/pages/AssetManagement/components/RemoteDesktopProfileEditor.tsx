import React, { useEffect, useState } from 'react';
import { AlertCircle, Loader2, Monitor, Save, ShieldCheck } from 'lucide-react';
import { ApiError } from '../../../api/http';
import { listRemoteDesktopProfiles, saveRemoteDesktopProfile } from '../../../api/pamRemoteDesktop';
import type { RemoteDesktopProfileInput } from '../../../api/pamRemoteDesktop';
import type { RemoteDesktopProfile, RemoteDesktopProtocol, RemoteDesktopSecurityMode } from '../types';

interface CredentialOption {
  id: string;
  name?: string;
  credential_name?: string;
  account_role?: string;
}

interface RemoteDesktopProfileEditorProps {
  assetId: string;
  credentials: CredentialOption[];
  language: string;
}

interface ProfileDraft {
  profile_name: string;
  port: string;
  enabled: boolean;
  normal_credential_id: string;
  admin_credential_id: string;
  rdp_domain: string;
  rdp_security_mode: RemoteDesktopSecurityMode;
  rdp_cert_fingerprint: string;
}

type ProfileDraftMap = Record<RemoteDesktopProtocol, ProfileDraft>;

const defaultDraft = (protocol: RemoteDesktopProtocol): ProfileDraft => ({
  profile_name: protocol.toUpperCase(),
  port: protocol === 'rdp' ? '3389' : '5900',
  enabled: false,
  normal_credential_id: '',
  admin_credential_id: '',
  rdp_domain: '',
  rdp_security_mode: 'nla',
  rdp_cert_fingerprint: '',
});

function toDraft(profile: RemoteDesktopProfile): ProfileDraft {
  return {
    ...defaultDraft(profile.protocol),
    profile_name: profile.profile_name || profile.protocol.toUpperCase(),
    port: String(profile.port || (profile.protocol === 'rdp' ? 3389 : 5900)),
    enabled: profile.enabled !== false,
    normal_credential_id: profile.normal_credential_id || '',
    admin_credential_id: profile.admin_credential_id || '',
    rdp_domain: profile.rdp_domain || '',
    rdp_security_mode: profile.rdp_security_mode || 'nla',
    rdp_cert_fingerprint: profile.rdp_cert_fingerprint || '',
  };
}

function toInput(protocol: RemoteDesktopProtocol, draft: ProfileDraft): RemoteDesktopProfileInput {
  const common = {
    profile_name: draft.profile_name.trim() || protocol.toUpperCase(),
    port: Number(draft.port),
    enabled: draft.enabled,
    normal_credential_id: draft.normal_credential_id || null,
    admin_credential_id: draft.admin_credential_id || null,
  };
  return protocol === 'rdp'
    ? {
      ...common,
      rdp_domain: draft.rdp_domain.trim(),
      rdp_security_mode: draft.rdp_security_mode,
      rdp_cert_fingerprint: draft.rdp_cert_fingerprint.trim().toUpperCase(),
    }
    : common;
}

function getErrorStatus(error: unknown): number | null {
  return error instanceof ApiError ? error.status : null;
}

function getErrorMessage(error: unknown, isZh: boolean): string {
  if (error instanceof ApiError && error.status === 403) return isZh ? '你没有权限读取或修改远程桌面配置。' : 'You do not have permission to view or edit remote desktop profiles.';
  if (error instanceof ApiError && error.status === 401) return isZh ? '登录状态已失效，请重新登录后重试。' : 'Your session has expired. Sign in again and retry.';
  return error instanceof Error ? error.message : (isZh ? '远程桌面配置加载失败。' : 'Remote desktop profiles could not be loaded.');
}

export default function RemoteDesktopProfileEditor({ assetId, credentials, language }: RemoteDesktopProfileEditorProps) {
  const isZh = language === 'zh';
  const [drafts, setDrafts] = useState<ProfileDraftMap>({ rdp: defaultDraft('rdp'), vnc: defaultDraft('vnc') });
  const [savedProfiles, setSavedProfiles] = useState<Partial<Record<RemoteDesktopProtocol, RemoteDesktopProfile>>>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [retryCount, setRetryCount] = useState(0);
  const [savingProtocol, setSavingProtocol] = useState<RemoteDesktopProtocol | null>(null);
  const [saveErrors, setSaveErrors] = useState<Partial<Record<RemoteDesktopProtocol, string>>>({});
  const [saveSuccess, setSaveSuccess] = useState<Partial<Record<RemoteDesktopProtocol, boolean>>>({});

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setLoadError(null);
    listRemoteDesktopProfiles(assetId, controller.signal)
      .then((profiles) => {
        if (!active) return;
        const nextSaved: Partial<Record<RemoteDesktopProtocol, RemoteDesktopProfile>> = {};
        const nextDrafts: ProfileDraftMap = { rdp: defaultDraft('rdp'), vnc: defaultDraft('vnc') };
        profiles.forEach((profile) => {
          if (profile.protocol !== 'rdp' && profile.protocol !== 'vnc') return;
          nextSaved[profile.protocol] = profile;
          nextDrafts[profile.protocol] = toDraft(profile);
        });
        setSavedProfiles(nextSaved);
        setDrafts(nextDrafts);
      })
      .catch((error: unknown) => {
        if (active && !(error instanceof DOMException && error.name === 'AbortError')) setLoadError(error);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [assetId, retryCount]);

  const updateDraft = (protocol: RemoteDesktopProtocol, patch: Partial<ProfileDraft>) => {
    setDrafts(current => ({ ...current, [protocol]: { ...current[protocol], ...patch } }));
    setSaveErrors(current => ({ ...current, [protocol]: undefined }));
    setSaveSuccess(current => ({ ...current, [protocol]: false }));
  };

  const saveProfile = async (protocol: RemoteDesktopProtocol) => {
    const draft = drafts[protocol];
    const port = Number(draft.port);
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
      setSaveErrors(current => ({ ...current, [protocol]: isZh ? '端口必须是 1 到 65535 之间的整数。' : 'Port must be an integer from 1 to 65535.' }));
      return;
    }
    const certFingerprint = draft.rdp_cert_fingerprint.trim();
    if (protocol === 'rdp' && certFingerprint && !/^[0-9A-Fa-f]{64}$/.test(certFingerprint)) {
      setSaveErrors(current => ({
        ...current,
        [protocol]: isZh ? 'RDP 证书指纹必须是 64 位十六进制 SHA-256 值。' : 'RDP certificate fingerprint must be a 64-character hexadecimal SHA-256 value.',
      }));
      return;
    }

    setSavingProtocol(protocol);
    setSaveErrors(current => ({ ...current, [protocol]: undefined }));
    setSaveSuccess(current => ({ ...current, [protocol]: false }));
    try {
      const saved = await saveRemoteDesktopProfile(assetId, protocol, toInput(protocol, draft));
      setSavedProfiles(current => ({ ...current, [protocol]: saved }));
      setDrafts(current => ({ ...current, [protocol]: toDraft(saved) }));
      setSaveSuccess(current => ({ ...current, [protocol]: true }));
    } catch (error) {
      setSaveErrors(current => ({ ...current, [protocol]: getErrorMessage(error, isZh) }));
    } finally {
      setSavingProtocol(null);
    }
  };

  const credentialLabel = (credential: CredentialOption) => credential.name || credential.credential_name || credential.id;
  const permissionDenied = getErrorStatus(loadError) === 401 || getErrorStatus(loadError) === 403;
  const readOnly = permissionDenied;

  const renderCredentialSelect = (protocol: RemoteDesktopProtocol, level: 'normal' | 'admin') => {
    const field = level === 'normal' ? 'normal_credential_id' : 'admin_credential_id';
    const label = level === 'normal' ? (isZh ? '普通凭据' : 'Normal credential') : (isZh ? '管理员凭据' : 'Administrator credential');
    return (
      <label className="block min-w-0">
        <span className="mb-1 block text-[10px] font-medium text-slate-500">{label}</span>
        <select
          value={drafts[protocol][field]}
          onChange={event => updateDraft(protocol, { [field]: event.target.value })}
          disabled={loading || readOnly || savingProtocol === protocol}
          className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs text-slate-700 outline-none focus:border-cyan-400 disabled:bg-slate-50"
        >
          <option value="">{isZh ? '继承资产对应凭据' : 'Inherit asset credential'}</option>
          {credentials.map(credential => <option key={credential.id} value={credential.id}>{credentialLabel(credential)}</option>)}
        </select>
      </label>
    );
  };

  const renderProtocolCard = (protocol: RemoteDesktopProtocol) => {
    const draft = drafts[protocol];
    const saved = savedProfiles[protocol];
    const saving = savingProtocol === protocol;
    return (
      <section key={protocol} className="rounded-xl border border-slate-200 bg-white p-3.5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${protocol === 'rdp' ? 'bg-violet-50 text-violet-600' : 'bg-blue-50 text-blue-600'}`}>
              <Monitor size={15} />
            </span>
            <div>
              <h4 className="text-xs font-bold text-slate-800">{protocol.toUpperCase()}</h4>
              <p className="text-[10px] text-slate-400">{saved ? (isZh ? '已保存配置' : 'Profile saved') : (isZh ? '尚未保存配置' : 'No saved profile')}</p>
            </div>
          </div>
          <label className="inline-flex items-center gap-2 text-[10px] font-semibold text-slate-600">
            <input
              type="checkbox"
              checked={draft.enabled}
              onChange={event => updateDraft(protocol, { enabled: event.target.checked })}
              disabled={loading || readOnly || saving}
              className="rounded border-slate-300 text-cyan-600 focus:ring-cyan-500"
            />
            {isZh ? '启用访问中心入口' : 'Enable in Access Center'}
          </label>
        </div>

        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="block min-w-0">
            <span className="mb-1 block text-[10px] font-medium text-slate-500">{isZh ? '配置名称' : 'Profile name'}</span>
            <input
              value={draft.profile_name}
              onChange={event => updateDraft(protocol, { profile_name: event.target.value })}
              disabled={loading || readOnly || saving}
              maxLength={120}
              className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs text-slate-700 outline-none focus:border-cyan-400 disabled:bg-slate-50"
            />
          </label>
          <label className="block min-w-0">
            <span className="mb-1 block text-[10px] font-medium text-slate-500">{isZh ? '目标端口' : 'Target port'}</span>
            <input
              type="number"
              min={1}
              max={65535}
              step={1}
              value={draft.port}
              onChange={event => updateDraft(protocol, { port: event.target.value })}
              disabled={loading || readOnly || saving}
              className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs text-slate-700 outline-none focus:border-cyan-400 disabled:bg-slate-50"
            />
          </label>
          {renderCredentialSelect(protocol, 'normal')}
          {renderCredentialSelect(protocol, 'admin')}
          {protocol === 'rdp' && (
            <>
              <label className="block min-w-0">
                <span className="mb-1 block text-[10px] font-medium text-slate-500">{isZh ? 'Windows 域（可选）' : 'Windows domain (optional)'}</span>
                <input
                  value={draft.rdp_domain}
                  onChange={event => updateDraft(protocol, { rdp_domain: event.target.value })}
                  disabled={loading || readOnly || saving}
                  maxLength={120}
                  className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs text-slate-700 outline-none focus:border-cyan-400 disabled:bg-slate-50"
                />
              </label>
              <label className="block min-w-0">
                <span className="mb-1 block text-[10px] font-medium text-slate-500">{isZh ? '安全协商' : 'Security negotiation'}</span>
                <select
                  value={draft.rdp_security_mode}
                  onChange={event => updateDraft(protocol, { rdp_security_mode: event.target.value as RemoteDesktopSecurityMode })}
                  disabled={loading || readOnly || saving}
                  className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs text-slate-700 outline-none focus:border-cyan-400 disabled:bg-slate-50"
                >
                  <option value="nla">NLA</option>
                  <option value="tls">TLS</option>
                  <option value="rdp">RDP</option>
                  <option value="any">{isZh ? '自动协商' : 'Any'}</option>
                </select>
              </label>
              <label className="block min-w-0 sm:col-span-2">
                <span className="mb-1 block text-[10px] font-medium text-slate-500">{isZh ? 'RDP 证书 SHA-256 指纹（可选）' : 'RDP certificate SHA-256 fingerprint (optional)'}</span>
                <input
                  value={draft.rdp_cert_fingerprint}
                  onChange={event => updateDraft(protocol, { rdp_cert_fingerprint: event.target.value })}
                  disabled={loading || readOnly || saving}
                  maxLength={64}
                  autoComplete="off"
                  spellCheck={false}
                  className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 font-mono text-xs text-slate-700 outline-none focus:border-cyan-400 disabled:bg-slate-50"
                />
                <span className="mt-1 block text-[10px] leading-4 text-slate-400">
                  {isZh ? '填写 64 位十六进制 SHA-256。设置后仅接受匹配证书；留空时仍执行系统证书校验，不会忽略证书错误。' : 'Enter 64 hexadecimal SHA-256 characters. When set, only a matching certificate is accepted; blank keeps system certificate validation enabled.'}
                </span>
              </label>
            </>
          )}
        </div>

        {protocol === 'vnc' && <p className="mt-2 text-[10px] leading-4 text-slate-400">{isZh ? 'VNC 凭据可以只包含密码；不要求用户名。' : 'VNC credentials may contain only a password; a username is not required.'}</p>}
        {saveErrors[protocol] && <p role="alert" className="mt-2 flex items-start gap-1.5 text-[10px] text-rose-600"><AlertCircle size={13} className="mt-0.5 shrink-0" />{saveErrors[protocol]}</p>}
        {saveSuccess[protocol] && <p role="status" className="mt-2 flex items-center gap-1.5 text-[10px] text-emerald-700"><ShieldCheck size={13} />{isZh ? '远程桌面配置已保存。' : 'Remote desktop profile saved.'}</p>}
        <div className="mt-3 flex justify-end">
          <button
            type="button"
            onClick={() => void saveProfile(protocol)}
            disabled={loading || readOnly || savingProtocol !== null}
            className="inline-flex items-center gap-1.5 rounded-lg bg-cyan-600 px-3 py-2 text-[10px] font-bold text-white transition hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
            {saving ? (isZh ? '保存中…' : 'Saving…') : (isZh ? '保存配置' : 'Save profile')}
          </button>
        </div>
      </section>
    );
  };

  return (
    <div className="col-span-2 rounded-xl border border-violet-100 bg-violet-50/35 p-3.5">
      <div className="mb-3 flex items-start gap-2">
        <Monitor size={15} className="mt-0.5 shrink-0 text-violet-600" />
        <div>
          <h3 className="text-[11px] font-bold text-slate-800">{isZh ? 'RDP / VNC 远程桌面' : 'RDP / VNC remote desktop'}</h3>
          <p className="mt-0.5 text-[10px] leading-4 text-slate-500">
            {isZh ? '连接参数和凭据引用单独保存；密码不会显示在表单中。新资产请先保存资产，再打开编辑配置。' : 'Connection settings and credential references are saved separately; passwords are never displayed. Save a new asset first, then reopen it to configure remote desktop.'}
          </p>
        </div>
      </div>

      {loading && <div className="flex items-center gap-2 rounded-lg bg-white px-3 py-3 text-xs text-slate-500"><Loader2 size={14} className="animate-spin text-cyan-600" />{isZh ? '正在加载远程桌面配置…' : 'Loading remote desktop profiles…'}</div>}
      {!loading && loadError && (
        <div role="alert" className={`rounded-lg border px-3 py-3 text-xs ${permissionDenied ? 'border-amber-200 bg-amber-50 text-amber-800' : 'border-rose-200 bg-rose-50 text-rose-700'}`}>
          <div className="flex items-start gap-2"><AlertCircle size={15} className="mt-0.5 shrink-0" /><p>{getErrorMessage(loadError, isZh)}</p></div>
          {!permissionDenied && <button type="button" onClick={() => setRetryCount(count => count + 1)} className="ml-6 mt-2 font-bold underline underline-offset-2">{isZh ? '重试' : 'Retry'}</button>}
        </div>
      )}
      {!loading && !loadError && <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">{renderProtocolCard('rdp')}{renderProtocolCard('vnc')}</div>}
    </div>
  );
}
