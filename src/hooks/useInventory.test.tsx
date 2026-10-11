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
