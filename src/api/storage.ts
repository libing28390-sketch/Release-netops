import { apiRequest, ApiError, authHeaders, createClientRequestId } from './http';

export type StorageBackend = 's3';

export interface StorageProvider {
  id: string;
  name: string;
  backend: StorageBackend;
  endpoint_url: string;
  bucket: string;
  region: string;
  force_path_style: boolean;
  verify_tls: boolean;
  is_default: boolean;
  notes?: string | null;
  source: 'database' | 'environment';
  access_key_id_masked?: string | null;
  has_access_key: boolean;
  has_secret_key: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface StorageProvidersResponse {
  items: StorageProvider[];
  effective_default_id?: string | null;
  default_source?: 'database' | 'environment' | null;
}

export type StorageUsagePurpose = 'config_backup' | 'pam_recording';
export type StorageUsageProviderMode = 'default' | 'environment' | 'profile';

export interface StorageUsageProfileOption {
  id: string;
  name: string;
  endpoint_url?: string | null;
  bucket?: string | null;
  source?: 'database' | 'environment' | string;
}

export interface StorageUsage {
  purpose: StorageUsagePurpose;
  label: string;
  provider_mode: StorageUsageProviderMode;
  provider_id?: string | null;
  bucket_override?: string | null;
  key_prefix?: string | null;
  profiles?: StorageUsageProfileOption[];
  effective_provider_id?: string | null;
  effective_provider_name?: string | null;
  effective_source?: 'database' | 'environment' | string | null;
  effective_bucket?: string | null;
  effective_endpoint_url?: string | null;
}

export interface StorageUsagesResponse {
  items: StorageUsage[];
  profiles?: StorageUsageProfileOption[];
}

export interface StorageUsageUpdate {
  provider_mode: StorageUsageProviderMode;
  provider_id?: string | null;
  bucket_override: string;
  key_prefix: string;
}

export interface StorageProviderInput {
  name: string;
  backend: StorageBackend;
  endpoint_url: string;
  bucket: string;
  access_key_id: string;
  secret_access_key: string;
  force_path_style: boolean;
  verify_tls: boolean;
  is_default: boolean;
  notes: string;
}

export type StorageProviderUpdate = Partial<StorageProviderInput>;

export interface StorageTestResponse {
  ok?: boolean;
  success?: boolean;
  message?: string;
  detail?: string;
  [key: string]: unknown;
}

export interface StorageObjectPath {
  object_key: string;
  s3_uri: string;
  size: number;
  last_modified?: string | null;
}

export interface StorageObjectPage {
  provider_id: string;
  provider_name: string;
  endpoint_url: string;
  bucket: string;
  items: StorageObjectPath[];
  folders: string[];
  next_continuation_token?: string | null;
  is_truncated: boolean;
}

export const listStorageProviders = (signal?: AbortSignal) =>
  apiRequest<StorageProvidersResponse>('/api/storage/providers', { signal });

export const listStorageObjects = (
  providerId: string,
  options: { prefix?: string; delimiter?: string; continuationToken?: string | null; pageSize?: number; signal?: AbortSignal } = {},
) => {
  const params = new URLSearchParams({ provider_id: providerId, page_size: String(options.pageSize ?? 100) });
  if (options.prefix) params.set('prefix', options.prefix);
  if (options.delimiter !== undefined) params.set('delimiter', options.delimiter);
  if (options.continuationToken) params.set('continuation_token', options.continuationToken);
  return apiRequest<StorageObjectPage>(`/api/storage/objects?${params.toString()}`, {
    signal: options.signal,
  });
};

export const getStorageObjectContent = async (
  providerId: string,
  objectKey: string,
  options: { download?: boolean; signal?: AbortSignal } = {},
): Promise<string> => {
  const params = new URLSearchParams({
    provider_id: providerId,
    object_key: objectKey,
    download: String(options.download ?? false),
  });
  const headers = new Headers(authHeaders());
  if (!headers.has('X-Request-ID')) headers.set('X-Request-ID', createClientRequestId('storage-content'));
  const response = await fetch(`/api/storage/objects/content?${params.toString()}`, {
    signal: options.signal,
    headers,
  });
  const requestId = response.headers.get('X-Request-ID') || undefined;
  const body = await response.text();
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event('netops:auth-expired'));
    let payload: unknown;
    try {
      payload = body ? JSON.parse(body) : undefined;
    } catch {
      payload = undefined;
    }
    const errorContract = payload && typeof payload === 'object' && 'error' in payload && typeof payload.error === 'object'
      ? payload.error as Record<string, unknown>
      : undefined;
    const rawDetail = errorContract
      ?? (payload && typeof payload === 'object' && 'detail' in payload ? payload.detail : undefined)
      ?? (payload && typeof payload === 'object' && 'message' in payload ? payload.message : undefined)
      ?? body
      ?? `HTTP ${response.status}`;
    const code = typeof errorContract?.code === 'string' ? errorContract.code : undefined;
    let message = typeof rawDetail === 'string' ? rawDetail : JSON.stringify(rawDetail) || String(rawDetail);
    if (requestId) message = `${message} (Request ID: ${requestId})`;
    throw new ApiError(response.status, message, rawDetail, requestId, code);
  }
  return body;
};

export const listStorageUsages = () =>
  apiRequest<StorageUsagesResponse>('/api/storage/usages');

export const updateStorageUsage = (purpose: StorageUsagePurpose, input: StorageUsageUpdate) =>
  apiRequest<StorageUsage>(`/api/storage/usages/${encodeURIComponent(purpose)}`, {
    method: 'PUT',
    body: JSON.stringify({
      provider_mode: input.provider_mode,
      provider_id: input.provider_id ?? null,
      bucket_override: input.bucket_override,
      key_prefix: input.key_prefix,
    }),
  });

export const testStorageUsage = (purpose: StorageUsagePurpose, input: StorageUsageUpdate) =>
  apiRequest<StorageTestResponse>(`/api/storage/usages/${encodeURIComponent(purpose)}/test`, {
    method: 'POST',
    body: JSON.stringify({
      provider_mode: input.provider_mode,
      provider_id: input.provider_id ?? null,
      bucket_override: input.bucket_override,
      key_prefix: input.key_prefix,
    }),
  });

export const createStorageProvider = (input: StorageProviderInput) =>
  apiRequest<StorageProvider>('/api/storage/providers', {
    method: 'POST',
    body: JSON.stringify(input),
  });

export const updateStorageProvider = (id: string, input: StorageProviderUpdate) =>
  apiRequest<StorageProvider>(`/api/storage/providers/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(input),
  });

export const deleteStorageProvider = (id: string) =>
  apiRequest<void>(`/api/storage/providers/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });

export type StorageConnectionInput = Omit<StorageProviderInput, 'name' | 'is_default' | 'notes'> & { region?: string };

export const testStorageProvider = (input: StorageConnectionInput) =>
  apiRequest<StorageTestResponse>('/api/storage/providers/test', {
    method: 'POST',
    body: JSON.stringify(input),
  });

export const testSavedStorageProvider = (id: string) =>
  apiRequest<StorageTestResponse>(`/api/storage/providers/${encodeURIComponent(id)}/test`, {
    method: 'POST',
  });
