import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import IPPoolTab from './IPPoolTab';

const response = (payload: unknown) => ({ ok: true, status: 200, json: async () => payload }) as Response;

const prefix = { id: 'prefix-1', prefix: '10.0.0.0/24', name: 'Office', tenant_id: 'tenant-default' };

const basePool = {
  id: 'pool-1', revision: 7, name: 'Reserved range', prefix_id: 'prefix-1', prefix: '10.0.0.0/24',
  prefix_name: 'Office', start_ip: '10.0.0.100', end_ip: '10.0.0.109', description: '',
  status: 'reserved', tenant_id: 'tenant-default', tenant_name: null,
  total_ips: 10, used_ips: 0, utilization: 0,
};

const setup = (poolRows: Record<string, unknown>[] = []) => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.startsWith('/api/ipam/pools?')) return response({ items: poolRows, total: poolRows.length });
    if (url === '/api/ipam/subnets') return response([prefix]);
    if (url === '/api/ipam/pools' && init?.method === 'POST') return response({ id: 'pool-new' });
    if (url.startsWith('/api/ipam/pools/') && init?.method === 'PUT') return response({ ok: true });
    return response({});
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<IPPoolTab language="zh" t={(key) => key} />);
  return fetchMock;
};

const openCreateForm = async () => {
  await screen.findByText('暂无地址范围记录');
  fireEvent.click(screen.getByRole('button', { name: '创建地址池' }));
  await screen.findByRole('heading', { name: '新建地址池' });
};

const fillRequiredFields = () => {
  fireEvent.change(screen.getByLabelText('地址池名称 *'), { target: { value: 'Office static' } });
  fireEvent.change(screen.getByLabelText('所属网段 *'), { target: { value: 'prefix-1' } });
  fireEvent.change(screen.getByLabelText('起始 IP 地址 *'), { target: { value: '10.0.0.100' } });
  fireEvent.change(screen.getByLabelText('结束 IP 地址 *'), { target: { value: '10.0.0.109' } });
};

