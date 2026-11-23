import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronDown,
  Clock3,
  ExternalLink,
  RefreshCw,
  Server,
  ShieldAlert,
  XCircle,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { AIModelHealthService, AIModelHealthSummary, checkAIModelHealth, getAIModelHealthSummary } from '../../../api/ai';
import { useCoreApp } from '../../../contexts/AppDomainContext';
import { aiAdminText } from '../../../i18n/aiAdmin';
import { EmptyState } from '../../../components/ui/EmptyState';
import { PageHeader } from '../../../components/ui/PageHeader';
import { Panel, PanelHeader } from '../../../components/ui/Panel';
import { StatusBadge, type StatusTone } from '../../../components/ui/StatusBadge';
import { SummaryBar } from '../../../components/ui/SummaryBar';
import { healthPageCopy } from './ModelHealthDashboardTab.copy';

type Translate = (key: string, variables?: Record<string, string | number>) => string;
type StatusKind = 'healthy' | 'degraded' | 'unhealthy' | 'unknown' | 'disabled' | 'not_supported';
type WindowDays = 30 | 90;

const normalizeStatus = (status?: string): StatusKind => {
  const value = String(status || 'unknown').toLowerCase();
  if (value === 'healthy' || value === 'degraded' || value === 'unhealthy' || value === 'disabled' || value === 'not_supported') return value;
  return 'unknown';
};

const statusMeta = (status: string | undefined, tx: Translate) => {
  const normalized = normalizeStatus(status);
  if (normalized === 'healthy') {
    return { label: tx('ai.health.status.healthy'), shortLabel: tx('ai.health.status.healthyShort'), tone: 'success' as StatusTone, bar: 'bg-success', icon: Check };
  }
  if (normalized === 'degraded') {
    return { label: tx('ai.health.status.degraded'), shortLabel: tx('ai.health.status.degradedShort'), tone: 'warning' as StatusTone, bar: 'bg-warning', icon: AlertTriangle };
  }
  if (normalized === 'unhealthy') {
    return { label: tx('ai.health.status.unhealthy'), shortLabel: tx('ai.health.status.unhealthyShort'), tone: 'danger' as StatusTone, bar: 'bg-danger', icon: XCircle };
  }
  if (normalized === 'disabled' || normalized === 'not_supported') {
    return {
      label: tx(normalized === 'disabled' ? 'ai.model.health.disabled' : 'ai.model.health.notSupported'),
      shortLabel: tx('ai.health.status.noData'),
      tone: 'neutral' as StatusTone,
      bar: 'bg-fg-subtle/40',
      icon: ShieldAlert,
    };
  }
  return { label: tx('ai.health.status.noData'), shortLabel: tx('ai.health.status.noData'), tone: 'neutral' as StatusTone, bar: 'bg-surface-emphasis', icon: Clock3 };
};

const toneIconClass: Record<StatusTone, string> = {
  neutral: 'bg-surface-emphasis text-fg-muted',
  accent: 'bg-accent-subtle text-accent',
  success: 'bg-success-subtle text-success',
  warning: 'bg-warning-subtle text-warning',
  danger: 'bg-danger-subtle text-danger',
};

const formatDate = (value: string | null | undefined, language: 'zh' | 'en', tx: Translate) => {
  // The "never probed" label lives in the page copy: the aiAdmin key used
  // here before did not exist, so the raw key string was shown.
  if (!value) return healthPageCopy[language].never;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return healthPageCopy[language].never;
  return date.toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
};

const formatMonthRange = (start: string | undefined, end: string | undefined, language: 'zh' | 'en') => {
  if (!start || !end) return '—';
  const startDate = new Date(start);
  const endDate = new Date(end);
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) return '—';
  if (language === 'zh') {
    return `${startDate.getFullYear()}年${String(startDate.getMonth() + 1).padStart(2, '0')}月 - ${endDate.getFullYear()}年${String(endDate.getMonth() + 1).padStart(2, '0')}月`;
  }
  return `${startDate.toLocaleString('en-US', { month: 'short', year: 'numeric' })} - ${endDate.toLocaleString('en-US', { month: 'short', year: 'numeric' })}`;
};

const formatLatency = (value: number | null | undefined, tx: Translate) => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return tx('ai.common.na');
  return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${Math.round(value)} ms`;
};

const StatusIcon: React.FC<{ status: string; tx: Translate }> = ({ status, tx }) => {
  const meta = statusMeta(status, tx);
  const Icon = meta.icon;
  return <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${toneIconClass[meta.tone]}`}><Icon className="h-3.5 w-3.5" aria-hidden="true" /></span>;
};

