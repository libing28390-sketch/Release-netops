import React, { useState, useCallback } from 'react';
import {
  ChevronDown, ChevronUp, ChevronRight,
  Pencil, Trash2,
  Activity, WifiOff, Terminal,
} from 'lucide-react';
import type { Device, DeviceConnectionCheckSummary } from '../../types';
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
      className={`px-3 py-2.5 text-[10px] font-bold uppercase tracking-wider cursor-pointer select-none transition-colors
        ${active ? 'text-[#00bceb]' : 'text-black/35 dark:text-white/30 hover:text-black/55 dark:hover:text-white/55'} ${className}`}
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
      <table className="w-full text-left border-collapse min-w-[860px]">
        <thead>
          <tr className="bg-black/[.02] dark:bg-white/[.02] border-b border-black/5 dark:border-white/6">
            <th className="px-3 py-2.5 w-9">
              <input
                type="checkbox"
                title={zh ? '选择全部' : 'Select all'}
                className="rounded border-black/20 dark:border-white/20 text-[#00bceb] focus:ring-[#00bceb] focus:ring-offset-0"
                checked={allChecked}
                ref={(el) => { if (el) el.indeterminate = someChecked; }}
                onChange={e => handleSelectAll(e.target.checked)}
              />
            </th>
            <th className="px-1 py-2.5 w-6" />
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
              <th className="px-3 py-2.5 text-[10px] font-bold uppercase tracking-wider text-black/35 dark:text-white/30">
                {zh ? '标签' : 'Tags'}
              </th>
            )}
            {columns.status && (
              <SortHeader col="status" sortConfig={sortConfig} onSort={onSort}>
                {zh ? '状态' : 'Status'}
              </SortHeader>
            )}
            {columns.cpuMem && (
              <th className="px-3 py-2.5 text-[10px] font-bold uppercase tracking-wider text-black/35 dark:text-white/30">
                CPU / MEM
              </th>
            )}
            {columns.actions && (
              <th className="px-3 py-2.5 text-[10px] font-bold uppercase tracking-wider text-black/35 dark:text-white/30 text-right pr-4">
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

            return (
              <React.Fragment key={device.id}>
                <tr
                  onClick={() => onShowDetails(device)}
                  className={`border-b border-black/[.04] dark:border-white/[.04] transition-colors cursor-pointer
                  hover:bg-black/[.02] dark:hover:bg-white/[.025] group
                  ${selected ? 'bg-[#00bceb]/[.04] dark:bg-[#00bceb]/[.06]' : ''}
                  ${expanded ? 'bg-black/[.015] dark:bg-white/[.02]' : ''}`}>
                  {/* Checkbox */}
                  <td className="px-3 py-2" onClick={e => e.stopPropagation()}>
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
                  <td className="px-1 py-2" onClick={e => e.stopPropagation()}>
                    <button onClick={() => toggleExpand(device.id)}
                      className="p-0.5 rounded text-black/25 dark:text-white/20 hover:text-black/50 dark:hover:text-white/50 transition-colors"
                      title={zh ? '展开详情' : 'Expand details'}>
                      <ChevronRight size={13} className={`transition-transform duration-200 ${expanded ? 'rotate-90' : ''}`} />
                    </button>
                  </td>
                  {/* Device (hostname + ip + role) */}
                  {columns.device && (
                    <td className="px-3 py-2">
                      <div className="text-left">
                        <span className="text-[12px] font-semibold text-black/80 dark:text-white/85 group-hover:text-[#00bceb] transition-colors">
                          {device.hostname || 'Unknown'}
                        </span>
                        <span className="block text-[10px] font-mono text-black/35 dark:text-white/30 mt-0.5">
                          {device.ip_address || '0.0.0.0'}
                        </span>
                      </div>
                      {device.role && (
                        <span className="inline-block mt-0.5 text-[9px] font-semibold uppercase px-1.5 py-0.5 rounded
                          bg-black/[.04] dark:bg-white/6 text-black/30 dark:text-white/30">
                          {device.role}
                        </span>
                      )}
                      {device.connection_method && (
                        <span className={`inline-block mt-0.5 ml-1 text-[9px] font-semibold uppercase px-1.5 py-0.5 rounded
                          ${device.connection_method === 'netconf'
                            ? 'bg-violet-500/8 text-violet-500 dark:text-violet-400'
                            : 'bg-black/[.04] dark:bg-white/6 text-black/30 dark:text-white/30'
                          }`}>
                          {device.connection_method === 'netconf' ? 'NETCONF' : 'SSH'}
                        </span>
                      )}
                    </td>
                  )}
                  {/* Platform */}
                  {columns.platform && (
                    <td className="px-3 py-2">
                      <span className="text-[11px] font-medium text-black/65 dark:text-white/65">{device.vendor || vendorOf(device.platform)}</span>
                      <span className="block text-[10px] text-black/35 dark:text-white/30 mt-0.5">{device.platform || 'unknown'}</span>
                      {device.version && (
                        <span className="block text-[10px] font-mono text-black/25 dark:text-white/20 mt-0.5 truncate max-w-[120px]" title={device.version}>
                          {device.version}
                        </span>
                      )}
                    </td>
                  )}
                  {/* Site */}
                  {columns.site && (
                    <td className="px-3 py-2">
                      <span className="text-[11px] text-black/55 dark:text-white/55">{device.datacenter || device.site || '—'}</span>
                      {device.rack && (
                        <span className="block text-[10px] text-black/35 dark:text-white/30 mt-0.5">
                          Rack {device.rack}{device.rack_unit ? ` / U${device.rack_unit}` : ''}
                        </span>
                      )}
                    </td>
                  )}
                  {/* Tags */}
                  {columns.tags && (
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap gap-1 max-w-[200px]">
                        {(device.tags || []).slice(0, 3).map(tag => (
                          <span
                            key={tag.id}
                            className="inline-flex items-center gap-0.5 rounded-full border border-black/5 dark:border-white/8 bg-black/[0.03] dark:bg-white/[0.06] px-1.5 py-0.5 text-[9px]"
                            title={tag.description || tag.value}
                          >
                            <span className="h-1.5 w-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: tag.color || '#06b6d4' }} />
                            <span className="text-black/60 dark:text-white/60 truncate max-w-[60px]">{zh ? (tag.label_zh || tag.label) : tag.label}</span>
                          </span>
                        ))}
                        {(device.tags || []).length > 3 && (
                          <span className="text-[9px] text-black/30 dark:text-white/25 px-1">
                            +{(device.tags || []).length - 3}
                          </span>
                        )}
                      </div>
                    </td>
                  )}
                  {/* Status */}
                  {columns.status && (
                    <td className="px-3 py-2">
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
                    <td className="px-3 py-2">
                      <CpuMemBar cpu={cpu} mem={mem} language={language} />
                    </td>
                  )}
                  {/* Actions */}
                  {columns.actions && (
                    <td className="px-3 py-2" onClick={e => e.stopPropagation()}>
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => onManage(device)}
                          title={zh ? '管理 / 配置' : 'Manage / Config'}
                          className="inline-flex items-center justify-center w-7 h-7 rounded-md text-[10px] font-semibold
                            bg-[#00bceb]/10 text-[#0096bd] dark:text-[#5dd8f0] hover:bg-[#00bceb]/20 transition-all">
                          <Terminal size={13} />
                        </button>
                        <button
                          onClick={() => onTestConnection(device, 'quick')}
                          title={zh ? '连通性检测' : 'Check connectivity'}
                          className={`inline-flex items-center justify-center w-7 h-7 rounded-md text-[10px] font-semibold transition-all
                            ${testing ? 'bg-blue-500/10 text-blue-600 dark:text-blue-400' : 'bg-violet-500/10 text-violet-600 dark:text-violet-400 hover:bg-violet-500/20'}`}>
                          <Activity size={13} className={testing ? 'animate-pulse' : ''} />
                        </button>
                        {onEdit && (
                        <button
                          onClick={() => onEdit(device)}
                          title={zh ? '编辑' : 'Edit'}
                          className="inline-flex items-center justify-center w-7 h-7 rounded-md
                            text-black/30 dark:text-white/25 hover:bg-black/5 dark:hover:bg-white/8
                            hover:text-black/60 dark:hover:text-white/60 transition-all">
                          <Pencil size={13} />
                        </button>
                        )}
                        {onDelete && (
                        <button
                          onClick={() => onDelete(device.id)}
                          title={zh ? '删除' : 'Delete'}
                          className="inline-flex items-center justify-center w-7 h-7 rounded-md
                            text-black/30 dark:text-white/25 hover:bg-red-500/10
                            hover:text-red-500 dark:hover:text-red-400 transition-all">
                          <Trash2 size={13} />
                        </button>
                        )}
                      </div>
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
                <WifiOff size={28} className="mx-auto mb-2 text-black/15 dark:text-white/15" />
                <p className="text-sm text-black/35 dark:text-white/30">
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
                <p className="text-sm text-black/35 dark:text-white/30">
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
