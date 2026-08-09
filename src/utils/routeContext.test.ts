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
