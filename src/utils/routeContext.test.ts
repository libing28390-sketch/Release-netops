import { describe, expect, it } from 'vitest';
import { getRouteContext } from './routeContext';

describe('getRouteContext AI routes', () => {
  it('maps the security gateway route to the security tab', () => {
    expect(getRouteContext('/ai/security').activeTab).toBe('ai-security');
  });

  it('keeps the provider route as the provider tab', () => {
    expect(getRouteContext('/ai/providers').activeTab).toBe('ai-providers');
  });

  it('maps the product catalog route to the catalog tab', () => {
    expect(getRouteContext('/ai/catalog').activeTab).toBe('ai-catalog');
  });

  it('supports the legacy AI security tab identifier', () => {
    expect(getRouteContext('/ai-security').activeTab).toBe('ai-security');
  });
});

describe('getRouteContext platform management routes', () => {
  it('maps SNMP metric templates to the platform management tab', () => {
    expect(getRouteContext('/management/snmp-metric-templates').activeTab).toBe('snmp-metric-templates');
  });
});

describe('getRouteContext terminal access routes', () => {
  it('keeps favorites and personal history as peer access tabs', () => {
    expect(getRouteContext('/access/favorites').activeTab).toBe('access-favorites');
    expect(getRouteContext('/access/history').activeTab).toBe('access-history');
  });
});
