import React, { useState } from 'react';
import { ChevronDown, ChevronUp, FileSearch, Play, SearchX, ShieldCheck, SlidersHorizontal, Search, LoaderCircle } from 'lucide-react';
import { runKnowledgeRetrievalTest, type RetrievalTestResult } from '../../../api/ai';
import { cn } from '../../../lib/cn';
import { ActionButton } from '../../../components/ui/ActionIconButton';
import { PageHeader } from '../../../components/ui/PageHeader';
import { Panel, PanelHeader } from '../../../components/ui/Panel';
import { StatusBadge } from '../../../components/ui/StatusBadge';
import { SummaryBar, type SummaryItem } from '../../../components/ui/SummaryBar';
import { EmptyState } from '../../../components/ui/EmptyState';

const VENDOR_OPTIONS = ['', 'Huawei', 'H3C', 'Cisco', 'Ruijie', 'Juniper', 'Fortinet', 'Aruba'];
const CATEGORY_OPTIONS = [
  { value: '', label: '全部类别' },
  { value: 'configuration', label: '配置指南 (configuration)' },
  { value: 'command_reference', label: '命令参考 (command_reference)' },
  { value: 'troubleshooting', label: '故障排查 (troubleshooting)' },
  { value: 'hardware', label: '硬件/产品目录 (hardware)' },
  { value: 'sop', label: '企业 SOP (sop)' },
];

const fieldLabelClass = 'mb-1.5 block text-xs font-medium text-fg-muted';
const fieldInputClass = 'w-full rounded-lg border border-line bg-surface px-3 py-2 text-[13px] text-fg outline-none transition-colors placeholder:text-fg-subtle focus:border-accent focus:ring-2 focus:ring-accent/20';

const ENGINE_LABELS: Record<string, string> = {
  v1: 'V1 精确扫描',
  v2_indexed: 'V2 索引检索',
  v2_exact_small_set: 'V2 精确路径（小知识库）',
};

