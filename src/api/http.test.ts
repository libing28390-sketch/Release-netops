import { describe, expect, it, vi } from 'vitest';

import { apiRequest } from './http';

describe('stable API error contract', () => {
  it('exposes error code and request id without losing the safe message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      headers: { get: (name: string) => name.toLowerCase() === 'x-request-id' ? 'req-api004' : null },
      json: async () => ({
        success: false,
        error: { code: 'PERMISSION_DENIED', message: 'Insufficient permission', request_id: 'req-api004' },
        detail: 'Insufficient permission',
      }),
    }));

    await expect(apiRequest('/api/v2/kb/sources')).rejects.toMatchObject({
      status: 403,
      requestId: 'req-api004',
      code: 'PERMISSION_DENIED',
      detail: { code: 'PERMISSION_DENIED', message: 'Insufficient permission', request_id: 'req-api004' },
    });
  });

  it('adds a safe request id to every API request while preserving caller ids', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: { get: () => null },
      json: async () => ({ ok: true }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await apiRequest('/api/test');
    const generatedHeaders = fetchMock.mock.calls[0][1].headers as Headers;
    expect(generatedHeaders.get('X-Request-ID')).toMatch(/^web_/);

    await apiRequest('/api/test', { headers: { 'X-Request-ID': 'caller_123' } });
    const callerHeaders = fetchMock.mock.calls[1][1].headers as Headers;
    expect(callerHeaders.get('X-Request-ID')).toBe('caller_123');
  });
});
