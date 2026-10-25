import { authHeaders } from '../../api/http';
import type {
  IncidentTicket,
  IncidentTicketAction,
  IncidentTicketDetail,
  ServiceCatalogItem,
  ServiceRequest,
  ServiceRequestAction,
  ServiceRequestDetail,
  TicketActionPayload,
  TicketAssignmentGroup,
  TicketAssignmentMember,
  TicketSourceType,
  TicketSlaPolicy,
  TicketSummaryResponse,
  TicketWorkCalendar,
  UnifiedTicket,
} from './types';

interface TicketApiEnvelope<T> {
  success?: boolean;
  data?: T;
  total?: number;
  detail?: unknown;
  message?: string;
}

export class TicketApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'TicketApiError';
    this.status = status;
  }
}

const errorMessage = (payload: TicketApiEnvelope<unknown>, status: number): string => {
  const detail = payload.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (detail && typeof detail === 'object' && 'message' in detail && typeof detail.message === 'string') return detail.message;
  if (payload.message?.trim()) return payload.message;
  return `HTTP ${status}`;
};

const requestTicketApi = async <T>(url: string, init: RequestInit = {}): Promise<TicketApiEnvelope<T>> => {
  const headers = new Headers(authHeaders(Boolean(init.body)));
  new Headers(init.headers || {}).forEach((value, key) => headers.set(key, value));
  const response = await fetch(url, { ...init, headers });
  const payload = await response.json().catch(() => ({})) as TicketApiEnvelope<T>;
  if (response.status === 401) window.dispatchEvent(new Event('netops:auth-expired'));
  if (!response.ok || payload.success === false) throw new TicketApiError(response.status, errorMessage(payload, response.status));
  return payload;
};

export interface IncidentTicketListParams {
  page: number;
  pageSize: number;
  status: string;
  search: string;
  myTodo: boolean;
  signal?: AbortSignal;
}

export interface UnifiedTicketListParams extends IncidentTicketListParams {
  type: 'all' | TicketSourceType;
}

export const listIncidentTickets = async ({ page, pageSize, status, search, myTodo, signal }: IncidentTicketListParams) => {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
    status,
    search,
    my_todo: String(myTodo),
  });
  const result = await requestTicketApi<IncidentTicket[]>(`/api/tickets/incidents?${params}`, { signal });
  return { items: Array.isArray(result.data) ? result.data : [], total: Number(result.total) || 0 };
};

export const listUnifiedTickets = async ({ page, pageSize, status, search, myTodo, type, signal }: UnifiedTicketListParams) => {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
    type,
    status,
    search,
    my_todo: String(myTodo),
  });
  const result = await requestTicketApi<UnifiedTicket[]>(`/api/tickets?${params}`, { signal });
  return { items: Array.isArray(result.data) ? result.data : [], total: Number(result.total) || 0 };
};

export const getTicketSummary = async (from: string, to: string, signal?: AbortSignal): Promise<TicketSummaryResponse> => {
  const params = new URLSearchParams({ from, to });
  const result = await requestTicketApi<TicketSummaryResponse>(`/api/tickets/summary?${params}`, { signal });
  if (!result.data) throw new Error('工单统计响应格式无效');
  return result.data;
};

export const getServiceCatalog = async (signal?: AbortSignal): Promise<ServiceCatalogItem[]> => {
  const result = await requestTicketApi<ServiceCatalogItem[]>('/api/service-catalog', { signal });
  return Array.isArray(result.data) ? result.data : [];
};

