import React, { useCallback, useEffect, useState } from 'react';
import { Activity, AlertCircle, Eye, Hash, RefreshCw, ShieldCheck } from 'lucide-react';
import { getKnowledgeRetrievalTrace, listKnowledgeRetrievalTraces, type KnowledgeRetrievalTrace } from '../../../api/ai';
import { PageHeader } from '../../../components/ui/PageHeader';
import { Panel, PanelHeader } from '../../../components/ui/Panel';
import { EmptyState } from '../../../components/ui/EmptyState';
import { StatusBadge, type StatusTone } from '../../../components/ui/StatusBadge';

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Retrieval Trace 请求失败';
}

function shortHash(value: string | null | undefined): string {
  const text = String(value || '');
  return text ? `${text.slice(0, 12)}…` : '--';
}

const traceStatusLabel: Record<string, string> = {
  hit: '已命中',
  no_match: '未命中',
};

const traceStatusTone: Record<string, StatusTone> = {
  hit: 'success',
  no_match: 'warning',
};

export const RetrievalTracePanel: React.FC = () => {
  const [status, setStatus] = useState('all');
  const [items, setItems] = useState<KnowledgeRetrievalTrace[]>([]);
  const [selected, setSelected] = useState<KnowledgeRetrievalTrace | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const result = await listKnowledgeRetrievalTraces(status, 50);
      setItems(result.items || []);
      setSelected((current) => current && result.items.some((item) => item.trace_id === current.trace_id) ? current : (result.items[0] || null));
    } catch (cause) {
      setError(errorMessage(cause));
      setItems([]);
      setSelected(null);
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => { void load(); }, [load]);

  const select = async (item: KnowledgeRetrievalTrace) => {
    setSelected(item);
    try {
      setSelected(await getKnowledgeRetrievalTrace(item.trace_id));
    } catch (cause) {
      setError(errorMessage(cause));
    }
  };

  return (
    <div className="mx-auto w-full space-y-4 text-fg">
      <PageHeader
        title={<span className="inline-flex items-center gap-2"><Activity className="h-5 w-5 text-accent" aria-hidden="true" />检索过程追踪</span>}
        description="查看一次本地知识检索经过了哪些筛选、产生多少候选文档，以及最终为何命中或未命中。适合排查 Copilot 无引用、答非所问或找不到知识的问题。"
        info="默认脱敏，不展示问题正文、知识片段、SQL、URL、文档 ID 或凭据。"
        infoLabel="检索过程追踪说明"
        actions={(
          <>
            <StatusBadge tone="success"><ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />租户隔离 · 默认脱敏</StatusBadge>
            <button type="button" onClick={() => void load()} disabled={loading} className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-xs font-semibold text-fg hover:bg-surface-muted disabled:opacity-50"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" />刷新</button>
          </>
        )}
      />
      <p className="text-xs leading-5 text-warning">这是当前服务实例的临时诊断记录，最多保留 200 条，服务重启后清空，不等同于持久审计日志。</p>

      {error && <div role="alert" className="flex items-center gap-2 rounded-lg border border-danger/30 bg-danger-subtle px-4 py-3 text-sm text-danger"><AlertCircle className="h-4 w-4" aria-hidden="true" />{error}</div>}

      <div className="grid gap-4 lg:grid-cols-[0.8fr_1.2fr]">
        <Panel aria-label="最近检索记录">
          <PanelHeader
            title="最近检索记录"
            actions={(
              <select value={status} onChange={(event) => setStatus(event.target.value)} className="rounded-lg border border-line bg-surface px-2 py-1.5 text-xs text-fg" aria-label="检索状态">
                <option value="all">全部状态</option><option value="hit">已命中</option><option value="no_match">未命中</option>
              </select>
            )}
          />
          <div className="p-4">
            {loading && !items.length ? (
              <p className="rounded-lg bg-surface-muted p-8 text-center text-sm text-fg-muted">正在加载检索记录…</p>
            ) : items.length ? (
              <div className="space-y-2">{items.map((item) => (
                <button type="button" key={item.trace_id} onClick={() => void select(item)} className={`w-full rounded-lg border p-3 text-left transition ${selected?.trace_id === item.trace_id ? 'border-accent/30 bg-accent-subtle' : 'border-line hover:border-accent/30 hover:bg-surface-muted'}`}>
                  <div className="flex items-center justify-between gap-2"><span className="font-mono text-xs font-semibold text-fg">{shortHash(item.trace_id)}</span><StatusBadge dot tone={traceStatusTone[item.status] || 'neutral'}>{traceStatusLabel[item.status] || item.status}</StatusBadge></div>
                  <div className="mt-2 flex flex-wrap gap-2 text-xs text-fg-muted"><span>{item.created_at}</span><span>候选文档 {item.candidate_count}</span><span>最终采用 {item.final_document_count}</span></div>
                </button>
              ))}</div>
            ) : (
              <EmptyState icon={Eye} title="暂无检索记录" description="先在 Copilot 中提问，或执行一次本地检索。" />
            )}
          </div>
        </Panel>

        <Panel aria-label="检索详情" className="p-5">
          {selected ? <>
            <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
              <div><h2 className="text-base font-semibold text-fg">检索详情</h2><p className="mt-1 font-mono text-xs text-fg-muted">{selected.trace_id}</p></div>
              <StatusBadge tone="accent" mono><Hash className="h-3.5 w-3.5" aria-hidden="true" />问题摘要 {shortHash(selected.query_hash)}</StatusBadge>
            </div>
            <div className="grid gap-2 sm:grid-cols-4">{[
              ['元数据候选', selected.metadata_candidate_documents],
              ['检索候选', selected.candidate_count],
              ['去重文档', selected.dedup_document_count],
              ['最终采用', selected.final_document_count],
            ].map(([label, value]) => <div key={String(label)} className="rounded-lg border border-line p-3"><div className="text-xs text-fg-muted">{label}</div><div className="mt-1 text-xl font-semibold tabular-nums text-fg">{String(value)}</div></div>)}</div>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div className="rounded-lg border border-line p-3"><h3 className="mb-2 text-xs font-semibold text-fg">实体与解析</h3><dl className="space-y-1.5 text-xs">{Object.entries(selected.request || {}).map(([key, value]) => <div key={key} className="flex justify-between gap-2"><dt className="text-fg-muted">{key}</dt><dd className="text-right font-medium text-fg">{String(value ?? '—')}</dd></div>)}<div className="flex justify-between gap-2"><dt className="text-fg-muted">是否存在歧义</dt><dd className="font-medium text-fg">{selected.resolution?.ambiguous ? '是' : '否'}</dd></div><div className="flex justify-between gap-2"><dt className="text-fg-muted">平台候选</dt><dd className="text-right font-medium text-fg">{selected.resolution?.platform_candidates?.join('、') || '无'}</dd></div></dl></div>
              <div className="rounded-lg border border-line p-3"><h3 className="mb-2 text-xs font-semibold text-fg">检索阶段</h3><dl className="space-y-1.5 text-xs"><div className="flex justify-between gap-2"><dt className="text-fg-muted">检索来源</dt><dd className="font-medium text-fg">{selected.source}</dd></div><div className="flex justify-between gap-2"><dt className="text-fg-muted">向量候选上限</dt><dd className="font-medium text-fg">{selected.vector_top_n}</dd></div><div className="flex justify-between gap-2"><dt className="text-fg-muted">需要澄清</dt><dd className="font-medium text-fg">{selected.clarification_required ? '是' : '否'}</dd></div><div className="flex justify-between gap-2"><dt className="text-fg-muted">跨平台检索</dt><dd className="font-medium text-fg">{selected.cross_platform_search ? '是' : '否'}</dd></div></dl></div>
            </div>
            <div className="mt-4 rounded-lg border border-line p-3"><div className="mb-2 flex items-center justify-between"><h3 className="text-xs font-semibold text-fg">引用摘要</h3><span className="text-xs text-fg-muted">告警 {selected.citation_warning_count}</span></div>{selected.citations?.length ? <div className="grid gap-2 sm:grid-cols-2">{selected.citations.map((citation) => <div key={citation.citation_id} className="rounded-lg bg-surface-muted p-2.5 text-xs"><div className="flex justify-between gap-2"><span className="font-mono text-fg">{shortHash(citation.citation_id)}</span><span className="text-fg-muted">{citation.validation}</span></div><div className="mt-1 text-fg-muted">{citation.vendor || '厂商未指定'} · {citation.product || '产品未指定'} · {citation.software_version || '版本未指定'}</div></div>)}</div> : <p className="text-xs text-fg-muted">本次检索没有可用引用。</p>}</div>
            <p className="mt-4 text-xs leading-5 text-fg-muted">默认脱敏：问题和知识片段正文、SQL、URL、文档及片段 ID、凭据均不会进入此查看器；问题仅显示 SHA-256 摘要。</p>
          </> : <EmptyState className="min-h-[340px] justify-center" icon={Eye} title="选择一条检索记录" description="选择左侧的一条记录查看安全摘要。" />}
        </Panel>
      </div>
    </div>
  );
};

export default RetrievalTracePanel;
