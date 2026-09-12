import { useCallback, useEffect, useState } from 'react';
import { createReconciliationRun, listReconciliationFindings, listReconciliationRuns } from '../api/ipam';
import type { ReconciliationFinding, ReconciliationRun } from '../types/ipam';

export function useIpamReconciliation() {
  const [runs, setRuns] = useState<ReconciliationRun[]>([]);
  const [findings, setFindings] = useState<ReconciliationFinding[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const refresh = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const response = await listReconciliationRuns();
      setRuns(response.items);
      setFindings(await listReconciliationFindings(response.items[0]?.id || '', ''));
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setLoading(false); }
  }, []);
  const run = useCallback(async () => { await createReconciliationRun(); await refresh(); }, [refresh]);
  useEffect(() => { void refresh(); }, [refresh]);
  return { runs, findings, loading, error, refresh, run };
}
