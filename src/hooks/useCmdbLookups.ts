import { useCallback, useEffect, useState } from 'react';
import { listSites, listVlans, listVrfs } from '../api/cmdb';
import type { Site, Vlan, Vrf } from '../types/cmdb';

export function useCmdbLookups() {
  const [sites, setSites] = useState<Site[]>([]);
  const [vrfs, setVrfs] = useState<Vrf[]>([]);
  const [vlans, setVlans] = useState<Vlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const refresh = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [siteRows, vrfRows, vlanRows] = await Promise.all([listSites(), listVrfs(), listVlans()]);
      setSites(siteRows); setVrfs(vrfRows); setVlans(vlanRows);
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  return { sites, vrfs, vlans, loading, error, refresh };
}
