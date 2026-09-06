import { useEffect, useState } from 'react';

type Recommendation = { id: string; recommendation: string; status: string; confidence?: number; evidence?: Record<string, any> };
const headers = () => { const token = localStorage.getItem('netops_token'); return token ? { Authorization: `Bearer ${token}` } : {}; };

const WanCapacityReviewPanel: React.FC = () => {
  const [items, setItems] = useState<Recommendation[]>([]);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(true);
  const load = async () => { setLoading(true); try { const response = await fetch('/api/monitoring/wan-capacity-recommendations', { headers: headers() }); if (response.ok) setItems((await response.json()).items || []); } finally { setLoading(false); } };
  useEffect(() => { void load(); }, []);
  const review = async (id: string, status: 'observing' | 'review' | 'handled' | 'not_applicable') => { const response = await fetch(`/api/monitoring/wan-capacity-recommendations/${encodeURIComponent(id)}`, { method: 'PATCH', headers: { ...headers(), 'Content-Type': 'application/json' }, body: JSON.stringify({ status, note: notes[id] || '' }) }); setMessage(response.ok ? '容量建议处置状态已更新' : '容量建议更新失败'); if (response.ok) void load(); };
  return <section className="mt-4 rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-4"><div className="flex items-center justify-between"><h3 className="text-sm font-extrabold text-[var(--app-text)]">容量建议处置</h3>{loading ? <span className="text-xs text-[var(--muted-text)]">加载中…</span> : message && <span className="text-xs text-cyan-700">{message}</span>}</div>{items.length ? <div className="mt-3 grid gap-2 md:grid-cols-2">{items.slice(0, 12).map((item) => <article key={item.id} className="rounded-xl border border-[var(--card-border)] px-3 py-3 text-xs"><div className="flex justify-between gap-2"><b>{item.recommendation}</b><span>{item.status}</span></div><p className="mt-1 text-[10px] text-[var(--muted-text)]">{item.evidence?.window_days || '--'}天 · P95 {item.evidence?.p95_utilization_pct ?? '--'}% · 置信度 {item.confidence ?? '--'}</p><textarea value={notes[item.id] || ''} onChange={(event) => setNotes((current) => ({ ...current, [item.id]: event.target.value }))} placeholder="处置备注（可选）" rows={2} className="mt-2 w-full rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-1.5 text-[11px]" /><div className="mt-2 flex flex-wrap gap-2"><button type="button" onClick={() => void review(item.id, 'observing')} className="font-bold text-cyan-700">观察</button><button type="button" onClick={() => void review(item.id, 'review')} className="font-bold text-amber-700">计划评估</button><button type="button" onClick={() => void review(item.id, 'handled')} className="font-bold text-emerald-700">已处理</button><button type="button" onClick={() => void review(item.id, 'not_applicable')} className="font-bold text-slate-600">不适用</button></div></article>)}</div> : <p className="mt-3 text-xs text-[var(--muted-text)]">暂无容量建议</p>}</section>;
};

export default WanCapacityReviewPanel;
