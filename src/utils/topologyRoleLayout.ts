import { topologyRoleVisualTier } from '../domain/topologyRoles';

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
  for (const value of [device.role, device.role_identity, device.device_category]) {
    const layer = topologyRoleVisualTier(value);
    if (layer !== null) return layer;
  }
  return null;
};

/**
 * Select the layer source without changing the graph's semantic rank data.
 * Directed relation ranks remain authoritative when they describe more than
 * one layer; role tiers fill the gap for ordinary undirected physical links.
 */
export const selectTopologyLayoutLayers = (
  devices: TopologyRoleLayoutDevice[],
): TopologyLayerSelection | null => {
  const evidenceLayers = devices.map(getEvidenceLayer);
  const evidenceValues = evidenceLayers.filter((layer): layer is number => layer !== null);
  const evidenceDistinct = new Set(evidenceValues);
  if (evidenceValues.some((layer) => layer > 0) && evidenceDistinct.size > 1) {
    return { layers: evidenceLayers, source: 'evidence' };
  }

  const roleLayers = devices.map(getRoleLayer);
  const roleValues = roleLayers.filter((layer): layer is number => layer !== null);
  if (roleValues.length > 0 && new Set(roleValues).size > 1) {
    const fallbackLayer = Math.max(...roleValues);
    return {
      layers: roleLayers.map((layer) => layer ?? fallbackLayer),
      source: 'role',
    };
  }
  return null;
};

const clampPosition = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));

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
  const maxSpacing = Math.max(250, width * 0.28);
  const spacing = ids.length > 1
    ? Math.min(maxSpacing, Math.max(120, (width * 0.88) / (ids.length - 1)))
    : 0;
  const totalWidth = spacing * Math.max(ids.length - 1, 0);
  const startX = Math.max(48, (width - totalWidth) / 2);
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
