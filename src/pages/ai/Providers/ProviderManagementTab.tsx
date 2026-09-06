import React, { useCallback, useEffect, useState } from 'react';
import {
  Activity,
  Bot,
  CheckCircle2,
  CircleAlert,
  Clock3,
  Download,
  Eye,
  EyeOff,
  Globe2,
  KeyRound,
  LockKeyhole,
  Plus,
  Pencil,
  Power,
  RefreshCw,
  ShieldCheck,
  Trash2,
  X,
  XCircle,
  type LucideIcon,
} from 'lucide-react';
import { getAIProvidersPage, createAIProvider, updateAIProvider, deleteAIProvider, getAIProviderDeletePreview, testAIProvider, AIProvider, AIProviderDeletePreview } from '../../../api/ai';
import { useCoreApp } from '../../../contexts/AppDomainContext';
import { ActionButton, ActionIconButton, ActionIconGroup, ActionLink } from '../../../components/ui/ActionIconButton';
import Pagination from '../../../components/Pagination';
import { aiAdminText } from '../../../i18n/aiAdmin';

type TextVariables = Record<string, string | number>;
type AIAdminText = (key: string, variables?: TextVariables) => string;

interface ProviderTestResult {
  id: string;
  success: boolean;
  message: string;
  latency_ms?: number;
  sample_response?: string | null;
  model_tested?: string | null;
  error_code?: string | null;
}

interface MetricCardProps {
  icon: LucideIcon;
  label: string;
  value: string | number;
  helper: string;
  tone: 'indigo' | 'emerald' | 'amber' | 'slate';
}

const metricToneClasses: Record<MetricCardProps['tone'], string> = {
  indigo: 'bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-300',
  emerald: 'bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-300',
  amber: 'bg-amber-50 text-amber-600 dark:bg-amber-500/10 dark:text-amber-300',
  slate: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
};

const DATA_REGION_OPTIONS = [
  { value: 'unknown', labelKey: 'ai.provider.region.unknown' },
  { value: 'global', labelKey: 'ai.provider.region.global' },
  { value: 'cn', labelKey: 'ai.provider.region.cn' },
  { value: 'us', labelKey: 'ai.provider.region.us' },
  { value: 'eu', labelKey: 'ai.provider.region.eu' },
] as const;

const MetricCard: React.FC<MetricCardProps> = ({ icon: Icon, label, value, helper, tone }) => (
  <div className="rounded-2xl border border-slate-200/80 bg-white/90 p-4 shadow-sm shadow-slate-200/40 dark:border-slate-800 dark:bg-slate-900/80 dark:shadow-none">
    <div className="flex items-start justify-between gap-3">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400 dark:text-slate-500">{label}</p>
        <p className="mt-2 text-2xl font-bold tracking-tight text-slate-900 dark:text-white">{value}</p>
      </div>
      <span className={`flex h-9 w-9 items-center justify-center rounded-xl ${metricToneClasses[tone]}`}>
        <Icon className="h-4 w-4" />
      </span>
    </div>
    <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{helper}</p>
  </div>
);

const getErrorMessage = (error: unknown, fallback: string) => (
  error instanceof Error && error.message ? error.message : fallback
);

const getProviderDeleteErrorMessage = (error: unknown, providerName: string, tx: AIAdminText) => {
  if (error && typeof error === 'object' && 'code' in error && error.code === 'AI_PROVIDER_HAS_MODELS') {
    const detail = 'detail' in error && error.detail && typeof error.detail === 'object' ? error.detail : null;
    const details = detail && 'details' in detail && detail.details && typeof detail.details === 'object' ? detail.details : null;
    const modelCount = details && 'model_count' in details && typeof details.model_count === 'number' ? details.model_count : 1;
    return tx('ai.provider.delete.blocked', { name: providerName, models: modelCount, routes: 0 });
  }
  return getErrorMessage(error, tx('ai.provider.error.delete'));
};

const getTestTitle = (result: ProviderTestResult, tx: AIAdminText) => (
  tx(result.success ? 'ai.provider.test.passed' : 'ai.provider.test.failed')
);

const getTestDescription = (result: ProviderTestResult, tx: AIAdminText) => {
  if (result.success) {
    return tx('ai.provider.test.successDescription', { model: result.model_tested ? ` · ${result.model_tested}` : '' });
  }

  if (result.error_code === 'AI_SECURITY_CLASSIFICATION_DENIED') {
    return tx('ai.provider.test.classification');
  }

  if (result.error_code === 'AI_SECURITY_POLICY_DISABLED') {
    return tx('ai.provider.test.policy');
  }

  if (result.error_code === 'AI_AUTH_FAILED') {
    return tx('ai.provider.test.auth');
  }

  if (result.error_code === 'AI_PROVIDER_CIRCUIT_OPEN') {
    return tx('ai.provider.test.circuit');
  }

  if (result.error_code === 'AI_HEALTH_BACKOFF') {
    return tx('ai.provider.test.backoff');
  }

  if (result.error_code === 'AI_MODEL_NOT_FOUND') {
    return tx('ai.provider.test.modelNotFound');
  }

  if (result.error_code === 'AI_PROVIDER_UNSUPPORTED') {
    return tx('ai.provider.test.unsupported');
  }

  if (result.error_code === 'AI_NETWORK_ERROR') {
    return tx('ai.provider.test.network');
  }

  return tx('ai.provider.test.generic');
};

interface ProviderRegistryWorkspaceProps {
  providers: AIProvider[];
  total: number;
  selectedProviderId: string | null;
  onSelect: (id: string) => void;
  onEdit: (provider: AIProvider) => void;
  onToggle: (provider: AIProvider) => void;
  onDelete: (id: string) => void;
  onTest: (id: string) => void;
  testingId: string | null;
  deletingId: string | null;
  testResult: ProviderTestResult | null;
  tx: AIAdminText;
}

