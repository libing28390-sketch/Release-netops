import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, Check, LoaderCircle, Search, X } from 'lucide-react';
import {
  getAIProviderModelCatalog,
  importAIProviderModels,
  type AIProvider,
  type AIProviderCatalogModel,
  type AIProviderModelImportItem,
} from '../../../api/ai';
import { useEscapeClose } from '../../../hooks/useEscapeClose';
import { useFocusTrap } from '../../../hooks/useFocusTrap';

type ImportableModelType = AIProviderModelImportItem['model_type'];
const MAX_IMPORT_ITEMS = 500;

interface ModelCatalogImportDialogProps {
  providers: AIProvider[];
  language: 'zh' | 'en';
  onClose: () => void;
  onImported: (result: { created: number; skipped: number }) => void;
}

const controlClass = 'min-h-10 w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-fg outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-accent/20 disabled:cursor-not-allowed disabled:opacity-60';
const smallButtonClass = 'inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg border border-line px-3 text-xs font-semibold text-fg-muted transition-colors hover:bg-surface-muted hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 disabled:cursor-not-allowed disabled:opacity-50';

const knownType = (model: AIProviderCatalogModel): ImportableModelType | null => {
  if (model.model_type === 'chat' || model.model_type === 'embedding' || model.model_type === 'rerank') return model.model_type;
  return null;
};

const errorStatus = (error: unknown): number | undefined => (
  error && typeof error === 'object' && 'status' in error && typeof error.status === 'number'
    ? error.status
    : undefined
);