const StatusBars: React.FC<{ service: AIModelHealthService; windowDays: WindowDays; tx: Translate }> = ({ service, windowDays, tx }) => {
  const timeline = service.timeline || [];
  const uptime = service.window_availability_percent == null ? tx('ai.health.status.noData') : `${service.window_availability_percent.toFixed(2)}% ${tx('ai.health.status.uptimeSuffix')}`;
  return (
    <div className="mt-3 overflow-x-auto pb-1">
      <div className="flex min-w-[720px] gap-[2px]" aria-label={tx('ai.health.status.timelineAria', { name: service.model_name })}>
        {timeline.map((point) => {
          const meta = statusMeta(point.status, tx);
          const title = point.check_count > 0
            ? `${point.bucket_date} · ${meta.label} · ${point.success_count}/${point.check_count} · ${point.availability_percent?.toFixed(2)}%`
            : `${point.bucket_date} · ${meta.label}`;
          return <span key={point.bucket_date} title={title} aria-label={title} className={`h-6 min-w-[3px] flex-1 rounded-[2px] transition-opacity hover:opacity-70 ${meta.bar}`} />;
        })}
      </div>
      <div className="mt-2 flex min-w-[720px] items-center justify-between text-xs text-fg-muted">
        <span>{tx('ai.health.status.daysAgo', { days: windowDays })}</span>
        <span className="flex items-center gap-3"><span className="hidden h-px w-24 bg-line sm:block" /><strong className="font-semibold tabular-nums text-fg">{uptime}</strong><span className="hidden h-px w-24 bg-line sm:block" /></span>
        <span>{tx('ai.health.status.today')}</span>
      </div>
    </div>
  );
};

const DetailStat: React.FC<{ label: string; value: React.ReactNode; tone?: 'success' | 'danger' }> = ({ label, value, tone }) => (
  <div>
    <p className="text-xs text-fg-muted">{label}</p>
    <p className={`mt-1 text-sm font-semibold tabular-nums ${tone === 'success' ? 'text-success' : tone === 'danger' ? 'text-danger' : 'text-fg'}`}>{value}</p>
  </div>
);

const ServiceStatusRow: React.FC<{
  service: AIModelHealthService;
  windowDays: WindowDays;
  expanded: boolean;
  onToggle: () => void;
  onCheck: () => void;
  checking: boolean;
  tx: Translate;
  language: 'zh' | 'en';
}> = ({ service, windowDays, expanded, onToggle, onCheck, checking, tx, language }) => {
  const meta = statusMeta(service.health_status, tx);
  const canCheck = service.enabled && ['chat', 'reasoning'].includes(service.model_type.toLowerCase());
  return (
    <article className="border-b border-line last:border-b-0">
      <div className="px-4 py-4 sm:px-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-center gap-3">
            <StatusIcon status={service.health_status} tx={tx} />
            <div className="min-w-0">
              <h3 className="truncate text-[15px] font-semibold text-fg" title={service.model_name}>{service.model_name}</h3>
              <p className="mt-0.5 truncate font-mono text-xs text-fg-muted" title={`${service.provider_name} · ${service.model_code}`}>{service.provider_name} · {service.model_code}</p>
            </div>
          </div>
          <div className="flex items-center gap-2 self-start sm:self-center">
            <StatusBadge tone={meta.tone} dot>{meta.shortLabel}</StatusBadge>
            <span className="text-xs tabular-nums text-fg-muted">{tx('ai.health.status.probes', { count: service.window_check_count })}</span>
            <button type="button" onClick={onToggle} aria-expanded={expanded} aria-label={tx('ai.health.status.toggleDetails', { name: service.model_name })} className="rounded-md p-1 text-fg-subtle transition hover:bg-accent-subtle hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"><ChevronDown className={`h-4 w-4 transition-transform ${expanded ? 'rotate-180' : ''}`} aria-hidden="true" /></button>
          </div>
        </div>

        <StatusBars service={service} windowDays={windowDays} tx={tx} />
        <div className="mt-2 flex flex-col gap-2 text-xs text-fg-muted sm:flex-row sm:items-center sm:justify-between">
          <span>{meta.label}</span>
          <button type="button" onClick={onCheck} disabled={!canCheck || checking} className="inline-flex items-center gap-1.5 self-start rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs font-medium text-fg transition hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-50 sm:self-auto"><RefreshCw className={`h-3 w-3 ${checking ? 'animate-spin' : ''}`} aria-hidden="true" />{checking ? tx('ai.model.health.checking') : tx('ai.health.checkNow')}</button>
        </div>
      </div>
      {expanded && (
        <div className="border-t border-line bg-surface-muted px-4 py-4 sm:px-5">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <DetailStat label={tx('ai.health.detail.checks')} value={service.window_check_count} />
            <DetailStat label={tx('ai.health.detail.success')} value={service.window_success_count} tone="success" />
            <DetailStat label={tx('ai.health.detail.failures')} value={service.window_failure_count} tone="danger" />
            <DetailStat label={tx('ai.health.detail.lastProbe')} value={formatDate(service.last_health_check_at, language, tx)} />
          </div>
          <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-fg-muted">
            <span>{tx('ai.health.detail.latency')}: {formatLatency(service.window_avg_latency_ms, tx)}</span>
            <span>{tx('ai.health.detail.type')}: {service.model_type}</span>
            <span>{tx('ai.health.detail.window')}: {windowDays} {tx('ai.health.status.days')}</span>
          </div>
        </div>
      )}
    </article>
  );
};

