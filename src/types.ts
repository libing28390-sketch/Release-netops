// Shared type definitions for Nexora
// Extracted from App.tsx for reuse across components

export interface ConfigVersion {
  id: string;
  timestamp: string;
  content: string;
  author: string;
  description: string;
}

export interface Device {
  id: string;
  hostname: string;
  ip_address: string;
  platform: string;
  status: 'online' | 'offline' | 'pending';
  compliance: 'compliant' | 'non-compliant' | 'unknown';
  lifecycle_status?: 'staging' | 'production' | 'maintenance' | 'decommissioned';
  sn: string;
  model: string;
  version: string;
  role: string;
  site: string;
  site_id?: string;
  site_name?: string;
  site_code?: string;
  site_country?: string;
  site_state_province?: string;
  site_city?: string;
  site_district?: string;
  region?: string;
  uptime: string;
  connection_method: 'ssh' | 'netconf';
  current_config?: string;
  config_history: ConfigVersion[];
  device_category?: string;
  username?: string;
  password?: string;
  enable_password?: string;
  normal_username?: string;
  normal_password?: string;
  admin_username?: string;
  admin_password?: string;
  auth_model?: 'single' | 'dual';
  priv_username?: string;
  credential_source?: 'local' | 'vault';
  vault_path?: string;
  onboarding_status?: 'pending_credentials' | 'credentials_set' | 'verified' | 'active';
  onboarding_updated_at?: string;
  password_last_rotated?: string;
  password_expires_at?: string;
  cpu_usage?: number;
  memory_usage?: number;
  cpu_history?: number[];
  memory_history?: number[];
  temp?: number;
  fan_status?: 'ok' | 'fail';
  psu_status?: 'redundant' | 'single' | 'fail';
  snmp_community?: string;
  snmp_configured?: boolean;
  snmp_port?: number;
  management_port?: number;
  sys_name?: string;
  sys_location?: string;
  sys_contact?: string;
  health_status?: 'healthy' | 'warning' | 'critical' | 'unknown';
  health_score?: number;
  health_summary?: string;
  health_reasons?: string[];
  open_alert_count?: number;
  critical_open_alerts?: number;
  major_open_alerts?: number;
  warning_open_alerts?: number;
  interface_down_count?: number;
  interface_flap_count?: number;
  high_util_interface_count?: number;
  interface_error_count?: number;
  // Plan-A: asset linkage fields (from LEFT JOIN physical_assets)
  asset_id?: string;
  vendor?: string;
  asset_tag?: string;
  datacenter?: string;
  rack?: string;
  rack_id?: string;
  rack_code?: string;
  rack_name?: string;
  rack_floor?: string;
  rack_room?: string;
  rack_row?: string;
  floor?: string;
  rack_unit?: string;
  department?: string;
  warranty_expiry?: string;
  purchase_date?: string;
  business_ip?: string;
  vlan?: string;
  uplink_switch?: string;
  uplink_port?: string;
  interface_data?: {
    name: string; status: string; speed_mbps: number;
    interface_type?: string; parent_interface_id?: string | null; channel_group?: number | null; aggregation_protocol?: string;
    in_octets: number; out_octets: number; description: string;
    in_bps?: number; out_bps?: number;
    in_errors?: number; out_errors?: number;
    in_discards?: number; out_discards?: number;
    in_ucast_pkts?: number; out_ucast_pkts?: number;
    bw_in_pct?: number; bw_out_pct?: number;
    last_change_secs?: number; flapping?: boolean;
  }[];
  tags?: TagDefinition[];
  tag_ids?: string[];
}

export interface DeviceConnectionCheckSummary {
  status: 'ok' | 'tcp_fail' | 'ssh_auth_fail' | 'ssh_timeout' | 'ssh_transport' | 'ssh_legacy' | 'fail';
  mode: 'quick' | 'deep';
  checked_at: string;
  error_code?: string;
  auth_model?: 'single' | 'dual';
  ssh?: boolean;
  ssh_summary?: string;
  ssh_error?: string;
  ping?: boolean;
  ping_error?: string;
  roles?: Record<string, {
    success: boolean;
    error?: string;
    summary?: string;
    error_code?: string;
  }>;
}

