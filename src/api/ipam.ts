import { apiRequest } from './http';
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
