import { describe, expect, it } from 'vitest';
import { buildComplianceExportData } from './complianceExport';

describe('buildComplianceExportData', () => {
  it('separates the visible rule/device details and excludes database identifiers', () => {
    const data = buildComplianceExportData([{
      id: 'finding-db-id', fingerprint: 'fingerprint-internal', rule_id: 'MGMT-001', device_id: 'device-db-id',
      title: 'Disable Telnet', description: 'Disable Telnet on managed devices.', severity: 'critical', category: 'Management Plane', status: 'open',
      first_seen: '2026-09-01T00:00:00Z', last_seen: '2026-09-02T00:00:00Z', last_seen_at: '2026-09-02T00:00:00Z',
      created_at: '2026-09-02T00:00:00Z', updated_at: '2026-09-02T00:00:00Z',
      hostname: 'core-sw-01', ip_address: '192.0.2.10', site: 'DC-1',
    }], 'zh');

    expect(data.headers).toEqual(['规则名称', '规则编号', '主机名', '管理 IP', '站点', '级别', '分类', '状态', '最近出现']);
    expect(data.rows[0]).toHaveLength(data.headers.length);
    expect(data.rows[0].slice(0, 8)).toEqual(['Disable Telnet', 'MGMT-001', 'core-sw-01', '192.0.2.10', 'DC-1', 'critical', 'Management Plane', 'open']);
    expect(data.rows[0].join(' ')).not.toContain('finding-db-id');
    expect(data.rows[0].join(' ')).not.toContain('device-db-id');
    expect(data.rows[0].join(' ')).not.toContain('fingerprint-internal');
  });
});
