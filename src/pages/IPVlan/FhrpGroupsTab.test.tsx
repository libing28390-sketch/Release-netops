import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import FhrpGroupsTab from './FhrpGroupsTab';

const response = (payload: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => payload,
  headers: { get: () => null },
}) as unknown as Response;

const space = {
  id: 'space-global', name: 'Global', kind: 'global', vrf_id: null,
  vrf_name: null, status: 'active',
};
const groupSummary = {
  id: 'group-1', security_tenant_id: 'tenant-default', address_space_id: space.id,
  address_space_name: space.name, group_type: 'fhrp' as const, protocol: 'vrrp' as const,
  group_id: '17', address_family: 4 as const, display_name: '', status: 'active' as const,
  revision: 4, created_at: '2026-11-09T00:00:00Z', updated_at: '2026-11-09T00:00:00Z',
};
const groupDetail = {
  ...groupSummary,
  members: [],
  vips: [],
};
const device = { id: 'device-1', hostname: 'R1', ip_address: '192.0.2.1' };
const vip = {
  id: 'vip-1', address: '192.0.2.254', vip_type: 'vrrp', status: 'active',
  prefix_id: 'prefix-1', address_space_id: space.id, address_space_name: space.name,
};

const setup = (onRequest?: (url: string, init?: RequestInit) => Response | undefined) => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const custom = onRequest?.(url, init);
    if (custom) return custom;
    if (url === '/api/ipam/address-spaces') return response({ items: [space] });
    if (url === '/api/devices?mode=light') return response([device]);
    if (url.startsWith('/api/ipam/fhrp/groups?')) {
      return response({ items: [groupSummary], total: 1, page: 1, page_size: 20, total_pages: 1 });
    }
    if (url === '/api/ipam/fhrp/groups/group-1') return response(groupDetail);
    if (url === '/api/ipam/fhrp/groups/group-1/current') {
      return response({
        items: [{
          id: 'observation-1', source_device_id: device.id, source_device_name: device.hostname,
          protocol: 'vrrp', group_id: 17, address_family: 4, interface_name: 'Vlan10',
          priority: 110, state: 'master', master_address: '192.0.2.1',
          virtual_ip: '192.0.2.254', virtual_mac: '00:00:5e:00:01:11',
          address_space_id: space.id, address_space_name: space.name,
          scope_status: 'resolved', group_scope_status: 'resolved', coverage_complete: true,
          collection_status: 'complete', observed_at: '2026-11-09T00:00:00Z',
          last_success_at: '2026-11-09T00:00:00Z',
        }],
        collection_states: [{
          device_id: device.id, device_name: device.hostname, protocol: 'vrrp',
          latest_attempt_generation: 2, latest_status: 'complete',
          last_attempt_at: '2026-11-09T00:00:00Z', last_completed_at: '2026-11-09T00:00:00Z',
          last_success_generation: 2, last_success_at: '2026-11-09T00:00:00Z',
          current_row_count: 1, last_error_code: '',
        }],
      });
    }
    if (url === '/api/ipam/fhrp/groups' && init?.method === 'POST') return response({ ...groupDetail, id: 'group-new', group_id: '33', revision: 1 }, 201);
    if (url === '/api/ipam/fhrp/groups/group-1/members' && init?.method === 'POST') {
      return response({ id: 'member-1', group_id: 'group-1', device_id: device.id, device_name: device.hostname, interface_id: null, interface_name: 'GigabitEthernet0/1', normalized_interface_name: 'gi0/1', role: 'master', priority: 110, status: 'active', revision: 1, created_at: '2026-11-09T00:00:00Z', updated_at: '2026-11-09T00:00:00Z', group_revision: 5 }, 201);
    }
    if (url.startsWith('/api/ipam/vips?')) return response({ items: [vip], total: 1, page: 1, page_size: 100, total_pages: 1 });
    if (url === '/api/ipam/fhrp/groups/group-1/vips' && init?.method === 'POST') {
      return response({ id: 'link-1', group_id: 'group-1', vip_id: 'vip-1', address: vip.address, vip_type: 'vrrp', group_revision: 5 }, 201);
    }
    return response({});
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<FhrpGroupsTab language="zh" t={(key) => key} />);
  return fetchMock;
};

const openGroupDetail = async () => {
  fireEvent.click(await screen.findByRole('button', { name: /VRRP 17/ }));
  await screen.findByRole('heading', { name: 'VRRP 17' });
};

