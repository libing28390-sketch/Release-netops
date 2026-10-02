import type { RackDeviceVM, RackVM } from '../types';
import type { TopologyLinkItem } from './RackCableLayer';

export interface RawTopologyLinkItem {
  id?: string;
  link_key?: string;
  source_device_id?: string;
  target_device_id?: string;
  source_hostname?: string;
  target_hostname?: string;
  source_hostname_resolved?: string;
  target_hostname_resolved?: string;
  source_port?: string;
  target_port?: string;
  source_port_normalized?: string;
  target_port_normalized?: string;
  source_aggregation_name?: string;
  target_aggregation_name?: string;
  link_kind?: string;
  member_count?: number;
  active_member_count?: number;
  members?: RawTopologyMember[];
  operational_state?: string;
  status?: string;
  discovery_source?: string;
  aggregation_protocol?: string;
  bandwidth_mbps?: number | null;
  speed_mbps?: number | null;
  cable_type?: string;
}

export interface RawTopologyMemberEndpoint {
  device_id?: string;
  name?: string;
  normalized?: string;
  speed_mbps?: number;
  up?: boolean;
}

export interface RawTopologyMember {
  source?: RawTopologyMemberEndpoint;
  target?: RawTopologyMemberEndpoint;
  protocol?: string;
}

const normalizeIdentity = (value?: string): string =>
  String(value || '').trim().toLowerCase();

const compactIdentity = (value?: string): string =>
  normalizeIdentity(value).replace(/[^a-z0-9]/g, '');

const addDeviceIdentity = (map: Map<string, RackDeviceVM>, value: string | undefined, device: RackDeviceVM) => {
  const normalized = normalizeIdentity(value);
  if (normalized) map.set(normalized, device);
  const compact = compactIdentity(value);
  if (compact) map.set(compact, device);
};

const normalizeStatus = (value?: string): TopologyLinkItem['status'] => {
  const status = normalizeIdentity(value);
  if (status === 'up' || status === 'active' || status === 'healthy') return 'up';
  if (status === 'down' || status === 'inactive' || status === 'failed') return 'down';
  if (status === 'degraded' || status === 'warning') return 'degraded';
  if (status === 'stale' || status === 'expired') return 'stale';
  return 'unknown';
};

const normalizeCableType = (value?: string): TopologyLinkItem['cable_type'] => {
  const cableType = normalizeIdentity(value);
  if (cableType === 'fiber' || cableType === 'dac' || cableType === 'copper') return cableType;
  return undefined;
};

const isS6800Device = (device?: RackDeviceVM): boolean => {
  if (!device) return false;
  const identity = `${device.assetKey || ''} ${device.vendor || ''} ${device.model || ''}`.toLowerCase();
  return identity.includes('s6800') || identity.includes('s6850');
};

const isS6800SfpPort = (device: RackDeviceVM | undefined, interfaceName: string): boolean => {
  if (!isS6800Device(device)) return false;
  const name = normalizeIdentity(interfaceName);
  if (/(mgmt|management|console|usb)/i.test(name)) return false;
  if (/(qsfp|fge|hge|40ge|100ge|40g|100g|fortygig|hundredgig)/i.test(name)) return false;
  if (!/(sfp|xge|10ge|ge|gigabit|ethernet)/i.test(name)) return false;
  const match = name.match(/(\d+)$/);
  const portNumber = match ? Number(match[1]) : Number.NaN;
  return Number.isFinite(portNumber) && portNumber >= 1 && portNumber <= 48;
};

const inferCableType = (
  localInterface: string,
  remoteInterface: string,
  explicitType?: string,
  localDevice?: RackDeviceVM,
  remoteDevice?: RackDeviceVM,
): TopologyLinkItem['cable_type'] => {
  const explicit = normalizeCableType(explicitType);
  if (explicit) return explicit;
  // S6800/S6850 ports 1–48 are SFP/SFP+ cages. A generic GE name describes
  // speed, not the physical receptacle, so use the asset port layout when no
  // explicit cable medium was supplied by discovery.
  if (isS6800SfpPort(localDevice, localInterface) || isS6800SfpPort(remoteDevice, remoteInterface)) {
    return 'fiber';
  }
  const identity = `${localInterface} ${remoteInterface}`.toLowerCase();
  if (/(qsfp|sfp|xge|10ge|ten[- ]?gigabit|fge|40ge|forty|hge|100ge|hundred)/i.test(identity)) {
    return 'fiber';
  }
  if (/(^|[^a-z])(ge|gigabit|ethernet)/i.test(identity)) {
    return 'copper';
  }
  return undefined;
};

/**
 * Convert the backend physical-link read model into rack-local links.
 *
 * This function intentionally never invents a link. Rows unrelated to the
 * current rack are dropped, and a link whose rack device is the target is
 * reversed so the renderer always starts from a real in-rack device.
 */
