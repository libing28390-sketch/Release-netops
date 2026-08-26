import React, { useCallback, useEffect, useState } from 'react';
import { AlertCircle, CheckCircle2, Clock3, Eye, ListFilter, Loader2, RefreshCw, RotateCcw, Search, ShieldAlert, XCircle } from 'lucide-react';
import {
  getKnowledgeIngestionJobErrors,
  listKnowledgeIngestionJobs,
  retryKnowledgeIngestionJob,
  type KnowledgeIngestionExecutionState,
  type KnowledgeIngestionJobErrors,
  type KnowledgeIngestionJobSummary,
} from '../../../api/ai';
import Pagination from '../../../components/Pagination';

const EXECUTION_STATES: Array<{ value: KnowledgeIngestionExecutionState; label: string }> = [
  { value: 'all', label: '全部状态' },
  { value: 'queued', label: '排队中' },
  { value: 'running', label: '运行中' },
  { value: 'retry_wait', label: '等待重试' },
  { value: 'paused', label: '已暂停' },
  { value: 'cancel_requested', label: '取消中' },
  { value: 'cancelled', label: '已取消' },
  { value: 'succeeded', label: '已完成' },
  { value: 'failed', label: '失败' },
];

const PHASES = [
  ['all', '全部阶段'],
  ['accepted', '已接收'],
  ['scoped', '范围确认'],
  ['fetched', '已采集'],
  ['parsed', '已解析'],
  ['normalized', '已规范化'],
  ['classified', '已分类'],
  ['chunked', '已切片'],
  ['embedded', '已向量化'],
  ['indexed', '已建索引'],
  ['validated', '已校验'],
  ['committed', '已提交'],
  ['completed', '已完成'],
  ['failed', '失败'],
  ['cancelled', '已取消'],
] as const;

const JOB_KIND_LABELS: Record<string, string> = {
  document_import: '文档导入',
  document_reindex: '文档重建索引',
  chunk_rebuild: 'Chunk 重建',
  embedding_rebuild: 'Embedding 重建',
  index_build: '索引构建',
  scope_refresh: '范围刷新',
  catalog_backfill: '目录回填',
  dry_run_validation: '试运行校验',
};

const PHASE_LABELS = Object.fromEntries(PHASES.map(([value, label]) => [value, label]));

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '导入任务请求失败，请稍后重试。';
}

function formatDate(value?: string | null): string {
  if (!value) return '--';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '--' : date.toLocaleString();
}

function statusClass(status: string): string {
  if (status === 'succeeded') return 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300';
  if (status === 'failed' || status === 'cancelled') return 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300';
  if (status === 'retry_wait' || status === 'cancel_requested') return 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300';
  return 'bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300';
}

function StatusIcon({ status }: { status: string }): React.ReactElement {
  if (status === 'succeeded') return <CheckCircle2 className="h-3.5 w-3.5" />;
  if (status === 'failed' || status === 'cancelled') return <XCircle className="h-3.5 w-3.5" />;
  if (status === 'retry_wait' || status === 'cancel_requested') return <Clock3 className="h-3.5 w-3.5" />;
  return <Loader2 className="h-3.5 w-3.5" />;
}

function safeProgress(job: KnowledgeIngestionJobSummary): number {
  const value = Number(job.progress_percent);
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, value));
}

function jobHasRetry(job: KnowledgeIngestionJobSummary): boolean {
  return job.execution_state === 'failed' || job.execution_state === 'retry_wait';
}

