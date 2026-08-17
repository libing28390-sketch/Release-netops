export class ApiError extends Error {
  status: number;
  detail: unknown;
  requestId?: string;
  code?: string;

  constructor(status: number, message: string, detail?: unknown, requestId?: string, code?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.requestId = requestId;
    this.code = code;
  }
}

export const authHeaders = (json = false): HeadersInit => {
  const token = localStorage.getItem('netops_token');
  return {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(json ? { 'Content-Type': 'application/json' } : {}),
  };
};

export function createClientRequestId(prefix = 'web'): string {
  const randomUUID = globalThis.crypto?.randomUUID?.bind(globalThis.crypto);
  if (typeof randomUUID === 'function') return `${prefix}_${randomUUID()}`;
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 14)}`;
}

export async function apiRequest<T>(url: string, init: RequestInit = {}): Promise<T> {
  const bodyIsFormData = typeof FormData !== 'undefined' && init.body instanceof FormData;
  const headers = new Headers(authHeaders(Boolean(init.body) && !bodyIsFormData));
  new Headers(init.headers || {}).forEach((value, key) => headers.set(key, value));
  if (!headers.has('X-Request-ID')) headers.set('X-Request-ID', createClientRequestId());
  const response = await fetch(url, {
    ...init,
    // Let the browser set the multipart boundary for FormData uploads.
    headers,
  });
  const requestId = response.headers.get('X-Request-ID') || undefined;
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) {
      window.dispatchEvent(new Event('netops:auth-expired'));
    }
    const errorContract = payload?.error && typeof payload.error === 'object' ? payload.error : undefined;
    const rawDetail = errorContract ?? payload?.detail ?? payload?.message ?? `HTTP ${response.status}`;
    const code = typeof errorContract?.code === 'string' ? errorContract.code : undefined;
    let message = typeof rawDetail === 'string' ? rawDetail : rawDetail?.message || JSON.stringify(rawDetail);
    if (requestId) {
      message = `${message} (Request ID: ${requestId})`;
    }
    throw new ApiError(response.status, message, rawDetail, requestId, code);
  }
  return payload as T;
}
