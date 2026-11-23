import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import IPAddressTab from './IPAddressTab';

const response = (payload: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => payload,
}) as Response;

const prefixes = [
  { id: 'prefix-1', prefix: '10.0.0.0/24', name: 'Office', network_type: 'server', gateway: '10.0.0.1' },
  { id: 'prefix-2', prefix: '10.1.0.0/24', name: 'Remote', network_type: 'server', gateway: '10.1.0.1' },
];

const eligiblePool = (id: string, prefixId: string, start: string, end: string) => ({
  id,
  name: `Static ${id}`,
  prefix_id: prefixId,
  prefix: prefixes.find((prefix) => prefix.id === prefixId)?.prefix,
  start_ip: start,
  end_ip: end,
  status: 'active',
  management_mode: 'local_static',
  allocation_allowed: true,
  mark_populated: false,
  mark_utilized: false,
  policy_pending: false,
});

const inventoryPayload = {
  items: [],
  total: 0,
  has_more: false,
  sites: [],
  summary: { gateways: 0, prefixes: 2, manual: 0, interface_observed: 0, discovered: 0 },
};

const setup = (options: {
  poolRows?: Record<string, unknown>[];
  poolStatus?: number;
  poolsByPrefix?: Record<string, Record<string, unknown>[]>;
  addressRows?: Record<string, unknown>[];
} = {}) => {
  const requests: Array<{ url: string; method: string; body?: Record<string, unknown>; headers?: HeadersInit }> = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = String(init?.method || 'GET').toUpperCase();
    const parsedUrl = new URL(url, 'http://localhost');

    if (String(url).split('?')[0] === '/api/ipam/subnets') return response(prefixes);
    if (url.startsWith('/api/ipam/addresses?')) {
      if (parsedUrl.searchParams.get('registered_only') === 'true') {
        return response({ items: options.addressRows || [], total: (options.addressRows || []).length });
      }
      return response({ ...inventoryPayload, items: options.addressRows || [], total: (options.addressRows || []).length });
    }
    if (url.startsWith('/api/ipam/pools?')) {
      if (options.poolStatus && options.poolStatus !== 200) return response({ detail: 'pool access denied' }, options.poolStatus);
      const prefixId = parsedUrl.searchParams.get('prefix_id') || '';
      const rows = options.poolsByPrefix?.[prefixId] || options.poolRows || [];
      return response({ items: rows, total: rows.length });
    }
    if (parsedUrl.pathname.startsWith('/api/ipam/subnets/') && parsedUrl.pathname.endsWith('/next-available-ip')) {
      requests.push({ url, method });
      return response({ next_available_ip: '10.0.0.20', pending_discovery_count: 2 });
    }
    if (url.endsWith('/addresses') && method === 'POST') {
      requests.push({ url, method, body: JSON.parse(String(init?.body || '{}')), headers: init?.headers });
      return response({ id: 'ip-new', address: '10.0.0.20', status: 'active' });
    }
    if (parsedUrl.pathname === '/api/ipam/addresses/ip-1' && method === 'PUT') {
      requests.push({ url, method, body: JSON.parse(String(init?.body || '{}')), headers: init?.headers });
      return response({ id: 'ip-1' });
    }
    if (parsedUrl.pathname === '/api/ipam/addresses/ip-1/release' && method === 'POST') {
      requests.push({ url, method, body: JSON.parse(String(init?.body || '{}')), headers: init?.headers });
      return response({ ok: true });
    }
    return response([]);
  });

  vi.stubGlobal('fetch', fetchMock);
  render(
    <MemoryRouter initialEntries={['/ipam/ips?prefix_id=prefix-1']}>
      <IPAddressTab language="zh" t={(key) => key} />
    </MemoryRouter>,
  );
  return { fetchMock, requests };
};

const openAllocationForm = async () => {
  await screen.findByPlaceholderText('搜索 CIDR 或名称...');
  fireEvent.click(screen.getByRole('button', { name: '分配IP地址' }));
  await screen.findByRole('heading', { name: '分配IP地址' });
};

