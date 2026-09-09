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

  it('treats an S6800/S6850 GE endpoint on ports 1-48 as an SFP fiber port', () => {
    const [link] = normalizeRackTopologyLinks([
      {
        id: 'sfp-link',
        source_device_id: 'network-device-1',
        target_device_id: 'network-device-2',
        source_hostname: 'SW-CORE-01',
        target_hostname: 'EDGE-01',
        source_port: 'GE1/0/1',
        target_port: 'GE1/0/0',
        status: 'up',
      },
    ], rackVM);

    expect(link.cable_type).toBe('fiber');
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

  it('expands an LLDP-backed aggregation edge onto physical cascade ports', () => {
    const links = normalizeRackTopologyLinks([
      {
        id: 'lag-1',
        link_kind: 'aggregation',
        source_device_id: 'network-device-1',
        target_device_id: 'network-device-2',
        source_hostname: 'SW-CORE-01',
        target_hostname: 'SW-DIST-01',
        source_aggregation_name: 'Bridge-Aggregation1',
        target_aggregation_name: 'Bridge-Aggregation1',
        source_port: 'Bridge-Aggregation1',
        target_port: 'Bridge-Aggregation1',
        members: [
          {
            source: { device_id: 'network-device-1', name: 'XGE1/0/49', normalized: 'te1/0/49', up: true, speed_mbps: 10000 },
            target: { device_id: 'network-device-2', name: 'XGE1/0/49', normalized: 'te1/0/49', up: true, speed_mbps: 10000 },
            protocol: 'lldp',
          },
          {
            source: { device_id: 'network-device-1', name: 'XGE1/0/50', normalized: 'te1/0/50', up: true, speed_mbps: 10000 },
            target: { device_id: 'network-device-2', name: 'XGE1/0/50', normalized: 'te1/0/50', up: true, speed_mbps: 10000 },
            protocol: 'lldp',
          },
        ],
        status: 'up',
      },
    ], rackVM);

    expect(links).toHaveLength(2);
    expect(links.map(link => link.local_interface)).toEqual(['XGE1/0/49', 'XGE1/0/50']);
    expect(links.map(link => link.remote_interface)).toEqual(['XGE1/0/49', 'XGE1/0/50']);
    expect(links.every(link => link.link_kind === 'aggregation')).toBe(true);
    expect(links.every(link => link.member_count === 2)).toBe(true);
    expect(links.every(link => link.cable_type === 'fiber')).toBe(true);
  });
});
