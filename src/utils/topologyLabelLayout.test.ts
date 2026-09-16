import { describe, expect, it } from 'vitest';
import {
  resolveTopologyPortLabelPlacements,
  type TopologyLabelRect,
  type TopologyPortLabelCandidate,
} from './topologyLabelLayout';

const rectFor = (point: { x: number; y: number }, width: number, height: number): TopologyLabelRect => ({
  ...point,
  width,
  height,
});

describe('topology port label collision layout', () => {
  it('moves labels away from a device-name obstacle and keeps the boxes separate', () => {
    const candidates: TopologyPortLabelCandidate[] = [
      { id: 'link-a:source', x: 120, y: 120, width: 70, height: 12, normal: { x: 0, y: 1 }, tangent: { x: 1, y: 0 } },
      { id: 'link-b:source', x: 120, y: 120, width: 70, height: 12, normal: { x: 0, y: 1 }, tangent: { x: 1, y: 0 } },
    ];
    const placements = resolveTopologyPortLabelPlacements(
      candidates,
      [rectFor({ x: 120, y: 120 }, 58, 42)],
      { gap: 4, bounds: { minX: 20, maxX: 220, minY: 20, maxY: 220 }, hideOnCollision: true },
    );

    expect(placements['link-a:source'].hidden).toBe(false);
    expect(placements['link-b:source'].hidden).toBe(false);
    expect(placements['link-a:source']).not.toEqual({ x: 120, y: 120, hidden: false });

    const first = placements['link-a:source'];
    const second = placements['link-b:source'];
    const separated = Math.abs(first.x - second.x) * 2 >= 70 + 70
      || Math.abs(first.y - second.y) * 2 >= 12 + 12;
    expect(separated).toBe(true);
  });

  it('keeps selected labels visible when dense space forces a residual collision', () => {
    const placements = resolveTopologyPortLabelPlacements(
      [
        { id: 'selected', x: 50, y: 50, width: 90, height: 18, priority: 200 },
        { id: 'secondary', x: 50, y: 50, width: 90, height: 18 },
      ],
      [rectFor({ x: 50, y: 50 }, 160, 160)],
      { gap: 4, bounds: { minX: 50, maxX: 50, minY: 50, maxY: 50 }, hideOnCollision: true },
    );

    expect(placements.selected.hidden).toBe(false);
    expect(placements.secondary.hidden).toBe(true);
  });
});

