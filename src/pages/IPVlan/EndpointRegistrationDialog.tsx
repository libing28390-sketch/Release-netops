import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { X } from 'lucide-react';
import { useEscapeClose } from '../../hooks/useEscapeClose';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import type { DiscoveredEndpointRow } from './ipamDiscoveryPresentation';

interface RegistrationPrefix {
  id: string;
  prefix: string;
  name?: string;
  site_name?: string;
  vrf_name?: string;
  address_space_name?: string;
  address_space_id?: string;
}

const errorLabels: Record<string, [string, string]> = {
  observation_not_current: ['该来源已过期或已被新采集替换，请刷新后重试。', 'The source expired or was replaced. Refresh and retry.'],
  observation_version_changed: ['来源已更新，请刷新后重新登记。', 'The source changed. Refresh before registering.'],
  infrastructure_address_not_terminal: ['该地址命中设备管理 IP、接口 IP 或虚拟网关，应通过设备接口 IP 导入维护，不能按终端登记。', 'This is a device management/interface IP or virtual gateway, not a terminal. Register it through interface IP import.'],
  subnet_address_space_required: ['该网段尚未确定地址空间，请先在网段页确认 Global 或 VRF。', 'Confirm the prefix Global or VRF address space first.'],
  observation_address_space_mismatch: ['所选网段与来源地址空间不一致。', 'The prefix and source address spaces differ.'],
  ip_not_in_subnet: ['该 IP 不在所选网段内。', 'This IP is outside the selected prefix.'],
  subnet_tenant_does_not_match_source: ['所选网段与来源所属租户不一致。', 'The prefix and source tenants differ.'],
};

export async function registrationError(response: Response, zh: boolean): Promise<string> {
  if (response.status === 401) return zh ? '登录已失效，请重新登录。' : 'Your session expired. Sign in again.';
  if (response.status === 403) return zh ? '当前账号没有登记此 IP 的权限。' : 'You do not have permission to register this IP.';
  const payload = await response.json().catch(() => ({}));
  const code = typeof payload?.detail === 'string' ? payload.detail : '';
  return errorLabels[code]?.[zh ? 0 : 1]
    || (zh ? '登记失败：请刷新来源并检查网段归属、地址冲突及权限。' : 'Registration failed. Refresh the source and check prefix scope, conflicts, and permissions.');
}

