import { DataTable } from '../DataTable';
import React, { useState, useCallback } from 'react';
import {
  ChevronDown, ChevronUp, ChevronRight,
  Pencil, Trash2,
  Activity, WifiOff, Terminal,
} from 'lucide-react';
import type { Device, DeviceConnectionCheckSummary } from '../../types';
import type { TableExportData } from '../ui/TableExportMenu';
import { ActionIconButton, ActionIconGroup } from '../ui/ActionIconButton';
import { CHECK_BADGE, HEALTH_CFG, LIFECYCLE_CFG, STATUS_CFG, formatCheckTime } from './StatusBadge';
import DeviceRowExpand from './DeviceRowExpand';
import { extractSoftwareMajorVersion, getDevicePlatformAdaptation, getProfileAdaptationMajorVersion } from '../../utils/platformVersion';

import { TableActionCell, TableActionHeader } from '../ui/TableActionColumn';
/* ─── Helpers ─── */
const clampPercent = (value?: number) => {
  const n = Number(value ?? 0);
  return Number.isFinite(n) ? Math.max(0, Math.min(100, n)) : 0;
};

const vendorOf = (platform: string): string => {
  if (!platform) return 'Unknown';
  const p = platform.toLowerCase();
  if (p.includes('cisco')) return 'Cisco';
  if (p.includes('huawei') || p.includes('vrp')) return 'Huawei';
  if (p.includes('juniper') || p.includes('junos')) return 'Juniper';
  if (p.includes('arista')) return 'Arista';
  if (p.includes('fortinet')) return 'Fortinet';
  if (p.includes('h3c') || p.includes('comware')) return 'H3C';
  if (p.includes('ruijie')) return 'Ruijie';
  return platform.split('_')[0] || 'Other';
};

const adaptationVersionLabel = (device: Device): string => {
  const version = getDevicePlatformAdaptation(device, 'zh').version;
  return version && !['common', 'unknown'].includes(version.toLowerCase())
    ? version.toUpperCase()
    : '';
};

const platformBindingName = (device: Device, zh: boolean): string => {
  return getDevicePlatformAdaptation(device, zh ? 'zh' : 'en').label;
};

const hasVersionMismatch = (device: Device): boolean => {
  if (!device.platform_profile_id && !device.platform_binding) return false;
  const softwareMajor = extractSoftwareMajorVersion(device.version);
  const adaptationMajor = device.platform_binding
    ? getProfileAdaptationMajorVersion(device.platform_binding)
    : device.platform_profile_id
      ? getProfileAdaptationMajorVersion({ id: device.platform_profile_id, platform_code: '' })
      : null;
  return softwareMajor !== null && adaptationMajor !== null && softwareMajor !== adaptationMajor;
};

/* ─── Column Def ─── */
export type ColumnKey =
  | 'hostname' | 'assetTag' | 'managementIp' | 'category' | 'role' | 'connectionMethod'
  | 'vendor' | 'platform' | 'model' | 'version' | 'adaptation' | 'adaptationVersion' | 'adaptationSource' | 'versionMismatch'
  | 'site' | 'rack' | 'rackUnit' | 'tags' | 'status' | 'health' | 'lifecycle' | 'checkStatus' | 'checkTime' | 'cpu' | 'memory' | 'actions';

export interface ColumnVisibility {
  hostname: boolean;
  assetTag: boolean;
  managementIp: boolean;
  category: boolean;
  role: boolean;
  connectionMethod: boolean;
  vendor: boolean;
  platform: boolean;
  model: boolean;
  version: boolean;
  adaptation: boolean;
  adaptationVersion: boolean;
  adaptationSource: boolean;
  versionMismatch: boolean;
  site: boolean;
  rack: boolean;
  rackUnit: boolean;
  tags: boolean;
  status: boolean;
  health: boolean;
  lifecycle: boolean;
  checkStatus: boolean;
  checkTime: boolean;
  cpu: boolean;
  memory: boolean;
  actions: boolean;
}

export const DEFAULT_COLUMNS: ColumnVisibility = {
  hostname: true,
  assetTag: true,
  managementIp: true,
  category: true,
  role: true,
  connectionMethod: true,
  vendor: true,
  platform: true,
  model: true,
  version: true,
  adaptation: true,
  adaptationVersion: true,
  adaptationSource: true,
  versionMismatch: true,
  site: true,
  rack: true,
  rackUnit: true,
  tags: true,
  status: true,
  health: true,
  lifecycle: true,
  checkStatus: true,
  checkTime: true,
  cpu: true,
  memory: true,
  actions: true,
};

