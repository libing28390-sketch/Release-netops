import { describe, expect, it } from 'vitest';
import {
  buildDiscoveredEndpointQuery,
  getEndpointClassLabel,
  getEndpointClassReason,
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
    expect(getDiscoveryEvidenceLabel('unknown', true)).toContain('暂不参与对账');
  });

  it('uses operator-facing endpoint labels without claiming a host is online', () => {
    expect(getEndpointClassLabel('infrastructure', true)).toBe('基础设施 IP');
    expect(getEndpointClassLabel('access_host', true)).toBe('已定位接入口');
    expect(getEndpointClassLabel('candidate', true)).toBe('接入口待定位');
    expect(getEndpointClassLabel('mac_only', true)).toBe('仅有 MAC');
    expect(getEndpointClassLabel('access_host', false)).toBe('Access port located');
    expect(getEndpointClassReason('access_path_not_confirmed', true)).toBe('尚未定位到唯一接入口');
    expect(getEndpointClassReason('access_path_not_confirmed', false)).toBe('No unique access port located yet');
  });

  it('explains that MAC-only observations do not create IP records', () => {
    expect(getDiscoveryRegistrationLabel('not_applicable', true)).toBe('仅有 MAC，无法登记 IP');
    expect(getDiscoveryEvidenceLabel('stale', true)).toBe('采集记录较旧');
  });

  it('distinguishes ARP, IPv6 ND, and FDB observations in both languages', () => {
    expect(getDiscoveryObservationSourceLabel('arp', undefined, true)).toBe('ARP 表');
    expect(getDiscoveryObservationSourceLabel('ndp', undefined, true)).toBe('IPv6 邻居表（ND）');
    expect(getDiscoveryObservationSourceLabel('fdb', undefined, true)).toBe('MAC 地址表（FDB）');
    expect(getDiscoveryObservationSourceLabel(undefined, 'fdb', true)).toBe('MAC 地址表（FDB）');
    expect(getDiscoveryObservationSourceLabel('ndp', undefined, false)).toBe('IPv6 neighbor table (ND)');
    expect(getDiscoveryObservationSourceLabel('fdb', undefined, false)).toBe('MAC address table (FDB)');
  });

  it('marks absent and unknown source types as pending without hiding their value', () => {
    expect(getDiscoveryObservationSourceLabel(undefined, undefined, true)).toBe('来源待确认');
    expect(getDiscoveryObservationSourceLabel(' ', 'ndp', true)).toBe('IPv6 邻居表（ND）');
    expect(getDiscoveryObservationSourceLabel({ invalid: true }, 'ndp', true)).toBe('IPv6 邻居表（ND）');
    expect(getDiscoveryObservationSourceLabel('vendor-x', undefined, false)).toBe('Source pending (vendor-x)');
  });

  it('labels collection scope and failure states without treating them as inferred VRFs', () => {
    expect(getDiscoveryEvidenceLabel('scope_pending', true)).toBe('所属网络待确认');
    expect(getDiscoveryRegistrationLabel('scope_pending', true)).toBe('所属网络待确认');
    expect(getDiscoveryCollectionStatusLabel('scope_unknown', true)).toBe('所属网络待确认');
    expect(getDiscoveryCollectionStatusLabel('failed', true)).toBe('采集失败');
    expect(getDiscoveryCollectionStatusLabel('vendor-state', false)).toBe('vendor-state');
  });
});
