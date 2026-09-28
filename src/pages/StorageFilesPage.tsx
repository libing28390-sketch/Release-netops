import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Copy,
  File,
  Folder,
  FolderOpen,
  Loader2,
  RefreshCw,
} from 'lucide-react';
import {
  listStorageObjects,
  listStorageProviders,
  type StorageObjectPath,
  type StorageObjectPage,
  type StorageProvider,
} from '../api/storage';
import { ApiError } from '../api/http';
import { secondaryActionBtnClass } from '../components/shared';
import { copyTextWithFallback } from '../utils/clipboard';

interface StorageFilesPageProps {
  language: string;
  currentUser?: { role?: string; role_profile?: string } | null;
}

interface DirectoryState {
  expanded: boolean;
  loaded: boolean;
  loading: boolean;
  error: string;
  folders: string[];
  items: StorageObjectPath[];
  nextToken: string | null;
}

const emptyDirectory = (expanded = false): DirectoryState => ({
  expanded,
  loaded: false,
  loading: false,
  error: '',
  folders: [],
  items: [],
  nextToken: null,
});

const formatObjectSize = (value: number) => {
  if (value < 1024) return `${value} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let size = value / 1024;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[unitIndex]}`;
};

const formatDate = (value: string | null | undefined, zh: boolean) => {
  if (!value) return zh ? '暂无' : '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(zh ? 'zh-CN' : 'en-US');
};