export function normalizeRackTopologyLinks(
  rawLinks: RawTopologyLinkItem[],
  rackVM: RackVM,
): TopologyLinkItem[] {
  const deviceMap = new Map<string, RackDeviceVM>();
  rackVM.devices.forEach((device) => {
    addDeviceIdentity(deviceMap, device.id, device);
    addDeviceIdentity(deviceMap, device.networkDeviceId, device);
    addDeviceIdentity(deviceMap, device.name, device);
  });

  const resolveDevice = (id?: string, name?: string): RackDeviceVM | undefined =>
    deviceMap.get(normalizeIdentity(id))
    || deviceMap.get(compactIdentity(id))
    || deviceMap.get(normalizeIdentity(name))
    || deviceMap.get(compactIdentity(name));

  const normalized = rawLinks.flatMap<TopologyLinkItem>((raw) => {
    const sourceName = raw.source_hostname_resolved || raw.source_hostname || '';
    const targetName = raw.target_hostname_resolved || raw.target_hostname || '';
    const sourceDevice = resolveDevice(raw.source_device_id, sourceName);
    const targetDevice = resolveDevice(raw.target_device_id, targetName);

    if (!sourceDevice && !targetDevice) return [];

    const normalizedLinkKind = normalizeIdentity(raw.link_kind);
    // A logical LAG parent without physical member evidence has no safe 3D
    // endpoint. Do not guess a port from the aggregation number (e.g. map
    // Bridge-Aggregation1 to physical port 1).
    if (normalizedLinkKind === 'aggregation'
      && (!raw.members || raw.members.length === 0)
      && !raw.source_port_normalized
      && !raw.target_port_normalized) {
      return [];
    }

    const members = normalizedLinkKind === 'aggregation' && raw.members?.length
      ? raw.members
      : [undefined];

    return members.flatMap<TopologyLinkItem>((member, memberIndex) => {
      const memberSource = member?.source;
      const memberTarget = member?.target;
      const memberSourceDevice = memberSource
        ? resolveDevice(memberSource.device_id, memberSource.name) || sourceDevice
        : sourceDevice;
      const memberTargetDevice = memberTarget
        ? resolveDevice(memberTarget.device_id, memberTarget.name) || targetDevice
        : targetDevice;
      const reverse = !memberSourceDevice && Boolean(memberTargetDevice);
      const localDevice = reverse ? memberTargetDevice! : memberSourceDevice!;
      const remoteDevice = reverse ? memberSourceDevice : memberTargetDevice;
      const localEndpoint = reverse ? memberTarget : memberSource;
      const remoteEndpoint = reverse ? memberSource : memberTarget;
      const localEndpointId = reverse
        ? (localEndpoint?.device_id || raw.target_device_id)
        : (localEndpoint?.device_id || raw.source_device_id);
      const remoteEndpointId = reverse
        ? (remoteEndpoint?.device_id || raw.source_device_id)
        : (remoteEndpoint?.device_id || raw.target_device_id);
      const localName = reverse
        ? (targetName || localDevice?.name || '')
        : (sourceName || localDevice?.name || '');
      const remoteName = reverse
        ? (sourceName || remoteDevice?.name || '')
        : (targetName || remoteDevice?.name || '');
      // Aggregation rows expose the parent name for graph semantics, but the
      // rack faceplate must terminate on each physical member port. Falling
      // back to the raw endpoint keeps older non-member rows compatible.
      const localInterface = localEndpoint?.name
        || localEndpoint?.normalized
        || (reverse ? (raw.target_port_normalized || raw.target_port || '') : (raw.source_port_normalized || raw.source_port || ''));
      const remoteInterface = remoteEndpoint?.name
        || remoteEndpoint?.normalized
        || (reverse ? (raw.source_port_normalized || raw.source_port || '') : (raw.target_port_normalized || raw.target_port || ''));
      const identityBase = raw.id || raw.link_key || [
        localEndpointId || localDevice.id,
        localInterface,
        remoteEndpointId || remoteDevice?.id || remoteName,
        remoteInterface,
      ].join('::');
      const identity = members.length > 1 ? `${identityBase}::member-${memberIndex + 1}` : identityBase;
      const memberIsUp = member
        ? memberSource?.up !== false && memberTarget?.up !== false
        : true;
      const normalizedStatus = normalizeStatus(raw.operational_state || raw.status);
      const status = member && !memberIsUp ? 'down' : normalizedStatus;

      return [{
        id: identity,
        local_device_id: localEndpointId || localDevice.networkDeviceId || localDevice.id,
        local_device_name: localName || localDevice.name,
        local_interface: localInterface,
        remote_device_id: remoteEndpointId || remoteDevice?.networkDeviceId || remoteDevice?.id,
        remote_device_name: remoteName || remoteDevice?.name,
        remote_interface: remoteInterface,
        speed_mbps: member?.source?.speed_mbps ?? raw.bandwidth_mbps ?? raw.speed_mbps ?? undefined,
        status,
        cable_type: inferCableType(localInterface, remoteInterface, raw.cable_type, localDevice, remoteDevice),
        discovery_source: raw.discovery_source || member?.protocol || undefined,
        aggregation_protocol: raw.aggregation_protocol || undefined,
        link_kind: normalizedLinkKind === 'aggregation' ? 'aggregation' : 'physical',
        member_index: members.length > 1 ? memberIndex : undefined,
        member_count: members.length > 1 ? members.length : undefined,
        aggregation_name: reverse ? raw.target_aggregation_name : raw.source_aggregation_name,
      }];
    });
  });

  return Array.from(new Map(normalized.map((link) => [link.id, link])).values());
}
