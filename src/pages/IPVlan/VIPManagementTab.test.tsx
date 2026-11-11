import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import VIPManagementTab from './VIPManagementTab';

const response = (payload: unknown, status = 200, ok = true) => ({
  ok,
  status,
  json: async () => payload,
}) as Response;

const prefix = { id: 'prefix-1', prefix: '10.0.0.0/24', name: 'Office' };

const baseVip = {
  id: 'vip-1', revision: 11, address: '10.0.0.10', vip_type: 'VRRP', device_id: null,
  device_name: null, backup_device_id: null, backup_device_name: null,
  interface_name: '', description: '', real_servers: '', status: 'reserved',
  prefix_id: null, prefix_cidr: null, address_space_id: null,
  address_space_name: null, scope_pending: true, tenant_name: null,
};

const setup = (
  vips: Record<string, unknown>[] = [baseVip],
  createResponse: Response = response({ id: 'vip-new' }),
) => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.startsWith('/api/ipam/vips?')) return response({ items: vips, total: vips.length });
    if (url.startsWith('/api/ipam/subnets?')) return response({ items: [prefix], total: 1 });
    if (url === '/api/devices?mode=light') return response([]);
    if (url === '/api/ipam/vips' && init?.method === 'POST') return createResponse;
    if (url.startsWith('/api/ipam/vips/') && init?.method === 'PUT') return response({ ok: true });
    return response({});
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<VIPManagementTab language="zh" t={(key) => key} />);
  return fetchMock;
};

const openCreate = async () => {
  fireEvent.click(await screen.findByRole('button', { name: '新增虚拟 IP' }));
  await screen.findByRole('heading', { name: '新增虚拟 IP' });
};

const fillVipAddress = () => {
  fireEvent.change(screen.getByLabelText('虚拟 IP 地址 (VIP) *'), { target: { value: '10.0.0.20' } });
};

