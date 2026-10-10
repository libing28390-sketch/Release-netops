import React, { useEffect, useMemo, useState } from 'react';
import { ExternalLink, Gauge, Link2, Network, Pencil, Save, ShieldCheck, X } from 'lucide-react';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { WanCircuitHistoryResponse, WanCircuitItem, WanCircuitSlaPolicyPayload, WanCircuitSlaResponse } from '../../types/wan-circuits';
import { alertPanelClass } from '../shared';
import { ActionButton, ActionLink } from '../ui/ActionIconButton';
import { ErrorState, ForbiddenState, LoadingState } from './WanCircuitStates';
import { circuitSeverityClass, circuitStatusBadgeClass, circuitStatusLabel } from './WanCircuitTable';

interface Props {
  item: WanCircuitItem | null;
  history: WanCircuitHistoryResponse | null;
  sla: WanCircuitSlaResponse | null;
  language: 'zh' | 'en';
  loading?: boolean;
  historyLoading?: boolean;
  slaLoading?: boolean;
  historyError?: string;
  slaError?: string;
  error?: string;
  forbidden?: boolean;
  onRetry?: () => void;
  onSaveSlaPolicy?: (payload: WanCircuitSlaPolicyPayload) => Promise<void>;
  savingSlaPolicy?: boolean;
}

const safeExternalUrl = (value?: string | null) => {
  if (!value) return null;
  try {
    const url = new URL(value, window.location.origin);
    if (url.protocol === 'http:' || url.protocol === 'https:') return url.toString();
  } catch { /* invalid links stay hidden */ }
  return null;
};

const formatDate = (value?: string | null, zh = true) => value ? new Date(value).toLocaleString(zh ? 'zh-CN' : 'en-US') : '--';
const formatPercent = (value?: number | null) => value == null ? '--' : `${Number(value).toFixed(2)}%`;
type PolicyForm = {
  availability_target_pct: string;
  latency_target_ms: string;
  loss_target_pct: string;
  measurement_window_days: string;
  minimum_coverage_pct: string;
  minimum_rtt_samples: string;
  minimum_loss_packets: string;
  availability_rule: 'any_success' | 'all_success';
  timezone: string;
  maintenance_excluded: boolean;
};
const defaultPolicyForm = (sla: WanCircuitSlaResponse | null): PolicyForm => {
  const policy = sla?.policy;
  return {
    availability_target_pct: String(policy?.availability_target_pct ?? 99.9), latency_target_ms: policy?.latency_target_ms == null ? '' : String(policy.latency_target_ms), loss_target_pct: policy?.loss_target_pct == null ? '' : String(policy.loss_target_pct),
    measurement_window_days: String(policy?.measurement_window_days ?? 30), minimum_coverage_pct: String(policy?.minimum_coverage_pct ?? 99), minimum_rtt_samples: String(policy?.minimum_rtt_samples ?? 100), minimum_loss_packets: String(policy?.minimum_loss_packets ?? 1000), availability_rule: policy?.availability_rule ?? 'any_success', timezone: policy?.timezone ?? 'Asia/Shanghai', maintenance_excluded: policy?.maintenance_excluded ?? false,
  };
};

