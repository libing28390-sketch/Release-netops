import { authHeaders } from '../helpers';

export interface PhysicalInterfaceItem {
  id?: string;
  name: string;
  shortName: string;
  status: 'up' | 'down' | 'testing' | 'unknown';
  speedMbps?: number;
  inBps?: number;
  outBps?: number;
  inErrors?: number;
  outErrors?: number;
  fcsErrors?: number;
  description?: string;
  remoteDevice?: string;
  remoteInterface?: string;
  cableType?: string;
}

export interface DeviceTelemetryResult {
  deviceId: string;
  hostname: string;
  ipAddress: string;
  platform: string;
  status: string;
  source: 'IF-MIB';
  sampledAt?: string;
  queriedAt?: string;
  isStale: boolean;
  cpuPct?: number;
  memoryPct?: number;
  temperatureC?: number;
  interfaces: PhysicalInterfaceItem[];
  upCount: number;
  downCount: number;
}

export type DeviceTelemetryLoadResult =
  | { status: 'ready'; data: DeviceTelemetryResult }
  | { status: 'empty'; data: null; reason: 'not_registered' | 'no_recent_samples' }
  | { status: 'error'; data: null; message: string };

// In-memory cache to avoid duplicate requests during hover / select
const telemetryCache = new Map<string, { data: DeviceTelemetryResult; expiresAt: number }>();
let networkDevicesCache: any[] | null = null;
let networkDevicesExpiresAt = 0;

/**
 * Fetch list of network devices from monitoring API
 */
