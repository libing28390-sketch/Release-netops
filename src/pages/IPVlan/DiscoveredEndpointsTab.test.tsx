import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import DiscoveredEndpointsTab from './DiscoveredEndpointsTab';

const response = (payload: unknown, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => payload }) as Response;

const item = {
  id: 'obs-1', ip: '10.10.1.21', mac: '00:11:22:33:44:55', tenant_id: 'tenant-1',
  site_id: 'site-1', site_name: 'WH-DC-01', vrf_id: 'vrf-1', vrf_name: 'PROD',
  scope_status: 'resolved', registration_status: 'unregistered', subnet_id: null, subnet_prefix: null,
  source_device_id: 'switch-1', source_device_name: 'SW-01', switch_id: 'switch-1', switch_name: 'SW-01',
  switch_port: null, vlan: '20', observed_at: '2026-10-28T02:00:00Z', mac_observed_at: null,
  projected_at: '2026-10-28T10:01:00+08:00', evidence_status: 'recent', hostname: '', source_type: 'arp',
  endpoint_class: 'candidate', endpoint_class_reason: 'access_path_not_confirmed',
};

const renderPage = (language = 'zh') => render(<MemoryRouter><DiscoveredEndpointsTab language={language} t={(key) => key} /></MemoryRouter>);

