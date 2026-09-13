import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  AlertTriangle, ArrowRight, CheckCircle2, CircleAlert, Database,
  LoaderCircle, RotateCcw, ShieldAlert, X,
} from 'lucide-react';
import type {
  CollectionPlanBulkOperation,
  CollectionPlanBulkOptions,
  CollectionPlanBulkPreview,
  CollectionPlanBulkPreviewResponse,
  CollectionPlanBulkPreviewRequest,
  CollectionPlanFilters,
  CollectionPlanOption,
} from '../types';

interface BulkCollectionPlanModalProps {
  language: string;
  onClose: () => void;
  onCreateScheduledJob: (filters: CollectionPlanFilters) => void;
}

type ApiFailure = Error & { status?: number; permissionDenied?: boolean };

const TEMPLATE_OPTIONS = [
  { value: 'basic', zh: '基础设备', en: 'Basic' },
  { value: 'layer2_switch', zh: '二层交换机', en: 'Layer 2 switch' },
  { value: 'layer3_gateway', zh: '三层网关', en: 'Layer 3 gateway' },
  { value: 'firewall', zh: '防火墙', en: 'Firewall' },
  { value: 'wireless', zh: '无线设备', en: 'Wireless' },
] as const;

const EMPTY_OPTIONS: CollectionPlanBulkOptions = {
  sites: [], roles: [], categories: [], platforms: [],
};

const safeBackendDetail = (payload: unknown): string | undefined => {
  if (!payload || typeof payload !== 'object') return undefined;
  const body = payload as { detail?: unknown; message?: unknown };
  const detail = typeof body.detail === 'string' ? body.detail : body.message;
  if (typeof detail !== 'string') return undefined;
  const normalized = detail.replace(/[\r\n\t]+/g, ' ').trim();
  return normalized && normalized.length <= 240 ? normalized : undefined;
};

const makeApiFailure = (status: number, payload: unknown, zh: boolean): ApiFailure => {
  const permissionDenied = status === 401 || status === 403;
  const message = permissionDenied
    ? (zh ? '当前账号无权执行此操作，或登录状态已失效。' : 'You are not authorized to perform this action, or your session has expired.')
    : status >= 500
      ? (zh ? `服务暂时不可用（HTTP ${status}），请稍后重试。` : `The service is temporarily unavailable (HTTP ${status}). Please try again later.`)
      : safeBackendDetail(payload) || (zh ? `请求失败（HTTP ${status}）。` : `Request failed (HTTP ${status}).`);
  const error = new Error(message) as ApiFailure;
  error.status = status;
  error.permissionDenied = permissionDenied;
  return error;
};

const parseOptionList = (input: unknown): CollectionPlanOption[] => {
  if (!Array.isArray(input)) return [];
  return input.flatMap((item): CollectionPlanOption[] => {
    if (!item || typeof item !== 'object') return [];
    const option = item as { value?: unknown; count?: unknown };
    if (typeof option.value !== 'string' || !option.value.trim()) return [];
    const count = typeof option.count === 'number' && Number.isFinite(option.count) ? option.count : 0;
    return [{ value: option.value, count }];
  });
};

const parseBulkOptions = (payload: unknown): CollectionPlanBulkOptions | null => {
  if (!payload || typeof payload !== 'object') return null;
  const body = payload as { success?: unknown; data?: unknown };
  if (body.success !== true || !body.data || typeof body.data !== 'object') return null;
  const data = body.data as Record<string, unknown>;
  return {
    sites: parseOptionList(data.sites),
    roles: parseOptionList(data.roles),
    categories: parseOptionList(data.categories),
    platforms: parseOptionList(data.platforms),
  };
};