const ProviderRegistryWorkspace: React.FC<ProviderRegistryWorkspaceProps> = ({
  providers,
  total,
  selectedProviderId,
  onSelect,
  onEdit,
  onToggle,
  onDelete,
  onTest,
  testingId,
  deletingId,
  testResult,
  tx,
}) => {
  const selectedProvider = providers.find((provider) => provider.id === selectedProviderId) || providers[0];
  const selectedResult = selectedProvider && testResult?.id === selectedProvider.id ? testResult : null;
  const selectedTesting = selectedProvider ? testingId === selectedProvider.id : false;
  const selectedDeleting = selectedProvider ? deletingId === selectedProvider.id : false;
  const selectedRegion = selectedProvider && DATA_REGION_OPTIONS.find((option) => option.value === selectedProvider.data_region?.toLowerCase());

  if (!selectedProvider) return null;

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(300px,0.82fr)_minmax(0,1.65fr)]">
      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900" aria-label={tx('ai.provider.list.aria')}>
        <div className="border-b border-slate-100 p-4 dark:border-slate-800">
          <div className="flex items-center justify-between gap-2"><div><h3 className="text-sm font-bold text-slate-900 dark:text-white">{tx('ai.provider.list.title')}</h3><p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">{tx('ai.provider.list.body')}</p></div><span className="rounded-full bg-indigo-50 px-2 py-1 text-[10px] font-bold text-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-300">{total}</span></div>
        </div>
        <div className="max-h-[620px] space-y-2 overflow-y-auto p-3">
          {providers.length === 0 ? <div className="px-3 py-8 text-center text-xs text-slate-400">{tx('ai.provider.list.empty')}</div> : providers.map((provider) => {
            const active = provider.id === selectedProvider.id;
            const region = DATA_REGION_OPTIONS.find((option) => option.value === provider.data_region?.toLowerCase());
            return <div key={provider.id} className={cnProviderRow(active)}>
              <button type="button" onClick={() => onSelect(provider.id)} className="min-w-0 flex-1 text-left" aria-label={tx('ai.provider.action.select', { name: provider.name })}>
                <div className="flex items-start gap-2"><span className={provider.enabled ? 'mt-1 h-2 w-2 shrink-0 rounded-full bg-emerald-500' : 'mt-1 h-2 w-2 shrink-0 rounded-full bg-slate-300'} /><span className="min-w-0 flex-1"><span className="block truncate text-sm font-bold text-slate-900 dark:text-white">{provider.name}</span><span className="mt-0.5 block truncate font-mono text-[10px] text-indigo-500">{provider.provider_type}</span></span><span className={provider.health_status === 'healthy' ? 'rounded-full bg-emerald-50 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300' : provider.health_status === 'unhealthy' ? 'rounded-full bg-rose-50 px-1.5 py-0.5 text-[9px] font-semibold text-rose-700 dark:bg-rose-950/40 dark:text-rose-300' : 'rounded-full bg-slate-100 px-1.5 py-0.5 text-[9px] font-semibold text-slate-500 dark:bg-slate-800 dark:text-slate-400'}>{provider.health_status || 'unknown'}</span></div>
                <div className="mt-2 flex flex-wrap gap-1.5 text-[10px] text-slate-500 dark:text-slate-400"><span className="max-w-[220px] truncate font-mono">{provider.base_url || tx('ai.provider.endpoint.default')}</span>{provider.api_key_masked && <span className="rounded bg-slate-100 px-1.5 py-0.5 dark:bg-slate-800">{tx('ai.provider.key.configured')}</span>}{region && <span>{tx(region.labelKey)}</span>}</div>
              </button>
              <ActionIconGroup label={tx('ai.provider.list.actions')} className="flex shrink-0 items-center gap-0.5"><ActionIconButton icon={Pencil} label={tx('ai.provider.action.edit', { name: provider.name })} size="xs" variant="accent" disabled={testingId === provider.id || deletingId === provider.id} onClick={() => onEdit(provider)} /><ActionIconButton icon={Power} label={tx(provider.enabled ? 'ai.provider.action.disable' : 'ai.provider.action.enable', { name: provider.name })} size="xs" disabled={testingId === provider.id || deletingId === provider.id} onClick={() => onToggle(provider)} /><ActionIconButton icon={Trash2} label={tx('ai.provider.action.delete', { name: provider.name })} size="xs" variant="danger" disabled={deletingId === provider.id} onClick={() => onDelete(provider.id)} /></ActionIconGroup>
            </div>;
          })}
        </div>
      </section>

      <section className="min-w-0 rounded-2xl border border-indigo-100 bg-gradient-to-br from-white via-indigo-50/40 to-violet-50/60 p-5 shadow-sm dark:border-indigo-900/60 dark:from-slate-900 dark:via-indigo-950/20 dark:to-violet-950/20 sm:p-6" aria-label={tx('ai.provider.detail.aria')}>
        <div className="flex flex-wrap items-start justify-between gap-3"><div className="flex min-w-0 items-center gap-3"><span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-slate-950 text-white shadow-md dark:bg-indigo-500/20 dark:text-indigo-200"><Bot className="h-5 w-5" /></span><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h3 className="truncate text-lg font-bold text-slate-900 dark:text-white">{selectedProvider.name}</h3><span className={selectedProvider.enabled ? 'rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-bold text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300' : 'rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-bold text-slate-500 dark:bg-slate-800 dark:text-slate-400'}>{tx(selectedProvider.enabled ? 'ai.provider.status.enabled' : 'ai.provider.status.disabled')}</span></div><p className="mt-1 truncate font-mono text-xs text-indigo-500">{selectedProvider.provider_type} · {selectedProvider.id}</p></div></div><div className="flex items-center gap-1"><ActionIconButton icon={Pencil} label={tx('ai.provider.action.edit', { name: selectedProvider.name })} variant="accent" disabled={selectedTesting || selectedDeleting} onClick={() => onEdit(selectedProvider)} /><ActionIconButton icon={Power} label={tx(selectedProvider.enabled ? 'ai.provider.action.disable' : 'ai.provider.action.enable', { name: selectedProvider.name })} disabled={selectedTesting || selectedDeleting} onClick={() => onToggle(selectedProvider)} /><ActionIconButton icon={Trash2} label={tx('ai.provider.action.delete', { name: selectedProvider.name })} variant="danger" disabled={selectedDeleting} onClick={() => onDelete(selectedProvider.id)} /></div></div>
        <div className="mt-5 grid gap-3 sm:grid-cols-2"><div className="rounded-xl border border-white/80 bg-white/75 p-3 dark:border-slate-800 dark:bg-slate-950/45"><div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400"><Globe2 className="h-3.5 w-3.5" />Base URL</div><div className="mt-2 truncate font-mono text-xs text-slate-700 dark:text-slate-200" title={selectedProvider.base_url || undefined}>{selectedProvider.base_url || tx('ai.provider.endpoint.default')}</div></div><div className="rounded-xl border border-white/80 bg-white/75 p-3 dark:border-slate-800 dark:bg-slate-950/45"><div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400"><KeyRound className="h-3.5 w-3.5" />API Key</div><div className="mt-2 flex items-center gap-2"><span className="truncate font-mono text-xs text-slate-700 dark:text-slate-200">{selectedProvider.api_key_masked || tx('ai.provider.key.notConfigured')}</span><span className="shrink-0 rounded-md bg-emerald-100 px-1.5 py-0.5 text-[10px] font-bold text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300">AES-256</span></div></div></div>
        <div className="mt-3 flex flex-wrap gap-2 text-[10px]"><span className={selectedProvider.health_status === 'healthy' ? 'rounded-full bg-emerald-100 px-2 py-1 font-semibold text-emerald-700' : selectedProvider.health_status === 'unhealthy' ? 'rounded-full bg-rose-100 px-2 py-1 font-semibold text-rose-700' : 'rounded-full bg-slate-200 px-2 py-1 font-semibold text-slate-600'}>{tx('ai.provider.status.health')}: {selectedProvider.health_status || tx('ai.provider.status.unknown')}</span>{selectedProvider.last_error_code && <span className="rounded-full bg-rose-50 px-2 py-1 font-mono text-rose-700">{selectedProvider.last_error_code}</span>}{selectedRegion && <span className="rounded-full bg-indigo-50 px-2 py-1 text-indigo-700">{tx('ai.provider.detail.region', { value: tx(selectedRegion.labelKey) })}</span>}<span className="rounded-full bg-slate-100 px-2 py-1 text-slate-600 dark:bg-slate-800 dark:text-slate-300">{tx('ai.provider.detail.classification', { value: selectedProvider.allowed_data_classification || 'PUBLIC' })}</span></div>
        <div className={selectedTesting ? 'mt-5 min-h-[112px] rounded-2xl border border-indigo-100 bg-indigo-50/70 p-4 dark:border-indigo-900/60 dark:bg-indigo-950/30' : selectedResult?.success ? 'mt-5 min-h-[112px] rounded-2xl border border-emerald-100 bg-emerald-50/70 p-4 dark:border-emerald-900/60 dark:bg-emerald-950/30' : selectedResult ? 'mt-5 min-h-[112px] rounded-2xl border border-rose-100 bg-rose-50/70 p-4 dark:border-rose-900/60 dark:bg-rose-950/30' : 'mt-5 min-h-[112px] rounded-2xl border border-slate-100 bg-white/70 p-4 dark:border-slate-800 dark:bg-slate-950/45'}>
          {selectedTesting ? <div className="flex items-start gap-3"><RefreshCw className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-indigo-600" /><div><p className="text-sm font-bold text-indigo-900 dark:text-indigo-100">{tx('ai.provider.detail.testing')}</p><p className="mt-1 text-xs leading-5 text-indigo-900/65 dark:text-indigo-200/65">{tx('ai.provider.detail.testingBody')}</p></div></div> : selectedResult ? <div className="flex items-start gap-3">{selectedResult.success ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" />}<div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><p className="text-sm font-bold text-slate-900 dark:text-white">{getTestTitle(selectedResult, tx)}</p>{typeof selectedResult.latency_ms === 'number' && <span className="rounded-full bg-white/80 px-2 py-0.5 text-[10px] font-semibold text-slate-600">{selectedResult.latency_ms} ms</span>}</div><p className="mt-1 text-xs leading-5 text-slate-600 dark:text-slate-300">{getTestDescription(selectedResult, tx)}</p>{!selectedResult.success && selectedResult.error_code && <p className="mt-1 text-[11px] font-mono font-semibold text-rose-700 dark:text-rose-300">{tx('ai.provider.detail.errorCode', { code: selectedResult.error_code })}</p>}{selectedResult.success && selectedResult.sample_response && <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-emerald-800 dark:text-emerald-200"><span className="font-semibold">{tx('ai.provider.detail.modelResponse')}</span><code className="max-w-full truncate rounded-md bg-white/80 px-2 py-1 font-mono">{selectedResult.sample_response}</code></div>}</div></div> : <div className="flex items-start gap-3"><Clock3 className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" /><div><p className="text-sm font-semibold text-slate-700 dark:text-slate-200">{tx('ai.provider.detail.notTested')}</p><p className="mt-1 text-xs leading-5 text-slate-400 dark:text-slate-500">{tx('ai.provider.detail.notTestedBody')}</p></div></div>}
        </div>
        <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-indigo-100 pt-4 dark:border-indigo-900/50"><div className="flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400"><Clock3 className="h-3.5 w-3.5" />{tx('ai.provider.detail.timeout', { seconds: selectedProvider.timeout, count: selectedProvider.max_retries })}</div><button type="button" onClick={() => onTest(selectedProvider.id)} disabled={selectedTesting || selectedDeleting} className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-xs font-bold text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-wait disabled:opacity-60">{selectedTesting ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5" />}{selectedTesting ? tx('ai.provider.detail.testingShort') : tx('ai.provider.detail.test')}</button></div>
      </section>
    </div>
  );
};

