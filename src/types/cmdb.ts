export interface Tenant { id: string; name: string; description?: string }
export interface Site { id: string; site_code: string; site_name: string; country?: string; state_province?: string; city?: string; district?: string; contact_name?: string; contact_phone?: string; contact_email?: string; tenant_id: string; status: string; created_at?: string; updated_at?: string }
export interface Vrf { id: string; vrf_name: string; tenant_id: string; rd?: string }
export interface Vlan {
  id: string;
  vlan_id: number;
  name: string;
  description?: string;
  site_id?: string;
  site_code?: string;
  site_name?: string;
  tenant_id: string;
  vrf_name?: string;
  prefixes?: string;
  gateway?: string;
  gateway_device?: string;
  gateway_interface?: string;
  svi_interfaces?: string;
  port_details?: string;
  device_count?: number;
  port_count?: number;
  mac_count?: number;
  arp_count?: number;
  business_systems?: string;
  business_count?: number;
  business_departments?: string;
  business_owners?: string;
  department?: string;
  owner?: string;
  highest_business_level?: string;
  last_discovered_at?: string;
  endpoint_last_seen_at?: string;
  endpoint_details?: Array<{
    source: 'arp' | 'mac' | string;
    ip_address?: string;
    mac_address?: string;
    interface_name?: string;
    device_hostname?: string;
    device_ip?: string;
    last_updated?: string;
  }>;
}

export interface CmdbEnvelope<T> {
  success: boolean;
  data: T;
  message: string;
}

export interface SiteFoundationInput {
  tenantId?: string;
  tenantName?: string;
  siteCode?: string;
  siteName: string;
  stateProvince?: string;
  city?: string;
  district?: string;
  contactName?: string;
  contactPhone?: string;
  contactEmail?: string;
  vrfName: string;
  vlanId: number;
  vlanName: string;
  prefix: string;
}
