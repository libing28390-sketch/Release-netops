import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import IPAddressTab from './IPAddressTab';

const response = (payload: unknown) => ({ ok: true, status: 200, json: async () => payload }) as Response;
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('preserves URL-based collected-source scope without an include-sources control', async () => {
  const formal = { id: 'ip-1', address: '192.0.2.10', hostname: 'registered-server', source: 'manual', status: 'active', site_id: 'hq', site_name: 'HQ', device_type: 'server' };
  const observed = { ...formal, id: 'discovered-arp-1', source: 'discovered', is_discovered: true, hostname: 'collected-host', device_type: 'host', observed_source_device_name: 'core-a', observed_source_type: 'arp', observed_context_key: 'VRF_BLUE', address_space_id: 'blue' };
  const fetcher = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://localhost');
    if (url.pathname === '/api/ipam/addresses') {
      const items = url.searchParams.get('registered_only') === 'true' ? [formal] : [formal, observed];
      return response({ items, total: items.length, summary: { manual: 1, discovered: items.length - 1 }, sites: [] });
    }
    return response([]);
  });
  vi.stubGlobal('fetch', fetcher);
  render(<MemoryRouter initialEntries={['/ipam/ips?view=sources']}><IPAddressTab language="zh" t={key => key} /></MemoryRouter>);
  expect(await screen.findByText('registered-server')).toBeTruthy();
  expect(await screen.findByText('collected-host')).toBeTruthy();
  expect(screen.queryByRole('checkbox', { name: '包含采集来源' })).toBeNull();
  fireEvent.click(screen.getByText('查看来源依据'));
  expect(screen.getByText('core-a')).toBeTruthy();
  expect(screen.getByText('VRF_BLUE')).toBeTruthy();
});
