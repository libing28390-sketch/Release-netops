import type { TableExportData } from './ui/TableExportMenu';

export interface MonitoringScopeOption {
  value: string;
  label?: string;
}

export interface MonitoringPlanExportRow {
  id: string;
  name?: string;
  description?: string;
  enabled?: boolean | number | string;
  created_at?: string;
  updated_at?: string;
  config?: {
    modules?: unknown[];
    target_ips?: string[];
    target_scope?: Record<string, unknown>;
  };
}

export interface MonitoringHealthExportRow {
  assignment_id?: string;
  asset_id?: string;
  collector_id?: string;
  module_variant_id?: string;
  status?: string;
  error_code?: string | null;
  age_seconds?: number | null;
  device_health?: string;
  last_attempt_at?: string | null;
  duration_ms?: number | null;
  consecutive_failures?: number;
}

const valueLabel = (value: unknown) => String(value ?? '').trim();
const optionLabel = (options: MonitoringScopeOption[], value: unknown) => {
  const raw = valueLabel(value);
  return options.find(option => option.value === raw)?.label || raw;
};
const enabledValue = (value: unknown) => value === true || value === 1 || value === '1';

export function getMonitoringPlanScopeFields(
  plan: MonitoringPlanExportRow,
  options: { sites?: MonitoringScopeOption[]; roles?: MonitoringScopeOption[]; categories?: MonitoringScopeOption[]; platforms?: MonitoringScopeOption[] } = {},
  zh = true,
) {
  const scope = plan.config?.target_scope || {};
  const mode = String(scope.mode || 'all').toLowerCase();
  const typeLabels: Record<string, [string, string]> = {
    all: ['全部在线设备', 'All online devices'],
    composite: ['复合筛选', 'Combined filters'],
    ip: ['指定 IP / 设备', 'IP / device list'],
    site: ['单个站点', 'Single site'],
    role: ['单个角色', 'Single role'],
    tag: ['标签匹配', 'Tag matching'],
  };
  const type = (typeLabels[mode] || [mode || '全部在线设备', mode || 'All online devices'])[zh ? 0 : 1];
  const appliesToScope = (fieldMode: string) => mode === fieldMode || mode === 'composite';
  const siteValue = appliesToScope('site') ? scope.value ?? scope.site : scope.site;
  const roleValue = appliesToScope('role') ? scope.value ?? scope.role : scope.role;
  const categoryValue = scope.category ?? scope.device_type;
  const platformValue = scope.platform;
  const ips = mode === 'ip'
    ? (Array.isArray(scope.values) ? scope.values : plan.config?.target_ips || []).map(valueLabel).filter(Boolean).join(', ')
    : '';

  return {
    type,
    // Site IDs are implementation keys. Export/display only a configured human label.
    site: appliesToScope('site')
      ? (options.sites || []).find(option => option.value === valueLabel(siteValue))?.label || ''
      : '',
    role: appliesToScope('role') ? optionLabel(options.roles || [], roleValue) : '',
    deviceType: appliesToScope('composite') ? optionLabel(options.categories || [], categoryValue) : '',
    platform: appliesToScope('composite') ? optionLabel(options.platforms || [], platformValue) : '',
    ips,
  };
}

