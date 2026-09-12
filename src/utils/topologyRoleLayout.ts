import { canonicalTopologyRole, topologyRoleVisualTier } from '../domain/topologyRoles';

export type TopologyRoleLayoutDevice = {
  id: string;
  hostname?: string;
  role?: unknown;
  role_identity?: unknown;
  device_category?: unknown;
  topology_rank?: unknown;
  relation_rank?: unknown;
  rank?: unknown;
};
export type TopologyRoleLayoutPoint = {
  x: number;
  y: number;
};

export type TopologyRoleLayoutLink = {
  source_device_id?: unknown;
  target_device_id?: unknown;
  relation_type?: unknown;
  discovery_source?: unknown;
  discovery_sources?: unknown;
  inferred?: unknown;
};

export type TopologyLayerSource = 'evidence' | 'role';

export type TopologyLayerSelection = {
  layers: Array<number | null>;
  source: TopologyLayerSource;
};

const toFiniteLayer = (value: unknown): number | null => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(0, Math.round(parsed)) : null;
};

const getEvidenceLayer = (device: TopologyRoleLayoutDevice): number | null => (
  toFiniteLayer(device.topology_rank ?? device.relation_rank ?? device.rank)
);

const getRoleLayer = (device: TopologyRoleLayoutDevice): number | null => {
  for (const value of [device.role_identity, device.role, device.device_category]) {
    const roleKey = canonicalTopologyRole(value);
    if (!roleKey || roleKey === 'unknown') continue;
    const layer = topologyRoleVisualTier(roleKey);
    if (layer !== null) return layer;
  }
  return null;
};

/**
 * Select the visual layer source without changing the graph's semantic rank
 * data. Recognized role tiers define the human-facing hierarchy (core,
 * distribution, access); relation ranks remain the fallback for graphs whose
 * devices do not carry enough role information.
 */
export const selectTopologyLayoutLayers = (
  devices: TopologyRoleLayoutDevice[],
): TopologyLayerSelection | null => {
  const roleLayers = devices.map(getRoleLayer);
  const roleValues = roleLayers.filter((layer): layer is number => layer !== null);
  if (roleValues.length > 0 && new Set(roleValues).size > 1) {
    // A missing role is not evidence that the device belongs to the highest
    // known tier. Putting it there makes blank/UNKNOWN assets share a row with
    // access devices and causes the row separator labels to overlap. Reserve
    // the next visual tier for those devices instead.
    const fallbackLayer = Math.max(4, Math.max(...roleValues) + 1);
    return {
      layers: roleLayers.map((layer) => layer ?? fallbackLayer),
      source: 'role',
    };
  }

  const evidenceLayers = devices.map(getEvidenceLayer);
  const evidenceValues = evidenceLayers.filter((layer): layer is number => layer !== null);
  const evidenceDistinct = new Set(evidenceValues);
  if (evidenceValues.some((layer) => layer > 0) && evidenceDistinct.size > 1) {
    return { layers: evidenceLayers, source: 'evidence' };
  }
  return null;
};

const clampPosition = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));
const MIN_NODE_CENTER_GAP = 72;
const NODE_LABEL_GAP = 12;

const estimateTopologyLabelWidth = (value: unknown): number => {
  const text = String(value || '').trim();
  const width = Array.from(text).reduce((total, character) => (
    total + (/^[\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef]$/u.test(character) ? 12 : 7.2)
  ), 0);
  return Math.max(56, Math.ceil(width + 16));
};

const isFinitePoint = (point: TopologyRoleLayoutPoint | undefined): point is TopologyRoleLayoutPoint => (
  Number.isFinite(point?.x) && Number.isFinite(point?.y)
);

const getNodeHalfExtent = (device: TopologyRoleLayoutDevice): number => (
  Math.max(MIN_NODE_CENTER_GAP / 2, estimateTopologyLabelWidth(device.hostname) / 2)
);

const compareDevices = (left: TopologyRoleLayoutDevice, right: TopologyRoleLayoutDevice) => (
  String(left.hostname || left.id).localeCompare(String(right.hostname || right.id), undefined, {
    numeric: true,
    sensitivity: 'base',
  })
);

