import React, { useEffect, useState } from 'react';
import { Wrench, Play, Shield, CheckCircle2, AlertTriangle, ArrowRight, Layers } from 'lucide-react';
import { getRegisteredTools, runAgent, getAgentRunTrace, AgentRunResponse } from '../../../api/ai';

export const AgentManagementTab: React.FC = () => {
  const [tools, setTools] = useState<any[]>([]);
  const [loadingTools, setLoadingTools] = useState(true);

  // Agent Run
  const [question, setQuestion] = useState('为什么 192.168.10.20 访问核心交换机掉包？');
  const [running, setRunning] = useState(false);
  const [agentRunResult, setAgentRunResult] = useState<AgentRunResponse | null>(null);

  const fetchTools = async () => {
    setLoadingTools(true);
    try {
      const data = await getRegisteredTools();
      setTools(data);
    } catch (err: any) {
      console.error(err);
    } finally {
      setLoadingTools(false);
    }
  };

  useEffect(() => {
    fetchTools();
  }, []);

  const handleRunAgent = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim() || running) return;
    setRunning(true);
    setAgentRunResult(null);
    try {
      const res = await runAgent(question.trim(), 'troubleshooting_agent');
      setAgentRunResult(res);
    } catch (err: any) {
      alert(err.message || 'Agent 执行异常');
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-8">
      {/* Registered Tools Section */}
      <div className="space-y-4">
        <div>
          <h2 className="nx-page-title flex items-center gap-2 text-gray-900 dark:text-white">
            <Wrench className="w-6 h-6 text-indigo-500" />
            Nexora Tool Registry 工具注册表与风险等级
          </h2>
          <p className="nx-page-description mt-1 text-gray-500 dark:text-gray-400">
            Agent 仅允许调用经注册的 R0 (READ_ONLY) 与 R1 工具。绝不给 AI 提供直接 SSH 或全特权写权限。
          </p>
        </div>

        {loadingTools ? (
          <div className="p-8 text-center text-gray-400">加载中...</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {tools.map((t) => (
              <div key={t.name} className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 shadow-sm space-y-2">
                <div className="flex items-center justify-between">
                  <span className="font-bold text-gray-900 dark:text-white text-sm">{t.display_name}</span>
                  <span className="px-2 py-0.5 text-xs font-mono font-bold bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300 rounded">
                    {t.risk_level}
                  </span>
                </div>
                <p className="text-xs font-mono text-indigo-600 dark:text-indigo-400">{t.name}</p>
                <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">{t.description}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Autonomous Agent Execution & Step Trace Section */}
      <div className="space-y-4 pt-6 border-t border-gray-200 dark:border-gray-700">
        <div>
          <h3 className="text-lg font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Play className="w-5 h-5 text-indigo-500" />
            网络排障 Agent 受控多步推演与执行轨迹
          </h3>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            AI 自动规划多步只读工具调用 (IP搜索 &rarr; ARP &rarr; MAC &rarr; 拓扑 &rarr; 告警)，并持久化全量执行轨迹。
          </p>
        </div>

        <form onSubmit={handleRunAgent} className="flex gap-3">
          <input
            type="text"
            placeholder="输入故障排障需求..."
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            className="flex-1 px-4 py-2.5 text-sm border border-gray-300 dark:border-gray-600 rounded-xl dark:bg-gray-900 dark:text-white font-medium"
          />
          <button
            type="submit"
            disabled={running || !question.trim()}
            className="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white font-medium text-sm rounded-xl flex items-center gap-1.5 disabled:opacity-50 transition"
          >
            {running ? 'Agent 推演中...' : '运行 Troubleshooting Agent'}
          </button>
        </form>

        {agentRunResult && (
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-6 shadow-sm space-y-6">
            <div className="flex items-center justify-between border-b border-gray-200 dark:border-gray-700 pb-3">
              <div>
                <span className="text-xs font-mono text-indigo-500">Run ID: {agentRunResult.run_id}</span>
                <h4 className="font-bold text-gray-900 dark:text-white text-base mt-0.5">{agentRunResult.question}</h4>
              </div>
              <span className="px-3 py-1 text-xs font-bold bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300 rounded-full">
                {agentRunResult.status.toUpperCase()}
              </span>
            </div>

            {/* Steps Trajectory Visualizer */}
            <div className="space-y-3">
              <h5 className="text-xs font-bold text-gray-500 uppercase tracking-wider">执行步骤轨迹 (Step Trajectory)</h5>
              <div className="space-y-2">
                {agentRunResult.steps.map((s, idx) => (
                  <div key={idx} className="bg-gray-50 dark:bg-gray-900/60 p-3.5 rounded-xl border border-gray-200/60 dark:border-gray-700/60 flex items-start gap-3 text-xs">
                    <div className="w-6 h-6 rounded-full bg-indigo-100 dark:bg-indigo-950 text-indigo-600 font-bold flex items-center justify-center flex-shrink-0 mt-0.5">
                      {s.step_no}
                    </div>
                    <div className="flex-1 space-y-1">
                      <div className="flex items-center justify-between font-mono">
                        <span className="font-bold text-gray-900 dark:text-white">
                          {s.step_type === 'final_answer' ? '🏁 最终排障结论' : `🛠️ Tool Call: ${s.tool_name}`}
                        </span>
                        <span className="text-emerald-500 font-semibold">{s.status || 'OK'}</span>
                      </div>
                      {s.tool_input && (
                        <p className="font-mono text-gray-500 text-[11px]">Input: {JSON.stringify(s.tool_input)}</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Final Answer */}
            <div className="bg-indigo-50/60 dark:bg-indigo-950/40 p-4 rounded-xl border border-indigo-100 dark:border-indigo-900/40 space-y-2">
              <h5 className="text-xs font-bold text-indigo-900 dark:text-indigo-300">Agent 最终故障根因诊断</h5>
              <p className="text-sm text-gray-800 dark:text-gray-200 leading-relaxed font-sans">{agentRunResult.final_result}</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
