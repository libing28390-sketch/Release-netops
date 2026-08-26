import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  CloudOff,
  Database,
  EyeOff,
  Fingerprint,
  FlaskConical,
  LockKeyhole,
  RefreshCw,
  Save,
  Search,
  ShieldCheck,
  Skull,
  Workflow,
  XCircle,
} from 'lucide-react';
import {
  AISecurityDryRunResult,
  AISecurityPolicy,
  AISecurityIncident,
  getAISecurityPolicy,
  getAISecurityEventsPage,
  getAISecurityIncidentsPage,
  resolveAISecurityIncident,
  exportAISecurityEvents,
  setAIKillSwitch,
  setAIDevPassthrough,
  setAITenantKillSwitch,
  testAISecurityPayload,
  updateAISecurityPolicy,
} from '../../../api/ai';
import Pagination from '../../../components/Pagination';

const DEFAULT_POLICY: AISecurityPolicy = {
  external_ai_enabled: false,
  kill_switch: false,
  max_payload_bytes: 256000,
  identifiers_must_be_tokenized: true,
  allow_sensitive_minimization: true,
  allowed_provider_types: ['deepseek', 'openai', 'openai_compatible', 'azure_openai', 'ollama', 'local', 'qwen'],
  allowed_classifications: ['PUBLIC', 'INTERNAL', 'CONFIDENTIAL'],
  allowed_data_regions: ['unknown', 'global', 'cn', 'us', 'eu'],
  tenant_kill_switches: {},
};

const formatBytes = (bytes: number) => {
  if (!Number.isFinite(bytes) || bytes <= 0) return '未设置';
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.round(bytes / 1024)} KB`;
};

const decisionClass = (decision: string) => {
  if (decision === 'BLOCK') return 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/70 dark:bg-rose-950/30 dark:text-rose-300';
  if (decision === 'MINIMIZE') return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/70 dark:bg-amber-950/30 dark:text-amber-300';
  return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/70 dark:bg-emerald-950/30 dark:text-emerald-300';
};

interface SwitchButtonProps {
  checked: boolean;
  disabled?: boolean;
  danger?: boolean;
  onClick: () => void;
  label: string;
}

const SwitchButton: React.FC<SwitchButtonProps> = ({ checked, disabled, danger, onClick, label }) => (
  <button
    type="button"
    role="switch"
    aria-checked={checked}
    aria-label={label}
    disabled={disabled}
    onClick={onClick}
    className={`relative inline-flex h-7 w-[52px] shrink-0 items-center rounded-full p-1 transition-colors focus:outline-none focus:ring-2 focus:ring-cyan-500/40 disabled:cursor-not-allowed disabled:opacity-50 ${
      checked ? (danger ? 'bg-rose-500' : 'bg-cyan-600') : 'bg-slate-200 dark:bg-slate-700'
    }`}
  >
    <span className={`h-5 w-5 rounded-full bg-white shadow-sm transition-transform ${checked ? 'translate-x-5' : 'translate-x-0'}`} />
  </button>
);

interface GuardrailRowProps {
  icon: React.ReactNode;
  label: string;
  description: string;
  enabled: boolean;
}

const GuardrailRow: React.FC<GuardrailRowProps> = ({ icon, label, description, enabled }) => (
  <div className="flex items-start gap-3 rounded-2xl border border-slate-200/80 bg-slate-50/80 p-3 dark:border-slate-800 dark:bg-slate-900/60">
    <span className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl ${enabled ? 'bg-emerald-100 text-emerald-600 dark:bg-emerald-950/50 dark:text-emerald-300' : 'bg-slate-200 text-slate-500 dark:bg-slate-800 dark:text-slate-400'}`}>
      {icon}
    </span>
    <span className="min-w-0 flex-1">
      <span className="flex items-center gap-2 text-sm font-semibold text-slate-800 dark:text-slate-100">
        {label}
        <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide ${enabled ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300' : 'bg-slate-200 text-slate-500 dark:bg-slate-800 dark:text-slate-400'}`}>
          {enabled ? 'ON' : 'OFF'}
        </span>
      </span>
      <span className="mt-1 block text-xs leading-5 text-slate-500 dark:text-slate-400">{description}</span>
    </span>
  </div>
);