const debugNumber = (value: unknown): number | null => {
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const stageLabel = (debug: Record<string, unknown> | undefined): string => (
  debug?.fts_stage === 'disabled' && debug?.vector_stage === 'disabled'
    ? '精准规则与词法检索'
    : `FTS: ${String(debug?.fts_stage || 'off')} · 向量: ${String(debug?.vector_stage || 'off')}`
);

/** Summary of one retrieval run, built only from fields the API returns. */
export const buildRetrievalSummary = (result: RetrievalTestResult): SummaryItem[] => {
  const debug = result.debug || {};
  const items: SummaryItem[] = [
    { key: 'chunks', value: result.final_chunks?.length || 0, label: '最终命中 Chunk', tone: result.final_chunks?.length ? 'success' : 'warning' },
  ];
  const candidates = debugNumber(debug.candidate_count);
  if (candidates !== null) items.push({ key: 'candidates', value: candidates, label: '候选分块' });
  const engine = typeof debug.retrieval_engine === 'string' ? debug.retrieval_engine : '';
  if (engine) items.push({ key: 'engine', value: ENGINE_LABELS[engine] || engine, label: '检索引擎' });
  const latency = debugNumber(debug.retrieval_latency_ms);
  if (latency !== null) items.push({ key: 'latency', value: `${Math.round(latency)} ms`, label: '检索耗时' });
  items.push({
    key: 'resolution',
    value: result.resolution?.ambiguous ? '需要澄清' : '唯一/可检索',
    label: '产品解析',
    tone: result.resolution?.ambiguous ? 'warning' : 'success',
  });
  return items;
};

export const RetrievalTestTab: React.FC = () => {
  const [query, setQuery] = useState('display ospf peer');
  const [vendor, setVendor] = useState('Huawei');
  const [productModel, setProductModel] = useState('');
  const [cliPlatform, setCliPlatform] = useState('');
  const [documentCategory, setDocumentCategory] = useState('');
  const [showAdvancedJson, setShowAdvancedJson] = useState(false);
  const [filtersText, setFiltersText] = useState('{}');
  const [result, setResult] = useState<RetrievalTestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const run = async (event: React.FormEvent | React.KeyboardEvent<HTMLInputElement>) => {
    event.preventDefault();
    if (!query.trim() || loading) return;
    setError('');
    let extraFilters: Record<string, unknown> = {};
    if (showAdvancedJson && filtersText.trim()) {
      try {
        const parsed = JSON.parse(filtersText);
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
          throw new Error('高级过滤条件必须是 JSON 对象');
        }
        extraFilters = parsed as Record<string, unknown>;
      } catch (err: any) {
        setError(err?.message || '高级过滤条件 JSON 格式无效');
        return;
      }
    }
    const filters: Record<string, unknown> = { ...extraFilters };
    if (vendor.trim()) filters.vendor = vendor.trim();
    if (productModel.trim()) filters.product_model = productModel.trim();
    if (cliPlatform.trim()) filters.cli_platform = cliPlatform.trim();
    if (documentCategory.trim()) filters.document_category = documentCategory.trim();

    setLoading(true);
    try {
      setResult(await runKnowledgeRetrievalTest(query.trim(), filters));
    } catch (err: any) {
      setError(err?.message || '检索测试失败');
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  const entityRows = Object.entries(result?.entities || {})
    .filter(([, value]) => value !== null && value !== '' && value !== undefined);

  return (
    <div className="w-full space-y-4 pb-8">
      <PageHeader
        title="管理员检索测试沙箱"
        description="调试 Query 实体解析、Metadata 硬过滤、候选产品归属、分块召回打分与 PostgreSQL 检索阶段。"
        info="页面严格屏蔽密钥与原始 SQL；权限与租户由服务端根据当前会话强制绑定，不能在页面上指定。"
        infoLabel="关于检索测试"
        actions={(
          <StatusBadge tone="success">
            <ShieldCheck size={13} aria-hidden="true" /> 权限与租户由服务端强制绑定
          </StatusBadge>
        )}
      />

      <Panel as="div" className="p-4">
        <form onSubmit={run} className="space-y-4" aria-label="检索测试条件">
          <div className="flex flex-col gap-3 sm:flex-row">
            <label className="relative flex flex-1 items-center">
              <span className="sr-only">测试查询</span>
              <Search className="pointer-events-none absolute left-3 h-4 w-4 text-fg-subtle" aria-hidden="true" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault();
                    void run(event);
                  }
                }}
                className={cn(fieldInputClass, 'h-10 pl-9 text-sm')}
                placeholder="输入测试查询，例如：Huawei CE6885 display ospf peer"
              />
            </label>
            <ActionButton
              type="submit"
              variant="primary"
              size="md"
              icon={loading ? LoaderCircle : Play}
              iconClassName={loading ? 'animate-spin motion-reduce:animate-none' : undefined}
              disabled={loading || !query.trim()}
              className="shrink-0"
            >
              {loading ? '检索中...' : '执行检索测试'}
            </ActionButton>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="block">
              <span className={fieldLabelClass}>厂商过滤 (Vendor)</span>
              <select value={vendor} onChange={(e) => setVendor(e.target.value)} className={fieldInputClass}>
                {VENDOR_OPTIONS.map((v) => (
                  <option key={v || 'all'} value={v}>{v || '全部厂商'}</option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className={fieldLabelClass}>产品型号 (Model)</span>
              <input
                value={productModel}
                onChange={(e) => setProductModel(e.target.value)}
                placeholder="如 CE6885-48YS8CQ"
                className={fieldInputClass}
              />
            </label>
            <label className="block">
              <span className={fieldLabelClass}>CLI 平台 (Platform)</span>
              <input
                value={cliPlatform}
                onChange={(e) => setCliPlatform(e.target.value)}
                placeholder="如 huawei_vrp / cisco_iosxe"
                className={cn(fieldInputClass, 'font-mono')}
              />
            </label>
            <label className="block">
              <span className={fieldLabelClass}>文档类别 (Category)</span>
              <select value={documentCategory} onChange={(e) => setDocumentCategory(e.target.value)} className={fieldInputClass}>
                {CATEGORY_OPTIONS.map((opt) => (
                  <option key={opt.value || 'all'} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </label>
          </div>

          <div className="border-t border-line pt-3">
            <button
              type="button"
              onClick={() => setShowAdvancedJson((v) => !v)}
              aria-expanded={showAdvancedJson}
              className="inline-flex items-center gap-1.5 rounded-md text-xs font-medium text-fg-muted transition-colors hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              <SlidersHorizontal className="h-3.5 w-3.5" aria-hidden="true" />
              高级 JSON 过滤扩展
              {showAdvancedJson ? <ChevronUp className="h-3.5 w-3.5" aria-hidden="true" /> : <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />}
            </button>
            {showAdvancedJson && (
              <textarea
                value={filtersText}
                onChange={(event) => setFiltersText(event.target.value)}
                aria-label="高级 JSON 过滤条件"
                className={cn(fieldInputClass, 'mt-2 h-24 resize-y bg-surface-muted font-mono text-xs')}
                placeholder='{"feature": "ospf", "knowledge_scope": "official"}'
              />
            )}
          </div>
        </form>
      </Panel>

      {error && (
        <div role="alert" className="rounded-lg border border-danger/30 bg-danger-subtle px-4 py-3 text-[13px] text-danger">
          {error}
        </div>
      )}

      {!result && !error && (
        <EmptyState
          icon={FileSearch}
          title="尚未执行检索测试"
          description="输入查询并选择过滤条件后执行，这里会显示实体解析、产品候选和最终命中的分块与打分。"
        />
      )}

      {result && (
        <>
          <SummaryBar label="检索结果概览" items={buildRetrievalSummary(result)} />

          <div className="grid gap-4 xl:grid-cols-[0.85fr_1.15fr]">
            <div className="space-y-4">
              <Panel>
                <PanelHeader title="实体与硬过滤状态" />
                <div className="px-4 py-3">
                  {entityRows.length ? (
                    <dl className="divide-y divide-line text-xs">
                      {entityRows.map(([key, value]) => (
                        <div key={key} className="flex justify-between gap-3 py-2">
                          <dt className="font-mono text-fg-muted">{key}</dt>
                          <dd className="max-w-[65%] break-words text-right font-medium text-fg">
                            {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  ) : (
                    <p className="py-2 text-xs text-fg-muted">未识别到实体或硬过滤条件。</p>
                  )}
                </div>
              </Panel>

              <Panel>
                <PanelHeader
                  title="产品解析候选"
                  actions={(
                    <div className="flex flex-wrap gap-1.5">
                      <StatusBadge>结果：{result.resolution?.outcome || 'unknown'}</StatusBadge>
                      <StatusBadge tone={result.resolution?.ambiguous ? 'warning' : 'success'} dot>
                        {result.resolution?.ambiguous ? '需要澄清' : '唯一/可检索'}
                      </StatusBadge>
                    </div>
                  )}
                />
                <div className="p-4">
                  <pre className="max-h-64 overflow-auto rounded-lg border border-line bg-surface-muted p-3 font-mono text-[11px] leading-5 text-fg">
                    {JSON.stringify(result.resolution?.candidates || [], null, 2)}
                  </pre>
                </div>
              </Panel>
            </div>

            <Panel>
              <PanelHeader
                title={`最终命中 Chunk（${result.final_chunks?.length || 0}）`}
                actions={<StatusBadge mono>{stageLabel(result.debug)}</StatusBadge>}
              />
              <div className="p-4">
                {result.final_chunks?.length ? (
                  <div className="space-y-3">
                    {result.final_chunks.map((item, index) => (
                      <article
                        key={item.chunk_id || `${item.document_id || 'chunk'}-${index}`}
                        className="rounded-lg border border-line bg-surface p-4 transition-colors hover:border-line-strong hover:bg-accent-subtle/40"
                      >
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p className="truncate text-[13px] font-semibold text-fg" title={item.document_name || item.document_id}>
                              <span className="mr-1.5 tabular-nums text-fg-subtle">#{index + 1}</span>
                              {item.document_name || item.document_id}
                            </p>
                            <p className="mt-1 text-xs text-fg-muted">
                              {item.section || 'General'} · {item.platform || '平台未指定'} · {item.version_evidence || '版本证据未请求'}
                            </p>
                          </div>
                          <StatusBadge tone="accent" mono>Score {Number(item.score || 0).toFixed(3)}</StatusBadge>
                        </div>
                        {item.score_components && typeof item.score_components === 'object' && (
                          <div className="mt-2 flex flex-wrap gap-1.5">
                            {Object.entries(item.score_components)
                              .filter(([, val]) => typeof val === 'number')
                              .map(([k, val]) => (
                                <span key={k} className="rounded-md border border-line bg-surface-muted px-2 py-0.5 font-mono text-[11px] text-fg-muted">
                                  {k}: {Number(val).toFixed(2)}
                                </span>
                              ))}
                          </div>
                        )}
                        <pre className="mt-3 max-h-52 overflow-auto whitespace-pre-wrap rounded-md border border-line bg-surface-muted p-3 text-xs leading-5 text-fg">
                          {item.content}
                        </pre>
                      </article>
                    ))}
                  </div>
                ) : (
                  <EmptyState
                    icon={SearchX}
                    title="没有命中的 Chunk"
                    description="没有满足硬过滤和证据门槛的 Chunk。请调整过滤条件或查询词重试。"
                    className="py-10"
                  />
                )}
              </div>
            </Panel>
          </div>
        </>
      )}
    </div>
  );
};

export default RetrievalTestTab;
