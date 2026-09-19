import type { Device } from '../types';

const SERVER_PLATFORMS = new Set([
  'linux', 'ubuntu', 'centos', 'debian', 'redhat', 'windows', 'windows_server',
  'linux_server', 'vmware', 'esxi',
]);
const SERVER_ROLES = new Set(['server', 'host', 'vm', 'virtual-machine', 'hypervisor', 'storage']);

/** Keep server assets out of every network topology read model and its links. */
export const isTopologyServerDevice = (device: Pick<Device, 'role' | 'device_category' | 'platform'>): boolean => {
  const role = String(device.role || '').trim().toLowerCase().replaceAll('_', '-');
  const platform = String(device.platform || '').trim().toLowerCase().replaceAll('-', '_');
  if (SERVER_ROLES.has(role) || SERVER_PLATFORMS.has(platform)) return true;
  return [device.device_category, device.platform].some((value) =>
    /server|服务器|虚拟机|hypervisor|esxi|vmware/i.test(String(value || '')),
  );
};

export const excludeServerTopologyDevices = <T extends Pick<Device, 'id' | 'role' | 'device_category' | 'platform'>>(
  devices: T[],
) => {
  const excludedIds = new Set(devices.filter(isTopologyServerDevice).map((device) => device.id));
  return {
    devices: devices.filter((device) => !excludedIds.has(device.id)),
    excludedIds,
  };
};
