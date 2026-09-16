import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Activity, Boxes, CheckCircle2, CircleAlert, CloudCog, Database,
  Gauge, Layers3, Plus, RefreshCw, RotateCcw, Save, Server, ShieldCheck,
  TestTube2, XCircle,
} from 'lucide-react';
import PageHero from './PageHero';

export type MonitoringManagementMode = 'plans' | 'modules' | 'collectors' | 'health';

interface MonitoringManagementPageProps {
  language: 'zh' | 'en';
  mode: MonitoringManagementMode;
  showToast: (message: string, type?: string) => void;
}

interface ModuleRow {
  id: string;
  module_key: string;
  display_name: string;
  vendor?: string;
  cli_platform?: string;
  feature_domain?: string;
  metric_group?: string;
  walk_fingerprint?: string;
  enabled?: boolean | number;
  built_in?: boolean | number;
}

interface VariantRow {
  id: string;
  module_id: string;
  variant_key: string;
  display_name: string;
  max_repetitions?: number;
  retries?: number;
  request_timeout_ms?: number;
  scrape_timeout_ms?: number;
  status?: string;
  enabled?: boolean | number;
}

interface CollectorRow {
  id: string;
  name: string;
  code: string;
  site_id?: string;
  status?: string;
  collector_type?: string;
  enabled?: boolean | number;
  last_config_version?: number | null;
  last_config_status?: string;
  max_concurrency?: number;
  queue_disk_limit_mb?: number;
}

interface PlanRow {
  id: string;
  name: string;
  cli_platform?: string;
  description?: string;
  config?: { modules?: Array<Record<string, unknown>> };
  enabled?: boolean | number;
}

interface HealthItem {
  assignment_id?: string;
  asset_id?: string;
  collector_id?: string;
  module_variant_id?: string;
  status?: string;
  error_code?: string | null;
  age_seconds?: number | null;
  interval_seconds?: number;
  device_health?: string;
}

interface HealthPayload {
  items?: HealthItem[];
  summary?: { total?: number; healthy?: number; health_ratio?: number; by_status?: Record<string, number> };
}