export interface Job {
  id: string;
  device_id: string;
  task_name: string;
  status: 'pending' | 'running' | 'success' | 'failed' | 'rolled_back';
  output?: string;
  created_at: string;
}

export interface AuditEvent {
  id: string;
  event_type: string;
  category: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
  status: string;
  actor_id?: string;
  actor_username?: string;
  actor_role?: string;
  source_ip?: string;
  target_type?: string;
  target_id?: string;
  target_name?: string;
  device_id?: string;
  job_id?: string;
  execution_id?: string;
  snapshot_id?: string;
  summary: string;
  details?: Record<string, any>;
  details_json?: string;
  created_at: string;
}

export interface ComplianceFinding {
  id: string;
  fingerprint: string;
  rule_id: string;
  device_id: string;
  run_id?: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
  category: string;
  title: string;
  description: string;
  detail?: string;
  remediation?: string;
  status: 'open' | 'in_progress' | 'resolved' | 'accepted_risk';
  owner?: string;
  note?: string;
  first_seen: string;
  last_seen: string;
  resolved_at?: string;
  created_at: string;
  updated_at: string;
  hostname?: string;
  ip_address?: string;
}

export interface ComplianceRunPoint {
  run_id: string;
  created_at: string;
  score: number;
  total_findings: number;
  device_count: number;
}

export interface ComplianceOverview {
  total_findings: number;
  open_findings: number;
  resolved_findings: number;
  in_progress_findings: number;
  accepted_risk_findings: number;
  latest_score: number;
  severity_breakdown: Record<string, number>;
  category_breakdown: Record<string, number>;
  run_history: ComplianceRunPoint[];
}

export interface ScheduledTask {
  id: number;
  device_id: string;
  task_name: string;
  schedule_type: 'once' | 'recurring';
  interval?: 'daily' | 'weekly' | 'monthly';
  scheduled_time: string;
  timezone: string;
  status: 'active' | 'completed' | 'failed';
}

export interface Script {
  id: string;
  name: string;
  content: string;
  type: string;
  description: string;
  parameters?: string[];
}

export interface ConfigTemplate {
  id: string;
  name: string;
  type: string;
  lastUsed: string;
  category: string;
  vendor?: string;
  content: string;
  rollback?: string;
}

export interface ConfigSnapshot {
  id: string;
  device_id: string;
  hostname: string;
  ip_address?: string;
  vendor: string;
  trigger: 'manual' | 'auto' | 'change' | 'scheduled';
  author: string;
  content?: string;
  created_at: string;
}

export interface DiffLine {
  type: 'context' | 'add' | 'remove';
  lineA?: number;
  lineB?: number;
  content: string;
}

export interface NotificationChannel {
  webhook_url: string;
  enabled: boolean;
  secret?: string; // DingTalk 签名密钥（可选）
}

export interface NotificationChannels {
  feishu?: NotificationChannel;
  dingtalk?: NotificationChannel;
  wechat?: NotificationChannel;
}

export interface User {
  id: string;
  username: string;
  role: string;
  lastLogin?: string;
  status?: string;
  avatar_url?: string;
  group_name?: string;
  change_groups?: string[];
  notification_channels?: NotificationChannels;
  preferred_language?: 'zh' | 'en';
  fixed_pin?: string;
  display_name?: string;
  phone?: string;
  email?: string;
}

export type ThemeMode = 'light' | 'dark';

export interface SessionUser {
  id?: string;
  username: string;
  role?: string;
  avatar_url?: string;
  group_name?: string;
  change_groups?: string[];
  preferred_language?: 'zh' | 'en';
  display_name?: string;
  phone?: string;
  email?: string;
}

export interface NotificationItem {
  id: string;
  title: string;
  message: string;
  time: string;
  source?: string;
  severity?: 'low' | 'medium' | 'high' | 'major' | 'critical' | 'warning';
  read: boolean;
}

