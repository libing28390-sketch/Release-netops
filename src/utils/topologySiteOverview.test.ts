import { describe, expect, it } from 'vitest';
import { buildTopologySiteOverview, getTopologySiteKey } from './topologySiteOverview';

describe('buildTopologySiteOverview', () => {
  it('derives every card metric from the currently filtered devices and links', () => {
    const sites = [
      { site_id: 'site-a', site_name: 'Site A', link_count: 99, offline_devices: 8, orphan_devices: 7, stale_links: 6 },
      { site_id: 'site-b', site_name: 'Site B', link_count: 88, offline_devices: 5, orphan_devices: 4, stale_links: 3 },
    ];
    const allDevices = [
      { id: 'a-online', site_id: 'site-a', status: 'online' },
      { id: 'a-offline', site_id: 'site-a', status: 'offline' },
      { id: 'b-online', site_id: 'site-b', status: 'online' },
    ];

    const overview = buildTopologySiteOverview(
      sites,
      allDevices.filter((device) => device.status === 'online'),
      [{ source_device_id: 'a-online', target_device_id: 'b-online', operational_state: 'up' }],
    );

    expect(overview.sites).toEqual([
      {
        id: 'site-a',
        name: 'Site A',
        deviceCount: 1,
        linkCount: 1,
        orphanCount: 0,
        offlineCount: 0,
        staleCount: 0,
      },
      {
        id: 'site-b',
        name: 'Site B',
        deviceCount: 1,
        linkCount: 1,
        orphanCount: 0,
        offlineCount: 0,
        staleCount: 0,
      },
    ]);
    expect(overview.connections).toEqual([{ source: 'site-a', target: 'site-b', count: 1, down: 0 }]);
  });

  it('counts visible orphans and stale links without falling back to API totals', () => {
    const overview = buildTopologySiteOverview(
      [{ site_id: 'site-a', site_name: 'Site A', orphan_devices: 99, stale_links: 99 }],
      [
        { id: 'a-1', site_id: 'site-a', status: 'online' },
        { id: 'a-2', site_id: 'site-a', status: 'offline' },
      ],
      [{ source_device_id: 'a-1', target_device_id: 'a-2', operational_state: 'stale' }],
    );

    expect(overview.sites[0]).toMatchObject({
      deviceCount: 2,
      linkCount: 1,
      orphanCount: 0,
      offlineCount: 1,
      staleCount: 1,
    });
  });

  it('does not keep empty site cards when a filter has no matching devices', () => {
    const overview = buildTopologySiteOverview(
      [{ site_id: 'site-a', site_name: 'Site A', link_count: 10 }],
      [],
      [],
    );

    expect(overview.sites).toEqual([]);
    expect(overview.connections).toEqual([]);
  });
});

describe('getTopologySiteKey', () => {
  it('uses the same site identity fallback order for devices and summaries', () => {
    expect(getTopologySiteKey({ site_code: 'branch-a', site_name: 'Branch A' })).toBe('branch-a');
    expect(getTopologySiteKey({ site_name: 'Branch A' })).toBe('Branch A');
    expect(getTopologySiteKey({})).toBe('unassigned');
  });
});
