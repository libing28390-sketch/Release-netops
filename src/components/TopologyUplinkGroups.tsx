import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowUpRight, ChevronDown, GitFork, Network, RadioTower, Wifi } from 'lucide-react';
import type { Device } from '../types';
import { getBuiltInTopologyIconUrl, getTopologyDeviceIconType } from '../domain/topologyDeviceIcons';
import { topologyRoleLabel, topologyRoleVisualTier } from '../domain/topologyRoles';
import { useTopologyIcons } from '../hooks/useTopologyIcons';
import type { TopologyDecoratedLink } from '../hooks/useTopology';
import { topologyDeviceRole } from '../utils/topologyRoleLayout';
import { formatTopologyLinkUtilization, getTopologyLinkLoadTier, getTopologyLinkUtilization, TOPOLOGY_LINK_LOAD_TIERS } from '../utils/topologyLinkLoad';
import './TopologyUplinkGroups.css';

type TopologyUplinkLink = Pick<TopologyDecoratedLink, 'source_device_id' | 'target_device_id'>
  & Partial<Pick<TopologyDecoratedLink,
    | 'id'
    | 'link_key'
    | 'source_port'
    | 'source_port_normalized'
    | 'target_port'
    | 'target_port_normalized'
    | 'relation_type'
    | 'semantic_relation'
    | 'inferred'
    | 'is_inferred'
    | 'is_unmanaged'
    | 'link_kind'
    | 'operational_state'
  >> & {
  source_interface_snapshot?: unknown;
  target_interface_snapshot?: unknown;
};

type TopologyUplinkParent = {
  device: Device;
  links: TopologyUplinkLink[];
};

export type TopologyUplinkGroup = {
  id: string;
  parents: Device[];
  devices: Device[];
};

type TopologyUplinkGrouping = {
  accessGroups: TopologyUplinkGroup[];
  wirelessGroups: TopologyUplinkGroup[];
  upstreams: Map<string, TopologyUplinkParent[]>;
  physicalLinkCount: number;
  inferredLinkCount: number;
};

type TopologyUplinkPath = {
  devices: Device[];
  links: TopologyUplinkLink[];
};

type DiagramPoint = {
  x: number;
  y: number;
};

type DiagramEdge = {
  id: string;
  from: DiagramPoint;
  to: DiagramPoint;
  links: TopologyUplinkLink[];
  focused: boolean;
};

const UPLINK_PATH_COLORS = ['#215bd6', '#8b3bd1', '#00847e', '#b45309', '#be185d', '#526819'];
const uplinkPathColor = (index: number) => UPLINK_PATH_COLORS[index]
  ?? `hsl(${Math.round(index * 137.508) % 360} 72% 36%)`;
const uplinkPathLabel = (index: number) => index < 26 ? String.fromCharCode(65 + index) : String(index + 1);

type AccessPointColumn = {
  id: string;
  accessGroupId: string | null;
  devices: Device[];
};

const isTruthy = (value: unknown): boolean => (
  value === true || value === 1 || ['1', 'true', 'yes'].includes(String(value || '').trim().toLowerCase())
);

const roleOf = (device: Device): string => topologyDeviceRole(device);
const isWirelessEndpoint = (device: Device): boolean => ['wireless_ap', 'wireless_controller'].includes(roleOf(device));
const isAccessDevice = (device: Device): boolean => ['access', 'switch'].includes(roleOf(device));

const compareText = (leftValue: string, rightValue: string): number => {
  const leftParts = String(leftValue).normalize('NFC').toLowerCase().match(/\d+|\D+/gu) || [];
  const rightParts = String(rightValue).normalize('NFC').toLowerCase().match(/\d+|\D+/gu) || [];
  const sharedLength = Math.min(leftParts.length, rightParts.length);
  for (let index = 0; index < sharedLength; index += 1) {
    const leftPart = leftParts[index];
    const rightPart = rightParts[index];
    const bothNumeric = /^\d+$/u.test(leftPart) && /^\d+$/u.test(rightPart);
    if (bothNumeric) {
      const numericDifference = Number(leftPart) - Number(rightPart);
      if (numericDifference) return numericDifference;
      if (leftPart.length !== rightPart.length) return leftPart.length - rightPart.length;
    } else if (leftPart !== rightPart) {
      return leftPart < rightPart ? -1 : 1;
    }
  }
  return leftParts.length - rightParts.length;
};

const compareDevices = (left: Device, right: Device): number => (
  compareText(String(left.hostname || left.id), String(right.hostname || right.id))
  || compareText(left.id, right.id)
);

const isPhysicalLinkShape = (link: TopologyUplinkLink): boolean => {
  const relation = String(link.relation_type || link.semantic_relation || '').trim().toUpperCase();
  const kind = String(link.link_kind || '').trim().toLowerCase();
  if (isTruthy(link.is_unmanaged)) return false;
  if (relation && relation !== 'PHYSICAL') return false;
  if (kind && kind !== 'physical' && kind !== 'aggregation') return false;
  // Older physical read-model rows do not carry relation_type or link_kind.
  return true;
};

const isPhysicalLink = (link: TopologyUplinkLink): boolean => (
  isPhysicalLinkShape(link) && !isTruthy(link.inferred) && !isTruthy(link.is_inferred)
);

const sortParents = (parents: Device[]): Device[] => [...parents].sort((left, right) => {
  const leftTier = topologyRoleVisualTier(roleOf(left)) ?? Number.MAX_SAFE_INTEGER;
  const rightTier = topologyRoleVisualTier(roleOf(right)) ?? Number.MAX_SAFE_INTEGER;
  return leftTier - rightTier || compareDevices(left, right);
});

const groupDevicesByParents = (devices: Device[], upstreams: Map<string, TopologyUplinkParent[]>, keyPrefix: string): TopologyUplinkGroup[] => {
  const groups = new Map<string, TopologyUplinkGroup>();
  devices.forEach((device) => {
    const parents = upstreams.get(device.id)?.map((item) => item.device) || [];
      const parentIds = parents.map((parent) => parent.id).sort(compareText);
    const id = `${keyPrefix}:${parentIds.length ? parentIds.join('|') : 'unconfirmed'}`;
    const group = groups.get(id) || { id, parents: sortParents(parents), devices: [] };
    group.devices.push(device);
    groups.set(id, group);
  });

  return Array.from(groups.values()).map((group) => ({
    ...group,
    devices: group.devices.sort(compareDevices),
  })).sort((left, right) => {
    if (left.parents.length === 0 || right.parents.length === 0) {
      if (left.parents.length !== right.parents.length) return left.parents.length === 0 ? 1 : -1;
    }
    return compareDevices(left.parents[0], right.parents[0])
      || left.parents.map((parent) => parent.id).join('|').localeCompare(right.parents.map((parent) => parent.id).join('|'))
      || left.id.localeCompare(right.id);
  });
};