describe('VIPManagementTab address scope', () => {
  beforeEach(() => {
    localStorage.removeItem('netops_token');
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('uses a warning tone for reserved VIP records', async () => {
    setup([{ ...baseVip, status: 'reserved' }]);
    const badge = (await screen.findByText('RESERVED')).closest('span');
    expect(badge?.className).toContain('bg-amber-50');
    expect(badge?.className).not.toContain('bg-emerald-50');
  });

  it('shows legacy VIPs without a verified Prefix as scope pending', async () => {
    setup([baseVip]);

    expect(await screen.findAllByText('范围待确认')).toHaveLength(1);
  });

  it('requires an explicit Prefix and never sends tenant or address-space overrides', async () => {
    const fetchMock = setup([]);
    await openCreate();
    fillVipAddress();

    fireEvent.click(screen.getByRole('button', { name: '确认保存' }));
    expect(await screen.findAllByText('请选择明确的归属前缀')).not.toHaveLength(0);
    expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/ipam/vips' && init?.method === 'POST')).toBe(false);

    fireEvent.change(screen.getByLabelText('归属前缀'), { target: { value: prefix.id } });
    fireEvent.click(screen.getByRole('button', { name: '确认保存' }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/ipam/vips' && init?.method === 'POST')).toBe(true));
    const [, init] = fetchMock.mock.calls.find(([url, request]) => String(url) === '/api/ipam/vips' && request?.method === 'POST')!;
    const payload = JSON.parse(String(init?.body));
    expect(payload).toMatchObject({ prefix_id: 'prefix-1', address: '10.0.0.20' });
    expect(new Headers(init?.headers).get('Idempotency-Key')).toBeTruthy();
    expect(payload).not.toHaveProperty('tenant_id');
    expect(payload).not.toHaveProperty('address_space_id');
  });

  it('allows an explicitly scoped Anycast VIP to be registered for a shared group', async () => {
    const fetchMock = setup([]);
    await openCreate();
    fillVipAddress();
    fireEvent.change(screen.getByLabelText('高可用技术模式 *'), { target: { value: 'anycast' } });
    fireEvent.change(screen.getByLabelText('归属前缀'), { target: { value: prefix.id } });
    fireEvent.click(screen.getByRole('button', { name: '确认保存' }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/ipam/vips' && init?.method === 'POST')).toBe(true));
    const [, init] = fetchMock.mock.calls.find(([url, request]) => String(url) === '/api/ipam/vips' && request?.method === 'POST')!;
    expect(JSON.parse(String(init?.body))).toMatchObject({
      prefix_id: prefix.id,
      address: '10.0.0.20',
      vip_type: 'anycast',
    });
  });

  it.each([
    { label: 'Anycast', vipType: 'anycast' },
    { label: 'VRRP', vipType: 'VRRP' },
  ])('shows the allocated-IP conflict for $label without submitting a duplicate create', async ({ vipType }) => {
    const detail = 'VIP 10.0.0.20 conflicts with an allocated IP in this address space';
    const fetchMock = setup([], response({ detail }, 409, false));
    await openCreate();
    fillVipAddress();
    fireEvent.change(screen.getByLabelText('高可用技术模式 *'), { target: { value: vipType } });
    fireEvent.change(screen.getByLabelText('归属前缀'), { target: { value: prefix.id } });
    fireEvent.click(screen.getByRole('button', { name: '确认保存' }));

    expect(await screen.findByText(detail)).toBeTruthy();
    expect(screen.getByRole('heading', { name: '新增虚拟 IP' })).toBeTruthy();
    const createCalls = fetchMock.mock.calls.filter(([url, init]) => (
      String(url) === '/api/ipam/vips' && init?.method === 'POST'
    ));
    expect(createCalls).toHaveLength(1);
    const [, request] = createCalls[0];
    expect(JSON.parse(String(request?.body))).toMatchObject({
      prefix_id: prefix.id,
      address: '10.0.0.20',
      vip_type: vipType,
    });
    expect(new Headers(request?.headers).get('Idempotency-Key')).toBeTruthy();
  });

  it('lets an operator resolve a legacy VIP by explicitly selecting a Prefix', async () => {
    const fetchMock = setup([baseVip]);
    expect(await screen.findAllByText('范围待确认')).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: '编辑' }));
    expect(await screen.findByText(/此 VIP 尚未确认地址空间/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('归属前缀'), { target: { value: 'prefix-1' } });
    fireEvent.click(screen.getByRole('button', { name: '确认保存' }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/ipam/vips/vip-1' && init?.method === 'PUT')).toBe(true));
    const [, init] = fetchMock.mock.calls.find(([url, request]) => String(url) === '/api/ipam/vips/vip-1' && request?.method === 'PUT')!;
    expect(JSON.parse(String(init?.body))).toMatchObject({ prefix_id: 'prefix-1', expected_revision: 11 });
    expect(JSON.parse(String(init?.body))).not.toHaveProperty('tenant_id');
    expect(JSON.parse(String(init?.body))).not.toHaveProperty('address_space_id');
  });

  it('does not allow a new VIP when the Prefix list permission check fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/ipam/vips?')) return response({ items: [], total: 0 });
      if (url.startsWith('/api/ipam/subnets?')) return response({ detail: 'denied' }, 403, false);
      if (url === '/api/devices?mode=light') return response([]);
      return response({});
    }));
    render(<VIPManagementTab language="zh" t={(key) => key} />);
    await openCreate();
    fillVipAddress();
    expect(await screen.findByText('当前账号没有查看可用网段的权限。')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '确认保存' }));
    expect(await screen.findAllByText('请选择明确的归属前缀')).not.toHaveLength(0);
  });

  it('sends the current revision when deleting a VIP', async () => {
    const fetchMock = setup([baseVip]);
    await screen.findByText('10.0.0.10');
    fireEvent.click(screen.getByRole('button', { name: '删除' }));
    fireEvent.click(await screen.findByRole('button', { name: '确定删除' }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => (
      String(url).startsWith('/api/ipam/vips/vip-1?') && init?.method === 'DELETE'
    ))).toBe(true));
    const [url] = fetchMock.mock.calls.find(([requestUrl, init]) => String(requestUrl).startsWith('/api/ipam/vips/vip-1?') && init?.method === 'DELETE')!;
    expect(new URL(String(url), 'http://localhost').searchParams.get('expected_revision')).toBe('11');
  });
});
