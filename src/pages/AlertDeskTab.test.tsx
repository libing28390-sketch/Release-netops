import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AlertDeskTab from './AlertDeskTab';

vi.mock('motion/react', () => ({
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  motion: {
    div: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => <div {...props}>{children}</div>,
  },
}));
vi.mock('../components/DataTable', () => ({
  DataTable: ({ children }: { children: React.ReactNode }) => <table>{children}</table>,
}));
vi.mock('../components/PageHero', () => ({
  default: ({ title, actions }: { title: string; actions?: React.ReactNode }) => <header><h1>{title}</h1>{actions}</header>,
}));
vi.mock('../components/Pagination', () => ({ default: () => null }));
vi.mock('./useAlertSiteLabels', () => ({ useAlertSiteLabels: () => new Map() }));

const response = (title: string) => ({
  ok: true,
  json: async () => ({
    items: [{
      id: `alert-${title}`,
      dedupe_key: `dedupe-${title}`,
      source: 'network_monitor',
      severity: 'warning',
      title,
      message: `Message for ${title}`,
      created_at: '2026-10-12T00:00:00Z',
      workflow_status: 'open',
      duration_seconds: 30,
    }],
    total: 1,
    page: 1,
    page_size: 10,
    status_counts: { open: 1 },
  }),
}) as unknown as Response;

const renderAlertDesk = (showToast = vi.fn()) => render(
  <AlertDeskTab
    language="en"
    currentUsername="operator"
    showToast={showToast}
    activeAlertSection="alerts"
    onNavigateAlertSection={vi.fn()}
  />,
);

describe('AlertDeskTab search request control', () => {
  beforeEach(() => {
    localStorage.setItem('netops_token', 'test-token');
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    cleanup();
    localStorage.removeItem('netops_token');
    vi.unstubAllGlobals();
  });

  it('debounces rapid typing and ignores a stale response after a newer search completes', async () => {
    let resolveRouterSearch: ((value: Response) => void) | undefined;
    vi.mocked(fetch).mockImplementation((input) => {
      const search = new URL(String(input), window.location.origin).searchParams.get('search') || '';
      if (search === '') return Promise.resolve(response('initial-alert'));
      if (search === 'router') {
        return new Promise<Response>((resolve) => { resolveRouterSearch = resolve; });
      }
      if (search === 'switch') return Promise.resolve(response('switch-result'));
      return Promise.resolve(response(`unexpected-${search}`));
    });

    renderAlertDesk();
    await screen.findByText('initial-alert');
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));

    const searchInput = screen.getByRole('searchbox', { name: 'Search alert title, device, interface, or IP' });
    fireEvent.change(searchInput, { target: { value: 'r' } });
    fireEvent.change(searchInput, { target: { value: 'rou' } });
    fireEvent.change(searchInput, { target: { value: 'router' } });

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2), { timeout: 1000 });
    expect(new URL(String(vi.mocked(fetch).mock.calls[1][0]), window.location.origin).searchParams.get('search')).toBe('router');
    expect(resolveRouterSearch).toBeTypeOf('function');

    fireEvent.change(searchInput, { target: { value: 'switch' } });
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3), { timeout: 1000 });
    await screen.findByText('switch-result');

    await act(async () => {
      resolveRouterSearch?.(response('stale-router-result'));
    });
    expect(screen.getByText('switch-result')).toBeTruthy();
    expect(screen.queryByText('stale-router-result')).toBeNull();
  });
});