describe('FhrpGroupsTab', () => {
  beforeEach(() => localStorage.removeItem('netops_token'));
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('loads only a server-paged group summary and fetches relationships when the row is opened', async () => {
    const fetchMock = setup();
    expect(await screen.findByText('Global')).toBeTruthy();
    expect(await screen.findByText('17')).toBeTruthy();
    expect(fetchMock.mock.calls.some(([url]) => String(url).startsWith('/api/ipam/fhrp/groups?'))).toBe(true);
    expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/ipam/fhrp/groups/group-1')).toBe(false);

    await openGroupDetail();

    expect(await screen.findByText('当前账号可见范围内没有成员。')).toBeTruthy();
    expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/ipam/fhrp/groups/group-1')).toBe(true);
    expect(await screen.findByText('192.0.2.254')).toBeTruthy();
    expect(screen.getByText('master')).toBeTruthy();
  });

  it.each([
    ['ssh_banner_unavailable', 'SSH 协议 Banner 未收到：设备在执行查询命令前关闭了连接。'],
    ['ssh_algorithm_mismatch', 'SSH 算法协商失败：检查双方支持的密钥交换、主机密钥和加密算法。'],
  ])('shows the FHRP collection failure reason for %s instead of a verified-empty result', async (errorCode, errorLabel) => {
    const attemptedAt = '2026-11-11T03:29:54Z';
    setup((url) => url === '/api/ipam/fhrp/groups/group-1/current'
      ? response({
        items: [],
        collection_states: [{
          device_id: device.id, device_name: device.hostname, protocol: 'vrrp',
          latest_attempt_generation: 3, latest_status: 'failed',
          last_attempt_at: attemptedAt, last_completed_at: attemptedAt,
          last_success_generation: 0, last_success_at: '',
          current_row_count: 0, last_error_code: errorCode,
        }],
      })
      : undefined);

    await openGroupDetail();

    expect(await screen.findByText(errorLabel)).toBeTruthy();
    expect(screen.getByText('采集失败')).toBeTruthy();
    expect(screen.getByText(errorCode)).toBeTruthy();
    expect(screen.getByText(/最近尝试/)).toBeTruthy();
    expect(screen.queryByText('最新完整采集未发现该组的运行观察。')).toBeNull();
    expect(await screen.findByText('尚无可用的当前采集观察；等待下一次采集或检查设备覆盖状态。')).toBeTruthy();
  });

  it('shows current FHRP coverage and the last successful observation time', async () => {
    const lastSuccessAt = '2026-11-09T00:00:00Z';
    const fetchMock = setup((url) => url === '/api/ipam/fhrp/groups/group-1/current'
      ? response({
        items: [{
          id: 'observation-partial', source_device_id: device.id, source_device_name: device.hostname,
          protocol: 'vrrp', group_id: 17, address_family: 4, interface_name: 'Vlan10',
          priority: 110, state: 'master', master_address: '192.0.2.1',
          virtual_ip: '192.0.2.254', virtual_mac: '00:00:5e:00:01:11',
          address_space_id: space.id, address_space_name: space.name,
          scope_status: 'resolved', group_scope_status: 'resolved', coverage_complete: false,
          collection_status: 'partial', observed_at: lastSuccessAt, last_success_at: lastSuccessAt,
        }],
        collection_states: [{
          device_id: device.id, device_name: device.hostname, protocol: 'vrrp',
          latest_attempt_generation: 3, latest_status: 'partial',
          last_attempt_at: lastSuccessAt, last_completed_at: lastSuccessAt,
          last_success_generation: 2, last_success_at: lastSuccessAt,
          current_row_count: 1, last_error_code: 'partial_coverage',
        }],
      })
      : undefined);

    await openGroupDetail();
    const currentTable = await waitFor(() => {
      const table = screen.getAllByRole('table').find((candidate) => (
        candidate.textContent?.includes('192.0.2.254')
        && candidate.textContent.includes('最近成功')
      ));
      expect(table).toBeTruthy();
      return table!;
    });
    const observationRow = within(currentTable).getAllByRole('row').find((row) => (
      row.textContent?.includes('192.0.2.254')
    ));

    expect(observationRow?.textContent).toContain('master');
    expect(observationRow?.textContent).toContain('partial');
    expect(observationRow?.textContent).toContain('2026');
    expect(screen.getAllByText(/最近成功/).some((node) => node.textContent?.includes('2026'))).toBe(true);
    expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/ipam/fhrp/groups/group-1/current')).toBe(true);
  });

  it('creates an explicit FHRP group with an idempotency key and selected address space', async () => {
    const fetchMock = setup();
    fireEvent.click(await screen.findByRole('button', { name: '新增组' }));
    const dialog = await screen.findByRole('dialog', { name: '新增 FHRP / Anycast 组' });
    fireEvent.change(within(dialog).getByLabelText('本地组标识'), { target: { value: '33' } });
    fireEvent.change(within(dialog).getByLabelText('显示名称'), { target: { value: 'Edge Gateway' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '保存' }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/ipam/fhrp/groups' && init?.method === 'POST')).toBe(true));
    const [, request] = fetchMock.mock.calls.find(([url, init]) => String(url) === '/api/ipam/fhrp/groups' && init?.method === 'POST')!;
    expect(JSON.parse(String(request?.body))).toEqual({
      address_space_id: space.id,
      group_type: 'fhrp',
      protocol: 'vrrp',
      group_id: '33',
      address_family: 4,
      display_name: 'Edge Gateway',
      status: 'active',
    });
    expect(new Headers(request?.headers).get('Idempotency-Key')).toBeTruthy();
    expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/ipam/vips' && init?.method === 'POST')).toBe(false);
  });

  it('adds a device interface as an explicit group member using the current revision', async () => {
    const fetchMock = setup();
    await openGroupDetail();
    fireEvent.click(screen.getByRole('button', { name: '添加成员' }));
    const dialog = await screen.findByRole('dialog', { name: '添加组成员' });
    fireEvent.change(await within(dialog).findByLabelText('设备'), { target: { value: device.id } });
    fireEvent.change(within(dialog).getByRole('textbox', { name: /接口名称/ }), { target: { value: 'GigabitEthernet0/1' } });
    fireEvent.change(within(dialog).getByLabelText('角色（可选）'), { target: { value: 'master' } });
    fireEvent.change(within(dialog).getByLabelText('优先级（可选）'), { target: { value: '110' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '添加成员' }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/ipam/fhrp/groups/group-1/members' && init?.method === 'POST')).toBe(true));
    const [, request] = fetchMock.mock.calls.find(([url, init]) => String(url) === '/api/ipam/fhrp/groups/group-1/members' && init?.method === 'POST')!;
    expect(JSON.parse(String(request?.body))).toMatchObject({
      expected_revision: groupDetail.revision,
      device_id: device.id,
      interface_name: 'GigabitEthernet0/1',
      role: 'master',
      priority: 110,
    });
  });

  it('links only a searched existing VIP that matches group space, protocol and family', async () => {
    const fetchMock = setup();
    await openGroupDetail();
    fireEvent.click(screen.getByRole('button', { name: '关联 VIP' }));
    const dialog = await screen.findByRole('dialog', { name: '关联正式 VIP' });
    fireEvent.change(within(dialog).getByLabelText('搜索 VIP 地址或描述'), { target: { value: vip.address } });
    fireEvent.click(within(dialog).getByRole('button', { name: '搜索已有 VIP' }));
    fireEvent.click(await within(dialog).findByRole('button', { name: '关联' }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/ipam/fhrp/groups/group-1/vips' && init?.method === 'POST')).toBe(true));
    const [, request] = fetchMock.mock.calls.find(([url, init]) => String(url) === '/api/ipam/fhrp/groups/group-1/vips' && init?.method === 'POST')!;
    expect(JSON.parse(String(request?.body))).toEqual({ expected_revision: groupDetail.revision, vip_id: vip.id });
    expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/ipam/vips' && init?.method === 'POST')).toBe(false);
  });

  it('keeps the empty state explicit when the account has no address-space scope', async () => {
    const fetchMock = setup((url) => url === '/api/ipam/address-spaces' ? response({ items: [] }) : undefined);
    expect(await screen.findByText('还没有可用地址空间')).toBeTruthy();
    expect((screen.getByRole('button', { name: '新增组' }) as HTMLButtonElement).disabled).toBe(true);
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).startsWith('/api/ipam/fhrp/groups?'))).toBe(true));
  });

  it('keeps the create form open and explains a permission denial', async () => {
    setup((url, init) => url === '/api/ipam/fhrp/groups' && init?.method === 'POST'
      ? response({ detail: 'forbidden' }, 403)
      : undefined);
    fireEvent.click(await screen.findByRole('button', { name: '新增组' }));
    const dialog = await screen.findByRole('dialog', { name: '新增 FHRP / Anycast 组' });
    fireEvent.change(within(dialog).getByLabelText('本地组标识'), { target: { value: '44' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '保存' }));

    expect(await within(dialog).findByRole('alert')).toBeTruthy();
    expect(within(dialog).getByRole('alert').textContent).toContain('当前账号没有执行此操作的权限');
  });
});
