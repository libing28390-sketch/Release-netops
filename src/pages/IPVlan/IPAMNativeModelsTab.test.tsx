// @vitest-environment jsdom
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import IPAMNativeModelsTab from './IPAMNativeModelsTab';

const jsonRes = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

describe('IPAMNativeModelsTab', () => {
  beforeEach(() => {
    localStorage.setItem('netops_token', 'test-token');
  });

  afterEach(() => {
    cleanup();
    localStorage.removeItem('netops_token');
    vi.unstubAllGlobals();
  });

  it('renders VLAN groups, creates a VLAN group, switches to Route Targets & saves VRF policy, and renders RIR/Aggregate/ASN', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/cmdb/sites') return jsonRes({ data: [{ id: 'site-1', site_name: 'WH-DC-01' }] });
      if (url === '/api/cmdb/vrfs') return jsonRes({ data: { items: [{ id: 'vrf-1', vrf_name: 'PROD' }] } });
      if (url === '/api/ipam/vlan-groups' && !init?.method) {
        return jsonRes({
          items: [{
            id: 'vlg-1',
            name: 'DC1-Prod',
            scope_type: 'site',
            scope_id: 'site-1',
            min_vid: 100,
            max_vid: 200,
            description: 'Prod VLANs',
            vlan_count: 2,
          }],
        });
      }
      if (url === '/api/ipam/vlan-groups' && init?.method === 'POST') {
        return jsonRes({ id: 'vlg-2', name: 'DC1-DMZ', min_vid: 300, max_vid: 400 }, 201);
      }
      if (url === '/api/ipam/route-targets' && !init?.method) {
        return jsonRes({ items: [{ id: 'rt-1', name: '65001:100', description: 'Prod RT' }] });
      }
      if (url === '/api/ipam/vrfs/vrf-1/route-targets' && !init?.method) {
        return jsonRes({ vrf_id: 'vrf-1', vrf_name: 'PROD', import_targets: [], export_targets: [] });
      }
      if (url === '/api/ipam/vrfs/vrf-1/route-targets' && init?.method === 'PUT') {
        return jsonRes({ vrf_id: 'vrf-1', vrf_name: 'PROD', import_targets: [{ id: 'rt-1', name: '65001:100' }], export_targets: [] });
      }
      if (url === '/api/ipam/rirs') return jsonRes({ items: [{ id: 'rir-1', name: 'RFC1918', is_private: true, aggregate_count: 1, asn_count: 1 }] });
      if (url === '/api/ipam/aggregates') return jsonRes({ items: [{ id: 'agg-1', prefix: '10.0.0.0/8', rir_id: 'rir-1', rir_name: 'RFC1918', child_prefix_count: 3 }] });
      if (url === '/api/ipam/asns') return jsonRes({ items: [{ id: 'asn-1', asn: 65001, rir_id: 'rir-1', rir_name: 'RFC1918', site_id: 'site-1', site_name: 'WH-DC-01' }] });
      return jsonRes({});
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<IPAMNativeModelsTab language="zh" />);

    expect(await screen.findByText('DC1-Prod')).toBeTruthy();
    expect(screen.getByText('100 - 200')).toBeTruthy();

    fireEvent.change(screen.getByPlaceholderText('分组名称（如 DC1-Prod）'), { target: { value: 'DC1-DMZ' } });
    fireEvent.click(screen.getByRole('button', { name: '新增分组' }));
    expect(await screen.findByText(/已创建 VLAN 分组 DC1-DMZ/)).toBeTruthy();

    // Switch to Route Targets tab and bind VRF
    fireEvent.click(screen.getByRole('tab', { name: /Route Targets/ }));
    expect(await screen.findByText('65001:100')).toBeTruthy();

    fireEvent.change(screen.getByRole('combobox', { name: '选择 VRF' }), { target: { value: 'vrf-1' } });
    const checkboxes = await screen.findAllByRole('checkbox');
    fireEvent.click(checkboxes[0]);
    fireEvent.click(screen.getByRole('button', { name: '保存 VRF 策略' }));
    expect(await screen.findByText('VRF Route Target 策略已保存')).toBeTruthy();

    // Switch to RIR / Aggregate / ASN tab
    fireEvent.click(screen.getByRole('tab', { name: /RIR \/ Aggregate \/ ASN/ }));
    expect(await screen.findByText('10.0.0.0/8')).toBeTruthy();
    expect(screen.getByText('AS65001')).toBeTruthy();

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([u, init]) => String(u) === '/api/ipam/vrfs/vrf-1/route-targets' && init?.method === 'PUT')).toBe(true);
    });
  });
});
