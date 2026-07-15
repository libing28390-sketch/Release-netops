import { useEffect, useState } from 'react';
import type { Device } from '../types';

interface UseInventoryPageDataParams {
  isAuthenticated: boolean;
  activeTab: string;
  inventorySubPage: string;
  inventorySearch: string;
  inventoryPlatformFilter: string;
  inventoryRoleFilter: string;
  inventoryStatusFilter: string;
  inventoryPage: number;
  inventoryPageSize: number;
  inventorySortConfig: { key: keyof Device; direction: 'asc' | 'desc' } | null;
  normalizeDeviceRecord: (record: any) => Device;
}

export const useInventoryPageData = ({
  isAuthenticated,
  activeTab,
  inventorySubPage,
  inventorySearch,
  inventoryPlatformFilter,
  inventoryRoleFilter,
  inventoryStatusFilter,
  inventoryPage,
  inventoryPageSize,
  inventorySortConfig,
  normalizeDeviceRecord,
}: UseInventoryPageDataParams) => {
  const [inventoryRefreshTick, setInventoryRefreshTick] = useState(0);
  const [inventoryRows, setInventoryRows] = useState<Device[]>([]);
  const [inventoryTotal, setInventoryTotal] = useState(0);
  const [inventoryStatusCounts, setInventoryStatusCounts] = useState<Record<string, number>>({});
  const [inventoryLoading, setInventoryLoading] = useState(false);
  const [assetsTotal, setAssetsTotal] = useState(0);

  useEffect(() => {
    if (!isAuthenticated || activeTab !== 'inventory' || inventorySubPage !== 'devices') return;

    let cancelled = false;
    const fetchInventoryPage = async () => {
      setInventoryLoading(true);
      try {
        const params = new URLSearchParams({
          search: inventorySearch,
          platform: inventoryPlatformFilter,
          role: inventoryRoleFilter,
          status: inventoryStatusFilter,
          page: String(inventoryPage),
          page_size: String(inventoryPageSize),
          sort_key: inventorySortConfig?.key || 'hostname',
          sort_direction: inventorySortConfig?.direction || 'asc',
          asset_type: 'network_device',
        });

        const resp = await fetch(`/api/devices?${params.toString()}`);
        if (!resp.ok) throw new Error('Failed to fetch inventory data');
        const data = await resp.json();
        if (cancelled) return;

        if (Array.isArray(data)) {
          setInventoryRows(data.map((item: any) => normalizeDeviceRecord(item)));
          setInventoryTotal(data.length);
          setInventoryStatusCounts({});
        } else {
          setInventoryRows(Array.isArray(data.items) ? data.items.map((item: any) => normalizeDeviceRecord(item)) : []);
          setInventoryTotal(typeof data.total === 'number' ? data.total : 0);
          setInventoryStatusCounts(data.status_counts && typeof data.status_counts === 'object' ? data.status_counts : {});
        }
      } catch {
        if (cancelled) return;
        setInventoryRows([]);
        setInventoryTotal(0);
        setInventoryStatusCounts({});
      } finally {
        if (!cancelled) setInventoryLoading(false);
      }
    };

    fetchInventoryPage();
    return () => {
      cancelled = true;
    };
  }, [
    isAuthenticated,
    activeTab,
    inventorySubPage,
    inventorySearch,
    inventoryPlatformFilter,
    inventoryRoleFilter,
    inventoryStatusFilter,
    inventorySortConfig,
    inventoryPage,
    inventoryPageSize,
    inventoryRefreshTick,
    normalizeDeviceRecord,
  ]);

  useEffect(() => {
    if (!isAuthenticated) return;
    const fetchAssetsTotal = async () => {
      try {
        const resp = await fetch('/api/assets/summary');
        if (resp.ok) {
          const data = await resp.json();
          setAssetsTotal(data.total || 0);
        }
      } catch {
        // Ignore summary fetch error in dashboard shortcut card.
      }
    };
    fetchAssetsTotal();
  }, [isAuthenticated]);

  return {
    inventoryRefreshTick,
    setInventoryRefreshTick,
    inventoryRows,
    inventoryTotal,
    inventoryStatusCounts,
    inventoryLoading,
    assetsTotal,
  };
};
