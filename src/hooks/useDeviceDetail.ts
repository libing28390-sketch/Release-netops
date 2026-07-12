import { useCallback, useEffect, useState } from 'react';
import type {
  Device,
  DeviceHealthAlertItem,
  DeviceHealthDetailResponse,
  DeviceHealthTrendResponse,
} from '../types';
import type { Language } from '../i18n.tsx';

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
  const [viewingDeviceAlerts, setViewingDeviceAlerts] = useState<DeviceHealthAlertItem[]>([]);
  const [deviceDetailLoading, setDeviceDetailLoading] = useState(false);
  const [deviceTrendRangeHours, setDeviceTrendRangeHours] = useState(24);
  const [deviceHealthTrend, setDeviceHealthTrend] = useState<DeviceHealthTrendResponse | null>(null);
  const [deviceHealthTrendLoading, setDeviceHealthTrendLoading] = useState(false);
  const [deviceOperationalData, setDeviceOperationalData] = useState<any | null>(null);
  const [deviceOperationalDataLoading, setDeviceOperationalDataLoading] = useState(false);

  const handleShowDetails = useCallback((device: Device) => {
    setViewingDevice(device);
    setViewingDeviceAlerts([]);
    setDeviceTrendRangeHours(24);
    setDeviceHealthTrend(null);
    setDeviceOperationalData(null);
    setShowDetailsModal(true);
    setDeviceDetailLoading(true);

    fetch(`/api/device-health/device/${device.id}`)
      .then(async (resp) => {
        if (!resp.ok) throw new Error('Failed to load device health detail');
        const data = (await resp.json()) as DeviceHealthDetailResponse;
        setViewingDevice(normalizeDeviceRecord(data.device));
        setViewingDeviceAlerts(Array.isArray(data.recent_open_alerts) ? data.recent_open_alerts : []);
      })
      .catch(() => {
        showToast(
          language === 'zh'
            ? '无法加载完整健康详情，已显示当前设备快照。'
            : 'Unable to load full health details, showing the current device snapshot.',
          'info',
        );
      })
      .finally(() => setDeviceDetailLoading(false));
  }, [language, showToast, normalizeDeviceRecord]);

  // Auto-load trend data when modal opens or range changes.
  useEffect(() => {
    if (!showDetailsModal || !viewingDevice?.id) return;

    let cancelled = false;
    const loadDeviceTrend = async () => {
      setDeviceHealthTrendLoading(true);
      try {
        const resp = await fetch(
          `/api/device-health/device/${viewingDevice.id}/trend?range_hours=${deviceTrendRangeHours}`,
        );
        if (!resp.ok) throw new Error('Failed to load device trend');
        const data = (await resp.json()) as DeviceHealthTrendResponse;
        if (!cancelled) setDeviceHealthTrend(data);
      } catch {
        if (!cancelled) setDeviceHealthTrend(null);
      } finally {
        if (!cancelled) setDeviceHealthTrendLoading(false);
      }
    };

    loadDeviceTrend();
    return () => {
      cancelled = true;
    };
  }, [deviceTrendRangeHours, showDetailsModal, viewingDevice?.id]);

  const loadDeviceOperationalData = useCallback(async (deviceId: string) => {
    setDeviceOperationalDataLoading(true);
    try {
      const resp = await fetch(`/api/devices/${deviceId}/operational-data`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          categories: ['interfaces', 'neighbors', 'arp', 'mac_table', 'routing_table', 'bgp', 'ospf'],
          auth_role: 'auto',
        }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data?.detail || 'Failed to collect operational data');
      }
      setDeviceOperationalData(data);
      showToast(language === 'zh' ? '已完成设备运行数据采集' : 'Operational data collected', 'success');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to collect operational data';
      showToast(language === 'zh' ? `采集失败：${message}` : message, 'error');
    } finally {
      setDeviceOperationalDataLoading(false);
    }
  }, [language, showToast]);

  return {
    showDetailsModal,
    setShowDetailsModal,
    viewingDevice,
    setViewingDevice,
    viewingDeviceAlerts,
    deviceDetailLoading,
    deviceTrendRangeHours,
    setDeviceTrendRangeHours,
    deviceHealthTrend,
    deviceHealthTrendLoading,
    deviceOperationalData,
    deviceOperationalDataLoading,
    handleShowDetails,
    loadDeviceOperationalData,
  };
};
