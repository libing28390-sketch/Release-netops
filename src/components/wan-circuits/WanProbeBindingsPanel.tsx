import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Pencil, Plus, Save, Trash2, X } from 'lucide-react';
import { ActionButton, ActionIconButton } from '../ui/ActionIconButton';
import { alertPanelClass } from '../shared';
import type { WanProbeBinding, WanProbeBindingPayload, WanProbePurpose, WanProbeTarget } from '../../types/wan-circuits';
import { EmptyState, ErrorState, ForbiddenState, LoadingState } from './WanCircuitStates';

interface Props {
  linkId: string;
  language: 'zh' | 'en';
  canEdit: boolean;
  showToast?: (message: string, type?: 'success' | 'error' | 'info') => void;
}
const authHeaders = (json = false): Record<string, string> => { const token = localStorage.getItem('netops_token'); return { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(json ? { 'Content-Type': 'application/json' } : {}) }; };
const parseError = async (response: Response, fallback: string) => { let message = ''; try { const body = await response.json() as { detail?: { message?: string } | string; message?: string }; message = typeof body.detail === 'string' ? body.detail : body.detail?.message || body.message || ''; } catch { /* non-json */ } const error = new Error(message || fallback); (error as Error & { status?: number }).status = response.status; return error; };
const evidenceLabel = (status: string | null | undefined, zh: boolean) => { if (status === 'verified') return zh ? '已验证' : 'Verified'; if (status === 'insufficient_capability' || status === 'unsupported' || status === 'path_capability_unsupported') return zh ? '执行能力不足' : 'Executor capability unavailable'; if (status === 'source_ip_configured_unverified' || status === 'source_ip_only') return zh ? '来源地址已配置，路径未验证' : 'Source configured; path unverified'; if (status === 'insufficient_default_route' || status === 'default_route_unverified') return zh ? '默认路由未验证' : 'Default route unverified'; if (status === 'unverified' || !status) return zh ? '未验证' : 'Unverified'; return status; };
const PURPOSES: WanProbePurpose[] = ['availability', 'quality', 'application'];
const supportedPurposes = (probeType?: string): WanProbePurpose[] => { if (probeType === 'ICMP_PING') return ['availability', 'quality']; if (probeType === 'TCP_CONNECT') return ['availability']; if (probeType === 'HTTP_GET' || probeType === 'HTTPS_GET' || probeType === 'DNS_RESOLVE') return ['application']; return []; };
const purposeLabel = (purpose: WanProbePurpose, zh: boolean) => ({ availability: zh ? '可用性' : 'Availability', quality: zh ? '质量' : 'Quality', application: zh ? '应用' : 'Application' }[purpose]);

