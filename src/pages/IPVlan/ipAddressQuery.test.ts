import { describe, expect, it } from 'vitest';
import { buildIPAddressInventoryQuery } from './ipAddressQuery';

describe('IPAM address inventory query', () => {
  it('keeps read-only interface observations visible and preserves filters', () => {
    const query = buildIPAddressInventoryQuery({
      siteId: 'site-1', prefixId: 'prefix-2', search: ' 10.2.3.4 ',
      statusFilter: 'active', typeFilter: 'server', purposeFilter: 'business', isMatrixView: false,
    });
    expect(query.get('registered_only')).toBe('false');
    expect(query.get('site_id')).toBe('site-1');
    expect(query.get('prefix_id')).toBe('prefix-2');
    expect(query.get('q')).toBe('10.2.3.4');
    expect(query.get('status')).toBe('active');
    expect(query.get('device_type')).toBe('server');
    expect(query.get('purpose')).toBe('business');
  });

  it('keeps matrix availability search and scope while skipping incompatible list filters', () => {
    const query = buildIPAddressInventoryQuery({
      siteId: 'site-2', prefixId: 'prefix-3', search: 'edge',
      statusFilter: 'available', typeFilter: 'router', purposeFilter: 'infrastructure', isMatrixView: true,
    });
    expect(query.get('registered_only')).toBe('false');
    expect(query.get('site_id')).toBe('site-2');
    expect(query.get('prefix_id')).toBe('prefix-3');
    expect(query.get('q')).toBe('edge');
    expect(query.has('status')).toBe(false);
    expect(query.has('device_type')).toBe(false);
    expect(query.has('purpose')).toBe(false);
  });
});
