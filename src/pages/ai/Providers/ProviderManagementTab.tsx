import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Ban,
  CheckCircle2,
  Clock3,
  Download,
  History,
  LockKeyhole,
  Pencil,
  Plug,
  Plus,
  Power,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  X,
  XCircle,
} from 'lucide-react';
import { PasswordInputField } from '../../../components/ui/PasswordInputField';
import { getAIProvidersPage, createAIProvider, updateAIProvider, deleteAIProvider, getAIProviderDeletePreview, testAIProvider, AIProvider, AIProviderDeletePreview } from '../../../api/ai';
import { ApiError } from '../../../api/http';
import { useCoreApp } from '../../../contexts/AppDomainContext';
import { useEscapeClose } from '../../../hooks/useEscapeClose';
import { useFocusTrap } from '../../../hooks/useFocusTrap';
import { ActionButton, ActionIconButton, ActionIconGroup, ActionLink } from '../../../components/ui/ActionIconButton';
import { PageHeader } from '../../../components/ui/PageHeader';
import { Panel } from '../../../components/ui/Panel';
import { StatusBadge, type StatusTone } from '../../../components/ui/StatusBadge';
import { SummaryBar } from '../../../components/ui/SummaryBar';
import { EmptyState } from '../../../components/ui/EmptyState';
import { InfoTip } from '../../../components/ui/InfoTip';
import Pagination from '../../../components/Pagination';
import { cn } from '../../../lib/cn';
import { aiAdminText } from '../../../i18n/aiAdmin';
import { getProviderPageCopy, type ProviderPageCopy } from './ProviderManagementTab.copy';
import { ProviderKeyHistoryDrawer, ProviderKeyInvalidateDialog } from './ProviderKeyDialogs';
import { defaultProviderPreset, getProviderPreset, identifyProviderPreset, providerPresetGroups } from './providerPresets';

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

const DATA_REGION_OPTIONS = [
  { value: 'unknown', labelKey: 'ai.provider.region.unknown' },
  { value: 'global', labelKey: 'ai.provider.region.global' },
  { value: 'cn', labelKey: 'ai.provider.region.cn' },
  { value: 'us', labelKey: 'ai.provider.region.us' },
  { value: 'eu', labelKey: 'ai.provider.region.eu' },
] as const;

/* Shared control styles — token based, 36px controls, 8px radius. */
const filterControlClass = 'h-9 rounded-lg border border-line bg-surface px-3 text-[13px] text-fg outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-accent/20';
const fieldLabelClass = 'mb-1.5 block text-[13px] font-medium text-fg';
const fieldInputClass = 'w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-fg outline-none transition-colors placeholder:text-fg-subtle focus:border-accent focus:ring-2 focus:ring-accent/20';
const fieldHelpClass = 'mt-1.5 text-xs leading-5 text-fg-muted';

const getErrorMessage = (error: unknown, fallback: string) => (
  error instanceof Error && error.message ? error.message : fallback
);

const getHealthStatusKey = (status?: string) => {
  switch (String(status || 'unknown').toLowerCase()) {
    case 'healthy': return 'ai.provider.status.healthy';
    case 'unhealthy': return 'ai.provider.status.unhealthy';
    case 'disabled': return 'ai.provider.status.disabled';
    case 'not_supported': return 'ai.provider.status.notSupported';
    default: return 'ai.provider.status.unknown';
  }
};

const getHealthTone = (status?: string): StatusTone => {
  switch (String(status || 'unknown').toLowerCase()) {
    case 'healthy': return 'success';
    case 'unhealthy': return 'danger';
    default: return 'neutral';
  }
};

const getPersistedTestResult = (provider: AIProvider): ProviderTestResult | null => {
  const status = String(provider.health_status || 'unknown').toLowerCase();
  if (!provider.last_health_check_at || !['healthy', 'unhealthy'].includes(status)) return null;
  return {
    id: provider.id,
    success: status === 'healthy',
    message: status === 'healthy' ? 'persisted provider health check passed' : 'persisted provider health check failed',
    model_tested: null,
    error_code: status === 'healthy' ? null : (provider.last_error_code || null),
  };
};

