import { describe, expect, it } from 'vitest';
import { buildTopologyRoleLayeredPositions, repairTopologyRoleLayeredPositions } from './topologyRoleLayout';

const devices = [
  { id: 'core', hostname: 'CORE', role: 'core' },
  { id: 'access-a', hostname: 'ACCESS-A', role: 'access' },
  { id: 'access-b', hostname: 'ACCESS-B', role: 'access' },
  { id: 'ac', hostname: 'AC', role: 'wireless_controller' },
];
const link = (source: string, target: string) => ({
  source_device_id: source, target_device_id: target,
  relation_type: 'PHYSICAL', discovery_source: 'lldp',
});

describe('wireless topology layout', () => {
  it('places the controller in a side lane aligned to its actual uplink', () => {
    const positions = buildTopologyRoleLayeredPositions(devices, 1200, 700, [
      link('core', 'access-a'), link('core', 'access-b'), link('access-a', 'ac'),
    ])!;
    expect(Object.keys(positions).sort()).toEqual(devices.map((device) => device.id).sort());
    expect(positions.ac.x).toBeGreaterThan(Math.max(positions.core.x, positions['access-a'].x, positions['access-b'].x) + 100);
    expect(positions.ac.y).toBe(positions['access-a'].y);
  });

  it('keeps a single-tier access graph usable and separates two controllers', () => {
    const nodes = [devices[1], devices[3], { id: 'ac2', role: 'wireless_controller', hostname: 'AC2' }];
    const positions = buildTopologyRoleLayeredPositions(nodes, 1000, 500, [link('access-a', 'ac'), link('access-a', 'ac2')])!;
    expect(Object.keys(positions)).toHaveLength(3);
    expect(positions.ac.x).toBeGreaterThan(positions['access-a'].x);
    expect(Math.abs(positions.ac.y - positions.ac2.y)).toBeGreaterThanOrEqual(160);
  });

  it('repairs legacy overlapping controller coordinates without entering the wired lane', () => {
    const links = [link('core', 'access-a'), link('access-a', 'ac')];
    const positions = buildTopologyRoleLayeredPositions(devices, 1200, 700, links)!;
    const legacy = Object.fromEntries(devices.map((device) => [device.id, { x: 600, y: 300 }]));
    const repaired = repairTopologyRoleLayeredPositions(devices, positions, legacy, 1200, 700, links);
    expect(repaired.ac).toEqual(positions.ac);
    expect(repaired.ac.x).toBeGreaterThan(repaired['access-a'].x + 100);
    expect(Object.keys(repaired)).toHaveLength(devices.length);
  });

  it('groups even a few APs by their physical switch, not by their controller', () => {
    const nodes = [...devices,
      { id: 'ap-a', hostname: 'AP-A', role: 'wireless_ap' },
      { id: 'ap-b', hostname: 'AP-B', role: 'wireless_ap' },
      { id: 'ap-c', hostname: 'AP-C', role: 'wireless_ap' },
    ];
    const positions = buildTopologyRoleLayeredPositions(nodes, 1200, 700, [
      link('core', 'access-a'), link('core', 'access-b'), link('core', 'ac'),
      link('access-a', 'ap-a'), link('access-a', 'ap-b'), link('access-b', 'ap-c'),
      { source_device_id: 'ac', target_device_id: 'ap-c', relation_type: 'CONTROL', inferred: true },
    ])!;
    expect(positions['ap-a'].y).toBe(positions['ap-b'].y);
    expect(positions['ap-c'].y).not.toBe(positions['ap-a'].y);
    expect(positions['ap-a'].y).toBeGreaterThan(positions['access-a'].y);
    expect(Object.keys(positions)).toHaveLength(nodes.length);
  });
});
