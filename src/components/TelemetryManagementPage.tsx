import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleDashed,
  Database,
  Gauge,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  Server,
  ShieldAlert,
  ShieldCheck,
  XCircle,
  type LucideIcon,
} from 'lucide-react';
import { ApiError } from '../api/http';
import {
  getTelemetryCollectors,
  getTelemetryCollectorCapacity,
  getTelemetryProfiles,
  getTelemetrySubscriptionStatus,
  getTelemetrySubscriptions,
  runTelemetrySubscriptionAction,
} from '../api/telemetry';
import type {
  TelemetryActionAccepted,
  TelemetryCapacityVector,
  TelemetryCollectorOption,
  TelemetryCollectorCapacity,
  TelemetryPathEvidence,
  TelemetryProtocolProfile,
  TelemetrySubscription,
  TelemetrySubscriptionAction,
  TelemetrySubscriptionStatus,
} from '../types/telemetry';
import type { Device } from '../types';
import TelemetryControlSetupPanel from './TelemetryControlSetupPanel';

interface TelemetryManagementPageProps {
  /** Pass false when the current user's role is known to be read-only. */
  canManage?: boolean;
  devices?: Device[];
}

type Notice = { kind: 'success' | 'error'; message: string };
type LoadIssue = { source: string; message: string; forbidden: boolean };

const PAGE_SIZE = 20;

const PUBLISH_LABELS: Record<string, string> = {
  DRAFT: '草稿', QUEUED: '排队中', PUBLISHING: '发布中', APPLIED: '已应用', FAILED: '发布失败',
};
const CONNECTION_LABELS: Record<string, string> = {
  DISABLED: '已停用', AWAITING_DEVICE: '等待设备', CONNECTING: '连接中', CONNECTED: '已连接', ERROR: '连接异常',
};
const DATA_LABELS: Record<string, string> = {
  NO_DATA: '暂无数据', FRESH: '数据新鲜', PARTIAL: '数据不完整', STALE: '数据过期', INVALID: '数据无效',
};

const SUPPORT_LABELS: Record<string, string> = {
  DOCUMENTED: '官网有说明，未实机验证',
  SAMPLE_VERIFIED: '样例已验证',
  DEVICE_VERIFIED: '设备已验证',
  UNKNOWN: '支持情况未知',
  UNSUPPORTED: '不支持',
};

function errorStatus(reason: unknown): number | undefined {
  return reason instanceof ApiError ? reason.status : undefined;
}

function errorMessage(reason: unknown, fallback: string): string {
  const status = errorStatus(reason);
  if (status === 401) return '登录状态已失效，请重新登录。';
  if (status === 403) return '当前账号没有查看或管理 Telemetry 数据的权限。';
  if (status === 404) return '目标资源不存在或已被删除，请刷新后重试。';
  if (reason instanceof ApiError && reason.code) {
    const known: Record<string, string> = {
      TELEMETRY_PROFILE_UNSUPPORTED: '所选协议档不支持此设备。',
      TELEMETRY_VERSION_UNVERIFIED: '设备软件版本尚未验证。',
      TELEMETRY_PATH_UNVERIFIED: '部分采集路径尚未验证。',
      TELEMETRY_INTERVAL_TOO_SHORT: '采样周期短于设备支持的最小周期。',
      TELEMETRY_CAPACITY_EXCEEDED: '采集器容量不足，操作未提交。',
      TELEMETRY_TLS_INVALID: '证书或 TLS 配置无效。',
      TELEMETRY_DEVICE_NOT_READY: '设备尚未准备好接收 Telemetry。',
      TELEMETRY_CONFIG_CONFLICT: '配置已被其他操作更新，请刷新后重试。',
    };
    if (known[reason.code]) return known[reason.code];
  }
  return reason instanceof Error && reason.message ? reason.message : fallback;
}

function displayDate(value?: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false });
}

function displayVendor(value?: string): string {
  if (!value) return '—';
  const normalized = value.toLowerCase();
  if (normalized.includes('huawei')) return '华为';
  if (normalized === 'h3c' || normalized.includes('h3c')) return '华三';
  return value;
}

