import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import DeviceRoutingContextTab from './DeviceRoutingContextTab';

const response = (payload: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => payload,
  headers: { get: () => null },
}) as unknown as Response;

const device = { id: 'device-1', name: 'SW-01', management_ip: '192.0.2.10' };
const addressSpaces = [
  { id: 'space-vrf', name: 'Corporate', kind: 'vrf', vrf_id: 'vrf-corp', vrf_name: 'CORP' },
  { id: 'space-global', name: 'Default', kind: 'global', vrf_id: null, vrf_name: null },
];
const mapping = {
  id: 'mapping-1',
  device_id: device.id,
  device_name: device.name,
  context_source: 'cli' as const,
  context_type: 'vrf' as const,
  local_context_key: 'CORP',
  local_context_name: 'Corporate VRF',
  address_space_id: 'space-vrf',
  address_space_name: 'Corporate',
  address_space_kind: 'vrf' as const,
  vrf_id: 'vrf-corp',
  status: 'active' as const,
  revision: 7,
  last_verified_at: null,
  created_at: '2026-11-06T08:00:00Z',
  updated_at: '2026-11-06T08:00:00Z',
};

const setup = (options: {
  mappings?: typeof mapping[];
  onRequest?: (url: string, init?: RequestInit) => Response | Promise<Response> | undefined;
} = {}) => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const customResponse = await options.onRequest?.(url, init);
    if (customResponse) return customResponse;
    if (url === '/api/devices?mode=light') return response([device]);
    if (url === '/api/ipam/address-spaces') return response({ items: addressSpaces });
    if (url.startsWith('/api/ipam/routing-contexts?')) return response({ items: options.mappings ?? [] });
    if (url === '/api/ipam/routing-contexts' && init?.method === 'POST') return response({ ...mapping, id: 'mapping-new' });
    if (url === '/api/ipam/routing-contexts/mapping-1' && init?.method === 'PUT') return response({ ...mapping, revision: 8 });
    return response({});
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<DeviceRoutingContextTab language="zh" t={(key) => key} />);
  return fetchMock;
};

const selectDevice = async (query = device.name) => {
  const input = await screen.findByRole('combobox', { name: '选择设备' });
  await waitFor(() => expect((input as HTMLInputElement).disabled).toBe(false));
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: query } });
  fireEvent.click(await screen.findByRole('option', { name: 'SW-01 · 192.0.2.10' }));
};

