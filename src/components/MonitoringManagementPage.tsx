import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity, Boxes, CheckCircle2, CircleAlert, CloudCog, Copy, Database,
  Eye, Gauge, Layers3, Pencil, Plus, RefreshCw, RotateCcw, Save, Search,
  Server, ShieldCheck, SlidersHorizontal, TestTube2, Trash2, X, XCircle,
} from 'lucide-react';
import PageHero from './PageHero';
import Pagination from './Pagination';
import { useEscapeClose } from '../hooks/useEscapeClose';

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
  supported_platforms?: string[];
  supported_models?: string[];
  supported_version_scope?: string[];
  status?: string;
  enabled?: boolean | number;
  oid_config?: Record<string, unknown>;
  oid_config_json?: string;
  mib_bundle_id?: string;
  generator_version?: string;
  generator_config_hash?: string;
  mib_hash?: string;
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
  created_at?: string;
  updated_at?: string;
  is_canonical?: boolean;
  coverage?: { target_count?: number; unmatched_online_devices?: number; variant_hits?: Record<string, number> };
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
  vendor?: string | string[];
  platform?: string | string[];
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
  last_attempt_at?: string | null;
  duration_ms?: number | null;
  consecutive_failures?: number;
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

const variantOidConfig = (variant: VariantRow): Record<string, unknown> => {
  if (variant.oid_config && typeof variant.oid_config === 'object') return variant.oid_config;
  try {
    const parsed = JSON.parse(String(variant.oid_config_json || '{}'));
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
};

const variantOidCount = (variant: VariantRow) => {
  const config = variantOidConfig(variant);
  const walks = Array.isArray(config.walk) ? config.walk.length : 0;
  const gets = Array.isArray(config.get) ? config.get.length : 0;
  const metrics = Array.isArray(config.metrics) ? config.metrics.length : 0;
  return { walks, gets, metrics };
};

type VariantJsonValidationState = 'idle' | 'valid' | 'invalid';

interface VariantJsonValidation {
  state: VariantJsonValidationState;
  message: string;
  config?: Record<string, unknown>;
}

const parseVariantOidConfig = (raw: string, zh: boolean): VariantJsonValidation => {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw || '{}');
  } catch (reason) {
    const detail = reason instanceof Error ? reason.message : String(reason);
    return { state: 'invalid', message: zh ? `JSON 格式错误：${detail}` : `Invalid JSON: ${detail}` };
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return { state: 'invalid', message: zh ? 'JSON 顶层必须是对象。' : 'The JSON root must be an object.' };
  }
  const config = parsed as Record<string, unknown>;
  for (const key of ['walk', 'get', 'metrics'] as const) {
    if (config[key] !== undefined && !Array.isArray(config[key])) {
      return { state: 'invalid', message: zh ? `${key} 必须是数组。` : `${key} must be an array.` };
    }
  }
  const walks = Array.isArray(config.walk) ? config.walk : [];
  const gets = Array.isArray(config.get) ? config.get : [];
  const metrics = Array.isArray(config.metrics) ? config.metrics : [];
  if (!walks.length && !gets.length) {
    return { state: 'invalid', message: zh ? '至少配置一个 walk 或 get OID。' : 'Configure at least one walk or get OID.' };
  }
  if (!metrics.length) {
    return { state: 'invalid', message: zh ? '至少配置一个指标。' : 'Configure at least one metric.' };
  }
  const oidPattern = /^(?:\.?\d+(?:\.\d+)+|[A-Za-z][A-Za-z0-9_-]*::[A-Za-z][A-Za-z0-9_-]*(?:\.\d+)*)$/;
  const invalidOid = [...walks, ...gets].find(value => typeof value !== 'string' || !oidPattern.test(value.trim()));
  if (invalidOid !== undefined) {
    return { state: 'invalid', message: zh ? `OID 格式无效：${String(invalidOid)}` : `Invalid OID: ${String(invalidOid)}` };
  }
  const invalidMetric = metrics.find(item => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return true;
    const metric = item as Record<string, unknown>;
    const metricNamePattern = /^[a-zA-Z_:][a-zA-Z0-9_:]*$/;
    return typeof metric.name !== 'string' || !metricNamePattern.test(metric.name.trim()) || typeof metric.oid !== 'string' || !oidPattern.test(metric.oid.trim());
  });
  if (invalidMetric) {
    return { state: 'invalid', message: zh ? '每个指标都必须包含合法的 name 和 OID。' : 'Each metric must include a valid name and OID.' };
  }
  return {
    state: 'valid',
    config,
    message: zh ? `JSON 格式正确 · ${walks.length + gets.length} 个 OID · ${metrics.length} 个指标` : `JSON is valid · ${walks.length + gets.length} OIDs · ${metrics.length} metrics`,
  };
};

const statusTone = (status: string | undefined) => {
  const normalized = String(status || '').toUpperCase();
  if (['OK', 'ONLINE', 'PUBLISHED', 'APPLIED', 'SUCCESS', 'PASS', 'TESTED'].includes(normalized)) return 'text-emerald-700 bg-emerald-50 border-emerald-200';
  if (['FAILED', 'OFFLINE', 'MISMATCH', 'ERROR'].includes(normalized)) return 'text-rose-700 bg-rose-50 border-rose-200';
  return 'text-amber-700 bg-amber-50 border-amber-200';
};

const displayStatus = (status: string | undefined, zh: boolean) => {
  const normalized = String(status || '').toUpperCase();
  if (!zh) return normalized || 'UNKNOWN';
  const labels: Record<string, string> = { PUBLISHED: '已发布', TESTED: '已测试', DRAFT: '草稿', ENABLED: '已启用', DISABLED: '已停用', ONLINE: '在线', OFFLINE: '离线', OK: '正常', PASS: '通过', SUCCESS: '成功', FAILED: '失败', ERROR: '异常', UNKNOWN: '未知', COMPILED: '已编译', APPLIED: '已应用' };
  return labels[normalized] || normalized || '未知';
};

const displayCollectorType = (collectorType: string | undefined, zh: boolean) => {
  const normalized = String(collectorType || 'LOCAL').toUpperCase();
  if (!zh) return normalized;
  return ({ LOCAL: '本地', REMOTE: '远程', EDGE: '边缘' } as Record<string, string>)[normalized] || normalized;
};