type TopologyLayoutEdge = {
  sourceId: string;
  targetId: string;
};

const normalizeLinkEndpoint = (value: unknown): string => String(value ?? '').trim();

const normalizeLinkSources = (link: TopologyRoleLayoutLink): string[] => {
  const values = [
    ...(Array.isArray(link.discovery_sources) ? link.discovery_sources : [link.discovery_sources]),
    link.discovery_source,
  ];
  return values
    .flatMap((value) => String(value || '').split(/[+,\s]+/u))
    .map((value) => value.trim().toUpperCase())
    .filter(Boolean);
};

const isPhysicalLayoutLink = (link: TopologyRoleLayoutLink): boolean => {
  if (link.inferred === true || Number(link.inferred) === 1) return false;
  const relation = String(link.relation_type || '').trim().toUpperCase();
  const sources = normalizeLinkSources(link);
  const hasDiscoveryEvidence = sources.some((source) => source === 'LLDP' || source === 'CDP');
  if (relation === 'PHYSICAL' || hasDiscoveryEvidence) return true;
  // Legacy physical-link responses may not expose relation_type, but they are
  // still safe to use when they are explicitly marked as non-inferred.
  return !relation;
};

const collectPhysicalLayoutEdges = (links: TopologyRoleLayoutLink[]): TopologyLayoutEdge[] => {
  const seen = new Set<string>();
  const edges: TopologyLayoutEdge[] = [];
  links.forEach((link) => {
    if (!isPhysicalLayoutLink(link)) return;
    const sourceId = normalizeLinkEndpoint(link.source_device_id);
    const targetId = normalizeLinkEndpoint(link.target_device_id);
    if (!sourceId || !targetId || sourceId === targetId) return;
    const [left, right] = [sourceId, targetId].sort();
    const key = `${left}::${right}`;
    if (seen.has(key)) return;
    seen.add(key);
    edges.push({ sourceId: left, targetId: right });
  });
  return edges;
};

const cloneLayerOrder = (order: Map<number, string[]>): Map<number, string[]> => (
  new Map(Array.from(order.entries()).map(([layer, ids]) => [layer, [...ids]]))
);

const buildOrderIndexes = (order: Map<number, string[]>): Map<string, number> => {
  const result = new Map<string, number>();
  order.forEach((ids) => ids.forEach((id, index) => result.set(id, index)));
  return result;
};

const countCrossingsForLayerOrder = (
  order: Map<number, string[]>,
  layerById: Map<string, number>,
  edges: TopologyLayoutEdge[],
): number => {
  const layerOrder = Array.from(order.keys()).sort((left, right) => left - right);
  const rowIndexByLayer = new Map(layerOrder.map((layer, index) => [layer, index]));
  const positionById = buildOrderIndexes(order);
  const edgePairs = new Map<string, Array<[number, number]>>();

  edges.forEach(({ sourceId, targetId }) => {
    const sourceLayer = layerById.get(sourceId);
    const targetLayer = layerById.get(targetId);
    if (sourceLayer === undefined || targetLayer === undefined || sourceLayer === targetLayer) return;
    const sourceRow = rowIndexByLayer.get(sourceLayer);
    const targetRow = rowIndexByLayer.get(targetLayer);
    const sourcePosition = positionById.get(sourceId);
    const targetPosition = positionById.get(targetId);
    if (sourceRow === undefined || targetRow === undefined || sourcePosition === undefined || targetPosition === undefined) return;

    const isSourceAbove = sourceRow < targetRow;
    const upperRow = isSourceAbove ? sourceRow : targetRow;
    const lowerRow = isSourceAbove ? targetRow : sourceRow;
    const upperPosition = isSourceAbove ? sourcePosition : targetPosition;
    const lowerPosition = isSourceAbove ? targetPosition : sourcePosition;
    const key = `${upperRow}:${lowerRow}`;
    const pairs = edgePairs.get(key) || [];
    pairs.push([upperPosition, lowerPosition]);
    edgePairs.set(key, pairs);
  });

  let crossings = 0;
  edgePairs.forEach((pairs) => {
    for (let leftIndex = 0; leftIndex < pairs.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < pairs.length; rightIndex += 1) {
        const [leftUpper, leftLower] = pairs[leftIndex];
        const [rightUpper, rightLower] = pairs[rightIndex];
        if (leftUpper === rightUpper || leftLower === rightLower) continue;
        if ((leftUpper - rightUpper) * (leftLower - rightLower) < 0) crossings += 1;
      }
    }
  });
  return crossings;
};

