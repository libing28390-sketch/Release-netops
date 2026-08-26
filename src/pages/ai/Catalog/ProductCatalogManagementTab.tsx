import React, { useCallback, useEffect, useState } from 'react';
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
import Pagination from '../../../components/Pagination';

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
  const [softwareVersionFilter, setSoftwareVersionFilter] = useState('');
  const [kindFilter, setKindFilter] = useState('');
  const [searchText, setSearchText] = useState('');
  const [appliedSearch, setAppliedSearch] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [facets, setFacets] = useState({ vendors: [] as string[], families: [] as string[], series: [] as string[], software_versions: [] as string[] });
  const [query, setQuery] = useState('CE68');
  const [resolution, setResolution] = useState<KnowledgeCatalogResolveResponse | null>(null);
  const [resolving, setResolving] = useState(false);

  const loadCatalog = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      if (panel === 'models') {
        const catalog = await getKnowledgeCatalog({ search: appliedSearch, vendor_id: vendorFilter, family_code: familyFilter, series_code: seriesFilter, software_version: softwareVersionFilter, page, page_size: pageSize });
        setModels(catalog.items);
        setTotal(catalog.meta?.pagination.total ?? catalog.total);
        if (catalog.meta?.pagination.page && catalog.meta.pagination.page !== page) setPage(catalog.meta.pagination.page);
        if (catalog.facets) setFacets(catalog.facets);
      } else {
        const aliasResponse = await getKnowledgeCatalogAliases({ alias: appliedSearch, alias_kind: kindFilter, page, page_size: pageSize });
        setAliases(aliasResponse.items);
        setTotal(aliasResponse.meta?.pagination.total ?? aliasResponse.total);
        if (aliasResponse.meta?.pagination.page && aliasResponse.meta.pagination.page !== page) setPage(aliasResponse.meta.pagination.page);
      }
    } catch (err: any) {
      setError(err?.message || '产品目录加载失败');
    } finally {
      setLoading(false);
    }
  }, [appliedSearch, familyFilter, kindFilter, page, pageSize, panel, seriesFilter, softwareVersionFilter, vendorFilter]);

  useEffect(() => {
    void loadCatalog();
  }, [loadCatalog]);

  const vendors = facets.vendors;
  const families = facets.families;
  const series = facets.series;
  const softwareVersions = facets.software_versions;
  const conflictCount = aliases.filter((item) => item.conflict_status === 'ambiguous_pending_review').length;

  const applySearch = (event?: React.FormEvent) => {
    event?.preventDefault();
    setPage(1);
    setAppliedSearch(searchText.trim());
  };

  const changePanel = (next: CatalogPanel) => {
    setPanel(next);
    setPage(1);
    setSearchText('');
    setAppliedSearch('');
    setVendorFilter('');
    setFamilyFilter('');
    setSeriesFilter('');
    setSoftwareVersionFilter('');
    setKindFilter('');
  };

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
          <h1 className="nx-page-title text-gray-900 dark:text-white">产品目录与别名管理</h1>
          <p className="nx-page-description mt-1 max-w-3xl text-gray-500 dark:text-gray-400">浏览已审核的 Vendor / Family / Series / Model 层级，检查 Alias 冲突并执行只读解析预览。目录物理迁移前，种子数据保持只读。</p>
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
            <button type="button" onClick={() => changePanel('models')} className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${panel === 'models' ? 'bg-white text-indigo-700 shadow-sm dark:bg-gray-700 dark:text-indigo-300' : 'text-gray-500'}`}><Database className="mr-1 inline h-3.5 w-3.5" />型号目录</button>
            <button type="button" onClick={() => changePanel('aliases')} className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${panel === 'aliases' ? 'bg-white text-indigo-700 shadow-sm dark:bg-gray-700 dark:text-indigo-300' : 'text-gray-500'}`}><Tag className="mr-1 inline h-3.5 w-3.5" />Alias 队列</button>
          </div>
        </div>
        <form onSubmit={applySearch} className="mb-3 flex flex-wrap gap-2">
          <div className="relative min-w-[260px] flex-1"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-gray-400" /><input value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder={panel === 'models' ? '搜索厂商、系列、型号、OS 或软件版本' : '搜索 Alias'} className="w-full rounded-xl border border-gray-200 bg-white py-2 pl-9 pr-3 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100" /></div>
          <button type="submit" className="rounded-xl bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700">搜索</button>
        </form>
        {panel === 'models' ? <div className="grid gap-2 md:grid-cols-4">
          <label className="text-[11px] font-semibold text-gray-500">Vendor<select value={vendorFilter} onChange={(event) => { setVendorFilter(event.target.value); setPage(1); }} className="mt-1 w-full rounded-lg border border-gray-200 bg-white px-2.5 py-2 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"><option value="">全部 Vendor</option>{vendors.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
          <label className="text-[11px] font-semibold text-gray-500">Family<select value={familyFilter} onChange={(event) => { setFamilyFilter(event.target.value); setPage(1); }} className="mt-1 w-full rounded-lg border border-gray-200 bg-white px-2.5 py-2 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"><option value="">全部 Family</option>{families.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
          <label className="text-[11px] font-semibold text-gray-500">Series<select value={seriesFilter} onChange={(event) => { setSeriesFilter(event.target.value); setPage(1); }} className="mt-1 w-full rounded-lg border border-gray-200 bg-white px-2.5 py-2 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"><option value="">全部 Series</option>{series.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
          <label className="text-[11px] font-semibold text-gray-500">Software Version<select value={softwareVersionFilter} onChange={(event) => { setSoftwareVersionFilter(event.target.value); setPage(1); }} className="mt-1 w-full rounded-lg border border-gray-200 bg-white px-2.5 py-2 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"><option value="">全部 Version</option>{softwareVersions.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
        </div> : <div className="max-w-xs"><label className="text-[11px] font-semibold text-gray-500">Alias 类型<select value={kindFilter} onChange={(event) => { setKindFilter(event.target.value); setPage(1); }} className="mt-1 w-full rounded-lg border border-gray-200 bg-white px-2.5 py-2 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"><option value="">全部类型</option>{Object.entries(KIND_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label></div>}
        <div className="mt-3 flex justify-end"><button type="button" onClick={() => { setVendorFilter(''); setFamilyFilter(''); setSeriesFilter(''); setSoftwareVersionFilter(''); setKindFilter(''); setSearchText(''); setAppliedSearch(''); setPage(1); }} className="rounded-lg border border-gray-200 px-3 py-2 text-xs font-semibold text-gray-600 hover:border-indigo-300 dark:border-gray-600 dark:text-gray-300">清除筛选</button></div>
      </section>

      {panel === 'models' ? (
        <section className="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-800">
          <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3 dark:border-gray-700"><div><h2 className="text-sm font-semibold text-gray-800 dark:text-gray-100">Reviewed Product Models</h2><p className="text-[11px] text-gray-500">共 {total} 个匹配型号 · 当前第 {page} 页</p></div><Eye className="h-4 w-4 text-gray-400" /></div>
          {loading ? <div className="flex items-center justify-center gap-2 p-10 text-xs text-gray-400"><Loader2 className="h-4 w-4 animate-spin" />加载中…</div> : <div className="overflow-x-auto"><table className="nx-data-table min-w-full text-left"><thead><tr><th>Vendor / Family</th><th>Series</th><th>Model</th><th>OS / Train</th><th>Software Version</th><th>状态</th></tr></thead><tbody>{models.map((item) => <tr key={item.product_model_id}><td><div className="font-semibold text-gray-800 dark:text-gray-100">{item.vendor_name}</div><div className="nx-micro-text text-gray-500">{item.family_code}</div></td><td><div className="font-medium text-gray-700 dark:text-gray-200">{item.series_name}</div><div className="nx-micro-text text-gray-500">{item.series_code}</div></td><td><div className="font-semibold text-indigo-700 dark:text-indigo-300">{item.model_code}</div><div className="nx-micro-text max-w-[260px] truncate text-gray-500">{item.product_model_id}</div></td><td><div>{scopeValue(item, 'os_family')}</div><div className="nx-micro-text text-gray-500">{scopeValue(item, 'software_train')}</div></td><td><div>{scopeValue(item, 'primary_version')}</div><div className="nx-micro-text text-gray-500">兼容 {scopeValue(item, 'compatibility_version')}</div></td><td><span className={`nx-micro-text rounded-full px-2 py-1 font-semibold ${statusTone(item.status)}`}>{item.status}</span><div className="mt-1 nx-micro-text text-gray-500">{item.review_status}</div></td></tr>)}</tbody></table></div>}
          <Pagination currentPage={page} totalItems={total} itemsPerPage={pageSize} onPageChange={setPage} onItemsPerPageChange={(size) => { setPageSize(size); setPage(1); }} language="zh" alwaysVisible />
        </section>
      ) : (
        <section className="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-800">
          <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3 dark:border-gray-700"><div><h2 className="text-sm font-semibold text-gray-800 dark:text-gray-100">Alias Review Queue</h2><p className="text-[11px] text-gray-500">前缀只产生候选；冲突必须人工澄清，当前不写入生产表</p></div><Tag className="h-4 w-4 text-gray-400" /></div>
          {loading ? <div className="flex items-center justify-center gap-2 p-10 text-xs text-gray-400"><Loader2 className="h-4 w-4 animate-spin" />加载中…</div> : <div className="overflow-x-auto"><table className="nx-data-table min-w-full text-left"><thead><tr><th>Alias</th><th>类型</th><th>目标型号</th><th>冲突 / 审核</th><th>动作</th></tr></thead><tbody>{aliases.map((item) => <tr key={item.id}><td><div className="font-semibold text-gray-800 dark:text-gray-100">{item.alias}</div><div className="nx-micro-text text-gray-500">{item.normalized_alias}</div></td><td><span className="nx-micro-text rounded-full bg-indigo-50 px-2 py-1 font-semibold text-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-300">{KIND_LABELS[item.alias_kind] || item.alias_kind}</span></td><td><div className="font-medium text-gray-700 dark:text-gray-200">{item.model?.model_code || item.product_model_id}</div><div className="nx-micro-text text-gray-500">{item.model?.vendor_id} / {item.model?.series_code}</div></td><td><span className={`nx-micro-text rounded-full px-2 py-1 font-semibold ${statusTone(item.conflict_status)}`}>{item.conflict_status}</span><div className="mt-1 nx-micro-text text-gray-500">{item.seed_status}</div></td><td><button type="button" onClick={() => setQuery(item.alias)} className="nx-action-button nx-action-button--sm border-gray-200 text-gray-600 hover:border-indigo-300 dark:border-gray-600 dark:text-gray-300">带入解析</button></td></tr>)}</tbody></table></div>}
          <Pagination currentPage={page} totalItems={total} itemsPerPage={pageSize} onPageChange={setPage} onItemsPerPageChange={(size) => { setPageSize(size); setPage(1); }} language="zh" alwaysVisible />
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
