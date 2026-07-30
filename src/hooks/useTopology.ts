import React, { useCallback, useMemo, useState } from 'react';
import * as htmlToImage from 'html-to-image';
import type { Device } from '../types';
import { EMPTY_TAG_FILTER, type TagFilterConfig } from '../components/TagConditionPicker';
import type { Language } from '../i18n.tsx';
import { parseJsonObject } from '../components/shared';
import {
  normalizeTopologyPort,
  type TopologyOperationalState,
} from '../utils/topologyCore';
import { buildTopologyExportFilename, getTopologyExportPixelRatio } from '../utils/topologyExport';
import { useTopologyVisibleDevices } from './useTopologyVisibleDevices';
import { useTopologySelectionSync } from './useTopologySelectionSync';

export type TopologyInterfaceSnapshot = {
  name: string;
  /** Interface speed reported by the device, in Mbps. */
  speedMbps: number | null;
  status: string;
  maxUtilizationPct: number | null;
  errorCount: number;
  discardCount: number;
  flapping: boolean;
  operationalState: TopologyOperationalState;
};

export type TopologyDecoratedLink = {
  id?: string;
  link_key?: string;
  source_device_id: string;
  target_device_id: string;
  source_port?: string;
  source_port_normalized?: string;
  target_port?: string;
  target_port_normalized?: string;
  source_hostname?: string;
  target_hostname?: string;
  source_hostname_resolved?: string;
  target_hostname_resolved?: string;
  discovery_source?: string;
  evidence_count?: number;
  metadata_json?: string;
  last_seen?: string;
  ttl_seconds?: number;
  inferred?: boolean;
  is_inferred?: boolean | number;
  status?: string;
  operational_state: TopologyOperationalState;
  operational_summary: string;
  evidence_sources: string[];
  reverse_confirmed: boolean;
  source_interface_snapshot: TopologyInterfaceSnapshot | null;
  target_interface_snapshot: TopologyInterfaceSnapshot | null;
  /** Effective link capacity in Mbps. When both sides are known, the lower speed wins. */
  bandwidth_mbps?: number | null;
  link_kind?: 'physical' | 'aggregation' | string;
  source_aggregation_name?: string;
  target_aggregation_name?: string;
  aggregation_protocol?: string;
  member_count?: number;
  active_member_count?: number;
  aggregation_bandwidth_mbps?: number | null;
  members?: Array<Record<string, unknown>>;
  is_unmanaged?: boolean;
};

export type TopologySiteSummary = {
  site_id: string;
  site_code: string;
  site_name: string;
  device_count: number;
  online_devices: number;
  offline_devices: number;
  link_count: number;
  cross_site_links: number;
  stale_links: number;
  orphan_devices: number;
  last_discovery_at?: string | null;
  last_discovery_status?: string | null;
};

export type TopologyDiscoveryProgress = {
  id: string;
  status: string;
  total_devices: number;
  processed_devices: number;
  success_devices: number;
  failed_devices: number;
  running_devices: number;
  pending_devices: number;
  progress_percent: number;
  started_at?: string;
  completed_at?: string | null;
};

export type TopologyLinkStatusFilter = 'all' | 'up' | 'degraded' | 'down' | 'stale' | 'unknown';
export type TopologyProtocolFilter = 'all' | 'lldp';

