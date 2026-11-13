import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import DHCPLeaseTab, { filterExternalDhcpPools, formatLocalDateInput, getDefaultLeaseDateRange } from './DHCPLeaseTab';

const response = (payload: unknown, status = 200, ok = true) => ({
  ok,
  status,
  json: async () => payload,
}) as Response;

const externalPool = {
  id: 'pool-dhcp-1', name: 'Office DHCP', address_space_id: 'space-1', address_space_name: 'Office Global',
  start_ip: '10.0.0.100', end_ip: '10.0.0.199', management_mode: 'external_dhcp',
  status: 'active', allocation_allowed: false, mark_populated: false, policy_pending: false,
};

const localPool = {
  id: 'pool-static-1', name: 'Static', address_space_id: 'space-1', start_ip: '10.0.0.10',
  end_ip: '10.0.0.99', management_mode: 'local_static', status: 'active',
  allocation_allowed: true, mark_populated: false, policy_pending: false,
};

const baseLease = {
  id: 'lease-1', revision: 13, address: '10.0.0.111', mac_address: '00:11:22:33:44:55', hostname: 'workstation',
  dhcp_server: 'Infoblox', lease_state: 'active', lease_start: '2026-11-05', lease_end: '2026-11-12',
  pool_id: null, pool_name: null, address_space_id: null, address_space_name: null,
  scope_pending: true, scope_status: 'scope_unknown',
};

const setup = (
  leases: Record<string, unknown>[] = [],
  pools: Record<string, unknown>[] = [externalPool, localPool],
) => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.startsWith('/api/ipam/leases?')) return response({ items: leases, total: leases.length });
    if (url.startsWith('/api/ipam/pools?')) return response({ items: pools, total: pools.length });
    if (url === '/api/ipam/leases' && init?.method === 'POST') return response({ id: 'lease-new' });
    if (url.startsWith('/api/ipam/leases/') && init?.method === 'PUT') return response({ ok: true });
    return response({});
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<DHCPLeaseTab language="zh" t={(key) => key} />);
  return fetchMock;
};

const openCreateForm = async () => {
  fireEvent.click(await screen.findByRole('button', { name: '创建租约' }));
  await screen.findByRole('heading', { name: '登记租约' });
};

const fillLeaseFields = () => {
  fireEvent.change(screen.getByLabelText('分配 IP 地址 *'), { target: { value: '10.0.0.111' } });
  fireEvent.change(screen.getByLabelText('客户端 MAC 物理地址 *'), { target: { value: '00:11:22:33:44:55' } });
};

describe('DHCP lease local date defaults', () => {
  it('formats date input values from local calendar fields, not UTC serialization', () => {
    const localDate = {
      getFullYear: () => 2026,
      getMonth: () => 9,
      getDate: () => 29,
    } as Pick<Date, 'getFullYear' | 'getMonth' | 'getDate'>;

    expect(formatLocalDateInput(localDate)).toBe('2026-10-29');
  });

  it('defaults a new lease to the local date and seven local calendar days later', () => {
    const now = new Date(2026, 9, 29, 0, 30);
    const expectedEnd = new Date(now);
    expectedEnd.setDate(expectedEnd.getDate() + 7);

    expect(getDefaultLeaseDateRange(now)).toEqual({
      start: formatLocalDateInput(now),
      end: formatLocalDateInput(expectedEnd),
    });
  });
});