const orderLayeredRowsByLinks = (
  grouped: Map<number, TopologyRoleLayoutDevice[]>,
  devices: TopologyRoleLayoutDevice[],
  selection: TopologyLayerSelection,
  links: TopologyRoleLayoutLink[],
): Map<number, string[]> => {
  const deviceById = new Map(devices.map((device) => [device.id, device]));
  const layerById = new Map<string, number>();
  devices.forEach((device, index) => {
    const layer = selection.layers[index];
    if (layer !== null) layerById.set(device.id, layer);
  });
  const edges = collectPhysicalLayoutEdges(links)
    .filter(({ sourceId, targetId }) => deviceById.has(sourceId) && deviceById.has(targetId));
  const neighbors = new Map<string, Set<string>>();
  edges.forEach(({ sourceId, targetId }) => {
    if (!neighbors.has(sourceId)) neighbors.set(sourceId, new Set());
    if (!neighbors.has(targetId)) neighbors.set(targetId, new Set());
    neighbors.get(sourceId)?.add(targetId);
    neighbors.get(targetId)?.add(sourceId);
  });

  const order = new Map<number, string[]>();
  grouped.forEach((rowDevices, layer) => {
    order.set(layer, [...rowDevices].sort(compareDevices).map((device) => device.id));
  });
  if (edges.length === 0 || order.size < 2) return order;

  const layerKeys = Array.from(order.keys()).sort((left, right) => left - right);
  const stableIndexById = buildOrderIndexes(order);
  let bestOrder = cloneLayerOrder(order);
  let bestCrossings = countCrossingsForLayerOrder(order, layerById, edges);

  for (let pass = 0; pass < 8; pass += 1) {
    const rowIndexes = layerKeys.map((_, index) => index);
    if (pass % 2 === 1) rowIndexes.reverse();
    rowIndexes.forEach((rowIndex) => {
      const layer = layerKeys[rowIndex];
      const row = order.get(layer) || [];
      if (row.length < 2) return;
      const currentIndexes = buildOrderIndexes(order);
      const currentRowLength = Math.max(row.length - 1, 1);
      const scored = row.map((id, currentIndex) => {
        const neighborPositions = Array.from(neighbors.get(id) || [])
          .filter((neighborId) => layerById.get(neighborId) !== layer)
          .map((neighborId) => {
            const neighborLayer = layerById.get(neighborId);
            const neighborIndex = currentIndexes.get(neighborId);
            const neighborRow = neighborLayer === undefined ? undefined : order.get(neighborLayer);
            if (neighborIndex === undefined || !neighborRow) return null;
            return neighborRow.length > 1
              ? (neighborIndex / (neighborRow.length - 1)) * currentRowLength
              : currentRowLength / 2;
          })
          .filter((value): value is number => value !== null);
        const barycenter = neighborPositions.length > 0
          ? neighborPositions.reduce((sum, value) => sum + value, 0) / neighborPositions.length
          : currentIndex;
        return {
          id,
          barycenter,
          currentIndex,
          stableIndex: stableIndexById.get(id) ?? currentIndex,
        };
      });
      scored.sort((left, right) => (
        left.barycenter - right.barycenter
        || left.currentIndex - right.currentIndex
        || left.stableIndex - right.stableIndex
        || compareDevices(deviceById.get(left.id) || { id: left.id }, deviceById.get(right.id) || { id: right.id })
      ));
      order.set(layer, scored.map((entry) => entry.id));
    });

    const crossings = countCrossingsForLayerOrder(order, layerById, edges);
    if (crossings < bestCrossings) {
      bestCrossings = crossings;
      bestOrder = cloneLayerOrder(order);
    }
    if (bestCrossings === 0) break;
  }
  return bestOrder;
};

