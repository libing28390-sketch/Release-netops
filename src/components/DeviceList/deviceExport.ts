import type { Device, DeviceConnectionCheckSummary } from '../../types';
import type { TableExportData } from '../ui/TableExportMenu';
import { getDevicePlatformAdaptation } from '../../utils/platformVersion';
import { normalizeDeviceRecord } from '../../utils/deviceUtils';
import { CHECK_BADGE, formatCheckTime } from './StatusBadge';
import type { ColumnVisibility } from './DeviceTable';
import { rackDisplayName } from './deviceColumns';

export type DeviceQuickFilter = 'all' | 'offline' | 'warning' | 'staging_maintenance' | 'healthy';

export interface NetworkDeviceExportView {
  columns: ColumnVisibility;
  language: string;
  connectionChecks?: Record<string, DeviceConnectionCheckSummary>;
}

export interface NetworkDeviceExportPage {
  items?: unknown[];
  total?: number;
}

export async function fetchAllNetworkDevicePages(
  fetchPage: (page: number, pageSize: number) => Promise<NetworkDeviceExportPage>,
  pageSize = 1000,
): Promise<Device[]> {
  const devices: Device[] = [];
  let total = Number.POSITIVE_INFINITY;
  for (let page = 1; devices.length < total; page += 1) {
    const payload = await fetchPage(page, pageSize);
    const items = Array.isArray(payload?.items) ? payload.items : [];
    devices.push(...items.map(normalizeDeviceRecord));
    total = Math.max(0, Number(payload?.total) || 0);
    if (items.length === 0) break;
  }
  return devices;
}

export function filterNetworkDevicesForExport(
  devices: Device[],
  options: {
    quickFilter: DeviceQuickFilter;
    lifecycleFilter: string;
    tagFilterIds: string[];
  },
): Device[] {
  const { quickFilter, lifecycleFilter, tagFilterIds } = options;
  return devices.filter((device) => {
    if (lifecycleFilter && lifecycleFilter !== 'all' && device.lifecycle_status !== lifecycleFilter) return false;
    if (tagFilterIds.length > 0 && !tagFilterIds.some((tagId) => device.tag_ids?.includes(tagId))) return false;

    switch (quickFilter) {
      case 'offline':
        return device.status === 'offline';
      case 'warning':
        return device.health_status === 'warning'
          || device.health_status === 'critical'
          || Number(device.open_alert_count || 0) > 0;
      case 'staging_maintenance':
        return device.lifecycle_status === 'staging'
          || device.lifecycle_status === 'maintenance'
          || device.status === 'pending';
      case 'healthy':
        return device.status === 'online'
          && device.health_status !== 'warning'
          && device.health_status !== 'critical'
          && Number(device.open_alert_count || 0) === 0;
      default:
        return true;
    }
  });
}

function trim(value: unknown): string {
  return typeof value === 'string' ? value.trim() : value === null || value === undefined ? '' : String(value).trim();
}

function vendorLabel(device: Device): string {
  const value = trim(device.vendor || (device as Device & { asset_vendor?: string }).asset_vendor);
  if (value) return value;
  const platform = trim(device.platform).toLowerCase();
  if (platform.includes('cisco')) return 'Cisco';
  if (platform.includes('huawei') || platform.includes('vrp')) return 'Huawei';
  if (platform.includes('juniper') || platform.includes('junos')) return 'Juniper';
  if (platform.includes('arista')) return 'Arista';
  if (platform.includes('fortinet')) return 'Fortinet';
  if (platform.includes('h3c') || platform.includes('comware')) return 'H3C';
  if (platform.includes('ruijie')) return 'Ruijie';
  return trim(device.platform).split('_')[0] || 'Other';
}

function platformAdaptation(device: Device, language: string) {
  const zh = language === 'zh';
  const summary = getDevicePlatformAdaptation(device, zh ? 'zh' : 'en');
  return summary.label || (zh ? '待自动识别' : 'Awaiting detection');
}

function tagValue(device: Device, zh: boolean): string {
  return (device.tags || [])
    .map((tag) => trim(zh ? (tag.label_zh || tag.label) : tag.label))
    .filter(Boolean)
    .join('、');
}

