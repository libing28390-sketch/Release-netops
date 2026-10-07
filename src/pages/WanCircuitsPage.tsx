import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Cable, Plus, RefreshCw, Search } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import PageHero from '../components/PageHero';
import Pagination from '../components/Pagination';
import { ActionButton } from '../components/ui/ActionIconButton';
import { sectionToolbarClass } from '../components/shared';
import { useCoreApp } from '../contexts/AppDomainContext';
import type { WanCircuitDetailResponse, WanCircuitFormPayload, WanCircuitHistoryResponse, WanCircuitItem, WanCircuitListResponse, WanCircuitOptions, WanCircuitSlaPolicyPayload, WanCircuitSlaResponse } from '../types/wan-circuits';
import { WanCircuitTable } from '../components/wan-circuits/WanCircuitTable';
import { WanCircuitDetail } from '../components/wan-circuits/WanCircuitDetail';
import { WanCircuitForm } from '../components/wan-circuits/WanCircuitForm';
import { WanProbeBindingsPanel } from '../components/wan-circuits/WanProbeBindingsPanel';
import { EmptyState, ErrorState, ForbiddenState, LoadingState } from '../components/wan-circuits/WanCircuitStates';

const DEFAULT_OPTIONS: WanCircuitOptions = { devices: [], interfaces: [], sites: [] };
const pageSizeOptions = [20, 50, 100];

const authHeaders = (json = false): Record<string, string> => {
  const token = localStorage.getItem('netops_token');
  return { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(json ? { 'Content-Type': 'application/json' } : {}) };
};

const responseError = async (response: Response, fallback: string) => {
  let detail = '';
  try {
    const body = await response.json() as { detail?: string; message?: string };
    detail = body.detail || body.message || '';
  } catch { /* non-json error */ }
  const error = new Error(detail || fallback);
  (error as Error & { status?: number }).status = response.status;
  return error;
};

const isForbidden = (error: unknown) => (error as Error & { status?: number })?.status === 403;

