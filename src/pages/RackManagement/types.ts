export interface Rack {
  id: string;
  name: string;
  datacenter: string;
  room: string;
  row: string;
  total_u: number;
  description: string;
  status: string;
  created_at: string;
  updated_at: string;
  
  site_id?: string;
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
  room: string;
  row: string;
  total_u: number;
  description: string;
  status: string;
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
