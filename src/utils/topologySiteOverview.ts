export interface TopologySiteRecord {
  site_id?: string | null;
  site_code?: string | null;
  site_name?: string | null;
  site?: string | null;
  link_count?: number | null;
  offline_devices?: number | null;
  orphan_devices?: number | null;
  stale_links?: number | null;
}

export interface TopologySiteDeviceRecord {
  id: string;
  status?: string | null;
  site_id?: string | null;
  site_code?: string | null;
  site_name?: string | null;
  site?: string | null;
}

export interface TopologySiteLinkRecord {
  source_device_id?: string | null;
  target_device_id?: string | null;
  operational_state?: string | null;
}

export interface TopologySiteOverviewItem {
  id: string;
  name: string;
  deviceCount: number;
  linkCount: number;
  orphanCount: number;
  offlineCount: number;
  staleCount: number;
}

export interface TopologySiteConnection {
  source: string;
  target: string;
  count: number;
  down: number;
}

export interface TopologySiteOverviewResult {
  sites: TopologySiteOverviewItem[];
  connections: TopologySiteConnection[];
  siteName: (id: string) => string;
}

const firstNonEmpty = (...values: unknown[]): string => {
  for (const value of values) {
    const normalized = String(value ?? '').trim();
    if (normalized) return normalized;
  }
  return '';
};

/** Return the same stable key for site summaries and the currently filtered devices. */
export const getTopologySiteKey = (record: Partial<TopologySiteRecord>): string => (
  firstNonEmpty(record.site_id, record.site_code, record.site_name, record.site) || 'unassigned'
);

export const buildTopologySiteOverview = (
  siteRecords: TopologySiteRecord[],
  devices: TopologySiteDeviceRecord[],
  links: TopologySiteLinkRecord[],
  unassignedSiteName = 'Unassigned site',
): TopologySiteOverviewResult => {
  const siteMap = new Map<string, TopologySiteOverviewItem>();

  siteRecords.forEach((site) => {
    const id = getTopologySiteKey(site);
    siteMap.set(id, {
      id,
      name: firstNonEmpty(site.site_name, site.site_code, id) || unassignedSiteName,
      deviceCount: 0,
      linkCount: 0,
      orphanCount: 0,
      offlineCount: 0,
      staleCount: 0,
    });
  });

  const deviceSite = new Map<string, string>();
  devices.forEach((device) => {
    const deviceId = String(device.id || '').trim();
    if (!deviceId) return;

    const siteId = getTopologySiteKey(device);
    deviceSite.set(deviceId, siteId);
    const current = siteMap.get(siteId) || {
      id: siteId,
      name: siteId === 'unassigned' ? unassignedSiteName : siteId,
      deviceCount: 0,
      linkCount: 0,
      orphanCount: 0,
      offlineCount: 0,
      staleCount: 0,
    };
    current.deviceCount += 1;
    if (String(device.status || '').trim().toLowerCase() === 'offline') current.offlineCount += 1;
    siteMap.set(siteId, current);
  });

  const connectedDeviceIds = new Set<string>();
  const connectionMap = new Map<string, TopologySiteConnection>();
  links.forEach((link) => {
    const sourceDeviceId = String(link.source_device_id || '').trim();
    const targetDeviceId = String(link.target_device_id || '').trim();
    const sourceSiteId = deviceSite.get(sourceDeviceId);
    const targetSiteId = deviceSite.get(targetDeviceId);
    if (!sourceSiteId || !targetSiteId) return;

    connectedDeviceIds.add(sourceDeviceId);
    connectedDeviceIds.add(targetDeviceId);

    const siteIds = new Set([sourceSiteId, targetSiteId]);
    siteIds.forEach((siteId) => {
      const site = siteMap.get(siteId);
      if (!site) return;
      site.linkCount += 1;
      if (String(link.operational_state || '').trim().toLowerCase() === 'stale') site.staleCount += 1;
    });

    if (sourceSiteId === targetSiteId) return;
    const [source, target] = [sourceSiteId, targetSiteId].sort();
    const key = `${source}::${target}`;
    const current = connectionMap.get(key) || { source, target, count: 0, down: 0 };
    current.count += 1;
    const state = String(link.operational_state || '').trim().toLowerCase();
    if (state === 'down' || state === 'degraded') current.down += 1;
    connectionMap.set(key, current);
  });

  devices.forEach((device) => {
    const deviceId = String(device.id || '').trim();
    const siteId = deviceSite.get(deviceId);
    if (!siteId || connectedDeviceIds.has(deviceId)) return;
    const site = siteMap.get(siteId);
    if (site) site.orphanCount += 1;
  });

  const sortedSites = Array.from(siteMap.values())
    .filter((site) => site.deviceCount > 0)
    .sort(
    (left, right) => right.deviceCount - left.deviceCount || left.name.localeCompare(right.name),
    );
  const sortedConnections = Array.from(connectionMap.values()).sort((left, right) => right.count - left.count);
  const names = new Map(sortedSites.map((site) => [site.id, site.name]));

  return {
    sites: sortedSites,
    connections: sortedConnections,
    siteName: (id: string) => names.get(id) || id,
  };
};
