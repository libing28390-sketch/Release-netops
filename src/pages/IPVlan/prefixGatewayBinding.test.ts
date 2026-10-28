import { describe, expect, it } from 'vitest';
import {
  buildGatewayCandidateQuery,
  getAutomaticGatewayBinding,
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
  });
});
