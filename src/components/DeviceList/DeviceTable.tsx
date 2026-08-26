import React, { useState, useCallback } from 'react';
import {
  ChevronDown, ChevronUp, ChevronRight,
  Pencil, Trash2,
  Activity, WifiOff, Terminal,
} from 'lucide-react';
import type { Device, DeviceConnectionCheckSummary } from '../../types';
import { ActionIconButton, ActionIconGroup } from '../ui/ActionIconButton';
import StatusBadge from './StatusBadge';
import CpuMemBar from './CpuMemBar';
import DeviceRowExpand from './DeviceRowExpand';

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

/* ─── Column Def ─── */
export type ColumnKey = 'device' | 'platform' | 'site' | 'tags' | 'status' | 'cpuMem' | 'actions';

export interface ColumnVisibility {
  device: boolean;
  platform: boolean;
  site: boolean;
  tags: boolean;
  status: boolean;
  cpuMem: boolean;
  actions: boolean;
}

export const DEFAULT_COLUMNS: ColumnVisibility = {
  device: true,
  platform: true,
  site: true,
  tags: true,
  status: true,
  cpuMem: true,
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
}

const DeviceTable: React.FC<DeviceTableProps> = ({
  rows, loading, language, sortConfig, onSort,
  selectedIds, onSelectChange,
  onShowDetails, onEdit, onDelete, onManage, onTestConnection,
  deviceConnectionChecks, connectionTestingDeviceId,
  columns,
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

  return (
    <div className="overflow-x-auto">
      <table className="nx-data-table min-w-[860px]">
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
            {columns.device && (
              <SortHeader col="hostname" sortConfig={sortConfig} onSort={onSort}>
                {zh ? '设备' : 'Device'}
              </SortHeader>
            )}
            {columns.platform && (
              <SortHeader col="platform" sortConfig={sortConfig} onSort={onSort}>
                {zh ? '系统' : 'System'}
              </SortHeader>
            )}
            {columns.site && (
              <SortHeader col="site" sortConfig={sortConfig} onSort={onSort}>
                {zh ? '位置' : 'Location'}
              </SortHeader>
            )}
            {columns.tags && (
              <th className="px-3 py-3 text-[11px] font-bold uppercase tracking-wider text-gray-400 dark:text-zinc-400">
                {zh ? '标签' : 'Tags'}
              </th>
            )}
            {columns.status && (
              <SortHeader col="status" sortConfig={sortConfig} onSort={onSort}>
                {zh ? '状态' : 'Status'}
              </SortHeader>
            )}
            {columns.cpuMem && (
              <th className="px-3 py-3 text-[11px] font-bold uppercase tracking-wider text-gray-400 dark:text-zinc-400">
                CPU / MEM
              </th>
            )}
            {columns.actions && (
              <th className="px-3 py-3 text-[11px] font-bold uppercase tracking-wider text-gray-400 dark:text-zinc-400 text-right pr-4">
                {zh ? '操作' : 'Actions'}
              </th>
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
                  {/* Device (hostname + ip + role) */}
                  {columns.device && (
                    <td className="px-3 py-2.5">
                      <div className="text-left">
                        <span className="text-xs font-bold text-gray-900 dark:text-white group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">
                          {device.hostname || 'Unknown'}
                        </span>
                        <span className="block text-[10px] font-mono text-gray-400 dark:text-zinc-400 mt-0.5">
                          {device.ip_address || '0.0.0.0'}
                        </span>
                      </div>
                      {device.role && (
                        <span className="inline-block mt-0.5 text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded
                          bg-gray-50 dark:bg-zinc-800/60 text-gray-500 dark:text-zinc-400 border border-gray-100 dark:border-zinc-700/80">
                          {device.role}
                        </span>
                      )}
                      {device.connection_method && (
                        <span className={`inline-block mt-0.5 ml-1 text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded
                          ${device.connection_method === 'netconf'
                            ? 'bg-violet-50 text-violet-700 dark:bg-violet-950/40 dark:text-violet-300'
                            : 'bg-gray-50 dark:bg-zinc-800/60 text-gray-500 dark:text-zinc-400 border border-gray-100 dark:border-zinc-700/80'
                          }`}>
                          {device.connection_method === 'netconf' ? 'NETCONF' : 'SSH'}
                        </span>
                      )}
                    </td>
                  )}
                  {/* Platform */}
                  {columns.platform && (
                    <td className="px-3 py-2.5">
                      <span className="text-xs font-semibold text-gray-700 dark:text-zinc-300">{device.vendor || vendorOf(device.platform)}</span>
                      <span className="block text-[11px] text-gray-500 dark:text-zinc-400 mt-0.5">{device.platform || 'unknown'}</span>
                      {device.version && (
                        <span className="block text-[10px] font-mono text-gray-400 dark:text-zinc-500 mt-0.5 truncate max-w-[120px]" title={device.version}>
                          {device.version}
                        </span>
                      )}
                    </td>
                  )}
                  {/* Site */}
                  {columns.site && (
                    <td className="px-3 py-2.5">
                      <span className="text-xs font-medium text-gray-800 dark:text-zinc-200">{device.datacenter || device.site || '—'}</span>
                      {device.rack && (
                        <span className="block text-[10px] text-gray-400 dark:text-zinc-400 mt-0.5">
                          Rack {device.rack}{device.rack_unit ? ` / U${device.rack_unit}` : ''}
                        </span>
                      )}
                    </td>
                  )}
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
                      </div>
                    </td>
                  )}
                  {/* Status */}
                  {columns.status && (
                    <td className="px-3 py-2.5">
                      <StatusBadge
                        status={device.status}
                        healthStatus={device.health_status}
                        lifecycleStatus={device.lifecycle_status}
                        uptime={device.uptime}
                        connectionCheck={deviceConnectionChecks[device.id]}
                        language={language}
                      />
                    </td>
                  )}
                  {/* CPU / MEM */}
                  {columns.cpuMem && (
                    <td className="px-3 py-2.5">
                      <CpuMemBar cpu={cpu} mem={mem} language={language} empty={!metricsAvailable} />
                    </td>
                  )}
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
      </table>
    </div>
  );
};

export default DeviceTable;
