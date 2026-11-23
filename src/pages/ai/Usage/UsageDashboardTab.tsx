import { DataTable } from '../../../components/DataTable';
import React, { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Fingerprint,
  RefreshCw,
  ShieldCheck,
  UserRound,
} from 'lucide-react';
import { getAIUsageSummary, getAIAuditLogs, getAIPlatformMetrics, type AIAuditLog, type AIUsageSummary, type AIPlatformMetrics } from '../../../api/ai';
import Pagination from '../../../components/Pagination';
import { useCoreApp } from '../../../contexts/AppDomainContext';
import { ActionButton } from '../../../components/ui/ActionIconButton';
import { EmptyState } from '../../../components/ui/EmptyState';
import { InfoTip } from '../../../components/ui/InfoTip';
import { PageHeader } from '../../../components/ui/PageHeader';
import { Panel, PanelHeader } from '../../../components/ui/Panel';
import { StatusBadge, type StatusTone } from '../../../components/ui/StatusBadge';
import { SummaryBar } from '../../../components/ui/SummaryBar';
import { cn } from '../../../lib/cn';

const sceneLabels: Record<string, string> = {
  provider_test: 'Provider 连通性测试',
  chat: 'AI Copilot 对话',
  natural_query: '自然语言查询',
  command_explain: '命令解释',
  config_explain: '配置分析',
  config_diff: 'Diff 智能分析',
  alarm_analysis: '告警根因诊断',
  troubleshooting: '网络故障诊断',
};

const formatScene = (scene: string, zh: boolean) => sceneLabels[scene] || (zh ? `其他 · ${scene}` : `Other · ${scene}`);

const formatLatency = (latency?: number | null) => {
  if (typeof latency !== 'number' || !Number.isFinite(latency)) return '—';
  return latency >= 1000 ? `${(latency / 1000).toFixed(2)} s` : `${latency} ms`;
};

const formatBytes = (bytes?: number | null) => {
  const value = Number(bytes || 0);
  if (!Number.isFinite(value) || value <= 0) return '0 B';
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  const index = Math.min(units.length - 1, Math.floor(Math.log(value) / Math.log(1024)));
  return `${(value / (1024 ** index)).toFixed(index > 1 ? 2 : 0)} ${units[index]}`;
};

const formatRequestId = (requestId: string) => requestId.length > 20 ? `${requestId.slice(0, 15)}…${requestId.slice(-4)}` : requestId;

interface AuditActor {
  label: string;
  detail: string;
  raw: string;
  kind: 'anonymous' | 'session' | 'named';
}

const getAuditActor = (userId: string | null | undefined, zh: boolean): AuditActor => {
  const raw = String(userId || '').trim();
  if (!raw || raw === 'anonymous') {
    return { label: zh ? '匿名请求' : 'Anonymous request', detail: zh ? '未绑定登录用户' : 'No signed-in user', raw: raw || 'anonymous', kind: 'anonymous' };
  }
  if (raw.startsWith('nxa_user_')) {
    return { label: zh ? '会话用户' : 'Session user', detail: `${zh ? '隐私化标识' : 'Privacy-safe ID'} · ${raw.slice(-8)}`, raw, kind: 'session' };
  }
  return { label: raw, detail: zh ? '已认证用户' : 'Authenticated user', raw, kind: 'named' };
};

const statusMeta = (status: string, zh: boolean): { label: string; tone: StatusTone; icon: typeof CheckCircle2 } => {
  if (status === 'success') return { label: zh ? '成功' : 'Success', tone: 'success', icon: CheckCircle2 };
  if (status === 'blocked') return { label: zh ? '已阻断' : 'Blocked', tone: 'warning', icon: ShieldCheck };
  return { label: zh ? '失败' : 'Failed', tone: 'danger', icon: AlertCircle };
};

interface BreakdownRow {
  provider_id: string;
  model_id: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
}

