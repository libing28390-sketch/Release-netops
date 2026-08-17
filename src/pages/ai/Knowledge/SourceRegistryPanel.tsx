import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Clock3, Loader2, RefreshCw, ShieldCheck, XCircle } from 'lucide-react';
import {
  getKnowledgeSourceRefreshStatus,
  listKnowledgeSourceRefreshObservations,
  listKnowledgeSources,
  refreshKnowledgeSource,
  validateKnowledgeSource,
  type KnowledgeSourceRefreshObservation,
  type KnowledgeSourceRefreshStatus,
  type KnowledgeSourceRegistry,
} from '../../../api/ai';

const freshnessLabel: Record<string, string> = {
  healthy: '正常',
  failed: '失败',
  attention: '需关注',
  never_checked: '未刷新',
  not_configured: '未启用',
};

function statusTone(value: string): string {
  if (value === 'healthy' || value === 'active' || value === 'valid' || value === 'unchanged') return 'text-emerald-700 bg-emerald-50 dark:text-emerald-300 dark:bg-emerald-950/30';
  if (value === 'failed' || value === 'invalid' || value === 'disabled') return 'text-rose-700 bg-rose-50 dark:text-rose-300 dark:bg-rose-950/30';
  if (value === 'attention' || value === 'changed' || value === 'replacement' || value === 'removed') return 'text-amber-700 bg-amber-50 dark:text-amber-300 dark:bg-amber-950/30';
  return 'text-slate-600 bg-slate-100 dark:text-slate-300 dark:bg-slate-800';
}