export default function EndpointRegistrationDialog({ item, zh, onClose, onRegistered }: {
  item: DiscoveredEndpointRow;
  zh: boolean;
  onClose: () => void;
  onRegistered: () => void;
}) {
  const dialogRef = useRef<HTMLElement>(null);
  const [prefixes, setPrefixes] = useState<RegistrationPrefix[]>([]);
  const [prefixId, setPrefixId] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const submitting = useRef(false);
  useFocusTrap(dialogRef, true);
  useEscapeClose(!saving, onClose);
  const headers = () => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}` } : {};
  };

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    setPrefixId('');
    setConfirmed(false);
    fetch('/api/ipam/subnets?include_metrics=false', { headers: headers(), signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error(await registrationError(response, zh));
        return response.json();
      })
      .then(payload => {
        if (controller.signal.aborted) return;
        const rows: unknown[] = Array.isArray(payload) ? payload : Array.isArray(payload?.items) ? payload.items : [];
        const eligiblePrefixes = rows.flatMap(raw => {
          if (!raw || typeof raw !== 'object') return [];
          const row = raw as Record<string, unknown>;
          if (typeof row.id !== 'string' || typeof row.prefix !== 'string' || !row.address_space_id
            || row.is_active === false || row.is_active === 0 || (row.status && row.status !== 'active')
            || (item.tenant_id && row.tenant_id && row.tenant_id !== item.tenant_id)
            || (item.scope_status === 'resolved' && item.address_space_id && row.address_space_id !== item.address_space_id)
            || (item.vrf_context_status === 'explicit_global' && (row.address_space_kind !== 'global' || row.vrf_id))
            || (item.vrf_context_status === 'explicit_vrf' && item.vrf_id && row.vrf_id !== item.vrf_id)
            || (item.site_id && row.site_id && row.site_id !== item.site_id)) return [];
          return [{ id: row.id, prefix: row.prefix, name: String(row.name || ''), site_name: String(row.site_name || ''), vrf_name: String(row.vrf_name || ''), address_space_name: String(row.address_space_name || ''), address_space_id: String(row.address_space_id || '') }];
        });
        setPrefixes(eligiblePrefixes);
        const suggestedPrefixId = String(item.suggested_subnet_id || '');
        if (suggestedPrefixId && eligiblePrefixes.some(prefix => prefix.id === suggestedPrefixId)) {
          setPrefixId(suggestedPrefixId);
        }
      })
      .catch(error => { if (!controller.signal.aborted) setError(error instanceof Error ? error.message : String(error)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [item.tenant_id, item.site_id, item.scope_status, item.address_space_id, item.suggested_subnet_id, retry, zh]);

  const autoMatchedPrefix = prefixes.find(prefix => prefix.id === item.suggested_subnet_id) || null;
  const autoScopeConfirmed = Boolean(autoMatchedPrefix && item.scope_status === 'resolved' && item.address_space_id);
  const resolvedScopeWithoutPrefix = Boolean(item.scope_status === 'resolved' && item.address_space_id && !autoMatchedPrefix);
  const globalSpaceChoiceRequired = Boolean(item.vrf_context_status === 'explicit_global' && !item.address_space_id && item.scope_status !== 'resolved');

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (submitting.current || !prefixId || (!autoScopeConfirmed && !confirmed) || !item.ip || !item.observed_at) return;
    submitting.current = true;
    setSaving(true);
    setError('');
    try {
      const response = await fetch('/api/ipam/reconciliation/register', {
        method: 'POST', headers: { 'Content-Type': 'application/json', ...headers() },
        body: JSON.stringify({ observation_id: item.id, subnet_id: prefixId, expected_observed_at: item.observed_at, confirmed_scope: true }),
      });
      if (!response.ok) { setError(await registrationError(response, zh)); return; }
      onRegistered();
    } catch {
      setError(zh ? '网络错误，登记未确认完成，请刷新台账后重试。' : 'Network error. Refresh the ledger before retrying.');
    } finally {
      submitting.current = false;
      setSaving(false);
    }
  };

  return <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/45 p-3">
    <section ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="endpoint-registration-title" className="w-full max-w-lg overflow-hidden rounded-2xl border border-[var(--ui-border)] bg-[var(--ui-surface)] shadow-2xl">
      <form onSubmit={submit}>
        <header className="flex justify-between border-b border-[var(--ui-border)] px-5 py-4">
          <h2 id="endpoint-registration-title" className="font-bold">{zh ? '登记到 IPAM' : 'Register in IPAM'}</h2>
          <button type="button" disabled={saving} onClick={onClose} aria-label={zh ? '关闭登记' : 'Close registration'}><X size={16} /></button>
        </header>
        <div className="space-y-4 p-5 text-xs">
          <div><strong className="font-mono">{item.ip}</strong> · {item.mac} · {item.site_name}</div>
          <p>{zh ? 'ARP / ND 提供 IP 与 MAC 关系；FDB 提供 MAC 所在端口。登记后可到 IP 地址页补充用途、分配设备与接口。采集交换机不会被当作此 IP 的分配设备。' : 'ARP / ND provides IP-to-MAC mappings; FDB provides MAC locations. After registration, edit the IP record to assign its purpose, device, and interface.'}</p>
          {autoScopeConfirmed && autoMatchedPrefix ? <div role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-emerald-900">
            <div className="font-semibold">{zh ? '已按采集到的地址空间自动匹配' : 'Automatically matched from the collected address space'}</div>
            <div className="mt-1">{autoMatchedPrefix.prefix} · {autoMatchedPrefix.address_space_name || (zh ? '全局（无 VRF）' : 'Global (no VRF)')}</div>
            <p className="mt-1 text-[var(--ui-text-body)]">{zh ? 'IP 将登记到这个网段和地址空间，无需手动绑定。' : 'The IP will be registered in this prefix and address space; no manual binding is needed.'}</p>
          </div> : resolvedScopeWithoutPrefix ? <div role="status" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-900">
            <div className="font-semibold">{zh ? '地址空间已确认，但没有唯一匹配的网段' : 'Address space is confirmed, but no unique prefix matched'}</div>
            <p className="mt-1">{zh ? `当前空间：${item.address_space_name || (item.address_space_kind === 'global' ? '全局（无 VRF）' : item.vrf_name || '已确认空间')}。请先创建或核对包含此 IP 的网段。` : `Current space: ${item.address_space_name || (item.address_space_kind === 'global' ? 'Global (no VRF)' : item.vrf_name || 'Confirmed space')}. Create or review a prefix containing this IP first.`}</p>
            <Link className="mt-2 inline-block text-cyan-700 underline" to="/ipam/prefixes">{zh ? '前往网段管理' : 'Open prefix management'}</Link>
          </div> : <label className="block space-y-2"><span>{zh ? '归属网段' : 'Prefix'}</span>
            <select aria-label={zh ? '归属网段' : 'Prefix'} value={prefixId} disabled={loading || saving} onChange={event => { setPrefixId(event.target.value); setConfirmed(false); }} className="w-full rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 py-2">
              <option value="">{loading ? (zh ? '正在加载…' : 'Loading…') : globalSpaceChoiceRequired
                ? (zh ? '来源已确认无 VRF，但存在多个全局空间；请选择能包含此 IP 的网段' : 'Global context is known but multiple Global spaces exist; select the prefix containing this IP.')
                : (zh ? '来源范围未明确，请选择已确认地址空间的网段' : 'Source scope is unresolved. Select a prefix with a confirmed address space.')}</option>
              {prefixes.map(prefix => <option key={prefix.id} value={prefix.id}>{prefix.prefix} · {prefix.name} · {prefix.site_name} · {prefix.address_space_name || prefix.vrf_name || (zh ? '已确认地址空间' : 'Confirmed address space')}</option>)}
            </select>
          </label>}
          {!loading && !prefixes.length && !resolvedScopeWithoutPrefix && <p>{zh ? '没有可登记的网段，请先' : 'No eligible prefixes. First '}<Link className="text-cyan-700 underline" to="/ipam/prefixes">{zh ? '创建网段并确认地址空间' : 'create a prefix and confirm its address space'}</Link>。</p>}
          {!autoScopeConfirmed && !resolvedScopeWithoutPrefix && <label className="flex items-start gap-2"><input type="checkbox" checked={confirmed} disabled={saving} onChange={event => setConfirmed(event.target.checked)} /><span>{zh ? '来源范围未能自动确认；我确认此 IP 属于所选网段及其 Global / VRF 地址空间。' : 'The source scope could not be confirmed automatically. I confirm this IP belongs to the selected prefix and Global / VRF address space.'}</span></label>}
          {error && <div role="alert" className="rounded-lg bg-rose-50 p-3 text-rose-700">{error}{!prefixes.length && <button type="button" className="ml-2 underline" onClick={() => setRetry(value => value + 1)}>{zh ? '重试' : 'Retry'}</button>}</div>}
        </div>
        <footer className="flex justify-end gap-2 border-t border-[var(--ui-border)] px-5 py-3">
          <button type="button" disabled={saving} onClick={onClose} className="rounded-lg border px-3 py-2 text-xs">{zh ? '取消' : 'Cancel'}</button>
          <button type="submit" disabled={loading || saving || !prefixId || resolvedScopeWithoutPrefix || (!autoScopeConfirmed && !confirmed)} className="rounded-lg bg-cyan-600 px-3 py-2 text-xs text-white disabled:opacity-50">{saving ? (zh ? '登记中…' : 'Registering…') : (zh ? '确认登记' : 'Confirm registration')}</button>
        </footer>
      </form>
    </section>
  </div>;
}
