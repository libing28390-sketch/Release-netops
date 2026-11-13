import { describe, expect, it } from 'vitest';
import { readExplicitTableData } from './ui/TableExportMenu';
import {
  buildMonitoringCollectorExportData,
  buildMonitoringHealthExportData,
  buildMonitoringModuleExportData,
  buildMonitoringPlanExportData,
  getMonitoringPlanScopeFields,
} from './MonitoringManagementPage.export';

const formatDate = (value?: string) => value || '—';
const displayStatus = (value?: string) => value || '未知';
const displayType = (value?: string) => value || 'LOCAL';

describe('monitoring management table exports', () => {
  it('splits plan scope details, maps known site IDs to labels, and blanks unknown site IDs', () => {
    const plan = {
      id: 'plan-internal-id', name: 'WAN polling', description: 'Collect WAN metrics', enabled: true,
      updated_at: '2026-09-28', config: { modules: [{}, {}], target_scope: { mode: 'site', value: 'site-internal-id' } },
    };
    const data = buildMonitoringPlanExportData([plan], { 'plan-internal-id': { valid: true } }, {
      sites: [{ value: 'site-internal-id', label: 'WH DC 02' }], roles: [], categories: [], platforms: [],
    }, true, formatDate);
    const sanitized = readExplicitTableData(data);
    expect(sanitized.headers).toEqual(['计划名称', '描述', '测试结果', '范围类型', '站点', '角色', '设备类型', '平台', 'IP 地址', '模块数量', '状态', '最近更新']);
    expect(sanitized.rows[0]).toEqual(['WAN polling', 'Collect WAN metrics', '测试通过', '单个站点', 'WH DC 02', '—', '—', '—', '—', '2', '已启用', '2026-09-28']);
    expect(JSON.stringify(sanitized)).not.toContain('site-internal-id');

    const unknownSite = getMonitoringPlanScopeFields({ ...plan, config: { target_scope: { mode: 'site', value: 'unmapped-site-id' } } }, { sites: [] }, true);
    expect(unknownSite.site).toBe('');
  });

  it('keeps all filtered plan rows beyond the current visual page', () => {
    const plans = Array.from({ length: 27 }, (_, index) => ({ id: `plan-${index}`, name: `Plan ${index}`, enabled: true }));
    const data = buildMonitoringPlanExportData(plans, {}, { sites: [], roles: [], categories: [], platforms: [] }, false, formatDate);
    expect(data.rows).toHaveLength(27);
    expect(data.rows.at(-1)?.[0]).toBe('Plan 26');
  });

  it('splits module name/key and vendor/platform into separate export fields', () => {
    const modules = [
      { id: 'module-db-id', display_name: 'Cisco interfaces', module_key: 'if_mib', vendor: 'Cisco', cli_platform: 'ios', metric_group: 'interfaces', enabled: true },
      ...Array.from({ length: 24 }, (_, index) => ({ id: `module-${index}`, display_name: `Module ${index}`, module_key: `key-${index}` })),
    ];
    const data = buildMonitoringModuleExportData(modules, [{ module_id: 'module-db-id' }, { module_id: 'module-db-id' }], true);
    expect(data.headers).toEqual(['模块名称', '模块 Key', '厂商', '平台', '指标类型', '采集版本数', '状态']);
    expect(data.rows[0]).toEqual(['Cisco interfaces', 'if_mib', 'Cisco', 'ios', 'interfaces', 2, '已启用']);
    expect(data.rows).toHaveLength(25);
    expect(JSON.stringify(data)).not.toContain('module-db-id');
  });

  it('splits collector name and code while omitting site IDs and actions', () => {
    const collectors = [
      { id: 'collector-db-id', name: 'Primary', code: 'collector-primary', site_id: 'site-db-id', collector_type: 'REMOTE', status: 'ONLINE', enabled: true },
      ...Array.from({ length: 24 }, (_, index) => ({ id: `collector-${index}`, name: `Collector ${index}`, code: `collector-${index}`, site_id: `site-${index}` })),
    ];
    const data = buildMonitoringCollectorExportData(collectors, true, displayType, displayStatus);
    const sanitized = readExplicitTableData(data);
    expect(sanitized.headers).toEqual(['采集器名称', '采集器编码', '类型', '运行状态', '启用']);
    expect(sanitized.rows[0]).toEqual(['Primary', 'collector-primary', 'REMOTE', 'ONLINE', '是']);
    expect(sanitized.rows).toHaveLength(25);
    expect(JSON.stringify(sanitized)).not.toMatch(/collector-db-id|site-db-id|Actions/);
  });

  it('splits collection health error, age and failure count while excluding assignment IDs', () => {
    const items = [
      { assignment_id: 'assignment-db-id', asset_id: 'asset-db-id', collector_id: 'collector-db-id', module_variant_id: 'variant-db-id', device_health: 'HEALTHY', status: 'FAILED', error_code: 'TIMEOUT', age_seconds: 42.2, consecutive_failures: 3, last_attempt_at: '2026-09-28 10:00', duration_ms: 210 },
      ...Array.from({ length: 24 }, (_, index) => ({ assignment_id: `assignment-${index}`, asset_id: `asset-${index}`, collector_id: `collector-${index}`, module_variant_id: `variant-${index}` })),
    ];
    const data = buildMonitoringHealthExportData(items, true, displayStatus, formatDate);
    const sanitized = readExplicitTableData(data);
    expect(sanitized.headers).toEqual(['设备健康', '采集状态', '错误代码', '最近成功（秒）', '连续失败次数', '最近尝试时间', '耗时（毫秒）']);
    expect(sanitized.rows[0]).toEqual(['HEALTHY', 'FAILED', 'TIMEOUT', '42', '3', '2026-09-28 10:00', '210']);
    expect(sanitized.rows).toHaveLength(25);
    expect(JSON.stringify(sanitized)).not.toMatch(/assignment-db-id|asset-db-id|collector-db-id|variant-db-id/);
  });
});
