import type { Device } from '../../types';

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
  check_items?: string[];
  description?: string;
  job_id?: string;
  run_at?: string;
}

export interface InspectionRun {
  id: string;
  schedule_id?: string;
  trigger_type: string;
  scope_type: string;
  scope_filter: string;
  status: string;
  started_at: string;
  completed_at?: string;
  total_devices: number;
  success_count: number;
  failed_count: number;
  unreachable_count: number;
  healthy_count: number;
  warning_count: number;
  critical_count: number;
  avg_health_score: number;
  created_by: string;
}

export interface ExecutionScheduleTabProps {
  t: (key: string) => string;
  language: string;
  showToast: (msg: string, type?: 'success' | 'error' | 'info') => void;
  initialTab?: 'schedules' | 'history';
  devices: Device[];
  onRerun?: (log: any) => void;
}

export interface FormState {
  name: string;
  action_type: string;
  scheduled_at: string;
  device_scope: string;
  device_filter: string;
  commands: string;
  script_id: string;
  is_config: boolean;
  config_reason: string;
  use_admin_creds: boolean;
  major_type: string;
  check_items: string[];
  description: string;
}

export interface ValidatedDevice {
  ip: string;
  hostname: string;
  tags: { id: string; label: string; label_zh: string; color: string }[];
}

export interface EligibleApprover {
  id: string;
  username: string;
  role: string;
}

export interface UnifiedExecutionLog {
  id: string;
  source: 'inspection' | 'playbook';
  started_at: string;
  trigger_type: 'manual' | 'plan' | 'job';
  status: string;
  total_devices: number;
  success_count: number;
  failed_count: number;
  partial_count?: number;
  avg_health_score?: number;
  created_by: string;
  name: string;
}

export type InspSubTab = 'schedules' | 'history';
export type InspDetailTab = 'raw' | 'snapshot' | 'analysis' | 'compliance';
