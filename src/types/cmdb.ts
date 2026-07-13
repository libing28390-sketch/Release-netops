export interface Tenant { id: string; name: string; description?: string }
export interface Site { id: string; site_code: string; site_name: string; tenant_id: string; status: string }
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
  siteCode: string;
  siteName: string;
  vrfName: string;
  vlanId: number;
  vlanName: string;
  prefix: string;
}
