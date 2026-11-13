import React, { useMemo, useState } from 'react';
import { ExternalLink, Loader2, RefreshCw, ShieldCheck, Sparkles } from 'lucide-react';
import {
  importKnowledgeOfficialSeedBatch,
  type KnowledgeOfficialSeedBatchResult,
  type KnowledgeOfficialUrlImportPayload,
} from '../../../api/ai';
import { aiAdminText, type AIAdminLanguage } from '../../../i18n/aiAdmin';
import {
  OFFICIAL_SEED_CATALOG,
  OFFICIAL_SEED_CATALOG_REVISION,
  type OfficialSeedVendor,
} from './officialSeedCatalog';

interface OfficialSeedPanelProps {
  language?: AIAdminLanguage;
  onCompleted?: () => void;
}

const VENDORS: Array<'all' | OfficialSeedVendor> = ['all', 'Huawei', 'H3C', 'Cisco', 'Ruijie'];

export const OfficialSeedPanel: React.FC<OfficialSeedPanelProps> = ({ language = 'zh', onCompleted }) => {
  const tx = (key: string, variables: Record<string, string | number> = {}) => aiAdminText(key, language, variables);
  const [vendorFilter, setVendorFilter] = useState<'all' | OfficialSeedVendor>('all');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<KnowledgeOfficialSeedBatchResult | null>(null);

  const visibleItems = useMemo(
    () => OFFICIAL_SEED_CATALOG.filter((item) => vendorFilter === 'all' || item.vendor === vendorFilter),
    [vendorFilter],
  );
  const visibleDirectItems = useMemo(() => visibleItems.filter((item) => item.directIngestion), [visibleItems]);
  const selectedItems = useMemo(
    () => OFFICIAL_SEED_CATALOG.filter((item) => selectedIds.has(item.id) && item.directIngestion),
    [selectedIds],
  );
  const allVisibleSelected = visibleDirectItems.length > 0 && visibleDirectItems.every((item) => selectedIds.has(item.id));
  const directCount = OFFICIAL_SEED_CATALOG.filter((item) => item.directIngestion).length;

  const toggleItem = (id: string) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    setResult(null);
    setError('');
  };

  const toggleVisibleDirectItems = () => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (allVisibleSelected) visibleDirectItems.forEach((item) => next.delete(item.id));
      else visibleDirectItems.forEach((item) => next.add(item.id));
      return next;
    });
    setResult(null);
    setError('');
  };

  const clearSelection = () => {
    setSelectedIds(new Set<string>());
    setResult(null);
    setError('');
  };

  const handleCollect = async () => {
    if (submitting || selectedItems.length === 0) return;
    setSubmitting(true);
    setError('');
    setResult(null);
    const payload: KnowledgeOfficialUrlImportPayload[] = selectedItems.map((item) => ({
      url: item.url,
      source_kind: item.sourceKind,
      vendor: item.vendor,
      product_family: item.productFamily,
      version_scope: item.versionScope,
      terms_review_status: 'approved',
      reviewer: `${OFFICIAL_SEED_CATALOG_REVISION}:catalog-review`,
      reviewed_at: '2026-08-28T00:00:00Z',
      name: item.title,
      description: `Curated official source from ${OFFICIAL_SEED_CATALOG_REVISION}`,
      publish_to_knowledge_base: true,
    }));
    try {
      const nextResult = await importKnowledgeOfficialSeedBatch(payload);
      setResult(nextResult);
      setSelectedIds(new Set<string>());
      onCompleted?.();
    } catch (err: any) {
      setError(err?.message || tx('ai.knowledge.officialSeed.error'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="rounded-2xl border border-blue-200/80 bg-gradient-to-br from-blue-50/80 via-white to-indigo-50/60 p-4 shadow-xs dark:border-blue-900/70 dark:from-blue-950/30 dark:via-slate-800 dark:to-indigo-950/20" aria-label={tx('ai.knowledge.officialSeed.aria')}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className="mt-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-white shadow-sm"><Sparkles className="h-4 w-4" /></span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-bold text-slate-900 dark:text-white">{tx('ai.knowledge.officialSeed.title')}</h3>
              <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-semibold text-blue-700 dark:bg-blue-950/60 dark:text-blue-200">{tx('ai.knowledge.officialSeed.directCount', { count: directCount })}</span>
            </div>
            <p className="mt-1 max-w-3xl text-[10px] leading-4 text-slate-600 dark:text-slate-300">{tx('ai.knowledge.officialSeed.body')}</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[10px] text-slate-500 dark:text-slate-400">
          <span className="inline-flex items-center gap-1 rounded-full bg-white/80 px-2 py-1 dark:bg-slate-900/60"><ShieldCheck className="h-3 w-3 text-emerald-500" />{tx('ai.knowledge.officialSeed.revalidated')}</span>
          <span className="font-mono">{OFFICIAL_SEED_CATALOG_REVISION}</span>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5" role="group" aria-label={tx('ai.knowledge.officialSeed.vendorFilter')}>
        {VENDORS.map((vendor) => {
          const active = vendorFilter === vendor;
          const count = OFFICIAL_SEED_CATALOG.filter((item) => vendor === 'all' || item.vendor === vendor).length;
          return (
            <button
              key={vendor}
              type="button"
              onClick={() => setVendorFilter(vendor)}
              className={`rounded-lg px-2.5 py-1 text-[10px] font-semibold transition ${active ? 'bg-indigo-600 text-white shadow-sm' : 'border border-slate-200 bg-white/80 text-slate-600 hover:border-indigo-300 hover:text-indigo-700 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-300'}`}
              aria-pressed={active}
            >
              {vendor === 'all' ? tx('ai.knowledge.officialSeed.vendorAll') : vendor} <span className="opacity-70">{count}</span>
            </button>
          );
        })}
        <span className="ml-auto text-[10px] text-slate-500 dark:text-slate-400">{tx('ai.knowledge.officialSeed.selected', { count: selectedItems.length })}</span>
        <button type="button" onClick={toggleVisibleDirectItems} disabled={visibleDirectItems.length === 0 || submitting} className="rounded-lg border border-indigo-200 bg-white/80 px-2.5 py-1 text-[10px] font-semibold text-indigo-700 hover:bg-indigo-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-indigo-900 dark:bg-slate-900/60 dark:text-indigo-200">
          {allVisibleSelected ? tx('ai.knowledge.officialSeed.clearVisible') : tx('ai.knowledge.officialSeed.selectVisible')}
        </button>
        {selectedItems.length > 0 && <button type="button" onClick={clearSelection} disabled={submitting} className="rounded-lg px-2 py-1 text-[10px] text-slate-500 hover:bg-white dark:text-slate-400 dark:hover:bg-slate-800">{tx('ai.knowledge.officialSeed.clearSelection')}</button>}
      </div>

      <div className="mt-3 grid max-h-[310px] gap-2 overflow-y-auto pr-1 sm:grid-cols-2 xl:grid-cols-3" aria-live="polite">
        {visibleItems.map((item) => (
          <div key={item.id} className={`flex min-w-0 items-center gap-2 rounded-xl border p-2.5 ${item.directIngestion ? (selectedIds.has(item.id) ? 'border-indigo-400 bg-indigo-50/80 dark:border-indigo-700 dark:bg-indigo-950/40' : 'border-slate-200 bg-white/80 dark:border-slate-700 dark:bg-slate-900/50') : 'border-dashed border-slate-200 bg-slate-50/70 dark:border-slate-700 dark:bg-slate-900/30'}`}>
            <label className={`flex min-w-0 flex-1 items-start gap-2 ${item.directIngestion ? 'cursor-pointer' : 'cursor-default'}`}>
              <input type="checkbox" checked={selectedIds.has(item.id)} onChange={() => toggleItem(item.id)} disabled={!item.directIngestion || submitting} className="mt-0.5 h-3.5 w-3.5 shrink-0 accent-indigo-600 disabled:opacity-40" />
              <span className="min-w-0">
                <span className="block truncate text-[11px] font-semibold text-slate-800 dark:text-slate-100" title={item.title}>{item.title}</span>
                <span className="mt-0.5 block truncate text-[9px] text-slate-500 dark:text-slate-400">{item.vendor} · {item.productFamily} · {item.versionScope.primary}</span>
                <span className={`mt-1 inline-flex rounded-full px-1.5 py-0.5 text-[9px] font-semibold ${item.directIngestion ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300' : 'bg-amber-50 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300'}`}>
                  {item.directIngestion ? tx('ai.knowledge.officialSeed.direct') : tx('ai.knowledge.officialSeed.registryOnly')}
                </span>
              </span>
            </label>
            <a href={item.url} target="_blank" rel="noreferrer" className="shrink-0 rounded-lg p-1.5 text-slate-400 hover:bg-white hover:text-indigo-600 dark:hover:bg-slate-800" aria-label={tx('ai.knowledge.officialSeed.openSource', { title: item.title })} title={item.url}>
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          </div>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-blue-100 pt-3 text-[10px] dark:border-blue-900/50">
        <p className="max-w-3xl leading-4 text-slate-500 dark:text-slate-400">{tx('ai.knowledge.officialSeed.catalogNotice')}</p>
        <button type="button" onClick={() => void handleCollect()} disabled={submitting || selectedItems.length === 0} className="inline-flex items-center gap-1.5 rounded-xl bg-blue-600 px-3 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50">
          {submitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          {submitting ? tx('ai.knowledge.officialSeed.collecting') : tx('ai.knowledge.officialSeed.collect')}
        </button>
      </div>
      {(error || result) && (
        <div className={`mt-3 rounded-xl px-3 py-2 text-[11px] ${error ? 'bg-rose-50 text-rose-700 dark:bg-rose-950/30 dark:text-rose-300' : 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300'}`} role="status" aria-live="polite">
          {error || tx('ai.knowledge.officialSeed.result', { succeeded: result?.succeeded_count || 0, failed: result?.failed_count || 0 })}
        </div>
      )}
    </section>
  );
};

export default OfficialSeedPanel;
