import { useCallback, useState } from 'react';
import type {
  Device,
  DeviceHealthDetailResponse,
} from '../types';
import type { Language } from '../i18n.tsx';
import { authHeaders } from '../api/http';

interface UseDeviceDetailArgs {
  language: Language;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
  normalizeDeviceRecord: (record: any) => Device;
}

export const useDeviceDetail = ({
  language,
  showToast,
  normalizeDeviceRecord,
}: UseDeviceDetailArgs) => {
  const [showDetailsModal, setShowDetailsModal] = useState(false);
  const [viewingDevice, setViewingDevice] = useState<Device | null>(null);

  const handleShowDetails = useCallback((device: Device) => {
    setViewingDevice(device);
    setShowDetailsModal(true);

    fetch(`/api/device-health/device/${device.id}`, { headers: authHeaders() })
      .then(async (resp) => {
        if (!resp.ok) throw new Error('Failed to load device health detail');
        const data = (await resp.json()) as DeviceHealthDetailResponse;
        setViewingDevice(normalizeDeviceRecord(data.device));
      })
      .catch(() => {
        showToast(
          language === 'zh'
            ? '无法加载完整健康详情，已显示当前设备快照。'
            : 'Unable to load full health details, showing the current device snapshot.',
          'info',
        );
      });
  }, [language, showToast, normalizeDeviceRecord]);

  return {
    showDetailsModal,
    setShowDetailsModal,
    viewingDevice,
    setViewingDevice,
    handleShowDetails,
  };
};
