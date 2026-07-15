export interface Subnet {
  id: string;
  name: string;
  network: string;
  prefix_len: number;
  vlan_id: number | null;
  vlan_name: string;
  gateway: string;
  description: string;
  site: string;
  status: string;
  total_ips: number;
  used_ips: number;
  utilization: number;
}

export interface IPAddress {
  id: string;
  subnet_id: string;
  address: string;
  hostname: string;
  device_id: string;
  interface_name: string;
  mac_address: string;
  device_type: string;
  status: string;
  description: string;
  last_seen: string;
}

export interface Conflict {
  ip_conflicts: { address: string; subnets: string; cnt: number }[];
  mac_conflicts: { mac_address: string; addresses: string; cnt: number }[];
  total_conflicts: number;
}

export interface IPVlanTabProps {
  language: string;
  t: (key: string) => string;
}
