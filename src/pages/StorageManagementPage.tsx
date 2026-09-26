import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CheckCircle2,
  Cloud,
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
import {
  createStorageProvider,
  deleteStorageProvider,
  listStorageProviders,
  testSavedStorageProvider,
  testStorageProvider,
  updateStorageProvider,
  type StorageProvider,
  type StorageProviderInput,
  type StorageTestResponse,
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

const EMPTY_FORM: StorageProviderInput = {
  name: '',
  backend: 's3',
  endpoint_url: '',
  bucket: '',
  access_key_id: '',
  secret_access_key: '',
  force_path_style: true,
  verify_tls: true,
  is_default: false,
  notes: '',
};

const inputClass = 'w-full rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 py-2 text-sm text-[var(--ui-fg)] outline-none transition focus:border-[var(--ui-accent)] focus:ring-2 focus:ring-[var(--ui-accent)]/15';

const errorMessage = (error: unknown, zh: boolean): string => {
  if (error instanceof ApiError) {
    if (error.status === 401) return zh ? '登录已失效，请重新登录。' : 'Your session has expired. Please sign in again.';
    if (error.status === 403) return zh ? '你没有管理对象存储的权限。' : 'You do not have permission to manage object storage.';
    if (error.status >= 500) return zh ? '服务暂时不可用，请稍后重试。' : 'The service is temporarily unavailable. Please try again.';
    return error.message.replace(/\s*\(Request ID:.*\)$/i, '') || (zh ? '请求失败，请重试。' : 'Request failed. Please try again.');
  }
  return error instanceof Error ? error.message : (zh ? '请求失败，请重试。' : 'Request failed. Please try again.');
};

const storageTestResult = (response: StorageTestResponse, zh: boolean): TestState => {
  const success = response.ok !== false;
  return {
    kind: success ? 'success' : 'error',
    message: success
      ? (zh
        ? 'S3 已连通且 Bucket 列表可访问；本项检查不验证文件上传和读取。'
        : 'S3 is reachable and the bucket listing is accessible. This check does not verify object uploads or reads.')
      : (response.message || (zh ? 'S3 连接或 Bucket 访问检查失败。' : 'S3 connection or bucket access check failed.')),
  };
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
    if (!form.name.trim() || !form.bucket.trim()) {
      return zh ? '请填写名称和 Bucket。' : 'Name and bucket are required.';
    }
    if (!form.endpoint_url.trim()) return zh ? '请填写 Endpoint。' : 'Endpoint is required.';
    if (mode === 'create' && (!form.access_key_id.trim() || !form.secret_access_key.trim())) {
      return zh ? '新建配置需要填写 Access Key ID 和 Secret。' : 'Access Key ID and secret are required for a new profile.';
    }
    return '';
  };

  const formConnectionInput = useMemo(() => ({
    backend: 's3' as const, endpoint_url: form.endpoint_url.trim(), bucket: form.bucket.trim(),
    access_key_id: form.access_key_id, secret_access_key: form.secret_access_key, force_path_style: form.force_path_style, verify_tls: form.verify_tls,
  }), [form]);

  const handleTestForm = async () => {
    const validation = validate();
    if (validation) { setFormTest({ kind: 'error', message: validation }); return; }
    const savedProfile = mode === 'edit' ? items.find((item) => item.id === editingId) : undefined;
    const hasAccessKey = Boolean(form.access_key_id.trim());
    const hasSecretKey = Boolean(form.secret_access_key);
    const connectionChanged = savedProfile && (
      form.endpoint_url.trim() !== savedProfile.endpoint_url
      || form.bucket.trim() !== savedProfile.bucket
      || form.force_path_style !== savedProfile.force_path_style
      || form.verify_tls !== savedProfile.verify_tls
    );
    if (mode === 'edit' && !hasAccessKey && !hasSecretKey && connectionChanged) {
      setFormTest({ kind: 'error', message: zh ? '连接参数已修改，请输入新的 Access Key 和 Secret 后再测试。' : 'Connection settings changed. Enter both credentials to test the draft.' });
      return;
    }
    if (hasAccessKey !== hasSecretKey) {
      setFormTest({ kind: 'error', message: zh ? '请同时填写 Access Key ID 和 Secret。' : 'Enter both the Access Key ID and secret.' });
      return;
    }
    setTestingId('form');
    setFormTest(null);
    try {
      const connectionInput = mode === 'edit' && savedProfile
        ? { ...formConnectionInput, region: savedProfile.region }
        : formConnectionInput;
      const response = mode === 'edit' && !hasAccessKey && savedProfile
        ? await testSavedStorageProvider(savedProfile.id)
        : await testStorageProvider(connectionInput);
      setFormTest(storageTestResult(response, zh));
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
        await createStorageProvider({ ...form, name: form.name.trim(), endpoint_url: form.endpoint_url.trim(), bucket: form.bucket.trim() });
      } else if (editingId) {
        const update: Partial<StorageProviderInput> = {
          name: form.name.trim(), backend: 's3', endpoint_url: form.endpoint_url.trim(), bucket: form.bucket.trim(),
          force_path_style: form.force_path_style, verify_tls: form.verify_tls, is_default: form.is_default, notes: form.notes,
        };
        if (form.access_key_id.trim()) update.access_key_id = form.access_key_id.trim();
        if (form.secret_access_key) update.secret_access_key = form.secret_access_key;
        await updateStorageProvider(editingId, update);
      }
      closeModal();
      await load();
    } catch (error) {
      setFormError(errorMessage(error, zh));
      if (error instanceof ApiError && error.status === 403) setPermissionDenied(true);
    } finally { setSaving(false); }
  };

  const handleDelete = async (provider: StorageProvider) => {
    if (!window.confirm(zh ? `确定删除对象存储配置“${provider.name}”吗？此操作不可撤销。` : `Delete object storage profile “${provider.name}”? This cannot be undone.`)) return;
    setDeletingId(provider.id);
    try { await deleteStorageProvider(provider.id); await load(); }
    catch (error) { setLoadError(errorMessage(error, zh)); if (error instanceof ApiError && error.status === 403) setPermissionDenied(true); }
    finally { setDeletingId(null); }
  };

  const handleTestSaved = async (provider: StorageProvider) => {
    setTestingId(provider.id);
    setSavedTests((current) => ({ ...current, [provider.id]: null }));
    try {
      const response = await testSavedStorageProvider(provider.id);
      setSavedTests((current) => ({ ...current, [provider.id]: storageTestResult(response, zh) }));
    } catch (error) {
      setSavedTests((current) => ({ ...current, [provider.id]: { kind: 'error', message: errorMessage(error, zh) } }));
      if (error instanceof ApiError && error.status === 403) setPermissionDenied(true);
    } finally { setTestingId(null); }
  };

  const defaultProfileName = items.find((item) => item.id === effectiveDefaultId)?.name
    || (defaultSource === 'environment' ? (zh ? '环境变量' : 'Environment') : '—');
  const formRowClass = 'grid gap-1.5 sm:grid-cols-[150px_minmax(0,1fr)] sm:items-start sm:gap-5';
  const formRowLabelClass = 'pt-2 text-xs font-semibold text-[var(--muted-text)]';

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <div className="min-h-0 flex-1 overflow-auto bg-[var(--app-bg)] px-4 py-4 sm:px-6 sm:py-5">
        {!isAdmin && !permissionDenied && !loadError && <div className="mb-4 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"><ShieldCheck size={17} className="mt-0.5 shrink-0" /><span>{zh ? '当前账号为只读模式，仅管理员可以修改存储设置。' : 'This account is read-only. Only administrators can change storage settings.'}</span></div>}
        {permissionDenied && <div className="mb-4 flex items-start gap-2 rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800"><XCircle size={17} className="mt-0.5 shrink-0" /><span>{zh ? '无权访问存储设置，请联系管理员。' : 'You do not have access to storage settings. Contact an administrator.'}</span></div>}

        <section className="overflow-hidden rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--ui-border)] px-5 pt-1 sm:px-6">
            <h1 className="py-3 text-sm font-semibold text-[var(--heading-text)]">{zh ? '对象存储' : 'Object Storage'}</h1>
            <div className="mb-1 flex items-center gap-2">
              <button type="button" className="rounded-md p-2 text-[var(--muted-text)] transition hover:bg-[var(--ui-surface-muted)] hover:text-[var(--ui-fg)] disabled:opacity-50" onClick={() => { void load(); }} disabled={loading} aria-label={zh ? '刷新存储设置' : 'Refresh storage settings'} title={zh ? '刷新' : 'Refresh'}><RefreshCw size={15} className={loading ? 'animate-spin' : ''} /></button>
              <button type="button" className="inline-flex items-center gap-1.5 rounded-md bg-emerald-600 px-3.5 py-2 text-sm font-semibold text-white transition hover:bg-emerald-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50" onClick={openCreate} disabled={!isAdmin || permissionDenied}><Plus size={15} />{zh ? '新增' : 'New'}</button>
            </div>
          </div>

          <div className="p-5 sm:p-6">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold text-[var(--heading-text)]">{zh ? '对象存储配置' : 'Object storage profiles'}</h2>
              </div>
              <div className="flex items-center gap-2 text-xs text-[var(--muted-text)]">
                <span>{zh ? `${items.length} 个配置` : `${items.length} profile${items.length === 1 ? '' : 's'}`}</span>
                <span className="text-[var(--ui-border)]">|</span>
                <span>{zh ? '当前默认：' : 'Current default: '}<strong className="font-semibold text-[var(--ui-fg)]">{defaultProfileName}</strong></span>
                {defaultSource === 'environment' && <span className="rounded bg-slate-100 px-1.5 py-0.5">.env</span>}
              </div>
            </div>

            {loadError && !permissionDenied && <div className="mb-4 flex items-center justify-between gap-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2.5 text-sm text-rose-800"><span>{loadError}</span><button type="button" className="font-semibold underline" onClick={() => void load()}>{zh ? '重试' : 'Retry'}</button></div>}
            <div className="overflow-x-auto rounded-md border border-[var(--ui-border)]">
              <table className="min-w-[920px] w-full border-collapse text-left text-sm">
                <thead className="bg-[var(--ui-surface-muted)] text-xs text-[var(--muted-text)]">
                  <tr>
                    <th className="px-4 py-3 font-semibold">{zh ? '名称' : 'Name'}</th>
                    <th className="px-4 py-3 font-semibold">Endpoint</th>
                    <th className="px-4 py-3 font-semibold">Bucket</th>
                    <th className="px-4 py-3 font-semibold">{zh ? '访问凭据' : 'Credentials'}</th>
                    <th className="px-4 py-3 font-semibold">{zh ? '状态' : 'Status'}</th>
                    <th className="px-4 py-3 font-semibold">{zh ? '更新时间' : 'Updated'}</th>
                    <th className="px-4 py-3 text-right font-semibold">{zh ? '操作' : 'Actions'}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--ui-border)]">
                  {loading ? <tr><td colSpan={7} className="h-40 text-center text-sm text-[var(--muted-text)]"><span className="inline-flex items-center gap-2"><Loader2 size={17} className="animate-spin" />{zh ? '正在加载配置…' : 'Loading profiles…'}</span></td></tr>
                    : items.length === 0 ? <tr><td colSpan={7} className="px-4 py-14 text-center">
                      <div className="mx-auto flex max-w-md flex-col items-center">
                        <span className="mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-[var(--ui-surface-muted)] text-[var(--ui-accent)]"><Cloud size={21} /></span>
                        <strong className="text-sm font-semibold text-[var(--heading-text)]">{zh ? '尚未配置对象存储' : 'No object storage configured'}</strong>
                        <button type="button" onClick={openCreate} disabled={!isAdmin || permissionDenied} className={`${primaryActionBtnClass} mt-4`}><Plus size={15} />{zh ? '创建存储配置' : 'Create profile'}</button>
                      </div>
                    </td></tr>
                    : items.map((provider) => {
                      const isEnvironment = provider.source === 'environment';
                      const isEffective = provider.id === effectiveDefaultId;
                      const rowTest = savedTests[provider.id];
                      return <React.Fragment key={provider.id}>
                        <tr className="transition-colors hover:bg-[var(--ui-surface-muted)]/60">
                          <td className="px-4 py-3.5">
                            <div className="flex items-center gap-2.5">
                              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-sky-50 text-sky-700"><Server size={15} /></span>
                              <span className="min-w-0"><span className="block truncate font-semibold text-[var(--ui-fg)]">{provider.name}</span></span>
                            </div>
                          </td>
                          <td className="max-w-[220px] truncate px-4 py-3.5 font-mono text-xs text-[var(--muted-text)]" title={provider.endpoint_url}>{provider.endpoint_url || '—'}</td>
                          <td className="px-4 py-3.5"><span className="block font-medium text-[var(--ui-fg)]">{provider.bucket || '—'}</span></td>
                          <td className="px-4 py-3.5"><span className="block font-mono text-xs text-[var(--ui-fg)]">{provider.access_key_id_masked || (provider.has_access_key ? (zh ? '已配置' : 'Configured') : '—')}</span><span className={`mt-0.5 block text-[11px] ${provider.has_secret_key ? 'text-emerald-700' : 'text-[var(--muted-text)]'}`}>{provider.has_secret_key ? (zh ? 'Secret 已配置' : 'Secret configured') : (zh ? '无 Secret' : 'No secret')}</span></td>
                          <td className="px-4 py-3.5"><div className="flex flex-wrap gap-1.5">{isEffective && <span className="rounded-full bg-emerald-50 px-2 py-1 text-[10px] font-semibold text-emerald-700">{zh ? '当前默认' : 'Default'}</span>}{provider.is_default && !isEffective && <span className="rounded-full bg-slate-100 px-2 py-1 text-[10px] font-semibold text-slate-600">{zh ? '默认' : 'Default'}</span>}{isEnvironment && <span className="rounded-full bg-slate-100 px-2 py-1 text-[10px] font-semibold text-slate-600">.env</span>}</div></td>
                          <td className="px-4 py-3.5 text-xs text-[var(--muted-text)]">{formatDate(provider.updated_at || provider.created_at, zh)}</td>
                          <td className="px-4 py-3.5"><div className="flex items-center justify-end gap-1">
                            <button type="button" className="rounded-md p-2 text-[var(--muted-text)] transition hover:bg-sky-50 hover:text-sky-700 disabled:opacity-40" onClick={() => void handleTestSaved(provider)} disabled={!isAdmin || permissionDenied || testingId === provider.id} title={zh ? '测试连接' : 'Test connection'} aria-label={zh ? `测试 ${provider.name}` : `Test ${provider.name}`}><TestTube2 size={15} /></button>
                            <button type="button" className="rounded-md p-2 text-[var(--muted-text)] transition hover:bg-slate-100 hover:text-[var(--ui-fg)] disabled:opacity-40" onClick={() => openEdit(provider)} disabled={!isAdmin || permissionDenied || isEnvironment} title={zh ? '编辑' : 'Edit'} aria-label={zh ? `编辑 ${provider.name}` : `Edit ${provider.name}`}><Pencil size={15} /></button>
                            <button type="button" className="rounded-md p-2 text-[var(--muted-text)] transition hover:bg-rose-50 hover:text-rose-700 disabled:opacity-40" onClick={() => void handleDelete(provider)} disabled={!isAdmin || permissionDenied || deletingId === provider.id || isEnvironment} title={zh ? '删除' : 'Delete'} aria-label={zh ? `删除 ${provider.name}` : `Delete ${provider.name}`}><Trash2 size={15} /></button>
                          </div></td>
                        </tr>
                        {rowTest && <tr><td colSpan={7} className="bg-[var(--ui-surface-muted)]/50 px-4 py-2"><span className={`inline-flex items-center gap-1.5 text-xs ${rowTest.kind === 'success' ? 'text-emerald-700' : 'text-rose-700'}`}>{rowTest.kind === 'success' ? <CheckCircle2 size={13} /> : <XCircle size={13} />}{rowTest.message}</span></td></tr>}
                      </React.Fragment>;
                    })}
                </tbody>
              </table>
            </div>
            <div className="mt-3 rounded-md border border-[var(--ui-border)] bg-[var(--ui-surface-muted)] px-3 py-2.5 text-xs text-[var(--muted-text)]">
              <p className="font-semibold text-[var(--heading-text)]">{zh ? '存储用途' : 'Storage usage'}</p>
              <p className="mt-1">
                {zh
                  ? '当前全局默认 Bucket 同时用于配置备份（config/）和 PAM 会话录像（pam/）；知识库文件目前未接入此对象存储。Bucket 需要先在 S3 服务中创建，本页只保存连接配置。'
                  : 'The global-default bucket stores configuration backups under config/ and PAM session recordings under pam/. Knowledge-base files are not currently routed to this object store. Create the bucket in the S3 service first; this page only saves connection settings.'}
              </p>
              <p className="mt-1">
                {zh
                  ? 'Environment 配置读取自 .env；只有数据库中没有全局默认配置时才会作为回退项使用。'
                  : 'The Environment profile reads from .env and is used as a fallback only when no database profile is set as the global default.'}
              </p>
            </div>
            {items.length > 0 && <p className="mt-3 text-[11px] text-[var(--muted-text)]">{zh ? '已被对象引用的配置不能删除或修改连接参数。' : 'Profiles referenced by stored objects cannot be deleted or have their connection settings changed.'}</p>}
          </div>
        </section>
      </div>

      {modalOpen && <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-[2px] sm:p-6" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) closeModal(); }}>
        <div role="dialog" aria-modal="true" aria-labelledby="storage-dialog-title" className="relative z-10 flex max-h-[calc(100vh-2rem)] w-full max-w-4xl flex-col overflow-hidden rounded-xl border border-[var(--ui-border)] bg-[var(--ui-surface)] shadow-2xl sm:max-h-[calc(100vh-3rem)]">
          <div className="flex shrink-0 items-start justify-between gap-4 border-b border-[var(--ui-border)] px-5 py-4 sm:px-7">
            <div><h2 id="storage-dialog-title" className="text-lg font-semibold text-[var(--heading-text)]">{mode === 'create' ? (zh ? '创建存储设置' : 'Create storage settings') : (zh ? '编辑存储设置' : 'Edit storage settings')}</h2></div>
            <button type="button" className="rounded-lg p-2 text-[var(--muted-text)] transition hover:bg-[var(--ui-surface-muted)] hover:text-[var(--ui-fg)]" onClick={closeModal} disabled={saving} aria-label={zh ? '关闭' : 'Close'}><X size={18} /></button>
          </div>

          <form onSubmit={handleSave} className="flex min-h-0 flex-1 flex-col">
            <div className="min-h-0 flex-1 space-y-7 overflow-y-auto px-5 py-5 sm:px-7 sm:py-6">
              <section>
                <div className="mb-4 border-b border-[var(--ui-border)] pb-2"><h3 className="text-sm font-semibold text-[var(--heading-text)]">{zh ? '基本设置' : 'Basic settings'}</h3></div>
                <div className="space-y-3">
                  <div className={formRowClass}><label className={formRowLabelClass} htmlFor="storage-name">{zh ? '名称' : 'Name'} <span className="text-rose-600">*</span></label><input id="storage-name" className={inputClass} value={form.name} onChange={(event) => setField('name', event.target.value)} autoFocus placeholder={zh ? '名称' : 'Name'} /></div>
                  <div className={formRowClass}><span className={formRowLabelClass}>{zh ? '类型' : 'Type'}</span><span className="flex h-[38px] items-center rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface-muted)] px-3 text-sm text-[var(--ui-fg)]">S3</span></div>
                </div>
              </section>

              <section>
                <div className="mb-4 border-b border-[var(--ui-border)] pb-2"><h3 className="text-sm font-semibold text-[var(--heading-text)]">S3</h3></div>
                <div className="space-y-3">
                  <div className={formRowClass}><label className={formRowLabelClass} htmlFor="storage-bucket">{zh ? '桶名称' : 'Bucket name'} <span className="text-rose-600">*</span></label><input id="storage-bucket" className={inputClass} value={form.bucket} onChange={(event) => setField('bucket', event.target.value)} placeholder={zh ? '桶名称' : 'Bucket name'} /></div>
                  <div className={formRowClass}><label className={formRowLabelClass} htmlFor="storage-access-key">Access key ID {mode === 'create' && <span className="text-rose-600">*</span>}</label><div><input id="storage-access-key" className={inputClass} value={form.access_key_id} onChange={(event) => setField('access_key_id', event.target.value)} placeholder={mode === 'edit' ? (zh ? '留空保留当前值' : 'Leave blank to keep current') : 'Access key ID'} autoComplete="off" />{mode === 'edit' && <p className="mt-1 text-[11px] text-[var(--muted-text)]">{zh ? '当前值：' : 'Current: '}{items.find((item) => item.id === editingId)?.access_key_id_masked || (zh ? '已隐藏' : 'Hidden')}</p>}</div></div>
                  <div className={formRowClass}><label className={formRowLabelClass} htmlFor="storage-secret">Access key secret {mode === 'create' && <span className="text-rose-600">*</span>}</label><div><input id="storage-secret" type="password" className={inputClass} value={form.secret_access_key} onChange={(event) => setField('secret_access_key', event.target.value)} placeholder={mode === 'edit' ? (zh ? '留空保留当前值' : 'Leave blank to keep current') : 'Access key secret'} autoComplete="new-password" />{mode === 'edit' && <p className="mt-1 text-[11px] text-[var(--muted-text)]">{items.find((item) => item.id === editingId)?.has_secret_key ? (zh ? '当前 Secret 已加密保存' : 'Current secret is stored securely') : (zh ? '当前未配置 Secret' : 'No current secret')}</p>}</div></div>
                  <div className={formRowClass}><label className={formRowLabelClass} htmlFor="storage-endpoint">{zh ? '端点' : 'Endpoint'} <span className="text-rose-600">*</span></label><div><input id="storage-endpoint" className={inputClass} value={form.endpoint_url} onChange={(event) => setField('endpoint_url', event.target.value)} placeholder={zh ? '端点' : 'Endpoint'} /><p className="mt-1 text-[11px] text-[var(--muted-text)]">{zh ? '填写 S3 API 地址（如 http://seaweedfs:8333）；Bucket 名和 config/、pam/ 目录不要填在 Endpoint 里，除非服务商明确要求路径前缀。' : 'Enter the S3 API URL (for example, http://seaweedfs:8333). Do not append the bucket name or config/ and pam/ folders unless your provider explicitly requires a path prefix.'}</p></div></div>
                </div>
              </section>

              <section>
                <div className="mb-4 border-b border-[var(--ui-border)] pb-2"><h3 className="text-sm font-semibold text-[var(--heading-text)]">{zh ? '其他设置' : 'Other settings'}</h3></div>
                <div className="space-y-4">
                  <div className={formRowClass}><label className={formRowLabelClass}>{zh ? '默认' : 'Default'}</label><label className="flex cursor-pointer items-center gap-2 pt-2 text-sm text-[var(--ui-fg)]"><input type="checkbox" className="accent-[var(--ui-accent)]" checked={form.is_default} onChange={(event) => setField('is_default', event.target.checked)} />{zh ? '设为全局默认' : 'Set as global default'}</label></div>
                  <div className={formRowClass}><label className={formRowLabelClass} htmlFor="storage-notes">{zh ? '备注' : 'Notes'}</label><textarea id="storage-notes" className={`${inputClass} min-h-20 resize-y`} value={form.notes} onChange={(event) => setField('notes', event.target.value)} placeholder={zh ? '选填' : 'Optional'} /></div>
                </div>
              </section>

              {formTest && <div className={`flex items-start gap-2 rounded-md px-3 py-2.5 text-sm ${formTest.kind === 'success' ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'}`}>{formTest.kind === 'success' ? <CheckCircle2 size={15} className="mt-0.5 shrink-0" /> : <XCircle size={15} className="mt-0.5 shrink-0" />}<span>{formTest.message}</span></div>}
              {formError && <div className="flex items-start gap-2 rounded-md bg-rose-50 px-3 py-2.5 text-sm text-rose-700"><XCircle size={15} className="mt-0.5 shrink-0" /><span>{formError}</span></div>}
            </div>

            <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-[var(--ui-border)] bg-[var(--ui-surface)] px-5 py-3.5 sm:px-7">
              <button type="button" className={secondaryActionBtnClass} onClick={() => void handleTestForm()} disabled={testingId === 'form' || saving}><TestTube2 size={15} />{testingId === 'form' ? (zh ? '测试中…' : 'Testing…') : (zh ? '测试连接' : 'Test connection')}</button>
              <div className="flex gap-2"><button type="button" className={secondaryActionBtnClass} onClick={closeModal} disabled={saving}>{zh ? '取消' : 'Cancel'}</button><button type="submit" className={primaryActionBtnClass} disabled={saving}><Save size={15} />{saving ? (zh ? '保存中…' : 'Saving…') : (zh ? '保存' : 'Save')}</button></div>
            </div>
          </form>
        </div>
      </div>}
    </div>
  );
};

export default StorageManagementPage;