describe('DHCP lease scope and Pool link', () => {
  beforeEach(() => {
    localStorage.removeItem('netops_token');
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('offers only confirmed active external DHCP pools', () => {
    expect(filterExternalDhcpPools([
      externalPool,
      localPool,
      { ...externalPool, id: 'pending', policy_pending: true },
      { ...externalPool, id: 'inactive', status: 'reserved' },
      { ...externalPool, id: 'unscoped', address_space_id: null },
    ]).map((pool) => pool.id)).toEqual(['pool-dhcp-1']);
  });

  it('shows an unlinked DHCP lease as a pending observation scope', async () => {
    setup([{ ...baseLease, scope_pending: true, scope_status: 'scope_unknown' }]);

    expect(await screen.findByText('范围待确认')).toBeTruthy();
    expect(screen.getByText('DHCP 租约是外部观测，不等同于静态 IP 归属；仅明确关联到外部 DHCP 池时显示所属地址空间')).toBeTruthy();
  });

  it('keeps scope unknown leases pending even if an address-space value is present', async () => {
    setup([{
      ...baseLease,
      address_space_id: 'space-1',
      address_space_name: 'Office Global',
      scope_pending: false,
      scope_status: 'scope_unknown',
    }]);

    expect(await screen.findByText('范围待确认')).toBeTruthy();
    expect(screen.queryByText('Office Global')).toBeNull();
  });

  it('saves an optional external DHCP pool link without tenant or address-space overrides', async () => {
    const fetchMock = setup();
    await openCreateForm();
    fillLeaseFields();
    const poolSelect = await screen.findByLabelText('外部 DHCP 地址池');
    expect(Array.from((poolSelect as HTMLSelectElement).options).some((option) => option.value === 'pool-static-1')).toBe(false);
    fireEvent.change(poolSelect, { target: { value: externalPool.id } });
    fireEvent.click(screen.getByRole('button', { name: '确认保存' }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/ipam/leases' && init?.method === 'POST')).toBe(true));
    const [, init] = fetchMock.mock.calls.find(([url, request]) => String(url) === '/api/ipam/leases' && request?.method === 'POST')!;
    const payload = JSON.parse(String(init?.body));
    expect(payload).toMatchObject({ pool_id: 'pool-dhcp-1', address: '10.0.0.111' });
    expect(new Headers(init?.headers).get('Idempotency-Key')).toBeTruthy();
    expect(payload).not.toHaveProperty('tenant_id');
    expect(payload).not.toHaveProperty('address_space_id');
  });

  it('allows an unscoped lease as a pending observation without claiming a domain', async () => {
    const fetchMock = setup();
    await openCreateForm();
    fillLeaseFields();
    await screen.findByLabelText('外部 DHCP 地址池');
    expect(screen.getByText('未关联外部 DHCP 池时，租约范围保持待确认。')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '确认保存' }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/ipam/leases' && init?.method === 'POST')).toBe(true));
    const [, init] = fetchMock.mock.calls.find(([url, request]) => String(url) === '/api/ipam/leases' && request?.method === 'POST')!;
    const payload = JSON.parse(String(init?.body));
    expect(payload).not.toHaveProperty('pool_id');
    expect(payload).not.toHaveProperty('tenant_id');
    expect(payload).not.toHaveProperty('address_space_id');
  });

  it('stops Pool selection on a permission error instead of assuming a scope', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/ipam/leases?')) return response({ items: [], total: 0 });
      if (url.startsWith('/api/ipam/pools?')) return response({ detail: 'denied' }, 403, false);
      return response({});
    }));
    render(<DHCPLeaseTab language="zh" t={(key) => key} />);
    await openCreateForm();

    expect(await screen.findByText('当前账号没有查看外部 DHCP 池的权限，已停止池选择。')).toBeTruthy();
    expect((screen.getByLabelText('外部 DHCP 地址池') as HTMLSelectElement).disabled).toBe(true);
  });

  it.each([
    [401, '登录已过期，无法加载外部 DHCP 池，请重新登录后重试。'],
    [500, '加载外部 DHCP 池失败，已停止池选择。'],
  ])('stops Pool selection and explains HTTP %s load failures', async (status, expectedMessage) => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/ipam/leases?')) return response({ items: [], total: 0 });
      if (url.startsWith('/api/ipam/pools?')) return response({ detail: 'failed' }, status, false);
      return response({});
    }));
    render(<DHCPLeaseTab language="zh" t={(key) => key} />);
    await openCreateForm();

    expect(await screen.findByText(expectedMessage)).toBeTruthy();
    expect((screen.getByLabelText('外部 DHCP 地址池') as HTMLSelectElement).disabled).toBe(true);
  });

  it('stops Pool selection when the pool request fails at the network layer', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/ipam/leases?')) return response({ items: [], total: 0 });
      if (url.startsWith('/api/ipam/pools?')) throw new Error('network failure');
      return response({});
    }));
    render(<DHCPLeaseTab language="zh" t={(key) => key} />);
    await openCreateForm();

    expect(await screen.findByText('加载外部 DHCP 池失败，已停止池选择。请检查网络后重试。')).toBeTruthy();
    expect((screen.getByLabelText('外部 DHCP 地址池') as HTMLSelectElement).disabled).toBe(true);
  });

  it('sends the current revision for lease edits and deletes', async () => {
    const fetchMock = setup([baseLease]);
    await screen.findByText('10.0.0.111');
    fireEvent.click(screen.getByRole('button', { name: '编辑' }));
    fireEvent.click(await screen.findByRole('button', { name: '确认保存' }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/ipam/leases/lease-1' && init?.method === 'PUT')).toBe(true));
    const [, updateInit] = fetchMock.mock.calls.find(([url, init]) => String(url) === '/api/ipam/leases/lease-1' && init?.method === 'PUT')!;
    expect(JSON.parse(String(updateInit?.body))).toMatchObject({ expected_revision: 13 });

    fireEvent.click(screen.getByRole('button', { name: '删除' }));
    fireEvent.click(await screen.findByRole('button', { name: '确定删除' }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => (
      String(url).startsWith('/api/ipam/leases/lease-1?') && init?.method === 'DELETE'
    ))).toBe(true));
    const [deleteUrl] = fetchMock.mock.calls.find(([url, init]) => String(url).startsWith('/api/ipam/leases/lease-1?') && init?.method === 'DELETE')!;
    expect(new URL(String(deleteUrl), 'http://localhost').searchParams.get('expected_revision')).toBe('13');
  });
});
