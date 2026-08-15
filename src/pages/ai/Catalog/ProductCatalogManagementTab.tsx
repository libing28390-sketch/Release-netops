import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  Eye,
  Filter,
  Layers,
  Loader2,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Tag,
} from 'lucide-react';
import {
  getKnowledgeCatalog,
  getKnowledgeCatalogAliases,
  resolveKnowledgeCatalogAlias,
  type KnowledgeCatalogAlias,
  type KnowledgeCatalogModel,
  type KnowledgeCatalogResolveResponse,
} from '../../../api/ai';

type CatalogPanel = 'models' | 'aliases';

const KIND_LABELS: Record<string, string> = {
  exact: 'Exact',
  canonical: 'Canonical',
  prefix: 'Prefix',
  trigram: 'Trigram',
};

function scopeValue(model: KnowledgeCatalogModel | undefined, key: string): string {
  return String(model?.software_scope?.[key] ?? '—');
}

function statusTone(status: string): string {
  if (status === 'active' || status === 'manual_approved') return 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300';
  if (status === 'ambiguous_pending_review' || status === 'draft' || status === 'pending_review') return 'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300';
  if (status === 'rejected' || status === 'disabled') return 'bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300';
  return 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300';
}

export const ProductCatalogManagementTab: React.FC = () => {
  const [panel, setPanel] = useState<CatalogPanel>('models');
  const [models, setModels] = useState<KnowledgeCatalogModel[]>([]);
  const [aliases, setAliases] = useState<KnowledgeCatalogAlias[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [vendorFilter, setVendorFilter] = useState('');
  const [familyFilter, setFamilyFilter] = useState('');
  const [seriesFilter, setSeriesFilter] = useState('');
  const [modelFilter, setModelFilter] = useState('');
  const [softwareVersionFilter, setSoftwareVersionFilter] = useState('');
  const [aliasFilter, setAliasFilter] = useState('');
  const [kindFilter, setKindFilter] = useState('');
  const [query, setQuery] = useState('CE68');
  const [resolution, setResolution] = useState<KnowledgeCatalogResolveResponse | null>(null);
  const [resolving, setResolving] = useState(false);

  const loadCatalog = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [catalog, aliasResponse] = await Promise.all([
        getKnowledgeCatalog({ vendor_id: vendorFilter, family_code: familyFilter, series_code: seriesFilter, model: modelFilter, software_version: softwareVersionFilter }),
        getKnowledgeCatalogAliases({ alias: aliasFilter, alias_kind: kindFilter }),
      ]);
      setModels(catalog.items);
      setAliases(aliasResponse.items);
    } catch (err: any) {
      setError(err?.message || '产品目录加载失败');
    } finally {
      setLoading(false);
    }
  }, [aliasFilter, familyFilter, kindFilter, modelFilter, seriesFilter, softwareVersionFilter, vendorFilter]);

  useEffect(() => {
    void loadCatalog();
  }, [loadCatalog]);

  const vendors = useMemo(() => Array.from(new Set(models.map((item) => item.vendor_id))), [models]);
  const families = useMemo(() => Array.from(new Set(models.map((item) => item.family_code))), [models]);
  const series = useMemo(() => Array.from(new Set(models.map((item) => item.series_code))), [models]);
  const softwareVersions = useMemo(() => Array.from(new Set(models.flatMap((item) => [item.software_scope?.primary_version, item.software_scope?.compatibility_version].filter((value): value is string => typeof value === 'string' && value.length > 0)))), [models]);
  const conflictCount = aliases.filter((item) => item.conflict_status === 'ambiguous_pending_review').length;

  const runResolution = async (event: React.FormEvent) => {
    event.preventDefault();
    const value = query.trim();
    if (!value) return;
    setResolving(true);
    setError('');
    try {
      setResolution(await resolveKnowledgeCatalogAlias(value));
    } catch (err: any) {
      setError(err?.message || '别名解析失败');
      setResolution(null);
    } finally {
      setResolving(false);
    }
  };

  return (
    <div className="mx-auto w-full max-w-[1500px] space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-indigo-500"><Layers className="h-4 w-4" />Knowledge Engine V2</div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">产品目录与别名管理</h1>
          <p className="mt-1 max-w-3xl text-sm text-gray-500 dark:text-gray-400">浏览已审核的 Vendor / Family / Series / Model 层级，检查 Alias 冲突并执行只读解析预览。目录物理迁移前，种子数据保持只读。</p>
        </div>
        <button type="button" onClick={() => void loadCatalog()} disabled={loading} className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs font-semibold text-gray-700 shadow-sm hover:border-indigo-300 disabled:opacity-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />刷新</button>
      </header>

      <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-amber-200 bg-amber-50/80 px-4 py-3 text-xs text-amber-800 dark:border-amber-900/70 dark:bg-amber-950/30 dark:text-amber-200">
        <ShieldCheck className="h-4 w-4 shrink-0" />
        <span className="font-semibold">只读审核种子</span>
        <span>CAT-005/006/010 当前为 contract-only；管理操作不会绕过 DB-006 迁移或修改 V1 元数据。</span>
        {conflictCount > 0 && <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-1 font-semibold dark:bg-amber-900/50"><AlertTriangle className="h-3.5 w-3.5" />{conflictCount} 条待裁决</span>}
      </div>

      {error && <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900/70 dark:bg-red-950/30 dark:text-red-300"><AlertTriangle className="h-4 w-4" />{error}</div>}

      <section className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2"><Filter className="h-4 w-4 text-indigo-500" /><span className="text-sm font-semibold text-gray-800 dark:text-gray-100">目录筛选</span></div>
          <div className="flex rounded-xl bg-gray-100 p-1 dark:bg-gray-900">
            <button type="button" onClick={() => setPanel('models')} className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${panel === 'models' ? 'bg-white text-indigo-700 shadow-sm dark:bg-gray-700 dark:text-indigo-300' : 'text-gray-500'}`}><Database className="mr-1 inline h-3.5 w-3.5" />型号目录</button>
            <button type="button" onClick={() => setPanel('aliases')} className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${panel === 'aliases' ? 'bg-white text-indigo-700 shadow-sm dark:bg-gray-700 dark:text-indigo-300' : 'text-gray-500'}`}><Tag className="mr-1 inline h-3.5 w-3.5" />Alias 队列</button>
          </div>
        </div>
        <div className="grid gap-2 md:grid-cols-5">
          <label className="text-[11px] font-semibold text-gray-500">Vendor<select value={vendorFilter} onChange={(event) => setVendorFilter(event.target.value)} className="mt-1 w-full rounded-lg border border-gray-200 bg-white px-2.5 py-2 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"><option value="">全部 Vendor</option>{vendors.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
          <label className="text-[11px] font-semibold text-gray-500">Family<select value={familyFilter} onChange={(event) => setFamilyFilter(event.target.value)} className="mt-1 w-full rounded-lg border border-gray-200 bg-white px-2.5 py-2 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"><option value="">全部 Family</option>{families.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
          <label className="text-[11px] font-semibold text-gray-500">Series<select value={seriesFilter} onChange={(event) => setSeriesFilter(event.target.value)} className="mt-1 w-full rounded-lg border border-gray-200 bg-white px-2.5 py-2 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"><option value="">全部 Series</option>{series.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
          <label className="text-[11px] font-semibold text-gray-500">型号搜索<input value={modelFilter} onChange={(event) => setModelFilter(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void loadCatalog(); }} placeholder="C9300-48P" className="mt-1 w-full rounded-lg border border-gray-200 bg-white px-2.5 py-2 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100" /></label>
          {panel === 'models' ? <label className="text-[11px] font-semibold text-gray-500">Software Version<select value={softwareVersionFilter} onChange={(event) => setSoftwareVersionFilter(event.target.value)} className="mt-1 w-full rounded-lg border border-gray-200 bg-white px-2.5 py-2 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"><option value="">全部 Version</option>{softwareVersions.map((item) => <option key={item} value={item}>{item}</option>)}</select></label> : <label className="text-[11px] font-semibold text-gray-500">Alias 类型<select value={kindFilter} onChange={(event) => setKindFilter(event.target.value)} className="mt-1 w-full rounded-lg border border-gray-200 bg-white px-2.5 py-2 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"><option value="">全部类型</option>{Object.entries(KIND_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>}
        </div>
        {panel === 'aliases' && <div className="mt-2"><label className="text-[11px] font-semibold text-gray-500">Alias 搜索<input value={aliasFilter} onChange={(event) => setAliasFilter(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void loadCatalog(); }} placeholder="CE68 / Catalyst93" className="mt-1 w-full rounded-lg border border-gray-200 bg-white px-2.5 py-2 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100" /></label></div>}
        <div className="mt-3 flex justify-end"><button type="button" onClick={() => { setVendorFilter(''); setFamilyFilter(''); setSeriesFilter(''); setModelFilter(''); setSoftwareVersionFilter(''); setAliasFilter(''); setKindFilter(''); }} className="rounded-lg border border-gray-200 px-3 py-2 text-xs font-semibold text-gray-600 hover:border-indigo-300 dark:border-gray-600 dark:text-gray-300">清除筛选</button></div>
      </section>

      {panel === 'models' ? (
        <section className="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-800">
          <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3 dark:border-gray-700"><div><h2 className="text-sm font-semibold text-gray-800 dark:text-gray-100">Reviewed Product Models</h2><p className="text-[11px] text-gray-500">共 {models.length} 个首批型号 · 状态仍由目录迁移门禁控制</p></div><Eye className="h-4 w-4 text-gray-400" /></div>
          {loading ? <div className="flex items-center justify-center gap-2 p-10 text-xs text-gray-400"><Loader2 className="h-4 w-4 animate-spin" />加载中…</div> : <div className="overflow-x-auto"><table className="min-w-full text-left text-xs"><thead className="bg-gray-50 text-[11px] text-gray-500 dark:bg-gray-900/60"><tr><th className="px-4 py-3">Vendor / Family</th><th className="px-4 py-3">Series</th><th className="px-4 py-3">Model</th><th className="px-4 py-3">OS / Train</th><th className="px-4 py-3">Software Version</th><th className="px-4 py-3">状态</th></tr></thead><tbody className="divide-y divide-gray-100 dark:divide-gray-700">{models.map((item) => <tr key={item.product_model_id} className="hover:bg-gray-50/80 dark:hover:bg-gray-900/40"><td className="px-4 py-3"><div className="font-semibold text-gray-800 dark:text-gray-100">{item.vendor_name}</div><div className="text-[11px] text-gray-500">{item.family_code}</div></td><td className="px-4 py-3"><div className="font-medium text-gray-700 dark:text-gray-200">{item.series_name}</div><div className="text-[11px] text-gray-500">{item.series_code}</div></td><td className="px-4 py-3"><div className="font-semibold text-indigo-700 dark:text-indigo-300">{item.model_code}</div><div className="max-w-[260px] truncate text-[11px] text-gray-500">{item.product_model_id}</div></td><td className="px-4 py-3"><div>{scopeValue(item, 'os_family')}</div><div className="text-[11px] text-gray-500">{scopeValue(item, 'software_train')}</div></td><td className="px-4 py-3"><div>{scopeValue(item, 'primary_version')}</div><div className="text-[11px] text-gray-500">兼容 {scopeValue(item, 'compatibility_version')}</div></td><td className="px-4 py-3"><span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${statusTone(item.status)}`}>{item.status}</span><div className="mt-1 text-[10px] text-gray-500">{item.review_status}</div></td></tr>)}</tbody></table></div>}
        </section>
      ) : (
        <section className="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-800">
          <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3 dark:border-gray-700"><div><h2 className="text-sm font-semibold text-gray-800 dark:text-gray-100">Alias Review Queue</h2><p className="text-[11px] text-gray-500">前缀只产生候选；冲突必须人工澄清，当前不写入生产表</p></div><Tag className="h-4 w-4 text-gray-400" /></div>
          {loading ? <div className="flex items-center justify-center gap-2 p-10 text-xs text-gray-400"><Loader2 className="h-4 w-4 animate-spin" />加载中…</div> : <div className="overflow-x-auto"><table className="min-w-full text-left text-xs"><thead className="bg-gray-50 text-[11px] text-gray-500 dark:bg-gray-900/60"><tr><th className="px-4 py-3">Alias</th><th className="px-4 py-3">类型</th><th className="px-4 py-3">目标型号</th><th className="px-4 py-3">冲突 / 审核</th><th className="px-4 py-3">动作</th></tr></thead><tbody className="divide-y divide-gray-100 dark:divide-gray-700">{aliases.map((item) => <tr key={item.id} className="hover:bg-gray-50/80 dark:hover:bg-gray-900/40"><td className="px-4 py-3"><div className="font-semibold text-gray-800 dark:text-gray-100">{item.alias}</div><div className="text-[11px] text-gray-500">{item.normalized_alias}</div></td><td className="px-4 py-3"><span className="rounded-full bg-indigo-50 px-2 py-1 text-[10px] font-semibold text-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-300">{KIND_LABELS[item.alias_kind] || item.alias_kind}</span></td><td className="px-4 py-3"><div className="font-medium text-gray-700 dark:text-gray-200">{item.model?.model_code || item.product_model_id}</div><div className="text-[10px] text-gray-500">{item.model?.vendor_id} / {item.model?.series_code}</div></td><td className="px-4 py-3"><span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${statusTone(item.conflict_status)}`}>{item.conflict_status}</span><div className="mt-1 text-[10px] text-gray-500">{item.seed_status}</div></td><td className="px-4 py-3"><button type="button" onClick={() => setQuery(item.alias)} className="rounded-lg border border-gray-200 px-2.5 py-1.5 text-[10px] font-semibold text-gray-600 hover:border-indigo-300 dark:border-gray-600 dark:text-gray-300">带入解析</button></td></tr>)}</tbody></table></div>}
        </section>
      )}

      <section className="rounded-2xl border border-indigo-100 bg-indigo-50/60 p-4 dark:border-indigo-900/50 dark:bg-indigo-950/20">
        <div className="mb-3 flex items-center gap-2"><Sparkles className="h-4 w-4 text-indigo-500" /><h2 className="text-sm font-semibold text-indigo-900 dark:text-indigo-200">Alias 只读解析预览</h2><span className="rounded-full bg-white/70 px-2 py-1 text-[10px] font-semibold text-indigo-600 dark:bg-indigo-950/50 dark:text-indigo-300">dry-run</span></div>
        <form onSubmit={(event) => void runResolution(event)} className="flex flex-wrap gap-2"><div className="relative min-w-[240px] flex-1"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-gray-400" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入 CE68、CE6885-48YS8CQ…" className="w-full rounded-xl border border-indigo-200 bg-white py-2 pl-9 pr-3 text-sm outline-none focus:border-indigo-400 dark:border-indigo-800 dark:bg-gray-900 dark:text-white" /></div><button type="submit" disabled={resolving || !query.trim()} className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2 text-xs font-semibold text-white shadow-sm hover:bg-indigo-700 disabled:opacity-50">{resolving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}解析</button></form>
        {resolution && <div className="mt-3 rounded-xl border border-indigo-100 bg-white p-3 dark:border-indigo-900/60 dark:bg-gray-900"><div className="flex flex-wrap items-center gap-2 text-xs"><span className={`rounded-full px-2 py-1 font-semibold ${resolution.outcome === 'unique' ? 'bg-emerald-50 text-emerald-700' : resolution.outcome === 'unknown' ? 'bg-gray-100 text-gray-600' : 'bg-amber-50 text-amber-700'}`}>{resolution.outcome}</span><span className="text-gray-500">候选 {resolution.candidate_count} 条</span>{resolution.requires_clarification && <span className="font-semibold text-amber-600">需要澄清</span>}<span className="ml-auto text-[10px] text-gray-400">driver selection: {resolution.driver_selection_allowed ? 'allowed' : 'blocked'}</span></div>{resolution.candidates.length > 0 && <div className="mt-2 grid gap-2 md:grid-cols-2">{resolution.candidates.map((candidate) => <div key={String(candidate.id || candidate.product_model_id)} className="rounded-lg border border-gray-100 p-2 text-xs dark:border-gray-700"><div className="font-semibold text-gray-800 dark:text-gray-100">{candidate.model?.model_code || String(candidate.product_model_id || 'UNKNOWN')}</div><div className="text-[11px] text-gray-500">{candidate.model?.vendor_id} / {candidate.model?.series_code} · {String(candidate.alias_kind || '')}</div></div>)}</div>}</div>}
      </section>
    </div>
  );
};

export default ProductCatalogManagementTab;
