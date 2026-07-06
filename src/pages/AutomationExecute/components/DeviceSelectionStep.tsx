import React from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Search, CheckCircle2, LayoutGrid, List, Server, Terminal, Cpu, X, ChevronDown } from 'lucide-react';
import type { Device } from '../../../types';
import Pagination from '../../../components/Pagination';
import { DEVICE_PAGE_SIZE } from '../constants';
import { getDeviceCategory, getVendor } from '../helpers';

interface DeviceSelectionStepProps {
  isZh: boolean;
  language: string;
  automationSearch: string;
  onAutomationSearchChange: (val: string) => void;
  deviceTree: Array<{ site: string; count: number; onlineCount: number; roles: Array<{ role: string; count: number; onlineCount: number }> }>;
  treeFilterSite: string | null;
  treeFilterRole: string | null;
  handleTreeFilter: (site: string | null, role: string | null) => void;
  setTreeFilterSite: (site: string | null) => void;
  setTreeFilterRole: (role: string | null) => void;
  deviceTypeFilter: 'all' | 'network' | 'server';
  setDeviceTypeFilter: (val: 'all' | 'network' | 'server') => void;
  statusFilter: string;
  setStatusFilter: (val: 'all' | 'online' | 'offline') => void;
  filteredDevices: Device[];
  vendors: string[];
  vendorFilter: string;
  setVendorFilter: (val: string) => void;
  handleSelectAllOnline: () => void;
  deviceViewMode: 'grid' | 'list';
  setDeviceViewMode: (val: 'grid' | 'list') => void;
  pagedDevices: Device[];
  batchMode: boolean;
  onToggleBatchMode: () => void;
  batchDeviceIds: string[];
  onToggleBatchDevice: (deviceId: string) => void;
  selectedDevice: Device | null;
  devicePage: number;
  setDevicePage: (val: number) => void;
  targetCount: number;
  showSelectedDrawer: boolean;
  setShowSelectedDrawer: (val: boolean) => void;
  handleClearSelection: () => void;
  devices: Device[];
}

