import React, { useCallback, useEffect, useState } from 'react';
import { ArrowUpRight, Globe, Layers, Network, Plus, RefreshCw, ShieldCheck, Trash2 } from 'lucide-react';
import PageHero from '../../components/PageHero';

interface Props {
  language: string;
  t?: (key: string) => string;
}

interface SiteOption {
  id: string;
  site_name?: string;
  name?: string;
}

interface VRFOption {
  id: string;
  vrf_name?: string;
  name?: string;
}

interface VLANGroupItem {
  id: string;
  name: string;
  scope_type: string;
  scope_id: string;
  min_vid: number;
  max_vid: number;
  description: string;
  vlan_count?: number;
}

interface RouteTargetItem {
  id: string;
  name: string;
  description: string;
}

interface VRFRouteTargetsResponse {
  vrf_id: string;
  vrf_name: string;
  import_targets: RouteTargetItem[];
  export_targets: RouteTargetItem[];
}

interface RIRItem {
  id: string;
  name: string;
  is_private: boolean;
  description: string;
  aggregate_count?: number;
  asn_count?: number;
}

interface AggregateItem {
  id: string;
  prefix: string;
  ip_version: number;
  rir_id: string;
  rir_name: string;
  date_added: string;
  description: string;
  child_prefix_count?: number;
}

interface ASNItem {
  id: string;
  asn: number;
  rir_id: string;
  rir_name: string;
  site_id: string | null;
  site_name?: string | null;
  description: string;
}

type SubTab = 'vlan-groups' | 'route-targets' | 'rir-aggregate-asn';

const authHeaders = (): Record<string, string> => {
  const token = localStorage.getItem('netops_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
};

const unwrapList = <T,>(payload: any): T[] => {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.items)) return payload.items;
  if (Array.isArray(payload?.data?.items)) return payload.data.items;
  if (Array.isArray(payload?.data)) return payload.data;
  return [];
};

