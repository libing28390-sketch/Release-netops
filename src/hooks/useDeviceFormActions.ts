import { useCallback, useState } from 'react';
import type { Device } from '../types';
import { authHeaders } from '../api/http';
import { useInventoryStore } from '../store/inventoryStore';
import { normalizeImportedPlatform, SSH_ALGORITHM_PROFILE_VALUES } from '../pages/AssetManagement/constants';
import { getPlatformBindingErrorMessage } from '../utils/platformBindingErrors';

const normalizeSshAlgorithmProfile = (value: unknown): Device['ssh_algorithm_profile'] => {
  const normalized = String(value || 'auto').trim().toLowerCase().replace(/-/g, '_');
  return SSH_ALGORITHM_PROFILE_VALUES.includes(normalized as typeof SSH_ALGORITHM_PROFILE_VALUES[number])
    ? normalized as Device['ssh_algorithm_profile']
    : 'auto';
};

interface UseDeviceFormActionsArgs {
  setDevices: React.Dispatch<React.SetStateAction<Device[]>>;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
}

export const useDeviceFormActions = ({ setDevices, showToast }: UseDeviceFormActionsArgs) => {
  const [showEditModal, setShowEditModal] = useState(false);
  const [editingDevice, setEditingDevice] = useState<Device | null>(null);
  const [editForm, setEditForm] = useState<Partial<Device>>({});
  const [showEditDevicePwd, setShowEditDevicePwd] = useState(false);
  const [showLifecycleConfirm, setShowLifecycleConfirm] = useState<'edit' | null>(null);
  const [lifecycleConfirmChecked, setLifecycleConfirmChecked] = useState(false);

  const setInventoryRefreshTick = useInventoryStore((s) => s.setInventoryRefreshTick);

  const handleSaveEdit = useCallback(async () => {
    if (!editingDevice) return;
    // Intercept: if lifecycle transitions to production, require explicit confirmation
    const oldLifecycle = editingDevice.lifecycle_status || 'staging';
    const newLifecycle = editForm.lifecycle_status || oldLifecycle;
    if (newLifecycle === 'production' && oldLifecycle !== 'production' && showLifecycleConfirm !== 'edit') {
      setLifecycleConfirmChecked(false);
      setShowLifecycleConfirm('edit');
      return;
    }
    try {
      const payload = {
        ...editForm,
        platform: editForm.platform ? normalizeImportedPlatform(editForm.platform) : editForm.platform,
        ssh_algorithm_profile: normalizeSshAlgorithmProfile(editForm.ssh_algorithm_profile),
      };
      const response = await fetch(`/api/devices/${editingDevice.id}`, {
        method: 'PUT',
        headers: authHeaders(true),
        body: JSON.stringify(payload),
      });
      if (response.ok) {
        if (editForm.tag_ids) {
          const token = localStorage.getItem('netops_token') || '';
          await fetch(`/api/tags/devices/${editingDevice.id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
            body: JSON.stringify({ tag_ids: editForm.tag_ids }),
          }).catch(() => {});
        }
        setDevices((prev) => prev.map((d) => (d.id === editingDevice.id ? { ...d, ...payload } as Device : d)));
        setInventoryRefreshTick((v) => v + 1);
        setShowEditModal(false);
        setShowLifecycleConfirm(null);
        showToast('Device updated successfully', 'success');
      } else {
        const data = await response.json();
        const detail = data.error ?? data.detail;
        const message = typeof detail === 'string' ? detail : detail?.message || response.statusText;
        const explanation = getPlatformBindingErrorMessage({
          detail,
          message,
          requestId: response.headers.get('X-Request-ID'),
        }, 'en');
        showToast(`Failed to update device: ${explanation}`, 'error');
      }
    } catch (error) {
      showToast(`Error updating device: ${error}`, 'error');
    }
  }, [editingDevice, editForm, showLifecycleConfirm, setDevices, setInventoryRefreshTick, showToast]);

  return {
    showEditModal,
    setShowEditModal,
    editingDevice,
    setEditingDevice,
    editForm,
    setEditForm,
    showEditDevicePwd,
    setShowEditDevicePwd,
    showLifecycleConfirm,
    setShowLifecycleConfirm,
    lifecycleConfirmChecked,
    setLifecycleConfirmChecked,
    handleSaveEdit,
  };
};
