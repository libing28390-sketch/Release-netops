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
});
