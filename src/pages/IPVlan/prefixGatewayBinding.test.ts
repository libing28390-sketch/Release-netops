import { describe, expect, it } from 'vitest';
import {
  buildGatewayCandidateQuery,
  getAutomaticGatewayBinding,
  getGatewayScopePendingMessage,
  isValidGatewayCandidatePrefix,
  type GatewayCandidateResponse,
} from './prefixGatewayBinding';

describe('IPAM gateway candidate binding', () => {
  it('sends the prefix and site and only includes a non-empty gateway IP', () => {
    expect(buildGatewayCandidateQuery({ prefix: ' 10.200.24.0/30 ', siteId: 'site-1' }).toString())
      .toBe('prefix=10.200.24.0%2F30&site_id=site-1');
    expect(buildGatewayCandidateQuery({ prefix: '10.200.24.0/30', siteId: 'site-1', gatewayIp: '10.200.24.1' }).toString())
      .toBe('prefix=10.200.24.0%2F30&site_id=site-1&gateway_ip=10.200.24.1');
  });

  it('uses only the explicit address-space mapping as gateway scope and omits it when unresolved', () => {
    const scopedQuery = buildGatewayCandidateQuery({
      prefix: '10.200.24.0/30',
      siteId: 'site-1',
      addressSpaceId: 'space-vrf-prod',
    });
    expect(scopedQuery.get('address_space_id')).toBe('space-vrf-prod');
    expect(scopedQuery.has('vrf_id')).toBe(false);

    const unresolvedQuery = buildGatewayCandidateQuery({
      prefix: '10.200.24.0/30',
      siteId: 'site-1',
      addressSpaceId: '  ',
    });
    expect(unresolvedQuery.has('address_space_id')).toBe(false);
  });

  it('validates IPv4 and IPv6 prefixes before querying candidates', () => {
    expect(isValidGatewayCandidatePrefix('10.200.24.0/30')).toBe(true);
    expect(isValidGatewayCandidatePrefix('2001:db8::/64')).toBe(true);
    expect(isValidGatewayCandidatePrefix('10.200.24.0/33')).toBe(false);
    expect(isValidGatewayCandidatePrefix('not-a-prefix')).toBe(false);
  });

  it('auto-binds only a unique match and never overrides a manual choice or invents an interface ID', () => {
    const response: GatewayCandidateResponse = {
      status: 'matched',
      gateway_ip: '10.200.24.1',
      selected: {
        device_id: 'device-r2',
        device_name: 'R2',
        interface_name: 'Loopback0',
        interface_id: null,
        address: '10.200.24.1',
      },
      endpoints: [],
    };
    expect(getAutomaticGatewayBinding('none', response)).toEqual({ deviceId: 'device-r2', interfaceId: '' });
    expect(getAutomaticGatewayBinding('manual', response)).toBeNull();
    expect(getAutomaticGatewayBinding('auto', { ...response, status: 'no_unique_gateway', selected: null })).toBeNull();
    expect(getAutomaticGatewayBinding('none', { ...response, status: 'scope_pending', selected: null })).toBeNull();
  });

  it('explains that VRF-less gateway evidence needs manual review', () => {
    expect(getGatewayScopePendingMessage('none', true)).toContain('不能自动关联网关');
    expect(getGatewayScopePendingMessage('manual', true)).toContain('已保留人工设备选择');
    expect(getGatewayScopePendingMessage('none', false)).toContain('cannot be auto-bound');
  });
});
