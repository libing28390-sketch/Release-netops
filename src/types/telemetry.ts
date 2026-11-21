/** A page returned by the Telemetry management API. */
export interface TelemetryPage<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export type TelemetrySupportStatus =
  | 'DOCUMENTED'
  | 'SAMPLE_VERIFIED'
  | 'DEVICE_VERIFIED'
  | 'UNSUPPORTED'
  | 'UNKNOWN';

export interface TelemetryPathEvidence {
  path: string;
  metric_key?: string;
  display_name?: string;
  validation_status: 'VERIFIED' | 'UNVERIFIED' | 'UNSUPPORTED' | 'PARTIAL' | string;
  evidence?: string;
}

export interface TelemetryProtocolProfile {
  id: string;
  profile_key: string;
  vendor: string;
  platform?: string;
  model_scope?: string;
  version_scope?: string;
  adapter_key?: string;
  encoding?: string;
  auth_mode?: string;
  required_proto_version?: string;
  min_interval_seconds?: number;
  support_status: TelemetrySupportStatus;
  official_sources?: string[];
  paths?: TelemetryPathEvidence[];
}

export interface TelemetrySubscriptionTemplate {
  id: string;
  profile_id: string;
  tenant_id?: string;
  template_key: string;
  version: number;
  metric_mappings: Array<Record<string, unknown>>;
  estimated_series: number;
  default_interval_seconds: number;
  status: 'DRAFT' | 'PUBLISHED' | 'RETIRED' | string;
}

export interface TelemetryTlsProfile {
  id: string;
  name: string;
  fingerprint: string;
  status: string;
}

export interface TelemetryCollectorOption {
  id: string;
  name: string;
  target_address: string;
  grpc_port: number | null;
  endpoint_configured: boolean;
  collector_type?: string;
  enabled?: boolean | number;
}

export interface TelemetryDeviceConfig {
  id?: string;
  profile_id: string;
  collector_id: string;
  credential_id?: string | null;
  tls_profile_id?: string | null;
  device_source_address?: string | null;
  allowed_sources: string[];
  enabled: boolean;
  revision: number;
  publish_job?: TelemetryActionAccepted;
}

export type TelemetryPublishState =
  | 'DRAFT'
  | 'QUEUED'
  | 'PUBLISHING'
  | 'APPLIED'
  | 'FAILED'
  | string;

export type TelemetryConnectionState =
  | 'DISABLED'
  | 'AWAITING_DEVICE'
  | 'CONNECTING'
  | 'CONNECTED'
  | 'ERROR'
  | string;

export type TelemetryDataState =
  | 'NO_DATA'
  | 'FRESH'
  | 'PARTIAL'
  | 'STALE'
  | 'INVALID'
  | string;

export interface TelemetryStructuredError {
  code: string;
  message: string;
  retryable?: boolean;
  request_id?: string;
}

/** Runtime health is distinct from desired_enabled on the subscription. */
export interface TelemetrySubscriptionStatus {
  publish_state?: TelemetryPublishState;
  connection_state?: TelemetryConnectionState;
  data_state?: TelemetryDataState;
  desired_version?: number | null;
  published_version?: number | null;
  applied_version?: number | null;
  last_received_at?: string | null;
  last_valid_at?: string | null;
  active_series?: number | null;
  samples_per_second?: number | null;
  clock_skew_ms?: number | null;
  quality?: string | null;
  error?: TelemetryStructuredError | null;
  updated_at?: string | null;
}

export interface TelemetrySubscription {
  id: string;
  name: string;
  device_id: string;
  device_name?: string;
  asset_tag?: string;
  collector_id?: string | null;
  collector_name?: string | null;
  profile_id?: string | null;
  profile_name?: string | null;
  template_id?: string | null;
  template_name?: string | null;
  template_version?: number | null;
  interval_seconds?: number | null;
  desired_enabled: boolean;
  revision?: number;
  runtime?: TelemetrySubscriptionStatus | null;
}

export interface TelemetryCapacityVector {
  devices: number | null;
  series: number | null;
  samples_per_second: number | null;
  message_bytes: number | null;
  queue_bytes: number | null;
}

export interface TelemetryCollectorCapacity {
  collector_id: string;
  measured_at?: string | null;
  limit: TelemetryCapacityVector;
  reserved: TelemetryCapacityVector;
  observed: TelemetryCapacityVector;
}

export interface TelemetryActionAccepted {
  job_id: string;
  desired_version: number;
  state: string;
}

export type TelemetrySubscriptionAction = 'enable' | 'disable' | 'retry';

export interface TelemetrySimulatedFrame {
  sensor_path: string;
  wire_bytes: number;
  sample_count: number;
  encoding?: string;
  producer?: string;
  device?: string;
  request_id?: number;
}

export interface TelemetrySimulationResult {
  subscription_id: string;
  device_id: string;
  hostname: string;
  vendor: string;
  protocol_profile: string;
  wire_format: string;
  simulated_paths: string[];
  decoded_frames: TelemetrySimulatedFrame[];
  active_series: number;
  sample_rate: number;
  normalized_samples: string[];
  runtime: TelemetrySubscriptionStatus;
}
