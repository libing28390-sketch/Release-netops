import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, CheckCircle2, CircleAlert, Database, Gauge, Play, ShieldCheck } from 'lucide-react';
import { getKnowledgeEvaluation, runKnowledgeEvaluation, type KnowledgeEvaluationReport } from '../../../api/ai';

const metricLabels: Record<string, string> = {
  retrieval_accuracy: 'Recall / Retrieval Accuracy',
  citation_accuracy: 'Precision / Citation Accuracy',
  citation_recall: 'Citation Recall',
  wrong_vendor_rate: 'Wrong Vendor Rate',
  version_conflict_rate: 'Version Conflict Rate',
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

export const RagEvaluationPanel: React.FC = () => {
  const [report, setReport] = useState<KnowledgeEvaluationReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');

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

  useEffect(() => { void load(); }, [load]);

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
    <div className="mx-auto w-full max-w-7xl space-y-5">
      <section className="rounded-3xl border border-indigo-100 bg-gradient-to-br from-indigo-50 via-white to-violet-50 p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-2 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.18em] text-indigo-600"><Activity className="h-4 w-4" /> KUI-016 · RAG Evaluation</div>
            <h1 className="text-2xl font-bold text-slate-900">RAG 评测与回归结果</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">固定 Query 集在 PostgreSQL 临时事务中执行，结果只返回指标、门禁和脱敏用例摘要；不写入生产表、不访问外网、不展示原始 SQL 或 Chunk 正文。</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-700"><ShieldCheck className="h-4 w-4" /> 租户与权限由服务端绑定</span>
            <button type="button" onClick={() => void run()} disabled={running || loading} className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"><Play className="h-4 w-4" />{running ? 'PostgreSQL 评测中…' : '运行回归'}</button>
          </div>
        </div>
      </section>

      {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}
      {loading && !report && <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">加载评测状态…</div>}
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
            <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><div className="mb-3 flex items-center justify-between"><h2 className="text-sm font-bold text-slate-900">评测执行</h2><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${report.status === 'passed' ? 'bg-emerald-100 text-emerald-700' : report.status === 'failed' ? 'bg-rose-100 text-rose-700' : 'bg-slate-100 text-slate-600'}`}>{report.status === 'not_run' ? '未运行' : report.status === 'passed' ? 'PASS' : 'FAIL'}</span></div><dl className="space-y-2 text-xs"><div className="flex justify-between gap-3"><dt className="text-slate-500">数据集</dt><dd className="font-medium text-slate-800">{report.baseline_id || 'v1-baseline'}</dd></div><div className="flex justify-between gap-3"><dt className="text-slate-500">数据库</dt><dd className="inline-flex items-center gap-1 font-medium text-slate-800"><Database className="h-3.5 w-3.5 text-indigo-500" />{report.database}</dd></div><div className="flex justify-between gap-3"><dt className="text-slate-500">用例数</dt><dd className="font-medium text-slate-800">{report.case_count}</dd></div><div className="flex justify-between gap-3"><dt className="text-slate-500">回滚</dt><dd className="font-medium text-slate-800">{report.rollback}</dd></div><div className="flex justify-between gap-3"><dt className="text-slate-500">生产写入</dt><dd className="font-medium text-emerald-700">{report.production_database_write ? '是' : '否'}</dd></div>{report.duration_ms !== undefined && <div className="flex justify-between gap-3"><dt className="text-slate-500">耗时</dt><dd className="font-medium text-slate-800">{report.duration_ms.toFixed(0)} ms</dd></div>}</dl></article>
            <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><div className="mb-3 flex items-center gap-2"><Gauge className="h-4 w-4 text-indigo-500" /><h2 className="text-sm font-bold text-slate-900">延迟</h2></div>{metrics ? <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">{Object.entries(metrics.latency_ms).map(([key, value]) => <div key={key} className="rounded-xl bg-slate-50 p-3"><div className="text-slate-500">{key.toUpperCase()}</div><div className="mt-1 font-bold text-slate-800">{Number(value).toFixed(2)} ms</div></div>)}</div> : <p className="text-xs text-slate-500">运行后显示 PostgreSQL 评测延迟。</p>}</article>
          </div>
          <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><div className="mb-3 flex items-center justify-between gap-3"><h2 className="text-sm font-bold text-slate-900">门禁与用例摘要</h2><span className="text-xs text-slate-500">最多显示 {Math.min(report.cases.length, 200)} 条</span></div>{report.status === 'not_run' ? <div className="rounded-xl bg-slate-50 p-8 text-center text-sm text-slate-500">尚未运行 PostgreSQL 回归，请点击“运行回归”。</div> : <><div className="mb-4 grid gap-2 sm:grid-cols-2">{report.gates.map((gate) => <div key={gate.metric} className={`flex items-center justify-between rounded-xl border px-3 py-2 text-xs ${gateColor(gate.passed)}`}><span>{metricLabels[gate.metric] || gate.metric}</span><span className="font-bold">{gate.passed ? 'PASS' : 'FAIL'} · {gate.operator} {percent(gate.threshold)}</span></div>)}</div><div className="overflow-x-auto"><table className="w-full min-w-[640px] text-left text-xs"><thead className="sticky top-0 bg-slate-50 text-slate-500"><tr><th className="px-3 py-2 font-semibold">Case</th><th className="px-3 py-2 font-semibold">Query</th><th className="px-3 py-2 font-semibold">检索</th><th className="px-3 py-2 font-semibold">引用</th><th className="px-3 py-2 font-semibold">延迟</th></tr></thead><tbody>{report.cases.map((item) => <tr key={item.id} className="border-t border-slate-100"><td className="px-3 py-2 font-semibold text-slate-800">{item.id}</td><td className="max-w-[280px] truncate px-3 py-2 text-slate-600" title={item.query}>{item.query}</td><td className="px-3 py-2">{item.retrieval_correct ? <span className="text-emerald-700">PASS</span> : <span className="text-rose-700">FAIL</span>}</td><td className="px-3 py-2 text-slate-700">{percent(item.citation_precision)}</td><td className="px-3 py-2 text-slate-700">{item.latency_ms.toFixed(2)} ms</td></tr>)}</tbody></table></div></>}</article>
        </section>
      </>}
    </div>
  );
};

export default RagEvaluationPanel;
