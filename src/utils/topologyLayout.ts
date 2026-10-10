export type TopologyLayoutPoint = {
  x: number;
  y: number;
};

export type TopologyLayoutNode = TopologyLayoutPoint & {
  id: string;
};

export type TopologyLayoutLink = {
  source_device_id?: string | number;
  target_device_id?: string | number;
  source?: string | number | { id?: string | number };
  target?: string | number | { id?: string | number };
  relation_type?: string;
};

export type TopologyLayoutBounds = {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
};

export type TopologyLayoutRepairOptions = Partial<TopologyLayoutBounds> & {
  nodeRadius?: number;
  edgeGap?: number;
  nodeGap?: number;
  maxPasses?: number;
  maxCrossingPasses?: number;
};

export type TopologyLayoutMetrics = {
  crossings: number;
  edgeNodeConflicts: number;
  edgeNodeViolation: number;
  nodeOverlaps: number;
  minEdgeNodeDistance: number | null;
};

/**
 * Place each connected RING relation component on a deterministic circle.
 * The generic force/layer layout remains the seed for the component centre,
 * so multiple rings and sites stay in their natural lanes.
 */
export const buildRingGroupPositions = (
  nodes: Array<{ id: string }>,
  links: TopologyLayoutLink[],
  width: number,
  height: number,
  seedPositions: Record<string, TopologyLayoutPoint> = {},
): Record<string, TopologyLayoutPoint> => {
  const nodeIds = new Set(nodes.map((node) => String(node.id)));
  const adjacency = new Map<string, Set<string>>();
  const resolveEndpoint = (endpoint: TopologyLayoutLink['source'] | TopologyLayoutLink['target'], fallback: unknown) => {
    if (endpoint && typeof endpoint === 'object') return String(endpoint.id || '');
    return String(endpoint ?? fallback ?? '');
  };
  links.forEach((link) => {
    if (String(link.relation_type || '').toUpperCase() !== 'RING') return;
    const source = resolveEndpoint(link.source, link.source_device_id);
    const target = resolveEndpoint(link.target, link.target_device_id);
    if (!nodeIds.has(source) || !nodeIds.has(target) || source === target) return;
    if (!adjacency.has(source)) adjacency.set(source, new Set());
    if (!adjacency.has(target)) adjacency.set(target, new Set());
    adjacency.get(source)?.add(target);
    adjacency.get(target)?.add(source);
  });

  const components: string[][] = [];
  const visited = new Set<string>();
  Array.from(adjacency.keys()).sort().forEach((start) => {
    if (visited.has(start)) return;
    const members: string[] = [];
    const queue = [start];
    visited.add(start);
    while (queue.length) {
      const current = queue.shift() as string;
      members.push(current);
      Array.from(adjacency.get(current) || []).sort().forEach((neighbor) => {
        if (visited.has(neighbor)) return;
        visited.add(neighbor);
        queue.push(neighbor);
      });
    }
    if (members.length >= 3) components.push(members.sort());
  });

  const positions: Record<string, TopologyLayoutPoint> = {};
  components.sort((left, right) => left[0].localeCompare(right[0])).forEach((members, componentIndex) => {
    const seeded = members.map((member) => seedPositions[member]).filter(Boolean);
    const fallbackX = width * (componentIndex + 1) / (components.length + 1);
    const centerX = seeded.length ? seeded.reduce((sum, point) => sum + point.x, 0) / seeded.length : fallbackX;
    const centerY = seeded.length ? seeded.reduce((sum, point) => sum + point.y, 0) / seeded.length : height / 2;
    const radius = Math.min(Math.max(110, members.length * 34), Math.max(110, Math.min(width, height) * 0.32));
    members.forEach((member, index) => {
      const angle = -Math.PI / 2 + (2 * Math.PI * index) / members.length;
      positions[member] = {
        x: Math.max(72, Math.min(width - 72, centerX + Math.cos(angle) * radius)),
        y: Math.max(82, Math.min(height - 82, centerY + Math.sin(angle) * radius)),
      };
    });
  });
  return positions;
};

/**
 * Lay out a point-to-point chain as a folded two-column path.  A chain such
 * as A-B-C-D-E-F becomes C-D on the top row, B-E on the middle row, and A-F
 * on the bottom row.  This preserves the path order while avoiding the
 * misleading diagonal tangle produced by a generic force layout.
 */
