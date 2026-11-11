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

  it('shows split endpoint columns and loads concise endpoint details on demand', async () => {
    const { container } = renderPage();
    expect(await screen.findByText('10.10.1.21')).toBeTruthy();
    expect(screen.getByText('PROD')).toBeTruthy();
    expect(screen.getByText('2026-10-28 10:00')).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: '上一次时间' })).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: '站点' })).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: 'VRF' })).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: '观察来源' })).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: '观察设备' })).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: '观察接口与路径' })).toBeTruthy();
    const endpointRow = screen.getByRole('row', { name: /10\.10\.1\.21/ });
    expect(endpointRow.querySelectorAll('td')).toHaveLength(13);
    expect(within(endpointRow).getByText('ARP 观察')).toBeTruthy();
    expect(within(endpointRow).getByText('WH-DC-01')).toBeTruthy();
    expect(within(endpointRow).getByText('PROD')).toBeTruthy();
    expect(within(endpointRow).getByText('SW-01')).toBeTruthy();
    expect(endpointRow.querySelectorAll('td')[10].textContent).toBe('');
    expect(endpointRow.querySelectorAll('td')[10].hasAttribute('title')).toBe(false);
    expect(screen.queryByText(/ARP 来源/)).toBeNull();
    expect(screen.queryByText('—')).toBeNull();
    expect(screen.queryByText('未知')).toBeNull();
    expect(screen.getByRole('button', { name: '搜索' }).closest('form')?.className).toContain('items-end');
    expect(container.querySelector('.nx-data-table-frame')).not.toBeNull();
    expect(screen.queryByRole('status')).toBeNull();
    expect(screen.getByRole('button', { name: '刷新' })).toBeTruthy();
    expect(container.querySelector('svg.lucide-terminal')).not.toBeNull();
    expect(screen.queryByText('类型未知')).toBeNull();
    expect(screen.getByText('ARP/ND 观察条数')).toBeTruthy();
    const summary = screen.getByRole('region', { name: '发现摘要' });
    expect(within(summary).getByText('不同 IP（当前范围）')).toBeTruthy();
    expect(within(summary).getByText('接入口主机候选')).toBeTruthy();
    expect(within(summary).getByText('仅 MAC 观察')).toBeTruthy();
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
    expect(within(screen.getByRole('dialog')).getByText('观察接口')).toBeTruthy();
    expect(fetchMock.mock.calls.some(([input]) => String(input) === '/api/ipam/endpoints/obs-1')).toBe(true);
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
    expect(header).toBe('"IP","MAC","判定","判定依据","观察来源","主机名","IPAM 登记","站点","VRF","VLAN","观察设备","观察接口与路径","观察时间","证据状态"');
    expect(row).toContain('"待核主机候选","尚无唯一的当前接入口证据","ARP 观察","","未登记","WH-DC-01","PROD","20","SW-01",""');
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
    expect(cells).toHaveLength(13);
    for (const index of [0, 1, 4, 6, 7, 8, 9, 10, 11]) expect(cells[index].textContent).toBe('');
    expect(cells[2].textContent).toContain('待核主机候选');
    expect(cells[3].textContent).toBe('来源待确认');
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
      { label: '主机判定', value: '待核主机候选' },
      { label: '判定依据', value: '尚无唯一的当前接入口证据' },
      { label: 'VLAN', value: '' },
      { label: '站点', value: '' },
      { label: '来源设备', value: '' },
      { label: '观察设备', value: '' },
      { label: '观察接口', value: '' },
      { label: '路径判定', value: '' },
      { label: '范围状态', value: 'resolved' },
      { label: '记录来源', value: '来源待确认' },
      { label: '上一次时间', value: '' },
    ]);
  });

  it('shows the loading state until the endpoint list request completes', async () => {
    let resolveList: ((value: Response) => void) | undefined;
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => { resolveList = resolve; })));
    renderPage();

    expect(await screen.findByText('正在加载已有发现记录…')).toBeTruthy();
    resolveList?.(response({ items: [], total: 0, summary: {}, sites: [], vrfs: [], devices: [] }));
    expect(await screen.findByText('当前筛选没有发现记录。清除筛选或更换条件后重试。')).toBeTruthy();
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
    fireEvent.change(screen.getByRole('combobox', { name: '证据状态筛选' }), { target: { value: 'conflict' } });
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
    const vrfCell = screen.getByRole('row', { name: /10\.10\.1\.21/ }).querySelectorAll('td')[7];
    expect(vrfCell.textContent).toBe('');
    expect(vrfCell.hasAttribute('title')).toBe(false);

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
    const macOnlyOption = screen.getByRole('option', { name: '仅 MAC 观察（不登记 IP）' }) as HTMLOptionElement;
    expect(macOnlyOption.disabled).toBe(false);
    fireEvent.change(screen.getByRole('combobox', { name: '记录类型筛选' }), { target: { value: 'mac' } });
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
          sites: [{ site_id: 'site-1', site_name: 'WH-DC-01' }], vrfs: [{ id: '__unknown__', name: '范围待确认' }],
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
    const defaultPendingSummaryLabel = within(screen.getByRole('region', { name: '发现摘要' })).getByText('范围待确认');
    expect(defaultPendingSummaryLabel.parentElement?.textContent).toBe('范围待确认1');
    const pendingRow = screen.getByRole('row', { name: /172\.16\.5\.10/ });
    expect(within(pendingRow).getByText('范围待确认')).toBeTruthy();
    expect(pendingRow.querySelectorAll('td')[7].textContent).toBe('');
    const pendingSummaryLabel = within(screen.getByRole('region', { name: '发现摘要' })).getByText('范围待确认');
    expect(pendingSummaryLabel.parentElement?.textContent).toBe('范围待确认1');
    fireEvent.change(screen.getByRole('combobox', { name: '观察范围筛选' }), { target: { value: 'business_vlan' } });
    expect(await screen.findByText('10.10.1.21')).toBeTruthy();
    expect(screen.getByText(/未知或待确认范围的当前记录/)).toBeTruthy();
    fireEvent.change(screen.getByRole('combobox', { name: '观察范围筛选' }), { target: { value: 'all' } });
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
    expect(exportedCsv).toContain('范围待确认');

    fireEvent.click(within(screen.getByRole('row', { name: /172\.16\.5\.10/ })).getByRole('button', { name: '查看详情' }));
    const detail = await screen.findByRole('dialog', { name: '终端详情' });
    const detailValues = Array.from(detail.querySelectorAll('dl > div')).map((field) => ({
      label: field.querySelector('dt')?.textContent,
      value: field.querySelector('dd')?.textContent,
    }));
    expect(detailValues).toContainEqual({ label: '当前成功代次', value: '21' });
    expect(detailValues).toContainEqual({ label: '最近成功代次', value: '21' });
    expect(detailValues).toContainEqual({ label: '最新尝试代次', value: '21' });
    expect(detailValues).toContainEqual({ label: '最新采集状态', value: '范围待确认' });
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
    fireEvent.change(screen.getByRole('combobox', { name: '记录类型筛选' }), { target: { value: 'mac' } });

    expect(await screen.findByText('00:11:22:33:44:99')).toBeTruthy();
    expect(screen.queryByText('10.10.1.21')).toBeNull();
    const fdbRow = screen.getByRole('row', { name: /00:11:22:33:44:99/ });
    expect(within(fdbRow).getByText('MAC 观察（未创建 IP）')).toBeTruthy();
    expect(within(fdbRow).getByText('FDB / MAC 观察（不登记 IP）')).toBeTruthy();
    expect(within(fdbRow).getByText('范围待确认')).toBeTruthy();
    expect(within(fdbRow).getByText('路径歧义')).toBeTruthy();
    expect(within(fdbRow).getByText(/聚合成员 · Port-channel1 · 虚拟网关 MAC/)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: '导出表格' }));
    await screen.findByText('已准备 1 条记录，请选择格式下载。');
    const csv = await blobs[1].text();
    const [header, row] = csv.replace(/^\uFEFF/, '').split('\r\n');
    expect(header).toBe('"IP","MAC","判定","判定依据","观察来源","主机名","IPAM 登记","站点","VRF","VLAN","观察设备","观察接口与路径","观察时间","证据状态"');
    expect(row.startsWith('"","00:11:22:33:44:99","仅 MAC 观察","只有 MAC 观察，没有 IP","FDB / MAC 观察（不登记 IP）"')).toBe(true);
    expect(row).toContain('"MAC 观察（未创建 IP） 范围待确认"');
    expect(row).not.toMatch(/"\d{1,3}(?:\.\d{1,3}){3}"/);

    fireEvent.click(within(fdbRow).getByRole('button', { name: '查看详情' }));
    const dialog = await screen.findByRole('dialog', { name: '终端详情' });
    expect(within(dialog).getByText('FDB / MAC 观察（不登记 IP）')).toBeTruthy();
    expect(within(dialog).getByText('待确认')).toBeTruthy();
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
    expect(screen.getByRole('columnheader', { name: 'Observation source' })).toBeTruthy();
    expect(within(endpointRow).getByText('IPv6 Neighbor Discovery (ND)')).toBeTruthy();
    fireEvent.click(within(endpointRow).getByRole('button', { name: 'View details' }));
    const dialog = await screen.findByRole('dialog', { name: 'Endpoint details' });
    expect(within(dialog).getByText('IPv6 Neighbor Discovery (ND)')).toBeTruthy();
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