export const WanProbeBindingsPanel: React.FC<Props> = ({ linkId, language, canEdit, showToast }) => {
  const zh = language === 'zh';
  const [targets, setTargets] = useState<WanProbeTarget[]>([]);
  const [bindings, setBindings] = useState<WanProbeBinding[]>([]);
  const [selectedBinding, setSelectedBinding] = useState<WanProbeBinding | null>(null);
  const [targetId, setTargetId] = useState('');
  const [purpose, setPurpose] = useState<WanProbePurpose>('availability');
  const [routeMode, setRouteMode] = useState<'default' | 'source_ip'>('default');
  const [sourceIp, setSourceIp] = useState('');
  const [priority, setPriority] = useState('100');
  const [enabled, setEnabled] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [forbidden, setForbidden] = useState(false);

  const load = useCallback(async (signal: AbortSignal) => {
    setLoading(true); setError(''); setForbidden(false);
    const [targetResponse, bindingResponse] = await Promise.all([
      fetch('/api/monitoring/outbound-targets', { headers: authHeaders(), signal }),
      fetch(`/api/monitoring/wan-probe-bindings?link_id=${encodeURIComponent(linkId)}`, { headers: authHeaders(), signal }),
    ]);
    if (!targetResponse.ok) throw await parseError(targetResponse, zh ? '探针目标加载失败' : 'Probe targets failed to load');
    if (!bindingResponse.ok) throw await parseError(bindingResponse, zh ? '探针绑定加载失败' : 'Probe bindings failed to load');
    const targetBody = await targetResponse.json() as { items?: WanProbeTarget[] };
    const bindingBody = await bindingResponse.json() as { items?: WanProbeBinding[] };
    setTargets(targetBody.items || []); setBindings(bindingBody.items || []); setLoading(false);
  }, [linkId, zh]);

  useEffect(() => { const controller = new AbortController(); void load(controller.signal).catch((cause: unknown) => { if (controller.signal.aborted) return; setLoading(false); if ((cause as Error & { status?: number }).status === 403) setForbidden(true); else setError(cause instanceof Error ? cause.message : (zh ? '探针绑定加载失败' : 'Probe bindings failed to load')); }); return () => controller.abort(); }, [load, zh]);
  const availableTargets = useMemo(() => targets.filter((target) => target.is_active !== false || bindings.some((binding) => binding.target_id === target.id)), [targets, bindings]);
  const selectedTarget = targets.find((target) => target.id === targetId);
  const allowedPurposes = useMemo(() => supportedPurposes(selectedTarget?.probe_type), [selectedTarget?.probe_type]);
  useEffect(() => { if (allowedPurposes.length && !allowedPurposes.includes(purpose)) setPurpose(allowedPurposes[0]); }, [allowedPurposes, purpose]);
  const resetForm = () => { setSelectedBinding(null); setTargetId(''); setPurpose('availability'); setRouteMode('default'); setSourceIp(''); setPriority('100'); setEnabled(true); };
  const editBinding = (binding: WanProbeBinding) => { setSelectedBinding(binding); setTargetId(binding.target_id); setPurpose(PURPOSES.includes(binding.purpose as WanProbePurpose) ? binding.purpose as WanProbePurpose : 'availability'); setRouteMode(binding.route_mode === 'source_ip' ? 'source_ip' : 'default'); setSourceIp(binding.source_ip || ''); setPriority(String(binding.priority ?? 100)); setEnabled(binding.enabled !== false); };
  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canEdit || !targetId || !allowedPurposes.includes(purpose)) return;
    setSaving(true);
    const payload: WanProbeBindingPayload = { link_id: linkId, target_id: targetId, purpose, route_mode: routeMode, source_ip: routeMode === 'source_ip' ? sourceIp.trim() : '', priority: Math.max(1, Number(priority) || 100), enabled };
    try {
      const response = await fetch(selectedBinding ? `/api/monitoring/wan-probe-bindings/${encodeURIComponent(selectedBinding.id)}` : '/api/monitoring/wan-probe-bindings', { method: selectedBinding ? 'PATCH' : 'POST', headers: authHeaders(true), body: JSON.stringify(payload) });
      if (!response.ok) throw await parseError(response, zh ? '探针绑定保存失败' : 'Probe binding save failed');
      resetForm(); await load(new AbortController().signal); showToast?.(zh ? '探针绑定已保存' : 'Probe binding saved', 'success');
    } catch (cause) { if ((cause as Error & { status?: number }).status === 403) setForbidden(true); else { const message = cause instanceof Error ? cause.message : (zh ? '探针绑定保存失败' : 'Probe binding save failed'); setError(message); showToast?.(message, 'error'); } } finally { setSaving(false); }
  };
  const remove = async (binding: WanProbeBinding) => {
    if (!canEdit || !window.confirm(zh ? '确认删除此探针绑定？' : 'Delete this probe binding?')) return;
    try { const response = await fetch(`/api/monitoring/wan-probe-bindings/${encodeURIComponent(binding.id)}`, { method: 'DELETE', headers: authHeaders() }); if (!response.ok) throw await parseError(response, zh ? '探针绑定删除失败' : 'Probe binding delete failed'); await load(new AbortController().signal); showToast?.(zh ? '探针绑定已删除' : 'Probe binding deleted', 'success'); } catch (cause) { if ((cause as Error & { status?: number }).status === 403) setForbidden(true); else { const message = cause instanceof Error ? cause.message : (zh ? '探针绑定删除失败' : 'Probe binding delete failed'); setError(message); showToast?.(message, 'error'); } }
  };

  return <section className={`${alertPanelClass} p-4`} aria-label={zh ? '探针绑定' : 'Probe bindings'}><div className="flex flex-wrap items-start justify-between gap-2"><div><h3 className="text-sm font-bold text-[var(--heading-text)]">{zh ? '探针绑定' : 'Probe bindings'}</h3><p className="mt-1 text-[11px] text-[var(--muted-text)]">{zh ? '系统按线路上下文留存探针结果；只有路径证据通过核验后才进入 SLA，目标可达本身不代表线路已验证。' : 'Probe results are recorded per circuit context. Only verified path evidence can enter SLA; target reachability alone does not verify a circuit.'}</p></div>{!canEdit && <span className="rounded-full bg-slate-100 px-2 py-1 text-[10px] text-slate-600">{zh ? '只读' : 'Read only'}</span>}</div>
    {forbidden ? <div className="mt-3"><ForbiddenState message={zh ? '当前账号无权查看或编辑探针绑定。' : 'Your account cannot view or edit probe bindings.'} /></div> : loading ? <div className="mt-3"><LoadingState label={zh ? '加载探针绑定…' : 'Loading probe bindings…'} /></div> : error ? <div className="mt-3"><ErrorState title={zh ? '探针绑定加载失败' : 'Probe bindings failed'} message={error} onAction={() => { const controller = new AbortController(); void load(controller.signal); }} actionLabel={zh ? '重试' : 'Retry'} /></div> : <>
      {canEdit && <form onSubmit={save} className="mt-3 grid gap-2 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface-muted)] p-3 sm:grid-cols-2 lg:grid-cols-4"><select value={targetId} onChange={(event) => setTargetId(event.target.value)} aria-label={zh ? '探针目标' : 'Probe target'} className="rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2.5 py-2 text-xs text-[var(--ui-fg)]"><option value="">{zh ? '选择已有目标' : 'Select target'}</option>{availableTargets.map((target) => <option key={target.id} value={target.id}>{target.target_name} · {target.probe_type}</option>)}</select><select value={purpose} onChange={(event) => setPurpose(event.target.value as WanProbePurpose)} aria-label={zh ? '探针用途' : 'Probe purpose'} className="rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2.5 py-2 text-xs text-[var(--ui-fg)]">{PURPOSES.map((option) => <option key={option} value={option} disabled={!allowedPurposes.includes(option)}>{purposeLabel(option, zh)} · {option}{!allowedPurposes.includes(option) ? (zh ? '（协议不支持）' : ' (unsupported)') : ''}</option>)}</select><select value={routeMode} onChange={(event) => setRouteMode(event.target.value as 'default' | 'source_ip')} className="rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2.5 py-2 text-xs text-[var(--ui-fg)]"><option value="default">default</option><option value="source_ip">source_ip</option></select>{routeMode === 'source_ip' ? <input value={sourceIp} onChange={(event) => setSourceIp(event.target.value)} placeholder={zh ? '来源 IP（仅配置）' : 'Source IP (configuration only)'} className="rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2.5 py-2 text-xs text-[var(--ui-fg)]" /> : <div className="rounded-lg border border-dashed border-[var(--ui-border)] px-2.5 py-2 text-[11px] text-[var(--muted-text)]">{zh ? '默认路由' : 'Default route'}</div>}<input type="number" min="1" value={priority} onChange={(event) => setPriority(event.target.value)} aria-label={zh ? '优先级' : 'Priority'} className="rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-2.5 py-2 text-xs text-[var(--ui-fg)]" /><label className="flex items-center gap-2 text-xs text-[var(--muted-text)]"><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />{zh ? '启用' : 'Enabled'}</label><div className="flex gap-2"><ActionButton icon={selectedBinding ? Save : Plus} variant="accent" size="sm" type="submit" disabled={saving || !targetId || !allowedPurposes.includes(purpose)}>{saving ? (zh ? '保存中…' : 'Saving…') : (selectedBinding ? (zh ? '保存修改' : 'Save changes') : (zh ? '添加绑定' : 'Add binding'))}</ActionButton>{selectedBinding && <ActionButton icon={X} size="sm" onClick={resetForm}>{zh ? '取消' : 'Cancel'}</ActionButton>}</div></form>}
      {bindings.length === 0 ? <div className="mt-3"><EmptyState title={zh ? '暂无探针绑定' : 'No probe bindings'} message={availableTargets.length ? (zh ? '可从已有探针目标中添加绑定。' : 'Add a binding from an existing probe target.') : (zh ? '当前租户没有可用的探针目标。' : 'No probe targets are available for this tenant.')} /></div> : <div className="mt-3 space-y-2">{bindings.map((binding) => <div key={binding.id} className="rounded-lg border border-[var(--ui-border)] p-3"><div className="flex flex-wrap items-start justify-between gap-2"><div className="min-w-0"><p className="truncate text-xs font-semibold text-[var(--heading-text)]">{binding.target_name || binding.target_id} · {binding.probe_type || '--'}</p><p className="mt-1 text-[10px] text-[var(--muted-text)]">{binding.host || '--'} · {binding.route_mode}{binding.route_mode === 'source_ip' ? ` · ${binding.source_ip || '--'}` : ''} · {binding.purpose ? purposeLabel(binding.purpose as WanProbePurpose, zh) : (zh ? '用途未设置' : 'Purpose unset')} · priority {binding.priority ?? 100}</p></div><div className="flex items-center gap-1">{canEdit && <><ActionIconButton icon={Pencil} label={zh ? '编辑绑定' : 'Edit binding'} onClick={() => editBinding(binding)} /><ActionIconButton icon={Trash2} label={zh ? '删除绑定' : 'Delete binding'} variant="danger" onClick={() => void remove(binding)} /></>}</div></div><p className="mt-2 text-[10px] text-amber-700">{zh ? '路径证据' : 'Route evidence'}：{evidenceLabel(binding.route_evidence?.evidence_status, zh)} · {binding.route_evidence?.evidence_status === 'verified' ? (zh ? '路径证据已验证；SLA仍按覆盖和策略判断' : 'Path evidence verified; SLA still depends on coverage and policy') : (zh ? '当前路径未验证或能力不足；不等同于 SLA 达标' : 'Path is unverified or capability is insufficient; this does not establish SLA')}</p></div>)}</div>}
    </>}</section>;
};
