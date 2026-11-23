import React, { useEffect, useState } from 'react';
import { Bot, Play, RefreshCw, Wrench } from 'lucide-react';
import {
  getRegisteredAgents,
  getRegisteredTools,
  runAgent,
  type AgentRunResponse,
  type RegisteredAgent,
} from '../../../api/ai';
import { useCoreApp } from '../../../contexts/AppDomainContext';
import { ActionButton } from '../../../components/ui/ActionIconButton';
import { PageHeader } from '../../../components/ui/PageHeader';
import { Panel, PanelHeader } from '../../../components/ui/Panel';
import { StatusBadge, type StatusTone } from '../../../components/ui/StatusBadge';
import { SummaryBar } from '../../../components/ui/SummaryBar';
import { EmptyState } from '../../../components/ui/EmptyState';
import { cn } from '../../../lib/cn';

const statusTone = (status?: string): StatusTone => {
  const normalized = String(status || '').toLowerCase();
  if (['finished', 'success', 'ok', 'completed'].includes(normalized)) return 'success';
  if (['blocked', 'error', 'failed'].includes(normalized)) return 'danger';
  return 'warning';
};

const riskTone = (risk?: string): StatusTone => {
  const level = String(risk || '').toUpperCase();
  if (level === 'R0') return 'success';
  if (level === 'R1') return 'accent';
  if (level === 'R2') return 'warning';
  return level ? 'danger' : 'neutral';
};

const fieldInputClass = 'h-9 min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 text-sm text-fg outline-none transition-colors placeholder:text-fg-subtle focus:border-accent focus:ring-2 focus:ring-accent/20';

