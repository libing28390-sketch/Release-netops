import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useInventory } from './useInventory';

const response = (payload: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: vi.fn().mockResolvedValue(payload),
}) as unknown as Response;

const devices = (start: number, count: number) => Array.from({ length: count }, (_, offset) => ({
  id: `device-${start + offset}`,
  hostname: `device-${start + offset}`,
  status: 'offline',
}));

describe('useInventory all-light mode', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('loads every page so access workspace is not capped at 200 devices', async () => {
    const requestedUrls: URL[] = [];
    vi.mocked(fetch).mockImplementation(async input => {
      const url = new URL(String(input), 'http://localhost');
      requestedUrls.push(url);
      const page = Number(url.searchParams.get('page'));
      return page === 1
        ? response({ items: devices(0, 200), total: 201 })
        : response({ items: devices(200, 1), total: 201 });
    });

    const { result } = renderHook(() => useInventory('all-light'));
    await act(async () => {
      await result.current.fetchDevicesData();
    });

    expect(requestedUrls).toHaveLength(2);
    expect(requestedUrls.map(url => url.searchParams.get('page'))).toEqual(['1', '2']);
    expect(requestedUrls.every(url => url.searchParams.get('page_size') === '200')).toBe(true);
    expect(requestedUrls.every(url => url.searchParams.get('mode') === 'light')).toBe(true);
    expect(result.current.devices).toHaveLength(201);
    expect(result.current.devices.at(-1)?.hostname).toBe('device-200');
    expect(result.current.devicesError).toBeNull();
  });

  it('loads every network-device page for quick operations using the lightweight projection', async () => {
    const requestedUrls: URL[] = [];
    vi.mocked(fetch).mockImplementation(async input => {
      const url = new URL(String(input), 'http://localhost');
      requestedUrls.push(url);
      const page = Number(url.searchParams.get('page'));
      return page === 1
        ? response({ items: devices(0, 200), total: 201 })
        : response({ items: devices(200, 1), total: 201 });
    });

    const { result } = renderHook(() => useInventory('all-network-light'));
    await act(async () => {
      await result.current.fetchDevicesData();
    });

    expect(requestedUrls).toHaveLength(2);
    expect(requestedUrls.every(url => url.searchParams.get('asset_type') === 'network_device')).toBe(true);
    expect(requestedUrls.every(url => url.searchParams.get('mode') === 'light')).toBe(true);
    expect(result.current.devices).toHaveLength(201);
    expect(result.current.devicesError).toBeNull();
  });

  it.each([
    ['all-network-light', 'light'],
    ['all-network-topology', 'topology'],
  ] as const)('excludes server records from %s', async (deviceFetchMode, requestMode) => {
    const networkDevice = {
      ...devices(0, 1)[0],
      role: 'switch',
      platform: 'cisco_ios',
      asset_type: 'network_device',
    };
    const serverAsset = {
      ...devices(1, 1)[0],
      role: 'server',
      platform: 'linux',
      asset_type: 'server',
    };
    const legacyServer = {
      ...devices(2, 1)[0],
      role: 'server',
      platform: 'linux',
      asset_type: 'network_device',
    };
    vi.mocked(fetch).mockResolvedValue(response({
      items: [networkDevice, serverAsset, legacyServer],
      total: 3,
    }));

    const { result } = renderHook(() => useInventory(deviceFetchMode));
    await act(async () => {
      await result.current.fetchDevicesData();
    });

    const requestedUrl = new URL(String(vi.mocked(fetch).mock.calls[0][0]), 'http://localhost');
    expect(requestedUrl.searchParams.get('asset_type')).toBe('network_device');
    expect(requestedUrl.searchParams.get('mode')).toBe(requestMode);
    expect(result.current.devices.map(device => device.id)).toEqual(['device-0']);
  });

  it('hides stale server devices and selections when a network-only refresh fails', async () => {
    vi.mocked(fetch).mockResolvedValue(response({ detail: 'temporarily unavailable' }, 503));
    const { result } = renderHook(() => useInventory('all-network-light'));
    const networkDevice = {
      ...devices(0, 1)[0],
      role: 'switch',
      platform: 'cisco_ios',
      asset_type: 'network_device',
    };
    const serverDevice = {
      ...devices(1, 1)[0],
      role: 'server',
      platform: 'linux',
      asset_type: 'server',
    };

    await act(async () => {
      result.current.setDevices([networkDevice, serverDevice] as never);
      result.current.setSelectedDevice(serverDevice as never);
    });

    expect(result.current.devices.map(device => device.id)).toEqual(['device-0']);
    expect(result.current.selectedDevice).toBeNull();
    await act(async () => {
      await result.current.fetchDevicesData();
    });

    expect(result.current.devices.map(device => device.id)).toEqual(['device-0']);
    expect(result.current.selectedDevice).toBeNull();
    expect(result.current.devicesError).toBe('temporarily unavailable');
  });

  it('loads every network-device page for topology while retaining interface telemetry', async () => {
    const requestedUrls: URL[] = [];
    const firstPage = devices(0, 200).map((device, index) => index === 0 ? {
      ...device,
      config_history: [{ id: 'snapshot-1' }],
      interface_data: [{ name: 'GigabitEthernet1/0/1', status: 'up' }],
    } : device);
    vi.mocked(fetch).mockImplementation(async input => {
      const url = new URL(String(input), 'http://localhost');
      requestedUrls.push(url);
      const page = Number(url.searchParams.get('page'));
      return page === 1
        ? response({ items: firstPage, total: 201 })
        : response({ items: devices(200, 1), total: 201 });
    });

    const { result } = renderHook(() => useInventory('all-network-topology'));
    await act(async () => {
      await result.current.fetchDevicesData();
    });

    expect(requestedUrls).toHaveLength(2);
    expect(requestedUrls.map(url => url.searchParams.get('page'))).toEqual(['1', '2']);
    expect(requestedUrls.every(url => url.searchParams.get('page_size') === '200')).toBe(true);
    expect(requestedUrls.every(url => url.searchParams.get('mode') === 'topology')).toBe(true);
    expect(requestedUrls.every(url => url.searchParams.get('asset_type') === 'network_device')).toBe(true);
    expect(result.current.devices).toHaveLength(201);
    expect(result.current.devices[0].config_history).toEqual([]);
    expect(result.current.devices[0].interface_data).toEqual([{ name: 'GigabitEthernet1/0/1', status: 'up' }]);
    expect(result.current.devicesError).toBeNull();
  });

  it('keeps the last complete device set if a later page fails', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(response({ items: devices(0, 200), total: 201 }))
      .mockResolvedValueOnce(response({ detail: 'temporarily unavailable' }, 503));

    const { result } = renderHook(() => useInventory('all-light'));
    await act(async () => {
      result.current.setDevices([{
        id: 'existing',
        hostname: 'previous-complete-result',
      } as never]);
    });
    await act(async () => {
      await result.current.fetchDevicesData();
    });

    expect(result.current.devices).toHaveLength(1);
    expect(result.current.devices[0].hostname).toBe('previous-complete-result');
    expect(result.current.devicesError).toBe('temporarily unavailable');
  });

  it('rejects a mixed snapshot when the total changes between pages', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(response({ items: devices(0, 200), total: 201 }))
      .mockResolvedValueOnce(response({ items: devices(200, 1), total: 202 }));

    const { result } = renderHook(() => useInventory('all-light'));
    await act(async () => {
      result.current.setDevices([{
        id: 'existing',
        hostname: 'previous-complete-result',
      } as never]);
    });
    await act(async () => {
      await result.current.fetchDevicesData();
    });

    expect(result.current.devices).toHaveLength(1);
    expect(result.current.devices[0].hostname).toBe('previous-complete-result');
    expect(result.current.devicesError).toBe('设备列表在加载期间发生变化，请刷新重试');
  });
});
