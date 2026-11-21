// @vitest-environment jsdom
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { resetSystemInfoCache, useSystem } from './useSystem';
import { useNotifications } from './useNotifications';
import { resetInventoryDeviceCache, useInventory } from './useInventory';

const jsonRes = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

describe('Batch 2 frontend performance hooks', () => {
  beforeEach(() => {
    resetSystemInfoCache();
    localStorage.setItem('netops_token', 'tok-perf-1');
  });

  afterEach(() => {
    cleanup();
    resetSystemInfoCache();
    localStorage.removeItem('netops_token');
    vi.unstubAllGlobals();
  });

  it('useSystem deduplicates concurrent and repeated /api/system/info requests across multiple consumers', async () => {
    const fetchMock = vi.fn(async () => jsonRes({
      version: '2.0.0',
      edition: 'Enterprise',
      build_date: '2026-11-20',
      project_name: 'Nexora',
      system_name: 'Nexora',
      license: { valid: true, customer_id: 'c1', edition: 'Enterprise', expiration_date: '2099-01-01', current_version: '2.0.0' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    const Consumer = ({ label }: { label: string }) => {
      const { edition } = useSystem();
      return <span data-testid={label}>{edition}</span>;
    };

    const { rerender } = render(
      <div>
        <Consumer label="a" />
        <Consumer label="b" />
        <Consumer label="c" />
      </div>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('a').textContent).toBe('Enterprise');
      expect(screen.getByTestId('b').textContent).toBe('Enterprise');
      expect(screen.getByTestId('c').textContent).toBe('Enterprise');
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Mounting a 4th consumer later hits the in-memory cache with zero additional fetches
    rerender(
      <div>
        <Consumer label="a" />
        <Consumer label="d" />
      </div>,
    );
    expect(screen.getByTestId('d').textContent).toBe('Enterprise');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('useNotifications skips redundant state updates when polled payload is unchanged', async () => {
    const payload = [
      { id: 'n1', title: 'Alert 1', message: 'msg', time: '2026-11-20T10:00:00Z', source: 'alert', severity: 'high', read: false },
    ];
    const fetchMock = vi.fn(async () => jsonRes(payload));
    vi.stubGlobal('fetch', fetchMock);

    let renderCount = 0;
    let triggerLoad: (() => Promise<void>) | null = null;

    const Harness = () => {
      renderCount += 1;
      const hook = useNotifications({ currentUser: { id: 'u1', username: 'admin' }, language: 'zh', isAuthenticated: true });
      triggerLoad = hook.loadNotifications;
      return <span data-testid="count">{hook.unreadCount}</span>;
    };

    render(<Harness />);
    await waitFor(() => expect(screen.getByTestId('count').textContent).toBe('1'));
    const rendersAfterInitial = renderCount;

    // Poll again with identical payload -> must NOT trigger another React render
    await triggerLoad!();
    await triggerLoad!();
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(renderCount).toBe(rendersAfterInitial);
  });

  it('useInventory serves fresh cross-route cache without redundant fetches and clears on reset', async () => {
    resetInventoryDeviceCache();
    const fetchMock = vi.fn(async () => jsonRes({
      items: [{ id: 'dev-1', hostname: 'CORE-SW-01', ip_address: '10.0.0.1', status: 'online' }],
      total: 1,
    }));
    vi.stubGlobal('fetch', fetchMock);

    let triggerFetch: (() => Promise<void>) | null = null;
    const Probe = () => {
      const { devices, fetchDevicesData } = useInventory('light');
      triggerFetch = () => fetchDevicesData();
      return <span data-testid="dev-count">{devices.length}</span>;
    };

    render(<Probe />);
    await triggerFetch!();
    await waitFor(() => expect(screen.getByTestId('dev-count').textContent).toBe('1'));
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Calling again within fresh TTL hits in-memory cache with 0 extra HTTP requests
    await triggerFetch!();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Resetting cache forces a fresh fetch
    resetInventoryDeviceCache();
    await triggerFetch!();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