export const buildFoldedChainPositions = (
  order: string[],
  width: number,
  height: number,
): Record<string, TopologyLayoutPoint> => {
  if (order.length === 0) return {};

  const rowCount = Math.ceil(order.length / 2);
  const topInset = Math.min(108, Math.max(72, height * 0.14));
  const bottomInset = Math.min(108, Math.max(72, height * 0.14));
  const availableHeight = Math.max(0, height - topInset - bottomInset);
  const rowGap = rowCount > 1
    ? Math.min(176, Math.max(124, availableHeight / Math.max(rowCount - 1, 1)))
    : 0;
  const totalHeight = rowGap * Math.max(rowCount - 1, 0);
  const firstY = rowCount > 1
    ? Math.max(56, Math.min(
      Math.max(topInset, height - bottomInset - totalHeight),
      topInset + Math.max(0, (availableHeight - totalHeight) / 2),
    ))
    : Math.max(56, Math.min(height - 56, height * 0.42));

  const columnGap = Math.min(300, Math.max(180, width * 0.34));
  const leftX = Math.max(72, Math.min(width - 72, width / 2 - columnGap / 2));
  const rightX = Math.max(72, Math.min(width - 72, width / 2 + columnGap / 2));
  const positions: Record<string, TopologyLayoutPoint> = {};

  order.forEach((id, index) => {
    const isLeftColumn = index < rowCount;
    const row = isLeftColumn ? rowCount - 1 - index : index - rowCount;
    positions[id] = {
      x: isLeftColumn ? leftX : rightX,
      y: firstY + row * rowGap,
    };
  });

  return positions;
};

type ResolvedEdge = {
  sourceId: string;
  targetId: string;
  index: number;
};

type SegmentPoint = TopologyLayoutPoint & {
  distance: number;
};

const DEFAULT_OPTIONS = {
  nodeRadius: 44,
  edgeGap: 18,
  nodeGap: 14,
  maxPasses: 10,
  maxCrossingPasses: 16,
};

const toFiniteNumber = (value: unknown, fallback: number) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const normalizeOptions = (options: TopologyLayoutRepairOptions = {}) => ({
  minX: toFiniteNumber(options.minX, 48),
  maxX: toFiniteNumber(options.maxX, 999999),
  minY: toFiniteNumber(options.minY, 56),
  maxY: toFiniteNumber(options.maxY, 999999),
  nodeRadius: Math.max(1, toFiniteNumber(options.nodeRadius, DEFAULT_OPTIONS.nodeRadius)),
  edgeGap: Math.max(0, toFiniteNumber(options.edgeGap, DEFAULT_OPTIONS.edgeGap)),
  nodeGap: Math.max(0, toFiniteNumber(options.nodeGap, DEFAULT_OPTIONS.nodeGap)),
  maxPasses: Math.max(1, Math.round(toFiniteNumber(options.maxPasses, DEFAULT_OPTIONS.maxPasses))),
  maxCrossingPasses: Math.max(0, Math.round(toFiniteNumber(options.maxCrossingPasses, DEFAULT_OPTIONS.maxCrossingPasses))),
});

const getEndpointId = (link: TopologyLayoutLink, side: 'source' | 'target'): string => {
  const explicitId = side === 'source' ? link.source_device_id : link.target_device_id;
  if (explicitId !== undefined && explicitId !== null && String(explicitId).trim()) {
    return String(explicitId);
  }

  const endpoint = side === 'source' ? link.source : link.target;
  if (endpoint && typeof endpoint === 'object' && 'id' in endpoint) {
    return String(endpoint.id ?? '');
  }
  return endpoint === undefined || endpoint === null ? '' : String(endpoint);
};

const resolveEdges = (links: TopologyLayoutLink[], nodeIds: Set<string>): ResolvedEdge[] => links
  .map((link, index) => ({
    sourceId: getEndpointId(link, 'source'),
    targetId: getEndpointId(link, 'target'),
    index,
  }))
  .filter((link) => (
    link.sourceId
    && link.targetId
    && link.sourceId !== link.targetId
    && nodeIds.has(link.sourceId)
    && nodeIds.has(link.targetId)
  ));

const clonePositions = (positions: Map<string, TopologyLayoutPoint>) => new Map(
  Array.from(positions.entries()).map(([id, point]) => [id, { x: point.x, y: point.y }]),
);

