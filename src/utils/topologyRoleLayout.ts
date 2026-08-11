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
    const fallbackLayer = Math.max(...roleValues);
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
    y: clampPosition(y, 56, Math.max(56, height - 56)),
  }]));
};

/**
 * Build the deterministic top-to-bottom layout used by the hierarchy mode.
 * The returned null means that this graph has no usable hierarchy signal and
 * should continue through the existing force/chain fallback.
 */
export const buildTopologyRoleLayeredPositions = (
  devices: TopologyRoleLayoutDevice[],
  width: number,
  height: number,
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

  layerKeys.forEach((layer, index) => {
    const rowIds = (grouped.get(layer) || [])
      .sort(compareDevices)
      .map((device) => device.id);
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
): Record<string, TopologyRoleLayoutPoint> => {
  const repaired: Record<string, TopologyRoleLayoutPoint> = {};
  const rows = new Map<number, TopologyRoleLayoutDevice[]>();

  devices.forEach((device) => {
    const base = structuredPositions[device.id];
    if (!isFinitePoint(base)) return;
    const rowKey = base.y;
    rows.set(rowKey, [...(rows.get(rowKey) || []), device]);
  });

  rows.forEach((rowDevices, rowKey) => {
    const candidates = rowDevices.map((device) => {
      const base = structuredPositions[device.id];
      const preferred = preferredPositions[device.id];
      const preferredX = Number(preferred?.x);
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
        y: clampPosition(rowKey, 56, Math.max(56, height - 56)),
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