describe('IPAddressTab pool-bounded allocation', () => {
  beforeEach(() => {
    localStorage.removeItem('netops_token');
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('offers only pools that are active, local, allocatable, unpopulated, and confirmed', async () => {
    setup({
      poolRows: [
        eligiblePool('eligible', 'prefix-1', '10.0.0.10', '10.0.0.30'),
        { ...eligiblePool('reserved', 'prefix-1', '10.0.0.40', '10.0.0.50'), status: 'reserved' },
        { ...eligiblePool('external', 'prefix-1', '10.0.0.60', '10.0.0.70'), management_mode: 'external_dhcp' },
        { ...eligiblePool('disabled', 'prefix-1', '10.0.0.80', '10.0.0.90'), allocation_allowed: false },
        { ...eligiblePool('populated', 'prefix-1', '10.0.0.100', '10.0.0.110'), mark_populated: true },
        { ...eligiblePool('pending', 'prefix-1', '10.0.0.120', '10.0.0.130'), policy_pending: true },
      ],
    });
    await openAllocationForm();

    const poolSelect = await screen.findByRole('combobox', { name: '分配范围' }) as HTMLSelectElement;
    await waitFor(() => expect(poolSelect.querySelectorAll('option')).toHaveLength(2));
    await waitFor(() => expect(poolSelect.disabled).toBe(false));
    expect(Array.from(poolSelect.options).map((option) => option.value)).toEqual(['', 'eligible']);
  });

  it('uses the selected pool for both the recommendation query and the create payload', async () => {
    const { requests } = setup({ poolRows: [eligiblePool('pool-1', 'prefix-1', '10.0.0.10', '10.0.0.30')] });
    await openAllocationForm();
    const poolSelect = await screen.findByRole('combobox', { name: '分配范围' }) as HTMLSelectElement;
    await waitFor(() => expect(poolSelect.options).toHaveLength(2));
    await waitFor(() => expect(poolSelect.disabled).toBe(false));
    fireEvent.change(poolSelect, { target: { value: 'pool-1' } });
    fireEvent.click(screen.getByRole('button', { name: '获取推荐 IP' }));

    await waitFor(() => expect(requests.some((request) => request.url === '/api/ipam/subnets/prefix-1/next-available-ip?pool_id=pool-1')).toBe(true));
    expect((screen.getByPlaceholderText('e.g. 10.1.1.10') as HTMLInputElement).value).toBe('10.0.0.20');
    expect(screen.getByText(/当前页面中另有 2 个/)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: '确定保存' }));
    await waitFor(() => expect(requests.some((request) => request.method === 'POST')).toBe(true));
    expect(requests.find((request) => request.method === 'POST')?.body).toMatchObject({
      subnet_id: 'prefix-1',
      pool_id: 'pool-1',
      address: '10.0.0.20',
    });
    expect(new Headers(requests.find((request) => request.method === 'POST')?.headers).get('Idempotency-Key')).toBeTruthy();
  });

  it('clears the selected pool when the Prefix changes', async () => {
    setup({
      poolsByPrefix: {
        'prefix-1': [eligiblePool('pool-1', 'prefix-1', '10.0.0.10', '10.0.0.30')],
        'prefix-2': [eligiblePool('pool-2', 'prefix-2', '10.1.0.10', '10.1.0.30')],
      },
    });
    await openAllocationForm();
    const poolSelect = await screen.findByRole('combobox', { name: '分配范围' }) as HTMLSelectElement;
    await waitFor(() => expect(poolSelect.options).toHaveLength(2));
    await waitFor(() => expect(poolSelect.disabled).toBe(false));
    fireEvent.change(poolSelect, { target: { value: 'pool-1' } });

    const prefixSearch = screen.getByPlaceholderText('搜索 CIDR 或名称...');
    fireEvent.focus(prefixSearch);
    fireEvent.click(await screen.findByRole('button', { name: /10\.1\.0\.0\/24/ }));

    await waitFor(() => expect(poolSelect.value).toBe(''));
    await waitFor(() => expect(poolSelect.options[1]?.value).toBe('pool-2'));
  });

  it('disables pool selection and reports 401/403 instead of assuming a pool is available', async () => {
    setup({ poolStatus: 403 });
    await openAllocationForm();

    const poolSelect = await screen.findByRole('combobox', { name: '分配范围' }) as HTMLSelectElement;
    expect((await screen.findByRole('alert')).textContent).toContain('当前账号没有查看此网段地址池的权限，已停止池选择。');
    expect(poolSelect.disabled).toBe(true);
    expect(Array.from(poolSelect.options).map((option) => option.value)).toEqual(['']);
  });

  it('keeps quick matrix allocation outside the pool selector', async () => {
    const { fetchMock, requests } = setup({ poolRows: [eligiblePool('pool-1', 'prefix-1', '10.0.0.10', '10.0.0.30')] });
    fireEvent.click(await screen.findByRole('button', { name: '矩阵' }));
    fireEvent.click(await screen.findByTitle('10.0.0.2 (空闲)'));

    await screen.findByRole('heading', { name: '快速分配 IP' });
    expect(screen.queryByRole('combobox', { name: '分配范围' })).toBeNull();
    expect(fetchMock.mock.calls.some(([url]) => String(url).startsWith('/api/ipam/pools?'))).toBe(false);

    fireEvent.click(screen.getByRole('button', { name: '确认分配' }));
    await waitFor(() => expect(requests.some((request) => request.method === 'POST')).toBe(true));
    expect(requests.find((request) => request.method === 'POST')?.body).not.toHaveProperty('pool_id');
    expect(new Headers(requests.find((request) => request.method === 'POST')?.headers).get('Idempotency-Key')).toBeTruthy();
  });

  it('sends revisions for registered IP edits and release operations', async () => {
    const address = {
      id: 'ip-1', revision: 41, subnet_id: 'prefix-1', address: '10.0.0.30', hostname: 'server-1',
      device_id: '', interface_name: '', mac_address: '', device_type: 'server', purpose: 'business',
      status: 'active', description: '', expires_at: '', last_seen: '', created_at: '', updated_at: '',
      is_discovered: false, is_virtual_gateway: false, is_prefix_gateway: false,
    };
    const { requests } = setup({ addressRows: [address] });
    const row = (await screen.findByText('10.0.0.30')).closest('tr')!;
    fireEvent.click(within(row).getByRole('button', { name: '编辑' }));
    await screen.findByRole('heading', { name: '编辑IP记录' });
    fireEvent.click(screen.getByRole('button', { name: '确定保存' }));

    await waitFor(() => expect(requests.some((request) => request.method === 'PUT')).toBe(true));
    expect(requests.find((request) => request.method === 'PUT')?.body).toMatchObject({ expected_revision: 41 });

    const refreshedRow = screen.getByText('10.0.0.30').closest('tr')!;
    fireEvent.click(within(refreshedRow).getByRole('button', { name: '删除' }));
    fireEvent.click(await screen.findByRole('button', { name: '释放IP' }));
    await waitFor(() => expect(requests.some((request) => request.url.endsWith('/release'))).toBe(true));
    expect(requests.find((request) => request.url.endsWith('/release'))?.body).toEqual({ expected_revision: 41 });
  });
});