const clampPoint = (point: TopologyLayoutPoint, bounds: TopologyLayoutBounds): TopologyLayoutPoint => ({
  x: Math.max(bounds.minX, Math.min(bounds.maxX, point.x)),
  y: Math.max(bounds.minY, Math.min(bounds.maxY, point.y)),
});

const getClosestPointOnSegment = (
  point: TopologyLayoutPoint,
  start: TopologyLayoutPoint,
  end: TopologyLayoutPoint,
): SegmentPoint => {
  const deltaX = end.x - start.x;
  const deltaY = end.y - start.y;
  const lengthSquared = deltaX * deltaX + deltaY * deltaY;
  const ratio = lengthSquared <= 0
    ? 0
    : Math.max(0, Math.min(1, ((point.x - start.x) * deltaX + (point.y - start.y) * deltaY) / lengthSquared));
  const x = start.x + deltaX * ratio;
  const y = start.y + deltaY * ratio;
  return {
    x,
    y,
    distance: Math.hypot(point.x - x, point.y - y),
  };
};

const stableHash = (value: string) => Array.from(value).reduce(
  (hash, character) => ((hash * 31) + character.charCodeAt(0)) | 0,
  17,
);

const getSeparationNormal = (
  point: TopologyLayoutPoint,
  closest: SegmentPoint,
  start: TopologyLayoutPoint,
  end: TopologyLayoutPoint,
  stableKey: string,
): TopologyLayoutPoint => {
  const deltaX = point.x - closest.x;
  const deltaY = point.y - closest.y;
  const distance = Math.hypot(deltaX, deltaY);
  if (distance > 0.0001) {
    return { x: deltaX / distance, y: deltaY / distance };
  }

  const edgeDeltaX = end.x - start.x;
  const edgeDeltaY = end.y - start.y;
  const edgeLength = Math.max(1, Math.hypot(edgeDeltaX, edgeDeltaY));
  const sign = stableHash(stableKey) % 2 === 0 ? 1 : -1;
  return {
    x: (-edgeDeltaY / edgeLength) * sign,
    y: (edgeDeltaX / edgeLength) * sign,
  };
};

const getSegmentIntersection = (
  firstStart: TopologyLayoutPoint,
  firstEnd: TopologyLayoutPoint,
  secondStart: TopologyLayoutPoint,
  secondEnd: TopologyLayoutPoint,
) => {
  const firstDeltaX = firstEnd.x - firstStart.x;
  const firstDeltaY = firstEnd.y - firstStart.y;
  const secondDeltaX = secondEnd.x - secondStart.x;
  const secondDeltaY = secondEnd.y - secondStart.y;
  const denominator = firstDeltaX * secondDeltaY - firstDeltaY * secondDeltaX;
  if (Math.abs(denominator) < 0.0001) return null;

  const startDeltaX = secondStart.x - firstStart.x;
  const startDeltaY = secondStart.y - firstStart.y;
  const firstRatio = (startDeltaX * secondDeltaY - startDeltaY * secondDeltaX) / denominator;
  const secondRatio = (startDeltaX * firstDeltaY - startDeltaY * firstDeltaX) / denominator;
  if (firstRatio <= 0.08 || firstRatio >= 0.92 || secondRatio <= 0.08 || secondRatio >= 0.92) return null;

  return {
    x: firstStart.x + firstRatio * firstDeltaX,
    y: firstStart.y + firstRatio * firstDeltaY,
  };
};

const getCrossing = (
  first: ResolvedEdge,
  second: ResolvedEdge,
  positions: Map<string, TopologyLayoutPoint>,
) => {
  if ([first.sourceId, first.targetId].some((id) => id === second.sourceId || id === second.targetId)) return null;
  const firstStart = positions.get(first.sourceId);
  const firstEnd = positions.get(first.targetId);
  const secondStart = positions.get(second.sourceId);
  const secondEnd = positions.get(second.targetId);
  if (!firstStart || !firstEnd || !secondStart || !secondEnd) return null;
  return getSegmentIntersection(firstStart, firstEnd, secondStart, secondEnd);
};

const findFirstCrossing = (edges: ResolvedEdge[], positions: Map<string, TopologyLayoutPoint>) => {
  for (let firstIndex = 0; firstIndex < edges.length; firstIndex += 1) {
    for (let secondIndex = firstIndex + 1; secondIndex < edges.length; secondIndex += 1) {
      const point = getCrossing(edges[firstIndex], edges[secondIndex], positions);
      if (point) {
        return {
          first: edges[firstIndex],
          second: edges[secondIndex],
          point,
        };
      }
    }
  }
  return null;
};