const HealthStatusBadge: React.FC<{ status?: string; tx: AIAdminText }> = ({ status, tx }) => (
  <StatusBadge tone={getHealthTone(status)} dot>{tx(getHealthStatusKey(status))}</StatusBadge>
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

export const ALLOWLIST_EXCEEDS_DEPLOYMENT = 'AI_PROVIDER_ALLOWLIST_EXCEEDS_DEPLOYMENT';

/** Readable text for a Provider allowlist that goes beyond the deployment allowlist; null for other errors. */
export const getAllowlistCeilingError = (error: unknown, pc: ProviderPageCopy): string | null => {
  if (!error || typeof error !== 'object') return null;
  const record = error as { code?: unknown; detail?: unknown };
  const detail = record.detail && typeof record.detail === 'object' ? record.detail as Record<string, unknown> : null;
  const code = typeof record.code === 'string' && record.code
    ? record.code
    : (detail && typeof detail.code === 'string' ? detail.code : '');
  if (code !== ALLOWLIST_EXCEEDS_DEPLOYMENT) return null;
  const details = detail && detail.details && typeof detail.details === 'object' ? detail.details as Record<string, unknown> : null;
  const rejected = details && Array.isArray(details.rejected_patterns)
    ? details.rejected_patterns.filter((item): item is string => typeof item === 'string').slice(0, 5).join('、')
    : '';
  const configured = details ? details.deployment_allowlist_configured !== false : true;
  return configured ? pc.allowlistExceedsDeployment(rejected) : pc.allowlistExceedsNoDeployment(rejected);
};

const getTestTitle = (result: ProviderTestResult, tx: AIAdminText) => (
  tx(result.success ? 'ai.provider.test.passed' : 'ai.provider.test.failed')
);

const TEST_ERROR_KEYS: Record<string, string> = {
  AI_SECURITY_CLASSIFICATION_DENIED: 'ai.provider.test.classification',
  AI_SECURITY_POLICY_DISABLED: 'ai.provider.test.policy',
  AI_AUTH_FAILED: 'ai.provider.test.auth',
  AI_PROVIDER_CIRCUIT_OPEN: 'ai.provider.test.circuit',
  AI_HEALTH_BACKOFF: 'ai.provider.test.backoff',
  AI_MODEL_NOT_FOUND: 'ai.provider.test.modelNotFound',
  AI_PROVIDER_NO_ENABLED_MODEL: 'ai.provider.test.noEnabledModel',
  AI_PROVIDER_UNSUPPORTED: 'ai.provider.test.unsupported',
  AI_NETWORK_ERROR: 'ai.provider.test.network',
};

const getTestDescription = (result: ProviderTestResult, tx: AIAdminText) => {
  if (result.success) {
    return tx('ai.provider.test.successDescription', { model: result.model_tested ? ` · ${result.model_tested}` : '' });
  }
  return tx((result.error_code && TEST_ERROR_KEYS[result.error_code]) || 'ai.provider.test.generic');
};

const regionLabel = (value: string | null | undefined, tx: AIAdminText) => {
  const option = DATA_REGION_OPTIONS.find((item) => item.value === String(value || '').toLowerCase());
  return option ? tx(option.labelKey) : (value || tx('ai.provider.region.unknown'));
};

const endpointHost = (url?: string | null) => {
  if (!url) return null;
  try { return new URL(url).host || url; } catch { return url; }
};

/** Host name only (no port), matching the server's endpoint-change rule. */
const endpointHostname = (url?: string | null) => {
  if (!url) return '';
  try { return new URL(url).hostname.toLowerCase(); } catch { return ''; }
};

const isLocalType = (type?: string | null) => type === 'ollama' || type === 'local';

/** Textarea value (one pattern per line) -> normalized list. */
export const parseEndpointPatterns = (value: string): string[] => (
  Array.from(new Set(value.split(/\r?\n/).map((line) => line.trim().replace(/\/+$/, '')).filter(Boolean)))
);

/** 1-based line numbers of entries that are not HTTPS URL patterns. */
export const invalidEndpointPatternLines = (value: string): number[] => (
  value.split(/\r?\n/).reduce<number[]>((bad, line, index) => {
    const trimmed = line.trim();
    if (!trimmed) return bad;
    try {
      const parsed = new URL(trimmed.replace(/\*/g, 'allowlist-wildcard'));
      if (parsed.protocol !== 'https:' || !parsed.hostname) bad.push(index + 1);
    } catch {
      bad.push(index + 1);
    }
    return bad;
  }, [])
);

const sameList = (left: string[], right: string[]) => (
  left.length === right.length && left.every((item, index) => item === right[index])
);

interface ProviderRegistryWorkspaceProps {
  providers: AIProvider[];
  selectedProviderId: string | null;
  onSelect: (id: string) => void;
  onEdit: (provider: AIProvider) => void;
  onToggle: (provider: AIProvider) => void;
  onDelete: (id: string) => void;
  onTest: (id: string) => void;
  onShowKeyHistory: (provider: AIProvider) => void;
  onInvalidateKey: (provider: AIProvider) => void;
  testingId: string | null;
  deletingId: string | null;
  testResult: ProviderTestResult | null;
  tx: AIAdminText;
  pc: ProviderPageCopy;
}

const DetailRow: React.FC<{ label: React.ReactNode; children: React.ReactNode }> = ({ label, children }) => (
  <>
    <dt className="text-fg-muted">{label}</dt>
    <dd className="flex min-w-0 flex-wrap items-center gap-2 text-fg">{children}</dd>
  </>
);

const ProviderRegistryWorkspace: React.FC<ProviderRegistryWorkspaceProps> = ({
  providers,
  selectedProviderId,
  onSelect,
  onEdit,
  onToggle,
  onDelete,
  onTest,
  onShowKeyHistory,
  onInvalidateKey,
  testingId,
  deletingId,
  testResult,
  tx,
  pc,
}) => {
  const selectedProvider = providers.find((provider) => provider.id === selectedProviderId) || providers[0];
  if (!selectedProvider) return null;

  const selectedResult = testResult?.id === selectedProvider.id ? testResult : getPersistedTestResult(selectedProvider);
  const selectedTesting = testingId === selectedProvider.id;
  const selectedDeleting = deletingId === selectedProvider.id;
  const toggleLabel = tx(selectedProvider.enabled ? 'ai.provider.action.disable' : 'ai.provider.action.enable', { name: selectedProvider.name });
  const tags = Array.isArray(selectedProvider.tags) ? selectedProvider.tags : [];
  const endpointPatterns = Array.isArray(selectedProvider.approved_endpoint_patterns) ? selectedProvider.approved_endpoint_patterns : [];

  return (
    <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(380px,1fr)]">
      <Panel aria-label={tx('ai.provider.list.aria')} className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr>
                <th scope="col">{tx('ai.provider.table.name')}</th>
                <th scope="col">{tx('ai.provider.table.endpoint')}</th>
                <th scope="col">{tx('ai.provider.table.region')}</th>
                <th scope="col">{tx('ai.provider.table.health')}</th>
                <th scope="col">{tx('ai.provider.table.status')}</th>
                <th scope="col" className="nx-action-column-header"><span className="sr-only">{tx('ai.provider.table.actions')}</span></th>
              </tr>
            </thead>
            <tbody>
              {providers.map((provider) => {
                const active = provider.id === selectedProvider.id;
                const busy = testingId === provider.id || deletingId === provider.id;
                return (
                  <tr
                    key={provider.id}
                    aria-selected={active}
                    onClick={() => onSelect(provider.id)}
                    className={cn('cursor-pointer', active && '[&>td]:bg-accent-subtle')}
                  >
                    <td>
                      <button
                        type="button"
                        onClick={(event) => { event.stopPropagation(); onSelect(provider.id); }}
                        className="block max-w-[220px] text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded-md"
                        aria-label={tx('ai.provider.action.select', { name: provider.name })}
                      >
                        <span className="block truncate font-semibold text-fg">{provider.name}</span>
                        <span className="block truncate text-xs text-fg-subtle">{provider.provider_type}</span>
                      </button>
                    </td>
                    <td className="max-w-[240px] truncate font-mono text-xs text-fg-muted" title={provider.base_url || undefined}>
                      {endpointHost(provider.base_url) || tx('ai.provider.endpoint.default')}
                    </td>
                    <td className="whitespace-nowrap text-fg-muted">{regionLabel(provider.data_region, tx)}</td>
                    <td><HealthStatusBadge status={provider.health_status} tx={tx} /></td>
                    <td>
                      <StatusBadge tone={provider.enabled ? 'neutral' : 'warning'}>
                        {tx(provider.enabled ? 'ai.provider.status.enabled' : 'ai.provider.status.disabled')}
                      </StatusBadge>
                    </td>
                    <td onClick={(event) => event.stopPropagation()}>
                      <ActionIconGroup label={tx('ai.provider.list.actions')} className="nx-action-group--table">
                        <ActionIconButton icon={Pencil} label={tx('ai.provider.action.edit', { name: provider.name })} size="xs" disabled={busy} onClick={() => onEdit(provider)} />
                        <ActionIconButton icon={Power} label={tx(provider.enabled ? 'ai.provider.action.disable' : 'ai.provider.action.enable', { name: provider.name })} size="xs" disabled={busy} onClick={() => onToggle(provider)} />
                        <ActionIconButton icon={Trash2} label={tx('ai.provider.action.delete', { name: provider.name })} size="xs" variant="danger" disabled={deletingId === provider.id} onClick={() => onDelete(provider.id)} />
                      </ActionIconGroup>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel aria-label={tx('ai.provider.detail.aria')}>
        <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div className="min-w-0">
            <h3 className="truncate text-base font-semibold text-fg">{selectedProvider.name}</h3>
            <p className="mt-0.5 truncate font-mono text-xs text-fg-subtle">{selectedProvider.id}</p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <button
              type="button"
              role="switch"
              aria-checked={Boolean(selectedProvider.enabled)}
              aria-label={toggleLabel}
              title={toggleLabel}
              disabled={selectedTesting || selectedDeleting}
              onClick={() => onToggle(selectedProvider)}
              className="mr-2 inline-flex items-center gap-2 rounded-md px-1 py-1 text-[13px] text-fg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
            >
              <span className={cn('relative h-5 w-9 rounded-full transition-colors', selectedProvider.enabled ? 'bg-accent' : 'bg-line-strong')}>
                <span className={cn('absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform', selectedProvider.enabled ? 'translate-x-4' : 'translate-x-0')} />
              </span>
              {tx(selectedProvider.enabled ? 'ai.provider.status.enabled' : 'ai.provider.status.disabled')}
            </button>
            <ActionIconButton icon={Pencil} label={tx('ai.provider.action.edit', { name: selectedProvider.name })} size="sm" disabled={selectedTesting || selectedDeleting} onClick={() => onEdit(selectedProvider)} />
            <ActionIconButton icon={Trash2} label={tx('ai.provider.action.delete', { name: selectedProvider.name })} size="sm" variant="danger" disabled={selectedDeleting} onClick={() => onDelete(selectedProvider.id)} />
          </div>
        </div>

        <dl className="grid grid-cols-[104px_minmax(0,1fr)] gap-x-3 gap-y-3 px-5 py-4 text-[13px]">
          <DetailRow label={tx('ai.provider.field.type')}>{selectedProvider.provider_type}</DetailRow>
          <DetailRow label="Base URL">
            <span className="min-w-0 break-all font-mono text-xs">{selectedProvider.base_url || tx('ai.provider.endpoint.default')}</span>
          </DetailRow>
          <DetailRow label="API Key">
            <span className="font-mono text-xs">{selectedProvider.api_key_masked || tx('ai.provider.key.notConfigured')}</span>
            {selectedProvider.api_key_masked && <StatusBadge><LockKeyhole size={12} aria-hidden="true" />AES-256</StatusBadge>}
            <span className="flex flex-wrap items-center gap-1">
              <ActionButton
                type="button"
                icon={History}
                aria-label={pc.keyHistoryActionAria(selectedProvider.name)}
                title={pc.keyHistoryActionAria(selectedProvider.name)}
                onClick={() => onShowKeyHistory(selectedProvider)}
              >
                {pc.keyHistoryAction}
              </ActionButton>
              {selectedProvider.api_key_masked && (
                <ActionButton
                  type="button"
                  icon={Ban}
                  variant="danger"
                  aria-label={pc.invalidateActionAria(selectedProvider.name)}
                  title={pc.invalidateActionAria(selectedProvider.name)}
                  disabled={selectedTesting || selectedDeleting}
                  onClick={() => onInvalidateKey(selectedProvider)}
                >
                  {pc.invalidateAction}
                </ActionButton>
              )}
            </span>
          </DetailRow>
          <DetailRow label={tx('ai.provider.field.region')}>{regionLabel(selectedProvider.data_region, tx)}</DetailRow>
          <DetailRow label={<span className="inline-flex items-center gap-1">{pc.allowlistLabel}<InfoTip label={pc.allowlistInfoLabel}>{pc.allowlistHelp}</InfoTip></span>}>
            {isLocalType(selectedProvider.provider_type) ? (
              <span className="text-xs text-fg-muted">{pc.allowlistLocal}</span>
            ) : endpointPatterns.length > 0 ? (
              <ul className="min-w-0 space-y-1" aria-label={pc.allowlistListAria}>
                {endpointPatterns.map((pattern) => (
                  <li key={pattern} className="break-all font-mono text-xs">{pattern}</li>
                ))}
              </ul>
            ) : (
              <span className="text-xs text-fg-muted">{pc.allowlistEmpty}</span>
            )}
          </DetailRow>
          <DetailRow label={tx('ai.provider.field.classification')}>
            <StatusBadge mono>{selectedProvider.allowed_data_classification || 'PUBLIC'}</StatusBadge>
          </DetailRow>
          <DetailRow label={tx('ai.provider.field.limits')}>
            {tx('ai.provider.detail.timeout', { seconds: selectedProvider.timeout, count: selectedProvider.max_retries })}
          </DetailRow>
          {tags.length > 0 && (
            <DetailRow label={tx('ai.provider.field.tags')}>
              {tags.map((tag) => <StatusBadge key={tag}>{tag}</StatusBadge>)}
            </DetailRow>
          )}
        </dl>

        <div className="border-t border-line px-5 py-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2 text-[13px]">
              <h4 className="text-sm font-semibold text-fg">{tx('ai.provider.section.connectivity')}</h4>
              <span className="text-fg-muted">{tx('ai.provider.status.health')}:</span>
              <HealthStatusBadge status={selectedProvider.health_status} tx={tx} />
              {selectedProvider.last_error_code && <StatusBadge tone="danger" mono>{selectedProvider.last_error_code}</StatusBadge>}
            </div>
            <ActionButton
              icon={selectedTesting ? RefreshCw : ShieldCheck}
              iconClassName={selectedTesting ? 'animate-spin motion-reduce:animate-none' : undefined}
              onClick={() => onTest(selectedProvider.id)}
              disabled={selectedTesting || selectedDeleting}
            >
              {selectedTesting ? tx('ai.provider.detail.testingShort') : tx('ai.provider.detail.test')}
            </ActionButton>
          </div>

          <div
            role="status"
            aria-live="polite"
            className={cn(
              'mt-3 flex items-start gap-2.5 rounded-lg px-3 py-2.5 text-[13px]',
              selectedTesting ? 'bg-surface-muted text-fg-muted'
                : selectedResult?.success ? 'bg-success-subtle'
                  : selectedResult ? 'bg-danger-subtle'
                    : 'bg-surface-muted',
            )}
          >
            {selectedTesting ? (
              <>
                <RefreshCw size={16} className="mt-0.5 shrink-0 animate-spin text-fg-muted motion-reduce:animate-none" aria-hidden="true" />
                <div><p className="font-medium text-fg">{tx('ai.provider.detail.testing')}</p><p className="mt-0.5 text-xs text-fg-muted">{tx('ai.provider.detail.testingBody')}</p></div>
              </>
            ) : selectedResult ? (
              <>
                {selectedResult.success
                  ? <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-success" aria-hidden="true" />
                  : <XCircle size={16} className="mt-0.5 shrink-0 text-danger" aria-hidden="true" />}
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className={cn('font-medium', selectedResult.success ? 'text-success' : 'text-danger')}>{getTestTitle(selectedResult, tx)}</p>
                    {typeof selectedResult.latency_ms === 'number' && <span className="text-xs tabular-nums text-fg-muted">{selectedResult.latency_ms} ms</span>}
                  </div>
                  <p className="mt-0.5 text-xs leading-5 text-fg-muted">{getTestDescription(selectedResult, tx)}</p>
                  {!selectedResult.success && selectedResult.error_code && <p className="mt-1 font-mono text-xs text-danger">{tx('ai.provider.detail.errorCode', { code: selectedResult.error_code })}</p>}
                  {selectedResult.success && selectedResult.sample_response && (
                    <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-fg-muted">
                      <span>{tx('ai.provider.detail.modelResponse')}</span>
                      <code className="max-w-full truncate rounded-md bg-surface px-1.5 py-0.5 font-mono text-fg">{selectedResult.sample_response}</code>
                    </p>
                  )}
                </div>
              </>
            ) : (
              <>
                <Clock3 size={16} className="mt-0.5 shrink-0 text-fg-subtle" aria-hidden="true" />
                <div><p className="font-medium text-fg">{tx('ai.provider.detail.notTested')}</p><p className="mt-0.5 text-xs text-fg-muted">{tx('ai.provider.detail.notTestedBody')}</p></div>
              </>
            )}
          </div>

          <p className="mt-2 text-xs leading-5 text-fg-subtle">
            {tx('ai.provider.probe.label')}
            <code className="rounded bg-surface-muted px-1.5 py-0.5 font-mono text-fg-muted">Reply with one short word: ok</code>
          </p>
        </div>
      </Panel>
    </div>
  );
};

export const ProviderManagementTab: React.FC = () => {
  const { language, showToast } = useCoreApp();
  const tx = (key: string, variables?: TextVariables) => aiAdminText(key, language, variables);
  const pc = getProviderPageCopy(language);
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
  const [pageSize, setPageSize] = useState(10);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<ProviderTestResult | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [selectedProviderId, setSelectedProviderId] = useState<string | null>(null);

  const [showModal, setShowModal] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  useEscapeClose(showModal, () => setShowModal(false));
  useFocusTrap(dialogRef, showModal, '#provider-name');
  const [editingId, setEditingId] = useState<string | null>(null);
  // Endpoint the edited Provider had when the editor opened. Changing its host
  // or type clears the stored key on the server, so a new key is required.
  const [originalEndpoint, setOriginalEndpoint] = useState<{ type: string; host: string } | null>(null);
  const [name, setName] = useState('');
  const [providerType, setProviderType] = useState(defaultProviderPreset.providerType);
  const [presetId, setPresetId] = useState(defaultProviderPreset.id);
  const [baseUrl, setBaseUrl] = useState(defaultProviderPreset.baseUrl ?? '');
  const [apiKey, setApiKey] = useState('');
  const [showApiKey, setShowApiKey] = useState(false);
  const [defaultModelCode, setDefaultModelCode] = useState(defaultProviderPreset.modelCode ?? '');
  const [timeout, setTimeout] = useState(30);
  const [maxRetries, setMaxRetries] = useState(2);
  const [proxyUrl, setProxyUrl] = useState('');
  const [tagsInput, setTagsInput] = useState('');
  const [dataRegion, setDataRegion] = useState('unknown');
  const [allowedDataClassification, setAllowedDataClassification] = useState('PUBLIC');
  const [noTrainingConfirmed, setNoTrainingConfirmed] = useState(false);
  const [retentionDays, setRetentionDays] = useState<string>('');
  const [dpaRef, setDpaRef] = useState('');
  // Egress allowlist, one pattern per line. Only sent on edit when changed:
  // an unchanged list must not block a Base URL change that the server would
  // otherwise extend the allowlist for.
  const [endpointPatternsInput, setEndpointPatternsInput] = useState('');
  const [originalEndpointPatterns, setOriginalEndpointPatterns] = useState<string[]>([]);
  // Server rejection of the allowlist (deployment ceiling), shown under the field.
  const [endpointPatternServerError, setEndpointPatternServerError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [keyHistoryProvider, setKeyHistoryProvider] = useState<AIProvider | null>(null);
  const [invalidateProvider, setInvalidateProvider] = useState<AIProvider | null>(null);

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
            last_health_check_at: new Date().toISOString(),
            last_success_at: result.success ? new Date().toISOString() : item.last_success_at,
            last_error_code: result.success ? null : (result.error_code || item.last_error_code),
          }
        : item));
      showToast(tx(result.success ? 'ai.provider.toast.testPassed' : 'ai.provider.toast.testFailed', { name: provider?.name || 'Provider' }), result.success ? 'success' : 'error');
    } catch (err: unknown) {
      const errorCode = err instanceof ApiError ? err.code : undefined;
      const messageKey = errorCode ? TEST_ERROR_KEYS[errorCode] : undefined;
      const result: ProviderTestResult = {
        id,
        success: false,
        message: messageKey ? tx(messageKey) : getErrorMessage(err, tx('ai.provider.error.test')),
        error_code: errorCode,
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
    setOriginalEndpoint({ type: provider.provider_type, host: endpointHostname(provider.base_url) });
    setName(provider.name);
    setProviderType(provider.provider_type);
    setPresetId(identifyProviderPreset(provider.provider_type, provider.base_url)?.id ?? provider.provider_type);
    setBaseUrl(provider.base_url || '');
    setApiKey('');
    setShowApiKey(false);
    setDefaultModelCode('');
    setTimeout(provider.timeout || 30);
    setMaxRetries(provider.max_retries ?? 2);
    setProxyUrl(provider.proxy_url || '');
    setTagsInput(Array.isArray(provider.tags) ? provider.tags.join(', ') : '');
    setDataRegion(provider.data_region || 'unknown');
    setAllowedDataClassification(provider.allowed_data_classification || 'PUBLIC');
    setNoTrainingConfirmed(Boolean(provider.no_training_confirmed));
    setRetentionDays(provider.retention_days != null ? String(provider.retention_days) : '');
    setDpaRef(provider.data_processing_agreement_ref || '');
    const patterns = Array.isArray(provider.approved_endpoint_patterns) ? provider.approved_endpoint_patterns : [];
    setOriginalEndpointPatterns(parseEndpointPatterns(patterns.join('\n')));
    setEndpointPatternsInput(patterns.join('\n'));
    setEndpointPatternServerError(null);
    setShowModal(true);
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    const badPatternLines = editingId && !isLocalType(providerType) ? invalidEndpointPatternLines(endpointPatternsInput) : [];
    if (badPatternLines.length > 0) {
      showToast(pc.allowlistInvalid(badPatternLines.join(', ')), 'error');
      return;
    }
    setSubmitting(true);
    try {
      const parsedTags = tagsInput
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean);
      const parsedRetention = retentionDays.trim() !== '' ? Number(retentionDays) : undefined;
      if (editingId) {
        // Review item L6-c: on edit every editable field is sent, so a field
        // the user emptied is cleared on the server.  The update API treats
        // `null`/missing as "unchanged", so emptied text fields are sent as
        // "" and emptied tags as [].  retention_days is an integer: an empty
        // value is sent as null, which the server currently ignores (keeps
        // the stored value) until update_provider honours an explicit null
        // via model_fields_set.
        const editFields: Record<string, unknown> = {
          max_retries: maxRetries,
          proxy_url: proxyUrl.trim(),
          tags: parsedTags,
          ...(allowedDataClassification !== 'PUBLIC'
            ? {
                no_training_confirmed: noTrainingConfirmed,
                retention_days: Number.isFinite(parsedRetention) ? parsedRetention : null,
                data_processing_agreement_ref: dpaRef.trim(),
              }
            : {}),
        };
        const nextPatterns = parseEndpointPatterns(endpointPatternsInput);
        if (!isLocalType(providerType) && !sameList(nextPatterns, originalEndpointPatterns)) {
          editFields.approved_endpoint_patterns = nextPatterns;
        }
        // One request: a new key in the edit form goes through the server's
        // versioned rotation path (same as rotate-key), so the edit and the
        // key change are applied atomically.  An empty field keeps the key.
        await updateAIProvider(editingId, {
          name,
          provider_type: providerType,
          base_url: baseUrl || undefined,
          api_key: apiKey.trim() || undefined,
          timeout,
          data_region: dataRegion,
          allowed_data_classification: allowedDataClassification,
          ...editFields,
        });
      } else {
        const createFields: Record<string, unknown> = {
          max_retries: maxRetries,
          ...(proxyUrl.trim() ? { proxy_url: proxyUrl.trim() } : {}),
          ...(parsedTags.length > 0 ? { tags: parsedTags } : {}),
          ...(allowedDataClassification !== 'PUBLIC'
            ? {
                ...(noTrainingConfirmed ? { no_training_confirmed: true } : {}),
                ...(Number.isFinite(parsedRetention) ? { retention_days: parsedRetention } : {}),
                ...(dpaRef.trim() ? { data_processing_agreement_ref: dpaRef.trim() } : {}),
              }
            : {}),
        };
        await createAIProvider({
          name,
          provider_type: providerType,
          base_url: baseUrl || undefined,
          api_key: apiKey || undefined,
          default_model_code: defaultModelCode || undefined,
          timeout,
          data_region: dataRegion,
          enabled: true,
          allowed_data_classification: allowedDataClassification,
          ...createFields,
        });
      }
      setShowModal(false);
      setEditingId(null);
      setApiKey('');
      setShowApiKey(false);
      await fetchProviders();
      showToast(tx(editingId ? 'ai.provider.toast.updated' : 'ai.provider.toast.added'), 'success');
    } catch (err: unknown) {
      const ceilingError = getAllowlistCeilingError(err, pc);
      if (ceilingError) {
        setEndpointPatternServerError(ceilingError);
        showToast(ceilingError, 'error');
      } else {
        showToast(getErrorMessage(err, tx('ai.provider.error.create')), 'error');
      }
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

  const healthyCount = providers.filter((provider) => String(provider.health_status || '').toLowerCase() === 'healthy').length;
  const hasActiveFilters = Boolean(appliedSearch || search || dataRegionFilter || healthFilter || enabledFilter !== 'all' || providerTypeFilter || tagFilter);
  const applyPreset = (id: string) => {
    const preset = getProviderPreset(id);
    if (!preset) return;
    setPresetId(id);
    setProviderType(preset.providerType);
    setBaseUrl(preset.baseUrl ?? '');
    setApiKey('');
    setShowApiKey(false);
    setDefaultModelCode(preset.modelCode ?? '');
    setDataRegion(preset.dataRegion ?? 'unknown');
  };

  const openCreate = () => {
    setEditingId(null);
    setOriginalEndpoint(null);
    applyPreset(defaultProviderPreset.id);
    setName('');
    setTimeout(30);
    setMaxRetries(2);
    setProxyUrl('');
    setTagsInput('');
    setAllowedDataClassification('PUBLIC');
    setNoTrainingConfirmed(false);
    setRetentionDays('');
    setDpaRef('');
    setEndpointPatternsInput('');
    setOriginalEndpointPatterns([]);
    setEndpointPatternServerError(null);
    setShowModal(true);
  };
  const closeEditor = () => { setEditingId(null); setOriginalEndpoint(null); setShowApiKey(false); setShowModal(false); };
  const isLocalProviderType = isLocalType(providerType);
  const selectedPreset = getProviderPreset(presetId);
  const endpointPatternErrors = editingId && !isLocalProviderType ? invalidEndpointPatternLines(endpointPatternsInput) : [];

  const handleKeyInvalidated = (updated: AIProvider) => {
    setInvalidateProvider(null);
    setProviders((current) => current.map((item) => item.id === updated.id ? updated : item));
    if (testResult?.id === updated.id) setTestResult(null);
    showToast(pc.invalidateDone(updated.name), 'success');
    void fetchProviders();
  };
  // Changing the host or type of an existing Provider clears its stored key on
  // the server, so the editor asks for a new key in that case.
  const endpointChanged = Boolean(
    editingId && originalEndpoint
    && (originalEndpoint.type !== providerType || originalEndpoint.host !== endpointHostname(baseUrl)),
  );
  const apiKeyRequired = !isLocalProviderType && (!editingId || endpointChanged);

  return (
    <div className="w-full space-y-4 pb-8">
      <PageHeader
        title={tx('ai.provider.page.title')}
        description={tx('ai.provider.page.description')}
        infoLabel={tx('ai.provider.page.infoLabel')}
        info={<>{tx('ai.provider.security.keys')}；{tx('ai.provider.security.gateway')}。</>}
        actions={(
          <>
            <ActionLink
              href="/downloads/nexora-ai-provider-debug-manual.md"
              download={tx('ai.provider.manual.filename')}
              aria-label={tx('ai.provider.manual.aria')}
              title={tx('ai.provider.manual.title')}
              icon={Download}
              size="md"
            >
              {tx('ai.provider.manual.short')}
            </ActionLink>
            <ActionButton
              type="button"
              icon={RefreshCw}
              iconClassName={loading ? 'animate-spin motion-reduce:animate-none' : undefined}
              size="md"
              onClick={() => void fetchProviders()}
            >
              {tx('ai.common.refresh')}
            </ActionButton>
            <ActionButton type="button" icon={Plus} variant="primary" size="md" onClick={openCreate}>
              {tx('ai.provider.action.add')}
            </ActionButton>
          </>
        )}
      />

      <SummaryBar
        label={tx('ai.provider.summary.aria')}
        items={[
          { key: 'total', value: total, label: tx('ai.provider.summary.total') },
          { key: 'enabled', value: activeCount, label: tx('ai.provider.summary.enabled'), tone: 'accent' },
          { key: 'healthy', value: healthyCount, label: tx('ai.provider.summary.healthy'), tone: 'success' },
          { key: 'keys', value: `${securedCount}/${providers.length}`, label: tx('ai.provider.summary.keys') },
        ]}
      />

      <form onSubmit={submitSearch} aria-label={tx('ai.provider.filter.aria')} className="flex flex-wrap items-center gap-2">
        <label className="relative flex min-w-[220px] max-w-sm flex-1 items-center">
          <Search size={15} className="pointer-events-none absolute left-3 text-fg-subtle" aria-hidden="true" />
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={tx('ai.provider.filter.search')}
            aria-label={tx('ai.provider.filter.searchLabel')}
            className={cn(filterControlClass, 'w-full pl-9')}
          />
        </label>
        <select value={dataRegionFilter} onChange={(event) => { setDataRegionFilter(event.target.value); setPage(1); }} aria-label={tx('ai.provider.filter.regionLabel')} className={filterControlClass}>
          <option value="">{tx('ai.provider.filter.allRegions')}</option>
          {Array.from(new Set([...DATA_REGION_OPTIONS.map((item) => item.value), ...providerFacets.data_regions])).map((region) => <option key={region} value={region}>{regionLabel(region, tx)}</option>)}
        </select>
        <select value={healthFilter} onChange={(event) => { setHealthFilter(event.target.value); setPage(1); }} aria-label={tx('ai.provider.filter.allHealth')} className={filterControlClass}>
          <option value="">{tx('ai.provider.filter.allHealth')}</option>
          {Array.from(new Set(['healthy', 'unhealthy', 'unknown', 'disabled', ...providerFacets.health_statuses])).map((health) => <option key={health} value={health}>{tx(getHealthStatusKey(health))}</option>)}
        </select>
        <select value={enabledFilter} onChange={(event) => { setEnabledFilter(event.target.value); setPage(1); }} aria-label={tx('ai.provider.filter.allEnabled')} className={filterControlClass}>
          <option value="all">{tx('ai.provider.filter.allEnabled')}</option>
          <option value="enabled">{tx('ai.provider.status.enabled')}</option>
          <option value="disabled">{tx('ai.provider.status.disabled')}</option>
        </select>
        {providerFacets.provider_types.length > 1 && (
          <select value={providerTypeFilter} onChange={(event) => { setProviderTypeFilter(event.target.value); setPage(1); }} aria-label={tx('ai.provider.filter.allTypes')} className={filterControlClass}>
            <option value="">{tx('ai.provider.filter.allTypes')}</option>
            {providerFacets.provider_types.map((type) => <option key={type} value={type}>{type}</option>)}
          </select>
        )}
        {providerFacets.tags.length > 0 && (
          <select value={tagFilter} onChange={(event) => { setTagFilter(event.target.value); setPage(1); }} aria-label={tx('ai.provider.filter.allTags')} className={filterControlClass}>
            <option value="">{tx('ai.provider.filter.allTags')}</option>
            {providerFacets.tags.map((tag) => <option key={tag} value={tag}>{tag}</option>)}
          </select>
        )}
        {hasActiveFilters && (
          <button type="button" onClick={clearProviderFilters} className="h-9 rounded-lg px-2 text-[13px] font-medium text-accent hover:bg-accent-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
            {tx('ai.common.clearFilters')}
          </button>
        )}
        <span className="ml-auto text-xs text-fg-subtle">{tx('ai.provider.filter.count', { count: total })}</span>
      </form>

      {error && (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-danger/30 bg-danger-subtle px-4 py-3 text-[13px] text-danger">
          <span className="flex items-start gap-2"><XCircle size={16} className="mt-0.5 shrink-0" aria-hidden="true" />{error}</span>
          <ActionButton type="button" variant="danger" onClick={() => void fetchProviders()}>{tx('ai.common.retry')}</ActionButton>
        </div>
      )}

      {loading ? (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(380px,1fr)]" aria-busy="true">
          {[0, 1].map((item) => (
            <div key={item} className="h-[320px] animate-pulse rounded-xl border border-line bg-surface p-5 motion-reduce:animate-none">
              <div className="h-5 w-1/3 rounded-md bg-surface-emphasis" />
              <div className="mt-5 space-y-3">
                <div className="h-4 rounded-md bg-surface-muted" />
                <div className="h-4 w-5/6 rounded-md bg-surface-muted" />
                <div className="h-4 w-2/3 rounded-md bg-surface-muted" />
              </div>
            </div>
          ))}
        </div>
      ) : providers.length === 0 ? (
        <EmptyState
          icon={Plug}
          title={tx('ai.provider.empty.title')}
          description={tx('ai.provider.empty.body')}
          action={<ActionButton type="button" icon={Plus} variant="primary" size="md" onClick={openCreate}>{tx('ai.provider.empty.action')}</ActionButton>}
        />
      ) : (
        <div className="space-y-3">
          <ProviderRegistryWorkspace
            providers={providers}
            selectedProviderId={selectedProviderId}
            onSelect={setSelectedProviderId}
            onEdit={openEdit}
            onToggle={(provider) => void handleToggle(provider)}
            onDelete={(id) => void handleDelete(id)}
            onTest={(id) => void handleTest(id)}
            onShowKeyHistory={setKeyHistoryProvider}
            onInvalidateKey={setInvalidateProvider}
            testingId={testingId}
            deletingId={deletingId}
            testResult={testResult}
            tx={tx}
            pc={pc}
          />
          {total > pageSize && (
            <Pagination currentPage={page} totalItems={total} itemsPerPage={pageSize} onPageChange={setPage} onItemsPerPageChange={(size) => { setPageSize(size); setPage(1); }} language={language} alwaysVisible />
          )}
        </div>
      )}

      {keyHistoryProvider && (
        <ProviderKeyHistoryDrawer
          provider={keyHistoryProvider}
          copy={pc}
          language={language}
          onClose={() => setKeyHistoryProvider(null)}
        />
      )}

      {invalidateProvider && (
        <ProviderKeyInvalidateDialog
          provider={invalidateProvider}
          copy={pc}
          onClose={() => setInvalidateProvider(null)}
          onInvalidated={handleKeyInvalidated}
          onError={(message) => showToast(message, 'error')}
        />
      )}

      {showModal && (
        <div ref={dialogRef} className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4" role="dialog" aria-modal="true" aria-labelledby="add-provider-title" tabIndex={-1}>
          <div className="nx-form-dialog-surface flex max-h-[calc(100vh-2rem)] w-full max-w-xl flex-col overflow-hidden">
            <div className="nx-dialog-header flex items-start justify-between gap-4 border-b px-6 py-4">
              <div>
                <h3 id="add-provider-title" className="text-base font-semibold text-fg">{tx(editingId ? 'ai.provider.editor.editTitle' : 'ai.provider.editor.newTitle')}</h3>
                <p className="mt-0.5 text-[13px] text-fg-muted">{tx('ai.provider.editor.body')}</p>
              </div>
              <button type="button" onClick={closeEditor} aria-label={tx('ai.provider.editor.close')} className="shrink-0 text-fg-subtle transition-colors hover:bg-surface-muted hover:text-fg">
                <X size={18} aria-hidden="true" />
              </button>
            </div>

            <form onSubmit={handleCreate} className="flex min-h-0 flex-1 flex-col">
              <div className="space-y-4 overflow-y-auto px-6 py-5">
                <div className="grid gap-4 sm:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
                  <div>
                    <label htmlFor="provider-name" className={fieldLabelClass}>{tx('ai.provider.editor.name')}</label>
                    <input id="provider-name" type="text" required placeholder={tx('ai.provider.editor.namePlaceholder')} value={name} onChange={(e) => setName(e.target.value)} className={fieldInputClass} />
                  </div>
                  <div>
                    <label htmlFor="provider-type" className={fieldLabelClass}>{tx('ai.provider.editor.type')}</label>
                    <select id="provider-type" value={presetId} onChange={(event) => applyPreset(event.target.value)} className={fieldInputClass}>
                      {!selectedPreset && <option value={presetId}>{presetId}</option>}
                      {providerPresetGroups.map((group) => (
                        <optgroup key={group.labelKey} label={tx(group.labelKey)}>
                          {group.presets.map((preset) => <option key={preset.id} value={preset.id}>{tx(preset.label)}</option>)}
                        </optgroup>
                      ))}
                    </select>
                  </div>
                </div>

                <div>
                  <label htmlFor="provider-base-url" className={fieldLabelClass}>Base URL</label>
                  <input id="provider-base-url" type="url" required={!editingId && !isLocalProviderType} placeholder={selectedPreset?.exampleUrl || selectedPreset?.baseUrl} aria-describedby={selectedPreset?.helpKey ? 'provider-preset-help' : undefined} value={baseUrl} onChange={(event) => {
                    const nextUrl = event.target.value;
                    if (baseUrl === selectedPreset?.baseUrl && nextUrl !== baseUrl && dataRegion === selectedPreset?.dataRegion) {
                      setDataRegion('unknown');
                    }
                    setBaseUrl(nextUrl);
                  }} className={cn(fieldInputClass, 'font-mono')} />
                  {selectedPreset?.helpKey && <p id="provider-preset-help" className={fieldHelpClass}>{tx(selectedPreset.helpKey)}</p>}
                </div>

                {editingId && !isLocalProviderType && (
                  <div>
                    <div className="mb-1.5 flex items-center gap-1">
                      <label htmlFor="provider-endpoint-patterns" className="block text-[13px] font-medium text-fg">{pc.allowlistLabel}</label>
                      <InfoTip label={pc.allowlistInfoLabel}>{pc.allowlistHelp}</InfoTip>
                    </div>
                    <textarea
                      id="provider-endpoint-patterns"
                      rows={3}
                      spellCheck={false}
                      placeholder="https://api.deepseek.com"
                      value={endpointPatternsInput}
                      onChange={(e) => { setEndpointPatternsInput(e.target.value); setEndpointPatternServerError(null); }}
                      aria-invalid={endpointPatternErrors.length > 0 || Boolean(endpointPatternServerError)}
                      aria-describedby="provider-endpoint-patterns-help"
                      className={cn(fieldInputClass, 'font-mono')}
                    />
                    <p id="provider-endpoint-patterns-help" className={cn(fieldHelpClass, (endpointPatternErrors.length > 0 || endpointPatternServerError) && 'text-danger')}>
                      {endpointPatternErrors.length > 0
                        ? pc.allowlistInvalid(endpointPatternErrors.join(', '))
                        : (endpointPatternServerError || pc.allowlistFieldHelp)}
                    </p>
                  </div>
                )}

                <div>
                  <div className="mb-1.5 flex items-center justify-between gap-3">
                    <label htmlFor="provider-api-key" className="block text-[13px] font-medium text-fg">API Key</label>
                    <span className="inline-flex items-center gap-1 text-xs text-fg-muted"><LockKeyhole size={12} aria-hidden="true" />AES-256-GCM</span>
                  </div>
                  <PasswordInputField
                    id="provider-api-key"
                    autoComplete="new-password"
                    required={apiKeyRequired}
                    visible={showApiKey}
                    onVisibilityChange={setShowApiKey}
                    showPasswordLabel={tx('ai.provider.editor.keyVisibility.show')}
                    hidePasswordLabel={tx('ai.provider.editor.keyVisibility.hide')}
                    placeholder={editingId ? (endpointChanged && !isLocalProviderType ? tx('ai.provider.editor.keyRequiredOnEndpointChange') : tx('ai.provider.editor.keyOptionalOnEdit')) : isLocalProviderType ? tx('ai.provider.editor.apiKeyOptional') : 'sk-...'}
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    className="rounded-lg font-mono text-sm text-fg placeholder:text-fg-subtle"
                  />
                  {endpointChanged && !isLocalProviderType && (
                    <p className="mt-1.5 text-xs leading-5 text-warning" role="note">{tx('ai.provider.editor.endpointChangedHelp')}</p>
                  )}
                </div>

                <div className={`grid gap-4 ${editingId ? 'sm:grid-cols-2' : 'sm:grid-cols-[1fr_120px_110px]'}`}>
                  {!editingId && (
                    <div>
                      <label htmlFor="provider-model-code" className={fieldLabelClass}>{tx('ai.provider.editor.model')}</label>
                      <input id="provider-model-code" type="text" placeholder={tx('ai.provider.preset.modelPlaceholder')} value={defaultModelCode} onChange={(e) => setDefaultModelCode(e.target.value)} className={cn(fieldInputClass, 'font-mono')} />
                      <p className={fieldHelpClass}>{tx('ai.provider.editor.modelHelp')}</p>
                    </div>
                  )}
                  <div>
                    <label htmlFor="provider-timeout" className={fieldLabelClass}>{tx('ai.provider.editor.timeout')}</label>
                    <input id="provider-timeout" type="number" min={5} max={300} value={timeout} onChange={(e) => setTimeout(Number(e.target.value) || 30)} className={fieldInputClass} />
                  </div>
                  <div>
                    <label htmlFor="provider-max-retries" className={fieldLabelClass}>{language === 'zh' ? '最大重试' : 'Max Retries'}</label>
                    <input id="provider-max-retries" type="number" min={0} max={5} value={maxRetries} onChange={(e) => setMaxRetries(Math.max(0, Math.min(5, Number(e.target.value) || 0)))} className={fieldInputClass} />
                  </div>
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <label htmlFor="provider-data-region" className={fieldLabelClass}>{tx('ai.provider.editor.region')}</label>
                    <select id="provider-data-region" value={dataRegion} onChange={(e) => setDataRegion(e.target.value)} className={fieldInputClass}>
                      {DATA_REGION_OPTIONS.map((option) => <option key={option.value} value={option.value}>{tx(option.labelKey)}</option>)}
                    </select>
                    <p className={fieldHelpClass}>{tx('ai.provider.editor.regionBody')}</p>
                  </div>
                  <div>
                    <label htmlFor="provider-allowed-data-classification" className={fieldLabelClass}>{tx('ai.provider.editor.classification')}</label>
                    <select id="provider-allowed-data-classification" value={allowedDataClassification} onChange={(e) => setAllowedDataClassification(e.target.value)} className={fieldInputClass}>
                      <option value="PUBLIC">PUBLIC · {tx('ai.provider.editor.public')}</option>
                      <option value="INTERNAL">INTERNAL · {tx('ai.provider.editor.internal')}</option>
                      <option value="CONFIDENTIAL">CONFIDENTIAL · {tx('ai.provider.editor.confidential')}</option>
                    </select>
                    <p className={fieldHelpClass}>{tx('ai.provider.editor.classificationHelp')}</p>
                  </div>
                </div>

                {allowedDataClassification !== 'PUBLIC' && (
                  <fieldset className="space-y-3 rounded-lg border border-line border-l-[3px] border-l-warning bg-surface px-4 py-3">
                    <legend className="px-1 text-[13px] font-medium text-fg">{tx('ai.provider.editor.compliance')}</legend>
                    <label className="flex items-center gap-2 text-[13px] text-fg">
                      <input type="checkbox" checked={noTrainingConfirmed} onChange={(e) => setNoTrainingConfirmed(e.target.checked)} className="h-4 w-4 rounded border-line-strong accent-[var(--ui-accent)]" />
                      {language === 'zh' ? '已确认供应商承诺不将 API 数据用于模型训练 (Zero-Training)' : 'Confirmed provider does not train on API data'}
                    </label>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div>
                        <label htmlFor="provider-retention-days" className={fieldLabelClass}>{language === 'zh' ? '数据留存天数 (天)' : 'Data Retention (days)'}</label>
                        <input id="provider-retention-days" type="number" min={0} max={365} placeholder="0" value={retentionDays} onChange={(e) => setRetentionDays(e.target.value)} className={fieldInputClass} />
                      </div>
                      <div>
                        <label htmlFor="provider-dpa-ref" className={fieldLabelClass}>{language === 'zh' ? 'DPA 协议编号/链接' : 'DPA Reference'}</label>
                        <input id="provider-dpa-ref" type="text" placeholder="DPA-2026-001" value={dpaRef} onChange={(e) => setDpaRef(e.target.value)} className={fieldInputClass} />
                      </div>
                    </div>
                  </fieldset>
                )}

                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <label htmlFor="provider-proxy-url" className={fieldLabelClass}>{language === 'zh' ? '代理地址 (可选)' : 'Proxy URL (Optional)'}</label>
                    <input id="provider-proxy-url" type="url" placeholder="http://proxy.internal:8080" value={proxyUrl} onChange={(e) => setProxyUrl(e.target.value)} className={cn(fieldInputClass, 'font-mono')} />
                  </div>
                  <div>
                    <label htmlFor="provider-tags" className={fieldLabelClass}>{language === 'zh' ? '标签 (逗号分隔)' : 'Tags (comma-separated)'}</label>
                    <input id="provider-tags" type="text" placeholder="prod, cn-region" value={tagsInput} onChange={(e) => setTagsInput(e.target.value)} className={fieldInputClass} />
                  </div>
                </div>
                {editingId && <p className="-mt-2 text-xs leading-5 text-fg-muted">{pc.clearHint}</p>}
              </div>

              <div className="nx-dialog-footer flex flex-col-reverse gap-2 border-t px-6 py-4 sm:flex-row sm:justify-end">
                <button type="button" onClick={closeEditor} className="nx-dialog-action-secondary px-4 py-2">{tx('ai.provider.editor.cancel')}</button>
                <button type="submit" disabled={submitting} className="nx-dialog-action-primary inline-flex items-center justify-center gap-2 px-4 py-2 disabled:cursor-wait disabled:opacity-60">
                  {submitting && <RefreshCw size={16} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />}
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
