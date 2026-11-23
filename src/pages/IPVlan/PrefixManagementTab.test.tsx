import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import PrefixManagementTab from './PrefixManagementTab';

const response = (payload: unknown) => ({ ok: true, status: 200, json: async () => payload }) as Response;
const failure = (status: number, payload: unknown) => ({ ok: false, status, json: async () => payload }) as Response;

type TestInterfaceCandidate = {
  candidate_id: string;
  prefix: string;
  tenant_id?: string;
  vrf_id?: string | null;
  address_space_id?: string | null;
  status?: string;
  interfaces?: Array<{ device_name?: string; interface_name?: string; address?: string }>;
};

type TestAddressSpace = {
  id: string;
  kind: string;
  vrf_id?: string | null;
  security_tenant_id?: string;
};

function makeInterfaceImportPreview(
  request: { candidate_ids: string[]; address_space_overrides?: Record<string, string> },
  candidates: TestInterfaceCandidate[],
  addressSpaces: TestAddressSpace[] = [],
) {
  const grouped = new Map<string, {
    group_id: string;
    candidate_ids: string[];
    prefix: string;
    address_space_id: string | null;
    status: 'to_create' | 'existing' | 'scope_pending';
    source_count: number;
    interface_count: number;
    ip_count: number;
    interfaces: Array<{ device_name: string; interface_name: string; address: string }>;
  }>();
  for (const candidateId of request.candidate_ids) {
    const candidate = candidates.find((item) => item.candidate_id === candidateId);
    if (!candidate) continue;
    const vrfSpace = candidate.vrf_id
      ? addressSpaces.find((space) => space.kind === 'vrf'
        && space.vrf_id === candidate.vrf_id
        && (!candidate.tenant_id || space.security_tenant_id === candidate.tenant_id))
      : undefined;
    const addressSpaceId = request.address_space_overrides?.[candidateId]
      || candidate.address_space_id
      || vrfSpace?.id
      || null;
    const groupKey = `${addressSpaceId || 'pending'}:${candidate.prefix}`;
    let group = grouped.get(groupKey);
    if (!group) {
      group = {
        group_id: groupKey,
        candidate_ids: [],
        prefix: candidate.prefix,
        address_space_id: addressSpaceId,
        status: addressSpaceId ? 'to_create' : 'scope_pending',
        source_count: 0,
        interface_count: 0,
        ip_count: 0,
        interfaces: [],
      };
      grouped.set(groupKey, group);
    }
    group.candidate_ids.push(candidateId);
    group.source_count += 1;
    const sourceInterfaces = candidate.interfaces || [];
    group.interfaces.push(...sourceInterfaces.map((source) => ({
      device_name: source.device_name || '',
      interface_name: source.interface_name || '',
      address: source.address || '',
    })));
  }
  const groups = Array.from(grouped.values()).map((group) => {
    group.interface_count = group.interfaces.length;
    group.ip_count = new Set(group.interfaces.map((item) => item.address).filter(Boolean)).size;
    return group;
  });
  const newGroups = groups.filter((group) => group.status === 'to_create');
  const existingGroups = groups.filter((group) => group.status === 'existing');
  const pendingGroups = groups.filter((group) => group.status === 'scope_pending');
  const ipCount = new Set(groups.flatMap((group) => group.interfaces.map((item) => item.address)).filter(Boolean)).size;
  return {
    selected_candidate_count: request.candidate_ids.length,
    prefix_count: groups.length,
    new_prefix_count: newGroups.length,
    existing_prefix_count: existingGroups.length,
    pending_candidate_count: pendingGroups.length,
    interface_count: groups.reduce((total, group) => total + group.interface_count, 0),
    ip_count: ipCount,
    new_address_count: ipCount,
    existing_address_count: 0,
    can_generate: pendingGroups.length === 0,
    blockers: pendingGroups.length > 0 ? ['请确认网络归属'] : [],
    groups,
  };
}

