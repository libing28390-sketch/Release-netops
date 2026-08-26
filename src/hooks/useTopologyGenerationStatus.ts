import { useCallback, useEffect, useState } from 'react';

export type TopologyGenerationStatus = {
  generation: {
    strategy: string;
    automatic: {
      enabled: boolean;
      job_id: string;
      interval_seconds: number;
      scope: string;
    };
    manual: {
      enabled: boolean;
      scopes: string[];
    };
    evidence_ttl_seconds: number;
    stale_retention_seconds: number;
    pipeline: Array<{ stage: string; description: string }>;
  };
  inventory: {
    managed_devices: number;
    eligible_devices: number;
    total_observations: number;
    matched_observations: number;
    ambiguous_observations: number;
    unmatched_observations: number;
    managed_links: number;
    multi_evidence_links: number;
    stale_links: number;
    last_observation_at?: string | null;
  };
  latest_manual_run?: {
    id: string;
    scope: string;
    site_id?: string;
    status: string;
    started_at?: string;
    completed_at?: string | null;
    total_devices?: number;
    success_devices?: number;
    failed_devices?: number;
    last_error_code?: string;
  } | null;
  warnings: Array<{ code: string; count: number; message: string }>;
  health: 'healthy' | 'degraded' | 'empty';
};

const topologyAuthHeaders = (): Record<string, string> => {
  const token = localStorage.getItem('netops_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
};

export const useTopologyGenerationStatus = (refreshKey?: string) => {
  const [status, setStatus] = useState<TopologyGenerationStatus | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch('/api/topology/generation-status', {
        headers: topologyAuthHeaders(),
      });
      if (!response.ok) throw new Error(`topology_generation_status_${response.status}`);
      const payload = await response.json() as TopologyGenerationStatus;
      setStatus(payload);
      setError('');
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'topology_generation_status_failed');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 60_000);
    return () => window.clearInterval(timer);
  }, [refresh, refreshKey]);

  return { status, error, loading, refresh };
};
