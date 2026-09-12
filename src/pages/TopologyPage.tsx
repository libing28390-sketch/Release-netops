import React from 'react';
import { motion } from 'motion/react';
import { Activity, AlertTriangle, ArrowRight, Clock3, Database, Download, EyeOff, GitMerge, Globe, LayoutGrid, MapPin, Network, PanelRightClose, PanelRightOpen, RotateCcw, Search, Tag, X } from 'lucide-react';
import type { Device, TagDefinition } from '../types';
import { darkActionBtnClass, secondaryActionBtnClass } from '../components/shared';
import { ActionButton } from '../components/ui/ActionIconButton';
import TagConditionPicker, { countTagFilterConditions, EMPTY_TAG_FILTER, hasTagFilterConditions, type TagFilterConfig } from '../components/TagConditionPicker';
import TopologyGraph from '../components/TopologyGraph';
import TopologyInspectorPanel from '../components/TopologyInspectorPanel';
import PageHero from '../components/PageHero';
import { useTopologyGenerationStatus } from '../hooks/useTopologyGenerationStatus';
import { matchesTopologyTagConditions } from '../hooks/useTopologyVisibleDevices';
import { topologyRoleLabel } from '../domain/topologyRoles';
import { buildTopologySiteOverview } from '../utils/topologySiteOverview';

type TopologyStatusFilter = 'all' | 'online' | 'offline' | 'pending';
type TopologyLinkStatusFilter = 'all' | 'up' | 'degraded' | 'down' | 'stale' | 'unknown';
type TopologyProtocolFilter = 'all' | 'lldp';
type TopologyGraphView = 'all' | 'physical' | 'l2' | 'l3' | 'logical' | 'site' | 'external' | 'oob';

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
  relation_type?: string;
  semantic_relation?: string;
  confidence?: number;
  semantic_confidence?: number;
  is_manual?: number | boolean;
  manual_confirmed?: number | boolean;
  rank_excluded?: number | boolean;
  reverse_confirmed?: boolean;
  link_kind?: string;
  aggregation_protocol?: string;
  member_count?: number;
  active_member_count?: number;
  aggregation_bandwidth_mbps?: number | null;
  members?: Array<{ source?: { name?: string; speed_mbps?: number; up?: boolean }; target?: { name?: string; speed_mbps?: number; up?: boolean } }>;
}

interface TopologySiteOverviewProps {
  language: string;
  sites: any[];
  devices: Device[];
  links: TopologyDecoratedLinkLike[];
  onSelectSite: (siteId: string) => void;
}