/** Count physical-link crossings for a rendered role-layer position map. */
export const countTopologyLayerCrossings = (
  devices: TopologyRoleLayoutDevice[],
  links: TopologyRoleLayoutLink[],
  positions: Record<string, TopologyRoleLayoutPoint>,
): number => {
  const selection = selectTopologyLayoutLayers(devices);
  if (!selection) return 0;
  const layerById = new Map<string, number>();
  const grouped = new Map<number, TopologyRoleLayoutDevice[]>();
  devices.forEach((device, index) => {
    const layer = selection.layers[index];
    if (layer === null || !isFinitePoint(positions[device.id])) return;
    layerById.set(device.id, layer);
    grouped.set(layer, [...(grouped.get(layer) || []), device]);
  });
  const order = new Map<number, string[]>();
  grouped.forEach((rowDevices, layer) => {
    order.set(layer, [...rowDevices].sort((left, right) => (
      positions[left.id].x - positions[right.id].x
      || compareDevices(left, right)
    )).map((device) => device.id));
  });
  return countCrossingsForLayerOrder(order, layerById, collectPhysicalLayoutEdges(links));
};

const buildHorizontalRowPositions = (
  ids: string[],
  width: number,
  height: number,
  y: number,
): Record<string, TopologyRoleLayoutPoint> => {
  const sideInset = Math.min(72, Math.max(48, width * 0.06));
  const availableWidth = Math.max(0, width - sideInset * 2);
  const maxSpacing = Math.max(250, width * 0.28);
  const spacing = ids.length > 1
    ? Math.min(maxSpacing, availableWidth / (ids.length - 1))
    : 0;
  const totalWidth = spacing * Math.max(ids.length - 1, 0);
  const startX = Math.max(sideInset, (width - totalWidth) / 2);
  return Object.fromEntries(ids.map((id, index) => [id, {
    x: clampPosition(startX + index * spacing, 48, Math.max(48, width - 48)),
    // A short viewport must not collapse multiple semantic layers onto the
    // same row. The SVG zoom-to-fit step can scale this virtual height back
    // into the available viewport; clamping here loses the layer separation.
    y: Math.max(56, y),
  }]));
};

/**
 * Build the deterministic role-tier layout used by hierarchy mode. When
 * physical LLDP/CDP links are available, their adjacency orders each row to
 * reduce crossings; the returned null means that this graph has no usable
 * hierarchy signal and should continue through the existing force/chain
 * fallback.
 */
export const buildTopologyRoleLayeredPositions = (
  devices: TopologyRoleLayoutDevice[],
  width: number,
  height: number,
  links: TopologyRoleLayoutLink[] = [],
): Record<string, TopologyRoleLayoutPoint> | null => {
  if (devices.length === 0) return null;
  const selection = selectTopologyLayoutLayers(devices);
  if (!selection) return null;

  const grouped = new Map<number, TopologyRoleLayoutDevice[]>();
  devices.forEach((device, index) => {
    const layer = selection.layers[index];
    if (layer === null) return;
    const current = grouped.get(layer) || [];
    current.push(device);
    grouped.set(layer, current);
  });
  const layerKeys = Array.from(grouped.keys()).sort((left, right) => left - right);
  if (layerKeys.length < 2) return null;

  const positions: Record<string, TopologyRoleLayoutPoint> = {};
  const topInset = Math.min(118, Math.max(88, height * 0.18));
  const bottomInset = Math.min(106, Math.max(82, height * 0.16));
  const layerCount = Math.max(layerKeys.length - 1, 1);
  const availableLayerHeight = Math.max(0, height - topInset - bottomInset);
  const layerGap = Math.min(170, Math.max(82, availableLayerHeight / layerCount));
  const totalLayerHeight = layerGap * Math.max(layerKeys.length - 1, 0);
  const firstLayerY = topInset + Math.max(0, (availableLayerHeight - totalLayerHeight) / 2);
  const orderedRows = orderLayeredRowsByLinks(grouped, devices, selection, links);

  layerKeys.forEach((layer, index) => {
    const rowIds = orderedRows.get(layer) || [];
    Object.assign(
      positions,
      buildHorizontalRowPositions(rowIds, width, height, firstLayerY + layerGap * index),
    );
  });
  return positions;
};