const authHeaders = (): Record<string, string> => {
  const token = localStorage.getItem('netops_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
};

const enabled = (value: unknown) => value === true || value === 1 || value === '1';

const statusTone = (status: string | undefined) => {
  const normalized = String(status || '').toUpperCase();
  if (['OK', 'ONLINE', 'PUBLISHED', 'APPLIED', 'SUCCESS'].includes(normalized)) return 'text-emerald-700 bg-emerald-50 border-emerald-200';
  if (['FAILED', 'OFFLINE', 'MISMATCH', 'ERROR'].includes(normalized)) return 'text-rose-700 bg-rose-50 border-rose-200';
  return 'text-amber-700 bg-amber-50 border-amber-200';
};

const MonitoringManagementPage: React.FC<MonitoringManagementPageProps> = ({ language, mode, showToast }) => {
  const zh = language === 'zh';
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [modules, setModules] = useState<ModuleRow[]>([]);
  const [variants, setVariants] = useState<VariantRow[]>([]);
  const [collectors, setCollectors] = useState<CollectorRow[]>([]);
  const [plans, setPlans] = useState<PlanRow[]>([]);
  const [health, setHealth] = useState<HealthPayload>({});
  const [selectedModule, setSelectedModule] = useState('');
  const [selectedCollector, setSelectedCollector] = useState('');
  const [moduleForm, setModuleForm] = useState({ module_key: '', display_name: '', vendor: 'generic', cli_platform: 'generic', metric_group: 'interface', walk_fingerprint: '' });
  const [variantForm, setVariantForm] = useState({ variant_key: '', display_name: '', max_repetitions: '25', request_timeout_ms: '3000', scrape_timeout_ms: '20000' });
  const [collectorForm, setCollectorForm] = useState({ name: '', code: '', site_id: '', collector_type: 'LOCAL' });
  const [planForm, setPlanForm] = useState({ name: '', cli_platform: '', description: '', config: '{\n  "modules": []\n}' });

  const request = useCallback(async (path: string, init?: RequestInit) => {
    const response = await fetch(path, {
      ...init,
      headers: { ...authHeaders(), ...(init?.headers || {}), ...(init?.body ? { 'Content-Type': 'application/json' } : {}) },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof payload?.detail === 'string' ? payload.detail : JSON.stringify(payload?.detail || payload || response.statusText);
      throw new Error(detail);
    }
    return payload;
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      if (mode === 'modules') {
        const [modulePayload, variantPayload] = await Promise.all([
          request('/api/monitoring/modules'),
          request('/api/monitoring/module-variants'),
        ]);
        setModules(Array.isArray(modulePayload?.items) ? modulePayload.items : []);
        setVariants(Array.isArray(variantPayload?.items) ? variantPayload.items : []);
      } else if (mode === 'collectors') {
        const payload = await request('/api/monitoring/collectors');
        setCollectors(Array.isArray(payload?.items) ? payload.items : []);
      } else if (mode === 'plans') {
        const payload = await request('/api/monitoring/collection-plans');
        setPlans(Array.isArray(payload?.items) ? payload.items : []);
      } else {
        setHealth(await request('/api/monitoring/collection-health'));
      }
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [mode, request]);

  useEffect(() => { void load(); }, [load]);

  const runAction = useCallback(async (path: string, method = 'POST', body?: unknown) => {
    try {
      await request(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });
      showToast(zh ? '操作已完成' : 'Action completed', 'success');
      await load();
    } catch (reason) {
      showToast(reason instanceof Error ? reason.message : String(reason), 'error');
    }
  }, [load, request, showToast, zh]);

  const createModule = async (event: React.FormEvent) => {
    event.preventDefault();
    await runAction('/api/monitoring/modules', 'POST', moduleForm);
    setModuleForm({ module_key: '', display_name: '', vendor: 'generic', cli_platform: 'generic', metric_group: 'interface', walk_fingerprint: '' });
  };

  const createVariant = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selectedModuleRow) return;
    await runAction('/api/monitoring/module-variants', 'POST', {
      module_id: selectedModuleRow.id,
      variant_key: variantForm.variant_key,
      display_name: variantForm.display_name,
      max_repetitions: Number(variantForm.max_repetitions) || 25,
      request_timeout_ms: Number(variantForm.request_timeout_ms) || 3000,
      scrape_timeout_ms: Number(variantForm.scrape_timeout_ms) || 20000,
      status: 'DRAFT',
      enabled: true,
    });
    setVariantForm({ variant_key: '', display_name: '', max_repetitions: '25', request_timeout_ms: '3000', scrape_timeout_ms: '20000' });
  };

  const createCollector = async (event: React.FormEvent) => {
    event.preventDefault();
    await runAction('/api/monitoring/collectors', 'POST', collectorForm);
    setCollectorForm({ name: '', code: '', site_id: '', collector_type: 'LOCAL' });
  };

  const createPlan = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      const config = JSON.parse(planForm.config);
      await runAction('/api/monitoring/collection-plans', 'POST', { ...planForm, config });
      setPlanForm({ name: '', cli_platform: '', description: '', config: '{\n  "modules": []\n}' });
    } catch {
      showToast(zh ? 'Plan JSON 格式无效' : 'Plan JSON is invalid', 'error');
    }
  };

  const title = mode === 'modules'
    ? (zh ? '模块目录' : 'Module Catalog')
    : mode === 'collectors'
      ? (zh ? '采集器管理' : 'Collectors')
      : mode === 'plans'
        ? (zh ? 'Collection Plans' : 'Collection Plans')
        : (zh ? '采集健康' : 'Collection Health');
  const subtitle = mode === 'modules'
    ? (zh ? '管理 SNMP Module、Variant 与发布状态' : 'Manage SNMP modules, variants, and publication state')
    : mode === 'collectors'
      ? (zh ? '编译、发布和回滚 Collector 配置' : 'Compile, publish, and roll back collector artifacts')
      : mode === 'plans'
        ? (zh ? '从 CMDB Collection Plan 生成采集 Assignment' : 'Compile assignments from CMDB collection plans')
        : (zh ? '区分设备健康与采集链路健康' : 'Separate device health from collection health');

  const tabItems: Array<[MonitoringManagementMode, string, string]> = [
    ['plans', zh ? 'Plans' : 'Plans', '/monitor/collection-plans'],
    ['modules', zh ? 'Modules' : 'Modules', '/monitor/modules'],
    ['collectors', zh ? 'Collectors' : 'Collectors', '/monitor/collectors'],
    ['health', zh ? 'Collection Health' : 'Collection Health', '/monitor/collection-health'],
  ];

  const selectedModuleRow = modules.find(item => item.id === selectedModule) || modules[0];
  const selectedCollectorRow = collectors.find(item => item.id === selectedCollector) || collectors[0];
  const moduleVariants = useMemo(() => variants.filter(item => !selectedModuleRow || item.module_id === selectedModuleRow.id), [selectedModuleRow, variants]);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <PageHero
        icon={mode === 'modules' ? Boxes : mode === 'collectors' ? CloudCog : mode === 'plans' ? Layers3 : Gauge}
        title={title}
        subtitle={subtitle}
        actions={<button type="button" onClick={() => void load()} disabled={loading} className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-sm hover:border-cyan-300 disabled:opacity-50"><RefreshCw size={14} className={loading ? 'animate-spin' : ''} />{zh ? '刷新' : 'Refresh'}</button>}
        extras={<div className="flex flex-wrap gap-2">{tabItems.map(([key, label, path]) => <button key={key} type="button" onClick={() => navigate(path)} className={`rounded-xl px-3 py-2 text-xs font-bold transition ${mode === key ? 'bg-cyan-600 text-white shadow-sm' : 'border border-slate-200 bg-white text-slate-600 hover:border-cyan-300'}`}>{label}</button>)}</div>}
      />
      <div className="min-h-0 flex-1 overflow-auto p-6">
        {error && <div className="mb-4 flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700"><CircleAlert size={16} className="mt-0.5 shrink-0" /><span>{error}</span></div>}
        {mode === 'modules' && (
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
            <section className="space-y-3">
              {modules.length === 0 && !loading ? <EmptyState zh={zh} label={zh ? '暂无 Module' : 'No modules yet'} /> : modules.map(module => <button key={module.id} type="button" onClick={() => setSelectedModule(module.id)} className={`w-full rounded-2xl border p-4 text-left transition ${selectedModuleRow?.id === module.id ? 'border-cyan-400 bg-cyan-50/60 shadow-sm' : 'border-slate-200 bg-white hover:border-cyan-200'}`}><div className="flex items-start justify-between gap-3"><div><p className="font-bold text-slate-900">{module.display_name}</p><p className="mt-1 font-mono text-xs text-cyan-700">{module.module_key}</p></div><span className={`rounded-full border px-2 py-1 text-[10px] font-bold ${enabled(module.enabled) ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-slate-200 bg-slate-50 text-slate-500'}`}>{enabled(module.enabled) ? 'ENABLED' : 'DISABLED'}</span></div><div className="mt-3 flex flex-wrap gap-2 text-[10px] text-slate-500"><span>{module.vendor || 'generic'}</span><span>·</span><span>{module.cli_platform || 'generic'}</span><span>·</span><span>{module.metric_group || '—'}</span></div></button>)}
            </section>
            <aside className="space-y-4">
              <form onSubmit={createModule} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="mb-3 flex items-center gap-2"><Plus size={16} className="text-cyan-600" /><h2 className="text-sm font-bold text-slate-900">{zh ? '新增 Module' : 'Add module'}</h2></div><Input label="Module Key" value={moduleForm.module_key} onChange={value => setModuleForm({ ...moduleForm, module_key: value })} required /><Input label={zh ? '显示名称' : 'Display name'} value={moduleForm.display_name} onChange={value => setModuleForm({ ...moduleForm, display_name: value })} required /><Input label="Walk Fingerprint" value={moduleForm.walk_fingerprint} onChange={value => setModuleForm({ ...moduleForm, walk_fingerprint: value })} /><button type="submit" className="mt-3 inline-flex items-center gap-2 rounded-xl bg-cyan-600 px-3 py-2 text-xs font-bold text-white"><Save size={14} />{zh ? '保存' : 'Save'}</button></form>
              {selectedModuleRow && <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="flex items-center justify-between"><div><h2 className="text-sm font-bold text-slate-900">{selectedModuleRow.display_name}</h2><p className="font-mono text-[10px] text-slate-500">{selectedModuleRow.id}</p></div><button type="button" onClick={() => void runAction(`/api/monitoring/modules/${selectedModuleRow.id}/validate`)} className="rounded-lg border border-slate-200 px-2 py-1 text-[10px] font-bold text-slate-600">{zh ? '验证' : 'Validate'}</button></div><div className="mt-4 space-y-2">{moduleVariants.length === 0 ? <p className="text-xs text-slate-400">{zh ? '暂无 Variant' : 'No variants'}</p> : moduleVariants.map(variant => <div key={variant.id} className="rounded-xl border border-slate-100 bg-slate-50 p-3"><div className="flex items-center justify-between gap-2"><span className="font-mono text-xs font-bold text-slate-800">{variant.variant_key}</span><span className={`rounded-full border px-2 py-0.5 text-[9px] font-bold ${statusTone(variant.status)}`}>{variant.status}</span></div><div className="mt-2 text-[10px] text-slate-500">{variant.request_timeout_ms}ms request · {variant.scrape_timeout_ms}ms scrape · max-rep {variant.max_repetitions}</div><div className="mt-2 flex gap-2"><ActionButton icon={<TestTube2 size={12} />} label={zh ? '测试' : 'Test'} onClick={() => void runAction(`/api/monitoring/module-variants/${variant.id}/test`)} /><ActionButton icon={<CheckCircle2 size={12} />} label={zh ? '发布' : 'Publish'} onClick={() => void runAction(`/api/monitoring/module-variants/${variant.id}/publish`)} /></div></div>)}</div><form onSubmit={createVariant} className="mt-4 border-t border-slate-100 pt-4"><p className="mb-2 text-xs font-bold text-slate-800">{zh ? '新增 Variant' : 'Add variant'}</p><div className="grid gap-2 sm:grid-cols-2"><Input label="Variant Key" value={variantForm.variant_key} onChange={value => setVariantForm({ ...variantForm, variant_key: value })} required /><Input label={zh ? '显示名称' : 'Display name'} value={variantForm.display_name} onChange={value => setVariantForm({ ...variantForm, display_name: value })} required /><Input label="Max Repetitions" value={variantForm.max_repetitions} onChange={value => setVariantForm({ ...variantForm, max_repetitions: value })} /><Input label="Request Timeout ms" value={variantForm.request_timeout_ms} onChange={value => setVariantForm({ ...variantForm, request_timeout_ms: value })} /><Input label="Scrape Timeout ms" value={variantForm.scrape_timeout_ms} onChange={value => setVariantForm({ ...variantForm, scrape_timeout_ms: value })} /></div><button type="submit" className="mt-3 rounded-xl bg-cyan-600 px-3 py-2 text-xs font-bold text-white"><Plus size={14} className="mr-1 inline" />{zh ? '保存 Variant' : 'Save variant'}</button></form></div>}
            </aside>
          </div>
        )}
        {mode === 'collectors' && (
          <div className="space-y-5">
            <form onSubmit={createCollector} className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm md:grid-cols-4"><Input label={zh ? '名称' : 'Name'} value={collectorForm.name} onChange={value => setCollectorForm({ ...collectorForm, name: value })} required /><Input label="Code" value={collectorForm.code} onChange={value => setCollectorForm({ ...collectorForm, code: value })} required /><Input label="Site ID" value={collectorForm.site_id} onChange={value => setCollectorForm({ ...collectorForm, site_id: value })} /><button type="submit" className="self-end rounded-xl bg-cyan-600 px-3 py-2 text-xs font-bold text-white"><Plus size={14} className="mr-1 inline" />{zh ? '新增 Collector' : 'Add collector'}</button></form>
            <div className="grid gap-4 lg:grid-cols-2">{collectors.length === 0 && !loading ? <EmptyState zh={zh} label={zh ? '暂无 Collector' : 'No collectors yet'} /> : collectors.map(collector => <button key={collector.id} type="button" onClick={() => setSelectedCollector(collector.id)} className={`rounded-2xl border p-4 text-left transition ${selectedCollectorRow?.id === collector.id ? 'border-cyan-400 bg-cyan-50/60' : 'border-slate-200 bg-white hover:border-cyan-200'}`}><div className="flex items-start justify-between gap-3"><div><p className="font-bold text-slate-900">{collector.name}</p><p className="mt-1 font-mono text-xs text-cyan-700">{collector.code}</p></div><span className={`rounded-full border px-2 py-1 text-[10px] font-bold ${statusTone(collector.status)}`}>{collector.status || 'UNKNOWN'}</span></div><div className="mt-3 flex flex-wrap gap-3 text-[10px] text-slate-500"><span>{collector.collector_type || 'LOCAL'}</span><span>v{collector.last_config_version || '—'}</span><span>{collector.last_config_status || '—'}</span></div></button>)}</div>
            {selectedCollectorRow && <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-sm font-bold text-slate-900">{selectedCollectorRow.name}</h2><p className="font-mono text-[10px] text-slate-500">{selectedCollectorRow.id}</p></div><div className="flex flex-wrap gap-2"><ActionButton icon={<TestTube2 size={13} />} label={zh ? '测试' : 'Test'} onClick={() => void runAction(`/api/monitoring/collectors/${selectedCollectorRow.id}/test`)} /><ActionButton icon={<ShieldCheck size={13} />} label={zh ? '校验' : 'Validate'} onClick={() => void runAction(`/api/monitoring/collectors/${selectedCollectorRow.id}/validate`)} /><ActionButton icon={<CloudCog size={13} />} label={zh ? '编译' : 'Compile'} onClick={() => void runAction(`/api/monitoring/collectors/${selectedCollectorRow.id}/compile`)} /><ActionButton icon={<CheckCircle2 size={13} />} label={zh ? '发布' : 'Publish'} onClick={() => void runAction(`/api/monitoring/collectors/${selectedCollectorRow.id}/publish`)} /><ActionButton icon={<RotateCcw size={13} />} label={zh ? '回滚' : 'Rollback'} onClick={() => void runAction(`/api/monitoring/collectors/${selectedCollectorRow.id}/rollback`)} /></div></div></div>}
          </div>
        )}
        {mode === 'plans' && <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]"><section className="space-y-3">{plans.length === 0 && !loading ? <EmptyState zh={zh} label={zh ? '暂无 Plan' : 'No plans yet'} /> : plans.map(plan => <div key={plan.id} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="flex items-start justify-between gap-3"><div><p className="font-bold text-slate-900">{plan.name}</p><p className="mt-1 text-xs text-cyan-700">{plan.cli_platform || '*'}</p></div><span className={`rounded-full border px-2 py-1 text-[10px] font-bold ${enabled(plan.enabled) ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-slate-200 bg-slate-50 text-slate-500'}`}>{enabled(plan.enabled) ? 'ENABLED' : 'DISABLED'}</span></div><p className="mt-2 text-xs text-slate-500">{plan.description || (zh ? '无描述' : 'No description')}</p><div className="mt-3 flex items-center justify-between text-[10px] text-slate-500"><span>{plan.config?.modules?.length || 0} modules</span><button type="button" onClick={() => void runAction(`/api/monitoring/collection-plans/${plan.id}/compile-test`)} className="rounded-lg border border-slate-200 px-2 py-1 font-bold text-slate-600">{zh ? '编译测试' : 'Compile test'}</button></div></div>)}</section><form onSubmit={createPlan} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="mb-3 flex items-center gap-2"><Database size={16} className="text-cyan-600" /><h2 className="text-sm font-bold text-slate-900">{zh ? '新增 Collection Plan' : 'Add collection plan'}</h2></div><Input label={zh ? '名称' : 'Name'} value={planForm.name} onChange={value => setPlanForm({ ...planForm, name: value })} required /><Input label="CLI Platform" value={planForm.cli_platform} onChange={value => setPlanForm({ ...planForm, cli_platform: value })} /><Input label={zh ? '描述' : 'Description'} value={planForm.description} onChange={value => setPlanForm({ ...planForm, description: value })} /><label className="mt-3 block text-[10px] font-bold uppercase tracking-wide text-slate-500">Config JSON<textarea value={planForm.config} onChange={event => setPlanForm({ ...planForm, config: event.target.value })} rows={10} className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-2 font-mono text-xs outline-none focus:border-cyan-400" /></label><button type="submit" className="mt-3 rounded-xl bg-cyan-600 px-3 py-2 text-xs font-bold text-white"><Save size={14} className="mr-1 inline" />{zh ? '保存 Plan' : 'Save plan'}</button></form></div>}
        {mode === 'health' && <section className="space-y-5"><div className="grid gap-3 sm:grid-cols-3"><MetricCard icon={<Activity size={16} />} label={zh ? 'Assignments' : 'Assignments'} value={health.summary?.total ?? 0} /><MetricCard icon={<CheckCircle2 size={16} />} label={zh ? '健康' : 'Healthy'} value={health.summary?.healthy ?? 0} /><MetricCard icon={<Gauge size={16} />} label={zh ? '健康率' : 'Health ratio'} value={`${Math.round((health.summary?.health_ratio || 0) * 100)}%`} /></div><div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"><div className="grid grid-cols-[1.2fr_1fr_1fr_0.8fr_1fr] gap-3 border-b border-slate-100 bg-slate-50 px-4 py-3 text-[10px] font-bold uppercase tracking-wide text-slate-500"><span>Asset</span><span>Collector</span><span>Module</span><span>Status</span><span>Error / Age</span></div>{(health.items || []).length === 0 ? <div className="p-8 text-center text-xs text-slate-400">{loading ? (zh ? '加载中…' : 'Loading…') : (zh ? '暂无采集 Assignment' : 'No assignments')}</div> : health.items?.map(item => <div key={item.assignment_id} className="grid grid-cols-[1.2fr_1fr_1fr_0.8fr_1fr] gap-3 border-b border-slate-100 px-4 py-3 text-xs text-slate-700 last:border-0"><span className="font-mono">{item.asset_id || '—'}</span><span>{item.collector_id || '—'}</span><span className="truncate font-mono">{item.module_variant_id || '—'}</span><span><span className={`rounded-full border px-2 py-1 text-[10px] font-bold ${statusTone(item.status)}`}>{item.status || 'UNKNOWN'}</span></span><span className="text-[10px] text-slate-500">{item.error_code || (item.age_seconds == null ? '—' : `${Math.round(item.age_seconds)}s`)}</span></div>)}</div></section>}
      </div>
    </div>
  );
};

const Input: React.FC<{ label: string; value: string; onChange: (value: string) => void; required?: boolean }> = ({ label, value, onChange, required }) => <label className="block text-[10px] font-bold uppercase tracking-wide text-slate-500">{label}<input required={required} value={value} onChange={event => onChange(event.target.value)} className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-medium text-slate-800 outline-none focus:border-cyan-400" /></label>;

const ActionButton: React.FC<{ icon: React.ReactNode; label: string; onClick: () => void }> = ({ icon, label, onClick }) => <button type="button" onClick={onClick} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1.5 text-[10px] font-bold text-slate-600 hover:border-cyan-300 hover:text-cyan-700">{icon}{label}</button>;

const MetricCard: React.FC<{ icon: React.ReactNode; label: string; value: string | number }> = ({ icon, label, value }) => <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="flex items-center gap-2 text-xs font-bold text-slate-500">{icon}{label}</div><p className="mt-2 text-2xl font-extrabold text-slate-900">{value}</p></div>;

const EmptyState: React.FC<{ zh: boolean; label: string }> = ({ label }) => <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-12 text-center text-sm text-slate-400">{label}</div>;

export default MonitoringManagementPage;
