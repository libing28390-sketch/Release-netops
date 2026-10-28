import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchAllPaginatedItems } from './pagination';

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe('fetchAllPaginatedItems', () => {
  it('retains the active filters and fetches every page until the reported total', async () => {
    localStorage.setItem('netops_token', 'test-token');
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ items: [{ id: 'a' }], total: 3 }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ items: [{ id: 'b' }, { id: 'c' }], total: 3 }) });
    vi.stubGlobal('fetch', fetchMock);

    const result = await fetchAllPaginatedItems<{ id: string }>(
      '/api/alerts', new URLSearchParams({ status: 'resolved', search: 'core switch' }), 2,
    );

    expect(result.map((row) => row.id)).toEqual(['a', 'b', 'c']);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const firstUrl = new URL(String(fetchMock.mock.calls[0][0]), 'http://localhost');
    const secondUrl = new URL(String(fetchMock.mock.calls[1][0]), 'http://localhost');
    expect(firstUrl.searchParams.get('status')).toBe('resolved');
    expect(firstUrl.searchParams.get('search')).toBe('core switch');
    expect(firstUrl.searchParams.get('page')).toBe('1');
    expect(firstUrl.searchParams.get('page_size')).toBe('2');
    expect(secondUrl.searchParams.get('page')).toBe('2');
    expect(secondUrl.searchParams.get('status')).toBe('resolved');
    expect(fetchMock.mock.calls[1][1]).toEqual({ headers: { Authorization: 'Bearer test-token' } });
  });

  it('reads CMDB pagination envelopes nested under data and fetches all filtered pages', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ success: true, data: { items: [{ id: 'site-1' }], total: 3 } }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ success: true, data: { items: [{ id: 'site-2' }, { id: 'site-3' }], total: 3 } }) });
    vi.stubGlobal('fetch', fetchMock);

    const result = await fetchAllPaginatedItems<{ id: string }>(
      '/api/cmdb/sites', new URLSearchParams({ q: 'warehouse' }), 2,
    );

    expect(result.map((row) => row.id)).toEqual(['site-1', 'site-2', 'site-3']);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(new URL(String(fetchMock.mock.calls[0][0]), 'http://localhost').searchParams.get('q')).toBe('warehouse');
    expect(new URL(String(fetchMock.mock.calls[1][0]), 'http://localhost').searchParams.get('page')).toBe('2');
  });

  it('reads success envelopes with data arrays and a top-level total', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ success: true, data: [{ id: 'change-1' }], total: 3 }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ success: true, data: [{ id: 'change-2' }, { id: 'change-3' }], total: 3 }) });
    vi.stubGlobal('fetch', fetchMock);

    const result = await fetchAllPaginatedItems<{ id: string }>(
      '/api/change-orders', new URLSearchParams({ status: 'approved' }), 2,
    );

    expect(result.map((row) => row.id)).toEqual(['change-1', 'change-2', 'change-3']);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(new URL(String(fetchMock.mock.calls[0][0]), 'http://localhost').searchParams.get('status')).toBe('approved');
    expect(new URL(String(fetchMock.mock.calls[1][0]), 'http://localhost').searchParams.get('page')).toBe('2');
  });

  it('supports a response-specific paginated collection key', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ devices: [{ id: 'device-1' }], total: 2 }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ devices: [{ id: 'device-2' }], total: 2 }) });
    vi.stubGlobal('fetch', fetchMock);

    const result = await fetchAllPaginatedItems<{ id: string }>(
      '/api/configs/backup-runs/run-1', new URLSearchParams({ site: 'WH-DC-01', status: 'failed' }), 1, { itemsKey: 'devices' },
    );

    expect(result.map((row) => row.id)).toEqual(['device-1', 'device-2']);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const firstUrl = new URL(String(fetchMock.mock.calls[0][0]), 'http://localhost');
    expect(firstUrl.searchParams.get('site')).toBe('WH-DC-01');
    expect(firstUrl.searchParams.get('status')).toBe('failed');
    expect(new URL(String(fetchMock.mock.calls[1][0]), 'http://localhost').searchParams.get('page')).toBe('2');
  });

  it('rejects when a later page fails so an incomplete export cannot download silently', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ items: [{ id: 'a' }], total: 2 }) })
      .mockResolvedValueOnce({ ok: false, status: 503 });
    vi.stubGlobal('fetch', fetchMock);

    await expect(fetchAllPaginatedItems('/api/audit/events', new URLSearchParams(), 1))
      .rejects.toThrow('Failed to fetch paginated items from /api/audit/events (HTTP 503)');
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('rejects a truncated result when the server total says more rows remain', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ items: [{ id: 'a' }], total: 2 }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ items: [], total: 2 }) });
    vi.stubGlobal('fetch', fetchMock);

    await expect(fetchAllPaginatedItems('/api/pam/sessions', new URLSearchParams(), 1))
      .rejects.toThrow('ended at 1 of 2 rows');
  });
});
