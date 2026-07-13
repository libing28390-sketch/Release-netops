import React, { useMemo, useState } from 'react';
import { Building2, ChevronDown, GitCompareArrows, Network, RefreshCw, Server, Workflow } from 'lucide-react';

import { createSiteFoundation } from '../../../api/cmdb';
import {
  allocateNextAddress, approveReconciliationAction, requestReconciliationAction,
  reserveAddress,
} from '../../../api/ipam';
import { useCmdbLookups } from '../../../hooks/useCmdbLookups';
import { useIpamPrefixes } from '../../../hooks/useIpamPrefixes';
import { useIpamReconciliation } from '../../../hooks/useIpamReconciliation';


type Flow = 'site' | 'allocate' | 'reconcile' | 'onboard';

interface Props { language: string }

const inputClass = 'w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm outline-none focus:border-blue-400 dark:border-white/10 dark:bg-white/5';

const EnterpriseWorkflowPanel: React.FC<Props> = ({ language }) => {
  const zh = language === 'zh';
  const [expanded, setExpanded] = useState(false);
  const [flow, setFlow] = useState<Flow>('site');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const cmdb = useCmdbLookups();
  const ipam = useIpamPrefixes();
  const reconciliation = useIpamReconciliation();
  const [siteForm, setSiteForm] = useState({
    tenantId: '', tenantName: '', siteCode: '', siteName: '',
    vrfName: 'default', vlanId: '100', vlanName: 'SERVER', prefix: '',
  });
  const [allocation, setAllocation] = useState({
    prefixId: '', mode: 'next', address: '', hostname: '', purpose: '',
  });

  const flowItems = useMemo(() => [
    { id: 'site' as const, icon: Building2, zh: '站点初始化', en: 'Site setup' },
    { id: 'allocate' as const, icon: Network, zh: 'IP 分配', en: 'IP allocation' },
    { id: 'reconcile' as const, icon: GitCompareArrows, zh: '对账处置', en: 'Reconciliation' },
    { id: 'onboard' as const, icon: Server, zh: '资产投产', en: 'Asset onboarding' },
  ], []);

  const execute = async (operation: () => Promise<void>) => {
    setBusy(true); setError(''); setMessage('');
    try { await operation(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  };

  const submitSite = () => execute(async () => {
    if (!siteForm.siteCode || !siteForm.siteName || !siteForm.prefix) throw new Error(zh ? '请填写站点编码、名称和 Prefix' : 'Site code, name and prefix are required');
    const result = await createSiteFoundation({
      tenantId: siteForm.tenantId || undefined,
      tenantName: siteForm.tenantId ? undefined : siteForm.tenantName,
      siteCode: siteForm.siteCode, siteName: siteForm.siteName,
      vrfName: siteForm.vrfName, vlanId: Number(siteForm.vlanId),
      vlanName: siteForm.vlanName, prefix: siteForm.prefix,
    });
    setMessage(zh ? `初始化完成：${result.site.site_name} / ${result.prefix.prefix}` : `Initialized ${result.site.site_name} / ${result.prefix.prefix}`);
    await Promise.all([cmdb.refresh(), ipam.refresh()]);
  });

  const submitAllocation = () => execute(async () => {
    if (!allocation.prefixId) throw new Error(zh ? '请选择 Prefix' : 'Select a prefix');
    const payload = { hostname: allocation.hostname, purpose: allocation.purpose };
    const result = allocation.mode === 'reserve'
      ? await reserveAddress(allocation.prefixId, allocation.address, payload)
      : await allocateNextAddress(allocation.prefixId, payload);
    setMessage(zh ? `已分配 ${result.address}，状态 ${result.status}` : `Allocated ${result.address} (${result.status})`);
  });

  const handleFinding = (findingId: string, findingType: string) => execute(async () => {
    const actionType = findingType === 'undocumented_endpoint' ? 'register_ip'
      : findingType === 'stale_ip_address' ? 'mark_stale'
        : findingType.includes('mismatch') ? 'update_ip_metadata' : 'ignore_once';
    const action = await requestReconciliationAction(findingId, actionType);
    try {
      await approveReconciliationAction(action.id);
      setMessage(zh ? '差异已审批并写入权威数据' : 'Finding approved and applied');
    } catch {
      setMessage(zh ? `动作 ${action.id} 已提交，等待管理员审批` : `Action ${action.id} is pending administrator approval`);
    }
    await reconciliation.refresh();
  });

  return (
    <section className="mb-4 rounded-2xl border border-blue-500/15 bg-gradient-to-r from-blue-50/80 to-cyan-50/50 shadow-sm dark:from-blue-500/10 dark:to-cyan-500/5">
      <button type="button" onClick={() => setExpanded(value => !value)} className="flex w-full items-center justify-between px-5 py-4 text-left">
        <span className="flex items-center gap-3">
          <span className="rounded-xl bg-blue-600 p-2 text-white"><Workflow size={18} /></span>
          <span><span className="block text-sm font-semibold">{zh ? 'CMDB / IPAM 企业工作流' : 'CMDB / IPAM enterprise workflows'}</span><span className="text-xs text-black/45 dark:text-white/45">{zh ? '按业务流程完成初始化、分配、对账与投产' : 'Setup, allocate, reconcile and onboard through governed flows'}</span></span>
        </span>
        <ChevronDown size={18} className={`transition-transform ${expanded ? 'rotate-180' : ''}`} />
      </button>
      {expanded && (
        <div className="border-t border-blue-500/10 p-5">
          <div className="mb-5 grid grid-cols-2 gap-2 md:grid-cols-4">
            {flowItems.map(item => <button key={item.id} type="button" onClick={() => { setFlow(item.id); setError(''); setMessage(''); }} className={`flex items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-sm ${flow === item.id ? 'bg-blue-600 text-white' : 'bg-white/80 text-black/60 dark:bg-white/5 dark:text-white/60'}`}><item.icon size={16} />{zh ? item.zh : item.en}</button>)}
          </div>

          {flow === 'site' && <div className="grid gap-3 md:grid-cols-4">
            <select className={inputClass} value={siteForm.tenantId} onChange={event => setSiteForm({ ...siteForm, tenantId: event.target.value })}><option value="">{zh ? '新建租户' : 'Create tenant'}</option>{cmdb.tenants.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
            {!siteForm.tenantId && <input className={inputClass} placeholder={zh ? '租户名称' : 'Tenant name'} value={siteForm.tenantName} onChange={event => setSiteForm({ ...siteForm, tenantName: event.target.value })} />}
            <input className={inputClass} placeholder={zh ? '站点编码' : 'Site code'} value={siteForm.siteCode} onChange={event => setSiteForm({ ...siteForm, siteCode: event.target.value })} />
            <input className={inputClass} placeholder={zh ? '站点名称' : 'Site name'} value={siteForm.siteName} onChange={event => setSiteForm({ ...siteForm, siteName: event.target.value })} />
            <input className={inputClass} placeholder="VRF" value={siteForm.vrfName} onChange={event => setSiteForm({ ...siteForm, vrfName: event.target.value })} />
            <input className={inputClass} type="number" min="1" max="4094" placeholder="VLAN ID" value={siteForm.vlanId} onChange={event => setSiteForm({ ...siteForm, vlanId: event.target.value })} />
            <input className={inputClass} placeholder={zh ? 'VLAN 名称' : 'VLAN name'} value={siteForm.vlanName} onChange={event => setSiteForm({ ...siteForm, vlanName: event.target.value })} />
            <input className={inputClass} placeholder="10.10.0.0/24" value={siteForm.prefix} onChange={event => setSiteForm({ ...siteForm, prefix: event.target.value })} />
            <button type="button" disabled={busy} onClick={submitSite} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{busy ? (zh ? '执行中…' : 'Working…') : (zh ? '创建完整站点' : 'Create site foundation')}</button>
          </div>}

          {flow === 'allocate' && <div className="grid gap-3 md:grid-cols-3">
            <select className={inputClass} value={allocation.prefixId} onChange={event => setAllocation({ ...allocation, prefixId: event.target.value })}><option value="">{zh ? '选择 Prefix' : 'Select prefix'}</option>{ipam.prefixes.map(item => <option key={item.id} value={item.id}>{item.prefix || item.network} · {item.name}</option>)}</select>
            <select className={inputClass} value={allocation.mode} onChange={event => setAllocation({ ...allocation, mode: event.target.value })}><option value="next">{zh ? '自动推荐下一个地址' : 'Allocate next'}</option><option value="reserve">{zh ? '保留指定地址' : 'Reserve address'}</option></select>
            {allocation.mode === 'reserve' && <input className={inputClass} placeholder={zh ? '指定 IP 地址' : 'Address'} value={allocation.address} onChange={event => setAllocation({ ...allocation, address: event.target.value })} />}
            <input className={inputClass} placeholder="Hostname" value={allocation.hostname} onChange={event => setAllocation({ ...allocation, hostname: event.target.value })} />
            <input className={inputClass} placeholder={zh ? '用途' : 'Purpose'} value={allocation.purpose} onChange={event => setAllocation({ ...allocation, purpose: event.target.value })} />
            <button type="button" disabled={busy} onClick={submitAllocation} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{zh ? '确认并分配' : 'Allocate'}</button>
          </div>}

          {flow === 'reconcile' && <div>
            <div className="mb-3 flex items-center justify-between"><span className="text-sm text-black/55 dark:text-white/55">{zh ? `当前差异 ${reconciliation.findings.length} 条` : `${reconciliation.findings.length} findings`}</span><button type="button" disabled={busy} onClick={() => execute(async () => { await reconciliation.run(); setMessage(zh ? '对账任务已生成' : 'Reconciliation run created'); })} className="flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-xs font-medium text-white"><RefreshCw size={14} />{zh ? '重新对账' : 'Run'}</button></div>
            {reconciliation.loading ? <div className="py-6 text-center text-sm text-black/40">Loading…</div> : reconciliation.findings.length === 0 ? <div className="rounded-xl bg-white/70 py-8 text-center text-sm text-emerald-600 dark:bg-white/5">{zh ? '当前没有待处理差异' : 'No findings need action'}</div> : <div className="max-h-72 space-y-2 overflow-auto">{reconciliation.findings.map(item => <div key={item.id} className="flex items-center justify-between rounded-xl bg-white/80 p-3 text-sm dark:bg-white/5"><span><span className="font-medium">{item.finding_type}</span><span className="ml-2 text-xs text-black/40">{item.risk_level} · {item.status}</span></span><button type="button" disabled={busy || !['open', 'accepted'].includes(item.status)} onClick={() => handleFinding(item.id, item.finding_type)} className="rounded-lg border border-blue-500/20 px-3 py-1.5 text-xs text-blue-600 disabled:opacity-40">{zh ? '提交处置' : 'Submit action'}</button></div>)}</div>}
          </div>}

          {flow === 'onboard' && <div className="rounded-xl bg-white/75 p-5 dark:bg-white/5"><p className="text-sm font-medium">{zh ? '资产上线流程' : 'Asset production workflow'}</p><p className="mt-1 text-xs text-black/45 dark:text-white/45">{zh ? '暂存资产 → 凭据校验 → SSH/SNMP 连通验证 → 关联设备 → 投产。现有资产管理页面已经执行这些门禁。' : 'Staging asset → credential validation → SSH/SNMP verification → managed device link → production.'}</p><a href="/cmdb/assets" className="mt-4 inline-flex rounded-lg bg-blue-600 px-4 py-2 text-sm text-white">{zh ? '进入资产管理' : 'Open asset management'}</a></div>}

          {(message || error || cmdb.error || ipam.error || reconciliation.error) && <div className={`mt-4 rounded-lg px-3 py-2 text-sm ${error || cmdb.error || ipam.error || reconciliation.error ? 'bg-red-50 text-red-600 dark:bg-red-500/10' : 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10'}`}>{error || cmdb.error || ipam.error || reconciliation.error || message}</div>}
        </div>
      )}
    </section>
  );
};

export default EnterpriseWorkflowPanel;
