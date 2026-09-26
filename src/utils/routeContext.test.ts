import { describe, expect, it } from 'vitest';
import { getRouteContext } from './routeContext';

describe('getRouteContext AI routes', () => {
  it('maps the security gateway route to the security tab', () => {
    expect(getRouteContext('/ai/security').activeTab).toBe('ai-security');
  });

  it('keeps the provider route as the provider tab', () => {
    expect(getRouteContext('/ai/providers').activeTab).toBe('ai-providers');
  });

  it('maps the model health route to the health tab', () => {
    expect(getRouteContext('/ai/health').activeTab).toBe('ai-health');
  });

  it('maps the product catalog route to the catalog tab', () => {
    expect(getRouteContext('/ai/catalog').activeTab).toBe('ai-catalog');
  });

  it('supports the legacy AI security tab identifier', () => {
    expect(getRouteContext('/ai-security').activeTab).toBe('ai-security');
  });
});

describe('getRouteContext platform management routes', () => {
  it('redirects deprecated SNMP metric templates to the unified monitoring tab', () => {
    expect(getRouteContext('/management/snmp-metric-templates').activeTab).toBe('monitoring');
  });

  it('maps the email notification settings route to its dedicated page', () => {
    expect(getRouteContext('/management/notifications').activeTab).toBe('email-settings');
  });
});

describe('getRouteContext terminal access routes', () => {
  it('keeps favorites and personal history as peer access tabs', () => {
    expect(getRouteContext('/access/favorites').activeTab).toBe('access-favorites');
    expect(getRouteContext('/access/history').activeTab).toBe('access-history');
  });
});

describe('getRouteContext monitoring routes', () => {
  it('maps monitoring navigation targets to their rendered panels', () => {
    expect(getRouteContext('/monitor/telemetry').activeTab).toBe('monitoring');
    expect(getRouteContext('/monitor/servers').activeTab).toBe('server-monitoring');
    expect(getRouteContext('/monitor/networks').activeTab).toBe('inventory');
    expect(getRouteContext('/monitor/networks').subPage).toBe('devices');
    expect(getRouteContext('/monitor/dashboards').activeTab).toBe('monitoring-dashboards');
    expect(getRouteContext('/monitor/reports').activeTab).toBe('monitoring-reports');
    expect(getRouteContext('/monitor/reports/interfaces').subPage).toBe('interfaces');
    expect(getRouteContext('/monitor/reports/devices').subPage).toBe('devices');
    expect(getRouteContext('/monitor/reports/outbound').subPage).toBe('outbound');
    expect(getRouteContext('/monitor/collection-plans').activeTab).toBe('monitoring-plans');
    expect(getRouteContext('/monitor/modules').activeTab).toBe('monitoring-modules');
    expect(getRouteContext('/monitor/collectors').activeTab).toBe('monitoring-collectors');
    expect(getRouteContext('/monitor/collection-health').activeTab).toBe('monitoring-health');
    expect(getRouteContext('/monitor/topology').activeTab).toBe('topology');
  });
});
