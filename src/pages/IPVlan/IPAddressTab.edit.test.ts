import { describe, expect, it, vi } from 'vitest';
import {
  buildNextAvailableIpUrl,
  filterAllocatableAddressPools,
  fetchRegisteredAddressForEdit,
  formatPendingDiscoveryWarning,
  getIPAddressDeviceAssignmentDisplay,
  getIPAddressReadOnlyDisplayFields,
  observedPrefixScopeLabel,
} from './IPAddressTab';

const jsonResponse = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status,
  headers: { 'Content-Type': 'application/json' },
});

const mixedInventoryRow = {
  id: 'registered-1',
  revision: 3,
  subnet_id: 'prefix-1',
  address: '10.20.0.15',
  source: 'manual+discovered',
  hostname: 'observed-host',
  device_id: 'observed-switch',
  interface_name: 'GigabitEthernet1/0/2',
  mac_address: '00:11:22:33:44:55',
};

describe('IP address edit source', () => {
  it('only offers active, explicitly eligible local-static pools', () => {
    const options = filterAllocatableAddressPools([
      { id: 'eligible', name: 'Static', status: 'active', management_mode: 'local_static', allocation_allowed: true, mark_populated: false, policy_pending: false, start_ip: '10.0.0.10', end_ip: '10.0.0.20' },
      { id: 'reserved', status: 'reserved', management_mode: 'local_static', allocation_allowed: true, mark_populated: false, policy_pending: false },
      { id: 'external', status: 'active', management_mode: 'external_dhcp', allocation_allowed: true, mark_populated: false, policy_pending: false },
      { id: 'disabled', status: 'active', management_mode: 'local_static', allocation_allowed: false, mark_populated: false, policy_pending: false },
      { id: 'populated', status: 'active', management_mode: 'local_static', allocation_allowed: true, mark_populated: true, policy_pending: false },
      { id: 'pending', status: 'active', management_mode: 'local_static', allocation_allowed: true, mark_populated: false, policy_pending: true },
      { id: 'unknown-flags', status: 'active', management_mode: 'local_static', allocation_allowed: true, mark_populated: null, policy_pending: false },
    ]);

    expect(options.map((pool) => pool.id)).toEqual(['eligible']);
  });

  it('adds the selected pool ID to the bounded recommendation request only when selected', () => {
    expect(buildNextAvailableIpUrl('prefix-1')).toBe('/api/ipam/subnets/prefix-1/next-available-ip');
    expect(buildNextAvailableIpUrl('prefix-1', 'pool-7')).toBe('/api/ipam/subnets/prefix-1/next-available-ip?pool_id=pool-7');
  });

  it('loads the registered-only inventory and selects the exact persisted ID', async () => {
    const registeredRecord = {
      ...mixedInventoryRow,
      source: 'manual',
      hostname: '',
      device_id: '',
      interface_name: '',
      mac_address: '',
      status: 'active',
      purpose: 'business',
      device_type: 'server',
      description: 'ledger owner',
    };
    const fetcher = vi.fn(async () => jsonResponse({
      items: [
        { ...registeredRecord, id: 'another-record' },
        registeredRecord,
      ],
    }));

    const result = await fetchRegisteredAddressForEdit(mixedInventoryRow, {
      headers: { Authorization: 'Bearer test-token' },
      fetcher: fetcher as unknown as typeof fetch,
    });

    expect(result).toEqual(registeredRecord);
    const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    const query = new URL(url, 'http://localhost').searchParams;
    expect(query.get('registered_only')).toBe('true');
    expect(query.get('site_id')).toBe('all');
    expect(query.get('prefix_id')).toBe('prefix-1');
    expect(query.get('q')).toBe('10.20.0.15');
    expect(query.get('page')).toBe('1');
    expect(query.get('page_size')).toBe('100');
    expect(init.headers).toEqual({ Authorization: 'Bearer test-token' });
  });

  it('stops when the registered ID is missing instead of using mixed inventory values', async () => {
    const fetcher = vi.fn(async () => jsonResponse({ items: [] }));

    await expect(fetchRegisteredAddressForEdit(mixedInventoryRow, {
      fetcher: fetcher as unknown as typeof fetch,
    })).rejects.toMatchObject({ reason: 'missing' });
  });

  it('stops editing when the registered row has no usable revision', async () => {
    const fetcher = vi.fn(async () => jsonResponse({ items: [{ ...mixedInventoryRow, revision: undefined }] }));

    await expect(fetchRegisteredAddressForEdit(mixedInventoryRow, {
      fetcher: fetcher as unknown as typeof fetch,
    })).rejects.toMatchObject({ reason: 'invalid_response' });
  });

  it('preserves permission status for the page to show a localized access error', async () => {
    const fetcher = vi.fn(async () => jsonResponse({ detail: 'forbidden' }, 403));

    await expect(fetchRegisteredAddressForEdit(mixedInventoryRow, {
      fetcher: fetcher as unknown as typeof fetch,
    })).rejects.toMatchObject({ reason: 'http', status: 403 });
  });

  it('shows observed host, switch port, and MAC as read-only display fallbacks', () => {
    expect(getIPAddressReadOnlyDisplayFields({
      hostname: '',
      interface_name: '',
      switch_name: '',
      switch_port: '',
      mac_address: '',
      observed_hostname: 'observed-host',
      observed_switch_name: 'access-sw-01',
      observed_switch_port: 'GigabitEthernet1/0/2',
      observed_mac_address: '00:11:22:33:44:55',
    })).toEqual({
      hostname: 'observed-host',
      switchName: 'access-sw-01',
      switchPort: 'GigabitEthernet1/0/2',
      macAddress: '00:11:22:33:44:55',
    });
  });

  it('labels the IPAM assignment separately from the observed access switch', () => {
    expect(getIPAddressDeviceAssignmentDisplay({
      device_id: '',
      bound_device_hostname: '',
      asset_hostname: '',
      switch_name: '',
      observed_switch_name: 'access-sw-01',
      source: 'manual+discovered',
      is_discovered: false,
    }, true)).toBe('登记: 未绑定 · 接入: access-sw-01');
    expect(getIPAddressDeviceAssignmentDisplay({
      device_id: 'device-server',
      bound_device_hostname: 'app-01',
      asset_hostname: '',
      switch_name: '',
      observed_switch_name: 'access-sw-01',
      source: 'manual+discovered',
      is_discovered: false,
    }, true)).toBe('登记: app-01 · 接入: access-sw-01');
    expect(getIPAddressDeviceAssignmentDisplay({
      device_id: 'observed-switch-id',
      bound_device_hostname: 'access-sw-01',
      asset_hostname: '',
      switch_name: 'access-sw-01',
      observed_switch_name: 'access-sw-01',
      source: 'discovered',
      is_discovered: true,
    }, true)).toBe('登记: 未登记 · 接入: access-sw-01');
  });

  it('does not label an interface snapshot without VRF as global', () => {
    expect(observedPrefixScopeLabel('vrf_unavailable', true)).toBe('VRF 待确认');
    expect(observedPrefixScopeLabel('unmatched', true)).toBe('未匹配网段');
    expect(observedPrefixScopeLabel('global_default', true)).toBe('全局/默认');
    expect(observedPrefixScopeLabel('scope_pending', true)).toBe('地址空间待确认');
    expect(observedPrefixScopeLabel('matched', true)).toBe('已匹配地址空间内网段');
    expect(observedPrefixScopeLabel(undefined, true)).toBe('地址空间待确认');
    expect(observedPrefixScopeLabel('scope_pending', false)).toBe('Address space needs confirmation');
  });

  it('identifies an interface observation device without calling it an endpoint access switch', () => {
    expect(getIPAddressDeviceAssignmentDisplay({
      device_id: 'router-1', bound_device_hostname: 'router-a',
      switch_name: 'router-a', source: 'interface_cli', is_discovered: true,
    }, true)).toBe('采集设备: router-a · IPAM 未登记');
    expect(getIPAddressDeviceAssignmentDisplay({
      device_id: 'router-1', source: 'interface_cli', is_discovered: true,
    }, false)).toBe('Collected device: router-1 · Not registered in IPAM');
  });

  it('explains how many current-page IP observations are temporarily reserved', () => {
    expect(formatPendingDiscoveryWarning(0, true)).toBe('');
    expect(formatPendingDiscoveryWarning(3, true)).toContain('当前页面中另有 3 个');
    expect(formatPendingDiscoveryWarning(2, false)).toContain('2 IP observations currently shown');
  });
});
