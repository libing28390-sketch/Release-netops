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
import { Panel } from '../../../components/ui/Panel';
import { StatusBadge } from '../../../components/ui/StatusBadge';

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
    <Panel className="p-4" aria-label={tx('ai.knowledge.officialSeed.aria')}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className="mt-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-subtle text-accent"><Sparkles className="h-4 w-4" aria-hidden="true" /></span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-base font-semibold text-fg">{tx('ai.knowledge.officialSeed.title')}</h3>
              <StatusBadge tone="accent">{tx('ai.knowledge.officialSeed.directCount', { count: directCount })}</StatusBadge>
            </div>
            <p className="mt-1 max-w-3xl text-xs leading-4 text-fg-muted ">{tx('ai.knowledge.officialSeed.body')}</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-fg-muted ">
          <StatusBadge tone="success"><ShieldCheck className="h-3 w-3" aria-hidden="true" />{tx('ai.knowledge.officialSeed.revalidated')}</StatusBadge>
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
              className={`rounded-lg px-2.5 py-1 text-xs font-semibold transition ${active ? 'bg-accent text-white shadow-sm' : 'border border-line bg-surface text-fg-muted hover:border-accent/30 hover:text-accent '}`}
              aria-pressed={active}
            >
              {vendor === 'all' ? tx('ai.knowledge.officialSeed.vendorAll') : vendor} <span className="opacity-70">{count}</span>
            </button>
          );
        })}
        <span className="ml-auto text-xs text-fg-muted ">{tx('ai.knowledge.officialSeed.selected', { count: selectedItems.length })}</span>
        <button type="button" onClick={toggleVisibleDirectItems} disabled={visibleDirectItems.length === 0 || submitting} className="rounded-lg border border-accent/30 bg-surface px-2.5 py-1 text-xs font-semibold text-accent hover:bg-accent-subtle disabled:cursor-not-allowed disabled:opacity-50 ">
          {allVisibleSelected ? tx('ai.knowledge.officialSeed.clearVisible') : tx('ai.knowledge.officialSeed.selectVisible')}
        </button>
        {selectedItems.length > 0 && <button type="button" onClick={clearSelection} disabled={submitting} className="rounded-lg px-2 py-1 text-xs text-fg-muted hover:bg-surface ">{tx('ai.knowledge.officialSeed.clearSelection')}</button>}
      </div>

      <div className="mt-3 grid max-h-[310px] gap-2 overflow-y-auto pr-1 sm:grid-cols-2 xl:grid-cols-3" aria-live="polite">
        {visibleItems.map((item) => (
          <div key={item.id} className={`flex min-w-0 items-center gap-2 rounded-xl border p-2.5 ${item.directIngestion ? (selectedIds.has(item.id) ? 'border-accent bg-accent-subtle ' : 'border-line bg-surface ') : 'border-dashed border-line bg-surface-muted '}`}>
            <label className={`flex min-w-0 flex-1 items-start gap-2 ${item.directIngestion ? 'cursor-pointer' : 'cursor-default'}`}>
              <input type="checkbox" checked={selectedIds.has(item.id)} onChange={() => toggleItem(item.id)} disabled={!item.directIngestion || submitting} className="mt-0.5 h-3.5 w-3.5 shrink-0 accent-[var(--ui-accent)] disabled:opacity-40" />
              <span className="min-w-0">
                <span className="block truncate text-[11px] font-semibold text-fg " title={item.title}>{item.title}</span>
                <span className="mt-0.5 block truncate text-xs text-fg-muted ">{item.vendor} · {item.productFamily} · {item.versionScope.primary}</span>
                <StatusBadge tone={item.directIngestion ? 'success' : 'warning'} className="mt-1">
                  {item.directIngestion ? tx('ai.knowledge.officialSeed.direct') : tx('ai.knowledge.officialSeed.registryOnly')}
                </StatusBadge>
              </span>
            </label>
            <a href={item.url} target="_blank" rel="noreferrer" className="shrink-0 rounded-lg p-1.5 text-fg-subtle hover:bg-surface hover:text-accent " aria-label={tx('ai.knowledge.officialSeed.openSource', { title: item.title })} title={item.url}>
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          </div>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3 text-xs">
        <p className="max-w-3xl leading-4 text-fg-muted ">{tx('ai.knowledge.officialSeed.catalogNotice')}</p>
        <button type="button" onClick={() => void handleCollect()} disabled={submitting || selectedItems.length === 0} className="inline-flex items-center gap-1.5 rounded-xl bg-accent px-3 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50">
          {submitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          {submitting ? tx('ai.knowledge.officialSeed.collecting') : tx('ai.knowledge.officialSeed.collect')}
        </button>
      </div>
      {(error || result) && (
        <div className={`mt-3 rounded-xl px-3 py-2 text-[11px] ${error ? 'bg-danger-subtle text-danger ' : 'bg-success-subtle text-success '}`} role="status" aria-live="polite">
          {error || tx('ai.knowledge.officialSeed.result', { succeeded: result?.succeeded_count || 0, failed: result?.failed_count || 0 })}
        </div>
      )}
    </Panel>
  );
};

export default OfficialSeedPanel;
