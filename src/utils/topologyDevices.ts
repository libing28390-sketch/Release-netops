import type { Device } from '../types';
import { topologyDeviceRole, type TopologyRoleLayoutDevice } from './topologyRoleLayout';

export type TopologyDeviceScope = 'all' | 'wired' | 'wireless';

const SERVER_PLATFORMS = new Set([
  'linux', 'ubuntu', 'centos', 'debian', 'redhat', 'windows', 'windows_server',
  'linux_server', 'vmware', 'esxi',
]);
const SERVER_ROLES = new Set(['server', 'host', 'vm', 'virtual-machine', 'hypervisor', 'storage']);

/** Keep server assets out of every network topology read model and its links. */
export const isTopologyServerDevice = (device: Pick<Device, 'asset_type' | 'role' | 'role_identity' | 'device_category' | 'platform'>): boolean => {
  const role = String(device.role || device.role_identity || '').trim().toLowerCase().replaceAll('_', '-');
  const platform = String(device.platform || '').trim().toLowerCase().replaceAll('-', '_');
  if (String(device.asset_type || '').trim().toLowerCase() === 'server'
    || SERVER_ROLES.has(role)
    || SERVER_PLATFORMS.has(platform)) return true;
  return [device.device_category, device.platform, device.role_identity].some((value) =>
    /server|服务器|主机|虚拟机|hypervisor|esxi|vmware/i.test(String(value || '')),
  );
};

export const excludeServerTopologyDevices = <T extends Pick<Device, 'id' | 'asset_type' | 'role' | 'role_identity' | 'device_category' | 'platform'>>(
  devices: T[],
) => {
  const excludedIds = new Set(devices.filter(isTopologyServerDevice).map((device) => device.id));
  return {
    devices: devices.filter((device) => !excludedIds.has(device.id)),
    excludedIds,
  };
};

/** Keep LLDP-only, unmatched peers in diagnostics, but never draw them as extra assets. */
export const projectManagedTopologyCanvas = <
  D extends TopologyRoleLayoutDevice & { is_unmanaged?: boolean },
  L extends { source_device_id?: string; target_device_id?: string; is_unmanaged?: boolean },
>(devices: D[], links: L[], scope: TopologyDeviceScope = 'all') => {
  const managedDevices = devices.filter((device) => {
    if (device.is_unmanaged) return false;
    if (scope === 'all') return true;
    const role = topologyDeviceRole(device);
    const wireless = role === 'wireless_ap' || role === 'wireless_controller' || role === 'wireless';
    return scope === 'wireless' ? wireless : !wireless;
  });
  const managedDeviceIds = new Set(managedDevices.map((device) => device.id));
  const managedLinks = links.filter((link) => (
    !link.is_unmanaged
    && Boolean(link.source_device_id && managedDeviceIds.has(link.source_device_id))
    && Boolean(link.target_device_id && managedDeviceIds.has(link.target_device_id))
  ));

  return { devices: managedDevices, links: managedLinks };
};
