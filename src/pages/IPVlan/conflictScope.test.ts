import { describe, expect, it } from 'vitest';
import { subnetHasScopedConflict } from './conflictScope';
import type { Conflict, Subnet } from './types';

const subnet = (id: string, address_space_id: string | null): Pick<Subnet, 'id' | 'address_space_id'> => ({
  id,
  address_space_id,
});

describe('subnetHasScopedConflict', () => {
  it('does not carry a same-CIDR conflict into another address space', () => {
    const conflicts: Conflict = {
      ip_conflicts: [{ address_space_id: 'space-a', address: '10.0.0.10', subnets: 'prefix-a,prefix-b', cnt: 2 }],
      mac_conflicts: [],
      total_conflicts: 1,
    };

    expect(subnetHasScopedConflict(subnet('prefix-a', 'space-a'), conflicts)).toBe(true);
    expect(subnetHasScopedConflict(subnet('prefix-a-other-space', 'space-b'), conflicts)).toBe(false);
  });

  it('fails closed for legacy subnets without explicit address-space identity', () => {
    const conflicts: Conflict = {
      ip_conflicts: [{ address_space_id: 'space-a', address: '10.0.0.10', subnets: 'prefix-a', cnt: 2 }],
      mac_conflicts: [],
      total_conflicts: 1,
    };

    expect(subnetHasScopedConflict(subnet('prefix-a', null), conflicts)).toBe(false);
  });
});
