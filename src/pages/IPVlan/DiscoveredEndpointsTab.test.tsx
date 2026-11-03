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
        summary: { discovered_ip_count: 1, mac_only_count: 0, registered_count: 0, unregistered_count: 1, scope_pending_count: 0, conflict_count: 0, coverage_status: 'partial', coverage_reason: '部分来源缺少范围', source_last_success_at: '2026-10-29T09:00:00+08:00' },
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
    expect(screen.getByRole('columnheader', { name: '接入设备' })).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: '接入端口' })).toBeTruthy();
    const endpointRow = screen.getByRole('row', { name: /10\.10\.1\.21/ });
    expect(endpointRow.querySelectorAll('td')).toHaveLength(11);
    expect(within(endpointRow).getByText('WH-DC-01')).toBeTruthy();
    expect(within(endpointRow).getByText('PROD')).toBeTruthy();
    expect(within(endpointRow).getByText('SW-01')).toBeTruthy();
    expect(endpointRow.querySelectorAll('td')[8].textContent).toBe('');
    expect(endpointRow.querySelectorAll('td')[8].hasAttribute('title')).toBe(false);
    expect(screen.queryByText(/ARP 来源/)).toBeNull();
    expect(screen.queryByText('—')).toBeNull();
    expect(screen.queryByText('未知')).toBeNull();
    expect(screen.getByRole('button', { name: '搜索' }).closest('form')?.className).toContain('items-end');
    expect(container.querySelector('.nx-data-table-frame')).not.toBeNull();
    expect(screen.queryByRole('status')).toBeNull();
    expect(screen.getByRole('button', { name: '刷新' })).toBeTruthy();
    expect(container.querySelector('svg.lucide-terminal')).not.toBeNull();
    expect(screen.queryByText('类型未知')).toBeNull();
    expect(screen.getByText('IP发现记录')).toBeTruthy();
    const summary = screen.getByRole('region', { name: '发现摘要' });
    expect(within(summary).getByText('已登记')).toBeTruthy();
    expect(within(summary).getByText('未登记')).toBeTruthy();
    expect(within(summary).queryByText('仅 MAC 记录')).toBeNull();
    expect(screen.queryByText('源采集最近成功')).toBeNull();
    expect(screen.getByText('更多筛选').closest('details')?.open).toBe(false);

    const fetchMock = vi.mocked(fetch);
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes('/api/ipam/endpoints?kind=ip&network_scope=business_vlan'))).toBe(true);
    expect(fetchMock.mock.calls.some(([input]) => String(input).startsWith('/api/devices?'))).toBe(false);

    fireEvent.click(screen.getByRole('button', { name: '查看详情' }));
    expect(await screen.findByRole('dialog', { name: '终端详情' })).toBeTruthy();
    expect(screen.queryByText(/run-17/)).toBeNull();
    expect(screen.getByRole('columnheader', { name: /^IP$/ })).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: /^MAC$/ })).toBeTruthy();
    expect(within(screen.getByRole('dialog')).getByText('接入端口')).toBeTruthy();
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
    expect(header).toBe('"IP","MAC","主机名","IPAM 登记","站点","VRF","VLAN","接入设备","接入端口","观察时间","证据状态"');
    expect(row).toContain('"WH-DC-01","PROD","20","SW-01",""');
  });

  it('leaves missing list and detail values blank', async () => {
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
    expect(cells).toHaveLength(11);
    for (const index of [0, 1, 2, 4, 5, 6, 7, 8, 9]) expect(cells[index].textContent).toBe('');
    expect(cells[3].textContent).toContain('未登记');
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
      { label: 'VLAN', value: '' },
      { label: '站点', value: '' },
      { label: '来源设备', value: '' },
      { label: '接入设备', value: '' },
      { label: '接入端口', value: '' },
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
    const vrfCell = screen.getByRole('row', { name: /10\.10\.1\.21/ }).querySelectorAll('td')[5];
    expect(vrfCell.textContent).toBe('');
    expect(vrfCell.hasAttribute('title')).toBe(false);

    fireEvent.click(screen.getByRole('button', { name: '导出表格' }));
    await screen.findByText('已准备 1 条记录，请选择格式下载。');
    const csv = await blobs[1].text();
    const [, row] = csv.replace(/^\uFEFF/, '').split('\r\n');
    expect(row).toContain('"WH-DC-01","","20"');
    expect(csv).not.toContain('全局/默认');
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
