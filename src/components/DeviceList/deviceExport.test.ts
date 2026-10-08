import { describe, expect, it } from 'vitest';
import type { Device } from '../../types';
import { DEFAULT_COLUMNS } from './DeviceTable';
import { buildNetworkDeviceExportData, fetchAllNetworkDevicePages, filterNetworkDevicesForExport } from './deviceExport';

const device = (overrides: Partial<Device> = {}): Device => ({
  id: 'internal-device-id',
  hostname: 'core-sw-01',
  asset_tag: 'NET-WH-001',
  ip_address: '192.168.18.201',
  device_category: 'switch',
  role: 'core',
  connection_method: 'ssh',
  vendor: 'Cisco',
  platform: 'cisco_ios',
  model: 'C2960',
  version: '15.2',
  status: 'online',
  compliance: 'unknown',
  lifecycle_status: 'production',
  sn: '',
  uptime: '',
  site: 'WH-DC-02J-01',
  rack: 'R1',
  rack_unit: 'U1',
  tags: [{ id: 'internal-tag-id', category: 'role', code: 'core', label: 'Core', label_zh: '核心' }],
  tag_ids: ['internal-tag-id'],
  health_status: 'healthy',
  cpu_usage: 10,
  memory_usage: 45,
  collection_status: 'healthy',
  ...overrides,
} as Device);

describe('network device table export', () => {
  it('loads all API pages instead of reusing only the displayed page', async () => {
    const requestedPages: number[] = [];
    const records = await fetchAllNetworkDevicePages(async (page, pageSize) => {
      requestedPages.push(page);
      expect(pageSize).toBe(2);
      return page === 1
        ? { items: [{ id: 'one', hostname: 'one' }, { id: 'two', hostname: 'two' }], total: 3 }
        : { items: [{ id: 'three', hostname: 'three' }], total: 3 };
    }, 2);

    expect(requestedPages).toEqual([1, 2]);
    expect(records.map((item) => item.hostname)).toEqual(['one', 'two', 'three']);
  });

  it('exports each visible network-device field to its own matching column', () => {
    const allColumns = Object.fromEntries(
      Object.keys(DEFAULT_COLUMNS).map((key) => [key, true]),
    ) as typeof DEFAULT_COLUMNS;
    const result = buildNetworkDeviceExportData([device()], { columns: allColumns, language: 'zh' });
    const row = result.rows[0].map(String);

    expect(result.headers).toEqual([
      '设备名称', '资产编号', '管理 IP', '设备类别', '角色', '连接方式', '厂商', '型号', '软件版本',
      '命令/解析适配', '站点', '机柜', 'U 位', '标签', '在线状态',
      '健康状态', '生命周期', '连通性检查', '检查时间',
    ]);
    expect(row.slice(0, 9)).toEqual([
      'core-sw-01', 'NET-WH-001', '192.168.18.201', 'switch', 'core', 'SSH', 'Cisco', 'C2960', '15.2',
    ]);
    expect(row.slice(10, 14)).toEqual(['WH-DC-02J-01', '—', 'U1', '核心']);
    expect(row.slice(14)).toEqual(['在线', '健康', '已投产', '—', '—']);
    expect(result.headers).not.toContain('CPU');
    expect(result.headers).not.toContain('内存');
    expect(result.headers).not.toContain('平台');
    expect(result.headers).not.toContain('适配版本');
    expect(result.headers).not.toContain('适配来源');
    expect(result.headers).not.toContain('版本校验');
    expect(result.headers).not.toContain('ID');
    expect(row).not.toContain('internal-device-id');
    expect(row).not.toContain('internal-tag-id');
  });

  it('follows column visibility and current quick, lifecycle, and tag filters', () => {
    const visibleColumns = { ...DEFAULT_COLUMNS, vendor: false, adaptation: false, actions: false };
    const exported = buildNetworkDeviceExportData([device()], { columns: visibleColumns, language: 'en' });
    expect(exported.headers).not.toContain('Vendor');
    expect(exported.headers).not.toContain('Actions');

    const rows = [
      device(),
      device({ id: 'offline', hostname: 'offline', status: 'offline', tag_ids: [] }),
      device({ id: 'no-tag', hostname: 'no-tag', tag_ids: [] }),
      device({ id: 'other-lifecycle', hostname: 'other', lifecycle_status: 'maintenance' }),
    ];
    expect(filterNetworkDevicesForExport(rows, {
      quickFilter: 'all', lifecycleFilter: 'production', tagFilterIds: ['internal-tag-id'],
    }).map((item) => item.hostname)).toEqual(['core-sw-01']);
    expect(filterNetworkDevicesForExport(rows, {
      quickFilter: 'offline', lifecycleFilter: 'all', tagFilterIds: [],
    }).map((item) => item.hostname)).toEqual(['offline']);
  });

  it('exports the rack name instead of a rack code or internal rack id', () => {
    const result = buildNetworkDeviceExportData(
      [device({ rack: 'internal-rack-id', rack_id: 'internal-rack-id', rack_code: 'RACK-CODE', rack_name: 'Server Room A-01' })],
      { columns: { ...DEFAULT_COLUMNS, rack: true }, language: 'en' },
    );
    const rackIndex = result.headers.indexOf('Rack');

    expect(rackIndex).toBeGreaterThanOrEqual(0);
    expect(result.rows[0][rackIndex]).toBe('Server Room A-01');
    expect(result.rows[0]).not.toContain('internal-rack-id');
  });

  it('does not show a legacy rack code or id as a substitute for a missing rack name', () => {
    const result = buildNetworkDeviceExportData(
      [device({ rack: 'internal-rack-id', rack_id: 'internal-rack-id', rack_code: 'RACK-CODE-01', rack_name: '' })],
      { columns: { ...DEFAULT_COLUMNS, rack: true }, language: 'en' },
    );
    const rackIndex = result.headers.indexOf('Rack');

    expect(result.rows[0][rackIndex]).toBe('—');
    expect(result.rows[0]).not.toContain('internal-rack-id');
  });
});
