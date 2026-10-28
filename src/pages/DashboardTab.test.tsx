import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import DashboardTab from './DashboardTab';

vi.mock('../hooks/useSystem', () => ({ useSystem: () => ({ systemInfo: { system_name: 'Nexora' } }) }));
vi.mock('../hooks/useChartTheme', () => ({
  useChartTheme: () => ({ grid: '#eee', axis: '#666', tooltipBorder: '#ddd', tooltipShadow: 'none', tooltipBg: '#fff', tooltipText: '#222' }),
}));
vi.mock('../components/PageHero', () => ({
  default: ({ title, actions }: { title: string; actions?: React.ReactNode }) => <header><h1>{title}</h1>{actions}</header>,
}));
vi.mock('recharts', async () => {
  const { createElement } = await import('react');
  const passthrough = ({ children }: { children?: React.ReactNode }) => createElement('div', null, children);
  return {
    ResponsiveContainer: passthrough,
    AreaChart: passthrough,
    Area: passthrough,
    XAxis: passthrough,
    YAxis: passthrough,
    CartesianGrid: passthrough,
    Tooltip: passthrough,
    ReferenceLine: passthrough,
    PieChart: passthrough,
    Pie: passthrough,
    Cell: passthrough,
  };
});

const renderDashboard = (overrides: Record<string, unknown> = {}) => {
  const props = {
    devices: [],
    jobs: [],
    scheduledTasks: [],
    trendDays: 7 as const,
    setTrendDays: vi.fn(),
    complianceTrend: [],
    managedAssetPlatformData: [],
    dashBannerCollapsed: false,
    setDashBannerCollapsed: vi.fn(),
    dashLastRefresh: new Date('2026-10-21T00:00:00.000Z'),
    autoRefreshEnabled: true,
    setAutoRefreshEnabled: vi.fn(),
    fetchSharedData: vi.fn().mockResolvedValue(undefined),
    fetchDevicesData: vi.fn().mockResolvedValue(undefined),
    fetchAssetsTotal: vi.fn().mockResolvedValue(undefined),
    selectedJob: null,
    setSelectedJob: vi.fn(),
    hostResources: null,
    unreadNotificationCount: 0,
    notifications: [],
    language: 'en',
    t: (key: string) => key,
    setActiveTab: vi.fn(),
    navigate: vi.fn(),
    assetsTotal: 0,
    assetsOnlineTotal: 0,
    assetsTotalError: null,
    assetsPlatformError: null,
    ...overrides,
  };
  return { ...render(<DashboardTab {...props} />), props };
};

describe('DashboardTab accessible interactions', () => {
  afterEach(() => cleanup());

  it('exposes refresh states and the automatic refresh toggle state', async () => {
    let finishRefresh: (() => void) | undefined;
    const pendingRefresh = new Promise<void>(resolve => { finishRefresh = resolve; });
    const { props } = renderDashboard({ fetchSharedData: vi.fn(() => pendingRefresh) });

    const refreshButton = screen.getByRole('button', { name: 'Refresh Now' }) as HTMLButtonElement;
    fireEvent.click(refreshButton);
    await waitFor(() => expect(refreshButton.disabled).toBe(true));
    expect(refreshButton.getAttribute('aria-busy')).toBe('true');

    const autoRefreshButton = screen.getByRole('button', { name: 'Auto-refresh on' });
    expect(autoRefreshButton.getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(autoRefreshButton);
    expect(props.setAutoRefreshEnabled).toHaveBeenCalledWith(false);

    finishRefresh?.();
    await waitFor(() => expect(refreshButton.disabled).toBe(false));
  });

  it('supports keyboard activation for summary cards and exposes chart toggle selection', () => {
    const { props } = renderDashboard();

    const assetCard = screen.getByRole('button', { name: /totalAssets/ });
    expect(assetCard.className).toContain('focus-visible:ring-2');
    fireEvent.keyDown(assetCard, { key: 'Enter' });
    expect(props.navigate).toHaveBeenCalledWith('/assets/network-devices');

    const complianceToggle = screen.getByRole('button', { name: 'Compliance rate' });
    expect(complianceToggle.getAttribute('aria-pressed')).toBe('true');

    const sevenDayRange = screen.getByRole('button', { name: 'Show last 7 days' });
    expect(sevenDayRange.getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: 'Show last 30 days' }));
    expect(props.setTrendDays).toHaveBeenCalledWith(30);
  });
});
