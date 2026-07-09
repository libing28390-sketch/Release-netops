import React, { useCallback, useMemo, useState } from 'react';
import * as htmlToImage from 'html-to-image';
import type { Device } from '../types';
import type { Language } from '../i18n.tsx';
import { parseJsonObject } from '../components/shared';
import {
  normalizeTopologyPort,
  type TopologyOperationalState,
} from '../utils/topologyCore';
import { useTopologyVisibleDevices } from './useTopologyVisibleDevices';
import { useTopologySelectionSync } from './useTopologySelectionSync';

export type TopologyInterfaceSnapshot = {
  name: string;
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
  inferred?: boolean;
  status?: string;
  operational_state: TopologyOperationalState;
  operational_summary: string;
  evidence_sources: string[];
  reverse_confirmed: boolean;
  source_interface_snapshot: TopologyInterfaceSnapshot | null;
  target_interface_snapshot: TopologyInterfaceSnapshot | null;
  is_unmanaged?: boolean;
};

const STALE_THRESHOLD_MS = 30 * 60 * 1000;

interface UseTopologyArgs {
  devices: Device[];
  language: Language;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
}

export const useTopology = ({ devices, language, showToast }: UseTopologyArgs) => {
  const [topologyLinks, setTopologyLinks] = useState<any[]>([]);
  const [topologyUnmanagedNodes, setTopologyUnmanagedNodes] = useState<any[]>([]);
  const [topologyUnmanagedLinks, setTopologyUnmanagedLinks] = useState<any[]>([]);
  const [topologySearch, setTopologySearch] = useState('');
  const [topologyStatusFilter, setTopologyStatusFilter] = useState<'all' | 'online' | 'offline' | 'pending'>('all');
  const [topologyRoleFilter, setTopologyRoleFilter] = useState('all');
  const [topologySiteFilter, setTopologySiteFilter] = useState('all');
  const [selectedTopologyDeviceId, setSelectedTopologyDeviceId] = useState<string | null>(null);
  const [selectedTopologyLinkKey, setSelectedTopologyLinkKey] = useState<string | null>(null);
  const [topologyDiscoveryRunning, setTopologyDiscoveryRunning] = useState(false);
  const [hideStaleLinks, setHideStaleLinks] = useState(false);
  const [hideOrphanDevices, setHideOrphanDevices] = useState(false);
  const topologyRef = React.useRef<HTMLDivElement>(null);

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
      const sourceDeviceStatus = String(sourceDevice?.status || 'unknown').toLowerCase();
      const targetDeviceStatus = String(targetDevice?.status || 'unknown').toLowerCase();
      const lastSeenTime = link.last_seen ? new Date(link.last_seen).getTime() : NaN;
      const isStale = Number.isFinite(lastSeenTime) && Date.now() - lastSeenTime > STALE_THRESHOLD_MS;

      let operationalState: TopologyOperationalState = 'unknown';
      let operationalSummary = language === 'zh'
        ? '缺少接口遥测，链路状态未知。'
        : 'Link state is unknown because interface telemetry is unavailable.';

      if (link.inferred) {
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
      } else if (isStale) {
        operationalState = 'stale';
        operationalSummary = language === 'zh'
          ? '这条链路在最近 30 分钟内没有被新的邻居发现刷新，建议重新触发发现确认当前连通性。'
          : 'This adjacency has not been refreshed by recent discovery within the last 30 minutes. Run discovery again to confirm current connectivity.';
      } else if (
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
        operational_state: operationalState,
        operational_summary: operationalSummary,
        evidence_sources: evidenceSources,
        reverse_confirmed: Boolean(metadata.reverse_seen),
        source_interface_snapshot: sourceInterfaceSnapshot,
        target_interface_snapshot: targetInterfaceSnapshot,
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
    topologyVisibleDevices,
  } = useTopologyVisibleDevices({
    devices,
    topologySearch,
    topologyStatusFilter,
    topologyRoleFilter,
    topologySiteFilter,
    topologyUnmanagedNodes,
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

    const unmanagedDecoratedLinks: TopologyDecoratedLink[] = topologyUnmanagedLinks
      .filter((link: any) => topologyVisibleDeviceIds.has(link.source_device_id) && topologyVisibleDeviceIds.has(link.target_device_id))
      .map((link: any) => ({
        ...link,
        operational_state: 'unknown' as TopologyOperationalState,
        operational_summary: '',
        evidence_sources: [link.discovery_source || 'lldp'],
        reverse_confirmed: false,
        source_interface_snapshot: null,
        target_interface_snapshot: null,
        is_unmanaged: true,
      }));

    return [...managedDecoratedLinks, ...unmanagedDecoratedLinks];
  }, [describeTopologyLink, topologyLinks, topologyUnmanagedLinks, topologyVisibleDeviceIds, topologyVisibleDevices]);

  // -- Apply hideStaleLinks toggle filter --
  const topologyVisibleLinks = useMemo<TopologyDecoratedLink[]>(() => {
    if (!hideStaleLinks) return topologyAllDecoratedLinks;
    return topologyAllDecoratedLinks.filter((link) => link.operational_state !== 'stale');
  }, [topologyAllDecoratedLinks, hideStaleLinks]);

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
    siteCount: new Set(topologyFilteredDevices.map((device) => String(device.site || '').trim()).filter(Boolean)).size,
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
    showToast('Preparing topology map for export...', 'info');
    try {
      await new Promise((resolve) => setTimeout(resolve, 500));
      const dataUrl = await htmlToImage.toPng(topologyRef.current, {
        backgroundColor: '#ffffff',
        pixelRatio: 2,
        style: {
          transform: 'scale(1)',
          transformOrigin: 'top left',
        },
      });
      const link = document.createElement('a');
      const ts = new Date().toISOString().replace(/[-:]/g, '').replace('T', '_').slice(0, 15);
      link.download = `network-topology-${ts}.png`;
      link.href = dataUrl;
      link.click();
      showToast('Topology map exported successfully', 'success');
    } catch (error) {
      console.error('Export error:', error);
      showToast('Failed to export map. Please try again.', 'error');
    }
  }, [showToast]);

  const handleTriggerDiscovery = useCallback(async () => {
    setTopologyDiscoveryRunning(true);
    try {
      const response = await fetch('/api/topology/discover', { method: 'POST' });
      if (response.ok) {
        showToast(
          language === 'zh' ? '已启动一次手动拓扑刷新，稍后自动更新链路状态' : 'Manual topology refresh started. Link state will update shortly.',
          'success',
        );
        window.setTimeout(async () => {
          try {
            const linksResponse = await fetch('/api/topology/links');
            if (linksResponse.ok) {
              const linksPayload = await linksResponse.json();
              if (linksPayload && typeof linksPayload === 'object' && !Array.isArray(linksPayload)) {
                setTopologyLinks(Array.isArray(linksPayload.links) ? linksPayload.links : []);
                setTopologyUnmanagedNodes(Array.isArray(linksPayload.unmanaged_nodes) ? linksPayload.unmanaged_nodes : []);
                setTopologyUnmanagedLinks(Array.isArray(linksPayload.unmanaged_links) ? linksPayload.unmanaged_links : []);
              } else {
                setTopologyLinks(Array.isArray(linksPayload) ? linksPayload : []);
                setTopologyUnmanagedNodes([]);
                setTopologyUnmanagedLinks([]);
              }
            }
          } catch {
            // ignore delayed refresh errors
          }
        }, 2500);
      } else {
        showToast(language === 'zh' ? '拓扑发现启动失败' : 'Failed to start topology discovery', 'error');
      }
    } catch {
      showToast(language === 'zh' ? '连接失败，无法触发拓扑发现' : 'Connection error', 'error');
    } finally {
      setTopologyDiscoveryRunning(false);
    }
  }, [language, showToast]);

  return {
    // raw data setters (consumed by App.fetchSharedData)
    setTopologyLinks,
    setTopologyUnmanagedNodes,
    setTopologyUnmanagedLinks,
    // filters & selection
    topologySearch,
    setTopologySearch,
    topologyStatusFilter,
    setTopologyStatusFilter,
    topologyRoleFilter,
    setTopologyRoleFilter,
    topologySiteFilter,
    setTopologySiteFilter,
    selectedTopologyDeviceId,
    setSelectedTopologyDeviceId,
    selectedTopologyLinkKey,
    setSelectedTopologyLinkKey,
    topologyDiscoveryRunning,
    topologyRef,
    // canvas toggles
    hideStaleLinks,
    setHideStaleLinks,
    hideOrphanDevices,
    setHideOrphanDevices,
    // derived
    topologySiteOptions,
    topologyRoleOptions,
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
  };
};
