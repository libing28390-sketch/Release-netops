import { describe, expect, it } from 'vitest';
import { buildAccessCenterExportData } from './exportData';

const devices = Array.from({ length: 25 }, (_, index) => ({
  hostname: `edge-${index + 1}`,
  ip_address: `192.0.2.${index + 1}`,
  status: 'online' as const,
  platform: 'Cisco IOS',
  vendor: 'Cisco',
  management_port: 22,
  site_name: 'WH-DC-01',
  connection_method: 'ssh',
  web_http_enabled: true,
  web_https_enabled: false,
}));

describe('buildAccessCenterExportData', () => {
  it('exports all filtered records and separates device, address, and protocol fields', () => {
    const result = buildAccessCenterExportData(devices, 'SSH', true);
    expect(result.headers).toEqual(['设备名称', '平台', '厂商', '在线状态', '管理 IP', '端口', '站点', '协议']);
    expect(result.rows).toHaveLength(25);
    expect(result.rows[0]).toEqual(['edge-1', 'Cisco IOS', 'Cisco', '在线', '192.0.2.1', 22, 'WH-DC-01', 'SSH']);
  });

  it('splits every capability in the aggregate view', () => {
    const result = buildAccessCenterExportData(devices, 'ALL', false);
    expect(result.headers.slice(-4)).toEqual(['SSH', 'RDP', 'HTTP', 'HTTPS']);
    expect(result.rows[0].slice(-4)).toEqual(['Enabled', 'Disabled', 'Enabled', 'Disabled']);
  });
});