export const createServiceCatalogItem = async (body: { key: string; name: string; description: string }): Promise<ServiceCatalogItem> => {
  const result = await requestTicketApi<ServiceCatalogItem>('/api/service-catalog', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (!result.data?.id) throw new Error('创建服务目录失败：响应缺少目录编号');
  return result.data;
};

export type ServiceCatalogVersionPayload = Pick<ServiceCatalogItem,
  'request_schema' | 'requires_approval' | 'assignment_group_id' | 'approval_group_id' |
  'fulfillment_instructions' | 'acceptance_criteria' | 'sla_policy_version_id'>;

export const createServiceCatalogVersion = async (catalogId: string, body: ServiceCatalogVersionPayload): Promise<ServiceCatalogItem> => {
  const result = await requestTicketApi<ServiceCatalogItem>(`/api/service-catalog/${encodeURIComponent(catalogId)}/versions`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (!result.data?.id) throw new Error('发布服务目录版本失败：响应缺少目录编号');
  return result.data;
};

export const createServiceRequest = async (body: {
  catalog_item_id: string;
  version: number;
  title: string;
  details: Record<string, unknown>;
}): Promise<ServiceRequest> => {
  const result = await requestTicketApi<ServiceRequest>('/api/service-requests', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (!result.data?.id) throw new Error('提交服务申请失败：响应缺少申请编号');
  return result.data;
};

export const getServiceRequestDetail = async (requestId: string, signal?: AbortSignal): Promise<ServiceRequestDetail> => {
  const result = await requestTicketApi<ServiceRequestDetail>(`/api/service-requests/${encodeURIComponent(requestId)}`, { signal });
  if (!result.data?.request) throw new Error('服务申请详情格式无效');
  return {
    request: result.data.request,
    events: Array.isArray(result.data.events) ? result.data.events : [],
    sla: result.data.sla || { configured: false, clocks: [] },
    linked_change_orders: Array.isArray(result.data.linked_change_orders) ? result.data.linked_change_orders : [],
  };
};

export const postServiceRequestAction = async (
  requestId: string,
  action: ServiceRequestAction,
  body: TicketActionPayload,
) => requestTicketApi<ServiceRequest>(`/api/service-requests/${encodeURIComponent(requestId)}/actions`, {
  method: 'POST',
  body: JSON.stringify({ action, ...body }),
});

export const linkServiceRequestChangeOrder = async (requestId: string, changeOrderNumber: string): Promise<void> => {
  await requestTicketApi<unknown>(`/api/service-requests/${encodeURIComponent(requestId)}/change-orders`, {
    method: 'POST',
    body: JSON.stringify({ change_order_number: changeOrderNumber }),
  });
};

export const getTicketWorkCalendars = async (signal?: AbortSignal): Promise<TicketWorkCalendar[]> => {
  const result = await requestTicketApi<TicketWorkCalendar[]>('/api/ticket-work-calendars', { signal });
  return Array.isArray(result.data) ? result.data : [];
};

export const saveTicketWorkCalendar = async (body: {
  id?: string;
  name: string;
  timezone: string;
  schedule: TicketWorkCalendar['schedule'];
  holidays: string[];
}): Promise<TicketWorkCalendar> => {
  const result = await requestTicketApi<TicketWorkCalendar>('/api/ticket-work-calendars', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (!result.data?.id) throw new Error('保存工作日历失败：响应缺少日历编号');
  return result.data;
};

export const getTicketSlaPolicies = async (signal?: AbortSignal): Promise<TicketSlaPolicy[]> => {
  const result = await requestTicketApi<TicketSlaPolicy[]>('/api/ticket-sla-policies', { signal });
  return Array.isArray(result.data) ? result.data : [];
};

export const saveTicketSlaPolicy = async (body: {
  id?: string;
  name: string;
  source_type: TicketSourceType;
  priority: TicketSlaPolicy['priority'];
  response_target_minutes?: number;
  restore_target_minutes?: number;
  fulfillment_target_minutes?: number;
  warning_before_minutes?: number;
  calendar_version_id?: string;
}): Promise<TicketSlaPolicy> => {
  const result = await requestTicketApi<TicketSlaPolicy>('/api/ticket-sla-policies', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (!result.data?.id) throw new Error('保存时限策略失败：响应缺少策略编号');
  return result.data;
};

export const getIncidentTicketDetail = async (ticketId: string, signal?: AbortSignal): Promise<IncidentTicketDetail> => {
  const result = await requestTicketApi<IncidentTicketDetail>(`/api/tickets/incidents/${encodeURIComponent(ticketId)}`, { signal });
  if (!result.data?.ticket) throw new Error('故障工单详情格式无效');
  return {
    ticket: result.data.ticket,
    events: Array.isArray(result.data.events) ? result.data.events : [],
    linked_change_orders: Array.isArray(result.data.linked_change_orders) ? result.data.linked_change_orders : [],
  };
};

export const getTicketAssignmentGroups = async (): Promise<TicketAssignmentGroup[]> => {
  const result = await requestTicketApi<TicketAssignmentGroup[]>('/api/ticket-assignment-groups');
  return Array.isArray(result.data) ? result.data : [];
};

export const getTicketAssignmentGroupMembers = async (groupId: string, ticketId?: string): Promise<TicketAssignmentMember[]> => {
  const params = ticketId ? `?${new URLSearchParams({ ticket_id: ticketId })}` : '';
  const result = await requestTicketApi<TicketAssignmentMember[]>(`/api/ticket-assignment-groups/${encodeURIComponent(groupId)}/members${params}`);
  return Array.isArray(result.data) ? result.data : [];
};

export const createTicketAssignmentGroup = async (body: { name: string; description: string }): Promise<TicketAssignmentGroup> => {
  const result = await requestTicketApi<TicketAssignmentGroup>('/api/ticket-assignment-groups', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (!result.data?.id) throw new Error('创建责任组失败：响应缺少责任组编号');
  return result.data;
};

export const updateTicketAssignmentGroup = async (groupId: string, body: { name: string; description: string }): Promise<TicketAssignmentGroup | undefined> => {
  const result = await requestTicketApi<TicketAssignmentGroup>(`/api/ticket-assignment-groups/${encodeURIComponent(groupId)}`, {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  return result.data;
};

export const deleteTicketAssignmentGroup = async (groupId: string): Promise<void> => {
  await requestTicketApi<unknown>(`/api/ticket-assignment-groups/${encodeURIComponent(groupId)}`, { method: 'DELETE' });
};

export const addTicketAssignmentGroupMember = async (groupId: string, userId: string): Promise<void> => {
  await requestTicketApi<unknown>(`/api/ticket-assignment-groups/${encodeURIComponent(groupId)}/members`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId }),
  });
};

export const removeTicketAssignmentGroupMember = async (groupId: string, userId: string): Promise<void> => {
  await requestTicketApi<unknown>(`/api/ticket-assignment-groups/${encodeURIComponent(groupId)}/members/${encodeURIComponent(userId)}`, { method: 'DELETE' });
};

export const postIncidentTicketAction = async (ticketId: string, action: IncidentTicketAction, body: TicketActionPayload) => {
  return requestTicketApi<IncidentTicket>(`/api/tickets/incidents/${encodeURIComponent(ticketId)}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action, ...body }),
  });
};

export const createOrOpenIncidentTicket = async (incidentId: string): Promise<{ ticket: IncidentTicket; created: boolean }> => {
  const result = await requestTicketApi<IncidentTicket>(`/api/tickets/from-incident/${encodeURIComponent(incidentId)}`, { method: 'POST' });
  if (!result.data?.id) throw new Error('创建或打开故障工单失败：响应缺少工单编号');
  return { ticket: result.data, created: Boolean((result as TicketApiEnvelope<IncidentTicket> & { created?: boolean }).created) };
};

export const buildIncidentTicketPath = (ticketId: string): string => `/tickets?ticket_id=${encodeURIComponent(ticketId)}`;
