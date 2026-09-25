import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CheckCircle2,
  Cloud,
  KeyRound,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  Server,
  ShieldCheck,
  TestTube2,
  Trash2,
  X,
  XCircle,
} from 'lucide-react';
import PageHero from '../components/PageHero';
import {
  createStorageProvider,
  deleteStorageProvider,
  listStorageProviders,
  testSavedStorageProvider,
  testStorageProvider,
  updateStorageProvider,
  listStorageUsages,
  testStorageUsage,
  updateStorageUsage,
  type StorageProvider,
  type StorageProviderInput,
  type StorageUsage,
  type StorageUsagePurpose,
  type StorageUsageProviderMode,
  type StorageUsageProfileOption,
} from '../api/storage';
import { ApiError } from '../api/http';
import { primaryActionBtnClass, secondaryActionBtnClass } from '../components/shared';
import { useEscapeClose } from '../hooks/useEscapeClose';

interface StorageManagementPageProps {
  language: string;
  currentUser?: { role?: string; role_profile?: string } | null;
}

type FormMode = 'create' | 'edit';
type TestState = { kind: 'success' | 'error'; message: string } | null;
type UsageDraft = {
  provider_mode: StorageUsageProviderMode;
  provider_id: string;
  bucket_override: string;
  key_prefix: string;
};

const USAGE_CATALOG: Array<{ purpose: StorageUsagePurpose; defaultPrefix: string; zh: string; en: string }> = [
  { purpose: 'config_backup', defaultPrefix: 'config', zh: '配置备份', en: 'Config backups' },
  { purpose: 'pam_recording', defaultPrefix: 'pam', zh: 'PAM 录像', en: 'PAM recordings' },
];

const EMPTY_USAGE_DRAFTS: Record<StorageUsagePurpose, UsageDraft> = {
  config_backup: { provider_mode: 'default', provider_id: '', bucket_override: '', key_prefix: 'config' },
  pam_recording: { provider_mode: 'default', provider_id: '', bucket_override: '', key_prefix: 'pam' },
};

const EMPTY_FORM: StorageProviderInput = {
  name: '',
  backend: 's3',
  endpoint_url: '',
  bucket: '',
  region: 'us-east-1',
  access_key_id: '',
  secret_access_key: '',
  force_path_style: true,
  verify_tls: true,
  is_default: false,
  notes: '',
};

const inputClass = 'w-full rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 py-2 text-sm text-[var(--ui-fg)] outline-none transition focus:border-[var(--ui-accent)] focus:ring-2 focus:ring-[var(--ui-accent)]/15';
const labelClass = 'mb-1.5 block text-xs font-semibold text-[var(--muted-text)]';

const errorMessage = (error: unknown, zh: boolean): string => {
  if (error instanceof ApiError) {
    if (error.status === 401) return zh ? '登录已失效，请重新登录。' : 'Your session has expired. Please sign in again.';
    if (error.status === 403) return zh ? '你没有管理对象存储的权限。' : 'You do not have permission to manage object storage.';
    if (error.status >= 500) return zh ? '服务暂时不可用，请稍后重试。' : 'The service is temporarily unavailable. Please try again.';
    return error.message.replace(/\s*\(Request ID:.*\)$/i, '') || (zh ? '请求失败，请重试。' : 'Request failed. Please try again.');
  }
  return error instanceof Error ? error.message : (zh ? '请求失败，请重试。' : 'Request failed. Please try again.');
};

const formatDate = (value: string | null | undefined, zh: boolean) => {
  if (!value) return zh ? '暂无' : '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(zh ? 'zh-CN' : 'en-US');
};

