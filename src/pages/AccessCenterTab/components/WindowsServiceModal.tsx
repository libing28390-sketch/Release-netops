import { DataTable } from '../../../components/DataTable';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, ChevronLeft, ChevronRight, Loader2, Play, RefreshCw, Search, Square, X } from 'lucide-react';
import {
  getWindowsServices,
  performWindowsServiceAction,
  WindowsManagementError,
  type WindowsService,
  type WindowsServiceAction,
} from '../../../api/windowsManagement';
import { useEscapeClose } from '../../../hooks/useEscapeClose';
import { ActionIconButton } from '../../../components/ui/ActionIconButton';

import { TableActionCell, TableActionHeader } from '../../../components/ui/TableActionColumn';
import type { TableExportData } from '../../../components/ui/TableExportMenu';
interface WindowsServiceModalProps {
  isOpen: boolean;
  assetId: string | null;
  hostname?: string;
  language: string;
  showToast: (message: string, type: 'success' | 'error' | 'info') => void;
  onClose: () => void;
}

type ViewState = 'loading' | 'ready' | 'error' | 'forbidden';

const statusClass: Record<string, string> = {
  running: 'bg-emerald-50 text-emerald-700',
  stopped: 'bg-slate-100 text-slate-600',
  paused: 'bg-amber-50 text-amber-700',
};

function serviceStatus(service: WindowsService) {
  return String(service.status || 'unknown').toLowerCase();
}

