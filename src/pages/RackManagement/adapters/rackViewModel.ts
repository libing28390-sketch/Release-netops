import {
  Rack,
  RackLayout,
  RackDevice,
  RackVM,
  RackDeviceVM,
  DeviceHealthStatus,
  DeviceTelemetryVM,
  RackDeviceCoordinates
} from '../types';

export const U_HEIGHT_3D = 0.4445;
export const RACK_OUTER_WIDTH_DEFAULT = 6.0;
export const RACK_INNER_WIDTH = 4.826;
export const RACK_TOTAL_DEPTH_DEFAULT = 10.0;
export const CHASSIS_DEPTH_FULL = 7.5;
export const CHASSIS_DEPTH_HALF = 3.75;

export interface HealthInfo {
  status?: string;
  cpu_usage?: number | null;
  memory_usage?: number | null;
  temp?: number | null;
  open_alert_count?: number;
  critical_open_alerts?: number;
  warning_open_alerts?: number;
  network_device_id?: string;
}

export type HealthMap = Record<string, HealthInfo>;

/**
 * Normalizes device health status strictly based on real telemetry data.
 * Does not fake unknown as healthy.
 */
export function normalizeHealthStatus(
  healthInfo?: HealthInfo,
  lifecycleStatus?: string
): DeviceHealthStatus {
  const normLifecycle = (lifecycleStatus || '').trim().toLowerCase();
  if (normLifecycle === 'offline') {
    return 'offline';
  }

  if (!healthInfo) {
    return 'unknown';
  }

  const rawStatus = (healthInfo.status || '').trim().toLowerCase();
  if (rawStatus === 'healthy' || rawStatus === 'normal' || rawStatus === 'up' || rawStatus === 'ok') {
    return 'healthy';
  }
  if (rawStatus === 'warning' || rawStatus === 'major' || rawStatus === 'degraded') {
    return 'warning';
  }
  if (rawStatus === 'critical' || rawStatus === 'down' || rawStatus === 'error' || rawStatus === 'alarm') {
    return 'critical';
  }
  if (rawStatus === 'offline') {
    return 'offline';
  }

  // If there are explicit open alerts
  if ((healthInfo.critical_open_alerts ?? 0) > 0) {
    return 'critical';
  }
  if ((healthInfo.warning_open_alerts ?? 0) > 0 || (healthInfo.open_alert_count ?? 0) > 0) {
    return 'warning';
  }

  // If telemetry values exist without explicit status
  if (healthInfo.cpu_usage != null || healthInfo.memory_usage != null || healthInfo.temp != null) {
    const cpu = healthInfo.cpu_usage ?? 0;
    const mem = healthInfo.memory_usage ?? 0;
    const temp = healthInfo.temp ?? 0;
    if (cpu >= 90 || mem >= 90 || temp >= 75) return 'critical';
    if (cpu >= 80 || mem >= 80 || temp >= 60) return 'warning';
    return 'healthy';
  }

  return 'unknown';
}

/**
 * Compute 3D spatial coordinates from U position and chassis depth.
 */
export function calculateDeviceCoordinates(
  startU: number,
  heightU: number,
  face: 'front' | 'rear',
  isFullDepth: boolean
): RackDeviceCoordinates {
  const h = Math.max(0.01, heightU * U_HEIGHT_3D - 0.02);
  const centerY = (startU - 1 + heightU / 2) * U_HEIGHT_3D;
  const width = RACK_INNER_WIDTH - 0.04;
  const depth = isFullDepth ? CHASSIS_DEPTH_FULL : CHASSIS_DEPTH_HALF;

  let centerZ = 0;
  if (!isFullDepth) {
    const offset = (CHASSIS_DEPTH_FULL - CHASSIS_DEPTH_HALF) / 2;
    centerZ = face === 'front' ? offset : -offset;
  }

  return {
    centerY,
    height: h,
    depth,
    centerZ,
    width
  };
}

/**
 * Normalizes a raw Rack / RackLayout into a robust, quality-checked RackVM.
 */
