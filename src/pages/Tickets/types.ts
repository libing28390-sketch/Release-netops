export type IncidentTicketStatus = 'open' | 'in_progress' | 'pending_confirmation' | 'closed' | 'cancelled' | 'merged' | string;

export type IncidentTicketAction =
  | 'assign'
  | 'claim'
  | 'start'
  | 'request_confirmation'
  | 'confirm_close'
  | 'cancel'
  | 'merge';

export interface IncidentTicket {
  id: string;
  ticket_number?: string;
  ticket_key?: string;
  title?: string;
  description?: string;
  type?: string;
  ticket_type?: string;
  priority?: string;
  status: IncidentTicketStatus;
  incident_id?: string;
  requester_id?: string;
  requester_username?: string;
  assignment_group_id?: string;
  assignment_group_name?: string;
  assignee_id?: string;
  assignee_username?: string;
  current_owner_username?: string;
  recovery_evidence?: unknown;
  evidence?: unknown;
  sla?: TicketSlaSummary;
  allowed_actions?: IncidentTicketAction[];
  created_at?: string;
  updated_at?: string;
  [key: string]: unknown;
}

export type TicketSourceType = 'incident' | 'service_request';

export interface UnifiedTicket {
  ticket_key: string;
  source_type: TicketSourceType;
  source_id?: string;
  request_id?: string;
  title: string;
  status: string;
  priority?: string;
  requester_username?: string;
  current_owner_username?: string;
  assignment_group_name?: string;
  assignee_username?: string;
  created_at?: string;
  updated_at?: string;
  allowed_actions?: string[];
  next_step?: string;
  [key: string]: unknown;
}

export type ServiceRequestFieldType = 'text' | 'textarea' | 'number' | 'select' | 'boolean';
export type ServiceCatalogFieldType = ServiceRequestFieldType;

export interface ServiceRequestField {
  key: string;
  label: string;
  type: ServiceRequestFieldType;
  required?: boolean;
  options?: string[];
  help?: string;
}

export interface ServiceCatalogItem {
  id: string;
  key: string;
  name: string;
  description?: string;
  current_version?: number;
  version: number;
  request_schema?: { fields?: ServiceRequestField[] };
  requires_approval?: boolean;
  assignment_group_id?: string;
  assignment_group_name?: string;
  approval_group_id?: string;
  fulfillment_instructions?: string;
  acceptance_criteria?: string;
  sla_policy_version_id?: string;
  active?: boolean;
}

export type ServiceRequestAction =
  | 'approve' | 'reject' | 'assign' | 'claim' | 'acknowledge' | 'start'
  | 'wait_external' | 'resume' | 'deliver' | 'confirm_complete' | 'return' | 'cancel' | 'link_change_order';

export interface ServiceRequest {
  id: string;
  request_number?: string;
  ticket_key?: string;
  source_type: 'service_request';
  title: string;
  priority?: string;
  status: string;
  requester_id?: string;
  requester_username?: string;
  assignment_group_id?: string;
  assignment_group_name?: string;
  assignee_id?: string;
  assignee_username?: string;
  current_owner_username?: string;
  details?: Record<string, unknown>;
  catalog_snapshot?: ServiceCatalogItem;
  allowed_actions?: ServiceRequestAction[];
  created_at?: string;
  updated_at?: string;
}

export interface ServiceRequestEvent {
  id: string;
  event_type: string;
  actor_username?: string;
  summary?: string;
  evidence?: unknown;
  details?: Record<string, unknown>;
  created_at?: string;
}

export interface TicketSlaClock {
  kind: string;
  status: string;
  configured: boolean;
  started_at?: string | null;
  deadline_at?: string | null;
  remaining_seconds?: number | null;
  calendar_timezone?: string | null;
}

export interface TicketSlaSummary {
  configured: boolean;
  clocks: TicketSlaClock[];
}

export interface TicketWorkCalendar {
  id: string;
  version_id: string;
  name: string;
  version: number;
  timezone: string;
  schedule: Record<string, Array<{ start: string; end: string }>>;
  holidays: string[];
}

export interface TicketSlaPolicy {
  id: string;
  version_id: string;
  active?: boolean;
  name: string;
  version: number;
  source_type: TicketSourceType;
  priority: 'P1' | 'P2' | 'P3' | 'P4';
  response_target_minutes?: number | null;
  restore_target_minutes?: number | null;
  fulfillment_target_minutes?: number | null;
  warning_before_minutes?: number | null;
  calendar_version_id?: string | null;
}

export interface TicketSummaryResponse {
  from: string;
  to: string;
  totals: {
    all: number;
    incident: number;
    service_request: number;
    active: number;
    closed: number;
  };
  by_priority: Array<{ priority: string; count: number }>;
  by_assignment_group: Array<{ id: string | null; name: string; count: number }>;
  durations_seconds: {
    first_response_avg: number | null;
    incident_restore_avg: number | null;
    service_fulfillment_avg: number | null;
    close_avg: number | null;
  };
  sample_counts: {
    first_response_avg: number;
    incident_restore_avg: number;
    service_fulfillment_avg: number;
    close_avg: number;
  };
  duration_basis: 'elapsed_utc_ticket_events' | string;
}

export interface ServiceRequestDetail {
  request: ServiceRequest;
  events: ServiceRequestEvent[];
  sla?: TicketSlaSummary;
  linked_change_orders?: LinkedChangeOrder[];
}

export interface IncidentTicketEvent {
  id?: string;
  action?: string;
  event_type?: string;
  actor_username?: string;
  summary?: string;
  message?: string;
  evidence?: unknown;
  details?: Record<string, unknown>;
  payload?: Record<string, unknown>;
  created_at?: string;
}

export interface LinkedChangeOrder {
  id: string;
  order_number?: string;
  title?: string;
  status?: string;
}

export interface IncidentTicketDetail {
  ticket: IncidentTicket;
  events: IncidentTicketEvent[];
  linked_change_orders: LinkedChangeOrder[];
}

export interface TicketAssignmentGroup {
  id: string;
  name: string;
  description?: string;
  active?: boolean;
  member_count?: number;
}

export interface TicketAssignmentMember {
  id?: string;
  user_id?: string;
  username: string;
  display_name?: string;
  role?: string;
}

export interface TicketActionPayload {
  assignment_group_id?: string;
  assignee_id?: string;
  reason?: string;
  summary?: string;
  evidence?: string;
  target_ticket_id?: string;
}
