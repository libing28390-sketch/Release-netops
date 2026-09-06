import React, { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle,
  ChevronRight,
  Database,
  Eye,
  Filter,
  Pencil,
  Layers,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Tag,
  Trash2,
  X,
} from 'lucide-react';
import {
  getKnowledgeCatalog,
  getKnowledgeCatalogAliases,
  resolveKnowledgeCatalogAlias,
  createKnowledgeCatalogCustomModel,
  updateKnowledgeCatalogCustomModel,
  deleteKnowledgeCatalogCustomModel,
  type KnowledgeCatalogCustomModelInput,
  type KnowledgeCatalogCustomModelUpdate,
  type KnowledgeCatalogAlias,
  type KnowledgeCatalogHierarchyVendor,
  type KnowledgeCatalogModel,
  type KnowledgeCatalogResolveResponse,
} from '../../../api/ai';
import Pagination from '../../../components/Pagination';
import { useCoreApp } from '../../../contexts/AppDomainContext';
import { aiAdminText } from '../../../i18n/aiAdmin';

type TextVariables = Record<string, string | number>;

type CatalogPanel = 'models' | 'aliases';

const KIND_LABELS: Record<string, string> = {
  exact: 'ai.catalog.kind.exact',
  canonical: 'ai.catalog.kind.canonical',
  prefix: 'ai.catalog.kind.prefix',
  trigram: 'ai.catalog.kind.trigram',
};

const CATALOG_STATUS_LABELS: Record<string, string> = {
  draft: 'ai.catalog.status.draft',
  active: 'ai.catalog.status.active',
  disabled: 'ai.catalog.status.disabled',
  archived: 'ai.catalog.status.archived',
  deleted: 'ai.catalog.status.deleted',
  manual_approved: 'ai.catalog.status.manual_approved',
  pending_review: 'ai.catalog.status.pending_review',
  ambiguous_pending_review: 'ai.catalog.status.ambiguous_pending_review',
  rejected: 'ai.catalog.status.rejected',
};

const RESOLUTION_OUTCOME_LABELS: Record<string, string> = {
  unique: 'ai.catalog.resolve.unique',
  ambiguous: 'ai.catalog.resolve.ambiguous',
  unknown: 'ai.catalog.resolve.unknown',
};

function catalogLabel(tx: (key: string, variables?: TextVariables) => string, labels: Record<string, string>, value: string): string {
  return labels[value] ? tx(labels[value]) : value;
}

function scopeValue(model: KnowledgeCatalogModel | undefined, key: string, emptyLabel: string): string {
  return String(model?.software_scope?.[key] ?? emptyLabel);
}

function statusTone(status: string): string {
  if (status === 'active' || status === 'manual_approved') return 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300';
  if (status === 'ambiguous_pending_review' || status === 'draft' || status === 'pending_review') return 'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300';
  if (status === 'rejected' || status === 'disabled') return 'bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300';
  return 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300';
}

