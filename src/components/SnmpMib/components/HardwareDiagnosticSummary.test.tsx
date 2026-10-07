import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import HardwareDiagnosticSummary from './HardwareDiagnosticSummary';
import type {
  LibreNMSHardwareMetricSummary,
  LibreNMSHardwareSensor,
  SnmpHardwareDiscoveryTestResult,
} from './hardwareDiagnosticTypes';
import { getHardwareDiscoveryToast } from './hardwareDiagnosticUtils';

afterEach(() => cleanup());

const sensor = (overrides: Partial<LibreNMSHardwareSensor> = {}): LibreNMSHardwareSensor => ({
  sensor_id: 41,
  sensor_class: 'processor',
  sensor_descr: 'CPU 1 usage',
  sensor_type: 'cisco-cpu',
  sensor_current: 42,
  sensor_oid: '1.3.6.1.4.1.9.2.1.58.0',
  sensor_index: '1',
  lastupdate: '2026-10-07T08:00:00Z',
  data_origin: 'librenms_native',
  value_status: 'available',
  freshness: 'fresh',
  sample_age_seconds: 20,
  observed_at: '2026-10-07T08:00:00Z',
  ...overrides,
});

const metric = (overrides: Partial<LibreNMSHardwareMetricSummary> = {}): LibreNMSHardwareMetricSummary => ({
  key: 'processor',
  measurement_type: 'processor',
  unit: '',
  source: 'librenms_native',
  entity_count: 1,
  value_count: 1,
  fresh_count: 1,
  latest_sample_at: '2026-10-07T08:00:00Z',
  status: 'available',
  ...overrides,
});

const result = (overrides: Partial<SnmpHardwareDiscoveryTestResult> = {}): SnmpHardwareDiscoveryTestResult => ({
  source: 'librenms_native',
  state: 'available',
  message: 'Latest LibreNMS native result loaded',
  matched_device_id: 'nexora-device-1',
  matched_hostname: 'edge-01',
  binding: {
    id: 'binding-1',
    instance_id: 'instance-1',
    instance_name: 'Primary LibreNMS',
    native_device_id: '28',
    native_hostname: 'edge-01',
    collector_id: 'collector-a',
    poller_group: 'default',
    desired_state: 'enabled',
    sync_status: 'synced',
    last_sync_at: '2026-10-07T07:59:00Z',
    last_discovery_at: '2026-10-07T07:55:00Z',
    last_poll_at: '2026-10-07T08:00:00Z',
    last_error_code: '',
  },
  engine: {
    instance_id: 'instance-1',
    name: 'Primary LibreNMS',
    version: '26.9.1',
    commit: 'abcdef1',
    health_state: 'healthy',
  },
  identity: {
    native_device_id: '28',
    hostname: 'edge-01',
    display: 'edge-01.example.test',
    os: 'ios',
    version: '17.9.4',
    hardware: 'Catalyst 9300',
    sysObjectID: '1.3.6.1.4.1.9.1.1745',
  },
  collection: {
    engine_status: 'connected',
    sample_status: 'available',
    export_status: 'unverified',
    sync_status: 'synced',
    last_discovered: '2026-10-07T07:55:00Z',
    last_polled: '2026-10-07T08:00:00Z',
    stale_after_seconds: 900,
  },
  health_graphs: [],
  hardware_sensors: [sensor()],
  transceivers: [],
  wireless_sensors: [],
  sensor_count: 1,
  metric_summary: [metric()],
  ...overrides,
});

