import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiRequest } from '../../api/http';
import PresetProfilesModal from './PresetProfilesModal';

vi.mock('../../api/http', () => ({
  apiRequest: vi.fn(),
}));

const mockedApiRequest = vi.mocked(apiRequest);

const preset = (vendor: string, model: string, category: string) => ({
  id: `${vendor.toLowerCase()}-${model.toLowerCase()}`,
  vendor,
  model,
  category,
  description: `${vendor} ${model} baseline`,
  metric_definitions: {
    cpu: { mode: 'direct_percent', oid: '1.3.6.1.4.1.1.1.1', unit: '%' },
  },
  interface_config: { enabled: true, counter_mode: 'auto' },
  testable: true,
});

describe('PresetProfilesModal filters', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('filters official presets by vendor and category', async () => {
    const user = userEvent.setup();
    mockedApiRequest.mockResolvedValue({
      success: true,
      data: [
        preset('Huawei', 'S5700', 'Campus Switch'),
        preset('Huawei', 'CE6800', 'Data Center Switch'),
        preset('H3C', 'S5130', 'Access Switch'),
      ],
    } as never);

    render(
      <PresetProfilesModal
        open
        onClose={vi.fn()}
        onApplyPreset={vi.fn()}
        language="en"
        showToast={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByText('Huawei S5700')).toBeTruthy());
    const vendorFilter = screen.getByRole('combobox', { name: 'Filter by vendor' });
    const categoryFilter = screen.getByRole('combobox', { name: 'Filter by category' });

    await user.selectOptions(vendorFilter, 'Huawei');
    await waitFor(() => expect(screen.getByText('Huawei CE6800')).toBeTruthy());
    expect(screen.queryByText('H3C S5130')).toBeNull();

    await user.selectOptions(categoryFilter, 'Data Center Switch');
    await waitFor(() => expect(screen.getByText('Huawei CE6800')).toBeTruthy());
    expect(screen.queryByText('Huawei S5700')).toBeNull();
  });

  it('confirms a managed target and runs the built-in preset test', async () => {
    const user = userEvent.setup();
    mockedApiRequest
      .mockResolvedValueOnce({
        success: true,
        data: [preset('H3C', 'S5130', 'Campus Switch')],
      } as never)
      .mockResolvedValueOnce({
        success: true,
        data: { ip: '10.0.0.8', device_id: 'device-8', hostname: 'S5130-8' },
      } as never)
      .mockResolvedValueOnce({
        success: true,
        data: {
          host: '10.0.0.8',
          status: 'ok',
          message: 'All metrics returned',
          metric_count: 5,
          metrics: {
            cpu: { value: 12, status: 'ok', unit: '%' },
            uptime: { value: 3723, status: 'ok', unit: 's' },
            fan: { value: true, raw_value: [2, 2, 2], status: 'ok', unit: 'bool' },
          },
        },
      } as never)
      .mockResolvedValueOnce({
        success: true,
        data: {
          status: 'ok',
          passed: true,
          message: 'Interface checks passed',
          interfaces: 24,
        },
      } as never);

    render(
      <PresetProfilesModal
        open
        onClose={vi.fn()}
        onApplyPreset={vi.fn()}
        language="en"
        showToast={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByText('H3C S5130')).toBeTruthy());
    const targetInput = screen.getByRole('textbox', { name: 'Preset test device IP' });
    await user.type(targetInput, '10.0.0.8');
    await user.click(screen.getByRole('button', { name: 'Confirm device' }));
    await waitFor(() => expect(screen.getByText(/S5130-8 \/ 10\.0\.0\.8/)).toBeTruthy());

    await user.click(screen.getByRole('button', { name: 'Test this built-in preset' }));
    await waitFor(() => expect(screen.getByText('Hardware result')).toBeTruthy());
    expect(screen.getByText('Interface IF-MIB result')).toBeTruthy();
    expect(screen.getByText('1h 2m 3s')).toBeTruthy();
    expect(screen.getByText(/Raw summary: 2 × 3 items/)).toBeTruthy();
    expect(mockedApiRequest).toHaveBeenCalledWith(
      '/api/platform-registry/snmp-hardware-test',
      expect.objectContaining({ method: 'POST' }),
    );
  });
});
