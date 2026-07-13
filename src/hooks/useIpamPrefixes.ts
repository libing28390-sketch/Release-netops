import { useCallback, useEffect, useState } from 'react';
import { listPrefixes } from '../api/ipam';
import type { IpamPrefix } from '../types/ipam';

export function useIpamPrefixes(search = '') {
  const [prefixes, setPrefixes] = useState<IpamPrefix[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const refresh = useCallback(async () => {
    setLoading(true); setError('');
    try { setPrefixes(await listPrefixes(search)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setLoading(false); }
  }, [search]);
  useEffect(() => { void refresh(); }, [refresh]);
  return { prefixes, loading, error, refresh };
}
