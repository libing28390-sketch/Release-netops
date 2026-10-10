import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useMonitoring } from './useMonitoring';
import { useMonitoringStore } from '../store/monitoringStore';

const response = (payload: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  headers: new Headers(),
  json: vi.fn().mockResolvedValue(payload),
}) as unknown as Response;

describe('useMonitoring overview errors', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
    useMonitoringStore.getState().resetMonitoringState();
  });

  afterEach(() => {
    cleanup();
    useMonitoringStore.getState().resetMonitoringState();
    vi.unstubAllGlobals();
  });

  it('surfaces 403 safely and keeps the last successful overview', async () => {
    const previousOverview = { online_devices: 7, offline_devices: 2, open_alerts: 3 };
    useMonitoringStore.getState().setMonitorOverview(previousOverview);
    vi.mocked(fetch).mockResolvedValue(response({ detail: 'permission denied' }, 403));
    const { result } = renderHook(() => useMonitoring({ isAuthenticated: false, activeTab: 'monitoring', language: 'en' }));

    await act(async () => { await result.current.fetchMonitoringOverview(); });

    expect(result.current.monitorOverviewError).toEqual({
      status: 403,
      message: 'You do not have permission to view the monitoring overview.',
      permissionDenied: true,
    });
    expect(useMonitoringStore.getState().monitorOverview).toBe(previousOverview);
    expect(result.current.monitorOverviewLoading).toBe(false);
    expect(fetch).toHaveBeenCalledWith('/api/monitoring/overview', expect.objectContaining({ headers: expect.any(Headers) }));
  });

  it('uses the shared HTTP contract to expire a 401 session and clears the error after success', async () => {
    const authExpired = vi.fn();
    window.addEventListener('netops:auth-expired', authExpired);
    vi.mocked(fetch).mockResolvedValueOnce(response({ detail: 'expired' }, 401));
    const { result } = renderHook(() => useMonitoring({ isAuthenticated: false, activeTab: 'monitoring', language: 'zh' }));

    await act(async () => { await result.current.fetchMonitoringOverview(); });
    expect(authExpired).toHaveBeenCalledTimes(1);
    expect(result.current.monitorOverviewError).toMatchObject({ status: 401, permissionDenied: true });
    expect(result.current.monitorOverviewError?.message).toContain('登录状态已失效');

    const nextOverview = { online_devices: 5, offline_devices: 1 };
    vi.mocked(fetch).mockResolvedValueOnce(response(nextOverview));
    await act(async () => { await result.current.fetchMonitoringOverview(true); });

    expect(fetch).toHaveBeenLastCalledWith('/api/monitoring/overview?force_refresh=1', expect.any(Object));
    expect(useMonitoringStore.getState().monitorOverview).toEqual(nextOverview);
    expect(result.current.monitorOverviewError).toBeNull();
    expect(result.current.monitorOverviewUpdatedAt).toBeInstanceOf(Date);
    window.removeEventListener('netops:auth-expired', authExpired);
  });

  it('does not report a canceled overview request as an error', async () => {
    vi.mocked(fetch).mockRejectedValue(new DOMException('Aborted', 'AbortError'));
    const { result } = renderHook(() => useMonitoring({ isAuthenticated: false, activeTab: 'monitoring', language: 'en' }));
    const controller = new AbortController();

    await act(async () => { await result.current.fetchMonitoringOverview(false, controller.signal); });

    expect(result.current.monitorOverviewError).toBeNull();
    expect(result.current.monitorOverviewLoading).toBe(false);
  });
});