const getCrossingCount = (edges: ResolvedEdge[], positions: Map<string, TopologyLayoutPoint>) => {
  let crossings = 0;
  for (let firstIndex = 0; firstIndex < edges.length; firstIndex += 1) {
    for (let secondIndex = firstIndex + 1; secondIndex < edges.length; secondIndex += 1) {
      if (getCrossing(edges[firstIndex], edges[secondIndex], positions)) crossings += 1;
    }
  }
  return crossings;
};

const getEdgeNodeStats = (
  nodes: TopologyLayoutNode[],
  edges: ResolvedEdge[],
  positions: Map<string, TopologyLayoutPoint>,
  clearance: number,
) => {
  let edgeNodeConflicts = 0;
  let edgeNodeViolation = 0;
  let minEdgeNodeDistance = Infinity;

  nodes.forEach((node) => {
    const point = positions.get(node.id);
    if (!point) return;
    edges.forEach((edge) => {
      if (edge.sourceId === node.id || edge.targetId === node.id) return;
      const start = positions.get(edge.sourceId);
      const end = positions.get(edge.targetId);
      if (!start || !end) return;
      const closest = getClosestPointOnSegment(point, start, end);
      minEdgeNodeDistance = Math.min(minEdgeNodeDistance, closest.distance);
      if (closest.distance < clearance) {
        edgeNodeConflicts += 1;
        edgeNodeViolation += clearance - closest.distance;
      }
    });
  });

  return {
    edgeNodeConflicts,
    edgeNodeViolation,
    minEdgeNodeDistance: Number.isFinite(minEdgeNodeDistance) ? minEdgeNodeDistance : null,
  };
};

const getNodeOverlapStats = (
  nodes: TopologyLayoutNode[],
  positions: Map<string, TopologyLayoutPoint>,
  minimumDistance: number,
) => {
  let nodeOverlaps = 0;
  let overlapDistance = 0;
  for (let firstIndex = 0; firstIndex < nodes.length; firstIndex += 1) {
    const first = positions.get(nodes[firstIndex].id);
    if (!first) continue;
    for (let secondIndex = firstIndex + 1; secondIndex < nodes.length; secondIndex += 1) {
      const second = positions.get(nodes[secondIndex].id);
      if (!second) continue;
      const distance = Math.hypot(first.x - second.x, first.y - second.y);
      if (distance < minimumDistance) {
        nodeOverlaps += 1;
        overlapDistance += minimumDistance - distance;
      }
    }
  }
  return { nodeOverlaps, overlapDistance };
};

const getLayoutScore = (
  nodes: TopologyLayoutNode[],
  edges: ResolvedEdge[],
  positions: Map<string, TopologyLayoutPoint>,
  initialPositions: Map<string, TopologyLayoutPoint>,
  options: ReturnType<typeof normalizeOptions>,
) => {
  const clearance = options.nodeRadius + options.edgeGap;
  const edgeNodeStats = getEdgeNodeStats(nodes, edges, positions, clearance);
  const overlapStats = getNodeOverlapStats(nodes, positions, options.nodeRadius * 1.75 + options.nodeGap);
  let movement = 0;
  positions.forEach((point, id) => {
    const initial = initialPositions.get(id);
    if (initial) movement += Math.hypot(point.x - initial.x, point.y - initial.y);
  });

  // Removing a crossing is the strongest objective.  The remaining terms
  // keep the repair local and prevent it from trading a crossing for a node
  // overlap or a line passing through another device.
  return getCrossingCount(edges, positions) * 10000
    + edgeNodeStats.edgeNodeViolation * 40
    + overlapStats.nodeOverlaps * 6000
    + overlapStats.overlapDistance * 40
    + movement * 0.02;
};

const getCompassDirections = (): TopologyLayoutPoint[] => [
  { x: 1, y: 0 },
  { x: -1, y: 0 },
  { x: 0, y: 1 },
  { x: 0, y: -1 },
  { x: Math.SQRT1_2, y: Math.SQRT1_2 },
  { x: -Math.SQRT1_2, y: Math.SQRT1_2 },
  { x: Math.SQRT1_2, y: -Math.SQRT1_2 },
  { x: -Math.SQRT1_2, y: -Math.SQRT1_2 },
];

const normalizeDirection = (direction: TopologyLayoutPoint): TopologyLayoutPoint | null => {
  const length = Math.hypot(direction.x, direction.y);
  return length > 0.0001 ? { x: direction.x / length, y: direction.y / length } : null;
};

