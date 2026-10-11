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