describe('HardwareDiagnosticSummary', () => {
  it('describes the action as a read of existing native results and shows sensor timestamps and OID/index', () => {
    render(<HardwareDiagnosticSummary zh result={result()} />);

    expect(screen.getByText('LibreNMS 原生硬件采集结果')).toBeTruthy();
    expect(screen.getByText(/不会立即发现设备或触发轮询/)).toBeTruthy();
    expect(screen.getByText('CPU 1 usage')).toBeTruthy();
    expect(screen.getByText('42')).toBeTruthy();
    expect(screen.getByText(/1.3.6.1.4.1.9.2.1.58.0 · 1/)).toBeTruthy();
    expect(screen.getAllByText(/原生样本/).length).toBeGreaterThan(0);
    expect(screen.getByText('Catalyst 9300')).toBeTruthy();
    expect(screen.queryByText(/实时读数与后台样本/)).toBeNull();
  });

  it('renders native sensor class aggregates and freshness without guessing units', () => {
    render(
      <HardwareDiagnosticSummary
        zh
        result={result({
          metric_summary: [metric({ entity_count: 3, value_count: 2, fresh_count: 1, status: 'stale' })],
          hardware_sensors: [sensor({ sensor_current: 0, freshness: 'stale', sample_age_seconds: 3601 })],
        })}
      />,
    );

    expect(screen.getAllByText('processor').length).toBeGreaterThan(0);
    expect(screen.getAllByText('样本已过期').length).toBeGreaterThan(0);
    expect(screen.getAllByText('3').length).toBeGreaterThan(0);
    expect(screen.getByText('2')).toBeTruthy();
    expect(screen.getByText(/样本时间/)).toBeTruthy();
    expect(screen.getAllByText('0').length).toBeGreaterThan(0);
    expect(screen.queryByText('0%')).toBeNull();
  });

  it('shows health graph names as metadata and explicitly says they are not CPU or memory readings', () => {
    render(
      <HardwareDiagnosticSummary
        zh
        result={result({
          state: 'metadata_only',
          message: 'LibreNMS has hardware metadata only',
          hardware_sensors: [],
          metric_summary: [],
          health_graphs: [{ health_type: 'processor', name: 'CPU Usage', desc: 'Processor utilization graph' }],
        })}
      />,
    );

    expect(screen.getByText('仅有元数据')).toBeTruthy();
    expect(screen.getByText(/不是数值样本/)).toBeTruthy();
    expect(screen.getByText('CPU Usage')).toBeTruthy();
    expect(screen.getByText(/没有返回 Processor 当前值/)).toBeTruthy();
    expect(screen.queryByText('42')).toBeNull();
  });

  it('renders native processor and memory current values with their own sample age and unit', () => {
    render(
      <HardwareDiagnosticSummary
        zh
        result={result({
          hardware_sensors: [],
          sensor_count: 2,
          metric_summary: [],
          processor_sensors: [{
            sensor_id: 3,
            sensor_descr: 'CPU 0 utilization',
            sensor_current: 37.5,
            unit: '%',
            lastupdate: '2026-10-07T08:00:00Z',
            freshness: 'fresh',
            value_status: 'available',
            sample_age_seconds: 20,
          }],
          memory_pools: [{
            sensor_id: 7,
            sensor_descr: 'Main memory pool',
            sensor_current: 0,
            unit: '%',
            lastupdate: '2026-10-07T07:00:00Z',
            freshness: 'stale',
            value_status: 'available',
            sample_age_seconds: 3620,
          }],
        })}
      />,
    );

    expect(screen.getByText('CPU 0 utilization')).toBeTruthy();
    expect(screen.getByText('37.5 %')).toBeTruthy();
    expect(screen.getByText('Main memory pool')).toBeTruthy();
    expect(screen.getByText('0 %')).toBeTruthy();
    expect(screen.getAllByText(/新鲜/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/已过期/).length).toBeGreaterThan(0);
    expect(screen.getByTitle('2026-10-07T08:00:00Z')).toBeTruthy();
    expect(screen.getByTitle('2026-10-07T07:00:00Z')).toBeTruthy();
  });

  it('keeps no-binding, unavailable-engine, and no-native-data states explicit', () => {
    const { rerender } = render(
      <HardwareDiagnosticSummary
        zh
        result={result({ state: 'not_bound', message: '该设备尚未绑定 LibreNMS 原生实例', binding: null, engine: null })}
      />,
    );
    expect(screen.getByText('未绑定')).toBeTruthy();
    expect(screen.getByText('该设备尚未绑定 LibreNMS 原生实例')).toBeTruthy();

    rerender(
      <HardwareDiagnosticSummary
        zh
        result={result({ state: 'engine_unavailable', message: '无法连接 LibreNMS', hardware_sensors: [], metric_summary: [] })}
      />,
    );
    expect(screen.getByText('引擎不可用')).toBeTruthy();

    rerender(
      <HardwareDiagnosticSummary
        zh
        result={result({ state: 'no_native_hardware_data', message: '暂无原生硬件结果', hardware_sensors: [], metric_summary: [] })}
      />,
    );
    expect(screen.getByText(/不能据此断定设备不支持硬件监控/)).toBeTruthy();
  });

  it('shows loading, permission-denied, and request failure states accessibly', () => {
    const { rerender } = render(<HardwareDiagnosticSummary zh result={null} loading />);
    expect(screen.getByRole('status').textContent).toContain('读取 LibreNMS');

    rerender(<HardwareDiagnosticSummary zh result={null} error={{ message: '无权读取 LibreNMS 原生结果', permissionDenied: true }} />);
    expect(screen.getByRole('alert').textContent).toContain('无权读取 LibreNMS 原生结果');

    rerender(<HardwareDiagnosticSummary zh={false} result={null} error={{ message: 'LibreNMS request failed', permissionDenied: false }} />);
    expect(screen.getByRole('alert').textContent).toContain('LibreNMS request failed');
  });

  it('copies only the native diagnostic contract and redacts sensitive assignments', async () => {
    const user = userEvent.setup();
    const onCopy = vi.fn();
    render(
      <HardwareDiagnosticSummary
        zh
        result={result({
          message: 'password=NeverShareThis',
          hardware_sensors: [sensor({ sensor_descr: 'Secret sensor password=HiddenValue' })],
          processor_sensors: [{
            sensor_id: 88,
            sensor_descr: 'CPU api_token=NativeSecret',
            sensor_current: 25,
            unit: '%',
            value_status: 'available',
            freshness: 'fresh',
          }],
        })}
        onCopy={onCopy}
      />,
    );

    expect(screen.getByRole('status').textContent).toContain('password=[REDACTED]');
    expect(screen.queryByText(/NeverShareThis/)).toBeNull();
    expect(screen.getByText(/Secret sensor password=\[REDACTED\]/)).toBeTruthy();

    await user.click(screen.getByRole('button', { name: '复制脱敏诊断 JSON' }));

    expect(onCopy).toHaveBeenCalledOnce();
    const payloadText = onCopy.mock.calls[0][0];
    const payload = JSON.parse(payloadText) as {
      source: string;
      state: string;
      hardware_sensors: LibreNMSHardwareSensor[];
      processor_sensors: Array<Record<string, unknown>>;
    };
    expect(payload.source).toBe('librenms_native');
    expect(payload.state).toBe('available');
    expect(payload.hardware_sensors[0].data_origin).toBe('librenms_native');
    expect(payload.processor_sensors[0].sensor_current).toBe(25);
    expect(payload.processor_sensors[0].sensor_descr).toBe('CPU api_token=[REDACTED]');
    expect(payloadText).toContain('[REDACTED]');
    expect(payloadText).not.toContain('NeverShareThis');
    expect(payloadText).not.toContain('HiddenValue');
    expect(payloadText).not.toContain('NativeSecret');
    expect(payloadText).not.toContain('probe_evidence');
  });
});

