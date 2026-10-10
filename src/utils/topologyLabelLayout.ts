export type TopologyLabelPoint = {
  x: number;
  y: number;
};

export type TopologyLabelRect = TopologyLabelPoint & {
  width: number;
  height: number;
};

export type TopologyPortLabelCandidate = TopologyLabelPoint & {
  id: string;
  width: number;
  height: number;
  /** Perpendicular direction used to fan labels away from a link. */
  normal?: TopologyLabelPoint;
  /** Direction pointing away from the endpoint toward the remote endpoint. */
  tangent?: TopologyLabelPoint;
  priority?: number;
};

export type TopologyPortLabelPlacement = TopologyLabelPoint & {
  hidden: boolean;
};

export type TopologyLabelLayoutBounds = {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
};

export type TopologyLabelLayoutOptions = {
  bounds?: TopologyLabelLayoutBounds;
  gap?: number;
  hideOnCollision?: boolean;
};

const DEFAULT_GAP = 5;

const finite = (value: unknown, fallback: number) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const normalize = (vector: TopologyLabelPoint): TopologyLabelPoint => {
  const length = Math.hypot(vector.x, vector.y);
  return length > 0.0001 ? { x: vector.x / length, y: vector.y / length } : { x: 0, y: 0 };
};

const rectFor = (point: TopologyLabelPoint, width: number, height: number, gap: number): TopologyLabelRect => ({
  x: point.x,
  y: point.y,
  width: Math.max(1, width) + gap * 2,
  height: Math.max(1, height) + gap * 2,
});

const overlaps = (left: TopologyLabelRect, right: TopologyLabelRect): boolean => (
  Math.abs(left.x - right.x) * 2 < left.width + right.width
  && Math.abs(left.y - right.y) * 2 < left.height + right.height
);

const clampPoint = (point: TopologyLabelPoint, bounds: TopologyLabelLayoutBounds | undefined, width: number, height: number) => {
  if (!bounds) return point;
  const halfWidth = Math.max(0, width / 2);
  const halfHeight = Math.max(0, height / 2);
  return {
    x: Math.max(bounds.minX + halfWidth, Math.min(bounds.maxX - halfWidth, point.x)),
    y: Math.max(bounds.minY + halfHeight, Math.min(bounds.maxY - halfHeight, point.y)),
  };
};

const candidateOffsets = (
  candidate: TopologyPortLabelCandidate,
): TopologyLabelPoint[] => {
  const normal = normalize(candidate.normal || { x: 0, y: 1 });
  const tangent = normalize(candidate.tangent || { x: 1, y: 0 });
  const perpendicular = { x: -tangent.y, y: tangent.x };
  const fanDirections = [
    normal,
    { x: -normal.x, y: -normal.y },
    perpendicular,
    { x: -perpendicular.x, y: -perpendicular.y },
    tangent,
    { x: -tangent.x, y: -tangent.y },
    { x: 0, y: 1 },
    { x: 0, y: -1 },
    { x: 1, y: 0 },
    { x: -1, y: 0 },
  ];
  const distances = [0, 14, 28, 44, 64, 88];
  const offsets: TopologyLabelPoint[] = [{ x: 0, y: 0 }];
  fanDirections.forEach((direction) => {
    const unit = normalize(direction);
    distances.slice(1).forEach((distance) => {
      offsets.push({ x: unit.x * distance, y: unit.y * distance });
    });
  });
  return offsets;
};

/**
 * Place endpoint labels without letting their background boxes cover device
 * names, node glyphs, or one another. The input point is the preferred anchor
 * produced by the graph router; all fallback positions are deterministic.
 */
export const resolveTopologyPortLabelPlacements = (
  candidates: TopologyPortLabelCandidate[],
  obstacles: TopologyLabelRect[] = [],
  options: TopologyLabelLayoutOptions = {},
): Record<string, TopologyPortLabelPlacement> => {
  const gap = Math.max(0, finite(options.gap, DEFAULT_GAP));
  const ordered = [...candidates]
    .filter((candidate) => candidate.id && Number.isFinite(candidate.x) && Number.isFinite(candidate.y))
    .sort((left, right) => (
      Number(right.priority || 0) - Number(left.priority || 0)
      || left.id.localeCompare(right.id, undefined, { numeric: true, sensitivity: 'base' })
    ));
  const placed: Array<{ rect: TopologyLabelRect; priority: number }> = [];
  const result: Record<string, TopologyPortLabelPlacement> = {};

  ordered.forEach((candidate) => {
    const width = Math.max(1, finite(candidate.width, 1));
    const height = Math.max(1, finite(candidate.height, 1));
    const priority = Number(candidate.priority || 0);
    let best: { point: TopologyLabelPoint; collisions: number; displacement: number } | null = null;

    candidateOffsets(candidate).forEach((offset) => {
      const unclamped = { x: candidate.x + offset.x, y: candidate.y + offset.y };
      const point = clampPoint(unclamped, options.bounds, width + gap * 2, height + gap * 2);
      const rect = rectFor(point, width, height, gap);
      const collisions = obstacles.reduce((count, obstacle) => count + Number(overlaps(rect, obstacle)), 0)
        + placed.reduce((count, previous) => count + Number(overlaps(rect, previous.rect)), 0);
      const displacement = Math.hypot(point.x - candidate.x, point.y - candidate.y);
      const score = collisions * 100000 + displacement;
      const bestScore = best ? best.collisions * 100000 + best.displacement : Number.POSITIVE_INFINITY;
      if (score < bestScore) best = { point, collisions, displacement };
    });

    const placement = best || { point: { x: candidate.x, y: candidate.y }, collisions: 0, displacement: 0 };
    const hidden = Boolean(options.hideOnCollision && placement.collisions > 0 && priority < 100);
    result[candidate.id] = { ...placement.point, hidden };
    if (!hidden) {
      placed.push({
        rect: rectFor(placement.point, width, height, gap),
        priority,
      });
    }
  });

  return result;
};