export const WanCircuitsPage: React.FC = () => {
  const { language, showToast, currentUser } = useCoreApp();
  const canEditWan = currentUser.role === 'Administrator' || currentUser.role === 'Operator';
  const location = useLocation();
  const navigate = useNavigate();
  const zh = language === 'zh';
  const [items, setItems] = useState<WanCircuitItem[]>([]);
  const [total, setTotal] = useState(0);
  const [summary, setSummary] = useState<Record<string, number | string | null>>({});
  const [options, setOptions] = useState<WanCircuitOptions>(DEFAULT_OPTIONS);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [keyword, setKeyword] = useState('');
  const [siteId, setSiteId] = useState('');
  const [appliedKeyword, setAppliedKeyword] = useState('');
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState('');
  const [forbidden, setForbidden] = useState(false);
  const [selectedId, setSelectedId] = useState('');
  const [detail, setDetail] = useState<WanCircuitItem | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const [detailForbidden, setDetailForbidden] = useState(false);
  const [history, setHistory] = useState<WanCircuitHistoryResponse | null>(null);
  const [sla, setSla] = useState<WanCircuitSlaResponse | null>(null);
  const [historyError, setHistoryError] = useState('');
  const [slaError, setSlaError] = useState('');
  const [formItem, setFormItem] = useState<WanCircuitItem | null | undefined>(undefined);
  const [saving, setSaving] = useState(false);
  const [savingSlaPolicy, setSavingSlaPolicy] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);
  const routeCircuitId = useMemo(() => {
    const match = location.pathname.match(/^\/monitor\/circuits\/([^/]+)$/);
    return match ? decodeURIComponent(match[1]) : '';
  }, [location.pathname]);

  const loadOptions = useCallback(async (signal: AbortSignal) => {
    const response = await fetch('/api/monitoring/wan-options', { headers: authHeaders(), signal });
    if (!response.ok) throw await responseError(response, zh ? '线路选项加载失败' : 'Circuit options failed to load');
    setOptions(await response.json() as WanCircuitOptions);
  }, [zh]);

  useEffect(() => {
    setSelectedId(routeCircuitId);
  }, [routeCircuitId]);

  useEffect(() => {
    const controller = new AbortController();
    void loadOptions(controller.signal).catch((error: unknown) => { if (!controller.signal.aborted && !isForbidden(error)) showToast(error instanceof Error ? error.message : (zh ? '线路选项加载失败' : 'Circuit options failed to load'), 'error'); });
    return () => controller.abort();
  }, [loadOptions, reloadToken, showToast, zh]);

  const loadList = useCallback(async (signal: AbortSignal) => {
    setListLoading(true); setListError(''); setForbidden(false);
    const query = new URLSearchParams({ page: String(page), page_size: String(Math.min(100, Math.max(20, pageSize))) });
    if (appliedKeyword.trim()) query.set('keyword', appliedKeyword.trim());
    if (siteId) query.set('site_id', siteId);
    const response = await fetch(`/api/monitoring/wan-links?${query.toString()}`, { headers: authHeaders(), signal });
    if (!response.ok) throw await responseError(response, zh ? '专线列表加载失败' : 'Circuit list failed to load');
    const body = await response.json() as WanCircuitListResponse;
    setItems(Array.isArray(body.items) ? body.items : []); setTotal(Number(body.total || 0)); setSummary(body.summary || {});
    if (!body.items?.length && !routeCircuitId) { setSelectedId(''); setDetail(null); }
    setListLoading(false);
  }, [appliedKeyword, page, pageSize, siteId, zh]);

  useEffect(() => {
    const controller = new AbortController();
    void loadList(controller.signal).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      setListLoading(false);
      if (isForbidden(error)) setForbidden(true);
      else setListError(error instanceof Error ? error.message : (zh ? '专线列表加载失败' : 'Circuit list failed to load'));
    });
    return () => controller.abort();
  }, [loadList, reloadToken, zh]);

  useEffect(() => {
    if (!selectedId) return;
    const controller = new AbortController();
    setDetailLoading(true); setDetailError(''); setDetailForbidden(false); setHistory(null); setSla(null); setHistoryError(''); setSlaError('');
    const loadDetail = async () => {
      const detailResponse = await fetch(`/api/monitoring/wan-links/${encodeURIComponent(selectedId)}`, { headers: authHeaders(), signal: controller.signal });
      if (!detailResponse.ok) throw await responseError(detailResponse, zh ? '线路详情加载失败' : 'Circuit details failed to load');
      const detailBody = await detailResponse.json() as WanCircuitDetailResponse;
      setDetail(detailBody.item); setDetailLoading(false);
      const [historyResult, slaResult] = await Promise.allSettled([
        fetch(`/api/monitoring/wan-links/${encodeURIComponent(selectedId)}/history?history_minutes=1440`, { headers: authHeaders(), signal: controller.signal }),
        fetch(`/api/monitoring/wan-links/${encodeURIComponent(selectedId)}/sla?window=24h`, { headers: authHeaders(), signal: controller.signal }),
      ]);
      if (controller.signal.aborted) return;
      if (historyResult.status === 'fulfilled' && historyResult.value.ok) setHistory(await historyResult.value.json() as WanCircuitHistoryResponse);
      else setHistoryError(historyResult.status === 'fulfilled' && historyResult.value.status === 403 ? (zh ? '无权查看历史证据' : 'You are not allowed to view history evidence') : (zh ? '历史接口未返回有效数据' : 'History endpoint did not return usable data'));
      if (slaResult.status === 'fulfilled' && slaResult.value.ok) setSla(await slaResult.value.json() as WanCircuitSlaResponse);
      else setSlaError(slaResult.status === 'fulfilled' && slaResult.value.status === 403 ? (zh ? '无权查看 SLA 覆盖' : 'You are not allowed to view SLA coverage') : (zh ? 'SLA 覆盖数据不可用' : 'SLA coverage is unavailable'));
    };
    void loadDetail().catch((error: unknown) => { if (controller.signal.aborted) return; setDetailLoading(false); if (isForbidden(error)) setDetailForbidden(true); else setDetailError(error instanceof Error ? error.message : (zh ? '线路详情加载失败' : 'Circuit details failed to load')); });
    return () => controller.abort();
  }, [reloadToken, selectedId, zh]);

  const selectedListItem = useMemo(() => items.find((item) => item.id === selectedId) || null, [items, selectedId]);
  const triggerReload = () => setReloadToken((value) => value + 1);
  const applySearch = (event: React.FormEvent) => { event.preventDefault(); setPage(1); setAppliedKeyword(keyword); };
  const selectCircuit = (item: WanCircuitItem) => { setSelectedId(item.id); navigate(`/monitor/circuits/${encodeURIComponent(item.id)}`); };
  const openEdit = (item: WanCircuitItem) => setFormItem(item);
  const openCreate = () => setFormItem(null);

  const refreshDeviceInterfaces = useCallback(async (deviceId: string, action: 'create' | 'update') => {
    const query = new URLSearchParams({ action });
    const response = await fetch(
      `/api/monitoring/wan-options/devices/${encodeURIComponent(deviceId)}/interfaces/refresh?${query.toString()}`,
      { method: 'POST', headers: authHeaders() },
    );
    if (!response.ok) throw await responseError(response, zh ? '自动读取设备端口失败' : 'Failed to refresh device ports');
    const body = await response.json() as { interfaces?: WanCircuitOptions['interfaces'] };
    const refreshedInterfaces = Array.isArray(body.interfaces) ? body.interfaces : [];
    setOptions((current) => ({
      ...current,
      interfaces: [
        ...current.interfaces.filter((entry) => entry.device_id !== deviceId),
        ...refreshedInterfaces,
      ],
    }));
  }, [zh]);

  const saveCircuit = async (payload: WanCircuitFormPayload) => {
    setSaving(true);
    try {
      const id = typeof payload.id === 'string' ? payload.id : '';
      const response = await fetch(id ? `/api/monitoring/wan-links/${encodeURIComponent(id)}` : '/api/monitoring/wan-links', { method: id ? 'PATCH' : 'POST', headers: authHeaders(true), body: JSON.stringify(payload) });
      if (!response.ok) throw await responseError(response, zh ? '线路保存失败' : 'Circuit save failed');
      const body = await response.json() as { item?: WanCircuitItem };
      const savedId = id || body.item?.id || '';
      setFormItem(undefined); showToast(zh ? '线路已保存' : 'Circuit saved', 'success'); triggerReload();
      if (savedId) { setSelectedId(savedId); navigate(`/monitor/circuits/${encodeURIComponent(savedId)}`); }
    } catch (error) { showToast(error instanceof Error ? error.message : (zh ? '线路保存失败' : 'Circuit save failed'), 'error'); } finally { setSaving(false); }
  };

  const saveSlaPolicy = async (payload: WanCircuitSlaPolicyPayload) => {
    if (!selectedId) return;
    setSavingSlaPolicy(true);
    try {
      const response = await fetch(`/api/monitoring/wan-links/${encodeURIComponent(selectedId)}/sla-policy`, { method: 'PUT', headers: authHeaders(true), body: JSON.stringify(payload) });
      if (!response.ok) throw await responseError(response, zh ? 'SLA 策略保存失败' : 'SLA policy save failed');
      showToast(zh ? 'SLA 策略已保存；达标状态仍以采样证据为准' : 'SLA policy saved; pass status still depends on sampling evidence', 'success');
      triggerReload();
    } catch (error) {
      showToast(error instanceof Error ? error.message : (zh ? 'SLA 策略保存失败' : 'SLA policy save failed'), 'error');
      throw error;
    } finally { setSavingSlaPolicy(false); }
  };

  const displayedSummary = [
    [zh ? '线路总数' : 'Circuits', summary.total ?? total],
    [zh ? '正常' : 'Healthy', summary.healthy ?? items.filter((item) => item.health_status === 'healthy').length],
    [zh ? '需关注' : 'Attention', summary.risky ?? summary.degraded ?? items.filter((item) => item.health_status === 'degraded' || item.health_status === 'critical').length],
    [zh ? '无数据' : 'No data', summary.unknown ?? '--'],
  ];

  return (
    <div className="flex h-full min-h-0 flex-col overflow-auto" style={{ background: 'var(--app-bg)' }}>
      <PageHero icon={Cable} title={zh ? '专线中心' : 'WAN circuits'} subtitle={zh ? '线路、端点、历史证据与 SLA 覆盖' : 'Circuits, endpoints, evidence and SLA coverage'} actions={<><ActionButton icon={RefreshCw} variant="default" size="sm" onClick={triggerReload} disabled={listLoading}>{zh ? '刷新' : 'Refresh'}</ActionButton><ActionButton icon={Plus} variant="primary" size="sm" onClick={openCreate}>{zh ? '注册线路' : 'Register circuit'}</ActionButton></>} />
      <main className="min-h-0 flex-1 space-y-4 p-4 md:p-6">
        {forbidden ? <ForbiddenState message={zh ? '当前账号没有访问专线中心的权限。' : 'Your account is not allowed to access WAN circuits.'} /> : <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{displayedSummary.map(([label, value]) => <div key={String(label)} className="rounded-xl border border-[var(--ui-border)] bg-[var(--ui-surface)] p-3 shadow-sm"><div className="text-[11px] text-[var(--muted-text)]">{label}</div><div className="mt-1 text-xl font-bold text-[var(--heading-text)]">{value ?? '--'}</div></div>)}</div>
          <form onSubmit={applySearch} className={`${sectionToolbarClass} flex-wrap`}><label className="flex min-w-[220px] flex-1 items-center gap-2 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 py-2"><Search size={15} className="text-[var(--muted-text)]" aria-hidden="true" /><input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder={zh ? '搜索线路、编号或运营商' : 'Search circuit, number or provider'} className="min-w-0 flex-1 bg-transparent text-xs text-[var(--ui-fg)] outline-none" /></label><select value={siteId} onChange={(event) => { setSiteId(event.target.value); setPage(1); }} className="rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 py-2 text-xs text-[var(--ui-fg)]"><option value="">{zh ? '全部站点' : 'All sites'}</option>{options.sites.map((site) => <option key={site.id} value={site.id}>{site.site_name}</option>)}</select><select value={pageSize} onChange={(event) => { setPageSize(Math.min(100, Math.max(20, Number(event.target.value)))); setPage(1); }} className="rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 py-2 text-xs text-[var(--ui-fg)]" aria-label={zh ? '每页条数' : 'Items per page'}>{pageSizeOptions.map((size) => <option key={size} value={size}>{size} / {zh ? '页' : 'page'}</option>)}</select><ActionButton icon={Search} variant="accent" size="sm" type="submit">{zh ? '查询' : 'Search'}</ActionButton></form>
          {listLoading ? <LoadingState label={zh ? '加载专线列表…' : 'Loading circuits…'} /> : listError ? <ErrorState title={zh ? '专线列表加载失败' : 'Circuit list failed to load'} message={listError} onAction={triggerReload} actionLabel={zh ? '重试' : 'Retry'} /> : items.length === 0 ? <EmptyState title={zh ? '暂无专线' : 'No circuits'} message={zh ? '请注册线路或调整筛选条件。' : 'Register a circuit or adjust the filters.'} /> : <><WanCircuitTable items={items} selectedId={selectedId} language={language} onSelect={selectCircuit} onEdit={openEdit} /><Pagination currentPage={page} totalItems={total} onPageChange={setPage} itemsPerPage={pageSize} onItemsPerPageChange={(size) => { setPageSize(Math.min(100, Math.max(20, size))); setPage(1); }} language={language} alwaysVisible itemLabel={zh ? '条线路' : 'circuits'} /></>}
          {selectedId && <WanCircuitDetail item={detail || selectedListItem} history={history} sla={sla} language={language} loading={detailLoading} forbidden={detailForbidden} error={detailError} onRetry={triggerReload} historyLoading={detailLoading} slaLoading={detailLoading} historyError={historyError} slaError={slaError} onSaveSlaPolicy={saveSlaPolicy} savingSlaPolicy={savingSlaPolicy} />}
          {selectedId && detail && <WanProbeBindingsPanel linkId={selectedId} language={language} canEdit={canEditWan} showToast={showToast} />}
          {!detailLoading && selectedListItem && (historyError || slaError) && <div className="rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2 text-xs text-amber-800">{historyError && <span>{historyError}</span>}{historyError && slaError && <span> · </span>}{slaError && <span>{slaError}</span>}</div>}
        </>}
      </main>
      {formItem !== undefined && <WanCircuitForm item={formItem} options={options} language={language} saving={saving} onRefreshDeviceInterfaces={refreshDeviceInterfaces} onSubmit={saveCircuit} onClose={() => setFormItem(undefined)} />}
    </div>
  );
};

export default WanCircuitsPage;
