import { useCallback, useEffect, useState } from 'react';
import { listSites, listTenants, listVlans, listVrfs } from '../api/cmdb';
import type { Site, Tenant, Vlan, Vrf } from '../types/cmdb';

export function useCmdbLookups() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [sites, setSites] = useState<Site[]>([]);
  const [vrfs, setVrfs] = useState<Vrf[]>([]);
  const [vlans, setVlans] = useState<Vlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const refresh = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [tenantRows, siteRows, vrfRows, vlanRows] = await Promise.all([listTenants(), listSites(), listVrfs(), listVlans()]);
      setTenants(tenantRows); setSites(siteRows); setVrfs(vrfRows); setVlans(vlanRows);
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  return { tenants, sites, vrfs, vlans, loading, error, refresh };
}
