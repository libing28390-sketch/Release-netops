import React, { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Clock3,
  Database,
  Fingerprint,
  Gauge,
  Info,
  RefreshCw,
  ShieldCheck,
  UserRound,
  UsersRound,
  Zap,
} from 'lucide-react';
import { getAIUsageSummary, getAIAuditLogs, getAIPlatformMetrics, type AIAuditLog, type AIUsageSummary, type AIPlatformMetrics } from '../../../api/ai';
import Pagination from '../../../components/Pagination';
import { useCoreApp } from '../../../contexts/AppDomainContext';

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

const statusMeta = (status: string, zh: boolean) => {
  if (status === 'success') return { label: zh ? '成功' : 'Success', className: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300', icon: CheckCircle2 };
  if (status === 'blocked') return { label: zh ? '已阻断' : 'Blocked', className: 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300', icon: ShieldCheck };
  return { label: zh ? '失败' : 'Failed', className: 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300', icon: AlertCircle };
};

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

  const successfulCount = metrics?.requests.success || 0;
  const blockedCount = metrics?.requests.blocked || 0;
  const errorCount = metrics?.requests.error || 0;

  return (
    <div className="mx-auto w-full max-w-[1500px] space-y-5 pb-8">
      <section className="relative overflow-hidden rounded-[26px] border border-indigo-100/80 bg-gradient-to-br from-white via-indigo-50/70 to-cyan-100/60 px-5 py-6 shadow-sm shadow-indigo-100/50 dark:border-indigo-900/60 dark:from-slate-900 dark:via-indigo-950/40 dark:to-slate-900 dark:shadow-none sm:px-7 sm:py-7">
        <div className="pointer-events-none absolute -right-20 -top-24 h-64 w-64 rounded-full bg-cyan-300/20 blur-3xl dark:bg-cyan-500/10" />
        <div className="relative flex flex-col justify-between gap-6 xl:flex-row xl:items-center">
          <div className="max-w-3xl">
            <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-indigo-200/80 bg-white/70 px-3 py-1 text-[11px] font-bold uppercase tracking-[0.18em] text-indigo-600 dark:border-indigo-800 dark:bg-indigo-950/50 dark:text-indigo-300"><Activity className="h-3.5 w-3.5" />{zh ? 'AI 运营 · 用量与审计' : 'AI Operations · Usage & Audit'}</div>
            <h2 className="nx-page-title flex items-center gap-3 text-slate-950 dark:text-white"><span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-indigo-600 text-white shadow-lg shadow-indigo-600/25"><Activity className="h-6 w-6" /></span>{zh ? 'Token 使用统计与 AI 审计' : 'Token Usage & AI Audit'}</h2>
            <p className="nx-page-description mt-3 max-w-2xl text-slate-600 dark:text-slate-300">{zh ? '把每次 AI 请求的用量、延迟、状态和发起方放在同一个可追溯视图中。用户列会区分登录用户、会话用户和匿名请求。' : 'Track usage, latency, status, and request actors in one auditable view. The user column distinguishes signed-in, session, and anonymous requests.'}</p>
          </div>
          <button type="button" onClick={() => void fetchData()} disabled={loading} className="inline-flex items-center gap-2 self-start rounded-xl border border-white/90 bg-white/80 px-3.5 py-2.5 text-sm font-semibold text-slate-600 shadow-sm transition hover:border-indigo-200 hover:bg-white hover:text-indigo-600 disabled:cursor-wait disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-300 dark:hover:border-indigo-700 dark:hover:text-indigo-300 xl:self-center"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />{zh ? '刷新数据' : 'Refresh data'}</button>
        </div>
      </section>

      {error && <div role="alert" className="flex items-center justify-between gap-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/70 dark:bg-rose-950/30 dark:text-rose-300"><span>{error}</span><button type="button" onClick={() => void fetchData()} className="rounded-lg bg-white/80 px-3 py-1.5 text-xs font-semibold dark:bg-rose-900/30">{zh ? '重试' : 'Retry'}</button></div>}

      {summary && (
        <section className="grid grid-cols-2 gap-3 xl:grid-cols-4">
          <div className="rounded-2xl border border-slate-200/80 bg-white/90 p-4 shadow-sm shadow-slate-200/40 dark:border-slate-800 dark:bg-slate-900/80 dark:shadow-none"><div className="flex items-start justify-between"><div><p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">{zh ? '总请求次数' : 'Total requests'}</p><p className="mt-2 text-2xl font-bold text-slate-900 dark:text-white">{summary.total_requests.toLocaleString()}</p></div><span className="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-50 text-amber-600 dark:bg-amber-500/10 dark:text-amber-300"><Zap className="h-4 w-4" /></span></div><p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{zh ? '包含成功、阻断和错误' : 'Success, blocked, and error requests'}</p></div>
          <div className="rounded-2xl border border-slate-200/80 bg-white/90 p-4 shadow-sm shadow-slate-200/40 dark:border-slate-800 dark:bg-slate-900/80 dark:shadow-none"><div className="flex items-start justify-between"><div><p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">Input tokens</p><p className="mt-2 text-2xl font-bold text-slate-900 dark:text-white">{summary.total_input_tokens.toLocaleString()}</p></div><span className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-300"><Activity className="h-4 w-4" /></span></div><p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{zh ? '发送给模型的上下文量' : 'Context sent to models'}</p></div>
          <div className="rounded-2xl border border-slate-200/80 bg-white/90 p-4 shadow-sm shadow-slate-200/40 dark:border-slate-800 dark:bg-slate-900/80 dark:shadow-none"><div className="flex items-start justify-between"><div><p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">Output tokens</p><p className="mt-2 text-2xl font-bold text-slate-900 dark:text-white">{summary.total_output_tokens.toLocaleString()}</p></div><span className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-300"><Activity className="h-4 w-4" /></span></div><p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{zh ? '模型返回的内容量' : 'Content returned by models'}</p></div>
          <div className="rounded-2xl border border-slate-200/80 bg-white/90 p-4 shadow-sm shadow-slate-200/40 dark:border-slate-800 dark:bg-slate-900/80 dark:shadow-none"><div className="flex items-start justify-between"><div><p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">{zh ? '平均延迟' : 'Avg latency'}</p><p className="mt-2 text-2xl font-bold text-slate-900 dark:text-white">{formatLatency(summary.avg_latency_ms)}</p></div><span className="flex h-9 w-9 items-center justify-center rounded-xl bg-cyan-50 text-cyan-600 dark:bg-cyan-500/10 dark:text-cyan-300"><Clock3 className="h-4 w-4" /></span></div><p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{zh ? '从请求进入网关到完成' : 'Gateway-to-completion time'}</p></div>
        </section>
      )}

      {metrics && <section className="grid grid-cols-2 gap-3 xl:grid-cols-4"><div className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900"><p className="text-xs font-semibold text-slate-400">{zh ? '网关请求状态' : 'Gateway status'}</p><p className="mt-2 text-lg font-bold text-slate-900 dark:text-white"><span className="text-emerald-600">{successfulCount}</span><span className="mx-1 text-slate-300">/</span><span className="text-amber-600">{blockedCount}</span><span className="mx-1 text-slate-300">/</span><span className="text-rose-600">{errorCount}</span></p><p className="mt-1 text-[11px] text-slate-400">{zh ? '成功 / 阻断 / 错误' : 'Success / blocked / error'}</p></div><div className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900"><p className="text-xs font-semibold text-slate-400">{zh ? '工具调用' : 'Tool calls'}</p><p className="mt-2 text-lg font-bold text-slate-900 dark:text-white">{Object.values(metrics.tools).reduce((sum, value) => sum + value, 0)}</p><p className="mt-1 text-[11px] text-slate-400">{zh ? '受控只读工具执行次数' : 'Controlled read-only executions'}</p></div><div className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900"><p className="text-xs font-semibold text-slate-400">{zh ? 'Agent 结果' : 'Agent results'}</p><p className="mt-2 text-lg font-bold text-slate-900 dark:text-white">{Object.values(metrics.agents).reduce((sum, value) => sum + value, 0)}</p><p className="mt-1 text-[11px] text-slate-400">{zh ? 'Agent 执行结果数' : 'Agent execution results'}</p></div><div className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900"><p className="text-xs font-semibold text-slate-400">Provider Cache</p><p className="mt-2 text-lg font-bold text-slate-900 dark:text-white">{zh ? '默认关闭' : 'Off by default'}</p><p className="mt-1 text-[11px] text-slate-400">{zh ? '避免跨请求复用敏感上下文' : 'Avoid cross-request context reuse'}</p></div></section>}

      {metrics?.database?.backend === 'postgresql' && <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-2"><span className="flex h-9 w-9 items-center justify-center rounded-xl bg-cyan-50 text-cyan-600 dark:bg-cyan-500/10 dark:text-cyan-300"><Database className="h-4 w-4" /></span><div><h3 className="text-sm font-bold text-slate-900 dark:text-white">{zh ? 'PostgreSQL 数据库观测' : 'PostgreSQL database observability'}</h3><p className="text-[11px] text-slate-500 dark:text-slate-400">{zh ? '只读目录指标；不返回 SQL、参数或业务正文' : 'Read-only catalog signals; SQL, parameters, and business payloads are excluded'}</p></div></div><span className={`rounded-full px-2.5 py-1 text-[10px] font-bold ${metrics.database.status === 'PASS' ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300' : 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300'}`}>{metrics.database.status}</span></div>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-950/50"><p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-slate-400">{zh ? '缓存命中率' : 'Cache hit rate'}</p><p className="mt-1 text-lg font-bold text-slate-900 dark:text-white">{Math.round((metrics.database.cache?.hit_rate || 0) * 100)}%</p><p className="text-[10px] text-slate-500">{(metrics.database.cache?.hits || 0).toLocaleString()} / {(metrics.database.cache?.reads || 0).toLocaleString()} {zh ? '读取' : 'reads'}</p></div>
          <div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-950/50"><p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-slate-400">{zh ? '慢查询样本' : 'Slow query samples'}</p><p className="mt-1 text-lg font-bold text-slate-900 dark:text-white">{metrics.database.slow_queries?.slow_query_count || 0}</p><p className="text-[10px] text-slate-500">{zh ? `阈值 ${metrics.database.slow_queries?.threshold_ms || 0} ms` : `Threshold ${metrics.database.slow_queries?.threshold_ms || 0} ms`}</p></div>
          <div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-950/50"><p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-slate-400">{zh ? '数据库容量' : 'Database size'}</p><p className="mt-1 text-lg font-bold text-slate-900 dark:text-white">{formatBytes(metrics.database.capacity?.database_bytes)}</p><p className="text-[10px] text-slate-500">{Math.round((metrics.database.capacity?.usage_ratio || 0) * 100)}% {zh ? '预算占用' : 'of budget'}</p></div>
          <div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-950/50"><p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-slate-400">{zh ? '关系膨胀信号' : 'Relation bloat signal'}</p><p className="mt-1 text-lg font-bold text-slate-900 dark:text-white">{metrics.database.relation_stats?.status || '—'}</p><p className="text-[10px] text-slate-500">{zh ? '基于 dead/live tuple 比率' : 'Based on dead/live tuple ratio'}</p></div>
        </div>
        <div className="flex items-center gap-2 text-[10px] text-slate-500 dark:text-slate-400"><Gauge className="h-3.5 w-3.5" />{zh ? '所有指标由 PostgreSQL 只读系统视图计算；SQLite 不作为生产观测证据。' : 'All signals come from read-only PostgreSQL catalog views; SQLite is not production evidence.'}</div>
      </section>}

      <section className="flex flex-col gap-3 rounded-2xl border border-indigo-100 bg-indigo-50/60 px-4 py-4 dark:border-indigo-900/70 dark:bg-indigo-950/20 sm:flex-row sm:items-start sm:px-5"><span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-white shadow-md shadow-indigo-600/20"><Info className="h-4 w-4" /></span><div><h3 className="text-sm font-bold text-indigo-950 dark:text-indigo-100">{zh ? '用户列怎么看？' : 'How to read the user column'}</h3><p className="mt-1.5 text-xs leading-5 text-indigo-900/70 dark:text-indigo-200/70">{zh ? '“会话用户”表示请求来自已认证会话；右侧 8 位是隐私化内部标识，便于追踪同一请求来源，但不是登录用户名。能直接识别的用户名会直接显示。' : '“Session user” means the request came from an authenticated session. The final 8 characters are a privacy-safe internal identifier for tracing, not the login name. Recognizable usernames are shown directly.'}</p></div></section>

      <section className="space-y-4">
        <div className="flex items-center justify-between gap-3"><div><h3 className="text-lg font-bold text-slate-900 dark:text-white">{zh ? '近期 AI 请求审计日志' : 'Recent AI request audit logs'}</h3><p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{zh ? `最近加载 ${logs.length} 条记录，按时间倒序排列` : `${logs.length} records loaded, newest first`}</p></div><span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1.5 text-[11px] font-semibold text-slate-500 dark:bg-slate-800 dark:text-slate-400"><UsersRound className="h-3.5 w-3.5" />{zh ? `${logs.length} 条` : `${logs.length} records`}</span></div>
        {loading ? <div className="space-y-2 rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">{[0, 1, 2, 3, 4].map((item) => <div key={item} className="h-12 animate-pulse rounded-xl bg-slate-100 dark:bg-slate-800" />)}</div> : logs.length === 0 ? <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-14 text-center text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-400"><Activity className="mx-auto mb-3 h-8 w-8 opacity-40" />{zh ? '当前没有审计记录' : 'No audit records yet'}</div> : <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900"><div className="overflow-x-auto"><table className="min-w-[980px] w-full border-collapse text-left text-xs"><thead className="border-b border-slate-200 bg-slate-50 text-slate-500 dark:border-slate-800 dark:bg-slate-950/60 dark:text-slate-400"><tr><th className="px-4 py-3 font-semibold">Request ID</th><th className="px-4 py-3 font-semibold">{zh ? '发起用户' : 'Requester'}</th><th className="px-4 py-3 font-semibold">{zh ? '业务场景' : 'Scene'}</th><th className="px-4 py-3 font-semibold">{zh ? 'Token 用量' : 'Tokens'}</th><th className="px-4 py-3 font-semibold">{zh ? '耗时' : 'Latency'}</th><th className="px-4 py-3 font-semibold">{zh ? '状态' : 'Status'}</th><th className="px-4 py-3 font-semibold">{zh ? '时间' : 'Time'}</th></tr></thead><tbody className="divide-y divide-slate-100 dark:divide-slate-800">{paginatedLogs.map((log) => { const actor = getAuditActor(log.user_id, zh); const status = statusMeta(log.status, zh); const StatusIcon = status.icon; const inputTokens = log.input_tokens || 0; const outputTokens = log.output_tokens || 0; return <tr key={log.id} className="transition hover:bg-slate-50/80 dark:hover:bg-slate-800/40"><td className="px-4 py-3"><span className="font-mono font-semibold text-indigo-600 dark:text-indigo-300" title={log.request_id}>{formatRequestId(log.request_id)}</span><span className="mt-0.5 block font-mono text-[10px] text-slate-400">{log.id?.slice(-8)}</span></td><td className="px-4 py-3"><div className="flex items-center gap-2.5" title={actor.raw}><span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-xl ${actor.kind === 'named' ? 'bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-300' : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400'}`}>{actor.kind === 'named' ? <UserRound className="h-4 w-4" /> : <Fingerprint className="h-4 w-4" />}</span><span className="min-w-0"><span className="block font-semibold text-slate-800 dark:text-slate-100">{actor.label}</span><span className="block font-mono text-[10px] text-slate-400">{actor.detail}</span></span></div></td><td className="px-4 py-3"><span className="inline-flex rounded-lg bg-slate-100 px-2.5 py-1 font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">{formatScene(log.scene, zh)}</span></td><td className="px-4 py-3"><div className="font-mono font-semibold text-slate-700 dark:text-slate-200">{inputTokens.toLocaleString()} <span className="text-slate-300">/</span> {outputTokens.toLocaleString()}</div><div className="mt-0.5 text-[10px] text-slate-400">{zh ? '输入 / 输出' : 'in / out'}</div></td><td className="px-4 py-3 font-mono text-slate-600 dark:text-slate-300">{formatLatency(log.latency_ms)}</td><td className="px-4 py-3"><span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-semibold ${status.className}`}><StatusIcon className="h-3.5 w-3.5" />{status.label}</span>{log.error_code && log.status !== 'success' && <span className="mt-1 block font-mono text-[10px] text-slate-400" title={log.error_message || undefined}>{log.error_code}</span>}</td><td className="whitespace-nowrap px-4 py-3 text-slate-500 dark:text-slate-400">{new Date(log.created_at).toLocaleString()}</td></tr>; })}</tbody></table></div><Pagination currentPage={currentPage} totalItems={logs.length} onPageChange={setCurrentPage} itemsPerPage={itemsPerPage} onItemsPerPageChange={(size) => { setItemsPerPage(size); setCurrentPage(1); }} language={language} alwaysVisible /></div>}
      </section>
    </div>
  );
};
