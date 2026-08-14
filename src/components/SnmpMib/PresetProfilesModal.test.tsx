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
  vendor,
  model,
  category,
  description: `${vendor} ${model} baseline`,
  metric_definitions: {
    cpu: { mode: 'direct_percent', oid: '1.3.6.1.4.1.1.1.1', unit: '%' },
  },
  interface_config: { enabled: true, counter_mode: 'auto' },
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
});