export function normalizeRackToVM(
  rackData: Rack | RackLayout,
  healthMap: HealthMap = {},
  siteLabelResolver?: (rack: Pick<Rack, 'site_id' | 'site_code' | 'site_name' | 'datacenter'>) => string
): RackVM {
  const totalU = Math.max(1, parseInt(String(rackData.total_u), 10) || 42);
  const widthMm = Math.max(300, parseInt(String(rackData.width_mm), 10) || 600);
  const depthMm = Math.max(400, parseInt(String(rackData.depth_mm), 10) || 1000);
  const heightMm = Math.round(totalU * 44.45);

  const rawDevices: RackDevice[] = (rackData as RackLayout).devices || [];
  const globalIssues: string[] = [];

  let ratedPowerTotal = 0;
  const normalizedDevices: RackDeviceVM[] = [];

  // Track U-occupancy for conflict detection
  const frontOccupancy = new Map<number, string>();
  const rearOccupancy = new Map<number, string>();

  for (const raw of rawDevices) {
    const issues: string[] = [];
    const startU = parseInt(String(raw.start_u), 10);
    const heightU = Math.max(1, parseInt(String(raw.u_height), 10) || 1);
    const endU = startU + heightU - 1;

    // Check face orientation
    let face: 'front' | 'rear' = 'front';
    const rawPos = (raw.position || '').trim().toLowerCase();
    if (rawPos === 'rear') {
      face = 'rear';
    } else if (rawPos !== 'front' && rawPos !== '') {
      issues.push(`未知朝向 '${raw.position}'，已默认按前面板处理`);
    }

    // Check U bounds
    if (Number.isNaN(startU) || startU < 1) {
      issues.push(`起始U位非法 (start_u=${raw.start_u})，必须 >= 1`);
    }
    if (startU > totalU) {
      issues.push(`起始U位超出机柜高度 (U${startU} > ${totalU}U)`);
    }
    if (endU > totalU) {
      issues.push(`设备顶部超出机柜高度 (U${startU}-U${endU} > ${totalU}U)`);
    }

    // Check overlap
    const isFullDepth = raw.is_full_depth === 1 || Boolean(raw.is_full_depth);
    for (let u = startU; u <= endU; u++) {
      if (face === 'front' || isFullDepth) {
        const conflictName = frontOccupancy.get(u);
        if (conflictName) {
          issues.push(`前面板 U${u} 与已上架设备 '${conflictName}' 空间重叠`);
        } else {
          frontOccupancy.set(u, raw.name);
        }
      }
      if (face === 'rear' || isFullDepth) {
        const conflictName = rearOccupancy.get(u);
        if (conflictName) {
          issues.push(`后面板 U${u} 与已上架设备 '${conflictName}' 空间重叠`);
        } else {
          rearOccupancy.set(u, raw.name);
        }
      }
    }

    // Power
    const ratedPowerWatts = parseInt(String(raw.power_watts), 10) || 0;
    ratedPowerTotal += ratedPowerWatts;

    // Health lookup
    const assetId = (raw.asset_id || '').trim();
    const sn = (raw.serial_number || '').trim().toLowerCase();
    const nameNorm = (raw.name || '').trim().toLowerCase();

    const health =
      (assetId && healthMap[assetId]) ||
      (sn && healthMap[sn]) ||
      (nameNorm && healthMap[nameNorm]) ||
      healthMap[raw.id];

    const healthStatus = normalizeHealthStatus(health, raw.status);

    const metrics: DeviceTelemetryVM = {
      cpuPct: health?.cpu_usage ?? undefined,
      memoryPct: health?.memory_usage ?? undefined,
      temperatureC: health?.temp ?? undefined,
      openAlertCount: health?.open_alert_count,
      criticalAlerts: health?.critical_open_alerts,
      warningAlerts: health?.warning_open_alerts,
      ratedPowerWatts,
      powerSource: ratedPowerWatts > 0 ? 'RATED' : 'NONE'
    };

    // Calculate 3D coordinates
    const clampedStartU = Math.max(1, Math.min(totalU, startU || 1));
    const clampedHeightU = Math.max(1, Math.min(totalU - clampedStartU + 1, heightU));
    const coordinates = calculateDeviceCoordinates(clampedStartU, clampedHeightU, face, isFullDepth);

    const isValid = issues.length === 0;

    normalizedDevices.push({
      id: raw.id,
      rackId: raw.rack_id || rackData.id,
      name: raw.name || '未命名设备',
      assetId,
      networkDeviceId: health?.network_device_id,
      deviceTypeId: raw.device_type_id || '',
      vendor: raw.vendor || '',
      model: raw.model || '',
      role: (raw.device_role || 'switch').toLowerCase(),
      startU,
      heightU,
      endU,
      face,
      isFullDepth,
      serialNumber: raw.serial_number || '',
      lifecycleStatus: raw.status || 'active',
      healthStatus,
      metrics,
      dataQuality: {
        valid: isValid,
        issues
      },
      coordinates
    });
  }

  const validDevices = normalizedDevices.filter(d => d.dataQuality.valid);
  const invalidDevices = normalizedDevices.filter(d => !d.dataQuality.valid);

  if (invalidDevices.length > 0) {
    globalIssues.push(`机柜内存在 ${invalidDevices.length} 台数据异常设备`);
  }

  // Calculate used U (union of front and rear)
  const allUsedUs = new Set<number>([
    ...Array.from(frontOccupancy.keys()),
    ...Array.from(rearOccupancy.keys())
  ]);
  const usedU = allUsedUs.size;
  const availableU = Math.max(0, totalU - usedU);

  const siteLabel = siteLabelResolver
    ? siteLabelResolver(rackData)
    : rackData.site_name || rackData.site_code || rackData.datacenter || '';

  return {
    id: rackData.id,
    name: rackData.name || rackData.rack_name || 'Rack',
    siteId: rackData.site_id || '',
    siteLabel,
    floor: rackData.floor || '',
    room: rackData.room || rackData.room_name || '',
    row: rackData.row || rackData.row_name || '',
    totalU,
    widthMm,
    depthMm,
    heightMm,
    usedU,
    availableU,
    ratedPowerTotalWatts: ratedPowerTotal,
    devices: normalizedDevices,
    validDevices,
    invalidDevices,
    dataQuality: {
      valid: globalIssues.length === 0,
      issues: globalIssues
    }
  };
}
