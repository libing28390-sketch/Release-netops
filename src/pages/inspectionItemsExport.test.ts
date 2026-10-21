import { describe, expect, it } from 'vitest';
import { buildInspectionItemsExportData, filterInspectionItems, getFriendlyInspectionVendor } from './inspectionItemsExport';

const items = [
  { id: 'item-db-id-1', name: 'cpu_usage', name_zh: 'CPU 使用率', category: 'Server', check_key: 'cpu', description: 'CPU load', method: 'Shell', vendor: 'Linux', warning_threshold: 80, critical_threshold: 95, script_id: 'script-db-id-1' },
  { id: 'item-db-id-2', name: 'if_errors', name_zh: '接口错误', category: 'Network', check_key: 'ifErrors', description: 'Interface errors', method: 'SNMP', vendor: 'cisco_ios', oid: '1.3.6.1.2', script_id: null },
];

describe('inspection item export', () => {
  it('uses the active local filters across the supplied pages', () => {
    const matches = filterInspectionItems(items, { category: 'Network', method: 'SNMP', vendor: 'Cisco', search: 'iferrors' });
    expect(matches.map((item) => item.name)).toEqual(['if_errors']);
    expect(getFriendlyInspectionVendor('cisco_ios')).toBe('Cisco');
  });

  it('splits composite columns and leaves database/script IDs out of exports', () => {
    const data = buildInspectionItemsExportData(items, [{ id: 'script-db-id-1', name: 'Linux health checks' }], 'zh');

    expect(data.headers).toEqual(['中文名称', '英文名称', '分类', '厂商', '检查 Key', '采集方式', '绑定脚本', 'OID', '警告阈值', '严重阈值', '描述']);
    expect(data.rows[0]).toHaveLength(data.headers.length);
    expect(data.rows[0]).toEqual(['CPU 使用率', 'cpu_usage', '服务器/主机', 'Linux', 'cpu', 'SHELL', 'Linux health checks', '—', '80%', '95%', 'CPU load']);
    expect(data.rows.map((row) => row.join(' ')).join(' ')).not.toContain('item-db-id');
    expect(data.rows.map((row) => row.join(' ')).join(' ')).not.toContain('script-db-id');
  });

  it('does not leak an unresolved internal script reference', () => {
    const data = buildInspectionItemsExportData([{ id: 'x', name: 'check', name_zh: '检查', script_id: 'unknown-script-id' }], [], 'en');
    expect(data.rows[0][6]).toBe('');
    expect(data.rows[0].join(' ')).not.toContain('unknown-script-id');
  });
});
