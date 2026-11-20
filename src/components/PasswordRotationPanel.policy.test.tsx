// @vitest-environment jsdom
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import PasswordRotationPanel from './PasswordRotationPanel';

const jsonRes = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

describe('PasswordRotationPanel policy controls', () => {
  beforeEach(() => {
    localStorage.setItem('netops_token', 'test-token');
  });

  afterEach(() => {
    cleanup();
    localStorage.removeItem('netops_token');
    vi.unstubAllGlobals();
  });

  it('displays effective rotation policy, edits policy via modal, and requires confirmation to enable auto-rotation', async () => {
    let policyState = {
      auto_rotate_enabled: false,
      interval_days: 90,
      notify_days: 14,
      included_roles: ['admin'],
      updated_by: 'system',
      updated_at: '2026-11-20T00:00:00Z',
      next_scheduled_run_at: null as string | null,
    };

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/api/devices/rotation/status')) {
        return jsonRes({ success: true, data: [] });
      }
      if (url.endsWith('/api/devices/rotation/policy') && (!init?.method || init.method === 'GET')) {
        return jsonRes({ success: true, data: policyState });
      }
      if (url.endsWith('/api/devices/rotation/policy') && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body || '{}'));
        policyState = {
          ...policyState,
          ...body,
          next_scheduled_run_at: body.auto_rotate_enabled ? '2026-11-21T03:00:00Z' : null,
        };
        return jsonRes({ success: true, data: policyState });
      }
      if (url.endsWith('/api/devices/rotation/policy/impact')) {
        return jsonRes({
          success: true,
          data: {
            total_devices: 5,
            expired_accounts_count: 2,
            expiring_soon_accounts_count: 1,
            included_roles: policyState.included_roles,
            schedule_window: '03:00',
          },
        });
      }
      return jsonRes({ success: true, data: [] });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<PasswordRotationPanel language="zh" currentUser={{ role: 'Administrator' }} />);

    expect(await screen.findByText(/定时自动更新：已关闭（到期后需手动轮换）/)).toBeTruthy();

    // Open policy config modal and save updated settings
    fireEvent.click(screen.getByRole('button', { name: '策略配置' }));
    expect(await screen.findByText('凭据轮换策略配置')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: '保存策略' }));
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([u, init]) => String(u).endsWith('/api/devices/rotation/policy') && init?.method === 'PUT')).toBe(true);
    });

    // Click enable auto-rotation -> opens impact preview confirmation modal
    fireEvent.click(screen.getByRole('button', { name: '开启自动更新' }));
    expect(await screen.findByText('确认开启定时自动更新密码？')).toBeTruthy();
    expect(await screen.findByText(/当前已过期账号数：2/)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: '确认开启' }));
    expect(await screen.findByText(/定时自动更新：已开启/)).toBeTruthy();
  });
});
