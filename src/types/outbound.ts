export type OutboundStatus = 'healthy' | 'degraded' | 'unavailable' | 'unknown';

export type OutboundProbeType = 'TCP_CONNECT' | 'HTTP_GET' | 'HTTPS_GET' | 'DNS_RESOLVE' | 'ICMP_PING';

export interface OutboundTarget {
  id: string;
  target_name: string;
  host: string;
  port: number;
  probe_type: OutboundProbeType | string;
  group_name: string;
  url?: string;
  expected_status_code?: number;
  expected_keyword?: string;
  timeout_ms?: number;
  enabled: boolean | number;
  is_active?: boolean | number;
  created_at?: string;
  updated_at?: string;
}

export interface OutboundTargetResult {
  target_id: string;
  target_name: string;
  group: string;
  probe_type: string;
  success: boolean;
  latency_ms?: number | null;
  error_type?: string | null;
  error_message?: string | null;
  resolved_ip?: string | null;
  http_status?: number | null;
  dns_answers?: string[];
}

export interface OutboundGroupStatus {
  status: OutboundStatus;
  success_count: number;
  total_count: number;
  availability_percent: number;
}

export interface OutboundHistoryPoint {
  finished_at: string;
  status: OutboundStatus;
  success_count: number;
  total_targets: number;
  availability_percent: number;
  average_latency_ms?: number | null;
  public_ip?: string;
  public_ip_changed?: boolean | number;
}

export interface OutboundStatusPayload {
  run_id?: string;
  node_id?: string;
  node_name?: string;
  status: OutboundStatus;
  raw_status?: OutboundStatus;
  status_reason: string;
  success_count: number;
  total_count: number;
  availability_percent: number;
  average_latency_ms?: number | null;
  public_ip?: string;
  public_ip_changed?: boolean;
  consecutive_failure_count: number;
  consecutive_recovery_count?: number;
  checked_at: string;
  groups: Record<string, OutboundGroupStatus>;
  targets: OutboundTargetResult[];
}

export interface OutboundHealthResponse {
  current: OutboundStatusPayload | null;
  history: OutboundHistoryPoint[];
  history_hours?: number;
  history_total_points?: number;
  targets: OutboundTarget[];
}

export interface OutboundTargetHistoryPoint extends OutboundTargetResult {
  id: string;
  run_id: string;
  sampled_at: string;
  run_status?: OutboundStatus;
  public_ip?: string | null;
}

export interface OutboundTargetHistorySummary {
  sample_count: number;
  success_count: number;
  failure_count: number;
  availability_percent: number;
  average_latency_ms?: number | null;
  p50_latency_ms?: number | null;
  p95_latency_ms?: number | null;
  max_latency_ms?: number | null;
}

export interface OutboundTargetHistoryResponse {
  target: OutboundTarget;
  history_hours: number;
  history_total_points?: number;
  summary: OutboundTargetHistorySummary;
  latest: OutboundTargetHistoryPoint | null;
  history: OutboundTargetHistoryPoint[];
}
