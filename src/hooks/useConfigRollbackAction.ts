import { useCallback } from 'react';
import type { ConfigVersion, Device } from '../types';

interface UseConfigRollbackActionParams {
  selectedDevice: Device | null;
  setSelectedDevice: React.Dispatch<React.SetStateAction<Device | null>>;
  setDevices: React.Dispatch<React.SetStateAction<Device[]>>;
  setViewingConfig: React.Dispatch<React.SetStateAction<ConfigVersion | null>>;
  setShowConfigModal: React.Dispatch<React.SetStateAction<boolean>>;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
}

export const useConfigRollbackAction = ({
  selectedDevice,
  setSelectedDevice,
  setDevices,
  setViewingConfig,
  setShowConfigModal,
  showToast,
}: UseConfigRollbackActionParams) => {
  const handleRollbackConfig = useCallback(async (device: Device, version: ConfigVersion) => {
    const newVersion: ConfigVersion = {
      id: `v${Date.now()}`,
      timestamp: new Date().toISOString().replace('T', ' ').substring(0, 16),
      content: device.current_config || '',
      author: 'admin',
      description: `Rollback to ${version.id}`,
    };

    const updatedHistory = [newVersion, ...device.config_history];

    try {
      const execRes = await fetch('/api/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          device_id: device.id,
          command: version.content,
        }),
      });

      if (!execRes.ok) {
        showToast('Failed to execute rollback on device', 'error');
        return;
      }

      const dbRes = await fetch(`/api/devices/${device.id}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          current_config: version.content,
          config_history: updatedHistory,
        }),
      });

      if (dbRes.ok) {
        const updatedDevice = {
          ...device,
          current_config: version.content,
          config_history: updatedHistory,
        };

        setDevices((prev) => prev.map((d) => (d.id === device.id ? updatedDevice : d)));

        if (selectedDevice?.id === device.id) {
          setSelectedDevice(updatedDevice);
        }

        setViewingConfig(null);
        setShowConfigModal(false);
        showToast(`Rolled back to version ${version.id}`, 'success');
      } else {
        showToast('Failed to update configuration history', 'error');
      }
    } catch {
      showToast('Connection error during rollback', 'error');
    }
  }, [selectedDevice?.id, setDevices, setSelectedDevice, setShowConfigModal, setViewingConfig, showToast]);

  return {
    handleRollbackConfig,
  };
};
