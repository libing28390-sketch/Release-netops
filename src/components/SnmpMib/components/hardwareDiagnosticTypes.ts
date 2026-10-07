/**
 * Read-only view of the latest hardware results already collected by the
 * bound LibreNMS instance. This contract intentionally contains no SNMP
 * credentials, probe evidence, or Python-adapter readings.
 */
export type LibreNMSHardwareState =
  | 'not_bound'
  | 'binding_conflict'
  | 'disabled'
  | 'sync_failed'
  | 'sync_pending'
  | 'instance_disabled'
  | 'native_device_missing'
  | 'credential_unavailable'
  | 'engine_unavailable'
  | 'available'
  | 'metadata_only'
  | 'no_native_hardware_data'
  // The service can return this for an unexpected binding lookup failure.
  | 'unavailable';

export interface LibreNMSHardwareBinding {
  id: string;
  instance_id: string;
  instance_name: string;
  native_device_id: string;
  native_hostname: string;
  collector_id: string;
  poller_group: string;
  desired_state: string;
  sync_status: string;
  last_sync_at: string | null;
  last_discovery_at: string | null;
  last_poll_at: string | null;
  last_error_code: string;
}

export interface LibreNMSHardwareEngine {
  instance_id: string;
  name: string;
  version: string;
  commit: string;
  health_state: string;
}

export interface LibreNMSHardwareIdentity {
  native_device_id?: string;
  hostname?: string;
  display?: string;
  os?: string;
  version?: string;
  hardware?: string;
  sysObjectID?: string;
}

export interface LibreNMSHardwareCollection {
  engine_status: string;
  sample_status: string;
  export_status: string;
  sync_status: string;
  last_discovered: string | null;
  last_polled: string | null;
  stale_after_seconds: number | null;
  error_code?: string | null;
}

export interface LibreNMSHealthGraphMetadata {
  health_type?: string;
  name?: string;
  desc?: string;
}

export interface LibreNMSHardwareSensor {
  sensor_id?: number | string;
  sensor_class?: string;
  device_id?: number | string;
  poller_type?: string;
  sensor_oid?: string;
  sensor_index?: string | number | null;
  sensor_type?: string;
  sensor_descr?: string;
  group?: string | null;
  sensor_current?: number | null;
  sensor_limit?: number | null;
  sensor_limit_warn?: number | null;
  sensor_limit_low?: number | null;
  sensor_limit_low_warn?: number | null;
  sensor_alert?: number | null;
  entPhysicalIndex?: string | number | null;
  entPhysicalIndex_measured?: string | null;
  lastupdate?: string | null;
  data_origin?: 'librenms_native' | string;
  value_status?: 'available' | 'missing' | string;
  freshness?: 'fresh' | 'stale' | 'unknown' | string;
  sample_age_seconds?: number | null;
  /** Original timestamp reported by the native sensor row, when available. */
  observed_at?: string | null;
}

/** Current values read from LibreNMS processor/mempool rows, never graph metadata. */
export interface LibreNMSHardwareNativeSample {
  sensor_id?: number | string;
  sensor_descr?: string;
  sensor_current?: number | null;
  unit?: string | null;
  lastupdate?: string | null;
  observed_at?: string | null;
  freshness?: 'fresh' | 'stale' | 'unknown' | string;
  value_status?: 'available' | 'missing' | string;
  sample_age_seconds?: number | null;
  sensor_oid?: string;
  sensor_index?: string | number | null;
  [nativeField: string]: unknown;
}

export interface LibreNMSHardwareMetricSummary {
  key: string;
  measurement_type?: string;
  unit?: string;
  source?: string;
  entity_count: number;
  value_count: number;
  fresh_count: number;
  latest_sample_at: string | null;
  status: 'available' | 'stale' | 'missing' | string;
}

export interface LibreNMSWirelessSensor {
  sensor_id?: number | string;
  device_id?: number | string;
  sensor_class?: string;
  sensor_index?: string | number | null;
  sensor_descr?: string;
  sensor_current?: number | null;
  sensor_prev?: number | null;
  lastupdate?: string | null;
  radio_number?: number | string | null;
  ssid?: string | null;
  bssid?: string | null;
  ap_name?: string | null;
  ap_id?: number | string | null;
}

export interface LibreNMSHardwareTransceiver {
  port_id?: number | string;
  ifName?: string | null;
  ifDescr?: string | null;
  ifIndex?: number | string | null;
  entity_index?: number | string | null;
  entPhysicalIndex?: number | string | null;
  vendor?: string | null;
  serial?: string | null;
  part_number?: string | null;
  revision?: string | null;
  date_code?: string | null;
}

export interface SnmpHardwareDiscoveryTestResult {
  source: 'librenms_native';
  /** Time the Nexora diagnostic response was generated, not a sample timestamp. */
  generated_at?: string | null;
  state: LibreNMSHardwareState | (string & {});
  message: string;
  matched_device_id?: string;
  matched_hostname?: string;
  binding_resolution?: { status?: string } | null;
  binding: LibreNMSHardwareBinding | null;
  engine: LibreNMSHardwareEngine | null;
  identity: LibreNMSHardwareIdentity;
  collection: LibreNMSHardwareCollection;
  health_graphs: LibreNMSHealthGraphMetadata[];
  hardware_sensors: LibreNMSHardwareSensor[];
  processor_sensors?: LibreNMSHardwareNativeSample[];
  memory_pools?: LibreNMSHardwareNativeSample[];
  transceivers: LibreNMSHardwareTransceiver[];
  wireless_sensors: LibreNMSWirelessSensor[];
  sensor_count: number;
  metric_summary: LibreNMSHardwareMetricSummary[];
}
