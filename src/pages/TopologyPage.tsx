import React from 'react';
import { motion } from 'motion/react';
import { Download, Globe, RotateCcw, Search, Network, EyeOff } from 'lucide-react';
import type { Device } from '../types';
import { darkActionBtnClass, secondaryActionBtnClass } from '../components/shared';
import TopologyGraph from '../components/TopologyGraph';
import TopologyInspectorPanel from '../components/TopologyInspectorPanel';
import PageHero from '../components/PageHero';

type TopologyStatusFilter = 'all' | 'online' | 'offline' | 'pending';
type TopologyLinkStatusFilter = 'all' | 'up' | 'degraded' | 'down' | 'stale' | 'unknown';
type TopologyProtocolFilter = 'all' | 'lldp' | 'cdp';

interface TopologyStats {
  nodeCount: number;
  linkCount: number;
  siteCount: number;
  atRiskCount: number;
  orphanCount: number;
}

interface TopologyLinkStats {
  up: number;
  degraded: number;
  down: number;
  stale: number;
  multiSource: number;
}

interface TopologyOperationalTone {
  badge: string;
  panel: string;
}

interface TopologyDecoratedLinkLike {
  id?: string;
  link_key?: string;
  source_device_id: string;
  target_device_id: string;
  source_port?: string;
  target_port?: string;
  source_hostname?: string;
  source_hostname_resolved?: string;
  target_hostname?: string;
  target_hostname_resolved?: string;
  source_interface_snapshot?: unknown;
  target_interface_snapshot?: unknown;
  inferred?: boolean;
  operational_state?: 'up' | 'degraded' | 'down' | 'stale' | 'unknown';
  operational_summary?: string;
  last_seen?: string;
  evidence_sources: string[];
  evidence_count?: number;
  reverse_confirmed?: boolean;
}

interface TopologyPageProps {
  language: string;
  topologyDiscoveryRunning: boolean;
  topologyDiscoveryProgress: {
    id: string;
    status: string;
    total_devices: number;
    processed_devices: number;
    success_devices: number;
    failed_devices: number;
    progress_percent: number;
  } | null;
  topologyDiscoveryDevices: any[];
  topologySites: any[];
  topologyDataError: string;
  topologyStats: TopologyStats;
  topologyLinkStats: TopologyLinkStats;
  topologySearch: string;
  topologySiteFilter: string;
  topologyRoleFilter: string;
  topologyStatusFilter: TopologyStatusFilter;
  topologyLinkStatusFilter: TopologyLinkStatusFilter;
  topologyProtocolFilter: TopologyProtocolFilter;
  topologySiteOptions: Array<{ id: string; name: string }>;
  topologyRoleOptions: string[];
  topologyVisibleDevices: Device[];
  topologyVisibleLinks: TopologyDecoratedLinkLike[];
  selectedTopologyDeviceId: string | null;
  selectedTopologyLinkKey: string | null;
  selectedTopologyDevice: Device | null;
  selectedTopologyLink: TopologyDecoratedLinkLike | null;
  topologyNeighborDevices: Device[];
  topologyDeviceLinks: TopologyDecoratedLinkLike[];
  topologyPriorityDevices: Device[];
  topologyOrphanDevices: Device[];
  topologyCanvasRef: React.RefObject<HTMLDivElement | null>;
  onTriggerDiscovery: () => void;
  onCancelDiscovery: () => void;
  onExportMap: () => void;
  onTopologySearchChange: (value: string) => void;
  onTopologySiteFilterChange: (value: string) => void;
  onTopologyRoleFilterChange: (value: string) => void;
  onTopologyStatusFilterChange: (value: TopologyStatusFilter) => void;
  onTopologyLinkStatusFilterChange: (value: TopologyLinkStatusFilter) => void;
  onTopologyProtocolFilterChange: (value: TopologyProtocolFilter) => void;
  onSelectTopologyDevice: (deviceId: string) => void;
  onSelectTopologyLink: (linkKey: string | null) => void;
  onOpenDeviceDetail: (device: Device) => void;
  onOpenMonitoring: () => void;
  hideStaleLinks: boolean;
  onHideStaleLinksChange: (value: boolean) => void;
  hideOrphanDevices: boolean;
  onHideOrphanDevicesChange: (value: boolean) => void;
  formatTopologyPort: (value?: string) => string;
  formatTopologyInterfaceTelemetry: (snapshot: unknown) => string;
  formatTopologyLastSeen: (value?: string) => string;
  formatTopologyOperationalState: (value?: string) => string;
  formatTopologyEvidenceLabel: (value?: string) => string;
  getTopologyOperationalTone: (value?: string) => TopologyOperationalTone;
}

