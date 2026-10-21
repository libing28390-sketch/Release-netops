import { describe, expect, it } from 'vitest';
import { getRackSiteLabel } from './siteLabel';

describe('getRackSiteLabel', () => {
  it('shows the configured default site name instead of its internal code', () => {
    const sites = new Map([
      ['site-default', { id: 'site-default', site_code: 'default_site', site_name: '默认站点' }],
    ]);

    expect(getRackSiteLabel({
      site_id: 'site-default',
      site_code: 'default_site',
      datacenter: 'default_site',
    }, sites)).toBe('默认站点');
  });

  it('uses the rack API name before a code when the site directory is not loaded', () => {
    expect(getRackSiteLabel({ site_name: '默认站点', site_code: 'default_site' }, new Map()))
      .toBe('默认站点');
  });

  it('falls back to the site code or datacenter when the name is unavailable', () => {
    expect(getRackSiteLabel({ site_code: 'site-a', datacenter: 'dc-a' }, new Map())).toBe('site-a');
    expect(getRackSiteLabel({ datacenter: 'dc-a' }, new Map())).toBe('dc-a');
  });
});
