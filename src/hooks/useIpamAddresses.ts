import { useCallback, useEffect, useState } from 'react';
import { listAddresses } from '../api/ipam';
import type { IpamAddress } from '../types/ipam';

export function useIpamAddresses(prefixId?: string) {
  const [addresses, setAddresses] = useState<IpamAddress[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const refresh = useCallback(async () => {
    if (!prefixId) { setAddresses([]); return; }
    setLoading(true); setError('');
    try { setAddresses(await listAddresses(prefixId)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setLoading(false); }
  }, [prefixId]);
  useEffect(() => { void refresh(); }, [refresh]);
  return { addresses, loading, error, refresh };
}
