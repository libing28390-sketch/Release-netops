import { useEffect, useState } from 'react';
import type { Device } from '../types';

export const useInventoryUiState = () => {
  const [inventoryPage, setInventoryPage] = useState(1);
  const [inventoryPageSize, setInventoryPageSize] = useState(10);
  const [inventorySearch, setInventorySearch] = useState('');
  const [inventoryPlatformFilter, setInventoryPlatformFilter] = useState('all');
  const [inventoryRoleFilter, setInventoryRoleFilter] = useState('all');
  const [inventoryStatusFilter, setInventoryStatusFilter] = useState('all');
  const [inventoryLifecycleFilter, setInventoryLifecycleFilter] = useState('all');
  const [inventorySortConfig, setInventorySortConfig] = useState<{ key: keyof Device; direction: 'asc' | 'desc' } | null>(null);
  const [selectedDeviceIds, setSelectedDeviceIds] = useState<string[]>([]);

  useEffect(() => {
    setInventoryPage(1);
  }, [inventorySearch, inventoryPlatformFilter, inventoryRoleFilter, inventoryStatusFilter, inventoryPageSize]);

  useEffect(() => {
    setSelectedDeviceIds([]);
  }, [inventorySearch, inventoryPlatformFilter, inventoryRoleFilter, inventoryStatusFilter, inventorySortConfig, inventoryPage]);

  return {
    inventoryPage,
    setInventoryPage,
    inventoryPageSize,
    setInventoryPageSize,
    inventorySearch,
    setInventorySearch,
    inventoryPlatformFilter,
    setInventoryPlatformFilter,
    inventoryRoleFilter,
    setInventoryRoleFilter,
    inventoryStatusFilter,
    setInventoryStatusFilter,
    inventoryLifecycleFilter,
    setInventoryLifecycleFilter,
    inventorySortConfig,
    setInventorySortConfig,
    selectedDeviceIds,
    setSelectedDeviceIds,
  };
};
