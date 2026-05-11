import React, { useState, useMemo, useEffect, useRef, useCallback } from 'react';
import { Search, Server, Activity, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, X, Filter } from 'lucide-react';
import type { Device } from '../types';
import { sectionToolbarClass } from '../components/shared';
import PageHero from '../components/PageHero';

interface InterfaceMonitoringTabProps {
  devices: Device[];
  devicesLastUpdatedAt: number | null;
  language: string;
  snmpTestingId: string | null;
  snmpSyncingId: string | null;
  onSnmpTest: (deviceId: string) => Promise<void>;
  onSnmpSyncNow: (deviceId: string) => Promise<void>;
}

function InterfaceMonitoringTab({
  devices,
  devicesLastUpdatedAt,
  language,
  snmpTestingId,
  snmpSyncingId,
  onSnmpTest,
  onSnmpSyncNow,
}: InterfaceMonitoringTabProps) {
  // ── Internal state ──
  const [intfSearch, setIntfSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [intfDevicePage, setIntfDevicePage] = useState(1);
  const [intfExpandedDevice, setIntfExpandedDevice] = useState<string | null>(null);
  const [intfPageMap, setIntfPageMap] = useState<Record<string, number>>({});
  const [intfFilterMap, setIntfFilterMap] = useState<Record<string, string>>({});
  const [intfInnerStatusMap, setIntfInnerStatusMap] = useState<Record<string, 'all' | 'up' | 'down' | 'error'>>({});
  const [intfStatusFilter, setIntfStatusFilter] = useState<'all' | 'hasData' | 'hasDown' | 'hasErrors'>('hasData');
  const [intfSortBy, setIntfSortBy] = useState<'name' | 'downCount' | 'errors' | 'bw'>('name');
  const searchInputRef = useRef<HTMLInputElement>(null);

  // ── Debounce search input (150ms) ──
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(intfSearch);
      setIntfDevicePage(1);
    }, 150);
    return () => clearTimeout(timer);
  }, [intfSearch]);

  // ── Ctrl+K shortcut to focus search ──
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        searchInputRef.current?.focus();
        searchInputRef.current?.select();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  // ── "Updated ago" timer ──
  const [intfNowTick, setIntfNowTick] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => setIntfNowTick((v) => v + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  const intfUpdatedAgoSec = useMemo(() => {
    if (!devicesLastUpdatedAt) return null;
    return Math.max(0, Math.floor((Date.now() - devicesLastUpdatedAt) / 1000));
  }, [devicesLastUpdatedAt, intfNowTick]);

  // ── Computed values ──
  const DEVS_PER_PAGE = 10;
  const INTFS_PER_PAGE = 15;
  const fmtBytes = (b: number) => b > 1073741824 ? `${(b / 1073741824).toFixed(1)} GB` : b > 1048576 ? `${(b / 1048576).toFixed(1)} MB` : b > 1024 ? `${(b / 1024).toFixed(0)} KB` : `${b} B`;
  const fmtRate = (bps?: number) => {
    if (bps == null || !Number.isFinite(bps) || bps < 0) return '-';
    if (bps >= 1_000_000_000) return `${(bps / 1_000_000_000).toFixed(2)} Gbps`;
    if (bps >= 1_000_000) return `${(bps / 1_000_000).toFixed(2)} Mbps`;
    if (bps >= 1_000) return `${(bps / 1_000).toFixed(1)} Kbps`;
    return `${bps.toFixed(0)} bps`;
  };
  const fmtDuration = (secs?: number) => {
    if (secs == null || secs < 0) return '-';
    if (secs < 60) return `${secs}s`;
    if (secs < 3600) return `${Math.floor(secs / 60)}m`;
    if (secs < 86400) return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`;
    return `${Math.floor(secs / 86400)}d ${Math.floor((secs % 86400) / 3600)}h`;
  };

  // Helper: compute device-level stats — memoized per devices change
  const statsMap = useMemo(() => {
    const map = new Map<string, { intfs: NonNullable<Device['interface_data']>; upC: number; downC: number; errC: number; discC: number; maxBw: number; flapping: boolean; hasData: boolean }>();
    for (const d of devices) {
      const intfs = d.interface_data || [];
      const upC = intfs.filter(i => i.status === 'up').length;
      const downC = intfs.filter(i => i.status === 'down').length;
      const errC = intfs.reduce((a, i) => a + (i.in_errors || 0) + (i.out_errors || 0), 0);
      const discC = intfs.reduce((a, i) => a + (i.in_discards || 0) + (i.out_discards || 0), 0);
      const maxBw = intfs.reduce((m, i) => Math.max(m, i.bw_in_pct || 0, i.bw_out_pct || 0), 0);
      const flapping = intfs.some(i => i.flapping);
      map.set(d.id, { intfs, upC, downC, errC, discC, maxBw, flapping, hasData: intfs.length > 0 });
    }
    return map;
  }, [devices]);

  const devStats = useCallback((d: Device) => {
    return statsMap.get(d.id) || { intfs: [], upC: 0, downC: 0, errC: 0, discC: 0, maxBw: 0, flapping: false, hasData: false };
  }, [statsMap]);

  // Step 1: search filter (uses debounced input)
  const searchFiltered = useMemo(() => devices.filter(d => {
    if (!debouncedSearch.trim()) return true;
    const q = debouncedSearch.toLowerCase();
    return d.hostname.toLowerCase().includes(q) || d.ip_address.toLowerCase().includes(q);
  }), [devices, debouncedSearch]);

  // Step 2: status filter
  const statusFiltered = useMemo(() => searchFiltered.filter(d => {
    const s = devStats(d);
    if (intfStatusFilter === 'hasData') return s.hasData;
    if (intfStatusFilter === 'hasDown') return s.downC > 0;
    if (intfStatusFilter === 'hasErrors') return (s.errC + s.discC) > 0 || s.flapping;
    return true;
  }), [searchFiltered, intfStatusFilter, devStats]);
  const hiddenCount = searchFiltered.length - statusFiltered.length;

  // Step 3: sort
  const sortedDevices = useMemo(() => [...statusFiltered].sort((a, b) => {
    const sa = devStats(a), sb = devStats(b);
    if (intfSortBy === 'downCount') return sb.downC - sa.downC || a.hostname.localeCompare(b.hostname);
    if (intfSortBy === 'errors') return (sb.errC + sb.discC) - (sa.errC + sa.discC) || a.hostname.localeCompare(b.hostname);
    if (intfSortBy === 'bw') return sb.maxBw - sa.maxBw || a.hostname.localeCompare(b.hostname);
    return a.hostname.localeCompare(b.hostname);
  }), [statusFiltered, intfSortBy, devStats]);

  // Global stats & filter tab counts — single pass over searchFiltered
  const { totalUp, totalDown, totalErrors, totalDiscards, filterCounts } = useMemo(() => {
    let up = 0, down = 0, errs = 0, discs = 0;
    let hasDataC = 0, hasDownC = 0, hasErrorsC = 0;
    for (const d of searchFiltered) {
      const s = devStats(d);
      up += s.upC;
      down += s.downC;
      errs += s.errC;
      discs += s.discC;
      if (s.hasData) hasDataC++;
      if (s.downC > 0) hasDownC++;
      if ((s.errC + s.discC) > 0 || s.flapping) hasErrorsC++;
    }
    return {
      totalUp: up, totalDown: down, totalErrors: errs, totalDiscards: discs,
      filterCounts: { all: searchFiltered.length, hasData: hasDataC, hasDown: hasDownC, hasErrors: hasErrorsC },
    };
  }, [searchFiltered, devStats]);

  // Top-5 bandwidth interfaces
  const topNBw: { hostname: string; name: string; bwIn: number; bwOut: number; speedMbps: number; inBps: number; outBps: number }[] = [];
  searchFiltered.forEach(d => {
    (d.interface_data || []).forEach(intf => {
      const bwIn = intf.bw_in_pct || 0;
      const bwOut = intf.bw_out_pct || 0;
      if (bwIn > 0 || bwOut > 0) topNBw.push({ hostname: d.hostname, name: intf.name, bwIn, bwOut, speedMbps: intf.speed_mbps, inBps: intf.in_bps || 0, outBps: intf.out_bps || 0 });
    });
  });
  topNBw.sort((a, b) => Math.max(b.bwIn, b.bwOut) - Math.max(a.bwIn, a.bwOut));
  const top5Bw = topNBw.slice(0, 5);

  const totalDevPages = Math.max(1, Math.ceil(sortedDevices.length / DEVS_PER_PAGE));
  const safePage = Math.min(intfDevicePage, totalDevPages);
  const pagedDevices = sortedDevices.slice((safePage - 1) * DEVS_PER_PAGE, safePage * DEVS_PER_PAGE);

  const filterTabs: { key: typeof intfStatusFilter; label: string; count: number }[] = [
    { key: 'all', label: language === 'zh' ? '全部' : 'All', count: filterCounts.all },
    { key: 'hasData', label: language === 'zh' ? '有接口数据' : 'Has Data', count: filterCounts.hasData },
    { key: 'hasDown', label: language === 'zh' ? '有DOWN口' : 'Has DOWN', count: filterCounts.hasDown },
    { key: 'hasErrors', label: language === 'zh' ? '有错误/丢包' : 'Errors/Drops', count: filterCounts.hasErrors },
  ];

  return (
            <div className="flex flex-col h-full overflow-hidden">
              <PageHero
                icon={Activity}
                title={language === 'zh' ? '接口监控' : 'Interface Monitoring'}
                subtitle={language === 'zh' ? '所有设备的接口实时状态总览' : 'Real-time interface status overview for all devices'}
                actions={
                  <>
                    <div className="flex items-center gap-2 px-3 py-1.5 bg-white border border-black/5 rounded-xl">
                      <span className="w-2 h-2 rounded-full bg-[#00bceb]" />
                      <span className="text-xs text-black/60">
                        {intfUpdatedAgoSec === null
                          ? (language === 'zh' ? '同步中...' : 'Syncing...')
                          : (language === 'zh' ? `${intfUpdatedAgoSec}s 前更新` : `Updated ${intfUpdatedAgoSec}s ago`)}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 px-3 py-1.5 bg-white border border-black/5 rounded-xl">
                      <span className="w-2 h-2 rounded-full bg-emerald-500" />
                      <span className="text-xs text-black/60">UP: {totalUp}</span>
                    </div>
                    <div className="flex items-center gap-2 px-3 py-1.5 bg-white border border-black/5 rounded-xl">
                      <span className="w-2 h-2 rounded-full bg-red-500" />
                      <span className="text-xs text-black/60">DOWN: {totalDown}</span>
                    </div>
                    {totalErrors > 0 && (
                      <div className="flex items-center gap-2 px-3 py-1.5 bg-red-50 border border-red-100 rounded-xl">
                        <span className="text-xs text-red-600 font-medium">{language === 'zh' ? '错误' : 'Errors'}: {totalErrors.toLocaleString()}</span>
                      </div>
                    )}
                    {totalDiscards > 0 && (
                      <div className="flex items-center gap-2 px-3 py-1.5 bg-orange-50 border border-orange-100 rounded-xl">
                        <span className="text-xs text-orange-600 font-medium">{language === 'zh' ? '丢包' : 'Drops'}: {totalDiscards.toLocaleString()}</span>
                      </div>
                    )}
                  </>
                }
              />

              <div className="flex-1 overflow-auto px-6 py-5 space-y-6">

                {/* Top-5 Bandwidth Ranking */}
                {top5Bw.length > 0 && (
                  <div className="bg-white rounded-2xl border border-black/5 shadow-sm p-5">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-black/40 mb-3">{language === 'zh' ? 'Top 5 带宽利用率接口' : 'Top 5 Bandwidth Utilization'}</h3>
                    <div className="space-y-2.5">
                      {top5Bw.map((item, idx) => (
                        <div key={idx} className="flex items-center gap-3">
                          <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0 ${idx === 0 ? 'bg-red-100 text-red-600' : idx === 1 ? 'bg-orange-100 text-orange-600' : 'bg-black/5 text-black/40'}`}>{idx + 1}</span>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2">
                              <span className="text-xs font-semibold truncate">{item.hostname}</span>
                              <span className="text-[10px] font-mono text-black/40 truncate">{item.name}</span>
                              {item.speedMbps > 0 && <span className="text-[10px] text-black/25">{item.speedMbps >= 1000 ? `${item.speedMbps / 1000}G` : `${item.speedMbps}M`}</span>}
                            </div>
                            <div className="flex items-center gap-2 mt-1">
                              <div className="flex items-center gap-1 flex-1">
                                <span className="text-[9px] text-blue-500 w-5 flex-shrink-0">IN</span>
                                <progress className="util-progress util-progress-in flex-1" max={100} value={Math.min(item.bwIn, 100)} />
                                <span className="text-[10px] font-mono text-blue-600 w-12 text-right">{item.bwIn.toFixed(1)}%</span>
                              </div>
                              <div className="flex items-center gap-1 flex-1">
                                <span className="text-[9px] text-orange-500 w-7 flex-shrink-0">OUT</span>
                                <progress className="util-progress util-progress-out flex-1" max={100} value={Math.min(item.bwOut, 100)} />
                                <span className="text-[10px] font-mono text-orange-600 w-12 text-right">{item.bwOut.toFixed(1)}%</span>
                              </div>
                            </div>
                          </div>
                          <div className="text-right flex-shrink-0 ml-2">
                            <div className="text-[10px] font-mono text-blue-600">{fmtRate(item.inBps)}</div>
                            <div className="text-[10px] font-mono text-orange-600">{fmtRate(item.outBps)}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Search + Filter tabs + Sort */}
                <div className="flex flex-col gap-3">
                  <div className={sectionToolbarClass}>
                    <div className="relative flex-1">
                      <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-black/40" size={16} />
                      <input
                        ref={searchInputRef}
                        type="text"
                        placeholder={language === 'zh' ? '搜索主机名或 IP…  (Ctrl+K 聚焦)' : 'Search hostname or IP…  (Ctrl+K to focus)'}
                        value={intfSearch}
                        onChange={(e) => setIntfSearch(e.target.value)}
                        className="w-full pl-9 pr-8 py-2 bg-black/[0.02] border border-black/5 rounded-xl text-sm focus:border-black/20 outline-none transition-all"
                      />
                      {intfSearch && (
                        <button
                          onClick={() => { setIntfSearch(''); searchInputRef.current?.focus(); }}
                          className="absolute right-2.5 top-1/2 -translate-y-1/2 p-0.5 rounded text-black/25 hover:text-black/60 transition-colors"
                          title={language === 'zh' ? '清除搜索' : 'Clear search'}
                        >
                          <X size={14} />
                        </button>
                      )}
                    </div>
                    <select
                      value={intfSortBy}
                      onChange={(e) => { setIntfSortBy(e.target.value as any); setIntfDevicePage(1); }}
                      title={language === 'zh' ? '接口监控排序方式' : 'Interface monitoring sort order'}
                      className="px-3 py-2 bg-black/[0.02] border border-black/5 rounded-xl text-xs outline-none cursor-pointer"
                    >
                      <option value="name">{language === 'zh' ? '按主机名排序' : 'Sort by Name'}</option>
                      <option value="downCount">{language === 'zh' ? '按DOWN数↓' : 'Sort by DOWN'}</option>
                      <option value="errors">{language === 'zh' ? '按错误数↓' : 'Sort by Errors'}</option>
                      <option value="bw">{language === 'zh' ? '按带宽利用率↓' : 'Sort by BW%'}</option>
                    </select>
                    <span className="text-xs text-black/40">{sortedDevices.length} {language === 'zh' ? '台设备' : 'devices'}</span>
                  </div>
                  <div className="flex items-center gap-1.5 flex-wrap">
                    {filterTabs.map(tab => (
                      <button
                        key={tab.key}
                        onClick={() => { setIntfStatusFilter(tab.key); setIntfDevicePage(1); }}
                        className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${intfStatusFilter === tab.key ? 'bg-black text-white shadow-sm' : 'bg-black/[0.03] text-black/50 hover:bg-black/[0.06]'}`}
                      >
                        {tab.label} <span className={`ml-1 ${intfStatusFilter === tab.key ? 'text-white/60' : 'text-black/30'}`}>({tab.count})</span>
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              {/* Device list */}
              {sortedDevices.length === 0 ? (
                <div className="bg-white rounded-2xl border border-black/5 shadow-sm p-16 text-center">
                  <Server size={48} className="mx-auto text-black/10 mb-4" />
                  <p className="text-black/40 text-sm">{language === 'zh' ? '没有匹配的设备' : 'No matching devices'}</p>
                </div>
              ) : (
                <div className="bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden">
                  {pagedDevices.map((device) => {
                    const isExpanded = intfExpandedDevice === device.id;
                    const intfs = device.interface_data || [];
                    const ds = devStats(device);
                    // Inner interface filter & pagination
                    const innerFilter = intfFilterMap[device.id] || '';
                    const innerStatus = intfInnerStatusMap[device.id] || 'all';
                    const filteredIntfs = intfs.filter(i => {
                      // Text search: name, description, status
                      if (innerFilter.trim()) {
                        const q = innerFilter.toLowerCase();
                        const matchName = i.name.toLowerCase().includes(q);
                        const matchDesc = (i.description || '').toLowerCase().includes(q);
                        const matchStatus = i.status.toLowerCase().includes(q);
                        if (!matchName && !matchDesc && !matchStatus) return false;
                      }
                      // Status filter
                      if (innerStatus === 'up') return i.status === 'up';
                      if (innerStatus === 'down') return i.status === 'down';
                      if (innerStatus === 'error') return ((i.in_errors || 0) + (i.out_errors || 0) + (i.in_discards || 0) + (i.out_discards || 0)) > 0;
                      return true;
                    });
                    const innerDownCount = intfs.filter(i => i.status === 'down').length;
                    const innerErrorCount = intfs.filter(i => ((i.in_errors || 0) + (i.out_errors || 0) + (i.in_discards || 0) + (i.out_discards || 0)) > 0).length;
                    const innerPage = intfPageMap[device.id] || 1;
                    const innerTotalPages = Math.max(1, Math.ceil(filteredIntfs.length / INTFS_PER_PAGE));
                    const safeInnerPage = Math.min(innerPage, innerTotalPages);
                    const pagedIntfs = filteredIntfs.slice((safeInnerPage - 1) * INTFS_PER_PAGE, safeInnerPage * INTFS_PER_PAGE);
                    const innerRangeStart = filteredIntfs.length > 0 ? (safeInnerPage - 1) * INTFS_PER_PAGE + 1 : 0;
                    const innerRangeEnd = Math.min(safeInnerPage * INTFS_PER_PAGE, filteredIntfs.length);

                    return (
                      <div key={device.id} className="border-b border-black/5 last:border-b-0">
                        {/* Device row — clickable */}
                        <div
                          className="px-6 py-3.5 flex items-center justify-between cursor-pointer hover:bg-black/[0.01] transition-colors select-none"
                          onClick={() => setIntfExpandedDevice(isExpanded ? null : device.id)}
                        >
                          <div className="flex items-center gap-4 min-w-0">
                            <ChevronRight size={16} className={`text-black/30 transition-transform duration-200 flex-shrink-0 ${isExpanded ? 'rotate-90' : ''}`} />
                            <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${device.status === 'online' ? 'bg-emerald-50 text-emerald-600' : 'bg-black/5 text-black/30'}`}>
                              <Server size={16} />
                            </div>
                            <div className="min-w-0">
                              <span className="font-semibold text-sm">{device.hostname}</span>
                              <span className="text-xs text-black/40 ml-3">{device.ip_address}</span>
                              <span className="text-xs text-black/30 ml-2">{device.platform}</span>
                              {ds.flapping && <span className="ml-2 px-1.5 py-0.5 text-[9px] font-bold uppercase bg-red-100 text-red-600 rounded animate-pulse">FLAP</span>}
                            </div>
                          </div>
                          <div className="flex items-center gap-4">
                            <span className={`w-2 h-2 rounded-full flex-shrink-0 ${device.status === 'online' ? 'bg-emerald-500' : 'bg-black/20'}`} />
                            {intfs.length > 0 ? (
                              <div className="flex items-center gap-3 text-xs">
                                <span className="text-emerald-600 font-medium">{ds.upC} up</span>
                                <span className={`font-medium ${ds.downC > 0 ? 'text-red-500' : 'text-black/30'}`}>{ds.downC} down</span>
                                {ds.errC > 0 && <span className="text-red-500 font-medium">{ds.errC.toLocaleString()} err</span>}
                                <span className="text-black/30">{intfs.length} total</span>
                              </div>
                            ) : (
                              <span className="text-[10px] text-black/30 italic">{language === 'zh' ? '未采集到接口数据' : 'No interface data'}</span>
                            )}
                            <button
                              onClick={(e) => { e.stopPropagation(); void onSnmpTest(device.id); }}
                              disabled={snmpTestingId === device.id}
                              className="ml-2 px-3 py-1 text-[10px] font-bold uppercase bg-blue-50 text-blue-600 rounded-lg hover:bg-blue-100 transition-all disabled:opacity-50 flex-shrink-0"
                            >
                              {snmpTestingId === device.id ? 'Testing...' : 'SNMP Test'}
                            </button>
                            <button
                              onClick={(e) => { e.stopPropagation(); void onSnmpSyncNow(device.id); }}
                              disabled={snmpSyncingId === device.id}
                              className="px-3 py-1 text-[10px] font-bold uppercase bg-emerald-50 text-emerald-600 rounded-lg hover:bg-emerald-100 transition-all disabled:opacity-50 flex-shrink-0"
                            >
                              {snmpSyncingId === device.id
                                ? (language === 'zh' ? '同步中...' : 'Syncing...')
                                : (language === 'zh' ? '立即同步SNMP' : 'SNMP Sync Now')}
                            </button>
                          </div>
                        </div>

                        {/* Expanded interface table */}
                        {isExpanded && (
                          <div className="bg-black/[0.01] border-t border-black/5 px-6 pb-4 pt-3">
                            {intfs.length === 0 ? (
                              <p className="text-sm text-black/30 py-4 text-center">{language === 'zh' ? '暂无接口数据，请确认设备已开启 SNMP，并可点击"立即同步SNMP"主动拉取。' : 'No interface data. Verify SNMP is enabled, then click "SNMP Sync Now" to fetch immediately.'}</p>
                            ) : (
                              <>
                                {/* Interface search + status filter */}
                                <div className="flex items-center gap-3 mb-3 flex-wrap">
                                  <div className="relative flex-1 max-w-xs min-w-[160px]">
                                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-black/30" size={14} />
                                    <input
                                      type="text"
                                      placeholder={language === 'zh' ? '搜索接口名/描述…' : 'Filter name/desc…'}
                                      value={innerFilter}
                                      onChange={(e) => {
                                        setIntfFilterMap(prev => ({ ...prev, [device.id]: e.target.value }));
                                        setIntfPageMap(prev => ({ ...prev, [device.id]: 1 }));
                                      }}
                                      className="w-full pl-8 pr-7 py-1.5 bg-white border border-black/10 rounded-lg text-xs outline-none focus:border-black/20"
                                    />
                                    {innerFilter && (
                                      <button
                                        onClick={() => {
                                          setIntfFilterMap(prev => ({ ...prev, [device.id]: '' }));
                                          setIntfPageMap(prev => ({ ...prev, [device.id]: 1 }));
                                        }}
                                        className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 rounded text-black/25 hover:text-black/60 transition-colors"
                                      >
                                        <X size={12} />
                                      </button>
                                    )}
                                  </div>
                                  <div className="flex items-center gap-1">
                                    {(['all', 'down', 'error'] as const).map(st => {
                                      const label = st === 'all'
                                        ? (language === 'zh' ? `全部 (${intfs.length})` : `All (${intfs.length})`)
                                        : st === 'down'
                                        ? (language === 'zh' ? `DOWN (${innerDownCount})` : `DOWN (${innerDownCount})`)
                                        : (language === 'zh' ? `异常 (${innerErrorCount})` : `Error (${innerErrorCount})`);
                                      return (
                                        <button
                                          key={st}
                                          onClick={() => {
                                            setIntfInnerStatusMap(prev => ({ ...prev, [device.id]: st }));
                                            setIntfPageMap(prev => ({ ...prev, [device.id]: 1 }));
                                          }}
                                          className={`px-2 py-1 rounded text-[10px] font-medium transition-all ${
                                            innerStatus === st
                                              ? st === 'down' ? 'bg-red-100 text-red-700' : st === 'error' ? 'bg-orange-100 text-orange-700' : 'bg-black/10 text-black/70'
                                              : 'text-black/40 hover:bg-black/5'
                                          }`}
                                        >
                                          {label}
                                        </button>
                                      );
                                    })}
                                  </div>
                                  <span className="text-[10px] text-black/30 ml-auto">
                                    {filteredIntfs.length === intfs.length
                                      ? `${intfs.length} ${language === 'zh' ? '个接口' : 'interfaces'}`
                                      : `${filteredIntfs.length} / ${intfs.length} ${language === 'zh' ? '匹配' : 'matched'}`}
                                  </span>
                                </div>
                                {/* Table */}
                                <div className="border border-black/5 rounded-xl overflow-hidden">
                                  <table className="w-full text-xs">
                                    <thead className="bg-black/[0.02]">
                                      <tr>
                                        <th className="px-4 py-2.5 text-left font-bold text-[10px] uppercase tracking-wider text-black/40">{language === 'zh' ? '接口' : 'Interface'}</th>
                                        <th className="px-4 py-2.5 text-left font-bold text-[10px] uppercase tracking-wider text-black/40">{language === 'zh' ? '状态' : 'Status'}</th>
                                        <th className="px-4 py-2.5 text-right font-bold text-[10px] uppercase tracking-wider text-black/40">{language === 'zh' ? '速率' : 'Speed'}</th>
                                        <th className="px-4 py-2.5 text-right font-bold text-[10px] uppercase tracking-wider text-black/40">{language === 'zh' ? '入速率' : 'IN Rate'}</th>
                                        <th className="px-4 py-2.5 text-right font-bold text-[10px] uppercase tracking-wider text-black/40">{language === 'zh' ? '出速率' : 'OUT Rate'}</th>
                                        <th className="px-4 py-2.5 text-right font-bold text-[10px] uppercase tracking-wider text-black/40">BW% IN/OUT</th>
                                        <th className="px-4 py-2.5 text-right font-bold text-[10px] uppercase tracking-wider text-black/40">{language === 'zh' ? '错误' : 'Errors'}</th>
                                        <th className="px-4 py-2.5 text-right font-bold text-[10px] uppercase tracking-wider text-black/40">{language === 'zh' ? '丢包' : 'Drops'}</th>
                                        <th className="px-4 py-2.5 text-center font-bold text-[10px] uppercase tracking-wider text-black/40">{language === 'zh' ? '持续时间' : 'Since'}</th>
                                        <th className="px-4 py-2.5 text-left font-bold text-[10px] uppercase tracking-wider text-black/40">{language === 'zh' ? '描述' : 'Description'}</th>
                                      </tr>
                                    </thead>
                                    <tbody className="divide-y divide-black/5">
                                      {pagedIntfs.length === 0 && (
                                        <tr><td colSpan={10} className="px-4 py-8 text-center text-xs text-black/30">
                                          <Filter size={20} className="mx-auto mb-2 text-black/15" />
                                          {language === 'zh' ? '当前筛选条件下没有匹配的接口' : 'No interfaces match the current filter'}
                                        </td></tr>
                                      )}
                                      {pagedIntfs.map((intf, i) => {
                                        const intfErrors = (intf.in_errors || 0) + (intf.out_errors || 0);
                                        const intfDiscards = (intf.in_discards || 0) + (intf.out_discards || 0);
                                        const bwIn = intf.bw_in_pct ?? null;
                                        const bwOut = intf.bw_out_pct ?? null;
                                        return (
                                        <tr key={i} className="hover:bg-white/80 transition-colors">
                                          <td className="px-4 py-2 font-mono text-[11px] font-medium">{intf.name}</td>
                                          <td className="px-4 py-2">
                                            <span className={`inline-flex items-center gap-1.5 text-[10px] font-bold uppercase ${intf.status === 'up' ? 'text-emerald-600' : 'text-red-500'}`}>
                                              <span className={`w-1.5 h-1.5 rounded-full ${intf.status === 'up' ? 'bg-emerald-500' : 'bg-red-500'}`} />
                                              {intf.status}
                                            </span>
                                            {intf.flapping && <span className="ml-1 px-1 py-0.5 text-[8px] font-bold uppercase bg-red-100 text-red-600 rounded animate-pulse">FLAP</span>}
                                          </td>
                                          <td className="px-4 py-2 text-right text-black/60">{intf.speed_mbps > 0 ? (intf.speed_mbps >= 1000 ? `${intf.speed_mbps / 1000}G` : `${intf.speed_mbps}M`) : '-'}</td>
                                          <td className="px-4 py-2 text-right font-mono text-[10px]">
                                            <div className="text-blue-600">{fmtRate(intf.in_bps)}</div>
                                            <div className="text-black/30">{fmtBytes(intf.in_octets || 0)}</div>
                                          </td>
                                          <td className="px-4 py-2 text-right font-mono text-[10px]">
                                            <div className="text-orange-600">{fmtRate(intf.out_bps)}</div>
                                            <div className="text-black/30">{fmtBytes(intf.out_octets || 0)}</div>
                                          </td>
                                          <td className="px-4 py-2 text-right">
                                            {bwIn != null || bwOut != null ? (
                                              <div className="space-y-0.5">
                                                <div className="flex items-center justify-end gap-1">
                                                  <span className="text-[8px] text-blue-500 w-5 text-right">IN</span>
                                                  <progress className="util-progress util-progress-in w-10" max={100} value={Math.min(bwIn || 0, 100)} />
                                                  <span className={`font-mono text-[9px] w-10 text-right ${(bwIn || 0) > 80 ? 'text-red-600' : 'text-blue-600'}`}>{(bwIn || 0).toFixed(1)}%</span>
                                                </div>
                                                <div className="flex items-center justify-end gap-1">
                                                  <span className="text-[8px] text-orange-500 w-5 text-right">OUT</span>
                                                  <progress className="util-progress util-progress-out w-10" max={100} value={Math.min(bwOut || 0, 100)} />
                                                  <span className={`font-mono text-[9px] w-10 text-right ${(bwOut || 0) > 80 ? 'text-red-600' : 'text-orange-600'}`}>{(bwOut || 0).toFixed(1)}%</span>
                                                </div>
                                              </div>
                                            ) : <span className="text-[10px] text-black/20">-</span>}
                                          </td>
                                          <td className="px-4 py-2 text-right">
                                            <span className={`font-mono text-[10px] ${intfErrors > 0 ? 'text-red-600 font-bold' : 'text-black/30'}`}>{intfErrors > 0 ? intfErrors.toLocaleString() : '0'}</span>
                                          </td>
                                          <td className="px-4 py-2 text-right">
                                            <span className={`font-mono text-[10px] ${intfDiscards > 0 ? 'text-orange-600 font-bold' : 'text-black/30'}`}>{intfDiscards > 0 ? intfDiscards.toLocaleString() : '0'}</span>
                                          </td>
                                          <td className="px-4 py-2 text-center">
                                            <span className="font-mono text-[10px] text-black/40">{fmtDuration(intf.last_change_secs)}</span>
                                          </td>
                                          <td className="px-4 py-2 text-black/40 truncate max-w-[150px]" title={intf.description || ''}>{intf.description || '-'}</td>
                                        </tr>
                                        );
                                      })}
                                    </tbody>
                                  </table>
                                </div>
                                {/* Interface pagination */}
                                {innerTotalPages > 1 && (
                                  <div className="flex items-center justify-between mt-3 px-1">
                                    <span className="text-[10px] text-black/30">
                                      {language === 'zh'
                                        ? `显示 ${innerRangeStart}-${innerRangeEnd}，共 ${filteredIntfs.length} 个接口`
                                        : `${innerRangeStart}-${innerRangeEnd} of ${filteredIntfs.length} interfaces`}
                                    </span>
                                    <div className="flex items-center gap-1">
                                      {/* First page */}
                                      <button
                                        disabled={safeInnerPage <= 1}
                                        onClick={() => setIntfPageMap(prev => ({ ...prev, [device.id]: 1 }))}
                                        title={language === 'zh' ? '第一页' : 'First page'}
                                        className="px-1.5 py-1 text-[10px] border border-black/10 rounded-md hover:bg-black/5 disabled:opacity-30 transition-all"
                                      >
                                        <ChevronsLeft size={12} />
                                      </button>
                                      {/* Previous page */}
                                      <button
                                        disabled={safeInnerPage <= 1}
                                        onClick={() => setIntfPageMap(prev => ({ ...prev, [device.id]: safeInnerPage - 1 }))}
                                        title={language === 'zh' ? '上一页' : 'Previous page'}
                                        className="px-1.5 py-1 text-[10px] border border-black/10 rounded-md hover:bg-black/5 disabled:opacity-30 transition-all"
                                      >
                                        <ChevronLeft size={12} />
                                      </button>
                                      {/* Page number input */}
                                      <span className="text-[10px] text-black/40 px-1">
                                        <input
                                          type="number"
                                          min={1}
                                          max={innerTotalPages}
                                          value={safeInnerPage}
                                          onChange={(e) => {
                                            const v = parseInt(e.target.value, 10);
                                            if (v >= 1 && v <= innerTotalPages) {
                                              setIntfPageMap(prev => ({ ...prev, [device.id]: v }));
                                            }
                                          }}
                                          className="w-8 text-center text-[10px] border border-black/10 rounded py-0.5 outline-none focus:border-black/20"
                                        />
                                        <span className="mx-0.5">/</span>{innerTotalPages}
                                      </span>
                                      {/* Next page */}
                                      <button
                                        disabled={safeInnerPage >= innerTotalPages}
                                        onClick={() => setIntfPageMap(prev => ({ ...prev, [device.id]: safeInnerPage + 1 }))}
                                        title={language === 'zh' ? '下一页' : 'Next page'}
                                        className="px-1.5 py-1 text-[10px] border border-black/10 rounded-md hover:bg-black/5 disabled:opacity-30 transition-all"
                                      >
                                        <ChevronRight size={12} />
                                      </button>
                                      {/* Last page */}
                                      <button
                                        disabled={safeInnerPage >= innerTotalPages}
                                        onClick={() => setIntfPageMap(prev => ({ ...prev, [device.id]: innerTotalPages }))}
                                        title={language === 'zh' ? '最后一页' : 'Last page'}
                                        className="px-1.5 py-1 text-[10px] border border-black/10 rounded-md hover:bg-black/5 disabled:opacity-30 transition-all"
                                      >
                                        <ChevronsRight size={12} />
                                      </button>
                                    </div>
                                  </div>
                                )}
                              </>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}

                  {/* Device pagination */}
                  {totalDevPages > 1 && (
                    <div className="px-6 py-3 border-t border-black/5 flex items-center justify-between">
                      <span className="text-xs text-black/40">{language === 'zh' ? `共 ${sortedDevices.length} 台设备，第 ${safePage}/${totalDevPages} 页` : `${sortedDevices.length} devices, page ${safePage} of ${totalDevPages}`}</span>
                      <div className="flex gap-1">
                        <button
                          disabled={safePage <= 1}
                          onClick={() => setIntfDevicePage(safePage - 1)}
                          title={language === 'zh' ? '上一页' : 'Previous page'}
                          className="p-1.5 rounded-lg border border-black/5 hover:bg-black/5 disabled:opacity-30 transition-all"
                        >
                          <ChevronLeft size={16} />
                        </button>
                        <button
                          disabled={safePage >= totalDevPages}
                          onClick={() => setIntfDevicePage(safePage + 1)}
                          title={language === 'zh' ? '下一页' : 'Next page'}
                          className="p-1.5 rounded-lg border border-black/5 hover:bg-black/5 disabled:opacity-30 transition-all"
                        >
                          <ChevronRight size={16} />
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Hidden (no-data) devices summary */}
              {intfStatusFilter !== 'all' && hiddenCount > 0 && (
                  <div className="text-center py-3">
                    <span className="text-xs text-black/30">
                      {language === 'zh'
                        ? `${hiddenCount} 台设备被当前筛选条件隐藏`
                        : `${hiddenCount} devices hidden by current filter`}
                    </span>
                    <button onClick={() => { setIntfStatusFilter('all'); setIntfDevicePage(1); }} className="ml-2 text-xs text-blue-500 hover:underline">
                      {language === 'zh' ? '显示全部' : 'Show all'}
                    </button>
                  </div>
              )}
              </div>
            </div>
  );
}

export default InterfaceMonitoringTab;