const topologyAuthHeaders = (): Record<string, string> => {
  const token = localStorage.getItem('netops_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
};

const createTopologyIdempotencyKey = (): string => {
  const cryptoApi = globalThis.crypto;
  if (cryptoApi && typeof cryptoApi.randomUUID === 'function') {
    return cryptoApi.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
};

const topologyApiErrorMessage = (payload: unknown, fallback: string): string => {
  if (!payload || typeof payload !== 'object') return fallback;
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (detail && typeof detail === 'object') {
    const message = (detail as { message?: unknown }).message;
    const code = (detail as { code?: unknown }).code;
    if (typeof message === 'string' && message.trim()) return message;
    if (typeof code === 'string' && code.trim()) return code;
  }
  return fallback;
};

const STALE_THRESHOLD_MS = 30 * 60 * 1000;

const EXPORT_BANDWIDTH_TIERS = [
  { label: '10M', color: '#f97316', minMbps: 0 },
  { label: '100M', color: '#eab308', minMbps: 100 },
  { label: '1G', color: '#22c55e', minMbps: 1_000 },
  { label: '10G', color: '#0ea5e9', minMbps: 10_000 },
  { label: '40G', color: '#8b5cf6', minMbps: 40_000 },
  { label: '80G', color: '#ec4899', minMbps: 80_000 },
  { label: '100G', color: '#db2777', minMbps: 100_000 },
  { label: '200G+', color: '#4338ca', minMbps: 200_000 },
  { label: 'Unknown', color: '#64748b', minMbps: -1 },
] as const;

const inferInterfaceSpeedMbps = (value?: string): number | null => {
  const name = String(value || '').trim().toLowerCase().replace(/\s+/g, '');
  if (!name) return null;
  if (/^(fourhundredgigabitethernet|fourhundredgige|400g)/.test(name)) return 400_000;
  if (/^(twohundredgigabitethernet|twohundredgige|200g)/.test(name)) return 200_000;
  if (/^(eightygigabitethernet|eightygige|80g)/.test(name)) return 80_000;
  if (/^(fortygigabitethernet|fo)/.test(name)) return 40_000;
  if (/^(hundredgigabitethernet|hu)/.test(name)) return 100_000;
  if (/^(twentyfivegige|tw)/.test(name)) return 25_000;
  if (/^(tengigabitethernet|te)/.test(name)) return 10_000;
  if (/^(gigabitethernet|gi|ge)/.test(name)) return 1_000;
  if (/^(fastethernet|fa)/.test(name)) return 100;
  if (/^(ethernet|et|e)/.test(name)) return 10;
  return null;
};

interface UseTopologyArgs {
  devices: Device[];
  language: Language;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
  refreshDevices?: () => Promise<unknown>;
}

export const useTopology = ({ devices, language, showToast, refreshDevices }: UseTopologyArgs) => {
  const [topologyLinks, setTopologyLinks] = useState<any[]>([]);
  const [topologySearch, setTopologySearch] = useState('');
  const [topologyStatusFilter, setTopologyStatusFilter] = useState<'all' | 'online' | 'offline' | 'pending'>('all');
  const [topologyRoleFilter, setTopologyRoleFilter] = useState('all');
  const [topologySiteFilter, setTopologySiteFilter] = useState('all');
  const [topologyTagFilter, setTopologyTagFilter] = useState<TagFilterConfig>(() => ({
    expression: { ...EMPTY_TAG_FILTER.expression, tag_ids: [], groups: [] },
    groups: [],
    exclude_tag_ids: [],
  }));
  const [topologyLinkStatusFilter, setTopologyLinkStatusFilter] = useState<TopologyLinkStatusFilter>('all');
  // Topology discovery is LLDP-based by default; keep the protocol contract
  // internal instead of exposing a redundant one-option filter in the toolbar.
  const [topologyProtocolFilter, setTopologyProtocolFilter] = useState<TopologyProtocolFilter>('lldp');
  const [selectedTopologyDeviceId, setSelectedTopologyDeviceId] = useState<string | null>(null);
  const [selectedTopologyLinkKey, setSelectedTopologyLinkKey] = useState<string | null>(null);
  const [topologyDiscoveryRunning, setTopologyDiscoveryRunning] = useState(false);
  const [topologyDiscoveryRunId, setTopologyDiscoveryRunId] = useState<string | null>(null);
  const [topologyDiscoveryProgress, setTopologyDiscoveryProgress] = useState<TopologyDiscoveryProgress | null>(null);
  const [topologyDiscoveryDevices, setTopologyDiscoveryDevices] = useState<any[]>([]);
  const [topologySites, setTopologySites] = useState<TopologySiteSummary[]>([]);
  const [topologyDataError, setTopologyDataError] = useState('');
  // A topology canvas represents the currently verified graph. Historical
  // links remain available through the explicit stale-link toggle, but must
  // not look like live neighbors by default.
  const [hideStaleLinks, setHideStaleLinks] = useState(true);
  const [hideOrphanDevices, setHideOrphanDevices] = useState(false);
  const topologyRef = React.useRef<HTMLDivElement>(null);

  const refreshTopologyData = useCallback(async () => {
    // The topology canvas is intentionally capped at the backend's normal
    // graph page size; requesting 10k rows only increases payload and render
    // work for a view that already filters to one site when needed.
    const params = new URLSearchParams({ limit: '5000' });
    params.set('include_stale', hideStaleLinks ? 'false' : 'true');
    if (topologySiteFilter !== 'all') params.set('site_id', topologySiteFilter);
    const [linksResponse, sitesResponse] = await Promise.all([
      fetch(`/api/topology/links?${params.toString()}`, { headers: topologyAuthHeaders() }),
      fetch('/api/topology/sites', { headers: topologyAuthHeaders() }),
    ]);
    if (!linksResponse.ok) throw new Error(`topology_links_${linksResponse.status}`);
    const linksPayload = await linksResponse.json();
    const nextLinks = Array.isArray(linksPayload?.links) ? linksPayload.links : [];
    // A device can be added from the asset/CMDB page while this SPA is still
    // holding the previous device snapshot. In that case the backend returns
    // valid links, but the frontend would drop them because their endpoint IDs
    // are not present in the stale local list. Reconcile the device inventory
    // before publishing the new graph data.
    if (refreshDevices) {
      const currentDeviceIds = new Set(devices.map((device) => String(device.id)));
      const hasUnknownEndpoint = nextLinks.some((link: any) => (
        !currentDeviceIds.has(String(link.source_device_id || ''))
        || !currentDeviceIds.has(String(link.target_device_id || ''))
      ));
      if (hasUnknownEndpoint) await refreshDevices();
    }
    setTopologyLinks(nextLinks);
    if (sitesResponse.ok) {
      const sitesPayload = await sitesResponse.json();
      setTopologySites(Array.isArray(sitesPayload?.items) ? sitesPayload.items : []);
    }
    setTopologyDataError(sitesResponse.ok ? '' : `topology_sites_${sitesResponse.status}`);
  }, [devices, hideStaleLinks, refreshDevices, topologySiteFilter]);

  React.useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        await refreshTopologyData();
      } catch (error) {
        if (active) setTopologyDataError(error instanceof Error ? error.message : 'topology_fetch_failed');
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 60_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [refreshTopologyData]);

  const evaluateTopologyInterfaceSnapshot = useCallback(
    (device: Device | null | undefined, port?: string): TopologyInterfaceSnapshot | null => {
      if (!device || !port) return null;
      const normalizedPort = normalizeTopologyPort(port);
      if (!normalizedPort) return null;

      const match = (device.interface_data || []).find((item) => {
        const names = [item?.name, item?.description].map((entry) => normalizeTopologyPort(entry));
        return names.includes(normalizedPort);
      });
      if (!match) return null;

      const maxUtilizationPct = [match.bw_in_pct, match.bw_out_pct]
        .filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
        .reduce<number | null>((current, next) => (current == null ? next : Math.max(current, next)), null);

      const errorCount = Number(match.in_errors || 0) + Number(match.out_errors || 0);
      const discardCount = Number(match.in_discards || 0) + Number(match.out_discards || 0);
      const speedValue = Number(match.speed_mbps);
      const speedMbps = Number.isFinite(speedValue) && speedValue > 0
        ? speedValue
        : inferInterfaceSpeedMbps(match.name || port);
      const status = String(match.status || 'unknown').toLowerCase();

      let operationalState: TopologyOperationalState = 'unknown';
      if (status === 'down') {
        operationalState = 'down';
      } else if (match.flapping || errorCount > 0 || discardCount > 0 || (maxUtilizationPct != null && maxUtilizationPct >= 85)) {
        operationalState = 'degraded';
      } else if (status === 'up') {
        operationalState = 'up';
      }

      return {
        name: String(match.name || port),
        speedMbps,
        status,
        maxUtilizationPct,
        errorCount,
        discardCount,
        flapping: Boolean(match.flapping),
        operationalState,
      };
    },
    [],
  );

  const describeTopologyLink = useCallback(
    (link: any, sourceDevice?: Device, targetDevice?: Device): TopologyDecoratedLink => {
      const metadata = parseJsonObject(link.metadata_json);
      const metadataProtocols = Array.isArray(metadata.protocols) ? metadata.protocols : [];
      const discoverySources = String(link.discovery_source || '')
        .split('+')
        .map((item) => item.trim().toLowerCase())
        .filter(Boolean);
      const evidenceSources = Array.from(new Set([...metadataProtocols, ...discoverySources]));
      const sourceInterfaceSnapshot = evaluateTopologyInterfaceSnapshot(sourceDevice, link.source_port_normalized || link.source_port);
      const targetInterfaceSnapshot = evaluateTopologyInterfaceSnapshot(targetDevice, link.target_port_normalized || link.target_port);
      const endpointSpeeds = [
        sourceInterfaceSnapshot?.speedMbps ?? inferInterfaceSpeedMbps(link.source_port || link.source_port_normalized),
        targetInterfaceSnapshot?.speedMbps ?? inferInterfaceSpeedMbps(link.target_port || link.target_port_normalized),
      ]
        .filter((speed): speed is number => typeof speed === 'number' && Number.isFinite(speed) && speed > 0);
      const backendBandwidth = Number(link.aggregation_bandwidth_mbps || link.bandwidth_mbps);
      const bandwidthMbps = Number.isFinite(backendBandwidth) && backendBandwidth > 0
        ? backendBandwidth
        : (endpointSpeeds.length > 0 ? Math.min(...endpointSpeeds) : null);
      let members: Array<Record<string, unknown>> = Array.isArray(link.members) ? link.members : [];
      if (!members.length && typeof link.members_json === 'string') {
        try {
          const parsed = JSON.parse(link.members_json);
          members = Array.isArray(parsed) ? parsed : [];
        } catch {
          members = [];
        }
      }
      const sourceDeviceStatus = String(sourceDevice?.status || 'unknown').toLowerCase();
      const targetDeviceStatus = String(targetDevice?.status || 'unknown').toLowerCase();
      const lastSeenTime = link.last_seen ? new Date(link.last_seen).getTime() : NaN;
      const evidenceTtlMs = Number.isFinite(Number(link.ttl_seconds))
        ? Math.max(60_000, Number(link.ttl_seconds) * 1000)
        : STALE_THRESHOLD_MS;
      const isStale = Number.isFinite(lastSeenTime) && Date.now() - lastSeenTime > evidenceTtlMs;
      const serverOperationalState = String(link.operational_state || link.status || '').toLowerCase();
      const serverMarksStale = serverOperationalState === 'stale';
      const inferred = Boolean(link.inferred || link.is_inferred);

      let operationalState: TopologyOperationalState = 'unknown';
      let operationalSummary = language === 'zh'
        ? '缺少接口遥测，链路状态未知。'
        : 'Link state is unknown because interface telemetry is unavailable.';

      if (inferred) {
        operationalState = 'unknown';
        operationalSummary = language === 'zh'
          ? '这是推断链路，需要等待真实邻居证据确认。'
          : 'This is an inferred adjacency and needs direct neighbor evidence.';
      } else if (sourceDeviceStatus === 'offline' || targetDeviceStatus === 'offline') {
        operationalState = 'down';
        operationalSummary = language === 'zh'
          ? '至少一端设备离线，链路视为中断。'
          : 'At least one endpoint device is offline, so the link is treated as down.';
      } else if (sourceInterfaceSnapshot?.operationalState === 'down' || targetInterfaceSnapshot?.operationalState === 'down') {
        operationalState = 'down';
        operationalSummary = language === 'zh'
          ? '本端或对端接口处于 down。'
          : 'One side of the adjacency reports the interface as down.';
      } else if (serverMarksStale || isStale) {
        operationalState = 'stale';
        operationalSummary = language === 'zh'
          ? '这条链路在最近 30 分钟内没有被新的邻居发现刷新，建议重新触发发现确认当前连通性。'
          : 'This adjacency has not been refreshed by recent discovery within the last 30 minutes. Run discovery again to confirm current connectivity.';
      } else if (serverOperationalState === 'down') {
        operationalState = 'down';
        operationalSummary = language === 'zh'
          ? '服务端链路状态为 down。'
          : 'The server reports this link as down.';
      } else if (
        sourceInterfaceSnapshot?.operationalState === 'up'
        && targetInterfaceSnapshot?.operationalState === 'up'
        && sourceDeviceStatus === 'online'
        && targetDeviceStatus === 'online'
      ) {
        operationalState = 'up';
        operationalSummary = language === 'zh'
          ? '双端接口均为 up，且未发现明显退化信号。'
          : 'Both interfaces are up and no degradation signals were detected.';
      } else if (serverOperationalState === 'up') {
        operationalState = 'up';
        operationalSummary = language === 'zh'
          ? '服务端链路状态为 up。'
          : 'The server reports this link as up.';
      } else if (
        serverOperationalState === 'degraded'
        ||
        sourceDeviceStatus === 'pending'
        || targetDeviceStatus === 'pending'
        || sourceInterfaceSnapshot?.operationalState === 'degraded'
        || targetInterfaceSnapshot?.operationalState === 'degraded'
      ) {
        operationalState = 'degraded';
        operationalSummary = language === 'zh'
          ? '链路可达，但接口存在高利用率、抖动或错误计数。'
          : 'The link is reachable but shows utilization, flapping, or error signals.';
      }

      return {
        ...link,
        inferred,
        operational_state: operationalState,
        operational_summary: operationalSummary,
        evidence_sources: evidenceSources,
        reverse_confirmed: Boolean(metadata.reverse_seen),
        source_interface_snapshot: sourceInterfaceSnapshot,
        target_interface_snapshot: targetInterfaceSnapshot,
        bandwidth_mbps: bandwidthMbps,
        link_kind: String(link.link_kind || 'physical'),
        source_aggregation_name: String(link.source_aggregation_name || ''),
        target_aggregation_name: String(link.target_aggregation_name || ''),
        aggregation_protocol: String(link.aggregation_protocol || ''),
        member_count: Number(link.member_count || 0),
        active_member_count: Number(link.active_member_count || 0),
        aggregation_bandwidth_mbps: Number(link.aggregation_bandwidth_mbps || 0) || null,
        members,
      };
    },
    [evaluateTopologyInterfaceSnapshot, language],
  );

  const formatTopologyInterfaceTelemetry = useCallback((snapshot: TopologyInterfaceSnapshot | null) => {
    if (!snapshot) return language === 'zh' ? '暂无接口遥测' : 'No interface telemetry';
    const segments: string[] = [];
    if (snapshot.status) segments.push(snapshot.status.toUpperCase());
    if (snapshot.maxUtilizationPct != null) segments.push(`${language === 'zh' ? '利用率' : 'Util'} ${Math.round(snapshot.maxUtilizationPct)}%`);
    if (snapshot.errorCount > 0) segments.push(`${language === 'zh' ? '错误' : 'Err'} ${snapshot.errorCount}`);
    if (snapshot.discardCount > 0) segments.push(`${language === 'zh' ? '丢弃' : 'Drop'} ${snapshot.discardCount}`);
    if (snapshot.flapping) segments.push(language === 'zh' ? '抖动' : 'Flap');
    return segments.join(' · ') || (language === 'zh' ? '暂无接口遥测' : 'No interface telemetry');
  }, [language]);

  const {
    topologySiteOptions,
    topologyRoleOptions,
    topologyTagOptions,
    topologyTagCandidateDevices,
    topologyVisibleDevices,
  } = useTopologyVisibleDevices({
    devices,
    topologySearch,
    topologyStatusFilter,
    topologyRoleFilter,
    topologySiteFilter,
    topologyTagFilter,
  });

  const topologyVisibleDeviceIds = useMemo(
    () => new Set(topologyVisibleDevices.map((device) => device.id)),
    [topologyVisibleDevices],
  );

  // -- All decorated links (unfiltered by toggle, used for stats) --
  const topologyAllDecoratedLinks = useMemo<TopologyDecoratedLink[]>(() => {
    const deviceMap = new Map<string, Device>();
    topologyVisibleDevices.forEach((device) => {
      deviceMap.set(device.id, device);
    });
    const managedDecoratedLinks = topologyLinks
      .filter((link) => topologyVisibleDeviceIds.has(link.source_device_id) && topologyVisibleDeviceIds.has(link.target_device_id))
      .map((link) => describeTopologyLink(link, deviceMap.get(link.source_device_id), deviceMap.get(link.target_device_id)));

    return managedDecoratedLinks;
  }, [describeTopologyLink, topologyLinks, topologyVisibleDeviceIds, topologyVisibleDevices]);

  // -- Apply hideStaleLinks toggle filter --
  const topologyVisibleLinks = useMemo<TopologyDecoratedLink[]>(() => {
    return topologyAllDecoratedLinks.filter((link) => {
      if (hideStaleLinks && link.operational_state === 'stale') return false;
      if (topologyLinkStatusFilter !== 'all' && link.operational_state !== topologyLinkStatusFilter) return false;
      if (topologyProtocolFilter !== 'all') {
        const source = String(link.discovery_source || '').toLowerCase();
        if (!source.split('+').includes(topologyProtocolFilter)) return false;
      }
      return true;
    });
  }, [hideStaleLinks, topologyAllDecoratedLinks, topologyLinkStatusFilter, topologyProtocolFilter]);

  // -- Connected device IDs (computed from visible links after stale filter) --
  const topologyConnectedDeviceIds = useMemo(() => {
    const connected = new Set<string>();
    topologyVisibleLinks.forEach((link) => {
      if (link.source_device_id) connected.add(link.source_device_id);
      if (link.target_device_id) connected.add(link.target_device_id);
    });
    return connected;
  }, [topologyVisibleLinks]);

  // -- Apply hideOrphanDevices toggle filter on visible devices --
  const topologyFilteredDevices = useMemo(() => {
    if (!hideOrphanDevices) return topologyVisibleDevices;
    return topologyVisibleDevices.filter((device) => topologyConnectedDeviceIds.has(device.id));
  }, [topologyVisibleDevices, hideOrphanDevices, topologyConnectedDeviceIds]);

  const topologyDeviceLinks = useMemo(() => {
    if (!selectedTopologyDeviceId) return [] as TopologyDecoratedLink[];
    return topologyVisibleLinks
      .filter((link) => link.source_device_id === selectedTopologyDeviceId || link.target_device_id === selectedTopologyDeviceId)
      .sort((left, right) => {
        const leftPeer = left.source_device_id === selectedTopologyDeviceId ? String(left.target_hostname || '') : String(left.source_hostname || '');
        const rightPeer = right.source_device_id === selectedTopologyDeviceId ? String(right.target_hostname || '') : String(right.source_hostname || '');
        return leftPeer.localeCompare(rightPeer);
      });
  }, [selectedTopologyDeviceId, topologyVisibleLinks]);

  // -- Stats: use ALL decorated links (before toggle filtering) so the user sees the real totals --
  const topologyStats = useMemo(() => ({
    nodeCount: topologyFilteredDevices.length,
    linkCount: topologyVisibleLinks.length,
    siteCount: new Set(topologyFilteredDevices.map((device) => String(device.site_id || device.site || '').trim()).filter(Boolean)).size,
    atRiskCount: topologyFilteredDevices.filter((device) => device.status !== 'online' || device.health_status === 'critical' || (device.open_alert_count || 0) > 0).length,
    orphanCount: topologyFilteredDevices.filter((device) => !topologyConnectedDeviceIds.has(device.id)).length,
  }), [topologyConnectedDeviceIds, topologyFilteredDevices, topologyVisibleLinks.length]);

  const topologyLinkStats = useMemo(() => ({
    up: topologyVisibleLinks.filter((link) => link.operational_state === 'up').length,
    degraded: topologyVisibleLinks.filter((link) => link.operational_state === 'degraded').length,
    down: topologyVisibleLinks.filter((link) => link.operational_state === 'down').length,
    stale: topologyVisibleLinks.filter((link) => link.operational_state === 'stale').length,
    multiSource: topologyVisibleLinks.filter((link) => link.evidence_sources.length > 1 || link.reverse_confirmed || Number(link.evidence_count || 0) > 1).length,
  }), [topologyVisibleLinks]);

  const selectedTopologyDevice = useMemo(
    () => topologyFilteredDevices.find((device) => device.id === selectedTopologyDeviceId) || null,
    [selectedTopologyDeviceId, topologyFilteredDevices],
  );

  const selectedTopologyLink = useMemo<TopologyDecoratedLink | null>(
    () => topologyVisibleLinks.find((link) => (link.link_key || link.id) === selectedTopologyLinkKey) || null,
    [selectedTopologyLinkKey, topologyVisibleLinks],
  );

  const topologyNeighborIds = useMemo(() => {
    if (!selectedTopologyDeviceId) return new Set<string>();
    const neighbors = new Set<string>();
    topologyVisibleLinks.forEach((link) => {
      if (link.source_device_id === selectedTopologyDeviceId && link.target_device_id) neighbors.add(link.target_device_id);
      if (link.target_device_id === selectedTopologyDeviceId && link.source_device_id) neighbors.add(link.source_device_id);
    });
    return neighbors;
  }, [selectedTopologyDeviceId, topologyVisibleLinks]);

  const topologyNeighborDevices = useMemo(
    () => topologyFilteredDevices
      .filter((device) => topologyNeighborIds.has(device.id))
      .sort((left, right) => left.hostname.localeCompare(right.hostname)),
    [topologyNeighborIds, topologyFilteredDevices],
  );

  const topologyOrphanDevices = useMemo(
    () => topologyFilteredDevices
      .filter((device) => !topologyConnectedDeviceIds.has(device.id))
      .sort((left, right) => left.hostname.localeCompare(right.hostname)),
    [topologyConnectedDeviceIds, topologyFilteredDevices],
  );

  const topologyPriorityDevices = useMemo(
    () => [...topologyFilteredDevices]
      .sort((left, right) => {
        const leftScore = (left.status !== 'online' ? 100 : 0) + (left.critical_open_alerts || 0) * 10 + (left.open_alert_count || 0);
        const rightScore = (right.status !== 'online' ? 100 : 0) + (right.critical_open_alerts || 0) * 10 + (right.open_alert_count || 0);
        return rightScore - leftScore;
      })
      .slice(0, 5),
    [topologyFilteredDevices],
  );

  useTopologySelectionSync({
    selectedTopologyDeviceId,
    setSelectedTopologyDeviceId,
    selectedTopologyLinkKey,
    setSelectedTopologyLinkKey,
    topologyVisibleDevices,
    topologyDeviceLinks,
  });

  const handleExportMap = useCallback(async () => {
    if (!topologyRef.current) return;
    const topologySvg = topologyRef.current.querySelector('svg.topology-graph-svg') as SVGSVGElement | null;
    if (!topologySvg) {
      showToast('Topology canvas is not ready for export', 'error');
      return;
    }
    showToast('Preparing topology map for export...', 'info');
    let graphRoot: SVGGElement | undefined;
    let exportOverlay: SVGGElement | null = null;
    let originalTransform: string | null = null;
    let originalViewBox: string | null = null;
    try {
      await new Promise((resolve) => setTimeout(resolve, 500));
      const viewBox = topologySvg.viewBox.baseVal;
      const viewportWidth = Math.max(1, Math.round(viewBox.width || topologySvg.clientWidth || 1));
      const viewportHeight = Math.max(1, Math.round(viewBox.height || topologySvg.clientHeight || 1));
      originalViewBox = topologySvg.getAttribute('viewBox');

      // Export from the original graph coordinate space. Temporarily remove
      // the live root transform so the browser paints the same SVG reliably;
      // restore it immediately after the image is generated.
      graphRoot = Array.from(topologySvg.children)
        .find((child) => child.tagName.toLowerCase() === 'g') as SVGGElement | undefined;
      originalTransform = graphRoot?.getAttribute('transform') || null;
      graphRoot?.removeAttribute('transform');

      // The live canvas is intentionally roomy for panning. Crop the export
      // to the actual graph bounds so a one-row topology does not produce a
      // very tall image with large empty regions.
      let exportX = 0;
      let exportY = 0;
      let width = viewportWidth;
      let height = viewportHeight;
      try {
        const bounds = graphRoot?.getBBox?.();
        if (bounds && bounds.width > 0 && bounds.height > 0) {
          const padding = 36;
          exportX = Math.floor(bounds.x - padding);
          exportY = Math.floor(bounds.y - padding);
          width = Math.ceil(bounds.width + padding * 2);
          height = Math.ceil(bounds.height + padding * 2);
          topologySvg.setAttribute('viewBox', `${exportX} ${exportY} ${width} ${height}`);
        }
      } catch {
        // Fall back to the full canvas when getBBox is unavailable.
      }

      // The bandwidth legend is an HTML overlay, while export intentionally
      // renders the SVG only. The graph already renders the authoritative
      // site badge using deduplicated drawable links, so do not add a second
      // summary badge here.
      const svgNs = 'http://www.w3.org/2000/svg';
      const makeSvg = (tag: string, attrs: Record<string, string>, text?: string) => {
        const element = document.createElementNS(svgNs, tag);
        Object.entries(attrs).forEach(([key, value]) => element.setAttribute(key, value));
        if (text != null) element.textContent = text;
        return element;
      };
      exportOverlay = makeSvg('g', { class: 'topology-export-overlay', 'pointer-events': 'none' }) as SVGGElement;
      const legendWidth = Math.max(390, 76 + EXPORT_BANDWIDTH_TIERS.length * 61);
      const legendHeight = 34;
      const legendGroup = makeSvg('g', { transform: `translate(${exportX + 16}, ${exportY + Math.max(16, height - legendHeight - 16)})` });
      legendGroup.appendChild(makeSvg('rect', {
        x: '0', y: '0', width: String(Math.min(legendWidth, width - 32)), height: String(legendHeight), rx: '10',
        fill: '#ffffff', 'fill-opacity': '0.94', stroke: '#cbd5e1', 'stroke-opacity': '0.9',
      }));
      legendGroup.appendChild(makeSvg('text', {
        x: '12', y: '21', fill: '#475569', 'font-family': 'Segoe UI, Microsoft YaHei, sans-serif',
        'font-size': '10', 'font-weight': '700',
      }, 'Bandwidth'));
      const legendStartX = 76;
      const legendStep = 61;
      EXPORT_BANDWIDTH_TIERS.forEach((tier, index) => {
        const x = legendStartX + index * legendStep;
        if (x > width - 50) return;
        legendGroup.appendChild(makeSvg('line', {
          x1: String(x), y1: '17', x2: String(x + 18), y2: '17',
          stroke: tier.color, 'stroke-width': tier.label === 'Unknown' ? '2' : '3',
          'stroke-linecap': 'round',
        }));
        legendGroup.appendChild(makeSvg('text', {
          x: String(x + 23), y: '21', fill: '#475569', 'font-family': 'Segoe UI, Microsoft YaHei, sans-serif',
          'font-size': '9', 'font-weight': '600',
        }, tier.label));
      });
      exportOverlay.appendChild(legendGroup);
      topologySvg.appendChild(exportOverlay);

      const exportPixelRatio = getTopologyExportPixelRatio(width, height);
      const dataUrl = await htmlToImage.toPng(topologySvg as unknown as HTMLElement, {
        backgroundColor: '#ffffff',
        cacheBust: true,
        width,
        height,
        canvasWidth: width,
        canvasHeight: height,
        // Render a 4K-class bitmap for readable topology labels while keeping
        // a safety cap for unusually large canvases.
        pixelRatio: exportPixelRatio,
        style: {
          backgroundColor: '#ffffff',
          transform: 'scale(1)',
          transformOrigin: 'top left',
        },
      });
      const selectedSite = topologySites.find((site) => site.site_id === topologySiteFilter);
      const exportSiteLabel = topologySiteFilter === 'all'
        ? (topologySites.length === 1 ? topologySites[0].site_name : 'all-sites')
        : (selectedSite?.site_name || topologySiteFilter);
      const link = document.createElement('a');
      link.download = buildTopologyExportFilename(exportSiteLabel, 'png');
      link.href = dataUrl;
      link.click();
      showToast('Topology map exported successfully', 'success');
    } catch (error) {
      console.error('Export error:', error);
      showToast('Failed to export map. Please try again.', 'error');
    } finally {
      exportOverlay?.remove();
      if (graphRoot) {
        if (originalTransform) graphRoot.setAttribute('transform', originalTransform);
        else graphRoot.removeAttribute('transform');
      }
      if (originalViewBox) topologySvg.setAttribute('viewBox', originalViewBox);
    }
  }, [showToast, topologySiteFilter, topologySites]);

  const handleTriggerDiscovery = useCallback(async () => {
    setTopologyDiscoveryRunning(true);
    setTopologyDiscoveryDevices([]);
    try {
      const body = topologySiteFilter === 'all'
        ? { scope: 'full', site_id: '', device_ids: [] }
        : { scope: 'site', site_id: topologySiteFilter, device_ids: [] };
      const response = await fetch('/api/topology/discover', {
        method: 'POST',
        headers: {
          ...topologyAuthHeaders(),
          'Content-Type': 'application/json',
          'Idempotency-Key': `topology-discovery-${createTopologyIdempotencyKey()}`,
        },
        body: JSON.stringify(body),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload?.run_id) {
        throw new Error(topologyApiErrorMessage(payload, 'topology_discovery_start_failed'));
      }
      setTopologyDiscoveryRunId(String(payload.run_id));
      setTopologyDiscoveryProgress({
        id: String(payload.run_id),
        status: 'pending',
        total_devices: Number(payload.device_count || 0),
        processed_devices: 0,
        success_devices: 0,
        failed_devices: 0,
        running_devices: 0,
        pending_devices: Number(payload.device_count || 0),
        progress_percent: 0,
      });
      showToast(language === 'zh' ? '拓扑发现任务已启动，可实时查看进度。' : 'Topology discovery started; live progress is available.', 'success');
    } catch (error) {
      setTopologyDiscoveryRunning(false);
      showToast(
        language === 'zh'
          ? `拓扑发现启动失败：${error instanceof Error ? error.message : '连接错误'}`
          : `Failed to start topology discovery: ${error instanceof Error ? error.message : 'connection error'}`,
        'error',
      );
    }
  }, [language, showToast, topologySiteFilter]);

  React.useEffect(() => {
    if (!topologyDiscoveryRunId) return;
    let active = true;
    let timer: number | null = null;
    const terminalStates = new Set(['completed', 'partial', 'failed', 'cancelled']);

    const poll = async () => {
      try {
        const response = await fetch(`/api/topology/discovery-runs/${topologyDiscoveryRunId}`, {
          headers: topologyAuthHeaders(),
        });
        if (!response.ok) throw new Error(`discovery_progress_${response.status}`);
        const payload = await response.json();
        if (!active) return;
        const run = payload?.run as TopologyDiscoveryProgress;
        setTopologyDataError('');
        setTopologyDiscoveryProgress(run);
        setTopologyDiscoveryDevices(Array.isArray(payload?.devices) ? payload.devices : []);
        if (run && terminalStates.has(run.status)) {
          setTopologyDiscoveryRunning(false);
          setTopologyDiscoveryRunId(null);
          await refreshDevices?.();
          await refreshTopologyData();
          showToast(
            language === 'zh'
              ? `拓扑发现${run.status === 'completed' ? '完成' : '结束'}：成功 ${run.success_devices || 0}，失败 ${run.failed_devices || 0}`
              : `Topology discovery ${run.status}: ${run.success_devices || 0} succeeded, ${run.failed_devices || 0} failed`,
            run.status === 'failed' ? 'error' : (run.status === 'partial' || run.status === 'cancelled' ? 'info' : 'success'),
          );
          return;
        }
      } catch (error) {
        if (active) setTopologyDataError(error instanceof Error ? error.message : 'discovery_progress_failed');
      }
      if (active) timer = window.setTimeout(poll, 1500);
    };

    void poll();
    return () => {
      active = false;
      if (timer != null) window.clearTimeout(timer);
    };
  }, [language, refreshDevices, refreshTopologyData, showToast, topologyDiscoveryRunId]);

  const handleCancelDiscovery = useCallback(async () => {
    const runId = topologyDiscoveryRunId || topologyDiscoveryProgress?.id;
    if (!runId || !topologyDiscoveryRunning) return;
    const response = await fetch(`/api/topology/discovery-runs/${runId}/cancel`, {
      method: 'POST',
      headers: topologyAuthHeaders(),
    });
    if (!response.ok) {
      showToast(language === 'zh' ? '取消拓扑发现失败' : 'Failed to cancel topology discovery', 'error');
    }
  }, [language, showToast, topologyDiscoveryProgress?.id, topologyDiscoveryRunId, topologyDiscoveryRunning]);

  return {
    // filters & selection
    topologySearch,
    setTopologySearch,
    topologyStatusFilter,
    setTopologyStatusFilter,
    topologyRoleFilter,
    setTopologyRoleFilter,
    topologySiteFilter,
    setTopologySiteFilter,
    topologyTagFilter,
    setTopologyTagFilter,
    topologyLinkStatusFilter,
    setTopologyLinkStatusFilter,
    topologyProtocolFilter,
    setTopologyProtocolFilter,
    selectedTopologyDeviceId,
    setSelectedTopologyDeviceId,
    selectedTopologyLinkKey,
    setSelectedTopologyLinkKey,
    topologyDiscoveryRunning,
    topologyDiscoveryProgress,
    topologyDiscoveryDevices,
    topologySites,
    topologyDataError,
    topologyRef,
    // canvas toggles
    hideStaleLinks,
    setHideStaleLinks,
    hideOrphanDevices,
    setHideOrphanDevices,
    // derived
    topologySiteOptions,
    topologyRoleOptions,
    topologyTagOptions,
    topologyTagCandidateDevices,
    topologyVisibleDevices: topologyFilteredDevices,
    topologyVisibleLinks,
    topologyDeviceLinks,
    topologyStats,
    topologyLinkStats,
    selectedTopologyDevice,
    selectedTopologyLink,
    topologyNeighborDevices,
    topologyOrphanDevices,
    topologyPriorityDevices,
    // formatters / helpers
    formatTopologyInterfaceTelemetry,
    // actions
    handleExportMap,
    handleTriggerDiscovery,
    handleCancelDiscovery,
    refreshTopologyData,
  };
};