export const ModelHealthDashboardTab: React.FC = () => {
  const { language, showToast } = useCoreApp();
  const navigate = useNavigate();
  const tx: Translate = (key, variables = {}) => aiAdminText(key, language, variables);
  const [windowDays, setWindowDays] = useState<WindowDays>(90);
  const [summary, setSummary] = useState<AIModelHealthSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [expandedServices, setExpandedServices] = useState<Set<string>>(new Set());
  const [checkingModelId, setCheckingModelId] = useState<string | null>(null);

  const fetchData = useCallback(async (silent = false) => {
    if (silent) setRefreshing(true);
    else setLoading(true);
    setError('');
    try {
      setSummary(await getAIModelHealthSummary(windowDays));
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : tx('ai.health.error.load');
      setError(message);
      if (!silent) showToast(message, 'error');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [language, showToast, windowDays]);

  useEffect(() => {
    void fetchData();
    const timer = window.setInterval(() => void fetchData(true), 60_000);
    return () => window.clearInterval(timer);
  }, [fetchData]);

  const handleCheck = async (service: AIModelHealthService) => {
    setCheckingModelId(service.model_id);
    try {
      const result = await checkAIModelHealth(service.model_id);
      if (result.success) {
        showToast(tx('ai.model.health.toast.success', { name: service.model_name, latency: result.latency_ms }), 'success');
      } else if (result.error_code === 'AI_HEALTH_BACKOFF') {
        showToast(healthPageCopy[language === 'zh' ? 'zh' : 'en'].backoff(service.model_name), 'info');
      } else {
        showToast(tx('ai.model.health.toast.failure', { name: service.model_name, code: result.error_code || 'unknown' }), 'error');
      }
      await fetchData(true);
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : tx('ai.model.health.toast.error'), 'error');
    } finally {
      setCheckingModelId(null);
    }
  };

  const latestDate = summary?.generated_at;
  const rangeLabel = formatMonthRange(summary?.window_start, latestDate, language);
  const overallStatus = normalizeStatus(summary?.overall_status);
  const overallTone: StatusTone = !summary ? 'neutral' : overallStatus === 'healthy' ? 'success' : overallStatus === 'unknown' ? 'neutral' : 'danger';
  const OverallIcon = overallStatus === 'healthy' ? CheckCircle2 : overallStatus === 'unknown' ? Clock3 : AlertTriangle;
  const services = useMemo(() => summary?.services || [], [summary]);
  const copy = healthPageCopy[language === 'zh' ? 'zh' : 'en'];
  const overallTitle = overallStatus === 'healthy' ? tx('ai.health.status.operational') : overallStatus === 'unknown' ? tx('ai.health.status.awaitingData') : tx('ai.health.status.attention');
  const overallBody = overallStatus === 'healthy' ? tx('ai.health.status.operationalBody') : overallStatus === 'unknown' ? tx('ai.health.status.awaitingDataBody') : tx('ai.health.status.attentionBody');
  const bannerClass = overallTone === 'success' ? 'border-success/40 bg-success-subtle' : overallTone === 'danger' ? 'border-danger/40 bg-danger-subtle' : 'border-line bg-surface-muted';
  const availability = summary?.availability_percent;
  const summaryItems = summary ? [
    { key: 'services', value: summary.service_count, label: copy.services, tone: overallTone },
    { key: 'availability', value: typeof availability === 'number' && Number.isFinite(availability) ? `${availability.toFixed(2)}%` : tx('ai.common.na'), label: copy.availability },
    { key: 'latency', value: formatLatency(summary.avg_latency_ms, tx), label: copy.avgLatency },
    { key: 'checks', value: summary.total_check_count, label: copy.checks },
    { key: 'failures', value: summary.total_failure_count, label: copy.failures, tone: (summary.total_failure_count > 0 ? 'danger' : 'success') as StatusTone },
  ] : [];

  return (
    <div className="min-h-full pb-10" data-testid="ai-health-page">
      <div className="mx-auto w-full max-w-[1680px] space-y-4 px-1 sm:px-2">
        <PageHeader
          className="pt-1 sm:pt-2"
          title={tx('ai.health.status.currentTitle')}
          description={`${copy.description} ${tx('ai.health.status.updatedAt', { value: latestDate ? formatDate(latestDate, language, tx) : copy.never })}`}
          info={copy.info}
          infoLabel={copy.infoLabel}
          actions={(
            <>
              <button type="button" onClick={() => navigate('/ai/models')} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-line bg-surface px-3 text-sm font-medium text-fg transition hover:border-accent hover:text-accent">{tx('ai.health.manageModels')}<ExternalLink className="h-3.5 w-3.5" aria-hidden="true" /></button>
              <button type="button" onClick={() => void fetchData()} disabled={loading || refreshing} aria-label={tx('ai.common.refresh')} className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-line bg-surface text-fg-muted transition hover:border-accent hover:text-accent disabled:cursor-wait disabled:opacity-50"><RefreshCw className={`h-4 w-4 ${loading || refreshing ? 'animate-spin' : ''}`} aria-hidden="true" /></button>
            </>
          )}
        />

        {error && <div role="alert" className="rounded-lg border border-danger/40 bg-danger-subtle px-4 py-3 text-sm text-danger">{error}</div>}

        <section data-testid="ai-health-overall" className={`flex flex-col gap-2 rounded-xl border px-4 py-3 sm:flex-row sm:items-center sm:justify-between ${bannerClass}`}>
          <div className="flex min-w-0 items-start gap-3">
            <span className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${toneIconClass[overallTone]}`}><OverallIcon className="h-4 w-4" aria-hidden="true" /></span>
            <div className="min-w-0">
              <p className="text-[15px] font-semibold text-fg">{overallTitle}</p>
              <p className="mt-0.5 text-[13px] text-fg-muted">{overallBody}</p>
            </div>
          </div>
        </section>

        {summaryItems.length > 0 && <SummaryBar label={copy.summaryLabel} items={summaryItems} />}

        <Panel>
          <PanelHeader
            title={tx('ai.health.status.systemStatus')}
            description={summary ? `${summary.service_count} ${tx('ai.health.status.services')} · ${rangeLabel}` : '—'}
            actions={(
              <div className="flex rounded-lg border border-line p-0.5" role="group" aria-label={tx('ai.health.detail.window')}>
                {([30, 90] as WindowDays[]).map((days) => (
                  <button key={days} type="button" aria-pressed={windowDays === days} onClick={() => setWindowDays(days)} className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${windowDays === days ? 'bg-accent text-white' : 'text-fg-muted hover:bg-accent-subtle hover:text-fg'}`}>{days}{tx('ai.health.status.daysShort')}</button>
                ))}
              </div>
            )}
          />
          {loading && !summary ? (
            <div className="space-y-4 px-4 py-6 sm:px-5">{[0, 1, 2, 3].map((item) => <div key={item} className="h-24 animate-pulse rounded-lg bg-surface-muted" />)}</div>
          ) : services.length === 0 ? (
            <div className="p-4"><EmptyState icon={Server} title={tx('ai.health.status.noServices')} description={copy.emptyDescription} /></div>
          ) : (
            <div>
              {services.map((service) => (
                <ServiceStatusRow
                  key={service.model_id}
                  service={service}
                  windowDays={windowDays}
                  expanded={expandedServices.has(service.model_id)}
                  onToggle={() => setExpandedServices((current) => { const next = new Set(current); if (next.has(service.model_id)) next.delete(service.model_id); else next.add(service.model_id); return next; })}
                  onCheck={() => void handleCheck(service)}
                  checking={checkingModelId === service.model_id}
                  tx={tx}
                  language={language}
                />
              ))}
            </div>
          )}
          <div className="flex flex-col gap-2 border-t border-line px-4 py-3 text-xs text-fg-muted sm:flex-row sm:items-center sm:justify-between sm:px-5">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-success" />{tx('ai.health.status.legendHealthy')}</span>
              <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-warning" />{tx('ai.health.status.legendDegraded')}</span>
              <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-danger" />{tx('ai.health.status.legendUnhealthy')}</span>
              <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-surface-emphasis" />{tx('ai.health.status.legendUnknown')}</span>
            </div>
            <span>{summary ? tx('ai.health.status.summary', { checks: summary.total_check_count, success: summary.total_success_count, failure: summary.total_failure_count }) : '—'}</span>
          </div>
        </Panel>
      </div>
    </div>
  );
};

export default ModelHealthDashboardTab;