describe('DeviceRoutingContextTab', () => {
  beforeEach(() => {
    localStorage.removeItem('netops_token');
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('loads device options, requests mappings only after device selection, and shows the empty state', async () => {
    const fetchMock = setup();
    const deviceInput = await screen.findByRole('combobox', { name: '选择设备' });
    await waitFor(() => expect((deviceInput as HTMLInputElement).disabled).toBe(false));
    fireEvent.focus(deviceInput);
    expect(screen.queryByRole('listbox')).toBeNull();
    expect(fetchMock.mock.calls.some(([url]) => String(url).startsWith('/api/ipam/routing-contexts?'))).toBe(false);

    await selectDevice();

    expect(await screen.findByText('该设备还没有上下文映射')).toBeTruthy();
    expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/ipam/routing-contexts?device_id=device-1')).toBe(true);
  });

  it('rejects unknown local keys and creates a VRF mapping with the explicit compatible address space', async () => {
    const fetchMock = setup();
    await selectDevice();
    fireEvent.click(await screen.findByRole('button', { name: '新增映射' }));
    const dialog = await screen.findByRole('dialog', { name: '新增设备上下文映射' });
    fireEvent.click(within(dialog).getByRole('button', { name: '保存映射' }));
    expect(await within(dialog).findByRole('alert')).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText('本地上下文标识'), { target: { value: 'unknown' } });
    fireEvent.change(within(dialog).getByLabelText('目标地址空间'), { target: { value: 'space-vrf' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '保存映射' }));
    expect(await within(dialog).findByRole('alert')).toBeTruthy();
    expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/ipam/routing-contexts' && init?.method === 'POST')).toBe(false);

    fireEvent.change(within(dialog).getByLabelText('上下文来源'), { target: { value: 'snmp' } });
    fireEvent.change(within(dialog).getByLabelText('本地上下文标识'), { target: { value: 'VRF-CORP' } });
    fireEvent.change(within(dialog).getByLabelText('本地上下文名称'), { target: { value: 'Corporate' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '保存映射' }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/ipam/routing-contexts' && init?.method === 'POST')).toBe(true));
    const [, init] = fetchMock.mock.calls.find(([url, request]) => String(url) === '/api/ipam/routing-contexts' && request?.method === 'POST')!;
    expect(JSON.parse(String(init?.body))).toEqual({
      device_id: 'device-1',
      context_source: 'snmp',
      context_type: 'vrf',
      local_context_key: 'VRF-CORP',
      local_context_name: 'Corporate',
      address_space_id: 'space-vrf',
    });
  });

  it('limits Global contexts to Global address spaces', async () => {
    const fetchMock = setup();
    await selectDevice();
    fireEvent.click(await screen.findByRole('button', { name: '新增映射' }));
    const dialog = await screen.findByRole('dialog', { name: '新增设备上下文映射' });
    fireEvent.change(within(dialog).getByLabelText('上下文类型'), { target: { value: 'global' } });

    const addressSpaceSelect = within(dialog).getByLabelText('目标地址空间');
    expect(within(addressSpaceSelect).getByRole('option', { name: 'Default · 全局' })).toBeTruthy();
    expect(within(addressSpaceSelect).queryByRole('option', { name: 'Corporate · CORP' })).toBeNull();
    fireEvent.change(within(dialog).getByLabelText('本地上下文标识'), { target: { value: 'global' } });
    fireEvent.change(addressSpaceSelect, { target: { value: 'space-global' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '保存映射' }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/ipam/routing-contexts' && init?.method === 'POST')).toBe(true));
    const [, init] = fetchMock.mock.calls.find(([url, request]) => String(url) === '/api/ipam/routing-contexts' && request?.method === 'POST')!;
    expect(JSON.parse(String(init?.body))).toMatchObject({
      context_type: 'global',
      local_context_key: 'global',
      local_context_name: '',
      address_space_id: 'space-global',
    });
  });

  it('updates using the displayed revision and surfaces a revision conflict', async () => {
    const fetchMock = setup({
      mappings: [mapping],
      onRequest: (url, init) => url === '/api/ipam/routing-contexts/mapping-1' && init?.method === 'PUT'
        ? response({ detail: 'Mapping revision is stale.' }, 409)
        : undefined,
    });
    await selectDevice();
    expect(await screen.findByText('7')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '编辑' }));
    const dialog = await screen.findByRole('dialog', { name: '编辑设备上下文映射' });
    fireEvent.change(within(dialog).getByLabelText('本地上下文名称'), { target: { value: 'Corporate updated' } });
    fireEvent.change(within(dialog).getByLabelText('映射状态'), { target: { value: 'disabled' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '保存映射' }));

    expect(await within(dialog).findByText(/版本冲突/)).toBeTruthy();
    const [, init] = fetchMock.mock.calls.find(([url, request]) => String(url) === '/api/ipam/routing-contexts/mapping-1' && request?.method === 'PUT')!;
    expect(JSON.parse(String(init?.body))).toEqual({
      expected_revision: 7,
      address_space_id: 'space-vrf',
      local_context_name: 'Corporate updated',
      status: 'disabled',
    });
    expect(fetchMock.mock.calls.filter(([url]) => String(url).startsWith('/api/ipam/routing-contexts?device_id=')).length).toBeGreaterThan(1);
  });

  it('confirms deactivation and updates status without deleting the record', async () => {
    const fetchMock = setup({ mappings: [mapping] });
    await selectDevice();
    await screen.findByText('Corporate VRF');
    fireEvent.click(screen.getByRole('button', { name: '停用' }));
    const dialog = await screen.findByRole('alertdialog', { name: '确认停用映射？' });
    fireEvent.click(within(dialog).getByRole('button', { name: '确认停用' }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/ipam/routing-contexts/mapping-1' && init?.method === 'PUT')).toBe(true));
    const [, init] = fetchMock.mock.calls.find(([url, request]) => String(url) === '/api/ipam/routing-contexts/mapping-1' && request?.method === 'PUT')!;
    expect(JSON.parse(String(init?.body))).toEqual({
      expected_revision: 7,
      address_space_id: 'space-vrf',
      local_context_name: 'Corporate VRF',
      status: 'disabled',
    });
    expect(fetchMock.mock.calls.some(([url, request]) => String(url) === '/api/ipam/routing-contexts/mapping-1' && request?.method === 'DELETE')).toBe(false);
  });

  it('shows a permission error and prevents writes when mapping access is denied', async () => {
    setup({
      onRequest: (url) => url.startsWith('/api/ipam/routing-contexts?')
        ? response({ detail: 'forbidden' }, 403)
        : undefined,
    });
    await selectDevice();

    expect(await screen.findByText('当前账号没有查看设备上下文映射的权限。')).toBeTruthy();
    expect((screen.getByRole('button', { name: '新增映射' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('shows mapping load errors and allows retry', async () => {
    let failFirstRequest = true;
    const fetchMock = setup({
      onRequest: (url) => {
        if (url.startsWith('/api/ipam/routing-contexts?') && failFirstRequest) {
          failFirstRequest = false;
          return response({ detail: 'Temporary mapping service error.' }, 503);
        }
        if (url.startsWith('/api/ipam/routing-contexts?')) return response({ items: [] });
        return undefined;
      },
    });
    await selectDevice();
    expect(await screen.findByText('Temporary mapping service error.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    expect(await screen.findByText('该设备还没有上下文映射')).toBeTruthy();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).startsWith('/api/ipam/routing-contexts?device_id=')).length).toBeGreaterThan(1);
  });

  it('lists discovered routing context candidates and confirms ownership without manual key entry', async () => {
    const fetchMock = setup({
      onRequest: (url) => {
        if (url === '/api/ipam/routing-contexts/candidates?device_id=device-1') {
          return response({
            items: [
              {
                device_id: 'device-1',
                device_name: 'SW-01',
                context_source: 'cli',
                context_type: 'vrf',
                local_context_key: 'CORP-VRF',
                local_context_name: 'CORP-VRF',
                sources: ['arp', 'interface_inventory'],
                observation_count: 12,
                last_observed_at: '2026-11-19T10:00:00Z',
                coverage_status: 'complete',
                can_confirm: true,
                mapping_status: 'pending',
                mapping_id: null,
                mapping_revision: null,
                address_space_id: null,
                address_space_name: null,
                address_space_kind: null,
              },
              {
                device_id: 'device-1',
                device_name: 'SW-01',
                context_source: 'snmp',
                context_type: 'unknown',
                local_context_key: '',
                local_context_name: '',
                sources: ['arp'],
                observation_count: 3,
                last_observed_at: '2026-11-19T10:00:00Z',
                coverage_status: 'scope_unknown',
                can_confirm: false,
                mapping_status: 'unknown_context',
                mapping_id: null,
                mapping_revision: null,
                address_space_id: null,
                address_space_name: null,
                address_space_kind: null,
              },
            ],
          });
        }
        return undefined;
      },
    });
    await selectDevice();

    const candidateSection = await screen.findByRole('region', { name: '已采集路由上下文候选' });
    expect(within(candidateSection).getAllByText('CORP-VRF').length).toBeGreaterThan(0);
    expect(within(candidateSection).getByText('缺少可靠上下文（待确认）')).toBeTruthy();

    fireEvent.change(within(candidateSection).getByLabelText('目标地址空间 CORP-VRF'), { target: { value: 'space-vrf' } });
    fireEvent.click(within(candidateSection).getByRole('button', { name: '确认归属' }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/ipam/routing-contexts' && init?.method === 'POST')).toBe(true);
    });
    const [, init] = fetchMock.mock.calls.find(([url, request]) => String(url) === '/api/ipam/routing-contexts' && request?.method === 'POST')!;
    expect(JSON.parse(String(init?.body))).toEqual({
      device_id: 'device-1',
      context_source: 'cli',
      context_type: 'vrf',
      local_context_key: 'CORP-VRF',
      local_context_name: 'CORP-VRF',
      address_space_id: 'space-vrf',
    });
  });
});