function statusTone(status?: string, type: 'publish' | 'connection' | 'data' | 'support' = 'data'): string {
  const value = (status || '').toUpperCase();
  if (['APPLIED', 'CONNECTED', 'FRESH', 'SUPPORTED', 'VERIFIED', 'SAMPLE_VERIFIED', 'DEVICE_VERIFIED', 'ENABLED'].includes(value)) {
    return 'border-emerald-200 bg-emerald-50 text-emerald-700';
  }
  if (['FAILED', 'ERROR', 'INVALID', 'STALE', 'UNSUPPORTED'].includes(value)) {
    return 'border-rose-200 bg-rose-50 text-rose-700';
  }
  if (['DOCUMENTED', 'UNKNOWN', 'PARTIAL', 'QUEUED', 'PUBLISHING', 'CONNECTING', 'AWAITING_DEVICE', 'UNVERIFIED', 'NO_DATA'].includes(value)) {
    return 'border-amber-200 bg-amber-50 text-amber-800';
  }
  if (type === 'connection' && value === 'DISABLED') return 'border-slate-200 bg-slate-100 text-slate-600';
  return 'border-[var(--card-border)] bg-[var(--card-bg)] text-[var(--muted-text)]';
}

function StatusPill({ value, type, fallback = '未知', label }: { value?: string; type?: 'publish' | 'connection' | 'data' | 'support'; fallback?: string; label?: string }) {
  const normalized = (value || '').toUpperCase();
  const labels = type === 'publish' ? PUBLISH_LABELS
    : type === 'connection' ? CONNECTION_LABELS
      : type === 'support' ? SUPPORT_LABELS
        : DATA_LABELS;
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-bold ${statusTone(normalized, type)}`}>
      {label || labels[normalized] || value || fallback}
    </span>
  );
}

function profileScope(profile: TelemetryProtocolProfile): string {
  const splitScope = (value?: string) => String(value || '').split(/[,/;]+/).map((item) => item.trim()).filter(Boolean);
  const parts = [
    ...splitScope(profile.model_scope),
    ...splitScope(profile.version_scope),
  ];
  return parts.length ? parts.join(' · ') : '支持范围待补充';
}

function profileDisplayName(profile: TelemetryProtocolProfile): string {
  if (profile.profile_key === 'h3c_grpc_dialout_json_v2') return '华三 Comware Dial-out JSON v2';
  if (profile.profile_key === 'h3c_grpc_dialout_json_v3') return '华三 Comware Dial-out JSON v3';
  if (profile.profile_key === 'huawei_grpc_dialout_json') return '华为 gRPC Dial-out JSON';
  return profile.profile_key;
}

function EvidenceList({ paths }: { paths?: TelemetryPathEvidence[] }) {
  if (!paths?.length) return <p className="mt-2 text-xs text-[var(--muted-text)]">尚无逐路径验证记录</p>;
  return (
    <ul className="mt-2 space-y-1">
      {paths.slice(0, 4).map((item, index) => (
        <li key={`${item.path}:${item.metric_key || ''}:${index}`} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
          <code className="max-w-full break-all rounded bg-black/[0.04] px-1.5 py-0.5 text-slate-600 dark:bg-white/[0.06] dark:text-slate-300">{item.path}</code>
          {item.metric_key && <span className="text-[var(--muted-text)]">{item.metric_key}</span>}
          <StatusPill value={item.validation_status} type="support" />
          {item.evidence && <span className="w-full break-words text-[var(--muted-text)]">依据：{item.evidence}</span>}
        </li>
      ))}
      {paths.length > 4 && <li className="text-xs text-[var(--muted-text)]">另有 {paths.length - 4} 条路径证据</li>}
    </ul>
  );
}

function OfficialSourceList({ sources }: { sources?: string[] }) {
  if (!sources?.length) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {sources.map((source, index) => (
        <a key={`${source}:${index}`} href={source} target="_blank" rel="noreferrer" className="text-xs font-semibold text-cyan-700 underline underline-offset-2 hover:text-cyan-900">
          厂商资料 {index + 1}
        </a>
      ))}
    </div>
  );
}

function MetricValue({ label, value, icon: Icon }: { label: string; value: string; icon: LucideIcon }) {
  return (
    <div className="flex items-center gap-4 rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] px-5 py-4">
      <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-cyan-500/10 text-cyan-700 dark:text-cyan-300">
        <Icon size={19} aria-hidden="true" />
      </span>
      <div className="min-w-0">
        <p className="text-xs font-medium text-[var(--muted-text)]">{label}</p>
        <p className="mt-0.5 text-2xl font-semibold tabular-nums tracking-tight text-[var(--app-text)]">{value}</p>
      </div>
    </div>
  );
}

function CapacityTable({ capacity }: { capacity: TelemetryCollectorCapacity }) {
  const formatBytes = (value: number) => {
    if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(value % (1024 ** 3) ? 1 : 0)} GiB`;
    if (value >= 1024 ** 2) return `${(value / 1024 ** 2).toFixed(value % (1024 ** 2) ? 1 : 0)} MiB`;
    if (value >= 1024) return `${(value / 1024).toFixed(1)} KiB`;
    return `${value} B`;
  };
  const dimensions: Array<{ key: keyof TelemetryCapacityVector; label: string; format?: (value: number) => string }> = [
    { key: 'devices', label: '设备数' },
    { key: 'series', label: '序列数' },
    { key: 'samples_per_second', label: '样本/秒', format: (value) => value.toLocaleString('zh-CN') },
    { key: 'message_bytes', label: '消息大小', format: formatBytes },
    { key: 'queue_bytes', label: '持久队列', format: formatBytes },
  ];
  const cell = (value: number | null | undefined, format?: (value: number) => string) => value == null ? '—' : format ? format(value) : value.toLocaleString('zh-CN');
  return (
    <div className="mt-3 overflow-x-auto rounded-xl border border-[var(--card-border)]">
      <table className="w-full min-w-[500px] text-left text-xs">
        <thead className="bg-black/[0.025] text-xs font-bold text-[var(--muted-text)] dark:bg-white/[0.035]">
          <tr><th className="px-3 py-2">容量维度</th><th className="px-3 py-2">上限</th><th className="px-3 py-2">已预留</th><th className="px-3 py-2">实测</th></tr>
        </thead>
        <tbody className="divide-y divide-[var(--card-border)]">
          {dimensions.map(({ key, label, format }) => (
            <tr key={key}>
              <th scope="row" className="px-3 py-2 font-semibold text-[var(--app-text)]">{label}</th>
              <td className="px-3 py-2 text-[var(--muted-text)]">{cell(capacity.limit?.[key], format)}</td>
              <td className="px-3 py-2 text-[var(--muted-text)]">{cell(capacity.reserved?.[key], format)}</td>
              <td className="px-3 py-2 font-semibold text-[var(--app-text)]">{cell(capacity.observed?.[key], format)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="border-t border-[var(--card-border)] px-3 py-2 text-xs leading-relaxed text-[var(--muted-text)]">单条 gRPC / JSON 消息限制 4 MiB，写入批次限制 1 MiB；Telemetry 数据经独立接收器推送到 telemetry-vmagent，不进入现有 64 MiB 抓取响应。队列上限为 16 GiB，当前实际队列占用未接入数据库监控，显示“—”。</p>
      <p className="border-t border-[var(--card-border)] px-3 py-2 text-xs text-[var(--muted-text)]">容量统计时间：{displayDate(capacity.measured_at)}</p>
    </div>
  );
}

function StatusDetails({ status }: { status: TelemetrySubscriptionStatus }) {
  return (
    <div className="grid gap-3 p-3 sm:grid-cols-2 xl:grid-cols-4">
      <div><p className="text-xs font-bold text-[var(--muted-text)]">版本</p><p className="mt-1 text-xs text-[var(--app-text)]">期望 {status.desired_version ?? '—'} · 已发布 {status.published_version ?? '—'} · 已应用 {status.applied_version ?? '—'}</p></div>
      <div><p className="text-xs font-bold text-[var(--muted-text)]">最近接收</p><p className="mt-1 text-xs text-[var(--app-text)]">{displayDate(status.last_received_at)}</p></div>
      <div><p className="text-xs font-bold text-[var(--muted-text)]">最近有效样本</p><p className="mt-1 text-xs text-[var(--app-text)]">{displayDate(status.last_valid_at)}</p></div>
      {status.clock_skew_ms != null && <div><p className="text-xs font-bold text-[var(--muted-text)]">设备时钟偏差</p><p className="mt-1 text-xs text-[var(--app-text)]">{status.clock_skew_ms.toLocaleString('zh-CN')} 毫秒</p></div>}
      <div><p className="text-xs font-bold text-[var(--muted-text)]">活动序列 / 速率</p><p className="mt-1 text-xs text-[var(--app-text)]">{status.active_series ?? '—'} / {status.samples_per_second ?? '—'} 样本/秒</p></div>
      {status.quality && <div><p className="text-xs font-bold text-[var(--muted-text)]">数据质量</p><p className="mt-1 text-xs text-[var(--app-text)]">{status.quality}</p></div>}
      {status.error && <div className="sm:col-span-2 xl:col-span-3"><p className="text-xs font-bold text-rose-700">{status.error.code} · {status.error.retryable ? '可重试' : '需处理'}</p><p className="mt-1 text-xs text-rose-700">{status.error.message}</p></div>}
    </div>
  );
}

const TelemetryManagementPage: React.FC<TelemetryManagementPageProps> = ({ canManage = true, devices = [] }) => {
  const [profiles, setProfiles] = useState<TelemetryProtocolProfile[]>([]);
  const [view, setView] = useState<'subscriptions' | 'configuration'>('subscriptions');
  const [collectors, setCollectors] = useState<TelemetryCollectorOption[]>([]);
  const [subscriptions, setSubscriptions] = useState<TelemetrySubscription[]>([]);
  const [totalSubscriptions, setTotalSubscriptions] = useState(0);
  const [page, setPage] = useState(1);
  const [loadedPage, setLoadedPage] = useState(0);
  const [reloadKey, setReloadKey] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [loadIssues, setLoadIssues] = useState<LoadIssue[]>([]);
  const [mutationDenied, setMutationDenied] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busyActions, setBusyActions] = useState<Record<string, TelemetrySubscriptionAction>>({});
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [expandedStatus, setExpandedStatus] = useState<TelemetrySubscriptionStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const [statusIssue, setStatusIssue] = useState<string | null>(null);
  const [selectedCollectorId, setSelectedCollectorId] = useState('');
  const [capacity, setCapacity] = useState<TelemetryCollectorCapacity | null>(null);
  const [capacityLoading, setCapacityLoading] = useState(false);
  const [capacityIssue, setCapacityIssue] = useState<LoadIssue | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setIsLoading(true);
    setLoadIssues([]);
    void Promise.allSettled([
      getTelemetryProfiles(controller.signal),
      getTelemetrySubscriptions({ page, page_size: PAGE_SIZE }, controller.signal),
      getTelemetryCollectors(controller.signal),
    ]).then(([profilesResult, subscriptionsResult, collectorsResult]) => {
      if (controller.signal.aborted) return;
      const issues: LoadIssue[] = [];
      if (profilesResult.status === 'fulfilled') setProfiles(profilesResult.value.items || []);
      else issues.push({ source: '协议档', message: errorMessage(profilesResult.reason, '协议档加载失败。'), forbidden: errorStatus(profilesResult.reason) === 403 });
      if (subscriptionsResult.status === 'fulfilled') {
        setSubscriptions(subscriptionsResult.value.items || []);
        setTotalSubscriptions(subscriptionsResult.value.total || 0);
        setLoadedPage(page);
      } else {
        issues.push({ source: '订阅列表', message: errorMessage(subscriptionsResult.reason, '订阅列表加载失败。'), forbidden: errorStatus(subscriptionsResult.reason) === 403 });
      }
      if (collectorsResult.status === 'fulfilled') setCollectors((collectorsResult.value.items || []).filter((item) => item.collector_type === 'LOCAL' && item.enabled !== false && item.enabled !== 0));
      else issues.push({ source: '采集器列表', message: errorMessage(collectorsResult.reason, '采集器列表加载失败。'), forbidden: errorStatus(collectorsResult.reason) === 403 });
      setLoadIssues(issues);
    }).finally(() => {
      if (!controller.signal.aborted) setIsLoading(false);
    });
    return () => controller.abort();
  }, [page, reloadKey]);

  const currentPageSubscriptions = loadedPage === page ? subscriptions : [];

  const collectorOptions = useMemo(() => collectors.map((collector) => ({
    id: collector.id,
    label: collector.name || collector.id,
  })), [collectors]);

  useEffect(() => {
    if (collectorOptions.some((item) => item.id === selectedCollectorId)) return;
    setSelectedCollectorId(collectorOptions[0]?.id || '');
  }, [collectorOptions, selectedCollectorId]);

  useEffect(() => {
    if (!selectedCollectorId) {
      setCapacity(null);
      setCapacityIssue(null);
      setCapacityLoading(false);
      return;
    }
    const controller = new AbortController();
    setCapacityLoading(true);
    setCapacityIssue(null);
    void getTelemetryCollectorCapacity(selectedCollectorId, controller.signal).then((payload) => {
      if (!controller.signal.aborted) setCapacity(payload);
    }).catch((reason: unknown) => {
      if (controller.signal.aborted) return;
      setCapacity(null);
      setCapacityIssue({
        source: '容量摘要',
        message: errorMessage(reason, '采集器容量摘要加载失败。'),
        forbidden: errorStatus(reason) === 403,
      });
    }).finally(() => {
      if (!controller.signal.aborted) setCapacityLoading(false);
    });
    return () => controller.abort();
  }, [selectedCollectorId, reloadKey]);

  useEffect(() => {
    if (!expandedId) {
      setExpandedStatus(null);
      setStatusIssue(null);
      return;
    }
    const controller = new AbortController();
    setExpandedStatus(null);
    setStatusIssue(null);
    setStatusLoading(true);
    void getTelemetrySubscriptionStatus(expandedId, controller.signal).then((payload) => {
      if (!controller.signal.aborted) setExpandedStatus(payload);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setStatusIssue(errorMessage(reason, '订阅状态加载失败。'));
    }).finally(() => {
      if (!controller.signal.aborted) setStatusLoading(false);
    });
    return () => controller.abort();
  }, [expandedId, reloadKey]);

  const refresh = useCallback(() => {
    setNotice(null);
    setReloadKey((current) => current + 1);
  }, []);

  const submitAction = useCallback(async (subscription: TelemetrySubscription, action: TelemetrySubscriptionAction) => {
    setBusyActions((current) => ({ ...current, [subscription.id]: action }));
    setNotice(null);
    try {
      const accepted: TelemetryActionAccepted = await runTelemetrySubscriptionAction(subscription.id, action);
      const actionLabel = action === 'enable' ? '启用' : action === 'disable' ? '停用' : '重试';
      setNotice({ kind: 'success', message: `${actionLabel}请求已提交，任务 ${accepted.job_id}，期望版本 ${accepted.desired_version}。` });
      setReloadKey((current) => current + 1);
    } catch (reason) {
      if (errorStatus(reason) === 403) setMutationDenied(true);
      setNotice({ kind: 'error', message: errorMessage(reason, '操作提交失败。') });
    } finally {
      setBusyActions((current) => {
        const next = { ...current };
        delete next[subscription.id];
        return next;
      });
    }
  }, []);

  const managedDisabled = !canManage || mutationDenied || loadIssues.some((issue) => issue.forbidden);
  const currentPageCount = Math.ceil(totalSubscriptions / PAGE_SIZE);
  const activeCount = currentPageSubscriptions.filter((item) => item.desired_enabled).length;
  const failedCount = currentPageSubscriptions.filter((item) => item.runtime?.publish_state === 'FAILED' || item.runtime?.connection_state === 'ERROR' || item.runtime?.data_state === 'INVALID').length;

  return (
    <section className="mx-auto w-full max-w-screen-2xl space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-6 rounded-3xl bg-gradient-to-br from-slate-950 via-slate-900 to-cyan-950 px-6 py-7 text-white md:px-8 md:py-9">
        <div className="flex items-center gap-4">
          <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-cyan-400/15 text-cyan-200">
            <Activity size={24} aria-hidden="true" />
          </span>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">Telemetry 采集</h1>
            <p className="mt-1 text-sm text-slate-300">管理设备订阅，查看采集状态和接收器容量。</p>
          </div>
        </div>
        <button type="button" onClick={refresh} disabled={isLoading} className="inline-flex items-center gap-2 rounded-xl border border-white/20 bg-white/5 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-white/10 disabled:opacity-50">
          {isLoading ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
          刷新数据
        </button>
      </header>

      {canManage === false && (
        <div role="status" className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs text-amber-800">
          <ShieldCheck size={15} className="mt-0.5 shrink-0" />当前账号仅有查看权限，启停和重试操作已禁用。
        </div>
      )}
      {loadIssues.map((issue) => (
        <div key={`${issue.source}:${issue.message}`} role="alert" className={`flex items-start gap-2 rounded-xl border px-3 py-2.5 text-xs ${issue.forbidden ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-amber-200 bg-amber-50 text-amber-800'}`}>
          {issue.forbidden ? <ShieldAlert size={15} className="mt-0.5 shrink-0" /> : <AlertTriangle size={15} className="mt-0.5 shrink-0" />}
          <span><b>{issue.source}：</b>{issue.message}</span>
        </div>
      ))}
      {mutationDenied && canManage && (
        <div role="alert" className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2.5 text-xs text-rose-700">
          <ShieldAlert size={15} className="mt-0.5 shrink-0" />服务端拒绝了管理操作，当前页面已禁用启停和重试按钮。
        </div>
      )}
      {notice && (
        <div role={notice.kind === 'error' ? 'alert' : 'status'} className={`rounded-xl border px-3 py-2.5 text-xs ${notice.kind === 'error' ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>
          {notice.message}
        </div>
      )}

      <div role="group" aria-label="Telemetry 采集视图" className="flex flex-wrap gap-x-6 border-b border-[var(--card-border)] px-1">
        {([
          { id: 'subscriptions', label: '订阅与运行状态', icon: Activity },
          { id: 'configuration', label: '设备配置', icon: Server },
        ] as const).map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            aria-pressed={view === id}
            aria-controls={`telemetry-${id}`}
            onClick={() => setView(id)}
            className={`inline-flex items-center gap-2 border-b-2 px-2 py-3 text-sm font-semibold transition ${view === id ? 'border-cyan-600 text-cyan-700 dark:text-cyan-300' : 'border-transparent text-[var(--muted-text)] hover:text-[var(--app-text)]'}`}
          >
            <Icon size={16} aria-hidden="true" />
            {label}
          </button>
        ))}
      </div>

      <div id="telemetry-subscriptions" hidden={view !== 'subscriptions'} className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <MetricValue label="当前页订阅" value={`${currentPageSubscriptions.length} / ${loadedPage === page ? totalSubscriptions : '—'}`} icon={Activity} />
          <MetricValue label="期望启用" value={activeCount.toLocaleString('zh-CN')} icon={Play} />
          <MetricValue label="异常订阅" value={failedCount.toLocaleString('zh-CN')} icon={AlertTriangle} />
        </div>

        <section className="rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-4 shadow-sm md:p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="flex items-center gap-2 text-base font-semibold text-[var(--app-text)]"><Activity size={16} className="text-cyan-700 dark:text-cyan-300" />订阅列表</h2>
              <p className="mt-1 text-xs text-[var(--muted-text)]">期望开关、发布状态、连接状态和数据状态分别展示。</p>
            </div>
          </div>
          {isLoading && currentPageSubscriptions.length === 0 ? (
            <div className="mt-4 flex items-center justify-center gap-2 rounded-xl border border-dashed border-[var(--card-border)] py-12 text-xs text-[var(--muted-text)]"><Loader2 size={15} className="animate-spin" />正在加载订阅…</div>
          ) : currentPageSubscriptions.length ? (
            <div className="mt-4 overflow-x-auto rounded-xl border border-[var(--card-border)]">
              <table className="w-full min-w-[980px] text-left text-xs">
                <thead className="bg-black/[0.025] text-xs font-bold text-[var(--muted-text)] dark:bg-white/[0.035]">
                  <tr><th className="px-3 py-2.5">设备</th><th className="px-3 py-2.5">订阅 / 协议档</th><th className="px-3 py-2.5">期望</th><th className="px-3 py-2.5">发布</th><th className="px-3 py-2.5">连接</th><th className="px-3 py-2.5">数据</th><th className="px-3 py-2.5">最近有效样本</th><th className="px-3 py-2.5">操作</th></tr>
                </thead>
                <tbody className="divide-y divide-[var(--card-border)]">
                  {currentPageSubscriptions.map((subscription) => {
                    const busy = busyActions[subscription.id];
                    const runtime = subscription.runtime;
                    const label = subscription.device_name || subscription.asset_tag || subscription.device_id;
                    return (
                      <Fragment key={subscription.id}>
                        <tr key={subscription.id} className="align-top">
                          <td className="px-3 py-3"><p className="font-bold text-[var(--app-text)]">{label}</p><p className="mt-0.5 font-mono text-xs text-[var(--muted-text)]">{subscription.device_id}</p></td>
                          <td className="px-3 py-3"><p className="font-semibold text-[var(--app-text)]">{subscription.name}</p><p className="mt-0.5 text-xs text-[var(--muted-text)]">{subscription.profile_name || '未关联协议档'}{subscription.template_name ? ` · ${subscription.template_name} v${subscription.template_version ?? '—'}` : ''}</p><p className="mt-0.5 text-xs text-[var(--muted-text)]">{subscription.interval_seconds ? `${subscription.interval_seconds} 秒周期` : '周期未知'}{subscription.collector_name ? ` · ${subscription.collector_name}` : ''}</p></td>
                          <td className="px-3 py-3"><StatusPill value={subscription.desired_enabled ? 'ENABLED' : 'DISABLED'} type={subscription.desired_enabled ? 'support' : 'connection'} label={subscription.desired_enabled ? '期望启用' : '期望停用'} /></td>
                          <td className="px-3 py-3"><StatusPill value={runtime?.publish_state} type="publish" /></td>
                          <td className="px-3 py-3"><StatusPill value={runtime?.connection_state} type="connection" /></td>
                          <td className="px-3 py-3"><StatusPill value={runtime?.data_state} type="data" /></td>
                          <td className="px-3 py-3 text-xs text-[var(--muted-text)]">{displayDate(runtime?.last_valid_at)}</td>
                          <td className="px-3 py-3">
                            <div className="flex flex-wrap gap-1.5">
                              <button type="button" disabled={managedDisabled || Boolean(busy)} onClick={() => void submitAction(subscription, subscription.desired_enabled ? 'disable' : 'enable')} className={`inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-xs font-bold text-white disabled:cursor-not-allowed disabled:opacity-50 ${subscription.desired_enabled ? 'bg-slate-600 hover:bg-slate-700' : 'bg-emerald-600 hover:bg-emerald-700'}`}>
                                {busy ? <Loader2 size={12} className="animate-spin" /> : subscription.desired_enabled ? <Pause size={12} /> : <Play size={12} />}{subscription.desired_enabled ? '停用' : '启用'}
                              </button>
                              <button type="button" disabled={managedDisabled || Boolean(busy)} onClick={() => void submitAction(subscription, 'retry')} className="inline-flex items-center gap-1 rounded-md border border-[var(--card-border)] px-2 py-1.5 text-xs font-bold text-[var(--app-text)] hover:bg-black/[0.04] disabled:cursor-not-allowed disabled:opacity-50 dark:hover:bg-white/[0.06]">
                                {busy === 'retry' ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />}重试
                              </button>
                              <button type="button" aria-expanded={expandedId === subscription.id} onClick={() => setExpandedId((current) => current === subscription.id ? null : subscription.id)} className="rounded-md px-2 py-1.5 text-xs font-bold text-cyan-700 hover:bg-cyan-50">{expandedId === subscription.id ? '收起' : '状态详情'}</button>
                            </div>
                          </td>
                        </tr>
                        {expandedId === subscription.id && (
                          <tr key={`${subscription.id}:status`}><td colSpan={8} className="bg-black/[0.02] dark:bg-white/[0.025]">
                            {statusLoading ? <p className="flex items-center gap-2 p-3 text-xs text-[var(--muted-text)]"><Loader2 size={13} className="animate-spin" />正在加载状态详情…</p>
                              : statusIssue ? <p role="alert" className="p-3 text-xs text-rose-700">{statusIssue}</p>
                                : expandedStatus ? <StatusDetails status={expandedStatus} /> : <p className="p-3 text-xs text-[var(--muted-text)]">暂无状态详情。</p>}
                          </td></tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
              <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[var(--card-border)] px-3 py-2">
                <span className="text-xs text-[var(--muted-text)]">第 {page} / {Math.max(1, currentPageCount)} 页 · 共 {totalSubscriptions} 条</span>
                <div className="flex gap-1.5">
                  <button type="button" disabled={page <= 1 || isLoading} onClick={() => setPage((value) => Math.max(1, value - 1))} className="inline-flex items-center gap-1 rounded-md border border-[var(--card-border)] px-2 py-1.5 text-xs font-bold disabled:opacity-40"><ChevronLeft size={12} />上一页</button>
                  <button type="button" disabled={page >= currentPageCount || isLoading} onClick={() => setPage((value) => value + 1)} className="inline-flex items-center gap-1 rounded-md border border-[var(--card-border)] px-2 py-1.5 text-xs font-bold disabled:opacity-40">下一页<ChevronRight size={12} /></button>
                </div>
              </div>
            </div>
          ) : (
            <div className="mt-4 rounded-xl border border-dashed border-[var(--card-border)] px-4 py-10 text-center">
              {isLoading ? <Loader2 size={16} className="mx-auto animate-spin text-[var(--muted-text)]" /> : loadIssues.some((issue) => issue.source === '订阅列表') ? <XCircle size={18} className="mx-auto text-rose-500" /> : <CircleDashed size={18} className="mx-auto text-[var(--muted-text)]" />}
              <p className="mt-2 text-sm font-semibold text-[var(--app-text)]">{loadIssues.some((issue) => issue.source === '订阅列表') ? '订阅列表暂不可用' : '暂无 Telemetry 订阅'}</p>
              <p className="mt-1 text-xs text-[var(--muted-text)]">{loadIssues.some((issue) => issue.source === '订阅列表') ? '请查看上方错误信息并刷新重试。' : '配置设备和订阅后，运行状态会显示在这里。'}</p>
              {!isLoading && !loadIssues.some((issue) => issue.source === '订阅列表') && canManage && (
                <button type="button" onClick={() => setView('configuration')} className="mt-3 rounded-lg bg-cyan-700 px-4 py-2 text-xs font-semibold text-white hover:bg-cyan-800">
                  配置设备
                </button>
              )}
            </div>
          )}
        </section>

        <section className="rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-4 shadow-sm md:p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="flex items-center gap-2 text-base font-semibold text-[var(--app-text)]"><Gauge size={16} className="text-cyan-700 dark:text-cyan-300" />采集器容量摘要</h2>
              <p className="mt-1 text-xs text-[var(--muted-text)]">对比准入上限、已预留和实际观测值。</p>
            </div>
            <label className="flex items-center gap-2 text-xs font-semibold text-[var(--muted-text)]">
              采集器
              <select value={selectedCollectorId} onChange={(event) => setSelectedCollectorId(event.target.value)} disabled={!collectorOptions.length} className="max-w-[240px] rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-1.5 text-xs text-[var(--app-text)] disabled:opacity-50">
                {collectorOptions.map((collector) => <option key={collector.id} value={collector.id}>{collector.label}</option>)}
              </select>
            </label>
          </div>
          {capacityLoading ? (
            <div className="mt-3 flex items-center gap-2 rounded-xl border border-dashed border-[var(--card-border)] px-3 py-7 text-xs text-[var(--muted-text)]"><Loader2 size={14} className="animate-spin" />正在加载容量摘要…</div>
          ) : capacityIssue ? (
            <div role="alert" className={`mt-3 flex items-start gap-2 rounded-xl border px-3 py-3 text-xs ${capacityIssue.forbidden ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-amber-200 bg-amber-50 text-amber-800'}`}>
              {capacityIssue.forbidden ? <ShieldAlert size={14} className="mt-0.5 shrink-0" /> : <AlertTriangle size={14} className="mt-0.5 shrink-0" />}{capacityIssue.message}
            </div>
          ) : capacity ? (
            <CapacityTable capacity={capacity} />
          ) : (
            <div className="mt-3 rounded-xl border border-dashed border-[var(--card-border)] px-4 py-8 text-center">
              {collectorOptions.length ? <Database size={18} className="mx-auto text-[var(--muted-text)]" /> : <Server size={18} className="mx-auto text-[var(--muted-text)]" />}
              <p className="mt-2 text-xs font-semibold text-[var(--app-text)]">{collectorOptions.length ? '暂无容量摘要' : '当前订阅页没有关联采集器'}</p>
              <p className="mt-1 text-xs text-[var(--muted-text)]">{collectorOptions.length ? '选择采集器后查看资源上限、预留和观测值。' : '采集器容量会在订阅关联采集器后展示。'}</p>
            </div>
          )}
        </section>

        <footer className="flex items-center gap-2 px-1 text-xs text-[var(--muted-text)]">
          {failedCount ? <AlertTriangle size={12} className="text-amber-600" /> : <CheckCircle2 size={12} className="text-emerald-600" />}
          页面只呈现控制面返回的期望配置和运行状态，不会向设备下发协议配置。
        </footer>
      </div>

      <div id="telemetry-configuration" hidden={view !== 'configuration'} className="space-y-4">
        <TelemetryControlSetupPanel
          devices={devices}
          profiles={profiles}
          canManage={canManage && !mutationDenied}
          onChanged={refresh}
        />
        <details className="rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-4 shadow-sm md:p-5">
          <summary className="cursor-pointer text-sm font-semibold text-[var(--app-text)]">协议支持范围 <span className="ml-2 text-xs font-normal text-[var(--muted-text)]">{profiles.length} 个协议档</span></summary>
          {isLoading && profiles.length === 0 ? (
            <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3" aria-label="正在加载协议档">
              {[0, 1, 2].map((item) => <div key={item} className="h-28 animate-pulse rounded-xl bg-black/[0.04] dark:bg-white/[0.05]" />)}
            </div>
          ) : profiles.length ? (
            <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {profiles.map((profile) => (
                <article key={profile.id} className="rounded-xl border border-[var(--card-border)] p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0"><p className="truncate text-xs font-extrabold text-[var(--app-text)]">{profileDisplayName(profile)}</p><p className="mt-0.5 text-xs text-[var(--muted-text)]">{displayVendor(profile.vendor)}{profile.platform ? ` · ${profile.platform}` : ''}</p></div>
                    <StatusPill value={profile.support_status} type="support" />
                  </div>
                  <p className="mt-2 text-xs leading-relaxed text-[var(--muted-text)]">{profileScope(profile)}</p>
                  <code className="mt-1 block break-all text-[9px] text-[var(--muted-text)]">ID: {profile.id}</code>
                  {profile.min_interval_seconds != null && <p className="mt-1 text-xs text-[var(--muted-text)]">最小采样周期 {profile.min_interval_seconds} 秒</p>}
                  <OfficialSourceList sources={profile.official_sources} />
                  <EvidenceList paths={profile.paths} />
                </article>
              ))}
            </div>
          ) : (
            <div className="mt-4 rounded-xl border border-dashed border-[var(--card-border)] px-4 py-7 text-center text-xs text-[var(--muted-text)]">
              {loadIssues.some((issue) => issue.source === '协议档') ? '协议档暂不可用，请检查上方错误信息后重试。' : '暂无可用协议档。'}
            </div>
          )}
        </details>
      </div>
    </section>
  );
};

export default TelemetryManagementPage;