/**
 * The API returns ``provider_breakdown`` keyed by ``"<provider_id>:<model_id>"``
 * (see AIUsageSummary); older responses used an array of rows.  Accept both,
 * sorted by request count.
 */
const normalizeBreakdown = (raw: unknown): BreakdownRow[] => {
  const toRow = (item: Record<string, unknown>, key?: string): BreakdownRow => {
    const [keyProvider, ...keyModel] = String(key || '').split(':');
    return {
      provider_id: String(item.provider_id ?? keyProvider ?? ''),
      model_id: String(item.model_id ?? keyModel.join(':') ?? ''),
      requests: Number(item.requests || 0),
      input_tokens: Number(item.input_tokens || 0),
      output_tokens: Number(item.output_tokens || 0),
    };
  };
  let rows: BreakdownRow[] = [];
  if (Array.isArray(raw)) {
    rows = raw.filter((item) => item && typeof item === 'object').map((item) => toRow(item as Record<string, unknown>));
  } else if (raw && typeof raw === 'object') {
    rows = Object.entries(raw as Record<string, unknown>)
      .filter(([, item]) => item && typeof item === 'object')
      .map(([key, item]) => toRow(item as Record<string, unknown>, key));
  }
  return rows.sort((left, right) => right.requests - left.requests);
};

/** Flat metric tile used inside a Panel (no gradients, no shadows). */
const MetricTile: React.FC<{ label: React.ReactNode; value: React.ReactNode; hint?: React.ReactNode; className?: string; children?: React.ReactNode }> = ({ label, value, hint, className, children }) => (
  <div className={cn('min-w-0 rounded-lg border border-line bg-surface px-4 py-3', className)}>
    <p className="text-xs text-fg-muted">{label}</p>
    <p className="mt-1 truncate text-xl font-semibold tabular-nums text-fg">{value}</p>
    {children}
    {hint && <p className="mt-1 text-xs text-fg-subtle">{hint}</p>}
  </div>
);

const thClass = 'px-4 py-2.5 text-xs font-medium text-fg-muted';
const tdClass = 'px-4 py-2.5 align-top';