export const WanCircuitDetail: React.FC<Props> = ({ item, history, sla, language, loading, historyLoading, slaLoading, historyError, slaError, error, forbidden, onRetry, onSaveSlaPolicy, savingSlaPolicy }) => {
  const zh = language === 'zh';
  const chartData = useMemo(() => (history?.history || []).map((sample) => ({
    time: formatDate(sample.sampled_at, zh),
    download: sample.download_util_pct,
    upload: sample.upload_util_pct,
    collection: sample.collection_status,
  })), [history, zh]);
  const [editingSlaPolicy, setEditingSlaPolicy] = useState(false);
  const [policyForm, setPolicyForm] = useState<PolicyForm>(() => defaultPolicyForm(sla));
  useEffect(() => { if (!editingSlaPolicy) setPolicyForm(defaultPolicyForm(sla)); }, [editingSlaPolicy, sla]);
  const updatePolicy = (key: keyof PolicyForm, value: string | boolean) => setPolicyForm((current) => ({ ...current, [key]: value } as PolicyForm));
  const submitPolicy = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!onSaveSlaPolicy) return;
    try {
      await onSaveSlaPolicy({
        expected_version: sla?.policy_version ?? 0,
        availability_target_pct: Number(policyForm.availability_target_pct), latency_target_ms: policyForm.latency_target_ms === '' ? null : Number(policyForm.latency_target_ms), loss_target_pct: policyForm.loss_target_pct === '' ? null : Number(policyForm.loss_target_pct),
        measurement_window_days: Number(policyForm.measurement_window_days), minimum_coverage_pct: Number(policyForm.minimum_coverage_pct), minimum_rtt_samples: Number(policyForm.minimum_rtt_samples), minimum_loss_packets: Number(policyForm.minimum_loss_packets), availability_rule: policyForm.availability_rule, timezone: policyForm.timezone, maintenance_excluded: policyForm.maintenance_excluded,
      });
    } catch {
      return;
    }
    setEditingSlaPolicy(false);
  };

  if (loading) return <LoadingState label={zh ? '加载线路详情…' : 'Loading circuit details…'} />;
  if (forbidden) return <ForbiddenState message={zh ? '当前账号没有查看该线路详情的权限。' : 'Your account is not allowed to view this circuit detail.'} />;
  if (error) return <ErrorState title={zh ? '线路详情加载失败' : 'Circuit details failed to load'} message={error} onAction={onRetry} actionLabel={zh ? '重试' : 'Retry'} />;
  if (!item) return <div className={`${alertPanelClass} flex min-h-48 items-center justify-center p-8 text-sm text-[var(--muted-text)]`}>{zh ? '选择一条线路查看详情' : 'Select a circuit to view details'}</div>;

  const status = item.health_status || 'unknown';
  const grafanaUrl = safeExternalUrl(item.grafana_url);
  const diagnosticsUrl = safeExternalUrl(item.diagnostics_url);
  const availability = sla?.availability;
  const slots = sla?.slots;
  const slotDistribution = typeof slots === 'object' && slots !== null ? slots : null;
  return (
    <section className="space-y-4" aria-label={zh ? '线路详情' : 'Circuit details'}>
      <div className={`${alertPanelClass} p-4`}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2"><h2 className="truncate text-base font-bold text-[var(--heading-text)]">{item.link_name || item.id}</h2><span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${circuitStatusBadgeClass(status)}`}>{circuitStatusLabel(status, zh)}</span></div>
            <p className="mt-1 text-xs text-[var(--muted-text)]">{item.site_name || item.site_id || '--'} · {item.provider || (zh ? '运营商未填写' : 'Provider not set')} · {item.interface_name || '--'}</p>
          </div>
          <div className="flex flex-wrap gap-2">{grafanaUrl && <ActionLink href={grafanaUrl} target="_blank" rel="noreferrer" icon={ExternalLink} variant="default" size="sm">Grafana</ActionLink>}{diagnosticsUrl && <ActionLink href={diagnosticsUrl} target="_blank" rel="noreferrer" icon={Network} variant="default" size="sm">{zh ? '设备诊断' : 'Diagnostics'}</ActionLink>}</div>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Metric icon={Link2} label={zh ? '线路编号' : 'Circuit number'} value={item.circuit_number || '--'} />
          <Metric icon={Gauge} label={zh ? '接口状态' : 'Interface status'} value={`${item.admin_status || '--'} / ${item.oper_status || '--'}`} />
          <Metric icon={ShieldCheck} label={zh ? '配置版本' : 'Configuration version'} value={item.configuration_version == null ? '--' : String(item.configuration_version)} />
          <Metric icon={Network} label={zh ? '最新采集' : 'Last collection'} value={formatDate(item.last_success_at || item.sampled_at, zh)} />
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(300px,1fr)]">
        <div className={`${alertPanelClass} p-4`}>
          <div className="flex flex-wrap items-start justify-between gap-2"><div><h3 className="text-sm font-bold text-[var(--heading-text)]">{zh ? '历史趋势与采集证据' : 'History and collection evidence'}</h3><p className="mt-1 text-[11px] text-[var(--muted-text)]">{history ? `${formatDate(history.start_time, zh)} – ${formatDate(history.end_time, zh)}` : (historyError || (zh ? '历史数据不可用' : 'History unavailable'))}</p></div>{historyLoading && <span className="text-xs text-[var(--muted-text)]">{zh ? '加载中…' : 'Loading…'}</span>}</div>
          <div className="mt-3 h-56">{historyLoading ? <LoadingState label={zh ? '加载历史样本…' : 'Loading samples…'} /> : chartData.length > 0 ? <ResponsiveContainer width="100%" height="100%"><AreaChart data={chartData} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}><CartesianGrid strokeDasharray="3 3" stroke="var(--ui-border)" /><XAxis dataKey="time" tick={{ fontSize: 10 }} minTickGap={28} /><YAxis domain={[0, 100]} unit="%" tick={{ fontSize: 10 }} /><Tooltip /><Area type="monotone" dataKey="download" name={zh ? '下行利用率' : 'Download utilisation'} stroke="var(--ui-accent)" fill="var(--ui-accent)" fillOpacity={0.14} connectNulls={false} /><Area type="monotone" dataKey="upload" name={zh ? '上行利用率' : 'Upload utilisation'} stroke="#8b5cf6" fill="#8b5cf6" fillOpacity={0.1} connectNulls={false} /></AreaChart></ResponsiveContainer> : <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-[var(--ui-border)] px-4 text-center text-xs text-[var(--muted-text)]">{zh ? '暂无有效历史样本；当前状态不能推导端到端可用性。' : 'No valid history samples; interface status cannot establish end-to-end availability.'}</div>}</div>
          {history && <div className="mt-3 grid gap-2 text-[11px] text-[var(--muted-text)] sm:grid-cols-3"><span>{zh ? '样本' : 'Samples'}：{history.history?.length || 0}</span><span>{zh ? '分辨率' : 'Resolution'}：{history.resolution ? `${history.resolution}s` : '--'}</span><span>{zh ? '事件' : 'Events'}：{history.events?.length || 0}</span></div>}
          {history?.events?.length ? <div className="mt-3 space-y-1">{history.events.slice(0, 5).map((event) => <div key={event.id} className="flex flex-wrap items-center gap-2 rounded-lg bg-[var(--ui-surface-muted)] px-3 py-2 text-[11px]"><span className={`rounded-full px-2 py-0.5 font-semibold ${circuitSeverityClass(event.status)}`}>{event.status}</span><span className="font-medium text-[var(--heading-text)]">{event.title}</span><span className="text-[var(--muted-text)]">{formatDate(event.started_at, zh)}</span></div>)}</div> : null}
        </div>

        <div className={`${alertPanelClass} p-4`}>
          <div className="flex items-start justify-between gap-2"><div><h3 className="text-sm font-bold text-[var(--heading-text)]">{zh ? 'SLA 覆盖' : 'SLA coverage'}</h3><p className="mt-1 text-[11px] text-[var(--muted-text)]">{sla?.window_start && sla.window_end ? `${formatDate(sla.window_start, zh)} – ${formatDate(sla.window_end, zh)}` : (zh ? '窗口不可用' : 'Window unavailable')}</p></div><div className="flex items-center gap-2">{slaLoading && <span className="text-xs text-[var(--muted-text)]">{zh ? '加载中…' : 'Loading…'}</span>}{onSaveSlaPolicy && !editingSlaPolicy && <ActionButton icon={Pencil} size="sm" onClick={() => setEditingSlaPolicy(true)}>{zh ? '编辑策略' : 'Edit policy'}</ActionButton>}</div></div>
          {slaLoading ? <div className="mt-4"><LoadingState label={zh ? '加载 SLA…' : 'Loading SLA…'} /></div> : sla?.status === 'available' ? <div className="mt-4 space-y-4"><div className="rounded-lg bg-[var(--ui-surface-muted)] p-3"><p className="text-[11px] text-[var(--muted-text)]">{zh ? '可用性估计' : 'Availability estimate'}</p><p className="mt-1 text-2xl font-bold text-[var(--heading-text)]">{formatPercent(availability?.value ?? sla.availability_pct)}</p><p className="mt-1 text-[10px] text-[var(--muted-text)]">{zh ? '置信区间' : 'Confidence interval'}：{formatPercent(availability?.lower_bound)} – {formatPercent(availability?.upper_bound)}</p></div><div><p className="mb-2 text-[11px] font-semibold text-[var(--heading-text)]">{zh ? '覆盖数据' : 'Coverage data'} · {formatPercent(sla.coverage_pct)}</p>{slotDistribution ? <div className="grid grid-cols-2 gap-2 text-[11px] text-[var(--muted-text)]"><span>↑ {slotDistribution.up ?? 0}</span><span>↓ {slotDistribution.down ?? 0}</span><span>? {slotDistribution.unknown ?? 0}</span><span>⚙ {slotDistribution.maintenance ?? 0}</span></div> : <div className="text-[11px] text-[var(--muted-text)]">{zh ? '覆盖槽位' : 'Coverage slots'}：{typeof slots === 'number' ? slots : '--'}</div>}</div></div> : <div className="mt-4 rounded-lg border border-dashed border-amber-300 bg-amber-50/70 p-3 text-xs text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-200"><p className="font-semibold">{zh ? 'SLA 数据不足' : 'Insufficient SLA data'}</p><p className="mt-1">{slaError || sla?.reason_code || sla?.reason || (zh ? '后端未提供覆盖原因' : 'No coverage reason supplied by API')}</p><p className="mt-2 text-[11px]">{zh ? '接口 UP 只代表接口状态，不能替代端到端可用性。' : 'Interface UP does not establish end-to-end availability.'}</p></div>}
          {editingSlaPolicy && onSaveSlaPolicy && <form onSubmit={submitPolicy} className="mt-4 space-y-3 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface-muted)] p-3"><div className="flex items-center justify-between gap-2"><div><p className="text-xs font-bold text-[var(--heading-text)]">{zh ? 'SLA 策略' : 'SLA policy'}</p><p className="mt-1 text-[10px] text-[var(--muted-text)]">{zh ? '策略保存成功不代表当前 SLA 已达标。' : 'Saving a policy does not mean the current SLA is passing.'}</p></div><ActionButton icon={X} size="sm" onClick={() => setEditingSlaPolicy(false)}>{zh ? '取消' : 'Cancel'}</ActionButton></div><div className="grid gap-2 sm:grid-cols-2">{([['availability_target_pct', zh ? '可用性目标 %' : 'Availability target %'], ['latency_target_ms', zh ? '延迟目标 ms（可空）' : 'Latency target ms (optional)'], ['loss_target_pct', zh ? '丢包目标 %（可空）' : 'Loss target % (optional)'], ['measurement_window_days', zh ? '测量窗口天数' : 'Measurement window days'], ['minimum_coverage_pct', zh ? '最低覆盖 %' : 'Minimum coverage %'], ['minimum_rtt_samples', zh ? '最少 RTT 样本' : 'Minimum RTT samples'], ['minimum_loss_packets', zh ? '最少丢包样本' : 'Minimum loss packets'], ['timezone', zh ? '时区' : 'Timezone']] as const).map(([key, label]) => <label key={key} className="text-[11px] font-semibold text-[var(--muted-text)]">{label}<input type={key === 'timezone' ? 'text' : 'number'} value={formPolicyValue(policyForm, key)} onChange={(event) => updatePolicy(key, event.target.value)} className="mt-1 w-full rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2.5 py-2 text-xs text-[var(--ui-fg)]" /></label>)}<label className="text-[11px] font-semibold text-[var(--muted-text)]">{zh ? '可用性规则' : 'Availability rule'}<select value={policyForm.availability_rule} onChange={(event) => updatePolicy('availability_rule', event.target.value as PolicyForm['availability_rule'])} className="mt-1 w-full rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2.5 py-2 text-xs text-[var(--ui-fg)]"><option value="any_success">any_success</option><option value="all_success">all_success</option></select></label><label className="flex items-end gap-2 pb-2 text-[11px] font-semibold text-[var(--muted-text)]"><input type="checkbox" checked={policyForm.maintenance_excluded} onChange={(event) => updatePolicy('maintenance_excluded', event.target.checked)} />{zh ? '排除维护窗口' : 'Exclude maintenance'}</label></div><div className="flex justify-end"><ActionButton icon={Save} variant="accent" type="submit" disabled={savingSlaPolicy}>{savingSlaPolicy ? (zh ? '保存中…' : 'Saving…') : (zh ? '保存策略' : 'Save policy')}</ActionButton></div></form>}
        </div>
      </div>

      <div className={`${alertPanelClass} p-4`}><h3 className="text-sm font-bold text-[var(--heading-text)]">{zh ? '端点与合同' : 'Endpoints and contract'}</h3><div className="mt-3 grid gap-3 md:grid-cols-2">{item.endpoints?.length === 2 ? item.endpoints.map((endpoint) => <EndpointCard key={endpoint.id || endpoint.side} endpoint={endpoint} language={language} />) : <div className="rounded-lg border border-dashed border-[var(--ui-border)] p-3 text-xs text-[var(--muted-text)]">{zh ? '后端未返回完整 A/Z 端点，无法确认端到端路径。' : 'The API did not return a complete A/Z pair; the end-to-end path cannot be confirmed.'}</div>}</div><div className="mt-3 grid gap-2 text-xs text-[var(--muted-text)] sm:grid-cols-3"><span>{zh ? '下行合同' : 'Download contract'}：{item.contracted_download_bps ? `${(item.contracted_download_bps / 1_000_000).toFixed(0)} Mbps` : '--'}</span><span>{zh ? '上行合同' : 'Upload contract'}：{item.contracted_upload_bps ? `${(item.contracted_upload_bps / 1_000_000).toFixed(0)} Mbps` : '--'}</span><span>{zh ? 'SLA 目标' : 'SLA target'}：{formatPercent(item.sla_target_pct)}</span></div></div>
    </section>
  );
};

