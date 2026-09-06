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

function parseBooleanFlag(value: unknown): boolean {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number') return value === 1;
  const normalized = String(value ?? '').trim().toLowerCase();
  return normalized === '1' || normalized === 'true' || normalized === 'yes';
}

/**
 * Compute 3D spatial coordinates from U position and chassis depth.
 */
export function calculateDeviceCoordinates(
  startU: number,
  heightU: number,
  face: 'front' | 'rear',
  isFullDepth: boolean,
  rackDepth: number = RACK_TOTAL_DEPTH_DEFAULT,
  rackWidth: number = RACK_OUTER_WIDTH_DEFAULT,
): RackDeviceCoordinates {
  const h = Math.max(0.01, heightU * U_HEIGHT_3D - 0.02);
  const centerY = (startU - 1 + heightU / 2) * U_HEIGHT_3D;
  const safeRackWidth = Math.max(0.1, rackWidth);
  const width = Math.max(
    0.1,
    safeRackWidth * (RACK_INNER_WIDTH / RACK_OUTER_WIDTH_DEFAULT) - 0.04,
  );
  const safeRackDepth = Math.max(0.1, rackDepth);
  const fullDepth = safeRackDepth * (CHASSIS_DEPTH_FULL / RACK_TOTAL_DEPTH_DEFAULT);
  const halfDepth = safeRackDepth * (CHASSIS_DEPTH_HALF / RACK_TOTAL_DEPTH_DEFAULT);
  const depth = isFullDepth ? fullDepth : halfDepth;

  let centerZ = 0;
  if (!isFullDepth) {
    const offset = (fullDepth - halfDepth) / 2;
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
  const rackDepthScene = (depthMm / 1000) * RACK_TOTAL_DEPTH_DEFAULT;
  const rackWidthScene = (widthMm / 600) * RACK_OUTER_WIDTH_DEFAULT;

  const rawDevices: RackDevice[] = (rackData as RackLayout).devices || [];
  const globalIssues: string[] = [];

  let ratedPowerTotal = 0;
  const normalizedDevices: RackDeviceVM[] = [];

  // Track U-occupancy for conflict detection
  const frontOccupancy = new Map<number, string>();
  const rearOccupancy = new Map<number, string>();

  for (const raw of rawDevices) {
    const issues: string[] = [];
    const mountKind = String(raw.mount_kind || raw.default_mount_kind || 'u_mount').trim().toLowerCase();
    const isUMount = mountKind === 'u_mount';
    const rawPosition = String(raw.position || '').trim().toLowerCase();
    const position = rawPosition || (isUMount ? 'front' : 'unknown');
    const parsedStartU = raw.start_u == null ? Number.NaN : parseInt(String(raw.start_u), 10);
    const parsedHeightU = raw.height_u == null
      ? parseInt(String(raw.u_height), 10)
      : parseInt(String(raw.height_u), 10);
    const heightKnown = Number.isFinite(parsedHeightU) && parsedHeightU >= 1;
    const startKnown = Number.isFinite(parsedStartU) && parsedStartU >= 1;
    // Geometry needs a bounded placeholder so a malformed row cannot crash
    // Three.js.  The explicit flags below prevent that placeholder from being
    // presented as a real 1U/U1 placement in the UI.
    const heightU = heightKnown ? parsedHeightU : 1;
    const startU = startKnown ? parsedStartU : 1;
    const endU = startU + heightU - 1;

    // Check face orientation
    let face: 'front' | 'rear' = 'front';
    if (position === 'rear') {
      face = 'rear';
    } else if (isUMount && !['front', 'full_depth'].includes(position)) {
      issues.push(`未知朝向 '${raw.position}'，已默认按前面板处理`);
    }

    const isFullDepth = position === 'full_depth'
      || String(raw.depth_class || '').trim().toLowerCase() === 'full'
      || parseBooleanFlag(raw.is_full_depth);

    if (isUMount) {
      // Check U bounds only for standard U-mounted devices. Non-U equipment
      // must not be coerced into U1 or consume cabinet capacity.
      if (!Number.isFinite(parsedStartU) || parsedStartU < 1) {
        issues.push(`起始U位非法 (start_u=${raw.start_u})，必须 >= 1`);
      }
      if (!Number.isFinite(parsedHeightU) || parsedHeightU < 1) {
        issues.push(`设备高度非法 (height_u=${raw.height_u ?? raw.u_height})，必须 >= 1U`);
      }
      if (startU > totalU) {
        issues.push(`起始U位超出机柜高度 (U${startU} > ${totalU}U)`);
      }
      if (endU > totalU) {
        issues.push(`设备顶部超出机柜高度 (U${startU}-U${endU} > ${totalU}U)`);
      }

      // Check overlap only after the row is a valid standard placement.
      if (issues.length === 0) {
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
      }
    } else {
      // Known non-U placement classes remain visible in the read model, but
      // are intentionally excluded from the elevation/3D U-slot renderer.
      if (!['zero_u', 'side_mount', 'floor', 'unknown'].includes(mountKind)) {
        issues.push(`未知安装方式 '${raw.mount_kind}'，需要人工确认`);
      } else if (mountKind === 'side_mount' && !['left_side', 'right_side'].includes(position)) {
        issues.push('侧挂设备必须指定 left_side 或 right_side');
      } else if (mountKind === 'zero_u' && !['rear', 'left_side', 'right_side', 'unknown'].includes(position)) {
        issues.push('0U 设备位置必须是 rear、left_side、right_side 或 unknown');
      } else if (mountKind === 'floor' && !raw.location_note?.trim()) {
        issues.push('落地设备必须填写位置说明');
      }
    }

    if (raw.placement_status === 'invalid') {
      issues.push('placement_status=invalid，需要先完成数据修复');
    }

    // Power
    const ratedPowerWatts = parseInt(String(raw.power_watts), 10) || 0;
    ratedPowerTotal += ratedPowerWatts;

    // Health lookup
    const assetId = (raw.asset_id || '').trim();
    const networkDeviceId = (raw.network_device_id || '').trim();
    const sn = (raw.serial_number || raw.physical_serial_number || raw.network_sn || '').trim().toLowerCase();
    const nameNorm = (raw.name || '').trim().toLowerCase();
    const networkHostname = (raw.network_hostname || raw.physical_hostname || '').trim().toLowerCase();

    const health =
      (assetId && healthMap[assetId]) ||
      (networkDeviceId && healthMap[networkDeviceId]) ||
      (sn && healthMap[sn]) ||
      (networkHostname && healthMap[networkHostname]) ||
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

    // Calculate 3D coordinates for standard U devices. Non-U rows receive a
    // harmless placeholder coordinate for tooltips/cable lookup but are not
    // included in validDevices and therefore cannot crash the renderer.
    const clampedStartU = Math.max(1, Math.min(totalU, startU || 1));
    const clampedHeightU = Math.max(1, Math.min(totalU - clampedStartU + 1, heightU));
    const coordinates = calculateDeviceCoordinates(
      clampedStartU,
      clampedHeightU,
      face,
      isFullDepth,
      rackDepthScene,
      rackWidthScene,
    );

    const isValid = issues.length === 0;

    normalizedDevices.push({
      id: raw.id,
      rackId: raw.rack_id || rackData.id,
      name: raw.name || '未命名设备',
      assetId,
      networkDeviceId: health?.network_device_id || networkDeviceId || undefined,
      deviceTypeId: raw.device_type_id || '',
      vendor: raw.vendor || '',
      model: raw.model || '',
      role: (raw.device_role || 'switch').toLowerCase(),
      startU,
      heightU,
      endU,
      startKnown,
      heightKnown,
      face,
      mountKind,
      position,
      locationNote: raw.location_note || '',
      placementStatus: raw.placement_status || (isUMount ? 'estimated' : 'unknown'),
      renderable: isUMount && isValid,
      assetKey: raw.resolved_asset_key || raw.model_key || undefined,
      assetResolutionLevel: raw.asset_resolution_level || undefined,
      assetFidelity: raw.asset_fidelity || undefined,
      assetPath: raw.asset_path || null,
      assetUrl: raw.asset_url || null,
      assetAvailable: raw.asset_available,
      assetRenderStrategy: raw.asset_render_strategy || undefined,
      isFullDepth,
      serialNumber: raw.serial_number || raw.physical_serial_number || raw.network_sn || '',
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

  const validDevices = normalizedDevices.filter(d => d.renderable);
  const invalidDevices = normalizedDevices.filter(d => d.mountKind === 'u_mount' && !d.renderable);
  const nonUDevices = normalizedDevices.filter(d => d.mountKind !== 'u_mount');

  if (invalidDevices.length > 0) {
    globalIssues.push(`机柜内存在 ${invalidDevices.length} 台数据异常设备`);
  }
  const unknownNonUDevices = nonUDevices.filter(d => !d.dataQuality.valid);
  if (unknownNonUDevices.length > 0) {
    globalIssues.push(`机柜内存在 ${unknownNonUDevices.length} 台非U位设备需要确认`);
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
    nonUDevices,
    dataQuality: {
      valid: globalIssues.length === 0,
      issues: globalIssues
    }
  };
}
