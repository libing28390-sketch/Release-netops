import { isValidIPv4, isValidIPv6 } from './helpers';

export type GatewayBindingSource = 'none' | 'auto' | 'manual';
export type GatewayCandidateStatus = 'matched' | 'scope_pending' | 'no_unique_gateway' | 'ambiguous' | 'no_candidate' | 'needs_site';

export interface GatewayCandidateEndpoint {
  device_id: string | null;
  device_name: string;
  interface_name: string;
  interface_id: string | null;
  address?: string | null;
  ip_address?: string | null;
  interface_type?: string | null;
}

export interface GatewayCandidateResponse {
  status: GatewayCandidateStatus;
  selected: GatewayCandidateEndpoint | null;
  endpoints: GatewayCandidateEndpoint[];
  gateway_ip?: string | null;
}

export function isValidGatewayCandidatePrefix(value: string): boolean {
  const parts = String(value || '').trim().split('/');
  if (parts.length !== 2 || !parts[0] || !/^\d+$/.test(parts[1])) return false;
  const prefixLength = Number(parts[1]);
  return parts[0].includes(':')
    ? prefixLength >= 0 && prefixLength <= 128 && isValidIPv6(parts[0])
    : prefixLength >= 0 && prefixLength <= 32 && isValidIPv4(parts[0]);
}

export function buildGatewayCandidateQuery(input: {
  prefix: string;
  siteId: string;
  gatewayIp?: string;
  addressSpaceId?: string | null;
}): URLSearchParams {
  const query = new URLSearchParams({ prefix: input.prefix.trim(), site_id: input.siteId });
  const gatewayIp = String(input.gatewayIp || '').trim();
  if (gatewayIp) query.set('gateway_ip', gatewayIp);
  const addressSpaceId = String(input.addressSpaceId || '').trim();
  if (addressSpaceId) query.set('address_space_id', addressSpaceId);
  return query;
}

export function getAutomaticGatewayBinding(
  source: GatewayBindingSource,
  response: GatewayCandidateResponse,
): { deviceId: string; interfaceId: string } | null {
  const selected = response.selected;
  if (source === 'manual' || response.status !== 'matched' || !selected?.device_id) return null;
  return {
    deviceId: selected.device_id,
    interfaceId: selected.interface_id || '',
  };
}

export function getGatewayScopePendingMessage(source: GatewayBindingSource, zh: boolean): string {
  if (source === 'manual') {
    return zh
      ? '接口快照没有 VRF；候选仅供核实，已保留人工设备选择。'
      : 'The interface snapshot has no VRF; candidates need review and the manual device selection is preserved.';
  }
  return zh
    ? '接口快照没有 VRF，不能自动关联网关；请核实路由域并手动选择设备。'
    : 'The interface snapshot has no VRF, so the gateway cannot be auto-bound. Confirm the routing scope and choose a device manually.';
}
