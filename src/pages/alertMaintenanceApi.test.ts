import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createAlertMaintenanceWindow } from './alertMaintenanceApi';

const response = (body: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  headers: new Headers(),
  json: vi.fn().mockResolvedValue(body),
}) as unknown as Response;

const payload = {
  name: 'Planned maintenance',
  target_ip: '192.0.2.10',
  target_ips: ['192.0.2.10'],
  selection_mode: 'resources' as const,
  condition_logic: 'all' as const,
  match_conditions: [],
  starts_at: '2026-11-03T02:00:00.000Z',
  ends_at: '2026-11-03T03:00:00.000Z',
  reason: 'Network upgrade',
  notify_user_ids: [],
  created_by: 'operator',
};

describe('alert maintenance API', () => {
  beforeEach(() => localStorage.setItem('netops_token', 'maintenance-test-token'));

  afterEach(() => {
    localStorage.removeItem('netops_token');
    vi.unstubAllGlobals();
  });

  it('sends the session token when creating a maintenance window', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ id: 'maintenance-1' }));
    vi.stubGlobal('fetch', fetchMock);

    await createAlertMaintenanceWindow(payload);

    expect(fetchMock).toHaveBeenCalledWith('/api/alerts/maintenance-windows', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify(payload),
    }));
    const requestHeaders = new Headers(fetchMock.mock.calls[0][1]?.headers);
    expect(requestHeaders.get('Authorization')).toBe('Bearer maintenance-test-token');
    expect(requestHeaders.get('Content-Type')).toBe('application/json');
  });

  it('preserves the authentication failure status and notifies the app when the session expired', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ detail: 'Authentication required' }, 401)));
    const onAuthExpired = vi.fn();
    window.addEventListener('netops:auth-expired', onAuthExpired);

    try {
      await expect(createAlertMaintenanceWindow(payload)).rejects.toMatchObject({ status: 401 });
      expect(onAuthExpired).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener('netops:auth-expired', onAuthExpired);
    }
  });
});
