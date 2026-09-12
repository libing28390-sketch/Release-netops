export interface Rack {
  id: string;
  name: string;
  datacenter: string;
  floor?: string;
  room: string;
  row: string;
  total_u: number;
  description: string;
  status: string;
  created_at: string;
  updated_at: string;
  
  site_id?: string;
  site_code?: string;
  site_name?: string;
  rack_code?: string;
  rack_name?: string;
  room_name?: string;
  row_name?: string;
  used_u?: number;
  available_u?: number;
  power_capacity_w?: number;
  power_capacity_watts?: number;
  current_power_w?: number;
  power_utilization?: number;
  max_weight_kg?: number | null;
  current_weight_kg?: number;
  cooling_zone?: string;
  remarks?: string;
  placement_strategy?: 'bottom_first' | 'top_first';
  rack_type_id?: string;
  width_mm?: number;
  depth_mm?: number;
  allow_front_rear_mount?: number | boolean;
  mount_policy?: 'front_only' | 'front_rear' | 'full_depth' | string;
  layout_revision?: number;
}

export type RackSummaryHealth = 'healthy' | 'offline' | 'partial' | 'unknown' | 'empty';
export type RackSummaryDataQuality = 'complete' | 'partial' | 'invalid' | 'empty';

export interface RackSummary extends Rack {
  site_label: string;
  device_count: number;
  front_used: number;
  rear_used: number;
  used_u: number;
  available_u: number;
  u_utilization_pct: number | null;
  power_used_watts: number;
  power_utilization_pct: number | null;
  monitored_device_count: number;
  healthy_device_count: number;
  offline_device_count: number;
  unknown_monitoring_device_count: number;
  unlinked_asset_count: number;
  unmonitored_device_count: number;
  non_u_device_count?: number;
  unknown_placement_device_count?: number;
  invalid_device_count: number;
  health_status: RackSummaryHealth;
  data_quality_status: RackSummaryDataQuality;
}

