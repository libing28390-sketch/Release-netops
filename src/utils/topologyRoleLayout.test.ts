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

  it('uses explicit device role tiers for visual ordering', () => {
    const selection = selectTopologyLayoutLayers([
      { id: 'a', role: 'core' },
      { id: 'b', role: 'distribution' },
      { id: 'c', role: 'access' },
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

  it('does not invent role tiers for devices with unknown roles', () => {
    const unknownRoleDevices: TopologyRoleLayoutDevice[] = [
      { id: 'a', role: 'unknown' },
      { id: 'b', role: 'unknown' },
    ];
    expect(selectTopologyLayoutLayers(unknownRoleDevices)).toBeNull();
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

  it('keeps horizontal row spacing proportional to role-layer separation', () => {
    const positions = buildTopologyRoleLayeredPositions(whDc02Devices, 2000, 600);
    expect(positions).not.toBeNull();

    const firewallGap = Math.abs((positions?.['fw-10'].x ?? 0) - (positions?.['fw-9'].x ?? 0));
    expect(firewallGap).toBeGreaterThanOrEqual(410);
    expect(firewallGap).toBeLessThanOrEqual(430);

    const ultrawidePositions = buildTopologyRoleLayeredPositions(whDc02Devices, 3000, 600);
    const ultrawideFirewallGap = Math.abs((ultrawidePositions?.['fw-10'].x ?? 0) - (ultrawidePositions?.['fw-9'].x ?? 0));
    expect(ultrawideFirewallGap).toBeLessThanOrEqual(430);
  });

  it('packs adjacent parent groups into wider rows without changing the default layout', () => {
    const parentIds = ['dist-a', 'dist-b', 'dist-c'];
    const devices: TopologyRoleLayoutDevice[] = [
      ...parentIds.map((id) => ({ id, hostname: id.toUpperCase(), role: 'distribution' })),
      ...parentIds.flatMap((parentId) => Array.from({ length: 4 }, (_, index) => ({
        id: `access-${parentId}-${index + 1}`,
        hostname: `ACCESS-${parentId}-${index + 1}`,
        role: 'access',
      }))),
    ];
    const links: TopologyRoleLayoutLink[] = parentIds.flatMap((parentId) => (
      devices.filter((device) => device.id.startsWith(`access-${parentId}-`)).map((device) => ({
        source_device_id: parentId,
        target_device_id: device.id,
        relation_type: 'PHYSICAL',
        discovery_source: 'lldp',
      }))
    ));

    const defaultPositions = buildTopologyRoleLayeredPositions(devices, 1800, 600, links);
    const widePositions = buildTopologyRoleLayeredPositions(devices, 1800, 600, links, 8);
    const accessDevices = devices.filter((device) => device.role === 'access');
    const defaultAccessRows = new Set(accessDevices.map((device) => defaultPositions?.[device.id].y));
    const wideAccessRows = new Set(accessDevices.map((device) => widePositions?.[device.id].y));
    const wideRowSizes = Array.from(wideAccessRows, (rowY) => (
      accessDevices.filter((device) => widePositions?.[device.id].y === rowY).length
    ));

    expect(defaultAccessRows.size).toBe(3);
    expect(wideAccessRows.size).toBe(2);
    expect(wideRowSizes.every((size) => size <= 8)).toBe(true);
    parentIds.forEach((parentId) => {
      const parentRows = new Set(accessDevices
        .filter((device) => device.id.startsWith(`access-${parentId}-`))
        .map((device) => widePositions?.[device.id].y));
      expect(parentRows.size).toBe(1);
    });
  });

  it('wraps 37 access devices to the available name space when the row ceiling is 60', () => {
    const distribution = ['dist-a', 'dist-b', 'dist-c'].map((id) => ({
      id,
      hostname: id.toUpperCase(),
      role: 'distribution',
    }));
    const access = Array.from({ length: 37 }, (_, index) => ({
      id: `access-${String(index + 1).padStart(2, '0')}`,
      hostname: `ACCESS-SW-${String(index + 1).padStart(2, '0')}`,
      role: 'access',
    }));
    const controller: TopologyRoleLayoutDevice = {
      id: 'wireless-controller', hostname: 'AC-01', role: 'wireless_controller',
    };
    const links: TopologyRoleLayoutLink[] = [
      ...access.map((device, index) => ({
        source_device_id: index < 13 ? 'dist-a' : index < 25 ? 'dist-b' : 'dist-c',
        target_device_id: device.id,
        relation_type: 'PHYSICAL',
        discovery_source: 'lldp',
      })),
      {
        source_device_id: 'dist-a', target_device_id: controller.id,
        relation_type: 'PHYSICAL', discovery_source: 'lldp',
      },
    ];

    const mainDevices = [...distribution, ...access];
    const positions = buildTopologyRoleLayeredPositions([...mainDevices, controller], 1920, 700, links, 60);
    const accessRows = new Set(access.map((device) => positions?.[device.id].y));
    const orderedAccessRows = Array.from(accessRows).sort((left, right) => (left ?? 0) - (right ?? 0));

    expect(accessRows.size).toBe(3);
    expect(accessRows.size).toBeLessThan(60);
    expect(access.every((device) => Number.isFinite(positions?.[device.id].x))).toBe(true);
    expect(orderedAccessRows[1] - orderedAccessRows[0]).toBe(125);
    expect(orderedAccessRows[2] - orderedAccessRows[1]).toBe(125);
    expect(positions?.[controller.id].x).toBeGreaterThan(Math.max(...mainDevices.map((device) => positions?.[device.id].x ?? 0)));
  });

  it('packs access uplink groups on narrow viewports even when the configured ceiling is 60', () => {
    const distribution = ['dist-a', 'dist-b', 'dist-c', 'dist-d'].map((id) => ({
      id,
      hostname: id.toUpperCase(),
      role: 'distribution',
    }));
    const access = Array.from({ length: 8 }, (_, index) => ({
      id: `access-${String(index + 1).padStart(2, '0')}`,
      hostname: `ACCESS-SW-${String(index + 1).padStart(2, '0')}`,
      role: 'access',
    }));
    const links: TopologyRoleLayoutLink[] = access.map((device, index) => ({
      source_device_id: `dist-${String.fromCharCode(97 + Math.floor(index / 2))}`,
      target_device_id: device.id,
      relation_type: 'PHYSICAL',
      discovery_source: 'lldp',
    }));

    const positions = buildTopologyRoleLayeredPositions([...distribution, ...access], 600, 600, links, 60);
    const accessRows = new Set(access.map((device) => positions?.[device.id].y));

    expect(accessRows.size).toBe(2);
  });

  it('keeps 50 devices grouped by every physical higher-tier uplink and isolates unlinked access devices', () => {
    const upstream: TopologyRoleLayoutDevice[] = [
      { id: 'core-a', hostname: 'CORE-A', role: 'core' },
      { id: 'core-b', hostname: 'CORE-B', role: 'core' },
      { id: 'dist-a', hostname: 'DIST-A', role: 'distribution' },
    ];
    const access = Array.from({ length: 47 }, (_, index) => ({
      id: `access-${String(index + 1).padStart(2, '0')}`,
      hostname: `ACCESS-SW-${String(index + 1).padStart(2, '0')}`,
      role: 'access',
    }));
    const uplinkCombinationById = new Map<string, string>();
    const links: TopologyRoleLayoutLink[] = access.flatMap((device, index) => {
      if (index >= 45) {
        uplinkCombinationById.set(device.id, 'unlinked');
        return [];
      }
      const coreId = index < 22 ? 'core-a' : 'core-b';
      const combination = `${coreId}+dist-a`;
      uplinkCombinationById.set(device.id, combination);
      const parents = [coreId, 'dist-a'];
      return parents.map((parentId) => ({
        source_device_id: parentId,
        target_device_id: device.id,
        relation_type: 'PHYSICAL',
        discovery_source: 'lldp',
      }));
    });
    const devices = [...upstream, ...access];
    const positions = buildTopologyRoleLayeredPositions(devices, 1920, 700, links, 60);
    const reversedLinkPositions = buildTopologyRoleLayeredPositions(devices, 1920, 700, [...links].reverse(), 60);
    const accessRows = Array.from(new Set(access.map((device) => positions?.[device.id].y)))
      .sort((left, right) => (left ?? 0) - (right ?? 0))
      .map((rowY) => {
        const rowDevices = access.filter((device) => positions?.[device.id].y === rowY);
        const combinations = new Set(rowDevices.map((device) => uplinkCombinationById.get(device.id)));
        expect(combinations.size).toBe(1);
        return Array.from(combinations)[0];
      });

    const linkedRows = accessRows.slice(0, -1);
    expect(accessRows[accessRows.length - 1]).toBe('unlinked');
    expect(new Set(linkedRows)).toEqual(new Set(['core-a+dist-a', 'core-b+dist-a']));
    expect(linkedRows[0]).toBe(linkedRows[1]);
    expect(linkedRows[2]).toBe(linkedRows[3]);
    expect(linkedRows[1]).not.toBe(linkedRows[2]);
    expect(reversedLinkPositions).toEqual(positions);
  });

  it('keeps wireless AP groups on separate parent rows when the row capacity increases', () => {
    const devices: TopologyRoleLayoutDevice[] = [
      { id: 'dist-a', hostname: 'DIST-A', role: 'distribution' },
      { id: 'dist-b', hostname: 'DIST-B', role: 'distribution' },
      { id: 'ap-a-1', hostname: 'AP-A-1', role: 'wireless_ap' },
      { id: 'ap-a-2', hostname: 'AP-A-2', role: 'wireless_ap' },
      { id: 'ap-b-1', hostname: 'AP-B-1', role: 'wireless_ap' },
      { id: 'ap-b-2', hostname: 'AP-B-2', role: 'wireless_ap' },
    ];
    const links: TopologyRoleLayoutLink[] = [
      ...['ap-a-1', 'ap-a-2'].map((id) => ({
        source_device_id: 'dist-a',
        target_device_id: id,
        relation_type: 'PHYSICAL',
        discovery_source: 'lldp',
      })),
      ...['ap-b-1', 'ap-b-2'].map((id) => ({
        source_device_id: 'dist-b',
        target_device_id: id,
        relation_type: 'PHYSICAL',
        discovery_source: 'lldp',
      })),
    ];

    const positions = buildTopologyRoleLayeredPositions(devices, 1800, 600, links, 12);
    const apRows = new Set(devices.slice(2).map((device) => positions?.[device.id].y));

    expect(apRows.size).toBe(2);
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
