import { describe, expect, it } from 'vitest';
import { readExplicitTableData } from '../components/ui/TableExportMenu';
import { buildCmdbExportData, buildCmdbVlanExportData } from './cmdbExport';

describe('CMDB explicit table export mapping', () => {
  it('keeps split visible fields in header order without concatenating cell values', () => {
    const data = buildCmdbExportData([
      { hostname: 'core-sw-01', assetTag: 'NET-WH-001', category: 'switch', role: 'core', site: 'WH-DC-02J-01 · UU1' },
    ], [
      { key: 'hostname', header: '设备名称', value: row => row.hostname },
      { key: 'assetTag', header: '资产编号', value: row => row.assetTag },
      { key: 'category', header: '设备分类', value: row => row.category },
      { key: 'role', header: '设备角色', value: row => row.role },
      { key: 'site', header: '站点', value: row => row.site },
    ]);

    expect(readExplicitTableData(data)).toEqual({
      headers: ['设备名称', '资产编号', '设备分类', '设备角色', '站点'],
      rows: [['core-sw-01', 'NET-WH-001', 'switch', 'core', 'WH-DC-02J-01 · UU1']],
    });
  });

  it('marks credentials as sensitive and omits internal IDs and action columns', () => {
    const data = buildCmdbExportData([{ id: 'db-id', name: 'SSH', password: 'must-not-export' }], [
      { key: 'name', header: '凭据名称', value: row => row.name },
      { key: 'id', header: '内部 ID', value: row => row.id },
      { key: 'password', header: '密码', marker: 'sensitive', value: row => row.password },
      { key: 'actions', header: '操作', value: () => 'edit' },
    ]);

    expect(readExplicitTableData(data)).toEqual({
      headers: ['凭据名称', '密码'],
      rows: [['SSH', '']],
    });
  });

  it('splits VLAN summary fields and keeps every cell aligned with the visible export headers', () => {
    const data = buildCmdbVlanExportData([{
      vlan_id: 20,
      name: 'Users',
      device_hostname: 'core-sw-01',
      device_ip: '192.0.2.1',
      site_name: 'WH-DC-02J-01',
      vrf_name: 'CORP',
      prefixes: '10.20.0.0/24, 10.20.1.0/24',
      gateway: '10.20.0.1',
      svi_interfaces: 'Vlan20, Vlan21',
      port_details: 'core-sw-01:Gi1/0/1 uplink, core-sw-01:Gi1/0/2 host',
      endpoint_details: [{ source: 'arp', ip_address: '10.20.0.50', mac_address: '0011.2233.4455', interface_name: 'Gi1/0/2' }],
      business_systems: 'ERP, Billing',
      department: 'IT',
      owner: 'operator',
      highest_business_level: 'P1',
      port_count: 2,
      device_count: 1,
      undocumented_port_count: 1,
    }], true);

    expect(data.headers).toEqual([
      'VLAN ID', '名称', '设备名称', '设备 IP', '站点', 'VRF', '描述', '网段', '网关 IP', '网关设备', 'SVI 接口',
      '接入接口', '端口数', '设备数', '缺少描述数', '终端 IP', '终端 MAC', '业务系统', '部门', '负责人', '业务等级',
    ]);
    expect(data.rows[0]).toEqual([
      20, 'Users', 'core-sw-01', '192.0.2.1', 'WH-DC-02J-01', 'CORP', '—', '10.20.0.0/24 · 10.20.1.0/24',
      '10.20.0.1', '—', 'Vlan20 · Vlan21', 'Gi1/0/1 · Gi1/0/2', 2, 1, 1, '10.20.0.50', '0011.2233.4455',
      'ERP · Billing', 'IT', 'operator', 'P1',
    ]);
    expect(data.rows[0]).toHaveLength(data.headers.length);
    expect(data.headers).not.toContain('id');
  });
});