const parseBulkPreview = (payload: unknown): CollectionPlanBulkPreviewResponse | null => {
  if (!payload || typeof payload !== 'object') return null;
  const body = payload as { success?: unknown; data?: unknown };
  if (body.success !== true || !body.data || typeof body.data !== 'object') return null;
  const data = body.data as Record<string, unknown>;
  if (
    typeof data.matched_count !== 'number' || !Number.isFinite(data.matched_count) ||
    typeof data.overridden_count !== 'number' || !Number.isFinite(data.overridden_count) ||
    typeof data.snapshot_token !== 'string' || !data.snapshot_token ||
    (data.operation !== 'apply' && data.operation !== 'reset')
  ) return null;

  const sample = Array.isArray(data.sample) ? data.sample.slice(0, 10).flatMap((item): CollectionPlanBulkPreview['sample'] => {
    if (!item || typeof item !== 'object') return [];
    const candidate = item as Record<string, unknown>;
    const deviceId = candidate.device_id;
    if (typeof deviceId !== 'string' && typeof deviceId !== 'number') return [];
    const textOrNull = (value: unknown): string | null => typeof value === 'string' ? value : null;
    return [{
      device_id: deviceId,
      hostname: textOrNull(candidate.hostname),
      ip_address: textOrNull(candidate.ip_address),
      role: textOrNull(candidate.role),
      site: textOrNull(candidate.site),
      platform: textOrNull(candidate.platform),
      current_template: textOrNull(candidate.current_template),
    }];
  }) : [];
  return {
    matched_count: Math.max(0, data.matched_count),
    overridden_count: Math.max(0, data.overridden_count),
    sample,
    snapshot_token: data.snapshot_token,
    operation: data.operation,
    ...(typeof data.template_id === 'string' ? { template_id: data.template_id } : {}),
  };
};

const hasAtLeastOneFilter = (filters: CollectionPlanFilters): boolean =>
  Object.values(filters).some((value) => typeof value === 'string' && value.trim().length > 0);

const getAuthHeaders = (): HeadersInit => {
  const token = localStorage.getItem('netops_token');
  return token
    ? { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }
    : { 'Content-Type': 'application/json' };
};

