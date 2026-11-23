import { DataTable } from '../../../components/DataTable';
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  CloudOff,
  Database,
  EyeOff,
  Fingerprint,
  FlaskConical,
  LockKeyhole,
  RefreshCw,
  Save,
  Search,
  ShieldAlert,
  ShieldCheck,
  Skull,
  XCircle,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import {
  AISecurityDryRunResult,
  AISecurityPolicy,
  AISecurityIncident,
  getAISecurityPolicy,
  getAISecurityEventsPage,
  getAISecurityIncidentsPage,
  resolveAISecurityIncident,
  setAIKillSwitch,
  setAIDevPassthrough,
  setAITenantKillSwitch,
  testAISecurityPayload,
  updateAISecurityPolicy,
} from '../../../api/ai';
import Pagination from '../../../components/Pagination';
import type { TableExportData } from '../../../components/ui/TableExportMenu';
import { ActionButton } from '../../../components/ui/ActionIconButton';
import { PageHeader } from '../../../components/ui/PageHeader';
import { Panel, PanelHeader } from '../../../components/ui/Panel';
import { StatusBadge, type StatusTone } from '../../../components/ui/StatusBadge';
import { SummaryBar } from '../../../components/ui/SummaryBar';
import { EmptyState } from '../../../components/ui/EmptyState';
import { InfoTip } from '../../../components/ui/InfoTip';
import { cn } from '../../../lib/cn';

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

/* Shared control styles — token based, 36px controls, 8px radius (same as the Provider page). */
const filterControlClass = 'h-9 rounded-lg border border-line bg-surface px-3 text-[13px] text-fg outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-accent/20';
const tableHeadClass = 'px-3 py-2 text-xs font-medium text-fg-muted';
const tableCellClass = 'px-3 py-2 text-[13px] text-fg';

