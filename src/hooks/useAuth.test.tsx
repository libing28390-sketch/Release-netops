import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useAuth } from './useAuth';

vi.mock('./useSystem', () => ({ resetSystemInfoCache: vi.fn() }));
vi.mock('./useInventory', () => ({ resetInventoryDeviceCache: vi.fn() }));

const callbacks = {
  language: 'zh',
  setLanguage: vi.fn(),
  showToast: vi.fn(),
  setShowSetupWizard: vi.fn(),
  setShowUserMenu: vi.fn(),
  setShowNotifications: vi.fn(),
};
const reply = (status: number, data?: unknown) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => data,
});

describe('useAuth reconnect', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    localStorage.clear();
    sessionStorage.clear();
    localStorage.setItem('netops_token', 'session-token');
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('keeps an unverified session on the reconnect screen and restores the real identity after retries', async () => {
    const user = { username: 'network-operator', role: 'Operator', preferred_language: 'en' };
    let sessionCalls = 0;
    const fetchMock = vi.fn(async (url: string) => {
      if (url === '/api/session') {
        sessionCalls++;
        if (sessionCalls === 2) return reply(200, {});
        if (sessionCalls <= 6) return reply(503);
        return reply(200, { user });
      }
      return reply(200, { setup_completed: true });
    });
    vi.stubGlobal('fetch', fetchMock);
    const { result } = renderHook(() => useAuth(callbacks));

    await act(async () => { await vi.advanceTimersByTimeAsync(19000); });
    expect(sessionCalls).toBe(6);
    expect(result.current.authChecking).toBe(true);
    expect(result.current.isAuthenticated).toBe(false);
    expect(localStorage.getItem('netops_token')).toBe('session-token');
    expect(sessionStorage.getItem('netops_session_snapshot')).toBeNull();

    await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
    expect(result.current.authChecking).toBe(false);
    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.currentUser).toEqual(user);
    expect(fetchMock).toHaveBeenCalledWith('/api/grafana/session', expect.objectContaining({ method: 'POST' }));
  });

  it('retains a confirmed snapshot on network errors and clears it on a 401', async () => {
    sessionStorage.setItem('netops_session_snapshot', JSON.stringify({ username: 'viewer', role: 'Viewer' }));
    let recovered = false;
    vi.stubGlobal('fetch', vi.fn(async () => {
      if (!recovered) throw new Error('offline');
      return reply(401);
    }));
    const { result } = renderHook(() => useAuth(callbacks));
    await act(async () => { await vi.advanceTimersByTimeAsync(19000); });
    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.currentUser.username).toBe('viewer');
    expect(localStorage.getItem('netops_token')).toBe('session-token');

    recovered = true;
    await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.authChecking).toBe(false);
    expect(localStorage.getItem('netops_token')).toBeNull();
    expect(sessionStorage.getItem('netops_session_snapshot')).toBeNull();
  });

  it('ignores a stale session response after the token is cleared', async () => {
    let resolveSession!: (response: ReturnType<typeof reply>) => void;
    vi.stubGlobal('fetch', vi.fn(() => new Promise((resolve) => { resolveSession = resolve; })));
    const { result } = renderHook(() => useAuth(callbacks));
    await act(async () => {
      window.dispatchEvent(new Event('netops:auth-expired'));
      resolveSession(reply(200, { user: { username: 'stale-user', role: 'Administrator' } }));
    });
    expect(result.current.authChecking).toBe(false);
    expect(result.current.isAuthenticated).toBe(false);
    expect(sessionStorage.getItem('netops_session_snapshot')).toBeNull();
  });
});