const IPAMNativeModelsTab: React.FC<Props> = ({ language }) => {
  const zh = language === 'zh';
  const [subTab, setSubTab] = useState<SubTab>('vlan-groups');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  // Reference lookups
  const [sites, setSites] = useState<SiteOption[]>([]);
  const [vrfs, setVrfs] = useState<VRFOption[]>([]);

  // VLAN Groups state
  const [vlanGroups, setVlanGroups] = useState<VLANGroupItem[]>([]);
  const [vgForm, setVgForm] = useState({
    name: '',
    scope_type: '',
    scope_id: '',
    min_vid: '1',
    max_vid: '4094',
    description: '',
  });

  // Route Targets state
  const [routeTargets, setRouteTargets] = useState<RouteTargetItem[]>([]);
  const [rtForm, setRtForm] = useState({ name: '', description: '' });
  const [selectedVrfId, setSelectedVrfId] = useState('');
  const [vrfImportIds, setVrfImportIds] = useState<string[]>([]);
  const [vrfExportIds, setVrfExportIds] = useState<string[]>([]);
  const [savingVrfRts, setSavingVrfRts] = useState(false);

  // RIR / Aggregate / ASN state
  const [rirs, setRirs] = useState<RIRItem[]>([]);
  const [aggregates, setAggregates] = useState<AggregateItem[]>([]);
  const [asns, setAsns] = useState<ASNItem[]>([]);
  const [rirForm, setRirForm] = useState({ name: '', is_private: false, description: '' });
  const [aggForm, setAggForm] = useState({ prefix: '', rir_id: '', date_added: '', description: '' });
  const [asnForm, setAsnForm] = useState({ asn: '', rir_id: '', site_id: '', description: '' });

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const hdrs = authHeaders();
      const [sitesRes, vrfsRes, vgRes, rtRes, rirRes, aggRes, asnRes] = await Promise.all([
        fetch('/api/cmdb/sites', { headers: hdrs }),
        fetch('/api/cmdb/vrfs', { headers: hdrs }),
        fetch('/api/ipam/vlan-groups', { headers: hdrs }),
        fetch('/api/ipam/route-targets', { headers: hdrs }),
        fetch('/api/ipam/rirs', { headers: hdrs }),
        fetch('/api/ipam/aggregates', { headers: hdrs }),
        fetch('/api/ipam/asns', { headers: hdrs }),
      ]);
      if (sitesRes.ok) setSites(unwrapList<SiteOption>(await sitesRes.json()));
      if (vrfsRes.ok) setVrfs(unwrapList<VRFOption>(await vrfsRes.json()));
      if (vgRes.ok) setVlanGroups(unwrapList<VLANGroupItem>(await vgRes.json()));
      if (rtRes.ok) setRouteTargets(unwrapList<RouteTargetItem>(await rtRes.json()));
      if (rirRes.ok) setRirs(unwrapList<RIRItem>(await rirRes.json()));
      if (aggRes.ok) setAggregates(unwrapList<AggregateItem>(await aggRes.json()));
      if (asnRes.ok) setAsns(unwrapList<ASNItem>(await asnRes.json()));
    } catch (err: any) {
      setError(err?.message || (zh ? '加载扩展台账数据失败' : 'Failed to load IPAM resource models'));
    } finally {
      setLoading(false);
    }
  }, [zh]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const loadVrfRouteTargets = useCallback(async (vrfId: string) => {
    if (!vrfId) {
      setVrfImportIds([]);
      setVrfExportIds([]);
      return;
    }
    try {
      const res = await fetch(`/api/ipam/vrfs/${encodeURIComponent(vrfId)}/route-targets`, { headers: authHeaders() });
      if (!res.ok) return;
      const data: VRFRouteTargetsResponse = await res.json();
      setVrfImportIds((data.import_targets || []).map((t) => t.id));
      setVrfExportIds((data.export_targets || []).map((t) => t.id));
    } catch {
      // ignore transient error
    }
  }, []);

  useEffect(() => {
    void loadVrfRouteTargets(selectedVrfId);
  }, [selectedVrfId, loadVrfRouteTargets]);

  const siteLabel = (siteId: string | null | undefined) => {
    if (!siteId) return zh ? '全局' : 'Global';
    const match = sites.find((s) => s.id === siteId);
    return match?.site_name || match?.name || siteId;
  };

  const handleCreateVlanGroup = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setNotice('');
    try {
      const res = await fetch('/api/ipam/vlan-groups', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          name: vgForm.name.trim(),
          scope_type: vgForm.scope_id ? 'site' : '',
          scope_id: vgForm.scope_id,
          min_vid: Number(vgForm.min_vid) || 1,
          max_vid: Number(vgForm.max_vid) || 4094,
          description: vgForm.description.trim(),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      setVgForm({ name: '', scope_type: '', scope_id: '', min_vid: '1', max_vid: '4094', description: '' });
      setNotice(zh ? `已创建 VLAN 分组 ${data.name}` : `Created VLAN group ${data.name}`);
      await loadAll();
    } catch (err: any) {
      setError(err?.message || (zh ? '创建 VLAN 分组失败' : 'Failed to create VLAN group'));
    }
  };

  const handleDeleteVlanGroup = async (id: string) => {
    setError('');
    setNotice('');
    const res = await fetch(`/api/ipam/vlan-groups/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      headers: authHeaders(),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      setError(data.detail || (zh ? '删除 VLAN 分组失败' : 'Failed to delete VLAN group'));
      return;
    }
    await loadAll();
  };

  const handleCreateRouteTarget = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setNotice('');
    try {
      const res = await fetch('/api/ipam/route-targets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ name: rtForm.name.trim(), description: rtForm.description.trim() }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      setRtForm({ name: '', description: '' });
      setNotice(zh ? `已创建 Route Target ${data.name}` : `Created Route Target ${data.name}`);
      await loadAll();
    } catch (err: any) {
      setError(err?.message || (zh ? '创建 Route Target 失败' : 'Failed to create Route Target'));
    }
  };

  const handleDeleteRouteTarget = async (id: string) => {
    setError('');
    const res = await fetch(`/api/ipam/route-targets/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      headers: authHeaders(),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      setError(data.detail || (zh ? '删除 Route Target 失败' : 'Failed to delete Route Target'));
      return;
    }
    await loadAll();
    if (selectedVrfId) await loadVrfRouteTargets(selectedVrfId);
  };

  const handleSaveVrfRouteTargets = async () => {
    if (!selectedVrfId) return;
    setSavingVrfRts(true);
    setError('');
    setNotice('');
    try {
      const res = await fetch(`/api/ipam/vrfs/${encodeURIComponent(selectedVrfId)}/route-targets`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ import_target_ids: vrfImportIds, export_target_ids: vrfExportIds }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      setNotice(zh ? 'VRF Route Target 策略已保存' : 'VRF Route Target policy saved');
    } catch (err: any) {
      setError(err?.message || (zh ? '保存 VRF 策略失败' : 'Failed to save VRF Route Targets'));
    } finally {
      setSavingVrfRts(false);
    }
  };

  const handleCreateRir = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setNotice('');
    try {
      const res = await fetch('/api/ipam/rirs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          name: rirForm.name.trim(),
          is_private: rirForm.is_private,
          description: rirForm.description.trim(),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      setRirForm({ name: '', is_private: false, description: '' });
      setNotice(zh ? `已创建 RIR ${data.name}` : `Created RIR ${data.name}`);
      await loadAll();
    } catch (err: any) {
      setError(err?.message || (zh ? '创建 RIR 失败' : 'Failed to create RIR'));
    }
  };

  const handleDeleteRir = async (id: string) => {
    setError('');
    const res = await fetch(`/api/ipam/rirs/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      headers: authHeaders(),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      setError(data.detail || (zh ? '删除 RIR 失败' : 'Failed to delete RIR'));
      return;
    }
    await loadAll();
  };

  const handleCreateAggregate = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setNotice('');
    try {
      const res = await fetch('/api/ipam/aggregates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          prefix: aggForm.prefix.trim(),
          rir_id: aggForm.rir_id,
          date_added: aggForm.date_added.trim(),
          description: aggForm.description.trim(),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      setAggForm({ prefix: '', rir_id: aggForm.rir_id, date_added: '', description: '' });
      setNotice(zh ? `已创建顶层地址块 ${data.prefix}` : `Created Aggregate ${data.prefix}`);
      await loadAll();
    } catch (err: any) {
      setError(err?.message || (zh ? '创建 Aggregate 失败' : 'Failed to create Aggregate'));
    }
  };

  const handleDeleteAggregate = async (id: string) => {
    setError('');
    const res = await fetch(`/api/ipam/aggregates/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      headers: authHeaders(),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      setError(data.detail || (zh ? '删除 Aggregate 失败' : 'Failed to delete Aggregate'));
      return;
    }
    await loadAll();
  };

  const handleCreateAsn = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setNotice('');
    try {
      const res = await fetch('/api/ipam/asns', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          asn: Number(asnForm.asn),
          rir_id: asnForm.rir_id,
          site_id: asnForm.site_id || null,
          description: asnForm.description.trim(),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      setAsnForm({ asn: '', rir_id: asnForm.rir_id, site_id: '', description: '' });
      setNotice(zh ? `已登记 AS${data.asn}` : `Created AS${data.asn}`);
      await loadAll();
    } catch (err: any) {
      setError(err?.message || (zh ? '登记 ASN 失败' : 'Failed to create ASN'));
    }
  };

  const handleDeleteAsn = async (id: string) => {
    setError('');
    const res = await fetch(`/api/ipam/asns/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      headers: authHeaders(),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      setError(data.detail || (zh ? '删除 ASN 失败' : 'Failed to delete ASN'));
      return;
    }
    await loadAll();
  };

  const toggleId = (list: string[], id: string, setter: (v: string[]) => void) => {
    setter(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
  };

  const inputCls =
    'rounded-xl border border-slate-200/90 dark:border-zinc-700 bg-slate-50/70 dark:bg-zinc-800/80 px-3 py-2 text-xs text-slate-800 dark:text-zinc-100 placeholder:text-slate-400 outline-none transition focus:border-cyan-500 focus:bg-white dark:focus:bg-zinc-800';
  const selectCls =
    'rounded-xl border border-slate-200/90 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-3 py-2 text-xs font-medium text-slate-700 dark:text-zinc-200 outline-none transition focus:border-cyan-500 cursor-pointer';
  const primaryBtnCls =
    'inline-flex items-center justify-center gap-1.5 rounded-xl bg-cyan-600 px-3.5 py-2 text-xs font-semibold text-white shadow-2xs transition hover:bg-cyan-700 disabled:opacity-50 cursor-pointer';
  const cardCls =
    'rounded-2xl border border-slate-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900/95 shadow-2xs';

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 overflow-auto bg-slate-50/60 dark:bg-zinc-950 p-5 md:p-6">
      <PageHero
        icon={Layers}
        title={zh ? '扩展 IPAM 台账' : 'Extended IPAM Models'}
        subtitle={zh ? '管理 VLAN 分组（作用域与 VID 区间）、BGP/VRF Route Target 策略以及 RIR / Aggregate / ASN 顶层地址归属。' : 'Manage VLAN Groups, VRF Route Target import/export policies, and RIR / Aggregate / ASN ownership.'}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <a
              href="/cmdb/vlans"
              className="inline-flex items-center gap-1 rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3 py-1.5 text-xs font-semibold text-slate-600 dark:text-zinc-300 shadow-2xs hover:border-cyan-300 hover:text-cyan-700 dark:hover:text-cyan-300 transition-colors"
            >
              <span>{zh ? 'CMDB VLAN 明细' : 'CMDB VLANs'}</span>
              <ArrowUpRight size={13} />
            </a>
            <a
              href="/cmdb/vrfs"
              className="inline-flex items-center gap-1 rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3 py-1.5 text-xs font-semibold text-slate-600 dark:text-zinc-300 shadow-2xs hover:border-cyan-300 hover:text-cyan-700 dark:hover:text-cyan-300 transition-colors"
            >
              <span>{zh ? 'CMDB VRF 主体' : 'CMDB VRFs'}</span>
              <ArrowUpRight size={13} />
            </a>
            <button
              type="button"
              onClick={() => void loadAll()}
              disabled={loading}
              className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3 py-1.5 text-xs font-semibold text-slate-700 dark:text-zinc-200 shadow-2xs hover:border-cyan-300 transition-colors cursor-pointer"
            >
              <RefreshCw size={13} className={loading ? 'animate-spin text-cyan-600' : ''} />
              {zh ? '刷新' : 'Refresh'}
            </button>
          </div>
        }
      />

      {/* 4-Card KPI Summary Strip */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          {
            label: zh ? 'VLAN 分组' : 'VLAN Groups',
            value: vlanGroups.length,
            sub: zh ? 'VID 区间容器与作用域' : 'VID range scopes',
            icon: Layers,
            tone: 'bg-cyan-50 text-cyan-600 dark:bg-cyan-950/50 dark:text-cyan-400',
            target: 'vlan-groups' as SubTab,
          },
          {
            label: 'Route Targets',
            value: routeTargets.length,
            sub: zh ? 'BGP / MPLS VRF 策略' : 'VRF import/export policy',
            icon: Network,
            tone: 'bg-indigo-50 text-indigo-600 dark:bg-indigo-950/50 dark:text-indigo-400',
            target: 'route-targets' as SubTab,
          },
          {
            label: zh ? 'RIR / 顶层地址块' : 'RIR / Aggregates',
            value: `${rirs.length} / ${aggregates.length}`,
            sub: zh ? '公私网注册机构与聚合块' : 'Registries & root blocks',
            icon: Globe,
            tone: 'bg-emerald-50 text-emerald-600 dark:bg-emerald-950/50 dark:text-emerald-400',
            target: 'rir-aggregate-asn' as SubTab,
          },
          {
            label: zh ? '自治系统号 (ASN)' : 'ASNs',
            value: asns.length,
            sub: zh ? '公网 / 私有 BGP AS 号' : 'Registered BGP ASNs',
            icon: ShieldCheck,
            tone: 'bg-amber-50 text-amber-600 dark:bg-amber-950/50 dark:text-amber-400',
            target: 'rir-aggregate-asn' as SubTab,
          },
        ].map((card) => {
          const Icon = card.icon;
          const active = subTab === card.target;
          return (
            <button
              key={card.label}
              type="button"
              onClick={() => setSubTab(card.target)}
              className={`flex items-center justify-between gap-3 rounded-2xl border p-4 text-left transition-all cursor-pointer ${
                active
                  ? 'border-cyan-300/80 dark:border-cyan-800 bg-white dark:bg-zinc-900 shadow-xs ring-1 ring-cyan-500/15'
                  : 'border-slate-200/80 dark:border-zinc-800 bg-white/90 dark:bg-zinc-900/80 hover:border-slate-300 dark:hover:border-zinc-700'
              }`}
            >
              <div className="min-w-0">
                <p className="text-[11px] font-semibold text-slate-500 dark:text-zinc-400">{card.label}</p>
                <p className="mt-1 font-mono text-xl font-extrabold tracking-tight text-slate-900 dark:text-zinc-100">{card.value}</p>
                <p className="mt-0.5 truncate text-[10px] text-slate-400 dark:text-zinc-500">{card.sub}</p>
              </div>
              <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${card.tone}`}>
                <Icon size={18} />
              </div>
            </button>
          );
        })}
      </div>

      {/* Segmented Sub-Tab Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex flex-wrap items-center gap-1 rounded-2xl border border-slate-200/80 dark:border-zinc-800 bg-slate-100/80 dark:bg-zinc-900 p-1" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={subTab === 'vlan-groups'}
            onClick={() => setSubTab('vlan-groups')}
            className={`inline-flex items-center gap-1.5 rounded-xl px-3.5 py-2 text-xs font-semibold transition-all cursor-pointer ${
              subTab === 'vlan-groups'
                ? 'bg-white dark:bg-zinc-800 text-cyan-700 dark:text-cyan-300 shadow-xs'
                : 'text-slate-600 dark:text-zinc-400 hover:text-slate-900 dark:hover:text-zinc-100'
            }`}
          >
            <Layers size={13} />
            {zh ? `VLAN 分组 (${vlanGroups.length})` : `VLAN Groups (${vlanGroups.length})`}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={subTab === 'route-targets'}
            onClick={() => setSubTab('route-targets')}
            className={`inline-flex items-center gap-1.5 rounded-xl px-3.5 py-2 text-xs font-semibold transition-all cursor-pointer ${
              subTab === 'route-targets'
                ? 'bg-white dark:bg-zinc-800 text-cyan-700 dark:text-cyan-300 shadow-xs'
                : 'text-slate-600 dark:text-zinc-400 hover:text-slate-900 dark:hover:text-zinc-100'
            }`}
          >
            <Network size={13} />
            {zh ? `Route Targets (${routeTargets.length})` : `Route Targets (${routeTargets.length})`}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={subTab === 'rir-aggregate-asn'}
            onClick={() => setSubTab('rir-aggregate-asn')}
            className={`inline-flex items-center gap-1.5 rounded-xl px-3.5 py-2 text-xs font-semibold transition-all cursor-pointer ${
              subTab === 'rir-aggregate-asn'
                ? 'bg-white dark:bg-zinc-800 text-cyan-700 dark:text-cyan-300 shadow-xs'
                : 'text-slate-600 dark:text-zinc-400 hover:text-slate-900 dark:hover:text-zinc-100'
            }`}
          >
            <Globe size={13} />
            {zh ? `RIR / Aggregate / ASN (${rirs.length}/${aggregates.length}/${asns.length})` : `RIR / Aggregate / ASN (${rirs.length}/${aggregates.length}/${asns.length})`}
          </button>
        </div>
        <p className="text-[11px] text-slate-400 dark:text-zinc-500">
          {zh ? '注：具体 VLAN / VRF 实体在 CMDB 基础数据中维护，本页负责上层分组、RT 策略与顶层地址归属。' : 'Note: Concrete VLAN/VRF records live in CMDB; this page manages groups, RT policies, and top-level address ownership.'}
        </p>
      </div>

      {error && (
        <div role="alert" className="rounded-xl border border-rose-200 dark:border-rose-900/60 bg-rose-50 dark:bg-rose-950/40 px-4 py-2.5 text-xs font-medium text-rose-800 dark:text-rose-300">
          {error}
        </div>
      )}
      {notice && (
        <div className="rounded-xl border border-emerald-200 dark:border-emerald-900/60 bg-emerald-50 dark:bg-emerald-950/40 px-4 py-2.5 text-xs font-medium text-emerald-800 dark:text-emerald-300">
          {notice}
        </div>
      )}

      {subTab === 'vlan-groups' && (
        <div className="space-y-4">
          <form onSubmit={handleCreateVlanGroup} className={`grid grid-cols-1 gap-3 p-4 md:grid-cols-6 ${cardCls}`}>
            <input
              required
              placeholder={zh ? '分组名称（如 DC1-Prod）' : 'Group name'}
              value={vgForm.name}
              onChange={(e) => setVgForm((p) => ({ ...p, name: e.target.value }))}
              className={`${inputCls} md:col-span-2`}
            />
            <select
              aria-label={zh ? '作用域站点' : 'Scope site'}
              value={vgForm.scope_id}
              onChange={(e) => setVgForm((p) => ({ ...p, scope_id: e.target.value }))}
              className={selectCls}
            >
              <option value="">{zh ? '全局（不限站点）' : 'Global'}</option>
              {sites.map((s) => (
                <option key={s.id} value={s.id}>{s.site_name || s.name || s.id}</option>
              ))}
            </select>
            <div className="flex items-center gap-1.5">
              <input
                type="number"
                min={1}
                max={4094}
                aria-label={zh ? '最小 VID' : 'Min VID'}
                value={vgForm.min_vid}
                onChange={(e) => setVgForm((p) => ({ ...p, min_vid: e.target.value }))}
                className={`w-full font-mono ${inputCls}`}
              />
              <span className="text-xs text-slate-400">-</span>
              <input
                type="number"
                min={1}
                max={4094}
                aria-label={zh ? '最大 VID' : 'Max VID'}
                value={vgForm.max_vid}
                onChange={(e) => setVgForm((p) => ({ ...p, max_vid: e.target.value }))}
                className={`w-full font-mono ${inputCls}`}
              />
            </div>
            <input
              placeholder={zh ? '备注' : 'Description'}
              value={vgForm.description}
              onChange={(e) => setVgForm((p) => ({ ...p, description: e.target.value }))}
              className={inputCls}
            />
            <button type="submit" className={primaryBtnCls}>
              <Plus size={13} />
              {zh ? '新增分组' : 'Add Group'}
            </button>
          </form>

          <div className={`overflow-auto ${cardCls}`}>
            <table className="w-full text-left text-xs">
              <thead className="border-b border-slate-200/80 dark:border-zinc-800 bg-slate-50/80 dark:bg-zinc-800/50 text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-zinc-400">
                <tr>
                  <th className="px-4 py-3">{zh ? '名称' : 'Name'}</th>
                  <th className="px-4 py-3">{zh ? '作用域' : 'Scope'}</th>
                  <th className="px-4 py-3">{zh ? 'VID 范围' : 'VID Range'}</th>
                  <th className="px-4 py-3">{zh ? '关联 VLAN 数' : 'VLANs'}</th>
                  <th className="px-4 py-3">{zh ? '说明' : 'Description'}</th>
                  <th className="px-4 py-3 text-right">{zh ? '操作' : 'Actions'}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-zinc-800/80">
                {vlanGroups.map((g) => (
                  <tr key={g.id} className="transition-colors hover:bg-slate-50/80 dark:hover:bg-zinc-800/40">
                    <td className="px-4 py-3 font-semibold text-slate-900 dark:text-zinc-100">{g.name}</td>
                    <td className="px-4 py-3">
                      <span className="inline-flex rounded-lg bg-slate-100 dark:bg-zinc-800 px-2 py-0.5 text-[11px] font-medium text-slate-600 dark:text-zinc-300">
                        {g.scope_type === 'site' ? siteLabel(g.scope_id) : (zh ? '全局' : 'Global')}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex rounded-lg border border-cyan-200/80 dark:border-cyan-900/60 bg-cyan-50/70 dark:bg-cyan-950/40 px-2 py-0.5 font-mono text-[11px] font-semibold text-cyan-700 dark:text-cyan-300">
                        {g.min_vid} - {g.max_vid}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono font-semibold text-slate-700 dark:text-zinc-300">{g.vlan_count ?? 0}</td>
                    <td className="px-4 py-3 text-slate-500 dark:text-zinc-400">{g.description || '—'}</td>
                    <td className="px-4 py-3 text-right">
                      <button
                        type="button"
                        onClick={() => void handleDeleteVlanGroup(g.id)}
                        className="inline-flex items-center gap-1 rounded-lg p-1.5 text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-950/40 hover:text-rose-700 transition-colors cursor-pointer"
                        aria-label={zh ? `删除分组 ${g.name}` : `Delete ${g.name}`}
                      >
                        <Trash2 size={13} />
                      </button>
                    </td>
                  </tr>
                ))}
                {!vlanGroups.length && (
                  <tr>
                    <td colSpan={6} className="px-4 py-12 text-center text-slate-400 dark:text-zinc-500">
                      <Layers size={24} className="mx-auto mb-2 opacity-40" />
                      <p className="font-medium">{zh ? '暂无 VLAN 分组' : 'No VLAN groups yet'}</p>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {subTab === 'route-targets' && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className={`space-y-3.5 p-5 ${cardCls}`}>
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-900 dark:text-zinc-100">{zh ? 'Route Target 定义' : 'Route Targets'}</h3>
              <span className="rounded-full bg-indigo-50 dark:bg-indigo-950/50 px-2.5 py-0.5 font-mono text-[11px] font-semibold text-indigo-600 dark:text-indigo-300">
                {routeTargets.length}
              </span>
            </div>
            <form onSubmit={handleCreateRouteTarget} className="flex flex-wrap gap-2">
              <input
                required
                placeholder={zh ? '如 65001:100' : 'e.g. 65001:100'}
                value={rtForm.name}
                onChange={(e) => setRtForm((p) => ({ ...p, name: e.target.value }))}
                className={`min-w-[140px] flex-1 font-mono ${inputCls}`}
              />
              <input
                placeholder={zh ? '用途说明' : 'Description'}
                value={rtForm.description}
                onChange={(e) => setRtForm((p) => ({ ...p, description: e.target.value }))}
                className={`min-w-[140px] flex-1 ${inputCls}`}
              />
              <button type="submit" className={primaryBtnCls}>
                <Plus size={13} />
                {zh ? '新增 RT' : 'Add RT'}
              </button>
            </form>
            <div className="overflow-hidden rounded-xl border border-slate-100 dark:border-zinc-800">
              <table className="w-full text-left text-xs">
                <thead className="border-b border-slate-200/80 dark:border-zinc-800 bg-slate-50/80 dark:bg-zinc-800/50 text-[11px] font-semibold text-slate-500 dark:text-zinc-400">
                  <tr>
                    <th className="px-3.5 py-2.5">Route Target</th>
                    <th className="px-3.5 py-2.5">{zh ? '说明' : 'Description'}</th>
                    <th className="px-3.5 py-2.5 text-right">{zh ? '操作' : 'Actions'}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-zinc-800/80">
                  {routeTargets.map((rt) => (
                    <tr key={rt.id} className="transition-colors hover:bg-slate-50/80 dark:hover:bg-zinc-800/40">
                      <td className="px-3.5 py-2.5">
                        <span className="inline-flex rounded-lg border border-indigo-200/80 dark:border-indigo-900/60 bg-indigo-50/70 dark:bg-indigo-950/40 px-2 py-0.5 font-mono font-semibold text-indigo-700 dark:text-indigo-300">
                          {rt.name}
                        </span>
                      </td>
                      <td className="px-3.5 py-2.5 text-slate-500 dark:text-zinc-400">{rt.description || '—'}</td>
                      <td className="px-3.5 py-2.5 text-right">
                        <button
                          type="button"
                          onClick={() => void handleDeleteRouteTarget(rt.id)}
                          className="rounded-lg p-1.5 text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-950/40 transition-colors cursor-pointer"
                          aria-label={zh ? `删除 ${rt.name}` : `Delete ${rt.name}`}
                        >
                          <Trash2 size={13} />
                        </button>
                      </td>
                    </tr>
                  ))}
                  {!routeTargets.length && (
                    <tr>
                      <td colSpan={3} className="px-3.5 py-8 text-center text-slate-400 dark:text-zinc-500">
                        {zh ? '暂无 Route Target' : 'No Route Targets yet'}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className={`space-y-3.5 p-5 ${cardCls}`}>
            <h3 className="text-sm font-bold text-slate-900 dark:text-zinc-100">{zh ? 'VRF 导入 / 导出策略绑定' : 'VRF Import / Export Binding'}</h3>
            <select
              aria-label={zh ? '选择 VRF' : 'Select VRF'}
              value={selectedVrfId}
              onChange={(e) => setSelectedVrfId(e.target.value)}
              className={`w-full ${selectCls}`}
            >
              <option value="">{zh ? '请选择 VRF 以配置导入/导出 RT...' : 'Select a VRF to configure Route Targets...'}</option>
              {vrfs.map((v) => (
                <option key={v.id} value={v.id}>{v.vrf_name || v.name || v.id}</option>
              ))}
            </select>
            {selectedVrfId ? (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-xl border border-slate-200/80 dark:border-zinc-800 bg-slate-50/60 dark:bg-zinc-800/40 p-3.5">
                    <div className="mb-2.5 text-xs font-bold text-emerald-700 dark:text-emerald-400">Import Targets</div>
                    <div className="space-y-2">
                      {routeTargets.map((rt) => (
                        <label key={`imp-${rt.id}`} className="flex items-center gap-2 text-xs font-mono text-slate-700 dark:text-zinc-200 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={vrfImportIds.includes(rt.id)}
                            onChange={() => toggleId(vrfImportIds, rt.id, setVrfImportIds)}
                            className="rounded border-slate-300 text-cyan-600 focus:ring-cyan-500"
                          />
                          <span>{rt.name}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                  <div className="rounded-xl border border-slate-200/80 dark:border-zinc-800 bg-slate-50/60 dark:bg-zinc-800/40 p-3.5">
                    <div className="mb-2.5 text-xs font-bold text-cyan-700 dark:text-cyan-400">Export Targets</div>
                    <div className="space-y-2">
                      {routeTargets.map((rt) => (
                        <label key={`exp-${rt.id}`} className="flex items-center gap-2 text-xs font-mono text-slate-700 dark:text-zinc-200 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={vrfExportIds.includes(rt.id)}
                            onChange={() => toggleId(vrfExportIds, rt.id, setVrfExportIds)}
                            className="rounded border-slate-300 text-cyan-600 focus:ring-cyan-500"
                          />
                          <span>{rt.name}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  disabled={savingVrfRts}
                  onClick={() => void handleSaveVrfRouteTargets()}
                  className={primaryBtnCls}
                >
                  {savingVrfRts ? (zh ? '保存中...' : 'Saving...') : (zh ? '保存 VRF 策略' : 'Save VRF Policy')}
                </button>
              </div>
            ) : (
              <div className="rounded-xl border border-dashed border-slate-200 dark:border-zinc-800 px-4 py-8 text-center text-xs text-slate-400 dark:text-zinc-500">
                {zh ? '选择一个 VRF 后，可勾选其 BGP Import / Export Route Targets' : 'Select a VRF to assign BGP Import / Export Route Targets'}
              </div>
            )}
          </div>
        </div>
      )}

      {subTab === 'rir-aggregate-asn' && (
        <div className="space-y-4">
          {/* RIR Section */}
          <div className={`space-y-3.5 p-5 ${cardCls}`}>
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-900 dark:text-zinc-100">RIR ({rirs.length})</h3>
              <span className="text-[11px] text-slate-400 dark:text-zinc-500">{zh ? '如 APNIC / ARIN / RIPE / RFC1918' : 'e.g. APNIC / ARIN / RIPE / RFC1918'}</span>
            </div>
            <form onSubmit={handleCreateRir} className="flex flex-wrap items-center gap-2.5">
              <input
                required
                placeholder={zh ? 'RIR 名称（如 RFC1918 / APNIC）' : 'RIR name (e.g. RFC1918 / APNIC)'}
                value={rirForm.name}
                onChange={(e) => setRirForm((p) => ({ ...p, name: e.target.value }))}
                className={`min-w-[180px] flex-1 ${inputCls}`}
              />
              <label className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200/80 dark:border-zinc-700 bg-slate-50/70 dark:bg-zinc-800 px-3 py-2 text-xs font-medium text-slate-700 dark:text-zinc-200 cursor-pointer">
                <input
                  type="checkbox"
                  checked={rirForm.is_private}
                  onChange={(e) => setRirForm((p) => ({ ...p, is_private: e.target.checked }))}
                />
                {zh ? '私有空间' : 'Private'}
              </label>
              <input
                placeholder={zh ? '说明' : 'Description'}
                value={rirForm.description}
                onChange={(e) => setRirForm((p) => ({ ...p, description: e.target.value }))}
                className={`min-w-[160px] flex-1 ${inputCls}`}
              />
              <button type="submit" className={primaryBtnCls}>
                <Plus size={13} />
                {zh ? '新增 RIR' : 'Add RIR'}
              </button>
            </form>
            <div className="flex flex-wrap gap-2">
              {rirs.map((r) => (
                <div key={r.id} className="inline-flex items-center gap-2 rounded-xl border border-slate-200/90 dark:border-zinc-700 bg-slate-50/80 dark:bg-zinc-800/70 px-3 py-1.5 text-xs">
                  <span className="font-bold text-slate-800 dark:text-zinc-100">{r.name}</span>
                  {r.is_private && <span className="rounded-md bg-amber-100 dark:bg-amber-950/60 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800 dark:text-amber-300">{zh ? '私有' : 'Private'}</span>}
                  <span className="font-mono text-[11px] text-slate-500 dark:text-zinc-400">Agg:{r.aggregate_count ?? 0} · ASN:{r.asn_count ?? 0}</span>
                  <button
                    type="button"
                    onClick={() => void handleDeleteRir(r.id)}
                    className="rounded p-0.5 text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-950/50 hover:text-rose-700 cursor-pointer"
                    aria-label={zh ? `删除 RIR ${r.name}` : `Delete RIR ${r.name}`}
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              ))}
              {!rirs.length && (
                <p className="text-xs text-slate-400 dark:text-zinc-500">{zh ? '尚未登记 RIR，请先新增 RIR（如 RFC1918 或 APNIC）后再登记聚合地址块与 ASN。' : 'No RIRs yet. Add an RIR first before creating Aggregates or ASNs.'}</p>
              )}
            </div>
          </div>

          {/* Aggregates + ASNs */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className={`space-y-3.5 p-5 ${cardCls}`}>
              <h3 className="text-sm font-bold text-slate-900 dark:text-zinc-100">{zh ? '顶层地址块 (Aggregates)' : 'Aggregates'}</h3>
              <form onSubmit={handleCreateAggregate} className="grid grid-cols-1 gap-2 sm:grid-cols-4">
                <input
                  required
                  placeholder="10.0.0.0/8"
                  value={aggForm.prefix}
                  onChange={(e) => setAggForm((p) => ({ ...p, prefix: e.target.value }))}
                  className={`font-mono ${inputCls}`}
                />
                <select
                  required
                  aria-label={zh ? 'Aggregate 所属 RIR' : 'Aggregate RIR'}
                  value={aggForm.rir_id}
                  onChange={(e) => setAggForm((p) => ({ ...p, rir_id: e.target.value }))}
                  className={selectCls}
                >
                  <option value="">{zh ? '选择 RIR' : 'Select RIR'}</option>
                  {rirs.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                </select>
                <input
                  placeholder={zh ? '说明' : 'Description'}
                  value={aggForm.description}
                  onChange={(e) => setAggForm((p) => ({ ...p, description: e.target.value }))}
                  className={inputCls}
                />
                <button type="submit" className={primaryBtnCls}>
                  <Plus size={13} />
                  {zh ? '新增' : 'Add'}
                </button>
              </form>
              <div className="overflow-hidden rounded-xl border border-slate-100 dark:border-zinc-800">
                <table className="w-full text-left text-xs">
                  <thead className="border-b border-slate-200/80 dark:border-zinc-800 bg-slate-50/80 dark:bg-zinc-800/50 text-[11px] font-semibold text-slate-500 dark:text-zinc-400">
                    <tr>
                      <th className="px-3.5 py-2.5">CIDR</th>
                      <th className="px-3.5 py-2.5">RIR</th>
                      <th className="px-3.5 py-2.5">{zh ? '下辖网段' : 'Prefixes'}</th>
                      <th className="px-3.5 py-2.5 text-right">{zh ? '操作' : 'Actions'}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-zinc-800/80">
                    {aggregates.map((a) => (
                      <tr key={a.id} className="transition-colors hover:bg-slate-50/80 dark:hover:bg-zinc-800/40">
                        <td className="px-3.5 py-2.5">
                          <span className="inline-flex rounded-lg border border-emerald-200/80 dark:border-emerald-900/60 bg-emerald-50/70 dark:bg-emerald-950/40 px-2 py-0.5 font-mono font-semibold text-emerald-700 dark:text-emerald-300">
                            {a.prefix}
                          </span>
                        </td>
                        <td className="px-3.5 py-2.5 text-slate-700 dark:text-zinc-300">{a.rir_name}</td>
                        <td className="px-3.5 py-2.5 font-mono font-semibold text-slate-700 dark:text-zinc-300">{a.child_prefix_count ?? 0}</td>
                        <td className="px-3.5 py-2.5 text-right">
                          <button type="button" onClick={() => void handleDeleteAggregate(a.id)} className="rounded-lg p-1.5 text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-950/40 cursor-pointer" aria-label={`Delete ${a.prefix}`}>
                            <Trash2 size={13} />
                          </button>
                        </td>
                      </tr>
                    ))}
                    {!aggregates.length && (
                      <tr><td colSpan={4} className="px-3.5 py-8 text-center text-slate-400 dark:text-zinc-500">{zh ? '暂无顶层地址块' : 'No aggregates yet'}</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className={`space-y-3.5 p-5 ${cardCls}`}>
              <h3 className="text-sm font-bold text-slate-900 dark:text-zinc-100">{zh ? '自治系统号 (ASNs)' : 'ASNs'}</h3>
              <form onSubmit={handleCreateAsn} className="grid grid-cols-1 gap-2 sm:grid-cols-4">
                <input
                  required
                  type="number"
                  min={1}
                  max={4294967295}
                  placeholder="65001"
                  value={asnForm.asn}
                  onChange={(e) => setAsnForm((p) => ({ ...p, asn: e.target.value }))}
                  className={`font-mono ${inputCls}`}
                />
                <select
                  required
                  aria-label={zh ? 'ASN 所属 RIR' : 'ASN RIR'}
                  value={asnForm.rir_id}
                  onChange={(e) => setAsnForm((p) => ({ ...p, rir_id: e.target.value }))}
                  className={selectCls}
                >
                  <option value="">{zh ? '选择 RIR' : 'Select RIR'}</option>
                  {rirs.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                </select>
                <select
                  aria-label={zh ? 'ASN 站点' : 'ASN Site'}
                  value={asnForm.site_id}
                  onChange={(e) => setAsnForm((p) => ({ ...p, site_id: e.target.value }))}
                  className={selectCls}
                >
                  <option value="">{zh ? '不限站点' : 'No site'}</option>
                  {sites.map((s) => <option key={s.id} value={s.id}>{s.site_name || s.name || s.id}</option>)}
                </select>
                <button type="submit" className={primaryBtnCls}>
                  <Plus size={13} />
                  {zh ? '登记' : 'Add'}
                </button>
              </form>
              <div className="overflow-hidden rounded-xl border border-slate-100 dark:border-zinc-800">
                <table className="w-full text-left text-xs">
                  <thead className="border-b border-slate-200/80 dark:border-zinc-800 bg-slate-50/80 dark:bg-zinc-800/50 text-[11px] font-semibold text-slate-500 dark:text-zinc-400">
                    <tr>
                      <th className="px-3.5 py-2.5">ASN</th>
                      <th className="px-3.5 py-2.5">RIR</th>
                      <th className="px-3.5 py-2.5">{zh ? '站点' : 'Site'}</th>
                      <th className="px-3.5 py-2.5 text-right">{zh ? '操作' : 'Actions'}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-zinc-800/80">
                    {asns.map((n) => (
                      <tr key={n.id} className="transition-colors hover:bg-slate-50/80 dark:hover:bg-zinc-800/40">
                        <td className="px-3.5 py-2.5">
                          <span className="inline-flex rounded-lg border border-amber-200/80 dark:border-amber-900/60 bg-amber-50/70 dark:bg-amber-950/40 px-2 py-0.5 font-mono font-semibold text-amber-700 dark:text-amber-300">
                            AS{n.asn}
                          </span>
                        </td>
                        <td className="px-3.5 py-2.5 text-slate-700 dark:text-zinc-300">{n.rir_name}</td>
                        <td className="px-3.5 py-2.5 text-slate-600 dark:text-zinc-400">{n.site_name || (n.site_id ? siteLabel(n.site_id) : '—')}</td>
                        <td className="px-3.5 py-2.5 text-right">
                          <button type="button" onClick={() => void handleDeleteAsn(n.id)} className="rounded-lg p-1.5 text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-950/40 cursor-pointer" aria-label={`Delete AS${n.asn}`}>
                            <Trash2 size={13} />
                          </button>
                        </td>
                      </tr>
                    ))}
                    {!asns.length && (
                      <tr><td colSpan={4} className="px-3.5 py-8 text-center text-slate-400 dark:text-zinc-500">{zh ? '暂无 ASN 记录' : 'No ASNs yet'}</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default IPAMNativeModelsTab;
