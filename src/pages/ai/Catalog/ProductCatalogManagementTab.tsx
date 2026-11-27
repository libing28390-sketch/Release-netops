import { DataTable } from '../../../components/DataTable';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  ChevronRight,
  Database,
  Pencil,
  Loader2,
  Plus,
  RefreshCw,
  Search,
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
import { useEscapeClose } from '../../../hooks/useEscapeClose';
import { useFocusTrap } from '../../../hooks/useFocusTrap';
import { aiAdminText } from '../../../i18n/aiAdmin';
import { fetchAllPaginatedItems } from '../../../utils/pagination';

import { ActionIconButton } from '../../../components/ui/ActionIconButton';
import { TableActionCell, TableActionHeader } from '../../../components/ui/TableActionColumn';
import { PageHeader } from '../../../components/ui/PageHeader';
import { SummaryBar } from '../../../components/ui/SummaryBar';
import { Panel, PanelHeader } from '../../../components/ui/Panel';
import { StatusBadge, type StatusTone } from '../../../components/ui/StatusBadge';
import { EmptyState } from '../../../components/ui/EmptyState';
import { catalogCopy } from './ProductCatalogManagementTab.copy';
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

function statusTone(status: string): StatusTone {
  if (status === 'active' || status === 'manual_approved') return 'success';
  if (status === 'ambiguous_pending_review' || status === 'draft' || status === 'pending_review') return 'warning';
  if (status === 'rejected' || status === 'disabled') return 'danger';
  return 'neutral';
}

function resolutionTone(outcome: string): StatusTone {
  if (outcome === 'unique') return 'success';
  if (outcome === 'unknown') return 'neutral';
  return 'warning';
}

// Shared control styles (token classes, light/dark via --ui-* variables).
const INPUT_CLASS = 'w-full rounded-lg border border-line bg-surface px-3 py-2 text-[13px] text-fg outline-none placeholder:text-fg-subtle focus:border-accent focus-visible:ring-2 focus-visible:ring-accent/30 disabled:bg-surface-muted disabled:text-fg-muted';
const SELECT_CLASS = 'mt-1 w-full rounded-lg border border-line bg-surface px-2.5 py-2 text-[13px] text-fg outline-none focus:border-accent';
const FIELD_LABEL_CLASS = 'text-xs font-medium text-fg-muted';
const SECONDARY_BUTTON = 'inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-1.5 text-[13px] font-medium text-fg hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-50';
const PRIMARY_BUTTON = 'inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-[13px] font-medium text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50';
const HIERARCHY_ITEM = 'flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[13px] transition-colors';
const HIERARCHY_ACTIVE = 'bg-accent-subtle font-medium text-accent';
const HIERARCHY_IDLE = 'text-fg hover:bg-surface-muted';

