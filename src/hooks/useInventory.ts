import React, { useState, useCallback, useMemo, useRef } from 'react';
import type { Device } from '../types';
import { displaySiteLabel } from '../utils/deviceUtils';
import { excludeServerTopologyDevices } from '../utils/topologyDevices';
import { authHeaders } from '../api/http';

export type DeviceFetchMode =
  | 'light'
  | 'full'
  | 'paged-light'
  | 'all-light'
  | 'all-network-light'
  | 'all-network-topology';

const ALL_DEVICE_PAGE_SIZE = 200;

export const useInventory = (deviceFetchMode: DeviceFetchMode = 'full') => {
  const [devices, setDevices] = useState<Device[]>([]);
  const [selectedDevice, setSelectedDevice] = useState<Device | null>(null);
  const [devicesLastUpdatedAt, setDevicesLastUpdatedAt] = useState<number>(0);
  const [devicesError, setDevicesError] = useState<string | null>(null);
  const isNetworkOnlyMode = deviceFetchMode === 'all-network-light' || deviceFetchMode === 'all-network-topology';
  const visibleDevices = useMemo(
    () => isNetworkOnlyMode ? excludeServerTopologyDevices(devices).devices : devices,
    [devices, isNetworkOnlyMode],
  );
  const visibleSelectedDevice = useMemo(
    () => isNetworkOnlyMode && selectedDevice && !visibleDevices.some((device) => device.id === selectedDevice.id)
      ? null
      : selectedDevice,
    [isNetworkOnlyMode, selectedDevice, visibleDevices],
  );

  const safeJsonArray = (value: any) => {
    if (Array.isArray(value)) return value;
    if (typeof value === 'string') {
      try {
        const parsed = JSON.parse(value);
        return Array.isArray(parsed) ? parsed : [];
      } catch {
        return [];
      }
    }
    return [];
  };

  const normalizeDeviceRecord = useCallback((raw: any): Device => {
    const hostname = typeof raw?.hostname === 'string' && raw.hostname.trim()
      ? raw.hostname
      : (typeof raw?.id === 'string' ? raw.id : 'Unknown');

    return {
      ...raw,
      id: String(raw?.id || ''),
      hostname,
      ip_address: typeof raw?.ip_address === 'string' ? raw.ip_address : '',
      platform: typeof raw?.platform === 'string' ? raw.platform : 'unknown',
      status: (raw?.status === 'online' || raw?.status === 'offline' || raw?.status === 'pending') ? raw.status : 'offline',
      compliance: (raw?.compliance === 'compliant' || raw?.compliance === 'non-compliant' || raw?.compliance === 'unknown') ? raw.compliance : 'unknown',
      role: typeof raw?.role === 'string' ? raw.role : '',
      site: displaySiteLabel(raw),
      model: typeof raw?.model === 'string' ? raw.model : '',
      version: typeof raw?.version === 'string' ? raw.version : '',
      sn: typeof raw?.sn === 'string' ? raw.sn : '',
      uptime: typeof raw?.uptime === 'string' ? raw.uptime : '',
      connection_method: raw?.connection_method === 'netconf' ? 'netconf' : 'ssh',
      fan_status: raw?.fan_status === true || raw?.fan_status === 1 || ['true', '1', 'ok', 'normal', 'redundant', 'single', 'up', 'running', 'ready'].includes(String(raw?.fan_status || '').trim().toLowerCase())
        ? true
        : raw?.fan_status === false || raw?.fan_status === 0 || ['false', '0', 'fail', 'failed', 'warning', 'error', 'down', 'offline', 'alarm'].includes(String(raw?.fan_status || '').trim().toLowerCase())
          ? false
          : null,
      psu_status: raw?.psu_status === true || raw?.psu_status === 1 || ['true', '1', 'ok', 'normal', 'redundant', 'single', 'up', 'running', 'ready'].includes(String(raw?.psu_status || '').trim().toLowerCase())
        ? true
        : raw?.psu_status === false || raw?.psu_status === 0 || ['false', '0', 'fail', 'failed', 'warning', 'error', 'down', 'offline', 'alarm'].includes(String(raw?.psu_status || '').trim().toLowerCase())
          ? false
          : null,
      web_access_enabled: raw?.web_access_enabled === true || raw?.web_access_enabled === 1,
      web_http_enabled: raw?.web_http_enabled === true || raw?.web_http_enabled === 1,
      web_https_enabled: raw?.web_https_enabled === true || raw?.web_https_enabled === 1,
      config_history: safeJsonArray(raw?.config_history),
      interface_data: safeJsonArray(raw?.interface_data),
      cpu_history: safeJsonArray(raw?.cpu_history),
      memory_history: safeJsonArray(raw?.memory_history),
      health_status: ['healthy', 'warning', 'critical', 'unknown'].includes(String(raw?.health_status)) ? raw.health_status : 'unknown',
      health_score: typeof raw?.health_score === 'number' ? raw.health_score : Number(raw?.health_score || 0),
      health_summary: typeof raw?.health_summary === 'string' ? raw.health_summary : '',
      health_reasons: Array.isArray(raw?.health_reasons) ? raw.health_reasons : [],
      open_alert_count: typeof raw?.open_alert_count === 'number' ? raw.open_alert_count : Number(raw?.open_alert_count || 0),
      critical_open_alerts: typeof raw?.critical_open_alerts === 'number' ? raw.critical_open_alerts : Number(raw?.critical_open_alerts || 0),
      major_open_alerts: typeof raw?.major_open_alerts === 'number' ? raw.major_open_alerts : Number(raw?.major_open_alerts || 0),
      warning_open_alerts: typeof raw?.warning_open_alerts === 'number' ? raw.warning_open_alerts : Number(raw?.warning_open_alerts || 0),
      interface_down_count: typeof raw?.interface_down_count === 'number' ? raw.interface_down_count : Number(raw?.interface_down_count || 0),
      interface_flap_count: typeof raw?.interface_flap_count === 'number' ? raw.interface_flap_count : Number(raw?.interface_flap_count || 0),
      high_util_interface_count: typeof raw?.high_util_interface_count === 'number' ? raw.high_util_interface_count : Number(raw?.high_util_interface_count || 0),
      interface_error_count: typeof raw?.interface_error_count === 'number' ? raw.interface_error_count : Number(raw?.interface_error_count || 0),
    } as Device;
  }, []);

  const lastFetchId = useRef(0);

  const fetchDevicesData = useCallback(async (assetType: string = 'all') => {
    const fetchId = ++lastFetchId.current;
    setDevicesError(null);
    try {
      const isAllLightMode = deviceFetchMode === 'all-light' || deviceFetchMode === 'all-network-light';
      const isTopologyMode = deviceFetchMode === 'all-network-topology';
      const isAllPagesMode = isAllLightMode || isTopologyMode;
      const requestMode = deviceFetchMode === 'paged-light' || isAllLightMode
        ? 'light'
        : isTopologyMode
          ? 'topology'
          : deviceFetchMode;
      const params = new URLSearchParams({ mode: requestMode });
      if (deviceFetchMode === 'paged-light') {
        params.set('page', '1');
        params.set('page_size', '30');
      }
      if (isAllPagesMode) {
        params.set('page', '1');
        params.set('page_size', String(ALL_DEVICE_PAGE_SIZE));
      }
      if (isNetworkOnlyMode) {
        params.set('asset_type', 'network_device');
      } else if (assetType !== 'all') {
        params.set('asset_type', assetType);
      } else if (deviceFetchMode === 'paged-light') {
        params.set('asset_type', 'network_device');
      }

      const fetchDevicePage = async (page?: number) => {
        const requestParams = new URLSearchParams(params);
        if (page !== undefined) requestParams.set('page', String(page));
        const response = await fetch(`/api/devices?${requestParams.toString()}`, { headers: authHeaders() });
        if (!response.ok) {
          const errorBody = await response.json().catch(() => null);
          const detail = typeof errorBody?.detail === 'string' ? errorBody.detail : '';
          throw new Error(detail || (response.status === 401
            ? '登录已过期，请重新登录后重试'
            : response.status === 403
              ? '当前账号无权查看网络设备'
              : `加载网络设备失败（${response.status}）`));
        }
        return response.json();
      };

      let devs: any[];
      if (isAllPagesMode) {
        const firstPage = await fetchDevicePage(1);
        if (fetchId !== lastFetchId.current) return;
        if (!Array.isArray(firstPage?.items)) {
          throw new Error('设备列表响应格式无效');
        }
        const total = firstPage.total;
        if (typeof total !== 'number' || !Number.isSafeInteger(total) || total < 0) {
          throw new Error('设备列表总数响应无效');
        }

        devs = [...firstPage.items];
        const totalPages = Math.ceil(total / ALL_DEVICE_PAGE_SIZE);
        for (let page = 2; page <= totalPages; page += 1) {
          if (fetchId !== lastFetchId.current) return;
          const nextPage = await fetchDevicePage(page);
          if (fetchId !== lastFetchId.current) return;
          if (!Array.isArray(nextPage?.items)) {
            throw new Error('设备列表分页响应无效');
          }
          if (nextPage.total !== total) {
            throw new Error('设备列表在加载期间发生变化，请刷新重试');
          }
          if (nextPage.items.length === 0) {
            throw new Error('设备列表分页响应不完整，请刷新重试');
          }
          devs.push(...nextPage.items);
        }

        const deviceIds = new Set(devs.map((device) => String(device?.id || '')));
        if (devs.length !== total || deviceIds.size !== total || deviceIds.has('')) {
          throw new Error('设备列表分页响应不完整，请刷新重试');
        }
      } else {
        const payload = await fetchDevicePage();
        devs = Array.isArray(payload) ? payload : Array.isArray(payload?.items) ? payload.items : [];
      }
      
      // Safety Check: Prevent older or mismatched mode requests from overwriting state
      if (fetchId !== lastFetchId.current) return;

      const normalizedDevices = devs.map((d: any) => {
        const normalized = normalizeDeviceRecord(d);
        if (deviceFetchMode !== 'full') {
          return {
            ...normalized,
            config_history: [],
          };
        }
        return normalized;
      });
      setDevices(isNetworkOnlyMode
        ? excludeServerTopologyDevices(normalizedDevices).devices
        : normalizedDevices);
      setDevicesLastUpdatedAt(Date.now());
    } catch (error) {
      if (fetchId === lastFetchId.current) {
        setDevicesError(error instanceof Error ? error.message : '加载网络设备失败');
        console.error('Failed to fetch devices data:', error);
      }
    }
  }, [deviceFetchMode, normalizeDeviceRecord]);

  return {
    devices: visibleDevices,
    setDevices,
    selectedDevice: visibleSelectedDevice,
    setSelectedDevice,
    devicesLastUpdatedAt,
    devicesError,
    fetchDevicesData,
    normalizeDeviceRecord
  };
};