export type AlertWorkflowStatus = 'open' | 'acknowledged' | 'investigating' | 'suppressed' | 'resolved';

export interface AlertRecord {
  id: string;
  dedupe_key: string;
  source: string;
  severity: 'low' | 'medium' | 'high' | 'major' | 'critical' | 'warning';
  title: string;
  message: string;
  device_id?: string | null;
  interface_name?: string | null;
  hostname?: string | null;
  ip_address?: string | null;
  site?: string | null;
  created_at: string;
  resolved_at?: string | null;
  workflow_status: AlertWorkflowStatus;
  assignee?: string | null;
  ack_by?: string | null;
  ack_at?: string | null;
  note?: string;
  updated_at?: string | null;
  occurrence_count?: number;
  duration_seconds?: number | null;
  is_open?: boolean;
}

export interface AlertSummary {
  open_count: number;
  critical_open: number;
  major_open: number;
  warning_open: number;
  acknowledged_open: number;
  suppressed_open?: number;
  assigned_open: number;
  alerts_24h: number;
  resolved_24h: number;
  avg_mttr_minutes?: number | null;
  avg_mtta_minutes?: number | null;
}

export interface AlertListResponse {
  items: AlertRecord[];
  total: number;
  page: number;
  page_size: number;
  filters?: {
    sites?: string[];
    assignees?: string[];
  };
  status_counts?: Record<string, number>;
}

export interface AlertDetailResponse {
  item: AlertRecord;
  timeline: AlertRecord[];
}

export interface AlertMaintenanceWindow {
  id: string;
  name: string;
  target_ip: string;
  target_ips?: string[];
  title_pattern?: string;
  message_pattern?: string;
  selection_mode?: 'conditions' | 'resources';
  condition_logic?: AlertMaintenanceConditionLogic;
  match_conditions?: AlertMaintenanceCondition[];
  starts_at: string;
  ends_at: string;
  notify_user_ids: string[];
  reason?: string;
  status: string;
  runtime_status: 'scheduled' | 'active' | 'expired' | 'cancelled';
  created_by: string;
  created_at: string;
  updated_at: string;
  last_match_count?: number;
}

export interface AlertMaintenanceListResponse {
  items: AlertMaintenanceWindow[];
  total: number;
  page: number;
  page_size: number;
}

export interface AlertMaintenancePreview {
  count: number;
  items: Array<{
    id: string;
    title: string;
    message: string;
    interface_name?: string | null;
    created_at: string;
    hostname?: string | null;
    ip_address?: string | null;
    site?: string | null;
  }>;
}

export type AlertMaintenanceConditionField = 'alert_description' | 'alert_ip' | 'alert_level';

export type AlertMaintenanceConditionOperator = 'contains' | 'equals' | 'not_contains' | 'not_equals' | 'regex';

export type AlertMaintenanceConditionLogic = 'all' | 'any' | 'none';

export interface AlertMaintenanceCondition {
  field: AlertMaintenanceConditionField;
  operator: AlertMaintenanceConditionOperator;
  value: string;
}

export type AlertRuleMetricType =
  | 'cpu'
  | 'memory'
  | 'interface_util'
  | 'interface_down'
  | 'interconnect_down'
  | 'temperature_high'
  | 'snmp_unreachable'
  | 'lldp_neighbor_lost'
  | 'fan_failure'
  | 'power_supply_failure'
  | 'interface_error_rate_high'
  | 'interface_flap'
  | 'bgp_neighbor_down'
  | 'ospf_neighbor_down'
  | 'bfd_session_down'
  | 'ping_unreachable'
  | 'host_cpu'
  | 'host_memory'
  | 'host_disk'
  | 'srv_cpu_load'
  | 'srv_cpu_util'
  | 'srv_iowait'
  | 'srv_mem_avail'
  | 'srv_swap'
  | 'srv_disk_util'
  | 'srv_disk_inode'
  | 'srv_io_latency'
  | 'srv_tcp_retrans'
  | 'srv_tcp_conns'
  | 'srv_process_health';

