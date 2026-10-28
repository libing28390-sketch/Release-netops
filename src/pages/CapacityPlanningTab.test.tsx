import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import CapacityPlanningTab from './CapacityPlanningTab';

vi.mock('../hooks/useChartTheme', () => ({
  useChartTheme: () => ({
    isDark: false,
    grid: '#eee',
    axis: '#666',
    tooltipBorder: '#ddd',
    tooltipShadow: 'none',
    tooltipBg: '#fff',
    tooltipText: '#222',
  }),
}));
vi.mock('../components/PageHero', () => ({
  default: ({ title, actions }: { title: string; actions?: React.ReactNode }) => <header><h1>{title}</h1>{actions}</header>,
}));
vi.mock('recharts', async () => {
  const { createElement } = await import('react');
  const passthrough = ({ children }: { children?: React.ReactNode }) => createElement('div', null, children);
  return {
    ResponsiveContainer: passthrough,
    LineChart: passthrough,
    Line: passthrough,
    XAxis: passthrough,
    YAxis: passthrough,
    CartesianGrid: passthrough,
    Tooltip: passthrough,
    ReferenceLine: passthrough,
    Legend: passthrough,
  };
});

const response = (body: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: vi.fn().mockResolvedValue(body),
}) as unknown as Response;

const renderCapacity = (language = 'en') => render(
  <CapacityPlanningTab language={language} t={(key) => key} />,
);

const forecastItems = [
  {
    device_id: 'device-critical',
    hostname: 'router-critical',
    peak_link_util: 96,
    risk_level: 'critical',
    worst_interface: 'GigabitEthernet0/0',
    capacity_score: 42,
  },
  {
    device_id: 'device-warning',
    hostname: 'router-warning',
    peak_link_util: 82,
    risk_level: 'warning',
    worst_interface: 'GigabitEthernet0/1',
    capacity_score: 72,
  },
];

describe('CapacityPlanningTab interaction states', () => {
  beforeEach(() => {
    localStorage.setItem('netops_token', 'test-token');
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    cleanup();
    localStorage.removeItem('netops_token');
    vi.unstubAllGlobals();
  });

  it('shows loading, reports permission denial safely, and retries the existing endpoints', async () => {
    let overviewCalls = 0;
    vi.mocked(fetch).mockImplementation((input) => {
      const url = String(input);
      if (url === '/api/capacity/overview') {
        overviewCalls += 1;
        return Promise.resolve(overviewCalls === 1
          ? response({ detail: 'private backend detail' }, 403)
          : response({ all_devices: [] }));
      }
      if (url === '/api/capacity/forecast') return Promise.resolve(response({ items: [] }));
      return Promise.resolve(response({ interfaces: [] }));
    });

    renderCapacity();
    expect(screen.getByText('Loading capacity analysis…')).toBeTruthy();
    const permissionError = await screen.findByRole('alert');
    expect(permissionError.textContent).toContain('You do not have permission');
    expect(permissionError.textContent).not.toContain('private backend detail');

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await screen.findByText('No risks found');
    expect(overviewCalls).toBe(2);
    expect(fetch).toHaveBeenCalledWith('/api/capacity/overview', expect.objectContaining({
      headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
    }));
    expect(fetch).toHaveBeenCalledWith('/api/capacity/forecast', expect.objectContaining({
      headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
    }));
  });

  it('keeps available risks visible and reports a partial refresh failure', async () => {
    let overviewCalls = 0;
    vi.mocked(fetch).mockImplementation((input) => {
      const url = String(input);
      if (url === '/api/capacity/overview') {
        overviewCalls += 1;
        return Promise.resolve(overviewCalls === 1
          ? response({ all_devices: [] })
          : response({ detail: 'temporary failure' }, 503));
      }
      if (url === '/api/capacity/forecast') return Promise.resolve(response({ items: forecastItems }));
      return Promise.resolve(response({ interfaces: [] }));
    });

    renderCapacity();
    expect(await screen.findByRole('button', { name: /router-critical/ })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));

    expect(await screen.findByText('Some capacity data is unavailable. Showing available results.')).toBeTruthy();
    expect(screen.getByRole('button', { name: /router-critical/ })).toBeTruthy();
    expect(screen.queryByText('temporary failure')).toBeNull();
  });

  it('exposes selected filters and risk rows and distinguishes a no-match result', async () => {
    vi.mocked(fetch).mockImplementation((input) => {
      const url = String(input);
      if (url === '/api/capacity/overview') return Promise.resolve(response({ all_devices: [] }));
      if (url === '/api/capacity/forecast') return Promise.resolve(response({ items: forecastItems }));
      return Promise.resolve(response({ interfaces: [] }));
    });

    renderCapacity();
    const criticalFilter = await screen.findByRole('button', { name: 'Critical 1' });
    const allFilter = screen.getByRole('button', { name: 'All 2' });
    expect(criticalFilter.className).toContain('focus-visible:ring-2');
    expect(allFilter.getAttribute('aria-pressed')).toBe('true');
    expect(criticalFilter.getAttribute('aria-pressed')).toBe('false');

    fireEvent.click(criticalFilter);
    await waitFor(() => expect(criticalFilter.getAttribute('aria-pressed')).toBe('true'));
    const criticalRisk = screen.getByRole('button', { name: /router-critical/ });
    expect(criticalRisk.getAttribute('aria-pressed')).toBe('true');
    expect(screen.queryByRole('button', { name: /router-warning/ })).toBeNull();
    expect(await screen.findByText('No interface trend data is available for this device')).toBeTruthy();

    const search = screen.getByRole('textbox', { name: 'Search device or metric' });
    fireEvent.change(search, { target: { value: 'no-such-device' } });
    expect(screen.getByText('No devices match the current filters')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Clear search' }));
    await waitFor(() => expect(screen.getByRole('button', { name: /router-critical/ })).toBeTruthy());
  });

  it('moves the selected detail to a visible risk when the current selection is filtered out', async () => {
    vi.mocked(fetch).mockImplementation((input) => {
      const url = String(input);
      if (url === '/api/capacity/overview') return Promise.resolve(response({ all_devices: [] }));
      if (url === '/api/capacity/forecast') return Promise.resolve(response({ items: forecastItems }));
      return Promise.resolve(response({ interfaces: [] }));
    });

    renderCapacity();
    const warningRisk = await screen.findByRole('button', { name: /router-warning/ });
    fireEvent.click(warningRisk);
    await waitFor(() => expect(warningRisk.getAttribute('aria-pressed')).toBe('true'));

    fireEvent.click(screen.getByRole('button', { name: 'Critical 1' }));

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /router-warning/ })).toBeNull();
      expect(screen.getByRole('button', { name: /router-critical/ }).getAttribute('aria-pressed')).toBe('true');
    });
  });
});