function healthLabel(device: Device, zh: boolean): string {
  const labels: Record<string, string> = zh
    ? { healthy: '健康', warning: '警告', critical: '严重', unknown: '未知' }
    : { healthy: 'Healthy', warning: 'Warning', critical: 'Critical', unknown: 'Unknown' };
  return labels[device.health_status || 'unknown'] || (device.health_status || 'unknown');
}

function lifecycleLabel(device: Device, zh: boolean): string {
  const labels: Record<string, string> = zh
    ? { staging: '待投产', production: '已投产', maintenance: '维护中', decommissioned: '已退役' }
    : { staging: 'Staging', production: 'Production', maintenance: 'Maintenance', decommissioned: 'Decommissioned' };
  return labels[device.lifecycle_status || 'staging'] || (device.lifecycle_status || 'staging');
}

/** Generate one export field per visible network-device table column. */
export function buildNetworkDeviceExportData(devices: Device[], view: NetworkDeviceExportView): TableExportData {
  const zh = view.language === 'zh';
  const columns: Array<{ key: keyof ColumnVisibility; header: string; value: (device: Device) => string }> = [
    { key: 'hostname', header: zh ? '设备名称' : 'Device name', value: (device) => trim(device.hostname) || (zh ? '未知' : 'Unknown') },
    { key: 'assetTag', header: zh ? '资产编号' : 'Asset tag', value: (device) => trim(device.asset_tag) || '—' },
    { key: 'managementIp', header: zh ? '管理 IP' : 'Management IP', value: (device) => trim(device.ip_address) || '—' },
    { key: 'category', header: zh ? '设备类别' : 'Category', value: (device) => trim(device.device_category) || '—' },
    { key: 'role', header: zh ? '角色' : 'Role', value: (device) => trim(device.role) || '—' },
    { key: 'connectionMethod', header: zh ? '连接方式' : 'Connection method', value: (device) => trim(device.connection_method).toUpperCase() || '—' },
    { key: 'vendor', header: zh ? '厂商' : 'Vendor', value: vendorLabel },
    { key: 'model', header: zh ? '型号' : 'Model', value: (device) => trim(device.model || (device as Device & { asset_model?: string }).asset_model) || '—' },
    { key: 'version', header: zh ? '软件版本' : 'Software version', value: (device) => trim(device.version) || '—' },
    { key: 'adaptation', header: zh ? '命令/解析适配' : 'Command/parser adaptation', value: (device) => platformAdaptation(device, view.language) },
    { key: 'site', header: zh ? '站点' : 'Site', value: (device) => trim(device.datacenter || device.site) || '—' },
    { key: 'rack', header: zh ? '机柜' : 'Rack', value: rackDisplayName },
    { key: 'rackUnit', header: zh ? 'U 位' : 'Rack unit', value: (device) => trim(device.rack_unit) || '—' },
    { key: 'tags', header: zh ? '标签' : 'Tags', value: (device) => tagValue(device, zh) || '—' },
    { key: 'status', header: zh ? '在线状态' : 'Status', value: (device) => device.status === 'online' ? (zh ? '在线' : 'Online') : device.status === 'offline' ? (zh ? '离线' : 'Offline') : device.status === 'pending' ? (zh ? '等待中' : 'Pending') : trim(device.status) || '—' },
    { key: 'health', header: zh ? '健康状态' : 'Health', value: (device) => healthLabel(device, zh) },
    { key: 'lifecycle', header: zh ? '生命周期' : 'Lifecycle', value: (device) => lifecycleLabel(device, zh) },
    { key: 'checkStatus', header: zh ? '连通性检查' : 'Connectivity check', value: (device) => {
      const check = view.connectionChecks?.[device.id];
      const label = check && CHECK_BADGE[check.status];
      return label ? (zh ? label.zh : label.en) : '—';
    } },
    { key: 'checkTime', header: zh ? '检查时间' : 'Check time', value: (device) => {
      const checkedAt = view.connectionChecks?.[device.id]?.checked_at;
      return checkedAt ? formatCheckTime(checkedAt, view.language) : '—';
    } },
  ];
  const visibleColumns = columns.filter(({ key }) => view.columns[key]);
  return {
    headers: visibleColumns.map(({ header }) => header),
    rows: devices.map((device) => visibleColumns.map(({ value }) => value(device))),
  };
}