export const ModelCatalogImportDialog: React.FC<ModelCatalogImportDialogProps> = ({
  providers,
  language,
  onClose,
  onImported,
}) => {
  const zh = language === 'zh';
  const [providerId, setProviderId] = useState(providers[0]?.id || '');
  const [mode, setMode] = useState<'catalog' | 'paste'>('catalog');
  const [catalog, setCatalog] = useState<AIProviderCatalogModel[]>([]);
  const [catalogSource, setCatalogSource] = useState<'account' | 'public' | null>(null);
  const [catalogLoaded, setCatalogLoaded] = useState(false);
  const [loadingCatalog, setLoadingCatalog] = useState(false);
  const [importing, setImporting] = useState(false);
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [selectionLimitNotice, setSelectionLimitNotice] = useState(false);
  const [typeOverrides, setTypeOverrides] = useState<Record<string, ImportableModelType>>({});
  const [bulkType, setBulkType] = useState<ImportableModelType>('chat');
  const [pastedIdsText, setPastedIdsText] = useState('');
  const [pastedType, setPastedType] = useState<ImportableModelType>('chat');
  const [requestError, setRequestError] = useState<{ kind: 'permission' | 'auth' | 'error'; action: 'catalog' | 'import'; message: string } | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const busy = loadingCatalog || importing;

  useEscapeClose(!importing, onClose);
  useFocusTrap(dialogRef, true, '#model-catalog-provider');

  const effectiveProviderId = providerId || providers[0]?.id || '';
  const selectedProvider = providers.find((provider) => provider.id === effectiveProviderId);
  const filteredModels = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    if (!normalizedQuery) return catalog;
    return catalog.filter((model) => (
      model.name.toLocaleLowerCase().includes(normalizedQuery)
      || model.model_code.toLocaleLowerCase().includes(normalizedQuery)
      || model.model_type.toLocaleLowerCase().includes(normalizedQuery)
    ));
  }, [catalog, query]);

  const getType = (model: AIProviderCatalogModel): ImportableModelType | null => knownType(model) || typeOverrides[model.model_code] || null;
  const eligibleFiltered = filteredModels.filter((model) => !model.already_registered && getType(model) !== null);
  const selectedUnknown = catalog.filter((model) => selected.has(model.model_code) && !model.already_registered && model.model_type === 'unknown');
  const catalogImportItems = catalog
    .filter((model) => selected.has(model.model_code) && !model.already_registered)
    .map((model) => {
      const modelType = getType(model);
      return modelType ? { model_code: model.model_code, name: model.name, model_type: modelType } : null;
    })
    .filter((item): item is AIProviderModelImportItem => item !== null);
  const trimmedPastedIds = pastedIdsText.split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
  const uniquePastedIds = Array.from(new Set(trimmedPastedIds));
  const pastedImportItems = uniquePastedIds.map((modelCode) => ({
    model_code: modelCode,
    name: modelCode,
    model_type: pastedType,
  }));
  const importItems = mode === 'catalog' ? catalogImportItems : pastedImportItems;
  const selectedUnclassifiedCount = selectedUnknown.filter((model) => !typeOverrides[model.model_code]).length;

  const resetProviderState = (nextProviderId: string) => {
    setProviderId(nextProviderId);
    setCatalog([]);
    setCatalogSource(null);
    setCatalogLoaded(false);
    setQuery('');
    setSelected(new Set());
    setSelectionLimitNotice(false);
    setTypeOverrides({});
    setPastedIdsText('');
    setPastedType('chat');
    setRequestError(null);
  };

  useEffect(() => {
    if (providers.some((provider) => provider.id === providerId)) return;
    const nextProviderId = providers[0]?.id || '';
    if (nextProviderId === providerId) return;
    setProviderId(nextProviderId);
    setCatalog([]);
    setCatalogSource(null);
    setCatalogLoaded(false);
    setQuery('');
    setSelected(new Set());
    setSelectionLimitNotice(false);
    setTypeOverrides({});
    setPastedIdsText('');
    setPastedType('chat');
    setRequestError(null);
  }, [providers, providerId]);

  const switchMode = (nextMode: 'catalog' | 'paste') => {
    setMode(nextMode);
    setRequestError(null);
  };

  const handleModeTabKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const tabs = Array.from(event.currentTarget.closest('[role="tablist"]')?.querySelectorAll<HTMLButtonElement>('[role="tab"]') || []);
    if (tabs.length < 2) return;
    const currentIndex = tabs.indexOf(event.currentTarget);
    const nextIndex = event.key === 'Home'
      ? 0
      : event.key === 'End'
        ? tabs.length - 1
        : (currentIndex + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    tabs[nextIndex].focus();
    tabs[nextIndex].click();
  };

  const handleFetchCatalog = async () => {
    if (!effectiveProviderId || busy) return;
    setLoadingCatalog(true);
    setRequestError(null);
    try {
      const response = await getAIProviderModelCatalog(effectiveProviderId);
      const responseItems = Array.isArray(response.items) ? response.items : [];
      const items = Array.from(new Map(responseItems.map((item) => [item.model_code, item] as const)).values());
      setCatalog(items);
      setCatalogSource(response.source || 'account');
      setCatalogLoaded(true);
      setTypeOverrides({});
      const defaultSelected = response.source === 'public' ? [] : items
        .filter((model) => !model.already_registered && model.model_type === 'chat')
        .map((model) => model.model_code);
      setSelected(new Set(defaultSelected.slice(0, MAX_IMPORT_ITEMS)));
      setSelectionLimitNotice(defaultSelected.length > MAX_IMPORT_ITEMS);
    } catch (error) {
      const status = errorStatus(error);
      const kind = status === 401 ? 'auth' : status === 403 ? 'permission' : 'error';
      const message = error instanceof Error ? error.message : '';
      setRequestError({ kind, action: 'catalog', message });
    } finally {
      setLoadingCatalog(false);
    }
  };

  const handleImport = async () => {
    if (!effectiveProviderId || importing || loadingCatalog || isAccessDenied || requestError?.action === 'catalog' || importItems.length === 0 || importItems.length > MAX_IMPORT_ITEMS) return;
    setImporting(true);
    setRequestError(null);
    let result: { created: number; skipped: number };
    try {
      result = await importAIProviderModels(effectiveProviderId, importItems);
    } catch (error) {
      const status = errorStatus(error);
      const kind = status === 401 ? 'auth' : status === 403 ? 'permission' : 'error';
      const message = error instanceof Error ? error.message : '';
      setRequestError({ kind, action: 'import', message });
      setImporting(false);
      return;
    }
    setImporting(false);
    onImported({ created: result.created, skipped: result.skipped });
    onClose();
  };

  const toggleSelected = (modelCode: string, checked: boolean) => {
    if (checked && !selected.has(modelCode) && selected.size >= MAX_IMPORT_ITEMS) {
      setSelectionLimitNotice(true);
      return;
    }
    if (!checked) setSelectionLimitNotice(false);
    setSelected((current) => {
      const next = new Set(current);
      if (checked) next.add(modelCode);
      else next.delete(modelCode);
      return next;
    });
  };

  const selectEligibleShown = () => {
    const next = new Set(selected);
    const remaining = Math.max(0, MAX_IMPORT_ITEMS - next.size);
    const candidates = eligibleFiltered.filter((model) => !next.has(model.model_code));
    candidates.slice(0, remaining).forEach((model) => next.add(model.model_code));
    setSelected(next);
    setSelectionLimitNotice(candidates.length > remaining);
  };

  const clearSelection = () => {
    setSelected(new Set());
    setSelectionLimitNotice(false);
  };

  const applyBulkType = () => {
    if (selectedUnknown.length === 0) return;
    setTypeOverrides((current) => {
      const next = { ...current };
      selectedUnknown.forEach((model) => { next[model.model_code] = bulkType; });
      return next;
    });
  };

  const assignRowType = (modelCode: string, value: string) => {
    if (!value) {
      setTypeOverrides((current) => {
        const next = { ...current };
        delete next[modelCode];
        return next;
      });
      return;
    }
    const nextType = value as ImportableModelType;
    setTypeOverrides((current) => ({ ...current, [modelCode]: nextType }));
    setSelected((current) => new Set(current).add(modelCode));
  };

  const permissionCopy = requestError?.kind === 'auth'
    ? (zh ? '登录状态已失效，请重新登录后再试。' : 'Your session has expired. Sign in again and retry.')
    : requestError?.kind === 'permission'
      ? requestError.action === 'catalog'
        ? (zh ? '当前账号没有读取此 Provider 模型目录的权限。' : 'Your account cannot read this provider model catalog.')
        : (zh ? '当前账号没有导入此 Provider 模型的权限。' : 'Your account cannot import models for this provider.')
      : null;

  const isAccessDenied = requestError?.kind === 'permission' || requestError?.kind === 'auth';
  const errorCopy = permissionCopy || requestError?.message || (zh ? '模型操作失败，请稍后重试。' : 'The model request failed. Try again.');
  const importLimitExceeded = importItems.length > MAX_IMPORT_ITEMS;
  const importBlocked = busy
    || !effectiveProviderId
    || (mode === 'catalog' && !catalogLoaded)
    || Boolean(requestError && (requestError.action === 'catalog' || requestError.kind === 'permission' || requestError.kind === 'auth'))
    || importItems.length === 0
    || importLimitExceeded
    || (mode === 'catalog' && selectedUnclassifiedCount > 0);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-3 sm:p-5"
      onMouseDown={(event) => { if (event.target === event.currentTarget && !importing) onClose(); }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="model-catalog-import-title"
        tabIndex={-1}
        className="nx-form-dialog-shell w-full max-w-3xl"
      >
        <header className="nx-form-dialog-header">
          <div>
            <h2 id="model-catalog-import-title">{zh ? '导入 Provider 模型' : 'Import Provider Models'}</h2>
            <p>{zh ? '读取模型目录，或粘贴模型 ID 并确认类型后批量添加。' : 'Fetch a catalog or paste model IDs, confirm the types, then add them in a batch.'}</p>
          </div>
          <button
            type="button"
            aria-label={zh ? '关闭' : 'Close'}
            className="nx-form-dialog-close"
            disabled={importing}
            onClick={onClose}
          >
            <X size={18} aria-hidden="true" />
          </button>
        </header>

        <div className="nx-form-dialog-body space-y-4">
          <div className={`grid grid-cols-1 gap-3 sm:items-end ${mode === 'catalog' ? 'sm:grid-cols-[minmax(0,1fr)_auto]' : ''}`}>
            <div>
              <label htmlFor="model-catalog-provider" className="mb-1.5 block text-[13px] font-medium text-fg">
                {zh ? '供应商 Provider' : 'Provider'}
              </label>
              <select
                id="model-catalog-provider"
                value={effectiveProviderId}
                disabled={busy || providers.length === 0}
                onChange={(event) => resetProviderState(event.target.value)}
                className={controlClass}
              >
                {providers.length === 0 && <option value="">{zh ? '没有可用的 Provider' : 'No providers available'}</option>}
                {providers.map((provider) => (
                  <option key={provider.id} value={provider.id}>{provider.name} ({provider.provider_type})</option>
                ))}
              </select>
            </div>
            {mode === 'catalog' && (
              <button
                type="button"
                className="nx-dialog-action-secondary inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border px-4 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                disabled={!effectiveProviderId || busy || isAccessDenied}
                onClick={() => void handleFetchCatalog()}
              >
                {loadingCatalog ? <LoaderCircle size={16} className="animate-spin" aria-hidden="true" /> : <Search size={16} aria-hidden="true" />}
                {loadingCatalog ? (zh ? '读取中…' : 'Fetching…') : (zh ? '读取模型列表' : 'Fetch models')}
              </button>
            )}
          </div>

          <div role="tablist" aria-label={zh ? '导入方式' : 'Import method'} className="flex border-b border-line">
            <button
              type="button"
              role="tab"
              id="model-catalog-tab"
              aria-controls="model-catalog-panel"
              aria-selected={mode === 'catalog'}
              tabIndex={mode === 'catalog' ? 0 : -1}
              disabled={busy}
              onKeyDown={handleModeTabKeyDown}
              onClick={() => switchMode('catalog')}
              className={`min-h-10 border-b-2 px-3 text-sm font-semibold transition-colors ${mode === 'catalog' ? 'border-accent text-accent' : 'border-transparent text-fg-muted hover:text-fg'}`}
            >
              {zh ? '读取目录' : 'Catalog'}
            </button>
            <button
              type="button"
              role="tab"
              id="model-paste-tab"
              aria-controls="model-paste-panel"
              aria-selected={mode === 'paste'}
              tabIndex={mode === 'paste' ? 0 : -1}
              disabled={busy}
              onKeyDown={handleModeTabKeyDown}
              onClick={() => switchMode('paste')}
              className={`min-h-10 border-b-2 px-3 text-sm font-semibold transition-colors ${mode === 'paste' ? 'border-accent text-accent' : 'border-transparent text-fg-muted hover:text-fg'}`}
            >
              {zh ? '批量粘贴模型 ID' : 'Paste model IDs'}
            </button>
          </div>

          {selectedProvider && !selectedProvider.enabled && (
            <p className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
              {zh ? '此 Provider 当前已停用，导入的模型不会因此启用 Provider。' : 'This provider is disabled. Importing models will not enable it.'}
            </p>
          )}

          {requestError && (
            <div role="alert" className={`flex items-start gap-2 rounded-lg border px-3 py-2.5 text-sm ${isAccessDenied ? 'border-amber-500/30 bg-amber-500/10 text-amber-800 dark:text-amber-200' : 'border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300'}`}>
              <AlertCircle size={17} className="mt-0.5 shrink-0" aria-hidden="true" />
              <div>
                <p className="font-semibold">{errorCopy}</p>
                {requestError.message && permissionCopy && <p className="mt-1 break-words text-xs opacity-80">{requestError.message}</p>}
              </div>
            </div>
          )}

          {mode === 'catalog' && !catalogLoaded && !loadingCatalog && !requestError && (
            <div className="flex min-h-44 flex-col items-center justify-center rounded-xl border border-dashed border-line px-5 text-center">
              {providers.length === 0 ? (
                <p className="text-sm text-fg-muted">{zh ? '先创建 Provider，再读取其模型目录。' : 'Create a provider before fetching its model catalog.'}</p>
              ) : (
                <p className="text-sm text-fg-muted">{zh ? '选择 Provider，然后点击“读取模型列表”。' : 'Choose a provider and select “Fetch models” to load its catalog.'}</p>
              )}
            </div>
          )}

          {mode === 'catalog' && loadingCatalog && (
            <div role="status" className="flex min-h-44 items-center justify-center gap-2 rounded-xl border border-line text-sm text-fg-muted">
              <LoaderCircle size={18} className="animate-spin" aria-hidden="true" />
              {zh ? `正在读取 ${selectedProvider?.name || 'Provider'} 的模型列表…` : `Fetching models from ${selectedProvider?.name || 'provider'}…`}
            </div>
          )}

          {mode === 'catalog' && catalogLoaded && !loadingCatalog && (
            <section role="tabpanel" id="model-catalog-panel" aria-labelledby="model-catalog-tab" aria-label={zh ? '模型目录' : 'Model catalog'} className="space-y-3">
              {catalogSource === 'public' && (
                <p className="rounded-lg border border-sky-500/30 bg-sky-500/10 px-3 py-2.5 text-xs leading-relaxed text-sky-800 dark:text-sky-200">
                  {zh ? '官方公开目录，需在厂商处确认账号权限。公开目录模型不会默认勾选。' : 'Official public catalog. Confirm account access with the provider; public catalog models are not selected by default.'}
                </p>
              )}
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-sm font-semibold text-fg">
                    {zh ? `找到 ${catalog.length} 个模型` : `${catalog.length} models found`}
                  </p>
                  <p className="mt-0.5 text-xs text-fg-muted">
                    {zh ? `已选 ${selected.size} 个 · 可导入 ${importItems.length} 个` : `${selected.size} selected · ${importItems.length} ready to import`}
                    {selectedUnclassifiedCount > 0 && (zh ? ` · ${selectedUnclassifiedCount} 个待指定类型` : ` · ${selectedUnclassifiedCount} need a type`)}
                  </p>
                  {selectionLimitNotice && <p role="status" className="mt-1 text-xs font-medium text-amber-700 dark:text-amber-300">{zh ? `每次最多导入 ${MAX_IMPORT_ITEMS} 个模型；可减少选择后分批导入。` : `Imports are limited to ${MAX_IMPORT_ITEMS} models at a time. Reduce the selection and import in batches.`}</p>}
                </div>
                <label className="relative block w-full sm:max-w-xs">
                  <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-subtle" aria-hidden="true" />
                  <input
                    type="search"
                    aria-label={zh ? '搜索目录模型' : 'Search catalog models'}
                    placeholder={zh ? '搜索名称或模型代码' : 'Search name or model code'}
                    value={query}
                    disabled={busy}
                    onChange={(event) => setQuery(event.target.value)}
                    className={`${controlClass} pl-9`}
                  />
                </label>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <button type="button" className={smallButtonClass} disabled={busy || eligibleFiltered.length === 0} onClick={selectEligibleShown}>
                  {zh ? `全选当前可导入项 (${eligibleFiltered.length})` : `Select eligible shown (${eligibleFiltered.length})`}
                </button>
                <button type="button" className={smallButtonClass} disabled={busy || selected.size === 0} onClick={clearSelection}>
                  {zh ? '清空选择' : 'Clear selection'}
                </button>
                {selectedUnknown.length > 0 && (
                  <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2 sm:justify-end">
                    <label htmlFor="model-catalog-bulk-type" className="text-xs text-fg-muted">
                      {zh ? `为已选未知类型项指定类型 (${selectedUnknown.length})` : `Assign type to selected unknowns (${selectedUnknown.length})`}
                    </label>
                    <select
                      id="model-catalog-bulk-type"
                      value={bulkType}
                      disabled={busy}
                      onChange={(event) => setBulkType(event.target.value as ImportableModelType)}
                      className="min-h-9 rounded-lg border border-line bg-surface px-2 text-xs text-fg outline-none focus:border-accent focus:ring-2 focus:ring-accent/20"
                    >
                      <option value="chat">Chat</option>
                      <option value="embedding">Embedding</option>
                      <option value="reasoning">Reasoning</option>
                      <option value="rerank">Rerank</option>
                    </select>
                    <button type="button" className={smallButtonClass} disabled={busy} onClick={applyBulkType}>
                      {zh ? '应用' : 'Apply'}
                    </button>
                  </div>
                )}
              </div>

              {filteredModels.length === 0 ? (
                <div className="rounded-xl border border-dashed border-line px-4 py-10 text-center text-sm text-fg-muted">
                  {catalog.length === 0
                    ? (zh ? '该 Provider 没有返回模型。' : 'This provider returned no models.')
                    : (zh ? '没有匹配的模型。' : 'No models match your search.')}
                </div>
              ) : (
                <ul className="max-h-[min(48vh,440px)] space-y-2 overflow-y-auto pr-1" aria-label={zh ? '可选模型' : 'Selectable models'}>
                  {filteredModels.map((model) => {
                    const isRegistered = model.already_registered;
                    const currentType = getType(model);
                    const isSelected = selected.has(model.model_code);
                    return (
                      <li key={model.model_code} className={`grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-2 rounded-xl border px-3 py-3 sm:grid-cols-[auto_minmax(0,1fr)_minmax(130px,180px)] sm:items-center ${isRegistered ? 'border-line bg-surface-muted/60 opacity-75' : 'border-line bg-surface'}`}>
                        <input
                          type="checkbox"
                          aria-label={`${zh ? '选择' : 'Select'} ${model.name} (${model.model_code})`}
                          checked={isSelected}
                          disabled={isRegistered || busy}
                          onChange={(event) => toggleSelected(model.model_code, event.target.checked)}
                          className="mt-1 h-4 w-4 rounded border-line-strong text-accent focus:ring-accent sm:mt-0"
                        />
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="truncate text-sm font-semibold text-fg">{model.name || model.model_code}</span>
                            {isRegistered && (
                              <span className="inline-flex items-center gap-1 rounded-full bg-surface-muted px-2 py-0.5 text-[10px] font-semibold text-fg-muted">
                                <Check size={12} aria-hidden="true" />{zh ? '已登记' : 'Already registered'}
                              </span>
                            )}
                          </div>
                          <code className="mt-1 block break-all text-xs text-fg-muted">{model.model_code}</code>
                          <p className="mt-1 text-[11px] text-fg-subtle">
                            {model.model_type === 'unknown'
                              ? (currentType ? (zh ? `目录类型未知 · 指定为 ${currentType}` : `Catalog type unknown · assigned ${currentType}`) : (zh ? '目录未识别类型，请手动指定' : 'Unknown catalog type; assign a type manually'))
                              : (zh ? `目录类型：${model.model_type}` : `Catalog type: ${model.model_type}`)}
                          </p>
                        </div>
                        {model.model_type === 'unknown' && !isRegistered && (
                          <label className="col-start-2 sm:col-start-auto">
                            <span className="sr-only">{zh ? `为 ${model.name} 指定模型类型` : `Assign model type for ${model.name}`}</span>
                            <select
                              aria-label={zh ? `为 ${model.name} 指定类型` : `Assign type for ${model.name}`}
                              value={typeOverrides[model.model_code] || ''}
                              disabled={busy}
                              onChange={(event) => assignRowType(model.model_code, event.target.value)}
                              className="min-h-9 w-full rounded-lg border border-line bg-surface px-2 text-xs text-fg outline-none focus:border-accent focus:ring-2 focus:ring-accent/20 disabled:opacity-60"
                            >
                              <option value="">{zh ? '选择类型…' : 'Choose type…'}</option>
                              <option value="chat">Chat</option>
                              <option value="embedding">Embedding</option>
                              <option value="reasoning">Reasoning</option>
                              <option value="rerank">Rerank</option>
                            </select>
                          </label>
                        )}
                        {model.model_type !== 'unknown' && <span className="col-start-2 text-xs font-medium text-fg-muted sm:col-start-auto sm:text-right">{currentType}</span>}
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          )}

          {mode === 'paste' && (
            <section role="tabpanel" id="model-paste-panel" aria-labelledby="model-paste-tab" className="space-y-4">
              <div>
                <label htmlFor="model-catalog-pasted-ids" className="mb-1.5 block text-[13px] font-medium text-fg">
                  {zh ? '批量粘贴模型 ID' : 'Paste model IDs'}
                </label>
                <textarea
                  id="model-catalog-pasted-ids"
                  rows={9}
                  value={pastedIdsText}
                  disabled={busy}
                  onChange={(event) => setPastedIdsText(event.target.value)}
                  placeholder={zh ? '例如：\nmodel-id-1\nmodel-id-2' : 'Example:\nmodel-id-1\nmodel-id-2'}
                  className={`${controlClass} min-h-40 resize-y font-mono text-[13px] leading-relaxed`}
                />
                <p className="mt-2 text-xs leading-relaxed text-fg-muted">
                  {zh
                    ? '从供应商控制台复制模型 ID，每行一个。系统会去除首尾空白并自动去重；此方式不会读取或请求供应商目录。'
                    : 'Copy model IDs from the provider console, one per line. Leading and trailing whitespace is trimmed and duplicates are removed. This path does not fetch the provider catalog.'}
                </p>
              </div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] sm:items-end">
                <div>
                  <label htmlFor="model-catalog-pasted-type" className="mb-1.5 block text-[13px] font-medium text-fg">
                    {zh ? '整批模型类型' : 'Type for this batch'}
                  </label>
                  <select
                    id="model-catalog-pasted-type"
                    value={pastedType}
                    disabled={busy}
                    onChange={(event) => setPastedType(event.target.value as ImportableModelType)}
                    className={controlClass}
                  >
                    <option value="chat">Chat</option>
                    <option value="embedding">Embedding</option>
                    <option value="reasoning">Reasoning</option>
                    <option value="rerank">Rerank</option>
                  </select>
                </div>
                <p role="status" className="text-xs text-fg-muted sm:pb-2">
                  {uniquePastedIds.length > MAX_IMPORT_ITEMS
                    ? (zh ? `识别到 ${uniquePastedIds.length} 个唯一 ID；每次最多导入 ${MAX_IMPORT_ITEMS} 个，请拆成多批后提交。` : `${uniquePastedIds.length} unique IDs found; each import allows up to ${MAX_IMPORT_ITEMS}. Split these IDs into smaller batches.`)
                    : zh
                      ? `识别到 ${uniquePastedIds.length} 个唯一 ID${trimmedPastedIds.length > uniquePastedIds.length ? `，已去除 ${trimmedPastedIds.length - uniquePastedIds.length} 个重复项` : ''}。`
                      : `${uniquePastedIds.length} unique IDs${trimmedPastedIds.length > uniquePastedIds.length ? ` · removed ${trimmedPastedIds.length - uniquePastedIds.length} duplicates` : ''}.`}
                </p>
              </div>
            </section>
          )}
        </div>

        <footer className="nx-form-dialog-footer flex flex-col-reverse gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-5">
          <p className="text-xs text-fg-muted">
            {mode === 'paste'
              ? (zh ? `将提交 ${uniquePastedIds.length} 个唯一 ID，名称使用模型 ID；此路径不请求目录，也不会修改模型路由。` : `${uniquePastedIds.length} unique IDs will be submitted with the ID as each model name; this path makes no catalog request and does not change model routes.`)
              : catalogLoaded
                ? (zh ? `将导入 ${importItems.length} 个模型，不会修改模型路由；已存在的模型会跳过。` : `${importItems.length} models will be submitted; model routes will not change, and existing models are skipped.`)
                : (zh ? '读取目录不会修改模型配置。' : 'Fetching the catalog does not change model configuration.')}
          </p>
          <div className="flex justify-end gap-2">
            <button type="button" className="nx-dialog-action-secondary rounded-lg border px-4 text-sm font-semibold disabled:opacity-50" disabled={importing} onClick={onClose}>
              {zh ? '取消' : 'Cancel'}
            </button>
            <button type="button" className="nx-dialog-action-primary inline-flex items-center justify-center gap-2 rounded-lg border px-4 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50" disabled={importBlocked} onClick={() => void handleImport()}>
              {importing && <LoaderCircle size={16} className="animate-spin" aria-hidden="true" />}
              {importing
                ? (zh ? '导入中…' : 'Importing…')
                : mode === 'paste'
                  ? (zh ? `导入输入 ID (${importItems.length})` : `Import IDs (${importItems.length})`)
                  : (zh ? `导入所选 (${importItems.length})` : `Import selected (${importItems.length})`)}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
};
