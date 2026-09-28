import { describe, expect, it } from 'vitest';
import { buildAssetExportData, fetchAllAssetPages, type AssetExportColumn } from './exportUtils';
import type { Asset } from './types';

const splitColumns: AssetExportColumn[] = [
  { key: 'hostname', zh: '设备', en: 'Device' },
  { key: 'asset_tag', zh: '资产编号', en: 'Asset tag' },
  { key: 'asset_type', zh: '资产类型', en: 'Asset type' },
  { key: 'device_category', zh: '设备分类', en: 'Category' },
  { key: 'device_role', zh: '设备角色', en: 'Role' },
  { key: 'site', zh: '站点', en: 'Site' },
  { key: 'rack', zh: '机柜', en: 'Rack' },
  { key: 'rack_unit', zh: 'U位', en: 'Rack U' },
];

describe('asset table export contract', () => {
  it('requests every page for the active filter result before exporting', async () => {
    const allAssets = Array.from({ length: 2305 }, (_, index) => ({
      id: `asset-${index + 1}`,
      hostname: `device-${index + 1}`,
    } as Asset));
    const requestedPages: number[] = [];

    const loaded = await fetchAllAssetPages(async (page, pageSize) => {
      requestedPages.push(page);
      const start = (page - 1) * pageSize;
      return { items: allAssets.slice(start, start + pageSize), total: allAssets.length };
    }, 1000, 2);

    expect(requestedPages).toEqual([1, 2, 3]);
    expect(loaded).toEqual(allAssets);
  });

  it('keeps each visible business field in its own column and excludes database IDs', () => {
    const asset = {
      id: 'internal-asset-id',
      hostname: 'core-sw-01',
      asset_tag: 'NET-WH-001',
      asset_type: 'network_device',
      device_category: 'switch',
      device_role: 'core',
      site_id: 'internal-site-id',
      site_name: 'WH-DC-02J-01',
      rack: 'RACK-01',
      rack_unit: '1',
    } as Asset;

    const exported = buildAssetExportData([asset], splitColumns, 'zh');

    expect(exported.headers).toEqual(['设备', '资产编号', '资产类型', '设备分类', '设备角色', '站点', '机柜', 'U位']);
    expect(exported.rows).toEqual([[
      'core-sw-01',
      'NET-WH-001',
      '网络设备',
      '交换机',
      'core',
      'WH-DC-02J-01',
      'RACK-01',
      'U1',
    ]]);
    expect(exported.rows[0]).toHaveLength(exported.headers.length);
    expect(JSON.stringify(exported)).not.toContain('internal-asset-id');
    expect(JSON.stringify(exported)).not.toContain('internal-site-id');
  });

  it('does not export a site ID when no business site label is available', () => {
    const asset = {
      id: 'internal-asset-id',
      site_id: 'internal-site-id',
      site_name: '',
      site_code: '',
      rack: '',
      rack_unit: '',
    } as Asset;

    const exported = buildAssetExportData([asset], [splitColumns[5]], 'en');

    expect(exported.headers).toEqual(['Site']);
    expect(exported.rows).toEqual([['—']]);
  });

  it.each(['15', 'U15', 'UU15'])('normalizes rack unit %s to one U prefix', (rackUnit) => {
    const asset = { rack_unit: rackUnit } as Asset;
    const exported = buildAssetExportData([asset], [splitColumns[7]], 'en');

    expect(exported.rows).toEqual([['U15']]);
  });
});
