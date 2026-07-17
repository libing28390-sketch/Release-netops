export interface Tenant { id: string; name: string; description?: string }
export interface Site { id: string; site_code: string; site_name: string; country?: string; state_province?: string; city?: string; district?: string; contact_name?: string; contact_phone?: string; contact_email?: string; tenant_id: string; status: string; created_at?: string; updated_at?: string }
export interface Vrf { id: string; vrf_name: string; tenant_id: string; rd?: string }
export interface Vlan { id: string; vlan_id: number; name: string; site_id?: string; tenant_id: string }

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