export type AlertRuleScopeType = 'global' | 'site' | 'device' | 'interface';

export type AlertRuleScopeMatchMode = 'exact' | 'contains' | 'prefix' | 'glob';

export interface AlertRuleSettings {
  id?: string;
  name: string;
  metric_type: AlertRuleMetricType;
  scope_type: AlertRuleScopeType;
  scope_match_mode: AlertRuleScopeMatchMode;
  scope_value: string;
  severity: 'critical' | 'major' | 'warning';
  threshold?: number | null;
  for_duration_seconds: number;
  enabled: boolean;
  aggregation_mode: 'dedupe_key';
  notification_repeat_window_seconds: number;
  notify_on_active: boolean;
  notify_on_recovery: boolean;
  notify_on_reopen_after_maintenance: boolean;
  created_by?: string;
  created_at?: string;
  updated_by?: string;
  updated_at?: string;
}

export interface AlertRuleListResponse {
  items: AlertRuleSettings[];
  total: number;
  page: number;
  page_size: number;
}

export interface AlertRulePreview {
  alerts_24h: number;
  resolved_24h: number;
  repeated_key_count: number;
  top_repeated_alerts: Array<{
    dedupe_key: string;
    title: string;
    severity: string;
    event_count: number;
    last_seen: string;
  }>;
  open_alert_groups: Array<{
    title: string;
    severity: string;
    open_count: number;
  }>;
}

export interface AlertRuleHistoryItem {
  id: string;
  rule_id: string;
  changed_by: string;
  created_at: string;
  snapshot: AlertRuleSettings;
}

export interface HostResourceSnapshot {
  status: 'healthy' | 'degraded' | 'critical';
  metrics_available: boolean;
  cpu_percent: number | null;
  memory_percent: number | null;
  memory_used_gb: number | null;
  memory_total_gb: number | null;
  disk_percent: number | null;
  disk_used_gb: number;
  disk_total_gb: number;
  disk_free_gb: number;
  load_1m: number | null;
  uptime_hours: number | null;
  database_status: string;
  database_ok: boolean;
  process_memory_mb: number | null;
  process_cpu_percent: number | null;
  hostname: string | null;
  platform: string | null;
  updated_at: string;
  active_alert_count?: number;
  active_alerts?: HostResourceAlert[];
}

export interface HostResourceAlert {
  id?: string;
  dedupe_key?: string;
  severity: 'major' | 'critical';
  title: string;
  message: string;
  metric_key?: string;
  created_at?: string;
  resolved_at?: string | null;
}

export interface HostResourceTrendPoint {
  ts: string;
  status: 'healthy' | 'degraded' | 'critical';
  cpu_percent: number | null;
  memory_percent: number | null;
  disk_percent: number | null;
  load_1m: number | null;
  process_memory_mb: number | null;
  process_cpu_percent: number | null;
  memory_used_gb: number | null;
  memory_total_gb: number | null;
  disk_used_gb: number | null;
  disk_total_gb: number | null;
  disk_free_gb: number | null;
  uptime_hours: number | null;
  database_ok: number;
  database_status: string;
}

export interface HostResourceHistoryPayload {
  current: HostResourceSnapshot;
  series: HostResourceTrendPoint[];
  alerts: HostResourceAlert[];
  range_hours: number;
  resolution_hint?: '1m' | '5m' | '30m';
  sample_count?: number;
  thresholds: Record<string, { warn: number; critical: number; title: string; title_zh: string }>;
}

export interface DeviceHealthOverview {
  total_devices: number;
  average_score: number;
  healthy: number;
  warning: number;
  critical: number;
  unknown: number;
  top_risky_devices: Device[];
}

export interface DeviceHealthAlertItem {
  id: string;
  severity: string;
  title: string;
  message: string;
  interface_name?: string;
  created_at: string;
}

export interface DeviceHealthDetailResponse {
  device: Device;
  recent_open_alerts: DeviceHealthAlertItem[];
}

export interface DeviceHealthHistoryPoint {
  ts: string;
  average_score: number;
  total_devices: number;
  healthy: number;
  warning: number;
  critical: number;
  unknown: number;
}

