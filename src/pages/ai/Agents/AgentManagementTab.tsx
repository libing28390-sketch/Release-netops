import React, { useEffect, useState } from 'react';
import { Bot, LoaderCircle, Play, Shield, Wrench } from 'lucide-react';
import {
  getRegisteredAgents,
  getRegisteredTools,
  runAgent,
  type AgentRunResponse,
  type RegisteredAgent,
} from '../../../api/ai';
import { useCoreApp } from '../../../contexts/AppDomainContext';

const statusBadgeTone = (status?: string) => {
  const normalized = String(status || '').toLowerCase();
  if (['finished', 'success', 'ok', 'completed'].includes(normalized)) {
    return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300';
  }
  if (['blocked', 'error', 'failed'].includes(normalized)) {
    return 'bg-rose-100 text-rose-800 dark:bg-rose-950/60 dark:text-rose-300';
  }
  return 'bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300';
};

export const AgentManagementTab: React.FC = () => {
  const { showToast } = useCoreApp();
  const [agents, setAgents] = useState<RegisteredAgent[]>([]);
  const [selectedAgentCode, setSelectedAgentCode] = useState('troubleshooting_agent');
  const [tools, setTools] = useState<any[]>([]);
  const [loadingRegistry, setLoadingRegistry] = useState(true);

  const [question, setQuestion] = useState('为什么测试设备访问核心交换机掉包？');
  const [running, setRunning] = useState(false);
  const [agentRunResult, setAgentRunResult] = useState<AgentRunResponse | null>(null);

  useEffect(() => {
    let active = true;
    void (async () => {
      setLoadingRegistry(true);
      try {
        const [toolList, agentList] = await Promise.all([
          getRegisteredTools(),
          getRegisteredAgents().catch(() => [] as RegisteredAgent[]),
        ]);
        if (!active) return;
        setTools(Array.isArray(toolList) ? toolList : []);
        setAgents(Array.isArray(agentList) ? agentList : []);
        const firstEnabled = agentList.find((a) => a.enabled);
        if (firstEnabled) setSelectedAgentCode(firstEnabled.code);
      } catch (err: any) {
        if (active) showToast(err?.message || '加载 Agent 注册表失败', 'error');
      } finally {
        if (active) setLoadingRegistry(false);
      }
    })();
    return () => { active = false; };
  }, [showToast]);

  const handleRunAgent = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim() || running) return;
    setRunning(true);
    setAgentRunResult(null);
    try {
      const res = await runAgent(question.trim(), selectedAgentCode || 'troubleshooting_agent');
      setAgentRunResult(res);
    } catch (err: any) {
      showToast(err?.message || 'Agent 执行异常', 'error');
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="w-full space-y-6 pb-8">
      <section className="relative overflow-hidden rounded-[26px] border border-indigo-100/80 bg-gradient-to-br from-white via-indigo-50/70 to-violet-100/60 p-6 shadow-sm dark:border-indigo-900/60 dark:from-slate-900 dark:via-indigo-950/40 dark:to-slate-900">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-indigo-200/80 bg-white/80 px-3 py-1 text-[11px] font-bold uppercase tracking-[0.16em] text-indigo-600 dark:border-indigo-800 dark:bg-indigo-950/50 dark:text-indigo-300">
              <Bot className="h-3.5 w-3.5" /> Controlled Agent Registry
            </div>
            <h2 className="nx-page-title text-slate-950 dark:text-white">Agent 注册表与 R0 只读工具集</h2>
            <p className="nx-page-description mt-2 max-w-3xl text-slate-600 dark:text-slate-300">
              Agent 运行时严格读取数据库注册配置（最大步数、超时、工具白名单），仅允许调用 R0 只读诊断工具，绝不赋予 AI 直接 SSH 写入权限。
            </p>
          </div>
          <div className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50/90 px-3.5 py-2 text-xs font-semibold text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-300">
            <Shield className="h-4 w-4" /> 已注册 {agents.length} 个 Agent · {tools.length} 个工具
          </div>
        </div>
      </section>

      {agents.length > 0 && (
        <section className="space-y-3">
          <h3 className="flex items-center gap-2 text-sm font-bold text-slate-900 dark:text-white">
            <Bot className="h-4 w-4 text-indigo-500" /> 已注册 Agent 实例
          </h3>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {agents.map((agent) => {
              const selected = agent.code === selectedAgentCode;
              return (
                <button
                  key={agent.id}
                  type="button"
                  onClick={() => setSelectedAgentCode(agent.code)}
                  className={`rounded-2xl border p-4 text-left transition ${
                    selected
                      ? 'border-indigo-400 bg-indigo-50/60 shadow-sm dark:border-indigo-700 dark:bg-indigo-950/30'
                      : 'border-slate-200 bg-white hover:border-indigo-200 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-indigo-800'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-bold text-slate-900 dark:text-white">{agent.name}</span>
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${agent.enabled ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300' : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400'}`}>
                      {agent.enabled ? '已启用' : '已停用'}
                    </span>
                  </div>
                  <p className="mt-1 font-mono text-[11px] text-indigo-600 dark:text-indigo-400">{agent.code}</p>
                  <p className="mt-2 line-clamp-2 text-xs text-slate-500 dark:text-slate-400">{agent.description || '内置受控排障 Agent'}</p>
                  <div className="mt-3 flex flex-wrap gap-2 text-[10px] text-slate-500 dark:text-slate-400">
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono dark:bg-slate-800">max_steps: {agent.max_steps}</span>
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono dark:bg-slate-800">timeout: {agent.timeout}s</span>
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono dark:bg-slate-800">tools: {agent.allowed_tools?.length || 'ALL R0'}</span>
                  </div>
                </button>
              );
            })}
          </div>
        </section>
      )}

      <section className="space-y-3">
        <h3 className="flex items-center gap-2 text-sm font-bold text-slate-900 dark:text-white">
          <Wrench className="h-4 w-4 text-indigo-500" /> Nexora Tool Registry 只读工具目录
        </h3>
        {loadingRegistry ? (
          <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-400 dark:border-slate-800 dark:bg-slate-900">加载中...</div>
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {tools.map((t) => (
              <div key={t.name} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm space-y-2 dark:border-slate-800 dark:bg-slate-900">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-bold text-slate-900 dark:text-white">{t.display_name}</span>
                  <span className="rounded bg-emerald-100 px-2 py-0.5 font-mono text-[11px] font-bold text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300">
                    {t.risk_level}
                  </span>
                </div>
                <p className="font-mono text-xs text-indigo-600 dark:text-indigo-400">{t.name}</p>
                <p className="text-xs leading-relaxed text-slate-500 dark:text-slate-400">{t.description}</p>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="space-y-4 border-t border-slate-200 pt-6 dark:border-slate-800">
        <div>
          <h3 className="flex items-center gap-2 text-base font-bold text-slate-900 dark:text-white">
            <Play className="h-4 w-4 text-indigo-500" />
            受控多步推演与执行轨迹（当前 Agent：<code className="font-mono text-indigo-600 dark:text-indigo-400">{selectedAgentCode}</code>）
          </h3>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            AI 自动规划多步只读工具调用（IP 搜索 → ARP → MAC → 拓扑 → 告警），并持久化全量执行轨迹。
          </p>
        </div>

        <form onSubmit={handleRunAgent} className="flex flex-col gap-3 sm:flex-row">
          <input
            type="text"
            placeholder="输入故障排障需求..."
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            className="flex-1 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-900 outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-500/15 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
          />
          <button
            type="submit"
            disabled={running || !question.trim()}
            className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {running ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {running ? 'Agent 推演中...' : '运行排障 Agent'}
          </button>
        </form>

        {agentRunResult && (
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm space-y-6 dark:border-slate-800 dark:bg-slate-900">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 pb-3 dark:border-slate-800">
              <div>
                <span className="font-mono text-xs text-indigo-500">Run ID: {agentRunResult.run_id}</span>
                <h4 className="mt-0.5 text-base font-bold text-slate-900 dark:text-white">{agentRunResult.question}</h4>
              </div>
              <span className={`rounded-full px-3 py-1 text-xs font-bold ${statusBadgeTone(agentRunResult.status)}`}>
                {String(agentRunResult.status || 'UNKNOWN').toUpperCase()}
              </span>
            </div>

            <div className="space-y-3">
              <h5 className="text-xs font-bold uppercase tracking-wider text-slate-500">执行步骤轨迹 (Step Trajectory)</h5>
              <div className="space-y-2">
                {agentRunResult.steps.map((s, idx) => (
                  <div key={idx} className="flex items-start gap-3 rounded-xl border border-slate-200/70 bg-slate-50 p-3.5 text-xs dark:border-slate-800 dark:bg-slate-950/50">
                    <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-indigo-100 font-bold text-indigo-600 dark:bg-indigo-950 dark:text-indigo-300">
                      {s.step_no}
                    </div>
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="flex items-center justify-between gap-2 font-mono">
                        <span className="font-bold text-slate-900 dark:text-white">
                          {s.step_type === 'final_answer' ? '最终排障结论' : `Tool Call: ${s.tool_name}`}
                        </span>
                        <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${statusBadgeTone(s.status || 'ok')}`}>
                          {s.status || 'OK'}
                        </span>
                      </div>
                      {s.tool_input && (
                        <p className="font-mono text-[11px] text-slate-500 dark:text-slate-400">Input: {JSON.stringify(s.tool_input)}</p>
                      )}
                      {s.tool_output && (
                        <pre className="mt-1 max-h-32 overflow-auto rounded-lg bg-white p-2 font-mono text-[10px] text-slate-600 ring-1 ring-slate-200 dark:bg-slate-900 dark:text-slate-300 dark:ring-slate-800">
                          {typeof s.tool_output === 'string' ? s.tool_output : JSON.stringify(s.tool_output, null, 2)}
                        </pre>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-xl border border-indigo-100 bg-indigo-50/60 p-4 space-y-2 dark:border-indigo-900/50 dark:bg-indigo-950/30">
              <h5 className="text-xs font-bold text-indigo-900 dark:text-indigo-300">Agent 最终故障根因诊断</h5>
              <p className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-slate-800 dark:text-slate-200">{agentRunResult.final_result || '暂无结论输出'}</p>
            </div>
          </div>
        )}
      </section>
    </div>
  );
};
