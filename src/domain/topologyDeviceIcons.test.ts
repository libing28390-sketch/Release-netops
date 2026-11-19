import { describe, expect, it } from 'vitest';
import { getTopologyDeviceIconType } from './topologyDeviceIcons';

describe('topology device icon type', () => {
  it('uses explicit device categories instead of the hostname or topology tier', () => {
    expect(getTopologyDeviceIconType({ device_category: 'Firewall', role: 'edge', hostname: 'SW99' })).toBe('firewall');
    expect(getTopologyDeviceIconType({ role: '汇聚层', hostname: 'office-01' })).toBe('switch');
  });

  it('keeps wireless access points and controllers in separate icon libraries', () => {
    expect(getTopologyDeviceIconType({ role: '无线接入点', device_category: 'wireless', hostname: 'access-point-1' })).toBe('wireless_ap');
    expect(getTopologyDeviceIconType({ role_identity: 'wireless_controller', device_category: 'wireless', role: 'access' })).toBe('wireless_controller');
  });
});
