import { afterEach, describe, expect, it, vi } from 'vitest';
import { locateIpWithRun } from './ipLocatorRuns';

const jsonResponse = (body: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('IP locator durable run client', () => {
  it('falls back only when V2 is disabled', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ detail: 'IP 定位 V2 未启用' }, 503))
      .mockResolvedValueOnce(jsonResponse({ target_ip: '192.0.2.5', found: true }));
    vi.stubGlobal('fetch', fetchMock);
    const onStage = vi.fn();

    const result = await locateIpWithRun<{ found: boolean }>({
      ip: '192.0.2.5',
      token: 'token',
      onStage,
    });

    expect(result.found).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(onStage).toHaveBeenCalledWith('legacy');
  });

  it('polls the durable run until the result is available', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ id: 'run-1', status: 'queued' }, 202))
      .mockResolvedValueOnce(jsonResponse({ id: 'run-1', status: 'running' }))
      .mockResolvedValueOnce(jsonResponse({ id: 'run-1', status: 'completed', result: { found: true } }));
    vi.stubGlobal('fetch', fetchMock);
    const onStage = vi.fn();

    const result = await locateIpWithRun<{ found: boolean }>({
      ip: '192.0.2.5',
      token: 'token',
      pollIntervalMs: 0,
      onStage,
    });

    expect(result).toEqual({ found: true });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(onStage).toHaveBeenNthCalledWith(1, 'queued');
    expect(onStage).toHaveBeenNthCalledWith(2, 'running');
  });

  it('does not bypass the task queue for unrelated service failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail: '任务存储不可用' }, 503)));

    await expect(locateIpWithRun({
      ip: '192.0.2.5',
      token: 'token',
    })).rejects.toThrow('任务存储不可用');
  });
});
