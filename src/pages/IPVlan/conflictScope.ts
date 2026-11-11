import type { Conflict, Subnet } from './types';

export function subnetHasScopedConflict(subnet: Pick<Subnet, 'id' | 'address_space_id'>, conflicts: Conflict): boolean {
  const addressSpaceId = String(subnet.address_space_id || '').trim();
  if (!addressSpaceId) return false;

  return [...conflicts.ip_conflicts, ...conflicts.mac_conflicts].some((item) => {
    if (String(item.address_space_id || '').trim() !== addressSpaceId) return false;
    return String(item.subnets || '')
      .split(',')
      .map((value) => value.trim())
      .includes(subnet.id);
  });
}