/* ─── SortHeader ─── */
const SortHeader: React.FC<{
  col: string;
  sortConfig: { key: string; direction: 'asc' | 'desc' } | null;
  onSort: (key: string) => void;
  children: React.ReactNode;
  className?: string;
}> = ({ col, sortConfig, onSort, children, className = '' }) => {
  const active = sortConfig?.key === col;
  return (
    <th
      className={`px-3 py-3 text-[11px] font-bold uppercase tracking-wider cursor-pointer select-none transition-colors
        ${active ? 'text-blue-600 dark:text-blue-400' : 'text-gray-400 dark:text-zinc-400 hover:text-gray-600 dark:hover:text-zinc-200'} ${className}`}
      onClick={() => onSort(col)}
    >
      <span className="inline-flex items-center gap-0.5">
        {children}
        {active && (sortConfig?.direction === 'asc'
          ? <ChevronUp size={10} />
          : <ChevronDown size={10} />
        )}
      </span>
    </th>
  );
};

/* ─── DeviceTable Props ─── */
interface DeviceTableProps {
  rows: Device[];
  loading: boolean;
  language: string;
  sortConfig: { key: string; direction: 'asc' | 'desc' } | null;
  onSort: (key: string) => void;
  selectedIds: string[];
  onSelectChange: React.Dispatch<React.SetStateAction<string[]>>;
  onShowDetails: (device: Device) => void;
  onEdit?: (device: Device) => void;
  onDelete?: (id: string) => void;
  onManage: (device: Device) => void;
  onTestConnection: (device: Device, mode?: 'quick' | 'deep') => void;
  deviceConnectionChecks: Record<string, DeviceConnectionCheckSummary>;
  connectionTestingDeviceId: string | null;
  columns: ColumnVisibility;
  exportData: () => Promise<TableExportData>;
  exportDisabled?: boolean;
}