const TopologySiteOverview: React.FC<TopologySiteOverviewProps> = ({ language, sites, devices, links, onSelectSite }) => {
  const overview = React.useMemo(
    () => buildTopologySiteOverview(sites, devices, links, language === 'zh' ? '未分配站点' : 'Unassigned site'),
    [devices, language, links, sites],
  );

  return (
    <div className="h-full overflow-auto bg-slate-50/70 p-5">
      <div className="mx-auto max-w-[1500px]">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-[11px] font-extrabold uppercase tracking-[0.16em] text-sky-700">
              <LayoutGrid size={14} />
              {language === 'zh' ? '全网站点总览' : 'Site overview'}
            </div>
            <h4 className="mt-1 text-xl font-extrabold tracking-tight text-slate-900">
              {language === 'zh' ? '先看故障域，再进入站点拓扑' : 'Start with a fault domain, then drill into its topology'}
            </h4>
            <p className="mt-1 max-w-2xl text-xs leading-5 text-slate-500">
              {language === 'zh' ? '站点之间只保留汇总链路，设备级端口标签在站点详情中查看，避免多站点同时展开造成视觉噪声。' : 'Inter-site links are summarized here; inspect device ports after entering a site to keep the canvas readable.'}
            </p>
          </div>
          <span className="rounded-full border border-sky-200 bg-white px-3 py-1.5 text-[11px] font-bold text-sky-700">
            {overview.sites.length} {language === 'zh' ? '个站点' : 'sites'} · {overview.connections.length} {language === 'zh' ? '组跨站连接' : 'cross-site paths'}
          </span>
        </div>

        {overview.sites.length === 0 ? (
          <div className="mt-8 rounded-2xl border border-dashed border-slate-300 bg-white p-12 text-center text-sm text-slate-500">
            {language === 'zh' ? '暂无可用站点数据，请先刷新拓扑发现。' : 'No site data is available. Run topology discovery first.'}
          </div>
        ) : (
          <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {overview.sites.map((site) => {
              const healthy = site.offlineCount === 0 && site.staleCount === 0 && site.orphanCount === 0;
              return (
                <button
                  key={site.id}
                  type="button"
                  onClick={() => onSelectSite(site.id === 'unassigned' ? 'all' : site.id)}
                  className="group rounded-2xl border border-slate-200 bg-white p-4 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:border-sky-300 hover:shadow-lg"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-2.5">
                      <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${healthy ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600'}`}>
                        <MapPin size={17} />
                      </span>
                      <div className="min-w-0">
                        <div className="truncate text-sm font-extrabold text-slate-900">{site.name}</div>
                        <div className="mt-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">{site.id}</div>
                      </div>
                    </div>
                    <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${healthy ? 'bg-emerald-500' : 'bg-amber-500'}`} title={healthy ? 'Healthy' : 'Needs attention'} />
                  </div>
                  <div className="mt-4 grid grid-cols-3 gap-2 border-t border-slate-100 pt-3">
                    <span><b className="block text-lg font-extrabold tabular-nums text-slate-900">{site.deviceCount}</b><small className="text-[10px] font-semibold text-slate-400">{language === 'zh' ? '设备' : 'Devices'}</small></span>
                    <span><b className="block text-lg font-extrabold tabular-nums text-slate-900">{site.linkCount}</b><small className="text-[10px] font-semibold text-slate-400">{language === 'zh' ? '链路' : 'Links'}</small></span>
                    <span><b className={`block text-lg font-extrabold tabular-nums ${site.offlineCount || site.orphanCount || site.staleCount ? 'text-rose-600' : 'text-emerald-600'}`}>{site.offlineCount + site.orphanCount + site.staleCount}</b><small className="text-[10px] font-semibold text-slate-400">{language === 'zh' ? '需关注' : 'Attention'}</small></span>
                  </div>
                  <div className="mt-3 flex items-center justify-between text-[11px] font-bold text-sky-700">
                    <span>{language === 'zh' ? '进入站点拓扑' : 'Open site topology'}</span>
                    <ArrowRight size={14} className="transition-transform group-hover:translate-x-1" />
                  </div>
                </button>
              );
            })}
          </div>
        )}

        {overview.connections.length > 0 && (
          <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2 text-sm font-extrabold text-slate-900"><GitMerge size={16} className="text-sky-600" />{language === 'zh' ? '跨站连接摘要' : 'Cross-site connections'}</div>
            <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
              {overview.connections.map((connection) => (
                <div key={`${connection.source}:${connection.target}`} className="flex items-center gap-2 rounded-xl border border-slate-100 bg-slate-50/80 px-3 py-2.5 text-xs">
                  <span className="min-w-0 flex-1 truncate font-bold text-slate-700">{overview.siteName(connection.source)}</span>
                  <span className="shrink-0 rounded-full bg-sky-100 px-2 py-0.5 text-[10px] font-extrabold text-sky-700">{connection.count} {language === 'zh' ? '条' : 'links'}</span>
                  <ArrowRight size={13} className={connection.down ? 'text-amber-500' : 'text-slate-300'} />
                  <span className="min-w-0 flex-1 truncate text-right font-bold text-slate-700">{overview.siteName(connection.target)}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

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
    running_devices?: number;
    pending_devices?: number;
    progress_percent: number;
    completed_at?: string | null;
    last_error_code?: string;
  } | null;
  topologyDiscoveryDevices: any[];
  topologySites: any[];
  topologyDataError: string;
  topologyStats: TopologyStats;
  topologyLinkStats: TopologyLinkStats;
  topologySearch: string;
  topologySiteFilter: string;
  topologyGraphView: TopologyGraphView;
  topologyTagFilter: TagFilterConfig;
  topologyRoleFilter: string;
  topologyStatusFilter: TopologyStatusFilter;
  topologyLinkStatusFilter: TopologyLinkStatusFilter;
  topologyProtocolFilter: TopologyProtocolFilter;
  topologySiteOptions: Array<{ id: string; name: string }>;
  topologyTagOptions: TagDefinition[];
  topologyTagCandidateDevices: Device[];
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
  onTopologyGraphViewChange: (value: TopologyGraphView) => void;
  onTopologyTagFilterChange: (value: TagFilterConfig) => void;
  onTopologyRoleFilterChange: (value: string) => void;
  onTopologyStatusFilterChange: (value: TopologyStatusFilter) => void;
  onTopologyLinkStatusFilterChange: (value: TopologyLinkStatusFilter) => void;
  onTopologyProtocolFilterChange: (value: TopologyProtocolFilter) => void;
  onSelectTopologyDevice: (deviceId: string) => void;
  onSelectTopologyLink: (linkKey: string | null) => void;
  onConfirmTopologyRelation: (edgeId: string, relationType: string) => Promise<void>;
  loadTopologyHistory: (edgeId: string) => Promise<Array<{
    id: string;
    entity_type: string;
    entity_id: string;
    event_type: string;
    before?: unknown;
    after?: unknown;
    source?: string;
    actor?: string;
    created_at?: string;
  }>>;
  onOpenWorkspace: (device: Device) => void;
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
  topologyGraphView,
  topologyTagFilter,
  topologyRoleFilter,
  topologyStatusFilter,
  topologyLinkStatusFilter,
  topologyProtocolFilter,
  topologySiteOptions,
  topologyTagOptions,
  topologyTagCandidateDevices,
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
  onTopologyGraphViewChange,
  onTopologyTagFilterChange,
  onTopologyRoleFilterChange,
  onTopologyStatusFilterChange,
  onTopologyLinkStatusFilterChange,
  onTopologyProtocolFilterChange,
  onSelectTopologyDevice,
  onSelectTopologyLink,
  onConfirmTopologyRelation,
  loadTopologyHistory,
  onOpenWorkspace,
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
  const [canvasView, setCanvasView] = React.useState<'overview' | 'site'>(topologySiteFilter === 'all' ? 'overview' : 'site');
  const [inspectorOpen, setInspectorOpen] = React.useState(false);
  const [tagPickerOpen, setTagPickerOpen] = React.useState(false);
  const [draftTopologyTagFilter, setDraftTopologyTagFilter] = React.useState<TagFilterConfig>(topologyTagFilter);
  const handleSiteFilterChange = (value: string) => {
    onTopologySiteFilterChange(value);
    setCanvasView(value === 'all' ? 'overview' : 'site');
  };
  React.useEffect(() => {
    setCanvasView(topologySiteFilter === 'all' ? 'overview' : 'site');
  }, [topologySiteFilter]);
  React.useEffect(() => {
    setDraftTopologyTagFilter(topologyTagFilter);
  }, [topologyTagFilter]);
  React.useEffect(() => {
    if (selectedTopologyDeviceId || selectedTopologyLinkKey) setInspectorOpen(true);
  }, [selectedTopologyDeviceId, selectedTopologyLinkKey]);
  const terminalDiscoveryStatus = topologyDiscoveryProgress && ['completed', 'partial', 'failed', 'cancelled'].includes(topologyDiscoveryProgress.status)
    ? `${topologyDiscoveryProgress.id}:${topologyDiscoveryProgress.status}`
    : undefined;
  const {
    status: generationStatus,
    error: generationStatusError,
    loading: generationStatusLoading,
  } = useTopologyGenerationStatus(terminalDiscoveryStatus);
  const generationInventory = generationStatus?.inventory;
  const automaticIntervalSeconds = Math.max(60, generationStatus?.generation.automatic.interval_seconds || 86400);
  const evidenceTtlSeconds = Math.max(60, generationStatus?.generation.evidence_ttl_seconds || 172800);
  const formatTopologyInterval = (seconds: number) => {
    if (seconds >= 86400 && seconds % 86400 === 0) {
      const days = Math.round(seconds / 86400);
      return language === 'zh' ? `${days} 天` : `${days} day${days === 1 ? '' : 's'}`;
    }
    const minutes = Math.max(1, Math.round(seconds / 60));
    return language === 'zh' ? `${minutes} 分钟` : `${minutes} minutes`;
  };
  const automaticIntervalLabel = formatTopologyInterval(automaticIntervalSeconds);
  const evidenceTtlLabel = formatTopologyInterval(evidenceTtlSeconds);
  const tagPreviewDevices = React.useMemo(() => {
    if (!hasTagFilterConditions(draftTopologyTagFilter)) return [];
    return topologyTagCandidateDevices.filter((device) => matchesTopologyTagConditions(device, draftTopologyTagFilter));
  }, [draftTopologyTagFilter, topologyTagCandidateDevices]);
  const topologyTagConditionCount = countTagFilterConditions(topologyTagFilter);
  const pipelineLabels: Record<string, string> = language === 'zh'
    ? {
        select: '筛选在线设备',
        collect: '只读采集 LLDP',
        normalize: '规范化厂商与端口',
        match: '匹配受管设备',
        deduplicate: '合并双向重复证据',
        publish: '发布链路与未纳管节点',
      }
    : {
        select: 'Select eligible devices',
        collect: 'Collect LLDP read-only',
        normalize: 'Normalize vendor and ports',
        match: 'Match managed devices',
        deduplicate: 'Merge directional evidence',
        publish: 'Publish links and unmanaged peers',
      };
  const pipelineStages = generationStatus?.generation.pipeline.map((stage) => stage.stage)
    || ['select', 'collect', 'normalize', 'match', 'deduplicate', 'publish'];

  return (
    <div className="topology-page-shell h-full flex flex-col overflow-hidden">
      <PageHero
        icon={Network}
        title={language === 'zh' ? '网络拓扑' : 'Network Topology'}
        subtitle={language === 'zh'
          ? '基于 LLDP 邻居证据自动生成连接关系，按站点、角色和状态快速缩小故障域。'
          : 'Generate network adjacency from LLDP evidence and reduce the fault domain by site, role, and health state.'}
        actions={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onTriggerDiscovery}
              disabled={topologyDiscoveryRunning}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-blue-600 text-white hover:bg-blue-700 shadow-2xs transition-all cursor-pointer disabled:opacity-60"
            >
              <RotateCcw size={13} className={topologyDiscoveryRunning ? 'animate-spin' : ''} />
              {topologyDiscoveryRunning
                ? (language === 'zh' ? '发现中...' : 'Discovering...')
                : (language === 'zh' ? '刷新发现' : 'Refresh Discovery')}
            </button>
            {topologyDiscoveryRunning && (
              <button
                type="button"
                onClick={onCancelDiscovery}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold border border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100 transition-all cursor-pointer"
              >
                {language === 'zh' ? '取消任务' : 'Cancel Run'}
              </button>
            )}
            <ActionButton
              type="button"
              icon={Download}
              variant="accent"
              onClick={onExportMap}
            >
              {language === 'zh' ? '导出拓扑图' : 'Export Map'}
            </ActionButton>
          </div>
        }
      />

      <div className="ops-page-scroll flex-1 overflow-auto p-5 space-y-4">

      {topologyDataError && (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
          {language === 'zh' ? '拓扑数据刷新异常：' : 'Topology data refresh warning: '}{topologyDataError}
        </div>
      )}

      {/* Topology Generation Pipeline */}
      <div className="bg-white dark:bg-zinc-900/90 border border-gray-200/70 dark:border-zinc-800/80 rounded-2xl p-4 shadow-2xs">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-blue-600 bg-blue-50 px-2 py-0.5 rounded-full">
                LLDP
              </span>
              <h3 className="text-sm font-bold text-gray-900 dark:text-white">{language === 'zh' ? '拓扑自动生成流水线' : 'Topology Generation Pipeline'}</h3>
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${generationStatus?.health === 'healthy' ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300' : generationStatus?.health === 'degraded' ? 'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300' : 'bg-gray-100 text-gray-600 dark:bg-zinc-800 dark:text-zinc-400'}`}>
                {generationStatusLoading
                  ? (language === 'zh' ? '读取中' : 'Loading')
                  : generationStatus?.health === 'healthy'
                    ? (language === 'zh' ? '证据正常' : 'Healthy')
                    : generationStatus?.health === 'degraded'
                      ? (language === 'zh' ? '需要关注' : 'Attention')
                      : (language === 'zh' ? '等待证据' : 'Awaiting Evidence')}
              </span>
            </div>
            <p className="mt-1 text-xs text-gray-400">
              {language === 'zh'
                ? `系统每 ${automaticIntervalLabel} 自动执行一次；“刷新发现”会同时刷新接口摘要、聚合成员和邻居关系，全部为设备只读查询，不写入设备配置。`
                : `Automatic discovery runs every ${automaticIntervalLabel}; Refresh Discovery is for immediate validation. Device access is limited to vendor-specific read-only neighbor queries.`}
            </p>
          </div>
          <div className="flex flex-wrap gap-2 text-xs font-mono text-gray-500">
            <span className="inline-flex items-center gap-1.5 rounded-xl border border-gray-200/80 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-800 px-2.5 py-1 text-[11px]"><Clock3 size={12} />{language === 'zh' ? `证据 ${evidenceTtlLabel}过期` : `${evidenceTtlLabel} TTL`}</span>
            <span className="inline-flex items-center gap-1.5 rounded-xl border border-gray-200/80 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-800 px-2.5 py-1 text-[11px]"><Database size={12} />{language === 'zh' ? `${generationInventory?.eligible_devices ?? '—'} 台可发现` : `${generationInventory?.eligible_devices ?? '—'} eligible`}</span>
            <span className="inline-flex items-center gap-1.5 rounded-xl border border-gray-200/80 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-800 px-2.5 py-1 text-[11px]"><Activity size={12} />{language === 'zh' ? `${generationInventory?.managed_links ?? '—'} 条已生成链路` : `${generationInventory?.managed_links ?? '—'} links`}</span>
          </div>
        </div>

        <div className="mt-3 grid gap-2 grid-cols-2 sm:grid-cols-3 xl:grid-cols-6">
          {pipelineStages.map((stage, index) => (
            <div key={stage} className="relative rounded-xl border border-gray-100 dark:border-zinc-800 bg-gray-50/70 dark:bg-zinc-800/40 px-3 py-2">
              <div className="text-[9px] font-bold text-blue-600 dark:text-blue-400 font-mono">{String(index + 1).padStart(2, '0')}</div>
              <div className="mt-0.5 text-xs font-medium text-gray-700 dark:text-zinc-300 truncate">{pipelineLabels[stage] || stage}</div>
            </div>
          ))}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-gray-400 font-mono">
          <span>{language === 'zh' ? '最近邻居证据：' : 'Latest evidence: '}{generationInventory?.last_observation_at ? formatTopologyLastSeen(generationInventory.last_observation_at) : (language === 'zh' ? '暂无' : 'None')}</span>
          <span>{language === 'zh' ? '匹配：' : 'Matched: '}<b className="text-emerald-600 font-bold">{generationInventory?.matched_observations ?? 0}</b></span>
          <span>{language === 'zh' ? '歧义：' : 'Ambiguous: '}<b className="text-amber-600 font-bold">{generationInventory?.ambiguous_observations ?? 0}</b></span>
          <span>{language === 'zh' ? '未纳管：' : 'Unmanaged: '}<b className="text-gray-600 font-bold">{generationInventory?.unmatched_observations ?? 0}</b></span>
          <span>{language === 'zh' ? '双向/多证据：' : 'Multi-evidence: '}<b className="text-blue-600 font-bold">{generationInventory?.multi_evidence_links ?? 0}</b></span>
          <span>{language === 'zh' ? '陈旧链路：' : 'Stale: '}<b className="text-rose-600 font-bold">{generationInventory?.stale_links ?? 0}</b></span>
        </div>
        {(generationStatusError || (generationStatus?.warnings.length || 0) > 0) && (
          <div className="mt-2.5 flex flex-wrap gap-2">
            {generationStatusError && (
              <span className="inline-flex items-center gap-1 rounded-xl bg-amber-50 px-2 py-1 text-[11px] font-semibold text-amber-700"><AlertTriangle size={11} />{language === 'zh' ? '生成状态暂时不可用，拓扑数据仍可继续查看。' : 'Generation status is temporarily unavailable; topology data remains available.'}</span>
            )}
            {generationStatus?.warnings.map((warning) => (
              <span key={warning.code} className="inline-flex items-center gap-1 rounded-xl bg-amber-50 px-2 py-1 text-[11px] font-semibold text-amber-700"><AlertTriangle size={11} />{warning.code} · {warning.count}</span>
            ))}
          </div>
        )}
      </div>

      {/* Discovery Task Strip */}
      {topologyDiscoveryProgress && (
        <div className={`bg-white dark:bg-zinc-900/90 border border-gray-200/70 dark:border-zinc-800/80 rounded-2xl p-4 shadow-2xs ${topologyDiscoveryProgress.status === 'failed' ? 'border-l-4 border-l-rose-500' : topologyDiscoveryProgress.status === 'partial' ? 'border-l-4 border-l-amber-500' : 'border-l-4 border-l-blue-500'}`}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-bold text-gray-900 dark:text-white">{language === 'zh' ? '拓扑发现任务执行中' : 'Topology Discovery Run'}</h3>
              <p className="mt-0.5 text-xs text-gray-400 font-mono">
                {topologyDiscoveryProgress.status} · {topologyDiscoveryProgress.processed_devices}/{topologyDiscoveryProgress.total_devices}
                {' · '}{language === 'zh' ? '成功' : 'Succeeded'} {topologyDiscoveryProgress.success_devices || 0}
                {' · '}{language === 'zh' ? '失败' : 'Failed'} {topologyDiscoveryProgress.failed_devices || 0}
              </p>
            </div>
            <span className="text-lg font-extrabold tabular-nums text-blue-600 font-mono">{topologyDiscoveryProgress.progress_percent}%</span>
          </div>
          <div className="mt-2.5 h-1.5 overflow-hidden rounded-full bg-gray-100 dark:bg-zinc-800">
            <div className="h-full rounded-full bg-blue-600 transition-all duration-300" style={{ width: `${Math.min(100, Math.max(0, topologyDiscoveryProgress.progress_percent))}%` }} />
          </div>
          {topologyDiscoveryDevices.length > 0 && (
            <div className="mt-2.5 flex flex-wrap gap-1.5">
              {topologyDiscoveryDevices.slice(0, 8).map((item: any) => (
                <span
                  key={item.device_id}
                  title={item.error_message || item.error_code || item.status}
                  className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${item.status === 'success' ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400' : item.status === 'failed' ? 'bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-400' : 'bg-gray-100 text-gray-600 dark:bg-zinc-800 dark:text-zinc-400'}`}
                >
                  {item.hostname || item.device_id}: {item.status}{item.error_code ? ` (${item.error_code})` : ''}
                </span>
              ))}
            </div>
          )}
          {(topologyDiscoveryProgress.failed_devices || 0) > 0 && (
            <p className="mt-2 text-[11px] text-rose-600">
              {language === 'zh'
                ? '失败设备会保留上一轮有效邻居证据；将鼠标停留在设备状态上可查看错误详情。'
                : 'Failed devices retain their last valid neighbor evidence. Hover a device status to inspect the error.'}
            </p>
          )}
        </div>
      )}

      {/* Metrics Bar */}
      <div className="bg-white dark:bg-zinc-900/90 border border-gray-200/70 dark:border-zinc-800/80 rounded-2xl p-3.5 shadow-2xs flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          {[
            { label: language === 'zh' ? '节点' : 'Nodes', value: topologyStats.nodeCount, color: 'text-blue-600 dark:text-blue-400' },
            { label: language === 'zh' ? '链路' : 'Links', value: topologyStats.linkCount, color: 'text-gray-800 dark:text-zinc-200' },
            { label: language === 'zh' ? '站点' : 'Sites', value: topologyStats.siteCount, color: 'text-emerald-600 dark:text-emerald-400' },
            { label: language === 'zh' ? '风险' : 'Risk', value: topologyStats.atRiskCount, color: topologyStats.atRiskCount > 0 ? 'text-amber-600' : 'text-gray-400' },
            { label: language === 'zh' ? '孤立' : 'Orphans', value: topologyStats.orphanCount, color: topologyStats.orphanCount > 0 ? 'text-rose-600' : 'text-gray-400' },
          ].map((item) => (
            <div key={item.label} className="flex items-baseline gap-1.5">
              <span className={`text-xl font-extrabold tabular-nums tracking-tight font-mono ${item.color}`}>{item.value}</span>
              <span className="text-xs font-medium text-gray-400">{item.label}</span>
            </div>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs">
          {[
            { label: language === 'zh' ? '正常' : 'Up', value: topologyLinkStats.up, dot: 'bg-emerald-500' },
            { label: language === 'zh' ? '退化' : 'Degraded', value: topologyLinkStats.degraded, dot: 'bg-amber-500' },
            { label: language === 'zh' ? '中断' : 'Down', value: topologyLinkStats.down, dot: 'bg-rose-500' },
            { label: language === 'zh' ? '陈旧' : 'Stale', value: topologyLinkStats.stale, dot: 'bg-gray-300 dark:bg-zinc-600' },
            { label: language === 'zh' ? '多源' : 'Multi', value: topologyLinkStats.multiSource, dot: 'bg-blue-500' },
          ].map((item) => (
            <div key={item.label} className="flex items-center gap-1.5 bg-gray-50 dark:bg-zinc-800 px-2 py-1 rounded-lg">
              <span className={`h-1.5 w-1.5 rounded-full ${item.dot}`} />
              <span className="font-semibold tabular-nums text-gray-800 dark:text-zinc-200 font-mono">{item.value}</span>
              <span className="text-gray-400 text-[11px]">{item.label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Filters Toolbar */}
      <div className="bg-white dark:bg-zinc-900/90 border border-gray-200/70 dark:border-zinc-800/80 rounded-2xl p-3.5 shadow-2xs space-y-2.5">
        <div className="grid gap-2.5 lg:grid-cols-[minmax(0,1.4fr)_repeat(7,minmax(0,0.8fr))]">
          <label className="flex items-center gap-2 rounded-xl border border-gray-200/80 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-800 px-3 py-1.5">
            <Search size={14} className="text-gray-400" />
            <input
              value={topologySearch}
              onChange={(event) => onTopologySearchChange(event.target.value)}
              placeholder={language === 'zh' ? '搜索主机名、IP、站点、角色' : 'Search hostname, IP, site, role'}
              className="w-full bg-transparent text-xs outline-none text-gray-800 dark:text-zinc-100 placeholder:text-gray-400"
            />
          </label>
          <select
            value={topologySiteFilter}
            onChange={(event) => handleSiteFilterChange(event.target.value)}
            title={language === 'zh' ? '按站点筛选拓扑' : 'Filter topology by site'}
            className="rounded-xl border border-gray-200/80 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-800 px-2.5 py-1.5 text-xs outline-none text-gray-700 dark:text-zinc-200 cursor-pointer"
          >
            <option value="all">{language === 'zh' ? '全部站点' : 'All Sites'}</option>
            {topologySiteOptions.map((site) => <option key={site.id} value={site.id}>{site.name}</option>)}
          </select>
          <select
            value={topologyGraphView}
            onChange={(event) => onTopologyGraphViewChange(event.target.value as TopologyGraphView)}
            title={language === 'zh' ? '选择关系视图' : 'Choose relation view'}
            className="rounded-xl border border-gray-200/80 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-800 px-2.5 py-1.5 text-xs outline-none text-gray-700 dark:text-zinc-200 cursor-pointer"
          >
            <option value="physical">{language === 'zh' ? '物理视图（LLDP/CDP）' : 'Physical (LLDP/CDP)'}</option>
            <option value="l2">{language === 'zh' ? '二层视图（STP/MAC）' : 'L2 (STP/MAC)'}</option>
            <option value="l3">{language === 'zh' ? '三层视图（OSPF/BGP/路由）' : 'L3 (OSPF/BGP/Routing)'}</option>
            <option value="logical">{language === 'zh' ? '逻辑视图（L3/路由）' : 'Logical (L3/Routing)'}</option>
            <option value="all">{language === 'zh' ? '综合视图' : 'Composite'}</option>
            <option value="oob">{language === 'zh' ? 'OOB 管理视图' : 'OOB management'}</option>
            <option value="external">{language === 'zh' ? '外部/端点视图' : 'External / endpoint'}</option>
          </select>
          <div className="relative">
            <button
              type="button"
              onClick={() => {
                if (!tagPickerOpen) setDraftTopologyTagFilter(topologyTagFilter);
                setTagPickerOpen((open) => !open);
              }}
              className={`flex w-full items-center justify-between gap-1.5 rounded-xl border border-gray-200/80 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-800 px-2.5 py-1.5 text-left text-xs cursor-pointer ${topologyTagConditionCount ? 'text-blue-600 font-bold' : 'text-gray-600 dark:text-zinc-300'}`}
              title={language === 'zh' ? '按标签筛选拓扑设备和链路' : 'Filter topology devices and links by tags'}
            >
              <span className="flex min-w-0 items-center gap-1 truncate"><Tag size={12} />{language === 'zh' ? '设备标签' : 'Device tags'}{topologyTagConditionCount ? ` (${topologyTagConditionCount})` : ''}</span>
              <span className="text-[10px]">▾</span>
            </button>
            {tagPickerOpen && (
              <div className="absolute left-0 top-full z-40 mt-1 w-[min(560px,calc(100vw-2rem))] rounded-2xl border border-gray-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 p-4 shadow-xl">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-xs font-bold text-gray-800 dark:text-zinc-200">{language === 'zh' ? '标签条件（支持嵌套与 / 或 / 非）' : 'Nested tag conditions (AND / OR / NOT)'}</span>
                  <button
                    type="button"
                    onClick={() => setDraftTopologyTagFilter({
                      expression: { ...EMPTY_TAG_FILTER.expression, tag_ids: [], groups: [] },
                      groups: [],
                      exclude_tag_ids: [],
                    })}
                    className="text-[11px] text-gray-400 hover:text-gray-700 cursor-pointer"
                  >
                    {language === 'zh' ? '清空' : 'Clear'}
                  </button>
                </div>
                <TagConditionPicker
                  value={draftTopologyTagFilter}
                  onChange={setDraftTopologyTagFilter}
                  language={language}
                  tagDefinitions={topologyTagOptions}
                />
                {hasTagFilterConditions(draftTopologyTagFilter) && (
                  <div className="mt-2 rounded-xl bg-blue-50 dark:bg-blue-950/40 p-2.5 text-xs text-blue-700 dark:text-blue-300">
                    {language === 'zh' ? `预览：${tagPreviewDevices.length} 台设备，确认后仅显示这些设备及其内部链路` : `Preview: ${tagPreviewDevices.length} devices`}
                  </div>
                )}
                <div className="mt-3 flex justify-end gap-2">
                  <button type="button" onClick={() => { setDraftTopologyTagFilter(topologyTagFilter); setTagPickerOpen(false); }} className="rounded-xl border border-gray-200 px-3 py-1 text-xs text-gray-600 hover:bg-gray-50 cursor-pointer">{language === 'zh' ? '取消' : 'Cancel'}</button>
                  <button type="button" onClick={() => { onTopologyTagFilterChange(draftTopologyTagFilter); setTagPickerOpen(false); }} className="rounded-xl bg-blue-600 px-3 py-1 text-xs font-bold text-white hover:bg-blue-700 cursor-pointer">{language === 'zh' ? '确认筛选' : 'Apply'}</button>
                </div>
              </div>
            )}
          </div>
          <select
            value={topologyRoleFilter}
            onChange={(event) => onTopologyRoleFilterChange(event.target.value)}
            title={language === 'zh' ? '按角色筛选拓扑' : 'Filter topology by role'}
            className="rounded-xl border border-gray-200/80 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-800 px-2.5 py-1.5 text-xs outline-none text-gray-700 dark:text-zinc-200 cursor-pointer"
          >
            <option value="all">{language === 'zh' ? '全部角色' : 'All Roles'}</option>
            {topologyRoleOptions.map((role) => <option key={role} value={role}>{topologyRoleLabel(role, language)}</option>)}
          </select>
          <select
            value={topologyStatusFilter}
            onChange={(event) => onTopologyStatusFilterChange(event.target.value as TopologyStatusFilter)}
            title={language === 'zh' ? '按状态筛选拓扑' : 'Filter topology by status'}
            className="rounded-xl border border-gray-200/80 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-800 px-2.5 py-1.5 text-xs outline-none text-gray-700 dark:text-zinc-200 cursor-pointer"
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
            className="rounded-xl border border-gray-200/80 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-800 px-2.5 py-1.5 text-xs outline-none text-gray-700 dark:text-zinc-200 cursor-pointer"
          >
            <option value="all">{language === 'zh' ? '全部链路状态' : 'All Link States'}</option>
            <option value="up">{language === 'zh' ? '链路正常' : 'Link Up'}</option>
            <option value="degraded">{language === 'zh' ? '链路退化' : 'Link Degraded'}</option>
            <option value="down">{language === 'zh' ? '链路中断' : 'Link Down'}</option>
            <option value="stale">{language === 'zh' ? '链路陈旧' : 'Link Stale'}</option>
            <option value="unknown">{language === 'zh' ? '链路未知' : 'Link Unknown'}</option>
          </select>
        </div>
        <div className="flex items-center gap-3 pt-0.5">
          <label className="flex items-center gap-2 cursor-pointer select-none rounded-xl border border-gray-200/80 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-800 px-3 py-1 transition-colors hover:bg-gray-100" title={language === 'zh' ? '隐藏陈旧链路（最近30分钟未刷新的链路将被隐藏）' : 'Hide stale links'}>
            <input
              type="checkbox"
              checked={hideStaleLinks}
              onChange={(e) => onHideStaleLinksChange(e.target.checked)}
              className="h-3.5 w-3.5 rounded accent-blue-600 cursor-pointer"
            />
            <EyeOff size={13} className="text-gray-400" />
            <span className="text-xs font-semibold text-gray-600 dark:text-zinc-300">{language === 'zh' ? '隐藏陈旧链路' : 'Hide Stale Links'}</span>
          </label>
          <label className="flex items-center gap-2 cursor-pointer select-none rounded-xl border border-gray-200/80 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-800 px-3 py-1 transition-colors hover:bg-gray-100" title={language === 'zh' ? '隐藏孤立设备（没有任何链路连接的设备将被隐藏）' : 'Hide orphan devices'}>
            <input
              type="checkbox"
              checked={hideOrphanDevices}
              onChange={(e) => onHideOrphanDevicesChange(e.target.checked)}
              className="h-3.5 w-3.5 rounded accent-blue-600 cursor-pointer"
            />
            <EyeOff size={13} className="text-gray-400" />
            <span className="text-xs font-semibold text-gray-600 dark:text-zinc-300">{language === 'zh' ? '隐藏孤立设备' : 'Hide Orphan Devices'}</span>
          </label>
        </div>
      </div>

      {/* Canvas & Inspector Shell */}
      <div className={`grid min-h-0 flex-1 gap-4 ${inspectorOpen ? 'xl:grid-cols-[minmax(0,2.35fr)_minmax(320px,0.85fr)]' : 'xl:grid-cols-1'}`}>
        <div className="bg-white dark:bg-zinc-900/90 border border-gray-200/70 dark:border-zinc-800/80 relative flex min-h-[500px] flex-col overflow-hidden rounded-2xl shadow-2xs" ref={topologyCanvasRef}>
          <div className="relative flex items-center justify-between border-b border-gray-100 dark:border-zinc-800 px-4 py-3">
            <div>
              <h3 className="text-sm font-bold text-gray-900 dark:text-white">
                {language === 'zh' ? '拓扑画布' : 'Topology Canvas'}
              </h3>
              <p className="text-xs text-gray-400">
                {language === 'zh'
                  ? '离线设备默认保留展示；陈旧链路表示最近 30 分钟未刷新。'
                  : 'Offline devices remain visible by default; stale links indicate 30m without refresh.'}
              </p>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2 text-xs">
              <div className="flex items-center rounded-xl bg-gray-100 dark:bg-zinc-800 p-0.5">
                <button
                  type="button"
                  onClick={() => handleSiteFilterChange('all')}
                  className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-semibold transition-all cursor-pointer ${canvasView === 'overview' ? 'bg-white dark:bg-zinc-700 text-gray-900 dark:text-white shadow-2xs' : 'text-gray-500 hover:text-gray-800'}`}
                >
                  <LayoutGrid size={12} /> {language === 'zh' ? 'Site 总览' : 'Overview'}
                </button>
                <button
                  type="button"
                  onClick={() => setCanvasView('site')}
                  disabled={topologySiteFilter === 'all'}
                  className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-semibold transition-all cursor-pointer ${canvasView === 'site' ? 'bg-white dark:bg-zinc-700 text-gray-900 dark:text-white shadow-2xs' : 'text-gray-500 hover:text-gray-800'} disabled:cursor-not-allowed disabled:opacity-40`}
                >
                  <Network size={12} /> {language === 'zh' ? '站点拓扑' : 'Site topology'}
                </button>
              </div>
              <button
                type="button"
                onClick={() => setInspectorOpen((value) => !value)}
                className="inline-flex items-center gap-1.5 rounded-xl border border-gray-200/80 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-2.5 py-1 text-xs font-semibold text-gray-700 dark:text-zinc-200 hover:bg-gray-50 transition-all cursor-pointer"
                title={inspectorOpen ? 'Hide inspector' : 'Show inspector'}
              >
                {inspectorOpen ? <PanelRightClose size={13} /> : <PanelRightOpen size={13} />}
                {inspectorOpen ? (language === 'zh' ? '收起详情' : 'Hide') : (language === 'zh' ? '展开详情' : 'Details')}
              </button>
            </div>
          </div>

          <div className="relative flex-1">
            {canvasView === 'overview' ? (
              <TopologySiteOverview
                language={language}
                sites={topologySites}
                devices={topologyVisibleDevices}
                links={topologyVisibleLinks}
                onSelectSite={handleSiteFilterChange}
              />
            ) : topologyVisibleDevices.length === 0 ? (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-center">
                <div className="rounded-full border border-gray-200 dark:border-zinc-800 bg-gray-50 dark:bg-zinc-800 p-4 text-gray-400">
                  <Globe size={26} />
                </div>
                <div>
                  <p className="text-sm font-semibold text-gray-700 dark:text-zinc-200">
                    {language === 'zh' ? '当前筛选条件下没有可展示的设备' : 'No devices match the current topology filter'}
                  </p>
                  <p className="mt-1 text-xs text-gray-400">
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
                  onOpenWorkspace={onOpenWorkspace}
                  onLinkClick={(link) => {
                    onSelectTopologyDevice(link.source_device_id);
                    onSelectTopologyLink(link.link_key || link.id || null);
                  }}
                />
              </motion.div>
            )}
          </div>

          <div className="relative flex flex-wrap items-center gap-3 border-t border-gray-100 dark:border-zinc-800 px-4 py-2.5 text-xs font-mono text-gray-400">
            <span>{language === 'zh' ? `当前展示 ${topologyStats.nodeCount} 节点 · ${topologyStats.linkCount} 链路` : `Showing ${topologyStats.nodeCount} nodes / ${topologyStats.linkCount} links`}</span>
            <span className="h-3 w-px bg-gray-200 dark:bg-zinc-700" />
            <span>{language === 'zh' ? `${topologyLinkStats.up} 正常 · ${topologyLinkStats.degraded} 退化 · ${topologyLinkStats.down} 中断 · ${topologyLinkStats.stale} 陈旧` : `${topologyLinkStats.up} up · ${topologyLinkStats.degraded} degraded · ${topologyLinkStats.down} down · ${topologyLinkStats.stale} stale`}</span>
            <span className="h-3 w-px bg-gray-200 dark:bg-zinc-700" />
            <span>{language === 'zh' ? '虚线代表推断链路' : 'Dashed: inferred'}</span>
          </div>
        </div>

        {inspectorOpen && <TopologyInspectorPanel
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
          onConfirmTopologyRelation={onConfirmTopologyRelation}
          loadTopologyHistory={loadTopologyHistory}
        />}
      </div>
      </div>
    </div>
  );
};

export default TopologyPage;