export const BulkCollectionPlanModal: React.FC<BulkCollectionPlanModalProps> = ({
  language,
  onClose,
  onCreateScheduledJob,
}) => {
  const zh = language === 'zh';
  const [options, setOptions] = useState<CollectionPlanBulkOptions>(EMPTY_OPTIONS);
  const [optionsLoading, setOptionsLoading] = useState(true);
  const [optionsError, setOptionsError] = useState<ApiFailure | null>(null);
  const [filters, setFilters] = useState<CollectionPlanFilters>({});
  const [operation, setOperation] = useState<CollectionPlanBulkOperation>('apply');
  const [templateId, setTemplateId] = useState<(typeof TEMPLATE_OPTIONS)[number]['value']>('basic');
  const [preview, setPreview] = useState<CollectionPlanBulkPreview | null>(null);
  const [previewRequest, setPreviewRequest] = useState<CollectionPlanBulkPreviewRequest | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [applyLoading, setApplyLoading] = useState(false);
  const [actionError, setActionError] = useState<ApiFailure | null>(null);
  const [confirmationChecked, setConfirmationChecked] = useState(false);
  const [applySucceeded, setApplySucceeded] = useState(false);
  const [affectedCount, setAffectedCount] = useState(0);
  const optionsController = useRef<AbortController | null>(null);
  const actionController = useRef<AbortController | null>(null);
  const actionSequence = useRef(0);

  const loadOptions = useCallback(async () => {
    optionsController.current?.abort();
    const controller = new AbortController();
    optionsController.current = controller;
    setOptionsLoading(true);
    setOptionsError(null);
    try {
      const response = await fetch('/api/collection-plans/bulk-options', {
        headers: getAuthHeaders(),
        signal: controller.signal,
      });
      const payload: unknown = await response.json().catch(() => null);
      if (!response.ok) throw makeApiFailure(response.status, payload, zh);
      const parsed = parseBulkOptions(payload);
      if (!parsed) throw new Error(zh ? '服务器返回了无法识别的选项数据。' : 'The server returned an invalid options response.');
      setOptions(parsed);
    } catch (error) {
      if (controller.signal.aborted) return;
      setOptionsError(error instanceof Error ? error as ApiFailure : new Error(zh ? '加载筛选项失败。' : 'Failed to load filter options.'));
    } finally {
      if (!controller.signal.aborted) setOptionsLoading(false);
    }
  }, [zh]);

  useEffect(() => {
    void loadOptions();
    return () => {
      optionsController.current?.abort();
      actionController.current?.abort();
    };
  }, [loadOptions]);

  const optionSets = useMemo(() => [
    { key: 'site' as const, label: zh ? '站点' : 'Site', items: options.sites },
    { key: 'role' as const, label: zh ? '角色' : 'Role', items: options.roles },
    { key: 'category' as const, label: zh ? '设备类型' : 'Device category', items: options.categories },
    { key: 'platform' as const, label: zh ? '平台' : 'Platform', items: options.platforms },
  ], [options, zh]);

  const canClose = !previewLoading && !applyLoading;
  const filtersSelected = hasAtLeastOneFilter(filters);
  const isBusy = previewLoading || applyLoading;
  const noOptions = !optionsLoading && !optionsError && !Object.values(options).some((values) => values.length > 0);

  const invalidatePreview = () => {
    actionSequence.current += 1;
    actionController.current?.abort();
    actionController.current = null;
    setPreviewLoading(false);
    setPreview(null);
    setPreviewRequest(null);
    setActionError(null);
    setConfirmationChecked(false);
    setApplySucceeded(false);
    setAffectedCount(0);
  };

  const updateFilter = (key: keyof CollectionPlanFilters, value: string) => {
    invalidatePreview();
    setFilters((current) => {
      const updated = { ...current };
      if (value) updated[key] = value;
      else delete updated[key];
      return updated;
    });
  };

  const changeOperation = (next: CollectionPlanBulkOperation) => {
    invalidatePreview();
    setOperation(next);
  };

  const changeTemplate = (next: (typeof TEMPLATE_OPTIONS)[number]['value']) => {
    invalidatePreview();
    setTemplateId(next);
  };

  const requestPreview = async () => {
    if (!filtersSelected || isBusy || applySucceeded) return;
    const request: CollectionPlanBulkPreviewRequest = {
      operation,
      ...(operation === 'apply' ? { template_id: templateId } : {}),
      filters: { ...filters },
    };
    const sequence = ++actionSequence.current;
    const controller = new AbortController();
    actionController.current?.abort();
    actionController.current = controller;
    setPreview(null);
    setPreviewRequest(null);
    setConfirmationChecked(false);
    setActionError(null);
    setPreviewLoading(true);
    try {
      const response = await fetch('/api/collection-plans/bulk-preview', {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify(request),
        signal: controller.signal,
      });
      const payload: unknown = await response.json().catch(() => null);
      if (!response.ok) throw makeApiFailure(response.status, payload, zh);
      const parsed = parseBulkPreview(payload);
      if (!parsed || parsed.operation !== request.operation || (request.template_id && parsed.template_id !== request.template_id)) {
        throw new Error(zh ? '服务器返回了无法识别的预览数据，请重试。' : 'The server returned an invalid preview response. Please try again.');
      }
      if (actionSequence.current === sequence) {
        setPreview({ ...parsed, operation: request.operation, ...(request.template_id ? { template_id: request.template_id } : {}), filters: request.filters });
        setPreviewRequest(request);
      }
    } catch (error) {
      if (controller.signal.aborted || actionSequence.current !== sequence) return;
      setActionError(error instanceof Error ? error as ApiFailure : new Error(zh ? '预览失败，请重试。' : 'Preview failed. Please try again.'));
    } finally {
      if (actionSequence.current === sequence) setPreviewLoading(false);
    }
  };

  const applyPreview = async () => {
    if (!preview || !previewRequest || preview.matched_count < 1 || !confirmationChecked || isBusy || applySucceeded) return;
    const sequence = ++actionSequence.current;
    const controller = new AbortController();
    actionController.current?.abort();
    actionController.current = controller;
    setActionError(null);
    setApplyLoading(true);
    try {
      const response = await fetch('/api/collection-plans/bulk-apply', {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ ...previewRequest, snapshot_token: preview.snapshot_token }),
        signal: controller.signal,
      });
      const payload: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        if (response.status === 409) {
          setPreview(null);
          setPreviewRequest(null);
          setConfirmationChecked(false);
          throw new Error(zh ? '预览快照已过期或目标数据已变化。请重新预览后再确认应用。' : 'The preview snapshot expired or the target data changed. Preview again before applying.');
        }
        throw makeApiFailure(response.status, payload, zh);
      }
      const body = payload && typeof payload === 'object' ? payload as { success?: unknown; data?: unknown } : null;
      const data = body?.data && typeof body.data === 'object' ? body.data as { affected_count?: unknown } : null;
      if (body?.success !== true || typeof data?.affected_count !== 'number' || !Number.isFinite(data.affected_count)) {
        throw new Error(zh ? '服务器返回了无法识别的应用结果。' : 'The server returned an invalid apply result.');
      }
      if (actionSequence.current === sequence) {
        setAffectedCount(Math.max(0, data.affected_count));
        setApplySucceeded(true);
      }
    } catch (error) {
      if (controller.signal.aborted || actionSequence.current !== sequence) return;
      setActionError(error instanceof Error ? error as ApiFailure : new Error(zh ? '应用失败，请重试。' : 'Apply failed. Please try again.'));
    } finally {
      if (actionSequence.current === sequence) setApplyLoading(false);
    }
  };

  const warningText = operation === 'apply'
    ? (zh ? '确认后会用所选模板替换所有命中设备的当前采集模板，并清除这些设备的 collector overrides。' : 'This replaces the collection template on every matched device and clears their collector overrides.')
    : (zh ? '确认后会将所有命中设备恢复为角色默认模板并清除 collector overrides；不会删除设备资产。' : 'This restores the role-default template and clears collector overrides for every matched device. Device assets will not be deleted.');

  const optionLabel = (option: CollectionPlanOption) => `${option.value} (${option.count})`;

  return (
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/45 p-3 backdrop-blur-sm sm:p-6"
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        onMouseDown={(event) => { if (event.target === event.currentTarget && canClose) onClose(); }}
      >
        <motion.div
          role="dialog" aria-modal="true" aria-labelledby="bulk-plan-title"
          initial={{ opacity: 0, y: 18, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 10, scale: 0.99 }}
          className="flex max-h-[92vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl"
        >
          <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4 sm:px-6">
            <div className="flex items-center gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-cyan-50 text-cyan-700"><Database size={19} /></span>
              <div>
                <h2 id="bulk-plan-title" className="text-base font-bold text-slate-900">{zh ? '批量采集模板' : 'Bulk Collection Templates'}</h2>
                <p className="mt-0.5 text-xs text-slate-500">{zh ? '先按服务端范围预览，再确认写入；不会加载全量设备到浏览器。' : 'Preview the server-side target scope before writing; the full device list is never loaded here.'}</p>
              </div>
            </div>
            <button type="button" onClick={onClose} disabled={!canClose} aria-label={zh ? '关闭' : 'Close'} className="rounded-lg p-2 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 disabled:opacity-40"><X size={18} /></button>
          </div>

          <div className="flex-1 space-y-5 overflow-y-auto px-5 py-5 sm:px-6">
            {optionsError && (
              <div role="alert" className={`flex items-start gap-3 rounded-xl border p-3.5 text-sm ${optionsError.permissionDenied ? 'border-amber-200 bg-amber-50 text-amber-900' : 'border-rose-200 bg-rose-50 text-rose-800'}`}>
                {optionsError.permissionDenied ? <ShieldAlert size={17} className="mt-0.5 shrink-0" /> : <CircleAlert size={17} className="mt-0.5 shrink-0" />}
                <div className="min-w-0 flex-1"><p className="font-semibold">{optionsError.permissionDenied ? (zh ? '权限不足' : 'Permission required') : (zh ? '无法加载筛选项' : 'Could not load filter options')}</p><p className="mt-1 break-words text-xs">{optionsError.message}</p></div>
                <button type="button" onClick={() => void loadOptions()} disabled={optionsLoading || isBusy} className="shrink-0 inline-flex items-center gap-1.5 rounded-lg border border-current/20 px-2.5 py-1.5 text-xs font-semibold disabled:opacity-40"><RotateCcw size={13} />{zh ? '重试' : 'Retry'}</button>
              </div>
            )}

            {optionsLoading && (
              <div role="status" className="flex items-center gap-2 rounded-xl bg-slate-50 px-4 py-5 text-sm text-slate-600"><LoaderCircle size={16} className="animate-spin text-cyan-600" />{zh ? '正在加载可用筛选范围…' : 'Loading available filter options…'}</div>
            )}

            {!optionsLoading && !optionsError && noOptions && (
              <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center">
                <Database size={20} className="mx-auto text-slate-400" />
                <p className="mt-2 text-sm font-semibold text-slate-700">{zh ? '暂无可用筛选数据' : 'No filter options available'}</p>
                <p className="mt-1 text-xs text-slate-500">{zh ? '当前没有可供批量操作的设备范围。' : 'There are currently no device scopes available for bulk operations.'}</p>
              </div>
            )}

            {!optionsLoading && !optionsError && !noOptions && (
              <>
                <section className="space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div><h3 className="text-sm font-bold text-slate-800">{zh ? '1. 选择目标范围' : '1. Choose target scope'}</h3><p className="mt-0.5 text-xs text-slate-500">{zh ? '至少选择一个条件；多个条件按精确匹配的 AND 关系组合。' : 'Choose at least one condition; multiple conditions are combined with exact-match AND logic.'}</p></div>
                    <button type="button" onClick={() => { invalidatePreview(); setFilters({}); }} disabled={!filtersSelected || isBusy || applySucceeded} className="text-xs font-semibold text-cyan-700 hover:text-cyan-900 disabled:cursor-not-allowed disabled:opacity-40">{zh ? '清除筛选' : 'Clear filters'}</button>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    {optionSets.map(({ key, label, items }) => (
                      <label key={key} className="space-y-1.5 text-xs font-semibold text-slate-700">
                        <span>{label}</span>
                        <select value={filters[key] || ''} onChange={(event) => updateFilter(key, event.target.value)} disabled={isBusy || applySucceeded} className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-normal text-slate-700 outline-none transition focus:border-cyan-400 focus:ring-2 focus:ring-cyan-500/15 disabled:bg-slate-50 disabled:text-slate-400">
                          <option value="">{zh ? `全部（不限制${label}）` : `Any ${label.toLowerCase()}`}</option>
                          {items.map((option) => <option key={option.value} value={option.value}>{optionLabel(option)}</option>)}
                        </select>
                        {items.length === 0 && <span className="block text-[11px] font-normal text-slate-400">{zh ? '暂无该维度选项' : 'No options for this dimension'}</span>}
                      </label>
                    ))}
                  </div>
                  {!filtersSelected && <p className="flex items-center gap-1.5 text-xs text-amber-700"><AlertTriangle size={14} />{zh ? '必须至少选择一个条件，禁止无条件全库写入。' : 'At least one condition is required; an unfiltered fleet-wide write is not allowed.'}</p>}
                </section>

                <section className="space-y-3 rounded-xl border border-slate-200 bg-slate-50/70 p-4">
                  <h3 className="text-sm font-bold text-slate-800">{zh ? '2. 选择操作' : '2. Choose operation'}</h3>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <label className={`flex cursor-pointer items-start gap-2.5 rounded-xl border p-3 transition ${operation === 'apply' ? 'border-cyan-300 bg-cyan-50/70' : 'border-slate-200 bg-white'} ${isBusy || applySucceeded ? 'cursor-not-allowed opacity-60' : ''}`}>
                      <input type="radio" name="bulk-operation" checked={operation === 'apply'} onChange={() => changeOperation('apply')} disabled={isBusy || applySucceeded} className="mt-0.5 accent-cyan-600" />
                      <span><span className="block text-xs font-bold text-slate-800">{zh ? '应用采集模板' : 'Apply a template'}</span><span className="mt-1 block text-[11px] text-slate-500">{zh ? '从受支持的模板中选择。' : 'Choose from the supported templates.'}</span></span>
                    </label>
                    <label className={`flex cursor-pointer items-start gap-2.5 rounded-xl border p-3 transition ${operation === 'reset' ? 'border-amber-300 bg-amber-50/70' : 'border-slate-200 bg-white'} ${isBusy || applySucceeded ? 'cursor-not-allowed opacity-60' : ''}`}>
                      <input type="radio" name="bulk-operation" checked={operation === 'reset'} onChange={() => changeOperation('reset')} disabled={isBusy || applySucceeded} className="mt-0.5 accent-amber-600" />
                      <span><span className="block text-xs font-bold text-slate-800">{zh ? '恢复角色默认' : 'Reset to role default'}</span><span className="mt-1 block text-[11px] text-slate-500">{zh ? '按每台设备的角色恢复默认采集模板。' : 'Restore the default collection template for each device role.'}</span></span>
                    </label>
                  </div>
                  {operation === 'apply' && (
                    <label className="block space-y-1.5 text-xs font-semibold text-slate-700">
                      <span>{zh ? '采集模板' : 'Collection template'}</span>
                      <select value={templateId} onChange={(event) => changeTemplate(event.target.value as (typeof TEMPLATE_OPTIONS)[number]['value'])} disabled={isBusy || applySucceeded} className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-normal text-slate-700 outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-500/15 disabled:bg-slate-50">
                        {TEMPLATE_OPTIONS.map((item) => <option key={item.value} value={item.value}>{zh ? item.zh : item.en}</option>)}
                      </select>
                    </label>
                  )}
                </section>

                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="text-xs text-slate-500">{zh ? '预览仅返回命中总数和最多 10 台设备样例。' : 'Preview returns the total match count and at most 10 sample devices.'}</p>
                  <button type="button" onClick={() => void requestPreview()} disabled={!filtersSelected || isBusy || applySucceeded} className="inline-flex items-center gap-2 rounded-xl bg-cyan-700 px-4 py-2.5 text-xs font-bold text-white shadow-sm transition hover:bg-cyan-800 disabled:cursor-not-allowed disabled:opacity-40">
                    {previewLoading ? <LoaderCircle size={14} className="animate-spin" /> : <RotateCcw size={14} />}{zh ? '预览目标' : 'Preview targets'}
                  </button>
                </div>

                {actionError && (
                  <div role="alert" className={`flex items-start gap-2.5 rounded-xl border p-3 text-xs ${actionError.permissionDenied ? 'border-amber-200 bg-amber-50 text-amber-900' : 'border-rose-200 bg-rose-50 text-rose-800'}`}>
                    {actionError.permissionDenied ? <ShieldAlert size={15} className="mt-0.5 shrink-0" /> : <CircleAlert size={15} className="mt-0.5 shrink-0" />}
                    <div><p className="font-semibold">{actionError.permissionDenied ? (zh ? '权限不足' : 'Permission required') : (zh ? '操作未完成' : 'Action not completed')}</p><p className="mt-1 break-words">{actionError.message}</p></div>
                  </div>
                )}

                {previewLoading && <div role="status" className="flex items-center gap-2 rounded-xl bg-cyan-50 px-4 py-3 text-xs text-cyan-800"><LoaderCircle size={14} className="animate-spin" />{zh ? '正在向服务器计算命中范围…' : 'Calculating the target scope on the server…'}</div>}

                {preview && previewRequest && (
                  <section className="space-y-3 rounded-2xl border border-cyan-100 bg-white p-4 shadow-sm">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div><h3 className="text-sm font-bold text-slate-900">{zh ? '预览结果' : 'Preview results'}</h3><p className="mt-1 text-xs text-slate-500">{zh ? '筛选条件变更后需重新预览。' : 'Changing any filter requires a fresh preview.'}</p></div>
                      <div className="flex gap-2">
                        <span className="rounded-lg bg-cyan-50 px-2.5 py-1.5 text-xs font-bold text-cyan-800">{zh ? `命中 ${preview.matched_count} 台` : `${preview.matched_count} matched`}</span>
                        <span className="rounded-lg bg-amber-50 px-2.5 py-1.5 text-xs font-bold text-amber-800">{zh ? `自定义覆盖 ${preview.overridden_count} 台` : `${preview.overridden_count} overridden`}</span>
                      </div>
                    </div>

                    {preview.matched_count === 0 ? (
                      <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-center text-xs text-slate-600">{zh ? '当前条件没有匹配设备。调整筛选条件后重新预览。' : 'No devices match these filters. Adjust the conditions and preview again.'}</div>
                    ) : (
                      <>
                        <div className="max-h-64 overflow-auto rounded-xl border border-slate-100">
                          <table className="w-full min-w-[680px] text-left text-xs">
                            <thead className="sticky top-0 bg-slate-50 text-[10px] uppercase tracking-wide text-slate-500"><tr>
                              <th className="px-3 py-2">{zh ? '设备 / IP' : 'Device / IP'}</th><th className="px-3 py-2">{zh ? '站点 / 角色' : 'Site / Role'}</th><th className="px-3 py-2">{zh ? '平台' : 'Platform'}</th><th className="px-3 py-2">{zh ? '当前模板' : 'Current template'}</th>
                            </tr></thead>
                            <tbody className="divide-y divide-slate-100">
                              {preview.sample.map((device, index) => <tr key={`${device.device_id}-${index}`} className="text-slate-700">
                                <td className="px-3 py-2.5"><span className="block max-w-64 truncate font-semibold text-slate-800">{device.hostname || String(device.device_id)}</span><span className="block font-mono text-[10px] text-slate-500">ID {device.device_id} · {device.ip_address || '—'}</span></td>
                                <td className="px-3 py-2.5"><span>{device.site || '—'}</span><span className="block text-[10px] text-slate-500">{device.role || '—'}</span></td>
                                <td className="px-3 py-2.5 font-mono">{device.platform || '—'}</td><td className="px-3 py-2.5">{device.current_template || '—'}</td>
                              </tr>)}
                            </tbody>
                          </table>
                        </div>
                        <p className="text-[11px] text-slate-500">{zh ? `显示 ${preview.sample.length} 台样例（最多 10 台），操作范围仍以服务端预览快照为准。` : `Showing ${preview.sample.length} sample(s), at most 10; the server preview snapshot defines the operation scope.`}</p>

                        {!applySucceeded ? (
                          <div className="space-y-3 rounded-xl border border-amber-200 bg-amber-50/70 p-3.5">
                            <div className="flex items-start gap-2 text-xs text-amber-950"><AlertTriangle size={15} className="mt-0.5 shrink-0" /><p>{warningText}</p></div>
                            <label className="flex cursor-pointer items-start gap-2 text-xs font-medium text-slate-700"><input type="checkbox" checked={confirmationChecked} onChange={(event) => setConfirmationChecked(event.target.checked)} disabled={isBusy} className="mt-0.5 accent-amber-600" /><span>{zh ? '我已检查命中数量和样例，并理解上述影响。' : 'I reviewed the match count and samples and understand the impact above.'}</span></label>
                            <div className="flex justify-end">
                              <button type="button" onClick={() => void applyPreview()} disabled={!confirmationChecked || isBusy} className="inline-flex items-center gap-2 rounded-xl bg-amber-700 px-4 py-2.5 text-xs font-bold text-white shadow-sm transition hover:bg-amber-800 disabled:cursor-not-allowed disabled:opacity-40">
                                {applyLoading ? <LoaderCircle size={14} className="animate-spin" /> : <ShieldAlert size={14} />}{applyLoading ? (zh ? '正在应用…' : 'Applying…') : operation === 'apply' ? (zh ? '确认并应用' : 'Confirm and apply') : (zh ? '确认恢复默认' : 'Confirm reset')}
                              </button>
                            </div>
                          </div>
                        ) : (
                          <div role="status" className="flex flex-col gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-3.5 sm:flex-row sm:items-center sm:justify-between">
                            <div className="flex items-start gap-2 text-xs text-emerald-900"><CheckCircle2 size={16} className="mt-0.5 shrink-0" /><span className="font-semibold">{zh ? `操作完成：影响 ${affectedCount} 台设备。` : `Completed: ${affectedCount} device(s) affected.`}</span></div>
                            {preview.matched_count > 0 && <button type="button" onClick={() => onCreateScheduledJob(previewRequest.filters)} className="inline-flex items-center justify-center gap-2 rounded-xl bg-cyan-700 px-3.5 py-2.5 text-xs font-bold text-white transition hover:bg-cyan-800">{zh ? '为相同范围创建 NSOT 周期任务' : 'Create an NSOT schedule for this scope'}<ArrowRight size={14} /></button>}
                          </div>
                        )}
                      </>
                    )}
                  </section>
                )}
              </>
            )}
          </div>

          <div className="flex items-center justify-between gap-3 border-t border-slate-100 bg-slate-50/70 px-5 py-3.5 sm:px-6">
            <p className="text-[11px] text-slate-500">{zh ? '只有批量应用成功且命中设备后，才可创建相同范围的 NSOT 周期任务。' : 'The matching-scope NSOT schedule link is available only after a successful apply with matched devices.'}</p>
            <button type="button" onClick={onClose} disabled={!canClose} className="shrink-0 rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-100 disabled:opacity-40">{zh ? '关闭' : 'Close'}</button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
};
