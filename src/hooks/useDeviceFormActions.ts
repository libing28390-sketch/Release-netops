import { useCallback, useState } from 'react';
import type { Device } from '../types';
import { authHeaders } from '../api/http';
import { useInventoryStore } from '../store/inventoryStore';
import { SSH_ALGORITHM_PROFILE_VALUES } from '../pages/AssetManagement/constants';

const normalizeSshAlgorithmProfile = (value: unknown): Device['ssh_algorithm_profile'] => {
  const normalized = String(value || 'auto').trim().toLowerCase().replace(/-/g, '_');
  return SSH_ALGORITHM_PROFILE_VALUES.includes(normalized as typeof SSH_ALGORITHM_PROFILE_VALUES[number])
    ? normalized as Device['ssh_algorithm_profile']
    : 'auto';
};

const EMPTY_ADD_FORM: Partial<Device> = {
  hostname: '',
  ip_address: '',
  platform: 'cisco_ios',
  role: 'Access',
  site: '',
  connection_method: 'ssh',
  ssh_algorithm_profile: 'auto',
  username: '',
  password: '',
  snmp_community: 'public',
  snmp_port: 161,
  snmp_cpu_oid: '',
  snmp_memory_oid: '',
  lifecycle_status: 'staging',
};

interface UseDeviceFormActionsArgs {
  devices: Device[];
  setDevices: React.Dispatch<React.SetStateAction<Device[]>>;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
}

export const useDeviceFormActions = ({ devices, setDevices, showToast }: UseDeviceFormActionsArgs) => {
  const [showAddModal, setShowAddModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [editingDevice, setEditingDevice] = useState<Device | null>(null);
  const [editForm, setEditForm] = useState<Partial<Device>>({});
  const [addForm, setAddForm] = useState<Partial<Device>>(EMPTY_ADD_FORM);
  const [showAddDevicePwd, setShowAddDevicePwd] = useState(false);
  const [showEditDevicePwd, setShowEditDevicePwd] = useState(false);
  const [showLifecycleConfirm, setShowLifecycleConfirm] = useState<'add' | 'edit' | null>(null);
  const [lifecycleConfirmChecked, setLifecycleConfirmChecked] = useState(false);

  const setInventoryRefreshTick = useInventoryStore((s) => s.setInventoryRefreshTick);
  const setInventoryPage = useInventoryStore((s) => s.setInventoryPage);

  void devices;

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
        ssh_algorithm_profile: normalizeSshAlgorithmProfile(editForm.ssh_algorithm_profile),
      };
      const response = await fetch(`/api/devices/${editingDevice.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
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
        showToast(`Failed to update device: ${data.detail || data.error || response.statusText}`, 'error');
      }
    } catch (error) {
      showToast(`Error updating device: ${error}`, 'error');
    }
  }, [editingDevice, editForm, showLifecycleConfirm, setDevices, setInventoryRefreshTick, showToast]);

  const handleAddDevice = useCallback(async () => {
    if (!addForm.hostname || !addForm.ip_address) {
      showToast('Hostname and IP Address are required', 'error');
      return;
    }
    if (addForm.lifecycle_status === 'production' && showLifecycleConfirm !== 'add') {
      setLifecycleConfirmChecked(false);
      setShowLifecycleConfirm('add');
      return;
    }
    try {
      const payload = {
        ...addForm,
        ssh_algorithm_profile: normalizeSshAlgorithmProfile(addForm.ssh_algorithm_profile),
      };
      const response = await fetch('/api/devices', {
        method: 'POST',
        headers: authHeaders(true),
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (response.ok) {
        if (addForm.tag_ids && addForm.tag_ids.length > 0 && data.id) {
          const token = localStorage.getItem('netops_token') || '';
          await fetch(`/api/tags/devices/${data.id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
            body: JSON.stringify({ tag_ids: addForm.tag_ids }),
          }).catch(() => {});
        }
        setDevices((prev) => [...prev, { ...data, ssh_algorithm_profile: normalizeSshAlgorithmProfile(data.ssh_algorithm_profile || payload.ssh_algorithm_profile) }]);
        setInventoryRefreshTick((v) => v + 1);
        setInventoryPage(1);
        setShowAddModal(false);
        setAddForm(EMPTY_ADD_FORM);
        showToast('Device added successfully', 'success');
        setShowLifecycleConfirm(null);
      } else {
        showToast(`Failed to add device: ${data.error || data.detail || response.statusText}`, 'error');
      }
    } catch (error) {
      showToast(`Error adding device: ${error}`, 'error');
    }
  }, [addForm, showLifecycleConfirm, setDevices, setInventoryRefreshTick, setInventoryPage, showToast]);

  return {
    showAddModal,
    setShowAddModal,
    showEditModal,
    setShowEditModal,
    editingDevice,
    setEditingDevice,
    editForm,
    setEditForm,
    addForm,
    setAddForm,
    showAddDevicePwd,
    setShowAddDevicePwd,
    showEditDevicePwd,
    setShowEditDevicePwd,
    showLifecycleConfirm,
    setShowLifecycleConfirm,
    lifecycleConfirmChecked,
    setLifecycleConfirmChecked,
    handleSaveEdit,
    handleAddDevice,
  };
};
