import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import IPAddressTab from './IPAddressTab';

const response = (payload: unknown) => ({ ok: true, status: 200, json: async () => payload }) as Response;

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const interfaceRow = (id: string, address: string, interfaceName: string, liveness?: Record<string, unknown>) => ({
  id,
  address,
  hostname: `host-${id}`,
  source: 'manual',
  source_type: 'interface_collection',
  status: 'active',
  site_id: 'hq',
  site_name: 'HQ',
  device_id: 'dev-1',
  interface_name: interfaceName,
  device_type: 'interface',
  ...(liveness ? { interface_liveness: liveness } : {}),
});

it('shows the interface state of device interface addresses under the status column', async () => {
  const rows = [
    interfaceRow('ip-current', '10.254.0.1', 'Loop0', {
      state: 'up', freshness: 'recent', source: 'snmp', age_minutes: 5, window_minutes: 1440, alive: true,
    }),
    interfaceRow('ip-stale', '10.254.23.1', 'FGE1/0/54', {
      state: 'up', freshness: 'historical', source: 'cli_snapshot', age_minutes: 16918, window_minutes: 1440, alive: false,
    }),
    interfaceRow('ip-down', '192.168.10.1', 'Vlan10', {
      state: 'down', freshness: 'recent', source: 'snmp', age_minutes: 72, window_minutes: 1440, alive: false,
    }),
    interfaceRow('ip-unknown', '10.254.34.1', 'RAGG34', {
      state: 'unknown', freshness: 'unknown', window_minutes: 1440, alive: false,
    }),
    { ...interfaceRow('ip-server', '10.0.0.20', ''), device_id: '', source_type: 'manual', device_type: 'server' },
  ];
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://localhost');
    if (url.pathname === '/api/ipam/addresses') {
      return response({ items: rows, total: rows.length, summary: { manual: rows.length, discovered: 0 }, sites: [] });
    }
    return response([]);
  }));

  render(<MemoryRouter initialEntries={['/ipam/ips']}><IPAddressTab language="zh" t={(key) => key} /></MemoryRouter>);

  expect(await screen.findByText('host-ip-current')).toBeTruthy();
  const badges = screen.getAllByTestId('ip-interface-liveness');
  expect(badges.map((badge) => [badge.textContent, badge.getAttribute('data-tone')])).toEqual([
    ['接口 up · 5 分钟前', 'current'],
    ['接口 up · 11 天前', 'stale'],
    ['接口 down · 1 小时前', 'down'],
  ]);
  expect(badges[0].getAttribute('title')).toBe('设备接口地址，存活以接口状态为准（来源：SNMP 接口表，5 分钟前采集）');
  expect(badges[1].getAttribute('title')).toContain('已超过 1 天，可能不是当前状态');
  expect(badges[2].className).toContain('rose');
});
