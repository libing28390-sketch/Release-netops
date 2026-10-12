import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
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
    return {
      label: tx('ai.health.status.healthy'),
      shortLabel: tx('ai.health.status.healthyShort'),
      bar: 'bg-[#21c38e]',
      soft: 'bg-[#d8f7ec] text-[#11966a] border-[#9ce9cb]',
      icon: Check,
    };
  }
  if (normalized === 'degraded') {
    return {
      label: tx('ai.health.status.degraded'),
      shortLabel: tx('ai.health.status.degradedShort'),
      bar: 'bg-[#f4b53f]',
      soft: 'bg-[#fff4d7] text-[#a86f00] border-[#f4d278]',
      icon: AlertTriangle,
    };
  }
  if (normalized === 'unhealthy') {
    return {
      label: tx('ai.health.status.unhealthy'),
      shortLabel: tx('ai.health.status.unhealthyShort'),
      bar: 'bg-[#ec5965]',
      soft: 'bg-[#ffe3e5] text-[#c83747] border-[#f3adb4]',
      icon: XCircle,
    };
  }
  if (normalized === 'disabled' || normalized === 'not_supported') {
    return {
      label: tx(normalized === 'disabled' ? 'ai.model.health.disabled' : 'ai.model.health.notSupported'),
      shortLabel: tx('ai.health.status.noData'),
      bar: 'bg-slate-300',
      soft: 'bg-slate-100 text-slate-500 border-slate-200',
      icon: ShieldAlert,
    };
  }
  return {
    label: tx('ai.health.status.noData'),
    shortLabel: tx('ai.health.status.noData'),
    bar: 'bg-slate-200',
    soft: 'bg-slate-100 text-slate-500 border-slate-200',
    icon: Clock3,
  };
};

