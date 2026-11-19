import { canonicalTopologyRole, topologyRoleVisualTier } from '../domain/topologyRoles';

export type TopologyRoleLayoutDevice = {
  id: string;
  hostname?: string;
  role?: unknown;
  role_identity?: unknown;
  device_category?: unknown;
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

export type TopologyLayerSource = 'role';

export type TopologyLayerSelection = {
  layers: Array<number | null>;
  source: TopologyLayerSource;
};

const getRoleLayer = (device: TopologyRoleLayoutDevice): number | null => {
  for (const value of [device.role_identity, device.role, device.device_category]) {
    const roleKey = canonicalTopologyRole(value);
    if (!roleKey || roleKey === 'unknown') continue;
    const layer = topologyRoleVisualTier(roleKey);
    if (layer !== null) return layer;
  }
  return null;
};

export const topologyDeviceRole = (device: TopologyRoleLayoutDevice): string => (
  [device.role_identity, device.role, device.device_category]
    .map(canonicalTopologyRole).find((role) => role && role !== 'unknown') || 'unknown'
);

export const isTopologyWirelessController = (device: TopologyRoleLayoutDevice): boolean => (
  topologyDeviceRole(device) === 'wireless_controller'
);

const wirelessMainWidth = (width: number): number => (
  width - (width >= 700 ? Math.min(320, Math.max(240, width * 0.24)) : width * 0.42)
);

export const TOPOLOGY_WIRELESS_CONTROL_HALF_WIDTH = 118;
export const TOPOLOGY_SITE_SIDE_PADDING = 88;

/**
 * Use only explicit device roles for visual hierarchy. Link structure does
 * not create user-facing hierarchy rows.
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

  return null;
};

const clampPosition = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));
const MIN_NODE_CENTER_GAP = 72;
const NODE_LABEL_GAP = 12;
const MAX_NODES_PER_TOPOLOGY_ROW = 6;
const MIN_TOPOLOGY_SUBROW_GAP = 160;
const MIN_WIRED_ACCESS_SUBROW_GAP = 125;
const MAX_TOPOLOGY_NODE_LABEL_WIDTH = 220;
const TOPOLOGY_NODE_LABEL_MARGIN = MAX_TOPOLOGY_NODE_LABEL_WIDTH / 2 + 12;

const normalizeMaxNodesPerRow = (maxNodesPerRow: number): number => (
  Number.isFinite(maxNodesPerRow)
    ? Math.max(1, Math.floor(maxNodesPerRow))
    : MAX_NODES_PER_TOPOLOGY_ROW
);

const estimateTopologyLabelWidth = (value: unknown): number => {
  const text = String(value || '').trim();
  const width = Array.from(text).reduce((total, character) => (
    total + (/^[\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef]$/u.test(character) ? 12 : 7.2)
  ), 0);
  return Math.max(56, Math.min(MAX_TOPOLOGY_NODE_LABEL_WIDTH, Math.ceil(width + 16)));
};

const getTopologyRowLabelMargin = (devices: TopologyRoleLayoutDevice[]): number => (
  devices.length > 0
    ? devices.reduce((largest, device) => Math.max(largest, estimateTopologyLabelWidth(device.hostname) / 2 + NODE_LABEL_GAP), 48)
    : TOPOLOGY_NODE_LABEL_MARGIN
);

const getTopologyRowSideInset = (width: number, labelMargin: number): number => (
  labelMargin > 48
    ? Math.min(width * 0.32, Math.max(72, width * 0.06, labelMargin))
    : Math.min(72, Math.max(48, width * 0.06))
);

const getTopologyRowCapacity = (
  devices: TopologyRoleLayoutDevice[],
  width: number,
  maxNodesPerRow: number,
  labelMargin = getTopologyRowLabelMargin(devices),
  layerGap = MIN_TOPOLOGY_SUBROW_GAP,
): number => {
  const rowCeiling = normalizeMaxNodesPerRow(maxNodesPerRow);
  if (devices.length === 0) return rowCeiling;
  const sideInset = getTopologyRowSideInset(width, labelMargin);
  const availableWidth = Math.max(0, width - sideInset * 2);
  const widestLabel = devices.reduce((largest, device) => Math.max(largest, estimateTopologyLabelWidth(device.hostname)), 56);
  const requiredCenterGap = Math.max(MIN_NODE_CENTER_GAP, widestLabel + NODE_LABEL_GAP);
  const maxCenterGap = Math.max(250, Math.min(width * 0.42, layerGap * 3.2));
  const widthCapacity = requiredCenterGap > maxCenterGap
    ? 1
    : Math.max(1, Math.floor(availableWidth / requiredCenterGap) + 1);
  return Math.min(rowCeiling, widthCapacity);
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

type TopologyLayoutPositionRow = {
  ids: string[];
  compactAccessGap: boolean;
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
  const hasDiscoveryEvidence = sources.some((source) => source === 'LLDP');
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
        const neighborPositions = Array.from(neighbors.get(id) || []).sort()
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
  y: number,
  layerGap: number,
  labelMargin = 48,
): Record<string, TopologyRoleLayoutPoint> => {
  const sideInset = getTopologyRowSideInset(width, labelMargin);
  const availableWidth = Math.max(0, width - sideInset * 2);
  // Relate horizontal row spread to the actual tier separation. Using total
  // canvas height makes four-tier topologies look much wider than they are tall.
  const maxSpacing = Math.max(250, Math.min(width * 0.42, layerGap * 3.2));
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

const splitDenseRoleRow = (
  ids: string[],
  layer: number,
  devicesById: Map<string, TopologyRoleLayoutDevice>,
  layerById: Map<string, number>,
  edges: TopologyLayoutEdge[],
  xById: Map<string, number>,
  groupEveryParent = false,
  maxNodesPerRow = MAX_NODES_PER_TOPOLOGY_ROW,
  groupByParentCombination = false,
): string[][] => {
  if (ids.length === 0) return [];
  if (ids.length <= maxNodesPerRow && !groupEveryParent && !groupByParentCombination) return [ids];

  const originalOrder = new Map(ids.map((id, index) => [id, index]));
  const candidatesByChild = new Map<string, Set<string>>();
  for (const edge of edges) {
    const sourceLayer = layerById.get(edge.sourceId);
    const targetLayer = layerById.get(edge.targetId);
    if (sourceLayer === undefined || targetLayer === undefined || sourceLayer === targetLayer) continue;
    const childId = sourceLayer === layer ? edge.sourceId : targetLayer === layer ? edge.targetId : '';
    const parentId = sourceLayer === layer ? edge.targetId : targetLayer === layer ? edge.sourceId : '';
    const parentLayer = layerById.get(parentId);
    if (!childId || !originalOrder.has(childId) || parentLayer === undefined || parentLayer >= layer) continue;
    const candidates = candidatesByChild.get(childId) || new Set<string>();
    candidates.add(parentId);
    candidatesByChild.set(childId, candidates);
  }

  const childrenByParent = new Map<string, string[]>();
  const parentIdsByGroup = new Map<string, string[]>();
  const parentLoads = new Map<string, number>();
  for (const id of ids) {
    const candidates = Array.from(candidatesByChild.get(id) || []);
    const nearestLayer = candidates.reduce((nearest, parentId) => (
      Math.max(nearest, layerById.get(parentId) ?? Number.NEGATIVE_INFINITY)
    ), Number.NEGATIVE_INFINITY);
    const nearestParents = candidates.filter((parentId) => layerById.get(parentId) === nearestLayer);
    const groupingParents = groupByParentCombination ? candidates : nearestParents;
    nearestParents.sort((left, right) => (
      (parentLoads.get(left) || 0) - (parentLoads.get(right) || 0)
      || (xById.get(left) ?? Number.MAX_SAFE_INTEGER) - (xById.get(right) ?? Number.MAX_SAFE_INTEGER)
      || compareDevices(devicesById.get(left) || { id: left }, devicesById.get(right) || { id: right })
    ));
    const parentId = groupEveryParent || groupByParentCombination
      ? [...groupingParents].sort().join('|') || '__unlinked__'
      : nearestParents[0] || '__unlinked__';
    childrenByParent.set(parentId, [...(childrenByParent.get(parentId) || []), id]);
    if (parentId !== '__unlinked__') {
      parentIdsByGroup.set(parentId, groupByParentCombination || groupEveryParent
        ? [...groupingParents].sort()
        : [parentId]);
    }
    if (parentId !== '__unlinked__') parentLoads.set(parentId, (parentLoads.get(parentId) || 0) + 1);
  }

  const orderedGroups = Array.from(childrenByParent.entries()).sort(([left], [right]) => {
    if (left === '__unlinked__') return 1;
    if (right === '__unlinked__') return -1;
    const leftParents = parentIdsByGroup.get(left) || [left];
    const rightParents = parentIdsByGroup.get(right) || [right];
    const leftX = leftParents.reduce((total, parentId) => total + (xById.get(parentId) ?? Number.MAX_SAFE_INTEGER), 0) / leftParents.length;
    const rightX = rightParents.reduce((total, parentId) => total + (xById.get(parentId) ?? Number.MAX_SAFE_INTEGER), 0) / rightParents.length;
    return leftX - rightX
      || left.localeCompare(right);
  });

  const splitGroup = (children: string[]): string[][] => {
    const orderedChildren = children.sort((left, right) => (originalOrder.get(left) || 0) - (originalOrder.get(right) || 0));
    const rows: string[][] = [];
    for (let offset = 0; offset < orderedChildren.length; offset += maxNodesPerRow) {
      rows.push(orderedChildren.slice(offset, offset + maxNodesPerRow));
    }
    return rows;
  };

  if (groupEveryParent || (maxNodesPerRow <= MAX_NODES_PER_TOPOLOGY_ROW && !groupByParentCombination)) {
    return orderedGroups.flatMap(([, children]) => splitGroup(children));
  }

  const rows: string[][] = [];
  let currentRow: string[] = [];
  const flushCurrentRow = () => {
    if (currentRow.length === 0) return;
    rows.push(currentRow);
    currentRow = [];
  };

  orderedGroups.forEach(([parentId, children]) => {
    const orderedChildren = children.sort((left, right) => (originalOrder.get(left) || 0) - (originalOrder.get(right) || 0));
    if (groupByParentCombination && parentId === '__unlinked__') {
      flushCurrentRow();
      rows.push(...splitGroup(orderedChildren));
      return;
    }
    if (orderedChildren.length <= maxNodesPerRow) {
      if (currentRow.length + orderedChildren.length > maxNodesPerRow) flushCurrentRow();
      currentRow.push(...orderedChildren);
      return;
    }

    flushCurrentRow();
    let offset = 0;
    while (offset + maxNodesPerRow <= orderedChildren.length) {
      rows.push(orderedChildren.slice(offset, offset + maxNodesPerRow));
      offset += maxNodesPerRow;
    }
    currentRow = orderedChildren.slice(offset);
  });

  flushCurrentRow();
  return rows;
};

/**
 * Build the deterministic role-tier layout used by hierarchy mode. When
 * physical LLDP links are available, their adjacency orders each row to
 * reduce crossings; the returned null means that this graph has no usable
 * hierarchy signal and should continue through the existing force/chain
 * fallback. `maxNodesPerRow` is an upper bound; the viewport and estimated
 * label widths can reduce the effective capacity.
 */
export const buildTopologyRoleLayeredPositions = (
  devices: TopologyRoleLayoutDevice[],
  width: number,
  height: number,
  links: TopologyRoleLayoutLink[] = [],
  maxNodesPerRow = MAX_NODES_PER_TOPOLOGY_ROW,
): Record<string, TopologyRoleLayoutPoint> | null => {
  if (devices.length === 0) return null;
  const rowCapacityCeiling = normalizeMaxNodesPerRow(maxNodesPerRow);
  const controllers = devices.filter(isTopologyWirelessController).sort(compareDevices);
  const mainDevices = devices.filter((device) => !isTopologyWirelessController(device));
  if (controllers.length > 0 && mainDevices.length > 0) {
    const mainWidth = wirelessMainWidth(width);
    const fallbackPositions: Record<string, TopologyRoleLayoutPoint> = {};
    const orderedMain = [...mainDevices].sort(compareDevices);
    const fallbackCapacity = getTopologyRowCapacity(orderedMain, mainWidth, rowCapacityCeiling);
    for (let offset = 0; offset < orderedMain.length; offset += fallbackCapacity) {
      Object.assign(fallbackPositions, buildHorizontalRowPositions(
        orderedMain.slice(offset, offset + fallbackCapacity).map((device) => device.id),
        mainWidth, 120 + (offset / fallbackCapacity) * MIN_TOPOLOGY_SUBROW_GAP,
        MIN_TOPOLOGY_SUBROW_GAP, getTopologyRowLabelMargin(orderedMain.slice(offset, offset + fallbackCapacity)),
      ));
    }
    const mainPositions = buildTopologyRoleLayeredPositions(mainDevices, mainWidth, height, links, rowCapacityCeiling) || fallbackPositions;
    const wiredRight = Math.max(...Object.values(mainPositions).map((point) => point.x));
    // Match the left site padding when placing the control band beside a sparse wired layout.
    const controllerX = Math.min(
      mainWidth + (width - mainWidth) / 2,
      wiredRight + TOPOLOGY_SITE_SIDE_PADDING + TOPOLOGY_WIRELESS_CONTROL_HALF_WIDTH,
    );
    const edges = collectPhysicalLayoutEdges(links);
    const positions = { ...mainPositions };
    const occupied: number[] = [];
    for (const controller of controllers) {
      const neighbors = edges.flatMap((edge) => (
        edge.sourceId === controller.id ? [edge.targetId] : edge.targetId === controller.id ? [edge.sourceId] : []
      )).filter((id) => mainPositions[id]);
      let y = neighbors.length > 0
        ? neighbors.reduce((total, id) => total + mainPositions[id].y, 0) / neighbors.length
        : Math.min(...Object.values(mainPositions).map((point) => point.y));
      while (occupied.some((otherY) => Math.abs(otherY - y) < MIN_TOPOLOGY_SUBROW_GAP)) y += MIN_TOPOLOGY_SUBROW_GAP;
      occupied.push(y);
      positions[controller.id] = { x: controllerX, y };
    }
    return positions;
  }
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
  const orderedRows = orderLayeredRowsByLinks(grouped, devices, selection, links);
  const deviceById = new Map(devices.map((device) => [device.id, device]));
  const layerById = new Map<string, number>();
  devices.forEach((device, index) => {
    const layer = selection.layers[index];
    if (layer !== null) layerById.set(device.id, layer);
  });
  const edges = collectPhysicalLayoutEdges(links)
    .filter((edge) => deviceById.has(edge.sourceId) && deviceById.has(edge.targetId));
  const xById = new Map<string, number>();
  for (const layer of layerKeys) {
    const ordered = orderedRows.get(layer) || [];
    ordered.forEach((id, index) => {
      xById.set(id, ((index + 0.5) / Math.max(ordered.length, 1)) * width);
    });
  }
  const rowsByLayer = new Map<number, TopologyLayoutPositionRow[]>();
  for (const layer of layerKeys) {
    const ids = orderedRows.get(layer) || [];
    const apIds = ids.filter((id) => topologyDeviceRole(deviceById.get(id)!) === 'wireless_ap');
    const otherIds = ids.filter((id) => !apIds.includes(id));
    const otherDevices = otherIds.map((id) => deviceById.get(id)!).filter(Boolean);
    const apDevices = apIds.map((id) => deviceById.get(id)!).filter(Boolean);
    const otherRoles = otherDevices.map(topologyDeviceRole);
    const shouldGroupAccessByUplink = otherRoles.includes('access')
      && otherRoles.every((role) => role === 'access' || role === 'switch');
    const otherRows = splitDenseRoleRow(
      otherIds, layer, deviceById, layerById, edges, xById, false,
      getTopologyRowCapacity(otherDevices, width, rowCapacityCeiling, getTopologyRowLabelMargin(otherDevices), layerGap),
      shouldGroupAccessByUplink,
    );
    const apRows = splitDenseRoleRow(
      apIds, layer, deviceById, layerById, edges, xById, true,
      getTopologyRowCapacity(apDevices, width, rowCapacityCeiling, getTopologyRowLabelMargin(apDevices), layerGap),
    );
    const rows = [
      ...otherRows.map((ids) => ({ ids, compactAccessGap: shouldGroupAccessByUplink })),
      ...apRows.map((ids) => ({ ids, compactAccessGap: false })),
    ];
    rowsByLayer.set(layer, rows);
  }
  const rowGap = Math.max(layerGap, MIN_TOPOLOGY_SUBROW_GAP);
  const rowSequence = layerKeys.flatMap((layer) => (
    (rowsByLayer.get(layer) || []).map((row) => ({ layer, ...row }))
  ));
  const rowGaps = rowSequence.slice(1).map((row, index) => {
    const previous = rowSequence[index];
    return row.layer === previous.layer && row.compactAccessGap && previous.compactAccessGap
      ? MIN_WIRED_ACCESS_SUBROW_GAP
      : rowGap;
  });
  const totalLayoutHeight = rowGaps.reduce((total, gap) => total + gap, 0);
  const firstRowY = topInset + Math.max(0, (availableLayerHeight - totalLayoutHeight) / 2);
  let rowY = firstRowY;
  rowSequence.forEach((row, index) => {
    if (index > 0) rowY += rowGaps[index - 1];
    const rowPositions = buildHorizontalRowPositions(
      row.ids,
      width,
      rowY,
      layerGap,
      getTopologyRowLabelMargin(row.ids.map((id) => deviceById.get(id)!).filter(Boolean)),
    );
    Object.assign(positions, rowPositions);
    for (const [id, point] of Object.entries(rowPositions)) xById.set(id, point.x);
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
  const controllers = devices.filter(isTopologyWirelessController);
  const mainDevices = devices.filter((device) => !isTopologyWirelessController(device));
  if (controllers.length > 0 && mainDevices.length > 0) {
    const repaired = repairTopologyRoleLayeredPositions(
      mainDevices, structuredPositions, preferredPositions, wirelessMainWidth(width), height, links,
    );
    for (const controller of controllers) {
      if (structuredPositions[controller.id]) repaired[controller.id] = { ...structuredPositions[controller.id] };
    }
    return repaired;
  }
  const repaired: Record<string, TopologyRoleLayoutPoint> = {};
  const rows = new Map<number, TopologyRoleLayoutDevice[]>();

  devices.forEach((device) => {
    const base = structuredPositions[device.id];
    if (!isFinitePoint(base)) return;
    const rowKey = base.y;
    rows.set(rowKey, [...(rows.get(rowKey) || []), device]);
  });
  const rowKeys = Array.from(rows.keys()).sort((left, right) => left - right);
  const observedLayerGaps = rowKeys.slice(1)
    .map((rowKey, index) => rowKey - rowKeys[index])
    .filter((gap) => gap > 0);
  const layerGap = observedLayerGaps.length > 0
    ? Math.min(...observedLayerGaps)
    : Math.min(170, Math.max(82, height * 0.22));

  const structuredDevices = devices.filter((device) => isFinitePoint(structuredPositions[device.id]));
  const hasCompletePreferredPositions = structuredDevices.length > 0 && structuredDevices.every((device) => (
    Number.isFinite(Number(preferredPositions[device.id]?.x))
    && Number(preferredPositions[device.id]?.x) >= 48
    && Number(preferredPositions[device.id]?.x) <= width - 48
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
        rowKey,
        layerGap,
        MAX_TOPOLOGY_NODE_LABEL_WIDTH / 2 + 12,
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
