import React, { useEffect, useState } from 'react';
import { X, Cpu, Clock, Database, Layers, ShieldAlert, Code, Copy, Check } from 'lucide-react';
import type { AssistantRetrievalTrace } from '../../../api/ai';
import { ActionButton } from '../../../components/ui/ActionIconButton';

interface CopilotInspectorDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  activeMessage?: any;
}

export const CopilotInspectorDrawer: React.FC<CopilotInspectorDrawerProps> = ({
  isOpen,
  onClose,
  activeMessage,
}) => {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!isOpen) return undefined;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleCopyPayload = () => {
    if (!activeMessage) return;
    void navigator.clipboard.writeText(JSON.stringify(activeMessage, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const retrieval = activeMessage?.retrieval as AssistantRetrievalTrace | undefined;
  const retrievalRequest = retrieval?.request || {};
  const retrievalStatus = retrieval?.status === 'clarification_required'
    ? '本地策略已拦截 · 未检索知识库正文'
    : retrieval?.status === 'no_match'
    ? '本地 RAG 已执行 · 精确检索未命中'
    : retrieval?.status === 'hit'
      ? '本地 RAG 已执行 · 已命中'
      : '未收到本次检索 Trace';
  const llmSkipped = retrieval?.status === 'no_match' || retrieval?.status === 'clarification_required';
  const metric = (value: unknown, suffix = '') => (
    typeof value === 'number' && Number.isFinite(value) ? `${value}${suffix}` : (llmSkipped ? '未调用' : '未上报')
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 p-4 backdrop-blur-[1px] sm:p-6"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="relative flex h-[min(82vh,760px)] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-gray-200/80 bg-white shadow-2xl dark:border-gray-700 dark:bg-gray-900"
        role="dialog"
        aria-modal="true"
        aria-labelledby="copilot-inspector-title"
      >
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-gray-200/80 p-3.5 select-none dark:border-gray-800">
          <div className="flex items-center gap-2 font-bold text-gray-900 dark:text-white">
            <Cpu className="h-4 w-4 text-indigo-500" />
            <span id="copilot-inspector-title">开发者调试 Trace (Inspector)</span>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭调试 Trace"
            className="rounded-lg p-1 text-gray-400 transition hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-800 dark:hover:text-gray-200"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Content Body */}
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 pb-12 select-text">
        {activeMessage?.copilot && (
          <div className="space-y-2 p-3 bg-indigo-50/70 dark:bg-indigo-950/20 rounded-xl border border-indigo-100 dark:border-indigo-900/60">
            <div className="font-semibold text-indigo-700 dark:text-indigo-300">工程师证据面板</div>
            <div className="space-y-1 text-[11px] text-gray-600 dark:text-gray-300">
              <div>意图：{activeMessage.copilot.intent || 'consultation'} · 风险：{activeMessage.copilot.risk || 'low'}</div>
              <div>设备连接：{activeMessage.copilot.runtime?.device_connected ? '是' : '否'} · CLI：{activeMessage.copilot.runtime?.cli_executed ? '已执行' : '未执行'}</div>
              <div>外发：{activeMessage.copilot.runtime?.external_egress ? '已通过安全网关' : '未外发'}</div>
              {(activeMessage.copilot.source_labels || []).length > 0 && <div>证据来源：{activeMessage.copilot.source_labels.join('、')}</div>}
            </div>
          </div>
        )}
        {/* Intent & Scene Routing */}
        <div className="space-y-2 p-3 bg-gray-50 dark:bg-gray-800/50 rounded-xl border border-gray-200/60 dark:border-gray-700/60">
          <div className="font-semibold text-gray-700 dark:text-gray-300 flex items-center gap-1.5">
            <Layers className="w-3.5 h-3.5 text-indigo-500" /> 意图与路由分析
          </div>
          <div className="font-mono text-[11px] space-y-1">
            <div className="flex justify-between">
              <span className="text-gray-400">Intent:</span>
              <span className="font-semibold text-indigo-600 dark:text-indigo-400">{activeMessage?.intent || 'GENERAL_QA'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">Scene Key:</span>
              <span className="text-gray-700 dark:text-gray-300">chat</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">Route Model:</span>
              <span className="text-gray-700 dark:text-gray-300 font-semibold">{activeMessage?.route_model || (llmSkipped ? '未调用' : '未上报')}</span>
            </div>
          </div>
        </div>

        {/* Performance & Token Metrics */}
        <div className="space-y-2 p-3 bg-gray-50 dark:bg-gray-800/50 rounded-xl border border-gray-200/60 dark:border-gray-700/60">
          <div className="font-semibold text-gray-700 dark:text-gray-300 flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5 text-emerald-500" /> 性能与开销
          </div>
          <div className="font-mono text-[11px] space-y-1">
            <div className="flex justify-between">
              <span className="text-gray-400">Total Latency:</span>
              <span className="text-emerald-600 dark:text-emerald-400 font-medium">{metric(activeMessage?.latency_ms, ' ms')}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">Input Tokens:</span>
              <span className="text-gray-700 dark:text-gray-300">{metric(activeMessage?.input_tokens, ' tokens')}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">Output Tokens:</span>
              <span className="text-gray-700 dark:text-gray-300">{metric(activeMessage?.output_tokens, ' tokens')}</span>
            </div>
          </div>
        </div>

        {/* Vector Retrieval Details */}
        <div className="space-y-2 p-3 bg-gray-50 dark:bg-gray-800/50 rounded-xl border border-gray-200/60 dark:border-gray-700/60">
          <div className="font-semibold text-gray-700 dark:text-gray-300 flex items-center gap-1.5">
            <Database className="w-3.5 h-3.5 text-blue-500" /> 知识库向量命中 (Top Hits)
          </div>
          {retrieval ? (
            <div className="space-y-2 font-mono text-[11px]">
              <div className={`rounded border px-2 py-1.5 ${retrieval.status === 'clarification_required' ? 'border-violet-200 bg-violet-50 text-violet-700 dark:border-violet-900/60 dark:bg-violet-950/20 dark:text-violet-300' : retrieval.status === 'no_match' ? 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-300' : 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900/60 dark:bg-blue-950/20 dark:text-blue-300'}`}>
                {retrievalStatus}
              </div>
              {retrieval.clarification_required && (
                <div className="rounded border border-violet-200 bg-violet-50 px-2 py-1.5 text-violet-700 dark:border-violet-900/60 dark:bg-violet-950/20 dark:text-violet-300">
                  澄清前不返回正文、不调用外部模型；补齐范围后才会重新检索。
                </div>
              )}
              <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-gray-500 dark:text-gray-400">
                <span>Metadata candidates</span><span className="text-right text-gray-700 dark:text-gray-200">{metric(retrieval.metadata_candidate_documents)}</span>
                <span>Final documents</span><span className="text-right text-gray-700 dark:text-gray-200">{metric(retrieval.final_document_count)}</span>
                <span>Vector top-N</span><span className="text-right text-gray-700 dark:text-gray-200">{metric(retrieval.vector_top_n)}</span>
              </div>
              {Object.keys(retrievalRequest).length > 0 && (
                <div className="rounded border border-gray-200 bg-white p-2 text-[10px] text-gray-500 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-400">
                  <div className="mb-1 font-semibold text-gray-700 dark:text-gray-200">精确检索条件</div>
                  {Object.entries(retrievalRequest).map(([key, value]) => (
                    <div key={key} className="flex justify-between gap-2"><span>{key}</span><span className="text-right text-gray-700 dark:text-gray-200">{String(value)}</span></div>
                  ))}
                </div>
              )}
              {retrieval.resolution?.ambiguous && (
                <div className="text-amber-600 dark:text-amber-300">平台候选存在歧义：{(retrieval.resolution.platform_candidates || []).join('、') || '未上报'}</div>
              )}
            </div>
          ) : activeMessage?.sources && activeMessage.sources.length > 0 ? (
            <div className="space-y-1.5 font-mono text-[11px]">
              {activeMessage.sources.map((src: any, idx: number) => (
                <div key={idx} className="p-2 bg-white dark:bg-gray-900 rounded border border-gray-200 dark:border-gray-700">
                  <div className="font-semibold text-gray-800 dark:text-gray-200">{src.document}</div>
                  <div className="text-[10px] text-gray-400">{src.section} · Relevance: 88%</div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-[11px] text-gray-400 py-1">未收到本次检索 Trace（可能是旧消息）</div>
          )}
        </div>

        {/* Raw JSON Trace */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <div className="font-semibold text-gray-700 dark:text-gray-300 flex items-center gap-1.5">
              <Code className="w-3.5 h-3.5 text-amber-500" /> 原始 Message Payload
            </div>
            <ActionButton
              type="button"
              icon={copied ? Check : Copy}
              variant={copied ? 'success' : 'accent'}
              size="sm"
              onClick={handleCopyPayload}
              title="复制 JSON 载荷"
              className="!h-7 !px-2 !text-[10px]"
            >
              {copied ? '已复制' : '复制 JSON'}
            </ActionButton>
          </div>
          <pre className="p-3 bg-[#0d1117] text-[#e6edf3] font-mono text-[10px] rounded-xl overflow-auto max-h-80 leading-relaxed border border-gray-800 select-all shadow-inner">
            {JSON.stringify(activeMessage || {}, null, 2)}
          </pre>
        </div>
        </div>
      </div>
    </div>
  );
};
