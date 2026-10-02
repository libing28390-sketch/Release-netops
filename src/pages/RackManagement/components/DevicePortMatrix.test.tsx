import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DevicePortMatrix } from './DevicePortMatrix';
import { loadDeviceTelemetry } from '../adapters/snmpTelemetry';

vi.mock('../adapters/snmpTelemetry', () => ({
  loadDeviceTelemetry: vi.fn(),
}));

const loadMock = vi.mocked(loadDeviceTelemetry);

describe('DevicePortMatrix truthful telemetry states', () => {
  afterEach(() => cleanup());

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders only interfaces returned by monitoring', async () => {
    loadMock.mockResolvedValue({
      status: 'ready',
      data: {
        deviceId: 'network-device-1',
        hostname: 'SW-CORE-01',
        ipAddress: '10.0.0.1',
        platform: 'h3c_comware',
        status: 'online',
        source: 'IF-MIB',
        sampledAt: new Date().toISOString(),
        queriedAt: new Date().toISOString(),
        isStale: false,
        interfaces: [{
          name: 'GigabitEthernet1/0/48',
          shortName: 'GE1/0/48',
          status: 'up',
          speedMbps: 1000,
        }],
        upCount: 1,
        downCount: 0,
      },
    });

    render(<DevicePortMatrix deviceId="network-device-1" deviceName="SW-CORE-01" zh />);

    await waitFor(() => expect(screen.getByText('1 个已验证接口')).toBeTruthy());
    expect(screen.getByTitle('GigabitEthernet1/0/48 (UP)')).toBeTruthy();
    expect(screen.queryByText('MGMT:')).toBeNull();
    expect(screen.queryByText('CONSOLE:')).toBeNull();
    expect(screen.queryByTitle('GigabitEthernet1/0/0 (UP)')).toBeNull();
  });

  it('shows an honest empty state without creating demo ports', async () => {
    loadMock.mockResolvedValue({ status: 'empty', data: null, reason: 'no_recent_samples' });

    render(<DevicePortMatrix deviceId="network-device-1" deviceName="SW-CORE-01" zh />);

    await waitFor(() => expect(screen.getByText('最近 15 分钟没有可用的物理接口采样')).toBeTruthy());
    expect(screen.getByText('系统不会用演示端口填补缺失数据')).toBeTruthy();
    expect(screen.queryAllByRole('button')).toHaveLength(0);
  });

  it('offers a retry when telemetry fails', async () => {
    loadMock
      .mockResolvedValueOnce({ status: 'error', data: null, message: 'offline' })
      .mockResolvedValueOnce({ status: 'empty', data: null, reason: 'not_registered' });

    render(<DevicePortMatrix deviceId="network-device-1" deviceName="SW-CORE-01" zh />);

    await waitFor(() => expect(screen.getByText('接口遥测请求失败，当前状态未知')).toBeTruthy());
    fireEvent.click(screen.getByText('重试遥测'));
    await waitFor(() => expect(loadMock).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByText('设备未关联监控对象，无法读取接口遥测')).toBeTruthy());
  });
});
