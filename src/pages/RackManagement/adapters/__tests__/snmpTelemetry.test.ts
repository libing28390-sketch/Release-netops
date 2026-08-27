import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../helpers', () => ({ authHeaders: () => ({ Authorization: 'Bearer test' }) }));

describe('fetchDeviceTelemetry', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.restoreAllMocks();
  });

  it('prefers the stable monitoring device id over a similar hostname', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          items: [
            { id: 'device-wrong', hostname: 'sw-core-01-lab' },
            { id: 'device-right', hostname: 'sw-core-01' },
          ],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          device: {
            hostname: 'sw-core-01',
            interface_data: [{ name: 'GigabitEthernet1/0/1', status: 'up' }],
          },
        }),
      });
    vi.stubGlobal('fetch', fetchMock);

    const { fetchDeviceTelemetry } = await import('../snmpTelemetry');
    const result = await fetchDeviceTelemetry('SW-CORE-01', 'device-right');

    expect(fetchMock.mock.calls[1][0]).toBe('/api/monitoring/device/device-right/realtime?window_minutes=15&limit=100');
    expect(result?.deviceId).toBe('device-right');
    expect(result?.interfaces[0].shortName).toBe('GE1/0/1');
  });

  it('does not treat an empty registry hostname as a fuzzy match', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({ items: [{ id: 'unrelated-device', hostname: '' }] }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { fetchDeviceTelemetry } = await import('../snmpTelemetry');
    const result = await fetchDeviceTelemetry('SW-NOT-REGISTERED');

    expect(result).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
