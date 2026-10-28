import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import IPReconciliationTab from './IPReconciliationTab';

const response = (payload: unknown, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => payload }) as Response;
const sourceObservation = {
  observation_id: 'obs-1', ip: '10.1.1.9', mac: '00:11:22:33:44:55', observed_at: '2026-10-28T09:10:00+08:00',
  scope_status: 'resolved', evidence_status: 'recent', timestamp_status: 'valid', calibration_safe: true, site_name: 'WH-DC-01', vrf_name: 'PROD', source_device_name: 'SW-01',
};
const baseSummary = {
  total_undocumented: 1, total_mismatched: 1, total_stale: 0, total_never_observed: 1, total_unscoped: 0, total_unavailable: 0,
  allocated_ipam_address_count: 12, active_endpoint_count: 10, interface_snapshot_ip_count: 55,
  coverage_status: 'complete', coverage_reason: '', latest_active_endpoint_seen: '2026-10-28T09:10:00+08:00',
};

const renderPage = () => render(<MemoryRouter><IPReconciliationTab language="zh" t={(key) => key} /></MemoryRouter>);

describe('IPReconciliationTab', () => {
  beforeEach(() => {
    localStorage.setItem('netops_token', 'test-token');
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/ipam/reconciliation?')) {
        const activeTab = new URL(url, 'http://localhost').searchParams.get('active_tab');
        const payload: Record<string, unknown> = { summary: baseSummary, result_total: 0 };
        if (activeTab === 'undocumented') {
          payload.undocumented_endpoints = [sourceObservation];
          payload.result_total = 1;
        }
        if (activeTab === 'mismatched') {
          payload.mismatched_endpoints = [{ ...sourceObservation, ipam_address_id: 'address-1', ipam_mac: '00:11:22:33:44:66', observed_mac: sourceObservation.mac, mac_mismatch: true }];
          payload.result_total = 1;
        }
        if (activeTab === 'stale') {
          payload.stale_ip_addresses = [{ ipam_address_id: 'address-stale', ip: '10.1.1.99', last_observed_at: '2026-10-01T09:10:00Z', miss_count: 3, required_misses: 3, subnet_prefix: '10.1.1.0/24' }];
          payload.result_total = 1;
        }
        if (activeTab === 'never_observed') {
          payload.never_observed = [{ ipam_address_id: 'address-never', ip: '10.1.1.88', last_observed_at: null, subnet_prefix: '10.1.1.0/24' }];
          payload.result_total = 1;
        }
        return response(payload);
      }
      if (url === '/api/ipam/subnets') return response([{ id: 'subnet-1', prefix: '10.1.1.0/24', site_id: 'site-1', site_name: 'WH-DC-01', vrf_id: 'vrf-1', vrf_name: 'PROD' }]);
      if (url === '/api/ipam/reconciliation/register' || url === '/api/ipam/reconciliation/calibrate') return response({ ok: true });
      if (url === '/api/ipam/endpoints/obs-1') return response({ ...sourceObservation, observations: [{ source_type: 'arp', observed_at: sourceObservation.observed_at, source_version: 'v3' }] });
      return response({});
    }));
  });

  afterEach(() => {
    cleanup();
    localStorage.removeItem('netops_token');
    vi.unstubAllGlobals();
  });

  it('renders all six categories, uses server pagination, and does not expose IP release', async () => {
    renderPage();
    expect(await screen.findByText('10.1.1.9')).toBeTruthy();
    for (const name of ['发现未登记', '信息不一致', '长期未发现', '登记后未观察', '归属待确认', '来源不可用']) {
      expect(screen.getByRole('button', { name: new RegExp(name) })).toBeTruthy();
    }
    expect(screen.queryByText(/接口快照 IP（不纳入对账）/)).toBeNull();
    expect(screen.getByText(/IPAM 已登记 IP/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /释放此 IP|Release IP/ })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: /长期未发现/ }));
    expect(await screen.findByText('10.1.1.99')).toBeTruthy();
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).includes('active_tab=stale'))).toBe(true));
  });

  it('requires explicit prefix and scope confirmation before registering an observation with version guards', async () => {
    renderPage();
    await screen.findByText('10.1.1.9');
    fireEvent.click(screen.getByRole('button', { name: '登记到 IPAM' }));
    const dialog = await screen.findByRole('dialog', { name: '登记观察到的 IP' });
    const prefix = within(dialog).getByRole('combobox', { name: '目标 IPAM 网段' });
    fireEvent.change(prefix, { target: { value: 'subnet-1' } });
    fireEvent.click(screen.getByRole('checkbox', { name: /我已核对来源/ }));
    fireEvent.click(screen.getByRole('button', { name: '确认登记' }));

    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([input, init]) => String(input) === '/api/ipam/reconciliation/register' && init?.method === 'POST')).toBe(true));
    const request = vi.mocked(fetch).mock.calls.find(([input]) => String(input) === '/api/ipam/reconciliation/register');
    expect(JSON.parse(String(request?.[1]?.body))).toEqual({ observation_id: 'obs-1', subnet_id: 'subnet-1', expected_observed_at: sourceObservation.observed_at, confirmed_scope: true });
    expect((await screen.findByRole('status')).textContent).toContain('已登记 IP 10.1.1.9');
  });

  it('keeps the registration preview open when the source version is stale', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/ipam/reconciliation?')) return response({ summary: baseSummary, undocumented_endpoints: [sourceObservation], result_total: 1 });
      if (url === '/api/ipam/subnets') return response([{ id: 'subnet-1', prefix: '10.1.1.0/24', site_id: 'site-1', site_name: 'WH-DC-01' }]);
      if (url === '/api/ipam/reconciliation/register') return response({ detail: 'Observation changed after review' }, 409);
      return response({});
    }));
    renderPage();
    await screen.findByText('10.1.1.9');
    fireEvent.click(screen.getByRole('button', { name: '登记到 IPAM' }));
    const dialog = await screen.findByRole('dialog', { name: '登记观察到的 IP' });
    fireEvent.change(within(dialog).getByRole('combobox', { name: '目标 IPAM 网段' }), { target: { value: 'subnet-1' } });
    fireEvent.click(within(dialog).getByRole('checkbox', { name: /我已核对来源/ }));
    fireEvent.click(within(dialog).getByRole('button', { name: '确认登记' }));
    expect((await within(dialog).findByRole('alert')).textContent).toContain('Observation changed after review');
    expect(screen.getByRole('dialog', { name: '登记观察到的 IP' })).toBeTruthy();
    expect((within(dialog).getByRole('combobox', { name: '目标 IPAM 网段' }) as HTMLSelectElement).value).toBe('subnet-1');
  });

  it('offers guarded MAC-only calibration only for current resolved ARP evidence', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/ipam/reconciliation?')) {
        const activeTab = new URL(url, 'http://localhost').searchParams.get('active_tab');
        return response({
          summary: baseSummary,
          result_total: activeTab === 'mismatched' ? 1 : 0,
          mismatched_endpoints: activeTab === 'mismatched' ? [{
            ...sourceObservation, ipam_address_id: 'address-1', ipam_mac: '00:11:22:33:44:66', observed_mac: sourceObservation.mac,
            mac_mismatch: true, scope_status: 'resolved', evidence_status: 'recent', timestamp_status: 'valid', calibration_safe: true,
          }] : [],
        });
      }
      if (url === '/api/ipam/reconciliation/calibrate') return response({ ok: true });
      return response({});
    });
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: /信息不一致/ }));
    expect(await screen.findByText('00:11:22:33:44:66')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '校准 MAC' }));
    fireEvent.click(screen.getByRole('checkbox', { name: /我确认仅将 IPAM 登记 MAC/ }));
    fireEvent.click(screen.getByRole('button', { name: '确认校准 MAC' }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input) === '/api/ipam/reconciliation/calibrate')).toBe(true));
    const request = fetchMock.mock.calls.find(([input]) => String(input) === '/api/ipam/reconciliation/calibrate');
    expect(JSON.parse(String(request?.[1]?.body))).toEqual({
      observation_id: 'obs-1', ipam_address_id: 'address-1', expected_observed_at: sourceObservation.observed_at,
      expected_mac_address: '00:11:22:33:44:66', confirmed: true,
    });
  });

  it('shows authorization errors without describing an empty result as a clean reconciliation', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => String(input).startsWith('/api/ipam/reconciliation?')
      ? response({ detail: 'forbidden' }, 403)
      : response({})));
    renderPage();
    expect((await screen.findByRole('alert')).textContent).toContain('当前账号没有权限执行此 IPAM 操作');
    expect(screen.queryByText('未发现漏登记 IP。')).toBeNull();
  });
});