export const DeviceSelectionStep: React.FC<DeviceSelectionStepProps> = ({
  isZh,
  language,
  automationSearch,
  onAutomationSearchChange,
  deviceTree,
  treeFilterSite,
  treeFilterRole,
  handleTreeFilter,
  setTreeFilterSite,
  setTreeFilterRole,
  deviceTypeFilter,
  setDeviceTypeFilter,
  statusFilter,
  setStatusFilter,
  filteredDevices,
  vendors,
  vendorFilter,
  setVendorFilter,
  handleSelectAllOnline,
  deviceViewMode,
  setDeviceViewMode,
  pagedDevices,
  batchMode,
  onToggleBatchMode,
  batchDeviceIds,
  onToggleBatchDevice,
  selectedDevice,
  devicePage,
  setDevicePage,
  targetCount,
  showSelectedDrawer,
  setShowSelectedDrawer,
  handleClearSelection,
  devices,
}) => {
  return (
    <motion.div
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 20 }}
      transition={{ duration: 0.2 }}
      className="h-full flex flex-col gap-2"
    >
      <div className="flex-1 min-h-0 flex gap-3 overflow-hidden">
        {/* Left: Quick Filter Panel */}
        <div className="w-[200px] flex-shrink-0 bg-white rounded-xl border border-gray-100 overflow-hidden flex flex-col">
          <div className="px-3 py-2.5 border-b border-gray-100 flex items-center justify-between">
            <span className="text-[10px] font-bold uppercase tracking-widest text-gray-400">
              {isZh ? '快速筛选' : 'Quick Filter'}
            </span>
            {(treeFilterSite || treeFilterRole) && (
              <button
                onClick={() => {
                  setTreeFilterSite(null);
                  setTreeFilterRole(null);
                }}
                className="text-[10px] text-cyan-600 hover:text-cyan-700 font-semibold"
              >
                {isZh ? '清除' : 'Clear'}
              </button>
            )}
          </div>
          <div className="flex-1 min-h-0 overflow-auto p-2.5 space-y-3">
            {/* Search */}
            <div>
              <label className="text-[10px] font-semibold text-gray-400 block mb-1.5">{isZh ? '搜索设备' : 'Search'}</label>
              <div className="relative">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-300" size={12} />
                <input
                  type="text"
                  placeholder={isZh ? 'IP / 主机名...' : 'IP / Hostname...'}
                  value={automationSearch}
                  onChange={(e) => onAutomationSearchChange(e.target.value)}
                  className="w-full pl-7 pr-2.5 py-1.5 bg-gray-50 border border-gray-100 rounded-lg text-[11px] focus:border-cyan-300 focus:bg-white outline-none transition-all"
                />
              </div>
            </div>
            {/* Site chips */}
            <div>
              <label className="text-[10px] font-semibold text-gray-400 block mb-1.5">{isZh ? '站点' : 'Site'}</label>
              <div className="flex flex-wrap gap-1">
                {deviceTree.map((node) => (
                  <button
                    key={node.site}
                    onClick={() => handleTreeFilter(node.site, null)}
                    className={`px-2 py-1 rounded-md text-[10px] font-medium transition-all ${
                      treeFilterSite === node.site
                        ? 'bg-cyan-50 text-cyan-700 ring-1 ring-cyan-200'
                        : 'bg-gray-50 text-gray-500 hover:bg-gray-100'
                    }`}
                  >
                    {node.site}
                    <span className="ml-1 text-[9px] opacity-60">
                      {node.onlineCount}/{node.count}
                    </span>
                  </button>
                ))}
              </div>
            </div>
            {/* Device Type chips */}
            <div>
              <label className="text-[10px] font-semibold text-gray-400 block mb-1.5">{isZh ? '设备类型' : 'Device Type'}</label>
              <div className="flex flex-wrap gap-1">
                {(['all', 'network', 'server'] as const).map((t) => (
                  <button
                    key={t}
                    onClick={() => setDeviceTypeFilter(t)}
                    className={`px-2 py-1 rounded-md text-[10px] font-medium transition-all ${
                      deviceTypeFilter === t
                        ? 'bg-cyan-50 text-cyan-700 ring-1 ring-cyan-200'
                        : 'bg-gray-50 text-gray-500 hover:bg-gray-100'
                    }`}
                  >
                    {t === 'all' ? (isZh ? '全部' : 'All') : t === 'network' ? (isZh ? '网络设备' : 'Network') : (isZh ? '服务器' : 'Server')}
                  </button>
                ))}
              </div>
            </div>
            {/* Status chips */}
            <div>
              <label className="text-[10px] font-semibold text-gray-400 block mb-1.5">{isZh ? '状态' : 'Status'}</label>
              <div className="flex flex-wrap gap-1">
                {(['all', 'online', 'offline'] as const).map((s) => (
                  <button
                    key={s}
                    onClick={() => setStatusFilter(s)}
                    className={`px-2 py-1 rounded-md text-[10px] font-medium transition-all ${
                      statusFilter === s
                        ? 'bg-cyan-50 text-cyan-700 ring-1 ring-cyan-200'
                        : 'bg-gray-50 text-gray-500 hover:bg-gray-100'
                    }`}
                  >
                    {s === 'all' ? (isZh ? '全部' : 'All') : s === 'online' ? (isZh ? '在线' : 'Online') : (isZh ? '离线' : 'Offline')}
                  </button>
                ))}
              </div>
            </div>
            {/* Summary */}
            <div className="pt-2 border-t border-gray-100 text-[10px] text-gray-400">
              {isZh ? '匹配' : 'Found'} <span className="font-semibold text-gray-600">{filteredDevices.length}</span> {isZh ? '台设备' : 'devices'}
            </div>
          </div>
        </div>

        {/* Right Area: Table/Grid list */}
        <div className="flex-1 min-w-0 flex flex-col gap-2">
          {/* Filter bar */}
          <div className="flex-shrink-0 flex items-center gap-2 bg-white rounded-xl border border-gray-100 px-3 py-2">
            {vendors.length > 1 && (
              <select
                value={vendorFilter}
                onChange={(e) => setVendorFilter(e.target.value)}
                className="px-2.5 py-1.5 border border-gray-100 rounded-lg text-xs bg-gray-50 outline-none focus:border-cyan-300"
              >
                <option value="all">{isZh ? '全部厂商' : 'All Vendors'}</option>
                {vendors.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            )}
            <div className="flex-1" />
            <div className="flex items-center gap-2">
              <button
                onClick={handleSelectAllOnline}
                className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-100 hover:bg-emerald-100 transition-all"
              >
                <CheckCircle2 size={11} />
                {isZh ? '全选在线' : 'Select Online'}
              </button>
              <div className="w-px h-5 bg-gray-200" />
              <div className="flex items-center bg-gray-100 rounded-lg p-0.5">
                <button
                  onClick={() => setDeviceViewMode('grid')}
                  title={isZh ? '卡片视图' : 'Grid view'}
                  className={`p-1.5 rounded-md transition-all ${
                    deviceViewMode === 'grid' ? 'bg-white text-gray-700 shadow-sm' : 'text-gray-400 hover:text-gray-500'
                  }`}
                >
                  <LayoutGrid size={13} />
                </button>
                <button
                  onClick={() => setDeviceViewMode('list')}
                  title={isZh ? '列表视图' : 'List view'}
                  className={`p-1.5 rounded-md transition-all ${
                    deviceViewMode === 'list' ? 'bg-white text-gray-700 shadow-sm' : 'text-gray-400 hover:text-gray-500'
                  }`}
                >
                  <List size={13} />
                </button>
              </div>
            </div>
          </div>

          {/* List display */}
          <div className="flex-1 min-h-0 overflow-auto">
            {deviceViewMode === 'grid' ? (
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-2.5">
                {pagedDevices.map((device) => {
                  const isSelected = batchMode ? batchDeviceIds.includes(device.id) : selectedDevice?.id === device.id;
                  const vendor = getVendor(device.platform);
                  const isOffline = device.status !== 'online';
                  return (
                    <motion.button
                      key={device.id}
                      initial={{ opacity: 0, scale: 0.95 }}
                      animate={{ opacity: 1, scale: 1 }}
                      disabled={isOffline}
                      onClick={() => {
                        if (isOffline) return;
                        if (!batchMode) onToggleBatchMode();
                        onToggleBatchDevice(device.id);
                      }}
                      className={`relative p-3 rounded-xl border-2 text-left transition-all group ${
                        isOffline
                          ? 'border-gray-100 bg-gray-50/60 opacity-50 cursor-not-allowed'
                          : isSelected
                          ? 'border-cyan-400 bg-cyan-50/60 shadow-md shadow-cyan-500/10 ring-1 ring-cyan-200'
                          : 'border-gray-100 bg-white hover:border-cyan-200 hover:shadow-md hover:-translate-y-0.5'
                      }`}
                    >
                      <div
                        className={`absolute top-2 right-2 w-4 h-4 rounded border-2 flex items-center justify-center transition-all ${
                          isOffline ? 'border-gray-200 bg-gray-100' : isSelected ? 'bg-cyan-500 border-cyan-500' : 'border-gray-200 bg-white'
                        }`}
                      >
                        {isSelected && <CheckCircle2 size={10} className="text-white" />}
                      </div>
                      <div className="flex items-center gap-2 mb-1.5">
                        <span
                          className={`w-2 h-2 rounded-full flex-shrink-0 ${
                            device.status === 'online' ? 'bg-emerald-500 shadow-sm shadow-emerald-500/50' : 'bg-gray-300'
                          }`}
                        />
                        <div className="flex-1 flex items-center justify-between min-w-0">
                          <span className="text-xs font-bold text-gray-800 truncate">{device.hostname}</span>
                          {getDeviceCategory(device) === 'server' ? (
                            <Terminal size={10} className="text-gray-400 ml-1" />
                          ) : (
                            <Cpu size={10} className="text-gray-400 ml-1" />
                          )}
                        </div>
                      </div>
                      <p className="text-[11px] font-mono text-gray-400 mb-1.5">{device.ip_address}</p>
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">{vendor}</span>
                        {device.role && <span className="text-[9px] px-1.5 py-0.5 rounded bg-gray-50 text-gray-400">{device.role}</span>}
                      </div>
                    </motion.button>
                  );
                })}
                {filteredDevices.length === 0 && (
                  <div className="col-span-full py-16 text-center text-gray-300">
                    <Server size={32} strokeWidth={1} className="mx-auto mb-3 opacity-50" />
                    <p className="text-sm">{isZh ? '没有匹配的设备' : 'No matching devices'}</p>
                  </div>
                )}
              </div>
            ) : (
              <div className="rounded-xl border border-gray-100 bg-white overflow-hidden">
                <table className="w-full text-left">
                  <thead>
                    <tr className="border-b border-gray-100 bg-gray-50/60">
                      <th className="w-10 px-3 py-2">
                        <input
                          type="checkbox"
                          checked={
                            pagedDevices.filter((d) => d.status === 'online').length > 0 &&
                            pagedDevices.filter((d) => d.status === 'online').every((d) => batchDeviceIds.includes(d.id))
                          }
                          onChange={() => {
                            if (!batchMode) onToggleBatchMode();
                            const onlineOnPage = pagedDevices.filter((d) => d.status === 'online');
                            const allSelected = onlineOnPage.every((d) => batchDeviceIds.includes(d.id));
                            onlineOnPage.forEach((d) => {
                              if (allSelected) {
                                if (batchDeviceIds.includes(d.id)) onToggleBatchDevice(d.id);
                              } else {
                                if (!batchDeviceIds.includes(d.id)) onToggleBatchDevice(d.id);
                              }
                            });
                          }}
                          title="Select all"
                          className="w-3.5 h-3.5 rounded accent-cyan-500"
                        />
                      </th>
                      <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-gray-400">{isZh ? '状态' : 'Status'}</th>
                      <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-gray-400">{isZh ? '主机名' : 'Hostname'}</th>
                      <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-gray-400">IP</th>
                      <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-gray-400">{isZh ? '厂商' : 'Vendor'}</th>
                      <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-gray-400">{isZh ? '类型' : 'Type'}</th>
                      <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-gray-400">{isZh ? '角色' : 'Role'}</th>
                      <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-gray-400">{isZh ? '站点' : 'Site'}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pagedDevices.map((device) => {
                      const isSelected = batchDeviceIds.includes(device.id);
                      const vendor = getVendor(device.platform);
                      const isOffline = device.status !== 'online';
                      return (
                        <tr
                          key={device.id}
                          onClick={() => {
                            if (isOffline) return;
                            if (!batchMode) onToggleBatchMode();
                            onToggleBatchDevice(device.id);
                          }}
                          className={`border-b border-gray-50 transition-colors ${
                            isOffline ? 'opacity-40 cursor-not-allowed' : isSelected ? 'bg-cyan-50/70 hover:bg-cyan-50 cursor-pointer' : 'hover:bg-gray-50/80 cursor-pointer'
                          }`}
                        >
                          <td className="px-3 py-1.5">
                            <input
                              title="Select device"
                              type="checkbox"
                              disabled={isOffline}
                              checked={isSelected}
                              onChange={(e) => {
                                e.stopPropagation();
                                if (isOffline) return;
                                if (!batchMode) onToggleBatchMode();
                                onToggleBatchDevice(device.id);
                              }}
                              onClick={(e) => e.stopPropagation()}
                              className="w-3.5 h-3.5 rounded accent-cyan-500 disabled:opacity-30"
                            />
                          </td>
                          <td className="px-3 py-1.5">
                            <span
                              className={`inline-flex items-center gap-1.5 text-[10px] font-semibold ${
                                device.status === 'online' ? 'text-emerald-600' : 'text-gray-400'
                              }`}
                            />
                            <span className="flex items-center gap-1">
                              <span className={`w-1.5 h-1.5 rounded-full ${device.status === 'online' ? 'bg-emerald-500' : 'bg-gray-300'}`} />
                              {device.status === 'online' ? (isZh ? '在线' : 'Online') : (isZh ? '离线' : 'Offline')}
                            </span>
                          </td>
                          <td className="px-3 py-1.5 text-xs font-bold text-gray-800">{device.hostname}</td>
                          <td className="px-3 py-1.5 text-[11px] font-mono text-gray-500">{device.ip_address}</td>
                          <td className="px-3 py-1.5">
                            <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">{vendor}</span>
                          </td>
                          <td className="px-3 py-1.5">
                            <div className="flex items-center gap-1.5 text-[10px] text-gray-400">
                              {getDeviceCategory(device) === 'server' ? (
                                <>
                                  <Terminal size={10} /> {isZh ? '服务器' : 'Server'}
                                </>
                              ) : (
                                <>
                                  <Cpu size={10} /> {isZh ? '网络设备' : 'Network'}
                                </>
                              )}
                            </div>
                          </td>
                          <td className="px-3 py-1.5 text-[11px] text-gray-500">{device.role || '—'}</td>
                          <td className="px-3 py-1.5 text-[11px] text-cyan-500">{device.site || '—'}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                {filteredDevices.length === 0 && (
                  <div className="py-16 text-center text-gray-300">
                    <Server size={32} strokeWidth={1} className="mx-auto mb-3 opacity-50" />
                    <p className="text-sm">{isZh ? '没有匹配的设备' : 'No matching devices'}</p>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Pagination */}
          {filteredDevices.length > DEVICE_PAGE_SIZE && (
            <div className="flex-shrink-0 px-1">
              <Pagination
                currentPage={devicePage}
                totalItems={filteredDevices.length}
                onPageChange={setDevicePage}
                itemsPerPage={DEVICE_PAGE_SIZE}
                language={language}
              />
            </div>
          )}
        </div>
      </div>

      {/* Bottom Sticky Action Bar */}
      <div className="flex-shrink-0 flex items-center justify-between rounded-xl border border-gray-100 bg-white px-4 py-2.5 shadow-sm">
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-500">
            {isZh ? `共 ${filteredDevices.length} 台` : `${filteredDevices.length} devices`}
            {statusFilter === 'all' && (
              <span className="ml-1.5 text-emerald-600 font-medium font-sans">
                ({devices.filter((d) => d.status === 'online').length} {isZh ? '在线' : 'online'})
              </span>
            )}
          </span>
          {targetCount > 0 && (
            <>
              <button
                onClick={() => setShowSelectedDrawer(!showSelectedDrawer)}
                className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-cyan-50 text-cyan-700 text-xs font-bold border border-cyan-100 shadow-sm hover:bg-cyan-100 transition-all cursor-pointer"
              >
                <CheckCircle2 size={12} />
                {isZh ? `已选 ${targetCount} 台` : `${targetCount} selected`}
                <ChevronDown size={10} className={`transition-transform ${showSelectedDrawer ? 'rotate-180' : ''}`} />
              </button>
              <button onClick={handleClearSelection} className="text-[11px] text-gray-400 hover:text-red-500 transition-colors font-semibold">
                {isZh ? '清空已选' : 'Clear All'}
              </button>
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-gray-400 font-medium italic">{isZh ? '请从顶部或下方选择工具' : 'Select a tool from above'}</span>
        </div>
      </div>

      {/* Selected Devices Drawer Overlay */}
      <AnimatePresence>
        {showSelectedDrawer && targetCount > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 10 }}
            className="absolute bottom-16 left-4 right-4 z-40 bg-white rounded-xl border border-gray-200 shadow-xl max-h-[240px] overflow-hidden"
          >
            <div className="px-4 py-2.5 border-b border-gray-100 flex items-center justify-between bg-gray-50/50">
              <span className="text-xs font-bold text-gray-600">{isZh ? `已选设备 (${targetCount})` : `Selected Devices (${targetCount})`}</span>
              <button title="Close" onClick={() => setShowSelectedDrawer(false)} className="p-1 rounded-lg hover:bg-gray-100 text-gray-400">
                <X size={12} />
              </button>
            </div>
            <div className="overflow-auto max-h-[190px] p-2">
              <div className="flex flex-wrap gap-1.5">
                {(batchMode ? batchDeviceIds : selectedDevice ? [selectedDevice.id] : []).map((deviceId) => {
                  const dev = devices.find((d) => d.id === deviceId);
                  if (!dev) return null;
                  return (
                    <span key={deviceId} className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-gray-50 border border-gray-100 text-xs group">
                      <span className={`w-1.5 h-1.5 rounded-full ${dev.status === 'online' ? 'bg-emerald-500' : 'bg-gray-300'}`} />
                      <span className="font-semibold text-gray-700">{dev.hostname}</span>
                      <span className="text-gray-400 font-mono text-[10px]">{dev.ip_address}</span>
                      <button title="Remove" onClick={() => onToggleBatchDevice(deviceId)} className="text-gray-300 hover:text-red-500 transition-colors ml-0.5">
                        <X size={10} />
                      </button>
                    </span>
                  );
                })}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
};
