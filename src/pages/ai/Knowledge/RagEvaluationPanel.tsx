import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, CheckCircle2, CircleAlert, Database, Gauge, ListChecks, Play, ShieldCheck } from 'lucide-react';
import { getKnowledgeEvaluation, getKnowledgeExperimentObservability, getKnowledgeGold400FixtureSummary, runKnowledgeEvaluation, type KnowledgeEvaluationReport, type KnowledgeExperimentObservability, type KnowledgeGold400FixtureSummary } from '../../../api/ai';

const metricLabels: Record<string, string> = {
  retrieval_accuracy: '检索准确率',
  citation_accuracy: '引用准确率',
  citation_recall: '引用召回率',
  wrong_vendor_rate: '错误厂商率',
  version_conflict_rate: '版本冲突率',
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '评测请求失败';
}

function percent(value: number | undefined): string {
  return `${((Number(value) || 0) * 100).toFixed(1)}%`;
}

function gateColor(passed: boolean): string {
  return passed ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-rose-200 bg-rose-50 text-rose-700';
}

const observabilityMetricLabels: Record<string, string> = {
  recall_at_5: 'Recall@5',
  recall_at_10: 'Recall@10',
  mrr: 'MRR',
  ndcg: 'NDCG',
  citation_precision: '引用 Precision',
  citation_recall: '引用 Recall',
  wrong_vendor_rate: '错误厂商率',
  feature_pollution_rate: 'Feature 污染率',
  latency_ms: '延迟',
  error_rate: '错误率',
};

const fixtureLabels: Record<string, string> = {
  knowledge_config_reference: '知识配置参考',
  troubleshooting: '故障排查',
  configuration_validation_diagnostic: '配置验证诊断',
  asset_alarm_query: '资产与告警查询',
  intent_clarification_missing_parameter: '意图澄清 / 缺少参数',
  tool_call_dangerous_operation: '工具调用 / 危险操作',
  negative_security_no_match: '安全负例 / 不应命中',
  train: '训练集',
  debug: '调试集',
  hidden: '隐藏集',
  unspecified: '未指定',
  cross_vendor_or_unknown: '跨厂商或未指定',
};

function fixtureBucketLabel(key: string): string {
  return fixtureLabels[key] || key;
}

function formatObservabilityMetric(key: string, value: number | null): string {
  if (value === null || value === undefined) return '未测量';
  if (key.endsWith('_rate') || key.includes('precision') || key.includes('recall') || key === 'mrr' || key === 'ndcg') {
    return `${(value * 100).toFixed(1)}%`;
  }
  if (key.includes('latency')) return `${Number(value).toFixed(1)} ms`;
  return Number(value).toFixed(3);
}

function observabilityStatusLabel(value: string): string {
  return ({ planned: '计划', running: '运行中', completed: '已完成', failed: '失败', cancelled: '已取消', disabled: 'disabled', shadow: 'shadow', active: 'active', degraded: 'degraded', observed: 'observed', timeout: 'timeout' } as Record<string, string>)[value] || value || '未知';
}

