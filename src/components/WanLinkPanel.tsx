import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Loader2, Plus, RefreshCw, Trash2, XCircle } from 'lucide-react';
import { Area, AreaChart, CartesianGrid, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useCoreApp } from '../contexts/AppDomainContext';
import type { WanLink, WanLinkHistoryResponse, WanLinkOptionsResponse } from '../types/wan';

const emptyForm: Record<string, any> = {
  link_name: '', site_id: '', site_name: '', device_id: '', interface_id: '', interface_name: '', if_index: '',
  provider: '', circuit_number: '', public_ip: '', link_role: 'primary', direction_mode: 'normal',
  contracted_download_mbps: '100', contracted_upload_mbps: '100', collection_interval_sec: '60',
  timezone: 'Asia/Shanghai', enabled: true, maintenance_window: '', notes: '',
};

const PROVIDER_GROUPS = [
  {
    key: 'domestic',
    zh: '国内运营商',
    en: 'Domestic operators',
    options: [
      '中国电信',
      '中国联通',
      '中国移动',
      '中国广电',
      '中国教育和科研计算机网 CERNET',
      '阿里云',
      '腾讯云',
      '华为云',
      '其他国内运营商',
    ],
  },
  {
    key: 'international',
    zh: '国际及跨境运营商',
    en: 'International and global operators',
    options: [
      '中国电信国际 CTG',
      '中国联通国际 CUG',
      'AT&T',
      'Verizon',
      'Lumen / Level 3',
      'Orange Business',
      'Vodafone Business',
      'NTT Communications',
      'Tata Communications',
      'Singtel',
      'PCCW Global',
      'Telia Carrier',
      'Cogent',
      'GTT Communications',
      'AWS Direct Connect',
      'Azure ExpressRoute',
      'Google Cloud Interconnect',
      '其他国际运营商',
    ],
  },
];

