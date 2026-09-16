import React, { useCallback, useEffect, useMemo, useState } from 'react';
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
  config?: { modules?: Array<Record<string, unknown>>; target_ips?: string[]; target_scope?: Record<string, unknown> };
  enabled?: boolean | number;
}

interface PlanTestResult {
  valid?: boolean;
  errors?: string[];
  module_count?: number;
  target_count?: number | null;
  targets?: Array<{ id?: string; hostname?: string; ip_address?: string; platform?: string }>;
}

type TargetScopeMode = 'all' | 'composite' | 'ip' | 'site' | 'role' | 'tag';

interface TargetScopeForm {
  mode: TargetScopeMode;
  site: string;
  role: string;
  category: string;
  platform: string;
  ips: string;
  tagIds: string;
}

interface PlanFormState {
  name: string;
  cli_platform: string;
  description: string;
  config: string;
  enabled: boolean;
}

interface ScopeOption {
  value: string;
  label?: string;
  count?: number;
}

interface ScopeOptions {
  sites: ScopeOption[];
  roles: ScopeOption[];
  categories: ScopeOption[];
  platforms: ScopeOption[];
}

interface PlanModuleEntry {
  module: string;
  variant: string;
  enabled: boolean;
  interval: string;
  scrape_timeout: string;
}

