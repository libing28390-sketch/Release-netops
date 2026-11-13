import { describe, expect, it } from 'vitest';
import {
  buildFoldedChainPositions,
  buildRingGroupPositions,
  measureTopologyLayout,
  repairTopologyLayout,
  type TopologyLayoutNode,
} from './topologyLayout';

const layoutOptions = {
  minX: 48,
  maxX: 700,
  minY: 56,
  maxY: 420,
  nodeRadius: 44,
  edgeGap: 18,
};

describe('repairTopologyLayout', () => {
  it('separates devices from unrelated links and reduces the reported topology crossing', () => {
    const nodes: TopologyLayoutNode[] = [
      { id: 'R1', x: 120, y: 60 },
      { id: 'R3', x: 370, y: 60 },
      { id: 'R4', x: 120, y: 205 },
      { id: 'R2', x: 265, y: 255 },
      { id: 'SW6', x: 390, y: 205 },
      { id: 'SW5', x: 515, y: 205 },
    ];
    const links = [
      { source_device_id: 'R1', target_device_id: 'R3' },
      { source_device_id: 'R1', target_device_id: 'R2' },
      { source_device_id: 'R4', target_device_id: 'R2' },
      { source_device_id: 'R4', target_device_id: 'SW6' },
      { source_device_id: 'R3', target_device_id: 'SW5' },
    ];

    const before = measureTopologyLayout(nodes, links, layoutOptions);
    const repaired = repairTopologyLayout(nodes, links, layoutOptions);
    const repairedNodes = nodes.map((node) => ({ ...node, ...repaired[node.id] }));
    const after = measureTopologyLayout(repairedNodes, links, layoutOptions);

    expect(before.crossings).toBeGreaterThan(0);
    expect(before.edgeNodeConflicts).toBeGreaterThan(0);
    expect(after.crossings).toBeLessThan(before.crossings);
    expect(after.edgeNodeConflicts).toBe(0);
    expect(after.minEdgeNodeDistance).toBeGreaterThanOrEqual(62);
    repairedNodes.forEach((node) => {
      expect(node.x).toBeGreaterThanOrEqual(layoutOptions.minX);
      expect(node.x).toBeLessThanOrEqual(layoutOptions.maxX);
      expect(node.y).toBeGreaterThanOrEqual(layoutOptions.minY);
      expect(node.y).toBeLessThanOrEqual(layoutOptions.maxY);
    });
  });

  it('is deterministic for the same physical graph', () => {
    const nodes: TopologyLayoutNode[] = [
      { id: 'A', x: 100, y: 100 },
      { id: 'B', x: 400, y: 100 },
      { id: 'C', x: 250, y: 100 },
    ];
    const links = [{ source_device_id: 'A', target_device_id: 'B' }];

    expect(repairTopologyLayout(nodes, links, layoutOptions))
      .toEqual(repairTopologyLayout(nodes, links, layoutOptions));
  });
});

describe('buildFoldedChainPositions', () => {
  it('folds the six-device physical path into the two-column topology shape', () => {
    const positions = buildFoldedChainPositions(
      ['SW5', 'R3', 'R1', 'R2', 'R4', 'SW6'],
      700,
      580,
    );

    expect(positions.R1.y).toBe(positions.R2.y);
    expect(positions.R3.y).toBe(positions.R4.y);
    expect(positions.SW5.y).toBe(positions.SW6.y);
    expect(positions.R1.y).toBeLessThan(positions.R3.y);
    expect(positions.R3.y).toBeLessThan(positions.SW5.y);
    expect(positions.R1.x).toBeLessThan(positions.R2.x);
    expect(positions.R3.x).toBeLessThan(positions.R4.x);
    expect(positions.SW5.x).toBeLessThan(positions.SW6.x);
  });
});

describe('buildRingGroupPositions', () => {
  it('lays out ring relations on a stable circle while leaving other nodes untouched', () => {
    const nodes = ['A', 'B', 'C', 'D', 'OUTSIDE'].map((id) => ({ id }));
    const links = [
      { source_device_id: 'A', target_device_id: 'B', relation_type: 'RING' },
      { source_device_id: 'B', target_device_id: 'C', relation_type: 'RING' },
      { source_device_id: 'C', target_device_id: 'D', relation_type: 'RING' },
      { source_device_id: 'D', target_device_id: 'A', relation_type: 'RING' },
    ];
    const first = buildRingGroupPositions(nodes, links, 800, 600);
    const second = buildRingGroupPositions(nodes, [...links].reverse(), 800, 600);

    expect(first).toEqual(second);
    expect(Object.keys(first).sort()).toEqual(['A', 'B', 'C', 'D']);
    expect(first.OUTSIDE).toBeUndefined();
    expect(new Set(Object.values(first).map((point) => `${point.x}:${point.y}`)).size).toBe(4);
  });
});
