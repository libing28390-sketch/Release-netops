import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import IPAddressDetailDrawer, { type IPAddressDetailSeed } from './IPAddressDetailDrawer';

const response = (payload: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => payload,
}) as Response;

const seed: IPAddressDetailSeed = {
  id: 'ip-loop0',
  address: '10.254.0.1',
  status: 'active',
  purpose: 'loopback',
  device_type: 'loopback',
  subnet_prefix: '10.254.0.1/32',
  site_name: 'WH-DC-01',
  hostname: 'S6850_1',
  interface_name: 'Loop0',
};

const renderDrawer = (addressOverrides: Record<string, unknown>) => {
  const fetchMock = vi.fn(async () => response({
    address: { ...seed, device_id: 'dev-1', vrf_name: '', ...addressOverrides },
    interface: null,
    discovery: [],
    same_ip_elsewhere: [],
    history: [],
  }));
  vi.stubGlobal('fetch', fetchMock);
  // The drawer links to the locator / prefix pages, so it needs a router.
  render(
    <MemoryRouter initialEntries={['/ipam/ips']}>
      <IPAddressDetailDrawer
        zh
        seed={seed}
        authHeaders={() => ({})}
        onClose={() => undefined}
        statusLabel={(status) => status}
        purposeLabel={(purpose) => purpose}
        roleLabel={(role) => role}
      />
    </MemoryRouter>,
  );
  return fetchMock;
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('IPAddressDetailDrawer interface liveness', () => {
  it('shows a current up interface from the SNMP table', async () => {
    const fetchMock = renderDrawer({
      interface_liveness: {
        state: 'up', freshness: 'recent', source: 'snmp', age_minutes: 5, window_minutes: 1440, alive: true,
      },
    });

    const box = await screen.findByTestId('ip-detail-liveness');
    expect(fetchMock).toHaveBeenCalledWith('/api/ipam/addresses/ip-loop0/detail', expect.anything());
    expect(box.textContent).toContain('存活判断：设备接口地址，以接口状态为准');
    expect(box.textContent).toContain('接口 up · 5 分钟前采集 · 来源 SNMP 接口表 · 当前');
    expect(box.textContent).toContain('下方的 ARP 记录仅供参考');
    expect(box.className).toContain('emerald');
  });

  it('warns that an old CLI snapshot may no longer be current', async () => {
    renderDrawer({
      interface_liveness: {
        state: 'up', freshness: 'historical', source: 'cli_snapshot', age_minutes: 16918, window_minutes: 1440, alive: false,
      },
    });

    const box = await screen.findByTestId('ip-detail-liveness');
    expect(box.textContent).toContain('接口 up · 11 天前采集 · 来源 CLI 接口采集 · 已超过 1 天，可能不是当前状态');
    expect(box.className).toContain('amber');
  });

  it('shows a down gateway interface in red', async () => {
    renderDrawer({
      interface_name: 'Vlan10',
      interface_liveness: {
        state: 'down', freshness: 'recent', source: 'snmp', age_minutes: 0, window_minutes: 1440, alive: false,
      },
    });

    const box = await screen.findByTestId('ip-detail-liveness');
    expect(box.textContent).toContain('接口 down · 0 分钟前采集 · 来源 SNMP 接口表 · 当前');
    expect(box.className).toContain('rose');
  });

  it('explains when there is no interface state yet', async () => {
    renderDrawer({
      interface_name: 'RAGG34',
      interface_liveness: { state: 'unknown', freshness: 'unknown', window_minutes: 1440, alive: false },
    });

    const box = await screen.findByTestId('ip-detail-liveness');
    expect(box.textContent).toContain('没有接口状态记录');
    expect(box.textContent).not.toContain('采集 · 来源');
  });

  it('omits the liveness box for addresses that are not bound to a device interface', async () => {
    renderDrawer({ device_id: '', interface_name: '' });

    expect(await screen.findByText('全局（无 VRF）')).toBeTruthy();
    await waitFor(() => expect(screen.queryByText('正在加载详情…')).toBeNull());
    expect(screen.queryByTestId('ip-detail-liveness')).toBeNull();
  });
});
