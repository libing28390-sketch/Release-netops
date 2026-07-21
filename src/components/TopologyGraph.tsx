import React, { useEffect, useMemo, useRef, useState } from 'react';
import * as d3 from 'd3';
import {
  aggregateTopologyGraph,
  type TopologyDrillSegment,
  type TopologyHierarchyLevel,
  resolveTopologyDisplayMode,
  type TopologyDisplayMode,
} from '../utils/topologyAggregation';

const topologyIconAssets = import.meta.glob('../assets/topology/devices/**/*.svg', {
  eager: true,
  import: 'default',
  query: '?url',
}) as Record<string, string>;

interface Device {
  id: string;
  hostname: string;
  ip_address: string;
  status: string;
  role: string;
  platform?: string;
  model?: string;
  vendor?: string;
  cpu_usage?: number;
  memory_usage?: number;
  uptime?: string;
  site?: string;
  site_id?: string;
  site_country?: string;
  site_state_province?: string;
  site_city?: string;
  site_district?: string;
  region?: string;
  floor?: string;
  rack_id?: string;
  rack?: string;
  rack_code?: string;
  rack_name?: string;
  rack_floor?: string;
  rack_room?: string;
  rack_row?: string;
  health_status?: string;
  open_alert_count?: number;
  critical_open_alerts?: number;
  is_unmanaged?: boolean;
  is_group?: boolean;
  group_id?: string;
  group_label?: string;
  group_site?: string;
  group_layer?: string;
  group_member_count?: number;
  group_online_count?: number;
  group_offline_count?: number;
  group_warning_count?: number;
  group_alert_count?: number;
  group_member_ids?: string[];
  group_level?: TopologyHierarchyLevel;
  group_path?: TopologyDrillSegment[];
  group_can_drill?: boolean;
}

interface Link {
  id?: string;
  link_key?: string;
  source_device_id: string;
  target_device_id: string;
  source?: any;
  target?: any;
  source_port?: string;
  target_port?: string;
  inferred?: boolean;
  source_hostname?: string;
  target_hostname?: string;
  source_port_normalized?: string;
  target_port_normalized?: string;
  discovery_source?: string;
  operational_state?: 'up' | 'degraded' | 'down' | 'stale' | 'unknown';
  bandwidth_mbps?: number | null;
  link_kind?: 'physical' | 'aggregation' | string;
  source_aggregation_name?: string;
  target_aggregation_name?: string;
  aggregation_protocol?: string;
  member_count?: number;
  active_member_count?: number;
  aggregation_bandwidth_mbps?: number | null;
  members?: Array<Record<string, unknown>>;
  evidence_count?: number;
  is_unmanaged?: boolean;
  group_link?: boolean;
  grouped_link_count?: number;
}

type BandwidthTierKey = '10m' | '100m' | '1g' | '10g' | '40g' | '80g' | '100g' | '200g' | 'unknown';

type BandwidthTier = {
  key: BandwidthTierKey;
  label: string;
  color: string;
  mutedColor: string;
  width: number;
};

const BANDWIDTH_TIERS: BandwidthTier[] = [
  { key: '10m', label: '10M', color: '#f97316', mutedColor: 'rgba(249,115,22,0.30)', width: 2.1 },
  { key: '100m', label: '100M', color: '#eab308', mutedColor: 'rgba(234,179,8,0.30)', width: 2.3 },
  { key: '1g', label: '1G', color: '#22c55e', mutedColor: 'rgba(34,197,94,0.30)', width: 2.5 },
  { key: '10g', label: '10G', color: '#0ea5e9', mutedColor: 'rgba(14,165,233,0.30)', width: 2.9 },
  { key: '40g', label: '40G', color: '#8b5cf6', mutedColor: 'rgba(139,92,246,0.30)', width: 3.4 },
  { key: '80g', label: '80G', color: '#ec4899', mutedColor: 'rgba(236,72,153,0.30)', width: 3.8 },
  { key: '100g', label: '100G', color: '#db2777', mutedColor: 'rgba(219,39,119,0.30)', width: 4.2 },
  { key: '200g', label: '200G+', color: '#4338ca', mutedColor: 'rgba(67,56,202,0.30)', width: 4.7 },
  { key: 'unknown', label: '未知', color: '#64748b', mutedColor: 'rgba(100,116,139,0.28)', width: 1.8 },
];

const getBandwidthTier = (bandwidthMbps?: number | null): BandwidthTier => {
  const speed = Number(bandwidthMbps);
  if (!Number.isFinite(speed) || speed <= 0) return BANDWIDTH_TIERS[8];
  if (speed >= 200_000) return BANDWIDTH_TIERS[7];
  if (speed >= 100_000) return BANDWIDTH_TIERS[6];
  if (speed >= 80_000) return BANDWIDTH_TIERS[5];
  if (speed >= 40_000) return BANDWIDTH_TIERS[4];
  if (speed >= 10_000) return BANDWIDTH_TIERS[3];
  if (speed >= 1_000) return BANDWIDTH_TIERS[2];
  if (speed >= 100) return BANDWIDTH_TIERS[1];
  return BANDWIDTH_TIERS[0];
};

interface TopologyGraphProps {
  devices: Device[];
  links: Link[];
  onNodeClick?: (device: Device) => void;
  onOpenWorkspace?: (device: Device) => void;
  selectedNodeId?: string | null;
  selectedLinkKey?: string | null;
  onLinkClick?: (link: Link) => void;
}

const getFullInterfaceLabel = (value?: string) => String(value || '').replace(/\s+interface\s*$/i, '').trim();

const getLinkEndpointLabel = (item: any, side: 'source' | 'target') => {
  if (side === 'source' && item?.source_is_group) return '';
  if (side === 'target' && item?.target_is_group) return '';
  if (String(item?.link_kind || '').toLowerCase() === 'aggregation') {
    const aggregationName = side === 'source' ? item.source_aggregation_name : item.target_aggregation_name;
    if (aggregationName) return getFullInterfaceLabel(aggregationName);
  }
  return getFullInterfaceLabel(side === 'source'
    ? item?.source_port || item?.source_port_normalized
    : item?.target_port || item?.target_port_normalized);
};

const getLinkEndpointShortLabel = (item: any, side: 'source' | 'target') =>
  abbreviateInterface(getLinkEndpointLabel(item, side));

const abbreviateInterface = (value?: string) => {
  const raw = getFullInterfaceLabel(value);
  if (!raw) return '';
  const compact = raw.replace(/\s+/g, '');
  if (/^GigabitEthernet/i.test(compact)) return `GE${compact.slice('GigabitEthernet'.length)}`;
  if (/^TenGigabitEthernet/i.test(compact)) return `Te${compact.slice('TenGigabitEthernet'.length)}`;
  if (/^FortyGigabitEthernet/i.test(compact)) return `Fo${compact.slice('FortyGigabitEthernet'.length)}`;
  if (/^HundredGigabitEthernet/i.test(compact)) return `Hu${compact.slice('HundredGigabitEthernet'.length)}`;
  if (/^FastEthernet/i.test(compact)) return `Fa${compact.slice('FastEthernet'.length)}`;
  if (/^Ethernet/i.test(compact)) return `Et${compact.slice('Ethernet'.length)}`;
  // Keep the device-native vendor prefix while shortening verbose forms for
  // the canvas. The full raw value is attached as a hover title below.
  return compact;
};

const normalizeGraphInterface = (value?: string) => {
  const raw = String(value || '')
    .trim()
    .toLowerCase()
    .replace(/\binterface\b/g, '')
    .replace(/\s+/g, '')
    .replace(/interface$/, '');
  if (!raw) return '';
  if (/^et\d/.test(raw)) return `eth${raw.slice(2)}`;
  if (/^e\d/.test(raw)) return `eth${raw.slice(1)}`;
  if (/^ge\d/.test(raw)) return `gi${raw.slice(2)}`;
  if (raw.startsWith('gigabitethernet')) return `gi${raw.slice('gigabitethernet'.length)}`;
  if (raw.startsWith('ethernet')) return `eth${raw.slice('ethernet'.length)}`;
  return raw;
};

type DeviceGlyphKind = 'switch' | 'firewall' | 'router' | 'server' | 'wireless' | 'generic';
type TopologyLayoutMode = 'hierarchy' | 'horizontal' | 'force' | 'radial';

const getLayerTone = (device: Device) => {
  if (device.is_group) {
    const groupLayer = String(device.group_layer || device.group_label || '').toUpperCase();
    if (groupLayer === 'CORE') return { color: '#1e40af', soft: 'rgba(30,64,175,0.16)', label: 'CORE' };
    if (groupLayer === 'AGGREGATION') return { color: '#1d4ed8', soft: 'rgba(29,78,216,0.14)', label: 'AGGREGATION' };
    if (groupLayer === 'ACCESS') return { color: '#075985', soft: 'rgba(7,89,133,0.14)', label: 'ACCESS' };
    return { color: '#475569', soft: 'rgba(71,85,105,0.12)', label: 'GROUP' };
  }
  const layer = getDeviceTopologyLayer(device);
  if (layer === 0) return { color: '#1e40af', soft: 'rgba(30,64,175,0.16)', label: 'CORE' };
  if (layer === 1) return { color: '#1d4ed8', soft: 'rgba(29,78,216,0.14)', label: 'AGGREGATION' };
  if (layer === 2) return { color: '#075985', soft: 'rgba(7,89,133,0.14)', label: 'ACCESS' };
  const kind = getDeviceGlyphKind(device);
  if (kind === 'firewall') return { color: '#b91c1c', soft: 'rgba(185,28,28,0.14)', label: 'FIREWALL' };
  if (kind === 'router') return { color: '#c2410c', soft: 'rgba(194,65,12,0.14)', label: 'ROUTER' };
  if (kind === 'server') return { color: '#15803d', soft: 'rgba(21,128,61,0.14)', label: 'SERVER' };
  return { color: '#475569', soft: 'rgba(71,85,105,0.12)', label: 'DEVICE' };
};

type LayerSummary = {
  label: string;
  color: string;
  count: number;
};

const buildLayerSummary = (devices: Device[]): LayerSummary[] => {
  const summary = new Map<string, LayerSummary>();
  devices.forEach((device) => {
    const tone = getLayerTone(device);
    const current = summary.get(tone.label);
    if (current) {
      current.count += device.is_group ? Math.max(1, Number(device.group_member_count || 0)) : 1;
    } else {
      summary.set(tone.label, {
        label: tone.label,
        color: tone.color,
        count: device.is_group ? Math.max(1, Number(device.group_member_count || 0)) : 1,
      });
    }
  });
  const order = ['CORE', 'AGGREGATION', 'ROUTER', 'FIREWALL', 'ACCESS', 'SERVER', 'DEVICE'];
  return Array.from(summary.values()).sort((left, right) => {
    const leftIndex = order.indexOf(left.label);
    const rightIndex = order.indexOf(right.label);
    return (leftIndex < 0 ? order.length : leftIndex) - (rightIndex < 0 ? order.length : rightIndex);
  });
};

const formatLayerSummary = (devices: Device[]) =>
  buildLayerSummary(devices).map((item) => `${item.label} ${item.count}`).join(' / ');

const getDeviceGlyphKind = (device: Device): DeviceGlyphKind => {
  if (device.is_group) return 'generic';
  const fingerprint = [device.role, device.hostname, device.platform, device.model]
    .map((value) => String(value || '').toLowerCase())
    .join(' ');

  if (/(firewall| fortigate|forti|palo|pan-|checkpoint|srx|asa|ftd|fw\b)/.test(fingerprint)) return 'firewall';
  if (/(router|gateway|wan|edge router|isr|asr|mx\b)/.test(fingerprint)) return 'router';
  if (/(switch|core|distribution|access|leaf|spine|nexus|catalyst)/.test(fingerprint)) return 'switch';
  if (/(server|compute|hypervisor|vmware|esxi|linux|windows server|unix)/.test(fingerprint)) return 'server';
  if (/(wireless|wi-fi|wifi|access point|\bap\b|wlc|aironet|aruba|unifi)/.test(fingerprint)) return 'wireless';
  return 'generic';
};

const iconCategoryByKind: Record<Exclude<DeviceGlyphKind, 'generic'>, string> = {
  switch: 'switches',
  router: 'routers',
  firewall: 'firewalls',
  server: 'servers',
  wireless: 'wireless',
};

const preferredIconNames: Record<Exclude<DeviceGlyphKind, 'generic'>, string[]> = {
  switch: ['switch.svg', 'cisco-switch-l3-480x480.svg', 'cisco-switch-l3-240x240.svg', 'cisco-switch-l3-144x144.svg'],
  router: ['router.svg'],
  firewall: ['firewall.svg'],
  server: ['server.svg', 'server-linux.svg', 'server-windows.svg'],
  wireless: ['wireless.svg', 'access-point.svg', 'wifi-ap.svg'],
};

const getDeviceIconUrl = (kind: DeviceGlyphKind) => {
  if (kind === 'generic') return undefined;
  const category = iconCategoryByKind[kind];
  const candidates = Object.entries(topologyIconAssets)
    .filter(([path]) => path.includes(`/devices/${category}/`));
  for (const preferredName of preferredIconNames[kind]) {
    const match = candidates.find(([path]) => path.endsWith(`/${preferredName}`));
    if (match) return match[1];
  }
  return candidates[0]?.[1];
};

const hasDeviceIconAsset = (device: Device) => Boolean(getDeviceIconUrl(getDeviceGlyphKind(device)));

const deviceIconSize: Record<Exclude<DeviceGlyphKind, 'generic'>, { width: number; height: number }> = {
  switch: { width: 58, height: 58 },
  router: { width: 58, height: 58 },
  firewall: { width: 50, height: 60 },
  server: { width: 58, height: 58 },
  wireless: { width: 58, height: 58 },
};

const appendDeviceGlyph = (selection: d3.Selection<SVGGElement, any, any, any>, device: Device) => {
  const glyphKind = getDeviceGlyphKind(device);
  selection
    .attr('shape-rendering', 'geometricPrecision')
    .attr('pointer-events', 'none');
  if (glyphKind === 'generic') return;

  const iconUrl = getDeviceIconUrl(glyphKind);
  if (!iconUrl) return;
  const size = deviceIconSize[glyphKind];
  selection.append('image')
    .attr('href', iconUrl)
    .attr('x', -size.width / 2)
    .attr('y', -size.height / 2)
    .attr('width', size.width)
    .attr('height', size.height)
    .attr('preserveAspectRatio', 'xMidYMid meet')
    .attr('pointer-events', 'none');
};

const shouldRenderDeviceGlyph = (device: Device) => hasDeviceIconAsset(device);

const getSiteKey = (site?: string) => {
  const normalizedSite = String(site || '').trim();
  return normalizedSite || 'Unassigned';
};

const getNodeTone = (device: Device) => {
  if (device.is_unmanaged) {
    return { fill: '#94a3b8', stroke: '#64748b', halo: 'rgba(148,163,184,0.18)' };
  }
  if (device.status === 'offline') {
    return { fill: '#ef4444', stroke: '#b91c1c', halo: 'rgba(239,68,68,0.18)' };
  }
  if (device.health_status === 'critical' || (device.critical_open_alerts || 0) > 0) {
    return { fill: '#f97316', stroke: '#c2410c', halo: 'rgba(249,115,22,0.18)' };
  }
  if (device.health_status === 'warning' || (device.open_alert_count || 0) > 0 || device.status === 'pending') {
    return { fill: '#f59e0b', stroke: '#b45309', halo: 'rgba(245,158,11,0.18)' };
  }
  return { fill: '#10b981', stroke: '#047857', halo: 'rgba(16,185,129,0.16)' };
};