async function confirmInterfaceImport() {
  const dialog = await screen.findByRole('dialog', { name: '核对导入结果' });
  const confirm = await within(dialog).findByRole('button', { name: '确认导入' });
  await waitFor(() => expect((confirm as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(confirm);
}

const openMoreActionsForPrefix = async (prefix: string) => {
  const prefixLink = await screen.findByText(prefix);
  const row = prefixLink.closest('tr');
  if (!row) throw new Error(`Could not find table row for ${prefix}`);
  fireEvent.click(within(row).getByRole('button', { name: /^管理 / }));
  return row;
};

describe('PrefixManagementTab creation defaults', () => {
  beforeEach(() => {
    localStorage.removeItem('netops_token');
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/ipam/subnets?')) return response({ items: [], total: 0 });
      if (url.startsWith('/api/ipam/prefixes/classification-summary?')) return response({
        total: 0, auto_count: 0, manual_count: 0, unclassified_count: 0,
        mixed_count: 0, conflict_count: 0, reuse_count: 0, stale_count: 0,
      });
      if (url === '/api/cmdb/sites' || url === '/api/cmdb/vrfs' || url === '/api/cmdb/vlans' || url === '/api/devices?mode=light') {
        return response([]);
      }
      if (url === '/api/ipam/address-spaces') return response({ items: [] });
      return response([]);
    }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  const openGatewayCandidateForm = async (
    candidateResponse: unknown,
    manualDeviceId?: string,
  ) => {
    const candidateRequests: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/cmdb/sites') return response([{ id: 'site-1', site_name: 'Campus A', site_code: 'A' }]);
      if (url === '/api/ipam/address-spaces') return response({ items: [{
        id: 'space-vrf-prod', name: 'Production', kind: 'vrf', vrf_id: 'vrf-prod', vrf_name: 'PROD',
        security_tenant_id: 'tenant-default', status: 'active', revision: 1,
      }] });
      if (url === '/api/cmdb/vlans') return response([]);
      if (url === '/api/devices?mode=light') return response([
        { id: 'manual-device', hostname: 'Manual Gateway', ip_address: '192.0.2.1' },
        { id: 'candidate-device-a', hostname: 'Candidate Gateway A', ip_address: '192.0.2.2' },
        { id: 'candidate-device-b', hostname: 'Candidate Gateway B', ip_address: '192.0.2.3' },
      ]);
      if (url.startsWith('/api/ipam/prefixes/gateway-candidates?')) {
        candidateRequests.push(url);
        return response(candidateResponse);
      }
      if (url.startsWith('/api/ipam/subnets?')) return response({ items: [], total: 0 });
      if (url.startsWith('/api/ipam/prefixes/classification-summary?')) return response({
        total: 0, auto_count: 0, manual_count: 0, unclassified_count: 0,
        mixed_count: 0, conflict_count: 0, reuse_count: 0, stale_count: 0,
      });
      return response([]);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<MemoryRouter><PrefixManagementTab language="zh" t={(key) => key} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: '新增网段' }));
    const dialog = await screen.findByRole('dialog', { name: '新增网段' });
    fireEvent.change(within(dialog).getByRole('combobox', { name: '所属地址空间' }), { target: { value: 'space-vrf-prod' } });
    fireEvent.change(within(dialog).getByPlaceholderText('e.g. 10.1.1.0/24'), { target: { value: '10.1.1.0/24' } });
    fireEvent.change(within(dialog).getByPlaceholderText('e.g. 10.1.1.1'), { target: { value: '10.1.1.1' } });
    const siteSelect = within(dialog).getByRole('option', { name: 'Campus A (A)' }).closest('select')!;
    fireEvent.change(siteSelect, { target: { value: 'site-1' } });
    if (manualDeviceId) {
      const manualGateway = within(dialog).getByRole('option', { name: 'Manual Gateway (192.0.2.1)' }).closest('select')!;
      fireEvent.change(manualGateway, { target: { value: manualDeviceId } });
    }
    await waitFor(() => expect(candidateRequests.some((url) => (
      new URL(url, 'http://localhost').searchParams.get('gateway_ip') === '10.1.1.1'
    ))).toBe(true), { timeout: 1500 });
    return { dialog, fetchMock };
  };

  it('does not assume a new prefix is a server network', async () => {
    render(<MemoryRouter><PrefixManagementTab language="zh" t={(key) => key} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: '新增网段' }));

    const dialog = await screen.findByRole('dialog', { name: '新增网段' });
    const networkType = Array.from(dialog.querySelectorAll('select')).find((select) =>
      Array.from(select.options).some((option) => option.value === 'unclassified'),
    );
    expect(networkType).toBeTruthy();
    expect((networkType as HTMLSelectElement).value).toBe('unclassified');
    expect(within(dialog).getByText('网络用途 (Role)')).toBeTruthy();
  });

  it('requires an explicit address space and can create a named global space', async () => {
    const requests: Array<{ url: string; body?: Record<string, unknown>; headers?: HeadersInit }> = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = String(init?.method || 'GET').toUpperCase();
      if (url === '/api/ipam/address-spaces' && method === 'POST') {
        const body = JSON.parse(String(init?.body || '{}'));
        requests.push({ url, body });
        return response({
          id: 'space-global-explicit',
          name: body.name,
          kind: 'global',
          vrf_id: null,
          vrf_name: null,
          security_tenant_id: 'tenant-default',
          status: 'active',
          revision: 1,
        });
      }
      if (url === '/api/ipam/address-spaces') return response({ items: [] });
      if (url === '/api/ipam/subnets' && method === 'POST') {
        requests.push({ url, body: JSON.parse(String(init?.body || '{}')), headers: init?.headers });
        return response({ id: 'prefix-explicit-space' });
      }
      if (url.startsWith('/api/ipam/subnets?')) return response({ items: [], total: 0 });
      if (url.startsWith('/api/ipam/prefixes/classification-summary?')) return response({
        total: 0, auto_count: 0, manual_count: 0, unclassified_count: 0,
        mixed_count: 0, conflict_count: 0, reuse_count: 0, stale_count: 0,
      });
      return response([]);
    }));

    render(<MemoryRouter><PrefixManagementTab language="zh" t={(key) => key} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: '新增网段' }));
    const dialog = await screen.findByRole('dialog', { name: '新增网段' });
    expect(within(dialog).getByText('当前没有可选地址空间。创建一个全局空间，或先在 CMDB 中创建 VRF。')).toBeTruthy();

    fireEvent.change(within(dialog).getByRole('textbox', { name: '新全局地址空间名称' }), { target: { value: '园区 B 默认域' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '创建全局空间' }));
    const spaceSelect = within(dialog).getByRole('combobox', { name: '所属地址空间' }) as HTMLSelectElement;
    await screen.findByRole('option', { name: '全局（无 VRF） · 园区 B 默认域' });
    expect(spaceSelect.value).toBe('space-global-explicit');

    fireEvent.change(within(dialog).getByPlaceholderText('e.g. 10.1.1.0/24'), { target: { value: '10.88.50.0/24' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '确定保存' }));
    expect(requests.find((item) => item.url === '/api/ipam/address-spaces')?.body).toMatchObject({
      name: '园区 B 默认域',
      kind: 'global',
    });
    expect(requests.find((item) => item.url === '/api/ipam/subnets')?.body).toMatchObject({
      address_space_id: 'space-global-explicit',
      vrf_id: null,
    });
    expect(new Headers(requests.find((item) => item.url === '/api/ipam/subnets')?.headers).get('Idempotency-Key')).toBeTruthy();
  });

  it('submits the VRF attached to the selected address space', async () => {
    const space = {
      id: 'space-vrf-prod',
      name: 'PROD',
      kind: 'vrf',
      vrf_id: 'vrf-prod',
      vrf_name: 'PROD',
      security_tenant_id: 'tenant-default',
      status: 'active',
      revision: 1,
    };
    let createBody: Record<string, unknown> | null = null;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/ipam/address-spaces') return response({ items: [space] });
      if (url === '/api/ipam/subnets' && init?.method === 'POST') {
        createBody = JSON.parse(String(init.body || '{}'));
        return response({ id: 'prefix-vrf-prod' });
      }
      if (url.startsWith('/api/ipam/subnets?')) return response({ items: [], total: 0 });
      if (url.startsWith('/api/ipam/prefixes/classification-summary?')) return response({
        total: 0, auto_count: 0, manual_count: 0, unclassified_count: 0,
        mixed_count: 0, conflict_count: 0, reuse_count: 0, stale_count: 0,
      });
      return response([]);
    }));

    render(<MemoryRouter><PrefixManagementTab language="zh" t={(key) => key} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: '新增网段' }));
    const dialog = await screen.findByRole('dialog', { name: '新增网段' });
    fireEvent.change(within(dialog).getByRole('combobox', { name: '所属地址空间' }), { target: { value: space.id } });
    fireEvent.change(within(dialog).getByPlaceholderText('e.g. 10.1.1.0/24'), { target: { value: '10.90.0.0/16' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '确定保存' }));

    expect(createBody).toMatchObject({ address_space_id: space.id, vrf_id: 'vrf-prod' });
  });

  it('does not submit a new prefix without a selected address space', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/ipam/address-spaces') return response({ items: [] });
      if (url.startsWith('/api/ipam/subnets?')) return response({ items: [], total: 0 });
      if (url.startsWith('/api/ipam/prefixes/classification-summary?')) return response({
        total: 0, auto_count: 0, manual_count: 0, unclassified_count: 0,
        mixed_count: 0, conflict_count: 0, reuse_count: 0, stale_count: 0,
      });
      return response([]);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<MemoryRouter><PrefixManagementTab language="zh" t={(key) => key} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: '新增网段' }));
    const dialog = await screen.findByRole('dialog', { name: '新增网段' });
    fireEvent.change(within(dialog).getByPlaceholderText('e.g. 10.1.1.0/24'), { target: { value: '10.90.0.0/16' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '确定保存' }));

    expect(within(dialog).getByText('请选择明确的地址空间；不能根据站点或空 VRF 自动推断。')).toBeTruthy();
    expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/ipam/subnets')).toBe(false);
  });

  it('shows address-space loading and empty states without assigning a default', async () => {
    let finishSpaceRequest: ((value: Response) => void) | undefined;
    const spaces = new Promise<Response>((resolve) => { finishSpaceRequest = resolve; });
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/ipam/address-spaces') return spaces;
      if (url.startsWith('/api/ipam/subnets?')) return response({ items: [], total: 0 });
      if (url.startsWith('/api/ipam/prefixes/classification-summary?')) return response({
        total: 0, auto_count: 0, manual_count: 0, unclassified_count: 0,
        mixed_count: 0, conflict_count: 0, reuse_count: 0, stale_count: 0,
      });
      return response([]);
    }));

    render(<MemoryRouter><PrefixManagementTab language="zh" t={(key) => key} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: '新增网段' }));
    const dialog = await screen.findByRole('dialog', { name: '新增网段' });
    expect(within(dialog).getByRole('option', { name: '正在加载地址空间…' })).toBeTruthy();

    finishSpaceRequest?.(response({ items: [] }));
    expect(await within(dialog).findByText('当前没有可选地址空间。创建一个全局空间，或先在 CMDB 中创建 VRF。')).toBeTruthy();
    expect((within(dialog).getByRole('combobox', { name: '所属地址空间' }) as HTMLSelectElement).value).toBe('');
  });

  it('surfaces address-space permission errors instead of silently falling back', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/ipam/address-spaces') return failure(403, { detail: 'no address-space view permission' });
      if (url.startsWith('/api/ipam/subnets?')) return response({ items: [], total: 0 });
      if (url.startsWith('/api/ipam/prefixes/classification-summary?')) return response({
        total: 0, auto_count: 0, manual_count: 0, unclassified_count: 0,
        mixed_count: 0, conflict_count: 0, reuse_count: 0, stale_count: 0,
      });
      return response([]);
    }));

    render(<MemoryRouter><PrefixManagementTab language="zh" t={(key) => key} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: '新增网段' }));
    const dialog = await screen.findByRole('dialog', { name: '新增网段' });
    expect(await within(dialog).findByText('当前账号没有查看地址空间的权限。')).toBeTruthy();
    expect((within(dialog).getByRole('combobox', { name: '所属地址空间' }) as HTMLSelectElement).value).toBe('');
  });

  it('previews a legacy prefix mapping and keeps it open when the revision is stale', async () => {
    const prefix = {
      id: 'legacy-prefix-1',
      revision: 17,
      prefix: '10.88.40.0/24',
      network: '10.88.40.0',
      prefix_len: 24,
      vrf_id: null,
      vrf_name: null,
      address_space_id: null,
      address_space_name: null,
      address_space_kind: null,
      scope_status: 'scope_pending',
      vlan_id: null,
      vlan_name: null,
      site_id: 'site-1',
      site_name: 'Campus A',
      site_code: 'A',
      tenant_id: 'tenant-default',
      tenant_name: '',
      status: 'active',
      name: 'Legacy prefix',
      gateway: '',
      description: '',
      total_ips: 254,
      used_ips: 0,
      active_ips: 0,
      utilization: 0,
      network_type: 'unclassified',
      gateway_device_id: null,
      gateway_device_name: null,
      gateway_interface_id: null,
      traceable: 1,
      created_at: '',
      updated_at: '2026-11-05T10:00:00Z',
    };
    const space = {
      id: 'space-campus-a',
      name: 'Campus A default',
      kind: 'global',
      vrf_id: null,
      vrf_name: null,
      security_tenant_id: 'tenant-default',
      status: 'active',
      revision: 1,
    };
    let mappingRequest: Record<string, unknown> | null = null;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/ipam/address-spaces') return response({ items: [space] });
      if (url.startsWith('/api/ipam/subnets?')) return response({ items: [prefix], total: 1 });
      if (url.startsWith('/api/ipam/prefixes/classification-summary?')) return response({
        total: 1, auto_count: 0, manual_count: 0, unclassified_count: 1,
        mixed_count: 0, conflict_count: 0, reuse_count: 0, stale_count: 0,
      });
      if (url.startsWith('/api/ipam/subnets/legacy-prefix-1/address-space-preview?')) {
        return response({
          expected_updated_at: prefix.updated_at,
          target_space: { id: space.id, name: space.name, kind: space.kind, vrf_id: null, vrf_name: null },
          impact: { ip_addresses: 3, pools: 1, vips: 0, leases: 4 },
          blockers: [],
          can_confirm: true,
        });
      }
      if (url === '/api/ipam/subnets/legacy-prefix-1/resolve-address-space' && init?.method === 'POST') {
        mappingRequest = JSON.parse(String(init.body || '{}'));
        return failure(409, { detail: 'Prefix changed after preview; reload and try again.' });
      }
      return response([]);
    }));

    render(<MemoryRouter><PrefixManagementTab language="zh" t={(key) => key} /></MemoryRouter>);
    expect(await screen.findByText('网络归属未确认')).toBeTruthy();
    const prefixRow = await openMoreActionsForPrefix('10.88.40.0/24');
    fireEvent.click(within(prefixRow).getByRole('button', { name: '确认网络归属' }));
    const dialog = await screen.findByRole('dialog', { name: '确认地址空间' });
    fireEvent.change(within(dialog).getByRole('combobox', { name: '目标地址空间' }), { target: { value: space.id } });
    expect(await within(dialog).findByText('登记 IP')).toBeTruthy();
    expect(within(dialog).getByText('3')).toBeTruthy();
    const confirmed = within(dialog).getByRole('checkbox', { name: /我已核实此网段/ });
    const submit = within(dialog).getByRole('button', { name: '确认地址空间' });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(confirmed);
    fireEvent.click(submit);

    const staleAlert = await within(dialog).findByRole('alert');
    expect(staleAlert.textContent).toContain('Prefix changed after preview; reload and try again.');
    expect(mappingRequest).toMatchObject({
      address_space_id: space.id,
      expected_revision: 17,
      expected_updated_at: prefix.updated_at,
      confirmed: true,
    });
  });

  it('creates the first global space inline and continues mapping the legacy prefix', async () => {
    const prefix = {
      id: 'legacy-prefix-first-space',
      revision: 19,
      prefix: '10.88.70.0/24',
      network: '10.88.70.0',
      prefix_len: 24,
      vrf_id: null,
      vrf_name: null,
      address_space_id: null,
      address_space_name: null,
      address_space_kind: null,
      scope_status: 'scope_pending',
      vlan_id: null,
      vlan_name: null,
      site_id: 'site-1',
      site_name: 'Campus A',
      site_code: 'A',
      tenant_id: 'tenant-default',
      tenant_name: '',
      status: 'active',
      name: 'Legacy campus prefix',
      gateway: '',
      description: '',
      total_ips: 254,
      used_ips: 0,
      active_ips: 0,
      utilization: 0,
      network_type: 'unclassified',
      gateway_device_id: null,
      gateway_device_name: null,
      gateway_interface_id: null,
      traceable: 1,
      created_at: '',
      updated_at: '2026-11-05T10:00:00Z',
    };
    const createdSpace = {
      id: 'space-global-campus-a',
      name: 'Campus A default',
      kind: 'global',
      vrf_id: null,
      vrf_name: null,
      security_tenant_id: 'tenant-default',
      status: 'active',
      revision: 1,
    };
    const resolvedPrefix = {
      ...prefix,
      address_space_id: createdSpace.id,
      address_space_name: createdSpace.name,
      address_space_kind: 'global',
      scope_status: 'resolved',
    };
    const requests: Array<{ url: string; method: string; body?: Record<string, unknown> }> = [];
    let spaceListReads = 0;
    let prefixListReads = 0;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = String(init?.method || 'GET').toUpperCase();
      if (url === '/api/ipam/address-spaces' && method === 'GET') {
        spaceListReads += 1;
        return response({ items: spaceListReads === 1 ? [] : [createdSpace] });
      }
      if (url === '/api/ipam/address-spaces' && method === 'POST') {
        requests.push({ url, method, body: JSON.parse(String(init?.body || '{}')) });
        return response(createdSpace);
      }
      if (url.startsWith('/api/ipam/subnets/legacy-prefix-first-space/address-space-preview?')) {
        return response({
          expected_updated_at: prefix.updated_at,
          target_space: { id: createdSpace.id, name: createdSpace.name, kind: 'global', vrf_id: null, vrf_name: null },
          impact: { ip_addresses: 0, pools: 0, vips: 0, leases: 0 },
          blockers: [],
          can_confirm: true,
        });
      }
      if (url === '/api/ipam/subnets/legacy-prefix-first-space/resolve-address-space' && method === 'POST') {
        requests.push({ url, method, body: JSON.parse(String(init?.body || '{}')) });
        return response({ ok: true });
      }
      if (url.startsWith('/api/ipam/subnets?')) {
        prefixListReads += 1;
        return response({ items: [prefixListReads === 1 ? prefix : resolvedPrefix], total: 1 });
      }
      if (url.startsWith('/api/ipam/prefixes/classification-summary?')) return response({
        total: 1, auto_count: 0, manual_count: 0, unclassified_count: 1,
        mixed_count: 0, conflict_count: 0, reuse_count: 0, stale_count: 0,
      });
      return response([]);
    }));

    render(<MemoryRouter><PrefixManagementTab language="zh" t={(key) => key} /></MemoryRouter>);
    const prefixRow = await openMoreActionsForPrefix('10.88.70.0/24');
    fireEvent.click(within(prefixRow).getByRole('button', { name: '确认网络归属' }));
    const dialog = await screen.findByRole('dialog', { name: '确认地址空间' });
    fireEvent.change(within(dialog).getByRole('textbox', { name: '新全局地址空间名称' }), { target: { value: 'Campus A default' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '创建并选中' }));

    const targetSelect = within(dialog).getByRole('combobox', { name: '目标地址空间' }) as HTMLSelectElement;
    expect(await within(dialog).findByText('登记 IP')).toBeTruthy();
    expect(targetSelect.value).toBe(createdSpace.id);
    fireEvent.click(within(dialog).getByRole('checkbox', { name: /我已核实此网段/ }));
    fireEvent.click(within(dialog).getByRole('button', { name: '确认地址空间' }));

    expect(await screen.findByText('Campus A default')).toBeTruthy();
    expect(requests.find((item) => item.method === 'POST' && item.url === '/api/ipam/address-spaces')?.body).toMatchObject({
      name: 'Campus A default',
      kind: 'global',
    });
    expect(requests.find((item) => item.url.endsWith('/resolve-address-space'))?.body).toMatchObject({
      address_space_id: createdSpace.id,
      expected_revision: 19,
      expected_updated_at: prefix.updated_at,
      confirmed: true,
    });
    expect(spaceListReads).toBeGreaterThanOrEqual(2);
  });

  it('renders a duplicate-space response as text and leaves mapping unsubmitted', async () => {
    const prefix = {
      id: 'legacy-prefix-duplicate-space', prefix: '10.88.90.0/24', prefix_len: 24,
      vrf_id: null, vrf_name: null, address_space_id: null, scope_status: 'scope_pending',
      vlan_id: null, site_id: 'site-1', site_name: 'Campus A', tenant_id: 'tenant-default',
      status: 'active', name: 'Legacy duplicate', gateway: '', description: '',
      total_ips: 254, used_ips: 0, active_ips: 0, utilization: 0, network_type: 'unclassified',
      gateway_device_id: null, gateway_device_name: null, gateway_interface_id: null,
      traceable: 1, updated_at: '2026-11-05T10:00:00Z',
    };
    const duplicateDetail = '同名地址空间已存在：<script>alert(1)</script>';
    let mappingPosts = 0;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/ipam/address-spaces' && init?.method === 'POST') return failure(409, { detail: duplicateDetail });
      if (url === '/api/ipam/address-spaces') return response({ items: [] });
      if (url.startsWith('/api/ipam/subnets?')) return response({ items: [prefix], total: 1 });
      if (url.startsWith('/api/ipam/prefixes/classification-summary?')) return response({
        total: 1, auto_count: 0, manual_count: 0, unclassified_count: 1,
        mixed_count: 0, conflict_count: 0, reuse_count: 0, stale_count: 0,
      });
      if (url.endsWith('/resolve-address-space') && init?.method === 'POST') mappingPosts += 1;
      return response([]);
    }));

    render(<MemoryRouter><PrefixManagementTab language="zh" t={(key) => key} /></MemoryRouter>);
    const prefixRow = await openMoreActionsForPrefix('10.88.90.0/24');
    fireEvent.click(within(prefixRow).getByRole('button', { name: '确认网络归属' }));
    const dialog = await screen.findByRole('dialog', { name: '确认地址空间' });
    fireEvent.change(within(dialog).getByRole('textbox', { name: '新全局地址空间名称' }), { target: { value: 'Campus A default' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '创建并选中' }));

    const error = await within(dialog).findByRole('alert');
    expect(error.textContent).toBe(duplicateDetail);
    expect(dialog.querySelector('script')).toBeNull();
    expect((within(dialog).getByRole('button', { name: '确认地址空间' }) as HTMLButtonElement).disabled).toBe(true);
    expect(mappingPosts).toBe(0);
  });

  it('shows mapping blockers and will not enable confirmation', async () => {
    const prefix = {
      id: 'legacy-prefix-2', prefix: '10.88.60.0/24', prefix_len: 24,
      vrf_id: null, vrf_name: null, address_space_id: null, scope_status: 'scope_pending',
      vlan_id: null, site_id: 'site-1', site_name: 'Campus A', tenant_id: 'tenant-default',
      status: 'active', name: 'Legacy blocked', gateway: '', description: '',
      total_ips: 254, used_ips: 0, active_ips: 0, utilization: 0, network_type: 'unclassified',
      gateway_device_id: null, gateway_device_name: null, gateway_interface_id: null,
      traceable: 1, updated_at: '2026-11-05T10:00:00Z',
    };
    const space = {
      id: 'space-campus-a', name: 'Campus A default', kind: 'global',
      vrf_id: null, vrf_name: null, security_tenant_id: 'tenant-default', status: 'active', revision: 1,
    };
    let resolvePosts = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/ipam/address-spaces') return response({ items: [space] });
      if (url.startsWith('/api/ipam/subnets?')) return response({ items: [prefix], total: 1 });
      if (url.startsWith('/api/ipam/prefixes/classification-summary?')) return response({
        total: 1, auto_count: 0, manual_count: 0, unclassified_count: 1,
        mixed_count: 0, conflict_count: 0, reuse_count: 0, stale_count: 0,
      });
      if (url.startsWith('/api/ipam/subnets/legacy-prefix-2/address-space-preview?')) {
        return response({
          expected_updated_at: prefix.updated_at,
          target_space: { id: space.id, name: space.name, kind: space.kind, vrf_id: null, vrf_name: null },
          impact: { ip_addresses: 1, pools: 0, vips: 0, leases: 0 },
          blockers: [{ code: 'duplicate', message: 'Address conflict must be resolved first.' }],
          can_confirm: false,
        });
      }
      if (url === '/api/ipam/subnets/legacy-prefix-2/resolve-address-space' && init?.method === 'POST') resolvePosts += 1;
      return response([]);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<MemoryRouter><PrefixManagementTab language="zh" t={(key) => key} /></MemoryRouter>);
    const prefixRow = await openMoreActionsForPrefix('10.88.60.0/24');
    fireEvent.click(within(prefixRow).getByRole('button', { name: '确认网络归属' }));
    const dialog = await screen.findByRole('dialog', { name: '确认地址空间' });
    fireEvent.change(within(dialog).getByRole('combobox', { name: '目标地址空间' }), { target: { value: space.id } });
    expect(await within(dialog).findByText('Address conflict must be resolved first.')).toBeTruthy();
    expect((within(dialog).getByRole('button', { name: '确认地址空间' }) as HTMLButtonElement).disabled).toBe(true);
    expect(resolvePosts).toBe(0);
  });

  it('selects pending candidates across pages and requires explicit confirmation before using the only Global space', async () => {
    const candidates = Array.from({ length: 26 }, (_value, index) => ({
      candidate_id: `pending-candidate-${index}`,
      prefix: `10.88.${index}.0/24`,
      tenant_id: 'tenant-default',
      site_id: 'site-1',
      vrf_id: null,
      address_space_id: null,
      status: 'scope_pending',
      vrf_scope_pending: true,
      interface_count: 1,
      ip_count: 1,
      interfaces: [{
        interface_id: null,
        device_id: `device-${index}`,
        device_name: `core-${index}`,
        interface_name: `Vlan-interface${index}`,
        address: `10.88.${index}.1`,
      }],
    }));
    const globalSpace = {
      id: 'space-global-campus-b', name: 'Campus B default', kind: 'global', vrf_id: null, vrf_name: null,
      security_tenant_id: 'tenant-default', status: 'active', revision: 1,
    };
    const requests: Array<{ body?: Record<string, unknown>; headers?: HeadersInit }> = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/ipam/address-spaces') return response({ items: [globalSpace] });
      if (url === '/api/ipam/prefixes/generate-from-interfaces' && init?.method === 'POST') {
        requests.push({ body: JSON.parse(String(init.body || '{}')), headers: init.headers });
        return response({ created_prefixes: 26, created_addresses: 26, skipped_addresses: [] });
      }
      if (url.startsWith('/api/ipam/prefixes/interface-candidates?')) {
        const query = new URL(url, 'http://localhost').searchParams;
        const page = Number(query.get('page') || 1);
        const pageItems = candidates.slice((page - 1) * 25, page * 25);
        return response({
          candidates: pageItems, candidate_count: 26, existing_count: 0, to_create_count: 0,
          interface_count: 26, vrf_pending_count: 26, skipped_count: 0, page,
          page_size: 25, filtered_count: 26, total_pages: 2,
        });
      }
      if (url === '/api/ipam/prefixes/interface-import-preview' && init?.method === 'POST') {
        return response(makeInterfaceImportPreview(JSON.parse(String(init.body || '{}')), candidates, [globalSpace]));
      }
      if (url.startsWith('/api/ipam/subnets?')) return response({ items: [], total: 0 });
      if (url.startsWith('/api/ipam/prefixes/classification-summary?')) return response({
        total: 0, auto_count: 0, manual_count: 0, unclassified_count: 0,
        mixed_count: 0, conflict_count: 0, reuse_count: 0, stale_count: 0,
      });
      return response([]);
    }));

    render(<MemoryRouter><PrefixManagementTab language="zh" t={(key) => key} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: '从接口 IP 生成' }));
    const generationDialog = await screen.findByRole('dialog', { name: '从接口采集生成 IPAM 网段' });

    const firstCheckbox = await within(generationDialog).findByRole('checkbox', { name: '选择网段 10.88.0.0/24' });
    expect((firstCheckbox as HTMLInputElement).disabled).toBe(false);
    fireEvent.click(within(generationDialog).getByRole('button', { name: '选择本页' }));
    expect(screen.getByText('已明确选择 25 个网段')).toBeTruthy();
    expect((screen.getByRole('button', { name: /生成所选/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole('alert').textContent).toContain('10.88.0.0/24');

    fireEvent.click(within(generationDialog).getByRole('button', { name: '下一页' }));
    const lastCheckbox = await within(generationDialog).findByRole('checkbox', { name: '选择网段 10.88.25.0/24' });
    fireEvent.click(lastCheckbox);
    expect(screen.getByText('已明确选择 26 个网段')).toBeTruthy();
    fireEvent.click(within(generationDialog).getByRole('button', { name: '上一页' }));
    expect((await within(generationDialog).findByRole('checkbox', { name: '选择网段 10.88.0.0/24' }) as HTMLInputElement).checked).toBe(true);

    fireEvent.click(screen.getByRole('button', { name: '确认无 VRF，使用 Global 并应用 (26)' }));
    expect(screen.getByText('已选 26 个候选；其中 0 个待确认地址空间')).toBeTruthy();
    expect(screen.getAllByText('本次已确认 · 待生成')).toHaveLength(25);
    expect((screen.getByRole('button', { name: /生成所选/ }) as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: '生成所选 (26)' }));
    await confirmInterfaceImport();
    expect(await screen.findByText('已创建 26 个网段，并登记 26 个接口 IP')).toBeTruthy();
    expect(requests).toHaveLength(1);
    expect(requests[0].body?.candidate_ids).toHaveLength(26);
    expect(Object.keys(requests[0].body?.address_space_overrides as Record<string, string>)).toHaveLength(26);
    expect(Object.values(requests[0].body?.address_space_overrides as Record<string, string>).every((spaceId) => spaceId === globalSpace.id)).toBe(true);
    expect(new Headers(requests[0].headers).get('Idempotency-Key')).toBeTruthy();
  });

  it('requires a target when multiple Globals exist and keeps known VRF candidates on their matching VRF', async () => {
    const candidates = [
      {
        candidate_id: 'unknown-scope-candidate', prefix: '10.88.90.0/24', tenant_id: 'tenant-default',
        site_id: 'site-1', vrf_id: null, address_space_id: null, status: 'scope_pending', vrf_scope_pending: true,
        interface_count: 1, ip_count: 1,
        interfaces: [{ interface_id: null, device_id: 'device-1', device_name: 'core-1', interface_name: 'Vlan90', address: '10.88.90.1' }],
      },
      {
        candidate_id: 'known-vrf-pending-candidate', prefix: '10.88.91.0/24', tenant_id: 'tenant-default',
        site_id: 'site-1', vrf_id: 'vrf-prod', address_space_id: null, status: 'scope_pending', vrf_scope_pending: true,
        interface_count: 1, ip_count: 1,
        interfaces: [{ interface_id: null, device_id: 'device-2', device_name: 'core-2', interface_name: 'Vlan91', address: '10.88.91.1' }],
      },
    ];
    const spaces = [
      { id: 'space-global-a', name: 'Global A', kind: 'global', vrf_id: null, vrf_name: null, security_tenant_id: 'tenant-default', status: 'active', revision: 1 },
      { id: 'space-global-b', name: 'Global B', kind: 'global', vrf_id: null, vrf_name: null, security_tenant_id: 'tenant-default', status: 'active', revision: 1 },
      { id: 'space-global-other-tenant', name: 'Global other tenant', kind: 'global', vrf_id: null, vrf_name: null, security_tenant_id: 'tenant-other', status: 'active', revision: 1 },
      { id: 'space-vrf-prod', name: 'Production', kind: 'vrf', vrf_id: 'vrf-prod', vrf_name: 'PROD', security_tenant_id: 'tenant-default', status: 'active', revision: 1 },
      { id: 'space-vrf-prod-other-tenant', name: 'Production other tenant', kind: 'vrf', vrf_id: 'vrf-prod', vrf_name: 'PROD', security_tenant_id: 'tenant-other', status: 'active', revision: 1 },
    ];
    let generateBody: Record<string, unknown> | null = null;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/ipam/address-spaces') return response({ items: spaces });
      if (url.startsWith('/api/ipam/prefixes/interface-candidates?')) return response({
        candidates, candidate_count: 2, existing_count: 0, to_create_count: 0,
        interface_count: 2, vrf_pending_count: 2, skipped_count: 0, page: 1,
        page_size: 25, filtered_count: 2, total_pages: 1,
      });
      if (url === '/api/ipam/prefixes/interface-import-preview' && init?.method === 'POST') {
        return response(makeInterfaceImportPreview(JSON.parse(String(init.body || '{}')), candidates, spaces));
      }
      if (url === '/api/ipam/prefixes/generate-from-interfaces' && init?.method === 'POST') {
        generateBody = JSON.parse(String(init.body || '{}'));
        return response({ created_prefixes: 2, created_addresses: 2, skipped_addresses: [] });
      }
      if (url.startsWith('/api/ipam/subnets?')) return response({ items: [], total: 0 });
      if (url.startsWith('/api/ipam/prefixes/classification-summary?')) return response({
        total: 0, auto_count: 0, manual_count: 0, unclassified_count: 0,
        mixed_count: 0, conflict_count: 0, reuse_count: 0, stale_count: 0,
      });
      return response([]);
    }));

    render(<MemoryRouter><PrefixManagementTab language="zh" t={(key) => key} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: '从接口 IP 生成' }));
    fireEvent.click(await screen.findByRole('checkbox', { name: '选择网段 10.88.90.0/24' }));
    fireEvent.click(screen.getByRole('checkbox', { name: '选择网段 10.88.91.0/24' }));

    const globalTarget = screen.getByRole('combobox', { name: '无 VRF 候选的目标 Global 地址空间' });
    expect((globalTarget as HTMLSelectElement).value).toBe('');
    expect(within(globalTarget).queryByRole('option', { name: /other tenant/i })).toBeNull();
    const confirmGlobal = screen.getByRole('button', { name: '确认无 VRF，使用 Global 并应用 (1)' });
    expect((confirmGlobal as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(globalTarget, { target: { value: 'space-global-b' } });
    fireEvent.click(confirmGlobal);

    const bulkVrfTarget = screen.getByRole('combobox', { name: '批量目标 VRF 地址空间' });
    expect(within(bulkVrfTarget).getByRole('option', { name: /VRF：PROD · Production/ })).toBeTruthy();
    expect(within(bulkVrfTarget).queryByRole('option', { name: /other tenant/i })).toBeNull();

    const knownVrfSpace = screen.getByRole('combobox', { name: '为 10.88.91.0/24' });
    expect(within(knownVrfSpace).queryByRole('option', { name: /Global/ })).toBeNull();
    expect(within(knownVrfSpace).getByRole('option', { name: /Production/ })).toBeTruthy();
    expect((knownVrfSpace as HTMLSelectElement).value).toBe('');
    fireEvent.change(knownVrfSpace, { target: { value: 'space-vrf-prod' } });
    fireEvent.click(screen.getByRole('button', { name: '生成所选 (2)' }));
    await confirmInterfaceImport();

    expect(await screen.findByText('已创建 2 个网段，并登记 2 个接口 IP')).toBeTruthy();
    expect(generateBody).toMatchObject({
      candidate_ids: ['unknown-scope-candidate', 'known-vrf-pending-candidate'],
      address_space_overrides: {
        'unknown-scope-candidate': 'space-global-b',
        'known-vrf-pending-candidate': 'space-vrf-prod',
      },
    });
  });

  it('shows the Global space creation path when no active Global space exists', async () => {
    const candidate = {
      candidate_id: 'no-global-scope-candidate', prefix: '10.88.92.0/24', tenant_id: 'tenant-default',
      site_id: 'site-1', vrf_id: null, address_space_id: null, status: 'scope_pending', vrf_scope_pending: true,
      interface_count: 1, ip_count: 1,
      interfaces: [{ interface_id: null, device_id: 'device-1', device_name: 'core-1', interface_name: 'Vlan92', address: '10.88.92.1' }],
    };
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/ipam/address-spaces') return response({ items: [] });
      if (url.startsWith('/api/ipam/prefixes/interface-candidates?')) return response({
        candidates: [candidate], candidate_count: 1, existing_count: 0, to_create_count: 0,
        interface_count: 1, vrf_pending_count: 1, skipped_count: 0, page: 1,
        page_size: 25, filtered_count: 1, total_pages: 1,
      });
      if (url.startsWith('/api/ipam/subnets?')) return response({ items: [], total: 0 });
      if (url.startsWith('/api/ipam/prefixes/classification-summary?')) return response({
        total: 0, auto_count: 0, manual_count: 0, unclassified_count: 0,
        mixed_count: 0, conflict_count: 0, reuse_count: 0, stale_count: 0,
      });
      return response([]);
    }));

    render(<MemoryRouter><PrefixManagementTab language="zh" t={(key) => key} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: '从接口 IP 生成' }));
    fireEvent.click(await screen.findByRole('checkbox', { name: '选择网段 10.88.92.0/24' }));

    expect(screen.getByRole('button', { name: '创建全局空间' })).toBeTruthy();
    expect(screen.getByText(/当前没有可用的 Global 地址空间。请先使用上方“创建全局空间”入口/)).toBeTruthy();
    expect((screen.getByRole('button', { name: '确认无 VRF，使用 Global 并应用 (1)' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('generates an already mapped Global candidate without asking for scope confirmation', async () => {
    const globalSpace = {
      id: 'space-global-mapped', name: 'Campus A default', kind: 'global', vrf_id: null, vrf_name: null,
      security_tenant_id: 'tenant-default', status: 'active', revision: 1,
    };
    const candidate = {
      candidate_id: 'mapped-global-candidate', prefix: '10.88.93.0/24', tenant_id: 'tenant-default',
      site_id: 'site-1', vrf_id: null, address_space_id: globalSpace.id, status: 'to_create', vrf_scope_pending: false,
      interface_count: 1, ip_count: 1,
      interfaces: [{ interface_id: null, device_id: 'device-1', device_name: 'core-1', interface_name: 'Vlan93', address: '10.88.93.1' }],
    };
    let generateBody: Record<string, unknown> | null = null;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/ipam/address-spaces') return response({ items: [globalSpace] });
      if (url.startsWith('/api/ipam/prefixes/interface-candidates?')) return response({
        candidates: [candidate], candidate_count: 1, existing_count: 0, to_create_count: 1,
        interface_count: 1, vrf_pending_count: 0, skipped_count: 0, page: 1,
        page_size: 25, filtered_count: 1, total_pages: 1,
      });
      if (url === '/api/ipam/prefixes/interface-import-preview' && init?.method === 'POST') {
        return response(makeInterfaceImportPreview(JSON.parse(String(init.body || '{}')), [candidate], [globalSpace]));
      }
      if (url === '/api/ipam/prefixes/generate-from-interfaces' && init?.method === 'POST') {
        generateBody = JSON.parse(String(init.body || '{}'));
        return response({ created_prefixes: 1, created_addresses: 1, skipped_addresses: [] });
      }
      if (url.startsWith('/api/ipam/subnets?')) return response({ items: [], total: 0 });
      if (url.startsWith('/api/ipam/prefixes/classification-summary?')) return response({
        total: 0, auto_count: 0, manual_count: 0, unclassified_count: 0,
        mixed_count: 0, conflict_count: 0, reuse_count: 0, stale_count: 0,
      });
      return response([]);
    }));

    render(<MemoryRouter><PrefixManagementTab language="zh" t={(key) => key} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: '从接口 IP 生成' }));
    fireEvent.click(await screen.findByRole('checkbox', { name: '选择网段 10.88.93.0/24' }));
    expect(screen.queryByRole('combobox', { name: '为 10.88.93.0/24' })).toBeNull();
    expect(screen.queryByRole('button', { name: /确认无 VRF/ })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '生成所选 (1)' }));
    await confirmInterfaceImport();
    expect(await screen.findByText('已创建 1 个网段，并登记 1 个接口 IP')).toBeTruthy();
    expect(generateBody).toMatchObject({ candidate_ids: ['mapped-global-candidate'] });
    expect(generateBody).not.toHaveProperty('address_space_overrides');
  });

  it('lets the backend resolve a known VRF candidate without a manual space override', async () => {
    const space = {
      id: 'space-vrf-prod',
      name: 'PROD',
      kind: 'vrf',
      vrf_id: 'vrf-prod',
      vrf_name: 'PROD',
      security_tenant_id: 'tenant-default',
      status: 'active',
      revision: 1,
    };
    const candidate = {
      candidate_id: 'known-vrf-candidate',
      prefix: '10.88.80.0/24',
      tenant_id: 'tenant-default',
      site_id: 'site-1',
      vrf_id: 'vrf-prod',
      status: 'to_create',
      vrf_scope_pending: false,
      interface_count: 1,
      ip_count: 1,
      interfaces: [{
        interface_id: 'interface-1',
        device_id: 'device-1',
        device_name: 'core-1',
        interface_name: 'Vlan-interface80',
        address: '10.88.80.1',
      }],
    };
    let generateBody: Record<string, unknown> | null = null;
    let generateHeaders: HeadersInit | undefined;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/ipam/address-spaces') return response({ items: [space] });
      if (url.startsWith('/api/ipam/prefixes/interface-candidates?')) return response({
        candidates: [candidate], candidate_count: 1, existing_count: 0, to_create_count: 1,
        interface_count: 1, vrf_pending_count: 0, skipped_count: 0, page: 1,
        page_size: 25, filtered_count: 1, total_pages: 1,
      });
      if (url === '/api/ipam/prefixes/interface-import-preview' && init?.method === 'POST') {
        return response(makeInterfaceImportPreview(JSON.parse(String(init.body || '{}')), [candidate], [space]));
      }
      if (url === '/api/ipam/prefixes/generate-from-interfaces' && init?.method === 'POST') {
        generateBody = JSON.parse(String(init.body || '{}'));
        generateHeaders = init.headers;
        return response({ created_prefixes: 1, created_addresses: 1, skipped_addresses: [] });
      }
      if (url.startsWith('/api/ipam/subnets?')) return response({ items: [], total: 0 });
      if (url.startsWith('/api/ipam/prefixes/classification-summary?')) return response({
        total: 0, auto_count: 0, manual_count: 0, unclassified_count: 0,
        mixed_count: 0, conflict_count: 0, reuse_count: 0, stale_count: 0,
      });
      return response([]);
    }));

    render(<MemoryRouter><PrefixManagementTab language="zh" t={(key) => key} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: '从接口 IP 生成' }));
    const checkbox = await screen.findByRole('checkbox', { name: '选择网段 10.88.80.0/24' });
    expect((checkbox as HTMLInputElement).disabled).toBe(false);
    fireEvent.click(checkbox);
    fireEvent.click(screen.getByRole('button', { name: /生成所选/ }));
    await confirmInterfaceImport();
    expect(await screen.findByText('已创建 1 个网段，并登记 1 个接口 IP')).toBeTruthy();

    expect(generateBody).toMatchObject({ candidate_ids: ['known-vrf-candidate'] });
    expect(generateBody).not.toHaveProperty('address_space_overrides');
    expect(new Headers(generateHeaders).get('Idempotency-Key')).toBeTruthy();
  });

  it('sends the prefix revision when editing and deleting a prefix', async () => {
    const prefix = {
      id: 'prefix-write', revision: 23, prefix: '10.88.60.0/24', network: '10.88.60.0', prefix_len: 24,
      vrf_id: null, vrf_name: null, address_space_id: 'space-global', address_space_name: 'Campus A default',
      address_space_kind: 'global', scope_status: 'resolved', vlan_id: null, vlan_name: null,
      site_id: 'site-1', site_name: 'Campus A', site_code: 'A', tenant_id: 'tenant-default', tenant_name: '',
      status: 'active', name: 'Write contract', gateway: '', description: '', total_ips: 254,
      used_ips: 0, active_ips: 0, utilization: 0, network_type: 'unclassified', gateway_device_id: null,
      gateway_device_name: null, gateway_interface_id: null, traceable: 1, created_at: '', updated_at: '2026-11-05T10:00:00Z',
    };
    const requests: Array<{ url: string; method: string; body?: Record<string, unknown> }> = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = String(init?.method || 'GET').toUpperCase();
      if (url === '/api/ipam/address-spaces') return response({ items: [{
        id: 'space-global', name: 'Campus A default', kind: 'global', vrf_id: null, vrf_name: null,
        security_tenant_id: 'tenant-default', status: 'active', revision: 1,
      }] });
      if (new URL(url, 'http://localhost').pathname === '/api/ipam/subnets/prefix-write' && (method === 'PUT' || method === 'DELETE')) {
        requests.push({ url, method, ...(init?.body ? { body: JSON.parse(String(init.body)) } : {}) });
        return response({ ok: true });
      }
      if (url.startsWith('/api/ipam/subnets?')) return response({ items: [prefix], total: 1 });
      if (url.startsWith('/api/ipam/prefixes/classification-summary?')) return response({
        total: 1, auto_count: 0, manual_count: 0, unclassified_count: 1,
        mixed_count: 0, conflict_count: 0, reuse_count: 0, stale_count: 0,
      });
      return response([]);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<MemoryRouter><PrefixManagementTab language="zh" t={(key) => key} /></MemoryRouter>);

    const prefixCell = await screen.findByText('10.88.60.0/24');
    let row = prefixCell.closest('tr')!;
    const rowManageButton = within(row).getByRole('button', { name: /^管理 / });
    fireEvent.click(rowManageButton);
    expect(within(row).getByRole('link', { name: '管理 IP' }).getAttribute('href')).toBe('/ipam/ips?prefix_id=prefix-write');
    fireEvent.click(within(row).getByRole('button', { name: '编辑网段（用途、网关等）' }));
    const editDialog = await screen.findByRole('dialog', { name: '编辑网段' });
    fireEvent.click(within(editDialog).getByRole('button', { name: '确定保存' }));
    await waitFor(() => expect(requests.some((request) => request.method === 'PUT')).toBe(true));
    expect(requests.find((request) => request.method === 'PUT')?.body).toMatchObject({ expected_revision: 23 });

    row = screen.getByText('10.88.60.0/24').closest('tr')!;
    fireEvent.click(within(row).getByRole('button', { name: /^管理 / }));
    expect(within(row).getByRole('button', { name: '迁移网络归属' })).toBeTruthy();
    expect(within(row).getByRole('button', { name: '管理地址池' })).toBeTruthy();
    expect(within(row).getByRole('button', { name: '编辑网段（用途、网关等）' })).toBeTruthy();
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(within(row).queryByRole('button', { name: '迁移网络归属' })).toBeNull());
    expect(document.activeElement).toBe(within(row).getByRole('button', { name: /^管理 / }));

    fireEvent.click(within(row).getByRole('button', { name: /^管理 / }));
    fireEvent.pointerDown(document.body);
    await waitFor(() => expect(within(row).queryByRole('button', { name: '删除' })).toBeNull());
    fireEvent.click(within(row).getByRole('button', { name: /^管理 / }));
    fireEvent.click(within(row).getByRole('button', { name: '删除' }));
    fireEvent.click(await screen.findByRole('button', { name: '确认删除' }));
    await waitFor(() => expect(requests.some((request) => request.method === 'DELETE')).toBe(true));
    const deleteUrl = requests.find((request) => request.method === 'DELETE')?.url || '';
    expect(new URL(deleteUrl, 'http://localhost').searchParams.get('expected_revision')).toBe('23');
  });

  it('reports confirmed and interrupted suggestion groups and reloads the prefix list', async () => {
    const prefixes = [
      { id: 'mgmt', revision: 1, prefix: '10.88.62.0/24', network_type: 'unclassified', suggested_network_type: 'management' },
      { id: 'transit', revision: 1, prefix: '10.88.63.0/30', network_type: 'unclassified', suggested_network_type: 'transit' },
    ].map((prefix) => ({
      ...prefix, status: 'active', total_ips: 4, used_ips: 0, active_ips: 0, utilization: 0,
    }));
    let listLoads = 0;
    const refreshSnapshots: number[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith('/api/ipam/subnets?')) {
        listLoads++;
        return response({ items: prefixes, total: prefixes.length });
      }
      if (url === '/api/ipam/subnets/batch-update-network-type') {
        const { network_type: type } = JSON.parse(String(init?.body));
        if (type === 'management') return response({ updated: 1 });
        refreshSnapshots.push(listLoads);
        throw new Error('connection interrupted');
      }
      return response([]);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<MemoryRouter><PrefixManagementTab language="zh" t={(key) => key} /></MemoryRouter>);

    fireEvent.click(await screen.findByRole('button', { name: '采纳推荐用途' }));
    fireEvent.click(screen.getByRole('button', { name: '确认采纳' }));

    expect(await screen.findByText(/已采纳推荐用途：1 个网段/)).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toContain('连接中断，提交结果待确认');
    expect(refreshSnapshots).toHaveLength(1);
    expect(listLoads).toBeGreaterThan(refreshSnapshots[0]);
  });

  it('includes each selected prefix revision in batch purpose and delete writes', async () => {
    const prefix = {
      id: 'prefix-batch', revision: 31, prefix: '10.88.61.0/24', network: '10.88.61.0', prefix_len: 24,
      vrf_id: null, vrf_name: null, address_space_id: 'space-global', address_space_name: 'Campus A default',
      address_space_kind: 'global', scope_status: 'resolved', vlan_id: null, vlan_name: null,
      site_id: 'site-1', site_name: 'Campus A', site_code: 'A', tenant_id: 'tenant-default', tenant_name: '',
      status: 'active', name: 'Batch contract', gateway: '', description: '', total_ips: 254,
      used_ips: 0, active_ips: 0, utilization: 0, network_type: 'unclassified', gateway_device_id: null,
      gateway_device_name: null, gateway_interface_id: null, traceable: 1, created_at: '', updated_at: '2026-11-05T10:00:00Z',
    };
    const requests: Array<{ url: string; body: Record<string, unknown> }> = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = String(init?.method || 'GET').toUpperCase();
      if (url === '/api/ipam/address-spaces') return response({ items: [] });
      if (url === '/api/ipam/subnets/batch-update-network-type' || url === '/api/ipam/subnets/batch-delete') {
        requests.push({ url, body: JSON.parse(String(init?.body || '{}')) });
        return response({ ok: true });
      }
      if (url.startsWith('/api/ipam/subnets?')) return response({ items: [prefix], total: 1 });
      if (url.startsWith('/api/ipam/prefixes/classification-summary?')) return response({
        total: 1, auto_count: 0, manual_count: 0, unclassified_count: 1,
        mixed_count: 0, conflict_count: 0, reuse_count: 0, stale_count: 0,
      });
      if (url === '/api/ipam/subnets/batch-update-network-type' && method === 'POST') return response({ updated: 1 });
      return response([]);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<MemoryRouter><PrefixManagementTab language="zh" t={(key) => key} /></MemoryRouter>);

    let row = (await screen.findByText('10.88.61.0/24')).closest('tr')!;
    fireEvent.click(within(row).getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: '批量修改用途' }));
    fireEvent.click(within(await screen.findByRole('dialog', { name: '批量修改网段用途' })).getByRole('button', { name: '确认修改' }));
    await waitFor(() => expect(requests.some((request) => request.url.endsWith('/batch-update-network-type'))).toBe(true));
    expect(requests.find((request) => request.url.endsWith('/batch-update-network-type'))?.body.expected_revisions).toEqual({ 'prefix-batch': 31 });

    row = screen.getByText('10.88.61.0/24').closest('tr')!;
    fireEvent.click(within(row).getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: '批量删除' }));
    fireEvent.click(await screen.findByRole('button', { name: '确定批量删除' }));
    await waitFor(() => expect(requests.some((request) => request.url.endsWith('/batch-delete'))).toBe(true));
    expect(requests.find((request) => request.url.endsWith('/batch-delete'))?.body.expected_revisions).toEqual({ 'prefix-batch': 31 });
  });

  it('explains the exact duplicate CIDR and sites in the batch address-space preview', async () => {
    const prefixes = [
      {
        id: 'prefix-duplicate-a', revision: 3, prefix: '10.200.35.0/30', network: '10.200.35.0', prefix_len: 30,
        vrf_id: null, vrf_name: null, address_space_id: null, address_space_name: null, address_space_kind: null,
        scope_status: 'scope_pending', vlan_id: null, vlan_name: null, site_id: 'site-1', site_name: 'WH-DC-01',
        site_code: '', tenant_id: 'tenant-default', tenant_name: '', status: 'active', name: '', gateway: '',
        description: '', total_ips: 2, used_ips: 0, active_ips: 0, utilization: 0, network_type: 'transit',
        gateway_device_id: null, gateway_device_name: null, gateway_interface_id: null, traceable: 1,
        created_at: '', updated_at: '2026-11-10T10:00:00Z',
      },
      {
        id: 'prefix-duplicate-b', revision: 4, prefix: '10.200.35.0/30', network: '10.200.35.0', prefix_len: 30,
        vrf_id: null, vrf_name: null, address_space_id: null, address_space_name: null, address_space_kind: null,
        scope_status: 'scope_pending', vlan_id: null, vlan_name: null, site_id: 'site-2', site_name: 'WH-DC-02',
        site_code: '', tenant_id: 'tenant-default', tenant_name: '', status: 'active', name: '', gateway: '',
        description: '', total_ips: 2, used_ips: 0, active_ips: 0, utilization: 0, network_type: 'transit',
        gateway_device_id: null, gateway_device_name: null, gateway_interface_id: null, traceable: 1,
        created_at: '', updated_at: '2026-11-10T10:00:00Z',
      },
    ];
    const space = {
      id: 'space-global-review', name: 'Global default', kind: 'global', vrf_id: null, vrf_name: null,
      security_tenant_id: 'tenant-default', status: 'active', revision: 1,
    };
    let resolveRequestSent = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/ipam/address-spaces') return response({ items: [space] });
      if (url === '/api/ipam/subnets/address-space-batch-resolve') {
        resolveRequestSent = true;
        return response({ ok: true });
      }
      if (url === '/api/ipam/subnets/address-space-batch-preview') return response({
        address_space_id: space.id,
        target_space: space,
        expected_target_revision: 1,
        selected_count: 2,
        can_confirm: false,
        totals: { ip_addresses: 0, pools: 0, vips: 0, leases: 0 },
        items: prefixes.map((prefix) => ({
          prefix_id: prefix.id,
          prefix: prefix.prefix,
          site_name: prefix.site_name,
          expected_updated_at: prefix.updated_at,
          expected_revision: prefix.revision,
          blockers: [{
            code: 'duplicate_prefix_cidr_in_batch',
            message: 'Batch contains 2 Prefix records for CIDR 10.200.35.0/30',
            network: '10.200.35.0/30',
            duplicate_count: 2,
            sites: ['WH-DC-01', 'WH-DC-02'],
          }],
          can_confirm: false,
        })),
      });
      if (url.startsWith('/api/ipam/subnets?')) return response({ items: prefixes, total: prefixes.length });
      if (url.startsWith('/api/ipam/prefixes/classification-summary?')) return response({
        total: 2, auto_count: 0, manual_count: 0, unclassified_count: 0,
        mixed_count: 0, conflict_count: 0, reuse_count: 0, stale_count: 0,
      });
      return response([]);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<MemoryRouter><PrefixManagementTab language="zh" t={(key) => key} /></MemoryRouter>);
    for (const index of prefixes.map((_prefix, itemIndex) => itemIndex)) {
      const duplicatePrefixButtons = await screen.findAllByText(prefixes[0].prefix, { selector: 'button' });
      const row = duplicatePrefixButtons[index].closest('tr')!;
      fireEvent.click(within(row).getByRole('checkbox'));
    }
    fireEvent.click(screen.getByRole('button', { name: '批量修改地址空间' }));
    const dialog = await screen.findByRole('dialog', { name: '批量修改地址空间' });
    fireEvent.change(within(dialog).getByRole('combobox', { name: '批量目标地址空间' }), { target: { value: space.id } });

    const duplicateMessages = await within(dialog).findAllByText(/本批次选中的 2 条记录使用了相同 CIDR：10\.200\.35\.0\/30/);
    expect(duplicateMessages).toHaveLength(2);
    expect(duplicateMessages[0].textContent).toContain('涉及站点：WH-DC-01、WH-DC-02');
    const confirm = within(dialog).getByRole('button', { name: '确认映射 2 个网段' });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    expect(resolveRequestSent).toBe(false);
  });

  it('queries gateway candidates with the selected address space and preserves a manual device choice', async () => {
    let candidateUrl = '';
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/cmdb/sites') return response([{ id: 'site-1', site_name: 'Campus A', site_code: 'A' }]);
      if (url === '/api/ipam/address-spaces') return response({ items: [{
        id: 'space-vrf-prod', name: 'Production', kind: 'vrf', vrf_id: 'vrf-prod', vrf_name: 'PROD',
        security_tenant_id: 'tenant-default', status: 'active', revision: 1,
      }] });
      if (url === '/api/cmdb/vlans') return response([]);
      if (url === '/api/devices?mode=light') return response([
        { id: 'manual-device', hostname: 'Manual Gateway', ip_address: '192.0.2.1' },
        { id: 'candidate-device', hostname: 'Candidate Gateway', ip_address: '192.0.2.2' },
      ]);
      if (url.startsWith('/api/ipam/prefixes/gateway-candidates?')) {
        candidateUrl = url;
        return response({
          status: 'matched',
          selected: {
            device_id: 'candidate-device', device_name: 'Candidate Gateway',
            interface_name: 'Vlan20', interface_id: null, address: '10.1.1.1',
          },
          endpoints: [],
        });
      }
      if (url.startsWith('/api/ipam/subnets?')) return response({ items: [], total: 0 });
      if (url.startsWith('/api/ipam/prefixes/classification-summary?')) return response({
        total: 0, auto_count: 0, manual_count: 0, unclassified_count: 0,
        mixed_count: 0, conflict_count: 0, reuse_count: 0, stale_count: 0,
      });
      return response([]);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<MemoryRouter><PrefixManagementTab language="zh" t={(key) => key} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: '新增网段' }));
    const dialog = await screen.findByRole('dialog', { name: '新增网段' });
    fireEvent.change(within(dialog).getByRole('combobox', { name: '所属地址空间' }), { target: { value: 'space-vrf-prod' } });
    fireEvent.change(within(dialog).getByPlaceholderText('e.g. 10.1.1.0/24'), { target: { value: '10.1.1.0/24' } });
    const siteSelect = within(dialog).getByRole('option', { name: 'Campus A (A)' }).closest('select')!;
    fireEvent.change(siteSelect, { target: { value: 'site-1' } });
    const gatewayDevice = within(dialog).getByRole('option', { name: 'Manual Gateway (192.0.2.1)' }).closest('select')!;
    fireEvent.change(gatewayDevice, { target: { value: 'manual-device' } });

    await waitFor(() => expect(candidateUrl).not.toBe(''), { timeout: 1500 });
    const query = new URL(candidateUrl, 'http://localhost').searchParams;
    expect(query.get('address_space_id')).toBe('space-vrf-prod');
    expect(query.has('vrf_id')).toBe(false);
    expect(gatewayDevice.value).toBe('manual-device');
  });

  it('shows the no-match prompt and preserves a manual gateway choice', async () => {
    const { dialog } = await openGatewayCandidateForm({
      status: 'no_candidate', selected: null, endpoints: [], gateway_ip: '10.1.1.1',
    }, 'manual-device');

    expect(await within(dialog).findByText('没有接口与填写的网关 IP 匹配；已保留人工设备选择。')).toBeTruthy();
    const gatewayDevice = within(dialog).getByRole('option', { name: 'Manual Gateway (192.0.2.1)' }).closest('select') as HTMLSelectElement;
    expect(gatewayDevice.value).toBe('manual-device');
  });

  it('shows the ambiguous-candidate prompt and preserves a manual gateway choice', async () => {
    const { dialog } = await openGatewayCandidateForm({
      status: 'ambiguous',
      selected: null,
      gateway_ip: '10.1.1.1',
      endpoints: [
        {
          device_id: 'candidate-device-a', device_name: 'Candidate Gateway A',
          interface_name: 'Vlan10', interface_id: null, address: '10.1.1.1',
          address_space_id: 'space-vrf-prod', context_type: 'vrf', scope_status: 'resolved',
        },
        {
          device_id: 'candidate-device-b', device_name: 'Candidate Gateway B',
          interface_name: 'Vlan20', interface_id: null, address: '10.1.1.1',
          address_space_id: 'space-vrf-prod', context_type: 'vrf', scope_status: 'resolved',
        },
      ],
    }, 'manual-device');

    expect(await within(dialog).findByText('多个接口与网关 IP 完全匹配，无法唯一选择；已保留人工设备选择。')).toBeTruthy();
    const gatewayDevice = within(dialog).getByRole('option', { name: 'Manual Gateway (192.0.2.1)' }).closest('select') as HTMLSelectElement;
    expect(gatewayDevice.value).toBe('manual-device');
  });

  it('does not auto-bind an ambiguous gateway candidate when no manual choice exists', async () => {
    const { dialog } = await openGatewayCandidateForm({
      status: 'ambiguous',
      selected: null,
      gateway_ip: '10.1.1.1',
      endpoints: [
        {
          device_id: 'candidate-device-a', device_name: 'Candidate Gateway A',
          interface_name: 'Vlan10', interface_id: null, address: '10.1.1.1',
          address_space_id: 'space-vrf-prod', context_type: 'vrf', scope_status: 'resolved',
        },
        {
          device_id: 'candidate-device-b', device_name: 'Candidate Gateway B',
          interface_name: 'Vlan20', interface_id: null, address: '10.1.1.1',
          address_space_id: 'space-vrf-prod', context_type: 'vrf', scope_status: 'resolved',
        },
      ],
    });

    expect(await within(dialog).findByText('多个接口与网关 IP 完全匹配，无法唯一选择；当前未自动关联。')).toBeTruthy();
    const gatewayDevice = within(dialog).getByRole('option', { name: '未绑定' }).closest('select') as HTMLSelectElement;
    expect(gatewayDevice.value).toBe('');
  });

  it('keeps purpose uncertainty separate from system-maintained classification', async () => {
    const prefix = {
      id: 'auto-unclassified', revision: 1, prefix: '10.87.1.0/24', network: '10.87.1.0', prefix_len: 24,
      vrf_id: null, vrf_name: null, address_space_id: 'space-global', address_space_name: 'Campus A default',
      address_space_kind: 'global', scope_status: 'resolved', vlan_id: null, vlan_name: null,
      site_id: 'site-1', site_name: 'Campus A', site_code: 'A', tenant_id: 'tenant-default', tenant_name: '',
      status: 'active', name: 'Auto but unknown purpose', gateway: '', description: '', total_ips: 254,
      used_ips: 0, active_ips: 0, utilization: 0, network_type: 'unclassified', classification_status: 'auto',
      gateway_device_id: null, gateway_device_name: null, gateway_interface_id: null, traceable: 1,
    };
    const prefixQueries: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/ipam/subnets?')) {
        prefixQueries.push(url);
        return response({ items: [prefix], total: 21 });
      }
      if (url.startsWith('/api/ipam/prefixes/classification-summary?')) return response({
        total: 21, auto_count: 21, manual_count: 0, unclassified_count: 21,
        mixed_count: 0, conflict_count: 0, reuse_count: 0, stale_count: 0,
      });
      if (url === '/api/ipam/address-spaces') return response({ items: [{
        id: 'space-global', name: 'Campus A default', kind: 'global', vrf_id: null, vrf_name: null,
        security_tenant_id: 'tenant-default', status: 'active', revision: 1,
      }] });
      return response([]);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<MemoryRouter><PrefixManagementTab language="zh" t={(key) => key} /></MemoryRouter>);

    const row = (await screen.findByText(prefix.prefix)).closest('tr')!;
    expect(within(row).getByText('用途未确定')).toBeTruthy();
    expect(within(row).getByText('全局（无 VRF）')).toBeTruthy();
    expect(screen.getByRole('button', { name: /用途未确定: 21/ })).toBeTruthy();
    fireEvent.click(screen.getByText('用途维护方式'));
    fireEvent.click(screen.getByRole('button', { name: /系统维护: 21/ }));

    expect(await screen.findByText('当前分类筛选：系统维护 · 21 条网段记录')).toBeTruthy();
    await waitFor(() => expect(prefixQueries.some((query) => (
      new URL(query, 'http://localhost').searchParams.get('classification') === 'auto'
    ))).toBe(true));
  });

  it('shows explicit Global and VRF ownership and leaves unmapped scope unconfirmed', async () => {
    const prefixes = [
      {
        id: 'global-prefix', revision: 1, prefix: '10.87.2.0/24', network: '10.87.2.0', prefix_len: 24,
        vrf_id: null, vrf_name: null, address_space_id: 'space-global', address_space_name: 'Campus A default',
        address_space_kind: 'global', scope_status: 'resolved', vlan_id: null, vlan_name: null,
        site_id: 'site-1', site_name: 'Campus A', site_code: 'A', tenant_id: 'tenant-default', tenant_name: '',
        status: 'active', name: 'Global prefix', gateway: '', description: '', total_ips: 254, used_ips: 0,
        active_ips: 0, utilization: 0, network_type: 'unclassified', gateway_device_id: null,
        gateway_device_name: null, gateway_interface_id: null, traceable: 1,
      },
      {
        id: 'vrf-global-prefix', revision: 1, prefix: '10.87.3.0/24', network: '10.87.3.0', prefix_len: 24,
        vrf_id: 'vrf-global', vrf_name: 'global', address_space_id: 'space-vrf-global', address_space_name: 'global',
        address_space_kind: 'vrf', scope_status: 'resolved', vlan_id: null, vlan_name: null,
        site_id: 'site-1', site_name: 'Campus A', site_code: 'A', tenant_id: 'tenant-default', tenant_name: '',
        status: 'active', name: 'VRF prefix', gateway: '', description: '', total_ips: 254, used_ips: 0,
        active_ips: 0, utilization: 0, network_type: 'server', gateway_device_id: null,
        gateway_device_name: null, gateway_interface_id: null, traceable: 1,
      },
      {
        id: 'pending-prefix', revision: 1, prefix: '10.87.4.0/24', network: '10.87.4.0', prefix_len: 24,
        vrf_id: 'vrf-unconfirmed', vrf_name: 'Unconfirmed VRF hint', address_space_id: null, address_space_name: null,
        address_space_kind: null, scope_status: 'scope_pending', vlan_id: null, vlan_name: null,
        site_id: 'site-1', site_name: 'Campus A', site_code: 'A', tenant_id: 'tenant-default', tenant_name: '',
        status: 'active', name: 'Unconfirmed prefix', gateway: '', description: '', total_ips: 254, used_ips: 0,
        active_ips: 0, utilization: 0, network_type: 'unclassified', gateway_device_id: null,
        gateway_device_name: null, gateway_interface_id: null, traceable: 1,
      },
    ];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/ipam/subnets?')) return response({ items: prefixes, total: prefixes.length });
      if (url === '/api/ipam/subnets/tree') return response(prefixes);
      if (url.startsWith('/api/ipam/prefixes/classification-summary?')) return response({
        total: prefixes.length, auto_count: 0, manual_count: 0, unclassified_count: 2,
        mixed_count: 0, conflict_count: 0, reuse_count: 0, stale_count: 0,
      });
      if (url === '/api/ipam/address-spaces') return response({ items: [
        { id: 'space-global', name: 'Campus A default', kind: 'global', vrf_id: null, vrf_name: null, security_tenant_id: 'tenant-default', status: 'active', revision: 1 },
        { id: 'space-vrf-global', name: 'global', kind: 'vrf', vrf_id: 'vrf-global', vrf_name: 'global', security_tenant_id: 'tenant-default', status: 'active', revision: 1 },
      ] });
      return response([]);
    }));

    render(<MemoryRouter><PrefixManagementTab language="zh" t={(key) => key} /></MemoryRouter>);

    const globalRow = (await screen.findByText('10.87.2.0/24')).closest('tr')!;
    expect(within(globalRow).getByText('全局（无 VRF）')).toBeTruthy();
    expect(within(globalRow).getByText('Campus A default')).toBeTruthy();
    const vrfRow = screen.getByText('10.87.3.0/24').closest('tr')!;
    expect(within(vrfRow).getByText('VRF global')).toBeTruthy();
    expect(within(vrfRow).queryByText('global')).toBeNull();
    const pendingRow = screen.getByText('10.87.4.0/24').closest('tr')!;
    expect(within(pendingRow).getByText('网络归属未确认')).toBeTruthy();
    expect(within(pendingRow).queryByText('VRF Unconfirmed VRF hint')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: '新增网段' }));
    const dialog = await screen.findByRole('dialog', { name: '新增网段' });
    const addressSpace = within(dialog).getByRole('combobox', { name: '所属地址空间' });
    expect(within(addressSpace).getByRole('option', { name: '全局（无 VRF） · Campus A default' })).toBeTruthy();
    expect(within(addressSpace).getByRole('option', { name: 'VRF：global' })).toBeTruthy();

    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '新增网段' })).toBeNull());
    fireEvent.click(screen.getByRole('button', { name: '层次树视图' }));
    const treeRow = (await screen.findByText('10.87.2.0/24')).closest('tr')!;
    fireEvent.click(within(treeRow).getByRole('button', { name: /^管理 / }));
    expect(within(treeRow).getByRole('link', { name: '管理 IP' }).getAttribute('href')).toBe('/ipam/ips?prefix_id=global-prefix');
    expect(within(treeRow).getByRole('button', { name: '编辑网段（用途、网关等）' })).toBeTruthy();
    expect(within(treeRow).getByRole('button', { name: '迁移网络归属' })).toBeTruthy();
  });

  it('separates unmapped duplicate CIDRs from confirmed cross-site reuse', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/ipam/subnets?')) return response({ items: [], total: 4 });
      if (url.startsWith('/api/ipam/prefixes/classification-summary?')) return response({
        total: 4,
        auto_count: 2,
        manual_count: 1,
        unclassified_count: 1,
        mixed_count: 0,
        conflict_count: 0,
        reuse_count: 0,
        address_space_pending_count: 2,
        pending_duplicate_group_count: 1,
        pending_duplicate_record_count: 2,
        stale_count: 0,
      });
      if (url === '/api/ipam/address-spaces') return response({ items: [] });
      return response([]);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<MemoryRouter><PrefixManagementTab language="zh" t={(key) => key} /></MemoryRouter>);

    const pendingNotice = await screen.findByRole('status', { name: '待确认地址归属与重复网段' });
    expect(pendingNotice.textContent).toContain('地址空间待确认 2 条');
    expect(pendingNotice.textContent).toContain('跨站点重复 CIDR 待裁决 1 组（2 条 Prefix）');
    expect(pendingNotice.textContent).toContain('不计为已确认冲突或合法复用');
    expect(screen.getByRole('button', { name: /跨站点复用: 0/ })).toBeTruthy();
  });
});