export function buildMonitoringPlanExportData(
  plans: MonitoringPlanExportRow[],
  testResults: Record<string, { valid?: boolean } | undefined>,
  scopeOptions: { sites?: MonitoringScopeOption[]; roles?: MonitoringScopeOption[]; categories?: MonitoringScopeOption[]; platforms?: MonitoringScopeOption[] },
  zh: boolean,
  formatDate: (value: string | undefined, zh: boolean) => string,
): TableExportData {
  return {
    headers: [
      zh ? '计划名称' : 'Plan name', zh ? '描述' : 'Description', zh ? '测试结果' : 'Test result',
      zh ? '范围类型' : 'Scope type', zh ? '站点' : 'Site', zh ? '角色' : 'Role',
      zh ? '设备类型' : 'Device type', zh ? '平台' : 'Platform', zh ? 'IP 地址' : 'IP addresses',
      zh ? '模块数量' : 'Module count', zh ? '状态' : 'Status', zh ? '最近更新' : 'Updated',
    ],
    rows: plans.map(plan => {
      const scope = getMonitoringPlanScopeFields(plan, scopeOptions, zh);
      const result = testResults[plan.id];
      return [
        plan.name || '—', plan.description || '—',
        result ? (result.valid ? (zh ? '测试通过' : 'PASS') : (zh ? '需处理' : 'ISSUE')) : '—',
        scope.type, scope.site || '—', scope.role || '—', scope.deviceType || '—', scope.platform || '—', scope.ips || '—',
        plan.config?.modules?.length || 0,
        enabledValue(plan.enabled) ? (zh ? '已启用' : 'ENABLED') : (zh ? '已停用' : 'DISABLED'),
        formatDate(plan.updated_at || plan.created_at, zh),
      ];
    }),
  };
}

export function buildMonitoringModuleExportData(
  modules: Array<{ id: string; module_key?: string; display_name?: string; vendor?: string; cli_platform?: string; metric_group?: string; enabled?: boolean | number | string }>,
  variants: Array<{ module_id: string }>,
  zh: boolean,
): TableExportData {
  return {
    headers: [zh ? '模块名称' : 'Module name', zh ? '模块 Key' : 'Module key', zh ? '厂商' : 'Vendor', zh ? '平台' : 'Platform', zh ? '指标类型' : 'Metric group', zh ? '采集版本数' : 'Variant count', zh ? '状态' : 'Status'],
    rows: modules.map(module => [
      module.display_name || '—', module.module_key || '—', module.vendor || 'generic', module.cli_platform || 'generic',
      module.metric_group || '—', variants.filter(variant => variant.module_id === module.id).length,
      enabledValue(module.enabled) ? (zh ? '已启用' : 'ENABLED') : (zh ? '已停用' : 'DISABLED'),
    ]),
  };
}

export function buildMonitoringCollectorExportData(
  collectors: Array<{ id?: string; site_id?: string; name?: string; code?: string; collector_type?: string; status?: string; enabled?: boolean | number | string }>,
  zh: boolean,
  displayType: (value: string | undefined, zh: boolean) => string,
  displayStatus: (value: string | undefined, zh: boolean) => string,
): TableExportData {
  return {
    // site_id is a database key without a human-readable site label, so it is omitted.
    headers: [zh ? '采集器名称' : 'Collector name', zh ? '采集器编码' : 'Collector code', zh ? '类型' : 'Type', zh ? '运行状态' : 'Runtime status', zh ? '启用' : 'Enabled'],
    rows: collectors.map(collector => [
      collector.name || '—', collector.code || '—', displayType(collector.collector_type, zh), displayStatus(collector.status, zh),
      enabledValue(collector.enabled) ? (zh ? '是' : 'YES') : (zh ? '否' : 'NO'),
    ]),
  };
}

export function buildMonitoringHealthExportData(
  items: MonitoringHealthExportRow[],
  zh: boolean,
  displayStatus: (value: string | undefined, zh: boolean) => string,
  formatDate: (value: string | undefined, zh: boolean) => string,
): TableExportData {
  return {
    // Assignment, asset, collector and variant IDs are system identifiers and are excluded.
    headers: [zh ? '设备健康' : 'Device health', zh ? '采集状态' : 'Collection status', zh ? '错误代码' : 'Error code', zh ? '最近成功（秒）' : 'Last success age (s)', zh ? '连续失败次数' : 'Consecutive failures', zh ? '最近尝试时间' : 'Last attempt', zh ? '耗时（毫秒）' : 'Duration (ms)'],
    rows: items.map(item => [
      displayStatus(item.device_health, zh), displayStatus(item.status, zh), item.error_code || '—',
      item.age_seconds == null ? '—' : String(Math.round(item.age_seconds)),
      item.consecutive_failures ?? 0, formatDate(item.last_attempt_at || undefined, zh), item.duration_ms == null ? '—' : item.duration_ms,
    ]),
  };
}
