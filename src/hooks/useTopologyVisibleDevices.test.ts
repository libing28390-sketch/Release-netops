import { describe, expect, it } from 'vitest';
import type { Device } from '../types';
import { NETWORK_TOPOLOGY_ROLE_VALUES } from '../domain/topologyRoles';
import { getTopologyRoleKey, getTopologyRoleOptions, matchesTopologyStatusFilter } from './useTopologyVisibleDevices';

const deviceWithRole = (role: string): Device => ({
  id: `device-${role}`,
  hostname: `device-${role}`,
  role,
} as Device);

describe('topology role catalog', () => {
  it('always exposes every role available in the asset import template', () => {
    expect(getTopologyRoleOptions([])).toEqual(NETWORK_TOPOLOGY_ROLE_VALUES);
    expect(getTopologyRoleOptions([])).toHaveLength(16);
  });

  it.each(NETWORK_TOPOLOGY_ROLE_VALUES)('preserves canonical role %s without fingerprint reclassification', (role) => {
    expect(getTopologyRoleKey(deviceWithRole(role))).toBe(role);
  });

  it('maps legacy role names to the shared canonical catalog', () => {
    expect(getTopologyRoleKey(deviceWithRole('core_switch'))).toBe('core');
    expect(getTopologyRoleKey(deviceWithRole('aggregation_switch'))).toBe('distribution');
    expect(getTopologyRoleKey(deviceWithRole('wireless_ac'))).toBe('wireless_controller');
  });
});

describe('topology status filter', () => {
  it('matches canonical status values even when inventory casing or whitespace differs', () => {
    expect(matchesTopologyStatusFilter({ status: ' Online ' } as unknown as Pick<Device, 'status'>, 'online')).toBe(true);
    expect(matchesTopologyStatusFilter({ status: 'offline' } as Pick<Device, 'status'>, 'online')).toBe(false);
    expect(matchesTopologyStatusFilter({ status: 'pending' } as Pick<Device, 'status'>, 'all')).toBe(true);
  });
});
