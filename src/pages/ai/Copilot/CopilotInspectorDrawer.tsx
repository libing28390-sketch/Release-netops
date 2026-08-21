import React, { useState } from 'react';
import { X, Cpu, Clock, Database, Layers, ShieldAlert, Code, Copy, Check } from 'lucide-react';
import type { AssistantRetrievalTrace } from '../../../api/ai';

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
  if (!isOpen) return null;

  const handleCopyPayload = () => {
    if (!activeMessage) return;
    void navigator.clipboard.writeText(JSON.stringify(activeMessage, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const retrieval = activeMessage?.retrieval as AssistantRetrievalTrace | undefined;
  const retrievalRequest = retrieval?.request || {};
  const retrievalStatus = retrieval?.status === 'no_match'
    ? '本地 RAG 已执行 · 精确检索未命中'
    : retrieval?.status === 'hit'
      ? '本地 RAG 已执行 · 已命中'
      : '未收到本次检索 Trace';
  const llmSkipped = retrieval?.status === 'no_match';
  const metric = (value: unknown, suffix = '') => (
    typeof value === 'number' && Number.isFinite(value) ? `${value}${suffix}` : (llmSkipped ? '未调用' : '未上报')
  );

  return (
    <aside className="w-96 sm:w-[420px] shrink-0 min-h-0 bg-white dark:bg-gray-900 border-l border-gray-200/80 dark:border-gray-800 flex flex-col h-full z-20 shadow-xl text-xs select-none">
      {/* Header */}
      <div className="p-3.5 border-b border-gray-200/80 dark:border-gray-800 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2 font-bold text-gray-900 dark:text-white">
          <Cpu className="w-4 h-4 text-indigo-500" />
          <span>开发者调试 Trace (Inspector)</span>
        </div>
        <button
          onClick={onClose}
          className="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Content Body */}
      <div className="flex-1 overflow-y-auto p-4 pb-12 space-y-4">
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
              <div className={`rounded border px-2 py-1.5 ${retrieval.status === 'no_match' ? 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-300' : 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900/60 dark:bg-blue-950/20 dark:text-blue-300'}`}>
                {retrievalStatus}
              </div>
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
            <button
              type="button"
              onClick={handleCopyPayload}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-gray-100 hover:bg-gray-200 dark:bg-gray-800 dark:hover:bg-gray-700 text-[10px] text-gray-600 dark:text-gray-300 transition"
              title="复制 JSON 载荷"
            >
              {copied ? <Check className="w-3 h-3 text-emerald-500" /> : <Copy className="w-3 h-3" />}
              {copied ? '已复制' : '复制 JSON'}
            </button>
          </div>
          <pre className="p-3 bg-[#0d1117] text-[#e6edf3] font-mono text-[10px] rounded-xl overflow-auto max-h-80 leading-relaxed border border-gray-800 select-all shadow-inner">
            {JSON.stringify(activeMessage || {}, null, 2)}
          </pre>
        </div>
      </div>
    </aside>
  );
};