describe('getHardwareDiscoveryToast', () => {
  it('marks fresh native readings successful and stale or metadata-only results informational', () => {
    const fresh = getHardwareDiscoveryToast(result(), true);
    expect(fresh.type).toBe('success');
    expect(fresh.message).toContain('新鲜数值');

    const stale = getHardwareDiscoveryToast(result({
      metric_summary: [metric({ fresh_count: 0, status: 'stale' })],
      hardware_sensors: [sensor({ freshness: 'stale' })],
    }), false);
    expect(stale.type).toBe('info');
    expect(stale.message).toContain('stale');

    const metadata = getHardwareDiscoveryToast(result({ state: 'metadata_only', hardware_sensors: [], metric_summary: [] }), false);
    expect(metadata.type).toBe('info');
    expect(metadata.message).toContain('metadata');

    const processor = getHardwareDiscoveryToast(result({
      state: 'available',
      hardware_sensors: [],
      metric_summary: [],
      processor_sensors: [{ value_status: 'available', freshness: 'fresh', sensor_current: 13 }],
    }), true);
    expect(processor.type).toBe('success');
    expect(processor.message).toContain('1 个有新鲜数值');
  });

  it('classifies binding and engine failures as errors without claiming an SNMP probe failed', () => {
    const failed = getHardwareDiscoveryToast(result({ state: 'engine_unavailable', message: 'API timeout' }), false);
    expect(failed.type).toBe('error');
    expect(failed.message).toContain('native result could not be read');
    expect(failed.message).not.toContain('SNMP probe failed');
  });
});