describe('DiscoveredEndpointsTab', () => {
  beforeEach(() => {
    localStorage.setItem('netops_token', 'test-token');
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/ipam/endpoints?')) return response({
        items: [item], total: 1, page: 1, page_size: 20, has_more: false,
        summary: { discovered_ip_count: 1, distinct_ip_count: 1, infrastructure_ip_count: 0, access_host_ip_count: 0, candidate_ip_count: 1, mac_only_count: 0, registered_count: 0, unregistered_count: 1, scope_pending_count: 0, conflict_count: 0, path_ambiguity_count: 0, coverage_status: 'partial', coverage_reason: '部分来源缺少范围', source_last_success_at: '2026-10-29T09:00:00+08:00' },
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

  it('groups endpoint table columns and loads concise endpoint details on demand', async () => {
    const { container } = renderPage();
    expect(await screen.findByText('10.10.1.21')).toBeTruthy();
    expect(screen.getByText('PROD')).toBeTruthy();
    expect(screen.getByText('2026-10-28 10:00')).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: '最近采集时间' })).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: '网络位置' })).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: '采集来源' })).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: 'IPAM 台账' })).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: '接入接口 / 路径' })).toBeTruthy();
    const endpointRow = screen.getByRole('row', { name: /10\.10\.1\.21/ });
    expect(endpointRow.querySelectorAll('td')).toHaveLength(9);
    expect(within(endpointRow).getByText('ARP 表', { exact: true })).toBeTruthy();
    expect(within(endpointRow).getByText('WH-DC-01')).toBeTruthy();
    expect(within(endpointRow).getByText('PROD')).toBeTruthy();
    expect(within(endpointRow).getByText('SW-01')).toBeTruthy();
    expect(within(endpointRow).getByText('VLAN 20')).toBeTruthy();
    expect(endpointRow.querySelectorAll('td')[6].textContent).toBe('');
    expect(endpointRow.querySelectorAll('td')[6].hasAttribute('title')).toBe(false);
    expect(screen.queryByText(/ARP 来源/)).toBeNull();
    expect(screen.queryByText('—')).toBeNull();
    expect(screen.queryByText('未知')).toBeNull();
    expect(screen.getByRole('button', { name: '搜索' }).closest('form')?.className).toContain('items-end');
    expect(container.querySelector('.nx-data-table-frame')).not.toBeNull();
    expect(screen.queryByRole('status')).toBeNull();
    expect(screen.getByRole('button', { name: '刷新' })).toBeTruthy();
    expect(container.querySelector('svg.lucide-terminal')).not.toBeNull();
    expect(screen.queryByText('类型未知')).toBeNull();
    expect(screen.queryByRole('region', { name: '发现摘要' })).toBeNull();
    expect(screen.queryByText('源采集最近成功')).toBeNull();
    expect(screen.getByText('更多筛选').closest('details')?.open).toBe(false);
    expect(screen.queryByRole('option', { name: '历史观察' })).toBeNull();

    const fetchMock = vi.mocked(fetch);
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes('/api/ipam/endpoints?kind=ip&network_scope=all'))).toBe(true);
    expect(fetchMock.mock.calls.some(([input]) => String(input).startsWith('/api/devices?'))).toBe(false);

    fireEvent.click(screen.getByRole('button', { name: '查看详情' }));
    expect(await screen.findByRole('dialog', { name: '终端详情' })).toBeTruthy();
    expect(screen.queryByText(/run-17/)).toBeNull();
    expect(screen.getByRole('columnheader', { name: /^IP$/ })).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: /^MAC$/ })).toBeTruthy();
    expect(within(screen.getByRole('dialog')).getByText('接入接口')).toBeTruthy();
    expect(fetchMock.mock.calls.some(([input]) => String(input) === '/api/ipam/endpoints/obs-1')).toBe(true);
  });

  it('opens registration from a current IP row without writing before confirmation', async () => {
    renderPage();
    const row = await screen.findByRole('row', { name: /10\.10\.1\.21/ });
    fireEvent.click(within(row).getByRole('button', { name: '登记到 IPAM' }));
    const dialog = await screen.findByRole('dialog', { name: '登记到 IPAM' });
    expect(within(dialog).getByRole('button', { name: '确认登记' }).hasAttribute('disabled')).toBe(true);
    expect(vi.mocked(fetch).mock.calls.some(call => call[1]?.method === 'POST')).toBe(false);
  });

  it('exports site, VRF, access device, and access port as separate fields', async () => {
    const blobs: Blob[] = [];
    class ExportURL extends URL {
      static createObjectURL(blob: Blob) {
        blobs.push(blob);
        return `blob:export-${blobs.length}`;
      }

      static revokeObjectURL() {}
    }
    vi.stubGlobal('URL', ExportURL);

    renderPage();
    await screen.findByText('10.10.1.21');
    fireEvent.click(screen.getByRole('button', { name: '导出表格' }));
    await screen.findByText('已准备 1 条记录，请选择格式下载。');

    const csv = await blobs[1].text();
    const [header, row] = csv.replace(/^\uFEFF/, '').split('\r\n');
    expect(header).toBe('"IP","MAC","终端类型","说明","来源","IPAM 主机名","IPAM 登记","站点","VRF","VLAN","采集设备","接入接口 / 路径","采集时间","采集情况"');
    expect(row).toContain('"接入口待定位","尚未定位到唯一接入口","ARP 表","","未登记","WH-DC-01","PROD","20","SW-01",""');
  });

  it('shows missing source as pending and leaves other missing values blank', async () => {
    const emptyEndpoint = {
      ...item,
      id: 'obs-empty',
      ip: null,
      mac: null,
      hostname: null,
      site_name: null,
      vrf_name: null,
      vrf_context_inferred: false,
      vlan: null,
      source_device_name: null,
      switch_name: null,
      switch_port: null,
      observed_at: null,
      registration_status: 'unregistered',
      source_type: undefined,
      observation_source: undefined,
    };
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/ipam/endpoints?')) return response({ items: [emptyEndpoint], total: 1, summary: {}, sites: [], vrfs: [], devices: [] });
      if (url === '/api/ipam/endpoints/obs-empty') return response(emptyEndpoint);
      return response({});
    }));
    renderPage();

    const endpointRow = (await screen.findByRole('row', { name: /未登记/ }));
    const cells = endpointRow.querySelectorAll('td');
    expect(cells).toHaveLength(9);
    for (const index of [0, 1, 3, 6, 7]) expect(cells[index].textContent).toBe('');
    expect(cells[2].textContent).toContain('接入口待定位');
    expect(cells[4].textContent).toBe('来源待确认');
    expect(cells[5].textContent).toContain('未登记');
    expect(endpointRow.textContent).not.toContain('—');
    expect(endpointRow.textContent).not.toContain('未知');
    expect(screen.queryByText('端口待定位')).toBeNull();
    expect(screen.queryByText(/ARP 来源/)).toBeNull();
    expect(Array.from(cells).some((cell) => cell.hasAttribute('title'))).toBe(false);

    fireEvent.click(within(endpointRow).getByRole('button', { name: '查看详情' }));
    const dialog = await screen.findByRole('dialog', { name: '终端详情' });
    const detailValues = Array.from(dialog.querySelectorAll('dl > div')).map((field) => ({
      label: field.querySelector('dt')?.textContent,
      value: field.querySelector('dd')?.textContent,
    }));
    expect(detailValues).toEqual([
      { label: 'IP', value: '' },
      { label: 'MAC', value: '' },
      { label: '终端类型', value: '接入口待定位' },
      { label: '说明', value: '尚未定位到唯一接入口' },
      { label: 'VLAN', value: '' },
      { label: '站点', value: '' },
      { label: '来源设备', value: '' },
      { label: '关联交换机', value: '' },
      { label: '接入接口', value: '' },
      { label: '接入路径', value: '' },
      { label: '网络归属', value: '已确认' },
      { label: '来源', value: '来源待确认' },
      { label: '最近采集时间', value: '' },
    ]);
  });

  it('shows the loading state until the endpoint list request completes', async () => {
    let resolveList: ((value: Response) => void) | undefined;
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => { resolveList = resolve; })));
    renderPage();

    expect(await screen.findByText('正在加载采集记录…')).toBeTruthy();
    resolveList?.(response({ items: [], total: 0, summary: {}, sites: [], vrfs: [], devices: [] }));
    expect(await screen.findByText('没有符合条件的记录，请调整筛选或重置。')).toBeTruthy();
  });

  it('shows a retryable error when the endpoint API fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => String(input).startsWith('/api/ipam/endpoints?')
      ? response({ detail: 'internal error' }, 500)
      : response({})));
    renderPage();

    expect((await screen.findByRole('alert')).textContent).toContain('加载发现终端失败，请稍后重试');
    expect(screen.getByRole('button', { name: '重试' })).toBeTruthy();
  });

  it('keeps secondary filters collapsed and applies them when expanded', async () => {
    renderPage();
    await screen.findByText('10.10.1.21');
    const disclosure = screen.getByText('更多筛选').closest('details');
    expect(disclosure?.open).toBe(false);
    fireEvent.click(screen.getByText('更多筛选'));
    expect(disclosure?.open).toBe(true);
    fireEvent.change(screen.getByRole('combobox', { name: '采集情况筛选' }), { target: { value: 'conflict' } });
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).includes('evidence_status=conflict'))).toBe(true));
  });

  it('leaves an inferred default VRF blank in the list and export', async () => {
    const blobs: Blob[] = [];
    class ExportURL extends URL {
      static createObjectURL(blob: Blob) {
        blobs.push(blob);
        return `blob:export-${blobs.length}`;
      }

      static revokeObjectURL() {}
    }
    vi.stubGlobal('URL', ExportURL);
    const inferredEndpoint = { ...item, vrf_id: null, vrf_name: '全局/默认', vrf_context_inferred: true };
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => String(input).startsWith('/api/ipam/endpoints?')
      ? response({ items: [inferredEndpoint], total: 1, summary: {}, sites: [], vrfs: [], devices: [] })
      : response({})));
    renderPage();
    expect(await screen.findByText('10.10.1.21')).toBeTruthy();
    const networkCell = screen.getByRole('row', { name: /10\.10\.1\.21/ }).querySelectorAll('td')[3];
    expect(networkCell.textContent).toContain('WH-DC-01');
    expect(networkCell.textContent).not.toContain('全局/默认');

    fireEvent.click(screen.getByRole('button', { name: '导出表格' }));
    await screen.findByText('已准备 1 条记录，请选择格式下载。');
    const csv = await blobs[1].text();
    const [, row] = csv.replace(/^\uFEFF/, '').split('\r\n');
    expect(row).toContain('"WH-DC-01","","20"');
    expect(csv).not.toContain('全局/默认');
  });

  it('loads MAC-only observations from the current FDB scope', async () => {
    renderPage();
    await screen.findByText('10.10.1.21');
    const macOnlyOption = screen.getByRole('option', { name: '仅有 MAC' }) as HTMLOptionElement;
    expect(macOnlyOption.disabled).toBe(false);
    fireEvent.change(screen.getByRole('combobox', { name: '查看内容筛选' }), { target: { value: 'mac' } });
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).includes('/api/ipam/endpoints?kind=mac&network_scope=all'))).toBe(true));
  });

  it('exposes current IP observations with pending scope through the all-scope filter', async () => {
    const blobs: Blob[] = [];
    class ExportURL extends URL {
      static createObjectURL(blob: Blob) {
        blobs.push(blob);
        return `blob:scope-export-${blobs.length}`;
      }

      static revokeObjectURL() {}
    }
    vi.stubGlobal('URL', ExportURL);

    const pendingScopeItem = {
      ...item,
      id: 'obs-scope-pending',
      ip: '172.16.5.10',
      vrf_id: null,
      vrf_name: null,
      scope_status: 'scope_pending',
      registration_status: 'scope_pending',
      collection_status: 'scope_unknown',
      generation: 21,
      last_success_generation: 21,
      latest_attempt_generation: 21,
      last_success_at: '2026-11-11T02:33:19+08:00',
    };
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/ipam/endpoints' && url.searchParams.get('network_scope') === 'all') {
        return response({
          items: [pendingScopeItem], total: 1, page: 1, page_size: 20, has_more: false,
          summary: { discovered_ip_count: 1, mac_only_count: 0, registered_count: 0, unregistered_count: 0, scope_pending_count: 1 },
          sites: [{ site_id: 'site-1', site_name: 'WH-DC-01' }], vrfs: [{ id: '__unknown__', name: '所属网络待确认' }],
          devices: [{ device_id: 'switch-1', device_name: 'SW-01' }],
        });
      }
      if (url.pathname === '/api/ipam/endpoints') {
        return response({
          items: [item], total: 1, summary: { discovered_ip_count: 1, registered_count: 0, unregistered_count: 1, scope_pending_count: 0 },
          sites: [], vrfs: [], devices: [],
        });
      }
      if (url.pathname === '/api/ipam/endpoints/obs-scope-pending') return response(pendingScopeItem);
      return response({});
    }));

    renderPage();
    expect(await screen.findByText('172.16.5.10')).toBeTruthy();
    const pendingRow = screen.getByRole('row', { name: /172\.16\.5\.10/ });
    expect(within(pendingRow).getByText('网络待确认')).toBeTruthy();
    fireEvent.change(screen.getByRole('combobox', { name: '网段范围筛选' }), { target: { value: 'business_vlan' } });
    expect(await screen.findByText('10.10.1.21')).toBeTruthy();
    expect(screen.getByText(/所属网络尚未确认的记录/)).toBeTruthy();
    fireEvent.change(screen.getByRole('combobox', { name: '网段范围筛选' }), { target: { value: 'all' } });
    expect(await screen.findByText('172.16.5.10')).toBeTruthy();
    const fetchMock = vi.mocked(fetch);
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes('/api/ipam/endpoints?kind=ip&network_scope=all'))).toBe(true);

    fireEvent.click(screen.getByRole('button', { name: '导出表格' }));
    await screen.findByText('已准备 1 条记录，请选择格式下载。');
    expect(fetchMock.mock.calls.some(([input]) => {
      const url = new URL(String(input), 'http://localhost');
      return url.pathname === '/api/ipam/endpoints'
        && url.searchParams.get('kind') === 'ip'
        && url.searchParams.get('network_scope') === 'all'
        && url.searchParams.get('page_size') === '100';
    })).toBe(true);
    const exportedCsv = await blobs[1].text();
    expect(exportedCsv).toContain('172.16.5.10');
    expect(exportedCsv).toContain('所属网络待确认');

    fireEvent.click(within(screen.getByRole('row', { name: /172\.16\.5\.10/ })).getByRole('button', { name: '查看详情' }));
    const detail = await screen.findByRole('dialog', { name: '终端详情' });
    const detailValues = Array.from(detail.querySelectorAll('dl > div')).map((field) => ({
      label: field.querySelector('dt')?.textContent,
      value: field.querySelector('dd')?.textContent,
    }));
    expect(detailValues).toContainEqual({ label: '当前数据批次', value: '21' });
    expect(detailValues).toContainEqual({ label: '上次成功批次', value: '21' });
    expect(detailValues).toContainEqual({ label: '最近采集批次', value: '21' });
    expect(detailValues).toContainEqual({ label: '最新采集状态', value: '所属网络待确认' });
    expect(detailValues).toContainEqual({ label: '最近成功时间', value: '2026-11-11 02:33:19' });
  });

  it('renders a current FDB path as a MAC observation without IP ownership', async () => {
    const blobs: Blob[] = [];
    class ExportURL extends URL {
      static createObjectURL(blob: Blob) {
        blobs.push(blob);
        return `blob:fdb-export-${blobs.length}`;
      }

      static revokeObjectURL() {}
    }
    vi.stubGlobal('URL', ExportURL);

    const fdbItem = {
      ...item,
      id: 'fdb:current-1',
      ip: null,
      mac: '00:11:22:33:44:99',
      source_type: 'mac',
      observation_source: 'fdb',
      endpoint_class: 'mac_only',
      endpoint_class_reason: 'fdb_without_ip',
      scope_status: 'scope_pending',
      registration_status: 'not_applicable',
      switch_name: 'SW-EDGE-01',
      switch_port: 'Port-channel1',
      path_ambiguity: true,
      path_ambiguity_reason: 'multiple_current_fdb_paths_for_mac_vlan_scope',
      path_classification: 'aggregation_member',
      path_evidence: 'current_interface_aggregation_membership',
      aggregation_name: 'Port-channel1',
      virtual_gateway_mac: true,
    };
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      if (url.pathname === '/api/ipam/endpoints' && url.searchParams.get('kind') === 'mac') {
        return response({
          items: [fdbItem], total: 1, page: 1, page_size: 20, has_more: false,
          summary: { discovered_ip_count: 0, mac_only_count: 1, registered_count: 0, unregistered_count: 0, conflict_count: 0, path_ambiguity_count: 1, scope_pending_count: 1 },
          sites: [{ site_id: 'site-1', site_name: 'WH-DC-01' }], vrfs: [], devices: [{ device_id: 'switch-1', device_name: 'SW-EDGE-01' }],
        });
      }
      if (decodeURIComponent(url.pathname) === '/api/ipam/endpoints/fdb:current-1') {
        return response({ ...fdbItem, observations: [{
          source_type: 'fdb', source_device_name: 'SW-EDGE-01', interface_name: 'Port-channel1',
          vlan: '20', ip: null, mac: fdbItem.mac, observed_at: fdbItem.observed_at,
        }] });
      }
      if (url.pathname === '/api/ipam/endpoints') {
        return response({ items: [item], total: 1, summary: {}, sites: [], vrfs: [], devices: [] });
      }
      return response({});
    }));
    renderPage();
    await screen.findByText('10.10.1.21');
    fireEvent.change(screen.getByRole('combobox', { name: '查看内容筛选' }), { target: { value: 'mac' } });

    expect(await screen.findByText('00:11:22:33:44:99')).toBeTruthy();
    expect(screen.queryByText('10.10.1.21')).toBeNull();
    const fdbRow = screen.getByRole('row', { name: /00:11:22:33:44:99/ });
    expect(within(fdbRow).getByText('仅有 MAC，无法登记 IP')).toBeTruthy();
    expect(within(fdbRow).getByText('MAC 地址表（FDB）')).toBeTruthy();
    expect(within(fdbRow).getByText('网络待确认')).toBeTruthy();
    expect(within(fdbRow).getByText('路径歧义')).toBeTruthy();
    expect(within(fdbRow).getByText(/聚合成员 · Port-channel1 · 虚拟网关 MAC/)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: '导出表格' }));
    await screen.findByText('已准备 1 条记录，请选择格式下载。');
    const csv = await blobs[1].text();
    const [header, row] = csv.replace(/^\uFEFF/, '').split('\r\n');
    expect(header).toBe('"IP","MAC","终端类型","说明","来源","IPAM 主机名","IPAM 登记","站点","VRF","VLAN","采集设备","接入接口 / 路径","采集时间","采集情况"');
    expect(row.startsWith('"","00:11:22:33:44:99","仅有 MAC","未获取到对应 IP","MAC 地址表（FDB）"')).toBe(true);
    expect(row).toContain('"仅有 MAC，无法登记 IP 所属网络待确认"');
    expect(row).not.toMatch(/"\d{1,3}(?:\.\d{1,3}){3}"/);

    fireEvent.click(within(fdbRow).getByRole('button', { name: '查看详情' }));
    const dialog = await screen.findByRole('dialog', { name: '终端详情' });
    expect(within(dialog).getByText('MAC 地址表（FDB）')).toBeTruthy();
    expect(within(dialog).getByText('所属网络待确认')).toBeTruthy();
    expect(within(dialog).getByText(/聚合成员 · Port-channel1 · 虚拟网关 MAC/)).toBeTruthy();
  });

  it('labels IPv6 ND distinctly in English in the list and detail', async () => {
    const ndpItem = { ...item, id: 'ndp-obs', source_type: 'ndp', observation_source: undefined };
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/ipam/endpoints?')) return response({ items: [ndpItem], total: 1, summary: {}, sites: [], vrfs: [], devices: [] });
      if (url === '/api/ipam/endpoints/ndp-obs') return response(ndpItem);
      return response({});
    }));
    renderPage('en');

    const endpointRow = await screen.findByRole('row', { name: /10\.10\.1\.21/ });
    expect(screen.getByRole('columnheader', { name: 'Collection source' })).toBeTruthy();
    expect(within(endpointRow).getByText('IPv6 neighbor table (ND)')).toBeTruthy();
    fireEvent.click(within(endpointRow).getByRole('button', { name: 'View details' }));
    const dialog = await screen.findByRole('dialog', { name: 'Endpoint details' });
    expect(within(dialog).getByText('IPv6 neighbor table (ND)')).toBeTruthy();
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
    fireEvent.change(await screen.findByRole('combobox', { name: '查看内容筛选' }), { target: { value: 'all' } });
    expect(await screen.findByText('10.10.1.22')).toBeTruthy();
    resolveOld?.(response({ items: [item], total: 1, summary: {}, sites: [], vrfs: [], devices: [] }));
    await waitFor(() => expect(screen.queryByText('10.10.1.21')).toBeNull());
  });

  it('keeps uncommon filters folded and counts every non-default condition through reset', async () => {
    renderPage();
    await screen.findByText('10.10.1.21');
    const disclosure = screen.getByText('更多筛选').closest('details')!;
    expect(disclosure.open).toBe(false);
    expect(screen.getByRole('combobox', { name: '来源设备筛选' }).closest('details')).toBeNull();
    expect(screen.getByRole('combobox', { name: '查看内容筛选' }).closest('details')).toBe(disclosure);
    expect(screen.getByRole('combobox', { name: '网段范围筛选' }).closest('details')).toBe(disclosure);
    fireEvent.click(screen.getByText('更多筛选'));
    fireEvent.change(screen.getByRole('combobox', { name: '终端类型筛选' }), { target: { value: 'all' } });
    fireEvent.change(screen.getByRole('combobox', { name: '查看内容筛选' }), { target: { value: 'all' } });
    fireEvent.change(screen.getByRole('combobox', { name: '网段范围筛选' }), { target: { value: 'business_vlan' } });
    expect(disclosure.querySelector('summary')?.textContent).toBe('更多筛选3');
    fireEvent.click(screen.getByRole('button', { name: '重置' }));
    expect(disclosure.querySelector('summary')?.textContent).toBe('更多筛选');
    expect((screen.getByRole('combobox', { name: '终端类型筛选' }) as HTMLSelectElement).value).toBe('terminal');
    expect((screen.getByRole('combobox', { name: '查看内容筛选' }) as HTMLSelectElement).value).toBe('ip');
    expect((screen.getByRole('combobox', { name: '网段范围筛选' }) as HTMLSelectElement).value).toBe('all');
  });

  it('switches directly between source devices even after an empty result', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const query = new URL(String(input), 'http://localhost').searchParams;
      const device = query.get('device_id');
      return response({
        items: device === 'switch-1' ? [] : [{ ...item, source_device_id: 'switch-2', source_device_name: 'SW-02' }],
        total: device === 'switch-1' ? 0 : 1,
        sites: [{ id: 'site-1', name: 'WH-DC-01' }], vrfs: [], summary: {},
        devices: [{ id: 'switch-1', name: 'SW-01' }, { id: 'switch-2', name: 'SW-02' }],
      });
    }));
    renderPage();
    await screen.findByText('10.10.1.21');
    fireEvent.change(screen.getByRole('combobox', { name: '来源设备筛选' }), { target: { value: 'switch-1' } });
    await screen.findByText('没有符合条件的记录，请调整筛选或重置。');
    const deviceSelect = screen.getByRole('combobox', { name: '来源设备筛选' });
    expect(within(deviceSelect).getByRole('option', { name: 'SW-02' })).toBeTruthy();
    fireEvent.change(deviceSelect, { target: { value: 'switch-2' } });
    const row = await screen.findByRole('row', { name: /10\.10\.1\.21/ });
    expect(within(row).getByText('SW-02')).toBeTruthy();
    expect((deviceSelect as HTMLSelectElement).value).toBe('switch-2');
    const requestedDevices = vi.mocked(fetch).mock.calls.map(([input]) => new URL(String(input), 'http://localhost').searchParams.get('device_id'));
    expect(requestedDevices).toEqual([null, 'switch-1', 'switch-2']);
  });

  it('filters infrastructure IPs without disturbing site selection', async () => {
    const records = [
      item,
      { ...item, id: 'host-2', ip: '10.10.1.22' },
      { ...item, id: 'device-1', ip: '10.10.1.1', endpoint_class: 'infrastructure' },
      { ...item, id: 'device-2', ip: '10.10.1.2', endpoint_class: 'infrastructure' },
    ];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const query = new URL(String(input), 'http://localhost').searchParams;
      const rows = query.get('endpoint_class') === 'terminal'
        ? records.filter(row => row.endpoint_class !== 'infrastructure') : records;
      return response({
        items: rows, total: rows.length,
        summary: { discovered_ip_count: 4, infrastructure_ip_count: 2, candidate_ip_count: 2, scope_pending_count: 0 },
        sites: [{ id: 'site-1', name: 'WH-DC-01' }], devices: [{ id: 'switch-1', name: 'SW-01' }], vrfs: [],
      });
    }));
    renderPage();
    await screen.findByText('10.10.1.21');
    expect(screen.queryByRole('region', { name: '发现摘要' })).toBeNull();
    expect(screen.queryByRole('row', { name: /10\.10\.1\.1\b/ })).toBeNull();
    fireEvent.change(screen.getByRole('combobox', { name: '站点筛选' }), { target: { value: 'site-1' } });
    await screen.findByText('10.10.1.21');
    expect(screen.queryByRole('button', { name: '查看全部 IP 记录' })).toBeNull();
    expect((screen.getByRole('combobox', { name: '站点筛选' }) as HTMLSelectElement).value).toBe('site-1');
    fireEvent.click(screen.getByText('更多筛选'));
    fireEvent.change(screen.getByRole('combobox', { name: '终端类型筛选' }), { target: { value: 'all' } });
    await screen.findByRole('row', { name: /10\.10\.1\.1\b/ });
    expect(vi.mocked(fetch).mock.calls.some(([input]) => {
      const query = new URL(String(input), 'http://localhost').searchParams;
      return query.get('site_id') === 'site-1' && (!query.get('endpoint_class') || query.get('endpoint_class') === 'all');
    })).toBe(true);
    expect(screen.queryByText('“所属网络待确认”在哪里处理？')).toBeNull();
  });

  it('shows a clear permission error instead of an empty success state', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => String(input).startsWith('/api/ipam/endpoints?')
      ? response({ detail: 'forbidden' }, 403)
      : response({ items: [] })));
    renderPage();
    expect((await screen.findByRole('alert')).textContent).toContain('当前账号没有权限查看发现终端');
    expect(screen.queryByText('没有符合条件的记录，请调整筛选或重置。')).toBeNull();
  });

  it('preserves suggested_subnet_id and vrf_context_status when opening registration dialog', async () => {
    const resolvedGlobalItem = {
      ...item,
      id: 'obs-global-1',
      vrf_id: null,
      vrf_name: '全局/默认',
      address_space_id: 'space-global-1',
      address_space_name: 'Global-Default',
      address_space_kind: 'global',
      vrf_context_status: 'explicit_global',
      scope_status: 'resolved',
      suggested_subnet_id: 'prefix-10-10-1',
      suggested_subnet_prefix: '10.10.1.0/24',
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith('/api/ipam/endpoints?')) {
        return response({
          items: [resolvedGlobalItem], total: 1, page: 1, page_size: 20, has_more: false,
          sites: [{ id: 'site-1', name: 'WH-DC-01' }], vrfs: [], devices: [{ id: 'switch-1', name: 'SW-01' }],
        });
      }
      if (String(url).split('?')[0] === '/api/ipam/subnets') {
        return response({
          items: [{
            id: 'prefix-10-10-1',
            prefix: '10.10.1.0/24',
            name: 'Office-VLAN20',
            tenant_id: 'tenant-1',
            site_id: 'site-1',
            site_name: 'WH-DC-01',
            vrf_id: null,
            vrf_name: '',
            address_space_id: 'space-global-1',
            address_space_name: 'Global-Default',
            address_space_kind: 'global',
            is_active: 1,
            status: 'active',
          }],
        });
      }
      if (url === '/api/ipam/reconciliation/register' && init?.method === 'POST') {
        return response({ ok: true });
      }
      return response({});
    });
    vi.stubGlobal('fetch', fetchMock);

    renderPage();
    const row = await screen.findByRole('row', { name: /10\.10\.1\.21/ });
    fireEvent.click(within(row).getByRole('button', { name: '登记到 IPAM' }));
    const dialog = await screen.findByRole('dialog', { name: '登记到 IPAM' });
    await waitFor(() => {
      expect(within(dialog).getByRole('button', { name: '确认登记' }).hasAttribute('disabled')).toBe(false);
    });
    fireEvent.click(within(dialog).getByRole('button', { name: '确认登记' }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/ipam/reconciliation/register',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            observation_id: 'obs-global-1',
            subnet_id: 'prefix-10-10-1',
            expected_observed_at: resolvedGlobalItem.observed_at,
            confirmed_scope: true,
          }),
        }),
      );
    });
  });
});
