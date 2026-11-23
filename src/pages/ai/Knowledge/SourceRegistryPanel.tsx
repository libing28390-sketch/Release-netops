import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Clock3, Loader2, RefreshCw, ShieldCheck, XCircle } from 'lucide-react';
import {
  getKnowledgeSourceRefreshStatus,
  listOfficialSourceSuggestions,
  listKnowledgeSourceRefreshObservations,
  listKnowledgeSources,
  refreshKnowledgeSource,
  reviewOfficialSourceSuggestion,
  validateKnowledgeSource,
  type OfficialSourceSuggestion,
  type KnowledgeSourceRefreshObservation,
  type KnowledgeSourceRefreshStatus,
  type KnowledgeSourceRegistry,
} from '../../../api/ai';
import Pagination from '../../../components/Pagination';
import { PageHeader } from '../../../components/ui/PageHeader';
import { Panel, PanelHeader } from '../../../components/ui/Panel';
import { EmptyState } from '../../../components/ui/EmptyState';
import { StatusBadge, type StatusTone } from '../../../components/ui/StatusBadge';

const freshnessLabel: Record<string, string> = {
  healthy: '正常',
  failed: '失败',
  attention: '需关注',
  never_checked: '未刷新',
  not_configured: '未启用',
};

const sourceStatusLabel: Record<string, string> = {
  active: '已启用',
  disabled: '已停用',
  draft: '草稿',
  quarantined: '已隔离',
};

const validationStatusLabel: Record<string, string> = {
  valid: '已通过',
  invalid: '未通过',
  pending: '待校验',
  failed: '校验失败',
  unknown: '未知',
};

const observationStatusLabel: Record<string, string> = {
  unchanged: '无变化',
  changed: '发现变化',
  replacement: '来源替换',
  removed: '来源下线',
  success: '成功',
  failed: '失败',
  none: '无变化',
};

const suggestionStatusLabel: Record<string, string> = {
  pending: '待审核',
  failed: '失败',
  collecting: '采集中',
  imported: '已入库',
  rejected: '已驳回',
};

const sourceKindLabel: Record<string, string> = {
  official_url: '厂商官网',
  product_page: '产品页',
  configuration_guide: '配置指南',
  command_reference: '命令参考',
  release_note: '版本说明',
  product_support: '产品支持页',
};

const officialSourceKinds = ['official_url', 'product_page', 'configuration_guide', 'command_reference', 'release_note', 'product_support'] as const;

function statusTone(value: string): StatusTone {
  if (value === 'healthy' || value === 'active' || value === 'valid' || value === 'unchanged') return 'success';
  if (value === 'failed' || value === 'invalid' || value === 'disabled') return 'danger';
  if (value === 'attention' || value === 'changed' || value === 'replacement' || value === 'removed') return 'warning';
  return 'neutral';
}

