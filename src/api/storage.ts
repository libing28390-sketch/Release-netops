import { apiRequest } from './http';

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

export const listStorageProviders = () =>
  apiRequest<StorageProvidersResponse>('/api/storage/providers');

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