export interface RackSummaryPage {
  items: RackSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface RackType {
  id: string;
  name: string;
  vendor?: string;
  model?: string;
  total_u: number;
  width_mm?: number;
  depth_mm?: number;
  max_weight_kg?: number;
  power_capacity_watts?: number;
  allow_front_rear_mount?: number | boolean;
  mount_policy?: 'front_only' | 'front_rear' | 'full_depth' | string;
  description?: string;
}

export interface DeviceType {
  id: string;
  model: string;
  vendor: string;
  u_height: number;
  device_role: string;
  is_full_depth: number | boolean;
  depth_class?: 'half' | 'full' | 'unknown' | string;
  width_mm?: number | null;
  depth_mm?: number | null;
  height_mm?: number | null;
  weight_kg?: number | null;
  dimension_status?: 'confirmed' | 'estimated' | 'unknown' | 'pending_verification' | string;
  default_mount_kind?: 'u_mount' | 'zero_u' | 'side_mount' | 'floor' | 'unknown' | string;
  model_family?: string;
  catalog_key?: string;
  description: string;
}

export interface RackDevice {
  id: string;
  name: string;
  rack_id: string;
  device_type_id: string;
  start_u: number | null;
  position: 'front' | 'rear' | 'full_depth' | 'left_side' | 'right_side' | 'unknown' | string;
  mount_kind?: 'u_mount' | 'zero_u' | 'side_mount' | 'floor' | 'unknown' | string;
  height_u?: number | null;
  placement_status?: 'confirmed' | 'estimated' | 'unknown' | 'invalid' | string;
  placement_source?: string;
  dimension_status?: string;
  location_note?: string;
  model_key?: string;
  default_mount_kind?: string;
  resolved_asset_key?: string;
  asset_resolution_level?: 'exact' | 'family' | 'vendor_generic' | 'global_generic' | string;
  asset_fidelity?: 'exact' | 'family' | 'vendor' | 'generic' | string;
  asset_path?: string | null;
  asset_url?: string | null;
  asset_available?: boolean;
  asset_render_strategy?: string;
  status: string;
  serial_number: string;
  physical_asset_tag?: string;
  physical_serial_number?: string;
  physical_hostname?: string;
  network_device_id?: string;
  network_hostname?: string;
  network_sn?: string;
  asset_id: string;
  model: string;
  vendor: string;
  u_height: number;
  device_role: string;
  is_full_depth: number;
  depth_class?: 'half' | 'full' | 'unknown' | string;
  power_watts?: number;
}

export interface RackLayout {
  id: string;
  name: string;
  datacenter: string;
  floor?: string;
  room: string;
  row: string;
  total_u: number;
  description: string;
  status: string;
  site_id?: string;
  site_code?: string;
  site_name?: string;
  rack_code?: string;
  rack_name?: string;
  room_name?: string;
  row_name?: string;
  placement_strategy?: 'bottom_first' | 'top_first';
  rack_type_id?: string;
  width_mm?: number;
  depth_mm?: number;
  max_weight_kg?: number | null;
  power_capacity_watts?: number;
  allow_front_rear_mount?: number | boolean;
  mount_policy?: 'front_only' | 'front_rear' | 'full_depth' | string;
  layout_revision?: number;
  devices: RackDevice[];
  placements?: RackDevice[];
  occupancy?: {
    front: number[];
    rear: number[];
    used_u: number;
    available_u: number;
  };
  data_quality?: {
    non_u_device_count: number;
    unknown_placement_device_count: number;
    invalid_device_count: number;
    status: 'complete' | 'partial' | 'invalid' | string;
  };
  meta?: {
    schema_version?: string;
    layout_revision?: number;
    generated_at?: string;
  };
  front_used: number;
  rear_used: number;
  total_used: number;
  available_u: number;
  non_u_device_count?: number;
  unknown_placement_device_count?: number;
  invalid_device_count?: number;
}


export interface RackStats {
  total_racks: number;
  total_devices: number;
  total_u: number;
  used_u: number;
  utilization: number;
  total_power_capacity_watts?: number;
  total_power_used_watts?: number;
  power_utilization_pct?: number | null;
  total_non_u_devices?: number;
  total_unknown_placements?: number;
  total_invalid_placements?: number;
}

export interface Props {
  language: string;
  t: (key: string) => string;
}

export type DeviceHealthStatus = 'healthy' | 'warning' | 'critical' | 'offline' | 'unknown';

export interface DeviceTelemetryVM {
  cpuPct?: number;
  memoryPct?: number;
  temperatureC?: number;
  openAlertCount?: number;
  criticalAlerts?: number;
  warningAlerts?: number;
  ratedPowerWatts: number;
  powerSource: 'RATED' | 'TELEMETRY' | 'ESTIMATED' | 'NONE';
}

export interface RackDeviceCoordinates {
  centerY: number;
  height: number;
  depth: number;
  centerZ: number;
  width: number;
}

export interface RackDeviceVM {
  id: string;
  rackId: string;
  name: string;
  assetId: string;
  networkDeviceId?: string;
  deviceTypeId: string;
  vendor: string;
  model: string;
  role: string;
  startU: number;
  heightU: number;
  endU: number;
  /** True only when the source supplied a valid standard-U start position. */
  startKnown?: boolean;
  /** True only when height_u/u_height is a valid, explicit standard-U height. */
  heightKnown?: boolean;
  face: 'front' | 'rear';
  mountKind?: 'u_mount' | 'zero_u' | 'side_mount' | 'floor' | 'unknown' | string;
  position?: string;
  locationNote?: string;
  placementStatus?: string;
  renderable?: boolean;
  assetKey?: string;
  assetResolutionLevel?: string;
  assetFidelity?: string;
  assetPath?: string | null;
  assetUrl?: string | null;
  assetAvailable?: boolean;
  assetRenderStrategy?: string;
  isFullDepth: boolean;
  serialNumber: string;
  lifecycleStatus: string;
  healthStatus: DeviceHealthStatus;
  metrics: DeviceTelemetryVM;
  dataQuality: {
    valid: boolean;
    issues: string[];
  };
  coordinates: RackDeviceCoordinates;
}

export interface RackVM {
  id: string;
  name: string;
  siteId: string;
  siteLabel: string;
  floor: string;
  room: string;
  row: string;
  totalU: number;
  widthMm: number;
  depthMm: number;
  heightMm: number;
  usedU: number;
  availableU: number;
  ratedPowerTotalWatts: number;
  devices: RackDeviceVM[];
  validDevices: RackDeviceVM[];
  invalidDevices: RackDeviceVM[];
  nonUDevices?: RackDeviceVM[];
  dataQuality: {
    valid: boolean;
    issues: string[];
  };
}

export type RackDisplayMode = 'physical' | 'health' | 'role' | 'power';
