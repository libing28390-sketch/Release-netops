import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useRackReadModel } from './useRackReadModel';

const apiResponse = (data: unknown, ok = true) => ({
  ok,
  status: ok ? 200 : 500,
  json: async () => ok ? ({ success: true, data }) : ({ success: false, detail: 'failed' }),
});

const summaryPage = {
  items: [{
    id: 'rack-1',
    name: 'A-01',
    datacenter: 'DC-A',
    room: '301',
    row: 'A',
    total_u: 42,
    description: '',
    status: 'active',
    created_at: '2026-08-28T00:00:00Z',
    updated_at: '2026-08-28T00:00:00Z',
    site_label: 'DC-A',
    device_count: 0,
    front_used: 0,
    rear_used: 0,
    used_u: 0,
    available_u: 42,
    u_utilization_pct: 0,
    power_used_watts: 0,
    power_utilization_pct: 0,
    monitored_device_count: 0,
    healthy_device_count: 0,
    offline_device_count: 0,
    unknown_monitoring_device_count: 0,
    unlinked_asset_count: 0,
    unmonitored_device_count: 0,
    invalid_device_count: 0,
    health_status: 'empty',
    data_quality_status: 'empty',
  }],
  total: 1,
  page: 1,
  page_size: 50,
};

const layout = {
  id: 'rack-1',
  name: 'A-01',
  datacenter: 'DC-A',
  room: '301',
  row: 'A',
  total_u: 42,
  description: '',
  status: 'active',
  devices: [],
  front_used: 0,
  rear_used: 0,
  total_used: 0,
  available_u: 42,
};

describe('useRackReadModel', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('loads summaries first and fetches a full layout only on demand', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(apiResponse(summaryPage))
      .mockResolvedValueOnce(apiResponse(layout));
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useRackReadModel({ page: 1, pageSize: 50 }));

    await waitFor(() => expect(result.current.summaryLoading).toBe(false));
    expect(result.current.racks).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain('/racks/summary?page=1&page_size=50');

    await act(async () => {
      await result.current.loadLayout('rack-1');
    });
    expect(result.current.layout?.id).toBe('rack-1');
    expect(fetchMock).toHaveBeenCalledTimes(2);

    await act(async () => {
      await result.current.loadLayout('rack-1');
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('surfaces a summary dependency failure with an explicit retry state', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(apiResponse(null, false)));

    const { result } = renderHook(() => useRackReadModel({ page: 1, pageSize: 500, health: 'offline' }));

    await waitFor(() => expect(result.current.summaryLoading).toBe(false));
    expect(result.current.summaryError).toBe('failed');
    expect(result.current.racks).toEqual([]);
  });

  it('does not let an older layout response overwrite the newer rack selection', async () => {
    let resolveOld: ((value: unknown) => void) | undefined;
    let resolveNew: ((value: unknown) => void) | undefined;
    const oldResponse = new Promise(resolve => { resolveOld = resolve; });
    const newResponse = new Promise(resolve => { resolveNew = resolve; });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(apiResponse(summaryPage))
      .mockReturnValueOnce(oldResponse)
      .mockReturnValueOnce(newResponse);
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useRackReadModel({ page: 1, pageSize: 50 }));
    await waitFor(() => expect(result.current.summaryLoading).toBe(false));

    const oldLoad = result.current.loadLayout('rack-old', true);
    const newLoad = result.current.loadLayout('rack-new', true);
    resolveNew?.(apiResponse({ ...layout, id: 'rack-new' }));
    await act(async () => { await newLoad; });
    expect(result.current.layout?.id).toBe('rack-new');

    resolveOld?.(apiResponse({ ...layout, id: 'rack-old' }));
    await act(async () => { await oldLoad; });
    expect(result.current.layout?.id).toBe('rack-new');
  });
});