const getDeviceStatusColor = (device: Device): string => {
  if (device.status === 'offline') return '#ef4444'; // Red / Down
  if (device.health_status === 'critical' || (device.critical_open_alerts || 0) > 0) return '#f97316'; // Orange / Warning
  if (device.health_status === 'warning' || (device.open_alert_count || 0) > 0 || device.status === 'pending') return '#f59e0b'; // Yellow / Warning
  if (device.is_unmanaged || device.status === 'unknown') return '#94a3b8'; // Grey / Unknown
  return '#10b981'; // Green / Online
};

const buildSiteAnchors = (devices: Device[], width: number) => {
  const siteMap = new Map<string, { key: string; label: string; count: number }>();

  devices.forEach((device) => {
    const key = getSiteKey(device.site_id || device.site);
    const current = siteMap.get(key);
    if (current) {
      current.count += device.is_group ? Math.max(1, Number(device.group_member_count || 0)) : 1;
      return;
    }
    siteMap.set(key, {
      key,
      label: String(device.site || '').trim() || 'Unassigned',
      count: device.is_group ? Math.max(1, Number(device.group_member_count || 0)) : 1,
    });
  });

  const sites = Array.from(siteMap.values()).sort((left, right) => {
    if (left.key === 'Unassigned') return 1;
    if (right.key === 'Unassigned') return -1;
    return left.label.localeCompare(right.label);
  });

  const margin = Math.min(110, width * 0.12);
  const usableWidth = Math.max(width - margin * 2, 0);
  const anchors = sites.map((site, index) => {
    const x = sites.length <= 1
      ? width / 2
      : margin + (usableWidth * index) / Math.max(sites.length - 1, 1);
    return {
      ...site,
      x,
    };
  });

  return anchors;
};

const buildSeedPositions = (devices: Device[], width: number, height: number) => {
  const positions: Record<string, { x: number; y: number }> = {};
  const siteAnchors = buildSiteAnchors(devices, width);
  const siteAnchorMap = new Map(siteAnchors.map((site) => [site.key, site]));

  const groupedBySite = new Map<string, Device[]>();
  devices.forEach((device) => {
    const siteKey = getSiteKey(device.site_id || device.site);
    if (!groupedBySite.has(siteKey)) groupedBySite.set(siteKey, []);
    groupedBySite.get(siteKey)?.push(device);
  });

  Array.from(groupedBySite.entries()).forEach(([siteKey, siteDevices]) => {
    const anchorX = siteAnchorMap.get(siteKey)?.x ?? width / 2;
    const columns = Math.max(1, Math.ceil(Math.sqrt(siteDevices.length)));
    const rows = Math.max(1, Math.ceil(siteDevices.length / columns));
    const spacing = Math.min(82, Math.max(54, width / Math.max(devices.length, 8)));
    siteDevices.forEach((device, index) => {
      const column = index % columns;
      const row = Math.floor(index / columns);
      positions[device.id] = {
        x: anchorX + (column - (columns - 1) / 2) * spacing,
        y: height * 0.52 + (row - (rows - 1) / 2) * spacing,
      };
    });
  });

  return { positions, siteAnchors };
};

type LayoutNode = Device & { x: number; y: number };

