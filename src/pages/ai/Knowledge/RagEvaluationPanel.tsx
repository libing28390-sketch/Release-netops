import { DataTable } from '../../../components/DataTable';
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, CheckCircle2, CircleAlert, Database, Gauge, ListChecks, Play, ShieldCheck } from 'lucide-react';
import { getKnowledgeEvaluation, getKnowledgeExperimentObservability, getKnowledgeGold400FixtureSummary, runKnowledgeEvaluation, type KnowledgeEvaluationReport, type KnowledgeExperimentObservability, type KnowledgeGold400FixtureSummary } from '../../../api/ai';
import { PageHeader } from '../../../components/ui/PageHeader';
import { Panel, PanelHeader } from '../../../components/ui/Panel';
import { EmptyState } from '../../../components/ui/EmptyState';
import { StatusBadge } from '../../../components/ui/StatusBadge';

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
  return passed ? 'border-success/30 bg-success-subtle text-success' : 'border-danger/30 bg-danger-subtle text-danger';
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
    <div className="w-full space-y-4 text-fg">
      <PageHeader
        title={<span className="inline-flex items-center gap-2"><Activity className="h-5 w-5 text-accent" aria-hidden="true" />固定基线自检</span>}
        description="用固定夹具问题集回归实体解析、厂商与版本过滤、结果排序和引用规则，适合检索代码变更后的开发测试。"
        info="它不读取当前租户的生产文档，也不测试真实向量模型或线上延迟；执行时使用 PostgreSQL 临时事务，不写入生产数据、不访问外网。"
        infoLabel="基线自检说明"
        actions={(
          <>
            <StatusBadge tone="success"><ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />租户与权限由服务端绑定</StatusBadge>
            <button type="button" onClick={() => void run()} disabled={running || loading} className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"><Play className="h-4 w-4" aria-hidden="true" />{running ? '基线自检中…' : '运行基线回归'}</button>
          </>
        )}
      />
      <p className="text-xs leading-5 text-warning">当前实现仅建议在开发测试环境、没有并发 Copilot 检索时运行。</p>

      {error && <div role="alert" className="rounded-xl border border-danger/30 bg-danger-subtle px-4 py-3 text-sm text-danger ">{error}</div>}
      {loading && !report && <Panel className="p-8 text-center text-sm text-fg-muted">加载评测状态…</Panel>}
      <Panel aria-label="实验与 Shadow 观察">
        <PanelHeader
          title="实验与 Shadow 观察 · OBS-002"
          description="只读展示数据集、组件版本、灰度状态、排名差异和质量指标；不展示 Prompt、回答、文档正文或文档 ID。"
          actions={<StatusBadge mono>PostgreSQL · tenant scoped</StatusBadge>}
        />
        <div className="p-5">
        {observabilityLoading ? <p className="rounded-xl bg-surface-muted p-5 text-center text-xs text-fg-muted ">加载实验摘要…</p> : !observability ? <p className="rounded-xl border border-warning/30 bg-warning-subtle p-5 text-center text-xs text-warning ">实验持久化依赖尚未就绪；当前基线页面仍可使用。</p> : !observability.runs.length && !observability.rollouts.length && !observability.shadow_observations.length ? <EmptyState className="py-8" icon={Activity} title="暂无实验或 Shadow 记录" description="未把空数据解释为通过。" /> : <div className="space-y-4">
          {observability.runs[0] && <div className="grid gap-3 lg:grid-cols-[1fr_1.2fr]"><div className="rounded-xl border border-line p-4 "><div className="mb-3 flex items-center justify-between gap-2"><h3 className="text-xs font-bold text-fg ">最近实验</h3><StatusBadge tone="accent">{observabilityStatusLabel(observability.runs[0].status)}</StatusBadge></div><dl className="space-y-1.5 text-[11px]"><div className="flex justify-between gap-2"><dt className="text-fg-muted">Dataset</dt><dd className="max-w-[70%] truncate text-right font-medium text-fg ">{observability.runs[0].dataset_id || '—'}</dd></div><div className="flex justify-between gap-2"><dt className="text-fg-muted">Git SHA</dt><dd className="font-mono font-medium text-fg ">{observability.runs[0].git_sha || '—'}</dd></div><div className="flex justify-between gap-2"><dt className="text-fg-muted">Prompt / Parser</dt><dd className="max-w-[70%] truncate text-right font-medium text-fg ">{observability.runs[0].prompt_version || '—'} / {observability.runs[0].parser_version || '—'}</dd></div><div className="flex justify-between gap-2"><dt className="text-fg-muted">Embedding</dt><dd className="max-w-[70%] truncate text-right font-medium text-fg ">{observability.runs[0].embedding_model || '—'} · {observability.runs[0].embedding_dimensions}d</dd></div><div className="flex justify-between gap-2"><dt className="text-fg-muted">Reranker / Provider</dt><dd className="max-w-[70%] truncate text-right font-medium text-fg ">{observability.runs[0].reranker_version || '—'} / {observability.runs[0].provider_model || '—'}</dd></div></dl></div><div className="rounded-xl border border-line p-4 "><h3 className="mb-3 text-xs font-bold text-fg ">质量指标</h3><div className="grid grid-cols-2 gap-2 sm:grid-cols-3">{Object.entries(observability.runs[0].metrics || {}).filter(([key]) => observabilityMetricLabels[key]).map(([key, value]) => <div key={key} className="rounded-lg bg-surface-muted p-2.5 "><div className="text-xs text-fg-muted">{observabilityMetricLabels[key]}</div><div className="mt-1 text-sm font-bold text-fg ">{formatObservabilityMetric(key, value)}</div></div>)}</div></div></div>}
          {observability.rollouts.length > 0 && <div><h3 className="mb-2 text-xs font-bold text-fg ">灰度状态</h3><div className="grid gap-2 md:grid-cols-2">{observability.rollouts.map((item) => <div key={item.rollout_id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-line px-3 py-2 text-[11px] "><span className="font-semibold text-fg ">{item.component}</span><StatusBadge>{observabilityStatusLabel(item.mode)} · {item.rollout_percent}%</StatusBadge><span className={item.kill_switch ? 'font-semibold text-danger' : 'text-fg-muted'}>{item.kill_switch ? 'Kill Switch ON' : `${item.baseline_version} → ${item.candidate_version}`}</span></div>)}</div></div>}
          {observability.shadow_observations.length > 0 && <div><h3 className="mb-2 text-xs font-bold text-fg ">Shadow 排名差异（候选哈希）</h3><div className="grid gap-2 md:grid-cols-2">{observability.shadow_observations.map((item) => <div key={item.observation_id} className="rounded-xl border border-line p-3 text-[11px] "><div className="flex flex-wrap items-center justify-between gap-2"><span className="font-semibold text-fg ">{item.component}</span><StatusBadge>{observabilityStatusLabel(item.status)}</StatusBadge></div><div className="mt-2 flex flex-wrap gap-3 text-fg-muted"><span>baseline {item.baseline_count}</span><span>candidate {item.candidate_count}</span><span>{item.order_changed ? `变化 ${item.rank_deltas.length} 项` : '顺序未变'}</span><span>{item.candidate_latency_ms == null ? '候选延迟未测量' : `${item.candidate_latency_ms} ms`}</span></div></div>)}</div></div>}
        </div>}
        </div>
      </Panel>
      <Panel aria-labelledby="gold400-fixture-title">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-3">
          <div className="min-w-0">
            <h3 id="gold400-fixture-title" className="flex items-center gap-2 text-base font-semibold text-fg"><ListChecks className="h-4 w-4 text-accent" aria-hidden="true" />400 条官方来源自动评测集概览</h3>
            <p className="mt-0.5 max-w-3xl text-xs leading-5 text-fg-muted">这里可以确认 400 条数据的数量、类别、厂商和 train/debug/hidden 切分。当前策略不要求人工评审；每个 answer 用例必须绑定允许域名下的官方 HTTPS 来源。页面不会下发题目、标准答案、Gold 文档 ID 或文档正文。</p>
          </div>
          <StatusBadge tone="warning">Official URL-backed · no human review</StatusBadge>
        </div>
        <div className="p-5">
        {fixtureLoading ? <p role="status" className="rounded-lg bg-surface-muted p-5 text-center text-xs text-fg-muted">加载 400 条夹具概览…</p> : fixtureError ? <p role="alert" className="rounded-lg border border-warning/30 bg-warning-subtle p-5 text-center text-xs text-warning">暂时无法读取 400 条测试夹具：{fixtureError}</p> : !fixture ? <p role="status" className="rounded-lg bg-surface-muted p-5 text-center text-xs text-fg-muted">暂无夹具概览。</p> : <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-lg border border-line p-4"><div className="text-xs font-semibold uppercase tracking-wide text-fg-muted">用例总数</div><div className="mt-1 text-2xl font-bold text-fg ">{fixture.case_count}</div><div className="mt-1 text-[11px] text-fg-muted">固定测试夹具</div></div>
            <div className="rounded-lg border border-line p-4"><div className="text-xs font-semibold uppercase tracking-wide text-fg-muted">数据状态</div><div className="mt-1 text-lg font-bold text-fg ">{fixture.status}</div><div className="mt-1 truncate text-[11px] text-fg-muted" title={fixture.dataset_id}>{fixture.dataset_id}</div></div>
            <div className="rounded-lg border border-line p-4"><div className="text-xs font-semibold uppercase tracking-wide text-fg-muted">数据库</div><div className="mt-1 text-lg font-bold text-fg ">{fixture.database}</div></div>
            <div className={`rounded-xl border p-4 ${fixture.production_eligible ? 'border-success/30 bg-success-subtle ' : 'border-danger/30 bg-danger-subtle '}`}><div className={`text-xs font-semibold uppercase tracking-wide ${fixture.production_eligible ? 'text-success ' : 'text-danger '}`}>来源门禁</div><div className={`mt-1 text-lg font-bold ${fixture.production_eligible ? 'text-success ' : 'text-danger '}`}>{fixture.production_gate}</div><div className={`mt-1 text-[11px] ${fixture.production_eligible ? 'text-success ' : 'text-danger '}`}>{fixture.synthetic_data ? '合成数据，不可作为正式来源' : '已绑定官方 URL；仍需看检索质量门禁'}</div></div>
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            {([
              ['按类别', fixture.coverage.categories],
              ['按厂商', fixture.coverage.vendors],
              ['按切分', fixture.coverage.splits],
            ] as Array<[string, KnowledgeGold400FixtureSummary['coverage']['categories']]>).map(([title, items]) => (
              <div key={title} className="rounded-lg border border-line p-4">
                <h3 className="mb-3 text-xs font-bold text-fg ">{title}</h3>
                <ul className="space-y-2 text-xs">
                  {items.map((item) => <li key={item.key} className="flex items-center justify-between gap-3"><span className="truncate text-fg-muted " title={item.key}>{fixtureBucketLabel(item.key)}</span><span className="font-bold text-fg ">{item.count}</span></li>)}
                </ul>
              </div>
            ))}
          </div>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line bg-surface-muted px-3 py-2 text-xs text-fg-muted">
            <span>来源策略：{fixture.source_policy.official_sources} · {fixture.source_policy.source_collection} · PostgreSQL · 外网 {fixture.source_policy.external_network} · secrets {fixture.source_policy.secrets} · 生产数据 {fixture.source_policy.production_data}</span>
            <span className="font-semibold text-fg">人工评审：{fixture.review.human_review_required ? (fixture.review.human_review_ready ? '已就绪' : '仍需完成') : '不要求'}（双审要求 {fixture.review.minimum_double_review_cases} 条）</span>
            <span className="basis-full truncate text-fg-muted " title={`${fixture.collection.source_manifest} · ${fixture.collection.source_manifest_sha256}`}>
              来源清单：{fixture.collection.source_manifest} · SHA-256 {fixture.collection.source_manifest_sha256.slice(0, 12)}… · {fixture.collection.collected_at}
            </span>
          </div>
        </>}
        </div>
      </Panel>
      {report && <>
        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          {metricCards.map(([key, value, higherIsBetter]) => {
            const gate = report.gates.find((item) => item.metric === key);
            const passed = gate?.passed ?? true;
            return <article key={key} className={`rounded-xl border p-4 ${gateColor(passed)}`}><div className="flex items-center justify-between gap-2"><span className="text-[11px] font-bold uppercase tracking-wide">{metricLabels[key]}</span>{passed ? <CheckCircle2 className="h-4 w-4" /> : <CircleAlert className="h-4 w-4" />}</div><div className="mt-2 text-2xl font-bold">{percent(value)}</div><p className="mt-1 text-[11px] opacity-80">{higherIsBetter ? '越高越好' : '越低越好'} · {gate ? `${gate.operator} ${percent(gate.threshold)}` : '待运行'}</p></article>;
          })}
        </section>

        <section className="grid gap-4 lg:grid-cols-[0.8fr_1.2fr]">
          <div className="space-y-4">
            <Panel as="div" className="p-5"><div className="mb-3 flex items-center justify-between"><h2 className="text-base font-semibold text-fg">评测执行</h2><StatusBadge dot tone={report.status === 'passed' ? 'success' : report.status === 'failed' ? 'danger' : 'neutral'}>{report.status === 'not_run' ? '未运行' : report.status === 'passed' ? 'PASS' : 'FAIL'}</StatusBadge></div><dl className="space-y-2 text-xs"><div className="flex justify-between gap-3"><dt className="text-fg-muted">数据集</dt><dd className="font-medium text-fg ">{report.baseline_id || 'v1-baseline'}</dd></div><div className="flex justify-between gap-3"><dt className="text-fg-muted">数据库</dt><dd className="inline-flex items-center gap-1 font-medium text-fg "><Database className="h-3.5 w-3.5 text-accent" />{report.database}</dd></div><div className="flex justify-between gap-3"><dt className="text-fg-muted">用例数</dt><dd className="font-medium text-fg ">{report.case_count}</dd></div><div className="flex justify-between gap-3"><dt className="text-fg-muted">回滚</dt><dd className="font-medium text-fg ">{report.rollback}</dd></div><div className="flex justify-between gap-3"><dt className="text-fg-muted">生产写入</dt><dd className="font-medium text-success ">{report.production_database_write ? '是' : '否'}</dd></div>{report.duration_ms !== undefined && <div className="flex justify-between gap-3"><dt className="text-fg-muted">耗时</dt><dd className="font-medium text-fg ">{report.duration_ms.toFixed(0)} ms</dd></div>}</dl></Panel>
            <Panel as="div" className="p-5"><div className="mb-3 flex items-center gap-2"><Gauge className="h-4 w-4 text-accent" aria-hidden="true" /><h2 className="text-base font-semibold text-fg">延迟</h2></div>{metrics ? <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">{Object.entries(metrics.latency_ms).map(([key, value]) => <div key={key} className="rounded-xl bg-surface-muted p-3 "><div className="text-fg-muted">{key.toUpperCase()}</div><div className="mt-1 font-bold text-fg ">{Number(value).toFixed(2)} ms</div></div>)}</div> : <p className="text-xs text-fg-muted">运行后显示 PostgreSQL 评测延迟。</p>}</Panel>
          </div>
          <Panel as="div" className="p-5"><div className="mb-3 flex items-center justify-between gap-3"><h2 className="text-base font-semibold text-fg">基线门禁与用例摘要</h2><span className="text-xs text-fg-muted">最多显示 {Math.min(report.cases.length, 200)} 条</span></div>{report.status === 'not_run' ? <EmptyState icon={Play} title="尚未运行基线回归，请点击“运行基线回归”。" description="运行后在这里显示门禁结果和每个用例的检索摘要。" /> : <><div className="mb-4 grid gap-2 sm:grid-cols-2">{report.gates.map((gate) => <div key={gate.metric} className={`flex items-center justify-between rounded-xl border px-3 py-2 text-xs ${gateColor(gate.passed)}`}><span>{metricLabels[gate.metric] || gate.metric}</span><span className="font-bold">{gate.passed ? '通过' : '未通过'} · {gate.operator} {percent(gate.threshold)}</span></div>)}</div><div className="overflow-x-auto"><DataTable unstyled exportConfig={{ filename: 'rag-regression-results' }} className="w-full min-w-[640px] text-left text-xs"><thead className="sticky top-0 z-10 bg-surface-muted text-fg-muted shadow-sm "><tr><th className="px-3 py-2 font-semibold">用例</th><th className="px-3 py-2 font-semibold">问题摘要</th><th className="px-3 py-2 font-semibold">检索结果</th><th className="px-3 py-2 font-semibold">引用准确率</th><th className="px-3 py-2 font-semibold">延迟</th></tr></thead><tbody>{report.cases.map((item) => <tr key={item.id} className="border-t border-line "><td className="px-3 py-2 font-semibold text-fg ">{item.id}</td><td className="px-3 py-2 text-fg-muted ">固定案例（正文不展示）</td><td className="px-3 py-2">{item.retrieval_correct ? <StatusBadge tone="success">通过</StatusBadge> : <StatusBadge tone="danger">未通过</StatusBadge>}</td><td className="px-3 py-2 text-fg ">{percent(item.citation_precision)}</td><td className="px-3 py-2 text-fg ">{item.latency_ms.toFixed(2)} ms</td></tr>)}</tbody></DataTable></div></>}</Panel>
        </section>
      </>}
    </div>
  );
};

export default RagEvaluationPanel;