const formatDate = (value: string | null | undefined, language: 'zh' | 'en', tx: Translate) => {
  if (!value) return tx('ai.health.never');
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return tx('ai.health.never');
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
  return <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border ${meta.soft}`}><Icon className="h-3.5 w-3.5" /></span>;
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
      <div className="mt-2 flex min-w-[720px] items-center justify-between text-xs text-slate-500 dark:text-slate-400">
        <span>{tx('ai.health.status.daysAgo', { days: windowDays })}</span>
        <span className="flex items-center gap-3"><span className="hidden h-px w-24 bg-slate-300 sm:block dark:bg-slate-700" /><strong className="font-semibold text-slate-600 dark:text-slate-300">{uptime}</strong><span className="hidden h-px w-24 bg-slate-300 sm:block dark:bg-slate-700" /></span>
        <span>{tx('ai.health.status.today')}</span>
      </div>
    </div>
  );
};

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
    <article className="border-b border-slate-200 last:border-b-0 dark:border-slate-800">
      <div className="px-5 py-5 sm:px-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-center gap-3">
            <StatusIcon status={service.health_status} tx={tx} />
            <div className="min-w-0">
              <h3 className="truncate text-[17px] font-semibold text-slate-900 dark:text-white">{service.model_name}</h3>
              <p className="mt-0.5 truncate font-mono text-[11px] text-slate-500 dark:text-slate-400">{service.provider_name} · {service.model_code}</p>
            </div>
          </div>
          <div className="flex items-center gap-2 self-start sm:self-center">
            <span className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold ${meta.soft}`}>{meta.shortLabel}</span>
            <span className="text-xs text-slate-400">{tx('ai.health.status.probes', { count: service.window_check_count })}</span>
            <button type="button" onClick={onToggle} aria-label={tx('ai.health.status.toggleDetails', { name: service.model_name })} className="rounded-md p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"><ChevronDown className={`h-4 w-4 transition-transform ${expanded ? 'rotate-180' : ''}`} /></button>
          </div>
        </div>

        <StatusBars service={service} windowDays={windowDays} tx={tx} />
        <div className="mt-2 flex flex-col gap-2 text-xs text-slate-500 dark:text-slate-400 sm:flex-row sm:items-center sm:justify-between">
          <span>{meta.label}</span>
          <button type="button" onClick={onCheck} disabled={!canCheck || checking} className="inline-flex items-center gap-1.5 self-start rounded-lg border border-indigo-200 px-2.5 py-1.5 text-[11px] font-semibold text-indigo-700 transition hover:bg-indigo-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-indigo-800 dark:text-indigo-300 dark:hover:bg-indigo-950/40 sm:self-auto">{checking ? <RefreshCw className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}{checking ? tx('ai.model.health.checking') : tx('ai.health.checkNow')}</button>
        </div>
      </div>
      {expanded && <div className="border-t border-slate-100 bg-slate-50/70 px-5 py-4 dark:border-slate-800 dark:bg-slate-950/40 sm:px-6"><div className="grid grid-cols-2 gap-3 sm:grid-cols-4"><div><p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">{tx('ai.health.detail.checks')}</p><p className="mt-1 font-mono text-sm font-semibold text-slate-800 dark:text-slate-100">{service.window_check_count}</p></div><div><p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">{tx('ai.health.detail.success')}</p><p className="mt-1 font-mono text-sm font-semibold text-emerald-600 dark:text-emerald-300">{service.window_success_count}</p></div><div><p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">{tx('ai.health.detail.failures')}</p><p className="mt-1 font-mono text-sm font-semibold text-rose-600 dark:text-rose-300">{service.window_failure_count}</p></div><div><p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">{tx('ai.health.detail.lastProbe')}</p><p className="mt-1 text-sm font-semibold text-slate-800 dark:text-slate-100">{formatDate(service.last_health_check_at, language, tx)}</p></div></div><div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-slate-500 dark:text-slate-400"><span>{tx('ai.health.detail.latency')}: {formatLatency(service.window_avg_latency_ms, tx)}</span><span>{tx('ai.health.detail.type')}: {service.model_type}</span><span>{tx('ai.health.detail.window')}: {windowDays} {tx('ai.health.status.days')}</span></div></div>}
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
      if (result.success) showToast(tx('ai.model.health.toast.success', { name: service.model_name, latency: result.latency_ms }), 'success');
      else showToast(tx('ai.model.health.toast.failure', { name: service.model_name, code: result.error_code || 'unknown' }), 'error');
      await fetchData(true);
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : tx('ai.model.health.toast.error'), 'error');
    } finally {
      setCheckingModelId(null);
    }
  };

  const latestDate = summary?.generated_at;
  const rangeLabel = formatMonthRange(summary?.window_start, latestDate, language);
  const overall = statusMeta(summary?.overall_status, tx);
  const OverallIcon = summary?.overall_status === 'healthy' ? CheckCircle2 : summary?.overall_status === 'unknown' ? Clock3 : AlertTriangle;
  const services = useMemo(() => summary?.services || [], [summary]);

  return (
    <div className="min-h-full bg-[#f7f8fa] pb-10 dark:bg-slate-950">
      <div className="mx-auto w-full max-w-[1680px] space-y-5 px-1 sm:px-2">
        <header className="flex flex-col justify-between gap-4 px-1 pt-1 sm:flex-row sm:items-end sm:px-2 sm:pt-2">
          <div><p className="text-[11px] font-bold uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">NEXORA STATUS</p><h2 className="mt-1 text-[27px] font-semibold tracking-tight text-[#172b4d] dark:text-white">{tx('ai.health.status.currentTitle')}</h2></div>
          <div className="flex flex-wrap items-center gap-2 text-sm text-slate-500 dark:text-slate-400"><span>{tx('ai.health.status.updatedAt', { value: latestDate ? formatDate(latestDate, language, tx) : tx('ai.health.never') })}</span><button type="button" onClick={() => void fetchData()} disabled={loading || refreshing} aria-label={tx('ai.common.refresh')} className="rounded-lg border border-slate-200 bg-white p-2 text-slate-500 shadow-sm transition hover:border-indigo-300 hover:text-indigo-600 disabled:cursor-wait disabled:opacity-50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300"><RefreshCw className={`h-4 w-4 ${loading || refreshing ? 'animate-spin' : ''}`} /></button></div>
        </header>

        {error && <div role="alert" className="rounded-xl border border-rose-300 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/70 dark:bg-rose-950/30 dark:text-rose-300">{error}</div>}

        <section className={`overflow-hidden rounded-xl border shadow-sm ${summary?.overall_status === 'healthy' ? 'border-[#31c79a]' : summary?.overall_status === 'unknown' ? 'border-slate-300' : 'border-[#ed6571]'}`}>
          <div className={`flex items-center gap-3 px-5 py-4 ${summary?.overall_status === 'healthy' ? 'bg-[#d6f7ee] text-[#152b2b]' : summary?.overall_status === 'unknown' ? 'bg-slate-100 text-slate-700' : 'bg-[#ffe2e5] text-[#4e2027]'}`}><span className="flex h-6 w-6 items-center justify-center rounded-full bg-white/80"><OverallIcon className="h-4 w-4" /></span><span className="text-[18px] font-medium">{summary?.overall_status === 'healthy' ? tx('ai.health.status.operational') : summary?.overall_status === 'unknown' ? tx('ai.health.status.awaitingData') : tx('ai.health.status.attention')}</span></div>
          <div className="flex flex-col gap-3 bg-white px-5 py-4 text-[15px] text-slate-700 dark:bg-slate-900 dark:text-slate-300 sm:flex-row sm:items-center sm:justify-between"><span>{summary?.overall_status === 'healthy' ? tx('ai.health.status.operationalBody') : summary?.overall_status === 'unknown' ? tx('ai.health.status.awaitingDataBody') : tx('ai.health.status.attentionBody')}</span><button type="button" onClick={() => navigate('/ai/models')} className="inline-flex items-center gap-1.5 self-start text-xs font-semibold text-indigo-600 hover:text-indigo-700 dark:text-indigo-300">{tx('ai.health.manageModels')}<ExternalLink className="h-3.5 w-3.5" /></button></div>
        </section>

        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <div className="flex flex-col justify-between gap-3 border-b border-slate-200 px-5 py-4 dark:border-slate-800 sm:flex-row sm:items-center sm:px-6"><div className="flex items-center gap-2"><h3 className="text-[18px] font-medium text-slate-900 dark:text-white">{tx('ai.health.status.systemStatus')}</h3><span className="text-xs text-slate-400">{summary ? `${summary.service_count} ${tx('ai.health.status.services')}` : '—'}</span></div><div className="flex items-center gap-2"><button type="button" disabled className="rounded-md p-1 text-slate-300 dark:text-slate-700"><ChevronLeft className="h-4 w-4" /></button><span className="min-w-[170px] text-center text-sm text-slate-500 dark:text-slate-400">{rangeLabel}</span><button type="button" disabled className="rounded-md p-1 text-slate-300 dark:text-slate-700"><ChevronRight className="h-4 w-4" /></button><div className="ml-2 flex rounded-lg border border-slate-200 p-0.5 dark:border-slate-700">{([30, 90] as WindowDays[]).map((days) => <button key={days} type="button" onClick={() => setWindowDays(days)} className={`rounded-md px-2 py-1 text-[11px] font-semibold ${windowDays === days ? 'bg-indigo-600 text-white' : 'text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800'}`}>{days}{tx('ai.health.status.daysShort')}</button>)}</div></div></div>
          {loading && !summary ? <div className="space-y-4 px-5 py-8 sm:px-6">{[0, 1, 2, 3].map((item) => <div key={item} className="h-28 animate-pulse rounded-lg bg-slate-100 dark:bg-slate-800" />)}</div> : services.length === 0 ? <div className="px-5 py-16 text-center text-sm text-slate-500 dark:text-slate-400"><Server className="mx-auto mb-3 h-8 w-8 opacity-40" />{tx('ai.health.status.noServices')}</div> : <div>{services.map((service) => <ServiceStatusRow key={service.model_id} service={service} windowDays={windowDays} expanded={expandedServices.has(service.model_id)} onToggle={() => setExpandedServices((current) => { const next = new Set(current); if (next.has(service.model_id)) next.delete(service.model_id); else next.add(service.model_id); return next; })} onCheck={() => void handleCheck(service)} checking={checkingModelId === service.model_id} tx={tx} language={language} />)}</div>}
          <div className="flex flex-col gap-2 border-t border-slate-200 px-5 py-4 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400 sm:flex-row sm:items-center sm:justify-between sm:px-6"><div className="flex flex-wrap items-center gap-x-4 gap-y-2"><span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-[#21c38e]" />{tx('ai.health.status.legendHealthy')}</span><span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-[#f4b53f]" />{tx('ai.health.status.legendDegraded')}</span><span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-[#ec5965]" />{tx('ai.health.status.legendUnhealthy')}</span><span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-slate-200" />{tx('ai.health.status.legendUnknown')}</span></div><span>{summary ? tx('ai.health.status.summary', { checks: summary.total_check_count, success: summary.total_success_count, failure: summary.total_failure_count }) : '—'}</span></div>
        </section>
      </div>
    </div>
  );
};

export default ModelHealthDashboardTab;