export const RagEvaluationPanel: React.FC = () => {
  const [report, setReport] = useState<KnowledgeEvaluationReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const [observability, setObservability] = useState<KnowledgeExperimentObservability | null>(null);
  const [observabilityLoading, setObservabilityLoading] = useState(true);
  const [fixture, setFixture] = useState<KnowledgeGold400FixtureSummary | null>(null);
  const [fixtureLoading, setFixtureLoading] = useState(true);
  const [fixtureError, setFixtureError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setReport(await getKnowledgeEvaluation(true));
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadObservability = useCallback(async () => {
    setObservabilityLoading(true);
    try {
      setObservability(await getKnowledgeExperimentObservability(50));
    } catch {
      // The page remains usable when migration 0202 is not installed yet.
      setObservability(null);
    } finally {
      setObservabilityLoading(false);
    }
  }, []);

  const loadFixture = useCallback(async () => {
    setFixtureLoading(true);
    setFixtureError('');
    try {
      setFixture(await getKnowledgeGold400FixtureSummary());
    } catch (cause) {
      setFixture(null);
      setFixtureError(errorMessage(cause));
    } finally {
      setFixtureLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { void loadObservability(); }, [loadObservability]);
  useEffect(() => { void loadFixture(); }, [loadFixture]);

  const run = async () => {
    setRunning(true);
    setError('');
    try {
      setReport(await runKnowledgeEvaluation());
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setRunning(false);
    }
  };

  const metrics = report?.metrics;
  const metricCards = useMemo(() => (
    metrics ? [
      ['retrieval_accuracy', metrics.retrieval_accuracy, true],
      ['citation_accuracy', metrics.citation_accuracy, true],
      ['citation_recall', metrics.citation_recall, true],
      ['wrong_vendor_rate', metrics.wrong_vendor_rate, false],
      ['version_conflict_rate', metrics.version_conflict_rate, false],
    ] as Array<[string, number, boolean]> : []
  ), [metrics]);

  return (
    <div className="w-full space-y-5 text-slate-900 dark:text-slate-100">
      <section className="rounded-3xl border border-indigo-100 bg-gradient-to-br from-indigo-50 via-white to-violet-50 p-6 shadow-sm dark:border-indigo-900/60 dark:from-indigo-950/40 dark:via-slate-900 dark:to-violet-950/30">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-2 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.18em] text-indigo-600"><Activity className="h-4 w-4" /> RAG Evaluation · KUI-016</div>
            <h1 className="nx-page-title text-slate-900 dark:text-white">固定基线自检</h1>
            <p className="nx-page-description mt-2 max-w-3xl text-slate-600 dark:text-slate-300">用固定夹具问题集回归实体解析、厂商与版本过滤、结果排序和引用规则，适合检索代码变更后的开发测试。</p>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-500 dark:text-slate-400">它不读取当前租户的生产文档，也不测试真实向量模型或线上延迟；执行时使用 PostgreSQL 临时事务，不写入生产数据、不访问外网。</p>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-amber-700 dark:text-amber-300">当前实现仅建议在开发测试环境、没有并发 Copilot 检索时运行。</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-300"><ShieldCheck className="h-4 w-4" /> 租户与权限由服务端绑定</span>
            <button type="button" onClick={() => void run()} disabled={running || loading} className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"><Play className="h-4 w-4" />{running ? '基线自检中…' : '运行基线回归'}</button>
          </div>
        </div>
      </section>

      {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-300">{error}</div>}
      {loading && !report && <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">加载评测状态…</div>}
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-sm font-bold text-slate-900 dark:text-white">实验与 Shadow 观察 · OBS-002</h2><p className="mt-1 text-xs text-slate-500 dark:text-slate-400">只读展示数据集、组件版本、灰度状态、排名差异和质量指标；不展示 Prompt、回答、文档正文或文档 ID。</p></div><span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">PostgreSQL · tenant scoped</span></div>
        {observabilityLoading ? <p className="rounded-xl bg-slate-50 p-5 text-center text-xs text-slate-500 dark:bg-slate-800/70">加载实验摘要…</p> : !observability ? <p className="rounded-xl border border-amber-200 bg-amber-50 p-5 text-center text-xs text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-300">实验持久化依赖尚未就绪；当前基线页面仍可使用。</p> : !observability.runs.length && !observability.rollouts.length && !observability.shadow_observations.length ? <p className="rounded-xl bg-slate-50 p-5 text-center text-xs text-slate-500 dark:bg-slate-800/70">暂无实验或 Shadow 记录；未把空数据解释为通过。</p> : <div className="space-y-4">
          {observability.runs[0] && <div className="grid gap-3 lg:grid-cols-[1fr_1.2fr]"><div className="rounded-xl border border-slate-100 p-4 dark:border-slate-800"><div className="mb-3 flex items-center justify-between gap-2"><h3 className="text-xs font-bold text-slate-700 dark:text-slate-200">最近实验</h3><span className="rounded-full bg-indigo-50 px-2 py-1 text-[10px] font-semibold text-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-300">{observabilityStatusLabel(observability.runs[0].status)}</span></div><dl className="space-y-1.5 text-[11px]"><div className="flex justify-between gap-2"><dt className="text-slate-500">Dataset</dt><dd className="max-w-[70%] truncate text-right font-medium text-slate-800 dark:text-slate-200">{observability.runs[0].dataset_id || '—'}</dd></div><div className="flex justify-between gap-2"><dt className="text-slate-500">Git SHA</dt><dd className="font-mono font-medium text-slate-800 dark:text-slate-200">{observability.runs[0].git_sha || '—'}</dd></div><div className="flex justify-between gap-2"><dt className="text-slate-500">Prompt / Parser</dt><dd className="max-w-[70%] truncate text-right font-medium text-slate-800 dark:text-slate-200">{observability.runs[0].prompt_version || '—'} / {observability.runs[0].parser_version || '—'}</dd></div><div className="flex justify-between gap-2"><dt className="text-slate-500">Embedding</dt><dd className="max-w-[70%] truncate text-right font-medium text-slate-800 dark:text-slate-200">{observability.runs[0].embedding_model || '—'} · {observability.runs[0].embedding_dimensions}d</dd></div><div className="flex justify-between gap-2"><dt className="text-slate-500">Reranker / Provider</dt><dd className="max-w-[70%] truncate text-right font-medium text-slate-800 dark:text-slate-200">{observability.runs[0].reranker_version || '—'} / {observability.runs[0].provider_model || '—'}</dd></div></dl></div><div className="rounded-xl border border-slate-100 p-4 dark:border-slate-800"><h3 className="mb-3 text-xs font-bold text-slate-700 dark:text-slate-200">质量指标</h3><div className="grid grid-cols-2 gap-2 sm:grid-cols-3">{Object.entries(observability.runs[0].metrics || {}).filter(([key]) => observabilityMetricLabels[key]).map(([key, value]) => <div key={key} className="rounded-lg bg-slate-50 p-2.5 dark:bg-slate-800/70"><div className="text-[10px] text-slate-500">{observabilityMetricLabels[key]}</div><div className="mt-1 text-sm font-bold text-slate-800 dark:text-slate-100">{formatObservabilityMetric(key, value)}</div></div>)}</div></div></div>}
          {observability.rollouts.length > 0 && <div><h3 className="mb-2 text-xs font-bold text-slate-700 dark:text-slate-200">灰度状态</h3><div className="grid gap-2 md:grid-cols-2">{observability.rollouts.map((item) => <div key={item.rollout_id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-100 px-3 py-2 text-[11px] dark:border-slate-800"><span className="font-semibold text-slate-700 dark:text-slate-200">{item.component}</span><span className="rounded-full bg-slate-100 px-2 py-0.5 font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">{observabilityStatusLabel(item.mode)} · {item.rollout_percent}%</span><span className={item.kill_switch ? 'font-semibold text-rose-600' : 'text-slate-500'}>{item.kill_switch ? 'Kill Switch ON' : `${item.baseline_version} → ${item.candidate_version}`}</span></div>)}</div></div>}
          {observability.shadow_observations.length > 0 && <div><h3 className="mb-2 text-xs font-bold text-slate-700 dark:text-slate-200">Shadow 排名差异（候选哈希）</h3><div className="grid gap-2 md:grid-cols-2">{observability.shadow_observations.map((item) => <div key={item.observation_id} className="rounded-xl border border-slate-100 p-3 text-[11px] dark:border-slate-800"><div className="flex flex-wrap items-center justify-between gap-2"><span className="font-semibold text-slate-700 dark:text-slate-200">{item.component}</span><span className="rounded-full bg-slate-100 px-2 py-0.5 font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">{observabilityStatusLabel(item.status)}</span></div><div className="mt-2 flex flex-wrap gap-3 text-slate-500"><span>baseline {item.baseline_count}</span><span>candidate {item.candidate_count}</span><span>{item.order_changed ? `变化 ${item.rank_deltas.length} 项` : '顺序未变'}</span><span>{item.candidate_latency_ms == null ? '候选延迟未测量' : `${item.candidate_latency_ms} ms`}</span></div></div>)}</div></div>}
        </div>}
      </section>
      <section aria-labelledby="gold400-fixture-title" className="rounded-2xl border border-amber-200 bg-amber-50/60 p-5 shadow-sm dark:border-amber-900/60 dark:bg-amber-950/20">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="mb-1 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.16em] text-amber-700 dark:text-amber-300"><ListChecks className="h-4 w-4" /> Official Source · 400</div>
            <h2 id="gold400-fixture-title" className="text-sm font-bold text-slate-900 dark:text-white">400 条官方来源自动评测集概览</h2>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-600 dark:text-slate-300">这里可以确认 400 条数据的数量、类别、厂商和 train/debug/hidden 切分。当前策略不要求人工评审；每个 answer 用例必须绑定允许域名下的官方 HTTPS 来源。页面不会下发题目、标准答案、Gold 文档 ID 或文档正文。</p>
          </div>
          <span className="rounded-full border border-amber-300 bg-white px-2.5 py-1 text-[11px] font-semibold text-amber-700 dark:border-amber-800 dark:bg-slate-900 dark:text-amber-300">Official URL-backed · no human review</span>
        </div>
        {fixtureLoading ? <p role="status" className="rounded-xl bg-white/70 p-5 text-center text-xs text-slate-500 dark:bg-slate-900/60 dark:text-slate-300">加载 400 条夹具概览…</p> : fixtureError ? <p role="alert" className="rounded-xl border border-amber-300 bg-white/70 p-5 text-center text-xs text-amber-800 dark:border-amber-800 dark:bg-slate-900/60 dark:text-amber-200">暂时无法读取 400 条测试夹具：{fixtureError}</p> : !fixture ? <p role="status" className="rounded-xl bg-white/70 p-5 text-center text-xs text-slate-500 dark:bg-slate-900/60 dark:text-slate-300">暂无夹具概览。</p> : <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-xl border border-amber-100 bg-white p-4 dark:border-amber-900/50 dark:bg-slate-900"><div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">用例总数</div><div className="mt-1 text-2xl font-bold text-slate-900 dark:text-white">{fixture.case_count}</div><div className="mt-1 text-[11px] text-slate-500">固定测试夹具</div></div>
            <div className="rounded-xl border border-amber-100 bg-white p-4 dark:border-amber-900/50 dark:bg-slate-900"><div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">数据状态</div><div className="mt-1 text-lg font-bold text-slate-900 dark:text-white">{fixture.status}</div><div className="mt-1 truncate text-[11px] text-slate-500" title={fixture.dataset_id}>{fixture.dataset_id}</div></div>
            <div className="rounded-xl border border-amber-100 bg-white p-4 dark:border-amber-900/50 dark:bg-slate-900"><div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">数据库契约</div><div className="mt-1 text-lg font-bold text-slate-900 dark:text-white">{fixture.database}</div><div className="mt-1 text-[11px] text-slate-500">SQLite：{fixture.source_policy.sqlite}</div></div>
            <div className={`rounded-xl border p-4 ${fixture.production_eligible ? 'border-emerald-200 bg-emerald-50 dark:border-emerald-900/60 dark:bg-emerald-950/30' : 'border-rose-200 bg-rose-50 dark:border-rose-900/60 dark:bg-rose-950/30'}`}><div className={`text-[10px] font-semibold uppercase tracking-wide ${fixture.production_eligible ? 'text-emerald-600 dark:text-emerald-300' : 'text-rose-600 dark:text-rose-300'}`}>来源门禁</div><div className={`mt-1 text-lg font-bold ${fixture.production_eligible ? 'text-emerald-700 dark:text-emerald-200' : 'text-rose-700 dark:text-rose-200'}`}>{fixture.production_gate}</div><div className={`mt-1 text-[11px] ${fixture.production_eligible ? 'text-emerald-700/80 dark:text-emerald-300/80' : 'text-rose-700/80 dark:text-rose-300/80'}`}>{fixture.synthetic_data ? '合成数据，不可作为正式来源' : '已绑定官方 URL；仍需看检索质量门禁'}</div></div>
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            {([
              ['按类别', fixture.coverage.categories],
              ['按厂商', fixture.coverage.vendors],
              ['按切分', fixture.coverage.splits],
            ] as Array<[string, KnowledgeGold400FixtureSummary['coverage']['categories']]>).map(([title, items]) => (
              <div key={title} className="rounded-xl border border-amber-100 bg-white p-4 dark:border-amber-900/50 dark:bg-slate-900">
                <h3 className="mb-3 text-xs font-bold text-slate-700 dark:text-slate-200">{title}</h3>
                <ul className="space-y-2 text-xs">
                  {items.map((item) => <li key={item.key} className="flex items-center justify-between gap-3"><span className="truncate text-slate-600 dark:text-slate-300" title={item.key}>{fixtureBucketLabel(item.key)}</span><span className="font-bold text-slate-900 dark:text-white">{item.count}</span></li>)}
                </ul>
              </div>
            ))}
          </div>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-200 bg-white/70 px-3 py-2 text-[11px] text-slate-600 dark:border-amber-900/60 dark:bg-slate-900/60 dark:text-slate-300">
            <span>来源策略：{fixture.source_policy.official_sources} · {fixture.source_policy.source_collection} · PostgreSQL · 外网 {fixture.source_policy.external_network} · secrets {fixture.source_policy.secrets} · 生产数据 {fixture.source_policy.production_data}</span>
            <span className="font-semibold text-amber-700 dark:text-amber-300">人工评审：{fixture.review.human_review_required ? (fixture.review.human_review_ready ? '已就绪' : '仍需完成') : '不要求'}（双审要求 {fixture.review.minimum_double_review_cases} 条）</span>
            <span className="basis-full truncate text-slate-500 dark:text-slate-400" title={`${fixture.collection.source_manifest} · ${fixture.collection.source_manifest_sha256}`}>
              来源清单：{fixture.collection.source_manifest} · SHA-256 {fixture.collection.source_manifest_sha256.slice(0, 12)}… · {fixture.collection.collected_at}
            </span>
          </div>
        </>}
      </section>
      {report && <>
        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          {metricCards.map(([key, value, higherIsBetter]) => {
            const gate = report.gates.find((item) => item.metric === key);
            const passed = gate?.passed ?? true;
            return <article key={key} className={`rounded-2xl border p-4 shadow-sm ${gateColor(passed)}`}><div className="flex items-center justify-between gap-2"><span className="text-[11px] font-bold uppercase tracking-wide">{metricLabels[key]}</span>{passed ? <CheckCircle2 className="h-4 w-4" /> : <CircleAlert className="h-4 w-4" />}</div><div className="mt-2 text-2xl font-bold">{percent(value)}</div><p className="mt-1 text-[11px] opacity-80">{higherIsBetter ? '越高越好' : '越低越好'} · {gate ? `${gate.operator} ${percent(gate.threshold)}` : '待运行'}</p></article>;
          })}
        </section>

        <section className="grid gap-4 lg:grid-cols-[0.8fr_1.2fr]">
          <div className="space-y-4">
            <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900"><div className="mb-3 flex items-center justify-between"><h2 className="text-sm font-bold text-slate-900 dark:text-white">评测执行</h2><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${report.status === 'passed' ? 'bg-emerald-100 text-emerald-700' : report.status === 'failed' ? 'bg-rose-100 text-rose-700' : 'bg-slate-100 text-slate-600'}`}>{report.status === 'not_run' ? '未运行' : report.status === 'passed' ? 'PASS' : 'FAIL'}</span></div><dl className="space-y-2 text-xs"><div className="flex justify-between gap-3"><dt className="text-slate-500">数据集</dt><dd className="font-medium text-slate-800 dark:text-slate-200">{report.baseline_id || 'v1-baseline'}</dd></div><div className="flex justify-between gap-3"><dt className="text-slate-500">数据库</dt><dd className="inline-flex items-center gap-1 font-medium text-slate-800 dark:text-slate-200"><Database className="h-3.5 w-3.5 text-indigo-500" />{report.database}</dd></div><div className="flex justify-between gap-3"><dt className="text-slate-500">用例数</dt><dd className="font-medium text-slate-800 dark:text-slate-200">{report.case_count}</dd></div><div className="flex justify-between gap-3"><dt className="text-slate-500">回滚</dt><dd className="font-medium text-slate-800 dark:text-slate-200">{report.rollback}</dd></div><div className="flex justify-between gap-3"><dt className="text-slate-500">生产写入</dt><dd className="font-medium text-emerald-700 dark:text-emerald-300">{report.production_database_write ? '是' : '否'}</dd></div>{report.duration_ms !== undefined && <div className="flex justify-between gap-3"><dt className="text-slate-500">耗时</dt><dd className="font-medium text-slate-800 dark:text-slate-200">{report.duration_ms.toFixed(0)} ms</dd></div>}</dl></article>
            <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900"><div className="mb-3 flex items-center gap-2"><Gauge className="h-4 w-4 text-indigo-500" /><h2 className="text-sm font-bold text-slate-900 dark:text-white">延迟</h2></div>{metrics ? <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">{Object.entries(metrics.latency_ms).map(([key, value]) => <div key={key} className="rounded-xl bg-slate-50 p-3 dark:bg-slate-800/70"><div className="text-slate-500">{key.toUpperCase()}</div><div className="mt-1 font-bold text-slate-800 dark:text-slate-200">{Number(value).toFixed(2)} ms</div></div>)}</div> : <p className="text-xs text-slate-500">运行后显示 PostgreSQL 评测延迟。</p>}</article>
          </div>
          <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900"><div className="mb-3 flex items-center justify-between gap-3"><h2 className="text-sm font-bold text-slate-900 dark:text-white">基线门禁与用例摘要</h2><span className="text-xs text-slate-500">最多显示 {Math.min(report.cases.length, 200)} 条</span></div>{report.status === 'not_run' ? <div className="rounded-xl bg-slate-50 p-8 text-center text-sm text-slate-500 dark:bg-slate-800/70">尚未运行基线回归，请点击“运行基线回归”。</div> : <><div className="mb-4 grid gap-2 sm:grid-cols-2">{report.gates.map((gate) => <div key={gate.metric} className={`flex items-center justify-between rounded-xl border px-3 py-2 text-xs ${gateColor(gate.passed)}`}><span>{metricLabels[gate.metric] || gate.metric}</span><span className="font-bold">{gate.passed ? '通过' : '未通过'} · {gate.operator} {percent(gate.threshold)}</span></div>)}</div><div className="overflow-x-auto"><table className="w-full min-w-[640px] text-left text-xs"><thead className="sticky top-0 z-10 bg-slate-50 text-slate-500 shadow-sm dark:bg-slate-800/95 dark:text-slate-300"><tr><th className="px-3 py-2 font-semibold">用例</th><th className="px-3 py-2 font-semibold">问题摘要</th><th className="px-3 py-2 font-semibold">检索结果</th><th className="px-3 py-2 font-semibold">引用准确率</th><th className="px-3 py-2 font-semibold">延迟</th></tr></thead><tbody>{report.cases.map((item) => <tr key={item.id} className="border-t border-slate-100 dark:border-slate-800"><td className="px-3 py-2 font-semibold text-slate-800 dark:text-slate-200">{item.id}</td><td className="px-3 py-2 text-slate-500 dark:text-slate-400">固定案例（正文不展示）</td><td className="px-3 py-2">{item.retrieval_correct ? <span className="text-emerald-700 dark:text-emerald-300">通过</span> : <span className="text-rose-700 dark:text-rose-300">未通过</span>}</td><td className="px-3 py-2 text-slate-700 dark:text-slate-200">{percent(item.citation_precision)}</td><td className="px-3 py-2 text-slate-700 dark:text-slate-200">{item.latency_ms.toFixed(2)} ms</td></tr>)}</tbody></table></div></>}</article>
        </section>
      </>}
    </div>
  );
};

export default RagEvaluationPanel;
