import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useMonitoring } from './useMonitoring';

const healthPayload = {
  items: [],
  total: 450,
  filters: { health_status: 'healthy', availability_status: 'all', collection_status: 'all' },
};

describe('useMonitoring health device pagination', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  it('sends a bounded limit and offset and preserves the total count', async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: async () => healthPayload,
    } as Response);
    const { result } = renderHook(() => useMonitoring({ isAuthenticated: false, activeTab: 'monitoring', language: 'en' }));

    let payload;
    await act(async () => {
      payload = await result.current.fetchMonitoringHealthDevices({ health_status: 'healthy', limit: 900, offset: 200 });
    });

    const requestUrl = new URL(String(vi.mocked(fetch).mock.calls[0][0]), 'http://localhost');
    expect(requestUrl.pathname).toBe('/api/monitoring/health-devices');
    expect(requestUrl.searchParams.get('health_status')).toBe('healthy');
    expect(requestUrl.searchParams.get('limit')).toBe('500');
    expect(requestUrl.searchParams.get('offset')).toBe('200');
    expect(payload?.total).toBe(450);
  });

  it('defaults to 200 rows from offset zero and retains the HTTP status for permission handling', async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => healthPayload,
    } as Response);
    const { result } = renderHook(() => useMonitoring({ isAuthenticated: false, activeTab: 'monitoring', language: 'en' }));

    await act(async () => {
      await result.current.fetchMonitoringHealthDevices();
    });

    let requestUrl = new URL(String(vi.mocked(fetch).mock.calls[0][0]), 'http://localhost');
    expect(requestUrl.searchParams.get('limit')).toBe('200');
    expect(requestUrl.searchParams.get('offset')).toBe('0');

    vi.mocked(fetch).mockResolvedValueOnce({
      ok: false,
      status: 403,
      json: async () => ({ detail: 'forbidden' }),
    } as Response);
    await expect(result.current.fetchMonitoringHealthDevices()).rejects.toMatchObject({ status: 403, message: 'forbidden' });
  });
});
