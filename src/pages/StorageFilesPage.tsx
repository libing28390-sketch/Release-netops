import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Copy,
  Download,
  Eye,
  File,
  FileCode2,
  Folder,
  FolderOpen,
  Loader2,
  RefreshCw,
  X,
} from 'lucide-react';
import {
  getStorageObjectContent,
  listStorageObjects,
  listStorageProviders,
  type StorageObjectPath,
  type StorageObjectPage,
  type StorageProvider,
} from '../api/storage';
import { ApiError } from '../api/http';
import { primaryActionBtnClass, secondaryActionBtnClass } from '../components/shared';
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

interface PreviewState {
  objectKey: string;
  content: string;
  loading: boolean;
  error: string;
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

const isConfigObject = (objectKey: string) => /\.cfg(?:\.(?:gz|enc))?$/i.test(objectKey);

const configFileName = (objectKey: string) => {
  const rawName = objectKey.split('/').pop() || 'configuration.cfg';
  const withoutWrapper = rawName.replace(/\.(?:gz|enc)$/i, '');
  return withoutWrapper.toLowerCase().endsWith('.cfg') ? withoutWrapper : `${withoutWrapper}.cfg`;
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
  const [selectedPrefix, setSelectedPrefix] = useState('');
  const [selectedObjectKey, setSelectedObjectKey] = useState('');
  const [copyFeedback, setCopyFeedback] = useState('');
  const [copiedPath, setCopiedPath] = useState('');
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [downloadingKey, setDownloadingKey] = useState('');
  const requestGeneration = useRef(0);
  const requestControllers = useRef(new Map<string, AbortController>());
  const previewController = useRef<AbortController | null>(null);

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
    previewController.current?.abort();
    previewController.current = null;
    setPreview(null);
    setSelectedPrefix('');
    setSelectedObjectKey('');
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

  const openFolder = (prefix: string) => {
    setSelectedPrefix(prefix);
    setSelectedObjectKey('');
    previewController.current?.abort();
    previewController.current = null;
    setPreview(null);
    const current = directories[prefix] ?? emptyDirectory();
    if (!current.expanded) {
      setDirectories((previous) => ({
        ...previous,
        [prefix]: { ...(previous[prefix] ?? emptyDirectory()), expanded: true },
      }));
    }
    if (!current.loaded && !current.loading && providerId) {
      void loadDirectoryPage(providerId, prefix, null, false, requestGeneration.current);
    }
  };

  const loadMore = (prefix: string) => {
    const current = directories[prefix];
    if (!providerId || !current?.nextToken || current.loading) return;
    void loadDirectoryPage(providerId, prefix, current.nextToken, true, requestGeneration.current);
  };

  useEffect(() => () => {
    previewController.current?.abort();
  }, []);

  const closePreview = () => {
    previewController.current?.abort();
    previewController.current = null;
    setPreview(null);
  };

  const handlePreview = async (object: StorageObjectPath) => {
    if (!providerId || !isAdmin || !isConfigObject(object.object_key)) return;
    setSelectedObjectKey(object.object_key);
    previewController.current?.abort();
    const controller = new AbortController();
    previewController.current = controller;
    setPreview({ objectKey: object.object_key, content: '', loading: true, error: '' });
    try {
      const content = await getStorageObjectContent(providerId, object.object_key, { signal: controller.signal });
      if (controller.signal.aborted) return;
      setPreview({ objectKey: object.object_key, content, loading: false, error: '' });
    } catch (error) {
      if (controller.signal.aborted) return;
      setPreview({ objectKey: object.object_key, content: '', loading: false, error: pageErrorMessage(error, zh) });
    } finally {
      if (previewController.current === controller) previewController.current = null;
    }
  };

  const handleDownload = async (object: StorageObjectPath) => {
    if (!providerId || !isAdmin || !isConfigObject(object.object_key) || downloadingKey) return;
    setSelectedObjectKey(object.object_key);
    setDownloadingKey(object.object_key);
    try {
      const content = await getStorageObjectContent(providerId, object.object_key, { download: true });
      const url = URL.createObjectURL(new Blob([content], { type: 'text/plain;charset=utf-8' }));
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = configFileName(object.object_key);
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (error) {
      setCopyFeedback(pageErrorMessage(error, zh));
      setCopiedPath('');
    } finally {
      setDownloadingKey('');
    }
  };

  const handleCopyPath = async (path: string) => {
    const copied = await copyTextWithFallback(path);
    setCopiedPath(copied ? path : '');
    setCopyFeedback(copied
      ? (zh ? '已复制到剪贴板' : 'Copied to clipboard')
      : (zh ? '复制失败，请检查浏览器剪贴板权限' : 'Copy failed; check browser clipboard permissions'));
  };

  const renderFolderTree = (prefix: string): React.ReactNode => {
    const directory = directories[prefix] ?? emptyDirectory(prefix === '');
    return (
      <div>
        {directory.error && (
          <div className="my-1 flex items-start justify-between gap-2 rounded-md border border-rose-200 bg-rose-50 px-2 py-2 text-[11px] text-rose-800">
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
          const isSelected = selectedPrefix === folderPrefix;
          return (
            <div key={folderPrefix} className="min-w-0">
              <div className={`group flex min-w-0 items-center gap-0.5 rounded-md pr-1 ${isSelected ? 'bg-[var(--ui-accent)]/10 text-[var(--ui-accent)]' : 'text-[var(--ui-fg)] hover:bg-[var(--ui-surface-muted)]'}`}>
                <button type="button" className="grid h-7 w-6 shrink-0 place-items-center rounded text-[var(--muted-text)] hover:text-[var(--ui-fg)]" onClick={() => toggleFolder(folderPrefix)} aria-label={`${child.expanded ? (zh ? '折叠' : 'Collapse') : (zh ? '展开' : 'Expand')} ${folderName}`} aria-expanded={child.expanded}>
                  {child.expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </button>
                <button type="button" className="flex min-w-0 flex-1 items-center gap-2 py-1.5 text-left text-xs" onClick={() => openFolder(folderPrefix)} title={folderPrefix}>
                  {child.expanded ? <FolderOpen size={15} className="shrink-0 text-amber-600" /> : <Folder size={15} className="shrink-0 text-amber-600" />}
                  <span className="truncate font-medium">{folderName}</span>
                </button>
                <button type="button" className="rounded p-1 text-[var(--muted-text)] opacity-0 transition hover:bg-white hover:text-[var(--ui-accent)] group-hover:opacity-100 focus:opacity-100" onClick={() => void handleCopyPath(folderUri)} title={zh ? '复制目录 S3 URI' : 'Copy folder S3 URI'} aria-label={`${zh ? '复制目录路径' : 'Copy folder path'} ${folderUri}`}>
                  {copiedPath === folderUri ? <CheckCircle2 size={14} /> : <Copy size={14} />}
                </button>
              </div>
              {child.loading && !child.loaded && <p className="flex items-center gap-1.5 px-7 py-1 text-[10px] text-[var(--muted-text)]"><Loader2 size={12} className="animate-spin" />{zh ? '读取中…' : 'Loading…'}</p>}
              {child.expanded && (
                <div className="ml-3 border-l border-[var(--ui-border)] pl-2">
                  {renderFolderTree(folderPrefix)}
                </div>
              )}
            </div>
          );
        })}
      </div>
    );
  };

  const rootDirectory = directories[''];
  const bucket = selectedProvider?.bucket ?? '';
  const currentDirectory = directories[selectedPrefix] ?? emptyDirectory(selectedPrefix === '');
  const selectedObject = useMemo(
    () => selectedObjectKey
      ? Object.values(directories).flatMap((directory) => directory.items).find((object) => object.object_key === selectedObjectKey) ?? null
      : null,
    [directories, selectedObjectKey],
  );
  const breadcrumbParts = useMemo(() => {
    const parts = selectedPrefix.split('/').filter(Boolean);
    return parts.map((part, index) => ({
      label: part,
      prefix: `${parts.slice(0, index + 1).join('/')}/`,
    }));
  }, [selectedPrefix]);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <div className="min-h-0 flex-1 overflow-auto bg-[var(--app-bg)] px-4 py-4 sm:px-6 sm:py-5">
        <section className="overflow-hidden rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[var(--ui-border)] px-5 py-4 sm:px-6">
            <div>
              <h1 className="text-sm font-semibold text-[var(--heading-text)]">{zh ? '文件浏览' : 'File browser'}</h1>
              <p className="mt-1 text-xs text-[var(--muted-text)]">{zh ? '使用双栏目录树浏览快照；选中文件后可直接在线查看或下载 CFG。' : 'Browse snapshots in a split folder explorer, then preview or download CFG files.'}</p>
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
              <div className="grid min-h-[560px] overflow-hidden rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] lg:grid-cols-[250px_minmax(0,1fr)]">
                <aside className="min-w-0 border-b border-[var(--ui-border)] bg-[var(--ui-surface-muted)]/50 lg:border-b-0 lg:border-r" aria-label={zh ? '资源管理器' : 'Explorer'}>
                  <div className="flex h-10 items-center justify-between border-b border-[var(--ui-border)] px-3">
                    <span className="text-[10px] font-bold tracking-[0.12em] text-[var(--muted-text)]">{zh ? '资源管理器' : 'EXPLORER'}</span>
                    <span className="max-w-[145px] truncate font-mono text-[10px] text-[var(--muted-text)]" title={bucket}>{bucket}</span>
                  </div>
                  <div className="max-h-[30vh] overflow-auto p-2 lg:max-h-[68vh]" role="tree" aria-label={zh ? 'S3 文件目录树' : 'S3 object folder tree'}>
                    <div className={`group flex items-center gap-1 rounded-md pr-1 ${selectedPrefix === '' ? 'bg-[var(--ui-accent)]/10 text-[var(--ui-accent)]' : 'text-[var(--ui-fg)] hover:bg-[var(--ui-surface-muted)]'}`}>
                      <button type="button" className="grid h-7 w-6 shrink-0 place-items-center rounded text-[var(--muted-text)] hover:text-[var(--ui-fg)]" onClick={() => toggleFolder('')} aria-label={`${rootDirectory?.expanded ? (zh ? '折叠' : 'Collapse') : (zh ? '展开' : 'Expand')} ${bucket}`} aria-expanded={rootDirectory?.expanded ?? false}>
                        {rootDirectory?.expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                      </button>
                      <button type="button" className="flex min-w-0 flex-1 items-center gap-2 py-1.5 text-left text-xs" onClick={() => openFolder('')} title={`s3://${bucket}/`}>
                        {rootDirectory?.expanded ? <FolderOpen size={15} className="shrink-0 text-amber-600" /> : <Folder size={15} className="shrink-0 text-amber-600" />}
                        <span className="truncate font-semibold">{bucket || (zh ? 'Bucket 根目录' : 'Bucket root')}</span>
                      </button>
                    </div>
                    {rootDirectory?.loading && !rootDirectory.loaded && <p className="flex items-center gap-1.5 px-7 py-1 text-[10px] text-[var(--muted-text)]"><Loader2 size={12} className="animate-spin" />{zh ? '读取中…' : 'Loading…'}</p>}
                    {rootDirectory?.error && <div className="my-1 flex items-start justify-between gap-2 rounded-md border border-rose-200 bg-rose-50 px-2 py-2 text-[11px] text-rose-800"><span>{rootDirectory.error}</span><button type="button" className="shrink-0 font-semibold underline" onClick={() => void loadDirectoryPage(providerId, '', null, false, requestGeneration.current)}>{zh ? '重试' : 'Retry'}</button></div>}
                    {rootDirectory?.expanded && <div className="ml-3 border-l border-[var(--ui-border)] pl-2">{renderFolderTree('')}</div>}
                  </div>
                  <div className="border-t border-[var(--ui-border)] px-3 py-2 text-[10px] text-[var(--muted-text)]">
                    {zh ? '目录路径' : 'PATH'} <span className="mt-1 block break-all font-mono text-[var(--ui-fg)]">{selectedPrefix || '/'}</span>
                  </div>
                </aside>

                <main className="flex min-w-0 flex-col">
                  <div className="flex min-h-10 flex-wrap items-center justify-between gap-2 border-b border-[var(--ui-border)] px-3 py-2">
                    <nav className="flex min-w-0 flex-wrap items-center gap-1 text-xs" aria-label={zh ? '目录面包屑' : 'Folder breadcrumbs'}>
                      <button type="button" className="rounded px-1.5 py-1 font-medium text-[var(--ui-accent)] hover:bg-[var(--ui-surface-muted)]" onClick={() => openFolder('')}>{bucket || 'Bucket'}</button>
                      {breadcrumbParts.map((part) => (
                        <React.Fragment key={part.prefix}>
                          <ChevronRight size={13} className="shrink-0 text-[var(--muted-text)]" />
                          <button type="button" className={`max-w-40 truncate rounded px-1.5 py-1 ${part.prefix === selectedPrefix ? 'font-semibold text-[var(--ui-fg)]' : 'text-[var(--muted-text)] hover:bg-[var(--ui-surface-muted)] hover:text-[var(--ui-fg)]'}`} onClick={() => openFolder(part.prefix)} title={part.prefix}>{part.label}</button>
                        </React.Fragment>
                      ))}
                    </nav>
                    <span className="shrink-0 text-[10px] text-[var(--muted-text)]">{currentDirectory.items.length}{currentDirectory.nextToken ? '+' : ''} {zh ? '个文件' : 'files'}</span>
                  </div>

                  <div className="max-h-[68vh] min-h-[420px] flex-1 overflow-auto">
                    {currentDirectory.error ? (
                      <div className="flex items-start gap-2 px-4 py-8 text-sm text-rose-700"><AlertCircle size={16} className="mt-0.5 shrink-0" /><span>{currentDirectory.error}</span><button type="button" className="ml-auto shrink-0 font-semibold underline" onClick={() => void loadDirectoryPage(providerId, selectedPrefix, null, false, requestGeneration.current)}>{zh ? '重试' : 'Retry'}</button></div>
                    ) : currentDirectory.loading && !currentDirectory.loaded ? (
                      <div className="flex items-center justify-center gap-2 px-4 py-12 text-sm text-[var(--muted-text)]"><Loader2 size={16} className="animate-spin" />{zh ? '正在读取目录…' : 'Loading folder…'}</div>
                    ) : !currentDirectory.loading && currentDirectory.loaded && currentDirectory.folders.length === 0 && currentDirectory.items.length === 0 ? (
                      <div className="px-4 py-14 text-center text-sm text-[var(--muted-text)]">{zh ? (selectedPrefix ? '此目录为空。' : '此 Bucket 中没有对象。') : (selectedPrefix ? 'This folder is empty.' : 'This bucket has no objects.')}</div>
                    ) : (
                      <>
                        <div className="sticky top-0 z-[1] grid grid-cols-[minmax(0,1fr)_90px_170px] gap-3 border-b border-[var(--ui-border)] bg-[var(--ui-surface-muted)]/80 px-4 py-2 text-[10px] font-semibold uppercase tracking-wide text-[var(--muted-text)] backdrop-blur">
                          <span>{zh ? '名称' : 'Name'}</span><span className="text-right">{zh ? '大小' : 'Size'}</span><span className="text-right">{zh ? '修改时间' : 'Modified'}</span>
                        </div>
                        <div className="divide-y divide-[var(--ui-border)]/70">
                          {currentDirectory.folders.map((folderPrefix) => {
                            const folderName = folderPrefix.slice(selectedPrefix.length).replace(/\/$/, '') || folderPrefix;
                            return (
                              <button key={folderPrefix} type="button" className="grid w-full grid-cols-[minmax(0,1fr)_90px_170px] items-center gap-3 px-4 py-2.5 text-left text-xs text-[var(--ui-fg)] transition hover:bg-[var(--ui-surface-muted)]" onClick={() => openFolder(folderPrefix)} title={folderPrefix}>
                                <span className="flex min-w-0 items-center gap-2"><Folder size={16} className="shrink-0 text-amber-600" /><span className="truncate font-medium">{folderName}</span></span>
                                <span className="text-right text-[var(--muted-text)]">—</span><span className="text-right text-[var(--muted-text)]">{zh ? '目录' : 'Folder'}</span>
                              </button>
                            );
                          })}
                          {currentDirectory.items.map((object) => {
                            const fileName = object.object_key.slice(selectedPrefix.length) || object.object_key;
                            const isSelected = selectedObjectKey === object.object_key;
                            const configObject = isConfigObject(object.object_key);
                            return (
                              <button key={object.object_key} type="button" className={`grid w-full grid-cols-[minmax(0,1fr)_90px_170px] items-center gap-3 px-4 py-2.5 text-left text-xs transition ${isSelected ? 'bg-[var(--ui-accent)]/10 text-[var(--ui-fg)]' : 'text-[var(--ui-fg)] hover:bg-[var(--ui-surface-muted)]'}`} onClick={() => { setSelectedObjectKey(object.object_key); closePreview(); }} title={object.object_key}>
                                <span className="flex min-w-0 items-center gap-2"><span className={`grid h-7 w-7 shrink-0 place-items-center rounded ${configObject ? 'bg-sky-50 text-sky-700' : 'bg-[var(--ui-surface-muted)] text-[var(--muted-text)]'}`}>{configObject ? <FileCode2 size={15} /> : <File size={15} />}</span><span className="min-w-0"><span className="block truncate font-medium">{fileName}</span><span className="mt-0.5 block truncate font-mono text-[10px] text-[var(--muted-text)]">{object.s3_uri}</span></span></span>
                                <span className="text-right text-[var(--muted-text)]">{formatObjectSize(object.size)}</span><span className="truncate text-right text-[var(--muted-text)]" title={object.last_modified ?? ''}>{formatDate(object.last_modified, zh)}</span>
                              </button>
                            );
                          })}
                        </div>
                        {currentDirectory.loading && currentDirectory.loaded && <p className="flex items-center justify-center gap-2 px-4 py-3 text-xs text-[var(--muted-text)]"><Loader2 size={13} className="animate-spin" />{zh ? '正在加载更多…' : 'Loading more…'}</p>}
                        {currentDirectory.nextToken && <div className="border-t border-[var(--ui-border)] px-4 py-3 text-center"><button type="button" className="inline-flex items-center gap-1 rounded px-3 py-1.5 text-xs font-semibold text-[var(--ui-accent)] hover:bg-[var(--ui-surface-muted)] disabled:opacity-50" onClick={() => loadMore(selectedPrefix)} disabled={currentDirectory.loading}>{zh ? '加载更多文件' : 'Load more files'}</button></div>}
                      </>
                    )}
                  </div>

                  {selectedObject && (
                    <section className="border-t border-[var(--ui-border)] bg-[var(--ui-surface-muted)]/40 px-4 py-3" aria-label={zh ? '文件操作' : 'File actions'}>
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div className="flex min-w-0 items-center gap-2">
                          {isConfigObject(selectedObject.object_key) ? <FileCode2 size={17} className="shrink-0 text-sky-700" /> : <File size={17} className="shrink-0 text-[var(--muted-text)]" />}
                          <div className="min-w-0"><p className="truncate text-xs font-semibold text-[var(--ui-fg)]">{selectedObject.object_key.split('/').pop()}</p><p className="truncate font-mono text-[10px] text-[var(--muted-text)]" title={selectedObject.s3_uri}>{selectedObject.s3_uri}</p></div>
                        </div>
                        <div className="flex shrink-0 items-center gap-2">
                          <button type="button" className={secondaryActionBtnClass} onClick={() => void handleCopyPath(selectedObject.s3_uri)}>{copiedPath === selectedObject.s3_uri ? <CheckCircle2 size={14} /> : <Copy size={14} />}{zh ? '复制路径' : 'Copy path'}</button>
                          {isConfigObject(selectedObject.object_key) ? (
                            <>
                              <button type="button" className={secondaryActionBtnClass} onClick={() => void handlePreview(selectedObject)} disabled={!isAdmin || (preview?.loading === true && preview.objectKey === selectedObject.object_key)}>{preview?.loading && preview.objectKey === selectedObject.object_key ? <Loader2 size={14} className="animate-spin" /> : <Eye size={14} />}{zh ? '在线查看' : 'Preview'}</button>
                              <button type="button" className={primaryActionBtnClass} onClick={() => void handleDownload(selectedObject)} disabled={!isAdmin || Boolean(downloadingKey)}>{downloadingKey === selectedObject.object_key ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}{zh ? '下载 CFG' : 'Download CFG'}</button>
                            </>
                          ) : <span className="text-[10px] text-[var(--muted-text)]">{zh ? '此文件类型暂不支持在线查看或下载' : 'Preview and download are available for CFG snapshots'}</span>}
                        </div>
                      </div>
                    </section>
                  )}

                  {preview && (
                    <section className="border-t border-[var(--ui-border)] bg-[var(--ui-surface)]" aria-label={zh ? '配置预览' : 'Configuration preview'}>
                      <div className="flex items-center justify-between gap-3 border-b border-[var(--ui-border)] px-4 py-2">
                        <div className="min-w-0"><p className="text-xs font-semibold text-[var(--ui-fg)]">{zh ? '配置预览' : 'Configuration preview'}</p><p className="truncate font-mono text-[10px] text-[var(--muted-text)]" title={preview.objectKey}>{preview.objectKey}</p></div>
                        <button type="button" className="rounded p-1.5 text-[var(--muted-text)] hover:bg-[var(--ui-surface-muted)] hover:text-[var(--ui-fg)]" onClick={closePreview} title={zh ? '关闭预览' : 'Close preview'} aria-label={zh ? '关闭预览' : 'Close preview'}><X size={15} /></button>
                      </div>
                      {preview.loading ? <div className="flex items-center gap-2 px-4 py-8 text-sm text-[var(--muted-text)]"><Loader2 size={16} className="animate-spin" />{zh ? '正在加载配置…' : 'Loading configuration…'}</div>
                        : preview.error ? <div className="flex items-start gap-2 px-4 py-8 text-sm text-rose-700"><AlertCircle size={16} className="mt-0.5 shrink-0" /><span>{preview.error}</span></div>
                          : <pre className="max-h-[48vh] overflow-auto whitespace-pre-wrap break-words px-4 py-3 font-mono text-xs leading-5 text-[var(--ui-fg)]">{preview.content || (zh ? '配置内容为空。' : 'The configuration is empty.')}</pre>}
                    </section>
                  )}
                </main>
              </div>
            )}

            <p className="text-[11px] text-[var(--muted-text)]">{zh ? '配置快照支持在线查看和下载为 .cfg；目录按存储中的日期、厂商等路径展开。操作需要管理员权限。' : 'Configuration snapshots can be previewed and downloaded as .cfg files; folders follow the date and vendor paths stored in the bucket. Administrator access is required.'}</p>
          </div>
        </section>
      </div>
    </div>
  );
};

export default StorageFilesPage;
