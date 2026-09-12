import { useCallback } from 'react';
import type { Device } from '../types';
import { deleteDevicesByIds } from '../utils/deviceDelete';
import { useInventoryStore } from '../store/inventoryStore';

export const useInventoryDeleteActions = (
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void,
  setDevices?: React.Dispatch<React.SetStateAction<Device[]>>,
) => {
  const {
    deviceToDelete,
    setDeviceToDelete,
    isDeletingSelected,
    setIsDeletingSelected,
    showDeleteModal,
    setShowDeleteModal,
    selectedDeviceIds,
    setSelectedDeviceIds,
    setInventoryRefreshTick,
  } = useInventoryStore();

  const confirmDeleteDevice = useCallback(async () => {
    if (!deviceToDelete && !isDeletingSelected) return;

    if (isDeletingSelected) {
      if (selectedDeviceIds.length === 0) return;
      const { successCount, failCount } = await deleteDevicesByIds(selectedDeviceIds);
      const selectedIdSet = new Set(selectedDeviceIds);
      if (setDevices) {
        setDevices((prev) => prev.filter((d) => !selectedIdSet.has(d.id)));
      }
      setSelectedDeviceIds([]);
      setInventoryRefreshTick((v) => v + 1);
      if (failCount === 0) {
        showToast(`Successfully deleted ${successCount} devices`, 'success');
      } else {
        showToast(`Deleted ${successCount} devices, failed to delete ${failCount} devices`, 'error');
      }
    } else if (deviceToDelete) {
      try {
        const response = await fetch(`/api/devices/${deviceToDelete}`, { method: 'DELETE' });
        if (response.ok) {
          if (setDevices) {
            setDevices((prev) => prev.filter((d) => d.id !== deviceToDelete));
          }
          setSelectedDeviceIds((prev: string[]) => prev.filter((id) => id !== deviceToDelete));
          setInventoryRefreshTick((v) => v + 1);
          showToast('Device deleted successfully', 'success');
        } else {
          const data = await response.json();
          showToast(`Failed to delete device: ${data.error}`, 'error');
        }
      } catch (error) {
        showToast(`Error deleting device: ${error}`, 'error');
      }
    }

    setShowDeleteModal(false);
    setDeviceToDelete(null);
    setIsDeletingSelected(false);
  }, [
    deviceToDelete,
    isDeletingSelected,
    selectedDeviceIds,
    setDevices,
    setSelectedDeviceIds,
    setInventoryRefreshTick,
    showToast,
    setShowDeleteModal,
    setDeviceToDelete,
    setIsDeletingSelected,
  ]);

  return {
    confirmDeleteDevice,
    showDeleteModal,
    setShowDeleteModal,
    deviceToDelete,
    setDeviceToDelete,
    isDeletingSelected,
    setIsDeletingSelected,
  };
};
