import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { WanCircuitForm } from '../components/wan-circuits/WanCircuitForm';
import type { WanCircuitOptions } from '../types/wan-circuits';
import WanCircuitsPage from './WanCircuitsPage';

vi.mock('../contexts/AppDomainContext', () => ({
  useCoreApp: () => ({ language: 'zh', showToast: vi.fn(), currentUser: { role: 'Operator' } }),
}));

const response = (body: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: vi.fn().mockResolvedValue(body),
}) as unknown as Response;

describe('WanCircuitsPage deep links', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/wan-options')) return Promise.resolve(response({ devices: [], interfaces: [], sites: [] }));
      if (url.includes('/outbound-targets')) return Promise.resolve(response({ items: [{ id: 'target-1', target_name: 'Public DNS', host: '1.1.1.1', probe_type: 'ICMP_PING', is_active: true }], total: 1 }));
      if (url.includes('/wan-probe-bindings?')) return Promise.resolve(response({ items: [{ id: 'binding-1', link_id: 'deep-circuit', target_id: 'target-1', target_name: 'Public DNS', host: '1.1.1.1', probe_type: 'ICMP_PING', purpose: 'availability', route_mode: 'source_ip', source_ip: '192.0.2.10', priority: 10, enabled: true, route_evidence: { evidence_status: 'insufficient_capability' } }] }));
      if (url.includes('/wan-links/deep-circuit/sla-policy')) return Promise.resolve(response({ success: true, item: { policy_version: 1, policy: { availability_target_pct: 99.9 } } }));
      if (url.includes('/wan-links/deep-circuit/history')) return Promise.resolve(response({ history: [], events: [], start_time: null, end_time: null }));
      if (url.includes('/wan-links/deep-circuit/sla')) return Promise.resolve(response({ status: 'insufficient_data', reason_code: 'path_evidence_unavailable', availability_pct: null, availability: { value: null, lower_bound: null, upper_bound: null }, coverage_pct: null, slots: 0 }));
      if (url.includes('/wan-links/deep-circuit')) return Promise.resolve(response({ item: { id: 'deep-circuit', link_name: 'Deep circuit', site_id: 'site-1', site_name: '深链站点', device_id: 'device-1', interface_id: 'interface-1', interface_name: 'Gi0/0', if_index: 1, contracted_download_bps: 1000000, contracted_upload_bps: 1000000, endpoints: [{ side: 'A', endpoint_type: 'managed', site_id: 'site-1', device_id: 'device-1', interface_id: 'interface-1', endpoint_name: 'Gi0/0', counter_orientation: 'normal', measurement_scope: 'shared_interface' }, { side: 'Z', endpoint_type: 'unmanaged', site_id: 'site-1', endpoint_name: 'Provider handoff', counter_orientation: 'normal', measurement_scope: 'dedicated' }] } }));
      if (url.includes('/wan-links?')) return Promise.resolve(response({ items: [], total: 0, page: 1, page_size: 20, summary: { total: 0, healthy: 0, risky: 0, active_alerts: 0 } }));
      return Promise.resolve(response({}));
    }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('keeps a deep-linked selection when the current list page is empty', async () => {
    render(<MemoryRouter initialEntries={['/monitor/circuits/deep-circuit']}><WanCircuitsPage /></MemoryRouter>);

    expect(await screen.findByText('Deep circuit')).toBeTruthy();
    await waitFor(() => expect(screen.getByText(/Provider handoff/)).toBeTruthy());
    expect(await screen.findByText(/共享物理接口/)).toBeTruthy();
    expect(await screen.findByText(/能力不足/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '编辑绑定' }));
    expect((screen.getByRole('option', { name: /应用/ }) as HTMLOptionElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('探针用途'), { target: { value: 'quality' } });
    fireEvent.click(screen.getByRole('button', { name: '保存修改' }));
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([input, init]) => String(input).includes('/wan-probe-bindings/binding-1') && init?.method === 'PATCH' && JSON.parse(String(init.body)).purpose === 'quality')).toBe(true));
    fireEvent.click(screen.getByRole('button', { name: '编辑策略' }));
    fireEvent.click(screen.getByRole('button', { name: '保存策略' }));
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([input, init]) => String(input).includes('/sla-policy') && init?.method === 'PUT' && JSON.parse(String(init.body)).expected_version === 0)).toBe(true));
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).includes('/wan-links/deep-circuit'))).toBe(true);
  });
});