export const SecurityPolicyTab: React.FC = () => {
  const [policy, setPolicy] = useState<AISecurityPolicy>(DEFAULT_POLICY);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [lastSavedAt, setLastSavedAt] = useState<Date | null>(null);
  const [sample, setSample] = useState('show interface 10.0.0.1\nstatus: interface is up');
  const [dryRun, setDryRun] = useState<AISecurityDryRunResult | null>(null);
  const [testing, setTesting] = useState(false);
  const [events, setEvents] = useState<Array<import('../../../api/ai').AISecurityEvent>>([]);
  const [incidents, setIncidents] = useState<AISecurityIncident[]>([]);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [incidentsLoading, setIncidentsLoading] = useState(false);
  const [eventPage, setEventPage] = useState(1);
  const [eventPageSize, setEventPageSize] = useState(20);
  const [eventTotal, setEventTotal] = useState(0);
  const [eventSearch, setEventSearch] = useState('');
  const [eventSearchApplied, setEventSearchApplied] = useState('');
  const [eventDecision, setEventDecision] = useState('');
  const [incidentPage, setIncidentPage] = useState(1);
  const [incidentPageSize, setIncidentPageSize] = useState(20);
  const [incidentTotal, setIncidentTotal] = useState(0);
  const [incidentSearch, setIncidentSearch] = useState('');
  const [incidentSearchApplied, setIncidentSearchApplied] = useState('');
  const [incidentStatus, setIncidentStatus] = useState('');
  const [incidentSeverity, setIncidentSeverity] = useState('');

  const loadPolicy = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setPolicy(await getAISecurityPolicy());
    } catch (err) {
      setError(err instanceof Error ? err.message : '无法读取 AI 安全策略');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadEvents = useCallback(async () => {
    setEventsLoading(true);
    try {
      const result = await getAISecurityEventsPage({ page: eventPage, page_size: eventPageSize, search: eventSearchApplied, decision: eventDecision });
      setEvents(result.items);
      setEventTotal(result.total);
      if (result.page !== eventPage) setEventPage(result.page);
    } catch (err) {
      setError(err instanceof Error ? err.message : '无法读取安全审计事件');
    } finally {
      setEventsLoading(false);
    }
  }, [eventDecision, eventPage, eventPageSize, eventSearchApplied]);

  const loadIncidents = useCallback(async () => {
    setIncidentsLoading(true);
    try {
      const result = await getAISecurityIncidentsPage({ page: incidentPage, page_size: incidentPageSize, search: incidentSearchApplied, status: incidentStatus, severity: incidentSeverity });
      setIncidents(result.items);
      setIncidentTotal(result.total);
      if (result.page !== incidentPage) setIncidentPage(result.page);
    } catch (err) {
      setError(err instanceof Error ? err.message : '无法读取安全事件响应记录');
    } finally {
      setIncidentsLoading(false);
    }
  }, [incidentPage, incidentPageSize, incidentSearchApplied, incidentSeverity, incidentStatus]);

  const load = useCallback(async () => {
    await Promise.all([loadPolicy(), loadEvents(), loadIncidents()]);
  }, [loadEvents, loadIncidents, loadPolicy]);

  useEffect(() => { void loadPolicy(); }, [loadPolicy]);
  useEffect(() => { void loadEvents(); }, [loadEvents]);
  useEffect(() => { void loadIncidents(); }, [loadIncidents]);

  const save = async (patch: Partial<AISecurityPolicy>) => {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      // `dev_passthrough` is runtime status returned by the read endpoint,
      // not part of the persisted policy update contract.
      const { dev_passthrough: _devPassthrough, ...policyPayload } = { ...policy, ...patch };
      const nextPolicy = await updateAISecurityPolicy(policyPayload);
      setPolicy(nextPolicy);
      setLastSavedAt(new Date());
      setNotice('安全策略已保存，新的请求会立即按此策略执行。');
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存 AI 安全策略失败');
    } finally {
      setSaving(false);
    }
  };

  const resolveIncident = async (id: string) => {
    try {
      await resolveAISecurityIncident(id);
      setIncidents((current) => current.map((incident) => incident.id === id ? { ...incident, status: 'resolved', resolved_at: new Date().toISOString() } : incident));
      setNotice('安全事件已标记为已解决。');
    } catch (err) {
      setError(err instanceof Error ? err.message : '安全事件处理失败');
    }
  };

  const toggleExternalAI = () => {
    if (!policy.external_ai_enabled && !window.confirm('开启外部 AI 出口后，符合策略的内容才会发送到已允许的 Provider。确定继续吗？')) return;
    void save({ external_ai_enabled: !policy.external_ai_enabled });
  };

  const toggleKillSwitch = async () => {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const enabled = !policy.kill_switch;
      await setAIKillSwitch(enabled, enabled ? 'AI Security Gateway emergency stop' : 'AI Security Gateway operator resume');
      setPolicy((current) => ({ ...current, kill_switch: enabled }));
      setLastSavedAt(new Date());
      setNotice(enabled ? 'Kill switch 已触发，所有外部 AI 请求都会被阻断。' : 'Kill switch 已解除，请确认外部出口策略仍符合预期。');
    } catch (err) {
      setError(err instanceof Error ? err.message : '切换紧急停止开关失败');
    } finally {
      setSaving(false);
    }
  };

  const toggleTenantKillSwitch = async () => {
    setSaving(true);
    setError(null);
    try {
      const enabled = !Boolean(policy.tenant_kill_switches?.['tenant-default']);
      await setAITenantKillSwitch('tenant-default', enabled, enabled ? 'tenant security emergency stop' : 'tenant security operator resume');
      setPolicy((current) => ({ ...current, tenant_kill_switches: { ...(current.tenant_kill_switches || {}), 'tenant-default': enabled } }));
      setNotice(enabled ? '当前租户外部 AI 已暂停。' : '当前租户外部 AI 已恢复。');
    } catch (err) {
      setError(err instanceof Error ? err.message : '切换租户安全开关失败');
    } finally {
      setSaving(false);
    }
  };

  const toggleTemporaryTestMode = async () => {
    if (!policy.dev_passthrough?.supported) return;
    const enabled = !Boolean(policy.dev_passthrough.enabled);
    if (enabled && !window.confirm(`AI 临时测试模式会在 ${policy.dev_passthrough.max_minutes} 分钟后自动关闭，并跳过分类与 Token 化，但仍保留凭据 DLP、Provider 白名单、区域、大小和工具安全检查。确定开启吗？`)) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const next = await setAIDevPassthrough(enabled, policy.dev_passthrough.max_minutes);
      setPolicy((current) => ({ ...current, dev_passthrough: next }));
      setLastSavedAt(new Date());
      setNotice(enabled ? `AI 临时测试模式已开启，将在 ${next.max_minutes} 分钟内自动关闭。` : 'AI 临时测试模式已关闭。');
    } catch (err) {
      setError(err instanceof Error ? err.message : '切换 AI 临时测试模式失败');
    } finally {
      setSaving(false);
    }
  };

  const runDryRun = async () => {
    if (!sample.trim()) {
      setError('请先输入一段待检查的文本。');
      return;
    }
    setTesting(true);
    setError(null);
    setDryRun(null);
    try {
      setDryRun(await testAISecurityPayload([{ role: 'user', content: sample }]));
    } catch (err) {
      setError(err instanceof Error ? err.message : '安全策略演练失败');
    } finally {
      setTesting(false);
    }
  };

  const exportEvents = async () => {
    try {
      const csv = await exportAISecurityEvents();
      const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = `nexora-ai-security-events-${new Date().toISOString().slice(0, 10)}.csv`;
      link.click();
      URL.revokeObjectURL(url);
      setNotice('安全事件审计已导出（仅元数据）。');
    } catch (err) {
      setError(err instanceof Error ? err.message : '安全事件导出失败');
    }
  };

  const gatewayReady = policy.external_ai_enabled && !policy.kill_switch;
  const devPassthroughActive = Boolean(policy.dev_passthrough?.enabled);
  const status = useMemo(() => {
    if (policy.kill_switch) {
      return {
        label: '紧急停止已触发',
        detail: '所有外部 AI 请求都会在网关处被阻断。解除前请确认告警和变更原因。',
        icon: Skull,
        tone: 'rose',
      };
    }
    if (!policy.external_ai_enabled) {
      return {
        label: '默认拒绝外部 AI',
        detail: '当前 Provider 连接测试会返回 AI_SECURITY_BLOCKED；先启用外部 AI 出口才能进行真实连通性测试。',
        icon: CloudOff,
        tone: 'amber',
      };
    }
    if (devPassthroughActive) {
      return {
        label: 'AI 临时测试模式已开启',
        detail: '当前请求会跳过分类与 Token 化；凭据 DLP、Provider/区域、大小和工具安全检查仍然保留。',
        icon: AlertTriangle,
        tone: 'amber',
      };
    }
    return {
      label: '安全网关已就绪',
      detail: '请求会先经过数据分级、脱敏/最小化、Token 化和 DLP 检查，再转发到允许的 Provider。',
      icon: ShieldCheck,
      tone: 'emerald',
    };
  }, [devPassthroughActive, policy.external_ai_enabled, policy.kill_switch]);

  const StatusIcon = status.icon;
  const statusTone = status.tone === 'rose'
    ? 'border-rose-200 bg-rose-50/80 text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/20 dark:text-rose-300'
    : status.tone === 'amber'
      ? 'border-amber-200 bg-amber-50/80 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-300'
      : 'border-emerald-200 bg-emerald-50/80 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/20 dark:text-emerald-300';

  if (loading) {
    return (
      <div className="flex min-h-[420px] items-center justify-center rounded-3xl border border-slate-200 bg-white text-sm text-slate-500 shadow-sm dark:border-slate-800 dark:bg-slate-950 dark:text-slate-400">
        <div className="flex items-center gap-3"><RefreshCw className="h-4 w-4 animate-spin text-cyan-600" />正在读取安全网关策略…</div>
      </div>
    );
  }

  return (
    <div className="min-h-full bg-gradient-to-br from-slate-50 via-white to-cyan-50/40 px-4 py-5 dark:from-slate-950 dark:via-slate-950 dark:to-cyan-950/20 sm:px-6 lg:px-8">
      <div className="mx-auto w-full max-w-[1500px] space-y-6">
        <header className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
          <div>
            <div className="mb-2 flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.2em] text-cyan-700 dark:text-cyan-300">
              <ShieldCheck className="h-4 w-4" /> AI governance / security gateway
            </div>
            <h1 className="nx-page-title text-slate-950 dark:text-white">AI 安全网关</h1>
            <p className="nx-page-description mt-2 max-w-3xl text-slate-500 dark:text-slate-400">统一控制外部 AI 出口。默认拒绝、可审计、可演练；Provider 连接测试和所有 AI 调用都必须经过这里。</p>
          </div>
          <button
            type="button"
            onClick={() => void load()}
            className="inline-flex items-center justify-center gap-2 self-start rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm font-semibold text-slate-700 shadow-sm transition hover:border-cyan-300 hover:text-cyan-700 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:border-cyan-700 dark:hover:text-cyan-300 lg:self-auto"
            disabled={saving || testing}
          >
            <RefreshCw className={`h-4 w-4 ${saving ? 'animate-spin' : ''}`} /> 刷新状态
          </button>
        </header>

        {error && (
          <div role="alert" className="flex items-start gap-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/70 dark:bg-rose-950/30 dark:text-rose-300">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span className="flex-1">{error}</span>
            <button type="button" onClick={() => setError(null)} aria-label="关闭错误提示"><XCircle className="h-4 w-4" /></button>
          </div>
        )}
        {notice && (
          <div role="status" className="flex items-center gap-3 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-900/70 dark:bg-emerald-950/30 dark:text-emerald-300">
            <CheckCircle2 className="h-4 w-4 shrink-0" />
            <span className="flex-1">{notice}</span>
            <span className="text-xs opacity-75">{lastSavedAt ? `刚刚 ${lastSavedAt.toLocaleTimeString()}` : ''}</span>
          </div>
        )}

        <section className={`relative overflow-hidden rounded-3xl border p-5 shadow-sm sm:p-6 ${statusTone}`}>
          <div className="pointer-events-none absolute -right-10 -top-16 h-48 w-48 rounded-full border-[24px] border-current opacity-10" />
          <div className="relative flex flex-col justify-between gap-5 lg:flex-row lg:items-center">
            <div className="flex items-start gap-4">
              <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-white/80 shadow-sm dark:bg-slate-950/50"><StatusIcon className="h-6 w-6" /></span>
              <div>
                <div className="text-[11px] font-bold uppercase tracking-[0.18em] opacity-70">Current gateway posture</div>
                <h2 className="mt-1 text-xl font-bold">{status.label}</h2>
                <p className="mt-1 max-w-3xl text-sm leading-6 opacity-80">{status.detail}</p>
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2 rounded-full bg-white/70 px-3 py-2 text-xs font-bold uppercase tracking-wider shadow-sm dark:bg-slate-950/40">
              <span className={`h-2 w-2 rounded-full ${gatewayReady ? 'bg-emerald-500' : 'bg-rose-500'}`} />
              {devPassthroughActive ? 'AI test mode / timed' : gatewayReady ? 'Protected / ready' : 'Blocked by policy'}
            </div>
          </div>
        </section>

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(360px,0.85fr)]">
          <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900 sm:p-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2 text-sm font-bold text-slate-900 dark:text-white"><LockKeyhole className="h-4 w-4 text-cyan-600" />出口控制</div>
                <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">只在明确需要时开启外部 AI；紧急停止可以随时切断出口。</p>
              </div>
              <span className="rounded-full bg-cyan-50 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-cyan-700 dark:bg-cyan-950/50 dark:text-cyan-300">Administrator</span>
            </div>

            <div className="mt-5 grid gap-4 md:grid-cols-2">
              <div className={`rounded-2xl border p-4 transition ${policy.external_ai_enabled ? 'border-cyan-200 bg-cyan-50/60 dark:border-cyan-900/60 dark:bg-cyan-950/20' : 'border-slate-200 bg-slate-50/70 dark:border-slate-800 dark:bg-slate-950/50'}`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-2"><CloudOff className={`h-4 w-4 ${policy.external_ai_enabled ? 'text-cyan-600' : 'text-slate-500'}`} /><span className="text-sm font-semibold text-slate-800 dark:text-slate-100">外部 AI 出口</span></div>
                  <SwitchButton checked={policy.external_ai_enabled} disabled={saving} onClick={toggleExternalAI} label="切换外部 AI 出口" />
                </div>
                <div className="mt-4 flex items-center gap-2 text-sm font-bold text-slate-900 dark:text-white">{policy.external_ai_enabled ? '已启用' : '默认拒绝'}<span className="text-xs font-normal text-slate-500">{policy.external_ai_enabled ? ' / policy checked' : ' / fail closed'}</span></div>
                <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">开启后，只有通过本网关检查并命中允许 Provider 类型的请求才会出站。</p>
                <div className="mt-4 flex items-center justify-between border-t border-slate-200/70 pt-3 text-xs dark:border-slate-800"><span className="text-slate-500">允许 Provider</span><code className="rounded-md bg-white px-2 py-1 font-mono font-semibold text-cyan-700 shadow-sm dark:bg-slate-900 dark:text-cyan-300">{policy.allowed_provider_types.join(', ') || 'none'}</code></div>
              </div>

              <div className={`rounded-2xl border p-4 transition ${policy.kill_switch ? 'border-rose-200 bg-rose-50/60 dark:border-rose-900/60 dark:bg-rose-950/20' : 'border-slate-200 bg-slate-50/70 dark:border-slate-800 dark:bg-slate-950/50'}`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-2"><Skull className={`h-4 w-4 ${policy.kill_switch ? 'text-rose-600' : 'text-slate-500'}`} /><span className="text-sm font-semibold text-slate-800 dark:text-slate-100">紧急停止</span></div>
                  <SwitchButton checked={policy.kill_switch} danger disabled={saving} onClick={() => void toggleKillSwitch()} label="切换 AI 紧急停止" />
                </div>
                <div className="mt-4 flex items-center gap-2 text-sm font-bold text-slate-900 dark:text-white">{policy.kill_switch ? '已触发' : '未触发'}<span className="text-xs font-normal text-slate-500">{policy.kill_switch ? ' / all egress blocked' : ' / normal operation'}</span></div>
                <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">故障、泄露或策略异常时立即阻断所有外部调用，不会自动降级到未受控的 Provider。</p>
                <div className="mt-4 flex items-center gap-2 border-t border-slate-200/70 pt-3 text-xs text-slate-500 dark:border-slate-800"><CircleHelp className="h-3.5 w-3.5" />适合应急处置，解除后请重新运行策略演练。</div>
              </div>

              <div className={`rounded-2xl border p-4 transition ${policy.tenant_kill_switches?.['tenant-default'] ? 'border-rose-200 bg-rose-50/60 dark:border-rose-900/60 dark:bg-rose-950/20' : 'border-slate-200 bg-slate-50/70 dark:border-slate-800 dark:bg-slate-950/50'}`}>
                <div className="flex items-start justify-between gap-3"><div className="flex items-center gap-2"><Skull className="h-4 w-4 text-rose-500" /><span className="text-sm font-semibold text-slate-800 dark:text-slate-100">当前租户开关</span></div><SwitchButton checked={Boolean(policy.tenant_kill_switches?.['tenant-default'])} danger disabled={saving} onClick={() => void toggleTenantKillSwitch()} label="切换当前租户 AI 开关" /></div>
                <div className="mt-4 text-sm font-bold text-slate-900 dark:text-white">{policy.tenant_kill_switches?.['tenant-default'] ? '已暂停' : '未暂停'}</div>
                <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">租户开关优先于 Provider 配置，只影响当前认证租户。</p>
              </div>

              {policy.dev_passthrough?.supported && (
                <div className={`rounded-2xl border p-4 transition ${policy.dev_passthrough.enabled ? 'border-amber-200 bg-amber-50/70 dark:border-amber-900/60 dark:bg-amber-950/20' : 'border-slate-200 bg-slate-50/70 dark:border-slate-800 dark:bg-slate-950/50'}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-2"><AlertTriangle className={`h-4 w-4 ${policy.dev_passthrough.enabled ? 'text-amber-600' : 'text-slate-500'}`} /><span className="text-sm font-semibold text-slate-800 dark:text-slate-100">AI 临时测试模式</span></div>
                    <SwitchButton checked={Boolean(policy.dev_passthrough.enabled)} danger disabled={saving} onClick={() => void toggleTemporaryTestMode()} label="切换 AI 临时测试模式" />
                  </div>
                  <div className="mt-4 text-sm font-bold text-slate-900 dark:text-white">{policy.dev_passthrough.enabled ? `已开启 · 剩余 ${Math.ceil(policy.dev_passthrough.remaining_seconds / 60)} 分钟` : '未开启'}</div>
                  <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">管理员临时测试使用，最多 15 分钟，重启自动关闭。跳过分类与 Token 化，但仍保留凭据 DLP、Provider/区域、大小和工具安全检查。</p>
                </div>
              )}
            </div>
          </section>

          <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900 sm:p-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2 text-sm font-bold text-slate-900 dark:text-white"><ShieldCheck className="h-4 w-4 text-emerald-600" />数据保护基线</div>
                <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">这些约束在网关层执行，Provider 无法绕过。</p>
              </div>
              <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300">Fail closed</span>
            </div>
            <div className="mt-5 space-y-3">
              <GuardrailRow icon={<Fingerprint className="h-4 w-4" />} label="敏感标识符 Token 化" description="设备 IP、用户名、密钥等标识在出站前替换为稳定 Token。" enabled={policy.identifiers_must_be_tokenized} />
              <GuardrailRow icon={<EyeOff className="h-4 w-4" />} label="敏感内容最小化" description="只保留当前分析所需内容，减少原始配置和凭据暴露。" enabled={policy.allow_sensitive_minimization} />
              <GuardrailRow icon={<Database className="h-4 w-4" />} label="请求体大小限制" description={`单次 payload 上限 ${formatBytes(policy.max_payload_bytes)}，超过即拒绝。`} enabled={policy.max_payload_bytes > 0} />
              <GuardrailRow icon={<LockKeyhole className="h-4 w-4" />} label="分类与驻留边界" description={`允许分类 ${policy.allowed_classifications?.join('、') || 'PUBLIC/INTERNAL/CONFIDENTIAL'}；区域 ${policy.allowed_data_regions?.join('、') || 'unknown'}`} enabled={(policy.allowed_classifications || []).length > 0} />
            </div>
          </section>
        </div>

        <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900 sm:p-6">
          <div className="flex items-center gap-2 text-sm font-bold text-slate-900 dark:text-white"><Workflow className="h-4 w-4 text-indigo-600" />一条请求如何通过网关</div>
          <div className="mt-5 flex flex-col gap-3 md:flex-row md:items-stretch md:gap-0">
            {[
              ['01', '数据分级', '识别敏感等级'],
              ['02', '最小化', '压缩必要上下文'],
              ['03', 'Token 化', '替换敏感标识'],
              ['04', 'DLP 检查', '发现即阻断'],
              ['05', 'Provider', '按 allowlist 控制 DeepSeek、OpenAI-compatible、Azure、Ollama 等适配器'],
            ].map(([number, title, detail], index, steps) => (
              <React.Fragment key={number}>
                <div className="flex min-w-0 flex-1 items-center gap-3 rounded-2xl border border-slate-200/80 bg-slate-50/70 p-3 dark:border-slate-800 dark:bg-slate-950/50">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-indigo-100 text-xs font-bold text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-300">{number}</span>
                  <span className="min-w-0"><span className="block text-sm font-semibold text-slate-800 dark:text-slate-100">{title}</span><span className="mt-0.5 block truncate text-[11px] text-slate-500 dark:text-slate-400">{detail}</span></span>
                </div>
                {index < steps.length - 1 && <ChevronRight className="mx-auto h-5 w-5 shrink-0 self-center text-slate-300 dark:text-slate-700 md:mx-2" />}
              </React.Fragment>
            ))}
          </div>
        </section>

        <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900 sm:p-6">
          <div className="flex items-center justify-between gap-3"><div><div className="flex items-center gap-2 text-sm font-bold text-slate-900 dark:text-white"><AlertTriangle className="h-4 w-4 text-rose-600" />安全事件响应</div><p className="mt-1 text-xs text-slate-500 dark:text-slate-400">阻断请求只保留元数据证据；处理动作受租户和 Administrator 权限保护。</p></div><span className="rounded-full bg-rose-50 px-2.5 py-1 text-[10px] font-bold text-rose-700 dark:bg-rose-950/40 dark:text-rose-300">{incidentTotal} 条匹配</span></div>
          <form onSubmit={(event) => { event.preventDefault(); setIncidentPage(1); setIncidentSearchApplied(incidentSearch.trim()); }} className="mt-4 flex flex-wrap gap-2">
            <div className="relative min-w-[240px] flex-1"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" /><input value={incidentSearch} onChange={(event) => setIncidentSearch(event.target.value)} placeholder="搜索请求 ID、任务、类型或分类" className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2 pl-9 pr-3 text-xs dark:border-slate-700 dark:bg-slate-950 dark:text-white" /></div>
            <select value={incidentStatus} onChange={(event) => { setIncidentStatus(event.target.value); setIncidentPage(1); }} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-950 dark:text-white"><option value="">全部状态</option><option value="open">待处理</option><option value="investigating">处理中</option><option value="resolved">已解决</option></select>
            <select value={incidentSeverity} onChange={(event) => { setIncidentSeverity(event.target.value); setIncidentPage(1); }} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-950 dark:text-white"><option value="">全部级别</option><option value="critical">Critical</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select>
            <button type="submit" className="rounded-xl bg-rose-600 px-4 py-2 text-xs font-semibold text-white hover:bg-rose-700">搜索</button>
          </form>
          <div className="mt-4 space-y-2">{incidentsLoading ? <div className="py-6 text-center text-xs text-slate-400">正在加载安全事件…</div> : incidents.map((incident) => <div key={incident.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-100 px-3 py-2 text-xs dark:border-slate-800"><span className="font-semibold text-slate-800 dark:text-slate-100">{incident.incident_type}</span><span className="rounded-full bg-rose-50 px-2 py-0.5 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300">{incident.severity}</span><span className="text-slate-500">{incident.created_at}</span><span className="ml-auto text-slate-500">{incident.status}</span>{incident.status !== 'resolved' && <button type="button" onClick={() => void resolveIncident(incident.id)} className="rounded border border-emerald-200 px-2 py-1 font-semibold text-emerald-700 hover:bg-emerald-50 dark:border-emerald-900/60 dark:text-emerald-300">标记已解决</button>}</div>)}{!incidentsLoading && incidents.length === 0 && <div className="py-4 text-center text-xs text-slate-400">当前筛选没有匹配的安全事件</div>}</div>
          <Pagination currentPage={incidentPage} totalItems={incidentTotal} itemsPerPage={incidentPageSize} onPageChange={setIncidentPage} onItemsPerPageChange={(size) => { setIncidentPageSize(size); setIncidentPage(1); }} language="zh" alwaysVisible />
        </section>

        <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900 sm:p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="flex items-center gap-2 text-sm font-bold text-slate-900 dark:text-white"><Database className="h-4 w-4 text-cyan-600" />安全事件审计</div>
              <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">仅展示策略版本、分类、处置、Provider/Model 和请求 ID，不返回原始提示词或秘密。</p>
            </div>
            <div className="flex items-center gap-2"><button type="button" onClick={() => void exportEvents()} className="rounded-xl border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-600 hover:border-cyan-300 dark:border-slate-700 dark:text-slate-300">导出元数据</button><button type="button" onClick={() => void loadEvents()} className="rounded-xl border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-600 hover:border-cyan-300 dark:border-slate-700 dark:text-slate-300">刷新事件</button></div>
          </div>
          <form onSubmit={(event) => { event.preventDefault(); setEventPage(1); setEventSearchApplied(eventSearch.trim()); }} className="mt-4 flex flex-wrap gap-2">
            <div className="relative min-w-[240px] flex-1"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" /><input value={eventSearch} onChange={(event) => setEventSearch(event.target.value)} placeholder="搜索 Request ID、Provider、Model 或错误码" className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2 pl-9 pr-3 text-xs dark:border-slate-700 dark:bg-slate-950 dark:text-white" /></div>
            <select value={eventDecision} onChange={(event) => { setEventDecision(event.target.value); setEventPage(1); }} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-950 dark:text-white"><option value="">全部决定</option><option value="ALLOW">ALLOW</option><option value="MINIMIZE">MINIMIZE</option><option value="BLOCK">BLOCK</option></select>
            <button type="submit" className="rounded-xl bg-cyan-600 px-4 py-2 text-xs font-semibold text-white hover:bg-cyan-700">搜索</button>
          </form>
          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full text-left text-xs"><thead className="text-slate-400"><tr><th className="px-2 py-2">时间</th><th className="px-2 py-2">决定</th><th className="px-2 py-2">分类</th><th className="px-2 py-2">Provider / Model</th><th className="px-2 py-2">发现项</th></tr></thead><tbody>
              {!eventsLoading && events.map((event) => <tr key={event.id} className="border-t border-slate-100 dark:border-slate-800"><td className="px-2 py-2 whitespace-nowrap text-slate-500">{event.created_at}</td><td className="px-2 py-2 font-semibold">{event.decision}</td><td className="px-2 py-2">{event.classification}</td><td className="px-2 py-2">{event.provider_id || '—'} / {event.model_id || '—'}</td><td className="px-2 py-2">{event.finding_categories?.join('、') || '无'}</td></tr>)}
            </tbody></table>
            {eventsLoading ? <div className="py-6 text-center text-xs text-slate-400">正在加载审计事件…</div> : events.length === 0 && <div className="py-6 text-center text-xs text-slate-400">当前筛选没有匹配的审计事件</div>}
          </div>
          <Pagination currentPage={eventPage} totalItems={eventTotal} itemsPerPage={eventPageSize} onPageChange={setEventPage} onItemsPerPageChange={(size) => { setEventPageSize(size); setEventPage(1); }} language="zh" alwaysVisible />
        </section>

        <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900 sm:p-6">
          <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
            <div>
              <div className="flex items-center gap-2 text-sm font-bold text-slate-900 dark:text-white"><FlaskConical className="h-4 w-4 text-violet-600" />策略演练</div>
              <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">只在本地执行安全检查，不会调用外部 Provider。先用它验证为什么某段内容会被允许、最小化或阻断。</p>
            </div>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-violet-50 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-violet-700 dark:bg-violet-950/50 dark:text-violet-300"><Check className="h-3 w-3" />No external call</span>
          </div>
          <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(260px,0.42fr)]">
            <div>
              <label htmlFor="ai-security-dry-run" className="mb-2 block text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">待检查内容</label>
              <textarea
                id="ai-security-dry-run"
                value={sample}
                onChange={(event) => setSample(event.target.value)}
                className="min-h-[170px] w-full resize-y rounded-2xl border border-slate-200 bg-slate-50 p-4 font-mono text-sm leading-6 text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-cyan-400 focus:ring-4 focus:ring-cyan-500/10 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                placeholder="输入命令、配置片段或对话内容…"
              />
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <button type="button" disabled={testing} onClick={() => void runDryRun()} className="inline-flex items-center gap-2 rounded-xl bg-slate-950 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-cyan-600 dark:hover:bg-cyan-500">
                  <FlaskConical className={`h-4 w-4 ${testing ? 'animate-pulse' : ''}`} />{testing ? '检查中…' : '运行策略检查'}
                </button>
                <span className="text-xs text-slate-400">演练结果不会改变当前策略。</span>
              </div>
            </div>
            <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50/70 p-4 dark:border-slate-700 dark:bg-slate-950/60">
              <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400"><AlertTriangle className="h-3.5 w-3.5 text-amber-500" />检查结果</div>
              {dryRun ? (
                <div className="mt-4 space-y-3">
                  <div role="status" aria-label="策略检查结果" className={`rounded-xl border px-3 py-2.5 text-sm font-bold ${decisionClass(dryRun.decision)}`}>
                    {dryRun.decision} <span className="ml-1 text-xs font-normal opacity-80">/ {dryRun.max_data_level}</span>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div className="rounded-xl bg-white p-3 dark:bg-slate-900"><div className="text-slate-400">Payload</div><div className="mt-1 font-mono font-semibold text-slate-700 dark:text-slate-200">{dryRun.payload_bytes?.toLocaleString() || '—'} B</div></div>
                    <div className="rounded-xl bg-white p-3 dark:bg-slate-900"><div className="text-slate-400">Findings</div><div className="mt-1 font-semibold text-slate-700 dark:text-slate-200">{dryRun.finding_categories.join('、') || '无'}</div></div>
                  </div>
                  <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">{dryRun.reason || '策略检查完成，未发现需要额外处理的问题。'}</p>
                </div>
              ) : (
                <div className="mt-8 text-center text-xs leading-5 text-slate-400"><ShieldCheck className="mx-auto mb-2 h-7 w-7 opacity-40" />输入内容后运行一次检查，结果会显示在这里。</div>
              )}
            </div>
          </div>
        </section>

        <div className="flex items-center gap-2 pb-2 text-xs text-slate-400"><Save className="h-3.5 w-3.5" />策略保存后立即对新的 AI 请求生效；已存在的请求不会被重新放行。</div>
      </div>
    </div>
  );
};

export default SecurityPolicyTab;
