import React, { useEffect, useMemo, useState } from 'react';
import { ArrowUpRight, Cable, ChevronDown, GitFork, Network, RadioTower, Router, Wifi } from 'lucide-react';
import type { Device } from '../types';
import { getBuiltInTopologyIconUrl, getTopologyDeviceIconType } from '../domain/topologyDeviceIcons';
import { topologyRoleLabel, topologyRoleVisualTier } from '../domain/topologyRoles';
import { useTopologyIcons } from '../hooks/useTopologyIcons';
import type { TopologyDecoratedLink } from '../hooks/useTopology';
import { topologyDeviceRole } from '../utils/topologyRoleLayout';

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
  >>;

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
  language: string;
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

const TopologyUplinkGroups: React.FC<TopologyUplinkGroupsProps> = ({
  devices,
  links,
  language,
  selectedNodeId,
  onNodeClick,
}) => {
  const zh = language === 'zh';
  const topologyIcons = useTopologyIcons(devices);
  const grouping = useMemo(() => buildTopologyUplinkGrouping(devices, links), [devices, links]);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(() => new Set());
  const selectedDevice = devices.find((device) => device.id === selectedNodeId) || null;
  const selectedParents = selectedDevice ? grouping.upstreams.get(selectedDevice.id) || [] : [];
  const selectedParentIds = new Set(selectedParents.map((item) => item.device.id));
  const coreDevices = devices.filter((device) => roleOf(device) === 'core').sort(compareDevices);
  const distributionDevices = devices.filter((device) => roleOf(device) === 'distribution').sort(compareDevices);
  const accessIds = new Set(grouping.accessGroups.flatMap((group) => group.devices.map((device) => device.id)));
  const apIds = new Set(grouping.wirelessGroups.flatMap((group) => group.devices.map((device) => device.id)));
  const controllers = devices.filter((device) => roleOf(device) === 'wireless_controller').sort(compareDevices);
  const otherDevices = devices.filter((device) => (
    !accessIds.has(device.id)
    && !apIds.has(device.id)
    && roleOf(device) !== 'core'
    && roleOf(device) !== 'distribution'
    && roleOf(device) !== 'wireless_controller'
  )).sort((left, right) => (
    getRoleLabel(left, language).localeCompare(getRoleLabel(right, language)) || compareDevices(left, right)
  ));
  const validGroupIds = new Set([...grouping.accessGroups, ...grouping.wirelessGroups].map((group) => group.id));

  useEffect(() => {
    if (!selectedDevice) return;
    const selectedIds = new Set([selectedDevice.id, ...selectedParentIds]);
    const selectedGroups = [...grouping.accessGroups, ...grouping.wirelessGroups]
      .filter((group) => group.devices.some((device) => selectedIds.has(device.id)))
      .map((group) => group.id);
    if (!selectedGroups.length) return;
    setExpandedGroups((current) => new Set([...current, ...selectedGroups]));
  }, [selectedDevice, selectedNodeId, grouping.accessGroups, grouping.wirelessGroups]);

  useEffect(() => {
    setExpandedGroups((current) => new Set(Array.from(current).filter((id) => validGroupIds.has(id))));
  }, [grouping.accessGroups, grouping.wirelessGroups]);

  const toggleGroup = (id: string) => setExpandedGroups((current) => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  });

  const nodeButton = (device: Device) => {
    const selected = device.id === selectedNodeId;
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
        onClick={() => onNodeClick(device)}
        aria-pressed={selected}
        data-selected={selected || undefined}
        data-uplink-parent={isSelectedParent || undefined}
        className={`flex w-full min-w-0 items-center gap-2 rounded-lg border px-2.5 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${classes}`}
        title={`${device.hostname} · ${device.ip_address}`}
      >
        <span className="grid size-8 shrink-0 place-items-center rounded-md bg-slate-100 text-slate-600 dark:bg-zinc-800 dark:text-zinc-300">
          {iconUrl ? <img src={iconUrl} alt="" aria-hidden="true" className="size-6 object-contain" /> : iconFallback}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-xs font-semibold">{device.hostname || device.ip_address || device.id}</span>
          <span className="block truncate text-[10px] text-slate-500 dark:text-zinc-400">{device.ip_address || device.id}</span>
        </span>
        <span className="shrink-0 text-[9px] font-medium text-slate-500 dark:text-zinc-400">{stateLabel}</span>
      </button>
    );
  };

  const roleSection = (title: string, devicesForRole: Device[], tone: string, deviceGridClass = 'grid grid-cols-1 gap-2 sm:grid-cols-2 2xl:grid-cols-3') => (
    devicesForRole.length ? (
    <section className={`rounded-xl border p-3 ${tone}`} aria-label={title}>
      <div className="mb-2 flex items-center justify-between gap-3">
        <h3 className="text-xs font-bold">{title}</h3>
        <span className="rounded-full bg-white/80 px-2 py-0.5 text-[10px] font-semibold text-slate-600 dark:bg-zinc-900/70 dark:text-zinc-300">{devicesForRole.length}</span>
      </div>
      <div className={deviceGridClass}>
        {devicesForRole.map((device) => <React.Fragment key={device.id}>{nodeButton(device)}</React.Fragment>)}
      </div>
    </section>
    ) : null
  );

  const accessGroupSection = (
    groups: TopologyUplinkGroup[],
    pendingLabel: string,
    emptyMessage: string,
  ) => (
    <section className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm dark:border-zinc-800 dark:bg-zinc-900/70" aria-label={zh ? '接入上联分组' : 'Access uplink groups'}>
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="grid size-7 place-items-center rounded-lg bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300"><Cable size={15} aria-hidden="true" /></span>
          <h3 className="text-xs font-bold text-slate-800 dark:text-zinc-100">{zh ? '接入上联分组' : 'Access uplink groups'}</h3>
        </div>
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-600 dark:bg-zinc-800 dark:text-zinc-300">
          {groups.reduce((total, group) => total + group.devices.length, 0)}
        </span>
      </div>
      {groups.length ? (
        <div className="grid grid-cols-1 gap-2 xl:grid-cols-2 2xl:grid-cols-3">
          {groups.map((group) => {
            const expanded = expandedGroups.has(group.id);
            const selectedInGroup = group.devices.some((device) => device.id === selectedNodeId);
            const hasMultiParent = group.parents.length > 1;
            const groupLabel = group.parents.length
              ? group.parents.map((parent) => parent.hostname || parent.ip_address || parent.id).join(' + ')
              : pendingLabel;
            return (
              <article
                key={group.id}
                className={`min-w-0 overflow-hidden rounded-lg border transition-colors ${selectedInGroup ? 'border-blue-400 bg-blue-50/50 ring-1 ring-blue-200 dark:border-blue-600 dark:bg-blue-950/20 dark:ring-blue-900' : 'border-slate-200 bg-slate-50/50 dark:border-zinc-700 dark:bg-zinc-950/20'}`}
                data-uplink-group={group.id}
              >
                <button
                  type="button"
                  aria-expanded={expanded}
                  aria-label={`${groupLabel} · ${group.devices.length} ${zh ? '台设备' : 'devices'}`}
                  onClick={() => toggleGroup(group.id)}
                  className="flex min-h-[64px] w-full items-center justify-between gap-3 px-3 py-2 text-left hover:bg-slate-100/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:hover:bg-zinc-800/70"
                >
                  <span className="min-w-0">
                    <span className="flex items-center gap-1.5 truncate text-xs font-semibold text-slate-800 dark:text-zinc-100">
                      {hasMultiParent ? <GitFork size={14} className="shrink-0 text-blue-600 dark:text-blue-300" aria-hidden="true" /> : null}
                      {!group.parents.length ? <span className="size-1.5 shrink-0 rounded-full bg-amber-500" /> : null}
                      <span className="truncate">{groupLabel}</span>
                    </span>
                    <span className="mt-1 block truncate text-[10px] text-slate-500 dark:text-zinc-400">
                      {group.parents.length
                        ? group.parents.map((parent) => getRoleLabel(parent, language)).join(' · ')
                        : (zh ? '尚无可确认的直接物理上联' : 'No confirmed direct physical uplink')}
                    </span>
                  </span>
                  <span className="flex shrink-0 items-center gap-2">
                    <span className={`rounded-full px-2 py-0.5 text-[9px] font-bold ${!group.parents.length ? 'bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-200' : hasMultiParent ? 'bg-blue-100 text-blue-800 dark:bg-blue-950/60 dark:text-blue-200' : 'bg-slate-200 text-slate-700 dark:bg-zinc-800 dark:text-zinc-300'}`}>
                      {!group.parents.length ? pendingLabel : hasMultiParent ? (zh ? `${group.parents.length} 路上联` : `${group.parents.length} uplinks`) : (zh ? '单上联' : 'Single uplink')}
                    </span>
                    <span className="rounded-full bg-white px-2 py-0.5 text-[10px] font-semibold text-slate-600 dark:bg-zinc-900 dark:text-zinc-300">{group.devices.length}</span>
                    <ChevronDown size={15} className={`shrink-0 text-slate-500 transition-transform ${expanded ? 'rotate-180' : ''}`} aria-hidden="true" />
                  </span>
                </button>
                {expanded ? (
                  <div className="grid max-h-72 grid-cols-1 gap-1.5 overflow-auto border-t border-slate-200 p-2 sm:grid-cols-2 dark:border-zinc-800" aria-label={zh ? '组内设备' : 'Group devices'}>
                    {group.devices.map((device) => <React.Fragment key={device.id}>{nodeButton(device)}</React.Fragment>)}
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
      ) : (
        <p className="rounded-lg border border-dashed border-slate-200 px-3 py-4 text-center text-xs text-slate-500 dark:border-zinc-700 dark:text-zinc-400">{emptyMessage}</p>
      )}
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
    <div className="flex h-full min-h-0 flex-col gap-2 overflow-auto rounded-xl bg-slate-50 p-2.5 dark:bg-zinc-950/40 sm:p-3">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-sm dark:border-zinc-800 dark:bg-zinc-900/80" aria-label={zh ? '上联分组说明' : 'Uplink grouping details'}>
        <p className="min-w-0 text-[11px] text-slate-600 dark:text-zinc-300">
          {zh ? '接入分组依据已确认的物理链路；推断关系不会作为上联归属。' : 'Access groups use evidenced physical links; inferred relations are excluded.'}
        </p>
        <div className="flex shrink-0 flex-wrap items-center gap-1.5 text-[10px]">
          <span className="rounded-full bg-slate-100 px-2.5 py-1 font-semibold text-slate-700 dark:bg-zinc-800 dark:text-zinc-200">{zh ? `${devices.length} 台设备` : `${devices.length} devices`}</span>
          <span className="rounded-full bg-emerald-50 px-2.5 py-1 font-semibold text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-200">{zh ? `${grouping.physicalLinkCount} 条物理链路` : `${grouping.physicalLinkCount} physical links`}</span>
          {grouping.inferredLinkCount > 0 ? <span className="rounded-full bg-amber-50 px-2.5 py-1 font-semibold text-amber-800 dark:bg-amber-950/50 dark:text-amber-200">{zh ? `${grouping.inferredLinkCount} 条推断关系待确认` : `${grouping.inferredLinkCount} inferred relations need confirmation`}</span> : null}
        </div>
      </div>

      {grouping.physicalLinkCount === 0 ? (
        <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100" role="status">
          <ArrowUpRight size={15} className="mt-0.5 shrink-0" aria-hidden="true" />
          <span>{zh ? '尚无可确认的物理上联。接入设备会显示为“上联待确认”，不会根据推断关系补出上联。' : 'No confirmed physical uplinks are available. Access devices remain under “Uplink pending”; inferred relations do not create parents.'}</span>
        </div>
      ) : null}

      {selectedDevice ? (
        <section className="flex flex-wrap items-center gap-2 rounded-lg border border-blue-200 bg-blue-50/70 px-3 py-2 dark:border-blue-900 dark:bg-blue-950/20" aria-label={zh ? '选中设备上联详情' : 'Selected device uplinks'}>
          <div className="flex min-w-0 items-center gap-1.5 text-[11px]">
            <Router size={14} className="shrink-0 text-blue-700 dark:text-blue-300" aria-hidden="true" />
            <span className="text-blue-700 dark:text-blue-300">{zh ? '当前设备' : 'Selected'}:</span>
            <strong className="max-w-48 truncate text-slate-900 dark:text-white">{selectedDevice.hostname}</strong>
            <span className="shrink-0 text-slate-500 dark:text-zinc-400">· {getRoleLabel(selectedDevice, language)}</span>
          </div>
          <span className="rounded-full bg-white px-2 py-0.5 text-[10px] font-semibold text-blue-800 dark:bg-zinc-900 dark:text-blue-200">{selectedParents.length ? (zh ? `${selectedParents.length} 个直接上联` : `${selectedParents.length} direct uplinks`) : (zh ? '上联待确认' : 'Uplink pending')}</span>
          {selectedParents.length ? (
            <ul className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
              {selectedParents.map(({ device: parent, links: parentLinks }) => {
                const portsLabel = parentLinks.map((link) => {
                  const ports = getLinkPorts(link, selectedDevice.id);
                  return `${ports.child || (zh ? '本端端口未提供' : 'Local port unavailable')} ↔ ${ports.parent || (zh ? '对端端口未提供' : 'Peer port unavailable')}`;
                }).join(' · ');
                return (
                  <li key={parent.id} className="min-w-0">
                    <button
                      type="button"
                      onClick={() => onNodeClick(parent)}
                      aria-pressed={false}
                      data-uplink-parent="true"
                      title={`${parent.hostname} · ${portsLabel}`}
                      className="flex max-w-full min-w-0 items-center gap-1.5 rounded-md border border-cyan-300 bg-white px-2 py-1 text-left text-[10px] text-cyan-900 ring-1 ring-cyan-100 hover:bg-cyan-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:border-cyan-800 dark:bg-zinc-900 dark:text-cyan-100 dark:ring-cyan-950"
                    >
                      <ArrowUpRight size={12} className="shrink-0" aria-hidden="true" />
                      <span className="max-w-40 truncate font-semibold">{parent.hostname}</span>
                      <span className="min-w-0 truncate text-slate-500 dark:text-zinc-400">{portsLabel}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="text-[10px] text-amber-900 dark:text-amber-100">
              {grouping.inferredLinkCount > 0
                ? (zh ? '未找到可确认的直接物理上联；推断关系不会作为上联展示。' : 'No direct physical uplink evidence; inferred relations are not shown as parents.')
                : (zh ? '未找到可确认的直接物理上联。' : 'No confirmed direct physical uplink was found.')}
            </p>
          )}
        </section>
      ) : null}

      <div className={`grid grid-cols-1 gap-2 ${coreDevices.length && distributionDevices.length ? 'xl:grid-cols-[minmax(190px,0.5fr)_minmax(0,2fr)]' : ''}`}>
        {roleSection(zh ? '核心层' : 'Core layer', coreDevices, 'border-violet-200 bg-violet-50/70 text-violet-900 dark:border-violet-900 dark:bg-violet-950/20 dark:text-violet-100', 'grid grid-cols-1 gap-2')}
        {roleSection(zh ? '汇聚层' : 'Distribution layer', distributionDevices, 'border-teal-200 bg-teal-50/70 text-teal-900 dark:border-teal-900 dark:bg-teal-950/20 dark:text-teal-100', 'grid grid-cols-1 gap-2 sm:grid-cols-2 2xl:grid-cols-5')}
      </div>

      {accessGroupSection(
        grouping.accessGroups,
        zh ? '上联待确认' : 'Uplink pending',
        zh ? '当前筛选条件下没有接入设备。' : 'No access devices match the current filters.',
      )}

      {(apIds.size > 0 || controllers.length > 0) ? <section className="rounded-xl border border-purple-200 bg-purple-50/40 p-3 dark:border-purple-900 dark:bg-purple-950/10" aria-label={zh ? '无线设备' : 'Wireless devices'}>
        <div className="mb-2 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2"><span className="grid size-7 place-items-center rounded-lg bg-purple-100 text-purple-700 dark:bg-purple-950/60 dark:text-purple-300"><Wifi size={15} aria-hidden="true" /></span><h3 className="text-xs font-bold text-purple-900 dark:text-purple-100">{zh ? '无线接入点' : 'Wireless access points'}</h3></div>
          <span className="rounded-full bg-white/80 px-2 py-0.5 text-[10px] font-semibold text-purple-800 dark:bg-zinc-900/70 dark:text-purple-200">{grouping.wirelessGroups.reduce((total, group) => total + group.devices.length, 0)}</span>
        </div>
        <div className="grid grid-cols-1 gap-2 2xl:grid-cols-[minmax(0,1fr)_minmax(220px,0.35fr)]">
          <div>
            {grouping.wirelessGroups.length ? (
              <div className="grid grid-cols-1 gap-2 xl:grid-cols-2">
                {grouping.wirelessGroups.map((group) => {
                  const expanded = expandedGroups.has(group.id);
                  const selectedInGroup = group.devices.some((device) => device.id === selectedNodeId);
                  const label = group.parents.length
                    ? group.parents.map((parent) => parent.hostname || parent.ip_address || parent.id).join(' + ')
                    : (zh ? '上联待确认' : 'Uplink pending');
                  return (
                    <article key={group.id} className={`overflow-hidden rounded-lg border ${selectedInGroup ? 'border-purple-400 bg-white ring-1 ring-purple-200 dark:border-purple-700 dark:bg-zinc-900 dark:ring-purple-900' : 'border-purple-100 bg-white/80 dark:border-purple-900/70 dark:bg-zinc-900/70'}`}>
                      <button type="button" aria-expanded={expanded} aria-label={`${label} · ${group.devices.length} AP`} onClick={() => toggleGroup(group.id)} className="flex min-h-[58px] w-full items-center justify-between gap-2 px-3 py-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-500">
                        <span className="min-w-0"><span className="block truncate text-xs font-semibold text-slate-800 dark:text-zinc-100">{label}</span><span className="mt-0.5 block truncate text-[10px] text-slate-500 dark:text-zinc-400">{group.parents.length ? group.parents.map((parent) => getRoleLabel(parent, language)).join(' · ') : (zh ? '尚无可确认的有线父设备' : 'No confirmed wired parent')}</span></span>
                        <span className="flex shrink-0 items-center gap-2"><span className={`rounded-full px-2 py-0.5 text-[9px] font-bold ${group.parents.length ? 'bg-purple-100 text-purple-800 dark:bg-purple-950/60 dark:text-purple-200' : 'bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-200'}`}>{group.parents.length ? (zh ? '有线父设备' : 'Wired parent') : (zh ? '待确认' : 'Pending')}</span><span className="text-[10px] font-semibold text-slate-600 dark:text-zinc-300">{group.devices.length}</span><ChevronDown size={14} className={`text-slate-500 transition-transform ${expanded ? 'rotate-180' : ''}`} aria-hidden="true" /></span>
                      </button>
                      {expanded ? <div className="grid max-h-60 grid-cols-1 gap-1.5 overflow-auto border-t border-purple-100 p-2 sm:grid-cols-2 dark:border-purple-900/70">{group.devices.map((device) => <React.Fragment key={device.id}>{nodeButton(device)}</React.Fragment>)}</div> : null}
                    </article>
                  );
                })}
              </div>
            ) : <p className="rounded-lg border border-dashed border-purple-200 bg-white/60 px-3 py-4 text-center text-xs text-slate-500 dark:border-purple-900 dark:bg-zinc-900/40 dark:text-zinc-400">{zh ? '当前筛选条件下没有无线接入点。' : 'No wireless access points match the current filters.'}</p>}
          </div>
          <section className="rounded-lg border border-purple-100 bg-white/75 p-2.5 dark:border-purple-900/70 dark:bg-zinc-900/70" aria-label={zh ? '无线控制器' : 'Wireless controllers'}>
            <div className="mb-2 flex items-center justify-between gap-2"><h4 className="text-[11px] font-bold text-purple-900 dark:text-purple-100">{zh ? '无线控制器' : 'Wireless controllers'}</h4><span className="rounded-full bg-purple-100 px-2 py-0.5 text-[9px] font-semibold text-purple-800 dark:bg-purple-950/60 dark:text-purple-200">{controllers.length}</span></div>
            {controllers.length ? <div className="grid grid-cols-1 gap-1.5">{controllers.map((device) => <React.Fragment key={device.id}>{nodeButton(device)}</React.Fragment>)}</div> : <p className="text-[10px] text-slate-500 dark:text-zinc-400">{zh ? '没有无线控制器设备。' : 'No wireless controllers.'}</p>}
          </section>
        </div>
      </section> : null}

      {otherDevices.length ? roleSection(zh ? '其他角色设备' : 'Other role devices', otherDevices, 'border-slate-200 bg-white text-slate-800 dark:border-zinc-800 dark:bg-zinc-900/70 dark:text-zinc-100') : null}
    </div>
  );
};

export default TopologyUplinkGroups;