export const IngestionJobsPanel: React.FC = () => {
  const [items, setItems] = useState<KnowledgeIngestionJobSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [executionState, setExecutionState] = useState<KnowledgeIngestionExecutionState>('all');
  const [phase, setPhase] = useState('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedJobId, setSelectedJobId] = useState('');
  const [jobErrors, setJobErrors] = useState<KnowledgeIngestionJobErrors | null>(null);
  const [errorsLoading, setErrorsLoading] = useState(false);
  const [retryingJobId, setRetryingJobId] = useState('');

  const loadJobs = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError('');
    try {
      const result = await listKnowledgeIngestionJobs({
        executionState: executionState === 'all' ? '' : executionState,
        phase: phase === 'all' ? '' : phase,
        search,
        page,
        pageSize,
        signal,
      });
      if (signal?.aborted) return;
      setItems(result.items);
      setTotal(result.total);
      setSelectedJobId((current) => current && result.items.some((item) => item.id === current) ? current : '');
    } catch (cause) {
      if (signal?.aborted) return;
      setError(errorMessage(cause));
      setItems([]);
      setTotal(0);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [executionState, page, pageSize, phase, search]);

  useEffect(() => {
    const controller = new AbortController();
    void loadJobs(controller.signal);
    return () => controller.abort();
  }, [loadJobs]);

  useEffect(() => {
    if (!selectedJobId) {
      setJobErrors(null);
      setErrorsLoading(false);
      return undefined;
    }
    const controller = new AbortController();
    setErrorsLoading(true);
    setJobErrors(null);
    void getKnowledgeIngestionJobErrors(selectedJobId, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setJobErrors(result);
      })
      .catch((cause) => {
        if (!controller.signal.aborted) setError(errorMessage(cause));
      })
      .finally(() => {
        if (!controller.signal.aborted) setErrorsLoading(false);
      });
    return () => controller.abort();
  }, [selectedJobId]);

  const applySearch = () => {
    setSearch(searchInput.trim());
    setPage(1);
  };

  const clearFilters = () => {
    setSearchInput('');
    setSearch('');
    setExecutionState('all');
    setPhase('all');
    setPage(1);
  };

  const retryJob = async (job: KnowledgeIngestionJobSummary) => {
    if (!jobHasRetry(job) || retryingJobId) return;
    setRetryingJobId(job.id);
    setError('');
    try {
      await retryKnowledgeIngestionJob(job.id);
      setSelectedJobId('');
      await loadJobs();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setRetryingJobId('');
    }
  };

  return (
    <section className="rounded-2xl border border-slate-200/80 bg-white p-4 shadow-xs dark:border-slate-700/80 dark:bg-slate-800" aria-label="导入任务管理">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="mb-1 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.16em] text-indigo-600 dark:text-indigo-300"><ListFilter className="h-4 w-4" /> ING-020 · Import Jobs</div>
          <h3 className="text-sm font-bold text-slate-900 dark:text-white">导入任务列表</h3>
          <p className="mt-1 text-[10px] text-slate-500 dark:text-slate-400">服务端筛选与分页；阶段进度、失败阶段和安全错误码均来自租户范围内的 Import Job。</p>
        </div>
        <button type="button" onClick={() => void loadJobs()} disabled={loading} className="inline-flex items-center gap-2 rounded-xl border border-indigo-200 bg-white px-3 py-2 text-xs font-semibold text-indigo-700 hover:bg-indigo-50 disabled:opacity-50 dark:border-indigo-800 dark:bg-slate-900 dark:text-indigo-300 dark:hover:bg-indigo-950/40"><RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />刷新</button>
      </div>

      <div className="mt-4 grid gap-2 md:grid-cols-[minmax(220px,1fr)_180px_180px_auto_auto]">
        <label className="relative text-[11px] text-slate-500 dark:text-slate-400"><span className="sr-only">搜索导入任务</span><Search className="pointer-events-none absolute left-3 top-2.5 h-3.5 w-3.5" /><input value={searchInput} onChange={(event) => setSearchInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') applySearch(); }} placeholder="搜索任务 ID、类型、阶段或错误码" className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2 pl-9 pr-3 text-xs text-slate-700 outline-none focus:border-indigo-300 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200" /></label>
        <label className="text-[11px] text-slate-500 dark:text-slate-400"><span className="sr-only">任务状态</span><select aria-label="导入任务状态" value={executionState} onChange={(event) => { setExecutionState(event.target.value as KnowledgeIngestionExecutionState); setPage(1); }} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">{EXECUTION_STATES.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
        <label className="text-[11px] text-slate-500 dark:text-slate-400"><span className="sr-only">导入阶段</span><select aria-label="导入任务阶段" value={phase} onChange={(event) => { setPhase(event.target.value); setPage(1); }} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">{PHASES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <button type="button" onClick={applySearch} className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-700"><Search className="h-3.5 w-3.5" />搜索</button>
        <button type="button" onClick={clearFilters} className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-900"><RotateCcw className="h-3.5 w-3.5" />重置</button>
      </div>

      {error && <div role="alert" className="mt-3 flex items-center gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-300"><AlertCircle className="h-4 w-4" />{error}</div>}

      {loading && !items.length ? <div className="mt-4 rounded-xl bg-slate-50 p-8 text-center text-sm text-slate-500 dark:bg-slate-900/70 dark:text-slate-400"><Loader2 className="mx-auto mb-2 h-5 w-5 animate-spin" />正在加载导入任务…</div> : !items.length ? <div className="mt-4 rounded-xl border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-400"><Eye className="mx-auto mb-2 h-6 w-6 opacity-50" />{search || executionState !== 'all' || phase !== 'all' ? '当前筛选条件没有匹配任务。' : '暂无导入任务。提交官方 URL 或企业 SOP 后，任务会出现在这里。'}</div> : <>
        <div className="mt-4 overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-700">
          <table className="nx-data-table min-w-[980px] w-full text-left">
            <thead className="border-b border-slate-200 bg-slate-50 text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400"><tr><th className="px-3 py-2.5 font-semibold">任务</th><th className="px-3 py-2.5 font-semibold">状态</th><th className="px-3 py-2.5 font-semibold">阶段进度</th><th className="px-3 py-2.5 font-semibold">统计</th><th className="px-3 py-2.5 font-semibold">更新时间</th><th className="px-3 py-2.5 font-semibold">操作</th></tr></thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">{items.map((job) => { const progress = safeProgress(job); const selected = selectedJobId === job.id; return <tr key={job.id} className={selected ? 'bg-indigo-50/60 dark:bg-indigo-950/20' : 'hover:bg-slate-50/70 dark:hover:bg-slate-900/40'}>
              <td className="px-3 py-3"><button type="button" onClick={() => setSelectedJobId(job.id)} className="text-left"><span className="block font-mono text-[11px] font-semibold text-indigo-700 hover:underline dark:text-indigo-300">{job.id}</span><span className="mt-1 block text-[11px] text-slate-500">{JOB_KIND_LABELS[job.job_kind] || job.job_kind}</span></button></td>
              <td className="px-3 py-3"><span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-semibold ${statusClass(job.execution_state)}`}><StatusIcon status={job.execution_state} />{EXECUTION_STATES.find((option) => option.value === job.execution_state)?.label || job.execution_state}</span>{job.last_error_code && <span className="mt-1 block font-mono text-[10px] text-rose-600 dark:text-rose-300">{job.last_error_code}</span>}</td>
              <td className="px-3 py-3"><div className="min-w-[180px]"><div className="mb-1 flex items-center justify-between gap-2 text-[10px] text-slate-500"><span>{PHASE_LABELS[job.phase] || job.phase}</span><span className="font-mono font-semibold text-slate-700 dark:text-slate-200">{progress.toFixed(2)}%</span></div><div className="h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-700" role="progressbar" aria-label={`${job.id} 阶段进度`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><div className={`h-full rounded-full transition-all ${job.execution_state === 'failed' ? 'bg-rose-500' : job.execution_state === 'succeeded' ? 'bg-emerald-500' : 'bg-indigo-500'}`} style={{ width: `${progress}%` }} /></div></div></td>
              <td className="whitespace-nowrap px-3 py-3 text-[11px] text-slate-500"><span className="font-mono text-slate-700 dark:text-slate-200">{job.processed_count}/{job.total_count}</span> 已处理<br /><span className="text-emerald-600 dark:text-emerald-300">成功 {job.succeeded_count}</span><span className="mx-1 text-slate-300">·</span><span className="text-rose-600 dark:text-rose-300">失败 {job.failed_count}</span></td>
              <td className="whitespace-nowrap px-3 py-3 text-[11px] text-slate-500 dark:text-slate-400">{formatDate(job.updated_at || job.created_at)}</td>
              <td className="px-3 py-3"><div className="flex flex-wrap gap-1.5"><button type="button" onClick={() => setSelectedJobId(job.id)} className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1.5 text-[10px] font-semibold text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-900"><Eye className="h-3 w-3" />错误详情</button>{jobHasRetry(job) && <button type="button" onClick={() => void retryJob(job)} disabled={Boolean(retryingJobId)} className="inline-flex items-center gap-1 rounded-lg border border-amber-200 px-2 py-1.5 text-[10px] font-semibold text-amber-700 hover:bg-amber-50 disabled:opacity-50 dark:border-amber-900/60 dark:text-amber-300 dark:hover:bg-amber-950/30"><RotateCcw className={`h-3 w-3 ${retryingJobId === job.id ? 'animate-spin' : ''}`} />{retryingJobId === job.id ? '重试中…' : '重试'}</button>}</div></td>
            </tr>; })}</tbody>
          </table>
        </div>
        <Pagination currentPage={page} totalItems={total} onPageChange={setPage} itemsPerPage={pageSize} onItemsPerPageChange={(size) => { setPageSize(size); setPage(1); }} language="zh" alwaysVisible />
      </>}

      {selectedJobId && <div className="mt-4 rounded-xl border border-indigo-100 bg-indigo-50/50 p-3 dark:border-indigo-900/50 dark:bg-indigo-950/20"><div className="flex flex-wrap items-center justify-between gap-2"><div className="flex items-center gap-2 text-xs font-bold text-slate-800 dark:text-slate-100"><ShieldAlert className="h-4 w-4 text-indigo-600" />错误详情 · <span className="font-mono">{selectedJobId}</span></div><button type="button" onClick={() => setSelectedJobId('')} className="text-[11px] text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">关闭</button></div>{errorsLoading ? <p className="mt-3 text-xs text-slate-500">正在加载安全错误摘要…</p> : !jobErrors?.errors?.length ? <p className="mt-3 text-xs text-slate-500">该任务暂无可展示的错误详情。</p> : <div className="mt-3 space-y-2">{jobErrors.errors.map((detail, index) => <div key={`${detail.occurred_at || 'error'}-${index}`} className="rounded-lg border border-white/70 bg-white/80 p-2.5 text-[11px] dark:border-slate-800 dark:bg-slate-900/60"><div className="flex flex-wrap items-center justify-between gap-2"><span className="font-mono font-semibold text-rose-700 dark:text-rose-300">{detail.code || 'INGESTION_ERROR'}</span><span className="text-slate-400">{formatDate(detail.occurred_at)}</span></div><p className="mt-1 text-slate-600 dark:text-slate-300">{detail.safe_message || detail.message || '任务执行失败，请检查来源和依赖状态。'}</p><div className="mt-1 text-[10px] text-slate-400">阶段：{PHASE_LABELS[detail.phase || ''] || detail.phase || jobErrors.phase} · {detail.retryable ? '可重试' : '不可重试'}</div></div>)}</div>}</div>}
    </section>
  );
};

export default IngestionJobsPanel;
