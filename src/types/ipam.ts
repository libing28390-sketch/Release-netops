export type AddressStatus = 'available' | 'reserved' | 'allocated' | 'active' | 'dhcp' | 'vip' | 'deprecated' | 'released' | 'quarantine';
export type PrefixStatus = 'container' | 'active' | 'reserved' | 'deprecated';

export interface IpamPrefix {
  id: string;
  prefix?: string;
  network?: string;
  prefix_len?: number;
  name: string;
  tenant_id?: string;
  site_id?: string;
  vrf_id?: string;
  status: PrefixStatus;
  utilization?: number;
}

export interface IpamAddress {
  id: string;
  subnet_id: string;
  address: string;
  hostname?: string;
  device_id?: string;
  interface_id?: string;
  interface_name?: string;
  mac_address?: string;
  status: AddressStatus;
  purpose?: string;
  available_after?: string;
}

export interface AddressAllocationInput {
  hostname?: string;
  device_id?: string;
  interface_id?: string;
  interface_name?: string;
  mac_address?: string;
  purpose?: string;
  expires_at?: string;
}

export interface ReconciliationRun {
  id: string;
  status: string;
  total_findings: number;
  open_findings: number;
  started_at: string;
}

export interface ReconciliationFinding {
  id: string;
  run_id: string;
  finding_type: string;
  status: string;
  risk_level: 'low' | 'medium' | 'high';
  target_type?: string;
  target_id?: string;
  observed: Record<string, unknown>;
  current: Record<string, unknown>;
  proposed: Record<string, unknown>;
}
