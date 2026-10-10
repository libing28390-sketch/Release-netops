import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { apiRequest } from '../../../api/http';
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
const ruleResult = {
  status: 'success',
  message: 'LibreNMS rule comware returned 1 hardware measurements',
  host: 'edge-01',
  version: '2c',
  matched_device_id: 'asset-1',
  matched_hostname: 'edge-01',
  identity: { sys_name: 'edge-01', sys_object_id: '1.3.6.1.4.1.25506.11.1.1' },
  rule: { id: 'comware', os_key: 'comware', vendor: 'h3c', platform: 'comware', source_path: 'resources/definitions/os_discovery/comware.yaml', source_commit: '6c26b4fe4a40f7b392c19c36a44257212736e38c' },
  rule_source_path: 'resources/definitions/os_discovery/comware.yaml',
  rule_source_commit: '6c26b4fe4a40f7b392c19c36a44257212736e38c',
  category_results: [{ source_type: 'librenms_rule', component_class: 'processor', status: 'success', reason: 'LibreNMS processor rule returned one row' }],
  sensor_count: 1,
  sensors: [{ source_type: 'librenms_rule', source_id: 'comware:processors:1', component_class: 'processor', measurement_type: 'cpu_usage_percent', sensor_name: 'CPU 0', group_name: 'processor', oid: '1.3.6.1.4.1.25506.2.6.1.1.1.1.6', index: [1], value: 20, raw_value: '20', unit: '%', quality: 'good', source_path: 'resources/definitions/os_discovery/comware.yaml', source_commit: '6c26b4fe4a40f7b392c19c36a44257212736e38c' }],
};

const savedResult: SnmpHardwareDiscoveryTestResult = {
  source: 'nexora_snmp',
  state: 'available',
  message: 'Saved LibreNMS-rule sample loaded',
  matched_device_id: 'asset-1',
  matched_hostname: 'edge-01',
  binding: null,
  engine: null,
  identity: { hostname: 'edge-01' },
  collection: {
    engine_status: 'local',
    sample_status: 'available',
    export_status: 'unverified',
    sync_status: 'not_applicable',
    last_discovered: null,
    last_polled: null,
    stale_after_seconds: 180,
  },
  health_graphs: [],
  hardware_sensors: [],
  processor_sensors: [],
  memory_pools: [],
  transceivers: [],
  wireless_sensors: [],
  sensor_count: 0,
  metric_summary: [],
};

describe('LiveWalkInspector LibreNMS rule flow', () => {
  it('runs only the pinned device rule and removes arbitrary OID controls', async () => {
    vi.mocked(apiRequest).mockResolvedValue({ success: true, data: ruleResult } as never);
    render(
      <LiveWalkInspector
        zh
        selectedDevice={device}
        showCandidateSelector={false}
        showHardwareValidationTab
        showSystemInfoTab
        initialTab="snmpwalk"
        showToast={vi.fn()}
      />,
    );

    expect(screen.queryByPlaceholderText(/OID/i)).toBeNull();
    expect(screen.queryByRole('button', { name: /查找 OID|从 MIB 库|常用 OID/i })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '运行硬件规则诊断' }));

    await screen.findAllByText('resources/definitions/os_discovery/comware.yaml');
    expect(screen.getByText('CPU 0')).toBeTruthy();
    expect(screen.getByText('1.3.6.1.4.1.25506.2.6.1.1.1.1.6.1')).toBeTruthy();
    const [url, options] = vi.mocked(apiRequest).mock.calls[0];
    expect(url).toBe('/api/platform-registry/snmp-librenms-rule-test');
    expect(JSON.parse(String(options?.body))).toEqual({ device_id: 'asset-1' });
    expect(String(options?.body)).not.toMatch(/oid|community|password|token/i);
    expect(vi.mocked(apiRequest).mock.calls.some(([path]) => path === '/api/platform-registry/snmp-walk-test')).toBe(false);
  });

  it('reads only saved samples through the rule-provenance diagnostic endpoint', async () => {
    vi.mocked(apiRequest).mockResolvedValue({ success: true, data: savedResult } as never);
    render(
      <LiveWalkInspector
        zh
        selectedDevice={device}
        showCandidateSelector={false}
        showHardwareValidationTab
        initialTab="validate"
        showToast={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '读取最新已保存样本' }));
    await waitFor(() => expect(vi.mocked(apiRequest)).toHaveBeenCalledTimes(1));
    expect(vi.mocked(apiRequest).mock.calls[0][0]).toBe('/api/platform-registry/snmp-hardware-discovery-test');
    expect(JSON.parse(String(vi.mocked(apiRequest).mock.calls[0][1]?.body))).toEqual({ device_id: 'asset-1' });
    expect(screen.queryByRole('button', { name: /SNMPWALK|Walk/i })).toBeNull();
  });

  it('uses the same rule inspector in editors without offering the custom IF-MIB probe', () => {
    render(
      <LiveWalkInspector
        zh
        selectedDevice={device}
        showCandidateSelector={false}
        initialTab="snmpwalk"
        showToast={vi.fn()}
      />,
    );

    expect(screen.getByRole('button', { name: '运行硬件规则诊断' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /验证接口 OID/i })).toBeNull();
    expect(screen.queryByPlaceholderText(/OID/i)).toBeNull();
  });
});