const buildGraphLinks = (nodes: LayoutNode[], links: Link[]) => {
  const nodeMap = new Map(nodes.map((node) => [node.id, node]));
  const seen = new Set<string>();
  const pairKey = (link: Link) => [String(link.source_device_id || ''), String(link.target_device_id || '')].sort().join('::');
  const lldpPairs = new Set(
    links
      .filter((link) => String(link.discovery_source || '').toLowerCase().split('+').includes('lldp'))
      .map(pairKey),
  );

  return links
    .filter((link) => {
      const protocols = String(link.discovery_source || '').toLowerCase().split('+').filter(Boolean);
      const isCdpOnly = protocols.includes('cdp') && !protocols.includes('lldp');
      return !(isCdpOnly && lldpPairs.has(pairKey(link)));
    })
    .map((link) => ({
      ...link,
      source: nodeMap.get(link.source_device_id),
      target: nodeMap.get(link.target_device_id),
    }))
    .filter((link) => link.source && link.target)
    .filter((link) => {
      const pair = [String(link.source_device_id || ''), String(link.target_device_id || '')].sort().join('::');
      const portKey = [
        normalizeGraphInterface(link.source_port || link.source_port_normalized),
        normalizeGraphInterface(link.target_port || link.target_port_normalized),
      ].sort().join('::');
      const key = `${pair}::${portKey}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
};

/**
 * Return a deterministic order for a real point-to-point chain.  Force layouts
 * are useful for branches and meshes, but they make a simple switch chain look
 * random on every refresh.  Only use this path when the managed graph is one
 * connected path (two endpoints, no node degree above two).
 */
const getLinearChainOrder = (devices: Device[], links: Link[]) => {
  if (devices.length < 2) return null;

  const nodeById = new Map(devices.map((device) => [device.id, device]));
  const graphNodes: LayoutNode[] = devices.map((device) => ({ ...device, x: 0, y: 0 }));
  const graphLinks = buildGraphLinks(graphNodes, links)
    .filter((link: any) => link.source_device_id !== link.target_device_id);
  const uniquePairLinks = new Map<string, any>();
  graphLinks.forEach((link: any) => {
    const pair = [String(link.source_device_id), String(link.target_device_id)].sort().join('::');
    if (!uniquePairLinks.has(pair)) uniquePairLinks.set(pair, link);
  });
  if (uniquePairLinks.size !== devices.length - 1) return null;

  const adjacency = new Map<string, Set<string>>();
  devices.forEach((device) => adjacency.set(device.id, new Set<string>()));
  uniquePairLinks.forEach((link: any) => {
    adjacency.get(link.source_device_id)?.add(link.target_device_id);
    adjacency.get(link.target_device_id)?.add(link.source_device_id);
  });
  if (Array.from(adjacency.values()).some((neighbors) => neighbors.size > 2)) return null;

  const sortIds = (left: string, right: string) => {
    const leftDevice = nodeById.get(left);
    const rightDevice = nodeById.get(right);
    return String(leftDevice?.hostname || left).localeCompare(String(rightDevice?.hostname || right));
  };
  const endpoints = Array.from(adjacency.entries())
    .filter(([, neighbors]) => neighbors.size === 1)
    .map(([id]) => id)
    .sort(sortIds);
  if (endpoints.length !== 2) return null;

  const order: string[] = [];
  const visited = new Set<string>();
  let previous: string | null = null;
  let current: string | null = endpoints[0];
  while (current && !visited.has(current)) {
    order.push(current);
    visited.add(current);
    const next = Array.from(adjacency.get(current) || [])
      .filter((candidate) => candidate !== previous && !visited.has(candidate))
      .sort(sortIds)[0];
    previous = current;
    current = next || null;
  }
  return order.length === devices.length ? order : null;
};

const buildHorizontalRowPositions = (ids: string[], width: number, height: number, yFraction = 0.42) => {
  const maxSpacing = Math.max(250, width * 0.28);
  const spacing = ids.length > 1
    ? Math.min(maxSpacing, Math.max(120, (width * 0.88) / (ids.length - 1)))
    : 0;
  const totalWidth = spacing * Math.max(ids.length - 1, 0);
  const startX = Math.max(48, (width - totalWidth) / 2);
  const y = clampPosition(height * yFraction, 56, Math.max(56, height - 56));
  return Object.fromEntries(ids.map((id, index) => [id, {
    x: clampPosition(startX + index * spacing, 48, Math.max(48, width - 48)),
    y,
  }]));
};

const getDeviceTopologyLayer = (device: Device): number | null => {
  const fingerprint = [device.role, device.hostname, device.model]
    .map((value) => String(value || '').toLowerCase())
    .join(' ');
  if (/(core|核心|backbone|骨干)/.test(fingerprint)) return 0;
  if (/(distribution|aggregation|汇聚|分布)/.test(fingerprint)) return 1;
  if (/(access|接入|edge|acc[-_ ]?sw)/.test(fingerprint)) return 2;
  return null;
};

const buildLayeredPositions = (devices: Device[], links: Link[], width: number, height: number) => {
  if (devices.length === 0) return null;
  const layers = devices.map(getDeviceTopologyLayer);
  const hasExplicitLayers = layers.some((layer) => layer != null);
  if (!hasExplicitLayers && !devices.every((device) => getDeviceGlyphKind(device) === 'switch')) return null;
  if (!hasExplicitLayers || new Set(layers).size === 1) {
    const chainOrder = getLinearChainOrder(devices, links);
    const orderedIds = chainOrder || [...devices]
      .sort((left, right) => left.hostname.localeCompare(right.hostname))
      .map((device) => device.id);
    return buildHorizontalRowPositions(orderedIds, width, height);
  }

  const fallbackLayer = Math.max(...layers.filter((layer): layer is number => layer != null), 1);
  const grouped = new Map<number, Device[]>();
  devices.forEach((device, index) => {
    const layer = layers[index] ?? fallbackLayer;
    if (!grouped.has(layer)) grouped.set(layer, []);
    grouped.get(layer)?.push(device);
  });
  const layerKeys = Array.from(grouped.keys()).sort((left, right) => left - right);
  const positions: Record<string, { x: number; y: number }> = {};
  layerKeys.forEach((layer, index) => {
    const rowDevices = grouped.get(layer) || [];
    const rowIds = rowDevices
      .sort((left, right) => left.hostname.localeCompare(right.hostname))
      .map((device) => device.id);
    const rowPositions = buildHorizontalRowPositions(
      rowIds,
      width,
      height,
      layerKeys.length === 1 ? 0.42 : 0.30 + (0.42 * index) / Math.max(layerKeys.length - 1, 1),
    );
    Object.assign(positions, rowPositions);
  });
  return positions;
};

const buildLinearPositions = (devices: Device[], links: Link[], width: number, height: number) => {
  const order = getLinearChainOrder(devices, links);
  if (!order) return null;
  return buildHorizontalRowPositions(order, width, height);
};

const buildRadialPositions = (devices: Device[], width: number, height: number) => {
  if (devices.length === 0) return null;
  const centerX = width / 2;
  const centerY = height / 2;
  const radius = Math.max(90, Math.min(width, height) * 0.28);
  const ordered = [...devices].sort((left, right) => left.hostname.localeCompare(right.hostname));
  return Object.fromEntries(ordered.map((device, index) => {
    const angle = -Math.PI / 2 + (2 * Math.PI * index) / Math.max(ordered.length, 1);
    return [device.id, {
      x: clampPosition(centerX + Math.cos(angle) * radius, 72, Math.max(72, width - 72)),
      y: clampPosition(centerY + Math.sin(angle) * radius, 82, Math.max(82, height - 82)),
    }];
  }));
};

const calculateAutoLayoutPositions = (
  devices: Device[],
  links: Link[],
  width: number,
  height: number,
  layoutMode: TopologyLayoutMode = 'hierarchy',
) => {
  if (layoutMode === 'radial') return buildRadialPositions(devices, width, height);
  if (layoutMode === 'horizontal') {
    const order = getLinearChainOrder(devices, links) || [...devices]
      .sort((left, right) => left.hostname.localeCompare(right.hostname))
      .map((device) => device.id);
    return buildHorizontalRowPositions(order, width, height);
  }
  if (layoutMode === 'hierarchy') {
    const layeredPositions = buildLayeredPositions(devices, links, width, height);
    if (layeredPositions) return layeredPositions;
  }

  const { positions: seededPositions } = buildSeedPositions(devices, width, height);
  const nodes: LayoutNode[] = devices.map((device) => ({
    ...device,
    x: seededPositions[device.id]?.x ?? width / 2,
    y: seededPositions[device.id]?.y ?? height / 2,
  }));
  const graphLinks = buildGraphLinks(nodes, links);

  if (nodes.length > 1) {
    const simulation = d3.forceSimulation(nodes as any)
      .force('link', d3.forceLink(graphLinks as any).id((node: any) => node.id)
        .distance((link: any) => link.inferred ? 140 : 112)
        .strength((link: any) => link.inferred ? 0.22 : 0.84))
      .force('charge', d3.forceManyBody().strength((node: any) => node.is_unmanaged ? -300 : -680))
      .force('collide', d3.forceCollide().radius((node: any) => node.is_unmanaged ? 42 : 56))
      .force('x', d3.forceX((node: any) => seededPositions[node.id]?.x ?? width / 2).strength(0.5))
      .force('y', d3.forceY((node: any) => seededPositions[node.id]?.y ?? height / 2).strength(0.76))
      .stop();

    const settleTicks = Math.max(140, Math.min(320, nodes.length * 22));
    for (let index = 0; index < settleTicks; index += 1) simulation.tick();
    simulation.stop();
  }

  return Object.fromEntries(nodes.map((node) => [node.id, {
    x: clampPosition(node.x || width / 2, 48, Math.max(48, width - 48)),
    y: clampPosition(node.y || height / 2, 56, Math.max(56, height - 56)),
  }]));
};

const clampPosition = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));
const TOPOLOGY_LAYOUT_STORAGE_KEY = 'nexora.topology.layout.v3';

type PersistedTopologyLayout = {
  positions?: Record<string, { x: number; y: number }>;
  transform?: { x: number; y: number; k: number };
  layoutMode?: 'free';
  displayMode?: TopologyLayoutMode;
};

const layoutIsFree = (layout: PersistedTopologyLayout) => layout.layoutMode === 'free';

type MinimapSnapshot = {
  nodes: Array<{ id: string; x: number; y: number; fill: string; selected: boolean }>;
  links: Array<{ id: string; sourceX: number; sourceY: number; targetX: number; targetY: number; color: string; width: number }>;
  viewport: { x: number; y: number; width: number; height: number };
  bounds: { minX: number; minY: number; scale: number; offsetX: number; offsetY: number; width: number; height: number };
  panel: { width: number; height: number };
};

const readPersistedLayout = (): PersistedTopologyLayout => {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(TOPOLOGY_LAYOUT_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as PersistedTopologyLayout;
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
};

const writePersistedLayout = (layout: PersistedTopologyLayout) => {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(TOPOLOGY_LAYOUT_STORAGE_KEY, JSON.stringify(layout));
  } catch {
    // Ignore storage failures to keep the interaction path stable.
  }
};

const createDefaultTransform = (width: number, height: number, nodes?: { x: number; y: number }[]) => {
  if (!nodes || nodes.length === 0) {
    return d3.zoomIdentity
      .translate(Math.max(width * 0.08, 44), Math.max(height * 0.08, 36))
      .scale(0.9);
  }

  let minX = Infinity, maxX = -Infinity;
  let minY = Infinity, maxY = -Infinity;

  nodes.forEach((node) => {
    const nodePadding = 64;
    minX = Math.min(minX, node.x - nodePadding);
    maxX = Math.max(maxX, node.x + nodePadding);
    minY = Math.min(minY, node.y - nodePadding);
    maxY = Math.max(maxY, node.y + nodePadding);
  });

  const dx = maxX - minX;
  const dy = maxY - minY;
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;

  const paddingPercent = 0.22; // occupy ~78% of viewport
  const targetWidth = width * (1 - paddingPercent);
  const targetHeight = height * (1 - paddingPercent);

  let scale = Math.min(targetWidth / dx, targetHeight / dy);
  scale = Math.max(0.45, Math.min(scale, 1.8));

  const tx = width / 2 - cx * scale;
  const ty = height / 2 - cy * scale;

  return d3.zoomIdentity.translate(tx, ty).scale(scale);
};

const getOrthogonalRoute = (source: { x: number; y: number }, target: { x: number; y: number }, offset = 0) => {
  const deltaX = target.x - source.x;
  const deltaY = target.y - source.y;
  const dist = Math.max(1, Math.sqrt(deltaX * deltaX + deltaY * deltaY));

  // Perpendicular unit vector for offsetting parallel links
  const perpX = -deltaY / dist;
  const perpY = deltaX / dist;
  const sx = source.x + perpX * offset;
  const sy = source.y + perpY * offset;
  const tx = target.x + perpX * offset;
  const ty = target.y + perpY * offset;

  // Nearly horizontal: straight line
  if (Math.abs(deltaY) <= 20) {
    return {
      path: `M ${sx} ${sy} L ${tx} ${ty}`,
      labelX: (sx + tx) / 2,
      labelY: (sy + ty) / 2,
    };
  }

  // Nearly vertical: straight line
  if (Math.abs(deltaX) <= 20) {
    return {
      path: `M ${sx} ${sy} L ${tx} ${ty}`,
      labelX: (sx + tx) / 2,
      labelY: (sy + ty) / 2,
    };
  }

  // Intermediate midpoint
  const midX = (sx + tx) / 2;
  const midY = (sy + ty) / 2;

  // Diagonal / Bypassing: draw 90-degree orthogonal line
  // If the flow is more vertical (e.g. connecting different layers/rows)
  if (Math.abs(deltaY) >= Math.abs(deltaX)) {
    // Go vertically to midY, then horizontally to tx, then vertically to ty
    return {
      path: `M ${sx} ${sy} L ${sx} ${midY} L ${tx} ${midY} L ${tx} ${ty}`,
      labelX: (sx + tx) / 2,
      labelY: midY,
    };
  } else {
    // Go horizontally to midX, then vertically to ty, then horizontally to tx
    return {
      path: `M ${sx} ${sy} L ${midX} ${sy} L ${midX} ${ty} L ${tx} ${ty}`,
      labelX: midX,
      labelY: (sy + ty) / 2,
    };
  }
};

const buildMinimapSnapshot = (
  nodes: Array<any>,
  links: Array<any>,
  transform: d3.ZoomTransform,
  viewportWidth: number,
  viewportHeight: number,
  selectedNodeId?: string | null,
): MinimapSnapshot | null => {
  if (!nodes.length || viewportWidth === 0 || viewportHeight === 0) return null;

  const panel = { width: 188, height: 132 };
  const padding = 14;
  const xs = nodes.map((node) => Number(node.x || 0));
  const ys = nodes.map((node) => Number(node.y || 0));
  const minX = Math.min(...xs) - 70;
  const maxX = Math.max(...xs) + 70;
  const minY = Math.min(...ys) - 70;
  const maxY = Math.max(...ys) + 70;
  const contentWidth = Math.max(maxX - minX, 1);
  const contentHeight = Math.max(maxY - minY, 1);
  const scale = Math.min((panel.width - padding * 2) / contentWidth, (panel.height - padding * 2) / contentHeight);
  const offsetX = (panel.width - contentWidth * scale) / 2;
  const offsetY = (panel.height - contentHeight * scale) / 2;

  const toMiniX = (value: number) => offsetX + (value - minX) * scale;
  const toMiniY = (value: number) => offsetY + (value - minY) * scale;

  const worldLeft = (-transform.x) / transform.k;
  const worldTop = (-transform.y) / transform.k;
  const worldWidth = viewportWidth / transform.k;
  const worldHeight = viewportHeight / transform.k;

  return {
    nodes: nodes.map((node) => ({
      id: node.id,
      x: toMiniX(node.x || 0),
      y: toMiniY(node.y || 0),
      fill: getNodeTone(node).fill,
      selected: node.id === selectedNodeId,
    })),
    links: links.map((link, index) => ({
      id: String(link.link_key || link.id || index),
      sourceX: toMiniX(link.source.x || 0),
      sourceY: toMiniY(link.source.y || 0),
      targetX: toMiniX(link.target.x || 0),
      targetY: toMiniY(link.target.y || 0),
      color: getBandwidthTier(link.bandwidth_mbps).color,
      width: Math.max(1, getBandwidthTier(link.bandwidth_mbps).width * 0.65),
    })),
    viewport: {
      x: toMiniX(worldLeft),
      y: toMiniY(worldTop),
      width: Math.max(worldWidth * scale, 18),
      height: Math.max(worldHeight * scale, 14),
    },
    bounds: { minX, minY, scale, offsetX, offsetY, width: contentWidth, height: contentHeight },
    panel,
  };
};

const TopologyGraph: React.FC<TopologyGraphProps> = ({ devices, links, onNodeClick, onOpenWorkspace, selectedNodeId, selectedLinkKey, onLinkClick }) => {
  const GRID_SIZE = 16;
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const persistedPositionsRef = useRef<Record<string, { x: number; y: number }>>({});
  const zoomBehaviorRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const svgSelectionRef = useRef<d3.Selection<SVGSVGElement, unknown, null, undefined> | null>(null);
  const zoomTransformRef = useRef<d3.ZoomTransform | null>(null);
  const persistTimerRef = useRef<number | null>(null);
  const suppressPersistRef = useRef(false);
  const dragStateRef = useRef<{ id: string | null; moved: boolean }>({ id: null, moved: false });
  const suppressNextNodeClickRef = useRef(false);
  const spacePressedRef = useRef(false);
  const shiftPressedRef = useRef(false);
  const boxSelectModeRef = useRef(false);
  const gridSnapRef = useRef(true);
  const dragBeforePositionsRef = useRef<Record<string, { x: number; y: number }> | null>(null);
  const dragGroupRef = useRef<{
    primaryId: string;
    ids: string[];
    initialPositions: Record<string, { x: number; y: number }>;
  } | null>(null);
  const layoutHistoryRef = useRef<Array<{ positions: Record<string, { x: number; y: number }>; transform?: { x: number; y: number; k: number } }>>([]);
  const layoutHistoryIndexRef = useRef(-1);
  const hydrationCompleteRef = useRef(false);
  const [viewport, setViewport] = useState({ width: 0, height: 0 });
  const [zoomPercent, setZoomPercent] = useState(90);
  const [layoutVersion, setLayoutVersion] = useState(0);
  const [minimapSnapshot, setMinimapSnapshot] = useState<MinimapSnapshot | null>(null);
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>(selectedNodeId ? [selectedNodeId] : []);
  const [gridSnapEnabled, setGridSnapEnabled] = useState(true);
  const [spacePanActive, setSpacePanActive] = useState(false);
  const [boxSelectMode, setBoxSelectMode] = useState(false);
  const [layoutMode, setLayoutMode] = useState<TopologyLayoutMode>('hierarchy');
  const [displayScope, setDisplayScope] = useState<'auto' | TopologyDisplayMode>('auto');
  const [expandedGroupIds, setExpandedGroupIds] = useState<Set<string>>(new Set());
  const [drillPath, setDrillPath] = useState<TopologyDrillSegment[]>([]);
  const [historyState, setHistoryState] = useState({ canUndo: false, canRedo: false });
  const [hoveredDeviceId, setHoveredDeviceId] = useState<string | null>(null);
  const [hoveredLinkId, setHoveredLinkId] = useState<string | null>(null);
  const [hoverCardPosition, setHoverCardPosition] = useState({ x: 12, y: 12 });
  const hoverHideTimerRef = useRef<number | null>(null);
  const selectedNodeIdsKey = selectedNodeIds.join('|');
  const resolvedDisplayMode = useMemo(
    () => resolveTopologyDisplayMode(devices.length, displayScope),
    [devices.length, displayScope],
  );
  const displayGraph = useMemo(
    () => aggregateTopologyGraph<Device, Link>(devices, links, resolvedDisplayMode, expandedGroupIds, drillPath),
    [devices, drillPath, expandedGroupIds, links, resolvedDisplayMode],
  );
  const graphDevices = displayGraph.devices;
  const graphLinks = displayGraph.links;
  const hoveredDevice = useMemo(
    () => graphDevices.find((device) => device.id === hoveredDeviceId) || null,
    [graphDevices, hoveredDeviceId],
  );
  const hoveredLink = useMemo(
    () => graphLinks.find((link) => (link.link_key || link.id) === hoveredLinkId) || null,
    [graphLinks, hoveredLinkId],
  );

  useEffect(() => {
    const validIds = new Set(displayGraph.groups.map((group) => group.id));
    setExpandedGroupIds((current) => {
      const next = new Set(Array.from(current).filter((id) => validIds.has(id)));
      return next.size === current.size ? current : next;
    });
  }, [displayGraph.groups]);

  const clearHoverHideTimer = () => {
    if (hoverHideTimerRef.current !== null) {
      window.clearTimeout(hoverHideTimerRef.current);
      hoverHideTimerRef.current = null;
    }
  };

  const scheduleHoverCardHide = () => {
    clearHoverHideTimer();
    hoverHideTimerRef.current = window.setTimeout(() => {
      setHoveredDeviceId(null);
      setHoveredLinkId(null);
      hoverHideTimerRef.current = null;
    }, 180);
  };

  const updateHoverCard = (event: any, device: Device) => {
    const container = containerRef.current;
    if (!container) return;
    clearHoverHideTimer();
    const rect = container.getBoundingClientRect();
    const cardWidth = 220;
    const cardHeight = 176;
    const x = Math.min(Math.max(event.clientX - rect.left + 14, 8), Math.max(8, rect.width - cardWidth - 8));
    const y = Math.min(Math.max(event.clientY - rect.top + 14, 8), Math.max(8, rect.height - cardHeight - 8));
    setHoverCardPosition({ x, y });
    setHoveredDeviceId(device.id);
    setHoveredLinkId(null); // hide link hover card
  };

  const updateLinkHoverCard = (event: any, link: Link) => {
    const container = containerRef.current;
    if (!container) return;
    clearHoverHideTimer();
    const rect = container.getBoundingClientRect();
    const cardWidth = 240;
    const cardHeight = 220;
    const x = Math.min(Math.max(event.clientX - rect.left + 14, 8), Math.max(8, rect.width - cardWidth - 8));
    const y = Math.min(Math.max(event.clientY - rect.top + 14, 8), Math.max(8, rect.height - cardHeight - 8));
    setHoverCardPosition({ x, y });
    setHoveredLinkId(link.link_key || link.id || '');
    setHoveredDeviceId(null); // hide device hover card
  };

  const toggleGroup = (group: Device) => {
    if (!group.is_group || !group.group_id) return;
    if (group.group_can_drill && group.group_path?.length) {
      setDrillPath(group.group_path);
      setExpandedGroupIds(new Set());
      setHoveredDeviceId(null);
      return;
    }
    setExpandedGroupIds((current) => {
      const next = new Set(current);
      if (next.has(group.group_id)) next.delete(group.group_id);
      else next.add(group.group_id);
      return next;
    });
    setHoveredDeviceId(null);
  };

  const resetDrillPath = () => {
    setDrillPath([]);
    setExpandedGroupIds(new Set());
    setHoveredDeviceId(null);
  };

  const jumpToDrillPath = (index: number) => {
    setDrillPath((current) => current.slice(0, index));
    setExpandedGroupIds(new Set());
    setHoveredDeviceId(null);
  };

  const clonePositions = (positions: Record<string, { x: number; y: number }>) => Object.fromEntries(
    Object.entries(positions).map(([id, position]) => [id, { x: position.x, y: position.y }]),
  );

  const cloneTransform = (transform: d3.ZoomTransform | null | undefined) => transform
    ? { x: transform.x, y: transform.y, k: transform.k }
    : undefined;

  const positionsEqual = (left: Record<string, { x: number; y: number }>, right: Record<string, { x: number; y: number }>) => {
    const leftIds = Object.keys(left);
    const rightIds = Object.keys(right);
    if (leftIds.length !== rightIds.length) return false;
    return leftIds.every((id) => left[id]?.x === right[id]?.x && left[id]?.y === right[id]?.y);
  };

  const refreshHistoryState = () => {
    setHistoryState({
      canUndo: layoutHistoryIndexRef.current > 0,
      canRedo: layoutHistoryIndexRef.current >= 0 && layoutHistoryIndexRef.current < layoutHistoryRef.current.length - 1,
    });
  };

  const recordLayoutHistory = (before: Record<string, { x: number; y: number }>, after: Record<string, { x: number; y: number }>) => {
    if (positionsEqual(before, after)) return;
    if (layoutHistoryIndexRef.current < 0) {
      layoutHistoryRef.current = [{ positions: clonePositions(before), transform: cloneTransform(zoomTransformRef.current) }];
      layoutHistoryIndexRef.current = 0;
    }
    layoutHistoryRef.current = layoutHistoryRef.current.slice(0, layoutHistoryIndexRef.current + 1);
    layoutHistoryRef.current.push({ positions: clonePositions(after), transform: cloneTransform(zoomTransformRef.current) });
    layoutHistoryIndexRef.current += 1;
    refreshHistoryState();
  };

  const persistLayoutSnapshot = (snapshot: { positions: Record<string, { x: number; y: number }>; transform?: { x: number; y: number; k: number } }) => {
    persistedPositionsRef.current = clonePositions(snapshot.positions);
    zoomTransformRef.current = snapshot.transform
      ? d3.zoomIdentity.translate(snapshot.transform.x, snapshot.transform.y).scale(snapshot.transform.k)
      : null;
    writePersistedLayout({
      positions: persistedPositionsRef.current,
      transform: snapshot.transform,
      layoutMode: 'free',
      displayMode: layoutMode,
    });
    syncLayoutToBackend({
      positions: persistedPositionsRef.current,
      transform: snapshot.transform,
      layoutMode: 'free',
      displayMode: layoutMode,
    });
    setLayoutVersion((value) => value + 1);
    refreshHistoryState();
  };

  useEffect(() => {
    setSelectedNodeIds(selectedNodeId ? [selectedNodeId] : []);
  }, [selectedNodeId]);

  useEffect(() => {
    gridSnapRef.current = gridSnapEnabled;
  }, [gridSnapEnabled]);

  useEffect(() => {
    boxSelectModeRef.current = boxSelectMode;
  }, [boxSelectMode]);

  useEffect(() => {
    const isTextEditingTarget = (target: EventTarget | null) => {
      const element = target as HTMLElement | null;
      return Boolean(element?.closest?.('input, textarea, select, [contenteditable="true"]'));
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (isTextEditingTarget(event.target)) return;
      if (event.code === 'ShiftLeft' || event.code === 'ShiftRight') {
        shiftPressedRef.current = true;
        return;
      }
      if ((event.metaKey || event.ctrlKey) && event.code === 'KeyZ') {
        event.preventDefault();
        if (event.shiftKey) redoLayout();
        else undoLayout();
        return;
      }
      if ((event.metaKey || event.ctrlKey) && event.code === 'KeyY') {
        event.preventDefault();
        redoLayout();
        return;
      }
      if (event.code !== 'Space') return;
      event.preventDefault();
      if (!spacePressedRef.current) {
        spacePressedRef.current = true;
        setSpacePanActive(true);
      }
    };
    const handleKeyUp = (event: KeyboardEvent) => {
      if (event.code === 'ShiftLeft' || event.code === 'ShiftRight') {
        shiftPressedRef.current = false;
      }
      if (event.code !== 'Space') return;
      spacePressedRef.current = false;
      setSpacePanActive(false);
    };
    const handleWindowBlur = () => {
      spacePressedRef.current = false;
      shiftPressedRef.current = false;
      setSpacePanActive(false);
    };
    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keyup', handleKeyUp);
    window.addEventListener('blur', handleWindowBlur);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keyup', handleKeyUp);
      window.removeEventListener('blur', handleWindowBlur);
    };
  }, []);

  const syncLayoutToBackend = (layout: PersistedTopologyLayout) => {
    if (typeof window === 'undefined') return;
    const token = window.localStorage.getItem('netops_token');
    if (!token) return;
    void fetch('/api/topology/layout', {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ layout }),
    }).catch(() => {
      // Keep local persistence even if remote sync is temporarily unavailable.
    });
  };

  const persistCurrentLayout = (displayMode: TopologyLayoutMode = layoutMode) => {
    if (!hydrationCompleteRef.current) return;
    const transform = zoomTransformRef.current;
    const layout = {
      positions: persistedPositionsRef.current,
      transform: transform ? { x: transform.x, y: transform.y, k: transform.k } : undefined,
      layoutMode: 'free' as const,
      displayMode,
    };
    writePersistedLayout(layout);
    if (persistTimerRef.current) {
      window.clearTimeout(persistTimerRef.current);
    }
    persistTimerRef.current = window.setTimeout(() => {
      syncLayoutToBackend(layout);
    }, 240);
  };

  const applyTransform = (transform: d3.ZoomTransform) => {
    if (!svgSelectionRef.current || !zoomBehaviorRef.current) return;
    svgSelectionRef.current.call(zoomBehaviorRef.current.transform as any, transform);
  };

  const zoomAroundViewportCenter = (factor: number) => {
    if (viewport.width === 0 || viewport.height === 0) return;
    const nodePositions = graphDevices.map((d) => persistedPositionsRef.current[d.id] || { x: viewport.width / 2, y: viewport.height / 2 });
    const baseTransform = zoomTransformRef.current || createDefaultTransform(viewport.width, viewport.height, nodePositions);
    const nextScale = clampPosition(baseTransform.k * factor, 0.35, 3.2);
    const centerX = viewport.width / 2;
    const centerY = viewport.height / 2;
    const worldX = (centerX - baseTransform.x) / baseTransform.k;
    const worldY = (centerY - baseTransform.y) / baseTransform.k;
    const nextTransform = d3.zoomIdentity
      .translate(centerX - worldX * nextScale, centerY - worldY * nextScale)
      .scale(nextScale);
    applyTransform(nextTransform);
  };

  const fitViewport = () => {
    if (viewport.width === 0 || viewport.height === 0) return;
    const nodePositions = graphDevices.map((d) => {
      const pos = persistedPositionsRef.current[d.id] || { x: viewport.width / 2, y: viewport.height / 2 };
      return pos;
    });
    applyTransform(createDefaultTransform(viewport.width, viewport.height, nodePositions));
  };

  const resetLayout = () => {
    const before = clonePositions(persistedPositionsRef.current);
    recordLayoutHistory(before, {});
    persistedPositionsRef.current = {};
    zoomTransformRef.current = null;
    writePersistedLayout({});
    syncLayoutToBackend({});
    setLayoutVersion((value) => value + 1);
  };

  const applyAutoLayout = (nextLayoutMode: TopologyLayoutMode = layoutMode) => {
    if (viewport.width === 0 || viewport.height === 0 || devices.length === 0) return;
    const before = clonePositions(persistedPositionsRef.current);
    const next = calculateAutoLayoutPositions(devices, links, viewport.width, viewport.height, nextLayoutMode);
    if (gridSnapRef.current) {
      Object.values(next).forEach((position) => {
        position.x = Math.round(position.x / GRID_SIZE) * GRID_SIZE;
        position.y = Math.round(position.y / GRID_SIZE) * GRID_SIZE;
      });
    }
    persistedPositionsRef.current = next;
    recordLayoutHistory(before, next);
    persistCurrentLayout(nextLayoutMode);
    applyTransform(createDefaultTransform(viewport.width, viewport.height, Object.values(next)));
    setLayoutVersion((value) => value + 1);
  };

  const changeLayoutMode = (nextLayoutMode: TopologyLayoutMode) => {
    setLayoutMode(nextLayoutMode);
    applyAutoLayout(nextLayoutMode);
  };

  const undoLayout = () => {
    if (layoutHistoryIndexRef.current <= 0) return;
    layoutHistoryIndexRef.current -= 1;
    const snapshot = layoutHistoryRef.current[layoutHistoryIndexRef.current];
    if (snapshot) persistLayoutSnapshot(snapshot);
  };

  const redoLayout = () => {
    if (layoutHistoryIndexRef.current < 0 || layoutHistoryIndexRef.current >= layoutHistoryRef.current.length - 1) return;
    layoutHistoryIndexRef.current += 1;
    const snapshot = layoutHistoryRef.current[layoutHistoryIndexRef.current];
    if (snapshot) persistLayoutSnapshot(snapshot);
  };

  const handleMinimapClick = (event: React.MouseEvent<SVGSVGElement>) => {
    if (!minimapSnapshot || viewport.width === 0 || viewport.height === 0) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const localX = event.clientX - bounds.left;
    const localY = event.clientY - bounds.top;
    const worldX = minimapSnapshot.bounds.minX + (localX - minimapSnapshot.bounds.offsetX) / minimapSnapshot.bounds.scale;
    const worldY = minimapSnapshot.bounds.minY + (localY - minimapSnapshot.bounds.offsetY) / minimapSnapshot.bounds.scale;
    const nodePositions = graphDevices.map((d) => persistedPositionsRef.current[d.id] || { x: viewport.width / 2, y: viewport.height / 2 });
    const currentTransform = zoomTransformRef.current || createDefaultTransform(viewport.width, viewport.height, nodePositions);
    const nextTransform = d3.zoomIdentity
      .translate(viewport.width / 2 - worldX * currentTransform.k, viewport.height / 2 - worldY * currentTransform.k)
      .scale(currentTransform.k);
    applyTransform(nextTransform);
  };

  useEffect(() => {
    if (!containerRef.current) return;

    const updateViewport = () => {
      if (!containerRef.current) return;
      setViewport({
        width: containerRef.current.clientWidth,
        height: containerRef.current.clientHeight,
      });
    };

    updateViewport();
    const observer = new ResizeObserver(updateViewport);
    observer.observe(containerRef.current);
    window.addEventListener('resize', updateViewport);

    return () => {
      observer.disconnect();
      window.removeEventListener('resize', updateViewport);
    };
  }, []);

  useEffect(() => {
    const persistedLayout = readPersistedLayout();
    if (persistedLayout.displayMode && ['hierarchy', 'horizontal', 'force', 'radial'].includes(persistedLayout.displayMode)) {
      setLayoutMode(persistedLayout.displayMode);
    }
    const compatibleLocalLayout = layoutIsFree(persistedLayout)
      && ['hierarchy', 'horizontal', 'force', 'radial'].includes(persistedLayout.displayMode || '');
    persistedPositionsRef.current = compatibleLocalLayout ? (persistedLayout.positions || {}) : {};
    if (compatibleLocalLayout && persistedLayout.transform) {
      zoomTransformRef.current = d3.zoomIdentity
        .translate(persistedLayout.transform.x, persistedLayout.transform.y)
        .scale(persistedLayout.transform.k);
      setZoomPercent(Math.round(persistedLayout.transform.k * 100));
    }

    const token = typeof window === 'undefined' ? '' : (window.localStorage.getItem('netops_token') || '');
    if (!token) {
      hydrationCompleteRef.current = true;
      return;
    }

    void fetch('/api/topology/layout', {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async (response) => {
        if (!response.ok) return null;
        return response.json();
      })
      .then((payload) => {
        const layout = payload?.layout;
        if (!layout || typeof layout !== 'object') return;
        if (layout.displayMode && ['hierarchy', 'horizontal', 'force', 'radial'].includes(layout.displayMode)) {
          setLayoutMode(layout.displayMode as TopologyLayoutMode);
        }
        const compatibleRemoteLayout = layoutIsFree(layout)
          && ['hierarchy', 'horizontal', 'force', 'radial'].includes(String(layout.displayMode || ''));
        persistedPositionsRef.current = compatibleRemoteLayout ? (layout.positions || {}) : {};
        if (compatibleRemoteLayout && layout.transform) {
          zoomTransformRef.current = d3.zoomIdentity
            .translate(Number(layout.transform.x || 0), Number(layout.transform.y || 0))
            .scale(Number(layout.transform.k || 1));
          setZoomPercent(Math.round(Number(layout.transform.k || 1) * 100));
        } else {
          zoomTransformRef.current = null;
          setZoomPercent(90);
        }
        writePersistedLayout(layout);
        setLayoutVersion((value) => value + 1);
      })
      .finally(() => {
        hydrationCompleteRef.current = true;
      });
  }, [devices.length]);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange);
  }, []);

  const toggleFullscreen = () => {
    const el = containerRef.current;
    if (!el) return;
    if (!document.fullscreenElement) {
      el.requestFullscreen().then(() => setIsFullscreen(true)).catch(err => console.error(err));
    } else {
      document.exitFullscreen().then(() => setIsFullscreen(false)).catch(err => console.error(err));
    }
  };

  const exportSvg = () => {
    const svgEl = svgRef.current;
    if (!svgEl) return;
    const serializer = new XMLSerializer();
    let source = serializer.serializeToString(svgEl);
    if (!source.match(/^<svg[^>]+xmlns="http\:\/\/www\.w3\.org\/2000\/svg"/)) {
      source = source.replace(/^<svg/, '<svg xmlns="http://www.w3.org/2000/svg"');
    }
    if (!source.match(/^<svg[^>]+ xmlns\:xlink="http\:\/\/www\.w3\.org\/1999\/xlink"/)) {
      source = source.replace(/^<svg/, '<svg xmlns:xlink="http://www.w3.org/1999/xlink"');
    }
    const url = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(source);
    const link = document.createElement("a");
    link.href = url;
    link.download = "topology.svg";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const exportPng = () => {
    const svgEl = svgRef.current;
    if (!svgEl) return;
    const serializer = new XMLSerializer();
    const source = serializer.serializeToString(svgEl);
    const svgBlob = new Blob([source], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(svgBlob);
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      const scaleFactor = 2;
      canvas.width = (svgEl.clientWidth || 1200) * scaleFactor;
      canvas.height = (svgEl.clientHeight || 800) * scaleFactor;
      const context = canvas.getContext("2d");
      if (context) {
        context.fillStyle = "#ffffff";
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.drawImage(img, 0, 0, canvas.width, canvas.height);
        const pngUrl = canvas.toDataURL("image/png");
        const downloadLink = document.createElement("a");
        downloadLink.href = pngUrl;
        downloadLink.download = "topology.png";
        document.body.appendChild(downloadLink);
        downloadLink.click();
        document.body.removeChild(downloadLink);
      }
      URL.revokeObjectURL(url);
    };
    img.src = url;
  };

  useEffect(() => () => {
    if (persistTimerRef.current) {
      window.clearTimeout(persistTimerRef.current);
    }
    clearHoverHideTimer();
  }, []);

  /* eslint-disable react-hooks/exhaustive-deps */
  useEffect(() => {
    if (!svgRef.current || !containerRef.current || graphDevices.length === 0 || viewport.width === 0 || viewport.height === 0) return;

    const width = viewport.width;
    const height = viewport.height;

    const svg = d3.select(svgRef.current);
    svgSelectionRef.current = svg;
    svg.selectAll('*').remove();
    svg.attr('viewBox', `0 0 ${width} ${height}`);

    svg.select('defs').remove();
    const defs = svg.append('defs');
    const filter = defs.append('filter')
      .attr('id', 'shadow')
      .attr('x', '-10%')
      .attr('y', '-10%')
      .attr('width', '120%')
      .attr('height', '120%');
    filter.append('feDropShadow')
      .attr('dx', '0')
      .attr('dy', '4')
      .attr('stdDeviation', '6')
      .attr('flood-color', '#0f172a')
      .attr('flood-opacity', '0.06');

    svg.append('rect')
      .attr('class', 'topology-canvas-background')
      .attr('x', 0)
      .attr('y', 0)
      .attr('width', width)
      .attr('height', height)
      .attr('fill', '#ffffff')
      .attr('pointer-events', 'none');

    const g = svg.append('g');
    let syncMinimap = (_transform?: d3.ZoomTransform) => {};

    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.35, 3.2])
      .filter((event: any) => {
        if (dragStateRef.current.id) return false;
        // Let the page scroll normally. Canvas zoom is intentionally exposed
        // through the +/- controls and Fit so a wheel gesture never changes
        // the whole topology view unexpectedly.
        if (event.type === 'wheel') return false;
        if (spacePressedRef.current) return !event.ctrlKey && (!event.button || event.button === 0);
        if (event.shiftKey || shiftPressedRef.current || boxSelectModeRef.current) return false;
        const target = event.target as Element | null;
        const isNodeGesture = Boolean(target?.closest?.('.topology-node'));
        if (isNodeGesture && (event.type === 'mousedown' || event.type === 'pointerdown' || event.type === 'touchstart')) {
          return false;
        }
        return !event.ctrlKey && (!event.button || event.button === 0);
      })
      .on('start', () => {
        svg.style('cursor', 'grabbing');
      })
      .on('zoom', (event) => {
        zoomTransformRef.current = event.transform;
        setZoomPercent(Math.round(event.transform.k * 100));
        g.attr('transform', event.transform.toString());
        syncMinimap(event.transform);
      })
      .on('end', () => {
        svg.style('cursor', 'grab');
        if (suppressPersistRef.current) {
          suppressPersistRef.current = false;
          return;
        }
        persistCurrentLayout();
      });
    zoomBehaviorRef.current = zoom;
    svg
      .style('cursor', 'grab')
      .style('touch-action', 'none')
      .style('user-select', 'none');
    svg.call(zoom as any);

    const activeDeviceIds = new Set(graphDevices.map((device) => device.id));
    Object.keys(persistedPositionsRef.current).forEach((deviceId) => {
      if (!activeDeviceIds.has(deviceId)) {
        delete persistedPositionsRef.current[deviceId];
      }
    });

    const { positions: seededPositions, siteAnchors } = buildSeedPositions(graphDevices, width, height);
    const layeredPositions = layoutMode === 'hierarchy' ? buildLayeredPositions(graphDevices, graphLinks, width, height) : null;
    const linearPositions = layoutMode === 'horizontal' ? buildLinearPositions(graphDevices, graphLinks, width, height) : null;
    const radialPositions = layoutMode === 'radial' ? buildRadialPositions(graphDevices, width, height) : null;
    const structuredPositions = layeredPositions || linearPositions || radialPositions;
    const hasPersistedPositions = Object.keys(persistedPositionsRef.current).length > 0;
    const shouldAutoArrange = !hasPersistedPositions;
    const autoPositions = shouldAutoArrange
      ? (structuredPositions || calculateAutoLayoutPositions(graphDevices, graphLinks, width, height, layoutMode))
      : null;
    const nodes = graphDevices.map((device) => {
      let x = autoPositions?.[device.id]?.x ?? persistedPositionsRef.current[device.id]?.x ?? structuredPositions?.[device.id]?.x ?? seededPositions[device.id]?.x ?? width / 2;
      let y = autoPositions?.[device.id]?.y ?? persistedPositionsRef.current[device.id]?.y ?? structuredPositions?.[device.id]?.y ?? seededPositions[device.id]?.y ?? height / 2;

      // In structured layout modes, enforce layout constraints (e.g., strict rows in hierarchy)
      // to align layers correctly even if layout data was saved with different/stale Y coordinates.
      if (layoutMode === 'hierarchy' && structuredPositions?.[device.id]) {
        y = structuredPositions[device.id].y;
      } else if (layoutMode === 'horizontal' && structuredPositions?.[device.id]) {
        x = structuredPositions[device.id].x;
      } else if (layoutMode === 'radial' && structuredPositions?.[device.id]) {
        x = structuredPositions[device.id].x;
        y = structuredPositions[device.id].y;
      }

      return {
        ...device,
        x,
        y,
      };
    });
    const d3Links = buildGraphLinks(nodes, graphLinks);

    nodes.forEach((node: any) => {
      node.x = clampPosition(node.x || width / 2, 48, width - 48);
      node.y = clampPosition(node.y || height / 2, 56, height - 56);
      persistedPositionsRef.current[node.id] = { x: node.x, y: node.y };
    });

    const neighborMap = new Map<string, Set<string>>();
    d3Links.forEach((link: any) => {
      const sourceId = link.source.id;
      const targetId = link.target.id;
      if (!neighborMap.has(sourceId)) neighborMap.set(sourceId, new Set());
      if (!neighborMap.has(targetId)) neighborMap.set(targetId, new Set());
      neighborMap.get(sourceId)?.add(targetId);
      neighborMap.get(targetId)?.add(sourceId);
    });

    const selectedNodeIdSet = new Set(selectedNodeIds);
    const selectedNeighbors = selectedNodeId ? (neighborMap.get(selectedNodeId) || new Set<string>()) : new Set<string>();
    const hasFocus = Boolean(selectedNodeId);
    const isNodeSelected = (deviceId: string) => selectedNodeIdSet.has(deviceId);
    const layerSummary = buildLayerSummary(graphDevices);
    // Repeating ACCESS below every node is useful for a small mixed-layer
    // topology, but becomes visual noise when all devices are in one layer or
    // when the graph contains many nodes. In those cases the site badge,
    // legend, and node tooltip carry the same information more efficiently.
    const showNodeRoleLabels = !structuredPositions && layerSummary.length > 1 && graphDevices.length <= 20;
    const showLayerLegend = graphDevices.length > 12 || (!structuredPositions && layerSummary.length > 1);
    const layerSummaryBySite = new Map<string, string>();
    const devicesBySite = new Map<string, Device[]>();
    graphDevices.forEach((device) => {
      const key = getSiteKey(device.site_id || device.site);
      const current = devicesBySite.get(key) || [];
      current.push(device);
      devicesBySite.set(key, current);
    });
    devicesBySite.forEach((siteDevices, key) => layerSummaryBySite.set(key, formatLayerSummary(siteDevices)));

    const siteGuide = g.append('g').attr('pointer-events', 'none');

    if (structuredPositions) {
      const groupedSites = new Map<string, { label: string; nodes: any[] }>();
      nodes.forEach((node: any) => {
        const key = getSiteKey(node.site_id || node.site);
        const current = groupedSites.get(key) || { label: String(node.site || '').trim() || 'Unassigned', nodes: [] };
        current.nodes.push(node);
        groupedSites.set(key, current);
      });
      Array.from(groupedSites.values()).forEach((site, index) => {
        const minX = Math.min(...site.nodes.map((node) => node.x));
        const maxX = Math.max(...site.nodes.map((node) => node.x));
        const minY = Math.min(...site.nodes.map((node) => node.y));
        const maxY = Math.max(...site.nodes.map((node) => node.y));
        
        let left = minX - 88;
        let right = maxX + 88;
        const currentWidth = right - left;
        if (currentWidth < 680) {
          const delta = (680 - currentWidth) / 2;
          left -= delta;
          right += delta;
        }
        left = Math.max(8, left);
        right = Math.min(width - 8, right);

        const top = Math.max(28, minY - 88);
        const bottom = Math.min(height - 18, maxY + 98);

        siteGuide.append('rect')
          .attr('x', left)
          .attr('y', top)
          .attr('width', Math.max(right - left, 1))
          .attr('height', Math.max(bottom - top, 1))
          .attr('rx', 16)
          .attr('fill', '#f8fafc')
          .attr('stroke', '#e2e8f0')
          .attr('stroke-width', 1.5)
          .attr('filter', 'url(#shadow)');

        const labelGroup = siteGuide.append('g').attr('transform', `translate(${(left + right) / 2},${top + 12})`);
        const siteNodeIds = new Set(site.nodes.map((node) => node.id));
        const siteLinkCount = d3Links.filter((link: any) => siteNodeIds.has(link.source_device_id) && siteNodeIds.has(link.target_device_id)).length;
        const siteLayers = formatLayerSummary(site.nodes);
        const siteNodeCount = site.nodes.reduce((total: number, node: any) => total + (node.is_group ? Number(node.group_member_count || 0) : 1), 0);
        const siteName = site.label.length > 18 ? `${site.label.slice(0, 18)}...` : site.label;
        const label = `🏢 ${siteName.toUpperCase()}  ·  ${siteNodeCount} Nodes  ·  ${siteLinkCount} Links${siteLayers ? `  ·  ${siteLayers}` : ''}`;
        const labelWidth = Math.max(120, label.length * 6.0 + 36);
        labelGroup.append('rect')
          .attr('x', -labelWidth / 2)
          .attr('y', -12)
          .attr('width', labelWidth)
          .attr('height', 24)
          .attr('rx', 12)
          .attr('fill', 'rgba(15,23,42,0.92)')
          .attr('stroke', 'rgba(148,163,184,0.30)');
        labelGroup.append('text')
          .attr('text-anchor', 'middle')
          .attr('dominant-baseline', 'middle')
          .attr('fill', '#f1f5f9')
          .attr('font-family', '"Segoe UI Variable Text", "Microsoft YaHei UI", sans-serif')
          .attr('font-size', '10px')
          .attr('font-weight', 750)
          .text(label);

        // Render horizontal layer separators inside the site
        const rowGroups = new Map<string, { y: number; tone: ReturnType<typeof getLayerTone> }>();
        site.nodes.forEach((node: any) => {
          const tone = getLayerTone(node as Device);
          const rowKey = `${tone.label}:${Math.round(Number(node.y || 0) / 8) * 8}`;
          if (!rowGroups.has(rowKey)) rowGroups.set(rowKey, { y: node.y, tone });
        });

        rowGroups.forEach(({ y, tone }) => {
          const rowText = `${tone.label.toUpperCase()} LAYER`;
          const lineY = y - 48;
          const startX = left + 24;
          const estimatedTextWidth = rowText.length * 6.2;
          const lineStartX = startX + estimatedTextWidth + 12;

          // Separator line
          if (lineStartX < right - 24) {
            siteGuide.append('line')
              .attr('x1', lineStartX)
              .attr('y1', lineY)
              .attr('x2', right - 24)
              .attr('y2', lineY)
              .attr('stroke', '#E8EDF5')
              .attr('stroke-width', 1.2)
              .attr('stroke-dasharray', '3,3');
          }

          // Text label
          siteGuide.append('text')
            .attr('x', startX)
            .attr('y', lineY)
            .attr('text-anchor', 'start')
            .attr('dominant-baseline', 'middle')
            .attr('fill', '#64748b')
            .attr('font-family', '"Segoe UI Variable Text", "Microsoft YaHei UI", sans-serif')
            .attr('font-size', '10px')
            .attr('font-weight', 800)
            .attr('letter-spacing', '0.05em')
            .text(rowText);
        });

        // Render bandwidth legend at the bottom left of the site container in SVG
        const legendY = bottom - 26;
        const legendGroup = siteGuide.append('g')
          .attr('transform', `translate(${left + 24}, ${legendY})`);

        legendGroup.append('text')
          .attr('x', 0)
          .attr('y', 0)
          .attr('dominant-baseline', 'middle')
          .attr('fill', '#64748b')
          .attr('font-family', '"Segoe UI Variable Text", "Microsoft YaHei UI", sans-serif')
          .attr('font-size', '10px')
          .attr('font-weight', 800)
          .attr('letter-spacing', '0.05em')
          .text('Bandwidth');

        let legendCursorX = 72;
        const tiersToDraw = BANDWIDTH_TIERS.filter(t => t.key !== 'unknown');
        
        tiersToDraw.forEach((tier) => {
          legendGroup.append('line')
            .attr('x1', legendCursorX)
            .attr('y1', 0)
            .attr('x2', legendCursorX + 24)
            .attr('y2', 0)
            .attr('stroke', tier.color)
            .attr('stroke-width', Math.max(2.2, tier.width * 0.9));

          legendGroup.append('text')
            .attr('x', legendCursorX + 30)
            .attr('y', 0)
            .attr('dominant-baseline', 'middle')
            .attr('fill', '#475569')
            .attr('font-family', '"Segoe UI Variable Text", "Microsoft YaHei UI", sans-serif')
            .attr('font-size', '9px')
            .attr('font-weight', 700)
            .text(tier.label);

          legendCursorX += 30 + tier.label.length * 5.8 + 18;
        });
      });
    }

    if (showLayerLegend) {
      const layerLegend = siteGuide.append('g').attr('transform', 'translate(16,48)');
      const legendWidth = Math.max(116, layerSummary.reduce((total, item) => total + (`${item.label} ${item.count}`.length * 5.8) + 18, 12));
      layerLegend.append('rect')
        .attr('x', 0)
        .attr('y', 0)
        .attr('width', legendWidth)
        .attr('height', 22)
        .attr('rx', 11)
        .attr('fill', 'rgba(255,255,255,0.94)')
        .attr('stroke', 'rgba(148,163,184,0.38)');
      let cursor = 10;
      layerSummary.forEach((item) => {
        layerLegend.append('circle')
          .attr('cx', cursor)
          .attr('cy', 11)
          .attr('r', 2.5)
          .attr('fill', item.color);
        const itemLabel = `${item.label} ${item.count}`;
        layerLegend.append('text')
          .attr('x', cursor + 6)
          .attr('y', 14)
          .attr('fill', '#334155')
          .attr('font-family', '"Segoe UI Variable Text", "Microsoft YaHei UI", sans-serif')
          .attr('font-size', '9px')
          .attr('font-weight', 700)
          .text(itemLabel);
        cursor += itemLabel.length * 5.8 + 18;
      });
    }

    const siteGuides = structuredPositions ? [] : siteAnchors;
    siteGuides.forEach((site, index) => {
      const previous = siteGuides[index - 1];
      const next = siteGuides[index + 1];
      const left = previous ? (previous.x + site.x) / 2 + 4 : 8;
      const right = next ? (site.x + next.x) / 2 - 4 : width - 8;
      siteGuide.append('rect')
        .attr('x', left)
        .attr('y', 6)
        .attr('width', Math.max(right - left, 1))
        .attr('height', Math.max(height - 14, 1))
        .attr('rx', 18)
        .attr('fill', index % 2 === 0 ? 'rgba(56,189,248,0.025)' : 'rgba(129,140,248,0.025)')
        .attr('stroke', 'rgba(148,163,184,0.16)')
        .attr('stroke-dasharray', '4,6');

      siteGuide.append('line')
        .attr('x1', site.x)
        .attr('y1', 34)
        .attr('x2', site.x)
        .attr('y2', height - 28)
        .attr('stroke', 'rgba(148,163,184,0.16)')
        .attr('stroke-dasharray', '2,8');

      const labelGroup = siteGuide.append('g').attr('transform', `translate(${site.x},18)`);
      const siteLabel = `${site.label.length > 12 ? `${site.label.slice(0, 12)}...` : site.label} - ${site.count}${layerSummaryBySite.get(site.key) ? ` - ${layerSummaryBySite.get(site.key)}` : ''}`;
      const siteLabelWidth = Math.max(96, siteLabel.length * 5.8 + 20);
      labelGroup.append('rect')
        .attr('x', -siteLabelWidth / 2)
        .attr('y', -10)
        .attr('width', siteLabelWidth)
        .attr('height', 20)
        .attr('rx', 10)
        .attr('fill', 'rgba(15,29,48,0.92)')
        .attr('stroke', 'rgba(148,163,184,0.32)');

      labelGroup.append('text')
        .attr('text-anchor', 'middle')
        .attr('dominant-baseline', 'middle')
        .attr('fill', '#dbeafe')
        .attr('font-family', '"Segoe UI Variable Text", "Microsoft YaHei UI", "PingFang SC", "Noto Sans SC", sans-serif')
        .attr('font-size', '10px')
        .attr('font-weight', 700)
        .text(siteLabel);
    });

    const linkLayer = g.append('g').attr('stroke-linecap', 'round');

    // Compute parallel link offsets: when multiple links connect the same device pair,
    // spread them apart visually so they don't overlap
    const parallelOffsetMap = new Map<string, number>();
    const pairCountMap = new Map<string, number>();
    d3Links.forEach((link: any) => {
      const pair = [String(link.source_device_id || link.source?.id || ''), String(link.target_device_id || link.target?.id || '')].sort().join('::');
      pairCountMap.set(pair, (pairCountMap.get(pair) || 0) + 1);
    });
    const pairIndexMap = new Map<string, number>();
    d3Links.forEach((link: any, i: number) => {
      const pair = [String(link.source_device_id || link.source?.id || ''), String(link.target_device_id || link.target?.id || '')].sort().join('::');
      const count = pairCountMap.get(pair) || 1;
      const idx = pairIndexMap.get(pair) || 0;
      pairIndexMap.set(pair, idx + 1);
      const spacing = 12;
      const offset = count <= 1 ? 0 : (idx - (count - 1) / 2) * spacing;
      parallelOffsetMap.set(String(i), offset);
    });

    const linkHitArea = linkLayer
      .selectAll('path.link-hit')
      .data(d3Links)
      .join('path')
      .attr('class', 'link-hit')
      .attr('fill', 'none')
      .attr('stroke', 'transparent')
      .attr('stroke-width', 18)
      .style('cursor', (item: any) => (item.inferred ? 'default' : 'pointer'))
      .on('click', (_event, item: any) => {
        if (!onLinkClick || item.inferred) return;
        onLinkClick(item as Link);
      })
      .on('pointerenter', (event, item: any) => {
        if (item.inferred) return;
        updateLinkHoverCard(event, item as Link);
      })
      .on('pointermove', (event, item: any) => {
        if (item.inferred) return;
        updateLinkHoverCard(event, item as Link);
      })
      .on('pointerleave', () => {
        scheduleHoverCardHide();
      });

    const link = linkLayer
      .selectAll('path.link-visible')
      .data(d3Links)
      .join('path')
      .attr('class', 'link-visible')
      .attr('fill', 'none')
      .attr('stroke', (item: any) => {
        const bandwidth = getBandwidthTier(item.bandwidth_mbps);
        if (item.is_unmanaged) return 'rgba(100,116,139,0.52)';
        return item.inferred ? bandwidth.mutedColor : bandwidth.color;
      })
      .attr('stroke-width', (item: any) => {
        const bandwidth = getBandwidthTier(item.bandwidth_mbps);
        const isAggregation = String(item.link_kind || '').toLowerCase() === 'aggregation';
        const isSelected = Boolean(selectedLinkKey && (item.link_key === selectedLinkKey || item.id === selectedLinkKey));
        const isFocused = selectedNodeId && (item.source.id === selectedNodeId || item.target.id === selectedNodeId);
        if (isSelected) return Math.max(3.6, bandwidth.width + (isAggregation ? 1.8 : 0.9));
        if (item.is_unmanaged) return isFocused ? 1.8 : 1.2;
        if (item.inferred) return Math.max(1.4, bandwidth.width - 0.9);
        if (item.operational_state === 'down') return Math.max(2.2, bandwidth.width);
        return isFocused ? bandwidth.width + (isAggregation ? 1.3 : 0.7) : bandwidth.width + (isAggregation ? 0.8 : 0);
      })
      .attr('stroke-dasharray', (item: any) => {
        if (item.inferred) return '6,5';
        if (item.is_unmanaged) return '4,3';
        if (item.operational_state === 'down') return '8,4';
        if (String(item.link_kind || '').toLowerCase() === 'aggregation' && Number(item.member_count || 0) > Number(item.active_member_count || 0)) return '9,4';
        return 'none';
      })
      .attr('stroke-linejoin', 'round')
      .attr('opacity', (item: any) => {
        const isSelected = Boolean(selectedLinkKey && (item.link_key === selectedLinkKey || item.id === selectedLinkKey));
        if (isSelected) return 1;
        if (!hasFocus) return 0.88;
        // Keep bandwidth colors readable while still making the selected
        // neighborhood stand out.  The previous 14% opacity made every
        // non-focused link look gray regardless of its actual speed.
        return item.source.id === selectedNodeId || item.target.id === selectedNodeId ? 1 : 0.72;
      });
    link.append('title')
      .text((item: any) => {
        const source = getLinkEndpointLabel(item, 'source') || '-';
        const target = getLinkEndpointLabel(item, 'target') || '-';
        const bandwidth = getBandwidthTier(item.bandwidth_mbps).label;
        if (String(item.link_kind || '').toLowerCase() === 'aggregation') {
          return `${source} ↔ ${target} · ${bandwidth} · ${Number(item.active_member_count || 0)}/${Number(item.member_count || 0)} members`;
        }
        return `${source} ↔ ${target} · ${bandwidth}`;
      });

    const labelledLinks = d3Links.filter((item: any) => item.source_port || item.target_port || item.source_port_normalized || item.target_port_normalized);
    const linkLabelGroup = g.append('g')
      .selectAll('g')
      .data(labelledLinks)
      .join('g')
      // Bandwidth is encoded by the link color and the fixed legend; keeping
      // this group hidden avoids a second label colliding with port names.
      .style('display', 'none');

    const linkLabelText = linkLabelGroup
      .append('text')
      .attr('font-size', 9)
      .attr('font-family', '"Segoe UI Variable Text", "Microsoft YaHei UI", "PingFang SC", "Noto Sans SC", sans-serif')
      .attr('fill', '#dbeafe')
      .attr('font-weight', 600)
      .attr('text-anchor', 'middle')
      .attr('dominant-baseline', 'middle')
      .text((item: any) => {
        const left = getBandwidthTier(item.bandwidth_mbps).label;
        if (String(item.link_kind || '').toLowerCase() === 'aggregation') {
          return `${left} · ${Number(item.active_member_count || 0)}/${Number(item.member_count || 0)}`;
        }
        const right = '';
        if (left && right) return `${left}  ↔  ${right}`;
        return left || right;
      });
    linkLabelText.append('title')
      .text((item: any) => {
        const source = getLinkEndpointLabel(item, 'source') || '-';
        const target = getLinkEndpointLabel(item, 'target') || '-';
        return `${source} ↔ ${target}`;
      });

    const portLabelGroup = g.append('g')
      .selectAll('g')
      .data(labelledLinks)
      .join('g')
      .style('cursor', 'help');
    const sourcePortLabel = portLabelGroup
      .append('text')
      .attr('font-size', 11)
      .attr('font-family', '"Segoe UI Variable Text", "Microsoft YaHei UI", sans-serif')
      .attr('fill', '#334155')
      .attr('font-weight', 700)
      .attr('text-anchor', 'middle')
      .attr('dominant-baseline', 'middle')
      .attr('paint-order', 'stroke')
      .attr('stroke', '#ffffff')
      .attr('stroke-width', 3)
      .text((item: any) => getLinkEndpointShortLabel(item, 'source'));
    sourcePortLabel.append('title')
      .text((item: any) => getLinkEndpointLabel(item, 'source'));
    const targetPortLabel = portLabelGroup
      .append('text')
      .attr('font-size', 11)
      .attr('font-family', '"Segoe UI Variable Text", "Microsoft YaHei UI", sans-serif')
      .attr('fill', '#334155')
      .attr('font-weight', 700)
      .attr('text-anchor', 'middle')
      .attr('dominant-baseline', 'middle')
      .attr('paint-order', 'stroke')
      .attr('stroke', '#ffffff')
      .attr('stroke-width', 3)
      .text((item: any) => getLinkEndpointShortLabel(item, 'target'));
    targetPortLabel.append('title')
      .text((item: any) => getLinkEndpointLabel(item, 'target'));
    portLabelGroup.append('title')
      .text((item: any) => {
        const source = getFullInterfaceLabel(item.source_port || item.source_port_normalized) || '-';
        const target = getFullInterfaceLabel(item.target_port || item.target_port_normalized) || '-';
        return `${source} ↔ ${target}`;
      });

    const linkLabelBg = linkLabelGroup
      .insert('rect', 'text')
      .attr('rx', 10)
      .attr('ry', 10)
      .attr('fill', (item: any) => {
        const bandwidth = getBandwidthTier(item.bandwidth_mbps);
        const isSelected = Boolean(selectedLinkKey && (item.link_key === selectedLinkKey || item.id === selectedLinkKey));
        return isSelected ? 'rgba(14,44,67,0.98)' : `color-mix(in srgb, ${bandwidth.color} 28%, #0f172a)`;
      })
      .attr('stroke', (item: any) => {
        const bandwidth = getBandwidthTier(item.bandwidth_mbps);
        const isSelected = Boolean(selectedLinkKey && (item.link_key === selectedLinkKey || item.id === selectedLinkKey));
        return isSelected ? 'rgba(2,132,199,0.50)' : bandwidth.color;
      })
      .attr('stroke-width', 0.8);

    const getWorldPointer = (event: any) => {
      const sourceEvent = event.sourceEvent || event;
      const graphNode = g.node();
      return d3.pointer(sourceEvent, graphNode || svgRef.current);
    };

    const selectionBoxLayer = g.append('g').attr('pointer-events', 'none');
    const selectionBoxRect = selectionBoxLayer.append('rect')
      .attr('class', 'topology-selection-box')
      .style('display', 'none');
    let selectionBoxStart: { x: number; y: number; pointerId: number; additive: boolean } | null = null;

    let dragOffset = { x: 0, y: 0 };

    const node = g.append('g')
      .selectAll('g')
      .data(nodes)
      .join("g")
      .attr('class', 'topology-node')
      .classed('topology-node-selected', (d: any) => isNodeSelected(d.id))
      .style('cursor', 'grab')
      .call(d3.drag<any, any>()
        .filter((event: any) => !event.ctrlKey && !event.shiftKey && !shiftPressedRef.current && !spacePressedRef.current && (!event.button || event.button === 0))
        .on('start', dragstarted)
        .on('drag', dragged)
        .on('end', dragended)
      )
      .on("click", (event, d) => {
        if (suppressNextNodeClickRef.current) {
          suppressNextNodeClickRef.current = false;
          return;
        }
        const additive = event.shiftKey || event.ctrlKey || event.metaKey;
        if (additive) {
          setSelectedNodeIds((current) => current.includes(d.id)
            ? current.filter((id) => id !== d.id)
            : [...current, d.id]);
          return;
        }
        if (d.is_group) {
          toggleGroup(d as Device);
          return;
        }
        setSelectedNodeIds([d.id]);
        if (onNodeClick) onNodeClick(d as Device);
      })
      .on('pointerenter', (event: any, d: any) => updateHoverCard(event, d as Device))
      .on('pointermove', (event: any, d: any) => updateHoverCard(event, d as Device))
      .on('pointerleave', () => scheduleHoverCardHide());

    node.append('circle')
      // The device glyph already has its own boundary. An additional outer
      // halo made the topology look like a status dashboard rather than a
      // clean network diagram, so keep this structural layer invisible.
      .attr('r', 0)
      .attr('fill', (d: any) => {
        if (d.is_unmanaged) return 'rgba(148,163,184,0.08)';
        if (shouldRenderDeviceGlyph(d as Device)) return 'transparent';
        return 'none';
      })
      .attr('stroke', (d: any) => {
        if (d.is_unmanaged) return 'rgba(100,116,139,0.35)';
        return 'none';
      })
      .attr('stroke-width', (d: any) => {
        if (d.is_unmanaged) return 1.5;
        return 0;
      })
      .attr('stroke-dasharray', (d: any) => (d.is_unmanaged ? '4,3' : 'none'))
      .attr('opacity', (d: any) => {
        if (!hasFocus) return 1;
        return isNodeSelected(d.id) || selectedNeighbors.has(d.id) ? 1 : 0.25;
      });

    node.append('circle')
      .attr('r', (d: any) => (shouldRenderDeviceGlyph(d as Device) ? 20 : 0))
      .attr('fill', 'transparent')
      .attr('stroke', 'none')
      .style('cursor', 'pointer');

    node.append("circle")
      .attr("r", (d: any) => {
        if (d.is_group) return 0;
        if (d.is_unmanaged) return 20;
        return shouldRenderDeviceGlyph(d as Device) ? 0 : 20;
      })
      .attr('fill', (d: any) => {
        if (d.is_unmanaged) return 'rgba(241,245,249,0.96)';
        if (shouldRenderDeviceGlyph(d as Device)) return 'rgba(255,255,255,0.96)';
        return getNodeTone(d).fill;
      })
      .attr('stroke', (d: any) => {
        if (d.is_unmanaged) return '#94a3b8';
        const tone = getNodeTone(d);
        return tone.stroke;
      })
      .attr('stroke-width', (d: any) => {
        if (d.is_unmanaged) return 1.5;
        return isNodeSelected(d.id) ? 3 : 2;
      })
      .attr('stroke-dasharray', (d: any) => (d.is_unmanaged ? '3,2' : 'none'))
      .style('cursor', 'pointer')
      .attr('opacity', (d: any) => {
        if (!hasFocus) return 1;
        return isNodeSelected(d.id) || selectedNeighbors.has(d.id) ? 1 : 0.35;
      });

    node.append('rect')
      .attr('class', 'topology-group-hit')
      .attr('x', -96)
      .attr('y', -42)
      .attr('width', 192)
      .attr('height', 84)
      .attr('rx', 16)
      .attr('fill', 'transparent')
      .attr('stroke', 'none')
      .style('display', (d: any) => (d.is_group ? null : 'none'))
      .style('cursor', 'pointer');

    node.append('circle')
      .attr('r', 0)
      .attr('fill', 'rgba(248,250,252,0.96)')
      .attr('stroke', (d: any) => getNodeTone(d).stroke)
      .attr('stroke-width', 1.2)
      .attr('opacity', 0);

    node.append('circle')
      .attr('class', 'node-status-dot')
      .attr('r', (d: any) => (d.is_group ? 0 : 5.5))
      .attr('cx', 21)
      .attr('cy', -21)
      .attr('fill', (d: any) => getDeviceStatusColor(d as Device))
      .attr('stroke', '#ffffff')
      .attr('stroke-width', 1.5);

    node.append('circle')
      .attr('class', 'node-alert-dot')
      .attr('r', (d: any) => (d.is_group ? 0 : ((d.open_alert_count || 0) > 0 ? 6.0 : 0)))
      .attr('cx', -21)
      .attr('cy', -21)
      .attr('fill', (d: any) => ((d.critical_open_alerts || 0) > 0 ? '#dc2626' : '#f59e0b'))
      .attr('stroke', '#fff')
      .attr('stroke-width', 1.5)
      .attr('opacity', (d: any) => (d.is_group ? 0 : ((d.open_alert_count || 0) > 0 ? 1 : 0)));

    // Keep device glyphs fully legible even when another node is selected.
    // Focus mode still dims labels, links, and halos, but must not make a
    // healthy device icon look offline or disabled.
    const nodeGlyph = node.append('g').attr('opacity', 1);

    nodeGlyph.each(function (d: any) {
      if (d.is_group) {
        const tone = getLayerTone(d as Device);
        const group = d3.select(this).append('g').attr('transform', 'translate(-88,-34)');
        group.append('rect')
          .attr('width', 176)
          .attr('height', 68)
          .attr('rx', 14)
          .attr('fill', '#f8fafc')
          .attr('stroke', tone.color)
          .attr('stroke-width', 1.5)
          .attr('stroke-dasharray', '5,3');
        group.append('circle')
          .attr('cx', 15)
          .attr('cy', 17)
          .attr('r', 4)
          .attr('fill', getNodeTone(d as Device).fill);
        group.append('text')
          .attr('x', 26)
          .attr('y', 21)
          .attr('fill', '#0f172a')
          .attr('font-family', '"Segoe UI Variable Text", "Microsoft YaHei UI", sans-serif')
          .attr('font-size', '12px')
          .attr('font-weight', 800)
          .text(String(d.hostname || 'Group').slice(0, 24));
        group.append('text')
          .attr('x', 14)
          .attr('y', 41)
          .attr('fill', tone.color)
          .attr('font-family', '"Segoe UI Variable Text", "Microsoft YaHei UI", sans-serif')
          .attr('font-size', '10px')
          .attr('font-weight', 700)
          .text(`${d.group_member_count || 0} devices · ${d.group_online_count || 0} up`);
        group.append('text')
          .attr('x', 14)
          .attr('y', 56)
          .attr('fill', '#64748b')
          .attr('font-family', '"Segoe UI Variable Text", "Microsoft YaHei UI", sans-serif')
          .attr('font-size', '9px')
          .attr('font-weight', 600)
          .text(`${d.group_offline_count || 0} offline · ${d.group_alert_count || 0} alerts`);
      } else if (d.is_unmanaged) {
        // Render a "?" question mark for unmanaged devices
        d3.select(this).append('text')
          .attr('text-anchor', 'middle')
          .attr('dominant-baseline', 'central')
          .attr('fill', '#64748b')
          .attr('font-family', '"Segoe UI Variable Text", "Microsoft YaHei UI", sans-serif')
          .attr('font-size', '18px')
          .attr('font-weight', '700')
          .attr('pointer-events', 'none')
          .text('?');
      } else {
        appendDeviceGlyph(d3.select(this), d as Device);
      }
    });

    const nodeLabelGroup = node.append('g')
      .attr('transform', 'translate(0,39)')
      // Keep identity and layer text readable even while a node is focused.
      // Links and glyphs still provide focus context; fading labels makes
      // healthy devices look offline and is especially confusing in exports.
      .attr('opacity', 1)
      .style('display', (d: any) => (d.is_group ? 'none' : null));

    const boxWidth = 112;
    const boxHeight = 22;
    nodeLabelGroup.append('rect')
      .attr('x', -boxWidth / 2)
      .attr('y', -4)
      .attr('width', boxWidth)
      .attr('height', boxHeight)
      .attr('rx', 4)
      .attr('fill', '#ffffff')
      .attr('stroke', '#e2e8f0')
      .attr('stroke-width', 1.2)
      .attr('filter', 'url(#shadow)');

    const nodeHostnameText = nodeLabelGroup.append('text')
      .attr('y', 7.5)
      .attr('text-anchor', 'middle')
      .attr('dominant-baseline', 'middle')
      .attr('fill', (d: any) => (d.is_unmanaged ? '#64748b' : '#0f172a'))
      .attr('font-family', '"Segoe UI Variable Text", "Microsoft YaHei UI", "PingFang SC", "Noto Sans SC", sans-serif')
      .attr('font-size', '12.5px')
      .attr('font-weight', '800')
      .text((d: any) => String(d.hostname || '').toUpperCase());

    nodeLabelGroup.append('text')
      .attr('y', 31)
      .attr('text-anchor', 'middle')
      .attr('fill', (d: any) => getLayerTone(d as Device).color)
      .attr('font-family', '"Segoe UI Variable Text", "Microsoft YaHei UI", sans-serif')
      .attr('font-size', '9px')
      .attr('font-weight', '800')
      .attr('letter-spacing', '0.12em')
      .style('display', showNodeRoleLabels ? null : 'none')
      .attr('paint-order', 'stroke')
      .attr('stroke', '#ffffff')
      .attr('stroke-width', 2.5)
      .text((d: any) => getLayerTone(d as Device).label);

    node.append('title')
      .text((d: any) => {
        if (d.is_group) {
          return `${d.hostname} | ${d.group_member_count || 0} devices | ${d.group_online_count || 0} up | click to expand`;
        }
        const tone = getLayerTone(d as Device);
        const platform = String(d.platform || '').trim();
        const address = String(d.ip_address || '').trim();
        return [d.hostname, tone.label, platform, address].filter(Boolean).join(' | ');
      });

    const svgElement = svgRef.current;
    type SelectionInputEvent = MouseEvent | PointerEvent;
    const getSelectionEventId = (event: SelectionInputEvent) => 'pointerId' in event ? event.pointerId : 0;
    const getSelectionBox = (event: SelectionInputEvent) => {
      const [x, y] = d3.pointer(event, g.node() || svgElement);
      if (!selectionBoxStart) return null;
      return {
        x: Math.min(selectionBoxStart.x, x),
        y: Math.min(selectionBoxStart.y, y),
        width: Math.abs(x - selectionBoxStart.x),
        height: Math.abs(y - selectionBoxStart.y),
      };
    };
    const handleSelectionPointerDown = (event: SelectionInputEvent) => {
      if (event.button !== 0 || (!event.shiftKey && !shiftPressedRef.current && !boxSelectModeRef.current) || spacePressedRef.current) return;
      const target = event.target as Element | null;
      if (target?.closest?.('.topology-node')) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      const [x, y] = d3.pointer(event, g.node() || svgElement);
      selectionBoxStart = {
        x,
        y,
        pointerId: getSelectionEventId(event),
        additive: event.ctrlKey || event.metaKey,
      };
      selectionBoxRect
        .style('display', null)
        .attr('x', x)
        .attr('y', y)
        .attr('width', 0)
        .attr('height', 0);
      if ('pointerId' in event) svgElement?.setPointerCapture?.(event.pointerId);
    };
    const handleSelectionPointerMove = (event: SelectionInputEvent) => {
      if (!selectionBoxStart || getSelectionEventId(event) !== selectionBoxStart.pointerId) return;
      event.preventDefault();
      const box = getSelectionBox(event);
      if (!box) return;
      selectionBoxRect
        .attr('x', box.x)
        .attr('y', box.y)
        .attr('width', box.width)
        .attr('height', box.height);
    };
    const handleSelectionPointerUp = (event: SelectionInputEvent) => {
      if (!selectionBoxStart || getSelectionEventId(event) !== selectionBoxStart.pointerId) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      const box = getSelectionBox(event);
      if (box && (box.width > 6 || box.height > 6)) {
        const pickedIds = nodes
          .filter((item: any) => item.x >= box.x && item.x <= box.x + box.width && item.y >= box.y && item.y <= box.y + box.height)
          .map((item: any) => item.id);
        setSelectedNodeIds((current) => selectionBoxStart?.additive
          ? Array.from(new Set([...current, ...pickedIds]))
          : pickedIds);
      }
      selectionBoxRect.style('display', 'none');
      if ('pointerId' in event) svgElement?.releasePointerCapture?.(event.pointerId);
      selectionBoxStart = null;
    };
    svgElement?.addEventListener('pointerdown', handleSelectionPointerDown as EventListener, true);
    svgElement?.addEventListener('pointermove', handleSelectionPointerMove as EventListener, true);
    svgElement?.addEventListener('pointerup', handleSelectionPointerUp as EventListener, true);
    svgElement?.addEventListener('pointercancel', handleSelectionPointerUp as EventListener, true);
    svgElement?.addEventListener('mousedown', handleSelectionPointerDown as EventListener, true);
    svgElement?.addEventListener('mousemove', handleSelectionPointerMove as EventListener, true);
    svgElement?.addEventListener('mouseup', handleSelectionPointerUp as EventListener, true);
    window.addEventListener('mousemove', handleSelectionPointerMove as EventListener, true);
    window.addEventListener('mouseup', handleSelectionPointerUp as EventListener, true);

    const renderGraph = () => {
      nodes.forEach((node: any) => {
        node.x = clampPosition(node.x || width / 2, 48, width - 48);
        node.y = clampPosition(node.y || height / 2, 56, height - 56);
      });

      link
        .attr('d', (d: any, i: number) => getOrthogonalRoute(d.source, d.target, parallelOffsetMap.get(String(i)) || 0).path);

      linkHitArea
        .attr('d', (d: any, i: number) => getOrthogonalRoute(d.source, d.target, parallelOffsetMap.get(String(i)) || 0).path);

      linkLabelGroup
        .attr('transform', (d: any, i: number) => {
          const route = getOrthogonalRoute(d.source, d.target, parallelOffsetMap.get(String(i)) || 0);
          return `translate(${route.labelX},${route.labelY - 16})`;
        })
        .attr('opacity', (item: any) => {
          const isSelected = Boolean(selectedLinkKey && (item.link_key === selectedLinkKey || item.id === selectedLinkKey));
          if (isSelected) return 1;
          if (!hasFocus) return 0.96;
          return item.source.id === selectedNodeId || item.target.id === selectedNodeId ? 0.98 : 0.74;
        });

      portLabelGroup
        .attr('opacity', (item: any) => {
          if (!hasFocus) return 0.9;
          return item.source.id === selectedNodeId || item.target.id === selectedNodeId ? 0.95 : 0.68;
        });
      sourcePortLabel
        .attr('transform', (d: any, i: number) => {
          const offset = parallelOffsetMap.get(String(labelledLinks.indexOf(d))) || 0;
          const dx = d.target.x - d.source.x;
          const dy = d.target.y - d.source.y;
          const distance = Math.max(1, Math.hypot(dx, dy));
          const uX = dx / distance;
          const uY = dy / distance;
          const perpX = -dy / distance;
          const perpY = dx / distance;

          let x = d.source.x + uX * 44 + perpX * offset;
          let y = d.source.y + uY * 44 + perpY * offset;

          if (Math.abs(uY) < 0.4) {
            y -= 10;
          } else {
            x = d.source.x + (perpX > 0 ? 36 : -36) + perpX * offset;
            y = d.source.y + (uY > 0 ? 20 : -20) + perpY * offset;
          }
          return `translate(${x},${y})`;
        });
      targetPortLabel
        .attr('transform', (d: any, i: number) => {
          const offset = parallelOffsetMap.get(String(labelledLinks.indexOf(d))) || 0;
          const dx = d.target.x - d.source.x;
          const dy = d.target.y - d.source.y;
          const distance = Math.max(1, Math.hypot(dx, dy));
          const uX = dx / distance;
          const uY = dy / distance;
          const perpX = -dy / distance;
          const perpY = dx / distance;

          let x = d.target.x - uX * 44 + perpX * offset;
          let y = d.target.y - uY * 44 + perpY * offset;

          if (Math.abs(uY) < 0.4) {
            y -= 10;
          } else {
            x = d.target.x + (perpX < 0 ? 36 : -36) + perpX * offset;
            y = d.target.y + (-uY > 0 ? 20 : -20) + perpY * offset;
          }
          return `translate(${x},${y})`;
        });

      linkLabelBg.each(function () {
        const textNode = d3.select(this.nextSibling as SVGTextElement).node();
        if (!textNode) return;
        const bbox = textNode.getBBox();
        d3.select(this)
          .attr('x', bbox.x - 6)
          .attr('y', bbox.y - 4)
          .attr('width', bbox.width + 12)
          .attr('height', bbox.height + 8);
      });

      node
        .attr("transform", (d: any) => `translate(${d.x},${d.y})`);

      syncMinimap();
    };

    syncMinimap = (transform = zoomTransformRef.current || createDefaultTransform(width, height)) => {
      setMinimapSnapshot(buildMinimapSnapshot(nodes, d3Links, transform, width, height, selectedNodeId));
    };

    renderGraph();

    const initialTransform = !hasPersistedPositions && structuredPositions
      ? createDefaultTransform(width, height)
      : (zoomTransformRef.current || createDefaultTransform(width, height));
  suppressPersistRef.current = true;
    svg.call(zoom.transform as any, initialTransform);

    function dragstarted(event: any) {
      const [pointerX, pointerY] = getWorldPointer(event);
      const dragIds = selectedNodeIdSet.has(event.subject.id) && selectedNodeIdSet.size > 1
        ? Array.from(selectedNodeIdSet)
        : [event.subject.id];
      const initialPositions = Object.fromEntries(
        nodes
          .filter((item: any) => dragIds.includes(item.id))
          .map((item: any) => [item.id, { x: item.x, y: item.y }]),
      );
      dragStateRef.current = { id: event.subject.id, moved: false };
      dragBeforePositionsRef.current = clonePositions(persistedPositionsRef.current);
      dragGroupRef.current = {
        primaryId: event.subject.id,
        ids: dragIds,
        initialPositions,
      };
      dragOffset = {
        x: event.subject.x - pointerX,
        y: event.subject.y - pointerY,
      };
      event.sourceEvent?.stopPropagation?.();
      event.sourceEvent?.preventDefault?.();
      event.subject.fx = event.subject.x;
      event.subject.fy = event.subject.y;
      node.classed('topology-node-dragging', (item: any) => item.id === event.subject.id);
      linkLayer.style('opacity', 0.38);
      linkLabelGroup.style('opacity', 0.12);
      portLabelGroup.style('opacity', 0.12);
      svg.style('cursor', 'grabbing');
    }

    function dragged(event: any) {
      const [pointerX, pointerY] = getWorldPointer(event);
      const nextPrimaryX = pointerX + dragOffset.x;
      const nextPrimaryY = pointerY + dragOffset.y;
      const group = dragGroupRef.current;
      const primaryStart = group?.initialPositions[group.primaryId] || { x: event.subject.x, y: event.subject.y };
      const deltaX = nextPrimaryX - primaryStart.x;
      const deltaY = nextPrimaryY - primaryStart.y;
      const snapCoordinate = (value: number, min: number, max: number) => {
        const snapped = gridSnapRef.current ? Math.round(value / GRID_SIZE) * GRID_SIZE : value;
        return clampPosition(snapped, min, Math.max(min, max));
      };
      const movedDistance = Math.hypot(deltaX, deltaY);
      if (movedDistance > 3) {
        dragStateRef.current.moved = true;
      }
      const dragIds = group?.ids || [event.subject.id];
      nodes.forEach((item: any) => {
        if (!dragIds.includes(item.id)) return;
        const initial = group?.initialPositions[item.id] || { x: item.x, y: item.y };
        item.x = snapCoordinate(initial.x + deltaX, 48, width - 48);
        item.y = snapCoordinate(initial.y + deltaY, 56, height - 56);
        item.fx = item.x;
        item.fy = item.y;
        persistedPositionsRef.current[item.id] = { x: item.x, y: item.y };
      });
      renderGraph();
    }

    function dragended(event: any) {
      event.subject.fx = null;
      event.subject.fy = null;
      dragGroupRef.current?.ids.forEach((id) => {
        const item = nodes.find((nodeItem: any) => nodeItem.id === id);
        if (!item) return;
        (item as any).fx = null;
        (item as any).fy = null;
        persistedPositionsRef.current[id] = { x: item.x, y: item.y };
      });
      if (dragStateRef.current.moved) {
        suppressNextNodeClickRef.current = true;
        if (dragBeforePositionsRef.current) {
          recordLayoutHistory(dragBeforePositionsRef.current, persistedPositionsRef.current);
        }
        persistCurrentLayout();
      }
      dragStateRef.current = { id: null, moved: false };
      dragBeforePositionsRef.current = null;
      dragGroupRef.current = null;
      node.classed('topology-node-dragging', false);
      linkLayer.style('opacity', null);
      linkLabelGroup.style('opacity', null);
      portLabelGroup.style('opacity', null);
      svg.style('cursor', 'grab');
    }

    return () => {
      svgElement?.removeEventListener('pointerdown', handleSelectionPointerDown, true);
      svgElement?.removeEventListener('pointermove', handleSelectionPointerMove, true);
      svgElement?.removeEventListener('pointerup', handleSelectionPointerUp, true);
      svgElement?.removeEventListener('pointercancel', handleSelectionPointerUp, true);
      svgElement?.removeEventListener('mousedown', handleSelectionPointerDown as EventListener, true);
      svgElement?.removeEventListener('mousemove', handleSelectionPointerMove as EventListener, true);
      svgElement?.removeEventListener('mouseup', handleSelectionPointerUp as EventListener, true);
      window.removeEventListener('mousemove', handleSelectionPointerMove as EventListener, true);
      window.removeEventListener('mouseup', handleSelectionPointerUp as EventListener, true);
    };
  }, [graphDevices, graphLinks, layoutMode, onLinkClick, onNodeClick, selectedLinkKey, selectedNodeId, selectedNodeIdsKey, viewport.height, viewport.width, layoutVersion]);
  /* eslint-enable react-hooks/exhaustive-deps */

  return (
    <div ref={containerRef} className={`relative h-full w-full overflow-hidden rounded-[24px] border border-slate-200 bg-white shadow-inner ${spacePanActive ? 'topology-space-pan' : ''}`}>
      {devices.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center text-sm text-slate-500">
          No topology data available.
        </div>
      )}
      <div className={`pointer-events-none absolute left-4 top-4 z-10 rounded-xl border px-3 py-2 text-[10px] font-semibold tracking-wide backdrop-blur-sm ${spacePanActive ? 'border-cyan-300/50 bg-cyan-950/70 text-cyan-100' : 'border-slate-200 bg-white/95 text-slate-500 shadow-sm'}`}>
        空白区平移&nbsp;·&nbsp;节点拖动&nbsp;·&nbsp;框选模式或 Shift+空白框选&nbsp;·&nbsp;Space+拖动平移&nbsp;·&nbsp;滚轮缩放
      </div>
      <div className="absolute right-4 top-4 z-10 flex max-w-[calc(100%-2rem)] flex-wrap items-center justify-end gap-1.5 rounded-2xl border border-slate-200 bg-white/95 px-2.5 py-2 shadow-[0_10px_28px_rgba(15,23,42,0.12)] backdrop-blur-sm">
        <select
          value={layoutMode}
          onChange={(event) => changeLayoutMode(event.target.value as TopologyLayoutMode)}
          className="h-8 rounded-xl border border-slate-200 bg-white px-2 text-[10px] font-bold text-slate-600 outline-none transition-colors hover:border-cyan-300"
          aria-label="Layout mode"
          title="Hierarchy uses device roles; Horizontal is for linear chains; Force is for meshes; Radial is for hub-and-spoke views."
        >
          <option value="hierarchy">Hierarchy · roles</option>
          <option value="horizontal">Horizontal · chain</option>
          <option value="force">Force · mesh</option>
          <option value="radial">Radial · hub</option>
        </select>
        <select
          value={displayScope}
          onChange={(event) => {
            setExpandedGroupIds(new Set());
            setDrillPath([]);
            setDisplayScope(event.target.value as 'auto' | TopologyDisplayMode);
          }}
          className="h-8 rounded-xl border border-slate-200 bg-white px-2 text-[10px] font-bold text-slate-600 outline-none transition-colors hover:border-cyan-300"
          aria-label="Topology display scope"
          title="Automatically summarize large topologies, or switch to grouped and full-device views."
        >
          <option value="auto">Auto · {resolvedDisplayMode}</option>
          <option value="overview">Site overview</option>
          <option value="grouped">Grouped topology</option>
          <option value="detail">All devices</option>
        </select>
        {displayGraph.groups.length > 0 && (
          <button
            type="button"
            onClick={() => setExpandedGroupIds(new Set())}
            className="rounded-xl border border-violet-200 bg-violet-50 px-2.5 py-2 text-[10px] font-bold text-violet-700 transition-all hover:bg-violet-100"
            title="Collapse all topology groups"
          >
            {expandedGroupIds.size > 0 ? 'Collapse groups' : `${displayGraph.groups.length} groups`}
          </button>
        )}
        {drillPath.length > 0 && (
          <div className="flex max-w-[360px] items-center gap-1 overflow-x-auto rounded-xl border border-cyan-100 bg-cyan-50 px-2 py-1">
            <button type="button" onClick={resetDrillPath} className="shrink-0 text-[10px] font-extrabold text-cyan-700 hover:text-cyan-900">全部</button>
            {drillPath.map((segment, index) => (
              <React.Fragment key={`${segment.level}:${segment.key}`}>
                <span className="shrink-0 text-[10px] text-cyan-400">/</span>
                <button
                  type="button"
                  onClick={() => jumpToDrillPath(index + 1)}
                  className="max-w-[140px] shrink-0 truncate text-[10px] font-bold text-cyan-700 hover:text-cyan-900"
                  title={`${segment.level}: ${segment.label}`}
                >
                  {segment.label}
                </button>
              </React.Fragment>
            ))}
          </div>
        )}
        {graphDevices.length !== devices.length && (
          <span className="rounded-xl border border-slate-200 bg-slate-50 px-2.5 py-2 text-[10px] font-semibold text-slate-500">
            {graphDevices.length} visible / {devices.length} total
          </span>
        )}
        <button
          type="button"
          onClick={() => applyAutoLayout()}
          className="rounded-xl border border-cyan-200 bg-cyan-50 px-2.5 py-2 text-[10px] font-bold text-cyan-700 transition-all hover:border-cyan-300 hover:bg-cyan-100"
          aria-label="自动布局"
        >
          自动布局
        </button>
        <button
          type="button"
          onClick={() => { setGridSnapEnabled((value) => !value); }}
          className={`rounded-xl border px-2.5 py-2 text-[10px] font-bold transition-all ${gridSnapEnabled ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-slate-200 text-slate-500 hover:bg-slate-50'}`}
          aria-label="网格吸附"
          aria-pressed={gridSnapEnabled}
        >
          网格吸附
        </button>
        <button
          type="button"
          onClick={() => { setBoxSelectMode((value) => !value); }}
          className={`rounded-xl border px-2.5 py-2 text-[10px] font-bold transition-all ${boxSelectMode ? 'border-violet-200 bg-violet-50 text-violet-700' : 'border-slate-200 text-slate-500 hover:bg-slate-50'}`}
          aria-label="框选模式"
          aria-pressed={boxSelectMode}
        >
          框选
        </button>
        <button
          type="button"
          onClick={() => persistCurrentLayout()}
          className="rounded-xl border border-slate-200 px-2.5 py-2 text-[10px] font-bold text-slate-600 transition-all hover:border-cyan-300 hover:bg-slate-50"
          aria-label="保存布局"
        >
          保存
        </button>
        <button
          type="button"
          onClick={undoLayout}
          disabled={!historyState.canUndo}
          className="h-8 w-8 rounded-xl border border-slate-200 text-sm font-bold text-slate-600 transition-all hover:border-cyan-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-30"
          aria-label="撤销布局"
        >
          ↶
        </button>
        <button
          type="button"
          onClick={redoLayout}
          disabled={!historyState.canRedo}
          className="h-8 w-8 rounded-xl border border-slate-200 text-sm font-bold text-slate-600 transition-all hover:border-cyan-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-30"
          aria-label="恢复布局"
        >
          ↷
        </button>
        <span className="min-w-[54px] text-center text-[10px] font-semibold text-slate-500">
          已选 {selectedNodeIds.length}
        </span>
        <button
          type="button"
          onClick={() => setSelectedNodeIds([])}
          disabled={selectedNodeIds.length === 0}
          className="rounded-xl border border-slate-200 px-2.5 py-2 text-[10px] font-bold text-slate-600 transition-all hover:border-cyan-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-30"
          aria-label="清除选择"
        >
          清除
        </button>
        <button
          type="button"
          onClick={() => zoomAroundViewportCenter(0.88)}
          className="h-8 w-8 rounded-xl border border-slate-200 text-sm font-bold text-slate-600 transition-all hover:border-cyan-300 hover:bg-slate-50"
          aria-label="Zoom out"
        >
          -
        </button>
        <span className="min-w-[52px] text-center text-[11px] font-bold uppercase tracking-[0.14em] text-slate-600">
          {zoomPercent}%
        </span>
        <button
          type="button"
          onClick={() => zoomAroundViewportCenter(1.14)}
          className="h-8 w-8 rounded-xl border border-slate-200 text-sm font-bold text-slate-600 transition-all hover:border-cyan-300 hover:bg-slate-50"
          aria-label="Zoom in"
        >
          +
        </button>
        <button
          type="button"
          onClick={fitViewport}
          className="rounded-xl border border-slate-200 px-3 py-2 text-[11px] font-bold uppercase tracking-[0.12em] text-slate-600 transition-all hover:border-cyan-300 hover:bg-slate-50"
          aria-label="Fit"
        >
          Fit
        </button>
        <button
          type="button"
          onClick={resetLayout}
          className="rounded-xl border border-slate-200 px-3 py-2 text-[11px] font-bold uppercase tracking-[0.12em] text-slate-600 transition-all hover:border-cyan-300 hover:bg-slate-50"
          aria-label="Reset"
        >
          Reset
        </button>
        <button
          type="button"
          onClick={toggleFullscreen}
          className="rounded-xl border border-slate-200 px-3 py-2 text-[11px] font-bold uppercase tracking-[0.12em] text-slate-600 transition-all hover:border-cyan-300 hover:bg-slate-50"
          aria-label="Fullscreen"
        >
          {isFullscreen ? '窗口' : '全屏'}
        </button>
        <button
          type="button"
          onClick={exportSvg}
          className="rounded-xl border border-slate-200 px-3 py-2 text-[11px] font-bold uppercase tracking-[0.12em] text-slate-600 transition-all hover:border-cyan-300 hover:bg-slate-50"
          aria-label="Export SVG"
        >
          SVG
        </button>
        <button
          type="button"
          onClick={exportPng}
          className="rounded-xl border border-slate-200 px-3 py-2 text-[11px] font-bold uppercase tracking-[0.12em] text-slate-600 transition-all hover:border-cyan-300 hover:bg-slate-50"
          aria-label="Export PNG"
        >
          PNG
        </button>
      </div>

      {minimapSnapshot && (
        <div className="absolute bottom-4 right-4 z-10 overflow-hidden rounded-[22px] border border-white/10 bg-slate-950/80 p-3 shadow-[0_18px_42px_rgba(0,0,0,0.28)] backdrop-blur-sm">
          <div className="mb-2 flex items-center justify-between gap-3">
            <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-300">Navigator</span>
            <span className="text-[10px] font-semibold text-slate-500">Click to recenter</span>
          </div>
          <svg
            width={minimapSnapshot.panel.width}
            height={minimapSnapshot.panel.height}
            viewBox={`0 0 ${minimapSnapshot.panel.width} ${minimapSnapshot.panel.height}`}
            className="cursor-pointer rounded-2xl bg-[linear-gradient(180deg,#16253a_0%,#0e192b_100%)]"
            onClick={handleMinimapClick}
          >
            <rect x="0" y="0" width={minimapSnapshot.panel.width} height={minimapSnapshot.panel.height} rx="18" fill="transparent" />
            {minimapSnapshot.links.map((link) => (
              <line
                key={link.id}
                x1={link.sourceX}
                y1={link.sourceY}
                x2={link.targetX}
                y2={link.targetY}
                stroke={link.color}
                strokeOpacity="0.72"
                strokeWidth={link.width}
              />
            ))}
            {minimapSnapshot.nodes.map((node) => (
              <circle
                key={node.id}
                cx={node.x}
                cy={node.y}
                r={node.selected ? 4.6 : 3.3}
                fill={node.fill}
                stroke={node.selected ? '#0f172a' : 'rgba(255,255,255,0.95)'}
                strokeWidth={node.selected ? 1.5 : 1}
              />
            ))}
            <rect
              x={minimapSnapshot.viewport.x}
              y={minimapSnapshot.viewport.y}
              width={Math.min(minimapSnapshot.viewport.width, minimapSnapshot.panel.width)}
              height={Math.min(minimapSnapshot.viewport.height, minimapSnapshot.panel.height)}
              rx="8"
              fill="rgba(14,165,233,0.08)"
              stroke="rgba(2,132,199,0.9)"
              strokeWidth="1.5"
            />
          </svg>
        </div>
      )}
      {hoveredDevice && (
        <div
          className="pointer-events-auto absolute z-30 w-[220px] rounded-2xl border border-slate-200 bg-white/98 p-3 shadow-[0_18px_45px_rgba(15,23,42,0.22)] backdrop-blur-sm"
          style={{ left: hoverCardPosition.x, top: hoverCardPosition.y }}
          onPointerEnter={clearHoverHideTimer}
          onPointerLeave={scheduleHoverCardHide}
        >
          <div className="border-b border-slate-100 pb-2.5">
            <div className="truncate text-sm font-extrabold text-slate-900" title={hoveredDevice.hostname}>{hoveredDevice.hostname}</div>
            <div className="mt-1 flex items-center gap-1.5 text-[10px] font-bold tracking-[0.08em] text-sky-700">
              <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: getLayerTone(hoveredDevice).color }} />
              {hoveredDevice.is_group ? `${getLayerTone(hoveredDevice).label} GROUP` : getLayerTone(hoveredDevice).label}
            </div>
          </div>
          {hoveredDevice.is_group ? (
            <dl className="mt-2.5 space-y-2 text-[10px]">
              <div><dt className="font-semibold text-slate-400">Members</dt><dd className="mt-0.5 font-bold text-slate-700">{hoveredDevice.group_member_count || 0}</dd></div>
              <div><dt className="font-semibold text-slate-400">Health</dt><dd className="mt-0.5 font-bold text-slate-700">{hoveredDevice.group_online_count || 0} up · {hoveredDevice.group_offline_count || 0} offline</dd></div>
              <div><dt className="font-semibold text-slate-400">Alerts</dt><dd className="mt-0.5 font-bold text-slate-700">{hoveredDevice.group_alert_count || 0}</dd></div>
            </dl>
          ) : (
          <dl className="mt-2.5 space-y-2 text-[10px]">
            <div>
              <dt className="font-semibold uppercase tracking-[0.12em] text-slate-400">管理地址</dt>
              <dd className="mt-0.5 break-all font-mono font-bold text-slate-700">{hoveredDevice.ip_address || '-'}</dd>
            </div>
            <div>
              <dt className="font-semibold uppercase tracking-[0.12em] text-slate-400">品牌 / 型号</dt>
              <dd className="mt-0.5 break-all font-semibold text-slate-700">
                {String(hoveredDevice.vendor || hoveredDevice.platform || 'CISCO').toUpperCase()} / {hoveredDevice.model || 'Standard Switch'}
              </dd>
            </div>
            <div>
              <dt className="font-semibold uppercase tracking-[0.12em] text-slate-400">CPU 使用率</dt>
              <dd className="mt-0.5 font-bold text-slate-700">
                {hoveredDevice.cpu_usage !== undefined && hoveredDevice.cpu_usage !== null
                  ? `${typeof hoveredDevice.cpu_usage === 'number' ? hoveredDevice.cpu_usage.toFixed(1) : parseFloat(hoveredDevice.cpu_usage as any).toFixed(1)}%`
                  : '0.0%'}
              </dd>
            </div>
            <div>
              <dt className="font-semibold uppercase tracking-[0.12em] text-slate-400">内存使用率</dt>
              <dd className="mt-0.5 font-bold text-slate-700">
                {hoveredDevice.memory_usage !== undefined && hoveredDevice.memory_usage !== null
                  ? `${typeof hoveredDevice.memory_usage === 'number' ? hoveredDevice.memory_usage.toFixed(1) : parseFloat(hoveredDevice.memory_usage as any).toFixed(1)}%`
                  : '0.0%'}
              </dd>
            </div>
            <div>
              <dt className="font-semibold uppercase tracking-[0.12em] text-slate-400">持续运行时间 (Uptime)</dt>
              <dd className="mt-0.5 font-semibold text-slate-700">{hoveredDevice.uptime || '-'}</dd>
            </div>
            {(hoveredDevice.site_state_province || hoveredDevice.site_city || hoveredDevice.site_district || hoveredDevice.region) && (
              <div>
                <dt className="font-semibold uppercase tracking-[0.12em] text-slate-400">区域</dt>
                <dd className="mt-0.5 break-all font-semibold text-slate-700">
                  {hoveredDevice.region || [hoveredDevice.site_state_province, hoveredDevice.site_city, hoveredDevice.site_district].filter(Boolean).join(' / ')}
                </dd>
              </div>
            )}
          </dl>
          )}
          <button
            type="button"
            disabled={!hoveredDevice.is_group && !onOpenWorkspace}
            onClick={(event) => {
              event.stopPropagation();
              if (hoveredDevice.is_group) {
                toggleGroup(hoveredDevice);
                return;
              }
              if (!onOpenWorkspace) return;
              clearHoverHideTimer();
              setHoveredDeviceId(null);
              onOpenWorkspace(hoveredDevice);
            }}
            className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-xl bg-sky-600 px-3 py-2 text-[10px] font-extrabold text-white shadow-sm transition-colors hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {hoveredDevice.is_group ? (hoveredDevice.group_can_drill ? '进入下一级' : '展开设备') : '登录'}
          </button>
        </div>
      )}
      {hoveredLink && (
        <div
          className="pointer-events-auto absolute z-30 w-[240px] rounded-2xl border border-slate-200 bg-white/98 p-3 shadow-[0_18px_45px_rgba(15,23,42,0.22)] backdrop-blur-sm"
          style={{ left: hoverCardPosition.x, top: hoverCardPosition.y }}
          onPointerEnter={clearHoverHideTimer}
          onPointerLeave={scheduleHoverCardHide}
        >
          <div className="border-b border-slate-100 pb-2.5">
            <div className="truncate text-sm font-extrabold text-slate-900">链路详情</div>
            <div className="mt-1 flex items-center gap-1.5 text-[10px] font-bold tracking-[0.08em] text-sky-700">
              {hoveredLink.link_kind === 'aggregation' ? '聚合链路 (LAG)' : '物理链路'}
            </div>
          </div>
          <dl className="mt-2.5 space-y-2 text-[10px]">
            <div>
              <dt className="font-semibold uppercase tracking-[0.12em] text-slate-400">本端设备及接口</dt>
              <dd className="mt-0.5 font-bold text-slate-700">
                {hoveredLink.source_hostname || (hoveredLink.source as any)?.hostname || '-'} · {hoveredLink.source_port || hoveredLink.source_port_normalized || '-'}
              </dd>
            </div>
            <div>
              <dt className="font-semibold uppercase tracking-[0.12em] text-slate-400">对端设备及接口</dt>
              <dd className="mt-0.5 font-bold text-slate-700">
                {hoveredLink.target_hostname || (hoveredLink.target as any)?.hostname || '-'} · {hoveredLink.target_port || hoveredLink.target_port_normalized || '-'}
              </dd>
            </div>
            <div>
              <dt className="font-semibold uppercase tracking-[0.12em] text-slate-400">链路带宽</dt>
              <dd className="mt-0.5 font-bold text-slate-700">
                {getBandwidthTier(hoveredLink.bandwidth_mbps || hoveredLink.aggregation_bandwidth_mbps).label}
              </dd>
            </div>
            <div>
              <dt className="font-semibold uppercase tracking-[0.12em] text-slate-400">双工模式 (Duplex)</dt>
              <dd className="mt-0.5 font-semibold text-slate-700">Full Duplex (自协商)</dd>
            </div>
            <div>
              <dt className="font-semibold uppercase tracking-[0.12em] text-slate-400">所属 VLAN</dt>
              <dd className="mt-0.5 font-semibold text-slate-700">VLAN 1 (Default)</dd>
            </div>
            <div>
              <dt className="font-semibold uppercase tracking-[0.12em] text-slate-400">CRC/错误包</dt>
              <dd className="mt-0.5 font-semibold text-emerald-600">0 (正常)</dd>
            </div>
          </dl>
        </div>
      )}
      <svg ref={svgRef} className="topology-graph-svg h-full w-full" />
    </div>
  );
};

export default TopologyGraph;
