import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  buildVisibleIpamExportData,
  fetchAllIpamExportItems,
  fetchAllIpamReconciliationItems,
  type IpamExportColumn,
} from './ipamExport';

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  document.body.innerHTML = '';
});

describe('IPAM export', () => {
  it('keeps list filters and authorization on every exported page', async () => {
    localStorage.setItem('netops_token', 'test-token');
    const response = (payload: unknown) => ({ ok: true, json: async () => payload }) as Response;
    const request = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(response({ items: [{ id: 'prefix-a' }], total: 2, page: 1, page_size: 100 }))
      .mockResolvedValueOnce(response({ items: [{ id: 'prefix-b' }], total: 2, page: 2, page_size: 100 }));
    vi.stubGlobal('fetch', request);

    const items = await fetchAllIpamExportItems<{ id: string }>(
      '/api/ipam/subnets',
      new URLSearchParams({ site: 'site-a', q: '10.18.0', classification: 'unclassified' }),
    );

    expect(items.map((item) => item.id)).toEqual(['prefix-a', 'prefix-b']);
    expect(request).toHaveBeenCalledTimes(2);
    for (const [url, init] of request.mock.calls) {
      const parsed = new URL(String(url), 'http://localhost');
      expect(parsed.searchParams.get('site')).toBe('site-a');
      expect(parsed.searchParams.get('q')).toBe('10.18.0');
      expect(parsed.searchParams.get('classification')).toBe('unclassified');
      expect(parsed.searchParams.get('page_size')).toBe('100');
      expect(init?.headers).toEqual({ Authorization: 'Bearer test-token' });
    }
    expect(new URL(String(request.mock.calls[0][0]), 'http://localhost').searchParams.get('page')).toBe('1');
    expect(new URL(String(request.mock.calls[1][0]), 'http://localhost').searchParams.get('page')).toBe('2');
  });

  it('loads all filtered reconciliation pages from the tab-specific response shape', async () => {
    localStorage.setItem('netops_token', 'test-token');
    const response = (payload: unknown) => ({ ok: true, json: async () => payload }) as Response;
    const request = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(response({ undocumented_endpoints: [{ ip: '10.0.0.1' }, { ip: '10.0.0.2' }], result_total: 3, page: 1, page_size: 100 }))
      .mockResolvedValueOnce(response({ undocumented_endpoints: [{ ip: '10.0.0.3' }], result_total: 3, page: 2, page_size: 100 }));

    const items = await fetchAllIpamReconciliationItems<{ ip: string }>(
      '/api/ipam/reconciliation',
      new URLSearchParams({ active_tab: 'undocumented', q: 'core switch' }),
      'undocumented',
      request,
    );

    expect(items.map((item) => item.ip)).toEqual(['10.0.0.1', '10.0.0.2', '10.0.0.3']);
    expect(request).toHaveBeenCalledTimes(2);
    const firstUrl = new URL(String(request.mock.calls[0][0]), 'http://localhost');
    const secondUrl = new URL(String(request.mock.calls[1][0]), 'http://localhost');
    expect(firstUrl.searchParams.get('active_tab')).toBe('undocumented');
    expect(firstUrl.searchParams.get('q')).toBe('core switch');
    expect(firstUrl.searchParams.get('page')).toBe('1');
    expect(secondUrl.searchParams.get('page')).toBe('2');
    expect(request.mock.calls[0][1]).toEqual({ headers: { Authorization: 'Bearer test-token' } });
  });

  it.each(['never_observed', 'unscoped', 'unavailable'] as const)('exports all pages for the %s evidence category', async (tab) => {
    const request = vi.fn<typeof fetch>()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ [tab]: [{ ip: '10.0.0.1' }], result_total: 2 }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ [tab]: [{ ip: '10.0.0.2' }], result_total: 2 }) } as Response);
    const items = await fetchAllIpamReconciliationItems<{ ip: string }>('/api/ipam/reconciliation', new URLSearchParams({ active_tab: tab }), tab, request);
    expect(items).toHaveLength(2);
    expect(request).toHaveBeenCalledTimes(2);
  });

  it('rejects incomplete reconciliation exports instead of returning partial pages', async () => {
    const request = vi.fn<typeof fetch>()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ stale_ip_addresses: [{ address: '10.0.0.1' }], result_total: 2 }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ stale_ip_addresses: [], result_total: 2 }) } as Response);

    await expect(fetchAllIpamReconciliationItems<{ address: string }>(
      '/api/ipam/reconciliation', new URLSearchParams({ active_tab: 'stale' }), 'stale', request,
    )).rejects.toThrow('ended at 1 of 2 rows');
    expect(request).toHaveBeenCalledTimes(2);
  });

  it('exports only the visible table headers and maps rows in that exact order', () => {
    const table = document.createElement('table');
    table.innerHTML = '<thead><tr><th>IP Address</th><th>Internal ID</th><th style="display:none">Hidden</th><th class="nx-action-column-header">Actions</th></tr></thead>';
    document.body.append(table);

    type ExportRow = { address: string; id: string; hidden: string };
    const columns: IpamExportColumn<ExportRow>[] = [
      { header: 'IP Address', value: (item) => item.address },
      { header: 'Internal ID', value: (item) => item.id },
      { header: 'Hidden', value: (item) => item.hidden },
    ];
    const records: ExportRow[] = [
      { address: '10.0.0.1', id: 'ip-internal-id', hidden: 'not visible' },
    ];
    const exported = buildVisibleIpamExportData(table, columns, records);

    expect(exported.headers).toEqual(['IP Address']);
    expect(exported.rows).toEqual([['10.0.0.1']]);
  });
});