const DeviceTable: React.FC<DeviceTableProps> = ({
  rows, loading, language, sortConfig, onSort,
  selectedIds, onSelectChange,
  onShowDetails, onEdit, onDelete, onManage, onTestConnection,
  deviceConnectionChecks, connectionTestingDeviceId,
  columns, exportData, exportDisabled = false,
}) => {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const zh = language === 'zh';

  const toggleExpand = useCallback((id: string) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }, []);

  const allChecked = rows.length > 0 && rows.every(d => selectedIds.includes(d.id));
  const someChecked = selectedIds.length > 0 && !allChecked;

  const handleSelectAll = (checked: boolean) => {
    if (checked) {
      const ids = rows.map(d => d.id);
      onSelectChange(prev => Array.from(new Set([...prev, ...ids])));
    } else {
      const ids = new Set(rows.map(d => d.id));
      onSelectChange(prev => prev.filter(id => !ids.has(id)));
    }
  };

  /* Calculate visible column count for colSpan */
  const visibleCount = 2 /* checkbox + expand */ + Object.values(columns).filter(Boolean).length;
  const hasExportableColumns = Object.entries(columns).some(([key, visible]) => key !== 'actions' && visible);

  return (
    <div className="overflow-x-auto">
      <DataTable unstyled exportConfig={{ filename: 'devices', language: zh ? 'zh' : 'en', disabled: exportDisabled || loading || !hasExportableColumns, exportData }} className="nx-data-table min-w-[2200px]">
        <thead>
          <tr className="bg-black/[.02] dark:bg-white/[.02] border-b border-black/5 dark:border-white/6">
            <th className="px-3 py-3 w-9">
              <input
                type="checkbox"
                title={zh ? '选择全部' : 'Select all'}
                className="rounded border-black/20 dark:border-white/20 text-[#00bceb] focus:ring-[#00bceb] focus:ring-offset-0"
                checked={allChecked}
                ref={(el) => { if (el) el.indeterminate = someChecked; }}
                onChange={e => handleSelectAll(e.target.checked)}
              />
            </th>
            <th className="px-1 py-3 w-6" />
            {columns.hostname && (
              <SortHeader col="hostname" sortConfig={sortConfig} onSort={onSort}>
                {zh ? '设备名称' : 'Device name'}
              </SortHeader>
            )}
            {columns.assetTag && <th className="px-3 py-3 text-[11px] font-bold uppercase tracking-wider text-gray-400 dark:text-zinc-400">{zh ? '资产编号' : 'Asset tag'}</th>}
            {columns.managementIp && (
              <SortHeader col="ip_address" sortConfig={sortConfig} onSort={onSort}>
                {zh ? '管理 IP' : 'Management IP'}
              </SortHeader>
            )}
            {columns.category && <th className="px-3 py-3 text-[11px] font-bold uppercase tracking-wider text-gray-400 dark:text-zinc-400">{zh ? '设备类别' : 'Category'}</th>}
            {columns.role && (
              <SortHeader col="role" sortConfig={sortConfig} onSort={onSort}>
                {zh ? '角色' : 'Role'}
              </SortHeader>
            )}
            {columns.connectionMethod && <th className="px-3 py-3 text-[11px] font-bold uppercase tracking-wider text-gray-400 dark:text-zinc-400">{zh ? '连接方式' : 'Connection method'}</th>}
            {columns.vendor && <th className="px-3 py-3 text-[11px] font-bold uppercase tracking-wider text-gray-400 dark:text-zinc-400">{zh ? '厂商' : 'Vendor'}</th>}
            {columns.platform && (
              <SortHeader col="platform" sortConfig={sortConfig} onSort={onSort}>
                {zh ? '平台' : 'Platform'}
              </SortHeader>
            )}
            {columns.model && (
              <SortHeader col="model" sortConfig={sortConfig} onSort={onSort}>
                {zh ? '型号' : 'Model'}
              </SortHeader>
            )}
            {columns.version && <th className="px-3 py-3 text-[11px] font-bold uppercase tracking-wider text-gray-400 dark:text-zinc-400">{zh ? '软件版本' : 'Software version'}</th>}
            {columns.adaptation && <th className="px-3 py-3 text-[11px] font-bold uppercase tracking-wider text-gray-400 dark:text-zinc-400">{zh ? '命令/解析适配' : 'Command/parser adaptation'}</th>}
            {columns.adaptationVersion && <th className="px-3 py-3 text-[11px] font-bold uppercase tracking-wider text-gray-400 dark:text-zinc-400">{zh ? '适配版本' : 'Adaptation version'}</th>}
            {columns.adaptationSource && <th className="px-3 py-3 text-[11px] font-bold uppercase tracking-wider text-gray-400 dark:text-zinc-400">{zh ? '适配来源' : 'Adaptation source'}</th>}
            {columns.versionMismatch && <th className="px-3 py-3 text-[11px] font-bold uppercase tracking-wider text-gray-400 dark:text-zinc-400">{zh ? '版本校验' : 'Version check'}</th>}
            {columns.site && (
              <SortHeader col="site" sortConfig={sortConfig} onSort={onSort}>
                {zh ? '站点' : 'Site'}
              </SortHeader>
            )}
            {columns.rack && <th className="px-3 py-3 text-[11px] font-bold uppercase tracking-wider text-gray-400 dark:text-zinc-400">{zh ? '机柜' : 'Rack'}</th>}
            {columns.rackUnit && <th className="px-3 py-3 text-[11px] font-bold uppercase tracking-wider text-gray-400 dark:text-zinc-400">{zh ? 'U 位' : 'Rack unit'}</th>}
            {columns.tags && (
              <th className="px-3 py-3 text-[11px] font-bold uppercase tracking-wider text-gray-400 dark:text-zinc-400">
                {zh ? '标签' : 'Tags'}
              </th>
            )}
            {columns.status && (
              <SortHeader col="status" sortConfig={sortConfig} onSort={onSort}>{zh ? '在线状态' : 'Status'}</SortHeader>
            )}
            {columns.health && <th className="px-3 py-3 text-[11px] font-bold uppercase tracking-wider text-gray-400 dark:text-zinc-400">{zh ? '健康状态' : 'Health'}</th>}
            {columns.lifecycle && <th className="px-3 py-3 text-[11px] font-bold uppercase tracking-wider text-gray-400 dark:text-zinc-400">{zh ? '生命周期' : 'Lifecycle'}</th>}
            {columns.checkStatus && <th className="px-3 py-3 text-[11px] font-bold uppercase tracking-wider text-gray-400 dark:text-zinc-400">{zh ? '连通性检查' : 'Connectivity check'}</th>}
            {columns.checkTime && <th className="px-3 py-3 text-[11px] font-bold uppercase tracking-wider text-gray-400 dark:text-zinc-400">{zh ? '检查时间' : 'Check time'}</th>}
            {columns.cpu && <th className="px-3 py-3 text-[11px] font-bold uppercase tracking-wider text-gray-400 dark:text-zinc-400">CPU</th>}
            {columns.memory && <th className="px-3 py-3 text-[11px] font-bold uppercase tracking-wider text-gray-400 dark:text-zinc-400">{zh ? '内存' : 'Memory'}</th>}
            {columns.actions && (
              <TableActionHeader className="px-3 py-3 text-[11px] font-bold uppercase tracking-wider text-gray-400 dark:text-zinc-400 text-right pr-4">
                {zh ? '操作' : 'Actions'}
              </TableActionHeader>
            )}
          </tr>
        </thead>
        <tbody>
          {rows.map(device => {
            const selected = selectedIds.includes(device.id);
            const expanded = expandedIds.has(device.id);
            const testing = connectionTestingDeviceId === device.id;
            const cpu = clampPercent(device.cpu_usage);
            const mem = clampPercent(device.memory_usage);
            const assetMetadata = device as Device & { asset_vendor?: string; asset_model?: string };
            const adaptation = getDevicePlatformAdaptation(device, zh ? 'zh' : 'en');
            const adaptationName = platformBindingName(device, zh) || (zh ? '待自动识别' : 'Awaiting detection');
            const adaptationVersion = adaptationVersionLabel(device) || '—';
            const statusConfig = STATUS_CFG[device.status] || STATUS_CFG.pending;
            const healthConfig = HEALTH_CFG[device.health_status || 'unknown'] || HEALTH_CFG.unknown;
            const lifecycleConfig = LIFECYCLE_CFG[device.lifecycle_status || 'staging'] || LIFECYCLE_CFG.staging;
            const connectionCheck = deviceConnectionChecks[device.id];
            const checkConfig = connectionCheck ? (CHECK_BADGE[connectionCheck.status] || CHECK_BADGE.fail) : null;
            // Zero is a valid health value.  Only hide the bars when the
            // collection status says there is no usable snapshot.
            const metricsAvailable = device.collection_status === 'healthy'
              || Boolean(device.collection_last_success_at)
              || (!device.collection_status && (device.cpu_usage !== 0 || device.memory_usage !== 0));

            return (
              <React.Fragment key={device.id}>
                <tr
                  onClick={() => onShowDetails(device)}
                  className={`border-b border-black/[.04] dark:border-white/[.04] transition-colors cursor-pointer
                  hover:bg-black/[.02] dark:hover:bg-white/[.025] group
                  ${selected ? 'bg-[#00bceb]/[.04] dark:bg-[#00bceb]/[.06]' : ''}
                  ${expanded ? 'bg-black/[.015] dark:bg-white/[.02]' : ''}`}>
                  {/* Checkbox */}
                  <td className="px-3 py-2.5" onClick={e => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      title={`Select ${device.hostname || device.ip_address}`}
                      className="rounded border-black/20 dark:border-white/20 text-[#00bceb] focus:ring-[#00bceb] focus:ring-offset-0"
                      checked={selected}
                      onChange={e => {
                        if (e.target.checked) onSelectChange(prev => [...prev, device.id]);
                        else onSelectChange(prev => prev.filter(id => id !== device.id));
                      }}
                    />
                  </td>
                  {/* Expand */}
                  <td className="px-1 py-2.5" onClick={e => e.stopPropagation()}>
                    <button onClick={() => toggleExpand(device.id)}
                      className="p-0.5 rounded text-gray-400 dark:text-zinc-500 hover:text-gray-700 dark:hover:text-zinc-200 transition-colors"
                      title={zh ? '展开详情' : 'Expand details'}>
                      <ChevronRight size={13} className={`transition-transform duration-200 ${expanded ? 'rotate-90' : ''}`} />
                    </button>
                  </td>
                  {columns.hostname && <td className="px-3 py-2.5 text-xs font-bold text-gray-900 dark:text-white group-hover:text-blue-600 dark:group-hover:text-blue-400">{device.hostname || (zh ? '未知' : 'Unknown')}</td>}
                  {columns.assetTag && <td className="px-3 py-2.5 text-xs font-mono text-gray-700 dark:text-zinc-300">{device.asset_tag || '—'}</td>}
                  {columns.managementIp && <td className="px-3 py-2.5 text-xs font-mono text-gray-700 dark:text-zinc-300">{device.ip_address || '—'}</td>}
                  {columns.category && <td className="px-3 py-2.5 text-xs text-gray-700 dark:text-zinc-300">{device.device_category || '—'}</td>}
                  {columns.role && <td className="px-3 py-2.5 text-xs text-gray-700 dark:text-zinc-300">{device.role || '—'}</td>}
                  {columns.connectionMethod && <td className="px-3 py-2.5 text-xs font-semibold uppercase text-gray-600 dark:text-zinc-300">{device.connection_method || '—'}</td>}
                  {columns.vendor && <td className="px-3 py-2.5 text-xs text-gray-700 dark:text-zinc-300">{device.vendor || assetMetadata.asset_vendor || vendorOf(device.platform)}</td>}
                  {columns.platform && (
                    <td className="px-3 py-2.5 text-xs text-gray-700 dark:text-zinc-300">{device.platform || 'unknown'}</td>
                  )}
                  {columns.model && <td className="px-3 py-2.5 text-xs text-gray-700 dark:text-zinc-300">{device.model || assetMetadata.asset_model || '—'}</td>}
                  {columns.version && <td className="px-3 py-2.5 text-xs font-mono text-gray-700 dark:text-zinc-300">{device.version || '—'}</td>}
                  {columns.adaptation && <td className="px-3 py-2.5 text-xs text-gray-700 dark:text-zinc-300" title={adaptationName}>{adaptationName}</td>}
                  {columns.adaptationVersion && <td className="px-3 py-2.5 text-xs text-gray-700 dark:text-zinc-300">{adaptationVersion}</td>}
                  {columns.adaptationSource && <td className="px-3 py-2.5 text-xs text-gray-700 dark:text-zinc-300">{adaptation.explicit ? (zh ? '手动绑定' : 'Bound') : (zh ? '默认' : 'Default')}</td>}
                  {columns.versionMismatch && <td className="px-3 py-2.5 text-xs">{hasVersionMismatch(device) ? <span className="text-amber-700 dark:text-amber-300">{zh ? '不一致' : 'Mismatch'}</span> : <span className="text-gray-400 dark:text-zinc-500">{zh ? '一致' : 'Match'}</span>}</td>}
                  {columns.site && (
                    <td className="px-3 py-2.5 text-xs font-medium text-gray-800 dark:text-zinc-200">{device.datacenter || device.site || '—'}</td>
                  )}
                  {columns.rack && <td className="px-3 py-2.5 text-xs text-gray-700 dark:text-zinc-300">{device.rack_code || device.rack_name || device.rack || '—'}</td>}
                  {columns.rackUnit && <td className="px-3 py-2.5 text-xs text-gray-700 dark:text-zinc-300">{device.rack_unit || '—'}</td>}
                  {/* Tags */}
                  {columns.tags && (
                    <td className="px-3 py-2.5">
                      <div className="flex flex-wrap gap-1 max-w-[200px]">
                        {(device.tags || []).slice(0, 3).map(tag => (
                          <span
                            key={tag.id}
                            className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[9px] font-semibold whitespace-nowrap"
                            style={{ color: tag.color || '#2563eb', backgroundColor: `${tag.color || '#2563eb'}15` }}
                            title={tag.description || tag.code}
                          >
                            <span className="h-1 w-1 rounded-full flex-shrink-0" style={{ backgroundColor: tag.color || '#2563eb' }} />
                            <span className="truncate max-w-[60px]">{zh ? (tag.label_zh || tag.label) : tag.label}</span>
                          </span>
                        ))}
                        {(device.tags || []).length > 3 && (
                          <span className="text-[9px] font-mono text-gray-400 px-1">
                            +{(device.tags || []).length - 3}
                          </span>
                        )}
                        {(device.tags || []).length === 0 && <span className="text-xs text-gray-400 dark:text-zinc-500">—</span>}
                      </div>
                    </td>
                  )}
                  {columns.status && <td className={`px-3 py-2.5 text-xs font-bold ${statusConfig.text}`}>{zh ? statusConfig.labelZh : statusConfig.labelEn}</td>}
                  {columns.health && <td className={`px-3 py-2.5 text-xs font-semibold ${healthConfig.text}`}>{zh ? healthConfig.labelZh : healthConfig.labelEn}</td>}
                  {columns.lifecycle && <td className={`px-3 py-2.5 text-xs font-semibold ${lifecycleConfig.text}`}>{zh ? lifecycleConfig.labelZh : lifecycleConfig.labelEn}</td>}
                  {columns.checkStatus && <td className="px-3 py-2.5 text-xs">{checkConfig ? <span className={`inline-flex rounded border px-1.5 py-0.5 font-bold ${checkConfig.cls}`}>{zh ? checkConfig.zh : checkConfig.en}</span> : <span className="text-gray-400 dark:text-zinc-500">—</span>}</td>}
                  {columns.checkTime && <td className="px-3 py-2.5 text-xs text-gray-600 dark:text-zinc-400">{connectionCheck?.checked_at ? formatCheckTime(connectionCheck.checked_at, language) : '—'}</td>}
                  {columns.cpu && <td className="px-3 py-2.5 text-xs tabular-nums text-gray-700 dark:text-zinc-300">{metricsAvailable ? `${cpu}%` : '—'}</td>}
                  {columns.memory && <td className="px-3 py-2.5 text-xs tabular-nums text-gray-700 dark:text-zinc-300">{metricsAvailable ? `${mem}%` : '—'}</td>}
                  {/* Actions */}
                  {columns.actions && (
                    <td className="px-3 py-2.5 text-right whitespace-nowrap" onClick={e => e.stopPropagation()}>
                      <ActionIconGroup label={zh ? '设备操作' : 'Device actions'}>
                        <ActionIconButton
                          icon={Terminal}
                          label={zh ? '管理 / 配置' : 'Manage / Config'}
                          variant="accent"
                          onClick={() => onManage(device)}
                        />
                        <ActionIconButton
                          icon={Activity}
                          label={zh ? '连通性检测' : 'Check connectivity'}
                          variant="accent"
                          onClick={() => onTestConnection(device, 'quick')}
                          iconClassName={testing ? 'animate-pulse' : undefined}
                        />
                        {onEdit && (
                        <ActionIconButton
                          icon={Pencil}
                          label={zh ? '编辑' : 'Edit'}
                          onClick={() => onEdit(device)}
                        />
                        )}
                        {onDelete && (
                        <ActionIconButton
                          icon={Trash2}
                          label={zh ? '删除' : 'Delete'}
                          variant="danger"
                          onClick={() => onDelete(device.id)}
                        />
                        )}
                      </ActionIconGroup>
                    </td>
                  )}
                </tr>
                {expanded && (
                  <tr>
                    <td colSpan={visibleCount} className="p-0">
                      <DeviceRowExpand device={device} language={language} deviceConnectionChecks={deviceConnectionChecks} />
                    </td>
                  </tr>
                )}
              </React.Fragment>
            );
          })}

          {/* Empty state */}
          {!loading && rows.length === 0 && (
            <tr>
              <td colSpan={visibleCount} className="px-6 py-12 text-center">
                <WifiOff size={28} className="mx-auto mb-2 text-gray-300 dark:text-zinc-600" />
                <p className="text-sm text-gray-400 dark:text-zinc-500">
                  {zh ? '没有匹配的设备' : 'No devices found for current filters.'}
                </p>
              </td>
            </tr>
          )}

          {/* Loading state */}
          {loading && rows.length === 0 && (
            <tr>
              <td colSpan={visibleCount} className="px-6 py-12 text-center">
                <div className="inline-block w-5 h-5 border-2 border-[#00bceb]/30 border-t-[#00bceb] rounded-full animate-spin mb-2" />
                <p className="text-sm text-gray-400 dark:text-zinc-500">
                  {zh ? '加载中…' : 'Loading devices...'}
                </p>
              </td>
            </tr>
          )}
        </tbody>
      </DataTable>
    </div>
  );
};

export default DeviceTable;
