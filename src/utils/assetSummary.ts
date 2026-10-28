/** Return the asset-management device count for network devices and servers. */
export const getManagedAssetDeviceTotal = (summary: unknown): number | null => {
  if (!summary || typeof summary !== 'object' || Array.isArray(summary)) return null;

  const byType = (summary as { by_type?: unknown }).by_type;
  if (!byType || typeof byType !== 'object' || Array.isArray(byType)) return null;

  const counts = byType as Record<string, unknown>;
  const networkDevices = counts.network_device;
  const servers = counts.server;
  if (
    typeof networkDevices !== 'number' || !Number.isSafeInteger(networkDevices) || networkDevices < 0 ||
    typeof servers !== 'number' || !Number.isSafeInteger(servers) || servers < 0
  ) {
    return null;
  }

  return networkDevices + servers;
};

/** Return the online count from the same network-device and server asset scope. */
export const getManagedAssetDeviceOnlineTotal = (summary: unknown): number | null => {
  if (!summary || typeof summary !== 'object' || Array.isArray(summary)) return null;

  const byStatus = (summary as { by_online_status?: unknown }).by_online_status;
  if (!byStatus || typeof byStatus !== 'object' || Array.isArray(byStatus)) return null;

  const online = (byStatus as Record<string, unknown>).online;
  return typeof online === 'number' && Number.isSafeInteger(online) && online >= 0
    ? online
    : null;
};

/** Return platform counts for the same managed asset scope as the dashboard total. */
export const getManagedAssetPlatformCounts = (
  summary: unknown,
  expectedTotal: number,
): Record<string, number> | null => {
  if (!summary || typeof summary !== 'object' || Array.isArray(summary)) return null;
  if (!Number.isSafeInteger(expectedTotal) || expectedTotal < 0) return null;

  const byPlatform = (summary as { by_platform?: unknown }).by_platform;
  if (!byPlatform || typeof byPlatform !== 'object' || Array.isArray(byPlatform)) return null;

  const platformCounts = Object.create(null) as Record<string, number>;
  let platformTotal = 0;
  for (const [rawPlatform, count] of Object.entries(byPlatform)) {
    if (typeof count !== 'number' || !Number.isSafeInteger(count) || count < 0) return null;

    const platform = rawPlatform.trim() || 'unknown';
    platformCounts[platform] = (platformCounts[platform] || 0) + count;
    platformTotal += count;
    if (!Number.isSafeInteger(platformTotal) || !Number.isSafeInteger(platformCounts[platform])) return null;
  }

  return platformTotal === expectedTotal ? platformCounts : null;
};