describe('IPPoolTab status presentation', () => {
  beforeEach(() => {
    localStorage.removeItem('netops_token');
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/ipam/pools?')) return response({
        items: [{
          ...basePool,
          management_mode: 'reserved', allocation_allowed: false,
          mark_populated: false, mark_utilized: false, policy_pending: false,
        }],
        total: 1,
      });
      if (url === '/api/ipam/subnets') return response([]);
      return response({});
    }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('uses a warning tone for reserved pools', async () => {
    render(<IPPoolTab language="zh" t={(key) => key} />);
    const badge = (await screen.findByText('RESERVED')).closest('span');
    expect(badge?.className).toContain('bg-amber-50');
    expect(badge?.className).not.toContain('bg-emerald-50');
  });

  it('shows legacy pools with an unknown policy as pending and allocation restricted', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/ipam/pools?')) return response({
        items: [{ ...basePool, management_mode: null, allocation_allowed: false, policy_pending: true }],
        total: 1,
      });
      if (url === '/api/ipam/subnets') return response([prefix]);
      return response({});
    }));

    render(<IPPoolTab language="zh" t={(key) => key} />);

    expect(await screen.findByText('策略待确认')).toBeTruthy();
    expect(screen.getByText('策略未确认，分配受限')).toBeTruthy();
    expect(screen.getByText('本地分配: 受限')).toBeTruthy();
  });

  it('shows a non-active local static pool as paused even when allocation is configured', async () => {
    const fetchMock = setup([{
      ...basePool, status: 'reserved', management_mode: 'local_static',
      allocation_allowed: true, mark_populated: false, mark_utilized: false,
      policy_pending: false,
    }]);

    expect(await screen.findByText('本地分配: 暂停')).toBeTruthy();
    expect(screen.getByText('生命周期状态为保留，当前暂停分配')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: '编辑' }));
    const allocation = await screen.findByLabelText('允许本地静态分配') as HTMLInputElement;
    expect(allocation.checked).toBe(true);
    expect(screen.getByText(/管理方式和分配策略会保留/)).toBeTruthy();

    fireEvent.change(screen.getByLabelText('生命周期状态'), { target: { value: 'active' } });
    expect(allocation.checked).toBe(true);
    expect(screen.queryByText(/管理方式和分配策略会保留/)).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: '确认保存' }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/ipam/pools/pool-1' && init?.method === 'PUT')).toBe(true));
    const [, init] = fetchMock.mock.calls.find(([url, request]) => String(url) === '/api/ipam/pools/pool-1' && request?.method === 'PUT')!;
    expect(JSON.parse(String(init?.body))).toMatchObject({
      status: 'active',
      management_mode: 'local_static',
      allocation_allowed: true,
      expected_revision: 7,
    });
  });

  it('requires an explicit management mode before creating a pool', async () => {
    const fetchMock = setup();
    await openCreateForm();
    fillRequiredFields();

    fireEvent.click(screen.getByRole('button', { name: '确认保存' }));

    expect(await screen.findByText('请选择地址池管理方式')).toBeTruthy();
    expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/ipam/pools' && init?.method === 'POST')).toBe(false);
  });

  it('keeps utilization independent from allocation and disables allocation for external pools', async () => {
    setup();
    await openCreateForm();

    const modeSelect = screen.getByLabelText('管理方式 *');
    const allocation = screen.getByLabelText('允许本地静态分配') as HTMLInputElement;
    const utilized = screen.getByLabelText('利用率按整个地址范围计入') as HTMLInputElement;

    fireEvent.change(modeSelect, { target: { value: 'local_static' } });
    fireEvent.click(utilized);
    expect(utilized.checked).toBe(true);
    expect(allocation.checked).toBe(false);

    fireEvent.click(allocation);
    expect(allocation.checked).toBe(true);

    fireEvent.change(modeSelect, { target: { value: 'external_dhcp' } });
    expect(allocation.checked).toBe(false);
    expect(allocation.disabled).toBe(true);
  });

  it('sends the independent policy fields when creating a local static pool', async () => {
    const fetchMock = setup();
    await openCreateForm();
    fillRequiredFields();
    fireEvent.change(screen.getByLabelText('管理方式 *'), { target: { value: 'local_static' } });
    fireEvent.click(screen.getByLabelText('允许本地静态分配'));
    fireEvent.click(screen.getByLabelText('禁止在范围内创建单个 IP 地址'));
    fireEvent.click(screen.getByLabelText('利用率按整个地址范围计入'));

    fireEvent.click(screen.getByRole('button', { name: '确认保存' }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/ipam/pools' && init?.method === 'POST')).toBe(true));
    const [, init] = fetchMock.mock.calls.find(([url, request]) => String(url) === '/api/ipam/pools' && request?.method === 'POST')!;
    const payload = JSON.parse(String(init?.body));
    expect(payload).toMatchObject({
      management_mode: 'local_static',
      allocation_allowed: true,
      mark_populated: true,
      mark_utilized: true,
    });
    expect(new Headers(init?.headers).get('Idempotency-Key')).toBeTruthy();
    expect(payload).not.toHaveProperty('tenant_id');
    expect(payload).not.toHaveProperty('address_space_id');
  });

  it('allows an operator to resolve and save policy for an older pending pool', async () => {
    const fetchMock = setup([{
      ...basePool, management_mode: null, allocation_allowed: false,
      mark_populated: false, mark_utilized: false, policy_pending: true,
    }]);
    expect(await screen.findByText('策略未确认，分配受限')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '编辑' }));

    fireEvent.change(await screen.findByLabelText('管理方式 *'), { target: { value: 'local_static' } });
    fireEvent.click(screen.getByLabelText('允许本地静态分配'));
    fireEvent.click(screen.getByLabelText('利用率按整个地址范围计入'));
    fireEvent.click(screen.getByRole('button', { name: '确认保存' }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/ipam/pools/pool-1' && init?.method === 'PUT')).toBe(true));
    const [, init] = fetchMock.mock.calls.find(([url, request]) => String(url) === '/api/ipam/pools/pool-1' && request?.method === 'PUT')!;
    expect(JSON.parse(String(init?.body))).toMatchObject({
      management_mode: 'local_static',
      allocation_allowed: true,
      mark_populated: false,
      mark_utilized: true,
      expected_revision: 7,
    });
  });

  it('sends a stable idempotency key for a pool create retry', async () => {
    const seenKeys: string[] = [];
    let createAttempts = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith('/api/ipam/pools?')) return response({ items: [], total: 0 });
      if (url === '/api/ipam/subnets') return response([prefix]);
      if (url === '/api/ipam/pools' && init?.method === 'POST') {
        seenKeys.push(new Headers(init.headers).get('Idempotency-Key') || '');
        createAttempts += 1;
        return createAttempts === 1
          ? ({ ok: false, status: 503, json: async () => ({ detail: 'temporary failure' }) } as Response)
          : response({ id: 'pool-new' });
      }
      return response({});
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<IPPoolTab language="zh" t={(key) => key} />);
    await openCreateForm();
    fillRequiredFields();
    fireEvent.change(screen.getByLabelText('管理方式 *'), { target: { value: 'local_static' } });

    fireEvent.click(screen.getByRole('button', { name: '确认保存' }));
    expect(await screen.findByText('temporary failure')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '确认保存' }));

    await waitFor(() => expect(seenKeys).toHaveLength(2));
    expect(seenKeys[0]).toBeTruthy();
    expect(seenKeys[1]).toBe(seenKeys[0]);
  });

  it('sends the row revision with pool deletion', async () => {
    const fetchMock = setup([{ ...basePool, management_mode: 'reserved', allocation_allowed: false }]);
    await screen.findByText('RESERVED');
    fireEvent.click(screen.getByRole('button', { name: '删除' }));
    fireEvent.click(await screen.findByRole('button', { name: '确定删除' }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => (
      String(url).startsWith('/api/ipam/pools/pool-1?') && init?.method === 'DELETE'
    ))).toBe(true));
    const [url] = fetchMock.mock.calls.find(([requestUrl, init]) => String(requestUrl).startsWith('/api/ipam/pools/pool-1?') && init?.method === 'DELETE')!;
    expect(new URL(String(url), 'http://localhost').searchParams.get('expected_revision')).toBe('7');
  });
});
