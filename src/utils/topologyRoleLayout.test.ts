import { describe, expect, it } from 'vitest';
import {
  buildTopologyRoleLayeredPositions,
  countTopologyLayerCrossings,
  repairTopologyRoleLayeredPositions,
  selectTopologyLayoutLayers,
  type TopologyRoleLayoutDevice,
  type TopologyRoleLayoutLink,
} from './topologyRoleLayout';

const whDc02Devices: TopologyRoleLayoutDevice[] = [
  { id: 'fw-10', hostname: 'F1090-10', role: 'firewall' },
  { id: 'fw-9', hostname: 'F1090-9', role: 'firewall' },
  { id: 'core-1', hostname: 'S6850-1', role: 'core' },
  { id: 'core-2', hostname: 'S6850-2', role: 'core' },
  { id: 'dist-3', hostname: 'S6850-3', role: 'distribution' },
  { id: 'dist-4', hostname: 'S6850-4', role: 'distribution' },
  { id: 'access-5', hostname: 'S6850-5', role: 'access' },
  { id: 'access-6', hostname: 'S6850-6', role: 'access' },
];

describe('topology role-tier layout', () => {
  it('places the WH-DC-02 roles in firewall/core/distribution/access rows', () => {
    const positions = buildTopologyRoleLayeredPositions(whDc02Devices, 1000, 480);
    expect(positions).not.toBeNull();

    expect(positions?.['fw-9'].y).toBe(positions?.['fw-10'].y);
    expect(positions?.['fw-10'].y).toBeLessThan(positions?.['core-1'].y ?? 0);
    expect(positions?.['core-1'].y).toBeLessThan(positions?.['dist-3'].y ?? 0);
    expect(positions?.['dist-3'].y).toBeLessThan(positions?.['access-5'].y ?? 0);
    expect(positions?.['core-1'].y).toBe(positions?.['core-2'].y);
    expect(positions?.['dist-3'].y).toBe(positions?.['dist-4'].y);
    expect(positions?.['access-5'].y).toBe(positions?.['access-6'].y);
    expect(positions?.['core-1'].x).toBeLessThan(positions?.['core-2'].x ?? 0);
  });

  it('uses the defined role tiers before evidence ranks for visual ordering', () => {
    const selection = selectTopologyLayoutLayers([
      { id: 'a', role: 'core', topology_rank: 2 },
      { id: 'b', role: 'distribution', topology_rank: 1 },
      { id: 'c', role: 'access', topology_rank: 0 },
    ]);
    expect(selection).toEqual({ layers: [1, 2, 3], source: 'role' });
  });

  it('puts devices without a role in a separate fallback tier', () => {
    const selection = selectTopologyLayoutLayers([
      { id: 'core', role: 'core' },
      { id: 'access', role: 'access' },
      { id: 'unknown' },
    ]);

    expect(selection).toEqual({ layers: [1, 3, 4], source: 'role' });
  });

  it('prefers the canonical topology identity over a generic device role', () => {
    const selection = selectTopologyLayoutLayers([
      { id: 'a', role_identity: 'CORE_SWITCH', role: 'switch' },
      { id: 'b', role_identity: 'AGGREGATION_SWITCH', role: 'switch' },
      { id: 'c', role_identity: 'ACCESS_SWITCH', role: 'switch' },
    ]);
    expect(selection).toEqual({ layers: [1, 2, 3], source: 'role' });
  });

  it('falls back to evidence ranks when role tiers cannot form a hierarchy', () => {
    const selection = selectTopologyLayoutLayers([
      { id: 'a', role: 'unknown', topology_rank: 0 },
      { id: 'b', role: 'unknown', topology_rank: 1 },
    ]);
    expect(selection).toEqual({ layers: [0, 1], source: 'evidence' });
  });

  it('does not invent rows when every device has the same role', () => {
    expect(buildTopologyRoleLayeredPositions([
      { id: 'a', hostname: 'S1', role: 'access' },
      { id: 'b', hostname: 'S2', role: 'access' },
    ], 1000, 480)).toBeNull();
  });

  it('keeps semantic rows separate when the viewport is shorter than the hierarchy', () => {
    const positions = buildTopologyRoleLayeredPositions(whDc02Devices, 1000, 180);
    expect(positions).not.toBeNull();

    const rowYs = whDc02Devices.map((device) => positions?.[device.id]?.y);
    expect(new Set(rowYs).size).toBe(4);
    expect(positions?.['fw-10'].y).toBeLessThan(positions?.['core-1'].y ?? 0);
    expect(positions?.['core-1'].y).toBeLessThan(positions?.['dist-3'].y ?? 0);
    expect(positions?.['dist-3'].y).toBeLessThan(positions?.['access-5'].y ?? 0);
  });

  it('repairs collapsed saved x coordinates while keeping the role rows', () => {
    const structured = buildTopologyRoleLayeredPositions(whDc02Devices, 1000, 480);
    expect(structured).not.toBeNull();

    const collapsed = Object.fromEntries(
      whDc02Devices.map((device) => [device.id, { x: 500, y: 200 }]),
    );
    const repaired = repairTopologyRoleLayeredPositions(
      whDc02Devices,
      structured || {},
      collapsed,
      1000,
      480,
    );
    const accessX = ['access-5', 'access-6'].map((id) => repaired[id].x);

    expect(repaired['core-1'].y).toBe(structured?.['core-1'].y);
    expect(repaired['dist-3'].y).toBe(structured?.['dist-3'].y);
    expect(repaired['access-5'].y).toBe(structured?.['access-5'].y);
    expect(accessX[0]).not.toBe(accessX[1]);
  });

  it('orders rows from LLDP adjacency to remove a crossing edge pair', () => {
    const devices: TopologyRoleLayoutDevice[] = [
      { id: 'core-a', hostname: 'CORE-A', role: 'core' },
      { id: 'core-b', hostname: 'CORE-B', role: 'core' },
      { id: 'access-a', hostname: 'ACCESS-A', role: 'access' },
      { id: 'access-b', hostname: 'ACCESS-B', role: 'access' },
    ];
    const links: TopologyRoleLayoutLink[] = [
      { source_device_id: 'core-a', target_device_id: 'access-b', relation_type: 'PHYSICAL', discovery_source: 'lldp' },
      { source_device_id: 'core-b', target_device_id: 'access-a', relation_type: 'PHYSICAL', discovery_source: 'lldp' },
    ];
    const hostnameOrder = buildTopologyRoleLayeredPositions(devices, 1000, 480);
    const lldpOrder = buildTopologyRoleLayeredPositions(devices, 1000, 480, links);

    expect(hostnameOrder).not.toBeNull();
    expect(lldpOrder).not.toBeNull();
    expect(countTopologyLayerCrossings(devices, links, hostnameOrder || {})).toBe(1);
    expect(countTopologyLayerCrossings(devices, links, lldpOrder || {})).toBe(0);
    expect(lldpOrder?.['core-a'].x).toBeGreaterThan(lldpOrder?.['core-b'].x ?? 0);
  });

  it('does not use inferred logical links to reorder physical layers', () => {
    const devices: TopologyRoleLayoutDevice[] = [
      { id: 'core-a', hostname: 'CORE-A', role: 'core' },
      { id: 'core-b', hostname: 'CORE-B', role: 'core' },
      { id: 'access-a', hostname: 'ACCESS-A', role: 'access' },
      { id: 'access-b', hostname: 'ACCESS-B', role: 'access' },
    ];
    const logicalLinks: TopologyRoleLayoutLink[] = [
      { source_device_id: 'core-a', target_device_id: 'access-b', relation_type: 'L3_NEIGHBOR', discovery_source: 'ospf', inferred: true },
      { source_device_id: 'core-b', target_device_id: 'access-a', relation_type: 'L3_NEIGHBOR', discovery_source: 'ospf', inferred: true },
    ];
    const baseline = buildTopologyRoleLayeredPositions(devices, 1000, 480);
    const actual = buildTopologyRoleLayeredPositions(devices, 1000, 480, logicalLinks);

    expect(actual).toEqual(baseline);
  });

  it('replaces saved positions when they create more crossings than LLDP order', () => {
    const devices: TopologyRoleLayoutDevice[] = [
      { id: 'core-a', hostname: 'CORE-A', role: 'core' },
      { id: 'core-b', hostname: 'CORE-B', role: 'core' },
      { id: 'access-a', hostname: 'ACCESS-A', role: 'access' },
      { id: 'access-b', hostname: 'ACCESS-B', role: 'access' },
    ];
    const links: TopologyRoleLayoutLink[] = [
      { source_device_id: 'core-a', target_device_id: 'access-b', relation_type: 'PHYSICAL', discovery_source: 'lldp' },
      { source_device_id: 'core-b', target_device_id: 'access-a', relation_type: 'PHYSICAL', discovery_source: 'lldp' },
    ];
    const structured = buildTopologyRoleLayeredPositions(devices, 1000, 480, links) || {};
    const savedCrossing = buildTopologyRoleLayeredPositions(devices, 1000, 480) || {};
    const repaired = repairTopologyRoleLayeredPositions(devices, structured, savedCrossing, 1000, 480, links);

    expect(countTopologyLayerCrossings(devices, links, repaired)).toBe(0);
  });
});
