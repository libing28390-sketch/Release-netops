import { describe, expect, it } from 'vitest';
import { excludeServerTopologyDevices, isTopologyServerDevice } from './topologyDevices';

describe('topology device classification', () => {
  it('keeps server assets and their links out of the network graph input', () => {
    const devices = [
      { id: 'sw-1', role: 'access', device_category: 'network', platform: 'cisco_ios' },
      { id: 'srv-1', role: 'server', device_category: 'compute', platform: 'linux' },
      { id: 'host-1', role: 'server_access', device_category: 'network', platform: 'h3c_comware' },
    ];
    const result = excludeServerTopologyDevices(devices);

    expect(result.devices.map((device) => device.id)).toEqual(['sw-1', 'host-1']);
    expect(result.excludedIds).toEqual(new Set(['srv-1']));
    expect(isTopologyServerDevice(devices[2])).toBe(false);
  });
});
