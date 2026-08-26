import React, { useState } from 'react';
import { Search, ShieldCheck, SlidersHorizontal, Sparkles } from 'lucide-react';
import { runKnowledgeRetrievalTest, type RetrievalTestResult } from '../../../api/ai';

export const RetrievalTestTab: React.FC = () => {
  const [query, setQuery] = useState('display ospf peer');
  const [filtersText, setFiltersText] = useState('{\n  "vendor": "Huawei"\n}');
  const [result, setResult] = useState<RetrievalTestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const run = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');
    let filters: Record<string, unknown> = {};
    try {
      const parsed = JSON.parse(filtersText || '{}');
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('过滤条件必须是 JSON 对象');
      filters = parsed as Record<string, unknown>;
    } catch (err: any) {
      setError(err?.message || '过滤条件 JSON 无效');
      return;
    }
    setLoading(true);
    try {
      setResult(await runKnowledgeRetrievalTest(query.trim(), filters));
    } catch (err: any) {
      setError(err?.message || '检索测试失败');
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto w-full max-w-6xl space-y-5">
      <section className="rounded-3xl border border-indigo-100 bg-gradient-to-br from-indigo-50 via-white to-violet-50 p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-2 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.18em] text-indigo-600"><Sparkles className="h-4 w-4" /> RET-021</div>
            <h1 className="nx-page-title text-slate-900">管理员检索测试</h1>
            <p className="nx-page-description mt-2 max-w-3xl text-slate-600">查看 Query 实体解析、Metadata 硬过滤、候选产品、最终 Chunk、版本证据和 PostgreSQL 检索阶段。页面不显示 Provider 密钥或原始 SQL。</p>
          </div>
          <div className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-700"><ShieldCheck className="h-4 w-4" /> 权限与租户由服务端绑定</div>
        </div>
      </section>

      <form onSubmit={run} className="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm lg:grid-cols-[1.4fr_1fr_auto]">
        <label className="block"><span className="mb-1.5 block text-xs font-bold text-slate-600">查询</span><div className="flex items-center gap-2 rounded-xl border border-slate-200 px-3 py-2"><Search className="h-4 w-4 text-slate-400" /><input value={query} onChange={(event) => setQuery(event.target.value)} className="w-full bg-transparent text-sm outline-none" placeholder="例如：Huawei CE6885 show ospf peer" /></div></label>
        <label className="block"><span className="mb-1.5 flex items-center gap-1 text-xs font-bold text-slate-600"><SlidersHorizontal className="h-3.5 w-3.5" />过滤条件 JSON</span><textarea value={filtersText} onChange={(event) => setFiltersText(event.target.value)} className="h-20 w-full resize-y rounded-xl border border-slate-200 px-3 py-2 font-mono text-xs outline-none focus:border-indigo-400" /></label>
        <button type="submit" disabled={loading || !query.trim()} className="self-end rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50">{loading ? '检索中…' : '执行检索'}</button>
      </form>

      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}
      {result && <div className="grid gap-4 xl:grid-cols-[0.85fr_1.15fr]">
        <div className="space-y-4">
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><h2 className="mb-3 text-sm font-bold text-slate-900">实体与过滤</h2><dl className="space-y-2 text-xs">{Object.entries(result.entities || {}).filter(([, value]) => value !== null && value !== '' && value !== undefined).map(([key, value]) => <div key={key} className="flex justify-between gap-3 border-b border-slate-100 pb-2"><dt className="text-slate-500">{key}</dt><dd className="max-w-[65%] break-words text-right font-medium text-slate-800">{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}</dl></section>
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><h2 className="mb-3 text-sm font-bold text-slate-900">解析候选</h2><div className="mb-3 flex flex-wrap gap-2 text-xs"><span className="rounded-full bg-slate-100 px-2.5 py-1">结果：{result.resolution?.outcome || 'unknown'}</span><span className={`rounded-full px-2.5 py-1 ${result.resolution?.ambiguous ? 'bg-amber-100 text-amber-700' : 'bg-emerald-100 text-emerald-700'}`}>{result.resolution?.ambiguous ? '需要澄清' : '唯一/可检索'}</span></div><pre className="max-h-64 overflow-auto rounded-xl bg-slate-950 p-3 text-[11px] leading-5 text-slate-200">{JSON.stringify(result.resolution?.candidates || [], null, 2)}</pre></section>
        </div>
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><div className="mb-3 flex items-center justify-between"><h2 className="text-sm font-bold text-slate-900">最终 Chunk（{result.final_chunks?.length || 0}）</h2><span className="text-xs text-slate-500">{String(result.debug?.fts_stage || '')} · {String(result.debug?.vector_stage || '')}</span></div>{result.final_chunks?.length ? <div className="space-y-3">{result.final_chunks.map((item) => <article key={item.chunk_id} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div><p className="text-sm font-semibold text-slate-900">{item.document_name || item.document_id}</p><p className="mt-1 text-xs text-slate-500">{item.section || 'General'} · {item.platform || '平台未指定'} · {item.version_evidence || '版本证据未请求'}</p></div><span className="rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-bold text-indigo-700">{Number(item.score || 0).toFixed(3)}</span></div><pre className="mt-3 max-h-52 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-xs leading-5 text-slate-700">{item.content}</pre></article>)}</div> : <div className="rounded-xl bg-slate-50 p-8 text-center text-sm text-slate-500">没有满足硬过滤和证据门槛的 Chunk。</div>}</section>
      </div>}
    </div>
  );
};

export default RetrievalTestTab;
