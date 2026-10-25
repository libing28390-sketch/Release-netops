import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import TicketSummaryPanel from './TicketSummaryPanel';

const response = (body: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: vi.fn().mockResolvedValue(body),
}) as unknown as Response;

const summary = {
  from: '2026-10-01',
  to: '2026-10-30',
  totals: { all: 8, incident: 5, service_request: 3, active: 2, closed: 6 },
  by_priority: [{ priority: 'P1', count: 0 }, { priority: 'P2', count: 2 }],
  by_assignment_group: [{ id: null, name: '未分组', count: 1 }],
  durations_seconds: { first_response_avg: null, incident_restore_avg: 3600, service_fulfillment_avg: null, close_avg: 5400 },
  sample_counts: { first_response_avg: 0, incident_restore_avg: 2, service_fulfillment_avg: 0, close_avg: 2 },
  duration_basis: 'elapsed_utc_ticket_events',
};

describe('TicketSummaryPanel', () => {
  afterEach(() => {
    cleanup();
    localStorage.removeItem('netops_token');
    vi.unstubAllGlobals();
  });

  it('stays collapsed by default, submits an explicit UTC date range, and does not show empty duration samples as zero', async () => {
    localStorage.setItem('netops_token', 'test-token');
    const fetchMock = vi.fn().mockResolvedValue(response({ success: true, data: summary }));
    vi.stubGlobal('fetch', fetchMock);
    render(<TicketSummaryPanel language="zh" />);

    const summaryPanel = screen.getByTestId('ticket-summary-panel');
    expect(summaryPanel.className).toContain('shrink-0');
    expect(summaryPanel.className).toContain('overflow-visible');
    const toggle = screen.getByRole('button', { name: /工单统计/ });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(fetchMock).not.toHaveBeenCalled();

    fireEvent.click(toggle);
    const from = await screen.findByLabelText('统计开始日期') as HTMLInputElement;
    const to = screen.getByLabelText('统计结束日期') as HTMLInputElement;
    fireEvent.change(from, { target: { value: '2026-10-01' } });
    fireEvent.change(to, { target: { value: '2026-10-30' } });
    fireEvent.click(screen.getByRole('button', { name: '查询' }));

    expect(await screen.findByText('1 小时')).toBeTruthy();
    expect(screen.getByText('1 小时 30 分钟')).toBeTruthy();
    expect(screen.getAllByText('暂无数据').length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText(/^0 分钟$/)).toBeNull();
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input) === '/api/tickets/summary?from=2026-10-01&to=2026-10-30')).toBe(true));
  });

  it('rejects date ranges over the server limit without requesting them', async () => {
    localStorage.setItem('netops_token', 'test-token');
    const fetchMock = vi.fn().mockResolvedValue(response({ success: true, data: summary }));
    vi.stubGlobal('fetch', fetchMock);
    render(<TicketSummaryPanel language="en" />);
    fireEvent.click(screen.getByRole('button', { name: /Ticket summary/ }));
    fireEvent.change(await screen.findByLabelText('Summary start date'), { target: { value: '2024-01-01' } });
    fireEvent.change(screen.getByLabelText('Summary end date'), { target: { value: '2026-10-30' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));

    expect((await screen.findByRole('alert')).textContent).toContain('cannot exceed 366 days');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
