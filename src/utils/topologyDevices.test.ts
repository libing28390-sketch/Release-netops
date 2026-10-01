import { describe, expect, it } from 'vitest';
import { excludeServerTopologyDevices, isTopologyServerDevice, projectManagedTopologyCanvas } from './topologyDevices';

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

  it('renders one icon per managed asset and keeps unmatched LLDP peers in diagnostics only', () => {
    const devices = [
      { id: 'sw-1' },
      { id: 'sw-2' },
      { id: 'unknown-peer-1', is_unmanaged: true },
      { id: 'unknown-peer-2', is_unmanaged: true },
    ];
    const links = [
      { id: 'confirmed', source_device_id: 'sw-1', target_device_id: 'sw-2' },
      { id: 'unmatched-peer', source_device_id: 'sw-1', target_device_id: 'unknown-peer-1' },
      { id: 'orphan', source_device_id: 'unknown-peer-1', target_device_id: 'unknown-peer-2' },
    ];

    const projection = projectManagedTopologyCanvas(devices, links);

    expect(projection.devices.map((device) => device.id)).toEqual(['sw-1', 'sw-2']);
    expect(projection.links.map((link) => link.id)).toEqual(['confirmed']);
  });
});