export interface DeviceHealthHistoryResponse {
  range_hours: number;
  sample_count: number;
  series: DeviceHealthHistoryPoint[];
}

export interface DeviceHealthTrendPoint {
  ts: string;
  status: string;
  health_status: string;
  health_score: number;
  open_alert_count: number;
  critical_open_alerts: number;
  major_open_alerts: number;
  warning_open_alerts: number;
  interface_down_count: number;
  interface_flap_count: number;
  high_util_interface_count: number;
  interface_error_count: number;
  health_summary: string;
  health_reasons: string[];
}

export interface DeviceHealthTrendDevice {
  id: string;
  hostname: string;
  ip_address: string;
  platform: string;
  role: string;
  site: string;
}

export interface DeviceHealthTrendResponse {
  device: DeviceHealthTrendDevice | null;
  range_hours: number;
  sample_count: number;
  series: DeviceHealthTrendPoint[];
}

export const PLATFORM_LABELS: Record<string, string> = {
  cisco_ios: 'Cisco IOS',
  cisco_xe: 'Cisco IOS-XE',
  cisco_nxos: 'Cisco NX-OS',
  cisco_iosxr: 'Cisco IOS-XR',
  huawei_vrp: 'Huawei VRP',
  huawei_vrpv8: 'Huawei VRP8',
  hp_comware: 'H3C Comware V5',
  h3c_comware: 'H3C Comware V7',
  h3c_comware9: 'H3C Comware V9',
  arista_eos: 'Arista EOS',
  juniper_junos: 'Juniper Junos',
  ruijie_rgos: 'Ruijie RGOS',
  ruijie_os: 'Ruijie RGOS (legacy)',
  zte_zxros: 'ZTE ZXROS',
  maipu: 'Maipu Network OS',
};

export const getPlatformLabel = (platform: string) => PLATFORM_LABELS[platform] || platform;

export const getVendorFromPlatform = (platform: string) => {
  if (!platform) return 'Other';
  const p = platform.toLowerCase();
  if (p.includes('cisco')) return 'Cisco';
  if (p.includes('juniper')) return 'Juniper';
  if (p.includes('huawei') || p.includes('ne4') || p.includes('ne5') || p.includes('cx6')) return 'Huawei';
  if (p.includes('h3c') || p.includes('comware') || p.includes('vsr')) return 'H3C';
  if (p.includes('arista')) return 'Arista';
  if (p.includes('ruijie') || p.includes('rgos')) return 'Ruijie';
  if (p.includes('zte') || p.includes('zxros')) return 'ZTE';
  if (p.includes('maipu')) return 'Maipu';
  return 'Other';
};

// ─── Tag System Types ────────────────────────

export type TagCategory = 'device_type' | 'vendor' | 'os' | 'role' | 'env' | 'function' | 'status' | 'custom';

export interface TagDefinition {
  id: string;
  category: TagCategory;
  value: string;
  label: string;
  label_zh: string;
  color: string;
  icon: string;
  description: string;
  sort_order: number;
  built_in: number;       // 1=预定义, 0=自定义
  created_at: string;
}

export interface DeviceTag extends TagDefinition {
  assigned_at: string;
  created_by: string;
}

export interface TagStatistics {
  total_definitions: number;
  total_assignments: number;
  tagged_devices: number;
  categories: Record<string, number>;
  top_used: Array<TagDefinition & { device_count: number }>;
}

export const TAG_CATEGORY_LABELS: Record<TagCategory, { en: string; zh: string }> = {
  device_type: { en: 'Device Type', zh: '设备类型' },
  vendor:      { en: 'Vendor',      zh: '厂商' },
  os:          { en: 'OS',          zh: '操作系统' },
  role:        { en: 'Role',        zh: '角色' },
  env:         { en: 'Environment', zh: '环境' },
  function:    { en: 'Function',    zh: '功能' },
  status:      { en: 'Availability', zh: '在线状态' },
  custom:      { en: 'Custom',      zh: '自定义' },
};
