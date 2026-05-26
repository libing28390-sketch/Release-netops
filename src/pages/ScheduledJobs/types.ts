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
