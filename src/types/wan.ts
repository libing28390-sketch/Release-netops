export type WanHealthStatus = 'healthy' | 'degraded' | 'critical' | 'unavailable' | 'unknown';

export interface WanLink {
  id: string;
  link_name: string;
  site_id?: string;
  site_name?: string;
  device_id: string;
  interface_id: string;
  interface_name: string;
  if_index: number;
  provider?: string;
  circuit_number?: string;
  public_ip?: string;
  link_type: string;
  link_role: string;
  direction_mode: 'normal' | 'reversed' | string;
  contracted_download_bps: number;
  contracted_upload_bps: number;
  collection_interval_sec: number;
  timezone: string;
  enabled: boolean | number;
  maintenance_window?: string;
  notes?: string;
  sampled_at?: string | null;
  download_bps?: number | null;
  upload_bps?: number | null;
  download_util_pct?: number | null;
  upload_util_pct?: number | null;
  admin_status?: string;
  oper_status?: string;
  collection_status?: string;
  health_status?: WanHealthStatus;
  active_alert_count?: number;
  last_success_at?: string | null;
}

export interface WanLinkSample {
  id: string;
  link_id: string;
  sampled_at: string;
  download_bps?: number | null;
  upload_bps?: number | null;
  download_util_pct?: number | null;
  upload_util_pct?: number | null;
  in_error_delta?: number | null;
  out_error_delta?: number | null;
  in_discard_delta?: number | null;
  out_discard_delta?: number | null;
  in_error_rate?: number | null;
  out_error_rate?: number | null;
  in_discard_rate?: number | null;
  out_discard_rate?: number | null;
  oper_status?: string;
  collection_status?: string;
  quality_flags?: Record<string, unknown> | string;
}

export interface WanLinkHistoryResponse {
  link: WanLink;
  history_hours: number;
  history_minutes?: number;
  resolution?: number;
  start_time?: string;
  end_time?: string;
  history: WanLinkSample[];
  events: Array<{ id: string; metric: string; severity: string; status: string; title: string; message: string; started_at: string; recovered_at?: string | null }>;
}

export interface WanLinkOptionsResponse {
  devices: Array<{
    id: string;
    hostname?: string;
    ip_address?: string;
    site_id?: string;
    site_name?: string;
    site?: string;
    platform?: string;
    role?: string;
    device_category?: string;
  }>;
  interfaces: Array<{ id: string; device_id: string; interface_name: string; if_index?: number | null; description?: string; speed?: number; oper_status?: string }>;
  sites: Array<{ id: string; site_name: string; site_code?: string; timezone?: string }>;
}
