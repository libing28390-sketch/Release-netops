import { apiRequest, createClientRequestId } from './http';
import type {
  AddressAllocationInput, IpamAddress, IpamPrefix,
  ReconciliationFinding, ReconciliationRun,
} from '../types/ipam';

export const listPrefixes = (search = '') => apiRequest<IpamPrefix[]>(`/api/ipam/subnets?q=${encodeURIComponent(search)}`);
export const createPrefix = (payload: Record<string, unknown>) => apiRequest<{ id: string; prefix: string }>('/api/ipam/subnets', { method: 'POST', body: JSON.stringify(payload) });
export const listAddresses = (prefixId: string) => apiRequest<IpamAddress[]>(`/api/ipam/subnets/${prefixId}/addresses`);

export const allocateNextAddress = (prefixId: string, payload: AddressAllocationInput) => (
  apiRequest<IpamAddress>(`/api/ipam/subnets/${prefixId}/allocate-next`, { method: 'POST', body: JSON.stringify(payload) })
);

export const reserveAddress = (prefixId: string, address: string, payload: AddressAllocationInput) => (
  apiRequest<IpamAddress>(`/api/ipam/subnets/${prefixId}/reserve`, {
    method: 'POST', body: JSON.stringify({ ...payload, address }),
  })
);

export const releaseAddress = (addressId: string) => (
  apiRequest<{ ok: boolean }>(`/api/ipam/addresses/${addressId}/release`, { method: 'POST', body: '{}' })
);

export const createReconciliationRun = () => apiRequest<{ id: string; total_findings: number }>('/api/ipam/reconciliation/runs', { method: 'POST', body: '{}' });
export const listReconciliationRuns = () => apiRequest<{ items: ReconciliationRun[]; total: number }>('/api/ipam/reconciliation/runs');
export const listReconciliationFindings = (runId = '', status = '') => {
  const params = new URLSearchParams();
  if (runId) params.set('run_id', runId);
  if (status) params.set('status', status);
  return apiRequest<ReconciliationFinding[]>(`/api/ipam/reconciliation/findings?${params.toString()}`);
};
export const requestReconciliationAction = (findingId: string, actionType: string, payload: Record<string, unknown> = {}) => (
  apiRequest<{ id: string; status: string }>(`/api/ipam/reconciliation/findings/${findingId}/actions`, {
    method: 'POST', body: JSON.stringify({ action_type: actionType, payload }),
  })
);
export const approveReconciliationAction = (actionId: string) => (
  apiRequest<{ id: string; status: string }>(`/api/ipam/reconciliation/actions/${actionId}/approve`, { method: 'POST', body: '{}' })
);

export type RoutingContextSource = 'cli' | 'snmp';
export type RoutingContextType = 'vrf' | 'global';
export type RoutingContextStatus = 'active' | 'disabled';

