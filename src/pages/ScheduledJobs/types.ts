export interface ScheduledJob {
  id: string;
  name: string;
  job_type: string;
  action_type: string;
  cron_expr: string;
  scheduled_at: string;
  device_scope: string;
  device_filter: string;
  commands: string;
  script_id: string;
  is_config: number;
  config_reason: string;
  enabled: number;
  status: string;
  approved_by: string;
  approved_at: string;
  last_run_at: string;
  last_run_status: string;
  run_count: number;
  use_admin_creds?: number;
  created_by: string;
  created_at: string;
  major_type?: string;
}

export interface NsotPreviewCommand {
  action_code: string | null;
  command?: string | null;
  command_source?: string | null;
  textfsm_template?: string | null;
  textfsm_source?: string | null;
  status?: string | null;
  condition?: string | null;
}

export interface NsotPreviewCollector {
  key: string;
  label: string;
  transport: string;
  conditional: boolean;
  status?: 'supported' | 'partial' | 'parser_missing' | 'unsupported' | 'projection' | null;
  commands: NsotPreviewCommand[];
}

export interface NsotPreviewGroup {
  platform: string;
  platform_label?: string;
  profile_label?: string | null;
  software_version?: string | null;
  release_number?: string | number | null;
  registry_release_number?: string | number | null;
  template_id: string;
  template_name: string;
  role?: string;
  device_count: number;
  collectors: NsotPreviewCollector[];
  notes: string[];
}

export interface NsotCollectionPreview {
  generated_at: string;
  target_count: number;
  groups: NsotPreviewGroup[];
}

export interface EligibleApprover {
  id: string;
  username: string;
  role: string;
}

export interface SystemScheduledJob {
  id: string;
  name_zh: string;
  name_en: string;
  description_zh: string;
  description_en: string;
  category?: string;
  action_type?: string;
  deep_link?: string | null;
  trigger?: string;
  next_run_at?: string | null;
}

export interface ScheduledJobsTabProps {
  t: (key: string) => string;
  language: string;
  showToast: (msg: string, type?: 'success' | 'error' | 'info') => void;
}

export interface FormState {
  name: string;
  action_type: string;
  cron_expr: string;
  device_scope: string;
  device_filter: string;
  commands: string;
  script_id: string;
  is_config: boolean;
  config_reason: string;
  use_admin_creds: boolean;
  major_type: string;
}

export interface ValidatedDevice {
  ip: string;
  hostname: string;
  tags: { id: string; label: string; label_zh: string; color: string }[];
}

export interface CollectionPlanFilters {
  site?: string;
  role?: string;
  category?: string;
  platform?: string;
}

export interface CollectionPlanOption {
  value: string;
  count: number;
}

export interface CollectionPlanBulkOptions {
  sites: CollectionPlanOption[];
  roles: CollectionPlanOption[];
  categories: CollectionPlanOption[];
  platforms: CollectionPlanOption[];
}

export type CollectionPlanBulkOperation = 'apply' | 'reset';

export interface CollectionPlanBulkPreviewRequest {
  operation: CollectionPlanBulkOperation;
  template_id?: string;
  filters: CollectionPlanFilters;
}

export interface CollectionPlanBulkSample {
  device_id: string | number;
  hostname?: string | null;
  ip_address?: string | null;
  role?: string | null;
  site?: string | null;
  platform?: string | null;
  current_template?: string | null;
}

export interface CollectionPlanBulkPreviewResponse {
  matched_count: number;
  overridden_count: number;
  sample: CollectionPlanBulkSample[];
  snapshot_token: string;
  operation: CollectionPlanBulkOperation;
  template_id?: string;
}

export interface CollectionPlanBulkPreview extends CollectionPlanBulkPreviewResponse {
  filters: CollectionPlanFilters;
}