const tokenHeaders = () => {
  const token = localStorage.getItem('netops_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
};
const mbps = (bps?: number | null) => {
  if (bps == null) return '--';
  const value = Math.max(0, Number(bps));
  if (value < 1_000) return `${Math.round(value)} bps`;
  if (value < 1_000_000) return `${(value / 1_000).toFixed(value < 10_000 ? 2 : 1)} Kbps`;
  return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 0 : 1)} Mbps`;
};
const pct = (value?: number | null) => value == null ? '--' : `${Number(value).toFixed(1)}%`;
const formatTime = (value?: string | null) => value ? new Date(value).toLocaleTimeString('zh-CN', { hour12: false }) : '--';
const statusTone = (status?: string) => status === 'healthy' ? 'border-emerald-200 bg-emerald-50/50' : status === 'degraded' ? 'border-amber-200 bg-amber-50/60' : status === 'critical' || status === 'unavailable' ? 'border-rose-200 bg-rose-50/60' : 'border-slate-200 bg-slate-50/70';
const statusLabel = (status: string | undefined, zh: boolean) => ({ healthy: zh ? '正常' : 'Healthy', degraded: zh ? '关注' : 'Degraded', critical: zh ? '严重' : 'Critical', unavailable: zh ? '接口 Down' : 'Interface Down', unknown: zh ? '无数据' : 'No data' }[status || 'unknown'] || status || (zh ? '无数据' : 'No data'));

const heatColor = (sample: Record<string, any>) => {
  if (sample.collection_status !== 'success') return 'bg-slate-200';
  const flags = typeof sample.quality_flags === 'string' ? (() => { try { return JSON.parse(sample.quality_flags); } catch { return {}; } })() : sample.quality_flags || {};
  if (flags.maintenance_window) return 'bg-slate-400';
  const util = Math.max(Number(sample.download_util_pct || 0), Number(sample.upload_util_pct || 0));
  return util >= 95 ? 'bg-rose-500' : util >= 85 ? 'bg-orange-400' : util >= 70 ? 'bg-amber-300' : 'bg-emerald-400';
};

const WanLinkPanel: React.FC = () => {
  const { language, showToast } = useCoreApp();
  const zh = language === 'zh';
  const [links, setLinks] = useState<WanLink[]>([]);
  const [totalLinks, setTotalLinks] = useState(0);
  const [serverSummary, setServerSummary] = useState<Record<string, number>>({});
  const [options, setOptions] = useState<WanLinkOptionsResponse>({ devices: [], interfaces: [], sites: [] });
  const [selectedId, setSelectedId] = useState('');
  const [history, setHistory] = useState<WanLinkHistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState<Record<string, any>>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [historyMinutes, setHistoryMinutes] = useState(60);
  const [page, setPage] = useState(1);
  const [siteFilter, setSiteFilter] = useState('');
  const [providerFilter, setProviderFilter] = useState('');
  const [healthFilter, setHealthFilter] = useState('');
  const [keyword, setKeyword] = useState('');
  const [viewMode, setViewMode] = useState<'cards' | 'table'>('cards');
  const formRef = useRef<HTMLDivElement | null>(null);

  const load = async (signal?: AbortSignal, silent = false) => {
    if (!silent) setLoading(true);
    try {
      const query = new URLSearchParams({ page: String(page), page_size: '30' });
      if (siteFilter) query.set('site_id', siteFilter);
      if (providerFilter) query.set('provider', providerFilter);
      if (healthFilter) query.set('health_status', healthFilter);
      if (keyword.trim()) query.set('keyword', keyword.trim());
      const [linkResp, optionResp] = await Promise.all([
        fetch(`/api/monitoring/wan-links?${query}`, { headers: tokenHeaders(), signal }),
        fetch('/api/monitoring/wan-options', { headers: tokenHeaders(), signal }),
      ]);
      if (!linkResp.ok) throw new Error(zh ? '出口链路加载失败' : 'Unable to load WAN links');
      const payload = await linkResp.json();
      if (signal?.aborted) return;
      setLinks(payload.items || []);
      setTotalLinks(Number(payload.total || 0));
      setServerSummary(payload.summary || {});
      if (Number(payload.total || 0) > 30) setViewMode('table');
      if (optionResp.ok) setOptions(await optionResp.json());
      setSelectedId((current) => payload.items?.some((item: WanLink) => item.id === current) ? current : payload.items?.[0]?.id || '');
    } catch (error) {
      if ((error as Error)?.name !== 'AbortError') showToast(error instanceof Error ? error.message : String(error), 'error');
    } finally {
      if (!signal?.aborted && !silent) setLoading(false);
    }
  };

  const loadHistory = async (id: string, minutes = historyMinutes, signal?: AbortSignal) => {
    if (!id) { setHistory(null); return; }
    try {
      const response = await fetch(`/api/monitoring/wan-links/${encodeURIComponent(id)}/history?history_minutes=${minutes}`, { headers: tokenHeaders(), signal });
      if (response.ok && !signal?.aborted) setHistory(await response.json());
    } catch (error) {
      if ((error as Error)?.name !== 'AbortError') showToast(error instanceof Error ? error.message : String(error), 'error');
    }
  };

  useEffect(() => { const controller = new AbortController(); void load(controller.signal); return () => controller.abort(); }, [page, siteFilter, providerFilter, healthFilter, keyword]);
  useEffect(() => { const controller = new AbortController(); void loadHistory(selectedId, historyMinutes, controller.signal); return () => controller.abort(); }, [selectedId, historyMinutes]);
  useEffect(() => {
    const timer = window.setInterval(() => {
      const controller = new AbortController();
      void load(controller.signal, true);
      void loadHistory(selectedId, historyMinutes, controller.signal);
    }, 30_000);
    return () => window.clearInterval(timer);
  }, [page, siteFilter, providerFilter, healthFilter, keyword, selectedId, historyMinutes]);
  useEffect(() => {
    if (!formOpen) return;
    requestAnimationFrame(() => formRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
  }, [formOpen, form.id]);

  const selected = links.find((item) => item.id === selectedId) || null;
  const summary = useMemo(() => ({
    total: totalLinks,
    healthy: Number(serverSummary.healthy_links || links.filter((item) => item.health_status === 'healthy').length),
    download: links.reduce((sum, item) => sum + Number(item.download_bps || 0), 0),
    upload: links.reduce((sum, item) => sum + Number(item.upload_bps || 0), 0),
    maxUtil: Math.max(0, ...links.flatMap((item) => [Number(item.download_util_pct || 0), Number(item.upload_util_pct || 0)])),
    alerts: Number(serverSummary.active_alerts || links.reduce((sum, item) => sum + Number(item.active_alert_count || 0), 0)),
  }), [links, serverSummary, totalLinks]);

  const chartData = (history?.history || []).map((item) => ({
    time: formatTime(item.sampled_at),
    download: item.download_bps == null ? null : Number(item.download_bps) / 1_000_000,
    upload: item.upload_bps == null ? null : Number(item.upload_bps) / 1_000_000,
    downloadUtil: item.download_util_pct == null ? null : Number(item.download_util_pct),
    uploadUtil: item.upload_util_pct == null ? null : Number(item.upload_util_pct),
    errors: (Number(item.in_error_delta || 0) + Number(item.out_error_delta || 0)) || null,
    discards: (Number(item.in_discard_delta || 0) + Number(item.out_discard_delta || 0)) || null,
  }));
  const hasValidChartData = chartData.some((item) => item.download != null || item.upload != null || item.downloadUtil != null || item.uploadUtil != null);
  const validUtils = (history?.history || []).flatMap((item) => [item.download_util_pct, item.upload_util_pct]).filter((value): value is number => value != null).map(Number);
  const p95 = validUtils.length ? [...validUtils].sort((a, b) => a - b)[Math.min(validUtils.length - 1, Math.ceil(validUtils.length * 0.95) - 1)] : null;
  const highLoadMinutes = (history?.history || []).filter((item) => Math.max(Number(item.download_util_pct || 0), Number(item.upload_util_pct || 0)) >= 85).length * Math.max(1, Math.round(Number(history?.resolution || 60) / 60));
  const siteOptions = useMemo(() => [...options.sites].sort((a, b) => a.site_name.localeCompare(b.site_name)), [options.sites]);
  const visibleDevices = options.devices.filter((device) => {
    if (!form.site_id) return true;
    // Prefer the normalized site ID and keep the legacy `site` fallback for
    // older option payloads during rolling upgrades.
    return (device.site_id || device.site) === form.site_id;
  });
  const visibleInterfaces = options.interfaces.filter((item) => item.device_id === form.device_id);

  const openNew = () => {
    const site = siteOptions[0];
    setForm({ ...emptyForm, site_id: site?.id || '', site_name: site?.site_name || '', timezone: site?.timezone || emptyForm.timezone });
    setFormOpen(true);
  };
  const openEdit = (link: WanLink) => {
    setForm({ ...emptyForm, ...link, if_index: String(link.if_index || ''), contracted_download_mbps: String(Number(link.contracted_download_bps) / 1_000_000), contracted_upload_mbps: String(Number(link.contracted_upload_bps) / 1_000_000) });
    setFormOpen(true);
  };
  const update = (key: string, value: any) => setForm((current) => ({ ...current, [key]: value }));
  const save = async () => {
    setSaving(true);
    try {
      const payload = { ...form, id: form.id || undefined, if_index: form.if_index ? Number(form.if_index) : undefined, contracted_download_mbps: Number(form.contracted_download_mbps), contracted_upload_mbps: Number(form.contracted_upload_mbps), collection_interval_sec: Number(form.collection_interval_sec) };
      const response = await fetch(form.id ? `/api/monitoring/wan-links/${encodeURIComponent(form.id)}` : '/api/monitoring/wan-links', { method: form.id ? 'PATCH' : 'POST', headers: { ...tokenHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body?.detail?.message || body?.detail || (zh ? '保存失败' : 'Save failed'));
      setFormOpen(false); showToast(zh ? '出口链路已保存' : 'WAN link saved', 'success'); await load();
    } catch (error) { showToast(error instanceof Error ? error.message : String(error), 'error'); } finally { setSaving(false); }
  };
  const remove = async (id: string) => {
    if (!window.confirm(zh ? '确定删除这条出口链路及其采样吗？' : 'Delete this WAN link and its samples?')) return;
    const response = await fetch(`/api/monitoring/wan-links/${encodeURIComponent(id)}`, { method: 'DELETE', headers: tokenHeaders() });
    if (response.ok) { showToast(zh ? '出口链路已删除' : 'WAN link deleted', 'success'); await load(); }
  };
  const test = async (id: string) => {
    const response = await fetch(`/api/monitoring/wan-links/${encodeURIComponent(id)}/test`, { method: 'POST', headers: tokenHeaders() });
    const body = await response.json().catch(() => ({}));
    showToast(response.ok ? `${zh ? '采集测试' : 'Collection test'}: ${body.status || 'ok'}` : (body?.detail?.message || (zh ? '采集测试失败' : 'Collection test failed')), response.ok ? 'success' : 'error');
  };
  const trigger = async () => {
    const response = await fetch('/api/monitoring/wan-trigger', { method: 'POST', headers: tokenHeaders() });
    if (response.ok) { showToast(zh ? '已完成一次链路采集' : 'WAN collection completed', 'success'); await load(); if (selectedId) await loadHistory(selectedId, historyMinutes); } else showToast(zh ? '链路采集失败' : 'WAN collection failed', 'error');
  };

  return <section className="mt-5 rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-4 shadow-sm md:p-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><p className="text-[10px] font-bold uppercase tracking-[0.18em] text-cyan-600">{zh ? '出口链路监控' : 'WAN link monitoring'}</p><h2 className="mt-1 text-xl font-extrabold text-[var(--app-text)]">{zh ? '互联网出口链路' : 'Internet egress links'}</h2><p className="mt-1 text-xs text-[var(--muted-text)]">{zh ? 'SNMP 64 位计数器 · 签约带宽利用率 · 持续阈值告警' : '64-bit IF-MIB counters · contracted bandwidth · sustained alerts'}</p></div>
      <div className="flex flex-wrap gap-2"><button type="button" onClick={openNew} className="inline-flex items-center gap-1.5 rounded-xl bg-cyan-600 px-3 py-2 text-xs font-bold text-white"><Plus size={13} />{zh ? '新增出口链路' : 'Add WAN link'}</button><button type="button" onClick={trigger} className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--card-border)] px-3 py-2 text-xs font-semibold text-[var(--muted-text)]"><RefreshCw size={13} />{zh ? '立即采集' : 'Collect now'}</button><button type="button" onClick={() => void load()} className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--card-border)] px-3 py-2 text-xs font-semibold text-[var(--muted-text)]"><RefreshCw size={13} />{zh ? '刷新' : 'Refresh'}</button></div>
    </div>
    <div className="mt-4 grid gap-2 md:grid-cols-5"><select value={siteFilter} onChange={(event) => { setSiteFilter(event.target.value); setPage(1); }} className="rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-2 text-xs"><option value="">{zh ? '全部站点' : 'All sites'}</option>{siteOptions.map((site) => <option key={site.id} value={site.id}>{site.site_name}</option>)}</select><input value={providerFilter} onChange={(event) => { setProviderFilter(event.target.value); setPage(1); }} placeholder={zh ? '运营商' : 'Provider'} className="rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-2 text-xs" /><select value={healthFilter} onChange={(event) => { setHealthFilter(event.target.value); setPage(1); }} className="rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-2 text-xs"><option value="">{zh ? '全部状态' : 'All status'}</option><option value="healthy">{zh ? '正常' : 'Healthy'}</option><option value="degraded">{zh ? '关注' : 'Degraded'}</option><option value="critical">{zh ? '严重' : 'Critical'}</option><option value="unavailable">{zh ? '接口 Down' : 'Interface Down'}</option></select><input value={keyword} onChange={(event) => { setKeyword(event.target.value); setPage(1); }} placeholder={zh ? '链路/接口/站点关键字' : 'Link/interface/site'} className="rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-2 text-xs md:col-span-2" /></div>
    <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-6">{[[zh ? '出口链路' : 'WAN links', `${summary.healthy}/${summary.total}`], [zh ? '当前下载' : 'Download', mbps(summary.download)], [zh ? '当前上传' : 'Upload', mbps(summary.upload)], [zh ? '最高利用率' : 'Max utilization', pct(summary.maxUtil)], [zh ? '活动告警' : 'Active alerts', summary.alerts], [zh ? '视图' : 'View', <button key="view" type="button" onClick={() => setViewMode((mode) => mode === 'cards' ? 'table' : 'cards')} className="font-bold text-cyan-700">{viewMode === 'cards' ? (zh ? '卡片' : 'Cards') : (zh ? '表格' : 'Table')}</button>]].map(([label, value]) => <div key={String(label)} className="rounded-xl border border-[var(--card-border)] bg-black/[0.02] px-3 py-2.5"><p className="text-[10px] font-bold text-[var(--muted-text)]">{label}</p><p className="mt-1 text-sm font-extrabold text-[var(--app-text)]">{value}</p></div>)}</div>
    {loading ? <div className="flex min-h-32 items-center justify-center text-sm text-[var(--muted-text)]"><Loader2 className="mr-2 animate-spin" size={16} />{zh ? '正在加载出口链路…' : 'Loading WAN links…'}</div> : links.length === 0 ? <div className="mt-4 rounded-xl border border-dashed border-cyan-200 bg-cyan-50/40 px-4 py-8 text-center text-sm text-cyan-800">{zh ? '暂无出口链路，请先绑定站点、设备和接口。' : 'No WAN links configured. Bind a site, device and interface first.'}</div> : <>
      {viewMode === 'table' ? <div className="mt-4 overflow-x-auto rounded-xl border border-[var(--card-border)]"><table className="w-full min-w-[760px] text-left text-xs"><thead className="bg-black/[0.03] text-[var(--muted-text)]"><tr><th className="px-3 py-2">{zh ? '链路' : 'Link'}</th><th className="px-3 py-2">{zh ? '站点/运营商' : 'Site/provider'}</th><th className="px-3 py-2">{zh ? '状态' : 'Status'}</th><th className="px-3 py-2">{zh ? '下载/上传' : 'Down/up'}</th><th className="px-3 py-2">{zh ? '利用率' : 'Utilization'}</th><th className="px-3 py-2">{zh ? '操作' : 'Actions'}</th></tr></thead><tbody>{links.map((link) => <tr key={link.id} className="border-t border-[var(--card-border)]"><td className="px-3 py-2"><button type="button" onClick={() => setSelectedId(link.id)} className="font-bold text-cyan-700">{link.link_name}</button><p className="text-[10px] text-[var(--muted-text)]">{link.interface_name} · ifIndex {link.if_index}</p></td><td className="px-3 py-2">{link.site_name || '--'}<p className="text-[10px] text-[var(--muted-text)]">{link.provider || '--'}</p></td><td className="px-3 py-2">{statusLabel(link.health_status, zh)}<p className="text-[10px] text-[var(--muted-text)]">{link.collection_status || 'unknown'}</p></td><td className="px-3 py-2">{mbps(link.download_bps)}<p>{mbps(link.upload_bps)}</p></td><td className="px-3 py-2">{pct(link.download_util_pct)}<p>{pct(link.upload_util_pct)}</p></td><td className="px-3 py-2"><button type="button" onClick={() => void test(link.id)} className="mr-2 font-bold text-cyan-700">{zh ? '测试' : 'Test'}</button><button type="button" onClick={() => openEdit(link)} className="mr-2 font-bold text-cyan-700">{zh ? '编辑' : 'Edit'}</button><button type="button" onClick={() => void remove(link.id)} className="text-rose-600" aria-label={zh ? '删除链路' : 'Delete link'}><Trash2 size={13} /></button></td></tr>)}</tbody></table></div> : <div className="mt-4 grid gap-3 lg:grid-cols-2">{links.map((link) => <article key={link.id} className={`rounded-2xl border p-4 ${statusTone(link.health_status)} ${selectedId === link.id ? 'ring-2 ring-cyan-300/70' : ''}`}><div className="flex items-start justify-between gap-3"><button type="button" className="min-w-0 text-left" onClick={() => setSelectedId(link.id)}><p className="truncate text-sm font-extrabold text-[var(--app-text)]">{link.link_name}</p><p className="mt-1 truncate text-[10px] text-[var(--muted-text)]">{link.provider || (zh ? '未填写运营商' : 'Provider not set')} · {link.site_name || '--'} · {link.interface_name} (ifIndex {link.if_index})</p></button><span className="inline-flex items-center gap-1 rounded-full bg-white/70 px-2 py-1 text-[10px] font-bold text-[var(--muted-text)]">{link.health_status === 'healthy' ? <CheckCircle2 size={12} className="text-emerald-600" /> : link.health_status === 'unavailable' ? <XCircle size={12} className="text-rose-600" /> : <AlertTriangle size={12} className="text-amber-600" />}{statusLabel(link.health_status, zh)}</span></div><div className="mt-3 grid grid-cols-2 gap-2 text-xs"><div><span className="text-[var(--muted-text)]">{zh ? '下载' : 'Down'} </span><b>{mbps(link.download_bps)} / {mbps(link.contracted_download_bps)} </b><span className="text-cyan-700">({pct(link.download_util_pct)})</span></div><div><span className="text-[var(--muted-text)]">{zh ? '上传' : 'Up'} </span><b>{mbps(link.upload_bps)} / {mbps(link.contracted_upload_bps)} </b><span className="text-cyan-700">({pct(link.upload_util_pct)})</span></div></div><div className="mt-3 flex items-center justify-between text-[10px] text-[var(--muted-text)]"><span>{zh ? '最后采集' : 'Last collection'}：{formatTime(link.last_success_at || link.sampled_at)} · {link.collection_status || 'unknown'}</span><span className="flex gap-2"><button type="button" onClick={() => void test(link.id)} className="font-bold text-cyan-700">{zh ? '测试' : 'Test'}</button><button type="button" onClick={() => openEdit(link)} className="font-bold text-cyan-700">{zh ? '编辑' : 'Edit'}</button><button type="button" onClick={() => void remove(link.id)} className="text-rose-600" aria-label={zh ? '删除链路' : 'Delete link'}><Trash2 size={13} /></button></span></div></article>)}</div>}
      <div className="mt-3 flex items-center justify-end gap-2 text-xs"><button type="button" disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))} className="rounded-lg border border-[var(--card-border)] px-3 py-1.5 disabled:opacity-40">{zh ? '上一页' : 'Previous'}</button><span className="text-[var(--muted-text)]">{page} / {Math.max(1, Math.ceil(totalLinks / 30))}</span><button type="button" disabled={page >= Math.ceil(totalLinks / 30)} onClick={() => setPage((value) => value + 1)} className="rounded-lg border border-[var(--card-border)] px-3 py-1.5 disabled:opacity-40">{zh ? '下一页' : 'Next'}</button></div>
    </>}
    {selected && <div className="mt-5 rounded-2xl border border-[var(--card-border)] p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div><h3 className="text-sm font-extrabold text-[var(--app-text)]">{selected.link_name} · {zh ? '流量趋势' : 'Traffic trend'}</h3><p className="mt-1 text-[10px] text-[var(--muted-text)]">{zh ? `异常计数器不会被折算为 0；当前粒度 ${Math.max(1, Math.round(Number(history?.resolution || 60) / 60))} 分钟。` : `Invalid counters remain null; current resolution is ${Math.max(1, Math.round(Number(history?.resolution || 60) / 60))} minutes.`}</p></div><div className="flex flex-wrap gap-1">{[{ minutes: 5, zh: '5分钟', en: '5m' }, { minutes: 15, zh: '15分钟', en: '15m' }, { minutes: 60, zh: '1小时', en: '1h' }, { minutes: 360, zh: '6小时', en: '6h' }, { minutes: 1440, zh: '1天', en: '1d' }, { minutes: 10080, zh: '7天', en: '7d' }, { minutes: 43200, zh: '30天', en: '30d' }].map((range) => <button key={range.minutes} type="button" onClick={() => setHistoryMinutes(range.minutes)} className={`rounded-md px-2 py-1 text-[10px] font-bold ${historyMinutes === range.minutes ? 'bg-cyan-100 text-cyan-800' : 'text-[var(--muted-text)] hover:bg-black/[0.04]'}`}>{zh ? range.zh : range.en}</button>)}</div></div><div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-4"><div className="rounded-lg bg-black/[0.03] px-3 py-2"><p className="text-[10px] text-[var(--muted-text)]">P95 utilization</p><b>{pct(p95)}</b></div><div className="rounded-lg bg-black/[0.03] px-3 py-2"><p className="text-[10px] text-[var(--muted-text)]">High load ≥85%</p><b>{highLoadMinutes} min</b></div><div className="rounded-lg bg-black/[0.03] px-3 py-2"><p className="text-[10px] text-[var(--muted-text)]">Errors</p><b>{chartData.reduce((sum, item) => sum + Number(item.errors || 0), 0)}</b></div><div className="rounded-lg bg-black/[0.03] px-3 py-2"><p className="text-[10px] text-[var(--muted-text)]">Discards</p><b>{chartData.reduce((sum, item) => sum + Number(item.discards || 0), 0)}</b></div></div><div className="mt-4 h-64">{hasValidChartData ? <ResponsiveContainer width="100%" height="100%"><AreaChart data={chartData} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}><defs><linearGradient id="wanDownloadFill" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#06b6d4" stopOpacity={0.18} /><stop offset="95%" stopColor="#06b6d4" stopOpacity={0} /></linearGradient></defs><CartesianGrid strokeDasharray="3 3" stroke="rgba(100,116,139,.15)" /><XAxis dataKey="time" tick={{ fontSize: 10 }} minTickGap={26} /><YAxis yAxisId="traffic" tick={{ fontSize: 10 }} unit=" Mbps" /><YAxis yAxisId="util" orientation="right" tick={{ fontSize: 10 }} unit="%" /><YAxis yAxisId="count" hide /><Tooltip /><Legend /><Area yAxisId="traffic" type="monotone" dataKey="download" name={zh ? '下载 Mbps' : 'Download Mbps'} stroke="#06b6d4" fill="url(#wanDownloadFill)" connectNulls={false} dot={{ r: 2, strokeWidth: 1 }} /><Area yAxisId="traffic" type="monotone" dataKey="upload" name={zh ? '上传 Mbps' : 'Upload Mbps'} stroke="#8b5cf6" fill="none" connectNulls={false} dot={{ r: 2, strokeWidth: 1 }} /><Line yAxisId="util" type="monotone" dataKey="downloadUtil" name={zh ? '下载利用率' : 'Download util'} stroke="#f59e0b" dot={{ r: 2, strokeWidth: 1 }} connectNulls={false} /><Line yAxisId="util" type="monotone" dataKey="uploadUtil" name={zh ? '上传利用率' : 'Upload util'} stroke="#ef4444" dot={{ r: 2, strokeWidth: 1 }} connectNulls={false} /><Line yAxisId="count" type="monotone" dataKey="errors" name={zh ? '错包增量' : 'Errors'} stroke="#ec4899" dot={{ r: 2, strokeWidth: 1 }} connectNulls={false} /><Line yAxisId="count" type="monotone" dataKey="discards" name={zh ? '丢弃增量' : 'Discards'} stroke="#14b8a6" dot={{ r: 2, strokeWidth: 1 }} connectNulls={false} /></AreaChart></ResponsiveContainer> : <div className="flex h-full items-center justify-center text-xs text-[var(--muted-text)]">{zh ? '暂无有效流量样本；首轮采集将建立计数器基线。' : 'No valid traffic samples yet; the first poll establishes a counter baseline.'}</div>}</div><div className="mt-3"><p className="mb-1 text-[10px] font-bold text-[var(--muted-text)]">{zh ? '最近 60 次热度' : 'Last 60 samples'}</p><div className="flex gap-0.5">{(history?.history || []).slice(-60).map((sample: any, index) => <span key={`${sample.sampled_at}-${index}`} title={`${sample.sampled_at} · ${pct(Math.max(Number(sample.download_util_pct || 0), Number(sample.upload_util_pct || 0)))} · ${sample.collection_status || 'unknown'}`} className={`h-4 min-w-1 flex-1 rounded-sm ${heatColor(sample)}`} />)}</div></div><div className="mt-3 flex flex-wrap gap-2">{(history?.events || []).slice(0, 6).map((event) => <span key={event.id} className={`rounded-full border px-2 py-1 text-[10px] font-semibold ${event.status === 'firing' ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>{event.title} · {event.status === 'firing' ? (zh ? '告警中' : 'Firing') : (zh ? '已恢复' : 'Resolved')}</span>)}</div></div>}
    {formOpen && <div ref={formRef} className="scroll-mt-24 mt-5 rounded-2xl border-2 border-cyan-300 bg-cyan-50/40 p-4 shadow-md"><div className="flex items-center justify-between"><div><p className="text-[10px] font-bold uppercase tracking-[0.16em] text-cyan-700">{form.id ? (zh ? '正在编辑' : 'Editing') : (zh ? '正在新增' : 'Adding')}</p><h3 className="mt-0.5 text-sm font-extrabold text-[var(--app-text)]">{form.id ? (zh ? '编辑出口链路' : 'Edit WAN link') : (zh ? '新增出口链路' : 'Add WAN link')}</h3></div><button type="button" onClick={() => setFormOpen(false)} aria-label={zh ? '关闭' : 'Close'}><XCircle size={17} className="text-[var(--muted-text)]" /></button></div><div className="mt-3 grid gap-3 md:grid-cols-3"><label className="text-[10px] font-bold text-[var(--muted-text)]">{zh ? '站点' : 'Site'}<select value={form.site_id} onChange={(event) => { const site = siteOptions.find((item) => item.id === event.target.value); update('site_id', event.target.value); update('site_name', site?.site_name || ''); update('timezone', site?.timezone || emptyForm.timezone); update('device_id', ''); update('interface_id', ''); }} className="mt-1 w-full rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-2 text-xs"><option value="">{zh ? '请选择站点' : 'Select site'}</option>{siteOptions.map((site) => <option key={site.id} value={site.id}>{site.site_name}</option>)}</select></label><label className="text-[10px] font-bold text-[var(--muted-text)]">{zh ? '设备' : 'Device'}<select value={form.device_id} onChange={(event) => { update('device_id', event.target.value); update('interface_id', ''); }} className="mt-1 w-full rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-2 text-xs"><option value="">{zh ? '请选择设备' : 'Select device'}</option>{visibleDevices.length ? visibleDevices.map((device) => <option key={device.id} value={device.id}>{device.hostname || device.ip_address} · {device.site_name || device.site || '--'} · {device.role || device.device_category || (zh ? '出口候选' : 'WAN candidate')}</option>) : <option disabled value="">{zh ? '当前站点无核心/边界/防火墙设备' : 'No core, edge or firewall device at this site'}</option>}</select></label><label className="text-[10px] font-bold text-[var(--muted-text)]">{zh ? '接口' : 'Interface'}<select value={form.interface_id} onChange={(event) => { const item = visibleInterfaces.find((candidate) => candidate.id === event.target.value); update('interface_id', event.target.value); update('interface_name', item?.interface_name || ''); update('if_index', item?.if_index ? String(item.if_index) : ''); }} className="mt-1 w-full rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-2 text-xs"><option value="">{zh ? '请选择接口' : 'Select interface'}</option>{visibleInterfaces.map((item) => <option key={item.id} value={item.id}>{item.interface_name} · ifIndex {item.if_index || '--'}</option>)}</select></label><label className="text-[10px] font-bold text-[var(--muted-text)]">{zh ? '运营商' : 'Provider'}<select value={form.provider || ''} onChange={(event) => update('provider', event.target.value)} className="mt-1 w-full rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-2 text-xs"><option value="">{zh ? '请选择运营商' : 'Select provider'}</option>{PROVIDER_GROUPS.map((group) => <optgroup key={group.key} label={zh ? group.zh : group.en}>{group.options.map((provider) => <option key={provider} value={provider}>{provider}</option>)}</optgroup>)}{form.provider && !PROVIDER_GROUPS.some((group) => group.options.includes(form.provider)) && <option value={form.provider}>{form.provider} ({zh ? '历史值' : 'Existing value'})</option>}</select></label>{[['link_name', zh ? '链路名称' : 'Link name', 'text'], ['circuit_number', zh ? '线路编号' : 'Circuit number', 'text'], ['contracted_download_mbps', zh ? '签约下行 Mbps' : 'Contracted download Mbps', 'number'], ['contracted_upload_mbps', zh ? '签约上行 Mbps' : 'Contracted upload Mbps', 'number'], ['public_ip', '公网 IP', 'text']].map(([key, label, type]) => <label key={String(key)} className="text-[10px] font-bold text-[var(--muted-text)]">{label}<input type={String(type)} value={form[String(key)] ?? ''} onChange={(event) => update(String(key), event.target.value)} className="mt-1 w-full rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-2 text-xs" /></label>)}<label title={zh ? 'IF-MIB 中用于唯一识别接口的整数索引，由 SNMP 接口同步填充。' : 'The IF-MIB integer used to identify the interface; populated by SNMP interface sync.'} className="text-[10px] font-bold text-[var(--muted-text)]">{zh ? '接口索引（ifIndex）' : 'Interface index (ifIndex)'}<input type="number" value={form.if_index} readOnly className="mt-1 w-full rounded-lg border border-[var(--card-border)] bg-slate-100 px-2.5 py-2 text-xs" /><span className="mt-1 block text-[9px] font-normal text-[var(--muted-text)]">{zh ? 'SNMP 同步后自动填充；当前为 -- 时不能保存链路。' : 'Filled by SNMP sync; a missing value prevents saving.'}</span></label><label className="text-[10px] font-bold text-[var(--muted-text)]">{zh ? '链路角色' : 'Role'}<select value={form.link_role} onChange={(event) => update('link_role', event.target.value)} className="mt-1 w-full rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-2 text-xs"><option value="primary">{zh ? '主用' : 'Primary'}</option><option value="backup">{zh ? '备用' : 'Backup'}</option><option value="load_balanced">{zh ? '负载均衡' : 'Load balanced'}</option></select></label><label className="text-[10px] font-bold text-[var(--muted-text)]">{zh ? '方向' : 'Direction'}<select value={form.direction_mode} onChange={(event) => update('direction_mode', event.target.value)} className="mt-1 w-full rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-2 text-xs"><option value="normal">{zh ? '正常（正向）' : 'Normal (forward)'}</option><option value="reversed">{zh ? '反向' : 'Reversed'}</option></select></label></div><div className="mt-3 flex justify-end gap-2"><button type="button" onClick={() => setFormOpen(false)} className="rounded-lg border border-[var(--card-border)] px-3 py-2 text-xs">{zh ? '取消' : 'Cancel'}</button><button type="button" disabled={saving} onClick={() => void save()} className="rounded-lg bg-cyan-600 px-3 py-2 text-xs font-bold text-white disabled:opacity-50">{saving ? (zh ? '保存中…' : 'Saving…') : (zh ? '保存链路' : 'Save link')}</button></div></div>}
  </section>;
};

export default WanLinkPanel;