const Metric: React.FC<{ icon: React.ComponentType<{ size?: number; className?: string }>; label: string; value: string }> = ({ icon: Icon, label, value }) => <div className="rounded-lg bg-[var(--ui-surface-muted)] p-3"><div className="flex items-center gap-1.5 text-[10px] text-[var(--muted-text)]"><Icon size={13} />{label}</div><div className="mt-1 truncate text-xs font-semibold text-[var(--heading-text)]" title={value}>{value}</div></div>;

const EndpointCard: React.FC<{ endpoint: NonNullable<WanCircuitItem['endpoints']>[number]; language: 'zh' | 'en' }> = ({ endpoint, language }) => {
  const zh = language === 'zh';
  const managed = endpoint.endpoint_type === 'managed';
  return <div className="rounded-lg border border-[var(--ui-border)] p-3 text-xs"><div className="flex items-center justify-between gap-2"><span className="font-semibold text-[var(--heading-text)]">{endpoint.side} · {managed ? (zh ? '托管' : 'Managed') : (zh ? '非托管' : 'Unmanaged')}</span><span className="text-[10px] text-[var(--muted-text)]">{endpoint.measurement_scope === 'shared_interface' ? (zh ? '共享接口' : 'Shared interface') : endpoint.measurement_scope === 'dedicated' ? (zh ? '专用接口' : 'Dedicated interface') : (zh ? '测量范围未知' : 'Scope unknown')}</span></div><div className="mt-2 grid gap-1 text-[var(--muted-text)]"><span>{zh ? '站点' : 'Site'}：{endpoint.site_name || endpoint.site_id || '--'}</span>{managed ? <><span>{zh ? '设备' : 'Device'}：{endpoint.device_id || '--'}</span><span>{zh ? '接口' : 'Interface'}：{endpoint.interface_id || '--'} · ifIndex {endpoint.if_index ?? '--'}</span></> : <span>{zh ? '端点名称' : 'Endpoint name'}：{endpoint.endpoint_name || '--'}</span>}<span>{zh ? '计数器方向' : 'Counter orientation'}：{endpoint.counter_orientation}</span><span>{zh ? '绑定版本' : 'Binding version'}：{endpoint.binding_version ?? '--'}</span>{endpoint.measurement_scope === 'shared_interface' && <p className="mt-1 rounded-md bg-amber-50 px-2 py-1 text-[10px] text-amber-700 dark:bg-amber-950/20 dark:text-amber-200">{zh ? '共享物理接口：SNMP 计数器是聚合值，线路级利用率/容量告警已停用。' : 'Shared physical interface: SNMP counters are aggregate values; circuit-level utilisation and capacity alerts are disabled.'}</p>}</div></div>;
};

const formPolicyValue = (form: PolicyForm, key: Exclude<keyof PolicyForm, 'availability_rule' | 'maintenance_excluded'>) => String(form[key]);
