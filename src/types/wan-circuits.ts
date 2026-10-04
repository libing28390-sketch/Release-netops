import type {
  WanHealthStatus,
  WanLink,
  WanLinkHistoryResponse,
  WanLinkOptionsResponse,
} from './wan';

export type WanCircuitSide = 'A' | 'Z';
export type WanCircuitEndpointType = 'managed' | 'unmanaged';
export type WanCircuitCounterOrientation = 'normal' | 'reversed';
export type WanCircuitMeasurementScope = 'dedicated' | 'shared_interface';

export interface WanCircuitEndpoint {
  id?: string;
  side: WanCircuitSide;
  endpoint_type: WanCircuitEndpointType;
  site_id: string;
  device_id?: string | null;
  interface_id?: string | null;
  if_index?: number | null;
  site_name?: string;
  endpoint_name?: string;
  counter_orientation: WanCircuitCounterOrientation;
  measurement_scope: WanCircuitMeasurementScope;
  binding_version?: number | null;
  created_at?: string;
  updated_at?: string;
}

export interface WanCircuitItem extends WanLink {
  endpoints?: WanCircuitEndpoint[];
  configuration_version?: number;
  current?: boolean | Partial<WanLink> | null;
  contract_start?: string | null;
  contract_end?: string | null;
  sla_target_pct?: number | null;
  grafana_url?: string | null;
  diagnostics_url?: string | null;
}

export interface WanCircuitListResponse {
  items: WanCircuitItem[];
  total: number;
  page: number;
  page_size: number;
  summary?: Record<string, number | string | null>;
}

export interface WanCircuitDetailResponse {
  item: WanCircuitItem;
}

export interface WanCircuitHistoryResponse extends Omit<WanLinkHistoryResponse, 'link'> {
  link?: WanCircuitItem;
}

export interface WanCircuitSlaResponse {
  status: 'insufficient_data' | 'available' | string;
  reason_code?: string | null;
  window_start?: string | null;
  window_end?: string | null;
  availability?: {
    value?: number | null;
    lower_bound?: number | null;
    upper_bound?: number | null;
  } | null;
  coverage_pct?: number | null;
  /** Current backend returns a numeric slot count; newer responses may return a distribution object. */
  slots?: number | {
    up?: number;
    down?: number;
    unknown?: number;
    maintenance?: number;
  } | null;
  availability_pct?: number | null;
  reason?: string | null;
  policy_version?: number | null;
  policy?: WanCircuitSlaPolicy | null;
}

export interface WanCircuitSlaPolicy {
  availability_target_pct: number;
  latency_target_ms?: number | null;
  loss_target_pct?: number | null;
  measurement_window_days: number;
  minimum_coverage_pct: number;
  minimum_rtt_samples: number;
  minimum_loss_packets: number;
  availability_rule: 'any_success' | 'all_success';
  timezone: string;
  maintenance_excluded: boolean;
}

export interface WanCircuitSlaPolicyPayload extends WanCircuitSlaPolicy {
  expected_version: number;
}

export interface WanProbeTarget {
  id: string;
  target_name: string;
  host: string;
  probe_type: string;
  is_active?: boolean;
}

export type WanProbePurpose = 'availability' | 'quality' | 'application';

export interface WanProbeRouteEvidence {
  evidence_status?: string | null;
  [key: string]: unknown;
}

export interface WanProbeBinding {
  id: string;
  link_id: string;
  target_id: string;
  link_name?: string;
  target_name?: string;
  host?: string;
  probe_type?: string;
  purpose?: WanProbePurpose | string;
  route_mode: 'default' | 'source_ip' | string;
  source_ip?: string | null;
  priority?: number;
  enabled?: boolean;
  route_evidence?: WanProbeRouteEvidence | null;
}

export interface WanProbeBindingPayload {
  link_id: string;
  target_id: string;
  route_mode: 'default' | 'source_ip';
  source_ip: string;
  priority: number;
  enabled: boolean;
  purpose: WanProbePurpose;
}

export interface WanCircuitFormPayload extends Partial<WanLink> {
  endpoints: WanCircuitEndpoint[];
  contracted_download_mbps: number;
  contracted_upload_mbps: number;
  expected_version?: number;
}

export type WanCircuitOptions = WanLinkOptionsResponse;

export type WanCircuitStatus = WanHealthStatus | 'unknown';
