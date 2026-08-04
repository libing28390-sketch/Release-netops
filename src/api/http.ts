export class ApiError extends Error {
  status: number;
  detail: unknown;
  requestId?: string;

  constructor(status: number, message: string, detail?: unknown, requestId?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.requestId = requestId;
  }
}

export const authHeaders = (json = false): HeadersInit => {
  const token = localStorage.getItem('netops_token');
  return {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(json ? { 'Content-Type': 'application/json' } : {}),
  };
};

export async function apiRequest<T>(url: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { ...authHeaders(Boolean(init.body)), ...(init.headers || {}) },
  });
  const requestId = response.headers.get('X-Request-ID') || undefined;
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) {
      window.dispatchEvent(new Event('netops:auth-expired'));
    }
    const rawDetail = payload?.detail ?? payload?.message ?? `HTTP ${response.status}`;
    let message = typeof rawDetail === 'string' ? rawDetail : rawDetail?.message || JSON.stringify(rawDetail);
    if (requestId) {
      message = `${message} (Request ID: ${requestId})`;
    }
    throw new ApiError(response.status, message, rawDetail, requestId);
  }
  return payload as T;
}
