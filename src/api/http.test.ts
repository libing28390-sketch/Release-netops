import { afterEach, describe, expect, it, vi } from 'vitest';

import { apiRequest } from './http';

afterEach(() => {
  vi.unstubAllGlobals();
});

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

    await expect(apiRequest('/api/knowledge/sources')).rejects.toMatchObject({
      status: 403,
      requestId: 'req-api004',
      code: 'PERMISSION_DENIED',
      detail: { code: 'PERMISSION_DENIED', message: 'Insufficient permission', request_id: 'req-api004' },
    });
  });

  it('uses a specific detail when the error envelope only has a generic validation summary', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      headers: { get: (name: string) => name.toLowerCase() === 'x-request-id' ? 'req-asset-422' : null },
      json: async () => ({
        success: false,
        error: { code: 'VALIDATION_ERROR', message: '保存校验失败，请检查填写内容。' },
        detail: '设备口令上手状态为“待设置凭据”，请先保存凭据并验证连通性。',
      }),
    }));

    await expect(apiRequest('/api/assets/asset-1')).rejects.toMatchObject({
      status: 422,
      code: 'VALIDATION_ERROR',
      message: '设备口令上手状态为“待设置凭据”，请先保存凭据并验证连通性。 (Request ID: req-asset-422)',
      detail: { code: 'VALIDATION_ERROR', message: '保存校验失败，请检查填写内容。' },
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
