import { apiRequest } from './http';
import type {
  TelemetryActionAccepted,
  TelemetryCollectorCapacity,
  TelemetryCollectorOption,
  TelemetryDeviceConfig,
  TelemetryPage,
  TelemetryProtocolProfile,
  TelemetrySubscription,
  TelemetrySubscriptionAction,
  TelemetrySubscriptionStatus,
  TelemetrySubscriptionTemplate,
  TelemetryTlsProfile,
} from '../types/telemetry';

export const TELEMETRY_API_PREFIX = '/api/monitoring/telemetry';

export interface TelemetrySubscriptionListParams {
  page?: number;
  page_size?: number;
}

export function getTelemetryProfiles(signal?: AbortSignal): Promise<TelemetryPage<TelemetryProtocolProfile>> {
  return apiRequest<TelemetryPage<TelemetryProtocolProfile>>(`${TELEMETRY_API_PREFIX}/profiles`, { signal });
}

export function getTelemetryTemplates(signal?: AbortSignal): Promise<TelemetryPage<TelemetrySubscriptionTemplate>> {
  return apiRequest<TelemetryPage<TelemetrySubscriptionTemplate>>(`${TELEMETRY_API_PREFIX}/templates?page=1&page_size=100`, { signal });
}

export function createTelemetryTemplate(payload: {
  profile_id: string;
  template_key: string;
  version: number;
  metric_mappings: Array<Record<string, unknown>>;
  estimated_series: number;
  default_interval_seconds: number;
}): Promise<TelemetrySubscriptionTemplate> {
  return apiRequest<TelemetrySubscriptionTemplate>(`${TELEMETRY_API_PREFIX}/templates`, {
    method: 'POST', body: JSON.stringify(payload),
  });
}

export function updateTelemetryTemplateDraft(templateId: string, payload: {
  metric_mappings?: Array<Record<string, unknown>>;
  estimated_series?: number;
  default_interval_seconds?: number;
}): Promise<TelemetrySubscriptionTemplate> {
  return apiRequest<TelemetrySubscriptionTemplate>(`${TELEMETRY_API_PREFIX}/templates/${encodeURIComponent(templateId)}`, {
    method: 'PATCH', body: JSON.stringify(payload),
  });
}

export function publishTelemetryTemplate(templateId: string): Promise<TelemetrySubscriptionTemplate> {
  return apiRequest<TelemetrySubscriptionTemplate>(`${TELEMETRY_API_PREFIX}/templates/${encodeURIComponent(templateId)}/publish`, { method: 'POST' });
}

export function getTelemetryTlsProfiles(signal?: AbortSignal): Promise<{ items: TelemetryTlsProfile[] }> {
  return apiRequest<{ items: TelemetryTlsProfile[] }>(`${TELEMETRY_API_PREFIX}/tls-profiles`, { signal });
}

export function createTelemetryTlsProfile(payload: {
  name: string;
  ca_certificate_ref: string;
  client_certificate_ref: string;
  encrypted_private_key_ref: string;
  fingerprint: string;
}): Promise<TelemetryTlsProfile> {
  return apiRequest<TelemetryTlsProfile>(`${TELEMETRY_API_PREFIX}/tls-profiles`, {
    method: 'POST', body: JSON.stringify(payload),
  });
}

export function getTelemetryCollectors(signal?: AbortSignal): Promise<{ items: TelemetryCollectorOption[] }> {
  return apiRequest<{ items: TelemetryCollectorOption[] }>(`${TELEMETRY_API_PREFIX}/collectors`, { signal });
}

export function getTelemetryDeviceConfig(deviceId: string, signal?: AbortSignal): Promise<TelemetryDeviceConfig | null> {
  return apiRequest<TelemetryDeviceConfig | null>(`${TELEMETRY_API_PREFIX}/devices/${encodeURIComponent(deviceId)}/config`, { signal });
}

export function saveTelemetryDeviceConfig(deviceId: string, payload: TelemetryDeviceConfig): Promise<TelemetryDeviceConfig> {
  return apiRequest<TelemetryDeviceConfig>(`${TELEMETRY_API_PREFIX}/devices/${encodeURIComponent(deviceId)}/config`, {
    method: 'PUT', body: JSON.stringify(payload),
  });
}

export function createTelemetrySubscription(deviceId: string, payload: {
  name: string;
  template_id: string;
  template_version: number;
  interval_seconds: number;
  path_filters: string[];
}): Promise<TelemetrySubscription> {
  return apiRequest<TelemetrySubscription>(`${TELEMETRY_API_PREFIX}/devices/${encodeURIComponent(deviceId)}/subscriptions`, {
    method: 'POST', body: JSON.stringify(payload),
  });
}

export function getTelemetrySubscriptions(
  params: TelemetrySubscriptionListParams = {},
  signal?: AbortSignal,
): Promise<TelemetryPage<TelemetrySubscription>> {
  const query = new URLSearchParams();
  if (params.page !== undefined) query.set('page', String(params.page));
  if (params.page_size !== undefined) query.set('page_size', String(params.page_size));
  const encodedQuery = query.toString();
  const suffix = encodedQuery ? `?${encodedQuery}` : '';
  return apiRequest<TelemetryPage<TelemetrySubscription>>(`${TELEMETRY_API_PREFIX}/subscriptions${suffix}`, { signal });
}

export function getTelemetrySubscriptionStatus(
  subscriptionId: string,
  signal?: AbortSignal,
): Promise<TelemetrySubscriptionStatus> {
  return apiRequest<TelemetrySubscriptionStatus>(`${TELEMETRY_API_PREFIX}/subscriptions/${encodeURIComponent(subscriptionId)}/status`, { signal });
}

export function getTelemetryCollectorCapacity(
  collectorId: string,
  signal?: AbortSignal,
): Promise<TelemetryCollectorCapacity> {
  return apiRequest<TelemetryCollectorCapacity>(`${TELEMETRY_API_PREFIX}/collectors/${encodeURIComponent(collectorId)}/capacity`, { signal });
}

export function runTelemetrySubscriptionAction(
  subscriptionId: string,
  action: TelemetrySubscriptionAction,
): Promise<TelemetryActionAccepted> {
  return apiRequest<TelemetryActionAccepted>(
    `${TELEMETRY_API_PREFIX}/subscriptions/${encodeURIComponent(subscriptionId)}/${action}`,
    { method: 'POST' },
  );
}
