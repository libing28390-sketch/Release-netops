import { useEffect, useState } from 'react';
import { ChevronRight, Loader2, RefreshCw } from 'lucide-react';

type CorrelationSummary = { id: string; root_cause_code: string; severity: string; status: string; confidence?: number; title: string; summary?: string; starts_at: string; link_name?: string; site_name?: string; provider?: string };
type CorrelationDetail = CorrelationSummary & { scope?: Record<string, unknown>; evidence?: Array<{ observed_at?: string; source_type?: string; metric?: string; details?: Record<string, unknown> }> };
type LinkOption = { id: string; link_name: string; site_id?: string; site_name?: string; provider?: string };
const headers = () => { const token = localStorage.getItem('netops_token'); return token ? { Authorization: `Bearer ${token}` } : {}; };

const WanCorrelationEvidencePanel: React.FC = () => {
  const [items, setItems] = useState<CorrelationSummary[]>([]);
  const [links, setLinks] = useState<LinkOption[]>([]);
  const [selected, setSelected] = useState<CorrelationDetail | null>(null);
  const [status, setStatus] = useState('');
  const [severity, setSeverity] = useState('');
  const [siteId, setSiteId] = useState('');
  const [provider, setProvider] = useState('');
  const [keyword, setKeyword] = useState('');
  const [startAt, setStartAt] = useState('');
  const [endAt, setEndAt] = useState('');
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true); setError('');
    try {
      const query = new URLSearchParams({ page: String(page), page_size: '20' });
      if (status) query.set('status', status); if (severity) query.set('severity', severity); if (siteId) query.set('site_id', siteId); if (provider) query.set('provider', provider); if (keyword.trim()) query.set('keyword', keyword.trim()); if (startAt) query.set('start_at', new Date(startAt).toISOString()); if (endAt) query.set('end_at', new Date(endAt).toISOString());
      const response = await fetch(`/api/monitoring/wan-correlations?${query}`, { headers: headers() });
      if (!response.ok) throw new Error('关联事件加载失败');
      const payload = await response.json(); setItems(payload.items || []); setPages(Math.max(1, Number(payload.pages || 1)));
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); } finally { setLoading(false); }
  };

  useEffect(() => { void load(); }, [page, status, severity, siteId, provider, keyword, startAt, endAt]);
  useEffect(() => { const controller = new AbortController(); void fetch('/api/monitoring/wan-links?page_size=100', { headers: headers(), signal: controller.signal }).then((response) => response.ok ? response.json() : { items: [] }).then((body) => { if (!controller.signal.aborted) setLinks(body.items || []); }).catch(() => undefined); return () => controller.abort(); }, []);

  const selectEvent = async (id: string) => {
    setDetailLoading(true); setError('');
    try { const response = await fetch(`/api/monitoring/wan-correlations/${encodeURIComponent(id)}`, { headers: headers() }); if (!response.ok) throw new Error('关联证据加载失败'); setSelected((await response.json()).item); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); } finally { setDetailLoading(false); }
  };
  const resetPage = () => setPage(1);
  const providers = Array.from(new Set(links.map((link) => link.provider).filter(Boolean))) as string[];
  const sites = Array.from(new Map(links.filter((link) => link.site_id).map((link) => [link.site_id, link.site_name || link.site_id])).entries());

  return <section className="mt-4 rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-4 shadow-sm md:p-5"><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-[10px] font-bold uppercase tracking-[0.18em] text-violet-600">Evidence timeline</p><h2 className="mt-1 text-lg font-extrabold text-[var(--app-text)]">关联事件与证据链</h2><p className="mt-1 text-xs text-[var(--muted-text)]">服务端筛选事件，按需查看采集、探测、路由与容量证据。</p></div><div className="flex flex-wrap gap-2"><select value={status} onChange={(event) => { setStatus(event.target.value); resetPage(); }} className="rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-2 text-xs"><option value="">全部状态</option><option value="open">打开</option><option value="acknowledged">已确认</option><option value="resolved">已恢复</option></select><select value={severity} onChange={(event) => { setSeverity(event.target.value); resetPage(); }} className="rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-2 text-xs"><option value="">全部风险</option><option value="critical">严重</option><option value="major">重要</option><option value="warning">警告</option></select><select value={siteId} onChange={(event) => { setSiteId(event.target.value); resetPage(); }} className="rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-2 text-xs"><option value="">全部站点</option>{sites.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select><select value={provider} onChange={(event) => { setProvider(event.target.value); resetPage(); }} className="rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-2 text-xs"><option value="">全部运营商</option>{providers.map((item) => <option key={item} value={item}>{item}</option>)}</select><input value={startAt} onChange={(event) => { setStartAt(event.target.value); resetPage(); }} type="datetime-local" aria-label="开始时间" className="w-40 rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-2 text-xs" /><input value={endAt} onChange={(event) => { setEndAt(event.target.value); resetPage(); }} type="datetime-local" aria-label="结束时间" className="w-40 rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-2 text-xs" /><input value={keyword} onChange={(event) => { setKeyword(event.target.value); resetPage(); }} placeholder="搜索根因/链路" className="w-32 rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-2 text-xs" /><button type="button" onClick={() => void load()} className="rounded-lg border border-[var(--card-border)] p-2 text-[var(--muted-text)]" aria-label="刷新证据"><RefreshCw size={14} /></button></div></div>{error && <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</div>}{loading ? <div className="flex min-h-24 items-center justify-center text-sm text-[var(--muted-text)]"><Loader2 className="mr-2 animate-spin" size={16} />加载中…</div> : <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]"><div className="space-y-2">{items.length ? items.map((item) => <button key={item.id} type="button" onClick={() => void selectEvent(item.id)} className={`flex w-full items-center justify-between gap-3 rounded-xl border px-3 py-2 text-left ${selected?.id === item.id ? 'border-violet-400 bg-violet-50' : 'border-[var(--card-border)] hover:border-violet-300'}`}><span className="min-w-0"><span className="block truncate text-xs font-bold text-[var(--app-text)]">{item.title}</span><span className="mt-1 block text-[10px] text-[var(--muted-text)]">{item.root_cause_code} · {item.status} · {item.site_name || '--'} · {Math.round(Number(item.confidence || 0) * 100)}%</span></span><ChevronRight size={14} className="shrink-0 text-[var(--muted-text)]" /></button>) : <p className="rounded-xl border border-dashed border-[var(--card-border)] px-3 py-5 text-center text-xs text-[var(--muted-text)]">暂无关联事件</p>}<div className="flex items-center justify-end gap-2"><button type="button" disabled={page <= 1} onClick={() => setPage((value) => value - 1)} className="rounded border border-[var(--card-border)] px-2 py-1 text-[10px] disabled:opacity-40">上一页</button><span className="text-[10px] text-[var(--muted-text)]">{page}/{pages}</span><button type="button" disabled={page >= pages} onClick={() => setPage((value) => value + 1)} className="rounded border border-[var(--card-border)] px-2 py-1 text-[10px] disabled:opacity-40">下一页</button></div></div><div className="rounded-xl border border-[var(--card-border)] p-3">{detailLoading ? <div className="flex min-h-24 items-center justify-center text-sm text-[var(--muted-text)]"><Loader2 className="mr-2 animate-spin" size={16} />加载证据中…</div> : selected ? <><div className="flex flex-wrap items-center justify-between gap-2"><div><p className="text-sm font-extrabold text-[var(--app-text)]">{selected.title}</p><p className="mt-1 text-[10px] text-[var(--muted-text)]">{selected.summary || '--'} · {selected.starts_at}</p></div><span className="rounded-md bg-violet-50 px-2 py-1 text-[10px] font-bold text-violet-700">{selected.status}</span></div><p className="mt-3 break-words text-[10px] font-bold text-[var(--muted-text)]">范围：{selected.scope ? JSON.stringify(selected.scope) : '--'}</p><div className="mt-3 space-y-2">{selected.evidence?.length ? selected.evidence.map((evidence, index) => <div key={`${evidence.observed_at || 'evidence'}-${index}`} className="rounded-lg bg-black/[0.03] px-3 py-2"><div className="flex flex-wrap justify-between gap-2 text-[10px] font-bold text-[var(--app-text)]"><span>{evidence.source_type || 'evidence'} · {evidence.metric || '--'}</span><span>{evidence.observed_at || '--'}</span></div><p className="mt-1 break-words text-[10px] text-[var(--muted-text)]">{evidence.details ? JSON.stringify(evidence.details) : '--'}</p></div>) : <p className="text-xs text-[var(--muted-text)]">暂无明细证据</p>}</div></> : <p className="flex min-h-24 items-center justify-center text-xs text-[var(--muted-text)]">选择左侧事件查看证据时间线</p>}</div></div>}</section>;
};

export default WanCorrelationEvidencePanel;
