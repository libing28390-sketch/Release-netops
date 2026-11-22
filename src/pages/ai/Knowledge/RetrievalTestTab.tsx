import React, { useState } from 'react';
import { ChevronDown, ChevronUp, LoaderCircle, Play, Search, ShieldCheck, SlidersHorizontal, Sparkles } from 'lucide-react';
import { runKnowledgeRetrievalTest, type RetrievalTestResult } from '../../../api/ai';

const VENDOR_OPTIONS = ['', 'Huawei', 'H3C', 'Cisco', 'Ruijie', 'Juniper', 'Fortinet', 'Aruba'];
const CATEGORY_OPTIONS = [
  { value: '', label: '全部类别' },
  { value: 'configuration', label: '配置指南 (configuration)' },
  { value: 'command_reference', label: '命令参考 (command_reference)' },
  { value: 'troubleshooting', label: '故障排查 (troubleshooting)' },
  { value: 'hardware', label: '硬件/产品目录 (hardware)' },
  { value: 'sop', label: '企业 SOP (sop)' },
];

export const RetrievalTestTab: React.FC = () => {
  const [query, setQuery] = useState('display ospf peer');
  const [vendor, setVendor] = useState('Huawei');
  const [productModel, setProductModel] = useState('');
  const [cliPlatform, setCliPlatform] = useState('');
  const [documentCategory, setDocumentCategory] = useState('');
  const [showAdvancedJson, setShowAdvancedJson] = useState(false);
  const [filtersText, setFiltersText] = useState('{}');
  const [result, setResult] = useState<RetrievalTestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const run = async (event: React.FormEvent | React.KeyboardEvent<HTMLInputElement>) => {
    event.preventDefault();
    if (!query.trim() || loading) return;
    setError('');
    let extraFilters: Record<string, unknown> = {};
    if (showAdvancedJson && filtersText.trim()) {
      try {
        const parsed = JSON.parse(filtersText);
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
          throw new Error('高级过滤条件必须是 JSON 对象');
        }
        extraFilters = parsed as Record<string, unknown>;
      } catch (err: any) {
        setError(err?.message || '高级过滤条件 JSON 格式无效');
        return;
      }
    }
    const filters: Record<string, unknown> = { ...extraFilters };
    if (vendor.trim()) filters.vendor = vendor.trim();
    if (productModel.trim()) filters.product_model = productModel.trim();
    if (cliPlatform.trim()) filters.cli_platform = cliPlatform.trim();
    if (documentCategory.trim()) filters.document_category = documentCategory.trim();

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
    <div className="w-full space-y-5 pb-8">
      <section className="relative overflow-hidden rounded-[26px] border border-indigo-100/80 bg-gradient-to-br from-white via-indigo-50/70 to-violet-100/70 p-6 shadow-sm dark:border-indigo-900/60 dark:from-slate-900 dark:via-indigo-950/50 dark:to-slate-900">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-indigo-200/80 bg-white/75 px-3 py-1 text-[11px] font-bold uppercase tracking-[0.18em] text-indigo-600 dark:border-indigo-800 dark:bg-indigo-950/50 dark:text-indigo-300">
              <Sparkles className="h-3.5 w-3.5" /> RAG Retrieval Sandbox
            </div>
            <h1 className="nx-page-title text-slate-950 dark:text-white">管理员检索测试沙箱</h1>
            <p className="nx-page-description mt-2 max-w-3xl text-slate-600 dark:text-slate-300">
              可视化调试 Query 实体解析、Metadata 硬过滤、候选产品归属、分块召回打分与 PostgreSQL 检索阶段。页面严格屏蔽密钥与原始 SQL。
            </p>
          </div>
          <div className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50/90 px-3.5 py-2 text-xs font-semibold text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-300">
            <ShieldCheck className="h-4 w-4" /> 权限与租户由服务端强制绑定
          </div>
        </div>
      </section>

      <form onSubmit={run} className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <div className="flex flex-col gap-3 sm:flex-row">
          <div className="flex flex-1 items-center gap-2.5 rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2.5 focus-within:border-indigo-400 focus-within:ring-2 focus-within:ring-indigo-500/15 dark:border-slate-700 dark:bg-slate-950">
            <Search className="h-4 w-4 shrink-0 text-slate-400" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                  void run(event);
                }
              }}
              className="w-full bg-transparent text-sm text-slate-900 outline-none placeholder:text-slate-400 dark:text-white"
              placeholder="输入测试查询，例如：Huawei CE6885 display ospf peer"
            />
          </div>
          <button
            type="submit"
            disabled={loading || !query.trim()}
            className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {loading ? '检索中...' : '执行检索测试'}
          </button>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="block">
            <span className="mb-1 block text-[11px] font-semibold text-slate-500 dark:text-slate-400">厂商过滤 (Vendor)</span>
            <select
              value={vendor}
              onChange={(e) => setVendor(e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-800 outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
            >
              {VENDOR_OPTIONS.map((v) => (
                <option key={v || 'all'} value={v}>{v || '全部厂商'}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] font-semibold text-slate-500 dark:text-slate-400">产品型号 (Model)</span>
            <input
              value={productModel}
              onChange={(e) => setProductModel(e.target.value)}
              placeholder="如 CE6885-48YS8CQ"
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-800 outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] font-semibold text-slate-500 dark:text-slate-400">CLI 平台 (Platform)</span>
            <input
              value={cliPlatform}
              onChange={(e) => setCliPlatform(e.target.value)}
              placeholder="如 huawei_vrp / cisco_iosxe"
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 font-mono text-xs text-slate-800 outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] font-semibold text-slate-500 dark:text-slate-400">文档类别 (Category)</span>
            <select
              value={documentCategory}
              onChange={(e) => setDocumentCategory(e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-800 outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
            >
              {CATEGORY_OPTIONS.map((opt) => (
                <option key={opt.value || 'all'} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </label>
        </div>

        <div className="border-t border-slate-100 pt-3 dark:border-slate-800">
          <button
            type="button"
            onClick={() => setShowAdvancedJson((v) => !v)}
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500 transition hover:text-indigo-600 dark:text-slate-400 dark:hover:text-indigo-300"
          >
            <SlidersHorizontal className="h-3.5 w-3.5" />
            高级 JSON 过滤扩展
            {showAdvancedJson ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          </button>
          {showAdvancedJson && (
            <textarea
              value={filtersText}
              onChange={(event) => setFiltersText(event.target.value)}
              className="mt-2 h-24 w-full resize-y rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 font-mono text-xs text-slate-800 outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"
              placeholder='{"feature": "ospf", "knowledge_scope": "official"}'
            />
          )}
        </div>
      </form>

      {error && (
        <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-300">
          {error}
        </div>
      )}

      {result && (
        <div className="grid gap-4 xl:grid-cols-[0.85fr_1.15fr]">
          <div className="space-y-4">
            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
              <h2 className="mb-3 text-sm font-bold text-slate-900 dark:text-white">实体与硬过滤状态</h2>
              <dl className="space-y-2 text-xs">
                {Object.entries(result.entities || {})
                  .filter(([, value]) => value !== null && value !== '' && value !== undefined)
                  .map(([key, value]) => (
                    <div key={key} className="flex justify-between gap-3 border-b border-slate-100 pb-2 dark:border-slate-800">
                      <dt className="font-mono text-slate-500 dark:text-slate-400">{key}</dt>
                      <dd className="max-w-[65%] break-words text-right font-medium text-slate-800 dark:text-slate-200">
                        {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                      </dd>
                    </div>
                  ))}
              </dl>
            </section>

            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
              <h2 className="mb-3 text-sm font-bold text-slate-900 dark:text-white">产品解析候选</h2>
              <div className="mb-3 flex flex-wrap gap-2 text-xs">
                <span className="rounded-full bg-slate-100 px-2.5 py-1 font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-300">
                  结果：{result.resolution?.outcome || 'unknown'}
                </span>
                <span className={`rounded-full px-2.5 py-1 font-semibold ${result.resolution?.ambiguous ? 'bg-amber-100 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300' : 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300'}`}>
                  {result.resolution?.ambiguous ? '需要澄清' : '唯一/可检索'}
                </span>
              </div>
              <pre className="max-h-64 overflow-auto rounded-xl bg-slate-950 p-3 text-[11px] leading-5 text-slate-200">
                {JSON.stringify(result.resolution?.candidates || [], null, 2)}
              </pre>
            </section>
          </div>

          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-bold text-slate-900 dark:text-white">
                最终命中 Chunk（{result.final_chunks?.length || 0}）
              </h2>
              <span className="rounded-lg bg-slate-100 px-2.5 py-1 font-mono text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                {result.debug?.fts_stage === 'disabled' && result.debug?.vector_stage === 'disabled'
                  ? '精准规则与词法检索'
                  : `FTS: ${String(result.debug?.fts_stage || 'off')} · 向量: ${String(result.debug?.vector_stage || 'off')}`}
              </span>
            </div>

            {result.final_chunks?.length ? (
              <div className="space-y-3">
                {result.final_chunks.map((item) => (
                  <article key={item.chunk_id} className="rounded-xl border border-slate-200 bg-slate-50/40 p-4 transition hover:border-indigo-200 dark:border-slate-800 dark:bg-slate-950/40 dark:hover:border-indigo-800">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <p className="text-sm font-semibold text-slate-900 dark:text-white">
                          {item.document_name || item.document_id}
                        </p>
                        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                          {item.section || 'General'} · {item.platform || '平台未指定'} · {item.version_evidence || '版本证据未请求'}
                        </p>
                      </div>
                      <span className="rounded-full bg-indigo-50 px-2.5 py-1 font-mono text-xs font-bold text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-300">
                        Score {Number(item.score || 0).toFixed(3)}
                      </span>
                    </div>
                    {item.score_components && typeof item.score_components === 'object' && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {Object.entries(item.score_components)
                          .filter(([, val]) => typeof val === 'number')
                          .map(([k, val]) => (
                            <span key={k} className="rounded-md bg-white px-2 py-0.5 font-mono text-[10px] text-slate-600 ring-1 ring-slate-200 dark:bg-slate-900 dark:text-slate-300 dark:ring-slate-700">
                              {k}: {Number(val).toFixed(2)}
                            </span>
                          ))}
                      </div>
                    )}
                    <pre className="mt-3 max-h-52 overflow-auto whitespace-pre-wrap rounded-lg border border-slate-100 bg-white p-3 text-xs leading-5 text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200">
                      {item.content}
                    </pre>
                  </article>
                ))}
              </div>
            ) : (
              <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-10 text-center text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-950/50 dark:text-slate-400">
                没有满足硬过滤和证据门槛的 Chunk。请调整过滤条件或查询词重试。
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
};

export default RetrievalTestTab;
