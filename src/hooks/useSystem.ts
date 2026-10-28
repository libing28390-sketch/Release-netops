import { useState, useEffect, useCallback } from 'react';

export interface SystemInfo {
  version: string;
  edition: 'Standard' | 'Professional' | 'Enterprise' | 'Trial';
  build_date: string;
  project_name: string;
  system_name: string;
  environment?: string;
  license: {
    valid: boolean;
    customer_id: string;
    edition: string;
    expiration_date: string;
    max_version?: string;
    current_version: string;
    error?: string;
  };
}

export function useSystem() {
  const [systemInfo, setSystemInfo] = useState<SystemInfo | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchSystemInfo = useCallback(async () => {
    try {
      const token = localStorage.getItem('netops_token');
      const resp = await fetch('/api/system/info', {
        headers: token ? { Authorization: `Bearer ${token}` } : {}
      });
      if (resp.ok) {
        setSystemInfo(await resp.json());
      }
    } catch (err) {
      console.error('Failed to fetch system info:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSystemInfo();
  }, [fetchSystemInfo]);

  const isFeatureEnabled = useCallback((feature: string) => {
    if (!systemInfo) return true; // Default to true until info loaded
    const edition = systemInfo.edition;

    switch (feature) {
      case 'compliance':
      case 'monitoring_advanced':
        return edition === 'Professional' || edition === 'Enterprise';
      case 'user_management':
      case 'audit_logs':
        return edition === 'Standard' || edition === 'Professional' || edition === 'Enterprise';
      default:
        return true;
    }
  }, [systemInfo]);

  return { 
    systemInfo, 
    loading, 
    fetchSystemInfo,
    isFeatureEnabled,
    edition: systemInfo?.edition || 'Standard'
  };
}