export const AgentManagementTab: React.FC = () => {
  const { showToast } = useCoreApp();
  const [agents, setAgents] = useState<RegisteredAgent[]>([]);
  const [selectedAgentCode, setSelectedAgentCode] = useState('troubleshooting_agent');
  const [tools, setTools] = useState<any[]>([]);
  const [loadingRegistry, setLoadingRegistry] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);

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
        const firstEnabled = (Array.isArray(agentList) ? agentList : []).find((a) => a.enabled);
        if (firstEnabled) setSelectedAgentCode(firstEnabled.code);
      } catch (err: any) {
        if (active) showToast(err?.message || '加载 Agent 注册表失败', 'error');
      } finally {
        if (active) setLoadingRegistry(false);
      }
    })();
    return () => { active = false; };
  }, [showToast, reloadKey]);

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

  const enabledAgents = agents.filter((agent) => agent.enabled).length;
  const readOnlyTools = tools.filter((tool) => String(tool?.risk_level || '').toUpperCase() === 'R0').length;

  return (
    <div className="w-full space-y-4 pb-8">
      <PageHeader
        title="Agent 注册表"
        description="受控 Agent 只能调用 R0 只读诊断工具，按注册配置限制步数、超时和工具白名单。"
        infoLabel="Agent 运行约束说明"
        info="Agent 运行时严格读取数据库注册配置（最大步数、超时、工具白名单），仅允许调用 R0 只读诊断工具，不会获得设备 SSH 写入权限。"
        actions={(
          <ActionButton
            type="button"
            icon={RefreshCw}
            iconClassName={loadingRegistry ? 'animate-spin motion-reduce:animate-none' : undefined}
            size="md"
            disabled={loadingRegistry}
            onClick={() => setReloadKey((value) => value + 1)}
          >
            刷新
          </ActionButton>
        )}
      />

      <SummaryBar
        label="Agent 注册表概况"
        items={[
          { key: 'agents', value: agents.length, label: '个 Agent' },
          { key: 'enabled', value: enabledAgents, label: '已启用', tone: 'accent' },
          { key: 'tools', value: tools.length, label: '个工具' },
          { key: 'readonly', value: readOnlyTools, label: 'R0 只读', tone: 'success' },
        ]}
      />

      <Panel aria-label="已注册 Agent">
        <PanelHeader title="已注册 Agent" description="点击选择用于下方推演的 Agent。" />
        {loadingRegistry ? (
          <div role="status" className="px-4 py-8 text-center text-sm text-fg-muted">加载中...</div>
        ) : agents.length === 0 ? (
          <EmptyState
            icon={Bot}
            title="暂无已注册 Agent"
            description="将使用内置的 troubleshooting_agent 运行推演。"
            className="m-4"
          />
        ) : (
          <div className="grid grid-cols-1 gap-3 p-4 md:grid-cols-2 xl:grid-cols-3">
            {agents.map((agent) => {
              const selected = agent.code === selectedAgentCode;
              return (
                <button
                  key={agent.id}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => setSelectedAgentCode(agent.code)}
                  className={cn(
                    'rounded-lg border p-3.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
                    selected ? 'border-accent bg-accent-subtle' : 'border-line bg-surface hover:bg-surface-muted',
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-semibold text-fg" title={agent.name}>{agent.name}</span>
                    <StatusBadge tone={agent.enabled ? 'success' : 'neutral'} dot>
                      {agent.enabled ? '已启用' : '已停用'}
                    </StatusBadge>
                  </div>
                  <p className="mt-1 truncate font-mono text-xs text-fg-muted">{agent.code}</p>
                  <p className="mt-2 line-clamp-2 text-xs leading-5 text-fg-muted">{agent.description || '内置受控排障 Agent'}</p>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    <StatusBadge mono>max_steps: {agent.max_steps}</StatusBadge>
                    <StatusBadge mono>timeout: {agent.timeout}s</StatusBadge>
                    <StatusBadge mono>tools: {agent.allowed_tools?.length || 'ALL R0'}</StatusBadge>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </Panel>

      <Panel aria-label="只读工具目录" className="overflow-hidden">
        <PanelHeader title="只读工具目录" description="Nexora Tool Registry 中 Agent 可调用的工具。" />
        {loadingRegistry ? (
          <div role="status" className="px-4 py-8 text-center text-sm text-fg-muted">加载中...</div>
        ) : tools.length === 0 ? (
          <EmptyState icon={Wrench} title="暂无已注册工具" description="工具注册表为空，Agent 无法调用任何诊断工具。" className="m-4" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th scope="col">工具</th>
                  <th scope="col">标识</th>
                  <th scope="col">说明</th>
                  <th scope="col">风险等级</th>
                </tr>
              </thead>
              <tbody>
                {tools.map((t) => (
                  <tr key={t.name}>
                    <td className="whitespace-nowrap font-semibold text-fg">{t.display_name}</td>
                    <td className="whitespace-nowrap font-mono text-xs text-fg-muted">{t.name}</td>
                    <td className="max-w-[480px] truncate text-fg-muted" title={t.description || undefined}>{t.description}</td>
                    <td><StatusBadge tone={riskTone(t.risk_level)} mono>{t.risk_level}</StatusBadge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel aria-label="受控多步推演">
        <PanelHeader
          title={<>受控多步推演与执行轨迹（当前 Agent：<code className="font-mono text-accent">{selectedAgentCode}</code>）</>}
          description="AI 自动规划多步只读工具调用（IP 搜索 → ARP → MAC → 拓扑 → 告警），并持久化全量执行轨迹。"
        />
        <div className="space-y-4 p-4">
          <form onSubmit={handleRunAgent} className="flex flex-col gap-2 sm:flex-row">
            <input
              type="text"
              placeholder="输入故障排障需求..."
              aria-label="排障需求"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              className={fieldInputClass}
            />
            <ActionButton
              type="submit"
              variant="primary"
              size="md"
              icon={running ? RefreshCw : Play}
              iconClassName={running ? 'animate-spin motion-reduce:animate-none' : undefined}
              disabled={running || !question.trim()}
            >
              {running ? 'Agent 推演中...' : '运行排障 Agent'}
            </ActionButton>
          </form>

          {agentRunResult && (
            <div className="space-y-4 rounded-lg border border-line p-4">
              <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line pb-3">
                <div className="min-w-0">
                  <span className="font-mono text-xs text-fg-muted">Run ID: {agentRunResult.run_id}</span>
                  <h4 className="mt-0.5 text-base font-semibold text-fg">{agentRunResult.question}</h4>
                </div>
                <StatusBadge tone={statusTone(agentRunResult.status)} dot>
                  {String(agentRunResult.status || 'UNKNOWN').toUpperCase()}
                </StatusBadge>
              </div>

              <div className="space-y-2">
                <h5 className="text-xs font-medium text-fg-muted">执行步骤轨迹 (Step Trajectory)</h5>
                {agentRunResult.steps.length === 0 ? (
                  <p className="text-sm text-fg-muted">本次运行没有记录步骤。</p>
                ) : (
                  <ol className="space-y-2">
                    {agentRunResult.steps.map((s, idx) => (
                      <li key={idx} className="flex items-start gap-3 rounded-lg border border-line bg-surface-muted p-3 text-xs">
                        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent-subtle font-semibold tabular-nums text-accent">
                          {s.step_no}
                        </span>
                        <div className="min-w-0 flex-1 space-y-1">
                          <div className="flex items-center justify-between gap-2 font-mono">
                            <span className="truncate font-semibold text-fg">
                              {s.step_type === 'final_answer' ? '最终排障结论' : `Tool Call: ${s.tool_name}`}
                            </span>
                            <StatusBadge tone={statusTone(s.status || 'ok')}>{s.status || 'OK'}</StatusBadge>
                          </div>
                          {s.tool_input && (
                            <p className="break-all font-mono text-[11px] text-fg-muted">Input: {JSON.stringify(s.tool_input)}</p>
                          )}
                          {s.tool_output && (
                            <pre className="mt-1 max-h-32 overflow-auto rounded-md border border-line bg-surface p-2 font-mono text-[11px] text-fg-muted">
                              {typeof s.tool_output === 'string' ? s.tool_output : JSON.stringify(s.tool_output, null, 2)}
                            </pre>
                          )}
                        </div>
                      </li>
                    ))}
                  </ol>
                )}
              </div>

              <div className="space-y-1.5 rounded-lg border border-line bg-accent-subtle p-4">
                <h5 className="text-xs font-semibold text-fg">Agent 最终故障根因诊断</h5>
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-fg">{agentRunResult.final_result || '暂无结论输出'}</p>
              </div>
            </div>
          )}
        </div>
      </Panel>
    </div>
  );
};
