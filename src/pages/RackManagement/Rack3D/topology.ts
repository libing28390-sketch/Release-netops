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
  operational_state?: string;
  status?: string;
  bandwidth_mbps?: number | null;
  speed_mbps?: number | null;
  cable_type?: string;
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

    const reverse = !sourceDevice && Boolean(targetDevice);
    const localDevice = reverse ? targetDevice! : sourceDevice!;
    const remoteDevice = reverse ? sourceDevice : targetDevice;
    const localEndpointId = reverse ? raw.target_device_id : raw.source_device_id;
    const remoteEndpointId = reverse ? raw.source_device_id : raw.target_device_id;
    const localName = reverse ? targetName : sourceName;
    const remoteName = reverse ? sourceName : targetName;
    const localInterface = reverse
      ? (raw.target_aggregation_name || raw.target_port_normalized || raw.target_port || '')
      : (raw.source_aggregation_name || raw.source_port_normalized || raw.source_port || '');
    const remoteInterface = reverse
      ? (raw.source_aggregation_name || raw.source_port_normalized || raw.source_port || '')
      : (raw.target_aggregation_name || raw.target_port_normalized || raw.target_port || '');
    const identity = raw.id || raw.link_key || [
      localEndpointId || localDevice.id,
      localInterface,
      remoteEndpointId || remoteDevice?.id || remoteName,
      remoteInterface,
    ].join('::');

    return [{
      id: identity,
      local_device_id: localEndpointId || localDevice.networkDeviceId || localDevice.id,
      local_device_name: localName || localDevice.name,
      local_interface: localInterface,
      remote_device_id: remoteEndpointId || remoteDevice?.networkDeviceId || remoteDevice?.id,
      remote_device_name: remoteName || remoteDevice?.name,
      remote_interface: remoteInterface,
      speed_mbps: raw.bandwidth_mbps ?? raw.speed_mbps ?? undefined,
      status: normalizeStatus(raw.operational_state || raw.status),
      cable_type: normalizeCableType(raw.cable_type),
    }];
  });

  return Array.from(new Map(normalized.map((link) => [link.id, link])).values());
}
