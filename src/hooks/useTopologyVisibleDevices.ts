import { useMemo } from 'react';
import type { Device } from '../types';

interface UseTopologyVisibleDevicesParams {
  devices: Device[];
  topologySearch: string;
  topologyStatusFilter: 'all' | 'online' | 'offline' | 'pending';
  topologyRoleFilter: string;
  topologySiteFilter: string;
  topologyUnmanagedNodes: any[];
}

export const useTopologyVisibleDevices = ({
  devices,
  topologySearch,
  topologyStatusFilter,
  topologyRoleFilter,
  topologySiteFilter,
  topologyUnmanagedNodes,
}: UseTopologyVisibleDevicesParams) => {
  const topologySiteOptions = useMemo(() => {
    const siteValues: string[] = devices
      .map((device) => String(device.site || '').trim())
      .filter((value): value is string => Boolean(value));
    const uniqueSites: string[] = [...new Set<string>(siteValues)];
    uniqueSites.sort((left: string, right: string) => left.localeCompare(right));
    return uniqueSites;
  }, [devices]);

  const topologyRoleOptions = useMemo(() => {
    const roleValues: string[] = devices
      .map((device) => String(device.role || '').trim())
      .filter((value): value is string => Boolean(value));
    const uniqueRoles: string[] = [...new Set<string>(roleValues)];
    uniqueRoles.sort((left: string, right: string) => left.localeCompare(right));
    return uniqueRoles;
  }, [devices]);

  const topologyVisibleDevices = useMemo(() => {
    const query = topologySearch.trim().toLowerCase();
    const managed = devices.filter((device) => {
      const matchesQuery = !query || [device.hostname, device.ip_address, device.site, device.role].some((value) => String(value || '').toLowerCase().includes(query));
      const matchesStatus = topologyStatusFilter === 'all' || device.status === topologyStatusFilter;
      const matchesRole = topologyRoleFilter === 'all' || String(device.role || '') === topologyRoleFilter;
      const matchesSite = topologySiteFilter === 'all' || String(device.site || '') === topologySiteFilter;
      return matchesQuery && matchesStatus && matchesRole && matchesSite;
    });

    const managedIds = new Set(managed.map((d) => d.id));
    const unmanagedPseudo: Device[] = topologyUnmanagedNodes
      .filter((n: any) => {
        const connectedIds: string[] = n.connected_device_ids || [];
        return connectedIds.some((id: string) => managedIds.has(id));
      })
      .filter((n: any) => {
        if (!query) return true;
        return [n.hostname, n.ip_address].some((v: string) => String(v || '').toLowerCase().includes(query));
      })
      .map((n: any) => ({
        id: n.id,
        hostname: n.hostname || 'Unknown',
        ip_address: n.ip_address || '',
        platform: '',
        status: 'unmanaged' as unknown as Device['status'],
        compliance: 'unknown' as const,
        sn: '',
        model: '',
        version: '',
        role: '',
        site: '',
        uptime: '',
        connection_method: 'ssh' as const,
        config_history: [],
        is_unmanaged: true,
      } satisfies Device & { is_unmanaged: boolean } as Device));

    return [...managed, ...unmanagedPseudo];
  }, [devices, topologyRoleFilter, topologySearch, topologySiteFilter, topologyStatusFilter, topologyUnmanagedNodes]);

  return {
    topologySiteOptions,
    topologyRoleOptions,
    topologyVisibleDevices,
  };
};
