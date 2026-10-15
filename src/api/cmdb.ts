import { apiRequest } from './http';
import { DEFAULT_TENANT_ID, type CmdbEnvelope, type Site, type SiteFoundationInput, type Vlan, type Vrf } from '../types/cmdb';
import { createPrefix } from './ipam';

export const listSites = async () => (await apiRequest<CmdbEnvelope<Site[]>>('/api/cmdb/sites')).data;
export const listVrfs = async () => (await apiRequest<CmdbEnvelope<Vrf[]>>('/api/cmdb/vrfs')).data;
export const listVlans = async () => (await apiRequest<CmdbEnvelope<Vlan[]>>('/api/cmdb/vlans')).data;

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
  const tenant = { id: DEFAULT_TENANT_ID };
  const site = await createSite({
    site_code: input.siteCode, site_name: input.siteName, tenant_id: DEFAULT_TENANT_ID,
    country: '', state_province: input.stateProvince || '', city: input.city || '', district: input.district || '',
    contact_name: input.contactName || '', contact_phone: input.contactPhone || '', contact_email: input.contactEmail || '',
    timezone: 'Asia/Shanghai', address: '', status: 'active',
  });
  const vrf = await createVrf({ vrf_name: input.vrfName, tenant_id: DEFAULT_TENANT_ID, rd: '', description: '' });
  const vlan = await createVlan({
    vlan_id: input.vlanId, name: input.vlanName, site_id: site.id,
    tenant_id: DEFAULT_TENANT_ID, status: 'active',
  });
  const prefix = await createPrefix({
    prefix: input.prefix, name: `${input.siteName}-${input.vlanName}`,
    tenant_id: DEFAULT_TENANT_ID, site_id: site.id, vrf_id: vrf.id, vlan_id: vlan.id,
    status: 'active', gateway: '', description: 'Created by site initialization workflow',
    network_type: 'server', traceable: 1,
  });
  return { tenant, site, vrf, vlan, prefix };
}
