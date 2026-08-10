import { describe, expect, it } from 'vitest';
import {
  buildTopologyRoleLayeredPositions,
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

  it('uses directed evidence ranks before role tiers when they are available', () => {
    const selection = selectTopologyLayoutLayers([
      { id: 'a', role: 'firewall', topology_rank: 0 },
      { id: 'b', role: 'core', topology_rank: 1 },
      { id: 'c', role: 'access', topology_rank: 2 },
    ]);
    expect(selection).toEqual({ layers: [0, 1, 2], source: 'evidence' });
  });

  it('does not invent rows when every device has the same role', () => {
    expect(buildTopologyRoleLayeredPositions([
      { id: 'a', hostname: 'S1', role: 'access' },
      { id: 'b', hostname: 'S2', role: 'access' },
    ], 1000, 480)).toBeNull();
  });
});