const EMPTY_TARGET_SCOPE: TargetScopeForm = {
  mode: 'all', site: '', role: '', category: '', platform: '', ips: '', tagIds: '',
};

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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [modules, setModules] = useState<ModuleRow[]>([]);
  const [variants, setVariants] = useState<VariantRow[]>([]);
  const [collectors, setCollectors] = useState<CollectorRow[]>([]);
  const [plans, setPlans] = useState<PlanRow[]>([]);
  const [planTestResults, setPlanTestResults] = useState<Record<string, PlanTestResult>>({});
  const [scopeOptions, setScopeOptions] = useState<ScopeOptions>({ sites: [], roles: [], categories: [], platforms: [] });
  const [health, setHealth] = useState<HealthPayload>({});
  const [selectedModule, setSelectedModule] = useState('');
  const [selectedCollector, setSelectedCollector] = useState('');
  const [moduleForm, setModuleForm] = useState({ module_key: '', display_name: '', vendor: 'generic', cli_platform: 'generic', metric_group: 'interface', walk_fingerprint: '' });
  const [variantForm, setVariantForm] = useState({ variant_key: '', display_name: '', max_repetitions: '25', request_timeout_ms: '3000', scrape_timeout_ms: '20000' });
  const [collectorForm, setCollectorForm] = useState({ name: '', code: '', site_id: '', collector_type: 'LOCAL' });
  const [editingPlanId, setEditingPlanId] = useState<string | null>(null);
  const [planModuleEntries, setPlanModuleEntries] = useState<PlanModuleEntry[]>([]);
  const [planFormError, setPlanFormError] = useState('');
  const [targetScope, setTargetScope] = useState<TargetScopeForm>({ ...EMPTY_TARGET_SCOPE });
  const [planForm, setPlanForm] = useState<PlanFormState>({ name: '', cli_platform: '*', description: '', config: '{\n  "modules": []\n}', enabled: true });

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
        const [payload, optionsPayload, modulePayload, variantPayload] = await Promise.all([
          request('/api/monitoring/collection-plans'),
          request('/api/collection-plans/bulk-options'),
          request('/api/monitoring/modules'),
          request('/api/monitoring/module-variants'),
        ]);
        setPlans(Array.isArray(payload?.items) ? payload.items : []);
        setModules(Array.isArray(modulePayload?.items) ? modulePayload.items : []);
        setVariants(Array.isArray(variantPayload?.items) ? variantPayload.items : []);
        const data = optionsPayload?.data || optionsPayload || {};
        setScopeOptions({
          sites: Array.isArray(data.sites) ? data.sites : [],
          roles: Array.isArray(data.roles) ? data.roles : [],
          categories: Array.isArray(data.categories) ? data.categories : [],
          platforms: Array.isArray(data.platforms) ? data.platforms : [],
        });
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

  const resetPlanForm = () => {
    setEditingPlanId(null);
    setTargetScope({ ...EMPTY_TARGET_SCOPE });
    setPlanModuleEntries([]);
    setPlanFormError('');
    setPlanForm({ name: '', cli_platform: '*', description: '', config: '{\n  "modules": []\n}', enabled: true });
  };

  const editPlan = (plan: PlanRow) => {
    setEditingPlanId(plan.id);
    setPlanFormError('');
    setPlanModuleEntries(Array.isArray(plan.config?.modules) ? plan.config.modules.map(entry => ({
      module: String(entry.module || entry.module_key || ''),
      variant: String(entry.variant || entry.variant_key || ''),
      enabled: entry.enabled !== false,
      interval: String(entry.interval || '60s'),
      scrape_timeout: String(entry.scrape_timeout || '20s'),
    })) : []);
    const rawScope = plan.config?.target_scope as Record<string, unknown> | undefined;
    const legacyIps = plan.config?.target_ips || [];
    const scopeMode = String(rawScope?.mode || (legacyIps.length ? 'ip' : 'all')) as TargetScopeMode;
    const filters = (rawScope?.filters as Record<string, unknown> | undefined) || {};
    setPlanForm({
      name: plan.name || '',
      cli_platform: plan.cli_platform || '',
      description: plan.description || '',
      config: JSON.stringify(plan.config || { modules: [] }, null, 2),
      enabled: enabled(plan.enabled),
    });
    setTargetScope({
      mode: ['all', 'composite', 'ip', 'site', 'role', 'tag'].includes(scopeMode) ? scopeMode : 'all',
      site: String(rawScope?.value || filters.site || ''),
      role: String(rawScope?.value || filters.role || ''),
      category: String(filters.category || ''),
      platform: String(filters.platform || ''),
      ips: Array.isArray(rawScope?.values) ? rawScope.values.join('\n') : legacyIps.join('\n'),
      tagIds: Array.isArray(rawScope?.tag_ids) ? rawScope.tag_ids.join(',') : '',
    });
  };

  const savePlan = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      if (!planModuleEntries.length) throw new Error(zh ? '至少添加一个采集模块。' : 'Add at least one collection module.');
      const duration = (value: string) => {
        const match = String(value || '').trim().match(/^(\d+(?:\.\d+)?)\s*([smh]?)$/i);
        if (!match) return NaN;
        return Number(match[1]) * ({ '': 1, s: 1, m: 60, h: 3600 }[String(match[2] || '').toLowerCase()] || 1);
      };
      if (planModuleEntries.some(entry => !entry.module || !entry.variant || !Number.isFinite(duration(entry.interval)) || !Number.isFinite(duration(entry.scrape_timeout)) || duration(entry.scrape_timeout) >= duration(entry.interval))) {
        throw new Error(zh ? '请检查模块、Variant、采集间隔和超时：超时必须小于间隔。' : 'Check module, variant, interval, and timeout; timeout must be less than interval.');
      }
      const config = { modules: planModuleEntries, ...(JSON.parse(planForm.config || '{}') || {}) };
      config.modules = planModuleEntries;
      delete config.target_ips;
      delete config.target_scope;
      const serializedScope = serializeTargetScope();
      if (serializedScope) config.target_scope = serializedScope;
      const path = editingPlanId
        ? `/api/monitoring/collection-plans/${editingPlanId}`
        : '/api/monitoring/collection-plans';
      await runAction(path, editingPlanId ? 'PUT' : 'POST', { ...planForm, config });
      resetPlanForm();
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : (zh ? 'Plan 配置无效' : 'Plan configuration is invalid');
      setPlanFormError(message);
      showToast(message, 'error');
    }
  };

  const compileTestPlan = async (planId: string) => {
    try {
      const result = await request(`/api/monitoring/collection-plans/${planId}/compile-test`, { method: 'POST' });
      setPlanTestResults(previous => ({ ...previous, [planId]: result }));
      showToast(result?.valid ? (zh ? '计划编译测试通过' : 'Plan compile test passed') : (zh ? '计划编译测试发现问题' : 'Plan compile test found issues'), result?.valid ? 'success' : 'error');
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setPlanTestResults(previous => ({ ...previous, [planId]: { valid: false, errors: [message] } }));
      showToast(message, 'error');
    }
  };

  const title = mode === 'modules'
    ? (zh ? '模块目录' : 'Module Catalog')
    : mode === 'collectors'
      ? (zh ? '采集器管理' : 'Collectors')
      : mode === 'plans'
        ? (zh ? '采集计划' : 'Collection Plans')
        : (zh ? '采集健康' : 'Collection Health');
  const subtitle = mode === 'modules'
    ? (zh ? '管理 SNMP 模块、变体与发布状态' : 'Manage SNMP modules, variants, and publication state')
    : mode === 'collectors'
      ? (zh ? '编译、发布和回滚采集器配置' : 'Compile, publish, and roll back collector artifacts')
      : mode === 'plans'
        ? (zh ? '从 CMDB 采集计划生成采集分配' : 'Compile assignments from CMDB collection plans')
        : (zh ? '区分设备健康与采集链路健康' : 'Separate device health from collection health');

  const selectedModuleRow = modules.find(item => item.id === selectedModule) || modules[0];
  const selectedCollectorRow = collectors.find(item => item.id === selectedCollector) || collectors[0];
  const moduleVariants = useMemo(() => variants.filter(item => !selectedModuleRow || item.module_id === selectedModuleRow.id), [selectedModuleRow, variants]);
  const planVariantOptions = (moduleKey: string) => {
    const moduleRow = modules.find(item => item.module_key === moduleKey || item.id === moduleKey);
    return variants.filter(item => !moduleRow || item.module_id === moduleRow.id);
  };
  const addPlanModule = () => setPlanModuleEntries(previous => [...previous, { module: '', variant: '', enabled: true, interval: '60s', scrape_timeout: '20s' }]);
  const updatePlanModule = (index: number, patchValue: Partial<PlanModuleEntry>) => setPlanModuleEntries(previous => previous.map((entry, entryIndex) => entryIndex === index ? { ...entry, ...patchValue } : entry));
  const removePlanModule = (index: number) => setPlanModuleEntries(previous => previous.filter((_, entryIndex) => entryIndex !== index));
  const serializeTargetScope = () => {
    const ips = targetScope.ips.split(/[\n,;]+/).map(value => value.trim()).filter(Boolean);
    const tagIds = targetScope.tagIds.split(/[\n,;]+/).map(value => value.trim()).filter(Boolean);
    if (targetScope.mode === 'ip' && ips.length) return { mode: 'ip', values: ips };
    if (targetScope.mode === 'site' && targetScope.site) return { mode: 'site', value: targetScope.site };
    if (targetScope.mode === 'role' && targetScope.role) return { mode: 'role', value: targetScope.role };
    if (targetScope.mode === 'tag' && tagIds.length) return { mode: 'tag', tag_ids: tagIds, match_mode: 'all' };
    if (targetScope.mode === 'composite') {
      const filters = { site: targetScope.site, role: targetScope.role, category: targetScope.category, platform: targetScope.platform };
      if (Object.values(filters).some(Boolean)) return { mode: 'composite', filters };
    }
    return undefined;
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <PageHero
        icon={mode === 'modules' ? Boxes : mode === 'collectors' ? CloudCog : mode === 'plans' ? Layers3 : Gauge}
        title={title}
        subtitle={subtitle}
        actions={<button type="button" onClick={() => void load()} disabled={loading} className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-sm hover:border-cyan-300 disabled:opacity-50"><RefreshCw size={14} className={loading ? 'animate-spin' : ''} />{zh ? '刷新' : 'Refresh'}</button>}
      />
      <div className="min-h-0 flex-1 overflow-auto p-6">
        {error && <div className="mb-4 flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700"><CircleAlert size={16} className="mt-0.5 shrink-0" /><span>{error}</span></div>}
        {mode === 'plans' && <PlanSection zh={zh} plans={plans} loading={loading} planTestResults={planTestResults} editPlan={editPlan} compileTestPlan={compileTestPlan} savePlan={savePlan} editingPlanId={editingPlanId} resetPlanForm={resetPlanForm} planForm={planForm} setPlanForm={setPlanForm} targetScope={targetScope} setTargetScope={setTargetScope} scopeOptions={scopeOptions} planModuleEntries={planModuleEntries} addPlanModule={addPlanModule} updatePlanModule={updatePlanModule} removePlanModule={removePlanModule} planFormError={planFormError} serializeTargetScope={serializeTargetScope} modules={modules} planVariantOptions={planVariantOptions} />}
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
        {mode === 'health' && <section className="space-y-5"><div className="grid gap-3 sm:grid-cols-3"><MetricCard icon={<Activity size={16} />} label={zh ? 'Assignments' : 'Assignments'} value={health.summary?.total ?? 0} /><MetricCard icon={<CheckCircle2 size={16} />} label={zh ? '健康' : 'Healthy'} value={health.summary?.healthy ?? 0} /><MetricCard icon={<Gauge size={16} />} label={zh ? '健康率' : 'Health ratio'} value={`${Math.round((health.summary?.health_ratio || 0) * 100)}%`} /></div><div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"><div className="grid grid-cols-[1.2fr_1fr_1fr_0.8fr_1fr] gap-3 border-b border-slate-100 bg-slate-50 px-4 py-3 text-[10px] font-bold uppercase tracking-wide text-slate-500"><span>Asset</span><span>Collector</span><span>Module</span><span>Status</span><span>Error / Age</span></div>{(health.items || []).length === 0 ? <div className="p-8 text-center text-xs text-slate-400">{loading ? (zh ? '加载中…' : 'Loading…') : (zh ? '暂无采集 Assignment' : 'No assignments')}</div> : health.items?.map(item => <div key={item.assignment_id} className="grid grid-cols-[1.2fr_1fr_1fr_0.8fr_1fr] gap-3 border-b border-slate-100 px-4 py-3 text-xs text-slate-700 last:border-0"><span className="font-mono">{item.asset_id || '—'}</span><span>{item.collector_id || '—'}</span><span className="truncate font-mono">{item.module_variant_id || '—'}</span><span><span className={`rounded-full border px-2 py-1 text-[10px] font-bold ${statusTone(item.status)}`}>{item.status || 'UNKNOWN'}</span></span><span className="text-[10px] text-slate-500">{item.error_code || (item.age_seconds == null ? '—' : `${Math.round(item.age_seconds)}s`)}</span></div>)}</div></section>}
      </div>
    </div>
  );
};

interface PlanSectionProps {
  zh: boolean;
  plans: PlanRow[];
  loading: boolean;
  planTestResults: Record<string, PlanTestResult>;
  editPlan: (plan: PlanRow) => void;
  compileTestPlan: (planId: string) => Promise<void>;
  savePlan: (event: React.FormEvent) => Promise<void>;
  editingPlanId: string | null;
  resetPlanForm: () => void;
  planForm: PlanFormState;
  setPlanForm: React.Dispatch<React.SetStateAction<PlanFormState>>;
  targetScope: TargetScopeForm;
  setTargetScope: React.Dispatch<React.SetStateAction<TargetScopeForm>>;
  scopeOptions: ScopeOptions;
  planModuleEntries: PlanModuleEntry[];
  addPlanModule: () => void;
  updatePlanModule: (index: number, value: Partial<PlanModuleEntry>) => void;
  removePlanModule: (index: number) => void;
  planFormError: string;
  serializeTargetScope: () => Record<string, unknown> | undefined;
  modules: ModuleRow[];
  planVariantOptions: (moduleKey: string) => VariantRow[];
}

const PlanSection: React.FC<PlanSectionProps> = ({
  zh, plans, loading, planTestResults, editPlan, compileTestPlan, savePlan, editingPlanId,
  resetPlanForm, planForm, setPlanForm, targetScope, setTargetScope, scopeOptions,
  planModuleEntries, addPlanModule, updatePlanModule, removePlanModule, planFormError,
  serializeTargetScope, modules, planVariantOptions,
}) => (
  <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_440px]">
    <section className="space-y-3">
      {plans.length === 0 && !loading ? <EmptyState zh={zh} label={zh ? '暂无计划' : 'No plans yet'} /> : plans.map(plan => {
        const testResult = planTestResults[plan.id];
        return <div key={plan.id} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-start justify-between gap-3">
            <div><p className="font-bold text-slate-900">{plan.name}</p><p className="mt-1 text-xs text-cyan-700">{plan.config?.target_scope ? (zh ? '已配置目标范围' : 'Target scope configured') : (zh ? '默认 CMDB 平台匹配' : 'Default CMDB platform matching')}</p></div>
            <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-1 text-[10px] font-bold text-emerald-700">{enabled(plan.enabled) ? (zh ? '已启用' : 'ENABLED') : (zh ? '已停用' : 'DISABLED')}</span>
          </div>
          <p className="mt-2 text-xs text-slate-500">{plan.description || (zh ? '无描述' : 'No description')}</p>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[10px] text-slate-500">
            <span>{plan.config?.modules?.length || 0} {zh ? '个模块' : 'modules'}{plan.config?.target_scope ? ' · ' + (zh ? '已配置范围' : 'scoped') : ''}</span>
            <div className="flex gap-2"><button type="button" onClick={() => editPlan(plan)} className="rounded-lg border border-slate-200 px-2.5 py-1.5 font-bold text-slate-600 hover:border-cyan-300">{zh ? '编辑' : 'Edit'}</button><button type="button" onClick={() => void compileTestPlan(plan.id)} className="rounded-lg border border-cyan-200 bg-cyan-50 px-2.5 py-1.5 font-bold text-cyan-700 hover:border-cyan-300">{zh ? '编译测试' : 'Compile test'}</button></div>
          </div>
          {testResult && <div className={testResult.valid ? 'mt-3 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-[11px] text-emerald-700' : 'mt-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-[11px] text-rose-700'}>
            <div className="font-semibold">{testResult.valid ? (zh ? '测试通过' : 'Test passed') : (zh ? '测试未通过' : 'Test failed')} · {testResult.module_count ?? 0} {zh ? '个模块' : 'modules'}{testResult.target_count != null ? ' · ' + testResult.target_count + ' ' + (zh ? '个目标' : 'targets') : ''}</div>
            {testResult.errors?.length ? <ul className="mt-1 list-disc pl-4">{testResult.errors.map(errorItem => <li key={errorItem}>{errorItem}</li>)}</ul> : <div className="mt-1">{zh ? '模块、变体、目标和超时参数校验通过' : 'Modules, targets, and timeout validation passed'}</div>}
            {testResult.targets?.length ? <div className="mt-1 font-mono text-[10px]">{testResult.targets.map(target => (target.hostname || target.id || '') + ' (' + (target.ip_address || '—') + ')').join(' · ')}</div> : null}
          </div>}
        </div>;
      })}
    </section>
    <form onSubmit={savePlan} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-2"><div className="flex items-center gap-2"><Database size={16} className="text-cyan-600" /><h2 className="text-sm font-bold text-slate-900">{editingPlanId ? (zh ? '编辑采集计划' : 'Edit collection plan') : (zh ? '新增采集计划' : 'Add collection plan')}</h2></div>{editingPlanId && <button type="button" onClick={resetPlanForm} className="rounded-lg border border-slate-200 px-2 py-1 text-[10px] font-bold text-slate-600">{zh ? '取消' : 'Cancel'}</button>}</div>
      <div className="space-y-3">
        <Input label={zh ? '名称' : 'Name'} value={planForm.name} onChange={value => setPlanForm({ ...planForm, name: value })} required />
        <label className="block text-[10px] font-bold uppercase tracking-wide text-slate-500">{zh ? '目标范围' : 'Target scope'}<select value={targetScope.mode} onChange={event => setTargetScope({ ...targetScope, mode: event.target.value as TargetScopeMode })} className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-medium text-slate-800 outline-none focus:border-cyan-400"><option value="all">{zh ? '全部在线设备' : 'All online devices'}</option><option value="composite">{zh ? '复合筛选（站点/角色/类型/平台）' : 'Combined filters (site/role/type/platform)'}</option><option value="ip">{zh ? '指定 IP / 设备清单' : 'IP / device list'}</option><option value="site">{zh ? '按单个站点' : 'Single site'}</option><option value="role">{zh ? '按单个角色' : 'Single role'}</option><option value="tag">{zh ? '按标签（Tag IDs）' : 'By tags (Tag IDs)'}</option></select></label>
        {targetScope.mode === 'composite' && <div className="grid gap-2 rounded-xl border border-slate-100 bg-slate-50 p-3 sm:grid-cols-2">{([['site', zh ? '站点' : 'Site', scopeOptions.sites], ['role', zh ? '角色' : 'Role', scopeOptions.roles], ['category', zh ? '设备类型' : 'Type', scopeOptions.categories], ['platform', zh ? '平台' : 'Platform', scopeOptions.platforms]] as const).map(([key, label, options]) => <label key={key} className="text-[10px] font-bold text-slate-500">{label}<select value={targetScope[key]} onChange={event => setTargetScope({ ...targetScope, [key]: event.target.value })} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2 py-2 text-xs font-normal text-slate-700"><option value="">{zh ? '不限' : 'Any'}</option>{options.map(option => <option key={option.value} value={option.value}>{option.label || option.value} ({option.count ?? 0})</option>)}</select></label>)}</div>}
        {targetScope.mode === 'ip' && <textarea value={targetScope.ips} onChange={event => setTargetScope({ ...targetScope, ips: event.target.value })} rows={3} placeholder={zh ? '每行一个 IP，必须已存在于 CMDB' : 'One IP per line; must already exist in CMDB'} className="w-full resize-y rounded-xl border border-slate-200 bg-slate-50 p-2 font-mono text-xs outline-none focus:border-cyan-400" />}
        {targetScope.mode === 'site' && <select value={targetScope.site} onChange={event => setTargetScope({ ...targetScope, site: event.target.value })} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs"><option value="">{zh ? '请选择站点' : 'Select site'}</option>{scopeOptions.sites.map(option => <option key={option.value} value={option.value}>{option.label || option.value} ({option.count ?? 0})</option>)}</select>}
        {targetScope.mode === 'role' && <select value={targetScope.role} onChange={event => setTargetScope({ ...targetScope, role: event.target.value })} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs"><option value="">{zh ? '请选择角色' : 'Select role'}</option>{scopeOptions.roles.map(option => <option key={option.value} value={option.value}>{option.value} ({option.count ?? 0})</option>)}</select>}
        {targetScope.mode === 'tag' && <textarea value={targetScope.tagIds} onChange={event => setTargetScope({ ...targetScope, tagIds: event.target.value })} rows={2} placeholder={zh ? '填写标签 ID，逗号分隔' : 'Tag IDs separated by commas'} className="w-full resize-y rounded-xl border border-slate-200 bg-slate-50 p-2 font-mono text-xs outline-none focus:border-cyan-400" />}
        <div className="flex items-center justify-between"><span className="text-xs font-bold text-slate-700">{zh ? '模块配置' : 'Module configuration'}</span><button type="button" onClick={addPlanModule} className="inline-flex items-center gap-2 rounded-xl border border-cyan-200 bg-cyan-50 px-3 py-2 text-xs font-bold text-cyan-700 hover:border-cyan-300"><Plus size={14} />{zh ? '添加模块' : 'Add module'}</button></div>
        {planModuleEntries.map((entry, index) => <div key={index + '-' + entry.module} className="rounded-xl border border-slate-200 bg-slate-50 p-3"><div className="mb-2 flex items-center justify-between"><span className="text-xs font-bold text-slate-700">{zh ? '模块 ' + (index + 1) : 'Module ' + (index + 1)}</span><button type="button" onClick={() => removePlanModule(index)} className="text-xs font-semibold text-rose-600">{zh ? '移除' : 'Remove'}</button></div><div className="grid gap-2 sm:grid-cols-2"><label className="text-[10px] font-bold text-slate-500">{zh ? '模块' : 'Module'}<select value={entry.module} onChange={event => updatePlanModule(index, { module: event.target.value, variant: '' })} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2 py-2 text-xs"><option value="">{zh ? '请选择模块' : 'Select module'}</option>{modules.map(module => <option key={module.module_key} value={module.module_key}>{module.display_name || module.module_key}</option>)}</select></label><label className="text-[10px] font-bold text-slate-500">Variant<select value={entry.variant} onChange={event => updatePlanModule(index, { variant: event.target.value })} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2 py-2 text-xs"><option value="">{zh ? '请选择 Variant' : 'Select variant'}</option>{planVariantOptions(entry.module).map(variant => <option key={variant.variant_key} value={variant.variant_key}>{variant.display_name || variant.variant_key} · {variant.status}</option>)}</select></label><Input label={zh ? '采集间隔' : 'Interval'} value={entry.interval} onChange={value => updatePlanModule(index, { interval: value })} /><Input label={zh ? '超时' : 'Timeout'} value={entry.scrape_timeout} onChange={value => updatePlanModule(index, { scrape_timeout: value })} /></div></div>)}
        {planFormError && <div className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">{planFormError}</div>}
        <details className="rounded-xl border border-slate-200 bg-slate-50 p-3"><summary className="cursor-pointer text-xs font-bold text-slate-600">{zh ? '高级 Config JSON 预览（只读）' : 'Advanced Config JSON preview (read-only)'}</summary><pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-white p-3 font-mono text-[10px] leading-5 text-slate-600">{JSON.stringify({ modules: planModuleEntries, ...(serializeTargetScope() ? { target_scope: serializeTargetScope() } : {}) }, null, 2)}</pre></details>
        <Input label={zh ? '描述' : 'Description'} value={planForm.description} onChange={value => setPlanForm({ ...planForm, description: value })} />
      </div>
      <button type="submit" className="mt-4 inline-flex items-center gap-2 rounded-xl bg-cyan-600 px-4 py-2 text-xs font-bold text-white shadow-sm hover:bg-cyan-700"><Save size={14} />{editingPlanId ? (zh ? '保存修改' : 'Save changes') : (zh ? '保存计划' : 'Save plan')}</button>
    </form>
  </div>
);

const Input: React.FC<{ label: string; value: string; onChange: (value: string) => void; required?: boolean }> = ({ label, value, onChange, required }) => <label className="block text-[10px] font-bold uppercase tracking-wide text-slate-500">{label}<input required={required} value={value} onChange={event => onChange(event.target.value)} className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-medium text-slate-800 outline-none focus:border-cyan-400" /></label>;

const ActionButton: React.FC<{ icon: React.ReactNode; label: string; onClick: () => void }> = ({ icon, label, onClick }) => <button type="button" onClick={onClick} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1.5 text-[10px] font-bold text-slate-600 hover:border-cyan-300 hover:text-cyan-700">{icon}{label}</button>;

const MetricCard: React.FC<{ icon: React.ReactNode; label: string; value: string | number }> = ({ icon, label, value }) => <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="flex items-center gap-2 text-xs font-bold text-slate-500">{icon}{label}</div><p className="mt-2 text-2xl font-extrabold text-slate-900">{value}</p></div>;

const EmptyState: React.FC<{ zh: boolean; label: string }> = ({ label }) => <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-12 text-center text-sm text-slate-400">{label}</div>;

export default MonitoringManagementPage;