/**
 * Build groups only from direct, non-inferred physical link evidence. The
 * role tiers provide direction for access-switch uplinks; AP/WLC parents are
 * the directly wired non-wireless peers.
 */
export const buildTopologyUplinkGrouping = (devices: Device[], links: TopologyUplinkLink[]): TopologyUplinkGrouping => {
  const deviceById = new Map(devices.map((device) => [device.id, device]));
  const physicalLinks = links.filter(isPhysicalLink);
  const inferredLinkCount = links.filter((link) => (
    isPhysicalLinkShape(link) && (isTruthy(link.inferred) || isTruthy(link.is_inferred))
  )).length;
  const adjacent = new Map<string, Map<string, TopologyUplinkLink[]>>();

  physicalLinks.forEach((link) => {
    const source = deviceById.get(link.source_device_id);
    const target = deviceById.get(link.target_device_id);
    if (!source || !target || source.id === target.id) return;
    const add = (deviceId: string, peerId: string) => {
      const peers = adjacent.get(deviceId) || new Map<string, TopologyUplinkLink[]>();
      peers.set(peerId, [...(peers.get(peerId) || []), link]);
      adjacent.set(deviceId, peers);
    };
    add(source.id, target.id);
    add(target.id, source.id);
  });

  const upstreams = new Map<string, TopologyUplinkParent[]>();
  devices.forEach((device) => {
    const role = roleOf(device);
    const candidates = Array.from(adjacent.get(device.id)?.entries() || [])
      .map(([peerId, peerLinks]) => ({ device: deviceById.get(peerId)!, links: peerLinks }))
      .filter((peer) => !isWirelessEndpoint(peer.device))
      .filter((peer) => {
        if (role === 'wireless_ap' || role === 'wireless_controller') return true;
        const deviceTier = topologyRoleVisualTier(role);
        const peerTier = topologyRoleVisualTier(roleOf(peer.device));
        return deviceTier !== null && peerTier !== null && peerTier < deviceTier;
      })
      .sort((left, right) => compareDevices(left.device, right.device));
    if (candidates.length) upstreams.set(device.id, candidates);
  });

  const accessDevices = devices.filter(isAccessDevice);
  const accessGroups = groupDevicesByParents(accessDevices, upstreams, 'access');
  const accessPoints = devices.filter((device) => roleOf(device) === 'wireless_ap');
  const wirelessGroups = groupDevicesByParents(accessPoints, upstreams, 'wireless');

  return { accessGroups, wirelessGroups, upstreams, physicalLinkCount: physicalLinks.length, inferredLinkCount };
};

interface TopologyUplinkGroupsProps {
  devices: Device[];
  links: TopologyUplinkLink[];
  deviceOrder?: readonly string[];
  language: string;
  deviceScopeFiltered?: boolean;
  selectedNodeId?: string | null;
  onNodeClick: (device: Device) => void;
}

const getRoleLabel = (device: Device, language: string): string => {
  const role = roleOf(device);
  return role && role !== 'unknown'
    ? topologyRoleLabel(role, language)
    : (language === 'zh' ? '未知角色' : 'Unknown role');
};

const getPortLabel = (value?: string): string => {
  const port = String(value || '').trim();
  // Port-<index> is an unresolved collector fallback, not a verified name.
  return /^port-\d+$/i.test(port) ? '' : port;
};

const getLinkPorts = (link: TopologyUplinkLink, childId: string): { child: string; parent: string } => {
  const sourcePort = getPortLabel(link.source_port || link.source_port_normalized);
  const targetPort = getPortLabel(link.target_port || link.target_port_normalized);
  return link.source_device_id === childId
    ? { child: sourcePort, parent: targetPort }
    : { child: targetPort, parent: sourcePort };
};

const traceUplinkPaths = (
  selected: Device | null,
  upstreams: Map<string, TopologyUplinkParent[]>,
): TopologyUplinkPath[] => {
  if (!selected) return [];
  const paths: TopologyUplinkPath[] = [];
  const visit = (
    current: Device,
    downstreamDevices: Device[],
    downstreamLinks: TopologyUplinkLink[],
    visited: Set<string>,
  ) => {
    const parents = (upstreams.get(current.id) || []).filter((parent) => !visited.has(parent.device.id));
    if (!parents.length) {
      if (downstreamLinks.length) {
        paths.push({ devices: [...downstreamDevices].reverse(), links: [...downstreamLinks].reverse() });
      }
      return;
    }
    parents.forEach((parent) => parent.links.forEach((link) => {
      visit(
        parent.device,
        [...downstreamDevices, parent.device],
        [...downstreamLinks, link],
        new Set([...visited, parent.device.id]),
      );
    }));
  };
  visit(selected, [selected], [], new Set([selected.id]));
  return paths.sort((left, right) => compareText(
    left.devices.map((device) => device.hostname).join(' > '),
    right.devices.map((device) => device.hostname).join(' > '),
  ));
};

const getLinkKey = (link: TopologyUplinkLink): string => (
  link.link_key || link.id || [
    link.source_device_id,
    link.source_port_normalized || link.source_port || '',
    link.target_device_id,
    link.target_port_normalized || link.target_port || '',
  ].join('::')
);

const getCurvePath = (from: DiagramPoint, to: DiagramPoint): string => {
  const deltaY = to.y - from.y;
  if (Math.abs(deltaY) < 4) {
    const bend = Math.max(22, Math.abs(to.x - from.x) * 0.09);
    return 'M ' + from.x + ' ' + from.y
      + ' C ' + from.x + ' ' + (from.y - bend)
      + ' ' + to.x + ' ' + (to.y - bend)
      + ' ' + to.x + ' ' + to.y;
  }
  const bendY = from.y + deltaY * 0.48;
  return 'M ' + from.x + ' ' + from.y
    + ' C ' + from.x + ' ' + bendY
    + ' ' + to.x + ' ' + bendY
    + ' ' + to.x + ' ' + to.y;
};

