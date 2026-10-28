import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import DiscoveredEndpointsTab from './DiscoveredEndpointsTab';

const response = (payload: unknown, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => payload }) as Response;

const item = {
  id: 'obs-1', ip: '10.10.1.21', mac: '00:11:22:33:44:55', tenant_id: 'tenant-1',
  site_id: 'site-1', site_name: 'WH-DC-01', vrf_id: null, vrf_name: null,
  scope_status: 'resolved', registration_status: 'unregistered', subnet_id: null, subnet_prefix: null,
  source_device_id: 'switch-1', source_device_name: 'SW-01', switch_id: 'switch-1', switch_name: 'SW-01',
  switch_port: null, vlan: '20', observed_at: '2026-10-28T10:00:00+08:00', mac_observed_at: null,
  projected_at: '2026-10-28T10:01:00+08:00', evidence_status: 'recent', hostname: '',
};

const renderPage = () => render(<MemoryRouter><DiscoveredEndpointsTab language="zh" t={(key) => key} /></MemoryRouter>);

describe('DiscoveredEndpointsTab', () => {
  beforeEach(() => {
    localStorage.setItem('netops_token', 'test-token');
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/ipam/endpoints?')) return response({
        items: [item], total: 1, page: 1, page_size: 20, has_more: false,
        summary: { discovered_ip_count: 1, mac_only_count: 0, registered_count: 0, unregistered_count: 1, coverage_status: 'partial', coverage_reason: '部分来源缺少范围' },
        sites: [{ site_id: 'site-1', site_name: 'WH-DC-01' }], vrfs: [], devices: [{ device_id: 'switch-1', device_name: 'SW-01' }],
      });
      if (url === '/api/ipam/endpoints/obs-1') return response({ ...item, observations: [{ source_type: 'arp', source_device_name: 'SW-01', interface_name: null, vlan: '20', ip: item.ip, mac: item.mac, observed_at: item.observed_at, projected_at: item.projected_at, source_version: 'run-17', coverage_status: 'partial' }] });
      return response({});
    }));
  });

  afterEach(() => {
    cleanup();
    localStorage.removeItem('netops_token');
    vi.unstubAllGlobals();
  });

  it('loads the default IP list, exposes unknown identity and pending ARP port, then loads evidence on demand', async () => {
    renderPage();
    expect(await screen.findByText('10.10.1.21')).toBeTruthy();
    expect(screen.getByText('端口待定位（无 MAC 表证据）')).toBeTruthy();
    expect(screen.getByText('未知')).toBeTruthy();
    expect(screen.getByText('类型未知')).toBeTruthy();

    const fetchMock = vi.mocked(fetch);
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes('/api/ipam/endpoints?kind=ip'))).toBe(true);
    expect(fetchMock.mock.calls.some(([input]) => String(input).startsWith('/api/devices?'))).toBe(false);

    fireEvent.click(screen.getByRole('button', { name: '查看来源证据' }));
    expect(await screen.findByRole('dialog', { name: '发现来源证据' })).toBeTruthy();
    expect(await screen.findByText(/run-17/)).toBeTruthy();
    expect(fetchMock.mock.calls.some(([input]) => String(input) === '/api/ipam/endpoints/obs-1')).toBe(true);
  });

  it('sends the MAC-only filter to the paginated endpoint API', async () => {
    renderPage();
    await screen.findByText('10.10.1.21');
    fireEvent.change(screen.getByRole('combobox', { name: '记录类型筛选' }), { target: { value: 'mac' } });
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).includes('/api/ipam/endpoints?kind=mac'))).toBe(true));
  });

  it('builds the source device filter from authorized response metadata', async () => {
    renderPage();
    await screen.findByText('10.10.1.21');
    fireEvent.change(screen.getByRole('combobox', { name: '来源设备筛选' }), { target: { value: 'switch-1' } });
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).includes('device_id=switch-1'))).toBe(true));
  });

  it('ignores an older list response after a newer filter request completes', async () => {
    let resolveOld: ((value: Response) => void) | undefined;
    const oldResponse = new Promise<Response>((resolve) => { resolveOld = resolve; });
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/ipam/endpoints' && url.searchParams.get('kind') === 'ip') return oldResponse;
      if (url.pathname === '/api/ipam/endpoints' && url.searchParams.get('kind') === 'all') {
        return Promise.resolve(response({ items: [{ ...item, id: 'obs-new', ip: '10.10.1.22' }], total: 1, summary: {}, sites: [], vrfs: [], devices: [] }));
      }
      return Promise.resolve(response({}));
    }));
    renderPage();
    fireEvent.change(await screen.findByRole('combobox', { name: '记录类型筛选' }), { target: { value: 'all' } });
    expect(await screen.findByText('10.10.1.22')).toBeTruthy();
    resolveOld?.(response({ items: [item], total: 1, summary: {}, sites: [], vrfs: [], devices: [] }));
    await waitFor(() => expect(screen.queryByText('10.10.1.21')).toBeNull());
  });

  it('shows a clear permission error instead of an empty success state', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => String(input).startsWith('/api/ipam/endpoints?')
      ? response({ detail: 'forbidden' }, 403)
      : response({ items: [] })));
    renderPage();
    expect((await screen.findByRole('alert')).textContent).toContain('当前账号没有权限查看发现终端');
    expect(screen.queryByText('当前筛选没有发现记录。清除筛选或更换条件后重试。')).toBeNull();
  });
});