export default function WindowsServiceModal({
  isOpen,
  assetId,
  hostname,
  language,
  showToast,
  onClose,
}: WindowsServiceModalProps) {
  useEscapeClose(isOpen, onClose);
  const isZh = language === 'zh';
  const [services, setServices] = useState<WindowsService[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [searchDraft, setSearchDraft] = useState('');
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('all');
  const [viewState, setViewState] = useState<ViewState>('loading');
  const [error, setError] = useState('');
  const [actionKey, setActionKey] = useState('');
  const [reason, setReason] = useState('');
  const listAbortRef = useRef<AbortController | null>(null);
  const actionAbortRef = useRef<AbortController | null>(null);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const text = useMemo(() => ({
    title: isZh ? 'Windows 服务管理' : 'Windows service management',
    close: isZh ? '关闭' : 'Close',
    search: isZh ? '搜索服务名称或显示名' : 'Search service name or display name',
    submit: isZh ? '搜索' : 'Search',
    all: isZh ? '全部状态' : 'All statuses',
    running: isZh ? '运行中' : 'Running',
    stopped: isZh ? '已停止' : 'Stopped',
    paused: isZh ? '已暂停' : 'Paused',
    unknown: isZh ? '未知' : 'Unknown',
    name: isZh ? '服务' : 'Service',
    serviceName: isZh ? '服务名称' : 'Service name',
    displayName: isZh ? '显示名称' : 'Display name',
    description: isZh ? '说明' : 'Description',
    status: isZh ? '状态' : 'Status',
    actions: isZh ? '操作' : 'Actions',
    start: isZh ? '启动' : 'Start',
    stop: isZh ? '停止' : 'Stop',
    restart: isZh ? '重启' : 'Restart',
    loading: isZh ? '正在加载服务...' : 'Loading services...',
    empty: isZh ? '没有匹配的 Windows 服务' : 'No matching Windows services',
    permission: isZh ? '你没有查看此资产 Windows 服务的权限' : 'You do not have permission to view Windows services for this asset',
    loadError: isZh ? '服务列表加载失败' : 'Unable to load Windows services',
    retry: isZh ? '重试' : 'Retry',
    page: isZh ? '页' : 'pages',
    reason: isZh ? '操作原因（必填）' : 'Reason (required)',
  }), [isZh]);

  const exportAllServices = useCallback(async (): Promise<TableExportData> => {
    if (!assetId) throw new Error(text.loadError);
    const allServices: WindowsService[] = [];
    let page = 1;
    let total = Number.POSITIVE_INFINITY;
    while (allServices.length < total) {
      const result = await getWindowsServices(assetId, { page, pageSize: 100, search, status });
      allServices.push(...result.items);
      total = result.total;
      if (!result.items.length && allServices.length < total) {
        throw new Error(`Windows 服务导出不完整：已读取 ${allServices.length} / ${total} 条。`);
      }
      page += 1;
    }
    return {
      headers: [text.displayName, text.serviceName, text.description, text.status, isZh ? '启动类型' : 'Start type'],
      rows: allServices.map((service) => {
        const currentStatus = serviceStatus(service);
        return [
          service.display_name || service.name,
          service.name,
          service.description || '',
          currentStatus === 'running' ? text.running : currentStatus === 'stopped' ? text.stopped : currentStatus === 'paused' ? text.paused : (service.status || text.unknown),
          String(service.start_type || '—'),
        ];
      }),
    };
  }, [assetId, isZh, search, status, text]);

  const abortRequests = useCallback(() => {
    listAbortRef.current?.abort();
    actionAbortRef.current?.abort();
    listAbortRef.current = null;
    actionAbortRef.current = null;
  }, []);

  const loadServices = useCallback(async () => {
    if (!isOpen || !assetId) return;
    listAbortRef.current?.abort();
    const controller = new AbortController();
    listAbortRef.current = controller;
    setViewState('loading');
    setError('');
    try {
      const result = await getWindowsServices(assetId, { page, pageSize, search, status }, controller.signal);
      if (controller.signal.aborted) return;
      setServices(result.items);
      setTotal(result.total);
      setViewState('ready');
    } catch (cause) {
      if (controller.signal.aborted) return;
      const managementError = cause instanceof WindowsManagementError ? cause : null;
      setViewState(managementError?.status === 401 || managementError?.status === 403 ? 'forbidden' : 'error');
      setError(managementError?.message || (cause instanceof Error ? cause.message : text.loadError));
    }
  }, [assetId, page, pageSize, search, status, isOpen, text.loadError]);

  useEffect(() => {
    if (!isOpen) {
      abortRequests();
      return undefined;
    }
    void loadServices();
    return () => listAbortRef.current?.abort();
  }, [abortRequests, isOpen, loadServices]);

  useEffect(() => {
    if (!isOpen) return;
    setPage(1);
    setSearch('');
    setSearchDraft('');
    setStatus('all');
    setReason('');
  }, [isOpen, assetId]);

  const submitSearch = (event: React.FormEvent) => {
    event.preventDefault();
    setPage(1);
    setSearch(searchDraft.trim());
  };

  const performAction = async (service: WindowsService, action: WindowsServiceAction) => {
    if (!assetId || actionKey) return;
    if (!reason.trim()) {
      showToast(isZh ? '请先填写操作原因' : 'Enter a reason before changing the service', 'info');
      return;
    }
    const serviceLabel = service.display_name || service.name;
    const actionLabel = action === 'start' ? text.start : action === 'stop' ? text.stop : text.restart;
    const confirmed = window.confirm(isZh
      ? `确认对服务“${serviceLabel}”执行${actionLabel}？`
      : `Confirm ${actionLabel.toLowerCase()} service “${serviceLabel}”?`);
    if (!confirmed) return;

    const key = `${service.name}:${action}`;
    const controller = new AbortController();
    actionAbortRef.current = controller;
    setActionKey(key);
    try {
      const result = await performWindowsServiceAction(assetId, service.name, action, reason.trim(), controller.signal);
      if (controller.signal.aborted) return;
      showToast(result.message || (isZh ? `${serviceLabel} 操作已完成` : `${serviceLabel} action completed`), 'success');
      await loadServices();
    } catch (cause) {
      if (controller.signal.aborted) return;
      const message = cause instanceof Error ? cause.message : (isZh ? '服务操作失败' : 'Service action failed');
      showToast(message, 'error');
    } finally {
      if (!controller.signal.aborted) setActionKey('');
      actionAbortRef.current = null;
    }
  };

  if (!isOpen || !assetId) return null;

  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="windows-service-modal-title">
      <div className="flex max-h-[min(760px,90vh)] w-full max-w-5xl flex-col overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
          <div>
            <h2 id="windows-service-modal-title" className="text-base font-bold text-slate-800">{text.title}</h2>
            <p className="mt-1 text-xs text-slate-400">{hostname || assetId}</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-xl p-2 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700" aria-label={text.close}>
            <X size={18} />
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 bg-slate-50/60 px-6 py-3">
          <form onSubmit={submitSearch} className="flex min-w-[260px] flex-1 items-center gap-2">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={15} />
              <input value={searchDraft} onChange={(event) => setSearchDraft(event.target.value)} placeholder={text.search} className="w-full rounded-xl border border-slate-200 bg-white py-2 pl-9 pr-3 text-xs outline-none transition focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100" />
            </div>
            <button type="submit" className="rounded-xl bg-cyan-600 px-3.5 py-2 text-xs font-semibold text-white transition hover:bg-cyan-700">{text.submit}</button>
          </form>
          <select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600 outline-none focus:border-cyan-400" aria-label={text.status}>
            <option value="all">{text.all}</option>
            <option value="running">{text.running}</option>
            <option value="stopped">{text.stopped}</option>
            <option value="paused">{text.paused}</option>
          </select>
          <input value={reason} onChange={(event) => setReason(event.target.value)} placeholder={text.reason} className="min-w-[170px] rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs outline-none transition focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100" />
        </div>

        <div className="min-h-[300px] flex-1 overflow-auto px-6 py-4">
          {viewState === 'loading' && (
            <div className="flex min-h-[280px] items-center justify-center gap-2 text-sm text-slate-400"><Loader2 className="animate-spin" size={18} />{text.loading}</div>
          )}
          {viewState === 'forbidden' && (
            <div className="flex min-h-[280px] flex-col items-center justify-center gap-3 text-center"><AlertCircle className="text-amber-500" size={28} /><p className="text-sm font-semibold text-slate-600">{text.permission}</p><p className="max-w-md text-xs text-slate-400">{error}</p></div>
          )}
          {viewState === 'error' && (
            <div className="flex min-h-[280px] flex-col items-center justify-center gap-3 text-center"><AlertCircle className="text-rose-500" size={28} /><p className="text-sm font-semibold text-slate-600">{text.loadError}</p><p className="max-w-md text-xs text-slate-400">{error}</p><button type="button" onClick={() => void loadServices()} className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-600 hover:border-cyan-300 hover:text-cyan-700"><RefreshCw size={14} />{text.retry}</button></div>
          )}
          {viewState === 'ready' && services.length === 0 && (
            <div className="flex min-h-[280px] flex-col items-center justify-center gap-2 text-sm text-slate-400"><Square size={24} /><span>{text.empty}</span></div>
          )}
          {viewState === 'ready' && services.length > 0 && (
            <DataTable unstyled exportConfig={{ filename: 'windows-services', language: isZh ? 'zh' : 'en', disabled: viewState !== 'ready' || services.length === 0, exportData: exportAllServices }} className="w-full min-w-[1100px] border-separate border-spacing-0 text-left text-xs">
              <thead><tr className="text-[10px] uppercase tracking-wider text-slate-400"><th className="border-b border-slate-100 px-3 py-3">{text.displayName}</th><th className="border-b border-slate-100 px-3 py-3">{text.serviceName}</th><th className="border-b border-slate-100 px-3 py-3">{text.description}</th><th className="border-b border-slate-100 px-3 py-3">{text.status}</th><th className="border-b border-slate-100 px-3 py-3">{isZh ? '启动类型' : 'Start type'}</th><TableActionHeader className="border-b border-slate-100 px-3 py-3 text-right">{text.actions}</TableActionHeader></tr></thead>
              <tbody>{services.map((service) => {
                const currentStatus = serviceStatus(service);
                const isBusy = actionKey.startsWith(`${service.name}:`);
                return <tr key={service.name} className="border-b border-slate-50 hover:bg-slate-50/70">
                  <td className="px-3 py-3 font-semibold text-slate-700">{service.display_name || service.name}</td>
                  <td className="px-3 py-3 font-mono text-slate-500">{service.name}</td>
                  <td className="max-w-[370px] truncate px-3 py-3 text-slate-500" title={service.description || ''}>{service.description || '—'}</td>
                  <td className="px-3 py-3"><span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${statusClass[currentStatus] || 'bg-slate-100 text-slate-500'}`}>{currentStatus === 'running' ? text.running : currentStatus === 'stopped' ? text.stopped : currentStatus === 'paused' ? text.paused : (service.status || text.unknown)}</span></td>
                  <td className="px-3 py-3 text-slate-500">{String(service.start_type || '—')}</td>
                  <TableActionCell className="px-3 py-3">{(['start', 'stop', 'restart'] as WindowsServiceAction[]).map((action) => { const ActionIcon = action === 'start' ? Play : action === 'stop' ? Square : RefreshCw; const disabled = isBusy || (action === 'start' && currentStatus === 'running') || (action === 'stop' && currentStatus === 'stopped'); const label = action === 'start' ? text.start : action === 'stop' ? text.stop : text.restart; return <ActionIconButton key={action} icon={ActionIcon} label={label} iconClassName={isBusy ? 'animate-spin' : undefined} variant={action === 'start' ? 'success' : action === 'stop' ? 'danger' : 'accent'} disabled={disabled} onClick={() => void performAction(service, action)} />; })}</TableActionCell>
                </tr>;
              })}</tbody>
            </DataTable>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-slate-100 px-6 py-3 text-xs text-slate-400">
          <span>{total} {isZh ? '项服务' : 'services'}</span>
          <div className="flex items-center gap-2">
            <select value={pageSize} onChange={(event) => { setPageSize(Number(event.target.value)); setPage(1); }} className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs" aria-label={isZh ? '每页条数' : 'Items per page'}><option value={10}>10 / {isZh ? '页' : 'page'}</option><option value={20}>20 / {isZh ? '页' : 'page'}</option><option value={50}>50 / {isZh ? '页' : 'page'}</option></select>
            <button type="button" disabled={page <= 1 || viewState === 'loading'} onClick={() => setPage((value) => Math.max(1, value - 1))} className="rounded-lg border border-slate-200 p-1.5 disabled:opacity-30" aria-label={isZh ? '上一页' : 'Previous page'}><ChevronLeft size={14} /></button>
            <span>{page} / {totalPages} {text.page}</span>
            <button type="button" disabled={page >= totalPages || viewState === 'loading'} onClick={() => setPage((value) => Math.min(totalPages, value + 1))} className="rounded-lg border border-slate-200 p-1.5 disabled:opacity-30" aria-label={isZh ? '下一页' : 'Next page'}><ChevronRight size={14} /></button>
          </div>
        </div>
      </div>
    </div>
  );
}