const uniqueDirections = (directions: TopologyLayoutPoint[]) => {
  const seen = new Set<string>();
  return directions
    .map(normalizeDirection)
    .filter((direction): direction is TopologyLayoutPoint => Boolean(direction))
    .filter((direction) => {
      const key = `${direction.x.toFixed(3)}:${direction.y.toFixed(3)}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
};

export const measureTopologyLayout = (
  nodes: TopologyLayoutNode[],
  links: TopologyLayoutLink[],
  options: TopologyLayoutRepairOptions = {},
): TopologyLayoutMetrics => {
  const normalized = normalizeOptions(options);
  const positions = new Map(nodes.map((node) => [node.id, { x: node.x, y: node.y }]));
  const edges = resolveEdges(links, new Set(nodes.map((node) => node.id)));
  const edgeNodeStats = getEdgeNodeStats(nodes, edges, positions, normalized.nodeRadius + normalized.edgeGap);
  const overlapStats = getNodeOverlapStats(nodes, positions, normalized.nodeRadius * 1.75 + normalized.nodeGap);
  return {
    crossings: getCrossingCount(edges, positions),
    ...edgeNodeStats,
    nodeOverlaps: overlapStats.nodeOverlaps,
  };
};

export const repairTopologyLayout = (
  nodes: TopologyLayoutNode[],
  links: TopologyLayoutLink[],
  options: TopologyLayoutRepairOptions = {},
): Record<string, TopologyLayoutPoint> => {
  if (nodes.length <= 1) {
    return Object.fromEntries(nodes.map((node) => [node.id, { x: node.x, y: node.y }]));
  }

  const normalized = normalizeOptions(options);
  const bounds: TopologyLayoutBounds = {
    minX: Math.min(normalized.minX, normalized.maxX),
    maxX: Math.max(normalized.minX, normalized.maxX),
    minY: Math.min(normalized.minY, normalized.maxY),
    maxY: Math.max(normalized.minY, normalized.maxY),
  };
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges = resolveEdges(links, nodeIds);
  const positions = new Map(nodes.map((node) => [node.id, clampPoint({ x: node.x, y: node.y }, bounds)]));
  const initialPositions = clonePositions(positions);
  const clearance = normalized.nodeRadius + normalized.edgeGap;
  const degrees = new Map<string, number>();
  nodes.forEach((node) => degrees.set(node.id, 0));
  edges.forEach((edge) => {
    degrees.set(edge.sourceId, (degrees.get(edge.sourceId) || 0) + 1);
    degrees.set(edge.targetId, (degrees.get(edge.targetId) || 0) + 1);
  });

  const relaxEdgeNodeConflicts = () => {
    for (let pass = 0; pass < normalized.maxPasses; pass += 1) {
      const adjustments = new Map<string, TopologyLayoutPoint>();
      let hasConflict = false;

      nodes.forEach((node) => {
        const point = positions.get(node.id);
        if (!point) return;
        edges.forEach((edge) => {
          if (edge.sourceId === node.id || edge.targetId === node.id) return;
          const start = positions.get(edge.sourceId);
          const end = positions.get(edge.targetId);
          if (!start || !end) return;

          const closest = getClosestPointOnSegment(point, start, end);
          if (closest.distance >= clearance) return;
          hasConflict = true;
          const normal = getSeparationNormal(
            point,
            closest,
            start,
            end,
            `${node.id}:${edge.index}`,
          );
          const amount = Math.min(46, clearance - closest.distance + 6);
          const current = adjustments.get(node.id) || { x: 0, y: 0 };
          adjustments.set(node.id, {
            x: current.x + normal.x * amount,
            y: current.y + normal.y * amount,
          });
        });
    });

      if (!hasConflict) break;
      const beforePass = clonePositions(positions);
      const crossingsBeforePass = getCrossingCount(edges, positions);
      adjustments.forEach((adjustment, id) => {
        const point = positions.get(id);
        if (!point) return;
        const length = Math.hypot(adjustment.x, adjustment.y);
        const maxAdjustment = 54;
        const scale = length > maxAdjustment ? maxAdjustment / length : 1;
        positions.set(id, clampPoint({
          x: point.x + adjustment.x * scale,
          y: point.y + adjustment.y * scale,
        }, bounds));
      });
      if (getCrossingCount(edges, positions) > crossingsBeforePass) {
        beforePass.forEach((point, id) => positions.set(id, point));
        break;
      }
    }
  };

  relaxEdgeNodeConflicts();

  // Crossing evaluation is quadratic in the number of links. Keep the
  // guaranteed edge-node repair for large graphs, while bounding the more
  // expensive local search so opening a dense topology cannot freeze the UI.
  const crossingPassLimit = nodes.length > 120 || edges.length > 160
    ? 0
    : nodes.length > 80 || edges.length > 100
      ? Math.min(normalized.maxCrossingPasses, 3)
      : edges.length > 60
        ? Math.min(normalized.maxCrossingPasses, 6)
        : normalized.maxCrossingPasses;
  for (let pass = 0; pass < crossingPassLimit; pass += 1) {
    const crossing = findFirstCrossing(edges, positions);
    if (!crossing) break;

    const candidateIds = Array.from(new Set([
      crossing.first.sourceId,
      crossing.first.targetId,
      crossing.second.sourceId,
      crossing.second.targetId,
    ])).sort((left, right) => (
      (degrees.get(left) || 0) - (degrees.get(right) || 0)
      || left.localeCompare(right)
    ));
    const firstStart = positions.get(crossing.first.sourceId);
    const firstEnd = positions.get(crossing.first.targetId);
    const secondStart = positions.get(crossing.second.sourceId);
    const secondEnd = positions.get(crossing.second.targetId);
    if (!firstStart || !firstEnd || !secondStart || !secondEnd) break;

    const firstDirection = normalizeDirection({ x: firstEnd.x - firstStart.x, y: firstEnd.y - firstStart.y }) || { x: 1, y: 0 };
    const secondDirection = normalizeDirection({ x: secondEnd.x - secondStart.x, y: secondEnd.y - secondStart.y }) || { x: 0, y: 1 };
    const radialDirections = candidateIds.map((id) => {
      const point = positions.get(id) || crossing.point;
      return { x: point.x - crossing.point.x, y: point.y - crossing.point.y };
    });
    const directions = uniqueDirections([
      ...radialDirections,
      ...radialDirections.map((direction) => ({ x: -direction.x, y: -direction.y })),
      { x: -firstDirection.y, y: firstDirection.x },
      { x: firstDirection.y, y: -firstDirection.x },
      { x: -secondDirection.y, y: secondDirection.x },
      { x: secondDirection.y, y: -secondDirection.x },
      ...getCompassDirections(),
    ]);
    const baselineScore = getLayoutScore(nodes, edges, positions, initialPositions, normalized);
    const baselineCrossings = getCrossingCount(edges, positions);
    let bestScore = baselineScore;
    let bestId: string | null = null;
    let bestPoint: TopologyLayoutPoint | null = null;

    candidateIds.forEach((id) => {
      const point = positions.get(id);
      if (!point) return;
      directions.forEach((direction) => {
        // The first three steps keep ordinary crossings local. The larger
        // escape steps are needed when a crossing is bounded by a long edge:
        // a small nudge can leave the same intersection inside both segments.
        [24, 44, 68, 112, 160, 208].forEach((distance) => {
          const candidate = clampPoint({
            x: point.x + direction.x * distance,
            y: point.y + direction.y * distance,
          }, bounds);
          if (candidate.x === point.x && candidate.y === point.y) return;
          positions.set(id, candidate);
          const candidateCrossings = getCrossingCount(edges, positions);
          const score = candidateCrossings > baselineCrossings
            ? Number.POSITIVE_INFINITY
            : getLayoutScore(nodes, edges, positions, initialPositions, normalized);
          positions.set(id, point);
          if (score + 0.01 < bestScore) {
            bestScore = score;
            bestId = id;
            bestPoint = candidate;
          }
        });
      });
    });

    if (!bestId || !bestPoint) break;
    const beforeCandidate = clonePositions(positions);
    positions.set(bestId, bestPoint);
    relaxEdgeNodeConflicts();
    const repairedCrossings = getCrossingCount(edges, positions);
    const repairedScore = getLayoutScore(nodes, edges, positions, initialPositions, normalized);
    if (repairedCrossings > baselineCrossings || repairedScore + 0.01 >= baselineScore) {
      beforeCandidate.forEach((point, id) => positions.set(id, point));
      break;
    }
  }

  return Object.fromEntries(nodes.map((node) => [node.id, positions.get(node.id) || { x: node.x, y: node.y }]));
};
