export interface Asset {
  id: string;
  asset_type: string;
  asset_tag: string;
  serial_number: string;
  vendor: string;
  model: string;
  hostname: string;
  datacenter: string;
  rack: string;
  rack_unit: string;
  u_height?: number;
  planned_start_u?: number | null;
  management_ip: string;
  business_ip: string;
  device_role: string;
  vlan: string;
  uplink_switch: string;
  uplink_port: string;
  status: string;
  lifecycle_status: string;
  asset_origin?: 'new' | 'legacy';
  purchase_date: string;
  warranty_expiry: string;
  department: string;
  notes: string;
  platform: string;
  connection_method: string;
  username: string;
  snmp_community: string;
  snmp_port: string;
  created_at: string;
  updated_at: string;
  admin_username?: string;
  normal_username?: string;
  management_port?: number;
  is_managed?: number;
  takeover_error?: string;
  device_category?: string;
  power_watts?: number | string;
}

export interface AssetSummary {
  total: number;
  by_type: Record<string, number>;
  by_status: Record<string, number>;
  by_vendor: Record<string, number>;
  by_datacenter: Record<string, number>;
  by_department: Record<string, number>;
  warranty_expiring_soon: number;
}

export interface AssetManagementTabProps {
  language: string;
  t: (key: string) => string;
  setActiveTab?: (tab: string) => void;
}

export type ViewMode = 'table' | 'group' | 'topology';
export type GroupBy = 'datacenter' | 'department' | 'vendor';
