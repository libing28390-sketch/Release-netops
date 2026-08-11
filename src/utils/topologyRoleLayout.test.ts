import { describe, expect, it } from 'vitest';
import {
  buildTopologyRoleLayeredPositions,
  repairTopologyRoleLayeredPositions,
  selectTopologyLayoutLayers,
  type TopologyRoleLayoutDevice,
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
});
