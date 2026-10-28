import { describe, expect, it } from 'vitest';
import {
  buildDiscoveredEndpointQuery,
  getDiscoveryEvidenceLabel,
  getDiscoveryHostname,
  getDiscoveryPortLabel,
  getDiscoveryTypeLabel,
  normalizeDiscoveryOptions,
} from './ipamDiscoveryPresentation';

describe('discovered endpoint query and presentation', () => {
  it('sends the default IP view and combines server filters and pagination', () => {
    const query = buildDiscoveredEndpointQuery({
      siteId: 'site-1', vrfId: 'vrf-2', deviceId: 'device-3', query: ' 10.1.2.3 ',
      kind: 'ip', evidenceStatus: 'recent', registrationStatus: 'unregistered', page: 2, pageSize: 50,
    });
    expect(query.toString()).toBe('kind=ip&page=2&page_size=50&site_id=site-1&vrf_id=vrf-2&device_id=device-3&q=10.1.2.3&evidence_status=recent&registration_status=unregistered');
  });

  it('normalizes site and VRF options from supported response shapes', () => {
    expect(normalizeDiscoveryOptions({ items: [{ site_id: 's1', site_name: 'WH-DC-01' }] }, ['id', 'site_id'], ['name', 'site_name']))
      .toEqual([{ id: 's1', name: 'WH-DC-01' }]);
    expect(normalizeDiscoveryOptions([{ vrf_id: 'v1' }], ['id', 'vrf_id'], ['name', 'vrf_name']))
      .toEqual([{ id: 'v1', name: 'v1' }]);
  });

  it('keeps absent identity and port information explicitly unknown or pending', () => {
    expect(getDiscoveryHostname({ hostname: '' }, true)).toBe('未知');
    expect(getDiscoveryTypeLabel(true)).toBe('类型未知');
    expect(getDiscoveryPortLabel({ ip: '10.0.0.5', mac_observed_at: null, switch_port: null }, true)).toContain('无 MAC 表证据');
    expect(getDiscoveryEvidenceLabel('unknown', true)).toContain('不参与当前对账');
  });
});
