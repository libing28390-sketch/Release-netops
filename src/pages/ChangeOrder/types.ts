import type { User as UserOption, SessionUser, ConfigTemplate } from '../../types';

export interface ChangeOrder {
  id: string;
  order_number: string;
  title: string;
  incident_id?: string;
  description: string;
  order_type: string;
  priority: string;
  status: string;
  requester_id: string;
  requester_username: string;
  assigned_initial_reviewer_id: string;
  assigned_initial_reviewer_username: string;
  assigned_final_approver_id: string;
  assigned_final_approver_username: string;
  initial_reviewer_id: string;
  initial_reviewer_username: string;
  final_approver_id: string;
  final_approver_username: string;
  approver_id: string;
  approver_username: string;
  target_devices: { hostname: string; ip_address: string; username?: string; platform?: string }[];
  commands: string[];
  command_template?: unknown;
  rollback_plan: string;
  risk_level: string;
  scheduled_start: string;
  scheduled_end: string;
  actual_start: string;
  actual_end: string;
  result_summary: string;
  result_detail: Record<string, unknown>;
  authorization_exempt?: boolean;
  rejected_reason: string;
  control_sheet?: Record<string, any>;
  control_sheet_attachments?: ControlSheetAttachment[];
  control_sheet_missing?: boolean;
  created_at: string;
  updated_at: string;
}

export interface ControlSheetAttachment {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  uploaded_by_username: string;
  uploaded_at: string;
  download_url?: string;
}

export interface TimelineEvent {
  id: string;
  event_type: string;
  summary: string;
  actor_username: string;
  created_at: string;
}

export interface Summary {
  total: number;
  by_status: Record<string, number>;
  by_priority: Record<string, number>;
  by_type: Record<string, number>;
}

export interface DeviceOption {
  id: string;
  hostname: string;
  ip_address: string;
  platform?: string;
  asset_tag?: string;
}

export interface ScenarioPhasePreview {
  pre_check: string[];
  execute: string[];
  post_check: string[];
  rollback: string[];
}

export interface ScenarioVariable {
  key: string;
  label: string;
  label_zh?: string;
  type: string;
  required: boolean;
  placeholder?: string;
  options?: string[];
  platform_hints?: Record<string, string>;
}

export interface ScenarioTemplate {
  id: string;
  source_kind?: 'scenario' | 'config_template';
  source_template_id?: string;
  name: string;
  name_zh?: string;
  description?: string;
  description_zh?: string;
  category?: string;
  icon?: string;
  risk?: string;
  supported_platforms?: string[];
  default_platform?: string;
  variables?: ScenarioVariable[];
  platform_phases?: Record<string, Partial<ScenarioPhasePreview>>;
  templates?: ConfigTemplate[];
}

export interface PlatformMeta {
  name?: string;
  vendor?: string;
  icon?: string;
}

export interface CommandTemplateSnapshot {
  mode?: 'template';
  scenario_id: string;
  scenario_name?: string;
  scenario_name_zh?: string;
  platform: string;
  variables: Record<string, string>;
  preview: ScenarioPhasePreview;
  generated_at?: string;
}

export interface Props {
  language: string;
  t: (key: string) => string;
  users: UserOption[];
  scenarios: ScenarioTemplate[];
  configTemplates: ConfigTemplate[];
  platforms: Record<string, PlatformMeta>;
  currentUser: SessionUser;
  initialView?: 'all' | 'group_todo' | 'my_todo' | 'my_participated' | 'my_focus' | 'my_drafts' | 'create';
  findMatchingPlatform: (devicePlatform: string, platforms: string[] | Record<string, any>) => string | undefined;
}

export type WorkflowVisualState = 'done' | 'current' | 'pending' | 'error';
