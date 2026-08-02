import { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw } from 'lucide-react';

type WanAlertEvent = { id: string; link_name?: string; site_name?: string; provider?: string; title: string; message?: string; severity: string; status: string; metric_value?: number | null; threshold_value?: number | null; direction?: string; started_at: string; last_seen_at?: string; recovered_at?: string | null };
type LinkOption = { id: string; link_name: string };
const headers = () => { const token = localStorage.getItem('netops_token'); return token ? { Authorization: `Bearer ${token}` } : {}; };

const WanAlertEventsPanel: React.FC = () => {
  const [items, setItems] = useState<WanAlertEvent[]>([]);
  const [links, setLinks] = useState<LinkOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [severity, setSeverity] = useState('');
  const [linkId, setLinkId] = useState('');
  const [keyword, setKeyword] = useState('');
  const [pageSize, setPageSize] = useState(20);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);

  const load = async (signal?: AbortSignal) => {
    setLoading(true); setError('');
    try {
      const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
      if (status) query.set('status', status); if (severity) query.set('severity', severity); if (linkId) query.set('link_id', linkId); if (keyword.trim()) query.set('keyword', keyword.trim());
      const response = await fetch(`/api/monitoring/wan-alert-events?${query}`, { headers: headers(), signal });
      if (!response.ok) throw new Error(response.status === 403 ? '权限不足' : '告警事件加载失败');
      const body = await response.json();
      if (!signal?.aborted) { setItems(body.items || []); setPages(Math.max(1, Number(body.pages || 1))); }
    } catch (cause) { if ((cause as Error)?.name !== 'AbortError') setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { if (!signal?.aborted) setLoading(false); }
  };

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [page, pageSize, status, severity, linkId, keyword]);

  useEffect(() => {
    const controller = new AbortController();
    void fetch('/api/monitoring/wan-links?page_size=100', { headers: headers(), signal: controller.signal }).then((response) => response.ok ? response.json() : { items: [] }).then((body) => { if (!controller.signal.aborted) setLinks(body.items || []); }).catch(() => undefined);
    return () => controller.abort();
  }, []);

  const resetPage = () => setPage(1);
  const workflow = async (id: string, action: 'acknowledge' | 'close') => {
    const response = await fetch(`/api/monitoring/wan-alert-events/${encodeURIComponent(id)}`, { method: 'PATCH', headers: { ...headers(), 'Content-Type': 'application/json' }, body: JSON.stringify({ action }) });
    if (response.ok) void load(); else setError('告警处置失败');
  };

  return <section className="rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-4 shadow-sm md:p-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-[10px] font-bold uppercase tracking-[0.18em] text-rose-600">WAN alert events</p><h2 className="mt-1 text-xl font-extrabold text-[var(--app-text)]">出口告警事件</h2><p className="mt-1 text-xs text-[var(--muted-text)]">独立分页、组合筛选、确认和关闭审计</p></div><div className="flex flex-wrap gap-2"><select value={status} onChange={(event) => { setStatus(event.target.value); resetPage(); }} className="rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-2 text-xs"><option value="">全部状态</option><option value="firing">告警中</option><option value="acknowledged">已确认</option><option value="resolved">已恢复</option><option value="closed">已关闭</option></select><select value={severity} onChange={(event) => { setSeverity(event.target.value); resetPage(); }} className="rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-2 text-xs"><option value="">全部级别</option><option value="critical">严重</option><option value="major">重要</option><option value="warning">警告</option></select><select value={linkId} onChange={(event) => { setLinkId(event.target.value); resetPage(); }} className="max-w-40 rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-2 text-xs"><option value="">全部链路</option>{links.map((link) => <option key={link.id} value={link.id}>{link.link_name}</option>)}</select><input value={keyword} onChange={(event) => { setKeyword(event.target.value); resetPage(); }} placeholder="搜索事件/链路" className="w-32 rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-2 text-xs" /><select value={pageSize} onChange={(event) => { setPageSize(Number(event.target.value)); resetPage(); }} className="rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-2 text-xs"><option value={10}>10条</option><option value={20}>20条</option><option value={50}>50条</option><option value={100}>100条</option></select><button type="button" onClick={() => void load()} className="rounded-lg border border-[var(--card-border)] p-2 text-[var(--muted-text)]" aria-label="刷新"><RefreshCw size={14} /></button></div></div>
    {loading ? <div className="flex min-h-32 items-center justify-center text-sm text-[var(--muted-text)]"><Loader2 className="mr-2 animate-spin" size={16} />加载中…</div> : error ? <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-5 text-sm text-rose-700">{error}<button type="button" onClick={() => void load()} className="ml-3 font-bold underline">重试</button></div> : items.length === 0 ? <div className="mt-4 rounded-xl border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-[var(--muted-text)]">暂无告警事件</div> : <div className="mt-4 space-y-2">{items.map((item) => <article key={item.id} className="rounded-xl border border-[var(--card-border)] px-3 py-3"><div className="flex flex-wrap items-start justify-between gap-2"><div className="flex items-start gap-2"><div className="mt-0.5">{item.status === 'firing' || item.status === 'acknowledged' ? <AlertTriangle size={15} className="text-rose-600" /> : <CheckCircle2 size={15} className="text-emerald-600" />}</div><div><p className="text-sm font-bold text-[var(--app-text)]">{item.title}</p><p className="mt-1 text-xs text-[var(--muted-text)]">{item.link_name || '--'} · {item.site_name || '--'} · {item.provider || '--'} · {item.direction || '双向'}</p><p className="mt-1 text-[11px] text-[var(--muted-text)]">{item.message || '--'} · 触发 {item.metric_value ?? '--'} / {item.threshold_value ?? '--'}</p></div></div><div className="flex items-center gap-2"><span className="rounded-full bg-black/[0.04] px-2 py-1 text-[10px] font-bold">{item.severity} · {item.status}</span>{item.status === 'firing' && <button type="button" onClick={() => void workflow(item.id, 'acknowledge')} className="text-[11px] font-bold text-cyan-700">确认</button>}{!['resolved', 'closed'].includes(item.status) && <button type="button" onClick={() => void workflow(item.id, 'close')} className="text-[11px] font-bold text-rose-700">关闭</button>}</div></div><p className="mt-2 text-[10px] text-[var(--muted-text)]">开始：{new Date(item.started_at).toLocaleString('zh-CN')} · 最近：{item.last_seen_at ? new Date(item.last_seen_at).toLocaleString('zh-CN') : '--'} · 恢复：{item.recovered_at ? new Date(item.recovered_at).toLocaleString('zh-CN') : '--'}</p></article>)}</div>}
    <div className="mt-4 flex items-center justify-end gap-2"><button type="button" disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))} className="rounded-lg border border-[var(--card-border)] px-3 py-1.5 text-xs disabled:opacity-40">上一页</button><span className="px-2 py-1.5 text-xs text-[var(--muted-text)]">第 {page} / {pages} 页</span><button type="button" disabled={page >= pages} onClick={() => setPage((value) => Math.min(pages, value + 1))} className="rounded-lg border border-[var(--card-border)] px-3 py-1.5 text-xs disabled:opacity-40">下一页</button></div>
  </section>;
};

export default WanAlertEventsPanel;
