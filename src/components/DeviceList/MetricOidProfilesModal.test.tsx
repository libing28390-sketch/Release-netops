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
});