function safeTime(value?: string | null): string {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

export const SourceRegistryPanel: React.FC = () => {
  const [statusFilter, setStatusFilter] = useState('all');
  const [sources, setSources] = useState<KnowledgeSourceRegistry[]>([]);
  const [sourcePage, setSourcePage] = useState(1);
  const [sourcePageSize, setSourcePageSize] = useState(10);
  const [sourceTotal, setSourceTotal] = useState(0);
  const [selectedId, setSelectedId] = useState('');
  const [refreshStatus, setRefreshStatus] = useState<KnowledgeSourceRefreshStatus | null>(null);
  const [observations, setObservations] = useState<KnowledgeSourceRefreshObservation[]>([]);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [suggestions, setSuggestions] = useState<OfficialSourceSuggestion[]>([]);
  const [suggestionStatus, setSuggestionStatus] = useState('pending');
  const [selectedSuggestionId, setSelectedSuggestionId] = useState('');
  const [reviewDraft, setReviewDraft] = useState({ vendor: '', product_model: '', software_release: '', feature: '', url: '', source_kind: '' });

  const loadSources = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const result = await listKnowledgeSources(statusFilter, sourcePage, sourcePageSize);
      setSources(result.items);
      setSourceTotal(result.total);
      if (result.page !== sourcePage) setSourcePage(result.page);
      setSelectedId((current) => result.items.some((item) => item.id === current) ? current : (result.items[0]?.id || ''));
    } catch (err: any) {
      setError(err?.message || 'Source Registry 加载失败');
    } finally {
      setLoading(false);
    }
  }, [sourcePage, sourcePageSize, statusFilter]);

  const loadSuggestions = useCallback(async () => {
    try {
      const result = await listOfficialSourceSuggestions(suggestionStatus);
      setSuggestions(result.items || []);
      setSelectedSuggestionId((current) => result.items.some((item) => item.id === current) ? current : '');
    } catch (err: any) {
      setError(err?.message || '官方来源补充任务加载失败');
    }
  }, [suggestionStatus]);

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
  useEffect(() => { void loadSuggestions(); }, [loadSuggestions]);
  useEffect(() => { void loadDetail(selectedId); }, [loadDetail, selectedId]);

  const selected = useMemo(() => sources.find((item) => item.id === selectedId) || null, [selectedId, sources]);
  const selectedSuggestion = useMemo(() => suggestions.find((item) => item.id === selectedSuggestionId) || null, [selectedSuggestionId, suggestions]);

  const selectSuggestion = (item: OfficialSourceSuggestion) => {
    setSelectedSuggestionId(item.id);
    setReviewDraft({
      vendor: item.vendor || '', product_model: item.product_model || '', software_release: item.software_release || '',
      feature: item.feature || '', url: item.reviewed_url || item.suggested_url || '', source_kind: item.source_kind || 'product_page',
    });
  };

  const reviewSuggestion = async (decision: 'approve' | 'reject') => {
    if (!selectedSuggestion || busy) return;
    if (decision === 'approve') {
      const requiredFields = [reviewDraft.vendor, reviewDraft.product_model, reviewDraft.software_release, reviewDraft.feature, reviewDraft.source_kind, reviewDraft.url];
      if (requiredFields.some((value) => !value.trim())) {
        setError('确认采集前，请完整填写厂商、型号、软件版本、功能、来源类型和官方 URL。');
        return;
      }
      try {
        if (new URL(reviewDraft.url).protocol !== 'https:') throw new Error('HTTPS required');
      } catch {
        setError('官方来源必须填写有效的 HTTPS URL。');
        return;
      }
    }
    setBusy(`suggestion:${decision}`);
    setError('');
    setNotice('');
    try {
      await reviewOfficialSourceSuggestion(selectedSuggestion.id, { decision, ...(decision === 'approve' ? reviewDraft : {}) });
      setNotice(decision === 'approve' ? '官方来源已进入校验、采集、入库与原 Trace 回检流程。' : '该来源建议已驳回。');
      setSelectedSuggestionId('');
      await Promise.all([loadSuggestions(), loadSources()]);
    } catch (err: any) {
      setError(err?.message || '官方来源补充任务处理失败');
    } finally {
      setBusy(null);
    }
  };

  const runSourceAction = async (action: 'validate' | 'refresh') => {
    if (!selectedId || busy) return;
    setBusy(action);
    setNotice('');
    setError('');
    try {
      if (action === 'validate') await validateKnowledgeSource(selectedId);
      else await refreshKnowledgeSource(selectedId);
      setNotice(action === 'validate' ? '官方来源校验已完成。' : '来源刷新已完成，状态和观察记录已更新。');
      await loadSources();
      await loadDetail(selectedId);
    } catch (err: any) {
      setError(err?.message || (action === 'validate' ? '来源校验失败' : '来源刷新失败'));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title={<span className="inline-flex items-center gap-2"><ShieldCheck className="h-5 w-5 text-accent" aria-hidden="true" />官方来源与刷新</span>}
        description="登记并校验厂商官网来源，检查内容是否更新；适合维护官方知识的可信度和新鲜度。"
        info="规则校验只检查 URL、域名白名单、版本范围和条款配置，不访问外网；联网刷新通过安全网关访问官网，比较内容变化并生成新的来源版本。"
        infoLabel="来源校验与刷新说明"
        actions={(
        <>
          <select value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value); setSourcePage(1); }} className="rounded-lg border border-line bg-surface px-3 py-2 text-xs text-fg" aria-label="来源状态筛选">
            <option value="all">全部状态</option><option value="active">已启用</option><option value="disabled">已停用</option><option value="draft">草稿</option><option value="quarantined">已隔离</option>
          </select>
          <button type="button" onClick={() => void loadSources()} disabled={loading} className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-xs font-semibold text-fg hover:bg-surface-muted disabled:opacity-50"><RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" />刷新列表</button>
        </>
        )}
      />

      {error && <div className="flex items-start gap-2 rounded-xl border border-danger/30 bg-danger-subtle px-3 py-2 text-xs text-danger "><XCircle className="mt-0.5 h-4 w-4 shrink-0" />{error}</div>}
      {notice && <div className="flex items-start gap-2 rounded-xl border border-success/30 bg-success-subtle px-3 py-2 text-xs text-success "><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />{notice}</div>}

      <Panel aria-label="未命中官方来源补充任务">
        <PanelHeader
          title="未命中官方来源补充任务"
          description="Copilot 本地未命中后自动记录；管理员确认范围与 HTTPS 官方 URL 后，系统才会采集、入库并回检原 Trace。"
          actions={<select aria-label="补充任务状态" value={suggestionStatus} onChange={(event) => setSuggestionStatus(event.target.value)} className="rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs text-fg"><option value="pending">待审核</option><option value="failed">失败</option><option value="collecting">采集中</option><option value="imported">已入库</option><option value="rejected">已驳回</option><option value="all">全部</option></select>}
        />
        <div className="p-4">
        {suggestions.length === 0 ? <EmptyState className="py-8" title="当前没有该状态的补充任务" description="Copilot 本地未命中时会自动在这里生成待审核任务。" /> : (
          <div className="grid gap-3 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
            <div className="max-h-72 space-y-2 overflow-y-auto">{suggestions.map((item) => <button key={item.id} type="button" onClick={() => selectSuggestion(item)} className={`w-full rounded-lg border p-3 text-left ${selectedSuggestionId === item.id ? 'border-accent/30 bg-accent-subtle' : 'border-line bg-surface hover:bg-surface-muted'}`}><div className="flex justify-between gap-2"><span className="truncate text-xs font-semibold text-fg ">{item.label}</span><StatusBadge tone={item.status === 'imported' ? 'success' : item.status === 'failed' || item.status === 'rejected' ? 'danger' : 'warning'}>{suggestionStatusLabel[item.status] || item.status}</StatusBadge></div><p className="mt-1 truncate text-xs text-fg-muted">{item.vendor} · {item.product_model || '待填型号'} · {item.software_release || '待填版本'} · {item.feature || '待填功能'}</p><p className="mt-1 truncate text-xs text-fg-subtle">检索追踪 {item.trace_id}</p></button>)}</div>
            {selectedSuggestion ? <div className="grid gap-2 rounded-lg border border-line p-3 sm:grid-cols-2">
              {([['vendor', '厂商'], ['product_model', '型号'], ['software_release', '软件版本'], ['feature', '功能']] as const).map(([key, label]) => <label key={key} className="text-xs text-fg-muted">{label}<input value={reviewDraft[key]} onChange={(event) => setReviewDraft((current) => ({ ...current, [key]: event.target.value }))} className="mt-1 w-full rounded-lg border border-line px-2.5 py-2 text-xs " /></label>)}
              <label className="text-xs text-fg-muted">来源类型<select value={reviewDraft.source_kind} onChange={(event) => setReviewDraft((current) => ({ ...current, source_kind: event.target.value }))} className="mt-1 w-full rounded-lg border border-line bg-surface px-2.5 py-2 text-xs ">{officialSourceKinds.map((kind) => <option key={kind} value={kind}>{sourceKindLabel[kind]}</option>)}</select></label>
              <label className="text-xs text-fg-muted sm:col-span-2">官方 HTTPS URL<input value={reviewDraft.url} onChange={(event) => setReviewDraft((current) => ({ ...current, url: event.target.value }))} className="mt-1 w-full rounded-lg border border-line px-2.5 py-2 text-xs " /></label>
              <div className="flex gap-2 sm:col-span-2"><button type="button" disabled={Boolean(busy)} onClick={() => void reviewSuggestion('approve')} className="rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-white hover:bg-accent-hover disabled:opacity-50">{busy === 'suggestion:approve' ? '校验采集中…' : '确认并采集入库'}</button><button type="button" disabled={Boolean(busy)} onClick={() => void reviewSuggestion('reject')} className="rounded-lg border border-line px-3 py-2 text-xs font-semibold text-fg-muted disabled:opacity-50 ">驳回</button></div>
            </div> : <EmptyState className="min-h-40 justify-center" title="选择一条补充任务" description="选择一条任务后确认厂商、型号、版本、功能与 URL。" />}
          </div>
        )}
        </div>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)]">
        <Panel aria-label="注册来源">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3">
            <span className="text-xs font-semibold text-fg ">注册来源（共 {sourceTotal} 条）</span>
            <label className="text-xs text-fg-muted">每页
              <select value={sourcePageSize} onChange={(event) => { setSourcePageSize(Number(event.target.value)); setSourcePage(1); }} className="ml-1 rounded-lg border border-line bg-surface px-2 py-1 text-xs " aria-label="来源每页条数">
                <option value={20}>20</option><option value={50}>50</option><option value={100}>100</option>
              </select>
            </label>
          </div>
          {loading ? <div className="flex items-center gap-2 px-4 py-8 text-xs text-fg-subtle"><Loader2 className="h-4 w-4 animate-spin" />正在加载…</div> : sources.length === 0 ? <EmptyState className="m-4" icon={ShieldCheck} title="暂无来源" description="还没有登记官方来源，或当前筛选没有结果。" /> : <div className="max-h-[560px] overflow-y-auto p-2">{sources.map((source) => {
            const active = source.id === selectedId;
            return <button key={source.id} type="button" onClick={() => setSelectedId(source.id)} className={`w-full rounded-lg p-3 text-left transition ${active ? 'bg-accent-subtle ring-1 ring-accent/30' : 'hover:bg-surface-muted'}`}>
              <div className="flex items-start justify-between gap-2"><span className="min-w-0 truncate text-xs font-semibold text-fg ">{source.name || source.canonical_url}</span><StatusBadge dot tone={statusTone(source.status)}>{sourceStatusLabel[source.status] || source.status}</StatusBadge></div>
              <div className="mt-1 truncate text-xs text-fg-muted" title={source.canonical_url}>{source.canonical_url}</div>
              <div className="mt-2 flex flex-wrap gap-1.5 text-xs"><StatusBadge tone={statusTone(source.validation_status)}>校验：{validationStatusLabel[source.validation_status] || source.validation_status}</StatusBadge><StatusBadge>{sourceKindLabel[source.source_kind] || source.source_kind}</StatusBadge></div>
            </button>;
          })}</div>}
          {sourceTotal > sourcePageSize && <div className="border-t border-line px-3 py-2"><Pagination currentPage={sourcePage} totalItems={sourceTotal} itemsPerPage={sourcePageSize} onPageChange={setSourcePage} language="zh" /></div>}
        </Panel>

        <Panel aria-label="来源刷新状态">
          {!selected ? <EmptyState className="m-4 min-h-[260px] justify-center" icon={Clock3} title="选择一个来源" description="选择一个来源查看刷新状态。" /> : <>
            <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-3 "><div className="min-w-0"><h3 className="truncate text-sm font-semibold text-fg ">{selected.name || selected.canonical_url}</h3><p className="mt-1 truncate text-xs text-fg-muted">{selected.canonical_url}</p></div><div className="flex gap-2"><button type="button" onClick={() => void runSourceAction('validate')} disabled={Boolean(busy)} className="rounded-lg border border-accent/30 px-2.5 py-1.5 text-xs font-semibold text-accent hover:bg-accent-subtle disabled:opacity-50 ">{busy === 'validate' ? '校验中…' : '规则校验'}</button><button type="button" onClick={() => void runSourceAction('refresh')} disabled={Boolean(busy) || !selected.fetch_enabled} className="inline-flex items-center gap-1 rounded-lg bg-accent px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-accent-hover disabled:opacity-50"><RefreshCw className="h-3 w-3" />{busy === 'refresh' ? '刷新中…' : '联网刷新'}</button></div></div>
            {detailLoading ? <div className="flex items-center gap-2 px-4 py-8 text-xs text-fg-subtle"><Loader2 className="h-4 w-4 animate-spin" />正在读取刷新状态…</div> : <div className="space-y-4 p-4">
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4"><div className="rounded-lg border border-line p-3"><div className="text-xs text-fg-subtle">刷新状态</div><div className="mt-1"><StatusBadge dot tone={statusTone(refreshStatus?.freshness_status || 'unknown')}>{freshnessLabel[refreshStatus?.freshness_status || ''] || refreshStatus?.freshness_status || '未知'}</StatusBadge></div></div><div className="rounded-lg border border-line p-3"><div className="text-xs text-fg-subtle">最近结果</div><div className="mt-1 text-xs font-semibold text-fg ">{observationStatusLabel[refreshStatus?.last_outcome || ''] || refreshStatus?.last_outcome || '—'}</div></div><div className="rounded-lg border border-line p-3"><div className="text-xs text-fg-subtle">观察记录</div><div className="mt-1 text-xs font-semibold text-fg ">{refreshStatus?.observation_count ?? 0}</div></div><div className="rounded-lg border border-line p-3"><div className="text-xs text-fg-subtle">最近检查</div><div className="mt-1 truncate text-xs font-semibold text-fg " title={refreshStatus?.last_checked_at || ''}>{safeTime(refreshStatus?.last_checked_at)}</div></div></div>
              {refreshStatus?.last_error_code && <div className="flex items-start gap-2 rounded-xl border border-warning/30 bg-warning-subtle px-3 py-2 text-xs text-warning "><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />稳定错误码：{refreshStatus.last_error_code}</div>}
              <div><div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-fg "><Clock3 className="h-3.5 w-3.5 text-accent" />最近刷新观察</div>{observations.length === 0 ? <EmptyState className="py-6" title="暂无观察记录" description="执行一次联网刷新后会记录在这里。" /> : <div className="max-h-64 overflow-y-auto rounded-xl border border-line ">{observations.map((item) => { const state = item.detection_type && item.detection_type !== 'none' ? item.detection_type : item.outcome; return <div key={item.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-3 py-2 text-xs last:border-b-0 "><span className="text-fg-subtle">{safeTime(item.checked_at)}</span><StatusBadge tone={statusTone(state)}>{observationStatusLabel[state] || state}</StatusBadge><span className="text-fg-muted">HTTP {item.http_status || '—'}</span><span className="text-fg-muted">{item.error_code || '无错误'}</span></div>; })}</div>}</div>
            </div>}
          </>}
        </Panel>
      </div>
    </div>
  );
};

export default SourceRegistryPanel;
