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
  it('submits the selected shared interface scope on the A endpoint', () => {
    const options: WanCircuitOptions = {
      sites: [{ id: 'site-a', site_name: 'Site A' }],
      devices: [{ id: 'device-a', site_id: 'site-a', hostname: 'router-a' }],
      interfaces: [{ id: 'interface-a', device_id: 'device-a', interface_name: 'Gi0/0', if_index: 1 }],
    };
    const onSubmit = vi.fn();
    render(<WanCircuitForm item={null} options={options} language="zh" onSubmit={onSubmit} onClose={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('线路名称'), { target: { value: 'Shared circuit' } });
    fireEvent.change(screen.getByLabelText('A 端站点'), { target: { value: 'site-a' } });
    fireEvent.change(screen.getByLabelText('A 端设备'), { target: { value: 'device-a' } });
    fireEvent.change(screen.getByLabelText('A 端接口'), { target: { value: 'interface-a' } });
    fireEvent.change(screen.getByLabelText('下行合同 Mbps'), { target: { value: '100' } });
    fireEvent.change(screen.getByLabelText('上行合同 Mbps'), { target: { value: '100' } });
    fireEvent.change(screen.getByLabelText('A 端测量范围'), { target: { value: 'shared_interface' } });
    fireEvent.change(screen.getByLabelText('非托管端点名称'), { target: { value: 'Provider handoff' } });
    fireEvent.click(screen.getByRole('button', { name: '保存线路' }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ endpoints: expect.arrayContaining([expect.objectContaining({ side: 'A', measurement_scope: 'shared_interface' })]) }));
  });
});
