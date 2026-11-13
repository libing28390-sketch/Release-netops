import React from 'react';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import CmdbInterfaceCollectionProgress, { type CmdbInterfaceCollectionJob } from './CmdbInterfaceCollectionProgress';

afterEach(() => cleanup());

describe('CMDB interface collection progress', () => {
  it('shows aggregate counts and keeps device details collapsed until requested', () => {
    const job: CmdbInterfaceCollectionJob = {
      job_id: 'job-interfaces-1',
      status: 'running',
      total_targets: 16,
      success_count: 1,
      failed_count: 5,
      target_status_counts: { queued: 7, running: 2, succeeded: 1, failed: 3, timeout: 2, cancelled: 1 },
      targets_truncated: true,
      targets: [
        { target_id: 'device-running', target_hostname: 'edge-running', status: 'running' },
        { target_id: 'device-failed', target_hostname: 'edge-failed', status: 'failed', error_message: 'SSH connection timed out' },
      ],
    };

    render(<CmdbInterfaceCollectionProgress job={job} language="en" />);

    const card = screen.getByRole('region', { name: 'Interface collection progress' });
    expect(within(card).getByText('Completed 7 / 16')).toBeTruthy();
    expect(within(card).getByText('Succeeded 1')).toBeTruthy();
    expect(within(card).getByText('Failed 5')).toBeTruthy();
    expect(within(card).getByText('Running 2')).toBeTruthy();
    expect(within(card).getByText('Queued 7')).toBeTruthy();

    const progress = within(card).getByRole('progressbar');
    expect(progress.getAttribute('aria-valuenow')).toBe('7');
    expect(progress.getAttribute('aria-valuemax')).toBe('16');
    const detailsButton = within(card).getByRole('button', { name: 'View details' });
    const detailsPanelId = detailsButton.getAttribute('aria-controls');
    const detailsPanel = detailsPanelId ? card.querySelector(`#${detailsPanelId}`) : null;
    expect(detailsPanel?.hasAttribute('hidden')).toBe(true);

    fireEvent.click(detailsButton);
    expect(detailsPanel?.hasAttribute('hidden')).toBe(false);
    expect(within(card).getByText('edge-running')).toBeTruthy();
    expect(within(card).getByText('edge-failed')).toBeTruthy();
    expect(within(card).getByText('SSH connection timed out')).toBeTruthy();
  });

  it.each([
    ['cancelled', 'Cancelled'],
    ['timeout', 'Timed out'],
    ['partially_failed', 'Partially failed'],
  ])('distinguishes the terminal status %s', (status, label) => {
    render(
      <CmdbInterfaceCollectionProgress
        job={{
          job_id: `job-${status}`,
          status,
          total_targets: 2,
          success_count: status === 'partially_failed' ? 1 : 0,
          failed_count: status === 'partially_failed' || status === 'timeout' ? 1 : 0,
          target_status_counts: { queued: 0, running: 0, succeeded: status === 'partially_failed' ? 1 : 0, failed: status === 'partially_failed' ? 1 : 0, timeout: status === 'timeout' ? 1 : 0, cancelled: status === 'cancelled' ? 2 : 0 },
          targets: status === 'timeout' ? [{ target_id: 'edge-timeout', target_ip: '192.0.2.9', status: 'timeout', error_message: 'Device did not respond' }] : [],
        }}
        language="en"
      />,
    );

    const card = screen.getByRole('region', { name: 'Interface collection progress' });
    expect(within(card).getAllByText(label, { exact: true }).length).toBeGreaterThan(0);
    expect(within(card).getByRole('button', { name: 'View details' }).getAttribute('aria-expanded')).toBe('false');
    if (status === 'timeout') {
      fireEvent.click(within(card).getByRole('button', { name: 'View details' }));
      expect(within(card).getByText('Device did not respond')).toBeTruthy();
    }
  });

  it('does not invent a progress value when the total is unknown or zero', () => {
    const { rerender } = render(
      <CmdbInterfaceCollectionProgress job={{ job_id: 'unknown-total', status: 'running', success_count: 1, failed_count: 0 }} language="en" />,
    );
    const card = screen.getByRole('region', { name: 'Interface collection progress' });
    expect(within(card).getByText('Completed — / total unknown')).toBeTruthy();
    expect(within(card).queryByRole('progressbar')).toBeNull();

    rerender(
      <CmdbInterfaceCollectionProgress
        job={{ job_id: 'empty-job', status: 'succeeded', total_targets: 0, success_count: 0, failed_count: 0, target_status_counts: { queued: 0, running: 0, succeeded: 0, failed: 0, timeout: 0, cancelled: 0 } }}
        language="en"
      />,
    );
    expect(within(card).getByText('Completed 0 / 0')).toBeTruthy();
    expect(within(card).queryByRole('progressbar')).toBeNull();
    fireEvent.click(within(card).getByRole('button', { name: 'View details' }));
    expect(within(card).getByText('No collection targets')).toBeTruthy();

    rerender(
      <CmdbInterfaceCollectionProgress
        job={{
          job_id: 'truncated-counts',
          status: 'running',
          total_targets: 10,
          success_count: 2,
          failed_count: 0,
          targets_truncated: true,
          targets: [
            { target_id: 'running-visible', status: 'running' },
            { target_id: 'queued-visible', status: 'queued' },
          ],
        }}
        language="en"
      />,
    );
    expect(within(card).getByText('Running —')).toBeTruthy();
    expect(within(card).getByText('Queued —')).toBeTruthy();
    expect(within(card).queryByRole('progressbar')).toBeNull();
  });

  it('shows a compact loading state before the job record is available', () => {
    render(<CmdbInterfaceCollectionProgress job={null} language="en" loading />);
    expect(screen.getByText('Starting interface collection…')).toBeTruthy();
  });
});