export interface RoutingContextMapping {
  id: string;
  device_id: string;
  device_name: string;
  context_source: RoutingContextSource;
  context_type: RoutingContextType;
  local_context_key: string;
  local_context_name: string;
  address_space_id: string;
  address_space_name: string;
  address_space_kind: RoutingContextType;
  vrf_id: string | null;
  status: RoutingContextStatus;
  revision: number;
  last_verified_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateRoutingContextMappingInput {
  device_id: string;
  context_source: RoutingContextSource;
  context_type: RoutingContextType;
  local_context_key: string;
  local_context_name: string;
  address_space_id: string;
}

export interface UpdateRoutingContextMappingInput {
  expected_revision: number;
  address_space_id: string;
  local_context_name: string;
  status: RoutingContextStatus;
}

export const listRoutingContextMappings = (deviceId: string) => {
  const params = new URLSearchParams({ device_id: deviceId });
  return apiRequest<{ items: RoutingContextMapping[] }>(`/api/ipam/routing-contexts?${params.toString()}`);
};

export const createRoutingContextMapping = (payload: CreateRoutingContextMappingInput) => (
  apiRequest<RoutingContextMapping>('/api/ipam/routing-contexts', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
);

export const updateRoutingContextMapping = (id: string, payload: UpdateRoutingContextMappingInput) => (
  apiRequest<RoutingContextMapping>(`/api/ipam/routing-contexts/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
);

export type IpamFhrpProtocol = 'hsrp' | 'vrrp' | 'anycast';
export type IpamFhrpGroupType = 'fhrp' | 'anycast';
export type IpamFhrpStatus = 'active' | 'disabled';

export interface IpamFhrpGroupMember {
  id: string;
  group_id: string;
  device_id: string;
  device_name: string;
  interface_id: string | null;
  interface_name: string;
  normalized_interface_name: string;
  role: string | null;
  priority: number | null;
  status: IpamFhrpStatus;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface IpamFhrpVipLink {
  vip_id: string;
  address: string;
  vip_type: string;
  status: string;
  address_space_id: string;
  tenant_id: string;
  prefix_id: string;
  revision: number;
  linked_at: string;
}

export interface IpamFhrpGroupSummary {
  id: string;
  security_tenant_id: string;
  address_space_id: string;
  address_space_name: string;
  group_type: IpamFhrpGroupType;
  protocol: IpamFhrpProtocol;
  group_id: string;
  address_family: 4 | 6;
  display_name: string;
  status: IpamFhrpStatus;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface IpamFhrpGroupDetail extends IpamFhrpGroupSummary {
  members: IpamFhrpGroupMember[];
  vips: IpamFhrpVipLink[];
}

export interface IpamFhrpGroupCreateInput {
  address_space_id: string;
  group_type: IpamFhrpGroupType;
  protocol: IpamFhrpProtocol;
  group_id: string;
  address_family: 4 | 6;
  display_name?: string;
  status?: IpamFhrpStatus;
}

export interface IpamFhrpGroupUpdateInput {
  expected_revision: number;
  group_id?: string;
  display_name?: string;
  status?: IpamFhrpStatus;
}

export interface IpamFhrpMemberCreateInput {
  expected_revision: number;
  device_id: string;
  interface_name: string;
  role?: string;
  priority?: number;
  status?: IpamFhrpStatus;
}

export interface IpamFhrpVipSearchResult {
  id: string;
  address: string;
  vip_type: string;
  status: string;
  prefix_id: string | null;
  address_space_id: string | null;
  address_space_name?: string | null;
}

export interface IpamFhrpCurrentObservation {
  id: string;
  source_device_id: string;
  source_device_name: string;
  protocol: IpamFhrpProtocol;
  group_id: number;
  address_family: 4 | 6;
  interface_name: string;
  priority: number | null;
  state: string;
  master_address: string;
  virtual_ip: string;
  virtual_mac: string;
  address_space_id: string;
  address_space_name: string;
  scope_status: string;
  group_scope_status: 'resolved' | 'scope_pending' | 'scope_mismatch';
  coverage_complete: boolean;
  collection_status: string;
  observed_at: string;
  last_success_at: string;
}

export interface IpamFhrpCollectionState {
  device_id: string;
  device_name: string;
  protocol: IpamFhrpProtocol;
  latest_attempt_generation: number;
  latest_status: string;
  last_attempt_at: string;
  last_completed_at: string;
  last_success_generation: number;
  last_success_at: string;
  current_row_count: number;
  last_error_code: string;
}

const fhrpIdempotencyHeaders = (key?: string): HeadersInit => ({
  'Idempotency-Key': key || createClientRequestId('ipam-fhrp'),
});

export const listFhrpGroups = ({
  addressSpaceId = '',
  search = '',
  page = 1,
  pageSize = 20,
  signal,
}: {
  addressSpaceId?: string;
  search?: string;
  page?: number;
  pageSize?: number;
  signal?: AbortSignal;
} = {}) => {
  const query = new URLSearchParams();
  if (addressSpaceId) query.set('address_space_id', addressSpaceId);
  if (search.trim()) query.set('q', search.trim());
  query.set('page', String(page));
  query.set('page_size', String(pageSize));
  return apiRequest<{
    items: IpamFhrpGroupSummary[];
    total: number;
    page: number;
    page_size: number;
    total_pages: number;
  }>(`/api/ipam/fhrp/groups?${query.toString()}`, { signal });
};

export const getFhrpGroup = (groupId: string, signal?: AbortSignal) => (
  apiRequest<IpamFhrpGroupDetail>(`/api/ipam/fhrp/groups/${encodeURIComponent(groupId)}`, { signal })
);

export const getFhrpGroupCurrent = (groupId: string, signal?: AbortSignal) => (
  apiRequest<{
    items: IpamFhrpCurrentObservation[];
    collection_states: IpamFhrpCollectionState[];
  }>(`/api/ipam/fhrp/groups/${encodeURIComponent(groupId)}/current`, { signal })
);

export const createFhrpGroup = (payload: IpamFhrpGroupCreateInput, idempotencyKey?: string) => (
  apiRequest<IpamFhrpGroupDetail>('/api/ipam/fhrp/groups', {
    method: 'POST',
    headers: fhrpIdempotencyHeaders(idempotencyKey),
    body: JSON.stringify(payload),
  })
);

export const updateFhrpGroup = (
  groupId: string,
  payload: IpamFhrpGroupUpdateInput,
  idempotencyKey?: string,
) => (
  apiRequest<IpamFhrpGroupDetail>(`/api/ipam/fhrp/groups/${encodeURIComponent(groupId)}`, {
    method: 'PUT',
    headers: fhrpIdempotencyHeaders(idempotencyKey),
    body: JSON.stringify(payload),
  })
);

export const deleteFhrpGroup = (groupId: string, expectedRevision: number, idempotencyKey?: string) => {
  const query = new URLSearchParams({ expected_revision: String(expectedRevision) });
  return apiRequest<{ ok: boolean; id: string; revision: number }>(
    `/api/ipam/fhrp/groups/${encodeURIComponent(groupId)}?${query.toString()}`,
    { method: 'DELETE', headers: fhrpIdempotencyHeaders(idempotencyKey) },
  );
};

export const addFhrpGroupMember = (
  groupId: string,
  payload: IpamFhrpMemberCreateInput,
  idempotencyKey?: string,
) => (
  apiRequest<IpamFhrpGroupMember & { group_revision: number }>(
    `/api/ipam/fhrp/groups/${encodeURIComponent(groupId)}/members`,
    {
      method: 'POST',
      headers: fhrpIdempotencyHeaders(idempotencyKey),
      body: JSON.stringify(payload),
    },
  )
);

export const removeFhrpGroupMember = (
  groupId: string,
  memberId: string,
  expectedRevision: number,
  idempotencyKey?: string,
) => {
  const query = new URLSearchParams({ expected_revision: String(expectedRevision) });
  return apiRequest<{ ok: boolean; id: string; group_revision: number }>(
    `/api/ipam/fhrp/groups/${encodeURIComponent(groupId)}/members/${encodeURIComponent(memberId)}?${query.toString()}`,
    { method: 'DELETE', headers: fhrpIdempotencyHeaders(idempotencyKey) },
  );
};

export const attachFhrpGroupVip = (
  groupId: string,
  payload: { expected_revision: number; vip_id: string },
  idempotencyKey?: string,
) => (
  apiRequest<{ id: string; group_id: string; vip_id: string; address: string; vip_type: string; group_revision: number }>(
    `/api/ipam/fhrp/groups/${encodeURIComponent(groupId)}/vips`,
    {
      method: 'POST',
      headers: fhrpIdempotencyHeaders(idempotencyKey),
      body: JSON.stringify(payload),
    },
  )
);

export const detachFhrpGroupVip = (
  groupId: string,
  vipId: string,
  expectedRevision: number,
  idempotencyKey?: string,
) => {
  const query = new URLSearchParams({ expected_revision: String(expectedRevision) });
  return apiRequest<{ ok: boolean; group_id: string; vip_id: string; group_revision: number }>(
    `/api/ipam/fhrp/groups/${encodeURIComponent(groupId)}/vips/${encodeURIComponent(vipId)}?${query.toString()}`,
    { method: 'DELETE', headers: fhrpIdempotencyHeaders(idempotencyKey) },
  );
};

export const searchFhrpVipOptions = (addressQuery: string, signal?: AbortSignal) => {
  const query = new URLSearchParams({
    q: addressQuery,
    status: 'active',
    page: '1',
    page_size: '100',
  });
  return apiRequest<{ items: IpamFhrpVipSearchResult[]; total: number }>(
    `/api/ipam/vips?${query.toString()}`,
    { signal },
  );
};
