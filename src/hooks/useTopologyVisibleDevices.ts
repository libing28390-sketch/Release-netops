import { useMemo } from 'react';
import type { Device } from '../types';

interface UseTopologyVisibleDevicesParams {
  devices: Device[];
  topologySearch: string;
  topologyStatusFilter: 'all' | 'online' | 'offline' | 'pending';
  topologyRoleFilter: string;
  topologySiteFilter: string;
}

export const useTopologyVisibleDevices = ({
  devices,
  topologySearch,
  topologyStatusFilter,
  topologyRoleFilter,
  topologySiteFilter,
}: UseTopologyVisibleDevicesParams) => {
  const topologySiteOptions = useMemo(() => {
    const sites = new Map<string, string>();
    devices.forEach((device) => {
      const id = String(device.site_id || device.site || '').trim();
      if (id) sites.set(id, String(device.site || id));
    });
    return Array.from(sites.entries())
      .map(([id, name]) => ({ id, name }))
      .sort((left, right) => left.name.localeCompare(right.name));
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
      const matchesSite = topologySiteFilter === 'all' || String(device.site_id || device.site || '') === topologySiteFilter;
      return matchesQuery && matchesStatus && matchesRole && matchesSite;
    });

    // Unmanaged LLDP/CDP peers are retained by the discovery API as evidence,
    // but they are not CMDB assets and should not become pseudo-devices on the
    // primary topology canvas. Rendering them as "?" nodes makes a confirmed
    // device chain look disconnected and noisy. They remain available to the
    // backend/inspection views for later onboarding.
    return managed;
  }, [devices, topologyRoleFilter, topologySearch, topologySiteFilter, topologyStatusFilter]);

  return {
    topologySiteOptions,
    topologyRoleOptions,
    topologyVisibleDevices,
  };
};
