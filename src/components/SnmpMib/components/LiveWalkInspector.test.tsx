import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { apiRequest } from '../../../api/http';
import { DEFAULT_INTERFACE_CONFIG } from './InterfaceConfigSection';
import LiveWalkInspector from './LiveWalkInspector';
import type { SnmpHardwareDiscoveryTestResult } from './hardwareDiagnosticTypes';

vi.mock('../../../api/http', () => ({
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
  apiRequest: vi.fn(),
}));

afterEach(() => cleanup());
beforeEach(() => vi.clearAllMocks());

const device = { device_id: 'asset-1', hostname: 'edge-01', ip_address: '192.0.2.10' };

const nativeResult: SnmpHardwareDiscoveryTestResult = {
  source: 'librenms_native',
  state: 'available',
  message: 'LibreNMS native result loaded',
  matched_device_id: 'asset-1',
  matched_hostname: 'edge-01',
  binding: null,
  engine: null,
  identity: { hostname: 'edge-01' },
  collection: {
    engine_status: 'connected',
    sample_status: 'available',
    export_status: 'unverified',
    sync_status: 'synced',
    last_discovered: null,
    last_polled: null,
    stale_after_seconds: 900,
  },
  health_graphs: [],
  hardware_sensors: [],
  processor_sensors: [{
    sensor_id: 4,
    sensor_descr: 'CPU 0 usage',
    sensor_current: 20,
    unit: '%',
    lastupdate: '2026-10-07T07:59:50Z',
    freshness: 'fresh',
    value_status: 'available',
    sample_age_seconds: 10,
  }],
  memory_pools: [],
  transceivers: [],
  wireless_sensors: [],
  sensor_count: 0,
  metric_summary: [],
};

describe('LiveWalkInspector native diagnostic flow', () => {
  it('reads the selected device native snapshot without passing SNMP credentials or calling the Python hardware test', async () => {
    vi.mocked(apiRequest).mockResolvedValue({ success: true, data: nativeResult } as never);
    render(
      <LiveWalkInspector
        zh
        selectedDevice={device}
        showCandidateSelector={false}
        showHardwareValidationTab
        librenmsHardwareDiscoveryTest
        metrics={[]}
        initialTab="validate"
        showToast={vi.fn()}
      />,
    );

    const readButton = await screen.findByRole('button', { name: '读取 LibreNMS 原生结果' });
    await waitFor(() => expect((readButton as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(readButton);

    await screen.findByText('CPU 0 usage');
    expect(screen.getByText('20 %')).toBeTruthy();
    expect(vi.mocked(apiRequest).mock.calls).toHaveLength(1);
    const [url, options] = vi.mocked(apiRequest).mock.calls[0];
    expect(url).toBe('/api/platform-registry/snmp-hardware-discovery-test');
    expect(JSON.parse(String(options?.body))).toEqual({ device_id: 'asset-1' });
    expect(String(options?.body)).not.toMatch(/community|password|token/i);
    expect(vi.mocked(apiRequest).mock.calls.some(([path]) => path === '/api/platform-registry/snmp-hardware-test')).toBe(false);
  });

  it('retires the old template hardware probe while keeping the generic Walk and IF-MIB validation controls', () => {
    render(
      <LiveWalkInspector
        zh
        selectedDevice={device}
        showCandidateSelector={false}
        showHardwareValidationTab
        metrics={[]}
        interfaceConfig={{ ...DEFAULT_INTERFACE_CONFIG, enabled: true }}
        initialTab="validate"
        showToast={vi.fn()}
      />,
    );

    expect(screen.getByRole('button', { name: '验证接口 OID' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'SNMPWALK 实时探测与抓取' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: '测试硬件指标' })).toBeNull();
    expect(screen.getByText(/硬件 OID 模板的即时 Python 探测已停用/)).toBeTruthy();
    expect(vi.mocked(apiRequest)).not.toHaveBeenCalled();
  });
});
