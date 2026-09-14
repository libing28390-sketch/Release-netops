import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, ChevronLeft, ChevronRight, Loader2, Play, RefreshCw, Search, Square, X } from 'lucide-react';
import {
  getWindowsServices,
  performWindowsServiceAction,
  WindowsManagementError,
  type WindowsService,
  type WindowsServiceAction,
} from '../../../api/windowsManagement';

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
            <table className="w-full min-w-[680px] border-separate border-spacing-0 text-left text-xs">
              <thead><tr className="text-[10px] uppercase tracking-wider text-slate-400"><th className="border-b border-slate-100 px-3 py-3">{text.name}</th><th className="border-b border-slate-100 px-3 py-3">{text.status}</th><th className="border-b border-slate-100 px-3 py-3">{isZh ? '启动类型' : 'Start type'}</th><th className="border-b border-slate-100 px-3 py-3 text-right">{text.actions}</th></tr></thead>
              <tbody>{services.map((service) => {
                const currentStatus = serviceStatus(service);
                const isBusy = actionKey.startsWith(`${service.name}:`);
                return <tr key={service.name} className="border-b border-slate-50 hover:bg-slate-50/70">
                  <td className="px-3 py-3"><div className="font-semibold text-slate-700">{service.display_name || service.name}</div><div className="mt-0.5 font-mono text-[10px] text-slate-400">{service.name}</div>{service.description && <div className="mt-1 max-w-[370px] truncate text-[10px] text-slate-400">{service.description}</div>}</td>
                  <td className="px-3 py-3"><span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${statusClass[currentStatus] || 'bg-slate-100 text-slate-500'}`}>{currentStatus === 'running' ? text.running : currentStatus === 'stopped' ? text.stopped : currentStatus === 'paused' ? text.paused : (service.status || text.unknown)}</span></td>
                  <td className="px-3 py-3 text-slate-500">{String(service.start_type || '—')}</td>
                  <td className="px-3 py-3"><div className="flex justify-end gap-1.5">{(['start', 'stop', 'restart'] as WindowsServiceAction[]).map((action) => { const ActionIcon = action === 'start' ? Play : action === 'stop' ? Square : RefreshCw; const disabled = isBusy || (action === 'start' && currentStatus === 'running') || (action === 'stop' && currentStatus === 'stopped'); return <button key={action} type="button" disabled={disabled} onClick={() => void performAction(service, action)} className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1.5 text-[10px] font-semibold text-slate-600 transition hover:border-cyan-300 hover:bg-cyan-50 hover:text-cyan-700 disabled:cursor-not-allowed disabled:opacity-40"><ActionIcon size={12} className={isBusy ? 'animate-spin' : ''} />{action === 'start' ? text.start : action === 'stop' ? text.stop : text.restart}</button>; })}</div></td>
                </tr>;
              })}</tbody>
            </table>
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