const StorageManagementPage: React.FC<StorageManagementPageProps> = ({ language, currentUser }) => {
  const zh = language === 'zh';
  const isAdmin = currentUser?.role === 'Administrator' || currentUser?.role_profile === 'System Administrator';
  const [items, setItems] = useState<StorageProvider[]>([]);
  const [effectiveDefaultId, setEffectiveDefaultId] = useState<string | null>(null);
  const [defaultSource, setDefaultSource] = useState<'database' | 'environment' | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [permissionDenied, setPermissionDenied] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [mode, setMode] = useState<FormMode>('create');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<StorageProviderInput>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [formTest, setFormTest] = useState<TestState>(null);
  const [savedTests, setSavedTests] = useState<Record<string, TestState>>({});
  const [formError, setFormError] = useState('');
  const [usageItems, setUsageItems] = useState<StorageUsage[]>([]);
  const [usageDrafts, setUsageDrafts] = useState<Record<StorageUsagePurpose, UsageDraft>>(EMPTY_USAGE_DRAFTS);
  const [usageProfiles, setUsageProfiles] = useState<StorageUsageProfileOption[]>([]);
  const [usageLoading, setUsageLoading] = useState(true);
  const [usageError, setUsageError] = useState('');
  const [usageSavingPurpose, setUsageSavingPurpose] = useState<StorageUsagePurpose | null>(null);
  const [usageSaveError, setUsageSaveError] = useState<Record<string, string>>({});
  const [usageTestingPurpose, setUsageTestingPurpose] = useState<StorageUsagePurpose | null>(null);
  const [usageTestState, setUsageTestState] = useState<Record<string, TestState>>({});

  const clearFormCredentials = () => {
    setForm((current) => ({ ...current, access_key_id: '', secret_access_key: '' }));
  };
  const closeModal = () => {
    clearFormCredentials();
    setModalOpen(false);
  };

  useEscapeClose(modalOpen, () => { if (!saving) closeModal(); });

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      const response = await listStorageProviders();
      setItems(Array.isArray(response.items) ? response.items : []);
      setEffectiveDefaultId(response.effective_default_id ?? null);
      setDefaultSource(response.default_source ?? null);
      setPermissionDenied(false);
    } catch (error) {
      setLoadError(errorMessage(error, zh));
      setPermissionDenied(error instanceof ApiError && error.status === 403);
    } finally {
      setLoading(false);
    }
  }, [zh]);

  useEffect(() => { void load(); }, [load]);

  const loadUsages = useCallback(async () => {
    setUsageLoading(true);
    setUsageError('');
    try {
      const response = await listStorageUsages();
      const nextItems = Array.isArray(response.items) ? response.items : [];
      setUsageItems(nextItems);
      const nextDrafts = { ...EMPTY_USAGE_DRAFTS };
      nextItems.forEach((item) => {
        if (!USAGE_CATALOG.some((entry) => entry.purpose === item.purpose)) return;
        nextDrafts[item.purpose] = {
          provider_mode: item.provider_mode || 'default',
          provider_id: item.provider_id || '',
          bucket_override: item.bucket_override || '',
          key_prefix: item.key_prefix || USAGE_CATALOG.find((entry) => entry.purpose === item.purpose)?.defaultPrefix || '',
        };
      });
      setUsageDrafts(nextDrafts);
      const responseProfiles = Array.isArray(response.profiles) ? response.profiles : [];
      const itemProfiles = nextItems.flatMap((item) => Array.isArray(item.profiles) ? item.profiles : []);
      setUsageProfiles(responseProfiles.length > 0 ? responseProfiles : itemProfiles);
      setPermissionDenied(false);
    } catch (error) {
      setUsageError(errorMessage(error, zh));
      if (error instanceof ApiError && error.status === 403) setPermissionDenied(true);
    } finally {
      setUsageLoading(false);
    }
  }, [zh]);

  useEffect(() => { void loadUsages(); }, [loadUsages]);

  const usageProfileOptions = useMemo<StorageUsageProfileOption[]>(() => {
    const source = usageProfiles.length > 0 ? usageProfiles : items;
    const environment: StorageUsageProfileOption = { id: 'environment', name: zh ? '环境变量' : 'Environment variables', source: 'environment' };
    const options = source.some((profile) => profile.id === 'environment') ? source : [environment, ...source];
    return options.filter((profile, index, all) => all.findIndex((candidate) => candidate.id === profile.id) === index);
  }, [items, usageProfiles, zh]);

  const updateUsageDraft = (purpose: StorageUsagePurpose, patch: Partial<UsageDraft>) => {
    setUsageDrafts((current) => ({ ...current, [purpose]: { ...current[purpose], ...patch } }));
    setUsageSaveError((current) => ({ ...current, [purpose]: '' }));
    setUsageTestState((current) => ({ ...current, [purpose]: null }));
  };

  const usageValidationMessage = (purpose: StorageUsagePurpose) => {
    const draft = usageDrafts[purpose];
    if (!draft.key_prefix.trim()) {
      return zh ? '请填写对象 key 前缀。' : 'Enter an object key prefix.';
    }
    if (draft.provider_mode === 'profile' && !draft.provider_id) {
      return zh ? '请选择一个存储 profile。' : 'Select a storage profile.';
    }
    return '';
  };

  const usageRequestInput = (purpose: StorageUsagePurpose) => {
    const draft = usageDrafts[purpose];
    return {
      provider_mode: draft.provider_mode,
      provider_id: draft.provider_mode === 'profile' ? (draft.provider_id || null) : null,
      bucket_override: draft.bucket_override.trim(),
      key_prefix: draft.key_prefix.trim().replace(/^\/+|\/+$/g, ''),
    };
  };

  const handleUsageTest = async (purpose: StorageUsagePurpose) => {
    const validation = usageValidationMessage(purpose);
    if (validation) {
      setUsageTestState((current) => ({ ...current, [purpose]: { kind: 'error', message: validation } }));
      return;
    }
    setUsageTestingPurpose(purpose);
    setUsageTestState((current) => ({ ...current, [purpose]: null }));
    try {
      const response = await testStorageUsage(purpose, usageRequestInput(purpose));
      setUsageTestState((current) => ({
        ...current,
        [purpose]: {
          kind: response.ok === false ? 'error' : 'success',
          message: response.message || (zh ? '路由测试成功。' : 'Route test succeeded.'),
        },
      }));
    } catch (error) {
      setUsageTestState((current) => ({ ...current, [purpose]: { kind: 'error', message: errorMessage(error, zh) } }));
      if (error instanceof ApiError && error.status === 403) setPermissionDenied(true);
    } finally {
      setUsageTestingPurpose(null);
    }
  };

  const handleUsageSave = async (purpose: StorageUsagePurpose) => {
    const validation = usageValidationMessage(purpose);
    if (validation) {
      setUsageSaveError((current) => ({ ...current, [purpose]: validation }));
      return;
    }
    setUsageSavingPurpose(purpose);
    setUsageSaveError((current) => ({ ...current, [purpose]: '' }));
    try {
      await updateStorageUsage(purpose, usageRequestInput(purpose));
      await loadUsages();
    } catch (error) {
      setUsageSaveError((current) => ({ ...current, [purpose]: errorMessage(error, zh) }));
      if (error instanceof ApiError && error.status === 403) setPermissionDenied(true);
    } finally {
      setUsageSavingPurpose(null);
    }
  };

  const openCreate = () => {
    setMode('create');
    setEditingId(null);
    setForm({ ...EMPTY_FORM, is_default: items.length === 0 });
    setFormError('');
    setFormTest(null);
    setModalOpen(true);
  };

  const openEdit = (provider: StorageProvider) => {
    setMode('edit');
    setEditingId(provider.id);
    setForm({
      name: provider.name,
      backend: provider.backend,
      endpoint_url: provider.endpoint_url,
      bucket: provider.bucket,
      region: provider.region,
      access_key_id: '',
      secret_access_key: '',
      force_path_style: provider.force_path_style,
      verify_tls: provider.verify_tls,
      is_default: provider.is_default,
      notes: provider.notes || '',
    });
    setFormError('');
    setFormTest(null);
    setModalOpen(true);
  };

  const setField = <K extends keyof StorageProviderInput>(key: K, value: StorageProviderInput[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
    setFormError('');
  };

  const validate = () => {
    if (!form.name.trim() || !form.bucket.trim() || !form.region.trim()) {
      return zh ? '请填写名称、Bucket 和 Region。' : 'Name, bucket, and region are required.';
    }
    if (!form.endpoint_url.trim()) return zh ? '请填写 Endpoint。' : 'Endpoint is required.';
    if (mode === 'create' && (!form.access_key_id.trim() || !form.secret_access_key.trim())) {
      return zh ? '新建配置需要填写 Access Key ID 和 Secret。' : 'Access Key ID and secret are required for a new profile.';
    }
    return '';
  };

  const formConnectionInput = useMemo(() => ({
    backend: 's3' as const, endpoint_url: form.endpoint_url.trim(), bucket: form.bucket.trim(), region: form.region.trim(),
    access_key_id: form.access_key_id, secret_access_key: form.secret_access_key, force_path_style: form.force_path_style, verify_tls: form.verify_tls,
  }), [form]);

  const handleTestForm = async () => {
    const validation = validate();
    if (validation) { setFormTest({ kind: 'error', message: validation }); return; }
    setTestingId('form');
    setFormTest(null);
    try {
      const response = await testStorageProvider(formConnectionInput);
      setFormTest({ kind: response.ok === false ? 'error' : 'success', message: response.message || (zh ? '连接测试成功。' : 'Connection test succeeded.') });
    } catch (error) {
      setFormTest({ kind: 'error', message: errorMessage(error, zh) });
      if (error instanceof ApiError && error.status === 403) setPermissionDenied(true);
    } finally { setTestingId(null); }
  };

  const handleSave = async (event: React.FormEvent) => {
    event.preventDefault();
    const validation = validate();
    if (validation) { setFormError(validation); return; }
    setSaving(true);
    setFormError('');
    try {
      if (mode === 'create') {
        await createStorageProvider({ ...form, name: form.name.trim(), endpoint_url: form.endpoint_url.trim(), bucket: form.bucket.trim(), region: form.region.trim() });
      } else if (editingId) {
        const update: Partial<StorageProviderInput> = {
          name: form.name.trim(), backend: 's3', endpoint_url: form.endpoint_url.trim(), bucket: form.bucket.trim(), region: form.region.trim(),
          force_path_style: form.force_path_style, verify_tls: form.verify_tls, is_default: form.is_default, notes: form.notes,
        };
        if (form.access_key_id.trim()) update.access_key_id = form.access_key_id.trim();
        if (form.secret_access_key) update.secret_access_key = form.secret_access_key;
        await updateStorageProvider(editingId, update);
      }
      closeModal();
      await load();
      await loadUsages();
    } catch (error) {
      setFormError(errorMessage(error, zh));
      if (error instanceof ApiError && error.status === 403) setPermissionDenied(true);
    } finally { setSaving(false); }
  };

  const handleDelete = async (provider: StorageProvider) => {
    if (!window.confirm(zh ? `确定删除对象存储配置“${provider.name}”吗？此操作不可撤销。` : `Delete object storage profile “${provider.name}”? This cannot be undone.`)) return;
    setDeletingId(provider.id);
    try { await deleteStorageProvider(provider.id); await load(); await loadUsages(); }
    catch (error) { setLoadError(errorMessage(error, zh)); if (error instanceof ApiError && error.status === 403) setPermissionDenied(true); }
    finally { setDeletingId(null); }
  };

  const handleTestSaved = async (provider: StorageProvider) => {
    setTestingId(provider.id);
    setSavedTests((current) => ({ ...current, [provider.id]: null }));
    try {
      const response = await testSavedStorageProvider(provider.id);
      setSavedTests((current) => ({ ...current, [provider.id]: { kind: response.ok === false ? 'error' : 'success', message: response.message || (zh ? '连接测试成功。' : 'Connection test succeeded.') } }));
    } catch (error) {
      setSavedTests((current) => ({ ...current, [provider.id]: { kind: 'error', message: errorMessage(error, zh) } }));
      if (error instanceof ApiError && error.status === 403) setPermissionDenied(true);
    } finally { setTestingId(null); }
  };

  const title = zh ? '对象存储' : 'Object Storage';
  const subtitle = zh ? '管理 S3 兼容存储配置，供配置备份和 PAM 录像使用。' : 'Manage S3 compatible storage profiles for config backups and PAM recordings.';
  const usageModeLabel = (mode: StorageUsageProviderMode) => ({
    default: zh ? '当前默认' : 'Current default',
    environment: zh ? '环境变量' : 'Environment variables',
    profile: zh ? '指定 profile' : 'Specific profile',
  }[mode]);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <PageHero
        icon={Cloud}
        title={title}
        subtitle={subtitle}
        actions={<>
          <button type="button" className={secondaryActionBtnClass} onClick={() => void load()} disabled={loading} aria-label={zh ? '刷新对象存储' : 'Refresh object storage'}><RefreshCw size={15} className={loading ? 'animate-spin' : ''} />{zh ? '刷新' : 'Refresh'}</button>
          <button type="button" className={primaryActionBtnClass} onClick={openCreate} disabled={!isAdmin || permissionDenied}><Plus size={16} />{zh ? '新建配置' : 'New profile'}</button>
        </>}
      />
      <div className="min-h-0 flex-1 overflow-auto bg-[var(--app-bg)] px-4 py-5 sm:px-6">
        {!isAdmin && !permissionDenied && !loadError && <div className="mb-4 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"><ShieldCheck size={17} className="mt-0.5 shrink-0" /><span>{zh ? '当前账号为只读模式，仅管理员可以修改对象存储配置。' : 'This account is read-only. Only administrators can change object storage profiles.'}</span></div>}
        {permissionDenied && <div className="mb-4 flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800"><XCircle size={17} className="mt-0.5 shrink-0" /><span>{zh ? '无权访问对象存储配置，请联系管理员。' : 'You do not have access to object storage settings. Contact an administrator.'}</span></div>}
        {loadError && !permissionDenied && <div className="mb-4 flex items-start justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800"><span>{loadError}</span><button type="button" className="font-semibold underline" onClick={() => void load()}>{zh ? '重试' : 'Retry'}</button></div>}

        <section className="mb-5 rounded-2xl border border-[var(--ui-border)] bg-[var(--ui-surface)] p-4 shadow-sm sm:p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-bold text-[var(--heading-text)]">{zh ? '用途路由' : 'Storage usage routing'}</h2>
              <p className="mt-1 text-xs text-[var(--muted-text)]">{zh ? '这里只管理用途到存储的路由，不直接向 S3 上传；斜杠表示虚拟目录。' : 'This section manages routing only; it does not upload to S3. A slash represents a virtual directory.'}</p>
            </div>
            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[10px] font-semibold text-slate-600">{zh ? '用途级配置' : 'Per usage'}</span>
          </div>
          {usageLoading ? <div className="flex min-h-[130px] items-center justify-center text-sm text-[var(--muted-text)]"><Loader2 size={18} className="mr-2 animate-spin" />{zh ? '正在加载用途路由…' : 'Loading usage routes…'}</div> : usageError ? <div className="mt-4 flex items-start justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700"><span>{usageError}</span><button type="button" className="font-semibold underline" onClick={() => void loadUsages()}>{zh ? '重试' : 'Retry'}</button></div> : (
            <div className="mt-4 grid gap-4 xl:grid-cols-2">
              {USAGE_CATALOG.map((entry) => {
                const draft = usageDrafts[entry.purpose];
                const usage = usageItems.find((item) => item.purpose === entry.purpose);
                const previewPrefix = draft.key_prefix.trim().replace(/^\/+|\/+$/g, '');
                const previewObject = entry.purpose === 'config_backup' ? 'YYYY/MM/<snapshot-id>.cfg.enc' : 'YYYY/MM/<session-id>.<format>';
                return <article key={entry.purpose} className="rounded-xl border border-[var(--ui-border)] bg-[var(--ui-surface-muted)] p-4">
                  <div className="flex items-start justify-between gap-3"><div><h3 className="text-sm font-bold text-[var(--heading-text)]">{zh ? entry.zh : entry.en}</h3><p className="mt-1 text-[11px] text-[var(--muted-text)]">{zh ? '选择有效存储来源并设置对象 key 路径。' : 'Choose the effective storage source and object key path.'}</p></div><span className="rounded-full bg-white/70 px-2 py-1 text-[10px] font-semibold text-[var(--muted-text)]">{usageModeLabel(draft.provider_mode)}</span></div>
                  <div className="mt-4 grid gap-3 sm:grid-cols-2"><div><label className={labelClass} htmlFor={`usage-mode-${entry.purpose}`}>{zh ? '存储来源' : 'Storage source'}</label><select id={`usage-mode-${entry.purpose}`} className={inputClass} value={draft.provider_mode} onChange={(event) => updateUsageDraft(entry.purpose, { provider_mode: event.target.value as StorageUsageProviderMode })} disabled={!isAdmin || permissionDenied}><option value="default">{usageModeLabel('default')}</option><option value="environment">{usageModeLabel('environment')}</option><option value="profile">{usageModeLabel('profile')}</option></select></div>{draft.provider_mode === 'profile' && <div><label className={labelClass} htmlFor={`usage-profile-${entry.purpose}`}>{zh ? '存储 profile' : 'Storage profile'}</label><select id={`usage-profile-${entry.purpose}`} className={inputClass} value={draft.provider_id} onChange={(event) => updateUsageDraft(entry.purpose, { provider_id: event.target.value })} disabled={!isAdmin || permissionDenied}><option value="">{zh ? '请选择 profile' : 'Select a profile'}</option>{usageProfileOptions.filter((profile) => profile.id !== 'environment').map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select></div>}<div><label className={labelClass} htmlFor={`usage-bucket-${entry.purpose}`}>{zh ? 'Bucket 覆盖（可选）' : 'Bucket override (optional)'}</label><input id={`usage-bucket-${entry.purpose}`} className={inputClass} value={draft.bucket_override} onChange={(event) => updateUsageDraft(entry.purpose, { bucket_override: event.target.value })} placeholder={zh ? '留空使用有效 Bucket' : 'Leave blank to use effective bucket'} disabled={!isAdmin || permissionDenied} /></div><div><label className={labelClass} htmlFor={`usage-prefix-${entry.purpose}`}>{zh ? '对象 key 前缀' : 'Object key prefix'} *</label><input id={`usage-prefix-${entry.purpose}`} className={inputClass} value={draft.key_prefix} onChange={(event) => updateUsageDraft(entry.purpose, { key_prefix: event.target.value })} placeholder={entry.defaultPrefix} disabled={!isAdmin || permissionDenied} /><p className="mt-1 text-[10px] text-[var(--muted-text)]">{zh ? '斜杠仅表示虚拟目录，不会创建真实目录。' : 'Slashes represent virtual directories; no physical directory is created.'}</p></div></div>
                  <div className="mt-4 grid gap-2 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 py-2 text-xs sm:grid-cols-3"><div><span className="text-[var(--muted-text)]">{zh ? '有效 Provider' : 'Effective provider'}</span><p className="mt-1 truncate font-semibold text-[var(--ui-fg)]">{usage?.effective_provider_name || (draft.provider_mode === 'environment' ? (zh ? '环境变量' : 'Environment variables') : '—')}</p></div><div><span className="text-[var(--muted-text)]">Endpoint</span><p className="mt-1 truncate font-mono text-[var(--ui-fg)]" title={usage?.effective_endpoint_url || ''}>{usage?.effective_endpoint_url || '—'}</p></div><div><span className="text-[var(--muted-text)]">{zh ? '有效 Bucket' : 'Effective bucket'}</span><p className="mt-1 truncate font-semibold text-[var(--ui-fg)]">{usage?.effective_bucket || draft.bucket_override || '—'}</p></div></div>
                  <div className="mt-3 flex flex-wrap items-center justify-between gap-2"><p className="min-w-0 truncate text-xs text-[var(--muted-text)]" title={`${previewPrefix}/${previewObject}`}><span className="font-semibold text-[var(--ui-fg)]">{zh ? '对象 key 预览：' : 'Object key preview: '}</span><code>{previewPrefix ? `${previewPrefix}/` : ''}{previewObject}</code></p><div className="flex flex-wrap items-center gap-2"><button type="button" className={secondaryActionBtnClass} onClick={() => void handleUsageTest(entry.purpose)} disabled={!isAdmin || permissionDenied || usageTestingPurpose === entry.purpose || usageSavingPurpose === entry.purpose}><TestTube2 size={14} />{usageTestingPurpose === entry.purpose ? (zh ? '测试中…' : 'Testing…') : (zh ? '测试路由' : 'Test route')}</button><button type="button" className={primaryActionBtnClass} onClick={() => void handleUsageSave(entry.purpose)} disabled={!isAdmin || permissionDenied || usageSavingPurpose === entry.purpose || usageTestingPurpose === entry.purpose}><Save size={14} />{usageSavingPurpose === entry.purpose ? (zh ? '保存中…' : 'Saving…') : (zh ? '保存路由' : 'Save route')}</button></div></div>
                  {usageTestState[entry.purpose] && <div className={`mt-3 flex items-start gap-2 rounded-lg px-3 py-2 text-xs ${usageTestState[entry.purpose]?.kind === 'success' ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'}`}>{usageTestState[entry.purpose]?.kind === 'success' ? <CheckCircle2 size={14} className="mt-0.5 shrink-0" /> : <XCircle size={14} className="mt-0.5 shrink-0" />}<span>{usageTestState[entry.purpose]?.message}</span></div>}
                  {usageSaveError[entry.purpose] && <div className="mt-3 flex items-start gap-2 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700"><XCircle size={14} className="mt-0.5 shrink-0" /><span>{usageSaveError[entry.purpose]}</span></div>}
                </article>;
              })}
            </div>
          )}
        </section>

        {loading ? <div className="flex min-h-[240px] items-center justify-center text-sm text-[var(--muted-text)]"><Loader2 size={20} className="mr-2 animate-spin" />{zh ? '正在加载配置…' : 'Loading profiles…'}</div> : !loadError && !permissionDenied && items.length === 0 ? (
          <div className="mx-auto flex min-h-[280px] max-w-xl flex-col items-center justify-center rounded-2xl border border-dashed border-[var(--ui-border)] bg-[var(--ui-surface)] px-6 text-center shadow-sm"><div className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-cyan-50 text-cyan-600"><Cloud size={24} /></div><h2 className="text-base font-bold text-[var(--heading-text)]">{zh ? '尚未配置对象存储' : 'No object storage profiles yet'}</h2><p className="mt-1 text-sm text-[var(--muted-text)]">{zh ? '创建一个 S3 配置后，备份任务即可使用。' : 'Create an S3 profile to make it available to backup tasks.'}</p><button type="button" className={`${primaryActionBtnClass} mt-5`} onClick={openCreate} disabled={!isAdmin}><Plus size={16} />{zh ? '创建第一个配置' : 'Create first profile'}</button></div>
        ) : !loadError && !permissionDenied ? <>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2"><p className="text-xs text-[var(--muted-text)]">{zh ? `${items.length} 个配置` : `${items.length} profile${items.length === 1 ? '' : 's'}`}</p>{effectiveDefaultId && <span className="rounded-full bg-cyan-50 px-3 py-1 text-xs font-semibold text-cyan-700">{zh ? `当前生效：${items.find((item) => item.id === effectiveDefaultId)?.name || '环境变量'}` : `Effective: ${items.find((item) => item.id === effectiveDefaultId)?.name || 'environment'}`}{defaultSource === 'environment' && ` · ${zh ? '环境变量' : 'environment'}`}</span>}</div>
          <div className="grid gap-4 xl:grid-cols-2">{items.map((provider) => {
            const test = savedTests[provider.id];
            const isEffective = provider.id === effectiveDefaultId;
            const isEnvironment = provider.source === 'environment';
            return <article key={provider.id} className={`rounded-2xl border bg-[var(--ui-surface)] p-4 shadow-sm ${isEffective ? 'border-cyan-300 ring-1 ring-cyan-200' : 'border-[var(--ui-border)]'}`}>
              <div className="flex items-start justify-between gap-3"><div className="flex min-w-0 items-center gap-3"><div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-cyan-50 text-cyan-600"><Server size={19} /></div><div className="min-w-0"><h2 className="truncate text-base font-bold text-[var(--heading-text)]">{provider.name}</h2><p className="truncate text-xs text-[var(--muted-text)]">S3 · {provider.bucket} · {provider.region}</p></div></div><div className="flex shrink-0 items-center gap-1.5">{isEffective && <span className="rounded-full bg-emerald-50 px-2 py-1 text-[10px] font-bold text-emerald-700">{zh ? '默认' : 'Default'}</span>}<span className="rounded-full bg-slate-100 px-2 py-1 text-[10px] font-semibold text-slate-600">{provider.source === 'environment' ? (zh ? '环境变量' : 'Environment') : (zh ? '数据库' : 'Database')}</span></div></div>
              <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-2"><div><dt className="text-[var(--muted-text)]">Endpoint</dt><dd className="mt-1 truncate font-mono text-[var(--ui-fg)]" title={provider.endpoint_url}>{provider.endpoint_url}</dd></div><div><dt className="text-[var(--muted-text)]">{zh ? '凭据' : 'Credentials'}</dt><dd className="mt-1 flex items-center gap-1.5 text-[var(--ui-fg)]"><KeyRound size={13} className="text-[var(--muted-text)]" />{provider.has_access_key ? provider.access_key_id_masked || (zh ? '已配置' : 'Configured') : (zh ? '未配置 Access Key' : 'No access key')}<span className={provider.has_secret_key ? 'text-emerald-600' : 'text-amber-600'}>{provider.has_secret_key ? '· Secret ✓' : '· Secret —'}</span></dd></div><div><dt className="text-[var(--muted-text)]">{zh ? '连接选项' : 'Connection options'}</dt><dd className="mt-1 text-[var(--ui-fg)]">{provider.force_path_style ? 'Path style' : 'Virtual host'} · TLS {provider.verify_tls ? (zh ? '校验' : 'verify') : (zh ? '跳过' : 'skip')}</dd></div><div><dt className="text-[var(--muted-text)]">{zh ? '更新时间' : 'Updated'}</dt><dd className="mt-1 text-[var(--ui-fg)]">{formatDate(provider.updated_at || provider.created_at, zh)}</dd></div></dl>
              {provider.notes && <p className="mt-3 rounded-lg bg-[var(--ui-surface-muted)] px-3 py-2 text-xs text-[var(--muted-text)]">{provider.notes}</p>}
              {test && <div className={`mt-3 flex items-start gap-2 rounded-lg px-3 py-2 text-xs ${test.kind === 'success' ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'}`}>{test.kind === 'success' ? <CheckCircle2 size={14} className="mt-0.5 shrink-0" /> : <XCircle size={14} className="mt-0.5 shrink-0" />}<span>{test.message}</span></div>}
              <div className="mt-4 flex flex-wrap items-center justify-end gap-2 border-t border-[var(--ui-border)] pt-3"><button type="button" className={secondaryActionBtnClass} onClick={() => void handleTestSaved(provider)} disabled={testingId === provider.id}><TestTube2 size={14} />{testingId === provider.id ? (zh ? '测试中…' : 'Testing…') : (zh ? '测试连接' : 'Test')}</button><button type="button" className={secondaryActionBtnClass} onClick={() => openEdit(provider)} disabled={!isAdmin || permissionDenied || isEnvironment}><Pencil size={14} />{zh ? '编辑' : 'Edit'}</button><button type="button" className="inline-flex items-center gap-1.5 rounded-md border border-rose-200 px-3 py-2 text-[13px] font-semibold text-rose-600 transition hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50" onClick={() => void handleDelete(provider)} disabled={!isAdmin || permissionDenied || deletingId === provider.id || isEnvironment}><Trash2 size={14} />{deletingId === provider.id ? (zh ? '删除中…' : 'Deleting…') : (zh ? '删除' : 'Delete')}</button></div>
            </article>;
          })}</div>
        </> : null}

      </div>

      {modalOpen && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) closeModal(); }}><div role="dialog" aria-modal="true" aria-labelledby="storage-dialog-title" className="max-h-[min(850px,calc(100vh-2rem))] w-full max-w-3xl overflow-y-auto rounded-2xl border border-[var(--ui-border)] bg-[var(--ui-surface)] shadow-2xl"><div className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-[var(--ui-border)] bg-[var(--ui-surface)] px-5 py-4"><div><h2 id="storage-dialog-title" className="text-lg font-bold text-[var(--heading-text)]">{mode === 'create' ? (zh ? '新建对象存储配置' : 'New object storage profile') : (zh ? '编辑对象存储配置' : 'Edit object storage profile')}</h2><p className="mt-1 text-xs text-[var(--muted-text)]">{zh ? '支持 S3 兼容服务。凭据只会按后端安全策略保存。' : 'S3 compatible services are supported. Credentials are stored according to backend security policy.'}</p></div><button type="button" className="rounded-lg p-1.5 text-[var(--muted-text)] hover:bg-[var(--ui-surface-muted)]" onClick={closeModal} disabled={saving} aria-label={zh ? '关闭' : 'Close'}><X size={18} /></button></div><form onSubmit={handleSave} className="space-y-5 p-5"><div className="grid gap-4 sm:grid-cols-2"><div><label className={labelClass} htmlFor="storage-name">{zh ? '名称' : 'Name'} *</label><input id="storage-name" className={inputClass} value={form.name} onChange={(e) => setField('name', e.target.value)} autoFocus /></div><div><label className={labelClass} htmlFor="storage-backend">{zh ? '类型' : 'Backend'}</label><select id="storage-backend" className={inputClass} value={form.backend} disabled><option value="s3">S3</option></select></div><div><label className={labelClass} htmlFor="storage-endpoint">Endpoint *</label><input id="storage-endpoint" className={inputClass} value={form.endpoint_url} onChange={(e) => setField('endpoint_url', e.target.value)} placeholder="https://s3.example.com" /></div><div><label className={labelClass} htmlFor="storage-bucket">Bucket *</label><input id="storage-bucket" className={inputClass} value={form.bucket} onChange={(e) => setField('bucket', e.target.value)} /></div><div><label className={labelClass} htmlFor="storage-region">Region *</label><input id="storage-region" className={inputClass} value={form.region} onChange={(e) => setField('region', e.target.value)} placeholder="us-east-1" /></div><div><label className={labelClass} htmlFor="storage-access-key">Access Key ID {mode === 'create' ? '*' : ''}</label>{mode === 'edit' && <p className="mb-1 text-[11px] text-[var(--muted-text)]">{zh ? '当前值：' : 'Current: '}{items.find((item) => item.id === editingId)?.access_key_id_masked || (zh ? '未配置' : 'Not configured')}</p>}<input id="storage-access-key" className={inputClass} value={form.access_key_id} onChange={(e) => setField('access_key_id', e.target.value)} placeholder={mode === 'edit' ? (zh ? '留空保留当前凭据' : 'Leave blank to keep current credential') : ''} autoComplete="off" /></div><div><label className={labelClass} htmlFor="storage-secret">Secret Access Key {mode === 'create' ? '*' : ''}</label>{mode === 'edit' && <p className="mb-1 text-[11px] text-[var(--muted-text)]">{items.find((item) => item.id === editingId)?.has_secret_key ? (zh ? '当前 Secret 已配置' : 'Current secret is configured') : (zh ? '当前未配置 Secret' : 'No current secret')}</p>}<input id="storage-secret" type="password" className={inputClass} value={form.secret_access_key} onChange={(e) => setField('secret_access_key', e.target.value)} placeholder={mode === 'edit' ? (zh ? '留空保留当前凭据' : 'Leave blank to keep current credential') : ''} autoComplete="new-password" /></div></div><div className="flex flex-wrap gap-5 rounded-xl border border-[var(--ui-border)] bg-[var(--ui-surface-muted)] p-3 text-sm"><label className="inline-flex items-center gap-2 text-[var(--ui-fg)]"><input type="checkbox" checked={form.force_path_style} onChange={(e) => setField('force_path_style', e.target.checked)} />{zh ? '使用 Path-style 地址' : 'Use path-style addressing'}</label><label className="inline-flex items-center gap-2 text-[var(--ui-fg)]"><input type="checkbox" checked={form.verify_tls} onChange={(e) => setField('verify_tls', e.target.checked)} />{zh ? '校验 TLS 证书' : 'Verify TLS certificate'}</label><label className="inline-flex items-center gap-2 text-[var(--ui-fg)]"><input type="checkbox" checked={form.is_default} onChange={(e) => setField('is_default', e.target.checked)} />{zh ? '设为默认配置' : 'Set as default'}</label></div><div><label className={labelClass} htmlFor="storage-notes">{zh ? '备注' : 'Notes'}</label><textarea id="storage-notes" className={`${inputClass} min-h-20 resize-y`} value={form.notes} onChange={(e) => setField('notes', e.target.value)} /></div>{formTest && <div className={`flex items-start gap-2 rounded-lg px-3 py-2 text-xs ${formTest.kind === 'success' ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'}`}>{formTest.kind === 'success' ? <CheckCircle2 size={14} className="mt-0.5 shrink-0" /> : <XCircle size={14} className="mt-0.5 shrink-0" />}<span>{formTest.message}</span></div>}{formError && <div className="flex items-start gap-2 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700"><XCircle size={15} className="mt-0.5 shrink-0" /><span>{formError}</span></div>}<div className="flex flex-wrap items-center justify-between gap-3 border-t border-[var(--ui-border)] pt-4"><button type="button" className={secondaryActionBtnClass} onClick={() => void handleTestForm()} disabled={testingId === 'form' || saving}><TestTube2 size={15} />{testingId === 'form' ? (zh ? '测试中…' : 'Testing…') : (zh ? '测试当前配置' : 'Test current')}</button><div className="flex gap-2"><button type="button" className={secondaryActionBtnClass} onClick={closeModal} disabled={saving}>{zh ? '取消' : 'Cancel'}</button><button type="submit" className={primaryActionBtnClass} disabled={saving}><Save size={15} />{saving ? (zh ? '保存中…' : 'Saving…') : (zh ? '保存配置' : 'Save profile')}</button></div></div></form></div></div>}
    </div>
  );
};

export default StorageManagementPage;
