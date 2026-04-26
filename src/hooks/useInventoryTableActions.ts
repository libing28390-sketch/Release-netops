import { useCallback } from 'react';
import type { Device } from '../types';

interface UseInventoryTableActionsParams {
  selectedDeviceIds: string[];
  inventorySortConfig: { key: keyof Device; direction: 'asc' | 'desc' } | null;
  setInventorySortConfig: React.Dispatch<React.SetStateAction<{ key: keyof Device; direction: 'asc' | 'desc' } | null>>;
  setDeviceToDelete: React.Dispatch<React.SetStateAction<string | null>>;
  setIsDeletingSelected: React.Dispatch<React.SetStateAction<boolean>>;
  setShowDeleteModal: React.Dispatch<React.SetStateAction<boolean>>;
}

export const useInventoryTableActions = ({
  selectedDeviceIds,
  inventorySortConfig,
  setInventorySortConfig,
  setDeviceToDelete,
  setIsDeletingSelected,
  setShowDeleteModal,
}: UseInventoryTableActionsParams) => {
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
