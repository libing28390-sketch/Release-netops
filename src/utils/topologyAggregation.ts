export type TopologyDisplayMode = 'overview' | 'grouped' | 'detail';
export type TopologyHierarchyLevel = 'site' | 'region' | 'floor' | 'rack' | 'layer';

export interface TopologyDrillSegment {
  level: TopologyHierarchyLevel;
  key: string;
  label: string;
}

export interface TopologyAggregationDevice {
  id: string;
  hostname: string;
  ip_address: string;
  status: string;
  role: string;
  platform?: string;
  model?: string;
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

export interface TopologyAggregationLink {
  source_device_id: string;
  target_device_id: string;
  source_port?: string;
  target_port?: string;
  source_port_normalized?: string;
  target_port_normalized?: string;
  link_key?: string;
  id?: string;
  group_link?: boolean;
  source_is_group?: boolean;
  target_is_group?: boolean;
  grouped_link_count?: number;
}

export interface TopologyAggregationResult<
  TDevice extends TopologyAggregationDevice,
  TLink extends TopologyAggregationLink,
> {
  devices: TDevice[];
  links: TLink[];
  groups: TDevice[];
  mode: TopologyDisplayMode;
  expandedGroupIds: string[];
}

const layerForDevice = (device: TopologyAggregationDevice) => {
  const fingerprint = [device.role, device.hostname, device.model, device.platform]
    .map((value) => String(value || '').toLowerCase())
    .join(' ');
  if (/(firewall|fortigate|forti|palo|pan-|checkpoint|srx|asa|ftd|\bfw\b)/.test(fingerprint)) return 'PERIMETER';
  if (/(router|gateway|wan|edge router|\bisr\b|\basr\b|\bmx\b)/.test(fingerprint)) return 'PERIMETER';
  if (/(core|backbone|spine|leaf-spine)/.test(fingerprint)) return 'CORE';
  if (/(distribution|aggregation|agg)/.test(fingerprint)) return 'AGGREGATION';
  if (/(access|edge|acc[-_ ]?sw)/.test(fingerprint)) return 'ACCESS';
  return 'DEVICE';
};

const layerRank: Record<string, number> = { PERIMETER: 0, CORE: 1, AGGREGATION: 2, ACCESS: 3, DEVICE: 4 };

const getSite = (device: TopologyAggregationDevice) => {
  const id = String(device.site_id || device.site || '').trim();
  return id || 'Unassigned';
};

const getSiteLabel = (device: TopologyAggregationDevice) => String(device.site || '').trim() || 'Unassigned';

const normalizeValue = (value: unknown) => String(value || '').trim();
const fallbackKey = (value: string) => value.toLocaleLowerCase().replace(/\s+/g, ' ');

const getHierarchySegment = (
  device: TopologyAggregationDevice,
  level: TopologyHierarchyLevel,
): TopologyDrillSegment => {
  if (level === 'site') {
    const label = getSiteLabel(device);
    return { level, key: getSite(device), label };
  }
  if (level === 'region') {
    const label = normalizeValue(device.region)
      || [device.site_state_province, device.site_city, device.site_district]
        .map(normalizeValue).filter(Boolean).join(' / ')
      || 'Unassigned region';
    return { level, key: fallbackKey(label), label };
  }
  if (level === 'floor') {
    const label = normalizeValue(device.floor) || normalizeValue(device.rack_floor) || 'Unassigned floor';
    return { level, key: fallbackKey(label), label };
  }
  if (level === 'rack') {
    const label = normalizeValue(device.rack_name) || normalizeValue(device.rack_code)
      || normalizeValue(device.rack) || 'Unassigned rack';
    const key = normalizeValue(device.rack_id) || fallbackKey(label);
    return { level, key, label };
  }
  const label = layerForDevice(device);
  return { level, key: label.toLowerCase(), label };
};

const hasHierarchyValue = (device: TopologyAggregationDevice, level: TopologyHierarchyLevel) => {
  if (level === 'site' || level === 'layer') return true;
  if (level === 'region') return Boolean(
    normalizeValue(device.region) || normalizeValue(device.site_state_province)
      || normalizeValue(device.site_city) || normalizeValue(device.site_district),
  );
  if (level === 'floor') return Boolean(normalizeValue(device.floor) || normalizeValue(device.rack_floor));
  return Boolean(normalizeValue(device.rack_id) || normalizeValue(device.rack_code)
    || normalizeValue(device.rack_name) || normalizeValue(device.rack));
};

const hierarchyOrder: TopologyHierarchyLevel[] = ['site', 'region', 'floor', 'rack', 'layer'];

export const getTopologyHierarchyPath = (device: TopologyAggregationDevice): TopologyDrillSegment[] =>
  hierarchyOrder.map((level) => getHierarchySegment(device, level));

const matchesDrillPath = (device: TopologyAggregationDevice, drillPath: TopologyDrillSegment[]) => {
  const path = getTopologyHierarchyPath(device);
  return drillPath.every((segment) => {
    const actual = path.find((item) => item.level === segment.level);
    return actual?.level === segment.level && actual.key === segment.key;
  });
};

const nextHierarchyLevel = (
  devices: TopologyAggregationDevice[],
  drillPath: TopologyDrillSegment[],
): TopologyHierarchyLevel | null => {
  const lastIndex = drillPath.length ? hierarchyOrder.indexOf(drillPath[drillPath.length - 1].level) : -1;
  return hierarchyOrder.slice(lastIndex + 1).find((level) => devices.some((device) => hasHierarchyValue(device, level))) || null;
};

export const getTopologyHierarchyAvailability = (devices: TopologyAggregationDevice[]) =>
  hierarchyOrder.map((level) => ({
    level,
    available: devices.some((device) => hasHierarchyValue(device, level)),
  }));

export const resolveTopologyDisplayMode = (
  deviceCount: number,
  requested: 'auto' | TopologyDisplayMode,
): TopologyDisplayMode => {
  if (requested !== 'auto') return requested;
  if (deviceCount > 80) return 'overview';
  if (deviceCount > 15) return 'grouped';
  return 'detail';
};

export const aggregateTopologyGraph = <
  TDevice extends TopologyAggregationDevice,
  TLink extends TopologyAggregationLink,
>(
  devices: TDevice[],
  links: TLink[],
  mode: TopologyDisplayMode,
  expandedGroupIds: Set<string>,
  drillPath: TopologyDrillSegment[] = [],
): TopologyAggregationResult<TDevice, TLink> => {
  if (mode === 'detail' || devices.length === 0) {
    return { devices, links, groups: [], mode, expandedGroupIds: [] };
  }

  const scopedDevices = devices.filter((device) => matchesDrillPath(device, drillPath));
  const groupLevel = nextHierarchyLevel(scopedDevices, drillPath);
  if (!groupLevel) {
    return { devices: scopedDevices, links: links.filter((link) => scopedDevices.some((device) => device.id === link.source_device_id) && scopedDevices.some((device) => device.id === link.target_device_id)), groups: [], mode, expandedGroupIds: [] };
  }

  const groupsByKey = new Map<string, TDevice[]>();
  scopedDevices.forEach((device) => {
    const segment = getHierarchySegment(device, groupLevel);
    const key = `${segment.level}:${segment.key}`;
    const current = groupsByKey.get(key) || [];
    current.push(device);
    groupsByKey.set(key, current);
  });

  const expanded = new Set<string>();
  const renderDevices: TDevice[] = [];
  const endpointMap = new Map<string, string>();
  const groupNodes: TDevice[] = [];

  groupsByKey.forEach((members, key) => {
    if (members.length <= 1) {
      const member = members[0];
      renderDevices.push(member);
      endpointMap.set(member.id, member.id);
      return;
    }

    const groupId = `group:${mode}:${drillPath.map((segment) => `${segment.level}:${segment.key}`).join('|')}:${key}`;
    const segment = getHierarchySegment(members[0], groupLevel);
    const siteLabel = getSiteLabel(members[0]);
    const layer = members
      .map(layerForDevice)
      .sort((left, right) => (layerRank[left] ?? 9) - (layerRank[right] ?? 9))[0];
    const online = members.filter((member) => String(member.status).toLowerCase() === 'online').length;
    const offline = members.filter((member) => String(member.status).toLowerCase() === 'offline').length;
    const warning = members.filter((member) => String(member.health_status || '').toLowerCase() === 'warning').length;
    const alerts = members.reduce((total, member) => total + Number(member.open_alert_count || 0), 0);
    const group = {
      ...members[0],
      id: groupId,
      hostname: segment.label,
      ip_address: '',
      role: `${layer} GROUP`,
      platform: 'topology-group',
      model: 'topology-group',
      site: siteLabel,
      site_id: members[0].site_id || members[0].site,
      status: offline === members.length ? 'offline' : online === members.length ? 'online' : 'pending',
      health_status: offline > 0 || warning > 0 ? 'warning' : 'healthy',
      open_alert_count: alerts,
      is_group: true,
      group_id: groupId,
      group_label: segment.level.toUpperCase(),
      group_site: siteLabel,
      group_layer: layer,
      group_level: segment.level,
      group_path: [...drillPath, segment],
      group_can_drill: nextHierarchyLevel(members, [...drillPath, segment]) !== null,
      group_member_count: members.length,
      group_online_count: online,
      group_offline_count: offline,
      group_warning_count: warning,
      group_alert_count: alerts,
      group_member_ids: members.map((member) => member.id),
    } as TDevice;
    groupNodes.push(group);
    if (expandedGroupIds.has(groupId)) {
      expanded.add(groupId);
      members.forEach((member) => {
        renderDevices.push(member);
        endpointMap.set(member.id, member.id);
      });
      return;
    }
    renderDevices.push(group);
    members.forEach((member) => endpointMap.set(member.id, groupId));
  });

  const aggregatedLinks = new Map<string, TLink>();
  links.forEach((link, index) => {
    const source = endpointMap.get(link.source_device_id);
    const target = endpointMap.get(link.target_device_id);
    if (!source || !target || source === target) return;
    const pair = [source, target].sort().join('::');
    const existing = aggregatedLinks.get(pair);
    if (existing) {
      existing.grouped_link_count = Number(existing.grouped_link_count || 1) + 1;
      existing.group_link = true;
      return;
    }
    aggregatedLinks.set(pair, {
      ...link,
      id: `grouped-link:${mode}:${pair}:${index}`,
      link_key: `grouped-link:${mode}:${pair}`,
      source_device_id: source,
      target_device_id: target,
      source_port: source.startsWith('group:') ? '' : link.source_port,
      target_port: target.startsWith('group:') ? '' : link.target_port,
      source_port_normalized: source.startsWith('group:') ? '' : link.source_port_normalized,
      target_port_normalized: target.startsWith('group:') ? '' : link.target_port_normalized,
      group_link: source.startsWith('group:') || target.startsWith('group:'),
      source_is_group: source.startsWith('group:'),
      target_is_group: target.startsWith('group:'),
      grouped_link_count: 1,
    } as TLink);
  });

  return {
    devices: renderDevices,
    links: Array.from(aggregatedLinks.values()),
    groups: groupNodes,
    mode,
    expandedGroupIds: Array.from(expanded),
  };
};
