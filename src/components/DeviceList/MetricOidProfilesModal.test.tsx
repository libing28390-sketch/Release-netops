import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { apiRequest } from '../../api/http';
import MetricOidProfilesModal from './MetricOidProfilesModal';

vi.mock('../../api/http', () => ({
  apiRequest: vi.fn(),
}));

const mockedApiRequest = vi.mocked(apiRequest);

describe('MetricOidProfilesModal editor', () => {
  beforeEach(() => {
    mockedApiRequest.mockResolvedValue({
      success: true,
      data: [],
      total: 0,
      page: 1,
      page_size: 20,
      total_pages: 0,
    } as never);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('starts with only common metrics and keeps optional metrics behind Add metric', async () => {
    const user = userEvent.setup();
    render(
      <MetricOidProfilesModal
        open
        language="en"
        onClose={vi.fn()}
        onChanged={vi.fn()}
        showToast={vi.fn()}
      />,
    );

    await waitFor(() => expect(mockedApiRequest).toHaveBeenCalled());
    await user.click(screen.getByRole('button', { name: 'New Profile' }));

    expect(screen.getAllByRole('row')).toHaveLength(3);
    expect(screen.getByText('CPU')).toBeTruthy();
    expect(screen.getByText('Memory')).toBeTruthy();
    expect(screen.getAllByRole('button', { name: 'New Profile' })).toHaveLength(1);

    await user.selectOptions(screen.getByRole('combobox', { name: 'Metric to add' }), 'temperature');
    await user.click(screen.getByRole('button', { name: 'Add Metric' }));
    expect(screen.getAllByRole('row')).toHaveLength(4);
    expect(screen.getByText('Temperature')).toBeTruthy();
  });

  it('hides optional row and calculation fields until Advanced settings is opened', async () => {
    const user = userEvent.setup();
    render(
      <MetricOidProfilesModal
        open
        language="en"
        onClose={vi.fn()}
        showToast={vi.fn()}
      />,
    );

    await waitFor(() => expect(mockedApiRequest).toHaveBeenCalled());
    await user.click(screen.getByRole('button', { name: 'New Profile' }));
    expect(screen.queryByPlaceholderText('1 or 1.2')).toBeNull();

    const advancedButtons = screen.getAllByRole('button', { name: /Advanced calculation/ });
    expect(advancedButtons).toHaveLength(2);
    await user.click(advancedButtons[0]);

    expect(screen.getByPlaceholderText('1 or 1.2')).toBeTruthy();
    expect(screen.getAllByText('Aggregation')).toHaveLength(1);
    expect(screen.getByText('Scale multiplier')).toBeTruthy();
    expect(screen.getByText('Offset')).toBeTruthy();
  });

  it('confirms the target IP only after Enter and does not render a community field', async () => {
    const user = userEvent.setup();
    mockedApiRequest.mockImplementation(async (url) => {
      if (String(url).startsWith('/api/platform-registry/snmp-walk-target')) {
        return { success: true, data: { ip: '10.254.0.1', device_id: 'device-1', hostname: 'edge-01' } } as never;
      }
      return { success: true, data: [], total: 0, page: 1, page_size: 20, total_pages: 0 } as never;
    });
    render(
      <MetricOidProfilesModal
        open
        language="en"
        onClose={vi.fn()}
        showToast={vi.fn()}
      />,
    );

    await waitFor(() => expect(mockedApiRequest).toHaveBeenCalled());
    await user.click(screen.getByRole('button', { name: 'New Profile' }));
    await user.click(screen.getByRole('button', { name: 'Live Walk & Test Toolkit' }));
    const targetInput = screen.getByPlaceholderText('10.254.0.1');
    await user.type(targetInput, '10.254.0.1');
    expect(mockedApiRequest).not.toHaveBeenCalledWith(expect.stringContaining('/api/platform-registry/snmp-walk-target'), expect.anything());
    await user.keyboard('{Enter}');

    await waitFor(() => expect(mockedApiRequest.mock.calls.some(([url]) => url === '/api/platform-registry/snmp-walk-target?ip=10.254.0.1')).toBe(true));
    expect(screen.queryByRole('textbox', { name: /community/i })).toBeNull();
    expect(screen.getByText(/Matched: edge-01/)).toBeTruthy();
  });

  it('validates the enabled interface OIDs against the confirmed SNMP target', async () => {
    const user = userEvent.setup();
    mockedApiRequest.mockImplementation(async (url, options) => {
      if (String(url).startsWith('/api/platform-registry/snmp-walk-target')) {
        return { success: true, data: { ip: '10.254.0.1', device_id: 'device-1', hostname: 'edge-01' } } as never;
      }
      if (url === '/api/platform-registry/snmp-interface-test') {
        return {
          success: true,
          data: {
            host: '10.254.0.1',
            version: '2c',
            port: 161,
            status: 'ok',
            passed: true,
            message: 'Interface table and paired Counter64 counters passed validation',
            interfaces: 1,
            counter_supported: 1,
            selected_counter_bits: 64,
            checks: {
              identity: {
                oid: '1.3.6.1.2.1.31.1.1.1.1',
                passed: true,
                rows: 1,
                sample: [{ index: '55', value: 'FortyGigE1/0/54' }],
              },
            },
          },
        } as never;
      }
      return { success: true, data: [], total: 0, page: 1, page_size: 20, total_pages: 0 } as never;
    });
    render(
      <MetricOidProfilesModal
        open
        language="en"
        onClose={vi.fn()}
        showToast={vi.fn()}
      />,
    );

    await waitFor(() => expect(mockedApiRequest).toHaveBeenCalled());
    await user.click(screen.getByRole('button', { name: 'New Profile' }));
    await user.click(screen.getByRole('button', { name: 'Live Walk & Test Toolkit' }));
    await user.click(screen.getByRole('checkbox', { name: 'Enable interface template' }));
    const targetInput = screen.getByPlaceholderText('10.254.0.1');
    await user.type(targetInput, '10.254.0.1');
    await user.keyboard('{Enter}');
    await waitFor(() => expect(screen.getByText(/Matched: edge-01/)).toBeTruthy());

    await user.click(screen.getByRole('button', { name: 'Validate interface OIDs' }));
    await waitFor(() => expect(mockedApiRequest).toHaveBeenCalledWith(
      '/api/platform-registry/snmp-interface-test',
      expect.objectContaining({
        method: 'POST',
        body: expect.stringContaining('"interface_config"'),
      }),
    ));
    expect(screen.getByText(/Counter64 counters passed validation/)).toBeTruthy();
    expect(screen.getByText(/FortyGigE1\/0\/54/)).toBeTruthy();
  });

  it('saves only the enabled interface template with the selected counter width', async () => {
    const user = userEvent.setup();
    mockedApiRequest.mockImplementation(async (url, options) => {
      if (String(url).includes('/snmp-metric-profiles') && options?.method === 'POST') {
        return { success: true, data: { id: 'profile-1' } } as never;
      }
      if (String(url).includes('/mapping-validation')) {
        return { success: true, data: { matched_device_count: 0, profile_applied_device_count: 0, blocked_device_count: 0, collector_status: 'no_matching_device' } } as never;
      }
      return { success: true, data: [], total: 0, page: 1, page_size: 20, total_pages: 0 } as never;
    });
    render(
      <MetricOidProfilesModal
        open
        language="en"
        onClose={vi.fn()}
        onChanged={vi.fn()}
        showToast={vi.fn()}
      />,
    );

    await waitFor(() => expect(mockedApiRequest).toHaveBeenCalled());
    await user.click(screen.getByRole('button', { name: 'New Profile' }));
    await user.selectOptions(screen.getByRole('combobox', { name: 'Vendor (shared catalog)' }), 'Cisco');
    await user.type(screen.getByPlaceholderText('例如：C9300-48P / S6800-54QT'), 'C9300-48P');
    await user.click(screen.getByRole('checkbox', { name: 'Enable interface template' }));
    await user.selectOptions(screen.getByRole('combobox', { name: 'Traffic counter width' }), '64');
    await user.click(screen.getByRole('button', { name: 'Save Profile' }));

    await waitFor(() => expect(mockedApiRequest).toHaveBeenCalledWith(
      '/api/platform-registry/snmp-metric-profiles',
      expect.objectContaining({
        method: 'POST',
        body: expect.stringContaining('"counter_mode":"64"'),
      }),
    ));
    expect(await screen.findByRole('button', { name: 'Select all' })).toBeTruthy();
  });

  it('applies an official preset directly to the model profile used by devices', async () => {
    const user = userEvent.setup();
    const preset = {
      id: 'md-h3c-s6800-v7',
      family_id: 'md-h3c-comware-v7',
      vendor: 'H3C',
      model: 'S6800',
      category: 'Campus Switch',
      description: 'Comware V7',
      metric_definitions: {
        cpu: { mode: 'direct_percent', oid: '1.3.6.1.4.1.25506.1' },
      },
      interface_config: {},
      testable: true,
    };
    mockedApiRequest.mockImplementation(async (url, options) => {
      if (url === '/api/platform-registry/mibs/presets/models') {
        return { success: true, data: [preset], total: 1 } as never;
      }
      if (url === '/api/platform-registry/snmp-metric-profiles/apply-preset') {
        return { success: true, data: { id: 'profile-s6800' } } as never;
      }
      if (String(url).startsWith('/api/devices?mode=light')) {
        return {
          items: [{ id: 'device-1', hostname: 'edge-01', ip_address: '10.254.0.1', vendor: 'H3C', model: 'S6800', status: 'online' }],
        } as never;
      }
      if (url === '/api/platform-registry/snmp-hardware-test') {
        return { success: true, data: { status: 'ok', metric_count: 1, metrics: { cpu: { status: 'ok', value: 30 } } } } as never;
      }
      if (String(url).includes('/mapping-validation')) {
        return { success: true, data: { matched_device_count: 1, sample_device_id: null, profile_applied_device_count: 0, blocked_device_count: 1, collector_status: 'blocked_unverified' } } as never;
      }
      return { success: true, data: [], total: 0, page: 1, page_size: 20, total_pages: 0 } as never;
    });

    render(
      <MetricOidProfilesModal
        open
        language="en"
        onClose={vi.fn()}
        onChanged={vi.fn()}
        showToast={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByRole('button', { name: 'Official Templates' })).toBeTruthy());
    await user.click(screen.getByRole('button', { name: 'Official Templates' }));
    await waitFor(() => expect(screen.getByText('H3C S6800')).toBeTruthy());
    await user.click(screen.getByRole('button', { name: /Test & bind \(H3C S6800\)/ }));
    await screen.findByRole('combobox', { name: 'Test device' });
    await user.click(screen.getByRole('checkbox'));
    await waitFor(() => expect((screen.getByRole('button', { name: 'Test template' }) as HTMLButtonElement).disabled).toBe(false));
    await user.click(screen.getByRole('button', { name: 'Test template' }));
    await screen.findByText('Passed');
    await user.click(screen.getByRole('button', { name: 'Confirm binding' }));

    await waitFor(() => expect(mockedApiRequest).toHaveBeenCalledWith(
      '/api/platform-registry/snmp-metric-profiles/apply-preset',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ preset_id: 'md-h3c-s6800-v7' }),
      }),
    ));
  });

  it('applies the exact built-in preset directly from a matched model row', async () => {
    const user = userEvent.setup();
    const preset = {
      id: 'md-h3c-s6800-v7',
      family_id: 'md-h3c-comware-v7',
      vendor: 'H3C',
      model: 'S6800',
      category: 'Campus Switch',
      description: 'Comware V7',
      metric_definitions: {
        cpu: { mode: 'direct_percent', oid: '1.3.6.1.4.1.25506.1' },
      },
      interface_config: {},
      testable: true,
    };
    const inventoryMatch = {
      profile_id: null,
      vendor: 'H3C',
      model: 'S6800',
      cpu_oid: '',
      memory_oid: '',
      metric_definitions: {},
      configured: false,
      verification_status: 'unverified',
      device_count: 1,
      matched_device_count: 1,
      interface_config: {},
      interface_configured: false,
      platforms: ['h3c_comware'],
      sample_device_id: 'device-1',
      sample_device_ip: '10.254.0.1',
      sample_device_status: 'online',
    };
    mockedApiRequest.mockImplementation(async (url) => {
      if (url === '/api/platform-registry/mibs/presets/models') {
        return { success: true, data: [preset], total: 1 } as never;
      }
      if (String(url).startsWith('/api/platform-registry/snmp-metric-profiles?')) {
        return { success: true, data: [inventoryMatch], total: 1, page: 1, page_size: 20, total_pages: 1 } as never;
      }
      if (url === '/api/platform-registry/snmp-metric-profiles/apply-preset') {
        return { success: true, data: { id: 'profile-s6800' } } as never;
      }
      if (String(url).startsWith('/api/devices?mode=light')) {
        return {
          items: [{ id: 'device-1', hostname: 'edge-01', ip_address: '10.254.0.1', vendor: 'H3C', model: 'S6800', status: 'online' }],
        } as never;
      }
      if (url === '/api/platform-registry/snmp-hardware-test') {
        return { success: true, data: { status: 'ok', metric_count: 1, metrics: { cpu: { status: 'ok', value: 30 } } } } as never;
      }
      return { success: true, data: [], total: 0, page: 1, page_size: 20, total_pages: 0 } as never;
    });

    render(
      <MetricOidProfilesModal
        open
        language="en"
        onClose={vi.fn()}
        onChanged={vi.fn()}
        showToast={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByRole('button', { name: 'Test & bind' })).toBeTruthy());
    await user.click(screen.getByRole('button', { name: 'Test & bind' }));
    await screen.findByRole('combobox', { name: 'Test device' });
    await waitFor(() => expect((screen.getByRole('button', { name: 'Test template' }) as HTMLButtonElement).disabled).toBe(false));
    await user.click(screen.getByRole('button', { name: 'Test template' }));
    await screen.findByText('Passed');
    await user.click(screen.getByRole('button', { name: 'Confirm binding' }));
    await waitFor(() => expect(mockedApiRequest).toHaveBeenCalledWith(
      '/api/platform-registry/snmp-metric-profiles/apply-preset',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ preset_id: 'md-h3c-s6800-v7' }),
      }),
    ));
  });

  it('shows the official preset as already applied after the list is refreshed', async () => {
    const preset = {
      id: 'md-h3c-s6800-v7',
      family_id: 'md-h3c-comware-v7',
      vendor: 'H3C',
      model: 'S6800',
      category: 'Campus Switch',
      description: 'Comware V7',
      metric_definitions: {
        cpu: { mode: 'direct_percent', oid: '1.3.6.1.4.1.25506.1' },
      },
      interface_config: {},
      testable: true,
    };
    const appliedProfile = {
      profile_id: 'profile-s6800',
      source: 'official',
      official_preset_id: 'md-h3c-s6800-v7',
      vendor: 'H3C',
      model: 'S6800',
      cpu_oid: '1.3.6.1.4.1.25506.1',
      memory_oid: '',
      metric_definitions: {
        cpu: { mode: 'direct_percent', oid: '1.3.6.1.4.1.25506.1' },
      },
      metric_keys: ['cpu'],
      configured: true,
      verification_status: 'unverified',
      device_count: 1,
      matched_device_count: 1,
      inventory_device_count: 8,
      profile_applied_device_count: 1,
      blocked_device_count: 0,
      collector_status: 'active',
      interface_config: {},
      interface_configured: false,
      platforms: ['h3c_comware'],
      sample_device_id: 'device-1',
      sample_device_ip: '10.254.0.1',
      sample_device_status: 'online',
    };
    mockedApiRequest.mockImplementation(async (url) => {
      if (url === '/api/platform-registry/mibs/presets/models') {
        return { success: true, data: [preset], total: 1 } as never;
      }
      if (String(url).startsWith('/api/platform-registry/snmp-metric-profiles?')) {
        return { success: true, data: [appliedProfile], total: 1, page: 1, page_size: 20, total_pages: 1 } as never;
      }
      return { success: true, data: [], total: 0, page: 1, page_size: 20, total_pages: 0 } as never;
    });

    render(
      <MetricOidProfilesModal
        open
        language="en"
        onClose={vi.fn()}
        onChanged={vi.fn()}
        showToast={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByRole('button', { name: 'Applied' })).toBeTruthy());
    expect(screen.getByText('Official bound')).toBeTruthy();
    expect(screen.getByText('8 candidate devices')).toBeTruthy();
    expect(screen.getByText(/see the Bound Models template row for the actual binding count/i)).toBeTruthy();
  });

  it('allows binding an official preset to an offline device without running a live test', async () => {
    const user = userEvent.setup();
    const preset = {
      id: 'md-h3c-s6800-v7',
      family_id: 'md-h3c-comware-v7',
      vendor: 'H3C',
      model: 'S6800',
      category: 'Campus Switch',
      description: 'Comware V7',
      metric_definitions: {
        cpu: { mode: 'direct_percent', oid: '1.3.6.1.4.1.25506.1' },
      },
      interface_config: {},
      testable: true,
    };
    const inventoryMatch = {
      profile_id: null,
      vendor: 'H3C',
      model: 'S6800',
      cpu_oid: '',
      memory_oid: '',
      metric_definitions: {},
      configured: false,
      verification_status: 'unverified',
      device_count: 1,
      matched_device_count: 1,
      interface_config: {},
      interface_configured: false,
      platforms: ['h3c_comware'],
      sample_device_id: 'device-offline',
      sample_device_ip: '10.254.0.2',
      sample_device_status: 'offline',
    };
    mockedApiRequest.mockImplementation(async (url) => {
      if (url === '/api/platform-registry/mibs/presets/models') {
        return { success: true, data: [preset], total: 1 } as never;
      }
      if (String(url).startsWith('/api/platform-registry/snmp-metric-profiles?')) {
        return { success: true, data: [inventoryMatch], total: 1, page: 1, page_size: 20, total_pages: 1 } as never;
      }
      if (String(url).startsWith('/api/devices?mode=light')) {
        return {
          items: [{ id: 'device-offline', hostname: 'edge-offline', ip_address: '10.254.0.2', vendor: 'H3C', model: 'S6800', status: 'offline' }],
        } as never;
      }
      if (url === '/api/platform-registry/snmp-metric-profiles/apply-preset') {
        return { success: true, data: { id: 'profile-s6800' } } as never;
      }
      return { success: true, data: [], total: 0, page: 1, page_size: 20, total_pages: 0 } as never;
    });

    render(
      <MetricOidProfilesModal
        open
        language="en"
        onClose={vi.fn()}
        onChanged={vi.fn()}
        showToast={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByRole('button', { name: 'Test & bind' })).toBeTruthy());
    await user.click(screen.getByRole('button', { name: 'Test & bind' }));
    await screen.findByText(/live testing is unavailable; binding is still allowed/i);
    const testButton = screen.getByRole('button', { name: 'Device offline; test unavailable' }) as HTMLButtonElement;
    expect(testButton.disabled).toBe(true);
    const confirmButton = screen.getByRole('button', { name: 'Confirm binding \(untested\)' }) as HTMLButtonElement;
    expect(confirmButton.disabled).toBe(false);
    await user.click(confirmButton);

    expect(mockedApiRequest.mock.calls.some(([url]) => url === '/api/platform-registry/snmp-hardware-test')).toBe(false);
    await waitFor(() => expect(mockedApiRequest).toHaveBeenCalledWith(
      '/api/platform-registry/snmp-metric-profiles/apply-preset',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ preset_id: 'md-h3c-s6800-v7' }),
      }),
    ));
  });

  it('does not auto-test a mapped device when opening collected results', async () => {
    const user = userEvent.setup();
    const profile = {
      profile_id: 'profile-s6800',
      vendor: 'H3C',
      model: 'S6800',
      cpu_oid: '1.3.6.1.4.1.25506.1.6',
      memory_oid: '1.3.6.1.4.1.25506.1.8',
      cpu_config: { mode: 'direct_percent', oid: '1.3.6.1.4.1.25506.1.6' },
      memory_config: { mode: 'direct_percent', oid: '1.3.6.1.4.1.25506.1.8' },
      metric_definitions: {
        cpu: { mode: 'direct_percent', oid: '1.3.6.1.4.1.25506.1.6' },
        memory: { mode: 'direct_percent', oid: '1.3.6.1.4.1.25506.1.8' },
      },
      metric_keys: ['cpu', 'memory'],
      configured: true,
      verification_status: 'unverified',
      device_count: 1,
      matched_device_count: 1,
      profile_applied_device_count: 0,
      blocked_device_count: 1,
      collector_status: 'blocked_unverified',
      interface_config: {},
      interface_configured: false,
      interface_verification_status: 'unverified',
      platforms: ['h3c_comware'],
    };
    mockedApiRequest.mockImplementation(async (url) => {
      if (String(url).startsWith('/api/platform-registry/snmp-metric-profiles?')) {
        return { success: true, data: [profile], total: 1, page: 1, page_size: 20, total_pages: 1 } as never;
      }
      if (String(url).includes('/mapping-validation')) {
        return {
          success: true,
          data: {
            matched_device_count: 1,
            profile_applied_device_count: 0,
            blocked_device_count: 1,
            collector_status: 'blocked_unverified',
            devices: [
              { device_id: 'device-offline', hostname: 'S6800-0', ip_address: '10.254.0.2', status: 'offline' },
              { device_id: 'device-1', hostname: 'S6800-1', ip_address: '10.254.0.1', status: 'online' },
            ],
          },
        } as never;
      }
      return { success: true, data: [], total: 0, page: 1, page_size: 20, total_pages: 0 } as never;
    });

    render(
      <MetricOidProfilesModal
        open
        language="en"
        onClose={vi.fn()}
        onChanged={vi.fn()}
        showToast={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByRole('button', { name: 'Collected' })).toBeTruthy());
    await user.click(screen.getByRole('button', { name: 'Collected' }));
    await waitFor(() => expect(
      mockedApiRequest.mock.calls.some(([url]) => String(url).includes('/mapping-validation')),
    ).toBe(true));
    const candidateSelect = await screen.findByRole('combobox', { name: 'Select matched device (online first)' }) as HTMLSelectElement;
    expect(candidateSelect.value).toBe('device-1');
    expect(candidateSelect.options[1]?.textContent).toContain('online');
    await new Promise(resolve => setTimeout(resolve, 0));

    expect(mockedApiRequest.mock.calls.some(([url]) => String(url).includes('/snmp-hardware-test'))).toBe(false);
    expect(screen.getByRole('button', { name: 'Test Hardware Metrics' })).toBeTruthy();
  });
});
