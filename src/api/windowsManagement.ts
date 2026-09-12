export type WindowsServiceAction = 'start' | 'stop' | 'restart';

export interface WindowsHostSummary {
  hostname?: string;
  operating_system?: string;
  os_version?: string;
  cpu_count?: number;
  memory_total_bytes?: number;
  [key: string]: unknown;
}

export interface WindowsService {
  name: string;
  display_name?: string;
  status?: string;
  start_type?: string;
  can_stop?: boolean;
  can_pause?: boolean;
  description?: string;
  [key: string]: unknown;
}

export interface WindowsServicePage {
  items: WindowsService[];
  total: number;
  page: number;
  page_size: number;
}

export interface WindowsServiceActionResult {
  success?: boolean;
  message?: string;
  service?: WindowsService;
  previous_status?: string;
  current_status?: string;
  [key: string]: unknown;
}

export class WindowsManagementError extends Error {
  readonly status: number;
  readonly payload: unknown;

  constructor(message: string, status: number, payload: unknown) {
    super(message);
    this.name = 'WindowsManagementError';
    this.status = status;
    this.payload = payload;
  }
}

function authHeaders() {
  const token = localStorage.getItem('netops_token') || '';
  return {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    'Content-Type': 'application/json',
  };
}

async function requestJson<T>(url: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { ...authHeaders(), ...(init.headers || {}) },
    cache: 'no-store',
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof payload?.detail === 'string'
      ? payload.detail
      : typeof payload?.detail?.message === 'string'
        ? payload.detail.message
      : typeof payload?.error === 'string'
        ? payload.error
        : `HTTP ${response.status}`;
    throw new WindowsManagementError(detail, response.status, payload);
  }
  return payload as T;
}

export function testWindowsConnection(assetId: string, signal?: AbortSignal) {
  return requestJson<Record<string, unknown>>(`/api/windows/assets/${encodeURIComponent(assetId)}/test`, {
    method: 'POST',
    signal,
  });
}

export function getWindowsSummary(assetId: string, signal?: AbortSignal) {
  return requestJson<WindowsHostSummary>(`/api/windows/assets/${encodeURIComponent(assetId)}/summary`, { signal });
}

export async function getWindowsServices(
  assetId: string,
  params: { page: number; pageSize: number; search?: string; status?: string },
  signal?: AbortSignal,
): Promise<WindowsServicePage> {
  const query = new URLSearchParams({
    page: String(params.page),
    page_size: String(params.pageSize),
  });
  if (params.search) query.set('search', params.search);
  if (params.status && params.status !== 'all') query.set('status', params.status);

  const payload = await requestJson<Record<string, unknown>>(
    `/api/windows/assets/${encodeURIComponent(assetId)}/services?${query.toString()}`,
    { signal },
  );
  const rawItems = Array.isArray(payload.items)
    ? payload.items
    : Array.isArray(payload.services)
      ? payload.services
      : Array.isArray(payload.data)
        ? payload.data
        : [];
  const items = rawItems.map((value) => {
    const item = value as Record<string, unknown>;
    return {
      ...item,
      name: String(item.name ?? item.Name ?? ''),
      display_name: String(item.display_name ?? item.DisplayName ?? ''),
      status: String(item.status ?? item.State ?? item.Status ?? ''),
      start_type: String(item.start_type ?? item.StartMode ?? ''),
    } as WindowsService;
  });
  const total = Number(payload.total ?? payload.count ?? items.length) || 0;
  return {
    items,
    total,
    page: Number(payload.page ?? params.page) || params.page,
    page_size: Number(payload.page_size ?? params.pageSize) || params.pageSize,
  };
}

export function performWindowsServiceAction(
  assetId: string,
  serviceName: string,
  action: WindowsServiceAction,
  reason: string,
  signal?: AbortSignal,
) {
  return requestJson<WindowsServiceActionResult>(
    `/api/windows/assets/${encodeURIComponent(assetId)}/services/${encodeURIComponent(serviceName)}/actions`,
    {
      method: 'POST',
      signal,
      body: JSON.stringify({ action, confirm: true, reason }),
    },
  );
}
