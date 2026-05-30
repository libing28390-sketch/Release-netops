import { useCallback, useMemo } from 'react';
import type { Device } from '../types';
import type { TopologyOperationalState } from '../utils/topologyCore';

interface TopologyInterfaceSnapshot {
  name: string;
  status: string;
  maxUtilizationPct: number | null;
  errorCount: number;
  discardCount: number;
  flapping: boolean;
  operationalState: TopologyOperationalState;
}

interface TopologyDecoratedLink {
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
}

interface UseTopologyDerivedDataParams {
  devices: Device[];
  topologyLinks: any[];
  topologyUnmanagedLinks: any[];
  topologyVisibleDevices: Device[];
  selectedTopologyDeviceId: string | null;
  selectedTopologyLinkKey: string | null;
  language: string;
  parseJsonObject: (value: any) => Record<string, any>;
  normalizeTopologyPort: (value?: string) => string;
}

export const useTopologyDerivedData = ({
  devices,
  topologyLinks,
  topologyUnmanagedLinks,
  topologyVisibleDevices,
  selectedTopologyDeviceId,
  selectedTopologyLinkKey,
  language,
  parseJsonObject,
  normalizeTopologyPort,
}: UseTopologyDerivedDataParams) => {
  const evaluateTopologyInterfaceSnapshot = useCallback((device: Device | null | undefined, port?: string): TopologyInterfaceSnapshot | null => {
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
    if (status === 'down') operationalState = 'down';
    else if (match.flapping || errorCount > 0 || discardCount > 0 || (maxUtilizationPct != null && maxUtilizationPct >= 85)) operationalState = 'degraded';
    else if (status === 'up') operationalState = 'up';

    return {
      name: String(match.name || port),
      status,
      maxUtilizationPct,
      errorCount,
      discardCount,
      flapping: Boolean(match.flapping),
      operationalState,
    };
  }, [normalizeTopologyPort]);

  const describeTopologyLink = useCallback((link: any, sourceDevice?: Device, targetDevice?: Device): TopologyDecoratedLink => {
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
    const staleThresholdMs = 30 * 60 * 1000;
    const isStale = Number.isFinite(lastSeenTime) && (Date.now() - lastSeenTime > staleThresholdMs);

    let operationalState: TopologyOperationalState = 'unknown';
    let operationalSummary = language === 'zh'
      ? '链路状态未知，缺少接口遥测'
      : 'Link state is unknown because interface telemetry is unavailable.';

    if (link.inferred) {
      operationalState = 'unknown';
      operationalSummary = language === 'zh'
        ? '该链路为推断结果，需要真实邻居证据确认'
        : 'This is an inferred adjacency and needs direct neighbor evidence.';
    } else if (sourceDeviceStatus === 'offline' || targetDeviceStatus === 'offline') {
      operationalState = 'down';
      operationalSummary = language === 'zh'
        ? '至少一端设备离线，链路视为中断'
        : 'At least one endpoint device is offline, so the link is treated as down.';
    } else if (sourceInterfaceSnapshot?.operationalState === 'down' || targetInterfaceSnapshot?.operationalState === 'down') {
      operationalState = 'down';
      operationalSummary = language === 'zh'
        ? '链路一端接口 down'
        : 'One side of the adjacency reports the interface as down.';
    } else if (
      sourceInterfaceSnapshot?.operationalState === 'up'
      && targetInterfaceSnapshot?.operationalState === 'up'
      && sourceDeviceStatus === 'online'
      && targetDeviceStatus === 'online'
    ) {
      operationalState = 'up';
      operationalSummary = language === 'zh'
        ? '链路双端接口均为 up'
        : 'Both interfaces are up and no degradation signals were detected.';
    } else if (isStale) {
      operationalState = 'stale';
      operationalSummary = language === 'zh'
        ? '该链路最近 30 分钟未刷新，建议重新发现确认连通性'
        : 'This adjacency has not been refreshed by recent discovery within the last 30 minutes. Run discovery again to confirm current connectivity.';
    } else if (
      sourceDeviceStatus === 'pending'
      || targetDeviceStatus === 'pending'
      || sourceInterfaceSnapshot?.operationalState === 'degraded'
      || targetInterfaceSnapshot?.operationalState === 'degraded'
    ) {
      operationalState = 'degraded';
      operationalSummary = language === 'zh'
        ? '链路可达，但存在利用率/抖动/错误等退化信号'
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
  }, [evaluateTopologyInterfaceSnapshot, language, parseJsonObject]);

  const formatTopologyInterfaceTelemetry = useCallback((snapshot: TopologyInterfaceSnapshot | null) => {
    if (!snapshot) return language === 'zh' ? '暂无接口遥测' : 'No interface telemetry';
    const segments: string[] = [];
    if (snapshot.status) segments.push(snapshot.status.toUpperCase());
    if (snapshot.maxUtilizationPct != null) segments.push(`${language === 'zh' ? '利用率' : 'Util'} ${Math.round(snapshot.maxUtilizationPct)}%`);
    if (snapshot.errorCount > 0) segments.push(`${language === 'zh' ? '错误' : 'Err'} ${snapshot.errorCount}`);
    if (snapshot.discardCount > 0) segments.push(`${language === 'zh' ? '丢弃' : 'Drop'} ${snapshot.discardCount}`);
    if (snapshot.flapping) segments.push(language === 'zh' ? '抖动' : 'Flap');
    return segments.join(' / ') || (language === 'zh' ? '暂无接口遥测' : 'No interface telemetry');
  }, [language]);

  const topologyVisibleDeviceIds = useMemo(
    () => new Set(topologyVisibleDevices.map((device) => device.id)),
    [topologyVisibleDevices],
  );

  const topologyVisibleLinks = useMemo(() => {
    const deviceMap = new Map<string, Device>();
    topologyVisibleDevices.forEach((device) => {
      deviceMap.set(device.id, device);
    });
    const managedDecoratedLinks = topologyLinks
      .filter((link) => topologyVisibleDeviceIds.has(link.source_device_id) && topologyVisibleDeviceIds.has(link.target_device_id))
      .map((link) => describeTopologyLink(link, deviceMap.get(link.source_device_id), deviceMap.get(link.target_device_id)));

    const unmanagedDecoratedLinks = topologyUnmanagedLinks
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

  const topologyDeviceLinks = useMemo(() => {
    if (!selectedTopologyDeviceId) return [] as any[];
    return topologyVisibleLinks
      .filter((link) => link.source_device_id === selectedTopologyDeviceId || link.target_device_id === selectedTopologyDeviceId)
      .sort((left, right) => {
        const leftPeer = left.source_device_id === selectedTopologyDeviceId ? String(left.target_hostname || '') : String(left.source_hostname || '');
        const rightPeer = right.source_device_id === selectedTopologyDeviceId ? String(right.target_hostname || '') : String(right.source_hostname || '');
        return leftPeer.localeCompare(rightPeer);
      });
  }, [selectedTopologyDeviceId, topologyVisibleLinks]);

  const topologyConnectedDeviceIds = useMemo(() => {
    const connected = new Set<string>();
    topologyVisibleLinks.forEach((link) => {
      if (link.source_device_id) connected.add(link.source_device_id);
      if (link.target_device_id) connected.add(link.target_device_id);
    });
    return connected;
  }, [topologyVisibleLinks]);

  const topologyStats = useMemo(() => ({
    nodeCount: topologyVisibleDevices.length,
    linkCount: topologyVisibleLinks.length,
    siteCount: new Set(topologyVisibleDevices.map((device) => String(device.site || '').trim()).filter(Boolean)).size,
    atRiskCount: topologyVisibleDevices.filter((device) => device.status !== 'online' || device.health_status === 'critical' || (device.open_alert_count || 0) > 0).length,
    orphanCount: topologyVisibleDevices.filter((device) => !topologyConnectedDeviceIds.has(device.id)).length,
  }), [topologyConnectedDeviceIds, topologyVisibleDevices, topologyVisibleLinks.length]);

  const topologyLinkStats = useMemo(() => ({
    up: topologyVisibleLinks.filter((link: TopologyDecoratedLink) => link.operational_state === 'up').length,
    degraded: topologyVisibleLinks.filter((link: TopologyDecoratedLink) => link.operational_state === 'degraded').length,
    down: topologyVisibleLinks.filter((link: TopologyDecoratedLink) => link.operational_state === 'down').length,
    stale: topologyVisibleLinks.filter((link: TopologyDecoratedLink) => link.operational_state === 'stale').length,
    multiSource: topologyVisibleLinks.filter((link: TopologyDecoratedLink) => link.evidence_sources.length > 1 || link.reverse_confirmed || Number(link.evidence_count || 0) > 1).length,
  }), [topologyVisibleLinks]);

  const selectedTopologyDevice = useMemo(
    () => topologyVisibleDevices.find((device) => device.id === selectedTopologyDeviceId) || null,
    [selectedTopologyDeviceId, topologyVisibleDevices],
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
    () => topologyVisibleDevices.filter((device) => topologyNeighborIds.has(device.id)).sort((left, right) => left.hostname.localeCompare(right.hostname)),
    [topologyNeighborIds, topologyVisibleDevices],
  );

  const topologyOrphanDevices = useMemo(
    () => topologyVisibleDevices.filter((device) => !topologyConnectedDeviceIds.has(device.id)).sort((left, right) => left.hostname.localeCompare(right.hostname)),
    [topologyConnectedDeviceIds, topologyVisibleDevices],
  );

  const topologyPriorityDevices = useMemo(
    () => [...topologyVisibleDevices]
      .sort((left, right) => {
        const leftScore = (left.status !== 'online' ? 100 : 0) + (left.critical_open_alerts || 0) * 10 + (left.open_alert_count || 0);
        const rightScore = (right.status !== 'online' ? 100 : 0) + (right.critical_open_alerts || 0) * 10 + (right.open_alert_count || 0);
        return rightScore - leftScore;
      })
      .slice(0, 5),
    [topologyVisibleDevices],
  );

  return {
    formatTopologyInterfaceTelemetry,
    topologyVisibleLinks,
    topologyDeviceLinks,
    topologyConnectedDeviceIds,
    topologyStats,
    topologyLinkStats,
    selectedTopologyDevice,
    selectedTopologyLink,
    topologyNeighborDevices,
    topologyOrphanDevices,
    topologyPriorityDevices,
  };
};
