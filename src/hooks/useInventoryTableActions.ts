import { useCallback } from 'react';
import type { Device } from '../types';
import { useInventoryStore } from '../store/inventoryStore';

export const useInventoryTableActions = () => {
  const {
    inventorySortConfig,
    setInventorySortConfig,
    selectedDeviceIds,
    setDeviceToDelete,
    setIsDeletingSelected,
    setShowDeleteModal,
  } = useInventoryStore();

  const handleSort = useCallback((key: keyof Device) => {
    let direction: 'asc' | 'desc' = 'asc';
    if (inventorySortConfig && inventorySortConfig.key === key && inventorySortConfig.direction === 'asc') {
      direction = 'desc';
    }
    setInventorySortConfig({ key, direction });
  }, [inventorySortConfig, setInventorySortConfig]);

  const handleDeleteDevice = useCallback((id: string) => {
    setDeviceToDelete(id);
    setIsDeletingSelected(false);
    setShowDeleteModal(true);
  }, [setDeviceToDelete, setIsDeletingSelected, setShowDeleteModal]);

  const handleDeleteSelected = useCallback(() => {
    if (selectedDeviceIds.length === 0) return;
    setIsDeletingSelected(true);
    setDeviceToDelete(null);
    setShowDeleteModal(true);
  }, [selectedDeviceIds.length, setDeviceToDelete, setIsDeletingSelected, setShowDeleteModal]);

  return {
    handleSort,
    handleDeleteDevice,
    handleDeleteSelected,
  };
};