const TopologyUplinkGroups: React.FC<TopologyUplinkGroupsProps> = ({
  devices,
  links,
  deviceOrder,
  language,
  deviceScopeFiltered = false,
  selectedNodeId,
  onNodeClick,
}) => {
  const zh = language === 'zh';
  const topologyIcons = useTopologyIcons(devices);
  const deviceRank = useMemo(() => new Map(deviceOrder?.map((id, index) => [id, index])), [deviceOrder]);
  const rankOf = (id: string) => deviceRank.get(id) ?? Number.MAX_SAFE_INTEGER;
  const grouping = useMemo(() => {
    const result = buildTopologyUplinkGrouping(devices, links);
    if (!deviceRank.size) return result;
    const rank = (device: Device) => deviceRank.get(device.id) ?? Number.MAX_SAFE_INTEGER;
    const accessGroups = result.accessGroups
      .map((group) => ({
        ...group,
        devices: [...group.devices].sort((left, right) => rank(left) - rank(right)),
      }))
      .sort((left, right) => rank(left.devices[0]) - rank(right.devices[0]));
    return { ...result, accessGroups };
  }, [deviceRank, devices, links]);
  const physicalLinks = useMemo(() => links.filter(isPhysicalLink), [links]);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(() => new Set());
  const [expandedWirelessColumns, setExpandedWirelessColumns] = useState<Set<string>>(() => new Set());
  const canvasRef = useRef<HTMLElement | null>(null);
  const [canvasHeight, setCanvasHeight] = useState(0);
  const [showLinkLoad, setShowLinkLoad] = useState(false);
  const [linkTooltip, setLinkTooltip] = useState<{ edgeId: string; x: number; y: number } | null>(null);
  const pageSelectedDevice = devices.find((device) => device.id === selectedNodeId) || null;
  const edgeDevices = devices.filter((device) => topologyRoleVisualTier(roleOf(device)) === 0).sort(compareDevices);
  const coreDevices = devices.filter((device) => roleOf(device) === 'core').sort(compareDevices);
  const distributionDevices = devices.filter((device) => roleOf(device) === 'distribution').sort(compareDevices);
  const accessPointDevices = devices.filter((device) => roleOf(device) === 'wireless_ap').sort(compareDevices);
  const accessIds = new Set(grouping.accessGroups.flatMap((group) => group.devices.map((device) => device.id)));
  const apIds = new Set(grouping.wirelessGroups.flatMap((group) => group.devices.map((device) => device.id)));
  const controllers = devices.filter((device) => roleOf(device) === 'wireless_controller').sort(compareDevices);
  const accessGroupByDevice = new Map<string, TopologyUplinkGroup>();
  grouping.accessGroups.forEach((group) => group.devices.forEach((device) => accessGroupByDevice.set(device.id, group)));
  const pointsByAccessGroup = new Map<string, Device[]>();
  const accessPointParentIds = new Map<string, string[]>();
  accessPointDevices.forEach((accessPoint) => {
    const parents = (grouping.upstreams.get(accessPoint.id) || [])
      .map((item) => item.device)
      .filter(isAccessDevice)
      .sort(compareDevices);
    accessPointParentIds.set(accessPoint.id, parents.map((parent) => parent.id));
    const accessGroup = parents.map((parent) => accessGroupByDevice.get(parent.id)).find(Boolean);
    const groupId = accessGroup?.id || 'wireless:unconfirmed';
    pointsByAccessGroup.set(groupId, [...(pointsByAccessGroup.get(groupId) || []), accessPoint]);
  });
  const accessPointColumns: AccessPointColumn[] = grouping.accessGroups
    .map((group) => ({
      id: 'wireless:' + group.id,
      accessGroupId: group.id,
      devices: (pointsByAccessGroup.get(group.id) || []).sort(compareDevices),
    }))
    .filter((column) => column.devices.length > 0);
  const unassignedAccessPoints = (pointsByAccessGroup.get('wireless:unconfirmed') || []).sort(compareDevices);
  if (unassignedAccessPoints.length) {
    accessPointColumns.push({ id: 'wireless:unconfirmed', accessGroupId: null, devices: unassignedAccessPoints });
  }
  const validWirelessColumnKey = accessPointColumns.map((column) => column.id).join('\u0000');
  const defaultDiagramDevice = accessPointDevices[0]
    || grouping.accessGroups[0]?.devices[0]
    || coreDevices[0]
    || distributionDevices[0]
    || edgeDevices[0]
    || controllers[0]
    || null;
  const selectedDevice = pageSelectedDevice || defaultDiagramDevice;
  const selectedPaths = useMemo(
    () => traceUplinkPaths(selectedDevice, grouping.upstreams),
    [selectedDevice, grouping.upstreams],
  );
  const tracedLinks = useMemo(() => new Set(selectedPaths.flatMap((path) => path.links)), [selectedPaths]);
  const pathIndexesByLink = useMemo(() => {
    const indexesByLink = new Map<TopologyUplinkLink, number[]>();
    selectedPaths.forEach((path, index) => path.links.forEach((link) => {
      const indexes = indexesByLink.get(link) ?? [];
      indexes.push(index);
      indexesByLink.set(link, indexes);
    }));
    return indexesByLink;
  }, [selectedPaths]);
  const tracedDevices = useMemo(
    () => new Set(selectedPaths.flatMap((path) => path.devices.map((device) => device.id))),
    [selectedPaths],
  );
  const selectedParents = selectedDevice ? grouping.upstreams.get(selectedDevice.id) || [] : [];
  const selectedParentIds = new Set(selectedParents.map((item) => item.device.id));
  const deviceById = new Map(devices.map((device) => [device.id, device]));
  const otherDevices = devices.filter((device) => (
    !accessIds.has(device.id)
    && !apIds.has(device.id)
    && !edgeDevices.some((candidate) => candidate.id === device.id)
    && roleOf(device) !== 'core'
    && roleOf(device) !== 'distribution'
    && roleOf(device) !== 'wireless_controller'
  )).sort((left, right) => (
    getRoleLabel(left, language).localeCompare(getRoleLabel(right, language)) || compareDevices(left, right)
  ));
  const selectedAccessDevice = selectedDevice && isAccessDevice(selectedDevice)
    ? selectedDevice
    : selectedDevice && roleOf(selectedDevice) === 'wireless_ap'
      ? deviceById.get(accessPointParentIds.get(selectedDevice.id)?.[0] || '') || null
      : selectedPaths.flatMap((path) => path.devices).find(isAccessDevice) || null;
  const selectedAccessGroup = selectedAccessDevice ? accessGroupByDevice.get(selectedAccessDevice.id) || null : null;
  const selectedExpandableGroupId = selectedAccessGroup && selectedAccessGroup.devices.length > 1
    ? selectedAccessGroup.id
    : null;
  const validGroupIds = new Set([...grouping.accessGroups, ...grouping.wirelessGroups].map((group) => group.id));

  useEffect(() => {
    if (!selectedExpandableGroupId) return;
    setExpandedGroups((current) => current.has(selectedExpandableGroupId)
      ? current
      : new Set([...current, selectedExpandableGroupId]));
  }, [selectedExpandableGroupId]);

  useEffect(() => {
    setExpandedGroups((current) => new Set(Array.from(current).filter((id) => validGroupIds.has(id))));
  }, [grouping.accessGroups, grouping.wirelessGroups]);

  useEffect(() => {
    const validIds = new Set(validWirelessColumnKey ? validWirelessColumnKey.split('\u0000') : []);
    setExpandedWirelessColumns((current) => {
      const next = new Set(Array.from(current).filter((id) => validIds.has(id)));
      accessPointColumns.forEach((column) => next.add(column.id));
      return next;
    });
  }, [validWirelessColumnKey]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(([entry]) => {
      setCanvasHeight((current) => Math.abs(current - entry.contentRect.height) > 1
        ? entry.contentRect.height
        : current);
    });
    observer.observe(canvas);
    return () => observer.disconnect();
  }, []);

  const toggleGroup = (id: string) => setExpandedGroups((current) => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  });

  const maxGroupsPerRow = 6;
  const sizingCount = Math.max(
    grouping.accessGroups.length,
    accessPointColumns.length,
    coreDevices.length,
    distributionDevices.length,
    edgeDevices.length,
    1,
  );
  const diagramColumns = Math.min(maxGroupsPerRow, sizingCount);
  const leftGutter = 96;
  const controllerColumnWidth = controllers.length ? 198 : 22;
  const laneWidth = Math.max(840, diagramColumns * 168);
  const diagramWidth = leftGutter + laneWidth + controllerColumnWidth;
  const rowCapacity = Math.max(1, Math.floor(laneWidth / 150));
  const groupColumns = Math.min(maxGroupsPerRow, Math.max(1, grouping.accessGroups.length));
  const groupRows = Math.ceil(grouping.accessGroups.length / groupColumns);
  const layerGap = 10;
  let cursorY = 14;

  const layoutRoleRow = (items: Device[], top: number, desiredX: Map<string, number> = new Map()) => {
    const ordered = [...items].sort((left, right) => (
      rankOf(left.id) - rankOf(right.id)
      || (desiredX.get(left.id) ?? Number.MAX_SAFE_INTEGER)
        - (desiredX.get(right.id) ?? Number.MAX_SAFE_INTEGER)
      || compareDevices(left, right)
    ));
    const columns = Math.max(1, Math.min(rowCapacity, ordered.length || 1));
    const rowCount = Math.ceil(ordered.length / columns);
    const positions = new Map<string, DiagramPoint>();
    ordered.forEach((device, index) => {
      positions.set(device.id, {
        x: leftGutter + ((index % columns) + 0.5) * laneWidth / columns,
        y: top + 42 + Math.floor(index / columns) * 51,
      });
    });
    return {
      positions,
      rowCount,
      height: ordered.length ? 34 + rowCount * 51 : 0,
    };
  };

  const edgeTop = edgeDevices.length ? cursorY : -1;
  const edgeLayout = layoutRoleRow(edgeDevices, cursorY);
  if (edgeLayout.height) cursorY += edgeLayout.height + layerGap;
  const coreTop = coreDevices.length ? cursorY : -1;
  const coreLayout = layoutRoleRow(coreDevices, cursorY);
  if (coreLayout.height) cursorY += coreLayout.height + layerGap;

  const distributionDesiredX = new Map<string, number>();
  distributionDevices.forEach((device) => {
    const groupIndexes = grouping.accessGroups
      .map((group, index) => group.parents.some((parent) => parent.id === device.id) ? index : -1)
      .filter((index) => index >= 0);
    if (groupIndexes.length) {
      const childCenters = groupIndexes.map((index) => {
        const column = index % groupColumns;
        return leftGutter + ((column + 0.5) * laneWidth) / groupColumns;
      });
      distributionDesiredX.set(device.id, childCenters.reduce((total, value) => total + value, 0) / childCenters.length);
    }
  });
  const distributionTop = distributionDevices.length ? cursorY : -1;
  const distributionLayout = layoutRoleRow(distributionDevices, cursorY, distributionDesiredX);
  if (distributionLayout.height) cursorY += distributionLayout.height + layerGap;

  const accessTop = grouping.accessGroups.length ? cursorY : -1;
  const accessRowTops: number[] = [];
  if (grouping.accessGroups.length) {
    cursorY += 32;
    for (let row = 0; row < groupRows; row += 1) {
      accessRowTops.push(cursorY);
      const rowGroups = grouping.accessGroups.slice(row * groupColumns, (row + 1) * groupColumns);
      cursorY += (rowGroups.some((group) => group.devices.length > 1 && expandedGroups.has(group.id)) ? 190 : 70) + 8;
    }
    cursorY += 1;
  }
  const accessHeight = grouping.accessGroups.length ? cursorY - accessTop : 0;
  const wirelessTop = accessPointDevices.length || controllers.length ? cursorY : -1;
  const wirelessColumns = accessPointColumns.length;
  const wirelessColumnCount = Math.min(maxGroupsPerRow, Math.max(1, wirelessColumns));
  const wirelessRows = Math.ceil(wirelessColumns / wirelessColumnCount);
  const wirelessRowTops: number[] = [];
  if (wirelessTop >= 0) {
    cursorY += 32;
    for (let row = 0; row < wirelessRows; row += 1) {
      wirelessRowTops.push(cursorY);
      const rowGroups = accessPointColumns.slice(row * wirelessColumnCount, (row + 1) * wirelessColumnCount);
      cursorY += (rowGroups.some((column) => expandedWirelessColumns.has(column.id)) ? 244 : 54) + 8;
    }
    cursorY = Math.max(cursorY, wirelessTop + 86) + 2;
  }
  const wirelessHeight = wirelessTop >= 0 ? cursorY - wirelessTop : 0;

  const otherTop = otherDevices.length ? cursorY : -1;
  const otherLayout = layoutRoleRow(otherDevices, cursorY);
  if (otherLayout.height) cursorY += otherLayout.height + layerGap;
  const contentDiagramHeight = Math.max(360, cursorY + 16);
  const noticeHeight = 42 + (grouping.physicalLinkCount === 0 ? 56 : 0);
  const diagramHeight = Math.max(contentDiagramHeight, canvasHeight - noticeHeight);
  const verticalScale = diagramHeight / contentDiagramHeight;
  const scaleY = (value: number) => value * verticalScale;
  // Card positions scale with their rows, but their header heights stay fixed.
  const accessCenterByDevice = new Map<string, DiagramPoint>();
  grouping.accessGroups.forEach((group, index) => {
    const center = {
      x: leftGutter + ((index % groupColumns + 0.5) * laneWidth) / groupColumns,
      y: accessRowTops[Math.floor(index / groupColumns)] + 32 / verticalScale,
    };
    group.devices.forEach((device) => accessCenterByDevice.set(device.id, center));
  });
  const apCenterByColumnId = new Map<string, DiagramPoint>();
  accessPointColumns.forEach((column, index) => {
    const row = Math.floor(index / wirelessColumnCount);
    const columnIndex = index % wirelessColumnCount;
    apCenterByColumnId.set(column.id, {
      x: leftGutter + ((columnIndex + 0.5) * laneWidth) / wirelessColumnCount,
      y: wirelessRowTops[row] + 25 / verticalScale,
    });
  });
  const accessPointCenterByDevice = new Map<string, DiagramPoint>();
  accessPointColumns.forEach((column) => {
    const center = apCenterByColumnId.get(column.id);
    if (center) column.devices.forEach((device) => accessPointCenterByDevice.set(device.id, center));
  });

  const devicePoints = new Map<string, DiagramPoint>();
  const initialTierRows = [edgeLayout, coreLayout, distributionLayout, otherLayout];
  initialTierRows.forEach((layout) => layout.positions.forEach((point, id) => devicePoints.set(id, point)));
  controllers.forEach((controller, index) => {
    devicePoints.set(controller.id, {
      x: leftGutter + laneWidth + controllerColumnWidth / 2,
      y: wirelessTop + 50 + index * 48,
    });
  });

  const focusedDeviceIds = new Set([...(selectedDevice ? [selectedDevice.id] : []), ...tracedDevices]);
  const diagramEdgeMap = new Map<string, DiagramEdge>();
  const resolveDiagramAnchor = (deviceId: string): { key: string; point: DiagramPoint } | undefined => {
    const devicePoint = devicePoints.get(deviceId);
    if (devicePoint) return { key: 'device:' + deviceId, point: devicePoint };
    const accessPoint = accessCenterByDevice.get(deviceId);
    if (accessPoint) return { key: 'access:' + (accessGroupByDevice.get(deviceId)?.id || deviceId), point: accessPoint };
    const wirelessPoint = accessPointCenterByDevice.get(deviceId);
    if (wirelessPoint) {
      const wirelessColumn = accessPointColumns.find((column) => column.devices.some((device) => device.id === deviceId));
      return { key: 'wireless:' + (wirelessColumn?.id || deviceId), point: wirelessPoint };
    }
    return undefined;
  };
  physicalLinks.forEach((link) => {
    const source = resolveDiagramAnchor(link.source_device_id);
    const target = resolveDiagramAnchor(link.target_device_id);
    if (!source || !target || source.key === target.key) return;
    const [first, second] = [source.key, target.key].sort(compareText);
    const edgeId = first + '::' + second;
    const focused = tracedLinks.has(link)
      || focusedDeviceIds.has(link.source_device_id)
      || focusedDeviceIds.has(link.target_device_id);
    const existing = diagramEdgeMap.get(edgeId);
    if (existing) {
      existing.links.push(link);
      existing.focused = existing.focused || focused;
      return;
    }
    diagramEdgeMap.set(edgeId, {
      id: edgeId,
      from: source.point,
      to: target.point,
      links: [link],
      focused,
    });
  });
  const diagramEdges = Array.from(diagramEdgeMap.values());
  const getEdgeLoad = (edge: DiagramEdge) => edge.links.reduce<number | null>((highest, link) => {
    const load = getTopologyLinkUtilization(link);
    if (load === null) return highest;
    return highest === null ? load : Math.max(highest, load);
  }, null);
  const hoveredEdge = linkTooltip ? diagramEdgeMap.get(linkTooltip.edgeId) : undefined;
  const hoveredLoad = hoveredEdge ? getEdgeLoad(hoveredEdge) : null;
  const getEdgePathIndexes = (edge: DiagramEdge) => [...new Set(
    edge.links.flatMap((link) => pathIndexesByLink.get(link) ?? []),
  )].sort((left, right) => left - right);

  const nodeButton = (device: Device, diagramNode = false) => {
    const selected = device.id === selectedDevice?.id;
    const isSelectedParent = !selected && selectedParentIds.has(device.id);
    const customIcon = topologyIcons.customIconUrl(device);
    const iconUrl = customIcon || getBuiltInTopologyIconUrl(getTopologyDeviceIconType(device));
    const iconFallback = ['wireless_ap', 'wireless_controller'].includes(roleOf(device))
      ? (roleOf(device) === 'wireless_ap' ? <Wifi size={17} aria-hidden="true" /> : <RadioTower size={17} aria-hidden="true" />)
      : <Network size={17} aria-hidden="true" />;
    const stateLabel = device.status === 'online' ? (zh ? '在线' : 'Online')
      : device.status === 'offline' ? (zh ? '离线' : 'Offline')
        : (zh ? '待处理' : 'Pending');
    const classes = selected
      ? 'border-blue-400 bg-blue-50 text-blue-900 ring-2 ring-blue-200 dark:border-blue-500 dark:bg-blue-950/40 dark:text-blue-100 dark:ring-blue-900'
      : isSelectedParent
        ? 'border-cyan-400 bg-cyan-50 text-cyan-900 ring-1 ring-cyan-200 dark:border-cyan-600 dark:bg-cyan-950/30 dark:text-cyan-100 dark:ring-cyan-900'
        : 'border-slate-200 bg-white text-slate-800 hover:border-blue-300 hover:bg-blue-50/60 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:border-blue-700 dark:hover:bg-blue-950/30';
    return (
      <button
        key={device.id}
        type="button"
        id={'topology-uplink-device-' + device.id}
        onClick={() => onNodeClick(device)}
        aria-pressed={selected}
        data-selected={selected || undefined}
        data-uplink-parent={isSelectedParent || undefined}
        className={diagramNode
          ? 'topology-uplink-device'
          : `flex w-full min-w-0 items-center gap-2 rounded-lg border px-2.5 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${classes}`}
        title={`${device.hostname} · ${device.ip_address}`}
      >
        <span className={diagramNode ? 'topology-uplink-device-icon' : 'grid size-8 shrink-0 place-items-center rounded-md bg-slate-100 text-slate-600 dark:bg-zinc-800 dark:text-zinc-300'}>
          {iconUrl ? <img src={iconUrl} alt="" aria-hidden="true" className={diagramNode ? '' : 'size-6 object-contain'} /> : iconFallback}
        </span>
        <span className="min-w-0 flex-1">
          <span className={diagramNode ? 'topology-uplink-device-name' : 'block truncate text-xs font-semibold'}>{device.hostname || device.ip_address || device.id}</span>
          {diagramNode ? null : <span className="block truncate text-[10px] text-slate-500 dark:text-zinc-400">{device.ip_address || device.id}</span>}
        </span>
        {diagramNode ? null : <span className="shrink-0 text-[9px] font-medium text-slate-500 dark:text-zinc-400">{stateLabel}</span>}
      </button>
    );
  };

  const renderBand = (key: string, title: string, count: number, top: number, height: number) => (
    <div
      key={key}
      className={'topology-uplink-band topology-uplink-layer-' + key}
      data-topology-layer={key}
      style={{ top: scaleY(top), height: scaleY(height) }}
    >
      <div className="topology-uplink-band-heading">
        <span>{title} · {count} {zh ? '台' : 'devices'}</span>
      </div>
    </div>
  );

  const positionNode = (device: Device, point: DiagramPoint) => (
    <div className="topology-uplink-device-wrap" style={{ left: point.x, top: scaleY(point.y) }} key={'position:' + device.id}>
      {nodeButton(device, true)}
    </div>
  );

  const renderGroupCard = (group: TopologyUplinkGroup, index: number) => {
    const singleDevice = group.devices.length === 1 ? group.devices[0] : null;
    const expanded = expandedGroups.has(group.id);
    const memberCount = group.devices.length + (zh ? ' 台接入设备' : ' access devices');
    const uplinkStatus = group.parents.length === 0
      ? (zh ? '上联待确认' : 'Uplink pending')
      : group.parents.length > 1
        ? group.parents.length + (zh ? ' 路上联' : ' uplinks')
        : '';
    const row = Math.floor(index / groupColumns);
    const column = index % groupColumns;
    const left = leftGutter + column * laneWidth / groupColumns + 6;
    const width = laneWidth / groupColumns - 12;
    return (
      <article
        key={group.id}
        className="topology-uplink-group-card"
        style={{ left: left, top: scaleY(accessRowTops[row]), width: width }}
        data-uplink-group={group.id}
        data-selected={selectedAccessGroup?.id === group.id ? 'true' : 'false'}
      >
        {singleDevice ? (
          <div className="topology-uplink-single-access">
            {nodeButton(singleDevice, true)}
            {uplinkStatus && <span className="topology-uplink-group-status">{uplinkStatus}</span>}
          </div>
        ) : (
          <button
            type="button"
            className="topology-uplink-group-toggle"
            aria-expanded={expanded}
            onClick={() => toggleGroup(group.id)}
          >
            <span>
              <strong>{memberCount}</strong>
              {uplinkStatus && <span className="topology-uplink-group-status">{uplinkStatus}</span>}
            </span>
            <ChevronDown size={13} className={expanded ? 'rotate-180 transition-transform' : 'transition-transform'} aria-hidden="true" />
          </button>
        )}
        {!singleDevice && expanded ? (
          <div className="topology-uplink-group-members" aria-label={zh ? '组内接入设备' : 'Access group members'}>
            {group.devices.map((device) => nodeButton(device, true))}
          </div>
        ) : null}
      </article>
    );
  };

  const renderApCard = (column: AccessPointColumn, index: number) => {
    if (!column.devices.length) return null;
    const expanded = expandedWirelessColumns.has(column.id);
    const selectedInColumn = column.devices.some((device) => device.id === selectedDevice?.id);
    const row = Math.floor(index / wirelessColumnCount);
    const columnIndex = index % wirelessColumnCount;
    const left = leftGutter + columnIndex * laneWidth / wirelessColumnCount + 6;
    const width = laneWidth / wirelessColumnCount - 12;
    return (
      <article
        key={column.id}
        className="topology-uplink-ap-card"
        style={{ left: left, top: scaleY(wirelessRowTops[row]), width: width }}
        data-selected={selectedInColumn ? 'true' : 'false'}
      >
        <button
          type="button"
          className="topology-uplink-ap-toggle"
          aria-expanded={expanded}
          aria-label={(zh ? '接入组无线 AP' : 'Access group wireless APs') + ' · ' + column.devices.length + ' AP'}
          onClick={() => setExpandedWirelessColumns((current) => {
            const next = new Set(current);
            if (next.has(column.id)) next.delete(column.id);
            else next.add(column.id);
            return next;
          })}
        >
          <span className="flex min-w-0 items-center gap-1.5"><Wifi size={14} aria-hidden="true" /><strong>{column.devices.length} {zh ? '台 AP' : 'APs'}</strong></span>
          {column.accessGroupId ? <ChevronDown size={13} className={expanded ? 'rotate-180 transition-transform' : 'transition-transform'} aria-hidden="true" /> : null}
        </button>
        {expanded ? (
          <div className="topology-uplink-ap-members">
            {column.devices.map((device) => nodeButton(device, true))}
          </div>
        ) : null}
      </article>
    );
  };

  const renderPath = (path: TopologyUplinkPath, index: number) => (
    <section className="topology-uplink-selected-path" key={path.links.map(getLinkKey).join('|') || String(index)}>
      <h4 className="flex items-center gap-1.5" style={{ color: uplinkPathColor(index) }}>
        <GitFork size={13} aria-hidden="true" />
        {zh ? '路径 ' : 'Path '}{uplinkPathLabel(index)}
      </h4>
      <ol>
        {path.devices.map((device, deviceIndex) => {
          const link = path.links[deviceIndex];
          const nextDevice = path.devices[deviceIndex + 1];
          const ports = link && nextDevice ? getLinkPorts(link, nextDevice.id) : null;
          return (
            <li key={device.id}>
              <strong>{device.hostname || device.ip_address || device.id}</strong>
              {ports ? <span>{ports.parent || (zh ? '端口未提供' : 'Port unavailable')} ↔ {ports.child || (zh ? '端口未提供' : 'Port unavailable')}</span> : null}
            </li>
          );
        })}
      </ol>
    </section>
  );

  if (!devices.length) {
    return (
      <div className="flex min-h-64 flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-white px-5 py-10 text-center dark:border-zinc-700 dark:bg-zinc-900/70" role="status">
        <Network size={24} className="mb-3 text-slate-400" aria-hidden="true" />
        <p className="text-sm font-semibold text-slate-700 dark:text-zinc-200">{zh ? '当前筛选条件下没有可展示的设备' : 'No devices match the current filters'}</p>
        <p className="mt-1 text-xs text-slate-500 dark:text-zinc-400">{zh ? '清空搜索或放宽站点、角色、状态筛选后重试。' : 'Clear the search or relax the site, role, or status filters.'}</p>
      </div>
    );
  }

  return (
    <div className="topology-uplink-workspace" data-topology-view="uplink-groups">
      <section ref={canvasRef} className="topology-uplink-canvas" aria-label={zh ? '上联分组拓扑画布' : 'Uplink grouped topology canvas'}>
        <div className="sticky left-0 z-20 flex h-[42px] items-center gap-3 border-b border-slate-200 bg-white px-3 text-xs text-slate-600">
          <label className="flex shrink-0 items-center gap-2 font-semibold">
            {zh ? '链路着色' : 'Link color'}
            <select className="rounded-md border border-slate-200 bg-white px-2 py-1"
              value={showLinkLoad ? 'load' : 'path'}
              onChange={(event) => setShowLinkLoad(event.target.value === 'load')}>
              <option value="path">{zh ? '路径' : 'Path'}</option>
              <option value="load">{zh ? '负载' : 'Load'}</option>
            </select>
          </label>
          {showLinkLoad && (
            <span className="flex min-w-0 items-center gap-2 overflow-x-auto whitespace-nowrap text-[10px]">
              {TOPOLOGY_LINK_LOAD_TIERS.map((tier) => (
                <span key={tier.label} className="inline-flex shrink-0 items-center gap-1">
                  <span className="h-0.5 w-3 rounded" style={{ backgroundColor: tier.color }} />
                  {zh ? tier.labelZh : tier.label}
                </span>
              ))}
            </span>
          )}
        </div>
        {grouping.physicalLinkCount === 0 ? (
          <div className="mx-3 mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900" role="status">
            {deviceScopeFiltered
              ? (zh ? '当前视图内没有物理链路。选择「有线 + 无线」可查看跨类型连接。' : 'No physical links in this view. Choose Wired + Wireless to see connections between device types.')
              : (zh ? '尚无可确认的物理链路。分组只显示设备，不会用推断关系补出连线。' : 'No confirmed physical links are available. Inferred relations do not create diagram connections.')}
          </div>
        ) : null}
        <div className="topology-uplink-diagram" style={{ width: diagramWidth, height: diagramHeight }}>
          {edgeDevices.length ? renderBand('edge', zh ? '边界层' : 'Edge', edgeDevices.length, edgeTop, edgeLayout.height) : null}
          {coreDevices.length ? renderBand('core', zh ? '核心层' : 'Core layer', coreDevices.length, coreTop, coreLayout.height) : null}
          {distributionDevices.length ? renderBand('distribution', zh ? '汇聚层' : 'Distribution', distributionDevices.length, distributionTop, distributionLayout.height) : null}
          {grouping.accessGroups.length ? renderBand('access', zh ? '接入层' : 'Access layer', grouping.accessGroups.reduce((total, group) => total + group.devices.length, 0), accessTop, accessHeight) : null}
          {accessPointDevices.length || controllers.length ? renderBand('wireless', zh ? '无线' : 'Wireless', accessPointDevices.length + controllers.length, wirelessTop, wirelessHeight) : null}
          {otherDevices.length ? renderBand('other', zh ? '其他设备' : 'Other devices', otherDevices.length, otherTop, otherLayout.height) : null}

          <div className="absolute right-5 top-2 z-10 rounded-md border border-slate-200 bg-white/95 px-2 py-1 text-[10px] font-semibold text-slate-600 shadow-sm">
            {devices.length} {zh ? '台设备' : 'devices'} · {grouping.physicalLinkCount} {zh ? '条物理链路' : 'physical links'}
            {grouping.inferredLinkCount ? ' · ' + grouping.inferredLinkCount + (zh ? ' 条推断待确认' : ' inferred') : ''}
          </div>

          <svg className="topology-uplink-wires" viewBox={'0 0 ' + diagramWidth + ' ' + diagramHeight} preserveAspectRatio="none" aria-hidden="true">
            {diagramEdges.map((edge) => {
              const path = getCurvePath(
                { x: edge.from.x, y: scaleY(edge.from.y) },
                { x: edge.to.x, y: scaleY(edge.to.y) },
              );
              const pathIndexes = showLinkLoad ? [] : getEdgePathIndexes(edge);
              const dx = edge.to.x - edge.from.x;
              const dy = scaleY(edge.to.y - edge.from.y);
              const length = Math.hypot(dx, dy) || 1;
              return (
                <g key={edge.id}>
                  <path className="topology-uplink-wire-hit" d={path}
                    onPointerEnter={(event) => {
                      const bounds = event.currentTarget.ownerSVGElement?.getBoundingClientRect();
                      if (!bounds) return;
                      setLinkTooltip({
                        edgeId: edge.id,
                        x: Math.max(8, Math.min(event.clientX - bounds.left + 12, bounds.width - 210)),
                        y: Math.max(8, event.clientY - bounds.top - 52),
                      });
                    }}
                    onPointerLeave={() => setLinkTooltip(null)}
                  />
                  {pathIndexes.length > 0
                    ? pathIndexes.map((index, lane) => {
                      const offset = (lane - (pathIndexes.length - 1) / 2) * Math.min(4, 12 / Math.max(1, pathIndexes.length - 1));
                      return <path key={index} className="topology-uplink-wire" d={path}
                        data-focused="true" data-uplink-path={uplinkPathLabel(index)}
                        transform={`translate(${-dy / length * offset},${dx / length * offset})`}
                        style={{ stroke: uplinkPathColor(index) }} />;
                    })
                    : <path className="topology-uplink-wire" d={path}
                      data-focused={(showLinkLoad || selectedPaths.length === 0) && edge.focused || undefined}
                      style={showLinkLoad ? { stroke: getTopologyLinkLoadTier(getEdgeLoad(edge)).color } : undefined} />}
                </g>
              );
            })}
          </svg>
          {linkTooltip && hoveredEdge && (
            <div role="tooltip" className="pointer-events-none absolute z-20 rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white shadow-lg"
              style={{ left: linkTooltip.x, top: linkTooltip.y }}>
              {hoveredLoad === null
                ? (zh ? '负载无数据' : 'No load data')
                : `${hoveredEdge.links.length > 1 ? (zh ? '最高负载' : 'Peak load') : (zh ? '链路负载' : 'Link load')} ${formatTopologyLinkUtilization(hoveredLoad)}`}
              {!showLinkLoad && getEdgePathIndexes(hoveredEdge).length > 0 && (
                <div className="mt-0.5 max-w-48 text-[10px] font-normal text-slate-300">
                  {zh ? '路径 ' : 'Paths '}{getEdgePathIndexes(hoveredEdge).map(uplinkPathLabel).join(' · ')}
                </div>
              )}
              {hoveredEdge.links.length > 1 && (
                <div className="mt-0.5 text-[10px] font-normal text-slate-300">
                  {hoveredEdge.links.length} {zh ? '条物理链路' : 'physical links'}
                </div>
              )}
            </div>
          )}

          {[...edgeDevices, ...coreDevices, ...distributionDevices, ...otherDevices].map((device) => (
            positionNode(device, devicePoints.get(device.id)!)
          ))}
          {grouping.accessGroups.map(renderGroupCard)}
          {accessPointColumns.map(renderApCard)}
          {controllers.length ? (
            <section
              className="topology-uplink-controller-panel"
              style={{ top: scaleY(wirelessTop + 18), height: scaleY(Math.max(62, controllers.length * 48 + 40)) }}
              aria-label={zh ? '无线控制器' : 'Wireless controllers'}
            >
              <strong>{zh ? '无线控制器' : 'Wireless controllers'} · {controllers.length}</strong>
              <div className="topology-uplink-controller-list">
                {controllers.map((device) => nodeButton(device, true))}
              </div>
            </section>
          ) : null}
        </div>
      </section>

      <aside className="topology-uplink-detail" aria-label={zh ? '设备详情' : 'Device details'}>
        {selectedDevice ? (
          <>
            <div className="topology-uplink-detail-header">
              <span className="grid size-10 shrink-0 place-items-center rounded-xl border border-blue-100 bg-blue-50 text-blue-700">
                {roleOf(selectedDevice) === 'wireless_ap' ? <Wifi size={20} aria-hidden="true" />
                  : roleOf(selectedDevice) === 'wireless_controller' ? <RadioTower size={20} aria-hidden="true" />
                    : <Network size={20} aria-hidden="true" />}
              </span>
              <div className="min-w-0">
                <p>{getRoleLabel(selectedDevice, language)}</p>
                <h2 className="truncate" title={selectedDevice.hostname}>{selectedDevice.hostname}</h2>
                <code>{selectedDevice.ip_address || selectedDevice.id}</code>
              </div>
            </div>
            <div className="topology-uplink-detail-section flex items-center justify-between">
              <h3>{zh ? '物理上联路径' : 'Physical uplink paths'}</h3>
              <span className="rounded bg-blue-50 px-2 py-0.5 text-[10px] text-blue-700">{selectedPaths.length}</span>
            </div>
            <div className="topology-uplink-detail-content">
              {selectedPaths.length ? selectedPaths.map(renderPath) : (
                <p className="topology-uplink-detail-note">
                  {deviceScopeFiltered
                    ? (zh ? '当前视图内没有可展示的上联路径。' : 'No uplink paths are visible in this view.')
                    : grouping.inferredLinkCount
                    ? (zh ? '尚无可确认的物理上联。推断关系不会作为物理链路展示。' : 'No confirmed physical uplink is available. Inferred links are not shown as physical paths.')
                    : (zh ? '没有发现更上一级的物理链路。' : 'No higher-level physical uplink was found.')}
                </p>
              )}
            </div>
            <button
              type="button"
              className="topology-uplink-locate"
              onClick={() => document.getElementById('topology-uplink-device-' + selectedDevice.id)?.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' })}
            >
              <ArrowUpRight size={15} aria-hidden="true" />
              {zh ? '定位设备' : 'Locate device'}
            </button>
          </>
        ) : (
          <div className="flex h-full flex-col items-center justify-center px-5 text-center">
            <Network size={24} className="mb-3 text-slate-400" aria-hidden="true" />
            <p className="text-sm font-semibold text-slate-700">{zh ? '选择一台设备查看上联路径' : 'Select a device to see its uplink path'}</p>
            <p className="mt-1 text-xs text-slate-500">{zh ? '点击图中的设备，查看每条已确认的上联。' : 'Select a device in the diagram to see its confirmed uplinks.'}</p>
          </div>
        )}
      </aside>
    </div>
  );
};

export default TopologyUplinkGroups;
