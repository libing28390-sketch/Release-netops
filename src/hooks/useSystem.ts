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

const SYSTEM_INFO_CACHE_TTL_MS = 300_000;

let cachedSystemInfo: SystemInfo | null = null;
let cachedSystemInfoAt = 0;
let cachedSystemInfoToken = '';
let inFlightSystemInfoPromise: Promise<SystemInfo | null> | null = null;
const systemInfoListeners = new Set<(info: SystemInfo | null) => void>();

const notifySystemInfoListeners = (info: SystemInfo | null) => {
  systemInfoListeners.forEach((listener) => listener(info));
};

export function resetSystemInfoCache(): void {
  cachedSystemInfo = null;
  cachedSystemInfoAt = 0;
  cachedSystemInfoToken = '';
  inFlightSystemInfoPromise = null;
  notifySystemInfoListeners(null);
}

async function fetchSharedSystemInfo(force = false): Promise<SystemInfo | null> {
  const token = typeof localStorage !== 'undefined' ? (localStorage.getItem('netops_token') || '') : '';
  const cacheFresh = cachedSystemInfo !== null
    && cachedSystemInfoToken === token
    && (Date.now() - cachedSystemInfoAt) < SYSTEM_INFO_CACHE_TTL_MS;

  if (!force && cacheFresh) {
    return cachedSystemInfo;
  }
  if (!force && inFlightSystemInfoPromise && cachedSystemInfoToken === token) {
    return inFlightSystemInfoPromise;
  }

  cachedSystemInfoToken = token;
  const request = (async (): Promise<SystemInfo | null> => {
    try {
      const resp = await fetch('/api/system/info', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!resp.ok) return cachedSystemInfo;
      const data: SystemInfo = await resp.json();
      cachedSystemInfo = data;
      cachedSystemInfoAt = Date.now();
      notifySystemInfoListeners(data);
      return data;
    } catch (err) {
      console.error('Failed to fetch system info:', err);
      return cachedSystemInfo;
    } finally {
      if (inFlightSystemInfoPromise === request) {
        inFlightSystemInfoPromise = null;
      }
    }
  })();

  inFlightSystemInfoPromise = request;
  return request;
}

export function useSystem() {
  const [systemInfo, setSystemInfo] = useState<SystemInfo | null>(() => cachedSystemInfo);
  const [loading, setLoading] = useState<boolean>(() => cachedSystemInfo === null);

  const fetchSystemInfo = useCallback(async (force = false) => {
    const info = await fetchSharedSystemInfo(force);
    setSystemInfo(info);
    setLoading(false);
    return info;
  }, []);

  useEffect(() => {
    let active = true;
    const listener = (next: SystemInfo | null) => {
      if (active) {
        setSystemInfo(next);
        setLoading(false);
      }
    };
    systemInfoListeners.add(listener);

    if (cachedSystemInfo === null || (Date.now() - cachedSystemInfoAt) >= SYSTEM_INFO_CACHE_TTL_MS) {
      void fetchSharedSystemInfo(false).then((info) => {
        if (!active) return;
        setSystemInfo(info);
        setLoading(false);
      });
    } else {
      setSystemInfo(cachedSystemInfo);
      setLoading(false);
    }

    return () => {
      active = false;
      systemInfoListeners.delete(listener);
    };
  }, []);

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
    edition: systemInfo?.edition || 'Standard',
  };
}