export const UsageDashboardTab: React.FC = () => {
  const { language, showToast } = useCoreApp();
  const zh = language === 'zh';
  const [summary, setSummary] = useState<AIUsageSummary | null>(null);
  const [logs, setLogs] = useState<AIAuditLog[]>([]);
  const [metrics, setMetrics] = useState<AIPlatformMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(10);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [sumData, logData, metricsData] = await Promise.all([
        getAIUsageSummary(),
        getAIAuditLogs(100),
        getAIPlatformMetrics(),
      ]);
      setSummary(sumData);
      setLogs(logData);
      setMetrics(metricsData);
      setCurrentPage(1);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : (zh ? '获取 Token 审计数据失败' : 'Failed to load token audit data');
      setError(message);
      showToast(message, 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchData();
  }, []);

  const paginatedLogs = useMemo(() => {
    const start = (currentPage - 1) * itemsPerPage;
    return logs.slice(start, start + itemsPerPage);
  }, [logs, currentPage, itemsPerPage]);

  const auditExportData = useMemo(() => ({
    columnMarkers: ['include' as const],
    headers: [
      'Request ID',
      zh ? '发起用户' : 'Requester',
      zh ? '业务场景' : 'Scene',
      'Provider / Model',
      zh ? '输入 Token' : 'Input tokens',
      zh ? '输出 Token' : 'Output tokens',
      zh ? '耗时' : 'Latency',
      zh ? '状态' : 'Status',
      zh ? '时间' : 'Time',
    ],
    rows: logs.map((log) => {
      const status = statusMeta(log.status, zh);
      return [
        log.request_id,
        getAuditActor(log.user_id, zh).label,
        formatScene(log.scene, zh),
        [log.provider_id, log.model_id].filter(Boolean).join(' / ') || '—',
        log.input_tokens || 0,
        log.output_tokens || 0,
        formatLatency(log.latency_ms),
        status.label,
        new Date(log.created_at).toLocaleString(),
      ];
    }),
  }), [logs, zh]);

  const successfulCount = metrics?.requests.success || 0;
  const blockedCount = metrics?.requests.blocked || 0;
  const errorCount = metrics?.requests.error || 0;
  const toolCalls = metrics ? Object.values(metrics.tools).reduce((sum, value) => sum + value, 0) : 0;
  const agentResults = metrics ? Object.values(metrics.agents).reduce((sum, value) => sum + value, 0) : 0;
  const budgetPercent = Number(summary?.budget_percent || 0);
  const breakdown = useMemo(() => normalizeBreakdown(summary?.provider_breakdown), [summary]);

  return (
    <div className="w-full space-y-4 pb-8">
      <PageHeader
        title={zh ? 'Token 使用统计与 AI 审计' : 'Token Usage & AI Audit'}
        description={zh ? '每次 AI 请求的用量、延迟、状态和发起方，可追溯到单个请求。' : 'Usage, latency, status, and requester of every AI request, traceable to a single request.'}
        infoLabel={zh ? '数据说明' : 'About this data'}
        info={zh ? '统计来自 AI 网关请求日志与平台指标；成本按模型单价估算，仅供参考。' : 'Figures come from AI gateway request logs and platform metrics; costs are estimates from model prices.'}
        actions={(
          <ActionButton
            type="button"
            icon={RefreshCw}
            iconClassName={loading ? 'animate-spin motion-reduce:animate-none' : undefined}
            size="md"
            onClick={() => void fetchData()}
            disabled={loading}
          >
            {zh ? '刷新数据' : 'Refresh data'}
          </ActionButton>
        )}
      />

      {error && (
        <div role="alert" className="flex items-center justify-between gap-3 rounded-lg border border-line bg-danger-subtle px-4 py-3 text-sm text-danger">
          <span>{error}</span>
          <button type="button" onClick={() => void fetchData()} className="rounded-md bg-surface px-3 py-1.5 text-xs font-medium text-fg hover:bg-surface-muted">
            {zh ? '重试' : 'Retry'}
          </button>
        </div>
      )}

      {(summary || metrics) && (
        <SummaryBar
          label={zh ? '请求概览' : 'Request overview'}
          items={[
            ...(summary ? [{ key: 'total', value: summary.total_requests.toLocaleString(), label: zh ? '总请求' : 'Total requests' }] : []),
            ...(metrics ? [
              { key: 'success', value: successfulCount.toLocaleString(), label: zh ? '成功' : 'Success', tone: 'success' as const },
              { key: 'blocked', value: blockedCount.toLocaleString(), label: zh ? '阻断' : 'Blocked', tone: 'warning' as const },
              { key: 'error', value: errorCount.toLocaleString(), label: zh ? '错误' : 'Errors', tone: 'danger' as const },
              { key: 'tools', value: toolCalls.toLocaleString(), label: zh ? '工具调用' : 'Tool calls' },
              { key: 'agents', value: agentResults.toLocaleString(), label: zh ? 'Agent 结果' : 'Agent results' },
              { key: 'cache', value: zh ? '关闭' : 'Off', label: 'Provider Cache' },
            ] : []),
          ]}
        />
      )}

      {summary && (
        <Panel aria-label={zh ? '用量与成本' : 'Usage and cost'}>
          <PanelHeader title={zh ? '用量与成本' : 'Usage and cost'} description={zh ? '包含成功、阻断和错误请求' : 'Includes success, blocked, and error requests'} />
          <div className="grid grid-cols-2 gap-3 p-4 xl:grid-cols-5">
            <MetricTile label={zh ? '总请求次数' : 'Total requests'} value={summary.total_requests.toLocaleString()} hint={zh ? '包含成功、阻断和错误' : 'Success, blocked, and error requests'} />
            <MetricTile label="Input tokens" value={summary.total_input_tokens.toLocaleString()} hint={zh ? '发送给模型的上下文量' : 'Context sent to models'} />
            <MetricTile label="Output tokens" value={summary.total_output_tokens.toLocaleString()} hint={zh ? '模型返回的内容量' : 'Content returned by models'} />
            <MetricTile label={zh ? '平均延迟' : 'Avg latency'} value={formatLatency(summary.avg_latency_ms)} hint={zh ? '从请求进入网关到完成' : 'Gateway-to-completion time'} />
            <MetricTile
              label={(
                <span className="flex items-center justify-between gap-2">
                  <span>{zh ? '当日预估成本 / 预算' : 'Daily Est. Cost / Budget'}</span>
                  <StatusBadge tone={summary.budget_alert ? 'danger' : 'success'}>{budgetPercent.toFixed(1)}%</StatusBadge>
                </span>
              )}
              value={`$${Number(summary.daily_estimated_cost_usd ?? summary.estimated_cost_usd ?? 0).toFixed(4)}`}
              className={summary.budget_alert ? 'bg-danger-subtle' : undefined}
              hint={zh
                ? `日预算 $${Number(summary.budget_usd || 0).toFixed(2)} · 累计 $${Number(summary.estimated_cost_usd || 0).toFixed(4)}`
                : `Daily budget $${Number(summary.budget_usd || 0).toFixed(2)} · Total $${Number(summary.estimated_cost_usd || 0).toFixed(4)}`}
            >
              <div
                className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-surface-muted"
                role="progressbar"
                aria-label={zh ? '日预算使用率' : 'Daily budget usage'}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(Math.min(100, Math.max(0, budgetPercent)))}
              >
                <div
                  className={cn('h-full rounded-full transition-all', summary.budget_alert ? 'bg-danger' : 'bg-accent')}
                  style={{ width: `${Math.min(100, Math.max(0, budgetPercent))}%` }}
                />
              </div>
            </MetricTile>
          </div>
        </Panel>
      )}

      {breakdown.length > 0 && (
        <Panel aria-label={zh ? '按 Provider / Model 分布' : 'Provider & Model Breakdown'}>
          <PanelHeader
            title={zh ? '按 Provider / Model 分布' : 'Provider & Model Breakdown'}
            actions={<span className="text-xs text-fg-subtle">{breakdown.length} {zh ? '个组合' : 'entries'}</span>}
          />
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] border-collapse text-left text-[13px]">
              <thead className="border-b border-line">
                <tr>
                  <th className={thClass}>Model</th>
                  <th className={thClass}>Provider</th>
                  <th className={cn(thClass, 'text-right')}>{zh ? '请求' : 'Requests'}</th>
                  <th className={cn(thClass, 'text-right')}>Tokens</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {breakdown.slice(0, 8).map((item, idx) => (
                  <tr key={`${item.provider_id}-${item.model_id}-${idx}`} className="hover:bg-accent-subtle">
                    <td className={cn(tdClass, 'max-w-[280px] truncate font-mono text-fg')} title={`${item.provider_id} / ${item.model_id}`}>{item.model_id || 'unknown-model'}</td>
                    <td className={cn(tdClass, 'max-w-[220px] truncate font-mono text-xs text-fg-muted')} title={item.provider_id}>{item.provider_id || 'unknown-provider'}</td>
                    <td className={cn(tdClass, 'text-right tabular-nums text-fg')}>{item.requests.toLocaleString()} {zh ? '次' : 'req'}</td>
                    <td className={cn(tdClass, 'text-right font-mono tabular-nums text-fg')}>{(item.input_tokens + item.output_tokens).toLocaleString()} tok</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {metrics?.database?.backend === 'postgresql' && (
        <Panel aria-label={zh ? 'PostgreSQL 数据库观测' : 'PostgreSQL database observability'}>
          <PanelHeader
            title={zh ? 'PostgreSQL 数据库观测' : 'PostgreSQL database observability'}
            description={zh ? '只读目录指标；不返回 SQL、参数或业务正文' : 'Read-only catalog signals; SQL, parameters, and business payloads are excluded'}
            actions={<StatusBadge tone={metrics.database.status === 'PASS' ? 'success' : 'warning'} dot>{metrics.database.status}</StatusBadge>}
          />
          <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-4">
            <MetricTile
              label={zh ? '缓存命中率' : 'Cache hit rate'}
              value={`${Math.round((metrics.database.cache?.hit_rate || 0) * 100)}%`}
              hint={`${(metrics.database.cache?.hits || 0).toLocaleString()} / ${(metrics.database.cache?.reads || 0).toLocaleString()} ${zh ? '读取' : 'reads'}`}
            />
            <MetricTile
              label={zh ? '慢查询样本' : 'Slow query samples'}
              value={metrics.database.slow_queries?.slow_query_count || 0}
              hint={zh ? `阈值 ${metrics.database.slow_queries?.threshold_ms || 0} ms` : `Threshold ${metrics.database.slow_queries?.threshold_ms || 0} ms`}
            />
            <MetricTile
              label={zh ? '数据库容量' : 'Database size'}
              value={formatBytes(metrics.database.capacity?.database_bytes)}
              hint={`${Math.round((metrics.database.capacity?.usage_ratio || 0) * 100)}% ${zh ? '预算占用' : 'of budget'}`}
            />
            <MetricTile
              label={zh ? '关系膨胀信号' : 'Relation bloat signal'}
              value={metrics.database.relation_stats?.status || '—'}
              hint={zh ? '基于 dead/live tuple 比率' : 'Based on dead/live tuple ratio'}
            />
          </div>
          <p className="border-t border-line px-4 py-2.5 text-xs text-fg-subtle">
            {zh ? '所有指标由 PostgreSQL 只读系统视图计算。' : 'All signals come from read-only PostgreSQL catalog views.'}
          </p>
        </Panel>
      )}

      <Panel aria-label={zh ? '近期 AI 请求审计日志' : 'Recent AI request audit logs'}>
        <PanelHeader
          title={zh ? '近期 AI 请求审计日志' : 'Recent AI request audit logs'}
          description={zh ? `最近加载 ${logs.length} 条记录，按时间倒序排列` : `${logs.length} records loaded, newest first`}
          actions={<StatusBadge>{zh ? `${logs.length} 条` : `${logs.length} records`}</StatusBadge>}
        />
        {loading ? (
          <div className="space-y-2 p-4" aria-busy="true">
            {[0, 1, 2, 3, 4].map((item) => <div key={item} className="h-10 animate-pulse rounded-md bg-surface-muted motion-reduce:animate-none" />)}
          </div>
        ) : logs.length === 0 ? (
          <div className="p-4">
            <EmptyState
              icon={Activity}
              title={zh ? '当前没有审计记录' : 'No audit records yet'}
              description={zh ? '发起 AI 请求后，用量与状态会出现在这里。' : 'Usage and status appear here after AI requests are made.'}
            />
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <DataTable unstyled exportConfig={{ filename: 'ai-usage-audit', language: zh ? 'zh' : 'en', disabled: loading || logs.length === 0, exportData: auditExportData }} className="min-w-[1200px] w-full border-collapse text-left text-[13px]">
                <thead className="border-b border-line">
                  <tr>
                    <th data-export="include" className={thClass}>Request ID</th>
                    <th className={thClass}>
                      <span className="inline-flex items-center gap-1">
                        {zh ? '发起用户' : 'Requester'}
                        <InfoTip label={zh ? '用户列怎么看' : 'How to read the user column'}>
                          {zh
                            ? '“会话用户”表示请求来自已认证会话；右侧 8 位是隐私化内部标识，便于追踪同一请求来源，但不是登录用户名。能直接识别的用户名会直接显示。'
                            : '“Session user” means the request came from an authenticated session. The final 8 characters are a privacy-safe internal identifier for tracing, not the login name. Recognizable usernames are shown directly.'}
                        </InfoTip>
                      </span>
                    </th>
                    <th className={thClass}>{zh ? '业务场景' : 'Scene'}</th>
                    <th className={thClass}>Provider / Model</th>
                    <th className={cn(thClass, 'text-right')}>{zh ? '输入 Token' : 'Input tokens'}</th>
                    <th className={cn(thClass, 'text-right')}>{zh ? '输出 Token' : 'Output tokens'}</th>
                    <th className={cn(thClass, 'text-right')}>{zh ? '耗时' : 'Latency'}</th>
                    <th className={thClass}>{zh ? '状态' : 'Status'}</th>
                    <th className={thClass}>{zh ? '时间' : 'Time'}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {paginatedLogs.map((log) => {
                    const actor = getAuditActor(log.user_id, zh);
                    const status = statusMeta(log.status, zh);
                    const StatusIcon = status.icon;
                    const inputTokens = log.input_tokens || 0;
                    const outputTokens = log.output_tokens || 0;
                    return (
                      <tr key={log.id} className="hover:bg-accent-subtle">
                        <td className={tdClass}>
                          <span data-export-primary className="font-mono font-medium text-accent" title={log.request_id}>{formatRequestId(log.request_id)}</span>
                          <span data-export-ignore className="mt-0.5 block font-mono text-xs text-fg-subtle">{log.id?.slice(-8)}</span>
                        </td>
                        <td className={tdClass}>
                          <div className="flex items-center gap-2.5" title={actor.raw}>
                            <span className={cn('flex h-7 w-7 shrink-0 items-center justify-center rounded-md', actor.kind === 'named' ? 'bg-accent-subtle text-accent' : 'bg-surface-muted text-fg-muted')}>
                              {actor.kind === 'named' ? <UserRound className="h-4 w-4" aria-hidden="true" /> : <Fingerprint className="h-4 w-4" aria-hidden="true" />}
                            </span>
                            <span className="min-w-0">
                              <span data-export-primary className="block font-medium text-fg">{actor.label}</span>
                              <span data-export-ignore className="block font-mono text-xs text-fg-subtle">{actor.detail}</span>
                            </span>
                          </div>
                        </td>
                        <td className={tdClass}><StatusBadge>{formatScene(log.scene, zh)}</StatusBadge></td>
                        <td className={tdClass}>
                          <span className="block font-mono text-xs font-medium text-fg">{log.model_id || '—'}</span>
                          <span className="block font-mono text-xs text-fg-subtle">{log.provider_id || '—'}</span>
                        </td>
                        <td className={cn(tdClass, 'text-right font-mono tabular-nums text-fg')}>{inputTokens.toLocaleString()}</td>
                        <td className={cn(tdClass, 'text-right font-mono tabular-nums text-fg')}>{outputTokens.toLocaleString()}</td>
                        <td className={cn(tdClass, 'text-right font-mono tabular-nums text-fg')}>{formatLatency(log.latency_ms)}</td>
                        <td className={tdClass}>
                          <span data-export-primary>
                            <StatusBadge tone={status.tone}><StatusIcon className="h-3.5 w-3.5" aria-hidden="true" />{status.label}</StatusBadge>
                          </span>
                          {log.error_code && log.status !== 'success' && <span data-export-ignore className="mt-1 block font-mono text-xs text-fg-subtle" title={log.error_message || undefined}>{log.error_code}</span>}
                        </td>
                        <td className={cn(tdClass, 'whitespace-nowrap text-fg-muted')}>{new Date(log.created_at).toLocaleString()}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </DataTable>
            </div>
            <Pagination currentPage={currentPage} totalItems={logs.length} onPageChange={setCurrentPage} itemsPerPage={itemsPerPage} onItemsPerPageChange={(size) => { setItemsPerPage(size); setCurrentPage(1); }} language={language} alwaysVisible />
          </>
        )}
      </Panel>
    </div>
  );
};
