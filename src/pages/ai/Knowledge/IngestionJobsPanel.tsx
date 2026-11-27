import { DataTable } from '../../../components/DataTable';
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

import { TableActionCell, TableActionHeader } from '../../../components/ui/TableActionColumn';
import { ActionIconButton } from '../../../components/ui/ActionIconButton';
import { fetchAllPaginatedItems } from '../../../utils/pagination';
import type { TableExportData } from '../../../components/ui/TableExportMenu';
import { Panel, PanelHeader } from '../../../components/ui/Panel';
import { EmptyState } from '../../../components/ui/EmptyState';
import { StatusBadge, type StatusTone } from '../../../components/ui/StatusBadge';

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

function statusTone(status: string): StatusTone {
  if (status === 'succeeded') return 'success';
  if (status === 'failed' || status === 'cancelled') return 'danger';
  if (status === 'retry_wait' || status === 'cancel_requested') return 'warning';
  return 'accent';
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
  const [pageSize, setPageSize] = useState(10);
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

  const exportAllJobs = useCallback(async (): Promise<TableExportData> => {
    const params = new URLSearchParams();
    if (executionState !== 'all') params.set('execution_state', executionState);
    if (phase !== 'all') params.set('phase', phase);
    if (search) params.set('search', search);
    const allJobs = await fetchAllPaginatedItems<KnowledgeIngestionJobSummary>(
      '/api/knowledge/ingestion/jobs', params, 100,
    );
    return {
      headers: ['任务类型', '状态', '阶段', '进度', '已处理', '总数', '成功数', '失败数', '错误码', '更新时间'],
      rows: allJobs.map((job) => [
        JOB_KIND_LABELS[job.job_kind] || job.job_kind,
        EXECUTION_STATES.find((option) => option.value === job.execution_state)?.label || job.execution_state,
        PHASE_LABELS[job.phase] || job.phase,
        `${safeProgress(job).toFixed(2)}%`,
        job.processed_count,
        job.total_count,
        job.succeeded_count,
        job.failed_count,
        job.last_error_code || '',
        formatDate(job.updated_at || job.created_at),
      ]),
    };
  }, [executionState, phase, search]);

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
    <Panel aria-label="导入任务管理">
      <PanelHeader
        title={<span className="inline-flex items-center gap-2"><ListFilter className="h-4 w-4 text-accent" aria-hidden="true" />导入任务列表</span>}
        description="服务端筛选与分页；阶段进度、失败阶段和安全错误码均来自租户范围内的 Import Job。"
        actions={<button type="button" onClick={() => void loadJobs()} disabled={loading} className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-xs font-semibold text-fg hover:bg-surface-muted disabled:opacity-50"><RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" />刷新</button>}
      />
      <div className="p-4">
      <div className="grid gap-2 md:grid-cols-[minmax(220px,1fr)_180px_180px_auto_auto]">
        <label className="relative text-[11px] text-fg-muted "><span className="sr-only">搜索导入任务</span><Search className="pointer-events-none absolute left-3 top-2.5 h-3.5 w-3.5" /><input type="search" value={searchInput} onChange={(event) => setSearchInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') applySearch(); }} placeholder="搜索任务 ID、类型、阶段或错误码" className="w-full rounded-xl border border-line bg-surface-muted py-2 pl-9 pr-3 text-xs text-fg outline-none focus:border-accent/30 " /></label>
        <label className="text-[11px] text-fg-muted "><span className="sr-only">任务状态</span><select aria-label="导入任务状态" value={executionState} onChange={(event) => { setExecutionState(event.target.value as KnowledgeIngestionExecutionState); setPage(1); }} className="w-full rounded-xl border border-line bg-surface-muted px-3 py-2 text-xs text-fg ">{EXECUTION_STATES.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
        <label className="text-[11px] text-fg-muted "><span className="sr-only">导入阶段</span><select aria-label="导入任务阶段" value={phase} onChange={(event) => { setPhase(event.target.value); setPage(1); }} className="w-full rounded-xl border border-line bg-surface-muted px-3 py-2 text-xs text-fg ">{PHASES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <button type="button" onClick={clearFilters} className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-line px-3 py-2 text-xs font-semibold text-fg-muted hover:bg-surface-muted "><RotateCcw className="h-3.5 w-3.5" />重置</button>
      </div>

      {error && <div role="alert" className="mt-3 flex items-center gap-2 rounded-xl border border-danger/30 bg-danger-subtle px-3 py-2 text-xs text-danger "><AlertCircle className="h-4 w-4" />{error}</div>}

      {loading && !items.length ? <div className="mt-4 rounded-lg bg-surface-muted p-8 text-center text-sm text-fg-muted "><Loader2 className="mx-auto mb-2 h-5 w-5 animate-spin" />正在加载导入任务…</div> : !items.length ? (search || executionState !== 'all' || phase !== 'all'
        ? <EmptyState className="mt-4" icon={Eye} title="当前筛选条件没有匹配任务" description="调整状态、阶段或关键字后再试。" action={<button type="button" onClick={clearFilters} className="rounded-lg border border-line px-3 py-2 text-xs font-semibold text-fg hover:bg-surface-muted">清除筛选</button>} />
        : <EmptyState className="mt-4" icon={Eye} title="暂无导入任务" description="提交官方 URL 或企业 SOP 后，任务会出现在这里。" />) : <>
        <div className="mt-4 overflow-x-auto rounded-xl border border-line ">
          <DataTable unstyled exportConfig={{ filename: 'knowledge-ingestion-jobs', disabled: loading || items.length === 0, exportData: exportAllJobs }} className="nx-data-table min-w-[1440px] w-full text-left">
            <thead className="border-b border-line bg-surface-muted text-fg-muted "><tr><th className="px-3 py-2.5 font-semibold">任务类型</th><th className="px-3 py-2.5 font-semibold">状态</th><th className="px-3 py-2.5 font-semibold">阶段</th><th className="px-3 py-2.5 font-semibold">进度</th><th className="px-3 py-2.5 font-semibold">已处理</th><th className="px-3 py-2.5 font-semibold">总数</th><th className="px-3 py-2.5 font-semibold">成功数</th><th className="px-3 py-2.5 font-semibold">失败数</th><th className="px-3 py-2.5 font-semibold">错误码</th><th className="px-3 py-2.5 font-semibold">更新时间</th><TableActionHeader className="px-3 py-2.5 font-semibold">操作</TableActionHeader></tr></thead>
            <tbody className="divide-y divide-line ">{items.map((job) => { const progress = safeProgress(job); const selected = selectedJobId === job.id; return <tr key={job.id} className={selected ? 'bg-accent-subtle ' : 'hover:bg-surface-muted '}>
              <td className="px-3 py-3"><button type="button" onClick={() => setSelectedJobId(job.id)} className="text-left"><span data-export-ignore className="block font-mono text-[11px] font-semibold text-accent hover:underline ">{job.id}</span><span className="mt-1 block text-[11px] text-fg-muted">{JOB_KIND_LABELS[job.job_kind] || job.job_kind}</span></button></td>
              <td className="px-3 py-3"><StatusBadge tone={statusTone(job.execution_state)}><StatusIcon status={job.execution_state} />{EXECUTION_STATES.find((option) => option.value === job.execution_state)?.label || job.execution_state}</StatusBadge></td>
              <td className="px-3 py-3">{PHASE_LABELS[job.phase] || job.phase}</td>
              <td className="px-3 py-3"><div className="min-w-[120px]"><div className="mb-1 font-mono text-xs font-semibold text-fg ">{progress.toFixed(2)}%</div><div className="h-2 overflow-hidden rounded-full bg-surface-muted " role="progressbar" aria-label={`${job.id} 阶段进度`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><div className={`h-full rounded-full transition-all ${job.execution_state === 'failed' ? 'bg-danger' : job.execution_state === 'succeeded' ? 'bg-success' : 'bg-accent'}`} style={{ width: `${progress}%` }} /></div></div></td>
              <td className="px-3 py-3 font-mono">{job.processed_count}</td><td className="px-3 py-3 font-mono">{job.total_count}</td><td className="px-3 py-3 font-mono text-success ">{job.succeeded_count}</td><td className="px-3 py-3 font-mono text-danger ">{job.failed_count}</td>
              <td className="px-3 py-3 font-mono text-xs text-danger ">{job.last_error_code || '—'}</td>
              <td className="whitespace-nowrap px-3 py-3 text-[11px] text-fg-muted ">{formatDate(job.updated_at || job.created_at)}</td>
              <TableActionCell className="px-3 py-3"><ActionIconButton icon={Eye} label="错误详情" variant="accent" onClick={() => setSelectedJobId(job.id)} />{jobHasRetry(job) && <ActionIconButton icon={RotateCcw} label={retryingJobId === job.id ? '重试中' : '重试'} iconClassName={retryingJobId === job.id ? 'animate-spin' : undefined} variant="accent" onClick={() => void retryJob(job)} disabled={Boolean(retryingJobId)} />}</TableActionCell>
            </tr>; })}</tbody>
          </DataTable>
        </div>
        <Pagination currentPage={page} totalItems={total} onPageChange={setPage} itemsPerPage={pageSize} onItemsPerPageChange={(size) => { setPageSize(size); setPage(1); }} language="zh" alwaysVisible />
      </>}

      {selectedJobId && <div className="mt-4 rounded-lg border border-line bg-surface-muted p-3"><div className="flex flex-wrap items-center justify-between gap-2"><div className="flex items-center gap-2 text-xs font-bold text-fg "><ShieldAlert className="h-4 w-4 text-accent" />错误详情 · <span className="font-mono">{selectedJobId}</span></div><button type="button" onClick={() => setSelectedJobId('')} className="text-[11px] text-fg-muted hover:text-fg ">关闭</button></div>{errorsLoading ? <p className="mt-3 text-xs text-fg-muted">正在加载安全错误摘要…</p> : !jobErrors?.errors?.length ? <p className="mt-3 text-xs text-fg-muted">该任务暂无可展示的错误详情。</p> : <div className="mt-3 space-y-2">{jobErrors.errors.map((detail, index) => <div key={`${detail.occurred_at || 'error'}-${index}`} className="rounded-lg border border-line bg-surface p-2.5 text-[11px] "><div className="flex flex-wrap items-center justify-between gap-2"><span className="font-mono font-semibold text-danger ">{detail.code || 'INGESTION_ERROR'}</span><span className="text-fg-subtle">{formatDate(detail.occurred_at)}</span></div><p className="mt-1 text-fg-muted ">{detail.safe_message || detail.message || '任务执行失败，请检查来源和依赖状态。'}</p><div className="mt-1 text-xs text-fg-subtle">阶段：{PHASE_LABELS[detail.phase || ''] || detail.phase || jobErrors.phase} · {detail.retryable ? '可重试' : '不可重试'}</div></div>)}</div>}</div>}
      </div>
    </Panel>
  );
};

export default IngestionJobsPanel;
