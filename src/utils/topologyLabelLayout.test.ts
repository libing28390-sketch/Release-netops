import { describe, expect, it } from 'vitest';
import {
  resolveTopologyDeviceLabelPlacements,
  resolveTopologyPortLabelPlacements,
  type TopologyLabelRect,
  type TopologyDeviceLabelCandidate,
  type TopologyPortLabelCandidate,
} from './topologyLabelLayout';

const rectFor = (point: { x: number; y: number }, width: number, height: number): TopologyLabelRect => ({
  ...point,
  width,
  height,
});

const boxesOverlapWithGap = (
  left: TopologyLabelRect,
  right: TopologyLabelRect,
  gap: number,
) => (
  Math.abs(left.x - right.x) * 2 < left.width + right.width + gap * 2
  && Math.abs(left.y - right.y) * 2 < left.height + right.height + gap * 2
);

describe('topology device label collision layout', () => {
  it('keeps default positions when labels do not collide', () => {
    const candidates: TopologyDeviceLabelCandidate[] = [
      { id: 'switch-2', x: 260, y: 140, width: 92, height: 20 },
      { id: 'switch-1', x: 120, y: 140, width: 88, height: 20 },
    ];

    expect(resolveTopologyDeviceLabelPlacements(candidates, [])).toEqual({
      'switch-1': { x: 120, y: 140 },
      'switch-2': { x: 260, y: 140 },
    });
  });

  it('moves stacked names below glyphs and separates manual overlaps deterministically', () => {
    const candidates: TopologyDeviceLabelCandidate[] = [
      { id: 'device-3', x: 100, y: 100, width: 70, height: 22 },
      { id: 'device-2', x: 100, y: 100, width: 84, height: 26 },
      { id: 'device-1', x: 100, y: 100, width: 76, height: 18 },
    ];
    const glyphs = [100, 170, 240].map((y) => rectFor({ x: 100, y }, 76, 50));
    const placements = resolveTopologyDeviceLabelPlacements(candidates, glyphs, 4);
    const reversedPlacements = resolveTopologyDeviceLabelPlacements([...candidates].reverse(), glyphs, 4);

    expect(placements).toEqual(reversedPlacements);
    expect(placements['device-1'].y).toBeGreaterThan(265);
    expect(placements['device-2'].y).toBeGreaterThan(placements['device-1'].y);
    expect(placements['device-3'].y).toBeGreaterThan(placements['device-2'].y);
    expect(Object.values(placements).every((point) => point.x === 100)).toBe(true);

    const labels = candidates.map((candidate) => ({
      ...placements[candidate.id],
      width: candidate.width,
      height: candidate.height,
    }));
    labels.forEach((label) => {
      expect(glyphs.some((glyph) => boxesOverlapWithGap(label, glyph, 4))).toBe(false);
    });
    labels.forEach((label, index) => {
      expect(labels.slice(index + 1).some((other) => boxesOverlapWithGap(label, other, 4))).toBe(false);
    });
  });
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