async function getNetworkDevices(): Promise<any[]> {
  const now = Date.now();
  if (networkDevicesCache && now < networkDevicesExpiresAt) {
    return networkDevicesCache;
  }
  const res = await fetch('/api/monitoring/network-devices?page_size=200', {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Network device registry request failed (${res.status})`);
  const payload = await res.json();
  const items = Array.isArray(payload?.items) ? payload.items : (Array.isArray(payload) ? payload : []);
  networkDevicesCache = items;
  networkDevicesExpiresAt = now + 60000; // Cache 1 minute
  return items;
}

/**
 * Check if interface is virtual (loopback, null, vlan, etc.)
 */
function isVirtualInterface(name: string): boolean {
  const lower = name.toLowerCase();
  return (
    lower.startsWith('inloop') ||
    lower.startsWith('null') ||
    lower.startsWith('reg') ||
    lower.startsWith('loopback') ||
    lower.startsWith('vlan') ||
    lower.startsWith('tunnel') ||
    lower.startsWith('mgmt') ||
    lower.startsWith('m-eth') ||
    lower.startsWith('bridge')
  );
}

/**
 * Clean and simplify interface name: GigabitEthernet1/0/0 -> GE1/0/0, Ten-GigabitEthernet1/0/1 -> 10GE1/0/1
 */
function toShortInterfaceName(name: string): string {
  return name
    .replace(/^GigabitEthernet/i, 'GE')
    .replace(/^Ten-GigabitEthernet/i, '10GE')
    .replace(/^XGigabitEthernet/i, '10GE')
    .replace(/^FortyGigE/i, '40GE')
    .replace(/^HundredGigE/i, '100GE')
    .replace(/^Ethernet/i, 'Eth')
    .replace(/^FastEthernet/i, 'FE');
}

/**
 * Extract numerical port index from name for sorting (e.g. GE1/0/0 -> 0, GE1/0/1 -> 1)
 */
function getPortSortKey(name: string): number {
  const parts = name.split(/[\/\-_:]/);
  const lastPart = parts[parts.length - 1];
  const num = parseInt(lastPart, 10);
  return isNaN(num) ? 999 : num;
}

/**
 * Load authoritative real SNMP interface telemetry for any rack device (by device name, hostname, asset_id, or device_id)
 */
export async function loadDeviceTelemetry(
  deviceName: string,
  rawDeviceId?: string
): Promise<DeviceTelemetryLoadResult> {
  const cacheKey = `${deviceName}-${rawDeviceId || ''}`.toLowerCase();
  const cached = telemetryCache.get(cacheKey);
  if (cached && Date.now() < cached.expiresAt) {
    return { status: 'ready', data: cached.data };
  }

  try {
    const networkDevices = await getNetworkDevices();
    const lowerName = deviceName.toLowerCase().trim();
    const normalizedRawDeviceId = rawDeviceId?.toLowerCase().trim();

    // Match device in monitoring by stable IDs before hostname heuristics.
    const matchedById = normalizedRawDeviceId
      ? networkDevices.find((d: any) => {
          const id = String(d.id || '').toLowerCase().trim();
          const assetId = String(d.asset_id || '').toLowerCase().trim();
          return id === normalizedRawDeviceId || assetId === normalizedRawDeviceId;
        })
      : undefined;

    const matched = matchedById || networkDevices.find((d: any) => {
      const h = String(d.hostname || '').toLowerCase().trim();
      const ip = String(d.ip_address || '').trim();
      const id = String(d.id || '').toLowerCase().trim();

      return (
        h === lowerName ||
        id === lowerName ||
        ip === lowerName ||
        (Boolean(h) && Boolean(lowerName) && (h.includes(lowerName) || lowerName.includes(h)))
      );
    });

    const targetDeviceId = matched?.id || rawDeviceId;
    if (!targetDeviceId) {
      return { status: 'empty', data: null, reason: 'not_registered' };
    }

    const res = await fetch(`/api/monitoring/device/${encodeURIComponent(targetDeviceId)}/realtime?window_minutes=15&limit=100`, {
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error('Realtime telemetry fetch failed');
    const data = await res.json();
    const devInfo = data.device || {};
    const rawInterfaces = Array.isArray(data.latest_interfaces)
      ? data.latest_interfaces
      : (Array.isArray(devInfo.interface_data) ? devInfo.interface_data : []);

    if (rawInterfaces.length === 0) {
      return { status: 'empty', data: null, reason: 'no_recent_samples' };
    }

    // Filter and sort physical interfaces
    const physicalInterfaces: PhysicalInterfaceItem[] = rawInterfaces
      .filter((it: any) => !isVirtualInterface(it.name || it.interface_name || ''))
      .map((it: any) => {
        const fullName = it.name || it.interface_name || '';
        const shortName = toShortInterfaceName(fullName);
        const operStatus = String(it.status || it.oper_status || '').toLowerCase();
        const isUp = operStatus === 'up' || operStatus === 'normal' || operStatus === '1';

        // Parse description if it connects to remote device (e.g. TO-S6850-1, RBM-TO-F1090-10)
        const desc = String(it.description || '').trim();
        let remoteDev = '';
        if (desc.toUpperCase().startsWith('TO-')) {
          remoteDev = desc.substring(3).trim();
        } else if (desc.toUpperCase().includes('TO-')) {
          const match = desc.match(/TO-([A-Za-z0-9_\-]+)/i);
          if (match) remoteDev = match[1];
        }

        return {
          id: it.id,
          name: fullName,
          shortName,
          status: isUp ? 'up' : 'down',
          speedMbps: Number(it.speed_mbps || 0),
          inBps: Number(it.in_bps || 0),
          outBps: Number(it.out_bps || 0),
          inErrors: Number(it.in_errors || 0),
          outErrors: Number(it.out_errors || 0),
          fcsErrors: Number(it.fcs_errors || 0),
          description: desc,
          remoteDevice: remoteDev,
          cableType: (shortName.includes('10G') || shortName.includes('40G') || shortName.includes('100G')) ? 'fiber' : 'copper',
        };
      })
      .sort((a: PhysicalInterfaceItem, b: PhysicalInterfaceItem) => getPortSortKey(a.name) - getPortSortKey(b.name));

    if (physicalInterfaces.length === 0) {
      return { status: 'empty', data: null, reason: 'no_recent_samples' };
    }

    const upCount = physicalInterfaces.filter((p) => p.status === 'up').length;
    const downCount = physicalInterfaces.length - upCount;
    const sampledAtCandidates = rawInterfaces
      .map((item: any) => String(item.ts || item.counter_sampled_at || '').trim())
      .filter(Boolean)
      .sort();
    const sampledAt = sampledAtCandidates.at(-1);
    const sampledAtMs = sampledAt ? Date.parse(sampledAt) : Number.NaN;

    const result: DeviceTelemetryResult = {
      deviceId: targetDeviceId,
      hostname: devInfo.hostname || matched?.hostname || deviceName,
      ipAddress: devInfo.ip_address || matched?.ip_address || '',
      platform: devInfo.platform || matched?.platform || '',
      status: devInfo.status || matched?.status || 'online',
      source: 'IF-MIB',
      sampledAt,
      queriedAt: data.updated_at,
      isStale: !Number.isFinite(sampledAtMs) || Date.now() - sampledAtMs > 15 * 60 * 1000,
      cpuPct: devInfo.cpu_usage != null ? Number(devInfo.cpu_usage) : undefined,
      memoryPct: devInfo.memory_usage != null ? Number(devInfo.memory_usage) : undefined,
      temperatureC: devInfo.temp != null ? Number(devInfo.temp) : undefined,
      interfaces: physicalInterfaces,
      upCount,
      downCount,
    };

    telemetryCache.set(cacheKey, { data: result, expiresAt: Date.now() + 15000 });
    return { status: 'ready', data: result };
  } catch (err) {
    console.warn(`[snmpTelemetry] Failed to load telemetry for ${deviceName}:`, err);
    return {
      status: 'error',
      data: null,
      message: err instanceof Error ? err.message : 'Telemetry request failed',
    };
  }
}

/** Backward-compatible data-only helper for existing callers. */
export async function fetchDeviceTelemetry(
  deviceName: string,
  rawDeviceId?: string
): Promise<DeviceTelemetryResult | null> {
  const result = await loadDeviceTelemetry(deviceName, rawDeviceId);
  return result.status === 'ready' ? result.data : null;
}