const formatBytes = (bytes: number) => {
  if (!Number.isFinite(bytes) || bytes <= 0) return '未设置';
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.round(bytes / 1024)} KB`;
};

const decisionTone = (decision: string): StatusTone => {
  if (decision === 'BLOCK') return 'danger';
  if (decision === 'MINIMIZE' || decision === 'TOKENIZE') return 'warning';
  return 'success';
};

const decisionPanelClass = (decision: string) => {
  const tone = decisionTone(decision);
  if (tone === 'danger') return 'border-l-danger bg-danger-subtle text-danger';
  if (tone === 'warning') return 'border-l-warning bg-warning-subtle text-warning';
  return 'border-l-success bg-success-subtle text-success';
};

const severityTone = (severity?: string): StatusTone => {
  switch (String(severity || '').toLowerCase()) {
    case 'critical':
    case 'high':
      return 'danger';
    case 'medium':
      return 'warning';
    default:
      return 'neutral';
  }
};

const incidentStatusLabel = (status?: string) => {
  switch (String(status || '').toLowerCase()) {
    case 'open': return '待处理';
    case 'investigating': return '处理中';
    case 'resolved': return '已解决';
    default: return status || '—';
  }
};

const incidentStatusTone = (status?: string): StatusTone => {
  switch (String(status || '').toLowerCase()) {
    case 'resolved': return 'success';
    case 'investigating': return 'accent';
    case 'open': return 'warning';
    default: return 'neutral';
  }
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
    className={cn(
      'relative inline-flex h-6 w-11 shrink-0 items-center rounded-full p-0.5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-50',
      checked ? (danger ? 'bg-danger' : 'bg-accent') : 'bg-line-strong',
    )}
  >
    <span className={cn('h-5 w-5 rounded-full bg-surface shadow-sm transition-transform', checked ? 'translate-x-5' : 'translate-x-0')} />
  </button>
);

interface ControlCardProps {
  icon: LucideIcon;
  title: string;
  checked: boolean;
  danger?: boolean;
  disabled?: boolean;
  switchLabel: string;
  onToggle: () => void;
  stateText: React.ReactNode;
  stateTone: StatusTone;
  description: React.ReactNode;
  footer?: React.ReactNode;
}

/** One egress control: title + switch, current state, one-line explanation. */
const ControlCard: React.FC<ControlCardProps> = ({ icon: Icon, title, checked, danger, disabled, switchLabel, onToggle, stateText, stateTone, description, footer }) => (
  <div className={cn('rounded-lg border border-line bg-surface p-4', checked && danger && 'border-l-[3px] border-l-danger', checked && !danger && 'border-l-[3px] border-l-accent')}>
    <div className="flex items-start justify-between gap-3">
      <div className="flex min-w-0 items-center gap-2">
        <Icon size={16} strokeWidth={1.8} aria-hidden="true" className={checked ? (danger ? 'text-danger' : 'text-accent') : 'text-fg-muted'} />
        <span className="truncate text-sm font-semibold text-fg">{title}</span>
      </div>
      <SwitchButton checked={checked} danger={danger} disabled={disabled} onClick={onToggle} label={switchLabel} />
    </div>
    <div className="mt-3"><StatusBadge tone={stateTone} dot>{stateText}</StatusBadge></div>
    <p className="mt-2 text-xs leading-5 text-fg-muted">{description}</p>
    {footer && <div className="mt-3 border-t border-line pt-3 text-xs text-fg-muted">{footer}</div>}
  </div>
);

interface GuardrailRowProps {
  icon: React.ReactNode;
  label: string;
  description: string;
  enabled: boolean;
  state?: 'on' | 'bypass' | 'off';
}

const GuardrailRow: React.FC<GuardrailRowProps> = ({ icon, label, description, enabled, state }) => {
  const effectiveState = state || (enabled ? 'on' : 'off');
  const stateLabel = effectiveState === 'bypass' ? '测试模式放开' : effectiveState === 'on' ? 'ON' : 'OFF';
  const tone: StatusTone = effectiveState === 'bypass' ? 'warning' : effectiveState === 'on' ? 'success' : 'neutral';
  const iconTone = effectiveState === 'bypass'
    ? 'bg-warning-subtle text-warning'
    : effectiveState === 'on'
      ? 'bg-success-subtle text-success'
      : 'bg-surface-muted text-fg-muted';
  return (
    <div className="flex items-start gap-3 px-4 py-3">
      <span className={cn('mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg', iconTone)}>
        {icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-2 text-[13px] font-medium text-fg">
          {label}
          <StatusBadge tone={tone}>{stateLabel}</StatusBadge>
        </span>
        <span className="mt-0.5 block text-xs leading-5 text-fg-muted">{description}</span>
      </span>
    </div>
  );
};

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
  const [eventPageSize, setEventPageSize] = useState(10);
  const [eventTotal, setEventTotal] = useState(0);
  const [eventSearch, setEventSearch] = useState('');
  const [eventSearchApplied, setEventSearchApplied] = useState('');
  const [eventDecision, setEventDecision] = useState('');
  const [incidentPage, setIncidentPage] = useState(1);
  const [incidentPageSize, setIncidentPageSize] = useState(10);
  const [incidentTotal, setIncidentTotal] = useState(0);
  const [incidentSearch, setIncidentSearch] = useState('');
  const [incidentSearchApplied, setIncidentSearchApplied] = useState('');
  const [incidentStatus, setIncidentStatus] = useState('');
  const [incidentSeverity, setIncidentSeverity] = useState('');
  const [maxPayloadKbInput, setMaxPayloadKbInput] = useState('250');

  const loadPolicy = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const loaded = await getAISecurityPolicy();
      setPolicy(loaded);
      setMaxPayloadKbInput(String(Math.max(1, Math.round((loaded.max_payload_bytes || 256000) / 1024))));
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
    if (enabled && !window.confirm(`AI 临时测试模式是限时黑名单放行，会在 ${policy.dev_passthrough.max_minutes} 分钟后自动关闭。普通请求不再因数据分类被拦截，也不做最小化和 Token 化，但仍拦截凭据 DLP、Kill Switch、Provider/区域/租户权限、请求大小、危险工具/写入操作以及跨租户和凭据读取请求。确定开启吗？`)) return;
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

  const exportAllEvents = useCallback(async (): Promise<TableExportData> => {
    const allEvents: Array<import('../../../api/ai').AISecurityEvent> = [];
    let page = 1;
    let total = Number.POSITIVE_INFINITY;
    while (allEvents.length < total) {
      const result = await getAISecurityEventsPage({
        page,
        page_size: 100,
        search: eventSearchApplied,
        decision: eventDecision,
      });
      allEvents.push(...result.items);
      total = result.total;
      if (!result.items.length && allEvents.length < total) {
        throw new Error(`安全事件导出不完整：已读取 ${allEvents.length} / ${total} 条。`);
      }
      page += 1;
    }
    return {
      headers: ['时间', '决定', '分类', 'Provider ID', 'Model ID', '发现项'],
      rows: allEvents.map((event) => [
        event.created_at,
        event.decision,
        event.classification,
        event.provider_id || '',
        event.model_id || '',
        event.finding_categories?.join('、') || '无',
      ]),
    };
  }, [eventDecision, eventSearchApplied]);

  const gatewayReady = policy.external_ai_enabled && !policy.kill_switch;
  const devPassthroughActive = Boolean(policy.dev_passthrough?.enabled);
  const tenantPaused = Boolean(policy.tenant_kill_switches?.['tenant-default']);
  const status = useMemo(() => {
    if (policy.kill_switch) {
      return {
        label: '紧急停止已触发',
        detail: '所有外部 AI 请求都会在网关处被阻断。解除前请确认告警和变更原因。',
        icon: Skull,
        tone: 'danger' as StatusTone,
      };
    }
    if (!policy.external_ai_enabled) {
      return {
        label: '默认拒绝外部 AI',
        detail: '当前 Provider 连接测试会返回 AI_SECURITY_BLOCKED；先启用外部 AI 出口才能进行真实连通性测试。',
        icon: CloudOff,
        tone: 'warning' as StatusTone,
      };
    }
    if (devPassthroughActive) {
      return {
        label: 'AI 临时黑名单模式已开启',
        detail: '普通请求不再因数据分类被拦截，也不做最小化和 Token 化；凭据 DLP、Kill Switch、Provider/区域/租户权限、请求大小、危险工具/写入操作以及跨租户和凭据读取拦截仍然保留。',
        icon: AlertTriangle,
        tone: 'warning' as StatusTone,
      };
    }
    return {
      label: '安全网关已就绪',
      detail: '请求会先经过数据分级、脱敏/最小化、Token 化和 DLP 检查，再转发到允许的 Provider。',
      icon: ShieldCheck,
      tone: 'success' as StatusTone,
    };
  }, [devPassthroughActive, policy.external_ai_enabled, policy.kill_switch]);

  const StatusIcon = status.icon;
  const statusBorder = status.tone === 'danger' ? 'border-l-danger' : status.tone === 'warning' ? 'border-l-warning' : 'border-l-success';
  const statusIconTone = status.tone === 'danger' ? 'bg-danger-subtle text-danger' : status.tone === 'warning' ? 'bg-warning-subtle text-warning' : 'bg-success-subtle text-success';
  const openIncidentCount = incidents.filter((incident) => incident.status !== 'resolved').length;

  if (loading) {
    return (
      <div role="status" aria-busy="true" className="flex min-h-[420px] items-center justify-center rounded-xl border border-line bg-surface text-sm text-fg-muted">
        <div className="flex items-center gap-3"><RefreshCw className="h-4 w-4 animate-spin text-accent motion-reduce:animate-none" aria-hidden="true" />正在读取安全网关策略…</div>
      </div>
    );
  }

  return (
    <div className="w-full space-y-4 pb-8">
      <PageHeader
        title="AI 安全网关"
        description="统一控制外部 AI 出口：默认拒绝、可审计、可演练。"
        infoLabel="AI 安全网关说明"
        info="Provider 连接测试和所有 AI 调用都必须经过这里；策略保存后立即对新的请求生效，已存在的请求不会被重新放行。"
        actions={(
          <ActionButton
            type="button"
            icon={RefreshCw}
            iconClassName={saving ? 'animate-spin motion-reduce:animate-none' : undefined}
            size="md"
            onClick={() => void load()}
            disabled={saving || testing}
          >
            刷新状态
          </ActionButton>
        )}
      />

      <SummaryBar
        label="AI 安全网关概览"
        items={[
          { key: 'egress', value: policy.external_ai_enabled ? '已启用' : '默认拒绝', label: '外部 AI 出口', tone: policy.external_ai_enabled ? 'accent' : 'warning' },
          { key: 'kill', value: policy.kill_switch ? '已触发' : '未触发', label: '紧急停止', tone: policy.kill_switch ? 'danger' : 'success' },
          { key: 'providers', value: (policy.allowed_provider_types || []).length, label: '允许的 Provider 类型' },
          { key: 'payload', value: formatBytes(policy.max_payload_bytes), label: '单次 Payload 上限' },
          { key: 'incidents', value: incidentTotal, label: '安全事件', tone: openIncidentCount > 0 ? 'danger' : undefined },
          { key: 'events', value: eventTotal, label: '审计事件' },
        ]}
      />

      {error && (
        <div role="alert" className="flex items-start gap-3 rounded-lg border border-line border-l-[3px] border-l-danger bg-danger-subtle px-4 py-3 text-[13px] text-danger">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span className="flex-1">{error}</span>
          <button type="button" onClick={() => setError(null)} aria-label="关闭错误提示" className="rounded-md p-0.5 hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"><XCircle className="h-4 w-4" aria-hidden="true" /></button>
        </div>
      )}
      {notice && (
        <div role="status" className="flex items-center gap-3 rounded-lg border border-line border-l-[3px] border-l-success bg-success-subtle px-4 py-3 text-[13px] text-success">
          <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span className="flex-1">{notice}</span>
          <span className="text-xs opacity-75">{lastSavedAt ? `刚刚 ${lastSavedAt.toLocaleTimeString()}` : ''}</span>
        </div>
      )}

      <Panel className={cn('border-l-[3px] px-4 py-4', statusBorder)} aria-label="当前网关状态">
        <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-center">
          <div className="flex items-start gap-3">
            <span className={cn('flex h-10 w-10 shrink-0 items-center justify-center rounded-lg', statusIconTone)}><StatusIcon className="h-5 w-5" aria-hidden="true" /></span>
            <div className="min-w-0">
              <div className="text-xs text-fg-muted">当前网关状态</div>
              <h3 className="mt-0.5 text-base font-semibold text-fg">{status.label}</h3>
              <p className="mt-1 max-w-3xl text-[13px] leading-5 text-fg-muted">{status.detail}</p>
            </div>
          </div>
          <StatusBadge tone={devPassthroughActive ? 'warning' : gatewayReady ? 'success' : 'danger'} dot>
            {devPassthroughActive ? '临时黑名单 · 定时' : gatewayReady ? '安全网关 · 已就绪' : '策略已阻断'}
          </StatusBadge>
        </div>
      </Panel>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(360px,0.85fr)]">
        <Panel>
          <PanelHeader
            title={<span className="inline-flex items-center gap-2"><LockKeyhole className="h-4 w-4 text-accent" aria-hidden="true" />出口控制</span>}
            description="只在明确需要时开启外部 AI；紧急停止可以随时切断出口。"
            actions={<StatusBadge tone="accent">Administrator</StatusBadge>}
          />
          <div className="grid gap-3 p-4 md:grid-cols-2">
            <ControlCard
              icon={CloudOff}
              title="外部 AI 出口"
              checked={policy.external_ai_enabled}
              disabled={saving}
              switchLabel="切换外部 AI 出口"
              onToggle={toggleExternalAI}
              stateText={policy.external_ai_enabled ? '已启用 · 按策略检查' : '默认拒绝 · fail closed'}
              stateTone={policy.external_ai_enabled ? 'accent' : 'warning'}
              description="开启后，只有通过本网关检查并命中允许 Provider 类型的请求才会出站。"
              footer={(
                <div className="flex items-center justify-between gap-2">
                  <span>允许 Provider</span>
                  <code className="truncate rounded bg-surface-muted px-1.5 py-0.5 font-mono text-fg" title={(policy.allowed_provider_types || []).join(', ')}>{(policy.allowed_provider_types || []).join(', ') || 'none'}</code>
                </div>
              )}
            />

            <ControlCard
              icon={Skull}
              title="紧急停止"
              checked={policy.kill_switch}
              danger
              disabled={saving}
              switchLabel="切换 AI 紧急停止"
              onToggle={() => void toggleKillSwitch()}
              stateText={policy.kill_switch ? '已触发 · 全部出口阻断' : '未触发 · 正常运行'}
              stateTone={policy.kill_switch ? 'danger' : 'success'}
              description="故障、泄露或策略异常时立即阻断所有外部调用，不会自动降级到未受控的 Provider。"
              footer="适合应急处置，解除后请重新运行策略演练。"
            />

            <ControlCard
              icon={ShieldAlert}
              title="当前租户开关"
              checked={tenantPaused}
              danger
              disabled={saving}
              switchLabel="切换当前租户 AI 开关"
              onToggle={() => void toggleTenantKillSwitch()}
              stateText={tenantPaused ? '已暂停' : '未暂停'}
              stateTone={tenantPaused ? 'danger' : 'success'}
              description="租户开关优先于 Provider 配置，只影响当前认证租户。"
            />

            {policy.dev_passthrough?.supported && (
              <ControlCard
                icon={AlertTriangle}
                title="AI 临时黑名单模式"
                checked={Boolean(policy.dev_passthrough.enabled)}
                danger
                disabled={saving}
                switchLabel="切换 AI 临时测试模式"
                onToggle={() => void toggleTemporaryTestMode()}
                stateText={policy.dev_passthrough.enabled ? `已开启 · 剩余 ${Math.ceil(policy.dev_passthrough.remaining_seconds / 60)} 分钟` : '未开启'}
                stateTone={policy.dev_passthrough.enabled ? 'warning' : 'neutral'}
                description={(
                  <span className="inline-flex items-start gap-1">
                    管理员临时测试使用，最多 15 分钟，重启自动关闭。
                    <InfoTip label="临时黑名单模式说明">普通请求不再因数据分类被拦截，也不做最小化和 Token 化；仅保留凭据 DLP、Kill Switch、Provider/区域/租户权限、请求大小、危险工具/写入操作以及跨租户和凭据读取拦截。</InfoTip>
                  </span>
                )}
              />
            )}

            <div className="rounded-lg border border-line bg-surface p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-center gap-2"><EyeOff size={16} strokeWidth={1.8} aria-hidden="true" className="text-accent" /><span className="truncate text-sm font-semibold text-fg">敏感内容最小化</span></div>
                <SwitchButton
                  checked={policy.allow_sensitive_minimization}
                  disabled={saving}
                  onClick={() => void save({ allow_sensitive_minimization: !policy.allow_sensitive_minimization })}
                  label="切换敏感内容最小化"
                />
              </div>
              <div className="mt-3"><StatusBadge tone={policy.allow_sensitive_minimization ? 'success' : 'neutral'} dot>{policy.allow_sensitive_minimization ? '已开启' : '已关闭'}</StatusBadge></div>
              <p className="mt-2 text-xs leading-5 text-fg-muted">开启时自动裁剪无关配置上下文；关闭则直接按分类与 DLP 拦截。</p>
              <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-3">
                <label htmlFor="ai-max-payload-kb" className="text-xs font-medium text-fg-muted">单次 Payload 上限 (KB)</label>
                <input
                  id="ai-max-payload-kb"
                  type="number"
                  min={16}
                  max={4096}
                  value={maxPayloadKbInput}
                  onChange={(event) => setMaxPayloadKbInput(event.target.value)}
                  className={cn(filterControlClass, 'h-8 w-24 px-2.5 font-mono text-xs')}
                />
                <ActionButton
                  type="button"
                  icon={Save}
                  variant="primary"
                  disabled={saving}
                  className="ml-auto"
                  onClick={() => {
                    const kb = Math.max(16, Math.min(4096, Number(maxPayloadKbInput) || 250));
                    setMaxPayloadKbInput(String(kb));
                    void save({ max_payload_bytes: kb * 1024 });
                  }}
                >
                  保存上限
                </ActionButton>
              </div>
            </div>
          </div>
        </Panel>

        <Panel>
          <PanelHeader
            title={<span className="inline-flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-success" aria-hidden="true" />数据保护基线</span>}
            description="这些约束在网关层执行，Provider 无法绕过。"
            actions={<StatusBadge tone={devPassthroughActive ? 'warning' : 'success'}>{devPassthroughActive ? '黑名单基线' : 'Fail closed'}</StatusBadge>}
          />
          <div className="divide-y divide-line">
            <GuardrailRow
              icon={<Fingerprint className="h-4 w-4" />}
              label="敏感标识符 Token 化"
              description={devPassthroughActive ? '临时黑名单模式不再对普通标识符做 Token 化；密码、API Key、Token、私钥和 Cookie 仍由凭据 DLP 拦截。' : '设备 IP、用户名、密钥等标识在出站前替换为稳定 Token。'}
              enabled={policy.identifiers_must_be_tokenized}
              state={devPassthroughActive ? 'bypass' : undefined}
            />
            <GuardrailRow
              icon={<EyeOff className="h-4 w-4" />}
              label="敏感内容最小化"
              description={devPassthroughActive ? '临时黑名单模式不再对普通内容做最小化，便于联调时保留完整上下文；硬凭据 DLP 不放开。' : '只保留当前分析所需内容，减少原始配置和凭据暴露。'}
              enabled={policy.allow_sensitive_minimization}
              state={devPassthroughActive ? 'bypass' : undefined}
            />
            <GuardrailRow
              icon={<LockKeyhole className="h-4 w-4" />}
              label="数据分类边界"
              description={devPassthroughActive ? '临时黑名单模式不再因普通数据分类阻断请求；Provider 类型、区域和租户权限仍在网关执行。' : `允许分类 ${policy.allowed_classifications?.join('、') || 'PUBLIC/INTERNAL/CONFIDENTIAL'}。`}
              enabled={(policy.allowed_classifications || []).length > 0}
              state={devPassthroughActive ? 'bypass' : undefined}
            />
            <GuardrailRow
              icon={<CloudOff className="h-4 w-4" />}
              label="Provider / 区域 / 租户权限"
              description={`只允许已配置 Provider 类型和区域（${policy.allowed_data_regions?.join('、') || 'unknown'}），并继续执行当前租户授权与租户开关。`}
              enabled={(policy.allowed_provider_types || []).length > 0 && (policy.allowed_data_regions || []).length > 0}
            />
            <GuardrailRow
              icon={<Database className="h-4 w-4" />}
              label="请求体大小限制"
              description={`单次 payload 上限 ${formatBytes(policy.max_payload_bytes)}，超过即拒绝。`}
              enabled={policy.max_payload_bytes > 0}
            />
            <GuardrailRow icon={<ShieldCheck className="h-4 w-4" />} label="凭据 DLP" description="密码、API Key、Token、私钥、Cookie、JWT 以及凭据字段始终禁止出站。" enabled />
            <GuardrailRow icon={<Skull className="h-4 w-4" />} label="危险工具与写入操作拦截" description="raw SSH/SQL、设备写入命令、配置变更、提交、删除和重启等操作始终拦截。" enabled />
            <GuardrailRow icon={<LockKeyhole className="h-4 w-4" />} label="跨租户与凭据读取拦截" description="跨租户私有数据访问、凭据查询、导出和读取请求始终拦截。" enabled />
            <GuardrailRow icon={<AlertTriangle className="h-4 w-4" />} label="Kill Switch" description="全局、Provider 和租户 Kill Switch 一旦触发，立即阻断全部外部 AI 出口。" enabled />
          </div>
        </Panel>
      </div>

      <Panel>
        <PanelHeader title="一条请求如何通过网关" description="每个外部 AI 请求按顺序经过以下检查。" />
        <ol className="flex flex-col gap-2 p-4 md:flex-row md:items-stretch md:gap-0">
          {[
            ['01', '数据分级', '识别敏感等级'],
            ['02', '最小化', '压缩必要上下文'],
            ['03', 'Token 化', '替换敏感标识'],
            ['04', 'DLP 检查', '发现即阻断'],
            ['05', 'Provider', '按 allowlist 控制 DeepSeek、OpenAI-compatible、Azure、Ollama 等适配器'],
          ].map(([number, title, detail], index, steps) => (
            <React.Fragment key={number}>
              <li className="flex min-w-0 flex-1 items-center gap-3 rounded-lg border border-line bg-surface-muted px-3 py-2.5">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-accent-subtle font-mono text-xs font-semibold text-accent">{number}</span>
                <span className="min-w-0"><span className="block text-[13px] font-medium text-fg">{title}</span><span className="mt-0.5 block truncate text-xs text-fg-muted" title={detail}>{detail}</span></span>
              </li>
              {index < steps.length - 1 && <ChevronRight className="mx-auto h-4 w-4 shrink-0 self-center text-fg-subtle md:mx-1.5" aria-hidden="true" />}
            </React.Fragment>
          ))}
        </ol>
      </Panel>

      <Panel>
        <PanelHeader
          title={<span className="inline-flex items-center gap-2"><AlertTriangle className="h-4 w-4 text-danger" aria-hidden="true" />安全事件响应</span>}
          description="阻断请求只保留元数据证据；处理动作受租户和 Administrator 权限保护。"
          actions={<StatusBadge tone={incidentTotal > 0 ? 'danger' : 'neutral'}>{incidentTotal} 条匹配</StatusBadge>}
        />
        <div className="p-4">
          <form onSubmit={(event) => { event.preventDefault(); setIncidentPage(1); setIncidentSearchApplied(incidentSearch.trim()); }} className="flex flex-wrap gap-2">
            <div className="relative min-w-[240px] flex-1">
              <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-fg-subtle" aria-hidden="true" />
              <input type="search" value={incidentSearch} onChange={(event) => setIncidentSearch(event.target.value)} placeholder="搜索请求 ID、任务、类型或分类" aria-label="搜索安全事件" className={cn(filterControlClass, 'w-full pl-9')} />
            </div>
            <select value={incidentStatus} onChange={(event) => { setIncidentStatus(event.target.value); setIncidentPage(1); }} aria-label="按状态筛选安全事件" className={filterControlClass}><option value="">全部状态</option><option value="open">待处理</option><option value="investigating">处理中</option><option value="resolved">已解决</option></select>
            <select value={incidentSeverity} onChange={(event) => { setIncidentSeverity(event.target.value); setIncidentPage(1); }} aria-label="按级别筛选安全事件" className={filterControlClass}><option value="">全部级别</option><option value="critical">Critical</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select>
          </form>
          <div className="mt-3">
            {incidentsLoading ? (
              <div className="py-6 text-center text-xs text-fg-muted">正在加载安全事件…</div>
            ) : incidents.length === 0 ? (
              <EmptyState icon={ShieldCheck} title="当前筛选没有匹配的安全事件" description="网关阻断或判定异常的请求会在这里生成事件记录。" className="py-8" />
            ) : (
              <ul className="divide-y divide-line rounded-lg border border-line">
                {incidents.map((incident) => (
                  <li key={incident.id} className="flex flex-wrap items-center gap-3 px-3 py-2 text-[13px] transition-colors hover:bg-accent-subtle">
                    <span className="font-medium text-fg">{incident.incident_type}</span>
                    <StatusBadge tone={severityTone(incident.severity)}>{incident.severity}</StatusBadge>
                    <span className="text-xs text-fg-muted">{incident.created_at}</span>
                    <span className="ml-auto"><StatusBadge tone={incidentStatusTone(incident.status)} dot>{incidentStatusLabel(incident.status)}</StatusBadge></span>
                    {incident.status !== 'resolved' && (
                      <ActionButton type="button" variant="success" icon={CheckCircle2} onClick={() => void resolveIncident(incident.id)}>标记已解决</ActionButton>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <Pagination currentPage={incidentPage} totalItems={incidentTotal} itemsPerPage={incidentPageSize} onPageChange={setIncidentPage} onItemsPerPageChange={(size) => { setIncidentPageSize(size); setIncidentPage(1); }} language="zh" alwaysVisible />
        </div>
      </Panel>

      <Panel>
        <PanelHeader
          title={<span className="inline-flex items-center gap-2"><Database className="h-4 w-4 text-accent" aria-hidden="true" />安全事件审计</span>}
          description="仅展示策略版本、分类、处置、Provider/Model 和请求 ID，不返回原始提示词或秘密。"
          actions={<ActionButton type="button" icon={RefreshCw} iconClassName={eventsLoading ? 'animate-spin motion-reduce:animate-none' : undefined} onClick={() => void loadEvents()}>刷新事件</ActionButton>}
        />
        <div className="p-4">
          <form onSubmit={(event) => { event.preventDefault(); setEventPage(1); setEventSearchApplied(eventSearch.trim()); }} className="flex flex-wrap gap-2">
            <div className="relative min-w-[240px] flex-1">
              <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-fg-subtle" aria-hidden="true" />
              <input type="search" value={eventSearch} onChange={(event) => setEventSearch(event.target.value)} placeholder="搜索 Request ID、Provider、Model 或错误码" aria-label="搜索审计事件" className={cn(filterControlClass, 'w-full pl-9')} />
            </div>
            <select value={eventDecision} onChange={(event) => { setEventDecision(event.target.value); setEventPage(1); }} aria-label="按决定筛选审计事件" className={filterControlClass}><option value="">全部决定</option><option value="ALLOW">ALLOW</option><option value="MINIMIZE">MINIMIZE</option><option value="TOKENIZE">TOKENIZE</option><option value="BLOCK">BLOCK</option></select>
          </form>
          <div className="mt-3 overflow-x-auto rounded-lg border border-line">
            <DataTable unstyled exportConfig={{ filename: 'ai-security-events', language: 'zh', disabled: eventsLoading || eventTotal === 0, exportData: exportAllEvents }} className="min-w-[900px] text-left">
              <thead className="bg-surface-muted">
                <tr>
                  <th className={tableHeadClass}>时间</th>
                  <th className={tableHeadClass}>决定</th>
                  <th className={tableHeadClass}>分类</th>
                  <th className={tableHeadClass}>Provider ID</th>
                  <th className={tableHeadClass}>Model ID</th>
                  <th className={tableHeadClass}>发现项</th>
                </tr>
              </thead>
              <tbody>
                {!eventsLoading && events.map((event) => (
                  <tr key={event.id} className="border-t border-line transition-colors hover:bg-accent-subtle">
                    <td className={cn(tableCellClass, 'whitespace-nowrap text-fg-muted')}>{event.created_at}</td>
                    <td className={tableCellClass}><StatusBadge tone={decisionTone(event.decision)} mono>{event.decision}</StatusBadge></td>
                    <td className={tableCellClass}><StatusBadge mono>{event.classification}</StatusBadge></td>
                    <td className={cn(tableCellClass, 'max-w-[180px] truncate font-mono text-xs')} title={event.provider_id || ''}>{event.provider_id || '—'}</td>
                    <td className={cn(tableCellClass, 'max-w-[180px] truncate font-mono text-xs')} title={event.model_id || ''}>{event.model_id || '—'}</td>
                    <td className={cn(tableCellClass, 'max-w-[240px] truncate')} title={event.finding_categories?.join('、') || ''}>{event.finding_categories?.join('、') || '无'}</td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
            {eventsLoading ? (
              <div className="py-6 text-center text-xs text-fg-muted">正在加载审计事件…</div>
            ) : events.length === 0 && (
              <div className="py-6 text-center text-xs text-fg-muted">当前筛选没有匹配的审计事件</div>
            )}
          </div>
          <Pagination currentPage={eventPage} totalItems={eventTotal} itemsPerPage={eventPageSize} onPageChange={setEventPage} onItemsPerPageChange={(size) => { setEventPageSize(size); setEventPage(1); }} language="zh" alwaysVisible />
        </div>
      </Panel>

      <Panel>
        <PanelHeader
          title={<span className="inline-flex items-center gap-2"><FlaskConical className="h-4 w-4 text-accent" aria-hidden="true" />策略演练</span>}
          description="只在本地执行安全检查，不会调用外部 Provider。用它验证某段内容为什么会被允许、最小化或阻断。"
          actions={<StatusBadge tone="accent">No external call</StatusBadge>}
        />
        <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_minmax(260px,0.42fr)]">
          <div>
            <label htmlFor="ai-security-dry-run" className="mb-1.5 block text-[13px] font-medium text-fg">待检查内容</label>
            <textarea
              id="ai-security-dry-run"
              value={sample}
              onChange={(event) => setSample(event.target.value)}
              className="min-h-[170px] w-full resize-y rounded-lg border border-line bg-surface p-3 font-mono text-[13px] leading-6 text-fg outline-none transition-colors placeholder:text-fg-subtle focus:border-accent focus:ring-2 focus:ring-accent/20"
              placeholder="输入命令、配置片段或对话内容…"
            />
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <ActionButton type="button" variant="primary" size="md" icon={FlaskConical} iconClassName={testing ? 'animate-pulse motion-reduce:animate-none' : undefined} disabled={testing} onClick={() => void runDryRun()}>
                {testing ? '检查中…' : '运行策略检查'}
              </ActionButton>
              <span className="text-xs text-fg-muted">演练结果不会改变当前策略。</span>
            </div>
          </div>
          <div className="rounded-lg border border-dashed border-line-strong bg-surface-muted p-4">
            <div className="text-[13px] font-medium text-fg">检查结果</div>
            {dryRun ? (
              <div className="mt-3 space-y-3">
                <div role="status" aria-label="策略检查结果" className={cn('rounded-lg border border-line border-l-[3px] px-3 py-2.5 text-sm font-semibold', decisionPanelClass(dryRun.decision))}>
                  {dryRun.decision} <span className="ml-1 text-xs font-normal opacity-80">/ {dryRun.max_data_level}{dryRun.security_mode === 'blacklist' ? ' · 临时黑名单' : ''}</span>
                </div>
                <dl className="grid grid-cols-2 gap-2 text-xs">
                  <div className="rounded-lg border border-line bg-surface p-3"><dt className="text-fg-muted">Payload</dt><dd className="mt-1 font-mono font-semibold tabular-nums text-fg">{dryRun.payload_bytes?.toLocaleString() || '—'} B</dd></div>
                  <div className="rounded-lg border border-line bg-surface p-3"><dt className="text-fg-muted">Findings</dt><dd className="mt-1 font-semibold text-fg">{(dryRun.finding_categories || []).join('、') || '无'}</dd></div>
                </dl>
                <p className="text-xs leading-5 text-fg-muted">{dryRun.user_message || dryRun.reason || dryRun.reason_code || '策略检查完成，未发现需要额外处理的问题。'}</p>
              </div>
            ) : (
              <EmptyState icon={ShieldCheck} title="尚未运行检查" description="输入内容后运行一次检查，结果会显示在这里。" className="mt-3 border-0 bg-transparent px-2 py-6" />
            )}
          </div>
        </div>
      </Panel>
    </div>
  );
};

export default SecurityPolicyTab;