const MonitoringManagementPage: React.FC<MonitoringManagementPageProps> = ({ language, mode, showToast }) => {
  const zh = language === 'zh';
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [modules, setModules] = useState<ModuleRow[]>([]);
  const [variants, setVariants] = useState<VariantRow[]>([]);
  const [collectors, setCollectors] = useState<CollectorRow[]>([]);
  const [plans, setPlans] = useState<PlanRow[]>([]);
  const [planPreview, setPlanPreview] = useState<PlanRow | null>(null);
  const [planTestResults, setPlanTestResults] = useState<Record<string, PlanTestResult>>({});
  const [scopeOptions, setScopeOptions] = useState<ScopeOptions>({ sites: [], roles: [], categories: [], platforms: [] });
  const [health, setHealth] = useState<HealthPayload>({});
  const [selectedModule, setSelectedModule] = useState('');
  const [selectedCollector, setSelectedCollector] = useState('');
  const [moduleForm, setModuleForm] = useState({ module_key: '', display_name: '', vendor: 'generic', cli_platform: 'generic', metric_group: 'interface', walk_fingerprint: '' });
  const [variantForm, setVariantForm] = useState({ variant_key: '', display_name: '', max_repetitions: '25', request_timeout_ms: '3000', scrape_timeout_ms: '20000', oid_config: '{\n  "walk": [],\n  "get": [],\n  "metrics": []\n}' });
  const [collectorForm, setCollectorForm] = useState({ name: '', code: '', site_id: '', collector_type: 'LOCAL' });
  const [editingPlanId, setEditingPlanId] = useState<string | null>(null);
  const [planEditorOpen, setPlanEditorOpen] = useState(false);
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
      return true;
    } catch (reason) {
      showToast(reason instanceof Error ? reason.message : String(reason), 'error');
      return false;
    }
  }, [load, request, showToast, zh]);

  const createModule = async (event: React.FormEvent) => {
    event.preventDefault();
    if (await runAction('/api/monitoring/modules', 'POST', moduleForm)) setModuleForm({ module_key: '', display_name: '', vendor: 'generic', cli_platform: 'generic', metric_group: 'interface', walk_fingerprint: '' });
  };

  const createVariant = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selectedModuleRow) return;
    if (await runAction('/api/monitoring/module-variants', 'POST', {
      module_id: selectedModuleRow.id,
      variant_key: variantForm.variant_key,
      display_name: variantForm.display_name,
      max_repetitions: Number(variantForm.max_repetitions) || 25,
      request_timeout_ms: Number(variantForm.request_timeout_ms) || 3000,
      scrape_timeout_ms: Number(variantForm.scrape_timeout_ms) || 20000,
      oid_config: JSON.parse(variantForm.oid_config || '{}'),
      status: 'DRAFT',
      enabled: true,
    })) setVariantForm({ variant_key: '', display_name: '', max_repetitions: '25', request_timeout_ms: '3000', scrape_timeout_ms: '20000', oid_config: '{\n  "walk": [],\n  "get": [],\n  "metrics": []\n}' });
  };

  const createCollector = async (event: React.FormEvent) => {
    event.preventDefault();
    if (await runAction('/api/monitoring/collectors', 'POST', collectorForm)) setCollectorForm({ name: '', code: '', site_id: '', collector_type: 'LOCAL' });
  };

  const resetPlanForm = () => {
    setEditingPlanId(null);
    setPlanEditorOpen(false);
    setTargetScope({ ...EMPTY_TARGET_SCOPE });
    setPlanModuleEntries([]);
    setPlanFormError('');
    setPlanForm({ name: '', cli_platform: '*', description: '', config: '{\n  "modules": []\n}', enabled: true });
  };

  const editPlan = (plan: PlanRow) => {
    setEditingPlanId(plan.id);
    setPlanEditorOpen(true);
    setPlanFormError('');
    setPlanModuleEntries(Array.isArray(plan.config?.modules) ? plan.config.modules.map(entry => ({
      module: String(entry.module || entry.module_key || ''),
      variant: String(entry.variant || entry.variant_key || ''),
      enabled: entry.enabled !== false,
      interval: String(entry.interval || '60s'),
      scrape_timeout: String(entry.scrape_timeout || '20s'),
      vendor: entry.vendor as string | string[] | undefined,
      platform: entry.platform as string | string[] | undefined,
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
      const saved = await request(path, { method: editingPlanId ? 'PUT' : 'POST', body: JSON.stringify({ ...planForm, config }) });
      const savedId = String(saved?.id || editingPlanId || '');
      if (!savedId) throw new Error(zh ? '保存成功但未返回计划 ID。' : 'The saved plan did not return an id.');
      try {
        await request(`/api/monitoring/collection-plans/${encodeURIComponent(savedId)}/apply`, { method: 'POST' });
        showToast(zh ? '计划已保存并生效' : 'Plan saved and applied', 'success');
      } catch (applyReason) {
        const applyMessage = applyReason instanceof Error ? applyReason.message : String(applyReason);
        showToast(zh ? `计划已保存，但生效失败：${applyMessage}` : `Plan saved, but apply failed: ${applyMessage}`, 'error');
      }
      await load();
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

  const applyPlan = async (planId: string) => {
    try {
      await request(`/api/monitoring/collection-plans/${encodeURIComponent(planId)}/apply`, { method: 'POST' });
      showToast(zh ? '计划已生效' : 'Plan applied', 'success');
      await load();
    } catch (reason) {
      showToast(reason instanceof Error ? reason.message : String(reason), 'error');
    }
  };

  const openCreatePlan = () => {
    resetPlanForm();
    setPlanEditorOpen(true);
  };

  const viewPlan = async (plan: PlanRow) => {
    try {
      const result = await request(`/api/monitoring/collection-plans/${encodeURIComponent(plan.id)}/preview`);
      setPlanPreview(result?.plan || plan);
    } catch (reason) {
      showToast(reason instanceof Error ? reason.message : String(reason), 'error');
    }
  };

  const deletePlan = async (plan: PlanRow) => {
    const confirmed = window.confirm(zh
      ? `确定删除“${plan.name}”吗？该计划生成的采集分配也会一并删除。`
      : `Delete “${plan.name}”? Its generated collection assignments will also be removed.`);
    if (!confirmed) return;
    try {
      await request(`/api/monitoring/collection-plans/${plan.id}`, { method: 'DELETE' });
      if (editingPlanId === plan.id) resetPlanForm();
      if (planPreview?.id === plan.id) setPlanPreview(null);
      showToast(zh ? '计划已删除' : 'Plan deleted', 'success');
      await load();
    } catch (reason) {
      showToast(reason instanceof Error ? reason.message : String(reason), 'error');
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
    ? (zh ? '管理 SNMP 采集模块、采集版本与发布状态' : 'Manage SNMP collection modules, variants, and publication state')
    : mode === 'collectors'
      ? (zh ? '管理采集器连接、配置发布与运行状态' : 'Manage collector connections, configuration, and runtime status')
      : mode === 'plans'
        ? (zh ? '从 CMDB 采集计划生成采集分配' : 'Compile assignments from CMDB collection plans')
        : (zh ? '区分设备健康与采集链路健康' : 'Separate device health from collection health');

  const selectedModuleRow = modules.find(item => item.id === selectedModule) || modules[0];
  const selectedCollectorRow = collectors.find(item => item.id === selectedCollector) || collectors[0];
  const moduleVariants = useMemo(() => variants.filter(item => !selectedModuleRow || item.module_id === selectedModuleRow.id), [selectedModuleRow, variants]);
  const planVariantOptions = (moduleKey: string) => {
    if (!moduleKey) return [];
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
       actions={<div className="flex items-center gap-2">{mode === 'plans' && <button type="button" onClick={openCreatePlan} className="inline-flex items-center gap-2 rounded-xl bg-cyan-600 px-3 py-2 text-xs font-bold text-white shadow-sm hover:bg-cyan-700"><Plus size={14} />{zh ? '新建例外计划' : 'New exception plan'}</button>}<button type="button" onClick={() => void load()} disabled={loading} className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-sm hover:border-cyan-300 disabled:opacity-50"><RefreshCw size={14} className={loading ? 'animate-spin' : ''} />{zh ? '刷新' : 'Refresh'}</button></div>}
      />
      <div className="min-h-0 flex-1 overflow-auto p-6">
        {error && <div className="mb-4 flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700"><CircleAlert size={16} className="mt-0.5 shrink-0" /><span>{error}</span></div>}
        {mode === 'plans' && <PlanSection zh={zh} plans={plans} loading={loading} planTestResults={planTestResults} editPlan={editPlan} viewPlan={viewPlan} planPreview={planPreview} closePlanPreview={() => setPlanPreview(null)} deletePlan={deletePlan} compileTestPlan={compileTestPlan} applyPlan={applyPlan} savePlan={savePlan} editingPlanId={editingPlanId} planEditorOpen={planEditorOpen} resetPlanForm={resetPlanForm} planForm={planForm} setPlanForm={setPlanForm} targetScope={targetScope} setTargetScope={setTargetScope} scopeOptions={scopeOptions} planModuleEntries={planModuleEntries} addPlanModule={addPlanModule} updatePlanModule={updatePlanModule} removePlanModule={removePlanModule} planFormError={planFormError} serializeTargetScope={serializeTargetScope} modules={modules} planVariantOptions={planVariantOptions} />}
        {mode === 'modules' && <ModuleCatalogSection zh={zh} modules={modules} variants={variants} loading={loading} runAction={runAction} showToast={showToast} />}
        {mode === 'collectors' && <CollectorManagementSection zh={zh} collectors={collectors} loading={loading} runAction={runAction} />}
        {mode === 'health' && <CollectionHealthSection zh={zh} health={health} loading={loading} />}
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
  viewPlan: (plan: PlanRow) => Promise<void>;
  planPreview: PlanRow | null;
  closePlanPreview: () => void;
  deletePlan: (plan: PlanRow) => Promise<void>;
  compileTestPlan: (planId: string) => Promise<void>;
  applyPlan: (planId: string) => Promise<void>;
  savePlan: (event: React.FormEvent) => Promise<void>;
  editingPlanId: string | null;
  planEditorOpen: boolean;
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

const formatPlanDate = (value: string | undefined, zh: boolean) => {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat(zh ? 'zh-CN' : 'en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(date);
};

const planScopeLabel = (plan: PlanRow, zh: boolean) => {
  const scope = plan.config?.target_scope;
  if (!scope) return zh ? '全部在线设备' : 'All online devices';
  const mode = String(scope.mode || '');
  if (mode === 'ip') return zh ? `指定 ${Array.isArray(scope.values) ? scope.values.length : 0} 个地址` : `${Array.isArray(scope.values) ? scope.values.length : 0} addresses`;
  if (mode === 'site') return `${zh ? '站点' : 'Site'}: ${String(scope.value || '—')}`;
  if (mode === 'role') return `${zh ? '角色' : 'Role'}: ${String(scope.value || '—')}`;
  if (mode === 'tag') return zh ? '按标签匹配' : 'Tag matching';
  if (mode === 'composite') return zh ? '复合条件筛选' : 'Combined filters';
  return zh ? '全部在线设备' : 'All online devices';
};

const PlanSection: React.FC<PlanSectionProps> = ({
  zh, plans, loading, planTestResults, editPlan, viewPlan, planPreview, closePlanPreview,
  deletePlan, compileTestPlan, applyPlan, savePlan, editingPlanId, planEditorOpen,
  resetPlanForm, planForm, setPlanForm, targetScope, setTargetScope, scopeOptions,
  planModuleEntries, addPlanModule, updatePlanModule, removePlanModule, planFormError,
  serializeTargetScope, modules, planVariantOptions,
}) => {
  useEscapeClose(planEditorOpen, resetPlanForm);
  useEscapeClose(Boolean(planPreview), closePlanPreview);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'enabled' | 'disabled'>('all');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const query = search.trim().toLowerCase();
  const visiblePlans = plans.filter(plan => {
    const matchesSearch = !query || [plan.name, plan.description, plan.cli_platform, planScopeLabel(plan, zh)].some(value => String(value || '').toLowerCase().includes(query));
    const matchesStatus = statusFilter === 'all' || (statusFilter === 'enabled' ? enabled(plan.enabled) : !enabled(plan.enabled));
    return matchesSearch && matchesStatus;
  });
  const enabledCount = plans.filter(plan => enabled(plan.enabled)).length;
  const disabledCount = plans.length - enabledCount;
  const failedCount = plans.filter(plan => planTestResults[plan.id] && planTestResults[plan.id].valid === false).length;
  const totalPages = Math.max(1, Math.ceil(visiblePlans.length / pageSize));
  const pagedPlans = visiblePlans.slice((page - 1) * pageSize, page * pageSize);
  useEffect(() => { setPage(1); }, [pageSize, search, statusFilter]);
  useEffect(() => { setPage(current => Math.min(current, totalPages)); }, [totalPages]);

  return <>
    <section className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <PlanStat label={zh ? '全部计划' : 'All plans'} value={plans.length} tone="slate" />
        <PlanStat label={zh ? '已启用' : 'Enabled'} value={enabledCount} tone="emerald" />
        <PlanStat label={zh ? '已停用' : 'Disabled'} value={disabledCount} tone="amber" />
        <PlanStat label={zh ? '最近测试异常' : 'Test issues'} value={failedCount} tone="rose" />
      </div>
      <div className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-3 shadow-sm md:flex-row md:items-center md:justify-between">
        <div className="relative min-w-0 flex-1 md:max-w-md"><Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" /><input value={search} onChange={event => setSearch(event.target.value)} placeholder={zh ? '搜索计划名称、描述或目标范围' : 'Search name, description, or scope'} className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2 pl-9 pr-3 text-xs text-slate-800 outline-none transition focus:border-cyan-400 focus:bg-white" /></div>
        <div className="flex flex-wrap items-center gap-2"><div className="flex items-center gap-1.5 text-xs font-semibold text-slate-500"><SlidersHorizontal size={14} />{zh ? '状态' : 'Status'}</div><select value={statusFilter} onChange={event => setStatusFilter(event.target.value as typeof statusFilter)} className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700"><option value="all">{zh ? '全部' : 'All'}</option><option value="enabled">{zh ? '已启用' : 'Enabled'}</option><option value="disabled">{zh ? '已停用' : 'Disabled'}</option></select>{(search || statusFilter !== 'all') && <button type="button" onClick={() => { setSearch(''); setStatusFilter('all'); }} className="inline-flex items-center gap-1 rounded-xl px-2.5 py-2 text-xs font-semibold text-slate-500 hover:bg-slate-100"><X size={13} />{zh ? '重置' : 'Reset'}</button>}<span className="text-xs text-slate-400">{zh ? `${visiblePlans.length} / ${plans.length} 个计划` : `${visiblePlans.length} / ${plans.length} plans`}</span></div>
      </div>
      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="hidden grid-cols-[minmax(220px,1.6fr)_1.35fr_0.65fr_0.9fr_0.9fr_220px] gap-3 border-b border-slate-100 bg-slate-50 px-5 py-3 text-[10px] font-bold uppercase tracking-wide text-slate-500 lg:grid"><span>{zh ? '计划' : 'Plan'}</span><span>{zh ? '目标范围' : 'Scope'}</span><span>{zh ? '模块' : 'Modules'}</span><span>{zh ? '状态' : 'Status'}</span><span>{zh ? '最近更新' : 'Updated'}</span><span className="text-right">{zh ? '操作' : 'Actions'}</span></div>
        {loading && <div className="flex items-center justify-center gap-2 p-10 text-xs text-slate-400"><RefreshCw size={14} className="animate-spin" />{zh ? '正在加载计划…' : 'Loading plans…'}</div>}
        {!loading && plans.length === 0 && <EmptyState zh={zh} label={zh ? '还没有采集计划，点击右上角新建。' : 'No collection plans yet. Create one to get started.'} />}
        {!loading && plans.length > 0 && visiblePlans.length === 0 && <EmptyState zh={zh} label={zh ? '没有匹配当前筛选条件的计划。' : 'No plans match the current filters.'} />}
        {!loading && pagedPlans.map(plan => {
          const testResult = planTestResults[plan.id];
          return <div key={plan.id} className="grid gap-3 border-b border-slate-100 px-5 py-4 transition last:border-0 hover:bg-cyan-50/30 lg:grid-cols-[minmax(220px,1.6fr)_1.35fr_0.65fr_0.9fr_0.9fr_220px] lg:items-center">
            <div className="min-w-0"><div className="flex items-center gap-2"><p className="truncate text-sm font-bold text-slate-900">{plan.name}</p>{testResult && <span className={`rounded-full border px-1.5 py-0.5 text-[9px] font-bold ${testResult.valid ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-rose-200 bg-rose-50 text-rose-700'}`}>{testResult.valid ? (zh ? '测试通过' : 'PASS') : (zh ? '需处理' : 'ISSUE')}</span>}</div><p className="mt-1 truncate text-[11px] text-slate-500">{plan.description || (zh ? '暂无描述' : 'No description')}</p></div>
            <div className="text-xs text-slate-600"><span className="mr-2 text-[10px] font-bold text-slate-400 lg:hidden">{zh ? '范围' : 'Scope'}:</span>{planScopeLabel(plan, zh)}</div>
            <div className="text-xs font-semibold text-slate-700"><span className="mr-2 text-[10px] font-bold text-slate-400 lg:hidden">{zh ? '模块' : 'Modules'}:</span>{plan.config?.modules?.length || 0}</div>
            <div><span className="mr-2 text-[10px] font-bold text-slate-400 lg:hidden">{zh ? '状态' : 'Status'}:</span><span className={`inline-flex rounded-full border px-2 py-1 text-[10px] font-bold ${enabled(plan.enabled) ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-slate-200 bg-slate-100 text-slate-500'}`}>{enabled(plan.enabled) ? (zh ? '已启用' : 'ENABLED') : (zh ? '已停用' : 'DISABLED')}</span></div>
            <div className="text-xs text-slate-500"><span className="mr-2 text-[10px] font-bold text-slate-400 lg:hidden">{zh ? '更新' : 'Updated'}:</span>{formatPlanDate(plan.updated_at || plan.created_at, zh)}</div>
             <div className="flex flex-nowrap items-center justify-end gap-1"><button type="button" aria-label={zh ? '查看计划' : 'View plan'} title={zh ? '查看计划' : 'View plan'} onClick={() => void viewPlan(plan)} className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 text-slate-600 hover:border-cyan-300 hover:text-cyan-700"><Eye size={15} /></button><button type="button" aria-label={zh ? '编辑计划' : 'Edit plan'} title={zh ? '编辑计划' : 'Edit plan'} onClick={() => editPlan(plan)} className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 text-slate-600 hover:border-cyan-300 hover:text-cyan-700"><Pencil size={15} /></button><button type="button" aria-label={zh ? '校验计划' : 'Validate plan'} title={zh ? '校验计划' : 'Validate plan'} onClick={() => void compileTestPlan(plan.id)} className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-cyan-200 bg-cyan-50 text-cyan-700 hover:border-cyan-300"><ShieldCheck size={15} /></button><button type="button" aria-label={zh ? '立即生效' : 'Apply plan'} title={zh ? '立即生效' : 'Apply plan'} onClick={() => void applyPlan(plan.id)} className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-emerald-200 bg-emerald-50 text-emerald-700 hover:border-emerald-300"><CheckCircle2 size={15} /></button><button type="button" aria-label={zh ? '删除计划' : 'Delete plan'} title={zh ? '删除计划' : 'Delete plan'} disabled={plan.is_canonical} onClick={() => void deletePlan(plan)} className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-rose-600 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-30"><Trash2 size={15} /></button></div>
          </div>;
        })}
        {visiblePlans.length > 0 && <Pagination currentPage={page} totalItems={visiblePlans.length} itemsPerPage={pageSize} onPageChange={setPage} onItemsPerPageChange={size => { setPageSize(size); setPage(1); }} language={zh ? 'zh' : 'en'} itemLabel={zh ? '个计划' : 'plans'} />}
      </div>
    </section>

    {planEditorOpen && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 p-4"><button type="button" aria-label={zh ? '关闭编辑器' : 'Close editor'} onClick={resetPlanForm} className="absolute inset-0 cursor-default" /><form onSubmit={savePlan} className="relative z-10 flex max-h-[min(860px,calc(100vh-2rem))] w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"><div className="flex items-center justify-between border-b border-slate-200 px-6 py-4"><div><div className="flex items-center gap-2"><Database size={17} className="text-cyan-600" /><h2 className="text-base font-bold text-slate-900">{editingPlanId ? (zh ? '编辑采集计划' : 'Edit collection plan') : (zh ? '新建例外计划' : 'New exception plan')}</h2></div><p className="mt-1 text-xs text-slate-500">{zh ? '设置采集目标、模块和执行周期' : 'Set collection targets, modules, and schedule'}</p></div><button type="button" onClick={resetPlanForm} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700"><X size={18} /></button></div><div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-6">
      <section><div className="mb-3 flex items-center justify-between"><div><h3 className="text-sm font-bold text-slate-900">{zh ? '基本信息' : 'Basic information'}</h3><p className="mt-0.5 text-xs text-slate-500">{zh ? '系统默认只维护一套基线；此处用于高级例外范围。' : 'Use a clear name and platform matching rule.'}</p></div><label className="flex cursor-pointer items-center gap-2 text-xs font-semibold text-slate-600"><input type="checkbox" checked={planForm.enabled} onChange={event => setPlanForm({ ...planForm, enabled: event.target.checked })} className="h-4 w-4 accent-cyan-600" />{zh ? '启用计划' : 'Enabled'}</label></div><div className="grid gap-3 sm:grid-cols-2"><Input label={zh ? '计划名称' : 'Plan name'} value={planForm.name} onChange={value => setPlanForm({ ...planForm, name: value })} required /><Input label={zh ? '匹配平台' : 'Platform'} value={planForm.cli_platform} onChange={value => setPlanForm({ ...planForm, cli_platform: value })} /></div><div className="mt-3"><Input label={zh ? '描述' : 'Description'} value={planForm.description} onChange={value => setPlanForm({ ...planForm, description: value })} /></div></section>
     <section><div className="mb-3"><h3 className="text-sm font-bold text-slate-900">{zh ? '目标设备' : 'Target devices'}</h3><p className="mt-0.5 text-xs text-slate-500">{zh ? '选择计划要作用的设备范围。' : 'Choose which devices this plan applies to.'}</p></div><label className="block text-[10px] font-bold uppercase tracking-wide text-slate-500">{zh ? '目标范围' : 'Target scope'}<select value={targetScope.mode} onChange={event => setTargetScope({ ...targetScope, mode: event.target.value as TargetScopeMode })} className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-xs font-medium text-slate-800 outline-none focus:border-cyan-400"><option value="all">{zh ? '全部在线设备' : 'All online devices'}</option><option value="composite">{zh ? '复合筛选（站点 / 角色 / 类型 / 平台）' : 'Combined filters (site / role / type / platform)'}</option><option value="ip">{zh ? '指定 IP / 设备清单' : 'IP / device list'}</option><option value="site">{zh ? '按单个站点' : 'Single site'}</option><option value="role">{zh ? '按单个角色' : 'Single role'}</option><option value="tag">{zh ? '按标签 ID' : 'By tag IDs'}</option></select></label>{targetScope.mode === 'composite' && <div className="mt-3 grid gap-3 rounded-xl border border-slate-100 bg-slate-50 p-3 sm:grid-cols-2">{([['site', zh ? '站点' : 'Site', scopeOptions.sites], ['role', zh ? '角色' : 'Role', scopeOptions.roles], ['category', zh ? '设备类型' : 'Type', scopeOptions.categories], ['platform', zh ? '平台' : 'Platform', scopeOptions.platforms]] as const).map(([key, label, options]) => <label key={key} className="text-[10px] font-bold text-slate-500">{label}<select value={targetScope[key]} onChange={event => setTargetScope({ ...targetScope, [key]: event.target.value })} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2 py-2 text-xs font-normal text-slate-700"><option value="">{zh ? '不限' : 'Any'}</option>{options.map(option => <option key={option.value} value={option.value}>{option.label || option.value} ({option.count ?? 0})</option>)}</select></label>)}</div>}{targetScope.mode === 'ip' && <textarea value={targetScope.ips} onChange={event => setTargetScope({ ...targetScope, ips: event.target.value })} rows={4} placeholder={zh ? '每行一个 IP，必须已存在于 CMDB' : 'One IP per line; must exist in CMDB'} className="mt-3 w-full resize-y rounded-xl border border-slate-200 bg-slate-50 p-3 font-mono text-xs outline-none focus:border-cyan-400" />}{targetScope.mode === 'site' && <select value={targetScope.site} onChange={event => setTargetScope({ ...targetScope, site: event.target.value })} className="mt-3 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-xs"><option value="">{zh ? '请选择站点' : 'Select site'}</option>{scopeOptions.sites.map(option => <option key={option.value} value={option.value}>{option.label || option.value} ({option.count ?? 0})</option>)}</select>}{targetScope.mode === 'role' && <select value={targetScope.role} onChange={event => setTargetScope({ ...targetScope, role: event.target.value })} className="mt-3 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-xs"><option value="">{zh ? '请选择角色' : 'Select role'}</option>{scopeOptions.roles.map(option => <option key={option.value} value={option.value}>{option.value} ({option.count ?? 0})</option>)}</select>}{targetScope.mode === 'tag' && <textarea value={targetScope.tagIds} onChange={event => setTargetScope({ ...targetScope, tagIds: event.target.value })} rows={2} placeholder={zh ? '填写标签 ID，逗号分隔' : 'Tag IDs separated by commas'} className="mt-3 w-full resize-y rounded-xl border border-slate-200 bg-slate-50 p-3 font-mono text-xs outline-none focus:border-cyan-400" />}</section>
      <section><div className="mb-3 flex items-end justify-between gap-3"><div><h3 className="text-sm font-bold text-slate-900">{zh ? '采集模块' : 'Collection modules'}</h3><p className="mt-0.5 text-xs text-slate-500">{zh ? 'Variant 是模块针对设备或协议差异的采集实现版本。' : 'A variant is the module implementation for a device or protocol variation.'}</p></div><button type="button" onClick={addPlanModule} className="inline-flex shrink-0 items-center gap-1.5 rounded-xl border border-cyan-200 bg-cyan-50 px-3 py-2 text-xs font-bold text-cyan-700 hover:border-cyan-300"><Plus size={14} />{zh ? '添加模块' : 'Add module'}</button></div><div className="space-y-3">{planModuleEntries.length === 0 && <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-6 text-center text-xs text-slate-400">{zh ? '还没有模块，请点击“添加模块”。' : 'No modules yet. Click “Add module”.'}</div>}{planModuleEntries.map((entry, index) => <div key={index + '-' + entry.module} className="rounded-xl border border-slate-200 bg-slate-50 p-4"><div className="mb-3 flex items-center justify-between"><div className="flex items-center gap-2"><span className="flex h-6 w-6 items-center justify-center rounded-full bg-cyan-100 text-[10px] font-bold text-cyan-700">{index + 1}</span><span className="text-xs font-bold text-slate-700">{zh ? '采集模块' : 'Module'}</span>{entry.vendor && <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700">{zh ? '厂商范围' : 'Vendor scope'}: {Array.isArray(entry.vendor) ? entry.vendor.join(', ') : String(entry.vendor)}</span>}</div><button type="button" onClick={() => removePlanModule(index)} className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-semibold text-rose-600 hover:bg-rose-50"><Trash2 size={13} />{zh ? '移除' : 'Remove'}</button></div><div className="grid gap-3 sm:grid-cols-2"><label className="text-[10px] font-bold text-slate-500">{zh ? '模块' : 'Module'}<select value={entry.module} onChange={event => updatePlanModule(index, { module: event.target.value, variant: '' })} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2.5 text-xs"><option value="">{zh ? '请选择模块' : 'Select module'}</option>{modules.map(module => <option key={module.module_key} value={module.module_key}>{module.display_name || module.module_key}</option>)}</select></label><label className="text-[10px] font-bold text-slate-500">{zh ? '采集版本（Variant）' : 'Collection variant'}<select value={entry.variant} onChange={event => updatePlanModule(index, { variant: event.target.value })} disabled={!entry.module} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2.5 text-xs disabled:cursor-not-allowed disabled:bg-slate-100"><option value="">{zh ? (entry.module ? '请选择采集版本' : '请先选择模块') : (entry.module ? 'Select collection variant' : 'Select a module first')}</option>{planVariantOptions(entry.module).map(variant => <option key={variant.variant_key} value={variant.variant_key}>{variant.display_name || variant.variant_key} · {variant.status}</option>)}</select></label><Input label={zh ? '采集间隔' : 'Interval'} value={entry.interval} onChange={value => updatePlanModule(index, { interval: value })} /><Input label={zh ? '超时' : 'Timeout'} value={entry.scrape_timeout} onChange={value => updatePlanModule(index, { scrape_timeout: value })} /></div></div>)}</div></section>
      {planFormError && <div className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">{planFormError}</div>}
      <details className="rounded-xl border border-slate-200 bg-slate-50 p-3"><summary className="cursor-pointer text-xs font-bold text-slate-600">{zh ? '高级配置预览（只读）' : 'Advanced config preview (read-only)'}</summary><pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-white p-3 font-mono text-[10px] leading-5 text-slate-600">{JSON.stringify({ modules: planModuleEntries, ...(serializeTargetScope() ? { target_scope: serializeTargetScope() } : {}) }, null, 2)}</pre></details>
    </div><div className="flex items-center justify-end gap-2 border-t border-slate-200 bg-white px-6 py-4"><button type="button" onClick={resetPlanForm} className="rounded-xl border border-slate-200 px-4 py-2.5 text-xs font-bold text-slate-600 hover:bg-slate-50">{zh ? '取消' : 'Cancel'}</button><button type="submit" className="inline-flex items-center gap-2 rounded-xl bg-cyan-600 px-4 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-cyan-700"><Save size={14} />{editingPlanId ? (zh ? '保存修改' : 'Save changes') : (zh ? '创建计划' : 'Create plan')}</button></div></form></div>}

{planPreview && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 p-4"><button type="button" aria-label={zh ? '关闭详情' : 'Close details'} onClick={closePlanPreview} className="absolute inset-0 cursor-default" /><div role="dialog" aria-modal="true" className="relative z-10 flex max-h-[min(860px,calc(100vh-2rem))] w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"><div className="flex items-start justify-between border-b border-slate-200 px-6 py-4"><div><p className="text-xs font-semibold text-cyan-700">{zh ? '采集计划详情' : 'Collection plan details'}</p><h2 className="mt-1 text-lg font-bold text-slate-900">{planPreview.name}</h2><p className="mt-1 text-xs text-slate-500">{zh ? '只读查看；字段与编辑计划保持一致。' : 'Read-only view; fields match the editor.'}</p></div><button type="button" onClick={closePlanPreview} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100"><X size={18} /></button></div><div className="min-h-0 flex-1 overflow-y-auto p-6"><PlanReadOnlyFields plan={planPreview} zh={zh} /></div><div className="flex justify-end gap-2 border-t border-slate-200 px-6 py-4"><button type="button" onClick={() => { closePlanPreview(); editPlan(planPreview); }} className="inline-flex items-center gap-2 rounded-xl bg-cyan-600 px-4 py-2.5 text-xs font-bold text-white"><Pencil size={14} />{zh ? '编辑计划' : 'Edit plan'}</button></div></div></div>}
  </>;
};

const PlanStat: React.FC<{ label: string; value: number; tone: 'slate' | 'emerald' | 'amber' | 'rose' }> = ({ label, value, tone }) => {
  const tones = { slate: 'bg-slate-50 text-slate-700', emerald: 'bg-emerald-50 text-emerald-700', amber: 'bg-amber-50 text-amber-700', rose: 'bg-rose-50 text-rose-700' };
  return <div className={`rounded-2xl border border-slate-200 px-4 py-3 shadow-sm ${tones[tone]}`}><p className="text-[11px] font-bold opacity-80">{label}</p><p className="mt-1 text-2xl font-extrabold">{value}</p></div>;
};

const CollectionHealthSection: React.FC<{ zh: boolean; health: HealthPayload; loading: boolean }> = ({ zh, health, loading }) => {
  const items = health.items || [];
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const totalPages = Math.max(1, Math.ceil(items.length / pageSize));
  useEffect(() => { setPage(1); }, [pageSize, items.length]);
  useEffect(() => { setPage(current => Math.min(current, totalPages)); }, [totalPages]);
  const pageItems = items.slice((page - 1) * pageSize, page * pageSize);
  return <section className="space-y-4"><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><PlanStat label={zh ? '采集分配' : 'Assignments'} value={health.summary?.total ?? items.length} tone="slate" /><PlanStat label={zh ? '健康分配' : 'Healthy'} value={health.summary?.healthy ?? 0} tone="emerald" /><PlanStat label={zh ? '健康率' : 'Health ratio'} value={Math.round((health.summary?.health_ratio || 0) * 100)} tone="emerald" /><PlanStat label={zh ? '异常分配' : 'Needs attention'} value={Math.max((health.summary?.total ?? items.length) - (health.summary?.healthy ?? 0), 0)} tone="rose" /></div><div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"><div className="hidden grid-cols-[1.25fr_1fr_1.2fr_0.8fr_1fr] gap-3 border-b border-slate-100 bg-slate-50 px-5 py-3 text-[10px] font-bold uppercase tracking-wide text-slate-500 lg:grid"><span>{zh ? '设备' : 'Asset'}</span><span>{zh ? '采集器' : 'Collector'}</span><span>{zh ? '采集版本' : 'Module variant'}</span><span>{zh ? '状态' : 'Status'}</span><span>{zh ? '错误 / 最近采集' : 'Error / age'}</span></div>{loading && <div className="p-10 text-center text-xs text-slate-400">{zh ? '正在加载采集健康…' : 'Loading collection health…'}</div>}{!loading && items.length === 0 && <EmptyState zh={zh} label={zh ? '暂无采集分配数据。' : 'No collection assignments.'} />}{!loading && items.length > 0 && pageItems.map(item => <div key={item.assignment_id} className="grid gap-2 border-b border-slate-100 px-5 py-4 last:border-0 hover:bg-cyan-50/30 lg:grid-cols-[1.25fr_1fr_1.2fr_0.8fr_1fr] lg:items-center"><div className="min-w-0"><span className="mr-2 text-[10px] font-bold text-slate-400 lg:hidden">{zh ? '设备' : 'Asset'}:</span><span className="font-mono text-xs text-slate-700">{item.asset_id || '—'}</span></div><div className="text-xs text-slate-600"><span className="mr-2 text-[10px] font-bold text-slate-400 lg:hidden">{zh ? '采集器' : 'Collector'}:</span>{item.collector_id || '—'}</div><div className="min-w-0 truncate font-mono text-xs text-slate-600"><span className="mr-2 font-sans text-[10px] font-bold text-slate-400 lg:hidden">{zh ? '采集版本' : 'Module'}:</span>{item.module_variant_id || '—'}</div><div><span className="mr-2 text-[10px] font-bold text-slate-400 lg:hidden">{zh ? '状态' : 'Status'}:</span><span className={`inline-flex rounded-full border px-2 py-1 text-[10px] font-bold ${statusTone(item.status)}`}>{displayStatus(item.status, zh)}</span></div><div className="text-[10px] text-slate-500"><span className="mr-2 font-sans font-bold text-slate-400 lg:hidden">{zh ? '错误 / 最近采集' : 'Error / age'}:</span>{item.error_code || (item.age_seconds == null ? '—' : `${Math.round(item.age_seconds)}s`)}{item.consecutive_failures ? ` · ${zh ? `连续失败 ${item.consecutive_failures} 次` : `${item.consecutive_failures} consecutive failures`}` : ''}</div></div>)}{items.length > 0 && <Pagination currentPage={page} totalItems={items.length} itemsPerPage={pageSize} onPageChange={setPage} onItemsPerPageChange={size => { setPageSize(size); setPage(1); }} language={zh ? 'zh' : 'en'} itemLabel={zh ? '条采集分配' : 'assignments'} />}</div></section>;
};

const DetailItem: React.FC<{ label: string; value: string }> = ({ label, value }) => <div className="rounded-xl border border-slate-200 bg-slate-50 p-3"><p className="text-[10px] font-bold text-slate-400">{label}</p><p className="mt-1 truncate text-sm font-bold text-slate-800">{value}</p></div>;

const planScopeDetails = (plan: PlanRow, zh: boolean) => {
  const scope = plan.config?.target_scope;
  if (!scope) return zh ? '未设置额外筛选条件' : 'No additional filters';
  const mode = String(scope.mode || '');
  if (mode === 'ip') return (Array.isArray(scope.values) ? scope.values : []).join(', ') || (zh ? '未填写地址' : 'No addresses');
  if (mode === 'site' || mode === 'role') return String(scope.value || '—');
  if (mode === 'tag') return (Array.isArray(scope.tag_ids) ? scope.tag_ids : []).join(', ') || (zh ? '未填写标签' : 'No tags');
  if (mode === 'composite') {
    const filters = scope.filters && typeof scope.filters === 'object' ? scope.filters as Record<string, unknown> : {};
    return Object.entries(filters).filter(([, value]) => value).map(([key, value]) => `${key}: ${String(value)}`).join(' · ') || (zh ? '未填写筛选条件' : 'No filters');
  }
  return zh ? '全部在线设备' : 'All online devices';
};

const PlanReadOnlyFields: React.FC<{ plan: PlanRow; zh: boolean }> = ({ plan, zh }) => <div className="space-y-5">
  <section><div className="mb-3"><h3 className="text-sm font-bold text-slate-900">{zh ? '基本信息' : 'Basic information'}</h3><p className="mt-0.5 text-xs text-slate-500">{zh ? '与编辑页面保持一致的计划基本信息。' : 'The same plan fields shown in the editor.'}</p></div><div className="grid gap-3 sm:grid-cols-2"><DetailItem label={zh ? '计划名称' : 'Plan name'} value={plan.name || '—'} /><DetailItem label={zh ? '匹配平台' : 'Platform'} value={plan.cli_platform || '—'} /><DetailItem label={zh ? '计划状态' : 'Status'} value={enabled(plan.enabled) ? (zh ? '已启用' : 'Enabled') : (zh ? '已停用' : 'Disabled')} /></div><div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3"><p className="text-[10px] font-bold text-slate-400">{zh ? '描述' : 'Description'}</p><p className="mt-1 whitespace-pre-wrap text-sm text-slate-700">{plan.description || (zh ? '暂无描述' : 'No description')}</p></div></section>
 <section><div className="mb-3"><h3 className="text-sm font-bold text-slate-900">{zh ? '目标设备' : 'Target devices'}</h3><p className="mt-0.5 text-xs text-slate-500">{zh ? '选择计划要作用的设备范围。' : 'Choose which devices this plan applies to.'}</p></div><DetailItem label={zh ? '目标范围' : 'Target scope'} value={planScopeLabel(plan, zh)} /><div className="mt-2 rounded-xl border border-slate-200 bg-slate-50 p-3"><p className="text-[10px] font-bold text-slate-400">{zh ? '筛选详情' : 'Filter details'}</p><p className="mt-1 break-words text-xs text-slate-700">{planScopeDetails(plan, zh)}</p></div></section>
  {plan.coverage && <section><div className="mb-3"><h3 className="text-sm font-bold text-slate-900">{zh ? '覆盖预览' : 'Coverage preview'}</h3><p className="mt-0.5 text-xs text-slate-500">{zh ? '在线设备按当前厂商/平台规则命中的 Variant。' : 'Online devices matched by current vendor/platform rules.'}</p></div><div className="grid gap-3 sm:grid-cols-3"><DetailItem label={zh ? '命中设备' : 'Matched devices'} value={String(plan.coverage.target_count ?? 0)} /><DetailItem label={zh ? '未命中设备' : 'Unmatched devices'} value={String(plan.coverage.unmatched_online_devices ?? 0)} /><DetailItem label={zh ? '命中版本' : 'Variant hits'} value={String(Object.keys(plan.coverage.variant_hits || {}).length)} /></div></section>}
  <section><div className="mb-3"><h3 className="text-sm font-bold text-slate-900">{zh ? '采集模块' : 'Collection modules'}</h3><p className="mt-0.5 text-xs text-slate-500">{zh ? 'Variant 是模块针对设备或协议差异的采集实现版本。' : 'A variant is the module implementation for a device or protocol variation.'}</p></div><div className="space-y-2">{(plan.config?.modules || []).map((entry, index) => <div key={index} className="rounded-xl border border-slate-200 bg-slate-50 p-4"><div className="mb-3 flex items-center gap-2"><span className="flex h-6 w-6 items-center justify-center rounded-full bg-cyan-100 text-[10px] font-bold text-cyan-700">{index + 1}</span><span className="text-xs font-bold text-slate-700">{zh ? '采集模块' : 'Module'}</span>{(entry.vendor || entry.platform) && <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700">{zh ? '匹配' : 'Match'}: {Array.isArray(entry.vendor) ? entry.vendor.join(', ') : String(entry.vendor || entry.platform)}</span>}</div><div className="grid gap-3 sm:grid-cols-2"><DetailItem label={zh ? '模块' : 'Module'} value={String(entry.module || entry.module_key || '—')} /><DetailItem label={zh ? '采集版本（Variant）' : 'Collection variant'} value={String(entry.variant || entry.variant_key || '—')} /><DetailItem label={zh ? '采集间隔' : 'Interval'} value={String(entry.interval || '—')} /><DetailItem label={zh ? '超时' : 'Timeout'} value={String(entry.scrape_timeout || '—')} /></div></div>)}{!(plan.config?.modules || []).length && <div className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-xs text-slate-400">{zh ? '暂无采集模块' : 'No collection modules'}</div>}</div></section>
  <details className="rounded-xl border border-slate-200 bg-slate-50 p-3"><summary className="cursor-pointer text-xs font-bold text-slate-600">{zh ? '高级配置预览（只读）' : 'Advanced config preview (read-only)'}</summary><pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-white p-3 font-mono text-[10px] leading-5 text-slate-600">{JSON.stringify(plan.config || {}, null, 2)}</pre></details>
</div>;

type MonitoringAction = (path: string, method?: string, body?: unknown) => Promise<boolean>;

const MODULE_FORM_DEFAULT = { module_key: '', display_name: '', vendor: 'generic', cli_platform: 'generic', feature_domain: '', metric_group: 'interface', walk_fingerprint: '', description: '', enabled: true };
const VARIANT_FORM_DEFAULT = { variant_key: '', display_name: '', max_repetitions: '25', retries: '2', request_timeout_ms: '3000', scrape_timeout_ms: '20000', supported_platforms: '', supported_models: '', supported_version_scope: '', status: 'DRAFT', enabled: true, oid_config: '{\n  "walk": [],\n  "get": [],\n  "metrics": []\n}' };

interface ModuleCatalogSectionProps {
  zh: boolean;
  modules: ModuleRow[];
  variants: VariantRow[];
  loading: boolean;
  runAction: MonitoringAction;
  showToast: (message: string, type?: string) => void;
}

const OidConfigPreview: React.FC<{ variant: VariantRow; zh: boolean }> = ({ variant, zh }) => <details className="mt-3 rounded-lg border border-slate-200 bg-white">
  <summary className="cursor-pointer list-none px-3 py-2 text-[11px] font-semibold text-cyan-700 marker:hidden">{zh ? '查看 JSON 配置（只读）' : 'View JSON config (read-only)'}</summary>
  <pre className="max-h-72 overflow-auto border-t border-slate-100 bg-slate-950 p-3 text-[10px] leading-5 text-slate-100">{JSON.stringify(variantOidConfig(variant), null, 2)}</pre>
</details>;

const ModuleCatalogSection: React.FC<ModuleCatalogSectionProps> = ({ zh, modules, variants, loading, runAction, showToast }) => {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'enabled' | 'disabled'>('all');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [editorOpen, setEditorOpen] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [moduleForm, setModuleForm] = useState({ ...MODULE_FORM_DEFAULT });
  const [variantEditorOpen, setVariantEditorOpen] = useState(false);
  const [variantManagerOpen, setVariantManagerOpen] = useState(false);
  const [variantEditingId, setVariantEditingId] = useState<string | null>(null);
  const [variantForm, setVariantForm] = useState({ ...VARIANT_FORM_DEFAULT });
  const [variantValidation, setVariantValidation] = useState<VariantJsonValidation>({ state: 'idle', message: '' });
  const selectedModule = modules.find(item => item.id === selectedId) || null;
  const selectedEditorModule = modules.find(item => item.id === editingId) || null;
  const selectedVariants = variants.filter(item => item.module_id === (selectedId || editingId));
  const query = search.trim().toLowerCase();
  const visibleModules = modules.filter(module => {
    const matchesSearch = !query || [module.display_name, module.module_key, module.vendor, module.cli_platform, module.metric_group].some(value => String(value || '').toLowerCase().includes(query));
    const matchesStatus = statusFilter === 'all' || (statusFilter === 'enabled' ? enabled(module.enabled) : !enabled(module.enabled));
    return matchesSearch && matchesStatus;
  });
  const enabledCount = modules.filter(module => enabled(module.enabled)).length;
  const publishedCount = variants.filter(variant => String(variant.status || '').toUpperCase() === 'PUBLISHED').length;
  const totalPages = Math.max(1, Math.ceil(visibleModules.length / pageSize));
  const pagedModules = visibleModules.slice((page - 1) * pageSize, page * pageSize);
  useEffect(() => { setPage(1); }, [pageSize, search, statusFilter]);
  useEffect(() => { setPage(current => Math.min(current, totalPages)); }, [totalPages]);

  const openCreate = () => { setEditingId(null); setModuleForm({ ...MODULE_FORM_DEFAULT }); setVariantEditorOpen(false); setVariantManagerOpen(false); setEditorOpen(true); };
  const openEdit = (module: ModuleRow) => { setEditingId(module.id); setModuleForm({ ...MODULE_FORM_DEFAULT, ...module, module_key: module.module_key || '', display_name: module.display_name || '', enabled: enabled(module.enabled) }); setVariantEditorOpen(false); setVariantManagerOpen(false); setEditorOpen(true); };
  const openDetail = (module: ModuleRow) => { setSelectedId(module.id); setDetailOpen(true); };
  const closeEditor = () => { setEditorOpen(false); setEditingId(null); setVariantEditorOpen(false); };
  const openVariantManager = (module: ModuleRow, variant?: VariantRow) => { setEditorOpen(false); setDetailOpen(false); setEditingId(null); setSelectedId(module.id); setVariantEditingId(null); setVariantForm({ ...VARIANT_FORM_DEFAULT }); setVariantValidation({ state: 'idle', message: '' }); setVariantEditorOpen(false); setVariantManagerOpen(true); if (variant) { setVariantEditingId(variant.id); setVariantForm({ ...VARIANT_FORM_DEFAULT, variant_key: variant.variant_key || '', display_name: variant.display_name || '', max_repetitions: String(variant.max_repetitions ?? 25), retries: String(variant.retries ?? 2), request_timeout_ms: String(variant.request_timeout_ms ?? 3000), scrape_timeout_ms: String(variant.scrape_timeout_ms ?? 20000), supported_platforms: (variant.supported_platforms || []).join(', '), supported_models: (variant.supported_models || []).join(', '), supported_version_scope: (variant.supported_version_scope || []).join(', '), status: String(variant.status || 'DRAFT'), enabled: enabled(variant.enabled), oid_config: JSON.stringify(variantOidConfig(variant), null, 2) }); setVariantEditorOpen(true); } };
  const closeVariantManager = () => { setVariantManagerOpen(false); setSelectedId(null); setVariantEditingId(null); setVariantEditorOpen(false); setVariantValidation({ state: 'idle', message: '' }); };
  useEscapeClose(editorOpen, closeEditor);
  useEscapeClose(detailOpen, () => setDetailOpen(false));
  const saveModule = async (event: React.FormEvent) => {
    event.preventDefault();
    const path = editingId ? `/api/monitoring/modules/${editingId}` : '/api/monitoring/modules';
    const body = editingId ? { display_name: moduleForm.display_name, vendor: moduleForm.vendor, cli_platform: moduleForm.cli_platform, feature_domain: moduleForm.feature_domain, metric_group: moduleForm.metric_group, walk_fingerprint: moduleForm.walk_fingerprint, description: moduleForm.description, enabled: moduleForm.enabled } : moduleForm;
    if (await runAction(path, editingId ? 'PATCH' : 'POST', body)) closeEditor();
  };
  const deleteModule = async (module: ModuleRow) => {
    if (!window.confirm(zh ? `确定删除模块“${module.display_name}”吗？` : `Delete module “${module.display_name}”?`)) return;
    if (await runAction(`/api/monitoring/modules/${module.id}`, 'DELETE')) { setDetailOpen(false); closeEditor(); }
  };
  const openCreateVariant = () => { setVariantEditingId(null); setVariantForm({ ...VARIANT_FORM_DEFAULT }); setVariantValidation({ state: 'idle', message: '' }); setVariantEditorOpen(true); };
  const openEditVariant = (variant: VariantRow) => { setVariantEditingId(variant.id); setVariantForm({ ...VARIANT_FORM_DEFAULT, variant_key: variant.variant_key || '', display_name: variant.display_name || '', max_repetitions: String(variant.max_repetitions ?? 25), retries: String(variant.retries ?? 2), request_timeout_ms: String(variant.request_timeout_ms ?? 3000), scrape_timeout_ms: String(variant.scrape_timeout_ms ?? 20000), supported_platforms: (variant.supported_platforms || []).join(', '), supported_models: (variant.supported_models || []).join(', '), supported_version_scope: (variant.supported_version_scope || []).join(', '), status: String(variant.status || 'DRAFT'), enabled: enabled(variant.enabled), oid_config: JSON.stringify(variantOidConfig(variant), null, 2) }); setVariantValidation({ state: 'idle', message: '' }); setVariantEditorOpen(true); };
  const validateVariantJson = () => {
    const result = parseVariantOidConfig(variantForm.oid_config, zh);
    setVariantValidation({ state: result.state, message: result.message });
    showToast(result.message, result.state === 'valid' ? 'success' : 'error');
    return result;
  };
  const updateVariantForm = (patch: Partial<VariantFormState>) => {
    setVariantForm(current => ({ ...current, ...patch }));
    setVariantValidation({ state: 'idle', message: '' });
  };
  const formatVariantJson = () => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(variantForm.oid_config || '{}');
    } catch {
      return validateVariantJson();
    }
    const formatted = JSON.stringify(parsed, null, 2);
    const result = parseVariantOidConfig(formatted, zh);
    setVariantForm(current => ({ ...current, oid_config: formatted }));
    setVariantValidation({ state: result.state, message: result.message });
    showToast(result.state === 'valid' ? (zh ? 'JSON 已格式化并通过检查' : 'JSON formatted and validated') : result.message, result.state === 'valid' ? 'success' : 'error');
    return result;
  };
  const copyVariantJson = async () => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(variantForm.oid_config);
      } else {
        const helper = document.createElement('textarea');
        helper.value = variantForm.oid_config;
        helper.setAttribute('readonly', 'true');
        helper.style.position = 'fixed';
        helper.style.opacity = '0';
        document.body.appendChild(helper);
        helper.select();
        const copied = document.execCommand('copy');
        helper.remove();
        if (!copied) throw new Error('Clipboard copy failed');
      }
      showToast(zh ? 'JSON 已复制' : 'JSON copied', 'success');
    } catch {
      showToast(zh ? '复制失败，请手动选择 JSON 内容。' : 'Copy failed; select the JSON manually.', 'error');
    }
  };
  const saveVariant = async (event: React.FormEvent): Promise<boolean> => {
    event.preventDefault();
    const moduleId = editingId || selectedId;
    if (!moduleId) return false;
    const validation = parseVariantOidConfig(variantForm.oid_config, zh);
    setVariantValidation({ state: validation.state, message: validation.message });
    if (!validation.config) {
      showToast(validation.message, 'error');
      return false;
    }
    const oidConfig = validation.config;
    const body = { module_id: moduleId, variant_key: variantForm.variant_key, display_name: variantForm.display_name, max_repetitions: Number(variantForm.max_repetitions) || 25, retries: Number(variantForm.retries) || 0, request_timeout_ms: Number(variantForm.request_timeout_ms) || 3000, scrape_timeout_ms: Number(variantForm.scrape_timeout_ms) || 20000, supported_platforms: variantForm.supported_platforms.split(/[;,\n]/).map(value => value.trim()).filter(Boolean), supported_models: variantForm.supported_models.split(/[;,\n]/).map(value => value.trim()).filter(Boolean), supported_version_scope: variantForm.supported_version_scope.split(/[;,\n]/).map(value => value.trim()).filter(Boolean), oid_config: oidConfig, status: variantForm.status, enabled: variantForm.enabled };
    const path = variantEditingId ? `/api/monitoring/module-variants/${variantEditingId}` : '/api/monitoring/module-variants';
    if (await runAction(path, variantEditingId ? 'PATCH' : 'POST', variantEditingId ? { ...body, module_id: undefined } : body)) { setVariantEditorOpen(false); setVariantEditingId(null); return true; }
    return false;
  };
  const saveVariantAndTest = async () => {
    const savedVariantId = variantEditingId;
    const saved = await saveVariant({ preventDefault: () => undefined } as React.FormEvent);
    if (saved && savedVariantId) await runAction(`/api/monitoring/module-variants/${savedVariantId}/test`);
  };
  const deleteVariant = async (variant: VariantRow) => { if (!window.confirm(zh ? `确定删除采集版本“${variant.display_name}”吗？` : `Delete collection variant “${variant.display_name}”?`)) return; if (await runAction(`/api/monitoring/module-variants/${variant.id}`, 'DELETE')) setVariantEditorOpen(false); };

  return <section className="space-y-4">
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><PlanStat label={zh ? '全部模块' : 'All modules'} value={modules.length} tone="slate" /><PlanStat label={zh ? '已启用' : 'Enabled'} value={enabledCount} tone="emerald" /><PlanStat label={zh ? '已停用' : 'Disabled'} value={modules.length - enabledCount} tone="amber" /><PlanStat label={zh ? '已发布版本' : 'Published variants'} value={publishedCount} tone="rose" /></div>
    <div className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-3 shadow-sm md:flex-row md:items-center md:justify-between"><div className="relative min-w-0 flex-1 md:max-w-md"><Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" /><input value={search} onChange={event => setSearch(event.target.value)} placeholder={zh ? '搜索模块名称、Key、厂商或平台' : 'Search module name, key, vendor, or platform'} className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2 pl-9 pr-3 text-xs outline-none focus:border-cyan-400 focus:bg-white" /></div><div className="flex flex-wrap items-center gap-2"><SlidersHorizontal size={14} className="text-slate-400" /><select value={statusFilter} onChange={event => setStatusFilter(event.target.value as typeof statusFilter)} className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs"><option value="all">{zh ? '全部状态' : 'All status'}</option><option value="enabled">{zh ? '已启用' : 'Enabled'}</option><option value="disabled">{zh ? '已停用' : 'Disabled'}</option></select>{(search || statusFilter !== 'all') && <button type="button" onClick={() => { setSearch(''); setStatusFilter('all'); }} className="rounded-xl px-2.5 py-2 text-xs font-semibold text-slate-500 hover:bg-slate-100">{zh ? '重置' : 'Reset'}</button>}<button type="button" onClick={openCreate} className="inline-flex items-center gap-1.5 rounded-xl bg-cyan-600 px-3 py-2 text-xs font-bold text-white hover:bg-cyan-700"><Plus size={14} />{zh ? '新建模块' : 'New module'}</button></div></div>
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"><div className="hidden grid-cols-[minmax(220px,1.5fr)_1fr_1fr_0.8fr_0.8fr_220px] gap-3 border-b border-slate-100 bg-slate-50 px-5 py-3 text-[10px] font-bold uppercase tracking-wide text-slate-500 lg:grid"><span>{zh ? '模块' : 'Module'}</span><span>{zh ? '厂商 / 平台' : 'Vendor / platform'}</span><span>{zh ? '指标类型' : 'Metric group'}</span><span>{zh ? '采集版本' : 'Variants'}</span><span>{zh ? '状态' : 'Status'}</span><span className="text-right">{zh ? '操作' : 'Actions'}</span></div>{loading && <div className="p-10 text-center text-xs text-slate-400">{zh ? '正在加载模块…' : 'Loading modules…'}</div>}{!loading && modules.length === 0 && <EmptyState zh={zh} label={zh ? '还没有模块，点击“新建模块”。' : 'No modules yet. Create one to get started.'} />}{!loading && modules.length > 0 && visibleModules.length === 0 && <EmptyState zh={zh} label={zh ? '没有匹配当前筛选条件的模块。' : 'No modules match the current filters.'} />}{!loading && pagedModules.map(module => <div key={module.id} className="grid gap-3 border-b border-slate-100 px-5 py-4 last:border-0 hover:bg-cyan-50/30 lg:grid-cols-[minmax(220px,1.5fr)_1fr_1fr_0.8fr_0.8fr_220px] lg:items-center"><div className="min-w-0"><p className="truncate text-sm font-bold text-slate-900">{module.display_name}</p><p className="mt-1 truncate font-mono text-[11px] text-cyan-700">{module.module_key}</p></div><div className="text-xs text-slate-600">{module.vendor || 'generic'} <span className="text-slate-300">·</span> {module.cli_platform || 'generic'}</div><div className="text-xs text-slate-600">{module.metric_group || '—'}</div><div className="text-xs font-semibold text-slate-700">{variants.filter(item => item.module_id === module.id).length}</div><div><span className={`inline-flex rounded-full border px-2 py-1 text-[10px] font-bold ${enabled(module.enabled) ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-slate-200 bg-slate-100 text-slate-500'}`}>{enabled(module.enabled) ? (zh ? '已启用' : 'ENABLED') : (zh ? '已停用' : 'DISABLED')}</span></div><div className="flex flex-nowrap items-center justify-end gap-1"><button type="button" aria-label={zh ? '查看模块' : 'View module'} title={zh ? '查看模块' : 'View module'} onClick={() => openDetail(module)} className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 text-slate-600 hover:border-cyan-300 hover:text-cyan-700"><Eye size={15} /></button><button type="button" aria-label={zh ? '编辑模块' : 'Edit module'} title={zh ? '编辑模块' : 'Edit module'} onClick={() => openEdit(module)} className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 text-slate-600 hover:border-cyan-300 hover:text-cyan-700"><Pencil size={15} /></button><button type="button" aria-label={zh ? '管理版本' : 'Manage variants'} title={zh ? '管理版本' : 'Manage variants'} onClick={() => openVariantManager(module)} className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-cyan-200 bg-cyan-50 text-cyan-700 hover:border-cyan-300"><Layers3 size={15} /></button><button type="button" aria-label={zh ? '删除模块' : 'Delete module'} title={zh ? '删除模块' : 'Delete module'} onClick={() => void deleteModule(module)} className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-rose-600 hover:bg-rose-50"><Trash2 size={15} /></button></div></div>)}<Pagination currentPage={page} totalItems={visibleModules.length} itemsPerPage={pageSize} onPageChange={setPage} onItemsPerPageChange={size => { setPageSize(size); setPage(1); }} language={zh ? 'zh' : 'en'} itemLabel={zh ? '个模块' : 'modules'} /></div>

    {editorOpen && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 p-4"><button type="button" aria-label={zh ? '关闭模块编辑器' : 'Close module editor'} onClick={closeEditor} className="absolute inset-0 cursor-default" /><form onSubmit={saveModule} className="relative z-10 flex max-h-[min(900px,calc(100vh-2rem))] w-full max-w-5xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"><div className="flex items-center justify-between border-b border-slate-200 px-6 py-4"><div><h2 className="text-base font-bold text-slate-900">{editingId ? (zh ? '编辑采集模块' : 'Edit module') : (zh ? '新建采集模块' : 'New module')}</h2><p className="mt-1 text-xs text-slate-500">{zh ? '模块定义采集能力，采集版本定义具体实现。' : 'Modules define capabilities; variants define implementations.'}</p></div><button type="button" onClick={closeEditor} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100"><X size={18} /></button></div><div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-6"><section><h3 className="mb-3 text-sm font-bold text-slate-900">{zh ? '基本信息' : 'Basic information'}</h3><div className="grid gap-3 sm:grid-cols-2"><Input label={zh ? '模块 Key' : 'Module key'} value={moduleForm.module_key} onChange={value => setModuleForm({ ...moduleForm, module_key: value })} required /><Input label={zh ? '显示名称' : 'Display name'} value={moduleForm.display_name} onChange={value => setModuleForm({ ...moduleForm, display_name: value })} required /><Input label={zh ? '厂商' : 'Vendor'} value={moduleForm.vendor} onChange={value => setModuleForm({ ...moduleForm, vendor: value })} /><Input label={zh ? '平台' : 'Platform'} value={moduleForm.cli_platform} onChange={value => setModuleForm({ ...moduleForm, cli_platform: value })} /><Input label={zh ? '功能域' : 'Feature domain'} value={moduleForm.feature_domain} onChange={value => setModuleForm({ ...moduleForm, feature_domain: value })} /><Input label={zh ? '指标类型' : 'Metric group'} value={moduleForm.metric_group} onChange={value => setModuleForm({ ...moduleForm, metric_group: value })} /><Input label={zh ? 'Walk 指纹' : 'Walk fingerprint'} value={moduleForm.walk_fingerprint} onChange={value => setModuleForm({ ...moduleForm, walk_fingerprint: value })} /></div><div className="mt-3"><Input label={zh ? '描述' : 'Description'} value={moduleForm.description} onChange={value => setModuleForm({ ...moduleForm, description: value })} /></div><label className="mt-3 flex items-center gap-2 text-xs font-semibold text-slate-600"><input type="checkbox" checked={moduleForm.enabled} onChange={event => setModuleForm({ ...moduleForm, enabled: event.target.checked })} className="h-4 w-4 accent-cyan-600" />{zh ? '启用模块' : 'Enabled'}</label></section>{editingId && <section className="border-t border-slate-100 pt-5"><div className="mb-3 flex items-end justify-between gap-3"><div><h3 className="text-sm font-bold text-slate-900">{zh ? '采集版本' : 'Collection variants'}</h3><p className="mt-0.5 text-xs text-slate-500">{zh ? '这里只展示版本摘要；新增、修改、校验和发布请进入独立的“管理版本”。' : 'This section is read-only; use “Manage variants” for variant CRUD, validation, and publishing.'}</p></div><button type="button" onClick={() => { if (selectedEditorModule) openVariantManager(selectedEditorModule); }} className="inline-flex shrink-0 items-center gap-1 rounded-xl border border-cyan-200 bg-cyan-50 px-3 py-2 text-xs font-bold text-cyan-700 hover:border-cyan-300"><Layers3 size={14} />{zh ? '管理版本' : 'Manage variants'}</button></div><div className="space-y-2">{variants.filter(item => item.module_id === editingId).map(variant => <div key={variant.id} className="rounded-xl border border-slate-200 bg-slate-50 p-3"><div className="flex items-start justify-between gap-2"><div className="min-w-0"><p className="text-xs font-bold text-slate-800">{variant.display_name}</p><p className="mt-1 font-mono text-[10px] text-cyan-700">{variant.variant_key}</p></div><div className="flex shrink-0 items-center gap-2"><button type="button" onClick={() => { if (selectedEditorModule) openVariantManager(selectedEditorModule, variant); }} className="rounded-lg border border-cyan-200 bg-cyan-50 px-2 py-1 text-[10px] font-bold text-cyan-700 hover:border-cyan-300">{zh ? '编辑 JSON' : 'Edit JSON'}</button><span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[9px] font-bold text-slate-600">{displayStatus(variant.status, zh)}</span></div></div><p className="mt-2 text-[10px] text-slate-500">{variant.request_timeout_ms}ms 请求 · {variant.scrape_timeout_ms}ms 采集 · 最大重复 {variant.max_repetitions} · OID {variantOidCount(variant).walks + variantOidCount(variant).gets} · 指标 {variantOidCount(variant).metrics} · {variant.mib_bundle_id || (zh ? '自定义 OID' : 'Custom OID')}</p><OidConfigPreview variant={variant} zh={zh} /></div>)}{variants.filter(item => item.module_id === editingId).length === 0 && <div className="rounded-xl border border-dashed border-slate-300 p-5 text-center text-xs text-slate-400">{zh ? '暂无采集版本' : 'No variants yet'}</div>}</div></section>}</div><div className="flex justify-end gap-2 border-t border-slate-200 px-6 py-4"><button type="button" onClick={closeEditor} className="rounded-xl border border-slate-200 px-4 py-2.5 text-xs font-bold text-slate-600">{zh ? '取消' : 'Cancel'}</button><button type="submit" className="inline-flex items-center gap-2 rounded-xl bg-cyan-600 px-4 py-2.5 text-xs font-bold text-white"><Save size={14} />{editingId ? (zh ? '保存模块' : 'Save module') : (zh ? '创建模块' : 'Create module')}</button></div></form></div>}
    {variantManagerOpen && selectedModule && <VariantManagerModal zh={zh} module={selectedModule} variants={selectedVariants} form={variantForm} editingId={variantEditingId} editorOpen={variantEditorOpen} validation={variantValidation} onClose={closeVariantManager} onCreate={openCreateVariant} onEdit={openEditVariant} onTest={variant => { void runAction(`/api/monitoring/module-variants/${variant.id}/test`); }} onPublish={variant => { void runAction(`/api/monitoring/module-variants/${variant.id}/publish`); }} onDelete={variant => { void deleteVariant(variant); }} onCancelEditor={() => { setVariantEditorOpen(false); setVariantEditingId(null); setVariantValidation({ state: 'idle', message: '' }); }} onValidate={validateVariantJson} onFormat={formatVariantJson} onCopy={copyVariantJson} onFormChange={updateVariantForm} onSave={saveVariant} onSaveAndTest={saveVariantAndTest} />}
    {detailOpen && selectedModule && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 p-4"><button type="button" aria-label={zh ? '关闭模块详情' : 'Close module details'} onClick={() => setDetailOpen(false)} className="absolute inset-0 cursor-default" /><div role="dialog" aria-modal="true" className="relative z-10 flex max-h-[min(860px,calc(100vh-2rem))] w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"><div className="flex items-start justify-between border-b border-slate-200 px-6 py-4"><div><p className="text-xs font-semibold text-cyan-700">{zh ? '模块详情' : 'Module details'}</p><h2 className="mt-1 text-lg font-bold text-slate-900">{selectedModule.display_name}</h2><p className="mt-1 font-mono text-xs text-slate-500">{selectedModule.module_key}</p></div><button type="button" onClick={() => setDetailOpen(false)} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100"><X size={18} /></button></div><div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-6"><div className="grid gap-3 sm:grid-cols-3"><DetailItem label={zh ? '状态' : 'Status'} value={enabled(selectedModule.enabled) ? (zh ? '已启用' : 'Enabled') : (zh ? '已停用' : 'Disabled')} /><DetailItem label={zh ? '厂商' : 'Vendor'} value={selectedModule.vendor || 'generic'} /><DetailItem label={zh ? '指标类型' : 'Metric group'} value={selectedModule.metric_group || '—'} /></div><div className="rounded-xl border border-cyan-100 bg-cyan-50/60 p-3 text-xs leading-5 text-cyan-900">{zh ? '模块是采集能力定义；OID 与指标配置属于采集版本。版本的“校验 JSON”会检查语法、OID 与指标基本结构，不连接设备。' : 'A module defines a collection capability; OIDs and metrics belong to its variants. “Check OID config” validates JSON structure only and does not connect to a device.'}</div><div><div className="mb-3 flex items-center justify-between"><h3 className="text-sm font-bold text-slate-900">{zh ? '采集版本' : 'Variants'}</h3><span className="text-xs text-slate-400">{selectedVariants.length}</span></div><div className="space-y-2">{selectedVariants.map(variant => <div key={variant.id} className="rounded-xl border border-slate-200 bg-slate-50 p-3"><div className="flex items-start justify-between gap-2"><div><p className="text-xs font-bold text-slate-800">{variant.display_name}</p><p className="mt-1 font-mono text-[10px] text-cyan-700">{variant.variant_key}</p></div><span className={`rounded-full border px-2 py-0.5 text-[9px] font-bold ${statusTone(variant.status)}`}>{variant.status || 'DRAFT'}</span></div><p className="mt-2 text-[10px] text-slate-500">{variant.request_timeout_ms}ms 请求 · {variant.scrape_timeout_ms}ms 采集</p><OidConfigPreview variant={variant} zh={zh} /></div>)}{selectedVariants.length === 0 && <div className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-xs text-slate-400">{zh ? '暂无采集版本' : 'No variants yet'}</div>}</div></div></div><div className="flex justify-end gap-2 border-t border-slate-200 px-6 py-4"><button type="button" onClick={() => openVariantManager(selectedModule)} className="inline-flex items-center gap-1.5 rounded-xl border border-cyan-200 bg-cyan-50 px-3 py-2 text-xs font-bold text-cyan-700 hover:border-cyan-300"><Layers3 size={14} />{zh ? '管理版本' : 'Manage variants'}</button><button type="button" onClick={() => { setDetailOpen(false); openEdit(selectedModule); }} className="inline-flex items-center gap-1.5 rounded-xl bg-cyan-600 px-3 py-2 text-xs font-bold text-white"><Pencil size={14} />{zh ? '编辑模块' : 'Edit module'}</button></div></div></div>}
  </section>;
};

type VariantFormState = typeof VARIANT_FORM_DEFAULT;

interface VariantManagerModalProps {
  zh: boolean;
  module: ModuleRow;
  variants: VariantRow[];
  form: VariantFormState;
  editingId: string | null;
  editorOpen: boolean;
  validation: VariantJsonValidation;
  onClose: () => void;
  onCreate: () => void;
  onEdit: (variant: VariantRow) => void;
  onTest: (variant: VariantRow) => void;
  onPublish: (variant: VariantRow) => void;
  onDelete: (variant: VariantRow) => void;
  onCancelEditor: () => void;
  onValidate: () => void;
  onFormat: () => void;
  onCopy: () => void | Promise<void>;
  onFormChange: (patch: Partial<VariantFormState>) => void;
  onSave: (event: React.FormEvent) => void | Promise<unknown>;
  onSaveAndTest: () => void | Promise<void>;
}

const VariantManagerModal: React.FC<VariantManagerModalProps> = ({
  zh, module, variants, form, editingId, editorOpen, validation,
  onClose, onCreate, onEdit, onTest, onPublish, onDelete, onCancelEditor,
  onValidate, onFormat, onCopy, onFormChange, onSave, onSaveAndTest,
}) => {
  useEscapeClose(true, onClose);
  useEscapeClose(editorOpen, onCancelEditor);
  const jsonStats = (() => {
    try {
      const parsed: unknown = JSON.parse(form.oid_config || '{}');
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
      const config = parsed as Record<string, unknown>;
      return {
        walks: Array.isArray(config.walk) ? config.walk.length : 0,
        gets: Array.isArray(config.get) ? config.get.length : 0,
        metrics: Array.isArray(config.metrics) ? config.metrics.length : 0,
      };
    } catch {
      return null;
    }
  })();
  const handleJsonKeyDown: React.KeyboardEventHandler<HTMLTextAreaElement> = event => {
    if (event.key !== 'Tab') return;
    event.preventDefault();
    const target = event.currentTarget;
    const start = target.selectionStart;
    const end = target.selectionEnd;
    onFormChange({ oid_config: `${form.oid_config.slice(0, start)}  ${form.oid_config.slice(end)}` });
    window.requestAnimationFrame(() => {
      target.selectionStart = start + 2;
      target.selectionEnd = start + 2;
    });
  };
  const jsonBorderClass = `mt-3 min-h-[36rem] w-full resize-y rounded-xl border bg-slate-950 p-4 font-mono text-[12px] leading-6 text-slate-100 shadow-inner outline-none ${validation.state === 'invalid' ? 'border-rose-400 focus:border-rose-300' : validation.state === 'valid' ? 'border-emerald-400 focus:border-emerald-300' : 'border-slate-700 focus:border-cyan-400'}`;
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 p-4">
  <button type="button" aria-label={zh ? '关闭采集版本管理' : 'Close variant manager'} onClick={onClose} className="absolute inset-0 cursor-default" />
  <div role="dialog" aria-modal="true" className="relative z-10 flex max-h-[min(900px,calc(100vh-2rem))] w-full max-w-6xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
    <div className="flex items-start justify-between border-b border-slate-200 px-6 py-4">
      <div><p className="text-xs font-semibold text-cyan-700">{zh ? '采集版本管理' : 'Collection variant manager'}</p><h2 className="mt-1 text-lg font-bold text-slate-900">{module.display_name}</h2><p className="mt-1 font-mono text-xs text-slate-500">{module.module_key}</p></div>
      <button type="button" onClick={onClose} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100"><X size={18} /></button>
    </div>
    <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-6">
      <section>
        <div className="mb-3 flex items-end justify-between gap-3"><div><h3 className="text-sm font-bold text-slate-900">{zh ? '版本列表' : 'Variants'}</h3><p className="mt-0.5 text-xs text-slate-500">{zh ? '每个版本对应一套可发布的 OID 与指标配置。' : 'Each variant is a publishable OID and metric configuration.'}</p></div><button type="button" onClick={onCreate} className="inline-flex shrink-0 items-center gap-1 rounded-xl border border-cyan-200 bg-cyan-50 px-3 py-2 text-xs font-bold text-cyan-700 hover:border-cyan-300"><Plus size={14} />{zh ? '新增版本' : 'New variant'}</button></div>
        <div className="space-y-2">{variants.map(variant => <div key={variant.id} className="rounded-xl border border-slate-200 bg-slate-50 p-3"><div className="flex items-start justify-between gap-2"><div className="min-w-0"><p className="text-xs font-bold text-slate-800">{variant.display_name}</p><p className="mt-1 font-mono text-[10px] text-cyan-700">{variant.variant_key}</p></div><div className="flex shrink-0 flex-wrap items-center justify-end gap-1.5"><ActionButton icon={<Pencil size={12} />} label={zh ? '编辑版本' : 'Edit variant'} onClick={() => onEdit(variant)} iconOnly /><ActionButton icon={<ShieldCheck size={12} />} label={zh ? '校验 JSON' : 'Validate JSON'} onClick={() => onTest(variant)} iconOnly /><ActionButton icon={<CheckCircle2 size={12} />} label={zh ? '发布版本' : 'Publish variant'} onClick={() => onPublish(variant)} iconOnly /><ActionButton icon={<Trash2 size={12} />} label={zh ? '删除版本' : 'Delete variant'} onClick={() => onDelete(variant)} iconOnly /><span className={`rounded-full border px-2 py-0.5 text-[9px] font-bold ${statusTone(variant.status)}`}>{displayStatus(variant.status, zh)}</span></div></div><p className="mt-2 text-[10px] text-slate-500">{variant.request_timeout_ms}ms 请求 · {variant.scrape_timeout_ms}ms 采集 · 最大重复 {variant.max_repetitions} · OID {variantOidCount(variant).walks + variantOidCount(variant).gets} · 指标 {variantOidCount(variant).metrics} · {variant.mib_bundle_id || (zh ? '自定义 OID' : 'Custom OID')}</p>{(variant.supported_platforms?.length || variant.supported_models?.length || variant.supported_version_scope?.length) && <div className="mt-2 flex flex-wrap gap-1 text-[9px]"><span className="font-semibold text-slate-500">{zh ? '适配：' : 'Scope:'}</span>{variant.supported_platforms?.map(value => <span key={`platform-${value}`} className="rounded bg-cyan-500/10 px-1.5 py-0.5 font-mono text-cyan-700">{value}</span>)}{variant.supported_models?.map(value => <span key={`model-${value}`} className="rounded bg-violet-500/10 px-1.5 py-0.5 font-mono text-violet-700">{value}</span>)}{variant.supported_version_scope?.map(value => <span key={`version-${value}`} className="rounded bg-amber-500/10 px-1.5 py-0.5 font-mono text-amber-700">{value}</span>)}</div>}<OidConfigPreview variant={variant} zh={zh} /></div>)}{variants.length === 0 && <div className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-xs text-slate-400">{zh ? '暂无采集版本' : 'No variants yet'}</div>}</div>
      </section>
      {editorOpen && <form onSubmit={onSave} className="rounded-xl border border-cyan-200 bg-cyan-50/40 p-4"><div className="mb-3 flex items-center justify-between"><div><h3 className="text-sm font-bold text-slate-800">{editingId ? (zh ? '编辑采集版本' : 'Edit variant') : (zh ? '新增采集版本' : 'New variant')}</h3><p className="mt-0.5 text-[11px] text-slate-500">{zh ? 'JSON 是版本的主配置；保存前会校验语法、OID 和指标结构。' : 'JSON is the primary configuration; syntax, OIDs, and metrics are checked before saving.'}</p></div></div><section className="rounded-xl border border-cyan-200 bg-white p-4 shadow-sm"><div className="flex flex-wrap items-start justify-between gap-3"><div><h4 className="text-sm font-bold text-slate-900">{zh ? 'OID / 指标 JSON' : 'OID / metric JSON'}<span className="ml-2 rounded-full bg-cyan-50 px-2 py-0.5 text-[10px] font-semibold text-cyan-700">{zh ? '主配置' : 'Primary config'}</span></h4><p className="mt-1 text-[11px] text-slate-500">{zh ? '建议使用格式化后的双空格缩进；Tab 键会自动插入两个空格。' : 'Use two-space indentation; Tab inserts two spaces.'}</p></div><div className="flex flex-wrap items-center gap-1.5"><button type="button" onClick={onFormat} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1.5 text-[11px] font-bold text-slate-600 hover:border-cyan-300"><RefreshCw size={13} />{zh ? '格式化' : 'Format'}</button><button type="button" onClick={onValidate} className="inline-flex items-center gap-1.5 rounded-lg border border-cyan-200 bg-cyan-50 px-2.5 py-1.5 text-[11px] font-bold text-cyan-700 hover:border-cyan-300"><ShieldCheck size={13} />{zh ? '校验 JSON' : 'Validate JSON'}</button><button type="button" onClick={() => void onCopy()} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1.5 text-[11px] font-bold text-slate-600 hover:border-cyan-300"><Copy size={13} />{zh ? '复制' : 'Copy'}</button></div></div><div className="mt-3 grid gap-4 xl:grid-cols-[minmax(0,1fr)_200px]"><textarea aria-label={zh ? 'OID 与指标 JSON 配置' : 'OID and metric JSON configuration'} value={form.oid_config} onChange={event => onFormChange({ oid_config: event.target.value })} onKeyDown={handleJsonKeyDown} rows={30} wrap="off" spellCheck={false} className={jsonBorderClass} /><aside className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs text-slate-600"><h5 className="text-xs font-bold text-slate-800">{zh ? '结构概览' : 'Structure overview'}</h5><div className="mt-3 space-y-2"><div className="flex items-center justify-between"><span>walk</span><strong className="text-slate-900">{jsonStats?.walks ?? 0}</strong></div><div className="flex items-center justify-between"><span>get</span><strong className="text-slate-900">{jsonStats?.gets ?? 0}</strong></div><div className="flex items-center justify-between"><span>metrics</span><strong className="text-slate-900">{jsonStats?.metrics ?? 0}</strong></div></div><p className="mt-4 leading-5 text-slate-500">{zh ? 'walk/get 是采集范围，metrics 决定导出的 Prometheus 指标和标签。' : 'walk/get define collection scope; metrics define Prometheus names and labels.'}</p></aside></div><div className="mt-3 flex flex-wrap items-center justify-between gap-2"><span className="text-[11px] text-slate-400">{zh ? '支持数字 OID 或 MIB::对象名；保存和发布时后端会再次严格校验。' : 'Numeric OIDs and MIB::object names are supported; the backend validates again on save and publish.'}</span>{validation.state !== 'idle' && <p role="status" className={validation.state === 'valid' ? 'text-emerald-700' : 'text-rose-700'}>{validation.message}</p>}</div></section><details className="mt-4 rounded-xl border border-slate-200 bg-white p-4"><summary className="cursor-pointer text-xs font-bold text-slate-700">{zh ? '采集参数与适配范围' : 'Collection parameters and compatibility scope'}</summary><div className="mt-3 grid gap-3 sm:grid-cols-2"><Input label={zh ? '版本 Key' : 'Variant key'} value={form.variant_key} onChange={value => onFormChange({ variant_key: value })} required /><Input label={zh ? '显示名称' : 'Display name'} value={form.display_name} onChange={value => onFormChange({ display_name: value })} required /><Input label={zh ? '支持平台（逗号分隔）' : 'Supported platforms (comma separated)'} value={form.supported_platforms} onChange={value => onFormChange({ supported_platforms: value })} placeholder={zh ? 'h3c_comware_v7,h3c_comware_v9' : 'h3c_comware_v7,h3c_comware_v9'} /><Input label={zh ? '支持型号/系列（逗号分隔）' : 'Supported models/series (comma separated)'} value={form.supported_models} onChange={value => onFormChange({ supported_models: value })} placeholder={zh ? 'S6800,S10500' : 'S6800,S10500'} /><Input label={zh ? '支持软件版本（逗号分隔）' : 'Supported software versions (comma separated)'} value={form.supported_version_scope} onChange={value => onFormChange({ supported_version_scope: value })} placeholder={zh ? 'Comware V7,Comware V9' : 'Comware V7,Comware V9'} /><Input label={zh ? '最大重复数' : 'Max repetitions'} value={form.max_repetitions} onChange={value => onFormChange({ max_repetitions: value })} /><Input label={zh ? '请求超时（毫秒）' : 'Request timeout (ms)'} value={form.request_timeout_ms} onChange={value => onFormChange({ request_timeout_ms: value })} /><Input label={zh ? '采集超时（毫秒）' : 'Scrape timeout (ms)'} value={form.scrape_timeout_ms} onChange={value => onFormChange({ scrape_timeout_ms: value })} /><Input label={zh ? '重试次数' : 'Retries'} value={form.retries} onChange={value => onFormChange({ retries: value })} /></div></details><div className="mt-4 flex justify-end gap-2"><button type="button" onClick={onCancelEditor} className="rounded-xl border border-slate-200 px-4 py-2.5 text-xs font-bold text-slate-600">{zh ? '取消' : 'Cancel'}</button><button type="button" onClick={() => void onSaveAndTest()} disabled={!editingId} className="inline-flex items-center gap-1.5 rounded-xl border border-cyan-200 bg-cyan-50 px-4 py-2.5 text-xs font-bold text-cyan-700 hover:border-cyan-300 disabled:cursor-not-allowed disabled:opacity-40"><TestTube2 size={14} />{editingId ? (zh ? '保存并测试' : 'Save & test') : (zh ? '保存后测试' : 'Save before test')}</button><button type="submit" className="inline-flex items-center gap-1.5 rounded-xl bg-cyan-600 px-4 py-2.5 text-xs font-bold text-white"><Save size={14} />{editingId ? (zh ? '保存版本' : 'Save variant') : (zh ? '创建版本' : 'Create variant')}</button></div></form>}
    </div>
    {!editorOpen && <div className="flex justify-end border-t border-slate-200 px-6 py-4"><button type="button" onClick={onClose} className="rounded-xl bg-cyan-600 px-4 py-2.5 text-xs font-bold text-white">{zh ? '完成' : 'Done'}</button></div>}
  </div>
</div>;
};

const COLLECTOR_FORM_DEFAULT = { name: '', code: '', site_id: '', collector_type: 'LOCAL', management_address: '', remote_write_endpoint: '', max_concurrency: '8', queue_disk_limit_mb: '2048', enabled: true };

interface CollectorManagementSectionProps { zh: boolean; collectors: CollectorRow[]; loading: boolean; runAction: MonitoringAction; }

const CollectorManagementSection: React.FC<CollectorManagementSectionProps> = ({ zh, collectors, loading, runAction }) => {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'enabled' | 'disabled'>('all');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [editorOpen, setEditorOpen] = useState(false);
  const [detail, setDetail] = useState<CollectorRow | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState({ ...COLLECTOR_FORM_DEFAULT });
  useEscapeClose(editorOpen, () => setEditorOpen(false));
  useEscapeClose(Boolean(detail), () => setDetail(null));
  const query = search.trim().toLowerCase();
  const visibleCollectors = collectors.filter(collector => { const matchesSearch = !query || [collector.name, collector.code, collector.site_id, collector.collector_type, collector.status].some(value => String(value || '').toLowerCase().includes(query)); const matchesStatus = statusFilter === 'all' || (statusFilter === 'enabled' ? enabled(collector.enabled) : !enabled(collector.enabled)); return matchesSearch && matchesStatus; });
  const onlineCount = collectors.filter(item => ['ONLINE', 'OK', 'PASS'].includes(String(item.status || '').toUpperCase())).length;
  const enabledCount = collectors.filter(item => enabled(item.enabled)).length;
  const totalPages = Math.max(1, Math.ceil(visibleCollectors.length / pageSize));
  const pagedCollectors = visibleCollectors.slice((page - 1) * pageSize, page * pageSize);
  useEffect(() => { setPage(1); }, [pageSize, search, statusFilter]);
  useEffect(() => { setPage(current => Math.min(current, totalPages)); }, [totalPages]);
  const openCreate = () => { setEditingId(null); setForm({ ...COLLECTOR_FORM_DEFAULT }); setEditorOpen(true); };
  const openEdit = (collector: CollectorRow) => { setEditingId(collector.id); setForm({ ...COLLECTOR_FORM_DEFAULT, ...collector, name: collector.name || '', code: collector.code || '', max_concurrency: String(collector.max_concurrency ?? 8), queue_disk_limit_mb: String(collector.queue_disk_limit_mb ?? 2048), enabled: enabled(collector.enabled) }); setEditorOpen(true); };
  const saveCollector = async (event: React.FormEvent) => { event.preventDefault(); const path = editingId ? `/api/monitoring/collectors/${editingId}` : '/api/monitoring/collectors'; const body = { ...form, max_concurrency: Number(form.max_concurrency) || 8, queue_disk_limit_mb: Number(form.queue_disk_limit_mb) || 2048 }; if (editingId) delete (body as Partial<typeof body>).code; if (await runAction(path, editingId ? 'PATCH' : 'POST', body)) setEditorOpen(false); };
  const deleteCollector = async (collector: CollectorRow) => { if (!window.confirm(zh ? `确定删除采集器“${collector.name}”吗？` : `Delete collector “${collector.name}”?`)) return; if (await runAction(`/api/monitoring/collectors/${collector.id}`, 'DELETE')) setDetail(null); };

  return <section className="space-y-4"><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><PlanStat label={zh ? '全部采集器' : 'All collectors'} value={collectors.length} tone="slate" /><PlanStat label={zh ? '已启用' : 'Enabled'} value={enabledCount} tone="emerald" /><PlanStat label={zh ? '在线' : 'Online'} value={onlineCount} tone="rose" /><PlanStat label={zh ? '待处理' : 'Needs attention'} value={Math.max(collectors.length - onlineCount, 0)} tone="amber" /></div><div className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-3 shadow-sm md:flex-row md:items-center md:justify-between"><div className="relative min-w-0 flex-1 md:max-w-md"><Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" /><input value={search} onChange={event => setSearch(event.target.value)} placeholder={zh ? '搜索名称、编码、站点或状态' : 'Search name, code, site, or status'} className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2 pl-9 pr-3 text-xs outline-none focus:border-cyan-400 focus:bg-white" /></div><div className="flex flex-wrap items-center gap-2"><SlidersHorizontal size={14} className="text-slate-400" /><select value={statusFilter} onChange={event => setStatusFilter(event.target.value as typeof statusFilter)} className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs"><option value="all">{zh ? '全部状态' : 'All status'}</option><option value="enabled">{zh ? '已启用' : 'Enabled'}</option><option value="disabled">{zh ? '已停用' : 'Disabled'}</option></select>{(search || statusFilter !== 'all') && <button type="button" onClick={() => { setSearch(''); setStatusFilter('all'); }} className="rounded-xl px-2.5 py-2 text-xs font-semibold text-slate-500 hover:bg-slate-100">{zh ? '重置' : 'Reset'}</button>}<button type="button" onClick={openCreate} className="inline-flex items-center gap-1.5 rounded-xl bg-cyan-600 px-3 py-2 text-xs font-bold text-white hover:bg-cyan-700"><Plus size={14} />{zh ? '新建采集器' : 'New collector'}</button></div></div><div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"><div className="hidden grid-cols-[minmax(220px,1.4fr)_1fr_1fr_0.8fr_0.8fr_220px] gap-3 border-b border-slate-100 bg-slate-50 px-5 py-3 text-[10px] font-bold uppercase tracking-wide text-slate-500 lg:grid"><span>{zh ? '采集器' : 'Collector'}</span><span>{zh ? '站点' : 'Site'}</span><span>{zh ? '类型' : 'Type'}</span><span>{zh ? '运行状态' : 'Runtime'}</span><span>{zh ? '启用' : 'Enabled'}</span><span className="text-right">{zh ? '操作' : 'Actions'}</span></div>{loading && <div className="p-10 text-center text-xs text-slate-400">{zh ? '正在加载采集器…' : 'Loading collectors…'}</div>}{!loading && collectors.length === 0 && <EmptyState zh={zh} label={zh ? '还没有采集器，点击“新建采集器”。' : 'No collectors yet. Create one to get started.'} />}{!loading && collectors.length > 0 && visibleCollectors.length === 0 && <EmptyState zh={zh} label={zh ? '没有匹配当前筛选条件的采集器。' : 'No collectors match the current filters.'} />}{!loading && pagedCollectors.map(collector => <div key={collector.id} className="grid gap-3 border-b border-slate-100 px-5 py-4 last:border-0 hover:bg-cyan-50/30 lg:grid-cols-[minmax(220px,1.4fr)_1fr_1fr_0.8fr_0.8fr_220px] lg:items-center"><div className="min-w-0"><p className="truncate text-sm font-bold text-slate-900">{collector.name}</p><p className="mt-1 truncate font-mono text-[11px] text-cyan-700">{collector.code}</p></div><div className="text-xs text-slate-600">{collector.site_id || '—'}</div><div className="text-xs text-slate-600">{displayCollectorType(collector.collector_type, zh)}</div><div><span className={`inline-flex rounded-full border px-2 py-1 text-[10px] font-bold ${statusTone(collector.status)}`}>{displayStatus(collector.status, zh)}</span></div><div><span className={`inline-flex rounded-full border px-2 py-1 text-[10px] font-bold ${enabled(collector.enabled) ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-slate-200 bg-slate-100 text-slate-500'}`}>{enabled(collector.enabled) ? (zh ? '是' : 'YES') : (zh ? '否' : 'NO')}</span></div><div className="flex flex-nowrap items-center justify-end gap-1"><button type="button" aria-label={zh ? '查看采集器' : 'View collector'} title={zh ? '查看采集器' : 'View collector'} onClick={() => setDetail(collector)} className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 text-slate-600 hover:border-cyan-300 hover:text-cyan-700"><Eye size={15} /></button><button type="button" aria-label={zh ? '编辑采集器' : 'Edit collector'} title={zh ? '编辑采集器' : 'Edit collector'} onClick={() => openEdit(collector)} className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 text-slate-600 hover:border-cyan-300 hover:text-cyan-700"><Pencil size={15} /></button><button type="button" aria-label={zh ? '测试采集器' : 'Test collector'} title={zh ? '测试采集器' : 'Test collector'} onClick={() => void runAction(`/api/monitoring/collectors/${collector.id}/test`)} className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-cyan-200 bg-cyan-50 text-cyan-700 hover:border-cyan-300"><ShieldCheck size={15} /></button><button type="button" aria-label={zh ? '删除采集器' : 'Delete collector'} title={zh ? '删除采集器' : 'Delete collector'} onClick={() => void deleteCollector(collector)} className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-rose-600 hover:bg-rose-50"><Trash2 size={15} /></button></div></div>)}<Pagination currentPage={page} totalItems={visibleCollectors.length} itemsPerPage={pageSize} onPageChange={setPage} onItemsPerPageChange={size => { setPageSize(size); setPage(1); }} language={zh ? 'zh' : 'en'} itemLabel={zh ? '个采集器' : 'collectors'} /></div>
    {editorOpen && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 p-4"><button type="button" aria-label={zh ? '关闭采集器编辑器' : 'Close collector editor'} onClick={() => setEditorOpen(false)} className="absolute inset-0 cursor-default" /><form onSubmit={saveCollector} className="relative z-10 flex max-h-[min(860px,calc(100vh-2rem))] w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"><div className="flex items-center justify-between border-b border-slate-200 px-6 py-4"><div><h2 className="text-base font-bold text-slate-900">{editingId ? (zh ? '编辑采集器' : 'Edit collector') : (zh ? '新建采集器' : 'New collector')}</h2><p className="mt-1 text-xs text-slate-500">{zh ? '配置采集器连接信息和运行参数。' : 'Configure collector connection and runtime settings.'}</p></div><button type="button" onClick={() => setEditorOpen(false)} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100"><X size={18} /></button></div><div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-6"><section><h3 className="mb-3 text-sm font-bold text-slate-900">{zh ? '基本信息' : 'Basic information'}</h3><div className="grid gap-3 sm:grid-cols-2"><Input label={zh ? '名称' : 'Name'} value={form.name} onChange={value => setForm({ ...form, name: value })} required /><Input label={zh ? '编码' : 'Code'} value={form.code} onChange={value => setForm({ ...form, code: value })} required /><Input label={zh ? '站点 ID' : 'Site ID'} value={form.site_id} onChange={value => setForm({ ...form, site_id: value })} /><Input label={zh ? '采集器类型' : 'Collector type'} value={form.collector_type} onChange={value => setForm({ ...form, collector_type: value })} /><Input label={zh ? '管理地址' : 'Management address'} value={form.management_address} onChange={value => setForm({ ...form, management_address: value })} /><Input label={zh ? '远程写入地址' : 'Remote write endpoint'} value={form.remote_write_endpoint} onChange={value => setForm({ ...form, remote_write_endpoint: value })} /></div><label className="mt-3 flex items-center gap-2 text-xs font-semibold text-slate-600"><input type="checkbox" checked={form.enabled} onChange={event => setForm({ ...form, enabled: event.target.checked })} className="h-4 w-4 accent-cyan-600" />{zh ? '启用采集器' : 'Enabled'}</label></section><section className="border-t border-slate-100 pt-5"><h3 className="mb-3 text-sm font-bold text-slate-900">{zh ? '运行参数' : 'Runtime settings'}</h3><div className="grid gap-3 sm:grid-cols-2"><Input label={zh ? '最大并发数' : 'Max concurrency'} value={form.max_concurrency} onChange={value => setForm({ ...form, max_concurrency: value })} /><Input label={zh ? '队列磁盘上限（MB）' : 'Queue disk limit (MB)'} value={form.queue_disk_limit_mb} onChange={value => setForm({ ...form, queue_disk_limit_mb: value })} /></div></section></div><div className="flex justify-end gap-2 border-t border-slate-200 px-6 py-4"><button type="button" onClick={() => setEditorOpen(false)} className="rounded-xl border border-slate-200 px-4 py-2.5 text-xs font-bold text-slate-600">{zh ? '取消' : 'Cancel'}</button><button type="submit" className="inline-flex items-center gap-2 rounded-xl bg-cyan-600 px-4 py-2.5 text-xs font-bold text-white"><Save size={14} />{editingId ? (zh ? '保存采集器' : 'Save collector') : (zh ? '创建采集器' : 'Create collector')}</button></div></form></div>}
    {detail && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 p-4"><button type="button" aria-label={zh ? '关闭采集器详情' : 'Close collector details'} onClick={() => setDetail(null)} className="absolute inset-0 cursor-default" /><div role="dialog" aria-modal="true" className="relative z-10 flex max-h-[min(860px,calc(100vh-2rem))] w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"><div className="flex items-start justify-between border-b border-slate-200 px-6 py-4"><div><p className="text-xs font-semibold text-cyan-700">{zh ? '采集器详情' : 'Collector details'}</p><h2 className="mt-1 text-lg font-bold text-slate-900">{detail.name}</h2><p className="mt-1 font-mono text-xs text-slate-500">{detail.code}</p></div><button type="button" onClick={() => setDetail(null)} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100"><X size={18} /></button></div><div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-6"><div className="grid gap-3 sm:grid-cols-2"><DetailItem label={zh ? '状态' : 'Status'} value={displayStatus(detail.status, zh)} /><DetailItem label={zh ? '站点' : 'Site'} value={detail.site_id || '—'} /><DetailItem label={zh ? '类型' : 'Type'} value={displayCollectorType(detail.collector_type, zh)} /><DetailItem label={zh ? '配置版本' : 'Config version'} value={detail.last_config_version ? `v${detail.last_config_version}` : '—'} /></div><div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs text-slate-600">{zh ? '远程写入地址等敏感连接信息不会在详情中回显。' : 'Sensitive connection details are not shown here.'}</div></div><div className="flex flex-wrap justify-end gap-2 border-t border-slate-200 px-6 py-4"><ActionButton icon={<TestTube2 size={13} />} label={zh ? '测试' : 'Test'} onClick={() => void runAction(`/api/monitoring/collectors/${detail.id}/test`)} /><ActionButton icon={<ShieldCheck size={13} />} label={zh ? '校验' : 'Validate'} onClick={() => void runAction(`/api/monitoring/collectors/${detail.id}/validate`)} /><ActionButton icon={<CloudCog size={13} />} label={zh ? '编译' : 'Compile'} onClick={() => void runAction(`/api/monitoring/collectors/${detail.id}/compile`)} /><ActionButton icon={<CheckCircle2 size={13} />} label={zh ? '发布' : 'Publish'} onClick={() => void runAction(`/api/monitoring/collectors/${detail.id}/publish`)} /><ActionButton icon={<Pencil size={13} />} label={zh ? '编辑' : 'Edit'} onClick={() => { setDetail(null); openEdit(detail); }} /></div></div></div>}
  </section>;
};

const Input: React.FC<{ label: string; value: string; onChange: (value: string) => void; required?: boolean; disabled?: boolean; placeholder?: string }> = ({ label, value, onChange, required, disabled, placeholder }) => <label className="block text-[10px] font-bold uppercase tracking-wide text-slate-500">{label}<input required={required} disabled={disabled} value={value} placeholder={placeholder} onChange={event => onChange(event.target.value)} className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-medium text-slate-800 outline-none focus:border-cyan-400 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500" /></label>;

const ActionButton: React.FC<{ icon: React.ReactNode; label: string; onClick: () => void; iconOnly?: boolean }> = ({ icon, label, onClick, iconOnly = false }) => <button type="button" aria-label={label} title={label} onClick={onClick} className={iconOnly ? 'inline-flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 text-slate-600 hover:border-cyan-300 hover:text-cyan-700' : 'inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1.5 text-[10px] font-bold text-slate-600 hover:border-cyan-300 hover:text-cyan-700'}>{icon}{!iconOnly && label}</button>;

const MetricCard: React.FC<{ icon: React.ReactNode; label: string; value: string | number }> = ({ icon, label, value }) => <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="flex items-center gap-2 text-xs font-bold text-slate-500">{icon}{label}</div><p className="mt-2 text-2xl font-extrabold text-slate-900">{value}</p></div>;

const EmptyState: React.FC<{ zh: boolean; label: string }> = ({ label }) => <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-12 text-center text-sm text-slate-400">{label}</div>;

export default MonitoringManagementPage;