/**
 * Keep manual coordinates when they are valid, but rebuild a complete row if
 * a saved layout has collapsed two nodes or their labels onto each other.
 * Y is always taken from the current structured layout so a role change or a
 * newly imported device cannot inherit a stale layer coordinate.
 */
export const repairTopologyRoleLayeredPositions = (
  devices: TopologyRoleLayoutDevice[],
  structuredPositions: Record<string, TopologyRoleLayoutPoint>,
  preferredPositions: Record<string, Partial<TopologyRoleLayoutPoint>> = {},
  width: number,
  height: number,
  links: TopologyRoleLayoutLink[] = [],
): Record<string, TopologyRoleLayoutPoint> => {
  const repaired: Record<string, TopologyRoleLayoutPoint> = {};
  const rows = new Map<number, TopologyRoleLayoutDevice[]>();

  devices.forEach((device) => {
    const base = structuredPositions[device.id];
    if (!isFinitePoint(base)) return;
    const rowKey = base.y;
    rows.set(rowKey, [...(rows.get(rowKey) || []), device]);
  });

  const structuredDevices = devices.filter((device) => isFinitePoint(structuredPositions[device.id]));
  const hasCompletePreferredPositions = structuredDevices.length > 0 && structuredDevices.every((device) => (
    Number.isFinite(Number(preferredPositions[device.id]?.x))
  ));
  const preferredLayeredPositions = hasCompletePreferredPositions
    ? Object.fromEntries(structuredDevices.map((device) => [device.id, {
      x: Number(preferredPositions[device.id].x),
      y: structuredPositions[device.id].y,
    }]))
    : {};
  const structuredCrossings = countTopologyLayerCrossings(devices, links, structuredPositions);
  const preferredCrossings = hasCompletePreferredPositions
    ? countTopologyLayerCrossings(devices, links, preferredLayeredPositions)
    : Number.POSITIVE_INFINITY;
  // Keep a valid manual layout when it is at least as clear as the generated
  // LLDP order. If old/saved coordinates introduce more crossings, use the
  // relationship-aware order instead of preserving a bad automatic layout.
  const usePreferredPositions = hasCompletePreferredPositions && preferredCrossings <= structuredCrossings;

  rows.forEach((rowDevices, rowKey) => {
    const candidates = rowDevices.map((device) => {
      const base = structuredPositions[device.id];
      const preferred = preferredPositions[device.id];
      const preferredX = usePreferredPositions ? Number(preferred?.x) : Number.NaN;
      return {
        device,
        point: {
          x: Number.isFinite(preferredX) ? preferredX : base.x,
          y: base.y,
        },
      };
    }).sort((left, right) => (
      left.point.x - right.point.x
      || compareDevices(left.device, right.device)
    ));

    const hasCollision = candidates.some((entry, index) => {
      if (index === 0) return false;
      const previous = candidates[index - 1];
      const requiredGap = getNodeHalfExtent(previous.device)
        + getNodeHalfExtent(entry.device)
        + NODE_LABEL_GAP;
      return entry.point.x - previous.point.x < requiredGap;
    });

    if (hasCollision) {
      const rowPositions = buildHorizontalRowPositions(
        candidates.map((entry) => entry.device.id),
        width,
        height,
        rowKey,
      );
      Object.assign(repaired, rowPositions);
      return;
    }

    candidates.forEach(({ device, point }) => {
      repaired[device.id] = {
        x: clampPosition(point.x, 48, Math.max(48, width - 48)),
        y: Math.max(56, rowKey),
      };
    });
  });

  devices.forEach((device) => {
    if (repaired[device.id]) return;
    const base = structuredPositions[device.id];
    if (isFinitePoint(base)) repaired[device.id] = { ...base };
  });
  return repaired;
};