const pageErrorMessage = (error: unknown, zh: boolean) => {
  if (error instanceof ApiError) {
    if (error.status === 401) return zh ? '登录已失效，请重新登录。' : 'Your session has expired. Please sign in again.';
    if (error.status === 403) return zh ? '无权查看对象存储文件，请联系管理员。' : 'You do not have permission to browse object storage.';
    const safeDetail = error.message.replace(/\s*\(Request ID:.*\)$/i, '');
    if (error.status === 503 && /^(S3 listing failed \(|The S3 endpoint|The S3 bucket|Storage credentials|Storage provider could not be listed|The selected storage profile)/.test(safeDetail)) {
      return safeDetail;
    }
    if (error.status >= 500) return zh ? '服务暂时不可用，请稍后重试。' : 'The service is temporarily unavailable. Please try again.';
    return safeDetail || (zh ? '请求失败，请重试。' : 'Request failed. Please try again.');
  }
  return zh ? '请求失败，请重试。' : 'Request failed. Please try again.';
};

const StorageFilesPage: React.FC<StorageFilesPageProps> = ({ language, currentUser }) => {
  const zh = language === 'zh';
  const isAdmin = currentUser?.role === 'Administrator' || currentUser?.role_profile === 'System Administrator';
  const [providers, setProviders] = useState<StorageProvider[]>([]);
  const [providerId, setProviderId] = useState('');
  const [providersLoading, setProvidersLoading] = useState(true);
  const [providerError, setProviderError] = useState('');
  const [directories, setDirectories] = useState<Record<string, DirectoryState>>({});
  const [copyFeedback, setCopyFeedback] = useState('');
  const [copiedPath, setCopiedPath] = useState('');
  const [refreshNonce, setRefreshNonce] = useState(0);
  const requestGeneration = useRef(0);
  const requestControllers = useRef(new Map<string, AbortController>());

  const selectedProvider = useMemo(
    () => providers.find((provider) => provider.id === providerId) ?? null,
    [providers, providerId],
  );

  useEffect(() => {
    if (!isAdmin) {
      setProvidersLoading(false);
      setProviderError(zh ? '无权查看对象存储文件，请联系管理员。' : 'You do not have permission to browse object storage.');
      return undefined;
    }
    const controller = new AbortController();
    setProvidersLoading(true);
    setProviderError('');
    void listStorageProviders(controller.signal).then((response) => {
      const nextProviders = Array.isArray(response.items) ? response.items : [];
      setProviders(nextProviders);
      setProviderId((current) => nextProviders.some((provider) => provider.id === current)
        ? current
        : response.effective_default_id
          || nextProviders.find((provider) => provider.is_default)?.id
          || nextProviders[0]?.id
          || '');
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      setProviderError(pageErrorMessage(error, zh));
    }).finally(() => {
      if (!controller.signal.aborted) setProvidersLoading(false);
    });
    return () => controller.abort();
  }, [isAdmin, zh]);

  const loadDirectoryPage = useCallback(async (
    selectedProviderId: string,
    prefix: string,
    continuationToken: string | null,
    append: boolean,
    generation: number,
  ) => {
    requestControllers.current.get(prefix)?.abort();
    const controller = new AbortController();
    requestControllers.current.set(prefix, controller);
    setDirectories((current) => ({
      ...current,
      [prefix]: { ...(current[prefix] ?? emptyDirectory()), loading: true, error: '' },
    }));
    try {
      const response: StorageObjectPage = await listStorageObjects(selectedProviderId, {
        prefix,
        delimiter: '/',
        continuationToken,
        pageSize: 100,
        signal: controller.signal,
      });
      if (controller.signal.aborted || requestGeneration.current !== generation) return;
      setDirectories((current) => {
        const previous = current[prefix] ?? emptyDirectory(prefix === '');
        const pageFolders = (response.folders ?? []).filter((folder) => folder !== prefix);
        const markerFolders = response.items
          .map((item) => item.object_key)
          .filter((key) => key !== prefix && key.endsWith('/'));
        const folders = [...new Set([...(append ? previous.folders : []), ...pageFolders, ...markerFolders])].sort((a, b) => a.localeCompare(b));
        const pageItems = response.items.filter((item) => !item.object_key.endsWith('/'));
        const itemMap = new Map((append ? previous.items : []).map((item) => [item.object_key, item]));
        for (const item of pageItems) itemMap.set(item.object_key, item);
        return {
          ...current,
          [prefix]: {
            ...previous,
            loaded: true,
            loading: false,
            error: '',
            folders,
            items: [...itemMap.values()].sort((a, b) => a.object_key.localeCompare(b.object_key)),
            nextToken: response.next_continuation_token ?? null,
          },
        };
      });
    } catch (error) {
      if (controller.signal.aborted || requestGeneration.current !== generation) return;
      setDirectories((current) => ({
        ...current,
        [prefix]: {
          ...(current[prefix] ?? emptyDirectory(prefix === '')),
          loading: false,
          error: pageErrorMessage(error, zh),
        },
      }));
    } finally {
      if (requestControllers.current.get(prefix) === controller) requestControllers.current.delete(prefix);
    }
  }, [zh]);

  useEffect(() => {
    requestGeneration.current += 1;
    const generation = requestGeneration.current;
    requestControllers.current.forEach((controller) => controller.abort());
    requestControllers.current.clear();
    setDirectories(providerId ? { '': emptyDirectory(true) } : {});
    if (!providerId || !isAdmin) return undefined;
    void loadDirectoryPage(providerId, '', null, false, generation);
    return () => {
      if (requestGeneration.current === generation) requestGeneration.current += 1;
      requestControllers.current.forEach((controller) => controller.abort());
      requestControllers.current.clear();
    };
  }, [providerId, isAdmin, refreshNonce, loadDirectoryPage]);

  const toggleFolder = (prefix: string) => {
    const current = directories[prefix] ?? emptyDirectory();
    setDirectories((previous) => ({
      ...previous,
      [prefix]: { ...current, expanded: !current.expanded },
    }));
    if (!current.expanded && !current.loaded && !current.loading && providerId) {
      void loadDirectoryPage(providerId, prefix, null, false, requestGeneration.current);
    }
  };

  const loadMore = (prefix: string) => {
    const current = directories[prefix];
    if (!providerId || !current?.nextToken || current.loading) return;
    void loadDirectoryPage(providerId, prefix, current.nextToken, true, requestGeneration.current);
  };

  const handleCopyPath = async (path: string) => {
    const copied = await copyTextWithFallback(path);
    setCopiedPath(copied ? path : '');
    setCopyFeedback(copied
      ? (zh ? '已复制到剪贴板' : 'Copied to clipboard')
      : (zh ? '复制失败，请检查浏览器剪贴板权限' : 'Copy failed; check browser clipboard permissions'));
  };

  const renderDirectory = (prefix: string, depth: number): React.ReactNode => {
    const directory = directories[prefix] ?? emptyDirectory(prefix === '');
    return (
      <div>
        {directory.loading && !directory.loaded && (
          <p className="flex items-center gap-2 px-3 py-3 text-xs text-[var(--muted-text)]">
            <Loader2 size={14} className="animate-spin" />{zh ? '正在读取目录…' : 'Loading folder…'}
          </p>
        )}
        {directory.error && (
          <div className="my-2 flex items-start justify-between gap-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">
            <span className="flex items-start gap-2"><AlertCircle size={14} className="mt-0.5 shrink-0" />{directory.error}</span>
            <button type="button" className="shrink-0 font-semibold underline" onClick={() => void loadDirectoryPage(providerId, prefix, null, false, requestGeneration.current)}>
              {zh ? '重试' : 'Retry'}
            </button>
          </div>
        )}

        {directory.folders.map((folderPrefix) => {
          const child = directories[folderPrefix] ?? emptyDirectory();
          const folderName = folderPrefix.slice(prefix.length).replace(/\/$/, '') || folderPrefix;
          const folderUri = `s3://${selectedProvider?.bucket ?? ''}/${folderPrefix}`;
          return (
            <div key={folderPrefix}>
              <div className="group flex min-w-0 items-center gap-1 rounded-md pr-2 hover:bg-[var(--ui-surface-muted)]" style={{ paddingLeft: `${12 + depth * 22}px` }}>
                <button type="button" className="flex min-w-0 flex-1 items-center gap-2 py-2 text-left text-sm text-[var(--ui-fg)]" onClick={() => toggleFolder(folderPrefix)} aria-expanded={child.expanded}>
                  {child.expanded ? <ChevronDown size={15} className="shrink-0 text-[var(--muted-text)]" /> : <ChevronRight size={15} className="shrink-0 text-[var(--muted-text)]" />}
                  {child.expanded ? <FolderOpen size={16} className="shrink-0 text-amber-600" /> : <Folder size={16} className="shrink-0 text-amber-600" />}
                  <span className="truncate font-medium">{folderName}</span>
                  <span className="hidden truncate font-mono text-[10px] text-[var(--muted-text)] md:inline">{folderPrefix}</span>
                </button>
                <button type="button" className="rounded p-1.5 text-[var(--muted-text)] opacity-70 transition hover:bg-white hover:text-[var(--ui-accent)] sm:opacity-0 sm:group-hover:opacity-100" onClick={() => void handleCopyPath(folderUri)} title={zh ? '复制目录 S3 URI' : 'Copy folder S3 URI'} aria-label={`${zh ? '复制目录路径' : 'Copy folder path'} ${folderUri}`}>
                  {copiedPath === folderUri ? <CheckCircle2 size={14} /> : <Copy size={14} />}
                </button>
              </div>
              {child.expanded && (
                <div className="ml-4 border-l border-[var(--ui-border)]" style={{ marginLeft: `${20 + depth * 22}px` }}>
                  {renderDirectory(folderPrefix, depth + 1)}
                </div>
              )}
            </div>
          );
        })}

        {directory.items.map((object) => {
          const fileName = object.object_key.slice(prefix.length) || object.object_key;
          return (
            <div key={object.object_key} className="group flex min-w-0 items-center gap-2 rounded-md py-2 pr-2 hover:bg-[var(--ui-surface-muted)]" style={{ paddingLeft: `${36 + depth * 22}px` }}>
              <File size={15} className="shrink-0 text-sky-700" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-[var(--ui-fg)]" title={object.object_key}>{fileName}</p>
                <p className="truncate font-mono text-[10px] text-[var(--muted-text)]" title={object.s3_uri}>{object.s3_uri}</p>
              </div>
              <span className="hidden shrink-0 text-xs text-[var(--muted-text)] sm:inline">{formatObjectSize(object.size)}</span>
              <span className="hidden w-36 shrink-0 truncate text-right text-xs text-[var(--muted-text)] lg:inline" title={object.last_modified ?? ''}>{formatDate(object.last_modified, zh)}</span>
              <button type="button" className="rounded p-1.5 text-[var(--muted-text)] opacity-70 transition hover:bg-white hover:text-[var(--ui-accent)] sm:opacity-0 sm:group-hover:opacity-100" onClick={() => void handleCopyPath(object.s3_uri)} title={zh ? '复制文件 S3 URI' : 'Copy file S3 URI'} aria-label={`${zh ? '复制文件路径' : 'Copy file path'} ${object.s3_uri}`}>
                {copiedPath === object.s3_uri ? <CheckCircle2 size={14} /> : <Copy size={14} />}
              </button>
            </div>
          );
        })}

        {directory.loaded && !directory.loading && !directory.nextToken && directory.folders.length === 0 && directory.items.length === 0 && !directory.error && (
          <p className="px-3 py-3 text-xs text-[var(--muted-text)]">{zh ? '此目录为空。' : 'This folder is empty.'}</p>
        )}
        {directory.nextToken && (
          <button type="button" className="my-2 inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-semibold text-[var(--ui-accent)] hover:bg-[var(--ui-surface-muted)] disabled:opacity-50" style={{ marginLeft: `${12 + depth * 22}px` }} onClick={() => loadMore(prefix)} disabled={directory.loading}>
            {directory.loading && <Loader2 size={13} className="animate-spin" />}{zh ? '加载更多' : 'Load more'}
          </button>
        )}
      </div>
    );
  };

  const rootDirectory = directories[''];
  const bucket = selectedProvider?.bucket ?? '';

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <div className="min-h-0 flex-1 overflow-auto bg-[var(--app-bg)] px-4 py-4 sm:px-6 sm:py-5">
        <section className="overflow-hidden rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[var(--ui-border)] px-5 py-4 sm:px-6">
            <div>
              <h1 className="text-sm font-semibold text-[var(--heading-text)]">{zh ? '文件浏览' : 'File browser'}</h1>
              <p className="mt-1 text-xs text-[var(--muted-text)]">{zh ? '按目录树查看对象，并复制完整 S3 URI。路径需要配合 Endpoint 和有权限的 S3 客户端使用。' : 'Browse objects by folder and copy full S3 URIs. Paths require the endpoint and an authorized S3 client.'}</p>
            </div>
            <button type="button" className="rounded-md p-2 text-[var(--muted-text)] transition hover:bg-[var(--ui-surface-muted)] hover:text-[var(--ui-fg)] disabled:opacity-50" onClick={() => setRefreshNonce((value) => value + 1)} disabled={!providerId || providersLoading} title={zh ? '刷新文件列表' : 'Refresh object list'} aria-label={zh ? '刷新文件列表' : 'Refresh object list'}>
              <RefreshCw size={15} className={rootDirectory?.loading ? 'animate-spin' : ''} />
            </button>
          </div>

          <div className="space-y-4 p-5 sm:p-6">
            <div className="grid gap-3 lg:grid-cols-[minmax(240px,1fr)_minmax(260px,2fr)]">
              <label className="block text-xs font-semibold text-[var(--muted-text)]" htmlFor="storage-file-provider">
                {zh ? '存储配置 / Bucket' : 'Storage profile / Bucket'}
                <select id="storage-file-provider" className="mt-1.5 w-full rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 py-2 text-sm font-normal text-[var(--ui-fg)] outline-none focus:border-[var(--ui-accent)] focus:ring-2 focus:ring-[var(--ui-accent)]/15" value={providerId} onChange={(event) => setProviderId(event.target.value)} disabled={providersLoading || providers.length === 0}>
                  {!providers.length && <option value="">{providersLoading ? (zh ? '正在加载配置…' : 'Loading profiles…') : (zh ? '没有可用的 S3 配置' : 'No S3 profiles available')}</option>}
                  {providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.name} — {provider.bucket}</option>)}
                </select>
              </label>
              {selectedProvider && (
                <div className="grid gap-2 rounded-md border border-[var(--ui-border)] bg-[var(--ui-surface-muted)] px-3 py-2.5 text-xs sm:grid-cols-2">
                  <div className="min-w-0"><span className="text-[var(--muted-text)]">Endpoint: </span><span className="break-all font-mono text-[var(--ui-fg)]">{selectedProvider.endpoint_url || '—'}</span></div>
                  <div className="min-w-0"><span className="text-[var(--muted-text)]">Bucket: </span><span className="break-all font-mono text-[var(--ui-fg)]">{selectedProvider.bucket || '—'}</span></div>
                </div>
              )}
            </div>

            {providerError && <div className="flex items-start gap-2 rounded-md border border-rose-200 bg-rose-50 px-3 py-2.5 text-sm text-rose-800"><AlertCircle size={16} className="mt-0.5 shrink-0" /><span>{providerError}</span></div>}
            {!providerError && !providersLoading && providers.length === 0 && <p className="rounded-md border border-dashed border-[var(--ui-border)] px-4 py-8 text-center text-sm text-[var(--muted-text)]">{zh ? '请先在“存储配置”中添加 S3 配置。' : 'Add an S3 profile in Storage settings first.'}</p>}

            {copyFeedback && <p className={`text-xs ${copiedPath ? 'text-emerald-700' : 'text-rose-700'}`} aria-live="polite">{copyFeedback}</p>}

            {providerId && !providerError && (
              <div className="overflow-hidden rounded-md border border-[var(--ui-border)]">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--ui-border)] bg-[var(--ui-surface-muted)] px-3 py-2 text-xs">
                  <span className="font-mono font-semibold text-[var(--ui-fg)]">{`s3://${bucket || selectedProvider?.bucket || ''}/`}</span>
                  <span className="text-[var(--muted-text)]">{zh ? '目录树' : 'Folder tree'}</span>
                </div>
                {rootDirectory?.error ? (
                  <div className="flex items-start gap-2 px-4 py-8 text-sm text-rose-700"><AlertCircle size={16} className="mt-0.5 shrink-0" /><span>{rootDirectory.error}</span></div>
                ) : rootDirectory?.loading && !rootDirectory.loaded ? (
                  <div className="flex items-center justify-center gap-2 px-4 py-12 text-sm text-[var(--muted-text)]"><Loader2 size={16} className="animate-spin" />{zh ? '正在读取 Bucket 目录…' : 'Loading bucket folders…'}</div>
                ) : rootDirectory?.loaded && !rootDirectory.nextToken && rootDirectory.folders.length === 0 && rootDirectory.items.length === 0 ? (
                  <div className="px-4 py-12 text-center text-sm text-[var(--muted-text)]">{zh ? '此 Bucket 中没有对象。' : 'This bucket has no objects.'}</div>
                ) : (
                  <div className="max-h-[65vh] overflow-auto p-2" role="tree" aria-label={zh ? 'S3 文件目录树' : 'S3 object folder tree'}>
                    {renderDirectory('', 0)}
                  </div>
                )}
              </div>
            )}

            <p className="text-[11px] text-[var(--muted-text)]">{zh ? '此处只显示对象路径和元数据，不提供免认证下载链接；直接访问仍需 S3 客户端凭据。' : 'Only object paths and metadata are shown. No anonymous download links are generated; S3 credentials are still required for direct access.'}</p>
          </div>
        </section>
      </div>
    </div>
  );
};

export default StorageFilesPage;
