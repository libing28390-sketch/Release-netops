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
  authorization_mode?: string;
  created_by: string;
  created_at: string;
  updated_by?: string;
  updated_at?: string;
  major_type?: string;
  authorization_grant?: ScheduledJobAuthorizationGrant;
  allowed_actions?: string[];
}

export type TicketSourceType = 'incident' | 'service_request';

export interface ScheduledJobAuthorizationGrantInput {
  valid_until: string;
  max_runs: number;
  max_targets: number;
  scope: { type: string; filter: string };
  ticket_source_type: TicketSourceType;
  ticket_id: string;
  change_order_id?: string;
}

export interface ScheduledJobAuthorizationGrant extends ScheduledJobAuthorizationGrantInput {
  grant_id: string;
  version?: number;
  status: 'active' | 'expired' | 'exhausted' | 'revoked' | 'reauthorization_required' | string;
  template_version?: number | string;
  manifest_hash?: string;
  used_runs: number;
  remaining_runs: number;
  ticket_number?: string;
  ticket_title?: string;
  change_order_number?: string;
  allowed_actions?: string[];
}

export type ScheduledJobRunOutcome = 'succeeded' | 'partial_failure' | 'failed';

export interface ScheduledJobRun {
  run_id: string;
  scheduled_for?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  status: string;
  target_count?: number | null;
  success_count?: number | null;
  failure_count?: number | null;
  summary?: string | null;
  error?: string | null;
  authorization_version?: number | string | null;
  ticket_source_type?: TicketSourceType | null;
  ticket_id?: string | null;
  ticket_number?: string | null;
  ticket_title?: string | null;
  change_order_id?: string | null;
  change_order_number?: string | null;
  allowed_actions?: string[];
}

export interface ScheduledJobRunsResponse {
  items: ScheduledJobRun[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

export interface AuthorizationGrantForm {
  valid_until: string;
  max_runs: string;
  max_targets: string;
  ticket_source_type: TicketSourceType;
  ticket_id: string;
  change_order_id: string;
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
  tenant_id: string;
  verification_methods: ApprovalVerificationMethod[];
}

export type ApprovalVerificationMethod = 'mfa' | 'email' | 'feishu';

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
  authorization_grant: AuthorizationGrantForm;
  enabled: boolean;
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
