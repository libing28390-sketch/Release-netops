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
    await user.click(screen.getByRole('button', { name: 'New' }));

    expect(screen.getAllByRole('row')).toHaveLength(3);
    expect(screen.getByText('CPU')).toBeTruthy();
    expect(screen.getByText('Memory')).toBeTruthy();
    expect(screen.getAllByRole('button', { name: 'New' })).toHaveLength(1);

    await user.selectOptions(screen.getByRole('combobox', { name: 'Metric to add' }), 'temperature');
    await user.click(screen.getByRole('button', { name: 'Add metric' }));
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
    await user.click(screen.getByRole('button', { name: 'New' }));
    expect(screen.queryByPlaceholderText('1 or 1.2')).toBeNull();

    const advancedButtons = screen.getAllByRole('button', { name: /Advanced settings/ });
    expect(advancedButtons).toHaveLength(2);
    await user.click(advancedButtons[0]);

    expect(screen.getByPlaceholderText('1 or 1.2')).toBeTruthy();
    expect(screen.getAllByText('Aggregation')).toHaveLength(1);
    expect(screen.getByText('Scale')).toBeTruthy();
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
    await user.click(screen.getByRole('button', { name: 'New' }));
    const targetInput = screen.getByPlaceholderText('10.254.0.1');
    await user.type(targetInput, '10.254.0.1');
    expect(mockedApiRequest).not.toHaveBeenCalledWith(expect.stringContaining('/api/platform-registry/snmp-walk-target'), expect.anything());
    await user.keyboard('{Enter}');

    await waitFor(() => expect(mockedApiRequest.mock.calls.some(([url]) => url === '/api/platform-registry/snmp-walk-target?ip=10.254.0.1')).toBe(true));
    expect(screen.queryByRole('textbox', { name: /community/i })).toBeNull();
    expect(screen.getByText(/Matched: edge-01/)).toBeTruthy();
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
    await user.click(screen.getByRole('button', { name: 'New' }));
    await user.selectOptions(screen.getByRole('combobox', { name: 'Vendor (shared with assets)' }), 'Cisco');
    await user.type(screen.getByPlaceholderText('C9300-48P'), 'C9300-48P');
    await user.click(screen.getByRole('checkbox', { name: 'Enable interface template' }));
    await user.selectOptions(screen.getByRole('combobox', { name: 'Traffic counter width' }), '64');
    await user.click(screen.getByRole('button', { name: 'Save profile' }));

    await waitFor(() => expect(mockedApiRequest).toHaveBeenCalledWith(
      '/api/platform-registry/snmp-metric-profiles',
      expect.objectContaining({
        method: 'POST',
        body: expect.stringContaining('"counter_mode":"64"'),
      }),
    ));
  });
});
