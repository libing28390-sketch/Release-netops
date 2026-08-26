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
  description?: string;
}

export interface DeviceType {
  id: string;
  model: string;
  vendor: string;
  u_height: number;
  device_role: string;
  is_full_depth: number;
  description: string;
}

export interface RackDevice {
  id: string;
  name: string;
  rack_id: string;
  device_type_id: string;
  start_u: number;
  position: string;
  status: string;
  serial_number: string;
  asset_id: string;
  model: string;
  vendor: string;
  u_height: number;
  device_role: string;
  is_full_depth: number;
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
  devices: RackDevice[];
  front_used: number;
  rear_used: number;
  total_used: number;
  available_u: number;
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
  face: 'front' | 'rear';
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
  dataQuality: {
    valid: boolean;
    issues: string[];
  };
}

export type RackDisplayMode = 'physical' | 'health' | 'role' | 'power';

