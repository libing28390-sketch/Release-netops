import type { SessionUser } from '../../types';

export interface WebAccessProfile {
  id?: string;
  asset_id?: string;
  profile_name: string;
  scheme: 'http' | 'https';
  port: number | string;
  path: string;
  enabled: boolean;
  credential_mode?: 'inherit_asset' | 'independent';
  normal_username?: string;
  normal_password?: string;
  normal_password_set?: boolean;
  admin_username?: string;
  admin_password?: string;
  admin_password_set?: boolean;
  credential_id?: string;
  admin_credential_id?: string;
  created_at?: string;
  updated_at?: string;
}

export interface Asset {
  id: string;
  asset_type: string;
  asset_tag: string;
  serial_number: string;
  vendor: string;
  model: string;
  hostname: string;
  site_id: string;
  site_name?: string;
  site_code?: string;
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
  online_status?: 'online' | 'offline' | 'pending' | string;
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
  snmp_credential_id?: string;
  snmp_community_set?: boolean;
  created_at: string;
  updated_at: string;
  device_id?: string;
  tags?: Array<{
    id: string;
    category: string;
    value: string;
    label: string;
    label_zh: string;
    color: string;
    code?: string;
  }>;
  tag_ids?: string[];
  admin_username?: string;
  normal_username?: string;
  management_port?: number;
  is_managed?: number;
  takeover_error?: string;
  device_category?: string;
  function?: string;
  zone?: string;
  power_watts?: number | string;
  web_profiles?: WebAccessProfile[];
}

export interface AssetSummary {
  total: number;
  by_type: Record<string, number>;
  by_status: Record<string, number>;
  by_vendor: Record<string, number>;
  by_site: Record<string, number>;
  by_department: Record<string, number>;
  warranty_expiring_soon: number;
}

export interface AssetManagementTabProps {
  language: string;
  t: (key: string) => string;
  setActiveTab?: (tab: string) => void;
  currentUser?: Pick<SessionUser, 'role'>;
}