export const ProductCatalogManagementTab: React.FC = () => {
  const { language, showToast, currentUser } = useCoreApp();
  const tx = (key: string, variables?: TextVariables) => aiAdminText(key, language, variables);
  const canManageCatalog = currentUser?.role === 'Administrator' || currentUser?.role_profile === 'Platform Maintainer';
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
  const [kindFilter, setKindFilter] = useState('');
  const [searchText, setSearchText] = useState('');
  const [appliedSearch, setAppliedSearch] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [facets, setFacets] = useState({ vendors: [] as string[], families: [] as string[], series: [] as string[], software_versions: [] as string[] });
  const [hierarchy, setHierarchy] = useState<KnowledgeCatalogHierarchyVendor[]>([]);
  const [query, setQuery] = useState('CE68');
  const [resolution, setResolution] = useState<KnowledgeCatalogResolveResponse | null>(null);
  const [resolving, setResolving] = useState(false);
  const [catalogReadOnly, setCatalogReadOnly] = useState(true);
  const [catalogModalOpen, setCatalogModalOpen] = useState(false);
  const [editingModel, setEditingModel] = useState<KnowledgeCatalogModel | null>(null);
  const [catalogSubmitting, setCatalogSubmitting] = useState(false);
  const [catalogForm, setCatalogForm] = useState({
    vendor_code: '', vendor_name: '', family_code: '', family_name: '', series_code: '', series_name: '',
    model_code: '', display_name: '', status: 'draft' as 'draft' | 'active' | 'disabled' | 'archived',
    description: '', software_version: '', change_reason: '',
  });

  const loadCatalog = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      if (panel === 'models') {
        const catalog = await getKnowledgeCatalog({ search: appliedSearch, vendor_id: vendorFilter, family_code: familyFilter, series_code: seriesFilter, model: modelFilter, software_version: softwareVersionFilter, page, page_size: pageSize });
        setModels(catalog.items);
        setCatalogReadOnly(catalog.read_only);
        setTotal(catalog.meta?.pagination.total ?? catalog.total);
        if (catalog.meta?.pagination.page && catalog.meta.pagination.page !== page) setPage(catalog.meta.pagination.page);
        if (catalog.facets) {
          setFacets(catalog.facets);
          setHierarchy(catalog.facets.hierarchy || []);
        }
      } else {
        const aliasResponse = await getKnowledgeCatalogAliases({ alias: appliedSearch, alias_kind: kindFilter, page, page_size: pageSize });
        setAliases(aliasResponse.items);
        setTotal(aliasResponse.meta?.pagination.total ?? aliasResponse.total);
        if (aliasResponse.meta?.pagination.page && aliasResponse.meta.pagination.page !== page) setPage(aliasResponse.meta.pagination.page);
      }
    } catch (err: any) {
      setError(err?.message || tx('ai.catalog.error.load'));
    } finally {
      setLoading(false);
    }
  }, [appliedSearch, familyFilter, kindFilter, language, modelFilter, page, pageSize, panel, seriesFilter, softwareVersionFilter, vendorFilter]);

  useEffect(() => {
    void loadCatalog();
  }, [loadCatalog]);

  const vendors = facets.vendors;
  const families = facets.families;
  const series = facets.series;
  const softwareVersions = facets.software_versions;
  const selectedVendorNode = hierarchy.find((item) => item.vendor_id === vendorFilter);
  const selectedFamilyNode = selectedVendorNode?.families.find((item) => item.family_code === familyFilter);
  const selectedSeriesNode = selectedFamilyNode?.series.find((item) => item.series_code === seriesFilter);
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
    setModelFilter('');
    setSoftwareVersionFilter('');
    setKindFilter('');
  };

  const selectHierarchyVendor = (vendorId: string) => {
    setVendorFilter(vendorId);
    setFamilyFilter('');
    setSeriesFilter('');
    setModelFilter('');
    setPage(1);
  };

  const selectHierarchyFamily = (vendorId: string, familyCode: string) => {
    setVendorFilter(vendorId);
    setFamilyFilter(familyCode);
    setSeriesFilter('');
    setModelFilter('');
    setPage(1);
  };

  const selectHierarchySeries = (vendorId: string, familyCode: string, seriesCode: string) => {
    setVendorFilter(vendorId);
    setFamilyFilter(familyCode);
    setSeriesFilter(seriesCode);
    setModelFilter('');
    setPage(1);
  };

  const selectHierarchyModel = (vendorId: string, familyCode: string, seriesCode: string, modelCode: string) => {
    setVendorFilter(vendorId);
    setFamilyFilter(familyCode);
    setSeriesFilter(seriesCode);
    setModelFilter(modelCode);
    setPage(1);
  };

  const clearCatalogFilters = () => {
    setVendorFilter('');
    setFamilyFilter('');
    setSeriesFilter('');
    setModelFilter('');
    setSoftwareVersionFilter('');
    setKindFilter('');
    setSearchText('');
    setAppliedSearch('');
    setPage(1);
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
      setError(err?.message || tx('ai.catalog.error.alias'));
      setResolution(null);
    } finally {
      setResolving(false);
    }
  };

  const openCreateCatalogModel = () => {
    setEditingModel(null);
    setCatalogForm({ vendor_code: '', vendor_name: '', family_code: '', family_name: '', series_code: '', series_name: '', model_code: '', display_name: '', status: 'draft', description: '', software_version: '', change_reason: '' });
    setCatalogModalOpen(true);
  };

  const openEditCatalogModel = (model: KnowledgeCatalogModel) => {
    setEditingModel(model);
    setCatalogForm({
      vendor_code: model.vendor_id, vendor_name: model.vendor_name, family_code: model.family_code, family_name: model.family_name,
      series_code: model.series_code, series_name: model.series_name, model_code: model.model_code, display_name: model.display_name,
      status: (['draft', 'active', 'disabled', 'archived'].includes(model.status) ? model.status : 'draft') as 'draft' | 'active' | 'disabled' | 'archived',
      description: model.description || '', software_version: String(model.software_scope?.primary_version || ''), change_reason: '',
    });
    setCatalogModalOpen(true);
  };

  const submitCatalogModel = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!catalogForm.display_name.trim() || (!editingModel && (!catalogForm.vendor_code.trim() || !catalogForm.vendor_name.trim() || !catalogForm.family_code.trim() || !catalogForm.family_name.trim() || !catalogForm.series_code.trim() || !catalogForm.series_name.trim() || !catalogForm.model_code.trim()))) return;
    if (editingModel && !catalogForm.change_reason.trim()) {
      showToast(tx('ai.catalog.toast.reason'), 'error');
      return;
    }
    setCatalogSubmitting(true);
    try {
      const software_scope = catalogForm.software_version.trim() ? { primary_version: catalogForm.software_version.trim() } : {};
      if (editingModel) {
        const payload: KnowledgeCatalogCustomModelUpdate = { display_name: catalogForm.display_name.trim(), status: catalogForm.status, description: catalogForm.description.trim(), software_scope, change_reason: catalogForm.change_reason.trim(), expected_updated_at: editingModel.updated_at || undefined };
        await updateKnowledgeCatalogCustomModel(editingModel.product_model_id, payload);
      } else {
        const payload: KnowledgeCatalogCustomModelInput = { vendor_code: catalogForm.vendor_code.trim(), vendor_name: catalogForm.vendor_name.trim(), family_code: catalogForm.family_code.trim(), family_name: catalogForm.family_name.trim(), series_code: catalogForm.series_code.trim(), series_name: catalogForm.series_name.trim(), model_code: catalogForm.model_code.trim(), display_name: catalogForm.display_name.trim(), status: catalogForm.status, description: catalogForm.description.trim(), software_scope, change_reason: catalogForm.change_reason.trim() || tx('ai.catalog.editor.create') };
        await createKnowledgeCatalogCustomModel(payload);
      }
      setCatalogModalOpen(false);
      await loadCatalog();
      showToast(editingModel ? tx('ai.catalog.toast.updated') : tx('ai.catalog.toast.created'), 'success');
    } catch (err: any) {
      showToast(err?.message || tx('ai.catalog.toast.saveFailed'), 'error');
    } finally { setCatalogSubmitting(false); }
  };

  const archiveCatalogModel = async (model: KnowledgeCatalogModel) => {
    if (!window.confirm(tx('ai.catalog.archive.confirm', { name: model.display_name }))) return;
    try {
      await deleteKnowledgeCatalogCustomModel(model.product_model_id, tx('ai.catalog.archive.reason'));
      await loadCatalog();
      showToast(tx('ai.catalog.toast.archived'), 'success');
    } catch (err: any) { showToast(err?.message || tx('ai.catalog.toast.archiveFailed'), 'error'); }
  };

  return (
    <div className="w-full space-y-5 pb-8">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-indigo-500"><Layers className="h-4 w-4" />{tx('ai.catalog.eyebrow')}</div>
          <h1 className="nx-page-title text-gray-900 dark:text-white">{tx('ai.catalog.title')}</h1>
           <p className="nx-page-description mt-1 max-w-3xl text-gray-500 dark:text-gray-400">{tx('ai.catalog.description')}</p>
         </div>
         <div className="flex items-center gap-2"><button type="button" onClick={() => void loadCatalog()} disabled={loading} className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs font-semibold text-gray-700 shadow-sm hover:border-indigo-300 disabled:opacity-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />{tx('ai.common.refresh')}</button>{canManageCatalog && panel === 'models' && <button type="button" onClick={openCreateCatalogModel} className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-3 py-2 text-xs font-semibold text-white shadow-sm hover:bg-indigo-700"><Plus className="h-4 w-4" />{tx('ai.catalog.add')}</button>}</div>
      </header>

      <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-amber-200 bg-amber-50/80 px-4 py-3 text-xs text-amber-800 dark:border-amber-900/70 dark:bg-amber-950/30 dark:text-amber-200">
        <ShieldCheck className="h-4 w-4 shrink-0" />
         <span className="font-semibold">{tx(catalogReadOnly ? 'ai.catalog.seed' : 'ai.catalog.officialAndCustom')}</span>
         <span>{tx(catalogReadOnly ? 'ai.catalog.readOnlyBody' : 'ai.catalog.customBody')}</span>
        {conflictCount > 0 && <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-1 font-semibold dark:bg-amber-900/50"><AlertTriangle className="h-3.5 w-3.5" />{tx('ai.catalog.pending', { count: conflictCount })}</span>}
      </div>

      {error && <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900/70 dark:bg-red-950/30 dark:text-red-300"><AlertTriangle className="h-4 w-4" />{error}</div>}

      {panel === 'models' && (
        <section className="rounded-2xl border border-indigo-100 bg-indigo-50/50 p-4 shadow-sm dark:border-indigo-900/60 dark:bg-indigo-950/20" aria-label={tx('ai.catalog.browse.aria')}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold text-indigo-950 dark:text-indigo-100"><Layers className="h-4 w-4 text-indigo-500" />{tx('ai.catalog.browse.title')}</div>
              <p className="mt-1 text-[11px] leading-5 text-indigo-800/70 dark:text-indigo-200/70">{tx('ai.catalog.browse.body')}</p>
            </div>
            <button type="button" onClick={clearCatalogFilters} disabled={!vendorFilter && !familyFilter && !seriesFilter && !modelFilter} className="rounded-lg border border-indigo-200 bg-white px-2.5 py-1.5 text-[11px] font-semibold text-indigo-700 hover:border-indigo-400 disabled:cursor-not-allowed disabled:opacity-40 dark:border-indigo-800 dark:bg-indigo-950/30 dark:text-indigo-200">{tx('ai.catalog.browse.clear')}</button>
          </div>
          {hierarchy.length === 0 ? (
            <div className="mt-3 rounded-xl border border-dashed border-indigo-200 bg-white/60 px-3 py-4 text-center text-xs text-indigo-700/60 dark:border-indigo-800 dark:bg-indigo-950/20 dark:text-indigo-300/60">{tx('ai.catalog.browse.empty')}</div>
          ) : (
            <div className="mt-3 grid gap-3 xl:grid-cols-4">
              <div className="min-w-0 rounded-xl border border-indigo-100 bg-white/70 p-3 dark:border-indigo-900/50 dark:bg-slate-900/30">
                <div className="mb-2 flex items-center justify-between gap-2"><span className="text-[10px] font-bold uppercase tracking-[0.12em] text-indigo-700/70 dark:text-indigo-300/70">{tx('ai.catalog.hierarchy.vendor')}</span><span className="text-[10px] text-slate-400">{hierarchy.length}</span></div>
                <div className="space-y-1">
                  {hierarchy.map((item) => <button key={item.vendor_id} type="button" onClick={() => selectHierarchyVendor(item.vendor_id)} aria-pressed={vendorFilter === item.vendor_id && !familyFilter} className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-xs transition ${vendorFilter === item.vendor_id ? 'bg-indigo-600 font-semibold text-white' : 'text-slate-700 hover:bg-indigo-50 dark:text-slate-200 dark:hover:bg-indigo-950/40'}`}><span className="min-w-0 flex-1 truncate">{item.vendor_name}</span><span className="text-[10px] opacity-70">{item.model_count}</span><ChevronRight className="h-3.5 w-3.5 shrink-0 opacity-60" /></button>)}
                </div>
              </div>
              <div className="min-w-0 rounded-xl border border-indigo-100 bg-white/70 p-3 dark:border-indigo-900/50 dark:bg-slate-900/30">
                <div className="mb-2 flex items-center justify-between gap-2"><span className="text-[10px] font-bold uppercase tracking-[0.12em] text-indigo-700/70 dark:text-indigo-300/70">{tx('ai.catalog.hierarchy.family')}</span><span className="text-[10px] text-slate-400">{selectedVendorNode?.families.length || 0}</span></div>
               {selectedVendorNode ? <div className="space-y-1">{selectedVendorNode.families.map((item) => <button key={item.family_code} type="button" onClick={() => selectHierarchyFamily(selectedVendorNode.vendor_id, item.family_code)} aria-pressed={familyFilter === item.family_code && !seriesFilter} className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-xs transition ${familyFilter === item.family_code ? 'bg-indigo-600 font-semibold text-white' : 'text-slate-700 hover:bg-indigo-50 dark:text-slate-200 dark:hover:bg-indigo-950/40'}`}><span className="min-w-0 flex-1 truncate">{item.family_name}</span><span className="font-mono text-[10px] opacity-70">{item.family_code}</span><span className="text-[10px] opacity-70">{item.model_count}</span></button>)}</div> : <div className="py-5 text-center text-[11px] text-slate-400">{tx('ai.catalog.browse.selectVendor')}</div>}
              </div>
              <div className="min-w-0 rounded-xl border border-indigo-100 bg-white/70 p-3 dark:border-indigo-900/50 dark:bg-slate-900/30">
                <div className="mb-2 flex items-center justify-between gap-2"><span className="text-[10px] font-bold uppercase tracking-[0.12em] text-indigo-700/70 dark:text-indigo-300/70">{tx('ai.catalog.hierarchy.series')}</span><span className="text-[10px] text-slate-400">{selectedFamilyNode?.series.length || 0}</span></div>
               {selectedFamilyNode ? <div className="space-y-1">{selectedFamilyNode.series.map((item) => <button key={item.series_code} type="button" onClick={() => selectHierarchySeries(selectedVendorNode!.vendor_id, selectedFamilyNode.family_code, item.series_code)} aria-pressed={seriesFilter === item.series_code && !modelFilter} className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-xs transition ${seriesFilter === item.series_code ? 'bg-indigo-600 font-semibold text-white' : 'text-slate-700 hover:bg-indigo-50 dark:text-slate-200 dark:hover:bg-indigo-950/40'}`}><span className="min-w-0 flex-1 truncate">{item.series_name}</span><span className="font-mono text-[10px] opacity-70">{item.series_code}</span><span className="text-[10px] opacity-70">{item.model_count}</span></button>)}</div> : <div className="py-5 text-center text-[11px] text-slate-400">{tx('ai.catalog.browse.selectFamily')}</div>}
              </div>
              <div className="min-w-0 rounded-xl border border-indigo-100 bg-white/70 p-3 dark:border-indigo-900/50 dark:bg-slate-900/30">
                <div className="mb-2 flex items-center justify-between gap-2"><span className="text-[10px] font-bold uppercase tracking-[0.12em] text-indigo-700/70 dark:text-indigo-300/70">{tx('ai.catalog.hierarchy.model')}</span><span className="text-[10px] text-slate-400">{selectedSeriesNode?.models.length || 0}</span></div>
                {selectedSeriesNode ? <div className="space-y-1">{selectedSeriesNode.models.map((item) => <button key={item.product_model_id} type="button" onClick={() => selectHierarchyModel(selectedVendorNode!.vendor_id, selectedFamilyNode!.family_code, selectedSeriesNode.series_code, item.model_code)} aria-pressed={modelFilter === item.model_code} className={`flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left text-xs transition ${modelFilter === item.model_code ? 'bg-indigo-600 font-semibold text-white' : 'text-slate-700 hover:bg-indigo-50 dark:text-slate-200 dark:hover:bg-indigo-950/40'}`}><span className="min-w-0 flex-1"><span className="block truncate">{item.model_code}</span><span className="mt-0.5 block truncate text-[10px] opacity-65">{item.display_name}</span></span><span className={`mt-0.5 shrink-0 rounded-full px-1.5 py-0.5 text-[9px] ${modelFilter === item.model_code ? 'bg-white/20' : statusTone(item.status)}`}>{item.status}</span></button>)}</div> : <div className="py-5 text-center text-[11px] text-slate-400">{tx('ai.catalog.browse.selectSeries')}</div>}
              </div>
            </div>
          )}
          {(vendorFilter || familyFilter || seriesFilter || modelFilter) && <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[10px] text-indigo-800 dark:text-indigo-200"><span className="font-semibold">{tx('ai.catalog.browse.path')}</span>{[selectedVendorNode?.vendor_name || vendorFilter, selectedFamilyNode?.family_name || familyFilter, selectedSeriesNode?.series_name || seriesFilter, modelFilter].filter(Boolean).map((item, index) => <React.Fragment key={`${item}-${index}`}><span className="rounded-full bg-white px-2 py-1 font-mono dark:bg-indigo-950/50">{item}</span>{index < [selectedVendorNode?.vendor_name || vendorFilter, selectedFamilyNode?.family_name || familyFilter, selectedSeriesNode?.series_name || seriesFilter, modelFilter].filter(Boolean).length - 1 && <ChevronRight className="h-3 w-3 opacity-50" />}</React.Fragment>)}</div>}
        </section>
      )}

      <section className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2"><Filter className="h-4 w-4 text-indigo-500" /><span className="text-sm font-semibold text-gray-800 dark:text-gray-100">{tx('ai.catalog.filter.title')}</span></div>
          <div className="flex rounded-xl bg-gray-100 p-1 dark:bg-gray-900">
            <button type="button" onClick={() => changePanel('models')} className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${panel === 'models' ? 'bg-white text-indigo-700 shadow-sm dark:bg-gray-700 dark:text-indigo-300' : 'text-gray-500'}`}><Database className="mr-1 inline h-3.5 w-3.5" />{tx('ai.catalog.filter.models')}</button>
            <button type="button" onClick={() => changePanel('aliases')} className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${panel === 'aliases' ? 'bg-white text-indigo-700 shadow-sm dark:bg-gray-700 dark:text-indigo-300' : 'text-gray-500'}`}><Tag className="mr-1 inline h-3.5 w-3.5" />{tx('ai.catalog.filter.aliases')}</button>
          </div>
        </div>
        <form onSubmit={applySearch} className="mb-3 flex flex-wrap gap-2">
          <div className="relative min-w-[260px] flex-1"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-gray-400" /><input value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder={panel === 'models' ? tx('ai.catalog.filter.searchModels') : tx('ai.catalog.filter.searchAliases')} className="w-full rounded-xl border border-gray-200 bg-white py-2 pl-9 pr-3 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100" /></div>
          <button type="submit" className="rounded-xl bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700">{tx('ai.catalog.filter.search')}</button>
        </form>
        {panel === 'models' ? <div className="grid gap-2 md:grid-cols-4">
          <label className="text-[11px] font-semibold text-gray-500">{tx('ai.catalog.filter.vendor')}<select value={vendorFilter} onChange={(event) => { setVendorFilter(event.target.value); setPage(1); }} className="mt-1 w-full rounded-lg border border-gray-200 bg-white px-2.5 py-2 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"><option value="">{tx('ai.catalog.filter.allVendor')}</option>{vendors.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
          <label className="text-[11px] font-semibold text-gray-500">{tx('ai.catalog.filter.family')}<select value={familyFilter} onChange={(event) => { setFamilyFilter(event.target.value); setPage(1); }} className="mt-1 w-full rounded-lg border border-gray-200 bg-white px-2.5 py-2 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"><option value="">{tx('ai.catalog.filter.allFamily')}</option>{families.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
          <label className="text-[11px] font-semibold text-gray-500">{tx('ai.catalog.filter.series')}<select value={seriesFilter} onChange={(event) => { setSeriesFilter(event.target.value); setPage(1); }} className="mt-1 w-full rounded-lg border border-gray-200 bg-white px-2.5 py-2 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"><option value="">{tx('ai.catalog.filter.allSeries')}</option>{series.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
          <label className="text-[11px] font-semibold text-gray-500">{tx('ai.catalog.filter.softwareVersion')}<select value={softwareVersionFilter} onChange={(event) => { setSoftwareVersionFilter(event.target.value); setPage(1); }} className="mt-1 w-full rounded-lg border border-gray-200 bg-white px-2.5 py-2 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"><option value="">{tx('ai.catalog.filter.allVersion')}</option>{softwareVersions.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
        </div> : <div className="max-w-xs"><label className="text-[11px] font-semibold text-gray-500">{tx('ai.catalog.filter.aliasKind')}<select value={kindFilter} onChange={(event) => { setKindFilter(event.target.value); setPage(1); }} className="mt-1 w-full rounded-lg border border-gray-200 bg-white px-2.5 py-2 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"><option value="">{tx('ai.catalog.filter.allKinds')}</option>{Object.entries(KIND_LABELS).map(([key, labelKey]) => <option key={key} value={key}>{tx(labelKey)}</option>)}</select></label></div>}
        <div className="mt-3 flex justify-end"><button type="button" onClick={clearCatalogFilters} className="rounded-lg border border-gray-200 px-3 py-2 text-xs font-semibold text-gray-600 hover:border-indigo-300 dark:border-gray-600 dark:text-gray-300">{tx('ai.common.clearFilters')}</button></div>
      </section>

      {panel === 'models' ? (
        <section className="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-800">
           <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3 dark:border-gray-700"><div><h2 className="text-sm font-semibold text-gray-800 dark:text-gray-100">{tx('ai.catalog.master.title')}</h2><p className="text-[11px] text-gray-500">{tx('ai.catalog.master.summary', { total, page })}</p></div><Eye className="h-4 w-4 text-gray-400" /></div>
           {loading ? <div className="flex items-center justify-center gap-2 p-10 text-xs text-gray-400"><Loader2 className="h-4 w-4 animate-spin" />{tx('ai.common.loading')}</div> : <div className="overflow-x-auto"><table className="nx-data-table min-w-full text-left"><thead><tr><th>{tx('ai.catalog.master.vendorFamily')}</th><th>{tx('ai.catalog.master.series')}</th><th>{tx('ai.catalog.master.model')}</th><th>{tx('ai.catalog.master.os')}</th><th>{tx('ai.catalog.master.version')}</th><th>{tx('ai.catalog.master.status')}</th>{canManageCatalog && <th>{tx('ai.catalog.master.actions')}</th>}</tr></thead><tbody>{models.map((item) => <tr key={item.product_model_id}><td><div className="font-semibold text-gray-800 dark:text-gray-100">{item.vendor_name}</div><div className="nx-micro-text text-gray-500">{item.family_code}</div></td><td><div className="font-medium text-gray-700 dark:text-gray-200">{item.series_name}</div><div className="nx-micro-text text-gray-500">{item.series_code}</div></td><td><div className="font-semibold text-indigo-700 dark:text-indigo-300">{item.model_code}</div><div className="nx-micro-text max-w-[260px] truncate text-gray-500">{item.product_model_id}</div></td><td><div>{scopeValue(item, 'os_family', tx('ai.common.na'))}</div><div className="nx-micro-text text-gray-500">{scopeValue(item, 'software_train', tx('ai.common.na'))}</div></td><td><div>{scopeValue(item, 'primary_version', tx('ai.common.na'))}</div><div className="nx-micro-text text-gray-500">{tx('ai.catalog.master.compatible', { value: scopeValue(item, 'compatibility_version', tx('ai.common.na')) })}</div></td><td><span className={`nx-micro-text rounded-full px-2 py-1 font-semibold ${statusTone(item.status)}`}>{catalogLabel(tx, CATALOG_STATUS_LABELS, item.status)}</span><div className="mt-1 nx-micro-text text-gray-500">{catalogLabel(tx, CATALOG_STATUS_LABELS, item.review_status)}</div></td>{canManageCatalog && <td>{item.mutable ? <div className="flex items-center gap-1"><button type="button" onClick={() => openEditCatalogModel(item)} className="rounded-lg p-1.5 text-indigo-600 hover:bg-indigo-50" aria-label={`${tx('ai.catalog.master.edit')} ${item.display_name}`} title={tx('ai.catalog.master.edit')}><Pencil className="h-4 w-4" /></button>{item.status !== 'deleted' && <button type="button" onClick={() => void archiveCatalogModel(item)} className="rounded-lg p-1.5 text-red-600 hover:bg-red-50" aria-label={`${tx('ai.catalog.master.archive')} ${item.display_name}`} title={tx('ai.catalog.master.archive')}><Trash2 className="h-4 w-4" /></button>}</div> : <span className="nx-micro-text text-gray-400">{tx('ai.catalog.master.readOnly')}</span>}</td>}</tr>)}</tbody></table></div>}
           <Pagination currentPage={page} totalItems={total} itemsPerPage={pageSize} onPageChange={setPage} onItemsPerPageChange={(size) => { setPageSize(size); setPage(1); }} language={language} alwaysVisible />
        </section>
      ) : (
        <section className="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-800">
           <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3 dark:border-gray-700"><div><h2 className="text-sm font-semibold text-gray-800 dark:text-gray-100">{tx('ai.catalog.alias.title')}</h2><p className="text-[11px] text-gray-500">{tx('ai.catalog.alias.body')}</p></div><Tag className="h-4 w-4 text-gray-400" /></div>
           {loading ? <div className="flex items-center justify-center gap-2 p-10 text-xs text-gray-400"><Loader2 className="h-4 w-4 animate-spin" />{tx('ai.common.loading')}</div> : <div className="overflow-x-auto"><table className="nx-data-table min-w-full text-left"><thead><tr><th>{tx('ai.catalog.alias.alias')}</th><th>{tx('ai.catalog.alias.kind')}</th><th>{tx('ai.catalog.alias.target')}</th><th>{tx('ai.catalog.alias.review')}</th><th>{tx('ai.catalog.alias.action')}</th></tr></thead><tbody>{aliases.map((item) => <tr key={item.id}><td><div className="font-semibold text-gray-800 dark:text-gray-100">{item.alias}</div><div className="nx-micro-text text-gray-500">{item.normalized_alias}</div></td><td><span className="nx-micro-text rounded-full bg-indigo-50 px-2 py-1 font-semibold text-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-300">{catalogLabel(tx, KIND_LABELS, item.alias_kind)}</span></td><td><div className="font-medium text-gray-700 dark:text-gray-200">{item.model?.model_code || item.product_model_id}</div><div className="nx-micro-text text-gray-500">{item.model?.vendor_id} / {item.model?.series_code}</div></td><td><span className={`nx-micro-text rounded-full px-2 py-1 font-semibold ${statusTone(item.conflict_status)}`}>{catalogLabel(tx, CATALOG_STATUS_LABELS, item.conflict_status)}</span><div className="mt-1 nx-micro-text text-gray-500">{catalogLabel(tx, CATALOG_STATUS_LABELS, item.seed_status)}</div></td><td><button type="button" onClick={() => setQuery(item.alias)} className="nx-action-button nx-action-button--sm border-gray-200 text-gray-600 hover:border-indigo-300 dark:border-gray-600 dark:text-gray-300">{tx('ai.catalog.alias.useForResolution')}</button></td></tr>)}</tbody></table></div>}
           <Pagination currentPage={page} totalItems={total} itemsPerPage={pageSize} onPageChange={setPage} onItemsPerPageChange={(size) => { setPageSize(size); setPage(1); }} language={language} alwaysVisible />
        </section>
      )}

      <section className="rounded-2xl border border-indigo-100 bg-indigo-50/60 p-4 dark:border-indigo-900/50 dark:bg-indigo-950/20">
        <div className="mb-3 flex items-center gap-2"><Sparkles className="h-4 w-4 text-indigo-500" /><h2 className="text-sm font-semibold text-indigo-900 dark:text-indigo-200">{tx('ai.catalog.resolve.title')}</h2><span className="rounded-full bg-white/70 px-2 py-1 text-[10px] font-semibold text-indigo-600 dark:bg-indigo-950/50 dark:text-indigo-300">dry-run</span></div>
        <form onSubmit={(event) => void runResolution(event)} className="flex flex-wrap gap-2"><div className="relative min-w-[240px] flex-1"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-gray-400" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={tx('ai.catalog.resolve.input')} className="w-full rounded-xl border border-indigo-200 bg-white py-2 pl-9 pr-3 text-sm outline-none focus:border-indigo-400 dark:border-indigo-800 dark:bg-gray-900 dark:text-white" /></div><button type="submit" disabled={resolving || !query.trim()} className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2 text-xs font-semibold text-white shadow-sm hover:bg-indigo-700 disabled:opacity-50">{resolving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}{tx('ai.catalog.resolve.action')}</button></form>
        {resolution && <div className="mt-3 rounded-xl border border-indigo-100 bg-white p-3 dark:border-indigo-900/60 dark:bg-gray-900"><div className="flex flex-wrap items-center gap-2 text-xs"><span className={`rounded-full px-2 py-1 font-semibold ${resolution.outcome === 'unique' ? 'bg-emerald-50 text-emerald-700' : resolution.outcome === 'unknown' ? 'bg-gray-100 text-gray-600' : 'bg-amber-50 text-amber-700'}`}>{catalogLabel(tx, RESOLUTION_OUTCOME_LABELS, resolution.outcome)}</span><span className="text-gray-500">{tx('ai.catalog.resolve.candidates', { count: resolution.candidate_count })}</span>{resolution.requires_clarification && <span className="font-semibold text-amber-600">{tx('ai.catalog.resolve.clarify')}</span>}<span className="ml-auto text-[10px] text-gray-400">{resolution.driver_selection_allowed ? tx('ai.catalog.resolve.allowed') : tx('ai.catalog.resolve.blocked')}</span></div>{resolution.candidates.length > 0 && <div className="mt-2 grid gap-2 md:grid-cols-2">{resolution.candidates.map((candidate) => <div key={String(candidate.id || candidate.product_model_id)} className="rounded-lg border border-gray-100 p-2 text-xs dark:border-gray-700"><div className="font-semibold text-gray-800 dark:text-gray-100">{candidate.model?.model_code || String(candidate.product_model_id || tx('ai.catalog.resolve.unknown'))}</div><div className="text-[11px] text-gray-500">{candidate.model?.vendor_id} / {candidate.model?.series_code} · {catalogLabel(tx, KIND_LABELS, String(candidate.alias_kind || ''))}</div></div>)}</div>}</div>}
      </section>

      {catalogModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="catalog-model-editor-title">
          <div className="flex max-h-[calc(100vh-2rem)] w-full max-w-3xl flex-col overflow-hidden rounded-3xl bg-white shadow-2xl dark:bg-slate-900">
            <div className="flex items-start justify-between gap-3 border-b border-gray-100 px-5 py-4 dark:border-gray-800">
              <div>
                <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.14em] text-indigo-500"><Database className="h-4 w-4" />{tx(editingModel ? 'ai.catalog.editor.editEyebrow' : 'ai.catalog.editor.addEyebrow')}</div>
                <h3 id="catalog-model-editor-title" className="mt-2 text-xl font-bold text-gray-900 dark:text-white">{editingModel ? editingModel.display_name : tx('ai.catalog.editor.title')}</h3>
                <p className="mt-1 text-xs text-gray-500">{tx('ai.catalog.editor.body')}</p>
              </div>
              <button type="button" onClick={() => setCatalogModalOpen(false)} aria-label={tx('ai.catalog.editor.close')} className="rounded-xl p-2 text-gray-400 hover:bg-gray-100"><X className="h-5 w-5" /></button>
            </div>
            <form onSubmit={submitCatalogModel} className="min-h-0 overflow-y-auto px-5 py-5">
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {([['vendor_code', 'ai.catalog.editor.vendorCode'], ['vendor_name', 'ai.catalog.editor.vendorName'], ['family_code', 'ai.catalog.editor.familyCode'], ['family_name', 'ai.catalog.editor.familyName'], ['series_code', 'ai.catalog.editor.seriesCode'], ['series_name', 'ai.catalog.editor.seriesName'], ['model_code', 'ai.catalog.editor.modelCode'], ['display_name', 'ai.catalog.editor.displayName']] as const).map(([key, labelKey]) => (
                  <label key={key} className="text-xs font-bold text-gray-700 dark:text-gray-300">
                    <span>{tx(labelKey)}{editingModel && ['vendor_code', 'vendor_name', 'family_code', 'family_name', 'series_code', 'series_name', 'model_code'].includes(key) ? tx('ai.catalog.editor.readOnly') : ''}</span>
                    <input required={!editingModel || key === 'display_name'} disabled={Boolean(editingModel && key !== 'display_name')} value={catalogForm[key]} onChange={(event) => setCatalogForm((current) => ({ ...current, [key]: event.target.value }))} className="mt-1.5 w-full rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-sm font-normal text-gray-900 outline-none focus:border-indigo-500 disabled:bg-gray-100 dark:border-gray-700 dark:bg-gray-950 dark:text-white" />
                  </label>
                ))}
                <label className="text-xs font-bold text-gray-700 dark:text-gray-300">{tx('ai.catalog.editor.status')}<select value={catalogForm.status} onChange={(event) => setCatalogForm((current) => ({ ...current, status: event.target.value as typeof current.status }))} className="mt-1.5 w-full rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-sm font-normal dark:border-gray-700 dark:bg-gray-950 dark:text-white">{(['draft', 'active', 'disabled', 'archived'] as const).map((status) => <option key={status} value={status}>{catalogLabel(tx, CATALOG_STATUS_LABELS, status)}</option>)}</select></label>
                <label className="text-xs font-bold text-gray-700 dark:text-gray-300">{tx('ai.catalog.editor.softwareVersion')}<input value={catalogForm.software_version} onChange={(event) => setCatalogForm((current) => ({ ...current, software_version: event.target.value }))} placeholder={tx('ai.catalog.editor.versionPlaceholder')} className="mt-1.5 w-full rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-sm font-normal dark:border-gray-700 dark:bg-gray-950 dark:text-white" /></label>
                <label className="text-xs font-bold text-gray-700 dark:text-gray-300 sm:col-span-2 lg:col-span-3">{tx('ai.catalog.editor.description')}<textarea rows={2} value={catalogForm.description} onChange={(event) => setCatalogForm((current) => ({ ...current, description: event.target.value }))} className="mt-1.5 w-full rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-sm font-normal dark:border-gray-700 dark:bg-gray-950 dark:text-white" /></label>
                <label className="text-xs font-bold text-gray-700 dark:text-gray-300 sm:col-span-2 lg:col-span-3">{tx(editingModel ? 'ai.catalog.editor.reason' : 'ai.catalog.editor.reasonOptional')}<textarea required={Boolean(editingModel)} rows={2} value={catalogForm.change_reason} onChange={(event) => setCatalogForm((current) => ({ ...current, change_reason: event.target.value }))} placeholder={tx('ai.catalog.editor.reasonPlaceholder')} className="mt-1.5 w-full rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-sm font-normal dark:border-gray-700 dark:bg-gray-950 dark:text-white" /></label>
              </div>
              <div className="mt-5 flex justify-end gap-2 border-t border-gray-100 pt-4 dark:border-gray-800"><button type="button" onClick={() => setCatalogModalOpen(false)} className="rounded-xl px-4 py-2.5 text-sm font-semibold text-gray-500">{tx('ai.catalog.editor.cancel')}</button><button type="submit" disabled={catalogSubmitting} className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60"><RefreshCw className={catalogSubmitting ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />{catalogSubmitting ? tx('ai.catalog.editor.saving') : editingModel ? tx('ai.catalog.editor.save') : tx('ai.catalog.editor.create')}</button></div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default ProductCatalogManagementTab;