function safeTime(value?: string | null): string {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

export const SourceRegistryPanel: React.FC = () => {
  const [statusFilter, setStatusFilter] = useState('all');
  const [sources, setSources] = useState<KnowledgeSourceRegistry[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [refreshStatus, setRefreshStatus] = useState<KnowledgeSourceRefreshStatus | null>(null);
  const [observations, setObservations] = useState<KnowledgeSourceRefreshObservation[]>([]);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const loadSources = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const items = await listKnowledgeSources(statusFilter);
      setSources(items);
      setSelectedId((current) => items.some((item) => item.id === current) ? current : (items[0]?.id || ''));
    } catch (err: any) {
      setError(err?.message || 'Source Registry 加载失败');
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  const loadDetail = useCallback(async (sourceId: string) => {
    if (!sourceId) {
      setRefreshStatus(null);
      setObservations([]);
      return;
    }
    setDetailLoading(true);
    setError('');
    try {
      const [status, history] = await Promise.all([
        getKnowledgeSourceRefreshStatus(sourceId),
        listKnowledgeSourceRefreshObservations(sourceId, 30),
      ]);
      setRefreshStatus(status);
      setObservations(history);
    } catch (err: any) {
      setError(err?.message || '刷新状态加载失败');
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => { void loadSources(); }, [loadSources]);
  useEffect(() => { void loadDetail(selectedId); }, [loadDetail, selectedId]);

  const selected = useMemo(() => sources.find((item) => item.id === selectedId) || null, [selectedId, sources]);

  const runSourceAction = async (action: 'validate' | 'refresh') => {
    if (!selectedId || busy) return;
    setBusy(action);
    setNotice('');
    setError('');
    try {
      if (action === 'validate') await validateKnowledgeSource(selectedId);
      else await refreshKnowledgeSource(selectedId);
      setNotice(action === 'validate' ? 'Source Registry 校验已完成。' : '刷新任务已完成，状态已更新。');
      await loadSources();
      await loadDetail(selectedId);
    } catch (err: any) {
      setError(err?.message || (action === 'validate' ? '来源校验失败' : '来源刷新失败'));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-xl font-bold text-slate-900 dark:text-white"><ShieldCheck className="h-6 w-6 text-indigo-500" />Source Registry / 来源注册表</h2>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">管理官方来源身份、校验状态和刷新观察记录；响应只展示状态、哈希和稳定错误码。</p>
        </div>
        <div className="flex items-center gap-2">
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-900 dark:text-white" aria-label="来源状态筛选">
            <option value="all">全部状态</option><option value="active">Active</option><option value="disabled">Disabled</option><option value="draft">Draft</option><option value="quarantined">Quarantined</option>
          </select>
          <button type="button" onClick={() => void loadSources()} disabled={loading} className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"><RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />刷新列表</button>
        </div>
      </div>

      {error && <div className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-300"><XCircle className="mt-0.5 h-4 w-4 shrink-0" />{error}</div>}
      {notice && <div className="flex items-start gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-300"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />{notice}</div>}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)]">
        <section className="min-w-0 rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <div className="border-b border-slate-100 px-4 py-3 text-xs font-semibold text-slate-700 dark:border-slate-800 dark:text-slate-200">注册来源（{sources.length}）</div>
          {loading ? <div className="flex items-center gap-2 px-4 py-8 text-xs text-slate-400"><Loader2 className="h-4 w-4 animate-spin" />正在加载…</div> : sources.length === 0 ? <div className="px-4 py-10 text-center text-xs text-slate-400">暂无来源，或当前筛选没有结果。</div> : <div className="max-h-[560px] overflow-y-auto p-2">{sources.map((source) => {
            const active = source.id === selectedId;
            return <button key={source.id} type="button" onClick={() => setSelectedId(source.id)} className={`w-full rounded-xl p-3 text-left transition ${active ? 'bg-indigo-50 ring-1 ring-indigo-200 dark:bg-indigo-950/30 dark:ring-indigo-800' : 'hover:bg-slate-50 dark:hover:bg-slate-800/70'}`}>
              <div className="flex items-start justify-between gap-2"><span className="min-w-0 truncate text-xs font-semibold text-slate-800 dark:text-slate-100">{source.name || source.canonical_url}</span><span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${statusTone(source.status)}`}>{source.status}</span></div>
              <div className="mt-1 truncate text-[10px] text-slate-500" title={source.canonical_url}>{source.canonical_url}</div>
              <div className="mt-2 flex flex-wrap gap-1.5 text-[10px]"><span className={`rounded-full px-2 py-0.5 ${statusTone(source.validation_status)}`}>校验 {source.validation_status}</span><span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600 dark:bg-slate-800 dark:text-slate-300">{source.source_kind}</span></div>
            </button>;
          })}</div>}
        </section>

        <section className="min-w-0 rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
          {!selected ? <div className="flex min-h-[260px] items-center justify-center px-5 text-center text-xs text-slate-400">选择一个来源查看刷新状态。</div> : <>
            <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-4 py-3 dark:border-slate-800"><div className="min-w-0"><h3 className="truncate text-sm font-semibold text-slate-900 dark:text-white">{selected.name || selected.canonical_url}</h3><p className="mt-1 truncate text-[10px] text-slate-500">{selected.canonical_url}</p></div><div className="flex gap-2"><button type="button" onClick={() => void runSourceAction('validate')} disabled={Boolean(busy)} className="rounded-lg border border-indigo-200 px-2.5 py-1.5 text-[10px] font-semibold text-indigo-700 hover:bg-indigo-50 disabled:opacity-50 dark:border-indigo-800 dark:text-indigo-300">{busy === 'validate' ? '校验中…' : '重新校验'}</button><button type="button" onClick={() => void runSourceAction('refresh')} disabled={Boolean(busy) || !selected.fetch_enabled} className="inline-flex items-center gap-1 rounded-lg bg-indigo-600 px-2.5 py-1.5 text-[10px] font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"><RefreshCw className="h-3 w-3" />{busy === 'refresh' ? '刷新中…' : '立即刷新'}</button></div></div>
            {detailLoading ? <div className="flex items-center gap-2 px-4 py-8 text-xs text-slate-400"><Loader2 className="h-4 w-4 animate-spin" />正在读取刷新状态…</div> : <div className="space-y-4 p-4">
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4"><div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-800/70"><div className="text-[10px] text-slate-400">刷新状态</div><div className={`mt-1 inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ${statusTone(refreshStatus?.freshness_status || 'unknown')}`}>{freshnessLabel[refreshStatus?.freshness_status || ''] || refreshStatus?.freshness_status || '未知'}</div></div><div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-800/70"><div className="text-[10px] text-slate-400">最近结果</div><div className="mt-1 text-xs font-semibold text-slate-800 dark:text-slate-100">{refreshStatus?.last_outcome || '—'}</div></div><div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-800/70"><div className="text-[10px] text-slate-400">观察记录</div><div className="mt-1 text-xs font-semibold text-slate-800 dark:text-slate-100">{refreshStatus?.observation_count ?? 0}</div></div><div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-800/70"><div className="text-[10px] text-slate-400">最近检查</div><div className="mt-1 truncate text-xs font-semibold text-slate-800 dark:text-slate-100" title={refreshStatus?.last_checked_at || ''}>{safeTime(refreshStatus?.last_checked_at)}</div></div></div>
              {refreshStatus?.last_error_code && <div className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-[10px] text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />稳定错误码：{refreshStatus.last_error_code}</div>}
              <div><div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-slate-700 dark:text-slate-200"><Clock3 className="h-3.5 w-3.5 text-indigo-500" />最近刷新观察</div>{observations.length === 0 ? <div className="rounded-xl border border-dashed border-slate-200 px-3 py-6 text-center text-[10px] text-slate-400 dark:border-slate-700">暂无观察记录</div> : <div className="max-h-64 overflow-y-auto rounded-xl border border-slate-100 dark:border-slate-800">{observations.map((item) => <div key={item.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-slate-100 px-3 py-2 text-[10px] last:border-b-0 dark:border-slate-800"><span className="text-slate-400">{safeTime(item.checked_at)}</span><span className={`rounded-full px-2 py-0.5 font-semibold ${statusTone(item.detection_type || item.outcome)}`}>{item.detection_type && item.detection_type !== 'none' ? item.detection_type : item.outcome}</span><span className="text-slate-500">HTTP {item.http_status || '—'}</span><span className="text-slate-500">{item.error_code || '无错误'}</span></div>)}</div>}</div>
            </div>}
          </>}
        </section>
      </div>
    </div>
  );
};

export default SourceRegistryPanel;
