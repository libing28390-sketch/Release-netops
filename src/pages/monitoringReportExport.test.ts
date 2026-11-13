import { describe, expect, it } from 'vitest';
import { buildMonitoringReportExportData } from './monitoringReportExport';

describe('buildMonitoringReportExportData', () => {
  it('splits interface identity, location, traffic, and sample fields and keeps every row', () => {
    const data = buildMonitoringReportExportData([
      { id: 'db-1', hostname: 'core-1', vendor: 'Cisco', ip_address: '192.0.2.1', site_name: 'DC-1', role: 'core', interface_name: 'Gi0/1', description: 'uplink', oper_status: 'UP', speed_str: '1 Gbps', in_bps_str: '10 Mbps', out_bps_str: '20 Mbps', max_util: 80, total_errors: 2, alert_level: 'WARNING', advice: 'Inspect link', sample_quality: 'GOOD', sample_time: '2026-09-28T00:00:00Z' },
      { id: 'db-2', hostname: 'core-2', vendor: 'Cisco', ip_address: '192.0.2.2', site_name: 'DC-2', role: 'edge', interface_name: 'Gi0/2' },
    ], 'interfaces', 'en');

    expect(data.headers).toEqual([
      'Device name', 'Vendor', 'Management IP', 'Site', 'Role', 'Interface', 'Description', 'Oper status', 'Physical speed', 'Inbound traffic', 'Outbound traffic', 'Peak bandwidth utilization', 'Errors', 'Alert level', 'Advice', 'Sample quality', 'Sample time',
    ]);
    expect(data.rows).toHaveLength(2);
    expect(data.rows[0]).toEqual(expect.arrayContaining(['core-1', '192.0.2.1', 'DC-1', 'core', '10 Mbps', '20 Mbps', '80.0%', '2', 'Warning', 'Inspect link']));
    expect(data.headers).not.toContain('id');
  });

  it('splits device and outbound composite fields into distinct headers', () => {
    const devices = buildMonitoringReportExportData([
      { id: 'db-3', hostname: 'sw-1', ip_address: '192.0.2.3', vendor: 'Cisco', platform: 'ios', site_name: 'DC-1', role: 'core', status: 'ONLINE', cpu_usage: 25, memory_usage: 44, temperature_str: '35 C', risk_level: 'NORMAL', advice: 'Healthy', sample_quality: 'GOOD' },
    ], 'devices', 'zh');
    expect(devices.headers).toContain('管理 IP');
    expect(devices.headers).toContain('角色');
    expect(devices.rows[0]).toHaveLength(devices.headers.length);
    expect(devices.headers).not.toContain('设备名称 / 管理 IP');

    const outbound = buildMonitoringReportExportData([
      { id: 'db-4', name: 'WAN-1', isp: 'ISP-A', target: '198.51.100.1', target_type: 'ICMP', active_str: 'Enabled', latency_ms: 12, packet_loss: 0, health_grade: 'Healthy' },
    ], 'outbound', 'en');
    expect(outbound.headers).toContain('Target address');
    expect(outbound.headers).toContain('Protocol');
    expect(outbound.rows[0]).toHaveLength(outbound.headers.length);
  });
});