describe('WanCircuitForm measurement scope', () => {
  afterEach(() => cleanup());

  it('submits the selected shared interface scope on the A endpoint', async () => {
    const options: WanCircuitOptions = {
      sites: [{ id: 'site-a', site_name: 'Site A', timezone: 'Asia/Tokyo' }],
      devices: [{ id: 'device-a', site_id: 'site-a', hostname: 'router-a' }],
      interfaces: [
        { id: 'interface-a', device_id: 'device-a', interface_name: 'Gi0/0', if_index: 1 },
        { id: 'interface-unverified', device_id: 'device-a', interface_name: 'Et0/1', if_index: null },
      ],
    };
    const onSubmit = vi.fn();
    render(<WanCircuitForm item={null} options={options} language="zh" onRefreshDeviceInterfaces={vi.fn().mockResolvedValue(undefined)} onSubmit={onSubmit} onClose={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/线路名称/), { target: { value: 'Shared circuit' } });
    fireEvent.change(screen.getByLabelText('本端站点 *'), { target: { value: 'site-a' } });
    expect(screen.getByText(/当前线路时区：Asia\/Tokyo/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('本端设备 *'), { target: { value: 'device-a' } });
    await waitFor(() => expect((screen.getByLabelText('本端连接专线的端口 *') as HTMLSelectElement).disabled).toBe(false));
    fireEvent.change(screen.getByLabelText('本端连接专线的端口 *'), { target: { value: 'interface-a' } });
    expect(screen.queryByRole('option', { name: /Et0\/1/ })).toBeNull();
    expect(screen.getByText(/Site A · router-a · Gi0\/0/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('双向对称带宽（Mbps）'), { target: { value: '100' } });
    expect(screen.getByText('监控设置（可选）').closest('details')?.open).toBe(false);
    fireEvent.click(screen.getByText('监控设置（可选）'));
    fireEvent.click(screen.getByLabelText('为这条线路单独设置时区'));
    fireEvent.change(screen.getByLabelText('线路时区'), { target: { value: 'Asia/Shanghai' } });
    fireEvent.change(screen.getByLabelText('本端（A 端）接口是否只承载本专线？'), { target: { value: 'shared_interface' } });
    expect(screen.getByText(/设备只能提供整个端口的合计流量/)).toBeTruthy();
    expect(screen.queryByLabelText('对端（Z 端）端口计数方向')).toBeNull();
    fireEvent.change(screen.getByLabelText('对端名称 *'), { target: { value: 'Provider handoff' } });
    fireEvent.click(screen.getByRole('button', { name: '保存线路' }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      link_role: 'standalone',
      timezone: 'Asia/Shanghai',
      contracted_download_mbps: 100,
      contracted_upload_mbps: 100,
      endpoints: expect.arrayContaining([expect.objectContaining({ side: 'A', measurement_scope: 'shared_interface' })]),
    }));
  });

  it('maps asymmetric bandwidth to remote-to-local download and local-to-remote upload', async () => {
    const options: WanCircuitOptions = {
      sites: [{ id: 'site-a', site_name: 'Site A', timezone: 'Asia/Shanghai' }],
      devices: [{ id: 'device-a', site_id: 'site-a', hostname: 'router-a' }],
      interfaces: [{ id: 'interface-a', device_id: 'device-a', interface_name: 'Gi0/0', if_index: 7 }],
    };
    const onSubmit = vi.fn();
    render(<WanCircuitForm item={null} options={options} language="zh" onRefreshDeviceInterfaces={vi.fn().mockResolvedValue(undefined)} onSubmit={onSubmit} onClose={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(/线路名称/), { target: { value: 'Asymmetric circuit' } });
    fireEvent.change(screen.getByLabelText('线路用途'), { target: { value: 'MPLS' } });
    fireEvent.change(screen.getByLabelText('冗余角色'), { target: { value: 'backup' } });
    fireEvent.change(screen.getByLabelText('本端站点 *'), { target: { value: 'site-a' } });
    fireEvent.change(screen.getByLabelText('本端设备 *'), { target: { value: 'device-a' } });
    fireEvent.change(screen.getByLabelText('本端连接专线的端口 *'), { target: { value: 'interface-a' } });
    fireEvent.change(screen.getByLabelText('对端名称 *'), { target: { value: 'Carrier handoff' } });
    fireEvent.click(screen.getByLabelText('上下行合同带宽不同（非对称）'));
    fireEvent.change(screen.getByLabelText('对端 → 本端（Z→A，下行 Mbps）'), { target: { value: '200' } });
    fireEvent.change(screen.getByLabelText('本端 → 对端（A→Z，上行 Mbps）'), { target: { value: '100' } });
    fireEvent.click(screen.getByRole('button', { name: '保存线路' }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      link_type: 'MPLS',
      link_role: 'backup',
      contracted_download_mbps: 200,
      contracted_upload_mbps: 100,
    }));
  });

  it('explains when the selected device has no verified SNMP interfaces', async () => {
    const options: WanCircuitOptions = {
      sites: [{ id: 'site-a', site_name: 'Site A' }],
      devices: [{ id: 'device-a', site_id: 'site-a', hostname: 'router-a' }],
      interfaces: [{ id: 'interface-unverified', device_id: 'device-a', interface_name: 'Et0/1', if_index: null }],
    };
    const onRefreshDeviceInterfaces = vi.fn().mockResolvedValue(undefined);
    render(<WanCircuitForm item={null} options={options} language="zh" onRefreshDeviceInterfaces={onRefreshDeviceInterfaces} onSubmit={vi.fn()} onClose={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('本端站点 *'), { target: { value: 'site-a' } });
    fireEvent.change(screen.getByLabelText('本端设备 *'), { target: { value: 'device-a' } });

    expect(onRefreshDeviceInterfaces).toHaveBeenCalledWith('device-a', 'create');
    expect((await screen.findByRole('status')).textContent).toContain('SNMP 只读凭据和 IF-MIB 只读权限');
    expect(screen.queryByRole('option', { name: /Et0\/1/ })).toBeNull();
  });

  it('explains endpoint type and shows collection settings only for a managed remote device', () => {
    const options: WanCircuitOptions = {
      sites: [{ id: 'site-a', site_name: 'Site A' }],
      devices: [{ id: 'device-a', site_id: 'site-a', hostname: 'router-a' }],
      interfaces: [{ id: 'interface-a', device_id: 'device-a', interface_name: 'Gi0/0', if_index: 1 }],
    };
    const onRefreshDeviceInterfaces = vi.fn().mockResolvedValue(undefined);
    render(<WanCircuitForm item={null} options={options} language="zh" onRefreshDeviceInterfaces={onRefreshDeviceInterfaces} onSubmit={vi.fn()} onClose={vi.fn()} />);

    expect(screen.getByText(/A、Z 只是线路两端的代号，不代表上行或下行/)).toBeTruthy();
    expect(screen.getByText(/与本端结构一致；差别只在于对端是否由本系统纳管/)).toBeTruthy();
    expect(screen.queryByLabelText('对端（Z 端）端口计数方向')).toBeNull();
    expect(screen.queryByLabelText('对端（Z 端）接口是否只承载本专线？')).toBeNull();

    fireEvent.change(screen.getByLabelText('对端类型'), { target: { value: 'managed' } });
    expect(screen.getByText('监控设置（可选）').closest('details')?.open).toBe(false);
    fireEvent.click(screen.getByText('监控设置（可选）'));
    expect(screen.getByLabelText('对端（Z 端）端口计数方向')).toBeTruthy();
    expect(screen.getByLabelText('对端（Z 端）接口是否只承载本专线？')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('对端站点 *'), { target: { value: 'site-a' } });
    fireEvent.change(screen.getByLabelText('对端设备 *'), { target: { value: 'device-a' } });
    expect(onRefreshDeviceInterfaces).toHaveBeenCalledWith('device-a', 'create');
  });
});

describe('WanCircuitsPage interface auto refresh', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes('/interfaces/refresh') && init?.method === 'POST') {
        return Promise.resolve(response({
          success: true,
          interfaces: [{ id: 'interface-live', device_id: 'device-a', interface_name: 'Gi0/0', if_index: 17 }],
          total: 1,
        }));
      }
      if (url.includes('/wan-options')) {
        return Promise.resolve(response({
          sites: [{ id: 'site-a', site_name: '总部', timezone: 'Asia/Shanghai' }],
          devices: [{ id: 'device-a', site_id: 'site-a', hostname: 'edge-router' }],
          interfaces: [],
        }));
      }
      if (url.includes('/wan-links?')) return Promise.resolve(response({ items: [], total: 0, page: 1, page_size: 20, summary: {} }));
      return Promise.resolve(response({}));
    }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('automatically refreshes selected device ports and displays the returned interface name', async () => {
    render(<MemoryRouter initialEntries={['/monitor/circuits']}><WanCircuitsPage /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: '注册线路' }));
    fireEvent.change(screen.getByLabelText('本端站点 *'), { target: { value: 'site-a' } });
    fireEvent.change(screen.getByLabelText('本端设备 *'), { target: { value: 'device-a' } });

    expect(await screen.findByRole('option', { name: 'Gi0/0' })).toBeTruthy();
    expect(vi.mocked(fetch).mock.calls.some(([input, init]) => String(input).includes('/wan-options/devices/device-a/interfaces/refresh?action=create') && init?.method === 'POST')).toBe(true);
  });
});