function cnProviderRow(active: boolean): string {
  return active
    ? 'flex items-center gap-2 rounded-xl border border-indigo-300 bg-indigo-50/80 p-3 shadow-sm dark:border-indigo-800 dark:bg-indigo-950/30'
    : 'flex items-center gap-2 rounded-xl border border-transparent p-3 transition hover:border-slate-200 hover:bg-slate-50 dark:hover:border-slate-700 dark:hover:bg-slate-800/60';
}

export const ProviderManagementTab: React.FC = () => {
  const { language, showToast } = useCoreApp();
  const tx = (key: string, variables?: TextVariables) => aiAdminText(key, language, variables);
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState('');
  const [appliedSearch, setAppliedSearch] = useState('');
  const [dataRegionFilter, setDataRegionFilter] = useState('');
  const [healthFilter, setHealthFilter] = useState('');
  const [enabledFilter, setEnabledFilter] = useState('all');
  const [providerTypeFilter, setProviderTypeFilter] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [providerFacets, setProviderFacets] = useState({ data_regions: [] as string[], health_statuses: [] as string[], provider_types: [] as string[], tags: [] as string[] });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<ProviderTestResult | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [selectedProviderId, setSelectedProviderId] = useState<string | null>(null);

  const [showModal, setShowModal] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [providerType, setProviderType] = useState('deepseek');
  const [baseUrl, setBaseUrl] = useState('https://api.deepseek.com');
  const [apiKey, setApiKey] = useState('');
  const [showApiKey, setShowApiKey] = useState(false);
  const [defaultModelCode, setDefaultModelCode] = useState('deepseek-v4-flash');
  const [timeout, setTimeout] = useState(30);
  const [dataRegion, setDataRegion] = useState('unknown');
  const [allowedDataClassification, setAllowedDataClassification] = useState('PUBLIC');
  const [submitting, setSubmitting] = useState(false);

  const fetchProviders = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getAIProvidersPage({
        search: appliedSearch,
        data_region: dataRegionFilter,
        health_status: healthFilter,
        enabled: enabledFilter === 'all' ? undefined : enabledFilter === 'enabled',
        provider_type: providerTypeFilter,
        tag: tagFilter,
        page,
        page_size: pageSize,
      });
      setProviders(result.items);
      setTotal(result.total);
      setProviderFacets({
        data_regions: result.facets?.data_regions || [],
        health_statuses: result.facets?.health_statuses || [],
        provider_types: result.facets?.provider_types || [],
        tags: result.facets?.tags || [],
      });
      setSelectedProviderId((current) => current && result.items.some((item) => item.id === current) ? current : (result.items[0]?.id || null));
    } catch (err: unknown) {
      const message = getErrorMessage(err, tx('ai.provider.error.list'));
      setError(message);
      showToast(message, 'error');
    } finally {
      setLoading(false);
    }
  }, [appliedSearch, dataRegionFilter, enabledFilter, healthFilter, language, page, pageSize, providerTypeFilter, showToast, tagFilter]);

  useEffect(() => {
    void fetchProviders();
  }, [fetchProviders]);

  useEffect(() => {
    if (selectedProviderId && providers.some((provider) => provider.id === selectedProviderId)) return;
    setSelectedProviderId(providers[0]?.id || null);
  }, [providers, selectedProviderId]);

  const handleTest = async (id: string) => {
    const provider = providers.find((item) => item.id === id);
    setTestingId(id);
    setTestResult(null);
    try {
      const res = await testAIProvider(id);
      const result: ProviderTestResult = {
        id,
        success: res.success,
        message: res.message,
        latency_ms: res.latency_ms,
        sample_response: res.sample_response,
        model_tested: res.model_tested,
        error_code: res.error_code,
      };
      setTestResult(result);
      // Keep the summary card in sync with the just-completed probe. The API
      // persists the health result, but the list is otherwise only refreshed
      // on mount/manual refresh, which could leave a stale AI_SECURITY_BLOCKED
      // badge visible after a successful test.
      setProviders((current) => current.map((item) => item.id === id
        ? {
            ...item,
            health_status: result.success ? 'healthy' : 'unhealthy',
            last_error_code: result.success ? null : (result.error_code || item.last_error_code),
          }
        : item));
      showToast(tx(result.success ? 'ai.provider.toast.testPassed' : 'ai.provider.toast.testFailed', { name: provider?.name || 'Provider' }), result.success ? 'success' : 'error');
    } catch (err: unknown) {
      const result: ProviderTestResult = {
        id,
        success: false,
        message: getErrorMessage(err, tx('ai.provider.error.test')),
      };
      setTestResult(result);
      showToast(result.message, 'error');
    } finally {
      setTestingId(null);
    }
  };

  const handleDelete = async (id: string) => {
    const provider = providers.find((item) => item.id === id);
    try {
      const preview: AIProviderDeletePreview = await getAIProviderDeletePreview(id);
      const modelCount = Number(preview.model_count) || 0;
      const routeCount = Number(preview.route_count) || 0;
      if (!preview.can_delete || modelCount > 0 || routeCount > 0) {
        showToast(tx('ai.provider.delete.blocked', { name: provider?.name || 'Provider', models: modelCount, routes: routeCount }), 'error');
        return;
      }
      if (!window.confirm(tx('ai.provider.delete.preview', { name: provider?.name || 'Provider' }))) return;
    } catch {
      if (!window.confirm(tx('ai.provider.delete.previewFailed'))) return;
    }

    setDeletingId(id);
    try {
      await deleteAIProvider(id);
      await fetchProviders();
      if (selectedProviderId === id) setSelectedProviderId(null);
      if (testResult?.id === id) setTestResult(null);
      showToast(tx('ai.provider.toast.deleted', { name: provider?.name || 'Provider' }), 'success');
    } catch (err: unknown) {
      showToast(getProviderDeleteErrorMessage(err, provider?.name || 'Provider', tx), 'error');
    } finally {
      setDeletingId(null);
    }
  };

  const handleToggle = async (provider: AIProvider) => {
    try {
      const updated = await updateAIProvider(provider.id, { enabled: !provider.enabled });
      setProviders((current) => current.map((item) => item.id === updated.id ? updated : item));
      await fetchProviders();
      showToast(tx('ai.provider.toast.toggled', { name: provider.name, status: tx(updated.enabled ? 'ai.provider.status.enabled' : 'ai.provider.status.disabled') }), 'success');
    } catch (err: unknown) {
      showToast(getErrorMessage(err, tx('ai.provider.error.toggle')), 'error');
    }
  };

  const openEdit = (provider: AIProvider) => {
    setEditingId(provider.id);
    setName(provider.name);
    setProviderType(provider.provider_type);
    setBaseUrl(provider.base_url || '');
    setApiKey('');
    setShowApiKey(false);
    setDefaultModelCode('');
    setTimeout(provider.timeout || 30);
    setDataRegion(provider.data_region || 'unknown');
    setAllowedDataClassification(provider.allowed_data_classification || 'PUBLIC');
    setShowModal(true);
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      if (editingId) {
        await updateAIProvider(editingId, { name, provider_type: providerType, base_url: baseUrl || undefined, api_key: apiKey || undefined, timeout, data_region: dataRegion, allowed_data_classification: allowedDataClassification });
      } else {
        await createAIProvider({ name, provider_type: providerType, base_url: baseUrl || undefined, api_key: apiKey || undefined, default_model_code: defaultModelCode || undefined, timeout, data_region: dataRegion, enabled: true, allowed_data_classification: allowedDataClassification });
      }
      setShowModal(false);
      setEditingId(null);
      setName('');
      setApiKey('');
      setBaseUrl('https://api.deepseek.com');
      setShowApiKey(false);
      setDefaultModelCode('deepseek-v4-flash');
      setTimeout(30);
      setDataRegion('unknown');
      setAllowedDataClassification('PUBLIC');
      await fetchProviders();
      showToast(tx(editingId ? 'ai.provider.toast.updated' : 'ai.provider.toast.added'), 'success');
    } catch (err: unknown) {
      showToast(getErrorMessage(err, tx('ai.provider.error.create')), 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const activeCount = providers.filter((provider) => provider.enabled).length;
  const securedCount = providers.filter((provider) => Boolean(provider.api_key_masked)).length;

  const submitSearch = (event: React.FormEvent) => {
    event.preventDefault();
    setPage(1);
    setAppliedSearch(search.trim());
  };

  const clearProviderFilters = () => {
    setSearch('');
    setAppliedSearch('');
    setDataRegionFilter('');
    setHealthFilter('');
    setEnabledFilter('all');
    setProviderTypeFilter('');
    setTagFilter('');
    setPage(1);
  };

  return (
    <div className="w-full space-y-5 pb-8">
      <section className="relative overflow-hidden rounded-[26px] border border-indigo-100/80 bg-gradient-to-br from-white via-indigo-50/70 to-violet-100/70 px-5 py-6 shadow-sm shadow-indigo-100/50 dark:border-indigo-900/60 dark:from-slate-900 dark:via-indigo-950/50 dark:to-slate-900 dark:shadow-none sm:px-7 sm:py-7">
        <div className="pointer-events-none absolute -right-20 -top-24 h-64 w-64 rounded-full bg-indigo-300/20 blur-3xl dark:bg-indigo-500/10" />
        <div className="pointer-events-none absolute -bottom-32 left-1/3 h-64 w-64 rounded-full bg-violet-300/20 blur-3xl dark:bg-violet-500/10" />
        <div className="relative flex flex-col justify-between gap-6 xl:flex-row xl:items-center">
          <div className="max-w-3xl">
            <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-indigo-200/80 bg-white/70 px-3 py-1 text-[11px] font-bold uppercase tracking-[0.18em] text-indigo-600 dark:border-indigo-800 dark:bg-indigo-950/50 dark:text-indigo-300">
              <Activity className="h-3.5 w-3.5" />
              {tx('ai.provider.header.eyebrow')}
            </div>
            <h2 className="nx-page-title flex items-center gap-3 text-slate-950 dark:text-white">
              <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-indigo-600 text-white shadow-lg shadow-indigo-600/25">
                <Bot className="h-6 w-6" />
              </span>
              {tx('ai.provider.header.title')}
            </h2>
            <p className="nx-page-description mt-3 max-w-2xl text-slate-600 dark:text-slate-300">{tx('ai.provider.header.description')}</p>
            <div className="mt-4 flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-white/75 px-2.5 py-1.5 font-medium shadow-sm shadow-indigo-100/50 dark:bg-slate-900/70 dark:shadow-none">
                <ShieldCheck className="h-3.5 w-3.5 text-emerald-500" />
                {tx('ai.provider.security.keys')}
              </span>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-white/75 px-2.5 py-1.5 font-medium shadow-sm shadow-indigo-100/50 dark:bg-slate-900/70 dark:shadow-none">
                <LockKeyhole className="h-3.5 w-3.5 text-indigo-500" />
                {tx('ai.provider.security.gateway')}
              </span>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-2 self-start xl:self-center">
            <ActionLink
              href="/downloads/nexora-ai-provider-debug-manual.md"
              download={tx('ai.provider.manual.filename')}
              aria-label={tx('ai.provider.manual.aria')}
              title={tx('ai.provider.manual.title')}
              icon={Download}
              variant="accent"
              size="md"
            >
              {tx('ai.provider.manual.label')}
            </ActionLink>
            <ActionButton
              type="button"
              icon={RefreshCw}
              iconClassName={loading ? 'animate-spin' : undefined}
              variant="default"
              size="md"
              onClick={() => void fetchProviders()}
            >
              {tx('ai.common.refresh')}
            </ActionButton>
            <button
              type="button"
              onClick={() => { setEditingId(null); setApiKey(''); setShowApiKey(false); setDataRegion('unknown'); setAllowedDataClassification('PUBLIC'); setShowModal(true); }}
              className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-600/20 transition hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 dark:focus:ring-offset-slate-950"
            >
              <Plus className="h-4 w-4" />
              {tx('ai.provider.action.add')}
            </button>
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900" aria-label={tx('ai.provider.filter.aria')}>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><div><h3 className="text-sm font-bold text-slate-900 dark:text-white">{tx('ai.provider.filter.title')}</h3><p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">{tx('ai.provider.filter.body')}</p></div><span className="rounded-full bg-indigo-50 px-2.5 py-1 text-[10px] font-semibold text-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-300">{tx('ai.provider.filter.count', { count: total })}</span></div>
        <form onSubmit={submitSearch} className="grid gap-2 md:grid-cols-2 xl:grid-cols-6">
          <div className="relative md:col-span-2 xl:col-span-2"><Eye className="pointer-events-none absolute left-3 top-2.5 h-3.5 w-3.5 text-slate-400" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={tx('ai.provider.filter.search')} aria-label={tx('ai.provider.filter.searchLabel')} className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2 pl-9 pr-3 text-xs outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white" /></div>
          <select value={dataRegionFilter} onChange={(event) => { setDataRegionFilter(event.target.value); setPage(1); }} aria-label={tx('ai.provider.filter.regionLabel')} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-950 dark:text-white"><option value="">{tx('ai.provider.filter.allRegions')}</option>{Array.from(new Set([...DATA_REGION_OPTIONS.map((item) => item.value), ...providerFacets.data_regions])).map((region) => <option key={region} value={region}>{DATA_REGION_OPTIONS.find((item) => item.value === region) ? tx(DATA_REGION_OPTIONS.find((item) => item.value === region)!.labelKey) : region}</option>)}</select>
          <select value={healthFilter} onChange={(event) => { setHealthFilter(event.target.value); setPage(1); }} aria-label={tx('ai.provider.filter.allHealth')} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-950 dark:text-white"><option value="">{tx('ai.provider.filter.allHealth')}</option>{Array.from(new Set(['healthy', 'unhealthy', 'unknown', 'disabled', ...providerFacets.health_statuses])).map((health) => <option key={health} value={health}>{health}</option>)}</select>
          <select value={enabledFilter} onChange={(event) => { setEnabledFilter(event.target.value); setPage(1); }} aria-label={tx('ai.provider.filter.allEnabled')} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-950 dark:text-white"><option value="all">{tx('ai.provider.filter.allEnabled')}</option><option value="enabled">{tx('ai.provider.status.enabled')}</option><option value="disabled">{tx('ai.provider.status.disabled')}</option></select>
          <select value={providerTypeFilter} onChange={(event) => { setProviderTypeFilter(event.target.value); setPage(1); }} aria-label={tx('ai.provider.filter.allTypes')} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-950 dark:text-white"><option value="">{tx('ai.provider.filter.allTypes')}</option>{providerFacets.provider_types.map((type) => <option key={type} value={type}>{type}</option>)}</select>
          <select value={tagFilter} onChange={(event) => { setTagFilter(event.target.value); setPage(1); }} aria-label={tx('ai.provider.filter.allTags')} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-950 dark:text-white"><option value="">{tx('ai.provider.filter.allTags')}</option>{providerFacets.tags.map((tag) => <option key={tag} value={tag}>{tag}</option>)}</select>
          <div className="flex gap-2 md:col-span-2 xl:col-span-6"><button type="submit" className="rounded-xl bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700">{tx('ai.provider.filter.searchAction')}</button><button type="button" onClick={clearProviderFilters} className="rounded-xl border border-slate-200 px-4 py-2 text-xs font-semibold text-slate-600 hover:border-indigo-300 dark:border-slate-700 dark:text-slate-300">{tx('ai.common.clearFilters')}</button></div>
        </form>
      </section>

      <section className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <MetricCard
          icon={Bot}
          label={tx('ai.provider.metric.total')}
          value={total}
          helper={tx('ai.provider.metric.totalHelp')}
          tone="indigo"
        />
        <MetricCard
          icon={CheckCircle2}
          label={tx('ai.provider.metric.enabled')}
          value={activeCount}
          helper={tx('ai.provider.metric.enabledHelp')}
          tone="emerald"
        />
        <MetricCard
          icon={KeyRound}
          label={tx('ai.provider.metric.keys')}
          value={`${securedCount}/${providers.length}`}
          helper={tx('ai.provider.metric.keysHelp')}
          tone="amber"
        />
        <MetricCard
          icon={ShieldCheck}
          label={tx('ai.provider.metric.channel')}
          value="AES-256"
          helper={tx('ai.provider.metric.channelHelp')}
          tone="slate"
        />
      </section>

      <section className="flex flex-col gap-3 rounded-2xl border border-indigo-100 bg-indigo-50/65 px-4 py-4 dark:border-indigo-900/70 dark:bg-indigo-950/25 sm:flex-row sm:items-start sm:px-5">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-white shadow-md shadow-indigo-600/20">
          <CircleAlert className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-bold text-indigo-950 dark:text-indigo-100">{tx('ai.provider.probe.title')}</h3>
            <span className="rounded-full bg-white/80 px-2 py-0.5 text-[10px] font-semibold text-indigo-600 dark:bg-indigo-900/60 dark:text-indigo-300">
              {tx('ai.provider.probe.badge')}
            </span>
          </div>
          <p className="mt-1.5 max-w-4xl text-xs leading-5 text-indigo-900/70 dark:text-indigo-200/70">
            {tx('ai.provider.probe.body')}
          </p>
          <p className="mt-2 text-[11px] text-indigo-900/55 dark:text-indigo-200/55">
            {tx('ai.provider.probe.label')}
            <code className="rounded bg-white/70 px-1.5 py-0.5 font-mono text-[10px] text-indigo-700 dark:bg-indigo-900/50 dark:text-indigo-200">Reply with one short word: ok</code>
          </p>
        </div>
      </section>

      {error && (
        <div className="flex flex-col gap-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/70 dark:bg-rose-950/30 dark:text-rose-300 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-2">
            <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
          <button type="button" onClick={() => void fetchProviders()} className="self-start rounded-lg bg-white/80 px-3 py-1.5 text-xs font-semibold text-rose-700 transition hover:bg-white dark:bg-rose-900/30 dark:text-rose-200 dark:hover:bg-rose-900/50 sm:self-auto">
            {tx('ai.common.retry')}
          </button>
        </div>
      )}

      {loading ? (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {[0, 1].map((item) => (
            <div key={item} className="h-[380px] animate-pulse rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
              <div className="h-12 w-2/3 rounded-xl bg-slate-100 dark:bg-slate-800" />
              <div className="mt-6 h-28 rounded-2xl bg-slate-100 dark:bg-slate-800" />
              <div className="mt-4 h-24 rounded-2xl bg-slate-100 dark:bg-slate-800" />
              <div className="mt-6 h-10 rounded-xl bg-slate-100 dark:bg-slate-800" />
            </div>
          ))}
        </div>
      ) : providers.length === 0 ? (
        <div className="relative overflow-hidden rounded-2xl border border-dashed border-slate-300 bg-white/80 px-6 py-14 text-center dark:border-slate-700 dark:bg-slate-900/60">
          <div className="pointer-events-none absolute left-1/2 top-0 h-32 w-64 -translate-x-1/2 rounded-full bg-indigo-100/70 blur-3xl dark:bg-indigo-900/20" />
          <span className="relative mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-indigo-50 text-indigo-500 dark:bg-indigo-950/50 dark:text-indigo-300">
            <Bot className="h-7 w-7" />
          </span>
          <h3 className="relative mt-4 text-base font-bold text-slate-800 dark:text-white">{tx('ai.provider.empty.title')}</h3>
          <p className="relative mx-auto mt-1.5 max-w-md text-sm leading-6 text-slate-500 dark:text-slate-400">
            {tx('ai.provider.empty.body')}
          </p>
          <button type="button" onClick={() => { setEditingId(null); setApiKey(''); setShowApiKey(false); setDataRegion('unknown'); setAllowedDataClassification('PUBLIC'); setShowModal(true); }} className="relative mt-5 inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-600/20 transition hover:bg-indigo-700">
            <Plus className="h-4 w-4" />
            {tx('ai.provider.empty.action')}
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          <ProviderRegistryWorkspace
            providers={providers}
            total={total}
            selectedProviderId={selectedProviderId}
            onSelect={setSelectedProviderId}
            onEdit={openEdit}
            onToggle={(provider) => void handleToggle(provider)}
            onDelete={(id) => void handleDelete(id)}
            onTest={(id) => void handleTest(id)}
            testingId={testingId}
            deletingId={deletingId}
            testResult={testResult}
            tx={tx}
          />
          <Pagination currentPage={page} totalItems={total} itemsPerPage={pageSize} onPageChange={setPage} onItemsPerPageChange={(size) => { setPageSize(size); setPage(1); }} language={language} alwaysVisible />
        </div>
      )}

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="add-provider-title">
          <div className="flex max-h-[calc(100vh-2rem)] w-full max-w-xl flex-col overflow-hidden rounded-3xl border border-white/60 bg-white shadow-2xl shadow-slate-950/20 dark:border-slate-700 dark:bg-slate-900">
            <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-5 dark:border-slate-800 sm:px-6">
              <div>
                <div className="mb-2 inline-flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.16em] text-indigo-500">
                  <Plus className="h-3.5 w-3.5" />
                  {tx('ai.provider.editor.eyebrow')}
                </div>
                <h3 id="add-provider-title" className="text-xl font-bold tracking-tight text-slate-950 dark:text-white">{tx(editingId ? 'ai.provider.editor.editTitle' : 'ai.provider.editor.newTitle')}</h3>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{tx('ai.provider.editor.body')}</p>
              </div>
              <button type="button" onClick={() => { setEditingId(null); setShowApiKey(false); setShowModal(false); }} aria-label={tx('ai.provider.editor.close')} className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200">
                <X className="h-5 w-5" />
              </button>
            </div>

            <form onSubmit={handleCreate} className="overflow-y-auto px-5 py-5 sm:px-6">
              <div className="space-y-4">
                <div>
                  <label htmlFor="provider-data-region" className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">{tx('ai.provider.editor.region')}</label>
                  <select
                    id="provider-data-region"
                    value={dataRegion}
                    onChange={(e) => setDataRegion(e.target.value)}
                    className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 outline-none transition focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                  >
                    {DATA_REGION_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.value} · {tx(option.labelKey)}</option>)}
                  </select>
                  <p className="mt-1.5 text-[10px] text-slate-400">{tx('ai.provider.editor.regionBody')}</p>
                </div>

                <div>
                  <label htmlFor="provider-name" className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">{tx('ai.provider.editor.name')}</label>
                  <input id="provider-name" type="text" required placeholder={tx('ai.provider.editor.namePlaceholder')} value={name} onChange={(e) => setName(e.target.value)} className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
                </div>

                <div>
                  <label className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">{tx('ai.provider.editor.type')}</label>
                  <select value={providerType} onChange={(e) => {
                    const next = e.target.value;
                    setProviderType(next);
                    if (next === 'deepseek') { setBaseUrl('https://api.deepseek.com'); setDefaultModelCode('deepseek-v4-flash'); }
                    else if (next === 'openai' || next === 'azure_openai') { setBaseUrl('https://api.openai.com/v1'); setDefaultModelCode('gpt-4o'); }
                    else if (next === 'ollama' || next === 'local') { setBaseUrl('http://127.0.0.1:11434/v1'); setDefaultModelCode('llama3.1'); }
                    else { setBaseUrl(''); setDefaultModelCode(''); }
                  }} className="w-full rounded-xl border border-indigo-200 bg-indigo-50/70 px-3.5 py-2.5 text-sm font-semibold text-indigo-950 dark:border-indigo-900/60 dark:bg-indigo-950/30 dark:text-indigo-100">
                    <option value="deepseek">{tx('ai.provider.editor.deepseek')}</option>
                    <option value="openai">OpenAI</option>
                    <option value="openai_compatible">{tx('ai.provider.editor.compatible')}</option>
                    <option value="azure_openai">Azure OpenAI</option>
                    <option value="qwen">{tx('ai.provider.editor.qwen')}</option>
                    <option value="ollama">{tx('ai.provider.editor.ollama')}</option>
                    <option value="local">Local OpenAI-compatible</option>
                  </select>
                </div>

                <div>
                  <label htmlFor="provider-base-url" className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">Base URL</label>
                  <input id="provider-base-url" type="url" placeholder="https://api.deepseek.com" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 font-mono text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
                </div>

                <div>
                  <div className="mb-1.5 flex items-center justify-between gap-3">
                    <label htmlFor="provider-api-key" className="block text-xs font-bold text-slate-700 dark:text-slate-300">API Key</label>
                    <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-emerald-600 dark:text-emerald-400"><LockKeyhole className="h-3 w-3" />AES-256-GCM</span>
                  </div>
                  <div className="relative">
                    <input id="provider-api-key" type={showApiKey ? 'text' : 'password'} required={providerType !== 'ollama' && providerType !== 'local' && !editingId} placeholder={editingId ? tx('ai.provider.editor.keyOptionalOnEdit') : providerType === 'ollama' || providerType === 'local' ? tx('ai.provider.editor.apiKeyOptional') : 'sk-...'} value={apiKey} onChange={(e) => setApiKey(e.target.value)} className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 pr-11 font-mono text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
                    <button
                      type="button"
                      onClick={() => setShowApiKey((visible) => !visible)}
                      aria-label={tx(showApiKey ? 'ai.provider.editor.keyVisibility.hide' : 'ai.provider.editor.keyVisibility.show')}
                      title={tx(showApiKey ? 'ai.provider.editor.keyVisibility.hideTitle' : 'ai.provider.editor.keyVisibility.showTitle')}
                      className="absolute right-2 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-indigo-600 dark:hover:bg-slate-800 dark:hover:text-indigo-300"
                    >
                      {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>

                <div className="grid gap-4 sm:grid-cols-[1fr_150px]">
                  <div>
                    <label htmlFor="provider-model-code" className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">{tx('ai.provider.editor.model')} <span className="font-normal text-slate-400">(Model Code)</span></label>
                    <input id="provider-model-code" type="text" placeholder="deepseek-v4-flash" value={defaultModelCode} onChange={(e) => setDefaultModelCode(e.target.value)} className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 font-mono text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
                    <p className="mt-1.5 text-[10px] text-slate-400">{tx('ai.provider.editor.modelHelp')}</p>
                  </div>
                  <div>
                    <label htmlFor="provider-timeout" className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">{tx('ai.provider.editor.timeout')}</label>
                    <input id="provider-timeout" type="number" min={5} max={300} value={timeout} onChange={(e) => setTimeout(Number(e.target.value) || 30)} className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 outline-none transition focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
                  </div>
                </div>

                <div>
                  <label htmlFor="provider-allowed-data-classification" className="mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300">{tx('ai.provider.editor.classification')}</label>
                  <select
                    id="provider-allowed-data-classification"
                    value={allowedDataClassification}
                    onChange={(e) => setAllowedDataClassification(e.target.value)}
                    className="w-full rounded-xl border border-indigo-200 bg-indigo-50/70 px-3.5 py-2.5 text-sm font-semibold text-indigo-950 dark:border-indigo-900/60 dark:bg-indigo-950/30 dark:text-indigo-100"
                  >
                    <option value="PUBLIC">PUBLIC · {tx('ai.provider.editor.public')}</option>
                    <option value="INTERNAL">INTERNAL · {tx('ai.provider.editor.internal')}</option>
                    <option value="CONFIDENTIAL">CONFIDENTIAL · {tx('ai.provider.editor.confidential')}</option>
                  </select>
                  <p className="mt-1.5 text-[10px] text-slate-400">{tx('ai.provider.editor.classificationHelp')}</p>
                </div>

              </div>

              <div className="mt-6 flex flex-col-reverse gap-2 border-t border-slate-100 pt-4 dark:border-slate-800 sm:flex-row sm:justify-end">
                <button type="button" onClick={() => { setEditingId(null); setShowApiKey(false); setShowModal(false); }} className="rounded-xl px-4 py-2.5 text-sm font-semibold text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 dark:hover:bg-slate-800 dark:hover:text-slate-200">{tx('ai.provider.editor.cancel')}</button>
                <button type="submit" disabled={submitting} className="inline-flex items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-600/20 transition hover:bg-indigo-700 disabled:cursor-wait disabled:opacity-60">
                  {submitting && <RefreshCw className="h-4 w-4 animate-spin" />}
                  {submitting ? tx('ai.provider.editor.saving') : (editingId ? tx('ai.provider.editor.save') : tx('ai.provider.editor.add'))}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
