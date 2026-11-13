import { describe, expect, it } from 'vitest';
import {
  buildDiscoveredEndpointQuery,
  getDiscoveryCollectionStatusLabel,
  getDiscoveryEvidenceLabel,
  getDiscoveryHostname,
  getDiscoveryObservationSourceLabel,
  getDiscoveryPortLabel,
  getDiscoveryRegistrationLabel,
  getDiscoveryTypeLabel,
  normalizeDiscoveryOptions,
} from './ipamDiscoveryPresentation';

describe('discovered endpoint query and presentation', () => {
  it('sends the default IP view and combines server filters and pagination', () => {
    const query = buildDiscoveredEndpointQuery({
      siteId: 'site-1', vrfId: 'vrf-2', deviceId: 'device-3', query: ' 10.1.2.3 ',
      kind: 'ip', networkScope: 'business_vlan', endpointClass: 'all', evidenceStatus: 'recent', registrationStatus: 'unregistered', page: 2, pageSize: 50,
    });
    expect(query.toString()).toBe('kind=ip&network_scope=business_vlan&page=2&page_size=50&site_id=site-1&vrf_id=vrf-2&device_id=device-3&q=10.1.2.3&evidence_status=recent&registration_status=unregistered');
  });

  it('uses all authorized scopes only for MAC-only FDB observations', () => {
    const query = buildDiscoveredEndpointQuery({
      siteId: '', vrfId: '', deviceId: '', query: '',
      kind: 'mac', networkScope: 'business_vlan', endpointClass: 'all', evidenceStatus: '', registrationStatus: '', page: 1, pageSize: 20,
    });
    expect(query.get('network_scope')).toBe('all');
  });

  it('allows current IP observations outside mapped business prefixes to be reviewed explicitly', () => {
    const query = buildDiscoveredEndpointQuery({
      siteId: '', vrfId: '', deviceId: '', query: '',
      kind: 'ip', networkScope: 'all', endpointClass: 'all', evidenceStatus: '', registrationStatus: '', page: 1, pageSize: 20,
    });
    expect(query.get('network_scope')).toBe('all');
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
    expect(getDiscoveryPortLabel({ ip: '10.0.0.5', mac_observed_at: null, switch_port: null }, true)).toBe('端口待定位');
    expect(getDiscoveryEvidenceLabel('unknown', true)).toContain('不参与当前对账');
  });

  it('explains that MAC-only observations do not create IP records', () => {
    expect(getDiscoveryRegistrationLabel('not_applicable', true)).toBe('MAC 观察（未创建 IP）');
    expect(getDiscoveryEvidenceLabel('stale', true)).toBe('当前成功代次较早');
  });

  it('distinguishes ARP, IPv6 ND, and FDB observations in both languages', () => {
    expect(getDiscoveryObservationSourceLabel('arp', undefined, true)).toBe('ARP');
    expect(getDiscoveryObservationSourceLabel('ndp', undefined, true)).toBe('IPv6 邻居发现（ND）');
    expect(getDiscoveryObservationSourceLabel('fdb', undefined, true)).toBe('FDB / MAC 观察（不登记 IP）');
    expect(getDiscoveryObservationSourceLabel(undefined, 'fdb', true)).toBe('FDB / MAC 观察（不登记 IP）');
    expect(getDiscoveryObservationSourceLabel('ndp', undefined, false)).toBe('IPv6 Neighbor Discovery (ND)');
    expect(getDiscoveryObservationSourceLabel('fdb', undefined, false)).toBe('FDB / MAC observation (no IP registration)');
  });

  it('marks absent and unknown source types as pending without hiding their value', () => {
    expect(getDiscoveryObservationSourceLabel(undefined, undefined, true)).toBe('来源待确认');
    expect(getDiscoveryObservationSourceLabel(' ', 'ndp', true)).toBe('IPv6 邻居发现（ND）');
    expect(getDiscoveryObservationSourceLabel({ invalid: true }, 'ndp', true)).toBe('IPv6 邻居发现（ND）');
    expect(getDiscoveryObservationSourceLabel('vendor-x', undefined, false)).toBe('Source pending (vendor-x)');
  });

  it('labels collection scope and failure states without treating them as inferred VRFs', () => {
    expect(getDiscoveryCollectionStatusLabel('scope_unknown', true)).toBe('范围待确认');
    expect(getDiscoveryCollectionStatusLabel('failed', true)).toBe('采集失败');
    expect(getDiscoveryCollectionStatusLabel('vendor-state', false)).toBe('vendor-state');
  });
});
