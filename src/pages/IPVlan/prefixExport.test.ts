import { describe, expect, it, vi } from 'vitest';
import { fetchAllPrefixPages, mapPrefixesForExport, serializePrefixCsv } from './prefixExport';

describe('prefix export', () => {
  it('fetches every filtered page in bounded batches', async () => {
    const response = (payload: unknown) => ({ ok: true, json: async () => payload }) as Response;
    const request = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(response({ items: [{ id: '1' }, { id: '2' }], total: 3, page: 1, page_size: 2 }))
      .mockResolvedValueOnce(response({ items: [{ id: '3' }], total: 3, page: 2, page_size: 2 }));

    const prefixes = await fetchAllPrefixPages('/api/ipam/subnets', { site: 'wh', q: 'core' }, {}, 'en', request);

    expect(prefixes.map((prefix) => prefix.id)).toEqual(['1', '2', '3']);
    expect(request).toHaveBeenCalledTimes(2);
    expect(String(request.mock.calls[0][0])).toContain('page_size=100');
    expect(String(request.mock.calls[0][0])).toContain('site=wh');
    expect(String(request.mock.calls[1][0])).toContain('page=2');
    expect(String(request.mock.calls[1][0])).toContain('page_size=2');
  });

  it('does not return partial pages when a later export page fails', async () => {
    const request = vi.fn<typeof fetch>()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ items: [{ id: '1' }], total: 2, page: 1, page_size: 1 }) } as Response)
      .mockResolvedValueOnce({ ok: false, json: async () => ({ detail: 'backend unavailable' }) } as Response);

    await expect(fetchAllPrefixPages('/api/ipam/subnets', {}, {}, 'en', request)).rejects.toThrow('backend unavailable');
  });

  it('maps one prefix per row and labels allocation statistics as export-time snapshots', () => {
    const exported = mapPrefixesForExport([{
      id: 'prefix-1',
      prefix: '10.0.0.0/24',
      status: 'active',
      site_name: 'WH',
      vrf_name: 'default',
      total_ips: 254,
      used_ips: 12,
      active_ips: 8,
      utilization: 4.7,
      traceable: 1,
    }], 'zh');

    expect(exported.rows).toHaveLength(1);
    expect(exported.rows[0][2]).toBe('10.0.0.0/24');
    expect(exported.rows[0][4]).toBe('IPv4');
    expect(exported.rows[0][5]).toBe('使用中');
    expect(exported.rows[0][7]).toBe('WH');
    expect(exported.rows[0][19]).toBe(254);
    expect(exported.rows[0][28]).toBe('是');
    expect(exported.headers[19]).toContain('导出时快照');
  });

  it('writes UTF-8 BOM, quotes CSV cells, and neutralizes formula-like text', () => {
    const exported = mapPrefixesForExport([{
      prefix: '10.0.0.0/24',
      description: '=HYPERLINK("https://example.invalid","open"),\nsecond line',
    }], 'en');
    const csv = serializePrefixCsv(exported);

    expect(csv.startsWith('\uFEFF')).toBe(true);
    expect(csv).toContain('"\'=HYPERLINK(""https://example.invalid"",""open""),\nsecond line"');
    expect(csv).toContain('"Prefix / CIDR"');
  });
});