const TopologyPage: React.FC<TopologyPageProps> = ({
  language,
  topologyDiscoveryRunning,
  topologyDiscoveryProgress,
  topologyDiscoveryDevices,
  topologySites,
  topologyDataError,
  topologyStats,
  topologyLinkStats,
  topologySearch,
  topologySiteFilter,
  topologyRoleFilter,
  topologyStatusFilter,
  topologyLinkStatusFilter,
  topologyProtocolFilter,
  topologySiteOptions,
  topologyRoleOptions,
  topologyVisibleDevices,
  topologyVisibleLinks,
  selectedTopologyDeviceId,
  selectedTopologyLinkKey,
  selectedTopologyDevice,
  selectedTopologyLink,
  topologyNeighborDevices,
  topologyDeviceLinks,
  topologyPriorityDevices,
  topologyOrphanDevices,
  topologyCanvasRef,
  onTriggerDiscovery,
  onCancelDiscovery,
  onExportMap,
  onTopologySearchChange,
  onTopologySiteFilterChange,
  onTopologyRoleFilterChange,
  onTopologyStatusFilterChange,
  onTopologyLinkStatusFilterChange,
  onTopologyProtocolFilterChange,
  onSelectTopologyDevice,
  onSelectTopologyLink,
  onOpenDeviceDetail,
  onOpenMonitoring,
  hideStaleLinks,
  onHideStaleLinksChange,
  hideOrphanDevices,
  onHideOrphanDevicesChange,
  formatTopologyPort,
  formatTopologyInterfaceTelemetry,
  formatTopologyLastSeen,
  formatTopologyOperationalState,
  formatTopologyEvidenceLabel,
  getTopologyOperationalTone,
}) => {
  return (
    <div className="topology-page-shell h-full flex flex-col overflow-hidden">
      <PageHero
        icon={Network}
        title={language === 'zh' ? '网络拓扑' : 'Network Topology'}
        subtitle={language === 'zh'
          ? '基于 LLDP 邻居发现展示网络连接关系，按站点、角色和状态快速缩小故障域。'
          : 'Visualize LLDP-based network adjacency and reduce the fault domain by site, role, and health state.'}
        actions={
          <>
            <button onClick={onTriggerDiscovery} className={secondaryActionBtnClass} disabled={topologyDiscoveryRunning}>
              <RotateCcw size={16} />
              {topologyDiscoveryRunning
                ? (language === 'zh' ? '发现中...' : 'Discovering...')
                : (language === 'zh' ? '刷新发现' : 'Refresh Discovery')}
            </button>
            {topologyDiscoveryRunning && (
              <button onClick={onCancelDiscovery} className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-1.5 text-xs font-bold text-rose-700 transition hover:bg-rose-100">
                {language === 'zh' ? '取消任务' : 'Cancel Run'}
              </button>
            )}
            <button onClick={onExportMap} className={darkActionBtnClass}>
              <Download size={16} />
              {language === 'zh' ? '导出拓扑图' : 'Export Map'}
            </button>
          </>
        }
      />

      <div className="ops-page-scroll flex-1 overflow-auto px-6 py-5 space-y-5">

      {topologyDataError && (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800">
          {language === 'zh' ? '拓扑数据刷新异常：' : 'Topology data refresh warning: '}{topologyDataError}
        </div>
      )}

      {topologySites.length > 0 && (
        <div className="ops-surface rounded-2xl p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-bold text-slate-800">{language === 'zh' ? '站点视图' : 'Site View'}</h3>
              <p className="mt-0.5 text-[11px] text-slate-500">{language === 'zh' ? '先按站点缩小故障域，再进入站点拓扑。' : 'Start with a site fault domain, then inspect its topology.'}</p>
            </div>
            <button onClick={() => onTopologySiteFilterChange('all')} className="text-xs font-semibold text-sky-600 hover:text-sky-800">
              {language === 'zh' ? '查看全部' : 'All Sites'}
            </button>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {topologySites.map((site: any) => {
              const active = topologySiteFilter === site.site_id;
              const healthy = site.device_count > 0 && site.offline_devices === 0 && site.stale_links === 0;
              return (
                <button
                  key={site.site_id || site.site_code}
                  onClick={() => onTopologySiteFilterChange(site.site_id || 'all')}
                  className={`rounded-xl border p-3 text-left transition ${active ? 'border-sky-400 bg-sky-50' : 'border-slate-200 bg-slate-50/60 hover:border-sky-300'}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-bold text-slate-800">{site.site_name}</span>
                    <span className={`h-2 w-2 rounded-full ${healthy ? 'bg-emerald-500' : 'bg-amber-500'}`} />
                  </div>
                  <div className="mt-2 grid grid-cols-3 gap-2 text-[10px] text-slate-500">
                    <span><b className="block text-sm text-slate-800">{site.device_count}</b>{language === 'zh' ? '设备' : 'Devices'}</span>
                    <span><b className="block text-sm text-slate-800">{site.link_count}</b>{language === 'zh' ? '链路' : 'Links'}</span>
                    <span><b className="block text-sm text-rose-600">{site.orphan_devices}</b>{language === 'zh' ? '孤立' : 'Orphans'}</span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {topologyDiscoveryProgress && (
        <div className="ops-surface rounded-2xl border-l-4 border-l-sky-500 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-bold text-sky-900">{language === 'zh' ? '拓扑发现任务' : 'Topology Discovery Run'}</h3>
              <p className="mt-0.5 text-[11px] text-sky-700">{topologyDiscoveryProgress.status} · {topologyDiscoveryProgress.processed_devices}/{topologyDiscoveryProgress.total_devices}</p>
            </div>
            <span className="text-lg font-extrabold tabular-nums text-sky-800">{topologyDiscoveryProgress.progress_percent}%</span>
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-sky-100">
            <div className="h-full rounded-full bg-sky-500 transition-all" style={{ width: `${Math.min(100, Math.max(0, topologyDiscoveryProgress.progress_percent))}%` }} />
          </div>
          {topologyDiscoveryDevices.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {topologyDiscoveryDevices.slice(0, 8).map((item: any) => (
                <span key={item.device_id} className={`rounded-full px-2 py-1 text-[10px] font-semibold ${item.status === 'success' ? 'bg-emerald-100 text-emerald-700' : item.status === 'failed' ? 'bg-rose-100 text-rose-700' : 'bg-white text-sky-700'}`}>
                  {item.hostname || item.device_id}: {item.status}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="ops-toolbar rounded-2xl p-4">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          {[
            { label: language === 'zh' ? '节点' : 'Nodes', value: topologyStats.nodeCount, color: 'text-[#007ea0]' },
            { label: language === 'zh' ? '链路' : 'Links', value: topologyStats.linkCount, color: 'text-slate-700' },
            { label: language === 'zh' ? '站点' : 'Sites', value: topologyStats.siteCount, color: 'text-emerald-600' },
            { label: language === 'zh' ? '风险' : 'Risk', value: topologyStats.atRiskCount, color: topologyStats.atRiskCount > 0 ? 'text-amber-600' : 'text-slate-400' },
            { label: language === 'zh' ? '孤立' : 'Orphans', value: topologyStats.orphanCount, color: topologyStats.orphanCount > 0 ? 'text-rose-600' : 'text-slate-400' },
          ].map((item) => (
            <div key={item.label} className="flex items-baseline gap-1.5">
              <span className={`text-xl font-bold tabular-nums tracking-tight ${item.color}`}>{item.value}</span>
              <span className="text-[11px] font-medium text-black/35">{item.label}</span>
            </div>
          ))}
          <span className="hidden sm:inline text-black/10">|</span>
          {[
            { label: language === 'zh' ? '健康' : 'Up', value: topologyLinkStats.up, dot: 'bg-emerald-400' },
            { label: language === 'zh' ? '退化' : 'Degraded', value: topologyLinkStats.degraded, dot: 'bg-amber-400' },
            { label: language === 'zh' ? '中断' : 'Down', value: topologyLinkStats.down, dot: 'bg-rose-400' },
            { label: language === 'zh' ? '陈旧' : 'Stale', value: topologyLinkStats.stale, dot: 'bg-slate-300' },
            { label: language === 'zh' ? '多源' : 'Multi', value: topologyLinkStats.multiSource, dot: 'bg-sky-400' },
          ].map((item) => (
            <div key={item.label} className="flex items-center gap-1.5">
              <span className={`h-2 w-2 rounded-full ${item.dot}`} />
              <span className="text-sm font-semibold tabular-nums text-slate-700">{item.value}</span>
              <span className="text-[11px] text-black/30">{item.label}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="ops-toolbar rounded-2xl p-4">
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1.4fr)_repeat(5,minmax(0,0.8fr))]">
          <label className="ops-control flex items-center gap-2 rounded-xl px-3 py-2">
            <Search size={15} className="text-black/35" />
            <input
              value={topologySearch}
              onChange={(event) => onTopologySearchChange(event.target.value)}
              placeholder={language === 'zh' ? '搜索主机名、IP、站点、角色' : 'Search hostname, IP, site, role'}
              className="w-full bg-transparent text-sm outline-none placeholder:text-black/30"
            />
          </label>
          <select
            value={topologySiteFilter}
            onChange={(event) => onTopologySiteFilterChange(event.target.value)}
            title={language === 'zh' ? '按站点筛选拓扑' : 'Filter topology by site'}
            className="ops-control rounded-xl px-3 py-2 text-sm outline-none"
          >
            <option value="all">{language === 'zh' ? '全部站点' : 'All Sites'}</option>
            {topologySiteOptions.map((site) => <option key={site.id} value={site.id}>{site.name}</option>)}
          </select>
          <select
            value={topologyRoleFilter}
            onChange={(event) => onTopologyRoleFilterChange(event.target.value)}
            title={language === 'zh' ? '按角色筛选拓扑' : 'Filter topology by role'}
            className="ops-control rounded-xl px-3 py-2 text-sm outline-none"
          >
            <option value="all">{language === 'zh' ? '全部角色' : 'All Roles'}</option>
            {topologyRoleOptions.map((role) => <option key={role} value={role}>{role}</option>)}
          </select>
          <select
            value={topologyStatusFilter}
            onChange={(event) => onTopologyStatusFilterChange(event.target.value as TopologyStatusFilter)}
            title={language === 'zh' ? '按状态筛选拓扑' : 'Filter topology by status'}
            className="ops-control rounded-xl px-3 py-2 text-sm outline-none"
          >
            <option value="all">{language === 'zh' ? '全部状态' : 'All Status'}</option>
            <option value="online">{language === 'zh' ? '在线' : 'Online'}</option>
            <option value="offline">{language === 'zh' ? '离线' : 'Offline'}</option>
            <option value="pending">{language === 'zh' ? '待确认' : 'Pending'}</option>
          </select>
          <select
            value={topologyLinkStatusFilter}
            onChange={(event) => onTopologyLinkStatusFilterChange(event.target.value as TopologyLinkStatusFilter)}
            title={language === 'zh' ? '按链路状态筛选拓扑' : 'Filter topology by link state'}
            className="ops-control rounded-xl px-3 py-2 text-sm outline-none"
          >
            <option value="all">{language === 'zh' ? '全部链路状态' : 'All Link States'}</option>
            <option value="up">{language === 'zh' ? '链路正常' : 'Link Up'}</option>
            <option value="degraded">{language === 'zh' ? '链路退化' : 'Link Degraded'}</option>
            <option value="down">{language === 'zh' ? '链路中断' : 'Link Down'}</option>
            <option value="stale">{language === 'zh' ? '链路陈旧' : 'Link Stale'}</option>
            <option value="unknown">{language === 'zh' ? '链路未知' : 'Link Unknown'}</option>
          </select>
          <select
            value={topologyProtocolFilter}
            onChange={(event) => onTopologyProtocolFilterChange(event.target.value as TopologyProtocolFilter)}
            title={language === 'zh' ? '按邻居协议筛选拓扑' : 'Filter topology by neighbor protocol'}
            className="ops-control rounded-xl px-3 py-2 text-sm outline-none"
          >
            <option value="all">{language === 'zh' ? '全部协议' : 'All Protocols'}</option>
            <option value="lldp">LLDP</option>
            <option value="cdp">CDP</option>
          </select>
        </div>
        <div className="flex items-center gap-3 mt-2">
          <label className="flex items-center gap-2 cursor-pointer select-none rounded-lg border border-black/10 px-3 py-1.5 transition-colors hover:bg-slate-50" title={language === 'zh' ? '隐藏陈旧链路（最近30分钟未刷新的链路将被隐藏）' : 'Hide stale links (links not refreshed in the last 30 minutes)'}>
            <input
              type="checkbox"
              checked={hideStaleLinks}
              onChange={(e) => onHideStaleLinksChange(e.target.checked)}
              className="h-3.5 w-3.5 rounded accent-sky-600"
            />
            <EyeOff size={13} className="text-black/35" />
            <span className="text-xs font-medium text-black/55">{language === 'zh' ? '隐藏陈旧链路' : 'Hide Stale Links'}</span>
          </label>
          <label className="flex items-center gap-2 cursor-pointer select-none rounded-lg border border-black/10 px-3 py-1.5 transition-colors hover:bg-slate-50" title={language === 'zh' ? '隐藏孤立设备（没有任何链路连接的设备将被隐藏）' : 'Hide orphan devices (devices with no link connections)'}>
            <input
              type="checkbox"
              checked={hideOrphanDevices}
              onChange={(e) => onHideOrphanDevicesChange(e.target.checked)}
              className="h-3.5 w-3.5 rounded accent-sky-600"
            />
            <EyeOff size={13} className="text-black/35" />
            <span className="text-xs font-medium text-black/55">{language === 'zh' ? '隐藏孤立设备' : 'Hide Orphan Devices'}</span>
          </label>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 gap-4 xl:grid-cols-[minmax(0,2.35fr)_minmax(320px,0.85fr)]">
        <div className="ops-surface relative flex min-h-[620px] flex-col overflow-hidden rounded-2xl" ref={topologyCanvasRef}>
          <div className="absolute inset-0 bg-[radial-gradient(#000_1px,transparent_1px)] bg-[length:20px_20px] opacity-[0.03]" />
          <div className="relative flex items-center justify-between border-b border-black/5 px-5 py-4">
            <div>
              <h3 className="text-lg font-semibold tracking-tight text-[#0f172a]">
                {language === 'zh' ? '拓扑画布' : 'Topology Canvas'}
              </h3>
              <p className="text-xs text-black/45">
                {language === 'zh'
                  ? '离线设备默认保留展示；陈旧链路表示最近 30 分钟未刷新。手动发现用于立即校验，不应作为唯一更新方式。'
                  : 'Offline devices remain visible by default. Stale links mean discovery has not refreshed within the last 30 minutes. Manual discovery is for immediate validation, not the only update path.'}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-black/45">
              <span className="inline-flex items-center gap-2 rounded-full border border-black/10 bg-white/90 px-3 py-1.5">
                <span className="h-2 w-2 rounded-full bg-emerald-500" />
                {language === 'zh' ? '节点在线 / 链路正常' : 'Node Online / Link Up'}
              </span>
              <span className="inline-flex items-center gap-2 rounded-full border border-black/10 bg-white/90 px-3 py-1.5">
                <span className="h-2 w-2 rounded-full bg-amber-500" />
                {language === 'zh' ? '节点告警 / 链路退化' : 'Node Alert / Link Degraded'}
              </span>
              <span className="inline-flex items-center gap-2 rounded-full border border-black/10 bg-white/90 px-3 py-1.5">
                <span className="h-2 w-2 rounded-full bg-red-500" />
                {language === 'zh' ? '节点离线 / 链路中断' : 'Node Offline / Link Down'}
              </span>
              <span className="inline-flex items-center gap-2 rounded-full border border-black/10 bg-white/90 px-3 py-1.5">
                <span className="h-2 w-2 rounded-full bg-sky-500" />
                {language === 'zh' ? '链路陈旧' : 'Link Stale'}
              </span>
              <span className="inline-flex items-center gap-2 rounded-full border border-black/10 bg-white/90 px-3 py-1.5">
                <span className="h-2 w-2 rounded-full bg-slate-400" />
                {language === 'zh' ? '链路未知' : 'Link Unknown'}
              </span>
            </div>
          </div>

          <div className="relative flex-1">
            {topologyVisibleDevices.length === 0 ? (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-center">
                <div className="rounded-full border border-black/10 bg-slate-50 p-4 text-slate-500">
                  <Globe size={26} />
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-700">
                    {language === 'zh' ? '当前筛选条件下没有可展示的设备' : 'No devices match the current topology filter'}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    {language === 'zh' ? '清空搜索或放宽站点、角色、状态筛选后重试。' : 'Clear the search or relax the site, role, or status filters.'}
                  </p>
                </div>
              </div>
            ) : (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="relative h-full w-full">
                <TopologyGraph
                  devices={topologyVisibleDevices}
                  links={topologyVisibleLinks}
                  selectedNodeId={selectedTopologyDeviceId}
                  selectedLinkKey={selectedTopologyLinkKey}
                  onNodeClick={(device) => {
                    onSelectTopologyDevice(device.id);
                  }}
                  onLinkClick={(link) => {
                    onSelectTopologyDevice(link.source_device_id);
                    onSelectTopologyLink(link.link_key || link.id || null);
                  }}
                />
              </motion.div>
            )}
          </div>

          <div className="relative flex flex-wrap items-center gap-3 border-t border-black/5 px-5 py-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-black/45">
            <span>{language === 'zh' ? `当前展示 ${topologyStats.nodeCount} 个节点 / ${topologyStats.linkCount} 条链路` : `Showing ${topologyStats.nodeCount} nodes / ${topologyStats.linkCount} links`}</span>
            <span className="h-3 w-px bg-black/10" />
            <span>{language === 'zh' ? `${topologyLinkStats.up} 正常 · ${topologyLinkStats.degraded} 退化 · ${topologyLinkStats.down} 中断 · ${topologyLinkStats.stale} 陈旧` : `${topologyLinkStats.up} up · ${topologyLinkStats.degraded} degraded · ${topologyLinkStats.down} down · ${topologyLinkStats.stale} stale`}</span>
            <span className="h-3 w-px bg-black/10" />
            <span>{language === 'zh' ? '虚线代表推断链路' : 'Dashed lines indicate inferred links'}</span>
          </div>
        </div>

        <TopologyInspectorPanel
          language={language}
          selectedTopologyDevice={selectedTopologyDevice}
          selectedTopologyLink={selectedTopologyLink}
          topologyNeighborDevices={topologyNeighborDevices}
          topologyDeviceLinks={topologyDeviceLinks}
          topologyPriorityDevices={topologyPriorityDevices}
          topologyOrphanDevices={topologyOrphanDevices}
          selectedTopologyLinkKey={selectedTopologyLinkKey}
          secondaryActionBtnClass={secondaryActionBtnClass}
          onSelectDevice={onSelectTopologyDevice}
          onSelectLink={onSelectTopologyLink}
          onOpenDeviceDetail={onOpenDeviceDetail}
          onOpenMonitoring={onOpenMonitoring}
          formatTopologyPort={formatTopologyPort}
          formatTopologyInterfaceTelemetry={formatTopologyInterfaceTelemetry}
          formatTopologyLastSeen={formatTopologyLastSeen}
          formatTopologyOperationalState={formatTopologyOperationalState}
          formatTopologyEvidenceLabel={formatTopologyEvidenceLabel}
          getTopologyOperationalTone={getTopologyOperationalTone}
        />
      </div>
      </div>
    </div>
  );
};

export default TopologyPage;
