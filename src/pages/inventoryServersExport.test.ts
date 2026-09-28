import { describe, expect, it } from 'vitest';
import { buildInventoryServersExportData, filterInventoryServers } from './inventoryServersExport';

const servers = [
  { id: 'db-row-1', hostname: 'web-01', management_ip: '10.0.0.1', device_role: 'web', vendor: 'Dell', model: 'R650', datacenter: 'dc-a', rack: 'r1', rack_unit: 12, status: 'active', department: 'IT' },
  { id: 'db-row-2', hostname: 'web-02', management_ip: '10.0.0.2', device_role: 'web', vendor: 'Dell', model: 'R650', datacenter: 'dc-a', rack: 'r1', rack_unit: 13, status: 'inactive', department: 'IT' },
];

describe('buildInventoryServersExportData', () => {
  it('splits visible composite server fields and excludes the internal ID', () => {
    const data = buildInventoryServersExportData(servers, { language: 'zh', quickFilter: 'all' });

    expect(data.headers).toEqual(['主机名', '管理 IP', '角色', '厂商', '型号', '数据中心', '机柜', 'U 位', '状态', 'Ping', 'SSH', '部门']);
    expect(data.rows[0]).toEqual(['web-01', '10.0.0.1', 'web', 'Dell', 'R650', 'dc-a', 'r1', 'U12', '在线', '—', '—', 'IT']);
    expect(data.rows[0]).not.toContain('db-row-1');
  });

  it('exports every input row after applying the active quick filter and sort', () => {
    const data = buildInventoryServersExportData(servers, {
      language: 'en',
      quickFilter: 'offline',
      sortConfig: { key: 'hostname', direction: 'desc' },
      verification: { 'db-row-2': { ping: true, ssh: false } },
    });

    expect(data.rows).toHaveLength(1);
    expect(data.rows[0]).toEqual(['web-02', '10.0.0.2', 'web', 'Dell', 'R650', 'dc-a', 'r1', 'U13', 'Offline', 'OK', 'FAIL', 'IT']);
  });

  it('applies server, vendor, and client-side datacenter filters together', () => {
    const matches = filterInventoryServers(servers, {
      quickFilter: 'all',
      statusFilter: 'inactive',
      vendorFilter: 'Dell',
      datacenterFilter: 'dc-a',
    });
    expect(matches.map((server) => server.hostname)).toEqual(['web-02']);
  });
});
