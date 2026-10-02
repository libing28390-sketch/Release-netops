import React, { useCallback, useEffect, useState } from 'react';
import { Activity, AlertCircle, Eye, Hash, RefreshCw, ShieldCheck } from 'lucide-react';
import { getKnowledgeRetrievalTrace, listKnowledgeRetrievalTraces, type KnowledgeRetrievalTrace } from '../../../api/ai';

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Retrieval Trace 请求失败';
}

function shortHash(value: string | null | undefined): string {
  const text = String(value || '');
  return text ? `${text.slice(0, 12)}…` : '--';
}

const traceStatusLabel: Record<string, string> = {
  hit: '已命中',
  no_match: '未命中',
};

export const RetrievalTracePanel: React.FC = () => {
  const [status, setStatus] = useState('all');
  const [items, setItems] = useState<KnowledgeRetrievalTrace[]>([]);
  const [selected, setSelected] = useState<KnowledgeRetrievalTrace | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const result = await listKnowledgeRetrievalTraces(status, 50);
      setItems(result.items || []);
      setSelected((current) => current && result.items.some((item) => item.trace_id === current.trace_id) ? current : (result.items[0] || null));
    } catch (cause) {
      setError(errorMessage(cause));
      setItems([]);
      setSelected(null);
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => { void load(); }, [load]);

  const select = async (item: KnowledgeRetrievalTrace) => {
    setSelected(item);
    try {
      setSelected(await getKnowledgeRetrievalTrace(item.trace_id));
    } catch (cause) {
      setError(errorMessage(cause));
    }
  };

  return (
    <div className="mx-auto w-full space-y-5 text-slate-900 dark:text-slate-100">
      <section className="rounded-3xl border border-indigo-100 bg-gradient-to-br from-indigo-50 via-white to-violet-50 p-6 shadow-sm dark:border-indigo-900/60 dark:from-indigo-950/40 dark:via-slate-900 dark:to-violet-950/30">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-2 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.18em] text-indigo-600"><Activity className="h-4 w-4" />Retrieval Trace · KUI-017</div>
            <h1 className="nx-page-title text-slate-900 dark:text-white">检索过程追踪</h1>
            <p className="nx-page-description mt-2 max-w-3xl text-slate-600 dark:text-slate-300">查看一次本地知识检索经过了哪些筛选、产生多少候选文档，以及最终为何命中或未命中。适合排查 Copilot 无引用、答非所问或找不到知识的问题。</p>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-500 dark:text-slate-400">默认脱敏，不展示问题正文、知识片段、SQL、URL、文档 ID 或凭据。</p>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-amber-700 dark:text-amber-300">这是当前服务实例的临时诊断记录，最多保留 200 条，服务重启后清空，不等同于持久审计日志。</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-300"><ShieldCheck className="h-4 w-4" />租户隔离 · 默认脱敏</span>
            <button type="button" onClick={() => void load()} disabled={loading} className="inline-flex items-center gap-2 rounded-xl border border-indigo-200 bg-white px-3 py-2 text-xs font-semibold text-indigo-700 hover:bg-indigo-50 disabled:opacity-50 dark:border-indigo-800 dark:bg-slate-900 dark:text-indigo-300 dark:hover:bg-indigo-950/40"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />刷新</button>
          </div>
        </div>
      </section>

      {error && <div role="alert" className="flex items-center gap-2 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-300"><AlertCircle className="h-4 w-4" />{error}</div>}

      <section className="grid gap-4 lg:grid-cols-[0.8fr_1.2fr]">
        <article className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-bold text-slate-900 dark:text-white">最近检索记录</h2>
            <select value={status} onChange={(event) => setStatus(event.target.value)} className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200" aria-label="检索状态">
              <option value="all">全部状态</option><option value="hit">已命中</option><option value="no_match">未命中</option>
            </select>
          </div>
          {loading && !items.length ? (
            <p className="rounded-xl bg-slate-50 p-8 text-center text-sm text-slate-500 dark:bg-slate-800/70">正在加载检索记录…</p>
          ) : items.length ? (
            <div className="space-y-2">{items.map((item) => (
              <button type="button" key={item.trace_id} onClick={() => void select(item)} className={`w-full rounded-xl border p-3 text-left transition ${selected?.trace_id === item.trace_id ? 'border-indigo-300 bg-indigo-50 dark:border-indigo-800 dark:bg-indigo-950/40' : 'border-slate-200 hover:border-indigo-200 hover:bg-slate-50 dark:border-slate-800 dark:hover:border-indigo-800 dark:hover:bg-slate-800/70'}`}>
                <div className="flex items-center justify-between gap-2"><span className="font-mono text-xs font-semibold text-slate-800 dark:text-slate-200">{shortHash(item.trace_id)}</span><span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${item.status === 'hit' ? 'bg-emerald-100 text-emerald-700' : item.status === 'no_match' ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-600'}`}>{traceStatusLabel[item.status] || item.status}</span></div>
                <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-500"><span>{item.created_at}</span><span>候选文档 {item.candidate_count}</span><span>最终采用 {item.final_document_count}</span></div>
              </button>
            ))}</div>
          ) : (
            <div className="rounded-xl bg-slate-50 p-8 text-center text-sm text-slate-500 dark:bg-slate-800/70"><Eye className="mx-auto mb-2 h-6 w-6 text-slate-300" />暂无检索记录；先在 Copilot 中提问，或执行一次本地检索。</div>
          )}
        </article>

        <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          {selected ? <>
            <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
              <div><h2 className="text-sm font-bold text-slate-900 dark:text-white">检索详情</h2><p className="mt-1 font-mono text-[11px] text-slate-500">{selected.trace_id}</p></div>
              <span className="inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-semibold text-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-300"><Hash className="h-3.5 w-3.5" />问题摘要 {shortHash(selected.query_hash)}</span>
            </div>
            <div className="grid gap-2 sm:grid-cols-4">{[
              ['元数据候选', selected.metadata_candidate_documents],
              ['检索候选', selected.candidate_count],
              ['去重文档', selected.dedup_document_count],
              ['最终采用', selected.final_document_count],
            ].map(([label, value]) => <div key={String(label)} className="rounded-xl bg-slate-50 p-3 dark:bg-slate-800/70"><div className="text-[11px] text-slate-500">{label}</div><div className="mt-1 text-xl font-bold text-slate-800 dark:text-slate-100">{String(value)}</div></div>)}</div>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div className="rounded-xl border border-slate-100 p-3 dark:border-slate-800"><h3 className="mb-2 text-xs font-bold text-slate-700 dark:text-slate-200">实体与解析</h3><dl className="space-y-1.5 text-[11px]">{Object.entries(selected.request || {}).map(([key, value]) => <div key={key} className="flex justify-between gap-2"><dt className="text-slate-500">{key}</dt><dd className="text-right font-medium text-slate-800 dark:text-slate-200">{String(value ?? '—')}</dd></div>)}<div className="flex justify-between gap-2"><dt className="text-slate-500">是否存在歧义</dt><dd className="font-medium text-slate-800 dark:text-slate-200">{selected.resolution?.ambiguous ? '是' : '否'}</dd></div><div className="flex justify-between gap-2"><dt className="text-slate-500">平台候选</dt><dd className="text-right font-medium text-slate-800 dark:text-slate-200">{selected.resolution?.platform_candidates?.join('、') || '无'}</dd></div></dl></div>
              <div className="rounded-xl border border-slate-100 p-3 dark:border-slate-800"><h3 className="mb-2 text-xs font-bold text-slate-700 dark:text-slate-200">检索阶段</h3><dl className="space-y-1.5 text-[11px]"><div className="flex justify-between gap-2"><dt className="text-slate-500">检索来源</dt><dd className="font-medium text-slate-800 dark:text-slate-200">{selected.source}</dd></div><div className="flex justify-between gap-2"><dt className="text-slate-500">向量候选上限</dt><dd className="font-medium text-slate-800 dark:text-slate-200">{selected.vector_top_n}</dd></div><div className="flex justify-between gap-2"><dt className="text-slate-500">需要澄清</dt><dd className="font-medium text-slate-800 dark:text-slate-200">{selected.clarification_required ? '是' : '否'}</dd></div><div className="flex justify-between gap-2"><dt className="text-slate-500">跨平台检索</dt><dd className="font-medium text-slate-800 dark:text-slate-200">{selected.cross_platform_search ? '是' : '否'}</dd></div></dl></div>
            </div>
            <div className="mt-4 rounded-xl border border-slate-100 p-3 dark:border-slate-800"><div className="mb-2 flex items-center justify-between"><h3 className="text-xs font-bold text-slate-700 dark:text-slate-200">引用摘要</h3><span className="text-[11px] text-slate-500">告警 {selected.citation_warning_count}</span></div>{selected.citations?.length ? <div className="grid gap-2 sm:grid-cols-2">{selected.citations.map((citation) => <div key={citation.citation_id} className="rounded-lg bg-slate-50 p-2.5 text-[11px] dark:bg-slate-800/70"><div className="flex justify-between gap-2"><span className="font-mono text-slate-700 dark:text-slate-200">{shortHash(citation.citation_id)}</span><span className="text-slate-500">{citation.validation}</span></div><div className="mt-1 text-slate-600 dark:text-slate-300">{citation.vendor || '厂商未指定'} · {citation.product || '产品未指定'} · {citation.software_version || '版本未指定'}</div></div>)}</div> : <p className="text-xs text-slate-500">本次检索没有可用引用。</p>}</div>
            <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-[11px] leading-5 text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-300">默认脱敏：问题和知识片段正文、SQL、URL、文档及片段 ID、凭据均不会进入此查看器；问题仅显示 SHA-256 摘要。</div>
          </> : <div className="flex min-h-[340px] items-center justify-center rounded-xl bg-slate-50 text-sm text-slate-500 dark:bg-slate-800/70">选择一条检索记录查看安全摘要。</div>}
        </article>
      </section>
    </div>
  );
};

export default RetrievalTracePanel;