export const ProductCatalogManagementTab: React.FC = () => {
  const { language, showToast, currentUser } = useCoreApp();
  const tx = (key: string, variables?: TextVariables) => aiAdminText(key, language, variables);
  const copy = catalogCopy(language);
  const canManageCatalog = currentUser?.role === 'Administrator' || currentUser?.role_profile === 'Platform Maintainer';
  const [panel, setPanel] = useState<CatalogPanel>('models');
  const [models, setModels] = useState<KnowledgeCatalogModel[]>([]);
  const [aliases, setAliases] = useState<KnowledgeCatalogAlias[]>([]);
  const [totalConflictCount, setTotalConflictCount] = useState<number | null>(null);
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
  const [pageSize, setPageSize] = useState(10);
  const [total, setTotal] = useState(0);
  const [facets, setFacets] = useState({ vendors: [] as string[], families: [] as string[], series: [] as string[], software_versions: [] as string[] });
  const [hierarchy, setHierarchy] = useState<KnowledgeCatalogHierarchyVendor[]>([]);
  const [query, setQuery] = useState('CE68');
  const [resolution, setResolution] = useState<KnowledgeCatalogResolveResponse | null>(null);
  const [resolving, setResolving] = useState(false);
  const [catalogReadOnly, setCatalogReadOnly] = useState(true);
  const [catalogModalOpen, setCatalogModalOpen] = useState(false);
  const catalogDialogRef = useRef<HTMLDivElement>(null);
  useEscapeClose(catalogModalOpen, () => setCatalogModalOpen(false));
  useFocusTrap(catalogDialogRef, catalogModalOpen);
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
        setTotalConflictCount(Array.isArray(aliasResponse.conflicts) ? aliasResponse.conflicts.length : null);
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
  const conflictCount = totalConflictCount ?? aliases.filter((item) => item.conflict_status === 'ambiguous_pending_review').length;

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

  const exportCatalogModels = async () => {
    const params = new URLSearchParams({
      search: appliedSearch,
      vendor_id: vendorFilter,
      family_code: familyFilter,
      series_code: seriesFilter,
      model: modelFilter,
      software_version: softwareVersionFilter,
      status: 'all',
      sort_by: 'created_at',
      sort_order: 'desc',
    });
    const allModels = await fetchAllPaginatedItems<KnowledgeCatalogModel>('/api/knowledge/catalog', params, 100);
    const na = tx('ai.common.na');
    return {
      headers: [
        tx('ai.catalog.filter.vendor'),
        tx('ai.catalog.editor.familyName'),
        tx('ai.catalog.editor.familyCode'),
        tx('ai.catalog.editor.seriesName'),
        tx('ai.catalog.editor.seriesCode'),
        tx('ai.catalog.editor.modelCode'),
        language === 'zh' ? 'OS 系列' : 'OS Family',
        language === 'zh' ? '软件 Train' : 'Software Train',
        tx('ai.catalog.editor.softwareVersion'),
        tx('ai.knowledge.ingestion.compatibleVersion'),
        tx('ai.catalog.master.status'),
        language === 'zh' ? '审核状态' : 'Review Status',
      ],
      rows: allModels.map((model) => [
        model.vendor_name || na,
        model.family_name || na,
        model.family_code || '',
        model.series_name || na,
        model.series_code || '',
        model.model_code || '',
        String(model.software_scope?.os_family ?? na),
        String(model.software_scope?.software_train ?? na),
        String(model.software_scope?.primary_version ?? na),
        String(model.software_scope?.compatibility_version ?? na),
        catalogLabel(tx, CATALOG_STATUS_LABELS, model.status),
        catalogLabel(tx, CATALOG_STATUS_LABELS, model.review_status),
      ]),
    };
  };

  const exportCatalogAliases = async () => {
    const params = new URLSearchParams({
      alias: appliedSearch,
      alias_kind: kindFilter,
      conflict_status: 'all',
      sort_by: 'alias',
      sort_order: 'asc',
    });
    const allAliases = await fetchAllPaginatedItems<KnowledgeCatalogAlias>('/api/knowledge/catalog/aliases', params, 100);
    return {
      headers: [
        tx('ai.catalog.alias.alias'),
        language === 'zh' ? '规范化别名' : 'Normalized Alias',
        tx('ai.catalog.alias.kind'),
        tx('ai.catalog.alias.target'),
        tx('ai.catalog.filter.vendor'),
        tx('ai.catalog.editor.seriesCode'),
        language === 'zh' ? '冲突状态' : 'Conflict Status',
        language === 'zh' ? '种子状态' : 'Seed Status',
      ],
      rows: allAliases.map((alias) => [
        alias.alias,
        alias.normalized_alias || '',
        catalogLabel(tx, KIND_LABELS, alias.alias_kind),
        alias.model?.model_code || '',
        alias.model?.vendor_name || '',
        alias.model?.series_code || '',
        catalogLabel(tx, CATALOG_STATUS_LABELS, alias.conflict_status),
        catalogLabel(tx, CATALOG_STATUS_LABELS, alias.seed_status),
      ]),
    };
  };

  const hasHierarchySelection = Boolean(vendorFilter || familyFilter || seriesFilter || modelFilter);
  const hierarchyPath = [selectedVendorNode?.vendor_name || vendorFilter, selectedFamilyNode?.family_name || familyFilter, selectedSeriesNode?.series_name || seriesFilter, modelFilter].filter(Boolean);

  const hierarchyColumn = (titleKey: string, count: number, body: React.ReactNode) => (
    <div className="min-w-0 rounded-lg border border-line bg-surface-muted/40 p-2.5">
      <div className="mb-1.5 flex items-center justify-between gap-2 px-1">
        <span className="text-xs font-medium text-fg-muted">{tx(titleKey)}</span>
        <span className="text-xs tabular-nums text-fg-subtle" title={`${count} ${copy.hierarchyCount}`}>{count}</span>
      </div>
      {body}
    </div>
  );

  const hierarchyHint = (key: string) => <div className="px-1 py-5 text-center text-xs text-fg-subtle">{tx(key)}</div>;

  return (
    <div className="w-full space-y-4 pb-8">
      <PageHeader
        title={tx('ai.catalog.title')}
        description={tx('ai.catalog.description')}
        info={tx(catalogReadOnly ? 'ai.catalog.readOnlyBody' : 'ai.catalog.customBody')}
        infoLabel={copy.infoLabel}
        actions={(
          <>
            <button type="button" onClick={() => void loadCatalog()} disabled={loading} className={SECONDARY_BUTTON}>
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin motion-reduce:animate-none' : ''}`} aria-hidden="true" />{tx('ai.common.refresh')}
            </button>
            {canManageCatalog && panel === 'models' && (
              <button type="button" onClick={openCreateCatalogModel} className={PRIMARY_BUTTON}>
                <Plus className="h-4 w-4" aria-hidden="true" />{tx('ai.catalog.add')}
              </button>
            )}
          </>
        )}
      />

      <SummaryBar
        label={copy.summaryLabel}
        items={[
          { key: 'total', value: loading ? '…' : total, label: panel === 'models' ? copy.modelsTotal : copy.aliasesTotal, tone: 'accent' },
          conflictCount > 0
            ? { key: 'conflicts', value: conflictCount, label: copy.conflicts, tone: 'warning' }
            : { key: 'conflicts', value: '0', label: copy.noConflicts, tone: 'success' },
          { key: 'mode', value: catalogReadOnly ? copy.seedMode : copy.customMode, label: '', tone: catalogReadOnly ? 'neutral' : 'accent' },
        ]}
      />

      {error && (
        <div role="alert" className="flex items-center gap-2 rounded-lg border border-danger/30 bg-danger-subtle px-3 py-2 text-[13px] text-danger">
          <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />{error}
        </div>
      )}

      {panel === 'models' && (
        <Panel aria-label={tx('ai.catalog.browse.aria')}>
          <PanelHeader
            title={tx('ai.catalog.browse.title')}
            description={tx('ai.catalog.browse.body')}
            actions={<button type="button" onClick={clearCatalogFilters} disabled={!hasHierarchySelection} className={SECONDARY_BUTTON}>{tx('ai.catalog.browse.clear')}</button>}
          />
          <div className="p-3">
            {hierarchy.length === 0 ? (
              <div className="rounded-lg border border-dashed border-line-strong px-3 py-4 text-center text-[13px] text-fg-muted">{tx('ai.catalog.browse.empty')}</div>
            ) : (
              <div className="grid gap-2.5 xl:grid-cols-4">
                {hierarchyColumn('ai.catalog.hierarchy.vendor', hierarchy.length, (
                  <div className="space-y-0.5">
                    {hierarchy.map((item) => (
                      <button key={item.vendor_id} type="button" onClick={() => selectHierarchyVendor(item.vendor_id)} aria-pressed={vendorFilter === item.vendor_id && !familyFilter} className={`${HIERARCHY_ITEM} ${vendorFilter === item.vendor_id ? HIERARCHY_ACTIVE : HIERARCHY_IDLE}`}>
                        <span className="min-w-0 flex-1 truncate" title={item.vendor_name}>{item.vendor_name}</span>
                        <span className="text-xs tabular-nums text-fg-subtle">{item.model_count}</span>
                        <ChevronRight className="h-3.5 w-3.5 shrink-0 text-fg-subtle" aria-hidden="true" />
                      </button>
                    ))}
                  </div>
                ))}
                {hierarchyColumn('ai.catalog.hierarchy.family', selectedVendorNode?.families.length || 0, selectedVendorNode ? (
                  <div className="space-y-0.5">
                    {selectedVendorNode.families.map((item) => (
                      <button key={item.family_code} type="button" onClick={() => selectHierarchyFamily(selectedVendorNode.vendor_id, item.family_code)} aria-pressed={familyFilter === item.family_code && !seriesFilter} className={`${HIERARCHY_ITEM} ${familyFilter === item.family_code ? HIERARCHY_ACTIVE : HIERARCHY_IDLE}`}>
                        <span className="min-w-0 flex-1 truncate" title={item.family_name}>{item.family_name}</span>
                        <span className="font-mono text-xs text-fg-subtle">{item.family_code}</span>
                        <span className="text-xs tabular-nums text-fg-subtle">{item.model_count}</span>
                      </button>
                    ))}
                  </div>
                ) : hierarchyHint('ai.catalog.browse.selectVendor'))}
                {hierarchyColumn('ai.catalog.hierarchy.series', selectedFamilyNode?.series.length || 0, selectedFamilyNode ? (
                  <div className="space-y-0.5">
                    {selectedFamilyNode.series.map((item) => (
                      <button key={item.series_code} type="button" onClick={() => selectHierarchySeries(selectedVendorNode!.vendor_id, selectedFamilyNode.family_code, item.series_code)} aria-pressed={seriesFilter === item.series_code && !modelFilter} className={`${HIERARCHY_ITEM} ${seriesFilter === item.series_code ? HIERARCHY_ACTIVE : HIERARCHY_IDLE}`}>
                        <span className="min-w-0 flex-1 truncate" title={item.series_name}>{item.series_name}</span>
                        <span className="font-mono text-xs text-fg-subtle">{item.series_code}</span>
                        <span className="text-xs tabular-nums text-fg-subtle">{item.model_count}</span>
                      </button>
                    ))}
                  </div>
                ) : hierarchyHint('ai.catalog.browse.selectFamily'))}
                {hierarchyColumn('ai.catalog.hierarchy.model', selectedSeriesNode?.models.length || 0, selectedSeriesNode ? (
                  <div className="space-y-0.5">
                    {selectedSeriesNode.models.map((item) => (
                      <button key={item.product_model_id} type="button" onClick={() => selectHierarchyModel(selectedVendorNode!.vendor_id, selectedFamilyNode!.family_code, selectedSeriesNode.series_code, item.model_code)} aria-pressed={modelFilter === item.model_code} className={`${HIERARCHY_ITEM} items-start ${modelFilter === item.model_code ? HIERARCHY_ACTIVE : HIERARCHY_IDLE}`}>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate">{item.model_code}</span>
                          <span className="mt-0.5 block truncate text-xs text-fg-muted" title={item.display_name}>{item.display_name}</span>
                        </span>
                        <StatusBadge tone={statusTone(item.status)}>{catalogLabel(tx, CATALOG_STATUS_LABELS, item.status)}</StatusBadge>
                      </button>
                    ))}
                  </div>
                ) : hierarchyHint('ai.catalog.browse.selectSeries'))}
              </div>
            )}
            {hasHierarchySelection && (
              <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs text-fg-muted">
                <span className="font-medium">{tx('ai.catalog.browse.path')}</span>
                {hierarchyPath.map((item, index) => (
                  <React.Fragment key={`${item}-${index}`}>
                    <span className="rounded-md bg-surface-muted px-2 py-0.5 font-mono text-fg">{item}</span>
                    {index < hierarchyPath.length - 1 && <ChevronRight className="h-3 w-3 text-fg-subtle" aria-hidden="true" />}
                  </React.Fragment>
                ))}
              </div>
            )}
          </div>
        </Panel>
      )}

      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
          <h3 className="text-base font-semibold text-fg">{tx('ai.catalog.filter.title')}</h3>
          <div className="flex rounded-lg border border-line bg-surface-muted p-0.5">
            <button type="button" onClick={() => changePanel('models')} aria-pressed={panel === 'models'} className={`inline-flex items-center gap-1 rounded-md px-3 py-1 text-[13px] font-medium ${panel === 'models' ? 'bg-surface text-fg shadow-sm' : 'text-fg-muted hover:text-fg'}`}><Database className="h-3.5 w-3.5" aria-hidden="true" />{tx('ai.catalog.filter.models')}</button>
            <button type="button" onClick={() => changePanel('aliases')} aria-pressed={panel === 'aliases'} className={`inline-flex items-center gap-1 rounded-md px-3 py-1 text-[13px] font-medium ${panel === 'aliases' ? 'bg-surface text-fg shadow-sm' : 'text-fg-muted hover:text-fg'}`}><Tag className="h-3.5 w-3.5" aria-hidden="true" />{tx('ai.catalog.filter.aliases')}</button>
          </div>
        </div>
        <div className="space-y-3 p-4">
          <form onSubmit={applySearch} className="flex flex-wrap gap-2">
            <div className="relative min-w-[260px] flex-1">
              <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-fg-subtle" aria-hidden="true" />
              <input type="search" value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder={panel === 'models' ? tx('ai.catalog.filter.searchModels') : tx('ai.catalog.filter.searchAliases')} className={`${INPUT_CLASS} pl-9`} />
            </div>
          </form>
          {panel === 'models' ? (
            <div className="grid gap-3 md:grid-cols-4">
              <label className={FIELD_LABEL_CLASS}>{tx('ai.catalog.filter.vendor')}<select value={vendorFilter} onChange={(event) => { setVendorFilter(event.target.value); setPage(1); }} className={SELECT_CLASS}><option value="">{tx('ai.catalog.filter.allVendor')}</option>{vendors.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
              <label className={FIELD_LABEL_CLASS}>{tx('ai.catalog.filter.family')}<select value={familyFilter} onChange={(event) => { setFamilyFilter(event.target.value); setPage(1); }} className={SELECT_CLASS}><option value="">{tx('ai.catalog.filter.allFamily')}</option>{families.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
              <label className={FIELD_LABEL_CLASS}>{tx('ai.catalog.filter.series')}<select value={seriesFilter} onChange={(event) => { setSeriesFilter(event.target.value); setPage(1); }} className={SELECT_CLASS}><option value="">{tx('ai.catalog.filter.allSeries')}</option>{series.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
              <label className={FIELD_LABEL_CLASS}>{tx('ai.catalog.filter.softwareVersion')}<select value={softwareVersionFilter} onChange={(event) => { setSoftwareVersionFilter(event.target.value); setPage(1); }} className={SELECT_CLASS}><option value="">{tx('ai.catalog.filter.allVersion')}</option>{softwareVersions.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
            </div>
          ) : (
            <div className="max-w-xs">
              <label className={FIELD_LABEL_CLASS}>{tx('ai.catalog.filter.aliasKind')}<select value={kindFilter} onChange={(event) => { setKindFilter(event.target.value); setPage(1); }} className={SELECT_CLASS}><option value="">{tx('ai.catalog.filter.allKinds')}</option>{Object.entries(KIND_LABELS).map(([key, labelKey]) => <option key={key} value={key}>{tx(labelKey)}</option>)}</select></label>
            </div>
          )}
          <div className="flex justify-end"><button type="button" onClick={clearCatalogFilters} className={SECONDARY_BUTTON}>{tx('ai.common.clearFilters')}</button></div>
        </div>
      </Panel>

      {panel === 'models' ? (
        <Panel className="overflow-hidden">
          <PanelHeader title={tx('ai.catalog.master.title')} description={tx('ai.catalog.master.summary', { total, page })} />
          {loading ? (
            <div role="status" className="flex items-center justify-center gap-2 p-10 text-[13px] text-fg-muted"><Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />{tx('ai.common.loading')}</div>
          ) : total === 0 && models.length === 0 ? (
            <EmptyState
              icon={Database}
              title={copy.emptyModelsTitle}
              description={copy.emptyModelsBody}
              className="m-4"
            />
          ) : (
            <div className="overflow-x-auto">
              <DataTable unstyled exportConfig={{ filename: 'product-model-catalog', language, disabled: total === 0, exportData: exportCatalogModels }} className="nx-data-table min-w-full text-left">
                <thead><tr>
                  <th>{tx('ai.catalog.filter.vendor')}</th><th>{tx('ai.catalog.editor.familyName')}</th><th>{tx('ai.catalog.editor.familyCode')}</th>
                  <th>{tx('ai.catalog.editor.seriesName')}</th><th>{tx('ai.catalog.editor.seriesCode')}</th><th>{tx('ai.catalog.editor.modelCode')}</th>
                  <th>{language === 'zh' ? 'OS 系列' : 'OS Family'}</th><th>{language === 'zh' ? '软件 Train' : 'Software Train'}</th>
                  <th>{tx('ai.catalog.editor.softwareVersion')}</th><th>{tx('ai.knowledge.ingestion.compatibleVersion')}</th>
                  <th>{tx('ai.catalog.master.status')}</th><th>{language === 'zh' ? '审核状态' : 'Review Status'}</th>
                  {canManageCatalog && <TableActionHeader>{tx('ai.catalog.master.actions')}</TableActionHeader>}
                </tr></thead>
                <tbody>{models.map((item) => <tr key={item.product_model_id}>
                  <td className="font-medium text-fg">{item.vendor_name}</td>
                  <td>{item.family_name}</td><td className="font-mono text-xs text-fg-muted">{item.family_code}</td>
                  <td className="text-fg">{item.series_name}</td><td className="font-mono text-xs text-fg-muted">{item.series_code}</td>
                  <td><div data-export-primary className="font-medium text-accent">{item.model_code}</div><div data-export-ignore className="max-w-[260px] truncate text-xs text-fg-subtle" title={item.product_model_id}>{item.product_model_id}</div></td>
                  <td>{scopeValue(item, 'os_family', tx('ai.common.na'))}</td><td>{scopeValue(item, 'software_train', tx('ai.common.na'))}</td>
                  <td>{scopeValue(item, 'primary_version', tx('ai.common.na'))}</td><td>{scopeValue(item, 'compatibility_version', tx('ai.common.na'))}</td>
                  <td><StatusBadge tone={statusTone(item.status)} dot>{catalogLabel(tx, CATALOG_STATUS_LABELS, item.status)}</StatusBadge></td>
                  <td>{catalogLabel(tx, CATALOG_STATUS_LABELS, item.review_status)}</td>
                  {canManageCatalog && <TableActionCell>{item.mutable ? <div className="flex items-center gap-1">
                    <ActionIconButton icon={Pencil} label={`${tx('ai.catalog.master.edit')} ${item.display_name}`} tooltip={tx('ai.catalog.master.edit')} variant="accent" onClick={() => openEditCatalogModel(item)} />
                    {item.status !== 'deleted' && <ActionIconButton icon={Trash2} label={`${tx('ai.catalog.master.archive')} ${item.display_name}`} tooltip={tx('ai.catalog.master.archive')} variant="danger" onClick={() => void archiveCatalogModel(item)} />}
                  </div> : <span className="text-xs text-fg-subtle">{tx('ai.catalog.master.readOnly')}</span>}</TableActionCell>}
                </tr>)}</tbody>
              </DataTable>
            </div>
          )}
          <Pagination currentPage={page} totalItems={total} itemsPerPage={pageSize} onPageChange={setPage} onItemsPerPageChange={(size) => { setPageSize(size); setPage(1); }} language={language} alwaysVisible />
        </Panel>
      ) : (
        <Panel className="overflow-hidden">
          <PanelHeader title={tx('ai.catalog.alias.title')} description={tx('ai.catalog.alias.body')} />
          {loading ? (
            <div role="status" className="flex items-center justify-center gap-2 p-10 text-[13px] text-fg-muted"><Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />{tx('ai.common.loading')}</div>
          ) : total === 0 && aliases.length === 0 ? (
            <EmptyState icon={Tag} title={copy.emptyAliasesTitle} description={copy.emptyAliasesBody} className="m-4" />
          ) : (
            <div className="overflow-x-auto">
              <DataTable unstyled exportConfig={{ filename: 'product-model-aliases', language, disabled: total === 0, exportData: exportCatalogAliases }} className="nx-data-table min-w-full text-left">
                <thead><tr>
                  <th>{tx('ai.catalog.alias.alias')}</th><th>{language === 'zh' ? '规范化别名' : 'Normalized Alias'}</th>
                  <th>{tx('ai.catalog.alias.kind')}</th><th>{tx('ai.catalog.alias.target')}</th>
                  <th>{tx('ai.catalog.filter.vendor')}</th><th>{tx('ai.catalog.editor.seriesCode')}</th>
                  <th>{language === 'zh' ? '冲突状态' : 'Conflict Status'}</th><th>{language === 'zh' ? '种子状态' : 'Seed Status'}</th>
                  <TableActionHeader>{tx('ai.catalog.alias.action')}</TableActionHeader>
                </tr></thead>
                <tbody>{aliases.map((item) => <tr key={item.id}>
                  <td className="font-medium text-fg">{item.alias}</td>
                  <td className="font-mono text-xs text-fg-muted">{item.normalized_alias}</td>
                  <td><StatusBadge tone="accent">{catalogLabel(tx, KIND_LABELS, item.alias_kind)}</StatusBadge></td>
                  <td className="text-fg">{item.model?.model_code || tx('ai.common.na')}</td>
                  <td>{item.model?.vendor_name || tx('ai.common.na')}</td><td className="font-mono text-xs text-fg-muted">{item.model?.series_code || ''}</td>
                  <td><StatusBadge tone={statusTone(item.conflict_status)} dot>{catalogLabel(tx, CATALOG_STATUS_LABELS, item.conflict_status)}</StatusBadge></td>
                  <td>{catalogLabel(tx, CATALOG_STATUS_LABELS, item.seed_status)}</td>
                  <TableActionCell><ActionIconButton icon={Search} label={tx('ai.catalog.alias.useForResolution')} variant="accent" onClick={() => setQuery(item.alias)} /></TableActionCell>
                </tr>)}</tbody>
              </DataTable>
            </div>
          )}
          <Pagination currentPage={page} totalItems={total} itemsPerPage={pageSize} onPageChange={setPage} onItemsPerPageChange={(size) => { setPageSize(size); setPage(1); }} language={language} alwaysVisible />
        </Panel>
      )}

      <Panel>
        <PanelHeader
          title={<span className="inline-flex items-center gap-2"><Sparkles className="h-4 w-4 text-accent" aria-hidden="true" />{tx('ai.catalog.resolve.title')}<StatusBadge mono>dry-run</StatusBadge></span>}
        />
        <div className="p-4">
          <form onSubmit={(event) => void runResolution(event)} className="flex flex-wrap gap-2">
            <div className="relative min-w-[240px] flex-1">
              <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-fg-subtle" aria-hidden="true" />
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={tx('ai.catalog.resolve.input')} className={`${INPUT_CLASS} pl-9`} />
            </div>
            <button type="submit" disabled={resolving || !query.trim()} className={PRIMARY_BUTTON}>{resolving ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" /> : <Search className="h-4 w-4" aria-hidden="true" />}{tx('ai.catalog.resolve.action')}</button>
          </form>
          {resolution && (
            <div className="mt-3 rounded-lg border border-line bg-surface-muted/40 p-3">
              <div className="flex flex-wrap items-center gap-2 text-[13px]">
                <StatusBadge tone={resolutionTone(resolution.outcome)} dot>{catalogLabel(tx, RESOLUTION_OUTCOME_LABELS, resolution.outcome)}</StatusBadge>
                <span className="text-fg-muted">{tx('ai.catalog.resolve.candidates', { count: resolution.candidate_count })}</span>
                {resolution.requires_clarification && <span className="font-medium text-warning">{tx('ai.catalog.resolve.clarify')}</span>}
                <span className="ml-auto text-xs text-fg-subtle">{resolution.driver_selection_allowed ? tx('ai.catalog.resolve.allowed') : tx('ai.catalog.resolve.blocked')}</span>
              </div>
              {resolution.candidates.length > 0 && (
                <div className="mt-2 grid gap-2 md:grid-cols-2">
                  {resolution.candidates.map((candidate) => (
                    <div key={String(candidate.id || candidate.product_model_id)} className="rounded-md border border-line bg-surface p-2 text-[13px]">
                      <div className="font-medium text-fg">{candidate.model?.model_code || String(candidate.product_model_id || tx('ai.catalog.resolve.unknown'))}</div>
                      <div className="text-xs text-fg-muted">{candidate.model?.vendor_id} / {candidate.model?.series_code} · {catalogLabel(tx, KIND_LABELS, String(candidate.alias_kind || ''))}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </Panel>

      {catalogModalOpen && (
        <div ref={catalogDialogRef} className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-labelledby="catalog-model-editor-title" tabIndex={-1}>
          <div className="flex max-h-[calc(100vh-2rem)] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-line bg-surface shadow-xl">
            <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
              <div className="min-w-0">
                <div className="text-xs font-medium text-fg-muted">{tx(editingModel ? 'ai.catalog.editor.editEyebrow' : 'ai.catalog.editor.addEyebrow')}</div>
                <h3 id="catalog-model-editor-title" className="mt-1 truncate text-lg font-semibold text-fg">{editingModel ? editingModel.display_name : tx('ai.catalog.editor.title')}</h3>
                <p className="mt-1 text-[13px] text-fg-muted">{tx('ai.catalog.editor.body')}</p>
              </div>
              <button type="button" onClick={() => setCatalogModalOpen(false)} aria-label={tx('ai.catalog.editor.close')} className="rounded-md p-1.5 text-fg-subtle hover:bg-surface-muted hover:text-fg"><X className="h-5 w-5" aria-hidden="true" /></button>
            </div>
            <form onSubmit={submitCatalogModel} className="min-h-0 overflow-y-auto px-5 py-5">
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {([['vendor_code', 'ai.catalog.editor.vendorCode'], ['vendor_name', 'ai.catalog.editor.vendorName'], ['family_code', 'ai.catalog.editor.familyCode'], ['family_name', 'ai.catalog.editor.familyName'], ['series_code', 'ai.catalog.editor.seriesCode'], ['series_name', 'ai.catalog.editor.seriesName'], ['model_code', 'ai.catalog.editor.modelCode'], ['display_name', 'ai.catalog.editor.displayName']] as const).map(([key, labelKey]) => (
                  <label key={key} className={FIELD_LABEL_CLASS}>
                    <span>{tx(labelKey)}{editingModel && ['vendor_code', 'vendor_name', 'family_code', 'family_name', 'series_code', 'series_name', 'model_code'].includes(key) ? tx('ai.catalog.editor.readOnly') : ''}</span>
                    <input required={!editingModel || key === 'display_name'} disabled={Boolean(editingModel && key !== 'display_name')} value={catalogForm[key]} onChange={(event) => setCatalogForm((current) => ({ ...current, [key]: event.target.value }))} className={`mt-1.5 ${INPUT_CLASS}`} />
                  </label>
                ))}
                <label className={FIELD_LABEL_CLASS}>{tx('ai.catalog.editor.status')}<select value={catalogForm.status} onChange={(event) => setCatalogForm((current) => ({ ...current, status: event.target.value as typeof current.status }))} className={`mt-1.5 ${INPUT_CLASS}`}>{(['draft', 'active', 'disabled', 'archived'] as const).map((status) => <option key={status} value={status}>{catalogLabel(tx, CATALOG_STATUS_LABELS, status)}</option>)}</select></label>
                <label className={FIELD_LABEL_CLASS}>{tx('ai.catalog.editor.softwareVersion')}<input value={catalogForm.software_version} onChange={(event) => setCatalogForm((current) => ({ ...current, software_version: event.target.value }))} placeholder={tx('ai.catalog.editor.versionPlaceholder')} className={`mt-1.5 ${INPUT_CLASS}`} /></label>
                <label className={`${FIELD_LABEL_CLASS} sm:col-span-2 lg:col-span-3`}>{tx('ai.catalog.editor.description')}<textarea rows={2} value={catalogForm.description} onChange={(event) => setCatalogForm((current) => ({ ...current, description: event.target.value }))} className={`mt-1.5 ${INPUT_CLASS}`} /></label>
                <label className={`${FIELD_LABEL_CLASS} sm:col-span-2 lg:col-span-3`}>{tx(editingModel ? 'ai.catalog.editor.reason' : 'ai.catalog.editor.reasonOptional')}<textarea required={Boolean(editingModel)} rows={2} value={catalogForm.change_reason} onChange={(event) => setCatalogForm((current) => ({ ...current, change_reason: event.target.value }))} placeholder={tx('ai.catalog.editor.reasonPlaceholder')} className={`mt-1.5 ${INPUT_CLASS}`} /></label>
              </div>
              <div className="mt-5 flex justify-end gap-2 border-t border-line pt-4">
                <button type="button" onClick={() => setCatalogModalOpen(false)} className={SECONDARY_BUTTON}>{tx('ai.catalog.editor.cancel')}</button>
                <button type="submit" disabled={catalogSubmitting} className={PRIMARY_BUTTON}>{catalogSubmitting && <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />}{catalogSubmitting ? tx('ai.catalog.editor.saving') : editingModel ? tx('ai.catalog.editor.save') : tx('ai.catalog.editor.create')}</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default ProductCatalogManagementTab;
