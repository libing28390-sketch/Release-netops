import { isValidIPv4, isValidIPv6 } from './helpers';

export type GatewayBindingSource = 'none' | 'auto' | 'manual';
export type GatewayCandidateStatus = 'matched' | 'no_unique_gateway' | 'no_candidate' | 'needs_site';

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
}): URLSearchParams {
  const query = new URLSearchParams({ prefix: input.prefix.trim(), site_id: input.siteId });
  const gatewayIp = String(input.gatewayIp || '').trim();
  if (gatewayIp) query.set('gateway_ip', gatewayIp);
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
