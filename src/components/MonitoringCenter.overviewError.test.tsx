import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MonitoringOverviewStatus } from './MonitoringCenter';

describe('MonitoringOverviewStatus', () => {
  afterEach(() => cleanup());

  it('shows a safe permission error, retained-data timestamp, and retry action', () => {
    const onRetry = vi.fn();
    render(
      <MonitoringOverviewStatus
        hasData
        loading={false}
        error={{
          status: 403,
          message: 'You do not have permission to view the monitoring overview.',
          permissionDenied: true,
        }}
        updatedAt={new Date('2026-10-07T01:02:00.000Z')}
        language="en"
        onRetry={onRetry}
      />,
    );

    expect(screen.getByRole('alert').textContent).toContain('You do not have permission to view the monitoring overview.');
    expect(screen.getByRole('alert').textContent).toContain('Showing data last updated:');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('shows an explicit loading state before the first successful overview', () => {
    render(
      <MonitoringOverviewStatus
        hasData={false}
        loading
        error={null}
        updatedAt={null}
        language="en"
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByRole('status').textContent).toContain('Loading monitoring overview…');
  });
});
