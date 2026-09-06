import { describe, expect, it } from 'vitest';
import type { RackVM } from '../types';
import { normalizeRackTopologyLinks } from './topology';

const rackVM: RackVM = {
  id: 'rack-a',
  name: 'A-01',
  siteId: 'site-a',
  siteLabel: 'DC-A',
  floor: '3F',
  room: '301',
  row: 'A',
  totalU: 42,
  widthMm: 600,
  depthMm: 1000,
  heightMm: 1867,
  usedU: 2,
  availableU: 40,
  ratedPowerTotalWatts: 300,
  dataQuality: { valid: true, issues: [] },
  devices: [
    {
      id: 'rack-device-1',
      rackId: 'rack-a',
      name: 'SW-CORE-01',
      assetId: 'asset-1',
      networkDeviceId: 'network-device-1',
      deviceTypeId: 'type-1',
      vendor: 'H3C',
      model: 'S6850',
      role: 'switch',
      startU: 40,
      heightU: 2,
      endU: 41,
      face: 'front',
      isFullDepth: true,
      serialNumber: 'SN-1',
      lifecycleStatus: 'active',
      healthStatus: 'healthy',
      metrics: { ratedPowerWatts: 300, powerSource: 'RATED' },
      dataQuality: { valid: true, issues: [] },
      coordinates: { centerY: 17.78, height: 0.87, depth: 7.5, centerZ: 0, width: 4.78 },
    },
  ],
  validDevices: [],
  invalidDevices: [],
};
rackVM.validDevices = rackVM.devices;

describe('normalizeRackTopologyLinks', () => {
  it('maps the backend physical-link contract by network device id', () => {
    const links = normalizeRackTopologyLinks([
      {
        id: 'link-1',
        source_device_id: 'network-device-1',
        target_device_id: 'network-device-2',
        source_hostname_resolved: 'SW-CORE-01',
        target_hostname_resolved: 'SW-DIST-01',
        source_port_normalized: 'Ten-GigabitEthernet1/0/1',
        target_port_normalized: 'Ten-GigabitEthernet1/0/2',
        operational_state: 'up',
        bandwidth_mbps: 10000,
      },
    ], rackVM);

    expect(links).toHaveLength(1);
    expect(links[0]).toMatchObject({
      id: 'link-1',
      local_device_id: 'network-device-1',
      remote_device_id: 'network-device-2',
      local_interface: 'Ten-GigabitEthernet1/0/1',
      remote_interface: 'Ten-GigabitEthernet1/0/2',
      speed_mbps: 10000,
      status: 'up',
    });
  });

  it('reverses a link when the rack device is the target endpoint', () => {
    const [link] = normalizeRackTopologyLinks([
      {
        link_key: 'reverse-link',
        source_device_id: 'network-device-2',
        target_device_id: 'network-device-1',
        source_hostname: 'SW-DIST-01',
        target_hostname: 'SW-CORE-01',
        source_port: 'GE1/0/1',
        target_port: 'GE1/0/2',
        operational_state: 'degraded',
      },
    ], rackVM);

    expect(link.local_device_id).toBe('network-device-1');
    expect(link.local_interface).toBe('GE1/0/2');
    expect(link.remote_device_id).toBe('network-device-2');
    expect(link.status).toBe('degraded');
  });

  it('drops unrelated rows and never creates fallback links', () => {
    expect(normalizeRackTopologyLinks([], rackVM)).toEqual([]);
    expect(normalizeRackTopologyLinks([
      {
        id: 'unrelated',
        source_device_id: 'network-device-x',
        target_device_id: 'network-device-y',
        source_hostname: 'X',
        target_hostname: 'Y',
      },
    ], rackVM)).toEqual([]);
  });
});
