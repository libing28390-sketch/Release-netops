import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import EndpointRegistrationDialog from './EndpointRegistrationDialog';
import { canRegisterEndpoint, type DiscoveredEndpointRow } from './ipamDiscoveryPresentation';

const response = (payload: unknown, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => payload }) as Response;
const endpoint: DiscoveredEndpointRow = {
  id: 'current-arp-1', ip: '192.0.2.10', mac: '0011-2233-4455',
  tenant_id: 'tenant-1', site_id: 'site-1', site_name: 'HQ',
  observed_at: '2026-11-11T10:00:00Z', source_type: 'arp', registration_status: 'scope_pending',
};
const prefix = { id: 'prefix-1', prefix: '192.0.2.0/24', tenant_id: 'tenant-1', site_id: 'site-1', address_space_id: 'global-1', address_space_name: 'Global HQ' };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function mount(postStatus = 200, code = '') {
  const onRegistered = vi.fn();
  const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
    init?.method === 'POST' ? response({ detail: code }, postStatus) : response([
      prefix, { ...prefix, id: 'unresolved', address_space_id: '' },
      { ...prefix, id: 'other-tenant', tenant_id: 'tenant-2' },
      { ...prefix, id: 'other-site', site_id: 'site-2' },
    ]));
  vi.stubGlobal('fetch', fetcher);
  render(<MemoryRouter><EndpointRegistrationDialog item={endpoint} zh onClose={vi.fn()} onRegistered={onRegistered} /></MemoryRouter>);
  return { fetcher, onRegistered };
}

describe('current endpoint registration', () => {
  it('requires explicit prefix and scope confirmation and posts the displayed source version', async () => {
    const { fetcher, onRegistered } = mount();
    await screen.findByRole('option', { name: /Global HQ/ });
    expect(screen.getAllByRole('option')).toHaveLength(2);
    const submit = screen.getByRole('button', { name: '确认登记' }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('归属网段'), { target: { value: 'prefix-1' } });
    expect(submit.disabled).toBe(true);
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(submit);
    await waitFor(() => expect(onRegistered).toHaveBeenCalledOnce());
    const post = fetcher.mock.calls.find(call => call[1]?.method === 'POST');
    expect(post?.[0]).toBe('/api/ipam/reconciliation/register');
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({
      observation_id: endpoint.id, subnet_id: prefix.id, expected_observed_at: endpoint.observed_at, confirmed_scope: true,
    });
    expect(JSON.parse(String(post?.[1]?.body))).not.toHaveProperty('device_id');
  });

  it.each([[403, '', '当前账号没有登记此 IP 的权限。'], [409, 'observation_version_changed', '来源已更新，请刷新后重新登记。']] as const)('keeps the dialog open on %s without claiming success', async (status, code, message) => {
    const { onRegistered } = mount(status, code);
    await screen.findByRole('option', { name: /Global HQ/ });
    fireEvent.change(screen.getByLabelText('归属网段'), { target: { value: prefix.id } });
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: '确认登记' }));
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', message);
    expect(onRegistered).not.toHaveBeenCalled();
  });

  it('offers registration for current ARP/ND IPs, including scope pending, but excludes FDB, conflicts and registered rows', () => {
    expect(canRegisterEndpoint(endpoint)).toBe(true);
    expect(canRegisterEndpoint({ ...endpoint, source_type: 'ndp' })).toBe(true);
    expect(canRegisterEndpoint({ ...endpoint, source_type: 'mac', observation_source: 'fdb', ip: null })).toBe(false);
    expect(canRegisterEndpoint({ ...endpoint, evidence_status: 'stale' })).toBe(false);
    expect(canRegisterEndpoint({ ...endpoint, evidence_status: 'conflict' })).toBe(false);
    expect(canRegisterEndpoint({ ...endpoint, registration_status: 'registered' })).toBe(false);
  });
});
