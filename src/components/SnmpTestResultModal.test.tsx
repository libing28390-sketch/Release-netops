import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import SnmpTestResultModal from './SnmpTestResultModal';

afterEach(() => cleanup());

describe('SnmpTestResultModal', () => {
  it('reports reachability only, hides credentials and legacy hardware values, and links to native diagnostics', () => {
    render(
      <SnmpTestResultModal
        open
        language="zh"
        onClose={() => undefined}
        result={{
          success: true,
          response_ms: 18,
          ip: '192.0.2.15',
          community: 'NeverShowThisCommunity',
          port: 161,
          sys_name: 'edge-01',
          hardware_metrics: { cpu: 97, memory: 83 },
          hardware_collection_status: 'failed',
          metric_profile_id: 'legacy-profile-1',
          metric_profile_source: 'snmp_template',
          collection_mode: 'full',
        }}
      />,
    );

    expect(screen.getByText('SNMP 连通成功')).toBeTruthy();
    expect(screen.getByText('192.0.2.15')).toBeTruthy();
    expect(screen.getByText('161')).toBeTruthy();
    expect(screen.getByText('edge-01')).toBeTruthy();
    expect(screen.getByRole('link', { name: '/monitor/snmp-walk SNMP 诊断' }).getAttribute('href')).toBe('/monitor/snmp-walk');
    expect(screen.getByRole('note').textContent).toContain('不读取硬件指标');
    expect(screen.queryByText('Community')).toBeNull();
    expect(screen.queryByText('NeverShowThisCommunity')).toBeNull();
    expect(screen.queryByText('硬件健康采集')).toBeNull();
    expect(screen.queryByText('CPU 使用率')).toBeNull();
    expect(screen.queryByText(/模板 ID/)).toBeNull();
    expect(screen.queryByText(/硬件指标采集失败/)).toBeNull();
  });

  it('shows the native-results route even when the connectivity test fails', () => {
    render(
      <SnmpTestResultModal
        open
        language="en"
        onClose={() => undefined}
        result={{ success: false, ip: '192.0.2.15', error: 'timeout; community=NeverShowThisCommunity' }}
      />,
    );

    expect(screen.getByText('SNMP Unreachable')).toBeTruthy();
    expect(screen.getByRole('link', { name: '/monitor/snmp-walk SNMP Diagnostics' }).getAttribute('href')).toBe('/monitor/snmp-walk');
    expect(screen.getByText('timeout; community=[REDACTED]')).toBeTruthy();
    expect(screen.queryByText(/NeverShowThisCommunity/)).toBeNull();
  });
});
