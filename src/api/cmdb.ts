import { apiRequest } from './http';
import type { CmdbEnvelope, Site, SiteFoundationInput, Tenant, Vlan, Vrf } from '../types/cmdb';
import { createPrefix } from './ipam';

export const listTenants = async () => (await apiRequest<CmdbEnvelope<Tenant[]>>('/api/cmdb/tenants')).data;
export const listSites = async () => (await apiRequest<CmdbEnvelope<Site[]>>('/api/cmdb/sites')).data;
export const listVrfs = async () => (await apiRequest<CmdbEnvelope<Vrf[]>>('/api/cmdb/vrfs')).data;
export const listVlans = async () => (await apiRequest<CmdbEnvelope<Vlan[]>>('/api/cmdb/vlans')).data;

export const createTenant = async (name: string) => (
  await apiRequest<CmdbEnvelope<Tenant>>('/api/cmdb/tenants', {
    method: 'POST', body: JSON.stringify({ name, description: '' }),
  })
).data;

export const createSite = async (payload: Record<string, unknown>) => (
  await apiRequest<CmdbEnvelope<Site>>('/api/cmdb/sites', { method: 'POST', body: JSON.stringify(payload) })
).data;

export const createVrf = async (payload: Record<string, unknown>) => (
  await apiRequest<CmdbEnvelope<Vrf>>('/api/cmdb/vrfs', { method: 'POST', body: JSON.stringify(payload) })
).data;

export const createVlan = async (payload: Record<string, unknown>) => (
  await apiRequest<CmdbEnvelope<Vlan>>('/api/cmdb/vlans', { method: 'POST', body: JSON.stringify(payload) })
).data;

export async function createSiteFoundation(input: SiteFoundationInput) {
  const tenant = input.tenantId
    ? { id: input.tenantId }
    : await createTenant(input.tenantName?.trim() || `${input.siteName} Tenant`);
  const site = await createSite({
    site_code: input.siteCode, site_name: input.siteName, tenant_id: tenant.id,
    country: '', state_province: input.stateProvince || '', city: input.city || '', district: input.district || '',
    contact_name: input.contactName || '', contact_phone: input.contactPhone || '', contact_email: input.contactEmail || '',
    timezone: 'Asia/Shanghai', address: '', status: 'active',
  });
  const vrf = await createVrf({ vrf_name: input.vrfName, tenant_id: tenant.id, rd: '', description: '' });
  const vlan = await createVlan({
    vlan_id: input.vlanId, name: input.vlanName, site_id: site.id,
    tenant_id: tenant.id, status: 'active',
  });
  const prefix = await createPrefix({
    prefix: input.prefix, name: `${input.siteName}-${input.vlanName}`,
    tenant_id: tenant.id, site_id: site.id, vrf_id: vrf.id, vlan_id: vlan.id,
    status: 'active', gateway: '', description: 'Created by site initialization workflow',
    network_type: 'server', traceable: 1,
  });
  return { tenant, site, vrf, vlan, prefix };
}
